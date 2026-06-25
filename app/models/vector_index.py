from typing import Literal

from pydantic import BaseModel, Field


VectorAlgorithm = Literal["FLAT", "HNSW"]
VectorDataType = Literal["FLOAT32", "FLOAT64"]
VectorDistanceMetric = Literal["COSINE", "L2", "IP"]
VectorStorageType = Literal["HASH", "JSON"]


class RedisVectorIndexConfig(BaseModel):
    index_name: str = Field(min_length=1)
    key_prefix: str = Field(min_length=1)
    storage_type: VectorStorageType = "HASH"
    vector_field_name: str = Field(min_length=1)
    content_field_name: str = Field(min_length=1)
    metadata_field_name: str = Field(min_length=1)
    collection_field_name: str = "collection"
    dimension: int = Field(gt=0)
    data_type: VectorDataType = "FLOAT32"
    algorithm: VectorAlgorithm = "HNSW"
    distance_metric: VectorDistanceMetric = "COSINE"

    @property
    def key_pattern(self) -> str:
        return f"{self.key_prefix}*"
