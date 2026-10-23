import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator, Dict, List
from unittest.mock import AsyncMock, patch
import uuid

import httpx
import pytest
import pytest_asyncio
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app
from app.models.chat import ChatMessage, ChatSession
from app.models.file import DocumentFile, FileStatus
from app.models.user import User
from app.services.qdrant_service import build_user_filter, init_qdrant_collection, search_documents
from app.workers.ingestion_worker import process_file_event

settings = get_settings()


class InMemoryRedisMock:
    """Async in-memory key-value store and Pub/Sub simulating Redis in tests."""

    def __init__(self):
        self.store: Dict[str, tuple] = {}
        self.channels: Dict[str, List[asyncio.Queue]] = {}

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

    async def publish(self, channel: str, message: str) -> int:
        subs = self.channels.get(channel, [])
        for q in subs:
            await q.put({"type": "message", "channel": channel, "data": message})
        return len(subs)

    def pubsub(self):
        return MockPubSub(self)

    async def aclose(self) -> None:
        self.store.clear()
        self.channels.clear()


class MockPubSub:
    """Mock Redis PubSub subscriber object with async queues."""

    def __init__(self, redis_mock: InMemoryRedisMock):
        self.redis = redis_mock
        self.subscribed_channels = set()
        self.queue: asyncio.Queue = asyncio.Queue()

    async def subscribe(self, *channels: str):
        for ch in channels:
            self.subscribed_channels.add(ch)
            if ch not in self.redis.channels:
                self.redis.channels[ch] = []
            self.redis.channels[ch].append(self.queue)

    async def unsubscribe(self, *channels: str):
        for ch in channels:
            self.subscribed_channels.discard(ch)
            if ch in self.redis.channels and self.queue in self.redis.channels[ch]:
                self.redis.channels[ch].remove(self.queue)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 0.5):
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def aclose(self):
        for ch in list(self.subscribed_channels):
            await self.unsubscribe(ch)


async def parse_sse_stream(response: httpx.Response) -> List[Dict[str, any]]:
    """Parse raw text/event-stream response into a structured list of event dicts."""
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


@pytest_asyncio.fixture(scope="function")
async def e2e_test_env(tmp_path: Path):
    """Provide isolated SQLite database, in-memory Qdrant client, Redis mock, and Kafka event capture."""
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

    # Capture Kafka published events
    published_events: List[Dict[str, any]] = []

    async def mock_publish_file_uploaded(**kwargs):
        payload = {
            "file_id": str(kwargs.get("file_id")),
            "user_id": str(kwargs.get("user_id")),
            "file_path": str(kwargs.get("file_path")),
            "filename": kwargs.get("filename"),
        }
        published_events.append(payload)
        return payload

    with (
        patch("app.core.security.get_redis_client", return_value=mock_redis),
        patch("app.core.redis.get_redis_client", return_value=mock_redis),
        patch("app.api.v1.files.get_redis_client", return_value=mock_redis),
        patch("app.api.v1.chat.get_redis_client", return_value=mock_redis),
        patch("app.workers.ingestion_worker.get_redis_client", return_value=mock_redis),
        patch("app.core.qdrant.get_qdrant_client", return_value=qdrant_mem_client),
        patch("app.services.qdrant_service.get_qdrant_client", return_value=qdrant_mem_client),
        patch("app.workers.ingestion_worker.get_qdrant_client", return_value=qdrant_mem_client),
        patch("app.api.v1.files.publish_file_uploaded", side_effect=mock_publish_file_uploaded),
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
                "published_events": published_events,
            }

    app.dependency_overrides.clear()
    await qdrant_mem_client.close()
    await engine.dispose()


async def register_and_login_user(
    client: httpx.AsyncClient, email: str, full_name: str
) -> tuple[str, str]:
    """Helper to register and login a user, returning access_token and user_id."""
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": full_name},
    )
    assert res.status_code == 201
    user_id = res.json()["id"]

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    return token, user_id


