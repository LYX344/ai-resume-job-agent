# AI Resume Job Agent / AI 简历求职助手

一个面向就业作品集的 Python Agent 项目：个人知识库 + 办公自动化助手。

## 项目目标

本项目最终会实现：

- 文档上传与知识库入库
- Redis 向量检索与缓存
- MySQL 简历投递数据库问答
- RAG 问答与引用来源
- LangGraph Agent 工作流
- 工具调用
- 短期记忆与长期记忆
- 异步文档索引
- React + Vite 前端演示界面
- Docker Compose 一键启动
- 架构图、评测报告和面试讲解稿

## 学习路线

1. 搭 FastAPI 工程骨架。
2. 接入模型 API。
3. 接入 Redis。
4. 实现文档解析、切片、embedding、索引。
5. 实现基础 RAG 问答。
6. 用 LangGraph 改造成 Agent workflow。
7. 加工具调用和长期记忆。
8. 加异步任务、前端、评测和 Docker。

代码级学习入口见 `docs/code_walkthrough_from_zero.md`。这份文档按从空目录到当前项目的顺序拆解每一阶段要改哪些文件、为什么这么分层、怎么验证。模块职责、输入输出、调用关系和常见改动点见 `docs/code_module_breakdown.md`。

## 当前状态

已完成：

- FastAPI 工程骨架
- `/api/v1/health` 健康检查
- OpenAI-compatible 模型适配层
- OpenAI-compatible tool-calling adapter，可发送 `tools/tool_choice` 并解析 `tool_calls`
- `/api/v1/chat` 非流式聊天接口
- `/api/v1/chat/stream` SSE 流式聊天接口
- Docker Redis
- Docker MySQL 和简历投递样例数据库
- Redis health check
- MySQL health check
- Redis session 存储
- Redis vector index 配置预留
- `.txt` / `.md` / `.docx` / `.pdf` 文档解析与 chunk 切片
- PDF 文本层 / 扫描件 hybrid 路由：电子版直接提取文本层，扫描页渲染后走 OCR（PaddleOCR 本地或视觉 LLM API），支持中英混排和公章文字（best-effort），OCR 不可用时优雅降级为占位
- 知识库 collection 隔离：上传/检索按 collection（如 `resume` / `project_docs`）标量过滤，避免多知识库混存导致检索串味（隔离后简历检索 hit_rate 1.0，混查仅 0.67）
- 两阶段检索 rerank：向量召回 top-N + cross-encoder（bge-reranker-v2-m3）精排取 top-k，可插拔（identity 降级），混查 hit_rate 0.67→0.80
- Multi-Agent supervisor 求职投递工作流：简历分析 → JD 匹配 → 投递材料生成（`/api/v1/agent/job-application`）
- HITL 断点重连：JD 匹配后中断人工审核，从 LangGraph checkpoint 恢复生成材料（`/api/v1/agent/job-application/review` + `/resume`）
- MCP client 接入：用官方 `mcp` SDK 连接外部 MCP server（stdio / streamable HTTP），发现工具并暴露给 Agent 普通聊天的 tool-call 循环；默认 `MCP_ENABLED=false` 优雅降级，区分面试高频题 MCP / Function Calling / Skills
- MCP 能力发现与可视化：`inspect` 一次连接发现外部 server 的 tools / resources / prompts，前端 MCP 面板可视化展示；已验证可接官方第三方 `server-everything`（13 tools / 7 resources / 4 prompts）；trace 记录工具调用类型（builtin / llm_tool / mcp）
- 前端运行 Trace 回放：「运行 Trace」面板加载 `/api/v1/traces`，可视化最近 Agent 运行的 intent / 耗时 / model / 工具调用（builtin / llm_tool / mcp 分类）
- 确定性假 embedding，用于无 API Key 的入库链路测试
- OpenAI-compatible 真实 embedding client 适配，可通过配置切换
- Redis chunk HASH 入库
- `/api/v1/documents/upload` 文档上传入库接口
- `/api/v1/documents/upload/async` 异步文档索引任务接口
- `/api/v1/documents/tasks/{task_id}` 文档索引任务状态查询接口
- `/api/v1/documents/search` 基础向量检索接口
- `/api/v1/rag/query` RAG 问答接口
- `/api/v1/agent/run` LangGraph StateGraph Agent 工作流入口
- `/api/v1/agent/checkpoints/{thread_id}` Agent checkpoint snapshot 查询接口
- `/api/v1/agent/checkpoints/{thread_id}/history` Agent checkpoint history metadata 查询接口
- `/api/v1/mcp/tools` 已连接 MCP server 的可用工具列表
- `/api/v1/mcp/servers` MCP server 连接状态
- `/api/v1/mcp/capabilities` MCP server 的 tools / resources / prompts 汇总
- `/api/v1/config` 运行时模型配置查询（GET，API key 脱敏）与设置（PUT，保存到 Redis 即时生效）
- `/api/v1/config/test` 用当前配置对 LLM / 向量化 / Rerank 做最小连通性测试
- Agent `call_tools` 节点与 `search_docs` 文档检索工具
- Agent `calculator` 确定性计算工具
- Agent `create_todo` Markdown 待办生成工具
- Agent `summarize_file` 安全文件摘要工具
- Agent `draft_weekly_report` 周报草稿工具
- Agent `query_database` 简历投递数据库问答工具，使用只读 SELECT、安全 SQL 校验和确定性 SQL 模板
- Agent 工具 schema 注册表，可导出 OpenAI-compatible function tool schema
- Agent 普通聊天分支支持 bounded LLM tool-call loop：最多执行 3 轮安全工具调用，记录 `tool_calls`、通过 LangGraph `ToolNode` 子图执行工具、回传 tool message，并在达到上限后强制收束为最终回答
- Agent 响应返回 LangGraph checkpoint metadata，默认 `backend=local_file`、`durable=true`、`production_ready=false`，可跨本地进程重启重新加载 checkpoint
- Agent checkpoint snapshot/history 查询接口，可按 `thread_id` 查询 latest 或最近若干条 checkpoint metadata、parent checkpoint、step 和 state channel keys
- Agent 短期会话记忆与长期 memory profile
- React + Vite + TypeScript 前端控制台
- 前端支持后端连接检查、模型配置（运行时设置 LLM / 向量化 / Rerank 的 provider、base_url、model、api_key，无需改 `.env` 重启）、异步文档上传、任务状态轮询、知识库检索、Agent 运行和记忆写入
- 本地前端 CORS 配置
- mock 单元测试与接口测试
- 20 题固定检索评测脚本和 Markdown/JSON 报告
- 真实 embedding 切换准备脚本，默认 dry-run，可安全清理旧 Redis vector index 和 `doc:*` chunk
- 硅基流动 Qwen3-Embedding-4B 真实 embedding 端到端检索评测：清理旧 chunk、重建 Redis 索引后最新 `hit_rate=1.0`
- 固定 20 题真实 RAG answer 规则化评测（LLM 用 deepseek-v4-pro）：`pass_rate` / `citation_match` 均 `1.0`、零错误（关键词命中 + 引用一致性评分）
- 结构化 HTTP 请求日志
- 架构说明和面试讲解稿
- 演示截图/录屏清单
- 简历投递版项目话术

