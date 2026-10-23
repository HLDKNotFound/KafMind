import asyncio
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.files import router as files_router
from app.api.v1.users import router as users_router
from app.core.config import get_settings
from app.core.database import check_db_health, close_db
from app.core.kafka import check_kafka_health
from app.core.qdrant import check_qdrant_health, close_qdrant
from app.core.redis import check_redis_health, close_redis
from app.services.kafka_producer import stop_kafka_producer

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management for connection pools."""
    yield
    # Graceful shutdown of persistent connections
    await close_db()
    await close_redis()
    await close_qdrant()
    await stop_kafka_producer()


app = FastAPI(
    title=settings.APP_NAME,
    description="KafMind Backend API with Asynchronous Ingestion & Agentic RAG",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API v1 Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(files_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")


@app.get("/api/v1/health", status_code=status.HTTP_200_OK)
async def health_check() -> JSONResponse:
    """Actively verify live connectivity to PostgreSQL, Redis, Qdrant, and Kafka."""
    # Run all health checks concurrently for maximum performance
    pg_ok, redis_ok, qdrant_ok, kafka_ok = await asyncio.gather(
        check_db_health(),
        check_redis_health(),
        check_qdrant_health(),
        check_kafka_health(),
        return_exceptions=False,
    )

    all_healthy = all([pg_ok, redis_ok, qdrant_ok, kafka_ok])
    services_state: Dict[str, str] = {
        "postgres": "up" if pg_ok else "down",
        "redis": "up" if redis_ok else "down",
        "qdrant": "up" if qdrant_ok else "down",
        "kafka": "up" if kafka_ok else "down",
    }

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "healthy" if all_healthy else "degraded",
            "app": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "services": services_state,
        },
    )
