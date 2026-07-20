"""Stage B 프롬프트 주입 + LLM 호출. gate_matrix 스키마 구조화 출력.
"""

import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.pipeline.gate_matrix_table import GATE_MATRIX_TABLE, VERDICT_PRIORITY
from app.pipeline.state import ExtractedDraft, PipelineState

_RESPONSE_SCHEMA = {
    "name": "gate_b_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "matrix_entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "data_type": {"type": "string", "enum": ["라이프스타일", "생체지표"]},
                        "function_type": {
                            "type": "string",
                            "enum": ["단순기록", "비교·추이분석", "수치예측·진단"],
                        },
                        "boundary_case": {"type": "boolean"},
                        "legal_basis": {
                            "type": "object",
                            "properties": {
                                "article": {"type": "string"},
                                "quote": {"type": "string"},
                            },
                            "required": ["article", "quote"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["data_type", "function_type", "boundary_case", "legal_basis"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["matrix_entries"],
        "additionalProperties": False,
    },
}

_SYSTEM_PROMPT = """당신은 의료용 앱 판단 가이드 조문에서 gate_matrix(data_type × function_type 조합) 후보를
추출하는 전문가입니다. 주어진 조문 텍스트를 읽고, data_type/function_type 판단에 쓰일 조합 후보를
0개 이상 추출하세요. 관련 내용이 없으면 matrix_entries를 빈 배열로 반환하세요.

## data_type 2분류 (1차 구축 범위)
- 라이프스타일: 진단·치료 피드백 없이 식단·운동·수면 등을 자가관리하도록 돕는 데이터. 경계기준: "환자 맞춤형 진단·치료법 제공" 여부
- 생체지표: 혈당·혈압·심전도·산소포화도 등 측정값(그 자체로 민감정보 취급). 경계기준: 표시·저장만=웰니스 / 분석 후 진단·치료 피드백=의료기기
(민감정보는 생체지표에 포함, 임상·진료는 이번 구축 범위 제외 — 이 두 축만 사용)

## function_type 3분류 + 디시전 트리
- 단순기록: 표시·저장·형식변환만, 분석·피드백 없음
- 비교·추이분석: 추이·통계 비교 (검증된 통계 기반, 개별 진단 아님)
- 수치예측·진단: 데이터 해석해 진단·위험도·치료법 생성

```
Q1. 데이터를 해석해서 진단·위험도·치료법을 만들어내는가?
    예 -> 수치예측·진단
    아니오 -> Q2
Q2. 측정값의 추이·통계를 비교해서 보여주는가? (개별 진단 아님, 검증된 통계 기반)
    예 -> 비교·추이분석
    아니오 -> 단순기록
```

## function_type 예시 문구
- 단순기록: "측정된 데이터를 전송받아 원격으로 서버에 전송", "분석 및 피드백 기능 없이 출력·기록", "여러 기기에서 데이터 받아 일상적 건강관리 목적으로 기록·조회"
- 비교·추이분석: "동 연령·성별군 중 질환 발생비율 등 객관적 통계 결과 제시", "체중·체지방 자가측정 데이터의 변화량을 보여줌"
- 수치예측·진단: "유전자검사 결과 분석 → 암 발병확률 진단", "뇌파 측정 → 우울증·불안증 위험도 수치화", "수면 중 생체신호 기록 → 수면장애 평가",
  "혈당 수치값을 표시하고 위험 수치일 때 경고 알람을 제공"(수치를 보여주는 것에서 그치지 않고 위험 여부까지 판정해 알려주므로 단순기록이 아니라 수치예측·진단)

## function_type 트리 적용 제외 영역
"기기를 제어·통제·측정하는가"의 문제(예: 의료기기 무선 제어, 전극·센서로 자체 측정)는 Stage A(gate_keywords)
영역이고, 사용자 데이터를 다루지 않는 단순 정보열람·통신 기능도 이 프레임 대상이 아닙니다. 그런 조문이면
matrix_entries에 넣지 마세요.

## 경계 케이스 처리 원칙 (3단계, 아래 순서로 시도)
1. 우선순위 규칙: 한 조문/기능에 여러 function_type 신호가 섞여 있으면 더 위해도가 높은 쪽(수치예측·진단 >
   비교·추이분석 > 단순기록)으로 분류하세요.
2. 위 디시전 트리와 예시 문구를 기준으로 최대한 하나의 function_type으로 좁혀서 판단하세요.
3. 그래도 판단이 불가능한 잔여 케이스만 boundary_case=true로 표시하세요(이 경우 data_type/function_type은
   최선의 추정값을 넣어도 됩니다 — 최종 verdict는 시스템이 CONDITIONAL로 강제 처리합니다).

## 6칸 확정 매핑표 (참고자료 — 이 표 안에서만 판단할 것, 새 조합을 만들어내지 말 것)
| data_type | function_type | verdict |
|---|---|---|
| 생체지표 | 단순기록 | PASS |
| 생체지표 | 비교·추이분석 | CONDITIONAL |
| 생체지표 | 수치예측·진단 | FAIL |
| 라이프스타일 | 단순기록 | PASS |
| 라이프스타일 | 비교·추이분석 | PASS |
| 라이프스타일 | 수치예측·진단 | CONDITIONAL |
verdict/exemption_note/priority는 당신이 출력하지 않습니다 — data_type/function_type만 정확히 판단하세요.

## legal_basis
- article: 이 조합 판단의 근거가 되는 조문 번호/제목
- quote: 판단 근거가 되는 원문 문장을 그대로 인용 (반드시 아래 조문 텍스트 안에 실제로 존재하는 문장이어야 함. 지어내지 말 것)
"""


def _build_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def extract_B(state: PipelineState) -> dict:
    client = _build_client()
    drafts: list[ExtractedDraft] = list(state["drafts"])

    for chunk in state["chunks"]:
        if not chunk["content"].strip():
            continue

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": chunk["content"]},
            ],
            response_format={"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
        )
        parsed = json.loads(response.choices[0].message.content)

        for item in parsed["matrix_entries"]:
            data_type = item["data_type"]
            function_type = item["function_type"]

            if item["boundary_case"]:
                # TODO(human_review): 3단계로도 안 풀리는 경계 케이스 — interrupt로 관리자 검수에
                # 넘겨야 하지만 아직 human_review 노드가 없어 CONDITIONAL로만 표시하고 넘어간다.
                verdict = "CONDITIONAL"
                exemption_note = None
            else:
                lookup = GATE_MATRIX_TABLE[(data_type, function_type)]
                verdict = lookup["verdict"]
                exemption_note = lookup["exemption_note"]

            legal_basis = {
                "document_id": state["document_id"],
                "article": item["legal_basis"]["article"],
                "quote": item["legal_basis"]["quote"],
            }
            fields = {
                "data_type": data_type,
                "function_type": function_type,
                "verdict": verdict,
                "exemption_note": exemption_note,
                "risk_code": None,  # TODO: GATE01_ENG01~02 연계 코드 미확정 (db_구축_설계서.md §3.2)
                "priority": VERDICT_PRIORITY[verdict],
                "legal_basis": legal_basis,
            }
            drafts.append({"stage": "B", "fields": fields, "legal_basis": legal_basis})

    return {"drafts": drafts}
