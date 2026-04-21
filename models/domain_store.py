"""Retrieval facade for a single generate-path domain profile.

The generate path (Requirements → Test Cases, Epic → User Story, etc.)
historically ran a plain dense cosine search on a shared ``./data/``
Chroma collection, filtered in Python by domain / mne / tech / fmt.
Phase 5A ports it onto the same 4-stage pipeline the KB page uses —
hybrid BM25+dense with RRF, cross-encoder rerank, optional MMR — while
preserving the existing hit shape so ``TestCaseGenerator.query_similar``
and its callers don't have to change.

Parent-document expansion is deliberately skipped: A→B records are
already short and meta-dense, parents would add no value.

Metadata-match scoring (format/mne/tech overlap with the query's
metadata) is preserved as a post-pipeline tiebreaker so legacy callers
that read ``metadata_match_count`` keep working.
"""

from __future__ import annotations

import threading
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from langchain.schema import Document

from configs import settings_store
from configs.config import Config
from models.kb.bm25_index import KBBM25Index
from models.retrieval.hybrid_retriever import HybridRetriever
from utilities.customlogger import logger


DOMAIN_ID_PREFIX = "domain:"


def is_domain_source_id(source_id: str) -> bool:
    return bool(source_id) and source_id.startswith(DOMAIN_ID_PREFIX)


def profile_name_from_source_id(source_id: str) -> str:
    if not is_domain_source_id(source_id):
        raise ValueError(f"{source_id!r} is not a domain source id")
    return source_id[len(DOMAIN_ID_PREFIX):]


_BM25_DIR_NAME = "bm25"


