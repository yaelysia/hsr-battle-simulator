from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState, GameEvent
from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, ConditionIR, IRSource
from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator, CONDITION_EXPRESSION_NODE_SCHEMA


def test_regarded_follow_up_preserves_basic_but_does_not_reclassify_real_follow_up():
    source = IRSource('fixture', 'classification', 'attack')
    actor = UnitState('actor', 'ally', 'fixture', flags={'regard_attack_types': {'Normal': 'Insert'}})
    state = BattleState(units={'actor': actor})
    action = ActionDefinitionIR('basic', 'basic', 1, 'Normal', 'Normal', 'single',
        0, 0, 0, 0, (), (), (), 'Fire', source, coverage_status='executable')
    event = GameEvent('damage.hit_sequence.before', source_id='actor', action_definition=action)
    context = EvaluationContext(state=state, actor_id='actor', trigger_event=event, event_payload={'AttackType': 'Insert'})
    evaluator = RuleEvaluator()
    def matches(kind, current=context):
        condition = ConditionIR('type:'+kind, 'ByAttackType', {'AttackTypes': [kind]}, source,
            coverage_status='executable', expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)
        return evaluator.evaluate_condition(condition, current)
    assert matches('Normal') is True and matches('Insert') is True
    assert matches('BPSkill') is False
    genuine = replace(context, trigger_event=replace(event, action_definition=replace(action, attack_type='Insert')))
    assert matches('Normal', genuine) is False and matches('Insert', genuine) is True
    unrelated = replace(context, state=replace(state, units={'actor': replace(actor, flags={})}))
    assert matches('Normal', unrelated) is False
