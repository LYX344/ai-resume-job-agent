# 代码模块拆分详解

这份文档解决一个问题：你看项目代码时，应该知道“这个文件负责什么、输入输出是什么、被谁调用、改功能应该动哪里”。

它和 `docs/code_walkthrough_from_zero.md` 的区别：

- `code_walkthrough_from_zero.md`：按从 0 实现项目的时间顺序学习。
- `code_module_breakdown.md`：按当前工程模块边界学习，适合你复盘、改代码、准备面试追问。

## 1. 总体分层

当前后端大致分 8 层：

```text
app/main.py
  -> api routes
    -> dependencies
      -> services / rag / agent / tools / memory
        -> models
```

更具体地说：

```text
api/       HTTP 接口层，只处理请求、响应和错误码
models/    Pydantic 数据模型，定义输入输出结构
services/  外部依赖适配层，例如 LLM、Redis、MySQL、RQ
rag/       文档知识库链路：解析、切片、入库、检索、回答
agent/     LangGraph Agent 编排层
tools/     Agent 可调用工具
memory/    短期会话和长期记忆的业务逻辑
workers/   异步文档索引 worker
```

判断一个文件该放哪一层，可以问：

```text
它是在处理 HTTP 吗？放 api/
它是在定义数据形状吗？放 models/
它是在连接外部系统吗？放 services/
它是在处理知识库文档吗？放 rag/
它是在编排 Agent 节点吗？放 agent/
它是一个可被 Agent 调用的能力吗？放 tools/
它是在处理会话或用户偏好吗？放 memory/
它是后台任务执行入口吗？放 workers/
```

## 2. app/main.py：应用装配层

文件：

```text
app/main.py
```

职责：

- 创建 FastAPI 实例。
- 安装请求日志中间件。
- 安装 CORS。
- 注册所有 router。

不该做：

- 不直接连接 Redis。
- 不直接调用 LLM。
- 不写 RAG 或 Agent 业务逻辑。

调用关系：

```text
uvicorn app.main:app
  -> create_app()
  -> include_router(...)
```

如果你要新增一个新接口模块，例如 `jobs.py`：

1. 在 `app/api/routes/jobs.py` 里写 router。
2. 在 `app/main.py` import。
3. `app.include_router(jobs_router, prefix=settings.api_prefix)`。

## 3. app/core：全局配置和日志

文件：

```text
app/core/config.py
app/core/logging.py
```

### config.py

职责：

- 读取 `.env`。
- 提供所有可配置参数。
- 生成 Redis vector index 配置对象。

典型配置：

```text
LLM_BASE_URL
LLM_MODEL
LLM_API_KEY
EMBEDDING_PROVIDER
REDIS_URL
MYSQL_URL
AGENT_CHECKPOINT_BACKEND
```

核心原则：

```text
真实敏感值只在本地 .env。
代码、README、docs、tests 只写示例变量名，不写真实 key。
```

改动点：

- 新增环境变量：先在 `Settings` 加字段，再在 `.env.example` 加示例。
- 新增 Redis vector 参数：同时检查 `settings.redis_vector_index`。

### logging.py

职责：

- 设置日志格式。
- 给每个 HTTP 请求生成或透传 request id。
- 记录 method、path、status、duration。

边界：

```text
不记录请求体。
```

原因：

```text
请求体可能包含用户问题、文档内容、隐私信息或 key。
```

## 4. app/api：HTTP 接口层

文件：

```text
app/api/dependencies.py
app/api/routes/health.py
app/api/routes/chat.py
app/api/routes/documents.py
app/api/routes/rag.py
app/api/routes/agent.py
```

接口层统一职责：

- 接收 HTTP 请求。
- 通过 Depends 获取 service。
- 调用业务函数。
- 捕获异常并转换为 HTTP 错误码。
- 返回 Pydantic response model。

接口层不该做：

- 不写复杂业务判断。
- 不直接拼 prompt。
- 不直接写 Redis 命令。
- 不直接写 SQL。

### dependencies.py

职责：

```text
把外部依赖变成 FastAPI 可注入对象。
```

主要函数：

```text
get_llm_client()
get_redis_store()
get_mysql_store()
get_embedding_client()
get_document_index_queue()
```

为什么 LLM、Redis、MySQL 用 `yield`：

```text
它们有连接生命周期，用完要关闭。
```

为什么 embedding client 直接 return：

```text
当前 fake client 和 openai-compatible embedding client 没有长期持有连接。
```

### health.py

接口：

```text
GET /health
GET /health/redis
GET /health/mysql
```