## 一键启动（前后端集中入口）

为方便演示，提供一个集中启动入口：后端在同一端口（默认 8025）同时托管已构建的前端，启动后自动做健康检查并打开浏览器，按 `Ctrl+C` 优雅关闭。

最简单的方式是双击项目根目录的 `启动.bat`，或在命令行执行：

```powershell
.\.venv\Scripts\python.exe launch.py
```

- 默认模式（单进程）：后端 + 前端共用 `http://127.0.0.1:8025`；若 `frontend/dist` 不存在会自动 `npm run build`（需要 Node/npm）。
- 开发模式（前后端分离 + Vite 热更新）：`launch.py --dev`，前端走 `http://127.0.0.1:5173`。
- 常用参数：`--port`、`--host`、`--no-browser`、`--skip-build`、`--no-infra`、`--infra-only`、`--keep-infra`。

启动时会自动检查依赖：若 Redis(6379) / MySQL(3306) 未在监听且本机 Docker 可用，启动器会通过 `docker compose --profile infra up -d redis mysql` 自动拉起它们，已在运行则跳过。退出（`Ctrl+C` 或后端结束）时会自动停掉**本次由启动器拉起**的容器，但不会动你原本就在运行的容器；想退出时保留这些容器可加 `--keep-infra`。自备 Redis/MySQL 时用 `--no-infra` 跳过自动拉起；只拉依赖不起服务用 `--infra-only`。

