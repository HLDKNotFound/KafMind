from typing import Annotated, Any, Dict, List, Optional, Sequence
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """LangGraph state schema for KafMind Agentic RAG engine."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: str
    selected_file_ids: Optional[List[str]]
    retrieved_docs: List[Dict[str, Any]]
    rewrite_count: int
    custom_system_prompt: Optional[str]
    search_query: Optional[str]
    router_decision: Optional[str]
