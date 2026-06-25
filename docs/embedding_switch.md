# 真实 Embedding 切换手册

## 目标

从默认 fake embedding 切换到真实 embedding 前，必须先清理旧 Redis 向量数据，再重新上传文档和评测检索效果。

原因：

- fake embedding 和真实 embedding 的向量语义完全不同，混存在同一个 Redis index 里会让检索结果失真。
- 不同 embedding 模型可能输出不同维度，Redis vector index 的 `DIM` 必须和模型输出维度一致。
- 旧 chunk 即使维度相同，也不代表语义空间相同，仍然应该重建。

## 当前配置检查

先做 dry-run，确认当前 Redis、索引、chunk 数量和 embedding 配置：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_embedding_switch.py
```

这个命令不会修改 Redis。它只会输出：

- `embedding_provider`
- `embedding_model`
- `vector_index_name`
- `vector_key_prefix`
- `vector_dimension`
- `index_exists`
- `document_chunk_key_count`

## 清理旧向量数据

确认要删除旧 chunk 后，再执行：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_embedding_switch.py --execute --yes-i-understand-data-loss
```

它会做两件事：

- 删除 Redis vector index，例如 `idx:docs`。
- 删除当前文档 chunk key 前缀下的数据，例如 `doc:*`。

它不会删除：

- `session:*`
- `memory:profile:*`
- `task:index:*`
- LangGraph local-file checkpoint

## 配置真实 Embedding

在 `.env` 中设置真实 embedding 参数，不要把真实 Key 写进代码或提交到 Git：

```env
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://your-provider.example/v1
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_API_KEY=your-api-key
EMBEDDING_DIMENSIONS=0
REDIS_VECTOR_DIMENSION=1536
```

`REDIS_VECTOR_DIMENSION` 必须等于模型实际输出维度。维度不一致时，本项目会拒绝写入 Redis，避免污染索引。

如果使用硅基流动 Qwen3 embedding，可以显式要求模型返回 1536 维，和当前 Redis index 维度保持一致：

```env
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
EMBEDDING_API_KEY=your-api-key
EMBEDDING_DIMENSIONS=1536
REDIS_VECTOR_DIMENSION=1536
```

## 重建索引和文档

配置完成后：

1. 重启 FastAPI 服务，让 `.env` 配置重新加载。
2. 重新上传 `.txt` / `.md` / `.docx` 文档。
3. 上传流程会自动重新创建 Redis vector index。
4. 重新运行 retrieval eval。

评测命令：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py --top-k 3
```

## 验收标准

阶段 14B 只要求“切换准备完成”，不要求真实 Key 评测完成。

完成标准：

- dry-run 能显示当前 Redis index 和 chunk 数量。
- execute 模式必须显式确认，避免误删。
- 旧 fake chunk 不会和真实 embedding chunk 混存。
- 文档说明清楚维度、重建和评测流程。

阶段 14C 才会在配置真实 `EMBEDDING_API_KEY` 后做端到端评测，并输出 JSON/Markdown 报告。
