import base64
import io
import math
import threading
import uuid

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import ALL, MATCH, Dash, Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate

from configs.config import Config
from configs import kb_registry
import domains  # noqa: F401  (triggers profile registration)
from domains.registry import all_profiles, default_profile, get as get_profile
from models.generator_singleton import get_generator
from utilities.customlogger import logger
from utilities.domain_hint import render_domain_hint
from utilities import metrics_store
from utilities.upload_validation import (
    UploadValidationError,
    apply_source_alias,
    normalize_metadata,
    suggest_better_profile,
    validate_columns,
    validate_enum_values,
)

PAGE_SIZE = 10

# Shared look for the generated-output box so the view and the in-place
# editor line up visually — swapping Markdown ↔ Textarea in the same slot.
_OUTPUT_STYLE = {
    "backgroundColor": "#fffdf5",
    "border": "1px solid #e3e6ea",
    "padding": "12px",
    "borderRadius": "5px",
    "whiteSpace": "pre-wrap",
    "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    "fontSize": "13px",
    "lineHeight": "1.5",
}
_MARKDOWN_STYLE_VISIBLE = {**_OUTPUT_STYLE, "display": "block"}
_MARKDOWN_STYLE_HIDDEN = {**_OUTPUT_STYLE, "display": "none"}
_TEXTAREA_STYLE_HIDDEN = {
    **_OUTPUT_STYLE,
    "display": "none",
    "width": "100%",
    "minHeight": "20rem",
    "resize": "vertical",
}
_TEXTAREA_STYLE_VISIBLE = {**_TEXTAREA_STYLE_HIDDEN, "display": "block"}

# Background generation — the local LLM is slow, so we run the loop in a
# worker thread and let a dcc.Interval poll progress. State lives in this
# module-level dict keyed by job id; the Dash Store on the page holds only
# the job id string so the state survives across poll ticks.
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


def _job_snapshot(job_id):
    if not job_id:
        return None
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        return dict(job)


def _run_generation(job_id, data_list, profile_name, augment_kbs=None):
    try:
        from domains.registry import get as _get_profile
        from configs import settings_store
        profile = _get_profile(profile_name)
        generator = get_generator(profile_name=profile.name)
        mkeys = profile.metadata_keys
        source_col = profile.source_column
        generated_key = f"Generated {profile.target_label}"
        total = len(data_list)
        backend = (settings_store.get("llm.backend") or "openai").lower()
        model_name = (settings_store.get("llm.ollama.model") if backend == "ollama"
                      else settings_store.get("llm.openai.model"))
        metrics_store.start_run(job_id, profile.name, f"{backend}/{model_name}", total)
        with _JOBS_LOCK:
            _JOBS[job_id]["total"] = total
        for i, record in enumerate(data_list):
            req = record.get(source_col) or record.get("Requirement")
            fmt = record.get("Format", "plain_text")
            mne = record.get("mne", record.get("MNE", "N/A"))
            tech = record.get("tech", record.get("Tech", "N/A"))
            metadata = {mkeys["mne"]: mne, mkeys["tech"]: tech, mkeys["format"]: fmt}
            prompt, generated, item_metrics = generator.generate_test_case(
                req, metadata=metadata, return_with_prompt=True, k=3,
                augment_kbs=augment_kbs,
            )
            record[generated_key] = generated
            record["Prompt"] = prompt
            record["Status"] = "Generated"
            record["_metrics"] = item_metrics
            metrics_store.record_item(job_id, i, req or "", item_metrics)
            with _JOBS_LOCK:
                _JOBS[job_id]["done"] = i + 1
                _JOBS[job_id]["data"] = data_list
                _JOBS[job_id].setdefault("metrics", []).append(item_metrics)
        metrics_store.finish_run(job_id, "done")
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "done"
    except Exception as e:
        logger.exception("Generation job failed")
        metrics_store.finish_run(job_id, "error")
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "error"
            _JOBS[job_id]["error"] = str(e)


def _domain_options():
    return [{"label": f"{p.source_label} → {p.target_label}", "value": p.name} for p in all_profiles()]


def _augment_kb_options():
    return [
        {"label": f"{kb.get('name', kb['id'])} ({kb.get('doc_count', 0)} chunks)",
         "value": kb["id"]}
        for kb in kb_registry.list_kbs()
    ]

