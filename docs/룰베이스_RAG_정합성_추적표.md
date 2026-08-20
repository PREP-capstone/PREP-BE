# 룰베이스 ↔ RAG 정합성 추적표

> 버전: v1.5 | 2026-08-20
> 목적: 룰베이스(`gate_matrix`/`correction_rules`의 `legal_basis_doc`/`legal_basis_article`)와
> RAG(`evidence_documents.document_id`/`evidence_chunks.section_id`)가 **같은 문서·같은 조문을
> 가리키는지** 양쪽 담당자가 함께 보고 관리하는 기준표.
> 재검증 주기: RAG 쪽 문서 추가/재청킹이 있을 때마다, 또는 판정 API(`judgement/*`) 배포 전 필수 1회.
> v1.5 변경: **v1.4에서 발견한 웰니스판단기준·의료법 RDS 미반영 건, RAG 담당이 재청킹
> 배포해서 해소됨.** RDS로 재확인 — 웰니스판단기준은 조문 단위 section_id 30개(`I`~`IV.2.나`
> 등, `IV.3` 포함) 정상 적재, 의료법은 `제2조`/`제27조`/`제56조` 3개 정상 적재. mock
> 케이스(`생체지표_비교추이분석_CONDITIONAL`)로 실제 `/correction-candidates` 호출해
> `IV.3` quote가 실제 원문으로 채워지는 것까지 확인. `judgement/*`가 신뢰하는 화이트리스트
> 5개 문서 전부 실데이터 기준으로 정상 동작.
> v1.4 변경: **`judgement/*` API가 RAG lookup(`rag/chunks/lookup`)을 실제로 연결함** — "다음
> 재검증 시점"에 있던 배포 게이트가 지금이다(이슈 #39). 화이트리스트는
> `app/api/judgement.py`의 `_RAG_TRUSTED_DOCUMENT_IDS`(이 표의 ✅ 문서 5개)로 구현.
> **연결하면서 RDS 실데이터로 재확인해보니 표1과 어긋나는 게 2건 발견됨**:
> - 웰니스판단기준(`kr-mfds-wellness-0091-03-20260212`): 표1은 "조문 단위 재청킹 완료
>   (PR #25)"라고 돼 있지만, RDS의 실제 `section_id`는 여전히 `p4`~`p31` 같은 페이지
>   단위뿐이다(27건). `IV.3` 같은 조문 단위 section_id는 하나도 없어 lookup이 항상
>   빈 결과를 반환한다.
> - 의료법(`kr-medical-act-20260407`): 표1은 "청킹 완료(PR #25) — 제2조/제27조/제56조"라고
>   돼 있지만, RDS에는 이 문서의 청크가 **0건**이다.
>
> 둘 다 화이트리스트에는 남겨뒀다(document_id 자체는 맞고, 코드 쪽은 빈 결과를 에러 없이
> `quote: null`로 처리하니 안전 — 판본 불일치 같은 위험은 아님). 다만 PR #25가 실제로는
> RDS에 배포되지 않은 것으로 보이니 RAG 쪽에서 확인 부탁드립니다.
> v1.3 변경: **웰니스판단기준·의료법 재청킹 반영 (RAG PR #25)** — 조문 단위로 재청킹 완료 확인,
> 실제 원문(page 17~18)과 대조해 청킹 구조가 정확함을 검증. 이 과정에서 **룰베이스 자체 오류
> 2건 발견·수정**: gate_matrix의 `legal_basis_article`이 `III.가`/`III.다`로 돼 있었는데, 실제
> 문서 구조는 `III` → `2.` → `가/나/다`라 `III.2.가`/`III.2.다`가 맞음(§1.5.1 표기 규칙 위반).
> 운영 DB(로컬+RDS) 수정 완료.
> v1.2 변경: **표 3 신설** — `RAG_데이터수집_최종보고서.md`(2026-07-29) 기준 RAG 적재 문서
> 37건 전체를 실데이터(`evidence_documents_draft.csv`/`evidence_chunks_draft.csv`)로 재확인해
> 청킹 상태와 함께 정리. 룰베이스 미인용 29건도 포함(향후 참고용). 실제 청킹 완료는 8건뿐임을
> 확인.
> v1.1 변경: 모바일 의료용 앱 안전관리 지침 건 — 로컬 PDF 원문 직접 확인으로 동일 문서 확정,
> `MFDS-G-2026-03` 식별자 재확인 요청 해소.
> v1.0 변경: 최초 작성. 판정엔진 API 개발 착수 전 첫 전수 대조 결과 반영(2026-08-17).
> 대조 방법: `data/rag/evidence_documents_draft.csv` / `evidence_chunks_draft.csv`(RAG 실제 데이터)를
> 운영 DB의 `gate_matrix`/`correction_rules` active 행과 직접 비교.

---

## 표 1: 문서 단위 정합성 (document_id 레벨)

| 문서명 | 판본/발행일 | 룰베이스 document_id | RAG document_id | 일치 여부 | section_id 체계 | 영향 행 수 | 상태 | 최종 확인일 | 비고 |
|---|---|---|---|---|---|---|---|---|---|
| 웰니스판단기준 0091-03 | 2026.2 개정 | `kr-mfds-wellness-0091-03-20260212` | `kr-mfds-wellness-0091-03-20260212` | ✅ 일치 | ✅ **조문 단위로 재청킹 완료** (PR #25) — 원문 17~18쪽과 대조해 구조 확인(`III.2.가` 등) | gate_matrix 6 + correction_rules 54 = **60건** | ✅ 해소 | 2026-08-17 | 재청킹 검증 과정에서 gate_matrix 2건(`III.가`→`III.2.가`, `III.다`→`III.2.다`)의 자체 표기 오류 발견·수정. correction_rules 54건(`IV.1~3` 계열)은 전부 정상 확인 |
| 모바일 의료용 앱 안전관리 지침 | 2020.2 개정 | `kr-mfds-mobile-medical-app-guide-20200225` (2026-08-17 수정, 구 `kr-mobile-medical-app-guide-20200221`) | `kr-mfds-mobile-medical-app-guide-20200225` | ✅ **일치 확정** | 미확인 (RAG 청킹 대상에 이 문서 chunk 없음 — 확인 필요) | gate_matrix 1건 | ✅ 정상(document_id) / 🟡 청킹 확인 필요 | 2026-08-17 | 로컬 PDF(`kr-mobile-medical-app-guide-20200221.pdf`) 표지·제개정이력서 직접 확인 — "2020.2.21."은 문서 자체에 인쇄된 공식 승인일자(제·개정 이력서 2번 항목). PDF 파일 CreationDate는 2020-02-24. RAG의 2020-02-25는 MFDS 홈페이지 게시일로 추정 — 같은 문서, 날짜 출처만 다름. `MFDS-G-2026-03` 식별자 건 해소 |
| 비의료 건강관리서비스 가이드라인 및 사례집 | 룰베이스=**2차(2022.9)** / RAG=**1차(2019.5.21)** | `kr-mohw-nonmedical-health-guide-202209` | `kr-mohw-nonmedical-healthcare-guide-20190521` | ❌ **불일치 — 다른 판본** | RAG는 혼합(로마숫자 장 제목 + 페이지 단위) | correction_rules **29건** | 🔴 조치 필요 | 2026-08-17 | document_id만 맞추면 다른 판본 원문이 근거로 표시될 위험. 2차본 PDF 로컬 보유, RAG에 공유 예정 |
| 약사법 | 시행 2026.6.21, 법률 제21109호 | `kr-pharmaceutical-affairs-act-20260621` | `kr-pharmaceutical-affairs-act-20260621` | ✅ 일치 | ✅ 조문 단위(`제2조`/`제20조`/`제23조`/`제23조의2`/`제24조`) | correction_rules 7건 | 🟡 일부 조치 필요 | 2026-08-17 | `제44조` 1건 미청킹 — 표2 참조 |
| 의료기기법 | 시행 2026.7.1, 법률 제21263호 | `kr-medical-device-act-20260701` | `kr-medical-device-act-20260701` | ✅ 일치 | ✅ 조문 단위(`제2조`/`제24조`) | correction_rules 7건 | ✅ 정상 | 2026-08-17 | 인용 조문(`제2조`)이 청킹 범위 안 |
| 의료기기법 시행규칙 별표7 | 시행 2026.7.1, 총리령 제2127호 | `kr-medical-device-act-rule-annex7-20260701` | `kr-medical-device-act-rule-annex7-20260701` | ✅ 일치 | ✅ 항목 단위(`별표7.제1호`~`제18호`) | RAG 전용(Stage C 룰추출 대상 아님, advertising_score 척도 근거로만 사용) | ✅ 정상 | 2026-08-17 | 18개 항목 전부 청킹 완료 확인 |
| 의료법 | 시행 2026.4.7, 법률 제21524호 | `kr-medical-act-20260407` | `kr-medical-act-20260407` | ✅ document_id는 일치 | ✅ 청킹 완료(PR #25) — `제2조`/`제27조`/`제56조` 3건 | correction_rules **7건** | ✅ 해소 | 2026-08-17 | 인용 중인 `제27조` 청킹 범위 안 |
| LLM 기반 디지털의료기기 허가·심사 가이드라인 | 2026.6.30 제정, 안내서-1511-01 | `kr-mfds-llm-digital-medical-device-1511-01-20260630` | `kr-mfds-llm-digital-medical-device-1511-01-20260630` | ✅ document_id는 일치 | ❌ RAG chunk 0건 — 미청킹 | gate_matrix 1건 | 🟡 조치 필요(낮은 우선순위) | 2026-08-17 | function_type 매핑 근거 1건뿐이라 시급하지 않음 |

---

## 표 2: 조문 단위 정합성 (document_id는 일치하나 특정 조문만 미청킹인 경우)

| 문서 | 룰베이스가 인용하는 조문 | RAG 청킹 여부 | 인용 행 | 비고 |
|---|---|---|---|---|
| 약사법 | `제44조` | ❌ | correction_rules 1건 (`투약` → `복용 기록`) | 이 조문 자체가 "판매·수여 포섭 여부 잠정" 상태 — 법적 근거 확정 전이라 청킹 우선순위 낮음 |

---

---

## 표 3: RAG 적재 문서 전체 목록 (37건, `RAG_데이터수집_최종보고서.md` 2026-07-29 기준 + 실데이터 재확인)

표 1은 **룰베이스가 실제로 인용하는 문서만** 다룬다. 아래는 RAG에 등록된 **전체 37개 문서**를
청킹 여부까지 실데이터(`evidence_documents_draft.csv`/`evidence_chunks_draft.csv`)로 재확인한
목록이다 — 표 1에 없는 29건은 현재 룰베이스가 인용하지 않지만, 향후 규제/개인정보/광고 축
확장이나 판정엔진의 RAG 근거 조회 범위 판단에 참고할 것.

### 3.1 의료기기 / 웰니스 판정

| document_id | 제목 | 유형 | 청킹 상태 | 비고 |
|---|---|---|---|---|
| `kr-mfds-wellness-0091-03-20260212` | 의료기기와 개인용 건강관리제품(웰니스) 판단기준 | GUIDE/OFFICIAL_GUIDE | 27건 (⚠️ 페이지 단위) | 표1 참조 |
| `kr-medical-device-act-20260701` | 의료기기법 | LAW/ACT | 2건 | 표1 참조 |
| `kr-medical-device-act-decree-20260701` | 의료기기법 시행령 | LAW/DECREE | 0건(미청킹) | 룰베이스 미인용 |
| `kr-medical-device-act-rule-20260701` | 의료기기법 시행규칙 | LAW/RULE | 1건 | 룰베이스 미인용(제45조 관련) |
| `kr-medical-device-act-rule-annex7-20260701` | 의료기기법 시행규칙 별표7 | LAW/ANNEX | 18건 (항목 단위, 완료) | 표1 참조 |
| `kr-mfds-mobile-medical-app-guide-20200225` | 모바일 의료용 앱 안전관리 지침 | GUIDE/OFFICIAL_GUIDE | 0건(미청킹) | 표1 참조 — document_id는 확정, 청킹 대기 |

### 3.2 의료행위 / 비의료 건강관리

| document_id | 제목 | 유형 | 청킹 상태 | 비고 |
|---|---|---|---|---|
| `kr-medical-act-20260407` | 의료법 | LAW/ACT | 0건(미청킹) | 표1 참조 |
| `kr-medical-act-decree-20260210` | 의료법 시행령 | LAW/DECREE | 0건(미청킹) | 룰베이스 미인용 |
| `kr-mohw-nonmedical-healthcare-guide-20190521` | 비의료 건강관리서비스 가이드라인 및 사례집(**1차**, 2019.5.21) | GUIDE/MOHW_GUIDE | 35건 | 표1 참조 — 룰베이스가 인용하는 **2차(2022.9)본과 다른 판본** |

### 3.3 개인정보

| document_id | 제목 | 유형 | 청킹 상태 |
|---|---|---|---|
| `kr-pipa-active-20251002` | 개인정보 보호법 | LAW/ACT | 149건 |
| `kr-pipa-decree-20260519` | 개인정보 보호법 시행령 | LAW/DECREE | 133건 |
| `kr-pipa-future-20260911` | 개인정보 보호법(예정본) | LAW/ACT | 0건(미청킹) |
| `kr-pipc-data-portability-guide-20260625` | 개인정보 전송요구권 제도 안내서 | GUIDE/MANUAL | 0건(미청킹) |
| `kr-pipc-health-data-guide-20260615` | 보건의료데이터 활용 가이드라인 | GUIDE/GUIDELINE | 0건(미청킹) |
| `kr-pipc-integrated-privacy-guide-202507` | 개인정보 처리 통합 안내서 | GUIDE/MANUAL | 0건(미청킹) |
| `kr-pipc-privacy-faq-202512` | 개인정보 질의응답 모음집 | GUIDE/FAQ | 0건(미청킹) |
| `kr-pipc-privacy-policy-guide-20260423` | 개인정보 처리방침 작성지침 | GUIDE/MANUAL | 0건(미청킹) |
| `kr-pipc-pseudonymized-data-guide-20260331` | 가명정보 처리 가이드라인 | GUIDE/GUIDELINE | 0건(미청킹) |
| `kr-pipc-security-safeguards-guide-202511` | 개인정보 안전성 확보조치 기준 안내서 | GUIDE/MANUAL | 0건(미청킹) |

이 그룹은 룰베이스가 하나도 인용하지 않는다 — `privacy_score`는 §3.3.2 결정(2026-07-28)으로
`correction_rules`에 저장하지 않고 판정엔진이 런타임에 `data_sensitivity` 테이블로 계산하기
때문. 2번(채린) 담당의 `feasibility/data` API가 향후 이 그룹을 참조할 가능성이 있음.

### 3.4 약무행위

| document_id | 제목 | 유형 | 청킹 상태 | 비고 |
|---|---|---|---|---|
| `kr-pharmaceutical-affairs-act-20260621` | 약사법 | LAW/ACT | 5건(`제2조`/`제20조`/`제23조`/`제23조의2`/`제24조`) | 표1 참조 — `제44조` 미청킹 |

### 3.5 광고 / 표시광고 (advertising_score 관련, 룰베이스 미인용 — 별표7 척도는 프롬프트에 하드코딩됨)

| document_id | 제목 | 유형 | 청킹 상태 |
|---|---|---|---|
| `kr-food-labeling-ad-act-active-20250919` | 식품 등의 표시·광고에 관한 법률 | LAW/ACT | 0건(미청킹) |
| `kr-food-labeling-ad-act-future-20261127` | 식품 등의 표시·광고에 관한 법률(예정본) | LAW/ACT | 0건(미청킹) |
| `kr-food-labeling-ad-rule-20260101` | 식품 등의 표시·광고에 관한 법률 시행규칙 | LAW/RULE | 0건(미청킹) |
| `kr-health-functional-food-act-active-20250103` | 건강기능식품에 관한 법률 | LAW/ACT | 0건(미청킹) |
| `kr-health-functional-food-act-future-20261008` | 건강기능식품에 관한 법률(예정본) | LAW/ACT | 0건(미청킹) |
| `kr-health-functional-food-act-future-20261231` | 건강기능식품에 관한 법률(예정본) | LAW/ACT | 0건(미청킹) |
| `kr-health-functional-food-functional-ingredients-rule-20260413` | 건강기능식품 기능성 원료 및 기준·규격 인정에 관한 규정 | LAW/ADMIN_RULE | 0건(미청킹) |

### 3.6 소비자원 사례 (판정 근거가 아니라 리포트 보강용 — 3번 담당 시장성/리포트 영역 참고)

| document_id | 제목 | 유형 | 청킹 상태 |
|---|---|---|---|
| `kr-kca-consumer-damage-annual-casebook` | 한국소비자원 소비자 피해구제 연보 및 사례집 | REPORT/CASEBOOK | 0건(미청킹) |
| `kr-kca-damage-casebook-list` | 한국소비자원 피해구제사례집 | REPORT/CASEBOOK | 0건(미청킹) |
| `kr-kca-item-damage-cases` | 한국소비자원 품목별 피해구제사례 | CASE/DAMAGE_CASE | 0건(미청킹) |
| `kr-kca-item-dispute-decisions` | 한국소비자원 품목별 분쟁조정결정사례 | CASE/DISPUTE_DECISION | 0건(미청킹) |

### 3.7 AI / 디지털의료 (후순위, 룰베이스 미인용)

| document_id | 제목 | 유형 | 청킹 상태 | 비고 |
|---|---|---|---|---|
| `kr-ai-basic-act-20260122` | 인공지능 발전과 신뢰 기반 조성 등에 관한 기본법 | LAW/ACT | 0건(미청킹) | 룰베이스 미인용 |
| `kr-digital-medical-products-rule-20260124` | 디지털의료제품법 시행규칙 | LAW/RULE | 0건(미청킹) | 2차 구축 범위(임상·진료 제외 근거), 1차 미투입 |
| `kr-mfds-dtx-guideline-20200827` | 디지털치료기기 허가·심사 가이드라인 | GUIDE/GUIDELINE | 0건(미청킹) | 룰베이스 미인용 |
| `kr-mfds-llm-digital-medical-device-1511-01-20260630` | LLM 기반 디지털의료기기 허가·심사 가이드라인 | GUIDE/GUIDELINE | 0건(미청킹) | 표1 참조 |

### 3.8 규제샌드박스

| document_id | 제목 | 유형 | 청킹 상태 |
|---|---|---|---|
| `kr-regulatory-sandbox-cases` | 규제샌드박스 승인 사례 | CASE/SANDBOX_CASE | 0건(미청킹) |
| `kr-regulatory-sandbox-guide` | 규제샌드박스 지원·제도 안내 | GUIDE/INSTITUTION_GUIDE | 0건(미청킹) |

### 요약

- **등록된 문서 37건 중 실제 청킹 완료는 8건뿐**(370 chunks 전부 이 8건에서 나옴) — 나머지 29건은 metadata만 등록되고 본문 청킹 전 단계
- 청킹 완료 8건: 웰니스판단기준(27, ⚠️ 페이지단위) · 비의료가이드 1차(35, ⚠️ 판본다름) · 개인정보보호법(149) · 시행령(133) · 별표7(18, 정상) · 약사법(5) · 의료기기법(2) · 의료기기법시행규칙(1)
- 룰베이스가 인용하는 8개 문서 중 **정상은 3개뿐**(의료기기법·별표7·약사법 일부) — 나머지 5개(웰니스판단기준·비의료가이드·모바일앱지침·의료법·LLM가이드라인)는 표1에 기록된 문제가 있음

---

## 상태 범례

| 아이콘 | 의미 |
|---|---|
| ✅ | 확인 완료, 정상 |
| 🟡 | 조치 필요하지만 우선순위 낮음 / 잠정 확인 |
| 🔴 | 조치 필요, 판정 API "근거 표시" 기능에 직접 영향 |

## 다음 재검증 시점

- RAG가 웰니스판단기준을 조문 단위로 재청킹 완료했을 때
- RAG가 비의료 건강관리서비스 가이드라인 2차본(2022.9)을 확보·청킹 완료했을 때
- RAG가 의료법(`kr-medical-act-20260407`) 청킹을 시작했을 때
- `judgement/*` API가 실제로 RAG lookup을 붙이기 직전 (배포 게이트)
