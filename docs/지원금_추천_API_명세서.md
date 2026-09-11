# 지원금 추천 API

지원금 추천은 두 가지 진입 경로를 지원한다.

## 1. PDF 업로드 방식

메인 화면에서 아이디어 검진 리포트 PDF를 업로드한다.

```http
POST /api/v1/funding/recommendations
Content-Type: multipart/form-data
```

필드:

- `file`: PDF 파일, 필수
- `region`: 지역, 선택
- `startup_stage`: 사업 단계, 선택
- `keywords`: 추가 키워드 문자열, 선택
- `top_k`: 1~50, 기본값 12

## 2. 아이디어 검진 결과 연동 방식

아이디어 검진 결과 화면에서 현재 분석 세션의 `session_id`를 전달한다. PDF를 다시 업로드하지 않는다.

```http
POST /api/v1/funding/recommendations/from-session
Content-Type: application/json
```

요청:

```json
{
  "session_id": "session_20260812_001",
  "region": "전국",
  "startup_stage": "예비창업",
  "keywords": ["혈당", "건강관리"],
  "top_k": 12
}
```

`session_id`는 필수이며, `region`, `startup_stage`, `keywords`는 FE에서 추가 보정할 때만 보낸다. BE는 세션의 서비스명, 설명, 카테고리, 타깃, 서비스 유형, 건강 데이터 이름을 지원사업 매칭 프로필로 변환한다.

건강 데이터가 없어도 서비스 정보가 저장된 세션이면 추천을 실행한다. 건강 데이터 이름은 키워드 보강에만 사용한다.

## 성공 응답

두 API는 같은 응답 형식을 반환한다.

```json
{
  "isSuccess": true,
  "code": "FUNDING_RECOMMENDATIONS_FOUND",
  "message": "지원사업 추천 결과를 조회했습니다.",
  "result": {
    "total": 12,
    "recommended_at": "2026-09-10T14:30:00+09:00",
    "basis_date": "2026-09-10",
    "sort_order": [
      "match_score_desc",
      "deadline_asc",
      "max_amount_desc"
    ],
    "extracted_profile": {},
    "sources": [],
    "source_warnings": [],
    "recommendations": []
  }
}
```

정렬 순서는 매칭률 높은 순, 마감일 가까운 순, 지원금액 큰 순이다. 추천 기준일은 버튼을 누른 시점의 서버 날짜를 사용한다.

추천 항목에는 `support_types`와 `is_financial_support`가 포함된다. `support_types`는 `금전지원`, `사업화`, `시설·공간`, `보육`, `멘토링·교육`, `행사·네트워크` 중 공고에서 확인된 유형이고, `is_financial_support`는 실제 금전성 지원으로 필터링 가능한지 나타낸다. `support_amount_text`는 원문 지원 내용이므로 숫자 금액이 없을 수 있다.

지원사업 출처:

- K-Startup OpenAPI
- 기업마당 지원사업정보 API
- Startup-Plus 공개 페이지 보조 수집

## 오류 응답

| 상태 | code | 의미 |
| --- | --- | --- |
| 404 | `ANALYSIS_SESSION_NOT_FOUND` | 존재하지 않거나 만료된 세션 |
| 400 | `FUNDING_REPORT_PDF_REQUIRED` | PDF 방식에서 PDF가 아님 |
| 413 | `FUNDING_REPORT_TOO_LARGE` | PDF가 10MB 초과 |
| 422 | `FUNDING_REPORT_TEXT_EMPTY` | PDF 텍스트 추출 실패 |
