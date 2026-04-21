from threading import Lock
from typing import List, Optional

from domains.profile import DomainProfile

_profiles: dict = {}
_default: Optional[str] = None
_lock = Lock()


def register(profile: DomainProfile, make_default: bool = False) -> None:
    """Register a profile. First profile registered becomes the default."""
    global _default
    with _lock:
        _profiles[profile.name] = profile
        if make_default or _default is None:
            _default = profile.name


def get(name: str) -> DomainProfile:
    if name not in _profiles:
        raise KeyError(
            f"Unknown domain profile '{name}'. Known: {sorted(_profiles)}"
        )
    return _profiles[name]


def default_profile() -> DomainProfile:
    if _default is None:
        raise RuntimeError(
            "No domain profiles registered. Import domains package to trigger registration."
        )
    return _profiles[_default]


def all_profiles() -> List[DomainProfile]:
    return list(_profiles.values())
