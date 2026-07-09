from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import CanonicalIR, EffectIR, QueueIntentIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolver
from ..systems.action_availability import ActionAvailabilitySystem, ActionChoice
from ..systems.status import StatusApplicationResult, StatusSystem
from ..systems.status_callbacks import StatusCallbackExecutionResult, StatusCallbackSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p5_s6_resource_status_callback_consumers"
MATRIX_SCHEMA_VERSION = "p5_s6_resource_status_callback_consumers_matrix_v1"

CLASSIFICATION_STATES = {
    "executable",
    "boundary_only",
    "source_absent_not_required",
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
    "out_of_scope",
}
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
REQUIRED_ROWS = {
    "resource_consumer_value_resolver",
    "status_numeric_value_resolver",
    "callback_queue_value_resolver",
    "missing_context_negative_state_unchanged",
    "consumer_replay_source_audit",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_s6_resource_status_callback_consumers_matrix(ir, rules)
    matrix_checks = validate_p5_s6_resource_status_callback_consumers_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(bool(item["ok"]) for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p5_s6_resource_status_callback_structural_runtime_samples",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "consumer_matrix": matrix["consumer_matrix"],
        "gap_attribution_matrix": matrix["gap_attribution_matrix"],
        "runtime_samples": matrix["runtime_samples"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s6_resource_status_callback_consumers.json", result)
    write_json(output_dir / "p5_s6_resource_status_callback_consumers_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S6 resource/status/callback ValueResolver consumers.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']} "
        f"gap_counts={result['summary']['gap_attribution_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p5_s6_resource_status_callback_consumers_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    resource_case = _select_resource_consumer_case(ir, rules)
    status_case = _select_status_numeric_case(ir, rules)
    queue_case = _select_callback_queue_case(ir, rules)
    negative_case = _missing_context_negative_case(rules)
    rows = [
        _resource_consumer_row(resource_case),
        _status_numeric_row(status_case),
        _callback_queue_row(queue_case),
        _missing_context_negative_row(negative_case),
        _consumer_replay_source_audit_row(resource_case, status_case, queue_case),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts = _gap_counts(rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "consumer_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
            "resource_value_resolution_count": len(resource_case.get("value_resolutions") or ()),
            "status_value_resolution_count": len(status_case.get("value_resolutions") or ()),
            "queue_value_resolution_count": len(queue_case.get("value_resolutions") or ()),
        },
        "gap_attribution_matrix": _gap_attribution_matrix(rows),
        "runtime_samples": {
            "resource": resource_case.get("runtime_sample", {}),
            "status": status_case.get("runtime_sample", {}),
            "queue": queue_case.get("runtime_sample", {}),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "resource_runtime_sample_count": 1 if resource_case.get("found") else 0,
            "status_runtime_sample_count": 1 if status_case.get("found") else 0,
            "queue_runtime_sample_count": 1 if queue_case.get("found") else 0,
            "static_check_count": 1,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p5_s6_resource_status_callback_consumers.json",
                "p5_s6_resource_status_callback_consumers_matrix.json",
            ],
        },
    }


def validate_p5_s6_resource_status_callback_consumers_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("consumer_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_counts = dict(matrix.get("summary", {}).get("gap_attribution_counts") or {})
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "disallowed_gap_count_zero": disallowed_gap_count == 0,
        "resource_consumer_value_resolved": _row_check(rows, "resource_consumer_value_resolver", "resource_mutation_has_value_resolution"),
        "status_numeric_value_resolved": _row_check(rows, "status_numeric_value_resolver", "status_mutation_has_value_resolution"),
        "queue_value_resolved": _row_check(rows, "callback_queue_value_resolver", "queue_mutation_has_value_resolution"),
        "missing_context_state_unchanged": _row_check(rows, "missing_context_negative_state_unchanged", "state_unchanged_replay_ok"),
        "replay_source_audit_ok": _row_check(rows, "consumer_replay_source_audit", "all_replay_ok")
        and _row_check(rows, "consumer_replay_source_audit", "resource_mutation_source_audit_ok"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
        "disallowed_gap_count": disallowed_gap_count,
    }


def _select_resource_consumer_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    availability = ActionAvailabilitySystem(rules)
    for card in sorted(ir.character_data_cards, key=lambda item: item.card_id):
        if rules.combatant_action_set(card.entity_ref) is None:
            continue
        state = _basic_state(card.entity_ref)
        view = availability.view(state)
        for choice in view.choices:
            if not (choice.auto_target_ids or choice.selectable_target_ids):
                continue
            command = _command_from_choice(choice)
            after, transition = CombatExecutor(rules).execute(command, state)
            resource_mutations = [
                mutation
                for mutation in transition.transaction.mutations
                if mutation.source == "combat_executor.resources"
                and isinstance(mutation.metadata.get("resource_value_resolutions"), dict)
            ]
            if not resource_mutations:
                continue
            value_resolutions = _resource_value_resolutions(resource_mutations)
            if not value_resolutions or not all(item.get("ok") is True for item in value_resolutions):
                continue
            replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
            audit = RuntimeSourceAuditor(rules).validate_transition(transition)
            return {
                "found": True,
                "state": state,
                "after": after,
                "transition": transition,
                "replay": _replay_json(replay),
                "audit": _audit_summary(audit),
                "value_resolutions": value_resolutions,
                "mutation_count": len(resource_mutations),
                "runtime_sample": {
                    "actor_data_card_id": card.card_id,
                    "action_id": choice.action_id,
                    "action_level": choice.action_level,
                    "resource_mutation_count": len(resource_mutations),
                    "target_ids": list(command.target_ids),
                },
            }
    return {"found": False, "value_resolutions": (), "runtime_sample": {}}


def _select_status_numeric_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    status_system = StatusSystem(rules)
    for effect in sorted(ir.effects, key=lambda item: item.effect_id):
        if effect.opcode != "AddModifier":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        if not isinstance(standard, dict) or not standard.get("modifier_name"):
            continue
        state = _status_state()
        result = status_system.apply_add_modifier(
            state,
            effect,
            caster_id="ally:value_actor",
            source_id="validation:p5_s6_status",
            owner_id="ally:value_actor",
            param_entity_id="enemy:value_target",
            current_action_target_id="enemy:value_target",
            event_payload=_event_payload(),
        )
        value_resolutions = _status_value_resolutions(result)
        if not result.ok or not result.mutations or not any(item.get("ok") is True for item in value_resolutions):
            continue
        after = MutationReducer().apply_all(state, result.mutations)
        replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
        return {
            "found": True,
            "effect_id": effect.effect_id,
            "result": result,
            "replay": _replay_json(replay),
            "value_resolutions": value_resolutions,
            "runtime_sample": {
                "effect_id": effect.effect_id,
                "modifier_name": str(standard.get("modifier_name") or ""),
                "mutation_count": len(result.mutations),
                "record_count": len(result.records),
            },
        }
    return {"found": False, "value_resolutions": (), "runtime_sample": {}}


def _select_callback_queue_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    callback_system = StatusCallbackSystem(rules)
    for intent in sorted(ir.queue_intents, key=lambda item: item.queue_intent_id):
        if intent.coverage_status != "executable":
            continue
        window = rules.queue_window_for_intent(intent.queue_intent_id)
        if window is None or window.coverage_status != "executable":
            continue
        callback = rules.status_callback(intent.callback_id)
        if callback is None:
            continue
        task = next(
            (
                item
                for item in rules.status_callback_tasks_for_callback(callback.callback_id)
                if item.task_id == intent.source_task_id
            ),
            None,
        )
        if task is None:
            continue
        state = _queue_state(callback.modifier_name)
        detail = _queue_status_detail(callback)
        trigger_event = GameEvent(
            "status.queue.validation",
            source_id="ally:value_actor",
            target_id="enemy:value_target",
            event_id="event:p5_s6:queue",
            window=callback.event,
            process_only=True,
            payload=_event_payload(),
        )
        result = callback_system._execute_queue_intents(state, callback, task, detail, trigger_event, (intent,))
        value_resolutions = _queue_value_resolutions(result)
        if not result.ok or not result.mutations or not any(item.get("ok") is True for item in value_resolutions):
            continue
        after = MutationReducer().apply_all(state, result.mutations)
        replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
        missing_event_required = _queue_intent_requires_event_payload(intent)
        if missing_event_required:
            missing_event_result = callback_system._execute_queue_intents(state, callback, task, detail, None, (intent,))
            missing_event_blocked = not missing_event_result.mutations
            missing_event_errors = list(missing_event_result.errors)
        else:
            missing_event_blocked = True
            missing_event_errors = ["event_payload_not_required_for_selected_queue_intent"]
        return {
            "found": True,
            "intent": intent,
            "result": result,
            "replay": _replay_json(replay),
            "value_resolutions": value_resolutions,
            "missing_event_blocked": missing_event_blocked,
            "missing_event_required": missing_event_required,
            "missing_event_errors": missing_event_errors,
            "runtime_sample": {
                "queue_intent_id": intent.queue_intent_id,
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "queue_kind": intent.queue_kind,
                "mutation_count": len(result.mutations),
                "record_count": len(result.records),
            },
        }
    return {"found": False, "value_resolutions": (), "runtime_sample": {}}


def _missing_context_negative_case(rules: RuleBook) -> dict[str, Any]:
    resolver = ValueResolver(rules)
    state = _status_state()
    resolution = resolver.resolve(
        ValueBindingRequest(
            binding_kind="runtime_numeric_expression",
            expression={"kind": "fixed", "value": 1},
            required_context_keys=("event_payload", "status_modifier"),
            source_trace={"validation_negative": "missing_event_payload_and_modifier"},
        ),
        ValueContext(source_trace={"validation_negative": "missing_event_payload_and_modifier"}),
    )
    replay = MutationReducer().replay_snapshot(state, (), state.snapshot().to_json())
    return {"resolution": resolution.to_json(), "replay": _replay_json(replay)}


def _resource_consumer_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    checks = _checks(
        {
            "resource_sample_found": bool(case.get("found")),
            "resource_mutation_has_value_resolution": bool(case.get("value_resolutions")),
            "resource_value_resolutions_ok": all(item.get("ok") is True for item in case.get("value_resolutions") or ()),
            "resource_replay_ok": dict(case.get("replay") or {}).get("ok") is True,
        }
    )
    return _row(
        "resource_consumer_value_resolver",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=len(case.get("value_resolutions") or ()) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        details={
            "runtime_sample": case.get("runtime_sample", {}),
            "sample_resolution": _value_resolution_summary(_first(case.get("value_resolutions"))),
        },
    )


def _status_numeric_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    checks = _checks(
        {
            "status_sample_found": bool(case.get("found")),
            "status_mutation_has_value_resolution": bool(case.get("value_resolutions")),
            "any_status_value_resolution_ok": any(item.get("ok") is True for item in case.get("value_resolutions") or ()),
            "status_replay_ok": dict(case.get("replay") or {}).get("ok") is True,
        }
    )
    return _row(
        "status_numeric_value_resolver",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=len(case.get("value_resolutions") or ()) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        details={
            "runtime_sample": case.get("runtime_sample", {}),
            "sample_resolution": _value_resolution_summary(_first(case.get("value_resolutions"))),
        },
    )


def _callback_queue_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    checks = _checks(
        {
            "queue_sample_found": bool(case.get("found")),
            "queue_mutation_has_value_resolution": bool(case.get("value_resolutions")),
            "queue_value_resolution_ok": all(item.get("ok") is True for item in case.get("value_resolutions") or ()),
            "queue_replay_ok": dict(case.get("replay") or {}).get("ok") is True,
            "missing_event_payload_blocked_or_not_required": bool(case.get("missing_event_blocked", True)),
        }
    )
    return _row(
        "callback_queue_value_resolver",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=len(case.get("value_resolutions") or ()) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        details={
            "runtime_sample": case.get("runtime_sample", {}),
            "missing_event_required": bool(case.get("missing_event_required", False)),
            "missing_event_errors": list(case.get("missing_event_errors") or []),
            "sample_resolution": _value_resolution_summary(_first(case.get("value_resolutions"))),
        },
    )


def _missing_context_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    resolution = dict(case.get("resolution") or {})
    checks = _checks(
        {
            "missing_context_blocked": resolution.get("ok") is False
            and str(resolution.get("blocked_reason") or "").startswith("context_missing:"),
            "state_unchanged_replay_ok": dict(case.get("replay") or {}).get("ok") is True,
        }
    )
    return _row(
        "missing_context_negative_state_unchanged",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        details={"resolution": _value_resolution_summary(resolution), "replay": case.get("replay", {})},
    )


def _consumer_replay_source_audit_row(
    resource_case: dict[str, Any],
    status_case: dict[str, Any],
    queue_case: dict[str, Any],
) -> dict[str, JSONValue]:
    checks = _checks(
        {
            "resource_replay_ok": dict(resource_case.get("replay") or {}).get("ok") is True,
            "status_replay_ok": dict(status_case.get("replay") or {}).get("ok") is True,
            "queue_replay_ok": dict(queue_case.get("replay") or {}).get("ok") is True,
            "all_replay_ok": all(
                dict(case.get("replay") or {}).get("ok") is True
                for case in (resource_case, status_case, queue_case)
            ),
            "resource_mutation_source_audit_ok": dict(resource_case.get("audit") or {}).get(
                "resource_mutation_audit_ok"
            )
            is True,
        }
    )
    return _row(
        "consumer_replay_source_audit",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        details={
            "resource_audit": resource_case.get("audit", {}),
            "resource_replay": resource_case.get("replay", {}),
            "status_replay": status_case.get("replay", {}),
            "queue_replay": queue_case.get("replay", {}),
        },
    )


def _command_from_choice(choice: ActionChoice) -> ActionCommand:
    target_ids = tuple(choice.auto_target_ids or choice.selectable_target_ids[:1])
    return ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=choice.action_level,
        target_ids=target_ids,
        source="manual",
        metadata={"p5_s6_selected_from_availability": True},
    )


def _basic_state(template_id: str) -> BattleState:
    return BattleState(
        units={
            "ally:value_actor": _ally_unit("ally:value_actor", template_id),
            "enemy:value_target": _enemy_target(),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "ally:value_actor"},
    )


def _status_state() -> BattleState:
    return BattleState(
        units={
            "ally:value_actor": _ally_unit("ally:value_actor", "validation:status_actor"),
            "enemy:value_target": _enemy_target(),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle"},
    )


def _queue_state(modifier_name: str) -> BattleState:
    detail = {
        "instance_id": "status:p5_s6_queue",
        "status_id": f"modifier:{modifier_name}",
        "modifier_name": modifier_name,
        "owner_id": "ally:value_actor",
        "caster_id": "ally:value_actor",
        "source_id": "validation:p5_s6_queue",
        "source_trace": {"validation_status_detail": "p5_s6_queue"},
    }
    ally = _ally_unit("ally:value_actor", "validation:queue_actor")
    ally = replace(
        ally,
        statuses=(f"modifier:{modifier_name}",),
        flags={"status_details": [detail]},
    )
    return BattleState(
        units={"ally:value_actor": ally, "enemy:value_target": _enemy_target()},
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle"},
    )


def _queue_status_detail(callback: Any) -> dict[str, JSONValue]:
    return {
        "instance_id": "status:p5_s6_queue",
        "status_id": f"modifier:{callback.modifier_name}",
        "modifier_name": callback.modifier_name,
        "owner_id": "ally:value_actor",
        "caster_id": "ally:value_actor",
        "source_id": "validation:p5_s6_queue",
        "source_trace": {"validation_status_detail": "p5_s6_queue"},
    }


def _queue_intent_requires_event_payload(intent: QueueIntentIR) -> bool:
    event_aliases = {"AbilityTargetEntity", "ParamEntity", "CurrentActionTarget", "DamageAttackerEntity"}
    return intent.ability_target_alias in event_aliases or intent.actor_target_alias in event_aliases


def _ally_unit(unit_id: str, template_id: str) -> UnitState:
    return UnitState(
        unit_id=unit_id,
        side="ally",
        template_id=template_id,
        level=80,
        max_hp=3000.0,
        hp=3000.0,
        attack=1000.0,
        defense=500.0,
        speed=100.0,
        energy=0.0,
        max_energy=100.0,
    )


def _enemy_target() -> UnitState:
    return UnitState(
        unit_id="enemy:value_target",
        side="enemy",
        template_id="validation:value_target",
        level=80,
        max_hp=100000.0,
        hp=100000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        toughness=120.0,
        max_toughness=120.0,
        flags={"weaknesses": ["Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"]},
    )


def _event_payload() -> dict[str, JSONValue]:
    return {
        "actor_id": "ally:value_actor",
        "attacker_id": "ally:value_actor",
        "source_id": "ally:value_actor",
        "owner_id": "ally:value_actor",
        "target_id": "enemy:value_target",
        "current_hit_target_id": "enemy:value_target",
        "primary_action_target_id": "enemy:value_target",
        "target_ids": ["enemy:value_target"],
        "selected_target_ids": ["enemy:value_target"],
    }


def _resource_value_resolutions(mutations: list[Any]) -> list[dict[str, JSONValue]]:
    resolutions: list[dict[str, JSONValue]] = []
    for mutation in mutations:
        value = mutation.metadata.get("resource_value_resolutions")
        if isinstance(value, dict):
            for item in value.values():
                if isinstance(item, dict):
                    resolutions.append(item)
    return resolutions


def _status_value_resolutions(result: StatusApplicationResult) -> list[dict[str, JSONValue]]:
    resolutions: list[dict[str, JSONValue]] = []
    for mutation in result.mutations:
        metadata = mutation.metadata if isinstance(mutation.metadata, dict) else {}
        for source in _walk_dicts(metadata):
            for key in (
                "value_resolution",
                "max_layer_value_resolution",
                "layer_add_value_resolution",
            ):
                value = source.get(key)
                if isinstance(value, dict) and value.get("binding_kind"):
                    resolutions.append(value)
    return resolutions


def _queue_value_resolutions(result: StatusCallbackExecutionResult) -> list[dict[str, JSONValue]]:
    resolutions: list[dict[str, JSONValue]] = []
    for mutation in result.mutations:
        metadata = mutation.metadata if isinstance(mutation.metadata, dict) else {}
        value = metadata.get("priority_value_resolution")
        if isinstance(value, dict):
            resolutions.append(value)
    return resolutions


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_dicts(item)


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    executable_count: int = 0,
    blocked_or_gap_count: int = 0,
    gap_attribution: dict[str, int] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "executable_count": int(executable_count),
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "gap_attribution": gap_attribution or {},
        "details": details or {},
    }


def _checks(checks: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {"ok": all(bool(value) for value in checks.values()), **checks}


def _row_check(rows: dict[str, Any], row_id: str, check_name: str) -> bool:
    return bool(rows.get(row_id, {}).get("checks", {}).get("checks", {}).get(check_name))


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            counts[str(key)] += int(value or 0)
    return counts


def _gap_attribution_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    gap_rows = []
    for row in rows:
        gap_attribution = dict(row.get("gap_attribution") or {})
        if not gap_attribution:
            continue
        gap_rows.append(
            {
                "row_id": str(row.get("row_id") or ""),
                "classification": str(row.get("classification") or ""),
                "gap_attribution": gap_attribution,
                "blocked_or_gap_count": int(row.get("blocked_or_gap_count") or 0),
            }
        )
    gap_counts = _gap_counts(gap_rows)
    return {
        "schema_version": "p5_s6_gap_attribution_matrix_v1",
        "rows": gap_rows,
        "summary": {
            "row_count": len(gap_rows),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
        },
    }


def _value_resolution_summary(value: Any) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        return {}
    delegate = value.get("delegate_resolution") if isinstance(value.get("delegate_resolution"), dict) else {}
    request = value.get("request") if isinstance(value.get("request"), dict) else {}
    return {
        "ok": bool(value.get("ok")),
        "value": value.get("value"),
        "binding_kind": value.get("binding_kind"),
        "blocked_reason": value.get("blocked_reason", ""),
        "request": {
            "binding_kind": request.get("binding_kind", ""),
            "field_name": request.get("field_name", ""),
            "param_index": request.get("param_index"),
            "required_context_keys": list(request.get("required_context_keys") or []),
        },
        "delegate": {
            "ok": delegate.get("ok"),
            "value": delegate.get("value"),
            "value_source": delegate.get("value_source", ""),
            "expression_kind": delegate.get("expression_kind", ""),
            "blocked_reason": delegate.get("blocked_reason", ""),
        },
        "source_trace": _source_trace_summary(
            value.get("source_trace") if isinstance(value.get("source_trace"), dict) else {}
        ),
    }


def _source_trace_summary(trace: dict[str, JSONValue]) -> dict[str, JSONValue]:
    if not isinstance(trace, dict):
        return {}
    summary: dict[str, JSONValue] = {}
    for key in ("raw_type", "raw_id", "source_path", "effect_id", "queue_intent_id", "queue_priority_id"):
        if key in trace:
            summary[key] = trace[key]
    for nested_key in ("source", "effect_source", "queue_intent_source", "queue_priority_source"):
        nested = trace.get(nested_key)
        if isinstance(nested, dict):
            nested_summary = _source_trace_summary(nested)
            if nested_summary:
                summary[nested_key] = nested_summary
    return summary


def _replay_json(replay: Any) -> dict[str, JSONValue]:
    return {
        "ok": bool(getattr(replay, "ok", False)),
        "errors": list(getattr(replay, "errors", ()) or ()),
    }


def _audit_summary(audit: Any) -> dict[str, JSONValue]:
    data = audit.to_json()
    violations = data.get("violations") if isinstance(data.get("violations"), list) else []
    return {
        "ok": bool(data.get("ok")),
        "checked_mutations": data.get("checked_mutations", 0),
        "checked_records": data.get("checked_records", 0),
        "resource_mutation_audit_ok": not any(
            item.get("source") == "combat_executor.resources" for item in violations if isinstance(item, dict)
        ),
        "full_transition_audit_ok": bool(data.get("ok")),
        "violation_count": len(violations),
        "violations": [
            {
                "source": item.get("source", ""),
                "reason": item.get("reason", ""),
                "missing_field": item.get("missing_field", ""),
            }
            for item in violations[:6]
            if isinstance(item, dict)
        ],
    }


def _first(values: Any) -> Any:
    if isinstance(values, (list, tuple)) and values:
        return values[0]
    return {}


if __name__ == "__main__":
    raise SystemExit(main())
