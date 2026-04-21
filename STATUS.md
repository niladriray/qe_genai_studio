# Implementation Status

_Last updated: 2026-04-15 · Branch: `rel-03122025`_

Maps the tester-facing user stories and IP novelty claims to the code that implements them, after the recent round of fixes (structured status, priority-aware retrieval, few-shot prompting, curated-save, `dcc.Store` session state, upload validation).

## Summary

| Bucket | Stories | IP claims |
|---|---|---|
| ✅ Full | 9 / 10 | 2 / 3 |
| ⚠️ Partial | 1 / 10 | 1 / 3 |
| ❌ Not done | 0 / 10 | 0 / 3 |

## Epic 1 — Building the Test Case Knowledge Base

| # | Story | Status | Evidence |
|---|---|---|---|
| 1.1 | Upload existing test-case pairs | ✅ Full | `pages/addcontext.py` → `parse_uploaded_file` → `validate_columns([Requirement, Test Case, Format])` → `get_generator().add_test_cases(...)` |
| 1.2 | Include format & context metadata | ✅ Full | `utilities/upload_validation.py::validate_enum_values` checks against `Config.META_DATA_TG_FORMAT_TYPE` / `META_DATA_TG_TECHNOLOGY_TYPE`; `normalize_metadata` lowercases `Format`/`tech` so `BDD` vs `bdd` no longer breaks dedup |
| 1.3 | Ingestion status per row | ✅ Full | `TestCaseGenerator.add_test_cases` returns `{status, similarity_score}`; `addcontext.create_cards_from_page_data` renders `Already Exist (SC: 0.95)` badge correctly |

## Epic 2 — Generating New Test Cases

| # | Story | Status | Evidence |
|---|---|---|---|
| 2.1 | Initiate a generation request | ✅ Full | `pages/generatetestcase.py` upload path validates `[Requirement, Format]`; per-session state held in `dcc.Store("gen-data")` / `dcc.Store("gen-page")` |
| 2.2 | Understand the AI's reasoning | ✅ Full | `TestCaseGenerator.generate_test_case` builds explicit few-shot blocks — `Example N (similarity: 0.87, priority: 0.95): Requirement / Test Case` — and `generate_test_case(..., return_with_prompt=True)` surfaces the full prompt to the card (`generatetestcase.py` "Prompt Used" panel) |
| 2.3 | Receive and review generated content | ✅ Full | `create_cards_with_feedback` renders generated TC, metadata, and prompt per card |

## Epic 3 — Curation, Feedback, Continuous Improvement

| # | Story | Status | Evidence |
|---|---|---|---|
| 3.1 | Edit & refine generated cases | ✅ Full | `toggle_edit` reveals textarea + `save-btn` together; `handle_card_actions` on `save-btn` calls `save_curated_test_case` and updates the card |
| 3.2 | Curated cases prioritized in KB | ✅ Full | `TestCaseGenerator.save_curated_test_case` writes with `priority = Config.USE_CASE_TG_CURATED_PRIORITY` (0.95) + `curated=True`; retrieval honors it via `combined_score = similarity + Config.USE_CASE_TG_PRIORITY_WEIGHT · feedback_priority` in `StoreEmbeddings.is_duplicate` |
| 3.3 | Explicit thumbs up/down | ✅ Full | `handle_card_actions` dispatches on `thumbs-up`/`thumbs-down`; writes `USE_CASE_TG_THUMBS_UP_PRIORITY` (0.8) or `THUMBS_DOWN_PRIORITY` (0.3) via `update_test_cases`; priority now affects retrieval ranking (same path as 3.2) |
| 3.4 | Export finalized cases | ⚠️ Partial | `generate_excel_download_link` builds XLSX from `data_list` and the `html.A#download-btn` exposes it after Generate. **Gap:** in-session `Save Curated` re-ingests to the KB but does not write the edited text back into the `data_list` record, so a download taken after editing still contains the pre-edit generation. One-line fix noted in residual gaps. |

## Novel IP Claims

| Claim | Status | Evidence |
|---|---|---|
| Curated Example-Based Prompting | ✅ Full | Prompt template in `test_case_generator.generate_test_case` emits numbered `Example N: Requirement / Test Case` blocks, deduped by `(requirement, completion)` tuple, with similarity + priority annotations per example |
| Feedback-Driven Retrieval Prioritization | ✅ Full | Closed loop: thumbs/curation write `priority` into metadata → `StoreEmbeddings.is_duplicate` reads `feedback_priority` and ranks by `(metadata_match_count, combined_score)`. Verified in unit check: curated doc with `priority=0.95` ranks ahead of identical-similarity neutral doc with `priority=0.5` |
| Integrated A-to-B Transformation Engine | ⚠️ Partial | Wiring (ingest pair → retrieve similar → few-shot → generate → curate → prioritize) is generic, but entity vocabulary is hard-coded: `USE_CASE_TYPE_TG`, prompt text ("test case generator"), metadata keys (`mne`, `tech`, `fmt`), and column names (`Requirement`, `Test Case`) all assume the test-case domain. Making the engine truly reusable would require externalizing the prompt template and entity labels into config |

## Known residual gaps

- **3.4 stale download after edit.** `Save Curated` callback should also update `data_list` for the affected card before the next download is requested (wire through `Output("gen-data", "data")`).
- **Browse Prompts filtering.** `pages/browseprompt.py` now correctly calls `list_all`, but server-side key/value filter is client-only via AgGrid; add filtered query path on the connector if datasets grow.
- **No upload template.** Testers have no sample CSV/XLSX to download; column-name mistakes only surface as `UploadValidationError` after upload.
- **Hardcoded API key (orthogonal).** `app.py:7` still embeds an OpenAI key literal — rotate and move to environment / `.env` before any external sharing of the repo.
- **Single-process state.** The `TestCaseGenerator` singleton in `models/generator_singleton.py` is per-process; horizontal scaling would need a shared cache or a stateless connector.

## How this report was derived

Stories were checked against these files (all read-only):
- `pages/addcontext.py`, `pages/generatetestcase.py`, `pages/browseprompt.py`
- `models/test_case_generator.py`, `models/store_embeddings.py`, `models/generator_singleton.py`
- `connectors/vector_db_connector.py`
- `utilities/upload_validation.py`
- `configs/config.py`

Regenerate this report whenever `models/`, `pages/`, or `configs/config.py` change.
