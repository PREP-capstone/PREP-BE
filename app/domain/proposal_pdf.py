"""제안서 PDF 바이너리 생성 (§6-7 후속 작업, 이슈 #102).

reportlab을 쓴다 -- weasyprint 등 HTML->PDF 방식은 pango/cairo 같은 시스템
라이브러리가 필요해 Docker 배포(EC2_DOCKER_NGINX_DEPLOYMENT.md)에 부담이 되지만,
reportlab은 순수 파이썬이라 requirements.txt 추가만으로 끝난다.

⚠️ **한글 폰트는 PDF 표준 내장 CID 폰트(HYGothic-Medium 등)를 쓰지 않는다.** 처음
그렇게 시도했다가 실제로 렌더링 결과를 이미지로 확인해보니, 뷰어에 한글 폰트가 없는
환경(이 저장소가 배포되는 것과 비슷한 최소 구성 리눅스 서버 다수 포함)에서는 한글
글자가 통째로 빈 칸으로 나오는 것을 확인했다 -- CID 폰트는 "글자를 뷰어가 가진
시스템 폰트로 그려달라"는 참조일 뿐 폰트 자체를 담고 있지 않아서다. 그래서 나눔고딕
TTF를 app/assets/fonts/에 실제로 넣고 PDF에 임베딩(자동 서브셋팅으로 실제 용량은
문서에서 쓰는 글자만 남아 수십 KB 수준)한다 -- 어떤 뷰어에서 열어도 항상 같게 보인다.
나눔고딕은 SIL Open Font License(OFL)로 재배포 가능(app/assets/fonts/OFL.txt).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.domain.proposal_render_common import TEMPLATE_TITLES

_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT_REGULAR = "NanumGothic"
FONT_BOLD = "NanumGothic-Bold"

# 모듈 임포트 시 1회만 등록한다 -- registerFont를 요청마다 부르면 매번 TTF 파일을
# 다시 파싱하므로 낭비다. reportlab은 같은 이름 재등록도 안전하게 덮어쓴다.
pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(_FONT_DIR / "NanumGothic-Regular.ttf")))
pdfmetrics.registerFont(TTFont(FONT_BOLD, str(_FONT_DIR / "NanumGothic-Bold.ttf")))

_TITLE_STYLE = ParagraphStyle("ProposalTitle", fontName=FONT_BOLD, fontSize=16, leading=22, spaceAfter=4)
_HEADING_STYLE = ParagraphStyle("ProposalHeading", fontName=FONT_BOLD, fontSize=12, leading=16, spaceBefore=14, spaceAfter=6)
_BODY_STYLE = ParagraphStyle("ProposalBody", fontName=FONT_REGULAR, fontSize=10, leading=15)


def render_proposal_pdf(template_type: str, sections: list[dict]) -> bytes:
    """sections: [{"field_key", "label", "field_type", "value"}, ...] (표시 순서대로).

    field_type에 따라 렌더링 방식이 갈린다 -- TEXT는 문단, CHECKLIST는 불릿 목록,
    TABLE은 표(첫 행의 키를 헤더로 사용).
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )

    story = [
        Paragraph(TEMPLATE_TITLES.get(template_type, "사업계획서"), _TITLE_STYLE),
        Spacer(1, 6 * mm),
    ]
    for section in sections:
        story.append(Paragraph(section["label"], _HEADING_STYLE))
        story.append(_render_value(section["field_type"], section["value"]))

    doc.build(story)
    return buffer.getvalue()


def _render_value(field_type: str, value: object):
    """field_type과 value의 실제 모양이 어긋나면(예: TABLE인데 문자열이 옴) 예외를
    던지지 않고 안전하게 렌더링한다.

    ⚠️ **리뷰 중 발견한 회귀**: `POST /{id}/complete`의 CompleteSection은 field_key뿐
    아니라 field_type/value도 클라이언트(프론트)가 그대로 보내온 값을 신뢰한다 --
    즉 프론트 구현이 잘못돼서 field_type="TABLE"인데 value로 문자열을 보내면, 고치기
    전에는 `rows[0]`가 문자열의 첫 글자가 되고 `.keys()` 호출에서 AttributeError가
    나서 `GET /{id}/pdf` 전체가 처리되지 않은 500으로 죽었다. CHECKLIST도 마찬가지로
    문자열이 오면 글자 단위로 쪼개져 불릿마다 한 글자씩 찍히는 조용한 오류였다.
    아래 isinstance 체크가 그 두 경우 모두를 막는다.
    """
    if field_type == "CHECKLIST":
        if not isinstance(value, list) or not value:
            return Paragraph("(항목 없음)" if not value else "(형식 오류로 표시할 수 없습니다)", _BODY_STYLE)
        return ListFlowable(
            [ListItem(Paragraph(str(item), _BODY_STYLE)) for item in value],
            bulletType="bullet",
        )

    if field_type == "TABLE":
        if not isinstance(value, list) or not value or not all(isinstance(row, dict) for row in value):
            return Paragraph("(작성된 내용 없음)" if not value else "(형식 오류로 표시할 수 없습니다)", _BODY_STYLE)
        headers = list(value[0].keys())
        data = [headers] + [[str(row.get(header, "")) for header in headers] for row in value]
        table = Table(data)
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ]
            )
        )
        return table

    # TEXT (기본값 -- 알 수 없는 field_type이 들어와도 문단으로는 보여준다)
    text = value if isinstance(value, str) and value.strip() else "(작성된 내용 없음)"
    return Paragraph(text.replace("\n", "<br/>"), _BODY_STYLE)
