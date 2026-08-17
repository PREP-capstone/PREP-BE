> ✅ **2026-07-28 팀 합의 완료.** 아래 제안은 실제로 채택되어 `app/db/models/evidence_document.py`,
> `app/db/models/evidence_chunk.py`로 구현 완료됨(확인됨: 2026-08-17). 최신 결론은
> `db_구축_설계서.md` §1.5.1(조문 표기 정규화 규칙)을 참조할 것 — 이 문서는 그 결론이 나오기까지의
> **논의·합의 과정 기록**으로 보존한다.
>
> 다만 실제 적재 데이터를 재검증한 결과, 이 문서에서 합의된 규칙이 일부 문서(웰니스판단기준 등)의
> 실제 청킹에는 아직 반영되지 않은 것으로 확인됨. 최신 이행 현황은
> `룰베이스_RAG_정합성_추적표.md` 참조.

## 1. 목적

RAG DB 구축을 진행하기 전에, `evidence_documents`, `evidence_chunks` 스키마와 룰베이스 파이프라인의 참조 방식에 대해 팀 차원의 합의가 필요하다.

현재 RAG DB는 단순히 문서를 저장하는 용도가 아니라, 판정 엔진이 사용자에게 제시할 **법령·가이드·사례 근거를 조회하는 공통 근거 저장소** 역할을 하게 된다.

특히 룰베이스 파이프라인에서 `load_shared_chunks` 노드를 사용하려면, RAG 담당자가 만든 chunk를 룰베이스 담당자가 안정적으로 조회할 수 있어야 한다. 따라서 문서 분류 기준, chunk 표기 방식, document_id 발급 규칙, 청킹 순서 등을 먼저 맞춰야 한다.

---

## 2. 현재 상황

## 2.1 기존 ERD 기준

기존 ERD에는 `evidence_documents`, `evidence_chunks`가 아래처럼 단순하게 정의되어 있었다.

### evidence_documents

| 컬럼 | 설명 |
| --- | --- |
| document_id | 문서 ID |
| title | 문서명 |
| doc_type | 문서 유형 |
| category_tag | 문서 분류 태그 |
| effective_date | 시행일 |
| indexed_at | 인덱싱 시점 |

### evidence_chunks

| 컬럼 | 설명 |
| --- | --- |
| chunk_id | chunk ID |
| document_id | 원문 문서 ID |
| chunk_index | chunk 순서 |
| article_number | 조문 번호 |
| section_path | 섹션 경로 |
| content | chunk 본문 |

---

## 2.2 실제 수집 과정에서 확인된 추가 필요 metadata

법령, 시행령, 시행규칙, 별표, 가이드라인, 소비자원 사례 자료를 수집하면서 기존 ERD보다 더 많은 metadata가 필요하다는 점이 확인되었다.

추가로 필요해진 정보는 다음과 같다.

- 현행본 / 예정본 구분
- 같은 법령의 버전 묶음 관리
- 문서 세부 유형 구분
- regulatory / privacy / advertising 태그 분리
- 원문 URL 및 수집 출처 보관
- chunk별 페이지, 섹션, 조문 정보 관리
- 사례 단위 태그 관리
- vector DB 검색 결과와 Postgres metadata 연결

---

## 3. 제안하는 evidence_documents 스키마

현재 수집한 `evidence_documents_draft.csv` 기준으로 아래 컬럼을 제안한다.

| 컬럼 | 설명 |
| --- | --- |
| document_id | 문서 고유 ID |
| law_id | 같은 법령의 버전 묶음 ID |
| title | 문서명 |
| doc_type | LAW / GUIDE / CASE / REPORT |
| source_subtype | ACT, DECREE, RULE, ANNEX, MFDS_GUIDE, CASEBOOK 등 세부 유형 |
| issuing_org | 발행기관 |
| jurisdiction | 관할 국가 |
| rag_category | RAG 분류 |
| effective_date | 시행일 |
| publication_date | 발행일 |
| status | active / future / draft 등 |
| tag_regulatory | 규제 관련 여부 |
| tag_privacy | 개인정보 관련 여부 |
| tag_advertising | 광고 관련 여부 |
| source_url | 원문 URL |
| collection_source | 수집 경로 |
| processing_note | 처리 메모 |
| usage_scope | RAG / RULE_BASE / BOTH |
| content_hash | 중복 문서 방지용 해시 |
| indexed_at | vector DB 인덱싱 완료 시점 |

