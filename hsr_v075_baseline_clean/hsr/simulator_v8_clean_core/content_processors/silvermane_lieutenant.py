"""Regular Silvermane Lieutenant counter, excluding score-only bookkeeping.

Fixed TBGD 14c1d18f: Monster_W1_Soldier03_00_Ability.json,
MMonster_W1_Soldier03_00_ListenBeingAttacked.OnAfterBeingAttacked.
The outer native predicate checks the attacker team, counter guard, control and
Break. The regular-monster branch writes ReturnAttackCounter and enqueues the
native Skill06_Insert. BattleScore writes are excluded by the V1 scope; GridFight
backend/fake-avatar attacks do not exist in the admitted ordinary battle inputs.
"""
from ..core.content_hooks import ActionHookContext, ContentProcessorBase, EventHookContext, EventSubscription, HookResult
from ..core.model import BattleState


_STANCE = "MMonster_W1_Soldier03_00_ListenBeingAttacked"
_EVENT = "OnAfterBeingAttacked"
_COUNTER = "Monster_W1_Soldier03_00_Skill06_Insert_Phase01"


class SilvermaneLieutenantProcessor(ContentProcessorBase):
    content_id = "monster:1003010"
    version = "0.4.0"
    replaced_status_callbacks = frozenset({(_STANCE, _EVENT)})
    # Phase01 only calls this body and the camera, then arranges presentation.
    # Select the compiled body; retain native queue timing and body mutations.
    standalone_body_overrides = ((_COUNTER, "Monster_W1_Soldier03_00_Skill06_Insert_Phase02"),)

    def claims_action(self, state: BattleState, action_id: str, action_level: int) -> bool:
        return action_id == "monster_skill:100301002"

    def execute_action(self, ctx: ActionHookContext) -> HookResult:
        # SkillAbilityList also catalogs the alternate stance and counter bodies.
        # SkillList.EntryAbility calls only this ordinary thrust body.
        tasks = [t for t in ctx.services.rules.ability_tasks_for_action(
            ctx.command.action_id, ctx.command.action_level,
        ) if t.ability_name == "Monster_W1_Soldier03_00_Skill06_Phase02"
            and t.opcode == "DamageByAttackProperty" and t.callback_kind == "OnStart"]
        hits = tuple(t.task_id for t in sorted(tasks, key=lambda t: t.task_index))
        if len(hits) != 5:
            return ctx.services.block("lieutenant_thrust_five_compiled_hits_required")
        ctx.services.execute_damage_tasks(hits, action_definition=ctx.action_definition,
                                          target_resolution=ctx.target_resolution)
        unit = ctx.services.unit(ctx.command.actor_id)
        for detail in unit.flags.get("status_details", ()):
            if detail.get("modifier_name") == _STANCE:
                ctx.services.remove_status(unit.unit_id, detail)
        return ctx.services.finish(takeover=True)

    def subscriptions(self) -> tuple[EventSubscription, ...]:
        return (EventSubscription(("damage.target_attack.after",)),)

    def on_event(self, ctx: EventHookContext) -> HookResult:
        unit = ctx.state.units.get(ctx.event.target_id)
        if unit is None or unit.template_id != self.content_id or not any(
            d.get("modifier_name") == _STANCE for d in unit.flags.get("status_details", ())
        ):
            return ctx.services.finish()
        rules = ctx.services.rules
        callbacks = rules.status_callbacks_for_modifier_event(_STANCE, _EVENT)
        if len(callbacks) != 1:
            return ctx.services.block("lieutenant_counter_callback_missing")
        callback = callbacks[0]
        tasks = rules.status_callback_tasks_for_callback(callback.callback_id)
        intents = [i for i in rules.queue_intents_for_callback(callback.callback_id)
                   if i.action_ref_or_ability_name == _COUNTER]
        roots = [t for t in tasks if not t.parent_task_id and t.opcode == "PredicateTaskList"]
        if len(intents) != 1 or len(roots) != 1:
            return ctx.services.block("lieutenant_counter_source_shape_changed")
        queue_task = next(t for t in tasks if t.task_id == intents[0].source_task_id)
        guards = [t for t in tasks if t.parent_task_id == queue_task.parent_task_id
                  and t.opcode == "DefineDynamicValue"]
        if len(guards) != 1:
            return ctx.services.block("lieutenant_counter_guard_missing")
        ctx.services.execute_status_tasks(unit.unit_id, _STANCE, _EVENT,
            (guards[0].task_id, queue_task.task_id), roots[0].task_id, ctx.event)
        return ctx.services.finish()
