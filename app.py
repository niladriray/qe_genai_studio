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
            # Home Icon (Click to Navigate to Home Page)
            html.A(
                html.Img(
                    src="/assets/home-icon.png",  # Make sure to place a home icon in the assets folder
                    style={
                        "height": "30px",  # Adjust size
                        "width": "30px",
                        "margin-left": "15px",
                        "margin-top": "10px",
                        "cursor": "pointer",
                    }
                ),
                href="/home"  # Static URL for home navigation
            ),

            # Title (Centered)
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

            # Subtitle (Bottom Right)
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
            "height": "50px",  # Adjusted height
            "width": "100%",
            "display": "flex",
            "align-items": "center",
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
        "GPT & HuggingFace Embeddings in action",
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
        return dbc.Container(
    [
        html.H1("Welcome to Generative AI-Powered Test Case Generation", style={"text-align": "center", "margin-bottom": "20px"}),

        html.P(
            [
                "In today's fast-paced software development landscape, ensuring comprehensive test coverage is essential. ",
                html.Strong("Our RAG (Retrieval-Augmented Generation) based GenAI Platform"),
                " revolutionizes test case generation by leveraging context-aware AI to transform raw requirements into structured, executable test cases "
                "in multiple formats, including ", html.Strong("Plain Text, BDD, and more."),
            ],
            style={"text-align": "center", "font-size": "18px"},
        ),

        html.H2("🔹 Key Features", style={"margin-top": "30px"}),

        html.Ul([
            html.Li([html.Strong("Automated Test Case Generation – "), "Upload requirements and let AI generate test cases."]),
            html.Li([html.Strong("Support for Multiple Formats – "), "Generate test cases in ", html.Strong("Plain Text, BDD (Gherkin), and more.")]),
            html.Li([html.Strong("Retrieval-Augmented Generation (RAG) for Context Awareness – "), "Uses ChromaDB for smart retrieval."]),
            html.Li([html.Strong("User-Friendly Dashboard – "), "Edit, review, and manage generated test cases."]),
            html.Li([html.Strong("Adaptive AI Learning – "), "AI improves based on user feedback."]),
            html.Li([html.Strong("Real-Time API & Batch Processing – "), "Generate test cases on-demand via API calls."]),
        ], style={"font-size": "16px"}),

        html.H2("🚀 Future Possibilities", style={"margin-top": "30px"}),

        html.Ul([
            html.Li([html.Strong("Defect Analytics and Insights – "), "Analyze Defects and Production Incident contents and generate insights."]),
            html.Li([html.Strong("Agentic Development – "), "Development of Agents automating repetitive manual tasks"]),
            html.Li([html.Strong("Mult-Modal integration – "), "Image, Video, Audio data analysis to automate human dependent tests like A11y."]),
        ], style={"font-size": "16px"}),

        html.Div(style={"margin-top": "40px", "text-align": "center"}, children=[
            html.H4(html.Strong("Get Started Today!")),
            html.P("Experience the future of AI-powered test case generation."),
            dbc.Button("Try It Now", color="primary", href="/generatetestcase"),
        ]),
    ],
    fluid=True,
    style={"max-width": "900px", "margin": "auto", "padding": "20px"},
)

# Register callbacks for candlestick.py
addcontext.register_callbacks(app)
generatetestcase.register_callbacks(app)
browseprompt.register_callbacks(app)


if __name__ == "__main__":
    app.run_server(debug=True)