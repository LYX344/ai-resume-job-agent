# 面试讲解稿：AI Resume Job Agent / AI 简历求职助手

本文档用于把项目讲成一个可投简历、可面试展开的工程项目。原则是只讲已经完成并能演示的能力，不把后续计划伪装成已实现。

相关材料：

- `docs/resume_pitch.md`：投递简历时使用的压缩版项目话术。
- `docs/demo_checklist.md`：截图、录屏和现场演示清单。
- `docs/demo.md`：本地 demo smoke 脚本说明。
- `data/demo/packages/`：自动生成的演示包，汇总最新 smoke/eval 报告、截图清单、录屏流程和边界说明。

## 30 秒项目介绍

> 我做了一个个人知识库 Agent/RAG 助手，后端使用 Python FastAPI，Redis 同时承担会话、长期记忆、异步任务状态和向量检索，MySQL 保存简历投递结构化记录，前端使用 React + Vite + TypeScript。项目支持 `.txt` / `.md` / `.docx` 文档上传、切片、embedding、Redis 向量入库、RAG 检索问答、Agent 工具调用、数据库问答、短期/长期记忆、异步索引任务和检索评测报告。

## 2 分钟展开讲法

> 这个项目的目标不是单纯做聊天机器人，而是做一个有工程边界的个人知识库 Agent。  
> 后端我用 FastAPI 拆分 API、Service、RAG、Agent、Tools、Memory 和 Worker 模块。文档入库时，上传文件会先解析成 Document，再切成 DocumentChunk，生成 embedding 后写入 Redis HASH，并通过 RediSearch 向量索引支持 top_k 检索。  
> 查询时，系统会把用户问题向量化，从 Redis 召回相关 chunk，再构造 RAG prompt 调用 OpenAI-compatible LLM，回答会带 sources。Agent 入口使用 LangGraph StateGraph 编排多个节点，包含意图识别、是否检索判断、条件边路由、工具调用、回答生成和记忆保存，比如 calculator、create_todo、summarize_file、draft_weekly_report 和 search_docs。确定性工具不依赖 LLM，所以没有 API Key 时也能演示。  
> 我还做了 session 短期记忆、memory profile 长期记忆、MySQL 简历投递数据库问答、异步文档索引任务、React 控制台、结构化请求日志和固定问题集检索评测。仓库默认仍保留 fake embedding 作为无 Key 开发模式；当前本地已经切到硅基流动 Qwen3-Embedding-4B，按 1536 维重建 Redis 索引并完成 retrieval eval，最新 hit_rate 是 1.0。本地 LLM 反代（deepseek-v4-pro）已接入，并完成固定 20 题真实 RAG answer 规则化评测：pass_rate 与 citation_match 均为 1.0、零错误。

## 简历写法

项目名：

```text
个人知识库 Agent/RAG 助手 | Python, FastAPI, Redis, React, TypeScript
```

项目描述：

```text
构建个人知识库 Agent/RAG 系统，支持文档上传、切片、Redis 向量检索、RAG 问答、Agent 工具调用、短期/长期记忆、异步索引任务和前端演示控制台。
```

可写进简历的要点：

- 使用 FastAPI 搭建后端 API，按 API、Service、RAG、Agent、Tools、Memory、Worker 分层组织代码，并补充单元测试和接口测试。
- 基于 Redis 实现 session 短期记忆、长期 memory profile、异步任务状态和文档向量检索，使用 key 前缀和 TTL 管理不同生命周期数据。
- 实现文档入库链路：`.txt/.md/.docx` 解析、chunk 切片、overlap、embedding、Redis HASH 写入和 RediSearch KNN 检索，其中 DOCX 支持段落和表格文本提取。
- 基于 LangGraph StateGraph 实现 Agent workflow，使用条件边在 `call_tools` 和 `skip_tools` 间路由；普通聊天分支支持最多 3 轮 bounded LLM tool calls，经 LangGraph `ToolNode` 子图执行 calculator、create_todo、summarize_file、draft_weekly_report 等安全工具，并把执行过程和本地文件 checkpoint metadata 写入响应。
- 实现异步文档索引接口，上传后返回 task_id，前端轮询 pending/running/done/failed 状态，失败时返回错误原因。
- 使用 React + Vite + TypeScript 构建前端控制台，支持后端健康检查、文档上传、任务轮询、知识库检索、Agent 调用、sources/steps 展示和记忆写入。
- 增加固定问题集 retrieval 评测脚本，输出 JSON/Markdown 报告，记录 hit_rate、latency、retrieved chunks 和粗略 token 估算。

