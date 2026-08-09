"""판정엔진(런타임)이 소비하는 고정 기준표 3종을 시딩한다.

값의 원본은 판정_기준값_확정표.md(v1.0) §A-1·§A-2·§A-3의 INSERT문이다.

- signal_config          — 축별 점수 임계값 (§A-1, db_구축_설계서.md §3.3.1)
- data_difficulty        — D축 점수표 (§A-2, §3.4)
- collection_difficulty  — S축 점수표 (§A-3, §3.4)

세 테이블 모두 LLM 추출 대상이 아니라 확정된 기준표를 그대로 INSERT하는 대상이다.
⚠️ **오프라인 파이프라인은 이 값들을 읽지 않는다.** 축별 등급 산출·D×S 곱셈·최고값 채택은
전부 런타임(판정엔진) 범위다 (§3.3.2). 여기서는 구축·시딩까지만 담당한다.

재실행해도 안전하다(있으면 갱신, 없으면 삽입).

    python scripts/seed_reference_tables.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import CollectionDifficulty, DataDifficulty, RuleVersion, SignalConfig
from app.db.session import AsyncSessionLocal

# §3.3.1 임계값 확정 (2026-07-26 최종) — 3축 모두 동일. 0~1=낮음 / 2=중간 / 3=높음
SIGNAL_CONFIG_ROWS = [
    {"axis": "의료행위표현", "threshold_low": 1, "threshold_mid": 2},
    {"axis": "개인정보민감도", "threshold_low": 1, "threshold_mid": 2},
    {"axis": "광고표현위험", "threshold_low": 1, "threshold_mid": 2},
]

# §3.4 D축 — 5/10은 임상·진료 2차 구축 시 재사용 예정이라 지금은 2종만 넣는다.
DATA_DIFFICULTY_ROWS = [
    {"data_type": "라이프스타일", "weight": 1},
    {"data_type": "생체지표", "weight": 3},
]

# §3.4 S축
COLLECTION_DIFFICULTY_ROWS = [
    {"method": "수동입력", "weight": 1},
    {"method": "OS연동", "weight": 2},
    {"method": "기기연동", "weight": 4},
    {"method": "기관연동", "weight": 10},
]


async def _signal_config_rule_version(session) -> RuleVersion:
    """signal_config 전용 active rule_version을 확보한다.

    publish.py는 Stage별(GateKeyword/GateMatrix/CorrectionRule) 조인으로 deprecate 범위를
    좁히므로, 여기서 만든 버전은 파이프라인 publish에 끌려가지 않는다 — Stage 독립 lineage와
    같은 원리다.
    """
    existing = await session.scalar(
        select(RuleVersion)
        .join(SignalConfig, SignalConfig.rule_version_id == RuleVersion.rule_version_id)
        .where(RuleVersion.status == "active")
        .limit(1)
    )
    if existing:
        return existing

    version_count = len((await session.scalars(select(RuleVersion.rule_version_id))).all())
    rule_version = RuleVersion(version=f"v0.{version_count + 1}", status="active")
    session.add(rule_version)
    await session.flush()
    return rule_version


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        rule_version = await _signal_config_rule_version(session)

        for row in SIGNAL_CONFIG_ROWS:
            config = await session.scalar(
                select(SignalConfig).where(
                    SignalConfig.rule_version_id == rule_version.rule_version_id,
                    SignalConfig.axis == row["axis"],
                )
            )
            if config is None:
                session.add(SignalConfig(rule_version_id=rule_version.rule_version_id, **row))
            else:
                config.threshold_low = row["threshold_low"]
                config.threshold_mid = row["threshold_mid"]

        for row in DATA_DIFFICULTY_ROWS:
            existing = await session.get(DataDifficulty, row["data_type"])
            if existing is None:
                session.add(DataDifficulty(**row))
            else:
                existing.weight = row["weight"]

        for row in COLLECTION_DIFFICULTY_ROWS:
            existing = await session.get(CollectionDifficulty, row["method"])
            if existing is None:
                session.add(CollectionDifficulty(**row))
            else:
                existing.weight = row["weight"]

        await session.commit()

        print(f"signal_config          : {len(SIGNAL_CONFIG_ROWS)}행 (rule_version={rule_version.version})")
        print(f"data_difficulty        : {len(DATA_DIFFICULTY_ROWS)}행")
        print(f"collection_difficulty  : {len(COLLECTION_DIFFICULTY_ROWS)}행")


if __name__ == "__main__":
    asyncio.run(seed())
