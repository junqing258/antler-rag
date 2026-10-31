"""业务 chunk 与框架节点之间的无损映射。"""

from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

from rag.chunking import CHUNKER_VERSIONS


def draft_node(
    draft, *, knowledge_base_id, document_id, filename, digest, chunk_index, chunk_strategy
):
    metadata = {
        **draft.chroma_metadata(),
        "chunk_strategy": chunk_strategy,
        "chunker_version": CHUNKER_VERSIONS[chunk_strategy],
        "knowledge_base_id": knowledge_base_id,
        "document_id": document_id,
        "filename": filename,
        "sha256": digest,
        "chunk_index": chunk_index,
    }
    return TextNode(
        id_=f"{document_id}:{chunk_index}",
        text=draft.content,
        metadata=metadata,
        excluded_embed_metadata_keys=list(metadata),
        excluded_llm_metadata_keys=list(metadata),
        relationships={NodeRelationship.SOURCE: RelatedNodeInfo(node_id=document_id)},
    )
