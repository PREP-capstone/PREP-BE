# LangGraph 기반 LLM 추출 파이프라인 설계서

> 버전: v1.2 | 2026-07-12 — §3 PipelineState에 `current_stage` 필드 추가(§5.1/§5.2 라우팅 코드가 이미 참조 중이었으나 스키마 선언 누락, 실제 구현 중 발견)
> 버전: v1.1 | 2026-07-05
> 기반 문서: db_구축_설계서.md V2.6 §4(LLM 기반 정보 추출 파이프라인), §5(RAG 파이프라인)
> 목적: §4.1의 8단계 파이프라인을 LangGraph StateGraph로 구현하기 위한 노드·엣지·상태 설계
> 대상 Stage: A(gate_keywords) / B(gate_matrix) / C(correction_rules) / D(bm_mapping, 스키마만 대응·로직은 미확정)
> v1.1 변경: 문서 종류(법령·규제문서 vs 판단가이드 등)에 따라 청킹을 RAG 파이프라인(팀원 담당)과 공유할지 독립 수행할지 분기하는 `classify_document_source` 노드 추가 (§2, §3, §4, §13 신설)

---

## 1. 왜 LangGraph인가

db_구축_설계서 §4.1 파이프라인은 단순 순차 실행이 아니라 다음 특성을 가진다.

- **조건 분기**: Stage(A/B/C/D)에 따라 프롬프트·검증·후처리 로직이 달라짐
- **Stage C만 추가 단계 필요**: LLM 추출 후 gate_keywords/gate_matrix를 조회하는 파생값 계산 단계([5.5])가 끼어듦
- **Human-in-the-loop**: [7] 관리자 검수는 사람이 개입해서 승인/반려할 때까지 실행이 멈춰야 함
- **재시도·복구**: LLM 추출 실패, 인용 검증 실패 시 재시도하거나 검수 큐로 우회해야 함
- **버전 관리와 연동**: 승인 시점에 rule_versions 상태 전환이 원자적으로 일어나야 함

이런 "조건부 분기 + 사람 개입 대기 + 상태 지속성"은 단순 함수 체인보다 LangGraph의 StateGraph(노드/엣지/체크포인터) 모델이 적합하다.

---

## 2. 전체 그래프 구조

> db_구축_설계서 §1.4(데이터소스↔구축위치매핑)에 따르면 문서는 4종으로 나뉘고, 이 중 **"법령·규제 문서"만 RAG(§5, 팀원 담당)와 룰베이스(본 파이프라인)가 동일 원문을 공유**한다. "의료기기 판단 가이드"·"위험 표현 사전"은 룰베이스 전용, "규제 위반 사례"는 RAG 전용이라 겹치지 않는다. 이 구분을 그래프 진입점에서 먼저 분기한다(상세 협의 사항은 §13).

```
                              ┌───────────────────────┐
                              │ classify_document_source│  [0] 문서 분류
                              └─────────┬─────────────┘
                     법령·규제 문서(RAG와 공유) │  판단가이드/위험표현사전(룰베이스 전용)
                                ▼                          ▼
                    ┌────────────────────┐      ┌─────────────────┐
                    │  load_shared_chunks  │      │  ingest_document │  [1] PDF 업로드
                    │ (팀원 RAG 파이프라인이 │      └────────┬─────────┘
                    │  이미 만든 evidence_  │               ▼
                    │  chunks를 조회, 재청킹│      ┌─────────────────┐
                    │  하지 않음)           │      │ chunk_document    │  [2] 텍스트추출·청킹
                    └─────────┬───────────┘      └────────┬─────────┘
                               └─────────────┬─────────────┘
                                             ▼
                              ┌─────────────────┐
                              │  route_stage      │  [3] Stage 라우팅
                              │ (conditional edge, │      (Send API로 팬아웃,
                              │  Send API)         │       A/B/C/D 동시 처리 가능)
                              └───┬───┬───┬───┬───┘
                    ┌─────────────┘   │   │   └─────────────┐
                    ▼                 ▼   ▼                 ▼
            ┌──────────────┐ ┌──────────────┐       ┌──────────────┐
            │ extract_A     │ │ extract_B     │  ...  │ extract_D     │  [4]+[5]
            │ (프롬프트+LLM) │ │ (프롬프트+LLM) │       │ (프롬프트+LLM) │
            └──────┬───────┘ └──────┬───────┘       └──────┬───────┘
                   │                 │                       │
                   │          ┌──────▼───────┐               │
                   │          │ derive_scores  │  [5.5]        │
                   │          │ (Stage C 전용,  │  LLM 미개입    │
                   │          │  gate_keywords/ │               │
                   │          │  gate_matrix    │               │
                   │          │  조회)          │               │
                   │          └──────┬───────┘               │
                   └────────┬────────┴───────────────────────┘
                            ▼
                   ┌──────────────────┐
                   │  auto_validate     │  [6] 자동검증
                   └─────────┬────────┘
                        ┌────┴────┐
                  실패(재시도가능) │  통과 또는 재시도소진
                        ▼         ▼
              ┌──────────────┐ ┌───────────────────┐
              │ retry_extract │ │ human_review        │  [7] 관리자 검수
              │ (최대 N회)     │ │ (interrupt, 체크포인트│      (interrupt로 대기)
              └──────┬───────┘ │  로 상태 보존)        │
                     │         └─────────┬───────────┘
                     └──────►(다시 auto_validate로)   │
                                     ┌────┴────┐
                                  승인│         │반려
                                     ▼         ▼
                          ┌──────────────┐ ┌──────────────┐
                          │  publish       │ │  reject_log    │  [8]
                          │ (rule_versions │ │ (반려사유 기록, │
                          │  active 전환+  │ │  프롬프트 개선용)│
                          │  테이블 INSERT)│ └──────────────┘
                          └──────────────┘
```

