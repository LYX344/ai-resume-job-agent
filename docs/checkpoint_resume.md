# Checkpoint / Resume 设计说明

本文档说明普通 `/api/v1/agent/run` Agent checkpoint 的真实实现、已开放的调试接口，以及后续生产级 resume / human-in-the-loop 的设计边界。

## 当前已实现

当前普通 Agent 使用 LangGraph `StateGraph` 编排，并默认使用本项目封装的 `LocalFileCheckpointSaver`。

默认配置：

```text
AGENT_CHECKPOINT_BACKEND=local_file
AGENT_CHECKPOINT_PATH=data/checkpoints/agent_checkpoints.pkl
```

当前能力：

- 每次 `/api/v1/agent/run` 执行都会生成 LangGraph checkpoint。
- Agent 响应返回 `thread_id`、`checkpoint_id`、`step`、`created_at`、`backend`、`durable` 和 `production_ready`。
- 有 `session_id` 时，checkpoint thread 使用 `agent-session:{session_id}`。
- 无 `session_id` 时，checkpoint thread 使用 `agent-request:{uuid}`，避免无状态请求串用同一个 thread。
- `local_file` backend 会把 checkpoint 写入本地文件，可用于单机本地 demo 的重启后重新加载。

当前已开放两个只读调试接口：

```text
GET /api/v1/agent/checkpoints/{thread_id}
GET /api/v1/agent/checkpoints/{thread_id}/history?limit=20
```

第一个接口查询 latest checkpoint snapshot metadata。第二个接口查询同一个 thread 下最近若干条 checkpoint snapshot metadata。

## 接口安全边界

checkpoint 查询接口只返回 metadata，不返回完整 `channel_values`。

返回字段包括：

- `checkpoint_id`
- `parent_checkpoint_id`
- `step`
- `created_at`
- `backend`
- `durable`
- `production_ready`
- `pending_write_count`
- `state_channel_keys`
- `resume_supported`
- `human_in_the_loop_supported`
- `notes`

这样设计的原因是 checkpoint 可能包含：

- 用户输入。
- 工具调用结果。
- 模型输出。
- 内部状态字段。
- 可能的敏感信息。

直接把完整 `channel_values` 返回给前端，会暴露过多内部状态和隐私数据。当前接口只展示有哪些状态字段，方便调试图执行过程，不展示字段内容。

## 当前不能夸大的点

当前可以说：

- Agent 响应返回 LangGraph checkpoint metadata。
- 默认使用 local-file checkpoint，本地单机 demo 下可落盘。
- 支持按 `thread_id` 查询 latest checkpoint snapshot metadata。
- 支持按 `thread_id` 查询 checkpoint history metadata。

当前对普通 `/api/v1/agent/run` 不能说：

- 已接入官方 Redis/Postgres production checkpointer。
- 已支持多 worker / 多实例共享 checkpoint。
- 已实现通用的从中断点继续执行的 resume API。
- 已实现通用 human-in-the-loop 人工审批恢复。

响应中继续明确：

```text
production_ready=false
resume_supported=false
human_in_the_loop_supported=false
```

补充边界：求职投递 workflow 已经有特定 HITL 路径：

```text
POST /api/v1/agent/job-application/review
POST /api/v1/agent/job-application/resume
```

它基于 LangGraph `interrupt` 和 `Command(resume=...)`，在 JD 匹配后中断，人工审核补充后继续生成投递材料。它证明了 HITL 模式可跑通，但不等于普通 `/agent/run` 已有通用生产级 resume API。

## checkpoint、session、memory 的区别

这三个都属于状态管理，但保存的东西不同。

| 名称 | 保存内容 | 生命周期 | 当前存储 |
|------|----------|----------|----------|
| checkpoint | LangGraph 图执行状态快照 | 图执行调试 / 未来恢复 | local file |
| session | 当前会话短期聊天历史 | 默认 24 小时 TTL | Redis |
| memory | 跨会话长期偏好和项目背景 | 长期保存 | Redis |

面试讲法：

> Redis session 保存短期会话历史，memory profile 保存长期用户偏好，LangGraph checkpoint 保存图执行状态快照。三者都和状态有关，但用途、生命周期和恢复方式不同，不能混在一起讲。

## 生产级 resume 目标形态

真正的 resume 不是把旧 checkpoint 查出来，而是让图从某个中断状态继续执行。

目标接口形态可以是：

```text
POST /api/v1/agent/resume
```

请求体示例：

```json
{
  "thread_id": "agent-session:demo",
  "checkpoint_id": "checkpoint-id",
  "resume_input": {
    "user_message": "我同意继续执行",
    "approval": true
  }
}
```

目标流程：

```text
查询 checkpoint
-> 校验 thread_id / checkpoint_id
-> 恢复 LangGraph 图状态
-> 注入用户补充信息或审批结果
-> 从中断节点继续执行
-> 返回新的 answer / steps / checkpoint metadata
```

要真正实现它，还需要：

- 使用官方 Redis/Postgres 等共享 checkpointer。
- 图里设计可中断节点。
- 明确哪些节点可以等待用户输入。
- 保存中断原因、等待的动作和审批 payload。
- 处理 checkpoint 生命周期、过期、清理和并发。

## human-in-the-loop 目标形态

human-in-the-loop 适合放在有风险或需要用户确认的动作前，例如：

- 写入长期记忆。
- 修改数据库状态。
- 生成投递材料后准备投递。
- 打开投递页或填写表单前。

目标流程：

```text
Agent 生成计划
-> 命中需要审批的节点
-> 图中断并返回 approval_required
-> 前端展示计划、风险和可选动作
-> 用户点击同意 / 拒绝 / 修改
-> 调用 resume API
-> 图继续执行后续节点
```

当前项目的求职投递辅助 Agent 后续也应该走这个模式：系统可以生成投递建议和材料草稿，但真实提交前必须由用户确认。

## 后续实施顺序

建议按下面顺序推进：

1. 继续保留 local-file checkpoint 作为本地 demo 后端。
2. 评估官方 Redis/Postgres checkpointer，并做最小接入实验。
3. 给 Agent 图增加一个低风险中断节点，例如“投递材料确认”。
4. 新增 `POST /agent/resume`，只支持指定中断节点的继续执行。
5. 前端增加审批界面，展示 checkpoint metadata、待审批动作和用户选择。
6. 再考虑多 worker 并发、checkpoint TTL、审计日志和清理策略。

## 简历表达

推荐写法：

```text
接入 LangGraph local-file checkpoint，在 Agent 响应中返回 thread_id、checkpoint_id 和 step 等 metadata，并提供 latest/history snapshot 查询接口用于调试图状态；明确标记 production_ready=false，生产级 Redis/Postgres checkpointer、resume API 和 human-in-the-loop 恢复作为后续升级方向。
```

不要写：

```text
生产级 LangGraph resume / 人工审批恢复。
```
