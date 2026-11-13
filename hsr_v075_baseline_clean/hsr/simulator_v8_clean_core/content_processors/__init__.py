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

from ..core.content_hooks import mount_catalog, attach_processors, MountedProcessor
from .castorice import CastoriceProcessor, CastoriceServantProcessor
from .pela import PelaProcessor
from .asta import AstaProcessor
from .silvermane_lieutenant import SilvermaneLieutenantProcessor
from .aurumaton_gatekeeper import AurumatonGatekeeperProcessor
from .imaginary_weaver import ImaginaryWeaverProcessor
from .frigid_prowler import FrigidProwlerProcessor
from .guardian_shadow import GuardianShadowProcessor
from .aurumaton_envoy import AurumatonEnvoyProcessor
from .voidranger_trampler import VoidrangerTramplerProcessor
from .academic_rumors import AcademicRumorsProcessor
from .jing_yuan import JingYuanProcessor
from .topaz import TopazProcessor
from .lingsha import FuyuanProcessor
from .aglaea import AglaeaProcessor
from .memory_trailblazer import MemoryTrailblazerProcessor, MemProcessor
from .evernight import EvernightProcessor, NightProcessor
from .hyacine import HyacineProcessor

if TYPE_CHECKING:
    from ..rules.rulebook import RuleBook

PROCESSOR_CATALOG = {
    "avatar:1409": HyacineProcessor,
    "avatar:1413": EvernightProcessor,
    "servant:11413": NightProcessor,
    "servant:18007": MemProcessor,
    "avatar:8007": MemoryTrailblazerProcessor,
    "avatar:1402": AglaeaProcessor,
    "battle_event:11222": FuyuanProcessor,
    "avatar:1112": TopazProcessor,
    "avatar:1204": JingYuanProcessor,
    "monster:8013010": VoidrangerTramplerProcessor,
    "monster:2013020": AurumatonEnvoyProcessor,
    "monster:8003030": GuardianShadowProcessor,
    "monster:1023020": FrigidProwlerProcessor,
    "monster:8002010": ImaginaryWeaverProcessor,
    "monster:2013010": AurumatonGatekeeperProcessor,
    "monster:1003010": SilvermaneLieutenantProcessor,
    "avatar:1009": AstaProcessor,
    "avatar:1106": PelaProcessor,
    "avatar:1407": CastoriceProcessor,
    "servant:11407": CastoriceServantProcessor,
}


def mount_catalog_processors(rules: "RuleBook") -> "RuleBook":
    """Assembly entry: mount processors for content present in the RuleBook."""
    rules = mount_catalog(rules, PROCESSOR_CATALOG)
    if any(w.stage_environment_data for w in rules.ir.wave_definitions):
        processor = AcademicRumorsProcessor()
        attach_processors(rules, (*rules.content_processors,
            MountedProcessor(processor.content_id, processor.version, processor)))
    return rules
