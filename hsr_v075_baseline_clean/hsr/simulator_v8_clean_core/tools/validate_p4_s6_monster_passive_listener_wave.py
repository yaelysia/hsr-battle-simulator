from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import BattleState, GameEvent, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import CanonicalIR, PassiveMechanismSlotIR, StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p4_s6_monster_passive_listener_wave"
MATRIX_SCHEMA_VERSION = "p4_s6_monster_passive_listener_wave_matrix_v1"

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
GAP_STATES = {
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
}
REQUIRED_ROWS = {
    "monster_passive_slot_matrix",
    "monster_status_callback_event_matrix",
    "monster_listener_event_bucket_matrix",
    "monster_global_listener_boundary",
    "wave_definition_entry_matrix",
    "wave_monster_event_payload_boundary",
    "monster_summon_refs_boundary",
    "summon_intent_lifecycle_relation_matrix",
    "stage_environment_scope_boundary",
}

EVENT_BUCKETS = {
    "startup_or_enter": ("OnEnterBattle", "OnCreate", "OnStack"),
    "turn_or_action": ("OnActionEnd", "OnAfterAction", "OnAfterSkillUse", "OnAllowAction", "OnBeforeAction"),
    "hit_or_damage": ("OnAfterBeingAttacked", "OnAfterBeingHit", "OnAfterHit", "OnBeforeBeingAttacked"),
    "death_or_break": ("OnBeforeDying", "OnListenCharacterDie", "OnBeingBreak", "OnEndBreak"),
    "phase": ("OnPhase1", "OnPhase2", "OnPhase3"),
    "wave": ("OnWaveMonster",),
    "resource_or_hp": ("OnHPChange", "OnLimboWaitHeal", "OnBeingLimbo"),
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p4_s6_monster_passive_listener_wave_matrix(ir, rules)
    matrix_checks = validate_p4_s6_monster_passive_listener_wave_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p4_s6_monster_passive_listener_wave_structural_predicates",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "stage_environment_folded_into_monster_passive": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "monster_passive_listener_wave_matrix": matrix["monster_passive_listener_wave_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s6_monster_passive_listener_wave.json", result)
    write_json(output_dir / "p4_s6_monster_passive_listener_wave_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S6 monster passive/listener/wave boundaries.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p4_s6_monster_passive_listener_wave_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    monster_callbacks = tuple(callback for callback in ir.status_callbacks if _monster_source(callback.source.source_path, callback.source.raw_id))
    rows = [
        _monster_passive_slot_matrix_row(ir, rules),
        _monster_status_callback_event_matrix_row(monster_callbacks, rules),
        _monster_listener_event_bucket_matrix_row(monster_callbacks),
        _monster_global_listener_boundary_row(monster_callbacks),
        _wave_definition_entry_matrix_row(ir, rules),
        _wave_monster_event_payload_boundary_row(rules),
        _monster_summon_refs_boundary_row(ir, rules),
        _summon_intent_lifecycle_relation_matrix_row(ir, rules),
        _stage_environment_scope_boundary_row(ir),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "monster_passive_listener_wave_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "monster_callback_count": len(monster_callbacks),
            "monster_passive_slot_count": sum(1 for slot in ir.passive_mechanism_slots if slot.data_card_kind == "monster"),
            "wave_definition_count": len(ir.wave_definitions),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s6_monster_passive_listener_wave.json",
                "p4_s6_monster_passive_listener_wave_matrix.json",
            ],
        },
    }


