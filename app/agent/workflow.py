from typing import Any, Literal
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.checkpoint import LocalFileCheckpointSaver
from app.agent.state import AgentState
from app.core.config import settings
from app.memory.profile import (
    extract_memory_updates,
    format_memory_updates,
    format_memory_context,
    merge_memory_profile,
)
from app.memory.session import append_session_turn
from app.models.agent import (
    AgentCheckpointInfo,
    AgentCheckpointHistoryResponse,
    AgentCheckpointSnapshotResponse,
    AgentRunRequest,
    AgentRunResponse,
    AgentStep,
)
from app.models.chat import ChatMessage
from app.models.memory import MemoryProfile
from app.models.session import SessionState
from app.rag.answerer import answer_from_sources
from app.services.embedding_client import EmbeddingClient
from app.services.llm_client import (
    ChatPayloadMessage,
    LLMChatResult,
    LLMProviderError,
    LLMToolCall,
    OpenAICompatibleClient,
)
from app.services.mcp_client import MCPClient
from app.services.mysql_client import MySQLStore
from app.services.redis_client import RedisStore
from app.tools.calculator import calculate, extract_calculation_expression
from app.tools.create_todo import create_todo, extract_todo_text
from app.tools.draft_weekly_report import (
    draft_weekly_report,
    extract_weekly_report_text,
)
from app.tools.search_docs import search_docs
from app.tools.query_database import is_job_application_query, query_database
from app.tools.llm_executor import (
    LLM_EXECUTABLE_TOOL_NAMES,
    ExecutedToolCall,
    MCPToolCaller,
    execute_llm_tool_calls,
)
from app.tools.registry import list_openai_tools
from app.tools.summarize_file import extract_summary_file_path, summarize_file


MAX_LLM_TOOL_CALL_ROUNDS = 3
AGENT_CHECKPOINT_BACKEND = settings.agent_checkpoint_backend
AGENT_CHECKPOINT_DURABLE = AGENT_CHECKPOINT_BACKEND == "local_file"
AGENT_CHECKPOINT_PRODUCTION_READY = False
_AGENT_CHECKPOINTER = None
AGENT_CHECKPOINT_NOTES = [
    "local_file checkpoint supports single-machine demo reloads only.",
    "It is not an official Redis/Postgres production checkpointer.",
    "Resume and human-in-the-loop recovery are documented as planned capabilities.",
]


