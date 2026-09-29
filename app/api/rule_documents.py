"""관리자 검수 API (/admin/rule-documents, /admin/rule-drafts) — Basic Auth로 보호.

langgraph_파이프라인_설계서.md §4.5(관리자 검수 인터페이스)/db_구축_설계서.md §4.1 대응.
배치 단위 검수(2026-09-27 결정) — draft 하나하나가 아니라 문서 실행 전체(=thread_id 하나)를
승인/반려 목록으로 한 번에 제출받는다. 그래서 원래 설계서가 그린 "/publish"·별도 반려
엔드포인트 대신, 승인·반려가 섞인 decisions 배열 하나를 받는 단일 엔드포인트로 합쳤다.
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy import select

from app.core.admin_auth import require_admin
from app.db.models import LawAmendmentAlert, RuleReviewQueue
from app.db.session import AsyncSessionLocal
from app.domain import law_api
from app.pipeline.checkpointer import get_checkpointer
from app.pipeline.document_id_normalize import normalize_document_id
from app.pipeline.graph import build_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-rule-review"])

# funding.py/proposals.py와 같은 컨벤션(10MB 제한).
_UPLOAD_DIR = Path("data/rule_uploads")
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@router.get("/rules", response_class=HTMLResponse)
async def admin_rules_page(_reviewer: str = Depends(require_admin)) -> str:
    """내부 전용 최소 검수 페이지 — 프론트팀 리소스 없이 백엔드가 직접 서빙한다
    (2026-09-27 결정, 소비자용 화면이 아니라 팀 내부 도구라 별도 프론트 불필요)."""
    return (_STATIC_DIR / "admin_rules.html").read_text(encoding="utf-8")


def _is_pdf(file: UploadFile) -> bool:
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    return filename.endswith(".pdf") or content_type == "application/pdf"


async def _run_pipeline(thread_id: str, initial_state: dict) -> None:
    """백그라운드 태스크 — LLM 추출은 청크 수에 따라 수십 초~수 분 걸릴 수 있어 업로드
    응답을 블로킹하지 않는다. human_review의 interrupt()에서 자연스럽게 멈춘다.

    예외를 직접 로그로 남긴다 — 응답은 이미 나간 뒤라 관리자에게 전달할 경로가 없고,
    그냥 새어나가면 "검수 목록에 안 뜨는데 이유를 알 수 없는" 상태가 된다.
    """
    graph = build_graph(checkpointer=get_checkpointer())
    try:
        await graph.ainvoke(initial_state, config={"configurable": {"thread_id": thread_id}})
    except Exception:
        logger.exception(
            "룰 추출 파이프라인 실패: thread_id=%s document_id=%s",
            thread_id,
            initial_state.get("document_id"),
        )


class RuleDocumentUploadResponse(BaseModel):
    thread_id: str
    document_id: str


@router.post("/rule-documents", response_model=RuleDocumentUploadResponse)
async def upload_rule_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="법령/가이드 PDF")],
    target_stages: Annotated[str, Form(description="쉼표구분, 예: A,B")],
    # 비워두면 classify_document_source 노드가 document_id(파일명)로 자동 분류한다
    # (2026-09-27 결정) — 관리자가 값을 지정하면 그 값을 그대로 존중하고 분류를 건너뛴다.
    document_category: Annotated[
        Literal["법령규제문서", "판단가이드", "위험표현사전"] | None, Form()
    ] = None,
    document_id: Annotated[str | None, Form()] = None,
    _reviewer: str = Depends(require_admin),
) -> RuleDocumentUploadResponse:
    if not _is_pdf(file):
        raise HTTPException(status_code=422, detail="PDF 파일만 업로드할 수 있습니다.")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다(10MB 제한).")

    stages = [s.strip() for s in target_stages.split(",") if s.strip()]
    if not stages:
        raise HTTPException(status_code=422, detail="target_stages를 하나 이상 지정해야 합니다.")

    thread_id = str(uuid.uuid4())
    # document_id는 legal_basis_doc의 join 키다(ingest_document 주석 참조). 한글 파일명을
    # 그대로 두면 RAG evidence_documents.document_id(kr-xxx 형태)와 안 맞아 조인이 끊기므로,
    # 알려진 문서명이면 정식 kr-* id로 정규화한다(document_id_normalize.py 참고). 저장 경로는
    # 파일명과 무관하게 충돌 방지를 위해 thread_id로 따로 둔다.
    raw_document_id = document_id or Path(file.filename or "unknown").stem
    resolved_document_id = normalize_document_id(raw_document_id)

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = _UPLOAD_DIR / f"{thread_id}.pdf"
    saved_path.write_bytes(content)

    initial_state = {
        "source_path": str(saved_path),
        "document_id": resolved_document_id,
        # 자동 분류는 정규화 전 한글 제목을 봐야 한다 — resolved_document_id는 영문 slug라
        # "시행규칙" 같은 패턴이 남아있지 않다(classify_document_source 참고).
        "source_title": raw_document_id,
        "document_category": document_category,
        "target_stages": stages,
        "chunks": [],
        "current_chunk_id": None,
        "current_stage": None,
        "drafts": [],
        "derived_values": {},
        "validation": None,
        "retry_count": 0,
        "rule_version_id": None,
        "rejected_drafts": [],
    }
    background_tasks.add_task(_run_pipeline, thread_id, initial_state)
    return RuleDocumentUploadResponse(thread_id=thread_id, document_id=resolved_document_id)


# ---- 법령(law.go.kr API) 경로 — PDF 없이 조문을 직접 받아 투입 ----


class LawSearchResult(BaseModel):
    title: str
    mst: str
    law_type: str
    promulgation_no: str
    effective_date: str
    suggested_document_id: str


@router.get("/law-search", response_model=list[LawSearchResult])
async def search_law(
    query: str,
    _reviewer: str = Depends(require_admin),
) -> list[LawSearchResult]:
    """법령명으로 law.go.kr을 검색한다. 검색이 느슨해서 관계없는 법이 섞여 나오므로
    (예: "의료법" → "공공보건의료에 관한 법률") 화면에서 사람이 골라야 한다."""
    try:
        laws = await law_api.search_laws(query, display=20)
    except law_api.LawApiUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return [
        LawSearchResult(
            title=law.get("법령명한글") or "",
            mst=str(law.get("법령일련번호") or ""),
            law_type=law.get("법령구분명") or "",
            promulgation_no=str(law.get("공포번호") or ""),
            effective_date=str(law.get("시행일자") or ""),
            # 알려진 문서면 정식 kr-* id를 제안한다 — legal_basis_doc 조인 키라 중요.
            suggested_document_id=normalize_document_id(law.get("법령명한글") or ""),
        )
        for law in laws
    ]


class LawArticle(BaseModel):
    # article_key는 가지조문 구분용("2" vs "2-2") — 선택 시 이 값을 보낸다.
    # 조문번호만 쓰면 제2조를 고를 때 제2조의2까지 딸려온다(law_api.article_key 참고).
    article_key: str
    article_label: str
    title: str
    effective_date: str
    changed: bool
    body: str


@router.get("/law-articles", response_model=list[LawArticle])
async def list_law_articles(
    mst: str,
    changed_only: bool = False,
    _reviewer: str = Depends(require_admin),
) -> list[LawArticle]:
    """선택한 법령의 조문 목록. changed_only=true면 최근 개정에서 바뀐 조문만 추린다
    (개정 대응 시 검수 배치를 실제 변경분으로만 좁히는 용도)."""
    try:
        articles = await law_api.fetch_articles(mst)
    except law_api.LawApiUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if changed_only:
        articles = law_api.changed_articles(articles)
    return [
        LawArticle(
            article_key=a.get("조문키") or "",
            article_label=a.get("조문표기") or "",
            title=a.get("조문제목") or "",
            effective_date=str(a.get("조문시행일자") or ""),
            changed=a.get("조문변경여부") == "Y",
            body=a.get("본문") or "",
        )
        for a in articles
    ]


class LawIngestRequest(BaseModel):
    mst: str
    document_id: str
    target_stages: list[str]
    # 비우면 전체 조문. 조문 수가 100개를 넘는 법령이 많아 보통은 필요한 조문만 고른다 —
    # 우리가 실제로 인용하는 건 의료기기법 제2조, 의료법 제27조처럼 소수다.
    # 값은 law-articles가 준 article_key("2", "2-2")를 쓴다 — 조문번호만 쓰면 가지조문이
    # 같은 번호를 공유해서 원하지 않은 조문까지 딸려온다.
    article_keys: list[str] = []
    document_category: Literal["법령규제문서", "판단가이드", "위험표현사전"] | None = None


@router.post("/rule-documents/from-law", response_model=RuleDocumentUploadResponse)
async def ingest_rule_document_from_law(
    request: LawIngestRequest,
    background_tasks: BackgroundTasks,
    _reviewer: str = Depends(require_admin),
) -> RuleDocumentUploadResponse:
    """law.go.kr 본문 API에서 조문을 받아 PDF 없이 파이프라인에 투입한다.

    조문 단위로 이미 나뉜 텍스트라 ingest_document/chunk_document를 건너뛴다
    (graph._route_after_classify) — pypdf 파싱 오차가 원천적으로 없어진다.
    """
    if not request.target_stages:
        raise HTTPException(status_code=422, detail="target_stages를 하나 이상 지정해야 합니다.")

    try:
        articles = await law_api.fetch_articles(request.mst)
    except law_api.LawApiUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if request.article_keys:
        wanted = set(request.article_keys)
        articles = [a for a in articles if a.get("조문키") in wanted]
    if not articles:
        raise HTTPException(status_code=422, detail="선택한 조문을 찾을 수 없습니다.")

    chunks = law_api.articles_to_chunks(articles, request.document_id)
    if not chunks:
        raise HTTPException(status_code=422, detail="선택한 조문에 본문 텍스트가 없습니다.")

    thread_id = str(uuid.uuid4())
    initial_state = {
        "document_id": request.document_id,
        # 법령 API에서 받은 문서는 정의상 법령규제문서다 — 분류 노드가 파일명을 볼 일이 없다.
        "document_category": request.document_category or "법령규제문서",
        "target_stages": request.target_stages,
        "chunks": chunks,
        "raw_text": "",
        "current_chunk_id": None,
        "current_stage": None,
        "drafts": [],
        "derived_values": {},
        "validation": None,
        "retry_count": 0,
        "rule_version_id": None,
        "rejected_drafts": [],
    }
    background_tasks.add_task(_run_pipeline, thread_id, initial_state)
    return RuleDocumentUploadResponse(thread_id=thread_id, document_id=request.document_id)


class RuleDraftSummary(BaseModel):
    thread_id: str
    document_id: str
    status: str
    item_count: int
    created_at: str


@router.get("/rule-drafts", response_model=list[RuleDraftSummary])
async def list_rule_drafts(_reviewer: str = Depends(require_admin)) -> list[RuleDraftSummary]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(RuleReviewQueue)
                .where(RuleReviewQueue.status == "pending")
                .order_by(RuleReviewQueue.created_at)
            )
        ).scalars().all()
    return [
        RuleDraftSummary(
            thread_id=row.thread_id,
            document_id=row.document_id,
            status=row.status,
            item_count=len(row.items),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


class RuleDraftDetail(BaseModel):
    thread_id: str
    document_id: str
    status: str
    items: list[dict]
    chunks: list[dict]


@router.get("/rule-drafts/{thread_id}", response_model=RuleDraftDetail)
async def get_rule_draft(thread_id: str, _reviewer: str = Depends(require_admin)) -> RuleDraftDetail:
    async with AsyncSessionLocal() as session:
        row = await session.get(RuleReviewQueue, thread_id)
    if row is None:
        raise HTTPException(status_code=404, detail="검수 항목을 찾을 수 없습니다.")
    return RuleDraftDetail(
        thread_id=row.thread_id,
        document_id=row.document_id,
        status=row.status,
        items=row.items,
        chunks=row.chunks,
    )


class DecisionItem(BaseModel):
    action: Literal["approve", "reject"]
    reason: str | None = None
    edited_fields: dict | None = None


class RuleDraftDecisionRequest(BaseModel):
    decisions: list[DecisionItem]


class RuleDraftDecisionResponse(BaseModel):
    status: str


async def _claim_for_resolution(thread_id: str, decision_count: int) -> None:
    """pending 행만 resolving으로 선점한다.

    조회와 상태 변경을 한 트랜잭션(SELECT ... FOR UPDATE)으로 묶어야 한다 — 상태를 읽고
    세션을 닫은 뒤 resume하면 동시에 들어온 제출 두 건이 모두 검사를 통과해 같은 배치를
    두 번 publish한다.
    """
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(RuleReviewQueue)
                .where(RuleReviewQueue.thread_id == thread_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="검수 항목을 찾을 수 없습니다.")
        if row.status == "resolving":
            raise HTTPException(status_code=409, detail="다른 요청이 처리 중입니다.")
        if row.status != "pending":
            raise HTTPException(status_code=409, detail="이미 처리된 검수 항목입니다.")
        if decision_count != len(row.items):
            raise HTTPException(
                status_code=422, detail="decisions 개수가 검수 항목 수와 일치해야 합니다."
            )
        row.status = "resolving"
        await session.commit()


async def _set_review_status(thread_id: str, status: str) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.get(RuleReviewQueue, thread_id)
        if row is None:
            return
        row.status = status
        await session.commit()


@router.post("/rule-drafts/{thread_id}/decision", response_model=RuleDraftDecisionResponse)
async def decide_rule_draft(
    thread_id: str,
    request: RuleDraftDecisionRequest,
    reviewer: str = Depends(require_admin),
) -> RuleDraftDecisionResponse:
    await _claim_for_resolution(thread_id, len(request.decisions))

    graph = build_graph(checkpointer=get_checkpointer())
    resume_payload = {
        "decisions": [d.model_dump() for d in request.decisions],
        "reviewed_by": reviewer,
    }
    try:
        await graph.ainvoke(
            Command(resume=resume_payload), config={"configurable": {"thread_id": thread_id}}
        )
    except Exception:
        # publish 실패 등으로 그래프가 죽으면 pending으로 되돌린다 — resolved로 남겨두면
        # 재제출이 409로 막혀 그 스레드를 손으로 DB를 고치지 않고는 살릴 수 없다.
        logger.exception("검수 결정 처리 실패: thread_id=%s", thread_id)
        await _set_review_status(thread_id, "pending")
        raise
    await _set_review_status(thread_id, "resolved")
    return RuleDraftDecisionResponse(status="resolved")


# ---- 법령 개정 알림 (scripts/check_law_amendments.py가 기록한 것) ----


class LawAlertSummary(BaseModel):
    alert_id: str
    law_title: str
    document_id: str | None
    known_promulgation_no: int
    latest_promulgation_no: int
    known_effective_date: str
    latest_effective_date: str
    relevance: str
    status: str
    changed_count: int
    related_articles: list[dict]
    changed_articles: list[dict]
    # 우리가 인용하는데 현행 법령에 없는 조문 번호 — 해당 룰은 근거가 끊긴 상태다.
    missing_citations: list[str]
    detected_at: str


@router.get("/law-alerts", response_model=list[LawAlertSummary])
async def list_law_alerts(_reviewer: str = Depends(require_admin)) -> list[LawAlertSummary]:
    """미처리(open) 개정 알림 목록. relevance=related가 먼저 오도록 정렬한다 — 무관한
    개정이 목록 위를 차지하면 정작 대응이 필요한 건을 놓친다."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(LawAmendmentAlert)
                .where(LawAmendmentAlert.status == "open")
                .order_by(LawAmendmentAlert.relevance, LawAmendmentAlert.detected_at.desc())
            )
        ).scalars().all()
    return [
        LawAlertSummary(
            alert_id=str(row.alert_id),
            law_title=row.law_title,
            document_id=row.document_id,
            known_promulgation_no=row.known_promulgation_no,
            latest_promulgation_no=row.latest_promulgation_no,
            known_effective_date=row.known_effective_date,
            latest_effective_date=row.latest_effective_date,
            relevance=row.relevance,
            status=row.status,
            changed_count=len(row.changed_articles),
            related_articles=row.related_articles,
            changed_articles=row.changed_articles,
            missing_citations=row.missing_citations,
            detected_at=row.detected_at.isoformat(),
        )
        for row in rows
    ]


