"""Real MCP Server Implementation using stdio transport.

This is a proper MCP (Model Context Protocol) server that communicates
via JSON-RPC over stdio. Run this as a separate process.

Usage:
    python -m backend.mcp.server

Or via the MCP client:
    Process spawns this as a subprocess and communicates via stdin/stdout
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import the existing tool handlers (reuse business logic)
from backend.mcp.tools import MCPToolRegistry
from backend.utils import get_app_name

# Configure logging to stderr (stdout is reserved for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Create MCP Server instance with dynamic app name
_app_name = get_app_name().lower().replace(" ", "-")
server = Server(f"{_app_name}-mcp-server")

# Tool registry for business logic
_tool_registry: MCPToolRegistry = None


def get_registry() -> MCPToolRegistry:
    """Get or create tool registry singleton."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = MCPToolRegistry()
    return _tool_registry


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List all available tools via MCP protocol.

    This is called by MCP clients to discover available tools.
    """
    registry = get_registry()
    tools = []

    for tool_def in registry.get_all_tools():
        # Convert our tool definition to MCP Tool format
        schema = tool_def.to_json_schema()
        func_def = schema["function"]

        tools.append(Tool(
            name=func_def["name"],
            description=func_def["description"],
            inputSchema=func_def["parameters"]
        ))

    logger.info(f"Listed {len(tools)} tools via MCP")
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Execute a tool via MCP protocol.

    This is called by MCP clients to execute tools.

    Args:
        name: The tool name
        arguments: Tool arguments as a dictionary

    Returns:
        Sequence of TextContent with the result
    """
    logger.info(f"MCP call_tool: {name} with args: {arguments}")

    registry = get_registry()

    # Execute the tool using existing handler
    result = await registry.execute_tool(name, arguments or {})

    # Convert result to JSON string for MCP response
    result_json = json.dumps(result, ensure_ascii=False, indent=2)

    logger.info(f"MCP tool {name} completed: success={result.get('success', False)}")

    return [TextContent(type="text", text=result_json)]


async def main():
    """Main entry point for the MCP server.

    Runs the server using stdio transport (JSON-RPC over stdin/stdout).
    """
    app_name = get_app_name()
    logger.info(f"Starting {app_name} MCP Server...")

    # Initialize the tool registry
    registry = get_registry()
    tool_count = len(registry.get_all_tools())
    logger.info(f"Loaded {tool_count} tools")

    # Run the server with stdio transport
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP Server ready, listening on stdio")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
