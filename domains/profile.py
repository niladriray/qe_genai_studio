from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class DomainProfile:
    """
    Describes a single A→B transformation domain end-to-end.

    The engine reads everything domain-specific from the active profile:
    prompt wording, column names on uploads, which metadata fields matter
    for dedup/matching, and which priority/format/tech keys live on stored
    records. Adding a new domain (e.g. Epic → User Story) means writing a
    new profile module and registering it — no engine edits required.
    """

    name: str                                   # stable id, e.g. "test_case", "epic_to_user_story"
    source_label: str                           # human-facing label for the input side (e.g. "Requirement", "Epic")
    target_label: str                           # human-facing label for the output side (e.g. "Test Case", "User Story")
    source_column: str                          # column name expected in uploaded spreadsheets (input)
    target_column: str                          # column name for the paired artifact (output)
    use_case_type: str                          # legacy use-case tag written as USE_CASE_LABEL on stored records
    system_role: str                            # system/role sentence embedded at the top of the prompt
    few_shot_template: str                      # .format placeholders: {examples}, {query}, {format}, {mne}, {tech}
    bare_template: str                          # no-context variant, same placeholders minus {examples}
    metadata_keys: Mapping[str, str]            # logical → stored key: format/mne/tech/priority/completion
    format_enum: Sequence[str]                  # allowed values for the "format" metadata dimension
    technology_enum: Sequence[str]              # allowed values for the "tech" metadata dimension
    example_metadata_fields: Sequence[str] = field(
        default_factory=lambda: ("format", "mne", "tech")
    )                                           # logical fields that count toward metadata-match score during retrieval
    dedup_similarity_threshold: float = 0.8     # minimum cosine similarity to call two pairs duplicates
    dedup_match_fields: Sequence[str] = field(
        default_factory=lambda: ("tech", "fmt", "mne")
    )                                           # raw stored keys that must all match for dedup to fire
    source_aliases: Sequence[str] = field(default_factory=tuple)
    # Alternative column names accepted for `source_column` on upload and
    # renamed to the canonical column before validation. Lets a download
    # from the previous workflow domain feed this domain's upload as-is
    # (e.g. "Generated User Story" → "Requirement" for test_case).

    next_profile_name: Optional[str] = None
    # Registered name of the downstream profile in the workflow chain. When
    # set, the Generate page reshapes its download so it can be uploaded
    # directly into that next profile (blanks out the stale Format values
    # since format semantics differ per domain, and drops internal columns).
