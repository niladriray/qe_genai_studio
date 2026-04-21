"""
Manage Domains page — create and update user-defined DomainProfile entries
at runtime without redeploying code.

Editability rules (enforced by the UI and by server-side validation):

  • Built-in profiles (test_case, epic_to_user_story, manual_to_automation)
    live in version control. They are shown read-only; no Save.

  • For a *custom* profile that already has KB records:
      - Locked (would orphan or break existing records):
          name, use_case_type, source_column, target_column,
          metadata_keys.* (the raw stored keys)
      - Allowed but warned:
          removing entries from format_enum / technology_enum
      - Free edit:
          labels, system_role, few_shot_template, bare_template,
          example_metadata_fields, dedup_similarity_threshold,
          dedup_match_fields

  • For a custom profile with zero records: every field is free-edit.

The user can always create a *new* profile rather than mutating an existing
one — that's the sanctioned escape hatch when locked fields need to change.
"""

import json
from types import SimpleNamespace

import dash
import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, State, callback_context, dcc, html

import domains  # noqa: F401  (triggers profile registration)
from domains import custom_store
from domains.inventory import domain_record_count
from domains.profile import DomainProfile
from domains.registry import all_profiles, get as get_profile
from utilities.domain_templates import build_template_xlsx, template_filename

_NEW_VALUE = "__new__"

_METADATA_KEYS = ("format", "mne", "tech", "priority", "completion")
_DEFAULT_METADATA = {"format": "fmt", "mne": "mne", "tech": "tech", "priority": "priority", "completion": "comp"}

_BLANK = {
    "name": "",
    "source_label": "",
    "target_label": "",
    "source_column": "",
    "target_column": "",
    "use_case_type": "",
    "system_role": "",
    "few_shot_template": "",
    "bare_template": "",
    "metadata_keys": dict(_DEFAULT_METADATA),
    "format_enum": (),
    "technology_enum": (),
    "example_metadata_fields": ("format", "mne", "tech"),
    "dedup_similarity_threshold": 0.8,
    "dedup_match_fields": ("tech", "fmt", "mne"),
    "source_aliases": (),
}


def _profile_options():
    opts = [{"label": "➕ Create new domain…", "value": _NEW_VALUE}]
    for p in all_profiles():
        is_custom = custom_store.is_custom(p.name)
        suffix = " (custom)" if is_custom else " (built-in, read-only)"
        opts.append({"label": f"{p.source_label} → {p.target_label}{suffix}", "value": p.name})
    return opts


def _csv(values):
    return ", ".join(values) if values else ""


def _parse_csv(raw):
    return tuple(x.strip() for x in (raw or "").split(",") if x.strip())


def _field(label, component, help_text=None, locked=False):
    label_children = [label]
    extras = [component]
    if help_text:
        comp_id = getattr(component, "id", None)
        icon_id = f"{comp_id}-help" if isinstance(comp_id, str) and comp_id \
            else f"help-{id(component)}"
        label_children.extend([
            " ",
            html.Span(
                "\u24d8",  # ⓘ
                id=icon_id,
                className="cfg-help-icon",
                title=help_text,  # native fallback
                **{"aria-label": help_text},
            ),
        ])
        extras.append(
            dbc.Tooltip(help_text, target=icon_id, placement="right",
                        className="cfg-help-tooltip")
        )
    if locked:
        label_children.append(
            dbc.Badge("Locked — has KB records", color="warning", className="ms-2")
        )
    return dbc.Row(
        [
            dbc.Col(html.Label(label_children, style={"fontWeight": 600}), width=3),
            dbc.Col(extras, width=9),
        ],
        className="mb-3",
    )


def _text(id_, value="", disabled=False, placeholder=""):
    return dbc.Input(id=id_, type="text", value=value, disabled=disabled, placeholder=placeholder)


def _area(id_, value="", disabled=False, rows=4):
    return dbc.Textarea(id=id_, value=value, disabled=disabled, rows=rows, style={"fontFamily": "monospace", "fontSize": "0.85rem"})


