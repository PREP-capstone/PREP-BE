"""무면허 약무행위 키워드 화이트리스트 (약사법 근거, db_구축_설계서.md §1.5 LAW-PHARM-01).

이 목록은 두 곳에서 함께 쓰인다 — 어긋나면 시드와 파이프라인 산출물이 달라지므로 한곳에 둔다.
- `scripts/seed_pharmacy_keywords.py`: gate_keywords에 시딩할 키워드
- `app/pipeline/nodes/validate.py`: FAIL_CONFIRMED 인정 범위 판단

**왜 화이트리스트인가**: C안(2026-08-12)으로 약무행위는 weight=4 + FAIL_CONFIRMED로
regulatory_score 3점을 받는다. 그런데 검증에서 이를 `PROHIBITED_ACTION AND weight>=4`로
넓게 허용했더니, LLM이 "자가 측정"·"진단·치료" 같은 표현까지 FAIL_CONFIRMED로 발급해
적재분 전부가 3점(높음)으로 쏠렸다. 약무행위에만 예외를 주도록 범위를 좁힌다.
"""

PHARMACY_ACTION_KEYWORDS: tuple[str, ...] = ("처방", "조제", "복약지도", "투약")


def is_pharmacy_action(keyword: str | None) -> bool:
    """키워드가 약무행위를 가리키는지 판단한다.

    완전 일치가 아니라 포함 관계로 본다 — 실제 조문에서는 "맞춤형 영양제 처방"처럼
    복합어로 등장하고, 이런 표현을 잡는 것이 애초에 약무 키워드를 시딩한 이유이기 때문이다.
    """
    if not keyword:
        return False
    normalized = keyword.replace(" ", "")
    return any(action in normalized for action in PHARMACY_ACTION_KEYWORDS)
