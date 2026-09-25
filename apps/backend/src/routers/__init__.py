"""HTTP route modules, grouped by resource rather than application lifecycle."""

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
