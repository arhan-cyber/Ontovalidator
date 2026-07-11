"""POST /validate."""

import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from src.models import OntologyAssertion

from .. import dependencies
from ..schemas import ValidateRequest, ValidateResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/validate", response_model=ValidateResponse)
async def validate(req: ValidateRequest):
    if not req.raw_text.strip():
        raise HTTPException(400, {"error": "raw_text must not be empty"})
    if not req.triples:
        raise HTTPException(400, {"error": "at least one triple is required"})

    engine = dependencies.resolve_engine(req.embedding_model, req.svo_extractor)
    document_id = req.document_id or f"doc_{uuid4().hex[:12]}"
    triples = [
        OntologyAssertion(
            assertion_id=t.assertion_id or f"t{i}",
            subject=t.subject,
            relation=t.relation,
            object=t.object,
            polarity=t.polarity,
            rule_type=t.rule_type,
        )
        for i, t in enumerate(req.triples, 1)
    ]
    try:
        result = await run_in_threadpool(
            engine.validate_triples_batch,
            document_id=document_id,
            raw_text=req.raw_text,
            triples=triples,
            top_k=req.top_k,
        )
    except Exception as e:
        logger.exception("validate_triples_batch failed")
        raise HTTPException(500, {"error": "validation_failed", "detail": str(e)})
    return result
