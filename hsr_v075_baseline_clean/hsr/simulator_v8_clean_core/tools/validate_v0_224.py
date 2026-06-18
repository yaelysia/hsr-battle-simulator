from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.fidelity import build_fidelity_matrix
from ..core.model import ActionCommand, BattleState, BattleTransition
from ..core.reducer import MutationReducer
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
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_210 import (
    _formula_test_state,
    _select_status_damage_bonus_effect,
    _status_transition,
    _with_crit_mode,
)
from .validate_v0_216 import _dynamic_value_store_case, _select_dynamic_value_store_effect
from .validate_v0_218 import _multi_enemy_state, _transition_quality_checks
from .validate_v0_222 import _target_ids_for_definition
from .validate_v0_223 import (
    _damage_emission_case_json,
    _executable_damage_emission_case,
    _no_executable_damage_emission_case,
)


VALIDATION_VERSION = "v0_224"
FIXED_SAMPLE_TOKENS = (
    "Avatar_Gepard_00_Ability",
    "Avatar_Advanced_Huohuo_00_Ability",
    "Avatar_AetherDivide",
    "Monster_AetherDivide",
    "-295141034",
)


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
        write_json(output_dir / "canonical_ir_v0_224.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_224.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_224.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_224.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = _multi_enemy_state(build_result.state)
    base_command = replace(
        build_result.commands[0],
        target_ids=("enemy:target",),
        metadata={**build_result.commands[0].metadata, "crit_mode": "noncrit", "reset_actor_av": False},
    )
    formula_state = _formula_test_state(build_result.state)
    formula_command = _with_crit_mode(build_result.commands[0], "crit")

    damage_case = _executable_damage_emission_case(ir, rules, base_state, base_command)
    no_fake_damage_case = _no_executable_damage_emission_case(ir, rules, base_state, base_command)
    status_case = _status_source_case(ir, rules, formula_state, formula_command)
    dynamic_value_case = _dynamic_value_source_case(ir, rules, formula_state, formula_command)

    transitions = {
        "damage_executor": damage_case.get("transition"),
        "status_add_modifier": status_case.get("transition"),
        "effect_dynamic_value_store": dynamic_value_case.get("transition"),
    }
    source_audit = _source_audit_checks(rules, transitions)
    sample_trace = _sample_source_trace(source_audit["results"])

    snapshot_result = SnapshotCompletenessValidator().validate(base_state.snapshot())
    static_result = run_static_checks(package_root)
    transition_quality = _transition_quality_checks(
        {
            "damage_executor": damage_case,
            "no_fake_damage": no_fake_damage_case,
            "status_add_modifier": status_case,
            "effect_dynamic_value_store": dynamic_value_case,
        }
    )
    checks = {
        "source_audit": source_audit,
        "mutation_source_categories": _mutation_source_category_checks(transitions),
        "no_fake_damage_without_emission": _no_fake_damage_unchanged_checks(no_fake_damage_case),
        "executable_ir_sources": _executable_ir_source_checks(ir),
        "non_mutating_status_guard": _non_mutating_status_checks(ir, transitions),
        "validation_sample_policy": _validation_sample_policy_checks(package_root),
        "transition_quality": transition_quality,
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
                "discovery_files": len(discovery.files),
                "ir_action_definitions": len(ir.action_definitions),
                "ir_action_events": len(ir.action_events),
                "ir_ability_tasks": len(ir.ability_tasks),
                "ir_damage_emissions": len(ir.damage_emissions),
                "ir_effects": len(ir.effects),
                "sampled": ir.metadata.get("sampled", {}),
            },
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "command": {
                "actor_id": base_command.actor_id,
                "action_id": base_command.action_id,
                "action_level": base_command.action_level,
                "target_ids": list(base_command.target_ids),
            },
        },
        "checks": checks,
        "snapshot_completeness": snapshot_result.to_json(),
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_224.json", result)
    write_json(output_dir / "source_audit_v0_224.json", source_audit)
    write_json(output_dir / "sample_source_audit_trace_v0_224.json", sample_trace)
    write_json(output_dir / "sample_damage_emission_case_v0_224.json", _damage_emission_case_json(damage_case))
    write_json(output_dir / "sample_no_fake_damage_case_v0_224.json", _damage_emission_case_json(no_fake_damage_case))
    if damage_case.get("transition") is not None:
        write_json(output_dir / "sample_damage_emission_transition_v0_224.json", damage_case["transition"].to_json())
    if status_case.get("transition") is not None:
        write_json(output_dir / "sample_status_source_transition_v0_224.json", status_case["transition"].to_json())
    if dynamic_value_case.get("transition") is not None:
        write_json(output_dir / "sample_effect_source_transition_v0_224.json", dynamic_value_case["transition"].to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 runtime source authenticity audit.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_224"))
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
    status_counts: dict[str, int] = {}
    for node in (
        *ir.action_definitions,
        *ir.action_events,
        *ir.hit_profiles,
        *ir.damage_emissions,
        *ir.effects,
        *ir.ability_tasks,
    ):
        status = str(getattr(node, "coverage_status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "version": ir.version,
        "metadata": ir.metadata,
        "counts": {
            "entities": len(ir.entities),
            "action_definitions": len(ir.action_definitions),
            "action_events": len(ir.action_events),
            "hit_profiles": len(ir.hit_profiles),
            "damage_emissions": len(ir.damage_emissions),
            "ability_tasks": len(ir.ability_tasks),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
        },
        "coverage_status_counts": dict(sorted(status_counts.items())),
    }


def _status_source_case(
    ir: CanonicalIR,
    rules: RuleBook,
    state: BattleState,
    command: ActionCommand,
) -> dict[str, Any]:
    effect = _select_status_damage_bonus_effect(ir, rules)
    if effect is None:
        return {"transition": None, "before": state, "after": state, "error": "missing structured AddModifier source case"}
    registry = EffectRegistry(StatusSystem(rules))
    result = registry.execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id=command.actor_id,
            source_id=f"validation:{VALIDATION_VERSION}:status_source:{effect.effect_id}",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=command.target_ids[0] if command.target_ids else None,
        ),
    )
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    transition = _status_transition(
        command=command,
        before_state=state,
        after_state=after,
        effect=effect,
        effect_result=result,
    )
    return {
        "effect": effect,
        "before": state,
        "before_state": state,
        "after": after,
        "transition": transition,
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "selection": {
            "selection_mode": "structured_predicate",
            "opcode": effect.opcode,
            "coverage_status": effect.coverage_status,
            "source_trace": effect.source.to_json(),
        },
    }


