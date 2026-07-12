"""[8] rule_versions 활성화 노드.

참고: docs/langgraph_파이프라인_설계서.md §4 (publish), docs/db_구축_설계서.md §3.1/§3.2/§4.5
지금은 human_review(interrupt)가 없으므로 auto_validate 통과 시 바로 이 노드로 진입한다.
human_review가 붙으면 admin_decision == "approve"일 때만 호출되도록 바뀐다.

버전 부여 방식: rule_versions는 gate_keywords/gate_matrix/correction_rules/bm_mapping이 공유하는
"공통" 테이블(§3.1)이지만, 아직 Stage B/C/D가 구현되지 않아 지금은 Stage A 발행마다 새 버전을
발급하고 이전 active 버전을 deprecated로 내린다. Stage B/C/D가 붙으면 버전 스코프(전체 공유 vs
스테이지별)를 다시 정해야 한다.
"""

from sqlalchemy import select, update

from app.db.models import GateKeyword, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.state import PipelineState


async def publish(state: PipelineState) -> dict:
    drafts = state["drafts"]
    if not drafts:
        # 이번 실행에서 검증을 통과한 draft가 없으면 새 버전을 발행하지 않음
        # (기존 active 버전을 빈 버전으로 덮어쓰지 않기 위함)
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
