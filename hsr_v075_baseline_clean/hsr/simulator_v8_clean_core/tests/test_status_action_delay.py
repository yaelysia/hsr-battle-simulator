"""A pinned two-parameter normalized delay uses the shared numeric resolver."""

import json
import math
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import (
    ENGINE_RULE_REGISTRY_VERSION, TIMELINE_RULE_APPLICABILITY,
)
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hash, numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR, IRSource, StatusCallbackIR, StatusCallbackTaskIR, TimelineRuleIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _action_delay_emission_from_task, _status_callback_runtime_payload,
    _status_callback_task_admission,
)


def test_real_normalized_delay_resolves_both_hashes_and_failure_is_atomic():
    relative = 'Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json'
    document = json.loads((Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main' / relative).read_text())
    raw = document['ModifierMap']['MCommon_Element_Entangle']['_CallbackList'][2]['CallbackConfig'][3]
    assert raw['$type'] == 'RPG.GameCore.ModifyActionDelay'
    assert _status_callback_task_admission('OnStack', 'ModifyActionDelay', raw) == ('executable', '')
    assert _status_callback_task_admission('OnStack', 'ModifyActionDelay', {**raw, 'Unknown': True})[0] == 'blocked'
    source = IRSource(relative, 'ModifyActionDelay', 'test:delay', {
        'json_path': '$.ModifierMap.MCommon_Element_Entangle._CallbackList[2].CallbackConfig[3]',
    })
    callback = StatusCallbackIR('test:delay:callback', 'test:status', 'OnStack',
        ('test:delay:task',), source, (0, 0), coverage_status='executable', admission_status='executable')
    task = StatusCallbackTaskIR('test:delay:task', callback.callback_id, callback.modifier_name,
        callback.event, 0, 'CallbackConfig[3]', 'root', 'ModifyActionDelay', source,
        coverage_status='executable', task_payload=_status_callback_runtime_payload(raw))
    emission = _action_delay_emission_from_task(callback_id=callback.callback_id,
        task_id=task.task_id, modifier_name=callback.modifier_name, event=callback.event,
        opcode=task.opcode, task=raw, source=source)
    assert emission.coverage_status == 'executable', emission.blocked_reason
    # A shared template inherits its importing callback's admitted source;
    # its original file remains available for audit.
    imported = replace(source, source_path='Config/ConfigTaskListTemplate/Shared.json',
        evidence={**source.evidence, 'admission_source_path': relative})
    shared = _action_delay_emission_from_task(callback_id=callback.callback_id,
        task_id=task.task_id, modifier_name=callback.modifier_name, event=callback.event,
        opcode=task.opcode, task=raw, source=imported)
    assert shared.coverage_status == 'executable', shared.blocked_reason
    assert shared.source.source_path == imported.source_path
    clock = TimelineRuleIR('test:clock', 10000, 'base_action_gauge_div_speed',
        'base_action_gauge_div_speed', 'engine_convention', IRSource('fixture:clock', 'TimelineRule', 'clock'),
        registry_version=ENGINE_RULE_REGISTRY_VERSION, applicability=TIMELINE_RULE_APPLICABILITY)
    rules = RuleBook(CanonicalIR('test:delay', timeline_rules=(clock,)))
    detail = {'owner_id': 'holder', 'caster_id': 'holder', 'instance_id': 'test:instance',
              'status_id': 'modifier:test:status', 'modifier_name': callback.modifier_name,
              'source_trace': source.to_json(),
              'dynamic_values': {'__by_hash': {'-2109623552': 0.2, '369211422': 0.5}}}
    state = BattleState(units={'holder': UnitState('holder', 'enemy', 'test:holder',
        hp=100, max_hp=100, speed=100, action_value=20,
        statuses=(detail['status_id'],), flags={'status_details': [detail]})})
    system = StatusCallbackSystem(rules)
    result = system._execute_delay_emissions(state, callback, task, detail, None, (emission,))
    assert result.ok, result.errors
    # The raw program is 0.2 * (1 + 0.5), converted using a 100 AV full turn.
    assert math.isclose(result.after_state.units['holder'].action_value, 50)
    assert len(result.mutations) == 1

    missing = replace(emission, delay_expr=numeric_dynamic_hash('fixture:missing'))
    failed = system._execute_delay_emissions(state, callback, task, detail, None, (emission, missing))
    assert not failed.ok and failed.errors
    assert failed.after_state is state and not failed.mutations and not failed.events
    assert all(record.get('process_only') is True for record in failed.records)
    # The existing fixed OnCreate delay remains valid through the same resolver.
    fixed = system._execute_delay_emissions(state, callback, task, detail, None,
        (replace(emission, delay_expr=numeric_fixed(0.25)),))
    assert fixed.ok and math.isclose(fixed.after_state.units['holder'].action_value, 45)
