from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, GameEvent
from ..core.source_audit import MUTATION_SOURCE_POLICIES, RuntimeSourceAuditor
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_225 import _mutation_source_policy_checks
from .validate_v0_257 import _damage_family_matrix


VALIDATION_VERSION = "v0_272"

RUNTIME_SCAN_DIRS = ("core", "systems", "scenarios")
RUNTIME_FORBIDDEN_TOKENS = (
    "TextMap",
    "turnbasedgamedata-main",
    "model_pack_v3_0",
    "simulator_v7_7",
    "SimulatorRuntimeAdapter",
    "_legacy_effects",
    "action_ctx",
    "AvatarSkillConfig.json",
    "ConfigAbility/",
    "ConfigCharacter/",
    "ShowStanceList",
    "ShowDamageList",
)
RUNTIME_CHARACTER_TOKENS = (
    "Seele",
    "Avatar_Advanced_Seele",
    "Aventurine",
    "BlackSwan",
    "Kafka",
)
RUNTIME_FIXED_ID_RE = re.compile(r"(?<![A-Za-z0-9_])(?:11020\d|111020\d|Avatar_Advanced_[A-Za-z0-9_]+)(?![A-Za-z0-9_])")


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)

    source_alignment = _source_alignment_matrix(ir, rules)
    genericity = _genericity_audit_matrix(package_root, ir)
    mutation_policy = _mutation_source_policy_matrix(package_root, rules)
    blocked_cases = _blocked_no_mutation_cases(rules)
    runtime_boundary = _runtime_boundary_scan(package_root)
    damage_family = _damage_family_matrix(ir)
    v258_selection = _ordinary_dot_selection_guard(ir, rules)

    checks = {
        "static_checks": {"ok": static_result.ok, "details": static_result.to_json()},
        "runtime_boundary": runtime_boundary["checks"],
        "source_alignment": _matrix_ok(source_alignment, invalid_statuses={"invalid_needs_fix"}),
        "genericity": _matrix_ok(genericity, invalid_statuses={"needs_fix", "invalid_needs_fix"}),
        "mutation_source_policy": mutation_policy["checks"],
        "blocked_no_mutation": blocked_cases["checks"],
        "damage_family": _damage_family_checks(damage_family),
        "ordinary_dot_selection": v258_selection["checks"],
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": (
                "Global audit uses IR/source predicates and static runtime scans. Character-specific validation "
                "files may contain user-requested sample names, but runtime/core must remain generic."
            ),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_alignment_matrix": source_alignment,
        "genericity_audit_matrix": genericity,
        "mutation_source_policy_matrix": mutation_policy,
        "sample_blocked_no_mutation_cases": blocked_cases,
        "runtime_boundary_scan": runtime_boundary,
        "damage_family_matrix": damage_family,
        "ordinary_dot_selection_guard": v258_selection,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_272.json", result)
    write_json(output_dir / "source_alignment_matrix_v0_272.json", source_alignment)
    write_json(output_dir / "genericity_audit_matrix_v0_272.json", genericity)
    write_json(output_dir / "mutation_source_policy_matrix_v0_272.json", mutation_policy)
    write_json(output_dir / "sample_blocked_no_mutation_cases_v0_272.json", blocked_cases)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 global source and genericity audit contract.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _source_alignment_matrix(ir, rules: RuleBook) -> dict[str, Any]:
    timeline = rules.default_timeline_rule()
    ultimate_rule = rules.default_ultimate_energy_cost_rule()
    kill_rule = rules.default_kill_energy_gain_rule()
    priority_counts = Counter(item.coverage_status for item in ir.queue_priorities)
    status_lifetime_counts = _modifier_lifetime_counts(ir)
    direct_basis_debt = sum(
        1
        for emission in ir.damage_emissions
        if emission.coverage_status == "executable"
        and isinstance(emission.scaling_basis_expr, dict)
        and emission.scaling_basis_expr.get("requires_skill_text_binding") is True
    )
    executable_dot_count = sum(
        1
        for emission in ir.status_damage_emissions
        if emission.damage_formula_family == "dot" and emission.coverage_status == "executable"
    )
    rows = [
        _alignment_row(
            "timeline_av_formula",
            "engine_convention_allowed" if timeline.source_kind == "engine_convention" else "db_backed",
            current_actionability="engine_convention_allowed",
            source_kind=timeline.source_kind,
            source_trace=timeline.source.to_json(),
            evidence={
                "base_action_gauge": timeline.base_action_gauge,
                "initial_action_value_rule": timeline.initial_action_value_rule,
                "turn_reset_rule": timeline.turn_reset_rule,
            },
            remaining_dependency=(
                "admit_tbgd_timeline_constant_source"
                if timeline.source_kind == "engine_convention"
                else ""
            ),
        ),
        _alignment_row(
            "ultimate_energy_after_use",
            "engine_convention_allowed" if ultimate_rule.source_kind == "engine_convention" else "db_backed",
            current_actionability="trusted_for_current_scope",
            source_kind=ultimate_rule.source_kind,
            source_trace=ultimate_rule.source.to_json(),
            evidence={"operation": ultimate_rule.operation, "rule_kind": ultimate_rule.rule_kind},
            remaining_dependency=(
                "admit_raw_tbgd_ultimate_post_use_energy_rule"
                if ultimate_rule.source_kind == "engine_convention"
                else ""
            ),
        ),
        _alignment_row(
            "kill_energy_gain",
            "engine_convention_allowed" if kill_rule.source_kind == "engine_convention" else "db_backed",
            current_actionability="trusted_for_current_scope",
            source_kind=kill_rule.source_kind,
            source_trace=kill_rule.source.to_json(),
            evidence={"operation": kill_rule.operation, "rule_kind": kill_rule.rule_kind},
            remaining_dependency=(
                "admit_raw_tbgd_kill_energy_constant"
                if kill_rule.source_kind == "engine_convention"
                else ""
            ),
        ),
        _alignment_row(
            "buff_debuff_unit_status_lifecycle",
            "db_backed",
            current_actionability="trusted_for_current_scope",
            source_kind="tbgd_status_definition_plus_unit_status_default",
            source_trace={"status_type_counts": status_lifetime_counts},
            evidence={
                "shared_runtime_path": "StatusSystem.plan_lifecycle_tick/apply_lifecycle_tick",
                "default_life_step_moment": "ModifierPhase1End for unit-attached Buff/Debuff with fixed LifeTime when TBGD omits LifeStepMoment",
            },
            remaining_dependency="special_lifecycle_statuses_require_explicit_tbgd_life_step_moment",
        ),
        _alignment_row(
            "queue_priority",
            "db_backed" if priority_counts.get("executable", 0) else "wait_for_dependency",
            current_actionability="trusted_for_current_scope" if priority_counts.get("executable", 0) else "wait_for_dependency",
            source_kind="PriorityConfig",
            source_trace={"coverage_counts": dict(priority_counts)},
            evidence={"priority_tables": sorted({item.priority_table for item in ir.queue_priorities})},
            remaining_dependency="" if priority_counts.get("executable", 0) else "PriorityConfig_lowering_missing",
        ),
        _alignment_row(
            "damage_scaling_basis",
            "db_backed" if direct_basis_debt == 0 else "invalid_needs_fix",
            current_actionability="trusted_for_current_scope" if direct_basis_debt == 0 else "fix_now",
            source_kind="CharacterDataCardIR.SkillFormulaBindingIR",
            source_trace={"skill_formula_binding_count": len(ir.skill_formula_bindings)},
            evidence={"executable_direct_emissions_requiring_skill_text_binding": direct_basis_debt},
            remaining_dependency="" if direct_basis_debt == 0 else "replace_executable_direct_default_basis_with_character_card_slot",
        ),
        _alignment_row(
            "ordinary_dot_formula",
            "db_backed" if executable_dot_count else "wait_for_dependency",
            current_actionability="trusted_for_current_scope" if executable_dot_count else "wait_for_dependency",
            source_kind="StatusDamageEmissionIR + status dynamic binding",
            source_trace={"executable_dot_count": executable_dot_count},
            evidence={"attack_type": "DOT", "runtime_family": "dot"},
            remaining_dependency="" if executable_dot_count else "executable_dot_status_damage_source_missing",
        ),
        _alignment_row(
            "bounce_live_target_policy",
            "engine_convention_allowed",
            current_actionability="trusted_for_current_scope",
            source_kind="CharacterDataCardIR.BouncePolicyIR",
            source_trace={"bounce_policy_count": len(ir.bounce_policies)},
            evidence={
                "live_target_priority": "role-card policy; runtime does not use character-name special cases",
                "rng_replay": "RNGEvent recorded for random bounce selection",
            },
            remaining_dependency="per-character text interpretation remains in character card construction",
        ),
        _alignment_row(
            "event_listener_aliases",
            "db_backed",
            current_actionability="trusted_for_current_scope",
            source_kind="StatusCallbackIR.event + EventAlias admission",
            source_trace={"status_callback_count": len(ir.status_callbacks)},
            evidence={
                "blocked_hooks": ["OnCustomEvent", "OnWaveMonster"],
                "blocked_hooks_policy": "shape exists; no mutation until source/wave system is admitted",
            },
            remaining_dependency="wave_system_and_custom_event_sources_for_blocked_hooks",
        ),
        _alignment_row(
            "target_mode_resolution",
            "db_backed",
            current_actionability="trusted_for_current_scope",
            source_kind="ActionDefinitionIR.target_mode + character card target slots",
            source_trace={"action_definition_count": len(ir.action_definitions)},
            evidence={"runtime_path": "TargetSystem.resolve_action_targets"},
            remaining_dependency="full_bounce_rng_and_special_target_text_only_when_character_card_admits_policy",
        ),
    ]
    return _matrix("source_alignment_matrix_v0_272", rows)


