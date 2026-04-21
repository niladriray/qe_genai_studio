"""
Runtime-editable settings overlay.

Ships with defaults defined here; operators can override any value from
the /config page, which writes `configs/settings.json`. All code that
needs a configurable value should go through `settings_store.get(...)`
so changes take effect without redeployment.

Keys are dotted strings (e.g. "llm.backend"). LLM-group changes
invalidate the cached TestCaseGenerator instances so the next request
rebuilds with the new backend/model/key.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


_THIS_DIR = Path(__file__).parent
_SETTINGS_FILE = _THIS_DIR / "settings.json"

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


# Defaults mirror the pre-existing Config constants and env-var-driven
# behaviour so the app boots identically to before on a machine with no
# settings.json yet.
_DEFAULTS: Dict[str, Any] = {
    "llm.backend": os.environ.get("LLM_BACKEND", "openai").lower(),
    "llm.openai.model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    "llm.openai.api_key": os.environ.get("OPENAI_API_KEY", ""),
    "llm.ollama.model": os.environ.get("OLLAMA_MODEL", "llama3"),
    "llm.ollama.base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    "llm.ollama.think": False,

    "retrieval.default_similarity_threshold": 0.8,
    "retrieval.default_k": 5,
    "retrieval.min_context_similarity": 0.25,

    "priority.default": 0.5,
    "priority.thumbs_up": 0.8,
    "priority.thumbs_down": 0.3,
    "priority.curated": 0.95,
    "priority.weight": 0.3,

    "defaults.domain": "test_case",

    # Knowledge Base retrieval
    "kb.chat.history_turns": 6,
    "kb.retrieval.hybrid": True,
    "kb.retrieval.bm25_candidates": 20,
    "kb.retrieval.dense_candidates": 20,
    "kb.retrieval.rrf_k": 60,
    "kb.retrieval.rerank": True,
    "kb.retrieval.rerank_candidates": 30,
    "kb.retrieval.rerank_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "kb.retrieval.mmr": True,
    "kb.retrieval.mmr_lambda": 0.5,

    # Knowledge Base chunking (changes require a re-ingest to take effect)
    "kb.chunk.child_size": 500,
    "kb.chunk.child_overlap": 50,
    "kb.chunk.parent_size": 1500,
    "kb.chunk.parent_overlap": 200,

    # Knowledge Base ingest-time summarization (LLM cost per page)
    "kb.summarize.enabled": True,
    "kb.summarize.per_page": True,
    "kb.summarize.per_file": True,

    # Knowledge Base retrieval: expand child chunks to their parent window
    "kb.retrieval.parent_expand": True,

    # Generate-path (domain store) retrieval — same 4-stage pipeline as KB,
    # minus parent expansion (A→B records have no parents). Toggle
    # `domain.retrieval.hybrid=False` to fall back to the legacy dense-only
    # path through StoreEmbeddings.is_duplicate.
    "domain.retrieval.hybrid": True,
    "domain.retrieval.bm25_candidates": 15,
    "domain.retrieval.dense_candidates": 15,
    "domain.retrieval.rrf_k": 60,
    "domain.retrieval.rerank": True,
    "domain.retrieval.rerank_candidates": 20,
    "domain.retrieval.rerank_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "domain.retrieval.mmr": False,        # A→B pairs are already diverse
    "domain.retrieval.mmr_lambda": 0.5,
    "domain.retrieval.priority_weight": 0.3,  # post-rerank feedback boost

    # Phase 5B: let the Generate page augment A→B examples with retrieval
    # from one or more user Knowledge Bases. Auto-scopes per row by
    # matching the row's mnemonic against KB filenames.
    "generate.kb_context.enabled": True,
    "generate.kb_context.k": 3,
    "generate.kb_context.auto_scope_mne": True,

    # Phase 5C: expose each DomainProfile as a read-only "virtual KB" in
    # the KB Chat sidebar. Flip off to hide the Domain stores section.
    "kb.chat.expose_domain_sources": True,

    # Phase 5D: HyDE (Hypothetical Document Embeddings). One extra LLM
    # call per query to synthesise a plausible answer; that answer is
    # embedded for the dense leg, while BM25 and the cross-encoder keep
    # seeing the raw question. Biggest lift on terse / summary-style
    # queries. Costs ~1s extra on gpt-4o-mini. Off by default.
    "kb.retrieval.hyde": False,
    "domain.retrieval.hyde": False,
    "generate.kb_context.hyde": False,
}

# Keys whose change forces TestCaseGenerator instances to be rebuilt.
_LLM_KEYS = frozenset(k for k in _DEFAULTS if k.startswith("llm."))

# Changing any of these keys invalidates cached generators so the next
# request picks up the new retrieval parameters without a restart.
_GENERATOR_INVALIDATING_KEYS = _LLM_KEYS | frozenset(
    k for k in _DEFAULTS
    if k.startswith("domain.retrieval.") or k.startswith("generate.kb_context.")
)


def _load_file() -> Dict[str, Any]:
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(_SETTINGS_FILE.read_text() or "{}")
    except Exception:
        return {}


def _ensure_cache() -> Dict[str, Any]:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = {**_DEFAULTS, **_load_file()}
    return _cache


def get(key: str, default: Any = None) -> Any:
    """Return the effective value for a dotted settings key."""
    cache = _ensure_cache()
    if key in cache:
        return cache[key]
    if default is not None:
        return default
    return _DEFAULTS.get(key)


def get_all() -> Dict[str, Any]:
    """Return a fresh copy of the merged settings map."""
    return dict(_ensure_cache())


def defaults() -> Dict[str, Any]:
    """Return a fresh copy of the shipped defaults."""
    return dict(_DEFAULTS)


def _invalidate_generators() -> None:
    # Imported lazily to avoid a circular import at module load time.
    try:
        from models.generator_singleton import invalidate_all
    except Exception:
        return
    invalidate_all()


def save(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Merge `updates` into stored settings and persist. Returns merged state.

    Updates are shallow-merged (dotted keys are leaves). If any LLM-group
    key changed, the cached generator singletons are invalidated so the
    next call rebuilds with the new backend/model/key.
    """
    global _cache
    with _lock:
        stored = _load_file()
        generators_need_invalidation = False
        for k, v in updates.items():
            prev = stored.get(k, _DEFAULTS.get(k))
            if prev != v and k in _GENERATOR_INVALIDATING_KEYS:
                generators_need_invalidation = True
            stored[k] = v
        _SETTINGS_FILE.write_text(json.dumps(stored, indent=2, sort_keys=True))
        _cache = {**_DEFAULTS, **stored}
        merged = dict(_cache)

    # Push OpenAI key into process env so LangChain's ChatOpenAI picks it up.
    api_key = merged.get("llm.openai.api_key") or ""
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key

    if generators_need_invalidation:
        _invalidate_generators()

    return merged


def reset(keys: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Drop selected overrides (or all). Returns merged state."""
    global _cache
    with _lock:
        if keys is None:
            if _SETTINGS_FILE.exists():
                _SETTINGS_FILE.unlink()
            stored: Dict[str, Any] = {}
        else:
            stored = _load_file()
            for k in keys:
                stored.pop(k, None)
            _SETTINGS_FILE.write_text(json.dumps(stored, indent=2, sort_keys=True))
        _cache = {**_DEFAULTS, **stored}

    _invalidate_generators()
    return dict(_cache)


def bootstrap_env() -> None:
    """Called once at app startup: push the stored API key into os.environ
    if the user hasn't already exported one in their shell."""
    merged = _ensure_cache()
    if not os.environ.get("OPENAI_API_KEY"):
        stored_key = merged.get("llm.openai.api_key") or ""
        if stored_key:
            os.environ["OPENAI_API_KEY"] = stored_key