学习重点：

```text
/health 只能说明应用进程还活着。
/health/redis 和 /health/mysql 才说明外部依赖可用。
```

### documents.py

接口：

```text
POST /documents/upload
POST /documents/upload/async
GET  /documents/tasks/{task_id}
POST /documents/search
```

它连接了两条链路：

```text
同步入库：upload -> loader -> chunker -> indexer -> Redis
异步入库：upload/async -> Redis task -> RQ queue -> worker
```

错误码边界：

```text
400 文件类型、空文档、参数错误
502 Redis 或 embedding provider 失败
503 embedding 配置缺失
404 task_id 不存在
```

### rag.py

接口：

```text
POST /rag/query
```

职责：

```text
把 HTTP 请求交给 answer_rag_query()
```

它不直接做检索和 prompt 拼接，具体逻辑在 `app/rag/answerer.py`。

### agent.py

接口：

```text
POST /agent/run
GET  /agent/checkpoints/{thread_id}
GET  /agent/checkpoints/{thread_id}/history
```

`/agent/run` 是综合入口：

```text
用户问题
-> run_agent_workflow()
-> LangGraph 节点编排
-> 返回 answer + steps + sources + checkpoint
```

checkpoint 查询接口只返回 metadata，不返回完整状态。

## 5. app/models：数据结构层

文件：

```text
app/models/agent.py
app/models/chat.py
app/models/document.py
app/models/embedding.py
app/models/health.py
app/models/memory.py
app/models/rag.py
app/models/session.py
app/models/vector_index.py
```

`models/` 在本项目里不是 MySQL ORM。

它的职责是：

- 定义 HTTP request / response。
- 定义内部业务对象。
- 做基础字段校验。

### document.py

关键模型：

```text
Document              整篇文档
DocumentChunk         切片后的文档块
DocumentIngestResponse 上传入库响应
DocumentIndexTaskState 异步任务状态
DocumentSearchRequest  检索请求
DocumentSearchResult   检索结果
```

`Document` 和 `DocumentChunk` 的区别：

```text
Document 是完整文件。
DocumentChunk 是用于向量检索的最小知识单元。
```

### agent.py

关键模型：

```text
AgentRunRequest
AgentRunResponse
AgentStep
AgentCheckpointInfo
AgentCheckpointSnapshotResponse
AgentCheckpointHistoryResponse
```

`AgentStep` 的价值：

```text
让 Agent 运行过程可观察。
前端可以展示每个节点做了什么。
面试时可以证明它不是普通聊天接口。
```

### rag.py

关键模型：

```text
RagQueryRequest
RagQueryResponse
RagSource
```

为什么 response 要带 sources：

```text
RAG 的答案必须能追溯来源。
answer 是模型生成结果，sources 是项目结构化检索结果。
```

## 6. app/services：外部系统适配层

文件：

```text
app/services/llm_client.py
app/services/embedding_client.py
app/services/redis_client.py
app/services/mysql_client.py
app/services/document_index_queue.py
```

这一层的核心思想：

```text
把不稳定的外部系统封装起来。
业务层只调用稳定的项目内部接口。
```

### llm_client.py

输入：

```text
messages
model
temperature
max_tokens
tools
tool_choice
```

输出：

```text
LLMChatResult
  content
  model
  finish_reason
  usage
  tool_calls
```

核心封装：

```text
OpenAI-compatible /chat/completions
```

如果你要换模型服务：

```text
只改 .env 中的 LLM_BASE_URL、LLM_MODEL、LLM_API_KEY。
```

如果要支持新的响应格式：

```text
改 _parse_chat_response() 和 _parse_tool_calls()。
```

### embedding_client.py

输入：

```text
text 或 texts
```

输出：

```text
TextEmbedding(text, embedding)
```

两种实现：

```text
DeterministicEmbeddingClient
OpenAICompatibleEmbeddingClient
```

如果检索质量差，先判断：

```text
是 fake embedding 的限制？
是真实 embedding 没重建索引？
是知识库内容没覆盖？
是 top_k 太小？
```

### redis_client.py

负责四类 Redis 数据：

```text
JSON string: session、memory、task
HASH: doc chunk
RediSearch index: vector search
FLOAT32 bytes: embedding field
```

常用方法：

```text
save_session()
get_session()
save_memory_profile()
get_memory_profile()
save_index_task()
get_index_task()
ensure_vector_index()
save_document_chunk()
search_document_chunks()
delete_document_chunks()
```

如果你要看 Redis key 设计，优先读这里。

### mysql_client.py

