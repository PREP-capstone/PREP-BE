"""판정 API 여러 곳에서 공유하는 응답 스키마.

여기 정의한 타입은 gate/regulatory-risk/correction-candidates 세 API가 전부 참조한다.
각자 파일에 따로 정의하면 필드명이 갈라져도 아무도 모르게 깨지므로(예: article vs
legal_article), 한 곳에서만 정의하고 다 같이 import해서 쓴다.
"""

from typing import Literal

from pydantic import BaseModel, Field


class HealthDataItemInput(BaseModel):
    """건강/검진 데이터 항목 1건. analysis-sessions API(health-data 등록)와
    judgement API(/gate 등)가 동일한 입력을 주고받으므로 한 곳에서만 정의한다 —
    각자 따로 정의하면 source 허용값·길이 제약이 갈라져도 아무도 모르게 깨진다.
    """

    name: str = Field(min_length=1, max_length=100)
    data_type: str = Field(min_length=1, max_length=50)
    unit: str | None = Field(default=None, max_length=50)
    source: Literal["user_input", "device_sync", "os_sync"]
    is_sensitive: bool = False
    item_code: str | None = Field(default=None, max_length=80)  # data_sensitivity.item_code FK


class ApiResponse(BaseModel):
    """RAG 문서/청크 조회 API(rag.py)가 공유하는 응답 envelope.

    judgement.py는 이 envelope을 쓰지 않는다. /rag/search는 성공 응답만 명세서에
    고정된 순수 배열 형태(별도 계약)라 제외하고, 에러 응답은 다른 rag.py 엔드포인트와
    동일하게 이 envelope을 따른다.
    """

    isSuccess: bool
    code: str
    message: str
    result: object


class LegalBasis(BaseModel):
    """근거 조문 1건. document_id/article은 RAG evidence_documents/chunks 조회 키와
    형식이 같아야 한다 — db_구축_설계서.md §1.5.1 정규화 규칙 참조.

    quote는 RAG rag/chunks/lookup 연동 전까지는 None — 룰 테이블에는 조문 원문이
    저장돼 있지 않다(이슈 4 "RAG 근거 연결"에서 채워짐).
    """

    document_id: str
    article: str
    quote: str | None = None
