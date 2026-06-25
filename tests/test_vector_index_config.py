import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.vector_index import RedisVectorIndexConfig


def test_settings_builds_default_redis_vector_index_config() -> None:
    config = Settings().redis_vector_index

    assert config.index_name == "idx:docs"
    assert config.key_prefix == "doc:"
    assert config.key_pattern == "doc:*"
    assert config.storage_type == "HASH"
    assert config.vector_field_name == "embedding"
    assert config.dimension == 1536
    assert config.data_type == "FLOAT32"
    assert config.algorithm == "HNSW"
    assert config.distance_metric == "COSINE"


def test_settings_allows_vector_dimension_override() -> None:
    config = Settings(redis_vector_dimension=768).redis_vector_index

    assert config.dimension == 768


def test_vector_index_config_rejects_invalid_dimension() -> None:
    with pytest.raises(ValidationError):
        RedisVectorIndexConfig(
            index_name="idx:docs",
            key_prefix="doc:",
            vector_field_name="embedding",
            content_field_name="content",
            metadata_field_name="metadata",
            dimension=0,
        )
