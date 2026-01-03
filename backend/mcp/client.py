"""MCP Client for connecting to the MCP server via stdio.

This client spawns the MCP server as a subprocess and communicates
with it using JSON-RPC over stdio.
"""

import asyncio
import json
import logging
import sys
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

logger = logging.getLogger(__name__)


class MCPClient:
    """Client for communicating with the MCP server.

    This client manages the lifecycle of the MCP server subprocess
    and provides methods to list and call tools via MCP protocol.
    """

    def __init__(self):
        self._session: Optional[ClientSession] = None
        self._read_stream = None
        self._write_stream = None
        self._context = None

    @asynccontextmanager
    async def connect(self):
        """Connect to the MCP server.

        This spawns the MCP server as a subprocess and establishes
        communication via stdio.

        Usage:
            client = MCPClient()
            async with client.connect():
                tools = await client.list_tools()
                result = await client.call_tool("list_projects", {})
        """
        # Get the path to the MCP server module
        # Use the current Python interpreter to run the server
        python_path = sys.executable

        # Get project root directory
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        server_params = StdioServerParameters(
            command=python_path,
            args=["-m", "backend.mcp.server"],
            cwd=project_root,
            env={
                **os.environ,
                "PYTHONPATH": project_root,
            }
        )

        logger.info(f"Starting MCP server: {python_path} -m backend.mcp.server in {project_root}")

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the session
                await session.initialize()
                logger.info("MCP client connected and initialized")

                self._session = session
                try:
                    yield self
                finally:
                    self._session = None

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List all available tools from the MCP server.

        Returns:
            List of tool definitions with name, description, and inputSchema
        """
        if not self._session:
            raise RuntimeError("Not connected to MCP server")

        result = await self._session.list_tools()

        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema
            })

        logger.info(f"Listed {len(tools)} tools from MCP server")
        return tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result as a dictionary
        """
        if not self._session:
            raise RuntimeError("Not connected to MCP server")

        logger.info(f"Calling MCP tool: {name} with args: {arguments}")

        result = await self._session.call_tool(name, arguments)

        # Parse the response
        # MCP returns a list of content items
        if result.content:
            for content in result.content:
                if content.type == "text":
                    try:
                        return json.loads(content.text)
                    except json.JSONDecodeError:
                        return {"success": True, "result": content.text}

        return {"success": False, "error": "No content in response"}

    def get_tools_json_schema(self) -> List[Dict[str, Any]]:
        """Get tools in OpenAI-compatible JSON schema format.

        This is a synchronous wrapper that runs the async list_tools.
        Must be called from within an async context or after connect().
        """
        # This requires being connected, run synchronously
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in async context, this won't work
            # Caller should use list_tools() directly
            raise RuntimeError("Use await list_tools() in async context")

        async def _get():
            async with self.connect():
                tools = await self.list_tools()
                return tools

        tools = loop.run_until_complete(_get())

        # Convert to OpenAI function calling format
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["inputSchema"]
                }
            })
        return openai_tools


# Singleton client instance
_mcp_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    """Get or create the MCP client singleton."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client


async def test_mcp_connection():
    """Test the MCP client connection."""
    client = MCPClient()

    async with client.connect():
        # List tools
        tools = await client.list_tools()
        print(f"Available tools ({len(tools)}):")
        for tool in tools:
            print(f"  - {tool['name']}: {tool['description'][:50]}...")

        # Call a tool
        print("\nCalling list_projects tool...")
        result = await client.call_tool("list_projects", {})
        print(f"Result: {json.dumps(result, indent=2, ensure_ascii=False)}")


if __name__ == "__main__":
    asyncio.run(test_mcp_connection())
