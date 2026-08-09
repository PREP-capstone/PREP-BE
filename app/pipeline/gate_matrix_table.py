"""Stage B 확정 매핑표. LLM은 data_type/function_type만 판단, verdict는 여기서 조회."""

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

# TODO(D-1): 침습적 판정 대상 목록 미확정 — 팀 회의 필요.
# data_type이 라이프스타일/생체지표 2종으로 추상화된 이후라 CGM 등 구체 사례를 다시 정의해야 한다
# (구현_현황_정리.md §Stage B 추가 구현 필요, db_구축_설계서.md §8.2 연계).
# 목록이 확정되면 이 집합만 채우면 되고, 아래 로직은 그대로 동작한다.
# 비어 있는 동안 하드체크는 LLM이 판단한 invasive_signal에만 의존한다.
INVASIVE_KEYWORDS: frozenset[str] = frozenset()


def detect_invasive(text: str) -> bool:
    """조문 텍스트에서 침습적 신호를 코드 측에서 교차 확인한다.

    D-1 확정 전까지 INVASIVE_KEYWORDS가 비어 있어 항상 False를 반환한다 — 즉 지금은
    LLM의 invasive_signal이 유일한 입력이다.
    """
    return any(keyword in text for keyword in INVASIVE_KEYWORDS)


def is_invasive_hardcheck(data_type: str, acquire_method: str | None, invasive_signal: bool) -> bool:
    """FAIL 하드 오버라이드 대상인지 판단한다. function_type은 의도적으로 보지 않는다."""
    return data_type == "생체지표" and acquire_method == "기기연동" and invasive_signal
