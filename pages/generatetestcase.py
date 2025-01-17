from dash import html, dcc, Input, Output, State, callback_context, Dash, MATCH
import dash_bootstrap_components as dbc
import pandas as pd
import io, base64, math, dash
from models.test_case_generator import TestCaseGenerator
from models.feedback_loop import FeedbackLoop
from utilities.customlogger import logger
from utilities.text_formatter import format_testcase, format_bdd_scenarios

PAGE_SIZE = 10

layout = dbc.Container(
    [
        html.H2("Generate Test Cases"),
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
        html.Div(id="uploaded-file-content", style={"margin-top": "20px"}),  # Unique ID for content
        dbc.Row(
            [
                dbc.Col(dbc.Button("Prev", id="prev-btn", className="btn btn-secondary", n_clicks=0), width="auto"),
                dbc.Col(html.Div(id="pagination-info", style={"text-align": "center"}), width="auto"),  # Unique ID
                dbc.Col(dbc.Button("Next", id="next-btn", className="btn btn-secondary", n_clicks=0), width="auto"),
            ],
            justify="center",
            align="center",
            style={"margin-top": "20px"},
        ),
        html.Button("Generate", id="generate-btn", className="btn btn-primary", n_clicks=0),
        html.Div(id="generation-message", style={"margin-top": "20px", "color": "green"}),  # Unique ID
        html.Div(id="submit-download-section", style={"margin-top": "20px"}),
    ],
    fluid=True,
)


def parse_uploaded_file(contents, filename):
    try:
        content_type, content_string = contents.split(",")
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


