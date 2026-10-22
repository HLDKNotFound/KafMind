import asyncio
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from qdrant_client import AsyncQdrantClient

from app.agent.graph import app_graph
from app.agent.nodes import (
    generate_node,
    grade_documents_node,
    retrieve_node,
    rewrite_query_node,
    router_node,
)
from app.agent.state import AgentState
from app.core.config import get_settings
from app.services.qdrant_service import (
    init_qdrant_collection,
    search_documents,
    upsert_document_chunks,
)

settings = get_settings()


@pytest_asyncio.fixture(scope="function")
async def in_memory_qdrant() -> AsyncGenerator[AsyncQdrantClient, None]:
    """Provide a fresh in-memory Qdrant client with initialized kafmind_documents collection."""
    client = AsyncQdrantClient(":memory:")
    await init_qdrant_collection(client)
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_direct_routing_chitchat_without_qdrant():
    """Verify general chitchat routes directly to generate_node without querying Qdrant."""
    user_id = str(uuid.uuid4())
    state: AgentState = {
        "messages": [HumanMessage(content="Hello! Who are you and how can you help me?")],
        "user_id": user_id,
        "selected_file_ids": None,
        "retrieved_docs": [],
        "rewrite_count": 0,
        "custom_system_prompt": None,
    }

    with patch("app.agent.nodes.search_documents", new_callable=AsyncMock) as mock_search:
        result = await app_graph.ainvoke(state)

        # Qdrant search must NOT have been called for conversational chitchat
        mock_search.assert_not_called()
        assert result.get("router_decision") == "direct"
        assert len(result.get("retrieved_docs", [])) == 0

        # Graph returns assistant message
        assert len(result["messages"]) >= 2
        last_message = result["messages"][-1]
        assert isinstance(last_message, AIMessage)
        assert len(str(last_message.content).strip()) > 0


