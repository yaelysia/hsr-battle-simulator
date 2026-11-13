"""Guardian Shadow, pinned TBGD 14c1d18f and adopted ordinary battle rules.

https://honkai-star-rail.fandom.com/wiki/Guardian_Shadow (version unspecified):
Thunderstorm Condemnation hits eight times; Tranquil Ban needs another enemy.
The native Skill06 params supply count, damage and Shock. Its first selector
uses TauntOrRandomEnemy with RandomByAggroWhenFail=false; later hits are uniform.
No V1 ally applies Taunt; a present Taunt explicitly blocks this handler.
Skill02's angle calculation only feeds its visual effect; execute its two hits.
"""
from dataclasses import replace

from ..core.content_hooks import ActionHookContext, AvailabilityContext, ContentProcessorBase, EventHookContext, EventSubscription, HookResult
from ..core.model import BattleState, TargetResolution
from ..systems.action_availability import BlockedActionReason
from ..systems.rng import RNGOutcome, RNGRequest, choice_key_for_identity, event_id_for_identity
from ..systems.unit_lifecycle import UnitLifecycleSystem


class GuardianShadowProcessor(ContentProcessorBase):
    content_id = 'monster:8003030'
    version = '0.3.0'
    replaced_status_callbacks = frozenset({('Monster_XP_Elite02_00_Edict01_Self', 'OnAfterBeingAttacked')})
    standalone_body_overrides = ((
        'Monster_XP_Elite02_00_SkillP01_Phase01', 'Monster_XP_Elite02_00_SkillP01_Phase02',
    ),)
    # Remaining body tasks only show the counter and count an achievement.
    standalone_body_leaf_opcodes = ((
        'Monster_XP_Elite02_00_SkillP01_Phase02', ('DamageByAttackProperty',),
    ),)

    def claims_action(self, state: BattleState, action_id: str, action_level: int) -> bool:
        return action_id in {'monster_skill:800303002', 'monster_skill:800303006'}

    def filter_choices(self, ctx: AvailabilityContext) -> AvailabilityContext:
        other_enemy = any(u.unit_id != ctx.actor.unit_id and u.side == ctx.actor.side and u.hp > 0
                          and u.lifecycle_status == 'active' for u in ctx.state.units.values())
        unavailable = {'monster_skill:800303007'}
        if not other_enemy:
            unavailable.add('monster_skill:800303003')
        return replace(ctx, choices=tuple(c for c in ctx.choices if c.action_id not in unavailable),
            blocked=ctx.blocked + tuple(BlockedActionReason('guardian_action_prerequisite_not_met', 'content',
                actor_id=ctx.actor.unit_id, actor_side=ctx.actor.side, action_id=c.action_id,
                action_level=c.action_level) for c in ctx.choices if c.action_id in unavailable))

    def execute_action(self, ctx: ActionHookContext) -> HookResult:
        tasks = tuple(t for t in ctx.services.rules.ability_tasks_for_action(
            ctx.command.action_id, ctx.command.action_level) if t.callback_kind == 'OnStart')
        hits = sorted((t for t in tasks if t.opcode == 'DamageByAttackProperty'), key=lambda t: t.task_path)
        if len(hits) != 2:
            return ctx.services.block('guardian_two_compiled_damage_requests_required')
        if ctx.command.action_id == 'monster_skill:800303002':
            ctx.services.execute_damage_tasks(tuple(t.task_id for t in hits),
                action_definition=ctx.action_definition, target_resolution=ctx.target_resolution)
            return ctx.services.finish(takeover=True)
        actor = ctx.services.unit(ctx.command.actor_id)
        if any('Taunt' in d.get('behavior_flags', ()) for d in actor.flags.get('status_details', ())):
            # Ponytail: V1 has no ally Taunt; a future taunt card must supply the
            # first-hit forced-target rule before this branch can be admitted.
            return ctx.services.block('guardian_barrage_taunt_not_admitted')
        shocks = [t for t in tasks if t.opcode == 'AddModifier' and t.parent_task_id == hits[0].parent_task_id]
        count = ctx.action_definition.param_list[1].get('Value')
        if len(shocks) != 1 or type(count) not in (int, float) or count != 8:
            return ctx.services.block('guardian_barrage_source_params_changed')
        for index in range(int(count)):
            candidates = tuple(target for target in ctx.target_resolution.impact_group
                               if UnitLifecycleSystem().view(ctx.services.state, target).can_receive_damage)
            if not candidates:
                break
            identity = {'decision_scope': 'guardian_barrage', 'decision_index': index,
                        'action_id': ctx.command.action_id, 'actor_id': ctx.command.actor_id,
                        'event_index': ctx.state.event_index}
            rng_type = 'target_random'
            request = RNGRequest(rng_type, 'guardian_barrage_target',
                event_id_for_identity(rng_type, identity, event_index=ctx.state.event_index),
                choice_key_for_identity(rng_type, identity), 'content_processor', ctx.services.state.rng_state,
                'choice', tuple(RNGOutcome(target, {'target_id': target}, weight=1) for target in candidates),
                identity=identity)
            target = ctx.services.resolve_rng(request).selected_outcome_id
            selected = TargetResolution(selected=(target,), impact_group=(target,), primary=target,
                                        legal=candidates, selectable=candidates, reason='content_random_selection')
            ctx.services.execute_damage_tasks((hits[0].task_id,), action_definition=ctx.action_definition,
                target_resolution=selected, execution_key=f'barrage:{index}')
            if UnitLifecycleSystem().view(ctx.services.state, target).can_receive_damage:
                ctx.services.execute_effect_task(shocks[0].task_id, action_definition=ctx.action_definition,
                    target_resolution=selected, execution_key=f'barrage:{index}:shock')
        return ctx.services.finish(takeover=True)

    def subscriptions(self) -> tuple[EventSubscription, ...]:
        return (EventSubscription(('damage.target_attack.after',)),)

    def on_event(self, ctx: EventHookContext) -> HookResult:
        unit = ctx.state.units.get(ctx.event.target_id)
        modifier = 'Monster_XP_Elite02_00_Edict01_Self'
        event = 'OnAfterBeingAttacked'
        if unit is None or unit.template_id != self.content_id or 'modifier:' + modifier not in unit.statuses:
            return ctx.services.finish()
        callbacks = ctx.services.rules.status_callbacks_for_modifier_event(modifier, event)
        if len(callbacks) != 1:
            return ctx.services.block('guardian_tranquil_ban_callback_missing')
        callback = callbacks[0]
        tasks = ctx.services.rules.status_callback_tasks_for_callback(callback.callback_id)
        conditions = [t for t in tasks if t.condition_id and
                      ctx.services.rules.condition(t.condition_id).opcode == 'ByIsContainModifier']
        intents = [i for i in ctx.services.rules.queue_intents_for_callback(callback.callback_id)
                   if i.action_ref_or_ability_name == 'Monster_XP_Elite02_00_SkillP01_Phase01']
        removes = [t for t in tasks if t.opcode == 'RemoveModifier']
        if len(conditions) != 1 or len(intents) != 1 or len(removes) != 1:
            return ctx.services.block('guardian_tranquil_ban_source_shape_changed')
        # Ordinary battle excludes fake-avatar/GridFight attacks and the 8003031
        # variant. Keep the native same-caster ban predicate and queue rules.
        ctx.services.execute_status_tasks(unit.unit_id, modifier, event,
            (intents[0].source_task_id, removes[0].task_id), conditions[0].task_id, ctx.event)
        return ctx.services.finish()