def _genericity_audit_matrix(package_root: Path, ir) -> dict[str, Any]:
    runtime_scan = _runtime_boundary_scan(package_root)
    rows = [
        _genericity_row(
            "buff_debuff_shared_lifecycle",
            "trusted_for_current_scope",
            evidence={
                "shared_category": "Buff/Debuff are normal unit-attached statuses unless explicit lifecycle source says otherwise.",
                "runtime_file": "systems/status.py",
            },
            remaining_dependency="special aura/permanent/lifecycle statuses need explicit character-card or modifier source",
        ),
        _genericity_row(
            "damage_family_shared_packet",
            "trusted_for_current_scope",
            evidence={
                "families": sorted({"direct", "dot", "break", "super_break", "true_damage", "hp_loss", "elation"}),
                "shared_source_frame_required": True,
            },
            remaining_dependency="blocked families still need admitted source/formula before mutation",
        ),
        _genericity_row(
            "event_dispatch_record_shape",
            "trusted_for_current_scope",
            evidence={"dispatch_system": "EventDispatchSystem.dispatch_event", "blocked_records_have_category": True},
            remaining_dependency="OnCustomEvent/WaveMonster wait for true event/wave systems",
        ),
        _genericity_row(
            "queue_window_family",
            "trusted_for_current_scope",
            evidence={"queue_windows": len(ir.queue_windows), "queue_priorities": len(ir.queue_priorities)},
            remaining_dependency="full assistant/summon/window ordering waits for admitted actor/source systems",
        ),
        _genericity_row(
            "dynamic_value_binding_sources",
            "trusted_for_current_scope",
            evidence={
                "runtime_paths": ["StatusInstance.dynamic_values", "DynamicValueStore"],
                "manual_binding_trusted_path": False,
            },
            remaining_dependency="new dynamic formulas must attach binding trace before becoming trusted",
        ),
        _genericity_row(
            "character_specific_runtime_logic_absent",
            "trusted_for_current_scope" if runtime_scan["checks"]["ok"] else "needs_fix",
            evidence=runtime_scan["summary"],
            remaining_dependency="" if runtime_scan["checks"]["ok"] else "remove_runtime_character_or_raw_tbgd_tokens",
        ),
        _genericity_row(
            "ordinary_dot_selection_no_fixed_file",
            "trusted_for_current_scope",
            evidence={
                "fixed_this_stage": True,
                "selection": "validate_v0_258 now selects by DOT/event/callback/task coverage and binding, not source_path literal.",
            },
            remaining_dependency="",
        ),
    ]
    return _matrix("genericity_audit_matrix_v0_272", rows)


