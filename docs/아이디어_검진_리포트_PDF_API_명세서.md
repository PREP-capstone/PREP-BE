# 아이디어 검진 리포트 PDF API 명세서

## 개요

아이디어 검진 완료 직후의 결과를 서버에서 PDF로 생성해 내려받는다. 화면의
`window.print()`를 사용하지 않으므로 모바일 브라우저에서도 같은 PDF 파일을 받을 수 있다.

검진 결과 JSON은 Redis에 **10분(`REPORT_RESULT_TTL_SECONDS=600`)만 임시 보관**한다.
PDF 생성 요청은 이 임시 결과를 사용하며, LLM 판정을 다시 실행하거나 PDF 파일을 서버에
영구 저장하지 않는다.

## 요청

```http
GET /api/v1/analysis-sessions/{session_id}/report.pdf
```

| 경로 변수 | 필수 | 설명 |
| --- | --- | --- |
| `session_id` | 예 | 아이디어 검진 분석 세션 ID |

PDF를 받기 전 같은 `session_id`로 `POST /api/v1/analysis/evaluate`를 성공 호출해야 한다.

## 성공 응답

| 항목 | 값 |
| --- | --- |
| 상태 코드 | `200 OK` |
| Content-Type | `application/pdf` |
| Content-Disposition | `attachment; filename=...` |
| Cache-Control | `no-store` |

파일명 형식은 `PREP_아이디어검진_{서비스명}_{YYYY-MM-DD}.pdf`다.

PDF에는 서비스 개요, GATE 판정 및 근거 조문, 규제 위험도, 데이터 확보 가능성,
시장 현실성, 수익 구조, 다음 액션을 포함한다. GATE가 `FAIL`이면 데이터 확보 가능성,
시장 현실성, 수익 구조는 `분석 제외` 안내로 대체한다.

## 오류 응답

오류는 공통 API 응답 형식으로 반환한다.

```json
{
  "isSuccess": false,
  "code": "ANALYSIS_RESULT_REQUIRED",
  "message": "검진 결과가 없거나 보관 시간이 만료되었습니다. 다시 검진한 후 PDF를 다운로드해주세요.",
  "result": null
}
```

| 상태 | code | 발생 조건 |
| --- | --- | --- |
| `404` | `ANALYSIS_SESSION_NOT_FOUND` | 존재하지 않는 세션 |
| `409` | `HEALTH_DATA_REQUIRED` | 건강 데이터가 등록되지 않은 세션 |
| `409` | `ANALYSIS_RESULT_REQUIRED` | 검진을 아직 실행하지 않았거나 10분 캐시가 만료됨 |
| `500` | `REPORT_PDF_GENERATION_FAILED` | PDF 렌더링 실패 |

## FE 연동

`POST /api/v1/analysis/evaluate`가 성공한 뒤 10분 안에 호출한다. 브라우저에서
`fetch` 응답을 `Blob`으로 받아 다운로드하면 된다. `Content-Disposition` 헤더는 CORS에서
노출되어 있으므로 필요하면 파일명을 읽을 수 있다.

`ANALYSIS_RESULT_REQUIRED`를 받으면 "검진 결과 보관 시간이 만료되었습니다. 다시 검진해주세요."
안내 후 검진 화면으로 이동시킨다.
