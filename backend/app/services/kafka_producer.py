import json
import logging
import uuid
from typing import Any, Dict, Optional, Union

from aiokafka import AIOKafkaProducer

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_kafka_producer: Optional[AIOKafkaProducer] = None


async def get_kafka_producer() -> AIOKafkaProducer:
    """Get or start the shared AIOKafkaProducer singleton."""
    global _kafka_producer
    if _kafka_producer is None:
        _kafka_producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await _kafka_producer.start()
        logger.info(f"Connected AIOKafkaProducer to {settings.KAFKA_BOOTSTRAP_SERVERS}")
    return _kafka_producer


async def stop_kafka_producer() -> None:
    """Gracefully stop and flush the shared AIOKafkaProducer."""
    global _kafka_producer
    if _kafka_producer is not None:
        try:
            await _kafka_producer.stop()
            logger.info("Closed AIOKafkaProducer")
        except Exception as e:
            logger.warning(f"Error closing AIOKafkaProducer: {e}")
        finally:
            _kafka_producer = None


async def publish_file_uploaded(
    file_id: Union[str, uuid.UUID],
    user_id: Union[str, uuid.UUID],
    file_path: str,
    filename: str,
    producer: Optional[AIOKafkaProducer] = None,
) -> Dict[str, Any]:
    """Publish file.uploaded event to Kafka topic for asynchronous ingestion."""
    event_payload: Dict[str, Any] = {
        "file_id": str(file_id),
        "user_id": str(user_id),
        "file_path": str(file_path),
        "filename": filename,
    }

    if producer is None:
        producer = await get_kafka_producer()

    topic = settings.KAFKA_TOPIC_FILE_UPLOADED
    await producer.send_and_wait(topic, event_payload)
    logger.info(f"Published event to topic '{topic}': {event_payload}")
    return event_payload
