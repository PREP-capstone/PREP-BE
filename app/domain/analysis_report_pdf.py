"""아이디어 검진 결과를 서버 PDF로 렌더링한다.

제안서 PDF와 마찬가지로 나눔고딕 TTF를 PDF에 임베딩한다. HTML 화면 캡처가 아니라
검진 결과 JSON을 그대로 조립하므로 모바일 브라우저에서도 같은 파일을 내려받을 수 있다.
"""

from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
_FONT_REGULAR = "AnalysisNanumGothic"
_FONT_BOLD = "AnalysisNanumGothic-Bold"
pdfmetrics.registerFont(TTFont(_FONT_REGULAR, str(_FONT_DIR / "NanumGothic-Regular.ttf")))
pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(_FONT_DIR / "NanumGothic-Bold.ttf")))

_TITLE = ParagraphStyle("analysis-title", fontName=_FONT_BOLD, fontSize=17, leading=24, spaceAfter=4)
_SUBTITLE = ParagraphStyle("analysis-subtitle", fontName=_FONT_REGULAR, fontSize=9, leading=14, textColor=colors.HexColor("#666666"))
_HEADING = ParagraphStyle("analysis-heading", fontName=_FONT_BOLD, fontSize=12, leading=17, spaceBefore=12, spaceAfter=5)
_BODY = ParagraphStyle("analysis-body", fontName=_FONT_REGULAR, fontSize=9.5, leading=15, wordWrap="CJK")
_QUOTE = ParagraphStyle("analysis-quote", parent=_BODY, leftIndent=8 * mm, rightIndent=4 * mm, textColor=colors.HexColor("#444444"))
_SMALL = ParagraphStyle("analysis-small", parent=_BODY, fontSize=8.5, leading=13, textColor=colors.HexColor("#555555"))


def _text(value: Any, default: str = "정보 없음") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or default
    return str(value)


def _paragraph(value: Any, style: ParagraphStyle = _BODY, default: str = "정보 없음") -> Paragraph:
    safe = escape(_text(value, default)).replace("\n", "<br/>")
    return Paragraph(safe, style)


def _section(title: str, body: list[Any]) -> KeepTogether:
    return KeepTogether([Paragraph(escape(title), _HEADING), *body, Spacer(1, 2 * mm)])


def _summary_table(rows: list[tuple[str, Any]]) -> Table:
    data = [[_paragraph(label, _SMALL), _paragraph(value, _SMALL)] for label, value in rows]
    table = Table(data, colWidths=[42 * mm, 128 * mm], repeatRows=0)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _legal_basis_block(basis: dict[str, Any] | None) -> list[Any]:
    if not basis:
        return []
    title = " ".join(part for part in (basis.get("title"), basis.get("article")) if part)
    output = [Paragraph(escape(title or "판정 근거"), _BODY)]
    if basis.get("quote_status") == "FOUND" and basis.get("quote"):
        output.append(_paragraph(basis["quote"], _QUOTE))
    elif basis.get("quote_message"):
        output.append(_paragraph(basis["quote_message"], _SMALL))
    return output


