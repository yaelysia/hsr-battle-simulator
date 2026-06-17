from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.fidelity import build_fidelity_matrix
from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    TargetResolution,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import CanonicalIR, EffectIR, IRSource
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_214"
NON_MAINLINE_PREFIXES = (
    "Config/ConfigAbility/Activity",
    "Config/ConfigAbility/Rogue",
    "Config/ConfigAbility/Fate",
    "Config/ConfigAbility/BattleEvent/",
    "Config/ConfigAbility/Avatar/Avatar_AetherDivide",
    "Config/ConfigAbility/Monster/Monster_AetherDivide",
)
REMOVE_OPCODES = ("RemoveModifier",)
REMOVE_SELF_OPCODES = ("RemoveSelfModifier",)
HEAL_OPCODES = ("HealHP",)
SHIELD_OPCODES = ("InitShield", "StackShield", "ModifyShield")
MECHANISM_BAR_OPCODES = ("SetEnergyBarState", "SetMonsterEnergyBarState", "SetSummonerEnergyBarState")


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int | None = None,
    write_full_ir: bool = False,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)
    rules = RuleBook(ir)

    if write_full_ir:
        write_json(output_dir / "canonical_ir_v0_214.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_214.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_214.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_214.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = build_result.state
    command = build_result.commands[0]
    registry = EffectRegistry(StatusSystem(rules))

    remove_effect = _select_effect(ir, REMOVE_OPCODES, coverage_status="executable")
    remove_case = _remove_effect_case(rules, registry, base_state, command, remove_effect, "real_remove_modifier")

    remove_self_effect = _select_effect(ir, REMOVE_SELF_OPCODES, coverage_status="executable")
    remove_self_case = _remove_effect_case(
        rules,
        registry,
        base_state,
        command,
        remove_self_effect,
        "real_remove_self_modifier",
    )

    heal_fixed_effect = _select_fixed_amount_effect(ir, HEAL_OPCODES)
    heal_blocked_effect = _select_blocked_effect(ir, HEAL_OPCODES)
    heal_case = _fixed_or_blocked_case(
        registry,
        _with_damaged_actor(base_state, command.actor_id),
        command,
        heal_fixed_effect,
        heal_blocked_effect,
        "heal",
    )

    shield_fixed_effect = _select_fixed_amount_effect(ir, SHIELD_OPCODES)
    shield_blocked_effect = _select_blocked_effect(ir, SHIELD_OPCODES)
    shield_case = _fixed_or_blocked_case(
        registry,
        base_state,
        command,
        shield_fixed_effect,
        shield_blocked_effect,
        "shield",
    )

    mechanism_effect = _select_effect(ir, MECHANISM_BAR_OPCODES, coverage_status="executable")
    mechanism_blocked_effect = _select_blocked_effect(ir, MECHANISM_BAR_OPCODES)
    mechanism_case = _mechanism_bar_case(registry, base_state, command, mechanism_effect, mechanism_blocked_effect)

    snapshot_result = SnapshotCompletenessValidator().validate(base_state.snapshot())
    transition_checks = _transition_quality_checks(
        {
            "remove_modifier": remove_case,
            "remove_self_modifier": remove_self_case,
            "heal": heal_case,
            "shield": shield_case,
            "mechanism_bar_state": mechanism_case,
        }
    )
    checks = {
        "remove_modifier": _remove_checks(remove_case, expected_opcode="RemoveModifier"),
        "remove_self_modifier": _remove_checks(remove_self_case, expected_opcode="RemoveSelfModifier"),
        "heal_hp": _fixed_or_blocked_checks(heal_case, record_type="heal"),
        "shield": _fixed_or_blocked_checks(shield_case, record_type="shield"),
        "mechanism_bar_state": _mechanism_bar_checks(mechanism_case),
        "coverage": _coverage_checks(coverage.to_json()),
        "registry_coverage": _registry_coverage_checks(registry, remove_effect, remove_self_effect, heal_case, shield_case, mechanism_case),
        "transition_quality": transition_checks,
    }
    static_result = run_static_checks(package_root)

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                identity_result.ok,
                static_result.ok,
                snapshot_result.ok,
                *(item["ok"] for item in checks.values()),
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "discovery_files": len(discovery.files),
                "ir_effects": len(ir.effects),
                "ir_triggers": len(ir.triggers),
                "sampled": ir.metadata.get("sampled", {}),
            },
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "command": {
                "action_id": command.action_id,
                "action_level": command.action_level,
                "target_ids": list(command.target_ids),
            },
        },
        "checks": checks,
        "snapshot_completeness": snapshot_result.to_json(),
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }

    write_json(output_dir / "validation_summary_v0_214.json", result)
    for name, case in (
        ("remove_modifier", remove_case),
        ("remove_self_modifier", remove_self_case),
        ("heal_hp", heal_case),
        ("shield", shield_case),
        ("mechanism_bar_state", mechanism_case),
    ):
        write_json(output_dir / f"sample_{name}_case_v0_214.json", _case_json(case))
        transition = case.get("transition")
        if transition is not None:
            write_json(output_dir / f"sample_{name}_transition_v0_214.json", transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 TBGD effect payload standardization.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_214"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=None)
    parser.add_argument("--write-full-ir", action="store_true")
    args = parser.parse_args(argv)

    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root.resolve() if args.tbgd_root else find_tbgd_root(package_root)
    scenario_path = args.scenario or package_root / "scenarios/examples/identity_smoke_v0_204.json"
    result = run_validation(
        package_root,
        tbgd_root,
        args.output_dir,
        scenario_path,
        max_ability_files=args.max_ability_files,
        write_full_ir=args.write_full_ir,
    )
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _canonical_ir_summary(ir: CanonicalIR) -> dict[str, object]:
    effect_opcode_counts: dict[str, int] = {}
    for effect in ir.effects:
        effect_opcode_counts[effect.opcode] = effect_opcode_counts.get(effect.opcode, 0) + 1
    return {
        "version": ir.version,
        "metadata": ir.metadata,
        "counts": {
            "entities": len(ir.entities),
            "action_definitions": len(ir.action_definitions),
            "triggers": len(ir.triggers),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
        },
        "effect_opcode_counts": dict(sorted(effect_opcode_counts.items())),
    }


def _select_effect(
    ir: CanonicalIR,
    opcodes: tuple[str, ...],
    *,
    coverage_status: str,
) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode not in opcodes:
            continue
        if effect.coverage_status != coverage_status:
            continue
        if not _is_mainline_source(effect.source.source_path):
            continue
        if not isinstance(effect.payload.get("standard"), dict):
            continue
        return effect
    return None


def _select_fixed_amount_effect(ir: CanonicalIR, opcodes: tuple[str, ...]) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode not in opcodes or effect.coverage_status != "executable":
            continue
        if not _is_mainline_source(effect.source.source_path):
            continue
        standard = effect.payload.get("standard")
        if isinstance(standard, dict) and _fixed_amount(standard.get("amount")) is not None:
            return effect
    return None


def _select_blocked_effect(ir: CanonicalIR, opcodes: tuple[str, ...]) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode not in opcodes or effect.coverage_status == "executable":
            continue
        if not _is_mainline_source(effect.source.source_path):
            continue
        standard = effect.payload.get("standard")
        if isinstance(standard, dict) and isinstance(standard.get("blocked_reason"), str):
            return effect
    return None


def _remove_effect_case(
    rules: RuleBook,
    registry: EffectRegistry,
    base_state: BattleState,
    command: ActionCommand,
    effect: EffectIR | None,
    case_id: str,
) -> dict[str, Any]:
    if effect is None:
        return {"effect": None, "transition": None, "error": "missing executable remove effect"}
    standard = effect.payload.get("standard")
    modifier_name = standard.get("modifier_name") if isinstance(standard, dict) else None
    if not isinstance(modifier_name, str) or not modifier_name:
        return {"effect": effect, "transition": None, "error": "remove effect has no modifier_name"}
    if rules.modifier_definition(modifier_name) is None:
        return {"effect": effect, "transition": None, "error": f"missing modifier_definition:{modifier_name}"}

    setup_effect = _synthetic_add_modifier(modifier_name, f"{case_id}_setup")
    setup_result = _execute_effect(
        registry,
        base_state,
        setup_effect,
        command,
        source_suffix=f"{case_id}_setup",
        owner_id=command.actor_id,
        param_entity_id=command.actor_id,
        current_action_target_id=command.actor_id,
    )
    reducer = MutationReducer()
    before = reducer.apply_all(base_state, setup_result.mutations)
    remove_result = _execute_effect(
        registry,
        before,
        effect,
        command,
        source_suffix=case_id,
        owner_id=command.actor_id,
        param_entity_id=command.actor_id,
        current_action_target_id=command.actor_id,
    )
    after = reducer.apply_all(before, remove_result.mutations)
    transition = _effect_transition(
        command=command,
        before_state=before,
        after_state=after,
        effect=effect,
        effect_result=remove_result,
        target_id=command.actor_id,
        coverage_id=f"{VALIDATION_VERSION}_{case_id}",
    )
    return {
        "effect": effect,
        "setup_effect": setup_effect,
        "setup_result": setup_result,
        "before_state": before,
        "result": remove_result,
        "transition": transition,
        "expected_status_id": f"modifier:{modifier_name}",
    }


def _fixed_or_blocked_case(
    registry: EffectRegistry,
    base_state: BattleState,
    command: ActionCommand,
    fixed_effect: EffectIR | None,
    blocked_effect: EffectIR | None,
    record_type: str,
) -> dict[str, Any]:
    if fixed_effect is not None:
        result = _execute_effect(
            registry,
            base_state,
            fixed_effect,
            command,
            source_suffix=f"{record_type}_fixed",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=command.actor_id,
        )
        after = MutationReducer().apply_all(base_state, result.mutations)
        transition = _effect_transition(
            command=command,
            before_state=base_state,
            after_state=after,
            effect=fixed_effect,
            effect_result=result,
            target_id=command.actor_id,
            coverage_id=f"{VALIDATION_VERSION}_{record_type}_fixed",
        )
        return {"mode": "fixed_executable", "effect": fixed_effect, "result": result, "transition": transition, "before_state": base_state}
    return {"mode": "blocked_no_fixed_mainline_sample", "effect": blocked_effect, "transition": None}


def _mechanism_bar_case(
    registry: EffectRegistry,
    base_state: BattleState,
    command: ActionCommand,
    fixed_effect: EffectIR | None,
    blocked_effect: EffectIR | None,
) -> dict[str, Any]:
    if fixed_effect is not None:
        result = _execute_effect(
            registry,
            base_state,
            fixed_effect,
            command,
            source_suffix="mechanism_bar_state",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=command.actor_id,
        )
        after = MutationReducer().apply_all(base_state, result.mutations)
        transition = _effect_transition(
            command=command,
            before_state=base_state,
            after_state=after,
            effect=fixed_effect,
            effect_result=result,
            target_id=command.actor_id,
            coverage_id=f"{VALIDATION_VERSION}_mechanism_bar_state",
        )
        return {"mode": "fixed_executable", "effect": fixed_effect, "result": result, "transition": transition, "before_state": base_state}
    return {"mode": "blocked_no_fixed_mainline_sample", "effect": blocked_effect, "transition": None}


def _execute_effect(
    registry: EffectRegistry,
    state: BattleState,
    effect: EffectIR,
    command: ActionCommand,
    *,
    source_suffix: str,
    owner_id: str | None = None,
    param_entity_id: str | None = None,
    current_action_target_id: str | None = None,
):
    return registry.execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id=command.actor_id,
            source_id=f"validation:{VALIDATION_VERSION}:{source_suffix}:{effect.effect_id}",
            owner_id=owner_id or command.actor_id,
            param_entity_id=param_entity_id or command.actor_id,
            current_action_target_id=current_action_target_id or (command.target_ids[0] if command.target_ids else None),
        ),
    )