layout = dbc.Container(
    [
        html.H2("Generate From Source"),
        dbc.Row(
            [
                dbc.Col(html.Label("Domain:"), width="auto"),
                dbc.Col(
                    dbc.Select(
                        id="gen-domain",
                        options=_domain_options(),
                        value=default_profile().name,
                    ),
                    width=4,
                ),
            ],
            align="center",
            style={"margin-bottom": "10px"},
        ),
        dbc.Row(
            [
                dbc.Col(html.Label("Augment with KB:"), width="auto"),
                dbc.Col(
                    dcc.Dropdown(
                        id="gen-augment-kbs",
                        options=_augment_kb_options(),
                        multi=True,
                        placeholder="(Optional) pick one or more knowledge bases to fuse into the prompt",
                    ),
                    width=8,
                ),
            ],
            align="center",
            style={"margin-bottom": "10px"},
        ),
        html.Div(id="gen-domain-hint", style={"color": "#555", "margin-bottom": "10px"}),
        dcc.Store(id="gen-data", data=[]),
        dcc.Store(id="gen-page", data=1),
        dcc.Upload(
            id="gen-upload-data",
            children=html.Div(["Drag and Drop or ", html.A("Select Files")]),
            style={
                "width": "100%",
                "height": "60px",
                "lineHeight": "60px",
                "borderWidth": "1px",
                "borderStyle": "dashed",
                "borderRadius": "5px",
                "textAlign": "center",
            },
            multiple=False,
        ),
        html.Div(id="uploaded-file-content", style={"margin-top": "20px"}),
        dbc.Row(
            [
                dbc.Col(dbc.Button("Prev", id="gen-prev-btn", className="btn btn-secondary", n_clicks=0), width="auto"),
                dbc.Col(html.Div(id="pagination-info", style={"text-align": "center"}), width="auto"),
                dbc.Col(dbc.Button("Next", id="gen-next-btn", className="btn btn-secondary", n_clicks=0), width="auto"),
            ],
            justify="center",
            align="center",
            style={"margin-top": "20px"},
        ),
        html.Button("Generate", id="generate-btn", className="btn btn-primary", n_clicks=0),
        dcc.Store(id="gen-job-id"),
        dcc.Interval(id="gen-poll", interval=1000, disabled=True),
        html.Div(
            id="gen-progress",
            style={
                "position": "fixed",
                "right": "20px",
                "bottom": "60px",
                "width": "340px",
                "zIndex": 2000,
                "backgroundColor": "#ffffff",
                "border": "1px solid #ccc",
                "borderRadius": "8px",
                "padding": "10px 14px",
                "boxShadow": "0 4px 12px rgba(0,0,0,0.15)",
                "display": "none",
            },
        ),
        html.Div(id="generation-message", style={"margin-top": "20px", "color": "green"}),
        html.A(
            "Download Results",
            id="download-btn",
            className="btn btn-success",
            style={"margin-top": "10px", "display": "none"},
        ),
        html.Div(
            id="gen-nav-bar",
            style={
                "position": "sticky",
                "top": "0",
                "zIndex": 1000,
                "backgroundColor": "#f0f4f8",
                "borderBottom": "1px solid #ccc",
                "padding": "6px 12px",
                "display": "none",
                "overflowX": "auto",
                "whiteSpace": "nowrap",
            },
        ),
    ],
    fluid=True,
)


def parse_uploaded_file(contents, filename):
    try:
        _, content_string = contents.split(",")
        decoded = base64.b64decode(content_string)
        if filename.endswith(".csv"):
            df = pd.read_csv(io.StringIO(decoded.decode("utf-8")))
        elif filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(decoded))
        else:
            raise ValueError("Unsupported file format. Please upload a CSV or Excel file.")
        return df
    except Exception as e:
        raise ValueError(f"Error parsing file: {e}")


