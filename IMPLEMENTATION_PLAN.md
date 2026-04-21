# Implementation Plan — Remaining Partials

_Companion to `STATUS.md`. Covers the two items still marked Partial: user story **3.4 Export** and IP claim **A-to-B Transformation Engine**._

Two independent workstreams. Story 3.4 is a ~1-hour change; the IP claim is a ~1-day refactor best done in three phases.

---

## Part 1 — Story 3.4: Export must reflect curated edits

### Problem recap

`handle_card_actions` in `pages/generatetestcase.py` handles `save-btn` by calling `save_curated_test_case(...)` — which writes to Chroma — but it only returns `feedback-message` and `generated-test-case` for that one card. The `gen-data` Store and `download-btn.href` remain unchanged, so the next XLSX download carries the pre-edit text.

### Approach

Split the save branch into its own callback that also writes `gen-data` and refreshes `download-btn.href`, using Dash's `allow_duplicate=True` so it can co-output targets already owned by `handle_main`.

### Files to modify

- `pages/generatetestcase.py` — only file touched.

### Code changes

**1. Add a dedicated save callback** (new, alongside `handle_card_actions`):

```python
@app.callback(
    [
        Output({"type": "feedback-message", "index": MATCH}, "children", allow_duplicate=True),
        Output({"type": "generated-test-case", "index": MATCH}, "children", allow_duplicate=True),
        Output("gen-data", "data", allow_duplicate=True),
        Output("download-btn", "href", allow_duplicate=True),
        Output("download-btn", "style", allow_duplicate=True),
    ],
    Input({"type": "save-btn", "index": MATCH}, "n_clicks"),
    [
        State({"type": "save-btn", "index": MATCH}, "id"),
        State({"type": "edit-textarea", "index": MATCH}, "value"),
        State({"type": "requirement", "index": MATCH}, "children"),
        State({"type": "mne", "index": MATCH}, "children"),
        State({"type": "tech", "index": MATCH}, "children"),
        State({"type": "format", "index": MATCH}, "children"),
        State("gen-data", "data"),
    ],
    prevent_initial_call=True,
)
def handle_save(n_clicks, btn_id, edited_text, requirement, mne, tech, fmt, data_list):
    if not n_clicks:
        raise PreventUpdate
    idx = btn_id["index"]
    new_text = (edited_text or "").strip()
    if not new_text:
        return "⚠️ Empty edit ignored.", dash.no_update, dash.no_update, dash.no_update, dash.no_update

    metadata = {
        Config.USE_CASE_TG_METADATA_MNE: mne,
        Config.USE_CASE_TG_METADATA_TECH: tech,
        Config.USE_CASE_TG_METADATA_FMT: fmt,
    }
    generator = get_generator()
    result = generator.save_curated_test_case(requirement, new_text, metadata)

    data_list = data_list or []
    if 0 <= idx < len(data_list):
        data_list[idx]["Generated Test Case"] = new_text
        data_list[idx]["Curated"] = True
        data_list[idx]["Status"] = "Curated"

    href = generate_excel_download_link(data_list)
    visible = {"margin-top": "10px", "display": "inline-block"}
    msg = f"✅ Curated and saved to KB ({result.get('status', 'ok')}). Download refreshed."
    return msg, new_text, data_list, href, visible
```

**2. Remove the `save-btn` branch from `handle_card_actions`** (thumbs stay there; save is now its own handler). This also keeps the thumbs callback focused on feedback-message only.

**3. Import `PreventUpdate`**: `from dash.exceptions import PreventUpdate`.

**4. On the main `handle_main` generate branch**, add `allow_duplicate=True` on `gen-data` and `download-btn.*` outputs so both callbacks coexist.

### Verification

1. Boot app, generate 2 test cases, click **Download** → note file A.
2. Click **Edit** on card #1, change text, click **Save Curated**.
3. Confirm card shows edited text + "Curated" status + refreshed message.
4. Click **Download** again → file B should contain the edited text in row 1 while row 2 is unchanged.
5. Browse Prompts page: filter on `curated=True` — the new record appears with `priority=0.95`.
6. Regenerate on the same requirement — confirm the curated version shows up as `Example 1 (similarity: ~1.00, priority: 0.95)` in the prompt.

---

## Part 2 — IP Claim 3: A-to-B Transformation Engine

### Problem recap

The pipeline is structurally generic but lexically specific: class/method names, prompt strings, column names, and metadata keys (`mne`/`tech`/`fmt`) all hard-code the requirement→test-case domain. To substantiate the IP claim, a second domain needs to be pluggable without forking the code.

