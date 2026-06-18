from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
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
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import CanonicalIR, EffectIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.status import StatusSystem
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_226"
HP_LOSS_OPCODE = "LoseHPByRatio"
COMBAT_SOURCE_PREFIXES = (
    "Config/ConfigAbility/Avatar/",
    "Config/ConfigAbility/Monster/",
    "Config/ConfigAbility/Servant/",
)
EXCLUDED_SOURCE_MARKERS = (
    "Activity",
    "AetherDivide",
    "BattleEvent",
    "Currency",
    "Fate",
    "GridFight",
    "MazeBuff",
    "Rogue",
    "Story",
)


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int | None = None,
) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    rules = RuleBook(ir)
    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    state = build_result.state
    command = build_result.commands[0]
    registry = EffectRegistry(StatusSystem(rules))

    positive = _with_replay(_hp_loss_case(ir, registry, state, command))
    negative_cases = {
        "dynamic_unbound": _with_replay(_hp_loss_dynamic_unbound_case(ir, registry, state, command)),
        "floor_true": _with_replay(_hp_loss_blocked_case(ir, registry, state, command, "hp_loss_floor_rounding_not_supported")),
        "unknown_ratio_type": _with_replay(_hp_loss_synthetic_case(ir, registry, state, command, "UnknownRatio", "CurrentActionTarget")),
        "unsupported_target_alias": _with_replay(_hp_loss_synthetic_case(ir, registry, state, command, "MaxHP", "UnsupportedAlias")),
    }
    transition_cases = {"hp_loss_positive": positive, **{f"negative_{name}": case for name, case in negative_cases.items()}}

    static_result = run_static_checks(package_root)
    snapshot_result = SnapshotCompletenessValidator().validate(state.snapshot())
    quality = _transition_quality_checks(transition_cases)
    source_audit = _source_audit_checks(rules, {"hp_loss_positive": positive.get("transition")})
    positive_checks = _positive_hp_loss_checks(positive)
    negative_checks = _negative_hp_loss_checks(negative_cases)
    trust_matrix = _mechanism_trust_matrix(positive_checks, negative_checks, source_audit)

    checks = {
        "positive_hp_loss": positive_checks,
        "negative_hp_loss": negative_checks,
        "transition_quality": quality,
        "source_audit": source_audit,
        "mechanism_trust_matrix": _trust_matrix_checks(trust_matrix),
        "validate_v0_225_default_slim": _v0_225_slim_contract_check(package_root),
    }
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
                "ir_effects": len(ir.effects),
                "hp_loss_effects": sum(1 for effect in ir.effects if effect.opcode == HP_LOSS_OPCODE),
                "hp_loss_executable_effects": sum(
                    1 for effect in ir.effects if effect.opcode == HP_LOSS_OPCODE and effect.coverage_status == "executable"
                ),
                "sampled": ir.metadata.get("sampled", {}),
            },
        },
        "checks": checks,
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "command": {
                "action_id": command.action_id,
                "action_level": command.action_level,
                "target_ids": list(command.target_ids),
            },
        },
        "snapshot_completeness": snapshot_result.to_json(),
        "static_checks": static_result.to_json(),
    }

    write_json(output_dir / "validation_summary_v0_226.json", result)
    write_json(output_dir / "mechanism_trust_matrix_v0_226.json", trust_matrix)
    write_json(output_dir / "sample_hp_loss_case_v0_226.json", _case_json(positive))
    write_json(output_dir / "sample_hp_loss_negative_cases_v0_226.json", {name: _case_json(case) for name, case in negative_cases.items()})
    transition = positive.get("transition")
    if isinstance(transition, BattleTransition):
        write_json(output_dir / "sample_hp_loss_transition_v0_226.json", transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 HP loss effect from real TBGD LoseHPByRatio.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_226"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=None)
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
    )
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _hp_loss_case(ir: CanonicalIR, registry: EffectRegistry, state: BattleState, command: ActionCommand) -> dict[str, Any]:
    effect = _select_hp_loss_effect(ir, fixed=True, coverage_status="executable")
    if effect is None:
        return {"effect": None, "transition": None, "error": "missing executable mainline fixed LoseHPByRatio effect"}
    return _execute_case(registry, state, command, effect, selection_mode="structured_predicate")


def _hp_loss_dynamic_unbound_case(ir: CanonicalIR, registry: EffectRegistry, state: BattleState, command: ActionCommand) -> dict[str, Any]:
    effect = _select_hp_loss_effect(ir, fixed=False, coverage_status="executable")
    if effect is None:
        return {"effect": None, "transition": None, "error": "missing executable mainline dynamic LoseHPByRatio effect"}
    return _execute_case(registry, state, command, effect, selection_mode="structured_predicate_unbound_dynamic")