`usage_scope`, `content_hash`, `indexed_at`는 팀 논의 후 추가 여부를 확정하면 된다.

## 4. 제안하는 evidence_chunks 스키마

현재 생성한 `evidence_chunks_draft.csv` 기준으로 아래 컬럼을 제안한다.

| 컬럼 | 설명 |
| --- | --- |
| chunk_id | chunk 고유 ID |
| document_id | 원문 문서 ID |
| chunk_order | 문서 내 chunk 순서 |
| section_id | 조문/섹션/사례 ID |
| section_title | 조문/섹션 제목 |
| chunk_type | ARTICLE / GUIDE_SECTION / ANNEX_ITEM / CASE_ITEM 등 |
| chunk_text | chunk 본문 |
| page_start | 시작 페이지 |
| page_end | 끝 페이지 |
| char_count | 문자 수 |
| tag_regulatory | 규제 관련 여부 |
| tag_privacy | 개인정보 관련 여부 |
| tag_advertising | 광고 관련 여부 |
| case_tag_advertising | 사례 단위 광고 태그 |
| case_tag_privacy | 사례 단위 개인정보 태그 |
| case_tag_medical_device | 사례 단위 의료기기 태그 |
| case_tag_health_functional_food | 사례 단위 건강기능식품 태그 |
| effective_date | 근거 문서 시행일 |
| status | active / future 등 |
| source_url | 원문 URL |
| local_file_path | 로컬 원문 파일 경로 |

---

## 5. 기존 ERD 대비 주요 변경점

## 5.1 document_id, chunk_id는 UUID 대신 stable string ID 사용 제안

기존 ERD에서는 `document_id`, `chunk_id`가 UUID처럼 표현되어 있었지만, RAG 근거 문서에서는 사람이 읽을 수 있는 stable string ID가 더 적합하다.

예시:

```
kr-pipa-active-20251002
kr-pipa-decree-20260519
kr-mfds-wellness-0091-03-20260212
kr-pipa-active-20251002__0023
```

이 방식의 장점은 다음과 같다.

- 어떤 문서인지 바로 식별 가능
- 법령 개정 버전 관리가 쉬움
- `correction_rules.legal_basis_doc`에서 직접 참조하기 좋음
- vector DB metadata와 연결하기 쉬움
- 팀 간 문서 ID 공유가 쉬움

따라서 `document_id`, `chunk_id`는 UUID보다 `VARCHAR` 기반 stable ID를 사용하는 것을 제안한다.

---

## 5.2 category_tag 단일 컬럼 대신 태그 분리

기존 ERD의 `category_tag` 하나만으로는 문서가 어떤 판단축에 쓰이는지 구분하기 어렵다.

따라서 다음 Boolean 태그를 분리해서 관리하는 것을 제안한다.

```
tag_regulatory
tag_privacy
tag_advertising
```

예시:

| 문서 | tag_regulatory | tag_privacy | tag_advertising |
| --- | --- | --- | --- |
| 의료기기법 | true | false | true |
| 개인정보 보호법 | false | true | false |
| 웰니스 판단기준 | true | false | true |

이렇게 해야 Stage C의 `regulatory_score`, `privacy_score`, `advertising_score`와 연결하기 쉽다.

---

## 5.3 doc_type enum은 유지하고 세부 유형은 source_subtype으로 분리

원래 설계서의 `doc_type`은 다음 4개 enum으로 닫혀 있다.

```
LAW
GUIDE
CASE
REPORT
```

하지만 실제 수집 문서에는 시행령, 시행규칙, 별표, 안내서, 사례집 등 세부 유형이 필요하다.

따라서 `doc_type`은 기존 enum을 유지하고, 세부 유형은 `source_subtype`에 저장하는 방식을 제안한다.

예시:

| title | doc_type | source_subtype |
| --- | --- | --- |
| 의료기기법 | LAW | ACT |
| 개인정보 보호법 시행령 | LAW | DECREE |
| 의료기기법 시행규칙 별표7 | LAW | ANNEX |
| 웰니스 판단기준 | GUIDE | MFDS_GUIDE |
| 소비자 분쟁해결 우수사례집 | CASE | CASEBOOK |

이 방식이면 기존 enum 검증 로직을 깨지 않으면서 세부 분류를 관리할 수 있다.