### Approach — Domain Profile pattern

Introduce a `DomainProfile` object that owns everything domain-specific: entity labels, prompt template, column names, metadata schema, default format/tech enums, and a profile key that gets stamped into every stored record. The engine reads *only* from the profile; `Config.USE_CASE_TG_*` becomes the default profile's values.

Phased to keep each step shippable.

### Phase A — Extract the profile (no behavior change)

**New files**

- `domains/__init__.py`
- `domains/profile.py` — `DomainProfile` dataclass
- `domains/registry.py` — `register(profile)`, `get(name)`, `default_profile()`
- `domains/test_case.py` — the current test-case profile; re-exports current constants

**Modified files**

- `models/test_case_generator.py` — accept `profile: DomainProfile` arg (default = registry default); replace hardcoded prompt template and metadata keys with `profile.prompt_template.format(...)` and `profile.metadata_keys["format"]` etc.
- `models/store_embeddings.py::is_duplicate` — replace `Config.USE_CASE_TG_METADATA_FMT/MNE/TECH/PRIORITY` lookups with `profile.metadata_keys[...]`. Add `profile` arg with fallback to default.
- `configs/config.py` — keep existing constants; add `DEFAULT_DOMAIN = "test_case"`.

**`DomainProfile` sketch** (`domains/profile.py`):

```python
from dataclasses import dataclass, field
from typing import Sequence

@dataclass(frozen=True)
class DomainProfile:
    name: str                       # e.g. "test_case"
    source_label: str               # e.g. "Requirement"
    target_label: str               # e.g. "Test Case"
    source_column: str              # upload column name (source)
    target_column: str              # upload column name (target)
    use_case_type: str              # e.g. Config.USE_CASE_TYPE_TG
    system_role: str                # "You are a test case generator."
    few_shot_template: str          # placeholders: {examples},{query},{format},{mne},{tech},{source_label},{target_label},{system}
    bare_template: str              # no-context variant
    metadata_keys: dict             # {"format":"fmt","mne":"mne","tech":"tech","priority":"priority","completion":"completion"}
    format_enum: Sequence[str]
    technology_enum: Sequence[str]
    example_metadata_fields: Sequence[str] = field(default_factory=lambda: ("format", "mne", "tech"))
```

**`domains/test_case.py`**:

```python
from configs.config import Config
from domains.profile import DomainProfile
from domains.registry import register

TEST_CASE_PROFILE = DomainProfile(
    name="test_case",
    source_label="Requirement",
    target_label="Test Case",
    source_column="Requirement",
    target_column="Test Case",
    use_case_type=Config.USE_CASE_TYPE_TG,
    system_role="You are a test case generator.",
    few_shot_template=(
        "{system}\n\nUse the curated examples as templates for style and detail.\n\n"
        "=== Similar Examples ===\n{examples}\n\n"
        "=== New Request ===\nGenerate ONE {target_label} in {format} format.\n"
        "{source_label}:\n{query}\n\nMetadata:\n- MNE: {mne}\n- Tech: {tech}"
    ),
    bare_template=(
        "{system}\n\nGenerate ONE {target_label} in {format} format.\n"
        "{source_label}:\n{query}\n\nMetadata:\n- MNE: {mne}\n- Tech: {tech}"
    ),
    metadata_keys={
        "format": Config.USE_CASE_TG_METADATA_FMT,
        "mne": Config.USE_CASE_TG_METADATA_MNE,
        "tech": Config.USE_CASE_TG_METADATA_TECH,
        "priority": Config.USE_CASE_TG_METADATA_PRIORITY,
        "completion": "completion",
    },
    format_enum=Config.META_DATA_TG_FORMAT_TYPE,
    technology_enum=Config.META_DATA_TG_TECHNOLOGY_TYPE,
)

register(TEST_CASE_PROFILE, make_default=True)
```

**Registry** (`domains/registry.py`):

```python
_profiles: dict[str, "DomainProfile"] = {}
_default: str | None = None

def register(profile, make_default=False):
    _profiles[profile.name] = profile
    global _default
    if make_default or _default is None:
        _default = profile.name

def get(name):
    return _profiles[name]

def default_profile():
    return _profiles[_default]

def all_profiles():
    return list(_profiles.values())
```

Import the profile module from `app.py` (or a `domains/__init__.py` auto-loader) so registration happens at boot.

**Engine refactor** — `TestCaseGenerator.__init__` accepts `profile=None` → falls back to `default_profile()`. `generate_test_case` builds the prompt from `profile.few_shot_template` / `profile.bare_template`. `add_test_cases` stamps `domain=profile.name` into every metadata dict.

