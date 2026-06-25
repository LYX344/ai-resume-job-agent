from contextlib import asynccontextmanager

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from app.models.mcp import MCPServerConfig, load_mcp_server_configs
from app.services.mcp_client import (
    MCPClient,
    MCPClientError,
    build_qualified_name,
)


def _build_demo_server() -> FastMCP:
    server = FastMCP("test-demo")

    @server.tool()
    def echo(text: str) -> str:
        """Echo back the text."""
        return text

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    return server


def _inmemory_connector(server: FastMCP):
    @asynccontextmanager
    async def connector(_config: MCPServerConfig):
        async with create_connected_server_and_client_session(server) as session:
            yield session

    return connector


def _client_with_server(server: FastMCP, *, name: str = "demo") -> MCPClient:
    config = MCPServerConfig(name=name, transport="stdio", command="python")
    return MCPClient([config], connector=_inmemory_connector(server))


def test_build_qualified_name_sanitizes_and_namespaces() -> None:
    assert build_qualified_name("demo", "echo") == "mcp_demo_echo"
    assert build_qualified_name("my server", "do.it") == "mcp_my_server_do_it"


def test_load_mcp_server_configs_missing_file_returns_empty(tmp_path) -> None:
    assert load_mcp_server_configs(tmp_path / "nope.json") == []


def test_load_mcp_server_configs_parses_mcp_servers(tmp_path) -> None:
    config_file = tmp_path / "servers.json"
    config_file.write_text(
        '{"mcpServers": {'
        '"demo": {"transport": "stdio", "command": "python", "args": ["s.py"]},'
        '"off": {"enabled": false, "command": "x"}'
        "}}",
        encoding="utf-8",
    )

    configs = load_mcp_server_configs(config_file)

    assert len(configs) == 1
    assert configs[0].name == "demo"
    assert configs[0].command == "python"
    assert configs[0].args == ["s.py"]


def test_load_mcp_server_configs_ignores_malformed_file(tmp_path) -> None:
    config_file = tmp_path / "servers.json"
    config_file.write_text("not json", encoding="utf-8")

    assert load_mcp_server_configs(config_file) == []


@pytest.mark.anyio
async def test_list_tools_returns_namespaced_references() -> None:
    client = _client_with_server(_build_demo_server())

    references = await client.list_tools()

    names = sorted(reference.qualified_name for reference in references)
    assert names == ["mcp_demo_add", "mcp_demo_echo"]
    echo_ref = next(ref for ref in references if ref.tool_name == "echo")
    openai_tool = echo_ref.to_openai_tool()
    assert openai_tool["type"] == "function"
    assert openai_tool["function"]["name"] == "mcp_demo_echo"
    assert "properties" in openai_tool["function"]["parameters"]


@pytest.mark.anyio
async def test_call_tool_executes_remote_tool() -> None:
    client = _client_with_server(_build_demo_server())

    result = await client.call_tool("mcp_demo_add", {"a": 2, "b": 5})

    assert result.is_error is False
    assert result.tool_name == "add"
    assert result.server_name == "demo"
    assert "7" in result.text


@pytest.mark.anyio
async def test_call_tool_resolves_index_without_explicit_list() -> None:
    client = _client_with_server(_build_demo_server())

    result = await client.call_tool("mcp_demo_echo", {"text": "hi mcp"})

    assert result.is_error is False
    assert "hi mcp" in result.text


@pytest.mark.anyio
async def test_call_unknown_tool_raises() -> None:
    client = _client_with_server(_build_demo_server())
    await client.list_tools()

    with pytest.raises(MCPClientError):
        await client.call_tool("mcp_demo_missing", {})


@pytest.mark.anyio
async def test_disabled_client_degrades_to_empty() -> None:
    client = MCPClient([])

    assert client.enabled is False
    assert await client.list_tools() == []


@pytest.mark.anyio
async def test_unreachable_server_is_skipped() -> None:
    @asynccontextmanager
    async def failing_connector(_config: MCPServerConfig):
        if True:
            raise RuntimeError("connection refused")
        yield None

    config = MCPServerConfig(name="broken", transport="stdio", command="python")
    client = MCPClient([config], connector=failing_connector)

    assert await client.list_tools() == []
    statuses, references = await client.list_servers_status()
    assert references == []
    assert statuses[0].connected is False
    assert statuses[0].error


def _build_rp_server() -> FastMCP:
    server = FastMCP("test-rp")

    @server.tool()
    def echo(text: str) -> str:
        """Echo back the text."""
        return text

    @server.resource("demo://greeting")
    def greeting() -> str:
        """A greeting resource."""
        return "hello resource"

    @server.prompt()
    def summarize(text: str) -> str:
        """Summarize prompt template."""
        return f"summarize: {text}"

    return server


@pytest.mark.anyio
async def test_inspect_discovers_tools_resources_prompts() -> None:
    client = _client_with_server(_build_rp_server())

    result = await client.inspect()

    assert [tool.qualified_name for tool in result.tools] == ["mcp_demo_echo"]
    assert any("greeting" in resource.uri for resource in result.resources)
    assert any(prompt.name == "summarize" for prompt in result.prompts)
    assert result.servers[0].connected is True
    assert result.servers[0].resource_count == 1
    assert result.servers[0].prompt_count == 1


@pytest.mark.anyio
async def test_read_resource_returns_text() -> None:
    client = _client_with_server(_build_rp_server())

    inspect_result = await client.inspect()
    uri = inspect_result.resources[0].uri
    result = await client.read_resource(uri)

    assert "hello resource" in result.text