layout = dbc.Container(
    [
        html.H3("Manage Domains", className="mt-3"),
        html.P(
            "Define new A→B use cases or edit existing custom domains. "
            "Built-in domains are shown read-only — copy one to start a new domain.",
            className="text-muted",
        ),

        _field(
            "Domain",
            dbc.Select(id="md-domain-picker", options=_profile_options(), value=_NEW_VALUE),
            help_text="Pick a domain to edit, or choose 'Create new domain' to start fresh.",
        ),

        html.Div(id="md-status-banner"),

        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Identity", className="mb-3"),
                    _field("Name (id)", _text("md-name"),
                           help_text="Lowercase, snake_case. Used as the stored `domain` tag — immutable once records exist."),
                    _field("Use-case code", _text("md-use-case-type"),
                           help_text="Short tag written to each record (e.g. 'tg', 'eus'). Immutable once records exist."),
                    _field("Source label", _text("md-source-label"),
                           help_text="Human label for the INPUT artifact (e.g. 'Requirement', 'Epic', 'Manual Test Case')."),
                    _field("Target label", _text("md-target-label"),
                           help_text="Human label for the OUTPUT artifact (e.g. 'Test Case', 'User Story')."),
                    _field("Source column", _text("md-source-column"),
                           help_text="Column header expected in uploaded spreadsheets. Immutable once records exist."),
                    _field("Target column", _text("md-target-column"),
                           help_text="Column header for paired output in the uploaded spreadsheet. Immutable once records exist."),
                    _field("Source aliases", _text("md-source-aliases"),
                           help_text="Comma-separated alternative column names accepted on upload and renamed to the canonical source column. Use this to chain domains: declare the previous domain's OUTPUT column here so downloaded artifacts upload as-is."),
                ]
            ),
            className="mb-3",
        ),

        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Prompt Templates", className="mb-3"),
                    html.P(
                        "Placeholders available: {examples} (few-shot only), {query}, {format}, {mne}, {tech}.",
                        className="text-muted small",
                    ),
                    _field("System role", _area("md-system-role", rows=3)),
                    _field("Few-shot template", _area("md-few-shot", rows=10),
                           help_text="Used when similar KB examples exist. Must contain {examples}, {query}, {format}, {mne}, {tech}."),
                    _field("Bare template", _area("md-bare", rows=8),
                           help_text="Used when no similar examples exist. Must contain {query}, {format}, {mne}, {tech}."),
                ]
            ),
            className="mb-3",
        ),

        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Metadata Keys", className="mb-3"),
                    html.P(
                        "Raw keys written to every stored record. Values are immutable once records exist — changing them would silently break dedup and retrieval.",
                        className="text-muted small",
                    ),
                    dbc.Row(
                        [
                            dbc.Col([html.Label("format →"), _text("md-mk-format")], width=2),
                            dbc.Col([html.Label("mne →"), _text("md-mk-mne")], width=2),
                            dbc.Col([html.Label("tech →"), _text("md-mk-tech")], width=2),
                            dbc.Col([html.Label("priority →"), _text("md-mk-priority")], width=3),
                            dbc.Col([html.Label("completion →"), _text("md-mk-completion")], width=3),
                        ],
                        className="mb-2",
                    ),
                ]
            ),
            className="mb-3",
        ),

        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Allowed Values", className="mb-3"),
                    _field("format enum", _text("md-format-enum"),
                           help_text="Comma-separated. Removing an existing value leaves old records on an unlisted format — warning only, non-breaking."),
                    _field("technology enum", _text("md-tech-enum"),
                           help_text="Comma-separated. Removing an existing value has the same caveat."),
                ]
            ),
            className="mb-3",
        ),

        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Retrieval Tuning", className="mb-3"),
                    _field("example_metadata_fields", _text("md-example-fields"),
                           help_text="Comma-separated logical field names that contribute to ranking (typical: format, mne, tech)."),
                    _field("dedup similarity threshold", dbc.Input(id="md-dedup-threshold", type="number", min=0, max=1, step=0.01),
                           help_text="0–1. Higher = fewer dedups. Tighter (0.9) for structured code; looser (0.8–0.85) for narrative."),
                    _field("dedup match fields", _text("md-dedup-fields"),
                           help_text="Comma-separated raw stored keys that must all match for a document to count as a duplicate."),
                ]
            ),
            className="mb-3",
        ),

        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Templates", className="mb-3"),
                    html.P(
                        "Download an Excel template shaped for this domain. "
                        "Reflects the current form values — you can preview a template for a draft before saving.",
                        className="text-muted small",
                    ),
                    dbc.Button("Download KB template", id="md-dl-kb-btn", color="secondary", outline=True, className="me-2"),
                    dbc.Button("Download Generate template", id="md-dl-gen-btn", color="secondary", outline=True),
                    html.Span(id="md-template-msg", className="ms-3 text-muted small"),
                    dcc.Download(id="md-template-kb"),
                    dcc.Download(id="md-template-generate"),
                ]
            ),
            className="mb-3",
        ),

        html.Div(
            [
                dbc.Button("Save", id="md-save-btn", color="primary", className="me-2"),
                dbc.Button("Delete", id="md-delete-btn", color="danger", outline=True, className="me-2"),
                html.Span(id="md-save-msg", className="ms-3"),
            ],
            className="mb-5",
        ),
    ],
    fluid=True,
    style={"maxWidth": "1100px", "paddingBottom": "60px"},
)


