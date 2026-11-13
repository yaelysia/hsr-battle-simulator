"""衣匠倒计时自毁前保留行迹层数，复用原生离场回调的数值叶。

14c1d18f：1402102文本/参数；MServant_AglaeaServant_Passive.OnBeforeDying。
伤害导致的死亡已走正式濒死流程；静默自毁单独在已入队动作开始时补该行迹。
"""
from ..core.content_hooks import ContentProcessorBase, EventSubscription
from ..core.model import QueueActionStartFact
from ..core.settlement import SettlementRecord


class AglaeaProcessor(ContentProcessorBase):
    content_id = 'avatar:1402'
    version = '0.1.0'

    def subscriptions(self):
        return (EventSubscription(('queue.action.before',), scope='owned_units'),)

    def on_event(self, ctx):
        fact = ctx.event.queue_action_start_fact
        if type(fact) is not QueueActionStartFact or not fact.matches_dispatch(ctx.state, ctx.event):
            return ctx.services.finish()
        entry = fact.source_mutation.metadata['queue_entry']
        if entry['action_or_ability_ref'] != 'Servant_Aglaea_00_PassiveSkill01_ForceKill_Insert':
            return ctx.services.finish()
        unit = ctx.services.unit(fact.actor_id)
        if unit is None or 'modifier:MServant_AglaeaServant_00_AddSpeed' not in unit.statuses:
            return ctx.services.finish()
        modifier = 'MServant_AglaeaServant_Passive'
        callbacks = ctx.services.rules.status_callbacks_for_modifier_event(modifier, 'OnBeforeDying')
        if len(callbacks) != 1:
            return ctx.services.block('aglaea_speed_retention_callback_missing')
        tasks = ctx.services.rules.status_callback_tasks_for_callback(callbacks[0].callback_id)
        predicates = [t for t in tasks if t.condition_id
                      and ctx.services.rules.condition(t.condition_id).opcode == 'BySkillPointActivated']
        leaves = sorted((t for t in tasks if t.opcode in
                         {'DefineDynamicValue', 'SetDynamicValueByModifierValue', 'AddModifier'}), key=lambda t: t.task_index)
        if len(predicates) != 1 or len(leaves) != 3:
            return ctx.services.block('aglaea_speed_retention_leaf_shape_changed')
        ctx.services.execute_status_tasks(unit.unit_id, modifier, 'OnBeforeDying',
            tuple(t.task_id for t in leaves), predicates[0].task_id, ctx.event)
        ctx.services.add_record(SettlementRecord('rule_assumption', self.content_id, process_only=True,
            payload={'assumption_id': 'aglaea_countdown_speed_retention', 'status': '未实证',
                'reason': '倒计时自毁动作开始时，先按行迹原生数值保留速度层数。',
                'todo': '游戏实测倒计时、同一窗口插队与衣匠再召唤时的保留层数顺序。'}).to_json())
        return ctx.services.finish()
