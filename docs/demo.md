# 演示脚本说明

本项目提供一个本地演示烟测脚本：

```powershell
.\.venv\Scripts\python.exe scripts\demo_smoke.py
```

也提供一个演示包生成脚本：

```powershell
.\.venv\Scripts\python.exe scripts\generate_demo_package.py
```

它默认访问：

```text
http://127.0.0.1:8025/api/v1
```

运行前需要确认：

- Redis 容器已启动。
- FastAPI 后端正在 `127.0.0.1:8025` 运行。
- 可选：React 前端正在 `127.0.0.1:5173` 运行。

## 脚本会验证什么？

`scripts/demo_smoke.py` 会跑一组不依赖真实 `LLM_API_KEY` 的确定性演示：

1. 后端 health check。
2. Redis health check。
3. 异步上传 `README.md`。
4. 轮询索引任务直到 `done`。
5. 调用文档检索接口。
6. 调用 Agent 计算器工具。
7. 调用 Agent 待办工具。
8. 调用 Agent 文件摘要工具。
9. 调用 Agent 周报草稿工具。
10. 调用 Agent 显式长期记忆写入。

脚本会输出 JSON 和 Markdown 报告到：

```text
data/demo/runs/
```

## 演示包会整理什么？

`scripts/generate_demo_package.py` 不启动后端，也不依赖浏览器。它会读取当前已有的 smoke/eval 报告，并生成一份录屏前检查用的演示包。

演示包会输出到：

```text
data/demo/packages/
```

内容包括：

- 最近的 demo smoke 报告路径和摘要。
- 最近的 retrieval eval 报告路径和摘要。
- 8 张必备截图清单。
- 90 秒录屏流程。
- 演示前常用命令。
- 当前不能夸大的边界说明。
- `data/demo/assets/` 中截图和录屏的缺失状态。

其中 `recording_ready=True` 表示最近 smoke 报告通过，可以进入人工截图/录屏准备；`portfolio_assets_ready=True` 才表示 8 张截图和 90 秒视频都已经保存到固定目录。

## 自定义 API 地址

```powershell
.\.venv\Scripts\python.exe scripts\demo_smoke.py --api-base "http://127.0.0.1:8025/api/v1"
```

## 面试演示讲法

> 我准备了一个 demo smoke 脚本，用来一键验证本地演示链路。它会检查后端和 Redis 健康状态，异步上传 README 并轮询索引任务，然后依次验证文档检索、计算器、待办、文件摘要、周报草稿和长期记忆写入。这个脚本不依赖真实 LLM Key，所以可以稳定演示工程链路和 Agent 工具调用。

## 截图和录屏

演示材料整理见：

```text
docs/demo_checklist.md
```

建议至少准备 README、FastAPI Docs、React 控制台、异步索引、知识库检索、Agent steps、记忆写入和 smoke 报告 8 张截图。
截图和视频统一放到 `data/demo/assets/`，具体命名见 `docs/demo_assets_manifest.md`。录屏前可以先运行 `scripts/generate_demo_package.py`，再按最新生成的 `data/demo/packages/*.md` 检查素材。

## 注意

当前脚本会上传 `README.md`，因此会向 Redis 写入新的文档 chunk。它适合作为本地演示和面试前检查，不是线上压测脚本。
