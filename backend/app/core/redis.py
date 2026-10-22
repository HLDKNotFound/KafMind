from typing import Optional
import redis.asyncio as aioredis

from app.core.config import get_settings

settings = get_settings()

redis_client: Optional[aioredis.Redis] = None


def get_redis_client() -> aioredis.Redis:
    """Get or initialize the shared async Redis client."""
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return redis_client


async def check_redis_health() -> bool:
    """Check live connectivity to Redis."""
    try:
        client = get_redis_client()
        pong = await client.ping()
        return bool(pong)
    except Exception:
        return False


async def close_redis() -> None:
    """Close the Redis client connection pool."""
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