**Retrieval scoping** — in `is_duplicate`, pass `profile` through and filter candidates by `doc_metadata.get("domain", Config.DEFAULT_DOMAIN) == profile.name`. Records without `domain` field are treated as test_case for backwards compat.

At end of Phase A: zero behavioral change, all tests still pass, prompt output is identical.

### Phase B — UI exposure + data scoping

**Modified files**

- `pages/addcontext.py` — add `dbc.Select(id="domain-picker", options=[...from registry])` above the upload widget; store in `dcc.Store("addcontext-domain", data="test_case")`; pass selected profile into `add_test_cases` via `get_generator(profile_name=...)`.
- `pages/generatetestcase.py` — same dropdown + same plumbing; prompt pane now shows `{source_label} → {target_label}`.
- `utilities/upload_validation.py::validate_columns` — take the profile and validate `[profile.source_column, profile.target_column, "Format"]` (format stays because it's a universal formatting dim).
- `models/generator_singleton.py` — switch from a single instance to a per-profile dict: `_generators: dict[str, TestCaseGenerator]`; `get_generator(profile_name="test_case")` returns the one for that profile. Still lazy, still reuses HF embeddings.

**Browse Prompts** — add domain filter chip so testers can view per-domain KB.

### Phase C — Prove generality with a second profile

**New file** `domains/user_story.py` — profile for **User Story → Acceptance Criteria**:

```python
from domains.profile import DomainProfile
from domains.registry import register

USER_STORY_PROFILE = DomainProfile(
    name="user_story",
    source_label="User Story",
    target_label="Acceptance Criteria",
    source_column="User Story",
    target_column="Acceptance Criteria",
    use_case_type="us",
    system_role="You are an acceptance-criteria generator. Output Gherkin Given/When/Then.",
    few_shot_template=(...),   # analogous structure
    bare_template=(...),
    metadata_keys={
        "format": "fmt", "mne": "mne", "tech": "tech",
        "priority": "priority", "completion": "completion",
    },
    format_enum=("gherkin", "bullet"),
    technology_enum=("web", "api", "mobile"),
)

register(USER_STORY_PROFILE)
```

No engine code changes — if everything works end-to-end with just a new profile file, the IP claim is substantiated.

### Migration / backwards compat

- Existing Chroma records lack a `domain` field → treat as `test_case` in `is_duplicate` filter.
- One-time migration step in `main.py`: iterate `list_all`, stamp `domain=test_case` on any record missing it, re-write. Ship as an optional admin utility.
- `Config.USE_CASE_TG_*` constants retained — they're the values the default profile points at, so nothing external breaks.

### Files to read before starting

- `models/test_case_generator.py` — lines 44 (`ChatOpenAI` init), 72-150 (prompt build), 176-270 (`add_test_cases`)
- `models/store_embeddings.py::is_duplicate` — the key lookups that become profile-driven
- `configs/config.py` — confirm all `USE_CASE_TG_METADATA_*` references
- `pages/addcontext.py`, `pages/generatetestcase.py` — where the dropdown slots in, where columns are read

### Verification

**Phase A** (no-op refactor):

1. Boot app, upload the same CSV as before, confirm status badges identical to pre-refactor.
2. Generate on a known requirement, diff the prompt text vs. pre-refactor — must be byte-identical.
3. Browse Prompts shows `domain=test_case` on newly-added records.

**Phase B** (UI):

1. Domain dropdown is populated from the registry (just "test_case" for now, later "user_story" too).
2. Switching dropdown on upload rejects files whose column names don't match the profile's `source_column` / `target_column` with a clear validation error.
3. Generating with domain=test_case retrieves only test_case records (verify via log `metadata_match_count`).

**Phase C** (second domain):

1. Add a `user_story` profile. No edits to engine code.
2. Upload a 3-row sheet of user stories → acceptance criteria under the new domain; confirm ingestion.
3. Upload a new user story, Generate, confirm retrieval returns only `user_story`-domain examples and prompt uses the Gherkin-flavored template.
4. Cross-check: a generate request under domain=test_case does **not** surface the user_story records, proving domain isolation works.

### Rollout order

1. **Part 1** (story 3.4) — small, ship first.
2. **Part 2 Phase A** — invisible refactor; one PR, easy review.
3. **Part 2 Phase B** — adds UI surface; test carefully.
4. **Part 2 Phase C** — new profile module + docs update to substantiate the IP claim.
