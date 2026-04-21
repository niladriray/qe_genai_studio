# QE GenAI Studio

A local-first Dash application for Quality Engineering teams built on a
Retrieval-Augmented Generation (RAG) pipeline. It does three things:

1. **Artifact generation** — ingest curated examples (requirements → test cases,
   epics → user stories, manual steps → automation) and generate new artifacts
   grounded in your team's past work. Retrieval and generation are pluggable
   per *domain profile*. Each generation run can optionally be **augmented with
   one or more user Knowledge Bases**, so application-specific architecture,
   wireframes, and page specs flow into the prompt alongside the few-shot
   examples.
2. **Knowledge Base chat** — create named knowledge bases from your own files
   (PDF, DOCX, PPTX, TXT, MD, images) and chat with them. The KB Chat sidebar
   also exposes the **generate-path domain stores** (Requirements → Test Cases,
   Epic → User Story, Manual → Automation) as read-only "virtual KBs" so you
   can interrogate accumulated curated pairs in plain English.
3. **Unified retrieval pipeline** — both worlds share one engine:
   *(optional HyDE)* → hybrid BM25 + dense with RRF → cross-encoder rerank →
   MMR diversification → priority boost → parent-document expansion (KB only).
   Answers are grounded with inline citations and a collapsible References
   panel.

Everything runs locally. Vector storage is on-disk Chroma, with a BM25 sidecar
per KB **and per domain** for lexical search and a JSON sidecar for
parent-document retrieval. The LLM used for chat, generation, ingest-time
summarization, and HyDE query expansion can be OpenAI (`gpt-4`-class) or a
local Ollama model, toggleable at runtime from the Settings page.

---

