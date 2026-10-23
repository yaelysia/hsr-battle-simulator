"""Summoned monster birth panel: battle level context, per-card isolation, audit.

The summon task declares no level or difficulty field, so a summoned soldier must
take the battle's own level context instead of the card default or the owner panel.
This module checks:

* the same real child card under two source level/difficulty contexts computes the
  panel from the selected rows (expectations are read from TBGD JSON independently
  of the scaling helpers under test);
* the panel is per-card, and resolving one context after another leaves no cached
  result behind (a different card in the same battle keeps its own base panel);
* a missing level/difficulty input blocks the whole parent summon instead of
  falling back to base stats, level 1 or the owner panel;
* the native spawn record is audited against the formal profile base times the
  selected ratio row, so a changed birth stat or a swapped ratio row is rejected.

Stage 301002's context is a declared component input: only stage 307311 is part of
the shipped battle rulebook, so its context is assembled from the raw selected rows
to exercise a second difficulty context without compiling a second stage.
"""
from __future__ import annotations

import json
import math
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from hsr.simulator_v8_clean_core.core.model import BattleState
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.session import BattleSession
from hsr.simulator_v8_clean_core.systems.summon import (
    SummonSystem,
    _summoned_monster_level_context,
)
from hsr.simulator_v8_clean_core.systems.unit_spawn import (
    UnitSpawnRequest,
    UnitSpawnSystem,
)
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_SCENARIO = _CORE / "examples/cli/silvermane_lieutenant_summon_natural.json"
_SCRIPT = "monster_skill:100301004"
_SUMMONED = "monster:1002040"
_LIEUT = "monster:1003010"
_LIEUT_UNIT_ID = "enemy:stage:307311:wave:0:pos:0"
_LEVEL_CONTEXT_KIND = "battle_stage_level_hard_level_group_inherited_from_summoner"
_STAT_FIELDS = ("max_hp", "attack", "defense", "speed", "max_toughness")


def _rows(name: str):
    return json.loads(
        (_ROOT / "turnbasedgamedata-main" / f"ExcelOutput/{name}.json").read_text(
            encoding="utf-8"
        )
    )


def _row(name: str, **match):
    for row in _rows(name):
        if all(row.get(key) == value for key, value in match.items()):
            return row
    raise AssertionError(f"{name} row not found: {match}")


def _base_panel(monster_id: int) -> dict[str, float]:
    """Card profile base (MonsterConfig modify ratios already folded in)."""

    monster = _row("MonsterConfig", MonsterID=monster_id)
    template = _row(
        "MonsterTemplateConfig", MonsterTemplateID=monster["MonsterTemplateID"]
    )
    return {
        "max_hp": template["HPBase"]["Value"] * monster["HPModifyRatio"]["Value"],
        "attack": template["AttackBase"]["Value"] * monster["AttackModifyRatio"]["Value"],
        "defense": template["DefenceBase"]["Value"] * monster["DefenceModifyRatio"]["Value"],
        "speed": template["SpeedBase"]["Value"] * monster["SpeedModifyRatio"]["Value"],
        "max_toughness": template["StanceBase"]["Value"] * monster["StanceModifyRatio"]["Value"],
    }


def _stage_context(stage_id: int) -> tuple[dict[str, float], int, int, int | None]:
    """Ratios, level, hard level group and elite group read from the source rows."""

    stage = _row("StageConfig", StageID=stage_id)
    level = stage["Level"]
    hard_group = stage["HardLevelGroup"]
    hard = _row("HardLevelGroup", HardLevelGroup=hard_group, Level=level)
    ratios = {
        "max_hp": hard["HPRatio"]["Value"],
        "attack": hard["AttackRatio"]["Value"],
        "defense": hard["DefenceRatio"]["Value"],
        "speed": hard["SpeedRatio"]["Value"],
        "max_toughness": hard["StanceRatio"]["Value"],
    }
    elite_group = stage.get("EliteGroup")
    if elite_group is not None:
        elite = _row("EliteGroup", EliteGroup=elite_group)
        for field_name, raw_key in (
            ("max_hp", "HPRatio"),
            ("attack", "AttackRatio"),
            ("defense", "DefenceRatio"),
            ("speed", "SpeedRatio"),
            ("max_toughness", "StanceRatio"),
        ):
            ratios[field_name] *= elite[raw_key]["Value"]
    return ratios, level, hard_group, elite_group


