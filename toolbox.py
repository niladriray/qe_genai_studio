from dash import html, dcc, Input, Output, State, callback, clientside_callback, ClientsideFunction
import dash_bootstrap_components as dbc


SIDEBAR_WIDTH = "130px"
SIDEBAR_COLLAPSED_WIDTH = "52px"

_BG = "#0f1a2e"
_FG = "rgba(255,255,255,0.92)"
_FG_MUTED = "rgba(255,255,255,0.72)"
_FG_ACTIVE = "#ffffff"
_DIVIDER = "rgba(255,255,255,0.14)"
_SELECTED_BG = "rgba(255,255,255,0.10)"


_ICONS = {
    "addcontext": "\u2295",
    "generate":   "\u26A1",
    "browse":     "\u2630",
    "domains":    "\u25C7",
    "kb":         "\U0001F4DA",
    "config":     "\u2699\uFE0F",
    "metrics":    "\u2248",
}

_NAV_ITEMS = [
    {"id": "addcontext",       "icon": _ICONS["addcontext"], "label": "Context",   "href": "/addcontext",       "tooltip": "Add to Knowledge Base"},
    {"id": "generatetestcase", "icon": _ICONS["generate"],   "label": "Generate",  "href": "/generatetestcase", "tooltip": "Generate Artifacts"},
    {"id": "browseprompt",     "icon": _ICONS["browse"],     "label": "Browse",    "href": "/browseprompt",     "tooltip": "Browse Prompts"},
    {"id": "managedomain",     "icon": _ICONS["domains"],    "label": "Domains",   "href": "/managedomain",     "tooltip": "Manage Domains"},
    {"id": "knowledgebase",    "icon": _ICONS["kb"],         "label": "KB Chat",   "href": "/knowledge-base",   "tooltip": "Knowledge Base Chat"},
    {"id": "config",           "icon": _ICONS["config"],     "label": "Settings",  "href": "/config",           "tooltip": "App Settings"},
    {"id": "metrics",          "icon": _ICONS["metrics"],    "label": "Metrics",   "href": "/metrics",          "tooltip": "Performance Metrics"},
]


def _row_style(selected=False, collapsed=False):
    return {
        "display": "flex",
        "alignItems": "center",
        "gap": "10px",
        "padding": "8px 10px" if collapsed else "8px 12px",
        "margin": "2px 6px",
        "borderRadius": "6px",
        "cursor": "pointer",
        "transition": "background 0.15s ease, color 0.15s ease",
        "color": _FG_ACTIVE if selected else _FG,
        "backgroundColor": _SELECTED_BG if selected else "transparent",
        "fontWeight": 600 if selected else 500,
        "justifyContent": "center" if collapsed else "flex-start",
    }


def _label_style(collapsed=False):
    if collapsed:
        return {"display": "none"}
    return {"fontSize": "13px", "letterSpacing": "0.2px"}


def _nav_row(item):
    return html.Div(
        dcc.Link(
            [
                html.Span(
                    item["icon"],
                    **{"aria-hidden": "true"},
                    style={
                        "fontSize": "14px",
                        "width": "16px",
                        "textAlign": "center",
                        "lineHeight": "1",
                        "opacity": "1",
                    },
                ),
                html.Span(
                    item["label"],
                    id=f"{item['id']}-label",
                    style=_label_style(collapsed=False),
                ),
                # SR-only fallback so the link always has text when collapsed
                html.Span(item["label"], className="sr-only"),
            ],
            href=item["href"],
            title=item["tooltip"],
            style={
                "textDecoration": "none",
                "color": "inherit",
                "display": "flex",
                "alignItems": "center",
                "gap": "10px",
                "width": "100%",
                "justifyContent": "center",
            },
        ),
        id=f"{item['id']}-container",
        style=_row_style(selected=False, collapsed=False),
    )


def _wrapper_style(collapsed=False):
    width = SIDEBAR_COLLAPSED_WIDTH if collapsed else SIDEBAR_WIDTH
    return {
        "width": width,
        "flex": f"0 0 {width}",
        "height": "100%",
        "background": _BG,
        "display": "flex",
        "flexDirection": "column",
        "boxSizing": "border-box",
        "overflowY": "auto",
        "overflowX": "hidden",
        "borderRight": f"1px solid {_DIVIDER}",
        "transition": "width 0.15s ease, flex-basis 0.15s ease",
    }


def _brand_title_style(collapsed=False):
    if collapsed:
        return {"display": "none"}
    return {"fontSize": "15px", "fontWeight": 700, "color": _FG_ACTIVE, "letterSpacing": "0.2px"}


def _brand_subtitle_style(collapsed=False):
    if collapsed:
        return {"display": "none"}
    return {"fontSize": "10px", "color": _FG_MUTED, "marginTop": "2px"}


