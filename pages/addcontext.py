import base64
import io
import math

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Dash, Input, Output, State, callback_context, dcc, html

from configs.config import Config
import domains  # noqa: F401  (triggers profile registration)
from domains.registry import all_profiles, default_profile, get as get_profile
from models.generator_singleton import get_generator
from utilities.domain_hint import render_domain_hint
from utilities.upload_validation import (
    UploadValidationError,
    apply_source_alias,
    normalize_metadata,
    suggest_better_profile,
    validate_columns,
    validate_enum_values,
)

PAGE_SIZE = 10


def _domain_options():
    return [{"label": f"{p.source_label} → {p.target_label}", "value": p.name} for p in all_profiles()]


def create_cards_from_page_data(page_data, start_index=0, profile=None):
    profile = profile or default_profile()
    source_col = profile.source_column
    target_col = profile.target_column
    cards = []
    for offset, record in enumerate(page_data):
        idx = start_index + offset
        status = record.get("Status", "Pending")
        sim = record.get("similarity_score")
        if status == "Already Exist" and sim is not None:
            status_label = f"Already Exist (SC: {float(sim):.2f})"
            status_color = "danger"
        elif status == "Added":
            status_label = status
            status_color = "success"
        elif status == "Pending":
            status_label = status
            status_color = "warning"
        else:
            status_label = status
            status_color = "warning"

        card = dbc.Card(
            [
                dbc.CardHeader(
                    dbc.Row(
                        [
                            dbc.Col(html.Span(f"# {idx + 1}", style={"font-weight": "bold"}), width="auto"),
                            dbc.Col(
                                dbc.Badge(status_label, color=status_color, className="float-end"),
                                width="auto",
                            ),
                        ],
                        justify="between",
                        align="center",
                    ),
                    style={"background-color": "#f8f9fa"},
                ),
                dbc.CardBody(
                    [
                        html.H5("Details", className="card-title"),
                        html.P(
                            [
                                "Application: ", html.Strong(record.get("mne", "N/A")),
                                ", Tech: ", html.Strong(record.get("tech", "N/A")),
                                ", Format: ", html.Strong(record.get("Format", "plain_text")),
                            ],
                            className="card-text",
                        ),
                        html.H5(profile.source_label, className="card-title"),
                        html.P(record.get(source_col, f"No {profile.source_label.lower()} provided."), className="card-text"),
                        html.H5(profile.target_label, className="card-title"),
                        dcc.Markdown(record.get(target_col, f"No {profile.target_label.lower()} available."), className="card-text"),
                    ]
                ),
            ],
            style={"margin-bottom": "15px"},
        )
        cards.append(card)
    return cards


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
    except UploadValidationError:
        raise
    except Exception as e:
        raise ValueError(f"Error parsing file: {e}")


