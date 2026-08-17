## Description

사용자 질의에 대해 ChromaDB에 적재된 RAG 근거 chunk를 semantic search로 조회한다.

## Headers

Authorization: Bearer `<accessToken>`

## Request

Method: `POST`

URL: `/api/v1/rag/search`

```json
{
  "query": "허위 과대 광고",
  "top_k": 5,
  "tag_regulatory": true,
  "tag_privacy": false,
  "tag_advertising": true,
  "document_ids": [
    "kr-medical-device-act-rule-annex7-20260701"
  ]
}
```

## Response

```json
[
  {
    "chunk_id": "kr-medical-device-act-rule-annex7-20260701-annex7-09",
    "document_id": "kr-medical-device-act-rule-annex7-20260701",
    "title": "의료기기법 시행규칙 별표7 금지되는 광고의 범위",
    "doc_type": "LAW",
    "section_id": "별표7.제9호",
    "section_title": "금지되는 광고의 범위",
    "chunk_text": "효능ㆍ효과를 광고할 때에...",
    "source_url": "https://www.law.go.kr",
    "page_start": 1,
    "page_end": 1,
    "similarity": 0.4093
  }
]
```