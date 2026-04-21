"""Shared retrieval pipeline.

Both the Knowledge Base (per-user file stores) and the generate-path
domain stores (curated A→B pairs) drive the same 4-stage pipeline:

    1. Hybrid candidate pool: dense (Chroma) + BM25, fused with RRF.
    2. Cross-encoder rerank over the pool (query/doc pairwise).
    3. MMR diversification with rerank as relevance, cosine as diversity.
    4. Optional post-rerank ``priority_fn`` boost — this is where
       per-record feedback (thumbs up/down, curated flag) is reintroduced
       without polluting the earlier stages.

The retriever is parameterised by ``settings_prefix`` so each caller
reads its own knobs (``kb.retrieval.*`` for KB, ``domain.retrieval.*``
for domain stores). The parent-document expansion step stays in KB
code since it's KB-specific.
"""

from __future__ import annotations

import math
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from configs import settings_store
from models.kb import reranker
from models.kb.bm25_index import KBBM25Index
from models.retrieval.hyde import hyde_query
from utilities.customlogger import logger


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _shape_hits(res: Dict[str, Any],
                query_vec: Optional[List[float]] = None) -> List[Dict[str, Any]]:
    """Convert a raw ``collection.query`` result into our standard hit dicts.

    When ``query_vec`` is provided and the collection returned embeddings,
    similarity is (re)computed as real cosine(query, doc) — this is
    necessary because different Chroma collections can use different
    ``hnsw:space`` values (cosine / l2 / ip), so the reported ``distance``
    is not uniformly ``1 - cosine``. Embeddings produced by MiniLM via
    ``HuggingFaceEmbeddings`` are unit-normalized, so the dot product is
    cosine.
    """
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    embs_raw = res.get("embeddings")
    embs = embs_raw[0] if embs_raw is not None and len(embs_raw) > 0 else []
    hits: List[Dict[str, Any]] = []
    for i, (_id, doc, meta, dist) in enumerate(zip(ids, docs, metas, dists)):
        vec: Optional[List[float]] = None
        if i < len(embs) and embs[i] is not None:
            vec = list(embs[i])

        if query_vec is not None and vec is not None:
            similarity = _cosine(query_vec, vec)
        elif dist is not None:
            # Best-effort fallback when the embedding wasn't requested:
            # assume the collection space is cosine.
            similarity = 1.0 - float(dist)
        else:
            similarity = 0.0

        hit = {
            "id": _id,
            "document": doc or "",
            "metadata": meta or {},
            "distance": dist,
            "similarity": similarity,
        }
        if vec is not None:
            hit["embedding"] = vec
        hits.append(hit)
    return hits


