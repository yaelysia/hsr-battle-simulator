"""Native boolean source keys use formal scoped values, never payload guesses."""
from dataclasses import replace
from pathlib import Path
from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry, _binding_sources
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering, _effect_payload, _effect_coverage_status
from hsr.simulator_v8_clean_core.tbgd.named_boolean_source import boolean_opcode


def test_real_boolean_shape_uses_formal_parameter_and_keeps_native_audit():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    source = IRSource('validation_fixture/named-boolean', 'AbilityTask',
        'boolean', {'json_path': '$.CallbackConfig[0]', 'validation_fixture': True})
    target = {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'}
    key = {'RawString': 'Cyrene_TargetCount_{MDF_ID}'}
    write_raw = {'$type': 'DFDELJOIGBJ', 'HILNFHCPEAD': target, 'FHLJGDGMMHK': key, 'EKFIEAALOFF': True}
    read_raw = {'$type': 'AGAGMFCPBED', 'HILNFHCPEAD': target, 'FHLJGDGMMHK': key, 'Inverse': True}
    canonical = boolean_opcode(write_raw['$type'])
    write_payload = _effect_payload(write_raw, canonical, '', source=source)
    assert _effect_coverage_status(canonical, write_payload) == 'executable'
    write = EffectIR('write-flag', canonical, write_payload, source, 'executable')
    value_raw = {'$type': 'RPG.GameCore.SetDynamicValue', 'DynamicKey': 'MDF_ID',
                 'Value': {'IsDynamic': False, 'FixedValue': {'Value': 11}}}
    value = EffectIR('write-id', 'SetDynamicValue', _effect_payload(value_raw, 'SetDynamicValue', '', source=source), source, 'executable')
    rules = RuleBook(CanonicalIR('named-flags', effects=(write, value)))
    runtime = EffectRegistry(StatusSystem(rules))
    state = BattleState(units={name: UnitState(name, 'ally', 'avatar:' + name, hp=10, max_hp=10) for name in ('owner', 'other')})
    def context(current):
        return EffectExecutionContext(current, 'owner', 'callback', owner_id='owner',
            event_payload={'event_id': 'callback', 'operation_event_id': 'callback:write', 'MDF_ID': 999})
    initial = runtime.execute(value, context(state))
    assert not initial.unsupported, initial.unsupported
    state = MutationReducer().apply_all(state, initial.mutations)
    condition = TBGDLowering(root)._lower_ability_task_condition(read_raw, source, 'read-flag')
    assert condition.opcode == 'ByNamedBooleanFlag' and condition.coverage_status == 'executable', condition.to_json()
    evaluator = RuleEvaluator()
    def evaluate(current):
        return evaluator.evaluate_condition(condition, EvaluationContext(state=current, actor_id='owner', owner_id='owner',
            binding_sources=_binding_sources(context(current)), event_payload={'MDF_ID': 999}))
    assert evaluate(state) is True
    written = runtime.execute(write, context(state))
    assert not written.unsupported, written.unsupported
    assert RuntimeSourceAuditor(rules).validate_execution(written.mutations, written.records).ok
    after = MutationReducer().apply_all(state, written.mutations)
    assert after.units['owner'].flags['named_boolean_flags'] == {'Cyrene_TargetCount_11': True}
    assert after.units['other'] == state.units['other'] and evaluate(after) is False
    missing = replace(state, global_flags={})
    blocked = runtime.execute(write, context(missing))
    assert blocked.unsupported and not blocked.mutations and not blocked.rng_events
    forged = replace(written.mutations[0], effect_execution_fact=None, metadata={'effect_id': 'write-id'})
    assert not RuntimeSourceAuditor(rules).validate_execution((forged,), written.records).ok
    ancestor = replace(forged, path=('units', 'owner', 'flags'), before=state.units['owner'].flags,
        after={**state.units['owner'].flags, 'named_boolean_flags': {'Cyrene_TargetCount_11': True}}, before_exists=True)
    assert not RuntimeSourceAuditor(rules).validate_execution((ancestor,), written.records).ok
    malformed = _effect_payload({**write_raw, 'UnknownGameplay': True}, canonical, '', source=source)
    assert _effect_coverage_status(canonical, malformed) == 'blocked'
