from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.config import get_settings
from app.core.llm import get_chat_llm
from app.main import app


def test_env_config_loading():
    """Verify that .env configuration variables are loaded and validated correctly."""
    settings = get_settings()
    assert settings.APP_NAME == "KafMind"
    assert settings.LLM_MODEL_NAME == "deepseek-v4.1-flash:free"
    assert settings.TOKEN_HARBOR_BASE_URL == "https://tokenharbor.ai/v1"
    assert settings.EMBEDDING_MODEL_NAME == "BAAI/bge-small-en-v1.5"
    assert settings.EMBEDDING_DIMENSION == 384
    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert settings.REDIS_URL.startswith("redis://")
    assert settings.QDRANT_HOST == "localhost"
    assert settings.QDRANT_PORT == 6333
    assert settings.KAFKA_BOOTSTRAP_SERVERS in ["localhost:9092", "localhost:9094"]
    assert settings.KAFKA_TOPIC_FILE_UPLOADED == "file.uploaded"
    assert settings.KAFKA_TOPIC_FILE_STATUS == "file.status"
    assert isinstance(settings.CORS_ORIGINS, list)
    assert len(settings.CORS_ORIGINS) > 0


@pytest.mark.asyncio
async def test_health_endpoint_direct():
    """Test GET /api/v1/health returns 200 OK with services structure."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "services" in data
        assert "postgres" in data["services"]
        assert "redis" in data["services"]
        assert "qdrant" in data["services"]
        assert "kafka" in data["services"]


@pytest.mark.asyncio
async def test_health_endpoint_all_services_up():
    """Test GET /api/v1/health returns status 'healthy' when all backend services are reachable."""
    with (
        patch("app.main.check_db_health", new_callable=AsyncMock) as mock_db,
        patch("app.main.check_redis_health", new_callable=AsyncMock) as mock_redis,
        patch("app.main.check_qdrant_health", new_callable=AsyncMock) as mock_qdrant,
        patch("app.main.check_kafka_health", new_callable=AsyncMock) as mock_kafka,
    ):
        mock_db.return_value = True
        mock_redis.return_value = True
        mock_qdrant.return_value = True
        mock_kafka.return_value = True

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["services"]["postgres"] == "up"
            assert data["services"]["redis"] == "up"
            assert data["services"]["qdrant"] == "up"
            assert data["services"]["kafka"] == "up"


@pytest.mark.asyncio
async def test_token_harbor_llm_ping():
    """Verify live connectivity and chat completion with Token Harbor DeepSeek model."""
    settings = get_settings()
    llm = get_chat_llm(streaming=False)

    assert settings.TOKEN_HARBOR_API_KEY
    assert getattr(llm, "model_name", None) == settings.LLM_MODEL_NAME
    base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None)
    assert str(base_url).rstrip("/") == settings.TOKEN_HARBOR_BASE_URL.rstrip("/")

    try:
        response = await llm.ainvoke("ping")
        assert response is not None
        assert hasattr(response, "content")
        assert len(str(response.content).strip()) > 0
    except Exception as e:
        if "email_verification_required" in str(e):
            pytest.skip(
                "Token Harbor API requires email verification. "
                "Please verify your email address at https://tokenharbor.ai/dashboard"
            )
        raise

