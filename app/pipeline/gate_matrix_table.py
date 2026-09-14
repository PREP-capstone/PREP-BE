"""Stage B 확정 매핑표. LLM은 data_type/function_type만 판단, verdict는 여기서 조회."""

import re

from app.pipeline.genetic_test_actions import GENETIC_TEST_KEYWORDS

DATA_TYPE_ENUM = {"라이프스타일", "생체지표"}
FUNCTION_TYPE_ENUM = {"단순기록", "비교·추이분석", "수치예측·진단"}
MATRIX_VERDICT_ENUM = {"PASS", "CONDITIONAL", "FAIL"}

# 침습적 하드체크 전용 축(db_구축_설계서.md §3.2). 매트릭스 키가 아니므로 6칸 표는 확장되지 않는다.
ACQUIRE_METHOD_ENUM = {"수동입력", "기기연동", "OS연동"}

# 복수 조합 시 우선순위(FAIL > CONDITIONAL > PASS, db_구축_설계서.md §3.2)
VERDICT_PRIORITY = {"FAIL": 3, "CONDITIONAL": 2, "PASS": 1}

# D-2 확정(2026-08-25, 코드 템플릿 방식) — verdict=FAIL 셀에만 avoidance_redesign/
# avoidance_certification을 채운다. PASS/CONDITIONAL 셀은 회피가 필요 없으므로 키 자체를
# 안 둔다 — 조회 쪽(judgement.py)이 dict.get()으로 없으면 None 처리.
#
# 매트릭스 FAIL과 하드체크 FAIL 둘 다 인증 경로 안내 뒷문장이 같아서(§3.2 근거 조문도 동일)
# _CERTIFICATION_GUIDANCE로 공유한다 — 조문·절차가 바뀔 때 한 곳만 고치면 되도록.
_CERTIFICATION_GUIDANCE = (
    "정식 의료기기 인증(허가·인증·신고)이 필요합니다. "
    "식품의약품안전처 의료기기 인증 절차(의료기기법 제8조)를 확인하세요."
)

GATE_MATRIX_TABLE: dict[tuple[str, str], dict] = {
    ("생체지표", "단순기록"): {"verdict": "PASS", "exemption_note": None},
    ("생체지표", "비교·추이분석"): {"verdict": "CONDITIONAL", "exemption_note": None},
    ("생체지표", "수치예측·진단"): {
        "verdict": "FAIL",
        "exemption_note": None,
        "avoidance_redesign": (
            "수치 예측·진단(위험 수치 경고, 이상 여부 판단 등) 기능을 제거하고 측정값을 "
            "저장·기록하거나 추이만 보여주는 형태로 축소하면 PASS/CONDITIONAL로 전환될 수 있습니다."
        ),
        "avoidance_certification": f"예측·진단 기능을 그대로 유지하려면 {_CERTIFICATION_GUIDANCE}",
    },
    ("라이프스타일", "단순기록"): {"verdict": "PASS", "exemption_note": None},
    ("라이프스타일", "비교·추이분석"): {"verdict": "PASS", "exemption_note": None},
    ("라이프스타일", "수치예측·진단"): {"verdict": "CONDITIONAL", "exemption_note": None},
}


# ---- 침습적 하드체크 (6칸 표 조회 **이전** 단계) ----
#
# 구 룰베이스 구축방안 pseudocode의 `if acquireMethod=="기기연동" and 침습적: return FAIL`을 복원한 것.
# data_type=생체지표 + acquire_method=기기연동 + 침습적 신호가 함께 잡히면 function_type·표 조회
# 결과와 무관하게 FAIL로 오버라이드한다.
#
# ⚠️ 설계서 §3.2는 이 오버라이드 결과를 "FAIL_CONFIRMED"로 서술하지만, FAIL_CONFIRMED는
# gate_keywords.verdict의 값이고 gate_matrix.verdict는 PASS/CONDITIONAL/FAIL 3종 닫힌 enum이다
# (§3.2, 2026-07-05 확정). 여기서는 매트릭스 enum을 따라 FAIL을 쓴다 — 팀 확인 필요 항목.
HARDCHECK_VERDICT = "FAIL"

# 하드체크 FAIL은 매트릭스를 안 거치므로 avoidance 문구도 별도로 둔다(§3.2, D-2 코드 템플릿).
HARDCHECK_AVOIDANCE_REDESIGN = (
    "채혈·삽입형 센서처럼 각질층을 관통하는 침습적 측정 방식을 비침습 방식으로 바꾸거나, "
    "기기연동을 없애고 사용자가 직접 입력하는 방식으로 전환하면 하드체크 대상에서 제외됩니다."
)
HARDCHECK_AVOIDANCE_CERTIFICATION = f"침습적 측정 기능을 그대로 유지하려면 {_CERTIFICATION_GUIDANCE}"

