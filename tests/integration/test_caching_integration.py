"""Caching wired into embeddings, retrievers, and the verdict path."""

import os

import pytest

from src.cache import CacheEngine
from src.config import PipelineConfig
from src.factories import EngineFactory
from src.ingestion import DataIngestor, MockConceptExtractor, MockSVOExtractor, SimpleEmbeddingModel
from src.models import OntologyAssertion
from src.retrieval import SQLiteLexicalRetriever

DOCUMENT = (
    "Aspirin is a widely used analgesic. Aspirin treats headache and minor body aches. "
    "It does not treat malaria."
)


@pytest.fixture
def cache(tmp_workspace):
    return CacheEngine(os.path.join(tmp_workspace, "cache.db"))


@pytest.fixture
def ingested_db(tmp_workspace):
    db_path = os.path.join(tmp_workspace, "svo.db")
    DataIngestor(
        sqlite_conn_path=db_path,
        es_client=None,
        milvus_collection=None,
        neo4j_driver=None,
        embedding_model=SimpleEmbeddingModel(),
        svo_extractor=MockSVOExtractor(),
        concept_extractor=MockConceptExtractor(),
    ).ingest_document("doc1", DOCUMENT)
    return db_path


class CountingEmbeddingModel(SimpleEmbeddingModel):
    """SimpleEmbeddingModel that records how many texts actually reached the model."""

    def __init__(self, cache_engine=None):
        super().__init__(cache_engine)
        self.encoded = []

    def _encode_batch(self, texts):
        self.encoded.extend(texts)
        return super()._encode_batch(texts)


class TestEmbeddingCaching:
    def test_repeated_text_is_only_embedded_once(self, cache):
        model = CountingEmbeddingModel(cache)

        first = model.encode(["hello world"])
        second = model.encode(["hello world"])

        assert first == second
        assert model.encoded == ["hello world"]

    def test_only_the_uncached_texts_reach_the_model(self, cache):
        model = CountingEmbeddingModel(cache)
        model.encode(["a", "b"])
        model.encoded.clear()

        embeddings = model.encode(["a", "b", "c"])

        assert model.encoded == ["c"]
        assert len(embeddings) == 3

    def test_results_stay_aligned_with_their_inputs(self, cache):
        model = CountingEmbeddingModel(cache)
        model.encode(["b"])

        mixed = model.encode(["a", "b", "c"])
        uncached = CountingEmbeddingModel()._encode_batch(["a", "b", "c"])

        assert mixed == uncached

    def test_no_cache_still_works(self):
        model = CountingEmbeddingModel(None)
        assert len(model.encode(["x", "y"])) == 2


class TestRetrievalCaching:
    def test_second_identical_query_is_served_from_cache(self, ingested_db, cache):
        retriever = SQLiteLexicalRetriever(ingested_db, cache_engine=cache)

        first = retriever.retrieve("Aspirin treats headache", 5)
        before = cache.get_stats()["hits"]
        second = retriever.retrieve("Aspirin treats headache", 5)

        assert [r.chunk_id for r in first] == [r.chunk_id for r in second]
        assert cache.get_stats()["hits"] == before + 1

    def test_new_chunks_invalidate_the_cached_query(self, ingested_db, cache):
        retriever = SQLiteLexicalRetriever(ingested_db, cache_engine=cache)
        first = retriever.retrieve("Aspirin treats fever", 5)

        DataIngestor(
            sqlite_conn_path=ingested_db,
            es_client=None,
            milvus_collection=None,
            neo4j_driver=None,
            embedding_model=SimpleEmbeddingModel(),
            svo_extractor=MockSVOExtractor(),
            concept_extractor=MockConceptExtractor(),
        ).ingest_document("doc2", "Aspirin treats fever effectively.")

        second = retriever.retrieve("Aspirin treats fever", 5)

        assert len(second) > len(first)

    def test_cached_results_do_not_carry_chunk_bodies(self, ingested_db, cache):
        retriever = SQLiteLexicalRetriever(ingested_db, cache_engine=cache)
        retriever.retrieve("Aspirin", 5)

        cached = cache.get_retrieval("Aspirin", "SQLiteLexicalRetriever", 5, retriever._cache_fingerprint())
        assert all(entry["chunk"] is None for entry in cached)

    def test_retriever_without_cache_behaves_identically(self, ingested_db, cache):
        uncached = SQLiteLexicalRetriever(ingested_db).retrieve("Aspirin treats headache", 5)
        cached = SQLiteLexicalRetriever(ingested_db, cache_engine=cache).retrieve("Aspirin treats headache", 5)

        assert [r.chunk_id for r in uncached] == [r.chunk_id for r in cached]


class TestVerdictCaching:
    def _config(self, tmp_workspace, **overrides):
        return PipelineConfig(
            sqlite_path=os.path.join(tmp_workspace, "svo.db"),
            cache_db_path=os.path.join(tmp_workspace, "cache.db"),
            feedback_db_path=os.path.join(tmp_workspace, "feedback.db"),
            **overrides,
        )

    def _triple(self):
        return OntologyAssertion(
            assertion_id="t1", subject="Aspirin", relation="treats", object="headache"
        )

    def test_repeating_a_request_hits_the_verdict_cache(self, tmp_workspace):
        engine = EngineFactory.create_verification_engine(self._config(tmp_workspace))

        first = engine.validate_triples_batch("doc1", DOCUMENT, [self._triple()], top_k=5)
        second = engine.validate_triples_batch("doc1", DOCUMENT, [self._triple()], top_k=5)

        assert first["summary"]["cache_hits"] == 0
        assert second["summary"]["cache_hits"] == 1
        assert second["verdicts"][0]["label"] == first["verdicts"][0]["label"]

    def test_changed_text_under_the_same_document_id_is_re_evaluated(self, tmp_workspace):
        engine = EngineFactory.create_verification_engine(self._config(tmp_workspace))
        engine.validate_triples_batch("doc1", DOCUMENT, [self._triple()], top_k=5)

        rewritten = "Aspirin does not treat headache at all."
        second = engine.validate_triples_batch("doc1", rewritten, [self._triple()], top_k=5)

        assert second["summary"]["cache_hits"] == 0

    def test_caching_can_be_disabled(self, tmp_workspace):
        engine = EngineFactory.create_verification_engine(
            self._config(tmp_workspace, enable_cache=False)
        )

        assert engine.cache_engine is None
        result = engine.validate_triples_batch("doc1", DOCUMENT, [self._triple()], top_k=5)
        assert result["summary"]["cache_hits"] == 0
