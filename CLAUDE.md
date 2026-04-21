# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

The project is a Dash web app (not a CLI). There is no test suite or lint config.

```bash
pip install -r requirements.txt
python app.py            # Starts the Dash dev server (debug=True), default http://127.0.0.1:8050
python main.py           # One-off helper that initializes/cleans the local ChromaDB at ./data/
```

`requirements.txt` is duplicated (the same packages listed twice) and pins `tensorflow` to a local wheel at `file:///Users/niladriray/tensorflow-2.18.0-cp311-cp311-macosx_12_0_arm64.whl` — install on other machines will fail without editing that line. Python 3.11 is the target (cached `.pyc` files exist for 3.10/3.11/3.13; pin to 3.11 to match the tensorflow wheel).

## Architecture

The app is a Dash UI on top of a RAG pipeline that generates software test cases from requirements, backed by a local ChromaDB vector store.

**Layered structure** (each layer depends only on the layer below it):

1. **`app.py`** — Dash entry point. Defines header/toolbox/footer shell and a `dcc.Location`-driven router that swaps `page-content` between the three pages. Each page module exposes a `layout` and a `register_callbacks(app)` function that `app.py` calls once at import.
2. **`pages/`** — UI screens: `addcontext` (upload/seed test cases), `generatetestcase` (RAG-based generation), `browseprompt` (browse stored prompts). `toolbox.py` at the repo root renders the left nav and owns the highlight callback.
3. **`models/`** — Orchestration layer. `TestCaseGenerator` is the central class: it wires together `VectorDBConnector`, `TextTokenizer`, `StoreEmbeddings`, and `RAG_Text`, runs similarity retrieval, builds the LLM prompt, calls `ChatOpenAI` (gpt-4), formats output (plain/bdd/custom), and stores the generated case back into Chroma. `feedback_loop.py` adjusts stored-document priority based on thumbs-up/down.
4. **`connectors/`** — External-system adapters extending `BaseConnector`. The important one is `VectorDBConnector`, which wraps `langchain_chroma.Chroma` and switches between `OpenAIEmbeddings` and `HuggingFaceEmbeddings` (sentence-transformers/all-MiniLM-L6-v2) via the `use_gpt_embeddings` flag. `db_connector.py` and `spreadsheet_connector.py` are scaffolds for SQLAlchemy / Excel-CSV ingestion. `gpt_gateway_connector.py` exists for routing through an Azure API gateway (config in `configs/gptapigateway.properties`) but the live code path uses LangChain's `ChatOpenAI` directly.
5. **`tokenizer/`** — `TextTokenizer` / `ImageTokenizer` extending `BaseTokenizer`. Used by the models layer to chunk input before embedding.
6. **`configs/config.py`** — Central constants. `Config.USE_CASE_TG_SIMILARITY_CHECK = [0.8, "tech", "fmt", "mne"]` defines the dedup rule used in `TestCaseGenerator.add_test_cases`: a new requirement is treated as a duplicate only when similarity ≥ 0.8 **and** the `tech`, `fmt`, and `mne` metadata fields all match. `META_DATA_TG_FORMAT_TYPE` and `META_DATA_TG_TECHNOLOGY_TYPE` are the allowed metadata enums surfaced in the UI.
7. **`utilities/customlogger.py`** — Shared `logger` imported across the codebase; logs to `logs/app.log`.

**Data flow (generate path):** `pages/generatetestcase.py` → `TestCaseGenerator.generate_test_case(query, metadata)` → `query_similar` (embeds query, calls `StoreEmbeddings.is_duplicate(..., return_similar=True)`) → builds `context` from retrieved docs (skipped when top similarity < 0.25) → `ChatOpenAI(model="gpt-4")` → format-specific post-processing (`_format_bdd` / `_format_custom`) → `add_test_cases` re-embeds and persists the new case so future generations can retrieve it.

**Persistence:** ChromaDB is local on disk under `./data/` (`chroma.sqlite3` plus per-collection HNSW segments). These files are checked in and mutate during normal use — `git status` will show them as modified after running the app. `main.py` deletes the `delme` collection on startup as a sanity helper.

## Things to know before editing

- **Hardcoded OpenAI API key in `app.py:7`** — `os.environ["OPENAI_API_KEY"] = "sk-proj-…"` is committed to the repo. Treat this key as compromised; do not echo it back in commits or PRs and prefer reading it from the environment / `.env` (python-dotenv is already a dependency).
- The `pipelines/` directory exists but is empty — the README mentions `RAGPipeline` but the actual RAG logic lives in `models/rag_text.py` and `models/test_case_generator.py`.
- `__pycache__/` directories and `.DS_Store` files are committed throughout the tree; avoid adding more and don't get distracted by their churn in `git status`.
- `app.py` uses Dash's `app.run_server(debug=True)` (deprecated in Dash 3 in favor of `app.run`) — fine on the pinned `dash==2.18.2`.