def _effect_transition(
    *,
    command: ActionCommand,
    before_state: BattleState,
    after_state: BattleState,
    effect: EffectIR,
    effect_result,
    target_id: str,
    coverage_id: str,
) -> BattleTransition:
    settlement = ActionSettlement(
        action_id=command.action_id,
        actor_id=command.actor_id,
        target_ids=(target_id,),
        records=tuple(effect_result.records),
    )
    transaction = ActionTransaction(
        command=replace(command, metadata={**command.metadata, "effect_id": effect.effect_id, "opcode": effect.opcode}),
        before=before_state.snapshot(),
        events=(
            GameEvent(
                event_type=f"effect.{effect.opcode}",
                source_id=command.actor_id,
                target_id=target_id,
                event_id=f"event:{before_state.event_index}:{coverage_id}",
                window="effect_resolution",
                process_only=True,
                payload={"effect_id": effect.effect_id, "opcode": effect.opcode},
            ),
        ),
        mutations=effect_result.mutations,
        settlement=settlement,
    )
    return BattleTransition(
        transaction=transaction,
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=(target_id,),
            legal=(target_id,),
            selected=(target_id,),
            reason="effect_target_alias",
            source="effect_system",
            metadata={"effect_id": effect.effect_id, "opcode": effect.opcode},
        ),
        coverage={
            "executor": coverage_id,
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "mutation_count": len(effect_result.mutations),
            "unsupported": list(effect_result.unsupported),
        },
    )


