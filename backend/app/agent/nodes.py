import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.agent.state import AgentState
from app.core.llm import get_chat_llm
from app.services.qdrant_service import search_documents

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict:
    """Safely extract JSON dictionary from LLM response text."""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace : last_brace + 1])
        except Exception:
            pass

    return {}


def get_latest_user_query(messages: Sequence[BaseMessage]) -> str:
    """Extract latest human query text from messages sequence."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
            return str(msg.content)
    if messages:
        return str(messages[-1].content)
    return ""


async def router_node(state: AgentState) -> Dict[str, Any]:
    """Decide whether retrieval is required or if query can be answered directly."""
    messages = state.get("messages", [])
    query = get_latest_user_query(messages)
    selected_file_ids = state.get("selected_file_ids") or []

    # Fast-path 1: If specific files are explicitly attached, immediately retrieve without calling LLM
    if selected_file_ids:
        return {"router_decision": "retrieve"}

    # Fast-path 2: for clear greetings when no specific files are explicitly requested
    normalized_query = query.strip().lower()
    chitchat_greetings = {"hi", "hello", "hey", "good morning", "good evening", "who are you", "who are you?", "ping"}
    if normalized_query in chitchat_greetings:
        return {"router_decision": "direct"}

    # Use Token Harbor LLM to classify query intent
    llm = get_chat_llm(streaming=False, temperature=0.0)
    prompt = (
        "You are an intent routing classifier for an enterprise document RAG assistant.\n"
        "Analyze the user's latest message and conversation context to determine if it requires "
        "searching and retrieving from uploaded documents ('retrieve') or if it is general chitchat, "
        "greetings, or standard knowledge that can be answered directly ('direct').\n"
        f"Selected files attached: {len(selected_file_ids)} file(s)\n"
        f"User query: {query}\n\n"
        "Return ONLY a JSON object in this format:\n"
        '{"decision": "retrieve" | "direct", "reason": "<brief justification>"}'
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        parsed = extract_json(str(response.content))
        decision = parsed.get("decision", "").lower().strip()
        if decision not in ("retrieve", "direct"):
            # Fallback heuristic: if selected files exist or query mentions documents, retrieve; else direct
            if selected_file_ids or any(k in normalized_query for k in ["doc", "file", "pdf", "report", "policy", "what is"]):
                decision = "retrieve"
            else:
                decision = "direct"
    except Exception as e:
        logger.warning(f"Router LLM invocation failed: {e}. Defaulting to retrieve.")
        decision = "retrieve" if selected_file_ids else "direct"

    return {"router_decision": decision}


async def retrieve_node(state: AgentState) -> Dict[str, Any]:
    """Embed search query with FastEmbed and retrieve top 5 matching chunks from Qdrant."""
    user_id = state.get("user_id")
    if not user_id:
        logger.error("retrieve_node called without user_id in state.")
        return {"retrieved_docs": []}

    # Use rewritten search query if present, otherwise latest user query
    query = state.get("search_query")
    if not query:
        query = get_latest_user_query(state.get("messages", []))

    selected_file_ids = state.get("selected_file_ids")

    # Strict multi-tenant retrieval enforcing user_id and optional selected_file_ids
    docs = await search_documents(
        user_id=user_id,
        query_text=query,
        selected_file_ids=selected_file_ids,
        limit=5,
    )
    return {"retrieved_docs": docs}


async def grade_documents_node(state: AgentState) -> Dict[str, Any]:
    """Evaluate whether retrieved document chunks are relevant to the user query."""
    docs = state.get("retrieved_docs", [])
    if not docs:
        return {"retrieved_docs": []}

    query = state.get("search_query") or get_latest_user_query(state.get("messages", []))

    chunks_text = "\n\n".join(
        [
            f"[Chunk {i}] File: {d.get('filename')} (ID: {d.get('file_id')}, index {d.get('chunk_index')}):\n{d.get('text')}"
            for i, d in enumerate(docs)
        ]
    )

    llm = get_chat_llm(streaming=False, temperature=0.0)
    prompt = (
        "You are an evaluator assessing whether retrieved document chunks are relevant to a user query.\n"
        f"User Query: {query}\n\n"
        "Retrieved Chunks:\n"
        f"{chunks_text}\n\n"
        "Evaluate which chunks contain information relevant to addressing the query.\n"
        "Return ONLY a JSON object in this format:\n"
        '{"relevant_indices": [0, 1]} or {"relevant_indices": []}'
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        parsed = extract_json(str(response.content))
        relevant_indices = parsed.get("relevant_indices", [])
        if isinstance(relevant_indices, list):
            valid_indices = {int(idx) for idx in relevant_indices if isinstance(idx, int) or str(idx).isdigit()}
            filtered_docs = [d for i, d in enumerate(docs) if i in valid_indices]
            return {"retrieved_docs": filtered_docs}
    except Exception as e:
        logger.warning(f"Grading LLM invocation failed: {e}. Retaining original docs.")

    # Fallback: if grading fails, retain docs with positive score
    return {"retrieved_docs": docs}


async def rewrite_query_node(state: AgentState) -> Dict[str, Any]:
    """Rewrite search query when retrieved chunks are irrelevant and rewrite_count < 2."""
    current_count = state.get("rewrite_count", 0)
    new_count = current_count + 1

    messages = state.get("messages", [])
    original_query = get_latest_user_query(messages)

    llm = get_chat_llm(streaming=False, temperature=0.2)
    prompt = (
        "You are a search query optimizer for a document retrieval engine.\n"
        "The previous query failed to retrieve relevant documents.\n"
        "Analyze the user's question and rewrite it into a clear, focused search query "
        "optimized for semantic vector similarity retrieval.\n"
        f"Original user question: {original_query}\n\n"
        "Provide ONLY the rewritten search query with no additional commentary."
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        rewritten_query = str(response.content).strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"Rewrite LLM failed: {e}. Keeping original query.")
        rewritten_query = original_query

    return {
        "search_query": rewritten_query,
        "rewrite_count": new_count,
    }


async def generate_node(state: AgentState) -> Dict[str, Any]:
    """Synthesize final response with context, conversation history, custom prompt, and inline citations."""
    retrieved_docs = state.get("retrieved_docs", [])
    custom_prompt = state.get("custom_system_prompt")
    messages = list(state.get("messages", []))

    # Base persona and system prompt
    system_parts = []
    if custom_prompt and custom_prompt.strip():
        system_parts.append(custom_prompt.strip())
    else:
        system_parts.append(
            "You are KafMind, an advanced AI assistant powered by high-speed document retrieval and Kafka."
        )

    # Retrieval context & inline citation instructions
    if retrieved_docs:
        context_items = []
        for doc in retrieved_docs:
            fname = doc.get("filename", "document")
            cidx = doc.get("chunk_index", 0)
            text = doc.get("text", "").strip()
            context_items.append(f"--- Document Source: [{fname}:{cidx}] ---\n{text}")

        formatted_context = "\n\n".join(context_items)
        system_parts.append(
            "You have access to the following retrieved document excerpts.\n"
            "INSTRUCTIONS:\n"
            "1. Answer the user's question accurately using the provided context.\n"
            "2. Whenever you reference information from an excerpt, cite the source inline using the exact format: [filename:chunk_index] (for example: [annual_report.pdf:0] or [policy.docx:2]).\n"
            "3. If the context does not contain enough information, state what you know and clarify what is missing.\n\n"
            f"Retrieved Document Context:\n{formatted_context}"
        )
    elif state.get("router_decision") == "retrieve":
        system_parts.append(
            "Note: Document retrieval was performed, but no relevant excerpts were found in the uploaded files. "
            "Politely inform the user that no relevant content was found in their documents, and provide general assistance if appropriate."
        )

    full_system_message = "\n\n".join(system_parts)
    prompt_messages: List[BaseMessage] = [SystemMessage(content=full_system_message), *messages]

    llm = get_chat_llm(streaming=True)
    response = await llm.ainvoke(prompt_messages)
    return {"messages": [response]}
