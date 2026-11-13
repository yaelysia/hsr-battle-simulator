"""景元E0战技：整招回能由处理器负责，战斗行为复用编译任务。

https://srl.keqingmains.com/characters/lightning/jing-yuan （版本未注明）
明确战技回复30能量；固定14c1d18f AvatarSkillConfig120402.SPBase同为30。
原生表现编排只有两笔ModifySPNew(AddRatio=.3)，不能代表整招全部回能。
不执行这两笔，结束时按正式SPBase经L1一次结算；不按观测差额补数值。
数值条件为E0既验构筑（攻击过程中没有充能效率变化）；分段回能时序待实测。
神君创建、加段/加速、随机攻击、重置、控制与退场沿用已有编译路径。
战技两轮Retarget各含三个仅受击表现不同、数值完全相同的命中版本；
按行为清单每轮对每个合法敌人结算一次，倍率仍使用对应编译命中。
"""
from dataclasses import replace
from ..core.content_hooks import ContentProcessorBase
from ..core.model import GameEvent
from ..core.settlement import SettlementRecord


class JingYuanProcessor(ContentProcessorBase):
    content_id = 'avatar:1204'
    version = '0.1.0'

    def claims_action(self, state, action_id, action_level):
        return action_id == 'avatar_skill:120402'

    def execute_action(self, ctx):
        tasks = ctx.services.rules.ability_tasks_for_action(ctx.command.action_id, ctx.command.action_level)
        # These are compiled card task identities, not raw graph interpretation.
        # The fixed source's numeric/effect leaves already carry their bindings.
        body = {t.task_path: t for t in tasks if t.callback_kind == 'OnStart'
                and t.ability_name == 'Avatar_JingYuan_00_Skill02_Phase02'}
        def effect(path):
            ctx.services.execute_effect_task(body[path].task_id, action_definition=ctx.action_definition,
                target_resolution=ctx.target_resolution)
        for index in (1, 2, 3, 6, 7):  # Count, current count binding, display and speed.
            effect(f'OnStart[{index}]')
        ctx.services.execute_damage_tasks((body['OnStart[9]'].task_id,),
            action_definition=ctx.action_definition, target_resolution=ctx.target_resolution)
        for index in (11, 14):
            hit = body[f'OnStart[{index}].formal_branch[0].child[0].formal_branch[0].child[0]']
            for target in ctx.target_resolution.impact_group:
                if ctx.services.unit(target).hp <= 0:
                    continue
                resolution = replace(ctx.target_resolution, primary=target, selected=(target,), impact_group=(target,))
                ctx.services.execute_damage_tasks((hit.task_id,), action_definition=ctx.action_definition,
                    target_resolution=resolution, execution_key=f'skill_round:{index}:{target}')
        if 'character_trace_node:character_data_card:avatar:1204:1204103:1' in ctx.services.unit(
                ctx.command.actor_id).flags.get('selected_trace_node_ids', ()):
            effect('OnStart[17].formal_branch[0].child[0]')
        event = GameEvent('content.skill_energy', source_id=ctx.command.actor_id,
            event_id=f'jingyuan:skill_energy:{ctx.state.event_index}:{ctx.command.actor_id}', process_only=True)
        ctx.services.grant_energy(ctx.command.actor_id, ctx.action_definition.sp_base, event)
        ctx.services.add_record(SettlementRecord(record_type='rule_assumption', source=self.content_id,
            process_only=True, payload={'assumption_id': 'jingyuan_skill_energy_timing', 'status': '未实证',
                'reason': '战技结束时一次结算整招能量；数值使用正式SPBase。',
                'todo': '游戏实测分段回能时点，尤其攻击过程中充能效率变化的情况。'}).to_json())
        return ctx.services.finish(takeover=True)
