# 从 0 开始的代码级拆解

这份文档不是普通 README，而是给你对照学习用的代码路线图。它按“从空目录逐步做成当前项目”的顺序拆解：每一步要解决什么问题、核心文件是什么、代码为什么这样分层、怎么验证。

如果你已经知道项目是怎么一步步做出来的，想按当前工程模块复盘每个文件的职责、输入输出、调用关系和常见改动点，继续看 `docs/code_module_breakdown.md`。

当前项目根目录：

```text
ai-resume-job-agent/
```

## 0. 先理解项目目标

这个项目的定位是：

```text
求职场景的个人知识库 Agent
= 文档 RAG + Redis 向量检索 + MySQL 投递记录问答 + LangGraph 工具调用 + 记忆 + 前端演示
```

不要把它讲成“万能 Agent”。它更准确的说法是：

- 非结构化资料，例如 README、面试稿、项目文档，走 RAG。
- 结构化投递记录，例如公司、岗位、状态、渠道，走 MySQL 确定性查询。
- 明确工具任务，例如计算、待办、周报、文件摘要，走工具函数。
- 用户偏好和项目背景，走 Redis session 和 memory profile。

## 1. 搭 FastAPI 工程骨架

第一步只做能启动的后端，不碰 RAG。

核心文件：

```text
app/main.py
app/core/config.py
app/core/logging.py
app/api/routes/health.py
app/api/dependencies.py
```

`app/main.py` 是应用入口：

```python
def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    install_request_logging(app)
    app.add_middleware(CORSMiddleware, ...)
    app.include_router(agent_router, prefix=settings.api_prefix)
    app.include_router(chat_router, prefix=settings.api_prefix)
    app.include_router(documents_router, prefix=settings.api_prefix)
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(rag_router, prefix=settings.api_prefix)
    return app
```

你要学会看出它的职责很窄：

- 创建 FastAPI app。
- 安装日志中间件。
- 安装 CORS。
- 注册路由。
- 不写具体业务逻辑。

`app/core/config.py` 用 `BaseSettings` 读取 `.env`：

```python
class Settings(BaseSettings):
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    redis_url: str = "redis://127.0.0.1:6379/0"
    mysql_url: str = "mysql+pymysql://..."
```

这一步的关键思想：

```text
真实 key 不进代码，只进本地 .env。
代码只读取配置变量。
```

验证命令：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8025
```

浏览器访问：

```text
http://127.0.0.1:8025/api/v1/health
```

你应该看到：

```json
{"status":"ok"}
```

## 2. 写健康检查和依赖注入

健康检查分三层：

```text
/health        只证明 FastAPI 活着
/health/redis 证明 Redis 能连接
/health/mysql 证明 MySQL 能连接
```

核心文件：

```text
app/api/routes/health.py
app/api/dependencies.py
```

`dependencies.py` 负责创建服务对象：

```python
async def get_redis_store() -> AsyncIterator[RedisStore]:
    store = RedisStore.from_settings()
    try:
        yield store
    finally:
        await store.aclose()
