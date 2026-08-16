"""[8] rule_versions 발행 노드.

**누적 발행(B안, 2026-08-13)**: 새 버전은 기존 active 버전의 행을 **승계(복사)한 뒤** 이번
draft를 얹는다. 예전에는 이번 draft만 담은 버전을 새로 만들고 기존 active를 deprecated로
내려서, 문서를 한 건씩 투입할 때마다 직전 문서의 룰이 통째로 비활성화됐다.

불변식은 그대로다.
- Stage당 active 버전은 **항상 유일**하다 (조회 쪽 `status='active'` 필터를 고칠 필요 없음)
- Stage 간 lineage는 **독립**이다 (A는 v0.x, B는 v0.y로 서로 다른 버전을 갖는다)

**derived_from_keyword_id 재연결 (D-12, 2026-08-14)**: Stage A 행을 승계 복사하면
keyword_id(PK)가 새로 발급된다. 그대로 두면 correction_rules.derived_from_keyword_id가
승계 이전(곧 deprecated될) 키워드 행을 계속 가리키게 된다 — FK 자체는 안 깨지지만
"왜 이 점수인지"를 추적할 때 최신 active 근거를 잃는다. Stage A를 승계할 때는
old_keyword_id → new_keyword_id 매핑을 만들어 같은 트랜잭션 안에서 correction_rules를
함께 갱신한다.
"""

import uuid

from sqlalchemy import select, update

from app.db.models import CorrectionRule, GateKeyword, GateMatrix, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.state import ExtractedDraft, PipelineState

_STAGE_MODEL = {"A": GateKeyword, "B": GateMatrix, "C": CorrectionRule}


async def publish(state: PipelineState) -> dict:
    drafts = state["drafts"]
    if not drafts:
        # 발행할 draft가 없으면 새 버전을 만들지 않음
        return {"rule_version_id": state.get("rule_version_id")}

    drafts_by_stage: dict[str, list[ExtractedDraft]] = {}
    for draft in drafts:
        drafts_by_stage.setdefault(draft["stage"], []).append(draft)

    async with AsyncSessionLocal() as session:
        latest_rule_version_id = None

        for stage, stage_drafts in drafts_by_stage.items():
            model = _STAGE_MODEL[stage]

            # 승계 대상은 deprecate하기 **전에** 읽어둔다.
            active_version_ids = await _active_version_ids_for_stage(session, model)
            inherited_rows = await _rows_of_versions(session, model, active_version_ids)

            count_result = await session.execute(select(RuleVersion))
            version_number = len(count_result.scalars().all()) + 1
            new_version = RuleVersion(version=f"v0.{version_number}", status="active")
            session.add(new_version)
            await session.flush()  # rule_version_id 확보

            keyword_id_remap: dict[uuid.UUID, uuid.UUID] = {}
            for row in inherited_rows:
                cloned = _clone_row(row, new_version.rule_version_id)
                if stage == "A":
                    # 새 PK를 미리 발급해 매핑을 기록한다 — 모델 default(client-side)에
                    # 맡기면 flush 전까지 새 id를 알 수 없다.
                    new_keyword_id = uuid.uuid4()
                    cloned.keyword_id = new_keyword_id
                    keyword_id_remap[row.keyword_id] = new_keyword_id
                session.add(cloned)
            for draft in stage_drafts:
                session.add(_build_row(draft, new_version.rule_version_id))

            if keyword_id_remap:
                await _reconnect_derived_keyword_ids(session, keyword_id_remap)

            await _deprecate_versions(session, active_version_ids)
            latest_rule_version_id = new_version.rule_version_id

        await session.commit()
        # 참고: 이번 호출에서 Stage를 여러 개 발행했으면 Stage마다 별도 rule_version이 생기지만,
        # PipelineState.rule_version_id는 하나만 담을 수 있어 마지막으로 만든 버전만 반환한다.
        return {"rule_version_id": str(latest_rule_version_id)}


