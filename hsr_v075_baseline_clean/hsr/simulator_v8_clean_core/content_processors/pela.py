"""Pela's two-projectile basic; all hit settlement uses the L1 task consumer.

Fixed TBGD 14c1d18f91a8101d610e6c523447a7517de3fae1:
Avatar_Pela_00_Skill01_Phase02 launches GunA, then GunC at the selected
target, with identical fixed speed and no collision/miss branch. The first
launch does not wait; the second waits. Combat resolves their two impacts
in launch order. Rendering flight time is outside the simulator's scope.
Both damage and toughness expressions remain the compiled card inputs.
"""
from ..core.content_hooks import ActionHookContext, ContentProcessorBase, EventHookContext, EventSubscription, HookResult
from ..core.model import BattleState


class PelaProcessor(ContentProcessorBase):
    content_id = "avatar:1106"
    version = "0.2.0"
    _WIPE_OUT = "MAvatar_Pela_SkillTree03_DamageAddedRatio"
    _CONSUMING = "pela_wipe_out_consuming"
    replaced_status_callbacks = frozenset({(_WIPE_OUT, "OnAfterAttack")})

    # https://srl.keqingmains.com/characters/pela/ — Wipe Out buffs the NEXT
    # attack. The source grants it after DamagePerformFinish, whereas the
    # compiled action dispatches OnAfterAttack after the whole root graph.
    # Track whether the buff existed before this attack, and retain a new grant.
    def subscriptions(self) -> tuple[EventSubscription, ...]:
        return (EventSubscription(("status.lifecycle", "action.window.before_attack", "action.window.after_attack")),)

    def on_event(self, ctx: EventHookContext) -> HookResult:
        event = ctx.event
        fact = event.status_lifecycle_fact
        if fact is not None:
            if fact.modifier_name == self._WIPE_OUT and fact.callback_event == "OnModifierAdd":
                ctx.services.set_unit_flag(fact.owner_id, self._CONSUMING, False, reason="new Wipe Out grant belongs to the next attack")
            return ctx.services.finish()
        actor = ctx.state.units.get(event.source_id)
        if actor is None or actor.template_id != self.content_id:
            return ctx.services.finish()
        detail = next((d for d in actor.flags.get("status_details", ())
                       if d.get("modifier_name") == self._WIPE_OUT
                       and d.get("status_id") in actor.statuses), None)
        if event.event_type == "action.window.before_attack":
            ctx.services.set_unit_flag(actor.unit_id, self._CONSUMING, detail is not None, reason="capture Wipe Out before the attack")
        elif event.event_type == "action.window.after_attack" and actor.flags.get(self._CONSUMING):
            if detail is not None:
                ctx.services.remove_status(actor.unit_id, detail)
            ctx.services.set_unit_flag(actor.unit_id, self._CONSUMING, False, reason="consume Wipe Out after its attack")
        return ctx.services.finish()

    def claims_action(self, state: BattleState, action_id: str, action_level: int) -> bool:
        return action_id == "avatar_skill:110601"

    def execute_action(self, ctx: ActionHookContext) -> HookResult:
        hits = tuple(task.task_id for task in ctx.services.rules.ability_tasks_for_action(
            ctx.command.action_id, ctx.command.action_level,
        ) if task.opcode == "DamageByAttackProperty" and task.callback_kind == "OnStart")
        if len(hits) != 2:
            return ctx.services.block("pela_basic_two_compiled_hits_required")
        ctx.services.execute_damage_tasks(hits, action_definition=ctx.action_definition,
                                          target_resolution=ctx.target_resolution)
        return ctx.services.finish(takeover=True)