class DomainStoreService:
    """One instance per ``DomainProfile``.

    Wraps a shared chromadb Collection (the ``./data/`` generate-path
    store, one collection across all domains) and adds a per-profile
    BM25 sidecar at ``./data/bm25/<profile.name>.pkl``. Bootstraps the
    BM25 index from Chroma on first use — zero re-ingest needed.
    """

    def __init__(self, profile, vector_db_connector,
                 db_path: str = "./data/") -> None:
        self.profile = profile
        self._vdb = vector_db_connector
        self._db_path = Path(db_path)

        # Reach the raw chromadb collection through the langchain wrapper.
        # langchain_chroma.Chroma exposes ``_collection`` as the underlying
        # chromadb Collection. We need it to issue where-clause queries +
        # embeddings-inclusive gets, which the VectorDBConnector's
        # similarity_search_by_vector doesn't support.
        self._collection = getattr(self._vdb.vector_db, "_collection", None)
        if self._collection is None:
            raise RuntimeError(
                "DomainStoreService requires the VectorDBConnector to be "
                "connected (so the underlying Chroma collection is available)."
            )

        bm25_dir = self._db_path / _BM25_DIR_NAME
        bm25_dir.mkdir(parents=True, exist_ok=True)
        self._bm25 = KBBM25Index(bm25_dir / f"{profile.name}.pkl")
        self._bm25.load()

        self._bootstrap_lock = threading.Lock()
        self._bootstrapped_this_process = len(self._bm25) > 0

        self._retriever: Optional[HybridRetriever] = None

    # --- housekeeping -----------------------------------------------------

    @property
    def domain_name(self) -> str:
        return self.profile.name

    def _ensure_bm25_bootstrapped(self) -> None:
        if self._bootstrapped_this_process:
            return
        with self._bootstrap_lock:
            if self._bootstrapped_this_process:
                return
            if self._collection.count() == 0:
                self._bootstrapped_this_process = True
                return
            if len(self._bm25) == 0:
                self._bm25.bootstrap_from_chroma(
                    self._collection, where={"domain": self.profile.name}
                )
            self._bootstrapped_this_process = True

    def mark_stale(self) -> None:
        """Signal that new records landed in Chroma so the next query
        should rebuild the BM25 index from the authoritative store.

        Called by ``TestCaseGenerator.add_test_cases`` after a successful
        write. A full re-bootstrap is fine at domain-store size (at most
        a few thousand records) and avoids the complexity of tracking
        langchain-generated ids.
        """
        with self._bootstrap_lock:
            # Force a reload from Chroma: rebuild even if pickle was
            # previously populated, since we don't know the new ids.
            if self._collection.count() > 0:
                self._bm25.bootstrap_from_chroma(
                    self._collection, where={"domain": self.profile.name}
                )
            self._bootstrapped_this_process = True

    def _get_retriever(self) -> HybridRetriever:
        if self._retriever is None:
            self._retriever = HybridRetriever(
                chroma_collection=self._collection,
                bm25_index=self._bm25,
                text_embedder=self._vdb.embedding_model,
                settings_prefix="domain.retrieval",
            )
        return self._retriever

    # --- public write path ------------------------------------------------

    def add_to_bm25(self, ids: List[str], documents: List[str],
                    metadatas: List[Dict[str, Any]]) -> None:
        """Keep the BM25 sidecar in sync on each new ``add_test_cases``."""
        if not ids:
            return
        self._ensure_bm25_bootstrapped()
        self._bm25.add(ids, documents, metadatas)

    # --- public read path -------------------------------------------------

    def query_retrieval_hits(self, query: str, k: int = 5,
                             source_files: Optional[List[str]] = None,
                             priority_fn: Optional[Callable[[Dict[str, Any]], float]] = None,
                             hyde: Optional[bool] = None,
                            ) -> List[Dict[str, Any]]:
        """Run the shared hybrid pipeline and return hits in the native
        HybridRetriever shape (the same shape KB's ``query_text`` returns).

        ``source_files`` is treated as a list of mnemonic values for the
        ``mne`` metadata field — matching how ``DomainSource.list_files``
        presents them to the KB Chat scope dropdown.
        """
        if not query:
            return []
        if bool(settings_store.get("domain.retrieval.hybrid", True)):
            self._ensure_bm25_bootstrapped()
        where = self._domain_where(mnemonics=source_files)
        return self._get_retriever().query(
            question=query,
            k=k,
            where=where,
            priority_fn=priority_fn,
            log_tag=f"DOMAIN[{self.profile.name}]",
            hyde=hyde,
        )

    def query_similar(self, query: str, k: int = 5,
                      metadata: Optional[Mapping[str, Any]] = None,
                      similarity_threshold: float = 0.0,
                     ) -> List[Dict[str, Any]]:
        """Drop-in replacement for ``StoreEmbeddings.is_duplicate(
        ..., return_similar=True)``.

        Returns hits in the existing shape::

            [{document: langchain.Document, similarity_score, priority,
              metadata_match_count, feedback_priority, combined_score,
              rerank_score?, via?, final_rank?, ...}, ...]

        sorted by ``(metadata_match_count, combined_score)`` to match
        legacy behaviour.
        """
        if not query:
            return []

        use_hybrid = bool(settings_store.get("domain.retrieval.hybrid", True))
        if use_hybrid:
            self._ensure_bm25_bootstrapped()

        where = self._domain_where()
        metadata = dict(metadata or {})
        mkeys = self.profile.metadata_keys
        fmt_key = mkeys.get("format", "fmt")
        mne_key = mkeys.get("mne", "mne")
        tech_key = mkeys.get("tech", "tech")
        prio_key = mkeys.get("priority", "priority")

        def priority_fn(meta: Dict[str, Any]) -> float:
            try:
                return float(meta.get(prio_key, Config.USE_CASE_TG_DEFAULT_PRIORITY))
            except (TypeError, ValueError):
                return float(Config.USE_CASE_TG_DEFAULT_PRIORITY)

        raw_hits = self._get_retriever().query(
            question=query,
            k=k,
            where=where,
            priority_fn=priority_fn,
            log_tag=f"DOMAIN[{self.profile.name}]",
        )

        # Apply similarity threshold (callers pass 0 to disable).
        if similarity_threshold > 0:
            raw_hits = [h for h in raw_hits
                        if h.get("similarity", 0.0) >= similarity_threshold]

        # Shape each hit into the legacy dict form.
        shaped: List[Dict[str, Any]] = []
        for h in raw_hits:
            meta = dict(h.get("metadata") or {})

            format_match = meta.get(fmt_key, meta.get("format")) == metadata.get(fmt_key)
            mne_match = meta.get(mne_key) == metadata.get(mne_key)
            tech_match = meta.get(tech_key) == metadata.get(tech_key)
            metadata_match_count = int(format_match) + int(mne_match) + int(tech_match)

            feedback_priority = priority_fn(meta)
            similarity_score = float(h.get("similarity", 0.0))
            combined_score = (
                similarity_score
                + float(Config.USE_CASE_TG_PRIORITY_WEIGHT) * feedback_priority
            )

            shaped.append({
                "document": Document(
                    page_content=h.get("document", "") or "",
                    metadata=meta,
                ),
                "similarity_score": similarity_score,
                # Legacy callers read "priority" as metadata_match_count.
                "priority": metadata_match_count,
                "metadata_match_count": metadata_match_count,
                "feedback_priority": feedback_priority,
                "combined_score": combined_score,
                # New Phase 5A diagnostic fields — opaque to legacy callers.
                "rerank_score": h.get("rerank_score"),
                "rrf_score": h.get("rrf_score"),
                "dense_rank": h.get("dense_rank"),
                "bm25_rank": h.get("bm25_rank"),
                "via": h.get("via"),
                "final_rank": h.get("final_rank"),
            })

        # Preserve legacy ranking: metadata fit first, then combined score.
        shaped.sort(
            key=lambda x: (x["metadata_match_count"], x["combined_score"]),
            reverse=True,
        )
        return shaped

    # --- helpers ----------------------------------------------------------

    def _domain_where(self, mnemonics: Optional[List[str]] = None
                      ) -> Dict[str, Any]:
        """Chroma where clause that scopes retrieval to this domain, and
        optionally narrows further to specific mnemonic values (used by the
        KB-Chat-over-domains scope dropdown)."""
        base: Dict[str, Any] = {"domain": self.profile.name}
        values = [m for m in (mnemonics or []) if m]
        if not values:
            return base
        mne_key = self.profile.metadata_keys.get("mne", "mne")
        if len(values) == 1:
            mne_clause: Dict[str, Any] = {mne_key: values[0]}
        else:
            mne_clause = {mne_key: {"$in": values}}
        return {"$and": [base, mne_clause]}

    def list_mnemonic_groups(self) -> List[Dict[str, Any]]:
        """Return a synthetic "file list" grouped by the ``mne`` metadata
        field — used by the KB Chat page to render a scope dropdown for a
        domain source. Each entry mimics the KB file shape so
        ``_scope_options`` in the page works unchanged."""
        self._ensure_bm25_bootstrapped()
        mne_key = self.profile.metadata_keys.get("mne", "mne")
        counter: Counter = Counter()
        for meta in self._bm25.metadatas:
            val = (meta or {}).get(mne_key)
            if val in (None, ""):
                val = "—"
            counter[str(val)] += 1
        # Sort by count desc then alphabetical for a stable, scanning-friendly list
        groups = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [
            {"source_file": name, "chunks": count,
             "mime_type": "domain/record", "source_file_kind": "mne"}
            for name, count in groups
        ]

    def record_count(self) -> int:
        """Total records in Chroma tagged to this domain."""
        try:
            raw = self._collection.get(where={"domain": self.profile.name},
                                       include=["metadatas"])
            ids = raw.get("ids") or []
            return len(ids)
        except Exception:
            return 0

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DomainStoreService(profile={self.profile.name}, "
            f"bm25={len(self._bm25)})"
        )


