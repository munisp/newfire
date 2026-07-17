#!/usr/bin/env python3
"""Graph workflow definitions for NewFire workflows."""

import json
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool


class AgentState:
    """State definition for the agent graph."""
    messages: List[Any] = []
    tenant_id: str = ""
    model: str = "gpt-4o-mini"
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    output: str = ""


@tool
def search_qdrant(query: str) -> str:
    """Search company knowledge base using Qdrant."""
    return json.dumps({"results": [], "query": query})


@tool
def check_tenant_context(tenant_id: str) -> str:
    """Retrieve tenant-specific context and permissions."""
    return json.dumps({"tenant_id": tenant_id, "context": {}})


graph_builder = StateGraph(AgentState)

# Nodes
def chat_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Chat model node that generates responses."""
    model = ChatOpenAI(temperature=0, streaming=True)
    messages = state["messages"]
    response = model.invoke(messages)
    state["model"] = response.additional_kwargs.get("model", "unknown")
    state["latency_ms"] = 0
    state["input_tokens"] = response.usage_metadata.get("input_tokens", 0)
    state["output_tokens"] = response.usage_metadata.get("output_tokens", 0)
    state["output"] = response.content
    return {
        "messages": [response],
        "model": state["model"],
        "latency_ms": state["latency_ms"],
        "input_tokens": state["input_tokens"],
        "output_tokens": state["output_tokens"],
        "output": state["output"],
    }


def system_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """System message node that sets up tenant context."""
    tenant_id = state["tenant_id"]
    return {"messages": [SystemMessage(content=f"Tenant: {tenant_id}")]}


# Build graph
graph_builder.add_node("system", system_node)
graph_builder.add_node("chat", chat_node)
graph_builder.add_node("tools", ToolNode([search_qdrant, check_tenant_context]))

graph_builder.add_conditional_edges(
    "chat",
    tools_condition,
    {"tools": "tools", END: END},
)

graph_builder.add_edge("tools", "chat")
graph_builder.set_entry_point("system")

graph = graph_builder.compile()