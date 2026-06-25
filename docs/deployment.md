# Docker Compose 部署说明

本项目的 Docker Compose 用于本地演示环境。当前推荐优先使用项目根目录的 `launch.py` / `启动.bat` 一键启动器；需要纯 Compose 时显式选择 profiles。

- Redis：缓存、会话、记忆、任务状态和向量检索。
- MySQL：简历投递记录和结构化数据库问答样例数据。
- API：FastAPI 后端。
- Worker：RQ 文档索引 worker，消费 Redis 队列并更新任务状态。
- Frontend：React + Vite 前端控制台。

当前异步索引已使用 RQ worker。API 容器只负责创建 `task:index:{task_id}` 并把任务入队，worker 容器执行解析、切片、embedding 和 Redis chunk 写入。

## 启动

如果本机已经手动启动了 8025 后端或 5173 前端，先停止它们，否则端口会冲突。

只启动基础设施（Redis + MySQL）：

```powershell
docker compose --profile infra up -d
```

启动完整 Compose 环境（Redis + MySQL + API + worker + frontend）：

```powershell
docker compose --profile infra --profile app up -d --build
```

也可以使用本地一键启动器。它会在 Redis/MySQL 端口未监听时按需执行 `docker compose --profile infra up -d redis mysql`，然后启动本地后端并托管已构建前端：

```powershell
.\.venv\Scripts\python.exe launch.py
```

首次构建需要访问 Docker Hub 拉取基础镜像：

```text
python:3.13-slim
node:22-alpine
redis:8
mysql:8.4
```

如果本机网络无法访问 Docker Hub，`docker compose build` 会停在基础镜像拉取阶段。此时 Compose 配置本身仍可通过 `docker compose config` 做静态校验，等网络恢复后再重新运行完整启动命令。

如果 Docker Desktop 的数据目录已经迁移到 F 盘，项目不需要修改 `docker-compose.yml`。Compose 里的 volume 仍然使用逻辑名称，镜像、容器层和 volume 的实际落盘位置由 Docker Desktop 的数据目录决定。

启动后访问：

```text
后端 API：http://127.0.0.1:8025/docs
前端控制台：http://127.0.0.1:5173
Redis：127.0.0.1:6379
MySQL：127.0.0.1:3306
```

