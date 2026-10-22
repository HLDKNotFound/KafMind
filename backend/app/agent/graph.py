from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    generate_node,
    grade_documents_node,
    retrieve_node,
    rewrite_query_node,
    router_node,
)
from app.agent.state import AgentState


def route_after_router(state: AgentState) -> str:
    """Route to retrieve_node if document search is needed, else directly to generate_node."""
    if state.get("router_decision") == "retrieve":
        return "retrieve_node"
    return "generate_node"


def route_after_grading(state: AgentState) -> str:
    """Route to generate_node if relevant docs exist or max rewrites reached, else rewrite_query_node."""
    docs = state.get("retrieved_docs") or []
    if len(docs) > 0:
        return "generate_node"

    rewrite_count = state.get("rewrite_count", 0)
    if rewrite_count < 2:
        return "rewrite_query_node"

    return "generate_node"


def build_agent_graph():
    """Build and compile the LangGraph Agentic RAG workflow."""
    workflow = StateGraph(AgentState)

    # Register workflow nodes
    workflow.add_node("router_node", router_node)
    workflow.add_node("retrieve_node", retrieve_node)
    workflow.add_node("grade_documents_node", grade_documents_node)
    workflow.add_node("rewrite_query_node", rewrite_query_node)
    workflow.add_node("generate_node", generate_node)

    # Define execution graph edges
    workflow.add_edge(START, "router_node")

    workflow.add_conditional_edges(
        "router_node",
        route_after_router,
        {
            "retrieve_node": "retrieve_node",
            "generate_node": "generate_node",
        },
    )

    workflow.add_edge("retrieve_node", "grade_documents_node")

    workflow.add_conditional_edges(
        "grade_documents_node",
        route_after_grading,
        {
            "generate_node": "generate_node",
            "rewrite_query_node": "rewrite_query_node",
        },
    )

    workflow.add_edge("rewrite_query_node", "retrieve_node")
    workflow.add_edge("generate_node", END)

    return workflow.compile()


# Shared compiled graph instance
app_graph = build_agent_graph()
