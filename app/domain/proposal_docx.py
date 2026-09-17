"""제안서 Word(.docx) 바이너리 생성 (프론트 요청 v6, 2026-09-11 -- 요청 2).

`GET /{id}/pdf`(app/domain/proposal_pdf.py)와 완전히 동일한 입력(sections: list[dict],
field_key/label/field_type/value)을 받아 같은 구조의 문서를 만든다 -- 다만 PDF와 달리
한글 폰트를 파일에 임베딩할 필요가 없다. docx는 폰트 파일 자체를 담지 않고 이름만
참조하는 포맷이라 애초에 임베딩이라는 개념이 다르게 동작하고(Word/한글 등 뷰어가
실행되는 OS에 어떤 폰트든 동아시아 문자를 그릴 폴백 폰트가 기본 내장돼 있다 -- PDF
전용 CID 폰트가 뷰어에 그 폰트 자체가 없으면 완전히 빈 칸이 되는 것과는 다른 문제),
그래서 여기서는 별도 폰트 처리를 하지 않는다.

_TEMPLATE_TITLES/_render_value의 분기 로직은 proposal_pdf.py와 의도적으로 대칭이다 --
두 렌더러가 같은 입력에 다른 포맷으로 동일한 내용을 내놔야 하므로, 한쪽 field_type
분기가 바뀌면 다른 쪽도 맞춰 바꿔야 한다.
"""

from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

# proposal_pdf.py의 _TEMPLATE_TITLES와 동일한 값 -- 새 template_type이 추가되면
# 양쪽 다 갱신해야 한다.
_TEMPLATE_TITLES = {
    "PSST": "창업사업화 지원사업 사업계획서",
    "RND": "R&D 과제 사업계획서",
    "IR": "투자유치용(IR) 사업계획서",
}


def render_proposal_docx(template_type: str, sections: list[dict]) -> bytes:
    """sections: [{"field_key", "label", "field_type", "value"}, ...] (표시 순서대로).

    render_proposal_pdf와 동일하게 field_type에 따라 문단/불릿목록/표로 나뉜다.
    """
    document = Document()

    title = document.add_heading(_TEMPLATE_TITLES.get(template_type, "사업계획서"), level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT

    for section in sections:
        document.add_heading(section["label"], level=2)
        _render_value(document, section["field_type"], section["value"])

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _render_value(document: Document, field_type: str, value: object) -> None:
    """proposal_pdf.py의 _render_value와 동일한 안전장치 -- field_type과 value의
    실제 모양이 어긋나도(예: TABLE인데 문자열이 옴) 예외를 던지지 않는다. PDF
    렌더러에서 실제로 겪었던 회귀(리뷰 중 발견, app/domain/proposal_pdf.py 참고)와
    같은 클래스의 문제라 동일한 isinstance 체크를 그대로 가져온다.
    """
    if field_type == "CHECKLIST":
        if not isinstance(value, list) or not value:
            document.add_paragraph("(항목 없음)" if not value else "(형식 오류로 표시할 수 없습니다)")
            return
        for item in value:
            document.add_paragraph(str(item), style="List Bullet")
        return

    if field_type == "TABLE":
        if not isinstance(value, list) or not value or not all(isinstance(row, dict) for row in value):
            document.add_paragraph("(작성된 내용 없음)" if not value else "(형식 오류로 표시할 수 없습니다)")
            return
        headers = list(value[0].keys())
        table = document.add_table(rows=1 + len(value), cols=len(headers), style="Table Grid")
        for col_index, header in enumerate(headers):
            cell = table.rows[0].cells[col_index]
            cell.text = str(header)
            cell.paragraphs[0].runs[0].bold = True
        for row_index, row in enumerate(value, start=1):
            for col_index, header in enumerate(headers):
                table.rows[row_index].cells[col_index].text = str(row.get(header, ""))
        return

    # TEXT (기본값 -- 알 수 없는 field_type이 들어와도 문단으로는 보여준다)
    text = value if isinstance(value, str) and value.strip() else "(작성된 내용 없음)"
    for line in text.split("\n"):
        document.add_paragraph(line)
