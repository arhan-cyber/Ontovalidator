"""Base retriever interface."""

from abc import ABC, abstractmethod
from typing import List

from ..models import RetrievalResult


class BaseRetriever(ABC):
    @abstractmethod
    def retrieve(self, query: str, top_k: int) -> List[RetrievalResult]:
        pass