打包成 exe（可选，双击 exe 即可启动）：运行 `package_exe.bat`，生成的 `ai-resume-job-agent-launcher.exe` 复制到项目根目录（与 `app\`、`frontend\`、`.venv\` 同级）后运行即可。

> 说明：Redis / MySQL 默认不随 `docker compose up` 自动启动，而是由启动器在启动时按需用 Docker 拉起（需要 Docker Desktop）。无 `LLM_API_KEY` 时，需要大模型生成回答的路径会返回 503，确定性工具仍可演示。

本地开发服务：

```text
后端 API：http://127.0.0.1:8025/docs
前端控制台：http://127.0.0.1:5173
MySQL：127.0.0.1:3306
```

没有配置 `LLM_API_KEY` 时，聊天接口会返回 `503`，这是预期行为。在 `.env` 中填写 OpenAI-compatible 模型服务或本地反代配置后即可调用真实模型。

本地反代配置示例：

```powershell
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=http://127.0.0.1:12315/v1
LLM_MODEL=your-model
LLM_API_KEY=your-local-key
```

前端启动示例：

```powershell
cd frontend
npm install
npm run dev
```

前端默认连接：

```text
http://127.0.0.1:8025/api/v1
```

文档上传示例：

```powershell
curl.exe -F "file=@README.md;type=text/markdown" "http://127.0.0.1:8025/api/v1/documents/upload"
```

DOCX 上传示例：

```powershell
curl.exe -F "file=@data/uploads/stage17_docx_demo.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" "http://127.0.0.1:8025/api/v1/documents/upload"
```

异步文档索引示例：

```powershell
$response = curl.exe -s -F "file=@README.md;type=text/markdown" "http://127.0.0.1:8025/api/v1/documents/upload/async"
$taskId = ($response | ConvertFrom-Json).task_id
Invoke-RestMethod -Uri "http://127.0.0.1:8025/api/v1/documents/tasks/$taskId"
```

文档检索示例：

```powershell
$body = @{ query = "Redis RAG"; top_k = 2 } | ConvertTo-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8025/api/v1/documents/search" -Method Post -ContentType "application/json" -Body $body
```

RAG 问答示例：

```powershell
$body = @{ query = "Redis 能做什么？"; top_k = 2 } | ConvertTo-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8025/api/v1/rag/query" -Method Post -ContentType "application/json" -Body $body
```

Agent 工作流示例：

```powershell
$body = @{ query = "Redis 在项目里做什么？"; use_knowledge_base = $true; top_k = 2 } | ConvertTo-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8025/api/v1/agent/run" -Method Post -ContentType "application/json" -Body $body
```

Agent 计算工具示例：

```powershell
$body = @{ query = "请计算 2 + 3 * 4 等于多少？" } | ConvertTo-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8025/api/v1/agent/run" -Method Post -ContentType "application/json" -Body $body
```

Agent 待办工具示例：

```powershell
$body = @{ query = "帮我生成待办：复习 Redis、写简历、提交周报" } | ConvertTo-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8025/api/v1/agent/run" -Method Post -ContentType "application/json" -Body $body
```

Agent 文件摘要工具示例：

```powershell
$body = @{ query = "请总结 README.md" } | ConvertTo-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8025/api/v1/agent/run" -Method Post -ContentType "application/json" -Body $body
```

Agent 周报草稿工具示例：

```powershell
$body = @{ query = "帮我写周报：本周完成：接入 Redis、补充测试；问题：没有 API Key；下周计划：实现前端、完善 README" } | ConvertTo-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8025/api/v1/agent/run" -Method Post -ContentType "application/json" -Body $body
```

Agent 记忆示例：

```powershell
$body = @{ session_id = "demo-memory"; query = "请记住：我喜欢先给结论"; use_knowledge_base = $false } | ConvertTo-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8025/api/v1/agent/run" -Method Post -ContentType "application/json" -Body $body
```

Agent 数据库问答示例：

```powershell
$body = @{ query = "我投了哪些公司的什么岗位？" } | ConvertTo-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8025/api/v1/agent/run" -Method Post -ContentType "application/json" -Body $body
```

检索评测示例：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py --top-k 3
```

真实 embedding 切换准备：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_embedding_switch.py
```

确认要清理旧 fake/旧模型向量数据后再执行：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_embedding_switch.py --execute --yes-i-understand-data-loss
```

本地演示烟测：

```powershell
.\.venv\Scripts\python.exe scripts\demo_smoke.py
```

生成作品集演示包：

```powershell
.\.venv\Scripts\python.exe scripts\generate_demo_package.py
```

当前评测问题集：

```text
data/eval/rag_questions.json
```

评测报告会输出到：

```text
data/eval/runs/
```

当前样例报告：

```text
data/eval/runs/retrieval_eval_20260615_215758.md
```

