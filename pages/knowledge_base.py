"""Knowledge Base page — Stitch-inspired two-pane layout.

LEFT pane: list of user-created KBs + "+ New KB" entry.
RIGHT pane: welcome / KB detail (upload + files) / chat view, switched via
a `kb-view-mode` dcc.Store.
"""

from __future__ import annotations

import base64
import os
import tempfile
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import dash
import dash_bootstrap_components as dbc
from dash import ALL, MATCH, Dash, Input, Output, State, callback_context, dcc, html

from configs import kb_registry, settings_store
from configs.config import Config
from models.kb.kb_service import KBService
from models.kb.chat_engine import KBChatEngine
from models.domain_store import (
    DOMAIN_ID_PREFIX, DomainSource, is_domain_source_id,
    profile_name_from_source_id,
)
import domains  # noqa: F401  (triggers profile registration)
from domains.registry import all_profiles, get as get_profile
from utilities.customlogger import logger


# Re-ingest is potentially minutes long (LLM summarization per page), so it
# runs in a background thread. Status is shared via this module-level dict
# and polled from the UI with a dcc.Interval.
_REINGEST_STATE: Dict[str, Dict[str, Any]] = {}
_REINGEST_LOCK = threading.Lock()

# Uploads also run off the request thread because ingestion now includes
# per-page LLM summarization. Same pattern as re-ingest: shared dict
# updated by a worker, polled from the UI by a dcc.Interval.
_INGEST_STATE: Dict[str, Dict[str, Any]] = {}
_INGEST_LOCK = threading.Lock()


def _ingest_state(kb_id: str) -> Dict[str, Any]:
    with _INGEST_LOCK:
        return dict(_INGEST_STATE.get(kb_id) or {})


def _set_ingest_state(kb_id: str, **patch: Any) -> None:
    with _INGEST_LOCK:
        cur = _INGEST_STATE.get(kb_id) or {"kb_id": kb_id}
        cur.update(patch)
        _INGEST_STATE[kb_id] = cur


def _reingest_status(kb_id: str) -> Dict[str, Any]:
    with _REINGEST_LOCK:
        return dict(_REINGEST_STATE.get(kb_id) or {})


def _set_reingest_status(kb_id: str, **patch: Any) -> None:
    with _REINGEST_LOCK:
        cur = _REINGEST_STATE.get(kb_id) or {"kb_id": kb_id}
        cur.update(patch)
        _REINGEST_STATE[kb_id] = cur


def _start_reingest(kb_id: str) -> None:
    if _reingest_status(kb_id).get("status") == "running":
        return
    _set_reingest_status(kb_id, status="running", done=0, total=0,
                         message="Starting…", skipped=[], reingested_count=0)

    def worker() -> None:
        try:
            svc = KBService(kb_id)

            def progress(fname: str, done: int, total: int) -> None:
                _set_reingest_status(
                    kb_id, status="running", done=done, total=total,
                    message=f"{done}/{total} · {fname}",
                )

            result = svc.reingest_all(progress_cb=progress)
            skipped = result.get("skipped") or []
            reingested = result.get("reingested") or []
            msg_parts = [f"Re-ingested {len(reingested)} of {result.get('total', 0)} files"]
            if skipped:
                names = ", ".join((s.get("source_file") or "?") for s in skipped[:3])
                extra = f" + {len(skipped) - 3} more" if len(skipped) > 3 else ""
                msg_parts.append(f"skipped {len(skipped)} (need re-upload): {names}{extra}")
            _set_reingest_status(
                kb_id, status="done", message=" · ".join(msg_parts),
                skipped=skipped, reingested_count=len(reingested),
            )
        except Exception as e:
            logger.exception(f"KB re-ingest thread failed for {kb_id}: {e}")
            _set_reingest_status(kb_id, status="error", message=str(e))

    threading.Thread(target=worker, daemon=True).start()


ACCEPT_EXTENSIONS = ".pdf,.docx,.pptx,.txt,.md,.markdown,.png,.jpg,.jpeg,.gif,.bmp,.webp"


def _fmt_relative(iso_ts: str) -> str:
    if not iso_ts:
        return ""
    try:
        t = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except Exception:
        return iso_ts
    now = datetime.now(timezone.utc)
    delta = now - t
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _render_kb_card(kb: Dict[str, Any], selected: bool) -> html.Div:
    doc_count = kb.get("doc_count", 0)
    files_count = len(kb.get("files", []) or [])
    subtitle = f"{files_count} file{'s' if files_count != 1 else ''} · {doc_count} chunk{'s' if doc_count != 1 else ''}"
    desc = (kb.get("description") or "").strip()
    return html.Div(
        [
            html.Div(
                [
                    html.Div(kb["name"], className="kb-card-title"),
                    html.Button(
                        "\u2715",
                        id={"type": "kb-delete-kb", "id": kb["id"]},
                        title="Delete knowledge base",
                        n_clicks=0,
                        className="kb-card-delete",
                        **{"aria-label": f"Delete knowledge base {kb['name']}"},
                    ),
                ],
                className="kb-card-header",
            ),
            html.Div(desc or "No description.", className="kb-card-desc"),
            html.Div(
                [
                    html.Span(subtitle, className="kb-card-stats"),
                    html.Span(_fmt_relative(kb.get("updated_at", "")), className="kb-card-updated"),
                ],
                className="kb-card-footer",
            ),
        ],
        id={"type": "kb-card", "id": kb["id"]},
        n_clicks=0,
        className="kb-card kb-card--selected" if selected else "kb-card",
    )


def _domain_source_summary(profile) -> Dict[str, Any]:
    """Build a KB-like dict describing a domain source for sidebar + chat."""
    try:
        count = DomainSource(profile.name).record_count()
    except Exception:
        count = 0
    return {
        "id": f"{DOMAIN_ID_PREFIX}{profile.name}",
        "name": f"{profile.source_label} \u2192 {profile.target_label}",
        "description": (
            f"Curated {profile.source_label.lower()} / "
            f"{profile.target_label.lower()} pairs from the generate path."
        ),
        "doc_count": count,
        "kind": "domain",
    }


