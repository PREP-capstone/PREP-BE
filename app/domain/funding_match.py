from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any


_CATEGORY_1 = [
    "수면",
    "만성질환",
    "정신건강",
    "다이어트",
    "운동",
    "여성건강",
    "영양",
    "관광",
]

_CATEGORY_2 = [
    "데이터 기록관리",
    "비교추이분석",
    "위험알림",
    "수치예측진단",
    "정보제공",
]

_SERVICE_TYPES = ["모바일 앱", "웹 서비스", "웨어러블 기기", "AI 서비스", "플랫폼"]

_TARGETS = [
    "10대",
    "20대",
    "30대",
    "40대",
    "50대",
    "60대 이상",
    "직장인",
    "프리랜서",
    "자영업자",
    "수험생",
    "대학생",
    "1인 가구",
    "주부",
    "육아",
    "임산부",
    "갱년기",
    "만성질환자",
    "재활",
    "회복기 환자",
    "다이어트",
    "체중관리",
    "영양 불균형",
    "식습관 개선",
    "운동 관심층",
    "수면 관심층",
    "정신건강",
    "에너지관리",
    "여성건강",
]

_REGIONS = [
    "전국",
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "경기",
    "강원",
    "충북",
    "충청북도",
    "충남",
    "충청남도",
    "전북",
    "전라북도",
    "전남",
    "전라남도",
    "경북",
    "경상북도",
    "경남",
    "경상남도",
    "제주",
]

_STAGES = ["예비창업", "초기창업", "창업도약", "재창업", "창업기업", "스타트업"]

_KEYWORDS = [
    "AI",
    "인공지능",
    "모바일",
    "앱",
    "웹",
    "플랫폼",
    "헬스케어",
    "웰니스",
    "건강관리",
    "디지털헬스",
    "의료",
    "수면",
    "혈당",
    "당뇨",
    "식단",
    "영양",
    "운동",
    "스트레스",
    "정신건강",
    "여성건강",
    "관광",
    "콘텐츠",
    "지역",
    "AR",
    "데이터",
    "기록",
    "분석",
    "알림",
    "예측",
    "진단",
]

_FUNDING_INCLUDE_TERMS = [
    "사업화",
    "기술개발",
    "R&D",
    "정책자금",
    "융자",
    "보조금",
    "지원금",
    "사업비",
    "개발비",
    "창업자금",
    "자금",
    "투자연계",
]

_FUNDING_STRICT_INCLUDE_TERMS = [
    "정책자금",
    "융자",
    "보조금",
    "지원금",
    "사업비",
    "개발비",
    "창업자금",
    "자금지원",
    "투자연계",
]

_FUNDING_EXCLUDE_CATEGORIES = [
    "멘토링ㆍ컨설팅ㆍ교육",
    "행사ㆍ네트워크",
    "시설ㆍ공간ㆍ보육",
    "창업교육",
]

_FUNDING_AMOUNT_PATTERN = re.compile(r"\d+\s*(억|천만|백만|만원|원)")


@dataclass(frozen=True)
class FundingProfile:
    service_name: str | None
    category_1: str | None
    category_2: str | None
    targets: list[str]
    service_type: str | None
    region: str | None
    startup_stage: str | None
    keywords: list[str]


@dataclass(frozen=True)
class FundingProgram:
    program_id: str
    title: str
    region: str | None = None
    stage: str | None = None
    eligibility: dict[str, Any] | None = None
    open_date: date | None = None
    deadline: date | None = None
    max_amount: int | None = None
    support_amount_text: str | None = None
    source: str | None = None
    source_url: str | None = None
    description: str | None = None
    keywords: list[str] | None = None


@dataclass(frozen=True)
class FundingMatch:
    program: FundingProgram
    match_score: int
    matched_reasons: list[str]
    days_left: int | None


def compact_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def split_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    tokens = re.split(r"[,#;/\n]+", value)
    return _unique([token.strip() for token in tokens if token.strip()])


