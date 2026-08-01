from __future__ import annotations

import argparse
import json
import resource
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from ..build_types import aggregate_static_stat_contributions
from ..builds.character_assembler import assemble_character_build
from ..builds.manifest import BuildLockedReplayVerifier, canonical_ir_fingerprint
from ..builds.models import CharacterBuildInput, CharacterInitialConditionInput
from ..core.model import BattleState, GameEvent, UnitState
from ..equipment.models import (
    EquipmentBuildInput,
    RelicInstanceInput,
    RelicSubAffixRollInput,
)
from ..queries.equipment import EquipmentQueryService
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import (
    BattleSetupSpec,
    ScenarioSpec,
    TimelineSetupSpec,
    UnitSpec,
)
from ..systems.status_callbacks import StatusCallbackSystem
from ..tbgd.light_cone_cards import (
    build_light_cone_catalog,
    require_complete_light_cone_catalog,
)
from .io import write_json
from .validate_p8_s15_relic_set_dynamic_startup import _build_bundle


SEELE_CARD_ID = "character_data_card:avatar:1102"
LIGHT_CONE_ID = "23001"


def validate(tbgd_root: Path, manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    build = CharacterBuildInput.from_json(payload)
    if build.character_card_id != SEELE_CARD_ID:
        raise ValueError("P8-S20 manifest character identity mismatch")

    selected_light_cone = _selected_light_cone(tbgd_root)

    bundle = _build_bundle(
        tbgd_root,
        require_blocked_sample=False,
        inject_duplicate_probe=False,
        required_card_id=build.character_card_id,
        extra_light_cone_definitions=(selected_light_cone,),
    )
    rules: RuleBook = bundle["rules"]
    query = EquipmentQueryService(rules)
    assembly = assemble_character_build(rules, build)
    submission = query.submit_character_build(payload)
    definition_checks = _definition_checks(query, build)
    card = bundle["card"]
    built = _build_formal_scene(rules, card, build, "base")
    legality = _legality_matrix(rules, build, assembly)
    panel = _panel_matrix(assembly)
    mechanisms = _mechanism_matrix(rules, assembly, built)
    counterfactuals = _counterfactual_matrix(
        rules,
        card,
        build,
        assembly,
        built,
        mechanisms,
    )
    sources = _source_matrix(query, assembly, built, mechanisms)
    replay = _replay_matrix(rules, built, mechanisms, counterfactuals)
    static_scan = _static_scan(manifest_path)
    ir_fingerprint = canonical_ir_fingerprint(rules.ir)
    deletion_probe = {
        "manifest_not_referenced_by_production": not static_scan["manifest_references"],
        "rulebook_fingerprint_stable": (
            ir_fingerprint == canonical_ir_fingerprint(rules.ir)
        ),
    }
    checks = {
        "manifest_contains_choices_not_results": _manifest_is_choice_only(payload),
        "all_definition_refs_resolve_current_rulebook": all(definition_checks.values()),
        "six_relic_instances_legal": legality["six_relic_instances_legal"],
        "all_final_sub_affix_values_legal": legality["all_final_sub_affix_values_legal"],
        "outer_four_and_planar_two_active": mechanisms["sets_active"],
        "final_panel_reconstructs_from_ledger": panel["reconstructs"],
        "crit_rate_target_met_without_override": panel["crit_rate_target"],
        "crit_damage_target_met_without_override": panel["crit_damage_target"],
        "attack_target_met_without_override": panel["attack_target"],
        "in_the_night_speed_tiers_runtime_driven": mechanisms["speed_tiers_ok"],
        "rutilant_threshold_runtime_driven": counterfactuals["low_crit"]["isolated"],
        "genius_quantum_weakness_branch_runtime_driven": mechanisms["weakness_branch_ok"],
        "formal_scene_and_provider_registration_succeed": (
            submission.resolution_status == "resolved"
            and assembly.assembly_status == "assembled"
            and assembly.battle_admission_status == "admitted"
            and mechanisms["formal_boundary_ok"]
        ),
        "controlled_negatives_isolated": counterfactuals["all_isolated"],
        "static_and_dynamic_sources_walk_back": sources["ok"],
        "assembly_and_transitions_replay_equal": replay["ok"],
        "production_fixed_example_ids": len(static_scan["production_hits"]),
        "deleting_example_changes_core_behavior": not all(deletion_probe.values()),
    }
    ok = all(
        value == 0
        if key == "production_fixed_example_ids"
        else value is False
        if key == "deleting_example_changes_core_behavior"
        else value is True
        for key, value in checks.items()
    )
    assembly_evidence = {
        "checks": checks,
        "definition_checks": definition_checks,
        "submission": _submission_evidence(submission),
        "assembly": _assembly_evidence(assembly),
        "legality": legality,
        "panel": panel,
    }
    runtime_evidence = {
        "mechanisms": _public_mechanisms(mechanisms),
        "counterfactuals": _public_counterfactuals(counterfactuals),
        "sources": sources,
        "replay": replay,
        "static_scan": static_scan,
        "deletion_probe": deletion_probe,
        "external_character_content_dependency": {
            "status": "deferred",
            "reason": "character_action_graph_not_required_for_equipment_build_slice",
        },
    }
    artifacts = {
        "assembly_legality_panel_p8_s20.json": assembly_evidence,
        "runtime_condition_audit_replay_p8_s20.json": runtime_evidence,
    }
    for name, evidence in artifacts.items():
        write_json(output_dir / name, evidence)
    summary = {
        "ok": ok,
        "ready_for_review": ok,
        "predicates": checks,
        "resources": {
            "wall_seconds": round(time.monotonic() - started, 6),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "focused_rulebooks": 1,
            "full_lowering": 0,
            "artifact_files": list(artifacts),
            "artifact_bytes_before_summary": sum(
                (output_dir / name).stat().st_size for name in artifacts
            ),
        },
        "implementation_status": "ready_for_review" if ok else "blocked",
    }
    write_json(
        output_dir / "validation_summary_p8_s20_seele_complete_build_slice.json",
        summary,
    )
    return summary


def _selected_light_cone(tbgd_root: Path) -> Any:
    definitions = require_complete_light_cone_catalog(
        build_light_cone_catalog(tbgd_root.resolve())
    )
    selected = tuple(
        item
        for item in definitions
        if item.definition_key.definition_identity == LIGHT_CONE_ID
    )
    if len(selected) != 1:
        raise ValueError(f"P8-S20 light-cone definition count:{len(selected)}")
    return selected[0]


def _definition_checks(
    query: EquipmentQueryService,
    build: CharacterBuildInput,
) -> dict[str, bool]:
    equipment = build.equipment_build
    light_cone = equipment.light_cone
    checks = {
        "light_cone": light_cone is not None
        and query.get_light_cone(
            light_cone.definition_key.definition_identity
        ).resolution_status
        == "resolved",
    }
    for relic in equipment.relics:
        identity = relic.template_key.definition_identity
        checks[f"relic_template:{identity}"] = (
            query.get_relic_template(identity).resolution_status == "resolved"
            and query.get_relic_template_affixes(identity).resolution_status
            == "resolved"
        )
    return checks


def _build_formal_scene(
    rules: RuleBook,
    card: Any,
    build: CharacterBuildInput,
    tag: str,
) -> Any:
    scenario = ScenarioSpec(
        scenario_id=f"validation:p8_s20:{tag}",
        version="p8-s20",
        units=(
            UnitSpec(
                unit_id="ally:seele",
                side="ally",
                entity_ref=card.entity_ref,
                build_mode="assembled_character_build",
                level=build.level,
                eidolon_level=build.eidolon_level,
                panel=None,
                character_build=build,
                initial_condition=CharacterInitialConditionInput(
                    hp_mode="full",
                    initial_energy="0",
                ),
            ),
        ),
        route=(),
        battle_setup=BattleSetupSpec(
            timeline=TimelineSetupSpec(mode="runtime_initialize")
        ),
    )
    return ScenarioStateBuilder(rules).build(scenario)


def _legality_matrix(
    rules: RuleBook,
    build: CharacterBuildInput,
    result: Any,
) -> dict[str, Any]:
    equipment = result.equipment_assembly_result
    if equipment is None:
        return {
            "six_relic_instances_legal": False,
            "all_final_sub_affix_values_legal": False,
            "rows": [],
        }
    inputs = {item.instance_id: item for item in build.equipment_build.relics}
    rows: list[dict[str, Any]] = []
    for selection in equipment.relic_selections:
        instance = inputs.get(selection.instance_id)
        main_expected = (
            Decimal(selection.main_affix.calculation.base_value)
            + Decimal(selection.main_affix.calculation.per_level_value)
            * selection.main_affix.calculation.level_offset
        )
        sub_rows = []
        for item in selection.sub_affixes:
            roll = next(
                (
                    candidate
                    for candidate in (instance.sub_affix_rolls if instance else ())
                    if candidate.affix_key == item.affix_key
                ),
                None,
            )
            expected = (
                Decimal(item.base_value) * item.count
                + Decimal(item.step_value) * item.step
            )
            sub_rows.append(
                {
                    "affix": item.affix_key.stable_id,
                    "property": item.property_type,
                    "count": item.count,
                    "step": item.step,
                    "exact_value": item.exact_value,
                    "ok": (
                        roll is not None
                        and roll.count == item.count
                        and roll.step == item.step
                        and item.count > 0
                        and 0 <= item.step <= item.count * item.step_count
                        and expected == Decimal(item.exact_value)
                    ),
                }
            )
        rows.append(
            {
                "instance_id": selection.instance_id,
                "slot": selection.slot_key.definition_identity,
                "level": selection.level,
                "main_property": selection.main_affix.property_type,
                "main_exact_value": selection.main_affix.exact_value,
                "main_ok": (
                    instance is not None
                    and instance.instance_fingerprint
                    == selection.instance_fingerprint
                    and instance.main_affix_key == selection.main_affix.affix_key
                    and selection.level == 15
                    and main_expected == Decimal(selection.main_affix.exact_value)
                ),
                "sub_affixes": sub_rows,
            }
        )
    six_legal = (
        len(inputs) == len(rows) == 6
        and {row["slot"] for row in rows}
        == {"HEAD", "HAND", "BODY", "FOOT", "NECK", "OBJECT"}
        and all(row["main_ok"] for row in rows)
    )
    sub_legal = (
        sum(len(row["sub_affixes"]) for row in rows) == 24
        and all(
            item["ok"]
            for row in rows
            for item in row["sub_affixes"]
        )
    )
    return {
        "six_relic_instances_legal": six_legal,
        "all_final_sub_affix_values_legal": sub_legal,
        "rows": rows,
        "rulebook_definition_count": len(rules.ir.relic_template_definitions),
    }


def _panel_matrix(result: Any) -> dict[str, Any]:
    if result.base_panel is None:
        return {
            "reconstructs": False,
            "crit_rate_target": False,
            "crit_damage_target": False,
            "attack_target": False,
        }
    aggregates = aggregate_static_stat_contributions(result.contribution_ledger)
    panel_json = result.base_panel.to_json()
    actual = {
        key: value
        for key, value in panel_json.items()
        if key
        in {
            "max_hp",
            "attack",
            "defense",
            "speed",
            "max_energy",
            "critical_chance",
            "critical_damage",
            "base_aggro",
        }
    }
    actual.update(
        {
            item["property_type"]: item["exact_value"]
            for item in panel_json["additional_resources"]
        }
    )
    expected = {item.property_type: item.final_value for item in aggregates}
    reconstructs = set(actual) == set(expected) and all(
        Decimal(str(actual[key])) == Decimal(expected[key]) for key in expected
    )
    crit_rate = Decimal(str(panel_json["critical_chance"]))
    crit_damage = Decimal(str(panel_json["critical_damage"]))
    attack = Decimal(str(panel_json["attack"]))
    return {
        "reconstructs": reconstructs,
        "crit_rate_target": Decimal("0.75") <= crit_rate <= Decimal("0.85"),
        "crit_damage_target": crit_damage >= Decimal("1.60"),
        "attack_target": attack >= Decimal("2900"),
        "panel": panel_json,
        "aggregates": [item.to_json() for item in aggregates],
    }


def _mechanism_matrix(rules: RuleBook, assembly: Any, built: Any) -> dict[str, Any]:
    equipment = assembly.equipment_assembly_result
    registration = built.ability_provider_registration
    if equipment is None or registration is None:
        raise ValueError("P8-S20 formal equipment/provider result missing")
    selections = tuple(equipment.dynamic_mechanisms)
    by_target = {
        item.target_definition_key.stable_id: item for item in selections
    }
    expected_targets = {
        "light_cone::23001",
        "relic_set_threshold::108:4",
        "relic_set_threshold::309:2",
    }
    status_names = _status_names(built.state)
    light_cone = by_target["light_cone::23001"]
    genius = by_target["relic_set_threshold::108:4"]
    rutilant = by_target["relic_set_threshold::309:2"]

    parameter_bindings = tuple(
        sorted(light_cone.parameter_bindings, key=lambda item: item.parameter_index)
    )
    if len(parameter_bindings) != 4:
        raise ValueError(
            f"P8-S20 In the Night parameter count:{len(parameter_bindings)}"
        )
    speed_step = Decimal(parameter_bindings[0].exact_value)
    speed_cap = int(Decimal(parameter_bindings[-1].exact_value))
    current_speed = Decimal(str(built.state.units["ally:seele"].speed))
    speed_inputs = (
        Decimal("100") + speed_step - Decimal("0.1"),
        current_speed,
        Decimal("100") + speed_step * speed_cap + Decimal("20"),
    )
    speed_rows = []
    for speed in speed_inputs:
        row = _run_callback_slice(
            rules,
            built.state,
            light_cone,
            speed=float(speed),
            quantum_weakness=True,
            attack_type="Normal",
        )
        expected_layer = (
            0
            if speed < Decimal("100") + speed_step
            else min(speed_cap, int((speed - Decimal("100")) // speed_step))
        )
        row["expected_layer"] = expected_layer
        row["matches_oracle"] = row["layer"] == expected_layer
        speed_rows.append(row)

    weakness_true = _run_callback_slice(
        rules,
        built.state,
        genius,
        speed=float(current_speed),
        quantum_weakness=True,
        attack_type="Normal",
    )
    weakness_false = _run_callback_slice(
        rules,
        built.state,
        genius,
        speed=float(current_speed),
        quantum_weakness=False,
        attack_type="Normal",
    )
    static_thresholds = _static_threshold_ids(equipment)
    provider_count = len(_provider_payloads(built.state))
    return {
        "sets_active": (
            set(by_target) == expected_targets
            and {"108:2", "309:2"}.issubset(static_thresholds)
        ),
        "formal_boundary_ok": (
            built.build_manifest is not None
            and registration.ok
            and provider_count == len(selections) == 3
            and not built.blocked_setup
        ),
        "speed_tiers_ok": all(
            row["ok"] and row["matches_oracle"] for row in speed_rows
        ),
        "weakness_branch_ok": (
            weakness_true["ok"]
            and weakness_false["ok"]
            and _condition_value(weakness_true, "ByHasStanceWeak") is True
            and _condition_value(weakness_false, "ByHasStanceWeak") is False
            and weakness_true["damage_modifier_terms"]
            == weakness_false["damage_modifier_terms"] + 1
        ),
        "dynamic_targets": sorted(by_target),
        "static_thresholds": sorted(static_thresholds),
        "status_names": sorted(status_names),
        "rutilant_sub_modifier": _on_before_hit_modifier(rules, rutilant),
        "speed_rows": speed_rows,
        "weakness_true": weakness_true,
        "weakness_false": weakness_false,
        "_selections": by_target,
    }


def _run_callback_slice(
    rules: RuleBook,
    state: BattleState,
    selection: Any,
    *,
    speed: float,
    quantum_weakness: bool,
    attack_type: str,
) -> dict[str, Any]:
    callback = _on_before_hit_callback(rules, selection)
    controlled = _runtime_condition_state(
        state,
        speed=speed,
        quantum_weakness=quantum_weakness,
    )
    event = GameEvent(
        event_type="validation.p8_s20.runtime_condition_slice",
        source_id="ally:seele",
        target_id="enemy:target",
        window="OnBeforeHitAll",
        process_only=True,
        payload={
            "actor_id": "ally:seele",
            "target_id": "enemy:target",
            "current_hit_target_id": "enemy:target",
            "selected_target_ids": ["enemy:target"],
            "AttackType": attack_type,
            "attack_type": attack_type,
        },
    )
    result = StatusCallbackSystem(rules).execute(
        controlled,
        unit_id="ally:seele",
        modifier_name=callback.modifier_name,
        event=callback.event,
        trigger_event=event,
    )
    layer_values = [
        record.get("payload", {}).get("value")
        for record in result.records
        if record.get("record_type") == "status_dynamic_value"
        and record.get("payload", {}).get("dynamic_key") == "_Layer"
    ]
    condition_rows = [
        record.get("payload", {}).get("condition_result", {})
        for record in result.records
        if record.get("record_type") == "status_callback_task_blocked"
        and record.get("payload", {}).get("condition_result")
    ]
    damage_terms = sum(
        int(record.get("payload", {}).get("term_count") or 0)
        for record in result.records
        if record.get("record_type") == "damage_modifier_task"
    )
    return {
        "ok": result.ok and not result.errors,
        "speed": speed,
        "quantum_weakness": quantum_weakness,
        "modifier_name": callback.modifier_name,
        "layer": int(layer_values[-1]) if layer_values else 0,
        "damage_modifier_terms": damage_terms,
        "condition_results": [
            {
                "opcode": str(item.get("opcode") or ""),
                "result": item.get("result"),
                "details": item.get("details", {}),
            }
            for item in condition_rows
        ],
        "condition_sources": sorted(
            {
                str(item.get("source_trace", {}).get("source_path") or "")
                for item in condition_rows
                if isinstance(item, Mapping)
            }
        ),
        "mutation_count": len(result.mutations),
        "_before_state": controlled,
        "_result": result,
    }


def _runtime_condition_state(
    state: BattleState,
    *,
    speed: float,
    quantum_weakness: bool,
) -> BattleState:
    wearer = state.units["ally:seele"]
    pools = tuple(
        replace(
            pool,
            static_flat=speed - pool.base_value * (1 + pool.static_percentage),
        )
        if pool.property_type == "speed"
        else pool
        for pool in wearer.stat_pools
    )
    wearer = replace(wearer, speed=speed, stat_pools=pools)
    target = UnitState(
        unit_id="enemy:target",
        side="enemy",
        template_id="validation:p8_s20:condition_target",
        max_hp=100.0,
        hp=100.0,
        flags={"weaknesses": ["Quantum"] if quantum_weakness else []},
    )
    return replace(state, units={**state.units, wearer.unit_id: wearer, target.unit_id: target})


def _on_before_hit_callback(rules: RuleBook, selection: Any) -> Any:
    graph = rules.standalone_ability_graph(selection.graph_ref_id)
    if graph is None:
        raise ValueError("P8-S20 dynamic graph missing")
    callbacks = tuple(
        item
        for item in rules.ir.status_callbacks
        if item.callback_id in graph.status_callback_ids
        and item.event == "OnBeforeHitAll"
        and item.coverage_status == "executable"
        and item.admission_status == "executable"
    )
    if len(callbacks) != 1:
        raise ValueError(f"P8-S20 OnBeforeHitAll callback count:{len(callbacks)}")
    return callbacks[0]


def _on_before_hit_modifier(rules: RuleBook, selection: Any) -> str:
    return _on_before_hit_callback(rules, selection).modifier_name


def _condition_value(row: dict[str, Any], opcode: str) -> bool | None:
    values = [
        item.get("result")
        for item in row["condition_results"]
        if item.get("opcode") == opcode
    ]
    return values[0] if len(values) == 1 and isinstance(values[0], bool) else None


def _counterfactual_matrix(
    rules: RuleBook,
    card: Any,
    build: CharacterBuildInput,
    assembly: Any,
    built: Any,
    mechanisms: dict[str, Any],
) -> dict[str, Any]:
    original_equipment = assembly.equipment_assembly_result
    if original_equipment is None:
        raise ValueError("P8-S20 original equipment assembly missing")
    variants = {
        "low_crit": _lower_critical_chance_build(rules, build, assembly),
        "outer_removed": _remove_slot_build(build, "HEAD", "outer-removed"),
        "planar_removed": _remove_slot_build(build, "NECK", "planar-removed"),
    }
    rows: dict[str, dict[str, Any]] = {}
    for name, candidate in variants.items():
        result = assemble_character_build(rules, candidate)
        candidate_built = _build_formal_scene(rules, card, candidate, name)
        equipment = result.equipment_assembly_result
        if equipment is None:
            raise ValueError(f"P8-S20 {name} equipment assembly missing")
        rows[name] = {
            "assembly_status": result.assembly_status,
            "battle_admission_status": result.battle_admission_status,
            "critical_chance": (
                result.base_panel.critical_chance if result.base_panel else ""
            ),
            "dynamic_targets": sorted(_dynamic_target_ids(equipment)),
            "static_thresholds": sorted(_static_threshold_ids(equipment)),
            "status_names": sorted(_status_names(candidate_built.state)),
            "provider_count": len(_provider_payloads(candidate_built.state)),
            "build_fingerprint_changed": (
                candidate.input_fingerprint != build.input_fingerprint
            ),
            "_build": candidate,
            "_assembly": result,
            "_built": candidate_built,
        }

    original_targets = _dynamic_target_ids(original_equipment)
    original_static = _static_threshold_ids(original_equipment)
    original_statuses = _status_names(built.state)
    rutilant_sub = mechanisms["rutilant_sub_modifier"]
    low = rows["low_crit"]
    low["isolated"] = (
        Decimal(str(low["critical_chance"])) < Decimal("0.7")
        and set(low["dynamic_targets"]) == original_targets
        and original_statuses.difference(low["status_names"]) == {rutilant_sub}
        and not set(low["status_names"]).difference(original_statuses)
        and low["provider_count"] == 3
    )
    outer = rows["outer_removed"]
    outer["isolated"] = (
        set(outer["dynamic_targets"])
        == original_targets.difference({"relic_set_threshold::108:4"})
        and "108:2" in outer["static_thresholds"]
        and "309:2" in outer["static_thresholds"]
        and outer["provider_count"] == 2
    )
    planar = rows["planar_removed"]
    planar["isolated"] = (
        set(planar["dynamic_targets"])
        == original_targets.difference({"relic_set_threshold::309:2"})
        and "309:2" not in planar["static_thresholds"]
        and set(planar["static_thresholds"])
        == original_static.difference({"309:2"})
        and planar["provider_count"] == 2
    )
    no_weakness = {
        "isolated": mechanisms["weakness_branch_ok"],
        "with_quantum_weakness_terms": mechanisms["weakness_true"][
            "damage_modifier_terms"
        ],
        "without_quantum_weakness_terms": mechanisms["weakness_false"][
            "damage_modifier_terms"
        ],
    }
    admitted = all(
        row["assembly_status"] == "assembled"
        and row["battle_admission_status"] == "admitted"
        and row["build_fingerprint_changed"]
        and row["_built"].build_manifest is not None
        and row["_built"].ability_provider_registration is not None
        and row["_built"].ability_provider_registration.ok
        for row in rows.values()
    )
    return {
        **rows,
        "no_quantum_weakness": no_weakness,
        "all_isolated": (
            admitted
            and all(row["isolated"] for row in rows.values())
            and no_weakness["isolated"]
        ),
    }


def _lower_critical_chance_build(
    rules: RuleBook,
    build: CharacterBuildInput,
    assembly: Any,
) -> CharacterBuildInput:
    equipment = assembly.equipment_assembly_result
    if equipment is None:
        raise ValueError("P8-S20 low-crit source assembly missing")
    selections = {item.instance_id: item for item in equipment.relic_selections}
    relics: list[RelicInstanceInput] = []
    replacements = 0
    for relic in build.equipment_build.relics:
        selection = selections[relic.instance_id]
        critical = next(
            (
                item
                for item in selection.sub_affixes
                if item.property_type == "CriticalChanceBase"
            ),
            None,
        )
        if critical is None:
            relics.append(relic)
            continue
        template_resolution = rules.relic_template_definition(
            relic.template_key.definition_identity
        )
        if template_resolution.value is None:
            raise ValueError("P8-S20 low-crit template missing")
        group_resolution = rules.relic_sub_affix_group_definition(
            template_resolution.value.sub_affix_group_key.definition_identity
        )
        if group_resolution.value is None:
            raise ValueError("P8-S20 low-crit sub-affix group missing")
        occupied = {
            item.property_type
            for item in selection.sub_affixes
            if item.affix_key != critical.affix_key
        }
        occupied.add(selection.main_affix.property_type)
        alternatives = []
        for key in group_resolution.value.affix_keys:
            resolution = rules.relic_sub_affix_definition(key.definition_identity)
            if (
                resolution.value is not None
                and resolution.value.property_type not in occupied
                and resolution.value.property_type != "CriticalChanceBase"
            ):
                alternatives.append(resolution.value)
        if not alternatives:
            raise ValueError("P8-S20 low-crit legal replacement missing")
        alternative = sorted(
            alternatives,
            key=lambda item: item.definition_key.stable_id,
        )[0]
        rolls = tuple(
            RelicSubAffixRollInput(
                affix_key=alternative.definition_key,
                count=roll.count,
                step=min(
                    roll.step,
                    roll.count * alternative.step_count,
                ),
            )
            if roll.affix_key == critical.affix_key
            else roll
            for roll in relic.sub_affix_rolls
        )
        relics.append(replace(relic, sub_affix_rolls=rolls))
        replacements += 1
    if replacements != 5:
        raise ValueError(f"P8-S20 critical sub-affix replacement count:{replacements}")
    return _derived_build(build, tuple(relics), "low-crit")


def _remove_slot_build(
    build: CharacterBuildInput,
    slot: str,
    tag: str,
) -> CharacterBuildInput:
    relics = tuple(
        item
        for item in build.equipment_build.relics
        if item.slot_key.definition_identity != slot
    )
    if len(relics) != len(build.equipment_build.relics) - 1:
        raise ValueError(f"P8-S20 removable slot count invalid:{slot}")
    return _derived_build(build, relics, tag)


def _derived_build(
    build: CharacterBuildInput,
    relics: tuple[RelicInstanceInput, ...],
    tag: str,
) -> CharacterBuildInput:
    equipment = EquipmentBuildInput(
        build_id=f"{build.equipment_build.build_id}:{tag}",
        character_card_id=build.character_card_id,
        light_cone=build.equipment_build.light_cone,
        relics=relics,
        identity_labels=dict(build.equipment_build.identity_labels),
    )
    return replace(
        build,
        build_id=f"{build.build_id}:{tag}",
        equipment_build=equipment,
    )


def _source_matrix(
    query: EquipmentQueryService,
    assembly: Any,
    built: Any,
    mechanisms: dict[str, Any],
) -> dict[str, Any]:
    equipment = assembly.equipment_assembly_result
    registration = built.ability_provider_registration
    if equipment is None or registration is None:
        raise ValueError("P8-S20 source audit inputs missing")
    static_views = tuple(
        query.get_static_contribution_source(assembly, item.contribution_id)
        for item in equipment.static_contributions
    )
    transition = registration.to_transition()
    provider_mutations = tuple(
        item
        for item in registration.mutations
        if item.source == "ability_provider_registry"
    )
    if len(provider_mutations) != 1:
        raise ValueError("P8-S20 provider mutation count invalid")
    mutation = provider_mutations[0]
    providers = mutation.metadata.get("providers")
    if not isinstance(providers, (list, tuple)):
        raise TypeError("P8-S20 provider payload missing")
    dynamic_views = tuple(
        query.get_dynamic_mutation_source(
            assembly,
            transition,
            mutation.stable_id(),
            provider_id=str(provider.get("provider_id") or ""),
        )
        for provider in providers
        if isinstance(provider, Mapping)
    )
    condition_sources = sorted(
        {
            path
            for row in (
                *mechanisms["speed_rows"],
                mechanisms["weakness_true"],
                mechanisms["weakness_false"],
            )
            for path in row["condition_sources"]
        }
    )
    ok = (
        len(static_views) == len(equipment.static_contributions)
        and all(item.resolution_status == "resolved" for item in static_views)
        and len(dynamic_views) == len(equipment.dynamic_mechanisms) == 3
        and all(item.resolution_status == "resolved" for item in dynamic_views)
        and bool(condition_sources)
        and all(
            path.startswith("Config/ConfigAbility/Equip/")
            for path in condition_sources
        )
    )
    return {
        "ok": ok,
        "static_resolved": sum(
            item.resolution_status == "resolved" for item in static_views
        ),
        "static_total": len(static_views),
        "dynamic_resolved": sum(
            item.resolution_status == "resolved" for item in dynamic_views
        ),
        "dynamic_total": len(dynamic_views),
        "dynamic_targets": sorted(
            str(
                item.to_json()
                .get("target_definition", {})
                .get("definition_key", {})
                .get("stable_id", "")
            )
            for item in dynamic_views
        ),
        "condition_source_paths": condition_sources,
        "static_sample_ids": [item.contribution_id for item in static_views[:6]],
    }


def _replay_matrix(
    rules: RuleBook,
    built: Any,
    mechanisms: dict[str, Any],
    counterfactuals: dict[str, Any],
) -> dict[str, Any]:
    verifier = BuildLockedReplayVerifier(rules)
    rows: dict[str, dict[str, Any]] = {}

    def replay_registration(name: str, candidate: Any) -> None:
        registration = candidate.ability_provider_registration
        if registration is None:
            rows[name] = {"ok": False, "errors": ["registration_missing"]}
            return
        result = verifier.replay_snapshot(
            registration.before_state,
            registration.mutations,
            registration.after_state.snapshot().to_json(),
        )
        rows[name] = {
            "ok": result.ok and result.build_manifest_verified,
            "errors": list(result.errors),
            "mutation_count": len(registration.mutations),
        }

    replay_registration("base_provider_registration", built)
    for name in ("low_crit", "outer_removed", "planar_removed"):
        replay_registration(
            f"{name}_provider_registration",
            counterfactuals[name]["_built"],
        )
    speed_row = mechanisms["speed_rows"][1]
    callback = speed_row["_result"]
    callback_replay = verifier.replay_snapshot(
        speed_row["_before_state"],
        callback.mutations,
        callback.after_state.snapshot().to_json(),
    )
    rows["runtime_speed_condition"] = {
        "ok": callback_replay.ok and callback_replay.build_manifest_verified,
        "errors": list(callback_replay.errors),
        "mutation_count": len(callback.mutations),
    }
    return {"ok": all(row["ok"] for row in rows.values()), "rows": rows}


def _provider_payloads(state: BattleState) -> tuple[Mapping[str, Any], ...]:
    providers = state.units["ally:seele"].flags.get("ability_providers", ())
    return tuple(item for item in providers if isinstance(item, Mapping))


def _status_names(state: BattleState) -> set[str]:
    details = state.units["ally:seele"].flags.get("status_details", ())
    return {
        str(item.get("modifier_name") or "")
        for item in details
        if isinstance(item, Mapping) and item.get("modifier_name")
    }


def _dynamic_target_ids(equipment: Any) -> set[str]:
    return {
        item.target_definition_key.stable_id
        for item in equipment.dynamic_mechanisms
    }


def _static_threshold_ids(equipment: Any) -> set[str]:
    return {
        item.source_ref.definition_identity
        for item in equipment.static_contributions
        if item.source_ref.definition_kind == "relic_set_threshold"
    }


def _public_callback_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _public_mechanisms(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (
            [_public_callback_row(row) for row in item]
            if key == "speed_rows"
            else _public_callback_row(item)
            if key in {"weakness_true", "weakness_false"}
            else item
        )
        for key, item in value.items()
        if not key.startswith("_")
    }


def _public_counterfactuals(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, row in value.items():
        if name == "all_isolated":
            result[name] = row
        elif isinstance(row, dict):
            result[name] = {
                key: item for key, item in row.items() if not key.startswith("_")
            }
    return result


def _static_scan(manifest_path: Path) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    tokens = (
        "character_data_card:avatar:1102",
        "avatar:1102",
        "\"23001\"",
        "'23001'",
        "61081",
        "61082",
        "61083",
        "61084",
        "63095",
        "63096",
        "relic_set_threshold::108:4",
        "relic_set_threshold::309:2",
        "seele_complete_equipment",
    )
    production_hits: list[dict[str, str]] = []
    manifest_references: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts[0] == "tools":
            continue
        text = path.read_text(encoding="utf-8")
        for token in tokens:
            if token.lower() in text.lower():
                production_hits.append({"path": str(relative), "token": token})
        if manifest_path.name in text:
            manifest_references.append(str(relative))
    return {
        "production_hits": production_hits,
        "manifest_references": manifest_references,
        "scanned_root": str(root),
    }


def _submission_evidence(submission: Any) -> dict[str, Any]:
    summary = submission.summary
    return {
        "resolution_status": submission.resolution_status,
        "blocked_reason": submission.blocked_reason,
        "assembly_status": summary.assembly_status if summary else "",
        "battle_admission_status": (
            summary.battle_admission_status if summary else ""
        ),
        "input_fingerprint": summary.input_fingerprint if summary else "",
        "result_fingerprint": summary.result_fingerprint if summary else "",
    }


def _manifest_is_choice_only(payload: object) -> bool:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden = (
        "final_panel",
        "exact_value",
        "active_flag",
        "settlement",
        "damage_result",
        "speed_tier",
        "roll_history",
        "upgrade_history",
    )
    return not any(token in encoded for token in forbidden)


def _assembly_evidence(result: Any) -> dict[str, Any]:
    equipment = result.equipment_assembly_result
    return {
        "assembly_status": result.assembly_status,
        "battle_admission_status": result.battle_admission_status,
        "blocked_reasons": list(result.blocked_reasons),
        "diagnostics": [
            item.to_json() for item in result.unadmitted_mechanism_diagnostics
        ],
        "base_panel": result.base_panel.to_json() if result.base_panel is not None else None,
        "ledger_term_count": len(result.contribution_ledger),
        "dynamic_mechanism_count": len(result.admitted_dynamic_mechanism_refs),
        "equipment": (
            {
                "assembly_status": equipment.assembly_status,
                "battle_admission_status": equipment.battle_admission_status,
                "diagnostics": list(equipment.diagnostics),
                "battle_admission_blockers": [
                    item.to_json() for item in equipment.battle_admission_blockers
                ],
                "relic_selection_count": len(equipment.relic_selections),
                "static_contribution_count": len(equipment.static_contributions),
                "dynamic_mechanism_count": len(equipment.dynamic_mechanisms),
            }
            if equipment is not None
            else None
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate P8-S20 Seele build slice")
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = validate(args.tbgd_root, args.manifest, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
