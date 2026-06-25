from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_embedding_client,
    get_llm_client,
    get_mcp_client,
    get_mysql_store,
    get_redis_store,
)
from app.main import app
from app.models.chat import ChatMessage
from app.models.document import DocumentSearchResult
from app.models.embedding import TextEmbedding
from app.models.memory import MemoryProfile
from app.models.session import SessionState
from app.services.llm_client import (
    LLMChatResult,
    LLMConfigurationError,
    LLMToolCall,
    LLMToolFunctionCall,
)
from app.services.mcp_client import MCPToolCallResult, MCPToolReference
from app.services.mysql_client import SQLQueryResult


class FakeEmbeddingClient:
    async def embed_text(self, text: str) -> TextEmbedding:
        return TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4])


class FakeRedisStore:
    def __init__(self, results: list[DocumentSearchResult] | None = None) -> None:
        self.results = (
            results
            if results is not None
            else [
                DocumentSearchResult(
                    key="doc:abc:0",
                    content="Redis 可以保存 session，也可以做向量检索。",
                    metadata={"chunk_id": "abc:0", "source": "agent-notes.md"},
                    distance=0.09,
                )
            ]
        )
        self.index_created = False
        self.search_called = False
        self.session: SessionState | None = None
        self.memory_profile: MemoryProfile | None = None
        self.saved_session: SessionState | None = None
        self.saved_memory_profile: MemoryProfile | None = None

    async def ensure_vector_index(self, index_config=None) -> None:
        self.index_created = True

    async def search_document_chunks(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        collection: str | None = None,
        index_config=None,
    ) -> list[DocumentSearchResult]:
        self.search_called = True
        return self.results[:top_k]

    async def get_session(self, session_id: str) -> SessionState | None:
        if self.session is None or self.session.session_id != session_id:
            return None
        return self.session

    async def save_session(self, session: SessionState) -> None:
        self.saved_session = session
        self.session = session

    async def get_memory_profile(self) -> MemoryProfile | None:
        return self.memory_profile

    async def save_memory_profile(self, profile: MemoryProfile) -> None:
        self.saved_memory_profile = profile
        self.memory_profile = profile


class FakeMySQLStore:
    def __init__(self) -> None:
        self.executed_sql = ""

    async def execute_select(self, sql: str) -> SQLQueryResult:
        self.executed_sql = sql
        return SQLQueryResult(
            columns=["company", "role", "channel", "applied_at", "status"],
            rows=[
                {
                    "company": "腾讯",
                    "role": "AI 应用开发实习生",
                    "channel": "内推",
                    "applied_at": "2026-06-10",
                    "status": "interview",
                }
            ],
            sql=f"{sql} LIMIT 50",
        )


class FakeLLMClient:
    def __init__(self) -> None:
        self.messages = []
        self.kwargs = {}

    async def chat(self, **kwargs) -> LLMChatResult:
        self.kwargs = kwargs
        self.messages = kwargs["messages"]
        return LLMChatResult(
            content="Redis 可以用于 session 和向量检索。[1]",
            model=kwargs.get("model") or "mock-model",
            finish_reason="stop",
            usage={"total_tokens": 16},
        )


class FailingLLMClient:
    async def chat(self, **kwargs) -> LLMChatResult:
        raise LLMConfigurationError("LLM_API_KEY is not configured.")


class ToolCallingLLMClient:
    def __init__(self) -> None:
        self.kwargs = {}
        self.calls = []

    async def chat(self, **kwargs) -> LLMChatResult:
        self.kwargs = kwargs
        self.calls.append(kwargs)
        if len(self.calls) > 1:
            return LLMChatResult(
                content="计算结果是 4。",
                model=kwargs.get("model") or "mock-model",
                finish_reason="stop",
                usage={"total_tokens": 8},
            )
        return LLMChatResult(
            content="",
            model=kwargs.get("model") or "mock-model",
            finish_reason="tool_calls",
            usage={"total_tokens": 20},
            tool_calls=[
                LLMToolCall(
                    id="call_abc",
                    type="function",
                    function=LLMToolFunctionCall(
                        name="calculator",
                        arguments='{"expression":"2+2"}',
                    ),
                )
            ],
        )


