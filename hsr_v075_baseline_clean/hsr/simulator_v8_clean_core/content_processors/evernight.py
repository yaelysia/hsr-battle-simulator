"""长夜月的原生协议适配；数值和状态结算仍由已编译任务负责。

14c1d18f HPChange.OnHPChange 明确要求 ParamValue < 0。L1 的治疗事实只能
产生非负生命变化，故不再需要原生 Before/AfterBeingHeal 的临时 isHeal 标记。
Night 的普通/强化动作由 TriggerNormal 原生回调写入 basic 控制槽。
"""
from dataclasses import replace
from ..core.content_hooks import ContentProcessorBase, EventSubscription
from ..core.settlement import SettlementRecord
from ..systems.action_availability import BlockedActionReason


class EvernightProcessor(ContentProcessorBase):
    content_id = 'avatar:1413'
    version = '0.4.0'
    replaced_status_callbacks = frozenset({
        ('MAvatar_Evernight_00_HPChange', 'OnBeforeBeingHeal'),
        ('MAvatar_Evernight_00_HPChange', 'OnAfterBeingHeal'),
    })

    def subscriptions(self):
        return (EventSubscription(('action.window.after_skill_use',)),)

    def on_event(self, ctx):
        ctx.services.add_record(SettlementRecord('rule_assumption', self.content_id, process_only=True,
            payload={'assumption_id': 'evernight_party_count_alive_boundary', 'status': '未实证',
                'reason': '行迹按队伍中的记忆角色计数；来源省略AliveOnly，暂将倒下但未移除的队友计入，不计忆灵。',
                'todo': '游戏实测记忆队友倒下后，长夜月战技的队伍人数档位是否改变；倍率仍使用正式行迹参数。'}).to_json())
        return ctx.services.finish()


class NightProcessor(ContentProcessorBase):
    content_id = 'servant:11413'
    version = '0.1.0'
    replaced_status_callbacks = EvernightProcessor.replaced_status_callbacks

    def filter_choices(self, ctx):
        trigger = ctx.actor.flags.get('control_skill_mappings', {}).get('basic', 'Skill01')
        selected = {'Skill01': 'servant_skill:1141301', 'Skill11': 'servant_skill:1141307'}.get(trigger)
        rejected = tuple(c for c in ctx.choices if c.choice_kind in {'normal_action', 'summon_action'} and c.action_id != selected)
        return replace(ctx, choices=tuple(c for c in ctx.choices if c not in rejected),
            blocked=ctx.blocked + tuple(BlockedActionReason('night_control_action_replaced', 'content',
                actor_id=ctx.actor.unit_id, actor_side=ctx.actor.side, action_id=c.action_id,
                action_level=c.action_level) for c in rejected))
