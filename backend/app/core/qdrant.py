from typing import Optional
from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings

settings = get_settings()

qdrant_client: Optional[AsyncQdrantClient] = None


def get_qdrant_client() -> AsyncQdrantClient:
    """Get or initialize the shared AsyncQdrantClient."""
    global qdrant_client
    if qdrant_client is None:
        qdrant_client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            check_compatibility=False,
        )
    return qdrant_client


async def check_qdrant_health() -> bool:
    """Verify live connectivity to Qdrant vector database."""
    try:
        client = get_qdrant_client()
        await client.get_collections()
        return True
    except Exception:
        return False


async def close_qdrant() -> None:
    """Close the Qdrant async client connection."""
    global qdrant_client
    if qdrant_client is not None:
        await qdrant_client.close()
        qdrant_client = None
