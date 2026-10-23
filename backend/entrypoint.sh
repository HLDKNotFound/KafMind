#!/bin/sh
set -e

# Default command is 'server'
CMD="${1:-server}"

if [ "$CMD" = "server" ]; then
    echo "[KafMind] Applying database migrations..."
    alembic upgrade head
    echo "[KafMind] Starting FastAPI application server..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
elif [ "$CMD" = "worker" ]; then
    echo "[KafMind] Starting Kafka Ingestion Worker..."
    exec python -m app.workers.ingestion_worker
else
    # Execute any arbitrary command passed (e.g. pytest, bash)
    exec "$@"
fi
