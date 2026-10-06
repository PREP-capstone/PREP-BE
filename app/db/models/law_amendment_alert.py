import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class LawAmendmentAlert(Base):
    """law_amendment_alert — scripts/check_law_amendments.py가 감지한 법령 개정 알림.

    점검 스크립트 결과를 콘솔에만 찍으면 누가 돌려보기 전엔 아무도 모른다. 여기 남겨두고
    /admin/rules 페이지 배너로 띄워서, 평소 검수하러 들어가는 화면에서 바로 알 수 있게 한다.

    relevance가 핵심이다 — 법이 개정돼도 우리 룰이 인용하는 조문이 아니면 대응할 게 없다.
    실측(2026-09-27): 감지된 개정 4건(의료기기법·의료법·약사법·개인정보 보호법) 전부
    우리 인용 조문(의료법 제27조 / 의료기기법 제2조 / 약사법 제2·23·24·44조)과 겹치지
    않았다. 교집합을 안 내면 이런 무관한 알림이 배너를 채워 정작 중요한 걸 묻어버린다.
    """

    __tablename__ = "law_amendment_alert"
    # 점검 스크립트를 여러 번 돌려도 같은 개정건이 중복으로 쌓이지 않게 한다.
    __table_args__ = (
        UniqueConstraint(
            "law_title", "latest_promulgation_no", name="uq_law_amendment_alert_law_promulgation"
        ),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    law_title: Mapped[str] = mapped_column(String, nullable=False)
    # 룰 테이블의 legal_basis_doc과 대조할 RAG document_id. 매핑을 못 찾으면 NULL —
    # 이 경우 교집합을 못 내므로 relevance는 보수적으로 related로 둔다(사람이 확인).
    document_id: Mapped[str | None] = mapped_column(String, nullable=True)

    known_promulgation_no: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_promulgation_no: Mapped[int] = mapped_column(Integer, nullable=False)
    known_effective_date: Mapped[str] = mapped_column(String, nullable=False)
    latest_effective_date: Mapped[str] = mapped_column(String, nullable=False)

    # [{"조문번호", "조문제목", "조문시행일자", "본문"}] — 본문 API의 조문변경여부=Y 결과
    changed_articles: Mapped[list] = mapped_column(JSON, nullable=False)
    # changed_articles 중 우리 룰(gate_matrix/correction_rules)이 실제로 인용 중인 조문
    related_articles: Mapped[list] = mapped_column(JSON, nullable=False)
    # 우리가 인용하는데 현행 법령에는 없는 조문 번호 — 삭제·이동됐다는 뜻이고,
    # 해당 룰은 legal_basis_article 조인이 깨져 근거를 못 찾는 상태다.
    missing_citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    relevance: Mapped[str] = mapped_column(String, nullable=False)  # related / unrelated
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")  # open / resolved / dismissed

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
