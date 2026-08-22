"""카테고리 분류(STEP 1) 추론 회귀 테스트. 작업 #7 부속.

실제 체크포인트(data/models/, git 미포함)가 있어야 하는 케이스는
@pytest.mark.ml_model로 표시한다 — 로컬에 모델 파일을 배치하지 않은 환경(CI 포함)에서는
`-m "not ml_model"`로 제외한다.
"""

import pytest

from app.api.category_classifier import CategoryClassifyRequest, predict_category
from app.domain import category_classifier
from app.domain.category_classifier import CATEGORY_1_LABELS, CategoryModelUnavailable, predict_category_1


def test_category_1_labels_are_eight_unique_values_in_training_order() -> None:
    # LABEL_0~7 순서 — 채린 님 확인(2026-08-22). 순서가 바뀌면 모든 예측이
    # 조용히 다른 라벨로 오분류되므로 순서 자체를 회귀로 고정한다.
    assert CATEGORY_1_LABELS == [
        "수면", "정신건강", "운동", "식단", "만성질환", "여성건강", "유전자", "미용",
    ]
    assert len(set(CATEGORY_1_LABELS)) == 8


async def test_predict_returns_503_when_model_directory_missing(monkeypatch) -> None:
    # 모델 로더가 실제 실패 시 CategoryModelUnavailable -> 503으로 변환되는지는
    # 모델 파일 없이도 검증 가능하다 — 존재하지 않는 경로로 강제한다.
    monkeypatch.setattr(category_classifier.settings, "category_model_dir", "data/models/does-not-exist")
    category_classifier._load.cache_clear()
    try:
        response = await predict_category(CategoryClassifyRequest(service_description="테스트"))
        assert response.status_code == 503
    finally:
        category_classifier._load.cache_clear()


@pytest.mark.ml_model
def test_predict_category_1_matches_expected_label_for_clear_examples() -> None:
    # 명확한 예시 문장으로 실제 라벨 매핑이 맞는지 검증(2026-08-22, BertTokenizerFast
    # 명시 로드 이후). AutoTokenizer로 로드하면 전부 같은 라벨로 수렴하는 회귀가
    # 있었으므로, 이 테스트가 그 회귀를 다시 잡아낸다.
    label, confidence = predict_category_1("매일 식단 사진을 찍으면 칼로리를 계산해주는 서비스")
    assert label == "식단"
    assert confidence > 0.5


@pytest.mark.ml_model
async def test_predict_category_endpoint_returns_success(monkeypatch) -> None:
    category_classifier._load.cache_clear()
    response = await predict_category(
        CategoryClassifyRequest(service_description="여성 생리주기를 기록하고 배란일을 예측하는 앱")
    )
    assert response.result.category_1 == "여성건강"