def _hydrate(profile_name):
    """Return (form_values, record_count, is_builtin, is_new)."""
    if profile_name == _NEW_VALUE or not profile_name:
        return dict(_BLANK), 0, False, True
    try:
        p = get_profile(profile_name)
    except KeyError:
        return dict(_BLANK), 0, False, True
    is_builtin = not custom_store.is_custom(profile_name)
    count = domain_record_count(profile_name)
    data = {
        "name": p.name,
        "source_label": p.source_label,
        "target_label": p.target_label,
        "source_column": p.source_column,
        "target_column": p.target_column,
        "use_case_type": p.use_case_type,
        "system_role": p.system_role,
        "few_shot_template": p.few_shot_template,
        "bare_template": p.bare_template,
        "metadata_keys": dict(p.metadata_keys),
        "format_enum": tuple(p.format_enum),
        "technology_enum": tuple(p.technology_enum),
        "example_metadata_fields": tuple(p.example_metadata_fields),
        "dedup_similarity_threshold": float(p.dedup_similarity_threshold),
        "dedup_match_fields": tuple(p.dedup_match_fields),
        "source_aliases": tuple(getattr(p, "source_aliases", ()) or ()),
    }
    return data, count, is_builtin, False


def _banner(record_count, is_builtin, is_new):
    if is_new:
        return dbc.Alert("Creating a new custom domain. All fields are editable.", color="info")
    if is_builtin:
        return dbc.Alert(
            "This is a built-in domain (defined in code). View-only — use 'Create new domain' to fork.",
            color="secondary",
        )
    if record_count > 0:
        return dbc.Alert(
            [
                html.Strong(f"{record_count} KB records reference this domain. "),
                "Identity fields, source/target columns, and metadata-key mappings are locked — changing them would break existing records. "
                "If you need to change those, create a new domain instead.",
            ],
            color="warning",
        )
    return dbc.Alert("No KB records yet for this domain — all fields editable.", color="success")