def _hp_loss_blocked_case(
    ir: CanonicalIR,
    registry: EffectRegistry,
    state: BattleState,
    command: ActionCommand,
    blocked_reason: str,
) -> dict[str, Any]:
    effect = _select_hp_loss_blocked_effect(ir, blocked_reason)
    if effect is None:
        return {"effect": None, "transition": None, "error": f"missing blocked LoseHPByRatio effect:{blocked_reason}"}
    return _execute_case(registry, state, command, effect, selection_mode="structured_predicate_blocked")


def _hp_loss_synthetic_case(
    ir: CanonicalIR,
    registry: EffectRegistry,
    state: BattleState,
    command: ActionCommand,
    ratio_type: str,
    target_alias: str,
) -> dict[str, Any]:
    source = _select_hp_loss_effect(ir, fixed=True, coverage_status="executable")
    if source is None:
        return {"effect": None, "transition": None, "error": "missing executable source for synthetic negative"}
    standard = dict(source.payload.get("standard", {}))
    standard["ratio_type"] = ratio_type
    standard["target_alias"] = target_alias
    standard.pop("blocked_reason", None)
    effect = replace(
        source,
        effect_id=f"{source.effect_id}:synthetic_negative:{ratio_type}:{target_alias}",
        payload={**source.payload, "standard": standard},
        coverage_status="executable",
    )
    return _execute_case(registry, state, command, effect, selection_mode="synthetic_negative")


def _execute_case(
    registry: EffectRegistry,
    state: BattleState,
    command: ActionCommand,
    effect: EffectIR,
    *,
    selection_mode: str,
) -> dict[str, Any]:
    target_id = _target_id_for_effect(effect, command)
    result = registry.execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id=command.actor_id,
            source_id=f"validation:{VALIDATION_VERSION}:hp_loss:{effect.effect_id}",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=target_id,
        ),
    )
    after = MutationReducer().apply_all(state, result.mutations)
    transition = _effect_transition(command, state, after, effect, result, target_id)
    standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else {}
    return {
        "effect": effect,
        "before_state": state,
        "before": state,
        "after": after,
        "result": result,
        "transition": transition,
        "selection": {
            "selection_mode": selection_mode,
            "opcode": effect.opcode,
            "coverage_status": effect.coverage_status,
            "ratio_type": standard.get("ratio_type") if isinstance(standard, dict) else "",
            "target_alias": standard.get("target_alias") if isinstance(standard, dict) else "",
            "ratio_kind": standard.get("ratio", {}).get("kind") if isinstance(standard, dict) and isinstance(standard.get("ratio"), dict) else "",
            "source_trace": effect.source.to_json(),
        },
    }


def _effect_transition(
    command: ActionCommand,
    before_state: BattleState,
    after_state: BattleState,
    effect: EffectIR,
    effect_result,
    target_id: str,
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
                event_id=f"event:{before_state.event_index}:{VALIDATION_VERSION}:hp_loss",
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
            legal=(target_id,) if target_id in before_state.units else (),
            selected=(target_id,) if target_id in before_state.units else (),
            reason="effect_target_alias",
            source="effect_system",
            metadata={"effect_id": effect.effect_id, "opcode": effect.opcode},
        ),
        coverage={
            "executor": VALIDATION_VERSION,
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "mutation_count": len(effect_result.mutations),
            "unsupported": list(effect_result.unsupported),
        },
    )


def _select_hp_loss_effect(ir: CanonicalIR, *, fixed: bool, coverage_status: str) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode != HP_LOSS_OPCODE or effect.coverage_status != coverage_status:
            continue
        if not _is_mainline_combat_source(effect.source.source_path):
            continue
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            continue
        ratio = standard.get("ratio")
        if standard.get("ratio_type") not in {"MaxHP", "CurrentHP"}:
            continue
        if standard.get("floor") is True:
            continue
        if standard.get("target_alias") not in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}:
            continue
        ratio_is_fixed = isinstance(ratio, dict) and ratio.get("kind") == "fixed"
        ratio_is_dynamic = isinstance(ratio, dict) and ratio.get("kind") == "dynamic_hash"
        if fixed and ratio_is_fixed:
            return effect
        if not fixed and ratio_is_dynamic:
            return effect
    return None


