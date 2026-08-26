r"""DataIngestor._split_sentences must not exhibit catastrophic backtracking.

It replaced a regex (`.+?[.!?](?:\[[^\]]*\])*(?=\s+|$)` via `findall`) that
was effectively O(n^2) on text with no sentence-terminating punctuation at
all: a single schema-valid ~1-2MB request body with no `.`/`!`/`?` anywhere
could hang the request - and with it the whole single-threaded event loop -
for minutes. This asserts the replacement stays linear-time and that its
output matches the old regex's behavior on ordinary text (except two
data-loss bugs in the old regex that are fixed on purpose, documented below).
"""

import re
import time

from src.ingestion.pipeline import DataIngestor

# The original pathological pattern, kept here only to cross-check behavior
# on well-formed text - never call .findall() on attacker-controlled-length
# input with this in a test, that's the bug being tested against.
_OLD_PATTERN = re.compile(r".+?[.!?](?:\[[^\]]*\])*(?=\s+|$)")


def _old_split(text: str):
    stripped = text.strip()
    found = _OLD_PATTERN.findall(stripped)
    return found if found else [stripped]


def _new_split(text: str):
    stripped = text.strip()
    found = DataIngestor._split_sentences(stripped)
    return found if found else [stripped]


def test_no_terminator_at_all_completes_in_well_under_a_second():
    # ~1.8MB, no `.`/`!`/`?` anywhere - the exact shape that hung the old
    # regex for 9+ minutes and blocked every other request meanwhile.
    pathological = "a " * 900_000
    start = time.monotonic()
    result = DataIngestor._split_sentences(pathological)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"sentence splitting took {elapsed:.2f}s, expected well under 2s"
    assert result == [pathological]


def test_large_well_punctuated_text_also_stays_fast():
    text = "This is a normal sentence. " * 50_000  # ~1.4MB, well-formed
    start = time.monotonic()
    result = DataIngestor._split_sentences(text)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0
    assert len(result) == 50_000


def test_matches_old_regex_on_ordinary_text():
    cases = [
        "Aspirin treats headache. Aspirin reduces fever.",
        "This is 3.14 and this is another sentence.",  # decimal not split mid-number
        "Cited claim.[62] Another one.[63][64]",  # trailing citation brackets stay attached
        "Cited claim.[62 unclosed bracket rest of text",
        "   ",
        "",
        ". Hello",
        "Hello.",
        "Q: is this a question? A: yes! Great.",
    ]
    for text in cases:
        assert _new_split(text) == _old_split(text), f"mismatch for {text!r}"


def test_trailing_unterminated_text_is_kept_not_silently_dropped():
    # The old regex only returns fully-matched (terminator-ending) spans via
    # findall(), so trailing text with no closing punctuation vanished
    # entirely. The new splitter keeps it as a final chunk instead.
    text = "First sentence. Trailing fragment with no ending punctuation"
    old = _old_split(text)
    new = _new_split(text)
    assert old == ["First sentence."]  # documents the old data-loss bug
    assert new == ["First sentence.", " Trailing fragment with no ending punctuation"]
    assert "Trailing fragment" in "".join(new)


def test_paragraph_break_before_first_terminator_is_kept_not_dropped():
    # `.` in the old regex doesn't match newlines, so a paragraph with no
    # terminator before a blank line could never be reached by `.+?` at all
    # and was silently dropped in its entirety, not just truncated.
    text = "Multi\n\nline\n\ntext. With paragraphs."
    old = _old_split(text)
    new = _new_split(text)
    assert old == ["text.", " With paragraphs."]  # documents the old data-loss bug
    assert "Multi" in new[0] and "line" in new[0]


def test_chunk_document_end_to_end_on_pathological_input_stays_fast():
    ingestor = DataIngestor.__new__(DataIngestor)  # avoid constructing extractors
    pathological = "b " * 500_000
    start = time.monotonic()
    chunks = DataIngestor.chunk_document(ingestor, "doc1", pathological)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0
    assert len(chunks) == 1
    assert chunks[0].document_id == "doc1"


def test_mock_svo_extractor_on_pathological_input_stays_fast():
    # MockSVOExtractor had its own independent copy of the same pathological
    # regex (added when it was generalized to a verb-phrase heuristic) - a
    # punctuation-free document now chunks down to one giant chunk, which
    # gets handed to the SVO extractor whole, re-triggering the identical
    # O(n^2) blowup one level up the call stack. Caught by an end-to-end
    # DoS retest against the live server after the chunker fix alone landed.
    from src.ingestion.extractors import MockSVOExtractor

    extractor = MockSVOExtractor()
    pathological = "a " * 400_000  # ~800KB, no punctuation
    start = time.monotonic()
    result = extractor.extract(pathological)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"MockSVOExtractor.extract took {elapsed:.2f}s, expected well under 2s"
    assert result == []  # no recognizable verb in "a a a ..."