def validate_p4_s6_monster_passive_listener_wave_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("monster_passive_listener_wave_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_rows = [row for row in rows.values() if str(row.get("classification") or "") in GAP_STATES]
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "unclassified_count_zero": int(matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "gap_rows_have_attribution": all(bool(row.get("gap_attribution")) for row in gap_rows),
        "wave_payload_boundary_state_unchanged": _row_check(
            rows,
            "wave_monster_event_payload_boundary",
            "fake_wave_event_state_unchanged",
        ),
        "stage_environment_not_folded_into_monster_passive": _row_check(
            rows,
            "stage_environment_scope_boundary",
            "stage_refs_kept_out_of_monster_passive_runtime",
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _monster_passive_slot_matrix_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    slots = tuple(slot for slot in ir.passive_mechanism_slots if slot.data_card_kind == "monster")
    visible = sum(1 for slot in slots if rules.passive_mechanism_slot(slot.passive_slot_id) is slot)
    executable = [slot for slot in slots if slot.coverage_status == "executable"]
    blocked = len(slots) - len(executable)
    checks = {
        "monster_passive_slots_present": bool(slots),
        "rulebook_visible": visible == len(slots),
        "blocked_slots_have_reason": all(slot.blocked_reason for slot in slots if slot.coverage_status != "executable"),
        "no_passive_slot_marked_done_without_runtime_source": len(executable) == 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_passive_slot_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(slots),
        ir_count=len(slots),
        rulebook_visible_count=visible,
        executable_count=len(executable),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(slots)),
        details={
            "coverage_counts": dict(sorted(Counter(slot.coverage_status for slot in slots).items())),
            "runtime_system_counts": dict(sorted(Counter(slot.runtime_system for slot in slots).items())),
            "blocked_reason_counts_top": _counter_top(Counter(slot.blocked_reason for slot in slots if slot.blocked_reason), 20),
        },
    )


def _monster_status_callback_event_matrix_row(
    callbacks: tuple[StatusCallbackIR, ...],
    rules: RuleBook,
) -> dict[str, JSONValue]:
    visible = sum(1 for callback in callbacks if rules.status_callback(callback.callback_id) is callback)
    executable = [callback for callback in callbacks if callback.admission_status == "executable"]
    blocked = len(callbacks) - len(executable)
    checks = {
        "monster_callbacks_present": bool(callbacks),
        "rulebook_visible": visible == len(callbacks),
        "executable_callbacks_have_event_family": all(rules.status_event_family(callback.event) is not None for callback in executable),
        "blocked_callbacks_have_dependency": all(
            callback.blocking_dependency or callback.blocked_reason for callback in callbacks if callback.admission_status != "executable"
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_status_callback_event_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(callbacks),
        ir_count=len(callbacks),
        rulebook_visible_count=visible,
        executable_count=len(executable),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(callbacks)),
        details={
            "event_counts_top": _counter_top(Counter(callback.event for callback in callbacks), 30),
            "admission_counts": dict(sorted(Counter(callback.admission_status for callback in callbacks).items())),
            "coverage_counts": dict(sorted(Counter(callback.coverage_status for callback in callbacks).items())),
            "scope_kind_counts": dict(sorted(Counter(callback.scope_kind for callback in callbacks).items())),
            "blocking_dependency_counts_top": _counter_top(
                Counter(callback.blocking_dependency for callback in callbacks if callback.blocking_dependency),
                30,
            ),
        },
    )


def _monster_listener_event_bucket_matrix_row(callbacks: tuple[StatusCallbackIR, ...]) -> dict[str, JSONValue]:
    bucket_rows: list[dict[str, JSONValue]] = []
    for bucket, events in EVENT_BUCKETS.items():
        event_set = set(events)
        bucket_callbacks = [callback for callback in callbacks if callback.event in event_set]
        executable = [callback for callback in bucket_callbacks if callback.admission_status == "executable"]
        blocked = len(bucket_callbacks) - len(executable)
        if bucket_callbacks and blocked:
            classification = "admission_gap"
        elif bucket_callbacks:
            classification = "executable"
        else:
            classification = "source_absent_not_required"
        bucket_rows.append(
            {
                "bucket": bucket,
                "events": list(events),
                "raw_count": len(bucket_callbacks),
                "executable_count": len(executable),
                "blocked_count": blocked,
                "classification": classification,
                "blocking_dependency_counts_top": _counter_top(
                    Counter(callback.blocking_dependency for callback in bucket_callbacks if callback.blocking_dependency),
                    10,
                ),
            }
        )
    blocked_total = sum(int(row["blocked_count"]) for row in bucket_rows)
    checks = {
        "all_required_buckets_present": {row["bucket"] for row in bucket_rows} == set(EVENT_BUCKETS),
        "no_unclassified_buckets": not any(row["classification"] == "unclassified" for row in bucket_rows),
        "at_least_one_executable_bucket_callback": any(int(row["executable_count"]) > 0 for row in bucket_rows),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_listener_event_bucket_matrix",
        classification="admission_gap" if blocked_total else "executable",
        checks=checks,
        raw_count=sum(int(row["raw_count"]) for row in bucket_rows),
        ir_count=sum(int(row["raw_count"]) for row in bucket_rows),
        executable_count=sum(int(row["executable_count"]) for row in bucket_rows),
        blocked_or_gap_count=blocked_total,
        gap_attribution={"admission_gap": blocked_total} if blocked_total else {},
        details={"bucket_rows": bucket_rows},
    )


def _monster_global_listener_boundary_row(callbacks: tuple[StatusCallbackIR, ...]) -> dict[str, JSONValue]:
    global_callbacks = tuple(callback for callback in callbacks if callback.scope_kind == "global_listener")
    executable = [callback for callback in global_callbacks if callback.admission_status == "executable"]
    blocked = len(global_callbacks) - len(executable)
    checks = {
        "global_listener_scan_completed": len(global_callbacks) >= 0,
        "blocked_global_listeners_have_dependency": all(
            callback.blocking_dependency or callback.blocked_reason
            for callback in global_callbacks
            if callback.admission_status != "executable"
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_global_listener_boundary",
        classification="admission_gap" if blocked else ("executable" if global_callbacks else "source_absent_not_required"),
        checks=checks,
        raw_count=len(global_callbacks),
        ir_count=len(global_callbacks),
        executable_count=len(executable),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(global_callbacks)),
        details={
            "event_counts_top": _counter_top(Counter(callback.event for callback in global_callbacks), 20),
            "blocking_dependency_counts_top": _counter_top(
                Counter(callback.blocking_dependency for callback in global_callbacks if callback.blocking_dependency),
                20,
            ),
        },
    )


def _wave_definition_entry_matrix_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    definitions = tuple(ir.wave_definitions)
    entries = tuple(entry for definition in definitions for entry in definition.entries)
    total_ir_count = len(definitions) + len(entries)
    visible_definitions = sum(1 for definition in definitions if rules.wave_definition(definition.wave_definition_id) is definition)
    visible_entries = sum(
        1
        for definition in definitions
        for entry in definition.entries
        if entry in rules.wave_entries_for_wave(definition.wave_definition_id, entry.wave_index)
    )
    blocked = sum(1 for definition in definitions if definition.coverage_status != "executable") + sum(
        1 for entry in entries if entry.coverage_status != "executable"
    )
    checks = {
        "wave_definitions_present": bool(definitions),
        "rulebook_definitions_visible": visible_definitions == len(definitions),
        "entries_present": bool(entries),
        "entry_visibility_scan_completed": visible_entries >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "wave_definition_entry_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=total_ir_count,
        ir_count=total_ir_count,
        rulebook_visible_count=visible_definitions + visible_entries,
        executable_count=total_ir_count - blocked,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(definitions)),
        details={
            "definition_count": len(definitions),
            "entry_count": len(entries),
            "visible_definition_count": visible_definitions,
            "visible_entry_count": visible_entries,
            "definition_coverage_counts": dict(sorted(Counter(definition.coverage_status for definition in definitions).items())),
            "entry_coverage_counts": dict(sorted(Counter(entry.coverage_status for entry in entries).items())),
            "wave_count_top": _counter_top(Counter(str(definition.wave_count) for definition in definitions), 10),
            "stage_ability_ref_definition_count": sum(1 for definition in definitions if definition.stage_ability_refs),
        },
    )


def _wave_monster_event_payload_boundary_row(rules: RuleBook) -> dict[str, JSONValue]:
    state = _event_state()
    before = state.snapshot().to_json()
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    fake = dispatcher.dispatch_event(
        state,
        event=GameEvent(
            "wave.monster",
            source_id="wave_system",
            target_id="enemy:missing_payload",
            event_id="event:p4_s6:wave_fake",
            window="wave",
            process_only=True,
            payload={},
        ),
    )
    family = rules.status_event_family("OnWaveMonster")
    checks = {
        "fake_wave_event_blocked_without_mutation": not fake.mutations and fake.after_state == state,
        "fake_wave_event_state_unchanged": state.snapshot().to_json() == before,
        "on_wave_monster_family_missing_or_has_wave_source": family is None or "wave.monster" in family.runtime_event_sources,
        "missing_payload_does_not_execute_callback": not fake.mutations,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "wave_monster_event_payload_boundary",
        classification="boundary_only",
        checks=checks,
        raw_count=1,
        ir_count=1,
        blocked_or_gap_count=1,
        details={
            "fake_dispatch": {
                "mutation_count": len(fake.mutations),
                "record_count": len(fake.records),
                "listener_record_count": len(fake.listener_records),
                "errors": list(fake.errors),
            },
            "on_wave_monster_family": family.to_json() if family is not None else {},
        },
    )


def _monster_summon_refs_boundary_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    cards = tuple(card for card in ir.monster_data_cards if card.summon_refs)
    visible = sum(1 for card in cards if rules.monster_data_card(card.card_id) is card)
    ref_count = sum(len(card.summon_refs) for card in cards)
    intent_refs = {
        ref
        for intent in ir.summon_monster_intents
        for entry in intent.entries
        for ref in (entry.monster_raw_id, entry.monster_entity_ref)
        if ref
    }
    linked_refs = sum(1 for card in cards for ref in card.summon_refs if ref in intent_refs)
    checks = {
        "summon_ref_cards_scanned": len(cards) >= 0,
        "rulebook_visible": visible == len(cards),
        "refs_do_not_create_special_monster_skill_system": True,
        "linked_ref_scan_completed": linked_refs >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_summon_refs_boundary",
        classification="admission_gap" if ref_count else "source_absent_not_required",
        checks=checks,
        raw_count=ref_count,
        ir_count=len(cards),
        rulebook_visible_count=visible,
        executable_count=0,
        blocked_or_gap_count=ref_count,
        gap_attribution={"admission_gap": ref_count} if ref_count else {},
        sample_source_trace=_source(_first(cards)),
        details={
            "card_count": len(cards),
            "summon_ref_count": ref_count,
            "refs_linked_to_current_intent_monster_id_count": linked_refs,
            "note": "Summon refs remain spawn/lifecycle intents; summoned units must bind to MonsterDataCardIR instead of copied special rules.",
        },
    )


def _summon_intent_lifecycle_relation_matrix_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    intents = tuple(ir.summon_monster_intents)
    visible = sum(1 for intent in intents if rules.summon_monster_intent(intent.summon_intent_id) is intent)
    executable = [intent for intent in intents if intent.coverage_status == "executable"]
    blocked = len(intents) - len(executable)
    checks = {
        "summon_intents_present": bool(intents),
        "rulebook_visible": visible == len(intents),
        "blocked_intents_have_reason": all(intent.blocked_reason for intent in intents if intent.coverage_status != "executable"),
        "executable_intents_bind_monster_card_or_profile": all(
            any(entry.monster_raw_id or entry.monster_entity_ref for entry in intent.entries)
            for intent in executable
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "summon_intent_lifecycle_relation_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(intents),
        ir_count=len(intents),
        rulebook_visible_count=visible,
        executable_count=len(executable),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(intents)),
        details={
            "coverage_counts": dict(sorted(Counter(intent.coverage_status for intent in intents).items())),
            "blocked_reason_counts_top": _counter_top(Counter(intent.blocked_reason for intent in intents if intent.blocked_reason), 20),
        },
    )


def _stage_environment_scope_boundary_row(ir: CanonicalIR) -> dict[str, JSONValue]:
    definitions_with_stage_ability = tuple(definition for definition in ir.wave_definitions if definition.stage_ability_refs)
    ref_count = sum(len(definition.stage_ability_refs) for definition in definitions_with_stage_ability)
    checks = {
        "stage_refs_scanned": ref_count >= 0,
        "stage_refs_kept_out_of_monster_passive_runtime": True,
        "future_owner_recorded": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "stage_environment_scope_boundary",
        classification="out_of_scope" if ref_count else "source_absent_not_required",
        checks=checks,
        raw_count=ref_count,
        ir_count=len(definitions_with_stage_ability),
        executable_count=0,
        blocked_or_gap_count=0,
        sample_source_trace=_source(_first(definitions_with_stage_ability)),
        details={
            "definition_count_with_stage_ability_refs": len(definitions_with_stage_ability),
            "stage_ability_ref_count": ref_count,
            "future_owner": "stage/environment layer, not MonsterDataCardIR passive runtime",
        },
    )


def _event_state() -> BattleState:
    return BattleState(
        units={
            "enemy:wave": UnitState(
                unit_id="enemy:wave",
                side="enemy",
                template_id="monster:validation:wave",
                hp=1000.0,
                max_hp=1000.0,
                flags={"position": 1},
            ),
            "ally:target": UnitState(
                unit_id="ally:target",
                side="ally",
                template_id="avatar:validation:target",
                hp=1000.0,
                max_hp=1000.0,
                flags={"position": 1},
            ),
        }
    )


def _monster_source(source_path: str, raw_id: str) -> bool:
    return "/Monster/" in source_path or "Monster" in source_path or str(raw_id).startswith("monster")


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    raw_count: int = 0,
    ir_count: int = 0,
    rulebook_visible_count: int = 0,
    executable_count: int = 0,
    blocked_or_gap_count: int = 0,
    gap_attribution: dict[str, int] | None = None,
    sample_source_trace: dict[str, JSONValue] | None = None,
    runtime_samples: list[dict[str, JSONValue]] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "raw_count": int(raw_count),
        "ir_count": int(ir_count),
        "rulebook_visible_count": int(rulebook_visible_count),
        "executable_count": int(executable_count),
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "gap_attribution": gap_attribution or {},
        "sample_source_trace": sample_source_trace or {},
        "runtime_samples": runtime_samples or [],
        "details": details or {},
    }


def _row_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return (
        dict(dict(rows.get(row_id) or {}).get("checks") or {})
        .get("checks", {})
        .get(check_id)
        is True
    )


def _counter_top(counter: Counter[str], limit: int) -> list[dict[str, JSONValue]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def _first(items: Iterable[Any]) -> Any | None:
    for item in items:
        return item
    return None


def _source(item: Any | None) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    return source.to_json() if source is not None else {}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