注意事项：

- 如果简历篇幅有限，不要一次写满所有点。优先写 Redis、RAG、Agent 工具调用、异步任务和评测。
- 可以写“已完成真实 embedding 端到端检索评测”，也可以写“已完成固定 20 题真实 RAG answer 规则化评测（pass_rate / citation_match 均 1.0）”，但要说明这是规则化评分（关键词命中 + 引用一致性 + 非拒答），不是人工主观质量评分；LangGraph 可以写 StateGraph 编排、基础条件边、bounded ToolNode 子图执行和 local-file checkpoint 持久化，但不要写生产级官方 Redis/Postgres checkpoint、跨请求恢复、人工中断恢复或无限循环式 ReAct。

## 技术亮点

### 1. Redis 不只是缓存

讲法：

> 这个项目里 Redis 同时承担四类职责：短期 session、长期 memory profile、异步任务状态和文档向量检索。短生命周期数据设置 TTL，文档 chunk 和长期 profile 作为可复用状态保存。这样一个中间件覆盖了缓存、状态管理和 RAG 检索多个就业高频点。

可展开细节：

- `session:{session_id}`：短期会话。
- `memory:profile:default`：长期偏好和项目背景。
- `task:index:{task_id}`：异步索引任务状态。
- `doc:{document_id}:{chunk_index}`：文档 chunk 和 embedding。

### 2. RAG 链路完整

讲法：

> 我把 RAG 拆成入库和查询两条链路。入库是解析、切片、embedding、写 Redis；查询是 query embedding、Redis KNN 检索、sources 转换、prompt 构造和 LLM 回答。这样每个环节都可以单独测试和替换。

可展开细节：

- chunk 保留来源、序号和字符范围。
- sources 和 answer 分开返回，方便前端展示引用和排查。
- 无上下文时直接拒答，不调用 LLM。

### 3. Agent 有可观察 steps

讲法：

> Agent 响应不只返回最终答案，还返回 steps，展示 load_memory、understand_intent、decide_retrieval、call_tools、generate_answer、save_trace 每个节点的状态。这样前端能看到工具是否被调用，调试时也能定位是哪一步出问题。

可展开细节：

- calculator/todo/weekly report 等确定性工具不调用 LLM。
- search_docs 复用 RAG 检索能力。
- memory_update 必须有 `session_id`，避免假装保存。

### 4. 异步任务可演示

讲法：

> 文档索引可能耗时较长，所以我把异步上传做成了 RQ 队列模式。API 收到文件后创建 task_id，把任务入 Redis 队列并立即返回 202；独立 RQ worker 消费任务，执行解析、切片、embedding 和 Redis chunk 写入，再把状态更新为 done 或 failed。前端仍然只轮询 task 状态，所以接口边界保持稳定。

可展开细节：

- `pending -> running -> done/failed`。
- 失败状态保存 `error_message`。
- 任务状态存 Redis，而不是 Python 内存。

### 5. 有评测，不只靠感觉

讲法：

> 我准备了固定问题集和评测脚本，每次调整 chunk、embedding 或 top_k 后，都能跑同一批问题，比较 hit_rate、latency 和召回内容。检索层 retrieval eval hit_rate=1.0；答案层也完成了固定 20 题真实 RAG answer 规则化评测（pass_rate 与 citation_match 均 1.0），覆盖关键词命中和引用一致性。

## 常见面试问答

### Q1：MySQL 数据库问答是怎么接入的？为什么不直接让 LLM 裸连数据库？

答：

