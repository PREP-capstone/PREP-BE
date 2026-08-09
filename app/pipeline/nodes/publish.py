"""[8] rule_versions 발행 노드.
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
            await _deprecate_active_versions_for_stage(session, _STAGE_MODEL[stage])

            count_result = await session.execute(select(RuleVersion))
            version_number = len(count_result.scalars().all()) + 1
            new_version = RuleVersion(version=f"v0.{version_number}", status="active")
            session.add(new_version)
            await session.flush()  # rule_version_id 확보

            for draft in stage_drafts:
                session.add(_build_row(draft, new_version.rule_version_id))

            latest_rule_version_id = new_version.rule_version_id

        await session.commit()
        # 참고: 이번 호출에서 Stage를 여러 개 발행했으면 Stage마다 별도 rule_version이 생기지만,
        # PipelineState.rule_version_id는 하나만 담을 수 있어 마지막으로 만든 버전만 반환한다.
        return {"rule_version_id": str(latest_rule_version_id)}


async def _deprecate_active_versions_for_stage(session, model) -> None:
    active_version_ids = (
        await session.scalars(
            select(model.rule_version_id)
            .distinct()
            .join(RuleVersion, RuleVersion.rule_version_id == model.rule_version_id)
            .where(RuleVersion.status == "active")
        )
    ).all()
    if active_version_ids:
        await session.execute(
            update(RuleVersion)
            .where(RuleVersion.rule_version_id.in_(active_version_ids))
            .values(status="deprecated")
        )


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
