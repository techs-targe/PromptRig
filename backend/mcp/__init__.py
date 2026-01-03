"""MCP (Model Context Protocol) Implementation.

Provides a real MCP server (stdio transport) and client for AI agents
to interact with the Prompt Evaluation System.

Components:
- server.py: Real MCP server using stdio transport (JSON-RPC)
- client.py: MCP client for connecting to the server
- tools.py: Tool handlers and definitions (business logic)

Usage:
    # Run MCP server standalone:
    python -m backend.mcp.server

    # Use MCP client in code:
    from backend.mcp.client import MCPClient

    async with MCPClient().connect():
        tools = await client.list_tools()
        result = await client.call_tool("list_projects", {})
"""

from .tools import MCPToolRegistry, get_tool_registry
from .client import MCPClient, get_mcp_client

__all__ = [
    'MCPToolRegistry',
    'get_tool_registry',
    'MCPClient',
    'get_mcp_client',
]
