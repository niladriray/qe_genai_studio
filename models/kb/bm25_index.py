"""Per-KB in-memory BM25 index, persisted as a pickle file next to the
Chroma collection. Kept deliberately simple — rebuild the BM25Okapi object
from the stored corpus on every mutation. For a KB with a few thousand
chunks this is sub-100ms, which is cheaper than managing an incremental
index.

Lives at ``chromadb/kb/<kb-id>/text/bm25.pkl``.
"""

from __future__ import annotations

import pickle
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rank_bm25 import BM25Okapi

from utilities.customlogger import logger


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    """Cheap, deterministic tokenizer used for both corpus and queries.

    Lower-cases, keeps alphanumeric runs, drops single-character tokens so
    digits like "1" don't dominate documents full of page numbers.
    """
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]


def _matches_where(meta: Dict[str, Any], where: Optional[Dict[str, Any]]) -> bool:
    """Best-effort emulation of Chroma's metadata `where` clause.

    Supports ``{"field": value}`` equality and ``{"field": {"$in": [...]}}``.
    Anything else collapses to a permissive match — BM25 filtering is a
    pre-filter, the authoritative scope is enforced by Chroma for dense.
    """
    if not where:
        return True
    for k, v in where.items():
        val = meta.get(k)
        if isinstance(v, dict):
            if "$in" in v:
                if val not in v["$in"]:
                    return False
            elif "$eq" in v:
                if val != v["$eq"]:
                    return False
        else:
            if val != v:
                return False
    return True


class KBBM25Index:
    """Lazy, pickle-persisted BM25 index."""

    def __init__(self, persist_path: Path) -> None:
        self.persist_path = persist_path
        self._lock = threading.Lock()
        self.doc_ids: List[str] = []
        self.documents: List[str] = []
        self.metadatas: List[Dict[str, Any]] = []
        self.corpus: List[List[str]] = []
        self._bm25: Optional[BM25Okapi] = None

    # --- persistence ------------------------------------------------------

    def load(self) -> bool:
        if not self.persist_path.exists():
            return False
        try:
            with open(self.persist_path, "rb") as f:
                state = pickle.load(f)
        except Exception as e:
            logger.warning(f"BM25 load failed ({self.persist_path}): {e}")
            return False
        self.doc_ids = list(state.get("doc_ids") or [])
        self.documents = list(state.get("documents") or [])
        self.metadatas = [dict(m or {}) for m in state.get("metadatas") or []]
        self.corpus = [list(c or []) for c in state.get("corpus") or []]
        self._rebuild()
        return True

    def save(self) -> None:
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "doc_ids": self.doc_ids,
            "documents": self.documents,
            "metadatas": self.metadatas,
            "corpus": self.corpus,
        }
        tmp = self.persist_path.with_suffix(self.persist_path.suffix + ".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(state, f)
        tmp.replace(self.persist_path)

    def _rebuild(self) -> None:
        if self.corpus and any(self.corpus):
            self._bm25 = BM25Okapi(self.corpus)
        else:
            self._bm25 = None

    # --- bootstrap / mutation --------------------------------------------

    def bootstrap_from_chroma(self, collection,
                              where: Optional[Dict[str, Any]] = None) -> int:
        """Populate the index from an existing Chroma collection.

        ``where`` is passed through to ``collection.get(where=...)`` so that
        a shared collection (e.g. the generate-path ``./data/`` store where
        every domain lives in one collection) can be filtered down to this
        index's scope before bootstrap.

        Returns the number of docs indexed.
        """
        try:
            kwargs: Dict[str, Any] = {"include": ["documents", "metadatas"]}
            if where:
                kwargs["where"] = where
            raw = collection.get(**kwargs)
        except Exception as e:
            logger.warning(f"BM25 bootstrap get() failed: {e}")
            return 0
        ids = list(raw.get("ids") or [])
        docs = list(raw.get("documents") or [])
        metas = list(raw.get("metadatas") or [])
        if not ids:
            return 0
        with self._lock:
            self.doc_ids = ids
            self.documents = [d or "" for d in docs]
            self.metadatas = [dict(m or {}) for m in metas]
            self.corpus = [tokenize(d) for d in self.documents]
            self._rebuild()
            self.save()
        logger.info(f"BM25 bootstrapped {len(self.doc_ids)} docs from Chroma into {self.persist_path}")
        return len(self.doc_ids)

    def add(self, doc_ids: List[str], documents: List[str],
            metadatas: List[Dict[str, Any]]) -> None:
        if not doc_ids:
            return
        with self._lock:
            for i, d, m in zip(doc_ids, documents, metadatas):
                self.doc_ids.append(i)
                self.documents.append(d or "")
                self.metadatas.append(dict(m or {}))
                self.corpus.append(tokenize(d or ""))
            self._rebuild()
            self.save()

    def remove_where(self, predicate: Callable[[Dict[str, Any]], bool]) -> int:
        with self._lock:
            keep_ids: List[str] = []
            keep_docs: List[str] = []
            keep_meta: List[Dict[str, Any]] = []
            keep_corpus: List[List[str]] = []
            removed = 0
            for i, d, m, c in zip(self.doc_ids, self.documents, self.metadatas, self.corpus):
                if predicate(m or {}):
                    removed += 1
                    continue
                keep_ids.append(i)
                keep_docs.append(d)
                keep_meta.append(m)
                keep_corpus.append(c)
            self.doc_ids = keep_ids
            self.documents = keep_docs
            self.metadatas = keep_meta
            self.corpus = keep_corpus
            self._rebuild()
            self.save()
            return removed

    # --- querying ---------------------------------------------------------

    def query(self, question: str, k: int,
              where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if not self._bm25 or not self.doc_ids:
            return []
        toks = tokenize(question)
        if not toks:
            return []
        scores = self._bm25.get_scores(toks)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        out: List[Dict[str, Any]] = []
        rank_counter = 0
        for i in order:
            if scores[i] <= 0:
                break
            if not _matches_where(self.metadatas[i], where):
                continue
            rank_counter += 1
            out.append({
                "id": self.doc_ids[i],
                "document": self.documents[i],
                "metadata": dict(self.metadatas[i]),
                "bm25_score": float(scores[i]),
                "bm25_rank": rank_counter,
            })
            if len(out) >= k:
                break
        return out

    def __len__(self) -> int:
        return len(self.doc_ids)
