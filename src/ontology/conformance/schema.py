"""Meta-class schema checks and the ONT-013 agent-rule contract.

Three questions, in widening order:

1. does every node name a meta-class the blueprint actually declares?
2. does it carry that meta-class's mandatory attributes, with values drawn
   from the enumerations where the blueprint enumerates?
3. does its `agent_rules` block satisfy `Agent_Rules_Schema` — the contract
   ONT-013 exists to enforce?

The presence check and the value check deliberately ask different things of
the same attribute. `"input": ["null"]` *has* the key, so the meta-class is
satisfied; it has no value, so ONT-001 is not. That is
:meth:`OntologyNode.has_attr_key` versus :meth:`OntologyNode.attr`, and
conflating them makes one of the two checks vacuous.
"""

import collections
import logging
from typing import Dict, Iterable, List

from ..models import ConformanceFinding, Severity, SubjectKind
from .registry import ConformanceRule, RuleContext

logger = logging.getLogger(__name__)


class MetaClassKnownRule(ConformanceRule):
    """Every node's `meta_class` must be one the blueprint declares."""

    rule_id = "SCHEMA-META-CLASS"
    title = "Meta-class is declared in the blueprint"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        known = set(ctx.metamodel.meta_classes)
        for node in ctx.ontology.nodes.values():
            if node.meta_class in known:
                continue
            yield self.finding(
                SubjectKind.NODE,
                node.id,
                f"meta_class {node.meta_class!r} is not declared in the meta-model",
                evidence=f"declared meta-classes: {', '.join(sorted(known))}",
                remediation="retype the node, or add the meta-class to the blueprint",
            )


class MandatoryAttributesRule(ConformanceRule):
    """Every mandatory attribute key of the node's meta-class must be present.

    Presence only — a `["null"]` value satisfies this rule. Whether that null
    is acceptable is a question for the rule that reads the attribute
    (ONT-001, for the SIPOC fields).
    """

    rule_id = "SCHEMA-ATTR"
    title = "Mandatory meta-class attributes present"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.ontology.nodes.values():
            spec = ctx.metamodel.meta_classes.get(node.meta_class)
            if spec is None:
                continue  # reported by SCHEMA-META-CLASS
            missing = [name for name in spec.mandatory_attributes if not node.has_attr_key(name)]
            if not missing:
                continue
            yield self.finding(
                SubjectKind.NODE,
                node.id,
                f"{node.meta_class} requires attributes not present on this node: "
                f"{', '.join(sorted(missing))}",
                evidence=f"attributes present: {', '.join(sorted(node.attributes)) or '(none)'}",
                remediation=f"add {', '.join(sorted(missing))} to attributes",
            )


class EnumeratedAttributeRule(ConformanceRule):
    """Enumerated attribute values must come from the blueprint's list.

    Covers `type` on every meta-class and `classification` on Decision_Class.
    An enumerated attribute that is present but empty (`["null"]`) is also a
    violation: an unset `type` leaves the node outside the edge grammar
    entirely, since kind-set membership is what the grammar tests.
    """

    rule_id = "SCHEMA-TYPE"
    title = "Enumerated attribute values are in range"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.ontology.nodes.values():
            spec = ctx.metamodel.meta_classes.get(node.meta_class)
            if spec is None:
                continue
            for name, attr_spec in spec.mandatory_attributes.items():
                if not attr_spec.is_enumerated or not node.has_attr_key(name):
                    continue
                allowed = attr_spec.allowed_values or set()
                values = node.attr(name)
                if not values:
                    yield self.finding(
                        SubjectKind.NODE,
                        node.id,
                        f"attribute {name!r} is enumerated but carries no value",
                        evidence=f"raw value: {node.attributes.get(name)!r}",
                        remediation=f"set {name} to one of: {', '.join(sorted(allowed))}",
                    )
                    continue
                for value in values:
                    if value in allowed:
                        continue
                    yield self.finding(
                        SubjectKind.NODE,
                        node.id,
                        f"attribute {name!r} has value {value!r}, which "
                        f"{node.meta_class} does not permit",
                        evidence=f"permitted: {', '.join(sorted(allowed))}",
                        remediation=f"use one of the permitted {name} values",
                    )


