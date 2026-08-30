"""근거 조문 document_id -> 한글 문서명 정적 매핑.

data/rule/manifest.csv(title 컬럼)가 원본. RAG evidence_documents.title이 정식 출처지만
팀원 담당 테이블이라 로컬에 항상 채워져 있지 않고(2026-08-30 기준 로컬 0행), 수정하려면
사전 협의가 필요하다 — 그래서 내 담당 파일만으로 항상 동작하는 정적 매핑을 쓴다.
"""

DOCUMENT_TITLES: dict[str, str] = {
    "kr-medical-act-20260407": "의료법",
    "kr-medical-device-act-20260701": "의료기기법",
    "kr-medical-device-act-rule-annex7-20260701": "의료기기법 시행규칙 별표7 — 금지되는 광고의 범위",
    "kr-mfds-wellness-0091-03-20260212": "의료기기와 개인용 건강관리(웰니스) 제품 판단기준",
    "kr-mohw-nonmedical-health-guide-202209": "비의료 건강관리서비스 가이드라인 및 사례집(2차)",
    "kr-pharmaceutical-affairs-act-20260621": "약사법",
    # manifest.csv엔 kr-mfds-llm-medical-device-guide-20260630로 등록돼 있지만
    # GATE_MATRIX_TABLE/gate_matrix 시드가 실제로 쓰는 id는 이쪽 — 같은 문서.
    "kr-mfds-llm-digital-medical-device-1511-01-20260630": "거대언어모델(LLM) 기반 디지털의료기기 허가·심사 가이드라인",
    # 2026-08-17 문서ID 개명(룰베이스_RAG_정합성_추적표.md) — 신/구 id 둘 다 로컬 gate_matrix에
    # 남아 있어 둘 다 매핑. 같은 문서.
    "kr-mfds-mobile-medical-app-guide-20200225": "모바일 의료용 앱 안전관리 지침",
    "kr-mobile-medical-app-guide-20200221": "모바일 의료용 앱 안전관리 지침",
}
