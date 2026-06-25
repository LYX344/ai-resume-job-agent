# 简历投递版项目话术

这个文件用于把项目压缩成简历、作品集、面试开场和追问回答。原则：只写已经完成并能演示的能力。answer eval 已完成固定 20 题规则化评测（pass / citation 均 1.0），可以写，但要说明是规则化评分而非人工主观质量评分；不夸大 LangGraph 高级能力、PDF 或生产级分布式队列。

## 一句话版本

```text
基于 FastAPI、Redis、MySQL、React/TypeScript 构建个人知识库 Agent/RAG 助手，支持文档索引、向量检索、数据库问答、Agent 工具调用、短期/长期记忆、异步任务和检索评测。
```

## 简历项目名

```text
个人知识库 Agent/RAG 助手 | Python, FastAPI, Redis, React, TypeScript
```

## 简历描述

三行版：

```text
构建个人知识库 Agent/RAG 系统，支持 .txt/.md/.docx 文档上传、切片、Redis 向量检索、RAG 问答、Agent 工具调用、MySQL 投递记录问答和 React 前端演示。
基于 Redis 实现 session 短期记忆、长期 memory profile、RQ 异步索引队列/任务状态和文档 chunk 向量存储，并使用 TTL 管理短生命周期数据。
补充固定问题集检索评测、结构化请求日志、Docker Compose 编排、架构文档和本地 demo smoke 脚本，提升可测试性和可演示性。
```

精简版：

```text
实现个人知识库 Agent/RAG 助手，使用 FastAPI + Redis 完成文档入库、向量检索、Agent 工具调用、记忆系统和 RQ 异步索引，并提供 React 控制台、检索评测和 Docker Compose 本地部署。
```

## 简历要点

建议从下面选 4-5 条，不要全部堆上去：

- 使用 FastAPI 设计后端 API，按 API、Service、RAG、Agent、Tools、Memory、Worker 分层组织代码，并补充单元测试和接口测试。
- 实现 `.txt/.md/.docx` 文档解析、chunk 切片、overlap、embedding、Redis HASH 写入和 RediSearch KNN 检索链路，其中 DOCX 支持段落和表格文本提取。
- 实现 OpenAI-compatible embedding 适配层，支持 fake/真实 embedding provider 切换、维度校验和上游错误处理；当前本地已用 Qwen3-Embedding-4B 重建索引并完成固定问题集 retrieval eval，最新 hit_rate=1.0。
- 扩展 OpenAI-compatible LLM client，支持 `tools/tool_choice` 请求字段、`tool_calls` 响应解析，以及 assistant tool_calls / tool message 二次请求。
- 新增 Agent 工具 schema 注册表，将现有工具导出为 OpenAI-compatible function tool schema，并补充注册表测试。
- 在 Agent 普通聊天分支接入最多 3 轮 bounded LLM tool-call loop，通过 LangGraph `ToolNode` 子图执行安全工具，并将每轮执行结果回传给模型生成最终回答。
- 接入 LangGraph local-file checkpoint，在 Agent 响应中返回 `thread_id`、`checkpoint_id`、`backend=local_file`、`durable=true` 和 `production_ready=false`，并提供 checkpoint latest/history metadata 查询接口用于本地调试图状态。
- 基于 Redis 保存 session 短期记忆、长期 memory profile、RQ 异步任务状态和文档向量数据，使用 key 前缀和 TTL 管理不同生命周期数据。
- 基于 LangGraph StateGraph 实现 Agent workflow，使用条件边在工具执行和跳过工具之间路由，支持 `search_docs`、`calculator`、`create_todo`、`summarize_file`、`draft_weekly_report` 等工具调用，并返回 steps 方便调试。
- 实现 RQ 异步文档索引接口，上传后返回 task_id，API 入队后由独立 worker 消费任务，前端轮询 `pending/running/done/failed` 状态，失败时保留错误原因。
- 使用 React + Vite + TypeScript 构建前端控制台，支持文档上传、任务轮询、知识库检索、Agent 调用、sources/steps 展示和记忆写入。
- 增加固定问题集 retrieval 评测脚本，输出 JSON/Markdown 报告，记录 hit_rate、latency、retrieved chunks 和粗略 token 估算。
- 编写 Docker Compose、架构文档、面试讲解稿和 demo smoke 脚本，保证项目能复现、能验证、能展示。

## 面试开场

30 秒：

> 我做的是一个个人知识库 Agent/RAG 助手。后端用 FastAPI，Redis 不只做缓存，还承担 session、长期记忆、RQ 异步任务队列/状态和向量检索。文档上传后会解析、切片、生成 embedding 并写入 Redis，查询时走 top_k 检索再拼 RAG prompt。Agent 入口支持文档检索、计算器、待办、文件摘要、周报草稿和记忆写入，前端用 React/TypeScript 做了演示控制台。我还补了评测脚本、结构化日志、Docker Compose 和 demo smoke 报告。

10 秒：

> 这是一个 FastAPI + Redis 的个人知识库 Agent/RAG 项目，重点展示文档向量检索、Agent 工具调用、记忆系统、异步索引和前端演示闭环。

## 技术关键词矩阵