def extract_funding_profile(
    report_text: str,
    *,
    region: str | None = None,
    startup_stage: str | None = None,
    keywords: str | None = None,
) -> FundingProfile:
    """PREP 리포트 PDF 텍스트에서 지원사업 매칭에 필요한 최소 프로필을 추출한다.

    PDF 텍스트 추출 시 한글 글자 사이가 벌어지는 경우가 있어 원문과 공백 제거본을
    함께 사용한다. 별도 AI 모델 없이 카탈로그 값/키워드 기반으로만 매칭한다.
    """

    profile_text = _profile_scope_text(report_text)
    compact = compact_text(profile_text)
    service_name = _extract_service_name(report_text)
    category_1 = _find_first(_CATEGORY_1, compact)
    category_2 = _find_first(_CATEGORY_2, compact)
    service_type = _find_first(_SERVICE_TYPES, compact)
    targets = _find_all(_TARGETS, compact)

    inferred_region = _find_first(_REGIONS, compact)
    inferred_stage = _find_first(_STAGES, compact)
    merged_keywords = _unique(
        split_keywords(keywords)
        + _find_all(_KEYWORDS, compact)
        + ([category_1] if category_1 else [])
        + ([category_2] if category_2 else [])
        + ([service_type] if service_type else [])
    )

    return FundingProfile(
        service_name=service_name,
        category_1=category_1,
        category_2=category_2,
        targets=targets,
        service_type=service_type,
        region=region.strip() if region and region.strip() else inferred_region,
        startup_stage=startup_stage.strip() if startup_stage and startup_stage.strip() else inferred_stage,
        keywords=merged_keywords,
    )


def funding_profile_from_session(
    *,
    service_name: str,
    service_description: str,
    target_users: list[str],
    service_type: str | None,
    category_1: str | None,
    category_2: str | None,
    target: str | None,
    health_data_names: list[str],
    region: str | None = None,
    startup_stage: str | None = None,
    keywords: list[str] | None = None,
) -> FundingProfile:
    """저장된 아이디어 검진 세션을 지원사업 매칭 프로필로 변환한다."""
    inferred = extract_funding_profile(
        f"{service_name}\n{service_description}\n{' '.join(health_data_names)}",
        region=region,
        startup_stage=startup_stage,
        keywords=", ".join(keywords or []),
    )
    return FundingProfile(
        service_name=service_name,
        category_1=category_1 or inferred.category_1,
        category_2=category_2 or inferred.category_2,
        targets=_unique(target_users + ([target] if target else []) or inferred.targets),
        service_type=service_type or inferred.service_type,
        region=region or inferred.region,
        startup_stage=startup_stage or inferred.startup_stage,
        keywords=_unique(inferred.keywords + health_data_names),
    )


def score_funding_program(program: FundingProgram, profile: FundingProfile, today: date) -> FundingMatch:
    score = 0
    reasons: list[str] = []
    searchable = _program_searchable_text(program)
    searchable_compact = compact_text(searchable)

    if profile.category_1 and _contains(searchable_compact, profile.category_1):
        score += 24
        reasons.append(f"서비스 분야({profile.category_1})와 공고 키워드가 일치합니다.")
    if profile.category_2 and _contains(searchable_compact, profile.category_2):
        score += 14
        reasons.append(f"서비스 기능({profile.category_2})과 공고 내용이 맞습니다.")
    if profile.service_type and _contains(searchable_compact, profile.service_type):
        score += 10
        reasons.append(f"서비스 형태({profile.service_type})를 지원 대상으로 볼 수 있습니다.")

    matched_targets = [target for target in profile.targets if _contains(searchable_compact, target)]
    if matched_targets:
        score += min(12, 4 * len(matched_targets))
        reasons.append(f"타깃({', '.join(matched_targets[:3])}) 조건과 겹칩니다.")

    if profile.region and program.region:
        region_score = _region_score(program.region, profile.region)
        if region_score:
            score += region_score
            reasons.append(f"지역 조건({program.region})이 입력 지역과 맞습니다.")

    if profile.startup_stage and program.stage:
        stage_score = _stage_score(program.stage, profile.startup_stage)
        if stage_score:
            score += stage_score
            reasons.append(f"사업 단계({program.stage})가 입력 단계와 맞습니다.")

    matched_keywords = _matched_keywords(searchable_compact, profile.keywords)
    if matched_keywords:
        score += min(24, 4 * len(matched_keywords))
        reasons.append(f"핵심 키워드({', '.join(matched_keywords[:5])})가 공고와 겹칩니다.")

    days_left = (program.deadline - today).days if program.deadline else None
    if days_left is not None and days_left >= 0:
        if days_left <= 7:
            score += 4
            reasons.append("마감이 7일 이내라 빠른 검토가 필요합니다.")
        elif days_left <= 30:
            score += 2

    if not reasons:
        reasons.append("직접 일치 근거가 부족해 낮은 우선순위 후보로 분류했습니다.")

    return FundingMatch(program=program, match_score=min(score, 100), matched_reasons=reasons, days_left=days_left)