职责：

- 解析 MySQL URL。
- 创建 PyMySQL 连接。
- 执行只读 SELECT。
- schema introspection。
- SQL 安全校验。

SQL 安全入口：

```text
prepare_safe_select()
  -> normalize_sql()
  -> validate_readonly_select()
  -> enforce_limit()
```

如果未来做 LLM Text-to-SQL，仍然必须复用这层安全校验。

### document_index_queue.py

职责：

```text
把文档索引任务放进 RQ 队列。
```

为什么用 Protocol：

```text
DocumentIndexQueue 是抽象接口。
RQDocumentIndexQueue 是当前实现。
以后换 Celery 或其他队列，不需要改路由层。
```

## 7. app/rag：知识库链路

文件：

```text
app/rag/document_loader.py
app/rag/chunker.py
app/rag/indexer.py
app/rag/retriever.py
app/rag/answerer.py
```

完整入库链路：

```text
load_uploaded_document()
-> chunk_document()
-> index_document_chunks()
-> embedding_client.embed_texts()
-> redis_store.save_document_chunk()
```

完整问答链路：

```text
answer_rag_query()
-> retrieve_document_chunks()
-> to_rag_sources()
-> build_rag_messages()
-> llm_client.chat()
```

### document_loader.py

输入：

```text
文件路径 或 上传文件 bytes
```

输出：

```text
Document
```

负责格式差异：

```text
.txt/.md 按 UTF-8 解码
.docx 用 python-docx 提取文本
```

后续模块不再关心文件格式。

### chunker.py

输入：

```text
Document
```

输出：

```text
list[DocumentChunk]
```

负责：

- chunk_size。
- chunk_overlap。
- char range。
- chunk metadata。

### indexer.py

输入：

```text
list[DocumentChunk]
embedding_client
redis_store
```

输出：

```text
list[str] indexed_keys
```

它是入库编排函数，不直接知道 HTTP、文件上传或 RQ。

### retriever.py

输入：

```text
query
top_k
embedding_client
redis_store
```

输出：

```text
list[DocumentSearchResult]
```

职责：

```text
query embedding + Redis KNN search
```

### answerer.py

输入：

```text
query
sources 或 检索依赖
llm_client
```

输出：

```text
RagQueryResponse(answer, sources, model, usage)
```

最重要的边界：

```text
没有 sources 时不调用 LLM，直接拒答。
```

## 8. app/agent：Agent 编排层

文件：

```text
app/agent/state.py
app/agent/workflow.py
app/agent/checkpoint.py
```

### state.py

`AgentState` 是 LangGraph 内部状态。

它包含：

```text
输入参数：query、session_id、top_k
路由状态：intent、needs_retrieval、selected_tool
工具状态：tool_result、sources
LLM 工具调用：proposed_tool_calls、executed_tool_calls
记忆：session、memory_profile、memory_used
输出：answer、finish_reason、usage
可观察性：steps、checkpoint
```

### workflow.py

入口：

```text
run_agent_workflow()
```

建图：

```text
_build_agent_graph()
```

节点函数：

```text
load_memory()
understand_intent()
decide_retrieval()
call_tools()
skip_tools()
generate_answer()
save_trace()
```

路由函数：

```text
_route_after_decide_retrieval()
```

普通聊天工具循环：

```text
_run_general_chat_with_bounded_tools()
```

学习建议：

```text
不要从文件第一行读到最后一行。
先读 run_agent_workflow()。
再读 _build_agent_graph()。
然后按节点顺序读。
最后读 helper 函数。
```

### checkpoint.py

职责：

```text
把 LangGraph InMemorySaver 包装成本地文件持久化。
```

当前边界：

```text
local_file 只适合单机 demo。
不是生产级 Redis/Postgres checkpointer。
```

## 9. app/tools：工具层

文件：

```text
app/tools/calculator.py
app/tools/create_todo.py
app/tools/draft_weekly_report.py
app/tools/search_docs.py
app/tools/summarize_file.py
app/tools/query_database.py
app/tools/registry.py
app/tools/llm_executor.py
```

工具分两类：

```text
规则路由工具：workflow 直接调用
LLM 自动工具：模型返回 tool_calls 后执行
```

当前 LLM 自动工具只开放：

```text
calculator
create_todo
summarize_file
draft_weekly_report
```

不自动开放：

```text
memory_profile
query_database
```

原因：

- 记忆写入影响长期状态，必须显式。
- 数据库查询涉及结构化隐私数据，当前走确定性 intent 路由。

### registry.py

职责：