class MultiRoundToolCallingLLMClient:
    def __init__(self) -> None:
        self.calls = []

    async def chat(self, **kwargs) -> LLMChatResult:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return LLMChatResult(
                content="",
                model=kwargs.get("model") or "mock-model",
                finish_reason="tool_calls",
                usage={"total_tokens": 20},
                tool_calls=[
                    LLMToolCall(
                        id="call_calc",
                        type="function",
                        function=LLMToolFunctionCall(
                            name="calculator",
                            arguments='{"expression":"2+2"}',
                        ),
                    )
                ],
            )
        if len(self.calls) == 2:
            return LLMChatResult(
                content="",
                model=kwargs.get("model") or "mock-model",
                finish_reason="tool_calls",
                usage={"total_tokens": 24},
                tool_calls=[
                    LLMToolCall(
                        id="call_todo",
                        type="function",
                        function=LLMToolFunctionCall(
                            name="create_todo",
                            arguments='{"text":"复习 Redis、写简历"}',
                        ),
                    )
                ],
            )
        return LLMChatResult(
            content="计算结果是 4，并已生成待办。",
            model=kwargs.get("model") or "mock-model",
            finish_reason="stop",
            usage={"total_tokens": 12},
        )


class LoopingToolCallingLLMClient:
    def __init__(self) -> None:
        self.calls = []

    async def chat(self, **kwargs) -> LLMChatResult:
        self.calls.append(kwargs)
        if "tools" not in kwargs:
            return LLMChatResult(
                content="已根据已有工具结果停止。",
                model=kwargs.get("model") or "mock-model",
                finish_reason="stop",
                usage={"total_tokens": 10},
            )

        return LLMChatResult(
            content="",
            model=kwargs.get("model") or "mock-model",
            finish_reason="tool_calls",
            usage={"total_tokens": 9},
            tool_calls=[
                LLMToolCall(
                    id=f"call_loop_{len(self.calls)}",
                    type="function",
                    function=LLMToolFunctionCall(
                        name="calculator",
                        arguments='{"expression":"2+2"}',
                    ),
                )
            ],
        )


class StubMCPClient:
    def __init__(self) -> None:
        self.called_with: tuple[str, dict] | None = None
        self.config_path = "data/mcp/servers.json"

    @property
    def enabled(self) -> bool:
        return True

    @property
    def server_count(self) -> int:
        return 1

    async def list_tools(self):
        return [
            MCPToolReference(
                server_name="demo",
                tool_name="echo",
                qualified_name="mcp_demo_echo",
                description="Echo back text.",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            )
        ]

    async def call_tool(self, qualified_name: str, arguments: dict) -> MCPToolCallResult:
        self.called_with = (qualified_name, arguments)
        return MCPToolCallResult(
            qualified_name=qualified_name,
            server_name="demo",
            tool_name="echo",
            text=f"echoed: {arguments.get('text', '')}",
            is_error=False,
        )


class DisabledMCPClient:
    config_path = "data/mcp/servers.json"

    @property
    def enabled(self) -> bool:
        return False

    @property
    def server_count(self) -> int:
        return 0

    async def list_tools(self):
        return []


class MCPToolCallingLLMClient:
    def __init__(self) -> None:
        self.calls = []

    async def chat(self, **kwargs) -> LLMChatResult:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return LLMChatResult(
                content="",
                model=kwargs.get("model") or "mock-model",
                finish_reason="tool_calls",
                usage={"total_tokens": 20},
                tool_calls=[
                    LLMToolCall(
                        id="call_mcp_echo",
                        type="function",
                        function=LLMToolFunctionCall(
                            name="mcp_demo_echo",
                            arguments='{"text":"hi mcp"}',
                        ),
                    )
                ],
            )
        return LLMChatResult(
            content="已通过 MCP 工具回显：hi mcp。",
            model=kwargs.get("model") or "mock-model",
            finish_reason="stop",
            usage={"total_tokens": 10},
        )


