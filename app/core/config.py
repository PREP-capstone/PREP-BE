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
    # False면 LLM 응답 캐시(correction_llm.py 1시간, proposal_llm.py 10분)를 읽지도 쓰지도
    # 않는다 — scripts/eval_reliability.py의 반복 측정용. 켜둔 채로 같은 입력을 10번 돌리면
    # 두 번째부터 캐시 히트라 LLM이 실제로 흔들리는지와 무관하게 "10/10 일치"가 나온다.
    # trend_client.py(외부 데이터) 캐시는 이 설정과 무관 — "같은 기준 시점"을 고정해주는
    # 역할이라 측정 중에도 켜두는 게 맞다.
    llm_response_cache_enabled: bool = True
    rag_retrieval_top_k: int = 5
    chroma_persist_directory: str = "data/chroma"
    chroma_collection_name: str = "evidence_chunks"
    cors_allow_origins: str = "https://prepwell.shop,https://prep-fe.vercel.app,https://prep-fe-phi.vercel.app"
    cors_allow_origin_regex: str = r"http://(localhost|127\.0\.0\.1):[0-9]+"
    # 2026-08-29 ONNX Runtime 백엔드로 교체 — app/domain/category_classifier.py 참고.
    # category_model_dir는 PREP-AI release(category_classifier_onnx/) 압축 해제 경로.
    category_model_dir: str = "data/models/category_classifier_onnx"
    category_model_file: str = "model_quantized.onnx"
    category_model_backend: str = "onnx"
    naver_client_id: str = ""
    naver_client_secret: str = ""
    public_data_service_key: str = ""
    kstartup_api_url: str = "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"
    bizinfo_api_key: str = ""
    bizinfo_api_url: str = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
    funding_fetch_limit: int = 100
    funding_request_timeout_seconds: float = 8.0
    startup_plus_project_url: str = "https://www.startup-plus.kr/project"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
