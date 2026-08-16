from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class DataDifficulty(Base):
    """data_difficulty — D축 점수표. db_구축_설계서.md §3.4

    LLM 추출 대상이 아니라 고정 기준표를 직접 INSERT한다.
    D×S 곱셈·등급 판정은 런타임(판정엔진) 범위이므로 여기에 구현하지 않는다.
    """

    __tablename__ = "data_difficulty"

    data_type: Mapped[str] = mapped_column(String, primary_key=True)  # 라이프스타일 / 생체지표
    weight: Mapped[int] = mapped_column(Integer, nullable=False)  # 라이프스타일=1 / 생체지표=3


class CollectionDifficulty(Base):
    """collection_difficulty — S축 점수표. db_구축_설계서.md §3.4"""

    __tablename__ = "collection_difficulty"

    method: Mapped[str] = mapped_column(String, primary_key=True)  # 수동입력/OS연동/기기연동/기관연동
    weight: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 / 2 / 4 / 10