```

为什么要这样写：

- 路由不负责管理连接生命周期。
- 测试时可以替换依赖。
- Redis、MySQL、LLM client 的创建逻辑集中管理。

面试讲法：

> 我用 FastAPI dependency injection 管理 Redis、MySQL 和 LLM client 的生命周期，路由层只表达接口行为，不直接散落连接创建和关闭逻辑。

## 3. 接入 OpenAI-compatible LLM 层

这一层先做“普通聊天”，后续再支持工具调用。

核心文件：

```text
app/services/llm_client.py
app/models/chat.py
app/api/routes/chat.py
```

`OpenAICompatibleClient` 的核心职责：

- 组装 `/chat/completions` 请求。
- 添加 Bearer token。
- 支持普通 chat。
- 支持 SSE stream。
- 解析 `choices[0].message.content`。
- 解析 `tool_calls`。
- 包装上游错误。

核心请求结构：

```python
payload = {
    "model": model or self.model,
    "messages": [_dump_message(message) for message in messages],
}
```

支持工具调用后会额外带：

```python
payload["tools"] = tools
payload["tool_choice"] = "auto"
```

为什么不用某个厂商 SDK：

```text
项目只依赖 OpenAI-compatible HTTP 协议。
换 DeepSeek、Qwen、OpenAI、本地反代时，只换 base_url、model、api_key。
```

验证点：

- 没有 `LLM_API_KEY` 时应该返回 503，这是预期配置错误。
- 有本地反代后，普通 chat smoke 应通过。
- tool-call smoke 要能返回 `calculator` 这样的 `tool_calls`。

## 4. 接入 Redis 基础层

Redis 在本项目中不是只做缓存，而是同时承担四类能力：

```text
session:{id}           短期会话
memory:profile:{id}    长期记忆
task:index:{id}        异步索引任务状态
doc:{document}:{chunk} 文档 chunk + embedding
```

核心文件：

```text
app/services/redis_client.py
app/models/session.py
app/models/memory.py
app/models/document.py
app/models/vector_index.py
```

`RedisStore` 的普通 JSON 封装：

```python
async def set_json(self, key: str, value: dict[str, Any], *, expire_seconds: int | None = None):
    await self._client.set(key, json.dumps(value, ensure_ascii=False), ex=expire_seconds)
```

短期会话有 TTL：

```python
DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 24
```

长期记忆不设置 TTL：

```python
async def save_memory_profile(self, profile: MemoryProfile) -> None:
    await self.set_json(self._memory_profile_key(profile.profile_id), profile.model_dump())
```

为什么集中封装：

- 业务代码不直接写 Redis 命令。
- key 前缀统一。
- JSON、HASH、向量 bytes 的处理不散落。
- 后续替换 Redis 客户端或增加监控更容易。

验证命令：

```powershell
docker compose up -d redis
```

接口验证：

```text
GET /api/v1/health/redis
```

## 5. 实现文档解析

文档入库的第一步是把文件变成统一 `Document`。

核心文件：

```text
app/rag/document_loader.py
app/models/document.py
tests/test_document_processing.py
```

当前支持：

```text
.txt
.md
.docx
```

暂不支持：

```text
.pdf
```

上传文件解析入口：

```python
def load_uploaded_document(file_name: str, data: bytes) -> Document:
    safe_file_name = Path(file_name).name
    suffix = Path(safe_file_name).suffix.lower()
```

这里的安全点：

- `Path(file_name).name` 只保留文件名，避免上传路径穿越。
- `.txt/.md` 要求 UTF-8。
- `.docx` 使用 `python-docx` 解析段落和表格。
- 空文档直接拒绝。

统一输出模型：

```text
Document
  document_id
  content
  metadata.source
  metadata.file_name
  metadata.file_type
```

为什么要统一模型：

```text
后续 chunker、indexer、retriever 不需要关心文件原格式。
它们只处理 Document。
```

## 6. 实现 chunk 切片

RAG 不应该把整篇文档直接塞给模型。原因是模型注意力有限，长上下文会稀释重点，也会增加幻觉概率。

核心文件：

```text
app/rag/chunker.py
app/models/document.py
```

当前策略：

```python
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100
```

核心循环：

```python
while start_char < content_length:
    end_char = min(start_char + chunk_size, content_length)
    chunk_content = document.content[start_char:end_char]
    ...
    start_char = end_char - chunk_overlap
```

每个 chunk 保存：

```text
chunk_id
document_id
content
source
chunk_index
start_char
end_char
metadata
```

`chunk_overlap` 的意义：

```text
让相邻 chunk 保留一部分上下文，降低关键信息刚好被切断的概率。
```

当前边界：

```text
这是字符切片，不是 token 切片，也不理解 Markdown 标题结构。
它够做第一版，后续可以升级为按标题/段落/token 切片。
```

## 7. 接入 embedding 层

embedding 层负责把文本变成固定维度向量。

核心文件：

```text
app/services/embedding_client.py
app/models/embedding.py
```

项目保留两个 provider：

```text
fake                 无 key 本地测试
openai-compatible    真实 embedding 服务
```

fake embedding：

```python
class DeterministicEmbeddingClient:
    async def embed_text(self, text: str) -> TextEmbedding:
        return TextEmbedding(text=text, embedding=self._build_vector(text))