```text
把项目工具导出成 OpenAI-compatible function tool schema。
```

它告诉模型：

```text
工具叫什么
能做什么
参数 JSON schema 是什么
```

### llm_executor.py

职责：

```text
执行 LLM 返回的 tool_calls。
```

链路：

```text
LLMToolCall
-> JSON arguments
-> LangGraph ToolNode
-> ToolMessage
-> OpenAI-compatible tool message
```

如果你要新增一个 LLM 自动工具：

1. 在工具文件里实现确定性函数。
2. 在 `registry.py` 加 `ToolSchema`。
3. 在 `llm_executor.py` 加 wrapper 函数。
4. 加入 `LLM_EXECUTABLE_TOOL_NAMES`。
5. 补测试。

## 10. app/memory：记忆层

文件：

```text
app/memory/session.py
app/memory/profile.py
```

短期记忆：

```text
SessionState
session:{session_id}
有 TTL
```

长期记忆：

```text
MemoryProfile
memory:profile:default
无 TTL
```

显式记忆提取：

```text
extract_memory_updates()
```

格式化给 LLM 的记忆：

```text
format_memory_context()
```

边界：

```text
长期记忆是辅助上下文，不是知识库引用来源。
```

## 11. app/workers：异步任务层

文件：

```text
app/workers/document_indexing.py
app/workers/rq_worker.py
```

### document_indexing.py

负责真正执行索引：

```text
run_document_index_task()
  -> task running
  -> load_uploaded_document()
  -> chunk_document()
  -> index_document_chunks()
  -> task done/failed
```

注意：

```text
worker 和同步上传复用同一套 loader/chunker/indexer。
```

### rq_worker.py

职责：

```text
启动 RQ worker，监听 document-index queue。
```

运行：

```powershell
.\.venv\Scripts\python.exe -m app.workers.rq_worker
```

## 12. frontend：演示界面层

文件：

```text
frontend/src/api.ts
frontend/src/App.tsx
frontend/src/types.ts
frontend/src/styles.css
```

### api.ts

职责：

```text
集中封装 fetch。
```

函数：

```text
checkHealth()
uploadDocumentAsync()
getDocumentTask()
searchDocuments()
runAgent()
```

如果后端路径变了，优先改这里。

### App.tsx

页面模块：

```text
后端连接
文档入库
知识检索
Agent Console
记忆写入
```

展示重点：

```text
Agent answer
Agent steps
RAG sources
task status
distance
```

这不是完整生产前端，是作品集演示控制台。

## 13. scripts：评测和运维脚本

文件：

```text
scripts/demo_smoke.py
scripts/evaluate_retrieval.py
scripts/evaluate_rag_answers.py
scripts/generate_demo_package.py
scripts/prepare_embedding_switch.py
scripts/run-backend-8025.ps1
```

### prepare_embedding_switch.py

用途：

```text
切换真实 embedding 前检查/清理旧 Redis doc:* chunk 和 vector index。
```

安全设计：

```text
默认 dry-run。
真正删除必须显式传 --execute 和 --yes-i-understand-data-loss。
```

### evaluate_retrieval.py

用途：

```text
评估 top_k 检索是否命中预期 sources。
```

### evaluate_rag_answers.py

用途：

```text
评估真实 RAG answer、sources、引用编号、关键词命中、拒答和失败分类。
```

关键能力：

```text
--offset / --limit                  分批评测
--max-retries                        transient failure 重试次数
--retry-delay-seconds               初始重试等待
--retry-backoff-multiplier          重试退避倍率
--inter-request-delay-seconds       每题之间冷却，适合本地反代不稳定时使用
```

报告会记录：

```text
failure_reasons
primary_failure_reason
error_category
retryable
failure_reason_counts
error_category_counts
recommendations
```

当前边界：

```text
脚本已增强，但完整 20 题真实 LLM answer 稳定报告仍需要结合本地反代状态分批跑完。
```

### generate_demo_package.py

用途：

```text
整理最新 smoke/eval 报告、截图清单、录屏流程和边界说明。
```

## 14. tests：测试对应关系

你看代码时要同时看测试。

常见对应关系：