---

## 5.4 article_number 대신 section_id 사용 제안

기존 ERD에는 `article_number`가 있었지만, 모든 문서가 조문 구조를 갖는 것은 아니다.

문서 유형별로 필요한 표기 방식이 다르다.

| 문서 유형 | 예시 section_id |
| --- | --- |
| 법령 | 제23조, 제24조 |
| 시행령 | 제18조 |
| 별표 | 별표7-1, 별표7-2 |
| 가이드라인 | Ⅲ.2.가, p12 |
| 사례집 | case-2025-001 |

따라서 `article_number`보다 더 일반적인 `section_id`를 사용하는 것이 적합하다.

---

## 6. 판단가이드 문서의 RAG 적재 여부

## 6.1 논의가 필요한 이유

현재 설계에는 “법령·규제 문서”와 “판단가이드/위험표현사전”의 경계가 명확히 고정되어 있지 않다.

예를 들어 지침서-0091-03은 Stage A/B 룰베이스 추출의 핵심 근거이지만, 사용자에게 판정 근거를 설명할 때도 매우 유용하다.

따라서 판단가이드 문서를 RAG DB에도 넣을지, 룰베이스 전용으로 둘지 팀 합의가 필요하다.

---

## 6.2 선택지

### 안 A. 판단가이드는 룰베이스 전용으로 둔다

이 경우:

- RAG DB에는 법령, 시행령, 시행규칙, 별표, 사례, 보고서 중심으로 적재
- 판단가이드는 `gate_keywords`, `gate_matrix`, `correction_rules` 추출용으로만 사용
- `usage_scope=RULE_BASE`로 관리
- 이미 생성한 웰니스 판단기준 chunk는 `evidence_chunks`에서 제외하거나 `reference_only` 상태로 둠

장점:

- RAG 검색 결과가 법령/사례 중심으로 정리됨
- 판정 로직과 근거 검색 역할이 분리됨

단점:

- Stage A/B 판단 근거를 사용자에게 직접 보여주기 어려움

---

### 안 B. 판단가이드도 RAG에 함께 넣는다

이 경우:

- 지침서-0091-03, 모바일앱지침, LLM 가이드라인도 `evidence_documents`에 유지
- `doc_type=GUIDE`, `source_subtype=MFDS_GUIDE`로 관리
- `usage_scope=BOTH`로 관리
- RAG 검색 시 법령과 가이드를 모두 근거로 제공

장점:

- 설명 가능성이 좋아짐
- “왜 웰니스/의료기기로 판단했는지”를 사용자에게 보여주기 쉬움
- 룰베이스와 RAG가 같은 document_id를 참조할 수 있음

단점:

- RAG 검색 결과에서 법령보다 가이드가 과도하게 노출될 수 있음
- 검색 필터링 정책이 필요함

현재 작업 기준으로는 **안 B를 제안**한다.

지침서-0091-03은 Stage A/B 판정의 핵심 근거이고, 사용자 설명에도 활용 가치가 크기 때문이다.

---

## 7. load_shared_chunks 인터페이스 합의안

룰베이스 파이프라인에서 `load_shared_chunks` 노드를 사용하려면, RAG DB에서 chunk를 조회하는 입력/출력 형식을 맞춰야 한다.

## 7.1 ID 기반 조회

입력 예시:

```
{
  "document_id": "kr-pipa-active-20251002",
  "section_id": "제23조",
  "chunk_type": "ARTICLE"
}
```

출력 예시:

```
{
  "chunk_id": "kr-pipa-active-20251002__0023",
  "document_id": "kr-pipa-active-20251002",
  "section_id": "제23조",
  "section_title": "제23조(민감정보의 처리 제한)",
  "chunk_text": "...",
  "source_url": "...",
  "page_start": 12,
  "page_end": 13,
  "effective_date": "2025-10-02",
  "status": "active"
}
```

## 7.2 검색 기반 조회

입력 예시:

```
{
  "query": "민감정보 건강정보 처리 제한",
  "tag_privacy": true,
  "status": "active"
}
```

출력은 관련 chunk 목록으로 반환한다.

---

## 8. 청킹 순서 및 의존관계

룰베이스 파이프라인이 법령·규제 문서를 만났을 때 RAG가 이미 청킹해둔 chunk를 조회한다는 전제가 생긴다.

따라서 아래 정책을 정해야 한다.