| 关键词 | 项目里对应的真实实现 |
|--------|----------------------|
| FastAPI | API 路由、依赖注入、健康检查、文档上传、Agent 接口 |
| Redis | session、memory profile、task status、doc chunk、vector search |
| RAG | 文档解析、chunk、embedding、top_k 检索、sources、prompt |
| Agent | LangGraph StateGraph、conditional edges、intent、steps、deterministic tools、bounded ToolNode execution、local-file checkpoint persistence、checkpoint snapshot/history API、memory、RAG 对接 |
| LLM Adapter | OpenAI-compatible chat、streaming、tools/tool_choice、tool_calls parsing、tool message payload |
| Tools | calculator、create_todo、summarize_file、draft_weekly_report、search_docs、function tool schema registry、ToolNode executor |
| Async | RQ worker、task_id、状态轮询、失败记录 |
| Frontend | React、Vite、TypeScript、任务轮询、sources/steps 展示 |
| Evaluation | 固定问题集、hit_rate、latency、JSON/Markdown 报告 |
| Docker | Redis/MySQL/API/Worker/Frontend Compose 编排、healthcheck、环境变量 |

## 面试追问边界

可以主动说明：

- 仓库默认 embedding 是确定性假 embedding，用于无 Key 情况下验证工程链路；当前本地已完成 Qwen3-Embedding-4B 真实 embedding 检索评测（hit_rate=1.0），并完成固定 20 题真实 RAG answer 规则化评测（pass_rate / citation_match 均 1.0、零错误）。注意 answer eval 是规则化评分（关键词命中 + 引用一致性 + 非拒答），不是人工主观质量评分。
- 当前 LLM client 已支持 tool-calling adapter，普通聊天分支可以执行最多 3 轮 LLM 返回的 tool_calls，并把 ToolNode 执行结果作为 tool message 回传给模型；Agent 响应已返回 local-file checkpoint metadata，并提供 checkpoint latest/history 查询接口，但还没有生产级官方 Redis/Postgres checkpointer、真正从中断点继续执行的 resume 或人工中断恢复。
- 当前异步任务已使用 RQ worker 第一版，API 只入队、worker 消费任务、Redis 保存状态；它还不是完整生产级分布式队列，没有重试退避、死信队列、Dashboard 或调度能力。
- 当前文档解析支持 `.txt`、`.md` 和 `.docx`，PDF 是后续扩展。
- 当前没有做多用户权限系统，MVP 定位是个人单用户知识库；MySQL 已完成简历投递记录数据库问答第一版，但不是生产级多租户权限系统。

不要写：

- 已完成人工主观质量评测的 answer eval（当前完成的是规则化评分 pass/citation 1.0，不要夸大成人工质量评分）。
- 生产级 LangGraph 官方 Redis/Postgres checkpoint、真正从中断点继续执行的 resume 或人工中断恢复。
- 已实现无限循环式 ReAct Agent。
- 支持 PDF。
- 生产级分布式任务队列。
- 多用户权限管理。
- 已完成 LLM 自由生成 SQL、复杂跨表推理或生产级数据库权限系统。

## 投递前检查

1. 后端测试通过：`.\.venv\Scripts\python.exe -m pytest -q`
2. 前端构建通过：`cd frontend` 后运行 `npm run build`
3. demo smoke 通过：`.\.venv\Scripts\python.exe scripts\demo_smoke.py`
4. 生成演示包：`.\.venv\Scripts\python.exe scripts\generate_demo_package.py`
5. README 的当前限制没有过期。
6. `docs/interview_notes.md` 和本文件的说法一致。
7. 简历里没有写当前没实现的功能。

## 阶段 24-34 新增能力（可写进简历要点）

- MCP client 接入：用官方 `mcp` SDK 连接外部 MCP server（stdio / streamable HTTP），发现工具并暴露给 Agent 工具调用循环；能讲清 MCP / Function Calling / Skills 区别（2026 高频考点）。默认 `MCP_ENABLED=false` 可降级、in-memory 可测、真实 stdio smoke。边界：第一版每次操作独立建连、只连可信本地 server。

- 设计并实现 PDF 文本层 / 扫描件 OCR 的 hybrid 解析路由（PaddleOCR 本地 / 视觉 LLM API 可插拔），支持中英混排与公章文字，OCR 不可用优雅降级。
- 实现知识库 collection 隔离 + cross-encoder rerank 两阶段精排：隔离把简历检索 hit_rate 从 0.67 拉到 1.0，rerank 把混查 hit_rate 从 0.67 提到 0.80。
- 实现 supervisor 多 Agent 求职投递工作流（简历分析 → JD 匹配 → 材料生成）+ LangGraph interrupt/resume 人工介入断点续跑。
- 可量化表述示例：基于 LangGraph 设计 supervisor 多 agent 与 HITL 投递流程，结合向量检索 + bge-reranker 精排和 collection 知识库隔离，将简历检索命中率从 0.67 提升至 1.0，并通过固定问题集评测（retrieval hit_rate 1.0、20 题 answer pass/citation 均 1.0）保证质量。
- 边界（不能夸大）：HITL checkpointer 当前为单进程 InMemory；rerank/OCR 依赖外部 API 或本地重依赖，已做降级。
