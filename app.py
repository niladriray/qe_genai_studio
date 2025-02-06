from dash import Dash, dcc, html, Input, Output, State, ctx
import toolbox  # Import the toolbox
from pages import addcontext, generatetestcase, browseprompt
import dash_bootstrap_components as dbc
import os

os.environ["OPENAI_API_KEY"] = "REDACTED_OPENAI_KEY"

# Initialize Dash
app = Dash(__name__, suppress_callback_exceptions=True, external_stylesheets=[dbc.themes.BOOTSTRAP])

def create_header():
    return html.Div(
        "Header"
    )

app.layout = html.Div([
    # Header
    html.Div(
        [
            html.H2(
                "Test Case Generator",
                style={
                    "margin": "0",
                    "position": "absolute",
                    "top": "50%",
                    "left": "50%",
                    "transform": "translate(-50%, -50%)",
                    "font-size": "24px",
                }
            ),
            html.H3(
                "PNC Retail QE - GenAI Proof of Technology",
                style={
                    "margin": "0",
                    "position": "absolute",
                    "bottom": "5px",
                    "right": "10px",
                    "font-size": "12px",
                    "color": "white",
                }
            ),
        ],
        style={
            "background-color": "black",
            "color": "white",
            "position": "relative",
            "height": "50px",  # Reduced height
            "width": "100%",
        }
    ),

    # Main Content with Toolbox and Page Content
    html.Div([
        # Toolbox
        html.Div(
            toolbox.get_toolbox(),
            style={
                "width": "60px",  # Fixed width for the toolbox
                "background-color": "#f0f0f0",
                "overflow-y": "auto",
                "flex-shrink": "0",  # Prevent shrinking
                "height": "calc(100vh - 100px)",  # Adjust for top bar and footer
            }
        ),

        # Main Content
        html.Div(
            [
                dcc.Location(id="url", refresh=False),
                html.Div(id="page-content", style={"padding": "10px", "height": "100%"})
            ],
            style={
                "flex-grow": "1",  # Take up the remaining space
                "overflow-y": "auto",
                "padding": "10px",
                "background-color": "#ffffff"
            }
        )
    ], style={
        "display": "flex",
        "flex-direction": "row",
        "height": "calc(100vh - 100px)",  # Adjust for top bar and footer
        "background-color": "#e5e7e6",
    }),

    # Footer
    html.Div(
        "GPT & HuggingFace Embeddings IN ACTION",
        style={
            "background-color": "black",
            "color": "white",
            "text-align": "center",
            "height": "50px",
            "line-height": "50px",
            "font-size": "14px",
            "position": "absolute",
            "bottom": "0",
            "width": "100%",
        }
    )
], style={
    "height": "100vh",
    "width": "100vw",
    "margin": "0",
    "padding": "0",
    "position": "relative",
})


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
    else:
        return html.H1("Welcome to the Dashboard!", style={"text-align": "center"})

# Register callbacks for candlestick.py
addcontext.register_callbacks(app)
generatetestcase.register_callbacks(app)
browseprompt.register_callbacks(app)


if __name__ == "__main__":
    app.run_server(debug=True)