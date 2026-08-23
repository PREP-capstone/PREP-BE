"""카테고리 분류(STEP 1, category_1+category_2 동시 분류) 추론 회귀 테스트. 작업 #7 부속.

실제 체크포인트(data/models/, git 미포함)가 있어야 하는 케이스는
@pytest.mark.ml_model로 표시한다 — 로컬에 모델 파일을 배치하지 않은 환경(CI 포함)에서는
`-m "not ml_model"`로 제외한다.
"""

import pytest

from app.api.category_classifier import CategoryClassifyRequest, predict_category
from app.domain import category_classifier
from app.domain.category_classifier import (
    CATEGORY_1_LABELS,
    CATEGORY_2_LABELS,
    CategoryModelUnavailable,
    predict_categories,
)


def test_category_1_labels_are_eight_unique_values_in_training_order() -> None:
    # category_classes 순서 — 채린 님 확인(2026-08-22). 순서가 바뀌면 모든 예측이
    # 조용히 다른 라벨로 오분류되므로 순서 자체를 회귀로 고정한다.
    assert CATEGORY_1_LABELS == [
        "수면", "정신건강", "운동", "식단", "만성질환", "여성건강", "유전자", "미용",
    ]
    assert len(set(CATEGORY_1_LABELS)) == 8


def test_category_2_labels_are_four_unique_values_in_training_order() -> None:
    # function_type_map({'A':0,'B':1,'C':2,'D':3}) 순서 — 채린 님 확인(2026-08-23).
    assert CATEGORY_2_LABELS == ["정보제공", "데이터기록관리", "매칭연결", "개입치료"]
    assert len(set(CATEGORY_2_LABELS)) == 4


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
def test_predict_categories_returns_valid_labels_with_confidence() -> None:
    # 실측 정확도(Avg Macro F1 0.6775, 2026-08-23 기준 계속 학습 중)가 아직 높지
    # 않아 특정 문장의 정답 라벨을 단정하지 않는다 — 대신 라벨/확신도가 유효한
    # 범위에서 나오는지, 그리고 pooler_output이 아니라 last_hidden_state[:,0]을
    # 쓸 때만 나오는 "분별력 있는" 확신도 범위(거의 균등분포가 아님)를 검증한다.
    (category_1, category_1_confidence), (category_2, category_2_confidence) = predict_categories(
        "매일 식단 사진을 찍으면 칼로리를 계산해주는 서비스"
    )
    assert category_1 in CATEGORY_1_LABELS
    assert category_2 in CATEGORY_2_LABELS
    # 균등분포 기준선(8종 0.125 / 4종 0.25)보다 뚜렷이 높아야 한다 — pooler_output으로
    # 잘못 연결하면 그 기준선 근처(실측: 축1 ~0.13~0.17, 축2 ~0.26~0.29)로 나오는
    # 회귀가 있었다. 실제 CLS 방식 확신도(이 문장 기준 0.466/0.813)보다 낮게 잡아
    # 모델이 계속 학습되며 값이 흔들려도 테스트가 깨지지 않게 여유를 둔다.
    assert category_1_confidence > 0.3
    assert category_2_confidence > 0.4


@pytest.mark.ml_model
async def test_predict_category_endpoint_returns_success() -> None:
    category_classifier._load.cache_clear()
    response = await predict_category(
        CategoryClassifyRequest(service_description="여성 생리주기를 기록하고 배란일을 예측하는 앱")
    )
    assert response.result.category_1 in CATEGORY_1_LABELS
    assert response.result.category_2 in CATEGORY_2_LABELS