class DomainSource:
    """KB-Chat adapter that makes a generate-path domain store behave like
    a KB for the shared chat engine.

    The chat engine accesses three things: ``.kb`` (a dict with id/name),
    ``.kb_id``, ``.list_files()``, ``.query_text(...)``, ``.query_images(...)``.
    This class provides all of them by wrapping ``DomainStoreService``.
    """

    def __init__(self, profile_name: str) -> None:
        # Lazy imports to avoid pulling generator_singleton at module-load.
        from domains.registry import get as get_profile
        from models.generator_singleton import get_generator

        profile = get_profile(profile_name)
        self.profile = profile
        # Reuse the cached generator's connector so we don't spawn a second
        # embedder just to wire a DomainStoreService.
        generator = get_generator(profile_name=profile.name)
        self._service = DomainStoreService(
            profile=profile,
            vector_db_connector=generator.vector_db_connector,
        )
        self.kb_id = f"{DOMAIN_ID_PREFIX}{profile.name}"
        self.kb = {
            "id": self.kb_id,
            "name": f"{profile.source_label} → {profile.target_label}",
            "description": (
                f"Domain store — curated {profile.source_label.lower()} / "
                f"{profile.target_label.lower()} pairs from the generate path. "
                "Read-only here; add new records via the Add Context page."
            ),
            "kind": "domain",
        }

    def list_files(self) -> List[Dict[str, Any]]:
        return self._service.list_mnemonic_groups()

    def query_text(self, question: str, k: int = 5,
                   source_files: Optional[List[str]] = None,
                   hyde: Optional[bool] = None,
                   ) -> List[Dict[str, Any]]:
        hits = self._service.query_retrieval_hits(
            query=question, k=k, source_files=source_files, hyde=hyde,
        )
        for h in hits:
            # The chat engine looks for `source_file` in hit metadata when
            # rendering citations. Domain records have `mne` / `fmt` / `tech`
            # but no `source_file`, so synthesize one from the mnemonic for
            # the scope dropdown to align with citations.
            meta = h.get("metadata") or {}
            if "source_file" not in meta:
                mne_key = self.profile.metadata_keys.get("mne", "mne")
                mne_val = meta.get(mne_key) or "—"
                meta = dict(meta)
                meta["source_file"] = str(mne_val)
                h["metadata"] = meta
        return hits

    def query_images(self, question: str, k: int = 2,
                     min_similarity: float = 0.22,
                     source_files: Optional[List[str]] = None
                     ) -> List[Dict[str, Any]]:
        # Domain stores are text-only.
        return []

    def record_count(self) -> int:
        return self._service.record_count()
