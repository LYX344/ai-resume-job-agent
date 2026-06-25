# Cursor 项目核心逻辑说明

这份文件是给 Cursor 看的项目导航，也适合你一边读代码一边学习。它不追求覆盖所有细节，而是回答三个问题：

1. 这个项目到底在做什么？
2. 一次用户请求在代码里怎么流动？
3. 你应该按什么顺序读代码，才能把项目讲清楚？

## 1. 一句话定位

这是一个面向求职和个人知识管理场景的 Python Agent / RAG 项目。

核心能力不是“套一个大模型聊天壳”，而是把几类常见后端能力整合成一个可演示的 Agent：

```text
FastAPI 接口
+ Redis 会话 / 记忆 / 向量索引
+ RAG 文档问答
+ MySQL 简历投递记录问答
+ LangGraph Agent 编排
+ 工具调用
+ 异步文档入库
+ React 前端演示
+ 评测与面试说明文档
```

面试时可以把它讲成：

```text
我做的是一个求职知识助理。
它可以管理个人文档、检索知识库、回答简历和面试资料问题，
也可以查询结构化的投递记录，并通过 Agent 工具调用把不同能力组合起来。
```

## 2. 最重要的分层

先记住这个分层，后面读代码会轻松很多：

```text
app/main.py       组装 FastAPI 应用
app/api/          HTTP 接口层，只负责接请求、返回响应
app/models/       Pydantic 数据结构，定义输入输出长什么样
app/services/     外部系统适配层，例如 Redis、MySQL、LLM、Embedding、RQ
app/rag/          文档加载、切片、向量入库、检索、RAG 生成
app/tools/        Agent 可调用的确定性工具
app/agent/        LangGraph 工作流，决定什么时候调用工具和 RAG
app/memory/       短期会话记忆和长期用户画像记忆
app/workers/      后台异步任务 worker
app/evaluation/   检索评测和答案评测
frontend/         React 演示控制台
scripts/          本地测试、评测、演示包脚本
docs/             学习、架构、面试和演示文档
```

这个项目的一个重要设计原则是：接口层不要堆业务逻辑。

例如文档上传接口只负责接收文件，真正的加载、切片、向量化、写 Redis 都放在 `app/rag/` 和 `app/services/` 里。这样面试时可以讲“分层清晰、职责隔离、方便测试和替换实现”。

## 3. 一次文档上传怎么跑

入口：

```text
app/api/routes/documents.py
```

同步上传流程：

```text
POST /api/v1/documents/upload
-> 读取上传文件
-> app/rag/document_loader.py 解析 txt/md/docx
-> app/rag/chunker.py 切成 chunk
-> app/rag/indexer.py 调 embedding
-> app/services/embedding_client.py 生成向量
-> app/services/redis_client.py 存 chunk 和向量
```

为什么要切片：

```text
完整文档太长，直接塞给大模型会稀释注意力。
切片后可以先检索相关片段，再把少量高相关内容拼进 prompt。
```

为什么 Redis 里要保存原文和向量：

```text
向量负责语义检索。
原文负责最终拼 prompt 和展示引用来源。
```

你读代码时建议按这个顺序：

1. `app/api/routes/documents.py`
2. `app/rag/document_loader.py`
3. `app/rag/chunker.py`
4. `app/rag/indexer.py`
5. `app/services/embedding_client.py`
6. `app/services/redis_client.py`

对应测试主要看：

```text
tests/test_documents_api.py
tests/test_document_processing.py
tests/test_redis_vector_index.py
```

## 4. 一次 RAG 问答怎么跑

入口：

```text
app/api/routes/rag.py
```

核心流程：

```text
POST /api/v1/rag/query
-> app/rag/answerer.py
-> app/rag/retriever.py
-> app/services/embedding_client.py 把问题向量化
-> app/services/redis_client.py 做向量检索
-> 把检索到的 chunks 转成 sources
-> 拼接 RAG prompt
-> app/services/llm_client.py 调本地 OpenAI-compatible LLM
-> 返回 answer + sources
```