def _synthetic_add_modifier(modifier_name: str, raw_id: str) -> EffectIR:
    return EffectIR(
        effect_id=f"effect:validation:{VALIDATION_VERSION}:{raw_id}:AddModifier",
        opcode="AddModifier",
        payload={
            "standard": {
                "modifier_name": modifier_name,
                "target_alias": "ParamEntity",
                "dynamic_values": {},
                "lifetime": {"kind": "missing", "value": None, "supported": False, "reason": "missing"},
                "layer_add_when_stack": {"kind": "missing", "value": None, "supported": False, "reason": "missing"},
                "max_layer": {"kind": "missing", "value": None, "supported": False, "reason": "missing"},
                "chance": {"kind": "missing", "value": None, "supported": False, "reason": "missing"},
            },
            "validation_only": True,
        },
        source=IRSource(
            source_path=f"validation/{VALIDATION_VERSION}",
            raw_type="SyntheticAddModifierPrecondition",
            raw_id=raw_id,
            evidence={"purpose": "preload matching runtime status for real TBGD remove opcode"},
        ),
        coverage_status="executable",
    )


def _with_damaged_actor(state: BattleState, actor_id: str) -> BattleState:
    actor = state.units[actor_id]
    damaged = replace(actor, hp=max(1.0, actor.max_hp - 1000.0))
    return replace(state, units={**state.units, actor_id: damaged})


