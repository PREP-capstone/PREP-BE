"""업로드 파일명/제목을 알려진 RAG document_id(kr-xxx 형태)로 정규화한다.

룰 테이블의 legal_basis_doc은 RAG evidence_documents.document_id를 참조해야 하는데
(db_구축_설계서.md §1.5), 관리자가 업로드 화면에 한글 파일명을 그대로 두면
"의료기기법(법률)(제21263호)(20260701" 같은 문자열이 그대로 document_id가 돼서 조인이
끊긴다. app/domain/legal_documents.py의 DOCUMENT_TITLES(이미 알려진 문서 목록)를 거꾸로
찾아서 제목이 매칭되면 정식 kr-* id로 바꾼다.

목록에 없는 새 문서는 그대로 통과시킨다 — 새 법령의 영문 slug를 자동 생성하는 건
신뢰할 수 없어서(의미 있는 영문명은 사람이 정해야 함), 관리자가 직접 올바른 document_id를
입력하게 두는 편이 안전하다.
"""

from app.domain.legal_documents import DOCUMENT_TITLES

# 제목이 길수록 더 구체적인 문서다 — "의료기기법 시행규칙"이 "의료기기법"보다 먼저
# 매칭돼야 시행규칙 파일을 본법(kr-medical-device-act-...)으로 잘못 정규화하지 않는다.
_TITLE_TO_ID: list[tuple[str, str]] = sorted(
    ((title, doc_id) for doc_id, title in DOCUMENT_TITLES.items()),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def normalize_document_id(raw: str) -> str:
    for title, doc_id in _TITLE_TO_ID:
        if title in raw:
            return doc_id
    return raw
