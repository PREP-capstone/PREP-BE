"""조문 표기 정규화 (db_구축_설계서.md §1.5.1, 2026-07-28 확정).

`legal_basis_article`은 RAG `evidence_chunks.section_id`와의 **join 키**다. 표기가 어긋나면
근거 조회가 예외 없이 조용히 실패하므로, 프롬프트 지시에만 의존하지 않고 LLM 출력을 코드에서
한 번 더 정규화한다.

규칙
- 로마숫자: 유니코드 로마숫자(Ⅲ, U+2162)를 ASCII 대문자로 통일 (`Ⅲ` → `III`)
- 구분자: 마침표 `.`로 통일, 끝에 마침표 없음
- 공백: 제거하되 구분자가 없던 자리는 마침표로 대체 (`부록2 Q11` → `부록2.Q11`)
- 조문은 `제23조`, 별표는 `별표7.제8호` 형태 유지 — **법령(statute) 조문은 장(章) 접두어를
  붙이지 않는다.** §1.5.1 예시 표(`의료기기법 | 제2조, 제24조`)가 이미 이 형태다.
  chunk.py의 청크 계층("제1장.제2조")은 청킹 내부용이고, 최종 인용 표기는 아니다.
  약사법 실전 추출에서 LLM이 조문 위치 힌트를 그대로 베껴 "제1장.제2조"를 낸 사례가
  있어(2026-08-14), 코드에서 장 접두어를 무조건 제거한다.
"""

import re

# U+2160~U+216F(대문자), U+2170~U+217F(소문자) 로마숫자 → ASCII 대문자
_ROMAN_NUMERALS = "I II III IV V VI VII VIII IX X XI XII L C D M".split()
_ROMAN_TRANSLATION = {
    **{0x2160 + i: numeral for i, numeral in enumerate(_ROMAN_NUMERALS)},
    **{0x2170 + i: numeral for i, numeral in enumerate(_ROMAN_NUMERALS)},
}

# 공백과 마침표가 잇달아 나오는 구간을 마침표 하나로 접는다.
# "Ⅲ. 2. 가." → "III.2.가.", "부록2 Q11" → "부록2.Q11"
_SEPARATOR_RUN = re.compile(r"[\s.]+")

# 법령 조문의 장(章) 접두어. 청킹 내부 계층("제1장.제2조")을 LLM이 그대로 베껴 쓰는
# 경우가 있어 코드에서 제거한다. 뒤에 뭔가 이어질 때만 지운다 — "제5장" 단독 값은
# (장 전체를 가리키는 드문 케이스) 건드리지 않는다.
_CHAPTER_PREFIX = re.compile(r"^제\d+장\.(?=.)")


def _normalize_symbols(article: str) -> str:
    """로마숫자·구분자·공백만 정리한다. 장 접두어는 그대로 둔다.

    chunk.py가 내부 계층 라벨("제1장.제2조")을 만들 때 쓴다 — 이 값은 최종 인용이
    아니라 LLM 프롬프트 힌트일 뿐이라 장 정보를 남겨둬야 한다(§4.6 법령 개정 대응 등
    상위 구조 추적에 쓰일 수 있다).
    """
    normalized = article.translate(_ROMAN_TRANSLATION)
    normalized = _SEPARATOR_RUN.sub(".", normalized)
    return normalized.strip(".")


def normalize_article(article: str | None) -> str | None:
    """조문 표기를 §1.5.1 규칙대로 정규화한다. None/빈 문자열은 그대로 통과시킨다.

    LLM이 반환한 article(extract_a/b/c.py)이나 수기 입력값(seed 스크립트)에 쓴다.
    `_normalize_symbols`에 더해 법령 장 접두어까지 제거해 **최종 인용 표기**를 만든다.
    """
    if not article:
        return article

    normalized = _normalize_symbols(article)
    normalized = _CHAPTER_PREFIX.sub("", normalized)
    return normalized


def build_chunk_message(chunk: dict) -> str:
    """청크를 LLM 입력 메시지로 만든다.

    청킹 단계가 계산해 둔 `article_number`(예: `III.2`)를 함께 넘긴다. 이 값을 주지 않으면
    LLM이 본문만 보고 조문 번호를 추측하게 되고, join 키인 legal_basis_article이 흔들린다.
    """
    article_number = chunk.get("article_number")
    if not article_number:
        return chunk["content"]
    return f"[조문 위치] {article_number}\n[본문]\n{chunk['content']}"


# Stage A/B/C 프롬프트 공용 — LLM이 처음부터 정규화된 형태로 뱉게 유도한다.
# (코드에서 normalize_article()로 한 번 더 걸러내므로 이건 1차 방어선이다)
ARTICLE_NOTATION_PROMPT = """## 조문 표기 규칙 (반드시 지킬 것)
입력 맨 앞에 `[조문 위치]`가 주어지면 **그 값을 article의 기준으로 삼으세요.** 본문에 하위 항목
(가/나/다, ①②③ 등)이 명시돼 있고 그 항목이 근거라면 뒤에 이어 붙입니다
(예: 조문 위치가 `III.2`이고 본문의 "가 위해도판단요소"가 근거면 → `III.2.가`).
추측으로 새 번호를 만들지 마세요.

article은 아래 형식으로 출력하세요. 이 값은 근거 문서 조회의 join 키라서 표기가 어긋나면
근거를 찾지 못합니다.
- 로마숫자는 ASCII 대문자로: `Ⅲ` → `III`, `Ⅳ` → `IV` (유니코드 로마숫자 문자를 쓰지 말 것)
- 구분자는 마침표, 공백 없이, 끝에 마침표 없이: `Ⅲ. 2. 가.` → `III.2.가`
- 조문은 `제23조`, 별표는 `별표7.제8호` 형태
- 예시: `III.2.가`, `IV.1.가`, `IV.3`, `제2조`, `제45조`, `별표7.제8호`, `부록2.Q11`"""
