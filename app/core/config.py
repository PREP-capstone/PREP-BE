from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    database_url: str
    redis_url: str
    analysis_ttl_seconds: int = 1800
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536
    rag_retrieval_top_k: int = 5
    chroma_persist_directory: str = "data/chroma"
    chroma_collection_name: str = "evidence_chunks"
    category_model_dir: str = "data/models/best_healthcare_model_2line"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