def _render_domain_card(summary: Dict[str, Any], selected: bool) -> html.Div:
    subtitle = f"{summary.get('doc_count', 0)} pairs"
    return html.Div(
        [
            html.Div(
                [
                    html.Span("\U0001F4CA", className="kb-card-icon",
                              **{"aria-hidden": "true"}),
                    html.Div(summary["name"], className="kb-card-title"),
                ],
                className="kb-card-header",
            ),
            html.Div(summary.get("description") or "", className="kb-card-desc"),
            html.Div(
                [html.Span(subtitle, className="kb-card-stats")],
                className="kb-card-footer",
            ),
        ],
        id={"type": "kb-card", "id": summary["id"]},
        n_clicks=0,
        className=(
            "kb-card kb-card--domain kb-card--selected"
            if selected else "kb-card kb-card--domain"
        ),
    )


def _as_id_list(selected) -> List[str]:
    """Normalize the kb-selected-id store value (which may be a legacy
    scalar string or None) into a list of ids."""
    if not selected:
        return []
    if isinstance(selected, str):
        return [selected]
    return [s for s in selected if s]


def _sel_key(selected_ids: List[str]) -> str:
    """Stable composite key used to scope chat history to a selection."""
    return "|".join(sorted(_as_id_list(selected_ids)))


def _render_kb_list(selected) -> List[html.Div]:
    selected_ids = set(_as_id_list(selected))
    kbs = kb_registry.list_kbs()
    children: List[Any] = []
    if kbs:
        kbs = sorted(kbs, key=lambda k: k.get("updated_at", ""), reverse=True)
        children.extend(
            _render_kb_card(kb, selected=(kb["id"] in selected_ids))
            for kb in kbs
        )
    else:
        children.append(
            html.Div(
                "No knowledge bases yet. Click + New KB to create one.",
                className="kb-empty-hint",
            )
        )

    if bool(settings_store.get("kb.chat.expose_domain_sources", True)):
        profiles = list(all_profiles())
        if profiles:
            children.append(
                html.Div(
                    [
                        html.Span("Domain stores", className="kb-side-section-label"),
                        html.Span("read-only", className="kb-side-section-tag"),
                    ],
                    className="kb-side-section",
                )
            )
            for profile in profiles:
                summary = _domain_source_summary(profile)
                children.append(
                    _render_domain_card(summary,
                                        selected=(summary["id"] in selected_ids))
                )
    return children


def _resolve_single_summary(sid: str) -> Dict[str, Any] | None:
    if not sid:
        return None
    if is_domain_source_id(sid):
        try:
            profile = get_profile(profile_name_from_source_id(sid))
        except Exception:
            return None
        summary = _domain_source_summary(profile)
        try:
            summary["files"] = DomainSource(profile.name).list_files()
        except Exception:
            summary["files"] = []
        return summary
    return kb_registry.get_kb(sid)


def _resolve_source_summary(selected) -> Dict[str, Any] | None:
    """Return a KB-like dict for the current selection — a real KB, a
    virtual domain source, or a synthetic combined view when multiple
    sources are selected. None if unknown / empty."""
    ids = _as_id_list(selected)
    if not ids:
        return None
    if len(ids) == 1:
        return _resolve_single_summary(ids[0])

    parts = [s for s in (_resolve_single_summary(sid) for sid in ids) if s]
    if not parts:
        return None
    names = " + ".join(p.get("name") or "?" for p in parts)
    total_docs = sum(int(p.get("doc_count") or 0) for p in parts)
    files: List[Dict[str, Any]] = []
    seen = set()
    for p in parts:
        for f in (p.get("files") or []):
            key = (f.get("file_id") or "", f.get("source_file") or "")
            if key in seen:
                continue
            seen.add(key)
            files.append(f)
    return {
        "id": _sel_key(ids),
        "name": names,
        "description": f"Combined view across {len(parts)} sources.",
        "doc_count": total_docs,
        "files": files,
        "kind": "multi",
        "member_ids": ids,
    }


def _welcome_pane() -> html.Div:
    return html.Div(
        [
            html.Div("\U0001F4DA", className="kb-welcome-icon"),
            html.H3("Your knowledge, one chat away.", className="kb-welcome-title"),
            html.P(
                "Create a knowledge base, upload documents or images, and ask questions grounded in what you uploaded.",
                className="kb-welcome-sub",
            ),
        ],
        className="kb-welcome",
    )


def _render_files_list(files: List[Dict[str, Any]]) -> html.Div:
    if not files:
        return html.Div("No files yet. Drop some above to get started.", className="kb-files-empty")
    rows = []
    for f in files:
        ctype = f.get("content_type") or "text"
        loc = "image" if ctype == "image" else f"{f.get('chunks', 0)} chunks · {f.get('pages') or 1} pages"
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(f.get("source_file", "unknown"), className="kb-file-name"),
                            html.Span(loc, className="kb-file-meta"),
                        ],
                        className="kb-file-main",
                    ),
                    html.Button(
                        "Remove",
                        id={"type": "kb-delete-file", "id": f["file_id"]},
                        n_clicks=0,
                        className="kb-file-remove",
                    ),
                ],
                className="kb-file-row",
            )
        )
    return html.Div(rows, className="kb-files-list")


def _detail_pane(kb: Dict[str, Any]) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H3(kb["name"], className="kb-detail-title"),
                            html.Div(kb.get("description") or "", className="kb-detail-desc"),
                        ],
                        className="kb-detail-titleblock",
                    ),
                    html.Div(
                        [
                            dbc.Button(
                                "Re-ingest",
                                id="kb-reingest-btn",
                                color="secondary",
                                outline=True,
                                className="kb-reingest-btn",
                                title=("Re-chunk and re-summarize every file in this "
                                       "KB using the current settings. Files without "
                                       "a persisted upload will need to be re-uploaded."),
                            ),
                            dbc.Button(
                                "Open chat \u2192",
                                id="kb-open-chat",
                                color="primary",
                                className="kb-open-chat-btn",
                            ),
                        ],
                        className="kb-detail-actions",
                    ),
                ],
                className="kb-detail-header",
            ),
            html.Div(id="kb-reingest-status", className="kb-reingest-status"),
            dcc.Upload(
                id="kb-upload",
                multiple=True,
                accept=ACCEPT_EXTENSIONS,
                children=html.Div(
                    [
                        html.Div("\u2191", className="kb-upload-icon"),
                        html.Div("Drop files or click to upload",
                                 className="kb-upload-primary"),
                        html.Div("PDF, DOCX, PPTX, TXT, MD, or images",
                                 className="kb-upload-secondary"),
                    ],
                    className="kb-upload-inner",
                ),
                className="kb-upload",
            ),
            html.Div(id="kb-upload-status", className="kb-upload-status"),
            html.H5("Files", className="kb-files-heading"),
            html.Div(_render_files_list(kb.get("files", []) or []), id="kb-files-list"),
        ],
        className="kb-detail",
    )


