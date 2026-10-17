"""One real-source count lifecycle and the same consumer's generic Layer path."""
import json
import re
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem
from hsr.simulator_v8_clean_core.tbgd.adopted_modifier_counts import ADOPTED_MODIFIER_COUNTS, SOURCE
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _effect_payload, _effect_coverage_status, _attach_target_expressions_to_effect_payload,
)


def test_adopted_charging_count_preserves_already_totaled_stat_contributions():
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hashes
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
    from hsr.simulator_v8_clean_core.tbgd.adopted_modifier_counts import ASTA_SOURCE

    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    document = json.loads((root / ASTA_SOURCE).read_text())
    effects = []
    for (path, json_path), rule in ADOPTED_MODIFIER_COUNTS.items():
        if path != ASTA_SOURCE:
            continue
        raw = document
        for token in re.findall(r'[^.\[\]]+', json_path[2:]):
            raw = raw[int(token)] if isinstance(raw, list) else raw[token]
        assert raw == rule['expected_task']
        source = IRSource(path, 'StatusCallbackTask', 'charging', {'json_path': json_path})
        payload = _effect_payload(raw, 'SetModifierValue', '', source=source)
        assert _effect_coverage_status('SetModifierValue', payload) == 'executable'
        effects.append(EffectIR(json_path, 'SetModifierValue', payload, source, 'executable'))
        unrelated = _effect_payload(raw, 'SetModifierValue', '', source=replace(source, source_path='other'))
        assert _effect_coverage_status('SetModifierValue', unrelated) == 'blocked'

    registry = EffectRegistry(StatusSystem(RuleBook(CanonicalIR('charging-count-check', effects=tuple(effects)))))
    for effect in effects[:2]:
        name = effect.payload['standard']['modifier_name']
        detail = StatusInstance('count:1', 'modifier:' + name, name, 'holder', 'source', 'caster',
            max_stacks=1, modifiers=({'bucket': 'attribute', 'key': 'attack_added_ratio', 'value': 0.21},)).to_json()
        state = BattleState(units={
            'holder': UnitState('holder', 'ally', 'fixture:holder', attack=100,
                statuses=(detail['status_id'],), flags={'status_details': [detail]}),
            'caster': UnitState('caster', 'ally', 'fixture:caster'),
        })
        hash_key = str(numeric_dynamic_hashes(effect.payload['standard']['amount'])[0])
        result = registry.execute(effect, EffectExecutionContext(state, 'caster', 'count-check', owner_id='holder',
            dynamic_values={hash_key: 3}, include_ambient_status_bindings=False))
        assert not result.unsupported, result.unsupported
        after = MutationReducer().apply_all(state, result.mutations)
        current = after.units['holder'].flags['status_details'][0]
        assert current['stacks'] == 3 and current['stack_policy'] == 'independent_count'
        assert current['modifiers'] == detail['modifiers']
        assert effective_unit_stat(after.units['holder'], 'attack').value == 121
        assert not any(event.window == 'OnStack' for event in result.events)


def test_selected_nested_stack_property_installs_one_total_contribution():
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hashes
    from hsr.simulator_v8_clean_core.rules.ir import StatusCallbackIR, StatusCallbackTaskIR
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
    from hsr.simulator_v8_clean_core.tbgd.adopted_modifier_counts import ASTA_SOURCE
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _status_callback_runtime_payload, _status_callback_task_admission,
    )

    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    name = 'MAvatar_Asta_00_Passive_Charge'
    modifier = json.loads((root / ASTA_SOURCE).read_text())['GlobalModifiers'][name]
    raw = modifier['_CallbackList'][1]['CallbackConfig'][2]['FailedTaskList'][0]
    assert _status_callback_task_admission('OnStack', 'StackProperty', raw)[0] == 'executable'
    source = IRSource(ASTA_SOURCE, 'StatusCallbackTask', 'selected_property')
    callback = StatusCallbackIR('callback', name, 'OnStack', ('task',), source, (0, 0), 'executable')
    task = StatusCallbackTaskIR('task', 'callback', name, 'OnStack', 0,
        '$.GlobalModifiers.' + name + '._CallbackList[1].CallbackConfig[2].formal_branch[3].child[0]',
        'failed', 'StackProperty', source, coverage_status='executable',
        task_payload=_status_callback_runtime_payload(raw, source_modifier_name=name))
    hashes = numeric_dynamic_hashes(task.task_payload['PropertyValue'])
    detail = StatusInstance('charge:1', 'modifier:' + name, name, 'holder', 'source', 'holder',
        stacks=3, stack_policy='independent_count', dynamic_values={
            '__by_hash': {str(hashes[0]): 0.07, str(hashes[1]): 3},
        }).to_json()
    state = BattleState(units={'holder': UnitState('holder', 'ally', 'fixture:holder', attack=100,
        statuses=(detail['status_id'],), flags={'status_details': [detail]})})
    system = StatusCallbackSystem(RuleBook(CanonicalIR('selected-property',
        status_callbacks=(callback,), status_callback_tasks=(task,))))
    result = system._execute_formal_leaf_task(state, callback, task, detail, None, None)
    assert result.ok, result.errors
    after = result.after_state
    current = after.units['holder'].flags['status_details'][0]
    assert current['stacks'] == 3 and len(current['modifiers']) == 1
    assert effective_unit_stat(after.units['holder'], 'attack').value == 121
    repeated = system._execute_formal_leaf_task(after, callback, task, detail, None, None)
    assert repeated.ok and not repeated.mutations and repeated.after_state == after
    rejected = system._execute_formal_leaf_task(state, callback,
        replace(task, task_payload={**task.task_payload, 'TargetType': 'AllEnemy'}), detail, None, None)
    assert not rejected.ok and not rejected.mutations and rejected.after_state == state


