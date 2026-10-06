"""신뢰성(재현성)·타당성 측정 스크립트 — 팀 문서 "PREP 신뢰성·타당성 검증 계획" 참고.

    python scripts/eval_reliability.py run      --golden data/eval/golden_set_<이름>.csv [--runs 10] [--split test]
    python scripts/eval_reliability.py kappa    --golden data/eval/golden_set_<이름>.csv
    python scripts/eval_reliability.py baseline --golden data/eval/golden_set_<이름>.csv [--runs 10] [--temperature 1.0]
                                                [--compare data/eval/results/run_....json]
    python scripts/eval_reliability.py bm-loo

run       골든셋 각 행으로 분석 세션을 만들고 /analysis/evaluate와 같은 함수(evaluate_analysis)를
          --runs번 반복 호출한다. 출력을 층(A 판정값 / B 근거 / C 분류 모델 / D LLM 서술)으로 나눠
          재현성을 재고, 정답 라벨이 있는 행은 타당성(정확도·FAIL 재현율 등)도 계산한다.
          LLM 응답 캐시는 끄고 돈다(settings.llm_response_cache_enabled) — 켜두면 두 번째부터 캐시
          히트라 재현성이 저절로 100%가 된다. 트렌드(외부 데이터) 캐시는 "같은 기준 시점"을
          고정하는 역할이라 그대로 둔다. 세션은 끝나면 지운다(--keep-sessions로 보존).
kappa     rater_N_gate 열로 평가자 간 일치도(쌍별 Cohen's κ, Fleiss' κ)를 계산한다. DB·API 불필요.
baseline  같은 골든셋을 LLM에게 직접 PASS/CONDITIONAL/FAIL로 판정시켜 --runs번 반복한다 —
          "LLM 단독 판정 vs PREP" 비교용. --compare로 run 결과를 주면 나란히 비교한 표를 만든다.
bm-loo    경쟁사 DB에서 한 곳씩 빼고 그 서비스의 조회 키로 BM을 추천했을 때 실제 BM이 상위 2개에
          드는지(leave-one-out) 잰다. "가장 흔한 BM 2개 고정 추천" 베이스라인과 비교한다.

결과는 --out 폴더(기본 data/eval/results)에 JSON(행별 상세)과 Markdown(요약 표)으로 저장한다.
DB·Redis·OPENAI_API_KEY는 서버와 같은 .env를 쓴다. 실행 조건(git 커밋, 모델, 활성 rule_version)을
결과에 같이 남긴다 — "같은 조건에서 같은 결과"를 나중에 다시 확인할 수 있게 하기 위해서다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import itertools
import json
import math
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    # encoding: 한글 출력이 콘솔 코드페이지에 깨지지 않도록 / line_buffering: 오래 도는 측정이라
    # 파일로 리다이렉트해도 진행 상황이 바로 보이게 (run_pipeline.py와 같은 이유)
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from fastapi.responses import JSONResponse
from sqlalchemy import delete, select

from app.api.analysis_sessions import (
    AnalysisSession,
    CreateAnalysisSessionRequest,
    HealthDataUpsertRequest,
    create_analysis_session,
    create_health_data,
)
from app.api.business_model import _normalize_bm_pattern
from app.api.evaluate import EvaluateRequest, evaluate_analysis
from app.api.judgement import _match_gate_keywords
from app.core.config import settings
from app.core.redis_client import redis_client
from app.db.models import Competitor
from app.db.rule_version_queries import resolve_active_rule_version_ids
from app.db.session import AsyncSessionLocal, engine
from app.domain.category_classifier import CategoryModelUnavailable, predict_categories
from app.domain.health_data import SOURCE_TO_ACQUIRE_METHOD
from app.schemas.common import HealthDataItemInput

DEFAULT_OUT_DIR = ROOT / "data" / "eval" / "results"
VERDICTS = ("PASS", "CONDITIONAL", "FAIL")
_RATER_COLUMN = re.compile(r"rater_\d+_gate")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WHITESPACE = re.compile(r"\s+")
# 종합 신호등 색과 반대되는 색을 말하면 불변식 위반 — report_llm.py LLM④⑤ 프롬프트가 금지한 것.
_SIGNAL_WORDS = {"빨강": ("빨강", "빨간"), "노랑": ("노랑", "노란"), "초록": ("초록", "녹색")}
# LLM이 쓰는 서술 필드. 숫자 근거 확인(_grounding_text)에서는 이 필드들을 빼고 대조한다.
_LLM_TEXT_FIELDS = ("differentiation_point", "overall_summary", "one_liner")
_ACTION_LABELS = {
    "record": "단순 기록",
    "visualize_trend": "추이 그래프",
    "predict": "수치 예측",
    "diagnose": "진단",
    "alert": "위험 알림",
}


# ---------- 골든셋 ----------


@dataclass
class GoldenCase:
    case_id: str
    split: str
    tags: list[str]
    service_name: str
    service_description: str
    health_data_items: list[HealthDataItemInput]
    service_actions: list[str]
    service_type: str | None
    target: str | None
    expected_category_1: str | None
    expected_category_2: str | None
    expected_gate_verdict: str | None
    expected_final_regulatory_grade: str | None
    expected_risky_phrases: list[str]


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def _blank_to_none(value: str | None) -> str | None:
    return (value or "").strip() or None


def _parse_items(case_id: str, value: str) -> list[HealthDataItemInput]:
    """`이름|수집방법|item_code`를 `;`로 이은 칸 → HealthDataItemInput 목록 (골든셋_라벨링_가이드.md §4)."""
    items = []
    for part in _split(value):
        name, source, item_code = (part.split("|") + ["", ""])[:3]
        source = source.strip() or "user_input"
        if source not in SOURCE_TO_ACQUIRE_METHOD:
            raise ValueError(f"{case_id}: 수집방법 '{source}'은 {sorted(SOURCE_TO_ACQUIRE_METHOD)} 중 하나여야 합니다.")
        items.append(
            HealthDataItemInput(name=name.strip(), data_type="numeric", source=source, item_code=item_code.strip() or None)
        )
    if not items:
        raise ValueError(f"{case_id}: health_data_items가 비어 있습니다 — 판정 API가 409를 돌려줍니다.")
    return items


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_cases(path: Path, split: str | None = None, limit: int | None = None) -> list[GoldenCase]:
    cases = []
    for row in read_rows(path):
        if split and (row.get("split") or "").strip() != split:
            continue
        case_id = row["case_id"].strip()
        verdict = _blank_to_none(row.get("expected_gate_verdict"))
        if verdict and verdict not in VERDICTS:
            raise ValueError(f"{case_id}: expected_gate_verdict '{verdict}'은 {VERDICTS} 중 하나여야 합니다.")
        cases.append(
            GoldenCase(
                case_id=case_id,
                split=(row.get("split") or "").strip(),
                tags=_split(row.get("tags")),
                service_name=row["service_name"].strip(),
                service_description=row["service_description"].strip(),
                health_data_items=_parse_items(case_id, row.get("health_data_items", "")),
                service_actions=_split(row.get("service_actions")),
                service_type=_blank_to_none(row.get("service_type")),
                target=_blank_to_none(row.get("target")),
                expected_category_1=_blank_to_none(row.get("expected_category_1")),
                expected_category_2=_blank_to_none(row.get("expected_category_2")),
                expected_gate_verdict=verdict,
                expected_final_regulatory_grade=_blank_to_none(row.get("expected_final_regulatory_grade")),
                expected_risky_phrases=_split(row.get("expected_risky_phrases")),
            )
        )
    return cases[:limit] if limit else cases


# ---------- 공통 지표 ----------


def consistency(values: list) -> dict:
    """같은 입력 N회 결과가 몇 가지로 갈렸는지. 비교는 JSON 정규화 문자열로 한다(목록 순서는 유지)."""
    keys = [json.dumps(value, sort_keys=True, ensure_ascii=False) for value in values]
    counts = Counter(keys)
    modal_key, modal_count = counts.most_common(1)[0]
    return {
        "consistent": len(counts) == 1,
        "distinct": len(counts),
        "modal_share": round(modal_count / len(keys), 3),
        "modal": json.loads(modal_key),
    }


def _compact(text: str) -> str:
    return _WHITESPACE.sub("", text)


def bigram_jaccard(a: str, b: str) -> float:
    """문자 2-gram Jaccard — 같은 내용을 얼마나 같은 말로 썼는지 보는 어휘 수준 유사도(0~1)."""
    grams_a = {_compact(a)[i : i + 2] for i in range(max(len(_compact(a)) - 1, 1))}
    grams_b = {_compact(b)[i : i + 2] for i in range(max(len(_compact(b)) - 1, 1))}
    return len(grams_a & grams_b) / len(grams_a | grams_b) if grams_a | grams_b else 1.0


def set_jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def mean_pairwise(items: list, similarity) -> float:
    pairs = list(itertools.combinations(items, 2))
    if not pairs:
        return 1.0
    return sum(similarity(x, y) for x, y in pairs) / len(pairs)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def phrase_detected(phrase: str, risky_texts: list[str]) -> bool:
    """기대한 위험 구절이 교정 후보의 risky_text와 겹치는지(어느 한쪽이 다른 쪽을 포함)."""
    target = _compact(phrase)
    return any(target in _compact(text) or _compact(text) in target for text in risky_texts if text)


def signal_color_mismatch(text: str, actual_signal: str) -> list[str]:
    mentioned = {color for color, words in _SIGNAL_WORDS.items() if any(word in text for word in words)}
    return sorted(mentioned - {actual_signal})


def ungrounded_numbers(text: str, grounding: str) -> list[str]:
    """입력·판정 결과 어디에도 없는 숫자 — 지어낸 수치일 수 있어 사람이 검토할 후보로만 쓴다
    ("3가지 측면"처럼 무해한 숫자도 걸리므로 위반으로 단정하지 않는다)."""
    grounded = set(_NUMBER.findall(grounding))
    return sorted({number for number in _NUMBER.findall(text.replace(",", "")) if number not in grounded})


def gate_validity(pairs: list[tuple[str, str]]) -> dict:
    """(정답, 예측) 목록 → 혼동행렬·정확도·FAIL 재현율. FAIL→PASS는 치명 오류로 따로 센다."""
    confusion = {expected: {predicted: 0 for predicted in VERDICTS} for expected in VERDICTS}
    for expected, predicted in pairs:
        if predicted in VERDICTS:
            confusion[expected][predicted] += 1
    n = len(pairs)
    expected_fail = sum(confusion["FAIL"].values())
    predicted_fail = sum(row["FAIL"] for row in confusion.values())
    return {
        "n": n,
        "confusion": confusion,
        "accuracy": round(sum(confusion[v][v] for v in VERDICTS) / n, 3) if n else None,
        "fail_recall": round(confusion["FAIL"]["FAIL"] / expected_fail, 3) if expected_fail else None,
        "fail_precision": round(confusion["FAIL"]["FAIL"] / predicted_fail, 3) if predicted_fail else None,
        "critical_errors": confusion["FAIL"]["PASS"],
        "conditional_rate": round(sum(row["CONDITIONAL"] for row in confusion.values()) / n, 3) if n else None,
    }


# ---------- 평가자 일치도 ----------


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[k] * count_b[k] for k in set(a) | set(b)) / (n * n)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def fleiss_kappa(ratings: list[list[str]]) -> float | None:
    """ratings[i] = i번째 항목에 평가자들이 단 라벨 목록(항목마다 평가자 수가 같아야 한다)."""
    if not ratings or len(ratings[0]) < 2:
        return None
    raters = len(ratings[0])
    categories = sorted({label for row in ratings for label in row})
    agreement = [
        (sum(row.count(c) ** 2 for c in categories) - raters) / (raters * (raters - 1)) for row in ratings
    ]
    p_bar = sum(agreement) / len(ratings)
    shares = [sum(row.count(c) for row in ratings) / (len(ratings) * raters) for c in categories]
    p_e = sum(share**2 for share in shares)
    return None if p_e == 1 else (p_bar - p_e) / (1 - p_e)


def _cell(row: dict[str, str], column: str) -> str:
    # 행이 헤더보다 짧으면 DictReader가 None을 채운다 — 빈 칸과 똑같이 취급한다.
    return (row.get(column) or "").strip()


def kappa_report(rows: list[dict[str, str]]) -> dict:
    rater_columns = sorted(column for column in (rows[0] if rows else {}) if column and _RATER_COLUMN.fullmatch(column))
    pairs = {}
    for first, second in itertools.combinations(rater_columns, 2):
        labeled = [(_cell(row, first), _cell(row, second)) for row in rows if _cell(row, first) and _cell(row, second)]
        kappa = cohen_kappa([x for x, _ in labeled], [y for _, y in labeled])
        pairs[f"{first} vs {second}"] = {"n": len(labeled), "kappa": None if kappa is None else round(kappa, 3)}
    complete = [[_cell(row, c) for c in rater_columns] for row in rows if all(_cell(row, c) for c in rater_columns)]
    fleiss = fleiss_kappa(complete)
    to_consensus = {}
    for column in rater_columns:
        labeled = [
            (_cell(row, column), _cell(row, "expected_gate_verdict"))
            for row in rows
            if _cell(row, column) and _cell(row, "expected_gate_verdict")
        ]
        to_consensus[column] = round(sum(x == y for x, y in labeled) / len(labeled), 3) if labeled else None
    return {
        "rater_columns": rater_columns,
        "pairwise_cohen": pairs,
        "fleiss": {"n": len(complete), "kappa": None if fleiss is None else round(fleiss, 3)},
        "agreement_with_consensus": to_consensus,
    }


# ---------- run: 반복 측정 ----------


def layer_a(result: dict) -> dict:
    gate, regulatory = result["gate"], result["regulatory_risk"]
    data, market, bm = result["data_feasibility"], result["market_feasibility"], result["business_model"]
    return {
        "gate.verdict": gate["verdict"],
        "gate.data_type": gate["data_type"],
        "gate.function_type": gate["function_type"],
        "gate.hardcheck_fired": gate["hardcheck_fired"],
        "regulatory.scores": [
            regulatory["regulatory_score"],
            regulatory["privacy_score"],
            regulatory["advertising_score"],
        ],
        "regulatory.final_grade": regulatory["final_regulatory_grade"],
        "data_feasibility.risk_level": data["risk_level"] if data else None,
        "market.realism_grade": market["market_realism_grade"] if market else None,
        # match_level은 응답 직렬화에서 빠지는 필드(Field(exclude=True))라 덤프에는 없다 —
        # 1:1로 대응하는 공개 필드 match_scope_description으로 대신 비교한다.
        "business_model.match_level": bm.get("match_level", bm.get("match_scope_description")) if bm else None,
        "overall_signal": result["overall_signal"],
    }


def _basis_key(legal_basis: dict | None) -> list[str] | None:
    return [legal_basis["document_id"], legal_basis["article"]] if legal_basis else None


def layer_b(result: dict) -> dict:
    candidates = result["correction_candidates"]["candidates"]
    bm = result["business_model"]
    return {
        "gate.legal_basis": _basis_key(result["gate"].get("legal_basis")),
        "regulatory.matched_rules": sorted(_basis_key(m["legal_basis"]) for m in result["regulatory_risk"]["matched_rules"]),
        "correction.rule_candidates": sorted(
            [c["risky_text"], c["safe_text"]] for c in candidates if c["match_source"] == "rule"
        ),
        "next_actions": [a["action_text"] for a in result["next_actions"]],
        "overall_actions": [a["action_text"] for a in result["overall_actions"]],
        "business_model.patterns": [r["bm_pattern"] for r in bm["recommendations"]] if bm else None,
        "section_links": sorted(link["message"] for link in result["section_links"]),
    }


def llm_texts(result: dict) -> dict[str, str | None]:
    strengths = " | ".join(f"{s['bm_pattern']}: {s['strength']}" for s in result["bm_card_summaries"] if s.get("strength"))
    return {
        "differentiation_point": result["differentiation_point"],
        "bm_strengths": strengths or None,
        "overall_summary": result["overall_summary"],
        "one_liner": result["one_liner"],
    }


def _grounding_text(result: dict, description: str) -> str:
    """LLM 서술을 뺀 판정 결과 + 사용자 입력 — 서술에 나온 숫자가 여기 없으면 지어낸 수치 후보다."""
    stripped = {key: value for key, value in result.items() if key not in (*_LLM_TEXT_FIELDS, "bm_card_summaries")}
    stripped["bm_card_summaries"] = [
        {key: value for key, value in summary.items() if key != "strength"} for summary in result["bm_card_summaries"]
    ]
    return json.dumps(stripped, ensure_ascii=False) + description


def _text_metrics(texts: list[str | None]) -> dict:
    present = [text for text in texts if text]
    metrics: dict = {"available_share": round(len(present) / len(texts), 3) if texts else 0.0}
    if present:
        metrics["exact_match_share"] = round(Counter(present).most_common(1)[0][1] / len(present), 3)
        metrics["lexical_similarity"] = round(mean_pairwise(present, bigram_jaccard), 3)
    return metrics


def _classifier_available() -> bool:
    try:
        predict_categories("걸음수를 기록하는 앱")
    except CategoryModelUnavailable as error:
        print(f"⚠️  분류 모델을 쓸 수 없어 골든셋의 expected_category를 세션 입력으로 씁니다: {error}")
        return False
    return True


async def _create_session(case: GoldenCase, categories: tuple[str | None, str | None]) -> str:
    response = await create_analysis_session(
        CreateAnalysisSessionRequest(
            service_name=case.service_name,
            service_description=case.service_description,
            service_type=case.service_type,
            target=case.target,
            category_1=categories[0],
            category_2=categories[1],
        )
    )
    if isinstance(response, JSONResponse):
        raise RuntimeError(f"{case.case_id}: 세션 생성 실패 — {response.body.decode()}")
    session_id = response.result.session_id
    health = await create_health_data(
        session_id,
        HealthDataUpsertRequest(health_data_items=case.health_data_items, service_actions=case.service_actions),
    )
    if isinstance(health, JSONResponse):
        await _delete_session(session_id)
        raise RuntimeError(f"{case.case_id}: 데이터 항목 등록 실패 — {health.body.decode()}")
    return session_id


async def _delete_session(session_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisSession).where(AnalysisSession.session_id == session_id))
        await session.commit()


async def _unsafe_corrections(evaluations: list[dict], rule_version_ids: list) -> dict:
    """교정문(safe_text)을 판정엔진의 키워드 매칭에 다시 넣었을 때 위험 키워드가 남는지 — 교정이
    실제로 위험을 낮췄는지 보는 자동 검증(문서 "타당성" 절의 교정문 지표)."""
    candidates = {
        (c["risky_text"], c["safe_text"], c["match_source"])
        for result in evaluations
        for c in result["correction_candidates"]["candidates"]
    }
    unsafe = []
    for risky_text, safe_text, source in sorted(candidates):
        keywords = await _match_gate_keywords(safe_text, rule_version_ids)
        if keywords:
            unsafe.append(
                {"risky_text": risky_text, "safe_text": safe_text, "match_source": source, "keywords": [k.keyword for k in keywords]}
            )
    return {"total": len(candidates), "unsafe": unsafe}


async def run_case(
    case: GoldenCase, runs: int, use_classifier: bool, keep_session: bool, rule_version_ids: list, embed_client=None
) -> dict:
    if use_classifier:
        predictions = [predict_categories(case.service_description) for _ in range(runs)]
        category_runs = [[p[0][0], p[1][0]] for p in predictions]
        categories, category_source = tuple(category_runs[0]), "classifier"
    else:
        category_runs, category_source = [], "expected"
        categories = (case.expected_category_1, case.expected_category_2)

    session_id = await _create_session(case, categories)
    evaluations, errors = [], []
    try:
        for _ in range(runs):
            response = await evaluate_analysis(EvaluateRequest(session_id=session_id))
            if isinstance(response, JSONResponse):
                errors.append(json.loads(response.body))
            else:
                evaluations.append(response.result.model_dump(mode="json"))
        corrections = await _unsafe_corrections(evaluations, rule_version_ids) if evaluations else {"total": 0, "unsafe": []}
    finally:
        if not keep_session:
            await _delete_session(session_id)

    record: dict = {
        "case_id": case.case_id,
        "split": case.split,
        "tags": case.tags,
        "category_source": category_source,
        "runs_ok": len(evaluations),
        "errors": errors,
        "corrections": corrections,
    }
    if not evaluations:
        return record

    record["layers"] = {
        "A": {key: consistency([layer_a(r)[key] for r in evaluations]) for key in layer_a(evaluations[0])},
        "B": {key: consistency([layer_b(r)[key] for r in evaluations]) for key in layer_b(evaluations[0])},
        "C": {"category": consistency(category_runs)} if category_runs else {},
        "D": {},
    }
    texts_by_field = {field: [llm_texts(r)[field] for r in evaluations] for field in llm_texts(evaluations[0])}
    for field, texts in texts_by_field.items():
        metrics = _text_metrics(texts)
        present = [text for text in texts if text]
        if embed_client is not None and len(present) > 1:
            vectors = await embed_client.embed_texts(present)
            metrics["embedding_similarity"] = round(mean_pairwise(vectors, cosine), 3)
        record["layers"]["D"][field] = metrics
    llm_sets = [
        {c["risky_text"] for c in r["correction_candidates"]["candidates"] if c["match_source"] == "llm"} for r in evaluations
    ]
    record["layers"]["D"]["correction.llm_candidates"] = {
        "runs_with_llm_candidates": sum(bool(s) for s in llm_sets),
        "set_jaccard": round(mean_pairwise(llm_sets, set_jaccard), 3),
    }

    signal = record["layers"]["A"]["overall_signal"]["modal"]
    record["invariants"] = {
        "signal_color_mismatch": [
            {"field": field, "run": index, "colors": colors}
            for field in ("overall_summary", "one_liner")
            for index, text in enumerate(texts_by_field[field])
            if text and (colors := signal_color_mismatch(text, signal))
        ],
        "ungrounded_numbers": [
            {"field": field, "run": index, "numbers": numbers}
            for index, result in enumerate(evaluations)
            for field, text in llm_texts(result).items()
            if text and (numbers := ungrounded_numbers(text, _grounding_text(result, case.service_description)))
        ],
    }

    validity: dict = {}
    if case.expected_gate_verdict:
        validity["gate"] = [case.expected_gate_verdict, record["layers"]["A"]["gate.verdict"]["modal"]]
    if case.expected_final_regulatory_grade:
        validity["final_grade"] = [case.expected_final_regulatory_grade, record["layers"]["A"]["regulatory.final_grade"]["modal"]]
    if case.expected_risky_phrases:
        recalls = {"rule": [], "all": []}
        for result in evaluations:
            candidates = result["correction_candidates"]["candidates"]
            for scope in recalls:
                texts = [c["risky_text"] for c in candidates if scope == "all" or c["match_source"] == "rule"]
                hits = sum(phrase_detected(phrase, texts) for phrase in case.expected_risky_phrases)
                recalls[scope].append(hits / len(case.expected_risky_phrases))
        validity["risky_phrase_recall"] = {scope: round(sum(v) / len(v), 3) for scope, v in recalls.items()}
    if category_runs and case.expected_category_1:
        modal_category = record["layers"]["C"]["category"]["modal"]
        validity["category"] = {
            "category_1": [case.expected_category_1, modal_category[0]],
            "category_2": [case.expected_category_2, modal_category[1]] if case.expected_category_2 else None,
        }
    record["validity"] = validity
    return record


def summarize_run(records: list[dict]) -> dict:
    evaluated = [r for r in records if r.get("layers")]
    summary: dict = {"cases": len(records), "evaluated_cases": len(evaluated), "reproducibility": {}, "validity": {}}

    for layer in ("A", "B", "C"):
        fields = sorted({field for r in evaluated for field in r["layers"][layer]})
        layer_cases = [r for r in evaluated if r["layers"][layer]]
        summary["reproducibility"][layer] = {
            "all_fields_consistent_share": round(
                sum(all(v["consistent"] for v in r["layers"][layer].values()) for r in layer_cases) / len(layer_cases), 3
            )
            if layer_cases
            else None,
            "fields": {
                field: round(
                    sum(r["layers"][layer][field]["consistent"] for r in layer_cases if field in r["layers"][layer])
                    / sum(field in r["layers"][layer] for r in layer_cases),
                    3,
                )
                for field in fields
            },
        }

    d_fields = sorted({field for r in evaluated for field in r["layers"]["D"]})
    summary["reproducibility"]["D"] = {
        field: {
            metric: round(sum(values) / len(values), 3)
            for metric in ("available_share", "exact_match_share", "lexical_similarity", "embedding_similarity", "set_jaccard")
            if (values := [r["layers"]["D"][field][metric] for r in evaluated if metric in r["layers"]["D"].get(field, {})])
        }
        for field in d_fields
    }
    summary["invariants"] = {
        "signal_color_mismatch_runs": sum(len(r["invariants"]["signal_color_mismatch"]) for r in evaluated),
        "ungrounded_number_runs": sum(len(r["invariants"]["ungrounded_numbers"]) for r in evaluated),
        "total_runs": sum(r["runs_ok"] for r in evaluated),
        "corrections_total": sum(r["corrections"]["total"] for r in evaluated),
        "corrections_unsafe": sum(len(r["corrections"]["unsafe"]) for r in evaluated),
    }

    gate_pairs = [tuple(r["validity"]["gate"]) for r in evaluated if "gate" in r["validity"]]
    if gate_pairs:
        summary["validity"]["gate"] = gate_validity(gate_pairs)
        summary["validity"]["gate"]["critical_error_cases"] = [
            r["case_id"] for r in evaluated if r["validity"].get("gate") == ["FAIL", "PASS"]
        ]
        summary["validity"]["gate"]["wrong_cases"] = [
            r["case_id"] for r in evaluated if "gate" in r["validity"] and r["validity"]["gate"][0] != r["validity"]["gate"][1]
        ]
    grade_pairs = [r["validity"]["final_grade"] for r in evaluated if "final_grade" in r["validity"]]
    if grade_pairs:
        summary["validity"]["final_grade_accuracy"] = {
            "n": len(grade_pairs),
            "accuracy": round(sum(e == p for e, p in grade_pairs) / len(grade_pairs), 3),
        }
    recall_cases = [r["validity"]["risky_phrase_recall"] for r in evaluated if "risky_phrase_recall" in r["validity"]]
    if recall_cases:
        summary["validity"]["risky_phrase_recall"] = {
            "n": len(recall_cases),
            "rule_only": round(sum(c["rule"] for c in recall_cases) / len(recall_cases), 3),
            "rule_plus_llm": round(sum(c["all"] for c in recall_cases) / len(recall_cases), 3),
        }
    category_cases = [r["validity"]["category"] for r in evaluated if "category" in r["validity"]]
    if category_cases:
        summary["validity"]["category_1_accuracy"] = {
            "n": len(category_cases),
            "accuracy": round(sum(c["category_1"][0] == c["category_1"][1] for c in category_cases) / len(category_cases), 3),
        }
    return summary


# ---------- baseline: LLM 단독 판정 ----------

# 라벨 정의는 골든셋_라벨링_가이드.md §6과 같은 문장 — 평가자와 LLM이 같은 정의로 판정해야 공정하다.
_BASELINE_SYSTEM_PROMPT = """당신은 한국 식품의약품안전처 기준으로 디지털 헬스케어 서비스가 의료기기에 해당하는지
판단하는 전문가입니다. 주어진 서비스를 아래 셋 중 하나로 판정하고 이유를 한두 문장으로 쓰세요.
- PASS: 의료기기 해당 가능성이 낮다(일상적 건강관리·저위해도)
- CONDITIONAL: 조건에 따라 갈린다 — 추가 검토가 필요하다
- FAIL: 의료기기 해당 가능성이 높다(질병 진단·예측 목적, 고위해도)"""

_BASELINE_SCHEMA = {
    "name": "gate_verdict",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)}, "reason": {"type": "string"}},
        "required": ["verdict", "reason"],
        "additionalProperties": False,
    },
}


def baseline_user_prompt(case: GoldenCase) -> str:
    items = ", ".join(f"{item.name}({SOURCE_TO_ACQUIRE_METHOD[item.source]})" for item in case.health_data_items)
    actions = ", ".join(_ACTION_LABELS.get(action, action) for action in case.service_actions) or "명시 안 됨"
    return f"서비스 설명: {case.service_description}\n수집 데이터: {items}\n제공 기능: {actions}"


async def _ask_baseline(client, case: GoldenCase, temperature: float) -> dict:
    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": _BASELINE_SYSTEM_PROMPT},
                {"role": "user", "content": baseline_user_prompt(case)},
            ],
            response_format={"type": "json_schema", "json_schema": _BASELINE_SCHEMA},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as error:  # 레이트리밋 등 — 한 번 실패가 전체 측정을 죽이지 않게 기록만 한다
        return {"verdict": "ERROR", "reason": str(error)}


# ---------- bm-loo ----------


def _is_domestic(competitor) -> bool:
    return (competitor.country or "").strip() == "한국"


def top_patterns(competitors: list, k: int = 2) -> list[str]:
    """bm_mapping과 같은 순서 — 국내 경쟁사 수(frequency_score) → 전체 수 → 이름순(동점 고정)."""
    domestic = Counter(_normalize_bm_pattern(c.bm_pattern) for c in competitors if _is_domestic(c))
    overall = Counter(_normalize_bm_pattern(c.bm_pattern) for c in competitors)
    return sorted(overall, key=lambda p: (-domestic[p], -overall[p], p))[:k]


def recommend_bm(pool: list, held_out) -> tuple[str, list[str]]:
    """market_lookup.relaxation_stages와 같은 4단계 완화 — 운영 bm_mapping은 시드 테이블이라 여기서
    경쟁사로부터 다시 집계한다(빈도 기반 추천 "방식"의 타당성을 재는 것)."""
    stages = []
    if held_out.target and held_out.service_type:
        stages.append(("exact_match", ("category_1", "category_2", "target", "service_type")))
    if held_out.target:
        stages.append(("relaxed_service_type", ("category_1", "category_2", "target")))
    stages.append(("relaxed_category_only", ("category_1", "category_2")))
    for match_level, keys in stages:
        matched = [c for c in pool if all(getattr(c, key) == getattr(held_out, key) for key in keys)]
        if matched:
            return match_level, top_patterns(matched)
    return "insufficient_data", []


# ---------- 출력 ----------


def _git_state() -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
        return {"git_commit": commit or None, "git_dirty": dirty}
    except OSError:
        return {"git_commit": None, "git_dirty": None}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _write_outputs(out_dir: Path, name: str, payload: dict, markdown: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path, md_path = out_dir / f"{name}_{stamp}.json", out_dir / f"{name}_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    print(f"\n저장: {json_path}\n      {md_path}")


def _meta_lines(meta: dict) -> list[str]:
    return ["| 항목 | 값 |", "| --- | --- |", *[f"| {key} | {value} |" for key, value in meta.items()], ""]


def run_markdown(meta: dict, summary: dict) -> str:
    lines = ["# PREP 재현성·타당성 측정 결과", "", "## 실행 조건", "", *_meta_lines(meta)]
    lines += ["## 재현성 — 같은 입력 반복 시 결과가 모두 같은 케이스 비율", "", "| 층 | 모든 필드 일치 | 필드별 |", "| --- | --- | --- |"]
    for layer in ("A", "B", "C"):
        data = summary["reproducibility"][layer]
        fields = ", ".join(f"{field} {_pct(value)}" for field, value in data["fields"].items()) or "—"
        lines.append(f"| {layer} | {_pct(data['all_fields_consistent_share'])} | {fields} |")
    lines += ["", "## 재현성 — LLM 서술(D층)", "", "| 필드 | 생성 성공 | 완전 동일 | 어휘 유사도 | 임베딩 유사도 | 후보 집합 Jaccard |", "| --- | --- | --- | --- | --- | --- |"]
    for field, data in summary["reproducibility"]["D"].items():
        lines.append(
            f"| {field} | {_pct(data.get('available_share'))} | {_pct(data.get('exact_match_share'))} | "
            f"{data.get('lexical_similarity', '—')} | {data.get('embedding_similarity', '—')} | {data.get('set_jaccard', '—')} |"
        )
    inv = summary["invariants"]
    lines += [
        "",
        "## 불변식",
        "",
        f"- 신호등 색과 반대되는 서술: {inv['signal_color_mismatch_runs']}건 / 전체 {inv['total_runs']}회",
        f"- 입력·판정에 없는 숫자가 나온 서술(사람 검토 후보): {inv['ungrounded_number_runs']}건",
        f"- 교정문에 위험 키워드가 남은 후보: {inv['corrections_unsafe']} / {inv['corrections_total']}",
        "",
    ]
    validity = summary["validity"]
    if "gate" in validity:
        gate = validity["gate"]
        lines += [
            "## 타당성 — GATE (행: 정답, 열: PREP 판정)",
            "",
            "| 정답 / 예측 | PASS | CONDITIONAL | FAIL |",
            "| --- | --- | --- | --- |",
            *[f"| {e} | " + " | ".join(str(gate["confusion"][e][p]) for p in VERDICTS) + " |" for e in VERDICTS],
            "",
            f"- n={gate['n']}, 정확도 {_pct(gate['accuracy'])}, FAIL 재현율 {_pct(gate['fail_recall'])}, "
            f"FAIL 정밀도 {_pct(gate['fail_precision'])}, CONDITIONAL 비율 {_pct(gate['conditional_rate'])}",
            f"- 치명 오류(정답 FAIL → PASS): {gate['critical_errors']}건 {gate['critical_error_cases']}",
            f"- 틀린 케이스: {gate['wrong_cases']}",
            "",
        ]
    if "final_grade_accuracy" in validity:
        lines.append(f"- 최종 규제위험도 등급 일치율: {_pct(validity['final_grade_accuracy']['accuracy'])} (n={validity['final_grade_accuracy']['n']})")
    if "risky_phrase_recall" in validity:
        recall = validity["risky_phrase_recall"]
        lines.append(f"- 위험 표현 탐지 재현율: 규칙만 {_pct(recall['rule_only'])} → 규칙+LLM① {_pct(recall['rule_plus_llm'])} (n={recall['n']})")
    if "category_1_accuracy" in validity:
        lines.append(f"- 카테고리(category_1) 정확도: {_pct(validity['category_1_accuracy']['accuracy'])} (n={validity['category_1_accuracy']['n']})")
    return "\n".join(lines) + "\n"


async def command_run(args: argparse.Namespace) -> None:
    # 반복 측정 중에는 LLM 응답 캐시를 끈다 — 켜두면 두 번째 호출부터 캐시 히트라 "10/10 일치"가 저절로 나온다.
    settings.llm_response_cache_enabled = args.keep_llm_cache
    cases = load_cases(Path(args.golden), split=args.split, limit=args.limit)
    use_classifier = not args.no_classifier and _classifier_available()
    rule_version_ids = await resolve_active_rule_version_ids()
    embed_client = None
    if args.embed:
        from app.rag.embeddings import EmbeddingClient

        embed_client = EmbeddingClient()
    meta = {
        "command": "run",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        **_git_state(),
        "openai_model": settings.openai_model,
        "llm_response_cache_enabled": settings.llm_response_cache_enabled,
        "active_rule_version_ids": ", ".join(str(v) for v in rule_version_ids),
        "golden": args.golden,
        "split": args.split or "(전체)",
        "runs_per_case": args.runs,
        "category_source": "classifier" if use_classifier else "expected_category",
    }
    print(f"골든셋 {len(cases)}건 × {args.runs}회 — LLM 응답 캐시 {'켜짐' if args.keep_llm_cache else '꺼짐'}")

    records = []
    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case.case_id} {case.service_name}")
        try:
            record = await run_case(case, args.runs, use_classifier, args.keep_sessions, rule_version_ids, embed_client)
        except Exception as error:  # 한 케이스 실패가 전체 측정을 멈추지 않게 기록하고 넘어간다
            print(f"   ❌ {error}")
            record = {"case_id": case.case_id, "split": case.split, "tags": case.tags, "runs_ok": 0, "errors": [str(error)]}
        if record.get("layers"):
            unstable = [f"{layer}:{field}" for layer in "ABC" for field, v in record["layers"][layer].items() if not v["consistent"]]
            print(f"   {record['runs_ok']}/{args.runs}회 성공, 흔들린 판정·근거 필드: {unstable or '없음'}")
        records.append(record)

    summary = summarize_run(records)
    _write_outputs(Path(args.out), "run", {"meta": meta, "summary": summary, "cases": records}, run_markdown(meta, summary))


async def command_baseline(args: argparse.Namespace) -> None:
    from openai import AsyncOpenAI

    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY가 필요합니다.")
    cases = load_cases(Path(args.golden), split=args.split, limit=args.limit)
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=30.0)
    records = []
    for index, case in enumerate(cases, 1):
        answers = await asyncio.gather(*(_ask_baseline(client, case, args.temperature) for _ in range(args.runs)))
        verdicts = [answer["verdict"] for answer in answers]
        record = {"case_id": case.case_id, "expected": case.expected_gate_verdict, **consistency(verdicts), "answers": answers}
        print(f"[{index}/{len(cases)}] {case.case_id} {Counter(verdicts).most_common()} (정답 {case.expected_gate_verdict})")
        records.append(record)

    labeled = [r for r in records if r["expected"]]
    summary = {
        "cases": len(records),
        "all_runs_identical_share": round(sum(r["consistent"] for r in records) / len(records), 3) if records else None,
        "mean_modal_share": round(sum(r["modal_share"] for r in records) / len(records), 3) if records else None,
        "gate": gate_validity([(r["expected"], r["modal"]) for r in labeled]) if labeled else None,
    }
    meta = {
        "command": "baseline",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        **_git_state(),
        "openai_model": settings.openai_model,
        "temperature": args.temperature,
        "golden": args.golden,
        "split": args.split or "(전체)",
        "runs_per_case": args.runs,
    }
    lines = ["# LLM 단독 판정 베이스라인", "", "## 실행 조건", "", *_meta_lines(meta)]
    prep = None
    if args.compare:
        prep = json.loads(Path(args.compare).read_text(encoding="utf-8"))
    gate = summary["gate"] or {}
    prep_gate = (prep or {}).get("summary", {}).get("validity", {}).get("gate", {})
    prep_a = (prep or {}).get("summary", {}).get("reproducibility", {}).get("A", {}).get("fields", {})
    lines += [
        "## LLM 단독 vs PREP",
        "",
        "| 지표 | LLM 단독 | PREP |",
        "| --- | --- | --- |",
        f"| GATE 정확도 | {_pct(gate.get('accuracy'))} | {_pct(prep_gate.get('accuracy')) if prep else '—'} |",
        f"| FAIL 재현율 | {_pct(gate.get('fail_recall'))} | {_pct(prep_gate.get('fail_recall')) if prep else '—'} |",
        f"| 치명 오류(FAIL→PASS) | {gate.get('critical_errors', '—')} | {prep_gate.get('critical_errors', '—') if prep else '—'} |",
        f"| {args.runs}회 모두 같은 판정 | {_pct(summary['all_runs_identical_share'])} | {_pct(prep_a.get('gate.verdict')) if prep else '—'} |",
        "| 근거 조문 제시 | 없음 | 문서 ID + 조문 + 원문(legal_basis) |",
        "",
    ]
    _write_outputs(Path(args.out), "baseline", {"meta": meta, "summary": summary, "cases": records}, "\n".join(lines) + "\n")


async def command_bm_loo(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as session:
        competitors = (await session.execute(select(Competitor).order_by(Competitor.competitor_id))).scalars().all()
    pool = [c for c in competitors if _normalize_bm_pattern(c.bm_pattern) and c.category_1 and c.category_2]
    records = []
    for held_out in pool:
        others = [c for c in pool if c.competitor_id != held_out.competitor_id]
        match_level, recommended = recommend_bm(others, held_out)
        baseline = top_patterns(others)
        actual = _normalize_bm_pattern(held_out.bm_pattern)
        records.append(
            {
                "competitor_id": held_out.competitor_id,
                "actual": actual,
                "match_level": match_level,
                "recommended": recommended,
                "hit": actual in recommended,
                "baseline": baseline,
                "baseline_hit": actual in baseline,
            }
        )
    n = len(records)
    by_level = Counter(r["match_level"] for r in records)
    summary = {
        "n": n,
        "hit_at_2": round(sum(r["hit"] for r in records) / n, 3) if n else None,
        "baseline_hit_at_2": round(sum(r["baseline_hit"] for r in records) / n, 3) if n else None,
        "by_match_level": {
            level: {"n": count, "hit_at_2": round(sum(r["hit"] for r in records if r["match_level"] == level) / count, 3)}
            for level, count in by_level.items()
        },
    }
    print(f"BM leave-one-out n={n}: PREP 방식 {_pct(summary['hit_at_2'])} vs 최빈 2개 고정 {_pct(summary['baseline_hit_at_2'])}")
    lines = [
        "# BM 추천 leave-one-out",
        "",
        "경쟁사 한 곳씩 빼고, 그 서비스의 조회 키(category_1·2, target, service_type)로 추천한 상위 2개 BM에",
        "실제 BM이 들어가는 비율(hit@2). 운영 bm_mapping은 시드 테이블이라 경쟁사로부터 다시 집계해 계산한다.",
        "",
        "| 방식 | hit@2 |",
        "| --- | --- |",
        f"| PREP (4단계 완화 + 빈도순) | {_pct(summary['hit_at_2'])} |",
        f"| 베이스라인 (전체 최빈 2개 고정) | {_pct(summary['baseline_hit_at_2'])} |",
        "",
        "| 매칭 단계 | n | hit@2 |",
        "| --- | --- | --- |",
        *[f"| {level} | {v['n']} | {_pct(v['hit_at_2'])} |" for level, v in summary["by_match_level"].items()],
        "",
    ]
    _write_outputs(Path(args.out), "bm_loo", {"summary": summary, "cases": records}, "\n".join(lines) + "\n")


def command_kappa(args: argparse.Namespace) -> None:
    rows = [row for row in read_rows(Path(args.golden)) if not args.split or _cell(row, "split") == args.split]
    report = kappa_report(rows)
    if not report["rater_columns"]:
        raise SystemExit("rater_N_gate 열이 없습니다 — 골든셋_라벨링_가이드.md §4 참고.")
    lines = ["# 평가자 일치도", "", "| 비교 | n | κ |", "| --- | --- | --- |"]
    lines += [f"| {pair} (Cohen) | {v['n']} | {v['kappa'] if v['kappa'] is not None else '계산 불가'} |" for pair, v in report["pairwise_cohen"].items()]
    fleiss = report["fleiss"]
    lines.append(f"| 전체 평가자 (Fleiss) | {fleiss['n']} | {fleiss['kappa'] if fleiss['kappa'] is not None else '계산 불가'} |")
    lines += ["", "합의 라벨(expected_gate_verdict)과의 일치율", "", "| 평가자 | 일치율 |", "| --- | --- |"]
    lines += [f"| {column} | {_pct(value)} |" for column, value in report["agreement_with_consensus"].items()]
    lines += ["", "해석(Landis & Koch, 1977): 0.41~0.60 보통 / 0.61~0.80 상당한 일치 / 0.81 이상 거의 완전한 일치", ""]
    print("\n".join(lines))
    _write_outputs(Path(args.out), "kappa", report, "\n".join(lines) + "\n")


async def _run_async(handler, args: argparse.Namespace) -> None:
    try:
        await handler(args)
    finally:
        await redis_client.aclose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="PREP 신뢰성(재현성)·타당성 측정")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub, needs_golden: bool = True) -> None:
        if needs_golden:
            sub.add_argument("--golden", required=True, help="골든셋 CSV 경로 (담당자별 파일, 예: data/eval/golden_set_lmg.csv)")
            sub.add_argument("--split", help="이 split만 사용 (예: test)")
        sub.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="결과 저장 폴더")

    run_parser = subparsers.add_parser("run", help="반복 측정(재현성) + 정답 대비 타당성")
    add_common(run_parser)
    run_parser.add_argument("--runs", type=int, default=10, help="같은 입력 반복 횟수 (기본 10)")
    run_parser.add_argument("--limit", type=int, help="앞에서 N건만")
    run_parser.add_argument("--embed", action="store_true", help="LLM 서술의 임베딩 유사도도 계산 (OpenAI 임베딩 호출)")
    run_parser.add_argument("--no-classifier", action="store_true", help="분류 모델 대신 expected_category를 입력으로 사용")
    run_parser.add_argument("--keep-llm-cache", action="store_true", help="LLM 응답 캐시를 켠 채로 측정 (기본은 끔)")
    run_parser.add_argument("--keep-sessions", action="store_true", help="측정에 쓴 분석 세션을 지우지 않음")

    kappa_parser = subparsers.add_parser("kappa", help="평가자 간 일치도")
    add_common(kappa_parser)

    baseline_parser = subparsers.add_parser("baseline", help="LLM 단독 판정 반복 측정")
    add_common(baseline_parser)
    baseline_parser.add_argument("--runs", type=int, default=10)
    baseline_parser.add_argument("--limit", type=int)
    baseline_parser.add_argument("--temperature", type=float, default=1.0, help="기본 1.0 (일반적인 챗봇 사용 조건)")
    baseline_parser.add_argument("--compare", help="run 결과 JSON — 주면 LLM 단독 vs PREP 비교 표를 만든다")

    loo_parser = subparsers.add_parser("bm-loo", help="BM 추천 leave-one-out")
    add_common(loo_parser, needs_golden=False)

    args = parser.parse_args()
    if args.command == "kappa":
        command_kappa(args)
        return
    handlers = {"run": command_run, "baseline": command_baseline, "bm-loo": command_bm_loo}
    asyncio.run(_run_async(handlers[args.command], args))


if __name__ == "__main__":
    main()
