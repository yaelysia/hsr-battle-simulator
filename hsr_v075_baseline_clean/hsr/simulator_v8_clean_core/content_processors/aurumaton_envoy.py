"""金人勾魂使：先技能文本行为清单，再绑定固定 TBGD 14c1d18f 参数。

剖判单攻；镇魂施加震荡；后续攻击将震荡升级为强烈震荡并推迟行动；
转阴阳群攻并施加震荡；拘魂令锁定强烈震荡目标，下次行动天坠；
天坠仅在锁定目标仍强烈震荡时追加伤害并解除它，净化后用无追加变体。
数值与状态由原编译任务执行；AI 的动作轮转不由模拟器代选。
固定来源 Monster_W2_Valkyrie02_00_{Ability,AI} 与共享 MCommon_Shake。
未实证：以已提交回合归属解释插队中的锁定时机；AbortModifierPhasePerform
只中断状态表现，控制与持续时间仍由行为旗标、生命周期执行。需游戏验证。
"""
from dataclasses import replace

from ..core.content_hooks import AvailabilityContext, ContentProcessorBase, EventHookContext, EventSubscription
from ..core.settlement import SettlementRecord
from ..systems.action_availability import BlockedActionReason
from ..systems.rng import RNGOutcome, RNGRequest, choice_key_for_identity, event_id_for_identity


_LOCK = 'MMonster_W2_Valkyrie02_00_Skill04_Target'


def _locked_targets(state, actor_id):
    return tuple(u.unit_id for u in state.units.values() if u.hp > 0 and u.lifecycle_status == 'active'
                 and any(d.get('modifier_name') == _LOCK and d.get('caster_id') == actor_id
                         for d in u.flags.get('status_details', ())))