| 항목 | 결정 필요 |
| --- | --- |
| 법령·규제 문서는 누가 먼저 업로드하는가 | RAG 담당 / 룰베이스 담당 / 공통 |
| RAG 청킹이 아직 안 된 문서면 어떻게 할 것인가 | 대기 / 알림 / 룰베이스 자체 청킹 fallback |
| `chunking_queue.csv`를 팀 공통 큐로 쓸 것인가 | 사용 / 미사용 |
| 청킹 단위는 어떻게 맞출 것인가 | 조문 / 항 / 호 / 문단 / 사례 단위 |

현재 제안은 다음과 같다.

- 문서 등록과 청킹은 RAG 담당이 우선 수행
- 룰베이스는 `document_id`, `section_id` 기준으로 조회
- 아직 청킹되지 않은 문서는 fallback보다 “대기/알림” 처리
- `chunking_queue.csv`를 공통 작업 큐로 사용

---

## 9. document_id 발급 프로토콜

같은 문서를 양쪽에서 각각 등록하면 `evidence_documents`에 중복 레코드가 생길 수 있다.

따라서 document_id 발급 규칙이 필요하다.

## 9.1 제안 규칙

```
국가-기관/법령명-문서상태/버전-시행일 또는 발행일
```

예시:

```
kr-pipa-active-20251002
kr-pipa-future-20260911
kr-pipa-decree-20260519
kr-medical-device-act-20260701
kr-mfds-wellness-0091-03-20260212
```

## 9.2 중복 방지

중복 방지를 위해 다음 중 하나를 선택한다.

| 방식 | 설명 |
| --- | --- |
| 담당자 단일 등록 | RAG 담당자가 evidence_documents 등록을 전담 |
| 파일 해시 기반 upsert | 같은 파일이면 기존 document_id 재사용 |
| URL 기반 upsert | 같은 source_url이면 기존 document_id 재사용 |

현재 제안은 **RAG 담당자가 문서 등록을 전담하고, 추후 content_hash 기반 upsert를 추가**하는 방식이다.

---

## 10. FastAPI DB 반영 계획

팀 합의 후 FastAPI 백엔드에 다음 작업을 진행한다.

프로젝트 경로:

```
/Users/munchaerin/Code/PREP-BE
```

추가 예정 파일:

```
app/db/models/evidence_document.py
app/db/models/evidence_chunk.py
alembic/versions/xxxx_add_evidence_documents_and_chunks.py
scripts/import_evidence_csv.py
```

구현 작업:

- `EvidenceDocument` SQLAlchemy 모델 추가
- `EvidenceChunk` SQLAlchemy 모델 추가
- Alembic migration 추가
- CSV import script 작성
- `evidence_documents_draft.csv` 적재
- `evidence_chunks_draft.csv` 적재
- 향후 vector DB 적재 시 `chunk_id` 기준으로 Postgres metadata 연결

---

## 11. 현재 1차 작업 결과 및 이슈

현재 `chunking_queue.csv` 1~5번 문서 기준으로 `evidence_chunks_draft.csv` 초안을 생성했다.

| 문서 | chunk 생성 상태 |
| --- | --- |
| 의료기기와 개인용 건강관리 웰니스 제품 판단기준 | 완료 |
| 의료기기법 시행규칙 | 완료 |
| 의료기기법 | 부분 완료 |
| 개인정보 보호법 | 완료 |
| 개인정보 보호법 시행령 | 완료 |

주의사항:

| 항목 | 상태 |
| --- | --- |
| 의료기기법 시행규칙 별표7 | 현재 로컬 PDF에 실제 별표7 본문이 없어 별도 확보 필요 |
| 의료기기법 | 현재 파일에서 제2조만 추출되어 전체 본문 재확보 필요 |

따라서 DB 스키마 구축은 진행 가능하지만, 위 두 문서는 추가 확보 후 chunk 보완이 필요하다.

---

## 12. 팀 확인 요청 사항

아래 항목에 대해 팀 합의가 필요하다.

