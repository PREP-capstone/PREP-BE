from __future__ import annotations


def grade_by_threshold(score: int, threshold_low: int, threshold_mid: int, labels: tuple[str, str, str]) -> str:
    if score <= threshold_low:
        return labels[0]
    if score <= threshold_mid:
        return labels[1]
    return labels[2]
