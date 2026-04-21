from configs.config import Config


class UploadValidationError(ValueError):
    """Raised when an uploaded spreadsheet fails schema/metadata validation."""


def validate_columns(df, required=None, *, profile=None, include_target=True):
    """
    Ensure the uploaded DataFrame has the required columns.

    Two call styles are supported:
      - legacy: ``validate_columns(df, ["Requirement", "Test Case", "Format"])``
      - profile-driven: ``validate_columns(df, profile=profile)`` — derives the
        required columns from ``profile.source_column`` / ``profile.target_column``
        so a new A→B domain (e.g. Epic → User Story) works without code edits.
    """
    if required is None:
        if profile is None:
            raise ValueError("Either `required` or `profile` must be provided.")
        required = [profile.source_column]
        if include_target:
            required.append(profile.target_column)
        required.append("Format")

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise UploadValidationError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Found columns: {', '.join(df.columns)}"
        )


def normalize_metadata(record: dict) -> dict:
    """
    Lowercase/strip metadata enum values so dedup and retrieval aren't broken
    by case mismatches (e.g. 'BDD' vs 'bdd').
    """
    out = dict(record)
    for key in ("Format", "format", "fmt"):
        if key in out and isinstance(out[key], str):
            out[key] = out[key].strip().lower()
    for key in ("Tech", "tech"):
        if key in out and isinstance(out[key], str):
            out[key] = out[key].strip().lower()
    for key in ("MNE", "mne"):
        if key in out and isinstance(out[key], str):
            out[key] = out[key].strip()
    return out


def validate_enum_values(records, format_key="Format", tech_key="Tech", *, profile=None, strict_format=False):
    """
    Return human-readable warnings for out-of-enum metadata. When
    ``strict_format=True`` (used on the upload path), a format value
    outside the profile's enum is a hard error — we raise
    ``UploadValidationError`` so the upload is rejected, so cross-domain
    reuse cannot silently carry a stale Format into the next step.
    """
    warnings = []
    if profile is not None:
        allowed_fmt = set(profile.format_enum)
        allowed_tech = set(profile.technology_enum)
    else:
        allowed_fmt = set(Config.META_DATA_TG_FORMAT_TYPE)
        allowed_tech = set(Config.META_DATA_TG_TECHNOLOGY_TYPE)
    format_errors = []
    for i, rec in enumerate(records, start=1):
        fmt = rec.get(format_key)
        if fmt and fmt not in allowed_fmt:
            msg = f"Row {i}: format '{fmt}' is not in {sorted(allowed_fmt)}"
            if strict_format:
                format_errors.append(msg)
            else:
                warnings.append(msg)
        tech = rec.get(tech_key)
        if tech and tech not in allowed_tech:
            warnings.append(
                f"Row {i}: tech '{tech}' is not in {sorted(allowed_tech)}"
            )
    if format_errors:
        raise UploadValidationError(
            "Invalid Format values for this domain. Edit the Format column to one of "
            f"{sorted(allowed_fmt)} and re-upload.\n" + "\n".join(format_errors)
        )
    return warnings


def suggest_better_profile(df, current_profile):
    """
    Scan every registered domain profile and return the first one whose
    canonical source_column (or any declared source_alias) appears in the
    uploaded DataFrame while the currently-selected profile's canonical
    column does NOT. Used to turn the generic "Missing required column"
    error into a "did you mean <other domain>?" hint.
    """
    if current_profile is not None:
        if current_profile.source_column in df.columns:
            return None
    # Import lazily to avoid a cycle at module load time.
    from domains.registry import all_profiles
    cols_lower = {str(c).strip().lower() for c in df.columns}
    for p in all_profiles():
        if current_profile is not None and p.name == current_profile.name:
            continue
        if p.source_column.strip().lower() in cols_lower:
            return p
        for alias in getattr(p, "source_aliases", ()) or ():
            if alias.strip().lower() in cols_lower:
                return p
    return None


def apply_source_alias(df, profile):
    """
    Rename any recognised alias column to the profile's canonical
    ``source_column``. Case-insensitive match; first alias found wins;
    no-op when the canonical column already exists. Lets a download
    from the previous workflow domain feed this domain's upload as-is.
    """
    if profile is None or not getattr(profile, "source_aliases", None):
        return df
    if profile.source_column in df.columns:
        return df
    lower_to_actual = {str(c).strip().lower(): c for c in df.columns}
    for alias in profile.source_aliases:
        match = lower_to_actual.get(alias.strip().lower())
        if match is not None:
            return df.rename(columns={match: profile.source_column})
    return df
