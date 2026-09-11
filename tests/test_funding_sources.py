from datetime import date

from app.domain.funding_sources import (
    _find_items,
    _kstartup_request_params,
    _normalize_bizinfo_program,
    _normalize_program,
    _parse_date,
    _parse_date_range,
)


def test_find_items_handles_public_data_nested_payload() -> None:
    payload = {
        "response": {
            "body": {
                "items": {
                    "item": [
                        {
                            "biz_pbanc_sn": "123",
                            "biz_pbanc_nm": "AI 창업 지원사업",
                        }
                    ]
                }
            }
        }
    }

    assert _find_items(payload) == [{"biz_pbanc_sn": "123", "biz_pbanc_nm": "AI 창업 지원사업"}]


def test_normalize_program_maps_kstartup_like_fields() -> None:
    program = _normalize_program(
        {
            "biz_pbanc_sn": "123",
            "biz_pbanc_nm": "충남 AI 헬스케어 예비창업 지원사업",
            "detl_pg_url": "https://www.k-startup.go.kr/example",
            "biz_rcept_end_dt": "20260916",
            "supt_regin": "충남",
            "aply_trgt_ctnt": "예비창업자",
            "biz_pbanc_ctnt": "AI 헬스케어 모바일 앱 개발비를 최대 5천만원 지원합니다.",
        },
        source="K-Startup",
    )

    assert program is not None
    assert program.program_id == "123"
    assert program.title == "충남 AI 헬스케어 예비창업 지원사업"
    assert program.deadline == date(2026, 9, 16)
    assert program.region == "충남"
    assert program.max_amount == 50000000
    assert "AI" in program.keywords
    assert "금전지원" in program.support_types


def test_kstartup_request_params_include_public_data_pagination_aliases() -> None:
    params = _kstartup_request_params()

    assert params["page"] == 1
    assert params["pageNo"] == 1
    assert params["perPage"] == params["numOfRows"]


def test_normalize_program_parses_amount_from_description_when_support_class_exists() -> None:
    program = _normalize_program(
        {
            "pbanc_sn": "179130",
            "biz_pbanc_nm": "창업 아이디어 경진대회",
            "pbanc_rcpt_end_dt": "20260910",
            "supt_biz_clsfc": "시설ㆍ공간ㆍ보육",
            "pbanc_ctnt": "사업화 자금을 최대 5천만원 지원합니다.",
        },
        source="K-Startup",
    )

    assert program is not None
    assert program.support_amount_text == "시설ㆍ공간ㆍ보육"
    assert program.max_amount == 50000000


def test_parse_date_handles_deadline_label() -> None:
    assert _parse_date("2026.09.16") == date(2026, 9, 16)


def test_normalize_bizinfo_program_maps_json_item_fields() -> None:
    program = _normalize_bizinfo_program(
        {
            "seq": "PBLN_001",
            "title": "충남 AI 헬스케어 사업화 지원사업",
            "link": "https://www.bizinfo.go.kr/example",
            "author": "중소벤처기업부",
            "excInsttNm": "충남지방중소벤처기업청",
            "description": "<div>사업비 최대 5천만원을 지원합니다.</div>",
            "lcategory": "창업",
            "reqstDt": "20260901 ~ 20260930",
            "trgetNm": "예비창업자",
            "hashTags": "2026,충남,AI,창업",
        }
    )

    assert program is not None
    assert program.program_id == "PBLN_001"
    assert program.source == "기업마당"
    assert program.open_date == date(2026, 9, 1)
    assert program.deadline == date(2026, 9, 30)
    assert program.region == "충남"
    assert program.max_amount == 50000000
    assert "AI" in program.keywords


def test_parse_date_range_handles_bizinfo_period() -> None:
    assert _parse_date_range("2026.09.01 ~ 2026.09.30") == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )
