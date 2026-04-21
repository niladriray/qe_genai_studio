"""Cross-encoder reranker — scores query/document pairs jointly rather than
independently like a bi-encoder.

Used as the second retrieval stage after hybrid (BM25 + dense) assembles a
candidate pool. The model lives as a module-level singleton so the first
query pays the one-time load cost and subsequent KB requests reuse it.

Default model: ``cross-encoder/ms-marco-MiniLM-L-6-v2`` (~90 MB, CPU-fast).
Scores are raw logits — higher is more relevant, magnitudes are not
normalized across queries.
"""

from __future__ import annotations

import threading
from typing import List, Sequence, Tuple

from utilities.customlogger import logger

_lock = threading.Lock()
_model = None
_loaded_name = None


def _get_model(model_name: str):
    global _model, _loaded_name
    if _model is not None and _loaded_name == model_name:
        return _model
    with _lock:
        if _model is None or _loaded_name != model_name:
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading cross-encoder reranker: {model_name}")
            _model = CrossEncoder(model_name, max_length=512)
            _loaded_name = model_name
    return _model


def score_pairs(query: str, documents: Sequence[str],
                model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> List[float]:
    """Return a list of relevance scores, one per document, for the query."""
    if not documents:
        return []
    model = _get_model(model_name)
    pairs = [(query, d or "") for d in documents]
    raw = model.predict(pairs, convert_to_numpy=True, show_progress_bar=False)
    return [float(x) for x in raw]
