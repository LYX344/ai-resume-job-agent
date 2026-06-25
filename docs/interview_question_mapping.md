# 真实面试题导向优化映射

来源：用户整理的真实面试题笔记。原始文件不进入公开仓库。

这份文档的目的不是背答案，而是把真实面试高频问题反向映射到本项目：

```text
面试常考点
-> 本项目已经能支撑什么
-> 现在不能夸大什么
-> 下一步应该怎么对向优化
```

## 1. 总体判断

这个项目最适合对齐的面试方向：

- AI Agent / RAG / 知识库系统
- LangGraph / 工具调用 / Agent workflow
- Redis 向量检索、缓存、会话、任务状态
- MySQL 结构化数据库问答
- 异步队列和长任务状态追踪
- 前后端分离演示
- 从 0 到 1 架构设计和项目推进
- AI 编程工作流、成本控制、质量评测

这个项目不适合直接 claim 的方向：

- 企微 H5 登录、微信支付、秒杀系统、红包动画。
- Canvas 无限画布、WebAssembly。
- NestJS、TypeORM、Prisma、NextJS 深度项目经验。
- K8S 多租户生产部署。
- Elasticsearch 混合检索已经落地。
- AGUI 协议动态渲染已经落地。
- 生产级高并发系统压测。

正确策略：

```text
强相关题：用本项目直接回答。
弱相关题：用本项目思路迁移回答，明确未落地。
无关题：不硬套项目，单独按八股/方案题准备。
```

## 2. 高频考点优先级

| 优先级 | 高频考点 | 本项目匹配度 | 当前状态 | 对向优化建议 |
|---|---|---:|---|---|
| P0 | AI 系统架构分层 | 高 | 已具备 FastAPI + RAG + Agent + Redis + MySQL + Frontend | 固化一套 1 分钟架构讲法 |
| P0 | RAG 流程和检索准确性 | 高 | retrieval eval `hit_rate=1.0` + 20 题 answer eval `pass_rate`/`citation_match` 均 1.0 | 已完成检索与答案规则化评测；可扩展人工质量评分 |
| P0 | LangGraph 为什么选型 | 高 | 已迁移 StateGraph、条件边、ToolNode、checkpoint metadata | 补“为什么不是纯 LangChain/手写流程”的讲法 |
| P0 | 工具调用失败怎么处理 | 高 | 有工具 schema、bounded loop、错误包装 | 增加工具失败分类和兜底策略文档/测试 |
| P0 | AI 成本优化 | 中高 | 有 fake embedding、no sources 不调 LLM、top_k、max_tokens、评测 | 补 token/调用次数统计和成本估算报告 |
| P1 | 向量库选型和数据量 | 高 | 使用 Redis vector search，当前 demo 数据量较小 | 增加数据量边界、压测/扩展方案说明 |
| P1 | 上下文压缩/治理 | 中 | 有 chunk、top_k、memory context 边界 | 补 query rewrite、context packing、摘要压缩方案 |
| P1 | 异步队列可靠性 | 中高 | 已从 BackgroundTasks 升级 RQ worker | 补 retry、幂等、失败队列、任务不丢失说明 |
| P1 | 数据库和缓存一致性 | 中 | Redis/MySQL 分工清楚，但无强一致业务 | 补一致性方案文档，区分本项目是否需要 |
| P1 | SSE/WebSocket 区别和断线恢复 | 中 | 后端有 SSE chat stream，前端未接流式恢复 | 补 SSE 断线重连/Last-Event-ID 设计 |
| P2 | MySQL 慢查询/索引优化 | 中 | 有 MySQL 投递表和安全 SQL | 补索引、EXPLAIN、慢查询优化案例 |
| P2 | 前端 React/Vue 对比 | 中 | 当前 React + Vite + TS | 准备 React/Vue 面试答法，不强说 Vue 项目经验 |
| P2 | Docker/K8S | 中 | 有 Docker Compose，未生产 K8S | 补 Docker 镜像/容器/volume/network 讲法 |
| P0 | 多 Agent 协作 | 高 | 已实现 supervisor + 简历分析/JD匹配/材料生成三子 agent（LangGraph 循环图） | 讲 supervisor 路由、按完成步骤判断、多 agent 适用场景 |
| P1 | RAG 检索精排 Re-rank | 高 | 已实现向量召回 + bge-reranker 两阶段精排，混查 hit_rate 0.67→0.80 | 讲混合检索为何还要 rerank、召回率提升 |
| P1 | 断点续跑 / HITL | 中高 | 已实现 LangGraph interrupt/Command，从中断点恢复 + 人工审核 | 讲真 resume（非只读快照）、人工介入边界 |
| P1 | PDF / 文档入库 / 人工审核 | 高 | 已支持 PDF 文本层 + 扫描 OCR hybrid 路由 + HITL 审核 | 讲文本型/扫描型分流、OCR 可插拔、知识库隔离 |
| P3 | 秒杀/支付/企微登录 | 低 | 项目不覆盖 | 单独准备方案题，不写入本项目亮点 |

