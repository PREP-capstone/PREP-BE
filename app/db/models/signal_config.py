import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class SignalConfig(Base):
    """signal_config — 축별 점수 임계값. db_구축_설계서.md §3.3.1

    🔵 조회 주체는 판정엔진(런타임)이다. 오프라인 파이프라인은 이 테이블을 시딩만 하고
    읽지 않는다 — 축별 등급 산출과 최고값 채택이 모두 런타임에서 이루어지기 때문(§3.3.2).
    """

    __tablename__ = "signal_config"

    config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_versions.rule_version_id"), nullable=False
    )
    # 의료행위표현 / 개인정보민감도 / 광고표현위험
    axis: Mapped[str] = mapped_column(String, nullable=False)
    threshold_low: Mapped[int] = mapped_column(Integer, nullable=False)  # 점수 ≤ N → 낮음
    threshold_mid: Mapped[int] = mapped_column(Integer, nullable=False)  # 점수 ≤ M → 중간, 초과 시 높음
