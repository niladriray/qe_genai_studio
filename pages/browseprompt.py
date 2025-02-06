from dash import Dash, dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import pandas as pd
import math
from configs.config import Config
from langchain_chroma import Chroma
from connectors.vector_db_connector import VectorDBConnector  # Import your VectorDBConnector class

# Page size for pagination
PAGE_SIZE = 10

# Global variables for data
data_list = []
current_page = 1
total_pages = 0

# Initialize VectorDBConnector
vector_db_connector = VectorDBConnector(db_path="./data/", use_gpt_embeddings=False)
vector_db_connector.connect()

# Layout for the data grid page
layout = dbc.Container(
    [
        html.H2("ChromaDB Data Viewer"),
        html.Div(
            [
                dbc.Row(
                    [
                        dbc.Col(dbc.Input(id="filter-key", placeholder="Filter Key", type="text"), width=4),
                        dbc.Col(dbc.Input(id="filter-value", placeholder="Filter Value", type="text"), width=4),
                        dbc.Col(
                            dbc.Button("Apply Filter", id="apply-filter-btn", className="btn btn-primary", n_clicks=0),
                            width=2,
                        ),
                    ],
                    style={"margin-bottom": "20px"},
                ),
            ]
        ),
        dag.AgGrid(
            id="data-grid",
            columnDefs=[],  # Will be populated dynamically
            rowData=[],  # Will be populated dynamically
            defaultColDef={"filter": True, "sortable": True, "resizable": True},  # Enable filtering and sorting
            dashGridOptions={"pagination": True, "paginationPageSize": PAGE_SIZE},  # Enable pagination
            style={"height": "500px", "width": "100%"},
        ),
    ],
    fluid=True,
)


# Callbacks to handle data grid
def register_callbacks(app: Dash):
    @app.callback(
        [
            Output("data-grid", "columnDefs"),
            Output("data-grid", "rowData"),
        ],
        [
            Input("apply-filter-btn", "n_clicks"),
        ],
        [
            State("filter-key", "value"),
            State("filter-value", "value"),
        ],
        prevent_initial_call=True,
    )
    def handle_callbacks(apply_filter_clicks, filter_key, filter_value):
        # Fetch all data from the vector database
        all_data = vector_db_connector.execute("query", query="*", k=1000)  # Fetch all data (adjust `k` as needed)

        # Apply filters if provided
        if filter_key and filter_value:
            filtered_data = [
                {**doc.metadata, "Requirement": doc.page_content}  # Combine metadata with document content
                for doc in all_data
                if doc.metadata.get(filter_key) == filter_value
            ]
        else:
            filtered_data = [
                {**doc.metadata, "Requirement": doc.page_content}
                for doc in all_data
            ]

        # Convert data to a format suitable for AgGrid
        if filtered_data:
            # Dynamically generate column definitions based on keys in the first row
            column_defs = [{"field": col, "headerName": col, "sortable": True, "filter": True} for col in
                           filtered_data[0].keys()]
            row_data = filtered_data
        else:
            column_defs = []
            row_data = []

        return column_defs, row_data