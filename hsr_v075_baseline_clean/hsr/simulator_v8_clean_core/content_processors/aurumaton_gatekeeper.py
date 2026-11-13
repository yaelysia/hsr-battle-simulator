"""Regular Aurumaton action windows; passive activation is owned by the queue.

Fixed TBGD 14c1d18f: Monster_W2_Mecha03_00_Config.SkillList marks SkillP01
as Passive. Overdrive_On and Skill03's lifetime predicate define sanction state.
https://honkai-star-rail.fandom.com/wiki/Aurumaton_Gatekeeper documents that
Sanction Mode activates Restraint and Enchainment; ordinary mode uses Dread.
This restricts legal choices without selecting an enemy action or target.
"""
from dataclasses import replace

from ..core.content_hooks import AvailabilityContext, ContentProcessorBase
from ..systems.action_availability import BlockedActionReason


class AurumatonGatekeeperProcessor(ContentProcessorBase):
    content_id = "monster:2013010"
    version = "0.1.0"

    def filter_choices(self, ctx: AvailabilityContext) -> AvailabilityContext:
        sanction = "modifier:MMonster_W2_Mecha03_00_Overdrive_On" in ctx.actor.statuses
        allowed = {"monster_skill:201301003", "monster_skill:201301004"} if sanction else {"monster_skill:201301002"}
        choices, blocked = [], list(ctx.blocked)
        for choice in ctx.choices:
            if choice.action_id.startswith("monster_skill:") and choice.action_id not in allowed:
                reason = ("aurumaton_passive_is_automatic" if choice.action_id == "monster_skill:201301001"
                          else "aurumaton_action_requires_sanction_mode" if not sanction
                          else "aurumaton_action_unavailable_in_sanction_mode")
                blocked.append(BlockedActionReason(reason, "content", actor_id=ctx.actor.unit_id,
                    actor_side=ctx.actor.side, action_id=choice.action_id, action_level=choice.action_level))
            else:
                choices.append(choice)
        return replace(ctx, choices=tuple(choices), blocked=tuple(blocked))