> 我把 MySQL 作为结构化数据库问答能力接入，第一版围绕简历投递记录建模，包括 `job_applications` 和 `application_events`。Agent 识别到“投了哪些公司什么岗位、当前状态、渠道统计”等问题时，会走 `query_database` 工具，而不是文档 RAG。数据库工具当前使用确定性 SQL 模板，并且执行前做只读 SELECT、多语句、DDL/DML、LIMIT 和允许表校验，数据库账号本身也是只读账号。这样可以展示 Text-to-SQL 思路，但不会让 LLM 裸连数据库。

### Q2：fake embedding 有什么问题？为什么还要做？

答：

> fake embedding 不能代表真实语义效果，它只保证同一段文本生成稳定向量，用来验证 DocumentChunk 到 Redis HASH、向量索引、检索接口和评测脚本这些工程链路。项目已经有 OpenAI-compatible embedding client，当前本地用硅基流动 Qwen3-Embedding-4B 重建过 Redis 索引并完成 retrieval eval；后续如果更换模型，必须重新确认输出维度、清理旧 chunk、重新上传文档并重新评测。

### Q3：为什么要切 chunk，而不是整篇文档塞给模型？

答：

> 长文档会增加 token 成本和延迟，也会引入大量无关上下文，稀释模型注意力。RAG 先把文档切成 chunk，再按问题召回最相关的几个片段，让模型基于更短、更聚焦的上下文回答。

### Q4：chunk overlap 解决什么问题？

答：

> overlap 用来降低关键信息被切片边界截断的风险。如果一句话或一个概念刚好跨两个 chunk，没有 overlap 时单独召回其中一个片段可能上下文不完整。

### Q5：Redis 向量检索和普通 GET 有什么区别？

答：

> 普通 GET 是基于完整 key 的精确查询，比如 `GET session:abc123`。向量检索是把问题和文档 chunk 都变成向量，然后按相似度找 top_k，不需要提前知道具体 key，适合 RAG 的语义召回场景。

> Redis vector search 返回的 `distance` 是向量距离，不是越大越好的相关性分数。当前项目使用 COSINE 距离时，distance 越小表示 query 和 chunk 的向量越相近，语义相关性通常越高。

### Q6：为什么 RAG 回答要返回 sources？

答：

> sources 让回答可追溯。即使模型生成的引用格式不稳定，前端和调试仍然能看到系统实际召回了哪些 chunk、来自哪个文件、距离是多少。这能降低黑盒感，也方便排查回答错误到底是检索问题还是生成问题。

### Q7：为什么无检索结果时不调用 LLM？

答：

> 如果没有上下文，调用 LLM 很容易产生编造，也会浪费 token。当前设计是无 sources 时直接返回固定拒答，符合 RAG 只基于知识库回答的边界。

### Q8：为什么确定性工具不调用 LLM？

答：

> 计算器、待办生成、周报模板和显式记忆保存都可以用规则稳定完成。让 LLM 做这些反而会增加成本、延迟和不确定性。Agent 里应该把确定性任务交给工具，把需要语言理解和生成的部分再交给 LLM。

### Q9：为什么任务状态要放 Redis？

答：

> 后台任务和查询接口不是同一个 HTTP 请求。任务状态如果只放 Python 内存，服务重启会丢失，多进程部署也不共享。Redis 是独立中间件，API、后台任务和前端查询都能通过同一个 `task:index:{task_id}` 读写状态。

### Q10：BackgroundTasks、RQ 和 Celery 怎么取舍？

答：

> BackgroundTasks 适合早期本地演示，依赖少、实现快，可以先验证 task_id、状态轮询和失败记录。现在项目已经升级到 RQ，因为已有 Redis，RQ 配置少，能用独立 worker 把耗时索引从 API 进程里拆出去。Celery 更重，适合复杂生产任务，比如多 broker、复杂重试、定时调度和更完整的监控。当前阶段我会说是 RQ worker 第一版，还没有重试退避、死信队列或 Dashboard。

### Q：异步索引任务怎么保证不重复、失败怎么分类？

答：

