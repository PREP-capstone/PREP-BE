"""판정 API — 1번 담당(Gate/규제 위험도 판정). 이슈 1: judgement/gate.

data_type/function_type/acquire_method/invasive_signal 판별은 규칙 기반이다(LLM 미사용).
analysis-sessions API가 아직 없어 요청 스키마는 역할분담표 §6 예시를 기준으로 임시 확정했다 —
실제 스키마 나오면 특히 health_data_items[].source(수집방법)·data_type(값 타입, GATE_MATRIX_TABLE의
data_type과 이름만 같고 뜻이 다름) 필드를 다시 맞춰야 한다.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import GateKeyword, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.correction_terms import BIOMARKER_EXTRA
from app.pipeline.gate_matrix_table import GATE_MATRIX_TABLE, detect_invasive, is_invasive_hardcheck

router = APIRouter(prefix="/api/v1/judgement", tags=["judgement"])


class HealthDataItem(BaseModel):
    name: str
    data_type: str  # numeric/text/image 등 값 타입 — GATE_MATRIX_TABLE.data_type(라이프스타일/생체지표)과 다른 개념
    unit: str | None = None
    source: str  # user_input / device_sync / os_sync
    is_sensitive: bool = False


class GateRequest(BaseModel):
    service_name: str
    service_description: str
    health_data_items: list[HealthDataItem]
    service_actions: list[str]


class GateResponse(BaseModel):
    data_type: str
    function_type: str
    acquire_method: str | None
    invasive_signal: bool
    verdict: str
    hardcheck_fired: bool


_SOURCE_TO_ACQUIRE_METHOD = {
    "user_input": "수동입력",
    "device_sync": "기기연동",
    "os_sync": "OS연동",
}

# service_actions → function_type. 여러 액션이 섞이면 가장 위험도가 높은 쪽을 채택한다
# (db_구축_설계서.md §3.2의 "복수 조합 시 FAIL 우선" 원칙과 같은 방향).
_ACTION_PRIORITY: list[tuple[set[str], str]] = [
    ({"predict", "diagnose", "alert"}, "수치예측·진단"),
    ({"visualize_trend"}, "비교·추이분석"),
    ({"record"}, "단순기록"),
]

# acquire_method 우선순위 — 기기연동이어야 침습적 하드체크가 발동하므로 가장 위험한 것을 채택.
_ACQUIRE_METHOD_PRIORITY = ("기기연동", "OS연동", "수동입력")


async def _biomarker_keywords() -> set[str]:
    """gate_keywords의 DATA_TYPE 분류 키워드를 생체지표 판별 사전으로 재사용한다.

    새 키워드 목록을 따로 만들지 않는다 — 실제 법령 문서에서 검증된 키워드가 이미
    gate_keywords에 있고, 파이프라인이 문서를 더 넣으면 이 목록도 자동으로 늘어난다.
    심박수·체중 등 문서에 아직 안 뽑힌 흔한 생체지표는 correction_terms.BIOMARKER_EXTRA로 보충한다
    (Stage C가 같은 이유로 이미 쓰고 있는 목록).
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(GateKeyword.keyword)
            .join(RuleVersion, RuleVersion.rule_version_id == GateKeyword.rule_version_id)
            .where(RuleVersion.status == "active", GateKeyword.keyword_category == "DATA_TYPE")
        )
        return set(result.scalars().all()) | set(BIOMARKER_EXTRA)


def _classify_data_type(items: list[HealthDataItem], biomarker_keywords: set[str]) -> str:
    for item in items:
        if any(keyword in item.name for keyword in biomarker_keywords):
            return "생체지표"
    return "라이프스타일"


def _classify_function_type(actions: list[str]) -> str:
    action_set = set(actions)
    for trigger_actions, function_type in _ACTION_PRIORITY:
        if action_set & trigger_actions:
            return function_type
    return "단순기록"


def _classify_acquire_method(items: list[HealthDataItem]) -> str | None:
    methods = {_SOURCE_TO_ACQUIRE_METHOD.get(item.source) for item in items}
    for method in _ACQUIRE_METHOD_PRIORITY:
        if method in methods:
            return method
    return None


def _detect_invasive_signal(request: GateRequest) -> bool:
    text = request.service_description + " " + " ".join(item.name for item in request.health_data_items)
    return detect_invasive(text)


@router.post("/gate", response_model=GateResponse)
async def judge_gate(request: GateRequest) -> GateResponse:
    biomarker_keywords = await _biomarker_keywords()
    data_type = _classify_data_type(request.health_data_items, biomarker_keywords)
    function_type = _classify_function_type(request.service_actions)
    acquire_method = _classify_acquire_method(request.health_data_items)
    invasive_signal = _detect_invasive_signal(request)

    if is_invasive_hardcheck(data_type, acquire_method, invasive_signal):
        return GateResponse(
            data_type=data_type,
            function_type=function_type,
            acquire_method=acquire_method,
            invasive_signal=invasive_signal,
            verdict="FAIL",
            hardcheck_fired=True,
        )

    cell = GATE_MATRIX_TABLE[(data_type, function_type)]
    return GateResponse(
        data_type=data_type,
        function_type=function_type,
        acquire_method=acquire_method,
        invasive_signal=invasive_signal,
        verdict=cell["verdict"],
        hardcheck_fired=False,
    )