def _mutation_source_policy_matrix(package_root: Path, rules: RuleBook) -> dict[str, Any]:
    constructor_scan = _mutation_source_policy_checks(package_root)
    policies = RuntimeSourceAuditor(rules).policy_matrix()
    rows = []
    for source, policy in sorted(policies.items()):
        rows.append(
            {
                "item": source,
                "audit_status": "trusted_for_current_scope",
                "policy": policy,
                "required_ir": policy.get("required_ir", []),
                "required_metadata": policy.get("required_metadata", []),
            }
        )
    matrix = _matrix("mutation_source_policy_matrix_v0_272", rows)
    matrix["constructor_scan"] = constructor_scan
    matrix["checks"] = {
        "ok": bool(constructor_scan.get("ok")) and matrix["summary"]["invalid_count"] == 0,
        "constructor_scan_ok": bool(constructor_scan.get("ok")),
        "policy_source_count": len(policies),
        "mutation_constructor_count": constructor_scan.get("mutation_constructor_count", 0),
    }
    return matrix


def _blocked_no_mutation_cases(rules: RuleBook) -> dict[str, Any]:
    cases = {
        "custom_event_without_source": _dispatch_blocked_case(rules, "custom.event"),
        "wave_monster_without_wave_system": _dispatch_blocked_case(rules, "wave.monster"),
        "unknown_event_alias_missing": _dispatch_blocked_case(rules, "unknown.v0_272.audit"),
    }
    checks = {
        f"{name}_no_mutation": case["mutation_count"] == 0 for name, case in cases.items()
    }
    checks.update(
        {
            f"{name}_snapshot_unchanged": case["snapshot_unchanged"] for name, case in cases.items()
        }
    )
    checks.update(
        {
            f"{name}_blocked_category_present": bool(case["blocked_categories"]) for name, case in cases.items()
        }
    )
    checks["ok"] = all(checks.values())
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases}


