"""An activated technique has an owner and a single entry wave."""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState
from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator, EvaluationContext, CONDITION_EXPRESSION_NODE_SCHEMA
from hsr.simulator_v8_clean_core.rules.ir import ConditionIR, IRSource


def test_technique_scope_does_not_leak_to_another_actor_or_wave():
    condition = ConditionIR('technique', 'ByIsMazeSkillAffectCurrentWave', {},
        IRSource('fixture', 'condition', 'technique'), coverage_status='executable',
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)
    state = BattleState(global_flags={'initial_technique_waves': {'actor': 0}})
    evaluator = RuleEvaluator()
    context = EvaluationContext(state=state, actor_id='actor')
    assert evaluator.evaluate_condition(condition, context) is True
    assert evaluator.evaluate_condition(condition, replace(context, actor_id='other')) is False
    assert evaluator.evaluate_condition(condition, replace(context, state=replace(state, wave_index=1))) is False
    assert evaluator.evaluate_condition(condition, replace(context, state=BattleState())) is False
