"""
Settings page — runtime-editable app configuration.

Persists to `configs/settings.json` via `configs.settings_store`. LLM
changes hot-reload the cached TestCaseGenerator instances; retrieval
and priority changes take effect on the next call.
"""

import dash
import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, State, callback_context, dcc, html

import domains  # noqa: F401  (triggers profile registration)
from domains.registry import all_profiles
from configs import settings_store


_MASK_PLACEHOLDER = "__UNCHANGED__"


def _mask_key(raw: str) -> str:
    if not raw:
        return ""
    if len(raw) <= 8:
        return "•" * len(raw)
    return f"{'•' * 8}…{raw[-4:]}"


def _field(label, component, help_text=None):
    label_children = [label]
    extras = [component]
    if help_text:
        comp_id = getattr(component, "id", None)
        icon_id = f"{comp_id}-help" if isinstance(comp_id, str) and comp_id \
            else f"help-{id(component)}"
        label_children.extend([
            " ",
            html.Span(
                "\u24d8",  # ⓘ
                id=icon_id,
                className="cfg-help-icon",
                title=help_text,  # native browser tooltip fallback
                **{"aria-label": help_text},
            ),
        ])
        extras.append(
            dbc.Tooltip(help_text, target=icon_id, placement="right",
                        className="cfg-help-tooltip")
        )
    return dbc.Row(
        [
            dbc.Col(html.Label(label_children, style={"fontWeight": 600}), width=3),
            dbc.Col(extras, width=9),
        ],
        className="mb-3",
    )


def _text(id_, value="", placeholder="", disabled=False, type_="text"):
    return dbc.Input(id=id_, type=type_, value=value, placeholder=placeholder, disabled=disabled)


def _switch(id_, value):
    return dbc.Switch(id=id_, value=bool(value), style={"marginTop": "4px"})


def _int_input(id_, value, min_=1, max_=500):
    try:
        val = int(value)
    except (TypeError, ValueError):
        val = 0
    return dbc.Input(id=id_, type="number", min=min_, max=max_, step=1, value=val)


def _float_input(id_, value, min_=0.0, max_=1.0, step=0.01):
    try:
        val = float(value)
    except (TypeError, ValueError):
        val = 0.0
    return dbc.Input(id=id_, type="number", min=min_, max=max_, step=step, value=val)


def _domain_options():
    return [{"label": f"{p.source_label} → {p.target_label} ({p.name})", "value": p.name}
            for p in all_profiles()]


