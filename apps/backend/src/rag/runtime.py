"""由应用持有的 RAG 实例，不设置进程级的框架全局配置。"""

from dataclasses import dataclass

from rag.agentic import AgentService
from rag.retrieval import RetrievalService
from rag.store import RAGStore


@dataclass
class RAGRuntime:
    store: RAGStore
    retrieval: RetrievalService
    agent: AgentService

    @classmethod
    def create(cls, settings, store_factory):
        store = store_factory(settings)
        retrieval = RetrievalService.from_store(store)
        return cls(store, retrieval, AgentService(retrieval, settings))

    def close(self):
        self.store.close()
