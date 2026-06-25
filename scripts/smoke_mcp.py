"""Real stdio smoke test for the stage 34 MCP client.

Spawns ``scripts/mcp_demo_server.py`` as a stdio MCP server, discovers its
tools and calls them through the project's ``MCPClient``. This verifies the
end-to-end MCP client path (subprocess transport + protocol handshake +
tool call) without any mocks.

Usage::

    python scripts/smoke_mcp.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.mcp import MCPServerConfig  # noqa: E402
from app.services.mcp_client import MCPClient  # noqa: E402


async def main() -> None:
    demo_server = Path(__file__).resolve().parent / "mcp_demo_server.py"
    config = MCPServerConfig(
        name="demo",
        transport="stdio",
        command=sys.executable,
        args=[str(demo_server)],
    )
    client = MCPClient([config])

    tools = await client.list_tools()
    print("discovered tools:", [tool.qualified_name for tool in tools])

    add_result = await client.call_tool("mcp_demo_add", {"a": 2, "b": 5})
    print("add result:", add_result.text, "| is_error:", add_result.is_error)

    echo_result = await client.call_tool("mcp_demo_echo", {"text": "hello mcp"})
    print("echo result:", echo_result.text)

    stats_result = await client.call_tool("mcp_demo_text_stats", {"text": "a b c"})
    print("text_stats result:", stats_result.text)

    ok = (
        len(tools) == 3
        and "7" in add_result.text
        and "hello mcp" in echo_result.text
        and not add_result.is_error
    )
    print("SMOKE_OK" if ok else "SMOKE_FAILED")


if __name__ == "__main__":
    asyncio.run(main())