class AurumatonEnvoyProcessor(ContentProcessorBase):
    content_id = 'monster:2013020'
    version = '0.4.0'
    standalone_body_overrides = ((
        'Monster_W2_Valkyrie02_00_Skill04_Insert_Phase01',
        'Monster_W2_Valkyrie02_00_Skill04_Insert_Phase02',
    ),)

    def claims_action(self, state, action_id, action_level):
        return action_id == 'monster_skill:201302004'

    def execute_action(self, ctx):
        # SkillAbilityList catalogs the separate lock insertion as well. Only
        # EntryAbility's ordinary damage body belongs to this submitted action.
        tasks = sorted((t for t in ctx.services.rules.ability_tasks_for_action(
            ctx.command.action_id, ctx.command.action_level)
            if t.ability_name == 'Monster_W2_Valkyrie02_00_Skill04_Phase02'
            and t.callback_kind == 'OnStart' and not t.parent_task_id
            and t.opcode in {'DamageByAttackProperty', 'RemoveModifier', 'DefineDynamicValue'}),
            key=lambda t: t.task_index)
        if sum(t.opcode == 'DamageByAttackProperty' for t in tasks) != 5:
            return ctx.services.block('envoy_skyfall_five_hits_required')
        for task in tasks:
            if task.opcode == 'DamageByAttackProperty':
                ctx.services.execute_damage_tasks((task.task_id,), action_definition=ctx.action_definition,
                                                  target_resolution=ctx.target_resolution)
            else:
                ctx.services.execute_effect_task(task.task_id, action_definition=ctx.action_definition,
                                                 target_resolution=ctx.target_resolution)
        return ctx.services.finish(takeover=True)

    def filter_choices(self, ctx: AvailabilityContext) -> AvailabilityContext:
        locked = _locked_targets(ctx.state, ctx.actor.unit_id)
        special = {'monster_skill:201302004', 'monster_skill:201302006'}
        if locked:
            shaken = any('modifier:MCommon_Shake' in ctx.state.units[t].statuses for t in locked)
            allowed = {'monster_skill:201302004' if shaken else 'monster_skill:201302006'}
        else:
            allowed = {c.action_id for c in ctx.choices} - special
        rejected = tuple(c for c in ctx.choices if c.action_id not in allowed)
        return replace(ctx, choices=tuple(c for c in ctx.choices if c.action_id in allowed),
            blocked=ctx.blocked + tuple(BlockedActionReason('envoy_lock_prerequisite_not_met', 'content',
                actor_id=ctx.actor.unit_id, actor_side=ctx.actor.side, action_id=c.action_id,
                action_level=c.action_level) for c in rejected))

    def filter_target_candidates(self, state, actor, action_id, action_level, candidates):
        if action_id in {'monster_skill:201302004', 'monster_skill:201302006'}:
            locked = _locked_targets(state, actor.unit_id)
            require_shake = action_id == 'monster_skill:201302004'
            return tuple(t for t in candidates if t in locked and
                         ('modifier:MCommon_Shake' in state.units[t].statuses) == require_shake)
        return candidates

    def subscriptions(self):
        return (EventSubscription(('action.window.before_skill_use', 'damage.target_attack.after')),)

    def on_event(self, ctx: EventHookContext):
        actor = ctx.services.unit(ctx.event.source_id)
        if (actor is None or actor.template_id != self.content_id or ctx.event.event_type not in
                {'action.window.before_skill_use', 'damage.target_attack.after'}):
            return ctx.services.finish()
        ctx.services.add_record(SettlementRecord(
            record_type='rule_assumption', source=self.content_id, process_only=True,
            payload={'assumption_id': 'envoy_lock_timing', 'status': '未实证',
                     'reason': '自身攻击产生强烈震荡时，在受击后回调结束时锁定；插队锁定按已提交回合归属判断。状态阶段中止仅影响表现。',
                     'todo': '游戏实测：插队引发强烈震荡、锁定后净化、强烈震荡到期与行动恢复顺序。'},
        ).to_json())
        if ctx.event.event_type != 'damage.target_attack.after' or _locked_targets(ctx.state, actor.unit_id):
            return ctx.services.finish()
        flags = {flag for d in actor.flags.get('status_details', ()) for flag in d.get('behavior_flags', ())}
        if actor.hp <= 0 or flags & {'STAT_CTRL', 'DisableAction', 'Break'}:
            return ctx.services.finish()
        candidates = tuple(u.unit_id for u in ctx.services.state.units.values()
            if u.side != actor.side and u.hp > 0 and u.lifecycle_status == 'active'
            and 'modifier:MCommon_Shake' in u.statuses)
        if not candidates:
            return ctx.services.finish()
        identity = {'decision_scope': 'envoy_lock', 'decision_index': 0, 'actor_id': actor.unit_id,
                    'derived_event_id': ctx.event.event_id or str(ctx.event.to_json()['event_id']),
                    'event_id': ctx.event.event_id, 'event_index': ctx.state.event_index}
        kind = 'target_random'
        selected = ctx.services.resolve_rng(RNGRequest(kind, 'envoy_lock_target',
            event_id_for_identity(kind, identity, event_index=ctx.state.event_index),
            choice_key_for_identity(kind, identity), 'content_processor', ctx.services.state.rng_state,
            'choice', tuple(RNGOutcome(t, {'target_id': t}, weight=1) for t in candidates),
            identity=identity)).selected_outcome_id
        # Source Retarget selects one random shaken enemy. Reuse its compiled
        # lock modifiers; the presentation-only inserted ability costs no AV.
        graphs = ctx.services.rules.standalone_ability_graphs_by_name('Monster_W2_Valkyrie02_00_Skill04_Insert_Phase02')
        if len(graphs) != 1:
            return ctx.services.block('envoy_lock_body_missing')
        effects = [ctx.services.rules.effect(task.effect_id)
                   for task_id in graphs[0].task_ids
                   for task in [ctx.services.rules.ability_task(task_id)]
                   if task is not None and task.opcode == 'AddModifier']
        for name, target in ((_LOCK, selected), ('MMonster_W2_Valkyrie02_00_DynamicAI_ToastAndEffect', actor.unit_id)):
            matches = [e for e in effects if e is not None and e.payload.get('standard', {}).get('modifier_name') == name]
            if len(matches) != 1:
                return ctx.services.block('envoy_lock_modifier_missing')
            ctx.services.apply_status_effect(matches[0].effect_id, caster_id=actor.unit_id, target_id=target)
        for detail in ctx.services.unit(actor.unit_id).flags.get('status_details', ()):
            if detail.get('modifier_name') == 'OneMorePerTurn':
                ctx.services.remove_status(actor.unit_id, detail)
        return ctx.services.finish()
