"""Real ordinary count source uses the shared dynamic store and target resolver."""
import json
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import _attach_target_expressions_to_effect_payload, _effect_payload
from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions


def test_real_misha_count_commits_audited_store_and_missing_target_does_not_write():
    path = "Config/ConfigAbility/Avatar/Avatar_Misha_00_Ability.json"
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    document = json.loads((root / path).read_text())
    def count_task(value, location="$"):
        if isinstance(value, dict):
            if value.get("$type") == "RPG.GameCore.SetDynamicValueByCharacterCount":
                return value, location
            for key, child in value.items():
                found = count_task(child, location + "." + key)
                if found:
                    return found
        elif isinstance(value, list):
            for index, child in enumerate(value):
                found = count_task(child, location + f"[{index}]")
                if found:
                    return found
    raw, location = count_task(document)
    assert raw["ReadTargetType"]["Alias"] == "AllEnemy" and raw["AliveOnly"] is True
    source = IRSource(path, "SetDynamicValueByCharacterCount", "real-count", {"json_path": location})
    definitions = build_target_language_definitions(root)
    payload, expressions = _attach_target_expressions_to_effect_payload(
        _effect_payload(raw, "SetDynamicValueByCharacterCount", "", source=source), raw,
        effect_id="count", source=source, target_language_definitions=definitions)
    effect = EffectIR("count", "SetDynamicValueByCharacterCount", payload, source, "executable")
    rules = RuleBook(CanonicalIR("count", effects=(effect,),
        target_expressions=(*expressions, *(definition.expression for definition in definitions))))
    runtime = EffectRegistry(StatusSystem(rules))
    state = BattleState(units={
        "actor": UnitState("actor", "ally", "fixture", hp=100, max_hp=100),
        "living": UnitState("living", "enemy", "fixture", hp=100, max_hp=100),
        "dead": UnitState("dead", "enemy", "fixture", lifecycle_status="defeated", hp=0, max_hp=100),
    })
    context = EffectExecutionContext(state, "actor", "source:count", owner_id="actor",
        ability_instance_id="ability:count", event_payload={"operation_event_id": "count:1"})
    result = runtime.execute(effect, context)
    assert not result.unsupported, result.unsupported
    committed = MutationReducer().apply_all(state, result.mutations)
    values = list(store_from_state(committed)["entries"].values())
    assert len(values) == 1 and values[0]["name"] == raw["DynamicKey"] and values[0]["value"] == 1
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, audit.to_json()
    assert MutationReducer().replay_snapshot(state, result.mutations, committed.snapshot().to_json()).ok
    empty = replace(state, units={"actor": state.units["actor"], "dead": state.units["dead"]})
    zero = runtime.execute(effect, replace(context, state=empty))
    assert not zero.unsupported, zero.unsupported
    assert next(iter(store_from_state(MutationReducer().apply_all(empty, zero.mutations))["entries"].values()))["value"] == 0
    spec = dict(payload["standard"]["dynamic_operation"])
    spec["operand"] = {**spec["operand"], "parameters": {
        **spec["operand"]["parameters"], "source_target_expression_id": "missing"}}
    invalid = replace(effect, payload={**payload, "standard": {**payload["standard"], "dynamic_operation": spec}})
    rejected = runtime.execute(invalid, context)
    assert rejected.unsupported and not rejected.mutations and not rejected.rng_events
    assert store_from_state(state)["entries"] == {}