def _ref_location(ref: Dict[str, Any]) -> str:
    if ref.get("page") is not None:
        return f"p.{ref['page']}"
    if ref.get("slide") is not None:
        return f"slide {ref['slide']}"
    return ""


def _render_thumbs_cell(ref: Dict[str, Any]) -> Any:
    """Per-row 👍/👎 controls. Only rendered for ratable refs (user-KB
    text chunks); domain hits and images get an empty cell so the grid
    stays aligned."""
    kb_id = ref.get("kb_id")
    chunk_id = ref.get("chunk_id")
    if not kb_id or not chunk_id:
        return html.Div("", className="kb-ref-cell-thumbs")
    return html.Div(
        [
            html.Button(
                "\U0001F44D",
                id={"type": "kb-thumbs", "action": "up",
                    "kb_id": kb_id, "chunk_id": chunk_id},
                n_clicks=0,
                title="Boost this source for similar questions",
                className="kb-thumb-btn kb-thumb-up",
                **{"aria-label": f"Thumbs up for {ref.get('label', 'source')}"},
            ),
            html.Button(
                "\U0001F44E",
                id={"type": "kb-thumbs", "action": "down",
                    "kb_id": kb_id, "chunk_id": chunk_id},
                n_clicks=0,
                title="Demote this source for similar questions",
                className="kb-thumb-btn kb-thumb-down",
                **{"aria-label": f"Thumbs down for {ref.get('label', 'source')}"},
            ),
            html.Span(
                "",
                id={"type": "kb-thumbs-status",
                    "kb_id": kb_id, "chunk_id": chunk_id},
                className="kb-thumbs-status",
            ),
        ],
        className="kb-ref-cell-thumbs",
    )


def _render_references_panel(turn: Dict[str, Any]) -> Any:
    refs = turn.get("references") or []
    if not refs:
        return None

    rows = []
    for r in refs:
        loc = _ref_location(r)
        file_label = r.get("file") or "source"
        sim = r.get("similarity")
        sim_text = f"{sim:.2f}" if isinstance(sim, (int, float)) else "—"
        title_parts: List[Any] = [html.Span(file_label, className="kb-ref-file")]
        if loc:
            title_parts.append(html.Span(f" · {loc}", className="kb-ref-loc"))
        snippet = (r.get("snippet") or "").strip()
        cell_children = [html.Div(title_parts, className="kb-ref-cell-title")]
        if snippet:
            cell_children.append(html.Div(snippet, className="kb-ref-cell-snippet"))
        rows.append(
            html.Div(
                [
                    html.Div(r.get("label", "?"), className="kb-ref-cell-label"),
                    html.Div(sim_text, className="kb-ref-cell-sim"),
                    html.Div(cell_children, className="kb-ref-cell-main"),
                    _render_thumbs_cell(r),
                ],
                className="kb-ref-row",
            )
        )

    scope = turn.get("scope")
    auto_scoped = turn.get("auto_scoped")
    summary_children: List[Any] = [
        html.Span(f"References ({len(refs)})", className="kb-ref-summary-label"),
    ]
    if scope:
        tag = "auto-scoped to" if auto_scoped else "scoped to"
        summary_children.append(
            html.Span(f"· {tag} {', '.join(scope)}", className="kb-ref-summary-scope")
        )

    return html.Details(
        [
            html.Summary(summary_children, className="kb-ref-summary"),
            html.Div(rows, className="kb-ref-list"),
        ],
        className="kb-ref-details",
    )


_CONTENT_TYPE_LABEL = {
    "file_summary": "File summary",
    "page_summary": "Page summary",
    "text": "Source passage",
    "parent": "Source passage",
}


def _cite_modal_title(ctx: Dict[str, Any]) -> str:
    file_label = ctx.get("file") or "Source"
    loc_bits: List[str] = []
    if ctx.get("page") is not None:
        loc_bits.append(f"page {ctx['page']}")
    elif ctx.get("slide") is not None:
        loc_bits.append(f"slide {ctx['slide']}")
    suffix = f" · {' · '.join(loc_bits)}" if loc_bits else ""
    return f"{file_label}{suffix}"


def _cite_modal_body(ctx: Dict[str, Any]) -> Any:
    chunk_text = (ctx.get("chunk_text") or "").strip()
    parent_text = (ctx.get("parent_text") or "").strip()
    kind_label = _CONTENT_TYPE_LABEL.get(
        ctx.get("content_type") or "text", "Source passage",
    )

    # Summary chunks (or pre-Phase-4 KBs without parents) just show the
    # body verbatim — no parent window exists.
    if not parent_text:
        return html.Div(
            [
                html.Div(kind_label, className="kb-cite-section-label"),
                html.Pre(chunk_text or "(empty)",
                         className="kb-cite-body kb-cite-body-plain"),
            ],
            className="kb-cite-modal-inner",
        )

    # Parent text exists. Highlight the cited child chunk inside the
    # parent window when it's a clean substring; otherwise show both
    # blocks separately.
    if chunk_text and chunk_text in parent_text:
        before, _, after = parent_text.partition(chunk_text)
        body_pre = html.Pre(
            [
                before,
                html.Mark(chunk_text, className="kb-cite-mark"),
                after,
            ],
            className="kb-cite-body",
        )
        return html.Div(
            [
                html.Div("Cited passage in context (highlighted)",
                         className="kb-cite-section-label"),
                body_pre,
            ],
            className="kb-cite-modal-inner",
        )

    return html.Div(
        [
            html.Div("Cited passage", className="kb-cite-section-label"),
            html.Pre(chunk_text or "(empty)",
                     className="kb-cite-body kb-cite-body-cited"),
            html.Div("Surrounding context",
                     className="kb-cite-section-label"),
            html.Pre(parent_text, className="kb-cite-body"),
        ],
        className="kb-cite-modal-inner",
    )


