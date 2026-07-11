"""Fully-instrumented, extremely verbose trace of one ingest + validate_triples_batch
call through the REAL production code path (EngineFactory-built engine, real
DataIngestor, real retrievers) - logging every decision point:

  - resolved config (which embedding_model/svo_extractor/concept_extractor got built)
  - full contents of every "store" after ingestion
  - the router's decision (which QueryType(s) it assigned, and therefore which
    retriever(s) actually get called for the query)
  - lexical / semantic / graph retriever calls: args in, results out
  - the graph retriever's concept-graph BFS, hop by hop (which concepts matched,
    which chunks got pulled in at each hop, and the fallback path if no concepts
    matched at all)
  - the fusion engine's input (per-retriever results) and output (fused/ranked list)
  - per-chunk evidence matching (subject/relation/object literal match + negation
    detection) for every retrieved chunk
  - the evidence judge call (heuristic verdict in, LM judge verdict out, merge)
  - the final JSON result

IMPORTANT CORRECTION to a common assumption about this codebase: in the default
SQLite backend (no Elasticsearch/Milvus/Neo4j configured), there is only ONE
database - a single SQLite `chunks` table. SQLiteLexicalRetriever, SQLiteSemanticRetriever,
and SQLiteGraphRetriever all read the SAME rows from the SAME table; they just score
them differently. SQLiteSemanticRetriever does NOT use the embedding vectors
computed during ingestion - it does Jaccard token overlap on raw text, same
mechanism as lexical (see src/retrieval/semantic.py:56-66). The embedding vectors
ARE computed (embedding_model.encode(...)) but are only ever written to Milvus,
which is a no-op mock in this backend - so they're computed and then discarded.
Elasticsearch/Neo4j writes are similarly no-ops/skipped (see the
"[!] ... write failed/skipped" lines you've seen in ingestion logs). This script's
DB dump section prints one table with three different "views" (annotated) rather
than three separate stores, to reflect what's actually happening.

Must run on the remote server - loads real transformer models depending on env vars.

Run (env vars control which real models get used - same names api/app.py reads):

    ONTO_EMBEDDING_MODEL=transformer ONTO_SVO_EXTRACTOR=mock ONTO_CONCEPT_EXTRACTOR=transformer \
        python "remote server scripts/verbose_pipeline_trace.py"

Defaults to whatever's already in your environment / config.py defaults if you don't
set them (ONTO_EMBEDDING_MODEL=simple, ONTO_SVO_EXTRACTOR=mock, ONTO_CONCEPT_EXTRACTOR=mock).

The triple used is a deliberate diagnostic probe (see DOCUMENT_TEXT/TRIPLE below):
subject/relation/object are words that ONLY appear in the document's first sentence.
If the third sentence (which shares zero literal words with the query) shows up in
the evidence at all, that's only explainable by genuine multi-hop concept-graph
traversal - the hop-by-hop [GRAPH RETRIEVER] logging below will show exactly how.
"""

import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from src.config import load_config_from_env
from src.factories import EngineFactory
from src.models import OntologyAssertion, RetrievalResult
from src.retrieval.graph import SQLiteGraphRetriever

SEP = "=" * 100


def section(title):
    print(f"\n{SEP}\n{title}\n{SEP}")


DOCUMENT_TEXT = (
    "A hash table is a data structure that provides constant-time key-value "
    "lookup by using a hash function to map keys to array indices. A Python "
    "dictionary is implemented internally using a hash table, giving it average "
    "O(1) time complexity for lookups and insertions. Caching systems in web "
    "servers frequently store frequently accessed values in a Python dictionary "
    "to avoid recomputation."
)

TRIPLE = OntologyAssertion(
    assertion_id="diag_t1",
    subject="hash table",
    relation="required for",
    object="constant-time lookup",
)


