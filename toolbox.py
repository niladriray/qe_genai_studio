from dash import html, dcc, Input, Output, callback


def get_toolbox():
    return html.Div([
        # Toolbox Header
        html.H2("Menu", style={
            "text-align": "center",
            "font-size": "14px",
            "margin": "0",
            "padding": "10px 0",
            "width": "100%",
            "overflow": "hidden",
            "white-space": "nowrap",
        }),

        # Toolbox Links (Wrapped in Containers)
        html.Div([
            html.Div(
                dcc.Link(
                    html.Img(
                        id="addcontext-icon",
                        src="/assets/addcontext.png",
                        style={
                            "width": "40px",
                            "height": "40px",
                            "margin": "10px auto",
                            "display": "block",
                            "cursor": "pointer"
                        }
                    ),
                    href="/addcontext",
                ),
                id="addcontext-container",
                style={
                    "padding": "10px",
                    "text-align": "center",
                    "background-color": "#DADBDA",
                    "border-radius": "10px",
                    "margin": "5px",
                    "cursor": "pointer",
                }
            ),
            html.Div(
                dcc.Link(
                    html.Img(
                        id="generatetestcase-icon",
                        src="/assets/generatetestcase.png",
                        style={
                            "width": "40px",
                            "height": "40px",
                            "margin": "10px auto",
                            "display": "block",
                            "cursor": "pointer"
                        }
                    ),
                    href="/generatetestcase",
                ),
                id="generatetestcase-container",
                style={
                    "padding": "10px",
                    "text-align": "center",
                    "background-color": "#DADBDA",
                    "border-radius": "10px",
                    "margin": "5px",
                    "cursor": "pointer",
                }
            ),
        ], style={
            "display": "flex",
            "flex-direction": "column",
            "align-items": "center",
            "padding": "0",
            "margin": "0",
            "width": "100%",
            "overflow": "hidden"
        })
    ], style={
        "width": "100%",
        "max-width": "80px",  # Strictly limit the toolbox width
        "height": "100vh",
        "background-color": "#DADBDA",
        "overflow-y": "auto",
        "padding": "0",
        "box-sizing": "border-box",
    })


### Callback to Highlight Selected Container


@callback(
    [
        Output("addcontext-container", "style"),
        Output("generatetestcase-container", "style"),
    ],
    [Input("url", "pathname")]
)
def update_toolbox_highlight(pathname):
    """
    Highlight the selected toolbox container based on the current page.
    """
    default_style = {
        "display": "flex",  # Use flexbox for vertical alignment
        "align-items": "center",  # Vertically center content
        "justify-content": "center",  # Horizontally center content
        "padding": "10px",
        "background-color": "#DADBDA",
        "margin": "5px",
        "cursor": "pointer",
        "height": "60px",  # Make it smaller like a square
        "width": "60px",   # Ensure square dimensions
    }
    selected_style = {
        "display": "flex",  # Use flexbox for vertical alignment
        "align-items": "center",  # Vertically center content
        "justify-content": "center",  # Horizontally center content
        "padding": "10px",
        "background-color": "white",  # Highlighted background
        "margin": "5px",
        "cursor": "pointer",
        "height": "60px",  # Match square size
        "width": "60px",   # Match square size
        "box-shadow": "0px 4px 8px rgba(0, 0, 0, 0.2)",  # Optional shadow
    }

    return [
        selected_style if pathname == "/addcontext" else default_style,
        selected_style if pathname == "/generatetestcase" else default_style,
    ]