def _render_message(turn: Dict[str, Any]) -> html.Div:
    role = turn.get("role", "user")
    bubble_cls = "kb-msg kb-msg--user" if role == "user" else "kb-msg kb-msg--assistant"
    content = turn.get("content") or ""
    children: List[Any] = [dcc.Markdown(content, className="kb-msg-content")]
    cites = turn.get("citations") or []
    if cites:
        chips = []
        for c in cites:
            label_parts = [c.get("label", "?"), " "]
            file_label = c.get("file") or "source"
            loc = _ref_location(c)
            label_parts.append(file_label)
            if loc:
                label_parts.append(f" · {loc}")
            label_text = "".join(label_parts)
            kb_id = c.get("kb_id")
            chunk_id = c.get("chunk_id")
            if kb_id and chunk_id:
                chips.append(
                    html.Button(
                        label_text,
                        id={"type": "kb-cite", "kb_id": kb_id,
                            "chunk_id": chunk_id},
                        n_clicks=0,
                        className="kb-cite-chip kb-cite-chip-btn",
                        title="Show full source passage",
                    )
                )
            else:
                chips.append(
                    dbc.Badge(label_text, color="light",
                              text_color="primary", pill=True,
                              className="kb-cite-chip")
                )
        children.append(html.Div(chips, className="kb-cite-row"))
    bubble = html.Div(children, className=bubble_cls)
    if role == "assistant":
        panel = _render_references_panel(turn)
        if panel is not None:
            return html.Div([bubble, panel], className="kb-msg-wrap")
    return bubble


def _scope_options(kb: Dict[str, Any]) -> List[Dict[str, str]]:
    opts = [{"label": "All files (auto-scope)", "value": "__all__"}]
    for f in (kb.get("files") or []):
        src = f.get("source_file")
        if src:
            opts.append({"label": src, "value": src})
    return opts


def _chat_pane(kb: Dict[str, Any], history: Dict[str, Any] | None,
               scope_value: str | None) -> html.Div:
    turns: List[Dict[str, Any]] = []
    if history and history.get("kb_id") == kb["id"]:
        turns = history.get("turns") or []
    messages = [_render_message(t) for t in turns]
    if not messages:
        messages = [
            html.Div(
                [
                    html.Div("\U0001F4AC", className="kb-chat-empty-icon"),
                    html.Div(
                        f"Ask anything about \u201C{kb['name']}\u201D.",
                        className="kb-chat-empty-title",
                    ),
                    html.Div(
                        "Answers are grounded in the files you uploaded, with inline citations and a references panel.",
                        className="kb-chat-empty-sub",
                    ),
                ],
                className="kb-chat-empty",
            )
        ]
    return html.Div(
        [
            html.Div(
                [
                    html.Button("\u2190 Back", id="kb-chat-back",
                                className="kb-chat-back", n_clicks=0),
                    html.Div(
                        [
                            html.Div(kb["name"], className="kb-chat-title"),
                            html.Div(f"{len(kb.get('files', []) or [])} files · {kb.get('doc_count', 0)} chunks",
                                     className="kb-chat-sub"),
                        ],
                        className="kb-chat-titleblock",
                    ),
                    html.Div(
                        [
                            html.Label("Scope", htmlFor="kb-chat-scope-select",
                                       className="kb-scope-label"),
                            dbc.Select(
                                id="kb-chat-scope-select",
                                options=_scope_options(kb),
                                value=scope_value or "__all__",
                                className="kb-scope-select",
                            ),
                        ],
                        className="kb-scope-wrap",
                    ),
                ],
                className="kb-chat-header",
            ),
            html.Div(messages, id="kb-messages", className="kb-messages"),
            html.Div(
                [
                    dbc.Textarea(
                        id="kb-composer",
                        placeholder="Ask a question about this knowledge base…",
                        className="kb-composer",
                        rows=2,
                    ),
                    dbc.Button("Send", id="kb-send", color="primary",
                               className="kb-send-btn", n_clicks=0),
                ],
                className="kb-composer-row",
            ),
            html.Div(id="kb-chat-status", className="kb-chat-status"),
        ],
        className="kb-chat",
    )


def _right_pane(view_mode: str, selected,
                history: Dict[str, Any] | None,
                scope_value: str | None) -> Any:
    ids = _as_id_list(selected)
    if not ids or view_mode == "welcome":
        return _welcome_pane()
    kb = _resolve_source_summary(ids)
    if kb is None:
        return _welcome_pane()
    # Multi-select always goes to chat — no single detail/upload pane makes
    # sense when multiple sources are active.
    if len(ids) > 1:
        return _chat_pane(kb, history, scope_value)
    # Domain sources are read-only: never show the detail/upload pane.
    if is_domain_source_id(ids[0]) or view_mode == "chat":
        return _chat_pane(kb, history, scope_value)
    return _detail_pane(kb)


