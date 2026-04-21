"""
On-the-fly Excel template builder for domain profiles.

Exposes one public function, ``build_template_xlsx(profile, kind=...)``,
returning an in-memory ``.xlsx`` byte stream. The Manage Domains page
binds it to two download buttons per profile:

  • ``kind="kb"``       — columns for the Add Context (KB) upload path
  • ``kind="generate"`` — columns for the Generate upload path

The workbook always carries a second sheet "Allowed Values" listing the
profile's format/tech enums and (for the generate template) the
accepted source-column aliases, so the user opens a file that is
self-documenting.
"""

import io

import pandas as pd


def _columns_for(profile, kind: str):
    if kind == "kb":
        return [profile.source_column, profile.target_column, "Format", "tech", "mne"]
    if kind == "generate":
        return [profile.source_column, "Format", "tech", "mne"]
    raise ValueError(f"Unknown template kind: {kind!r}")


def build_template_xlsx(profile, *, kind: str) -> bytes:
    columns = _columns_for(profile, kind)
    empty_row = {c: "" for c in columns}
    df = pd.DataFrame([empty_row], columns=columns)

    allowed_rows = []
    for v in profile.format_enum:
        allowed_rows.append({"Field": "Format", "Allowed value": v})
    for v in profile.technology_enum:
        allowed_rows.append({"Field": "tech", "Allowed value": v})
    if kind == "generate":
        for alias in getattr(profile, "source_aliases", ()) or ():
            allowed_rows.append({"Field": f"alias for '{profile.source_column}'", "Allowed value": alias})
    allowed_df = pd.DataFrame(allowed_rows, columns=["Field", "Allowed value"])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Template", index=False)
        allowed_df.to_excel(writer, sheet_name="Allowed Values", index=False)

        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#F0F0F0", "border": 1})
        tpl_sheet = writer.sheets["Template"]
        for col_idx, col in enumerate(columns):
            tpl_sheet.write(0, col_idx, col, header_fmt)
            tpl_sheet.set_column(col_idx, col_idx, max(18, len(col) + 2))
        tpl_sheet.freeze_panes(1, 0)

        av_sheet = writer.sheets["Allowed Values"]
        for col_idx, col in enumerate(["Field", "Allowed value"]):
            av_sheet.write(0, col_idx, col, header_fmt)
        av_sheet.set_column(0, 0, 28)
        av_sheet.set_column(1, 1, 32)
        av_sheet.freeze_panes(1, 0)

    output.seek(0)
    return output.read()


def template_filename(profile, kind: str) -> str:
    return f"{profile.name}_{kind}_template.xlsx"
