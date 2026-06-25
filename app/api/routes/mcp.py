from fastapi import APIRouter, Depends

from app.api.dependencies import get_mcp_client
from app.models.mcp import (
    MCPCapabilitiesResponse,
    MCPServersResponse,
    MCPToolsResponse,
)
from app.services.mcp_client import MCPClient

router = APIRouter(tags=["mcp"])


@router.get("/mcp/tools", response_model=MCPToolsResponse)
async def list_mcp_tools(
    mcp_client: MCPClient = Depends(get_mcp_client),
) -> MCPToolsResponse:
    references = await mcp_client.list_tools()
    return MCPToolsResponse(
        enabled=mcp_client.enabled,
        config_path=mcp_client.config_path,
        server_count=mcp_client.server_count,
        tool_count=len(references),
        tools=[reference.to_info() for reference in references],
    )


@router.get("/mcp/servers", response_model=MCPServersResponse)
async def list_mcp_servers(
    mcp_client: MCPClient = Depends(get_mcp_client),
) -> MCPServersResponse:
    statuses, _references = await mcp_client.list_servers_status()
    return MCPServersResponse(
        enabled=mcp_client.enabled,
        config_path=mcp_client.config_path,
        server_count=mcp_client.server_count,
        servers=statuses,
    )


@router.get("/mcp/capabilities", response_model=MCPCapabilitiesResponse)
async def get_mcp_capabilities(
    mcp_client: MCPClient = Depends(get_mcp_client),
) -> MCPCapabilitiesResponse:
    result = await mcp_client.inspect()
    return MCPCapabilitiesResponse(
        enabled=mcp_client.enabled,
        config_path=mcp_client.config_path,
        server_count=mcp_client.server_count,
        servers=result.servers,
        tools=[tool.to_info() for tool in result.tools],
        resources=[resource.to_info() for resource in result.resources],
        prompts=[prompt.to_info() for prompt in result.prompts],
    )