## 3. AI Agent / RAG 类问题

真实题包括：

- AI 系统主要做什么？
- 介绍 AI 项目的架构情况。
- 简单介绍 RAG 流程。
- 用户问题如何路由到 AI 系统？
- 意图识别如何实现？
- 如何做向量化和知识库检索？
- 文档、PDF、课件如何切分、入库、人工审核？
- AI 回答效果差时从哪些环节优化？

### 本项目可直接支撑

项目架构：

```text
FastAPI API 层
-> LangGraph Agent workflow
-> RAG 文档知识库 / MySQL 投递记录 / 确定性工具 / 记忆系统
-> Redis 向量检索、session、memory、task 状态
-> React 控制台演示
```

RAG 流程：

```text
上传 .txt/.md/.docx
-> Document
-> DocumentChunk
-> embedding
-> Redis HASH + vector index
-> query embedding
-> Redis KNN top_k
-> sources
-> prompt
-> LLM answer with citations
```

意图路由：

```text
calculation -> calculator
todo -> create_todo
weekly report -> draft_weekly_report
file summary -> summarize_file
memory update -> memory_profile
job application query -> query_database
knowledge query -> search_docs/RAG
general chat -> LLM + bounded tool-call loop
```

检索准确性：

```text
已使用硅基流动 Qwen3-Embedding-4B 重建 Redis 索引。
固定 20 题 retrieval eval：hit_rate=1.0。
```

### 不能夸大（已随阶段 24-29 升级更新）

- 已支持 `.txt/.md/.docx/.pdf`；PDF 含文本层 / 扫描件 OCR 的 hybrid 路由（PaddleOCR 本地 / 视觉 LLM API 可插拔，OCR 不可用优雅降级）。
- 已有 human-in-the-loop 审核：投递流程在 JD 匹配后中断，人工审核补充后再恢复生成材料（不是全自动）。
- 不是 Elasticsearch + Redis 混合检索；但已做向量召回 + cross-encoder rerank（bge-reranker-v2-m3）两阶段精排，并用 collection tag 做知识库标量隔离。
- answer eval 是规则化评分（关键词命中 + 引用一致性 + 非拒答），不等于人工主观质量评分。
- HITL 的 checkpointer 当前是单进程 InMemory 单例，生产需共享 Redis/Postgres checkpointer。

### 对向优化

建议下一步做：

1. **真实 RAG answer eval 收口（已完成）**
   - 已跑完固定 20 题：`pass_rate` / `citation_match` 均 1.0、零错误（报告 `data/eval/runs/answer_eval_20260618_151548.md`）。
   - 报告记录 answer、sources、引用编号、失败原因和改进建议。
   - 已对本地反代 5xx/空响应做 retry + cooldown + 失败分类；根因（模型名不可用）已修复为 `deepseek-v4-pro`。

2. **深化 query rewrite / context packing**
   - query rewrite 第一版已实现，并带三级降级；后续重点是对比非推理模型、固定 JSON 输出和更多口语化问题集。
   - context packing 仍可深化：按 distance / rerank score / token 预算组织上下文，减少无关片段。
   - answer eval 可继续做优化前后对比。