layout = dbc.Container(
    [
        html.H2("Add Domain Examples"),
        dbc.Row(
            [
                dbc.Col(html.Label("Domain:"), width="auto"),
                dbc.Col(
                    dbc.Select(
                        id="addcontext-domain",
                        options=_domain_options(),
                        value=default_profile().name,
                    ),
                    width=4,
                ),
            ],
            align="center",
            style={"margin-bottom": "15px"},
        ),
        html.Div(id="addcontext-domain-hint", style={"color": "#555", "margin-bottom": "10px"}),
        dcc.Store(id="addcontext-data", data=[]),
        dcc.Store(id="addcontext-page", data=1),
        dcc.Upload(
            id="upload-data",
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
        html.Div(id="file-content", style={"margin-top": "20px"}),
        dbc.Row(
            [
                dbc.Col(dbc.Button("Prev", id="prev-btn", className="btn btn-secondary", n_clicks=0), width="auto"),
                dbc.Col(html.Div(id="page-info", style={"text-align": "center"}), width="auto"),
                dbc.Col(dbc.Button("Next", id="next-btn", className="btn btn-secondary", n_clicks=0), width="auto"),
            ],
            justify="center",
            align="center",
            style={"margin-top": "20px"},
        ),
        html.Button("Submit", id="submit-btn", className="btn btn-primary", n_clicks=0),
        html.Div(id="submit-message", style={"margin-top": "20px", "color": "green"}),
    ],
    style={"padding-bottom": "60px", "padding-top": "20px"},
    fluid=True,
)


def _page_slice(data, page):
    total_pages = max(1, math.ceil(len(data) / PAGE_SIZE)) if data else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    return data[start:start + PAGE_SIZE], page, total_pages, start


def register_callbacks(app: Dash):
    @app.callback(
        Output("addcontext-domain-hint", "children"),
        Input("addcontext-domain", "value"),
    )
    def show_domain_hint(domain_value):
        profile = get_profile(domain_value) if domain_value else default_profile()
        return render_domain_hint(profile, include_target=True)

    @app.callback(
        [
            Output("file-content", "children"),
            Output("page-info", "children"),
            Output("submit-message", "children"),
            Output("addcontext-data", "data"),
            Output("addcontext-page", "data"),
        ],
        [
            Input("upload-data", "contents"),
            Input("prev-btn", "n_clicks"),
            Input("next-btn", "n_clicks"),
            Input("submit-btn", "n_clicks"),
        ],
        [
            State("upload-data", "filename"),
            State("addcontext-data", "data"),
            State("addcontext-page", "data"),
            State("addcontext-domain", "value"),
        ],
    )
    def handle_callbacks(contents, prev_clicks, next_clicks, submit_clicks,
                         filename, data_list, current_page, domain_value):
        ctx = callback_context
        if not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        data_list = data_list or []
        current_page = current_page or 1
        profile = get_profile(domain_value) if domain_value else default_profile()

        if triggered_id == "upload-data":
            if not contents:
                return "No file uploaded.", "", "", [], 1
            try:
                df = parse_uploaded_file(contents, filename)
                original_df = df
                df = apply_source_alias(df, profile)
                validate_columns(df, profile=profile)
                records = df.to_dict("records")
                records = [normalize_metadata(r) for r in records]
                warnings = validate_enum_values(records, profile=profile, strict_format=True)
                data_list = records
                page_data, current_page, total_pages, start = _page_slice(data_list, 1)
                cards = create_cards_from_page_data(page_data, start_index=start, profile=profile)
                warn_msg = ""
                if warnings:
                    warn_msg = html.Div(
                        ["Warnings:"] + [html.Div(w) for w in warnings[:10]],
                        style={"color": "#b37400"},
                    )
                return cards, f"Page {current_page} of {total_pages}", warn_msg, data_list, current_page
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
                return msg, "", "", [], 1
            except Exception as e:
                return f"Error processing file: {e}", "", "", [], 1

        if not data_list:
            return dash.no_update, dash.no_update, "No data available.", dash.no_update, dash.no_update

        if triggered_id in ("prev-btn", "next-btn"):
            total_pages = max(1, math.ceil(len(data_list) / PAGE_SIZE))
            if triggered_id == "prev-btn" and current_page > 1:
                current_page -= 1
            elif triggered_id == "next-btn" and current_page < total_pages:
                current_page += 1
            page_data, current_page, total_pages, start = _page_slice(data_list, current_page)
            cards = create_cards_from_page_data(page_data, start_index=start, profile=profile)
            return cards, f"Page {current_page} of {total_pages}", "", dash.no_update, current_page

        if triggered_id == "submit-btn":
            try:
                generator = get_generator(profile_name=profile.name)
                df = pd.DataFrame(data_list)
                source_col = profile.source_column
                target_col = profile.target_column
                requirements = df[source_col].astype(str).tolist()
                test_cases = df[target_col].astype(str).tolist()
                raw_meta = df[["mne", "tech", "Format"]].to_dict("records")
                mkeys = profile.metadata_keys
                metadata = [
                    {
                        mkeys["mne"]: rec.get("mne"),
                        mkeys["tech"]: rec.get("tech"),
                        mkeys["format"]: rec.get("Format"),
                        mkeys["priority"]: Config.USE_CASE_TG_DEFAULT_PRIORITY,
                    }
                    for rec in raw_meta
                ]

                statuses = generator.add_test_cases(
                    profile.use_case_type, requirements, test_cases, metadata=metadata
                )

                for i, status in enumerate(statuses):
                    data_list[i]["Status"] = status["status"]
                    data_list[i]["similarity_score"] = status.get("similarity_score")

                page_data, current_page, total_pages, start = _page_slice(data_list, current_page)
                cards = create_cards_from_page_data(page_data, start_index=start, profile=profile)

                added = sum(1 for s in statuses if s["status"] == "Added")
                dup = len(statuses) - added
                msg = f"Submission successful - {added} added, {dup} already exist."
                return cards, f"Page {current_page} of {total_pages}", msg, data_list, current_page
            except Exception as e:
                return dash.no_update, dash.no_update, f"An error occurred during submission: {e}", dash.no_update, dash.no_update

        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
