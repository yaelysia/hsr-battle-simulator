"""Asta E0 bounce energy, using actual typed hit completions.

Fixed TBGD 14c1d18f: AvatarSkillConfig 100902 SPBase is per hit (6),
Avatar_Asta_00_Skill02_Phase02 executes one primary and four bounce hits.
https://srl.keqingmains.com/characters/fire/asta: Meteor Storm grants 6 per hit.
The ordinary action resource plan already grants the primary hit's SPBase;
this handler grants only the executed bounces, through L1 ERR/cap settlement.
V1 E0 and Chorus have no regeneration-rate change within this attack.
"""
from ..core.content_hooks import ContentProcessorBase, EventHookContext, EventSubscription, HookResult


class AstaProcessor(ContentProcessorBase):
    content_id = "avatar:1009"
    version = "0.1.0"

    def subscriptions(self) -> tuple[EventSubscription, ...]:
        return (EventSubscription(("damage.hit_sequence.after",)),)

    def on_event(self, ctx: EventHookContext) -> HookResult:
        fact = ctx.event.hit_window_invocation_fact
        actor = ctx.state.units.get(ctx.event.source_id)
        if fact is None or actor is None or actor.template_id != self.content_id:
            return ctx.services.finish()
        if not fact.matches(ctx.event):
            return ctx.services.block("asta_hit_window_identity_mismatch")
        # ponytail: scan the scoped IR tasks per hit; index by the
        # producer task if this becomes measurable in the fixed benchmark.
        task = next((t for t in ctx.services.rules.ir.ability_tasks
                     if t.action_id == "avatar_skill:100902" and t.opcode == "DamageByAttackProperty"
                     and (fact.sequence_id == t.task_id or fact.sequence_id.startswith(t.task_id + ":"))), None)
        if task is not None and any(e.target_group.startswith("bounce:")
                                    for e in ctx.services.rules.damage_emissions_for_task(task.task_id)):
            definition = ctx.services.rules.action_definition(task.action_id, task.level)
            if definition is None:
                return ctx.services.block("asta_bounce_energy_definition_missing")
            ctx.services.grant_energy(actor.unit_id, definition.sp_base, ctx.event)
        return ctx.services.finish()
