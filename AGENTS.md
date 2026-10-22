# AGENTS.md - Architectural & Development Guidelines for KafMind

## 1. Project Overview
KafMind is a ChatGPT-like Agentic RAG web application built for high-speed document retrieval and scalable asynchronous file ingestion via Apache Kafka.

## 2. Mandatory Tech Stack
- **Frontend:** React 19 (Vite + TypeScript), TailwindCSS, shadcn/ui, Zustand, TanStack Query, `@microsoft/fetch-event-source` (SSE).
- **Backend:** FastAPI (Python 3.12+), SQLAlchemy 2.0 (AsyncPG), Alembic, Pydantic v2.
- **Event Streaming:** Apache Kafka (KRaft mode) + `aiokafka` (Async Producer/Consumer).
- **AI & Agent:** LangChain & LangGraph.
  - **LLM:** Token Harbor (`deepseek-v4.1-flash:free`) via `ChatOpenAI` (OpenAI-compatible SDK) configured with `TOKEN_HARBOR_BASE_URL` and `TOKEN_HARBOR_API_KEY` from `.env`.
  - **Embeddings:** `FastEmbed` (`BAAI/bge-small-en-v1.5`, 384 dimensions).
- **Vector DB:** Qdrant (`AsyncQdrantClient`). Every vector payload MUST include `user_id` and `file_id` for strict multi-tenant data isolation.
- **Core DB & Cache:** PostgreSQL 16 (Users, Sessions, Messages, File Metadata) + Redis 7 (JWT Blacklist, Real-time File Status Pub/Sub).

## 3. Strict Coding & Testing Rules
1. **100% Async I/O in Backend:** All database queries, Qdrant searches, Redis operations, Kafka producers/consumers, and LangGraph executions must use `async/await`.
2. **Multi-Tenant Security:** Every Qdrant query MUST apply a strict payload filter on `user_id`.
3. **Non-Blocking File Uploads:** `POST /api/v1/files/upload` must only save the file, create a `PENDING` database record, publish an event to Kafka `file.uploaded`, and immediately return `202 Accepted`.

## 4. CRITICAL EXECUTION PROTOCOL (STAGE-GATE LOCK)
- **ONE STAGE AT A TIME:** You are strictly forbidden from implementing multiple stages in a single turn.
- **NO PRE-EMPTIVE SCAFFOLDING:** Only create the files and directories explicitly requested in the current stage prompt. Do NOT create placeholder files or boilerplate code for future stages.
- **MANDATORY HARD STOP:** Once the tasks and tests for the current stage are completed and passing, you MUST STOP IMMEDIATELY, output a brief summary of what was done, and wait for the user's explicit prompt to begin the next stage.