def _dynamic_value_source_case(
    ir: CanonicalIR,
    rules: RuleBook,
    state: BattleState,
    command: ActionCommand,
) -> dict[str, Any]:
    registry = EffectRegistry(StatusSystem(rules))
    effect = _select_dynamic_value_store_effect(ir)
    case = _dynamic_value_store_case(registry, state, command, effect)
    if isinstance(effect, EffectIR):
        before_state = case.get("before_state")
        after_state = case.get("after_state")
        transition = case.get("transition")
        if isinstance(before_state, BattleState) and isinstance(after_state, BattleState) and isinstance(transition, BattleTransition):
            replay = MutationReducer().replay_snapshot(
                before_state,
                transition.transaction.mutations,
                after_state.snapshot().to_json(),
            )
            case["replay"] = {"ok": replay.ok, "errors": list(replay.errors)}
        case.setdefault(
            "selection",
            {
                "selection_mode": "structured_predicate",
                "opcode": effect.opcode,
                "coverage_status": effect.coverage_status,
                "source_trace": effect.source.to_json(),
            },
        )
        case.setdefault("before_state", state)
    return case


def _source_audit_checks(
    rules: RuleBook,
    transitions: dict[str, object],
) -> dict[str, object]:
    auditor = RuntimeSourceAuditor(rules)
    results: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for name, transition in transitions.items():
        if not isinstance(transition, BattleTransition):
            checks[f"{name}_transition_exists"] = False
            results[name] = {"ok": False, "violations": [{"reason": "transition_missing"}]}
            continue
        audit = auditor.validate_transition(transition)
        checks[f"{name}_source_audit_ok"] = audit.ok
        checks[f"{name}_checked_mutations"] = audit.checked_mutations > 0 or name.startswith("no_fake")
        results[name] = audit.to_json()
    return {"ok": all(checks.values()), "checks": checks, "results": results}


def _sample_source_trace(audit_results: dict[str, Any]) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    wanted = {
        "damage": ("damage_system",),
        "resource": ("combat_executor.resources",),
        "timeline": ("combat_executor.timeline",),
        "status_or_effect": ("status_system", "effect_system"),
    }
    for label, sources in wanted.items():
        for result in audit_results.values():
            for trace in result.get("traces", []) if isinstance(result, dict) else []:
                mutation = trace.get("mutation", {}) if isinstance(trace, dict) else {}
                if isinstance(mutation, dict) and mutation.get("source") in sources:
                    samples[label] = trace
                    break
            if label in samples:
                break
    return {
        "ok": all(label in samples for label in wanted),
        "samples": samples,
        "missing": [label for label in wanted if label not in samples],
    }


def _mutation_source_category_checks(transitions: dict[str, object]) -> dict[str, object]:
    sources: set[str] = set()
    for transition in transitions.values():
        if isinstance(transition, BattleTransition):
            sources.update(mutation.source for mutation in transition.transaction.mutations)
    checks = {
        "has_timeline_mutation": "combat_executor.timeline" in sources,
        "has_resource_mutation": "combat_executor.resources" in sources,
        "has_damage_mutation": "damage_system" in sources,
        "has_status_or_effect_mutation": bool({"status_system", "effect_system"} & sources),
    }
    return {"ok": all(checks.values()), "checks": checks, "sources": sorted(sources)}