默认配置仍保留确定性假 embedding，适合无 Key 场景下验证工程链路；也已经提供 OpenAI-compatible 真实 embedding client。当前本地已用硅基流动 Qwen3-Embedding-4B 按 1536 维重建 Redis 文档索引，并完成固定问题集 retrieval eval，最新 `hit_rate=1.0`。如果换 embedding 模型，需要重新确认维度、清理旧 `doc:*` chunk、重新上传文档并跑检索评测。没有配置 `LLM_API_KEY` 时，需要 LLM 生成自然语言答案的路径会返回 `503`；计算、待办、文件摘要、周报草稿和显式记忆写入等确定性工具仍可本地演示。

真实 embedding 配置示例：

```powershell
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=your-key
EMBEDDING_DIMENSIONS=0
REDIS_VECTOR_DIMENSION=1536
```

硅基流动 Qwen3 embedding 配置示例：

```powershell
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
EMBEDDING_API_KEY=your-key
EMBEDDING_DIMENSIONS=1536
REDIS_VECTOR_DIMENSION=1536
```

## 投递版交付材料

如果要把这个项目用于简历或作品集，优先准备这些材料：

- `docs/resume_pitch.md`：简历项目名、项目描述、要点、面试开场和不能夸大的边界。
- `docs/demo_checklist.md`：截图清单、90 秒录屏脚本、现场演示顺序和失败兜底话术。
- `docs/demo_assets_manifest.md`：最终截图和 90 秒录屏的文件命名、保存位置和状态字段说明。
- `docs/interview_notes.md`：更完整的 30 秒/2 分钟讲解、技术亮点和常见追问。
- `docs/interview_question_mapping.md`：真实面试题常考点与本项目能力、缺口和对向优化路线的映射。
- `data/demo/runs/`：demo smoke 自动化演示报告。
- `data/demo/packages/`：自动生成的作品集演示包，汇总最新 smoke/eval 报告、截图清单、录屏流程和边界说明。
- `data/eval/runs/`：固定问题集检索评测报告。

## Docker Compose 启动

compose 服务按 profile 分组，避免基础设施被无意中随手启动占用端口：

- `infra` profile：`redis`、`mysql`
- `app` profile：`api`、`worker`、`frontend`

因此**直接 `docker compose up` 不会启动任何服务**，需要按需指定 profile：

```powershell
# 只起基础设施（Redis + MySQL）；本地用 launch.py 跑后端/前端时配合使用
docker compose --profile infra up -d

# 起全套（基础设施 + 后端 + worker + 前端）
docker compose --profile infra --profile app up -d --build
```

> 一键启动入口 `launch.py` / `启动.bat` / exe 会在启动时自动拉起 `infra`（Redis/MySQL），所以本地开发通常不需要手动执行上面的命令。

首次构建需要能访问 Docker Hub，以拉取 `python:3.13-slim`、`node:22-alpine`、`redis:8` 和 `mysql:8.4`。

服务地址：

```text
后端 API：http://127.0.0.1:8025/docs
前端控制台：http://127.0.0.1:5173
Redis：127.0.0.1:6379
MySQL：127.0.0.1:3306
```

异步文档索引已使用 RQ worker：API 创建任务并写入 Redis 队列，`worker` 服务消费任务并更新 Redis task 状态。Compose 中的 worker 命令为：

```powershell
python -m app.workers.rq_worker
```

如果本机已经手动启动了 8025 后端或 5173 前端，先停止旧进程再运行 compose，避免端口冲突。详细说明见 `docs/deployment.md`。

## 项目文档

建议按这个顺序阅读：

- `docs/code_walkthrough_from_zero.md`：从 0 开始的代码级拆解，按 FastAPI、配置、LLM、Redis、RAG、Agent、MySQL、worker、前端和评测逐步阅读代码。
- `docs/code_module_breakdown.md`：按当前工程模块解释每个目录/文件的职责、输入输出、调用链、测试对应关系和常见需求改动位置。
- `docs/architecture.md`：系统架构、模块边界、Redis key 设计、RAG/Agent/Memory/Async/Evaluation 流程图。
- `docs/demo.md`：本地演示 smoke 脚本、验证内容和面试讲法。
- `docs/demo_checklist.md`：截图、录屏、现场演示顺序和失败兜底清单。
- `docs/demo_assets_manifest.md`：演示截图和视频资产清单，区分 `recording_ready` 与 `portfolio_assets_ready`。
- `data/demo/packages/`：由 `scripts/generate_demo_package.py` 生成的演示包，用于录屏前检查和作品集交付。
- `docs/deployment.md`：Docker Compose 本地启动、健康检查、停止和 Key 配置说明。
- `docs/embedding_switch.md`：从 fake embedding 切换到真实 embedding 前的 Redis 清理、维度确认、重建索引和评测流程。
- `docs/checkpoint_resume.md`：checkpoint snapshot/history 查询、resume 目标形态和 human-in-the-loop 边界说明。
- `docs/interview_notes.md`：30 秒项目介绍、简历写法、技术亮点、常见面试问答和演示顺序。
- `docs/interview_question_mapping.md`：基于真实面试题整理的高频考点映射，区分可直接支撑、只能部分迁移和不能 claim 的内容，并给出对向优化优先级。
- `docs/resume_pitch.md`：简历投递版项目话术、项目要点和边界说明。
- `docs/learning_log.md`：本项目分阶段教学问答和概念纠正。
- `task_plan.md`：阶段计划和剩余任务。
- `progress.md`：每个阶段实际完成了什么。
- `findings.md`：技术决策、踩坑和工程发现。

