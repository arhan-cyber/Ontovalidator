"""SVO and concept extractors."""

from typing import List, Dict
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
