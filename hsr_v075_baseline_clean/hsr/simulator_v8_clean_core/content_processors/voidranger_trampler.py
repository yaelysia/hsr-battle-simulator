"""虚卒·践踏者，固定 TBGD 14c1d18f，普通 8013010 变体。

技能文本清单：两种单攻、扩散、锁定、下次对锁定目标强攻并施加纠缠。
Monster_AML_Elite01_00 的 Skill04/05：只保留蓄力、目标标记、伤害、纠缠
和清理；投射物/镜头/动画不参与回合制结算。Endurance 被击破移除。
伤害、概率、延迟和纠缠参数全部来自该卡编译任务，不在处理器重写。
"""
from dataclasses import replace

from ..core.content_hooks import ContentProcessorBase
from ..systems.action_availability import BlockedActionReason


_AIM = 'MMonster_AML_Elite01_00_Aim'
_CHARGE = 'Monster_AML_Elite01_00_Endurance'


class VoidrangerTramplerProcessor(ContentProcessorBase):
    content_id = 'monster:8013010'
    version = '0.1.0'

    def claims_action(self, state, action_id, action_level):
        return action_id in {'monster_skill:801301004', 'monster_skill:801301005'}

    def filter_choices(self, ctx):
        charged = 'modifier:' + _CHARGE in ctx.actor.statuses
        allowed = ({'monster_skill:801301005'} if charged else
                   {f'monster_skill:80130100{i}' for i in (1, 2, 3, 4)})
        rejected = tuple(c for c in ctx.choices if c.action_id not in allowed)
        return replace(ctx, choices=tuple(c for c in ctx.choices if c.action_id in allowed),
            blocked=ctx.blocked + tuple(BlockedActionReason('trampler_charge_prerequisite_not_met', 'content',
                actor_id=ctx.actor.unit_id, actor_side=ctx.actor.side, action_id=c.action_id,
                action_level=c.action_level) for c in rejected))

    def filter_target_candidates(self, state, actor, action_id, action_level, candidates):
        if action_id == 'monster_skill:801301005':
            return tuple(t for t in candidates if any(d.get('modifier_name') == _AIM and
                d.get('caster_id') == actor.unit_id for d in state.units[t].flags.get('status_details', ())))
        return candidates

    def execute_action(self, ctx):
        tasks = ctx.services.rules.ability_tasks_for_action(ctx.command.action_id, ctx.command.action_level)
        if ctx.command.action_id == 'monster_skill:801301004':
            for name, target in ((_CHARGE, ctx.command.actor_id), (_AIM, ctx.target_resolution.primary)):
                matches = [ctx.services.rules.effect(t.effect_id) for t in tasks if t.opcode == 'AddModifier'
                           and ctx.services.rules.effect(t.effect_id).payload.get('standard', {}).get('modifier_name') == name]
                if len(matches) != 1:
                    return ctx.services.block('trampler_charge_source_changed')
                ctx.services.apply_status_effect(matches[0].effect_id, caster_id=ctx.command.actor_id, target_id=target)
            return ctx.services.finish(takeover=True)
        hits = tuple(t.task_id for t in tasks if t.opcode == 'DamageByAttackProperty')
        entangle = [t for t in tasks if t.opcode == 'AddModifier' and
                    ctx.services.rules.effect(t.effect_id).payload.get('standard', {}).get('modifier_name') == 'MCommon_Entangle']
        if len(hits) != 1 or len(entangle) != 1:
            return ctx.services.block('trampler_charged_shot_source_changed')
        ctx.services.execute_damage_tasks(hits, action_definition=ctx.action_definition,
                                          target_resolution=ctx.target_resolution)
        # Source predicate excludes only the unselected 8013012 variant.
        if ctx.services.unit(ctx.target_resolution.primary).hp > 0:
            ctx.services.execute_effect_task(entangle[0].task_id, action_definition=ctx.action_definition,
                                             target_resolution=ctx.target_resolution)
        for unit in tuple(ctx.services.state.units.values()):
            for detail in unit.flags.get('status_details', ()):
                if (detail.get('modifier_name') in {_AIM, _CHARGE}
                        and detail.get('caster_id') == ctx.command.actor_id):
                    ctx.services.remove_status(unit.unit_id, detail)
        return ctx.services.finish(takeover=True)