def _build_layout():
    s = settings_store.get_all()
    stored_key = s.get("llm.openai.api_key") or ""
    return dbc.Container(
        [
            html.H3("Settings", className="mt-3"),
            html.P(
                "Runtime-editable application configuration. Persists to "
                "configs/settings.json. LLM changes take effect on the next "
                "generation; retrieval / priority tuning takes effect immediately.",
                className="text-muted",
            ),

            html.Div(id="cfg-status", className="mb-3"),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("LLM — Generation Backend", className="mb-3"),
                        _field(
                            "Backend",
                            dbc.Select(
                                id="cfg-llm-backend",
                                options=[
                                    {"label": "OpenAI", "value": "openai"},
                                    {"label": "Ollama (local)", "value": "ollama"},
                                ],
                                value=s.get("llm.backend", "openai"),
                            ),
                            help_text="Switch between OpenAI cloud and a locally-hosted Ollama model.",
                        ),
                        html.Div(
                            id="cfg-openai-card",
                            children=[
                                _field("OpenAI model", _text("cfg-openai-model", value=s.get("llm.openai.model", "gpt-4")),
                                       help_text="e.g. gpt-4, gpt-4o, gpt-4o-mini."),
                                _field(
                                    "OpenAI API key",
                                    _text("cfg-openai-key",
                                          value=_MASK_PLACEHOLDER if stored_key else "",
                                          placeholder=_mask_key(stored_key) or "paste sk-…",
                                          type_="password"),
                                    help_text=("Stored in configs/settings.json (gitignored). "
                                               "Leave the masked placeholder alone to keep the existing key; paste a new value to rotate."),
                                ),
                            ],
                        ),
                        html.Div(
                            id="cfg-ollama-card",
                            children=[
                                _field("Ollama model", _text("cfg-ollama-model", value=s.get("llm.ollama.model", "llama3")),
                                       help_text="e.g. llama3, qwen2.5:7b-instruct, qwen2.5-coder:7b-instruct."),
                                _field("Ollama base URL", _text("cfg-ollama-url", value=s.get("llm.ollama.base_url", "http://localhost:11434")),
                                       help_text="Where your local Ollama server is listening."),
                                _field("Enable thinking",
                                       dbc.Checkbox(id="cfg-ollama-think", value=bool(s.get("llm.ollama.think", False))),
                                       help_text="When off, Qwen3 skips chain-of-thought (faster, cheaper). Turn on for harder tasks."),
                            ],
                        ),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Retrieval Tuning", className="mb-3"),
                        _field("Default similarity threshold",
                               dbc.Input(id="cfg-ret-threshold", type="number", min=0, max=1, step=0.01,
                                         value=float(s.get("retrieval.default_similarity_threshold", 0.8))),
                               help_text="Global dedup threshold (0–1). Profiles may override."),
                        _field("Default k",
                               dbc.Input(id="cfg-ret-k", type="number", min=1, max=50, step=1,
                                         value=int(s.get("retrieval.default_k", 5))),
                               help_text="How many similar docs to retrieve for the few-shot prompt."),
                        _field("Min context similarity",
                               dbc.Input(id="cfg-ret-mincontext", type="number", min=0, max=1, step=0.01,
                                         value=float(s.get("retrieval.min_context_similarity", 0.25))),
                               help_text="Below this, retrieved examples are dropped and the bare prompt is used."),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Feedback Priorities", className="mb-3"),
                        _field("Default priority",
                               dbc.Input(id="cfg-prio-default", type="number", min=0, max=1, step=0.01,
                                         value=float(s.get("priority.default", 0.5)))),
                        _field("Thumbs-up priority",
                               dbc.Input(id="cfg-prio-up", type="number", min=0, max=1, step=0.01,
                                         value=float(s.get("priority.thumbs_up", 0.8)))),
                        _field("Thumbs-down priority",
                               dbc.Input(id="cfg-prio-down", type="number", min=0, max=1, step=0.01,
                                         value=float(s.get("priority.thumbs_down", 0.3)))),
                        _field("Curated priority",
                               dbc.Input(id="cfg-prio-curated", type="number", min=0, max=1, step=0.01,
                                         value=float(s.get("priority.curated", 0.95))),
                               help_text="Applied to tester-edited records saved back as examples."),
                        _field("Priority weight",
                               dbc.Input(id="cfg-prio-weight", type="number", min=0, max=1, step=0.01,
                                         value=float(s.get("priority.weight", 0.3))),
                               help_text="How much priority biases retrieval ranking vs pure similarity."),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Knowledge Base Chat", className="mb-3"),
                        _field("Chat history turns",
                               _int_input("cfg-kb-history", s.get("kb.chat.history_turns", 6),
                                          min_=0, max_=50),
                               help_text="How many prior user/assistant turns are included in each KB chat prompt."),
                        _field("Expose domain stores in sidebar",
                               _switch("cfg-kb-expose-domains",
                                       s.get("kb.chat.expose_domain_sources", True)),
                               help_text="Show the generate-path domains (Requirements → Test Cases, etc.) as read-only virtual KBs."),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("KB Retrieval Pipeline", className="mb-3"),
                        html.P(
                            "Stage-level toggles for retrieval on user Knowledge Bases. "
                            "Each stage runs independently — disable one to A/B compare.",
                            className="text-muted small mb-3",
                        ),
                        _field("Hybrid BM25 + dense",
                               _switch("cfg-kb-hybrid", s.get("kb.retrieval.hybrid", True)),
                               help_text="Run BM25 and dense search in parallel, fuse with RRF. Off = dense-only."),
                        _field("Dense candidates (top-N)",
                               _int_input("cfg-kb-dense-n", s.get("kb.retrieval.dense_candidates", 20),
                                          min_=1, max_=100)),
                        _field("BM25 candidates (top-N)",
                               _int_input("cfg-kb-bm25-n", s.get("kb.retrieval.bm25_candidates", 20),
                                          min_=1, max_=100)),
                        _field("RRF k",
                               _int_input("cfg-kb-rrf-k", s.get("kb.retrieval.rrf_k", 60),
                                          min_=1, max_=500),
                               help_text="Constant in 1/(k + rank). Larger = flatter decay."),
                        _field("Cross-encoder rerank",
                               _switch("cfg-kb-rerank", s.get("kb.retrieval.rerank", True)),
                               help_text="Rescore (query, doc) pairs jointly. Biggest precision lift."),
                        _field("Rerank pool size",
                               _int_input("cfg-kb-rerank-n", s.get("kb.retrieval.rerank_candidates", 30),
                                          min_=1, max_=200),
                               help_text="Top-N kept after rerank before MMR."),
                        _field("Rerank model",
                               _text("cfg-kb-rerank-model",
                                     value=s.get("kb.retrieval.rerank_model",
                                                 "cross-encoder/ms-marco-MiniLM-L-6-v2")),
                               help_text="HuggingFace cross-encoder id. Change only if you've pulled a different model."),
                        _field("MMR diversification",
                               _switch("cfg-kb-mmr", s.get("kb.retrieval.mmr", True)),
                               help_text="Balance relevance with diversity in the final top-k."),
                        _field("MMR λ",
                               _float_input("cfg-kb-mmr-lambda", s.get("kb.retrieval.mmr_lambda", 0.5)),
                               help_text="1.0 = pure relevance, 0.0 = pure diversity. 0.5 is a sensible default."),
                        _field("Parent-document expansion",
                               _switch("cfg-kb-parent", s.get("kb.retrieval.parent_expand", True)),
                               help_text="Expand each retrieved child chunk to its 1500-char parent window before the LLM sees it."),
                        _field("HyDE query expansion",
                               _switch("cfg-kb-hyde", s.get("kb.retrieval.hyde", False)),
                               help_text=(
                                   "LLM writes a plausible answer; that answer is embedded for the dense leg. "
                                   "BM25 and cross-encoder still see the raw question. "
                                   "Adds ~1–2 s + one LLM call per query. Best on terse / off-corpus queries."
                               )),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Domain-Store Retrieval (Generate Path)", className="mb-3"),
                        html.P(
                            "Same pipeline as KB retrieval, applied to the curated "
                            "source → target pairs under ./data/. Disable here to fall back "
                            "to the legacy dense-only search.",
                            className="text-muted small mb-3",
                        ),
                        _field("Hybrid BM25 + dense",
                               _switch("cfg-dom-hybrid", s.get("domain.retrieval.hybrid", True)),
                               help_text="Off = legacy StoreEmbeddings.is_duplicate dense-only path."),
                        _field("Dense candidates (top-N)",
                               _int_input("cfg-dom-dense-n", s.get("domain.retrieval.dense_candidates", 15),
                                          min_=1, max_=100)),
                        _field("BM25 candidates (top-N)",
                               _int_input("cfg-dom-bm25-n", s.get("domain.retrieval.bm25_candidates", 15),
                                          min_=1, max_=100)),
                        _field("RRF k",
                               _int_input("cfg-dom-rrf-k", s.get("domain.retrieval.rrf_k", 60),
                                          min_=1, max_=500)),
                        _field("Cross-encoder rerank",
                               _switch("cfg-dom-rerank", s.get("domain.retrieval.rerank", True))),
                        _field("Rerank pool size",
                               _int_input("cfg-dom-rerank-n", s.get("domain.retrieval.rerank_candidates", 20),
                                          min_=1, max_=200)),
                        _field("MMR diversification",
                               _switch("cfg-dom-mmr", s.get("domain.retrieval.mmr", False)),
                               help_text="Off by default — A→B pairs are already diverse enough."),
                        _field("MMR λ",
                               _float_input("cfg-dom-mmr-lambda", s.get("domain.retrieval.mmr_lambda", 0.5))),
                        _field("Priority boost weight",
                               _float_input("cfg-dom-priority-weight",
                                            s.get("domain.retrieval.priority_weight", 0.3)),
                               help_text="How much the per-record priority (thumbs-up / curated) blends into the final ranking."),
                        _field("HyDE query expansion",
                               _switch("cfg-dom-hyde", s.get("domain.retrieval.hyde", False)),
                               help_text="Same tradeoff as KB HyDE — adds one LLM call per retrieval."),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("KB-Augmented Generation", className="mb-3"),
                        html.P(
                            "When the user picks one or more KBs on /generatetestcase, "
                            "each row retrieves from those KBs and fuses excerpts into the prompt.",
                            className="text-muted small mb-3",
                        ),
                        _field("Enable KB augmentation",
                               _switch("cfg-gen-kb-enabled", s.get("generate.kb_context.enabled", True)),
                               help_text="Master switch — when off, the Augment-with-KB dropdown has no effect."),
                        _field("k per KB per row",
                               _int_input("cfg-gen-kb-k", s.get("generate.kb_context.k", 3),
                                          min_=1, max_=20)),
                        _field("Auto-scope by mnemonic",
                               _switch("cfg-gen-kb-auto-scope",
                                       s.get("generate.kb_context.auto_scope_mne", True)),
                               help_text="Match the row's mne value against KB filenames; narrow retrieval if a match is found."),
                        _field("HyDE for augmentation queries",
                               _switch("cfg-gen-kb-hyde", s.get("generate.kb_context.hyde", False)),
                               help_text="Separate from KB retrieval HyDE — flip on to use HyDE only during KB-augmented generation."),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("KB Chunking", className="mb-3"),
                        dbc.Alert(
                            [
                                html.Strong("Changes require a re-ingest."),
                                " Existing chunks in your KBs don't resize automatically — click ",
                                html.Strong("Re-ingest"),
                                " on the KB detail pane after saving.",
                            ],
                            color="warning", className="small py-2 mb-3",
                        ),
                        _field("Child chunk size",
                               _int_input("cfg-kb-child-size", s.get("kb.chunk.child_size", 500),
                                          min_=100, max_=5000),
                               help_text="Retrieval chunks. Characters."),
                        _field("Child chunk overlap",
                               _int_input("cfg-kb-child-overlap", s.get("kb.chunk.child_overlap", 50),
                                          min_=0, max_=1000)),
                        _field("Parent window size",
                               _int_input("cfg-kb-parent-size", s.get("kb.chunk.parent_size", 1500),
                                          min_=200, max_=10000),
                               help_text="Larger context window used for LLM prompt when parent expansion is on."),
                        _field("Parent window overlap",
                               _int_input("cfg-kb-parent-overlap", s.get("kb.chunk.parent_overlap", 200),
                                          min_=0, max_=2000)),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("KB Ingest-Time Summarization", className="mb-3"),
                        html.P(
                            [
                                "Produces ", html.Code("page_summary"),
                                " and ", html.Code("file_summary"),
                                " chunks during ingest. Big retrieval lift for summary-intent "
                                "questions, but adds one LLM call per page plus one per file. ",
                                html.Strong("Changes require a re-ingest "),
                                "to apply to existing KBs.",
                            ],
                            className="text-muted small mb-3",
                        ),
                        _field("Summarization master switch",
                               _switch("cfg-kb-sum-enabled", s.get("kb.summarize.enabled", True))),
                        _field("Per-page summaries",
                               _switch("cfg-kb-sum-page", s.get("kb.summarize.per_page", True)),
                               help_text="One LLM call per page; summary indexed as its own chunk."),
                        _field("Per-file executive summary",
                               _switch("cfg-kb-sum-file", s.get("kb.summarize.per_file", True)),
                               help_text="One LLM call per file; dominates summary-intent retrieval."),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Defaults", className="mb-3"),
                        _field("Default domain",
                               dbc.Select(id="cfg-default-domain",
                                          options=_domain_options(),
                                          value=s.get("defaults.domain", "test_case")),
                               help_text="Pre-selected in dropdowns on Generate / Add Context pages."),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Locked — not editable here", className="mb-3 text-muted"),
                        html.P(
                            "These settings are intentionally read-only because changing "
                            "them would invalidate stored KB vectors or break dedup:",
                            className="text-muted small",
                        ),
                        html.Ul(
                            [
                                html.Li("Embeddings model — switching OpenAI ↔ HuggingFace requires rebuilding the entire vector store."),
                                html.Li("Metadata key names (mne / fmt / tech / priority / comp) — changing them orphans existing records."),
                                html.Li("Format / technology enums — edit per-domain on the Manage Domains page."),
                            ],
                            className="small text-muted",
                        ),
                    ]
                ),
                className="mb-3",
            ),

            html.Div(
                [
                    dbc.Button("Save", id="cfg-save-btn", color="primary", className="me-2"),
                    dbc.Button("Reset to defaults", id="cfg-reset-btn", color="danger", outline=True),
                    dcc.ConfirmDialog(
                        id="cfg-reset-confirm",
                        message="Reset all settings to their shipped defaults? This deletes configs/settings.json.",
                    ),
                ],
                className="mb-5",
            ),
        ],
        fluid=True,
        style={"maxWidth": "1000px", "paddingBottom": "60px"},
    )


