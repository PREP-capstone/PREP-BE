from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class VerbSubstitution(Base):
    """verb_substitution — correction_rules 조합 생성용 동사·안전표현 사전.

    법령 문서에서 추출하는 대상이 아니라 고정 기준표다(data_difficulty·
    collection_difficulty와 같은 패턴 — LLM 추출 없이 직접 INSERT, rule_version에
    묶지 않는다).

    원 설계(룰_추출_기준_최종확정본.md §Stage C)는 "동사 목록: gate_keywords의
    PROHIBITED_ACTION 키워드 재사용"이라고 했으나, 실제 적재 데이터에는
    "의료용으로 표시"·"모니터링"처럼 동사가 아닌 값이 섞여 있어 그대로 재사용할 수
    없었다. 문서가 이미 확정한 동사 목록을 이 테이블에 못박고(2026-08-13),
    gate_keywords는 계속 게이트 판정 전용으로 둔다 — 목적이 다른 두 어휘 사전이다.
    """

    __tablename__ = "verb_substitution"

    verb: Mapped[str] = mapped_column(String, primary_key=True)
    verb_category: Mapped[str] = mapped_column(String, nullable=False)  # DIAGNOSIS/TREATMENT/PHARM
    safe_verb: Mapped[str] = mapped_column(String, nullable=False)
    # 파이프(|)로 다중 표기 가능. standalone=true면 빈 문자열(명사와 조합하지 않음).
    noun_classes: Mapped[str] = mapped_column(String, nullable=False, default="")
    # 명사 없이 동사 단독으로 risky_text가 되는가 (약무행위: 조제/투약/복약지도)
    standalone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    legal_basis_doc: Mapped[str | None] = mapped_column(String, nullable=True)
    legal_basis_article: Mapped[str | None] = mapped_column(String, nullable=True)
