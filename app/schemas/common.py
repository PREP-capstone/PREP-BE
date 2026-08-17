"""판정 API 여러 곳에서 공유하는 응답 스키마.

여기 정의한 타입은 gate/regulatory-risk/correction-candidates 세 API가 전부 참조한다.
각자 파일에 따로 정의하면 필드명이 갈라져도 아무도 모르게 깨지므로(예: article vs
legal_article), 한 곳에서만 정의하고 다 같이 import해서 쓴다.
"""

from pydantic import BaseModel


class LegalBasis(BaseModel):
    """근거 조문 1건. document_id/article은 RAG evidence_documents/chunks 조회 키와
    형식이 같아야 한다 — db_구축_설계서.md §1.5.1 정규화 규칙 참조.

    quote는 RAG rag/chunks/lookup 연동 전까지는 None — 룰 테이블에는 조문 원문이
    저장돼 있지 않다(이슈 4 "RAG 근거 연결"에서 채워짐).
    """

    document_id: str
    article: str
    quote: str | None = None
