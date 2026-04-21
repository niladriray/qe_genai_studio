"""JSON-backed registry for user-created Knowledge Bases.

Kept separate from `settings_store` because KB state is list-shaped and
churns independently of LLM / retrieval settings.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_THIS_DIR = Path(__file__).parent
_REGISTRY_FILE = _THIS_DIR / "kb_registry.json"
_CHROMA_ROOT = _THIS_DIR.parent / "chromadb" / "kb"

_lock = threading.Lock()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug or f"kb-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> Dict[str, Any]:
    if not _REGISTRY_FILE.exists():
        return {"kbs": []}
    try:
        data = json.loads(_REGISTRY_FILE.read_text() or "{}")
    except Exception:
        return {"kbs": []}
    if "kbs" not in data or not isinstance(data["kbs"], list):
        data["kbs"] = []
    return data


def _save(data: Dict[str, Any]) -> None:
    _REGISTRY_FILE.write_text(json.dumps(data, indent=2, sort_keys=False))


def list_kbs() -> List[Dict[str, Any]]:
    with _lock:
        return list(_load().get("kbs", []))


def get_kb(kb_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        for kb in _load().get("kbs", []):
            if kb.get("id") == kb_id:
                return dict(kb)
    return None


def chroma_root(kb_id: str) -> Path:
    return _CHROMA_ROOT / kb_id


def create_kb(name: str, description: str = "") -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("KB name is required.")
    with _lock:
        data = _load()
        existing_ids = {kb.get("id") for kb in data["kbs"]}
        base_id = slugify(name)
        kb_id = base_id
        i = 2
        while kb_id in existing_ids:
            kb_id = f"{base_id}-{i}"
            i += 1
        now = _now()
        record = {
            "id": kb_id,
            "name": name,
            "description": (description or "").strip(),
            "collection_text": f"kb_{kb_id}_text",
            "collection_image": f"kb_{kb_id}_image",
            "created_at": now,
            "updated_at": now,
            "doc_count": 0,
            "files": [],
        }
        data["kbs"].append(record)
        _save(data)
        return dict(record)


def update_kb(kb_id: str, **patch: Any) -> Optional[Dict[str, Any]]:
    with _lock:
        data = _load()
        for kb in data["kbs"]:
            if kb.get("id") == kb_id:
                kb.update(patch)
                kb["updated_at"] = _now()
                _save(data)
                return dict(kb)
    return None


def delete_kb(kb_id: str) -> bool:
    with _lock:
        data = _load()
        before = len(data["kbs"])
        data["kbs"] = [kb for kb in data["kbs"] if kb.get("id") != kb_id]
        if len(data["kbs"]) == before:
            return False
        _save(data)
    root = chroma_root(kb_id)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    return True


def add_file_record(kb_id: str, file_meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _lock:
        data = _load()
        for kb in data["kbs"]:
            if kb.get("id") == kb_id:
                kb.setdefault("files", []).append(file_meta)
                kb["doc_count"] = kb.get("doc_count", 0) + int(file_meta.get("chunks", 0) or 0)
                kb["updated_at"] = _now()
                _save(data)
                return dict(kb)
    return None


def remove_file_record(kb_id: str, file_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        data = _load()
        for kb in data["kbs"]:
            if kb.get("id") == kb_id:
                files = kb.get("files", [])
                removed_chunks = 0
                keep = []
                for f in files:
                    if f.get("file_id") == file_id:
                        removed_chunks += int(f.get("chunks", 0) or 0)
                    else:
                        keep.append(f)
                kb["files"] = keep
                kb["doc_count"] = max(0, kb.get("doc_count", 0) - removed_chunks)
                kb["updated_at"] = _now()
                _save(data)
                return dict(kb)
    return None
