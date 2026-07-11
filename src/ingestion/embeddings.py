"""Embedding models."""

import re
from typing import List, Union


class SimpleEmbeddingModel:
    """5-dimensional mock embedding model (CPU-only, no dependencies)."""

    def encode(self, texts: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(texts, str):
            texts = [texts]

        embeddings = []
        for text in texts:
            tokens = re.findall(r"\w+", text.lower())
            vector = [0.0] * 5
            for token in tokens:
                vector[abs(hash(token)) % 5] += 1.0

            norm = sum(value * value for value in vector) ** 0.5 or 1.0
            embeddings.append([round(value / norm, 4) for value in vector])

        return embeddings


class TransformerEmbeddingModel:
    """Real DistilBERT embeddings (CPU-friendly, no GPU required)."""

    def __init__(self, model_name: str = "distilbert-base-uncased"):
        from transformers import DistilBertTokenizer, AutoModel
        self.tokenizer = DistilBertTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)

    def encode(self, texts: Union[str, List[str]]) -> List[List[float]]:
        import torch

        if isinstance(texts, str):
            texts = [texts]

        inputs = self.tokenizer(texts, padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            outputs = self.model(**inputs)
            embeddings = outputs.last_hidden_state.mean(dim=1).cpu().numpy()
        return embeddings.tolist()


class TransformerSVOExtractor:
    """LLM-based SVO extraction using Flan-T5."""

    def __init__(self, model_name: str = "google/flan-t5-small"):
        from transformers import T5Tokenizer, AutoModelForSeq2SeqLM
        self.tokenizer = T5Tokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

    def extract(self, text: str):
        import torch
        from ..models import SVORelation

        prompt = f"Extract Subject-Verb-Object relations from text as 'Subject, Relation, Object'. Text: {text}"
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = self.model.generate(**inputs, max_length=64)
        output_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

        relations = []
        parts = [p.strip() for p in output_text.split(",")]
        if len(parts) >= 3:
            subject = parts[0]
            relation = parts[1]
            obj = parts[2]

            relations.append(SVORelation(
                subject_id="ent_" + re.sub(r'[^a-z0-9_]', '_', subject.lower()),
                subject_name_type=subject,
                relation=relation.upper(),
                object_id="ent_" + re.sub(r'[^a-z0-9_]', '_', obj.lower()),
                object_name_type=obj,
                source_chunk_ids=[]
            ))

        return relations