def sort_funding_matches(matches: list[FundingMatch]) -> list[FundingMatch]:
    return sorted(
        matches,
        key=lambda item: (
            -item.match_score,
            item.days_left if item.days_left is not None else 99999,
            -(item.program.max_amount or 0),
            item.program.title,
        ),
    )


def is_money_support_program(program: FundingProgram) -> bool:
    """지원금 추천 화면에 노출할 자금성 지원사업인지 판정한다."""

    support_text = program.support_amount_text or ""
    support_compact = compact_text(support_text)
    searchable_text = _program_searchable_text(program)
    searchable_compact = compact_text(searchable_text)

    if any(compact_text(term) in support_compact for term in _FUNDING_EXCLUDE_CATEGORIES):
        return (
            any(compact_text(term) in searchable_compact for term in _FUNDING_STRICT_INCLUDE_TERMS)
            or bool(_FUNDING_AMOUNT_PATTERN.search(searchable_text))
            or program.max_amount is not None
        )
    return any(compact_text(term) in searchable_compact for term in _FUNDING_INCLUDE_TERMS)


def profile_to_dict(profile: FundingProfile) -> dict[str, Any]:
    return {
        "service_name": profile.service_name,
        "category_1": profile.category_1,
        "category_2": profile.category_2,
        "targets": profile.targets,
        "service_type": profile.service_type,
        "region": profile.region,
        "startup_stage": profile.startup_stage,
        "keywords": profile.keywords,
    }


def _profile_scope_text(text: str) -> str:
    markers = [
        compact_text("규제 위험도"),
        compact_text("서비스 분류"),
        compact_text("데이터 확보"),
        compact_text("시장 현실성"),
    ]
    scoped_lines: list[str] = []
    collect_intro = True
    for line in text.splitlines():
        line_compact = compact_text(line)
        if line_compact and len(line_compact) <= 20 and any(line_compact.startswith(marker) for marker in markers):
            break
        if line_compact.startswith("#"):
            scoped_lines.append(line)
            continue
        if line_compact.startswith(("현재서비스는", "gatepass", "gatefail", "종합신호등")):
            collect_intro = False
        if collect_intro:
            scoped_lines.append(line)
    return "\n".join(scoped_lines) or text


def _extract_service_name(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    skip_tokens = ["PREP", "Startup Preparation", "Evaluation", "리포트", "목차"]
    for line in lines[:20]:
        clean = re.sub(r"\s+", "", line)
        if clean in {"다.", "니다."} or clean.endswith("보관됩니다."):
            continue
        if 1 < len(clean) <= 30 and not any(token.lower() in clean.lower() for token in skip_tokens):
            if re.search(r"[가-힣A-Za-z]", clean):
                return clean
    return None


def _find_first(candidates: list[str], compact: str) -> str | None:
    return next((candidate for candidate in candidates if _contains(compact, candidate)), None)


def _find_all(candidates: list[str], compact: str) -> list[str]:
    return [candidate for candidate in candidates if _contains(compact, candidate)]


def _contains(compact: str, keyword: str) -> bool:
    return compact_text(keyword) in compact


def _unique(values: list[str | None]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not value:
            continue
        normalized = value.strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _program_searchable_text(program: FundingProgram) -> str:
    values: list[str] = [
        program.title,
        program.region or "",
        program.stage or "",
        program.description or "",
        program.support_amount_text or "",
        " ".join(program.keywords or []),
    ]
    if program.eligibility:
        values.append(" ".join(str(v) for v in program.eligibility.values()))
    return " ".join(values)


def _region_score(program_region: str, requested_region: str) -> int:
    program_compact = compact_text(program_region)
    requested_compact = compact_text(requested_region)
    if "전국" in program_compact:
        return 10
    if requested_compact and requested_compact in program_compact:
        return 18
    if program_compact and program_compact in requested_compact:
        return 18
    return 0


def _stage_score(program_stage: str, requested_stage: str) -> int:
    program_compact = compact_text(program_stage)
    requested_compact = compact_text(requested_stage)
    if requested_compact in program_compact or program_compact in requested_compact:
        return 16
    if "창업기업" in program_compact or "스타트업" in program_compact:
        return 8
    return 0


def _matched_keywords(searchable_compact: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if len(compact_text(keyword)) >= 2 and _contains(searchable_compact, keyword)]
