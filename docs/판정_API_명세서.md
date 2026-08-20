# 판정 API 명세서

> 담당: 1번(Gate/규제 위험도 판정) · 대상: 3번(시장성/BM/리포트) 공유용
> 작업 #7(이슈 #31) — `RAG_근거검색_API_명세서.md`와 같은 포맷.
> 최신 코드 기준(`app/api/judgement.py`, `app/schemas/common.py`, PR #35 반영 상태).

이 3개 API는 요청 스키마(`GateRequest`)를 공유한다. 아직 `analysis-sessions` API가
없어 요청 스키마는 임시 확정 상태다 — 2번의 `POST /health-data`가 받는
`HealthDataItemInput`(`app/schemas/common.py`)과 통합 예정이라, `HealthDataItem`
필드가 나중에 조금 바뀔 수 있다(§진행 상황 참고).

## Headers

Authorization: Bearer `<accessToken>`

## 공용 요청 스키마 — `GateRequest`

```json
{
  "service_name": "string",
  "service_description": "string",
  "health_data_items": [
    {
      "name": "string",
      "data_type": "numeric|text|image 등 (라이프스타일/생체지표 enum과 다름, 값의 타입)",
      "unit": "string|null",
      "source": "user_input|device_sync|os_sync",
      "is_sensitive": true,
      "item_code": "string|null"
    }
  ],
  "service_actions": ["record", "visualize_trend", "predict", "diagnose", "alert"]
}
```

- `item_code`: `data_sensitivity.item_code`(예: `sensitive_001`). `privacy_score` 계산에만
  쓰인다 — 아직 2번/프론트 쪽 반영 전이라 `null`로 오면 `privacy_score`는 0으로 나온다
  (§진행 상황 참고).

## 공용 응답 스키마 — `LegalBasis`

```json
{ "document_id": "string", "article": "string", "quote": "string|null" }
```

`quote`는 RAG `rag/chunks/lookup` 연동 전까지 항상 `null` — 룰 테이블에는 조문
원문이 없다(이슈 4 "RAG 근거 연결"에서 채워짐).

---

## `POST /api/v1/judgement/gate`

### Description

규칙 기반(LLM 미사용)으로 `data_type`/`function_type`/`acquire_method`를 판별하고,
6칸 매트릭스 + 침습적 하드체크로 `verdict`(PASS/CONDITIONAL/FAIL)를 결정한다.

### Request

`GateRequest` (공용 스키마 참고)

### Response

```json
{
  "data_type": "라이프스타일|생체지표",
  "function_type": "단순기록|비교·추이분석|수치예측·진단",
  "acquire_method": "수동입력|기기연동|OS연동|null",
  "invasive_signal": true,
  "verdict": "PASS|CONDITIONAL|FAIL",
  "hardcheck_fired": true
}
```

---

## `POST /api/v1/judgement/regulatory-risk`

### Description

3축(의료행위표현/개인정보민감도/광고표현위험) 점수·등급을 계산한다. 등급은
**최고값 채택**(합산 아님) — `db_구축_설계서.md` §3.3.2, `판정엔진_개발설계서.md` §6.3.

### Request

`GateRequest` (공용 스키마 참고)

### Response

```json
{
  "regulatory_score": 0,
  "regulatory_grade": "낮음|중간|높음",
  "privacy_score": 0,
  "privacy_grade": "낮음|중간|높음",
  "advertising_score": 0,
  "advertising_grade": "낮음|중간|높음",
  "matched_rules": [
    {
      "legal_basis": { "document_id": "string", "article": "string", "quote": null },
      "exact_phrase_match": true
    }
  ]
}
```

- `matched_rules[].exact_phrase_match`: 근거 조문의 `risky_text`가 `service_description`에
  **문자 그대로 있었는지**(`true`) 아니면 매칭된 키워드로부터 역참조로만 딸려온
  추정 근거인지(`false`) 구분한다. 리포트에서 "이 표현이 실제로 발견됨"으로 보여줄
  근거는 `true`인 것만 쓰는 걸 권장한다.

---

## `POST /api/v1/judgement/correction-candidates`

### Description

위험 표현(risky_text) → 안전 표현(safe_text) 교정 후보 목록. 리포트 SECTION 2-1의
"위험 표현 목록 + Before→After 카드" 원천.

### Request

`GateRequest` (공용 스키마 참고)

### Response

```json
{
  "candidates": [
    {
      "risky_text": "string",
      "safe_text": "string",
      "legal_basis": { "document_id": "string", "article": "string", "quote": null },
      "exact_phrase_match": true
    }
  ]
}
```

- `exact_phrase_match`: `regulatory-risk`와 동일한 의미. `false`인 후보는 "이 문구를
  실제로 쓰셨네요"처럼 단정적으로 보여주면 안 된다 — 관련 키워드로부터 추정된
  후보라는 걸 UI에서 구분해줘야 한다.

---

## 판단근거 4줄 대조표 (`판정엔진_개발설계서.md` §6.4 기준)

리포트 SECTION 2-1의 "판단근거 4줄" 중 내 API로 채울 수 있는 건 2줄뿐이다.
나머지 2줄은 **다른 데이터 소스가 필요하다** — 통합 시점에 빠진 걸 알고 준비해두는 게 목적.

| 줄 | 요구 사항 | 내 API로 채울 수 있나 |
|---|---|---|
| ① 의료행위 표현 사용 여부 | gate_keywords → regulatory_score | ✅ `regulatory_score`/`regulatory_grade` |
| ② 수집 데이터 민감도 평가 | data_sensitivity → privacy_score | ⚠️ `privacy_score`/`privacy_grade` — 단 item_code 연동 전까지는 신뢰도 낮음(아래 참고) |
| ③ 서비스 형태 기반 적용 법령 | `service_law_map` | ❌ **내 API 범위 밖** — 다른 데이터 소스로 채워야 함 |
| ④ 광고/마케팅 표현 위험 | 별표7 → advertising_score | ⚠️ `advertising_score`/`advertising_grade` — 규칙 기반 한계로 신뢰도 낮음(아래 참고) |

"다음 액션 3~4개"(§6.4)도 `action_templates`가 필요해 **내 API 범위 밖**이다.

## 알려진 한계

- **`advertising_score`**: 3축 중 유일하게 LLM 판단 영역으로 설계된 축이라 완전한
  규칙 기반 대안이 없다. 지금은 `correction_rules` 매칭에만 의존 — 별표7 신호어
  목록을 상수로 빼서 보강하는 방안은 검토만 하고 미착수 상태.
- **`privacy_score`**: `item_code` 연동이 끝나기 전까지는 요청에 `item_code`가
  안 오면(2번/프론트 미반영 시) 항상 0으로 나온다. 아래 진행 상황 참고.

## 진행 상황 (이 API를 붙일 때 참고)

- `GateRequest.health_data_items[].item_code`는 방금 추가된 필드다(PR #35, 이슈 #31
  작업 #6). 2번의 `HealthDataItemInput`(`app/schemas/common.py`)에도 같은 필드가
  추가될 예정이고, 끝나면 `judgement.py`도 자체 `HealthDataItem` 대신 그 스키마를
  import하도록 정리할 계획 — 그때 요청 스키마 필드가 한 번 더 정리될 수 있다.
- `analysis-sessions`/`health-data` API(2번 담당, PR #34)가 머지되면, `session_id`
  기반으로 이 3개 API를 호출하는 흐름으로 바뀔 예정이다(이슈 4, 아직 블록 상태).
  지금은 mock(`data/judgement/mock_requests.json`) 기준으로 개발해도 된다.
