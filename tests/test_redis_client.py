import json
import struct

import pytest
from redis import ResponseError

from app.models.chat import ChatMessage
from app.models.document import DocumentChunk, DocumentIndexTaskState
from app.models.memory import MemoryProfile
from app.models.session import SessionState
from app.models.vector_index import RedisVectorIndexConfig
from app.rag.indexer import index_document_chunks
from app.services.embedding_client import DeterministicEmbeddingClient
from app.services.redis_client import RedisStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, object]] = {}
        self.expires: dict[str, int | None] = {}
        self.commands: list[tuple[object, ...]] = []
        self.index_exists = False
        self.index_missing_error = "Unknown Index name"
        self.search_results: list[object] = [
            1,
            "doc:abc:0",
            [
                "content",
                "agent rag redis",
                "metadata",
                '{"chunk_id": "abc:0", "source": "notes.md"}',
                "vector_distance",
                "0.12",
            ],
        ]
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        self.expires[key] = ex

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def hset(self, key: str, mapping: dict[str, object]) -> None:
        self.hashes[key] = mapping

    async def delete(self, *keys: str) -> int:
        deleted_count = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                deleted_count += 1
            if key in self.hashes:
                del self.hashes[key]
                deleted_count += 1
        return deleted_count

    async def scan_iter(self, match: str, count: int = 1000):  # type: ignore[no-untyped-def]
        if not match.endswith("*"):
            return
        prefix = match[:-1]
        for key in sorted([*self.values.keys(), *self.hashes.keys()]):
            if key.startswith(prefix):
                yield key

    async def execute_command(self, *args: object) -> object:
        self.commands.append(args)
        command = str(args[0]).upper()
        if command == "FT.INFO":
            if not self.index_exists:
                raise ResponseError(self.index_missing_error)
            return ["index_name", args[1]]
        if command == "FT.CREATE":
            self.index_exists = True
            return "OK"
        if command == "FT.DROPINDEX":
            if not self.index_exists:
                raise ResponseError(self.index_missing_error)
            self.index_exists = False
            return "OK"
        if command == "FT.SEARCH":
            return self.search_results
        return "OK"

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_redis_store_ping_returns_true() -> None:
    store = RedisStore(FakeRedis())

    assert await store.ping() is True


@pytest.mark.anyio
async def test_redis_store_set_and_get_json() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)

    await store.set_json("session:1", {"message": "hello"})

    assert json.loads(redis.values["session:1"]) == {"message": "hello"}
    assert await store.get_json("session:1") == {"message": "hello"}


@pytest.mark.anyio
async def test_redis_store_save_and_get_session() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    session = SessionState(
        session_id="abc123",
        messages=[
            ChatMessage(role="user", content="你好"),
            ChatMessage(role="assistant", content="你好，我能帮你什么？"),
        ],
    )

    await store.save_session(session, expire_seconds=60)

    assert "session:abc123" in redis.values
    assert redis.expires["session:abc123"] == 60
    saved = await store.get_session("abc123")
    assert saved == session


@pytest.mark.anyio
async def test_redis_store_get_missing_session_returns_none() -> None:
    store = RedisStore(FakeRedis())

    assert await store.get_session("missing") is None


@pytest.mark.anyio
async def test_redis_store_save_and_get_memory_profile() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    profile = MemoryProfile(
        profile_id="default",
        preferences=["回答尽量简洁"],
        project_context=["项目使用 FastAPI 和 Redis"],
        constraints=["不要泄露 API Key"],
    )

    await store.save_memory_profile(profile)

    assert "memory:profile:default" in redis.values
    assert redis.expires["memory:profile:default"] is None
    saved = await store.get_memory_profile()
    assert saved == profile


@pytest.mark.anyio
async def test_redis_store_get_missing_memory_profile_returns_none() -> None:
    store = RedisStore(FakeRedis())

    assert await store.get_memory_profile() is None


@pytest.mark.anyio
async def test_redis_store_save_and_get_index_task() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    task = DocumentIndexTaskState(
        task_id="task-1",
        status="pending",
        file_name="notes.md",
        file_type="md",
        created_at="2026-06-14T00:00:00+00:00",
        updated_at="2026-06-14T00:00:00+00:00",
    )

    await store.save_index_task(task, expire_seconds=120)

    assert "task:index:task-1" in redis.values
    assert redis.expires["task:index:task-1"] == 120
    saved = await store.get_index_task("task-1")
    assert saved == task