async def _active_version_ids_for_stage(session, model) -> list:
    """해당 Stage의 데이터를 가진 active 버전만 조회한다.

    join으로 스코프를 좁히는 것이 Stage 간 독립 lineage의 핵심이다. 이 join을 빼면
    Stage A만 발행해도 Stage B의 active 버전까지 deprecated로 끌려간다(과거 버그).
    """
    return list(
        (
            await session.scalars(
                select(model.rule_version_id)
                .distinct()
                .join(RuleVersion, RuleVersion.rule_version_id == model.rule_version_id)
                .where(RuleVersion.status == "active")
            )
        ).all()
    )


async def _rows_of_versions(session, model, version_ids: list) -> list:
    if not version_ids:
        return []
    return list(
        (
            await session.scalars(select(model).where(model.rule_version_id.in_(version_ids)))
        ).all()
    )


async def _deprecate_versions(session, version_ids: list) -> None:
    if not version_ids:
        return
    await session.execute(
        update(RuleVersion)
        .where(RuleVersion.rule_version_id.in_(version_ids))
        .values(status="deprecated")
    )


async def _reconnect_derived_keyword_ids(session, remap: dict) -> None:
    """Stage A 승계로 바뀐 keyword_id를 correction_rules.derived_from_keyword_id에 반영한다.

    keyword 텍스트 자체는 클론 시 그대로 복사되므로(값만 옮기고 PK만 새로 발급), 매핑은
    안전하게 old→new 1:1이다. `_active_version_ids_for_stage`가 deprecate하기 전에 이미
    읽어둔 old row를 기준으로 매핑을 만들었으므로, 여기서 갱신한 뒤 아래에서 old 버전을
    deprecated 처리해도 참조가 끊기지 않는다.
    """
    for old_id, new_id in remap.items():
        await session.execute(
            update(CorrectionRule)
            .where(CorrectionRule.derived_from_keyword_id == old_id)
            .values(derived_from_keyword_id=new_id)
        )


def _clone_row(row, rule_version_id):
    """기존 active 행을 새 버전으로 승계한다.

    PK는 새로 발급하고 created_at은 DB 기본값(now())에 맡긴다. 어떤 버전에 속했는지는
    rule_version_id가 들고 있으므로 이력은 버전 계보로 추적한다.

    Stage A는 이 함수가 반환한 뒤 호출부에서 keyword_id를 명시적으로 재발급하고
    `_reconnect_derived_keyword_ids`로 correction_rules를 갱신한다(D-12).
    """
    model = type(row)
    primary_keys = {column.name for column in model.__table__.primary_key.columns}
    skipped = primary_keys | {"rule_version_id", "created_at"}
    values = {
        column.name: getattr(row, column.name)
        for column in model.__table__.columns
        if column.name not in skipped
    }
    return model(rule_version_id=rule_version_id, **values)


def _build_row(draft: ExtractedDraft, rule_version_id):
    fields = draft["fields"]
    if draft["stage"] == "A":
        return GateKeyword(
            rule_version_id=rule_version_id,
            type=fields["type"],
            keyword=fields["keyword"],
            keyword_category=fields["keyword_category"],
            data_type_focus=fields["data_type_focus"],
            verdict=fields["verdict"],
            weight=fields["weight"],
        )
    if draft["stage"] == "B":
        return GateMatrix(
            rule_version_id=rule_version_id,
            data_type=fields["data_type"],
            function_type=fields["function_type"],
            verdict=fields["verdict"],
            exemption_note=fields["exemption_note"],
            acquire_method=fields.get("acquire_method"),
            avoidance_redesign=fields.get("avoidance_redesign"),
            avoidance_certification=fields.get("avoidance_certification"),
            legal_basis_doc=fields["legal_basis"]["document_id"],
            legal_basis_article=fields["legal_basis"]["article"],
            risk_code=fields["risk_code"],
            priority=fields["priority"],
        )
    if draft["stage"] == "C":
        derived_id = fields.get("derived_from_keyword_id")
        return CorrectionRule(
            rule_version_id=rule_version_id,
            risky_text=fields["risky_text"],
            safe_text=fields["safe_text"],
            regulatory_score=fields["regulatory_score"],
            advertising_score=fields["advertising_score"],
            derived_from_keyword_id=uuid.UUID(derived_id) if derived_id else None,
            legal_basis_doc=fields["legal_basis"]["document_id"],
            legal_basis_article=fields["legal_basis"]["article"],
        )
    raise ValueError(f"publish 미구현 stage: {draft['stage']}")
