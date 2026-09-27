"""[8] 반려 사유 기록 노드. 실제 영속화는 human_review가 rule_review_queue.decisions에
이미 다 남겼다(승인/반려 결정 전체) — 여기서 또 DB에 쓰면 같은 데이터를 중복 저장하게
된다. 이 노드는 그래프 구조(langgraph_파이프라인_설계서.md §2 다이어그램)를 그대로
유지하면서, 반려 건을 바로 확인할 수 있게 로그로 남기는 역할만 한다(추후 프롬프트
개선 데이터로 활용할 때는 rule_review_queue.decisions를 조회하면 된다).

배치 검수라 승인·반려가 한 실행 안에 같이 나올 수 있어, publish와 양자택일 분기가 아니라
human_review → reject_log → publish 순차 엣지로 둔다(graph.py 참고).
"""

import logging

from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


async def reject_log(state: PipelineState) -> dict:
    for entry in state["rejected_drafts"]:
        logger.info(
            "rule draft rejected: document_id=%s stage=%s reason=%s",
            state["document_id"],
            entry["draft"]["stage"],
            entry.get("reason"),
        )
    return {}