3. **深化 PDF/OCR 和人工审核**
   - PDF loader 已完成文本层解析 + 扫描页 OCR fallback；后续可做表格/版面结构化、OCR 质量评测和失败页人工复核。
   - 求职投递 workflow 已有 HITL review/resume；后续可把人工审核结果回写 MySQL 投递状态并做审计记录。

## 4. LangGraph / Agent / 工具调用类问题

真实题包括：

- LangChain / LangGraph 主要用了什么 AI 技术？
- 为什么选择 LangGraph？选型依据是什么？
- Claude Code 的核心循环流程？
- 工具调用失败怎么解决？
- 多智能体是什么，为什么需要？
- 单 Agent 也能分配多个职能，为什么还要多 Agent？
- 多 Agent 动态路由如何根据条件分配任务分支？

### 本项目可直接支撑

LangGraph 能力：

```text
StateGraph
条件边
ToolNode 子图
bounded 多轮工具调用
checkpoint metadata
local-file checkpoint
```

Agent 节点：

```text
load_memory
understand_intent
decide_retrieval
call_tools / skip_tools
generate_answer
save_trace
```

工具调用闭环：

```text
模型返回 tool_calls
-> 项目解析 arguments
-> ToolNode 执行工具
-> tool message 回传模型
-> 模型生成最终回答
```

工具调用防失控：

```text
MAX_LLM_TOOL_CALL_ROUNDS = 3
达到上限后不再提供 tools，强制生成最终回答。
```

MCP / Function Calling / Skills 区别（阶段 34 已落地）：

```text
Function Calling = 模型决定“调哪个工具、传什么参数”（产出调用意图）
MCP             = 工具/数据源“怎么被标准暴露和调用”的协议
                  （client/server, stdio/HTTP, initialize→list_tools→call_tool）
Skills          = 把领域知识/操作流程打包成可复用能力（知识/流程封装，非传输协议）
组合            = MCP client 发现外部工具(inputSchema) → 转 OpenAI function schema
                  → 模型 Function Calling → MCP call_tool 执行
```

本项目 MCP 接入：用官方 `mcp` SDK 自研 client，Agent 普通聊天分支合并外部 MCP server 工具，默认 `MCP_ENABLED=false` 优雅降级，in-memory 可测 + 真实 stdio smoke（`/api/v1/mcp/tools`、`/api/v1/mcp/servers`）。

### 不能夸大

- 当前没有 Planner / Executor / Critic 多角色协作（multi-agent 仅 supervisor + 3 子 agent 的求职投递工作流）。
- 当前 checkpoint metadata 查询不等于生产级 resume。
- MCP 第一版每次操作独立建连（非连接池），只连接可信本地 server；不是任意第三方 MCP server 即插即用的生产级网关。

### 对向优化

建议：

1. **工具失败分类（已完成第一版）**
   - 已在 `app/tools/llm_executor.py` 的 `ExecutedToolCall.error_category` 落地：`invalid_arguments`（参数 JSON 非法）、`unknown_tool`（执行前拦截非白名单工具）、`tool_execution_error`（工具内部异常，经 LangGraph ToolNode `handle_tool_errors` 捕获）。
   - 工具调用轮数触顶由 `tool_call_limit_reached` 标记，达到 `MAX_LLM_TOOL_CALL_ROUNDS=3` 后强制不带 tools 收束。
   - 上游 LLM 错误分层：`LLMProviderError`（5xx/网络抖动）在普通聊天路径降级兜底并记录 `provider_error`；`LLMConfigurationError`（未配置 Key）仍返回 503。
   - 失败分类已汇总进 Agent `generate_answer` step data（`tool_error_category_counts`、`provider_error`），可观察、可演示。

2. **补多 Agent 方案文档**
   - 当前为什么不用多 Agent。
   - 什么时候需要：任务复杂、角色职责冲突、需要审查/规划/执行分离。
   - 未来怎么拆：Planner Agent、Retriever Agent、SQL Agent、Writer Agent、Reviewer Agent。

