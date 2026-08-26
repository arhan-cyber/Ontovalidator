"""Ontology compliance endpoints: validation, graph view, conflict queue."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from src.ontology.compliance import OntologyComplianceValidator
from src.ontology.compliance_config import OntologyComplianceConfig
from src.ontology.conflicts import VALID_STATUSES, ConflictRegistry
from src.ontology.loader import OntologyInputError, load_metamodel, load_ontology

from .. import dependencies
from ..schemas import (
    ConflictResolveRequest,
    OntologyGraphResponse,
    OntologyValidateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ontology", tags=["ontology"])


def _config(req: Optional[OntologyValidateRequest] = None) -> OntologyComplianceConfig:
    config = OntologyComplianceConfig.from_env()
    if req is None:
        return config
    if req.ontology_path:
        config.ontology_path = req.ontology_path
    if req.metamodel_path:
        config.metamodel_path = req.metamodel_path
    if req.documents_path:
        config.document_corpus_path = req.documents_path
    if req.claim_kinds:
        config.claim_kinds = req.claim_kinds
    if req.severity_threshold:
        config.severity_threshold = req.severity_threshold
    config.enable_conformance = req.plane in ("a", "both")
    config.enable_grounding = req.plane in ("b", "both")
    config.include_it4it_corpus = req.include_it4it
    config.top_k = req.top_k
    return config


def _registry() -> ConflictRegistry:
    config = _config()
    if not config.enable_conflict_registry:
        raise HTTPException(
            503,
            {"error": "conflict_registry_disabled",
             "detail": "Set ONTO_ENABLE_CONFLICT_REGISTRY=true to use this endpoint"},
        )
    return ConflictRegistry(config.conflict_db_path)


@router.post("/validate")
async def validate_ontology(req: OntologyValidateRequest):
    """Run conformance and/or grounding, returning the full report."""
    config = _config(req)
    engine = dependencies.resolve_engine(None, None) if config.enable_grounding else None
    validator = OntologyComplianceValidator(config, engine=engine)
    try:
        report = await run_in_threadpool(validator.validate)
    except OntologyInputError as exc:
        raise HTTPException(400, {"error": "ontology_input_missing", "detail": str(exc)})
    except Exception as exc:
        logger.exception("ontology validation failed")
        raise HTTPException(500, {"error": "ontology_validation_failed", "detail": str(exc)})
    return report.to_dict()


@router.get("/graph", response_model=OntologyGraphResponse)
async def ontology_graph():
    """Nodes and edges for the graph viewer, without running any checks."""
    config = _config()
    try:
        graph = await run_in_threadpool(load_ontology, config.ontology_path)
    except OntologyInputError as exc:
        raise HTTPException(400, {"error": "ontology_input_missing", "detail": str(exc)})
    return {
        "version": graph.version,
        "nodes": [
            {
                "id": node.id,
                "meta_class": node.meta_class,
                "types": node.types,
                "description": node.description,
                "next_pointer": node.next_pointer,
            }
            for node in graph.nodes.values()
        ],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "key": edge.key,
            }
            for edge in graph.edges
        ],
    }


@router.get("/conflicts")
async def list_conflicts(
    status: Optional[str] = Query(None, description=f"One of: {', '.join(sorted(VALID_STATUSES))}"),
    limit: Optional[int] = Query(None, ge=1, le=1000),
):
    """The adjudication queue. Defaults to everything; filter to `open` to review."""
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            400,
            {"error": "invalid_status",
             "detail": f"status must be one of {sorted(VALID_STATUSES)}"},
        )
    registry = _registry()
    rows = await run_in_threadpool(registry.all_conflicts, status)
    if limit:
        rows = rows[:limit]
    return {
        "conflicts": rows,
        "unreviewed": await run_in_threadpool(registry.unreviewed_count),
    }


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, req: ConflictResolveRequest):
    """Adjudicate one conflict. Idempotent: re-running validation won't undo it."""
    registry = _registry()
    try:
        await run_in_threadpool(
            registry.resolve, conflict_id, req.status, req.note, req.resolved_by
        )
    except KeyError:
        raise HTTPException(404, {"error": "conflict_not_found", "detail": conflict_id})
    except ValueError as exc:
        raise HTTPException(400, {"error": "invalid_status", "detail": str(exc)})
    return await run_in_threadpool(registry.get, conflict_id)


@router.get("/amendments")
async def proposed_amendments():
    """Meta-model changes implied by conflicts adjudicated `metamodel_gap`.

    A proposal only. Nothing here is ever written to the meta-model JSON -
    changing the authoritative blueprint stays a deliberate human act.
    """
    registry = _registry()
    return {"amendments": await run_in_threadpool(registry.proposed_amendments)}
