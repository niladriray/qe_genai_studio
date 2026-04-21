"""Renders a domain profile's expected upload shape as Dash components.

Replaces a dense one-line string ("Format ∈ [...] · Tech ∈ [...]") with
labelled rows of colour-coded pill badges so the required columns and the
allowed enum values read at a glance.
"""

import dash_bootstrap_components as dbc
from dash import html


def _badge_row(label, values, color):
    return html.Div(
        [
            html.Span(
                f"{label}:",
                style={
                    "fontWeight": "600",
                    "color": "#333",
                    "marginRight": "8px",
                    "minWidth": "80px",
                    "display": "inline-block",
                },
            ),
            html.Span(
                [
                    dbc.Badge(
                        v,
                        color=color,
                        pill=True,
                        className="me-1 mb-1",
                        style={"fontWeight": "500"},
                    )
                    for v in values
                ]
            ),
        ],
        style={"marginBottom": "6px"},
    )


def render_domain_hint(profile, *, include_target=True):
    """Return a Dash element describing the profile's upload contract."""
    required_cols = [profile.source_column]
    if include_target:
        required_cols.append(profile.target_column)
    required_cols.extend(["Format", "tech", "mne"])

    rows = [
        _badge_row("Columns", required_cols, "primary"),
        _badge_row("Format", list(profile.format_enum), "info"),
        _badge_row("Tech", list(profile.technology_enum), "secondary"),
    ]
    aliases = list(getattr(profile, "source_aliases", ()) or ())
    if not include_target and aliases:
        rows.append(_badge_row("Accepts from", aliases, "success"))

    return html.Div(
        rows,
        style={
            "backgroundColor": "#f8f9fa",
            "border": "1px solid #e3e6ea",
            "borderRadius": "6px",
            "padding": "10px 12px",
            "marginBottom": "10px",
            "fontSize": "0.9rem",
        },
    )
