"""Minimal local MCP server used to smoke-test the stage 34 MCP client.

Run it as a stdio MCP server::

    python scripts/mcp_demo_server.py

It exposes a few deterministic tools so the MCP client integration can be
verified end-to-end without depending on any third-party MCP server.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def build_demo_server() -> FastMCP:
    server = FastMCP("personal-agent-demo")

    @server.tool()
    def echo(text: str) -> str:
        """Echo back the provided text unchanged."""
        return text

    @server.tool()
    def add(a: float, b: float) -> float:
        """Add two numbers and return the sum."""
        return a + b

    @server.tool()
    def text_stats(text: str) -> dict:
        """Return character and word counts for the given text."""
        return {"chars": len(text), "words": len(text.split())}

    @server.resource("demo://greeting")
    def greeting() -> str:
        """A simple greeting resource exposed over MCP."""
        return "Hello from the personal-agent demo MCP server."

    @server.prompt()
    def summarize(text: str) -> str:
        """Prompt template that asks the model to summarize text."""
        return f"请用一句话总结下面的内容：\n\n{text}"

    return server


if __name__ == "__main__":
    build_demo_server().run(transport="stdio")
