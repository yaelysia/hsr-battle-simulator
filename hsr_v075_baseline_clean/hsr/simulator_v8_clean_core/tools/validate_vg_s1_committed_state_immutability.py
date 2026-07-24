from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..core.immutable_json import FrozenJSONDict, FrozenJSONList, thaw_json
from ..core.model import (
    BattleState,
    Mutation,
    Snapshot,
    UnitState,
    _FrozenQueueStateDict,
    _FrozenResourceDict,
    _FrozenUnitStateDict,
)
from ..core.reducer import MutationReducer
from ..core.unit_state_codec import unit_state_from_payload, unit_state_to_payload
from .io import write_json


VALIDATION_VERSION = "vg_s1_committed_state_immutability"
SUMMARY_SCHEMA_VERSION = "vg_s1_committed_state_immutability_validation_v1"


class _ForgedFrozenJSONDict(FrozenJSONDict):
    """Validation-only subclass that bypasses the trusted parent constructor."""

    def __init__(self, value: Any):
        dict.__init__(self, {"forged": value})


class _ForgedFrozenJSONList(FrozenJSONList):
    """Validation-only subclass that bypasses the trusted parent constructor."""

    def __init__(self, value: Any):
        list.__init__(self, [value])


TRUE_PREDICATES = (
    "unit_constructor_detaches_nested_inputs",
    "unit_nested_state_recursively_immutable",
    "unit_replace_reapplies_normalization",
    "battle_constructor_detaches_nested_inputs",
    "battle_units_mapping_immutable",
    "battle_global_flags_recursively_immutable",
    "battle_queues_recursively_immutable",
    "battle_replace_reapplies_normalization",
    "scalar_replace_reuses_unchanged_frozen_subtrees",
    "forged_frozen_containers_cannot_bypass_model_boundary",
    "frozen_json_subclasses_revalidated_at_model_boundaries",
    "snapshot_constructor_detaches_input",
    "snapshot_internal_data_recursively_immutable",
    "snapshot_to_json_returns_detached_plain_json",
    "snapshot_to_json_calls_are_independent",
    "snapshot_mutation_cannot_reach_battle_state",
    "unit_codec_output_is_detached_plain_json",
    "unit_codec_round_trip_is_deterministic",
    "reducer_set_result_is_immutable",
    "reducer_delete_result_is_immutable",
    "reducer_spawn_result_is_immutable",
    "reducer_failure_preserves_before_state",
    "replay_snapshot_remains_deterministic",
    "invalid_json_value_rejected",
    "non_string_json_key_rejected",
    "non_finite_json_number_rejected",
)


def run_validation(output_dir: Path) -> dict[str, Any]:
    unit_matrix, unit = _unit_matrix()
    battle_matrix, state = _battle_matrix(unit)
    snapshot_matrix = _snapshot_matrix(state)
    codec_matrix = _codec_matrix(unit)
    reducer_matrix = _reducer_matrix(state)
    compatibility_matrix = _consumer_compatibility_matrix(
        unit,
        state,
        codec_matrix["decoded_unit"],
        reducer_matrix,
    )

    predicates: dict[str, bool | int] = {
        "unit_constructor_detaches_nested_inputs": unit_matrix["constructor_alias"]["ok"],
        "unit_nested_state_recursively_immutable": unit_matrix["internal_writes"]["ok"],
        "unit_replace_reapplies_normalization": unit_matrix["replace"]["ok"],
        "battle_constructor_detaches_nested_inputs": battle_matrix["constructor_alias"]["ok"],
        "battle_units_mapping_immutable": battle_matrix["units_writes"]["ok"],
        "battle_global_flags_recursively_immutable": battle_matrix["global_flag_writes"]["ok"],
        "battle_queues_recursively_immutable": battle_matrix["queue_writes"]["ok"],
        "battle_replace_reapplies_normalization": battle_matrix["replace"]["ok"],
        "scalar_replace_reuses_unchanged_frozen_subtrees": all(
            (
                unit_matrix["replace"]["scalar_replace_reuses_flags"],
                unit_matrix["replace"][
                    "scalar_replace_reuses_shield_instances"
                ],
                unit_matrix["replace"]["scalar_replace_reuses_resources"],
                battle_matrix["replace"][
                    "scalar_replace_reuses_units_mapping"
                ],
                battle_matrix["replace"][
                    "scalar_replace_reuses_global_flags"
                ],
                battle_matrix["replace"][
                    "scalar_replace_reuses_queues_mapping"
                ],
            )
        ),
        "forged_frozen_containers_cannot_bypass_model_boundary": all(
            row["ok"]
            for row in (
                *unit_matrix["invalid_values"][
                    "forged_frozen_container_rows"
                ],
                *battle_matrix["invalid_values"][
                    "forged_frozen_container_rows"
                ],
            )
        ),
        "frozen_json_subclasses_revalidated_at_model_boundaries": all(
            (
                unit_matrix["constructor_alias"][
                    "frozen_dict_subclass_rebuilt"
                ],
                unit_matrix["constructor_alias"][
                    "nested_frozen_list_subclass_rebuilt"
                ],
                unit_matrix["constructor_alias"][
                    "shield_frozen_dict_subclass_rebuilt"
                ],
                battle_matrix["constructor_alias"][
                    "global_frozen_dict_subclass_rebuilt"
                ],
                battle_matrix["constructor_alias"][
                    "queue_frozen_list_subclass_rebuilt"
                ],
                snapshot_matrix["constructor_alias"][
                    "frozen_subclasses_rebuilt"
                ],
            )
        )
        and all(
            row["ok"]
            for row in (
                *unit_matrix["invalid_values"][
                    "forged_frozen_json_subclass_rows"
                ],
                *battle_matrix["invalid_values"][
                    "forged_frozen_json_subclass_rows"
                ],
                *snapshot_matrix["invalid_values"][
                    "forged_frozen_json_subclass_rows"
                ],
            )
        ),
        "snapshot_constructor_detaches_input": snapshot_matrix["constructor_alias"]["ok"],
        "snapshot_internal_data_recursively_immutable": snapshot_matrix["internal_writes"]["ok"],
        "snapshot_to_json_returns_detached_plain_json": snapshot_matrix["plain_json"]["ok"],
        "snapshot_to_json_calls_are_independent": snapshot_matrix["independent_exports"]["ok"],
        "snapshot_mutation_cannot_reach_battle_state": snapshot_matrix["battle_isolation"]["ok"],
        "unit_codec_output_is_detached_plain_json": codec_matrix["detached_output"]["ok"],
        "unit_codec_round_trip_is_deterministic": codec_matrix["round_trip"]["ok"],
        "reducer_set_result_is_immutable": reducer_matrix["set"]["ok"],
        "reducer_delete_result_is_immutable": reducer_matrix["delete"]["ok"],
        "reducer_spawn_result_is_immutable": reducer_matrix["spawn"]["ok"],
        "reducer_failure_preserves_before_state": reducer_matrix["failure"]["ok"],
        "replay_snapshot_remains_deterministic": reducer_matrix["replay"]["ok"],
        "invalid_json_value_rejected": all(
            row["ok"]
            for row in (
                *unit_matrix["invalid_values"]["unknown_object_rows"],
                *battle_matrix["invalid_values"]["unknown_object_rows"],
                *snapshot_matrix["invalid_values"]["unknown_object_rows"],
            )
        ),
        "non_string_json_key_rejected": all(
            row["ok"]
            for row in (
                *unit_matrix["invalid_values"]["non_string_key_rows"],
                *battle_matrix["invalid_values"]["non_string_key_rows"],
                *snapshot_matrix["invalid_values"]["non_string_key_rows"],
            )
        ),
        "non_finite_json_number_rejected": all(
            row["ok"]
            for row in (
                *unit_matrix["invalid_values"]["non_finite_rows"],
                *battle_matrix["invalid_values"]["non_finite_rows"],
                *snapshot_matrix["invalid_values"]["non_finite_rows"],
            )
        ),
        "production_behavior_semantics_changed": not compatibility_matrix["ok"],
        "tbgd_read_count": 0,
        "full_rulebook_build_count": 0,
    }
    predicate_expectations: dict[str, bool | int] = {
        **{name: True for name in TRUE_PREDICATES},
        "production_behavior_semantics_changed": False,
        "tbgd_read_count": 0,
        "full_rulebook_build_count": 0,
    }
    predicate_mismatches = {
        name: {"expected": expected, "actual": predicates.get(name)}
        for name, expected in predicate_expectations.items()
        if predicates.get(name) != expected
    }

    serializable_codec_matrix = {
        key: value for key, value in codec_matrix.items() if key != "decoded_unit"
    }
    serializable_reducer_matrix = {
        key: value
        for key, value in reducer_matrix.items()
        if key not in {"set_state", "set_mutations"}
    }
    matrices = {
        "unit": unit_matrix,
        "battle": battle_matrix,
        "snapshot": snapshot_matrix,
        "codec": serializable_codec_matrix,
        "reducer_replay": serializable_reducer_matrix,
        "consumer_compatibility": compatibility_matrix,
    }
    matrix_summary = {
        name: {
            "ok": bool(matrix["ok"]),
            "row_count": _count_rows(matrix),
        }
        for name, matrix in matrices.items()
    }
    ok = not predicate_mismatches and all(
        item["ok"] for item in matrix_summary.values()
    )
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "version": VALIDATION_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "predicates": predicates,
        "predicate_expectations": predicate_expectations,
        "predicate_mismatches": predicate_mismatches,
        "matrix_summary": matrix_summary,
        "resource_budget": {
            "tbgd_read_count": 0,
            "full_rulebook_build_count": 0,
            "minimal_in_memory_rulebook_build_count": 0,
            "large_artifacts_written": False,
            "full_snapshot_dump_written": False,
            "output_scope": "summary_and_compact_matrices",
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir
        / "validation_summary_vg_s1_committed_state_immutability.json",
        summary,
    )
    write_json(
        output_dir / "vg_s1_committed_state_immutability_matrices.json",
        {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "matrices": matrices,
        },
    )
    return summary


