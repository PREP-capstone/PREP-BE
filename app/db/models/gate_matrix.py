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
    risk_code: Mapped[str | None] = mapped_column(String, nullable=True)  # TODO: GATE01_ENG01~02 연계 코드 미확정
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
