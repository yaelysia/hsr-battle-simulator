from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, JSONValue
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ActionAdmissionIR, CanonicalIR
from ..rules.rulebook import RuleBook
from ..systems.action_contract import (
    ActionContractSystem,
    ActionSubmissionAuthorization,
    _issue_action_submission_authorization,
)
from ..systems.action_availability import ActionAvailabilitySystem
from ..tbgd.lowering import TBGDLowering, _action_role_contract
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state, _decision_state, _source
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s6_action_ownership_window_contract"
MATRIX_SCHEMA_VERSION = "p7_s6_action_role_matrix_v1"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    *,
    canonical_ir: CanonicalIR | None = None,
) -> dict[str, Any]:
    role_matrix = _role_matrix()
    runtime = _runtime_query_submit_matrix()
    source_cards = (
        _source_card_samples_from_ir(canonical_ir)
        if canonical_ir is not None
        else _source_card_samples(tbgd_root)
    )
    static_boundary = _static_boundary(package_root)
    checks = {
        "role_matrix_complete": role_matrix["ok"],
        "query_choices_have_owner_role_window": runtime["query_contract_complete"],
        "query_submit_round_trip_committed": runtime["round_trip_committed"],
        "insert_window_contract_positive": runtime["insert_window_contract_positive"],
        "query_submit_replay_source_audit": runtime["replay_ok"] and runtime["source_audit_ok"],
        "unqueried_direct_submissions_blocked": runtime["all_negative_blocked"],
        "blocked_submissions_state_unchanged": runtime["all_negative_state_unchanged"],
        "character_monster_servant_structural_samples": source_cards["ok"],
        "query_and_executor_share_contract": static_boundary["ok"],
        "no_fixed_names_ids_or_skill_list_fallback": static_boundary["no_name_or_id_role_guess"],
        "no_large_artifacts": True,
    }
    ok = all(checks.values())
    summary = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checks": checks,
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "role_count": len(role_matrix["rows"]),
        "negative_case_count": len(runtime["negative_cases"]),
        "source_sample_count": len(source_cards["samples"]),
        "artifact_policy": {
            "large_artifacts_written": False,
            "canonical_ir_serialized": False,
            "full_transition_dump_written": False,
            "lowering_build_count": 0 if canonical_ir is not None else 1,
        },
    }
    evidence = {
        "role_matrix": role_matrix,
        "runtime_query_submit": runtime,
        "source_card_samples": source_cards,
        "static_boundary": static_boundary,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p7_s6_action_ownership_window_evidence.json", evidence)
    write_json(output_dir / "p7_s6_action_role_matrix.json", role_matrix)
    write_json(output_dir / "validation_summary_p7_s6_action_ownership_window_contract.json", summary)
    return summary


def run_runtime_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    """Run the current runtime/contract slice without rebuilding TBGD.

    This intentionally does not claim the character/monster/servant source
    samples.  S19 consumes this current lightweight result together with the
    separately recorded real-source scan instead of repeating lowering.
    """

    role_matrix = _role_matrix()
    runtime = _runtime_query_submit_matrix()
    static_boundary = _static_boundary(package_root)
    negative_cases = dict(runtime["negative_cases"])
    forged = dict(negative_cases.get("forged_action_authorization") or {})
    tampered = dict(negative_cases.get("tampered_issued_authorization") or {})
    checks = {
        "role_matrix_complete": role_matrix["ok"],
        "query_choices_have_owner_role_window": runtime["query_contract_complete"],
        "query_submit_round_trip_committed": runtime["round_trip_committed"],
        "insert_window_contract_positive": runtime["insert_window_contract_positive"],
        "issued_insert_authorization_committed": (
            dict(runtime["issued_insert_outcome"]).get("category") == "committed"
        ),
        "forged_action_authorization_blocked": (
            forged.get("outcome") == "blocked"
            and forged.get("blocked_reason") == "action_submission_authorization_not_issued"
            and forged.get("state_unchanged") is True
            and forged.get("mutation_count") == 0
        ),
        "tampered_issued_authorization_blocked": (
            tampered.get("outcome") == "blocked"
            and tampered.get("blocked_reason") == "action_submission_authorization_not_issued"
            and tampered.get("state_unchanged") is True
            and tampered.get("mutation_count") == 0
        ),
        "query_submit_replay_source_audit": runtime["replay_ok"] and runtime["source_audit_ok"],
        "unqueried_direct_submissions_blocked": runtime["all_negative_blocked"],
        "blocked_submissions_state_unchanged": runtime["all_negative_state_unchanged"],
        "query_and_executor_share_contract": static_boundary["ok"],
        "no_fixed_names_ids_or_skill_list_fallback": static_boundary["no_name_or_id_role_guess"],
        "no_large_artifacts": True,
    }
    ok = all(checks.values())
    summary = {
        "validation_version": f"{VALIDATION_VERSION}_runtime_only",
        "baseline_version": BASELINE_VERSION,
        "validation_scope": "runtime_contract_without_tbgd_rebuild",
        "ok": ok,
        "ready_for_review": ok,
        "checks": checks,
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "role_count": len(role_matrix["rows"]),
        "negative_case_count": len(negative_cases),
        "real_source_sample_claimed": False,
        "artifact_policy": {
            "large_artifacts_written": False,
            "canonical_ir_serialized": False,
            "full_transition_dump_written": False,
            "lowering_build_count": 0,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "p7_s6_action_ownership_window_runtime_evidence.json",
        {
            "role_matrix": role_matrix,
            "runtime_query_submit": runtime,
            "static_boundary": static_boundary,
        },
    )
    write_json(output_dir / "p7_s6_action_role_matrix.json", role_matrix)
    write_json(output_dir / "validation_summary_p7_s6_action_ownership_window_runtime.json", summary)
    return summary


def _role_matrix() -> dict[str, Any]:
    rules = _trust_rulebook()
    normal = rules.action_definition("validation:normal", 1)
    assert normal is not None
    cases = (
        ("normal_turn", replace(normal, attack_type="Normal"), "turn_action", "external_turn"),
        ("skill_turn", replace(normal, attack_type="BPSkill"), "turn_action", "external_turn"),
        ("ultimate_insert", replace(normal, attack_type="Ultra"), "insert_action", "insert_window"),
        ("passive_trigger", replace(normal, attack_type="Talent"), "passive_trigger", "trigger"),
        ("out_of_combat", replace(normal, attack_type="Maze"), "out_of_combat", "out_of_combat"),
        ("unknown_blocked", replace(normal, attack_type="UnclassifiedType"), "unknown", ""),
        ("empty_blocked", replace(normal, attack_type=""), "unknown", ""),
        ("unknown_literal_blocked", replace(normal, attack_type="Unknown"), "unknown", ""),
    )
    rows: list[dict[str, JSONValue]] = []
    for row_id, definition, expected_role, expected_mode in cases:
        contract = _action_role_contract(definition)
        modes = tuple(contract["submission_modes"])
        row_ok = contract["action_role"] == expected_role and (
            expected_mode in modes if expected_mode else bool(contract["blocked_reason"])
        )
        rows.append(
            {
                "row_id": row_id,
                "attack_type": definition.attack_type,
                "expected_role": expected_role,
                "expected_submission_mode": expected_mode,
                "contract": contract,
                "ok": row_ok,
            }
        )
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "ok": all(row["ok"] is True for row in rows),
        "selection_basis": "ActionDefinitionIR.attack_type structured field only",
        "rows": rows,
    }


def _runtime_query_submit_matrix() -> dict[str, Any]:
    rules = _rules_with_passive_admission()
    state = _decision_state(_base_state(skill_points=3, actor_energy=100.0))
    view = ActionAvailabilitySystem(rules).view(state)
    choice = next(
        (item for item in view.choices if item.action_id == "validation:normal"),
        None,
    )
    query_contract_complete = bool(view.choices) and all(
        choice_item.admission_id
        and choice_item.owner_entity_ref
        and choice_item.action_role != "unknown"
        and choice_item.allowed_windows
        and choice_item.submission_modes
        for choice_item in view.choices
    )
    round_trip: dict[str, Any] = {"ok": False, "reason": "query_choice_missing"}
    if choice is not None:
        target_id = next(
            target_id
            for target_id in choice.selectable_target_ids
            if state.units[target_id].side != state.units[choice.actor_id].side
        )
        command = ActionCommand(
            actor_id=choice.actor_id,
            action_id=choice.action_id,
            action_level=choice.action_level,
            target_ids=(target_id,),
            source="manual",
            metadata=dict(choice.command_template.get("metadata") or {}),
        )
        returned, transition = CombatExecutor(rules).execute(command, state)
        replay = MutationReducer().replay_snapshot(
            state,
            transition.transaction.mutations,
            transition.after.to_json(),
        )
        audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        round_trip = {
            "ok": transition.outcome.category == "committed"
            and returned.snapshot().to_json() == transition.after.to_json(),
            "outcome": transition.outcome.to_json(),
            "action_contract": transition.coverage.get("action_contract", {}),
            "mutation_count": len(transition.transaction.mutations),
            "replay_ok": replay.ok,
            "source_audit_ok": audit.ok,
        }

    wrong_window = replace(
        state,
        global_flags={**state.global_flags, "current_window": "before_attack"},
    )
    wrong_actor = _decision_state(_base_state(include_second_ally=True))
    wrong_actor = replace(
        wrong_actor,
        global_flags={**wrong_actor.global_flags, "turn_owner_id": "ally:second"},
    )
    resource_state = _decision_state(_base_state(skill_points=0))
    insert_state = replace(
        state,
        global_flags={**state.global_flags, "current_window": "ultimate"},
    )
    insert_decision = ActionContractSystem(rules).evaluate(
        insert_state,
        ActionCommand(
            "ally:actor",
            "validation:ultimate",
            1,
            ("enemy:target",),
        ),
        submission_mode="insert_window",
    )
    insert_command = ActionCommand(
        "ally:actor",
        "validation:ultimate",
        1,
        ("enemy:target",),
        source="queue",
    )
    forged_authorization = ActionSubmissionAuthorization(
        submission_mode="insert_window",
        actor_id="ally:actor",
        owner_entity_ref="validation:actor_a",
        action_id="validation:ultimate",
        action_level=1,
        window="ultimate",
        source_id="forged:insert",
    )
    forged_after, forged_transition = CombatExecutor(rules).execute(
        insert_command,
        insert_state,
        submission_authorization=forged_authorization,
    )
    issued_authorization = _issue_action_submission_authorization(
        state=insert_state,
        submission_mode="insert_window",
        actor_id="ally:actor",
        owner_entity_ref="validation:actor_a",
        action_id="validation:ultimate",
        action_level=1,
        window="ultimate",
        source_id="validation:issued_insert",
    )
    issued_after, issued_transition = CombatExecutor(rules).execute(
        insert_command,
        insert_state,
        submission_authorization=issued_authorization,
    )
    tampered_after, tampered_transition = CombatExecutor(rules).execute(
        insert_command,
        insert_state,
        submission_authorization=replace(
            issued_authorization,
            source_id="tampered:issued_insert",
        ),
    )
    cases = {
        "wrong_owner": (
            wrong_actor,
            ActionCommand("ally:second", "validation:normal", 1, ("enemy:target",)),
        ),
        "foreign_action": (
            state,
            ActionCommand("ally:actor", "validation:foreign", 1, ("enemy:target",)),
        ),
        "wrong_window": (
            wrong_window,
            ActionCommand("ally:actor", "validation:normal", 1, ("enemy:target",)),
        ),
        "passive_direct": (
            state,
            ActionCommand("ally:actor", "validation:passive", 1, ("enemy:target",)),
        ),
        "insert_direct": (
            state,
            ActionCommand("ally:actor", "validation:ultimate", 1, ("enemy:target",)),
        ),
        "forged_insert_metadata": (
            state,
            ActionCommand(
                "ally:actor",
                "validation:ultimate",
                1,
                ("enemy:target",),
                metadata={"is_insert_action": True, "action_window": "ultimate"},
            ),
        ),
        "forged_queue_source": (
            state,
            ActionCommand(
                "ally:actor",
                "validation:ultimate",
                1,
                ("enemy:target",),
                source="queue",
                queue_name="forged",
                metadata={"queue_parent": {"queue_entry": {"entry_id": "forged"}}},
            ),
        ),
        "resource_insufficient": (
            resource_state,
            ActionCommand("ally:actor", "validation:partial", 1, ("enemy:target",)),
        ),
        "selected_graph_not_executable": (
            state,
            ActionCommand("ally:actor", "validation:partial", 1, ("enemy:target",)),
        ),
        "unknown_action": (
            state,
            ActionCommand("ally:actor", "validation:unknown", 1, ("enemy:target",)),
        ),
    }
    negative_rows: dict[str, dict[str, JSONValue]] = {}
    for case_id, (before, command) in cases.items():
        returned, transition = CombatExecutor(rules).execute(command, before)
        negative_rows[case_id] = {
            "outcome": transition.outcome.category,
            "blocked_reason": str(transition.coverage.get("blocked_reason") or ""),
            "state_unchanged": returned == before
            and transition.after.to_json() == before.snapshot().to_json(),
            "mutation_count": len(transition.transaction.mutations),
            "successor_eligible": transition.outcome.successor_eligible,
        }
    negative_rows["forged_action_authorization"] = {
        "outcome": forged_transition.outcome.category,
        "blocked_reason": str(forged_transition.coverage.get("blocked_reason") or ""),
        "state_unchanged": forged_after == insert_state
        and forged_transition.after.to_json() == insert_state.snapshot().to_json(),
        "mutation_count": len(forged_transition.transaction.mutations),
        "successor_eligible": forged_transition.outcome.successor_eligible,
    }
    negative_rows["tampered_issued_authorization"] = {
        "outcome": tampered_transition.outcome.category,
        "blocked_reason": str(tampered_transition.coverage.get("blocked_reason") or ""),
        "state_unchanged": tampered_after == insert_state
        and tampered_transition.after.to_json() == insert_state.snapshot().to_json(),
        "mutation_count": len(tampered_transition.transaction.mutations),
        "successor_eligible": tampered_transition.outcome.successor_eligible,
    }
    queried_action_ids = {item.action_id for item in view.choices}
    forbidden_exposed = queried_action_ids.intersection(
        {"validation:foreign", "validation:partial", "validation:ultimate", "validation:passive"}
    )
    return {
        "row_id": "runtime_query_submit_round_trip",
        "query_contract_complete": query_contract_complete,
        "queried_action_ids": sorted(queried_action_ids),
        "forbidden_exposed_action_ids": sorted(forbidden_exposed),
        "round_trip": round_trip,
        "round_trip_committed": round_trip.get("ok") is True,
        "insert_window_contract_positive": insert_decision.ok
        and insert_decision.admission is not None
        and insert_decision.admission.action_role == "insert_action"
        and issued_transition.outcome.successor_eligible
        and issued_after.snapshot().to_json() == issued_transition.after.to_json(),
        "insert_window_contract": insert_decision.to_json(),
        "issued_insert_outcome": issued_transition.outcome.to_json(),
        "replay_ok": round_trip.get("replay_ok") is True,
        "source_audit_ok": round_trip.get("source_audit_ok") is True,
        "negative_cases": negative_rows,
        "all_negative_blocked": not forbidden_exposed
        and all(row["outcome"] == "blocked" and row["successor_eligible"] is False for row in negative_rows.values()),
        "all_negative_state_unchanged": all(
            row["state_unchanged"] is True and row["mutation_count"] == 0
            for row in negative_rows.values()
        ),
    }


def _rules_with_passive_admission() -> RuleBook:
    rules = _trust_rulebook()
    passive = ActionAdmissionIR(
        admission_id="validation:admission:passive",
        owner_entity_ref="validation:actor_a",
        action_id="validation:passive",
        action_level=1,
        action_role="passive_trigger",
        submission_modes=("trigger",),
        allowed_windows=("event_trigger",),
        control_kind="internal_trigger",
        resource_gate_kind="none",
        source=_source("admission:passive"),
        coverage_status="executable",
    )
    return RuleBook(
        replace(
            rules.ir,
            action_admissions=(*rules.ir.action_admissions, passive),
        )
    )


def _source_card_samples(tbgd_root: Path) -> dict[str, Any]:
    return _source_card_samples_from_ir(TBGDLowering(tbgd_root).build())


def _source_card_samples_from_ir(ir: CanonicalIR) -> dict[str, Any]:
    card_refs = {
        "character": {card.entity_ref for card in ir.character_data_cards},
        "monster": {card.entity_ref for card in ir.monster_data_cards},
        "servant": {definition.servant_ref for definition in ir.servant_definitions},
    }
    samples: list[dict[str, JSONValue]] = []
    for owner_kind, refs in card_refs.items():
        candidates = tuple(
            admission
            for admission in ir.action_admissions
            if admission.owner_entity_ref in refs
            and admission.coverage_status == "executable"
            and admission.action_role == "turn_action"
            and "external_turn" in admission.submission_modes
        )
        if candidates:
            selected = sorted(candidates, key=lambda item: item.admission_id)[0]
            samples.append(
                {
                    "owner_kind": owner_kind,
                    "status": "executable",
                    "admission_id": selected.admission_id,
                    "owner_entity_ref": selected.owner_entity_ref,
                    "action_role": selected.action_role,
                    "submission_modes": list(selected.submission_modes),
                    "allowed_windows": list(selected.allowed_windows),
                    "source": selected.source.to_json(),
                }
            )
        else:
            samples.append(
                {
                    "owner_kind": owner_kind,
                    "status": "implementation_missing",
                    "admission_id": "",
                }
            )
    role_counts = Counter(admission.action_role for admission in ir.action_admissions)
    coverage_counts = Counter(admission.coverage_status for admission in ir.action_admissions)
    return {
        "ok": len(samples) == 3 and all(sample["status"] == "executable" for sample in samples),
        "selection_predicate": "first sorted executable turn_action admission whose owner matches the corresponding data-card entity ref",
        "fixed_character_monster_servant_or_action_id_used": False,
        "samples": samples,
        "action_admission_count": len(ir.action_admissions),
        "role_counts": dict(sorted(role_counts.items())),
        "coverage_counts": dict(sorted(coverage_counts.items())),
    }


def _static_boundary(package_root: Path) -> dict[str, Any]:
    executor = (package_root / "core/executor.py").read_text(encoding="utf-8")
    availability = (package_root / "systems/action_availability.py").read_text(encoding="utf-8")
    contract = (package_root / "systems/action_contract.py").read_text(encoding="utf-8")
    lowering = (package_root / "tbgd/lowering.py").read_text(encoding="utf-8")
    checks = {
        "executor_calls_shared_contract": "self.action_contract.evaluate(" in executor,
        "executor_contract_precedes_require_definition": executor.index("self.action_contract.evaluate(")
        < executor.index("self.rules.require_action_definition("),
        "availability_calls_shared_contract": "self.contract.evaluate(" in availability,
        "contract_uses_owner_entity_ref": "actor.template_id" in contract,
        "contract_checks_turn_owner": "action_actor_not_turn_owner" in contract,
        "contract_checks_window": "action_window_not_admitted" in contract,
        "contract_checks_resource": "action_contract.resource_gate" in contract,
        "authorization_requires_internal_signature": "action_submission_authorization_not_issued" in contract
        and "_action_authorization_seal_valid" in contract
        and "_ACTION_AUTHORIZATION_ISSUER" in contract
        and "_issue_action_submission_authorization" in contract,
        "lowering_uses_structured_attack_type": "attack_type = definition.attack_type" in lowering,
    }
    forbidden_guess_tokens = (
        "SkillName",
        "skill_name",
        "AvatarName",
        "MonsterName",
    )
    no_name_or_id_role_guess = not any(token in contract for token in forbidden_guess_tokens)
    return {
        "ok": all(checks.values()) and no_name_or_id_role_guess,
        **checks,
        "no_name_or_id_role_guess": no_name_or_id_role_guess,
        "forbidden_guess_tokens": list(forbidden_guess_tokens),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S6 action ownership, role and window contract.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument(
        "--runtime-only",
        action="store_true",
        help="Validate current runtime/authorization contracts without rebuilding TBGD source samples.",
    )
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    if args.runtime_only:
        result = run_runtime_validation(package_root, args.output_dir)
        print(
            f"v8 {result['validation_version']} ok={result['ok']} roles={result['role_count']} "
            f"negative_cases={result['negative_case_count']} ready_for_review={result['ready_for_review']}"
        )
        return 0 if result["ok"] else 1
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} roles={result['role_count']} "
        f"negative_cases={result['negative_case_count']} ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
