"""
Legacy config constants. Values now delegate to `settings_store` so the
/config page can override them at runtime. Constants that aren't editable
at runtime (metadata key names, enum lists, embeddings model) remain as
plain class attributes.
"""

from configs import settings_store


class _DynamicFloat:
    """Behaves like a float whose value is re-read from settings_store
    on every access, so runtime changes on the /config page take effect
    without restarting the app."""

    def __init__(self, key: str):
        self._key = key

    def _v(self) -> float:
        return float(settings_store.get(self._key))

    def __float__(self): return self._v()
    def __repr__(self): return repr(self._v())
    def __str__(self): return str(self._v())
    def __mul__(self, other): return self._v() * other
    def __rmul__(self, other): return other * self._v()
    def __add__(self, other): return self._v() + other
    def __radd__(self, other): return other + self._v()
    def __sub__(self, other): return self._v() - other
    def __rsub__(self, other): return other - self._v()
    def __truediv__(self, other): return self._v() / other
    def __rtruediv__(self, other): return other / self._v()
    def __lt__(self, other): return self._v() < other
    def __le__(self, other): return self._v() <= other
    def __gt__(self, other): return self._v() > other
    def __ge__(self, other): return self._v() >= other
    def __eq__(self, other):
        try:
            return self._v() == float(other)
        except (TypeError, ValueError):
            return False
    def __ne__(self, other): return not self.__eq__(other)
    def __hash__(self): return hash(self._v())


class _ConfigMeta(type):
    """Lets `Config.DEFAULT_DOMAIN` resolve to the current settings value
    on every access, even though it's accessed via the class (not an
    instance)."""

    @property
    def DEFAULT_DOMAIN(cls) -> str:
        return settings_store.get("defaults.domain")


class Config(metaclass=_ConfigMeta):
    USE_CASE_LABEL = "usecase"
    USE_CASE_TYPE_TG = "tg"
    USE_CASE_TG_METADATA_MNE = "mne"
    USE_CASE_TG_METADATA_FMT = "fmt"
    USE_CASE_TG_METADATA_TECH = "tech"
    USE_CASE_TG_METADATA_COMPLETION = "comp"
    USE_CASE_TG_METADATA_PRIORITY = "priority"

    USE_CASE_TG_DEFAULT_PRIORITY = _DynamicFloat("priority.default")
    USE_CASE_TG_THUMBS_DOWN_PRIORITY = _DynamicFloat("priority.thumbs_down")
    USE_CASE_TG_THUMBS_UP_PRIORITY = _DynamicFloat("priority.thumbs_up")
    USE_CASE_TG_CURATED_PRIORITY = _DynamicFloat("priority.curated")
    USE_CASE_TG_PRIORITY_WEIGHT = _DynamicFloat("priority.weight")

    USE_CASE_TG_SIMILARITY_CHECK = [
        _DynamicFloat("retrieval.default_similarity_threshold"),
        "tech", "fmt", "mne",
    ]

    META_DATA_TG_FORMAT_TYPE = ["plain_text", "bdd", "other", "iqp"]
    META_DATA_TG_TECHNOLOGY_TYPE = ["mf", "api", "ui", "mobile", "data"]

    HUGGINGFACE_EMBEDDINGS = "sentence-transformers/all-MiniLM-L6-v2"