## Table of contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Running the app](#running-the-app)
4. [Feature tour](#feature-tour)
5. [Unified retrieval pipeline](#unified-retrieval-pipeline)
6. [Configuration](#configuration)
7. [Architecture](#architecture)
8. [Data & persistence](#data--persistence)
9. [Project structure](#project-structure)
10. [Development notes](#development-notes)
11. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Python 3.11** — the target runtime. The pinned TensorFlow wheel in
  `requirements.txt` is a macOS ARM64 Python 3.11 build, and some transitive
  dependencies are resolved against 3.11. Other Python versions may work for
  parts of the app but are not the supported path.
- **macOS on Apple Silicon** if you intend to use the bundled TensorFlow wheel
  as-is. On other platforms you will need to swap the `tensorflow` line in
  `requirements.txt` for the appropriate distribution (or remove it — nothing
  in the live code path imports TensorFlow directly).
- **Disk space**: ~2.5 GB after first run. Downloads on first use and cached
  under `~/.cache/huggingface/`:
  - `sentence-transformers/all-MiniLM-L6-v2` (~90 MB) — text embeddings
    (used by both KB and domain stores).
  - `cross-encoder/ms-marco-MiniLM-L-6-v2` (~90 MB) — shared retrieval reranker.
  - `sentence-transformers/clip-ViT-B-32` (~600 MB) — image embeddings,
    downloaded only if you upload images to a KB.
- **LLM access** — one of:
  - An OpenAI API key, **or**
  - A local [Ollama](https://ollama.com) server with a chat-capable model
    pulled (`ollama pull llama3`).
  The same LLM is used for chat answers, generation, ingest-time
  summarization, and (optionally) HyDE query expansion. Per-file ingest cost
  on `gpt-4o-mini` is ~$0.01–$0.02 (see
  [Ingestion cost](#ingestion-cost)). HyDE adds one LLM call per retrieval
  when enabled.

---

## Installation

### 1. Clone

```bash
git clone <your-fork-url> PNCGenAI
cd PNCGenAI
```

### 2. Create and activate a virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate            # bash / zsh
#  .venv\Scripts\activate            # Windows PowerShell
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **Heads-up about `requirements.txt`.**
> - The file lists every package **twice** — harmless for `pip` (same pins,
>   second block no-ops).
> - It pins TensorFlow to a **local wheel path on the author's machine**
>   (`file:///Users/niladriray/...`). If you are not the author, edit that line
>   before running `pip install`:
>   ```
>   tensorflow==2.18.0
>   ```
>   (or remove it — nothing in the live code path imports TensorFlow).
> - KB-specific deps (`pypdf`, `docx2txt`, `python-pptx`) and the lexical
>   search dep (`rank-bm25`) are at the tail of the file. If `pip install`
>   fails there, make sure you're on Python 3.11 and re-run.

### 4. Configure an LLM

The app reads LLM settings from `configs/settings.json` (written from the
Settings page at runtime) **or** from the process environment at startup. The
simplest first run:

```bash
export OPENAI_API_KEY="sk-..."
```

You can instead open `/config` in the running app and paste the key there — it
will be persisted to `configs/settings.json`. If you prefer Ollama, point the
app at your local server via the same Settings page (`llm.backend = ollama`,
`llm.ollama.model`, `llm.ollama.base_url`).

> Earlier versions of `app.py` hard-coded an OpenAI API key in source. It has
> been removed. If you pulled a branch that still has it, rotate that key
> immediately — assume it is compromised.

---

## Running the app

### Start the dev server

```bash
source .venv/bin/activate
python app.py
```

This boots Dash's development server at **http://127.0.0.1:8050** with
`debug=True` (hot-reload on source changes).

### Optional: prime / clean the legacy ChromaDB store

```bash
python main.py
```

One-off helper that connects to the legacy on-disk Chroma at `./data/` and
drops the sanity `delme` collection if it exists. Does not touch per-KB
stores under `chromadb/kb/` or per-domain BM25 indexes under `./data/bm25/`.

### Shutting down

Ctrl-C in the terminal. All state persists to disk; next start picks up where
you left off.

---

## Feature tour

The left sidebar exposes every page. Routes are driven by `dcc.Location` in
`app.py`.

| Route                 | Page module                      | Purpose                                                                                                       |
| --------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `/`                   | (home hero in `app.py`)          | Landing page with workflow overview and quick links.                                                          |
| `/addcontext`         | `pages/addcontext.py`            | Seed a domain profile by uploading a CSV/XLSX of curated source → target examples.                            |
| `/generatetestcase`   | `pages/generatetestcase.py`      | Generate artifacts for the selected domain. Hybrid retrieval over the domain store + optional KB augmentation. |
| `/browseprompt`       | `pages/browseprompt.py`          | Browse stored prompts / knowledge-base entries accumulated from the generate path.                            |
| `/managedomain`       | `pages/managedomain.py`          | View / add domain profiles (source → target transformations, allowed formats, metadata enums).                |
| `/knowledge-base`     | `pages/knowledge_base.py`        | Create user KBs from your own files and chat with them, **plus** chat over generate-path domain stores.       |
| `/config`             | `pages/config.py`                | Runtime-editable settings: LLM backend, model, API key, retrieval pipeline knobs.                             |
| `/metrics`            | `pages/metrics.py`               | Performance metrics per generation run — retrieval, prompt build, LLM latency, KB-context cost.               |

### Generate workflow (test cases, user stories, automation)

1. Pick a **domain** on `/addcontext` (e.g. *Requirements → Test Cases*).
2. Upload a CSV/XLSX with the domain's required columns. The uploader
   validates columns and metadata enums before submission.
3. Click **Submit** to embed and store the examples in the shared `./data/`
   ChromaDB collection (each record tagged with its `domain` metadata field).
4. Switch to `/generatetestcase`, select the same domain.
5. **(Optional) Augment with KB** — the dropdown above the upload zone lists
   every user KB. Pick one or more to fuse application-specific architecture
   / wireframe / page-spec excerpts into the prompt for each row. Within each
   selected KB, retrieval is auto-scoped per-row by matching the row's `mne`
   (mnemonic) value against KB filenames.
6. Upload a source CSV, click **Generate**.
7. The engine runs the **same 4-stage retrieval pipeline** that powers KB
   chat, but against the domain store (filtered by `where={"domain": ...}`).
   Top-*k* curated A→B pairs are formatted as few-shot examples; KB excerpts
   land in a separate `## Reference material from external knowledge base`
   block. The LLM produces the new artifact.
8. Thumbs up/down on a generated card updates a `priority` score that biases
   future retrieval (preserved across the Phase 5 refactor — applied as a
   post-rerank boost in the shared retriever).

Domain profiles live in `domains/` — see `test_case.py`,
`epic_to_user_story.py`, `manual_to_automation.py` for the shipped set. Add
new ones via Manage Domains; they're stored as JSON under `domains/custom/`.

### Knowledge Base workflow

The Knowledge Base feature is independent of the generate pipeline. It ships
its own Chroma collections, BM25 sidecar, parents JSON, reranker, and chat
engine.

1. Open `/knowledge-base`. Click **+ New KB** and give it a name and
   description.
2. The KB card appears in the left pane. Click it to open the detail view.
3. **Drop files** into the upload zone. Supported formats:
   - **Text**: PDF (`.pdf`), Word (`.docx`), PowerPoint (`.pptx`), plain text
     (`.txt`), Markdown (`.md`).
   - **Images**: `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`.
4. **Ingestion runs in the background with live progress.** A spinner card
   shows the current stage per file — *Loading*, *Chunking X/Y*, *Summarizing
   page X/Y*, *Building file summary*, *Indexing*. Files list refreshes as
   each file completes.
5. For each text file ingestion produces:
   - **Parent chunks** (default 1500 chars, in a sidecar JSON).
   - **Child chunks** (default 500 chars, in Chroma + BM25, MiniLM-embedded).
   - **Per-page summaries** (one LLM call per page, indexed as their own
     retrievable chunks).
   - **One per-file executive summary** (indexed as a single chunk that
     dominates retrieval for summary-intent questions).
6. Click **Open chat**. Chat header has a **Scope** dropdown: *All files
   (auto-scope)* or pin to a specific file. Ask a question. The engine:
   - Auto-scopes to a file if the question clearly names one.
   - Bumps `k` from 5 to 15 if the question asks for a summary / topics.
   - Runs the unified retrieval pipeline.
   - Builds a grounded prompt (parent windows, not child snippets) and calls
     the LLM.
7. Answers include inline citation chips like `[S1] refund_policy.pdf · p.3`
   and a collapsible **References** panel listing every retrieved chunk with
   its similarity score and snippet.

### KB Chat over domain stores

The KB Chat sidebar has a second section **DOMAIN STORES · read-only** below
your user KBs. Each registered domain profile (Requirements → Test Cases,
Epic → User Story, Manual → Automation, plus any custom domains) shows up as
a card with the total record count.

1. Click a domain card. Skip straight to chat view (no upload / re-ingest /
   delete — domain stores are read-only here; add records via *Add Context*).
2. The **Scope** dropdown lists *mnemonics* (the `mne` metadata values found
   in the store) with per-mnemonic record counts. Pick one to narrow
   retrieval to that application's pairs.
3. Ask a natural-language question. The same 4-stage pipeline runs, scoped
   by `where={"$and": [{"domain": <profile>}, {"mne": <selected>}]}`.
4. Toggle off in `/config` via `kb.chat.expose_domain_sources = false` if
   you want a cleaner sidebar.

### Re-ingest

If you change chunk sizes, toggle summarization on/off, or upgrade through a
release that changes ingest shape, click **Re-ingest** on a KB's detail pane
to rebuild indexes from the persisted uploads without re-uploading. Runs in a
background thread with live progress. Files that predate persistent upload
storage are reported as *needs re-upload*. Domain stores don't need re-ingest
— BM25 auto-bootstraps from Chroma on first query.

### Ingestion cost

Per-page summary ≈ ~500 input + ~100 output tokens; per-file summary ≈
~(pages × 80) input + ~300 output tokens. For a 55-page PDF on `gpt-4o-mini`
this is roughly $0.01–$0.02 and 1.5–2 minutes wall time. Disable per-page
summaries via `kb.summarize.per_page = false` to skip that stage; the file
summary alone still gives a big retrieval lift.

---

## Unified retrieval pipeline

Both `KBService.query_text` (user KBs) and `DomainStoreService.query_similar`
(generate-path A→B pairs) delegate to the same `HybridRetriever` in
`models/retrieval/hybrid_retriever.py`. Each call resolves its knobs via a
prefix (`kb.retrieval.*` for KB, `domain.retrieval.*` for domains) so a
single setting like `kb.retrieval.rerank=False` toggles only KB retrieval
without touching the generate path, and vice versa.

```
question
   │
   ├──▶ [0] HyDE (optional)
   │        • LLM writes a 3-5 sentence plausible answer
   │        • that answer is embedded for the dense leg
   │        • BM25 + cross-encoder still see the raw question
   │        • gated by <prefix>.hyde, default off
   │
   ├──▶ [0.5] Scope resolution               (KB chat & generate aug. only)
   │        • explicit dropdown selection wins
   │        • else auto-match question tokens against filenames / mnemonics
   │        • summary-intent keywords bump k from 5 to 15
   │
   ├──▶ [1] Hybrid retrieval                (BM25 + dense, fused with RRF)
   │        • BM25 top-N over the per-store pickle
   │        • Dense top-N from Chroma (MiniLM, cosine)
   │        • Reciprocal Rank Fusion: score(d) = Σ 1/(60 + rank_i(d))
   │        • BM25-only hits get cosine similarity backfilled from Chroma
   │
   ├──▶ [2] Cross-encoder rerank
   │        • cross-encoder/ms-marco-MiniLM-L-6-v2
   │        • rescores (raw query, doc) pairs jointly
   │        • top-N (default 30) kept for downstream stages
   │
   ├──▶ [2b] Priority-fn boost              (callers may opt in)
   │        • normalized rerank score blended with feedback priority
   │        • for domain stores: weighted by domain.retrieval.priority_weight
   │        • this is where the thumbs-up / curated flag re-enters ranking
   │
   ├──▶ [3] MMR diversification
   │        • relevance = normalized rerank score (cosine fallback)
   │        • diversity = cosine between candidate and already-picked docs
   │        • λ default 0.5; default off for domain stores (A→B already diverse)
   │
   └──▶ [4] Parent-document expansion       (KB only)
            • each child chunk carries parent_id; parents in parents.json
            • prompt uses parent window (~1500 chars) instead of child snippet
            • children sharing a parent are deduped at prompt build
```

**Content types in the index** (KB only):
- `text` — regular child chunks with a `parent_id` to a 1500-char window.
- `page_summary` — 2-3 sentence summary of one page, embedded + indexed.
- `file_summary` — one per file; ~200-word recap that typically dominates
  retrieval for *"what are the key topics in X"* style questions.

Domain-store records are flat — one record per A→B pair, no parents or
summaries.

**Every retrieved hit carries diagnostic fields** that surface in the
References panel data payload: `via` (`dense` / `bm25` / `hybrid`),
`dense_rank`, `bm25_rank`, `rrf_score`, `rerank_score`, `mmr_score`,
`priority_score`, `boosted_score`, `final_rank`, `similarity`, plus
`parent_document` when expansion fired.

**HyDE** (Hypothetical Document Embeddings) — `models/retrieval/hyde.py`. Off
by default. Adds one LLM call (~1-2 s on `gpt-4o-mini`) per query. Best on
terse, off-corpus-vocabulary queries — it expands the dense-leg query target
from a 13-character question into a ~600-character plausible answer, lifting
recall without polluting BM25 or the cross-encoder. Flip on per-pipeline
via `kb.retrieval.hyde`, `domain.retrieval.hyde`, or
`generate.kb_context.hyde`.

### Generate path: KB augmentation

When the user picks one or more KBs in the *Augment with KB* dropdown on
`/generatetestcase`, every row also retrieves from those KBs:

```
generate row
   │
   ├──▶ DomainStoreService.query_similar      → top-3 A→B examples
   │
   └──▶ for each augment_kb_id:
          ├─ resolve_file_scope(query + mne, kb.list_files())
          │     (auto-scopes to KB files matching the row's mnemonic;
          │      falls back to whole-KB retrieval when no filename match)
          ├─ KBService.query_text(query, k=3, source_files=scope, hyde=...)
          │     (4-stage pipeline + parent expansion)
          └─ format excerpts as [K1] <kb> · <file> · (page N)
                                <parent_window 700 chars>

prompt = template.format(
    examples=<curated A→B pairs>,
    kb_context=<## Reference material from external knowledge base block>,
    query=..., format=..., mne=..., tech=...,
)
```

The four shipped templates (`test_case`, `epic_to_user_story`,
`manual_to_automation`, plus any with the `{kb_context}` placeholder) inject
the KB block between the style preamble and the few-shot examples. Custom
profiles whose JSON templates lack the placeholder still work — the kwarg
is silently ignored — they just won't visually use the KB context until you
add `{kb_context}` to their template.

---

## Configuration

All runtime-editable settings live in `configs/settings_store.py`. Defaults
are baked in there; overrides are written to `configs/settings.json` from
the `/config` page.

### LLM & generate-path basics

| Dotted key                               | Default                      | Meaning                                                         |
| ---------------------------------------- | ---------------------------- | --------------------------------------------------------------- |
| `llm.backend`                            | `openai`                     | `openai` or `ollama`.                                           |
| `llm.openai.model`                       | `gpt-4o-mini`                | Any ChatOpenAI-compatible model.                                |
| `llm.openai.api_key`                     | `""` (env wins if set)       | Stored here if not provided as `OPENAI_API_KEY`.                |
| `llm.ollama.model`                       | `llama3`                     | Any chat model pulled via `ollama pull`.                        |
| `llm.ollama.base_url`                    | `http://localhost:11434`     | Ollama HTTP endpoint.                                           |
| `llm.ollama.think`                       | `False`                      | Enable "thinking" for reasoning-style Ollama models.            |
| `retrieval.default_k`                    | `5`                          | Top-*k* retrieval default for both KB chat and domain stores.   |
| `retrieval.default_similarity_threshold` | `0.8`                        | Dedup threshold for `add_test_cases`.                           |
| `retrieval.min_context_similarity`       | `0.25`                       | Skip context injection in the generate path if below this.      |

### KB chat

| Dotted key                       | Default | Meaning                                                                |
| -------------------------------- | ------- | ---------------------------------------------------------------------- |
| `kb.chat.history_turns`          | `6`     | Last N chat turns passed to the LLM as conversation context.           |
| `kb.chat.expose_domain_sources`  | `True`  | Render the *Domain stores* section in the KB Chat sidebar.             |

### KB retrieval pipeline

| Dotted key                          | Default                                       | Meaning                                                                      |
| ----------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------- |
| `kb.retrieval.hybrid`               | `True`                                        | Enable BM25 + dense with RRF fusion. Off → dense-only.                       |
| `kb.retrieval.dense_candidates`     | `20`                                          | Dense top-N feeding into RRF.                                                |
| `kb.retrieval.bm25_candidates`      | `20`                                          | BM25 top-N feeding into RRF.                                                 |
| `kb.retrieval.rrf_k`                | `60`                                          | RRF constant in `1 / (k + rank)`.                                            |
| `kb.retrieval.rerank`               | `True`                                        | Enable cross-encoder reranking.                                              |
| `kb.retrieval.rerank_candidates`    | `30`                                          | Pool size going into rerank; top-k is MMR-selected from this pool.           |
| `kb.retrieval.rerank_model`         | `cross-encoder/ms-marco-MiniLM-L-6-v2`        | Any HF cross-encoder works.                                                  |
| `kb.retrieval.mmr`                  | `True`                                        | Enable MMR diversification.                                                  |
| `kb.retrieval.mmr_lambda`           | `0.5`                                         | MMR tradeoff: 1.0 = pure relevance, 0.0 = pure diversity.                    |
| `kb.retrieval.parent_expand`        | `True`                                        | Expand child-chunk hits to their parent window for the LLM prompt.           |
| `kb.retrieval.hyde`                 | `False`                                       | HyDE query expansion for KB chat. Adds one LLM call per query.               |

### Domain-store retrieval pipeline (generate path)

| Dotted key                              | Default                                       | Meaning                                                                                |
| --------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------------------------- |
| `domain.retrieval.hybrid`               | `True`                                        | Enable hybrid for the generate path. Off → falls back to legacy `is_duplicate`.        |
| `domain.retrieval.dense_candidates`     | `15`                                          | Dense top-N feeding into RRF (smaller pool than KB; A→B records are short).            |
| `domain.retrieval.bm25_candidates`      | `15`                                          | BM25 top-N feeding into RRF.                                                           |
| `domain.retrieval.rrf_k`                | `60`                                          | RRF constant.                                                                          |
| `domain.retrieval.rerank`               | `True`                                        | Enable cross-encoder reranking on the domain side.                                     |
| `domain.retrieval.rerank_candidates`    | `20`                                          | Pool size after rerank.                                                                |
| `domain.retrieval.rerank_model`         | `cross-encoder/ms-marco-MiniLM-L-6-v2`        | Same model singleton as KB; loaded once across both pipelines.                         |
| `domain.retrieval.mmr`                  | `False`                                       | A→B pairs are usually already diverse; default off.                                    |
| `domain.retrieval.mmr_lambda`           | `0.5`                                         | Used only when `mmr=True`.                                                             |
| `domain.retrieval.priority_weight`      | `0.3`                                         | How much the per-record `priority` field (thumbs-up / curated) boosts ranking.         |
| `domain.retrieval.hyde`                 | `False`                                       | HyDE for domain retrieval (chat-over-domain-stores).                                   |

### KB augmentation in generate

| Dotted key                          | Default | Meaning                                                                                  |
| ----------------------------------- | ------- | ---------------------------------------------------------------------------------------- |
| `generate.kb_context.enabled`       | `True`  | Master switch for the *Augment with KB* path; when off, the dropdown is ignored.         |
| `generate.kb_context.k`             | `3`     | KB top-*k* per selected KB per row.                                                      |
| `generate.kb_context.auto_scope_mne`| `True`  | Auto-scope KB retrieval to filenames matching the row's mnemonic.                        |
| `generate.kb_context.hyde`          | `False` | HyDE for KB-augmentation queries during generation.                                      |

### Chunking (changes require a re-ingest)

| Dotted key                  | Default | Meaning                                                                            |
| --------------------------- | ------- | ---------------------------------------------------------------------------------- |
| `kb.chunk.child_size`       | `500`   | Retrieval chunk size in characters.                                                |
| `kb.chunk.child_overlap`    | `50`    | Retrieval chunk overlap.                                                           |
| `kb.chunk.parent_size`      | `1500`  | Parent window size.                                                                |
| `kb.chunk.parent_overlap`   | `200`   | Parent window overlap.                                                             |

### Ingest-time summarization (KB only — LLM cost per file)

| Dotted key                 | Default | Meaning                                                                         |
| -------------------------- | ------- | ------------------------------------------------------------------------------- |
| `kb.summarize.enabled`     | `True`  | Master switch for ingest-time summarization.                                    |
| `kb.summarize.per_page`    | `True`  | One LLM call per page; summary indexed as `page_summary`.                       |
| `kb.summarize.per_file`    | `True`  | One LLM call per file; summary indexed as `file_summary` (dominates summary recall). |

### Priority / feedback

| Dotted key                | Default | Meaning                                                     |
| ------------------------- | ------- | ----------------------------------------------------------- |
| `priority.default`        | `0.5`   | Priority assigned to freshly stored docs in generate path.  |
| `priority.thumbs_up`      | `0.8`   | Priority after a thumbs-up from the generate-path UI.       |
| `priority.thumbs_down`    | `0.3`   | Priority after a thumbs-down.                               |
| `priority.curated`        | `0.95`  | Priority for tester-curated (edited-and-saved) examples.    |
| `priority.weight`         | `0.3`   | Legacy weight in `combined_score = sim + weight*priority`.  |

Environment variables recognized at startup (merged on top of defaults):
`OPENAI_API_KEY`, `OPENAI_MODEL`, `LLM_BACKEND`, `OLLAMA_MODEL`,
`OLLAMA_BASE_URL`.

**Cache invalidation.** Changes to any `llm.*`, `domain.retrieval.*`, or
`generate.kb_context.*` key invalidate the cached `TestCaseGenerator`
singletons so the next request rebuilds with the new settings — no restart
needed.

---

## Architecture

Layered design — each layer depends only on the ones below.

```
┌───────────────────────────────────────────────────────────┐
│  app.py           Dash entry, router, header/footer/shell │
├───────────────────────────────────────────────────────────┤
│  pages/           UI screens: one layout + callbacks each │
│                   ├ addcontext                            │
│                   ├ generatetestcase    (Augment with KB) │
│                   ├ browseprompt                          │
│                   ├ managedomain                          │
│                   ├ knowledge_base   (chat + domain srcs) │
│                   ├ config                                │
│                   └ metrics                               │
├───────────────────────────────────────────────────────────┤
│  models/          Orchestration                           │
│                   ├ llm_factory.py    (OpenAI / Ollama)   │
│                   ├ test_case_generator.py                │
│                   │   └─ _build_kb_context()  (Phase 5B)  │
│                   ├ rag_text.py                           │
│                   ├ store_embeddings.py    (dedup at write)│
│                   ├ feedback_loop.py                      │
│                   ├ generator_singleton.py                │
│                   ├ domain_store.py                       │
│                   │   ├ DomainStoreService                │
│                   │   └ DomainSource     (KB-Chat adapter)│
│                   ├ retrieval/                            │
│                   │   ├ hybrid_retriever.py  (4-stage pipe)│
│                   │   └ hyde.py        (Hypothetical Doc) │
│                   └ kb/               (Knowledge Base)    │
│                     ├ kb_service.py   (ingest + chat KBs) │
│                     ├ chat_engine.py  (prompt + parse +   │
│                     │                  source dispatch)   │
│                     ├ loaders.py      (pdf/docx/pptx/md)  │
│                     ├ bm25_index.py   (per-store BM25)    │
│                     ├ reranker.py     (cross-encoder)     │
│                     ├ parents_store.py (parent-doc JSON)  │
│                     ├ summarizer.py   (page/file summary) │
│                     ├ image_embedder.py (CLIP singleton)  │
│                     └ retrieval_utils.py (intent/scope)   │
├───────────────────────────────────────────────────────────┤
│  connectors/      External-system adapters                │
│                   └ vector_db_connector.py (Chroma)       │
├───────────────────────────────────────────────────────────┤
│  tokenizer/       Chunking                                │
│                   └ text_tokenizer.py                     │
├───────────────────────────────────────────────────────────┤
│  domains/         Domain profiles (test_case,             │
│                   epic_to_user_story, manual_to_automation,│
│                   inventory, custom/*.json)               │
├───────────────────────────────────────────────────────────┤
│  configs/         config.py (constants),                  │
│                   settings_store.py (runtime overlay),    │
│                   kb_registry.py (per-user KB index)      │
├───────────────────────────────────────────────────────────┤
│  utilities/       Shared logger, upload validation,       │
│                   domain hint rendering                   │
└───────────────────────────────────────────────────────────┘
```

### Generate data flow

```
pages/generatetestcase.py
        │
        ├── (optional) "Augment with KB" multi-select
        │
        ▼
TestCaseGenerator.generate_test_case(query, metadata, augment_kbs=[...])
        │
        ├─▶ query_similar()
        │       └─▶ DomainStoreService → HybridRetriever
        │            (BM25 + dense + RRF + rerank + priority boost)
        │            scoped by where={"domain": <profile>}
        │            returns top-k A→B pairs (legacy hit shape preserved)
        │
        ├─▶ build few-shot prompt from top-k retrieved pairs
        │   (skipped if top similarity < retrieval.min_context_similarity)
        │
        ├─▶ _build_kb_context(query, mne, augment_kbs, profile)
        │       └─▶ for each KB: KBService.query_text(...)
        │            (full 4-stage pipeline + parent expansion)
        │            scope auto-resolved from mne against KB filenames
        │            top-3 excerpts formatted as [K1], [K2], [K3]
        │
        ├─▶ prompt = template.format(examples=…, kb_context=…,
        │                            query=…, format=…, mne=…, tech=…)
        │
        ├─▶ llm_factory.build_llm().invoke(prompt)
        │       → ChatOpenAI or ChatOllama per settings
        │
        ├─▶ format post-processing (plain / bdd / custom)
        │
        └─▶ add_test_cases()
            ├─ writes new pair into Chroma (./data/, tagged with domain)
            └─ DomainStoreService.mark_stale() so next query re-bootstraps BM25
```

### KB ingest data flow

```
pages/knowledge_base.py  (drop files → background worker)
        │
        ▼
KBService.ingest_file(path, progress_cb=…)        (chromadb/kb/<id>/uploads/<file_id>.<ext>)
        │
        ├─ loaders.LOADERS[mime](path)  → [(text, {"page":n}), …]
        │
        ├─ parent_tokenizer(1500 / 200).tokenize(page_text)
        │    └── store in parents.json keyed by parent_id
        │
        ├─ child_tokenizer(500 / 50).tokenize(parent_text)
        │    └── each child carries parent_id in metadata
        │        → MiniLM embed → Chroma + BM25
        │
        ├─ summarizer.summarize_page(page_text, llm)
        │    → MiniLM embed → Chroma + BM25  (content_type="page_summary")
        │
        └─ summarizer.summarize_file(per_page_summaries, title, llm)
             → MiniLM embed → Chroma + BM25  (content_type="file_summary")
```

### Chat data flow (KB or domain source)

```
pages/knowledge_base.py  (Send →)
        │
        ▼
KBChatEngine(source_id)
        │   source_id: "<kb_id>"  → KBService          (user KB)
        │              "domain:X" → DomainSource       (generate-path domain)
        │
        ▼
.answer(history, question, source_files=…)
        │
        ├─ retrieval_utils.retrieval_k_for(question)        # 5 | 15 by intent
        ├─ retrieval_utils.resolve_file_scope(question, files)  # auto-scope
        │
        ▼
source.query_text(question, k, source_files)
        │
        └─▶ HybridRetriever.query(question, k, where, hyde)
              ├─ [0] (optional) hyde_query → embed the answer for dense leg
              ├─ [1] hybrid (BM25 top-N + dense top-N → RRF)
              ├─ [2] cross-encoder rerank top-N
              ├─ [2b] priority-fn boost (when supplied)
              └─ [3] MMR diversify to final-k
        │
        ├─ (KB only) parent-document expansion via parents.json
        │
        ▼
chat_engine.build_prompt(...)
        │
        ├─ SOURCES block (parent windows, [S#]/[I#] labels, content_type tags)
        ├─ CONVERSATION block (last N turns)
        │
        ▼
llm_factory.build_llm().invoke(prompt)
        │
        ├─ parse [S#] / [I#] → citation chips
        ├─ build References payload (every retrieved hit)
        └─ return to UI
```

---

## Data & persistence

| Path                                                   | Written by                          | Notes                                                                                                          |
| ------------------------------------------------------ | ----------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `data/chroma.sqlite3` + `data/<uuid>/*.bin`            | Generate path (curated A→B pairs)   | Shared collection across all domains; each record carries a `domain` metadata field. Git-tracked but mutates.  |
| `data/bm25/<profile.name>.pkl`                         | `DomainStoreService` (Phase 5A)     | Per-domain BM25 sidecar. Bootstraps from Chroma on first query; re-bootstraps after `add_test_cases`.          |
| `chromadb/kb/<kb-id>/text/chroma.sqlite3` + HNSW       | KB text ingest                      | One persistent Chroma client per KB, MiniLM embeddings.                                                        |
| `chromadb/kb/<kb-id>/text/bm25.pkl`                    | KB ingest                           | Pickled BM25 corpus + ids + documents + metadatas. Rebuilt on every add/remove.                                |
| `chromadb/kb/<kb-id>/text/parents.json`                | KB ingest                           | Parent-document sidecar keyed by `parent_id`. Lookup-only.                                                     |
| `chromadb/kb/<kb-id>/image/`                           | KB image ingest                     | CLIP 512-d embeddings in its own Chroma client.                                                                |
| `chromadb/kb/<kb-id>/uploads/<file_id>.<ext>`          | KB ingest                           | Persistent copy of every uploaded file. Used by *Re-ingest*.                                                   |
| `configs/settings.json`                                | `/config` page                      | Overrides on top of `settings_store.py` defaults.                                                              |
| `configs/kb_registry.json`                             | `/knowledge-base` page              | Index of all user-created KBs.                                                                                 |
| `data/metrics.json`                                    | Generate path                       | Rolling performance metrics consumed by `/metrics`. Now also tracks `kb_context_sec` and `kb_context.hits`.    |
| `logs/app.log`                                         | `utilities/customlogger.py`         | Shared app log.                                                                                                |

`chromadb/kb/` is created on first KB ingest. Deleting a KB from the UI
removes the registry entry and the on-disk directory tree (Chroma + BM25 +
parents + uploads). Removing a single file from a KB deletes its chunks from
Chroma + BM25, drops its parent entries, and deletes the persisted upload.

`data/bm25/` is created automatically on the first generate-path query that
runs the hybrid pipeline. Safe to delete — it auto-rebuilds from Chroma.

---

## Project structure

```
PNCGenAI/
├── app.py                     Dash entry point, router, header, home hero
├── main.py                    One-off legacy ChromaDB init / cleanup helper
├── toolbox.py                 Left sidebar nav + collapse/highlight callbacks
├── requirements.txt           Python deps (currently duplicated; TF wheel is a
│                              local path — edit before installing)
├── assets/
│   └── styles.css             Global CSS (design tokens, .kb-*, .kb-ref-*,
│                              .kb-ingest-*, .kb-card--domain, etc.)
├── configs/
│   ├── config.py              Static constants
│   ├── settings_store.py      Runtime-editable settings overlay (LLM, KB,
│   │                          domain, generate, summarize)
│   ├── settings.json          Persisted overrides (keep out of git)
│   ├── kb_registry.py         User-KB index API
│   └── kb_registry.json       Persisted KB index
├── connectors/
│   ├── base_connector.py
│   ├── vector_db_connector.py Chroma wrapper with embeddings toggle
│   ├── db_connector.py        Scaffold (SQLAlchemy)
│   ├── spreadsheet_connector.py  Scaffold (pandas)
│   └── gpt_gateway_connector.py  Scaffold (Azure API gateway)
├── domains/
│   ├── registry.py            Profile registration
│   ├── profile.py             Profile dataclass
│   ├── test_case.py           Requirements → Test Cases (with {kb_context})
│   ├── epic_to_user_story.py  Epics → User Stories      (with {kb_context})
│   ├── manual_to_automation.py Manual steps → Automation (with {kb_context})
│   ├── inventory.py           Domain introspection helpers
│   ├── custom_store.py        User-defined profile JSON loader
│   └── custom/                User profile JSON files
├── models/
│   ├── llm_factory.py         build_llm() → ChatOpenAI or ChatOllama
│   ├── test_case_generator.py Generate-path orchestrator + _build_kb_context
│   ├── rag_text.py            Generic RAG helper
│   ├── store_embeddings.py    Add / dedupe (still used at write time)
│   ├── feedback_loop.py       Thumbs up/down priority updates
│   ├── generator_singleton.py Per-domain cached TestCaseGenerator
│   ├── domain_store.py        DomainStoreService + DomainSource (Phase 5A/C)
│   ├── retrieval/             Shared retrieval pipeline (Phase 5)
│   │   ├── __init__.py
│   │   ├── hybrid_retriever.py  4-stage pipeline used by both KB and domains
│   │   └── hyde.py            HyDE query expansion (Phase 5D)
│   └── kb/                    Knowledge Base package
│       ├── kb_service.py      Per-KB ingest + chat retrieval
│       ├── chat_engine.py     Source-polymorphic chat (KB or domain)
│       ├── loaders.py         pdf / docx / pptx / txt / md loaders
│       ├── bm25_index.py      BM25Okapi pickle (per KB and per domain)
│       ├── reranker.py        Cross-encoder singleton
│       ├── parents_store.py   Parent-document sidecar JSON
│       ├── summarizer.py      Page + file summarization prompts
│       ├── image_embedder.py  CLIP ViT-B/32 singleton
│       └── retrieval_utils.py Summary-intent + file-scope resolver
├── pages/                     (see Feature tour table)
├── tokenizer/
│   ├── base_tokenizer.py
│   ├── text_tokenizer.py      RecursiveCharacterTextSplitter (configurable)
│   └── image_tokenizer.py     Scaffold — KB uses models/kb/image_embedder.py
├── utilities/
│   ├── customlogger.py        Shared logger
│   ├── upload_validation.py   CSV/XLSX validation helpers
│   ├── domain_hint.py         Reusable schema-hint card
│   └── ...
├── data/                      Legacy ChromaDB store + per-domain BM25 sidecar
│   └── bm25/<profile.name>.pkl
├── chromadb/kb/<id>/          Per-KB stores
├── logs/                      App logs
├── tests/                     Ad-hoc manual test scripts (not a suite)
└── examples/                  Sample input spreadsheets
```

---

## Development notes

- **No test suite, no lint config.** Verification is by running the app and
  exercising flows manually, plus inline Python smoke tests
  (`python -c "from models...."`).
- **Hot reload.** `python app.py` runs Dash with `debug=True`, so saved
  changes to Python files trigger an auto-reload. Static assets under
  `assets/` are re-served on refresh.
- **Source-polymorphic chat engine.** `KBChatEngine(source_id)` accepts
  either a user KB id (e.g. `"banking-horizon"`) or the prefixed domain id
  `"domain:<profile_name>"`. Internally it dispatches to `KBService` or
  `DomainSource` (in `models/domain_store.py`); both expose the same
  `.kb` / `.kb_id` / `.list_files()` / `.query_text()` / `.query_images()`
  surface.
- **Shared retrieval engine.** `HybridRetriever` in `models/retrieval/`
  parameterises every stage by a settings prefix, so a single class powers
  both KB chat (`kb.retrieval.*`) and domain stores (`domain.retrieval.*`).
  Toggle stages independently per pipeline.
- **Cached singletons.** `models/generator_singleton.py` caches one
  `TestCaseGenerator` per domain. `KBService.text_embedder` is a class-level
  singleton (one MiniLM across all KBs). `models/kb/reranker.py` is a
  module-level singleton (one cross-encoder shared across KB and domain).
  `models/kb/image_embedder.py` is a module-level singleton (one CLIP
  shared across KBs).
- **Lazy downloads.** Cross-encoder and CLIP only download when first
  invoked. HyDE only loads a chat LLM when first triggered.
- **Cosine vs L2.** The legacy `./data/` Chroma collection was created by
  langchain with default L2 distance; the per-KB collections use cosine
  explicitly. `HybridRetriever._shape_hits` recomputes similarity from the
  fetched embeddings (MiniLM normalizes), so it's correct in both spaces.
- **BM25 staleness.** `add_test_cases` writes through langchain (auto-id),
  so we don't know the new ids; instead we call
  `DomainStoreService.mark_stale()` which re-bootstraps BM25 from Chroma on
  the next query. Cheap at domain-store size.
- **Custom profile compatibility.** `str.format` silently ignores unused
  kwargs. Custom profiles whose JSON templates lack `{kb_context}` keep
  working; just won't visually use the KB block until you add the
  placeholder.
- **Page contract.** Every module under `pages/` exports `layout` plus a
  `register_callbacks(app)` function that `app.py` calls once at import.
  Routes are wired in `app.py::display_page`. New pages must add a sidebar
  entry in `toolbox.py`.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'dash'` / `'rank_bm25'`**
Your shell is using the system Python. Activate the venv:
`source .venv/bin/activate`.

**`pip install` fails on the `tensorflow` line.**
Edit `requirements.txt` and replace the `tensorflow @ file:///...whl`
line with a published pin (`tensorflow==2.18.0`) or delete it. Nothing in
the live code path imports TensorFlow.

**Generate path retrieval similarity is 0.0 or negative.**
Should not happen after Phase 5A — `HybridRetriever._shape_hits` recomputes
cosine from embeddings. If you see it, the legacy Chroma collection might be
returning embeddings as `None`; flip `domain.retrieval.hybrid=False` to fall
back to the legacy `is_duplicate` path while you investigate.

**Generate produced no `## Reference material` block despite a KB selected.**
Check the log line `augment_kb: query failed on <id>` — usually means the KB
id is unknown (deleted KB still in dropdown selection) or the KB has zero
records. The dropdown rebuilds from `kb_registry.list_kbs()` on every page
render; refresh the page if a recent KB isn't showing.

**KB augmentation finds nothing for a row.**
The `mne` value didn't match any KB filename, *and* the unscoped fallback
retrieval came up empty. Verify the KB has at least one file ingested and
that retrieval is healthy via the KB Chat page on the same KB.

**KB Chat returns `Error: ... api key ...`**
No OpenAI key available. Either `export OPENAI_API_KEY=...` before starting
the app, paste a key into `/config`, or switch `llm.backend` to `ollama` and
make sure your Ollama daemon is running.

**Upload stuck on *Summarizing page N/M*.**
Expected on the first upload — per-page summaries are one LLM call per page.
For a 55-page PDF on `gpt-4o-mini` expect 1.5–2 minutes. The spinner stays
live; no refresh needed. Disable via `kb.summarize.per_page=false` if not
worth it for your corpus.

**Re-ingest reports *"files need re-upload"*.**
Files were ingested before persistent upload storage existed. Remove each
from the Files list and re-upload from your local disk.

**HyDE adds latency but doesn't help.**
HyDE is most effective on terse / off-corpus-vocabulary queries. On
already-strong queries (high cosine on the raw question), it's neutral to
slightly worse on the dense leg, which the cross-encoder usually normalizes.
Flip the relevant `*.hyde` setting back to `false` for that pipeline if the
~1-2 s/query cost isn't paying off.

**HyDE LLM call fails.**
Logged at warning level (`HyDE LLM invocation failed: …`). Pipeline degrades
to raw query — query still completes. Check your LLM credentials / Ollama
daemon.

**"I don't know" answers despite obviously relevant files.**
Open the References panel under the answer — if it's empty or all hits are
low-similarity, retrieval genuinely didn't find anything. Try:
- Pick the target file/mnemonic explicitly in the Scope dropdown.
- Rephrase the question to include a distinctive token from the filename.
- Enable `kb.summarize.per_file=true` and **Re-ingest** — file-summary
  chunks dominate summary-intent retrieval.
- Try toggling `kb.retrieval.hyde=true` for very terse questions.

**Nothing shows up for scanned PDFs.**
`pypdf` returns empty text for image-based PDFs. OCR is not wired. Either
OCR the PDF externally and upload the text version, or upload pages as
images (CLIP-indexed, but BM25 won't help).

**Port 8050 already in use.**
Another Dash instance is running. `lsof -i :8050` then kill it. For a
permanent port change, edit `app.run_server(debug=True, port=...)` at the
bottom of `app.py`.

**CLIP / cross-encoder / MiniLM download stalls.**
Models pull from Hugging Face on first use. If it fails, check your network,
delete any partial cache under `~/.cache/huggingface/`, and retry. Each
model is downloaded once and cached.

**Domain store sidebar section is empty.**
You haven't added any records via Add Context yet for any domain. Add at
least one row through Add Context first; then the domain card shows up with
a non-zero pair count.

**`git status` shows modifications under `data/` after every run.**
Expected — the legacy ChromaDB files mutate as the generate path uses the
store. Per-KB files under `chromadb/kb/` are not tracked by default — add
that path to `.gitignore` to be explicit. Same for `data/bm25/` if you want
to keep the index out of source control.