@pytest.mark.anyio
async def test_redis_store_get_missing_index_task_returns_none() -> None:
    store = RedisStore(FakeRedis())

    assert await store.get_index_task("missing") is None


@pytest.mark.anyio
async def test_redis_store_ensure_vector_index_creates_missing_index() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )

    await store.ensure_vector_index(config)

    assert redis.commands[0] == ("FT.INFO", "idx:test")
    assert redis.commands[1] == (
        "FT.CREATE",
        "idx:test",
        "ON",
        "HASH",
        "PREFIX",
        "1",
        "doc:",
        "SCHEMA",
        "content",
        "TEXT",
        "metadata",
        "TEXT",
        "collection",
        "TAG",
        "embedding",
        "VECTOR",
        "HNSW",
        "6",
        "TYPE",
        "FLOAT32",
        "DIM",
        4,
        "DISTANCE_METRIC",
        "COSINE",
    )


@pytest.mark.anyio
async def test_redis_store_ensure_vector_index_handles_redis_8_missing_index_error() -> None:
    redis = FakeRedis()
    redis.index_missing_error = "SEARCH_INDEX_NOT_FOUND Index not found"
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )

    await store.ensure_vector_index(config)

    assert redis.index_exists is True


@pytest.mark.anyio
async def test_redis_store_vector_index_exists_returns_false_for_missing_index() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )

    assert await store.vector_index_exists(config) is False


@pytest.mark.anyio
async def test_redis_store_drop_vector_index_returns_true_when_index_exists() -> None:
    redis = FakeRedis()
    redis.index_exists = True
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )

    assert await store.drop_vector_index(config) is True
    assert redis.index_exists is False
    assert redis.commands[-1] == ("FT.DROPINDEX", "idx:test")


@pytest.mark.anyio
async def test_redis_store_drop_vector_index_returns_false_for_missing_index() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )

    assert await store.drop_vector_index(config) is False


@pytest.mark.anyio
async def test_redis_store_delete_document_chunks_only_deletes_document_prefix() -> None:
    redis = FakeRedis()
    redis.hashes["doc:abc:0"] = {"content": "a"}
    redis.hashes["doc:abc:1"] = {"content": "b"}
    redis.values["session:abc"] = "{}"
    redis.values["task:index:123"] = "{}"
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )

    keys = await store.list_document_chunk_keys(config)
    deleted_count = await store.delete_document_chunks(config, batch_size=1)

    assert keys == ["doc:abc:0", "doc:abc:1"]
    assert deleted_count == 2
    assert redis.hashes == {}
    assert "session:abc" in redis.values
    assert "task:index:123" in redis.values


@pytest.mark.anyio
async def test_redis_store_save_document_chunk_writes_hash_fields() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )
    chunk = DocumentChunk(
        chunk_id="abc:0",
        document_id="abc",
        content="agent rag redis",
        source="notes.md",
        chunk_index=0,
        start_char=0,
        end_char=15,
        metadata={"file_name": "notes.md", "file_type": "md"},
    )

    key = await store.save_document_chunk(chunk, [0.1, 0.2, 0.3, 0.4], index_config=config)

    assert key == "doc:abc:0"
    saved = redis.hashes["doc:abc:0"]
    assert saved["content"] == "agent rag redis"
    assert struct.unpack("<4f", saved["embedding"]) == pytest.approx((0.1, 0.2, 0.3, 0.4))
    metadata = json.loads(saved["metadata"])
    assert metadata["chunk_id"] == "abc:0"
    assert metadata["document_id"] == "abc"
    assert metadata["source"] == "notes.md"
    assert metadata["chunk_index"] == 0


@pytest.mark.anyio
async def test_redis_store_rejects_embedding_dimension_mismatch() -> None:
    store = RedisStore(FakeRedis())
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )
    chunk = DocumentChunk(
        chunk_id="abc:0",
        document_id="abc",
        content="agent rag redis",
        source="notes.md",
        chunk_index=0,
        start_char=0,
        end_char=15,
    )

    with pytest.raises(ValueError):
        await store.save_document_chunk(chunk, [0.1, 0.2], index_config=config)