| 번호 | 확인 항목 | 명진 |
| --- | --- | --- |
| 1 | `document_id`, `chunk_id`를 UUID가 아니라 stable string ID로 사용해도 되는가 | 조아연. 그거 맞춰서 수정해놓을게여 |
| 2 | `category_tag` 대신 `rag_category`, `tag_regulatory`, `tag_privacy`, `tag_advertising`로 분리해도 되는가 | 조아연 |
| 3 | `doc_type`은 `LAW/GUIDE/CASE/REPORT`로 유지하고 세부 유형은 `source_subtype`으로 관리해도 되는가 | 조아연 |
| 4 | `article_number` 대신 `section_id`, `section_title`, `chunk_type` 구조를 사용해도 되는가 | 조아연
근데 section_id표기를 룰베이스에 맞춰줘야할듯  |
| 5 | 판단가이드 문서를 RAG에도 적재할 것인가, 룰베이스 전용으로 둘 것인가 | rag에도 적재 …. 리포트낼때 근거에 결국 필요할듯  |
| 6 | `usage_scope=RAG/RULE_BASE/BOTH` 컬럼을 추가할 것인가 | 조아연 |
| 7 | 문서 등록은 RAG 담당이 전담하고 룰베이스는 조회만 하는 방식으로 갈 것인가 | 찬성 |
| 8 | 청킹 미완료 문서가 있을 때 룰베이스는 대기/알림 처리할 것인가, 자체 fallback을 둘 것인가 | 대기알림 처리 조은듯  |
| 9 | schema 변경 시 PR 리뷰 및 사전 공유를 필수로 할 것인가 | 무족권 … |

---

## 13. 팀원에게 남길 메시지

아래 문구로 공유하면 된다.

> RAG DB 구축 전에 `evidence_documents`, `evidence_chunks` 스키마와 룰베이스의 `load_shared_chunks` 조회 방식을 먼저 맞추려고 합니다.
> 
> 
> 실제 자료 수집 과정에서 기존 ERD보다 metadata가 늘어나서, `document_id/chunk_id`는 UUID 대신 stable string ID를 쓰고, `category_tag`는 `tag_regulatory/tag_privacy/tag_advertising`로 분리하는 방향을 제안합니다.
> 
> 또 법령·가이드·별표·사례를 모두 표현하기 위해 `article_number` 대신 `section_id/section_title/chunk_type` 구조를 쓰려고 합니다.
> 
> 판단가이드 문서는 `usage_scope=RAG/RULE_BASE/BOTH`로 구분해서, RAG 근거와 룰베이스 추출 근거 양쪽에서 쓸 수 있게 하는 안을 제안합니다.
> 
> 이 방향으로 FastAPI DB 모델과 Alembic migration을 만들어도 괜찮을지 확인 부탁드립니다.
> 

---

## 14. 결론

기존 ERD의 방향성은 유지하되, 실제 RAG DB와 룰베이스 연동을 위해 `evidence_documents`, `evidence_chunks`는 확장하는 것이 필요하다.

핵심 변경은 다음과 같다.

- `document_id`, `chunk_id`: UUID → stable string ID
- `category_tag`: 단일 태그 → `rag_category` + 3축 Boolean 태그
- `article_number`: 조문 전용 → `section_id` 범용 구조
- 판단가이드 문서: `usage_scope`로 RAG/RULE_BASE/BOTH 구분
- RAG 담당이 문서 등록 및 청킹을 우선 수행하고, 룰베이스는 `load_shared_chunks`로 조회

팀 합의 후, 위 스키마 기준으로 FastAPI DB 모델과 migration을 구현한다.

---

### 요청사항

### 1. 문서 추가

| 문서 | 필요 이유 |
| --- | --- |
| **약사법** | 2026-07-26 확정 — 약무행위(처방·조제·복약지도)를 4번째 축 신설 없이 `regulatory_score`에 흡수하기로 함. gate_keywords에 약무 키워드를 시딩할 때 근거 조문 필요 |
| **보건복지부 비의료 건강관리 서비스 가이드라인** | 웰니스와 의료의 경계를 가르는 핵심 문서인데 수집 목록에 없음. Before→After 교정 근거로도 쓰임 |

### 2. section_id 표기

이걸 양쪽에서 맞춰야한다함. 나는 아래처럼 쓰고 있어서
**지침서 조문 표기 그대로 쓰는걸로 section_id 표기**를 맞추면 좋을거같아.
근데 그대로 쓰면 로마자는 좀 인식하기 어려워해서 지침서 조문 표기 + 정규화 규칙 적용하면 될듯?

