from dash import Dash, dcc, html, Input, Output, State, ctx
import toolbox  # Import the toolbox
from configs import settings_store
from pages import addcontext, generatetestcase, browseprompt, managedomain, config as config_page, metrics, knowledge_base
import dash_bootstrap_components as dbc
import domains  # noqa: F401  (triggers profile registration)
from domains.registry import all_profiles

# Push the stored OpenAI API key into os.environ so LangChain picks it up.
# Shell-exported OPENAI_API_KEY wins; if none, fall back to the value
# managed from the /config page (configs/settings.json).
settings_store.bootstrap_env()

# Initialize Dash
app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1, viewport-fit=cover"},
        {"name": "color-scheme", "content": "light"},
        {"name": "description", "content": "QE GenAI Studio — RAG-powered artifact generation."},
    ],
)
app.title = "QE GenAI Studio"

# Inject lang attribute on <html> for screen-reader language detection.
app.index_string = """<!DOCTYPE html>
<html lang="en">
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        <a href="#main-content" class="skip-link">Skip to main content</a>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""


_HEADER = html.Header(
    [
        html.A(
            html.Span(
                "QE",
                style={
                    "width": "32px",
                    "height": "32px",
                    "borderRadius": "6px",
                    "background": "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
                    "display": "inline-flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "fontSize": "12px",
                    "fontWeight": 800,
                    "color": "#1a1a2e",
                    "letterSpacing": "0.5px",
                },
            ),
            href="/home",
            **{"aria-label": "Go to home page"},
            style={"textDecoration": "none", "marginRight": "16px"},
        ),
        html.H1(
            "QE GenAI Studio",
            style={
                "margin": 0,
                "fontSize": "18px",
                "fontWeight": 600,
                "letterSpacing": "0.3px",
                "color": "#ffffff",
            },
        ),
        html.Span(
            "Quality Engineering · GenAI Proof of Technology",
            style={
                "marginLeft": "auto",
                "fontSize": "13px",
                "color": "rgba(255,255,255,0.92)",
            },
        ),
    ],
    className="app-header",
    role="banner",
)

_MAIN = html.Main(
    [
        dcc.Location(id="url", refresh=False),
        html.Div(id="page-content"),
    ],
    id="main-content",
    className="app-main",
    role="main",
    tabIndex="-1",
)

_FOOTER = html.Footer(
    "QE GenAI Studio  |  RAG-powered artifact generation",
    className="app-footer",
    role="contentinfo",
)

app.layout = html.Div(
    [
        _HEADER,
        html.Div(
            [
                toolbox.get_toolbox(),
                _MAIN,
            ],
            className="app-body",
        ),
        _FOOTER,
    ],
    className="app-shell",
)


# Callback to update content based on URL
@app.callback(
    Output("page-content", "children"),
    [Input("url", "pathname")]
)
def display_page(pathname):
    print(f"Navigated to: {pathname}")  # Debugging
    if pathname == "/addcontext":
        return addcontext.layout
    elif pathname == "/generatetestcase":
        return generatetestcase.layout
    elif pathname == "/browseprompt":
        return browseprompt.layout
    elif pathname == "/managedomain":
        return managedomain.layout
    elif pathname == "/config":
        return config_page.layout
    elif pathname == "/metrics":
        return metrics.layout
    elif pathname == "/knowledge-base":
        return knowledge_base.layout
    else:
        return _build_home_page()


def _build_home_page():
    hero = html.Div(
        [
            html.H1(
                "QE GenAI Studio",
                style={"fontSize": "42px", "fontWeight": 700,
                       "marginBottom": "8px", "color": "#ffffff"},
            ),
            html.P(
                "Generate, retrieve, and chat — all grounded in your team's knowledge.",
                style={"fontSize": "20px", "opacity": "0.9", "marginBottom": "20px"},
            ),
            html.P(
                [
                    "A local-first ", html.Strong("Retrieval-Augmented Generation"),
                    " platform with a unified four-stage pipeline — ",
                    html.Strong("hybrid BM25 + dense, cross-encoder rerank, MMR diversification, "
                                "and parent-document expansion"),
                    " — that powers both artifact generation and Knowledge Base chat. "
                    "Curated examples, application docs, and chat conversations all share "
                    "the same retrieval engine.",
                ],
                style={"fontSize": "15px", "maxWidth": "740px",
                       "margin": "0 auto 28px", "opacity": "0.85", "lineHeight": "1.6"},
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Button(
                            "Generate Now", color="light", size="lg",
                            href="/generatetestcase",
                            style={"fontWeight": 600, "color": "#1a1a2e"},
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button(
                            "Knowledge Base Chat", color="light", size="lg",
                            href="/knowledge-base",
                            style={"fontWeight": 600, "color": "#1a1a2e"},
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button(
                            "Add Context", color="outline-light", size="lg",
                            href="/addcontext",
                        ),
                        width="auto",
                    ),
                ],
                justify="center",
                className="g-2",
            ),
        ],
        style={
            "textAlign": "center",
            "color": "white",
            "background": "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
            "padding": "60px 20px 50px",
            "borderRadius": "12px",
            "marginBottom": "36px",
        },
    )

    _ICON_BLUE = "#2563eb"
    _ICON_RED = "#dc2626"

    _ICON_PATHS = {
        # Feather-style outline paths (24x24 viewBox).
        "zap":     '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
        "book":    ('<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>'
                    '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>'),
        "upload":  ('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
                    '<polyline points="17 8 12 3 7 8"/>'
                    '<line x1="12" y1="3" x2="12" y2="15"/>'),
        "search":  ('<circle cx="11" cy="11" r="8"/>'
                    '<line x1="21" y1="21" x2="16.65" y2="16.65"/>'),
        "layers":  ('<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
                    '<polyline points="2 17 12 22 22 17"/>'
                    '<polyline points="2 12 12 17 22 12"/>'),
        "bars":    ('<line x1="18" y1="20" x2="18" y2="10"/>'
                    '<line x1="12" y1="20" x2="12" y2="4"/>'
                    '<line x1="6" y1="20" x2="6" y2="14"/>'),
    }

    def _svg_icon(name, color):
        body = _ICON_PATHS[name]
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
            f"fill='none' stroke='{color}' stroke-width='2' "
            f"stroke-linecap='round' stroke-linejoin='round'>{body}</svg>"
        )
        from urllib.parse import quote
        data_url = "data:image/svg+xml;utf8," + quote(svg)
        return html.Img(src=data_url, alt="",
                        style={"width": "44px", "height": "44px"})

    def _workflow_card(icon, title, desc, href, badge=None):
        if isinstance(icon, tuple):
            icon_el = _svg_icon(icon[0], icon[1])
        else:
            icon_el = icon
        body_children = [
            html.Div(
                icon_el,
                style={"marginBottom": "12px", "lineHeight": "1"},
            ),
            html.H5(title, style={"fontWeight": 600, "marginBottom": "8px"}),
        ]
        if badge:
            body_children.append(
                dbc.Badge(badge, color="info", className="mb-2",
                          style={"fontSize": "10px", "letterSpacing": "0.4px"})
            )
        body_children.extend([
            html.P(desc, className="text-muted",
                   style={"fontSize": "13px", "lineHeight": "1.5",
                          "minHeight": "62px"}),
            dbc.Button("Open", color="primary", outline=True, size="sm", href=href),
        ])
        return dbc.Col(
            dbc.Card(
                dbc.CardBody(
                    body_children,
                    style={"textAlign": "center", "padding": "24px 16px"},
                ),
                style={"border": "1px solid #e3e6ea", "borderRadius": "10px",
                       "height": "100%"},
                className="shadow-sm",
            ),
            md=4, sm=6, xs=12, className="mb-3",
        )

    workflows = dbc.Row(
        [
            _workflow_card(
                ("zap", _ICON_BLUE), "Generate",
                "Generate test cases, user stories, or automation scripts grounded in your "
                "curated A→B examples — with optional KB augmentation per row.",
                "/generatetestcase", badge="HYBRID + KB AUGMENT",
            ),
            _workflow_card(
                ("book", _ICON_BLUE), "Knowledge Base",
                "Create named KBs from PDF / DOCX / PPTX / MD / images. Chat with them, "
                "or chat with the generate-path domain stores as read-only sources.",
                "/knowledge-base", badge="4-STAGE PIPELINE",
            ),
            _workflow_card(
                ("upload", _ICON_RED), "Add Context",
                "Seed a domain profile with curated source → target examples by uploading "
                "a CSV or XLSX. The shared retrieval engine indexes every record.",
                "/addcontext",
            ),
            _workflow_card(
                ("search", _ICON_BLUE), "Browse Prompts",
                "Explore stored prompts and knowledge-base entries to see what the engine "
                "has learned across all domains.",
                "/browseprompt",
            ),
            _workflow_card(
                ("layers", _ICON_BLUE), "Manage Domains",
                "Add new source → target transformations. Each domain becomes a chat-able "
                "store and a generation target.",
                "/managedomain",
            ),
            _workflow_card(
                ("bars", _ICON_RED), "Metrics",
                "Per-run timing breakdown — retrieval, prompt build, LLM latency, KB-context "
                "augmentation cost.",
                "/metrics",
            ),
        ],
        className="g-3",
    )

    # --- Retrieval pipeline visual ----------------------------------------

    def _stage_card(num, title, desc, accent="#2563eb"):
        return html.Div(
            [
                html.Div(
                    str(num),
                    style={
                        "width": "28px", "height": "28px", "borderRadius": "50%",
                        "background": accent, "color": "white",
                        "display": "flex", "alignItems": "center",
                        "justifyContent": "center",
                        "fontWeight": 700, "fontSize": "12px",
                        "marginRight": "10px", "flexShrink": 0,
                    },
                ),
                html.Div(
                    [
                        html.Div(title, style={"fontWeight": 600, "fontSize": "13px"}),
                        html.Div(desc, className="text-muted",
                                 style={"fontSize": "11px", "lineHeight": "1.4",
                                        "marginTop": "2px"}),
                    ]
                ),
            ],
            style={"display": "flex", "alignItems": "flex-start",
                   "padding": "10px", "background": "#f8fafc",
                   "borderRadius": "8px", "border": "1px solid #e5e7eb",
                   "height": "100%"},
        )

    pipeline_section = dbc.Card(
        dbc.CardBody(
            [
                html.H4(
                    "Unified Retrieval Pipeline",
                    style={"fontWeight": 600, "marginBottom": "8px"},
                ),
                html.P(
                    [
                        "One engine powers every retrieval call — KB chat, KB-augmented "
                        "generation, and chat over domain stores. Each stage is independently "
                        "togglable per pipeline (",
                        html.Code("kb.retrieval.*"), " or ", html.Code("domain.retrieval.*"),
                        ") via the ",
                        html.A("Settings", href="/config"), " page.",
                    ],
                    className="text-muted",
                    style={"fontSize": "13px", "marginBottom": "16px"},
                ),
                dbc.Row(
                    [
                        dbc.Col(_stage_card(
                            0, "HyDE (optional)",
                            "LLM writes a plausible answer; that answer is embedded for the "
                            "dense leg. Best on terse queries. Off by default.",
                            accent="#0e7490",
                        ), md=2, sm=6, xs=12, className="mb-2"),
                        dbc.Col(_stage_card(
                            1, "Hybrid (BM25 + dense)",
                            "BM25 lexical search + MiniLM cosine search, fused with "
                            "Reciprocal Rank Fusion. Catches keywords AND semantics.",
                        ), md=2, sm=6, xs=12, className="mb-2"),
                        dbc.Col(_stage_card(
                            2, "Cross-Encoder Rerank",
                            "ms-marco-MiniLM-L-6-v2 jointly scores (query, doc) pairs. "
                            "Dramatically lifts top-k precision.",
                        ), md=2, sm=6, xs=12, className="mb-2"),
                        dbc.Col(_stage_card(
                            3, "MMR + Priority",
                            "Diversifies the top-k; thumbs-up / curated feedback re-enters "
                            "ranking as a normalized post-rerank boost.",
                        ), md=2, sm=6, xs=12, className="mb-2"),
                        dbc.Col(_stage_card(
                            4, "Parent Expansion (KB)",
                            "Each child chunk expands to its 1500-char parent window before "
                            "the LLM sees it — richer context, dedup'd citations.",
                            accent="#15803d",
                        ), md=2, sm=6, xs=12, className="mb-2"),
                        dbc.Col(_stage_card(
                            5, "Grounded Answer",
                            "LLM generates with inline [S#] / [I#] / [K#] citations. "
                            "Collapsible References panel lists every retrieved source.",
                            accent="#15803d",
                        ), md=2, sm=6, xs=12, className="mb-2"),
                    ],
                    className="g-2",
                ),
            ]
        ),
        style={"borderRadius": "10px", "marginBottom": "24px"},
        className="shadow-sm",
    )

    # --- "What's new" / capability highlights -----------------------------

    def _highlight_card(icon, title, desc):
        return dbc.Col(
            html.Div(
                [
                    html.Div(
                        icon,
                        style={"fontSize": "22px", "marginBottom": "8px"},
                    ),
                    html.Div(title, style={"fontWeight": 600,
                                            "fontSize": "14px",
                                            "marginBottom": "4px"}),
                    html.Div(desc, className="text-muted",
                             style={"fontSize": "12px", "lineHeight": "1.5"}),
                ],
                style={"padding": "14px",
                       "background": "white",
                       "border": "1px solid #e5e7eb",
                       "borderLeft": "3px solid #2563eb",
                       "borderRadius": "8px", "height": "100%"},
            ),
            md=4, sm=6, xs=12, className="mb-3",
        )

    highlights = dbc.Card(
        dbc.CardBody(
            [
                html.H4(
                    "Recently Shipped",
                    style={"fontWeight": 600, "marginBottom": "16px"},
                ),
                dbc.Row(
                    [
                        _highlight_card(
                            "🔀", "Hybrid Search Everywhere",
                            "BM25 + dense with Reciprocal Rank Fusion now powers both "
                            "Knowledge Base chat AND the generate-path domain stores. "
                            "Catches keyword-heavy queries (rare names, IDs, MNE codes) "
                            "that pure cosine misses.",
                        ),
                        _highlight_card(
                            "🎯", "Cross-Encoder Reranker",
                            "ms-marco-MiniLM-L-6-v2 rescores the top 30 candidates "
                            "(query, doc) jointly — significantly better top-5 precision "
                            "than bi-encoder cosine alone.",
                        ),
                        _highlight_card(
                            "📑", "KB-Augmented Generation",
                            "Pick one or more KBs in the Generate page; per-row retrieval "
                            "auto-scopes by mnemonic to inject application architecture / "
                            "wireframe / page-spec excerpts into the prompt.",
                        ),
                        _highlight_card(
                            "💬", "Chat Over Domain Stores",
                            "The KB Chat sidebar now exposes generate-path domain stores "
                            "(Requirements → Test Cases, etc.) as read-only virtual KBs. "
                            "Same retrieval pipeline, scoped by mnemonic.",
                        ),
                        _highlight_card(
                            "🧠", "HyDE Query Expansion",
                            "Optional: LLM writes a hypothetical answer, then embeds that "
                            "for the dense leg. Lifts recall on terse / off-corpus queries. "
                            "BM25 + cross-encoder still see the raw question.",
                        ),
                        _highlight_card(
                            "📚", "Per-Page & Per-File Summaries",
                            "Ingestion produces per-page summaries and a per-file executive "
                            "summary, indexed alongside chunks. The file-summary chunk "
                            "dominates retrieval for summary-style questions.",
                        ),
                    ],
                    className="g-3",
                ),
            ]
        ),
        style={"borderRadius": "10px", "marginBottom": "24px"},
        className="shadow-sm",
    )

    # --- How it works -----------------------------------------------------

    def _step(num, title, desc):
        return dbc.Col(
            [
                html.Div(str(num), style={
                    "width": "36px", "height": "36px", "borderRadius": "50%",
                    "backgroundColor": "#0f3460", "color": "white", "display": "flex",
                    "alignItems": "center", "justifyContent": "center",
                    "fontWeight": 700, "margin": "0 auto 8px",
                }),
                html.H6(title, style={"fontWeight": 600}),
                html.P(desc, className="text-muted small"),
            ],
            md=2, sm=4, xs=6, style={"textAlign": "center"},
        )

    how_it_works = dbc.Card(
        dbc.CardBody(
            [
                html.H4("How It Works", style={"fontWeight": 600, "marginBottom": "20px"}),
                dbc.Row(
                    [
                        _step("1", "Upload",
                              "Curated A→B examples via Add Context, or PDF / DOCX / PPTX / "
                              "images via Knowledge Base."),
                        _step("2", "Index",
                              "MiniLM dense embeddings + BM25 lexical index per store. "
                              "KB ingest also produces parent windows + page / file summaries."),
                        _step("3", "Retrieve",
                              "Hybrid pool (BM25 + dense → RRF) → cross-encoder rerank → "
                              "MMR diversification + priority boost → parent expansion."),
                        _step("4", "Augment",
                              "Generate path can fuse top-k KB excerpts into the prompt, "
                              "auto-scoped by the row's mnemonic."),
                        _step("5", "Generate",
                              "OpenAI or local Ollama produces structured, citation-rich "
                              "output. References panel surfaces every source."),
                        _step("6", "Learn",
                              "Thumbs up / down + curated edits feed a per-record priority "
                              "score that biases future ranking."),
                    ],
                    className="g-3",
                ),
            ]
        ),
        style={"borderRadius": "10px", "marginBottom": "24px"},
        className="shadow-sm",
    )

    domains_section = dbc.Card(
        dbc.CardBody(
            [
                html.H4("Supported Domains", style={"fontWeight": 600, "marginBottom": "8px"}),
                html.P(
                    [
                        "The A-to-B Transformation Engine supports any source-to-target "
                        "workflow. Each registered domain is a generation target on ",
                        html.A("Generate", href="/generatetestcase"),
                        " AND a chat-able read-only source on ",
                        html.A("Knowledge Base", href="/knowledge-base"), ".",
                    ],
                    className="text-muted",
                    style={"fontSize": "13px", "marginBottom": "16px"},
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(f"{p.source_label} \u2192 {p.target_label}",
                                            style={"fontWeight": 600}),
                                    html.Small(f"Formats: {', '.join(p.format_enum)}",
                                               className="text-muted"),
                                ]),
                                style={"borderRadius": "8px",
                                       "border": "1px solid #dee2e6"},
                            ),
                            md=4, sm=6, xs=12, className="mb-2",
                        )
                        for p in all_profiles()
                    ],
                    className="g-2",
                ),
                dbc.Button("Manage Domains", color="secondary", outline=True, size="sm",
                           href="/managedomain", className="mt-2"),
            ]
        ),
        style={"borderRadius": "10px", "marginBottom": "24px"},
        className="shadow-sm",
    )

    roadmap = dbc.Card(
        dbc.CardBody(
            [
                html.H4("Roadmap", style={"fontWeight": 600, "marginBottom": "16px"}),
                dbc.Row(
                    [
                        dbc.Col([
                            html.Div(
                                [
                                    html.Span("Defect Analytics", style={"fontWeight": 600}),
                                    html.Br(),
                                    html.Small("Analyze defects and production incidents to "
                                               "generate actionable insights.",
                                               className="text-muted"),
                                ],
                                style={"padding": "12px",
                                       "borderLeft": "3px solid #0f3460",
                                       "marginBottom": "12px"},
                            ),
                            html.Div(
                                [
                                    html.Span("Agentic Workflows",
                                              style={"fontWeight": 600}),
                                    html.Br(),
                                    html.Small("Autonomous agents that chain generation, "
                                               "validation, and deployment steps.",
                                               className="text-muted"),
                                ],
                                style={"padding": "12px",
                                       "borderLeft": "3px solid #0f3460",
                                       "marginBottom": "12px"},
                            ),
                        ], md=6),
                        dbc.Col([
                            html.Div(
                                [
                                    html.Span("Vision-LLM Image Captioning",
                                              style={"fontWeight": 600}),
                                    html.Br(),
                                    html.Small("Auto-caption uploaded images via a vision "
                                               "model so text queries hit visual content "
                                               "with semantic richness, not just CLIP "
                                               "alignment.",
                                               className="text-muted"),
                                ],
                                style={"padding": "12px",
                                       "borderLeft": "3px solid #0f3460",
                                       "marginBottom": "12px"},
                            ),
                            html.Div(
                                [
                                    html.Span("CI/CD Integration",
                                              style={"fontWeight": 600}),
                                    html.Br(),
                                    html.Small("Generate and validate artifacts as part of "
                                               "your pipeline with a REST API layer.",
                                               className="text-muted"),
                                ],
                                style={"padding": "12px",
                                       "borderLeft": "3px solid #0f3460",
                                       "marginBottom": "12px"},
                            ),
                        ], md=6),
                    ],
                ),
            ]
        ),
        style={"borderRadius": "10px", "marginBottom": "36px"},
        className="shadow-sm",
    )

    return dbc.Container(
        [hero, workflows, pipeline_section, highlights, how_it_works,
         domains_section, roadmap],
        fluid=True,
        style={"maxWidth": "1100px", "margin": "auto", "padding": "20px 20px 60px"},
    )

# Register callbacks for candlestick.py
addcontext.register_callbacks(app)
generatetestcase.register_callbacks(app)
browseprompt.register_callbacks(app)
managedomain.register_callbacks(app)
config_page.register_callbacks(app)
metrics.register_callbacks(app)
knowledge_base.register_callbacks(app)


if __name__ == "__main__":
    app.run_server(debug=True, threaded=True, dev_tools_ui=False)