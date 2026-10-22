import asyncio
import logging
import uuid
from typing import List, Optional, Union

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient, models

from app.core.config import get_settings
from app.core.qdrant import get_qdrant_client

logger = logging.getLogger(__name__)
settings = get_settings()

_embedding_model: Optional[TextEmbedding] = None


def get_embedding_model() -> TextEmbedding:
    """Get or initialize singleton FastEmbed TextEmbedding model."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = TextEmbedding(model_name=settings.EMBEDDING_MODEL_NAME)
    return _embedding_model


def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """Synchronously compute 384-dimensional dense vectors for text chunks."""
    model = get_embedding_model()
    embeddings_gen = model.embed(texts)
    return [embedding.tolist() for embedding in embeddings_gen]


async def init_qdrant_collection(client: Optional[AsyncQdrantClient] = None) -> None:
    """Initialize kafmind_documents collection with Cosine distance and payload keyword indexes."""
    if client is None:
        client = get_qdrant_client()

    collection_name = settings.QDRANT_COLLECTION_NAME
    collection_exists = await client.collection_exists(collection_name=collection_name)

    if not collection_exists:
        logger.info(f"Creating Qdrant collection '{collection_name}' (dim={settings.EMBEDDING_DIMENSION}).")
        await client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=settings.EMBEDDING_DIMENSION,
                distance=models.Distance.COSINE,
            ),
        )

    # Ensure payload indexes on user_id and file_id for strict multi-tenant filtering & deletion
    for field_name in ["user_id", "file_id"]:
        try:
            await client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            logger.info(f"Created payload index on '{field_name}' in collection '{collection_name}'.")
        except Exception as e:
            # Index may already exist
            logger.debug(f"Payload index for '{field_name}' already exists or skipped: {e}")


async def upsert_document_chunks(
    user_id: Union[str, uuid.UUID],
    file_id: Union[str, uuid.UUID],
    filename: str,
    chunks: List[str],
    client: Optional[AsyncQdrantClient] = None,
) -> int:
    """Embed document chunks and upsert them to Qdrant with user_id & file_id multi-tenant payload."""
    if not chunks:
        return 0

    if client is None:
        client = get_qdrant_client()

    collection_name = settings.QDRANT_COLLECTION_NAME

    # Ensure collection exists before upserting
    await init_qdrant_collection(client)

    # Compute dense embeddings off-thread to prevent blocking event loop
    embeddings = await asyncio.to_thread(generate_embeddings, chunks)

    points: List[models.PointStruct] = []
    for idx, (chunk_text, vector) in enumerate(zip(chunks, embeddings)):
        point = models.PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "user_id": str(user_id),
                "file_id": str(file_id),
                "filename": filename,
                "text": chunk_text,
                "chunk_index": idx,
            },
        )
        points.append(point)

    # Upsert points into Qdrant collection
    await client.upsert(
        collection_name=collection_name,
        points=points,
    )
    logger.info(f"Upserted {len(points)} vector chunks for file_id={file_id} in collection '{collection_name}'.")
    return len(points)


async def delete_vectors_by_file_id(
    file_id: Union[str, uuid.UUID],
    client: Optional[AsyncQdrantClient] = None,
) -> None:
    """Delete all indexed vector chunks matching file_id from Qdrant collection."""
    if client is None:
        client = get_qdrant_client()

    collection_name = settings.QDRANT_COLLECTION_NAME

    # Check if collection exists before attempting delete
    exists = await client.collection_exists(collection_name=collection_name)
    if not exists:
        return

    await client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="file_id",
                        match=models.MatchValue(value=str(file_id)),
                    )
                ]
            )
        ),
    )
    logger.info(f"Deleted vectors for file_id={file_id} from collection '{collection_name}'.")


def build_user_filter(
    user_id: Union[str, uuid.UUID],
    extra_conditions: Optional[List[models.FieldCondition]] = None,
) -> models.Filter:
    """Build a Qdrant filter enforcing multi-tenant isolation by user_id."""
    must_conditions: List[Union[models.FieldCondition, models.Filter]] = [
        models.FieldCondition(
            key="user_id",
            match=models.MatchValue(value=str(user_id)),
        )
    ]
    if extra_conditions:
        must_conditions.extend(extra_conditions)
    return models.Filter(must=must_conditions)