> 两点。第一是幂等：`run_document_index_task` 发现任务已经是 `done` 就直接跳过，避免 RQ 重试或 worker 重启时重复 load、切片和 embedding，省掉重复的模型调用成本；chunk 用 Redis hset 写在 `doc:{document_id}:{chunk_index}` 这个固定 key 上，同一文档重复写是覆盖而不是累积。
> 第二是失败分类：我用 `classify_index_error` 把失败分成可重试和不可重试两类，写进任务状态的 `error_type` 和 `retryable` 字段。embedding provider 的 5xx/网络错误是 transient，标记可重试；文件格式不支持、内容为空、API Key 没配这些是 permanent，重试也没用，直接失败。这样上层重试策略才有依据，不会对永久性错误做无意义重试。
> 当前边界：已经有幂等和错误分类，但还没有接 RQ 原生的自动重试退避和死信队列，这是下一步。

### Q11：为什么日志不记录请求体？

答：

> Agent/RAG 请求体可能包含用户问题、文档内容、长期记忆甚至误填的敏感配置。完整记录请求体会有隐私泄露和日志膨胀风险。当前只记录 request_id、method、path、status_code、duration_ms 和 client_host，足够排查慢请求和错误请求。

### Q12：为什么前端需要 CORS？

答：

> React 开发服务在 `127.0.0.1:5173`，FastAPI 在 `127.0.0.1:8025`，端口不同就是不同 origin。浏览器会执行 CORS 安全策略，所以后端必须允许本地前端 origin。PowerShell 和 curl 不是浏览器，不执行 CORS 检查。

### Q13：Agent workflow 现在是不是 LangGraph？

答：

> 现在已经接入 LangGraph StateGraph。`/api/v1/agent/run` 会创建 AgentState，并经过 `load_memory -> understand_intent -> decide_retrieval`，再由条件边判断走 `call_tools` 还是 `skip_tools`，最后进入 `generate_answer -> save_trace`。规则识别出的工具仍由项目自己的 `call_tools` 节点执行；普通聊天分支如果 LLM 返回 tool_calls，会通过 LangGraph `ToolNode` 子图执行最多 3 轮安全工具调用，把每轮工具结果作为 tool message 回传给模型；如果达到上限，会再做一次不带 tools 的最终回答。当前默认接入 `local_file` checkpoint，并在响应里返回 `thread_id`、`checkpoint_id`、`backend=local_file`、`durable=true` 和 `production_ready=false`，也可以通过 `/api/v1/agent/checkpoints/{thread_id}` 查询 latest checkpoint snapshot metadata，通过 `/api/v1/agent/checkpoints/{thread_id}/history` 查询最近若干条 checkpoint metadata。

补充：

> 模型适配层现在已经支持 OpenAI-compatible tool calling：请求可以携带 `tools` 和 `tool_choice`，响应可以解析 `tool_calls`，二次请求也可以携带 assistant `tool_calls` 和 `tool` message。

> 工具层也已经新增 schema 注册表，可以把 search_docs、query_database、calculator、create_todo、summarize_file、draft_weekly_report 导出成 function tool schema。当前 LLM 自动执行范围先限定为 calculator、create_todo、summarize_file、draft_weekly_report，不把长期记忆写入和数据库查询交给模型自动调用；search_docs 和 query_database 仍主要走 Agent 规则路由。

> 当前普通聊天分支会把安全工具 schema 发给 LLM，并把模型返回的 tool_calls、ToolNode 执行结果、工具轮数和是否触顶记录到 steps 里。它已经不是 dry-run，也不是只执行一轮；但它是有最大轮数的 bounded loop，不是无限循环式 ReAct。

> checkpoint 这里我会说清楚边界：当前 `local_file` backend 是单机本地 demo 级持久化，能把 checkpoint 写到 `data/checkpoints/agent_checkpoints.pkl` 并在本地进程重启后重新加载；现在还补了 checkpoint latest/history 查询接口，只返回元数据和 state channel keys，不暴露完整图状态。但它不是官方 Redis/Postgres checkpointer，不适合多 worker 生产部署，也没有实现真正从中断点继续执行的 resume API 或人工审批恢复。

### Q：Agent 调用工具失败了怎么处理？

答：

