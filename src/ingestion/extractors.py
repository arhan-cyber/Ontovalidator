"""SVO and concept extractors."""

from typing import List, Dict, Optional
import re

from ..models import SVORelation


class MockSVOExtractor:
    """Mock SVO extractor with hardcoded rules. Production uses LLM."""

    def extract(self, text: str) -> List[SVORelation]:
        lowered = text.lower()
        relations = []

        if "treats" in lowered or "headache" in lowered:
            relations.append(SVORelation(
                subject_id="ent_aspirin",
                subject_name_type="Aspirin (Drug)",
                relation="TREATS",
                object_id="ent_headache",
                object_name_type="Headache (Condition)",
                source_chunk_ids=[]
            ))

        if "fever" in lowered or "reduce" in lowered:
            relations.append(SVORelation(
                subject_id="ent_aspirin",
                subject_name_type="Aspirin (Drug)",
                relation="REDUCES",
                object_id="ent_fever",
                object_name_type="Fever (Condition)",
                source_chunk_ids=[]
            ))

        return relations


class MockConceptExtractor:
    """Mock concept extractor with hardcoded rules. Production uses learned model."""

    def extract_concepts(self, text: str) -> Dict[str, List[str]]:
        lowered = text.lower()
        provides = []
        depends_on = []

        if "controller type" in lowered or "above the worker type" in lowered:
            provides.append("hierarchy")

        if "resolution pathway" in lowered or "determined by its manager" in lowered:
            provides.append("resolution pathway")
            depends_on.append("hierarchy")

        if not provides and "hierarchy" in lowered:
            provides.append("hierarchy")

        return {
            "provides": provides,
            "depends_on": depends_on
        }


class TransformerConceptExtractor:
    """LLM-based concept extraction with document-level deduplication.

    Uses few-shot prompts (one worked example per prompt) rather than zero-shot
    instructions. Zero-shot prompting on flan-t5-large was observed to make the
    "provides" prompt echo the entire input sentence back as a single "concept"
    (no commas in its output for the comma-split parser to break on) - the parallel
    "depends_on" prompt happened to get a clean short list, but "provides" didn't,
    so the fix here is symmetric worked examples for both. See
    remote server scripts/test_concept_graph.py for the side-by-side comparison
    that led to this: zero-shot produced a 23-word "concept" (the whole sentence),
    few-shot produced 'hash table'.
    """

    MAX_CONCEPT_WORDS = 6  # defensive guard: reject anything longer as clearly not a term

    _PROVIDES_PROMPT = (
        "Extract short key terms (2-4 words each) that this text defines or "
        "introduces. Output ONLY a comma-separated list of terms, nothing else.\n\n"
        "Text: A binary search tree is a data structure where each node has at "
        "most two children, and left children are smaller than their parent.\n"
        "Terms: binary search tree\n\n"
        "Text: {text}\n"
        "Terms:"
    )
    _DEPENDS_ON_PROMPT = (
        "Extract short key terms (2-4 words each) that this text assumes or "
        "refers to but does not define. Output ONLY a comma-separated list of "
        "terms, nothing else.\n\n"
        "Text: Binary search trees are often used to implement balanced trees "
        "such as AVL trees and red-black trees.\n"
        "Terms: balanced trees, AVL trees, red-black trees\n\n"
        "Text: {text}\n"
        "Terms:"
    )

    def __init__(self, model_name: str = "google/flan-t5-large"):
        from transformers import T5Tokenizer, AutoModelForSeq2SeqLM
        self.model_name = model_name
        self.tokenizer = T5Tokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        self._embedding_model = None

    def _get_embedding_model(self):
        if self._embedding_model is None:
            from .embeddings import TransformerEmbeddingModel
            self._embedding_model = TransformerEmbeddingModel()
        return self._embedding_model

    def _extract_raw_concepts(self, text: str) -> Dict[str, List[str]]:
        import torch
        concepts = {"provides": [], "depends_on": []}
        if not text or not text.strip():
            return concepts

        prompts = {
            "provides": self._PROVIDES_PROMPT.format(text=text[:512]),
            "depends_on": self._DEPENDS_ON_PROMPT.format(text=text[:512]),
        }

        for prompt_type, prompt in prompts.items():
            try:
                inputs = self.tokenizer(prompt, return_tensors="pt", max_length=768, truncation=True)
                with torch.no_grad():
                    outputs = self.model.generate(**inputs, max_length=128, num_beams=1)
                output_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
                terms = [term.strip() for term in output_text.split(",") if term.strip()]
                terms = [t for t in terms if len(t.split()) <= self.MAX_CONCEPT_WORDS]
                concepts[prompt_type] = terms
            except Exception:
                pass

        return concepts

    def _canonicalize_concepts(self, all_raw_concepts: Dict[str, List[str]]) -> Dict[str, str]:
        if not all_raw_concepts:
            return {}

        unique_raw = list(set(all_raw_concepts.values()))
        if not unique_raw:
            return {}

        embedding_model = self._get_embedding_model()
        try:
            embeddings = embedding_model.encode(unique_raw)
        except Exception:
            return {raw: raw.strip().lower() for raw in unique_raw}

        import numpy as np
        canonical_map = {}
        clusters = []

        for i, raw in enumerate(unique_raw):
            clustered = False
            for cluster in clusters:
                cluster_reps = [unique_raw[j] for j in cluster]
                for rep_idx in cluster:
                    sim = float(np.dot(embeddings[i], embeddings[rep_idx]) / (
                        (np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[rep_idx])) + 1e-8
                    ))
                    if sim > 0.9:
                        cluster.append(i)
                        clustered = True
                        break
                if clustered:
                    break

            if not clustered:
                clusters.append([i])

        for cluster in clusters:
            cluster_terms = [unique_raw[idx] for idx in cluster]
            canonical = min(cluster_terms, key=len).strip().lower()

            for term in cluster_terms:
                canonical_map[term] = canonical

        return canonical_map

    def extract_concepts_batch(self, chunk_texts: List[str]) -> List[Dict[str, List[str]]]:
        results = []
        all_raw_concepts = {}
        raw_per_chunk = []

        for chunk_text in chunk_texts:
            raw = self._extract_raw_concepts(chunk_text)
            raw_per_chunk.append(raw)
            all_raw_concepts.update({term: term for terms_list in raw.values() for term in terms_list})

        canonical_map = self._canonicalize_concepts(all_raw_concepts)

        for raw in raw_per_chunk:
            canonicalized = {
                "provides": [canonical_map.get(term, term.strip().lower()) for term in raw.get("provides", [])],
                "depends_on": [canonical_map.get(term, term.strip().lower()) for term in raw.get("depends_on", [])]
            }
            canonicalized["provides"] = list(dict.fromkeys(canonicalized["provides"]))
            canonicalized["depends_on"] = list(dict.fromkeys(canonicalized["depends_on"]))
            results.append(canonicalized)

        return results

    def extract_concepts(self, text: str) -> Dict[str, List[str]]:
        result = self.extract_concepts_batch([text])
        return result[0] if result else {"provides": [], "depends_on": []}
