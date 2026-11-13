"""Weaver attack variants from pinned TBGD 14c1d18f.

Monster_XP_Minion02_00_AI.Decision02 selects Skill02 while XP_Minion02_00_Attack
is present, otherwise Skill01. Only this state-dependent variant is enforced;
the external controller still chooses attacks and targets, not an AI rotation.
Damage, the Skill03 buff and its removal remain native compiled tasks.
"""
from dataclasses import replace

from ..core.content_hooks import AvailabilityContext, ContentProcessorBase
from ..systems.action_availability import BlockedActionReason


class ImaginaryWeaverProcessor(ContentProcessorBase):
    content_id = "monster:8002010"
    version = "0.1.0"

    def filter_choices(self, ctx: AvailabilityContext) -> AvailabilityContext:
        enhanced = "modifier:XP_Minion02_00_Attack" in ctx.actor.statuses
        unavailable = "monster_skill:800201001" if enhanced else "monster_skill:800201002"
        rejected = tuple(c for c in ctx.choices if c.action_id == unavailable)
        return replace(ctx,
            choices=tuple(c for c in ctx.choices if c.action_id != unavailable),
            blocked=ctx.blocked + tuple(BlockedActionReason(
                "weaver_attack_variant_requires_buff" if not enhanced else "weaver_attack_variant_is_enhanced",
                "content", actor_id=ctx.actor.unit_id, actor_side=ctx.actor.side,
                action_id=c.action_id, action_level=c.action_level,
            ) for c in rejected))
