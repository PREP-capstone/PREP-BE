"""STEP 1 카테고리 분류 모델(klue/roberta-base, category_1 8종 + category_2 4종
동시 분류) 추론. 2026-08-23 2축 모델(`best_healthcare_model_2line`)로 교체 —
이전 단일축(category_1 전용, klue/roberta-large) 체크포인트는 대체됐다.

체크포인트는 `settings.category_model_dir`에서 로드한다 — 바이너리라 git에
커밋하지 않고(data/models/는 .gitignore) 로컬/배포 환경마다 별도로 배치해야 한다.

이 체크포인트는 HuggingFace 표준 저장 형식(`config.json` + `save_pretrained`)이
아니라 커스텀 멀티태스크 모듈의 raw state_dict(`model.pt`)다. 인코더(klue/
roberta-base) 위에 category_head(8종)·function_head(4종) 두 개의 선형 헤드가
얹혀 있다 — `_MultiTaskCategoryClassifier`가 그 구조를 그대로 복원한다.

⚠️ 두 가지 함정이 실측으로 확인됐다(2026-08-22~23, 두 체크포인트 모두 동일):

1. **AutoTokenizer 쓰지 말 것** — tokenizer_config.json이 `tokenizer_class:
   RobertaTokenizer`로 잘못 기록돼 있지만 실제 vocab은 BERT WordPiece 형식이다.
   AutoTokenizer로 로드하면 한글이 전부 깨진 토큰으로 분해되어 모든 입력이 같은
   라벨로 수렴한다. BertTokenizerFast로 명시 로드해야 한다.
2. **pooler_output 쓰지 말 것** — HuggingFace 기본 관례(`outputs.pooler_output`)로
   두 헤드에 넣으면 확신도가 거의 균등분포(8종 기준 ~1/8)로 나온다. 학습은
   `last_hidden_state[:, 0]`(CLS 토큰 원본, pooler의 추가 tanh 변환 없이)을
   헤드에 직접 넣는 방식으로 됐다(채린 님 확인, 2026-08-23) — 이렇게 바꾸면
   확신도가 실제로 분별력 있게 나온다.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings

# category_classes 순서 — 채린 님 확인(2026-08-22). 두 체크포인트(단일축 large,
# 2축 base) 모두 같은 순서를 쓴다.
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

# function_type_map({'A':0,'B':1,'C':2,'D':3}) 순서 — 채린 님 확인(2026-08-23).
CATEGORY_2_LABELS: list[str] = [
    "정보제공",
    "데이터기록관리",
    "매칭연결",
    "개입치료",
]

_MAX_TOKEN_LENGTH = 256


class CategoryModelUnavailable(Exception):
    """모델 디렉터리가 없거나 로드에 실패했을 때. data/models/는 git에 없는
    바이너리라 로컬 환경마다 배치 여부가 다를 수 있다 — 앱 기동 자체를 막지 않고
    이 API 호출 시점에만 503으로 알린다."""


def _build_model(model_name: str, num_category: int, num_function: int):
    import torch.nn as nn
    from transformers import AutoConfig, AutoModel

    class _MultiTaskCategoryClassifier(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            config = AutoConfig.from_pretrained(model_name)
            self.encoder = AutoModel.from_config(config)
            self.category_head = nn.Linear(config.hidden_size, num_category)
            self.function_head = nn.Linear(config.hidden_size, num_function)

        def forward(self, **inputs):
            outputs = self.encoder(**inputs)
            cls = outputs.last_hidden_state[:, 0]  # pooler_output 아님 — 위 모듈 docstring 참고
            return self.category_head(cls), self.function_head(cls)

    return _MultiTaskCategoryClassifier()


@lru_cache(maxsize=1)
def _load():
    try:
        import torch
        from transformers import BertTokenizerFast
    except ImportError as error:
        raise CategoryModelUnavailable("torch/transformers가 설치되어 있지 않습니다.") from error

    model_dir = settings.category_model_dir
    try:
        tokenizer = BertTokenizerFast.from_pretrained(model_dir)
        label_config = torch.load(f"{model_dir}/label_config.pt", map_location="cpu", weights_only=False)
        model = _build_model(
            label_config["model_name"],
            label_config["num_category_labels"],
            label_config["num_function_labels"],
        )
        state_dict = torch.load(f"{model_dir}/model.pt", map_location="cpu", weights_only=False)
        model.load_state_dict(state_dict, strict=True)
    except (OSError, FileNotFoundError, KeyError) as error:
        raise CategoryModelUnavailable(f"카테고리 분류 모델을 찾을 수 없습니다: {model_dir}") from error

    model.eval()
    return tokenizer, model


def predict_categories(service_description: str) -> tuple[tuple[str, float], tuple[str, float]]:
    """service_description으로 category_1(8종)·category_2(4종)를 동시에 예측한다.

    반환값은 ((category_1, confidence), (category_2, confidence))이다. 모델을
    못 찾으면 CategoryModelUnavailable을 올린다 — 호출부(app/api/
    category_classifier.py)가 503으로 변환한다.
    """
    tokenizer, model = _load()
    # _load()가 이미 torch를 import해뒀으니(성공했다는 건 sys.modules에 캐시됐다는
    # 뜻) 여기서는 이름만 다시 바인딩한다 — _load() 호출보다 앞에 두면 torch 자체가
    # 없는 환경에서 CategoryModelUnavailable로 변환되기 전에 ModuleNotFoundError가
    # 먼저 터진다.
    import torch

    inputs = tokenizer(
        service_description, return_tensors="pt", truncation=True, max_length=_MAX_TOKEN_LENGTH
    )
    with torch.no_grad():
        category_logits, function_logits = model(**inputs)

    category_probs = torch.softmax(category_logits, dim=-1)[0]
    function_probs = torch.softmax(function_logits, dim=-1)[0]
    category_index = int(torch.argmax(category_probs).item())
    function_index = int(torch.argmax(function_probs).item())

    return (
        (CATEGORY_1_LABELS[category_index], float(category_probs[category_index])),
        (CATEGORY_2_LABELS[function_index], float(function_probs[function_index])),
    )
