"""The edge grammar: which kinds of node may legally connect to which.

One thing to get right here, and it is the whole file: membership is tested
against a node's **kind set**, not its meta-class. The blueprint writes
`performs` in meta-class terms (`Actor_Class -> Activity_Class`) and
`has_lifecycle_phase` in attribute-type terms (`Core Activity -> Domain
Activity`), in the same list, with no marker distinguishing the two
vocabularies. :meth:`OntologyGraph.kinds_of` returns the union, so both styles
resolve against the same set. Test `meta_class` alone and every type-phrased
rule fires spuriously; test `attributes.type` alone and every meta-class-phrased
rule does. Either way the violation count is wrong in both directions.

Per decision D1 the meta-model wins and the finding is filed against the
ontology — but a grammar violation is not automatically an ontology defect.
Three of V4's six are arguably gaps in the blueprint (`Cloud Watch` really is
an external system). Phase 1b routes these to the conflict registry for human
adjudication; the finding here carries the observed-versus-required shapes it
needs to do that.
"""

import logging
from typing import Iterable, List

from ..models import ConformanceFinding, Severity, SubjectKind
from .registry import ConformanceRule, RuleContext

logger = logging.getLogger(__name__)


class EdgeGrammarRule(ConformanceRule):
    """Every edge's endpoints must be kinds the edge type permits."""

    rule_id = "GRAMMAR"
    title = "Edge grammar conformance"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for edge in ctx.ontology.edges:
            rule = ctx.metamodel.edge_rules.get(edge.type)
            if rule is None:
                # An edge type the blueprint never declared has no grammar to
                # violate; CONSISTENCY-UNKNOWN-EDGE reports it once.
                continue
            source_kinds = ctx.ontology.kinds_of(edge.source)
            target_kinds = ctx.ontology.kinds_of(edge.target)
            if not source_kinds or not target_kinds:
                # A dangling endpoint has no kinds, which would make every
                # such edge look like a grammar violation. Reported once, as
                # what it is, by CONSISTENCY-DANGLING-EDGE.
                continue

            problems: List[str] = []
            if not source_kinds & rule.valid_from:
                problems.append(
                    f"source {edge.source!r} is {self._render(source_kinds)}, "
                    f"but valid_from is {self._render(rule.valid_from)}"
                )
            if not target_kinds & rule.valid_to:
                problems.append(
                    f"target {edge.target!r} is {self._render(target_kinds)}, "
                    f"but valid_to is {self._render(rule.valid_to)}"
                )
            if not problems:
                continue

            yield self.finding(
                SubjectKind.EDGE,
                edge.key,
                f"edge {edge} violates the {edge.type!r} grammar: {'; '.join(problems)}",
                evidence=(
                    f"observed {self._render(source_kinds)} --{edge.type}--> "
                    f"{self._render(target_kinds)}; required "
                    f"{self._render(rule.valid_from)} --{edge.type}--> "
                    f"{self._render(rule.valid_to)}"
                ),
                remediation=(
                    "either retype an endpoint, or adjudicate as a meta-model gap "
                    "and widen the grammar row"
                ),
                metadata={
                    "edge_type": edge.type,
                    "source": edge.source,
                    "target": edge.target,
                    "observed_from": sorted(source_kinds),
                    "observed_to": sorted(target_kinds),
                    "valid_from": sorted(rule.valid_from),
                    "valid_to": sorted(rule.valid_to),
                    # Which end to widen if this is adjudicated a meta-model
                    # gap. Consumed by ConflictRegistry.proposed_amendments.
                    "violating_ends": (
                        (["valid_from"] if not source_kinds & rule.valid_from else [])
                        + (["valid_to"] if not target_kinds & rule.valid_to else [])
                    ),
                },
            )

    @staticmethod
    def _render(kinds: Iterable[str]) -> str:
        return "{" + ", ".join(sorted(kinds)) + "}"


def grammar_rules() -> List[ConformanceRule]:
    return [EdgeGrammarRule()]