class AgentRuleContractRule(ConformanceRule):
    """ONT-013 — full `Agent_Rules_Schema` conformance.

    Four clauses, checked independently so a node failing one still gets
    reported against the others:

    * the block exists where the meta-class mandates it;
    * `precondition` / `delegation` / `execution` / `postcondition` are all
      present;
    * `precondition.on_fail` is one of the blueprint's enumerated values —
      the most common defect in V4 by an order of magnitude;
    * `execution` and `postcondition` name only documented actions.

    The action check reports **per distinct action, not per use**. Thirteen
    `fill_missing_value` calls are one undocumented verb used thirteen times;
    one line per call would drown the on_fail findings and imply thirteen
    independent fixes when there is one.
    """

    rule_id = "ONT-013"
    title = "Agent Rule Contract"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        schema = ctx.metamodel.agent_rules_schema
        findings: List[ConformanceFinding] = []

        # action name -> node ids using it
        undocumented_exec: Dict[str, List[str]] = collections.defaultdict(list)
        undocumented_post: Dict[str, List[str]] = collections.defaultdict(list)

        for node in ctx.ontology.nodes.values():
            spec = ctx.metamodel.meta_classes.get(node.meta_class)
            requires = spec.requires_agent_rules if spec else False

            if node.agent_rules is None:
                if requires:
                    findings.append(self.finding(
                        SubjectKind.NODE,
                        node.id,
                        f"{node.meta_class} mandates agent_rules, but the node has none",
                        remediation="add an agent_rules block conforming to Agent_Rules_Schema",
                    ))
                # Nothing further to say about a block that isn't there.
                continue

            rules = node.agent_rules

            missing_sections = sorted(schema.required_sections - rules.sections)
            if missing_sections:
                findings.append(self.finding(
                    SubjectKind.NODE,
                    node.id,
                    f"agent_rules is missing required sections: {', '.join(missing_sections)}",
                    evidence=f"present: {', '.join(sorted(rules.sections)) or '(none)'}",
                    remediation="add the missing sections, even if empty",
                ))

            if schema.on_fail_allowed and rules.on_fail not in schema.on_fail_allowed:
                findings.append(self.finding(
                    SubjectKind.NODE,
                    node.id,
                    f"precondition.on_fail is {rules.on_fail!r}, "
                    f"which is not one of the permitted values",
                    evidence=f"permitted: {', '.join(sorted(schema.on_fail_allowed))}",
                    remediation="set on_fail to 'skip' or 'block'; null is not a decision",
                ))

            for action in rules.execution_actions:
                if schema.execution_actions and action not in schema.execution_actions:
                    undocumented_exec[action].append(node.id)
            for action in rules.postcondition_actions:
                if schema.postcondition_actions and action not in schema.postcondition_actions:
                    undocumented_post[action].append(node.id)

        findings.extend(self._action_findings(
            ctx, undocumented_exec, "execution", sorted(schema.execution_actions),
            schema.execution_vocabulary_open,
        ))
        findings.extend(self._action_findings(
            ctx, undocumented_post, "postcondition", sorted(schema.postcondition_actions),
            schema.postcondition_vocabulary_open,
        ))
        return findings

    def _action_findings(
        self,
        ctx: RuleContext,
        used: Dict[str, List[str]],
        section: str,
        vocabulary: List[str],
        vocabulary_open: bool,
    ) -> Iterable[ConformanceFinding]:
        """Report action verbs the blueprint doesn't name.

        Reported under `ONT-013-VOCAB` at `warning` when the blueprint states
        the vocabulary with "e.g." - which it does for both `execution` and
        `postcondition`. An abbreviation meaning "for example" cannot carry
        the weight of a hard error, and V4's seven extra verbs
        (`evaluate_decision` and `halt` among them) are far more likely to be
        a blueprint that was never finished than seven deliberate violations.
        Separating the id also keeps them adjudicable on their own in the
        conflict registry, where `metamodel_gap` is the likely verdict.

        Reported per distinct action, not per use. Thirteen
        `fill_missing_value` calls are one undocumented verb used thirteen
        times, not thirteen independent fixes.
        """
        severity = Severity.WARNING if vocabulary_open else Severity.ERROR
        rule_id = "ONT-013-VOCAB" if vocabulary_open else None
        qualifier = (
            "is not among the examples given in"
            if vocabulary_open
            else "is not permitted by"
        )
        # Most-used first: the verb with the widest blast radius is the one
        # worth documenting first.
        for action, nodes in sorted(used.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            yield self.finding(
                SubjectKind.GRAPH,
                action,
                f"{section} action {action!r} is used {len(nodes)} time(s) but "
                f"{qualifier} Agent_Rules_Schema",
                evidence=f"used by: {ctx.sample(nodes)}; documented: {', '.join(vocabulary)}",
                remediation=(
                    f"add {action!r} to the Agent_Rules_Schema {section} vocabulary, "
                    f"or replace its uses with a documented action"
                ),
                severity=severity,
                rule_id=rule_id,
            )


def schema_rules() -> List[ConformanceRule]:
    return [
        MetaClassKnownRule(),
        MandatoryAttributesRule(),
        EnumeratedAttributeRule(),
        AgentRuleContractRule(),
    ]