def _unit_matrix() -> tuple[dict[str, Any], UnitState]:
    statuses = ["status:validation"]
    flags = {
        "lifecycle_status": "active",
        "position": 0,
        "nested": {
            "level_two": {
                "values": [{"token": "stable"}],
            }
        },
        "status_details": [
            {
                "status_id": "status:validation",
                "details": {"layers": [1, 2]},
            }
        ],
        "modifiers": [{"modifier_name": "modifier:validation"}],
    }
    shield_instances = [_shield_instance("shield:unit:1", 12.0)]
    resources = {
        "recoverable_hp": 4.0,
        "custom_resource": 2,
    }
    unit = _unit(
        statuses=statuses,
        flags=flags,
        shield_instances=shield_instances,
        resources=resources,
    )
    untrusted_flag_list = _ForgedFrozenJSONList("valid")
    untrusted_flags = _ForgedFrozenJSONDict(untrusted_flag_list)
    subclass_flags_unit = _unit(flags=untrusted_flags)
    untrusted_shield = _ForgedFrozenJSONDict("valid")
    subclass_shield_unit = _unit(
        shield_instances=(untrusted_shield,)
    )
    before = unit_state_to_payload(unit)
    statuses.append("status:external")
    flags["nested"]["level_two"]["values"][0]["token"] = "polluted"
    flags["nested"]["level_two"]["values"].append({"token": "external"})
    shield_instances[0]["source_trace"]["raw"]["paths"].append("external")
    shield_instances.append(_shield_instance("shield:external", 1.0))
    resources["custom_resource"] = 999.0
    constructor_checks = {
        "payload_unchanged_after_input_mutation": unit_state_to_payload(unit) == before,
        "statuses_saved_as_tuple": type(unit.statuses) is tuple,
        "shield_instances_saved_as_tuple": type(unit.shield_instances) is tuple,
        "flags_dict_compatible": isinstance(unit.flags, dict),
        "nested_flags_dict_compatible": isinstance(unit.flags["nested"], dict),
        "resources_dict_compatible": isinstance(unit.resources, dict),
        "frozen_dict_subclass_rebuilt": type(subclass_flags_unit.flags)
        is FrozenJSONDict
        and subclass_flags_unit.flags is not untrusted_flags,
        "nested_frozen_list_subclass_rebuilt": type(
            subclass_flags_unit.flags["forged"]
        )
        is FrozenJSONList
        and subclass_flags_unit.flags["forged"] is not untrusted_flag_list,
        "shield_frozen_dict_subclass_rebuilt": type(
            subclass_shield_unit.shield_instances[0]
        )
        is FrozenJSONDict
        and subclass_shield_unit.shield_instances[0] is not untrusted_shield,
    }
    constructor_alias = {
        **constructor_checks,
        "ok": all(constructor_checks.values()),
    }

    writes = [
        _write_attempt("statuses.append", lambda: _append(unit.statuses, "x")),
        _write_attempt(
            "shield_instances.append",
            lambda: _append(unit.shield_instances, {}),
        ),
        _write_attempt(
            "flags.top_assignment",
            lambda: _assign(unit.flags, "external", True),
        ),
        _write_attempt(
            "flags.top_update",
            lambda: _update(unit.flags, {"external": True}),
        ),
        _write_attempt("flags.top_pop", lambda: _pop(unit.flags, "nested")),
        _write_attempt(
            "flags.top_setdefault",
            lambda: _setdefault(unit.flags, "external", True),
        ),
        _write_attempt(
            "flags.nested_assignment",
            lambda: _assign(unit.flags["nested"]["level_two"], "external", True),
        ),
        _write_attempt(
            "flags.nested_update",
            lambda: _update(
                unit.flags["nested"]["level_two"],
                {"external": True},
            ),
        ),
        _write_attempt(
            "flags.nested_list_append",
            lambda: _append(
                unit.flags["nested"]["level_two"]["values"],
                {"token": "external"},
            ),
        ),
        _write_attempt(
            "shield.instance_assignment",
            lambda: _assign(unit.shield_instances[0], "remaining", 0.0),
        ),
        _write_attempt(
            "shield.nested_update",
            lambda: _update(
                unit.shield_instances[0]["source_trace"]["raw"],
                {"external": True},
            ),
        ),
        _write_attempt(
            "shield.nested_list_append",
            lambda: _append(
                unit.shield_instances[0]["source_trace"]["raw"]["paths"],
                "external",
            ),
        ),
        _write_attempt(
            "resources.assignment",
            lambda: _assign(unit.resources, "custom_resource", 3.0),
        ),
        _write_attempt(
            "resources.update",
            lambda: _update(unit.resources, {"custom_resource": 3.0}),
        ),
        _write_attempt(
            "resources.pop",
            lambda: _pop(unit.resources, "custom_resource"),
        ),
        _write_attempt(
            "resources.setdefault",
            lambda: _setdefault(unit.resources, "external", 1.0),
        ),
    ]
    internal_writes = {"rows": writes, "ok": all(row["ok"] for row in writes)}

    replacement_statuses = ["status:replacement"]
    replacement_flags = {"replacement": {"items": [{"value": "stable"}]}}
    replacement_shields = [_shield_instance("shield:replacement", 8.0)]
    replacement_resources = {"replacement_resource": 7}
    old_before = unit_state_to_payload(unit)
    replaced = replace(
        unit,
        statuses=replacement_statuses,
        flags=replacement_flags,
        shield_instances=replacement_shields,
        resources=replacement_resources,
    )
    replaced_before = unit_state_to_payload(replaced)
    scalar_replaced = replace(unit, hp=unit.hp - 1.0)
    replacement_statuses.append("status:external")
    replacement_flags["replacement"]["items"][0]["value"] = "polluted"
    replacement_shields[0]["priority_audit"]["kind"] = "polluted"
    replacement_resources["replacement_resource"] = 999
    replace_checks = {
        "new_unit_detached": unit_state_to_payload(replaced) == replaced_before,
        "old_unit_unchanged": unit_state_to_payload(unit) == old_before,
        "new_statuses_tuple": type(replaced.statuses) is tuple,
        "scalar_replace_changes_only_scalar": scalar_replaced.hp
        == unit.hp - 1.0,
        "scalar_replace_reuses_flags": scalar_replaced.flags is unit.flags,
        "scalar_replace_reuses_shield_instances": scalar_replaced.shield_instances
        is unit.shield_instances,
        "scalar_replace_reuses_resources": scalar_replaced.resources
        is unit.resources,
        "new_nested_flags_immutable": _write_attempt(
            "replace.flags.nested_assignment",
            lambda: _assign(replaced.flags["replacement"]["items"][0], "value", "x"),
        )["ok"],
        "new_shield_nested_immutable": _write_attempt(
            "replace.shield.nested_assignment",
            lambda: _assign(
                replaced.shield_instances[0]["priority_audit"],
                "kind",
                "x",
            ),
        )["ok"],
        "new_resources_immutable": _write_attempt(
            "replace.resources.assignment",
            lambda: _assign(replaced.resources, "replacement_resource", 1.0),
        )["ok"],
    }
    replace_matrix = {**replace_checks, "ok": all(replace_checks.values())}

    unknown_object_rows = [
        _rejection(
            "unit.flags.unknown_object",
            lambda: _unit(flags={"bad": object()}),
        ),
        _rejection(
            "unit.shield.unknown_object",
            lambda: _unit(shield_instances=[{"bad": object()}]),
        ),
        _rejection(
            "unit.resources.unknown_object",
            lambda: _unit(resources={"bad": object()}),
        ),
    ]
    non_string_key_rows = [
        _rejection(
            "unit.flags.non_string_key",
            lambda: _unit(flags={1: "bad"}),
        ),
        _rejection(
            "unit.shield.non_string_key",
            lambda: _unit(shield_instances=[{1: "bad"}]),
        ),
        _rejection(
            "unit.resources.non_string_key",
            lambda: _unit(resources={1: 1.0}),
        ),
    ]
    non_finite_rows = [
        _rejection(
            "unit.flags.nan",
            lambda: _unit(flags={"bad": math.nan}),
        ),
        _rejection(
            "unit.shield.infinity",
            lambda: _unit(shield_instances=[{"bad": math.inf}]),
        ),
        _rejection(
            "unit.resources.nan",
            lambda: _unit(resources={"bad": math.nan}),
        ),
        _rejection(
            "unit.resources.infinity",
            lambda: _unit(resources={"bad": math.inf}),
        ),
    ]
    representation_rows = [
        _rejection(
            "unit.statuses.non_string_member",
            lambda: _unit(statuses=["valid", 1]),
        ),
        _rejection(
            "unit.shield.non_object_member",
            lambda: _unit(shield_instances=[["not", "an", "object"]]),
        ),
        _rejection(
            "unit.resources.bool",
            lambda: _unit(resources={"bad": True}),
        ),
    ]
    forged_frozen_container_rows = [
        _rejection(
            "unit.resources.forged_frozen.nan",
            lambda: _unit(
                resources=_FrozenResourceDict({"bad": math.nan})
            ),
        ),
    ]
    forged_frozen_json_subclass_rows = [
        _rejection(
            "unit.flags.forged_frozen_dict.unknown_object",
            lambda: _unit(
                flags=_ForgedFrozenJSONDict(object())
            ),
        ),
        _rejection(
            "unit.flags.nested_forged_frozen_list.unknown_object",
            lambda: _unit(
                flags={
                    "nested": _ForgedFrozenJSONList(object()),
                }
            ),
        ),
        _rejection(
            "unit.shield.forged_frozen_dict.unknown_object",
            lambda: _unit(
                shield_instances=(
                    _ForgedFrozenJSONDict(object()),
                )
            ),
        ),
    ]
    invalid_values = {
        "unknown_object_rows": unknown_object_rows,
        "non_string_key_rows": non_string_key_rows,
        "non_finite_rows": non_finite_rows,
        "representation_rows": representation_rows,
        "forged_frozen_container_rows": forged_frozen_container_rows,
        "forged_frozen_json_subclass_rows": (
            forged_frozen_json_subclass_rows
        ),
        "ok": all(
            row["ok"]
            for row in (
                *unknown_object_rows,
                *non_string_key_rows,
                *non_finite_rows,
                *representation_rows,
                *forged_frozen_container_rows,
                *forged_frozen_json_subclass_rows,
            )
        ),
    }
    matrix = {
        "constructor_alias": constructor_alias,
        "internal_writes": internal_writes,
        "replace": replace_matrix,
        "invalid_values": invalid_values,
    }
    matrix["ok"] = all(row["ok"] for row in matrix.values())
    return matrix, unit