> 我把工具调用失败分成五类并结构化记录，而不是抛一个笼统错误：
> 一是参数错误（`invalid_arguments`），模型给的工具参数不是合法 JSON；
> 二是未知工具（`unknown_tool`），模型点名了不在白名单里的工具，我在执行前就拦截；
> 三是工具内部异常（`tool_execution_error`），由 LangGraph ToolNode 的 `handle_tool_errors` 捕获；
> 四是工具轮数触顶，普通聊天分支最多 3 轮 bounded tool calls，触顶后强制不带 tools 收束；
> 五是上游模型错误，这里再分层：provider 5xx/网络抖动属于瞬态故障，降级返回友好回答；没配置 API Key 这类部署问题直接返回 503。
> 前三类失败会作为 tool message 回传给模型让它自我纠正；所有失败分类都会汇总到 Agent 响应的 steps 里，便于调试和现场演示。

### Q14：为什么要做固定问题集评测？

答：

> 固定问题集可以控制变量。每次调整 chunk_size、embedding、top_k 或文档内容后，都跑同一批问题，比较 hit_rate、latency 和 retrieved chunks，避免靠临时手动问几个问题凭感觉判断效果。

### Q15：这个项目最大不足是什么？

答：

> 检索和答案评测都已经做了（retrieval hit_rate=1.0；固定 20 题 RAG answer 规则化评测 pass_rate / citation_match 均 1.0），不过当前 answer 评测是规则化评分（关键词命中 + 引用一致性 + 非拒答），还没有引入人工主观质量打分和更大规模题库，这是可以继续深化的点。异步索引已经从 BackgroundTasks 升级为 RQ worker，并补了任务幂等和失败的可重试/不可重试分类，但还没有接 RQ 原生的自动重试退避、死信队列或 Dashboard。LangGraph 已有 StateGraph、基础条件边、bounded ToolNode 子图执行、local-file checkpoint 持久化和 checkpoint latest/history 查询接口，但还没有官方 Redis/Postgres checkpointer、真正从中断点继续执行的 resume API 和人工中断恢复能力。MySQL 数据库问答目前是确定性 SQL 模板，还不是 LLM 自由生成 SQL。我的升级计划是把 answer 评测扩展到人工质量评分 + 更大题库，并继续补生产级 checkpoint/resume 和队列生产化能力。

## 演示顺序

推荐面试或作品集演示时按这个顺序：

1. 打开 React 控制台，先点后端 health check。
2. 上传一份 `.md`、`.txt` 或 `.docx` 文档，展示异步任务状态从 pending 到 done。
3. 在知识库检索里问一个和文档相关的问题，展示 top_k chunks、distance 和 source。
4. 用 Agent 跑一个计算问题，证明确定性工具不依赖 LLM。
5. 用 Agent 跑一个待办或周报请求，展示工具调用 steps。
6. 用“请记住：我喜欢先给结论”展示长期记忆写入。
7. 打开评测报告，展示固定问题集、hit_rate 和 latency。
8. 录屏前打开最新 `data/demo/packages/*.md`，确认截图、报告和边界说明都准备好。

完整截图和 90 秒录屏脚本见 `docs/demo_checklist.md`。

## 当前不要这样讲

- 可以说“已完成固定 20 题真实 RAG answer 规则化评测（pass_rate / citation_match 均 1.0）”，但不要夸大成“人工主观质量评测满分”——它是规则化评分（关键词命中 + 引用一致性 + 非拒答）。
- 不要说“已经完整使用 LangGraph 高级能力”，当前是 StateGraph + 基础条件边 + 最多 3 轮 bounded ToolNode 子图执行 + local-file checkpoint 持久化 + checkpoint latest/history 查询；求职投递 workflow 有特定 HITL interrupt/resume，但普通 `/agent/run` 还没有通用生产级 resume API，也没有官方 Redis/Postgres checkpointer。
- 不要把 PDF/OCR 说成无依赖全能解析。当前支持 `.txt` / `.md` / `.docx` / `.pdf`，PDF 文本层解析可用；扫描件 OCR 依赖 PaddleOCR 或视觉 LLM API，不可用时会优雅降级。
- 不要说“生产级异步任务队列”，当前是 RQ worker 第一版，还没有重试退避、死信队列、Dashboard 或调度能力。
- 不要说“多用户权限系统”，当前是个人单用户项目。