def _no_fake_damage_unchanged_checks(case: dict[str, Any]) -> dict[str, object]:
    transition = case.get("transition")
    checks = {
        "transition_exists": isinstance(transition, BattleTransition),
        "no_damage_mutation": isinstance(transition, BattleTransition)
        and all(mutation.source != "damage_system" for mutation in transition.transaction.mutations),
        "blocked_or_no_emission_record": isinstance(transition, BattleTransition)
        and any(
            isinstance(record, dict)
            and record.get("record_type") in {"damage_emission_blocked", "damage_emissions", "action_blocked"}
            for record in (transition.transaction.settlement.records if transition.transaction.settlement else ())
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _executable_ir_source_checks(ir: CanonicalIR) -> dict[str, object]:
    nodes = (
        *ir.action_definitions,
        *ir.action_events,
        *ir.hit_profiles,
        *ir.damage_emissions,
        *ir.ability_tasks,
        *ir.effects,
        *ir.conditions,
        *ir.triggers,
    )
    violations = []
    for node in nodes:
        if getattr(node, "coverage_status", "") != "executable":
            continue
        source = getattr(node, "source", None)
        source_json = source.to_json() if source is not None else {}
        if not source_json.get("source_path") or not source_json.get("raw_type") or not source_json.get("raw_id"):
            violations.append({"node": _node_id(node), "reason": "missing_source", "source": source_json})
        if "Missing" in str(source_json.get("raw_type", "")) or "Missing" in str(source_json.get("raw_id", "")):
            violations.append({"node": _node_id(node), "reason": "placeholder_source", "source": source_json})
    return {"ok": not violations, "violations": violations[:50], "checked_executable_nodes": sum(1 for node in nodes if getattr(node, "coverage_status", "") == "executable")}


def _non_mutating_status_checks(ir: CanonicalIR, transitions: dict[str, object]) -> dict[str, object]:
    forbidden_statuses = {"audit_only", "blocked", "discovered_only", "skipped_with_reason", "unsupported"}
    forbidden_damage_emissions: set[str] = set()
    forbidden_effects: set[str] = set()
    forbidden_actions: set[str] = set()
    for node in ir.damage_emissions:
        if getattr(node, "coverage_status", "") in forbidden_statuses:
            forbidden_damage_emissions.add(node.damage_emission_id)
    for node in ir.effects:
        if getattr(node, "coverage_status", "") in forbidden_statuses:
            forbidden_effects.add(node.effect_id)
    for node in ir.action_definitions:
        if getattr(node, "coverage_status", "") in forbidden_statuses:
            forbidden_actions.add(node.definition_id)
    violations = []
    for name, transition in transitions.items():
        if not isinstance(transition, BattleTransition):
            continue
        for mutation in transition.transaction.mutations:
            metadata = mutation.metadata
            matched: list[str] = []
            if mutation.source == "damage_system" and metadata.get("damage_emission_id") in forbidden_damage_emissions:
                matched.append(str(metadata.get("damage_emission_id")))
            if mutation.source in {"effect_system", "status_system"}:
                effect_id = metadata.get("effect_id")
                lifecycle = metadata.get("lifecycle_plan")
                if not effect_id and isinstance(lifecycle, dict):
                    source_trace = lifecycle.get("source_trace")
                    if isinstance(source_trace, dict):
                        effect_id = source_trace.get("effect_id")
                if effect_id in forbidden_effects:
                    matched.append(str(effect_id))
            if mutation.source in {"combat_executor.timeline", "combat_executor.resources"} and metadata.get("definition_id") in forbidden_actions:
                matched.append(str(metadata.get("definition_id")))
            if matched:
                violations.append(
                    {
                        "transition": name,
                        "mutation_id": mutation.stable_id(),
                        "source": mutation.source,
                        "matched_forbidden_ids": matched,
                    }
                )
    return {
        "ok": not violations,
        "violations": violations[:50],
        "forbidden_id_count": len(forbidden_damage_emissions) + len(forbidden_effects) + len(forbidden_actions),
    }


def _validation_sample_policy_checks(package_root: Path) -> dict[str, object]:
    violations = []
    for filename in ("validate_v0_215.py", "validate_v0_216.py", "validate_v0_217.py"):
        path = package_root / "tools" / filename
        text = path.read_text(encoding="utf-8")
        for token in FIXED_SAMPLE_TOKENS:
            if token in text:
                violations.append({"path": f"tools/{filename}", "token": token})
    return {"ok": not violations, "violations": violations}


def _node_id(node: object) -> str:
    for field in (
        "definition_id",
        "action_event_id",
        "hit_profile_id",
        "damage_emission_id",
        "task_id",
        "effect_id",
        "condition_id",
        "trigger_id",
    ):
        value = getattr(node, field, "")
        if isinstance(value, str) and value:
            return value
    return type(node).__name__


if __name__ == "__main__":
    raise SystemExit(main())