---

## 3. State 스키마

```python
from typing import TypedDict, Literal, Optional
from langgraph.graph.message import add_messages

class Chunk(TypedDict):
    chunk_id: str
    document_id: str
    article_number: str      # 예: "Ⅲ.2.가" — RAG(evidence_chunks)와 표기 규칙 공유 필요(§13-b)
    section_path: str
    content: str
    source: Literal["own", "shared_rag"]   # 직접 청킹했는지, 팀원 RAG의 evidence_chunks를 재사용했는지

class ExtractedDraft(TypedDict):
    stage: Literal["A", "B", "C", "D"]
    fields: dict              # Stage별 추출 스키마 (§4.2 JSON)
    legal_basis: dict         # {"document_id", "article", "quote"}

class ValidationResult(TypedDict):
    passed: bool
    failed_checks: list[str]  # ["필드누락", "값오류", "인용미확인", "중복후보", "파생값불일치"]

class PipelineState(TypedDict):
    document_id: str
    document_category: Literal["법령규제문서", "판단가이드", "위험표현사전"]  # [0] classify_document_source 결과
    raw_text: str
    chunks: list[Chunk]
    current_chunk_id: Optional[str]
    current_stage: Optional[Literal["A", "B", "C", "D"]]  # Send 팬아웃 시 각 분기에 세팅(§5.1/§5.2에서 참조하는데 기존에 필드 선언 누락돼 있었음, v1.2에서 추가)
    target_stages: list[Literal["A", "B", "C", "D"]]   # 이 문서에서 추출할 Stage(복수 가능)
    drafts: list[ExtractedDraft]
    derived_values: dict           # Stage C 전용: {"regulatory_score":, "derived_from_keyword_id":}
                                   # ※ privacy_score는 2026-07-28부로 런타임 계산 이관 — 본 dict 대상 아님
    validation: Optional[ValidationResult]
    retry_count: int
    rule_version_id: Optional[str]
    admin_decision: Optional[Literal["approve", "reject"]]
    reject_reason: Optional[str]
```

> `target_stages`는 문서 업로드 시 관리자가 지정(예: 웰니스판단기준 문서 → ["A","B"], 시행규칙 문서 → ["B"], 광고 관련 고시 → ["C"]). 한 문서가 여러 Stage에 동시에 걸리는 경우(예: 지침서-0091-03은 A·B 둘 다 해당) `Send` API로 팬아웃해서 병렬 처리.
>
> `document_category`가 "법령규제문서"면 `load_shared_chunks`로 라우팅(팀원 RAG의 evidence_chunks 재사용, `Chunk.source="shared_rag"`), "판단가이드"/"위험표현사전"이면 기존 `ingest_document`→`chunk_document` 경로로 독립 처리(`Chunk.source="own"`). 분류 기준은 db_구축_설계서 §1.4 표를 그대로 따른다.

---

## 4. 노드 정의