def _remove_checks(case: dict[str, Any], *, expected_opcode: str) -> dict[str, object]:
    transition = case.get("transition")
    records = _records_of_type(transition, "status_lifecycle")
    payloads = [record.get("payload", {}) for record in records if isinstance(record, dict)]
    after_units = transition.after.to_json().get("units", {}) if transition is not None else {}
    selected = transition.target_resolution.selected[0] if transition is not None and transition.target_resolution.selected else ""
    after_target = after_units.get(selected, {}) if isinstance(after_units, dict) else {}
    after_statuses = after_target.get("statuses", []) if isinstance(after_target, dict) else []
    expected_status_id = str(case.get("expected_status_id") or "")
    effect = case.get("effect")
    checks = {
        "real_effect_selected": isinstance(effect, EffectIR) and effect.opcode == expected_opcode,
        "real_effect_not_validation_only": isinstance(effect, EffectIR) and not bool(effect.payload.get("validation_only")),
        "transition_exists": transition is not None,
        "has_remove_lifecycle_record": any(payload.get("operation") == "remove" for payload in payloads if isinstance(payload, dict)),
        "status_removed": bool(expected_status_id) and expected_status_id not in after_statuses,
        "has_remove_mutation": bool(transition is not None and transition.transaction.mutations),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "effect": effect.to_json() if isinstance(effect, EffectIR) else None,
        "records": records,
        "after_statuses": after_statuses,
        "selected_target_id": selected,
    }


