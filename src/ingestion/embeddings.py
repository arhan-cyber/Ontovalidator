"""Embedding models."""

import re
from typing import Any, List, Optional, Union


class CachedEncoderMixin:
    """Adds a read-through embedding cache to any model exposing `_encode_batch`.

    Cache entries are keyed by model id as well as text, so swapping the
    underlying model never returns another model's vectors.
    """

    cache: Optional[Any] = None
    cache_model_id: str = "unknown"

    def encode(self, texts: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(texts, str):
            texts = [texts]

        if self.cache is None:
            return self._encode_batch(list(texts))

        embeddings: List[Optional[List[float]]] = [None] * len(texts)
        uncached_texts: List[str] = []
        uncached_indices: List[int] = []

        for index, text in enumerate(texts):
            cached = self.cache.get_embedding(text, self.cache_model_id)
            if cached is not None:
                embeddings[index] = cached
            else:
                uncached_texts.append(text)
                uncached_indices.append(index)

        if uncached_texts:
            # One batched forward pass for every miss, rather than one per text.
            computed = self._encode_batch(uncached_texts)
            for index, text, embedding in zip(uncached_indices, uncached_texts, computed):
                embeddings[index] = embedding
                self.cache.set_embedding(text, embedding, self.cache_model_id)

        return [e if e is not None else [] for e in embeddings]

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Alias for `encode` on a list; kept for callers that want the intent explicit."""
        return self.encode(texts)


class SimpleEmbeddingModel(CachedEncoderMixin):
    """5-dimensional mock embedding model (CPU-only, no dependencies)."""

    def __init__(self, cache_engine: Optional[Any] = None):
        self.cache = cache_engine
        self.cache_model_id = "simple-5d"

    def _encode_batch(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for text in texts:
            tokens = re.findall(r"\w+", text.lower())
            vector = [0.0] * 5
            for token in tokens:
                vector[abs(hash(token)) % 5] += 1.0

            norm = sum(value * value for value in vector) ** 0.5 or 1.0
            embeddings.append([round(value / norm, 4) for value in vector])

        return embeddings


class TransformerEmbeddingModel(CachedEncoderMixin):
    """Real DistilBERT embeddings (CPU-friendly, no GPU required)."""

    def __init__(self, model_name: str = "distilbert-base-uncased", cache_engine: Optional[Any] = None):
        from transformers import DistilBertTokenizer, AutoModel
        self.tokenizer = DistilBertTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.cache = cache_engine
        self.cache_model_id = model_name

    def _encode_batch(self, texts: List[str]) -> List[List[float]]:
        import torch

        inputs = self.tokenizer(texts, padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            outputs = self.model(**inputs)
            embeddings = outputs.last_hidden_state.mean(dim=1).cpu().numpy()
        return embeddings.tolist()


class TransformerSVOExtractor:
    """LLM-based SVO extraction using Flan-T5.

    Uses a few-shot prompt (one worked example) rather than a bare zero-shot
    instruction. Zero-shot prompting on flan-t5-small was observed to ignore
    the "Subject, Relation, Object" format entirely and just echo back a noun
    phrase with no commas at all (e.g. "Aspirin reduces inflammation and
    relieves pain..." -> "Aspirin") - the parser's `len(parts) >= 3` guard
    then silently discarded every sentence, so the extractor was a no-op
    on ordinary text without ever raising an error. `TransformerConceptExtractor`
    hit the same zero-shot failure mode and was already fixed with a worked
    example.

    Even few-shot, flan-t5-small (and flan-t5-base) follow the requested
    format inconsistently - roughly half of ordinary sentences still come
    back as an un-parseable echo or a malformed non-triple. Rather than ship
    a component that's a coin-flip between "real extraction" and "silent
    no-op", any sentence the model doesn't cleanly parse falls back to the
    same verb-phrase heuristic `MockSVOExtractor` uses, so this extractor is
    LM-first but never actually empty-handed on text with a recognizable verb.
    """

    MAX_PART_WORDS = 8  # defensive guard: reject a part this long as clearly not a clean S/R/O

    _SVO_PROMPT = (
        "Extract the main Subject, Relation, and Object from this sentence. "
        "Output ONLY a comma-separated triple: Subject, Relation, Object.\n\n"
        "Text: Aspirin reduces inflammation and relieves pain in patients with arthritis.\n"
        "Triple: Aspirin, reduces, inflammation\n\n"
        "Text: {text}\n"
        "Triple:"
    )

    def __init__(self, model_name: str = "google/flan-t5-small"):
        from transformers import T5Tokenizer, AutoModelForSeq2SeqLM
        from .extractors import MockSVOExtractor
        self.tokenizer = T5Tokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        self._fallback = MockSVOExtractor()

    def extract(self, text: str):
        from ..models import SVORelation

        if not text or not text.strip():
            return []

        try:
            import torch

            prompt = self._SVO_PROMPT.format(text=text[:512])
            inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=768)
            with torch.no_grad():
                outputs = self.model.generate(**inputs, max_length=64, num_beams=1)
            output_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

            parts = [p.strip().rstrip(".") for p in output_text.split(",")]
            parts = [p for p in parts if p]
            if len(parts) >= 3 and all(len(p.split()) <= self.MAX_PART_WORDS for p in parts[:3]):
                subject, relation, obj = parts[0], parts[1], parts[2]
                return [SVORelation(
                    subject_id="ent_" + re.sub(r'[^a-z0-9_]', '_', subject.lower()),
                    subject_name_type=subject,
                    relation=relation.upper(),
                    object_id="ent_" + re.sub(r'[^a-z0-9_]', '_', obj.lower()),
                    object_name_type=obj,
                    source_chunk_ids=[]
                )]
        except Exception:
            pass

        # The model didn't produce a parseable triple (or errored) - fall
        # back to the deterministic heuristic rather than returning nothing.
        return self._fallback.extract(text)
