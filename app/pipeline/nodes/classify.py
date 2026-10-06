"""[0] 문서 분류 노드. 업로드된 문서의 document_id(원본 파일명 기반)를 보고
법령규제문서/판단가이드/위험표현사전 3종을 규칙 기반으로 분류한다
(db_구축_설계서.md §1.4, langgraph_파이프라인_설계서.md §5.0). LLM을 쓰지 않는다 —
법령류 문서는 제목에 "시행규칙/시행령/법/고시" 같은 정형화된 패턴이 있어 키워드 매칭으로
충분하고, 애매하면 조용히 틀리는 것보다 fallback(판단가이드)이 안전하다
(ingest_document.py의 기존 기본값과 동일한 값으로 맞췄다).

관리자가 업로드 화면에서 document_category를 직접 골랐으면 그 값을 그대로 존중하고
분류를 건너뛴다 — 자동 분류는 어디까지나 기본값이지 강제가 아니다.

**주의 — 라우팅은 아직 안 바뀐다**: 설계서(§2)는 "법령규제문서"를 RAG 담당의
evidence_chunks와 공유하는 `load_shared_chunks` 경로로 보내게 돼 있지만, 그 노드는
`app/rag/`(팀원 담당) 스키마·가정과 얽혀 있어 사전 협의 없이 구현하지 않는다(CLAUDE.md).
그래서 지금은 document_category를 정하기만 하고, 청킹은 카테고리와 무관하게 항상
ingest_document→chunk_document로 간다(graph.py 참고).
"""

import re

from app.pipeline.state import PipelineState

# 예시: 의료기기법, 의료기기법 시행규칙, 약사법, 개인정보 보호법, 식약처고시 제2026-6호
# "법"으로 끝나는지도 보되(의료기기법/약사법처럼), "불법"·"방법"처럼 법명이 아닌 일반 단어의
# 일부로 낀 경우까지 넓게 잡지 않으려고 끝(용언 활용·조사 없이 그대로 끝남)만 본다.
_STATUTE_PATTERN = re.compile(r"(시행규칙|시행령|고시|법률|법$)")
# 예시: 지침서-0091-03, 모바일 의료용 앱 안전관리 지침, LLM 기반 ... 가이드라인, 안내서-1425-01
_GUIDELINE_PATTERN = re.compile(r"(지침서|안내서|가이드라인|판단기준|지침|가이드)")
# 별도 "위험 표현 사전" 문서군 — 아직 실제 시딩 사례가 없어 넓게 잡지 않고 좁은 패턴만 본다.
_RISKY_TERM_DICT_PATTERN = re.compile(r"(위험\s*표현\s*사전|금지\s*표현|광고\s*심의\s*기준)")


def _classify_by_title(title: str) -> str:
    if _RISKY_TERM_DICT_PATTERN.search(title):
        return "위험표현사전"
    if _STATUTE_PATTERN.search(title):
        return "법령규제문서"
    if _GUIDELINE_PATTERN.search(title):
        return "판단가이드"
    return "판단가이드"  # ingest_document.py 기존 기본값과 동일한 안전한 fallback


def classify_document_source(state: PipelineState) -> dict:
    if state.get("document_category"):
        return {}  # 관리자가 이미 지정 — 자동 분류로 덮어쓰지 않는다
    # document_id는 업로드 시점에 kr-* 영문 slug로 정규화돼 있어 한글 패턴이 남아있지 않다
    # (document_id_normalize.py). 정규화 전 원본 제목을 봐야 분류가 성립한다.
    title = state.get("source_title") or state.get("document_id") or ""
    return {"document_category": _classify_by_title(title)}
