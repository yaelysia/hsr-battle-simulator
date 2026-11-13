"""托帕E0：己方回合/行动开始时，没有负债证明则随机补一个。

固定14c1d18f技能111202文本与原生Passive_Sub_ListenAction回调；
https://hsr.keqingmains.com/topaz-and-numby/ （适用版本未注明）。
使用已编译战技的负债证明，参数/易伤/移除旧标记由L1状态系统处理。
该卡独有的回调别名映射到公共回合/动作窗口，不扩展整套原生回调协议。
"""
from ..core.content_hooks import ContentProcessorBase, EventSubscription
from ..core.settlement import SettlementRecord
from ..systems.rng import RNGOutcome, RNGRequest, choice_key_for_identity, event_id_for_identity
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..unit_eligibility import runtime_unit_is_light_team, runtime_unit_is_dark_team


_MARK = 'MAvatar_Topaz_BETargetTag'


class TopazProcessor(ContentProcessorBase):
    content_id = 'avatar:1112'
    version = '0.1.0'

    def subscriptions(self):
        return (EventSubscription(('turn.begin', 'action.window.before_skill_use', 'queue.action.before'), scope='battle'),)

    def on_event(self, ctx):
        actor = ctx.services.unit(ctx.event.source_id)
        if actor is None or not runtime_unit_is_light_team(actor):
            return ctx.services.finish()
        owners = [u for u in ctx.state.units.values() if u.template_id == self.content_id
                  and UnitLifecycleSystem().view(ctx.state, u.unit_id).is_active]
        for owner in owners:
            candidates = tuple(u.unit_id for u in ctx.services.state.units.values()
                if runtime_unit_is_dark_team(u) and UnitLifecycleSystem().view(ctx.services.state, u.unit_id).can_receive_damage)
            if not candidates or any(d.get('modifier_name') == _MARK and d.get('caster_id') == owner.unit_id
                for target in candidates for d in ctx.services.unit(target).flags.get('status_details', ())):
                continue
            level = owner.flags['effective_skill_levels_by_action_id']['avatar_skill:111202']
            effects = [ctx.services.rules.effect(t.effect_id) for t in ctx.services.rules.ability_tasks_for_action(
                'avatar_skill:111202', level) if t.opcode == 'AddModifier' and t.effect_id]
            marks = [e for e in effects if e.payload.get('standard', {}).get('modifier_name') == _MARK]
            if len(marks) != 1:
                return ctx.services.block('topaz_debt_effect_missing_or_ambiguous')
            identity = {'decision_scope': 'topaz_auto_debt', 'action_id': 'content:topaz_auto_debt', 'actor_id': owner.unit_id,
                'event_index': ctx.state.event_index, 'event_id': ctx.event.event_id, 'decision_index': 0}
            kind = 'target_random'
            target = ctx.services.resolve_rng(RNGRequest(kind, 'topaz_auto_debt',
                event_id_for_identity(kind, identity, event_index=ctx.state.event_index), choice_key_for_identity(kind, identity),
                'content_processor', ctx.services.state.rng_state, 'choice',
                tuple(RNGOutcome(t, {'target_id': t}, weight=1) for t in candidates), identity=identity)).selected_outcome_id
            ctx.services.apply_status_effect(marks[0].effect_id, caster_id=owner.unit_id, target_id=target,
                                            execution_key=ctx.event.event_id)
            ctx.services.add_record(SettlementRecord(record_type='rule_assumption', source=self.content_id,
                process_only=True, payload={'assumption_id': 'topaz_debt_window', 'status': '未实证',
                    'reason': '在己方回合或行动开始窗口补齐缺失的负债证明。',
                    'todo': '游戏实测回合初持续伤害、敌人阵亡、插队准备与补标记的先后顺序。'}).to_json())
        return ctx.services.finish()