## 健康检查

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8025/api/v1/health"
Invoke-RestMethod -Uri "http://127.0.0.1:8025/api/v1/health/redis"
Invoke-RestMethod -Uri "http://127.0.0.1:8025/api/v1/health/mysql"
Invoke-WebRequest -Uri "http://127.0.0.1:5173" | Select-Object StatusCode
docker compose ps
```

## 停止

```powershell
docker compose down
```

如果要同时删除 Redis 和 MySQL 数据卷：

```powershell
docker compose down -v
```

## MySQL 配置

Compose 会创建 `personal_agent` 数据库，并执行 `docker/mysql/init/01_job_applications.sql`：

- `job_applications`：公司、岗位、渠道、投递时间、状态、城市、薪资范围、备注。
- `application_events`：面试、HR 联系、offer、拒信、跟进等事件。
- `agent_reader`：本地演示用只读账号，只授予两张业务表的 `SELECT` 权限。

应用默认连接：

```text
MYSQL_URL=mysql+pymysql://agent_reader:agent_reader_password@127.0.0.1:3306/personal_agent
MYSQL_ALLOWED_TABLES=["job_applications","application_events"]
```

数据库问答工具仍会做二次安全校验：只允许 `SELECT`，禁止 DDL/DML、多语句和注释，强制 `LIMIT`，并限制可访问表。

## 模型 Key

默认不需要 `LLM_API_KEY` 也能演示确定性工具，例如计算器、待办、文件摘要、周报草稿和显式记忆写入。

如果要演示真实 LLM 对话或 RAG 回答，可以在本地环境变量或 `.env` 中设置：

```powershell
$env:LLM_PROVIDER="openai-compatible"
$env:LLM_BASE_URL="https://api.example.com/v1"
$env:LLM_MODEL="your-model"
$env:LLM_API_KEY="your-key"
docker compose --profile infra --profile app up -d --build
```

本地 OpenAI-compatible 反代示例：

```env
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=http://127.0.0.1:12315/v1
LLM_MODEL=your-model
LLM_API_KEY=your-local-key
```

不要把真实 `.env` 或 API Key 提交到 Git。

## Rerank 配置

默认使用 identity reranker，不需要 Key：

```text
RERANK_PROVIDER=identity
```

如果要演示两阶段检索精排，可以配置 OpenAI-compatible rerank 服务，例如：

```env
RERANK_PROVIDER=openai-compatible
RERANK_BASE_URL=https://api.siliconflow.cn/v1
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_API_KEY=your-key
RERANK_CANDIDATE_COUNT=20
```

检索流程是向量召回 top-N，再由 reranker 精排 top-k。rerank 服务不可用时应回退到 identity 或关闭真实 rerank，避免影响基础 RAG 演示。

## Embedding 配置

默认使用：

```text
EMBEDDING_PROVIDER=fake
```

这能保证没有 Key 时也能跑通文档入库、检索、Agent 工具和 demo smoke。

如果要切换真实 embedding，可以在 `.env` 中设置：

```powershell
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=your-key
EMBEDDING_DIMENSIONS=0
REDIS_VECTOR_DIMENSION=1536
```

硅基流动 Qwen3 embedding 示例：

```env
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
EMBEDDING_API_KEY=your-key
EMBEDDING_DIMENSIONS=1536
REDIS_VECTOR_DIMENSION=1536
```

注意：

- embedding 模型输出维度必须和 `REDIS_VECTOR_DIMENSION` 一致。
- 从 fake embedding 切到真实 embedding 后，需要先清理旧 chunk 或使用新索引，然后重新上传文档。
- 切换前可先 dry-run：
  ```powershell
  .\.venv\Scripts\python.exe scripts\prepare_embedding_switch.py
  ```
- 确认要清理旧向量数据后，再执行：
  ```powershell
  .\.venv\Scripts\python.exe scripts\prepare_embedding_switch.py --execute --yes-i-understand-data-loss
  ```
- 切换后建议重新运行 `scripts/evaluate_retrieval.py`，不要沿用 fake embedding 的评测结论。

## PDF / OCR 配置

文本型 PDF 只依赖 `pymupdf`，已在 `requirements.txt` 中。扫描件 OCR 是可选重依赖：

```env
PDF_OCR_ENABLED=true
PDF_OCR_PROVIDER=paddleocr
PDF_OCR_MAX_PAGES=50
```

如果需要本地 OCR，额外安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

也可以改用视觉 LLM API：

```env
PDF_OCR_PROVIDER=api
PDF_OCR_API_BASE_URL=https://api.example.com/v1
PDF_OCR_API_KEY=your-key
PDF_OCR_API_MODEL=your-vision-model
```

OCR 不可用时，扫描页会降级为明确占位文本，不会让整个上传流程崩溃。

## MCP / Trace 配置

MCP 默认关闭，启用前只配置可信本地 server：

```env
MCP_ENABLED=true
MCP_CONFIG_PATH=data/mcp/servers.json
```

配置文件参考 `data/mcp/servers.example.json`。MCP 工具会暴露给普通 Agent 的 bounded tool-call loop；默认关闭、单 server 失败跳过，避免外部 server 影响主流程。

本地 trace 默认开启：

```env
TRACE_ENABLED=true
TRACE_PATH=data/traces/traces.jsonl
TRACE_MAX_RECENT=100
```

Trace 是本地 JSONL 调试/演示能力，不是生产级 APM。

## Compose 服务关系

```text
redis -> api -> frontend
redis -> worker
mysql -> api
```

API 容器通过 Docker 网络访问 Redis：

```text
redis://redis:6379/0
```

worker 容器也通过同一个 Redis 地址消费 RQ 队列：

```text
REDIS_URL=redis://redis:6379/0
DOCUMENT_INDEX_QUEUE_NAME=document-index
```

API 容器通过 Docker 网络访问 MySQL：

```text
mysql+pymysql://agent_reader:agent_reader_password@mysql:3306/personal_agent
```

前端页面运行在浏览器中，所以默认 API Base 仍然是宿主机地址：

```text
http://127.0.0.1:8025/api/v1
```

这和容器内部服务名不同：浏览器不能直接访问 Docker 内部的 `api` 服务名。

## 本地单独运行 worker

如果不使用 Compose，而是本机手动启动 API 和 Redis，可以在项目根目录单独启动 worker：

```powershell
.\.venv\Scripts\python.exe -m app.workers.rq_worker
```

此命令会一直监听 `DOCUMENT_INDEX_QUEUE_NAME` 对应的 RQ 队列。关闭终端或停止进程后，异步上传接口仍会创建 task 和入队，但任务不会继续从 `pending` 变为 `running/done`，直到 worker 再次启动。