def create_cards_with_feedback(page_data, start_index=0, profile=None):
    profile = profile or default_profile()
    source_col_lower = profile.source_column.lower()
    target_key_lower = "generated " + profile.target_label.lower()
    source_label = profile.source_label
    target_label = profile.target_label
    cards = []
    for offset, record in enumerate(page_data):
        idx = start_index + offset
        lower = {k.lower(): v for k, v in record.items()}
        requirement = lower.get(source_col_lower, lower.get("requirement", f"No {source_label.lower()} provided."))
        format_type = lower.get("format", "N/A")
        mne = lower.get("mne", "N/A")
        tech = lower.get("tech", "N/A")
        status = lower.get("status", "Pending")
        status_color = "success" if status == "Generated" else "warning"
        generated_test_case = lower.get(target_key_lower, lower.get("generated test case", f"No {target_label.lower()} generated yet."))
        prompt = lower.get("prompt", "No prompt used.")

        # Short preview of the source for the card header
        source_preview = (requirement[:80] + "...") if len(str(requirement)) > 80 else requirement

        card = dbc.Card(
            [
                dbc.CardHeader(
                    dbc.Row(
                        [
                            dbc.Col(
                                html.Span(
                                    f"{source_label} #{idx + 1}",
                                    style={"font-weight": "bold"},
                                ),
                                width="auto",
                            ),
                            dbc.Col(
                                html.Small(source_preview, className="text-muted", style={"fontSize": "12px"}),
                            ),
                            dbc.Col(
                                dbc.Badge(status, color=status_color, className="float-end"),
                                width="auto",
                            ),
                        ],
                        justify="between",
                        align="center",
                    ),
                ),
                dbc.CardBody(
                    [
                        html.P(
                            [
                                "Application: ", html.Strong(f"{mne}"),
                                " | Tech: ", html.Strong(f"{tech}"),
                                " | Format: ", html.Strong(f"{format_type}"),
                            ],
                            className="card-text mb-2",
                            style={"fontSize": "13px"},
                        ),
                        html.Div(
                            [
                                html.Span(f"{mne}", id={"type": "mne", "index": idx}, style={"display": "none"}),
                                html.Span(f"{tech}", id={"type": "tech", "index": idx}, style={"display": "none"}),
                                html.Span(f"{format_type}", id={"type": "format", "index": idx}, style={"display": "none"}),
                            ]
                        ),
                        html.H6(source_label, className="card-title mt-2", style={"fontWeight": 600}),
                        dcc.Markdown(
                            requirement,
                            id={"type": "requirement", "index": idx},
                            className="card-text",
                            style={
                                "backgroundColor": "#fafbfc",
                                "border": "1px solid #e3e6ea",
                                "padding": "10px",
                                "borderRadius": "5px",
                                "maxHeight": "420px",
                                "overflowY": "auto",
                                "fontSize": "13px",
                                "lineHeight": "1.5",
                            },
                        ),

                        # Collapsible prompt section — collapsed by default
                        html.Details(
                            [
                                html.Summary(
                                    "Prompt Used",
                                    style={"cursor": "pointer", "fontWeight": 600, "fontSize": "14px", "color": "#555"},
                                ),
                                dcc.Markdown(
                                    prompt,
                                    className="card-text mt-2",
                                    style={
                                        "backgroundColor": "#f8f9fa",
                                        "padding": "10px",
                                        "borderRadius": "5px",
                                        "whiteSpace": "pre-wrap",
                                        "fontFamily": "monospace",
                                        "fontSize": "12px",
                                        "maxHeight": "400px",
                                        "overflowY": "auto",
                                    },
                                ),
                            ],
                            style={"marginBottom": "12px"},
                        ),

                        html.H6(f"Generated {target_label}:", className="card-title", style={"fontWeight": 600}),
                        dcc.Markdown(
                            generated_test_case,
                            id={"type": "generated-test-case", "index": idx},
                            className="card-text",
                            style=dict(_MARKDOWN_STYLE_VISIBLE),
                        ),
                        dbc.Textarea(
                            id={"type": "edit-textarea", "index": idx},
                            value=generated_test_case,
                            style=dict(_TEXTAREA_STYLE_HIDDEN),
                        ),

                        html.Div(
                            [
                                dbc.Button("Edit", id={"type": "edit-btn", "index": idx}, color="info", size="sm",
                                           style={"margin-top": "10px", "margin-right": "5px"}),
                                dbc.Button(
                                    "Save Curated",
                                    id={"type": "save-btn", "index": idx},
                                    color="primary",
                                    size="sm",
                                    style={"display": "none", "margin-top": "10px", "margin-right": "5px"},
                                ),
                                dbc.Row(
                                    [
                                        dbc.Col(
                                            dbc.Button("👍", id={"type": "thumbs-up", "index": idx}, color="success",
                                                       size="sm"),
                                            width="auto",
                                        ),
                                        dbc.Col(
                                            dbc.Button("👎", id={"type": "thumbs-down", "index": idx}, color="danger",
                                                       size="sm"),
                                            width="auto",
                                        ),
                                    ],
                                    justify="start",
                                    style={"margin-top": "10px"},
                                ),
                                html.Div(id={"type": "feedback-message", "index": idx}, style={"margin-top": "10px"}),
                            ],
                            style={"display": "block" if status == "Generated" else "none"},
                        ),
                    ]
                ),
            ],
            id=f"gen-card-{idx}",
            style={"margin-bottom": "15px"},
        )
        cards.append(card)
    return cards