3. **补 Claude Code 类核心循环对照讲法**
   - observe context。
   - plan。
   - act with tools。
   - observe tool result。
   - revise。
   - final response。

## 5. AI 成本、Token、效果评测类问题

真实题包括：

- Token 消耗量大概多少？
- 有没有考虑怎么节约 AI 成本？
- 做了哪些成本优化？
- 最终降了多少成本？
- 没用 AI 和用了 AI 后效率提升多少？
- 同一个模型不同工具，或同一个工具不同模型，效果差异有没有研究？

### 本项目可直接支撑

已有成本意识：

- fake embedding 模式用于本地开发，避免调真实模型。
- 无 sources 时不调用 LLM。
- `top_k` 可控。
- `max_tokens` 可配置。
- RAG 先评 retrieval，再评 answer，避免盲目调用大模型。
- 真实 embedding 切换前有 dry-run 清理脚本，避免混存导致重复试错。

### 不能夸大

- 当前没有完整 token 成本 dashboard。
- 当前没有按月真实用户 token 报表。
- 当前没有 AB 测试不同模型成本/效果。

### 对向优化

建议做一个轻量成本报告：

```text
data/eval/runs/cost_report_*.md
```

记录：

- 每轮评测问题数。
- LLM 成功/失败次数。
- prompt/completion token。
- 平均 latency。
- 估算成本。
- fake embedding 与真实 embedding 的用途区别。
- 模型失败造成的重试成本。

面试讲法：

> 我把成本优化分成开发期和运行期。开发期用 fake embedding 和 mock 测试减少无效调用；运行期通过 no-context 拒答、top_k、max_tokens、评测分批、失败重试控制来减少 token 浪费。

## 6. Redis / 向量库 / 缓存一致性类问题

真实题包括：

- 向量库使用什么？选型依据？
- RAG 怎么加速检索？
- Redis 分布式锁或 Lua 怎么用？
- 数据库和缓存一致性怎么保证？
- 数据量有多大？
- Elasticsearch + 向量库怎么做混合检索？
- 为什么混合检索后还需要 rerank？

### 本项目可直接支撑

Redis 用法：

```text
session 短期会话
memory profile 长期记忆
task index 状态
doc chunk HASH
RediSearch vector index
```

选型依据：

```text
个人项目和本地 demo 中，Redis 能同时承担缓存、状态、队列和向量检索，部署简单，面试展示集中。
```

### 不能夸大

- 当前数据量是 demo 级，不是百万级向量。
- 当前没有 Elasticsearch。
- 当前没有真正 hybrid search。
- 当前没有 reranker。
- 当前没有 Redis 分布式锁业务。

### 对向优化

建议：

1. **补 Redis key 设计和容量边界说明**
   - key prefix。
   - TTL。
   - vector dimension。
   - 数据量增加后的拆分方案。

2. **实现第一版 hybrid search 方案或设计文档**
   - keyword filter / BM25。
   - vector KNN。
   - merge + dedupe。
   - rerank。

3. **补缓存一致性方案文档**
   - 本项目 MySQL 投递记录当前不做缓存。
   - 如果未来缓存投递统计，用 Cache Aside。
   - 写后删除缓存，必要时延迟双删。
   - 强一致场景直接读 MySQL。

## 7. 异步队列 / 长任务可靠性类问题

真实题包括：

- Bull Queue 处理视频解析、Embedding 长任务，进程崩溃/K8S 重启后任务会不会丢？
- 如何保证消息队列任务不丢失？
- 任务重试会造成重复执行、重复调用大模型，如何优化？
- 任务中途中断如何断点续跑？
- 前端如何感知后端任务中断、终止、运行状态？
- 支付为什么要用异步队列？队列挂了如何保证一致性？

### 本项目可直接支撑

当前异步链路：

```text
POST /documents/upload/async
-> Redis task pending
-> RQ queue
-> worker running
-> done / failed
-> 前端轮询 task status
```

已完成：