| 노드명 | 역할 | db_구축_설계서 §4.1 대응 | LLM 호출 여부 |
|---|---|---|---|
| `classify_document_source` | 업로드 문서를 법령규제문서/판단가이드/위험표현사전 3종으로 분류(§1.4 표 기준), `document_category` 세팅 | [0] (신규) | ✗ |
| `load_shared_chunks` | (법령·규제 문서 전용) 팀원 RAG 파이프라인이 이미 적재한 evidence_chunks를 조회해 재사용, 재청킹하지 않음 | [0] (신규) | ✗ |
| `ingest_document` | PDF 업로드 접수, evidence_documents 레코드 생성 | [1] | ✗ |
| `chunk_document` | 텍스트 추출 + 조문/제목 단위 청크 분할, evidence_chunks 생성 | [2] | ✗ |
| `route_stage` | target_stages 기준 조건부 분기 (Send API로 Stage별 노드에 병렬 디스패치) | [3] | ✗ |
| `extract_A` / `extract_B` / `extract_C` / `extract_D` | Stage별 프롬프트 주입 + LLM 호출 + JSON Schema 강제 출력 | [4]+[5] | ✓ |
| `derive_scores` | (Stage C 전용) gate_keywords.weight 조회 → regulatory_score 계산. **2026-07-28: privacy_score 산출 제거**(사용자 입력에서 결정되는 값이라 런타임 이관 — db_구축_설계서 §3.3.2) | [5.5] | ✗ |
| `auto_validate` | 필수필드/enum/인용/중복/점수범위/파생값일치 검증 (§4.4) | [6] | ✗ |
| `retry_extract` | 검증 실패 시 프롬프트에 실패 사유 추가해 재추출 (최대 N회) | — (신규) | ✓ |
| `human_review` | 관리자 검수 대기 — `interrupt()`로 그래프 일시정지, 좌측 원문+우측 편집폼 데이터 노출 | [7] | ✗ |
| `publish` | rule_versions.status=active 전환, 기존 버전 deprecated, 대상 테이블 INSERT | [8] | ✗ |
| `reject_log` | 반려 사유 기록 (추후 프롬프트 개선 데이터로 활용) | — (신규) | ✗ |

---

## 5. 조건부 라우팅 상세

### 5.0 문서 출처 라우팅 (`classify_document_source`)

```python
def route_document_source(state: PipelineState):
    if state["document_category"] == "법령규제문서":
        return "load_shared_chunks"
    return "ingest_document"
```

- "법령규제문서"(법률·시행령·시행규칙·고시 원문): 팀원 RAG가 이미 청킹해둔 evidence_chunks를 조회만 함 → 재청킹·중복 저장 방지
- "판단가이드"(0091-03, 모바일앱지침, LLM가이드라인 등)/"위험표현사전": 룰베이스 전용이라 RAG와 무관하게 독립적으로 `ingest_document`→`chunk_document` 수행

### 5.1 Stage 라우팅 (`route_stage`)

```python
def route_stage(state: PipelineState):
    return [
        Send(f"extract_{stage}", {**state, "current_stage": stage})
        for stage in state["target_stages"]
    ]
```

`Send` API로 한 문서가 여러 Stage에 걸릴 때 병렬 처리. 예: 지침서-0091-03 → Stage A(weight척도)와 Stage B(data_type 경계) 동시 추출.

### 5.2 Stage C 분기 (`derive_scores`)

```python
def route_after_extract(state: PipelineState):
    if state["current_stage"] == "C":
        return "derive_scores"
    return "auto_validate"
```

Stage A/B/D는 LLM 추출 직후 바로 검증으로, Stage C만 파생값 계산 노드를 거친 뒤 검증으로 진입.

### 5.3 검증 결과 분기 (`auto_validate` 이후)

```python
def route_after_validate(state: PipelineState):
    if state["validation"]["passed"]:
        return "human_review"
    if state["retry_count"] < MAX_RETRY:
        return "retry_extract"
    return "human_review"  # 재시도 소진 시에도 이슈 태그 달아서 검수 큐로 (자동 폐기 금지)
```

> 원칙: 자동검증 실패가 재시도 후에도 안 풀리면 **폐기하지 않고** "검증실패" 태그를 달아 관리자 검수로 넘긴다(§4.4 원칙 — 자동 FAIL 확정 금지, 관리자 최종 판단).

---

## 6. Human-in-the-loop 설계 (`human_review`)

```python
def human_review(state: PipelineState):
    decision = interrupt({
        "draft": state["drafts"][-1],
        "validation": state["validation"],
        "chunk_context": get_chunk_by_id(state["current_chunk_id"]),
    })
    return {"admin_decision": decision["action"], "reject_reason": decision.get("reason")}
```