def register_callbacks(app: Dash):
    @app.callback(
        [
            Output("md-status-banner", "children"),
            Output("md-name", "value"), Output("md-name", "disabled"),
            Output("md-use-case-type", "value"), Output("md-use-case-type", "disabled"),
            Output("md-source-label", "value"),
            Output("md-target-label", "value"),
            Output("md-source-column", "value"), Output("md-source-column", "disabled"),
            Output("md-target-column", "value"), Output("md-target-column", "disabled"),
            Output("md-system-role", "value"),
            Output("md-few-shot", "value"),
            Output("md-bare", "value"),
            Output("md-mk-format", "value"), Output("md-mk-format", "disabled"),
            Output("md-mk-mne", "value"), Output("md-mk-mne", "disabled"),
            Output("md-mk-tech", "value"), Output("md-mk-tech", "disabled"),
            Output("md-mk-priority", "value"), Output("md-mk-priority", "disabled"),
            Output("md-mk-completion", "value"), Output("md-mk-completion", "disabled"),
            Output("md-format-enum", "value"),
            Output("md-tech-enum", "value"),
            Output("md-example-fields", "value"),
            Output("md-dedup-threshold", "value"),
            Output("md-dedup-fields", "value"),
            Output("md-source-aliases", "value"),
            Output("md-save-btn", "disabled"),
            Output("md-delete-btn", "disabled"),
            Output("md-save-msg", "children"),
        ],
        [Input("md-domain-picker", "value")],
    )
    def hydrate_form(picked):
        data, count, is_builtin, is_new = _hydrate(picked)
        lock_identity = (not is_new) and (is_builtin or count > 0)
        read_only = is_builtin
        mk = data["metadata_keys"]
        save_disabled = is_builtin
        delete_disabled = is_builtin or is_new or count > 0
        return (
            _banner(count, is_builtin, is_new),
            data["name"], read_only or (not is_new),
            data["use_case_type"], read_only or lock_identity,
            data["source_label"],
            data["target_label"],
            data["source_column"], read_only or lock_identity,
            data["target_column"], read_only or lock_identity,
            data["system_role"],
            data["few_shot_template"],
            data["bare_template"],
            mk.get("format", ""), read_only or lock_identity,
            mk.get("mne", ""), read_only or lock_identity,
            mk.get("tech", ""), read_only or lock_identity,
            mk.get("priority", ""), read_only or lock_identity,
            mk.get("completion", ""), read_only or lock_identity,
            _csv(data["format_enum"]),
            _csv(data["technology_enum"]),
            _csv(data["example_metadata_fields"]),
            data["dedup_similarity_threshold"],
            _csv(data["dedup_match_fields"]),
            _csv(data["source_aliases"]),
            save_disabled,
            delete_disabled,
            "",
        )

    @app.callback(
        [Output("md-save-msg", "children", allow_duplicate=True),
         Output("md-domain-picker", "options", allow_duplicate=True),
         Output("md-domain-picker", "value", allow_duplicate=True)],
        [Input("md-save-btn", "n_clicks"),
         Input("md-delete-btn", "n_clicks")],
        [State("md-domain-picker", "value"),
         State("md-name", "value"),
         State("md-use-case-type", "value"),
         State("md-source-label", "value"),
         State("md-target-label", "value"),
         State("md-source-column", "value"),
         State("md-target-column", "value"),
         State("md-system-role", "value"),
         State("md-few-shot", "value"),
         State("md-bare", "value"),
         State("md-mk-format", "value"),
         State("md-mk-mne", "value"),
         State("md-mk-tech", "value"),
         State("md-mk-priority", "value"),
         State("md-mk-completion", "value"),
         State("md-format-enum", "value"),
         State("md-tech-enum", "value"),
         State("md-example-fields", "value"),
         State("md-dedup-threshold", "value"),
         State("md-dedup-fields", "value"),
         State("md-source-aliases", "value")],
        prevent_initial_call=True,
    )
    def save_or_delete(save_clicks, delete_clicks, picked,
                       name, use_case_type, source_label, target_label,
                       source_column, target_column,
                       system_role, few_shot, bare,
                       mk_format, mk_mne, mk_tech, mk_priority, mk_completion,
                       format_enum_raw, tech_enum_raw, example_fields_raw,
                       dedup_threshold, dedup_fields_raw, source_aliases_raw):
        trigger = callback_context.triggered[0]["prop_id"].split(".")[0] if callback_context.triggered else ""

        if trigger == "md-delete-btn":
            if not picked or picked == _NEW_VALUE:
                return dbc.Alert("Nothing to delete.", color="warning"), dash.no_update, dash.no_update
            if not custom_store.is_custom(picked):
                return dbc.Alert("Built-in domains can't be deleted.", color="danger"), dash.no_update, dash.no_update
            if domain_record_count(picked) > 0:
                return dbc.Alert("Domain has KB records — cannot delete.", color="danger"), dash.no_update, dash.no_update
            custom_store.delete(picked)
            return dbc.Alert(f"Deleted '{picked}'.", color="success"), _profile_options(), _NEW_VALUE

        # Save path — validate identity fields first
        errors = []
        name = (name or "").strip().lower()
        if not name.replace("_", "").isalnum():
            errors.append("Name must be lowercase snake_case (letters/digits/underscore).")
        for label, val in [("use-case code", use_case_type), ("source label", source_label),
                            ("target label", target_label), ("source column", source_column),
                            ("target column", target_column)]:
            if not (val or "").strip():
                errors.append(f"{label} is required.")
        fmt_enum = _parse_csv(format_enum_raw)
        tech_enum = _parse_csv(tech_enum_raw)
        if not fmt_enum:
            errors.append("format enum cannot be empty.")
        if not tech_enum:
            errors.append("technology enum cannot be empty.")
        required_placeholders = ["{query}", "{format}", "{mne}", "{tech}"]
        for ph in required_placeholders:
            if ph not in (few_shot or ""):
                errors.append(f"Few-shot template missing placeholder {ph}.")
            if ph not in (bare or ""):
                errors.append(f"Bare template missing placeholder {ph}.")
        if "{examples}" not in (few_shot or ""):
            errors.append("Few-shot template missing placeholder {examples}.")
        try:
            threshold = float(dedup_threshold) if dedup_threshold is not None else 0.8
            if not (0 <= threshold <= 1):
                errors.append("dedup threshold must be between 0 and 1.")
        except (TypeError, ValueError):
            errors.append("dedup threshold must be a number.")
            threshold = 0.8

        editing_existing = picked and picked != _NEW_VALUE
        if editing_existing and not custom_store.is_custom(picked):
            errors.append("Built-in domains are read-only.")

        if errors:
            return dbc.Alert([html.Strong("Cannot save:"), html.Ul([html.Li(e) for e in errors])], color="danger"), dash.no_update, dash.no_update

        # Immutability check: if editing a custom domain with records, identity fields must match saved version.
        warning_extra = []
        if editing_existing:
            existing = custom_store.load_one(picked)
            count = domain_record_count(picked)
            if count > 0:
                locked_pairs = [
                    ("name", name, existing["name"]),
                    ("use_case_type", use_case_type, existing["use_case_type"]),
                    ("source_column", source_column, existing["source_column"]),
                    ("target_column", target_column, existing["target_column"]),
                ]
                for field, new_v, old_v in locked_pairs:
                    if (new_v or "").strip() != old_v:
                        return dbc.Alert(
                            f"'{field}' is locked — {count} KB records exist. Create a new domain instead.",
                            color="danger",
                        ), dash.no_update, dash.no_update
                stored_mk = existing["metadata_keys"]
                new_mk = {"format": mk_format, "mne": mk_mne, "tech": mk_tech,
                          "priority": mk_priority, "completion": mk_completion}
                for k, v in new_mk.items():
                    if (v or "").strip() != stored_mk.get(k):
                        return dbc.Alert(
                            f"metadata_keys.{k} is locked — {count} KB records exist.", color="danger",
                        ), dash.no_update, dash.no_update
                removed_fmt = set(existing["format_enum"]) - set(fmt_enum)
                removed_tech = set(existing["technology_enum"]) - set(tech_enum)
                if removed_fmt:
                    warning_extra.append(f"Removed format values {sorted(removed_fmt)} — existing records with these values will still retrieve but aren't selectable on new uploads.")
                if removed_tech:
                    warning_extra.append(f"Removed tech values {sorted(removed_tech)} — same caveat.")

        profile = DomainProfile(
            name=name,
            source_label=source_label.strip(),
            target_label=target_label.strip(),
            source_column=source_column.strip(),
            target_column=target_column.strip(),
            use_case_type=use_case_type.strip(),
            system_role=(system_role or "").strip(),
            few_shot_template=few_shot,
            bare_template=bare,
            metadata_keys={
                "format": (mk_format or "fmt").strip(),
                "mne": (mk_mne or "mne").strip(),
                "tech": (mk_tech or "tech").strip(),
                "priority": (mk_priority or "priority").strip(),
                "completion": (mk_completion or "comp").strip(),
            },
            format_enum=fmt_enum,
            technology_enum=tech_enum,
            example_metadata_fields=_parse_csv(example_fields_raw) or ("format", "mne", "tech"),
            dedup_similarity_threshold=threshold,
            dedup_match_fields=_parse_csv(dedup_fields_raw) or ("tech", "fmt", "mne"),
            source_aliases=_parse_csv(source_aliases_raw),
        )

        try:
            custom_store.save(profile)
        except Exception as e:
            return dbc.Alert(f"Save failed: {e}", color="danger"), dash.no_update, dash.no_update

        msg_children = [html.Strong(f"Saved '{profile.name}'.")]
        if warning_extra:
            msg_children.append(html.Ul([html.Li(w) for w in warning_extra]))
        return dbc.Alert(msg_children, color="success"), _profile_options(), profile.name

    def _form_profile(name, source_column, target_column, format_enum_raw,
                      tech_enum_raw, source_aliases_raw):
        return SimpleNamespace(
            name=(name or "domain").strip() or "domain",
            source_column=(source_column or "").strip(),
            target_column=(target_column or "").strip(),
            format_enum=_parse_csv(format_enum_raw),
            technology_enum=_parse_csv(tech_enum_raw),
            source_aliases=_parse_csv(source_aliases_raw),
        )

    def _template_ready(p, *, kind):
        if not p.source_column:
            return "Fill 'Source column' to download a template."
        if kind == "kb" and not p.target_column:
            return "Fill 'Target column' to download a KB template."
        if not p.format_enum:
            return "Fill 'format enum' to download a template."
        if not p.technology_enum:
            return "Fill 'technology enum' to download a template."
        return None

    _TEMPLATE_STATES = [
        State("md-name", "value"),
        State("md-source-column", "value"),
        State("md-target-column", "value"),
        State("md-format-enum", "value"),
        State("md-tech-enum", "value"),
        State("md-source-aliases", "value"),
    ]

    @app.callback(
        [Output("md-template-kb", "data"),
         Output("md-template-msg", "children", allow_duplicate=True)],
        Input("md-dl-kb-btn", "n_clicks"),
        _TEMPLATE_STATES,
        prevent_initial_call=True,
    )
    def download_kb_template(n, name, src_col, tgt_col, fmt_raw, tech_raw, alias_raw):
        p = _form_profile(name, src_col, tgt_col, fmt_raw, tech_raw, alias_raw)
        err = _template_ready(p, kind="kb")
        if err:
            return dash.no_update, err
        blob = build_template_xlsx(p, kind="kb")
        return dcc.send_bytes(lambda b: b.write(blob), template_filename(p, "kb")), ""

    @app.callback(
        [Output("md-template-generate", "data"),
         Output("md-template-msg", "children", allow_duplicate=True)],
        Input("md-dl-gen-btn", "n_clicks"),
        _TEMPLATE_STATES,
        prevent_initial_call=True,
    )
    def download_generate_template(n, name, src_col, tgt_col, fmt_raw, tech_raw, alias_raw):
        p = _form_profile(name, src_col, tgt_col, fmt_raw, tech_raw, alias_raw)
        err = _template_ready(p, kind="generate")
        if err:
            return dash.no_update, err
        blob = build_template_xlsx(p, kind="generate")
        return dcc.send_bytes(lambda b: b.write(blob), template_filename(p, "generate")), ""
