from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import httpx

from app.core.config import settings
from app.domain.funding_match import FundingProfile, FundingProgram, classify_support_types


_TITLE_KEYS = [
    "biz_pbanc_nm",
    "pbanc_nm",
    "announcement_title",
    "announcementTitle",
    "title",
    "ttl",
    "공고명",
    "제목",
]
_URL_KEYS = ["detl_pg_url", "detailurl", "detail_url", "url", "source_url", "pbanc_url", "상세URL"]
_DEADLINE_KEYS = [
    "biz_rcept_end_dt",
    "rcept_end_dt",
    "pbanc_rcpt_end_dt",
    "reception_end_date",
    "endDate",
    "deadline",
    "접수종료일",
    "마감일",
]
_OPEN_DATE_KEYS = [
    "biz_rcept_bgng_dt",
    "rcept_bgng_dt",
    "pbanc_rcpt_bgng_dt",
    "startDate",
    "open_date",
    "접수시작일",
]
_REGION_KEYS = ["supt_regin", "region", "area", "지역"]
_STAGE_KEYS = ["aply_trgt_ctnt", "aply_trgt", "biz_enyy", "target", "stage", "지원대상", "대상"]
_DESCRIPTION_KEYS = [
    "biz_pbanc_ctnt",
    "pbanc_ctnt",
    "description",
    "summary",
    "content",
    "사업내용",
    "공고내용",
]
_AMOUNT_KEYS = ["support_amount", "max_amount", "지원금액", "지원내용"]
_SUPPORT_CATEGORY_KEYS = ["supt_biz_clsfc", "지원사업분류", "지원분야"]
_KEYWORD_KEYS = ["biz_category", "category", "field", "keywords", "분야", "키워드"]
_BIZINFO_REGION_NAMES = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)


async def fetch_external_funding_programs(profile: FundingProfile) -> tuple[list[FundingProgram], list[str]]:
    """외부 공고 소스에서 지원사업을 가져온다.

    저장 DB를 두지 않는 MVP 구조라, 요청 시점에 공식 API와 보조 크롤링 소스를 조회한다.
    한 소스가 실패해도 다른 소스 결과는 살린다.
    """

    programs: list[FundingProgram] = []
    warnings: list[str] = []

    kstartup_rows, kstartup_warning = await fetch_kstartup_programs(profile)
    programs.extend(kstartup_rows)
    if kstartup_warning:
        warnings.append(kstartup_warning)

    bizinfo_rows, bizinfo_warning = await fetch_bizinfo_programs(profile)
    programs.extend(bizinfo_rows)
    if bizinfo_warning:
        warnings.append(bizinfo_warning)

    startup_plus_rows, startup_plus_warning = await fetch_startup_plus_programs(profile)
    programs.extend(startup_plus_rows)
    if startup_plus_warning:
        warnings.append(startup_plus_warning)

    return _dedupe_programs(programs), warnings


async def fetch_kstartup_programs(profile: FundingProfile) -> tuple[list[FundingProgram], str | None]:
    del profile  # 최신 공고를 넓게 가져온 뒤 내부 매칭 점수로 정렬한다.
    if not settings.public_data_service_key:
        return [], "PUBLIC_DATA_SERVICE_KEY가 없어 K-Startup OpenAPI 조회를 건너뛰었습니다."

    params = _kstartup_request_params()
    # 공공데이터포털 조건 검색 파라미터는 서비스별로 동작 방식이 달라 0건을
    # 반환하는 경우가 있다. 최신 공고를 넓게 가져오고 내부 점수화로 거르는 편이
    # 추천 누락 위험이 작다.

    try:
        async with httpx.AsyncClient(timeout=settings.funding_request_timeout_seconds) as client:
            response = await client.get(settings.kstartup_api_url, params=params)
            response.raise_for_status()
    except httpx.HTTPError as error:
        return [], f"K-Startup OpenAPI 조회에 실패했습니다: {error.__class__.__name__}"

    programs: list[FundingProgram] = []
    for row in _extract_rows_from_response(response):
        program = _normalize_program(row, source="K-Startup")
        if program:
            programs.append(program)
    return programs, None


async def fetch_startup_plus_programs(profile: FundingProfile) -> tuple[list[FundingProgram], str | None]:
    del profile  # 현재 Startup Plus 보조 수집은 공개 목록 HTML에서 best-effort로만 추출한다.
    try:
        async with httpx.AsyncClient(timeout=settings.funding_request_timeout_seconds, follow_redirects=True) as client:
            response = await client.get(settings.startup_plus_project_url)
            response.raise_for_status()
    except httpx.HTTPError as error:
        return [], f"Startup Plus 페이지 조회에 실패했습니다: {error.__class__.__name__}"

    return _parse_startup_plus_html(response.text), None


