"""POST /feedback/correct and GET /feedback/analysis."""

import logging

from fastapi import APIRouter, HTTPException

from src.feedback import FeedbackDashboard, FeedbackRecorder
from src.feedback.recorder import VALID_LABELS
from src.models import TripleVerdict

from .. import dependencies
from ..schemas import CorrectionRequest, CorrectionResponse, FeedbackAnalysisResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/feedback", tags=["feedback"])


def _recorder() -> FeedbackRecorder:
    engine = dependencies.resolve_engine(None, None)
    recorder = getattr(engine, "feedback_recorder", None)
    if recorder is None:
        raise HTTPException(503, {"error": "feedback_disabled", "detail": "Feedback recording is not enabled"})
    return recorder


def _verdict_from_request(req: CorrectionRequest) -> tuple[TripleVerdict, str]:
    """Rebuild the corrected verdict, preferring the cached original.

    Clients only hold a feedback_id, so the original verdict is looked up in the
    shared cache. When the cache has expired (or is disabled) the request's own
    fields are used, which is why they are accepted as a fallback.
    """
    engine = dependencies.resolve_engine(None, None)
    cache = getattr(engine, "cache_engine", None)
    cached = cache.get("feedback_verdict", req.feedback_id) if cache and req.feedback_id else None

    if cached:
        stored = cached["verdict"]
        return (
            TripleVerdict(
                assertion_id=stored["assertion_id"],
                subject=stored["subject"],
                relation=stored["relation"],
                object=stored["object"],
                label=stored["label"],
                score=stored["score"],
                rationale=stored.get("rationale", ""),
                evidence=[],
                counter_evidence=[],
                retrieval_sources=stored.get("retrieval_sources", []),
                rule_hits=stored.get("rule_hits", []),
            ),
            req.document_id or cached["document_id"],
        )

    missing = [f for f in ("assertion_id", "predicted_label", "document_id") if not getattr(req, f)]
    if missing:
        raise HTTPException(
            404,
            {
                "error": "verdict_not_found",
                "detail": (
                    "The original verdict is no longer cached. Resend it with "
                    f"these fields: {', '.join(missing)}"
                ),
            },
        )

    return (
        TripleVerdict(
            assertion_id=req.assertion_id,
            subject=req.subject or "",
            relation=req.relation or "",
            object=req.object or "",
            label=req.predicted_label,
            score=req.predicted_score or 0.0,
            rationale="",
            evidence=[],
            counter_evidence=[],
            retrieval_sources=req.retrieval_sources or [],
            rule_hits=[],
        ),
        req.document_id,
    )


@router.post("/correct", response_model=CorrectionResponse)
async def submit_correction(req: CorrectionRequest):
    if req.actual_label not in VALID_LABELS:
        raise HTTPException(
            400,
            {"error": "invalid_label", "detail": f"actual_label must be one of {list(VALID_LABELS)}"},
        )

    recorder = _recorder()
    verdict, document_id = _verdict_from_request(req)
    try:
        recorder.record_correction(
            verdict=verdict,
            actual_label=req.actual_label,
            document_id=document_id,
            actual_reason=req.reason,
        )
    except Exception as e:
        logger.exception("record_correction failed")
        raise HTTPException(500, {"error": "record_failed", "detail": str(e)})

    return CorrectionResponse(
        status="recorded",
        assertion_id=verdict.assertion_id,
        document_id=document_id,
        predicted_label=verdict.label,
        actual_label=req.actual_label,
    )


@router.get("/analysis", response_model=FeedbackAnalysisResponse)
async def get_error_analysis(days: int = 30):
    if days < 1:
        raise HTTPException(400, {"error": "invalid_days", "detail": "days must be >= 1"})

    recorder = _recorder()
    dashboard = FeedbackDashboard(recorder)
    metrics = dashboard.compute_metrics(days)
    return FeedbackAnalysisResponse(
        summary=metrics["summary"],
        error_analysis=metrics["error_analysis"],
        retriever_performance=metrics["retriever_performance"],
        recommendations=metrics["recommendations"],
    )