def _rrf_merge(rankings: List[List[str]], k: int = 60) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion: score(d) = Σ 1 / (k + rank_i(d))."""
    scores: Dict[str, float] = {}
    for rank_list in rankings:
        for rank, doc_id in enumerate(rank_list):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def _mmr_select(query_vec: List[float], candidates: List[Dict[str, Any]],
                top_k: int, lambda_: float = 0.5) -> List[Dict[str, Any]]:
    """Maximal Marginal Relevance diversification.

    Relevance signal: normalized rerank score when present on every
    candidate (stronger than bi-encoder cosine); else cosine(query, doc).
    Diversity signal: cosine between candidate and already-picked docs.
    Candidates without an "embedding" field fall back to original order.
    """
    usable = [c for c in candidates if c.get("embedding")]
    unusable = [c for c in candidates if not c.get("embedding")]
    if not usable:
        return candidates[:top_k]

    has_rerank = all("rerank_score" in c for c in usable)
    rel_by_id: Dict[str, float] = {}
    if has_rerank:
        scores = [c["rerank_score"] for c in usable]
        lo, hi = min(scores), max(scores)
        span = (hi - lo) if hi > lo else 1.0
        for c in usable:
            rel_by_id[c["id"]] = (c["rerank_score"] - lo) / span

    def _rel(c: Dict[str, Any]) -> float:
        if has_rerank:
            return rel_by_id.get(c["id"], 0.0)
        return _cosine(query_vec, c["embedding"])

    pool = list(usable)
    selected: List[Dict[str, Any]] = []
    while pool and len(selected) < top_k:
        best_idx = 0
        best_score = -float("inf")
        for i, cand in enumerate(pool):
            rel = _rel(cand)
            if selected:
                div = max(_cosine(cand["embedding"], s["embedding"]) for s in selected)
            else:
                div = 0.0
            mmr = lambda_ * rel - (1.0 - lambda_) * div
            if mmr > best_score:
                best_score = mmr
                best_idx = i
        picked = dict(pool.pop(best_idx))
        picked["mmr_score"] = best_score
        selected.append(picked)

    if len(selected) < top_k and unusable:
        selected.extend(unusable[: top_k - len(selected)])
    return selected


class HybridRetriever:
    """4-stage retrieval over one Chroma collection + one BM25 index.

    Usage::

        retriever = HybridRetriever(
            chroma_collection=collection,
            bm25_index=bm25,
            text_embedder=embedder,
            settings_prefix="kb.retrieval",
        )
        hits = retriever.query("my question", k=5, where={"domain": "test_case"})
    """

    def __init__(self, *,
                 chroma_collection,
                 bm25_index: KBBM25Index,
                 text_embedder,
                 settings_prefix: str = "kb.retrieval") -> None:
        self._col = chroma_collection
        self._bm25 = bm25_index
        self._embedder = text_embedder
        self._prefix = settings_prefix.rstrip(".")
        self._llm_lock = threading.Lock()
        self._llm_cached = None

    # --- settings helpers -------------------------------------------------

    def _s(self, key: str, default: Any) -> Any:
        return settings_store.get(f"{self._prefix}.{key}", default)

    def _llm(self):
        """Lazy shared LLM for HyDE. Only built when HyDE is first invoked."""
        if self._llm_cached is None:
            with self._llm_lock:
                if self._llm_cached is None:
                    from models.llm_factory import build_llm
                    self._llm_cached = build_llm()
        return self._llm_cached

    # --- main entry point -------------------------------------------------

    def query(self, question: str, k: int = 5,
              where: Optional[Dict[str, Any]] = None,
              priority_fn: Optional[Callable[[Dict[str, Any]], float]] = None,
              priority_weight: Optional[float] = None,
              log_tag: str = "retriever",
              hyde: Optional[bool] = None,
             ) -> List[Dict[str, Any]]:
        """Run the pipeline and return the top-k hits.

        ``where`` is a Chroma metadata filter applied to the dense side and
        (when supported) the BM25 side.
        ``priority_fn`` if provided is called with each candidate's
        metadata to produce a [0, 1] boost added post-rerank; disabled when
        ``priority_weight`` resolves to 0.
        ``hyde`` if non-None overrides the ``<prefix>.hyde`` setting. When
        enabled, the LLM synthesizes a plausible short answer; that answer
        is embedded for the dense leg. BM25 and the cross-encoder keep
        seeing the raw ``question``.
        """
        count = self._col.count() if hasattr(self._col, "count") else None
        if count == 0 or not question:
            return []
        if count is not None:
            k = max(1, min(k, count))

        use_hybrid = bool(self._s("hybrid", True))
        use_rerank = bool(self._s("rerank", True))
        use_mmr = bool(self._s("mmr", True))
        use_hyde = hyde if hyde is not None else bool(self._s("hyde", False))

        # HyDE: embed the hypothetical answer instead of the raw query for
        # the dense leg. BM25 and cross-encoder still see ``question``.
        dense_text = question
        hyde_text: Optional[str] = None
        if use_hyde:
            try:
                hyde_text = hyde_query(question, hint=None, llm=self._llm())
            except Exception as e:
                logger.warning(f"{log_tag} HyDE generation failed: {e}")
                hyde_text = None
            if hyde_text:
                dense_text = hyde_text
                logger.info(
                    f"{log_tag} HyDE active: dense-leg text length "
                    f"{len(dense_text)} (raw question {len(question)})"
                )

        emb = self._embedder.embed_query(dense_text)

        # --- Stage 1: candidate pool ---------------------------------------
        candidates = (
            self._hybrid_pool(question, emb, where, k)
            if use_hybrid else
            self._dense_only_pool(question, emb, where, k, use_rerank)
        )
        if not candidates:
            return []

        # --- Stage 2: cross-encoder rerank ---------------------------------
        if use_rerank and len(candidates) > 1:
            try:
                docs = [c.get("document", "") for c in candidates]
                model_name = self._s(
                    "rerank_model", "cross-encoder/ms-marco-MiniLM-L-6-v2"
                )
                scores = reranker.score_pairs(question, docs, model_name=model_name)
                for c, s in zip(candidates, scores):
                    c["rerank_score"] = float(s)
                candidates.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
                rerank_n = int(self._s("rerank_candidates", 30) or 30)
                candidates = candidates[: max(k, min(rerank_n, len(candidates)))]
            except Exception as e:
                logger.warning(f"{log_tag} rerank failed, skipping: {e}")

        # --- Stage 2b: priority-fn boost -----------------------------------
        # Applied before MMR so the diversity step sees the boosted ranking.
        if priority_fn is not None:
            weight = (
                priority_weight if priority_weight is not None
                else float(self._s("priority_weight", 0.0) or 0.0)
            )
            if weight > 0:
                rr_scores = [c.get("rerank_score") for c in candidates
                             if c.get("rerank_score") is not None]
                if rr_scores:
                    lo, hi = min(rr_scores), max(rr_scores)
                    span = (hi - lo) if hi > lo else 1.0
                    for c in candidates:
                        if c.get("rerank_score") is None:
                            continue
                        norm = (c["rerank_score"] - lo) / span
                        try:
                            prio = float(priority_fn(c.get("metadata") or {}) or 0.0)
                        except Exception:
                            prio = 0.0
                        prio = max(0.0, min(1.0, prio))
                        c["priority_score"] = prio
                        c["boosted_score"] = (1 - weight) * norm + weight * prio
                    candidates.sort(
                        key=lambda x: x.get("boosted_score", 0.0),
                        reverse=True,
                    )

        # --- Stage 3: MMR diversification ----------------------------------
        if use_mmr and len(candidates) > 1:
            lambda_ = float(self._s("mmr_lambda", 0.5) or 0.5)
            lambda_ = max(0.0, min(1.0, lambda_))
            results = _mmr_select(emb, candidates, top_k=k, lambda_=lambda_)
        else:
            results = candidates[:k]

        for i, c in enumerate(results):
            c["final_rank"] = i
        return results

    # --- candidate pools --------------------------------------------------

    def _dense_only_pool(self, question: str, emb: List[float],
                         where: Optional[Dict[str, Any]], k: int,
                         use_rerank: bool) -> List[Dict[str, Any]]:
        count = self._col.count() if hasattr(self._col, "count") else k
        candidate_n = max(
            k,
            int(self._s("rerank_candidates", 30) or 30) if use_rerank else k,
        )
        candidate_n = min(candidate_n, count) if count else candidate_n
        kwargs: Dict[str, Any] = {
            "query_embeddings": [emb],
            "n_results": candidate_n,
            "include": ["documents", "metadatas", "distances", "embeddings"],
        }
        if where is not None:
            kwargs["where"] = where
        res = self._col.query(**kwargs)
        hits = _shape_hits(res, query_vec=emb)
        for i, h in enumerate(hits):
            h["via"] = "dense"
            h["dense_rank"] = i
            h["bm25_rank"] = None
        return hits

    def _hybrid_pool(self, question: str, emb: List[float],
                     where: Optional[Dict[str, Any]], k: int
                    ) -> List[Dict[str, Any]]:
        count = self._col.count() if hasattr(self._col, "count") else None
        dense_n = int(self._s("dense_candidates", 20) or 20)
        bm25_n = int(self._s("bm25_candidates", 20) or 20)
        rrf_k = int(self._s("rrf_k", 60) or 60)
        if count is not None:
            dense_n = max(k, min(dense_n, count))

        dense_kwargs: Dict[str, Any] = {
            "query_embeddings": [emb],
            "n_results": dense_n,
            "include": ["documents", "metadatas", "distances", "embeddings"],
        }
        if where is not None:
            dense_kwargs["where"] = where
        dense_res = self._col.query(**dense_kwargs)
        dense_hits = _shape_hits(dense_res, query_vec=emb)
        dense_by_id = {h["id"]: h for h in dense_hits}
        dense_rank = {h["id"]: i for i, h in enumerate(dense_hits)}

        bm25_hits = self._bm25.query(question, k=bm25_n, where=where)
        bm25_by_id = {h["id"]: h for h in bm25_hits}
        bm25_rank = {h["id"]: h["bm25_rank"] - 1 for h in bm25_hits}

        fused = _rrf_merge(
            [list(dense_rank.keys()), list(bm25_rank.keys())],
            k=rrf_k,
        )

        # Fill cosine + embedding for BM25-only hits so MMR and the
        # references UI always have real numbers.
        missing_ids = [doc_id for doc_id, _ in fused
                       if doc_id not in dense_by_id and doc_id in bm25_by_id]
        backfill: Dict[str, Tuple[float, List[float]]] = {}
        if missing_ids:
            try:
                got = self._col.get(ids=missing_ids, include=["embeddings"])
                got_ids = got.get("ids") or []
                got_embs = got.get("embeddings")
                if got_embs is None:
                    got_embs = []
                for idx, doc_id in enumerate(got_ids):
                    if idx >= len(got_embs):
                        continue
                    vec = got_embs[idx]
                    if vec is None:
                        continue
                    vec_list = list(vec)
                    backfill[doc_id] = (_cosine(emb, vec_list), vec_list)
            except Exception as e:
                logger.debug(f"cosine-backfill fetch failed: {e}")

        candidates: List[Dict[str, Any]] = []
        for doc_id, rrf_score in fused:
            in_dense = doc_id in dense_by_id
            in_bm25 = doc_id in bm25_by_id
            if in_dense:
                hit = dict(dense_by_id[doc_id])
            elif in_bm25:
                src = bm25_by_id[doc_id]
                sim, vec = backfill.get(doc_id, (0.0, []))
                hit = {
                    "id": doc_id,
                    "document": src["document"],
                    "metadata": dict(src["metadata"]),
                    "distance": 1.0 - sim,
                    "similarity": sim,
                }
                if vec:
                    hit["embedding"] = vec
            else:
                continue
            hit["rrf_score"] = rrf_score
            hit["dense_rank"] = dense_rank.get(doc_id)
            hit["bm25_rank"] = bm25_rank.get(doc_id)
            hit["via"] = (
                "hybrid" if in_dense and in_bm25 else
                "dense" if in_dense else "bm25"
            )
            candidates.append(hit)
        return candidates