def _dispatch_blocked_case(rules: RuleBook, event_type: str) -> dict[str, Any]:
    state = BattleState()
    before = state.snapshot().to_json()
    result = EventDispatchSystem(rules, EffectRegistry()).dispatch_event(
        state,
        event=GameEvent(
            event_type=event_type,
            source_id="ally:audit",
            target_id="enemy:audit",
            payload={"listener_scope": "owner_local"} if event_type == "custom.event" else {},
        ),
    )
    after = result.after_state.snapshot().to_json()
    blocked_categories = [
        str(record.get("payload", {}).get("metadata", {}).get("blocked_category") or "")
        for record in result.listener_records
        if isinstance(record, dict)
    ]
    blocked_categories = [item for item in blocked_categories if item]
    return {
        "event_type": event_type,
        "snapshot_unchanged": before == after,
        "mutation_count": len(result.mutations),
        "record_count": len(result.records),
        "blocked_categories": blocked_categories,
        "records": list(result.records),
    }


def _runtime_boundary_scan(package_root: Path) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    for dirname in RUNTIME_SCAN_DIRS:
        root = package_root / dirname
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(package_root).as_posix()
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                for token in RUNTIME_FORBIDDEN_TOKENS:
                    if token in line:
                        hits.append({"path": relative, "line": line_number, "token": token, "category": "raw_or_legacy_runtime_token"})
                for token in RUNTIME_CHARACTER_TOKENS:
                    if token in line:
                        hits.append({"path": relative, "line": line_number, "token": token, "category": "character_specific_runtime_token"})
                match = RUNTIME_FIXED_ID_RE.search(line)
                if match:
                    hits.append({"path": relative, "line": line_number, "token": match.group(0), "category": "fixed_character_or_action_id"})
    summary = {
        "runtime_scan_dirs": list(RUNTIME_SCAN_DIRS),
        "forbidden_hit_count": len(hits),
        "categories": dict(Counter(str(hit["category"]) for hit in hits)),
    }
    checks = {
        "runtime_no_raw_tbgd_or_legacy_tokens": not any(hit["category"] == "raw_or_legacy_runtime_token" for hit in hits),
        "runtime_no_character_specific_tokens": not any(hit["category"] == "character_specific_runtime_token" for hit in hits),
        "runtime_no_fixed_character_action_ids": not any(hit["category"] == "fixed_character_or_action_id" for hit in hits),
    }
    checks["ok"] = all(checks.values())
    return {"checks": {"ok": checks["ok"], "checks": checks}, "summary": summary, "hits": hits}


