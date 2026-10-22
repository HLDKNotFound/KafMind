import json
from functools import lru_cache
from pathlib import Path
from typing import List, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file() -> str:
    """Locate the .env file either in current working dir, parents, or repository root."""
    cwd = Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        env_candidate = parent / ".env"
        if env_candidate.is_file():
            return str(env_candidate)
    
    # Fallback to repo root relative to this file
    root_env = Path(__file__).resolve().parents[3] / ".env"
    if root_env.is_file():
        return str(root_env)
    
    return ".env"


class Settings(BaseSettings):
    """Application settings and environment configuration."""

    # 1. LLM & Embedding Config (Token Harbor & FastEmbed)
    TOKEN_HARBOR_API_KEY: str = "your_token_harbor_api_key_here"
    TOKEN_HARBOR_BASE_URL: str = "https://tokenharbor.ai/v1"
    LLM_MODEL_NAME: str = "deepseek-v4.1-flash:free"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 8192

    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION: int = 384

    # 2. Backend & Authentication (FastAPI)
    APP_NAME: str = "KafMind"
    APP_ENV: str = "development"
    SECRET_KEY: str = "super_secret_jwt_key_change_in_production_987654321"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]
    UPLOAD_DIR: str = "uploads"

    # 3. Core Database & Cache (PostgreSQL + Redis)
    POSTGRES_USER: str = "kafmind_user"
    POSTGRES_PASSWORD: str = "kafmind_pass"
    POSTGRES_DB: str = "kafmind_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = "postgresql+asyncpg://kafmind_user:kafmind_pass@localhost:5432/kafmind_db"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://localhost:6379/0"

    # 4. Vector Database (Qdrant)
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION_NAME: str = "kafmind_documents"

    # 5. Event Streaming (Apache Kafka - KRaft)
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_FILE_UPLOADED: str = "file.uploaded"
    KAFKA_TOPIC_FILE_STATUS: str = "file.status"
    KAFKA_CONSUMER_GROUP: str = "kafmind-ingestion-group"

    # 6. Frontend Config (Vite / React)
    VITE_API_BASE_URL: str = "http://localhost:8000/api/v1"

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Union[str, List[str]]) -> List[str]:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except Exception:
                    pass
            return [v.strip() for v in value.split(",") if v.strip()]
        return value


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton of application settings."""
    return Settings()