def _battle_matrix(unit: UnitState) -> tuple[dict[str, Any], BattleState]:
    units = {"ally:actor": unit}
    global_flags = {
        "phase": "action",
        "current_window": "idle",
        "turn_owner_id": "ally:actor",
        "nested": {"level_two": {"values": [{"token": "stable"}]}},
        "status_ledger": [{"status_id": "status:validation"}],
        "summon_runtime": {
            "entries": {
                "summon:1": {
                    "runtime_id": "summon:1",
                    "targetability": {"targetable": True},
                }
            },
            "by_owner": {"ally:actor": ["summon:1"]},
        },
        "targeting": {
            "ally:actor": {
                "primary_target_id": "enemy:target",
                "target_ids": ["enemy:target"],
            }
        },
        "settlement": {
            "records": [{"record_id": "settlement:1", "details": {"terms": [1.0]}}]
        },
        "coverage": {"paths": [{"path": "validation"}]},
        "pending_events": [{"event_id": "event:pending"}],
        "rng_events": [{"event_id": "rng:1", "outcome": "hit"}],
        "active_turn": {"actor_id": "ally:actor"},
        "turn_queue_policy": {"policy": "stable"},
    }
    queue_item = {
        "entry_id": "queue:1",
        "payload": {
            "targets": ["enemy:target"],
            "details": {"kind": "validation"},
        },
    }
    queue_values = [queue_item]
    queues = {"action": queue_values}
    state = BattleState(
        units=units,
        global_flags=global_flags,
        queues=queues,
        skill_points=3,
        max_skill_points=5,
    )
    untrusted_global_list = _ForgedFrozenJSONList("valid")
    untrusted_global_flags = _ForgedFrozenJSONDict(
        untrusted_global_list
    )
    untrusted_queue_item = _ForgedFrozenJSONList("valid")
    subclass_state = BattleState(
        units={"ally:actor": unit},
        global_flags=untrusted_global_flags,
        queues={"queue": (untrusted_queue_item,)},
    )
    before = state.snapshot().to_json()
    units["external:unit"] = unit
    global_flags["nested"]["level_two"]["values"][0]["token"] = "polluted"
    global_flags["summon_runtime"]["by_owner"]["ally:actor"].append("external")
    queue_item["payload"]["targets"].append("external")
    queue_values.append({"entry_id": "queue:external"})
    queues["external"] = []
    constructor_checks = {
        "snapshot_unchanged_after_input_mutation": state.snapshot().to_json() == before,
        "units_mapping_detached": set(state.units) == {"ally:actor"},
        "global_flags_detached": state.global_flags["nested"]["level_two"]["values"][0][
            "token"
        ]
        == "stable",
        "queue_mapping_detached": set(state.queues) == {"action"},
        "queue_list_detached": len(state.queues["action"]) == 1,
        "queue_item_detached": list(
            state.queues["action"][0]["payload"]["targets"]
        )
        == ["enemy:target"],
        "global_frozen_dict_subclass_rebuilt": type(
            subclass_state.global_flags
        )
        is FrozenJSONDict
        and subclass_state.global_flags is not untrusted_global_flags
        and type(subclass_state.global_flags["forged"])
        is FrozenJSONList
        and subclass_state.global_flags["forged"]
        is not untrusted_global_list,
        "queue_frozen_list_subclass_rebuilt": type(
            subclass_state.queues["queue"][0]
        )
        is FrozenJSONList
        and subclass_state.queues["queue"][0] is not untrusted_queue_item,
    }
    constructor_alias = {
        **constructor_checks,
        "ok": all(constructor_checks.values()),
    }

    units_writes = _write_group(
        [
            _write_attempt(
                "units.assignment",
                lambda: _assign(state.units, "external", unit),
            ),
            _write_attempt(
                "units.update",
                lambda: _update(state.units, {"external": unit}),
            ),
            _write_attempt("units.pop", lambda: _pop(state.units, "ally:actor")),
            _write_attempt(
                "units.setdefault",
                lambda: _setdefault(state.units, "external", unit),
            ),
        ]
    )
    global_flag_writes = _write_group(
        [
            _write_attempt(
                "global_flags.assignment",
                lambda: _assign(state.global_flags, "external", True),
            ),
            _write_attempt(
                "global_flags.update",
                lambda: _update(state.global_flags, {"external": True}),
            ),
            _write_attempt(
                "global_flags.pop",
                lambda: _pop(state.global_flags, "nested"),
            ),
            _write_attempt(
                "global_flags.nested_assignment",
                lambda: _assign(
                    state.global_flags["nested"]["level_two"],
                    "external",
                    True,
                ),
            ),
            _write_attempt(
                "global_flags.nested_list_append",
                lambda: _append(
                    state.global_flags["nested"]["level_two"]["values"],
                    {"token": "external"},
                ),
            ),
        ]
    )
    queue_writes = _write_group(
        [
            _write_attempt(
                "queues.assignment",
                lambda: _assign(state.queues, "external", ()),
            ),
            _write_attempt(
                "queues.update",
                lambda: _update(state.queues, {"external": ()}),
            ),
            _write_attempt("queues.pop", lambda: _pop(state.queues, "action")),
            _write_attempt(
                "queue_tuple.append",
                lambda: _append(state.queues["action"], {}),
            ),
            _write_attempt(
                "queue_item.assignment",
                lambda: _assign(state.queues["action"][0], "entry_id", "external"),
            ),
            _write_attempt(
                "queue_item.nested_assignment",
                lambda: _assign(
                    state.queues["action"][0]["payload"]["details"],
                    "kind",
                    "external",
                ),
            ),
            _write_attempt(
                "queue_item.nested_list_append",
                lambda: _append(
                    state.queues["action"][0]["payload"]["targets"],
                    "external",
                ),
            ),
        ]
    )

    global_input = {"replacement": {"items": [{"value": "stable"}]}}
    queue_input = {
        "replacement": [{"entry_id": "replacement", "payload": {"steps": [1, 2]}}]
    }
    replacement_unit = replace(
        unit,
        unit_id="ally:replacement",
        template_id="validation:replacement",
    )
    units_input = {"ally:replacement": replacement_unit}
    replaced_global = replace(state, global_flags=global_input)
    replaced_queues = replace(state, queues=queue_input)
    replaced_units = replace(state, units=units_input)
    scalar_replaced_state = replace(
        state,
        skill_points=state.skill_points - 1,
    )
    global_before = replaced_global.snapshot().to_json()
    queue_before = replaced_queues.snapshot().to_json()
    unit_before = replaced_units.snapshot().to_json()
    global_input["replacement"]["items"][0]["value"] = "polluted"
    queue_input["replacement"][0]["payload"]["steps"].append(3)
    queue_input["external"] = []
    units_input.clear()
    replace_checks = {
        "global_flags_re_normalized": replaced_global.snapshot().to_json()
        == global_before,
        "queues_re_normalized": replaced_queues.snapshot().to_json() == queue_before,
        "units_re_normalized": replaced_units.snapshot().to_json() == unit_before,
        "scalar_replace_changes_only_scalar": scalar_replaced_state.skill_points
        == state.skill_points - 1,
        "scalar_replace_reuses_units_mapping": scalar_replaced_state.units
        is state.units,
        "scalar_replace_reuses_global_flags": scalar_replaced_state.global_flags
        is state.global_flags,
        "scalar_replace_reuses_queues_mapping": scalar_replaced_state.queues
        is state.queues,
        "scalar_replace_reuses_queue_item": scalar_replaced_state.queues[
            "action"
        ][0]
        is state.queues["action"][0],
        "global_flags_nested_immutable": _write_attempt(
            "replace.global_flags.nested_assignment",
            lambda: _assign(
                replaced_global.global_flags["replacement"]["items"][0],
                "value",
                "external",
            ),
        )["ok"],
        "queue_item_nested_immutable": _write_attempt(
            "replace.queue.nested_list_append",
            lambda: _append(
                replaced_queues.queues["replacement"][0]["payload"]["steps"],
                3,
            ),
        )["ok"],
        "units_mapping_immutable": _write_attempt(
            "replace.units.assignment",
            lambda: _assign(replaced_units.units, "external", replacement_unit),
        )["ok"],
    }
    replace_matrix = {**replace_checks, "ok": all(replace_checks.values())}

    unknown_object_rows = [
        _rejection(
            "battle.global_flags.unknown_object",
            lambda: BattleState(global_flags={"bad": object()}),
        ),
        _rejection(
            "battle.queue.unknown_object",
            lambda: BattleState(queues={"queue": [{"bad": object()}]}),
        ),
    ]
    non_string_key_rows = [
        _rejection(
            "battle.global_flags.non_string_key",
            lambda: BattleState(global_flags={1: "bad"}),
        ),
        _rejection(
            "battle.queue_item.non_string_key",
            lambda: BattleState(queues={"queue": [{1: "bad"}]}),
        ),
    ]
    non_finite_rows = [
        _rejection(
            "battle.global_flags.nan",
            lambda: BattleState(global_flags={"bad": math.nan}),
        ),
        _rejection(
            "battle.queue.infinity",
            lambda: BattleState(queues={"queue": [{"bad": math.inf}]}),
        ),
    ]
    representation_rows = [
        _rejection(
            "battle.units.empty_key",
            lambda: BattleState(units={"": unit}),
        ),
        _rejection(
            "battle.units.non_string_key",
            lambda: BattleState(units={1: unit}),
        ),
        _rejection(
            "battle.units.non_unit_value",
            lambda: BattleState(units={"ally:actor": object()}),
        ),
        _rejection(
            "battle.queue.empty_name",
            lambda: BattleState(queues={"": []}),
        ),
        _rejection(
            "battle.queue.non_string_name",
            lambda: BattleState(queues={1: []}),
        ),
        _rejection(
            "battle.queue.non_sequence",
            lambda: BattleState(queues={"queue": {"item": "bad"}}),
        ),
    ]
    forged_frozen_container_rows = [
        _rejection(
            "battle.units.forged_frozen.non_unit_value",
            lambda: BattleState(
                units=_FrozenUnitStateDict(
                    {"ally:forged": object()}
                )
            ),
        ),
        _rejection(
            "battle.queues.forged_frozen.non_sequence",
            lambda: BattleState(
                queues=_FrozenQueueStateDict(
                    {"queue": {"item": "bad"}}
                )
            ),
        ),
    ]
    forged_frozen_json_subclass_rows = [
        _rejection(
            "battle.global_flags.forged_frozen_dict.unknown_object",
            lambda: BattleState(
                global_flags=_ForgedFrozenJSONDict(object())
            ),
        ),
        _rejection(
            "battle.queue.forged_frozen_list.unknown_object",
            lambda: BattleState(
                queues={
                    "queue": (
                        _ForgedFrozenJSONList(object()),
                    )
                }
            ),
        ),
    ]
    invalid_values = {
        "unknown_object_rows": unknown_object_rows,
        "non_string_key_rows": non_string_key_rows,
        "non_finite_rows": non_finite_rows,
        "representation_rows": representation_rows,
        "forged_frozen_container_rows": forged_frozen_container_rows,
        "forged_frozen_json_subclass_rows": (
            forged_frozen_json_subclass_rows
        ),
        "ok": all(
            row["ok"]
            for row in (
                *unknown_object_rows,
                *non_string_key_rows,
                *non_finite_rows,
                *representation_rows,
                *forged_frozen_container_rows,
                *forged_frozen_json_subclass_rows,
            )
        ),
    }
    matrix = {
        "constructor_alias": constructor_alias,
        "units_writes": units_writes,
        "global_flag_writes": global_flag_writes,
        "queue_writes": queue_writes,
        "replace": replace_matrix,
        "invalid_values": invalid_values,
    }
    matrix["ok"] = all(row["ok"] for row in matrix.values())
    return matrix, state