# D-1 확정 (2026-08-12) — 판단 기준은 **"각질층을 관통하는가"**.
# 근거: 지침서-0091-03 고위해도 2번 "피부 뚫어 혈액 채취, 체내 삽입".
#
# 이 목록은 LLM이 놓친 케이스를 잡는 **재현율 보강용 교차확인 장치**이지 판정 주체가 아니다.
# 목록에 없는 신규 기기를 놓치지 않으려면 판단 기준 자체를 LLM에 서술해야 하므로,
# extract_b 프롬프트에는 이 키워드를 나열하지 않고 "각질층 관통 여부"를 기준으로 서술한다.
#
# ⚠️ "패치"는 의도적으로 넣지 않았다 — 단순 부착형(심전도 패치)은 비침습이고 마이크로니들처럼
# 각질층을 관통할 때만 침습이다. 형태 이름으로 일괄 매칭하면 비침습 패치를 전부 오탐한다.
INVASIVE_KEYWORDS: frozenset[str] = frozenset(
    {
        "침습",  # 문언 그대로 (비침습/무침습은 아래에서 먼저 제거하므로 오탐 없음)
        "CGM",
        "연속혈당",  # 연속혈당측정(기) — 센서를 피하에 삽입
        "채혈",
        "채취",  # 웰니스판단기준 0091-03 고위해도 예시 원문: "피부를 침투하여 혈액을
                 # 채취하는 제품"(2026-08-14 원문 대조로 추가). "채혈"보다 넓어 타액·소변
                 # 채취 등 비침습 케이스까지 걸릴 수 있으나, 이 목록은 FAIL을 직접 만들지
                 # 않고 needs_invasive_review()의 안전장치를 거치므로 과대 매칭의 최악
                 # 결과가 "검수 대기"에 그친다(§8.2 설계 그대로).
        "란셋",
        "마이크로니들",
        "미세침",
        "피하삽입",
        "체내삽입",
        "이식형",
        "삽입형",
        "천자",
    }
)

# "비침습적"에는 "침습"이, "비이식형"·"비삽입형"에는 "이식형"·"삽입형"이 부분 문자열로
# 들어 있어 그대로 두면 명시적으로 "아니다"라고 선언한 문장이 정반대로 판정된다.
# 매칭 전에 부정 표현을 통째로 걷어낸다. 웰니스판단기준 0091-03 원문에 "비침습적 및
# 비이식형 방법으로 측정한 혈압값"이 실제로 등장해(2026-08-14 확인) 이식형/삽입형도
# 침습과 같은 함정이 있음을 발견했다.
_NON_INVASIVE = re.compile(r"[비무](침습|이식|삽입)")
_WHITESPACE = re.compile(r"\s+")


def detect_invasive(text: str) -> bool:
    """조문 텍스트에서 침습 신호를 코드 측에서 교차 확인한다 (각질층 관통 기준).

    청크 단위로만 볼 수 있어 정밀도가 낮다 — 그래서 이 결과 단독으로는 FAIL을 만들지 않고,
    LLM 판단과 어긋날 때 CONDITIONAL(검수 대기)로 빼는 데에만 쓴다. `needs_invasive_review` 참조.
    """
    compact = _WHITESPACE.sub("", text)
    compact = _NON_INVASIVE.sub("", compact)  # 부정 표현 제거가 먼저다
    return any(keyword in compact for keyword in INVASIVE_KEYWORDS)


