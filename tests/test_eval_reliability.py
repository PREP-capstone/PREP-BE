"""scripts/eval_reliability.py 단위 테스트 — 보고서에 그대로 인용될 숫자라 지표 계산을 고정한다.

DB·OpenAI 없이 돈다. run_case는 세션 생성·evaluate 호출·키워드 재매칭을 모킹해 "같은 입력
N회 → 층별 재현성·불변식·타당성" 집계 로직만 확인한다.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import eval_reliability as er

TEMPLATE = Path(__file__).resolve().parents[1] / "data" / "eval" / "golden_set_template.csv"
GOLDEN = TEMPLATE.parent / "golden_set_lmj.csv"


def test_cohen_kappa_matches_hand_computation() -> None:
    # p_o = 4/5, p_e = (2·2 + 3·2 + 0·1)/25 = 0.4 → κ = (0.8 − 0.4)/(1 − 0.4)
    kappa = er.cohen_kappa(["PASS", "FAIL", "FAIL", "PASS", "FAIL"], ["PASS", "FAIL", "FAIL", "PASS", "CONDITIONAL"])
    assert kappa == pytest.approx(2 / 3)


def test_cohen_kappa_is_undefined_when_every_label_is_the_same() -> None:
    assert er.cohen_kappa(["PASS", "PASS"], ["PASS", "PASS"]) is None


def test_fleiss_kappa_matches_hand_computation() -> None:
    ratings = [
        ["PASS", "PASS", "PASS"],
        ["FAIL", "FAIL", "FAIL"],
        ["FAIL", "FAIL", "FAIL"],
        ["PASS", "PASS", "PASS"],
        ["FAIL", "CONDITIONAL", "FAIL"],
    ]
    # P̄ = (4 + 1/3)/5, P̄e = 0.4² + (8/15)² + (1/15)²
    p_bar, p_e = (4 + 1 / 3) / 5, 0.4**2 + (8 / 15) ** 2 + (1 / 15) ** 2
    assert er.fleiss_kappa(ratings) == pytest.approx((p_bar - p_e) / (1 - p_e))


def test_kappa_report_reads_template_rater_columns() -> None:
    report = er.kappa_report(er.read_rows(TEMPLATE))
    assert report["rater_columns"] == ["rater_1_gate", "rater_2_gate", "rater_3_gate"]
    assert report["pairwise_cohen"]["rater_1_gate vs rater_2_gate"] == {"n": 5, "kappa": 0.667}
    assert report["fleiss"]["n"] == 5


def test_gate_validity_counts_fail_to_pass_as_critical() -> None:
    result = er.gate_validity([("FAIL", "PASS"), ("FAIL", "FAIL"), ("PASS", "PASS"), ("CONDITIONAL", "FAIL")])
    assert result["accuracy"] == 0.5
    assert result["fail_recall"] == 0.5
    assert result["fail_precision"] == 0.5
    assert result["critical_errors"] == 1


def test_consistency_reports_modal_value_and_share() -> None:
    result = er.consistency(["FAIL", "FAIL", "PASS"])
    assert result == {"consistent": False, "distinct": 2, "modal_share": 0.667, "modal": "FAIL"}


def test_text_invariant_helpers() -> None:
    assert er.signal_color_mismatch("전반적으로 초록 신호입니다.", "빨강") == ["초록"]
    assert er.signal_color_mismatch("빨간 신호등이 켜졌습니다.", "빨강") == []
    assert er.ungrounded_numbers("전환율 30%가 예상됩니다.", '{"privacy_score": 3}') == ["30"]
    assert er.phrase_detected("불면증 여부를 진단", ["진단"])
    assert not er.phrase_detected("불면증 여부를 진단", ["혈당 검사"])


def test_template_rows_parse_into_cases() -> None:
    cases = er.load_cases(TEMPLATE)
    assert [case.case_id for case in cases] == ["EX01", "EX02", "EX03", "EX04", "EX05", "EX06"]
    first = cases[0]
    assert [(item.name, item.source, item.item_code) for item in first.health_data_items] == [
        ("걸음수", "os_sync", "lifestyle_001"),
        ("수면 시간", "os_sync", "lifestyle_002"),
    ]
    assert first.service_actions == ["record", "visualize_trend"]
    assert [case.case_id for case in er.load_cases(TEMPLATE, split="dev")] == ["EX02"]


def test_golden_set_is_loadable_with_unique_ids_and_known_splits() -> None:
    # 팀이 엑셀로 직접 고치는 파일이라, 형식 오류(잘못된 판정값·수집방법, 빈 데이터 항목, 중복 번호)를
    # 측정을 돌리기 전에 CI에서 먼저 잡는다. split=example은 템플릿 전용이다.
    cases = er.load_cases(GOLDEN)
    case_ids = [case.case_id for case in cases]
    assert len(case_ids) == len(set(case_ids))
    assert {case.split for case in cases} <= {"dev", "test"}


def _fake_result(summary: str) -> dict:
    return {
        "gate": {
            "verdict": "FAIL",
            "data_type": "생체지표",
            "function_type": "수치예측·진단",
            "hardcheck_fired": False,
            "legal_basis": {"document_id": "kr-mfds-wellness-0091-03-20260212", "article": "IV.3"},
        },
        "regulatory_risk": {
            "regulatory_score": 3,
            "privacy_score": 3,
            "advertising_score": 0,
            "final_regulatory_grade": "높음",
            "matched_rules": [{"legal_basis": {"document_id": "kr-medical-act-20260407", "article": "제27조"}}],
        },
        "correction_candidates": {
            "candidates": [{"risky_text": "위험 수치일 때 경고", "safe_text": "측정값을 기록해 드려요", "match_source": "rule"}]
        },
        "data_feasibility": None,
        "market_feasibility": None,
        "business_model": None,
        "next_actions": [{"action_text": "의료기기 해당 여부를 식약처에 문의하세요"}],
        "overall_actions": [],
        "section_links": [],
        "bm_card_summaries": [],
        "differentiation_point": None,
        "overall_summary": summary,
        "one_liner": "규제 위험이 커서 빨간 신호입니다.",
        "overall_signal": "빨강",
    }


async def test_run_case_separates_stable_verdicts_from_varying_llm_text(monkeypatch) -> None:
    summaries = iter(["규제 위험이 높습니다.", "초록 신호에 가깝고 전환율 30%가 기대됩니다."])

    async def fake_create_session(case, categories):
        return "session-test"

    async def fake_delete_session(session_id):
        return None

    async def fake_evaluate(request):
        result = _fake_result(next(summaries))
        return SimpleNamespace(result=SimpleNamespace(model_dump=lambda mode: result))

    async def fake_match_keywords(text, rule_version_ids):
        return []

    monkeypatch.setattr(er, "_create_session", fake_create_session)
    monkeypatch.setattr(er, "_delete_session", fake_delete_session)
    monkeypatch.setattr(er, "evaluate_analysis", fake_evaluate)
    monkeypatch.setattr(er, "_match_gate_keywords", fake_match_keywords)

    case = er.load_cases(TEMPLATE, split="dev")[0]  # EX02 — 정답 FAIL
    record = await er.run_case(case, runs=2, use_classifier=False, keep_session=False, rule_version_ids=[])

    assert record["runs_ok"] == 2
    assert all(field["consistent"] for field in record["layers"]["A"].values())
    assert all(field["consistent"] for field in record["layers"]["B"].values())
    assert record["layers"]["D"]["overall_summary"]["exact_match_share"] == 0.5
    assert record["layers"]["D"]["one_liner"]["exact_match_share"] == 1.0
    assert record["invariants"]["signal_color_mismatch"] == [{"field": "overall_summary", "run": 1, "colors": ["초록"]}]
    assert {"field": "overall_summary", "run": 1, "numbers": ["30"]} in record["invariants"]["ungrounded_numbers"]
    assert record["validity"]["gate"] == ["FAIL", "FAIL"]
    assert record["corrections"] == {"total": 1, "unsafe": []}

    summary = er.summarize_run([record])
    assert summary["reproducibility"]["A"]["all_fields_consistent_share"] == 1.0
    assert summary["validity"]["gate"]["accuracy"] == 1.0
    assert summary["invariants"]["signal_color_mismatch_runs"] == 1


def _competitor(competitor_id, bm_pattern, country="한국", **keys):
    defaults = {"category_1": "수면", "category_2": "데이터기록관리", "target": "개인", "service_type": "앱단독"}
    return SimpleNamespace(competitor_id=competitor_id, bm_pattern=bm_pattern, country=country, **{**defaults, **keys})


def test_recommend_bm_relaxes_keys_and_ranks_by_domestic_count() -> None:
    pool = [
        _competitor("c1", "Subscription(구독형)", target="수면개선희망자"),
        _competitor("c2", "Freemium(프리미엄)", target="수면개선희망자"),
        _competitor("c3", "Freemium(프리미엄)", country="미국", target="수면개선희망자"),
        _competitor("c4", "Add-on(애드온)", category_1="운동"),
    ]
    held_out = _competitor("x", "Subscription(구독형)")  # target "개인"은 pool에 없음 → 카테고리만 맞춤
    match_level, recommended = er.recommend_bm(pool, held_out)
    assert match_level == "relaxed_category_only"
    # 국내 수는 Subscription 1·Freemium 1 동점 → 전체 수(Freemium 2)가 앞선다
    assert recommended == ["Freemium", "Subscription"]
