"""Stage B 확정 매핑표. LLM은 data_type/function_type만 판단, verdict는 여기서 조회."""

import re

DATA_TYPE_ENUM = {"라이프스타일", "생체지표"}
FUNCTION_TYPE_ENUM = {"단순기록", "비교·추이분석", "수치예측·진단"}
MATRIX_VERDICT_ENUM = {"PASS", "CONDITIONAL", "FAIL"}

# 침습적 하드체크 전용 축(db_구축_설계서.md §3.2). 매트릭스 키가 아니므로 6칸 표는 확장되지 않는다.
ACQUIRE_METHOD_ENUM = {"수동입력", "기기연동", "OS연동"}

# 복수 조합 시 우선순위(FAIL > CONDITIONAL > PASS, db_구축_설계서.md §3.2)
VERDICT_PRIORITY = {"FAIL": 3, "CONDITIONAL": 2, "PASS": 1}

GATE_MATRIX_TABLE: dict[tuple[str, str], dict] = {
    ("생체지표", "단순기록"): {"verdict": "PASS", "exemption_note": None},
    ("생체지표", "비교·추이분석"): {"verdict": "CONDITIONAL", "exemption_note": None},
    ("생체지표", "수치예측·진단"): {"verdict": "FAIL", "exemption_note": None},
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

# "비침습적"에는 "침습"이 부분 문자열로 들어 있어 그대로 두면 정반대 판정이 난다.
# 매칭 전에 부정 표현을 통째로 걷어낸다.
_NON_INVASIVE = re.compile(r"[비무]침습")
_WHITESPACE = re.compile(r"\s+")


def detect_invasive(text: str) -> bool:
    """조문 텍스트에서 침습 신호를 코드 측에서 교차 확인한다 (각질층 관통 기준).

    청크 단위로만 볼 수 있어 정밀도가 낮다 — 그래서 이 결과 단독으로는 FAIL을 만들지 않고,
    LLM 판단과 어긋날 때 CONDITIONAL(검수 대기)로 빼는 데에만 쓴다. `needs_invasive_review` 참조.
    """
    compact = _WHITESPACE.sub("", text)
    compact = _NON_INVASIVE.sub("", compact)  # 부정 표현 제거가 먼저다
    return any(keyword in compact for keyword in INVASIVE_KEYWORDS)


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