def _select_hp_loss_blocked_effect(ir: CanonicalIR, blocked_reason: str) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode != HP_LOSS_OPCODE or not _is_mainline_combat_source(effect.source.source_path):
            continue
        standard = effect.payload.get("standard")
        if isinstance(standard, dict) and blocked_reason in str(standard.get("blocked_reason", "")):
            return effect
    return None


def _target_id_for_effect(effect: EffectIR, command: ActionCommand) -> str:
    standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else {}
    alias = standard.get("target_alias") if isinstance(standard, dict) else ""
    if alias in {"Caster", "ModifierOwnerEntity", "ParamEntity"}:
        return command.actor_id
    if alias == "CurrentActionTarget" and command.target_ids:
        return command.target_ids[0]
    return command.target_ids[0] if command.target_ids else command.actor_id


def _with_replay(case: dict[str, Any]) -> dict[str, Any]:
    transition = case.get("transition")
    before = case.get("before_state")
    after = case.get("after")
    if isinstance(transition, BattleTransition) and isinstance(before, BattleState) and isinstance(after, BattleState):
        replay = MutationReducer().replay_snapshot(before, transition.transaction.mutations, after.snapshot().to_json())
        case["replay"] = {"ok": replay.ok, "errors": list(replay.errors)}
    return case


def _positive_hp_loss_checks(case: dict[str, Any]) -> dict[str, Any]:
    transition = case.get("transition")
    records = _records_of_type(transition, "hp_loss")
    mutations = transition.transaction.mutations if isinstance(transition, BattleTransition) else ()
    payloads = [record.get("payload", {}) for record in records if isinstance(record, dict)]
    checks = {
        "structured_real_effect_selected": _selection_mode(case) == "structured_predicate" and _effect_is_real_hp_loss(case.get("effect")),
        "transition_exists": isinstance(transition, BattleTransition),
        "hp_mutation_exists": any(tuple(mutation.path)[-1:] == ("hp",) and mutation.source == "damage_system" for mutation in mutations),
        "hp_loss_record_exists": bool(records),
        "bypasses_normal_multipliers": any(payload.get("bypasses_normal_multipliers") is True for payload in payloads),
        "no_normal_multiplier_terms": all(payload.get("normal_multiplier_terms") == [] for payload in payloads),
        "mutation_metadata_has_effect_source": any(
            mutation.source == "damage_system"
            and isinstance(mutation.metadata.get("effect_source"), dict)
            and isinstance(mutation.metadata.get("numeric_evaluation"), dict)
            for mutation in mutations
        ),
        "replay_ok": bool(case.get("replay", {}).get("ok")),
    }
    return {"ok": all(checks.values()), "checks": checks, "records": records}