def _snapshot_matrix(state: BattleState) -> dict[str, Any]:
    source = {
        "root": {
            "children": [
                {
                    "name": "stable",
                    "details": {"values": [1, 2]},
                }
            ]
        }
    }
    snapshot = Snapshot(source)
    snapshot_from_frozen_input = Snapshot(snapshot.data)
    untrusted_snapshot_list = _ForgedFrozenJSONList("valid")
    untrusted_snapshot_data = _ForgedFrozenJSONDict(
        untrusted_snapshot_list
    )
    subclass_snapshot = Snapshot(untrusted_snapshot_data)
    expected = snapshot.to_json()
    source["root"]["children"][0]["name"] = "polluted"
    source["root"]["children"][0]["details"]["values"].append(3)
    constructor_checks = {
        "source_mutation_does_not_change_snapshot": snapshot.to_json() == expected,
        "source_and_snapshot_data_are_distinct": snapshot.data is not source,
        "already_frozen_input_is_structurally_shared": snapshot_from_frozen_input.data
        is snapshot.data,
        "already_frozen_input_keeps_value": snapshot_from_frozen_input.to_json()
        == expected,
        "frozen_subclasses_rebuilt": type(subclass_snapshot.data)
        is FrozenJSONDict
        and subclass_snapshot.data is not untrusted_snapshot_data
        and type(subclass_snapshot.data["forged"]) is FrozenJSONList
        and subclass_snapshot.data["forged"] is not untrusted_snapshot_list,
    }
    constructor_alias = {
        **constructor_checks,
        "ok": all(constructor_checks.values()),
    }
    internal_writes = _write_group(
        [
            _write_attempt(
                "snapshot.data.assignment",
                lambda: _assign(snapshot.data, "external", True),
            ),
            _write_attempt(
                "snapshot.data.nested_assignment",
                lambda: _assign(
                    snapshot.data["root"]["children"][0],
                    "name",
                    "external",
                ),
            ),
            _write_attempt(
                "snapshot.data.nested_update",
                lambda: _update(
                    snapshot.data["root"]["children"][0]["details"],
                    {"external": True},
                ),
            ),
            _write_attempt(
                "snapshot.data.nested_list_append",
                lambda: _append(
                    snapshot.data["root"]["children"][0]["details"]["values"],
                    3,
                ),
            ),
        ]
    )

    first = snapshot.to_json()
    second = snapshot.to_json()
    plain_checks = {
        "first_export_is_plain_json": _is_plain_json(first),
        "second_export_is_plain_json": _is_plain_json(second),
        "top_level_is_exact_dict": type(first) is dict,
        "nested_object_is_exact_dict": type(first["root"]) is dict,
        "nested_array_is_exact_list": type(first["root"]["children"]) is list,
        "json_dumps_allow_nan_false": _json_dumps_succeeds(first),
    }
    plain_json = {**plain_checks, "ok": all(plain_checks.values())}
    first["root"]["children"][0]["name"] = "external"
    first["root"]["children"][0]["details"]["values"].append(999)
    first["external"] = True
    independent_checks = {
        "exports_are_distinct": first is not second,
        "nested_exports_are_distinct": first["root"] is not second["root"],
        "second_export_unchanged": second == expected,
        "third_export_unchanged": snapshot.to_json() == expected,
    }
    independent_exports = {
        **independent_checks,
        "ok": all(independent_checks.values()),
    }

    before = state.snapshot().to_json()
    exposed = state.snapshot().to_json()
    exposed["global_flags"]["summon_runtime"]["entries"]["summon:1"][
        "targetability"
    ]["targetable"] = False
    exposed["global_flags"]["targeting"]["ally:actor"]["target_ids"].append(
        "external"
    )
    exposed["global_flags"]["settlement"]["records"][0]["details"]["terms"].append(
        999.0
    )
    exposed["units"]["ally:actor"]["flags"]["nested"]["level_two"]["values"][0][
        "token"
    ] = "external"
    exposed["units"]["ally:actor"]["status_details"][0]["details"]["layers"].append(
        999
    )
    exposed["units"]["ally:actor"]["shield_instances"][0]["source_trace"]["raw"][
        "paths"
    ].append("external")
    exposed["queues"]["action"][0]["payload"]["targets"].append("external")
    exposed["targeting"]["ally:actor"]["target_ids"].append("external")
    exposed["settlement"]["records"][0]["details"]["terms"].append(999.0)
    after = state.snapshot().to_json()
    equivalent_state = BattleState(
        units=dict(state.units),
        wave_index=state.wave_index,
        skill_points=state.skill_points,
        max_skill_points=state.max_skill_points,
        global_flags=thaw_json(state.global_flags),
        queues={
            name: thaw_json(queue)
            for name, queue in state.queues.items()
        },
        rng_state=state.rng_state,
        event_index=state.event_index,
    )
    isolation_checks = {
        "mutated_export_does_not_change_state_snapshot": after == before,
        "unit_flags_unchanged": state.units["ally:actor"].flags["nested"][
            "level_two"
        ]["values"][0]["token"]
        == "stable",
        "unit_status_details_unchanged": list(
            state.units["ally:actor"].flags["status_details"][0]["details"][
                "layers"
            ]
        )
        == [1, 2],
        "shield_details_unchanged": list(
            state.units["ally:actor"].shield_instances[0]["source_trace"]["raw"][
                "paths"
            ]
        )
        == ["source"],
        "queue_item_unchanged": list(
            state.queues["action"][0]["payload"]["targets"]
        )
        == ["enemy:target"],
        "summon_runtime_unchanged": state.global_flags["summon_runtime"]["entries"][
            "summon:1"
        ]["targetability"]["targetable"]
        is True,
        "equivalent_states_have_equal_snapshots": equivalent_state.snapshot().to_json()
        == before,
        "snapshot_serializes_without_nan": _json_dumps_succeeds(after),
    }
    battle_isolation = {
        **isolation_checks,
        "ok": all(isolation_checks.values()),
    }

    unknown_object_rows = [
        _rejection(
            "snapshot.unknown_object",
            lambda: Snapshot({"bad": object()}),
        )
    ]
    non_string_key_rows = [
        _rejection(
            "snapshot.non_string_key",
            lambda: Snapshot({1: "bad"}),
        )
    ]
    non_finite_rows = [
        _rejection(
            "snapshot.nan",
            lambda: Snapshot({"bad": math.nan}),
        ),
        _rejection(
            "snapshot.infinity",
            lambda: Snapshot({"bad": math.inf}),
        ),
    ]
    representation_rows = [
        _rejection(
            "snapshot.non_object_root",
            lambda: Snapshot(["bad"]),
        )
    ]
    forged_frozen_json_subclass_rows = [
        _rejection(
            "snapshot.data.forged_frozen_dict.unknown_object",
            lambda: Snapshot(
                _ForgedFrozenJSONDict(object())
            ),
        ),
    ]
    invalid_values = {
        "unknown_object_rows": unknown_object_rows,
        "non_string_key_rows": non_string_key_rows,
        "non_finite_rows": non_finite_rows,
        "representation_rows": representation_rows,
        "forged_frozen_json_subclass_rows": (
            forged_frozen_json_subclass_rows
        ),
        "ok": all(
            row["ok"]
            for row in (
                *unknown_object_rows,
                *non_string_key_rows,
                *non_finite_rows,
                *representation_rows,
                *forged_frozen_json_subclass_rows,
            )
        ),
    }
    matrix = {
        "constructor_alias": constructor_alias,
        "internal_writes": internal_writes,
        "plain_json": plain_json,
        "independent_exports": independent_exports,
        "battle_isolation": battle_isolation,
        "invalid_values": invalid_values,
    }
    matrix["ok"] = all(row["ok"] for row in matrix.values())
    return matrix


