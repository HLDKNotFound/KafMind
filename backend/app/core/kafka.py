import asyncio
from typing import Optional
from aiokafka.admin import AIOKafkaAdminClient

from app.core.config import get_settings

settings = get_settings()


async def check_kafka_health(timeout: float = 2.0) -> bool:
    """Verify live connectivity to Apache Kafka broker."""
    admin: Optional[AIOKafkaAdminClient] = None
    try:
        admin = AIOKafkaAdminClient(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            request_timeout_ms=int(timeout * 1000),
        )
        await asyncio.wait_for(admin.start(), timeout=timeout)
        await asyncio.wait_for(admin.list_topics(), timeout=timeout)
        return True
    except Exception:
        return False
    finally:
        if admin is not None:
            try:
                await admin.close()
            except Exception:
                pass
