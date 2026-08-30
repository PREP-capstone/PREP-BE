from __future__ import annotations

_GRADE_ORDER = {"낮음": 0, "중간": 1, "높음": 2}


def grade_by_threshold(score: int, threshold_low: int, threshold_mid: int, labels: tuple[str, str, str]) -> str:
    if score <= threshold_low:
        return labels[0]
    if score <= threshold_mid:
        return labels[1]
    return labels[2]


def max_grade(grades: list[str]) -> str:
    return max(grades, key=lambda g: _GRADE_ORDER[g])
