import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator, Dict, List
from unittest.mock import AsyncMock, patch
import uuid

import httpx
import pytest
import pytest_asyncio
from qdrant_client import AsyncQdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.services.qdrant_service import init_qdrant_collection, upsert_document_chunks

settings = get_settings()


class InMemoryRedisMock:
    """Async in-memory key-value store simulating Redis for blacklist operations."""

    def __init__(self):
        self.store: Dict[str, tuple] = {}

    async def setex(self, key: str, time_secs: int, value: str) -> bool:
        self.store[key] = (value, asyncio.get_event_loop().time() + time_secs)
        return True

    async def exists(self, key: str) -> int:
        if key in self.store:
            _, exp = self.store[key]
            if asyncio.get_event_loop().time() < exp:
                return 1
            del self.store[key]
        return 0

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.store.clear()


@pytest_asyncio.fixture(scope="function")
async def chat_test_env():
    """Provide isolated SQLite database, in-memory Qdrant client, and Redis mock for Stage 5 tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            try:
                yield session
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    mock_redis = InMemoryRedisMock()
    qdrant_mem_client = AsyncQdrantClient(":memory:")
    await init_qdrant_collection(qdrant_mem_client)

    with (
        patch("app.core.security.get_redis_client", return_value=mock_redis),
        patch("app.api.v1.chat.get_redis_client", return_value=mock_redis),
        patch("app.core.qdrant.get_qdrant_client", return_value=qdrant_mem_client),
        patch("app.services.qdrant_service.get_qdrant_client", return_value=qdrant_mem_client),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield {
                "client": client,
                "session_maker": session_maker,
                "redis": mock_redis,
                "qdrant": qdrant_mem_client,
            }

    app.dependency_overrides.clear()
    await qdrant_mem_client.close()
    await engine.dispose()


async def register_and_login(client: httpx.AsyncClient, email: str = "chat_user@example.com") -> tuple[str, str]:
    """Helper to register and login a user, returning access_token and user_id."""
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": "Chat User"},
    )
    user_id = res.json()["id"]

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    token = login_res.json()["access_token"]
    return token, user_id


async def parse_sse_stream(response: httpx.Response) -> List[Dict[str, any]]:
    """Parse raw text/event-stream response into list of event dicts."""
    events = []
    current_event = {}

    async for line in response.aiter_lines():
        line = line.strip()
        if not line:
            if current_event:
                events.append(current_event)
                if current_event.get("event") in ("done", "error"):
                    current_event = {}
                    break
                current_event = {}
            continue
        if line.startswith("event:"):
            current_event["event"] = line.split("event:", 1)[1].strip()
        elif line.startswith("data:"):
            data_raw = line.split("data:", 1)[1].strip()
            try:
                current_event["data"] = json.loads(data_raw)
            except Exception:
                current_event["data"] = data_raw

    if current_event:
        events.append(current_event)

    return events


@pytest.mark.asyncio
async def test_session_crud_and_multi_tenant(chat_test_env: dict):
    """Verify ChatSession creation, listing, retrieval, multi-tenant isolation, and deletion."""
    client: httpx.AsyncClient = chat_test_env["client"]
    token_a, user_a_id = await register_and_login(client, "user_a@example.com")
    token_b, user_b_id = await register_and_login(client, "user_b@example.com")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. User A creates session with custom title
    res_a1 = await client.post(
        "/api/v1/chat/sessions",
        headers=headers_a,
        json={"title": "Q3 Financials Planning"},
    )
    assert res_a1.status_code == 201
    data_a1 = res_a1.json()
    session_a1_id = data_a1["id"]
    assert data_a1["title"] == "Q3 Financials Planning"
    assert data_a1["user_id"] == user_a_id

    # 2. User A creates session with default title
    res_a2 = await client.post(
        "/api/v1/chat/sessions",
        headers=headers_a,
        json={},
    )
    assert res_a2.status_code == 201
    assert res_a2.json()["title"] == "New Chat"

    # 3. User B creates session
    res_b = await client.post(
        "/api/v1/chat/sessions",
        headers=headers_b,
        json={"title": "HR Policies Discussion"},
    )
    assert res_b.status_code == 201
    session_b_id = res_b.json()["id"]

    # 4. Multi-tenant list: User A gets only their 2 sessions
    list_a = await client.get("/api/v1/chat/sessions", headers=headers_a)
    assert list_a.status_code == 200
    sessions_a = list_a.json()
    assert len(sessions_a) == 2
    assert all(s["user_id"] == user_a_id for s in sessions_a)

    # User B gets only their 1 session
    list_b = await client.get("/api/v1/chat/sessions", headers=headers_b)
    assert list_b.status_code == 200
    sessions_b = list_b.json()
    assert len(sessions_b) == 1
    assert sessions_b[0]["id"] == session_b_id

    # 5. Get messages for empty session
    msg_res = await client.get(f"/api/v1/chat/sessions/{session_a1_id}/messages", headers=headers_a)
    assert msg_res.status_code == 200
    assert msg_res.json() == []

    # 6. Multi-tenant isolation: User A cannot access User B's session messages
    unauth_msg = await client.get(f"/api/v1/chat/sessions/{session_b_id}/messages", headers=headers_a)
    assert unauth_msg.status_code == 404

    # 7. Multi-tenant isolation: User A cannot delete User B's session
    unauth_del = await client.delete(f"/api/v1/chat/sessions/{session_b_id}", headers=headers_a)
    assert unauth_del.status_code == 404

    # 8. User A deletes their session
    del_res = await client.delete(f"/api/v1/chat/sessions/{session_a1_id}", headers=headers_a)
    assert del_res.status_code == 200

    # Verify session is gone
    check_del = await client.get(f"/api/v1/chat/sessions/{session_a1_id}/messages", headers=headers_a)
    assert check_del.status_code == 404


@pytest.mark.asyncio
async def test_chat_stream_sse_endpoint_chitchat(chat_test_env: dict):
    """Verify POST /api/v1/chat/sessions/{session_id}/stream streams SSE events and saves messages."""
    client: httpx.AsyncClient = chat_test_env["client"]
    session_maker = chat_test_env["session_maker"]

    token, user_id = await register_and_login(client, "stream_user@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create session
    create_res = await client.post("/api/v1/chat/sessions", headers=headers, json={"title": "New Chat"})
    session_id = create_res.json()["id"]

    # Stream SSE request
    user_query = "Hello! Who are you?"
    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/stream",
        headers=headers,
        json={"message": user_query},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        events = await parse_sse_stream(response)

    # Validate structured SSE events
    event_names = [e.get("event") for e in events]
    assert "agent_step" in event_names
    assert "token" in event_names
    assert "done" in event_names

    # Check agent_step payloads
    steps = [e["data"] for e in events if e.get("event") == "agent_step"]
    assert any(s.get("step") == "router_node" for s in steps)
    assert any(s.get("step") == "generate_node" for s in steps)

    # Check tokens
    tokens = [e["data"].get("token") for e in events if e.get("event") == "token" and isinstance(e.get("data"), dict)]
    full_assistant_text = "".join([t for t in tokens if t]).strip()
    assert len(full_assistant_text) > 0

    # Check done event
    done_events = [e for e in events if e.get("event") == "done"]
    assert len(done_events) == 1
    done_payload = done_events[0]["data"]
    assert "message_id" in done_payload
    assert done_payload["content"] == full_assistant_text

    # Verify PostgreSQL (SQLite in test) persistence of both user and assistant messages
    async with session_maker() as db:
        res = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == uuid.UUID(session_id))
            .order_by(ChatMessage.created_at.asc())
        )
        saved_messages = res.scalars().all()
        assert len(saved_messages) == 2

        # 1. User message
        assert saved_messages[0].role == "user"
        assert saved_messages[0].content == user_query

        # 2. Assistant message
        assert saved_messages[1].role == "assistant"
        assert saved_messages[1].content == full_assistant_text
        assert str(saved_messages[1].id) == done_payload["message_id"]

        # Session title should be updated from "New Chat" to preview of first message
        db_session = await db.get(ChatSession, uuid.UUID(session_id))
        assert db_session.title != "New Chat"
        assert "Hello" in db_session.title


@pytest.mark.asyncio
async def test_chat_stream_multi_turn_history(chat_test_env: dict):
    """Verify multi-turn conversations persist history and pass previous context to the agent."""
    client: httpx.AsyncClient = chat_test_env["client"]
    token, _ = await register_and_login(client, "multiturn@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create session
    create_res = await client.post("/api/v1/chat/sessions", headers=headers, json={"title": "Multi-turn Chat"})
    session_id = create_res.json()["id"]

    # Turn 1
    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/stream",
        headers=headers,
        json={"message": "My favorite color is emerald green."},
    ) as response1:
        assert response1.status_code == 200
        events1 = await parse_sse_stream(response1)
        assert any(e.get("event") == "done" for e in events1)

    # Turn 2
    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/stream",
        headers=headers,
        json={"message": "What is my favorite color?"},
    ) as response2:
        assert response2.status_code == 200
        events2 = await parse_sse_stream(response2)
        done2 = [e for e in events2 if e.get("event") == "done"][0]
        # Agent should recall context from Turn 1
        content2 = done2["data"]["content"].lower()
        assert "emerald" in content2 or "green" in content2

    # Verify total 4 messages in session history
    msg_res = await client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
    assert msg_res.status_code == 200
    msgs = msg_res.json()
    assert len(msgs) == 4
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


@pytest.mark.asyncio
async def test_chat_stream_with_retrieval_and_sources(chat_test_env: dict):
    """Verify document query routes through Qdrant, streams sources, and persists sources into PostgreSQL."""
    client: httpx.AsyncClient = chat_test_env["client"]
    session_maker = chat_test_env["session_maker"]
    qdrant = chat_test_env["qdrant"]

    token, user_id = await register_and_login(client, "rag_user@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Index document chunk into Qdrant for this user
    file_id = str(uuid.uuid4())
    filename = "server_deployment_guide.pdf"
    chunks = [
        "The KafMind production cluster must run with 3 Kafka brokers and 1 KRaft controller node."
    ]
    await upsert_document_chunks(
        user_id=user_id,
        file_id=file_id,
        filename=filename,
        chunks=chunks,
        client=qdrant,
    )

    # Create session
    create_res = await client.post("/api/v1/chat/sessions", headers=headers, json={"title": "RAG Session"})
    session_id = create_res.json()["id"]

    # Stream query requiring document retrieval
    doc_query = f"According to {filename}, how many Kafka brokers must run in production?"
    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/stream",
        headers=headers,
        json={"message": doc_query, "selected_file_ids": [file_id]},
    ) as response:
        assert response.status_code == 200
        events = await parse_sse_stream(response)

    # Verify events
    event_names = [e.get("event") for e in events]
    assert "agent_step" in event_names
    assert "sources" in event_names
    assert "done" in event_names

    # Check sources event content
    sources_events = [e for e in events if e.get("event") == "sources"]
    assert len(sources_events) >= 1
    sources_data = sources_events[0]["data"]["sources"]
    assert len(sources_data) > 0
    assert sources_data[0]["file_id"] == file_id
    assert sources_data[0]["filename"] == filename

    # Verify persistence of sources in PostgreSQL ChatMessage
    async with session_maker() as db:
        res = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == uuid.UUID(session_id))
            .where(ChatMessage.role == "assistant")
        )
        assistant_msg = res.scalar_one()
        assert assistant_msg.sources is not None
        assert len(assistant_msg.sources) > 0
        assert assistant_msg.sources[0]["file_id"] == file_id


@pytest.mark.asyncio
async def test_chat_stream_unauthorized_and_invalid_session(chat_test_env: dict):
    """Verify 401 Unauthorized for missing token and 404 for accessing another user's session."""
    client: httpx.AsyncClient = chat_test_env["client"]
    token_a, _ = await register_and_login(client, "alice@example.com")
    token_b, _ = await register_and_login(client, "bob@example.com")

    # Alice creates a session
    res_a = await client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Alice Chat"},
    )
    alice_session_id = res_a.json()["id"]

    # Bob attempts to stream to Alice's session -> 404
    bob_stream = await client.post(
        f"/api/v1/chat/sessions/{alice_session_id}/stream",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"message": "Sneaking into Alice's session"},
    )
    assert bob_stream.status_code == 404

    # Unauthenticated stream -> 401
    unauth_stream = await client.post(
        f"/api/v1/chat/sessions/{alice_session_id}/stream",
        json={"message": "Unauthenticated access"},
    )
    assert unauth_stream.status_code == 401

    # Nonexistent session -> 404
    nonexistent = str(uuid.uuid4())
    fake_stream = await client.post(
        f"/api/v1/chat/sessions/{nonexistent}/stream",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"message": "Ghost session"},
    )
    assert fake_stream.status_code == 404


@pytest.mark.asyncio
async def test_cascade_delete_messages(chat_test_env: dict):
    """Verify that deleting a ChatSession cascades to delete all its ChatMessages."""
    client: httpx.AsyncClient = chat_test_env["client"]
    session_maker = chat_test_env["session_maker"]

    token, _ = await register_and_login(client, "cascade_user@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create session
    create_res = await client.post("/api/v1/chat/sessions", headers=headers, json={"title": "Cascade Test"})
    session_id = create_res.json()["id"]

    # Post a message via stream
    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/stream",
        headers=headers,
        json={"message": "Message to be cascaded"},
    ) as resp:
        await parse_sse_stream(resp)

    # Confirm messages exist in DB
    async with session_maker() as db:
        res = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session_id))
        )
        assert len(res.scalars().all()) == 2

    # Delete session
    del_res = await client.delete(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    assert del_res.status_code == 200

    # Verify messages are deleted
    async with session_maker() as db:
        res = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session_id))
        )
        assert len(res.scalars().all()) == 0