重要说明：

- 仓库默认 embedding 仍保留确定性假 embedding，用于无 API Key 场景下验证工程链路；当前本地已完成硅基流动 Qwen3-Embedding-4B 真实 embedding 检索评测，项目知识库固定 20 题报告为 `data/eval/runs/retrieval_eval_20260615_215758.md`（hit_rate=1.0）。简历知识库场景另有 collection 隔离与 rerank 评测：混查会串味，collection 隔离可把简历检索 hit_rate 提升到 1.0，rerank 可把混查 hit_rate 从 0.67 提升到 0.80。更换 embedding 模型后必须清理旧向量、重建索引并重新评测。
- LLM client 已支持 OpenAI-compatible tool-calling adapter：请求可携带 `tools/tool_choice`，响应可解析 `tool_calls`，二次请求可携带 assistant `tool_calls` 和 `tool` message。
- 工具层已新增 schema 注册表，可以把 `search_docs`、`calculator`、`create_todo`、`summarize_file`、`draft_weekly_report`、`query_database` 导出为 function tool schema；当前普通聊天分支实际执行的 LLM 自动工具限定为 `calculator`、`create_todo`、`summarize_file`、`draft_weekly_report`，不把长期记忆写入和数据库查询暴露给模型自动调用。
- MySQL 数据库问答第一版已完成：Compose 初始化 `job_applications` 和 `application_events`，应用使用只读账号查询，`query_database` 工具通过确定性 SQL 模板回答投递记录问题，并做只读 SELECT、禁止多语句、强制 LIMIT 和允许表校验。当前还不是 LLM 自由生成 SQL。
- 文档 loader 当前支持 `.txt`、`.md`、`.docx` 和 `.pdf`；DOCX 提取段落和表格文本，PDF 使用 hybrid 路由（文本层直接提取，扫描页渲染后走 OCR），都进入同一套 `Document -> DocumentChunk -> embedding -> Redis` 流程。PDF 的 OCR 依赖是可选的：核心文本型解析只需 `pymupdf`，扫描件 OCR 需要额外安装 `requirements-ocr.txt`（PaddleOCR）或配置视觉 LLM API。
- 当前普通 Agent workflow 已迁移到 LangGraph `StateGraph`，节点包括 `load_memory`、`understand_intent`、`decide_retrieval`、`call_tools`、`skip_tools`、`generate_answer`、`save_trace`；`decide_retrieval` 后已使用条件边路由到工具执行或跳过工具，普通聊天分支可通过 LangGraph `ToolNode` 子图执行最多 3 轮 bounded LLM tool calls，并在达到上限后再做一次不带 tools 的最终回答。当前默认 `AGENT_CHECKPOINT_BACKEND=local_file`，checkpoint 保存到 `data/checkpoints/agent_checkpoints.pkl`，响应里返回 `backend=local_file`、`durable=true`、`production_ready=false`；可通过 `/agent/checkpoints/{thread_id}` 查询 latest checkpoint snapshot 元数据，也可通过 `/agent/checkpoints/{thread_id}/history` 查询最近若干条 checkpoint metadata。它可跨本地进程重启重新加载 checkpoint，但不是官方 Redis/Postgres checkpointer，不支持多 worker 生产级恢复，也还没有实现面向 `/agent/run` 的通用 resume API。求职投递 workflow 另有特定 HITL review/resume：`/agent/job-application/review` 在 JD 匹配后中断，`/agent/job-application/resume` 在人工审核后继续生成材料。
- 当前异步索引已从 FastAPI `BackgroundTasks` 升级为 RQ worker 第一版：API 只入队，worker 消费任务，Redis 保存 `pending/running/done/failed` 状态。它是真实独立 worker，但还没有重试退避、死信队列、Dashboard 或调度能力。

详细执行计划见：

- `task_plan.md`
- `findings.md`
- `progress.md`
- `docs/learning_log.md`
