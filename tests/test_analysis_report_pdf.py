"""검진 리포트 PDF 임시 캐시·다운로드 회귀 테스트."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pytest
from fastapi.responses import Response
from pypdf import PdfReader

from app.api import reports
from app.api.analysis_sessions import AnalysisSessionDetail, AnalysisSessionDetailResponse, HealthDataItemResponse
from app.domain import analysis_report_cache
from app.domain.analysis_report_pdf import render_analysis_report_pdf


def _report(verdict: str = "PASS") -> dict:
    return {
        "session": {
            "session_id": "session_pdf_test",
            "service_name": "혈당 기록 서비스",
            "service_description": "사용자가 혈당을 기록하고 추이를 확인하는 서비스입니다.",
            "target_users": ["건강관리 사용자"],
            "service_type": "모바일 앱",
            "category_1": "만성질환",
            "category_2": "데이터기록관리",
            "health_data_items": [{"name": "혈당"}],
        },
        "gate": {
            "verdict": verdict,
            "data_type": "생체지표",
            "function_type": "단순기록",
            "reasoning": ["혈당을 직접 기록합니다."],
            "legal_basis": {
                "title": "의료기기와 개인용 건강관리 제품 판단기준",
                "article": "IV.3",
                "quote_status": "FOUND",
                "quote": "개인용 건강관리제품과 의료기기 판단 사례입니다.",
            },
            "avoidance_redesign": "기록 기능 중심으로 재설계합니다.",
            "avoidance_certification": "허가 요건을 확인합니다.",
        },
        "regulatory_risk": {
            "regulatory_score": 1,
            "regulatory_grade": "낮음",
            "privacy_score": 2,
            "privacy_grade": "중간",
            "advertising_score": 0,
            "advertising_grade": "낮음",
            "final_regulatory_grade": "중간",
            "applicable_laws": ["개인정보 보호법"],
            "matched_rules": [],
        },
        "data_feasibility": {"risk_level": "LOW", "data_feasibility_score": 3, "privacy_grade": "중간", "privacy_risks": []},
        "market_feasibility": {
            "market_realism_grade": "높음",
            "match_scope_description": "비교 가능한 선례를 찾았습니다.",
            "platform_competitor_summary": "플랫폼 경쟁사는 확인되지 않았습니다.",
            "domestic_demand": "상위권",
        },
        "business_model": {"match_scope_description": "유사한 수익 구조를 찾았습니다."},
        "bm_card_summaries": [{"bm_pattern": "Freemium", "bm_description": "기본 기능을 무료로 제공합니다.", "precedent_services": ["예시 서비스"], "strength": "진입장벽이 낮습니다."}],
        "overall_actions": [{"action_text": "개인정보 동의 절차를 설계하세요."}],
        "overall_signal": "노랑",
        "one_liner": "기록 기능 중심으로 시작하는 것이 좋습니다.",
        "differentiation_point": "사용자 기록 경험을 단순화하세요.",
    }


def _session_response() -> AnalysisSessionDetailResponse:
    return AnalysisSessionDetailResponse(
        isSuccess=True,
        code="ANALYSIS_SESSION_FOUND",
        message="분석 세션을 조회했습니다.",
        result=AnalysisSessionDetail(
            session_id="session_pdf_test",
            service_name="혈당 기록 서비스",
            service_description="설명",
            target_users=[],
            service_type=None,
            category_1=None,
            category_2=None,
            target=None,
            health_data_items=[
                HealthDataItemResponse(
                    name="혈당", data_type="numeric", unit=None, source="user_input", is_sensitive=True, item_code=None
                )
            ],
            processing_purpose=[],
            service_actions=[],
        ),
    )


@pytest.mark.parametrize("verdict", ["PASS", "FAIL"])
def test_render_analysis_report_pdf_has_embedded_korean_text(verdict: str) -> None:
    pdf = render_analysis_report_pdf(_report(verdict))

    assert pdf.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
    assert "PREP 아이디어 검진 리포트" in text
    assert "GATE 판정 결과 및 근거" in text
    if verdict == "FAIL":
        assert "후속 분석" in text
    else:
        assert "시장 현실성" in text


def test_render_analysis_report_pdf_wraps_long_legal_quote_across_pages() -> None:
    report = _report("FAIL")
    report["gate"]["legal_basis"]["quote"] = "긴 법령 원문입니다. " * 1_500

    pdf = render_analysis_report_pdf(report)

    assert len(PdfReader(BytesIO(pdf)).pages) >= 2


def test_report_filename_uses_korea_standard_time(monkeypatch) -> None:
    class SeoulDatetime:
        @classmethod
        def now(cls, timezone):
            assert getattr(timezone, "key", None) == "Asia/Seoul"
            return datetime(2026, 10, 24, 0, 5)

    monkeypatch.setattr(reports, "datetime", SeoulDatetime)

    assert reports._filename("혈당 기록 서비스", "session_pdf_test").endswith("_2026-10-24.pdf")


async def test_report_result_cache_uses_configured_ttl(monkeypatch) -> None:
    stored: dict[str, object] = {}

    class FakeRedis:
        async def set(self, key: str, value: str, *, ex: int) -> None:
            stored.update(key=key, value=value, ttl=ex)

        async def get(self, key: str) -> str | None:
            return stored["value"] if key == stored.get("key") else None

    monkeypatch.setattr(analysis_report_cache, "redis_client", FakeRedis())

    await analysis_report_cache.cache_analysis_result("session_pdf_test", {"verdict": "PASS"})
    result = await analysis_report_cache.load_analysis_result("session_pdf_test")

    assert stored["key"] == "analysis_report:session_pdf_test"
    assert stored["ttl"] == 600
    assert result == {"verdict": "PASS"}


async def test_download_report_pdf_returns_attachment(monkeypatch) -> None:
    async def fake_session_detail(_session_id: str):
        return _session_response()

    async def fake_cached_report(_session_id: str):
        return _report()

    monkeypatch.setattr(reports, "get_analysis_session_detail", fake_session_detail)
    monkeypatch.setattr(reports, "load_analysis_result", fake_cached_report)

    response = await reports.download_analysis_report_pdf("session_pdf_test")

    assert isinstance(response, Response)
    assert response.media_type == "application/pdf"
    assert response.body.startswith(b"%PDF")
    assert "attachment;" in response.headers["content-disposition"]
    assert "filename*=" in response.headers["content-disposition"]


async def test_download_report_pdf_returns_409_when_cache_expired(monkeypatch) -> None:
    async def fake_session_detail(_session_id: str):
        return _session_response()

    async def no_cached_report(_session_id: str):
        return None

    monkeypatch.setattr(reports, "get_analysis_session_detail", fake_session_detail)
    monkeypatch.setattr(reports, "load_analysis_result", no_cached_report)

    response = await reports.download_analysis_report_pdf("session_pdf_test")

    assert response.status_code == 409
    assert b"ANALYSIS_RESULT_REQUIRED" in response.body