def _codec_matrix(unit: UnitState) -> dict[str, Any]:
    payload = unit_state_to_payload(unit)
    original = copy.deepcopy(payload)
    payload["flags"]["nested"]["level_two"]["values"][0]["token"] = "external"
    payload["shield_instances"][0]["source_trace"]["raw"]["paths"].append(
        "external"
    )
    payload["resources"]["custom_resource"] = 999.0
    payload["statuses"].append("status:external")
    fresh_payload = unit_state_to_payload(unit)
    detached_checks = {
        "payload_is_plain_json": _is_plain_json(fresh_payload),
        "payload_mutation_does_not_change_unit": fresh_payload == original,
        "flags_detached": payload["flags"] is not unit.flags,
        "shield_detached": payload["shield_instances"][0]
        is not unit.shield_instances[0],
        "resources_detached": payload["resources"] is not unit.resources,
    }
    detached_output = {
        **detached_checks,
        "ok": all(detached_checks.values()),
    }

    decoded = unit_state_from_payload(fresh_payload)
    encoded_again = unit_state_to_payload(decoded)
    encoded_third = unit_state_to_payload(decoded)
    round_trip_checks = {
        "payload_round_trip_equal": encoded_again == fresh_payload,
        "second_encode_equal": encoded_third == encoded_again,
        "snapshot_round_trip_equal": decoded.to_snapshot() == unit.to_snapshot(),
        "decoded_flags_immutable": _write_attempt(
            "codec.decoded.flags.assignment",
            lambda: _assign(decoded.flags, "external", True),
        )["ok"],
        "decoded_shield_nested_immutable": _write_attempt(
            "codec.decoded.shield.nested_list_append",
            lambda: _append(
                decoded.shield_instances[0]["source_trace"]["raw"]["paths"],
                "external",
            ),
        )["ok"],
        "decoded_resources_immutable": _write_attempt(
            "codec.decoded.resources.assignment",
            lambda: _assign(decoded.resources, "external", 1.0),
        )["ok"],
    }
    round_trip = {
        **round_trip_checks,
        "ok": all(round_trip_checks.values()),
    }
    return {
        "detached_output": detached_output,
        "round_trip": round_trip,
        "decoded_unit": decoded,
        "ok": detached_output["ok"] and round_trip["ok"],
    }


