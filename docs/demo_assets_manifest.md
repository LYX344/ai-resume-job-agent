# 演示素材资产清单

这个文件用于管理真正要放进作品集的截图和录屏文件。它和 `data/demo/packages/*.md` 的区别是：

- `data/demo/packages/*.md`：由脚本生成，记录最近报告和素材状态。
- `docs/demo_assets_manifest.md`：人工截图/录屏时照着执行的稳定清单。

## 保存位置

所有最终截图和录屏统一放到：

```text
data/demo/assets/
```

当前必须准备 9 个文件：

| 文件 | 类型 | 内容 |
|------|------|------|
| `01-readme-overview.png` | 截图 | README 项目定位、技术栈和当前状态 |
| `02-fastapi-docs.png` | 截图 | FastAPI Docs 和核心接口 |
| `03-react-console.png` | 截图 | React 前端控制台首页 |
| `04-async-indexing.png` | 截图 | 异步上传、task_id、状态轮询和 chunk_count |
| `05-document-search.png` | 截图 | 知识库检索结果、distance 和 source |
| `06-agent-tools-steps.png` | 截图 | Agent 工具调用 answer、intent 和 steps |
| `07-memory-update.png` | 截图 | 显式记忆写入、session_id 和 memory_used |
| `08-demo-smoke-report.png` | 截图 | 最近 smoke Markdown 报告 |
| `90-second-demo.mp4` | 视频 | 按 `docs/demo_checklist.md` 的 90 秒流程录制 |

## 状态字段

`scripts/generate_demo_package.py` 现在会输出两个状态：

```text
recording_ready=True/False
portfolio_assets_ready=True/False
```

含义分别是：

| 字段 | 说明 |
|------|------|
| `recording_ready` | 最近的 demo smoke 报告是否通过，表示可以进入人工截图/录屏准备 |
| `portfolio_assets_ready` | `data/demo/assets/` 下 8 张截图和 1 个视频是否都存在 |

所以：

- `recording_ready=True` 不等于作品集素材完成。
- `portfolio_assets_ready=True` 才表示截图和视频文件已经齐了。

## 推荐截图规格

建议浏览器截图统一使用桌面视口：

```text
1440 x 900
```

如果要额外展示移动端响应式，可以补一组非必需截图：

```text
390 x 844
```

当前作品集必备素材只要求桌面截图，避免资产范围过大。

## 生成状态报告

截图或录屏之后，重新运行：

```powershell
.\.venv\Scripts\python.exe scripts\generate_demo_package.py
```

如果文件还没准备齐，最新演示包的 `Asset Status` 会显示 `missing`。全部准备齐后会显示：

```text
portfolio_assets_ready=True
```

## 面试讲法

> 我把演示资产也纳入了工程化管理。`recording_ready` 只代表最近 smoke 通过，可以开始录屏；`portfolio_assets_ready` 代表 8 张截图和 90 秒视频都已经落到固定目录。这样能防止把“可以录”误说成“素材已完成”。
