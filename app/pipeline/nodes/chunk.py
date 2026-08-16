"""[2] 텍스트 추출·청킹 노드. 조문 헤딩 단위로 raw_text를 분할한다.

실제 법령 PDF에서 확인된 제약을 반영한 구현이다(2026-08-12, 웰니스 지침서 0091-03 기준).

- pypdf가 문단을 통째로 한 줄로 뽑아내 **헤딩이 줄 중간에 박힌다**. 줄머리(`^`) 앵커로는
  분할되지 않아 위치 무관 매칭을 쓴다.
- 헤딩의 공백이 **NUL 문자로 추출**되는 경우가 있다(`1.\x00배경`). 먼저 정규화한다.
- 목차는 본문과 같은 헤딩 문자열을 갖되 점선 리더(`Ⅲ. 판단기준 ······`)가 붙는다.
  걸러내지 않으면 목차가 본문 청크로 잡힌다.

**문서 유형에 따라 헤딩 패턴이 다르다.** 지침서에서 `제2조`는 헤딩이 아니라 다른 법령을 가리키는
**인용**이라, 법령용 패턴을 그대로 적용하면 "의료기기법 제2조의 의료기기" 같은 문장이 조각난다.
그래서 본문 구조를 보고 모드를 정한다(`_detect_mode`).

가/나/다 단위까지는 쪼개지 않는다 — 공백이 없는 추출 텍스트에서 헤딩 "가."와 문장 종결 "…한다."를
구분할 수 없어 오분할 위험이 크다. 대신 상위 위치를 `article_number`로 넘기고 하위 항목은 LLM이
본문에서 읽게 한다.
"""

import re
import uuid

from app.pipeline.article_ref import _normalize_symbols
from app.pipeline.state import Chunk, PipelineState

_ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"

# 목차 줄: 점선 리더가 5개 이상 이어진다
_TOC_LINE = re.compile(r"^[^\n]*[·․．.]{5,}[^\n]*$", re.MULTILINE)
# 페이지 표시: "- 12 -"
_PAGE_MARKER = re.compile(r"^\s*-\s*\d+\s*-\s*$", re.MULTILINE)

