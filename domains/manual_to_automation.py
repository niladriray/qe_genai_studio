"""
Domain profile: Manual Test Case → Automation Script.

One profile spans every technology layer (UI, API, mainframe, DB, a11y,
performance, mobile). The engine's existing (metadata_match_count,
combined_score) ranking in StoreEmbeddings.is_duplicate already delivers
per-(layer, framework) relevance for free — a UI/Playwright request will
surface UI/Playwright pairs above UI/Selenium above any cross-layer pair.
Splitting into six sub-profiles would only fragment the KB for no retrieval
benefit.

Axes carried on existing metadata dimensions:
  • tech — technology layer (ui, api, mf, db, a11y, performance, mobile)
  • fmt  — target automation framework (playwright, karate, k6, axe_core, ...)
  • mne  — application code (free-form, unchanged)
"""

from domains.profile import DomainProfile
from domains.registry import register


_SYSTEM_ROLE = (
    "You are a senior SDET. Convert manual test cases into production-ready "
    "automation scripts in the requested framework and for the requested "
    "technology layer. Output ONLY executable code (plus a minimal file "
    "header comment), no explanatory prose. The target technology is "
    "authoritative: never emit code for a different layer even if the "
    "retrieved examples do. Use selectors/locators/endpoints exactly as they "
    "appear in the manual steps; where they are missing, leave a "
    "clearly-marked TODO rather than inventing values."
)

_TECH_DISCIPLINE = (
    "CRITICAL CONTEXT — TARGET TECHNOLOGY: {tech}, TARGET FRAMEWORK: {format}. "
    "The automation MUST drive the {tech} layer and compile/run in {format}. "
    "Do NOT produce code for a different layer (e.g. no Playwright UI calls "
    "when {tech}=api, no HTTP client when {tech}=ui, no screen-scraper when "
    "{tech}=db). If retrieved examples appear to be for a different layer or "
    "framework, use them for style reference only — do not copy their imports, "
    "selectors, or assertions.\n\n"
)

_RUBRIC = (
    _TECH_DISCIPLINE
    + "Write the automation in {format} targeting the {tech} layer. Structure:\n"
    "  1. File header comment — one line describing the scenario + MNE\n"
    "  2. Imports / framework boilerplate appropriate to {format}\n"
    "  3. Setup / teardown if idiomatic for the framework\n"
    "  4. One top-level test function or scenario mirroring the manual steps\n"
    "  5. Explicit assertions for every verification step in the manual case\n"
    "  6. TODO comments wherever the manual case leaves data or selectors "
    "     unspecified (never fabricate)\n"
    "Layer-specific guardrails:\n"
    "  • ui — prefer role/label selectors; avoid brittle XPath; wait on state, not time\n"
    "  • api — validate status, headers, schema; parameterise base URL via env\n"
    "  • mf — model as green-screen field reads/writes; include JCL/session prologue\n"
    "  • db — wrap in a transaction; assert row counts, values, and constraints\n"
    "  • a11y — emit axe/pa11y run + WCAG-rule assertions; never soft-fail\n"
    "  • performance — set SLO thresholds (p95 latency, error rate) inline"
)

_FEW_SHOT_TEMPLATE = (
    "You are a senior SDET. Use the curated examples as style templates.\n\n"
    "{kb_context}"
    "=== Similar Examples ===\n{examples}\n\n"
    "=== New Request ===\n"
    + _RUBRIC
    + "\n\n"
    "Manual Test Case:\n{query}\n\n"
    "Metadata:\n- Application (MNE): {mne}\n- Technology: {tech}"
)

_BARE_TEMPLATE = (
    "You are a senior SDET.\n\n"
    "{kb_context}"
    + _RUBRIC
    + "\n\n"
    "Manual Test Case:\n{query}\n\n"
    "Metadata:\n- Application (MNE): {mne}\n- Technology: {tech}"
)

MANUAL_TO_AUTOMATION_PROFILE = DomainProfile(
    name="manual_to_automation",
    source_label="Manual Test Case",
    target_label="Automation Script",
    source_column="Test Case",
    target_column="Automation Script",
    use_case_type="m2a",
    system_role=_SYSTEM_ROLE,
    few_shot_template=_FEW_SHOT_TEMPLATE,
    bare_template=_BARE_TEMPLATE,
    metadata_keys={
        "format": "fmt",
        "mne": "mne",
        "tech": "tech",
        "priority": "priority",
        "completion": "comp",
    },
    format_enum=(
        "playwright", "selenium", "cypress",
        "karate", "rest_assured", "postman_newman",
        "axe_core", "pa11y", "lighthouse",
        "k6", "jmeter", "locust", "gatling",
        "dbunit", "pytest_sqlalchemy", "great_expectations",
        "tosca_scan", "hostondemand_screen",
        "appium",
    ),
    technology_enum=("ui", "api", "mf", "db", "a11y", "performance", "mobile"),
    example_metadata_fields=("format", "mne", "tech"),
    # Tighter than narrative domains. Two manual cases can share similar NL
    # but map to different automation artifacts; we must not suppress a new
    # script just because the description reads familiar.
    dedup_similarity_threshold=0.90,
    dedup_match_fields=("tech", "fmt", "mne"),
    # Accept the downloaded output of test_case as-is.
    source_aliases=("Generated Test Case",),
)

register(MANUAL_TO_AUTOMATION_PROFILE)
