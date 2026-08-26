"""Configuration for an ontology compliance run.

Kept separate from `PipelineConfig` because most of these settings describe a
*validation run* (which claim kinds, which documents, which severity floor)
rather than how the pipeline itself is wired. `from_pipeline_config` bridges
the two so a caller with a `PipelineConfig` doesn't have to restate anything.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .loader import DEFAULT_METAMODEL_PATH, DEFAULT_ONTOLOGY_PATH
from .projection import ALL_CLAIM_KINDS

DEFAULT_CORPUS_PATH = "Documents/"

# Decision D4: the 294-page reference standard stays out by default. It is 12x
# the two process manuals the ontology was actually derived from and would
# dominate retrieval.
IT4IT_PATTERN = "IT4IT*"

# Rules whose findings represent a meta-model-vs-ontology disagreement a human
# should adjudicate, rather than an unambiguous ontology defect. Grammar
# violations and undocumented action verbs are judgement calls; a dangling
# edge is not.
DEFAULT_ADJUDICABLE_RULES = ("GRAMMAR", "ONT-005", "ONT-013-VOCAB")


@dataclass
class OntologyComplianceConfig:
    ontology_path: str = DEFAULT_ONTOLOGY_PATH
    metamodel_path: str = DEFAULT_METAMODEL_PATH
    document_corpus_path: str = DEFAULT_CORPUS_PATH

    enable_conformance: bool = True
    enable_grounding: bool = True
    severity_threshold: str = "info"
    claim_kinds: Sequence[str] = field(default_factory=lambda: list(ALL_CLAIM_KINDS))
    top_k: int = 5

    include_it4it_corpus: bool = False
    include_patterns: List[str] = field(default_factory=lambda: ["*.pdf"])
    exclude_patterns: List[str] = field(default_factory=list)
    page_range: Optional[Tuple[int, int]] = None

    enable_conflict_registry: bool = True
    conflict_db_path: str = "conflicts.db"
    adjudicable_rules: Sequence[str] = DEFAULT_ADJUDICABLE_RULES

    def effective_exclude_patterns(self) -> List[str]:
        patterns = list(self.exclude_patterns)
        if not self.include_it4it_corpus and IT4IT_PATTERN not in patterns:
            patterns.append(IT4IT_PATTERN)
        return patterns

    @classmethod
    def from_env(cls) -> "OntologyComplianceConfig":
        def _bool(name: str, default: str) -> bool:
            return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")

        config = cls()
        config.ontology_path = os.getenv("ONTO_ONTOLOGY_PATH", config.ontology_path)
        config.metamodel_path = os.getenv("ONTO_METAMODEL_PATH", config.metamodel_path)
        config.document_corpus_path = os.getenv(
            "ONTO_DOCUMENT_CORPUS_PATH", config.document_corpus_path
        )
        config.enable_conformance = _bool("ONTO_ENABLE_METAMODEL_CONFORMANCE", "true")
        config.enable_grounding = _bool("ONTO_ENABLE_ONTOLOGY_GROUNDING", "true")
        config.severity_threshold = os.getenv("ONTO_CONFORMANCE_SEVERITY_THRESHOLD", "info")
        kinds = os.getenv("ONTO_ONTOLOGY_CLAIM_KINDS")
        if kinds:
            config.claim_kinds = [k.strip() for k in kinds.split(",") if k.strip()]
        config.include_it4it_corpus = _bool("ONTO_INCLUDE_IT4IT_CORPUS", "false")
        config.enable_conflict_registry = _bool("ONTO_ENABLE_CONFLICT_REGISTRY", "true")
        config.conflict_db_path = os.getenv("ONTO_CONFLICT_DB_PATH", config.conflict_db_path)
        return config

    @classmethod
    def from_pipeline_config(cls, pipeline_config) -> "OntologyComplianceConfig":
        config = cls.from_env()
        # PipelineConfig resolves db paths relative to sqlite_path; reuse that
        # so conflicts.db lands beside feedback.db rather than in the cwd.
        config.conflict_db_path = getattr(
            pipeline_config, "conflict_db_path", config.conflict_db_path
        )
        config.enable_conflict_registry = getattr(
            pipeline_config, "enable_conflict_registry", config.enable_conflict_registry
        )
        return config