def create_cards_with_feedback(page_data):
    """
    Create cards with feedback and editing functionality.
    """
    cards = []
    for idx, record in enumerate(page_data):
        requirement = record.get("Requirement", "")
        format_type = record.get("Format", "")
        status = record.get("Status", "Pending")
        status_color = "success" if status == "Generated" else "warning"
        generated_test_case = record.get("Generated Test Case", "No test case generated yet.")
        prompt = record.get("Prompt", "No prompt used.")
        if format_type == "plain_text":
            prompt = format_testcase(prompt)
        elif format_type == "bdd":
            prompt = format_testcase(prompt)

        record_id = record.get("id", idx + 1)  # Generate or use a unique identifier for each record

        # Conditional visibility for Edit and feedback buttons
        feedback_and_edit_visibility = {"display": "block"} if status == "Generated" else {"display": "none"}

        card = dbc.Card(
            [
                dbc.CardHeader(
                    dbc.Row(
                        [
                            dbc.Col(html.Span(f"# {idx + 1}", style={"font-weight": "bold"}), width="auto"),
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
                        html.H5(requirement, className="card-title"),
                        html.P(f"Format: {format_type}", className="card-subtitle"),
                        html.H6("Prompt Used:", className="card-title"),
                        dcc.Markdown(prompt, className="card-text", style={"backgroundColor": "#f8f9fa", "padding": "10px", "borderRadius": "5px"}),
                        html.H6("Generated Test Case:", className="card-title"),
                        dcc.Markdown(generated_test_case, id={"type": "generated-test-case", "index": idx}, className="card-text", style={"backgroundColor": "#f8f9fa", "padding": "10px", "borderRadius": "5px"}),
                        html.Div(
                            [
                                dbc.Button("Edit", id={"type": "edit-btn", "index": idx}, color="info", size="sm", style={"margin-top": "10px"}),
                                dbc.Textarea(
                                    id={"type": "edit-textarea", "index": idx},
                                    value=generated_test_case,
                                    style={"display": "none", "margin-top": "10px", "height": "6rem"},
                                ),
                                dbc.Row(
                                    [
                                        dbc.Col(
                                            dbc.Button("👍", id={"type": "thumbs-up", "index": idx}, color="success", size="sm"),
                                            width="auto",
                                        ),
                                        dbc.Col(
                                            dbc.Button("👎", id={"type": "thumbs-down", "index": idx}, color="danger", size="sm"),
                                            width="auto",
                                        ),
                                    ],
                                    justify="start",
                                    style={"margin-top": "10px"},
                                ),
                            ],
                            style=feedback_and_edit_visibility,
                        ),
                    ]
                ),
            ],
            style={"margin-bottom": "15px"},
        )
        cards.append(card)
    return cards



def register_callbacks(app: Dash):
    @app.callback(
        Output({"type": "edit-textarea", "index": MATCH}, "style"),
        [Input({"type": "edit-btn", "index": MATCH}, "n_clicks")],
        prevent_initial_call=True,
    )
    def toggle_edit_textarea(n_clicks):
        """
        Toggle the visibility of the textarea when the Edit button is clicked.
        """
        if n_clicks and n_clicks > 0:
            return {"display": "block", "margin-top": "10px"}
        return {"display": "none"}

    @app.callback(
        [
            Output("uploaded-file-content", "children"),
            Output("pagination-info", "children"),
            Output("generation-message", "children"),
        ],
        [
            Input("upload-data", "contents"),
            Input("prev-btn", "n_clicks"),
            Input("next-btn", "n_clicks"),
            Input("generate-btn", "n_clicks"),
        ],
        [State("upload-data", "filename")],
    )
    def handle_callbacks(contents, prev_clicks, next_clicks, generate_clicks, filename):
        global data_list, current_page, total_pages

        ctx = callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if triggered_id == "upload-data":
            if not contents:
                return "No file uploaded.", "", ""
            try:
                df = parse_uploaded_file(contents, filename)
                data_list = df.to_dict("records")
                for record in data_list:
                    record["Status"] = "Pending"  # Default status
                total_pages = math.ceil(len(data_list) / PAGE_SIZE)
                current_page = 1
                page_data = data_list[:PAGE_SIZE]
                cards = create_cards_with_feedback(page_data)
                return cards, f"Page {current_page} of {total_pages}", ""
            except Exception as e:
                return f"Error processing file: {str(e)}", "", ""

        elif triggered_id in ["prev-btn", "next-btn"]:
            if not data_list:
                return dash.no_update, dash.no_update, "No data available for pagination."

            if triggered_id == "prev-btn" and current_page > 1:
                current_page -= 1
            elif triggered_id == "next-btn" and current_page < total_pages:
                current_page += 1

            start_idx = (current_page - 1) * PAGE_SIZE
            end_idx = start_idx + PAGE_SIZE
            page_data = data_list[start_idx:end_idx]
            cards = create_cards_with_feedback(page_data)

            return cards, f"Page {current_page} of {total_pages}", ""

        elif triggered_id == "generate-btn":
            if not data_list:
                return dash.no_update, dash.no_update, "No data to generate test cases."

            try:
                generator = TestCaseGenerator(vector_db_path="./data/", use_gpt_embeddings=False)

                for record in data_list:
                    req = record["Requirement"]
                    fmt = record["Format"]

                    # Generate test case with prompt
                    prompt, generated_test_case = generator.generate_test_case(req, format=fmt, return_with_prompt=True, k=2)
                    record["Generated Test Case"] = generated_test_case
                    record["Prompt"] = prompt
                    record["Status"] = "Generated"

                start_idx = (current_page - 1) * PAGE_SIZE
                end_idx = start_idx + PAGE_SIZE
                page_data = data_list[start_idx:end_idx]
                cards = create_cards_with_feedback(page_data)

                return cards, f"Page {current_page} of {total_pages}", "Test cases generated successfully!"
            except Exception as e:
                return dash.no_update, dash.no_update, f"An error occurred during generation: {str(e)}"

        return dash.no_update, dash.no_update, ""

    # Add callback for thumbs up/down feedback (if needed)
    @app.callback(
        Output({"type": "feedback-message", "index": MATCH}, "children"),
        [
            Input({"type": "thumbs-up", "index": MATCH}, "n_clicks"),
            Input({"type": "thumbs-down", "index": MATCH}, "n_clicks"),
        ],
        [State({"type": "generated-test-case", "index": MATCH}, "children")],
        prevent_initial_call=True,
    )
    def handle_feedback(thumbs_up_clicks, thumbs_down_clicks, generated_text):
        """
        Handle feedback from thumbs up/down buttons for each card.
        """
        ctx = callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if triggered_id == "thumbs-up":
            return "👍 Thank you for the positive feedback!"
        elif triggered_id == "thumbs-down":
            return "👎 Thank you for the feedback! We'll work on improvements."

        return ""