这里要注意一个边界：

```text
如果没有检索到 sources，项目不会强行调用 LLM 编答案。
```

这是为了防止“没有资料还装作有资料”的幻觉问题。面试里可以说：RAG 不是只要接上向量库就完事，还要考虑无上下文、引用一致性、失败兜底。

你读代码时建议按这个顺序：

1. `app/api/routes/rag.py`
2. `app/rag/answerer.py`
3. `app/rag/retriever.py`
4. `app/services/redis_client.py`
5. `app/services/llm_client.py`

对应测试主要看：

```text
tests/test_rag_api.py
tests/test_rag_answerer.py
tests/test_rag_retriever.py
tests/test_evaluation_retrieval.py
tests/test_evaluation_answer.py
```

## 5. 一次 Agent 对话怎么跑

入口：

```text
app/api/routes/agent.py
```

核心流程：

```text
POST /api/v1/agent/run
-> app/agent/workflow.py
-> 加载短期会话和长期记忆
-> 判断用户意图
-> 决定是否检索文档
-> 决定是否调用工具
-> 必要时执行 bounded tool-call loop
-> 生成最终回答
-> 保存 trace 和 checkpoint metadata
```

Agent 的关键不是“所有事情都让 LLM 自由发挥”，而是把任务拆成可控节点：

```text
理解意图
-> 需要工具就调用工具
-> 需要知识就检索知识库
-> 需要数据库就走安全 SQL 查询
-> 最后统一生成自然语言回答
```

当前项目使用 LangGraph 的核心价值：

```text
用 StateGraph 把 Agent workflow 显式编排出来。
代码能看清楚每个节点输入什么、输出什么、下一步走哪里。
```

当前没有过度使用 LangGraph 的高级能力，所以不要在面试里夸大成“完整生产级多 Agent 系统”。更准确的说法是：

```text
我用 LangGraph 重构了原本手写的 Agent 流程，
让状态、节点和边更清晰，也为后续 checkpoint、人审和复杂工具链留接口。
```

你读代码时建议按这个顺序：

1. `app/api/routes/agent.py`
2. `app/agent/state.py`
3. `app/agent/workflow.py`
4. `app/tools/registry.py`
5. `app/tools/llm_executor.py`
6. `app/agent/checkpoint.py`

对应测试主要看：

```text
tests/test_agent_api.py
tests/test_agent_workflow_graph.py
tests/test_agent_tool_loop.py
tests/test_tool_node.py
tests/test_agent_checkpoint.py
```

## 6. 工具调用怎么理解

工具目录：

```text
app/tools/
```

当前工具包括：

```text
search_docs            查知识库
calculator             计算
create_todo            创建待办
summarize_file         总结文件
draft_weekly_report    生成周报草稿
query_database         查询 MySQL 投递记录
```

工具调用要区分两个概念：

```text
tools:
告诉模型有哪些工具、参数是什么、能做什么。

tool_calls:
模型实际返回的“我要调用哪个工具、参数是什么”。
```

项目里的安全策略：

```text
只有白名单工具可以执行。
工具调用轮数有限制，防止死循环。
记忆写入不是完全开放给 LLM 自动乱写。
SQL 查询不是让 LLM 直接生成任意 SQL。
```

这部分面试很常考，因为很多人只会说“我接了 function calling”，但讲不清楚工具 schema、执行器、结果回传和循环上限。

## 7. MySQL 数据库问答怎么跑

核心文件：

```text
app/services/mysql_client.py
app/tools/query_database.py
```

当前项目的数据库问答不是自由 Text-to-SQL，而是确定性模板：

```text
用户问投递记录
-> query_database 工具判断查询意图
-> 使用预设 SQL 模板
-> prepare_safe_select() 做只读安全检查
-> MySQL read-only 账号执行查询
-> 格式化成 Markdown 结果
```

为什么不直接让 LLM 写 SQL：

```text
LLM 可能生成危险 SQL、错误 SQL，或者查不该查的数据。
当前项目是个人作品集，先用确定性 SQL 模板更稳。
```