class VerboseSQLiteGraphRetriever(SQLiteGraphRetriever):
    """Same algorithm as SQLiteGraphRetriever.retrieve(), but prints every step:
    which concepts were extracted from stored metadata, which ones matched the
    query, which chunks got pulled in at each BFS hop, and the fallback path if
    the concept graph produced nothing at all."""

    def retrieve(self, query: str, top_k: int, max_hops: int = 3) -> List[RetrievalResult]:
        print(f"\n  [GRAPH] query={query!r} top_k={top_k} max_hops={max_hops}")
        query_tokens = set(re.findall(r"\w+", query.lower()))
        print(f"  [GRAPH] query_tokens={query_tokens}")
        if not query_tokens:
            print("  [GRAPH] no query tokens -> returning []")
            return []

        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("SELECT chunk_id, text, metadata FROM chunks").fetchall()
        except sqlite3.OperationalError:
            rows = [(r[0], r[1], None) for r in conn.execute("SELECT chunk_id, text FROM chunks").fetchall()]
        finally:
            conn.close()

        chunks_map = {}
        concept_to_providers = {}
        concept_to_dependents = {}

        print(f"  [GRAPH] loaded {len(rows)} chunk(s) from {self.db_path}")
        for chunk_id, text, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json) if metadata_json else {}
            except Exception:
                metadata = {}
            provides = metadata.get("provides", [])
            depends_on = metadata.get("depends_on", [])
            chunks_map[chunk_id] = {"chunk_id": chunk_id, "text": text, "provides": provides, "depends_on": depends_on}
            print(f"    chunk {chunk_id[:8]}: provides={provides} depends_on={depends_on}")
            print(f"        text: {text[:90]}{'...' if len(text) > 90 else ''}")
            for cp in provides:
                concept_to_providers.setdefault(cp.lower(), []).append(chunk_id)
            for cp in depends_on:
                concept_to_dependents.setdefault(cp.lower(), []).append(chunk_id)

        print(f"  [GRAPH] concept_to_providers={concept_to_providers}")
        print(f"  [GRAPH] concept_to_dependents={concept_to_dependents}")

        matched_concepts = []
        for cp in list(concept_to_providers.keys()) + list(concept_to_dependents.keys()):
            if cp in query.lower() or any(token in cp for token in query_tokens):
                matched_concepts.append(cp)
        matched_concepts = list(dict.fromkeys(matched_concepts))
        print(f"  [GRAPH] concepts matching the query directly (0-hop): {matched_concepts}")

        visited_chunks = {}
        for cp in matched_concepts:
            connected = set(concept_to_providers.get(cp, []) + concept_to_dependents.get(cp, []))
            print(f"  [GRAPH] hop 0: concept={cp!r} directly connects to chunks={[c[:8] for c in connected]}")
            for cid in connected:
                visited_chunks[cid] = max(visited_chunks.get(cid, 0.0), 1.0)

            for hop in range(1, max_hops):
                next_connected = set()
                for cid in connected:
                    cdata = chunks_map.get(cid)
                    if not cdata:
                        continue
                    all_chunk_concepts = cdata["provides"] + cdata["depends_on"]
                    for c_name in all_chunk_concepts:
                        c_name_lower = c_name.lower()
                        others = concept_to_providers.get(c_name_lower, []) + concept_to_dependents.get(c_name_lower, [])
                        for other_id in others:
                            if other_id != cid:
                                next_connected.add(other_id)

                score_decay = 0.8 ** hop
                print(
                    f"  [GRAPH] hop {hop}: expanding from concept={cp!r}'s frontier "
                    f"-> newly reached chunks={[c[:8] for c in next_connected]} (score={score_decay:.3f})"
                )
                for cid in next_connected:
                    visited_chunks[cid] = max(visited_chunks.get(cid, 0.0), score_decay)
                connected = next_connected
                if not connected:
                    print(f"  [GRAPH] hop {hop}: frontier empty, stopping expansion for concept={cp!r}")
                    break

        if not visited_chunks:
            print("  [GRAPH] concept graph produced NO matches -> falling back to plain keyword overlap over ALL chunks")
            scored = []
            for chunk_id, text, _ in rows:
                text_tokens = set(re.findall(r"\w+", text.lower()))
                overlap = len(query_tokens & text_tokens)
                print(f"    chunk {chunk_id[:8]}: overlap={overlap} shared_tokens={text_tokens & query_tokens}")
                if overlap:
                    scored.append((overlap, chunk_id))
            scored.sort(reverse=True)
            result = [
                RetrievalResult(chunk_id=chunk_id, score=float(score) * 0.9, source="graph")
                for score, chunk_id in scored[:top_k]
            ]
            print(f"  [GRAPH] fallback result: {[(r.chunk_id[:8], r.score) for r in result]}")
            return result

        results = [RetrievalResult(chunk_id=cid, score=score, source="graph") for cid, score in visited_chunks.items()]
        results.sort(key=lambda x: x.score, reverse=True)
        result = results[:top_k]
        print(f"  [GRAPH] all visited_chunks (pre-truncation)={ {k[:8]: v for k, v in visited_chunks.items()} }")
        print(f"  [GRAPH] returning top_{top_k}: {[(r.chunk_id[:8], r.score) for r in result]}")
        return result


def wrap_method(obj, method_name, tag):
    """Generic call/return logger: replaces obj.method_name with a version that
    prints its args and return value, then delegates to the original."""
    original = getattr(obj, method_name)

    def wrapped(*args, **kwargs):
        print(f"\n  [{tag}] CALLED {method_name}(args={args}, kwargs={kwargs})")
        result = original(*args, **kwargs)
        if isinstance(result, list):
            summary = [
                f"(chunk={getattr(r, 'chunk_id', '?')[:8]}, score={getattr(r, 'score', '?')}, source={getattr(r, 'source', '?')})"
                if hasattr(r, "chunk_id") else str(r)
                for r in result
            ]
            print(f"  [{tag}] RETURNED {len(result)} item(s): {summary}")
        else:
            print(f"  [{tag}] RETURNED {result!r}")
        return result

    setattr(obj, method_name, wrapped)


