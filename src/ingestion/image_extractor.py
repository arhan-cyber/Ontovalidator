"""OCR text out of images so figures become searchable evidence."""

from typing import Any, Dict, Optional


class ImageExtractor:
    """Extracts text from images using pytesseract, if it is installed.

    OCR is optional: without pytesseract/Pillow every call returns None and
    ingestion carries on with the other modalities.
    """

    def __init__(self, min_confidence: float = 0.5):
        self.min_confidence = min_confidence
        try:
            import pytesseract
            self.ocr = pytesseract
        except ImportError:
            self.ocr = None

    @property
    def available(self) -> bool:
        return self.ocr is not None

    def extract_from_image(self, image_path: str) -> Optional[Dict[str, Any]]:
        if not self.available:
            return None

        try:
            from PIL import Image
            from ..models import ChunkType

            with Image.open(image_path) as img:
                data = self.ocr.image_to_data(img, output_type=self.ocr.Output.DICT)
        except Exception:
            return None

        words, confidences = [], []
        for word, conf in zip(data.get("text", []), data.get("conf", [])):
            try:
                conf_value = float(conf)
            except (TypeError, ValueError):
                continue
            if conf_value < 0 or not word.strip():
                continue
            words.append(word.strip())
            confidences.append(conf_value / 100.0)

        if not words:
            return None

        confidence = sum(confidences) / len(confidences)
        if confidence < self.min_confidence:
            return None

        return {
            "type": ChunkType.IMAGE,
            "text": " ".join(words),
            "type_metadata": {
                "image_path": image_path,
                "confidence": round(confidence, 4),
                "word_count": len(words),
            },
        }


__all__ = ["ImageExtractor"]