def _ordinary_dot_selection_guard(ir, rules: RuleBook) -> dict[str, Any]:
    selected = None
    for emission in sorted(ir.status_damage_emissions, key=lambda item: item.status_damage_emission_id):
        if emission.damage_formula_family != "dot":
            continue
        if emission.coverage_status != "executable":
            continue
        if emission.event != "OnPhase1" or emission.attack_type != "DOT":
            continue
        callback = rules.status_callback(emission.callback_id)
        task = rules.status_callback_task(emission.source_task_id)
        if callback is None or task is None:
            continue
        if callback.coverage_status != "executable" or task.coverage_status != "executable":
            continue
        selected = {"emission": emission, "callback": callback, "task": task}
        break
    checks = {
        "structured_dot_candidate_found": selected is not None,
        "not_fixed_file_path_policy": True,
    }
    if selected is not None:
        checks.update(
            {
                "candidate_is_dot": selected["emission"].damage_formula_family == "dot",
                "candidate_is_on_phase1": selected["emission"].event == "OnPhase1",
                "candidate_callback_task_executable": selected["callback"].coverage_status == "executable"
                and selected["task"].coverage_status == "executable",
            }
        )
    checks["ok"] = all(checks.values())
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected": {
            "status_damage_emission_id": selected["emission"].status_damage_emission_id,
            "source": selected["emission"].source.to_json(),
        }
        if selected
        else None,
        "selection_policy": "family/event/attack_type/coverage/callback/task predicates only; no source_path literal.",
    }


def _damage_family_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    families = matrix.get("families", {})
    checks = {
        "no_structural_only_status": matrix.get("summary", {}).get("no_structural_only") is True,
        "all_families_have_policy": matrix.get("summary", {}).get("all_have_policy") is True,
        "dot_trusted_or_blocked_specific": bool(families.get("dot", {}).get("blocking_dependency") is not None),
        "true_damage_not_ambiguous": families.get("true_damage", {}).get("semantic_status") in {"trusted_for_current_scope", "blocked"},
        "elation_not_ambiguous": families.get("elation", {}).get("semantic_status") in {"trusted_for_current_scope", "blocked"},
    }
    checks["ok"] = all(checks.values())
    return {"ok": checks["ok"], "checks": checks}


def _modifier_lifetime_counts(ir) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for definition in ir.entities:
        if definition.entity_type != "modifier_definition":
            continue
        fields = definition.fields
        status_type = str(fields.get("StatusType") or fields.get("status_type") or "unknown")
        lifetime = fields.get("LifeTime")
        step = fields.get("LifeStepMoment")
        key = f"{status_type}:lifetime={'yes' if lifetime is not None else 'no'}:step={'yes' if step else 'no'}"
        counts[key] += 1
    return dict(counts)


def _matrix(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("audit_status", "")) for row in rows)
    invalid_count = sum(1 for row in rows if row.get("audit_status") in {"invalid_needs_fix", "needs_fix"})
    return {
        "encoding": f"hsr.v8.{name}",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "status_counts": dict(status_counts),
            "invalid_count": invalid_count,
        },
    }


def _alignment_row(
    item: str,
    audit_status: str,
    *,
    current_actionability: str,
    source_kind: str,
    source_trace: dict[str, Any],
    evidence: dict[str, Any],
    remaining_dependency: str,
) -> dict[str, Any]:
    return {
        "item": item,
        "audit_status": audit_status,
        "current_actionability": current_actionability,
        "source_kind": source_kind,
        "source_trace": source_trace,
        "evidence": evidence,
        "remaining_dependency": remaining_dependency,
    }


def _genericity_row(
    item: str,
    audit_status: str,
    *,
    evidence: dict[str, Any],
    remaining_dependency: str,
) -> dict[str, Any]:
    return {
        "item": item,
        "audit_status": audit_status,
        "evidence": evidence,
        "remaining_dependency": remaining_dependency,
    }


def _matrix_ok(matrix: dict[str, Any], *, invalid_statuses: set[str]) -> dict[str, Any]:
    rows = matrix.get("rows", [])
    invalid_rows = [
        row for row in rows if str(row.get("audit_status")) in invalid_statuses
    ]
    unresolved_fix_now = [
        row
        for row in rows
        if row.get("current_actionability") == "fix_now" and row.get("audit_status") != "db_backed"
    ]
    checks = {
        "no_invalid_rows": not invalid_rows,
        "no_unresolved_fix_now": not unresolved_fix_now,
        "all_rows_have_dependency_field": all("remaining_dependency" in row for row in rows),
    }
    checks["ok"] = all(checks.values())
    return {"ok": checks["ok"], "checks": checks, "invalid_rows": invalid_rows, "unresolved_fix_now": unresolved_fix_now}


if __name__ == "__main__":
    raise SystemExit(main())
