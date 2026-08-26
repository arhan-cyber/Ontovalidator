"""Shared linear-time sentence splitter.

Both `DataIngestor.chunk_document` and `MockSVOExtractor.extract` used to
split on the regex `.+?[.!?](?:\\[[^\\]]*\\])*(?=\\s+|$)` via `findall`. That
pattern's lazy `.+?` backtracks catastrophically - roughly O(n^2) - on any
text with no sentence-terminating punctuation at all, because `findall`
retries the whole match from every character position once an attempt runs
off the end of the string with no terminator to anchor on. A single
~1-2MB request body with no `.`/`!`/`?` anywhere (well within this API's
documented size limit) could hang the call - and with it the whole
single-threaded event loop - for minutes. `chunk_document`'s copy of this
was fixed first; `MockSVOExtractor` had its own independent copy of the same
pattern (added when it was generalized from a hardcoded keyword-matcher to a
verb-phrase heuristic) that hit the identical failure mode, since a
punctuation-free document now chunks down to one giant chunk that gets
handed to the SVO extractor whole. One shared, linear-time implementation
closes both.
"""

from typing import List

_SENTENCE_TERMINATORS = ".!?"


def split_sentences(text: str) -> List[str]:
    """Split text into sentences ending in `.`/`!`/`?`, in O(n) time.

    Citation markers like "[62]" commonly sit directly against the
    preceding punctuation with no space (Wikipedia-style text) and stay
    attached to their sentence. A terminator only ends a sentence when
    followed by whitespace or end-of-string (and preceded by at least one
    other character), so "3.14" is not split mid-number, matching the old
    regex's `.+` (one-or-more) and lookahead semantics.
    """
    sentences: List[str] = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        if i > start and text[i] in _SENTENCE_TERMINATORS:
            j = i + 1
            while j < n and text[j] == "[":
                close = text.find("]", j)
                if close == -1:
                    break
                j = close + 1
            if j >= n or text[j].isspace():
                sentences.append(text[start:j])
                start = j
                i = j
                continue
        i += 1
    if start < n and text[start:].strip():
        # Trailing text with no closing punctuation - the old regex silently
        # dropped this (findall only returns full matches); keep it instead
        # of losing content from the end of a document.
        sentences.append(text[start:])
    return sentences
