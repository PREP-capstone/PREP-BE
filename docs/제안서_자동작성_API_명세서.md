# 제안서 자동 작성 API 명세서

> 관련 이슈: #102
> `판정_API_명세서.md`/`시장성_BM_API_명세서.md`와 같은 포맷.
> DB 저장 없음(`db_구축_설계서.md` §1.3 "사용자 입력·분석결과 미저장" 원칙) — Redis TTL 캐시만 사용. `미결정_항목_정리.md` #1(E-4) "리포트 재조회·창업제안서 연계 방식 미정"을 본 문서로 확정한다.
>
> ⚠️ **리뷰 중 발견 1 (2026-09-07)**: `app/db/models/analysis_session.py`를 확인한 결과 `analysis_sessions`는 실제로 **Postgres에 영구 저장**되며, 삭제/TTL 로직이 코드에 없다. §10.4 원칙이 검진 세션 자체에는 아직 구현돼 있지 않다.
>
> ⚠️ **리뷰 중 발견 2 (2026-09-07, main 병합 후)**: 위 발견 1을 근거로 처음엔 "PDF 재업로드 대신 `session_id` 직접 참조"로 단순화했었는데, 본 PR 작업 중 **`feat/funding-pdf-recommendations`(PR #101)가 먼저 main에 병합**돼 같은 문제(검진 리포트 → 후속 기능)를 이미 **"리포트 PDF 업로드 + 텍스트 추출"** 방식으로 풀어놓은 걸 발견했다(`app/api/funding.py`, `app/domain/funding_match.py`). `session_id` 참조 방식으로 가면 이 기존 컨벤션과 갈라지고, `analysis_sessions`에 나중에 실제 TTL이 붙으면 참조 자체가 깨진다. **PDF 업로드 방식으로 되돌리고, funding.py 컨벤션을 그대로 따른다.**

## 0. 전체 흐름

```
[아이디어 검진] 진행 → 결과 리포트 PDF 다운로드
        │
        ▼
[제안서 자동 작성] 탭에서 리포트 PDF 업로드 + 지원사업 유형 선택
        │
        ▼
POST /proposals/generate (multipart/form-data)
  ── PDF 텍스트 추출(funding.py와 동일 방식) + LLM이 유형별 필드 매트릭스 기준 초안 생성
        │
        ▼ (사용자가 화면에서 초안 검토/수정)
        │
"완료" 버튼 또는 "PDF 저장하기" 버튼
        │
        ▼
POST /proposals/{id}/complete  ── 이 시점부터 Redis TTL 10분 시작
        │
        ▼
GET /proposals/{id}/pdf  ── 10분 이내에만 다운로드 가능, 이후 자동 삭제
```

- 작성 중(완료 전) 상태는 **프론트 로컬 state로만 유지**한다. "임시저장" API는 없음.
- "완료"와 "PDF 저장하기"는 **동일한 트리거**로 취급한다 — 둘 중 어느 쪽을 먼저 눌러도 그 시점부터 10분 TTL이 시작된다. (프론트 확인 완료, 2026-09-07)
- 검진 결과는 **리포트 PDF 업로드**로 받는다 — `session_id` 참조가 아니라 `app/api/funding.py`(PR #101)와 동일한 "PDF 업로드 → 텍스트 추출" 패턴을 따른다. `analysis_sessions`에 나중에 TTL이 붙어도 영향받지 않는 구조.
- 제안서 자체는 검진 결과와 동일한 캐시 클라이언트/패턴 재사용: `app/core/redis_client.py`, `ex=` TTL 방식 (`trend_client.py`, `correction_llm.py` 참조).

## 1. 지원사업 유형 (template_type)

| 코드 | 명칭 | 비고 |
|---|---|---|
| `PSST` | 창업사업화 지원사업 (PSST 표준형) | 예비창업패키지·초기창업패키지·창업도약패키지 등. Problem-Solution-Scaleup-Team |
| `RND` | R&D 과제형 (기술개발사업) | 총괄연구개발계획·연구비 산정 등 PSST와 별도 양식 |
| `IR` | 투자유치용 (IR) | 민간 VC/엔젤 투자자 대상. TAM/SAM/SOM·재무추정·지분구조 포함 |

`category_1`(String(80) 자유 텍스트)과 동일한 이유로 `template_type`도 DB에서는 **닫힌 enum이 아니라 자유 텍스트**로 둔다 — 새 유형이 추가돼도 스키마 변경 없이 §3의 매핑 테이블에 행만 추가하면 된다.

## 2. 유형별 필드 매트릭스

범례: ● 필수 / ○ 선택 / − 제외

### 2.0 일반현황·개요
| field_key | 항목 | PSST | RND | IR |
|---|---|---|---|---|
| `company_overview` | 기업개요·대표자 | ● | ● | ● |
| `idea_overview` | 창업아이템 개요 | ● | ● | ● |
| `location_timing` | 창업예정지·시기 | ● | ○ | − |
| `project_period` | 사업 수행기간(총수행기간·협약기간) | ● | ● | ● |

### 2.1 문제인식
| field_key | 항목 | PSST | RND | IR |
|---|---|---|---|---|
| `background_motivation` | 개발 배경·동기 | ● | ● | ● |
| `target_market_analysis` | 목표시장 분석 | ● | ● | ● |

### 2.2 실현가능성
| field_key | 항목 | PSST | RND | IR |
|---|---|---|---|---|
| `dev_status` | 개발/사업화 현황 | ● | ● | ● |
| `feasibility_diff` | 실현방안·차별점 | ● | ● | ● |
| `ip_plan` | 지식재산권 확보 계획 | − | ○ | ○ |

### 2.3 성장전략
| field_key | 항목 | PSST | RND | IR |
|---|---|---|---|---|
| `funding_plan` | 자금조달 계획 | ● | ● | ● |
| `revenue_model` | 수익모델·시장진입 | ● | ● | ● |
| `schedule` | 사업 추진 일정 | ● | ● | ● |
| `growth_targets` | 정량적 성장목표(3개년 매출·고용 수치) | ● | ● | ● |
| `exit_strategy` | 출구(EXIT) 전략 | − | − | ○ |
| `overseas_expansion` | 해외시장 진출전략(타겟국가·GTM·진출실적) | ○ | − | ○ |

### 2.4 팀 구성
| field_key | 항목 | PSST | RND | IR |
|---|---|---|---|---|
| `founder_capability` | 대표자 역량 | ● | ● | ● |
| `team_hiring_plan` | 팀 구성·고용계획 [^1] | ● | ● | ● |
| `new_hire_plan` | 신규 인력 채용계획(고용창출 목표, 정량) | − | ● | ○ |
| `partnership` | 파트너십·외부협력 | − | ○ | ○ |

[^1]: PSST 유형에서는 `new_hire_plan`(신규 인력 채용계획)을 별도 필드로 분리하지 않고 `team_hiring_plan` 안에 포함해서 작성한다.

### 2.5 PREP 특화 항목
| field_key | 항목 | PSST | RND | IR |
|---|---|---|---|---|
| `regulatory_compliance` | 규제 준수 및 리스크 대응 | ● | ● | ○ |
| `data_strategy` | 데이터 확보 전략 | ● | ● | ○ |
| `general_risk_mgmt` | 일반 리스크 관리 계획(시장·운영 리스크) | ○ | ○ | ○ |
| `program_utilization` | 지원 프로그램 활용계획(참가목적 등) | ○ | ○ | ○ |

### 2.6 R&D 특화 항목
| field_key | 항목 | PSST | RND | IR |
|---|---|---|---|---|
| `rd_plan_budget` | 연구개발목표·연구비산정·참여연구원 | − | ● | − |
| `annual_budget_exec` | 연차별 사업비 집행계획(정부출연금/자기부담금 현금·현물 구분) | − | ● | − |
| `rd_track_record` | 정부지원 수혜실적 및 기존 R&D 이력 | − | ● | − |
| `trl_level` | 기술성숙도(TRL, 1~9단계) 현재 수준 및 목표 수준 | − | ● | ○ |

### 2.7 투자유치용(IR) 추가 항목
| field_key | 항목 | PSST | RND | IR |
|---|---|---|---|---|
| `esg` | 사회적 가치·ESG | − | − | ○ |
| `bonus_criteria` | 우대 가점 사항 | − | ○ | ○ |
| `financial_projection` | 재무 추정(3~5개년, BEP) | − | − | ○ |
| `tam_sam_som` | TAM/SAM/SOM 시장규모 | − | − | ○ |
| `cap_table` | 지분구조(캡테이블) | − | − | ○ |

### 2.8 첨부서류 (텍스트 작성이 아닌 체크리스트 — §3의 field_type=CHECKLIST)
| field_key | 항목 | PSST | RND | IR |
|---|---|---|---|---|
| `attachment_checklist` | 첨부서류 체크리스트(사업자등록증·재무제표·납세증명서 등) | ● | ● | ● |

> `overseas_expansion`, `program_utilization`은 실제 지원사업 공고문 5건(인천공항공사 상생형·모두의창업·GX 오사카 Plug in·예비창업패키지·강북창업지원센터) 분석 과정에서 기존 매트릭스에 없던 항목으로 신규 확인되어 이번 작업에서 추가함 (근거는 이슈 #102 참고).
>
> `trl_level`은 R&D 과제형 사업계획서의 표준 평가지표(기술성숙도, 1~9단계)로 재확인되어 추가함 — R&D 특화 항목 3종(연구개발목표·연차별 사업비·수혜실적)에 빠져있던 항목. 검토 과정에서 함께 검토한 신청현황/중복지원 확인/주요 연혁/트랙션 지표/가격정책은 이번 매트릭스에는 포함하지 않기로 함(팀 판단, 2026-09-07).

## 3. DB 스키마 (신규, 고정 참조 데이터 — `data_difficulty`/`collection_difficulty`와 동일한 "고정 기준표" 패턴)

1차 초안의 `psst_requirement`/`rnd_requirement`/`ir_requirement` 3-컬럼 설계를 **폐기**했다 — 새 지원사업 유형이 추가될 때마다 컬럼을 늘려야 해서(ALTER TABLE) 교수님 피드백("표준 양식 하나로 고정하지 말고 확장 가능하게")과 정면으로 배치된다. `gate_matrix`처럼 **행 단위**로 바꿔 새 유형 추가 시 INSERT만으로 끝나게 한다.

### 3.1 `proposal_field_definitions` — 필드 자체의 정적 정보 (필드당 1행)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| field_key | VARCHAR, PK | 위 표의 field_key |
| category | VARCHAR | 일반현황 / 문제인식 / 실현가능성 / 성장전략 / 팀구성 / PREP특화 / RND특화 / IR추가 / 첨부서류 |
| label | VARCHAR | 화면 표시용 라벨 |
| description | TEXT | 작성 가이드 문구 (nullable) |
| field_type | VARCHAR | `TEXT`(서술형) / `CHECKLIST`(체크리스트) / `TABLE`(연도별 표 — 예: growth_targets, annual_budget_exec) |
| display_order | INTEGER | 화면 노출 순서 |

### 3.2 `proposal_template_field_map` — 유형×필드별 필수/선택 (유형-필드 쌍당 1행)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| template_type | VARCHAR | PSST / RND / IR (자유 텍스트, §1 참고) |
| field_key | VARCHAR, FK → proposal_field_definitions | |
| requirement | VARCHAR | REQUIRED / OPTIONAL (EXCLUDED는 행 자체를 안 만드는 것으로 표현 — 조회 시 없으면 제외) |

새 지원사업 유형이 추가되면 `proposal_template_field_map`에 행만 추가하면 되고, 겹치는 필드가 이미 있으면 `proposal_field_definitions`도 건드릴 필요 없다.

## 4. Headers

Authorization: Bearer `<accessToken>`

## 5. API 목록

### 5.1 `GET /api/v1/proposals/field-definitions?template_type={PSST|RND|IR}`

유형 선택 시 프론트가 동적으로 폼을 렌더링하기 위한 필드 목록 조회. `proposal_field_definitions` ⋈ `proposal_template_field_map`을 `template_type`으로 조회 — 매핑 행이 없는 필드(=EXCLUDED)는 응답에서 자연히 빠진다.

```json
{
  "isSuccess": true,
  "code": "COMMON200",
  "message": "성공",
  "result": {
    "template_type": "PSST",
    "fields": [
      { "field_key": "company_overview", "category": "일반현황", "label": "기업개요·대표자", "field_type": "TEXT", "requirement": "REQUIRED", "display_order": 1 },
      { "field_key": "attachment_checklist", "category": "첨부서류", "label": "첨부서류 체크리스트", "field_type": "CHECKLIST", "requirement": "REQUIRED", "display_order": 40 },
      { "field_key": "overseas_expansion", "category": "성장전략", "label": "해외시장 진출전략", "field_type": "TEXT", "requirement": "OPTIONAL", "display_order": 22 }
    ]
  }
}
```

### 5.2 `POST /api/v1/proposals/generate` (multipart/form-data)

`app/api/funding.py`(`/api/v1/funding/recommendations`)와 **동일한 요청 스타일**을 따른다 — 리포트 PDF는 `UploadFile`, 나머지는 `Form` 필드.

| 파트 | 타입 | 설명 |
|---|---|---|
| `report` | File (PDF) | 검진 결과 리포트 PDF. 10MB 제한(`_MAX_REPORT_BYTES`, funding.py와 동일 기준) |
| `template_type` | Form | `PSST` / `RND` / `IR` |
| `field_values` | Form (JSON 문자열) | 사용자가 화면에서 채운 필드값. `{"company_overview": "...", "attachment_checklist": ["사업자등록증"], ...}` |

리포트 PDF 텍스트 추출은 funding.py의 `_extract_pdf_text`/`_is_pdf`를 그대로 재사용하거나(가능하면 `app/domain/pdf_utils.py` 등 공유 모듈로 뽑아서 두 기능이 함께 쓰는 것을 권장 — §6-3 참고), 최소한 같은 에러 코드 네이밍(`PROPOSAL_REPORT_PDF_REQUIRED`/`PROPOSAL_REPORT_TOO_LARGE`)을 맞춘다.

`field_values`의 값 타입은 §3.1 `field_type`을 따른다 — `TEXT`는 문자열, `CHECKLIST`는 문자열 배열, `TABLE`은 `[{"year": 1, "revenue_krw": 0, "headcount": 0, "basis": "..."}, ...]` 형태의 배열(필드별 정확한 컬럼은 `app/domain/proposal_llm.py`의 `TABLE_ITEM_SCHEMAS` 참고).

```json
// 에러 응답 예시 (400 / 413, funding.py와 동일 패턴)
{ "isSuccess": false, "code": "PROPOSAL_REPORT_PDF_REQUIRED", "message": "PDF 파일만 업로드할 수 있습니다.", "result": null }
```

```json
// 성공 응답
{
  "isSuccess": true,
  "code": "COMMON200",
  "message": "성공",
  "result": {
    "proposal_id": "string",
    "template_type": "PSST",
    "llm_status": "ok",
    "sections": [
      { "field_key": "company_overview", "label": "기업개요·대표자", "field_type": "TEXT", "value": "string" },
      { "field_key": "attachment_checklist", "label": "첨부서류 체크리스트", "field_type": "CHECKLIST", "value": ["사업자등록증(또는 사업자등록 예정 확인서)", "대표자 신분증 사본", "개인정보 수집·이용 동의서"] },
      { "field_key": "growth_targets", "label": "정량적 성장목표", "field_type": "TABLE", "value": [ { "year": 1, "revenue_krw": 50000000, "headcount": 2, "basis": "..." } ] }
    ]
  }
}
```

`sections`는 세 갈래로 채워진다: ① 사용자가 이미 입력한 필드는 그 값 그대로, ② `CHECKLIST` 타입(`attachment_checklist`)은 `app/domain/proposal_llm.py`의 `ATTACHMENT_CHECKLISTS`에서 유형별 고정 목록을 조회(LLM 미사용), ③ 나머지(TEXT/TABLE, 사용자 미입력분)만 **유형 하나당 LLM 호출 1번**으로 한꺼번에 생성한다 — 33개 필드를 각각 호출하지 않는다.

자동 생성 문장은 심사위원이 읽는 제안서 문서체로 작성한다. 기본 종결은 `~이다`, `~한다`, `~함`을 사용하며 `~입니다`, `~합니다`, `~하세요`와 같은 존댓말·대화체 종결은 사용하지 않는다. 표와 목록도 같은 문체를 유지한다.

`llm_status`가 `"unavailable"`이면 ③에 해당하는 필드들이 실제 생성 대신 자리표시자(`"[자동 생성 실패 -- 직접 입력해주세요: <라벨>]"`, TABLE은 빈 배열)로 채워진 것이다 — §10.1 원칙("LLM 장애로 핵심 응답이 깨지면 안 된다")에 따라 요청 자체는 502로 실패하지 않는다. 프론트는 이 값을 보고 안내 배너를 띄우는 걸 권장.

이 시점(완료 전)에는 이 응답 전체를 캐시에 저장하지 않는다 — 재요청 시 매번 새로 생성. (단, ③의 LLM 호출 결과 자체는 `app/domain/proposal_llm.py` 내부에서 동일 입력이면 10분간 재사용된다 — 완료 전 재시도 비용 절감용으로, 제안서 자체의 10분 TTL과는 별개 목적이다.)

### 5.3 `POST /api/v1/proposals/{proposal_id}/complete`

"완료" 또는 "PDF 저장하기" 클릭 시 호출. 사용자가 수정한 최종본을 받아 Redis에 저장하고 10분 TTL을 시작한다.

```json
// 요청 -- template_type은 GET .../pdf가 문서 제목을 고르는 데 필요해서 이 시점에 함께 저장한다.
// 섹션은 field_key와 value만 보낸다. label/field_type은 서버가 proposal_field_definitions에서
// 조회해 채우므로 프론트가 실어보낼 필요 없다(잘못된 field_type을 보내 PDF 렌더링이 깨지는 것도 방지).
// value 타입은 generate 응답과 동일하게 field_type을 따른다(TEXT=문자열/CHECKLIST=배열/TABLE=배열)
{
  "template_type": "PSST",
  "sections": [
    { "field_key": "company_overview", "value": "사용자가 수정한 최종본" }
  ]
}
```

에러: `template_type`이 PSST/RND/IR이 아니면 `PROPOSAL_TEMPLATE_TYPE_INVALID`(400), 존재하지 않는 `field_key`가 섞여 있으면 `PROPOSAL_FIELD_KEY_INVALID`(400).

```json
// 응답
{
  "isSuccess": true,
  "code": "COMMON200",
  "message": "성공",
  "result": { "proposal_id": "string", "expires_at": "2026-09-07T12:10:00+09:00" }
}
```

### 5.4 `GET /api/v1/proposals/{proposal_id}/pdf`

10분 이내에만 다운로드 가능. `complete` 호출 전이면 404. **응답이 JSON이 아니라 실제 PDF 바이너리다** (`Content-Type: application/pdf`, `Content-Disposition: attachment; filename="proposal_{id}.pdf"`).

`app/domain/proposal_pdf.py`(reportlab)가 렌더링한다. 한글은 PDF 표준 CID 폰트(예: HYGothic-Medium)를 쓰지 않는다 — 실제로 렌더링해보니 한글 폰트가 없는 뷰어/서버에서는 글자가 통째로 빈 칸으로 나오는 걸 확인했다. 대신 나눔고딕 TTF를 `app/assets/fonts/`에 실제로 넣고 PDF에 임베딩한다(자동 서브셋팅으로 실사용 용량은 수십 KB 수준, OFL 라이선스로 재배포 가능).

```json
// 만료/미완료 시 에러 응답 (404, 이 경우만 JSON)
{
  "isSuccess": false,
  "code": "PROPOSAL_NOT_FOUND",
  "message": "제안서를 찾을 수 없거나 만료되었습니다.",
  "result": null
}
```

## 6. 후속 논의 필요

| # | 항목 |
|---|---|
| 1 | `generate` 응답 이후 사용자가 재생성을 요청할 수 있는 횟수 제한 여부 |
| 2 | **(리뷰 중 갱신)** PDF 텍스트 추출(`_extract_pdf_text`/`_is_pdf`, PDF 검증·크기 제한)을 `funding.py`와 이 기능이 각각 구현할지, `app/domain/pdf_utils.py` 같은 공유 모듈로 뽑을지 — funding 담당과 협의 필요 |
| 3 | `extract_funding_profile`(funding_match.py)이 리포트에서 이미 `category_1`/`category_2`/`service_type`/`target`/`region`/`stage`를 추출하고 있음 — 이 결과를 제안서 `field_values`의 일부(예: `target_market_analysis`, `company_overview`) 초기값으로 재사용해 사용자 입력 부담을 줄일 수 있는지 검토 |
| 4 | **(구현 완료, 2026-09-07)** LLM 프롬프트 설계 — `app/domain/proposal_llm.py`. 유형 하나당 호출 1번으로 묶어 TEXT/TABLE 필드를 한꺼번에 생성(`correction_llm.py`와 동일한 json_schema strict + Redis 캐싱 컨벤션) |
| 5 | **(구현 완료, 2026-09-07)** 실제 PDF 바이너리 생성 — `app/domain/proposal_pdf.py`(reportlab + 나눔고딕 임베딩). §6-1(동기 생성 vs presigned URL)은 동기 생성으로 확정 — 문서 분량이 크지 않아 presigned URL 인프라(S3 등)를 새로 둘 필요가 없다고 판단 |
| 6 | `ATTACHMENT_CHECKLISTS`(유형별 첨부서류 고정 목록, `app/domain/proposal_llm.py`)는 통상적으로 공통 요구되는 항목 기준의 초안이다 — 배포 전 실제 공고문으로 재대조 필요 |
| 7 | 프론트 실제 연동 — 지금까지는 백엔드 단독 구현/테스트만 진행함 |