async def fetch_bizinfo_programs(profile: FundingProfile) -> tuple[list[FundingProgram], str | None]:
    """기업마당 공식 지원사업정보 API에서 공고를 가져온다."""

    del profile  # 최신 공고를 넓게 가져온 뒤 내부 매칭 점수로 정렬한다.
    if not settings.bizinfo_api_key:
        return [], "BIZINFO_API_KEY가 없어 기업마당 API 조회를 건너뛰었습니다."

    params = {
        "crtfcKey": settings.bizinfo_api_key,
        "dataType": "json",
        "searchCnt": max(1, settings.funding_fetch_limit),
        "pageUnit": max(1, settings.funding_fetch_limit),
        "pageIndex": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.funding_request_timeout_seconds) as client:
            response = await client.get(settings.bizinfo_api_url, params=params)
            response.raise_for_status()
    except httpx.HTTPError as error:
        return [], f"기업마당 API 조회에 실패했습니다: {error.__class__.__name__}"

    programs: list[FundingProgram] = []
    for row in _extract_rows_from_response(response):
        program = _normalize_bizinfo_program(row)
        if program:
            programs.append(program)
    return programs, None


def _extract_rows_from_response(response: httpx.Response) -> list[dict[str, Any]]:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            return []
        return _find_items(payload)
    return _find_items(_xml_to_dict(response.text))


def _find_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for row in value for item in _find_items(row)]
    if not isinstance(value, dict):
        return []
    for key in ("item", "items", "data", "list", "result", "body"):
        child = value.get(key)
        if isinstance(child, list):
            return [row for row in child if isinstance(row, dict)]
        if isinstance(child, dict):
            rows = _find_items(child)
            if rows:
                return rows
    if any(key in value for key in _TITLE_KEYS):
        return [value]
    for child in value.values():
        rows = _find_items(child)
        if rows:
            return rows
    return []


def _xml_to_dict(text: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}

    def convert(element: ET.Element) -> Any:
        children = list(element)
        if not children:
            return element.text or ""
        grouped: dict[str, Any] = {}
        for child in children:
            value = convert(child)
            tag = child.tag.rsplit("}", 1)[-1]
            if tag in grouped:
                if not isinstance(grouped[tag], list):
                    grouped[tag] = [grouped[tag]]
                grouped[tag].append(value)
            else:
                grouped[tag] = value
        return grouped

    return {root.tag.rsplit("}", 1)[-1]: convert(root)}


def _normalize_program(row: dict[str, Any], *, source: str) -> FundingProgram | None:
    title = _pick(row, _TITLE_KEYS)
    if not title:
        return None
    source_url = _pick(row, _URL_KEYS)
    support_amount_text = _pick(row, _AMOUNT_KEYS)
    support_category_text = _pick(row, _SUPPORT_CATEGORY_KEYS)
    support_text = support_amount_text or support_category_text
    description = _pick(row, _DESCRIPTION_KEYS)
    keywords = _split_keywords(_pick(row, _KEYWORD_KEYS))
    if description:
        keywords.extend(_keyword_hits(description))

    return FundingProgram(
        program_id=_pick(row, ["biz_pbanc_sn", "pbanc_sn", "postsn", "id", "program_id"]) or f"{source}:{title}",
        title=title,
        region=_pick(row, _REGION_KEYS),
        stage=_pick(row, _STAGE_KEYS),
        eligibility={key: row[key] for key in _STAGE_KEYS if key in row},
        open_date=_parse_date(_pick(row, _OPEN_DATE_KEYS)),
        deadline=_parse_date(_pick(row, _DEADLINE_KEYS)),
        max_amount=_parse_amount(" ".join(value for value in [support_amount_text, description, title] if value)),
        support_amount_text=support_text,
        source=source,
        source_url=source_url,
        description=description,
        keywords=_unique(keywords),
        support_types=classify_support_types(" ".join(value for value in [support_text, description, title] if value)),
    )