def test_agent_run_executes_mcp_tool_in_general_chat() -> None:
    redis_store = FakeRedisStore()
    llm_client = MCPToolCallingLLMClient()
    mcp_client = StubMCPClient()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: llm_client
    app.dependency_overrides[get_mcp_client] = lambda: mcp_client
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "帮我用工具回显一句话", "use_knowledge_base": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "已通过 MCP 工具回显：hi mcp。"
    assert body["intent"] == "general_chat"
    generate_step = next(
        step for step in body["steps"] if step["name"] == "generate_answer"
    )
    assert generate_step["data"]["mcp_tool_count"] == 1
    executed = generate_step["data"]["executed_tool_calls"]
    assert executed[0]["name"] == "mcp_demo_echo"
    assert executed[0]["status"] == "success"
    assert mcp_client.called_with == ("mcp_demo_echo", {"text": "hi mcp"})
    assert any(
        tool["function"]["name"] == "mcp_demo_echo"
        for tool in llm_client.calls[0]["tools"]
    )


def test_agent_run_general_chat_without_mcp_tools() -> None:
    redis_store = FakeRedisStore()
    llm_client = FakeLLMClient()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: llm_client
    app.dependency_overrides[get_mcp_client] = lambda: DisabledMCPClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "帮我写一句自我介绍", "use_knowledge_base": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    generate_step = next(
        step for step in body["steps"] if step["name"] == "generate_answer"
    )
    assert generate_step["data"]["mcp_tool_count"] == 0


def test_agent_run_uses_rag_when_knowledge_base_is_enabled() -> None:
    redis_store = FakeRedisStore()
    llm_client = FakeLLMClient()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: llm_client
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "Redis 在项目里做什么？", "top_k": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Redis 可以用于 session 和向量检索。[1]"
    assert body["intent"] == "knowledge_query"
    assert body["used_knowledge_base"] is True
    assert body["model"] == "mock-model"
    assert body["finish_reason"] == "stop"
    assert body["usage"] == {"total_tokens": 16}
    assert body["sources"][0]["metadata"]["source"] == "agent-notes.md"
    assert [step["name"] for step in body["steps"]] == [
        "understand_intent",
        "decide_retrieval",
        "call_tools",
        "generate_answer",
        "save_trace",
    ]
    assert body["steps"][2]["data"] == {"tool": "search_docs", "source_count": 1}
    assert body["steps"][-1]["status"] == "skipped"
    assert redis_store.index_created is True
    assert redis_store.search_called is True
    assert llm_client.messages[0].role == "system"
    assert "[1] source=agent-notes.md" in llm_client.messages[1].content


def test_agent_run_skips_retrieval_for_general_chat() -> None:
    redis_store = FakeRedisStore()
    llm_client = FakeLLMClient()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: llm_client
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "帮我写一句自我介绍", "use_knowledge_base": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "general_chat"
    assert body["used_knowledge_base"] is False
    assert body["sources"] == []
    assert [step["name"] for step in body["steps"]] == [
        "understand_intent",
        "decide_retrieval",
        "call_tools",
        "generate_answer",
        "save_trace",
    ]
    assert body["steps"][2]["status"] == "skipped"
    assert redis_store.index_created is False
    assert redis_store.search_called is False
    assert len(llm_client.messages) == 1
    assert llm_client.messages[0].role == "user"
    assert llm_client.messages[0].content == "帮我写一句自我介绍"
    assert llm_client.kwargs["tool_choice"] == "auto"
    assert llm_client.kwargs["tools"][0]["function"]["name"] == "calculator"
    assert body["steps"][3]["data"]["proposed_tool_call_count"] == 0
    assert body["steps"][3]["data"]["executed_tool_call_count"] == 0
    assert body["checkpoint"]["thread_id"].startswith("agent-request:")
    assert body["checkpoint"]["checkpoint_id"]
    assert body["checkpoint"]["backend"] == "local_file"
    assert body["checkpoint"]["durable"] is True
    assert body["checkpoint"]["production_ready"] is False


