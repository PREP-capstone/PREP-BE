"""청킹 모드 판별·분할 회귀 테스트.

실제 PDF 없이 돌도록 추출 결과를 흉내낸 합성 텍스트를 쓴다. 실제 pypdf 출력의 특징
(공백 없음·문단이 한 줄로 이어짐)을 그대로 재현해야 의미가 있다.
"""

from app.pipeline.nodes.chunk import _detect_mode, _normalize_text, chunk_document

# 별표7 원문 형태 — 항목이 "제1호"가 아니라 "1." 이고 공백이 전혀 없다.
ANNEX_TEXT = (
    "■의료기기법시행규칙[별표7]금지되는광고의범위(제45조제1항관련)"
    "1.의료기기의명칭에관한거짓또는과대광고"
    "2.허가를받지않은의료기기의성능에관한광고"
    "3.의료기기의부작용을전부부정하는표현의광고"
    "4.임상시험성적서를거짓으로인용한광고"
    "5.의사가성능을보증한것으로오해할염려가있는광고"
    "6.대학교수가지도하고있다는내용의광고.다만,공공단체의경우에는그렇지않다."
    "7.외국제품을국내제품으로오인하게할우려가있는광고"
    "8.사용자의체험담을이용한광고"
    "9.최고라는절대적표현을사용한광고"
    "10.의료기기가아닌것으로오인하게할우려가있는광고"
    "11.의료기관이추천하고있는것처럼암시하는광고"
    "12.암시적방법을이용한광고"
    "13.사용전후의비교로결과를암시하는광고"
    "14.다른제품을비방하는광고"
    "15.외설적인도안을사용한광고"
    "16.수술장면을위협적으로표시하는광고"
    "17.심의를받지않은광고"
    "18.재심의요청을받은광고"
)

GUIDELINE_TEXT = (
    "Ⅰ 개요\n1.\x00배경최근융복합제품이등장하면서구분이모호한웰니스제품이개발되고있다.\n"
    "2.목적및적용범위이기준은의료기기법 제2조의 의료기기와개인용건강관리제품을구분한다.\n"
    "Ⅱ 용어의정의\n1.의료기기란질병을진단·치료하는제품을말한다.\n"
    "Ⅲ 판단기준\n1.고위해도요소침습적인제품은의료기기에해당한다.\n"
    "2.저위해도요소질병언급없는모니터링은해당하지않는다.\n"
)

STATUTE_TEXT = (
    "제1장 총칙\n제2조(정의) 이법에서사용하는용어의뜻은다음과같다.\n"
    "제3조(적용범위) 이법은의료기기에대하여적용한다.\n"
    "제4장 광고\n제24조(기재및광고의금지) 누구든지의료기기의명칭에관하여거짓광고를하지못한다.\n"
)


def test_annex_splits_into_eighteen_items() -> None:
    """별표7은 제1호~제18호가 각각 독립 청크여야 한다.

    advertising_score 척도가 18개 항목 번호에 매여 있어(§1.5.1), 항목이 뭉치면
    판정 근거를 항목 단위로 인용할 수 없다.
    """
    chunks = chunk_document({"raw_text": ANNEX_TEXT, "document_id": "d"})["chunks"]
    assert [c["article_number"] for c in chunks] == [str(n) for n in range(1, 19)]


def test_annex_item_1_and_7_are_not_dropped() -> None:
    """회귀: 앞 항목이 ')' 또는 '.'로 끝나면 다음 항목을 놓치던 버그.

    "(제45조제1항관련)1." 과 "그렇지않다.7." 이 각각 제1호·제7호인데, 숫자 앞 문자를
    따지는 룩비하인드에 걸려 통째로 누락됐다.
    """
    chunks = chunk_document({"raw_text": ANNEX_TEXT, "document_id": "d"})["chunks"]
    by_number = {c["article_number"]: c["content"] for c in chunks}
    assert "의료기기의명칭" in by_number["1"]
    assert "외국제품" in by_number["7"]


def test_annex_marker_must_be_in_title_position() -> None:
    """본문에서 "[별표7]"을 인용만 한 지침서는 별표로 보지 않는다.

    위치를 안 따지면 모바일앱지침(2752번째 글자에 인용)이 별표로 잡혀 38청크가
    95청크로 부서졌다.
    """
    # 인용은 제목 위치(앞 200자)를 훌쩍 넘긴 본문 어딘가에 나타난다.
    quoting_guideline = GUIDELINE_TEXT * 3 + "\n자세한내용은 [별표7] 을참고한다.\n"
    assert quoting_guideline.index("[별표7]") > 200
    assert _detect_mode(_normalize_text(quoting_guideline)) == "guideline"
    assert _detect_mode(_normalize_text(ANNEX_TEXT)) == "annex"


def test_guideline_mode_builds_hierarchical_article_numbers() -> None:
    """지침서는 로마숫자 + 숫자 계층을 만든다 (III.2 형태)."""
    chunks = chunk_document({"raw_text": GUIDELINE_TEXT, "document_id": "d"})["chunks"]
    numbers = [c["article_number"] for c in chunks]
    assert "III.1" in numbers and "III.2" in numbers
    assert all("Ⅲ" not in n for n in numbers), "유니코드 로마숫자가 남으면 RAG 조인이 깨진다"


def test_guideline_does_not_split_on_article_citations() -> None:
    """지침서의 "제2조"는 헤딩이 아니라 인용이라 분할 지점이 되면 안 된다."""
    chunks = chunk_document({"raw_text": GUIDELINE_TEXT, "document_id": "d"})["chunks"]
    citing = next(c for c in chunks if "제2조의 의료기기" in c["content"])
    assert citing["article_number"] == "I.2"


def test_statute_mode_uses_chapter_and_article() -> None:
    chunks = chunk_document({"raw_text": STATUTE_TEXT, "document_id": "d"})["chunks"]
    numbers = [c["article_number"] for c in chunks]
    assert "제1장.제2조" in numbers
    assert "제4장.제24조" in numbers