@pytest.mark.asyncio
async def test_stage7_complete_multi_user_e2e_journey(e2e_test_env: dict):
    """
    Simulate complete multi-user real-world journey:
    - Step 1: Register and authenticate User A and User B.
    - Step 2: User A uploads a document containing 'The internal codename for KafMind core is PROJECT-OMEGA-99'.
    - Step 3: Run the Kafka ingestion worker until the file status is READY in PostgreSQL and vectors are indexed in Qdrant.
    - Step 4: User A asks 'What is the internal codename for KafMind core?' via SSE and receives 'PROJECT-OMEGA-99' with valid citations.
    - Step 5 (Multi-tenant Isolation Check): User B asks the exact same question in their own session and is strictly prevented
      from retrieving User A's document chunks from Qdrant.
    """
    client: httpx.AsyncClient = e2e_test_env["client"]
    session_maker = e2e_test_env["session_maker"]
    qdrant: AsyncQdrantClient = e2e_test_env["qdrant"]
    redis: InMemoryRedisMock = e2e_test_env["redis"]
    published_events: List[Dict[str, any]] = e2e_test_env["published_events"]

    # =========================================================================
    # STEP 1: Register and authenticate User A and User B
    # =========================================================================
    token_a, user_a_id = await register_and_login_user(client, "user_a@example.com", "User A")
    token_b, user_b_id = await register_and_login_user(client, "user_b@example.com", "User B")

    assert user_a_id != user_b_id
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # =========================================================================
    # STEP 2: User A uploads document with confidential codename
    # =========================================================================
    confidential_doc_text = (
        "CONFIDENTIAL SPECIFICATION - FOR AUTHORIZED EYES ONLY\n"
        "Project Architecture & Systems Overview:\n"
        "The internal codename for KafMind core is PROJECT-OMEGA-99.\n"
        "All engineers working on the asynchronous event streaming ingestion pipeline\n"
        "must reference PROJECT-OMEGA-99 in all telemetry tags."
    )
    doc_bytes = confidential_doc_text.encode("utf-8")
    filename = "kafmind_core_specs.txt"

    upload_response = await client.post(
        "/api/v1/files/upload",
        files={"file": (filename, doc_bytes, "text/plain")},
        headers=headers_a,
    )
    assert upload_response.status_code == 202
    upload_data = upload_response.json()
    assert upload_data["message"] == "File upload accepted and queued for processing"
    file_id = upload_data["file_id"]

    # Verify PENDING status in initial response and DB
    assert upload_data["file"]["status"] == FileStatus.PENDING.value
    async with session_maker() as session:
        db_file = await session.get(DocumentFile, uuid.UUID(file_id))
        assert db_file is not None
        assert db_file.status == FileStatus.PENDING.value
        assert db_file.user_id == uuid.UUID(user_a_id)

    # Verify Kafka event published
    assert len(published_events) == 1
    kafka_event = published_events[0]
    assert kafka_event["file_id"] == file_id
    assert kafka_event["user_id"] == user_a_id
    assert kafka_event["filename"] == filename

    # =========================================================================
    # STEP 3: Run the Kafka ingestion worker until READY and indexed in Qdrant
    # =========================================================================
    async with session_maker() as session:
        await process_file_event(
            event=kafka_event,
            db_session=session,
            redis_client=redis,
            qdrant_client=qdrant,
        )

    # Verify PostgreSQL file record updated to READY with chunk count
    async with session_maker() as session:
        db_file_ready = await session.get(DocumentFile, uuid.UUID(file_id))
        assert db_file_ready.status == FileStatus.READY.value
        assert db_file_ready.chunk_count > 0
        assert db_file_ready.error_message is None

    # Verify Qdrant points indexed with multi-tenant payload (user_id and file_id)
    user_a_filter = build_user_filter(user_id=user_a_id)
    search_res = await qdrant.scroll(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        scroll_filter=user_a_filter,
        limit=10,
        with_payload=True,
    )
    points, _ = search_res
    assert len(points) > 0
    assert any("PROJECT-OMEGA-99" in p.payload.get("text", "") for p in points)
    assert all(p.payload.get("user_id") == user_a_id for p in points)
    assert all(p.payload.get("file_id") == file_id for p in points)

    # =========================================================================
    # STEP 4: User A asks for the codename via SSE stream and receives citations
    # =========================================================================
    # User A creates a chat session
    create_session_a = await client.post(
        "/api/v1/chat/sessions",
        headers=headers_a,
        json={"title": "User A Inquiries"},
    )
    assert create_session_a.status_code == 201
    session_a_id = create_session_a.json()["id"]

    query = "What is the internal codename for KafMind core?"
    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_a_id}/stream",
        headers=headers_a,
        json={"message": query},
    ) as stream_a:
        assert stream_a.status_code == 200
        events_a = await parse_sse_stream(stream_a)

    event_names_a = [e.get("event") for e in events_a]
    assert "agent_step" in event_names_a
    assert "sources" in event_names_a
    assert "done" in event_names_a

    # Check source citations
    sources_event = [e for e in events_a if e.get("event") == "sources"][0]
    sources_list = sources_event["data"]["sources"]
    assert len(sources_list) > 0
    assert any(s["file_id"] == file_id for s in sources_list)
    assert any(s["filename"] == filename for s in sources_list)

    # Verify answer contains the confidential codename
    done_event_a = [e for e in events_a if e.get("event") == "done"][0]
    full_answer_a = done_event_a["data"]["content"]
    assert "PROJECT-OMEGA-99" in full_answer_a

    # Verify database persistence of User A message with sources
    async with session_maker() as session:
        res = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == uuid.UUID(session_a_id))
            .where(ChatMessage.role == "assistant")
        )
        saved_assistant_a = res.scalar_one()
        assert "PROJECT-OMEGA-99" in saved_assistant_a.content
        assert saved_assistant_a.sources is not None
        assert len(saved_assistant_a.sources) > 0
        assert saved_assistant_a.sources[0]["file_id"] == file_id

    # =========================================================================
    # STEP 5: Multi-tenant Isolation Check - User B asks the exact same question
    # =========================================================================
    create_session_b = await client.post(
        "/api/v1/chat/sessions",
        headers=headers_b,
        json={"title": "User B Session"},
    )
    assert create_session_b.status_code == 201
    session_b_id = create_session_b.json()["id"]

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_b_id}/stream",
        headers=headers_b,
        json={"message": query},
    ) as stream_b:
        assert stream_b.status_code == 200
        events_b = await parse_sse_stream(stream_b)

    # User B MUST NOT receive User A's sources
    sources_events_b = [e for e in events_b if e.get("event") == "sources"]
    if sources_events_b:
        sources_b = sources_events_b[0]["data"].get("sources", [])
        assert len(sources_b) == 0, "User B leaked sources belonging to User A!"

    # User B's answer MUST NOT contain User A's private codename
    done_event_b = [e for e in events_b if e.get("event") == "done"][0]
    full_answer_b = done_event_b["data"]["content"]
    assert "PROJECT-OMEGA-99" not in full_answer_b

    # Direct database verification for User B assistant message
    async with session_maker() as session:
        res = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == uuid.UUID(session_b_id))
            .where(ChatMessage.role == "assistant")
        )
        saved_assistant_b = res.scalar_one()
        assert "PROJECT-OMEGA-99" not in saved_assistant_b.content
        assert saved_assistant_b.sources is None or len(saved_assistant_b.sources) == 0

    # Direct Qdrant query check for User B: strictly 0 points retrieved
    user_b_filter = build_user_filter(user_id=user_b_id)
    search_res_b = await qdrant.scroll(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        scroll_filter=user_b_filter,
        limit=10,
    )
    points_b, _ = search_res_b
    assert len(points_b) == 0, "User B retrieved vector points belonging to another user!"

    # Defense-in-depth: Even if User B explicitly passes User A's file_id in selected_file_ids
    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_b_id}/stream",
        headers=headers_b,
        json={"message": query, "selected_file_ids": [file_id]},
    ) as malicious_attempt_stream:
        assert malicious_attempt_stream.status_code == 200
        malicious_events = await parse_sse_stream(malicious_attempt_stream)

    malicious_sources = [e for e in malicious_events if e.get("event") == "sources"]
    if malicious_sources:
        assert len(malicious_sources[0]["data"].get("sources", [])) == 0
    malicious_done = [e for e in malicious_events if e.get("event") == "done"][0]
    assert "PROJECT-OMEGA-99" not in malicious_done["data"]["content"]