- `interrupt()` 호출 시 그래프 실행이 멈추고 상태가 **체크포인터**(예: Postgres checkpointer)에 저장됨 — 관리자가 몇 시간 뒤에 검토해도 그 지점부터 재개 가능
- 관리자 UI(/admin/rules 화면, §4.5)에서 승인/반려 액션을 `Command(resume={"action": "approve"})` 형태로 전달하면 그래프가 재개됨
- 검수자가 verdict, axis_score, risk_code, legal_basis.quote, safe_text를 수정한 경우 → 수정된 값으로 state 갱신 후 재개

---

## 7. Stage별 서브그래프 차이 요약

| 항목 | Stage A | Stage B | Stage C | Stage D |
|---|---|---|---|---|
| 프롬프트 스키마 | gate_keywords JSON (§4.2) | gate_matrix JSON | risky_text/safe_text/advertising_score만 (regulatory·privacy는 LLM 미출력) | bm_mapping JSON |
| derive_scores 통과 여부 | ✗ | ✗ | ✓ (필수) | ✗ |
| 시드데이터 우선 적용 | — | **12개 확정 조합은 LLM 호출 없이 바로 publish 가능** (룰_추출_기준_최종확정본.md 참조) | — | — |
| 검증 특이사항 | weight 1~5 범위, FAIL_CONFIRMED 4조건 매칭 확인 | verdict가 PASS/CONDITIONAL/FAIL 3종 내인지, exemption_note 정합성 | 파생값 일치 검증(§4.4 신규 항목) 필수 | frequency_score·precedent_level 근거 미확정 — 현재는 스키마만 대응, 자동검증 로직은 별도 확정 필요(미결정_항목_정리.md C그룹) |

> Stage B의 12개 확정 조합은 `route_stage` 단계에서 이미 DB에 존재하는지 먼저 조회하고, 없는 조합만 `extract_B`로 LLM 호출하는 캐시 성격의 사전 분기를 추가하는 것을 권장(불필요한 LLM 호출 절감).

---

## 8. 에러 처리 및 재시도

| 실패 유형 | 처리 |
|---|---|
| LLM 호출 자체 실패(타임아웃/API 오류) | `retry_extract`에서 최대 3회 재시도, 이후 "추출실패" 태그로 human_review 직행 |
| JSON Schema 파싱 실패 | 실패한 원본 출력을 프롬프트에 첨부해 "형식 오류, 재출력" 지시와 함께 재시도 |
| 인용 미확인(legal_basis.quote가 청크에 없음) | auto_validate에서 실패 처리 → retry_extract (원문에서 직접 인용하도록 재지시) |
| 파생값 불일치(Stage C) | LLM 문제가 아니라 로직 버그 가능성 — 재시도 대상 아님, 즉시 개발자 알림 + human_review 태그 |

---

## 9. 법령 개정 대응 흐름 (§4.6 매핑)

```
diff_check 노드 (신규)
   ↓ 기존 active 버전과 신규 draft 비교
   ↓ 변경분만 추출해 human_review에 "diff 하이라이트" 형태로 전달
   ↓ 승인 시 publish, 미변경 룰은 rule_version만 갱신하고 값은 유지
```

`diff_check`는 `ingest_document` 직후, 동일 `document_id`의 기존 active 버전이 있는지 확인하는 조건부 엣지로 추가.

---

## 10. LangGraph 개념 ↔ 본 파이프라인 매핑

| LangGraph 개념 | 이 파이프라인에서의 용도 |
|---|---|
| `StateGraph` | 전체 파이프라인의 그래프 정의 |
| `add_node` | ingest_document, chunk_document, extract_*, derive_scores, auto_validate, retry_extract, human_review, publish, reject_log |
| `add_conditional_edges` | route_stage, route_after_extract(Stage C 분기), route_after_validate(재시도/검수 분기) |
| `Send` | Stage 병렬 팬아웃 (한 문서가 여러 Stage에 해당하는 경우) |
| `interrupt()` | human_review에서 관리자 개입 대기 |
| `Command(resume=...)` | 관리자 승인/반려 액션을 그래프에 전달해 재개 |
| Checkpointer(Postgres 등) | 관리자 검수 대기 중 상태 영속화 — 서버 재시작에도 안전 |

---

## 11. db_구축_설계서 §4.1 8단계 ↔ 그래프 노드 대응표