async def run_agent_workflow(
    request: AgentRunRequest,
    *,
    redis_store: RedisStore,
    mysql_store: MySQLStore,
    embedding_client: EmbeddingClient,
    llm_client: OpenAICompatibleClient,
    mcp_client: MCPClient | None = None,
) -> AgentRunResponse:
    state = AgentState(
        query=request.query,
        session_id=request.session_id,
        use_knowledge_base=request.use_knowledge_base,
        top_k=request.top_k,
        model=request.model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
    checkpoint_thread_id = _build_checkpoint_thread_id(request.session_id)
    checkpoint_config = _build_checkpoint_config(checkpoint_thread_id)
    state.checkpoint = AgentCheckpointInfo(thread_id=checkpoint_thread_id)

    graph = _build_agent_graph(
        redis_store=redis_store,
        mysql_store=mysql_store,
        embedding_client=embedding_client,
        llm_client=llm_client,
        mcp_client=mcp_client,
    )
    final_state = _coerce_agent_state(
        await graph.ainvoke(_state_update(state), config=checkpoint_config)
    )
    checkpoint_snapshot = await graph.aget_state(checkpoint_config)
    final_state.checkpoint = _checkpoint_info_from_snapshot(
        checkpoint_snapshot,
        thread_id=checkpoint_thread_id,
    )
    return _to_response(final_state)


def get_agent_checkpoint_snapshot(
    thread_id: str,
) -> AgentCheckpointSnapshotResponse | None:
    checkpoint_tuple = _get_agent_checkpointer().get_tuple(
        _build_checkpoint_config(thread_id)
    )
    if checkpoint_tuple is None:
        return None

    return _checkpoint_snapshot_from_tuple(
        checkpoint_tuple,
        fallback_thread_id=thread_id,
    )


def list_agent_checkpoint_snapshots(
    thread_id: str,
    *,
    limit: int,
) -> AgentCheckpointHistoryResponse | None:
    checkpoint_tuples = list(
        _get_agent_checkpointer().list(
            _build_checkpoint_config(thread_id),
            limit=limit,
        )
    )
    if not checkpoint_tuples:
        return None

    snapshots = [
        _checkpoint_snapshot_from_tuple(
            checkpoint_tuple,
            fallback_thread_id=thread_id,
        )
        for checkpoint_tuple in checkpoint_tuples
    ]
    return AgentCheckpointHistoryResponse(
        thread_id=thread_id,
        checkpoint_count=len(snapshots),
        limit=limit,
        checkpoints=snapshots,
    )


def _checkpoint_snapshot_from_tuple(
    checkpoint_tuple: Any,
    *,
    fallback_thread_id: str,
) -> AgentCheckpointSnapshotResponse:
    config = checkpoint_tuple.config.get("configurable", {})
    parent_config = (checkpoint_tuple.parent_config or {}).get("configurable", {})
    metadata = checkpoint_tuple.metadata or {}
    checkpoint = checkpoint_tuple.checkpoint or {}
    channel_values = (
        checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    )
    return AgentCheckpointSnapshotResponse(
        thread_id=config.get("thread_id", fallback_thread_id),
        checkpoint_id=config.get("checkpoint_id"),
        checkpoint_namespace=config.get("checkpoint_ns") or "",
        step=metadata.get("step"),
        created_at=checkpoint.get("ts") if isinstance(checkpoint, dict) else None,
        backend=AGENT_CHECKPOINT_BACKEND,
        durable=AGENT_CHECKPOINT_DURABLE,
        production_ready=AGENT_CHECKPOINT_PRODUCTION_READY,
        parent_checkpoint_id=parent_config.get("checkpoint_id"),
        pending_write_count=len(checkpoint_tuple.pending_writes or []),
        state_channel_keys=sorted(str(key) for key in channel_values.keys()),
        resume_supported=False,
        human_in_the_loop_supported=False,
        notes=AGENT_CHECKPOINT_NOTES,
    )


def _build_agent_graph(
    *,
    redis_store: RedisStore,
    mysql_store: MySQLStore,
    embedding_client: EmbeddingClient,
    llm_client: OpenAICompatibleClient,
    mcp_client: MCPClient | None = None,
    checkpointer: BaseCheckpointSaver | None = _AGENT_CHECKPOINTER,
):
    builder = StateGraph(AgentState)

    async def load_memory_node(raw_state: dict[str, Any] | AgentState) -> dict[str, Any]:
        state = _coerce_agent_state(raw_state)
        await load_memory(state, redis_store=redis_store)
        return _state_update(state)

    async def understand_intent_node(
        raw_state: dict[str, Any] | AgentState,
    ) -> dict[str, Any]:
        state = _coerce_agent_state(raw_state)
        understand_intent(state)
        return _state_update(state)

    async def decide_retrieval_node(
        raw_state: dict[str, Any] | AgentState,
    ) -> dict[str, Any]:
        state = _coerce_agent_state(raw_state)
        decide_retrieval(state)
        return _state_update(state)

    async def call_tools_node(raw_state: dict[str, Any] | AgentState) -> dict[str, Any]:
        state = _coerce_agent_state(raw_state)
        await call_tools(
            state,
            redis_store=redis_store,
            mysql_store=mysql_store,
            embedding_client=embedding_client,
        )
        return _state_update(state)

    async def skip_tools_node(raw_state: dict[str, Any] | AgentState) -> dict[str, Any]:
        state = _coerce_agent_state(raw_state)
        skip_tools(state)
        return _state_update(state)

    async def generate_answer_node(
        raw_state: dict[str, Any] | AgentState,
    ) -> dict[str, Any]:
        state = _coerce_agent_state(raw_state)
        await generate_answer(
            state,
            llm_client=llm_client,
            mcp_client=mcp_client,
        )
        return _state_update(state)

    async def save_trace_node(raw_state: dict[str, Any] | AgentState) -> dict[str, Any]:
        state = _coerce_agent_state(raw_state)
        await save_trace(state, redis_store=redis_store)
        return _state_update(state)

    builder.add_node("load_memory", load_memory_node)
    builder.add_node("understand_intent", understand_intent_node)
    builder.add_node("decide_retrieval", decide_retrieval_node)
    builder.add_node("call_tools", call_tools_node)
    builder.add_node("skip_tools", skip_tools_node)
    builder.add_node("generate_answer", generate_answer_node)
    builder.add_node("save_trace", save_trace_node)

    builder.add_edge(START, "load_memory")
    builder.add_edge("load_memory", "understand_intent")
    builder.add_edge("understand_intent", "decide_retrieval")
    builder.add_conditional_edges(
        "decide_retrieval",
        _route_after_decide_retrieval,
        {"call_tools": "call_tools", "skip_tools": "skip_tools"},
    )
    builder.add_edge("call_tools", "generate_answer")
    builder.add_edge("skip_tools", "generate_answer")
    builder.add_edge("generate_answer", "save_trace")
    builder.add_edge("save_trace", END)

    compiled_checkpointer = (
        checkpointer if checkpointer is not None else _get_agent_checkpointer()
    )
    return builder.compile(checkpointer=compiled_checkpointer)


def _get_agent_checkpointer() -> BaseCheckpointSaver:
    global _AGENT_CHECKPOINTER
    if _AGENT_CHECKPOINTER is None:
        _AGENT_CHECKPOINTER = _build_agent_checkpointer()
    return _AGENT_CHECKPOINTER


def _build_agent_checkpointer() -> BaseCheckpointSaver:
    if settings.agent_checkpoint_backend == "in_memory":
        return InMemorySaver()
    if settings.agent_checkpoint_backend == "local_file":
        return LocalFileCheckpointSaver(settings.agent_checkpoint_path)
    raise ValueError(
        "Unsupported AGENT_CHECKPOINT_BACKEND: "
        f"{settings.agent_checkpoint_backend}"
    )


def _build_checkpoint_thread_id(session_id: str | None) -> str:
    if session_id:
        return f"agent-session:{session_id}"
    return f"agent-request:{uuid4().hex}"


def _build_checkpoint_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def _checkpoint_info_from_snapshot(
    snapshot: Any,
    *,
    thread_id: str,
) -> AgentCheckpointInfo:
    configurable = snapshot.config.get("configurable", {})
    metadata = snapshot.metadata or {}
    return AgentCheckpointInfo(
        thread_id=thread_id,
        checkpoint_id=configurable.get("checkpoint_id"),
        checkpoint_namespace=configurable.get("checkpoint_ns") or "",
        step=metadata.get("step"),
        created_at=snapshot.created_at,
        backend=AGENT_CHECKPOINT_BACKEND,
        durable=AGENT_CHECKPOINT_DURABLE,
        production_ready=AGENT_CHECKPOINT_PRODUCTION_READY,
    )


def _route_after_decide_retrieval(
    raw_state: dict[str, Any] | AgentState,
) -> Literal["call_tools", "skip_tools"]:
    state = _coerce_agent_state(raw_state)
    if state.selected_tool is not None or state.needs_retrieval:
        return "call_tools"
    return "skip_tools"


def _coerce_agent_state(raw_state: dict[str, Any] | AgentState) -> AgentState:
    if isinstance(raw_state, AgentState):
        return raw_state
    return AgentState.model_validate(raw_state)


def _state_update(state: AgentState) -> dict[str, Any]:
    return state.model_dump(mode="python")


async def load_memory(state: AgentState, *, redis_store: RedisStore) -> None:
    if state.session_id is None:
        return

    state.session = await redis_store.get_session(state.session_id) or SessionState(
        session_id=state.session_id,
    )
    state.memory_profile = await redis_store.get_memory_profile() or MemoryProfile()
    state.memory_used = True
    state.steps.append(
        AgentStep(
            name="load_memory",
            status="completed",
            detail="Loaded short-term session history and long-term memory profile.",
            data={
                "session_id": state.session_id,
                "session_message_count": len(state.session.messages),
                "memory_item_count": state.memory_profile.item_count,
            },
        )
    )


def understand_intent(state: AgentState) -> None:
    expression = extract_calculation_expression(state.query)
    todo_text = extract_todo_text(state.query)
    weekly_report_text = extract_weekly_report_text(state.query)
    summary_file_path = extract_summary_file_path(state.query)
    memory_updates = extract_memory_updates(state.query)
    if expression is not None:
        state.intent = "calculation"
        state.selected_tool = "calculator"
        state.tool_result["expression"] = expression
    elif todo_text is not None:
        state.intent = "todo_creation"
        state.selected_tool = "create_todo"
        state.tool_result["todo_text"] = todo_text
    elif weekly_report_text is not None:
        state.intent = "weekly_report_draft"
        state.selected_tool = "draft_weekly_report"
        state.tool_result["weekly_report_text"] = weekly_report_text
    elif summary_file_path is not None:
        state.intent = "file_summary"
        state.selected_tool = "summarize_file"
        state.tool_result["file_path"] = summary_file_path
    elif any(memory_updates.values()):
        state.intent = "memory_update"
        state.selected_tool = "memory_profile"
        state.tool_result["memory_updates"] = memory_updates
    elif is_job_application_query(state.query):
        state.intent = "database_query"
        state.selected_tool = "query_database"
        state.tool_result["database_query"] = state.query
    else:
        state.intent = "knowledge_query" if state.use_knowledge_base else "general_chat"
    state.steps.append(
        AgentStep(
            name="understand_intent",
            status="completed",
            detail="Classified request intent using request flags.",
            data={"intent": state.intent, "selected_tool": state.selected_tool},
        )
    )


def decide_retrieval(state: AgentState) -> None:
    state.needs_retrieval = state.intent == "knowledge_query"
    state.steps.append(
        AgentStep(
            name="decide_retrieval",
            status="completed",
            detail="Decided whether to use knowledge base retrieval.",
            data={"needs_retrieval": state.needs_retrieval},
        )
    )


def skip_tools(state: AgentState) -> None:
    state.steps.append(
        AgentStep(
            name="call_tools",
            status="skipped",
            detail="No tool was needed for this request.",
            data={"tool": None},
        )
    )


async def call_tools(
    state: AgentState,
    *,
    redis_store: RedisStore,
    mysql_store: MySQLStore,
    embedding_client: EmbeddingClient,
) -> None:
    if state.selected_tool == "calculator":
        result = calculate(state.tool_result["expression"])
        state.tool_result = {
            "tool": "calculator",
            "expression": result.expression,
            "value": result.value,
            "display_value": result.display_value,
        }
        state.steps.append(
            AgentStep(
                name="call_tools",
                status="completed",
                detail="Called calculator tool for arithmetic evaluation.",
                data={
                    "tool": "calculator",
                    "expression": result.expression,
                    "value": result.value,
                },
            )
        )
        return

    if state.selected_tool == "create_todo":
        result = create_todo(state.tool_result["todo_text"])
        state.tool_result = {
            "tool": "create_todo",
            "items": [item.title for item in result.items],
            "markdown": result.to_markdown(),
        }
        state.steps.append(
            AgentStep(
                name="call_tools",
                status="completed",
                detail="Called create_todo tool for checklist generation.",
                data={
                    "tool": "create_todo",
                    "item_count": len(result.items),
                },
            )
        )
        return

    if state.selected_tool == "draft_weekly_report":
        result = draft_weekly_report(state.tool_result["weekly_report_text"])
        state.tool_result = {
            "tool": "draft_weekly_report",
            "completed": result.completed,
            "blockers": result.blockers,
            "next_steps": result.next_steps,
            "markdown": result.to_markdown(),
        }
        state.steps.append(
            AgentStep(
                name="call_tools",
                status="completed",
                detail="Called draft_weekly_report tool for weekly report drafting.",
                data={
                    "tool": "draft_weekly_report",
                    "completed_count": len(result.completed),
                    "next_step_count": len(result.next_steps),
                },
            )
        )
        return

    if state.selected_tool == "memory_profile":
        if state.session_id is None:
            raise ValueError("session_id is required to save memory.")
        updates = state.tool_result["memory_updates"]
        state.tool_result = {
            "tool": "memory_profile",
            "memory_updates": updates,
            "markdown": format_memory_updates(updates),
        }
        state.steps.append(
            AgentStep(
                name="call_tools",
                status="completed",
                detail="Prepared explicit long-term memory updates.",
                data={
                    "tool": "memory_profile",
                    "memory_update_count": sum(len(items) for items in updates.values()),
                },
            )
        )
        return

    if state.selected_tool == "summarize_file":
        result = summarize_file(state.tool_result["file_path"])
        state.tool_result = {
            "tool": "summarize_file",
            "file_path": result.file_path,
            "line_count": result.line_count,
            "char_count": result.char_count,
            "markdown": result.to_markdown(),
        }
        state.steps.append(
            AgentStep(
                name="call_tools",
                status="completed",
                detail="Called summarize_file tool for local file summarization.",
                data={
                    "tool": "summarize_file",
                    "file_path": result.file_path,
                },
            )
        )
        return

    if state.selected_tool == "query_database":
        result = await query_database(
            state.tool_result["database_query"],
            database_store=mysql_store,
        )
        state.tool_result = {
            "tool": "query_database",
            "query": result.query,
            "sql": result.sql,
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "markdown": result.markdown,
        }
        state.steps.append(
            AgentStep(
                name="call_tools",
                status="completed",
                detail="Called query_database tool for structured job application data.",
                data={
                    "tool": "query_database",
                    "sql": result.sql,
                    "row_count": result.row_count,
                },
            )
        )
        return

    if not state.needs_retrieval:
        skip_tools(state)
        return

    state.sources = await search_docs(
        state.query,
        top_k=state.top_k,
        embedding_client=embedding_client,
        redis_store=redis_store,
    )
    state.steps.append(
        AgentStep(
            name="call_tools",
            status="completed",
            detail="Called search_docs tool for knowledge base retrieval.",
            data={"tool": "search_docs", "source_count": len(state.sources)},
        )
    )


async def generate_answer(
    state: AgentState,
    *,
    llm_client: OpenAICompatibleClient,
    mcp_client: MCPClient | None = None,
) -> None:
    if state.selected_tool == "calculator":
        state.answer = (
            f"{state.tool_result['expression']} = {state.tool_result['display_value']}"
        )
        state.steps.append(
            AgentStep(
                name="generate_answer",
                status="completed",
                detail="Returned deterministic calculator result without calling LLM.",
                data={"tool": "calculator"},
            )
        )
        return

    if state.selected_tool == "create_todo":
        state.answer = state.tool_result["markdown"]
        state.steps.append(
            AgentStep(
                name="generate_answer",
                status="completed",
                detail="Returned deterministic todo checklist without calling LLM.",
                data={"tool": "create_todo"},
            )
        )
        return

    if state.selected_tool == "draft_weekly_report":
        state.answer = state.tool_result["markdown"]
        state.steps.append(
            AgentStep(
                name="generate_answer",
                status="completed",
                detail="Returned deterministic weekly report draft without calling LLM.",
                data={"tool": "draft_weekly_report"},
            )
        )
        return

    if state.selected_tool == "memory_profile":
        state.answer = state.tool_result["markdown"]
        state.steps.append(
            AgentStep(
                name="generate_answer",
                status="completed",
                detail="Returned deterministic memory update confirmation without calling LLM.",
                data={"tool": "memory_profile"},
            )
        )
        return

    if state.selected_tool == "summarize_file":
        state.answer = state.tool_result["markdown"]
        state.steps.append(
            AgentStep(
                name="generate_answer",
                status="completed",
                detail="Returned deterministic file summary without calling LLM.",
                data={"tool": "summarize_file"},
            )
        )
        return

    if state.selected_tool == "query_database":
        state.answer = state.tool_result["markdown"]
        state.steps.append(
            AgentStep(
                name="generate_answer",
                status="completed",
                detail="Returned deterministic database query result without calling LLM.",
                data={
                    "tool": "query_database",
                    "row_count": state.tool_result["row_count"],
                },
            )
        )
        return

    if state.needs_retrieval:
        result = await answer_from_sources(
            state.query,
            llm_client=llm_client,
            sources=state.sources,
            memory_context=format_memory_context(state.memory_profile),
            model=state.model,
            temperature=state.temperature,
            max_tokens=state.max_tokens,
        )
        state.answer = result.answer
        state.sources = result.sources
        state.model = result.model
        state.finish_reason = result.finish_reason
        state.usage = result.usage
        state.steps.append(
            AgentStep(
                name="generate_answer",
                status="completed",
                detail="Generated answer from tool results.",
                data={"source_count": len(result.sources)},
            )
        )
        return

    tools = list_openai_tools(LLM_EXECUTABLE_TOOL_NAMES)
    mcp_tool_names: set[str] = set()
    mcp_caller: MCPToolCaller | None = None
    if mcp_client is not None and mcp_client.enabled:
        mcp_references = await mcp_client.list_tools()
        if mcp_references:
            tools = tools + [
                reference.to_openai_tool() for reference in mcp_references
            ]
            mcp_tool_names = {reference.qualified_name for reference in mcp_references}

            async def _call_mcp_tool(
                name: str, arguments: dict[str, Any]
            ) -> tuple[str, bool]:
                result = await mcp_client.call_tool(name, arguments)
                return result.text, result.is_error

            mcp_caller = _call_mcp_tool

    await _run_general_chat_with_bounded_tools(
        state,
        llm_client=llm_client,
        tools=tools,
        mcp_tool_names=mcp_tool_names,
        mcp_caller=mcp_caller,
    )
    state.steps.append(
        AgentStep(
            name="generate_answer",
            status="completed",
            detail=(
                "Generated answer without knowledge base retrieval and executed "
                "bounded LLM tool-call rounds when proposed."
            ),
            data={
                "tool_schema_count": len(tools),
                "mcp_tool_count": len(mcp_tool_names),
                "max_tool_call_rounds": MAX_LLM_TOOL_CALL_ROUNDS,
                "tool_call_round_count": state.tool_call_rounds,
                "tool_call_limit_reached": state.tool_call_limit_reached,
                "proposed_tool_call_count": len(state.proposed_tool_calls),
                "proposed_tool_calls": state.proposed_tool_calls,
                "executed_tool_call_count": len(state.executed_tool_calls),
                "executed_tool_calls": state.executed_tool_calls,
                "tool_error_category_counts": _summarize_tool_error_categories(
                    state.executed_tool_calls
                ),
                "provider_error": state.provider_error,
            },
        )
    )


async def save_trace(state: AgentState, *, redis_store: RedisStore) -> None:
    if state.session_id is None:
        state.steps.append(
            AgentStep(
                name="save_trace",
                status="skipped",
                detail="Trace persistence requires a session_id.",
            )
        )
        return

    session = state.session or SessionState(session_id=state.session_id)
    updated_session = append_session_turn(
        session,
        user_message=state.query,
        assistant_message=state.answer,
    )
    await redis_store.save_session(updated_session)

    profile = state.memory_profile or MemoryProfile()
    memory_updates = extract_memory_updates(state.query)
    updated_profile = merge_memory_profile(profile, memory_updates)
    if updated_profile != profile:
        await redis_store.save_memory_profile(updated_profile)
        state.memory_profile = updated_profile

    state.session = updated_session
    state.steps.append(
        AgentStep(
            name="save_trace",
            status="completed",
            detail="Saved session history and updated explicit long-term memory.",
            data={
                "session_id": state.session_id,
                "session_message_count": len(updated_session.messages),
                "memory_update_count": sum(len(items) for items in memory_updates.values()),
            },
        )
    )


def _build_general_chat_messages(state: AgentState) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    memory_context = format_memory_context(state.memory_profile)
    if memory_context:
        messages.append(
            ChatMessage(
                role="system",
                content=(
                    "以下是用户长期记忆。它只用于理解用户偏好和项目背景，"
                    "不能覆盖用户本轮明确指令。\n\n"
                    f"{memory_context}"
                ),
            )
        )
    if state.session is not None:
        messages.extend(state.session.messages[-8:])
    messages.append(ChatMessage(role="user", content=state.query))
    return messages


async def _run_general_chat_with_bounded_tools(
    state: AgentState,
    *,
    llm_client: OpenAICompatibleClient,
    tools: list[dict[str, Any]],
    mcp_tool_names: set[str] | None = None,
    mcp_caller: MCPToolCaller | None = None,
) -> None:
    messages: list[ChatPayloadMessage] = list(_build_general_chat_messages(state))
    usage_entries: list[dict[str, Any] | None] = []
    last_executed_tool_calls: list[ExecutedToolCall] = []

    try:
        for _round_index in range(MAX_LLM_TOOL_CALL_ROUNDS):
            result = await llm_client.chat(
                messages=messages,
                model=state.model,
                temperature=state.temperature,
                max_tokens=state.max_tokens,
                tools=tools,
                tool_choice="auto",
            )
            usage_entries.append(result.usage)
            if not result.tool_calls:
                _apply_llm_chat_result(state, result)
                state.usage = (
                    _combine_usage_entries(usage_entries)
                    if state.tool_call_rounds
                    else result.usage
                )
                return

            state.tool_call_rounds += 1
            state.proposed_tool_calls.extend(_serialize_tool_calls(result.tool_calls))
            executed_tool_calls = await execute_llm_tool_calls(
                result.tool_calls,
                mcp_tool_names=mcp_tool_names,
                mcp_caller=mcp_caller,
            )
            last_executed_tool_calls = executed_tool_calls
            state.executed_tool_calls.extend(
                tool_call.to_step_data() for tool_call in executed_tool_calls
            )
            messages = _build_tool_result_messages(
                messages, result, executed_tool_calls
            )

        state.tool_call_limit_reached = True
        final_result = await llm_client.chat(
            messages=messages,
            model=state.model,
            temperature=state.temperature,
            max_tokens=state.max_tokens,
        )
        usage_entries.append(final_result.usage)
        _apply_llm_chat_result(
            state,
            final_result,
            fallback=_format_tool_execution_fallback(last_executed_tool_calls),
        )
        state.usage = _combine_usage_entries(usage_entries)
    except LLMProviderError as exc:
        _apply_provider_error(state, exc, usage_entries=usage_entries)


def _apply_llm_chat_result(
    state: AgentState,
    result: LLMChatResult,
    *,
    fallback: str | None = None,
) -> None:
    state.answer = result.content or fallback or ""
    state.model = result.model
    state.finish_reason = result.finish_reason


def _build_tool_result_messages(
    messages: list[ChatPayloadMessage],
    tool_call_result: LLMChatResult,
    executed_tool_calls: list[ExecutedToolCall],
) -> list[ChatPayloadMessage]:
    return [
        *messages,
        {
            "role": "assistant",
            "content": tool_call_result.content,
            "tool_calls": _serialize_tool_calls(tool_call_result.tool_calls),
        },
        *[
            executed_tool_call.to_openai_tool_message()
            for executed_tool_call in executed_tool_calls
        ],
    ]


def _serialize_tool_calls(tool_calls: list[LLMToolCall]) -> list[dict[str, Any]]:
    return [
        {
            "id": tool_call.id,
            "type": tool_call.type,
            "function": {
                "name": tool_call.function.name,
                "arguments": tool_call.function.arguments,
            },
        }
        for tool_call in tool_calls
    ]


def _format_tool_execution_fallback(tool_calls: list[ExecutedToolCall]) -> str:
    if not tool_calls:
        return "模型没有返回最终回答。"
    tool_names = ", ".join(tool_call.name for tool_call in tool_calls)
    return (
        "工具已执行，但模型没有返回最终回答。"
        f"已执行工具：{tool_names}"
    )


def _apply_provider_error(
    state: AgentState,
    exc: LLMProviderError,
    *,
    usage_entries: list[dict[str, Any] | None],
) -> None:
    state.provider_error = str(exc)
    state.answer = state.answer or _format_provider_error_fallback()
    state.finish_reason = state.finish_reason or "provider_error"
    if any(usage is not None for usage in usage_entries):
        state.usage = _combine_usage_entries(usage_entries)


def _format_provider_error_fallback() -> str:
    return "抱歉，模型服务暂时不可用，请稍后再试。"


def _summarize_tool_error_categories(
    executed_tool_calls: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tool_call in executed_tool_calls:
        category = tool_call.get("error_category")
        if category:
            counts[category] = counts.get(category, 0) + 1
    return counts


def _combine_usage_entries(
    usage_entries: list[dict[str, Any] | None],
) -> dict[str, Any] | None:
    if not usage_entries or all(usage is None for usage in usage_entries):
        return None

    combined: dict[str, Any] = {
        "rounds": usage_entries,
        "tool_call_rounds": usage_entries[:-1],
        "final_round": usage_entries[-1],
    }
    if len(usage_entries) == 2:
        combined["tool_call_round"] = usage_entries[0]
    for usage in usage_entries:
        if usage is None:
            continue
        for key, value in usage.items():
            if isinstance(value, int | float):
                combined[key] = combined.get(key, 0) + value
    return combined


def _to_response(state: AgentState) -> AgentRunResponse:
    return AgentRunResponse(
        answer=state.answer,
        intent=state.intent,
        session_id=state.session_id,
        memory_used=state.memory_used,
        used_knowledge_base=state.needs_retrieval,
        sources=state.sources,
        steps=state.steps,
        checkpoint=state.checkpoint,
        model=state.model,
        finish_reason=state.finish_reason,
        usage=state.usage,
    )