- API 不直接执行耗时索引。
- worker 独立消费任务。
- Redis 保存业务任务状态。
- 前端轮询状态。

### 不能夸大

- 当前没有死信队列。
- 当前没有重试退避。
- 当前没有任务幂等去重。
- 当前没有断点续跑。
- 当前没有多 worker 崩溃恢复验证。

### 对向优化

建议优先做：

1. **索引任务幂等（已完成第一版）**
   - `run_document_index_task` 在 task 已 `done` 时直接跳过，避免重复 load/chunk/embedding 成本。
   - chunk 用 `hset` 写固定 key `doc:{document_id}:{chunk_index}`，同一文档重复写是覆盖语义。

2. **失败重试分类（已完成第一版）**
   - `classify_index_error` 写入 `DocumentIndexTaskState.error_type/retryable`。
   - embedding provider 5xx（`EmbeddingProviderError`）→ `provider_transient_error`，retryable=True。
   - 文件格式/内容错误、配置缺失 → retryable=False，不重试。

3. **前端状态增强**
   - pending/running/done/failed。
   - 失败原因。
   - 可重试按钮。

## 8. SSE / WebSocket / 前端实时类问题

真实题包括：

- SSE 和 WebSocket 区别？
- SSE 断线续传？
- WebSocket 心跳、重连、降级轮询？
- 弱网提示怎么做？
- 后端流式推送，前端如何边接收边渲染？

### 本项目可直接支撑

已有：

- 后端 `/chat/stream` SSE。
- 前端已有任务状态轮询。

### 不能夸大

- 当前 React 前端没有接 `/chat/stream`。
- 当前没有 Last-Event-ID 断点续传。
- 当前没有 WebSocket。
- 当前没有心跳/指数退避重连。

### 对向优化

建议：

1. 前端接入 SSE 流式回答。
2. 后端 stream chunk 增加 event id。
3. 前端断线后基于 session_id 重新请求或恢复。
4. 对任务状态轮询加入指数退避和弱网提示。

面试讲法：

> 当前项目用 SSE 更适合 LLM 单向流式输出；WebSocket 更适合双向实时协作、游戏、在线编辑等场景。任务状态这种低频状态更新当前用轮询即可，后续可根据并发和实时性要求切 SSE 或 WebSocket。

## 9. MySQL / 后端架构 / SQL 优化类问题

真实题包括：

- 传统业务系统后端分几层？
- MySQL 大表优化怎么做？
- 慢查询、索引、SQL 优化？
- 数据库事务是什么？
- 结合项目举例必须使用事务的业务场景？
- MySQL 5.6 和 8.0 区别？

### 本项目可直接支撑

当前后端分层：

```text
api
models
services
rag
agent
tools
memory
workers
```

MySQL 能力：

- `job_applications` 投递记录表。
- `application_events` 事件表。
- 只读账号。
- schema introspection。
- SQL 安全校验。
- 强制 LIMIT。
- 确定性 SQL 模板。

### 不能夸大

- 当前没有百万级大表。
- 当前没有真实慢查询调优案例。
- 当前没有分库分表、读写分离。
- 当前数据库问答不是 LLM 自由生成 SQL。

### 对向优化

建议：

1. 给 MySQL 初始化表补索引说明。
2. 增加 `docs/mysql_optimization_notes.md`：
   - 常用索引：`status`、`applied_at`、`channel`、`company`。
   - `EXPLAIN` 如何看。
   - 慢查询如何定位。
   - 大表归档和分页策略。

3. 如果做求职投递辅助 Agent，事务场景可以是：
   - 创建投递记录。
   - 写入投递事件。
   - 更新投递状态。
   - 三者必须在同一事务内保持一致。

## 10. Docker / K8S / 部署类问题

真实题包括：

- Docker 和 K8S 的关系？
- 容器和镜像的关系？
- 怎么挂载 volume？
- K8S 多服务怎么通信？
- 多租户场景 K8S 怎么部署？

### 本项目可直接支撑

已有：

