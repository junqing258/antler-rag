from antler_rag.app import ChatRequest


def test_chat_request_accepts_message_and_query() -> None:
    base = {"knowledge_base_id": "knowledge-base", "top_k": 5}

    assert ChatRequest.model_validate({**base, "message": "What tools are available?"}).query == "What tools are available?"
    assert ChatRequest.model_validate({**base, "query": "What tools are available?"}).query == "What tools are available?"
