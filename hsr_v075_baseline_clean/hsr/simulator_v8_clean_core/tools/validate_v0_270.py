from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, GameEvent, UnitState
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import CharacterDataCardIR
from ..rules.rulebook import RuleBook
from ..systems.scheduler import CombatScheduler
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_254 import _transition_checks
from .validate_v0_265 import _select_card_action, _seele_card
from .validate_v0_266 import _callback_transition
from .validate_v0_268 import ADVANCED_SEELE_ABILITY_PATH, ENHANCED_SEELE_RANK_IDS, _build_result_for_eidolon_level


VALIDATION_VERSION = "v0_270"
SEELE_ENTITY_REF = "avatar:1102"
RANK01_ID = "1110201"
RANK06_ID = "1110206"
RANK01_MODIFIER = "MAvatar_Seele_Rank01"
RANK06_LISTENER = "MAvatar_Seele_Rank06"
RANK06_DAMAGE_LISTENER = "MAvatar_Advanced_Seele_Rank06_Skill03Damage"
RANK06_FLAG = "MAvatar_Advanced_Seele_Rank06_Flag"
SEELE_AMPLIFICATION_BUFF = "MAvatar_Advanced_Seele_00_Passive_DamageUp"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    card = _seele_card(rules)
    source_case = _source_case(rules, card)
    e1_case = _eidolon_one_case(rules, card)
    e6_case = _eidolon_six_case(rules, card)
    checks = {
        "source": source_case["checks"],
        "eidolon_one": e1_case["checks"],
        "eidolon_six": e6_case["checks"],
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
                "seele": "Seele is the user-requested character card example; runtime/core contains no Seele special case.",
                "eidolon_one": "Selected from enhanced Rank01 DamageModifierIR and OnBeforeHitAll callback evidence.",
                "eidolon_six": "Selected from enhanced Rank06 status callbacks, AddModifier flag, and true-damage StatusDamageEmissionIR evidence.",
            },
        },
        "checks": checks,
        "source_case": source_case,
        "eidolon_one_case": e1_case,
        "eidolon_six_case": e6_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_270.json", result)
    write_json(output_dir / "seele_e1_damage_modifier_v0_270.json", e1_case)
    write_json(output_dir / "seele_e6_true_damage_v0_270.json", e6_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_270 enhanced Seele E1/E6 generic mechanisms.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _source_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    eidolons = rules.character_eidolon_slots_for_card(card.card_id)
    rank1 = next((slot for slot in eidolons if slot.rank == 1), None)
    rank6 = next((slot for slot in eidolons if slot.rank == 6), None)
    rank1_modifiers = [
        modifier
        for modifier in rules.ir.damage_modifiers
        if modifier.coverage_status == "executable"
        and modifier.event == "OnBeforeHitAll"
        and modifier.modifier_name == RANK01_MODIFIER
        and modifier.source.source_path == ADVANCED_SEELE_ABILITY_PATH
    ]
    rank6_flag_emissions = [
        emission
        for emission in rules.ir.status_damage_emissions
        if emission.coverage_status == "executable"
        and emission.damage_formula_family == "true_damage"
        and emission.modifier_name == RANK06_FLAG
        and emission.source.source_path == ADVANCED_SEELE_ABILITY_PATH
    ]
    rank6_callbacks = [
        callback
        for callback in rules.ir.status_callbacks
        if callback.coverage_status == "executable"
        and callback.source.source_path == ADVANCED_SEELE_ABILITY_PATH
        and callback.modifier_name in {RANK06_LISTENER, RANK06_DAMAGE_LISTENER, RANK06_FLAG}
    ]
    rank6_flag_status = rules.status_entity_for_modifier(RANK06_FLAG)
    amplification_status = rules.status_entity_for_modifier(SEELE_AMPLIFICATION_BUFF)
    checks = {
        "card_uses_enhanced_version": card.source.evidence.get("version_kind") == "enhanced",
        "e6_prefix_enables_all_enhanced_ranks": tuple(slot.rank_id for slot in eidolons) == ENHANCED_SEELE_RANK_IDS,
        "rank1_source_is_enhanced": bool(rank1 and rank1.rank_id == RANK01_ID and rank1.source.source_path == "ExcelOutput/AvatarRankConfig.json"),
        "rank6_source_is_enhanced": bool(rank6 and rank6.rank_id == RANK06_ID and rank6.source.source_path == "ExcelOutput/AvatarRankConfig.json"),
        "rank1_damage_modifier_lowered": bool(rank1_modifiers),
        "rank1_damage_modifier_terms": any(
            {"Attacker_CriticalChance", "Defender_DefenceAddedRatio"}.issubset({term.get("field") for term in modifier.modifier_terms})
            for modifier in rank1_modifiers
        ),
        "rank6_flag_status_config_debuff": (
            rank6_flag_status is not None
            and rank6_flag_status.fields.get("StatusType") == "Debuff"
        ),
        "amplification_status_config_buff": (
            amplification_status is not None
            and amplification_status.fields.get("StatusType") == "Buff"
        ),
        "rank6_callbacks_lowered": {"OnAfterSkillUse", "OnAfterHitAll", "OnAfterBeingAttacked", "OnBeforeDying"}.issubset(
            {callback.event for callback in rank6_callbacks}
        ),
        "rank6_true_damage_emission_lowered": bool(rank6_flag_emissions),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "rank1_slot": rank1.to_json() if rank1 else {},
        "rank6_slot": rank6.to_json() if rank6 else {},
        "rank1_damage_modifier_samples": [modifier.to_json() for modifier in rank1_modifiers[:3]],
        "rank6_callback_samples": [callback.to_json() for callback in rank6_callbacks[:8]],
        "rank6_true_damage_emissions": [emission.to_json() for emission in rank6_flag_emissions[:3]],
    }


def _eidolon_one_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    positive = _execute_rank1_damage_case(rules, card, target_hp=80000.0, target_max_hp=100000.0)
    negative = _execute_rank1_damage_case(rules, card, target_hp=95000.0, target_max_hp=100000.0)
    checks = {
        "positive_transition": positive["checks"]["ok"],
        "positive_applied_damage_modifier": bool(positive["applied_damage_modifier_records"]),
        "positive_crit_term_value": _ledger_term_value(positive, "crit", "critical_chance") == 0.15,
        "positive_defense_term_value": _ledger_term_value(positive, "defense", "defender_defence_added_ratio") == -0.2,
        "negative_transition": negative["checks"]["ok"],
        "negative_no_applied_damage_modifier": not negative["applied_damage_modifier_records"],
        "negative_condition_skipped": bool(negative["skipped_damage_modifier_records"]),
        "negative_no_ledger_terms": _ledger_term_value(negative, "crit", "critical_chance") is None
        and _ledger_term_value(negative, "defense", "defender_defence_added_ratio") is None,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "positive": positive,
        "negative": negative,
    }


def _execute_rank1_damage_case(rules: RuleBook, card: CharacterDataCardIR, *, target_hp: float, target_max_hp: float) -> dict[str, Any]:
    action = _select_card_action(rules, card, attack_type="Normal")
    state = _state_with_target(rules, 1, target_hp=target_hp, target_max_hp=target_max_hp, enemy_id="enemy:target")
    command = ActionCommand(
        actor_id="ally:seele",
        action_id=action.action_id,
        action_level=action.level,
        target_ids=("enemy:target",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": f"{VALIDATION_VERSION}:rank1:{target_hp}/{target_max_hp}"},
    )
    after, transition = CombatExecutor(rules).execute(command, state)
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    records = tuple(transition.transaction.settlement.records)
    applied = tuple(
        record for record in records
        if record.get("record_type") == "damage_modifier" and _payload(record).get("status") == "applied"
    )
    skipped = tuple(
        record for record in records
        if record.get("record_type") == "damage_modifier" and _payload(record).get("status") != "applied"
    )
    damage_mutations = tuple(mutation for mutation in transition.transaction.mutations if mutation.source == "damage_system")
    checks = {
        **_transition_checks(transition, state),
        "source_audit": audit.ok,
        "damage_mutation_present": bool(damage_mutations),
        "target_hp_changed": after.units["enemy:target"].hp < state.units["enemy:target"].hp,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_action": action.to_json(),
        "source_audit": audit.to_json(),
        "applied_damage_modifier_records": [record for record in applied],
        "skipped_damage_modifier_records": [record for record in skipped],
        "damage_mutations": [mutation.to_json() for mutation in damage_mutations],
    }


def _eidolon_six_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    ultimate = _execute_rank6_ultimate_flag_case(rules, card)
    non_ultimate = _execute_rank6_non_ultimate_case(rules, card)
    true_damage = _dispatch_rank6_being_attacked_case(rules, ultimate["after_state"])
    missing_dynamic = _dispatch_rank6_missing_dynamic_case(rules, ultimate["after_state"])
    cleanup = _dispatch_rank6_cleanup_case(rules, ultimate["after_state"])
    lifecycle = _rank6_flag_debuff_lifecycle_case(rules, ultimate["after_state"])
    checks = {
        "ultimate_transition": ultimate["checks"]["ok"],
        "ultimate_applies_flag": ultimate["checks"]["flag_present"],
        "ultimate_flag_duration_three": ultimate["checks"]["flag_duration_three"],
        "ultimate_flag_is_debuff": ultimate["checks"]["flag_is_debuff"],
        "ultimate_amplification_is_buff": ultimate["checks"]["amplification_is_buff"],
        "ultimate_flag_dynamic_value_bound": ultimate["checks"]["flag_dynamic_value_bound"],
        "non_ultimate_transition": non_ultimate["checks"]["ok"],
        "non_ultimate_no_flag": non_ultimate["checks"]["no_flag"],
        "true_damage_transition": true_damage["checks"]["ok"],
        "true_damage_mutation_present": true_damage["checks"]["true_damage_mutation_present"],
        "true_damage_bypasses_direct_ledger": true_damage["checks"]["true_damage_bypasses_direct_ledger"],
        "missing_dynamic_state_unchanged": missing_dynamic["checks"]["state_unchanged"],
        "cleanup_transition": cleanup["checks"]["ok"],
        "cleanup_removed_flag": cleanup["checks"]["flag_removed"],
        "unit_status_lifecycle": lifecycle["checks"]["ok"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "ultimate": _without_state(ultimate),
        "non_ultimate": _without_state(non_ultimate),
        "true_damage": true_damage,
        "missing_dynamic": missing_dynamic,
        "cleanup": cleanup,
        "debuff_lifecycle": lifecycle,
    }


def _execute_rank6_ultimate_flag_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    action = _select_card_action(rules, card, attack_type="Ultra")
    state = _state_with_target(rules, 6, target_hp=1_000_000.0, target_max_hp=1_000_000.0, enemy_id="enemy:target")
    actor = state.units["ally:seele"]
    state = replace(state, units={**state.units, "ally:seele": replace(actor, energy=120.0, max_energy=120.0)})
    command = ActionCommand(
        actor_id="ally:seele",
        action_id=action.action_id,
        action_level=action.level,
        target_ids=("enemy:target",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": f"{VALIDATION_VERSION}:rank6:ultimate"},
    )
    after, transition = CombatExecutor(rules).execute(command, state)
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    flag = _status_detail(after, "enemy:target", RANK06_FLAG)
    amplification = _status_detail(after, "ally:seele", SEELE_AMPLIFICATION_BUFF)
    damage_value = _status_dynamic_value(flag, "MDF_Rank06_DamageValue")
    checks = {
        **_transition_checks(transition, state),
        "source_audit": audit.ok,
        "flag_present": bool(flag),
        "flag_duration_three": _number(flag.get("remaining_duration")) == 3.0 and _number(flag.get("duration")) == 3.0 if flag else False,
        "flag_is_debuff": flag.get("status_type") == "Debuff" and flag.get("status_category") == "debuff" if flag else False,
        "amplification_present": bool(amplification),
        "amplification_is_buff": (
            amplification.get("status_type") == "Buff" and amplification.get("status_category") == "buff"
            if amplification else False
        ),
        "flag_dynamic_value_bound": damage_value is not None and damage_value > 0,
        "flag_callback_hash_bound": _status_dynamic_hash_value(flag, "-1585805301") == damage_value if flag else False,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_action": action.to_json(),
        "source_audit": audit.to_json(),
        "flag_detail": flag,
        "transition": transition.to_json(),
        "after_state": after,
    }


def _execute_rank6_non_ultimate_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    action = _select_card_action(rules, card, attack_type="Normal")
    state = _state_with_target(rules, 6, target_hp=1_000_000.0, target_max_hp=1_000_000.0, enemy_id="enemy:target")
    command = ActionCommand(
        actor_id="ally:seele",
        action_id=action.action_id,
        action_level=action.level,
        target_ids=("enemy:target",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": f"{VALIDATION_VERSION}:rank6:non_ultimate"},
    )
    _after, transition = CombatExecutor(rules).execute(command, state)
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = {
        **_transition_checks(transition, state),
        "source_audit": audit.ok,
        "no_flag": not _status_detail(_after, "enemy:target", RANK06_FLAG),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_action": action.to_json(),
        "source_audit": audit.to_json(),
        "transition": transition.to_json(),
    }


def _dispatch_rank6_being_attacked_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    result = _dispatch_damage_hit(rules, state)
    transition = _event_transition(
        before_state=state,
        result=result,
        action_id="event_dispatch:rank6_flag_being_attacked",
        actor_id="ally:other",
        target_id="enemy:target",
        metadata={"case": "rank6_flag_true_damage"},
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    mutations = tuple(mutation for mutation in result.mutations if mutation.source == "damage_system")
    checks = {
        **_transition_checks(transition, state),
        "source_audit": audit.ok,
        "true_damage_mutation_present": any(mutation.metadata.get("damage_formula_family") == "true_damage" for mutation in mutations),
        "true_damage_bypasses_direct_ledger": all(
            mutation.metadata.get("normal_multiplier_terms") == []
            and mutation.metadata.get("bypasses_normal_multipliers") is True
            for mutation in mutations
            if mutation.metadata.get("damage_formula_family") == "true_damage"
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "source_audit": audit.to_json(),
        "mutations": [mutation.to_json() for mutation in mutations],
        "transition": transition.to_json(),
    }


def _dispatch_rank6_missing_dynamic_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    state_without_dynamic = _remove_flag_dynamic_values(state)
    result = _dispatch_damage_hit(rules, state_without_dynamic)
    transition = _event_transition(
        before_state=state_without_dynamic,
        result=result,
        action_id="event_dispatch:rank6_flag_missing_dynamic",
        actor_id="ally:other",
        target_id="enemy:target",
        metadata={"case": "rank6_flag_missing_dynamic"},
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = {
        **_transition_checks(transition, state_without_dynamic),
        "source_audit": audit.ok,
        "state_unchanged": state_without_dynamic.snapshot().to_json() == result.after_state.snapshot().to_json(),
        "no_damage_mutation": not [mutation for mutation in result.mutations if mutation.source == "damage_system"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "errors": list(result.errors),
        "source_audit": audit.to_json(),
        "transition": transition.to_json(),
    }


def _dispatch_rank6_cleanup_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    event = GameEvent(
        "unit.before_dying",
        source_id="ally:seele",
        target_id="enemy:target",
        window="unit.before_dying",
        process_only=True,
        payload={
            "actor_id": "ally:seele",
            "target_id": "enemy:target",
            "current_hit_target_id": "enemy:target",
            "primary_target_id": "enemy:target",
            "selected_target_ids": ["enemy:target"],
            "target_ids": ["enemy:target"],
        },
    )
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(state, event=event)
    transition = _event_transition(
        before_state=state,
        result=result,
        action_id="event_dispatch:rank6_before_dying_cleanup",
        actor_id="ally:seele",
        target_id="enemy:target",
        metadata={"case": "rank6_before_dying_cleanup"},
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = {
        **_transition_checks(transition, state),
        "source_audit": audit.ok,
        "flag_removed": not _status_detail(result.after_state, "enemy:target", RANK06_FLAG),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "source_audit": audit.to_json(),
        "transition": transition.to_json(),
    }


def _rank6_flag_debuff_lifecycle_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    initial_flag = _status_detail(state, "enemy:target", RANK06_FLAG)
    initial_amplification = _status_detail(state, "ally:seele", SEELE_AMPLIFICATION_BUFF)
    initial_flag_duration = _number(initial_flag.get("remaining_duration"))
    initial_amplification_duration = _number(initial_amplification.get("remaining_duration"))

    ally_turn_state = _with_active_turn(state, "ally:seele")
    ally_result = CombatScheduler(rules).end_current_turn(ally_turn_state)
    ally_audit = RuntimeSourceAuditor(rules).validate_transition(ally_result.transition)
    ally_detail = _status_detail(ally_result.after_state, "enemy:target", RANK06_FLAG)
    ally_amplification = _status_detail(ally_result.after_state, "ally:seele", SEELE_AMPLIFICATION_BUFF)

    enemy_turn_state = _with_active_turn(state, "enemy:target")
    enemy_result = CombatScheduler(rules).end_current_turn(enemy_turn_state)
    enemy_audit = RuntimeSourceAuditor(rules).validate_transition(enemy_result.transition)
    enemy_detail = _status_detail(enemy_result.after_state, "enemy:target", RANK06_FLAG)
    enemy_amplification = _status_detail(enemy_result.after_state, "ally:seele", SEELE_AMPLIFICATION_BUFF)
    enemy_mutations = tuple(
        mutation
        for mutation in enemy_result.transition.transaction.mutations
        if mutation.source == "status_system" and mutation.metadata.get("operation") == "tick"
    )
    ally_transition_checks = _transition_checks(ally_result.transition, ally_turn_state)
    enemy_transition_checks = _transition_checks(enemy_result.transition, enemy_turn_state)
    checks = {
        "ally_turn_transition": all(ally_transition_checks.values()),
        "ally_turn_source_audit": ally_audit.ok,
        "ally_turn_does_not_tick_enemy_debuff": _number(ally_detail.get("remaining_duration")) == initial_flag_duration,
        "ally_turn_ticks_own_buff": (
            initial_amplification_duration is not None
            and _number(ally_amplification.get("remaining_duration")) == initial_amplification_duration - 1
        ),
        "enemy_turn_transition": all(enemy_transition_checks.values()),
        "enemy_turn_source_audit": enemy_audit.ok,
        "enemy_turn_ticks_debuff": bool(enemy_mutations),
        "enemy_turn_remaining_duration_two": (
            initial_flag_duration is not None
            and _number(enemy_detail.get("remaining_duration")) == initial_flag_duration - 1
        ),
        "enemy_turn_flag_still_debuff": enemy_detail.get("status_category") == "debuff",
        "enemy_turn_does_not_tick_ally_buff": _number(enemy_amplification.get("remaining_duration")) == initial_amplification_duration,
        "ally_amplification_is_buff": ally_amplification.get("status_category") == "buff",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "ally_turn_source_audit": ally_audit.to_json(),
        "enemy_turn_source_audit": enemy_audit.to_json(),
        "ally_turn_transition": ally_result.transition.to_json(),
        "enemy_turn_transition": enemy_result.transition.to_json(),
    }


def _dispatch_damage_hit(rules: RuleBook, state: BattleState):
    event = GameEvent(
        "damage.hit",
        source_id="ally:other",
        target_id="enemy:target",
        window="damage.hit",
        process_only=True,
        payload={
            "actor_id": "ally:other",
            "attacker_id": "ally:other",
            "damage_attacker_id": "ally:other",
            "target_id": "enemy:target",
            "current_hit_target_id": "enemy:target",
            "primary_target_id": "enemy:target",
            "selected_target_ids": ["enemy:target"],
            "target_ids": ["enemy:target"],
            "attack_type": "Normal",
            "SkillType": "Normal",
            "damage_formula_family": "direct",
        },
    )
    return EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(state, event=event)


def _with_active_turn(state: BattleState, actor_id: str) -> BattleState:
    return replace(
        state,
        global_flags={
            **state.global_flags,
            "turn_owner_id": actor_id,
            "active_turn": {"actor_id": actor_id, "turn_kind": "regular"},
        },
    )


def _event_transition(
    *,
    before_state: BattleState,
    result,
    action_id: str,
    actor_id: str,
    target_id: str,
    metadata: dict[str, Any],
):
    return _callback_transition(
        before_state=before_state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id=action_id,
        actor_id=actor_id,
        target_id=target_id,
        metadata=metadata,
    )


def _state_with_target(
    rules: RuleBook,
    eidolon_level: int,
    *,
    target_hp: float,
    target_max_hp: float,
    enemy_id: str,
) -> BattleState:
    state = _build_result_for_eidolon_level(rules, eidolon_level).state
    actor = state.units["ally:seele"]
    card = _seele_card(rules)
    target = UnitState(
        unit_id=enemy_id,
        side="enemy",
        template_id="monster:validation_target",
        level=80,
        max_hp=target_max_hp,
        hp=target_hp,
        defense=100.0,
        speed=100.0,
        flags={"position": 0, "weaknesses": ("Quantum",)},
    )
    return replace(
        state,
        units={
            **state.units,
            "ally:seele": replace(
                actor,
                energy=120.0,
                max_energy=120.0,
                flags={
                    **actor.flags,
                    "skill_levels_by_trigger_key": _skill_levels_by_trigger_key(card),
                },
                resources={"critical_chance": 0.0, "critical_damage": 0.5},
            ),
            enemy_id: target,
        },
        skill_points=5,
        max_skill_points=5,
    )


def _skill_levels_by_trigger_key(card: CharacterDataCardIR) -> dict[str, int]:
    actions = card.action_set.get("actions") if isinstance(card.action_set, dict) else None
    if not isinstance(actions, list):
        return {}
    levels: dict[str, int] = {}
    for action in actions:
        if not isinstance(action, dict):
            continue
        trigger_key = action.get("skill_trigger_key")
        level = action.get("level")
        if not isinstance(trigger_key, str) or not trigger_key or not isinstance(level, int):
            continue
        levels[trigger_key] = max(levels.get(trigger_key, 0), level)
    return levels


def _status_detail(state: BattleState, unit_id: str, modifier_name: str) -> dict[str, Any]:
    unit = state.units.get(unit_id)
    if unit is None:
        return {}
    for detail in unit.flags.get("status_details", ()):
        if isinstance(detail, dict) and detail.get("modifier_name") == modifier_name:
            return detail
    return {}


def _remove_flag_dynamic_values(state: BattleState) -> BattleState:
    unit = state.units["enemy:target"]
    details = []
    for detail in unit.flags.get("status_details", ()):
        if isinstance(detail, dict) and detail.get("modifier_name") == RANK06_FLAG:
            detail = {**detail, "dynamic_values": {"__by_name": {}, "__by_hash": {}, "__evaluations": []}}
        details.append(detail)
    flags = {**unit.flags, "status_details": tuple(details)}
    return replace(state, units={**state.units, "enemy:target": replace(unit, flags=flags)})


def _status_dynamic_value(detail: dict[str, Any], name: str) -> float | None:
    dynamic = detail.get("dynamic_values")
    if not isinstance(dynamic, dict):
        return None
    direct = dynamic.get(name)
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return float(direct)
    by_name = dynamic.get("__by_name")
    if isinstance(by_name, dict):
        value = by_name.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _status_dynamic_hash_value(detail: dict[str, Any], hash_key: str) -> float | None:
    dynamic = detail.get("dynamic_values")
    if not isinstance(dynamic, dict):
        return None
    by_hash = dynamic.get("__by_hash")
    if not isinstance(by_hash, dict):
        return None
    value = by_hash.get(hash_key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _ledger_term_value(case: dict[str, Any], bucket: str, key: str) -> float | None:
    for mutation in case.get("damage_mutations", ()):
        metadata = mutation.get("metadata") if isinstance(mutation, dict) else {}
        ledger = metadata.get("modifier_ledger") if isinstance(metadata, dict) else {}
        terms = ledger.get("applied_terms") if isinstance(ledger, dict) else ()
        if not isinstance(terms, list):
            continue
        for term in terms:
            if not isinstance(term, dict):
                continue
            if term.get("source_type") != "damage_modifier_ir":
                continue
            if term.get("bucket") == bucket and term.get("key") == key:
                value = term.get("applied_value")
                return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return None


def _payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _without_state(case: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in case.items() if key != "after_state"}


if __name__ == "__main__":
    raise SystemExit(main())
