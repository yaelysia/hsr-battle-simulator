"""L2 content-specific processor catalog.

The catalog is content-layer data: it maps a content identity (entity_ref)
to the processor class that card carries. The kernel mounts entries
generically (core.content_hooks.mount_catalog) and dispatches by the acting
unit's own identity; no kernel code branches on the names or ids below.

Mount interface and writing conventions: ARCHITECTURE_BOUNDARY_CONTRACT.md §5
(established by the M1-3 experiment).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.content_hooks import mount_catalog
from .castorice import CastoriceProcessor, CastoriceServantProcessor

if TYPE_CHECKING:
    from ..rules.rulebook import RuleBook

PROCESSOR_CATALOG = {
    "avatar:1407": CastoriceProcessor,
    "servant:11407": CastoriceServantProcessor,
}


def mount_catalog_processors(rules: "RuleBook") -> "RuleBook":
    """Assembly entry: mount processors for content present in the RuleBook."""
    return mount_catalog(rules, PROCESSOR_CATALOG)
