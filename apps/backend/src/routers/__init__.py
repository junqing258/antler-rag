"""HTTP 路由模块，按资源而非应用生命周期分组。"""

from . import admin, agentic, auth, documents, graph, health, knowledge_bases, retrieval

ALL_ROUTERS = (
    health.router,
    auth.router,
    admin.router,
    knowledge_bases.router,
    documents.router,
    retrieval.router,
    agentic.router,
    graph.router,
)

__all__ = ["ALL_ROUTERS"]
