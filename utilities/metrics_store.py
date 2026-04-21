"""
Metrics store for generation runs.

Each run is a batch (e.g. one spreadsheet upload → Generate). Stores
per-item timing breakdowns so the Metrics page can display them.
Persisted to ``data/metrics.json`` so runs survive process restarts;
the file is rewritten atomically on every mutation. Capped at the most
recent ``_MAX_RUNS`` runs.
"""

import json
import os
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_runs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_MAX_RUNS = 50

_STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "metrics.json"


def _load_from_disk() -> None:
    if not _STORE_PATH.exists():
        return
    try:
        with _STORE_PATH.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        return
    for run in runs:
        rid = run.get("run_id")
        if rid:
            _runs[rid] = run


def _save_to_disk_locked() -> None:
    """Atomic write. Caller must hold _lock."""
    try:
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"runs": list(_runs.values())}
        # Write to a temp file in the same dir, then rename — avoids partial files.
        fd, tmp_path = tempfile.mkstemp(prefix=".metrics-", suffix=".json", dir=str(_STORE_PATH.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp_path, _STORE_PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError:
        # Disk full / permission errors shouldn't break generation.
        pass


_load_from_disk()


def start_run(run_id: str, domain: str, model: str, total_items: int) -> None:
    with _lock:
        _runs[run_id] = {
            "run_id": run_id,
            "domain": domain,
            "model": model,
            "total_items": total_items,
            "started_at": time.time(),
            "finished_at": None,
            "items": [],
            "status": "running",
        }
        if len(_runs) > _MAX_RUNS:
            _runs.popitem(last=False)
        _save_to_disk_locked()


def record_item(run_id: str, index: int, source_text: str, metrics: Dict[str, Any]) -> None:
    with _lock:
        run = _runs.get(run_id)
        if run is None:
            return
        run["items"].append({
            "index": index,
            "source_preview": (source_text[:120] + "...") if len(source_text) > 120 else source_text,
            **metrics,
        })
        _save_to_disk_locked()


def finish_run(run_id: str, status: str = "done") -> None:
    with _lock:
        run = _runs.get(run_id)
        if run is None:
            return
        run["finished_at"] = time.time()
        run["status"] = status
        _save_to_disk_locked()


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        run = _runs.get(run_id)
        return dict(run) if run else None


def list_runs() -> List[Dict[str, Any]]:
    with _lock:
        result = []
        for run in reversed(_runs.values()):
            summary = {
                "run_id": run["run_id"],
                "domain": run["domain"],
                "model": run["model"],
                "total_items": run["total_items"],
                "completed_items": len(run["items"]),
                "started_at": run["started_at"],
                "finished_at": run["finished_at"],
                "status": run["status"],
            }
            if run["items"]:
                summary["avg_total_sec"] = round(
                    sum(it.get("total_sec", 0) for it in run["items"]) / len(run["items"]), 2
                )
                summary["avg_llm_sec"] = round(
                    sum(it.get("llm_sec", 0) for it in run["items"]) / len(run["items"]), 2
                )
                summary["avg_retrieval_sec"] = round(
                    sum(it.get("retrieval_sec", 0) for it in run["items"]) / len(run["items"]), 2
                )
                summary["total_run_sec"] = round(
                    sum(it.get("total_sec", 0) for it in run["items"]), 2
                )
            result.append(summary)
        return result
