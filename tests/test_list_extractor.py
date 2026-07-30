"""List extraction: bullets, numbers, and letters become their own chunks."""

import pytest

from src.ingestion import ListExtractor
from src.models import ChunkType


@pytest.fixture
def extractor():
    return ListExtractor()


class TestListExtraction:
    @pytest.mark.parametrize(
        "line,expected",
        [
            ("- Aspirin treats headache", "Aspirin treats headache"),
            ("* Aspirin treats headache", "Aspirin treats headache"),
            ("• Aspirin treats headache", "Aspirin treats headache"),
            ("1. Aspirin treats headache", "Aspirin treats headache"),
            ("2) Aspirin treats headache", "Aspirin treats headache"),
            ("a) Aspirin treats headache", "Aspirin treats headache"),
        ],
    )
    def test_common_list_markers_are_recognised(self, extractor, line, expected):
        chunks = extractor.extract_from_text(line)

        assert len(chunks) == 1
        assert chunks[0]["text"] == expected
        assert chunks[0]["type"] == ChunkType.LIST_ITEM

    def test_each_item_of_a_list_is_its_own_chunk(self, extractor):
        text = "Uses:\n- treats headache\n- reduces fever\n- relieves pain"

        chunks = extractor.extract_from_text(text)
        assert [c["text"] for c in chunks] == ["treats headache", "reduces fever", "relieves pain"]

    def test_prose_produces_no_chunks(self, extractor):
        text = "Aspirin treats headache. It also reduces fever."

        assert extractor.extract_from_text(text) == []

    def test_leading_whitespace_is_tolerated(self, extractor):
        assert extractor.extract_from_text("    - indented item")[0]["text"] == "indented item"

    def test_metadata_records_the_original_line_and_style(self, extractor):
        metadata = extractor.extract_from_text("Uses:\n1. treats headache")[0]["type_metadata"]

        assert metadata["original_line"] == "1. treats headache"
        assert metadata["line_num"] == 1
        assert metadata["list_style"] == "numbered"

    def test_a_marker_with_no_content_is_skipped(self, extractor):
        assert extractor.extract_from_text("- \n-  ") == []

    def test_empty_input_is_handled(self, extractor):
        assert extractor.extract_from_text("") == []
        assert extractor.extract_from_text(None) == []
