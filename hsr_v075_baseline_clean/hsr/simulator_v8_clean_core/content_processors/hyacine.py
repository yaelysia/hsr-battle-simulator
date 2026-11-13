"""风堇治疗累计的边界解释；不另写伤害或治疗数值。

技能文本未明确满血/溢出边界。沿用 L1 已提交的实际回血量作为累计值，
明确标为未实证；后续实测若包含溢出，改接治疗 producer 的总治疗量事实。
"""
from ..core.content_hooks import ContentProcessorBase, EventSubscription
from ..core.settlement import SettlementRecord


class HyacineProcessor(ContentProcessorBase):
    content_id = 'avatar:1409'
    version = '0.1.0'

    def subscriptions(self):
        return (EventSubscription(('action.window.after_skill_use',)),)

    def on_event(self, ctx):
        ctx.services.add_record(SettlementRecord('rule_assumption', self.content_id, process_only=True,
            payload={'assumption_id': 'hyacine_heal_tally_boundary', 'status': '未实证',
                'reason': '累计治疗暂按实际恢复的生命值统计，满血治疗与溢出部分不计入；数值由现有治疗结算产生。',
                'todo': '游戏实测满血和溢出治疗是否计入小伊卡累计治疗、是否触发其治疗增伤；若计入，改接总治疗量事实。'}).to_json())
        return ctx.services.finish()
