"""proposal_pdf.py/proposal_docx.py 두 렌더러가 공유하는 상수.

두 렌더러는 같은 sections 입력을 받아 포맷만 다르게(PDF vs Word) 렌더링하므로
template_type -> 문서 제목 매핑은 항상 동일해야 한다. 각 파일에 같은 딕셔너리를
따로 두면 새 template_type이 추가될 때 한쪽만 갱신하고 다른 쪽을 빠뜨리는 사고가
날 수 있어(코드 리뷰 지적) 한 곳으로 모았다.
"""

from __future__ import annotations

TEMPLATE_TITLES = {
    "PSST": "창업사업화 지원사업 사업계획서",
    "RND": "R&D 과제 사업계획서",
    "IR": "투자유치용(IR) 사업계획서",
}
