# 演示截图与录屏清单

这个文件用于准备作品集截图、面试录屏和现场演示。目标是让别人不用读源码，也能在 1-2 分钟内看懂项目完成度。

## 演示前检查

先确认本地服务可用：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8025/api/v1/health"
Invoke-RestMethod -Uri "http://127.0.0.1:8025/api/v1/health/redis"
Invoke-WebRequest -Uri "http://127.0.0.1:5173" | Select-Object StatusCode
.\.venv\Scripts\python.exe scripts\demo_smoke.py
.\.venv\Scripts\python.exe scripts\generate_demo_package.py
```

演示前至少保留一份最近通过的 smoke 报告：

```text
data/demo/runs/
```

没有真实 `LLM_API_KEY` 时，不要把普通聊天和完整 RAG answer 作为必演示路径。优先演示确定性链路：异步索引、检索、Agent 工具、记忆写入。配置真实 LLM 后，可以增加普通聊天和工具调用闭环演示；完整 RAG answer 仍应等真实 embedding 重建索引后再作为质量演示。

`generate_demo_package.py` 会把最近的 smoke/eval 报告、截图清单、90 秒录屏流程和当前边界汇总到：

```text
data/demo/packages/
```

真正导出的截图和视频统一放到：

```text
data/demo/assets/
```

资产命名和状态字段说明见：

```text
docs/demo_assets_manifest.md
```

## 必备截图

建议准备 8 张截图：

1. `README.md` 首页：展示项目定位、技术栈和当前状态。
2. FastAPI Docs：展示 `/api/v1/agent/run`、`/api/v1/documents/upload/async`、`/api/v1/documents/search` 等接口。
3. React 控制台首页：展示前后端分离和 API Base。
4. 文档上传任务：展示 task_id、`pending/running/done` 状态和 chunk_count。
5. 知识库检索结果：展示 query、top_k chunks、distance、source。
6. Agent 工具调用：展示 calculator/todo/weekly report 的 answer、intent 和 steps。
7. 记忆写入：展示 `memory_update`、session_id 和 memory_used。
8. smoke 报告：展示 `total/passed/failed` 和每一步耗时。

截图命名建议：

```text
01-readme-overview.png
02-fastapi-docs.png
03-react-console.png
04-async-indexing.png
05-document-search.png
06-agent-tools-steps.png
07-memory-update.png
08-demo-smoke-report.png
```

录屏文件命名为：

```text
90-second-demo.mp4
```

运行 `scripts/generate_demo_package.py` 后，演示包中的 `portfolio_assets_ready` 会根据这些文件是否存在自动判断。

## 90 秒录屏脚本

推荐录屏顺序：

| 时间 | 画面 | 讲什么 |
|------|------|--------|
| 0-10s | README | 这是个人知识库 Agent/RAG 项目，技术栈是 FastAPI、Redis、React 和 TypeScript。 |
| 10-20s | FastAPI Docs | 后端接口包括文档异步索引、检索、RAG 查询、Agent 运行和健康检查。 |
| 20-35s | React 控制台上传文档 | 上传文档后 API 返回 task_id，前端轮询任务状态，索引完成后记录 chunk_count。 |
| 35-50s | 文档检索 | 查询会走 Redis 向量检索，返回 top_k chunk、distance 和 source。 |
| 50-70s | Agent 工具 | Agent 会识别 intent 并调用工具，steps 可以看到运行过程。 |
| 70-80s | 记忆写入 | 显式“请记住”会写入长期 memory profile，同时保留短期 session。 |
| 80-90s | smoke 报告 | 演示前我用脚本跑一遍确定性链路，报告里可以看到所有步骤通过。 |

## 现场演示顺序

现场演示建议不要从代码开始，先展示结果，再打开关键实现：

1. 打开 React 控制台，确认后端连接正常。
2. 上传 `README.md` 或一份 `.md/.txt/.docx` 文档。
3. 等任务状态变成 `done`。
4. 在知识库检索里输入：`Redis 在项目里做什么？`
5. 在 Agent Console 里输入：`请计算 2 + 3 * 4 等于多少？`
6. 再输入：`帮我生成待办：复习 Redis、写简历、提交周报`
7. 再输入：`请记住：我喜欢先给结论`
8. 打开最近的 `data/demo/runs/*.md`，展示自动化 smoke 结果。
9. 打开最近的 `data/demo/packages/*.md`，确认截图清单、录屏流程和当前限制没有遗漏。

## 失败兜底

| 情况 | 现场讲法 |
|------|----------|
| 没有 `LLM_API_KEY` | 本地演示先跑确定性 Agent 工具和检索链路，需要模型生成的完整回答会返回 503，这是配置缺失而不是服务崩溃。 |
| Docker Hub 拉镜像失败 | Dockerfile 和 Compose 配置已经通过静态解析，完整 build/up 依赖 Docker Hub 网络。当前可以用本地后端、前端和 Redis 演示。 |
| 检索结果不够语义相关 | 先确认本地是否已使用真实 embedding 配置、是否清理旧 `doc:*` 并重建索引，以及是否参考最新 retrieval eval 报告。仓库默认仍保留 fake embedding 用于无 Key 工程链路测试。 |
| Agent 没有调用知识库 | 先检查请求里的 `use_knowledge_base`，再看 response 的 `intent`、`used_knowledge_base` 和 `steps`。 |

## 交付物检查

投递前确认这些文件存在：

- `README.md`
- `docs/architecture.md`
- `docs/demo.md`
- `docs/demo_checklist.md`
- `docs/demo_assets_manifest.md`
- `docs/deployment.md`
- `docs/interview_notes.md`
- `docs/resume_pitch.md`
- `data/demo/runs/*.md`
- `data/demo/packages/*.md`
- `data/demo/assets/*.png`
- `data/demo/assets/90-second-demo.mp4`
- `data/eval/runs/*.md`