layout = html.Div(
    [
        dcc.Store(id="kb-selected-id", storage_type="session", data=[]),
        dcc.Store(id="kb-view-mode", storage_type="session", data="welcome"),
        dcc.Store(id="kb-chat-history", storage_type="session", data={"kb_id": None, "turns": []}),
        dcc.Store(id="kb-chat-scope", storage_type="session", data="__all__"),
        dcc.Store(id="kb-refresh-tick", data=0),
        dcc.Interval(id="kb-reingest-tick", interval=2000, disabled=True),
        dcc.Interval(id="kb-ingest-tick", interval=1500, disabled=True),
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle("New Knowledge Base")),
                dbc.ModalBody(
                    [
                        dbc.Label("Name"),
                        dbc.Input(id="kb-new-name", placeholder="e.g. Billing App", type="text"),
                        html.Div(className="kb-modal-spacer"),
                        dbc.Label("Description"),
                        dbc.Textarea(id="kb-new-desc",
                                     placeholder="What lives in this knowledge base?",
                                     rows=3),
                        html.Div(id="kb-new-error", className="kb-modal-error"),
                    ]
                ),
                dbc.ModalFooter(
                    [
                        dbc.Button("Cancel", id="kb-new-cancel", color="secondary", outline=True),
                        dbc.Button("Create", id="kb-new-create", color="primary"),
                    ]
                ),
            ],
            id="kb-new-modal",
            is_open=False,
            centered=True,
        ),
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(id="kb-cite-modal-title")),
                dbc.ModalBody(id="kb-cite-modal-body", className="kb-cite-modal-body"),
                dbc.ModalFooter(
                    dbc.Button("Close", id="kb-cite-modal-close",
                               color="secondary", outline=True)
                ),
            ],
            id="kb-cite-modal",
            is_open=False,
            size="lg",
            scrollable=True,
            centered=True,
        ),
        dcc.Store(id="kb-pending-delete", data=None),
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle("Delete knowledge base?")),
                dbc.ModalBody(id="kb-delete-modal-body"),
                dbc.ModalFooter(
                    [
                        dbc.Button("Cancel", id="kb-delete-cancel",
                                   color="secondary", outline=True),
                        dbc.Button("Delete permanently",
                                   id="kb-delete-confirm", color="danger"),
                    ]
                ),
            ],
            id="kb-delete-modal",
            is_open=False,
            centered=True,
        ),
        html.Div(
            [
                html.Aside(
                    [
                        html.Div(
                            [
                                html.H3("Knowledge Bases", className="kb-side-title"),
                                dbc.Button("+ New KB", id="kb-new-btn",
                                           color="primary", size="sm",
                                           className="kb-new-btn"),
                            ],
                            className="kb-side-header",
                        ),
                        html.Div(id="kb-list", className="kb-list",
                                 children=_render_kb_list([])),
                    ],
                    className="kb-side",
                    **{"aria-label": "Knowledge base list"},
                ),
                html.Section(
                    id="kb-right-pane",
                    className="kb-right",
                    children=_welcome_pane(),
                ),
            ],
            className="kb-shell",
        ),
    ],
    className="kb-page",
)


def _decode_upload(contents: str) -> bytes:
    _, content_string = contents.split(",", 1)
    return base64.b64decode(content_string)


def _ingest_one(kb_id: str, contents: str, filename: str,
                progress_cb=None) -> Dict[str, Any]:
    raw = _decode_upload(contents)
    suffix = Path(filename).suffix or ""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(raw)
        tmp.close()
        service = KBService(kb_id)
        return service.ingest_file(tmp.name, source_filename=filename,
                                   progress_cb=progress_cb)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


_STAGE_LABELS = {
    "loading": "Loading file",
    "loaded": "Loaded",
    "chunking": "Chunking",
    "summarizing_page": "Summarizing page",
    "summarizing_file": "Building file summary",
    "indexing": "Indexing",
    "done": "Indexed",
}


def _start_ingest(kb_id: str, items: List[Dict[str, str]]) -> bool:
    """Kick off a background worker that ingests ``items`` one by one.

    ``items``: list of ``{"filename", "contents"}`` (base64 data URL).
    Returns False if a batch is already running for this KB.
    """
    if _ingest_state(kb_id).get("status") == "running":
        return False
    total = len(items)
    _set_ingest_state(
        kb_id,
        status="running",
        file_done=0,
        file_total=total,
        current="",
        stage="",
        stage_current=0,
        stage_total=0,
        message=f"Queued {total} file{'s' if total != 1 else ''}",
        results=[],
        errors=[],
    )

    def worker() -> None:
        for idx, item in enumerate(items, start=1):
            fn = item.get("filename") or "upload.bin"
            contents = item.get("contents")
            _set_ingest_state(kb_id, current=fn, stage="starting",
                              stage_current=0, stage_total=0,
                              message=f"File {idx}/{total}: {fn} — starting")

            def progress(stage: str, cur: int, tot: int, fn=fn, idx=idx) -> None:
                label = _STAGE_LABELS.get(stage, stage)
                if tot and stage in ("chunking", "summarizing_page"):
                    msg = f"File {idx}/{total}: {fn} — {label} {cur}/{tot}"
                else:
                    msg = f"File {idx}/{total}: {fn} — {label}"
                _set_ingest_state(kb_id, stage=stage, stage_current=cur,
                                  stage_total=tot, message=msg)

            try:
                rec = _ingest_one(kb_id, contents, fn, progress_cb=progress)
                state = _ingest_state(kb_id)
                results = list(state.get("results") or [])
                results.append({"filename": fn, "chunks": rec.get("chunks", 0),
                                "page_summaries": rec.get("page_summaries", 0),
                                "has_file_summary": rec.get("has_file_summary", False)})
                _set_ingest_state(kb_id, file_done=idx, results=results)
            except Exception as e:
                logger.exception(f"Upload ingest failed for {fn}: {e}")
                state = _ingest_state(kb_id)
                errors = list(state.get("errors") or [])
                errors.append(f"{fn}: {e}")
                _set_ingest_state(kb_id, file_done=idx, errors=errors)

        state = _ingest_state(kb_id)
        ok = len(state.get("results") or [])
        errs = len(state.get("errors") or [])
        summary_bits = [f"Indexed {ok} of {total}"]
        if errs:
            summary_bits.append(f"{errs} error{'s' if errs != 1 else ''}")
        _set_ingest_state(
            kb_id, status="done", current="", stage="done",
            message=" · ".join(summary_bits),
        )

    threading.Thread(target=worker, daemon=True).start()
    return True


