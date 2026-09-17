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

    merged: list[dict] = []
    emitted_categories: set[str] = set()
    for index, section in enumerate(sections):
        merged.append(section)
        current_category = section.get("category")
        next_category = sections[index + 1].get("category") if index + 1 < len(sections) else None
        if current_category != next_category and current_category in grouped:
            merged.extend(grouped[current_category])
            emitted_categories.add(current_category)

    # sections에 아예 없던 category(예: 오타, 혹은 그 카테고리 필드를 하나도 안 보낸
    # 요청)로 지정된 custom_fields는 자리를 못 찾으므로 문서 맨 끝에 붙인다.
    for category, items in grouped.items():
        if category not in emitted_categories:
            merged.extend(items)

    return merged