| 문서 | 룰베이스에서 쓰는 표기 |
| --- | --- |
| 웰니스판단기준 0091-03 | `Ⅲ.2.가`, `Ⅲ.나`, `Ⅳ.1.가`, `Ⅳ.2.나`, `Ⅳ.3` |
| 모바일 의료용 앱 안전관리 지침 | `Ⅲ.2.2`, `Ⅲ.2.5`, `Ⅲ.3.3`, `Ⅲ.3.5`, `부록2 Q1`, `부록2 Q11` |
| 의료기기법 | `제2조`, `제24조` |
| 개인정보보호법 | `제23조`, 시행령 `제18조` |
| 의료기기법 시행규칙 | `제45조`, `별표7 제1호`~`제18호` |

정규화 규칙

| 항목 | 제안 |
| --- | --- |
| 로마숫자 | ASCII 대문자로 통일 (`Ⅲ` → `III`) — 입력·검색·비교가 안전 |
| 구분자 | 마침표 `.` 통일, 끝에 마침표 없음 |
| 공백 | 제거 (`부록2 Q11` → `부록2.Q11`) |
| 조문 | `제23조` 형태 유지 |
| 별표 | `별표7.제8호` 형태 |

### 3.의료기기법 시행규칙 별표7 본문 미확보 해결

rag 보고서 §11에 "추가 확보 필요"로 적혀 있는데, 무조건 필요할듯
`advertising_score` 척도가 별표7 18개 항목에 100% 의존해 설계되어있음

| 점수 | 별표7 항목 |
| --- | --- |
| 3 | 1·2·4·8·9·15·17·18호 |
| 2 | 3·5·6·7·10·11·14호 |
| 1 | 12·13·16호 |

별표7 본문이 없으면 리포트 SECTION 2-1(규제 위험도)의 광고 판단근거에 **근거 조문을 표시할 수 x** Stage C는 이미 구현돼 LLM이 별표7 신호어로 점수를 매기고 있는데, 정작 그 근거를 RAG에서 못 꺼내와버림. 필수 문서 8개 중 최우선 확보 필요

### 4. 의료기기법 제24조 미추출

현재 파일에서 제2조만 추출되어있는데, **제24조(기재 및 광고의 금지)가 빠져 있음**

제24조는 `advertising_score`의 **주 근거 조문**
의료법 제56조는 적용 대상이 "의료인등"으로 한정돼 앱 개발사에는 직접 적용되지 않아 보조 근거로만 쓰고 있어서 별표7과 세트로 필요

### 5. 별표7은 항목 번호 단위(제1호~제18호)로 분할 요청

**이유 설명은 아래와 같음
점수 매핑과 1:1로 붙습니다.** 

별표7 18개 항목이 점수별로 **흩어져 있습니다**(1·2·4·8… 형태로 연속 구간이 아님). 항목 하나하나가 독립적인 판정 단위입니다.

통짜 chunk일 경우:

```
LLM 판정: "8호(거짓·과장 광고) 해당 → 3점"
        ↓
근거를 표시하려면 별표7 전체(18개 항목)를 통째로 띄워야 함
        ↓
리포트 §2-1의 "참고 법령 inline 표시" 요구사항을 충족 불가
사용자는 18개 중 어디에 걸렸는지 알 수 없음
```

항목 단위 분할 시:

```
LLM 판정: "8호 해당 → 3점"
        ↓
section_id = '별표7.제8호' 로 정확히 조회
        ↓
해당 항목 원문만 짧게 인라인 인용
```

**부가 이득 3가지**

1. **벡터 검색 품질** — 별표7 전체를 한 chunk로 임베딩하면 18개 항목의 의미가 뭉개져 "허위광고" 쿼리 정확도가 떨어집니다. 항목별로 쪼개면 각 항목의 의미가 살아있는 벡터가 됩니다.
2. **척도 조정 용이** — 향후 "8호를 2점으로" 같은 조정 시 chunk는 그대로 두고 매핑만 수정하면 됩니다.
3. **검증 가능성** — `advertising_score`는 3축 중 **유일하게 LLM이 직접 판단**하는 축입니다(regulatory·privacy는 테이블 조회 파생). LLM 판단이므로 "왜 이 점수인지"를 조문으로 되짚을 수 있어야 신뢰가 생깁니다.

**비용**: chunk 18개 증가. 33개 문서 전체 규모에서 무시할 수준이며, 각 항목이 짧아 chunk 크기도 적정합니다.