# Expose `layout` as a module attribute that is rebuilt on every access so
# the form reflects the currently-stored settings (including values just
# saved in a prior request) without restarting the app.
def __getattr__(name):
    if name == "layout":
        return _build_layout()
    raise AttributeError(name)


def register_callbacks(app: Dash):
    @app.callback(
        [Output("cfg-openai-card", "style"),
         Output("cfg-ollama-card", "style")],
        Input("cfg-llm-backend", "value"),
    )
    def toggle_backend_cards(backend):
        hide = {"display": "none"}
        show = {"display": "block"}
        if backend == "ollama":
            return hide, show
        return show, hide

    @app.callback(
        Output("cfg-reset-confirm", "displayed"),
        Input("cfg-reset-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def show_reset_confirm(n):
        return bool(n)

    @app.callback(
        Output("cfg-status", "children", allow_duplicate=True),
        Input("cfg-reset-confirm", "submit_n_clicks"),
        prevent_initial_call=True,
    )
    def reset_settings(_):
        settings_store.reset()
        return dbc.Alert("Settings reset to defaults. Reload the page to see default values.", color="warning")

    @app.callback(
        Output("cfg-status", "children", allow_duplicate=True),
        Input("cfg-save-btn", "n_clicks"),
        [State("cfg-llm-backend", "value"),
         State("cfg-openai-model", "value"),
         State("cfg-openai-key", "value"),
         State("cfg-ollama-model", "value"),
         State("cfg-ollama-url", "value"),
         State("cfg-ollama-think", "value"),
         State("cfg-ret-threshold", "value"),
         State("cfg-ret-k", "value"),
         State("cfg-ret-mincontext", "value"),
         State("cfg-prio-default", "value"),
         State("cfg-prio-up", "value"),
         State("cfg-prio-down", "value"),
         State("cfg-prio-curated", "value"),
         State("cfg-prio-weight", "value"),
         State("cfg-default-domain", "value"),
         # KB chat
         State("cfg-kb-history", "value"),
         State("cfg-kb-expose-domains", "value"),
         # KB retrieval pipeline
         State("cfg-kb-hybrid", "value"),
         State("cfg-kb-dense-n", "value"),
         State("cfg-kb-bm25-n", "value"),
         State("cfg-kb-rrf-k", "value"),
         State("cfg-kb-rerank", "value"),
         State("cfg-kb-rerank-n", "value"),
         State("cfg-kb-rerank-model", "value"),
         State("cfg-kb-mmr", "value"),
         State("cfg-kb-mmr-lambda", "value"),
         State("cfg-kb-parent", "value"),
         State("cfg-kb-hyde", "value"),
         # Domain retrieval pipeline
         State("cfg-dom-hybrid", "value"),
         State("cfg-dom-dense-n", "value"),
         State("cfg-dom-bm25-n", "value"),
         State("cfg-dom-rrf-k", "value"),
         State("cfg-dom-rerank", "value"),
         State("cfg-dom-rerank-n", "value"),
         State("cfg-dom-mmr", "value"),
         State("cfg-dom-mmr-lambda", "value"),
         State("cfg-dom-priority-weight", "value"),
         State("cfg-dom-hyde", "value"),
         # KB-augmented generation
         State("cfg-gen-kb-enabled", "value"),
         State("cfg-gen-kb-k", "value"),
         State("cfg-gen-kb-auto-scope", "value"),
         State("cfg-gen-kb-hyde", "value"),
         # KB chunking
         State("cfg-kb-child-size", "value"),
         State("cfg-kb-child-overlap", "value"),
         State("cfg-kb-parent-size", "value"),
         State("cfg-kb-parent-overlap", "value"),
         # Summarization
         State("cfg-kb-sum-enabled", "value"),
         State("cfg-kb-sum-page", "value"),
         State("cfg-kb-sum-file", "value")],
        prevent_initial_call=True,
    )
    def save_settings(_, backend, openai_model, openai_key, ollama_model, ollama_url, ollama_think,
                      ret_threshold, ret_k, ret_mincontext,
                      prio_default, prio_up, prio_down, prio_curated, prio_weight,
                      default_domain,
                      kb_history, kb_expose_domains,
                      kb_hybrid, kb_dense_n, kb_bm25_n, kb_rrf_k,
                      kb_rerank, kb_rerank_n, kb_rerank_model, kb_mmr, kb_mmr_lambda,
                      kb_parent, kb_hyde,
                      dom_hybrid, dom_dense_n, dom_bm25_n, dom_rrf_k,
                      dom_rerank, dom_rerank_n, dom_mmr, dom_mmr_lambda,
                      dom_priority_weight, dom_hyde,
                      gen_kb_enabled, gen_kb_k, gen_kb_auto_scope, gen_kb_hyde,
                      kb_child_size, kb_child_overlap, kb_parent_size, kb_parent_overlap,
                      kb_sum_enabled, kb_sum_page, kb_sum_file):
        errors = []

        def _num(name, raw, lo, hi):
            try:
                v = float(raw)
            except (TypeError, ValueError):
                errors.append(f"{name} must be a number.")
                return None
            if v < lo or v > hi:
                errors.append(f"{name} must be between {lo} and {hi}.")
            return v

        def _intval(name, raw, lo, hi, fallback):
            try:
                v = int(raw)
            except (TypeError, ValueError):
                errors.append(f"{name} must be an integer.")
                return fallback
            if v < lo or v > hi:
                errors.append(f"{name} must be between {lo} and {hi}.")
            return v

        ret_threshold = _num("Default similarity threshold", ret_threshold, 0, 1)
        ret_mincontext = _num("Min context similarity", ret_mincontext, 0, 1)
        prio_default = _num("Default priority", prio_default, 0, 1)
        prio_up = _num("Thumbs-up priority", prio_up, 0, 1)
        prio_down = _num("Thumbs-down priority", prio_down, 0, 1)
        prio_curated = _num("Curated priority", prio_curated, 0, 1)
        prio_weight = _num("Priority weight", prio_weight, 0, 1)
        ret_k_i = _intval("Default k", ret_k, 1, 50, 5)

        # KB chat
        kb_history_i = _intval("Chat history turns", kb_history, 0, 50, 6)

        # KB retrieval
        kb_dense_n_i = _intval("KB dense candidates", kb_dense_n, 1, 100, 20)
        kb_bm25_n_i = _intval("KB BM25 candidates", kb_bm25_n, 1, 100, 20)
        kb_rrf_k_i = _intval("KB RRF k", kb_rrf_k, 1, 500, 60)
        kb_rerank_n_i = _intval("KB rerank pool size", kb_rerank_n, 1, 200, 30)
        kb_mmr_lambda_f = _num("KB MMR λ", kb_mmr_lambda, 0, 1)

        # Domain retrieval
        dom_dense_n_i = _intval("Domain dense candidates", dom_dense_n, 1, 100, 15)
        dom_bm25_n_i = _intval("Domain BM25 candidates", dom_bm25_n, 1, 100, 15)
        dom_rrf_k_i = _intval("Domain RRF k", dom_rrf_k, 1, 500, 60)
        dom_rerank_n_i = _intval("Domain rerank pool size", dom_rerank_n, 1, 200, 20)
        dom_mmr_lambda_f = _num("Domain MMR λ", dom_mmr_lambda, 0, 1)
        dom_priority_weight_f = _num("Domain priority boost weight", dom_priority_weight, 0, 1)

        # Generate augmentation
        gen_kb_k_i = _intval("KB augmentation k per row", gen_kb_k, 1, 20, 3)

        # Chunking
        kb_child_size_i = _intval("Child chunk size", kb_child_size, 100, 5000, 500)
        kb_child_overlap_i = _intval("Child chunk overlap", kb_child_overlap, 0, 1000, 50)
        kb_parent_size_i = _intval("Parent window size", kb_parent_size, 200, 10000, 1500)
        kb_parent_overlap_i = _intval("Parent window overlap", kb_parent_overlap, 0, 2000, 200)

        if kb_child_overlap_i is not None and kb_child_size_i is not None and kb_child_overlap_i >= kb_child_size_i:
            errors.append("Child overlap must be smaller than child size.")
        if kb_parent_overlap_i is not None and kb_parent_size_i is not None and kb_parent_overlap_i >= kb_parent_size_i:
            errors.append("Parent overlap must be smaller than parent size.")

        if backend == "openai" and not (openai_model or "").strip():
            errors.append("OpenAI model is required when backend=openai.")
        if backend == "ollama":
            if not (ollama_model or "").strip():
                errors.append("Ollama model is required when backend=ollama.")
            if not (ollama_url or "").strip():
                errors.append("Ollama base URL is required when backend=ollama.")

        if not (kb_rerank_model or "").strip():
            errors.append("Rerank model id must not be empty.")

        if errors:
            return dbc.Alert([html.Strong("Cannot save:"),
                              html.Ul([html.Li(e) for e in errors])], color="danger")

        updates = {
            "llm.backend": backend,
            "llm.openai.model": (openai_model or "").strip(),
            "llm.ollama.model": (ollama_model or "").strip(),
            "llm.ollama.base_url": (ollama_url or "").strip(),
            "llm.ollama.think": bool(ollama_think),
            "retrieval.default_similarity_threshold": ret_threshold,
            "retrieval.default_k": ret_k_i,
            "retrieval.min_context_similarity": ret_mincontext,
            "priority.default": prio_default,
            "priority.thumbs_up": prio_up,
            "priority.thumbs_down": prio_down,
            "priority.curated": prio_curated,
            "priority.weight": prio_weight,
            "defaults.domain": default_domain,

            # KB chat
            "kb.chat.history_turns": kb_history_i,
            "kb.chat.expose_domain_sources": bool(kb_expose_domains),

            # KB retrieval pipeline
            "kb.retrieval.hybrid": bool(kb_hybrid),
            "kb.retrieval.dense_candidates": kb_dense_n_i,
            "kb.retrieval.bm25_candidates": kb_bm25_n_i,
            "kb.retrieval.rrf_k": kb_rrf_k_i,
            "kb.retrieval.rerank": bool(kb_rerank),
            "kb.retrieval.rerank_candidates": kb_rerank_n_i,
            "kb.retrieval.rerank_model": (kb_rerank_model or "").strip(),
            "kb.retrieval.mmr": bool(kb_mmr),
            "kb.retrieval.mmr_lambda": kb_mmr_lambda_f,
            "kb.retrieval.parent_expand": bool(kb_parent),
            "kb.retrieval.hyde": bool(kb_hyde),

            # Domain retrieval pipeline
            "domain.retrieval.hybrid": bool(dom_hybrid),
            "domain.retrieval.dense_candidates": dom_dense_n_i,
            "domain.retrieval.bm25_candidates": dom_bm25_n_i,
            "domain.retrieval.rrf_k": dom_rrf_k_i,
            "domain.retrieval.rerank": bool(dom_rerank),
            "domain.retrieval.rerank_candidates": dom_rerank_n_i,
            "domain.retrieval.mmr": bool(dom_mmr),
            "domain.retrieval.mmr_lambda": dom_mmr_lambda_f,
            "domain.retrieval.priority_weight": dom_priority_weight_f,
            "domain.retrieval.hyde": bool(dom_hyde),

            # KB augmentation in generate
            "generate.kb_context.enabled": bool(gen_kb_enabled),
            "generate.kb_context.k": gen_kb_k_i,
            "generate.kb_context.auto_scope_mne": bool(gen_kb_auto_scope),
            "generate.kb_context.hyde": bool(gen_kb_hyde),

            # KB chunking
            "kb.chunk.child_size": kb_child_size_i,
            "kb.chunk.child_overlap": kb_child_overlap_i,
            "kb.chunk.parent_size": kb_parent_size_i,
            "kb.chunk.parent_overlap": kb_parent_overlap_i,

            # Summarization
            "kb.summarize.enabled": bool(kb_sum_enabled),
            "kb.summarize.per_page": bool(kb_sum_page),
            "kb.summarize.per_file": bool(kb_sum_file),
        }

        # Only overwrite the API key if the user actually typed something
        # other than the masked placeholder.
        submitted_key = openai_key or ""
        if submitted_key and submitted_key != _MASK_PLACEHOLDER:
            updates["llm.openai.api_key"] = submitted_key.strip()

        settings_store.save(updates)
        return dbc.Alert(
            [html.Strong("Settings saved."),
             " LLM, retrieval, and KB-augmentation changes take effect on the "
             "next request. Chunking / summarization changes require a re-ingest "
             "to apply to existing KBs."],
            color="success",
        )
