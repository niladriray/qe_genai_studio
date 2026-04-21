"""
Persistence layer for user-defined domain profiles.

Built-in profiles (test_case, epic_to_user_story, manual_to_automation) live
in code and are immutable from the UI. Custom profiles created through the
Manage Domains page are serialised here as JSON files and auto-registered on
app startup, so the engine treats them identically to built-ins after load.
"""

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from domains.profile import DomainProfile
from domains.registry import register
from utilities.customlogger import logger


_CUSTOM_DIR = Path(__file__).parent / "custom"

# Logical fields of DomainProfile that must appear in a saved JSON payload.
_REQUIRED_FIELDS = (
    "name", "source_label", "target_label", "source_column", "target_column",
    "use_case_type", "system_role", "few_shot_template", "bare_template",
    "metadata_keys", "format_enum", "technology_enum",
)


def custom_dir() -> Path:
    _CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    return _CUSTOM_DIR


def _path_for(name: str) -> Path:
    safe = "".join(c for c in name if c.isalnum() or c in ("_", "-")).strip("_-")
    if not safe:
        raise ValueError(f"Invalid domain name for filesystem: {name!r}")
    return custom_dir() / f"{safe}.json"


def _to_profile(data: dict) -> DomainProfile:
    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        raise ValueError(f"Custom profile missing fields: {missing}")
    return DomainProfile(
        name=data["name"],
        source_label=data["source_label"],
        target_label=data["target_label"],
        source_column=data["source_column"],
        target_column=data["target_column"],
        use_case_type=data["use_case_type"],
        system_role=data["system_role"],
        few_shot_template=data["few_shot_template"],
        bare_template=data["bare_template"],
        metadata_keys=dict(data["metadata_keys"]),
        format_enum=tuple(data["format_enum"]),
        technology_enum=tuple(data["technology_enum"]),
        example_metadata_fields=tuple(data.get("example_metadata_fields", ("format", "mne", "tech"))),
        dedup_similarity_threshold=float(data.get("dedup_similarity_threshold", 0.8)),
        dedup_match_fields=tuple(data.get("dedup_match_fields", ("tech", "fmt", "mne"))),
        source_aliases=tuple(data.get("source_aliases", ())),
    )


def load_all() -> List[str]:
    """Read every custom/*.json and register it. Returns loaded names."""
    loaded = []
    for path in sorted(custom_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text())
            profile = _to_profile(data)
            register(profile)
            loaded.append(profile.name)
        except Exception as e:
            logger.error(f"Failed to load custom profile {path.name}: {e}")
    if loaded:
        logger.info(f"Loaded custom domain profiles: {loaded}")
    return loaded


def save(profile: DomainProfile) -> Path:
    """Serialise a profile to JSON and register it (overwrites if exists)."""
    path = _path_for(profile.name)
    payload = asdict(profile)
    path.write_text(json.dumps(payload, indent=2))
    register(profile)
    logger.info(f"Saved custom domain profile '{profile.name}' -> {path}")
    return path


def delete(name: str) -> bool:
    path = _path_for(name)
    if path.exists():
        path.unlink()
        logger.info(f"Deleted custom domain profile '{name}' at {path}")
        return True
    return False


def list_custom_names() -> List[str]:
    return [p.stem for p in sorted(custom_dir().glob("*.json"))]


def is_custom(name: str) -> bool:
    return _path_for(name).exists()


def load_one(name: str) -> dict:
    path = _path_for(name)
    return json.loads(path.read_text())
