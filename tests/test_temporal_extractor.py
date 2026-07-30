"""Temporal extraction: dates, relative expressions, and document dates."""

from datetime import datetime

import pytest

from src.ingestion import TemporalExtractor


@pytest.fixture
def extractor():
    return TemporalExtractor()


class TestExtractDates:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Approved on 2020-05-14.", datetime(2020, 5, 14)),
            ("Approved on May 14, 2020.", datetime(2020, 5, 14)),
            ("Approved on 14/5/2020.", datetime(2020, 5, 14)),
            ("Approved in 1897.", datetime(1897, 1, 1)),
        ],
    )
    def test_supported_date_formats_are_parsed(self, extractor, text, expected):
        assert extractor.extract_dates(text) == [expected]

    def test_a_full_date_is_not_also_counted_as_a_bare_year(self, extractor):
        assert extractor.extract_dates("Published 2020-05-14 by the board.") == [datetime(2020, 5, 14)]

    def test_multiple_dates_are_returned_in_chronological_order(self, extractor):
        dates = extractor.extract_dates("Used since 1897 and reviewed in 2015.")

        assert dates == [datetime(1897, 1, 1), datetime(2015, 1, 1)]

    def test_impossible_dates_are_discarded(self, extractor):
        assert extractor.extract_dates("Dated 45/13/2020.") == []

    def test_text_without_dates_yields_nothing(self, extractor):
        assert extractor.extract_dates("Aspirin treats headache.") == []


class TestTemporalExpressions:
    def test_relative_words_are_detected(self, extractor):
        found = extractor.extract_temporal_expressions("Aspirin is currently used for migraines.")

        assert found[0]["text"].lower() == "currently"
        assert found[0]["type"] == "recent"

    def test_decade_expressions_are_detected(self, extractor):
        found = extractor.extract_temporal_expressions("Widely prescribed in the 1990s.")

        assert found[0]["type"] == "decade"

    def test_years_ago_is_detected(self, extractor):
        found = extractor.extract_temporal_expressions("Approved 120 years ago.")

        assert found[0]["type"] == "relative"

    def test_expressions_are_ordered_by_position(self, extractor):
        found = extractor.extract_temporal_expressions("Currently used, and popular in the 1990s.")

        assert [f["span"][0] for f in found] == sorted(f["span"][0] for f in found)

    def test_plain_text_yields_nothing(self, extractor):
        assert extractor.extract_temporal_expressions("Aspirin treats headache.") == []


class TestDocumentDate:
    @pytest.mark.parametrize(
        "header",
        ["Published: 2020-05-14", "Updated: 2020-05-14", "Date: May 14, 2020"],
    )
    def test_document_headers_are_recognised(self, extractor, header):
        assert extractor.infer_document_date(f"{header}\n\nAspirin treats headache.") == datetime(2020, 5, 14)

    def test_no_header_yields_none(self, extractor):
        assert extractor.infer_document_date("Aspirin treats headache in 2020.") is None


class TestDescribe:
    def test_payload_carries_dates_expressions_and_document_date(self, extractor):
        payload = extractor.describe("Approved in 1897 and still used today.", datetime(2020, 1, 1))

        assert payload["mentioned_dates"] == ["1897-01-01T00:00:00"]
        assert payload["temporal_expressions"][0]["type"] == "recent"
        assert payload["document_date"] == "2020-01-01T00:00:00"

    def test_document_date_is_optional(self, extractor):
        assert extractor.describe("Aspirin treats headache.")["document_date"] is None