@pytest.mark.anyio
async def test_index_document_chunks_embeds_and_saves_chunks() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    embedding_client = DeterministicEmbeddingClient(dimension=4)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )
    chunks = [
        DocumentChunk(
            chunk_id="abc:0",
            document_id="abc",
            content="first chunk",
            source="notes.md",
            chunk_index=0,
            start_char=0,
            end_char=11,
        ),
        DocumentChunk(
            chunk_id="abc:1",
            document_id="abc",
            content="second chunk",
            source="notes.md",
            chunk_index=1,
            start_char=10,
            end_char=22,
        ),
    ]

    keys = await index_document_chunks(
        chunks,
        embedding_client=embedding_client,
        redis_store=store,
        index_config=config,
    )

    assert keys == ["doc:abc:0", "doc:abc:1"]
    assert redis.index_exists is True
    assert redis.hashes["doc:abc:0"]["content"] == "first chunk"
    assert redis.hashes["doc:abc:1"]["content"] == "second chunk"


@pytest.mark.anyio
async def test_redis_store_search_document_chunks_runs_knn_search_and_parses_results() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )

    results = await store.search_document_chunks([0.1, 0.2, 0.3, 0.4], top_k=3, index_config=config)

    command = redis.commands[-1]
    assert command[:3] == (
        "FT.SEARCH",
        "idx:test",
        "*=>[KNN 3 @embedding $query_vector AS vector_distance]",
    )
    assert "PARAMS" in command
    assert "SORTBY" in command
    assert "RETURN" in command
    assert "DIALECT" in command
    assert results[0].key == "doc:abc:0"
    assert results[0].content == "agent rag redis"
    assert results[0].metadata["chunk_id"] == "abc:0"
    assert results[0].distance == pytest.approx(0.12)


@pytest.mark.anyio
async def test_redis_store_search_document_chunks_parses_resp3_dict_results() -> None:
    redis = FakeRedis()
    redis.search_results = {
        "total_results": 1,
        "results": [
            {
                "id": "doc:abc:0",
                "extra_attributes": {
                    "content": "agent rag redis",
                    "metadata": '{"chunk_id": "abc:0", "source": "notes.md"}',
                    "vector_distance": "0.12",
                },
                "values": [],
            }
        ],
    }
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )

    results = await store.search_document_chunks([0.1, 0.2, 0.3, 0.4], top_k=3, index_config=config)

    assert results[0].key == "doc:abc:0"
    assert results[0].content == "agent rag redis"
    assert results[0].metadata["source"] == "notes.md"
    assert results[0].distance == pytest.approx(0.12)


@pytest.mark.anyio
async def test_redis_store_search_document_chunks_rejects_invalid_top_k() -> None:
    store = RedisStore(FakeRedis())

    with pytest.raises(ValueError):
        await store.search_document_chunks([0.1, 0.2, 0.3, 0.4], top_k=0)


@pytest.mark.anyio
async def test_redis_store_search_document_chunks_filters_by_collection() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )

    await store.search_document_chunks(
        [0.1, 0.2, 0.3, 0.4], top_k=3, collection="resume", index_config=config
    )

    command = redis.commands[-1]
    assert command[2] == (
        "(@collection:{resume})=>[KNN 3 @embedding $query_vector AS vector_distance]"
    )


@pytest.mark.anyio
async def test_redis_store_save_document_chunk_writes_collection_tag() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    config = RedisVectorIndexConfig(
        index_name="idx:test",
        key_prefix="doc:",
        vector_field_name="embedding",
        content_field_name="content",
        metadata_field_name="metadata",
        dimension=4,
    )
    chunk = DocumentChunk(
        chunk_id="abc:0",
        document_id="abc",
        content="agent rag redis",
        source="resume.pdf",
        chunk_index=0,
        start_char=0,
        end_char=15,
    )

    await store.save_document_chunk(
        chunk, [0.1, 0.2, 0.3, 0.4], collection="resume", index_config=config
    )

    saved = redis.hashes["doc:abc:0"]
    assert saved["collection"] == "resume"
    assert json.loads(saved["metadata"])["collection"] == "resume"
