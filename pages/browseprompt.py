from dash import Dash, dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import pandas as pd
import math
from configs.config import Config
from langchain_chroma import Chroma
from connectors.vector_db_connector import VectorDBConnector  # Import your VectorDBConnector class
import domains  # noqa: F401  (triggers profile registration)
from domains.registry import all_profiles, default_profile

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
_DOMAIN_ANY = "__any__"


def _domain_filter_options():
    opts = [{"label": "All domains", "value": _DOMAIN_ANY}]
    opts += [{"label": f"{p.source_label} → {p.target_label}", "value": p.name} for p in all_profiles()]
    return opts


layout = dbc.Container(
    [
        html.H2("ChromaDB Data Viewer"),
        html.Div(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            dbc.Select(
                                id="browse-domain",
                                options=_domain_filter_options(),
                                value=default_profile().name,
                            ),
                            width=3,
                        ),
                        dbc.Col(dbc.Input(id="filter-key", placeholder="Filter Key", type="text"), width=3),
                        dbc.Col(dbc.Input(id="filter-value", placeholder="Filter Value", type="text"), width=3),
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
            State("browse-domain", "value"),
        ],
        prevent_initial_call=True,
    )
    def handle_callbacks(apply_filter_clicks, filter_key, filter_value, domain_value):
        # Fetch all data from the vector database (true list, not an embed-"*" search).
        all_data = vector_db_connector.execute("list_all")

        # Scope by domain. Legacy records without "domain" default to the
        # system default (test_case) for backwards compatibility.
        def matches_domain(doc):
            if not domain_value or domain_value == _DOMAIN_ANY:
                return True
            return doc.metadata.get("domain", Config.DEFAULT_DOMAIN) == domain_value

        rows = [
            {**doc.metadata, "Requirement": doc.page_content}
            for doc in all_data
            if matches_domain(doc)
        ]

        if filter_key and filter_value:
            filtered_data = [r for r in rows if str(r.get(filter_key)) == str(filter_value)]
        else:
            filtered_data = rows

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