from scripts.fix_nonmedical_section_id_ii19 import (
    EXPECTED_RISKY_TEXTS,
    NEW_SECTION_ID,
    OLD_SECTION_ID,
    is_expected_rule,
)


def test_fix_targets_only_known_ii19_rules() -> None:
    assert OLD_SECTION_ID == "II.19"
    assert NEW_SECTION_ID == "II.3"
    assert set(EXPECTED_RISKY_TEXTS) == {"진단 질환", "처방 질환", "치료 질환"}

    assert is_expected_rule({"risky_text": "진단 질환"})
    assert is_expected_rule({"risky_text": "처방 질환"})
    assert is_expected_rule({"risky_text": "치료 질환"})
    assert not is_expected_rule({"risky_text": "다른 표현"})