def test_agent_run_executes_llm_tool_calls_and_generates_final_answer() -> None:
    redis_store = FakeRedisStore()
    llm_client = ToolCallingLLMClient()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: llm_client
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "帮我处理这个请求", "use_knowledge_base": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "计算结果是 4。"
    assert body["finish_reason"] == "stop"
    assert body["steps"][2]["status"] == "skipped"
    assert body["steps"][3]["data"]["tool_schema_count"] == 4
    assert body["steps"][3]["data"]["max_tool_call_rounds"] == 3
    assert body["steps"][3]["data"]["tool_call_round_count"] == 1
    assert body["steps"][3]["data"]["tool_call_limit_reached"] is False
    assert body["steps"][3]["data"]["proposed_tool_call_count"] == 1
    assert body["steps"][3]["data"]["proposed_tool_calls"] == [
        {
            "id": "call_abc",
            "type": "function",
            "function": {
                "name": "calculator",
                "arguments": '{"expression":"2+2"}',
            },
        }
    ]
    assert body["steps"][3]["data"]["executed_tool_call_count"] == 1
    executed_call = body["steps"][3]["data"]["executed_tool_calls"][0]
    assert executed_call["id"] == "call_abc"
    assert executed_call["name"] == "calculator"
    assert executed_call["arguments"] == {"expression": "2+2"}
    assert executed_call["status"] == "success"
    assert '"display_value": "4"' in executed_call["content"]
    assert len(llm_client.calls) == 2
    assert llm_client.calls[0]["tool_choice"] == "auto"
    assert llm_client.calls[0]["tools"][0]["function"]["name"] == "calculator"
    assert llm_client.calls[1]["tool_choice"] == "auto"
    assert llm_client.calls[1]["tools"][0]["function"]["name"] == "calculator"
    assert llm_client.calls[1]["messages"][-1]["role"] == "tool"
    assert llm_client.calls[1]["messages"][-1]["tool_call_id"] == "call_abc"
    assert redis_store.index_created is False
    assert redis_store.search_called is False


def test_agent_run_executes_multiple_llm_tool_call_rounds() -> None:
    redis_store = FakeRedisStore()
    llm_client = MultiRoundToolCallingLLMClient()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: llm_client
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "帮我连续处理任务", "use_knowledge_base": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "计算结果是 4，并已生成待办。"
    step_data = body["steps"][3]["data"]
    assert step_data["tool_call_round_count"] == 2
    assert step_data["tool_call_limit_reached"] is False
    assert step_data["proposed_tool_call_count"] == 2
    assert step_data["executed_tool_call_count"] == 2
    assert [call["name"] for call in step_data["executed_tool_calls"]] == [
        "calculator",
        "create_todo",
    ]
    assert len(llm_client.calls) == 3
    assert "tools" in llm_client.calls[0]
    assert "tools" in llm_client.calls[1]
    assert "tools" in llm_client.calls[2]
    assert llm_client.calls[1]["messages"][-1]["tool_call_id"] == "call_calc"
    assert llm_client.calls[2]["messages"][-1]["tool_call_id"] == "call_todo"
    assert redis_store.index_created is False
    assert redis_store.search_called is False


def test_agent_run_stops_tool_call_loop_at_max_rounds() -> None:
    redis_store = FakeRedisStore()
    llm_client = LoopingToolCallingLLMClient()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: llm_client
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "一直调用工具", "use_knowledge_base": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "已根据已有工具结果停止。"
    step_data = body["steps"][3]["data"]
    assert step_data["max_tool_call_rounds"] == 3
    assert step_data["tool_call_round_count"] == 3
    assert step_data["tool_call_limit_reached"] is True
    assert step_data["proposed_tool_call_count"] == 3
    assert step_data["executed_tool_call_count"] == 3
    assert len(llm_client.calls) == 4
    assert all("tools" in call for call in llm_client.calls[:3])
    assert "tools" not in llm_client.calls[3]
    assert redis_store.index_created is False
    assert redis_store.search_called is False



