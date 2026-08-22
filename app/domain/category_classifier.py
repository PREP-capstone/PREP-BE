"""STEP 1 카테고리 분류 모델(KLUE-RoBERTa large, category_1 8종) 추론.

체크포인트는 `settings.category_model_dir`에서 로드한다 — 1.3GB 바이너리라 git에
커밋하지 않고(data/models/는 .gitignore) 로컬/배포 환경마다 별도로 배치해야 한다.

⚠️ AutoTokenizer를 쓰면 안 된다. 이 체크포인트의 tokenizer_config.json은
`tokenizer_class: RobertaTokenizer`로 잘못 기록돼 있지만, 실제 vocab은 BERT
WordPiece 형식(`##` 연속 토큰, [CLS]/[SEP]/[PAD]/[MASK]/[UNK] 스페셜 토큰)이다.
AutoTokenizer로 로드하면 RobertaTokenizer(byte-level BPE)가 선택되어 한글 입력이
전부 깨진 토큰(예: '´' 반복)으로 분해되고, 그 결과 모든 입력이 같은 라벨로
수렴한다(실측: LABEL_3 고정, confidence ~0.3). BertTokenizerFast로 명시 로드해야
정상 동작한다 — 실제 라벨 대응 정확도로 검증 완료(2026-08-22).
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings

# LABEL_0~7 순서 — 학습 시점 라벨 인덱스와 동일(팀 확인, 2026-08-22).
CATEGORY_1_LABELS: list[str] = [
    "수면",
    "정신건강",
    "운동",
    "식단",
    "만성질환",
    "여성건강",
    "유전자",
    "미용",
]

_MAX_TOKEN_LENGTH = 256


class CategoryModelUnavailable(Exception):
    """모델 디렉터리가 없거나 로드에 실패했을 때. data/models/는 git에 없는
    바이너리라 로컬 환경마다 배치 여부가 다를 수 있다 — 앱 기동 자체를 막지 않고
    이 API 호출 시점에만 503으로 알린다."""


@lru_cache(maxsize=1)
def _load():
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForSequenceClassification, BertTokenizerFast
    except ImportError as error:
        raise CategoryModelUnavailable("torch/transformers가 설치되어 있지 않습니다.") from error

    model_dir = settings.category_model_dir
    try:
        tokenizer = BertTokenizerFast.from_pretrained(model_dir)
        model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    except OSError as error:
        raise CategoryModelUnavailable(f"카테고리 분류 모델을 찾을 수 없습니다: {model_dir}") from error

    model.eval()
    return tokenizer, model


def predict_category_1(service_description: str) -> tuple[str, float]:
    """service_description으로 category_1(8종)을 예측한다.

    반환값은 (라벨, softmax 확률)이다. 모델을 못 찾으면 CategoryModelUnavailable을
    올린다 — 호출부(app/api/category_classifier.py)가 503으로 변환한다.
    """
    import torch

    tokenizer, model = _load()
    inputs = tokenizer(
        service_description, return_tensors="pt", truncation=True, max_length=_MAX_TOKEN_LENGTH
    )
    with torch.no_grad():
        logits = model(**inputs).logits
    probs = torch.softmax(logits, dim=-1)[0]
    top_index = int(torch.argmax(probs).item())
    return CATEGORY_1_LABELS[top_index], float(probs[top_index])
