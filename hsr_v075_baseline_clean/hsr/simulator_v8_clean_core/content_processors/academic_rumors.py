"""学院怪谈（30146），固定 TBGD 14c1d18f 的内容专属环境处理器。

清单：终结技/追击增伤；每次施放积攒一段（上限取参数）；轮开始按段数
随机选敌，以目标 BaseHP 和该等级类别倍率造成真实伤害，随后清零段数。
参数来自 L0；伤害、RNG、时间线、出生和失败结算复用 L1。
来源：BattleEventAbility_2.BattleEventAbility_Challenge_Month_46；
GlobalModifier_Common_Specific.MCommon_ChallengeTurnLimit；ChallengeMazeConfig。
未实证：跨波保留未消费段数、重置首轮时长；非入队追击按当前动作合并，
复杂嵌套同名追击的计次仍需游戏实测。入队动作使用正式队列事实分别计次。
"""
from ..core.content_hooks import ContentProcessorBase, EventSubscription
from ..core.model import UnitState, QueueActionStartFact, QueueActionTerminalFact
from ..core.settlement import SettlementRecord
from ..rules.ir import DamageModifierIR, IRSource
from ..rules.expression_ir import numeric_fixed
from ..systems.damage import DamageModifierContribution, DamagePacket, DamageSourceFrame
from ..systems.rng import RNGOutcome, RNGRequest, choice_key_for_identity, event_id_for_identity
from ..systems.timeline import TimelineSystem
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..unit_eligibility import runtime_regarded_attack_type, runtime_unit_is_light_team, runtime_unit_is_dark_team


_CLOCK = 'environment:memory_turbulence'
_SOURCE = IRSource('content_processors/academic_rumors.py', 'adopted_stage_rule', 'academic_rumors',
    {'basis': 'fixed TBGD 14c1d18f BattleEventAbility_Challenge_Month_46; parameters compiled by L0'})


