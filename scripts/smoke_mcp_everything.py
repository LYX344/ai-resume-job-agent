"""Smoke test: connect to the official @modelcontextprotocol/server-everything.

Verifies the MCP client can connect to a real third-party MCP server (not just
the local demo server) over stdio via npx, discovering its tools / resources /
prompts. Requires Node.js + npx; the first run downloads the server package.

Usage::

    python scripts/smoke_mcp_everything.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.mcp import MCPServerConfig  # noqa: E402
from app.services.mcp_client import MCPClient  # noqa: E402


async def main() -> None:
    config = MCPServerConfig(
        name="everything",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-everything"],
    )
    client = MCPClient([config], tool_timeout_seconds=120.0)

    result = await client.inspect()
    for server in result.servers:
        print(
            f"server={server.name} connected={server.connected} "
            f"tools={server.tool_count} resources={server.resource_count} "
            f"prompts={server.prompt_count} error={server.error}"
        )
    print("sample tools:", [tool.qualified_name for tool in result.tools][:8])
    print("sample resources:", [resource.uri for resource in result.resources][:3])
    print("sample prompts:", [prompt.name for prompt in result.prompts][:3])

    ok = bool(result.servers) and result.servers[0].connected and bool(result.tools)
    print("EVERYTHING_OK" if ok else "EVERYTHING_FAILED")


if __name__ == "__main__":
    asyncio.run(main())
