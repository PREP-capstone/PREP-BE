"""verb_substitution 12행을 시딩한다 (2026-08-13 결정).

원 설계(룰_추출_기준_최종확정본.md §Stage C)는 "동사 목록: gate_keywords의
PROHIBITED_ACTION 키워드 재사용"이라고 했지만, 실제 적재된 값에는
"의료용으로 표시"·"모니터링"처럼 동사가 아닌 것이 섞여 있어 그대로 재사용할 수
없었다. 대신 같은 문서(§Stage C)가 이미 열거해둔 확정 목록을 그대로 옮긴다.

    진단단계(DIAGNOSIS): 진단하다, 검사하다, 판별하다, 측정하다(질환 맥락)
    치료단계(TREATMENT): 치료하다, 처방하다, 예방하다, 개선하다, 완화하다, 처치하다, 보정하다

이 11개 중 2개를 웰니스판단기준 0091-03 원문과 직접 대조해 제외했다.
- **예방**: IV.2.가 "만성질환을 **예방**하거나 관리에 도움을 주기 위한 앱" — PASS 예시
- **보정**: IV.1.나 "낙상 위험도 측정을 통해 **보행교정**이 가능하도록 도와주는 제품" — PASS 예시
목적어가 이미 질병명 자체("만성질환을 예방")라 noun_classes 제한으로 걸러낼 수 없어
목록에서 뺐다.

**측정**은 noun_classes를 생체지표 전용으로 좁혔다. 0091-03 IV.3(개인용건강관리제품과
의료기기 판단사례)이 "혈압을 측정하여 수치화하지 않고 그래프로 표시"는 PASS,
"고혈당 진단·치료 등을 위해 혈당값을 측정"·"위험수치 알람 기능"은 FAIL로 가른다 —
측정 자체가 아니라 수치 표시·알람 여부가 관건이라 텍스트 매칭으로 잡을 층위가
아니고, safe_text에 조건을 덧붙이는 방식으로 처리한다(generate_correction_rules.py
MEASURE_CAVEAT 참조).

약무 3개(조제·투약·복약지도)는 문서 확정 이후(2026-08-12 C안)의 결정이라 원 목록에
없어 추가했다. standalone=true — 명사 없이 동사 단독으로 risky_text가 된다.

data_difficulty·collection_difficulty와 같은 고정 기준표 패턴이다 — LLM 추출
대상이 아니라 직접 INSERT하고 rule_version에 묶지 않는다.

    python scripts/seed_verb_substitution.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):  # 한글 출력이 콘솔 코드페이지에 깨지지 않도록
    sys.stdout.reconfigure(encoding="utf-8")

from app.db.models import VerbSubstitution
from app.db.session import AsyncSessionLocal
from app.pipeline.article_ref import normalize_article

WELLNESS = "kr-mfds-wellness-0091-03-20260212"
MEDICAL_ACT = "kr-medical-act-20260407"
DEVICE_ACT = "kr-medical-device-act-20260701"
# 약사법은 usage=PENDING(파일 미확보) — 서지정보는 있으나 조문 번호를 확정 못해 비운다.
PHARM_ACT = "kr-pharmaceutical-affairs-act-20260621"

ROWS: list[dict] = [
    # ---- DIAGNOSIS (4) ----
    {
        "verb": "진단", "verb_category": "DIAGNOSIS", "safe_verb": "확인",
        "noun_classes": "질병명", "standalone": False,
        "legal_basis_doc": MEDICAL_ACT, "legal_basis_article": "제27조",
    },
    {
        "verb": "검사", "verb_category": "DIAGNOSIS", "safe_verb": "자가 측정",
        "noun_classes": "질병명", "standalone": False,
        "legal_basis_doc": WELLNESS, "legal_basis_article": "IV.1.가",
    },
    {
        "verb": "판별", "verb_category": "DIAGNOSIS", "safe_verb": "기록",
        "noun_classes": "질병명", "standalone": False,
        "legal_basis_doc": WELLNESS, "legal_basis_article": "IV.1.가",
    },
    {
        # 생체지표 전용 — 위 모듈 docstring의 IV.3 판단사례 참조
        "verb": "측정", "verb_category": "DIAGNOSIS", "safe_verb": "변화 추이 확인",
        "noun_classes": "생체지표", "standalone": False,
        "legal_basis_doc": WELLNESS, "legal_basis_article": "IV.3",
    },
    # ---- TREATMENT (5) — 예방·보정 제외 ----
    {
        "verb": "치료", "verb_category": "TREATMENT", "safe_verb": "관리",
        "noun_classes": "질병명", "standalone": False,
        "legal_basis_doc": WELLNESS, "legal_basis_article": "IV.2.가",
    },
    {
        "verb": "처방", "verb_category": "TREATMENT", "safe_verb": "안내",
        "noun_classes": "질병명", "standalone": False,
        "legal_basis_doc": WELLNESS, "legal_basis_article": "IV.2.나",
    },
    {
        "verb": "개선", "verb_category": "TREATMENT", "safe_verb": "향상 도움",
        "noun_classes": "질병명", "standalone": False,
        "legal_basis_doc": WELLNESS, "legal_basis_article": "IV.1.나",
    },
    {
        "verb": "완화", "verb_category": "TREATMENT", "safe_verb": "관리",
        "noun_classes": "질병명", "standalone": False,
        "legal_basis_doc": DEVICE_ACT, "legal_basis_article": "제2조",
    },
    {
        "verb": "처치", "verb_category": "TREATMENT", "safe_verb": "정보 제공",
        "noun_classes": "질병명", "standalone": False,
        "legal_basis_doc": WELLNESS, "legal_basis_article": "IV.2.가",
    },
    # ---- PHARM (3) — standalone, 명사와 조합하지 않음 ----
    {
        "verb": "조제", "verb_category": "PHARM",
        "safe_verb": "대체 표현 없음 — 약사 전속 업무이므로 기능 자체를 제외해야 함",
        "noun_classes": "", "standalone": True,
        # correction_rules.legal_basis_article은 NOT NULL이라 None을 못 넣는다.
        # 약사법(PENDING) 조문 번호를 아직 모른다는 뜻으로 빈 문자열을 쓴다 —
        # 파일이 확보되면 채워 넣을 자리표시자다.
        "legal_basis_doc": PHARM_ACT, "legal_basis_article": "",
    },
    {
        "verb": "투약", "verb_category": "PHARM", "safe_verb": "복용 기록",
        "noun_classes": "", "standalone": True,
        # correction_rules.legal_basis_article은 NOT NULL이라 None을 못 넣는다.
        # 약사법(PENDING) 조문 번호를 아직 모른다는 뜻으로 빈 문자열을 쓴다 —
        # 파일이 확보되면 채워 넣을 자리표시자다.
        "legal_basis_doc": PHARM_ACT, "legal_basis_article": "",
    },
    {
        "verb": "복약지도", "verb_category": "PHARM", "safe_verb": "복약 정보 제공",
        "noun_classes": "", "standalone": True,
        # correction_rules.legal_basis_article은 NOT NULL이라 None을 못 넣는다.
        # 약사법(PENDING) 조문 번호를 아직 모른다는 뜻으로 빈 문자열을 쓴다 —
        # 파일이 확보되면 채워 넣을 자리표시자다.
        "legal_basis_doc": PHARM_ACT, "legal_basis_article": "",
    },
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        inserted = updated = 0
        for raw_row in ROWS:
            row = dict(raw_row)
            row["legal_basis_article"] = normalize_article(row["legal_basis_article"])

            existing = await session.get(VerbSubstitution, row["verb"])
            if existing is None:
                session.add(VerbSubstitution(**row))
                inserted += 1
                continue

            changed = any(getattr(existing, key) != value for key, value in row.items() if key != "verb")
            if changed:
                for key, value in row.items():
                    if key != "verb":
                        setattr(existing, key, value)
                updated += 1

        await session.commit()
        print(f"verb_substitution: {inserted}행 신규 / {updated}행 갱신 (총 {len(ROWS)}행)")


if __name__ == "__main__":
    asyncio.run(seed())