class LawAlertStatusRequest(BaseModel):
    # dismissed = 확인했고 대응 불필요(무관한 개정 등), resolved = 재투입까지 마침
    status: Literal["dismissed", "resolved"]


@router.post("/law-alerts/{alert_id}/status", response_model=LawAlertSummary)
async def update_law_alert_status(
    # UUID로 받아야 형식이 틀린 값이 500이 아니라 422로 떨어진다.
    alert_id: uuid.UUID,
    request: LawAlertStatusRequest,
    reviewer: str = Depends(require_admin),
) -> LawAlertSummary:
    async with AsyncSessionLocal() as session:
        row = await session.get(LawAmendmentAlert, alert_id)
        if row is None:
            raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다.")
        row.status = request.status
        row.resolved_at = datetime.now(timezone.utc)
        row.resolved_by = reviewer
        await session.commit()
        await session.refresh(row)

        return LawAlertSummary(
            alert_id=str(row.alert_id),
            law_title=row.law_title,
            document_id=row.document_id,
            known_promulgation_no=row.known_promulgation_no,
            latest_promulgation_no=row.latest_promulgation_no,
            known_effective_date=row.known_effective_date,
            latest_effective_date=row.latest_effective_date,
            relevance=row.relevance,
            status=row.status,
            changed_count=len(row.changed_articles),
            related_articles=row.related_articles,
            changed_articles=row.changed_articles,
            missing_citations=row.missing_citations,
            detected_at=row.detected_at.isoformat(),
        )
