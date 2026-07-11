"""Diagnostic script: vet the provides/depends concept graph and multi-hop retrieval.

Two things need checking that can't be verified without a transformer model, so this
must run on the remote server (not locally - no GPU/accelerated torch on the dev
machine):

  1. Does TransformerConceptExtractor (google/flan-t5-large) actually extract sensible
     "provides"/"depends_on" concepts per chunk, and does its embedding-similarity
     canonicalization step (extractors.py:101-144) correctly merge near-duplicate
     concept names across chunks?

  2. Does SQLiteGraphRetriever (src/retrieval/graph.py) actually traverse that graph
     multiple hops, i.e. can it retrieve a chunk that shares NO literal keyword overlap
     with the query, purely because it's connected via a chain of provides/depends
     concept edges through an intermediate chunk?

HISTORY: the original zero-shot prompts made flan-t5-large echo the entire input
sentence back as one giant "concept" on the "provides" prompt (23 words observed),
while the parallel "depends_on" prompt happened to get a clean short comma-list.
Multi-hop retrieval technically still passed, but partly via accidental substring
matching against those giant sentence-blobs rather than genuine concept-graph
semantics. Switching to few-shot prompts (one worked example each) plus a defensive
length guard (reject any parsed term longer than
TransformerConceptExtractor.MAX_CONCEPT_WORDS) fixed it - confirmed via a zero-shot
vs few-shot side-by-side comparison, longest concept dropped from 23 words to 2.
That fix is now shipped in src/ingestion/extractors.py::TransformerConceptExtractor
itself (not a separate class anymore), so this script now just regression-checks the
production class directly.

Run on the remote server:

    python "remote server scripts/test_concept_graph.py"
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.pipeline import DataIngestor
from src.ingestion.embeddings import SimpleEmbeddingModel
from src.ingestion.extractors import MockSVOExtractor, TransformerConceptExtractor
from src.retrieval.graph import SQLiteGraphRetriever

# Deliberate 2-hop dependency chain:
#   doc_a  PROVIDES "hash table"
#   doc_b  DEPENDS_ON "hash table", PROVIDES "python dictionary"
#   doc_c  DEPENDS_ON "python dictionary"   <-- shares NO words with doc_a
#
# A query about "hash table" should be able to reach doc_c only by traversing
# doc_a -> hash table -> doc_b -> python dictionary -> doc_c (2 hops).
DOCUMENT_ID = "concept_graph_diag"
CHUNKS = {
    "doc_a": (
        "A hash table is a data structure that provides constant-time key-value "
        "lookup by using a hash function to map keys to array indices."
    ),
    "doc_b": (
        "A Python dictionary is implemented internally using a hash table, giving "
        "it average O(1) time complexity for lookups and insertions."
    ),
    "doc_c": (
        "Caching systems in web servers frequently store frequently accessed "
        "values in a Python dictionary to avoid recomputation."
    ),
}


def print_header(title):
    print(f"\n{'=' * 10} {title} {'=' * 10}")


def main():
    print_header("Loading TransformerConceptExtractor (google/flan-t5-large, few-shot prompts)")
    concept_extractor = TransformerConceptExtractor()

    db_path = tempfile.mktemp(suffix=".db")
    ingestor = DataIngestor(
        sqlite_conn_path=db_path,
        es_client=None,
        milvus_collection=None,
        neo4j_driver=None,
        embedding_model=SimpleEmbeddingModel(),
        svo_extractor=MockSVOExtractor(),
        concept_extractor=concept_extractor,
    )

    chunk_ids = {}
    for label, text in CHUNKS.items():
        print_header(f"Ingesting {label}")
        ingestor.ingest_document(f"{DOCUMENT_ID}_{label}", text)
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT chunk_id, metadata FROM chunks WHERE document_id = ?",
            (f"{DOCUMENT_ID}_{label}",),
        ).fetchone()
        conn.close()
        chunk_id, metadata_json = row
        metadata = json.loads(metadata_json)
        chunk_ids[label] = chunk_id
        print(f"  chunk_id: {chunk_id}")
        print(f"  provides:    {metadata.get('provides', [])}")
        print(f"  depends_on:  {metadata.get('depends_on', [])}")

    print_header("Multi-hop retrieval test")
    retriever = SQLiteGraphRetriever(db_path)

    for query, expectation in [
        ("hash table", "should retrieve doc_a directly, doc_b at 1 hop, doc_c at 2 hops"),
        ("caching web server", "should retrieve doc_c directly (keyword match) - baseline sanity check"),
    ]:
        print(f"\n--- query: {query!r}  ({expectation})")
        results = retriever.retrieve(query, top_k=5, max_hops=3)
        if not results:
            print("    NO RESULTS")
        for r in results:
            label = next((l for l, cid in chunk_ids.items() if cid == r.chunk_id), "?")
            print(f"    [{label}] score={r.score:.3f} source={r.source}")

    print_header("Verdict")
    doc_c_id = chunk_ids["doc_c"]
    hash_table_results = {r.chunk_id: r.score for r in retriever.retrieve("hash table", top_k=5, max_hops=3)}

    conn = sqlite3.connect(db_path)
    max_words_seen = 0
    for _, _, metadata_json in conn.execute("SELECT chunk_id, text, metadata FROM chunks"):
        metadata = json.loads(metadata_json)
        for term in metadata.get("provides", []) + metadata.get("depends_on", []):
            max_words_seen = max(max_words_seen, len(term.split()))
    conn.close()

    multi_hop_passed = doc_c_id in hash_table_results
    guard_respected = max_words_seen <= TransformerConceptExtractor.MAX_CONCEPT_WORDS

    print(f"Multi-hop PASS (doc_c reached via 'hash table' query): {multi_hop_passed}")
    print(f"Longest concept term stored: {max_words_seen} words (guard limit: {TransformerConceptExtractor.MAX_CONCEPT_WORDS})")

    if multi_hop_passed and guard_respected:
        print("\nPASS: concept extraction is producing short, sensible terms AND multi-hop")
        print("retrieval correctly traverses the resulting graph.")
    elif multi_hop_passed and not guard_respected:
        print("\nPARTIAL: multi-hop retrieval succeeded, but a concept exceeded the length")
        print("guard - check the provides/depends_on printout above for a regression back")
        print("toward the 'whole sentence as concept' failure mode.")
    else:
        print("\nFAIL: doc_c was NOT reached querying 'hash table'. Check the provides/")
        print("depends_on printout above: doc_b's depends_on should contain the SAME string")
        print("as doc_a's provides, and doc_c's depends_on should contain the SAME string")
        print("as doc_b's provides (post-canonicalization).")

    os.remove(db_path)


if __name__ == "__main__":
    main()
