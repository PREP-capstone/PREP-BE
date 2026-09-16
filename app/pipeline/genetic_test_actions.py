"""DTC 유전자검사 키워드 화이트리스트 (생명윤리 및 안전에 관한 법률 근거,
db_구축_설계서.md §1.5 LAW-BIOETHICS-01).

이 목록은 두 곳에서 함께 쓰인다 — 어긋나면 /gate의 인증 안내 문구와 /regulatory-risk의
위험 점수가 서로 다른 기준으로 "유전자검사"를 인식하게 된다.
- `app/pipeline/gate_matrix_table.py`의 `detect_genetic_test_signal()`: (생체지표, 수치예측·진단)
  FAIL 셀의 avoidance_certification 문구를 생명윤리법 기준으로 교체하는 신호
- `scripts/seed_genetic_test_keywords.py`: gate_keywords에 시딩할 키워드 — service_description
  텍스트 매칭만으로 regulatory_score에 반영(§01 모듈, judgement.py `_match_gate_keywords`)

**약사법(pharmacy_actions.py)과 다른 점**: 생명윤리법 원문은 2026-09-14 사용자가 직접
PDF로 제공(법률 제21065호, 2025.10.1. 시행) — 핵심 조문(제49조 신고, 제49조의2 DTC 인증,
제50조③ 질병 진단·치료 관련 검사 제한)은 `gate_matrix_table.GENETIC_AVOIDANCE_CERTIFICATION`
문구에 하드코딩 인용돼 있다. 다만 RAG(app/rag/)에는 아직 미적재라(evidence_chunks_draft.csv
확인, 2026-09-14 기준 없음) `_fill_quotes()`가 조문 원문을 조회해오지 못한다. gate_keywords에는
애초에 legal_basis 저장 컬럼이 없어 이 시딩 경로(_match_gate_keywords → keyword_score)는
RAG 문서 유무와 무관하게 동작한다 — 약사법 키워드도 같은 이유로 RAG 확보(2026-08-14) 이전인
2026-07-26부터 이미 점수에 반영되고 있었다. 다만 matched_rules에 legal_basis가 노출되는
건 correction_rules 경로(Stage C)뿐이라, 이 키워드들은 점수만 올릴 뿐 "왜"를 설명하는
근거 조문은 응답에 아직 노출되지 않는다 — RAG 적재 전까지의 알려진 제약(§8.2 LAW-BIOETHICS-01 항목).

DTC 유전자검사기관 인증 없이 제공하는 행위 자체를 잡으려는 목적이라 TREATMENT
("처치·개선·예방을 지시·유도하는 단계")·DIAGNOSIS 어느 쪽 정의에도 깔끔히 들어맞지 않는다 —
`keyword_category`는 기존 두 값을 억지로 재사용하지 않고 OTHER를 쓴다(기능적 영향 없음,
validate.py enum 체크 통과 여부만 결정).
"""

GENETIC_TEST_KEYWORDS: tuple[str, ...] = (
    "유전자검사",
    "유전자분석",
    "유전체분석",
    "유전체검사",
    "DTC유전자",
)