def _toggle_button_style(collapsed=False):
    return {
        "background": "transparent",
        "border": "none",
        "color": _FG_ACTIVE,
        "fontSize": "16px",
        "lineHeight": "1",
        "cursor": "pointer",
        "padding": "4px 6px",
        "borderRadius": "4px",
    }


def get_toolbox():
    rows = [_nav_row(item) for item in _NAV_ITEMS]

    brand = html.Div(
        [
            dcc.Link(
                [
                    html.Div("QE Studio", id="brand-title", style=_brand_title_style(False)),
                    html.Div("GenAI Workspace", id="brand-subtitle", style=_brand_subtitle_style(False)),
                ],
                href="/home",
                style={"textDecoration": "none", "flex": "1", "minWidth": "0"},
            ),
            html.Button(
                "\u00AB",
                id="sidebar-toggle",
                n_clicks=0,
                title="Collapse sidebar",
                **{
                    "aria-label": "Collapse sidebar",
                    "aria-expanded": "true",
                    "aria-controls": "primary-nav",
                },
                style=_toggle_button_style(False),
            ),
        ],
        id="brand-row",
        style={
            "display": "flex",
            "alignItems": "center",
            "padding": "12px 10px 10px",
            "gap": "6px",
        },
    )

    return html.Nav(
        [
            dcc.Store(id="sidebar-collapsed", data=False, storage_type="session"),
            brand,
            html.Hr(style={
                "border": "none",
                "borderTop": f"1px solid {_DIVIDER}",
                "margin": "0 0 8px",
            }),
            html.Div(
                rows,
                id="primary-nav",
                style={
                    "display": "flex",
                    "flexDirection": "column",
                    "paddingTop": "4px",
                },
            ),
        ],
        id="sidebar-wrapper",
        **{"aria-label": "Primary navigation"},
        style=_wrapper_style(collapsed=False),
    )


@callback(
    Output("sidebar-collapsed", "data"),
    Input("sidebar-toggle", "n_clicks"),
    State("sidebar-collapsed", "data"),
    prevent_initial_call=True,
)
def _toggle_sidebar(_, collapsed):
    return not bool(collapsed)


@callback(
    [
        Output("sidebar-wrapper", "style"),
        Output("brand-title", "style"),
        Output("brand-subtitle", "style"),
        Output("sidebar-toggle", "children"),
        Output("addcontext-label", "style"),
        Output("generatetestcase-label", "style"),
        Output("browseprompt-label", "style"),
        Output("managedomain-label", "style"),
        Output("knowledgebase-label", "style"),
        Output("config-label", "style"),
        Output("metrics-label", "style"),
    ],
    Input("sidebar-collapsed", "data"),
)
def _apply_collapse(collapsed):
    collapsed = bool(collapsed)
    chevron = "\u00BB" if collapsed else "\u00AB"
    label = _label_style(collapsed)
    return [
        _wrapper_style(collapsed),
        _brand_title_style(collapsed),
        _brand_subtitle_style(collapsed),
        chevron,
        label, label, label, label, label, label, label,
    ]


@callback(
    [
        Output("addcontext-container", "style"),
        Output("generatetestcase-container", "style"),
        Output("browseprompt-container", "style"),
        Output("managedomain-container", "style"),
        Output("knowledgebase-container", "style"),
        Output("config-container", "style"),
        Output("metrics-container", "style"),
    ],
    [Input("url", "pathname"), Input("sidebar-collapsed", "data")],
)
def update_toolbox_highlight(pathname, collapsed):
    routes = ["/addcontext", "/generatetestcase", "/browseprompt", "/managedomain", "/knowledge-base", "/config", "/metrics"]
    return [_row_style(selected=(pathname == r), collapsed=bool(collapsed)) for r in routes]


# Clientside: update aria-expanded + aria-label on the toggle for screen readers,
# and aria-current="page" on the active nav row.
clientside_callback(
    """    function(collapsed, pathname) {
        const btn = document.getElementById('sidebar-toggle');
        if (btn) {
            const expanded = !collapsed;
            btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
            btn.setAttribute('aria-label', expanded ? 'Collapse sidebar' : 'Expand sidebar');
            btn.setAttribute('title', expanded ? 'Collapse sidebar' : 'Expand sidebar');
        }
        const map = {
            'addcontext-container':       '/addcontext',
            'generatetestcase-container': '/generatetestcase',
            'browseprompt-container':     '/browseprompt',
            'managedomain-container':     '/managedomain',
            'knowledgebase-container':    '/knowledge-base',
            'config-container':           '/config',
            'metrics-container':          '/metrics',
        };
        Object.keys(map).forEach(function(id) {
            const el = document.getElementById(id);
            if (!el) return;
            if (pathname === map[id]) {
                el.setAttribute('aria-current', 'page');
            } else {
                el.removeAttribute('aria-current');
            }
        });
        return window.dash_clientside.no_update;
    }
    """,
    Output("sidebar-collapsed", "modified_timestamp"),
    [Input("sidebar-collapsed", "data"), Input("url", "pathname")],
)