def _reducer_matrix(state: BattleState) -> dict[str, Any]:
    reducer = MutationReducer()
    unit = state.units["ally:actor"]
    set_mutations = (
        _mutation(
            "set",
            ("units", "ally:actor", "hp"),
            unit.hp,
            90.0,
        ),
        _mutation(
            "set",
            ("units", "ally:actor", "flags", "reducer_nested"),
            None,
            {"values": [{"token": "stable"}]},
            before_exists=False,
        ),
        _mutation(
            "set",
            ("units", "ally:actor", "resources", "reducer_resource"),
            None,
            3.0,
            before_exists=False,
        ),
        _mutation(
            "set",
            ("global_flags", "reducer_global"),
            None,
            {"items": [{"value": "stable"}]},
            before_exists=False,
        ),
        _mutation(
            "set",
            ("queues", "action"),
            thaw_json(state.queues["action"]),
            [
                {
                    "entry_id": "queue:reducer",
                    "payload": {"steps": [1, 2]},
                }
            ],
        ),
    )
    state_before = state.snapshot().to_json()
    set_result = reducer.apply_all_result(state, set_mutations)
    set_state = set_result.after_state
    set_write_rows = [
        _write_attempt(
            "reducer.set.units.assignment",
            lambda: _assign(set_state.units, "external", unit),
        ),
        _write_attempt(
            "reducer.set.unit_flag_nested_assignment",
            lambda: _assign(
                set_state.units["ally:actor"].flags["reducer_nested"]["values"][0],
                "token",
                "external",
            ),
        ),
        _write_attempt(
            "reducer.set.resource_assignment",
            lambda: _assign(
                set_state.units["ally:actor"].resources,
                "reducer_resource",
                4.0,
            ),
        ),
        _write_attempt(
            "reducer.set.global_nested_assignment",
            lambda: _assign(
                set_state.global_flags["reducer_global"]["items"][0],
                "value",
                "external",
            ),
        ),
        _write_attempt(
            "reducer.set.queue_nested_list_append",
            lambda: _append(
                set_state.queues["action"][0]["payload"]["steps"],
                3,
            ),
        ),
    ]
    set_checks = {
        "reduction_succeeded": set_result.ok,
        "all_mutations_applied": set_result.applied_count == len(set_mutations),
        "unit_scalar_set": set_state.units["ally:actor"].hp == 90.0,
        "nested_flag_set": set_state.units["ally:actor"].flags[
            "reducer_nested"
        ]["values"][0]["token"]
        == "stable",
        "resource_set": set_state.units["ally:actor"].resources[
            "reducer_resource"
        ]
        == 3.0,
        "global_flag_set": set_state.global_flags["reducer_global"]["items"][0][
            "value"
        ]
        == "stable",
        "queue_set": list(set_state.queues["action"][0]["payload"]["steps"])
        == [1, 2],
        "before_state_unchanged": state.snapshot().to_json() == state_before,
        "all_result_writes_rejected": all(row["ok"] for row in set_write_rows),
    }
    set_matrix = {
        **set_checks,
        "write_rows": set_write_rows,
        "ok": all(set_checks.values()),
    }

    delete_mutations = (
        _mutation(
            "delete",
            ("units", "ally:actor", "flags", "nested"),
            thaw_json(state.units["ally:actor"].flags["nested"]),
            None,
            after_exists=False,
        ),
        _mutation(
            "delete",
            ("units", "ally:actor", "resources", "recoverable_hp"),
            state.units["ally:actor"].resources["recoverable_hp"],
            None,
            after_exists=False,
        ),
        _mutation(
            "delete",
            ("global_flags", "targeting"),
            thaw_json(state.global_flags["targeting"]),
            None,
            after_exists=False,
        ),
        _mutation(
            "delete",
            ("queues", "action"),
            thaw_json(state.queues["action"]),
            None,
            after_exists=False,
        ),
    )
    delete_result = reducer.apply_all_result(state, delete_mutations)
    delete_state = delete_result.after_state
    delete_write_rows = [
        _write_attempt(
            "reducer.delete.units.assignment",
            lambda: _assign(delete_state.units, "external", unit),
        ),
        _write_attempt(
            "reducer.delete.flags.assignment",
            lambda: _assign(
                delete_state.units["ally:actor"].flags,
                "external",
                True,
            ),
        ),
        _write_attempt(
            "reducer.delete.global_flags.assignment",
            lambda: _assign(delete_state.global_flags, "external", True),
        ),
        _write_attempt(
            "reducer.delete.queues.assignment",
            lambda: _assign(delete_state.queues, "external", ()),
        ),
    ]
    delete_checks = {
        "reduction_succeeded": delete_result.ok,
        "all_mutations_applied": delete_result.applied_count
        == len(delete_mutations),
        "unit_flag_deleted": "nested"
        not in delete_state.units["ally:actor"].flags,
        "resource_deleted": "recoverable_hp"
        not in delete_state.units["ally:actor"].resources,
        "global_flag_deleted": "targeting" not in delete_state.global_flags,
        "queue_deleted": "action" not in delete_state.queues,
        "before_state_unchanged": state.snapshot().to_json() == state_before,
        "all_result_writes_rejected": all(row["ok"] for row in delete_write_rows),
    }
    delete_matrix = {
        **delete_checks,
        "write_rows": delete_write_rows,
        "ok": all(delete_checks.values()),
    }

    spawn_unit = replace(
        unit,
        unit_id="ally:spawn",
        template_id="validation:spawn",
    )
    spawn_payload = unit_state_to_payload(spawn_unit)
    spawn_mutation = _mutation(
        "spawn",
        ("units", "ally:spawn"),
        None,
        spawn_payload,
        before_exists=False,
    )
    spawn_payload_before = copy.deepcopy(spawn_payload)
    spawn_payload["flags"]["nested"]["level_two"]["values"][0]["token"] = "external"
    spawn_result = reducer.apply_all_result(state, (spawn_mutation,))
    spawn_state = spawn_result.after_state
    spawn_write_rows = [
        _write_attempt(
            "reducer.spawn.units.assignment",
            lambda: _assign(spawn_state.units, "external", unit),
        ),
        _write_attempt(
            "reducer.spawn.flags.nested_assignment",
            lambda: _assign(
                spawn_state.units["ally:spawn"].flags["nested"]["level_two"][
                    "values"
                ][0],
                "token",
                "external",
            ),
        ),
        _write_attempt(
            "reducer.spawn.resources.assignment",
            lambda: _assign(
                spawn_state.units["ally:spawn"].resources,
                "external",
                1.0,
            ),
        ),
    ]
    spawn_checks = {
        "reduction_succeeded": spawn_result.ok,
        "spawn_applied": "ally:spawn" in spawn_state.units,
        "spawn_payload_canonical": unit_state_to_payload(
            spawn_state.units["ally:spawn"]
        )
        == spawn_payload_before,
        "original_state_has_no_spawn": "ally:spawn" not in state.units,
        "all_result_writes_rejected": all(row["ok"] for row in spawn_write_rows),
    }
    spawn_matrix = {
        **spawn_checks,
        "write_rows": spawn_write_rows,
        "ok": all(spawn_checks.values()),
    }

    external_after = {"values": [{"token": "stable"}]}
    external_after_before = copy.deepcopy(external_after)
    failure_mutations = (
        _mutation(
            "set",
            ("global_flags", "temporary"),
            None,
            external_after,
            before_exists=False,
        ),
        _mutation(
            "set",
            ("skill_points",),
            999,
            2,
        ),
    )
    failure_result = reducer.apply_all_result(state, failure_mutations)
    failure_checks = {
        "reduction_failed": not failure_result.ok,
        "after_is_original_state": failure_result.after_state is state,
        "before_is_original_state": failure_result.before_state is state,
        "zero_applied_mutations": failure_result.applied_count == 0,
        "before_snapshot_unchanged": state.snapshot().to_json() == state_before,
        "external_after_input_unchanged": external_after == external_after_before,
        "temporary_path_absent": "temporary" not in state.global_flags,
    }
    failure_matrix = {
        **failure_checks,
        "conflict_codes": [
            conflict.code for conflict in failure_result.conflicts
        ],
        "ok": all(failure_checks.values()),
    }

    expected = set_state.snapshot().to_json()
    expected_before = copy.deepcopy(expected)
    successful_replay = reducer.replay_snapshot(state, set_mutations, expected)
    tampered = copy.deepcopy(expected)
    tampered["global_flags"]["reducer_global"]["items"][0]["value"] = "tampered"
    failed_replay = reducer.replay_snapshot(state, set_mutations, tampered)
    second_successful_replay = reducer.replay_snapshot(
        state,
        set_mutations,
        expected,
    )
    replay_checks = {
        "detached_expected_replays": successful_replay.ok,
        "tampered_copy_mismatches": not failed_replay.ok
        and bool(failed_replay.errors)
        and failed_replay.errors[0].startswith("snapshot_mismatch:"),
        "original_expected_unchanged": expected == expected_before,
        "second_replay_still_succeeds": second_successful_replay.ok,
        "before_state_unchanged": state.snapshot().to_json() == state_before,
        "actual_snapshot_deterministic": successful_replay.actual
        == second_successful_replay.actual
        == expected,
    }
    replay_matrix = {
        **replay_checks,
        "failed_replay_errors": list(failed_replay.errors),
        "ok": all(replay_checks.values()),
    }

    matrix = {
        "set": set_matrix,
        "delete": delete_matrix,
        "spawn": spawn_matrix,
        "failure": failure_matrix,
        "replay": replay_matrix,
        "set_state": set_state,
        "set_mutations": set_mutations,
    }
    matrix["ok"] = all(
        matrix[name]["ok"]
        for name in ("set", "delete", "spawn", "failure", "replay")
    )
    return matrix