@lru_cache(maxsize=1)
def _case():
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    rules = build_battle_rulebook(_ROOT / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    intent = next(
        intent
        for intent in rules.ir.summon_monster_intents
        if intent.coverage_status == "executable" and _SCRIPT in intent.source_task_id
    )
    entry = intent.entries[0]
    template = rules.unit_birth_template(entry.birth_template_id)
    assert template is not None and template.coverage_status == "executable"
    gauge = next(
        rule.base_action_gauge
        for rule in rules.ir.timeline_rules
        if rule.coverage_status == "executable"
    )
    return rules, session, intent, entry, template, gauge


def _request(
    template,
    context: dict,
    *,
    unit_id: str = "enemy:summon:fixture:0",
) -> UnitSpawnRequest:
    _, _, intent, entry, _, _ = _case()
    return UnitSpawnRequest(
        spawn_kind="summoned_monster",
        unit_id=unit_id,
        birth_template_id=template.birth_template_id,
        entity_ref=template.entity_ref,
        source_id=intent.summon_intent_id,
        entry_id=entry.entry_id,
        owner_id=_LIEUT_UNIT_ID,
        summoner_id=_LIEUT_UNIT_ID,
        entry_index=0,
        copy_index=0,
        spawn_index=0,
        source_trace=intent.source.to_json(),
        entry_source_trace=entry.source.to_json(),
        level_context=context,
    )


def _source_trace(relative: str, raw_type: str, raw_id: str, evidence: dict):
    return {
        "source_path": relative,
        "raw_type": raw_type,
        "raw_id": raw_id,
        "evidence": evidence,
    }


def _second_context(stage_id: int) -> dict:
    """Component level context for a stage outside the shipped rulebook."""

    ratios, level, hard_group, elite_group = _stage_context(stage_id)
    stage = _row("StageConfig", StageID=stage_id)
    source_trace = {
        "stage": _source_trace(
            "ExcelOutput/StageConfig.json",
            "StageConfig",
            str(stage_id),
            {
                "level": level,
                "hard_level_group": hard_group,
                "elite_group": elite_group,
            },
        ),
        "hard_level_profile": _source_trace(
            "ExcelOutput/HardLevelGroup.json",
            "HardLevelGroup",
            f"{hard_group}:{level}",
            {"ratios": {name: ratios[name] for name in _STAT_FIELDS}},
        ),
    }
    if elite_group is not None:
        elite = _row("EliteGroup", EliteGroup=elite_group)
        source_trace["elite_group_profile"] = _source_trace(
            "ExcelOutput/EliteGroup.json",
            "EliteGroup",
            str(elite_group),
            {
                "ratios": {
                    name: elite[key]["Value"]
                    for name, key in (
                        ("max_hp", "HPRatio"),
                        ("attack", "AttackRatio"),
                        ("defense", "DefenceRatio"),
                        ("speed", "SpeedRatio"),
                        ("max_toughness", "StanceRatio"),
                    )
                }
            },
        )
    return {
        "kind": _LEVEL_CONTEXT_KIND,
        "admission_status": "executable",
        "source_basis": "CombatantProfileIR.base_stats_times_battle_stage_level_policy",
        "effective_context": "resolved_from_current_battle_stage_level_policy",
        "stage_id": str(stage_id),
        "wave_definition_id": f"wave_definition:stage:{stage_id}",
        "level": level,
        "hard_level_group": hard_group,
        "elite_group": elite_group,
        "ratios": ratios,
        "source_trace": source_trace,
    }


def _assert_panel(unit, base, ratios, level, gauge):
    for field_name in _STAT_FIELDS:
        assert getattr(unit, field_name) == pytest.approx(
            base[field_name] * ratios[field_name]
        ), field_name
    assert unit.level == level
    assert unit.hp == pytest.approx(unit.max_hp)
    assert unit.toughness == pytest.approx(unit.max_toughness)
    assert unit.action_value == pytest.approx(gauge / unit.speed)
    context = unit.flags["summon_level_context"]
    assert context["level"] == level
    assert context["ratios"] == pytest.approx(ratios)
    return context


def test_same_child_card_scales_from_each_source_context():
    rules, session, intent, entry, template, gauge = _case()
    owner = session.state.units[_LIEUT_UNIT_ID]
    context_a, reason = _summoned_monster_level_context(rules, session.state, owner)
    assert reason == ""
    context_b = _second_context(301002)
    assert context_b["level"] != context_a["level"]

    base = _base_panel(1002040)
    ratios_a, level_a, group_a, elite_a = _stage_context(307311)
    ratios_b, level_b, group_b, elite_b = _stage_context(301002)
    assert context_a["hard_level_group"] == group_a and context_a["ratios"] == pytest.approx(ratios_a)
    assert context_b["hard_level_group"] == group_b and context_b["ratios"] == pytest.approx(ratios_b)
    assert ratios_b["max_hp"] != ratios_a["max_hp"]  # at least one non-unit ratio

    spawner = UnitSpawnSystem()
    request_a = _request(template, context_a, unit_id="enemy:summon:a:0")
    # The new field survives request encoding round-trip unchanged and stays part
    # of the behavioral identity; it is never replaced by a default.
    encoded = request_a.to_json()
    assert encoded["level_context"] == context_a
    assert UnitSpawnRequest.from_json(encoded) == request_a
    plan_a = spawner.plan(template, request_a, owner=owner)
    assert plan_a.ok, plan_a.blocked_reason
    unit_a = plan_a.to_unit(expected_request=request_a, expected_template=template, owner=owner)
    _assert_panel(unit_a, base, ratios_a, level_a, gauge)

    plan_b = spawner.plan(
        template, _request(template, context_b, unit_id="enemy:summon:b:0"), owner=owner
    )
    assert plan_b.ok, plan_b.blocked_reason
    unit_b = plan_b.to_unit(expected_request=_request(template, context_b, unit_id="enemy:summon:b:0"), expected_template=template, owner=owner)
    _assert_panel(unit_b, base, ratios_b, level_b, gauge)
    assert unit_b.max_hp != pytest.approx(unit_a.max_hp)

    # Resolving the first context again after the second one must reproduce it:
    # no per-instance panel is cached across contexts.
    plan_a2 = spawner.plan(
        template, _request(template, context_a, unit_id="enemy:summon:a2:0"), owner=owner
    )
    assert plan_a2.ok, plan_a2.blocked_reason
    assert plan_a2.unit["max_hp"] == pytest.approx(plan_a.unit["max_hp"])
    assert plan_a2.unit["level"] == plan_a.unit["level"]
    assert plan_a2.unit["action_value"] == pytest.approx(plan_a.unit["action_value"])


def test_other_card_keeps_its_own_base_panel():
    rules, session, intent, entry, template, gauge = _case()
    owner = session.state.units[_LIEUT_UNIT_ID]
    context, reason = _summoned_monster_level_context(rules, session.state, owner)
    assert reason == ""
    # The caster's own wave unit is already scaled in the shipped battle: the child
    # card must not inherit that panel, and the caster must not take the child's.
    child_base = _base_panel(1002040)
    lieut_base = _base_panel(1003010)
    assert child_base["max_hp"] != lieut_base["max_hp"]
    spawner = UnitSpawnSystem()
    request = _request(template, context)
    plan = spawner.plan(template, request, owner=owner)
    assert plan.ok, plan.blocked_reason
    unit = plan.to_unit(expected_request=request, expected_template=template, owner=owner)
    ratios = context["ratios"]
    assert unit.max_hp == pytest.approx(child_base["max_hp"] * ratios["max_hp"])
    assert unit.max_hp != pytest.approx(lieut_base["max_hp"] * ratios["max_hp"])
    assert owner.max_hp == pytest.approx(lieut_base["max_hp"] * ratios["max_hp"])
    assert unit.max_hp != pytest.approx(owner.max_hp)


def test_missing_level_context_blocks_instead_of_falling_back():
    rules, session, intent, entry, template, gauge = _case()
    owner = session.state.units[_LIEUT_UNIT_ID]
    spawner = UnitSpawnSystem()
    empty = spawner.plan(
        template,
        replace(_request(template, {}), level_context={}),
    )
    assert not empty.ok
    assert "unit_spawn_request_level_context_missing" in empty.blocked_reason

    # A battle without stage/wave identity cannot scale a summon: the whole parent
    # action is blocked before any unit is planned.
    stateless = replace(
        session.state,
        global_flags={
            key: value
            for key, value in session.state.global_flags.items()
            if key != "wave_runtime"
        },
    )
    blocked = SummonSystem(rules).plan_spawn_from_intent(
        stateless, intent, owner_id=_LIEUT_UNIT_ID
    )
    assert not blocked.ok
    assert blocked.blocked_reason == "summon_monster_battle_wave_runtime_missing"
    assert blocked.unit_ids == ()

    # Displayed level and selected ratio row share one source: a summoner outside
    # the battle level context blocks instead of scaling with a different level.
    mismatched = replace(
        session.state,
        units={**session.state.units, _LIEUT_UNIT_ID: replace(owner, level=80)},
    )
    mismatch = SummonSystem(rules).plan_spawn_from_intent(
        mismatched, intent, owner_id=_LIEUT_UNIT_ID
    )
    assert not mismatch.ok
    assert mismatch.blocked_reason == "summon_monster_battle_level_owner_mismatch"


def _reassociate_records(records, old_id, new_id, *, record_type=None, source=None):
    """Move a settlement record onto a changed mutation identity."""

    result = []
    for record in records:
        if record.get("mutation_id") != old_id:
            result.append(record)
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            mutation_ids = payload.get("mutation_ids")
            if isinstance(mutation_ids, list):
                payload = {
                    **payload,
                    "mutation_ids": [
                        new_id if item == old_id else item for item in mutation_ids
                    ],
                }
        updated = {**record, "mutation_id": new_id, "payload": payload}
        if record_type is not None:
            updated["record_type"] = record_type
        if source is not None:
            updated["source"] = source
        result.append(updated)
    return result


def test_native_birth_record_must_match_formal_panel_and_ratio_row():
    rules, session, intent, entry, template, gauge = _case()
    system = SummonSystem(rules)
    plan = system.plan_spawn_from_intent(session.state, intent, owner_id=_LIEUT_UNIT_ID)
    assert plan.ok, plan.blocked_reason
    result = system.apply_spawn(session.state, plan)
    assert result.plan.ok, result.plan.blocked_reason
    spawn_mutations = tuple(
        mutation for mutation in result.mutations if mutation.op == "spawn"
    )
    # This ability runs two SummonMonster tasks; one lowered intent owns one entry.
    assert len(spawn_mutations) == 1

    auditor = RuntimeSourceAuditor(rules)
    audit = auditor.validate_execution(result.mutations, result.records)
    assert audit.ok, [(violation.reason, violation.details) for violation in audit.violations]

    # A changed birth stat is rejected even when re-associated with the same
    # summon settlement records.
    spawn = spawn_mutations[0]
    tampered_after = json.loads(json.dumps(spawn.after))
    tampered_after["max_hp"] = tampered_after["max_hp"] + 1.0
    tampered = replace(spawn, after=tampered_after)
    spawn_records = tuple(
        _reassociate_records(result.records, spawn.stable_id(), tampered.stable_id())
    )
    tampered_audit = auditor.validate_execution(
        (tampered, *spawn_mutations[1:]),
        spawn_records,
    )
    assert not tampered_audit.ok
    assert "summoned_monster_birth_stat_mismatch:max_hp" in {
        violation.reason for violation in tampered_audit.violations
    }

    # A swapped ratio row (weaker level context recorded on the mutation) is
    # rejected by the formal wave level policy comparison as well.
    metadata = json.loads(json.dumps(spawn.metadata))
    metadata["summon_level_context"]["ratios"]["max_hp"] = 1.0
    swapped = replace(spawn, metadata=metadata)
    swapped_records = tuple(
        _reassociate_records(result.records, spawn.stable_id(), swapped.stable_id())
    )
    swapped_audit = auditor.validate_execution(
        (swapped, *spawn_mutations[1:]),
        swapped_records,
    )
    assert not swapped_audit.ok
    reasons = {violation.reason for violation in swapped_audit.violations}
    # The panel still equals profile base times the formal policy row, so the
    # swapped recorded ratio is rejected by the context/plan comparisons instead.
    assert "summon_level_ratio_mismatch:max_hp:context" in reasons
    assert "summon_level_context_carried_mismatch" in reasons
    assert "summon_birth_settlement_context_mismatch" in reasons

def _spawn_case():
    rules, session, intent, entry, template, gauge = _case()
    system = SummonSystem(rules)
    plan = system.plan_spawn_from_intent(session.state, intent, owner_id=_LIEUT_UNIT_ID)
    assert plan.ok, plan.blocked_reason
    result = system.apply_spawn(session.state, plan)
    assert result.plan.ok, result.plan.blocked_reason
    spawn = next(m for m in result.mutations if m.op == "spawn")
    return rules, session, result, spawn


@pytest.mark.parametrize(
    "case",
    [
        # First review batch: archive selected from metadata instead of formal IR.
        "other_card_profile",
        "changed_delay",
        "carried_context",
        "wrong_hard_level_row",
        "missing_operation",
        # Follow-up review: kind trusted from the label, loose payload and plan
        # acceptance, and incomplete context/scaling copies.
        "servant_kind_bypass",
        "non_object_birth",
        "wrong_record_producer",
        "nested_unit_context_source",
        "unit_scaling_level",
    ],
)
def test_birth_audit_rejects_mismatched_formal_identity(case):
    rules, session, result, spawn = _spawn_case()
    after = json.loads(json.dumps(spawn.after))
    metadata = json.loads(json.dumps(spawn.metadata))
    record_type = "summon_transition"
    record_source = "summon_system"
    if case == "other_card_profile":
        foreign_id = session.state.units[_LIEUT_UNIT_ID].flags["combatant_profile_id"]
        profile = rules.combatant_profile_by_profile_id(foreign_id)
        assert profile is not None and foreign_id != metadata["combatant_profile_id"]
        metadata["combatant_profile_id"] = foreign_id
        for field in _STAT_FIELDS:
            base = (
                profile.toughness_profile[field]
                if field == "max_toughness"
                else profile.base_stats[field]
            )
            after[field] = base * metadata["summon_level_context"]["ratios"][field]
        after["hp"] = after["max_hp"]
        after["toughness"] = after["max_toughness"]
        after["action_value"] = _case()[-1] / after["speed"]
    elif case == "changed_delay":
        metadata["summon_delay_policy"]["value"] *= 2
        after["action_value"] *= 2
    elif case == "carried_context":
        after["flags"]["summon_level_context"]["ratios"]["attack"] = 999
    elif case == "wrong_hard_level_row":
        metadata["summon_level_context"]["source_trace"]["hard_level_profile"]["raw_id"] = "1:44"
    elif case == "missing_operation":
        metadata.pop("summon_operation")
        after["max_hp"] += 1
    elif case == "servant_kind_bypass":
        after["flags"]["summon_kind"] = "servant"
        metadata["summon_operation"] = "servant_spawn"
        after["max_hp"] += 1
    elif case == "non_object_birth":
        after = 123
    elif case == "nested_unit_context_source":
        after["flags"]["summon_level_context"]["source_trace"]["hard_level_profile"]["raw_id"] = "1:44"
    elif case == "unit_scaling_level":
        after["flags"]["summon_stat_scaling"]["level"] = 999
    elif case == "wrong_record_producer":
        pass
    else:  # pragma: no cover - parametrization guard
        raise AssertionError(case)
    if case == "wrong_record_producer":
        record_type = "unrelated"
        record_source = "unrelated"
    changed = replace(spawn, after=after, metadata=metadata)
    records = _reassociate_records(
        result.records,
        spawn.stable_id(),
        changed.stable_id(),
        record_type=record_type,
        source=record_source,
    )
    mutations = tuple(changed if m is spawn else m for m in result.mutations)
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, tuple(records))
    assert not audit.ok, f"audit accepted {case}"
