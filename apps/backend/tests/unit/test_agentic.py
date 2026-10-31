import asyncio

from core.config import Settings
from rag.agentic import AgentService
from rag.retrieval import Evidence


class FakeRetrievalService:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, **kwargs: object) -> list[Evidence]:
        query = str(kwargs["query"])
        self.queries.append(query)
        return [
            Evidence(
                evidence_id=f"vector:{query}:0",
                knowledge_base_id="kb",
                document_id="doc",
                chunk_id=f"{query}:0",
                chunk_index=0,
                filename="synthetic.md",
                content="Synthetic source",
                source_type="vector",
                score=0.9,
            )
        ]


class FakeAgent(AgentService):
    def __init__(self, retrieval: FakeRetrievalService, settings: Settings, responses: list[str]):
        super().__init__(retrieval, settings)  # type: ignore[arg-type]
        self.responses = responses

    async def _completion(self, messages: list[dict[str, str]]) -> str:
        return self.responses.pop(0)


def configured_settings(**kwargs: object) -> Settings:
    return Settings(
        llm_base_url="https://llm.example.test",
        llm_api_key="test-key",
        chat_model="test-model",
        **kwargs,
    )


def test_agent_only_runs_allowlisted_vector_queries_with_server_budget() -> None:
    retrieval = FakeRetrievalService()
    agent = FakeAgent(
        retrieval,
        configured_settings(agent_max_subqueries=2),
        ['{"subqueries":["follow-up", "third query", "ignored"]}', "Grounded answer"],
    )

    result = asyncio.run(
        agent.answer(knowledge_base_id="kb", message="original", top_k=3, mode="auto")
    )

    assert result.answer == "Grounded answer"
    assert retrieval.queries == ["original", "follow-up"]
    assert [step.tool for step in result.trace if step.tool] == [
        "vector_search",
        "vector_search",
    ]
    assert all(
        "Synthetic source" not in evidence_id
        for step in result.trace
        for evidence_id in step.evidence_ids
    )


def test_invalid_planner_output_stops_agent_and_returns_one_vector_fallback() -> None:
    retrieval = FakeRetrievalService()
    agent = FakeAgent(retrieval, configured_settings(), ["not valid JSON"])

    result = asyncio.run(
        agent.answer(knowledge_base_id="kb", message="original", top_k=3, mode="auto")
    )

    assert result.answer is None
    assert result.detail == "Planner failed; returned vector sources."
    assert retrieval.queries == ["original"]
    assert result.trace[-1].error_code == "planner_failed"


def test_minimum_budget_returns_original_without_model_call():
    retrieval = FakeRetrievalService()
    agent = FakeAgent(retrieval, configured_settings(agent_max_steps=1, agent_max_llm_calls=0), [])
    result = asyncio.run(
        agent.answer(knowledge_base_id="kb", message="original", top_k=3, mode="auto")
    )
    assert result.answer is None and result.evidence
    assert result.detail == "budget_exhausted"
    assert retrieval.queries == ["original"]
    assert result.trace[-1].error_code == "budget_exhausted"


def test_last_step_answer_failure_reuses_original_sources():
    class FailingAnswer(FakeAgent):
        async def _generate_answer(self, message, evidence):
            raise ValueError("bad response")

    retrieval = FakeRetrievalService()
    agent = FailingAnswer(
        retrieval, configured_settings(agent_max_steps=3), ['{"subqueries":["extra"]}']
    )
    result = asyncio.run(
        agent.answer(knowledge_base_id="kb", message="original", top_k=3, mode="auto")
    )
    assert result.answer is None
    assert result.detail == "LLM failed; returned vector sources."
    assert retrieval.queries == ["original"]
    assert result.trace[-1].error_code == "llm_failed"


def test_overall_deadline_during_planner_and_concurrent_state_isolation():
    class SlowAgent(FakeAgent):
        async def _plan(self, message):
            await asyncio.sleep(0.08)
            return ["extra"]

    retrieval = FakeRetrievalService()
    settings = configured_settings().model_copy(update={"agent_timeout_seconds": 0.02})
    agent = SlowAgent(retrieval, settings, [])

    async def scenario():
        return await asyncio.gather(
            *[
                agent.answer(knowledge_base_id="kb", message=q, top_k=3, mode="auto")
                for q in ["one", "two"]
            ]
        )

    results = asyncio.run(scenario())
    assert [r.detail for r in results] == ["timeout", "timeout"]
    assert [r.evidence[0].chunk_id for r in results] == ["one:0", "two:0"]
    assert sorted(retrieval.queries) == ["one", "two"]


def test_first_retrieval_timeout_has_no_late_mutation():
    import time

    class SlowRetrieval(FakeRetrievalService):
        def retrieve(self, **kwargs):
            time.sleep(0.05)
            return super().retrieve(**kwargs)

    retrieval = SlowRetrieval()
    agent = FakeAgent(
        retrieval, configured_settings().model_copy(update={"agent_timeout_seconds": 0.01}), []
    )

    async def scenario():
        result = await agent.answer(
            knowledge_base_id="kb", message="original", top_k=3, mode="auto"
        )
        assert result.detail == "timeout" and result.evidence == []
        trace = result.trace
        await asyncio.sleep(0.1)
        assert result.evidence == [] and result.trace == trace

    asyncio.run(scenario())
