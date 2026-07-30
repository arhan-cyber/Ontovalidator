"""Table extraction: one chunk per row, with headers preserved."""

import os

import pytest

from src.ingestion import TableExtractor
from src.models import ChunkType

HTML_TABLE = """
<table>
  <tr><th>Drug</th><th>Treats</th></tr>
  <tr><td>Aspirin</td><td>Headache</td></tr>
  <tr><td>Quinine</td><td>Malaria</td></tr>
</table>
"""


@pytest.fixture
def extractor():
    return TableExtractor()


class TestHtmlTables:
    def test_each_body_row_becomes_one_chunk(self, extractor):
        chunks = extractor.extract_from_html(HTML_TABLE, "t1")

        assert len(chunks) == 2
        assert all(c["type"] == ChunkType.TABLE_ROW for c in chunks)

    def test_row_text_pairs_headers_with_values(self, extractor):
        chunks = extractor.extract_from_html(HTML_TABLE, "t1")

        assert chunks[0]["text"] == "Drug: Aspirin | Treats: Headache"
        assert chunks[1]["text"] == "Drug: Quinine | Treats: Malaria"

    def test_metadata_records_the_table_position(self, extractor):
        metadata = extractor.extract_from_html(HTML_TABLE, "t1")[1]["type_metadata"]

        assert metadata["table_id"] == "t1"
        assert metadata["row_num"] == 1
        assert metadata["headers"] == ["Drug", "Treats"]
        assert metadata["values"] == {"Drug": "Quinine", "Treats": "Malaria"}

    def test_nested_markup_inside_cells_is_stripped(self, extractor):
        html = "<table><tr><th>Drug</th></tr><tr><td><b>Aspirin</b></td></tr></table>"

        assert extractor.extract_from_html(html)[0]["text"] == "Drug: Aspirin"

    def test_html_entities_are_decoded(self, extractor):
        html = "<table><tr><th>Note</th></tr><tr><td>a &amp; b</td></tr></table>"

        assert extractor.extract_from_html(html)[0]["text"] == "Note: a & b"

    def test_a_header_only_table_yields_nothing(self, extractor):
        assert extractor.extract_from_html("<table><tr><th>Drug</th></tr></table>") == []

    def test_non_table_input_yields_nothing(self, extractor):
        assert extractor.extract_from_html("<p>not a table</p>") == []
        assert extractor.extract_from_html("") == []

    def test_extra_cells_beyond_the_headers_are_still_kept(self, extractor):
        html = "<table><tr><th>A</th></tr><tr><td>1</td><td>2</td></tr></table>"

        chunk = extractor.extract_from_html(html)[0]
        assert chunk["text"] == "A: 1 | column_1: 2"

    def test_table_id_is_generated_when_omitted(self, extractor):
        assert extractor.extract_from_html(HTML_TABLE)[0]["type_metadata"]["table_id"].startswith("table_")


class TestCsvTables:
    def test_csv_text_becomes_row_chunks(self, extractor):
        chunks = extractor.extract_from_csv_text("Drug,Treats\nAspirin,Headache\n", "csv1")

        assert len(chunks) == 1
        assert chunks[0]["text"] == "Drug: Aspirin | Treats: Headache"
        assert chunks[0]["type_metadata"]["table_id"] == "csv1"

    def test_blank_lines_are_ignored(self, extractor):
        chunks = extractor.extract_from_csv_text("Drug,Treats\n\nAspirin,Headache\n\n", "csv1")

        assert len(chunks) == 1

    def test_csv_file_is_read_from_disk(self, extractor, tmp_workspace):
        path = os.path.join(tmp_workspace, "drugs.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Drug,Treats\nAspirin,Headache\n")

        assert extractor.extract_from_csv(path)[0]["text"] == "Drug: Aspirin | Treats: Headache"
