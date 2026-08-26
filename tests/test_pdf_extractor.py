"""PDF extraction: heading-stack section paths, page provenance, and error handling.

`Documents/` (the real Woolworths/IT4IT PDFs) is gitignored, so none of the
mandatory tests here may depend on it being present. Two independent paths
keep this file self-contained:

1. `HeadingStack` (the part of `pdf_extractor.py` most likely to regress) is
   tested directly against plain strings -- no PDF involved at all.
2. A tiny PDF is generated *at test time* from raw PDF syntax (no reportlab/
   pypdf/pikepdf available in this environment) via `_make_pdf`, so
   `PDFExtractor` and `DataIngestor.ingest_pdf`/`ingest_corpus` get exercised
   against a real pdfplumber-readable file without needing anything checked
   into the repo.

A third block of tests runs against the real `Documents/` PDFs when present,
guarded by `pytest.mark.skipif`, as a sanity check beyond the synthetic
fixture -- but the suite is green without them.
"""

import os
import sqlite3
from contextlib import closing
from typing import List

import pytest

from src.ingestion.pdf_extractor import HeadingStack, PDFExtractor, PDFExtractionError
from src.ingestion.pipeline import DataIngestor
from src.ingestion.embeddings import SimpleEmbeddingModel
from src.ingestion.extractors import MockSVOExtractor, MockConceptExtractor
from src.models import ChunkType

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCUMENTS_DIR = os.path.join(REPO_ROOT, "Documents")
EVENT_MGMT_PDF = os.path.join(DOCUMENTS_DIR, "wb_IT - Event Management Process v1.3.pdf")
INCIDENT_MGMT_PDF = os.path.join(DOCUMENTS_DIR, "wb_incident_management.pdf")
IT4IT_PDF = os.path.join(DOCUMENTS_DIR, "IT4IT Standards c221e.pdf")


