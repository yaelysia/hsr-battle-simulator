from __future__ import annotations

import json
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource, RuleEntity
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _attach_target_expressions_to_effect_payload,
    _modifier_definition_entity, _standard_add_modifier_payload,
    _standard_remove_modifier_payload, _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import (
    build_target_language_definitions, close_target_expression_language,
)

ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"


@lru_cache(maxsize=1)
def _sources():
    lowering = TBGDLowering(ROOT)
    common = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
    raw = json.loads((ROOT / common).read_text())["ModifierMap"]
    endurance = _modifier_definition_entity(
        common, "ModifierMap", "MCommon_Endurance", raw["MCommon_Endurance"],
        source_context={"json_path": "$.ModifierMap.MCommon_Endurance"},
    )
    lynx = lowering._lower_ability_file(
        ROOT / "Config/ConfigAbility/Avatar/Avatar_Lynx_00_Ability.json", {}, ability_file_order=0,
    )
    protection = next(row for row in lynx.entities if row.fields.get("modifier_name") == "MAvatar_Lynx_00_Rank02_Resist")
    callbacks = tuple(row for row in lynx.status_callbacks if row.modifier_name == "MAvatar_Lynx_00_Rank02_Resist")
    return (
        tuple(lowering._lower_status_immunity_rules()), build_target_language_definitions(ROOT),
        endurance, protection, callbacks, raw["MCommon_CTRL_Frozen"]["BehaviorFlagList"],
    )


