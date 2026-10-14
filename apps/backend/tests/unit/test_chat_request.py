import pytest
from pydantic import ValidationError

from models.schemas import ChatRequest


def test_chat_request_requires_message():
    base = {"knowledge_base_id": "knowledge-base", "top_k": 5}
    assert (
        ChatRequest.model_validate({**base, "message": "What tools are available?"}).message
        == "What tools are available?"
    )
    with pytest.raises(ValidationError, match="message"):
        ChatRequest.model_validate({**base, "query": "What tools are available?"})


def test_chat_request_accepts_retrieval_tuning_parameters() -> None:
    request = ChatRequest.model_validate(
        {
            "knowledge_base_id": "knowledge-base",
            "message": "What tools are available?",
            "score_threshold": 0.7,
            "rerank": True,
        }
    )

    assert request.score_threshold == 0.7
    assert request.rerank is True
