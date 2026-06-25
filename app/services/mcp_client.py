"""MCP (Model Context Protocol) client manager.

Connects to external MCP servers (stdio or streamable HTTP), discovers their
tools, and calls them. Discovered tools are exposed to the LLM as additional
OpenAI-compatible function tools, so the agent can call external MCP tools the
same way it calls built-in tools.

Design choices for this first version:
- Pluggable + graceful degradation: when MCP is disabled or no server config is
  found, ``list_tools()`` returns ``[]`` and the agent behaves exactly as before.
  A single unreachable server is skipped, not fatal.
- Per-operation connections: each ``list_tools`` / ``call_tool`` opens a fresh
  session and closes it. Simple and robust for a local demo; a production setup
  would pool persistent sessions (documented as a known boundary).
- Testable: the transport ``connector`` is injectable, so unit tests use an
  in-memory MCP session instead of spawning subprocesses.
- Namespacing: tool names are exposed as ``mcp_<server>_<tool>`` (sanitized to a
  valid OpenAI function name) to avoid clashing with built-in tools.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.models.mcp import (
    MCPPromptInfo,
    MCPResourceInfo,
    MCPServerConfig,
    MCPServerStatus,
    MCPToolInfo,
    load_mcp_server_configs,
)


class MCPClientError(Exception):
    """Raised when an MCP operation fails in a non-recoverable way."""


@dataclass(frozen=True)
class MCPToolReference:
    server_name: str
    tool_name: str
    qualified_name: str
    description: str
    input_schema: dict[str, Any]

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": self.description,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }

    def to_info(self) -> MCPToolInfo:
        return MCPToolInfo(
            server=self.server_name,
            name=self.tool_name,
            qualified_name=self.qualified_name,
            description=self.description,
            input_schema=self.input_schema,
        )


@dataclass(frozen=True)
class MCPToolCallResult:
    qualified_name: str
    server_name: str
    tool_name: str
    text: str
    is_error: bool


@dataclass(frozen=True)
class MCPResourceReference:
    server_name: str
    name: str
    uri: str
    description: str
    mime_type: str

    def to_info(self) -> MCPResourceInfo:
        return MCPResourceInfo(
            server=self.server_name,
            name=self.name,
            uri=self.uri,
            description=self.description,
            mime_type=self.mime_type,
        )


@dataclass(frozen=True)
class MCPPromptReference:
    server_name: str
    name: str
    description: str
    arguments: list[dict[str, Any]]

    def to_info(self) -> MCPPromptInfo:
        return MCPPromptInfo(
            server=self.server_name,
            name=self.name,
            description=self.description,
            arguments=self.arguments,
        )


@dataclass(frozen=True)
class MCPResourceReadResult:
    uri: str
    server_name: str
    text: str
    mime_type: str


@dataclass(frozen=True)
class MCPInspectResult:
    servers: list[MCPServerStatus]
    tools: list["MCPToolReference"]
    resources: list[MCPResourceReference]
    prompts: list[MCPPromptReference]


SessionConnector = Callable[[MCPServerConfig], AbstractAsyncContextManager[Any]]


def _sanitize(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("_") or "x"


def build_qualified_name(server_name: str, tool_name: str) -> str:
    qualified = f"mcp_{_sanitize(server_name)}_{_sanitize(tool_name)}"
    return qualified[:64]


class MCPClient:
    def __init__(
        self,
        configs: list[MCPServerConfig],
        *,
        config_path: str = "",
        tool_timeout_seconds: float = 30.0,
        max_tools: int = 32,
        connector: SessionConnector | None = None,
    ) -> None:
        self._configs = configs
        self._config_path = config_path
        self._tool_timeout_seconds = tool_timeout_seconds
        self._max_tools = max_tools
        self._connector = connector or _make_default_connector(tool_timeout_seconds)
        self._config_by_name = {config.name: config for config in configs}
        self._tool_index: dict[str, MCPToolReference] = {}
        self._resource_index: dict[str, MCPServerConfig] = {}

    @classmethod
    def from_settings(cls, *, connector: SessionConnector | None = None) -> "MCPClient":
        configs = (
            load_mcp_server_configs(settings.mcp_config_path)
            if settings.mcp_enabled
            else []
        )
        return cls(
            configs,
            config_path=settings.mcp_config_path,
            tool_timeout_seconds=settings.mcp_tool_timeout_seconds,
            max_tools=settings.mcp_max_tools,
            connector=connector,
        )

    @property
    def enabled(self) -> bool:
        return bool(self._configs)

    @property
    def config_path(self) -> str:
        return self._config_path

    @property
    def server_count(self) -> int:
        return len(self._configs)

    async def list_tools(self) -> list[MCPToolReference]:
        references: list[MCPToolReference] = []
        for config in self._configs:
            try:
                references.extend(await self._list_server_tools(config))
            except Exception:  # noqa: BLE001 - external server, degrade gracefully
                continue
        references = references[: self._max_tools]
        self._tool_index = {ref.qualified_name: ref for ref in references}
        return references

    async def list_servers_status(
        self,
    ) -> tuple[list[MCPServerStatus], list[MCPToolReference]]:
        statuses: list[MCPServerStatus] = []
        references: list[MCPToolReference] = []
        for config in self._configs:
            try:
                server_tools = await self._list_server_tools(config)
            except Exception as exc:  # noqa: BLE001 - external server boundary
                statuses.append(
                    MCPServerStatus(
                        name=config.name,
                        transport=config.transport,
                        connected=False,
                        tool_count=0,
                        error=str(exc) or exc.__class__.__name__,
                    )
                )
                continue
            references.extend(server_tools)
            statuses.append(
                MCPServerStatus(
                    name=config.name,
                    transport=config.transport,
                    connected=True,
                    tool_count=len(server_tools),
                )
            )
        references = references[: self._max_tools]
        self._tool_index = {ref.qualified_name: ref for ref in references}
        return statuses, references

    async def call_tool(
        self, qualified_name: str, arguments: dict[str, Any]
    ) -> MCPToolCallResult:
        if not self._tool_index:
            await self.list_tools()
        reference = self._tool_index.get(qualified_name)
        if reference is None:
            raise MCPClientError(f"Unknown MCP tool: {qualified_name}")
        config = self._config_by_name.get(reference.server_name)
        if config is None:
            raise MCPClientError(f"Unknown MCP server: {reference.server_name}")

        async with self._connector(config) as session:
            result = await session.call_tool(reference.tool_name, arguments)
        text, is_error = _extract_call_result(result)
        return MCPToolCallResult(
            qualified_name=qualified_name,
            server_name=reference.server_name,
            tool_name=reference.tool_name,
            text=text,
            is_error=is_error,
        )

    async def _list_server_tools(
        self, config: MCPServerConfig
    ) -> list[MCPToolReference]:
        async with self._connector(config) as session:
            result = await session.list_tools()
        return [
            MCPToolReference(
                server_name=config.name,
                tool_name=tool.name,
                qualified_name=build_qualified_name(config.name, tool.name),
                description=tool.description or "",
                input_schema=_normalize_input_schema(tool.inputSchema),
            )
            for tool in result.tools
        ]

    async def inspect(self) -> MCPInspectResult:
        servers: list[MCPServerStatus] = []
        tools: list[MCPToolReference] = []
        resources: list[MCPResourceReference] = []
        prompts: list[MCPPromptReference] = []
        for config in self._configs:
            try:
                server_tools, server_resources, server_prompts = (
                    await self._inspect_server(config)
                )
            except Exception as exc:  # noqa: BLE001 - external server boundary
                servers.append(
                    MCPServerStatus(
                        name=config.name,
                        transport=config.transport,
                        connected=False,
                        tool_count=0,
                        error=str(exc) or exc.__class__.__name__,
                    )
                )
                continue
            tools.extend(server_tools)
            resources.extend(server_resources)
            prompts.extend(server_prompts)
            servers.append(
                MCPServerStatus(
                    name=config.name,
                    transport=config.transport,
                    connected=True,
                    tool_count=len(server_tools),
                    resource_count=len(server_resources),
                    prompt_count=len(server_prompts),
                )
            )
        tools = tools[: self._max_tools]
        self._tool_index = {ref.qualified_name: ref for ref in tools}
        self._resource_index = {
            ref.uri: self._config_by_name[ref.server_name]
            for ref in resources
            if ref.server_name in self._config_by_name
        }
        return MCPInspectResult(
            servers=servers, tools=tools, resources=resources, prompts=prompts
        )

    async def read_resource(self, uri: str) -> MCPResourceReadResult:
        if not self._resource_index:
            await self.inspect()
        config = self._resource_index.get(uri)
        if config is None:
            raise MCPClientError(f"Unknown MCP resource: {uri}")
        async with self._connector(config) as session:
            result = await session.read_resource(uri)
        text, mime_type = _extract_resource_contents(result)
        return MCPResourceReadResult(
            uri=uri, server_name=config.name, text=text, mime_type=mime_type
        )

    async def _inspect_server(
        self, config: MCPServerConfig
    ) -> tuple[
        list[MCPToolReference],
        list[MCPResourceReference],
        list[MCPPromptReference],
    ]:
        async with self._connector(config) as session:
            tools = await _safe_list_tools(session, config)
            resources = await _safe_list_resources(session, config)
            prompts = await _safe_list_prompts(session, config)
        return tools, resources, prompts


def _normalize_input_schema(schema: Any) -> dict[str, Any]:
    if isinstance(schema, dict):
        return schema
    return {"type": "object", "properties": {}}


def _extract_call_result(result: Any) -> tuple[str, bool]:
    is_error = bool(getattr(result, "isError", False))
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    if not parts:
        structured = getattr(result, "structuredContent", None)
        if structured:
            parts.append(json.dumps(structured, ensure_ascii=False))
    return "\n".join(parts), is_error


async def _safe_list_tools(
    session: Any, config: MCPServerConfig
) -> list[MCPToolReference]:
    try:
        result = await session.list_tools()
    except Exception:  # noqa: BLE001 - capability may be unsupported by the server
        return []
    return [
        MCPToolReference(
            server_name=config.name,
            tool_name=tool.name,
            qualified_name=build_qualified_name(config.name, tool.name),
            description=tool.description or "",
            input_schema=_normalize_input_schema(tool.inputSchema),
        )
        for tool in result.tools
    ]


async def _safe_list_resources(
    session: Any, config: MCPServerConfig
) -> list[MCPResourceReference]:
    try:
        result = await session.list_resources()
    except Exception:  # noqa: BLE001 - capability may be unsupported by the server
        return []
    return [
        MCPResourceReference(
            server_name=config.name,
            name=getattr(resource, "name", "") or "",
            uri=str(getattr(resource, "uri", "")),
            description=getattr(resource, "description", "") or "",
            mime_type=getattr(resource, "mimeType", "") or "",
        )
        for resource in result.resources
    ]


async def _safe_list_prompts(
    session: Any, config: MCPServerConfig
) -> list[MCPPromptReference]:
    try:
        result = await session.list_prompts()
    except Exception:  # noqa: BLE001 - capability may be unsupported by the server
        return []
    return [
        MCPPromptReference(
            server_name=config.name,
            name=getattr(prompt, "name", "") or "",
            description=getattr(prompt, "description", "") or "",
            arguments=[
                {
                    "name": getattr(arg, "name", ""),
                    "description": getattr(arg, "description", "") or "",
                    "required": bool(getattr(arg, "required", False)),
                }
                for arg in (getattr(prompt, "arguments", None) or [])
            ],
        )
        for prompt in result.prompts
    ]


def _extract_resource_contents(result: Any) -> tuple[str, str]:
    parts: list[str] = []
    mime_type = ""
    for content in getattr(result, "contents", None) or []:
        text = getattr(content, "text", None)
        if text:
            parts.append(text)
        if not mime_type:
            mime_type = getattr(content, "mimeType", "") or ""
    return "\n".join(parts), mime_type


def _make_default_connector(timeout_seconds: float) -> SessionConnector:
    def connector(config: MCPServerConfig) -> AbstractAsyncContextManager[Any]:
        return _default_connect(config, timeout_seconds=timeout_seconds)

    return connector


@asynccontextmanager
async def _default_connect(
    config: MCPServerConfig, *, timeout_seconds: float
) -> AsyncIterator[Any]:
    from mcp import ClientSession

    read_timeout = timedelta(seconds=timeout_seconds)
    transport = (config.transport or "stdio").lower()

    if transport in {"stdio", "local"}:
        if not config.command:
            raise MCPClientError(
                f"MCP server '{config.name}' is missing 'command' for stdio transport."
            )
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env or None,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=read_timeout
            ) as session:
                await session.initialize()
                yield session
        return

    if transport in {"streamable_http", "http", "streamable-http"}:
        if not config.url:
            raise MCPClientError(
                f"MCP server '{config.name}' is missing 'url' for HTTP transport."
            )
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(
            config.url, headers=config.headers or None, timeout=timedelta(seconds=timeout_seconds)
        ) as (read, write, _get_session_id):
            async with ClientSession(
                read, write, read_timeout_seconds=read_timeout
            ) as session:
                await session.initialize()
                yield session
        return

    raise MCPClientError(f"Unsupported MCP transport: {config.transport}")


def build_mcp_client_from_settings() -> MCPClient:
    return MCPClient.from_settings()
