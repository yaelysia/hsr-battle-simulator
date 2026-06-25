from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import GameEvent
from ..rules.ir import CharacterDataCardIR, EffectIR, RuleEntity
from ..rules.rulebook import RuleBook
from ..scenarios import PanelInput, ScenarioSpec, ScenarioStateBuilder, UnitSpec
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_268"
SEELE_ENTITY_REF = "avatar:1102"
ENHANCED_SEELE_RANK_IDS = ("1110201", "1110202", "1110203", "1110204", "1110205", "1110206")
ADVANCED_SEELE_ABILITY_PATH = "Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    card = _seele_card(rules)
    modifier_case = _modifier_definition_source_case(rules)
    eidolon_case = _eidolon_runtime_effect_case(rules, card)
    checks = {
        "modifier_definition_sources": modifier_case["checks"],
        "eidolon_runtime_effects": eidolon_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": {
                "seele_card": "Seele is the user-requested example card; runtime/core remains free of character-name special cases.",
                "eidolon_effects": "Selected from enhanced CharacterDataCardIR eidolon slots, RankAbility source, and StatusCallbackIR opcode evidence.",
                "rank4_kill_energy": "Selected by enhanced Rank04 OnTriggerDeath ModifySPNew source; assertion is energy mutation, not skill point mutation.",
            },
        },
        "checks": checks,
        "modifier_definition_source_case": modifier_case,
        "eidolon_runtime_effect_case": eidolon_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_268.json", result)
    write_json(output_dir / "seele_eidolon_effects_v0_268.json", eidolon_case)
    write_json(output_dir / "modifier_definition_sources_v0_268.json", modifier_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_268 Seele eidolon effects example.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _seele_card(rules: RuleBook) -> CharacterDataCardIR:
    card = rules.character_data_card_for_entity(SEELE_ENTITY_REF)
    if card is None:
        raise RuntimeError("Seele character data card missing")
    return card


def _modifier_definition_source_case(rules: RuleBook) -> dict[str, Any]:
    rank4_definitions = rules.modifier_definitions("MAvatar_Seele_Rank04")
    advanced_rank4 = [
        definition
        for definition in rank4_definitions
        if definition.source.source_path == ADVANCED_SEELE_ABILITY_PATH
    ]
    rank4_effects = _advanced_rank4_modify_sp_effects(rules)
    checks = {
        "rank4_keeps_multiple_definition_sources": len(rank4_definitions) >= 2,
        "rank4_advanced_definition_present": len(advanced_rank4) == 1,
        "rank4_modify_sp_effect_present": len(rank4_effects) >= 1,
        "rank4_modify_sp_targets_energy": all(
            _standard_payload(effect).get("resource") == "energy"
            for effect in rank4_effects
        ),
        "rank4_modify_sp_no_skill_point_payload": all(
            _standard_payload(effect).get("resource") != "skill_points"
            for effect in rank4_effects
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "rank4_modifier_definitions": [definition.to_json() for definition in rank4_definitions],
        "rank4_modify_sp_effects": [effect.to_json() for effect in rank4_effects],
    }


def _eidolon_runtime_effect_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    e4_state = _state_for_eidolon_level(rules, 4)
    e6_state = _state_for_eidolon_level(rules, 6)
    e4_details = _status_details(e4_state, "ally:seele")
    rank1_detail = _detail_by_modifier(e4_details, "MAvatar_Seele_Rank01")
    rank4_detail = _detail_by_modifier(e4_details, "MAvatar_Seele_Rank04")
    e4_dispatch = _dispatch_rank4_kill_event(rules, e4_state, kill_credit_owner_id="ally:seele")
    wrong_owner_dispatch = _dispatch_rank4_kill_event(rules, e4_state, kill_credit_owner_id="ally:other")
    e6_flags = dict(e6_state.units["ally:seele"].flags)
    skill_bonus = e6_flags.get("eidolon_skill_level_bonus_by_action_id", {})
    startup_traces = tuple(
        trace
        for trace in _build_result_for_eidolon_level(rules, 6).source_traces
        if isinstance(trace, dict) and trace.get("kind") == "eidolon_startup_rank_ability"
    )
    checks = {
        "card_uses_enhanced_version": card.source.evidence.get("version_kind") == "enhanced",
        "e6_prefix_enables_all_enhanced_ranks": tuple(e6_flags.get("enabled_eidolon_rank_ids", ())) == ENHANCED_SEELE_RANK_IDS,
        "rank1_startup_status_from_advanced": _detail_source_path(rank1_detail) == ADVANCED_SEELE_ABILITY_PATH,
        "rank4_startup_status_from_advanced": _detail_source_path(rank4_detail) == ADVANCED_SEELE_ABILITY_PATH,
        "rank4_callback_from_advanced": any(
            ADVANCED_SEELE_ABILITY_PATH in callback_id
            for callback_id in rank4_detail.get("trigger_ids_by_event", {}).get("OnTriggerDeath", ())
        ),
        "rank4_dynamic_value_bound_to_rank_param": _dynamic_hash_value(rank4_detail, "-636281976") == 15.0,
        "rank4_kill_restores_energy": e4_dispatch["after_energy"] == 15.0,
        "rank4_kill_does_not_restore_skill_points": e4_dispatch["after_skill_points"] == e4_dispatch["before_skill_points"],
        "rank4_kill_energy_mutation_path": e4_dispatch["energy_mutation_path"] == ["units", "ally:seele", "energy"],
        "wrong_owner_kill_does_not_trigger_rank4": not wrong_owner_dispatch["mutations"],
        "e3_e5_skill_level_bonus_flags_present": skill_bonus.get("avatar_skill:1110202") == 2
        and skill_bonus.get("avatar_skill:1110204") == 2
        and skill_bonus.get("avatar_skill:1110203") == 2
        and skill_bonus.get("avatar_skill:1110201") == 1,
        "rank6_startup_has_blocker_or_admitted_trace": any(
            trace.get("eidolon_slot_id", "").endswith(":6")
            and trace.get("status") in {"applied", "blocked"}
            and (trace.get("reason") or trace.get("mutation_count") is not None)
            for trace in startup_traces
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "rank1_status_detail": rank1_detail,
        "rank4_status_detail": rank4_detail,
        "rank4_kill_dispatch": e4_dispatch,
        "wrong_owner_dispatch": wrong_owner_dispatch,
        "e6_eidolon_flags": {
            "enabled_eidolon_rank_ids": list(e6_flags.get("enabled_eidolon_rank_ids", ())),
            "eidolon_skill_level_bonus_by_action_id": skill_bonus,
            "eidolon_startup_rank_abilities": list(e6_flags.get("eidolon_startup_rank_abilities", ())),
        },
        "startup_traces": list(startup_traces),
    }


def _state_for_eidolon_level(rules: RuleBook, eidolon_level: int):
    return _build_result_for_eidolon_level(rules, eidolon_level).state


def _build_result_for_eidolon_level(rules: RuleBook, eidolon_level: int):
    scenario = ScenarioSpec(
        scenario_id=f"seele_eidolon_effect_level_{eidolon_level}",
        version=VALIDATION_VERSION,
        units=(
            UnitSpec(
                unit_id="ally:seele",
                side="ally",
                entity_ref=SEELE_ENTITY_REF,
                level=80,
                eidolon_level=eidolon_level,
                panel=PanelInput(
                    explicit_fields=("max_hp", "hp", "attack", "defense", "speed", "energy", "max_energy"),
                    max_hp=3000.0,
                    hp=3000.0,
                    attack=1200.0,
                    defense=500.0,
                    speed=115.0,
                    energy=0.0,
                    max_energy=120.0,
                ),
            ),
        ),
        skill_points=3,
        max_skill_points=5,
        route=(),
    )
    return ScenarioStateBuilder(rules).build(scenario)


def _dispatch_rank4_kill_event(rules: RuleBook, state, *, kill_credit_owner_id: str) -> dict[str, Any]:
    before_energy = state.units["ally:seele"].energy
    before_skill_points = state.skill_points
    event = GameEvent(
        "unit.defeated",
        source_id=kill_credit_owner_id,
        target_id="enemy:defeated",
        event_id=f"event:{VALIDATION_VERSION}:rank4_kill:{kill_credit_owner_id}",
        window="unit.defeated",
        process_only=True,
        payload={
            "actor_id": kill_credit_owner_id,
            "kill_credit_owner_id": kill_credit_owner_id,
            "kill_credit_source_id": "validation:rank4:lethal_source",
            "kill_credit_source_kind": "validation_damage_source",
            "defeated_unit_id": "enemy:defeated",
        },
    )
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(state, event=event)
    energy_mutations = [
        mutation
        for mutation in result.mutations
        if mutation.path == ("units", "ally:seele", "energy")
    ]
    return {
        "before_energy": before_energy,
        "after_energy": result.after_state.units["ally:seele"].energy,
        "before_skill_points": before_skill_points,
        "after_skill_points": result.after_state.skill_points,
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "records": list(result.records),
        "errors": list(result.errors),
        "energy_mutation_path": list(energy_mutations[0].path) if energy_mutations else [],
    }


def _advanced_rank4_modify_sp_effects(rules: RuleBook) -> tuple[EffectIR, ...]:
    return tuple(
        effect
        for effect in rules.ir.effects
        if effect.opcode == "ModifySPNew"
        and effect.source.source_path == ADVANCED_SEELE_ABILITY_PATH
        and "MAvatar_Seele_Rank04" in str(effect.effect_id)
    )


def _standard_payload(effect: EffectIR) -> dict[str, Any]:
    standard = effect.payload.get("standard")
    return standard if isinstance(standard, dict) else {}


def _status_details(state, unit_id: str) -> tuple[dict[str, Any], ...]:
    details = state.units[unit_id].flags.get("status_details", ())
    return tuple(detail for detail in details if isinstance(detail, dict))


def _detail_by_modifier(details: tuple[dict[str, Any], ...], modifier_name: str) -> dict[str, Any]:
    for detail in details:
        if detail.get("modifier_name") == modifier_name:
            return detail
    return {}


def _detail_source_path(detail: dict[str, Any]) -> str:
    source_trace = detail.get("source_trace")
    if not isinstance(source_trace, dict):
        return ""
    modifier_definition = source_trace.get("modifier_definition")
    if not isinstance(modifier_definition, dict):
        return ""
    return str(modifier_definition.get("source_path") or "")


def _dynamic_hash_value(detail: dict[str, Any], hash_key: str) -> float | None:
    dynamic_values = detail.get("dynamic_values")
    if not isinstance(dynamic_values, dict):
        return None
    by_hash = dynamic_values.get("__by_hash")
    if not isinstance(by_hash, dict):
        return None
    value = by_hash.get(hash_key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