def _case(*, grant="Endurance", incoming_flags=(), status_type="Debuff", one_use=False):
    immunity_rules, languages, endurance, lynx, callbacks, _ = _sources()
    if one_use:
        protection = lynx
    elif grant == "Endurance":
        protection = endurance
    else:
        # Other grants are synthetic holders of the exact shared table flag.
        protection = _modifier_definition_entity(
            "fixture/immunity.json", "ModifierMap", "Protection",
            {"BehaviorFlagList": [grant]}, source_context={"json_path": "$.ModifierMap.Protection"},
        )
    incoming = _modifier_definition_entity(
        "fixture/immunity.json", "ModifierMap", "Incoming",
        {"BehaviorFlagList": list(incoming_flags)}, source_context={"json_path": "$.ModifierMap.Incoming"},
    )
    status = RuleEntity(
        "test:incoming_type", "status", {"ModifierName": "Incoming", "StatusType": status_type},
        IRSource("fixture/status.json", "StatusConfig", "test:incoming_type"), "lowered",
    )
    effects = []
    expressions = [row.expression for row in languages]
    for effect_id, opcode, definition in (
        ("grant", "AddModifier", protection), ("incoming", "AddModifier", incoming),
        ("remove", "RemoveModifier", protection),
    ):
        raw = {"$type": f"RPG.GameCore.{opcode}", "ModifierName": {"Value": definition.fields["modifier_name"]}, "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}}
        if effect_id == "incoming" and status_type in {"Buff", "Debuff"}:
            raw["Chance"] = {"IsDynamic": False, "FixedValue": {"Value": 1.0}}
        source = IRSource("fixture/immunity_requests.json", opcode, effect_id, {"json_path": f"$.{effect_id}"})
        standard = _standard_add_modifier_payload(raw) if opcode == "AddModifier" else _standard_remove_modifier_payload(raw, opcode, "")
        payload, targets = _attach_target_expressions_to_effect_payload({"standard": standard}, raw, effect_id=effect_id, source=source)
        targets = [close_target_expression_language(row, languages) for row in targets]
        effect = EffectIR(effect_id, opcode, payload, source, "executable", modifier_definition_id=definition.entity_id, source_mode="mainline")
        if one_use and effect_id == "grant":
            effect = replace(effect, status_callback_ids=tuple(row.callback_id for row in callbacks))
        effects.extend(_synchronize_effect_target_expression_metadata([effect], targets))
        expressions.extend(targets)
    rules = RuleBook(CanonicalIR(
        "test", entities=(*immunity_rules, protection, incoming, status), effects=tuple(effects),
        target_expressions=tuple(expressions), status_callbacks=callbacks if one_use else (),
    ))
    state = BattleState(units={"holder": UnitState(
        "holder", "ally", "test:holder", hp=100.0, max_hp=100.0,
        resources={"effect_hit_rate": 100.0},
    )})
    installed = StatusSystem(rules).apply_add_modifier(state, rules.effect("grant"), caster_id="holder", source_id="test:grant")
    assert installed.ok, installed.unsupported
    return rules, MutationReducer().apply_all(state, installed.mutations)


def _attempt(rules, state):
    return StatusSystem(rules).apply_add_modifier(
        state, rules.effect("incoming"), caster_id="holder", source_id="test:attempt",
    )


def test_real_endurance_blocks_control_until_formal_removal():
    frozen_flags = _sources()[-1]
    rules, state = _case(incoming_flags=frozen_flags)
    before = state.snapshot()
    result = _attempt(rules, state)
    assert result.ok and not result.mutations and not result.rng_events, result.unsupported
    immunity = next(row for row in result.records if row["record_type"] == "status_immunity")
    match = immunity["payload"]["immunity_source"]["shared_immunity_matches"][0]
    assert match["granting_behavior_flag"] == "Endurance"
    assert match["rule_source"]["evidence"]["json_path"].endswith("ModifierBehaviorFlagImmuneMap.Endurance")
    assert state.snapshot() == before
    removed = StatusSystem(rules).apply_remove_modifier(state, rules.effect("remove"), caster_id="holder", source_id="test:remove")
    assert removed.ok, removed.unsupported
    cleared = MutationReducer().apply_all(state, removed.mutations)
    result = _attempt(rules, cleared)
    assert result.ok and result.mutations
    assert not any(row["record_type"] == "status_immunity" for row in result.records)


def test_all_shared_mappings_and_nonmatching_requests():
    rules = _sources()[0]
    assert len(rules) == 11
    for rule in rules:
        flags, types = rule.fields["behavior_flags"], rule.fields["status_types"]
        for status_type in types or ["Debuff"]:
            book, state = _case(grant=rule.fields["granting_behavior_flag"], incoming_flags=flags, status_type=status_type)
            result = _attempt(book, state)
            assert result.ok and not result.mutations and not result.rng_events, (rule.entity_id, result.unsupported)
            assert any(row["record_type"] == "status_immunity" for row in result.records)
    for grant, incoming_flags in (("Endurance", ("STAT_DOT",)), ("ImmuneDot", ("STAT_CTRL",)), ("ImmuneDebuff", ())):
        book, state = _case(grant=grant, incoming_flags=incoming_flags, status_type="Buff")
        result = _attempt(book, state)
        assert result.ok and result.mutations, result.unsupported


def test_consumed_protection_override_and_unknown_type_fail_closed():
    cases = (
        ({"one_use": True}, "status_immunity_callback_order_not_admitted"),
        ({"incoming_flags": ("STAT_CTRL", "STAT_ForceControl")}, "status_immunity_override_order_not_admitted"),
        ({"grant": "ImmuneDebuff", "status_type": "Unknown"}, "status_immunity_application_type_unknown"),
    )
    for kwargs, reason in cases:
        rules, state = _case(**kwargs)
        before = state.snapshot()
        result = _attempt(rules, state)
        assert not result.ok and result.unsupported == (reason,), result.unsupported
        assert not result.mutations and not result.rng_events
        assert state.snapshot() == before


def test_only_installed_grants_and_admitted_rules_are_consumed():
    rules, state = _case(incoming_flags=("STAT_CTRL",))
    unit = state.units["holder"]
    detached = replace(state, units={"holder": replace(unit, statuses=())})
    result = _attempt(rules, detached)
    assert result.ok and result.mutations
    assert not any(row["record_type"] == "status_immunity" for row in result.records)
    for coverage in ("blocked", "audit_only"):
        entities = tuple(
            replace(row, coverage_status=coverage)
            if row.entity_type == "status_immunity_rule" and row.fields["granting_behavior_flag"] == "Endurance"
            else row for row in rules.ir.entities
        )
        blocked = _attempt(RuleBook(replace(rules.ir, entities=entities)), state)
        assert not blocked.ok and not blocked.mutations and not blocked.rng_events
        assert blocked.unsupported == ("status_immunity_rule_not_admitted",)


if __name__ == "__main__":
    test_real_endurance_blocks_control_until_formal_removal()
    test_all_shared_mappings_and_nonmatching_requests()
    test_consumed_protection_override_and_unknown_type_fail_closed()
    test_only_installed_grants_and_admitted_rules_are_consumed()
    print("shared status immunity: 4 checks passed")