```

它的价值：

- 不花钱。
- 不依赖网络。
- 同一文本返回同一向量。
- 能测试入库链路。

它的限制：

```text
没有真实语义理解能力，不能代表最终检索质量。
```

真实 embedding：

```python
class OpenAICompatibleEmbeddingClient:
    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]:
        payload = {"model": self.model, "input": texts}
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
```

关键校验：

```python
if len(embedding) != self.expected_dimension:
    raise EmbeddingProviderError(...)
```

为什么必须校验维度：

```text
Redis vector index 创建时维度是固定的。
写入向量维度和 index 维度不一致，检索会失败或结果不可信。
```

## 8. 写入 Redis 向量索引

文档入库完整链路：

```text
file bytes
-> load_uploaded_document()
-> chunk_document()
-> embedding_client.embed_texts()
-> redis_store.save_document_chunk()
```

核心文件：

```text
app/rag/indexer.py
app/services/redis_client.py
```

`index_document_chunks()` 很短，但它串起主链路：

```python
await redis_store.ensure_vector_index(index_config)
embeddings = await embedding_client.embed_texts([chunk.content for chunk in chunks])
for chunk, embedding in zip(chunks, embeddings, strict=True):
    key = await redis_store.save_document_chunk(chunk, embedding.embedding)
```

Redis HASH 保存三类字段：

```text
content     chunk 原文
metadata    JSON 元数据
embedding   FLOAT32 bytes
```

embedding 转 bytes：

```python
struct.pack(f"<{dimension}f", *embedding)
```

为什么不是 JSON 数组：

```text
Redis vector search 要求向量字段以二进制 FLOAT32 形式参与 KNN 检索。
```

Redis index 创建：

```text
FT.CREATE idx:docs ON HASH PREFIX 1 doc: SCHEMA
content TEXT
metadata TEXT
embedding VECTOR HNSW ...
```

## 9. 实现文档上传和检索 API

核心文件：

```text
app/api/routes/documents.py
```

同步上传接口：

```text
POST /api/v1/documents/upload
```

它做完整入库：

```python
document = load_uploaded_document(...)
chunks = chunk_document(document)
indexed_keys = await index_document_chunks(...)
```

异步上传接口：

```text
POST /api/v1/documents/upload/async
```

它只做两件事：

- 创建 Redis 任务状态。
- 把任务丢进 RQ 队列。

检索接口：

```text
POST /api/v1/documents/search
```

检索链路：

```text
query
-> query embedding
-> Redis FT.SEARCH KNN
-> top_k chunks
```

核心函数：

```text
app/rag/retriever.py
retrieve_document_chunks()
```

注意：

```text
distance 越小，一般表示 query 和 chunk 越接近。
它不是越大越好的相关性分数。
```

## 10. 实现 RAG 问答

RAG 比检索多了回答生成。

核心文件：

```text
app/rag/answerer.py
app/api/routes/rag.py
app/models/rag.py
```

完整链路：

```text
query
-> retrieve_document_chunks()
-> to_rag_sources()
-> build_rag_messages()
-> llm_client.chat()
-> answer + sources
```

重要设计：

```python
if not sources:
    return RagQueryResponse(answer=NO_CONTEXT_ANSWER, sources=[])
