from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": deepcopy(self.parameters),
            },
        }


AGENT_TOOL_SCHEMAS: tuple[ToolSchema, ...] = (
    ToolSchema(
        name="search_docs",
        description=(
            "Search the user's indexed knowledge base and return relevant "
            "document chunks with sources."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's knowledge-base question.",
                    "minLength": 1,
                    "maxLength": 1000,
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of document chunks to retrieve.",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="calculator",
        description=(
            "Evaluate a safe arithmetic expression. Supports numbers, "
            "parentheses, +, -, *, /, //, %, and exponentiation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The arithmetic expression to calculate.",
                    "minLength": 1,
                    "maxLength": 120,
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="create_todo",
        description="Create a Markdown todo checklist from todo items or a todo request.",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Todo items or a natural-language todo request.",
                    "minLength": 1,
                    "maxLength": 2000,
                }
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="summarize_file",
        description=(
            "Summarize a safe local .md or .txt file inside README.md, docs/, "
            "or data/uploads/."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Safe relative file path to summarize.",
                    "minLength": 1,
                    "maxLength": 260,
                }
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="draft_weekly_report",
        description=(
            "Draft a Markdown weekly report from completed work, blockers, "
            "next steps, and notes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Weekly report source material.",
                    "minLength": 1,
                    "maxLength": 5000,
                }
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="query_database",
        description=(
            "Query structured job application records with safe read-only SQL. "
            "Use it for questions about companies, roles, statuses, channels, "
            "interviews, offers, and application statistics."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's job-application database question.",
                    "minLength": 1,
                    "maxLength": 1000,
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
)

_TOOL_SCHEMAS_BY_NAME = {schema.name: schema for schema in AGENT_TOOL_SCHEMAS}


def list_tool_names() -> list[str]:
    return [schema.name for schema in AGENT_TOOL_SCHEMAS]


def list_tool_schemas() -> list[ToolSchema]:
    return list(AGENT_TOOL_SCHEMAS)


def get_tool_schema(name: str) -> ToolSchema:
    return _TOOL_SCHEMAS_BY_NAME[name]


def list_openai_tools(tool_names: Iterable[str] | None = None) -> list[dict[str, Any]]:
    schemas = (
        (get_tool_schema(name) for name in tool_names)
        if tool_names is not None
        else AGENT_TOOL_SCHEMAS
    )
    return [schema.to_openai_tool() for schema in schemas]