def _consumer_compatibility_matrix(
    unit: UnitState,
    state: BattleState,
    decoded: UnitState,
    reducer_matrix: dict[str, Any],
) -> dict[str, Any]:
    snapshot = state.snapshot().to_json()
    expected_snapshot_keys = {
        "battle",
        "event_index",
        "global_flags",
        "max_skill_points",
        "metadata",
        "pending_events",
        "queues",
        "resources",
        "rng_state",
        "rng_events",
        "skill_points",
        "targeting",
        "teams",
        "active_teams",
        "timeline",
        "units",
        "wave_index",
        "settlement",
        "coverage",
    }
    checks = {
        "unit_flags_isinstance_dict": isinstance(unit.flags, dict),
        "nested_unit_flag_isinstance_dict": isinstance(
            unit.flags["nested"]["level_two"],
            dict,
        ),
        "unit_flags_get_works": unit.flags.get("lifecycle_status") == "active",
        "unit_flags_items_work": "nested" in dict(unit.flags.items()),
        "unit_flags_values_work": any(
            value == "active" for value in unit.flags.values()
        ),
        "unit_flags_dict_copy_is_writable": _copy_can_be_written(unit.flags),
        "resources_get_works": unit.resources.get("custom_resource") == 2.0,
        "battle_units_isinstance_dict": isinstance(state.units, dict),
        "battle_units_get_works": state.units.get("ally:actor") is unit,
        "battle_units_iteration_works": list(state.units) == ["ally:actor"],
        "battle_units_dict_copy_is_writable": _copy_can_be_written(state.units),
        "global_flags_get_works": state.global_flags.get("phase") == "action",
        "queues_isinstance_dict": isinstance(state.queues, dict),
        "queue_is_tuple": type(state.queues["action"]) is tuple,
        "queue_iteration_works": list(state.queues["action"])[0]["entry_id"]
        == "queue:1",
        "queue_indexing_works": state.queues["action"][0]["entry_id"] == "queue:1",
        "queue_length_works": len(state.queues["action"]) == 1,
        "snapshot_structure_preserved": set(snapshot) == expected_snapshot_keys,
        "snapshot_json_values_preserved": snapshot["battle"]["phase"] == "action"
        and snapshot["units"]["ally:actor"]["flags"]["nested"]["level_two"][
            "values"
        ][0]["token"]
        == "stable",
        "unit_to_snapshot_plain_json": _is_plain_json(unit.to_snapshot()),
        "codec_decode_read_compatible": decoded.flags.get("nested") is not None,
        "reducer_operation_semantics_preserved": all(
            reducer_matrix[name]["ok"]
            for name in ("set", "delete", "spawn", "failure", "replay")
        ),
    }
    return {
        "checks": checks,
        "ok": all(checks.values()),
    }


