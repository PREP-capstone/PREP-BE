# 데이터 확보 가능성 API

이슈 #110: 확보 난이도와 개인정보 민감도를 독립 지표로 제공한다.

## 요청

`POST /api/v1/feasibility/data`

`Content-Type: application/json`. MVP에서는 Authorization이 필요하지 않다.
세션 및 health-data를 먼저 등록해야 한다.

```json
{"session_id": "발급받은 세션 ID"}
```

## 성공 응답 (200)

걸음수와 복용약물을 수동입력하는 예시다. 복용약물은 민감도 3인 카탈로그 item_code로 등록한 상태다.

```json
{
  "isSuccess": true,
  "code": "DATA_FEASIBILITY_COMPLETED",
  "message": "데이터 확보 가능성 판단이 완료되었습니다.",
  "result": {
    "data_feasibility_score": 1,
    "risk_level": "LOW",
    "privacy_score": 3,
    "privacy_level": "HIGH",
    "privacy_grade": "높음",
    "available_sources": [],
    "privacy_risks": [
      {
        "data_name": "복용약물",
        "sensitivity_level": 3,
        "reason": "카탈로그 기반 개인정보 처리 검토 안내 (예시)"
      }
    ],
    "standard_scale_candidates": [],
    "mvp_roadmap": []
  }
}
```

## 지표 해석

| 필드 | 기준 | FE 표시 |
| --- | --- | --- |
| data_feasibility_score | 항목별 D×S의 최댓값, 현재 최대 30 | 확보 난이도 점수 |
| risk_level | 3 이하 LOW / 10 이하 MEDIUM / 초과 HIGH | 확보 난이도 쉬움 / 보통 / 어려움 |
| privacy_score | 등록 item_code의 sensitivity_level 최댓값, 0~3 | 개인정보 민감도 점수 |
| privacy_level | 0~1 LOW / 2 MEDIUM / 3 HIGH | 개인정보 민감도 등급 |
| privacy_grade | 낮음 / 중간 / 높음 | 개인정보 민감도 한글 표시 |
| privacy_risks[].sensitivity_level | 카탈로그 민감도, 미매칭 시 null | 항목별 검토 근거 |

두 점수를 합산하지 않는다. `risk_level=LOW`는 개인정보 위험까지 낮다는 뜻이 아니다.
화면에는 “확보 난이도: 쉬움 / 개인정보 민감도: 높음”을 함께 표시한다.
기존에 확보 가능성으로 표시한다면 LOW → 가능성 높음, HIGH → 가능성 낮음으로 대응한다.

민감도는 판정 API와 동일하게 item_code로 조회한다. 미매칭 항목은 점수에 포함되지 않는다.
`is_sensitive=true`인 미매칭 항목은 경고를 유지하고 sensitivity_level=null을 반환한다.
따라서 privacy_score=0은 개인정보 안전 확인을 의미하지 않는다. FE는 privacy_risks 경고도 표시해야 한다.

`/api/v1/analysis/evaluate`의 data_feasibility 결과에도 같은 추가 필드가 포함된다.
기존 필드는 유지되며 DB 컬럼 변경이나 마이그레이션은 필요하지 않다.

## 오류

| HTTP 상태 | code | 의미 |
| --- | --- | --- |
| 404 | ANALYSIS_SESSION_NOT_FOUND | 세션 없음 |
| 409 | HEALTH_DATA_REQUIRED | 검진 데이터 미등록 |
| 422 | 요청 검증 오류 | session_id 누락 등 |
| 500 | FEASIBILITY_REFERENCE_DATA_MISSING | 난이도 시드 누락 |

```json
{
  "isSuccess": false,
  "code": "HEALTH_DATA_REQUIRED",
  "message": "등록된 검진 데이터가 없습니다. 먼저 health-data를 등록해주세요.",
  "result": null
}
```
