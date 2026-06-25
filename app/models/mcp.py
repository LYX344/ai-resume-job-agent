"""MCP (Model Context Protocol) configuration models and a tolerant loader.

The agent can connect to external MCP servers and expose their tools to the LLM
as additional function-calling tools. This module only defines the config shape,
a fault-tolerant loader, and the API response models; the runtime client lives
in ``app/services/mcp_client.py``.

Server config follows the de-facto ``mcpServers`` shape used by Claude Desktop /
Cursor, for example::

    {
      "mcpServers": {
        "demo": {"transport": "stdio", "command": "python", "args": ["server.py"]},
        "remote": {"transport": "streamable_http", "url": "http://127.0.0.1:9000/mcp"}
      }
    }
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class MCPServerConfig(BaseModel):
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


def load_mcp_server_configs(path: str | Path) -> list[MCPServerConfig]:
    """Load MCP server configs from a JSON file.

    Returns an empty list when the file is missing, unreadable, or malformed so
    a misconfigured MCP file never breaks the rest of the application.
    """

    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []

    servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers, dict):
        return []

    configs: list[MCPServerConfig] = []
    for name, entry in servers.items():
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        try:
            configs.append(
                MCPServerConfig(
                    name=str(name),
                    transport=str(entry.get("transport", "stdio")),
                    command=entry.get("command"),
                    args=[str(arg) for arg in (entry.get("args") or [])],
                    env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
                    url=entry.get("url"),
                    headers={
                        str(k): str(v) for k, v in (entry.get("headers") or {}).items()
                    },
                )
            )
        except (ValidationError, TypeError, AttributeError):
            continue
    return configs


class MCPToolInfo(BaseModel):
    server: str
    name: str
    qualified_name: str
    description: str = ""
    input_schema: dict = Field(default_factory=dict)


class MCPServerStatus(BaseModel):
    name: str
    transport: str
    connected: bool
    tool_count: int
    resource_count: int = 0
    prompt_count: int = 0
    error: str | None = None


class MCPResourceInfo(BaseModel):
    server: str
    name: str
    uri: str
    description: str = ""
    mime_type: str = ""


class MCPPromptInfo(BaseModel):
    server: str
    name: str
    description: str = ""
    arguments: list[dict] = Field(default_factory=list)


class MCPToolsResponse(BaseModel):
    enabled: bool
    config_path: str
    server_count: int
    tool_count: int
    tools: list[MCPToolInfo] = Field(default_factory=list)


class MCPServersResponse(BaseModel):
    enabled: bool
    config_path: str
    server_count: int
    servers: list[MCPServerStatus] = Field(default_factory=list)


class MCPCapabilitiesResponse(BaseModel):
    enabled: bool
    config_path: str
    server_count: int
    servers: list[MCPServerStatus] = Field(default_factory=list)
    tools: list[MCPToolInfo] = Field(default_factory=list)
    resources: list[MCPResourceInfo] = Field(default_factory=list)
    prompts: list[MCPPromptInfo] = Field(default_factory=list)
