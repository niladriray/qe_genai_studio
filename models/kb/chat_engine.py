"""Chat engine for a Knowledge Base — grounded Q&A with inline citations."""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from configs import settings_store
from models.kb.kb_service import KBService
from models.kb.retrieval_utils import (
    is_summary_intent,
    resolve_file_scope,
    retrieval_k_for,
)
from models.llm_factory import build_llm
from utilities.customlogger import logger


def _build_source(source_id: str):
    """Return a KBService-like object for either a user KB id or a
    ``domain:<profile_name>`` virtual id."""
    from models.domain_store import DomainSource, is_domain_source_id, profile_name_from_source_id

    if is_domain_source_id(source_id):
        return DomainSource(profile_name_from_source_id(source_id))
    return KBService(source_id)


_CITE_RE = re.compile(r"\[(S|I)(\d+)\]")


def _snippet(text: str, n: int = 220) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= n:
        return text
    return text[:n].rstrip() + "…"


def _location_label(meta: Dict[str, Any]) -> str:
    if meta.get("page") is not None:
        return f"page {meta['page']}"
    if meta.get("slide") is not None:
        return f"slide {meta['slide']}"
    return ""


def _is_domain_hit(hit: Dict[str, Any]) -> bool:
    """A hit originating from a generate-path domain store — not a user KB."""
    meta = hit.get("metadata") or {}
    # Domain records are tagged with a non-empty `domain` + always carry a
    # `completion` (the paired target artifact). User KB records may have
    # neither.
    return bool(meta.get("domain")) and ("completion" in meta or "comp" in meta)


def _profile_labels(domain_name: str) -> tuple:
    """Return (source_label, target_label) for a domain, with safe fallbacks."""
    try:
        from domains.registry import get as get_profile
        profile = get_profile(domain_name)
        return profile.source_label, profile.target_label
    except Exception:
        return "Source", "Target"


def _format_domain_source(idx: int, hit: Dict[str, Any]) -> str:
    """Render a [S#] block for a domain-store record.

    Makes metadata (Application / Technology / Format) visible to the LLM
    as fields — NOT as a filename — and surfaces the paired target
    (completion) alongside the source chunk so questions like
    *"what user stories exist for App X?"* have the answer in-prompt.
    """
    meta = hit.get("metadata") or {}
    mne = meta.get("mne") or "—"
    tech = meta.get("tech") or "—"
    fmt = meta.get("fmt") or meta.get("format") or "—"
    domain_name = meta.get("domain") or ""
    source_lbl, target_lbl = _profile_labels(domain_name)

    source_body = (hit.get("document") or "").strip()
    target_body = (meta.get("completion") or meta.get("comp") or "").strip()

    lines = [f"[S{idx}] Application: {mne} | Technology: {tech} | Format: {fmt}"]
    if source_body:
        lines.append(f"    {source_lbl}: \"{_snippet(source_body, n=350)}\"")
    if target_body:
        lines.append(f"    {target_lbl}: \"{_snippet(target_body, n=450)}\"")
    return "\n".join(lines)


