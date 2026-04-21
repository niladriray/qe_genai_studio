"""
Introspection helpers for domain profiles — used by the Manage Domains page
to decide which fields are safe to edit vs locked.
"""

from configs.config import Config
from models.generator_singleton import get_generator


def domain_record_count(domain_name: str) -> int:
    """
    Count KB records tagged with the given domain. Records written before
    domain tagging existed default to Config.DEFAULT_DOMAIN.
    """
    try:
        generator = get_generator(profile_name=domain_name)
        docs = generator.vector_db_connector.execute("list_all")
    except Exception:
        return 0
    count = 0
    for d in docs:
        tag = d.metadata.get("domain", Config.DEFAULT_DOMAIN)
        if tag == domain_name:
            count += 1
    return count
