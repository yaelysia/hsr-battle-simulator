"""Frigid Prowler prerequisites and Overheat cleanup, pinned TBGD 14c1d18f.

Monster_W1_Mecha03_01_AI requires no existing summons for Skill05, an owned
minion for Skill07, and no minion for Skill08. The attack rotation and targets
remain external choices. Monster_W1_Mecha03_01_Overheat.OnAllowAction removes
the debuff on the next own action; use the public pre-skill window for that.
All attacks, summons, random absorption, marks and stacking debuffs are native.
"""
from dataclasses import replace

from ..core.content_hooks import AvailabilityContext, ContentProcessorBase, EventHookContext, EventSubscription, HookResult
from ..systems.action_availability import BlockedActionReason


class FrigidProwlerProcessor(ContentProcessorBase):
    content_id = "monster:1023020"
    version = "0.1.0"

    def filter_choices(self, ctx: AvailabilityContext) -> AvailabilityContext:
        minions = any(u.hp > 0 and u.lifecycle_status == 'active'
                      and u.flags.get('summoner_id') == ctx.actor.unit_id for u in ctx.state.units.values())
        unavailable = ({'monster_skill:102302005', 'monster_skill:102302008'} if minions
                       else {'monster_skill:102302007'})
        rejected = tuple(c for c in ctx.choices if c.action_id in unavailable)
        return replace(ctx, choices=tuple(c for c in ctx.choices if c.action_id not in unavailable),
            blocked=ctx.blocked + tuple(BlockedActionReason('prowler_summon_prerequisite_not_met', 'content',
                actor_id=ctx.actor.unit_id, actor_side=ctx.actor.side,
                action_id=c.action_id, action_level=c.action_level) for c in rejected))

    def subscriptions(self) -> tuple[EventSubscription, ...]:
        return (EventSubscription(('action.window.before_skill_use',)),)

    def on_event(self, ctx: EventHookContext) -> HookResult:
        unit = ctx.state.units.get(ctx.event.source_id)
        definition = ctx.event.action_definition
        if unit is not None and unit.template_id == self.content_id and definition is not None \
                and definition.action_id != 'monster_skill:102302008':
            for detail in unit.flags.get('status_details', ()):
                if detail.get('modifier_name') == 'Monster_W1_Mecha03_01_Overheat':
                    ctx.services.remove_status(unit.unit_id, detail)
        return ctx.services.finish()