class AcademicRumorsProcessor(ContentProcessorBase):
    content_id = 'system_entity:level'
    version = '0.1.0'

    def subscriptions(self):
        return (EventSubscription(('wave.started', 'turn.begin', 'queue.action.before', 'queue.action.after',
                                  'queue.action.abort', 'damage.hit_sequence.before'), scope='battle'),)

    def on_event(self, ctx):
        runtime = ctx.state.global_flags.get('wave_runtime', {})
        definition = ctx.services.rules.wave_definition(runtime.get('wave_definition_id', ''))
        data = definition.stage_environment_data if definition is not None else {}
        if not data:
            return ctx.services.finish()
        if data['event_id'] != '30146':
            return ctx.services.block('academic_rumors_environment_identity_mismatch')
        event = ctx.event
        if event.event_type == 'wave.started':
            rule, reason = ctx.services.rules.select_timeline_rule()
            if rule is None:
                return ctx.services.block(reason)
            av = TimelineSystem().full_action_value(data['speed'], rule) * (1 + data['initial_delay_ratio'])
            if ctx.services.unit(_CLOCK) is None:
                ctx.services.spawn_unit(UnitState(_CLOCK, 'summon', 'battle_event:' + data['event_id'],
                    hp=data['base_hp'], max_hp=data['base_hp'], speed=data['speed'], action_value=av,
                    resources={'stage_hits': 0, 'cycles_used': ctx.state.global_flags.get('challenge_cycles_used', 0)},
                    flags={'entity_type': 'battle_event', 'battle_event_kind': 'AbyssTurnCountDownEvent',
                        'timeline_admitted': True, 'owner_id': 'level:global', 'summoner_id': 'level:global',
                        'team_side': 'neutral', 'unselectable': True, 'selectable': False,
                        'display_name': '记忆紊流', 'cycle_limit': data['cycle_limit'],
                        'damage_bonus': data['damage_bonus'], 'max_hits': data['max_hits']}),
                    reason='create source-selected challenge environment')
            else:
                ctx.services.set_action_value(_CLOCK, av)
            ctx.services.add_record(SettlementRecord(record_type='rule_assumption', source=self.content_id,
                process_only=True, payload={'assumption_id': 'academic_rumors_wave_boundary', 'status': '未实证',
                    'reason': '换波保留未消费攻击段数，首轮行动值重置；未入队追击按当前动作合并计次。',
                    'todo': '游戏实测跨波段数、首轮顺序和复杂嵌套同名追击；第二半场须承接第一半场已用轮数。'}).to_json())
            return ctx.services.finish()
        clock = ctx.services.unit(_CLOCK)
        if clock is None:
            return ctx.services.finish()
        if event.event_type == 'turn.begin' and event.source_id == _CLOCK:
            return self._cycle(ctx, data)
        actor = ctx.services.unit(event.source_id)
        if actor is None or not runtime_unit_is_light_team(actor):
            return ctx.services.finish()
        pending = dict(clock.flags.get('pending_actions', {}))
        if event.event_type == 'queue.action.before':
            fact = event.queue_action_start_fact
            if type(fact) is not QueueActionStartFact or not fact.matches_dispatch(ctx.state, event):
                return ctx.services.block('stage_queue_start_fact_missing')
            entry = fact.source_mutation.metadata['queue_entry']
            pending[actor.unit_id] = {'entry_id': entry['entry_id'], 'follow_up': False}
            ctx.services.set_unit_flag(_CLOCK, 'pending_actions', pending, reason='track accepted queued action')
        elif event.event_type in {'queue.action.after', 'queue.action.abort'}:
            fact = event.queue_action_terminal_fact
            if type(fact) is not QueueActionTerminalFact or not fact.matches(ctx.state, event):
                return ctx.services.block('stage_queue_terminal_fact_missing')
            current = pending.pop(actor.unit_id, None)
            entry = fact.source_mutation.metadata['queue_entry']
            if current is not None and current['entry_id'] != entry['entry_id']:
                return ctx.services.block('stage_queue_completion_identity_mismatch')
            command = fact.completed_command
            action = ctx.services.rules.action_definition(command.action_id, command.action_level) if command else None
            if event.event_type == 'queue.action.after' and (
                    action is not None and runtime_regarded_attack_type(actor, action.attack_type) == 'Ultra'
                    or current is not None and current['follow_up']):
                self._charge(ctx, data, actor.unit_id)
            ctx.services.set_unit_flag(_CLOCK, 'pending_actions', pending, reason='finish accepted queued action')
        elif event.event_type == 'damage.hit_sequence.before' and event.action_definition is not None:
            attack_type = runtime_regarded_attack_type(actor, event.action_definition.attack_type)
            if attack_type not in {'Ultra', 'Insert'}:
                return ctx.services.finish()
            bonus = float(data['damage_bonus'])
            modifier = DamageModifierIR('academic_rumors:damage_bonus', 'content:academic_rumors',
                'content:academic_rumors:before_hit', '学院怪谈：终结技与追击增伤', 'OnBeforeHitAll', 'Caster',
                ({'coverage_status': 'executable', 'bucket': 'damage_bonus', 'key': 'damage_added_ratio',
                  'numeric_expr': numeric_fixed(bonus)},), _SOURCE, coverage_status='executable')
            ctx.services.add_damage_modifier(DamageModifierContribution(modifier, 0, bonus))
            if attack_type == 'Insert':
                if actor.unit_id in pending:
                    pending[actor.unit_id] = {**pending[actor.unit_id], 'follow_up': True}
                    ctx.services.set_unit_flag(_CLOCK, 'pending_actions', pending, reason='queued follow-up produced a hit')
                else:
                    last = dict(clock.flags.get('last_direct_follow_up', {}))
                    identity = [ctx.state.event_index, event.action_definition.action_id]
                    if last.get(actor.unit_id) != identity:
                        self._charge(ctx, data, actor.unit_id)
                        last[actor.unit_id] = identity
                        ctx.services.set_unit_flag(_CLOCK, 'last_direct_follow_up', last, reason='count direct follow-up once')
        return ctx.services.finish()

    def _charge(self, ctx, data, actor_id):
        before = ctx.services.unit(_CLOCK).resources['stage_hits']
        after = min(data['max_hits'], before + data['hits_per_action'])
        mutation = ctx.services.set_unit_resource(_CLOCK, 'stage_hits', after, reason='charge memory turbulence')
        ctx.services.add_record(SettlementRecord(record_type='stage_hit_charge', source=self.content_id,
            mutation_id=mutation.stable_id(), process_only=False,
            payload={'actor_id': actor_id, 'before': before, 'after': after, 'maximum': data['max_hits']}).to_json())

    def _cycle(self, ctx, data):
        clock = ctx.services.unit(_CLOCK)
        used = int(clock.resources['cycles_used']) + 1
        ctx.services.set_unit_resource(_CLOCK, 'cycles_used', used, reason='advance challenge cycle')
        if used >= data['cycle_limit']:
            ctx.services.request_battle_defeat('source challenge cycle budget exhausted')
            return ctx.services.finish()
        count = int(clock.resources['stage_hits'])
        ctx.services.set_unit_resource(_CLOCK, 'stage_hits', 0, reason='consume memory turbulence hits')
        for index in range(count):
            candidates = tuple(u.unit_id for u in ctx.services.state.units.values()
                if runtime_unit_is_dark_team(u) and UnitLifecycleSystem().view(ctx.services.state, u.unit_id).can_receive_damage)
            if not candidates:
                break
            identity = {'decision_scope': 'memory_turbulence', 'decision_index': index,
                        'action_id': 'battle_event:' + data['event_id'], 'cycle': used, 'wave': ctx.state.wave_index,
                        'event_index': ctx.state.event_index}
            kind = 'target_random'
            target = ctx.services.resolve_rng(RNGRequest(kind, 'memory_turbulence_target',
                event_id_for_identity(kind, identity, event_index=ctx.state.event_index), choice_key_for_identity(kind, identity),
                'content_processor', ctx.services.state.rng_state, 'choice',
                tuple(RNGOutcome(t, {'target_id': t}, weight=1) for t in candidates), identity=identity)).selected_outcome_id
            unit = ctx.services.unit(target)
            card = ctx.services.rules.monster_data_card_for_entity(unit.template_id)
            if card is None or card.rank not in data['hp_ratios']:
                return ctx.services.block('stage_true_damage_target_rank_not_admitted')
            # BaseHP is the source-scaled base panel, not current HP. Formula
            # routing, shields, HP clamps, defeat and kill ownership stay in L1.
            ctx.services.apply_damage(DamagePacket(attacker_id=_CLOCK, target_id=target, attack_type='TrueDamage',
                damage_formula_family='true_damage', amount=unit.max_hp * data['hp_ratios'][card.rank],
                amount_stage='fixed_final', element_type='Physical', source_trace=_SOURCE.to_json(),
                source_frame=DamageSourceFrame(owner_id=_CLOCK, source_id='content:academic_rumors',
                    source_kind='effect_damage', sequence_id=f'turbulence:{used}:{ctx.state.wave_index}:{index}',
                    target_id=target, source_trace=_SOURCE.to_json())))
        return ctx.services.finish()