_ROMAN_HEADING = re.compile(rf"[{_ROMAN}](?=[\s.])")
# 1. 배경 — 숫자 뒤 마침표 + 한글. 연도("2026.2")·각주("1)")와 겹치지 않게 2자리까지만 본다.
_NUM_HEADING = re.compile(r"(?<![\d.)])[1-9]\d?\.\s*(?=[가-힣])")
# 법령 조문 헤딩은 제목 괄호를 동반한다: 제2조(정의). 괄호를 요구해야 본문 인용과 구분된다.
_ARTICLE_HEADING = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?(?=\s*\()")
_CHAPTER_HEADING = re.compile(r"제\s*\d+\s*장(?=\s)")
# 부칙(附則)은 본문 조문 번호를 제1조부터 다시 매긴다. 챕터 헤딩으로 인식하지 않으면
# 마지막으로 본 장(예: 제5장) 소속으로 잘못 태깅된다 — 약사법 발췌본에서 부칙
# 제1~4조가 "제5장.제N조"로 잘못 붙던 걸 실사례로 확인했다(2026-08-13).
_ADDENDA_HEADING = re.compile(r"(?<![가-힣])부칙(?![가-힣])")
# 별표 항목: "제1호" 표기와 "1." 표기를 모두 받는다.
# 실제 별표7 원문은 "제1호"가 아니라 "1.의료기기의…" 형식이었다.
_ITEM_HEADING = re.compile(r"제\s*\d+\s*호")
# 별표 안에서는 "N."이 곧 항목 번호라 앞 글자를 따지지 않는다. `(?<!\d)`만 둬서 "18."을
# "8."로 쪼개는 것만 막는다. _NUM_HEADING의 `(?<![\d.)])`를 그대로 쓰면 ")1."(제1호)과
# "다.7."(제7호)처럼 앞 항목이 괄호·마침표로 끝난 경우를 놓친다.
_ANNEX_ITEM_HEADING = re.compile(r"(?<!\d)[1-9]\d?\.\s*(?=[가-힣])")
# 별표 문서 표식: "[별표 7]". **제목 위치에 있을 때만** 별표 문서로 본다.
# 다른 지침서도 본문에서 "[별표 7]"을 인용하므로(모바일앱지침은 2752번째 글자에 등장),
# 위치를 따지지 않으면 일반 지침서가 별표로 오분류돼 문단이 잘게 부서진다.
_ANNEX_MARKER = re.compile(r"\[\s*별표")
_ANNEX_TITLE_WINDOW = 200

# 모드별 (레벨, 패턴). 레벨이 작을수록 상위다.
_MODES = {
    "guideline": [(1, _ROMAN_HEADING), (2, _NUM_HEADING)],
    "statute": [(1, _CHAPTER_HEADING), (1, _ADDENDA_HEADING), (2, _ARTICLE_HEADING)],
    "annex": [(1, _ITEM_HEADING), (1, _ANNEX_ITEM_HEADING)],
}


def _normalize_text(raw_text: str) -> str:
    text = raw_text.replace("\x00", " ")
    text = _TOC_LINE.sub("", text)
    text = _PAGE_MARKER.sub("", text)
    return text


def _detect_mode(text: str) -> str:
    """본문 구조를 보고 헤딩 체계를 고른다.

    지침서(로마숫자 목차)와 법령(제N조)은 같은 문자열을 정반대 의미로 쓴다 — 지침서의 `제2조`는
    인용이고, 법령의 `제2조(정의)`는 헤딩이다. 문서 유형을 잘못 잡으면 조용히 오분할된다.
    """
    # 별표 표식을 가장 먼저 본다. 별표 본문에도 로마숫자·조문 인용이 섞일 수 있어
    # 뒤로 미루면 다른 모드로 잘못 잡힌다(별표7이 실제로 guideline으로 분류됐었다).
    annex_marker = _ANNEX_MARKER.search(text)
    if annex_marker and annex_marker.start() < _ANNEX_TITLE_WINDOW:
        return "annex"
    if len(_ROMAN_HEADING.findall(text)) >= 3:
        return "guideline"
    if len(_ARTICLE_HEADING.findall(text)) >= 3:
        return "statute"
    if len(_ITEM_HEADING.findall(text)) >= 3:
        return "annex"
    return "guideline"


def _collect_headings(text: str, mode: str) -> list[tuple[int, int, int, str]]:
    """(시작, 끝, 레벨, 라벨) 목록을 위치순으로 모은다."""
    found: list[tuple[int, int, int, str]] = []
    for level, pattern in _MODES[mode]:
        for match in pattern.finditer(text):
            label = re.sub(r"\s+", "", match.group()).rstrip(".")
            found.append((match.start(), match.end(), level, label))
    found.sort(key=lambda item: item[0])

    # 같은 위치에서 여러 패턴이 잡히면 더 상위 레벨만 남긴다
    deduped: list[tuple[int, int, int, str]] = []
    for entry in found:
        if deduped and entry[0] < deduped[-1][1]:
            continue
        deduped.append(entry)
    return deduped


def chunk_document(state: PipelineState) -> dict:
    text = _normalize_text(state["raw_text"])
    mode = _detect_mode(text)
    headings = _collect_headings(text, mode)

    if not headings:
        return {"chunks": [_build_chunk(state, article_number="", content=text)]}

    chunks: list[Chunk] = []
    stack: dict[int, str] = {}
    for i, (_, heading_end, level, label) in enumerate(headings):
        stack = {depth: value for depth, value in stack.items() if depth < level}
        stack[level] = label

        start = heading_end
        end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        content = text[start:end].strip()
        if not content:
            continue

        # 기호만 정리한다(장 접두어는 유지) — 최종 인용용 정리는 extract_a/b/c.py가
        # LLM 출력에 normalize_article()을 적용할 때 한다 (article_ref.py 참조).
        article_number = _normalize_symbols(".".join(stack[d] for d in sorted(stack)))
        chunks.append(_build_chunk(state, article_number=article_number, content=content))

    return {"chunks": chunks}


def _build_chunk(state: PipelineState, article_number: str, content: str) -> Chunk:
    return {
        "chunk_id": str(uuid.uuid4()),
        "document_id": state["document_id"],
        "article_number": article_number,
        "section_path": article_number,  # TODO: 계층형 경로 미구현
        "content": content,
        "source": "own",
    }
