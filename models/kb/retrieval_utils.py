"""Small helpers that influence retrieval without changing the vector store.

* `is_summary_intent` — does the question smell like a summary / overview ask?
* `retrieval_k_for` — bump k for summary-ish questions, keep it tight otherwise.
* `resolve_file_scope` — best-effort map from question tokens to KB filenames,
  so "key topics in March edition" auto-scopes to the March file even when
  the user hasn't picked anything in the file-filter dropdown.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


SUMMARY_KEYWORDS = {
    "topic", "topics", "summary", "summarise", "summarize", "summarised", "summarized",
    "summaries", "overview", "theme", "themes", "highlights", "outline", "gist",
    "takeaway", "takeaways", "tldr", "recap",
}

# Words we strip from a question before treating the remainder as filename
# candidates. Mix of English stopwords + generic document words that never
# uniquely identify a file. Also rolls in the summary-intent vocabulary so a
# question like "summarize the Feb 2026 issue" doesn't try to match
# "summarize" against filenames.
_SCOPE_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "for", "to", "and", "or", "vs",
    "with", "from", "about", "into", "over", "under", "per", "via",
    "what", "whats", "whos", "whose", "which", "who", "why", "when", "where",
    "how", "tell", "show", "give", "list", "explain", "describe", "compare",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "can", "could", "should", "would", "will", "shall", "may", "might", "must",
    "me", "my", "our", "their", "your", "his", "her", "this", "that", "these",
    "those", "there", "here", "it", "its", "say", "said",
    # generic document words
    "edition", "editions", "version", "file", "files", "document", "documents",
    "paper", "papers", "article", "articles", "issue", "issues",
    "pdf", "docx", "pptx", "txt", "md",
    "topic", "topics", "summary", "overview", "key", "main", "points",
} | SUMMARY_KEYWORDS


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9]+", text or "")]


def is_summary_intent(question: str) -> bool:
    """Rough heuristic — did the user ask for a summary / overview / topics?"""
    toks = set(_tokens(question))
    if SUMMARY_KEYWORDS & toks:
        return True
    # "main points", "key themes", "what's in", "what is it about" are catchable by token set too
    joined = " ".join(_tokens(question))
    for phrase in ("main point", "key point", "what is it about", "whats it about"):
        if phrase in joined:
            return True
    return False


def retrieval_k_for(question: str, default_k: int = 5, summary_k: int = 15) -> int:
    """Return the retrieval k to use for this question."""
    return summary_k if is_summary_intent(question) else default_k


def resolve_file_scope(question: str, files: List[Dict[str, Any]]) -> Optional[List[str]]:
    """Best-effort filename inference.

    Returns a list of `source_file` values if the question clearly references
    a subset of files, else None (meaning "all files").
    """
    if not files:
        return None

    q_tokens = set(_tokens(question))
    q_tokens -= _SCOPE_STOPWORDS
    # Short / numeric-only tokens are too ambiguous on their own.
    q_tokens = {t for t in q_tokens if len(t) >= 3}
    if not q_tokens:
        return None

    # Tokens shared by *every* file's name are useless for scoping ("banking"
    # in "Banking Horizon - March 2026.pdf", etc.). Drop them.
    per_file_tokens: List[set] = []
    for f in files:
        src = f.get("source_file") or ""
        per_file_tokens.append(set(_tokens(Path(src).stem)))
    if per_file_tokens:
        common = set.intersection(*per_file_tokens) if len(per_file_tokens) > 1 else set()
    else:
        common = set()

    scored: List[tuple[int, str]] = []
    for f, toks in zip(files, per_file_tokens):
        distinctive = toks - common
        overlap = q_tokens & distinctive
        if overlap:
            src = f.get("source_file")
            if src:
                scored.append((len(overlap), src))

    if not scored:
        return None
    # Keep only the strongest match(es). Ties go through together — the user
    # probably mentioned a token (like a shared year) that applies to more
    # than one file.
    best = max(s for s, _ in scored)
    matches = [name for score, name in scored if score == best]
    # Matching everything == no scope; preserve user intent rather than
    # pretending we narrowed anything.
    if len(matches) >= len(files):
        return None
    return matches