| §4.1 단계 | 그래프 노드 |
|---|---|
| [1] PDF 업로드 | `ingest_document` |
| [2] 텍스트 추출·청킹 | `chunk_document` |
| [3] Stage 라우팅 | `route_stage` (조건부 엣지 + Send) |
| [4] 프롬프트 주입 | `extract_A/B/C/D` 내부 |
| [5] LLM 추출 실행 | `extract_A/B/C/D` 내부 |
| [5.5] 파생값 계산(Stage C) | `derive_scores` |
| [6] 자동 검증 | `auto_validate` (+ `retry_extract`) |
| [7] 관리자 검수 | `human_review` |
| [8] rule_versions 활성화 | `publish` |

---

## 12. 다음 단계

1. State 스키마를 Pydantic/TypedDict로 코드화
2. Stage A부터 순서대로 노드 구현 (Phase 3 우선순위와 동일)
3. Stage B의 12개 확정 조합은 그래프 실행 전에 시드데이터로 먼저 INSERT — `route_stage`가 이를 인지하고 중복 추출 방지
4. Checkpointer 선정(Postgres 권장 — 기존 PostgreSQL 룰 테이블군과 동일 인프라 재사용 가능)
5. 관리자 UI(/admin/rules)와 `interrupt`/`Command(resume=...)` 연동 방식 확정

---

## 13. 팀원(RAG DB 담당)과 협의 필요 사항

`load_shared_chunks` 노드가 실제로 동작하려면 아래 항목을 구현 전에 팀원과 먼저 맞춰야 한다. 법적 근거 문제가 아니라 순수 인터페이스 합의 문제이므로 지금 바로 논의 가능(미결정_항목_정리.md B그룹에 추가 대상).

| 협의 항목 | 왜 필요한가 | 합의해야 할 구체 내용 |
|---|---|---|
| (a) 문서 분류 기준 | "법령·규제 문서" vs "판단가이드"/"위험표현사전" 구분이 서로 다르면 같은 문서를 양쪽이 중복 청킹하거나, 반대로 아무도 안 만듦 | db_구축_설계서 §1.4 표를 공동 기준으로 확정. 예: 지침서-0091-03·모바일앱지침·LLM가이드라인은 "판단가이드"(룰베이스 전용, RAG 미적재)로 명시 합의 |
| (b) evidence_chunks 스키마·표기 규칙 | 룰베이스가 `article_number`를 "Ⅲ.2.가" 식으로 참조하는데, RAG 청킹 단위·조문 표기 방식이 다르면 `load_shared_chunks`에서 매핑 불가 | article_number 표기 통일, 청크 단위(조/항/호 vs 문단 단위) 합의 |
| (c) 청킹 순서·의존관계 | 룰베이스 파이프라인이 법령·규제 문서를 만나면 RAG가 먼저 청킹해뒀다는 전제로 조회만 함 — RAG 청킹이 아직 안 끝난 문서면 대기/알림 필요 | 어느 쪽이 법령·규제 문서를 먼저 업로드·청킹할지, 미완료 시 룰베이스가 폴백(자체 청킹)할지 대기할지 정책 결정 |
| (d) 판단가이드 문서의 RAG 적재 여부 | 현재 설계는 판단가이드를 RAG에 넣지 않는 것으로 되어 있으나, 팀원이 규제 위반 사례 검색 시 판단가이드도 참조하고 싶을 수 있음 | 필요하면 §1.4 표 자체를 갱신(둘 다 활용)하고 본 문서 §2/§3에도 반영 |
| (e) app/db/models.py 공동 소유 | evidence_documents/evidence_chunks 테이블 정의를 양쪽이 다 참조·수정하므로 스키마 변경 시 상대방 파이프라인이 깨질 수 있음 | 스키마 변경은 PR 리뷰 필수화, 변경 전 상대방에게 사전 공지 |
| (f) document_id 발급 프로토콜 | 같은 법령·규제 문서를 양쪽이 각자 업로드하면 evidence_documents에 중복 레코드 생성 가능 | 문서 업로드는 한쪽(예: RAG 담당)이 전담 등록하고, 다른 쪽은 조회만 하도록 역할 분리, 또는 파일 해시 기준 upsert 로직 공유 |

> 우선순위: (a)·(f)는 `load_shared_chunks` 구현 이전에 반드시 확정. (b)는 §13-a 확정 직후. (c)·(d)·(e)는 구현하면서 조정 가능한 운영 정책.