可以在面试里这样讲：

```text
结构化数据适合 SQL 精确查询，非结构化文档适合 RAG 语义检索。
所以我没有把投递记录也塞进向量库，而是让 Agent 根据问题选择 query_database 工具。
```

## 8. Redis 在项目里做了什么

核心文件：

```text
app/services/redis_client.py
```

Redis 当前承担多种角色：

```text
session:*              短期会话历史，有 TTL
memory:*               长期记忆画像
doc:*                  文档 chunk 和向量
index_task:*           异步入库任务状态
RediSearch vector index 向量检索索引
```

注意：

```text
Redis vector distance 是距离，不是分数。
通常越小代表语义越接近。
```

为什么 embedding 维度必须配置：

```text
Redis 向量索引创建时需要知道维度。
不同 embedding 模型维度可能不同，混用会导致检索错误或写入失败。
```

所以切换 embedding 模型后要清理旧 chunk 并重新入库。

## 9. 记忆系统怎么理解

核心文件：

```text
app/memory/session.py
app/memory/profile.py
```

两类记忆：

```text
短期记忆:
当前会话的上下文，适合设置 TTL，避免 Redis 数据长期堆积。

长期记忆:
用户画像和稳定偏好，例如求职方向、技能栈、长期目标。
一般不设置短 TTL，但要可见、可控、可删除。
```

为什么不能让 LLM 随便写长期记忆：

```text
长期记忆会影响后续所有对话。
如果 LLM 幻觉写入错误偏好，后续回答都会被污染。
```

## 10. 异步入库怎么理解

核心文件：

```text
app/services/document_index_queue.py
app/workers/document_indexing.py
app/workers/rq_worker.py
```

同步上传适合小文件和开发测试。

异步上传适合更真实的业务流程：

```text
接口先返回 task_id
-> Redis 记录 pending
-> RQ worker 后台处理文档
-> 前端轮询 task status
-> 最终看到 done 或 failed
```

当前边界：

```text
RQ worker 已经能跑通异步入库，
但还不是生产级队列系统。
暂时没有完整 retry backoff、dead-letter queue、任务幂等和 dashboard。
```

面试时不要把它夸大成完整生产队列。可以说：

```text
我已经把同步上传演进成异步任务模型，后续可以继续补重试、死信队列和幂等。
```

## 11. 前端怎么理解

前端目录：

```text
frontend/
```

它是 React + Vite + TypeScript 的演示控制台，不是这个项目的核心算法部分。

前端主要价值：

```text
让面试官不用看命令行，也能看到上传文档、查询 RAG、运行 Agent、查看状态的效果。
```

前后端关系：

```text
frontend/src/api.ts
集中封装后端接口调用。

React 页面组件
只负责展示、输入、状态切换。
```

## 12. 评测系统怎么理解

核心文件：

```text
app/evaluation/retrieval.py
app/evaluation/answer.py
scripts/evaluate_retrieval.py
scripts/evaluate_rag_answers.py
```

检索评测回答的问题：

```text
问题来了以后，能不能从知识库里找回正确文档 chunk？
```

答案评测回答的问题：

```text
检索结果交给 LLM 后，最终回答是否覆盖关键点？
```

当前真实评测状态：

```text
真实 Qwen3-Embedding-4B retrieval eval 已完成，20 题 hit_rate=1.0。
真实 RAG answer eval 已完成完整 20 题（LLM 用 deepseek-v4-pro）：pass_rate / citation_match / answer_keyword_hit 均 1.0、零错误。
注意：answer eval 是规则化评分（关键词命中 + 引用一致性 + 非拒答），不是人工主观质量评分。
```

面试表达要准确：

```text
我完成了检索链路的真实 embedding 评测（hit_rate=1.0），
也完成了固定 20 题真实 RAG answer 规则化评测（pass_rate / citation 均 1.0）；
评测脚本具备失败分类、重试退避和分批能力，后续可扩展人工主观质量评分。
```

