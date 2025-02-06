from dash import html, dcc, Input, Output, State, callback_context, Dash
import dash_bootstrap_components as dbc
import pandas as pd
import io, dash, math
import base64
from models.test_case_generator import TestCaseGenerator
from configs.config import Config


def create_cards_from_page_data(page_data):
    cards = []
    for idx, record in enumerate(page_data):
        status = record.get("Status", "Pending")
        status_color = "success" if status == "Added" else "danger" if "Already Exist" in status else "warning"
        print(page_data[idx])
        if status == "Already Exist":
            status = "Already Exist SC:" + record.get("similarity_score")
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
                    style={"background-color": "#f8f9fa"},
                ),
                dbc.CardBody(
                    [
                        html.H5("Details", className="card-title"),
                        html.P(
                            [
                                "MNE: ", html.Strong(record.get("mne", "N/A")),
                                ", Tech: ", html.Strong(record.get("tech", "N/A")),
                                ", Format: ", html.Strong(record.get("Format", "plain_text")),
                            ],
                            className="card-text",
                        ),
                        html.H5("Requirement", className="card-title"),
                        html.P(record.get("Requirement", "No requirement provided."), className="card-text"),
                        html.H5("Test Case", className="card-title"),
                        dcc.Markdown(record.get("Test Case", "No test case available."), className="card-text"),
                    ]
                )
            ],
            style={"margin-bottom": "15px"},
        )
        cards.append(card)
    return cards



def parse_uploaded_file(contents, filename):
    """
    Parse the uploaded file content and return a pandas DataFrame.
    :param contents: The content of the uploaded file as a base64 string.
    :param filename: The name of the uploaded file.
    :return: A pandas DataFrame with the parsed data.
    """
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



layout = dbc.Container(
    [
        html.H2("Add Requirements & Test Cases"),
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
    style={
        "padding-bottom": "60px",  # Add bottom padding to create space above the footer
        "padding-top": "20px",  # Optional: Ensure spacing at the top
    },
    fluid=True,
)

PAGE_SIZE = 10  # Number of items per page


def register_callbacks(app: Dash):
    @app.callback(
        [
            Output("file-content", "children"),
            Output("page-info", "children"),
            Output("submit-message", "children"),
        ],
        [
            Input("upload-data", "contents"),
            Input("prev-btn", "n_clicks"),
            Input("next-btn", "n_clicks"),
            Input("submit-btn", "n_clicks"),
        ],
        [
            State("upload-data", "filename"),
        ],
    )
    def handle_callbacks(contents, prev_clicks, next_clicks, submit_clicks, filename):
        global data_list, current_page, total_pages

        ctx = dash.callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if triggered_id == "upload-data":
            if not contents:
                return "No file uploaded.", "", ""
            try:
                df = parse_uploaded_file(contents, filename)
                data_list = df.to_dict("records")
                total_pages = math.ceil(len(data_list) / PAGE_SIZE)
                current_page = 1
                page_data = data_list[:PAGE_SIZE]
                cards = create_cards_from_page_data(page_data)
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
            cards = create_cards_from_page_data(page_data)

            return cards, f"Page {current_page} of {total_pages}", ""

        elif triggered_id == "submit-btn":
            if not data_list:
                return dash.no_update, dash.no_update, "No data to submit. Please upload a file first."

            try:
                generator = TestCaseGenerator(
                    vector_db_path="./data/",
                    chunk_size=300,
                    chunk_overlap=50,
                    use_gpt_embeddings=False,
                )

                # Convert the data to a DataFrame for processing
                df = pd.DataFrame(data_list)

                # Extract requirements, test cases, and metadata
                requirements = df["Requirement"].tolist()
                test_cases = df["Test Case"].tolist()
                metadata = df[["mne", "tech", "Format"]].to_dict("records")
                metadata = [{**record, Config.USE_CASE_TG_METADATA_PRIORITY: Config.USE_CASE_TG_DEFAULT_PRIORITY} for record in metadata]

                # Call add_test_cases once with all data
                statuses = generator.add_test_cases("tg", requirements, test_cases, metadata=metadata)

                # Update the DataFrame with the statuses
                for i, status in enumerate(statuses):
                    data_list[i]["Status"] = status["status"]

                # Refresh the current page
                start_idx = (current_page - 1) * PAGE_SIZE
                end_idx = start_idx + PAGE_SIZE
                page_data = data_list[start_idx:end_idx]
                cards = create_cards_from_page_data(page_data)

                added_count = sum(1 for status in statuses if status["status"] == "Added")
                already_exist_count = len(statuses) - added_count

                submission_message = f"Submission successful - {added_count} added, {already_exist_count} already exist."

                return cards, f"Page {current_page} of {total_pages}", submission_message
            except Exception as e:
                return dash.no_update, dash.no_update, f"An error occurred during submission: {str(e)}"

        return dash.no_update, dash.no_update, ""