- `docker-compose.yml`
- `Dockerfile.api`
- `frontend/Dockerfile`
- Redis service
- MySQL service
- API service
- worker service
- frontend service

可讲：

```text
Docker 解决单个服务的镜像和容器封装。
Compose 解决本地多服务编排。
K8S 解决生产多实例、服务发现、扩缩容、滚动发布和资源隔离。
```

### 不能夸大

- 当前没有 K8S manifests。
- 当前没有生产多租户部署。
- 当前完整 build/up 受 Docker Hub 网络影响，未稳定完成全镜像烟测。

### 对向优化

建议：

1. 补 `docs/deployment_k8s_notes.md` 方案文档。
2. 不急着写 K8S yaml，先能讲清楚：
   - api deployment。
   - worker deployment。
   - redis/mysql 使用托管服务或 StatefulSet。
   - service discovery。
   - secret/configmap。
   - ingress。

## 11. 前端 / React / Vue / UI 设计类问题

真实题包括：

- Vue 和 React 核心区别。
- Vue2/Vue3 响应式。
- React/Vue 最新版本在做什么。
- 没有设计稿怎么推进页面？
- 前端如何展示任务状态、流式内容？
- CSS 动画、Canvas、WebSocket。

### 本项目可直接支撑

已有：

- React + Vite + TypeScript。
- API 调用集中在 `frontend/src/api.ts`。
- 任务状态轮询。
- sources 和 steps 展示。
- 记忆写入口。

### 不能夸大

- 当前不是 Vue 项目。
- 没有 Canvas 动画。
- 没有 WebSocket 前端实现。
- 没有复杂 UI/UX 多版本方案沉淀。

### 对向优化

建议：

1. 前端接 SSE stream。
2. 增加任务失败重试按钮。
3. 增加“投递辅助 Agent”确认界面。
4. 单独准备 React/Vue 八股，不把 Vue 强行套进本项目。

## 12. 项目管理 / AI 工作流 / 职业表达类问题

真实题包括：

- 从 0 到 1 搭建项目怎么设计架构？
- 接到需求后怎么做？
- 如何推动 AI 系统落地？
- 如何把 AI 融入开发流程？
- AI 写代码不可控，怎么 code review？
- 没有产品经理/设计稿时怎么推进？
- 未来职业规划？

### 本项目可直接支撑

已有工程材料：

- `task_plan.md` 阶段计划。
- `progress.md` 进度日志。
- `findings.md` 技术决策和踩坑。
- `docs/learning_log.md` 分阶段学习问答。
- `docs/code_walkthrough_from_zero.md` 从 0 学习文档。
- `docs/code_module_breakdown.md` 模块拆分文档。
- `docs/demo_checklist.md` 演示清单。
- `docs/resume_pitch.md` 简历话术。

可以讲：

```text
我用文件化计划管理项目，把需求、决策、进度、错误和学习记录都落到文档里。
每做一个阶段先定义验收标准，再写代码和测试，最后同步面试表达和不能夸大的边界。
```

### 对向优化

建议补一份：

```text
docs/ai_development_workflow.md
```

内容：

- 接需求。
- 拆阶段。
- 写验收标准。
- 用 AI 生成初稿。
- 人工 review。
- 测试验证。
- 记录决策和错误。
- 面试复盘。

## 13. 下一步最建议的实际优化顺序

从真实面试命中率看，不建议立刻做炫技功能。建议按下面顺序：

### P0：RAG answer eval 稳定化

目标：

```text
把“检索 hit_rate=1.0”升级成“回答质量、引用一致性、失败样例都有报告”。
```

当前进展：

```text
已增强 answer eval 脚本：
- 支持失败分类 failure_reasons / error_category。
- 支持 retryable 标记。
- 支持重试退避、分批 offset/limit、请求间冷却。
- Markdown 报告输出 recommendations。

已完成：
- 用 deepseek-v4-pro 跑完固定 20 题真实 answer eval：pass_rate / citation_match / answer_keyword_hit 均 1.0、零错误。
- 报告 data/eval/runs/answer_eval_20260618_151548.md 可作为答案规则化质量结论；后续可扩展人工主观质量评分和更大题库。
```

