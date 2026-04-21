"""Ingest-time summarization for Knowledge Base documents.

Two levels:
* Per-page summary — 2-3 sentences of the page. Indexed as its own chunk
  with ``content_type="page_summary"``, so vector + BM25 retrieval can hit
  it directly when the user asks about that page.
* Per-file executive summary — ~200-word structured recap of the whole
  document, built from the per-page summaries. Indexed as
  ``content_type="file_summary"`` and dominates retrieval for summary-intent
  questions like "what are the key topics in <file>".

Both use the same LLM backend as chat (via ``llm_factory.build_llm``).
Failures are logged and swallowed so a flaky LLM never blocks ingestion.
"""

from __future__ import annotations

from typing import List

from utilities.customlogger import logger


_PAGE_PROMPT = (
    "Summarize the following page in 2-3 concise sentences. Focus on the "
    "concrete facts, names, numbers, entities, and topics that appear in the "
    "page. Do not add introductions, apologies, or meta-commentary. If the "
    "page is mostly a header, table of contents, or boilerplate, say so "
    "briefly and list the topics it references.\n\n"
    "PAGE TEXT:\n{text}\n\nSUMMARY:"
)


_FILE_PROMPT = (
    "You are given a sequence of per-page summaries from a document titled "
    "\"{title}\". Produce a single executive summary of the entire document "
    "in 180-250 words. Structure:\n"
    "1. One opening sentence stating what the document is about.\n"
    "2. 4-7 bullet points, each a short phrase + one sentence, listing the "
    "key topics, stories, or themes covered. Include concrete names and "
    "numbers when present. Do not invent anything that is not in the "
    "summaries.\n\n"
    "PER-PAGE SUMMARIES:\n{per_page}\n\nEXECUTIVE SUMMARY:"
)


_MAX_PAGE_CHARS = 8000          # truncate very long pages before summarizing
_MAX_PER_PAGE_BUNDLE = 120       # cap per-page summaries sent to file-summarizer


def _invoke(llm, prompt: str) -> str:
    response = llm.invoke(prompt)
    text = getattr(response, "content", str(response))
    return (text or "").strip()


def summarize_page(text: str, llm) -> str:
    """Return a 2-3 sentence summary of ``text``, or empty string on failure."""
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) > _MAX_PAGE_CHARS:
        text = text[:_MAX_PAGE_CHARS]
    try:
        return _invoke(llm, _PAGE_PROMPT.format(text=text))
    except Exception as e:
        logger.warning(f"Page summary failed: {e}")
        return ""


def summarize_file(per_page: List[dict], title: str, llm) -> str:
    """Compose an executive summary from per-page summaries.

    ``per_page`` items: ``{"page": int|None, "summary": str}``.
    """
    lines = []
    for entry in per_page[:_MAX_PER_PAGE_BUNDLE]:
        summary = (entry.get("summary") or "").strip()
        if not summary:
            continue
        page = entry.get("page")
        if page is not None:
            lines.append(f"p.{page}: {summary}")
        else:
            lines.append(summary)
    if not lines:
        return ""
    body = "\n".join(lines)
    try:
        return _invoke(llm, _FILE_PROMPT.format(title=title, per_page=body))
    except Exception as e:
        logger.warning(f"File summary failed: {e}")
        return ""