def test_modifier_values_share_generic_mutations_and_explicit_default_adoption():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    effects = {}
    for (path, json_path), rule in ADOPTED_MODIFIER_COUNTS.items():
        if path != SOURCE:
            continue
        raw = json.loads((root / path).read_text())
        for token in re.findall(r"[^.\[\]]+", json_path[2:]):
            raw = raw[int(token)] if isinstance(raw, list) else raw[token]
        assert raw == rule["expected_task"]
        opcode = raw["$type"].rsplit(".", 1)[-1]
        source = IRSource(path, "AbilityTask", "real_count_task", {"json_path": json_path})
        payload = _effect_payload(raw, opcode, "", source=source)
        assert _effect_coverage_status(opcode, payload) == "executable"
        effect = EffectIR(json_path, opcode, payload, source, "executable")
        effects[json_path] = effect
        # Omitted fields are adopted only for the registered, unchanged source.
        for changed, changed_source in (({**raw, "Unknown": True}, source), (raw, replace(source, source_path="other"))):
            blocked = _effect_payload(changed, opcode, "", source=changed_source)
            assert _effect_coverage_status(opcode, blocked) != "executable"

    path = SOURCE
    lowering = TBGDLowering(root)
    lowered = lowering._lower_ability_file(root / path, {}, ability_file_order=0)
    resets = [task for task in lowered.status_callback_tasks if task.opcode == "SetModifierValue"]
    assert len(resets) == 2 and all(task.coverage_status == "executable" for task in resets)
    set_effect = effects["$.AbilityList[7].OnStart[3].FailedTaskList[0]"]
    extra_effect = effects["$.AbilityList[7].OnStart[3].SuccessTaskList[0]"]
    consume = effects["$.AbilityList[8].OnStart[10]"]
    read = effects["$.AbilityList[8].OnStart[11].SuccessTaskList[0]"]
    name = set_effect.payload["standard"]["modifier_name"]
    definition = next(item for item in lowered.entities if item.fields.get("modifier_name") == name)
    on_start_path = "$.AbilityList[7].OnStart[2]"
    raw_add = json.loads((root / path).read_text())["AbilityList"][7]["OnStart"][2]
    source = IRSource(path, "AbilityTask", "initial_counter", {"json_path": on_start_path})
    language = lowering._strict_target_language_definitions()
    payload, expressions = _attach_target_expressions_to_effect_payload(
        _effect_payload(raw_add, "AddModifier", ""), raw_add, effect_id=on_start_path,
        source=source, target_language_definitions=language,
    )
    initial_add = EffectIR(on_start_path, "AddModifier", payload, source, "executable",
                           modifier_definition_id=definition.entity_id, source_mode="mainline")
    callback_add = next(effect for effect in lowered.effects if effect.opcode == "AddModifier"
                        and effect.source.evidence.get("json_path") ==
                        "$.AbilityList[7].Modifiers.MAvatar_March7th_00_Passive._CallbackList[0].CallbackConfig[0]")
    callback_add = replace(callback_add, modifier_definition_id=definition.entity_id, source_mode="mainline")
    rules = RuleBook(CanonicalIR("modifier-count-check", entities=(definition,),
        effects=(*effects.values(), initial_add, callback_add),
        target_expressions=(*expressions, *lowered.target_expressions, *(item.expression for item in language))))
    registry = EffectRegistry(StatusSystem(rules))
    reducer = MutationReducer()

    def run(state, effect, source_id="check"):
        result = registry.execute(effect, EffectExecutionContext(state, "owner", source_id, owner_id="owner",
            dynamic_values={"1299003598": 2.0}, include_ambient_status_bindings=False,
            event_payload={"operation_event_id": f"check:{effect.effect_id}"}))
        assert not result.unsupported, result.unsupported
        return reducer.apply_all(state, result.mutations), result

    initial, _ = run(BattleState(units={"owner": UnitState("owner", "ally", "fixture:owner")}),
                     initial_add, source_id="ability_task:startup")
    state, reset = run(initial, set_effect)
    assert state.units["owner"].flags["status_details"][0]["stacks"] == 2
    assert state.units["owner"].flags["status_details"][0]["max_stacks"] is None
    assert not any(event.event_type == "status.lifecycle" for event in reset.events)
    state, first = run(state, consume)
    assert state.units["owner"].flags["status_details"][0]["stacks"] == 1
    state, copied = run(state, read)
    assert [entry["value"] for entry in store_from_state(state)["entries"].values()] == [1.0]
    reapplied, repeated = run(state, callback_add, source_id="status_callback_status:passive")
    assert not repeated.mutations and reapplied.snapshot() == state.snapshot()
    phase_reset = next(effect for effect in effects.values() if effect.source.evidence["json_path"].endswith("CallbackConfig[1].FailedTaskList[0]"))
    restored, _ = run(reapplied, phase_reset, source_id="status_callback_status:passive")
    old_detail = state.units["owner"].flags["status_details"][0]
    restored_detail = restored.units["owner"].flags["status_details"][0]
    assert restored_detail["stacks"] == 2 and restored_detail["instance_id"] == old_detail["instance_id"]
    assert restored_detail["source_id"] == old_detail["source_id"] == "ability_task:startup"
    state, exhausted = run(state, consume)
    assert not state.units["owner"].statuses and not state.units["owner"].flags["status_details"]
    assert any(event.window == "OnDestroy" for event in exhausted.events)
    assert not initial.units["owner"].flags["status_details"][0].get("stack_policy") == "independent_count"
    result = registry.execute(consume, EffectExecutionContext(state, "owner", "missing", owner_id="owner"))
    assert result.unsupported and not result.mutations
    extra, _ = run(initial, extra_effect)
    assert extra.units["owner"].flags["status_details"][0]["stacks"] == 3

    # An unrelated explicit operation needs no registered character or path.
    raw = {"$type": "RPG.GameCore.SetModifierValue", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
           "ModifierName": {"Value": "fixture_layers"}, "ValueType": "Layer", "ModifyFunction": "Set",
           "Value": {"IsDynamic": False, "FixedValue": {"Value": 9}}}
    payload = _effect_payload(raw, "SetModifierValue", "")
    assert _effect_coverage_status("SetModifierValue", payload) == "executable"
    generic = EffectIR("fixture:layers", "SetModifierValue", payload, IRSource("fixture", "test", "layers"), "executable")
    layered = StatusInstance("layers:1", "modifier:fixture_layers", "fixture_layers", "owner", "source", "owner",
                             max_stacks=3, stack_policy="additive_stack").to_json()
    layer_state = replace(initial, units={"owner": replace(initial.units["owner"],
        statuses=["modifier:fixture_layers"], flags={"status_details": [layered]})})
    after, result = run(layer_state, generic)
    assert after.units["owner"].flags["status_details"][0]["stacks"] == 3
    assert any(event.window == "OnStack" for event in result.events)
    subtract = {**raw, "ModifyFunction": "Add", "Value": {"IsDynamic": False, "FixedValue": {"Value": -3}}}
    empty, result = run(after, replace(generic, payload=_effect_payload(subtract, "SetModifierValue", "")))
    assert not empty.units["owner"].statuses
    assert any(event.window == "OnDestroy" for event in result.events)
    for value in (float("nan"), 1.5, -1):
        invalid = {**raw, "Value": {"IsDynamic": False, "FixedValue": {"Value": value}}}
        bad = replace(generic, payload=_effect_payload(invalid, "SetModifierValue", ""))
        rejected = registry.execute(bad, EffectExecutionContext(layer_state, "owner", "bad", owner_id="owner"))
        assert rejected.unsupported and not rejected.mutations
