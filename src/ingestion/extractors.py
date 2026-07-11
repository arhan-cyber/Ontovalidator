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
    """LLM-based concept extraction with document-level deduplication."""

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

        provides_prompt = f"Extract key concepts that are introduced or defined in this text. List as comma-separated terms:\n{text[:512]}"
        depends_on_prompt = f"Extract concepts that this text refers to or assumes but does not define. List as comma-separated terms:\n{text[:512]}"

        for prompt_type, prompt in [("provides", provides_prompt), ("depends_on", depends_on_prompt)]:
            try:
                inputs = self.tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
                with torch.no_grad():
                    outputs = self.model.generate(**inputs, max_length=128, num_beams=1)
                output_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
                extracted = [term.strip() for term in output_text.split(",") if term.strip()]
                concepts[prompt_type] = extracted
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
