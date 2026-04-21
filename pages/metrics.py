"""
Metrics page — per-run performance breakdown and timing analysis.

Shows a table of recent generation runs with drill-down into per-item
timing (retrieval, prompt build, LLM, store-back). Auto-refreshes
while a run is in progress.
"""

import datetime

import dash
import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, State, dcc, html

from utilities import metrics_store


def _fmt_ts(ts):
    if not ts:
        return "—"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _status_badge(status):
    color = {"done": "success", "running": "info", "error": "danger"}.get(status, "secondary")
    return dbc.Badge(status, color=color, className="ms-1")


def _build_run_table(runs):
    if not runs:
        return html.P("No generation runs recorded yet. Generate some artifacts and come back.", className="text-muted mt-3")
    header = html.Thead(html.Tr([
        html.Th("Run ID"),
        html.Th("Domain"),
        html.Th("Model"),
        html.Th("Items"),
        html.Th("Status"),
        html.Th("Avg Retrieval"),
        html.Th("Avg LLM"),
        html.Th("Avg Total"),
        html.Th("Run Total"),
        html.Th("Started"),
        html.Th(""),
    ]))
    rows = []
    for r in runs:
        rows.append(html.Tr([
            html.Td(r["run_id"][:8] + "..."),
            html.Td(r["domain"]),
            html.Td(r["model"]),
            html.Td(f"{r['completed_items']}/{r['total_items']}"),
            html.Td(_status_badge(r["status"])),
            html.Td(f"{r.get('avg_retrieval_sec', '—')}s"),
            html.Td(f"{r.get('avg_llm_sec', '—')}s"),
            html.Td(f"{r.get('avg_total_sec', '—')}s"),
            html.Td(f"{r.get('total_run_sec', '—')}s"),
            html.Td(_fmt_ts(r["started_at"])),
            html.Td(
                dbc.Button("Details", size="sm", color="primary", outline=True,
                           id={"type": "metrics-detail-btn", "index": r["run_id"]}),
            ),
        ]))
    return dbc.Table([header, html.Tbody(rows)], bordered=True, hover=True, size="sm", className="mt-3")


def _build_detail_table(run):
    if not run or not run.get("items"):
        return html.P("No item-level data available.", className="text-muted")
    items = run["items"]
    header = html.Thead(html.Tr([
        html.Th("#"),
        html.Th("Source (preview)"),
        html.Th("Retrieval"),
        html.Th("Docs"),
        html.Th("Top Sim"),
        html.Th("Context?"),
        html.Th("Prompt Build"),
        html.Th("Prompt Size"),
        html.Th("LLM"),
        html.Th("Response Size"),
        html.Th("Store"),
        html.Th("Total"),
    ]))
    rows = []
    for it in items:
        rows.append(html.Tr([
            html.Td(str(it["index"] + 1) if isinstance(it.get("index"), int) else "—"),
            html.Td(it.get("source_preview", "—"), style={"maxWidth": "200px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            html.Td(f"{it.get('retrieval_sec', '—')}s"),
            html.Td(it.get("docs_retrieved", "—")),
            html.Td(f"{it.get('top_similarity', '—')}"),
            html.Td("Yes" if it.get("context_used") else "No"),
            html.Td(f"{it.get('prompt_build_sec', '—')}s"),
            html.Td(f"{it.get('prompt_len_chars', '—'):,}" if isinstance(it.get("prompt_len_chars"), int) else "—"),
            html.Td(f"{it.get('llm_sec', '—')}s", style={"fontWeight": "bold"}),
            html.Td(f"{it.get('response_len_chars', '—'):,}" if isinstance(it.get("response_len_chars"), int) else "—"),
            html.Td(f"{it.get('store_sec', '—')}s"),
            html.Td(f"{it.get('total_sec', '—')}s", style={"fontWeight": "bold"}),
        ]))

    avg_row = html.Tr([
        html.Td("AVG", style={"fontWeight": "bold"}),
        html.Td(""),
        html.Td(f"{_avg(items, 'retrieval_sec')}s", style={"fontWeight": "bold"}),
        html.Td(f"{_avg(items, 'docs_retrieved', fmt='.0f')}"),
        html.Td(""),
        html.Td(""),
        html.Td(f"{_avg(items, 'prompt_build_sec')}s"),
        html.Td(""),
        html.Td(f"{_avg(items, 'llm_sec')}s", style={"fontWeight": "bold", "color": "#d63384"}),
        html.Td(""),
        html.Td(f"{_avg(items, 'store_sec')}s"),
        html.Td(f"{_avg(items, 'total_sec')}s", style={"fontWeight": "bold", "color": "#d63384"}),
    ], style={"backgroundColor": "#f8f9fa"})

    return dbc.Table(
        [header, html.Tbody(rows + [avg_row])],
        bordered=True, hover=True, size="sm", striped=True,
    )


def _avg(items, key, fmt=".3f"):
    vals = [it[key] for it in items if isinstance(it.get(key), (int, float))]
    if not vals:
        return "—"
    return f"{sum(vals) / len(vals):{fmt}}"


def _build_summary_cards(runs):
    if not runs:
        return html.Div()
    completed = [r for r in runs if r["status"] == "done" and r.get("avg_llm_sec")]
    if not completed:
        return html.Div()
    latest = completed[0]
    total_runs = len(runs)
    total_items = sum(r["completed_items"] for r in runs)
    avg_llm_all = sum(r.get("avg_llm_sec", 0) * r["completed_items"] for r in completed) / max(sum(r["completed_items"] for r in completed), 1)
    return dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("Total Runs", className="text-muted"),
            html.H3(str(total_runs)),
        ])), width=2),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("Total Items", className="text-muted"),
            html.H3(str(total_items)),
        ])), width=2),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("Avg LLM Time", className="text-muted"),
            html.H3(f"{avg_llm_all:.1f}s"),
        ])), width=2),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("Latest Model", className="text-muted"),
            html.H3(latest["model"], style={"fontSize": "16px"}),
        ])), width=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("Latest Avg Total", className="text-muted"),
            html.H3(f"{latest.get('avg_total_sec', '—')}s"),
        ])), width=3),
    ], className="mb-3")


