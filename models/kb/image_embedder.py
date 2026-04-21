"""CLIP-based embedder for images and image-compatible text queries.

Text and image embeddings live in the same 512-d space so a natural-language
query can retrieve a relevant image.
"""

from __future__ import annotations

import threading
from typing import List

from utilities.customlogger import logger

_model_lock = threading.Lock()
_model = None


def _get_model(model_name: str = "sentence-transformers/clip-ViT-B-32"):
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading CLIP model: {model_name}")
                _model = SentenceTransformer(model_name)
    return _model


class CLIPImageEmbedder:
    """Thin wrapper around sentence-transformers CLIP.

    The underlying model is a module-level singleton so the first call pays
    the load cost and subsequent KBService instances reuse it.
    """

    def __init__(self, model_name: str = "sentence-transformers/clip-ViT-B-32") -> None:
        self.model_name = model_name

    @property
    def model(self):
        return _get_model(self.model_name)

    def embed_image(self, path: str) -> List[float]:
        from PIL import Image

        img = Image.open(path).convert("RGB")
        try:
            vec = self.model.encode([img])[0]
        finally:
            img.close()
        return [float(x) for x in vec]

    def embed_text(self, text: str) -> List[float]:
        vec = self.model.encode([text])[0]
        return [float(x) for x in vec]
