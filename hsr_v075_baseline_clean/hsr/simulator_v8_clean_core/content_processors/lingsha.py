"""浮元次数耗尽时，先同步次数，再移除计数状态。

固定14c1d18f LifeTime.OnPhase1：_AttackTime减1，并回写灵砂的剩余次数。
原生SetModifierValue的省略减量已在L0按同一回调的明确减1表达式采纳。
L1计数归零会立即移除状态，故将该叶放到同步之后，避免向已移除实例写值。
应急追击按最低血量队友检查一次，避免组目标重复执行入队叶。
不重写伤害、治疗、净化、冷却数值或召唤结算。
"""
from ..core.content_hooks import ContentProcessorBase, EventSubscription
from ..core.settlement import SettlementRecord
from ..core.model import current_max_hp
from ..systems.mutation_events import HPChangeEventFact
from ..unit_eligibility import runtime_units_share_combat_team


_LIFETIME = 'MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime'
_EMERGENCY = 'MAvatar_Lingsha_PointB3_OnListen'


class FuyuanProcessor(ContentProcessorBase):
    content_id = 'battle_event:11222'
    version = '0.3.0'
    replaced_status_callbacks = frozenset({(_LIFETIME, 'OnPhase1'), (_EMERGENCY, 'OnListenHPChange')})

    def subscriptions(self):
        return (EventSubscription(('turn.begin', 'unit.removed')),
                EventSubscription(('hp.change',), scope='battle'))

    def on_event(self, ctx):
        if ctx.event.event_type == 'hp.change':
            return self._emergency(ctx)
        if ctx.event.event_type == 'unit.removed':
            unit = ctx.services.unit(ctx.event.target_id)
            if unit is not None and unit.template_id == self.content_id:
                # The native marker's OnDestroy subtracts Lingsha_BENum.
                # Dispatch the ordinary status removal before a later Skill
                # decides whether to replenish or summon a new Fuyuan.
                for detail in tuple(unit.flags.get('status_details', ())):
                    current = ctx.services.unit(unit.unit_id)
                    live = next((d for d in current.flags.get('status_details', ())
                                 if d['instance_id'] == detail['instance_id']), None)
                    if live is not None:
                        ctx.services.remove_status(unit.unit_id, live)
            return ctx.services.finish()
        unit = ctx.services.unit(ctx.event.source_id)
        if unit is None or unit.template_id != self.content_id or 'modifier:' + _LIFETIME not in unit.statuses:
            return ctx.services.finish()
        callbacks = ctx.services.rules.status_callbacks_for_modifier_event(_LIFETIME, 'OnPhase1')
        if len(callbacks) != 1:
            return ctx.services.block('fuyuan_lifetime_callback_missing')
        tasks = ctx.services.rules.status_callback_tasks_for_callback(callbacks[0].callback_id)
        writes = sorted((t for t in tasks if t.opcode == 'SetDynamicValue'), key=lambda t: t.task_index)
        consume = [t for t in tasks if t.opcode == 'SetModifierValue']
        if len(writes) != 2 or len(consume) != 1:
            return ctx.services.block('fuyuan_lifetime_leaf_shape_changed')
        ctx.services.execute_status_tasks(unit.unit_id, _LIFETIME, 'OnPhase1',
            tuple(t.task_id for t in (*writes, *consume)), None, ctx.event)
        ctx.services.add_record(SettlementRecord(record_type='rule_assumption', source=self.content_id,
            process_only=True, payload={'assumption_id': 'fuyuan_last_action_lifetime', 'status': '未实证',
                'reason': '先同步剩余次数，再移除归零计数状态；最后一次追击沿原队列完成。',
                'todo': '游戏实测浮元最后一次行动、应急追击与补充次数同时发生时的顺序。'}).to_json())
        return ctx.services.finish()

    def _emergency(self, ctx):
        """PointB3: any low-HP teammate causes one emergency Fuyuan attack.

        Fixed TBGD GlobalModifiers PointB3_OnListen gates HP loss and cooldown;
        its inner predicate supplies the 60% threshold and control check. The
        queue leaf has AbilityOwnerInsertUnusedCount=1. Select one qualifying
        teammate rather than expanding these two leaves over the whole team.
        Native Phase02 still applies cooldown, damage, heal and dispel.
        """
        fact = ctx.event.hp_change_event_fact
        if type(fact) is not HPChangeEventFact or not fact.matches_event(ctx.event) or fact.delta >= 0:
            return ctx.services.finish()
        changed = ctx.services.unit(fact.target_id)
        for unit in tuple(ctx.state.units.values()):
            if unit.template_id != self.content_id or unit.lifecycle_status != 'active':
                continue
            if 'modifier:' + _EMERGENCY not in unit.statuses or changed is None:
                continue
            owner = ctx.services.unit(str(unit.flags.get('summoner_id') or ''))
            if owner is None or 'modifier:MAvatar_Lingsha_00_PointB3_CD' in owner.statuses:
                continue
            if not runtime_units_share_combat_team(changed, owner):
                continue
            if any(entry.get('actor_id') == unit.unit_id for queue in ctx.services.state.queues.values()
                   for entry in queue if isinstance(entry, dict)):
                continue
            candidates = [u for u in ctx.services.state.units.values()
                          if runtime_units_share_combat_team(u, owner) and u.lifecycle_status == 'active' and u.hp > 0
                          and u.flags.get('entity_type') != 'battle_event' and current_max_hp(u) > 0]
            if not candidates:
                continue
            target = min(candidates, key=lambda u: (u.hp / current_max_hp(u), u.unit_id))
            callbacks = ctx.services.rules.status_callbacks_for_modifier_event(_EMERGENCY, 'OnListenHPChange')
            if len(callbacks) != 1:
                return ctx.services.block('fuyuan_emergency_callback_missing')
            tasks = ctx.services.rules.status_callback_tasks_for_callback(callbacks[0].callback_id)
            leaves = sorted((t for t in tasks if t.opcode in {'SetDynamicValue', 'TurnInsertAbility'}),
                            key=lambda t: t.task_index)
            predicates = [t for t in tasks if t.condition_id
                          and any(c.get('opcode') == 'ByCompareHPRatio' for c in
                                  ctx.services.rules.condition(t.condition_id).payload.get('PredicateList', ()))]
            if len(leaves) != 2 or len(predicates) != 1:
                return ctx.services.block('fuyuan_emergency_leaf_shape_changed')
            predicate = predicates[0]
            ctx.services.execute_status_tasks(unit.unit_id, _EMERGENCY, 'OnListenHPChange',
                tuple(t.task_id for t in leaves), predicate.task_id, ctx.event,
                parameter_entity_id=target.unit_id)
        return ctx.services.finish()