```text
app/services/llm_client.py          -> tests/test_llm_client.py
app/services/embedding_client.py    -> tests/test_embedding_client.py
app/services/redis_client.py        -> tests/test_redis_client.py
app/services/mysql_client.py        -> tests/test_mysql_client.py
app/rag/document_loader.py          -> tests/test_document_processing.py
app/api/routes/documents.py         -> tests/test_documents_api.py
app/api/routes/rag.py               -> tests/test_rag_api.py
app/agent/workflow.py               -> tests/test_agent_api.py
app/agent/workflow.py graph helpers -> tests/test_agent_workflow_graph.py
app/tools/registry.py               -> tests/test_tool_registry.py
app/tools/llm_executor.py           -> tests/test_llm_tool_executor.py
app/tools/query_database.py         -> tests/test_query_database_tool.py
scripts/generate_demo_package.py    -> tests/test_generate_demo_package.py
app/evaluation/*                    -> tests/test_evaluation_*.py
```

学习方法：

```text
先读测试名。
再读测试输入。
再读断言。
最后回到实现文件看它如何满足断言。
```

## 15. 常见需求应该改哪里

### 新增一个文档格式

改：

```text
app/rag/document_loader.py
tests/test_document_processing.py
app/api/routes/documents.py 如需调整错误提示
frontend/src/App.tsx 的 accept
```

不要改：

```text
chunker.py
indexer.py
retriever.py
```

前提是新格式最终也能输出 `Document`。

### 新增一个确定性工具

改：

```text
app/tools/new_tool.py
app/agent/workflow.py 的 understand_intent/call_tools/generate_answer
tests/test_new_tool.py
tests/test_agent_api.py
```

如果要给 LLM 自动调用，还要改：

```text
app/tools/registry.py
app/tools/llm_executor.py
tests/test_tool_registry.py
tests/test_llm_tool_executor.py
```

### 新增一个数据库问答类型

改：

```text
app/tools/query_database.py
tests/test_query_database_tool.py
```

如果需要新表：

```text
docker/mysql/init/01_job_applications.sql
app/core/config.py 的 mysql_allowed_tables
app/services/mysql_client.py 的安全边界测试
```

### 换 embedding 模型

改：

```text
.env
EMBEDDING_BASE_URL
EMBEDDING_MODEL
EMBEDDING_DIMENSIONS
REDIS_VECTOR_DIMENSION
```

然后必须：

```text
清理旧 doc:* chunk 和 index
重新上传文档
重新跑 retrieval eval
```

不要只改模型名就直接评测。

### 换 LLM 模型

改：

```text
.env
LLM_BASE_URL
LLM_MODEL
LLM_API_KEY
```

验证：

```text
普通 chat smoke
tool-call smoke
Agent 工具闭环 smoke
RAG answer eval
```

### 做真正的生产级 resume

不能只改 checkpoint 查询接口。

需要新增：

```text
官方 Redis/Postgres checkpointer
resume request model
可中断节点
human approval payload
resume API
并发和生命周期管理
安全的 checkpoint state 暴露策略
```

## 16. 面试时的模块讲法

可以这样讲：

> 这个项目不是把所有逻辑堆在一个 Agent 函数里。我把 HTTP 接口、模型适配、Redis/MySQL 外部依赖、RAG 文档链路、LangGraph Agent 编排、工具系统、记忆系统和异步 worker 拆开。这样每层职责明确：API 层只处理请求响应，RAG 层只处理知识库，Agent 层只负责编排和路由，services 层负责外部系统适配。

如果面试官追问“为什么这么拆”，回答：

> 因为 RAG、SQL 查询、工具调用和记忆是不同性质的数据路径。非结构化文档走向量检索，结构化投递记录走 MySQL 只读查询，确定性任务直接调用工具，普通聊天再交给 LLM。拆开后更容易测试，也更容易说明安全边界。

## 17. 你现在最该掌握的 5 条调用链

### 文档同步入库

```text
POST /documents/upload
-> load_uploaded_document()
-> chunk_document()
-> index_document_chunks()
-> embedding_client.embed_texts()
-> redis_store.save_document_chunk()
```

### 文档异步入库

```text
POST /documents/upload/async
-> create_document_index_task()
-> redis_store.save_index_task()
-> RQDocumentIndexQueue.enqueue_document_index_task()
-> worker run_document_index_task()
-> loader/chunker/indexer
```

### 文档检索

```text
POST /documents/search
-> retrieve_document_chunks()
-> embedding_client.embed_text()
-> redis_store.search_document_chunks()
```

### RAG 问答

```text
POST /rag/query
-> answer_rag_query()
-> retrieve_document_chunks()
-> build_rag_messages()
-> llm_client.chat()
```

### Agent 运行

```text
POST /agent/run
-> run_agent_workflow()
-> LangGraph load_memory
-> understand_intent
-> decide_retrieval
-> call_tools / skip_tools
-> generate_answer
-> save_trace
-> AgentRunResponse
```
