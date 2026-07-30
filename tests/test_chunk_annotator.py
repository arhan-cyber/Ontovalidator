"""Chunk annotation: HTML markup, negation analysis, and component matches."""

import re

import pytest

from src.annotation.annotator import ChunkAnnotator
from src.models import EvidenceSpan, OntologyAssertion


@pytest.fixture
def annotator():
    return ChunkAnnotator()


@pytest.fixture
def assertion():
    return OntologyAssertion(
        assertion_id="t1",
        subject="Aspirin",
        relation="treats",
        object="headache",
    )


def span(text, support_type="supports", subject=True, relation=True, obj=True):
    return EvidenceSpan(
        chunk_id="c1",
        text=text,
        source="fusion",
        support_type=support_type,
        confidence=0.9,
        matched_subject=subject,
        matched_relation=relation,
        matched_object=obj,
    )


class TestAnnotatedHtml:
    def test_each_component_is_marked_with_its_own_class(self, annotator, assertion):
        text = "Aspirin treats headache in adults."
        html = annotator.annotate(text, assertion, span(text))["annotated_html"]

        assert "<mark class='subject'>Aspirin</mark>" in html
        assert "<mark class='relation'>treats</mark>" in html
        assert "<mark class='object'>headache</mark>" in html

    def test_matching_is_case_insensitive_and_preserves_original_casing(self, annotator, assertion):
        text = "ASPIRIN Treats headache."
        html = annotator.annotate(text, assertion, span(text))["annotated_html"]

        assert "<mark class='subject'>ASPIRIN</mark>" in html
        assert "<mark class='relation'>Treats</mark>" in html

    def test_markup_is_balanced(self, annotator, assertion):
        text = "Aspirin treats headache and Aspirin treats fever."
        html = annotator.annotate(text, assertion, span(text))["annotated_html"]

        assert html.count("<mark") == html.count("</mark>")
        assert html.startswith("<p>") and html.endswith("</p>")

    def test_chunk_text_is_html_escaped(self, annotator, assertion):
        text = "Aspirin treats headache <script>alert(1)</script>"
        html = annotator.annotate(text, assertion, span(text))["annotated_html"]

        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_stripping_tags_recovers_the_original_text(self, annotator, assertion):
        text = "Aspirin treats headache in adults."
        html = annotator.annotate(text, assertion, span(text))["annotated_html"]

        assert re.sub(r"<[^>]+>", "", html) == text

    def test_absent_components_are_simply_not_marked(self, annotator, assertion):
        text = "Paracetamol is an analgesic."
        html = annotator.annotate(text, assertion, span(text, subject=False, relation=False, obj=False))["annotated_html"]

        assert "<mark" not in html

    def test_substring_of_a_longer_word_is_not_marked(self, annotator):
        assertion = OntologyAssertion(assertion_id="t", subject="pin", relation="treats", object="pain")
        text = "Aspirin treats pain."
        html = annotator.annotate(text, assertion, span(text))["annotated_html"]

        assert "<mark class='subject'>" not in html
        assert "<mark class='object'>pain</mark>" in html


class TestNegationAnalysis:
    def test_negation_keyword_and_scope_are_reported(self, annotator, assertion):
        text = "Aspirin does not treat malaria; it treats headache."
        analysis = annotator.annotate(text, assertion, span(text, support_type="refutes"))["negation_analysis"]

        assert analysis["negation_detected"] is True
        assert "does not" in analysis["negation_keywords"]
        assert analysis["negation_scope"][0] == "treat malaria"

    def test_clean_text_reports_no_negation(self, annotator, assertion):
        text = "Aspirin treats headache."
        analysis = annotator.annotate(text, assertion, span(text))["negation_analysis"]

        assert analysis["negation_detected"] is False
        assert analysis["negation_keywords"] == []

    def test_longer_keyword_wins_over_its_prefix(self, annotator, assertion):
        text = "Aspirin does not treat malaria."
        analysis = annotator.annotate(text, assertion, span(text, support_type="refutes"))["negation_analysis"]

        assert analysis["negation_keywords"] == ["does not"]


class TestComponentMatches:
    def test_flags_come_from_the_classifier_verdict(self, annotator, assertion):
        text = "Aspirin is an analgesic."
        result = annotator.annotate(
            text, assertion, span(text, support_type="partial", relation=False, obj=False)
        )

        assert result["component_matches"] == {"subject": True, "relation": False, "object": False}

    def test_flags_fall_back_to_the_heuristic_without_a_span(self, annotator, assertion):
        result = annotator.annotate("Aspirin treats headache.", assertion)

        assert result["component_matches"] == {"subject": True, "relation": True, "object": True}
