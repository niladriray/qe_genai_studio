from configs.config import Config
from domains.profile import DomainProfile
from domains.registry import register

_TECH_DISCIPLINE = (
    "CRITICAL CONTEXT — TARGET TECHNOLOGY: {tech}. Every generated test case "
    "MUST be written for the {tech} layer and no other. Interpret {tech} as:\n"
    "  • ui          → browser/native UI interactions (clicks, form fields, "
    "                   visible elements, navigation)\n"
    "  • api         → HTTP/service calls (endpoints, methods, request / "
    "                   response bodies, status codes, headers, schema)\n"
    "  • mf          → mainframe green-screen steps (PF keys, screen field "
    "                   reads/writes, session flow)\n"
    "  • db          → database operations (queries, row state, constraints, "
    "                   transactions)\n"
    "  • a11y        → accessibility checks against WCAG 2.1 AA\n"
    "  • performance → load / latency / throughput measurements\n"
    "  • mobile      → mobile app interactions (taps, gestures, platform APIs)\n"
    "Do NOT emit steps belonging to a different layer (e.g. no 'click button' "
    "steps when {tech}=api, no HTTP calls when {tech}=ui). If retrieved "
    "examples below appear to be for a different technology than {tech}, treat "
    "them as STYLE GUIDANCE ONLY — mimic their structure and level of detail, "
    "but do not copy their steps or assertions.\n\n"
)

_COVERAGE_RUBRIC = (
    _TECH_DISCIPLINE
    + "Generate a COMPLETE set of test cases in {format} format that achieves "
    "100% coverage of the requirement — emit as many test cases as needed; do "
    "NOT stop at one. Organise the output under these clearly-labelled sections "
    "and number test cases sequentially (TC-01, TC-02, ...). If a section is "
    "not applicable to this requirement, include the section header with a "
    "one-line justification.\n"
    "  1. Functional — Happy Path: primary success flows.\n"
    "  2. Functional — Alternate & Edge: boundary values, state transitions, "
    "     optional flows, concurrency, idempotency.\n"
    "  3. Functional — Negative: invalid input, error handling, authZ denial, "
    "     expired/locked states, validation failures.\n"
    "  4. Data Combinations — enumerate the input variables, their equivalence "
    "     classes and boundary values, then present a decision table or "
    "     pairwise matrix listing every combination to execute. Mark each row "
    "     with the expected outcome.\n"
    "  5. Non-Functional:\n"
    "       • Performance — quantified targets (p95 latency, throughput, "
    "         payload size, error budget).\n"
    "       • Reliability / Resilience — retry, idempotency, timeout, "
    "         degraded-mode, failover.\n"
    "       • Security — authN/authZ, input validation, injection, PII "
    "         handling, audit logging, OWASP-relevant checks.\n"
    "       • Observability — metrics, structured logs, traces, alert SLOs.\n"
    "       • Compatibility — supported browsers/devices/OS; localisation.\n"
    "  6. Accessibility (WCAG 2.1 AA) — keyboard navigation & focus order, "
    "     screen-reader labels / ARIA roles, colour-contrast >= 4.5:1, error "
    "     announcements, no keyboard traps, resizable text, alt text / captions. "
    "     Include at least one test per applicable WCAG success criterion.\n"
    "  7. Coverage Summary — brief traceability note mapping every acceptance "
    "     criterion / clause in the requirement to the TC-IDs that cover it, "
    "     so a reviewer can confirm nothing is missed.\n"
    "Each test case must include: TC-ID, Title, Preconditions, Test Data (or "
    "reference to the data-combination row), Steps, Expected Result, Priority "
    "(P1–P3), and Coverage tag (functional/edge/negative/perf/sec/a11y/etc.)."
)

_FEW_SHOT_TEMPLATE = (
    "You are a senior QE test designer. Use the curated examples as style "
    "templates for wording and level of detail, but do NOT copy their scope — "
    "the coverage rubric below is authoritative.\n\n"
    "{kb_context}"
    "=== Similar Examples ===\n{examples}\n\n"
    "=== New Request ===\n"
    + _COVERAGE_RUBRIC
    + "\n\n"
    "Requirement:\n{query}\n\n"
    "Metadata:\n- Application (MNE): {mne}\n- Technology: {tech}"
)

_BARE_TEMPLATE = (
    "You are a senior QE test designer.\n\n"
    "{kb_context}"
    + _COVERAGE_RUBRIC
    + "\n\n"
    "Requirement:\n{query}\n\n"
    "Metadata:\n- Application (MNE): {mne}\n- Technology: {tech}"
)

TEST_CASE_PROFILE = DomainProfile(
    name=Config.DEFAULT_DOMAIN,
    source_label="Requirement",
    target_label="Test Case",
    source_column="Requirement",
    target_column="Test Case",
    use_case_type=Config.USE_CASE_TYPE_TG,
    system_role=(
        "You are a test case generator. The user will specify a target "
        "technology (ui, api, mf, db, a11y, performance, mobile). Generate "
        "test cases ONLY for that technology. If retrieved examples appear to "
        "be mislabelled or for a different technology, use them for style "
        "reference only — never copy their steps."
    ),
    few_shot_template=_FEW_SHOT_TEMPLATE,
    bare_template=_BARE_TEMPLATE,
    metadata_keys={
        "format": Config.USE_CASE_TG_METADATA_FMT,       # "fmt"
        "mne": Config.USE_CASE_TG_METADATA_MNE,          # "mne"
        "tech": Config.USE_CASE_TG_METADATA_TECH,        # "tech"
        "priority": Config.USE_CASE_TG_METADATA_PRIORITY,  # "priority"
        "completion": Config.USE_CASE_TG_METADATA_COMPLETION,  # "comp" (legacy) or "completion"
    },
    format_enum=tuple(Config.META_DATA_TG_FORMAT_TYPE),
    technology_enum=tuple(Config.META_DATA_TG_TECHNOLOGY_TYPE),
    example_metadata_fields=("format", "mne", "tech"),
    dedup_similarity_threshold=Config.USE_CASE_TG_SIMILARITY_CHECK[0],
    dedup_match_fields=tuple(Config.USE_CASE_TG_SIMILARITY_CHECK[1:]),
    # Accept the downloaded output of epic_to_user_story as-is.
    source_aliases=("Generated User Story", "User Story"),
    # Chain: Test Case downloads feed directly into Manual → Automation.
    next_profile_name="manual_to_automation",
)

register(TEST_CASE_PROFILE, make_default=True)
