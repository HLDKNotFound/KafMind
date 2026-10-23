import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import app_graph
from app.agent.state import AgentState
from app.core.database import get_db
from app.core.redis import get_redis_client
from app.core.security import decode_token, is_token_blacklisted
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.schemas.chat import (
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionUpdate,
    ChatStreamRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


async def get_current_chat_user(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency supporting both Authorization header and query param for Chat endpoints."""
    auth_header = request.headers.get("Authorization")
    raw_token = None
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header.split(" ", 1)[1]
    elif token:
        raw_token = token

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(raw_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user identifier in token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chat session",
)
async def create_chat_session(
    body: Optional[ChatSessionCreate] = None,
    current_user: User = Depends(get_current_chat_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    """Create a new chat conversation session for the authenticated user."""
    title = body.title if (body and body.title) else "New Chat"
    new_session = ChatSession(
        user_id=current_user.id,
        title=title,
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return ChatSessionResponse.model_validate(new_session)


@router.get(
    "/sessions",
    response_model=List[ChatSessionResponse],
    summary="List all chat sessions for the current user",
)
async def list_chat_sessions(
    current_user: User = Depends(get_current_chat_user),
    db: AsyncSession = Depends(get_db),
) -> List[ChatSessionResponse]:
    """Retrieve all chat sessions belonging to the current user, ordered by most recently updated."""
    query = (
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
    )
    result = await db.execute(query)
    sessions = result.scalars().all()
    return [ChatSessionResponse.model_validate(s) for s in sessions]


@router.get(
    "/sessions/{session_id}/messages",
    response_model=List[ChatMessageResponse],
    summary="Get all messages in a chat session",
)
async def get_session_messages(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_chat_user),
    db: AsyncSession = Depends(get_db),
) -> List[ChatMessageResponse]:
    """Retrieve chronological message history for a specific chat session."""
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    query = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    result = await db.execute(query)
    messages = result.scalars().all()
    return [ChatMessageResponse.model_validate(m) for m in messages]


@router.delete(
    "/sessions/{session_id}",
    summary="Delete a chat session and all its messages",
)
async def delete_chat_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_chat_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a chat session with cascade deletion of all contained messages."""
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    await db.delete(session)
    await db.commit()
    return {"message": "Chat session deleted successfully", "session_id": str(session_id)}


@router.post(
    "/sessions/{session_id}/stream",
    summary="Stream LangGraph agent response via Server-Sent Events (SSE)",
)
async def stream_chat_session(
    session_id: uuid.UUID,
    body: ChatStreamRequest,
    request: Request,
    current_user: User = Depends(get_current_chat_user),
    db: AsyncSession = Depends(get_db),
):
    """
    SSE endpoint that:
    1. Persists the incoming user message to PostgreSQL.
    2. Runs the LangGraph agent via .astream_events(version="v2").
    3. Streams structured SSE events:
       - 'agent_step': Node execution status (router, retrieve, grade, rewrite, generate).
       - 'token': Streamed LLM generation tokens.
       - 'sources': Structured metadata for retrieved document chunks.
       - 'done': Final completion payload with assistant message ID.
    4. Persists the final assistant response and sources into PostgreSQL upon completion.
    """
    # 1. Multi-tenant session verification
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    # 2. Persist user message to PostgreSQL
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=body.message,
        sources=[],
    )
    db.add(user_msg)
    await db.commit()

    # 3. Retrieve chronological message history for LangGraph conversation state
    query = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    result = await db.execute(query)
    db_messages = result.scalars().all()

    langchain_messages = []
    for msg in db_messages:
        if msg.role == "user":
            langchain_messages.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            langchain_messages.append(AIMessage(content=msg.content))

    async def event_generator():
        accumulated_tokens: List[str] = []
        captured_sources: List[dict] = []

        initial_state: AgentState = {
            "messages": langchain_messages,
            "user_id": str(current_user.id),
            "selected_file_ids": body.selected_file_ids,
            "retrieved_docs": [],
            "rewrite_count": 0,
            "custom_system_prompt": current_user.custom_system_prompt,
        }

        tracked_nodes = {
            "router_node",
            "retrieve_node",
            "grade_documents_node",
            "rewrite_query_node",
            "generate_node",
        }

        try:
            async for event in app_graph.astream_events(initial_state, version="v2"):
                if await request.is_disconnected():
                    logger.info("Client disconnected from chat stream")
                    break

                event_type = event.get("event")
                node_name = event.get("name")

                # Handle node start
                if event_type == "on_chain_start" and node_name in tracked_nodes:
                    yield {
                        "event": "agent_step",
                        "data": json.dumps({
                            "step": node_name,
                            "status": "started",
                        }),
                    }

                # Handle node completion
                elif event_type == "on_chain_end" and node_name in tracked_nodes:
                    node_output = event.get("data", {}).get("output")
                    step_payload = {
                        "step": node_name,
                        "status": "completed",
                    }
                    if isinstance(node_output, dict):
                        if "router_decision" in node_output:
                            step_payload["decision"] = node_output["router_decision"]
                        if "search_query" in node_output:
                            step_payload["search_query"] = node_output["search_query"]
                        if "rewrite_count" in node_output:
                            step_payload["rewrite_count"] = node_output["rewrite_count"]
                        if "retrieved_docs" in node_output:
                            docs = node_output["retrieved_docs"] or []
                            step_payload["docs_count"] = len(docs)
                            # Update captured sources from retrieve/grade nodes
                            if node_name in ("retrieve_node", "grade_documents_node"):
                                captured_sources.clear()
                                for d in docs:
                                    captured_sources.append({
                                        "file_id": d.get("file_id"),
                                        "filename": d.get("filename"),
                                        "chunk_index": d.get("chunk_index"),
                                        "score": d.get("score"),
                                        "text": (d.get("text") or "")[:200],
                                    })

                        # Fallback for generate_node if tokens weren't streamed as chunks
                        if node_name == "generate_node" and not accumulated_tokens:
                            gen_msgs = node_output.get("messages", [])
                            if gen_msgs and hasattr(gen_msgs[-1], "content"):
                                fallback_text = str(gen_msgs[-1].content)
                                accumulated_tokens.append(fallback_text)
                                yield {
                                    "event": "token",
                                    "data": json.dumps({"token": fallback_text}),
                                }

                    yield {
                        "event": "agent_step",
                        "data": json.dumps(step_payload),
                    }

                # Handle token streaming
                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        token_str = str(chunk.content)
                        accumulated_tokens.append(token_str)
                        yield {
                            "event": "token",
                            "data": json.dumps({"token": token_str}),
                        }

            # Emit sources event
            yield {
                "event": "sources",
                "data": json.dumps({"sources": captured_sources}),
            }

            # Persist final assistant response to PostgreSQL
            final_content = "".join(accumulated_tokens).strip()
            assistant_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=final_content,
                sources=captured_sources,
            )
            db.add(assistant_msg)

            # Update session updated_at timestamp and title if default
            session_to_update = await db.get(ChatSession, session_id)
            if session_to_update:
                session_to_update.updated_at = datetime.now(timezone.utc)
                if session_to_update.title == "New Chat":
                    title_preview = body.message.strip()
                    if len(title_preview) > 40:
                        title_preview = title_preview[:37] + "..."
                    session_to_update.title = title_preview or "New Chat"

            await db.commit()
            await db.refresh(assistant_msg)

            # Emit completion event
            yield {
                "event": "done",
                "data": json.dumps({
                    "message_id": str(assistant_msg.id),
                    "content": final_content,
                    "sources": captured_sources,
                }),
            }

        except Exception as e:
            logger.error(f"Error during agent SSE streaming: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())
