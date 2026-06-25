from fastapi.testclient import TestClient

from app.api.dependencies import get_mcp_client
from app.main import app
from app.api.routes.agent import _extract_trace_tool_calls
from app.models.agent import AgentStep
from app.models.mcp import MCPServerStatus
from app.services.mcp_client import (
    MCPInspectResult,
    MCPPromptReference,
    MCPResourceReference,
    MCPToolReference,
)


def _echo_reference() -> MCPToolReference:
    return MCPToolReference(
        server_name="demo",
        tool_name="echo",
        qualified_name="mcp_demo_echo",
        description="Echo back text.",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )


class _FakeMCPClient:
    def __init__(self, *, enabled: bool = True, tools=None) -> None:
        self._enabled = enabled
        self._tools = tools if tools is not None else []
        self.config_path = "data/mcp/servers.json"

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def server_count(self) -> int:
        return 1 if self._enabled else 0

    async def list_tools(self):
        return self._tools

    async def list_servers_status(self):
        if not self._enabled:
            return [], []
        statuses = [
            MCPServerStatus(
                name="demo",
                transport="stdio",
                connected=True,
                tool_count=len(self._tools),
            )
        ]
        return statuses, self._tools

    async def inspect(self) -> MCPInspectResult:
        if not self._enabled:
            return MCPInspectResult(servers=[], tools=[], resources=[], prompts=[])
        servers = [
            MCPServerStatus(
                name="demo",
                transport="stdio",
                connected=True,
                tool_count=len(self._tools),
                resource_count=1,
                prompt_count=1,
            )
        ]
        resources = [
            MCPResourceReference(
                server_name="demo",
                name="greeting",
                uri="demo://greeting",
                description="Greeting.",
                mime_type="text/plain",
            )
        ]
        prompts = [
            MCPPromptReference(
                server_name="demo",
                name="summarize",
                description="Summarize.",
                arguments=[],
            )
        ]
        return MCPInspectResult(
            servers=servers, tools=self._tools, resources=resources, prompts=prompts
        )


def test_mcp_tools_endpoint_lists_tools() -> None:
    app.dependency_overrides[get_mcp_client] = lambda: _FakeMCPClient(
        tools=[_echo_reference()]
    )
    try:
        client = TestClient(app)
        response = client.get("/api/v1/mcp/tools")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["tool_count"] == 1
    assert body["tools"][0]["qualified_name"] == "mcp_demo_echo"
    assert body["tools"][0]["server"] == "demo"


def test_mcp_servers_endpoint_reports_status() -> None:
    app.dependency_overrides[get_mcp_client] = lambda: _FakeMCPClient(
        tools=[_echo_reference()]
    )
    try:
        client = TestClient(app)
        response = client.get("/api/v1/mcp/servers")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["server_count"] == 1
    assert body["servers"][0]["connected"] is True
    assert body["servers"][0]["tool_count"] == 1


def test_mcp_tools_endpoint_when_disabled() -> None:
    app.dependency_overrides[get_mcp_client] = lambda: _FakeMCPClient(enabled=False)
    try:
        client = TestClient(app)
        response = client.get("/api/v1/mcp/tools")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["tool_count"] == 0
    assert body["tools"] == []


def test_mcp_capabilities_endpoint_lists_tools_resources_prompts() -> None:
    app.dependency_overrides[get_mcp_client] = lambda: _FakeMCPClient(
        tools=[_echo_reference()]
    )
    try:
        client = TestClient(app)
        response = client.get("/api/v1/mcp/capabilities")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["tools"][0]["qualified_name"] == "mcp_demo_echo"
    assert body["resources"][0]["uri"] == "demo://greeting"
    assert body["prompts"][0]["name"] == "summarize"
    assert body["servers"][0]["resource_count"] == 1
    assert body["servers"][0]["prompt_count"] == 1


def test_extract_trace_tool_calls_marks_mcp_and_builtin() -> None:
    steps = [
        AgentStep(
            name="call_tools",
            status="completed",
            detail="",
            data={"tool": "calculator"},
        ),
        AgentStep(
            name="generate_answer",
            status="completed",
            detail="",
            data={
                "executed_tool_calls": [
                    {"name": "mcp_demo_echo", "status": "success"},
                    {"name": "create_todo", "status": "success"},
                ]
            },
        ),
    ]

    result = _extract_trace_tool_calls(steps)

    kinds = {call["name"]: call["kind"] for call in result}
    assert kinds["calculator"] == "builtin"
    assert kinds["mcp_demo_echo"] == "mcp"
    assert kinds["create_todo"] == "llm_tool"
