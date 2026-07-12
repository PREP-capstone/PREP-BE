"""[8] rule_versions 발행 노드. 검증 통과 draft로 새 버전을 만들고 이전 active 버전은 deprecated 처리.
human_review가 붙으면 admin_decision == "approve"일 때만 호출되도록 바뀐다.
"""

from sqlalchemy import select, update

from app.db.models import GateKeyword, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.state import PipelineState


async def publish(state: PipelineState) -> dict:
    drafts = state["drafts"]
    if not drafts:
        # 발행할 draft가 없으면 새 버전을 만들지 않음
        return {"rule_version_id": state.get("rule_version_id")}

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(RuleVersion).where(RuleVersion.status == "active").values(status="deprecated")
        )

        count_result = await session.execute(select(RuleVersion))
        version_number = len(count_result.scalars().all()) + 1

        new_version = RuleVersion(version=f"v0.{version_number}", status="active")
        session.add(new_version)
        await session.flush()  # rule_version_id 확보

        for draft in drafts:
            fields = draft["fields"]
            session.add(
                GateKeyword(
                    rule_version_id=new_version.rule_version_id,
                    type=fields["type"],
                    keyword=fields["keyword"],
                    keyword_category=fields["keyword_category"],
                    data_type_focus=fields["data_type_focus"],
                    verdict=fields["verdict"],
                    weight=fields["weight"],
                )
            )

        await session.commit()
        return {"rule_version_id": str(new_version.rule_version_id)}
