"""STEP 1 카테고리 분류 모델(klue/roberta-base, category_1 8종 + category_2 4종
동시 분류) 추론. 2026-08-29 ONNX Runtime(int8 양자화) 백엔드로 교체 — 이전
PyTorch(`model.pt`/`label_config.pt`) 직접 로드 방식은 대체됐다.

모델 산출물은 PREP-AI 저장소가 만든다(export_onnx.py + quantize_onnx.py,
`category_classifier_onnx/` 폴더 형태 — model.onnx, tokenizer_config.json,
tokenizer.json, labels.json, model_meta.json). 이 저장소는 그 zip을
`settings.category_model_dir`에 풀어둔 걸 읽기만 한다 — 바이너리라 git에
커밋하지 않는다(`data/models/`는 `.gitignore`, 배포 시 GitHub Actions가
PREP-AI release에서 받아 배치한다, docs/EC2_DOCKER_NGINX_DEPLOYMENT.md §9).

ONNX 그래프의 입력은 `input_ids`/`attention_mask`(둘 다 int64, `token_type_ids`
불필요 — PREP-AI export_onnx.py가 그렇게 트레이싱함), 출력은 `category_logits`
(8종)/`function_logits`(4종) 순서다.

⚠️ 함정 하나가 실측으로 확인됐다(2026-08-22~23) — 지금도 유효:

**AutoTokenizer 쓰지 말 것** — 원본 PyTorch 체크포인트의 tokenizer_config.json이
`tokenizer_class: RobertaTokenizer`로 잘못 기록돼 있었다(실제 vocab은 BERT
WordPiece). PREP-AI release 패키징 시 이 필드를 `BertTokenizerFast`로 정정해서
올리지만, 혹시 정정을 빠뜨린 release가 올라올 경우를 대비해 이 코드에서도
`AutoTokenizer` 대신 `BertTokenizerFast`를 명시적으로 로드한다.

(pooler_output 대신 last_hidden_state[:,0]을 써야 하는 함정은 이제 여기서
신경 쓸 필요가 없다 — ONNX로 export되는 시점에 그 pooling 방식이 그래프 안에
이미 고정돼 있다. PREP-AI의 export_onnx.py/모델_경량화_ONNX_양자화.md 참고.)
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings

# category_classes 순서 — 채린 님 확인(2026-08-22). PREP-AI release의
# labels.json도 이 순서로 만들어졌다(export 시점 기준) — 값 자체는 여기 이
# 상수가 단일 소스이고, labels.json은 저장소 밖에서 참고하는 문서용 사본이다.
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


@lru_cache(maxsize=1)
def _load():
    try:
        import onnxruntime as ort
        from transformers import BertTokenizerFast
    except ImportError as error:
        raise CategoryModelUnavailable("onnxruntime/transformers가 설치되어 있지 않습니다.") from error

    model_dir = settings.category_model_dir
    model_path = f"{model_dir}/{settings.category_model_file}"
    try:
        tokenizer = BertTokenizerFast.from_pretrained(model_dir)
        session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    except Exception as error:
        # onnxruntime의 로드 실패 예외(NoSuchFile/Fail/InvalidGraph/InvalidProtobuf 등,
        # onnxruntime.capi.onnxruntime_pybind11_state)는 공통 베이스 클래스가 없다
        # (전부 Exception 직계 서브클래스 — 실측 확인, 2026-08-29). 좁게 잡으면 파일
        # 손상·버전 불일치 같은 실패가 여기서 새어나가 /category-classifier/predict가
        # 503 대신 500으로 죽는다 — 그래서 이 로드 단계 전체를 넓게 잡는다.
        raise CategoryModelUnavailable(
            f"카테고리 분류 모델을 찾을 수 없습니다(backend={settings.category_model_backend}): {model_dir}"
        ) from error

    return tokenizer, session


def predict_categories(service_description: str) -> tuple[tuple[str, float], tuple[str, float]]:
    """service_description으로 category_1(8종)·category_2(4종)를 동시에 예측한다.

    반환값은 ((category_1, confidence), (category_2, confidence))이다. 모델을
    못 찾으면 CategoryModelUnavailable을 올린다 — 호출부(app/api/
    category_classifier.py)가 503으로 변환한다.
    """
    tokenizer, session = _load()
    import numpy as np

    inputs = tokenizer(
        service_description, return_tensors="np", truncation=True, max_length=_MAX_TOKEN_LENGTH
    )
    category_logits, function_logits = session.run(
        None, {"input_ids": inputs["input_ids"], "attention_mask": inputs["attention_mask"]}
    )

    def _softmax(logits: "np.ndarray") -> "np.ndarray":
        shifted = logits - np.max(logits)
        exp = np.exp(shifted)
        return exp / exp.sum()

    category_probs = _softmax(category_logits[0])
    function_probs = _softmax(function_logits[0])
    category_index = int(np.argmax(category_probs))
    function_index = int(np.argmax(function_probs))

    return (
        (CATEGORY_1_LABELS[category_index], float(category_probs[category_index])),
        (CATEGORY_2_LABELS[function_index], float(function_probs[function_index])),
    )
