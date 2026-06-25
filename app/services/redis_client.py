import json
import math
import struct
from typing import Any

from redis import RedisError, ResponseError
from redis.asyncio import Redis

from app.core.config import settings
from app.models.document import DocumentChunk, DocumentIndexTaskState, DocumentSearchResult
from app.models.memory import MemoryProfile
from app.models.session import SessionState
from app.models.vector_index import RedisVectorIndexConfig


DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 24
DEFAULT_INDEX_TASK_TTL_SECONDS = 60 * 60 * 24
DEFAULT_MEMORY_PROFILE_ID = "default"
DEFAULT_COLLECTION = "default"
VECTOR_DISTANCE_FIELD_NAME = "vector_distance"

_TAG_SPECIAL_CHARS = set(",.<>{}[]\"':;!@#$%^&*()-+=~ ")


def _escape_redis_tag(value: str) -> str:
    return "".join(f"\\{char}" if char in _TAG_SPECIAL_CHARS else char for char in value)


class RedisStore:
    def __init__(self, client: Redis) -> None:
        self._client = client

    @classmethod
    def from_settings(cls) -> "RedisStore":
        client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
        )
        return cls(client)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except RedisError:
            return False

    async def set_json(
        self,
        key: str,
        value: dict[str, Any],
        *,
        expire_seconds: int | None = None,
    ) -> None:
        await self._client.set(key, json.dumps(value, ensure_ascii=False), ex=expire_seconds)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        raw_value = await self._client.get(key)
        if raw_value is None:
            return None
        return json.loads(raw_value)

    async def save_session(
        self,
        session: SessionState,
        *,
        expire_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> None:
        await self.set_json(
            self._session_key(session.session_id),
            session.model_dump(),
            expire_seconds=expire_seconds,
        )

    async def get_session(self, session_id: str) -> SessionState | None:
        data = await self.get_json(self._session_key(session_id))
        if data is None:
            return None
        return SessionState.model_validate(data)

    async def save_memory_profile(self, profile: MemoryProfile) -> None:
        await self.set_json(
            self._memory_profile_key(profile.profile_id),
            profile.model_dump(),
        )

    async def get_memory_profile(
        self,
        profile_id: str = DEFAULT_MEMORY_PROFILE_ID,
    ) -> MemoryProfile | None:
        data = await self.get_json(self._memory_profile_key(profile_id))
        if data is None:
            return None
        return MemoryProfile.model_validate(data)

    async def save_index_task(
        self,
        task: DocumentIndexTaskState,
        *,
        expire_seconds: int = DEFAULT_INDEX_TASK_TTL_SECONDS,
    ) -> None:
        await self.set_json(
            self._index_task_key(task.task_id),
            task.model_dump(),
            expire_seconds=expire_seconds,
        )

    async def get_index_task(self, task_id: str) -> DocumentIndexTaskState | None:
        data = await self.get_json(self._index_task_key(task_id))
        if data is None:
            return None
        return DocumentIndexTaskState.model_validate(data)

    async def ensure_vector_index(self, index_config: RedisVectorIndexConfig | None = None) -> None:
        config = index_config or settings.redis_vector_index
        if config.storage_type != "HASH":
            raise ValueError("Only HASH vector storage is supported")

        if await self.vector_index_exists(config):
            return

        await self._client.execute_command(
            "FT.CREATE",
            config.index_name,
            "ON",
            config.storage_type,
            "PREFIX",
            "1",
            config.key_prefix,
            "SCHEMA",
            config.content_field_name,
            "TEXT",
            config.metadata_field_name,
            "TEXT",
            config.collection_field_name,
            "TAG",
            config.vector_field_name,
            "VECTOR",
            config.algorithm,
            "6",
            "TYPE",
            config.data_type,
            "DIM",
            config.dimension,
            "DISTANCE_METRIC",
            config.distance_metric,
        )

    async def vector_index_exists(self, index_config: RedisVectorIndexConfig | None = None) -> bool:
        config = index_config or settings.redis_vector_index
        try:
            await self._client.execute_command("FT.INFO", config.index_name)
            return True
        except ResponseError as exc:
            if self._is_missing_index_error(exc):
                return False
            raise

    async def drop_vector_index(self, index_config: RedisVectorIndexConfig | None = None) -> bool:
        config = index_config or settings.redis_vector_index
        try:
            await self._client.execute_command("FT.DROPINDEX", config.index_name)
            return True
        except ResponseError as exc:
            if self._is_missing_index_error(exc):
                return False
            raise

    async def list_document_chunk_keys(
        self,
        index_config: RedisVectorIndexConfig | None = None,
        *,
        scan_count: int = 1000,
    ) -> list[str]:
        config = index_config or settings.redis_vector_index
        pattern = f"{config.key_prefix}*"
        return [
            str(key)
            async for key in self._client.scan_iter(match=pattern, count=scan_count)
        ]

    async def delete_document_chunks(
        self,
        index_config: RedisVectorIndexConfig | None = None,
        *,
        batch_size: int = 500,
    ) -> int:
        keys = await self.list_document_chunk_keys(index_config)
        deleted_count = 0
        for index in range(0, len(keys), batch_size):
            batch = keys[index : index + batch_size]
            if batch:
                deleted_count += int(await self._client.delete(*batch))
        return deleted_count

    async def save_document_chunk(
        self,
        chunk: DocumentChunk,
        embedding: list[float],
        *,
        collection: str = DEFAULT_COLLECTION,
        index_config: RedisVectorIndexConfig | None = None,
    ) -> str:
        config = index_config or settings.redis_vector_index
        key = self._document_chunk_key(chunk.chunk_id, config)
        metadata = {
            **chunk.metadata,
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "source": chunk.source,
            "chunk_index": chunk.chunk_index,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "collection": collection,
        }

        await self._client.hset(
            key,
            mapping={
                config.content_field_name: chunk.content,
                config.metadata_field_name: json.dumps(metadata, ensure_ascii=False),
                config.collection_field_name: collection,
                config.vector_field_name: self._embedding_to_float32_bytes(embedding, config.dimension),
            },
        )
        return key

    async def search_document_chunks(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        collection: str | None = None,
        index_config: RedisVectorIndexConfig | None = None,
    ) -> list[DocumentSearchResult]:
        if top_k <= 0:
            raise ValueError("top_k must be greater than 0")

        config = index_config or settings.redis_vector_index
        query_vector = self._embedding_to_float32_bytes(query_embedding, config.dimension)
        prefilter = (
            f"(@{config.collection_field_name}:{{{_escape_redis_tag(collection)}}})"
            if collection
            else "*"
        )
        knn_query = f"{prefilter}=>[KNN {top_k} @{config.vector_field_name} $query_vector AS {VECTOR_DISTANCE_FIELD_NAME}]"

        raw_results = await self._client.execute_command(
            "FT.SEARCH",
            config.index_name,
            knn_query,
            "PARAMS",
            "2",
            "query_vector",
            query_vector,
            "SORTBY",
            VECTOR_DISTANCE_FIELD_NAME,
            "RETURN",
            "3",
            config.content_field_name,
            config.metadata_field_name,
            VECTOR_DISTANCE_FIELD_NAME,
            "DIALECT",
            "2",
        )
        return self._parse_search_results(raw_results, config)

    def _session_key(self, session_id: str) -> str:
        return f"session:{session_id}"

    def _memory_profile_key(self, profile_id: str) -> str:
        return f"memory:profile:{profile_id}"

    def _index_task_key(self, task_id: str) -> str:
        return f"task:index:{task_id}"

    def _document_chunk_key(self, chunk_id: str, index_config: RedisVectorIndexConfig) -> str:
        return f"{index_config.key_prefix}{chunk_id}"

    def _embedding_to_float32_bytes(self, embedding: list[float], dimension: int) -> bytes:
        if len(embedding) != dimension:
            raise ValueError(f"embedding dimension mismatch: expected {dimension}, got {len(embedding)}")
        if any(not math.isfinite(value) for value in embedding):
            raise ValueError("embedding values must be finite numbers")
        return struct.pack(f"<{dimension}f", *embedding)

    def _parse_search_results(
        self,
        raw_results: Any,
        index_config: RedisVectorIndexConfig,
    ) -> list[DocumentSearchResult]:
        if not raw_results:
            return []
        if isinstance(raw_results, dict):
            return self._parse_search_result_dict(raw_results, index_config)

        results: list[DocumentSearchResult] = []
        for index in range(1, len(raw_results), 2):
            key = str(raw_results[index])
            fields = self._fields_to_dict(raw_results[index + 1])
            metadata = self._parse_metadata(fields.get(index_config.metadata_field_name))
            results.append(
                DocumentSearchResult(
                    key=key,
                    content=str(fields.get(index_config.content_field_name, "")),
                    metadata=metadata,
                    distance=float(fields.get(VECTOR_DISTANCE_FIELD_NAME, 0.0)),
                )
            )
        return results

    def _parse_search_result_dict(
        self,
        raw_results: dict[str, Any],
        index_config: RedisVectorIndexConfig,
    ) -> list[DocumentSearchResult]:
        results: list[DocumentSearchResult] = []
        for item in raw_results.get("results", []):
            fields = item.get("extra_attributes", {})
            metadata = self._parse_metadata(fields.get(index_config.metadata_field_name))
            results.append(
                DocumentSearchResult(
                    key=str(item.get("id", "")),
                    content=str(fields.get(index_config.content_field_name, "")),
                    metadata=metadata,
                    distance=float(fields.get(VECTOR_DISTANCE_FIELD_NAME, 0.0)),
                )
            )
        return results

    def _fields_to_dict(self, fields: list[Any]) -> dict[str, Any]:
        return {str(fields[index]): fields[index + 1] for index in range(0, len(fields), 2)}

    def _parse_metadata(self, raw_metadata: Any) -> dict[str, Any]:
        if raw_metadata is None:
            return {}
        if isinstance(raw_metadata, bytes):
            raw_metadata = raw_metadata.decode("utf-8")
        return json.loads(str(raw_metadata))

    def _is_missing_index_error(self, exc: ResponseError) -> bool:
        message = str(exc).lower()
        return "unknown index" in message or "index not found" in message