def _fixed_or_blocked_checks(case: dict[str, Any], *, record_type: str) -> dict[str, object]:
    mode = case.get("mode")
    effect = case.get("effect")
    transition = case.get("transition")
    if mode == "fixed_executable":
        records = _records_of_type(transition, record_type)
        checks = {
            "real_fixed_effect_selected": isinstance(effect, EffectIR) and not bool(effect.payload.get("validation_only")),
            "transition_exists": transition is not None,
            "record_exists": bool(records),
            "record_is_mutation_linked": any(bool(record.get("mutation_id")) for record in records),
            "has_mutation": bool(transition is not None and transition.transaction.mutations),
        }
    else:
        standard = effect.payload.get("standard") if isinstance(effect, EffectIR) else {}
        checks = {
            "blocked_sample_selected": isinstance(effect, EffectIR),
            "blocked_sample_not_executable": isinstance(effect, EffectIR) and effect.coverage_status != "executable",
            "blocked_reason_present": isinstance(standard, dict) and isinstance(standard.get("blocked_reason"), str),
        }
        records = []
    return {
        "ok": all(checks.values()),
        "mode": mode,
        "checks": checks,
        "effect": effect.to_json() if isinstance(effect, EffectIR) else None,
        "records": records,
    }


def _mechanism_bar_checks(case: dict[str, Any]) -> dict[str, object]:
    mode = case.get("mode")
    effect = case.get("effect")
    transition = case.get("transition")
    if mode == "fixed_executable":
        records = _records_of_type(transition, "mechanism_bar_state")
        paths = [list(mutation.path) for mutation in transition.transaction.mutations] if transition is not None else []
        checks = {
            "real_mechanism_effect_selected": isinstance(effect, EffectIR) and effect.opcode in MECHANISM_BAR_OPCODES,
            "transition_exists": transition is not None,
            "mechanism_record_exists": bool(records),
            "mechanism_record_is_mutation_linked": any(bool(record.get("mutation_id")) for record in records),
            "writes_mechanism_bars": any(path[-2:] == ["flags", "mechanism_bars"] for path in paths),
            "does_not_write_unit_energy": not any(path[-1:] == ["energy"] for path in paths),
        }
    else:
        standard = effect.payload.get("standard") if isinstance(effect, EffectIR) else {}
        checks = {
            "blocked_sample_selected": isinstance(effect, EffectIR),
            "blocked_sample_not_executable": isinstance(effect, EffectIR) and effect.coverage_status != "executable",
            "blocked_reason_present": isinstance(standard, dict) and isinstance(standard.get("blocked_reason"), str),
        }
        records = []
    return {
        "ok": all(checks.values()),
        "mode": mode,
        "checks": checks,
        "effect": effect.to_json() if isinstance(effect, EffectIR) else None,
        "records": records,
    }


def _coverage_checks(coverage_json: dict[str, Any]) -> dict[str, object]:
    opcode_status = coverage_json.get("opcode_status", {})
    details = {opcode: opcode_status.get(opcode, {}) for opcode in (*REMOVE_OPCODES, *REMOVE_SELF_OPCODES, *HEAL_OPCODES, *SHIELD_OPCODES, *MECHANISM_BAR_OPCODES)}
    checks = {
        "remove_modifier_executable": details.get("RemoveModifier", {}).get("executable", 0) > 0,
        "remove_self_modifier_executable": details.get("RemoveSelfModifier", {}).get("executable", 0) > 0,
        "heal_hp_lowered_or_discovered": details.get("HealHP", {}).get("lowered", 0) > 0,
        "shield_lowered_or_discovered": any(details.get(opcode, {}).get("lowered", 0) > 0 for opcode in SHIELD_OPCODES),
        "mechanism_bar_lowered": any(details.get(opcode, {}).get("lowered", 0) > 0 for opcode in MECHANISM_BAR_OPCODES),
        "mechanism_bar_executable": any(details.get(opcode, {}).get("executable", 0) > 0 for opcode in MECHANISM_BAR_OPCODES),
    }
    return {"ok": all(checks.values()), "checks": checks, "opcode_status": details}


