"""Stage B 프롬프트 주입 + LLM 호출. gate_matrix 스키마 구조화 출력.

**"LLM은 data_type/function_type만 판단한다" 원칙의 명시적 예외**: 2026-07-26 복원된
`acquire_method`·침습적 신호도 LLM이 추출한다(db_구축_설계서.md §3.2). 다만 이것은 LLM이 새 조합을
판단하는 것이 아니다 — 6칸 표는 여전히 닫힌 확정 표이고, 이 두 값은 표 조회 **이전**에 적용되는
침습적 하드체크의 입력일 뿐이다. 표의 축은 늘어나지 않는다.
"""

import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.pipeline.article_ref import (
    ARTICLE_NOTATION_PROMPT,
    build_chunk_message,
    normalize_article,
)
from app.pipeline.gate_matrix_table import (
    GATE_MATRIX_TABLE,
    HARDCHECK_VERDICT,
    VERDICT_PRIORITY,
    detect_invasive,
    is_invasive_hardcheck,
    needs_invasive_review,
)
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
                        "acquire_method": {
                            "type": "string",
                            "enum": ["수동입력", "기기연동", "OS연동", "NONE"],
                        },
                        "invasive_signal": {"type": "boolean"},
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
                    "required": [
                        "data_type",
                        "function_type",
                        "boundary_case",
                        "acquire_method",
                        "invasive_signal",
                        "legal_basis",
                    ],
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

## acquire_method / invasive_signal (6칸 표와 무관한 별도 신호)
이 두 값은 **위 6칸 표 조회에 쓰이지 않습니다.** 표 조회 이전에 별도로 적용되는 "침습적 하드체크"
전용 신호이므로, 새로운 조합을 만들어내는 축이 아닙니다. 표는 그대로 6칸입니다.

- acquire_method: 그 조문이 다루는 데이터를 **어떻게 얻는지**를 표시하세요.
  - 수동입력: 사용자가 직접 입력·기록
  - OS연동: 스마트폰 OS의 건강 데이터(걸음수 등) 연동
  - 기기연동: 별도 측정기기·센서와 연결해 값을 받아옴
  - NONE: 조문에 획득 방법이 드러나지 않음
- invasive_signal: **판단 기준은 오직 하나 — "각질층을 관통하는가"입니다.**
  근거는 웰니스판단기준(0091-03) III.2.가·나 고위해도 5요소 중 2번(침습적)의 문언
  "피부를 뚫어 혈액을 채취하거나 체내에 삽입"입니다.
  - true(관통함): 센서를 피하에 삽입해 측정, 바늘·란셋으로 혈액 채취, 체내 삽입·이식,
    마이크로니들처럼 각질층을 뚫는 구조
  - false(관통 안 함): 피부 위에서 측정하는 방식 — 광학식 심박, 체중계, 체성분 측정,
    피부에 붙이기만 하는 심전도 패치 등
  - ⚠️ **기기의 형태 이름으로 판단하지 마세요.** 특히 "패치"는 그 단어만으로 결정되지 않습니다.
    단순 부착형 패치는 비침습이고, 마이크로니들 패치는 각질층을 관통하므로 침습입니다.
    똑같이 "패치"라 불려도 관통 여부가 다르면 판정이 달라집니다.
  - 조문만으로 관통 여부를 확정할 수 없으면 **invasive_signal=false로 두고 boundary_case=true**로
    표시하세요. 추측으로 true를 넣지 마세요 — 이 값이 true면 다른 판단과 무관하게 FAIL이 됩니다.

## legal_basis
- article: 이 조합 판단의 근거가 되는 조문 번호/제목
- quote: 판단 근거가 되는 원문 문장을 그대로 인용 (반드시 아래 조문 텍스트 안에 실제로 존재하는 문장이어야 함. 지어내지 말 것)

""" + ARTICLE_NOTATION_PROMPT


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
            # 룰베이스 구축은 재현 가능해야 한다. 같은 조문을 다시 돌렸을 때 다른 룰이 나오면
            # 검수·회귀 판단의 근거가 사라지므로 온도를 0으로 고정한다.
            # 참고: temperature=0으로도 원본 출력은 완전히 재현되지 않는다(모델이 비트 단위로
            # 결정적이지 않음). seed 고정도 시도했으나 효과가 없어 되돌렸다 — 재현성은
            # 검증·중복판정 단계가 흡수한다.
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": build_chunk_message(chunk)},
            ],
            response_format={"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
        )
        parsed = json.loads(response.choices[0].message.content)

        for item in parsed["matrix_entries"]:
            data_type = item["data_type"]
            function_type = item["function_type"]
            acquire_method = None if item["acquire_method"] == "NONE" else item["acquire_method"]
            invasive_signal = item["invasive_signal"]
            keyword_hit = detect_invasive(chunk["content"])

            hardcheck_fired = is_invasive_hardcheck(data_type, acquire_method, invasive_signal)
            review_fired = needs_invasive_review(
                data_type, acquire_method, invasive_signal, keyword_hit
            )
            # §3.2: acquire_method는 "침습적 하드체크 오버라이드 전용 필드"이고 해당 없는 일반
            # 조합은 비워둔다. 무조건 저장하면 생체지표×단순기록 같은 평범한 칸이 획득방법만
            # 다른 중복 행으로 쌓인다. 실제로 판정을 바꾼 경우에만 남긴다.
            stored_acquire_method = acquire_method if (hardcheck_fired or review_fired) else None

            # 침습적 하드체크는 6칸 표 조회보다 **먼저** 적용된다 — 걸리면 function_type과
            # 표 조회 결과에 관계없이 FAIL로 오버라이드한다 (db_구축_설계서.md §3.2).
            if hardcheck_fired:
                verdict = HARDCHECK_VERDICT
                exemption_note = None
            elif review_fired:
                # 코드는 침습 신호를 잡았는데 LLM은 아니라고 한 불일치. detect_invasive는 청크
                # 전체를 훑어 정밀도가 낮으므로 FAIL로 확정하지 않고 검수 대기로 뺀다.
                # TODO(human_review): interrupt 연결되면 CONDITIONAL 대신 관리자 검수로 보낼 것.
                verdict = "CONDITIONAL"
                exemption_note = None
            elif item["boundary_case"]:
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
                "article": normalize_article(item["legal_basis"]["article"]),
                "quote": item["legal_basis"]["quote"],
            }
            fields = {
                "data_type": data_type,
                "function_type": function_type,
                "verdict": verdict,
                "exemption_note": exemption_note,
                "acquire_method": stored_acquire_method,
                # gate_matrix에 저장되는 컬럼은 아니지만, auto_validate가 하드체크 오버라이드를
                # 그대로 재현해 검증할 수 있도록 draft에 실어 보낸다.
                "invasive_signal": invasive_signal,
                "invasive_keyword_hit": keyword_hit,
                # TODO(D-2): avoidance_* 문구 작성 주체 미정(코드 고정 템플릿 vs LLM 생성).
                # 결정 전까지 채우지 않는다 — verdict=FAIL이어도 None이다.
                "avoidance_redesign": None,
                "avoidance_certification": None,
                "risk_code": None,  # TODO: GATE01_ENG01~02 연계 코드 미확정 (db_구축_설계서.md §3.2)
                "priority": VERDICT_PRIORITY[verdict],
                "legal_basis": legal_basis,
            }
            drafts.append({"stage": "B", "fields": fields, "legal_basis": legal_basis})

    return {"drafts": drafts}
