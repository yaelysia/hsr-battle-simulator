"""Runnable checks for marked assumptions; these are not game evidence."""
from dataclasses import replace
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core.core.model import BattleState, UnitState
from simulator_v8_clean_core.core.settlement import SettlementRecord
from simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator
from simulator_v8_clean_core.rules.expression_ir import CONDITION_EXPRESSION_NODE_SCHEMA
from simulator_v8_clean_core.rules.ir import ConditionIR, IRSource, TargetExpressionNodeIR
from simulator_v8_clean_core.tbgd.lowering import _status_callback_task_admission
from simulator_v8_ui.report import process_notice_records
from simulator_v8_clean_core.session import rule_assumption_records
from simulator_v8_clean_core.cli import _show_state


def test_turn_identity_uses_committed_owner_and_not_stale_event_payload():
    state = BattleState(units={'a': UnitState('a', 'ally', 'fixture'),
                              'b': UnitState('b', 'enemy', 'fixture')},
                        global_flags={'turn_owner_id': 'a'})
    source = IRSource('fixture', 'condition', 'turn', {'json_path': '$'})
    target = TargetExpressionNodeIR.build('TargetAlias',
        replace(source, raw_id='turn:target', evidence={'json_path': '$.TargetType'}), {'alias': 'Caster'})
    condition = ConditionIR('turn', 'ByIsTurnActionEntity', {'TargetType': target},
                            source, 'executable',
                            CONDITION_EXPRESSION_NODE_SCHEMA)
    context = EvaluationContext(state=state, actor_id='a', event_payload={'turn_owner_id': 'b'})
    evaluator = RuleEvaluator()
    assert evaluator.evaluate_condition(condition, context) is True
    assert evaluator.evaluate_condition(condition, replace(context, actor_id='b')) is False
    assert evaluator.evaluate_condition(condition, replace(context, state=replace(state, global_flags={}))) is None


def test_assumption_is_visible_without_becoming_a_mutation_or_audit_failure():
    record = SettlementRecord(record_type='rule_assumption', source='fixture', process_only=True,
        payload={'assumption_id': 'timing', 'status': '未实证', 'reason': '采用既有回合边界',
                 'todo': '待游戏实测插队边界'}).to_json()
    notices = process_notice_records([record], {})
    assert len(notices) == 1 and notices[0]['category'] == '未实证'
    assert notices[0]['impact'] == '待游戏实测插队边界'
    assert notices[0]['reason'] == '采用既有回合边界'
    assert not record.get('mutation_id')


def test_modifier_perform_abort_only_admits_the_parameterless_shape():
    task = {'$type': 'RPG.GameCore.AbortModifierPhasePerform'}
    assert _status_callback_task_admission('OnPhase1', 'AbortModifierPhasePerform', task) == (
        'blocked', 'source_proven_presentation_only')
    assert _status_callback_task_admission('OnPhase1', 'AbortModifierPhasePerform',
                                         {**task, 'ChangeTurn': True})[1] != 'source_proven_presentation_only'


def test_restored_notices_survive_without_live_steps_and_print_in_cli(capsys):
    record = SettlementRecord(record_type='rule_assumption', source='fixture', process_only=True,
        payload={'assumption_id': 'timing', 'status': '未实证', 'reason': '采用既有回合边界',
                 'todo': '待游戏实测插队边界'}).to_json()
    transition = {'settlement': {'records': [record]}}
    history = [{'kind': 'submit', 'transition': transition},
               {'kind': 'advance', 'transitions': [transition]}]
    assert rule_assumption_records(history) == [record]
    _show_state(SimpleNamespace(state=BattleState(), operations=history, outcome='victory'))
    text = capsys.readouterr().out
    assert text.count('未实证') == 1 and '待游戏实测插队边界' in text