def _build_nav_bar(data_list, profile):
    """Build a sticky navigation bar with links to each generated item."""
    if not data_list:
        return html.Div(), {"display": "none"}
    source_label = profile.source_label
    links = []
    for i, record in enumerate(data_list):
        lower = {k.lower(): v for k, v in record.items()}
        source_text = lower.get(profile.source_column.lower(), lower.get("requirement", ""))
        preview = (str(source_text)[:40] + "...") if len(str(source_text)) > 40 else str(source_text)
        links.append(
            html.A(
                f"{source_label} {i + 1}",
                href=f"#gen-card-{i}",
                title=preview,
                className="btn btn-outline-secondary btn-sm me-1",
                style={"fontSize": "12px", "textDecoration": "none"},
            )
        )
    nav = html.Div(
        [html.Strong(f"{source_label}s: ", style={"fontSize": "13px", "marginRight": "8px"})] + links,
        style={"display": "inline-flex", "alignItems": "center", "flexWrap": "wrap", "gap": "2px"},
    )
    visible = {
        "position": "sticky",
        "top": "0",
        "zIndex": 1000,
        "backgroundColor": "#f0f4f8",
        "borderBottom": "1px solid #ccc",
        "padding": "6px 12px",
        "display": "block",
        "overflowX": "auto",
        "whiteSpace": "nowrap",
    }
    return nav, visible


_PROGRESS_BASE_STYLE = {
    "position": "fixed",
    "right": "20px",
    "bottom": "60px",
    "width": "340px",
    "zIndex": 2000,
    "backgroundColor": "#ffffff",
    "border": "1px solid #ccc",
    "borderRadius": "8px",
    "padding": "10px 14px",
    "boxShadow": "0 4px 12px rgba(0,0,0,0.15)",
}
_PROGRESS_VISIBLE = {**_PROGRESS_BASE_STYLE, "display": "block"}
_PROGRESS_HIDDEN = {**_PROGRESS_BASE_STYLE, "display": "none"}


def _render_progress(done, total, *, finished=False, target_label="results"):
    total = max(total, 1)
    pct = int(round(100 * done / total))
    if finished:
        label = f"✅ Generated {done} of {total} — done."
        color = "success"
    else:
        current = min(done + 1, total)
        label = f"Generating {target_label.lower()}… ({current} of {total}) — {pct}% complete"
        color = "info"
    close_btn = html.Button(
        "×",
        id="gen-progress-close",
        n_clicks=0,
        title="Close",
        style={
            "position": "absolute",
            "top": "4px",
            "right": "8px",
            "border": "none",
            "background": "transparent",
            "fontSize": "20px",
            "lineHeight": "1",
            "cursor": "pointer",
            "color": "#666",
            "padding": "0 4px",
        },
    )
    return html.Div(
        [
            close_btn,
            html.Div(label, style={"marginBottom": "6px", "fontWeight": 600, "paddingRight": "20px"}),
            dbc.Progress(value=pct, color=color, striped=not finished, animated=not finished, style={"height": "18px"}),
        ],
        style={"position": "relative"},
    )


def _page_slice(data, page):
    total_pages = max(1, math.ceil(len(data) / PAGE_SIZE)) if data else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    return data[start:start + PAGE_SIZE], page, total_pages, start


_INTERNAL_DOWNLOAD_COLUMNS = (
    "Status", "Prompt", "_metrics", "Curated", "similarity_score",
)


