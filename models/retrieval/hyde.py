"""HyDE — Hypothetical Document Embeddings.

Classical recipe (Gao et al., 2022): when a user's query is terse, its
embedding sits awkwardly in vector space compared to the richer embeddings
of target documents. Ask the LLM to write a *plausible* short answer,
embed that, and use the answer's embedding — not the query's — for the
dense retrieval leg. The BM25 leg and the cross-encoder rerank keep seeing
the raw user query, because BM25 depends on literal tokens and the
cross-encoder is trained on (query, doc) pairs.

Intended for summary-style / open-ended questions where bi-encoder recall
is weak. Skip for point-lookup or keyword-heavy queries — BM25 already
handles those.
"""

from __future__ import annotations

from typing import Optional

from utilities.customlogger import logger


_HYDE_PROMPT = (
    "Write a short, plausible answer to the following question as if you "
    "already knew the answer and were drafting the reply. Aim for 3-5 "
    "sentences. Be specific: use concrete nouns, proper names, technical "
    "vocabulary, and section names you would expect to appear in the "
    "actual answer. Do NOT repeat the question, do NOT add meta-commentary "
    "or disclaimers, and do NOT write \"I don't know\" — an imagined "
    "answer is useful even if the facts are guessed.{hint_block}\n\n"
    "QUESTION:\n{question}\n\nANSWER:"
)


def hyde_query(question: str, hint: Optional[str], llm) -> str:
    """Return a hypothetical answer for ``question``, or ``""`` on failure.

    ``hint``: a short sentence of domain context (e.g. "Test case for a
    banking application") added to the prompt; pass None to omit.
    """
    if not question or not question.strip():
        return ""
    hint_block = f"\n\nCONTEXT HINT: {hint.strip()}" if hint and hint.strip() else ""
    prompt = _HYDE_PROMPT.format(question=question.strip(), hint_block=hint_block)
    try:
        response = llm.invoke(prompt)
    except Exception as e:
        logger.warning(f"HyDE LLM invocation failed: {e}")
        return ""
    text = getattr(response, "content", str(response))
    return (text or "").strip()
