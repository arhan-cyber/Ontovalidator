"""Diagnostic script: run TransformerSVOExtractor against real sentences and print
BOTH the raw flan-t5-small generation and what the extract() parser derives from it.

This exists because 'Extracted 0 SVO relations' was observed in production, and the
extraction logic (src/ingestion/embeddings.py::TransformerSVOExtractor) cannot be
verified on the dev machine (no GPU/accelerated torch, transformer downloads not run
locally). Run this on the remote server:

    python "remote server scripts/test_svo_extractor.py"

It reuses the exact chunking + extraction code path used by DataIngestor, so its
output reflects what the API actually does end-to-end for SVO extraction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.pipeline import DataIngestor
from src.ingestion.embeddings import TransformerSVOExtractor

SAMPLE_TEXT = (
    "In 1970, Trump invested $70,000 of his father's wealth to receive billing as "
    "coproducer of a Broadway comedy—and lost the money.[62] After making low-ball "
    "bids for the New York Mets and the Cleveland Indians baseball teams, in 1983 for "
    "about $6 million, he purchased the New Jersey Generals, a team in the United "
    "States Football League.[63] The league folded after the 1985 season, largely due "
    "to his attempt to move to a fall schedule (when it would have competed with the "
    "National Football League for audience) and his attempt to force a merger with "
    "the NFL by bringing an antitrust suit.[64] In 1989 and 1990, he lent his name to "
    "the Tour de Trump cycling stage race, an attempt to create an American "
    "equivalent of European races such as the Tour de France or the Giro d'Italia.[65]"
)


def main():
    # Chunking sanity check first (this part IS testable without transformers,
    # but printing it here keeps the diagnostic self-contained). chunk_document
    # doesn't touch any instance state besides the class-level regex, so a bare
    # __new__ instance is safe to call it on without running __init__.
    ingestor = DataIngestor.__new__(DataIngestor)
    chunks = ingestor.chunk_document(document_id="diag", raw_text=SAMPLE_TEXT)
    print(f"=== Chunking produced {len(chunks)} chunk(s) ===")
    for i, c in enumerate(chunks, 1):
        print(f"[{i}] {c.text}")
    print()

    print("=== Loading TransformerSVOExtractor (google/flan-t5-small) ===")
    extractor = TransformerSVOExtractor()

    print("\n=== Per-chunk extraction ===")
    for i, c in enumerate(chunks, 1):
        print(f"\n--- chunk {i}: {c.text[:100]}{'...' if len(c.text) > 100 else ''}")

        # Reproduce extract()'s internals to see the RAW model output before parsing,
        # not just the (possibly empty) parsed result.
        import torch
        prompt = (
            f"Extract Subject-Verb-Object relations from text as "
            f"'Subject, Relation, Object'. Text: {c.text}"
        )
        inputs = extractor.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = extractor.model.generate(**inputs, max_length=64)
        raw_output = extractor.tokenizer.decode(outputs[0], skip_special_tokens=True)
        print(f"    raw model output: {raw_output!r}")

        relations = extractor.extract(c.text)
        if relations:
            for r in relations:
                print(f"    parsed -> ({r.subject_name_type!r}, {r.relation!r}, {r.object_name_type!r})")
        else:
            print("    parsed -> NO RELATIONS (parser rejected raw output)")


if __name__ == "__main__":
    main()