layout = dbc.Container([
    html.H3("Performance Metrics", className="mt-3"),
    html.P("Per-run timing breakdown for generation jobs. Click Details to drill into individual items.",
           className="text-muted"),
    dcc.Interval(id="metrics-refresh", interval=5000, n_intervals=0),
    html.Div(id="metrics-summary"),
    html.Div(id="metrics-run-table"),
    html.Hr(),
    html.Div(id="metrics-detail-section"),
    dcc.Store(id="metrics-selected-run"),
], fluid=True, style={"maxWidth": "1400px", "paddingBottom": "60px"})


def register_callbacks(app: Dash):
    @app.callback(
        [Output("metrics-summary", "children"),
         Output("metrics-run-table", "children")],
        Input("metrics-refresh", "n_intervals"),
    )
    def refresh_runs(_):
        runs = metrics_store.list_runs()
        return _build_summary_cards(runs), _build_run_table(runs)

    @app.callback(
        [Output("metrics-detail-section", "children"),
         Output("metrics-selected-run", "data")],
        Input({"type": "metrics-detail-btn", "index": dash.ALL}, "n_clicks"),
        State("metrics-selected-run", "data"),
        prevent_initial_call=True,
    )
    def show_details(n_clicks_list, current_run_id):
        ctx = dash.callback_context
        if not ctx.triggered or not any(n_clicks_list):
            return dash.no_update, dash.no_update
        prop_id = ctx.triggered[0]["prop_id"]
        import json
        try:
            btn_id = json.loads(prop_id.split(".")[0])
            run_id = btn_id["index"]
        except Exception:
            return dash.no_update, dash.no_update

        run = metrics_store.get_run(run_id)
        if not run:
            return html.P("Run not found.", className="text-danger"), None

        header = html.Div([
            html.H5([
                f"Run {run_id[:8]}... ",
                _status_badge(run["status"]),
            ]),
            html.P([
                f"Domain: {run['domain']} | Model: {run['model']} | ",
                f"Items: {len(run.get('items', []))}/{run['total_items']} | ",
                f"Started: {_fmt_ts(run['started_at'])} | ",
                f"Finished: {_fmt_ts(run.get('finished_at'))}",
            ], className="text-muted small"),
        ])
        detail = _build_detail_table(run)
        return html.Div([header, detail]), run_id