def register_callbacks(app: Dash):

    @app.callback(
        Output("kb-new-modal", "is_open"),
        Output("kb-new-name", "value"),
        Output("kb-new-desc", "value"),
        Output("kb-new-error", "children"),
        Output("kb-refresh-tick", "data"),
        Output("kb-selected-id", "data", allow_duplicate=True),
        Output("kb-view-mode", "data", allow_duplicate=True),
        Input("kb-new-btn", "n_clicks"),
        Input("kb-new-cancel", "n_clicks"),
        Input("kb-new-create", "n_clicks"),
        State("kb-new-name", "value"),
        State("kb-new-desc", "value"),
        State("kb-refresh-tick", "data"),
        State("kb-selected-id", "data"),
        State("kb-view-mode", "data"),
        prevent_initial_call=True,
    )
    def handle_new_modal(_open, _cancel, _create, name, desc, tick, sel_id, view):
        trig = callback_context.triggered_id
        if trig == "kb-new-btn":
            return True, "", "", "", dash.no_update, dash.no_update, dash.no_update
        if trig == "kb-new-cancel":
            return False, dash.no_update, dash.no_update, "", dash.no_update, dash.no_update, dash.no_update
        if trig == "kb-new-create":
            name = (name or "").strip()
            if not name:
                return True, dash.no_update, dash.no_update, "Name is required.", dash.no_update, dash.no_update, dash.no_update
            try:
                kb = kb_registry.create_kb(name, desc or "")
            except Exception as e:
                logger.exception(f"create_kb failed: {e}")
                return True, dash.no_update, dash.no_update, f"Error: {e}", dash.no_update, dash.no_update, dash.no_update
            return False, "", "", "", (tick or 0) + 1, [kb["id"]], "detail"
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    @app.callback(
        Output("kb-list", "children"),
        Input("kb-selected-id", "data"),
        Input("kb-refresh-tick", "data"),
    )
    def refresh_kb_list(selected, _tick):
        return _render_kb_list(selected)

    @app.callback(
        Output("kb-selected-id", "data", allow_duplicate=True),
        Output("kb-view-mode", "data", allow_duplicate=True),
        Output("kb-chat-scope", "data", allow_duplicate=True),
        Input({"type": "kb-card", "id": ALL}, "n_clicks"),
        State({"type": "kb-card", "id": ALL}, "id"),
        State("kb-selected-id", "data"),
        prevent_initial_call=True,
    )
    def select_kb(n_clicks_list, ids, current):
        if not any(n_clicks_list or []):
            return dash.no_update, dash.no_update, dash.no_update
        trig = callback_context.triggered_id
        if not trig or "id" not in trig:
            return dash.no_update, dash.no_update, dash.no_update
        clicked = trig["id"]
        cur = _as_id_list(current)
        if clicked in cur:
            cur.remove(clicked)
        else:
            cur.append(clicked)
        # Any selection change resets the scope so a stale "scoped to X"
        # from a previous selection doesn't bleed in.
        scope_reset = "__all__"
        if not cur:
            mode = "welcome"
        elif len(cur) == 1:
            mode = "chat" if is_domain_source_id(cur[0]) else "detail"
        else:
            mode = "chat"
        return cur, mode, scope_reset

    @app.callback(
        Output("kb-view-mode", "data", allow_duplicate=True),
        Input("kb-open-chat", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_chat(n):
        if not n:
            return dash.no_update
        return "chat"

    @app.callback(
        Output("kb-view-mode", "data", allow_duplicate=True),
        Input("kb-chat-back", "n_clicks"),
        prevent_initial_call=True,
    )
    def back_to_detail(n):
        if not n:
            return dash.no_update
        return "detail"

    @app.callback(
        Output("kb-right-pane", "children"),
        Input("kb-view-mode", "data"),
        Input("kb-selected-id", "data"),
        Input("kb-refresh-tick", "data"),
        Input("kb-chat-history", "data"),
        State("kb-chat-scope", "data"),
    )
    def render_right_pane(view_mode, selected, _tick, history, scope_value):
        return _right_pane(view_mode or "welcome", selected, history, scope_value)

    @app.callback(
        Output("kb-chat-scope", "data"),
        Input("kb-chat-scope-select", "value"),
        prevent_initial_call=True,
    )
    def update_scope(value):
        return value or "__all__"

    @app.callback(
        Output("kb-upload-status", "children"),
        Output("kb-ingest-tick", "disabled"),
        Input("kb-upload", "contents"),
        State("kb-upload", "filename"),
        State("kb-selected-id", "data"),
        prevent_initial_call=True,
    )
    def handle_upload(contents, filenames, selected):
        ids = _as_id_list(selected)
        if not contents or len(ids) != 1:
            return dash.no_update, dash.no_update
        kb_id = ids[0]
        contents_list = contents if isinstance(contents, list) else [contents]
        filenames_list = filenames if isinstance(filenames, list) else [filenames]
        items = [
            {"filename": fn or "upload.bin", "contents": c}
            for c, fn in zip(contents_list, filenames_list) if c
        ]
        if not items:
            return dash.no_update, dash.no_update
        started = _start_ingest(kb_id, items)
        if not started:
            return (
                html.Div("An ingest is already running for this KB — wait for it to finish.",
                         className="kb-status-err"),
                False,
            )
        return (
            html.Div(
                [
                    html.Span(className="kb-spinner", **{"aria-hidden": "true"}),
                    html.Span(f"Starting ingest of {len(items)} file{'s' if len(items) != 1 else ''}…",
                              className="kb-ingest-msg"),
                ],
                className="kb-ingest-status",
            ),
            False,
        )

    @app.callback(
        Output("kb-upload-status", "children", allow_duplicate=True),
        Output("kb-ingest-tick", "disabled", allow_duplicate=True),
        Output("kb-refresh-tick", "data", allow_duplicate=True),
        Input("kb-ingest-tick", "n_intervals"),
        State("kb-selected-id", "data"),
        State("kb-refresh-tick", "data"),
        prevent_initial_call=True,
    )
    def poll_ingest(_n, selected, tick):
        ids = _as_id_list(selected)
        if len(ids) != 1:
            return dash.no_update, True, dash.no_update
        kb_id = ids[0]
        state = _ingest_state(kb_id)
        status = state.get("status")
        if not status or status == "idle":
            return dash.no_update, True, dash.no_update

        file_done = int(state.get("file_done") or 0)
        file_total = int(state.get("file_total") or 0)
        message = state.get("message") or ""

        if status == "running":
            progress_text = f"{file_done}/{file_total} done" if file_total else ""
            inner = html.Div(
                [
                    html.Span(className="kb-spinner", **{"aria-hidden": "true"}),
                    html.Div(
                        [
                            html.Div(message, className="kb-ingest-msg"),
                            html.Div(progress_text, className="kb-ingest-sub") if progress_text else None,
                        ],
                        className="kb-ingest-body",
                    ),
                ],
                className="kb-ingest-status",
            )
            # Don't bump the refresh tick mid-run: it's an Input to
            # render_right_pane, which would rebuild the whole pane (and
            # wipe `kb-upload-status`) on every poll. Files list refreshes
            # once at the terminal status below.
            return inner, False, dash.no_update

        # status == "done" (or anything else terminal)
        results = state.get("results") or []
        errors = state.get("errors") or []
        children: List[Any] = []
        if results:
            lines = [
                f"{r['filename']}: {r['chunks']} chunks"
                + (f", {r['page_summaries']} summaries" if r.get("page_summaries") else "")
                + (" + file summary" if r.get("has_file_summary") else "")
                for r in results
            ]
            children.append(html.Div("Indexed: " + "; ".join(lines), className="kb-status-ok"))
        if errors:
            children.append(html.Div("Errors: " + "; ".join(errors), className="kb-status-err"))
        _set_ingest_state(kb_id, status="idle")
        return children, True, (tick or 0) + 1

    @app.callback(
        Output("kb-refresh-tick", "data", allow_duplicate=True),
        Input({"type": "kb-delete-file", "id": ALL}, "n_clicks"),
        State({"type": "kb-delete-file", "id": ALL}, "id"),
        State("kb-selected-id", "data"),
        State("kb-refresh-tick", "data"),
        prevent_initial_call=True,
    )
    def delete_file(n_clicks_list, ids, selected, tick):
        sel_ids = _as_id_list(selected)
        if not any(n_clicks_list or []) or len(sel_ids) != 1:
            return dash.no_update
        trig = callback_context.triggered_id
        if not trig or "id" not in trig:
            return dash.no_update
        try:
            KBService(sel_ids[0]).delete_file(trig["id"])
        except Exception as e:
            logger.exception(f"delete_file failed: {e}")
        return (tick or 0) + 1

    @app.callback(
        Output("kb-delete-modal", "is_open"),
        Output("kb-delete-modal-body", "children"),
        Output("kb-pending-delete", "data"),
        Input({"type": "kb-delete-kb", "id": ALL}, "n_clicks"),
        Input("kb-delete-cancel", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_delete_modal(n_clicks_list, _cancel_clicks):
        trig = callback_context.triggered_id
        if trig == "kb-delete-cancel":
            return False, dash.no_update, None
        if not isinstance(trig, dict) or trig.get("type") != "kb-delete-kb":
            raise dash.exceptions.PreventUpdate
        if not any(n_clicks_list or []):
            raise dash.exceptions.PreventUpdate
        kb_id = trig["id"]
        kb = kb_registry.get_kb(kb_id) or {}
        name = kb.get("name") or kb_id
        files_count = len(kb.get("files") or [])
        chunks_count = int(kb.get("doc_count") or 0)
        body = html.Div(
            [
                html.P(
                    [
                        "Are you sure you want to delete ",
                        html.Strong(name),
                        "?",
                    ],
                ),
                html.P(
                    f"{files_count} file{'s' if files_count != 1 else ''} · "
                    f"{chunks_count} indexed chunk{'s' if chunks_count != 1 else ''} "
                    "will be removed from disk.",
                    className="text-muted",
                    style={"fontSize": "13px"},
                ),
                html.P(
                    "This cannot be undone. You'll need to re-upload every "
                    "source file to rebuild it.",
                    style={"color": "var(--color-danger)", "fontSize": "13px",
                           "marginBottom": 0},
                ),
            ]
        )
        return True, body, kb_id

    @app.callback(
        Output("kb-refresh-tick", "data", allow_duplicate=True),
        Output("kb-selected-id", "data", allow_duplicate=True),
        Output("kb-view-mode", "data", allow_duplicate=True),
        Output("kb-delete-modal", "is_open", allow_duplicate=True),
        Output("kb-pending-delete", "data", allow_duplicate=True),
        Input("kb-delete-confirm", "n_clicks"),
        State("kb-pending-delete", "data"),
        State("kb-selected-id", "data"),
        State("kb-refresh-tick", "data"),
        prevent_initial_call=True,
    )
    def confirm_delete_kb(n_clicks, kb_id, selected, tick):
        if not n_clicks or not kb_id:
            raise dash.exceptions.PreventUpdate
        try:
            kb_registry.delete_kb(kb_id)
        except Exception as e:
            logger.exception(f"delete_kb failed: {e}")
            return dash.no_update, dash.no_update, dash.no_update, False, None
        cur = _as_id_list(selected)
        if kb_id in cur:
            cur.remove(kb_id)
        if not cur:
            new_view = "welcome"
        elif len(cur) == 1:
            new_view = "chat" if is_domain_source_id(cur[0]) else "detail"
        else:
            new_view = "chat"
        return (tick or 0) + 1, cur, new_view, False, None

    @app.callback(
        Output("kb-reingest-tick", "disabled"),
        Output("kb-reingest-status", "children", allow_duplicate=True),
        Input("kb-reingest-btn", "n_clicks"),
        State("kb-selected-id", "data"),
        prevent_initial_call=True,
    )
    def on_reingest_click(n_clicks, selected):
        ids = _as_id_list(selected)
        if not n_clicks or len(ids) != 1:
            return dash.no_update, dash.no_update
        kb_id = ids[0]
        if _reingest_status(kb_id).get("status") == "running":
            return False, dash.no_update
        _start_reingest(kb_id)
        return False, html.Div("Starting re-ingest…", className="kb-status-ok")

    @app.callback(
        Output("kb-reingest-status", "children"),
        Output("kb-reingest-tick", "disabled", allow_duplicate=True),
        Output("kb-refresh-tick", "data", allow_duplicate=True),
        Input("kb-reingest-tick", "n_intervals"),
        State("kb-selected-id", "data"),
        State("kb-refresh-tick", "data"),
        prevent_initial_call=True,
    )
    def poll_reingest(_n, selected, tick):
        ids = _as_id_list(selected)
        if len(ids) != 1:
            return dash.no_update, True, dash.no_update
        kb_id = ids[0]
        state = _reingest_status(kb_id)
        status = state.get("status")
        if not status or status == "idle":
            return dash.no_update, True, dash.no_update
        if status == "running":
            done = state.get("done", 0)
            total = state.get("total", 0)
            msg = state.get("message") or "Re-ingesting…"
            return (
                html.Div(f"Re-ingesting: {msg}", className="kb-status-ok"),
                False,
                dash.no_update,
            )
        # done or error
        cls = "kb-status-ok" if status == "done" else "kb-status-err"
        msg = state.get("message") or status
        children = [html.Div(msg, className=cls)]
        skipped = state.get("skipped") or []
        if skipped:
            children.append(
                html.Div(
                    "Files needing re-upload: " + ", ".join(
                        (s.get("source_file") or "?") for s in skipped
                    ),
                    className="kb-status-err",
                )
            )
        return children, True, (tick or 0) + 1

    @app.callback(
        Output("kb-chat-history", "data"),
        Output("kb-composer", "value"),
        Output("kb-chat-status", "children"),
        Input("kb-send", "n_clicks"),
        State("kb-composer", "value"),
        State("kb-selected-id", "data"),
        State("kb-chat-history", "data"),
        State("kb-chat-scope", "data"),
        running=[
            (Output("kb-send", "disabled"), True, False),
            (Output("kb-send", "children"),
             [html.Span(className="kb-send-spinner",
                        **{"aria-hidden": "true"}),
              html.Span("Searching…", className="kb-send-label")],
             "Send"),
        ],
        prevent_initial_call=True,
    )
    def send_message(n_clicks, text, selected, history, scope_value):
        sel_ids = _as_id_list(selected)
        if not n_clicks or not sel_ids:
            return dash.no_update, dash.no_update, dash.no_update
        text = (text or "").strip()
        if not text:
            return dash.no_update, dash.no_update, "Type a question first."

        hist_key = _sel_key(sel_ids)
        history = history or {"kb_id": None, "turns": []}
        if history.get("kb_id") != hist_key:
            history = {"kb_id": hist_key, "turns": []}
        turns = list(history.get("turns") or [])
        turns.append({"role": "user", "content": text,
                      "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")})

        explicit_scope: List[str] | None = None
        if scope_value and scope_value != "__all__":
            explicit_scope = [scope_value]

        engine_arg = sel_ids[0] if len(sel_ids) == 1 else sel_ids
        try:
            result = KBChatEngine(engine_arg).answer(
                turns[:-1], text, source_files=explicit_scope
            )
        except Exception as e:
            logger.exception(f"KBChat answer failed: {e}")
            turns.append({"role": "assistant",
                          "content": f"_Error: {e}_",
                          "citations": [],
                          "references": [],
                          "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            return {"kb_id": hist_key, "turns": turns}, "", f"Error: {e}"

        turns.append({
            "role": "assistant",
            "content": result.get("answer", ""),
            "citations": result.get("citations", []),
            "references": result.get("references", []),
            "scope": result.get("scope"),
            "auto_scoped": result.get("auto_scoped", False),
            "summary_intent": result.get("summary_intent", False),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        refs = result.get("references") or []
        text_n = sum(1 for r in refs if r.get("kind") == "text")
        image_n = sum(1 for r in refs if r.get("kind") == "image")
        status = (
            f"Answered in {result.get('latency_ms', 0)}ms · "
            f"k={result.get('k', '?')} · {text_n} text · {image_n} image sources"
        )
        if result.get("auto_scoped"):
            status += f" · auto-scoped to {', '.join(result.get('scope') or [])}"
        elif result.get("scope"):
            status += f" · scoped to {', '.join(result['scope'])}"
        return {"kb_id": hist_key, "turns": turns}, "", status

    @app.callback(
        Output({"type": "kb-thumbs-status",
                "kb_id": MATCH, "chunk_id": MATCH}, "children"),
        Input({"type": "kb-thumbs", "action": ALL,
               "kb_id": MATCH, "chunk_id": MATCH}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_thumbs_feedback(n_clicks_list):
        if not any(n_clicks_list or []):
            raise dash.exceptions.PreventUpdate
        trig = callback_context.triggered_id
        if not trig or trig.get("type") != "kb-thumbs":
            raise dash.exceptions.PreventUpdate
        action = trig.get("action")
        kb_id = trig.get("kb_id")
        chunk_id = trig.get("chunk_id")
        if not kb_id or not chunk_id or action not in ("up", "down"):
            raise dash.exceptions.PreventUpdate
        priority = float(
            Config.USE_CASE_TG_THUMBS_UP_PRIORITY if action == "up"
            else Config.USE_CASE_TG_THUMBS_DOWN_PRIORITY
        )
        try:
            ok = KBService(kb_id).set_chunk_priority(chunk_id, priority)
        except Exception as e:
            logger.exception(f"thumbs feedback failed for {kb_id}/{chunk_id}: {e}")
            return f"⚠ {e}"
        if not ok:
            return "⚠ not saved"
        return "\U0001F44D saved" if action == "up" else "\U0001F44E saved"

    @app.callback(
        Output("kb-cite-modal", "is_open"),
        Output("kb-cite-modal-title", "children"),
        Output("kb-cite-modal-body", "children"),
        Input({"type": "kb-cite", "kb_id": ALL, "chunk_id": ALL}, "n_clicks"),
        Input("kb-cite-modal-close", "n_clicks"),
        State("kb-cite-modal", "is_open"),
        prevent_initial_call=True,
    )
    def show_cite_modal(_chip_clicks, _close_clicks, is_open):
        trig = callback_context.triggered_id
        if trig == "kb-cite-modal-close":
            return False, dash.no_update, dash.no_update
        if not isinstance(trig, dict) or trig.get("type") != "kb-cite":
            raise dash.exceptions.PreventUpdate
        # Filter out the spurious n_clicks=0 from layout-mount that pattern
        # matching can fire on first render.
        if not any(_chip_clicks or []):
            raise dash.exceptions.PreventUpdate
        kb_id = trig.get("kb_id")
        chunk_id = trig.get("chunk_id")
        try:
            ctx = KBService(kb_id).get_parent_context(chunk_id)
        except Exception as e:
            logger.exception(f"cite modal lookup failed for {kb_id}/{chunk_id}: {e}")
            return True, "Source unavailable", html.Div(f"Error: {e}", className="kb-cite-error")
        if ctx is None:
            return True, "Source unavailable", html.Div(
                "This source no longer exists in the knowledge base — it may "
                "have been deleted or re-ingested.",
                className="kb-cite-error",
            )
        return True, _cite_modal_title(ctx), _cite_modal_body(ctx)