# ---- DTC 유전자검사 보조 안내 (6칸 표 조회 결과는 그대로 두고, 인증 안내 문구만 교체) ----
#
# 침습적 하드체크와 달리 verdict를 오버라이드하지 않는다 — (생체지표, 수치예측·진단) 셀은
# 이미 FAIL이라 유전자 여부와 무관하게 같은 결론에 도달한다. 다만 "의료기기 인증을 받으면
# 된다"는 기본 안내(_CERTIFICATION_GUIDANCE)는 DTC 유전자검사에는 틀린 법률이다 — 이건
# 의료기기법이 아니라 생명윤리법(DTC 유전자검사기관 신고·허용 항목) 문제다.
#
# 2026-09-14 원문 확보(사용자가 PDF 직접 제공, 법률 제21065호, 2025.10.1. 시행) — 아래
# 조문 인용은 이 원문 기준이다. RAG(app/rag/)에는 아직 미적재라 evidence_chunks 조회로
# quote를 채울 순 없지만(§8.2 참조), 이 문구 자체는 하드코딩 상수라 RAG 적재와 무관하게
# 정확한 조문을 인용할 수 있다.
#
# 핵심 조문 3개:
# - 제49조: 유전자검사기관은 **신고제**(허가·인증 아님)
# - 제49조의2②: "소비자 대상 직접 시행 유전자검사"(DTC, 제50조제3항제2호 유형을 가리키는
#   법률상 정식 용어)를 하려면 신고와 별개로 검사역량 **인증**(유효기간 3년)이 추가로 필요
# - 제50조③: 의료기관이 아닌 유전자검사기관은 질병의 예방·진단·치료와 관련한 유전자검사를
#   **원칙적으로 할 수 없다** — 예외는 ①의료기관 의뢰 ②질병예방 관련 복지부장관 인정 항목뿐.
#   즉 인증(제49조의2)을 받아도 "질병 진단" 목적 검사를 의료기관 경유 없이 직접 제공하는 건
#   별개로 막혀 있다 — "인증받으면 해결"이 아닌 이유가 이 조문이다. 위반 시 제67조⑦(2년
#   이하 징역/3천만원 이하 벌금)로 단순 미신고(제68조⑪, 1년/2천만원)보다 무겁다.
#
# 예방 목적 중 정확히 어떤 항목이 "복지부장관이 인정"한 허용 목록인지는 대통령령(시행령)
# 위임 사항이라 이 법률 원문만으로는 확정 불가 — 그 경계는 여전히 hedge로 남긴다.
#
# 키워드 목록 자체는 app/pipeline/genetic_test_actions.py가 단일 출처다 —
# scripts/seed_genetic_test_keywords.py(gate_keywords 시딩)와 공유한다.

GENETIC_AVOIDANCE_CERTIFICATION = (
    "유전자검사 관련 서비스는 의료기기 인증과 별개로 생명윤리 및 안전에 관한 법률상 "
    "유전자검사기관 신고(제49조)가 필요하고, 검사 결과를 소비자에게 직접 제공(DTC)하려면 "
    "검사역량 인증(제49조의2, 유효기간 3년)까지 받아야 합니다. 다만 의료기관이 아닌 "
    "유전자검사기관은 질병의 예방·진단·치료와 관련한 유전자검사를 원칙적으로 할 수 없습니다"
    "(제50조제3항 — 의료기관의 의뢰를 받았거나 질병예방 관련 검사로 보건복지부장관이 "
    "인정한 경우만 예외). 즉 신고·인증을 받아도 '질병 진단' 목적 검사 결과를 의료기관 경유 "
    "없이 직접 제공하는 것은 별도로 금지될 수 있으므로, 서비스가 예방/웰니스 목적인지 "
    "진단/치료 목적인지부터 확인해야 합니다. 예방 목적 중 구체적으로 허용되는 항목 범위는 "
    "시행령 위임 사항이라 별도 확인이 필요합니다."
)


def detect_genetic_test_signal(text: str) -> bool:
    """서비스 설명·데이터 항목명에서 유전자검사(DTC) 신호를 교차 확인한다.

    detect_invasive와 마찬가지로 재현율 보강용이며 verdict를 바꾸지 않는다 — 매칭되면
    avoidance_certification 문구만 GENETIC_AVOIDANCE_CERTIFICATION으로 교체된다.
    """
    compact = _WHITESPACE.sub("", text)
    return any(keyword in compact for keyword in GENETIC_TEST_KEYWORDS)


def is_invasive_hardcheck(data_type: str, acquire_method: str | None, invasive_signal: bool) -> bool:
    """FAIL 하드 오버라이드 대상인지 판단한다. function_type은 의도적으로 보지 않는다."""
    return data_type == "생체지표" and acquire_method == "기기연동" and invasive_signal


def needs_invasive_review(
    data_type: str, acquire_method: str | None, invasive_signal: bool, keyword_hit: bool
) -> bool:
    """안전장치: 코드는 침습 신호를 찾았는데 LLM은 아니라고 한 불일치 케이스.

    `detect_invasive`가 청크 전체를 훑기 때문에, 조문이 CGM을 지나가듯 언급했을 뿐인데
    무관한 항목까지 FAIL로 끌고 갈 수 있다. 그래서 불일치는 FAIL이 아니라 CONDITIONAL로
    빼서 사람이 보게 한다 — 놓치지도 않고, 근거 없이 FAIL을 주지도 않는다.
    """
    if is_invasive_hardcheck(data_type, acquire_method, invasive_signal):
        return False  # 이미 확정 FAIL
    return data_type == "생체지표" and acquire_method == "기기연동" and keyword_hit
