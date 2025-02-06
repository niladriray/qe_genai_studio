from dash import html, dcc, Input, Output, State, callback_context, Dash, MATCH
import dash_bootstrap_components as dbc
import pandas as pd
import io, base64, math, dash

from configs.config import Config
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
        html.Button(
            "Download Test Cases",
            id="download-btn",
            className="btn btn-success",
            style={"margin-top": "10px", "padding": "5px 10px", "border-radius": "5px", "box-shadow": "none"},
        ),
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
    Create cards with feedback and editing functionality, ensuring consistent fonts and plain-text display for the prompt.
    """
    cards = []
    for idx, record in enumerate(page_data):

        # Convert dictionary keys to lowercase
        record_lower = {k.lower(): v for k, v in record.items()}

        requirement = record_lower.get("requirement", "No requirement provided.")
        format_type = record_lower.get("format", "N/A")
        mne = record_lower.get("mne", "N/A")
        tech = record_lower.get("tech", "N/A")
        status = record_lower.get("status", "Pending")
        status_color = "success" if status == "Generated" else "warning"
        generated_test_case = record_lower.get("generated test case", "No test case generated yet.")
        prompt = record_lower.get("prompt", "No prompt used.")  # Ensure the prompt is plain text

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
                        # Display MNE, Tech, and Format
                        html.H5("Details", className="card-title"),
                        html.P(
                            [
                                "MNE: ", html.Strong(f"{mne}"),
                                ", Tech: ", html.Strong(f"{tech}"),
                                ", Format: ", html.Strong(f"{format_type}"),
                            ],
                            className="card-text",
                        ),
                        html.Div(
                            [
                                html.Span(f"{mne}", id={"type": "mne", "index": idx}, style={"display": "none"}),
                                html.Span(f"{tech}", id={"type": "tech", "index": idx},
                                          style={"display": "none"}),
                                html.Span(f"{format_type}", id={"type": "format", "index": idx},
                                          style={"display": "none"}),
                            ]
                        ),
                        # Display Requirement
                        html.H5("Requirement", className="card-title"),
                        html.P(requirement, className="card-text", id={"type": "requirement", "index": idx}),

                        #Display Prompt
                        html.H5("Prompt Used:", className="card-title"),
                        dcc.Markdown(prompt, className="card-text",
                                     style={"backgroundColor": "#f8f9fa", "padding": "10px", "borderRadius": "5px"}),

                        # Display Generated Test Case
                        html.H5("Generated Test Case:", className="card-title"),
                        html.P(generated_test_case, className="card-text",
                               id={"type": "generated-test-case", "index": idx}),
                        # Feedback and Edit Buttons
                        html.Div(
                            [
                                dbc.Button("Edit", id={"type": "edit-btn", "index": idx}, color="info", size="sm",
                                           style={"margin-top": "10px"}),
                                dbc.Textarea(
                                    id={"type": "edit-textarea", "index": idx},
                                    value=generated_test_case,
                                    rows=10,
                                    style={"display": "none", "margin-top": "10px", "height": "6rem"},
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
            Output("download-btn", "children"),  # Update this to return the download link
            Output("download-btn", "style"),  # Show or hide the download button
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
                return "No file uploaded.", "", "", None, {"display": "none"}
            try:
                df = parse_uploaded_file(contents, filename)
                data_list = df.to_dict("records")
                for record in data_list:
                    record["Status"] = "Pending"  # Default status
                    record["Generated Test Case"] = "No test case generated yet."  # Add a placeholder for test cases
                total_pages = math.ceil(len(data_list) / PAGE_SIZE)
                current_page = 1
                page_data = data_list[:PAGE_SIZE]
                cards = create_cards_with_feedback(page_data)
                return cards, f"Page {current_page} of {total_pages}", "", None, {"display": "none"}
            except Exception as e:
                return f"Error processing file: {str(e)}", "", "", None, {"display": "none"}

        elif triggered_id in ["prev-btn", "next-btn"]:
            if not data_list:
                return dash.no_update, dash.no_update, "No data available for pagination.", None, {"display": "none"}

            if triggered_id == "prev-btn" and current_page > 1:
                current_page -= 1
            elif triggered_id == "next-btn" and current_page < total_pages:
                current_page += 1

            start_idx = (current_page - 1) * PAGE_SIZE
            end_idx = start_idx + PAGE_SIZE
            page_data = data_list[start_idx:end_idx]
            cards = create_cards_with_feedback(page_data)

            return cards, f"Page {current_page} of {total_pages}", "", None, {"display": "none"}

        elif triggered_id == "generate-btn":
            if not data_list:
                return dash.no_update, dash.no_update, "No data to generate test cases.", None, {"display": "none"}

            try:
                generator = TestCaseGenerator(vector_db_path="./data/", use_gpt_embeddings=False)

                for record in data_list:
                    req = record["Requirement"]
                    fmt = record["Format"]
                    mne = record.get("MNE", "N/A")
                    tech = record.get("Tech", "N/A")

                    # Prepare metadata
                    metadata = {
                        Config.USE_CASE_TG_METADATA_MNE: mne,
                        Config.USE_CASE_TG_METADATA_TECH: tech,
                        Config.USE_CASE_TG_METADATA_FMT: fmt,
                    }

                    # Generate test case and update the record
                    prompt, generated_test_case = generator.generate_test_case(
                        req, metadata=metadata, return_with_prompt=True, k=2
                    )
                    record["Generated Test Case"] = generated_test_case
                    record["Prompt"] = prompt
                    record["Status"] = "Generated"

                start_idx = (current_page - 1) * PAGE_SIZE
                end_idx = start_idx + PAGE_SIZE
                page_data = data_list[start_idx:end_idx]
                cards = create_cards_with_feedback(page_data)

                # Update the download button
                download_link = dbc.Button(
                    "Download Test Cases",
                    id="download-btn",
                    href=generate_excel_download_link(data_list),
                    download="Generated_Test_Cases.xlsx",
                    color="success"
                )

                return (
                    cards,
                    f"Page {current_page} of {total_pages}",
                    "Test cases generated successfully!",
                    download_link,
                    {"display": "block"},  # Show the download button
                )
            except Exception as e:
                return dash.no_update, dash.no_update, f"An error occurred during generation: {str(e)}", None, {
                    "display": "none"}

        # Default case: ensure all five outputs are returned
        return dash.no_update, dash.no_update, dash.no_update, None, {"display": "none"}

    @app.callback(
        Output({"type": "feedback-message", "index": MATCH}, "children"),
        [
            Input({"type": "thumbs-up", "index": MATCH}, "n_clicks"),
            Input({"type": "thumbs-down", "index": MATCH}, "n_clicks"),
        ],
        [
            State({"type": "generated-test-case", "index": MATCH}, "children"),
            State({"type": "requirement", "index": MATCH}, "children"),
            State({"type": "mne", "index": MATCH}, "children"),  # Add MNE
            State({"type": "tech", "index": MATCH}, "children"),  # Add Tech
            State({"type": "format", "index": MATCH}, "children"),  # Add Format
        ],
        prevent_initial_call=True,
    )
    def handle_feedback(thumbs_up_clicks, thumbs_down_clicks, generated_text, requirement, mne, tech, format_type):
        """
        Handle feedback from thumbs up/down buttons for each card.
        """

        ctx = callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        is_thumbs_up = "thumbs-up" in triggered_id

        try:
            # Fetch metadata and adjust priority
            current_priority = 0  # Replace with logic to fetch existing priority if available
            new_priority = Config.USE_CASE_TG_THUMBS_UP_PRIORITY if is_thumbs_up else Config.USE_CASE_TG_THUMBS_DOWN_PRIORITY

            # Prepare metadata
            metadata = {
                Config.USE_CASE_TG_METADATA_MNE: mne,
                Config.USE_CASE_TG_METADATA_TECH: tech,
                Config.USE_CASE_TG_METADATA_FMT: format_type,
                Config.USE_CASE_TG_METADATA_PRIORITY: new_priority,
            }

            # Update the metadata in the vector database
            generator = TestCaseGenerator(vector_db_path="./data/", use_gpt_embeddings=False)
            generator.update_test_cases(
                requirements=[requirement],
                test_cases=[generated_text],
                metadata=[metadata]
            )

            return "👍 Feedback recorded!" if is_thumbs_up else "👎 Feedback recorded!"
        except Exception as e:
            logger.error("Error recording feedback: %s", str(e))
            return f"An error occurred while recording feedback: {str(e)}"

def generate_excel_download_link(data):
    """
    Generate a downloadable link for the Excel file containing test cases.
    :param data: The data list with generated test cases.
    :return: A Base64 encoded download link.
    """
    df = pd.DataFrame(data)

    # Create an Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="TestCases")

    output.seek(0)
    encoded = base64.b64encode(output.read()).decode()
    return f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{encoded}"