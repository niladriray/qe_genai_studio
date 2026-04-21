"""
Domain profile: Epic → User Story.

Demonstrates the A→B Transformation Engine IP claim: this module is the *only*
new code required to run the RAG pipeline for a second use case. No engine,
UI, retrieval, or storage edits are needed — the engine reads everything
domain-specific from this profile at runtime.

The prompt is structured around widely-adopted agile/SAFe conventions so the
generated artifact is review-ready rather than template-shaped:

  • INVEST  — the six properties every good story must satisfy
                (Independent, Negotiable, Valuable, Estimable, Small, Testable)
  • Connextra narrative — "As a <persona>, I want <capability>, so that <value>"
  • Gherkin acceptance criteria — Given/When/Then, deterministic and testable
  • Non-Functional Requirements — performance, accessibility (WCAG 2.1 AA),
                                  security, observability, compatibility
  • Definition of Done — exit checklist tying functional + non-functional work

Format-enum values map to the three most common delivery styles:
  • "standard"  — Connextra + Gherkin AC + NFR + DoD (full treatment)
  • "gherkin"   — AC-first, light narrative (for mature teams)
  • "plain_text" — prose summary only (for discovery/spike stories)
"""

from domains.profile import DomainProfile
from domains.registry import register


_SYSTEM_ROLE = (
    "You are a senior product manager who decomposes epics into a backlog of "
    "vertically-sliced user stories. Use Connextra narrative and Gherkin AC. "
    "Be concise — no boilerplate, no filler. Write for the target technology "
    "surface only. Never invent data not grounded in the epic."
)

# Common preamble injected into both templates so the LLM knows the expected
# output structure regardless of whether retrieved examples are present.
_TECH_DISCIPLINE = (
    "CRITICAL CONTEXT — TARGET TECHNOLOGY: {tech}. The user story, its "
    "acceptance criteria, and its NFRs MUST describe behaviour on the {tech} "
    "surface (web = browser UX; api = service contracts; mobile = native app; "
    "data = data pipeline / warehouse; platform = infra / shared services). "
    "Do not mix surfaces (e.g. no browser-UX AC when {tech}=api, no HTTP "
    "contract AC when {tech}=web). If retrieved examples appear to be for a "
    "different surface, treat them as style guidance only — do not copy their "
    "scenarios.\n\n"
)

_RUBRIC = (
    _TECH_DISCIPLINE
    + "DECOMPOSE the epic into a backlog of user stories in {format} style. "
    "A single epic MUST yield multiple stories (typically 3-6) — do NOT "
    "collapse the epic into one story. Each story must be a vertical slice "
    "that is independently deliverable. Apply splitting patterns: workflow "
    "steps, business-rule variants, happy vs error paths, CRUD, NFR slice.\n"
    "\n"
    "Structure the response EXACTLY as follows:\n"
    "\n"
    "## Story Map\n"
    "Numbered list: `US-01 — <title>`. MVP-first order.\n"
    "\n"
    "## User Stories\n"
    "\n"
    "### US-NN — <Title>\n"
    "**As a** <persona>, **I want** <capability>, **so that** <value>.\n"
    "\n"
    "**Acceptance Criteria**\n"
    "3-5 Gherkin scenarios (Given/When/Then) — happy path, one edge case, "
    "one error path. Use concrete example values.\n"
    "\n"
    "**NFRs** — only list items genuinely relevant to THIS story (perf "
    "target, security note, a11y requirement). One bullet each, skip if N/A.\n"
    "\n"
    "**Size:** XS / S / M / L\n"
    "\n"
    "Be concise. Do not add INVEST self-checks, traceability tables, or "
    "splitting rationale sections — keep the output tight and actionable."
)

_FEW_SHOT_TEMPLATE = (
    "You are a senior product manager and BA. Use the curated examples as "
    "templates for style, depth, and non-functional coverage.\n\n"
    "{kb_context}"
    "=== Similar Examples ===\n{examples}\n\n"
    "=== New Request ===\n"
    + _RUBRIC
    + "\n\n"
    "Epic:\n{query}\n\n"
    "Metadata:\n- Application (MNE): {mne}\n- Technology: {tech}"
)

_BARE_TEMPLATE = (
    "You are a senior product manager and BA.\n\n"
    "{kb_context}"
    + _RUBRIC
    + "\n\n"
    "Epic:\n{query}\n\n"
    "Metadata:\n- Application (MNE): {mne}\n- Technology: {tech}"
)

EPIC_TO_USER_STORY_PROFILE = DomainProfile(
    name="epic_to_user_story",
    source_label="Epic",
    target_label="User Story",
    source_column="Epic",
    target_column="User Story",
    use_case_type="eus",
    system_role=_SYSTEM_ROLE,
    few_shot_template=_FEW_SHOT_TEMPLATE,
    bare_template=_BARE_TEMPLATE,
    # Reuse the same generic metadata dimensions as test_case so the UI, upload
    # validation, and retrieval ranking work without modification.
    metadata_keys={
        "format": "fmt",
        "mne": "mne",
        "tech": "tech",
        "priority": "priority",
        "completion": "comp",
    },
    format_enum=("standard", "gherkin", "plain_text"),
    technology_enum=("web", "api", "mobile", "data", "platform"),
    example_metadata_fields=("format", "mne", "tech"),
    # A tighter threshold: user-story narratives are semantically fuzzier than
    # test steps, so only very close matches should count as duplicates.
    dedup_similarity_threshold=0.85,
    dedup_match_fields=("tech", "fmt", "mne"),
    # Chain: User Story downloads feed directly into Requirement → Test Case.
    next_profile_name="test_case",
)

register(EPIC_TO_USER_STORY_PROFILE)