def _normalize_bizinfo_program(row: dict[str, Any]) -> FundingProgram | None:
    title = _pick(row, ["title", "pblancNm", "공고명"])
    if not title:
        return None
    description = _strip_html(_pick(row, ["description", "bsnsSumryCn", "사업개요내용"]))
    hashtags = _pick(row, ["hashTags", "hashtags", "해시태그"])
    support_category = _pick(row, ["lcategory", "pldirSportRealmLclasCodeNm", "지원분야대분류"])
    request_period = _pick(row, ["reqstDt", "reqstBeginEndDe", "신청기간"])
    keywords = _split_keywords(hashtags)
    keywords.extend(_keyword_hits(" ".join(value for value in [title, description, support_category, hashtags] if value)))
    open_date, deadline = _parse_date_range(request_period)
    region = _find_bizinfo_region(hashtags)
    support_text = " / ".join(value for value in [support_category, description] if value)

    return FundingProgram(
        program_id=_pick(row, ["seq", "pblancId", "program_id"]) or f"BizInfo:{title}",
        title=title,
        region=region,
        stage=_pick(row, ["trgetNm", "지원대상"]),
        eligibility={key: row[key] for key in ("author", "excInsttNm", "trgetNm") if key in row},
        open_date=open_date,
        deadline=deadline,
        max_amount=_parse_amount(" ".join(value for value in [description, title] if value)),
        support_amount_text=support_text or None,
        source="기업마당",
        source_url=_pick(row, ["link", "pblancUrl", "공고URL"]),
        description=description,
        keywords=_unique(keywords),
        support_types=classify_support_types(" ".join(value for value in [support_text, description, title] if value)),
    )


def _kstartup_request_params() -> dict[str, Any]:
    limit = max(1, settings.funding_fetch_limit)
    return {
        "serviceKey": settings.public_data_service_key,
        "page": 1,
        "perPage": limit,
        "pageNo": 1,
        "numOfRows": limit,
        "returnType": "json",
        "dataType": "json",
    }


def _parse_startup_plus_html(text: str) -> list[FundingProgram]:
    """Startup Plus HTML에서 눈에 띄는 공고 링크를 best-effort로 추출한다.

    사이트 구조가 바뀌면 빈 배열이 될 수 있다. 공식 OpenAPI가 아니므로 보조 소스로만
    사용한다.
    """

    programs: list[FundingProgram] = []
    for href, title in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, flags=re.I | re.S):
        clean_title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(title))).strip()
        if len(clean_title) < 4 or not any(token in clean_title for token in ("지원", "창업", "모집", "사업")):
            continue
        programs.append(
            FundingProgram(
                program_id=f"startup-plus:{compact_url(href)}",
                title=clean_title,
                source="Startup Plus",
                source_url=urljoin(settings.startup_plus_project_url, href),
                description=clean_title,
                keywords=_keyword_hits(clean_title),
                support_types=classify_support_types(clean_title),
            )
        )
    return programs[: settings.funding_fetch_limit]


def compact_url(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value).strip("-")[:100]


def _pick(row: dict[str, Any], keys: list[str]) -> str | None:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value is None:
            value = lowered.get(key.lower())
        text = html.unescape(str(value or "")).strip()
        if text:
            return text
    return None


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip() or None


def _parse_date_range(value: str | None) -> tuple[date | None, date | None]:
    if not value:
        return None, None
    dates = re.findall(r"\d{4}[.\-/]?\d{2}[.\-/]?\d{2}", value)
    parsed = [_parse_date(item) for item in dates]
    parsed = [item for item in parsed if item is not None]
    if len(parsed) >= 2:
        return parsed[0], parsed[1]
    if parsed:
        return parsed[0], parsed[0]
    return None, None


def _find_bizinfo_region(value: str | None) -> str | None:
    compact = value or ""
    for region in _BIZINFO_REGION_NAMES:
        if region in compact:
            return region
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except ValueError:
            return None
    if "오늘마감" in value:
        return date.today()
    match = re.search(r"(\d+)일\s*남음", value)
    if match:
        return date.today() + timedelta(days=int(match.group(1)))
    return None


def _parse_amount(value: str | None) -> int | None:
    if not value:
        return None
    text = value.replace(",", "")
    match = re.search(r"(\d+)\s*억", text)
    if match:
        return int(match.group(1)) * 100_000_000
    match = re.search(r"(\d+)\s*천만", text)
    if match:
        return int(match.group(1)) * 10_000_000
    match = re.search(r"(\d+)\s*백만", text)
    if match:
        return int(match.group(1)) * 1_000_000
    match = re.search(r"(\d{6,})", text)
    return int(match.group(1)) if match else None


def _split_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [token.strip() for token in re.split(r"[,#/;\s]+", value) if len(token.strip()) >= 2]


def _keyword_hits(value: str) -> list[str]:
    candidates = [
        "AI",
        "인공지능",
        "헬스케어",
        "웰니스",
        "건강",
        "관광",
        "콘텐츠",
        "모바일",
        "앱",
        "데이터",
        "바우처",
        "지역",
    ]
    compact = re.sub(r"\s+", "", value).lower()
    return [candidate for candidate in candidates if re.sub(r"\s+", "", candidate).lower() in compact]


def _dedupe_programs(programs: list[FundingProgram]) -> list[FundingProgram]:
    seen: set[tuple[str | None, str]] = set()
    output: list[FundingProgram] = []
    for program in programs:
        key = (program.source_url, program.title)
        if key in seen:
            continue
        seen.add(key)
        output.append(program)
    return output


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
