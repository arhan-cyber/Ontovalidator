"""Enterprise ontology compliance validation.

Two independent planes, deliberately kept separate:

* **structural conformance** — does the ontology conform to its meta-model?
  Deterministic graph and schema checking, no documents, no models.
* **evidential grounding** — are the ontology's claims supported by the source
  documents? Runs on the existing retrieval and adjudication engine.

See `docs/ONTOLOGY_COMPLIANCE_PLAN.md`.
"""

from .loader import (
    DEFAULT_METAMODEL_PATH,
    DEFAULT_ONTOLOGY_PATH,
    OntologyInputError,
    load_metamodel,
    load_ontology,
    merge_systemic_rules,
)
from .models import (
    AgentRules,
    ConformanceFinding,
    EdgeRule,
    MetaClassSpec,
    MetaModel,
    OntologyEdge,
    OntologyGraph,
    OntologyNode,
    Severity,
    SubjectKind,
    SystemicRuleSpec,
    normalize_attr_list,
)

__all__ = [
    "AgentRules",
    "ConformanceFinding",
    "DEFAULT_METAMODEL_PATH",
    "DEFAULT_ONTOLOGY_PATH",
    "EdgeRule",
    "MetaClassSpec",
    "MetaModel",
    "OntologyEdge",
    "OntologyGraph",
    "OntologyInputError",
    "OntologyNode",
    "Severity",
    "SubjectKind",
    "SystemicRuleSpec",
    "load_metamodel",
    "load_ontology",
    "merge_systemic_rules",
    "normalize_attr_list",
]
