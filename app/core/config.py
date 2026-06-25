from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.vector_index import RedisVectorIndexConfig


class Settings(BaseSettings):
    app_name: str = "AI Resume Job Agent"
    app_env: str = "development"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_allow_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]

    llm_provider: str = "deepseek"
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 1

    embedding_provider: str = "fake"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str = ""
    embedding_dimensions: int = 0
    embedding_timeout_seconds: float = 30.0
    embedding_max_retries: int = 1

    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_socket_timeout_seconds: float = 2.0
    redis_vector_index_name: str = "idx:docs"
    redis_vector_key_prefix: str = "doc:"
    redis_vector_storage_type: str = "HASH"
    redis_vector_field_name: str = "embedding"
    redis_vector_content_field_name: str = "content"
    redis_vector_metadata_field_name: str = "metadata"
    redis_vector_dimension: int = 1536
    redis_vector_data_type: str = "FLOAT32"
    redis_vector_algorithm: str = "HNSW"
    redis_vector_distance_metric: str = "COSINE"

    document_index_queue_name: str = "document-index"
    document_index_job_timeout_seconds: int = 300
    document_index_result_ttl_seconds: int = 3600
    document_index_failure_ttl_seconds: int = 86400

    agent_checkpoint_backend: str = "local_file"
    agent_checkpoint_path: str = "data/checkpoints/agent_checkpoints.pkl"

    mysql_url: str = (
        "mysql+pymysql://agent_reader:agent_reader_password"
        "@127.0.0.1:3306/personal_agent"
    )
    mysql_connect_timeout_seconds: float = 3.0
    mysql_query_timeout_seconds: float = 5.0
    mysql_allowed_tables: list[str] = ["job_applications", "application_events"]
    mysql_default_limit: int = 50
    mysql_max_limit: int = 100

    pdf_ocr_enabled: bool = True
    pdf_ocr_provider: str = "paddleocr"
    pdf_text_layer_min_chars: int = 20
    pdf_ocr_dpi: int = 200
    pdf_ocr_language: str = "ch"
    pdf_ocr_enable_seal: bool = True
    pdf_ocr_max_pages: int = 50
    pdf_ocr_api_base_url: str = ""
    pdf_ocr_api_key: str = ""
    pdf_ocr_api_model: str = "paddleocr-vl"
    pdf_ocr_timeout_seconds: float = 60.0

    rerank_provider: str = "identity"
    rerank_base_url: str = "https://api.siliconflow.cn/v1"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_api_key: str = ""
    rerank_candidate_count: int = 20
    rerank_timeout_seconds: float = 30.0

    trace_enabled: bool = True
    trace_path: str = "data/traces/traces.jsonl"
    trace_max_recent: int = 100

    query_rewrite_provider: str = "llm"
    query_rewrite_max_tokens: int = 120

    # MCP (Model Context Protocol) client. Disabled by default so the project
    # runs unchanged without any external MCP server configured. When enabled,
    # external MCP server tools are exposed to the LLM as extra function tools.
    mcp_enabled: bool = False
    mcp_config_path: str = "data/mcp/servers.json"
    mcp_tool_timeout_seconds: float = 30.0
    mcp_max_tools: int = 32

    @property
    def redis_vector_index(self) -> RedisVectorIndexConfig:
        return RedisVectorIndexConfig(
            index_name=self.redis_vector_index_name,
            key_prefix=self.redis_vector_key_prefix,
            storage_type=self.redis_vector_storage_type,
            vector_field_name=self.redis_vector_field_name,
            content_field_name=self.redis_vector_content_field_name,
            metadata_field_name=self.redis_vector_metadata_field_name,
            dimension=self.redis_vector_dimension,
            data_type=self.redis_vector_data_type,
            algorithm=self.redis_vector_algorithm,
            distance_metric=self.redis_vector_distance_metric,
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
