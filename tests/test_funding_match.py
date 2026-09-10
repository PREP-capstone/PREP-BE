from datetime import date

from app.domain.funding_match import (
    FundingProgram,
    extract_funding_profile,
    funding_profile_from_session,
    is_money_support_program,
    score_funding_program,
    sort_funding_matches,
)


def test_extract_funding_profile_handles_spaced_korean_pdf_text() -> None:
    text = """
    PREP 리포트
    슬 립
    사용자의 수면 패턴을 분석하고 맞춤형 수면 루틴을 추천하는 모바일 앱입니다.
    # 수 면 # 데 이 터 기 록 관 리 # 수 면 관 심 층, 30대, 직장인 # 모 바 일 앱
    """

    profile = extract_funding_profile(text, region="충남", startup_stage="예비창업", keywords="AI, 모바일")

    assert profile.category_1 == "수면"
    assert profile.category_2 == "데이터 기록관리"
    assert profile.service_type == "모바일 앱"
    assert profile.region == "충남"
    assert profile.startup_stage == "예비창업"
    assert "수면 관심층" in profile.targets
    assert "AI" in profile.keywords


def test_funding_profile_from_session_uses_structured_values_without_pdf() -> None:
    profile = funding_profile_from_session(
        service_name="혈당 관리 앱",
        service_description="혈당 변화를 기록하고 추이를 보여주는 모바일 건강관리 서비스",
        target_users=["만성질환자"],
        service_type="모바일 앱",
        category_1="만성질환",
        category_2="비교추이분석",
        target="직장인",
        health_data_names=["공복혈당"],
        region="전국",
        startup_stage="예비창업",
    )

    assert profile.category_1 == "만성질환"
    assert profile.category_2 == "비교추이분석"
    assert profile.service_type == "모바일 앱"
    assert profile.targets == ["만성질환자", "직장인"]
    assert profile.region == "전국"
    assert profile.startup_stage == "예비창업"
    assert "혈당" in profile.keywords
    assert "공복혈당" in profile.keywords


def test_extract_funding_profile_ignores_later_legal_examples() -> None:
    text = """
    슬 립
    수면 패턴을 분석해서 맞춤형 수면 루틴을 추천하는 모바일 앱을 만들고 싶어요.
    # 수면 # 데 이 터 기 록 관 리 # 수면 관심층 # 모바일 앱
    규 제 위 험 도
    의료기기와 개인용 건강관리 제품 판단 사례
    당뇨병 환자의 혈당을 스마트폰으로 측정하는 사례
    """

    profile = extract_funding_profile(text)

    assert profile.category_1 == "수면"
    assert "수면" in profile.keywords
    assert "혈당" not in profile.keywords
    assert "당뇨" not in profile.keywords


def test_extract_funding_profile_uses_idea_and_hashtag_not_generated_summary() -> None:
    text = """
    슬 립
    수면 패턴을 분석해서 맞춤형 수면 루틴을 추천하는 모바일 앱입니다.
    현재 서비스는 개선 여지가 있습니다.
    GATE PASS · 비의료기기
    서비스 '슬립'은 의학적 정의에 따른 규제 위험도가 낮습니다.
    # 수면 # 데이터 기록관리 # 수면 관심층 # 모바일 앱
    규제 위험도
    """

    profile = extract_funding_profile(text)

    assert profile.category_2 == "데이터 기록관리"
    assert "의료" not in profile.keywords
    assert "수면 관심층" in profile.targets


def test_score_funding_program_uses_keywords_region_stage_and_deadline() -> None:
    profile = extract_funding_profile(
        "수면 데이터를 기록 분석하는 모바일 앱 # 수면 # 데이터 기록관리 # 모바일 앱",
        region="충남",
        startup_stage="예비창업",
        keywords="AI",
    )
    program = FundingProgram(
        program_id="fund-test-1",
        title="충남 AI 헬스케어 예비창업 지원사업",
        region="충남",
        stage="예비창업",
        deadline=date(2026, 9, 10),
        max_amount=50000000,
        description="수면, 모바일 앱, 데이터 기록관리 서비스 개발비를 지원합니다.",
        keywords=["AI", "헬스케어", "수면"],
    )

    match = score_funding_program(program, profile, date(2026, 9, 7))

    assert match.match_score >= 80
    assert match.days_left == 3
    assert any("서비스 분야" in reason for reason in match.matched_reasons)
    assert any("지역 조건" in reason for reason in match.matched_reasons)


def test_sort_funding_matches_uses_score_deadline_then_amount() -> None:
    today = date(2026, 9, 7)
    profile = extract_funding_profile("AI 헬스케어 앱", keywords="AI")
    first = FundingProgram(
        program_id="first",
        title="마감 가까운 사업",
        deadline=date(2026, 9, 8),
        max_amount=10000000,
        description="AI 지원",
        keywords=["AI"],
    )
    second = FundingProgram(
        program_id="second",
        title="금액 큰 사업",
        deadline=date(2026, 9, 20),
        max_amount=90000000,
        description="AI 지원",
        keywords=["AI"],
    )
    third = FundingProgram(
        program_id="third",
        title="점수 높은 사업",
        deadline=date(2026, 9, 30),
        max_amount=1000000,
        description="AI 헬스케어 앱 서비스",
        keywords=["AI", "헬스케어", "앱"],
    )

    matches = [
        score_funding_program(first, profile, today),
        score_funding_program(second, profile, today),
        score_funding_program(third, profile, today),
    ]
    sorted_ids = [match.program.program_id for match in sort_funding_matches(matches)]

    assert sorted_ids[0] == "third"
    assert sorted_ids[1:] == ["first", "second"]


def test_money_support_filter_excludes_non_cash_support_categories() -> None:
    program = FundingProgram(
        program_id="mentoring",
        title="하드웨어 제조 고민 1:1 무료 진단",
        support_amount_text="멘토링ㆍ컨설팅ㆍ교육",
        description="현직 전문가가 무료 멘토링을 제공합니다.",
    )

    assert not is_money_support_program(program)


def test_money_support_filter_excludes_broad_business_mentoring_without_cash_terms() -> None:
    program = FundingProgram(
        program_id="business-mentoring",
        title="AI 서비스 사업화 멘토링 프로그램",
        support_amount_text="멘토링ㆍ컨설팅ㆍ교육",
        description="사업화 전략 수립과 전문가 컨설팅을 지원합니다.",
    )

    assert not is_money_support_program(program)


def test_money_support_filter_includes_business_and_rnd_funding() -> None:
    business_program = FundingProgram(
        program_id="business",
        title="AI 헬스케어 사업화 지원사업",
        support_amount_text="사업화",
        description="서비스 개발비와 사업비를 지원합니다.",
    )
    rnd_program = FundingProgram(
        program_id="rnd",
        title="디지털헬스 기술개발 R&D 지원사업",
        support_amount_text="기술개발(R&D)",
        description="기술개발 자금을 지원합니다.",
    )

    assert is_money_support_program(business_program)
    assert is_money_support_program(rnd_program)


def test_money_support_filter_keeps_cash_program_even_if_category_is_broad() -> None:
    program = FundingProgram(
        program_id="broad",
        title="창업기업 사업화 자금 지원",
        support_amount_text="시설ㆍ공간ㆍ보육",
        description="선정 기업에 사업비 최대 5천만원을 지원합니다.",
    )

    assert is_money_support_program(program)