```

为什么无 sources 不调用 LLM：

- 防止模型胡编。
- 节省 token。
- 明确告诉用户知识库没有依据。

prompt 约束：

```text
只能基于提供的上下文回答。
上下文不足就说明不知道。
回答中用 [1]、[2] 标注来源。
```

面试讲法：

> RAG 接口把 answer 和 sources 分开返回。即使模型引用格式不完美，前端和评测脚本仍能看到本次回答依赖了哪些 chunk。

## 11. 引入 LangGraph Agent workflow

RAG 是单能力链路，Agent 是统一入口。

核心文件：

```text
app/agent/state.py
app/agent/workflow.py
app/models/agent.py
app/api/routes/agent.py
```

`AgentState` 是内部运行状态：

```text
query
intent
selected_tool
needs_retrieval
sources
answer
steps
session
memory_profile
checkpoint
```

对外响应是 `AgentRunResponse`：

```text
answer
intent
sources
steps
checkpoint metadata
usage
```

为什么分开：

```text
内部状态可以很复杂，但 API 不应该暴露所有内部字段。
```

LangGraph 建图顺序：

```text
START
-> load_memory
-> understand_intent
-> decide_retrieval
-> call_tools 或 skip_tools
-> generate_answer
-> save_trace
-> END
```

代码位置：

```python
builder = StateGraph(AgentState)
builder.add_node("load_memory", load_memory_node)
...
builder.add_conditional_edges(
    "decide_retrieval",
    _route_after_decide_retrieval,
    {"call_tools": "call_tools", "skip_tools": "skip_tools"},
)
```

这一版的 Agent 路由仍以确定性规则为主：

- 计算问题 -> `calculator`
- 待办问题 -> `create_todo`
- 文件摘要 -> `summarize_file`
- 周报草稿 -> `draft_weekly_report`
- 记忆写入 -> `memory_profile`
- 投递数据问题 -> `query_database`
- 知识库问题 -> `search_docs`
- 普通聊天 -> LLM，可带 bounded tool-call loop

## 12. 实现工具系统

工具分两类：

```text
确定性工具：代码直接判断并调用
LLM tool-call 工具：模型提出 tool_calls，项目执行，再把结果回传给模型
```

核心文件：

```text
app/tools/calculator.py
app/tools/create_todo.py
app/tools/summarize_file.py
app/tools/draft_weekly_report.py
app/tools/search_docs.py
app/tools/query_database.py
app/tools/registry.py
app/tools/llm_executor.py
```

`registry.py` 负责告诉模型有哪些工具：

```python
ToolSchema(
    name="calculator",
    description="Evaluate a safe arithmetic expression.",
    parameters={...},
)
```

`llm_executor.py` 负责执行模型返回的 `tool_calls`：

```text
LLM tool_calls
-> parse JSON arguments
-> LangGraph ToolNode
-> ToolMessage
-> OpenAI-compatible tool message
-> 二次调用 LLM
```

普通聊天分支最多执行 3 轮工具调用：

```python
MAX_LLM_TOOL_CALL_ROUNDS = 3
```

为什么要限制轮数：

```text
防止模型陷入无限工具调用循环。
达到上限后不再给 tools，强制模型基于已有结果生成最终回答。
```

## 13. 接入 MySQL 数据库问答

MySQL 用来回答结构化投递记录问题，不是用来替代 RAG。

核心文件：

```text
app/services/mysql_client.py
app/tools/query_database.py
docker/mysql/init/01_job_applications.sql
```

当前业务表：

```text
job_applications
application_events
```

数据库问答链路：

```text
用户问投递记录
-> is_job_application_query()
-> build_job_application_query_plan()
-> MySQLStore.execute_select()
-> prepare_safe_select()
-> format_database_result()
```

安全层：

- 只允许 `SELECT`。
- 禁止 `INSERT/UPDATE/DELETE/DROP/ALTER` 等 DDL/DML。
- 禁止多语句。
- 禁止注释。
- 只允许访问白名单表。
- 强制 `LIMIT`。
- MySQL 账号使用只读权限。

当前边界：

```text
这是确定性 SQL 模板，不是 LLM 自由生成 SQL。
```

面试讲法：

> 我没有直接执行 LLM 生成的 SQL。第一版数据库问答使用规则模板生成 SELECT，再经过 SQL 安全层校验和 LIMIT 收敛，最后用只读账号执行。

## 14. 实现记忆系统

记忆分两类：

```text
短期记忆：session 对话历史，有 TTL。
长期记忆：memory profile，不设置 TTL。
```

核心文件：

```text
app/memory/session.py
app/memory/profile.py
app/services/redis_client.py
app/agent/workflow.py
```

短期记忆：

```text
session:{session_id}
```

长期记忆：

```text
memory:profile:default
```

Agent 节点：

```text
load_memory  读取短期和长期记忆
save_trace   保存本轮 user/assistant，合并显式长期记忆
```

当前长期记忆写入不是让 LLM 自由决定，而是显式表达触发：

```text
请记住：我喜欢先给结论
```

为什么这样做：

```text
记忆会长期影响后续回答，不能让模型随便幻觉式写入。
显式记忆更可控，也更便于用户理解和删除。
```

## 15. 实现异步文档索引

同步上传适合小文件，异步索引更接近真实工程。

核心文件：

```text
app/api/routes/documents.py
app/services/document_index_queue.py
app/workers/document_indexing.py
app/workers/rq_worker.py
```

状态流转：

```text
pending -> running -> done
pending -> running -> failed
```

API 做：

```text
保存 task:index:{task_id}
enqueue RQ job
返回 202
```

worker 做：

```text
解析文件
切片
embedding
写 Redis vector index
更新任务状态
```

为什么 task 状态仍存在 Redis 项目 key，而不是只依赖 RQ job：

```text
前端轮询需要稳定的业务状态结构，包括 document_id、chunk_count、indexed_keys、error_message。
```

启动 worker：

```powershell
.\.venv\Scripts\python.exe -m app.workers.rq_worker
```

## 16. 接入 checkpoint 查询

checkpoint 是 LangGraph 图执行快照，不等于 session，也不等于 memory。

核心文件：

```text
app/agent/checkpoint.py
app/agent/workflow.py
app/api/routes/agent.py
docs/checkpoint_resume.md
```

当前接口：

```text
GET /api/v1/agent/checkpoints/{thread_id}
GET /api/v1/agent/checkpoints/{thread_id}/history
```

当前只返回 metadata：

```text
thread_id
checkpoint_id
parent_checkpoint_id
step
state_channel_keys
backend
durable
production_ready
resume_supported
human_in_the_loop_supported
```

不返回完整状态的原因：

```text
checkpoint 可能包含用户输入、工具结果、模型输出和内部状态，直接暴露会有隐私风险。
```

当前边界：

```text
local_file checkpoint 支持本地单机 demo reload。
还不是官方 Redis/Postgres production checkpointer。
还没有真正 resume API。
还没有 human-in-the-loop 恢复。
```

## 17. 前端演示控制台

前端不是重点业务系统，它是演示入口。

核心文件：

```text
frontend/src/api.ts
frontend/src/App.tsx
frontend/src/types.ts
frontend/src/styles.css
```

`api.ts` 集中封装 fetch：

```text
checkHealth()
uploadDocumentAsync()
getDocumentTask()
searchDocuments()
runAgent()
```

为什么集中封装：

- 组件不散落 URL。
- 错误处理统一。
- 后续换 API base 更方便。

`App.tsx` 覆盖五个演示区域：

```text
后端连接
文档入库
知识检索
Agent Console
记忆写入
```

前端轮询任务状态：

```text
upload -> task_id -> setInterval(getDocumentTask) -> done/failed
```

这能展示异步 worker 的真实状态，而不是只看上传接口返回。

## 18. 评测脚本和质量闭环

评测是这个项目区别于普通 demo 的关键。

核心文件：

```text
data/eval/rag_questions.json
scripts/evaluate_retrieval.py
scripts/evaluate_rag_answers.py
app/evaluation/retrieval.py
app/evaluation/answer.py
```

retrieval eval 评估：

```text
query 是否成功
top_k sources 是否命中 expected keywords
latency
hit_rate
```

当前真实 embedding 结果：

```text
questions=20
success=20
hit_rate=1.0
avg_latency_ms=1536.66
```

answer eval 评估：

```text
answer 文本
sources
引用编号 [1]/[2]
answer keyword hits
source keyword hits
拒答检测
失败样例
失败分类
改进建议
```

answer eval 现在支持分批和稳定性参数：

```text
--offset
--limit
--max-retries
--retry-delay-seconds
--retry-backoff-multiplier
--inter-request-delay-seconds
```

报告中会输出：

```text
failure_reason_counts
error_category_counts
retryable_failure_count
recommendations
```

当前边界：

```text
真实 embedding retrieval eval 已完成。
真实 LLM answer eval 脚本已增强，能做失败归因和分批评测；但完整 20 题 answer 稳定报告仍要结合本地反代状态继续跑完，不能夸大成稳定完成。
```

面试讲法：

> 我把 RAG 质量拆成检索质量、回答质量和失败归因。检索评测看 top_k 是否命中，回答评测看答案关键词、sources 和引用一致性；如果失败，再区分是检索缺口、模型生成问题、引用不匹配，还是本地 LLM 反代/网络不稳定。

## 19. Docker Compose 组织方式

核心文件：

```text
docker-compose.yml
Dockerfile.api
frontend/Dockerfile
docker/mysql/init/01_job_applications.sql
```

Compose 目标服务：

```text
redis
mysql
api
worker
frontend
```

当前已验证：

- Redis 可启动。
- MySQL 可启动并 healthy。
- Compose 静态配置可解析。
- worker 服务配置存在。

当前边界：

```text
完整 docker compose up -d --build 受 Docker Hub 网络影响，不能说已经完成全镜像构建烟测。
```

## 20. 推荐你按这个顺序复盘代码

第一次复盘不要从复杂 Agent 文件开始。按下面顺序读：

1. `app/main.py`
2. `app/core/config.py`
3. `app/api/routes/health.py`
4. `app/api/dependencies.py`
5. `app/services/llm_client.py`
6. `app/services/redis_client.py`
7. `app/rag/document_loader.py`
8. `app/rag/chunker.py`
9. `app/services/embedding_client.py`
10. `app/rag/indexer.py`
11. `app/rag/retriever.py`
12. `app/rag/answerer.py`
13. `app/api/routes/documents.py`
14. `app/api/routes/rag.py`
15. `app/agent/state.py`
16. `app/agent/workflow.py`
17. `app/tools/registry.py`
18. `app/tools/llm_executor.py`
19. `app/tools/query_database.py`
20. `app/workers/document_indexing.py`
21. `frontend/src/api.ts`
22. `frontend/src/App.tsx`

## 21. 每个阶段你应该能回答的问题

### FastAPI

1. `main.py` 为什么只注册路由，不写业务逻辑？
2. `dependencies.py` 为什么用 `yield` 管理 Redis/LLM/MySQL client？
3. `/health` 和 `/health/redis` 的区别是什么？

### RAG

1. `Document` 和 `DocumentChunk` 的区别是什么？
2. 为什么 chunk 需要 overlap？
3. fake embedding 的价值和限制分别是什么？
4. 为什么 Redis 向量字段要存 FLOAT32 bytes？
5. retrieval eval 的 `hit_rate=1.0` 能说明什么，不能说明什么？

### Agent

1. `AgentState` 和 `AgentRunResponse` 为什么分开？
2. LangGraph 的节点和边在这个项目里分别对应什么？
3. 为什么确定性工具不一定要让 LLM 决策？
4. 为什么 LLM 工具调用要限制最大轮数？
5. checkpoint、session、memory 的区别是什么？

### MySQL

1. 为什么投递记录问题不走 RAG？
2. 为什么不能直接执行 LLM 生成的 SQL？
3. SQL 安全层做了哪些限制？

### 前端

1. 为什么 API 调用集中在 `api.ts`？
2. 为什么异步上传后要轮询 task status？
3. 前端展示 sources 和 steps 对面试有什么价值？

## 22. 当前不要夸大的内容

面试和简历里不要说：

- 已支持 PDF。
- 已完成生产级队列系统。
- 已完成官方 Redis/Postgres LangGraph checkpointer。
- 已完成真正 resume / human-in-the-loop。
- 已完成 LLM 自由生成 SQL。
- 已完成无人工确认自动投递简历。
- 真实 LLM answer eval 已经稳定 20/20。

可以准确说：

- 已支持 `.txt/.md/.docx`。
- 已接入 Redis 向量检索、session、memory、task status。
- 已完成 Qwen3-Embedding-4B 真实 embedding 检索评测，固定 20 题 `hit_rate=1.0`。
- 已接入本地 OpenAI-compatible LLM 反代，并通过 chat、tool-call、Agent 工具闭环 smoke。
- 已接入 MySQL 简历投递数据库问答，第一版是确定性 SQL 模板 + 安全校验 + 只读查询。
- 已用 LangGraph StateGraph 编排 Agent workflow，并提供 checkpoint metadata 查询。
