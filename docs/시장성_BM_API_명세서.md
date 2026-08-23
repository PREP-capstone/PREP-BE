# 시장성·BM API 명세서

> 담당: 3번(시장성/BM/리포트) · 작업 #7(이슈 #31) — `판정_API_명세서.md`(1번 담당)와 같은 포맷.
> 최신 코드 기준(`app/api/feasibility.py`의 `/market`, `app/api/business_model.py`).

이 2개 API는 `session_id`(2번의 `analysis-sessions` API로 미리 만든 세션)만 받고,
실제 판단 대상 데이터(`category_1`/`category_2`/`target`/`service_type`)는 서버가
`analysis_sessions` 테이블에서 직접 조회한다 — 1번 담당 judgement API·2번 담당
`feasibility/data` API와 같은 흐름이다.

## Headers

Authorization: Bearer `<accessToken>`

## 공용 요청 스키마

```json
{ "session_id": "string" }
```

세션이 없으면 404를 반환한다.

### 에러 응답 (404)

```json
{
  "isSuccess": false,
  "code": "ANALYSIS_SESSION_NOT_FOUND",
  "message": "분석 세션을 찾을 수 없습니다.",
  "result": null
}
```

## 선행 조건 — category_1/category_2/target

`competitors`/`bm_mapping` 조회 키는 `category_1`(질병/분야 축 8종: 수면·정신건강·운동·
식단·만성질환·여성건강·유전자·미용) + `category_2`(기능축 4종: 정보제공·데이터기록관리·
매칭연결·개입치료) + `target` + `service_type` 4개다. `service_type`은 기존
`analysis_sessions`에 있었지만 `category_1`/`category_2`/`target`은 이번 작업(#7)에서
신규 추가한 컬럼이다(마이그레이션 `a1b2c3d4e5f6`).

> category_1은 원래 7종(수면·정신건강·운동·식단·만성질환·여성건강·미용)으로
> 알려져 있었으나, 실제 배포된 분류 모델은 **유전자**를 포함한 8종을 쓴다(채린
> 님 확인, 2026-08-22). DB 컬럼은 `String(80)` 자유 텍스트라 값 종류가 늘어도
> 스키마 변경은 필요 없다.

STEP 1 카테고리 분류 모델(klue/roberta-base 멀티태스크, `category_1`/`category_2`
동시 산출, Avg Macro F1 0.6775 — 축1 0.7033/축2 0.6518, 2026-08-23 기준 계속
학습 중)이 두 값을 함께 산출한다. `POST /api/v1/category-classifier/predict`(이번
작업에서 신규 통합, 아래 참고)로 추론하고, 그 결과를 `PATCH /api/v1/
analysis-sessions/{session_id}/category`로 세션에 반영해야 이 문서의 두 API가
정상 동작한다. `target`은 STEP 0 프론트 입력폼에서 받는 값을 `CreateAnalysisSessionRequest.target`
또는 같은 PATCH로 채운다.

`category_1`/`category_2` 중 하나라도 없으면 두 API 모두 `match_level:
"insufficient_data"`로 응답한다 — 조회 키가 없는 상태에서 임의로 Opportunity/추천을
만들지 않는다.

## 4단계 완화 조회 전략 (공유)

`판정엔진_개발설계서.md` §8.2/§9.1, `db_구축_설계서.md` §6.4. `app/domain/
market_lookup.py`에 두 API가 공유하는 구현이 있다.

```
1) exact_match          : category_1 + category_2 + target + service_type 전부 일치
2) relaxed_service_type : service_type 조건 해제
3) relaxed_category_only: category_1 + category_2 만 일치
4) insufficient_data    : 위 3단계 모두 n=0 (또는 category_1/category_2 자체가 없음)
```

응답에 `match_level`을 항상 포함해 근거 신뢰도를 드러낸다.

---

## `POST /api/v1/feasibility/market`

### Description

경쟁 포화도(개수 기반)로 시장 현실성 등급을 산출하고, 경쟁 카드 3개 + BM 지불 의향
선례를 함께 반환한다. `판정엔진_개발설계서.md` §8.

### Request

공용 요청 스키마 참고. `extra="forbid"` — 명세에 없는 필드를 보내면 422.

### Response

```json
{
  "match_level": "exact_match|relaxed_service_type|relaxed_category_only|insufficient_data",
  "competitor_count": 3,
  "saturation": "Opportunity|Challenging|Saturated|null",
  "market_realism_grade": "높음|중간|낮음|null",
  "platform_competitor_exists": true,
  "payment_precedent": "적음|보통|많음|null",
  "competitor_cards": [
    {
      "name": "string",
      "feature": "string|null",
      "limitation": "string|null",
      "badge": "진입 가능|차별화 필요"
    }
  ]
}
```

- 포화도 매핑(§8.1/§8.4): `competitor_count` 0~2 → Opportunity/높음, 3~4 →
  Challenging/중간, 5+ → Saturated/낮음. `platform_competitor_exists`는 매칭된
  경쟁사 중 `tier='플랫폼'`이 있는지를 별도로 표시한다 — §8.1의 "n≥5 AND tier=플랫폼
  존재 → Saturated 확정" 조건을 그대로 5+ 케이스에 적용하되, 신호등 등급 자체는
  개수만으로도 이미 Saturated로 확정하고 이 필드는 "개수로만 낮음"과 "대형 플랫폼까지
  확인된 낮음"을 리포트에서 구분하는 용도로 쓴다.
- `competitor_cards`: `LIMIT 3`. `feature`는 `competitors.core_tags`, `limitation`은
  `competitors.limitation`을 그대로 노출한다.
- `payment_precedent`: `bm_mapping.precedent_level`(§9.3의 "지불 의향" 판단근거).
  경쟁사 매칭과 별개로 자체 완화 조회를 수행하므로 `match_level`과 다른 단계에서
  나온 값일 수 있다.
- `match_level == "insufficient_data"`일 때 `saturation`/`market_realism_grade`는
  `null`, `competitor_cards`는 빈 배열.

### ⚠️ 이번 API 범위 밖 — 국내 수요 (§8.3 판단근거 ①)

`판정엔진_개발설계서.md` §13 SECTION 2-3 판단근거 4줄 중 "① 국내 수요"는 이 API에
없다.

| 데이터 소스 | 상태 |
|---|---|
| `app_store_ranking` | 팀이 공식 보류 결정(Notion "웰니스 창업 아이디어 검진 시스템" §8) — Google Play 공식 순위 API 부재, 유료 API(AppTweak 등) 계약 이슈 |
| 검색 트렌드 임계값(`trend_signal_config`) | 산출은 완료됐으나(`trend_slope_threshold=-0.15%/일`) 성장군이 정체군보다 더 하락하는 이상치가 있어 팀 재검토 대기 중(같은 문서 §7.7) |

둘 다 준비되면 이 API 응답에 `domestic_demand` 필드로 추가할 예정. 리포트에서
④ 광고표현위험 판단근거처럼 UI에 "데이터 준비 중" 표시가 필요하면 참고.

### `badge` 필드의 한계

배지 기준(§8.5)은 원래 "대형 서비스가 동일 기능 제공 시 차별화 필요"라는 LLM/사람
판단에 가깝다. 지금은 `tier == '플랫폼'`이면 `차별화 필요`, 아니면 `진입 가능`으로
근사한다 — 1번 담당 문서의 `advertising_score`와 같은 종류의 한계다.

---

## `POST /api/v1/business-model/recommend`

### Description

`bm_mapping`에서 BM 추천 2개를 완화 조회한다. `판정엔진_개발설계서.md` §9. **등급
판정 없음** — "지표 판정 없음, 추천만 제공"(§9.2) 원칙을 그대로 따른다.

### Request

공용 요청 스키마 참고.

### Response

```json
{
  "match_level": "exact_match|relaxed_service_type|relaxed_category_only|insufficient_data",
  "recommendations": [
    {
      "bm_pattern": "Freemium|Subscription|Add-on|Lock-in|Two-sided Market|Pay Per Use|Sensor As A Service|Leverage Customer Data|Digitization|Self-service|Performance-based Contracting|Razor And Blade",
      "frequency_score": 2,
      "frequency_score_global": 2,
      "precedent_level": "적음|보통|많음|null",
      "contributing_competitor_ids": "string|null"
    }
  ]
}
```

- `LIMIT 2`, `ORDER BY frequency_score DESC`.
- `match_level == "insufficient_data"`이면 `recommendations: []`, 카드 4줄 요약 문장
  없이 "검증 필요"로만 표시(§9.2) — 수치·근거를 임의 생성하지 않는다.
- 카드 4줄 요약(가격대·전환율·강점)은 이 API 범위 밖이다: 가격대는
  `competitors.price`(☆ 신설 완료, 이 API 응답엔 미포함 — 필요 시 market API의
  경쟁 카드와 조합), 전환율은 수집 가능성 자체가 미확인(§9.3), 강점은 LLM ③ 생성
  영역(§12).

---

## `POST /api/v1/category-classifier/predict` (부속 API)

### Description

STEP 1 카테고리 분류 모델(klue/roberta-base 멀티태스크, `data/models/
best_healthcare_model_2line`)로 `service_description` 텍스트에서 `category_1`·
`category_2`를 동시에 추론한다. 세션을 건드리지 않는 순수 추론 API다 — 결과
반영은 호출한 쪽이 `PATCH /api/v1/analysis-sessions/{session_id}/category`로
별도 수행한다(분류 호출 시점과 세션 반영 시점을 분리해 프론트/파이프라인이
자유롭게 오케스트레이션할 수 있게 한 것, 2026-08-22 확인).

모델 정확도는 Avg Macro F1 0.6775(축1 category_1 0.7033 / 축2 category_2
0.6518, 2026-08-23 기준) — 계속 학습 중이라 값이 바뀔 수 있다.

### Request

```json
{ "service_description": "string" }
```

### Response

```json
{
  "category_1": "수면|정신건강|운동|식단|만성질환|여성건강|유전자|미용",
  "category_1_confidence": 0.91,
  "category_2": "정보제공|데이터기록관리|매칭연결|개입치료",
  "category_2_confidence": 0.74
}
```

모델을 찾을 수 없으면(로컬에 `data/models/`를 배치하지 않은 환경) 503
`CATEGORY_MODEL_UNAVAILABLE`을 반환한다 — 체크포인트가 git에 없는 바이너리라
(`.gitignore`) 환경마다 별도 배치해야 하기 때문이다.

### ⚠️ 두 가지 함정 — 겉보기엔 정상 동작하는 것처럼 보여서 위험하다

1. **AutoTokenizer 쓰지 말 것**. 이 체크포인트의 `tokenizer_config.json`은
   `tokenizer_class: RobertaTokenizer`로 잘못 기록돼 있지만 실제 vocab은 BERT
   WordPiece 형식이다. `AutoTokenizer`로 로드하면 한글 입력이 전부 깨진 토큰으로
   분해되어 **모든 입력이 같은 라벨로 수렴한다**(단일축 구버전 체크포인트로 실측:
   항상 LABEL_3, confidence ~0.3). `BertTokenizerFast`를 명시 로드해야 한다.
2. **`outputs.pooler_output` 쓰지 말 것**. 이 체크포인트는 커스텀 멀티태스크
   구조(`encoder` + `category_head` + `function_head`, raw state_dict로 저장돼
   HuggingFace 표준 `save_pretrained` 형식이 아니다)라 `pooler_output`을 헤드에
   넣으면 확신도가 거의 균등분포(8종 기준 confidence ~0.13)로 나온다. 학습은
   `outputs.last_hidden_state[:, 0]`(CLS 토큰 원본)을 헤드에 직접 넣는 방식으로
   됐다(채린 님 확인, 2026-08-23) — 이렇게 해야 확신도가 실제로 분별력 있게
   나온다(예: 0.7~0.9대).

`app/domain/category_classifier.py`가 이 두 가지를 모두 피해서 구현돼 있다.
이 모델을 다른 곳에서도 로드할 계획이면 반드시 같은 방식을 써야 한다.

---

## 진행 상황 (이 API를 붙일 때 참고)

- `analysis_sessions`에 `category_1`/`category_2`/`target` 컬럼 신규 추가(마이그레이션
  `a1b2c3d4e5f6`) — 이 작업(#7) 전에는 스키마 자체가 없었다(미결정 항목 E-2).
  `POST /api/v1/analysis-sessions`(생성 시) 또는
  `PATCH /api/v1/analysis-sessions/{session_id}/category`(생성 후 반영)로 채운다.
- `competitors`(101건)·`bm_mapping`(59건) 시드 데이터로 실제 매칭 동작 확인 완료
  (2026-08-22, `scripts/import_postgres_seed_data.py`).
- `competitors.limitation`/`competitors.price` 컬럼은 이미 존재·시딩되어 있다
  (Google Sheet 경쟁사DB_BM매핑_수집시트 기준) — §15.10에서 "보강 필요"로 남아있던
  항목이 이미 반영된 상태였다.
- 카테고리 분류 모델을 단일축(category_1만, klue/roberta-large)에서 2축 동시
  분류(category_1+category_2, klue/roberta-base 멀티태스크)로 교체(2026-08-23).
  `category_2`도 이제 이 API로 채울 수 있다 — 계속 학습 중이라 정확도(Avg Macro
  F1 0.6775)는 앞으로 개선될 예정.

## 미완료 — 리포트 저장/조립 API (`/reports/preview`, `POST /reports`)

이번 작업(#7) 범위에서 **제외**했다. 미결정 항목 #1(리포트 저장 정책)이 아직
팀 결정 사항이다 — PREP §10.4 "사용자 입력·분석결과 미저장" 원칙과 "리포트 재조회
필요" 요구가 충돌한 채로 남아있고(`미결정_항목_정리.md` E-4, `판정엔진_개발설계서.md`
§17-1), 이 문서 작성 시점까지 해소된 근거를 찾지 못했다. 저장 스키마를 먼저 정하지
않고 구현하면 나중에 통째로 다시 만들어야 할 위험이 커서, 이번 라운드는 market/BM
API까지만 완성하고 reports는 팀 결정 이후로 미룬다.
