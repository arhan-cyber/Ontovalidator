"""The rule registry and the plumbing every conformance check shares.

A checker's job is to answer one question about the ontology and hand back
findings. Everything *around* that answer — which severity it carries, whether
the rule should fire at all, whether the governed meta-class even has
instances — is decided here, once, for every rule.

That split matters most for **severity degradation** (decision D2). V4 is a
work in progress: it has zero `Outcome_Class` instances, so rules that govern
Outcomes have nothing to be right or wrong about and report as warnings rather
than errors. A rule declares that with :attr:`ConformanceRule.degrades_when_empty`
and the registry applies it. Bury the same logic inside the checkers and the
day Outcome nodes land, someone has to remember to go delete it from each one;
declared here, the rules re-escalate to `error` on their own.
"""

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

from ..models import (
    CheckType,
    ConformanceFinding,
    MetaModel,
    OntologyGraph,
    Severity,
    SubjectKind,
    severity_at_least,
)

logger = logging.getLogger(__name__)

# One step down the ladder. `info` is the floor — a degraded rule still gets
# to say something, it just stops claiming the ontology is broken.
_DEMOTION = {
    Severity.ERROR: Severity.WARNING,
    Severity.WARNING: Severity.INFO,
    Severity.INFO: Severity.INFO,
}


@dataclass
class ConformanceConfig:
    """Knobs for one conformance run.

    `severity_threshold` filters the *returned* findings, not the work done —
    every rule still runs, so a downstream caller that wants the full set can
    re-run without the threshold instead of re-deriving it.
    """

    severity_threshold: Optional[Severity] = None
    include_rules: Optional[Set[str]] = None
    exclude_rules: Set[str] = field(default_factory=set)
    # The ONT-* lists in the two files disagree (finding 7). Reporting that is
    # on by default; a caller comparing two revisions of the same file pair
    # may not care.
    report_ruleset_skew: bool = True
    # Cap on how many examples a graph-level finding names in its evidence.
    max_evidence_items: int = 8


@dataclass
class RuleContext:
    """Everything a checker is allowed to look at."""

    ontology: OntologyGraph
    metamodel: MetaModel
    config: ConformanceConfig = field(default_factory=ConformanceConfig)

    def nodes_of_kind(self, kind: str) -> List[Any]:
        """Nodes answering to `kind`, whether it names a meta-class or a type."""
        return [n for n in self.ontology.nodes.values() if kind in n.kinds]

    def sample(self, items: Sequence[Any]) -> str:
        """Render up to `max_evidence_items` examples, with an overflow count."""
        limit = self.config.max_evidence_items
        shown = [str(i) for i in items[:limit]]
        if len(items) > limit:
            shown.append(f"... (+{len(items) - limit} more)")
        return ", ".join(shown)


class ConformanceRule:
    """Base class for every check, ONT-* or otherwise.

    Subclasses set the class attributes and implement :meth:`check`. They
    build findings through :meth:`finding`, which stamps the registered
    `rule_id` and severity on — so a checker never has to know, or restate,
    how severely its own failures are taken.
    """

    rule_id: str = ""
    title: str = ""
    severity: Severity = Severity.ERROR
    check_type: CheckType = CheckType.STATIC
    # Meta-class or attribute-type names. Zero instances of any one of them
    # and this rule's findings are demoted one step and marked `degraded`.
    degrades_when_empty: Tuple[str, ...] = ()

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        raise NotImplementedError

    def finding(
        self,
        subject_kind: SubjectKind,
        subject_id: str,
        message: str,
        evidence: Optional[str] = None,
        remediation: Optional[str] = None,
        severity: Optional[Severity] = None,
        rule_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ConformanceFinding:
        # `rule_id` lets one checker emit findings under a sub-id when the
        # blueprint states parts of its contract at different strengths - see
        # ONT-013 vs ONT-013-VOCAB.
        return ConformanceFinding(
            rule_id=rule_id or self.rule_id,
            severity=severity or self.severity,
            subject_kind=subject_kind,
            subject_id=subject_id,
            message=message,
            evidence=evidence,
            remediation=remediation,
            metadata=metadata,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {self.rule_id} {self.severity.value}>"


class SystemicRuleRegistry:
    """The single authority over the rule set (decision D3).

    Keyed by `rule_id` and ordered by registration, so a report reads in the
    order the rules were declared rather than in dictionary-hash order.
    """

    def __init__(self) -> None:
        self._rules: Dict[str, ConformanceRule] = {}

    def register(self, rule: ConformanceRule) -> ConformanceRule:
        if not rule.rule_id:
            raise ValueError(f"{type(rule).__name__} has no rule_id")
        if rule.rule_id in self._rules:
            raise ValueError(f"duplicate rule_id {rule.rule_id!r} in registry")
        self._rules[rule.rule_id] = rule
        return rule

    def register_all(self, rules: Iterable[ConformanceRule]) -> None:
        for rule in rules:
            self.register(rule)

    def get(self, rule_id: str) -> Optional[ConformanceRule]:
        return self._rules.get(rule_id)

    def rule_ids(self) -> List[str]:
        return list(self._rules)

    def __iter__(self) -> Iterator[ConformanceRule]:
        return iter(self._rules.values())

    def __len__(self) -> int:
        return len(self._rules)

    def __contains__(self, rule_id: object) -> bool:
        return rule_id in self._rules

    def _selected(self, rule: ConformanceRule, config: ConformanceConfig) -> bool:
        if config.include_rules is not None and rule.rule_id not in config.include_rules:
            return False
        return rule.rule_id not in config.exclude_rules

    def _degraded_kinds(self, rule: ConformanceRule, ontology: OntologyGraph) -> List[str]:
        return [k for k in rule.degrades_when_empty if not ontology.has_instances_of(k)]

    def run(self, ctx: RuleContext) -> List[ConformanceFinding]:
        """Run every selected rule, apply degradation, then filter and sort."""
        findings: List[ConformanceFinding] = []

        for rule in self._rules.values():
            if not self._selected(rule, ctx.config):
                logger.debug("rule %s deselected by config", rule.rule_id)
                continue
            try:
                produced = list(rule.check(ctx) or [])
            except Exception:
                # One broken checker must not cost us the other twenty-odd.
                # Surfaced as a finding rather than only a log line, so a
                # silently-crashing rule can't read as a clean pass.
                logger.exception("conformance rule %s raised", rule.rule_id)
                produced = [
                    rule.finding(
                        SubjectKind.GRAPH,
                        rule.rule_id,
                        f"rule {rule.rule_id} failed to run",
                        evidence="see logs for the traceback",
                        remediation="fix the checker; its result is unknown, not clean",
                        severity=Severity.ERROR,
                    )
                ]

            empty = self._degraded_kinds(rule, ctx.ontology)
            if empty and produced:
                note = f"severity reduced: the ontology has no {', '.join(empty)} instances"
                produced = [
                    replace(
                        f,
                        severity=_DEMOTION[f.severity],
                        degraded=True,
                        evidence=f"{f.evidence}; {note}" if f.evidence else note,
                    )
                    for f in produced
                ]
            findings.extend(produced)

        threshold = ctx.config.severity_threshold
        if threshold is not None:
            findings = [f for f in findings if severity_at_least(f.severity, threshold)]

        # Deterministic order: the golden baseline compares finding lists.
        findings.sort(key=lambda f: (f.rule_id, f.subject_kind.value, f.subject_id, f.message))
        return findings
