from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from app.agent.checkpoint import LocalFileCheckpointSaver
from app.agent.state import AgentState
from app.agent.workflow import (
    _build_checkpoint_config,
    _build_checkpoint_thread_id,
    _route_after_decide_retrieval,
    _run_general_chat_with_bounded_tools,
)
from app.services.llm_client import LLMProviderError


class CounterState(TypedDict):
    count: int


def test_route_after_decide_retrieval_calls_tools_for_selected_tool() -> None:
    state = AgentState(query="请计算 2+2", selected_tool="calculator")

    assert _route_after_decide_retrieval(state) == "call_tools"


def test_route_after_decide_retrieval_calls_tools_for_knowledge_retrieval() -> None:
    state = AgentState(query="Redis 在项目里做什么？", needs_retrieval=True)

    assert _route_after_decide_retrieval(state.model_dump(mode="python")) == "call_tools"


def test_route_after_decide_retrieval_skips_tools_for_general_chat() -> None:
    state = AgentState(query="帮我写一句自我介绍", needs_retrieval=False)

    assert _route_after_decide_retrieval(state) == "skip_tools"


def test_build_checkpoint_thread_id_uses_session_id_when_present() -> None:
    assert _build_checkpoint_thread_id("learn-1") == "agent-session:learn-1"


def test_build_checkpoint_thread_id_creates_request_thread_without_session() -> None:
    first_thread_id = _build_checkpoint_thread_id(None)
    second_thread_id = _build_checkpoint_thread_id(None)

    assert first_thread_id.startswith("agent-request:")
    assert second_thread_id.startswith("agent-request:")
    assert first_thread_id != second_thread_id


def test_build_checkpoint_config_sets_thread_id() -> None:
    assert _build_checkpoint_config("agent-session:learn-1") == {
        "configurable": {"thread_id": "agent-session:learn-1"}
    }


def test_local_file_checkpoint_saver_reloads_latest_checkpoint(tmp_path) -> None:
    checkpoint_path = tmp_path / "agent_checkpoints.pkl"
    first_saver = LocalFileCheckpointSaver(checkpoint_path)

    builder = StateGraph(CounterState)
    builder.add_node("increment", lambda state: {"count": state["count"] + 1})
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    graph = builder.compile(checkpointer=first_saver)

    config = {"configurable": {"thread_id": "agent-session:learn-1"}}
    assert graph.invoke({"count": 1}, config=config) == {"count": 2}
    snapshot = graph.get_state(config)

    second_saver = LocalFileCheckpointSaver(checkpoint_path)
    restored = second_saver.get_tuple(config)

    assert checkpoint_path.exists()
    assert restored is not None
    assert restored.config["configurable"]["thread_id"] == "agent-session:learn-1"
    assert restored.config["configurable"]["checkpoint_id"] == snapshot.config[
        "configurable"
    ]["checkpoint_id"]


class _ProviderErrorLLMClient:
    def __init__(self) -> None:
        self.call_count = 0

    async def chat(self, **_kwargs: object) -> object:
        self.call_count += 1
        raise LLMProviderError("LLM provider returned HTTP 503: service unavailable")


@pytest.mark.anyio
async def test_general_chat_falls_back_on_provider_error() -> None:
    state = AgentState(query="帮我写一句自我介绍", use_knowledge_base=False)
    llm_client = _ProviderErrorLLMClient()

    await _run_general_chat_with_bounded_tools(state, llm_client=llm_client, tools=[])

    assert llm_client.call_count == 1
    assert state.provider_error is not None
    assert "503" in state.provider_error
    assert state.answer == "抱歉，模型服务暂时不可用，请稍后再试。"
    assert state.finish_reason == "provider_error"