## 后续升级路线

优先级建议：

1. 已完成固定 20 题 RAG answer 规则化评测和引用一致性检查；下一步扩展人工主观质量评分和更大题库。
2. 为 RQ worker 增加重试退避、失败队列、Dashboard 或按需要迁移 Celery。
3. 升级普通 Agent 的官方 Redis/Postgres checkpointer、通用 resume API 和更完整的 ReAct 控制策略。
4. 把求职投递 workflow 继续做成可审计业务闭环：材料草稿、人工确认、投递记录状态回写；不做无确认自动提交。
5. 继续完善 PDF/OCR：版面结构化、表格抽取、OCR 质量评测和失败页人工复核。

### Q16：这个项目能不能说成综合型 Agent？

答：

> 可以，但要讲清楚综合能力来自路由编排，不是堆工具。当前项目已经有文档 RAG、MySQL 投递记录数据库问答、确定性工具、记忆系统、LangGraph workflow 和前端演示。可以定位为面向求职场景的综合型 Agent：文档问题走 RAG，投递统计问题走 MySQL QA，计算/总结/周报等任务走工具，用户偏好走记忆系统。

### Q17：后续能不能让 Agent 自动投简历？

答：

> 可以做投递辅助，但不能做无确认自动海投。第一版已经实现：`/agent/job-application` 用 supervisor 多 agent 编排简历分析 → JD 匹配 → 投递材料生成；`/agent/job-application/review` 用 LangGraph interrupt 在 JD 匹配后中断，把匹配分析交人工审核补充，`/resume` 从 checkpoint 恢复再生成材料——人在回路。简历走独立 collection 知识库 + rerank 精排保证检索准确。真实提交前必须用户确认；系统不保存平台密码，不绕过验证码，不做批量骚扰投递。这个边界能展示 Agent 自动化能力，也能避免账号、隐私和职业信誉风险。

### Q18：MCP 是什么？和 Function Calling、Skills 有什么区别？

- Function Calling 是模型“决定调哪个工具、传什么参数”的能力，只产出调用意图，执行由应用负责。
- MCP（Model Context Protocol）是“工具/数据源怎么被标准暴露和调用”的协议（client/server，stdio 或 streamable HTTP，`initialize`→`list_tools`→`call_tool`），相当于工具的 USB-C 接口，一份 server 可跨应用复用。
- Skills 是把领域知识/操作流程打包成可复用能力，偏知识与流程封装，不是传输协议。
- 本项目用官方 `mcp` SDK 自研 MCP client：发现外部 server 工具（`inputSchema`）→ 转 OpenAI function schema → 模型 Function Calling → 经 MCP `call_tool` 执行。默认关闭、单 server 失败降级、in-memory 可测、真实 stdio smoke。

## 阶段 24-34 新增能力速答

- **PDF / 扫描件**：文档支持 `.txt/.md/.docx/.pdf`；PDF 做文本层 / 扫描件 OCR 的 hybrid 路由——电子版直接读文本层（公章、中英混排都不影响），扫描页渲染后走 OCR（PaddleOCR 本地或视觉 LLM API），OCR 不可用优雅降级。
- **知识库隔离**：向量索引加 collection TAG，简历库与项目库标量隔离，避免多知识库混存检索串味（隔离 hit_rate 1.0 vs 混查 0.67）。
- **检索精排 rerank**：向量召回 top-N + cross-encoder（bge-reranker）精排取 top-k，可插拔降级；混查 hit_rate 0.67→0.80。回答“混合检索为何还要 rerank”：召回保证覆盖，rerank 保证排序精度。
- **多 Agent**：supervisor 编排简历分析/JD匹配/材料生成三专家子 agent；路由按“已完成步骤”而非“输出非空”，避免推理模型空 content 重复执行。
- **断点重连 / HITL**：LangGraph interrupt/Command 实现，JD 匹配后中断→人工审核→从 checkpoint 恢复，是真 resume（非只读快照）。
- **工程踩坑可讲**：paddle 3.x PIR+oneDNN 用 `enable_mkldnn=False` 规避；推理模型非流式空 content 用 reasoning_content fallback。
