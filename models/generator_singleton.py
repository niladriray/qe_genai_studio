from threading import Lock
from typing import Optional

import domains  # noqa: F401  (triggers profile registration)
from domains.registry import default_profile, get as get_profile
from models.test_case_generator import TestCaseGenerator

_generators: dict = {}
_lock = Lock()


def get_generator(
    vector_db_path: str = "./data/",
    use_gpt_embeddings: bool = False,
    profile_name: Optional[str] = None,
) -> TestCaseGenerator:
    """
    Return a process-wide TestCaseGenerator instance keyed by domain profile.
    Avoids re-loading the HuggingFace embedding model on every Dash callback.
    """
    profile = get_profile(profile_name) if profile_name else default_profile()
    key = profile.name
    if key not in _generators:
        with _lock:
            if key not in _generators:
                _generators[key] = TestCaseGenerator(
                    vector_db_path=vector_db_path,
                    use_gpt_embeddings=use_gpt_embeddings,
                    profile=profile,
                )
    return _generators[key]


def invalidate_all() -> None:
    """Drop every cached generator so the next call rebuilds with the
    current settings (LLM backend, model, API key). Called after
    settings_store.save() when an `llm.*` key changed."""
    with _lock:
        for gen in list(_generators.values()):
            try:
                gen.close()
            except Exception:
                pass
        _generators.clear()