def render_analysis_report_pdf(report: dict[str, Any]) -> bytes:
    """캐시된 EvaluateResult JSON을 다페이지 PDF로 만든다."""
    session = report["session"]
    gate = report["gate"]
    regulatory = report["regulatory_risk"]
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        title="PREP 아이디어 검진 리포트",
        author="PREP",
    )
    story: list[Any] = [
        Paragraph("PREP 아이디어 검진 리포트", _TITLE),
        _paragraph(session.get("service_name"), _SUBTITLE, "서비스명 없음"),
        Spacer(1, 5 * mm),
        _summary_table(
            [
                ("종합 신호등", report.get("overall_signal")),
                ("GATE 판정", gate.get("verdict")),
                ("규제 위험도", regulatory.get("final_regulatory_grade")),
                ("한 줄 총평", report.get("one_liner")),
            ]
        ),
        Spacer(1, 4 * mm),
    ]

    story.append(
        _section(
            "서비스 개요",
            [
                _summary_table(
                    [
                        ("서비스 설명", session.get("service_description")),
                        ("타깃 사용자", session.get("target_users")),
                        ("서비스 유형", session.get("service_type")),
                        ("카테고리", " / ".join(filter(None, [session.get("category_1"), session.get("category_2")]))),
                        ("수집 데이터", [item.get("name") for item in session.get("health_data_items", [])]),
                    ]
                )
            ],
        )
    )

    gate_body: list[Any] = [
        _summary_table(
            [
                ("판정", gate.get("verdict")),
                ("데이터 유형", gate.get("data_type")),
                ("기능 유형", gate.get("function_type")),
                ("판정 사유", gate.get("reasoning")),
            ]
        ),
        *_legal_basis_block(gate.get("legal_basis")),
    ]
    if gate.get("verdict") == "FAIL":
        gate_body.extend(
            [
                _paragraph("의료기기 해당 가능성이 높아 데이터 확보 가능성, 시장 현실성, 수익 구조 분석은 제외했습니다."),
                _paragraph(gate.get("avoidance_redesign"), _BODY, "서비스 목적과 기능을 다시 설계해 검진해주세요."),
                _paragraph(gate.get("avoidance_certification"), _BODY, "인증·허가 요건을 검토해주세요."),
            ]
        )
    story.append(_section("GATE 판정 결과 및 근거", gate_body))

    matched_rules = regulatory.get("matched_rules") or []
    regulatory_body: list[Any] = [
        _summary_table(
            [
                ("의료행위 표현", f"{regulatory.get('regulatory_score', 0)}점 / {regulatory.get('regulatory_grade') or '정보 없음'}"),
                ("개인정보 민감도", f"{regulatory.get('privacy_score', 0)}점 / {regulatory.get('privacy_grade') or '정보 없음'}"),
                ("광고 표현 위험", f"{regulatory.get('advertising_score', 0)}점 / {regulatory.get('advertising_grade') or '정보 없음'}"),
                ("적용 법령", regulatory.get("applicable_laws")),
            ]
        )
    ]
    for rule in matched_rules:
        regulatory_body.extend(_legal_basis_block(rule.get("legal_basis")))
    story.append(_section("규제 위험도", regulatory_body))

    if gate.get("verdict") == "FAIL":
        story.append(_section("후속 분석", [_paragraph("GATE FAIL로 데이터 확보 가능성, 시장 현실성, 수익 구조 분석을 제외했습니다. 서비스를 재설계한 뒤 다시 검진해주세요.")]))
    else:
        data = report.get("data_feasibility") or {}
        story.append(
            _section(
                "데이터 확보 가능성",
                [_summary_table([("확보 난이도", data.get("risk_level")), ("난이도 점수", data.get("data_feasibility_score")), ("개인정보 위험", data.get("privacy_grade")), ("개인정보 검토 항목", [item.get("data_name") for item in data.get("privacy_risks", [])])])],
            )
        )
        market = report.get("market_feasibility") or {}
        story.append(
            _section(
                "시장 현실성",
                [_summary_table([("시장 현실성", market.get("market_realism_grade")), ("비교 범위", market.get("match_scope_description")), ("플랫폼 경쟁", market.get("platform_competitor_summary")), ("국내 수요", market.get("domestic_demand")), ("차별화 포인트", report.get("differentiation_point"))])],
            )
        )
        business = report.get("business_model") or {}
        bm_lines: list[Any] = [_paragraph(business.get("match_scope_description"), _BODY)]
        for card in report.get("bm_card_summaries") or []:
            bm_lines.append(_summary_table([("수익 구조", card.get("bm_pattern")), ("설명", card.get("bm_description")), ("선례", card.get("precedent_services")), ("적합성", card.get("strength"))]))
        story.append(_section("수익 구조", bm_lines))

    actions = report.get("overall_actions") or report.get("next_actions") or []
    story.append(_section("다음 액션", [_paragraph([item.get("action_text") for item in actions], _BODY, "제안된 다음 액션이 없습니다.")]))
    doc.build(story)
    return buffer.getvalue()
