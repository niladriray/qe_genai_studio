"""Sidecar store for parent-document retrieval.

Children (small retrieval chunks) live in Chroma. Their parents (larger
context windows) live here as a JSON file per KB. On retrieval we expand a
child hit to its parent so the LLM sees richer context.

Kept out of Chroma deliberately — parents are not embedded or searched,
they're just a lookup table keyed by ``parent_id``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from utilities.customlogger import logger


class ParentsStore:
    def __init__(self, persist_path: Path) -> None:
        self.persist_path = persist_path
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            if self.persist_path.exists():
                raw = json.loads(self.persist_path.read_text() or "{}")
                if isinstance(raw, dict):
                    self._data = raw
        except Exception as e:
            logger.warning(f"ParentsStore load failed ({self.persist_path}): {e}")
            self._data = {}
        self._loaded = True

    def _save(self) -> None:
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.persist_path.with_suffix(self.persist_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False))
        tmp.replace(self.persist_path)

    def add(self, entries: Dict[str, Dict[str, Any]]) -> None:
        if not entries:
            return
        with self._lock:
            self._load()
            self._data.update(entries)
            self._save()

    def get(self, parent_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._load()
            return self._data.get(parent_id)

    def get_many(self, parent_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            self._load()
            return {pid: self._data[pid] for pid in parent_ids if pid in self._data}

    def remove_where(self, predicate: Callable[[Dict[str, Any]], bool]) -> int:
        with self._lock:
            self._load()
            keep = {pid: p for pid, p in self._data.items()
                    if not predicate(p.get("metadata") or {})}
            removed = len(self._data) - len(keep)
            if removed:
                self._data = keep
                self._save()
            return removed

    def __len__(self) -> int:
        with self._lock:
            self._load()
            return len(self._data)