对应面试题：

- AI 回答效果差怎么优化？
- 怎么确认召回数据准确性？
- RAG 整体效果怎么评估？

### P1：工具失败和队列可靠性

目标：

```text
补工具失败分类、RQ retry、任务幂等、失败状态可视化。
```

对应面试题：

- AI 调用工具失败怎么解决？
- 队列任务会不会丢？
- 重试导致重复调用模型怎么处理？

### P1：成本报告

目标：

```text
输出一次 RAG/Agent 调用成本估算报告。
```

对应面试题：

- Token 用量多少？
- 怎么节约 AI 成本？
- AI 投入前后收益如何？

### P2：SSE 前端流式输出

目标：

```text
React 前端接入 /chat/stream 或 Agent stream 设计。
```

对应面试题：

- SSE 和 WebSocket 区别？
- 后端流式推送，前端如何边接收边渲染？
- SSE 断线恢复怎么做？

### P2：MySQL 优化和事务场景

目标：

```text
补索引、EXPLAIN、事务场景和慢查询说明。
```

对应面试题：

- MySQL 慢查询怎么排查？
- 大表优化怎么做？
- 什么业务必须用事务？

### P3：求职投递辅助 Agent

目标：

```text
JD 解析 -> 匹配分析 -> 投递草稿 -> 人工确认 -> MySQL 回写。
```

对应面试题：

- 你这个 AI 系统真实业务价值是什么？
- 如何从工具型 demo 变成业务闭环？
- Agent 如何和数据库/知识库联动？

## 14. 面试时的总讲法

可以这样收束：

> 我这个项目是围绕求职场景做的个人知识库 Agent。非结构化资料走 RAG，结构化投递记录走 MySQL，只读 SQL 工具负责数据库问答，确定性任务走工具函数，长期偏好走 Redis memory。文档支持 `.txt/.md/.docx/.pdf`，PDF 用文本层 / 扫描件 OCR 的 hybrid 路由；检索做了 collection 知识库隔离 + bge-reranker 两阶段精排。Agent 层用 LangGraph StateGraph，并实现了 supervisor 多 agent（简历分析→JD匹配→材料生成）和 interrupt/resume 人工介入断点续跑。质量上做了固定问题集 retrieval eval（hit_rate=1.0）、20 题 answer 规则化评测（pass/citation 均 1.0）、工具失败分类、provider 降级、成本报告和 SSE 流式。整体是一个能讲清边界、有评测数据、覆盖 RAG / 多 agent / HITL 的工程化项目。

## 15. 阶段 24-29 能力升级映射（最新）

本轮升级精准命中真实面试题：

| 真实面试题 | 对应能力 |
|---|---|
| 多智能体 Multi-Agent 是什么/为什么/怎么协作（ML、HQ） | supervisor 多 agent 循环图，按完成步骤路由 |
| 混合检索为何还要精排 Re-rank（HQ）/ 怎么加速 RAG 检索（JR） | 向量召回 + bge-reranker 两阶段精排，hit_rate 0.67→0.80 |
| 任务中途中断如何断点续跑（HQ） | LangGraph interrupt/Command 从中断点恢复 |
| 文档/PDF/课件切分入库人工审核（PY）/ 入库人工审核两道环节（YF） | PDF 文本层 + 扫描 OCR hybrid 路由 + HITL 人工审核 |
| 政策文件场景召回准确性（JR） | 知识库 collection 隔离（防串味）+ rerank + 评测 |

讲法要点：

- rerank：召回 top-N 候选，cross-encoder（bge-reranker）按 query 相关性重排取 top-k；与知识库隔离互补（隔离防“查错库”，rerank 优“同库内排序”）。
- multi-agent：supervisor 编排专家子 agent，路由按“已完成步骤”而非“输出非空”（避免推理模型空 content 导致重复执行）。
- HITL：interrupt 在 JD 匹配后暂停，人工审核补充，Command(resume) 从 checkpoint 继续——真 resume，不是只读快照。