def dump_database_state(db_path):
    section(f"DATABASE STATE after ingestion  (single SQLite file: {db_path})")
    print(
        "NOTE: this backend has exactly ONE database - the `chunks` table below.\n"
        "Lexical, semantic, and graph retrievers all query these SAME rows; they\n"
        "just score them differently:\n"
        "  - lexical:  keyword token overlap on `text`\n"
        "  - semantic: Jaccard TOKEN overlap on `text` (NOT the embedding vectors -\n"
        "              those are computed during ingestion but only ever written to\n"
        "              Milvus, which is a no-op mock here, so they're discarded)\n"
        "  - graph:    provides/depends_on concept matching from `metadata`, falling\n"
        "              back to the same keyword overlap as lexical if no concepts match\n"
        "Elasticsearch/Neo4j writes are no-ops/skipped entirely in this backend.\n"
    )
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT chunk_id, document_id, text, metadata FROM chunks").fetchall()
    conn.close()

    print(f"Total rows in `chunks` table: {len(rows)}\n")
    for chunk_id, document_id, text, metadata_json in rows:
        metadata = json.loads(metadata_json) if metadata_json else {}
        print(f"--- chunk_id={chunk_id}  document_id={document_id}")
        print(f"    text: {text}")
        print(f"    metadata.provides:   {metadata.get('provides', [])}")
        print(f"    metadata.depends_on: {metadata.get('depends_on', [])}")
        print()


def main():
    section("CONFIG")
    config = load_config_from_env()
    db_path = tempfile.mktemp(suffix=".db")
    config.sqlite_path = db_path
    config.verbose = True
    print(f"embedding_model_name = {config.embedding_model_name}")
    print(f"svo_extractor_name   = {config.svo_extractor_name}")
    print(f"concept_extractor_name = {config.concept_extractor_name}")
    print(f"validator_name       = {config.validator_name}")
    print(f"sqlite_path (temp, isolated for this run) = {db_path}")

    section("BUILDING ENGINE (real EngineFactory.create_verification_engine)")
    engine = EngineFactory.create_verification_engine(config)
    print(f"router            = {engine.router.__class__.__name__}")
    print(f"lexical_store     = {engine.lexical_store.__class__.__name__}")
    print(f"semantic_store    = {engine.semantic_store.__class__.__name__}")
    print(f"graph_store       = {engine.graph_store.__class__.__name__} (about to swap for verbose version)")
    print(f"fusion_engine     = {engine.fusion_engine.__class__.__name__}")
    print(f"validator         = {engine.validator.__class__.__name__}")
    print(f"evidence_judge    = {engine.evidence_judge.__class__.__name__}")
    print(f"svo_extractor     = {engine.svo_extractor.__class__.__name__ if engine.svo_extractor else None}")
    print(f"embedding_model   = {engine.embedding_model.__class__.__name__ if engine.embedding_model else None}")

    # Swap in the hop-by-hop verbose graph retriever, and wrap the rest with
    # generic call/return logging.
    engine.graph_store = VerboseSQLiteGraphRetriever(db_path)
    wrap_method(engine.router, "route", "ROUTER")
    wrap_method(engine.lexical_store, "retrieve", "LEXICAL")
    wrap_method(engine.semantic_store, "retrieve", "SEMANTIC")
    wrap_method(engine.fusion_engine, "fuse_and_rank", "FUSION")
    if engine.evidence_judge:
        wrap_method(engine.evidence_judge, "judge", "EVIDENCE_JUDGE")

    section(f"DOCUMENT TEXT\n{DOCUMENT_TEXT}")
    section(
        f"TRIPLE (diagnostic probe - subject/relation/object words appear ONLY in "
        f"sentence 1 of the document)\n"
        f"  subject={TRIPLE.subject!r}\n  relation={TRIPLE.relation!r}\n  object={TRIPLE.object!r}"
    )

    section("RUNNING engine.validate_triples_batch(...)  [ingestion + adjudication, real production path]")
    result = engine.validate_triples_batch(
        document_id="verbose_trace_doc",
        raw_text=DOCUMENT_TEXT,
        triples=[TRIPLE],
        top_k=5,
    )

    dump_database_state(db_path)

    section("FINAL RESULT (JSON)")
    print(json.dumps(result, indent=2))

    section("VERDICT")
    verdict = result["verdicts"][0]
    evidence_chunk_texts = [e["text"] for e in verdict["evidence"]]
    sentence_3_reached = any("Caching systems" in t for t in evidence_chunk_texts)
    print(f"label={verdict['label']} score={verdict['score']}")
    print(f"evidence chunk count: {len(verdict['evidence'])}")
    print(f"Did sentence 3 (zero literal overlap with the query) appear in evidence: {sentence_3_reached}")
    if sentence_3_reached:
        print("-> Only explainable by genuine multi-hop concept-graph traversal (see [GRAPH] hop logs above).")
    else:
        print("-> Multi-hop did not reach sentence 3 this run - check the [GRAPH] logs above for why")
        print("   (no matched_concepts at hop 0? provides/depends_on empty or not connecting?).")

    os.remove(db_path)


if __name__ == "__main__":
    main()