def _registry_coverage_checks(
    registry: EffectRegistry,
    remove_effect: EffectIR | None,
    remove_self_effect: EffectIR | None,
    heal_case: dict[str, Any],
    shield_case: dict[str, Any],
    mechanism_case: dict[str, Any],
) -> dict[str, object]:
    heal_effect = heal_case.get("effect")
    shield_effect = shield_case.get("effect")
    mechanism_effect = mechanism_case.get("effect")
    checks = {
        "remove_registry_executable": isinstance(remove_effect, EffectIR) and registry.coverage(remove_effect) == "executable",
        "remove_self_registry_executable": isinstance(remove_self_effect, EffectIR) and registry.coverage(remove_self_effect) == "executable",
        "heal_registry_matches_payload": not isinstance(heal_effect, EffectIR)
        or (
            (heal_case.get("mode") == "fixed_executable" and registry.coverage(heal_effect) == "executable")
            or (heal_case.get("mode") != "fixed_executable" and registry.coverage(heal_effect) != "executable")
        ),
        "shield_registry_matches_payload": not isinstance(shield_effect, EffectIR)
        or (
            (shield_case.get("mode") == "fixed_executable" and registry.coverage(shield_effect) == "executable")
            or (shield_case.get("mode") != "fixed_executable" and registry.coverage(shield_effect) != "executable")
        ),
        "mechanism_registry_matches_payload": not isinstance(mechanism_effect, EffectIR)
        or (
            (mechanism_case.get("mode") == "fixed_executable" and registry.coverage(mechanism_effect) == "executable")
            or (mechanism_case.get("mode") != "fixed_executable" and registry.coverage(mechanism_effect) != "executable")
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _transition_quality_checks(cases: dict[str, dict[str, Any]]) -> dict[str, object]:
    transition_validator = TransitionContractValidator()
    settlement_validator = SettlementTraceabilityValidator()
    reducer = MutationReducer()
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for name, case in cases.items():
        transition = case.get("transition")
        if transition is None:
            if case.get("mode") == "blocked_no_fixed_mainline_sample":
                checks[f"{name}_blocked_case_has_no_transition"] = True
                continue
            checks[f"{name}_transition_exists"] = False
            continue
        before_state = case.get("before_state")
        contract = transition_validator.validate(transition)
        traceability = settlement_validator.validate(transition.transaction.settlement, transition.transaction.mutations)
        replay = (
            reducer.replay_snapshot(before_state, transition.transaction.mutations, transition.after.to_json())
            if isinstance(before_state, BattleState)
            else None
        )
        checks[f"{name}_contract_ok"] = contract.ok
        checks[f"{name}_traceability_ok"] = traceability.ok
        checks[f"{name}_replay_ok"] = bool(replay and replay.ok)
        details[name] = {
            "contract": contract.to_json(),
            "traceability": traceability.to_json(),
            "replay": {"ok": replay.ok, "errors": list(replay.errors)} if replay else {"ok": False},
        }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _records_of_type(transition, record_type: str) -> list[dict[str, Any]]:
    if transition is None or transition.transaction.settlement is None:
        return []
    return [
        record
        for record in transition.transaction.settlement.records
        if isinstance(record, dict) and record.get("record_type") == record_type
    ]


def _fixed_amount(expr: object) -> float | None:
    if isinstance(expr, (int, float)):
        return float(expr)
    if isinstance(expr, dict) and expr.get("kind") == "fixed" and isinstance(expr.get("value"), (int, float)):
        return float(expr["value"])
    return None


def _is_mainline_source(source_path: str) -> bool:
    return not source_path.startswith(NON_MAINLINE_PREFIXES)


def _case_json(case: dict[str, Any]) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in case.items():
        if isinstance(value, BattleState):
            encoded[key] = {"snapshot": value.snapshot().to_json()}
        elif hasattr(value, "to_json"):
            encoded[key] = value.to_json()
        elif key == "result" or key == "setup_result":
            encoded[key] = _effect_result_json(value)
        elif key.endswith("_state"):
            continue
        else:
            encoded[key] = value
    return encoded


def _effect_result_json(effect_result) -> dict[str, Any] | None:
    if effect_result is None:
        return None
    return {
        "events": [event.to_json() for event in effect_result.events],
        "mutations": [mutation.to_json() for mutation in effect_result.mutations],
        "records": list(effect_result.records),
        "unsupported": list(effect_result.unsupported),
    }


if __name__ == "__main__":
    raise SystemExit(main())
