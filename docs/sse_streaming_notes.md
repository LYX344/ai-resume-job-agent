# SSE 流式输出说明（阶段 23D）

本文档说明本项目的 SSE 流式实现，以及面试中关于 SSE / WebSocket / 断线续传的标准讲法。

## 1. 本项目的 SSE 实现

后端 `POST /api/v1/chat/stream`（`app/api/routes/chat.py`）用 FastAPI `StreamingResponse`（`text/event-stream`）输出 SSE。模型适配层 `app/services/llm_client.py` 的 `stream_chat` 把上游 OpenAI-compatible 流式响应解析成结构化 `LLMStreamDelta(type, text)`。

每条 SSE 数据事件格式：

```text
id: {递增序号}
data: {"delta": "...", "type": "reasoning" | "content"}
```

结束事件：

```text
id: {n}
data: {"done": true, "finish_reason": "stop"}
```

错误事件：

```text
id: {n}
data: {"error": {"status_code": 502, "message": "..."}}
```

关键设计：

- **区分 reasoning 与 content**：deepseek-v4-pro 等推理模型流式时先输出 `reasoning_content`（思考），再输出 `content`（答案）。`_parse_stream_line` 优先取 `content`，为空时取 `reasoning_content`，并打上 `type`，前端分别渲染“思考过程 / 最终答案”。
- **event id**：每条事件带递增 `id`，前端可记录 `lastEventId`，重连时通过 `Last-Event-ID` 请求头带回。
- **finish_reason**：done 事件带 `finish_reason`，前端可判断回复是否完整（`stop`）还是被 `max_tokens` 截断（`length`）。注意 deepseek 思考占大量 token，`max_tokens` 要给足（建议 >= 2000）。

前端 `frontend/src/api.ts` 的 `streamChat` 用 `fetch` + `ReadableStream` 读取，配合纯函数 `parseSSEBuffer` 解析；`App.tsx` 的“流式对话”面板边接收边渲染，支持 `AbortController` 停止。

## 2. SSE vs WebSocket

| 维度 | SSE | WebSocket |
|---|---|---|
| 方向 | 服务端 -> 客户端单向 | 全双工双向 |
| 协议 | HTTP（text/event-stream） | ws/wss（独立握手） |
| 断线重连 | 浏览器 EventSource 自带，支持 Last-Event-ID | 需自己实现心跳/重连 |
| 适用场景 | LLM 流式输出、通知、日志、进度推送 | 聊天室、协同编辑、游戏、实时双向 |
| 代理穿透 | 普通 HTTP，穿透性好 | 可能被部分代理拦截 |

本项目 LLM 流式输出是典型的服务端单向推送，用 SSE 更轻、更合适，不需要 WebSocket 的双向能力。

## 3. 断线续传的真实边界（重要）

SSE 的 `Last-Event-ID` 适合**可重放 / 可定位**的事件流（服务端有持久化事件序列，断线后从某个 id 之后重发）。

但 **LLM 流式生成本身不可恢复**：上游模型的生成是一次性的流，中间状态无法从某个 token 续传。因此本项目的 `Last-Event-ID` 主要用于**标记客户端已收到的位置**，真正断线后的策略是**重新发起一次生成**，而不是从断点续传上游 LLM。面试时要讲清楚这个边界，不要夸大成 “LLM 流式断点续传”。

如果未来要做真正可恢复的流，需要服务端把已生成内容持久化（如写入 Redis），重连时先回放已存内容、再继续生成。

## 4. 降级与弱网策略

- **降级轮询**：若浏览器/网络不支持流式或反复断线，可降级为非流式 `POST /chat`（一次性拿完整回复）；长任务可用状态轮询（本项目文档索引任务即用 1.2s 轮询）。
- **指数退避**：重连/轮询失败时，重试间隔逐次放大（如 1s -> 2s -> 4s，设上限），避免雪崩。
- **心跳**：长连接可周期性发送注释行 `: keepalive` 防止中间代理超时断开（演示场景未启用，可作为增强项）。
- **弱网提示**：连接异常时前端显示明确状态（如“连接中断，正在重试”），并允许手动重试。

## 5. 不能夸大的边界

- 当前前端流式面板演示的是 `/chat/stream`（纯聊天流式）；RAG / Agent 路径目前是非流式一次性返回。
- `Last-Event-ID` 是协议层支持，但 LLM 生成不可真正断点续传（见第 3 节）。
- 心跳、自动指数退避重连属于设计 / 增强项，演示版未全部实现。