def _unit(**overrides: Any) -> UnitState:
    values: dict[str, Any] = {
        "unit_id": "ally:actor",
        "side": "ally",
        "template_id": "validation:actor",
        "max_hp": 100.0,
        "hp": 100.0,
        "attack": 40.0,
        "defense": 30.0,
        "speed": 100.0,
        "energy": 20.0,
        "max_energy": 100.0,
        "toughness": 60.0,
        "max_toughness": 60.0,
        "action_value": 25.0,
    }
    values.update(overrides)
    return UnitState(**values)


def _shield_instance(instance_id: str, remaining: float) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "shield_id": "shield:validation",
        "source_id": "source:validation",
        "source_actor_id": "ally:actor",
        "source_kind": "status",
        "remaining": remaining,
        "capacity": remaining,
        "priority": 1,
        "stack_policy": "replace",
        "absorb_families": ["direct", "dot"],
        "created_event_index": 1,
        "source_trace": {
            "source_path": "validation/source.json",
            "raw": {"paths": ["source"]},
        },
        "priority_audit": {"kind": "explicit", "value": 1},
        "priority_rule": {
            "shield_priority_rule_id": "shield_priority_rule:validation",
            "registry_version": "validation_v1",
        },
        "owner_modifier_name": "modifier:shield",
        "status_instance_id": "status:shield",
    }


def _mutation(
    op: str,
    path: tuple[str, ...],
    before: Any,
    after: Any,
    *,
    before_exists: bool = True,
    after_exists: bool = True,
) -> Mutation:
    return Mutation(
        op=op,
        path=path,
        before=before,
        after=after,
        before_exists=before_exists,
        after_exists=after_exists,
        reason="VG-S1 validation",
        source="validation:vg_s1",
    )


def _write_attempt(name: str, callback: Callable[[], Any]) -> dict[str, Any]:
    try:
        callback()
    except Exception as exc:
        return {
            "case": name,
            "ok": isinstance(exc, (TypeError, AttributeError)),
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
    return {
        "case": name,
        "ok": False,
        "exception_type": "",
        "message": "write unexpectedly succeeded",
    }


def _rejection(name: str, callback: Callable[[], Any]) -> dict[str, Any]:
    try:
        callback()
    except Exception as exc:
        return {
            "case": name,
            "ok": isinstance(exc, (TypeError, ValueError)),
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
    return {
        "case": name,
        "ok": False,
        "exception_type": "",
        "message": "invalid input unexpectedly succeeded",
    }


def _write_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"rows": rows, "ok": all(row["ok"] for row in rows)}


def _assign(mapping: Any, key: Any, value: Any) -> None:
    mapping[key] = value


def _append(sequence: Any, value: Any) -> None:
    sequence.append(value)


def _update(mapping: Any, values: Any) -> None:
    mapping.update(values)


def _pop(mapping: Any, key: Any) -> None:
    mapping.pop(key)


def _setdefault(mapping: Any, key: Any, value: Any) -> None:
    mapping.setdefault(key, value)


def _copy_can_be_written(mapping: Any) -> bool:
    copied = dict(mapping)
    copied["validation:copy"] = True
    return copied["validation:copy"] is True and "validation:copy" not in mapping


def _is_plain_json(value: Any) -> bool:
    if value is None or type(value) in {bool, int, str}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_is_plain_json(item) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _is_plain_json(item)
            for key, item in value.items()
        )
    return False


def _json_dumps_succeeds(value: Any) -> bool:
    try:
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return False
    return True


def _count_rows(value: Any) -> int:
    if isinstance(value, dict):
        count = 1 if "ok" in value else 0
        return count + sum(_count_rows(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_rows(item) for item in value)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate VG-S1 committed state recursive immutability.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_validation(args.output_dir.resolve())
    passed = sum(
        1
        for name, expected in result["predicate_expectations"].items()
        if result["predicates"].get(name) == expected
    )
    total = len(result["predicate_expectations"])
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"predicates={passed}/{total} "
        f"ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
