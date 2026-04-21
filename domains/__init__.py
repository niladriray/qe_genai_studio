"""
Domain profile registry.

Importing this package auto-registers the built-in profiles. To add a new
A→B use case (e.g. Epic → User Story), drop a new module in this package
that builds a DomainProfile and calls register(...) at import time, then
add the module to the import list below.
"""

from domains import epic_to_user_story  # noqa: F401  (registers epic_to_user_story profile)
from domains import test_case  # noqa: F401  (registers test_case profile)
from domains import manual_to_automation  # noqa: F401  (registers manual_to_automation profile)

# Load any user-defined profiles persisted via the Manage Domains page.
from domains.custom_store import load_all as _load_custom_profiles

_load_custom_profiles()
