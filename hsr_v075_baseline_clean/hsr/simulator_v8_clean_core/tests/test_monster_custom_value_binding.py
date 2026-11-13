"""Formal per-card CustomValues binding and conditional passive startup admission.

These are component checks: they lower only the source ability file and the
monster card, so they stay independent of a full battle build.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.dynamic_key_hash import tbgd_dynamic_key_hash
from hsr.simulator_v8_clean_core.rules.evaluator import (
    NumericEvaluationContext,
    RuleEvaluator,
)
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hash
from hsr.simulator_v8_clean_core.rules.ir import IRSource, SummonMonsterIntentIR
from hsr.simulator_v8_clean_core.systems.ability import (
    _summon_monster_intent_caster_card_blocked_reason,
)
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering,
    _admit_passive_startup_slot,
    _monster_custom_value_binding_source,
)
from hsr.simulator_v8_clean_core.tbgd.monster_cards import build_monster_card_ir

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TBGD = _REPO_ROOT / "turnbasedgamedata-main"
_MONSTER_CONFIG = "Config/ConfigCharacter/Monster/Monster_W1_Soldier03_00_Config.json"
_MONSTER_CONFIG_A = "Config/ConfigCharacter/Monster/Monster_W1_Soldier03_00_Config_A.json"
_ABILITY = "Config/ConfigAbility/Monster/Monster_W1_Soldier03_00_Ability.json"


def _read(path: str) -> dict:
    return json.loads((_TBGD / path).read_text(encoding="utf-8"))


def _monster_configs() -> dict[str, dict]:
    rows = _read("ExcelOutput/MonsterConfig.json")
    return {str(row["MonsterID"]): row for row in rows}


def _binding(monster_id: str, config_path: str) -> dict:
    row = _monster_configs()[monster_id]
    config = _read(config_path)
    config_source = {
        "relative_path": "ExcelOutput/MonsterConfig.json",
        "row_index": 0,
        "monster_id": row["MonsterID"],
        "template_id": row["MonsterTemplateID"],
        "custom_values": row.get("CustomValues") or [],
    }
    return _monster_custom_value_binding_source(
        config_source=config_source,
        character_config=config,
        character_path=config_path,
    )


def test_custom_value_binding_maps_name_hash_and_value_for_consistent_card():
    binding = _binding("1003010", _MONSTER_CONFIG)
    assert binding["admission_status"] == "executable"
    assert binding["hash_to_name_admitted"] is True
    assert binding["conflict_count"] == 0
    summon_hash = str(tbgd_dynamic_key_hash("SummonID01"))
    entry_key = binding["by_hash"][summon_hash]
    entry = binding["entries"][entry_key]
    assert entry["name"] == "SummonID01"
    assert entry["value"] == 1002040.0
    assert entry["binding_scope"]["monster_id"] == 1003010
    assert binding["by_name"]["SummonID02"] == "custom_value:SummonID02"
    # The formal binding is enough to resolve the source's dynamic-hash request.
    result = RuleEvaluator().evaluate_numeric(
        numeric_dynamic_hash(int(summon_hash)),
        NumericEvaluationContext(binding_sources=(binding,)),
    )
    assert result.ok, result.blocked_reason
    assert result.value == 1002040.0
    assert result.bindings["matched_by"] == "hash"


def test_custom_value_binding_rejects_table_and_config_conflict_per_name():
    binding = _binding("1003011", _MONSTER_CONFIG_A)
    assert binding["admission_status"] == "executable"
    conflict_names = {item["name"] for item in binding["conflicts"]}
    assert conflict_names == {"SummonID02"}
    conflict = binding["conflicts"][0]
    assert conflict["table_value"] == 1002050.0
    assert conflict["character_config_value"] == 1002040.0
    assert "custom_value_table_and_character_config_conflict" in conflict["reasons"]
    # The conflicting name keeps no binding, so the other card can never borrow
    # this card's table row or its serialized default.
    assert str(tbgd_dynamic_key_hash("SummonID02")) not in binding["by_hash"]
    assert str(tbgd_dynamic_key_hash("SummonID01")) in binding["by_hash"]


def test_custom_value_binding_uses_selected_template_defaults_without_table_repetition():
    config = _read(_MONSTER_CONFIG)
    config_source = {
        "relative_path": "ExcelOutput/MonsterConfig.json",
        "row_index": 0,
        "monster_id": 1003010,
        "template_id": 1003010,
        "custom_values": [{"BFLIFKBEOPJ": "OnlyInTable", "MNDFOPKBHKP": 7}],
    }
    binding = _monster_custom_value_binding_source(
        config_source=config_source,
        character_config=config,
        character_path=_MONSTER_CONFIG,
    )
    reasons = {reason for item in binding["unbound"] for reason in item["reasons"]}
    assert "custom_value_table_row_missing" not in reasons
    assert "custom_value_character_config_missing" in reasons
    assert binding["conflict_count"] == 0
    assert "OnlyInTable" not in binding["by_name"]
    assert binding['by_name']
    assert all(entry['value_origin'] == 'character_config_default' for entry in binding['entries'].values())
    # A missing character declaration still cannot invent a binding.
    summary_module = __import__(
        "hsr.simulator_v8_clean_core.tbgd.lowering", fromlist=["_custom_value_binding_summary"]
    )
    summary = summary_module._custom_value_binding_summary(
        config_source, config, binding
    )
    assert summary["formal_unbound_count"] >= 1
    assert any(
        item["name"] == "OnlyInTable"
        and item["formal_binding_status"] == "rejected"
        and "custom_value_character_config_missing" in item["formal_binding_reason"]
        for item in summary["entries"]
    )


def test_custom_value_binding_scope_check_rejects_foreign_caster_card():
    class _Card:
        card_id = "monster_data_card:monster:1003010"
        monster_id = 1003010

    class _Rules:
        def monster_data_card_for_entity(self, entity_ref: str) -> _Card:
            assert entity_ref == "monster:1003010"
            return _Card()

    class _Actor:
        template_id = "monster:1003010"
        flags = {"monster_data_card_id": "monster_data_card:monster:1003010"}

    scope = {
        "monster_id": 1003010,
        "character_config_path": _MONSTER_CONFIG,
        "custom_value_binding_scope": {
            "monster_id": 1003010,
            "character_config_path": _MONSTER_CONFIG,
        },
    }

    def make_intent(caster_scope: dict, evidence: dict | None = None):
        return SummonMonsterIntentIR(
            summon_intent_id="summon_monster_intent:fixture",
            source_task_id="ability_task:fixture",
            owner_scope="caster",
            target_scope="summoned_monster_entries",
            delay_policy={"admission_status": "executable", "value": 1.0},
            entries=(),
            source_event="OnStart",
            source=IRSource(
                source_path=_ABILITY,
                raw_type="SummonMonsterIntent",
                raw_id="ability_task:fixture",
                evidence=evidence if evidence is not None else {},
            ),
            caster_card_scope=caster_scope,
            coverage_status="executable",
        )

    intent = make_intent(scope)
    # The formal field decides; an empty evidence payload must not change it.
    stripped = make_intent(scope, evidence={})
    assert _summon_monster_intent_caster_card_blocked_reason(_Rules(), intent, _Actor()) == ""
    assert _summon_monster_intent_caster_card_blocked_reason(_Rules(), stripped, _Actor()) == ""
    # Stale audit evidence is not a runtime input and cannot override the field.
    stale_evidence = make_intent(
        scope,
        evidence={"caster_card_scope": {**scope, "monster_id": 1003011}},
    )
    assert (
        _summon_monster_intent_caster_card_blocked_reason(_Rules(), stale_evidence, _Actor())
        == ""
    )
    foreign = make_intent({**scope, "monster_id": 1003011})
    assert (
        _summon_monster_intent_caster_card_blocked_reason(_Rules(), foreign, _Actor())
        == "summon_monster_intent_caster_card_mismatch"
    )
    missing = make_intent({})
    assert (
        _summon_monster_intent_caster_card_blocked_reason(_Rules(), missing, _Actor())
        == "summon_monster_intent_caster_card_scope_missing"
    )
    assert intent.to_json()["caster_card_scope"] == scope


def test_conditional_passive_startup_admits_real_monster_initializers():
    root = _TBGD
    lowerer = TBGDLowering(root)
    graphs, phases, tasks, effects, conditions, formulas, targets, _ = (
        lowerer._lower_standalone_ability_graphs([root / _ABILITY])
    )
    graph = next(
        item
        for item in graphs
        if item.ability_name == "Monster_W1_Soldier03_00_PassiveSkillInitiate"
    )
    card_ir = build_monster_card_ir(
        root, max_records_per_table=None, monster_ids=frozenset({"1003010"})
    )
    slot = next(
        item
        for item in card_ir.passive_mechanism_slots
        if item.semantics.get("ability_name") == graph.ability_name
    )
    admitted = _admit_passive_startup_slot(
        slot,
        graphs_by_name={graph.ability_name: [graph]},
        tasks_by_phase={
            phase.phase_id: [task for task in tasks if task.phase_id == phase.phase_id]
            for phase in phases
        },
        effects_by_id={effect.effect_id: effect for effect in effects},
        modifiers_with_triggers=set(),
        conditions_by_id={condition.condition_id: condition for condition in conditions},
    )
    assert admitted.coverage_status == "executable", admitted.blocked_reason
    admission = admitted.semantics["startup_admission"]
    assert admission["admission_status"] == "executable"
    admitted_tasks = admission["admitted_tasks"]
    predicate_entries = [
        item for item in admitted_tasks if item.get("kind") == "predicate_branch"
    ]
    assert len(predicate_entries) == 1
    predicate_entry = predicate_entries[0]
    assert predicate_entry["condition_opcode"] == "ByCompareMonsterID"
    assert predicate_entry["success_task_ids"]
    # The caster's own monster id is part of the official source condition, so
    # the branch is a runtime decision, not a compile-time ID allow-list.
    condition = next(
        item for item in conditions if item.condition_id == predicate_entry["condition_id"]
    )
    assert condition.opcode == "ByCompareMonsterID"
    assert condition.payload["TargetMonsterID"]["value"] == 1003011.0
    # Omitted ResetValue is admitted only as an initialize-when-absent policy.
    dynamic_entries = [
        item
        for item in admitted_tasks
        if item.get("effect_id")
        and next(
            effect
            for effect in effects
            if effect.effect_id == item["effect_id"]
        ).opcode
        == "DefineDynamicValue"
    ]
    policies = {
        next(
            effect
            for effect in effects
            if effect.effect_id == item["effect_id"]
        ).payload["standard"]["value_name"]: item["dynamic_value_reset_policy"]
        for item in dynamic_entries
    }
    assert policies == {
        "W1_Soldier03_00_SummonCounter": "initialize_zero_only_when_absent",
        "W1_Soldier03_00_AICounter": "explicit_reset_value",
    }
