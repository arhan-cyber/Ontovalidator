"""Plane A — static conformance of the ontology against its meta-model.

Deterministic graph and schema checking: no documents, no models, no network.
Every check is a :class:`~.registry.ConformanceRule` in one
:class:`~.registry.SystemicRuleRegistry`, which is the single authority over
the rule set — the union of the meta-model's ONT-* list and the ontology's,
plus the schema, grammar and self-consistency checks that no ONT-* rule
covers.

Typical use::

    from src.ontology import load_metamodel, load_ontology
    from src.ontology.conformance import run_conformance

    findings = run_conformance(load_ontology(), load_metamodel())

See `docs/ONTOLOGY_COMPLIANCE_PLAN.md` §5 for which rules are real static
properties and which are proxies for runtime ones.
"""

from typing import List, Optional

from ..models import (
    CheckType,
    ConformanceFinding,
    MetaModel,
    OntologyGraph,
    Severity,
    SubjectKind,
)
from .consistency import consistency_rules
from .grammar import grammar_rules
from .registry import (
    ConformanceConfig,
    ConformanceRule,
    RuleContext,
    SystemicRuleRegistry,
)
from .schema import schema_rules
from .systemic import systemic_rules


def build_registry() -> SystemicRuleRegistry:
    """A registry holding every Phase 1 check, in report order.

    Schema first, then the grammar, then the ONT-* rules, then the
    self-consistency checks — roughly widening scope, so a report read top to
    bottom starts with the nodes and ends with the file.
    """
    registry = SystemicRuleRegistry()
    registry.register_all(schema_rules())
    registry.register_all(grammar_rules())
    registry.register_all(systemic_rules())
    registry.register_all(consistency_rules())
    return registry


# Rules are stateless, so one shared registry is enough and keeps rule
# identity stable across runs (the conflict registry keys on rule_id).
_DEFAULT_REGISTRY: Optional[SystemicRuleRegistry] = None


def default_registry() -> SystemicRuleRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_registry()
    return _DEFAULT_REGISTRY


def run_conformance(
    ontology: OntologyGraph,
    metamodel: MetaModel,
    config: Optional[ConformanceConfig] = None,
    registry: Optional[SystemicRuleRegistry] = None,
) -> List[ConformanceFinding]:
    """Run every registered check and return the findings, worst-first by rule.

    Findings are ordered deterministically so two runs over the same inputs
    produce byte-identical output — the golden baseline depends on it.
    """
    context = RuleContext(
        ontology=ontology,
        metamodel=metamodel,
        config=config or ConformanceConfig(),
    )
    return (registry or default_registry()).run(context)


__all__ = [
    "CheckType",
    "ConformanceConfig",
    "ConformanceFinding",
    "ConformanceRule",
    "RuleContext",
    "Severity",
    "SubjectKind",
    "SystemicRuleRegistry",
    "build_registry",
    "default_registry",
    "run_conformance",
]