def _negative_hp_loss_checks(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for name, case in sorted(cases.items()):
        transition = case.get("transition")
        before = case.get("before_state")
        after = case.get("after")
        result = case.get("result")
        reasons = list(result.unsupported) if result is not None else []
        unchanged = isinstance(before, BattleState) and isinstance(after, BattleState) and before.snapshot().to_json() == after.snapshot().to_json()
        checks[f"{name}_transition_exists"] = isinstance(transition, BattleTransition)
        checks[f"{name}_no_mutations"] = isinstance(transition, BattleTransition) and not transition.transaction.mutations
        checks[f"{name}_snapshot_unchanged"] = unchanged
        checks[f"{name}_has_blocked_reason"] = bool(reasons)
        details[name] = {"selection": case.get("selection"), "unsupported": reasons, "replay": case.get("replay")}
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _transition_quality_checks(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    transition_validator = TransitionContractValidator()
    settlement_validator = SettlementTraceabilityValidator()
    reducer = MutationReducer()
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for name, case in sorted(cases.items()):
        transition = case.get("transition")
        before = case.get("before_state")
        after = case.get("after")
        checks[f"{name}_transition_exists"] = isinstance(transition, BattleTransition)
        if not isinstance(transition, BattleTransition) or not isinstance(before, BattleState) or not isinstance(after, BattleState):
            continue
        contract = transition_validator.validate(transition)
        traceability = settlement_validator.validate(transition.transaction.settlement, transition.transaction.mutations)
        replay = reducer.replay_snapshot(before, transition.transaction.mutations, after.snapshot().to_json())
        checks[f"{name}_contract_ok"] = contract.ok
        checks[f"{name}_traceability_ok"] = traceability.ok
        checks[f"{name}_replay_ok"] = replay.ok
        details[name] = {
            "contract": contract.to_json(),
            "traceability": traceability.to_json(),
            "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _source_audit_checks(rules: RuleBook, transitions: dict[str, Any]) -> dict[str, Any]:
    auditor = RuntimeSourceAuditor(rules)
    checks: dict[str, bool] = {}
    results: dict[str, Any] = {}
    for name, transition in transitions.items():
        if not isinstance(transition, BattleTransition):
            checks[f"{name}_exists"] = False
            continue
        audit = auditor.validate_transition(transition)
        checks[f"{name}_ok"] = audit.ok
        checks[f"{name}_checked_damage_mutation"] = audit.checked_mutations > 0
        results[name] = audit.to_json()
    return {"ok": all(checks.values()), "checks": checks, "results": results}


def _mechanism_trust_matrix(
    positive_checks: dict[str, Any],
    negative_checks: dict[str, Any],
    source_audit: dict[str, Any],
) -> dict[str, Any]:
    entries = {
        "hp_loss": {
            "source_audit_covered": bool(source_audit.get("ok")),
            "negative_case_covered": bool(negative_checks.get("ok")),
            "semantic_status": "trusted_for_current_scope" if positive_checks.get("ok") and source_audit.get("ok") else "needs_fix",
            "remaining_risk": "Trusted only for LoseHPByRatio with fixed/bound MaxHP or CurrentHP ratio; Floor rounding and unknown ratio types remain blocked.",
            "blocking_issue": "" if positive_checks.get("ok") and source_audit.get("ok") else "hp_loss source path is not fully validated",
        },
        "true_damage": {
            "source_audit_covered": False,
            "negative_case_covered": False,
            "semantic_status": "structural_only",
            "remaining_risk": "Bypass semantics exist, but no executable TBGD true damage source is admitted in v0_226.",
            "blocking_issue": "",
        },
    }
    return {"ok": all(entry["semantic_status"] != "needs_fix" for entry in entries.values()), "entries": entries}


def _trust_matrix_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    entries = matrix.get("entries", {})
    needs_fix = {
        name: entry
        for name, entry in entries.items()
        if isinstance(entry, dict) and entry.get("semantic_status") == "needs_fix"
    }
    return {"ok": not needs_fix, "needs_fix": needs_fix, "entry_count": len(entries)}


def _v0_225_slim_contract_check(package_root: Path) -> dict[str, Any]:
    path = package_root / "tools" / "validate_v0_225.py"
    text = path.read_text(encoding="utf-8")
    checks = {
        "has_write_diagnostics_flag": "--write-diagnostics" in text,
        "has_write_matrices_flag": "--write-matrices" in text,
        "default_skips_matrices": "coverage/fidelity matrices are skipped by default" in text,
        "default_writes_summary": "source_audit_summary_v0_225.json" in text,
    }
    return {"ok": all(checks.values()), "checks": checks}


def _effect_is_real_hp_loss(effect: object) -> bool:
    if not isinstance(effect, EffectIR):
        return False
    standard = effect.payload.get("standard")
    return (
        effect.opcode == HP_LOSS_OPCODE
        and effect.coverage_status == "executable"
        and _is_mainline_combat_source(effect.source.source_path)
        and isinstance(standard, dict)
        and standard.get("kind") == "hp_loss_ratio"
        and standard.get("ratio_type") in {"MaxHP", "CurrentHP"}
        and isinstance(standard.get("ratio"), dict)
        and standard["ratio"].get("kind") == "fixed"
    )


def _selection_mode(case: dict[str, Any]) -> str:
    selection = case.get("selection", {})
    return str(selection.get("selection_mode") or "") if isinstance(selection, dict) else ""


def _is_mainline_combat_source(source_path: str) -> bool:
    return source_path.startswith(COMBAT_SOURCE_PREFIXES) and not any(marker in source_path for marker in EXCLUDED_SOURCE_MARKERS)


def _records_of_type(transition: object, record_type: str) -> list[dict[str, Any]]:
    if not isinstance(transition, BattleTransition) or transition.transaction.settlement is None:
        return []
    return [
        record
        for record in transition.transaction.settlement.records
        if isinstance(record, dict) and record.get("record_type") == record_type
    ]


def _case_json(case: dict[str, Any]) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in case.items():
        if isinstance(value, BattleState):
            encoded[key] = {"snapshot": value.snapshot().to_json()}
        elif hasattr(value, "to_json"):
            encoded[key] = value.to_json()
        elif key == "result":
            encoded[key] = {
                "events": [event.to_json() for event in value.events],
                "mutations": [mutation.to_json() for mutation in value.mutations],
                "records": list(value.records),
                "unsupported": list(value.unsupported),
            }
        elif key.endswith("_state"):
            continue
        else:
            encoded[key] = value
    return encoded


if __name__ == "__main__":
    raise SystemExit(main())
