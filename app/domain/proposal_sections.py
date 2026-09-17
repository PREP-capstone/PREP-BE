"""제안서 렌더링용 섹션 병합 (프론트 요청 v6, 2026-09-11).

`POST /{proposal_id}/complete`가 받은 custom_fields(고정 field_key가 없는 자유
서술형 추가 항목)를 원래 sections 목록에 끼워 넣는다 -- "해당 category 섹션의
맨 마지막에 별도 문단으로 추가"라는 요구를 만족시키려면 sections 안에서 같은
category가 어디서 끝나는지 알아야 하므로, 이 함수가 유일하게 그 경계를 계산한다.
proposal_pdf.py/proposal_docx.py 양쪽 렌더러가 이 결과를 그대로 받아 쓴다 --
렌더러 쪽은 "field_key가 없는 TEXT 섹션"으로만 보여 별도 분기가 필요 없다.

sections의 각 dict는 최소 field_key/label/field_type/value/category를 가져야
한다(app/api/proposals.py의 complete_proposal이 DB 조회로 category까지 채워
Redis에 저장한다 -- §3.1 참고). category가 sections 어디에도 없으면(예: 프론트가
아직 반영 안 된 예전 클라이언트가 보낸 요청, 혹은 잘못된 category 문자열) 문서
맨 끝에 그대로 덧붙인다 -- 자리 자체가 사라지는 것보다는 안전하다.
"""

from __future__ import annotations

from collections import defaultdict


def merge_custom_fields(sections: list[dict], custom_fields: list[dict]) -> list[dict]:
    if not custom_fields:
        return sections

    grouped: dict[str, list[dict]] = defaultdict(list)
    for custom_field in custom_fields:
        grouped[custom_field["category"]].append(
            {
                "field_key": None,
                "label": custom_field["label"],
                "field_type": "TEXT",
                "value": custom_field["value"],
                "category": custom_field["category"],
            }
        )

    # category별 "진짜 마지막 등장 인덱스"를 먼저 계산한다 -- 코드 리뷰로 확인된
    # 회귀(2026-09-17): 같은 category를 가진 section이 sections 안에서 서로 떨어진
    # 여러 블록으로 나뉘어 있으면(complete_proposal은 프론트가 보낸 순서를 그대로
    # 신뢰하므로 실제로 도달 가능하다) "인접 블록 경계마다 삽입" 방식은 매번
    # 끼워 넣어 같은 custom_field가 문서에 중복 출력됐다. "마지막 등장 위치 하나"만
    # 미리 확정해두면 중복이 구조적으로 불가능해지고, "해당 category 필드들 중
    # 마지막 것 바로 다음"이라는 문서(§5.3.1) 그대로의 위치에도 항상 맞는다 --
    # 예전 방식은 첫 블록 끝에서 멈추면 이 계약과도 어긋났다.
    last_index_by_category: dict[str | None, int] = {}
    for index, section in enumerate(sections):
        last_index_by_category[section.get("category")] = index

    merged: list[dict] = []
    for index, section in enumerate(sections):
        merged.append(section)
        category = section.get("category")
        if index == last_index_by_category[category] and category in grouped:
            merged.extend(grouped[category])

    # sections에 아예 없던 category(예: 오타, 혹은 그 카테고리 필드를 하나도 안 보낸
    # 요청)로 지정된 custom_fields는 자리를 못 찾으므로 문서 맨 끝에 붙인다.
    for category, items in grouped.items():
        if category not in last_index_by_category:
            merged.extend(items)

    return merged
