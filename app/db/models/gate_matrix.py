import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class GateMatrix(Base):

    __tablename__ = "gate_matrix"

    matrix_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_versions.rule_version_id"), nullable=False
    )
    data_type: Mapped[str] = mapped_column(String, nullable=False)  # 라이프스타일 / 생체지표
    function_type: Mapped[str] = mapped_column(String, nullable=False)  # 단순기록 / 비교·추이분석 / 수치예측·진단
    verdict: Mapped[str] = mapped_column(String, nullable=False)  # PASS / CONDITIONAL / FAIL
    exemption_note: Mapped[str | None] = mapped_column(String, nullable=True)
    # 수동입력 / 기기연동 / OS연동 — 매트릭스 축 확장이 아니라 침습적 하드체크 오버라이드 전용.
    # 하드체크에 해당하지 않는 일반 조합은 비워둔다 (db_구축_설계서.md §3.2)
    acquire_method: Mapped[str | None] = mapped_column(String, nullable=True)
    # 아래 2개는 verdict=FAIL일 때만 채운다. 문구 작성 주체 미정(D-2)이라 현재는 항상 None.
    avoidance_redesign: Mapped[str | None] = mapped_column(String, nullable=True)
    avoidance_certification: Mapped[str | None] = mapped_column(String, nullable=True)
    # correction_rules(§3.3)와 동일 패턴 — 평문 2컬럼. 원문 인용은 저장하지 않고
    # RAG evidence_chunks.section_id와 legal_basis_article을 조인해 조회한다 (§1.5.1)
    legal_basis_doc: Mapped[str | None] = mapped_column(String, nullable=True)
    legal_basis_article: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_code: Mapped[str | None] = mapped_column(String, nullable=True)  # TODO: GATE01_ENG01~02 연계 코드 미확정
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