def build_prompt(kb_name: str,
                 history: List[Dict[str, Any]],
                 question: str,
                 text_hits: List[Dict[str, Any]],
                 image_hits: List[Dict[str, Any]],
                 scoped_files: Optional[List[str]] = None) -> str:
    lines: List[str] = []
    lines.append(
        f"You are a helpful assistant grounded in the knowledge base \"{kb_name}\"."
    )
    lines.append(
        "Prefer the provided SOURCES. If they contain the answer, use them and cite "
        "inline as [S1], [S2] for text and [I1] for images. If the sources only "
        "partially cover the question, give a best-effort answer from what IS there "
        "and note what is uncertain or missing. Only answer \"I don't know\" when "
        "the sources are empty or clearly unrelated to the question."
    )
    if scoped_files:
        files_part = ", ".join(scoped_files)
        lines.append(
            f"Retrieval has been scoped to: {files_part}. Answer only from these files."
        )
    lines.append("")
    # Detect whether this source is a domain store so the LLM knows to
    # interpret records as curated input→output pairs with named metadata.
    has_domain_hits = any(_is_domain_hit(h) for h in text_hits)
    if has_domain_hits:
        lines.append(
            "SOURCES BELOW are curated input\u2192output pairs from a domain "
            "store. Each record carries metadata fields:\n"
            "  - Application — also called \"mnemonic\" or stored as field "
            "\"mne\"; short code identifying the app (e.g. RBNK).\n"
            "  - Technology — the delivery layer; stored as field \"tech\" "
            "(ui / api / mf / db / web / mobile / data / platform).\n"
            "  - Format — flavor or framework of the output; stored as field "
            "\"fmt\" or \"format\".\n"
            "Each record contains BOTH the source artifact and its paired "
            "target, shown beneath the header line. Questions using any of "
            "the field names (\"Application\", \"mnemonic\", \"mne\", \"tech\", "
            "\"fmt\") all refer to these metadata fields visible in the "
            "headers below."
        )
        lines.append("")

    lines.append("SOURCES:")
    if not text_hits and not image_hits:
        lines.append("(no sources retrieved)")
    seen_parents: set = set()
    for i, hit in enumerate(text_hits, start=1):
        if _is_domain_hit(hit):
            lines.append(_format_domain_source(i, hit))
            continue
        meta = hit.get("metadata") or {}
        loc = _location_label(meta)
        loc_part = f" ({loc})" if loc else ""
        content_type = meta.get("content_type") or "text"
        kind_tag = ""
        if content_type == "file_summary":
            kind_tag = " [file summary]"
        elif content_type == "page_summary":
            kind_tag = " [page summary]"
        # Prefer the parent window if we have one we haven't already included
        pid = hit.get("parent_id")
        body = hit.get("document", "")
        if pid and pid not in seen_parents and hit.get("parent_document"):
            body = hit.get("parent_document") or body
            seen_parents.add(pid)
        lines.append(
            f"[S{i}] {meta.get('source_file', 'unknown')}{loc_part}{kind_tag} — "
            f"\"{_snippet(body, n=600)}\""
        )
    for i, hit in enumerate(image_hits, start=1):
        meta = hit.get("metadata") or {}
        lines.append(f"[I{i}] image: {meta.get('source_file', 'unknown')}")
    lines.append("")

    if history:
        lines.append("CONVERSATION SO FAR:")
        for turn in history:
            role = "User" if turn.get("role") == "user" else "Assistant"
            content = (turn.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content}")
        lines.append("")

    lines.append(f"User: {question}")
    lines.append("Assistant:")
    return "\n".join(lines)