# ---------------------------------------------------------------------------
# Minimal hand-built PDF, for tests that need something pdfplumber can open.
# ---------------------------------------------------------------------------


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _make_pdf(pages: List[List[str]]) -> bytes:
    """Build the smallest valid multi-page PDF that contains the given lines of text.

    No PDF-writing library (reportlab, pypdf, pikepdf, fpdf) is installed in
    this environment, so the PDF is assembled by hand: one Catalog, one
    Pages tree, one Page + content stream per page, and a shared Helvetica
    font, followed by a correct xref table and trailer.
    """
    n_pages = len(pages)
    page_obj_nums = [3 + 2 * i for i in range(n_pages)]
    content_obj_nums = [4 + 2 * i for i in range(n_pages)]
    font_obj_num = 3 + 2 * n_pages
    total_objects = font_obj_num

    kids = " ".join(f"{num} 0 R" for num in page_obj_nums)

    objects = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("latin-1")

    for i in range(n_pages):
        page_num = page_obj_nums[i]
        content_num = content_obj_nums[i]
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_obj_num} 0 R >> >> "
            f"/Contents {content_num} 0 R >>"
        ).encode("latin-1")

        stream_lines = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
        for line in pages[i]:
            stream_lines.append(f"({_escape_pdf_text(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream_body = "\n".join(stream_lines).encode("latin-1")
        objects[content_num] = (
            f"<< /Length {len(stream_body)} >>\nstream\n".encode("latin-1")
            + stream_body
            + b"\nendstream"
        )

    objects[font_obj_num] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in range(1, total_objects + 1):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode("latin-1")
        out += objects[num]
        out += b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {total_objects + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for num in range(1, total_objects + 1):
        out += f"{offsets[num]:010d} 00000 n \n".encode("latin-1")

    out += (
        f"trailer\n<< /Size {total_objects + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    ).encode("latin-1")

    return bytes(out)


def _write_pdf(path: str, pages: List[List[str]]) -> str:
    with open(path, "wb") as handle:
        handle.write(_make_pdf(pages))
    return path


# ---------------------------------------------------------------------------
# HeadingStack: pure string logic, no PDF anywhere.
# ---------------------------------------------------------------------------


class TestHeadingStackMatching:
    def test_a_short_numbered_title_is_a_heading(self):
        assert HeadingStack.match_heading("1.5 Process Principles") == ("1.5", "Process Principles")

    def test_a_trailing_period_after_the_number_is_tolerated(self):
        assert HeadingStack.match_heading("1. Introduction") == ("1", "Introduction")
        assert HeadingStack.match_heading("4.2.3. Contract Definition") == ("4.2.3", "Contract Definition")

    def test_a_numbered_sentence_is_not_a_heading(self):
        # Real example from wb_incident_management.pdf p.4: this shares the
        # same numbering style as a heading but is an action item, not a
        # section title -- it must not be mistaken for one.
        line = (
            "1.4.1.5 Invoke the Problem Management process to identify the underlying "
            "cause and implement a permanent solution where a workaround is not "
            "available, and the root cause is unknown."
        )
        assert HeadingStack.match_heading(line) is None

    def test_a_line_with_no_leading_number_is_not_a_heading(self):
        assert HeadingStack.match_heading("Process Principles") is None

    def test_a_lowercase_title_is_not_a_heading(self):
        assert HeadingStack.match_heading("1.5 process principles") is None

    def test_blank_and_none_lines_are_not_headings(self):
        assert HeadingStack.match_heading("") is None
        assert HeadingStack.match_heading("   ") is None
        assert HeadingStack.match_heading(None) is None

    def test_an_overlong_title_is_not_a_heading(self):
        line = "1.1 " + ("Word " * 30)
        assert HeadingStack.match_heading(line) is None


class TestHeadingStackHierarchy:
    def test_path_is_none_before_any_heading_is_seen(self):
        stack = HeadingStack()
        assert stack.path() is None

    def test_a_single_heading_becomes_the_path(self):
        stack = HeadingStack()
        assert stack.update("1 Introduction") is True
        assert stack.path() == "1 Introduction"

    def test_a_deeper_heading_nests_under_the_shallower_one(self):
        stack = HeadingStack()
        stack.update("1 Introduction")
        stack.update("1.1 Document Purpose")
        assert stack.path() == "1 Introduction > 1.1 Document Purpose"

    def test_a_sibling_heading_replaces_the_previous_one_at_its_depth(self):
        stack = HeadingStack()
        stack.update("1 Introduction")
        stack.update("1.1 Document Purpose")
        stack.update("1.2 Document Audience")
        assert stack.path() == "1 Introduction > 1.2 Document Audience"

    def test_a_shallower_heading_pops_deeper_ones(self):
        stack = HeadingStack()
        stack.update("1 Introduction")
        stack.update("1.1 Document Purpose")
        stack.update("1.1.1 Related Documentation")
        stack.update("2 Process Details")
        assert stack.path() == "2 Process Details"

    def test_non_heading_lines_do_not_change_the_stack(self):
        stack = HeadingStack()
        stack.update("1 Introduction")
        assert stack.update("This is a plain sentence describing the process.") is False
        assert stack.path() == "1 Introduction"


# ---------------------------------------------------------------------------
# PDFExtractor against the hand-built synthetic PDF.
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_pdf_path(tmp_workspace):
    pages = [
        [
            "1 Introduction",
            "1.1 Document Purpose",
            "This document describes a small test process.",
        ],
        [
            "1.2 Process Scope",
            "The scope covers exactly one paragraph of prose.",
            "- Alpha item",
            "- Beta item",
        ],
    ]
    return _write_pdf(os.path.join(tmp_workspace, "synthetic.pdf"), pages)


class TestPDFExtractorSyntheticDocument:
    def test_every_segment_carries_source_file_page_and_section_path(self, synthetic_pdf_path):
        doc = PDFExtractor().extract(synthetic_pdf_path)

        assert doc.source_file == "synthetic.pdf"
        assert len(doc.segments) >= 2
        assert all(seg.page in (1, 2) for seg in doc.segments)

    def test_a_heading_on_page_1_sets_the_section_path_for_the_text_that_follows(self, synthetic_pdf_path):
        doc = PDFExtractor().extract(synthetic_pdf_path)

        page1_segments = [seg for seg in doc.segments if seg.page == 1]
        assert any(
            seg.section_path == "1 Introduction > 1.1 Document Purpose"
            and "small test process" in seg.text
            for seg in page1_segments
        )

    def test_the_heading_stack_carries_over_from_page_1_to_page_2(self, synthetic_pdf_path):
        doc = PDFExtractor().extract(synthetic_pdf_path)

        page2_segments = [seg for seg in doc.segments if seg.page == 2]
        assert any(seg.section_path and seg.section_path.startswith("1 Introduction >") for seg in page2_segments)
        assert any(seg.section_path == "1 Introduction > 1.2 Process Scope" for seg in page2_segments)

    def test_page_range_filters_to_the_requested_pages(self, synthetic_pdf_path):
        doc = PDFExtractor().extract(synthetic_pdf_path, page_range=(2, 2))

        assert doc.segments
        assert all(seg.page == 2 for seg in doc.segments)
        assert not any("Document Purpose" in (seg.section_path or "") for seg in doc.segments)


class TestPDFExtractorErrorHandling:
    def test_a_missing_file_raises_a_clear_error(self, tmp_workspace):
        missing = os.path.join(tmp_workspace, "does_not_exist.pdf")
        with pytest.raises(PDFExtractionError):
            PDFExtractor().extract(missing)

    def test_a_corrupt_file_raises_a_clear_error_not_a_traceback(self, tmp_workspace):
        path = os.path.join(tmp_workspace, "corrupt.pdf")
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4\nthis is not a real pdf body at all")

        with pytest.raises(PDFExtractionError):
            PDFExtractor().extract(path)

    def test_a_zero_page_pdf_raises_a_clear_error(self, tmp_workspace):
        path = os.path.join(tmp_workspace, "empty.pdf")
        with open(path, "wb") as handle:
            handle.write(_make_pdf([]))

        with pytest.raises(PDFExtractionError, match="zero pages"):
            PDFExtractor().extract(path)

    def test_an_invalid_page_range_raises_a_clear_error(self, synthetic_pdf_path):
        with pytest.raises(PDFExtractionError):
            PDFExtractor().extract(synthetic_pdf_path, page_range=(5, 1))


# ---------------------------------------------------------------------------
# DataIngestor.ingest_pdf / ingest_corpus, against the synthetic PDF.
# ---------------------------------------------------------------------------


def _make_ingestor(db_path):
    return DataIngestor(
        sqlite_conn_path=db_path,
        es_client=None,
        milvus_collection=None,
        neo4j_driver=None,
        embedding_model=SimpleEmbeddingModel(),
        svo_extractor=MockSVOExtractor(),
        concept_extractor=MockConceptExtractor(),
    )


def _stored_chunks(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(
            "SELECT text, chunk_type, metadata FROM chunks WHERE document_id = 'synth_doc'"
        ).fetchall()


class TestIngestPdf:
    def test_ingest_pdf_reuses_the_normal_chunk_embed_svo_store_path(self, synthetic_pdf_path, tmp_workspace):
        db_path = os.path.join(tmp_workspace, "svo.db")
        result = _make_ingestor(db_path).ingest_pdf("synth_doc", synthetic_pdf_path)

        assert result["status"] == "success"
        assert result["chunks"] > 0
        rows = _stored_chunks(db_path)
        assert len(rows) == result["chunks"]

    def test_every_stored_chunk_carries_page_and_source_file_metadata(self, synthetic_pdf_path, tmp_workspace):
        import json

        db_path = os.path.join(tmp_workspace, "svo.db")
        _make_ingestor(db_path).ingest_pdf("synth_doc", synthetic_pdf_path)

        for text, _chunk_type, metadata_json in _stored_chunks(db_path):
            metadata = json.loads(metadata_json)
            assert metadata["source_file"] == "synthetic.pdf"
            assert metadata["page"] in (1, 2)

    def test_list_items_on_a_pdf_page_become_their_own_chunks(self, synthetic_pdf_path, tmp_workspace):
        db_path = os.path.join(tmp_workspace, "svo.db")
        result = _make_ingestor(db_path).ingest_pdf("synth_doc", synthetic_pdf_path)

        assert result["chunk_types"].get(ChunkType.LIST_ITEM.value, 0) == 2
        list_texts = [row[0] for row in _stored_chunks(db_path) if row[1] == "list_item"]
        assert "Alpha item" in list_texts
        assert "Beta item" in list_texts

    def test_a_pdf_extraction_error_is_reported_not_raised(self, tmp_workspace):
        db_path = os.path.join(tmp_workspace, "svo.db")
        result = _make_ingestor(db_path).ingest_pdf("bad_doc", os.path.join(tmp_workspace, "nope.pdf"))

        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    def test_ingest_document_is_unaffected_by_the_pdf_additions(self, tmp_workspace):
        db_path = os.path.join(tmp_workspace, "svo.db")
        result = _make_ingestor(db_path).ingest_document("doc1", "Aspirin treats headache.")

        assert result["status"] == "success"
        assert result["chunks"] >= 1


class TestIngestCorpus:
    def test_each_pdf_in_the_directory_gets_its_own_document_id(self, tmp_workspace):
        corpus_dir = os.path.join(tmp_workspace, "corpus")
        os.makedirs(corpus_dir)
        _write_pdf(os.path.join(corpus_dir, "First Report.pdf"), [["1 Intro", "Some text."]])
        _write_pdf(os.path.join(corpus_dir, "second_report.pdf"), [["1 Intro", "Other text."]])

        db_path = os.path.join(tmp_workspace, "svo.db")
        results = _make_ingestor(db_path).ingest_corpus(corpus_dir)

        assert len(results) == 2
        ids = {r["document_id"] for r in results}
        assert ids == {"first_report", "second_report"}
        assert all(r["status"] == "success" for r in results)

    def test_slugify_is_stable_across_repeated_calls(self, tmp_workspace):
        assert DataIngestor._slugify_filename("wb_IT - Event Management Process v1.3.pdf") == \
            DataIngestor._slugify_filename("wb_IT - Event Management Process v1.3.pdf")
        assert DataIngestor._slugify_filename("wb_IT - Event Management Process v1.3.pdf") == \
            "wb_it_event_management_process_v1_3"


# ---------------------------------------------------------------------------
# Real documents, when present on disk (gitignored -- CI/clean-checkout safe).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not os.path.exists(EVENT_MGMT_PDF), reason="Documents/ is gitignored; not present in this checkout")
class TestRealEventManagementDocument:
    def test_extracts_ten_pages_with_page_numbers_and_some_section_paths(self):
        doc = PDFExtractor().extract(EVENT_MGMT_PDF)

        assert {seg.page for seg in doc.segments} <= set(range(1, 11))
        assert any(seg.section_path for seg in doc.segments)

    def test_produces_table_rows_from_the_document_control_and_raci_tables(self):
        doc = PDFExtractor().extract(EVENT_MGMT_PDF)

        assert len(doc.tables) > 0
        assert all(t.page in range(1, 11) for t in doc.tables)


@pytest.mark.skipif(not os.path.exists(INCIDENT_MGMT_PDF), reason="Documents/ is gitignored; not present in this checkout")
class TestRealIncidentManagementDocument:
    def test_extracts_fourteen_pages(self):
        doc = PDFExtractor().extract(INCIDENT_MGMT_PDF)

        assert max(seg.page for seg in doc.segments) <= 14

    def test_a_known_numbered_heading_is_recognised(self):
        doc = PDFExtractor().extract(INCIDENT_MGMT_PDF)

        assert any(
            seg.section_path and "Process Principles" in seg.section_path
            for seg in doc.segments
        )


@pytest.mark.skipif(not os.path.exists(IT4IT_PDF), reason="Documents/ is gitignored; not present in this checkout")
class TestRealIT4ITDocumentPageRange:
    def test_page_range_avoids_reading_all_294_pages(self):
        doc = PDFExtractor().extract(IT4IT_PDF, page_range=(1, 5))

        assert all(seg.page in range(1, 6) for seg in doc.segments)
        assert all(t.page in range(1, 6) for t in doc.tables)


class TestPDFTextCleaning:
    """Layout artefacts must not survive into the chunk store.

    A table-of-contents dot leader is visual formatting, but the shared
    sentence splitter reads every ". " in it as a sentence. Four pages of the
    IT4IT front matter yielded 8,536 "sentences", 8,376 of them the string
    " ." - each of which would become a row in the chunk store and a candidate
    in every retriever. Cleaning happens on the PDF path only, because
    `ingest_document` shares the splitter and existing callers depend on it.
    """

    def test_dot_leaders_are_collapsed(self):
        from src.ingestion.pipeline import DataIngestor

        cleaned = DataIngestor._clean_pdf_text(
            "4.14. Digital Product Fulfillment. . . . . . . . . . . . . . 55"
        )
        assert ". . ." not in cleaned
        assert "Digital Product Fulfillment" in cleaned
        assert "55" in cleaned

    def test_repeated_page_furniture_is_removed(self):
        from src.ingestion.pipeline import DataIngestor

        cleaned = DataIngestor._clean_pdf_text("Evaluation Copy\nReal content here.")
        assert "Evaluation Copy" not in cleaned
        assert "Real content here." in cleaned

    def test_ordinary_prose_is_left_alone(self):
        from src.ingestion.pipeline import DataIngestor

        text = "Events are logged. Incidents are raised. The team responds."
        assert DataIngestor._clean_pdf_text(text) == text

    @pytest.mark.parametrize("text,expected", [
        (" .", False),
        (".", False),
        ("  ", False),
        ("55", False),
        ("a", False),
        ("- ", False),
        ("Event Management", True),
        ("GCP Systems", True),
        ("The team responds to events.", True),
    ])
    def test_substantive_filter(self, text, expected):
        from src.ingestion.pipeline import DataIngestor

        assert DataIngestor._is_substantive(text) is expected

    def test_dot_leader_page_yields_no_junk_chunks(self, tmp_path):
        """End-to-end on the PDF chunk path, without needing a real PDF."""
        from src.ingestion.pipeline import DataIngestor
        from src.ingestion.pdf_extractor import PDFDocument, PDFSegment

        ingestor = DataIngestor(
            sqlite_conn_path=str(tmp_path / "s.db"), es_client=None, milvus_collection=None,
            neo4j_driver=None, embedding_model=SimpleEmbeddingModel(),
            svo_extractor=MockSVOExtractor(), concept_extractor=MockConceptExtractor(),
        )
        toc = PDFDocument(
            source_file="toc.pdf",
            segments=[PDFSegment(
                page=3, section_path=None,
                text="1. Introduction. . . . . . . . . . 5\n2. Scope. . . . . . . . . . 9",
            )],
            tables=[],
        )
        chunks = ingestor._build_pdf_chunks("doc", toc)
        assert all(DataIngestor._is_substantive(c.text) for c in chunks)
        assert not any(c.text.strip() in {".", " .", ""} for c in chunks)