## 13. 从 0 阅读代码路线

如果你今天刚打开项目，建议按这个顺序读：

1. `README.md`
2. `docs/architecture.md`
3. `docs/code_walkthrough_from_zero.md`
4. `docs/code_module_breakdown.md`
5. `app/main.py`
6. `app/core/config.py`
7. `app/api/routes/health.py`
8. `app/api/routes/documents.py`
9. `app/rag/document_loader.py`
10. `app/rag/chunker.py`
11. `app/rag/indexer.py`
12. `app/rag/retriever.py`
13. `app/rag/answerer.py`
14. `app/agent/workflow.py`
15. `app/tools/registry.py`
16. `app/tools/query_database.py`
17. `app/services/redis_client.py`
18. `app/services/mysql_client.py`
19. `scripts/evaluate_retrieval.py`
20. `scripts/evaluate_rag_answers.py`

读每个文件时问三件事：

```text
它的输入是什么？
它的输出是什么？
为什么这段逻辑应该放在这个模块，而不是别的模块？
```

## 14. Cursor 回答这个项目时应该遵守的边界

不要声称已经实现：

```text
生产级 RQ 重试 / 死信队列
官方 Redis/Postgres LangGraph checkpointer
真实自动投简历
自由 Text-to-SQL
人工主观质量评分的 answer eval（当前已完成的是规则化评分）
Kubernetes 生产部署
Elasticsearch 混合检索
```

可以准确声称：

```text
FastAPI + Redis + MySQL + LangGraph + RAG 基础链路已跑通。
PDF 文本层解析已实现；扫描件可走 OCR，OCR 依赖为可选重依赖，不可用时优雅降级。
知识库 collection 隔离已实现，能避免简历库和项目库混存串味。
两阶段 rerank 已实现：向量召回 top-N 后用可插拔 reranker 精排 top-k，默认可 identity 降级。
真实 embedding 检索评测已完成（hit_rate=1.0）。
固定 20 题真实 RAG answer 规则化评测已完成（pass_rate / citation 均 1.0）。
Agent 工具调用（含失败五分类与 provider 降级）、记忆、异步入库（含任务幂等与失败分类）、前端演示、评测脚本都有基础实现。
MySQL 问答采用确定性 SQL 模板和只读安全层。
MCP client 已接入普通 Agent tool loop，并有 capabilities API 和前端 MCP 面板；边界是默认关闭、只连可信 server、未做持久连接池。
job-application workflow 已有特定 HITL review/resume；普通 `/agent/run` 仍没有通用生产级 resume API。
```

## 15. 后续优化优先级

如果继续按真实面试题对向优化，优先做这些：

1. RQ 任务可靠性：重试、失败分类、幂等、死信队列说明。
2. SSE 流式输出：前端能看到 Agent 逐步输出。
3. 成本统计：统计 embedding token、LLM token、单次问答估算成本。
4. MySQL 面试强化：索引、事务、慢查询、连接池、只读账号说明。
5. Answer eval 深化：已完成 20 题规则化评测（pass/citation 均 1.0），后续扩展人工主观质量评分和更大题库。
6. 人审投递助手设计：只做草稿和确认，不做自动乱投。

## 16. 一段可以背的项目讲解

```text
这个项目是一个求职场景下的个人 Agent / RAG 助理。
后端用 FastAPI 分层实现接口、服务适配、RAG 管线和 LangGraph Agent workflow。
非结构化资料通过 loader、chunker、embedding、Redis vector index 做语义检索；
结构化投递记录走 MySQL 的确定性 SQL 模板和只读安全层。
Agent 层把文档检索、数据库查询、计算、待办、文件总结等能力封装成工具，
再通过有限轮数的工具调用流程把工具结果合成最终回答。
项目还包含 Redis 会话记忆、长期画像记忆、RQ 异步文档入库、React 演示前端和评测脚本。
我重点考虑了 key 安全、工具调用边界、SQL 安全、embedding 模型切换后的索引清理、检索评测和面试可解释性。
```
