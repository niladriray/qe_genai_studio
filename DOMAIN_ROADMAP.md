# Domain Roadmap — A→B Use Cases for QE / Testing Teams

_Catalog of candidate `DomainProfile` modules that can plug into the existing engine without code changes. Each row = one new `domains/<name>.py` file._

Ordered roughly by value-to-effort ratio. "Source" is the artifact a user uploads; "Target" is what the LLM generates.

---

## Tier 1 — Highest leverage (ripe for this pipeline)

| # | Domain | Source → Target | Why it's a great fit | KB seed |
|---|--------|-----------------|----------------------|---------|
| 1 | `manual_to_automation` | Manual Test Case → Automation Script (Playwright / Selenium / Cypress / Karate) | Largest time-sink in every QE org. Converts existing manual IP into automation assets. Few-shot RAG excels here — style transfer from curated script examples. | Existing automation suite paired with the manual cases they came from |
| 2 | `story_to_scenarios` | User Story / Requirement → Test Scenario Matrix | Auto-expands one story into happy / edge / negative / security scenarios. Pairs naturally with the current `test_case` profile (output feeds the next pipeline step). | A few high-quality stories with their full scenario breakdown |
| 3 | `openapi_to_api_tests` | OpenAPI Spec Endpoint → API Test Collection (Postman / REST-Assured / Karate) | Spec-to-test is highly structured; easy to validate programmatically. Deterministic output = easy acceptance gates. | Endpoint spec blocks + corresponding Karate/Postman tests |
| 4 | `defect_to_reproducer` | Defect Report / Stack Trace → Reproducer Test Case | Speeds up triage. Curated pairs teach the model your logging conventions and app-specific entry points. | Closed bugs with their final reproducer + fix-validation test |

## Tier 2 — High value, slightly harder

| # | Domain | Source → Target | Notes |
|---|--------|-----------------|-------|
| 5 | `req_to_perf_test` | Requirement → Performance Test Script (JMeter / k6 / Locust / Gatling) | Covers non-functional testing most teams skip. Profile should encode SLO targets (p95, TPS, error budget). |
| 6 | `ui_to_a11y_checklist` | Wireframe / Screen Description → Accessibility Checklist (WCAG 2.1 AA) | Structured, auditable output. Board-pleasing deliverable. Reuses the a11y rubric from `epic_to_user_story`. |
| 7 | `diff_to_regression_tests` | Code Diff / PR Description → Impacted Regression Tests | Risk-based testing. Needs a secondary retrieval over the test inventory keyed on touched modules. |
| 8 | `schema_to_test_data` | Schema / DDL → Synthetic Test Data (with boundary & negative variations) | Foundational — feeds every other domain. Profile encodes PII rules & masking conventions. |

## Tier 3 — Compliance / Governance (banking-relevant)

| # | Domain | Source → Target | Notes |
|---|--------|-----------------|-------|
| 9 | `regulation_to_control_test` | Regulation Clause (SOX / PCI-DSS / OCC / FFIEC / GLBA) → Control Test | Traceability from regulation to evidence. Each generated test carries the regulation anchor as metadata. |
| 10 | `finding_to_remediation_plan` | Audit Finding → Remediation Test Plan | Closes the loop with internal audit. Output is gated by risk rating. |
| 11 | `stride_to_security_test` | Threat Model (STRIDE) Entry → Security Test Case | Shifts security-left systematically. Pairs with OWASP Top 10 reference corpus. |

## Tier 4 — Reporting & Narrative

| # | Domain | Source → Target | Notes |
|---|--------|-----------------|-------|
| 12 | `defects_to_trend_summary` | Defect Cluster → Quality Trend Summary | Turns raw bug data into exec-ready prose. Source is a JSON/CSV blob, not a single row. |
| 13 | `results_to_release_memo` | Test Run Results → Release Readiness Memo | Auto-drafts the go/no-go narrative. Format enum: `exec-brief`, `detailed`, `risk-only`. |

---

## Strategic picks for a QE org starting out

- **#1 (manual→automation)** is the headline use case — it directly converts the organisation's existing KB of hand-written test cases into automation assets. Fastest visible ROI.
- **#2 + #6 together** lets you pitch "every story gets functional + accessibility coverage by default."
- **#9–11** is the pitch for regulated industries (banking, healthcare, insurance): ROI framed as audit cost avoidance rather than tester productivity — usually an easier funding story.
- **#12 + #13** are the executive-facing layer; stand them up last but they're what makes leadership adopt the tool.

## Cross-cutting design notes

- **Metadata dimensions** (`mne`, `tech`, `fmt`, `priority`) generalise cleanly across all of the above. Profile-specific enums just swap values.
- **Dedup threshold** should be tuned per domain:
  - Structured outputs (API tests, SQL, automation scripts): `0.90+` — false duplicates are expensive.
  - Narrative outputs (summaries, plans, stories): `0.80–0.85` — semantic overlap is looser.
- **Format enums** worth considering:
  - Automation: `playwright`, `selenium`, `cypress`, `karate`, `rest_assured`
  - Performance: `jmeter`, `k6`, `locust`, `gatling`
  - Security: `owasp_top10`, `stride`, `nist_800_53`
  - Compliance: `sox`, `pci_dss`, `ffiec`, `occ`, `glba`, `hipaa`
- **Retrieval scoping** (already wired) keeps each domain's KB isolated — a regulation profile won't surface an automation snippet and vice versa.

## Rollout order (suggested)

1. `manual_to_automation` — biggest ROI, existing KB available.
2. `openapi_to_api_tests` — structured and easy to validate; builds confidence in the engine.
3. `defect_to_reproducer` — closes a real pain point; pairs with JIRA/Bugzilla integration.
4. `req_to_perf_test` + `ui_to_a11y_checklist` — proves the non-functional story.
5. Compliance tier (`regulation_to_control_test`, `finding_to_remediation_plan`) — unlocks the regulated-industry pitch.
6. Reporting tier last.

Each new profile is one file in `domains/` + a one-line import in `domains/__init__.py`. No engine, UI, or retrieval edits required — that's the IP claim in action.