def test_agent_run_loads_session_and_memory_for_general_chat() -> None:
    redis_store = FakeRedisStore()
    redis_store.session = SessionState(
        session_id="learn-1",
        messages=[
            ChatMessage(role="user", content="我之前在学 Redis。"),
            ChatMessage(role="assistant", content="我们已经完成 Redis health check。"),
        ],
    )
    redis_store.memory_profile = MemoryProfile(
        preferences=["回答尽量简洁"],
        constraints=["默认使用中文"],
    )
    llm_client = FakeLLMClient()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: llm_client
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={
                "session_id": "learn-1",
                "query": "帮我写一句自我介绍",
                "use_knowledge_base": False,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "learn-1"
    assert body["memory_used"] is True
    assert body["checkpoint"]["thread_id"] == "agent-session:learn-1"
    assert body["checkpoint"]["checkpoint_id"]
    assert body["checkpoint"]["backend"] == "local_file"
    assert body["checkpoint"]["durable"] is True
    assert body["checkpoint"]["production_ready"] is False
    assert [step["name"] for step in body["steps"]] == [
        "load_memory",
        "understand_intent",
        "decide_retrieval",
        "call_tools",
        "generate_answer",
        "save_trace",
    ]
    assert body["steps"][0]["data"] == {
        "session_id": "learn-1",
        "session_message_count": 2,
        "memory_item_count": 2,
    }
    assert body["steps"][-1]["status"] == "completed"
    assert body["steps"][-1]["data"]["memory_update_count"] == 0
    assert llm_client.messages[0].role == "system"
    assert "回答尽量简洁" in llm_client.messages[0].content
    assert llm_client.messages[1].content == "我之前在学 Redis。"
    assert redis_store.saved_session is not None
    assert redis_store.saved_session.messages[-2].content == "帮我写一句自我介绍"
    assert redis_store.saved_session.messages[-1].content == "Redis 可以用于 session 和向量检索。[1]"
    assert redis_store.saved_memory_profile is None
    assert redis_store.index_created is False
    assert redis_store.search_called is False


def test_agent_run_updates_memory_without_llm_when_memory_is_explicit() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={
                "session_id": "learn-2",
                "query": "请记住：我喜欢先给结论",
                "use_knowledge_base": False,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "memory_update"
    assert body["memory_used"] is True
    assert "已记录长期记忆" in body["answer"]
    assert body["steps"][3]["data"] == {
        "tool": "memory_profile",
        "memory_update_count": 1,
    }
    assert body["steps"][4]["data"] == {"tool": "memory_profile"}
    assert body["steps"][-1]["data"]["memory_update_count"] == 1
    assert redis_store.saved_memory_profile is not None
    assert "我喜欢先给结论" in redis_store.saved_memory_profile.preferences
    assert redis_store.saved_session is not None
    assert redis_store.saved_session.messages[-2].content == "请记住：我喜欢先给结论"


def test_agent_run_requires_session_id_for_memory_update() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "请记住：我喜欢先给结论", "use_knowledge_base": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "session_id is required to save memory."


def test_agent_run_uses_calculator_without_redis_or_llm() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "请计算 2 + 3 * 4 等于多少？"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "2+3*4 = 14"
    assert body["intent"] == "calculation"
    assert body["used_knowledge_base"] is False
    assert body["sources"] == []
    assert [step["name"] for step in body["steps"]] == [
        "understand_intent",
        "decide_retrieval",
        "call_tools",
        "generate_answer",
        "save_trace",
    ]
    assert body["steps"][2]["data"] == {
        "tool": "calculator",
        "expression": "2+3*4",
        "value": 14,
    }
    assert redis_store.index_created is False
    assert redis_store.search_called is False


def test_agent_run_uses_create_todo_without_redis_or_llm() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "帮我生成待办：复习 Redis、写简历、提交周报"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == (
        "待办清单：\n"
        "- [ ] 复习 Redis\n"
        "- [ ] 写简历\n"
        "- [ ] 提交周报"
    )
    assert body["intent"] == "todo_creation"
    assert body["used_knowledge_base"] is False
    assert body["sources"] == []
    assert body["steps"][2]["data"] == {"tool": "create_todo", "item_count": 3}
    assert body["steps"][3]["data"] == {"tool": "create_todo"}
    assert redis_store.index_created is False
    assert redis_store.search_called is False


def test_agent_run_uses_summarize_file_without_redis_or_llm() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "请总结 README.md"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "file_summary"
    assert body["used_knowledge_base"] is False
    assert "文件摘要：README.md" in body["answer"]
    assert body["steps"][2]["data"] == {
        "tool": "summarize_file",
        "file_path": "README.md",
    }
    assert body["steps"][3]["data"] == {"tool": "summarize_file"}
    assert redis_store.index_created is False
    assert redis_store.search_called is False


def test_agent_run_uses_draft_weekly_report_without_redis_or_llm() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={
                "query": (
                    "帮我写周报：本周完成：接入 Redis、补充测试；"
                    "问题：没有 API Key；下周计划：实现前端、完善 README"
                )
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "weekly_report_draft"
    assert body["used_knowledge_base"] is False
    assert "周报草稿：" in body["answer"]
    assert "- 接入 Redis" in body["answer"]
    assert "- 实现前端" in body["answer"]
    assert body["steps"][2]["data"] == {
        "tool": "draft_weekly_report",
        "completed_count": 2,
        "next_step_count": 2,
    }
    assert body["steps"][3]["data"] == {"tool": "draft_weekly_report"}
    assert redis_store.index_created is False
    assert redis_store.search_called is False


def test_agent_run_uses_query_database_without_redis_or_llm() -> None:
    redis_store = FakeRedisStore()
    mysql_store = FakeMySQLStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_mysql_store] = lambda: mysql_store
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "我投了哪些公司的什么岗位？"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "database_query"
    assert body["used_knowledge_base"] is False
    assert body["sources"] == []
    assert "简历投递记录：" in body["answer"]
    assert "腾讯" in body["answer"]
    assert body["steps"][2]["data"]["tool"] == "query_database"
    assert "job_applications" in body["steps"][2]["data"]["sql"]
    assert body["steps"][2]["data"]["row_count"] == 1
    assert body["steps"][3]["data"] == {"tool": "query_database", "row_count": 1}
    assert redis_store.index_created is False
    assert redis_store.search_called is False
    assert "SELECT company, role, channel" in mysql_store.executed_sql


def test_get_agent_checkpoint_returns_latest_snapshot_metadata() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        run_response = client.post(
            "/api/v1/agent/run",
            json={"query": "请计算 2 + 2"},
        )
        thread_id = run_response.json()["checkpoint"]["thread_id"]
        response = client.get(f"/api/v1/agent/checkpoints/{thread_id}")
    finally:
        app.dependency_overrides.clear()

    assert run_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == thread_id
    assert body["checkpoint_id"] == run_response.json()["checkpoint"]["checkpoint_id"]
    assert body["backend"] == "local_file"
    assert body["durable"] is True
    assert body["production_ready"] is False
    assert body["resume_supported"] is False
    assert body["human_in_the_loop_supported"] is False
    assert body["pending_write_count"] == 0
    assert "query" in body["state_channel_keys"]
    assert "answer" in body["state_channel_keys"]
    assert body["notes"]


def test_get_agent_checkpoint_history_returns_snapshot_metadata_list() -> None:
    session_id = f"stage19-history-{uuid4().hex}"
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        run_response = client.post(
            "/api/v1/agent/run",
            json={"session_id": session_id, "query": "请计算 2 + 2"},
        )
        thread_id = run_response.json()["checkpoint"]["thread_id"]
        response = client.get(f"/api/v1/agent/checkpoints/{thread_id}/history?limit=2")
    finally:
        app.dependency_overrides.clear()

    assert run_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == thread_id
    assert body["limit"] == 2
    assert body["checkpoint_count"] == 2
    assert len(body["checkpoints"]) == 2
    assert body["checkpoints"][0]["checkpoint_id"] == run_response.json()["checkpoint"][
        "checkpoint_id"
    ]
    assert body["checkpoints"][0]["resume_supported"] is False
    assert body["checkpoints"][0]["human_in_the_loop_supported"] is False
    assert "answer" in body["checkpoints"][0]["state_channel_keys"]
    assert "channel_values" not in body["checkpoints"][0]


def test_get_agent_checkpoint_returns_404_for_unknown_thread() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/agent/checkpoints/agent-session:missing-stage19")

    assert response.status_code == 404
    assert response.json()["detail"] == "Agent checkpoint thread not found."


def test_get_agent_checkpoint_history_returns_404_for_unknown_thread() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/v1/agent/checkpoints/agent-session:missing-stage19/history"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Agent checkpoint thread not found."


def test_agent_run_returns_400_for_empty_todo_request() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "待办："},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "No todo items were found."


def test_agent_run_returns_503_when_llm_is_not_configured() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"query": "普通聊天也需要模型", "use_knowledge_base": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "LLM_API_KEY is not configured."