def _parse_citations(answer: str,
                     text_hits: List[Dict[str, Any]],
                     image_hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    cites: List[Dict[str, Any]] = []
    for kind, num in _CITE_RE.findall(answer or ""):
        key = f"{kind}{num}"
        if key in seen:
            continue
        seen.add(key)
        idx = int(num) - 1
        pool = text_hits if kind == "S" else image_hits
        if idx < 0 or idx >= len(pool):
            continue
        hit = pool[idx]
        meta = hit.get("metadata") or {}
        cites.append({
            "label": key,
            "kind": "text" if kind == "S" else "image",
            "file": meta.get("source_file"),
            "file_id": meta.get("file_id"),
            "page": meta.get("page"),
            "slide": meta.get("slide"),
        })
    return cites


def _hit_to_reference(hit: Dict[str, Any], label: str, kind: str) -> Dict[str, Any]:
    meta = hit.get("metadata") or {}

    # Domain-store records get a richer label + a snippet that shows both
    # the source and the paired target, so the References panel is
    # actually useful for meta questions about metadata / target artifacts.
    if kind == "text" and _is_domain_hit(hit):
        mne = meta.get("mne") or "—"
        tech = meta.get("tech") or "—"
        fmt = meta.get("fmt") or meta.get("format") or "—"
        domain_name = meta.get("domain") or ""
        source_lbl, target_lbl = _profile_labels(domain_name)
        file_label = f"Application: {mne} · {tech} · {fmt}"
        src = (hit.get("document") or "").strip()
        tgt = (meta.get("completion") or meta.get("comp") or "").strip()
        snippet_parts = []
        if src:
            snippet_parts.append(f"{source_lbl}: {_snippet(src, 140)}")
        if tgt:
            snippet_parts.append(f"{target_lbl}: {_snippet(tgt, 180)}")
        snippet = "  ·  ".join(snippet_parts) if snippet_parts else None
        ref = {
            "label": label,
            "kind": kind,
            "file": file_label,
            "file_id": meta.get("file_id"),
            "page": None,
            "slide": None,
            "similarity": round(float(hit.get("similarity", 0.0)), 4),
            "snippet": snippet,
        }
    else:
        ref = {
            "label": label,
            "kind": kind,
            "file": meta.get("source_file"),
            "file_id": meta.get("file_id"),
            "page": meta.get("page"),
            "slide": meta.get("slide"),
            "similarity": round(float(hit.get("similarity", 0.0)), 4),
            "snippet": _snippet(hit.get("document", ""), 200) if kind == "text" else None,
        }

    if "via" in hit:
        ref["via"] = hit["via"]
    if "rerank_score" in hit:
        ref["rerank_score"] = round(float(hit["rerank_score"]), 3)
    return ref


class KBChatEngine:
    """Multi-turn chat over a single knowledge source — either a user KB
    or a generate-path domain store (via the ``domain:<profile>`` virtual
    id). The source object needs to expose ``.kb`` (dict), ``.kb_id``,
    ``.list_files()``, ``.query_text()``, and ``.query_images()`` — both
    ``KBService`` and ``DomainSource`` satisfy this."""

    def __init__(self, source_id: str) -> None:
        self.source = _build_source(source_id)
        # Backwards-compat alias: existing code reads `self.kb` as the source.
        self.kb = self.source
        self.llm = build_llm()

    def answer(self, history: List[Dict[str, Any]], question: str,
               k: Optional[int] = None,
               source_files: Optional[List[str]] = None) -> Dict[str, Any]:
        t0 = time.perf_counter()
        default_k = int(settings_store.get("retrieval.default_k", 5) or 5)
        if k is None:
            k = retrieval_k_for(question, default_k=default_k, summary_k=max(default_k, 15))
        history_turns = int(settings_store.get("kb.chat.history_turns", 6) or 6)
        recent = (history or [])[-history_turns:]

        # Auto-scope by filename unless the caller has passed an explicit scope.
        kb_files = self.source.list_files()
        effective_scope = source_files
        auto_scoped = False
        if effective_scope is None:
            inferred = resolve_file_scope(question, kb_files)
            if inferred:
                effective_scope = inferred
                auto_scoped = True

        text_hits = self.source.query_text(question, k=k, source_files=effective_scope)
        image_hits = self.source.query_images(question, k=2, source_files=effective_scope)

        prompt = build_prompt(
            kb_name=self.source.kb.get("name", ""),
            history=recent,
            question=question,
            text_hits=text_hits,
            image_hits=image_hits,
            scoped_files=effective_scope,
        )

        try:
            response = self.llm.invoke(prompt)
            answer_text = getattr(response, "content", str(response))
        except Exception as e:
            logger.exception(f"KBChatEngine LLM invocation failed: {e}")
            raise

        citations = _parse_citations(answer_text, text_hits, image_hits)
        references = (
            [_hit_to_reference(h, f"S{i}", "text") for i, h in enumerate(text_hits, start=1)]
            + [_hit_to_reference(h, f"I{i}", "image") for i, h in enumerate(image_hits, start=1)]
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            f"KBChat[{self.source.kb_id}] k={k} text_hits={len(text_hits)} "
            f"image_hits={len(image_hits)} auto_scoped={auto_scoped} "
            f"scope={effective_scope} summary_intent={is_summary_intent(question)} "
            f"latency={latency_ms}ms"
        )
        return {
            "answer": answer_text,
            "citations": citations,
            "references": references,
            "latency_ms": latency_ms,
            "scope": effective_scope,
            "auto_scoped": auto_scoped,
            "summary_intent": is_summary_intent(question),
            "k": k,
        }
