"""Top-level orchestrator: run both validation planes and merge the results.

    load -> conformance (Plane A) -> conflict registry -> project claims
         -> ingest corpus -> adjudicate (Plane B) -> ComplianceReport

Either plane can be turned off independently. Plane A needs nothing but the
two JSON files; Plane B additionally needs an engine and a document corpus,
and is skipped rather than failed when it hasn't got them.
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Sequence

from .compliance_config import OntologyComplianceConfig
from .conformance import run_conformance
from .conflicts import ConflictRegistry
from .loader import load_metamodel, load_ontology
from .models import MetaModel, OntologyGraph, Severity
from .projection import claims_to_assertions, project_ontology, provenance_index
from .report import ComplianceReport, rollup_grounding

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[str, int, int], None]]


class OntologyComplianceValidator:
    """Runs structural conformance and evidential grounding, and merges them."""

    def __init__(
        self,
        config: Optional[OntologyComplianceConfig] = None,
        engine: Optional[Any] = None,
        registry: Optional[ConflictRegistry] = None,
    ):
        self.config = config or OntologyComplianceConfig()
        self.engine = engine
        self._registry = registry

    # -- registry ----------------------------------------------------------

    @property
    def registry(self) -> Optional[ConflictRegistry]:
        if not self.config.enable_conflict_registry:
            return None
        if self._registry is None:
            self._registry = ConflictRegistry(self.config.conflict_db_path)
        return self._registry

    # -- planes ------------------------------------------------------------

    def run_conformance_plane(
        self, ontology: OntologyGraph, metamodel: MetaModel
    ) -> Dict[str, Any]:
        """Plane A, plus conflict-registry bookkeeping.

        Findings are recorded first and *then* re-labelled by any stored
        adjudication, so a conflict already resolved as `metamodel_gap`
        reports as info and one accepted as a deliberate exception disappears
        from the report without disappearing from the registry.
        """
        findings = run_conformance(ontology, metamodel)

        unreviewed = 0
        registry = self.registry
        if registry is not None:
            adjudicable = [f for f in findings if f.rule_id in self.config.adjudicable_rules]
            if adjudicable:
                stats = registry.record_many(adjudicable)
                logger.info(
                    "conflict registry: %s new, %s seen again",
                    stats.get("new", 0), stats.get("seen_again", 0),
                )
            findings = registry.apply_resolutions(findings)
            unreviewed = registry.unreviewed_count()

        threshold = Severity(self.config.severity_threshold)
        findings = [
            f for f in findings
            if _severity_rank(f.severity) <= _severity_rank(threshold)
        ]
        return {"findings": findings, "unreviewed_conflicts": unreviewed}

    def run_grounding_plane(
        self,
        ontology: OntologyGraph,
        progress: ProgressCallback = None,
    ) -> Dict[str, Any]:
        """Plane B: project claims, ingest the corpus, adjudicate corpus-wide."""
        if self.engine is None:
            logger.info("grounding skipped: no engine supplied")
            return {"ran": False, "reason": "no engine"}

        claims = project_ontology(ontology, self.config.claim_kinds)
        documents = self.ingest_corpus()
        if not documents:
            logger.warning(
                "grounding skipped: no documents ingested from %s",
                self.config.document_corpus_path,
            )
            return {"ran": False, "reason": "empty corpus"}

        def _tick(index: int, total: int, assertion_id: str) -> None:
            if progress is not None:
                progress(f"adjudicating {assertion_id}", index, total)

        result = self.engine.validate_assertions_corpus(
            claims_to_assertions(claims), top_k=self.config.top_k, progress_callback=_tick
        )
        rolled = rollup_grounding(result["verdicts"], provenance_index(claims))
        return {
            "ran": True,
            "verdicts": result["verdicts"],
            "corpus_fingerprint": result.get("corpus_fingerprint"),
            "corpus_documents": documents,
            "node_grounding": rolled["nodes"],
            "edge_grounding": rolled["edges"],
            "vocabulary_presence": self.measure_vocabulary_presence(ontology),
            "retrieval_backends": self.engine.get_backend_status(),
        }

    def measure_vocabulary_presence(self, ontology: OntologyGraph) -> Dict[str, bool]:
        """Whether each node's label occurs literally anywhere in the corpus.

        A blunt substring scan on purpose: it answers "could this term have
        been retrieved at all", which is the question that separates a corpus
        problem from a retrieval problem. It is not a judgement about whether
        the claim is *true*.
        """
        from ..storage import SQLiteChunkStore
        from ..storage.sqlite_conn import connect as _connect
        from .projection import clean_node_label

        engine = self.engine
        if engine is None or not isinstance(engine.chunk_store, SQLiteChunkStore):
            return {}
        conn = _connect(engine.chunk_store.db_path)
        try:
            corpus = " ".join(
                row[0] or "" for row in conn.execute("SELECT text FROM chunks")
            ).lower()
        finally:
            conn.close()
        return {
            node_id: clean_node_label(node_id).lower() in corpus
            for node_id in ontology.nodes
        }

    def ingest_corpus(self) -> List[str]:
        """Ingest the configured document corpus, returning the document ids.

        Scoping is by *ingest*: the retrievers filter on one `document_id` or
        none, so there is no way to search a subset afterwards. Excluding
        IT4IT here is what makes `include_it4it_corpus=False` mean anything
        (decision D4).
        """
        directory = self.config.document_corpus_path
        if not directory or not os.path.isdir(directory):
            logger.warning("document corpus directory not found: %s", directory)
            return []

        ingestor = self._build_ingestor()
        if ingestor is None:
            return []

        results = ingestor.ingest_corpus(
            directory,
            include_patterns=self.config.include_patterns,
            exclude_patterns=self.config.effective_exclude_patterns(),
            page_range=self.config.page_range,
        )
        ingested = []
        for result in results:
            if result.get("status") == "success":
                ingested.append(result.get("document_id"))
            else:
                logger.warning(
                    "corpus ingest failed for %s: %s",
                    result.get("document_id"), result.get("error"),
                )
        return [d for d in ingested if d]

    def _build_ingestor(self):
        from ..ingestion import (
            DataIngestor,
            MockConceptExtractor,
            MockSVOExtractor,
            SimpleEmbeddingModel,
        )

        engine = self.engine
        if engine is None:
            return None
        return DataIngestor(
            sqlite_conn_path=engine.chunk_store.db_path,
            es_client=getattr(engine.lexical_store, "client", None),
            milvus_collection=getattr(engine.semantic_store, "collection", None),
            neo4j_driver=getattr(engine.graph_store, "driver", None),
            embedding_model=engine.embedding_model or SimpleEmbeddingModel(),
            svo_extractor=engine.svo_extractor or MockSVOExtractor(),
            concept_extractor=MockConceptExtractor(),
            config=engine.config,
        )

    # -- entry point -------------------------------------------------------

    def validate(self, progress: ProgressCallback = None) -> ComplianceReport:
        ontology = load_ontology(self.config.ontology_path)
        metamodel = load_metamodel(self.config.metamodel_path)

        report = ComplianceReport(
            ontology_version=ontology.version,
            metamodel_version=metamodel.version,
            ontology_path=ontology.source_path,
            metamodel_path=metamodel.source_path,
            total_nodes=len(ontology.nodes),
            total_edges=len(ontology.edges),
        )

        if self.config.enable_conformance:
            if progress:
                progress("checking conformance", 0, 1)
            plane_a = self.run_conformance_plane(ontology, metamodel)
            report.findings = plane_a["findings"]
            report.unreviewed_conflicts = plane_a["unreviewed_conflicts"]

        if self.config.enable_grounding:
            plane_b = self.run_grounding_plane(ontology, progress=progress)
            if plane_b.get("ran"):
                report.grounding_ran = True
                report.verdicts = plane_b["verdicts"]
                report.corpus_fingerprint = plane_b["corpus_fingerprint"]
                report.corpus_documents = plane_b["corpus_documents"]
                report.node_grounding = plane_b["node_grounding"]
                report.edge_grounding = plane_b["edge_grounding"]
                report.vocabulary_presence = plane_b.get("vocabulary_presence", {})
                report.retrieval_backends = plane_b.get("retrieval_backends", {})

        return report


_SEVERITY_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def _severity_rank(severity: Severity) -> int:
    return _SEVERITY_RANK[severity]