@pytest.mark.asyncio
async def test_document_retrieval_multi_tenant_isolation_and_citations(in_memory_qdrant: AsyncQdrantClient):
    """Verify document-specific queries route through retrieve_node, enforce user_id isolation, and cite sources."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    file_a_id = str(uuid.uuid4())
    filename_a = "cloud_security_policy.pdf"
    chunks_a = [
        "KafMind strictly enforces AES-256-GCM encryption for all stored files and database backups.",
        "Access tokens expire after 30 minutes and refresh tokens rotate every 7 days.",
    ]
    await upsert_document_chunks(
        user_id=user_a,
        file_id=file_a_id,
        filename=filename_a,
        chunks=chunks_a,
        client=in_memory_qdrant,
    )

    file_b_id = str(uuid.uuid4())
    filename_b = "confidential_project_neptune.pdf"
    chunks_b = [
        "Project Neptune is Top Secret. Only User B has authorization to view project blueprints.",
    ]
    await upsert_document_chunks(
        user_id=user_b,
        file_id=file_b_id,
        filename=filename_b,
        chunks=chunks_b,
        client=in_memory_qdrant,
    )

    with patch("app.services.qdrant_service.get_qdrant_client", return_value=in_memory_qdrant):
        # 1. User A queries their own document
        state_a: AgentState = {
            "messages": [
                HumanMessage(
                    content="What encryption algorithm is enforced for stored files according to cloud_security_policy.pdf?"
                )
            ],
            "user_id": user_a,
            "selected_file_ids": None,
            "retrieved_docs": [],
            "rewrite_count": 0,
            "custom_system_prompt": None,
        }

        result_a = await app_graph.ainvoke(state_a)

        assert result_a.get("router_decision") == "retrieve"
        retrieved_docs_a = result_a.get("retrieved_docs", [])
        assert len(retrieved_docs_a) > 0

        # Multi-tenant check: all retrieved documents must belong to User A
        for doc in retrieved_docs_a:
            assert doc["file_id"] == file_a_id
            assert doc["filename"] == filename_a
            assert doc["file_id"] != file_b_id

        # Response check: verify answer contains inline source citation format [filename:chunk_index]
        last_message_a = result_a["messages"][-1]
        assert isinstance(last_message_a, AIMessage)
        content_a = str(last_message_a.content)
        assert "AES-256" in content_a or "encryption" in content_a.lower()
        assert f"[{filename_a}:" in content_a or f"[{filename_a}" in content_a

        # 2. Strict multi-tenant isolation check: User A attempts to search for User B's confidential project
        search_spy_results = await search_documents(
            user_id=user_a,
            query_text="Project Neptune blueprints",
            client=in_memory_qdrant,
        )
        # Even if nearest-neighbors from User A are returned, User B's vectors are NEVER exposed
        assert not any(doc["file_id"] == file_b_id for doc in search_spy_results)
        assert not any("neptune" in doc["text"].lower() for doc in search_spy_results)

        # 3. User B querying Project Neptune retrieves their own confidential document
        search_b_results = await search_documents(
            user_id=user_b,
            query_text="Project Neptune blueprints",
            client=in_memory_qdrant,
        )
        assert len(search_b_results) > 0
        assert all(doc["file_id"] == file_b_id for doc in search_b_results)
        assert all(doc["filename"] == filename_b for doc in search_b_results)
        assert any("neptune" in doc["text"].lower() for doc in search_b_results)


@pytest.mark.asyncio
async def test_selected_file_ids_filtering(in_memory_qdrant: AsyncQdrantClient):
    """Verify that specifying selected_file_ids strictly restricts retrieved chunks to those files."""
    user_id = str(uuid.uuid4())
    file_1 = str(uuid.uuid4())
    file_2 = str(uuid.uuid4())

    await upsert_document_chunks(
        user_id=user_id,
        file_id=file_1,
        filename="accounting_2025.txt",
        chunks=["Q1 net revenue was 5.2 million USD with 18 percent year-over-year growth."],
        client=in_memory_qdrant,
    )
    await upsert_document_chunks(
        user_id=user_id,
        file_id=file_2,
        filename="hr_manual.txt",
        chunks=["Employees receive 25 days of paid time off each calendar year."],
        client=in_memory_qdrant,
    )

    with patch("app.services.qdrant_service.get_qdrant_client", return_value=in_memory_qdrant):
        # Query with selected_file_ids restricted to file_1
        docs_file_1 = await search_documents(
            user_id=user_id,
            query_text="What was Q1 revenue?",
            selected_file_ids=[file_1],
            client=in_memory_qdrant,
        )
        assert len(docs_file_1) > 0
        for doc in docs_file_1:
            assert doc["file_id"] == file_1
            assert doc["file_id"] != file_2

        # Query with selected_file_ids restricted to file_2
        docs_file_2 = await search_documents(
            user_id=user_id,
            query_text="What was Q1 revenue?",
            selected_file_ids=[file_2],
            client=in_memory_qdrant,
        )
        for doc in docs_file_2:
            assert doc["file_id"] == file_2
            assert doc["file_id"] != file_1


@pytest.mark.asyncio
async def test_query_rewriter_flow():
    """Verify that rewrite_query_node increments rewrite_count and updates search_query."""
    user_id = str(uuid.uuid4())
    state: AgentState = {
        "messages": [HumanMessage(content="Where is the data stored?")],
        "user_id": user_id,
        "selected_file_ids": None,
        "retrieved_docs": [],
        "rewrite_count": 0,
        "search_query": None,
        "custom_system_prompt": None,
    }

    # Execute rewrite_query_node
    update = await rewrite_query_node(state)
    assert update["rewrite_count"] == 1
    assert update["search_query"] is not None
    assert len(update["search_query"].strip()) > 0

    # Ensure second iteration increments count to 2
    state["rewrite_count"] = 1
    state["search_query"] = update["search_query"]
    second_update = await rewrite_query_node(state)
    assert second_update["rewrite_count"] == 2


@pytest.mark.asyncio
async def test_custom_system_prompt_influence():
    """Verify that custom_system_prompt is passed and adhered to by generate_node."""
    custom_persona = "You are a medieval knight. Always start your response with 'Hark, noble traveler!'"
    state: AgentState = {
        "messages": [HumanMessage(content="Can you introduce yourself?")],
        "user_id": str(uuid.uuid4()),
        "selected_file_ids": None,
        "retrieved_docs": [],
        "rewrite_count": 0,
        "custom_system_prompt": custom_persona,
    }

    result = await generate_node(state)
    response_msg = result["messages"][0]
    content = str(response_msg.content).lower()
    assert "hark" in content or "traveler" in content or "noble" in content or "knight" in content


@pytest.mark.asyncio
async def test_astream_events_v2_token_streaming():
    """Verify token streaming via .astream_events(version='v2') emits chat model stream chunks."""
    state: AgentState = {
        "messages": [HumanMessage(content="hi")],
        "user_id": str(uuid.uuid4()),
        "selected_file_ids": None,
        "retrieved_docs": [],
        "rewrite_count": 0,
        "custom_system_prompt": None,
    }

    streamed_events = []
    streamed_chunks = []

    async for event in app_graph.astream_events(state, version="v2"):
        event_name = event.get("event")
        streamed_events.append(event_name)

        if event_name == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                streamed_chunks.append(chunk.content)

    # Verify standard LangGraph v2 lifecycle events occurred
    assert "on_chain_start" in streamed_events
    assert "on_chain_end" in streamed_events

    # Verify streamed tokens were received
    assert len(streamed_chunks) > 0
    full_text = "".join(streamed_chunks).strip()
    assert len(full_text) > 0
