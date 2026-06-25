"""End-to-end smoke: real LLM + real stdio MCP demo server through the Agent.

Injects a real ``MCPClient`` (stdio) connected to ``scripts/mcp_demo_server.py``
and a real OpenAI-compatible LLM (from ``.env``) into the agent workflow, then
runs a general-chat request that should make the model call an MCP tool.

Requires a reachable LLM (e.g. the local reverse proxy in ``.env``). Run::

    python scripts/smoke_agent_mcp.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.workflow import run_agent_workflow  # noqa: E402
from app.models.agent import AgentRunRequest  # noqa: E402
from app.models.mcp import MCPServerConfig  # noqa: E402
from app.services.embedding_client import (  # noqa: E402
    build_embedding_client_from_settings,
)
from app.services.llm_client import OpenAICompatibleClient  # noqa: E402
from app.services.mcp_client import MCPClient  # noqa: E402
from app.services.mysql_client import MySQLStore  # noqa: E402
from app.services.redis_client import RedisStore  # noqa: E402


async def main() -> None:
    demo_server = Path(__file__).resolve().parent / "mcp_demo_server.py"
    mcp_client = MCPClient(
        [
            MCPServerConfig(
                name="demo",
                transport="stdio",
                command=sys.executable,
                args=[str(demo_server)],
            )
        ]
    )

    discovered = await mcp_client.list_tools()
    print("discovered MCP tools:", [tool.qualified_name for tool in discovered])

    llm_client = OpenAICompatibleClient.from_settings()
    redis_store = RedisStore.from_settings()
    mysql_store = MySQLStore.from_settings()
    embedding_client = build_embedding_client_from_settings()

    request = AgentRunRequest(
        query="请调用 echo 工具，把这句话原样返回：你好 MCP 工具",
        use_knowledge_base=False,
    )

    try:
        response = await run_agent_workflow(
            request,
            redis_store=redis_store,
            mysql_store=mysql_store,
            embedding_client=embedding_client,
            llm_client=llm_client,
            mcp_client=mcp_client,
        )
    finally:
        await llm_client.aclose()
        await redis_store.aclose()
        await mysql_store.aclose()

    print("intent:", response.intent)
    print("answer:", response.answer)
    generate_step = next(
        (step for step in response.steps if step.name == "generate_answer"), None
    )
    executed = generate_step.data.get("executed_tool_calls", []) if generate_step else []
    mcp_tool_count = generate_step.data.get("mcp_tool_count") if generate_step else None
    print("mcp_tool_count:", mcp_tool_count)
    print("executed_tool_calls:", executed)

    called_mcp = any(
        call.get("name", "").startswith("mcp_") for call in executed
    )
    print("MCP_TOOL_EXECUTED" if called_mcp else "MCP_TOOL_NOT_CALLED")


if __name__ == "__main__":
    asyncio.run(main())