def _shape_download_frame(data, profile):
    """Build a chain-ready DataFrame for the Excel download.

    Strips internal bookkeeping columns and, when the profile declares a
    downstream domain, blanks the Format column — format enums differ per
    domain (e.g. test_case uses bdd/plain_text, manual_to_automation uses
    playwright/selenium), so carrying the prior value would fail strict
    upload validation on the next step."""
    df = pd.DataFrame(data)
    if df.empty:
        return df
    drop_cols = [c for c in _INTERNAL_DOWNLOAD_COLUMNS if c in df.columns]
    if drop_cols:
        df = df.drop(columns=drop_cols)
    if profile is not None and getattr(profile, "next_profile_name", None):
        for col in ("Format", "format"):
            if col in df.columns:
                df[col] = ""
    return df


def generate_excel_download_link(data, profile=None):
    df = _shape_download_frame(data, profile)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="TestCases")
    output.seek(0)
    encoded = base64.b64encode(output.read()).decode()
    return f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{encoded}"


def register_callbacks(app: Dash):
    @app.callback(
        Output("gen-domain-hint", "children"),
        Input("gen-domain", "value"),
    )
    def show_gen_domain_hint(domain_value):
        profile = get_profile(domain_value) if domain_value else default_profile()
        return render_domain_hint(profile, include_target=False)

    @app.callback(
        [
            Output({"type": "generated-test-case", "index": MATCH}, "style"),
            Output({"type": "edit-textarea", "index": MATCH}, "style"),
            Output({"type": "edit-textarea", "index": MATCH}, "value"),
            Output({"type": "save-btn", "index": MATCH}, "style"),
        ],
        [Input({"type": "edit-btn", "index": MATCH}, "n_clicks")],
        [State({"type": "generated-test-case", "index": MATCH}, "children")],
        prevent_initial_call=True,
    )
    def toggle_edit(n_clicks, current_text):
        if n_clicks and n_clicks > 0:
            save_style = {"display": "inline-block", "margin-top": "10px", "margin-right": "5px"}
            # Seed the editor with the currently displayed markdown so edits
            # start from the latest content (important after a previous save).
            return (
                dict(_MARKDOWN_STYLE_HIDDEN),
                dict(_TEXTAREA_STYLE_VISIBLE),
                current_text or "",
                save_style,
            )
        return (
            dict(_MARKDOWN_STYLE_VISIBLE),
            dict(_TEXTAREA_STYLE_HIDDEN),
            dash.no_update,
            {"display": "none"},
        )

    @app.callback(
        [
            Output("uploaded-file-content", "children"),
            Output("pagination-info", "children"),
            Output("generation-message", "children"),
            Output("download-btn", "href", allow_duplicate=True),
            Output("download-btn", "style", allow_duplicate=True),
            Output("download-btn", "download"),
            Output("gen-data", "data", allow_duplicate=True),
            Output("gen-page", "data"),
            Output("gen-upload-data", "contents", allow_duplicate=True),
        ],
        [
            Input("gen-upload-data", "contents"),
            Input("gen-prev-btn", "n_clicks"),
            Input("gen-next-btn", "n_clicks"),
        ],
        [
            State("gen-upload-data", "filename"),
            State("gen-data", "data"),
            State("gen-page", "data"),
            State("gen-domain", "value"),
        ],
        prevent_initial_call=True,
    )
    def handle_main(contents, prev_clicks, next_clicks, filename, data_list, current_page, domain_value):
        profile = get_profile(domain_value) if domain_value else default_profile()
        ctx = callback_context
        if not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        data_list = data_list or []
        current_page = current_page or 1
        hidden = {"display": "none"}

        if triggered_id == "gen-upload-data":
            if not contents:
                return (dash.no_update,) * 9
            dl_filename = f"Generated_{profile.target_label}s.xlsx"
            try:
                df = parse_uploaded_file(contents, filename)
                original_df = df
                df = apply_source_alias(df, profile)
                validate_columns(df, profile=profile, include_target=False)
                records = df.to_dict("records")
                records = [normalize_metadata(r) for r in records]
                warnings = validate_enum_values(records, profile=profile, strict_format=True)
                generated_key = f"Generated {profile.target_label}"
                for record in records:
                    record["Status"] = "Pending"
                    record[generated_key] = f"No {profile.target_label.lower()} generated yet."
                page_data, current_page, total_pages, start = _page_slice(records, 1)
                cards = create_cards_with_feedback(page_data, start_index=start, profile=profile)
                warn_children = ""
                if warnings:
                    warn_children = html.Div(
                        ["Warnings:"] + [html.Div(w) for w in warnings[:10]],
                        style={"color": "#b37400"},
                    )
                return cards, f"Page {current_page} of {total_pages}", warn_children, "", hidden, dl_filename, records, 1, None
            except UploadValidationError as e:
                msg = f"Upload error: {e}"
                try:
                    better = suggest_better_profile(original_df, profile)
                except Exception:
                    better = None
                if better is not None:
                    msg += (
                        f"\n\nDid you mean to select "
                        f"'{better.source_label} → {better.target_label}' as the Domain?"
                    )
                return msg, "", "", "", hidden, dl_filename, [], 1, None
            except Exception as e:
                return f"Error processing file: {e}", "", "", "", hidden, dl_filename, [], 1, None

        if not data_list:
            return dash.no_update, dash.no_update, "No data available.", dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if triggered_id in ("gen-prev-btn", "gen-next-btn"):
            total_pages = max(1, math.ceil(len(data_list) / PAGE_SIZE))
            if triggered_id == "gen-prev-btn" and current_page > 1:
                current_page -= 1
            elif triggered_id == "gen-next-btn" and current_page < total_pages:
                current_page += 1
            page_data, current_page, total_pages, start = _page_slice(data_list, current_page)
            cards = create_cards_with_feedback(page_data, start_index=start, profile=profile)
            return cards, f"Page {current_page} of {total_pages}", "", dash.no_update, dash.no_update, dash.no_update, dash.no_update, current_page, dash.no_update

        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # Kick off a background generation thread on Generate click. The thread
    # mutates module-level _JOBS state; the Interval below polls it.
    @app.callback(
        Output("gen-progress", "style", allow_duplicate=True),
        Input("gen-progress-close", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_progress(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        return dict(_PROGRESS_HIDDEN)

    @app.callback(
        [
            Output("gen-job-id", "data"),
            Output("gen-poll", "disabled", allow_duplicate=True),
            Output("gen-progress", "children", allow_duplicate=True),
            Output("gen-progress", "style", allow_duplicate=True),
            Output("generation-message", "children", allow_duplicate=True),
            Output("download-btn", "style", allow_duplicate=True),
            Output("gen-nav-bar", "children", allow_duplicate=True),
            Output("gen-nav-bar", "style", allow_duplicate=True),
        ],
        Input("generate-btn", "n_clicks"),
        [State("gen-data", "data"), State("gen-domain", "value"),
         State("gen-augment-kbs", "value")],
        prevent_initial_call=True,
    )
    def start_generation(n_clicks, data_list, domain_value, augment_kbs):
        if not n_clicks or not data_list:
            raise PreventUpdate
        profile = get_profile(domain_value) if domain_value else default_profile()
        job_id = uuid.uuid4().hex
        augment_kbs = [k for k in (augment_kbs or []) if k]
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "status": "running",
                "total": len(data_list),
                "done": 0,
                "data": None,
                "error": None,
                "profile_name": profile.name,
                "augment_kbs": augment_kbs,
            }
        threading.Thread(
            target=_run_generation,
            args=(job_id, data_list, profile.name, augment_kbs),
            daemon=True,
        ).start()
        progress = _render_progress(0, len(data_list), target_label=profile.target_label)
        return (
            job_id, False, progress, dict(_PROGRESS_VISIBLE), "",
            {"margin-top": "10px", "display": "none"},
            "", {"display": "none"},
        )

    @app.callback(
        [
            Output("gen-progress", "children", allow_duplicate=True),
            Output("gen-progress", "style", allow_duplicate=True),
            Output("gen-poll", "disabled", allow_duplicate=True),
            Output("uploaded-file-content", "children", allow_duplicate=True),
            Output("pagination-info", "children", allow_duplicate=True),
            Output("generation-message", "children", allow_duplicate=True),
            Output("download-btn", "href", allow_duplicate=True),
            Output("download-btn", "style", allow_duplicate=True),
            Output("download-btn", "children", allow_duplicate=True),
            Output("gen-data", "data", allow_duplicate=True),
            Output("gen-nav-bar", "children", allow_duplicate=True),
            Output("gen-nav-bar", "style", allow_duplicate=True),
        ],
        Input("gen-poll", "n_intervals"),
        [
            State("gen-job-id", "data"),
            State("gen-page", "data"),
            State("gen-domain", "value"),
        ],
        prevent_initial_call=True,
    )
    def poll_generation(n_intervals, job_id, current_page, domain_value):
        snap = _job_snapshot(job_id)
        _no = dash.no_update
        if snap is None:
            return _no, dict(_PROGRESS_HIDDEN), True, _no, _no, _no, _no, _no, _no, _no, _no, _no
        profile = get_profile(domain_value) if domain_value else default_profile()
        total, done = snap.get("total", 0) or 0, snap.get("done", 0) or 0

        if snap["status"] == "running":
            return (
                _render_progress(done, total, target_label=profile.target_label),
                dict(_PROGRESS_VISIBLE),
                False,
                _no, _no, _no, _no, _no, _no, _no, _no, _no,
            )

        if snap["status"] == "error":
            return (
                "",
                dict(_PROGRESS_HIDDEN),
                True,
                _no, _no,
                f"An error occurred during generation: {snap.get('error')}",
                _no, _no, _no, _no, _no, _no,
            )

        # Done — render final cards, enable download, build nav bar.
        data_list = snap.get("data") or []
        page_data, current_page, total_pages, start = _page_slice(data_list, current_page or 1)
        cards = create_cards_with_feedback(page_data, start_index=start, profile=profile)
        href = generate_excel_download_link(data_list, profile=profile) if data_list else ""
        dl_visible = {"margin-top": "10px", "display": "inline-block"} if data_list else {"display": "none"}
        dl_label = f"Download {profile.target_label}s"
        nav_children, nav_style = _build_nav_bar(data_list, profile)
        with _JOBS_LOCK:
            _JOBS.pop(job_id, None)
        return (
            _render_progress(total, total, finished=True),
            dict(_PROGRESS_VISIBLE),
            True,
            cards,
            f"Page {current_page} of {total_pages}",
            f"{profile.target_label}s generated successfully!",
            href,
            dl_visible,
            dl_label,
            data_list,
            nav_children,
            nav_style,
        )

    @app.callback(
        Output({"type": "feedback-message", "index": MATCH}, "children", allow_duplicate=True),
        [
            Input({"type": "thumbs-up", "index": MATCH}, "n_clicks"),
            Input({"type": "thumbs-down", "index": MATCH}, "n_clicks"),
        ],
        [
            State({"type": "generated-test-case", "index": MATCH}, "children"),
            State({"type": "requirement", "index": MATCH}, "children"),
            State({"type": "mne", "index": MATCH}, "children"),
            State({"type": "tech", "index": MATCH}, "children"),
            State({"type": "format", "index": MATCH}, "children"),
            State("gen-domain", "value"),
        ],
        prevent_initial_call=True,
    )
    def handle_feedback(thumbs_up, thumbs_down, generated_text, requirement, mne, tech, format_type, domain_value):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate
        triggered = ctx.triggered[0]["prop_id"]
        profile = get_profile(domain_value) if domain_value else default_profile()
        mkeys = profile.metadata_keys

        is_thumbs_up = "thumbs-up" in triggered
        metadata = {
            mkeys["mne"]: mne,
            mkeys["tech"]: tech,
            mkeys["format"]: format_type,
            mkeys["priority"]: (
                Config.USE_CASE_TG_THUMBS_UP_PRIORITY if is_thumbs_up
                else Config.USE_CASE_TG_THUMBS_DOWN_PRIORITY
            ),
        }
        try:
            get_generator(profile_name=profile.name).update_test_cases(
                requirements=[requirement],
                test_cases=[generated_text],
                metadata=[metadata],
            )
            return "👍 Feedback recorded." if is_thumbs_up else "👎 Feedback recorded."
        except Exception as e:
            logger.error("Error recording feedback: %s", e)
            return f"Error: {e}"

    # Save is split across two independent callbacks. Dash forbids mixing
    # MATCH outputs (per-card) with plain-id outputs (gen-data, download-btn)
    # in a single callback, so we run two: one pure-MATCH callback does the
    # KB write and per-card UI update; one pure-plain callback uses ALL to
    # listen to the same button click and refreshes gen-data + download link.
    @app.callback(
        [
            Output({"type": "feedback-message", "index": MATCH}, "children", allow_duplicate=True),
            Output({"type": "generated-test-case", "index": MATCH}, "children", allow_duplicate=True),
            Output({"type": "generated-test-case", "index": MATCH}, "style", allow_duplicate=True),
            Output({"type": "edit-textarea", "index": MATCH}, "style", allow_duplicate=True),
            Output({"type": "save-btn", "index": MATCH}, "style", allow_duplicate=True),
        ],
        Input({"type": "save-btn", "index": MATCH}, "n_clicks"),
        [
            State({"type": "edit-textarea", "index": MATCH}, "value"),
            State({"type": "requirement", "index": MATCH}, "children"),
            State({"type": "mne", "index": MATCH}, "children"),
            State({"type": "tech", "index": MATCH}, "children"),
            State({"type": "format", "index": MATCH}, "children"),
            State("gen-domain", "value"),
        ],
        prevent_initial_call=True,
    )
    def handle_save_card(n_clicks, edited_text, requirement, mne, tech, format_type, domain_value):
        if not n_clicks:
            raise PreventUpdate
        new_text = (edited_text or "").strip()
        if not new_text:
            return (
                "⚠️ Empty edit ignored — nothing saved.",
                dash.no_update, dash.no_update, dash.no_update, dash.no_update,
            )

        profile = get_profile(domain_value) if domain_value else default_profile()
        mkeys = profile.metadata_keys
        metadata = {
            mkeys["mne"]: mne,
            mkeys["tech"]: tech,
            mkeys["format"]: format_type,
        }
        try:
            result = get_generator(profile_name=profile.name).save_curated_test_case(
                requirement, new_text, metadata
            )
        except Exception as e:
            logger.error("Error saving curated test case: %s", e)
            return (
                f"Error saving: {e}",
                dash.no_update, dash.no_update, dash.no_update, dash.no_update,
            )

        msg = f"✅ Curated and saved to KB ({result.get('status', 'ok')}). Download refreshed."
        return (
            msg,
            new_text,
            dict(_MARKDOWN_STYLE_VISIBLE),
            dict(_TEXTAREA_STYLE_HIDDEN),
            {"display": "none"},
        )

    @app.callback(
        [
            Output("gen-data", "data", allow_duplicate=True),
            Output("download-btn", "href", allow_duplicate=True),
            Output("download-btn", "style", allow_duplicate=True),
        ],
        Input({"type": "save-btn", "index": ALL}, "n_clicks"),
        [
            State({"type": "save-btn", "index": ALL}, "id"),
            State({"type": "edit-textarea", "index": ALL}, "value"),
            State("gen-data", "data"),
            State("gen-domain", "value"),
        ],
        prevent_initial_call=True,
    )
    def sync_save_to_data(all_clicks, all_ids, all_edits, data_list, domain_value):
        ctx = callback_context
        if not ctx.triggered or not any(all_clicks or []):
            raise PreventUpdate
        triggered_prop = ctx.triggered[0]["prop_id"]
        # Cold-load: the ALL Input fires at layout time with n_clicks=None.
        if ctx.triggered[0]["value"] in (None, 0):
            raise PreventUpdate

        # Find which card fired by matching the triggered prop's id portion.
        try:
            import json
            triggered_id = json.loads(triggered_prop.split(".")[0])
            idx = triggered_id.get("index")
        except Exception:
            raise PreventUpdate

        # Locate the matching textarea value.
        new_text = None
        for bid, val in zip(all_ids or [], all_edits or []):
            if isinstance(bid, dict) and bid.get("index") == idx:
                new_text = (val or "").strip()
                break
        if not new_text:
            raise PreventUpdate

        profile = get_profile(domain_value) if domain_value else default_profile()
        generated_key = f"Generated {profile.target_label}"
        data_list = list(data_list) if data_list else []
        if idx is None or not (0 <= idx < len(data_list)):
            raise PreventUpdate
        data_list[idx][generated_key] = new_text
        data_list[idx]["Curated"] = True
        data_list[idx]["Status"] = "Curated"
        href = generate_excel_download_link(data_list, profile=profile)
        visible = {"margin-top": "10px", "display": "inline-block"}
        return data_list, href, visible
