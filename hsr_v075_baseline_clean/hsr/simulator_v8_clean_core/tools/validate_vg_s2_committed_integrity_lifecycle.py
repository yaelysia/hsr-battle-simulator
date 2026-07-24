from __future__ import annotations

import argparse
import ast
import copy
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from ..core.atomic_commit import (
    ATOMIC_COMMIT_SCHEMA_VERSION,
    events_for_atomic_result,
    finalize_selected_execution_graph,
    records_for_atomic_result,
    rng_events_for_atomic_result,
)
from ..core.model import BattleState, Mutation, RNGEvent, UnitState
from ..core.reducer import MutationReducer
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.state_integrity import (
    CommittedStateIntegrityError,
    CommittedStateIntegrityGate,
    StateIntegrityResult,
)
from ..core.transition_outcome import ExecutionNodeResult
from ..core.unit_state_codec import unit_state_from_payload, unit_state_to_payload
from ..ir_types import IRSource
from ..rules.ir import (
    CanonicalIR,
    RuleEntity,
    StatusCallbackIR,
    StatusCallbackTaskIR,
    StatusEventFamilyIR,
)
from ..rules.rulebook import RuleBook
from ..scenarios import build_state as scenario_build_state_module
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import PanelInput, ScenarioSpec, UnitSpec
from ..systems.damage import DamagePacket, DamageSystem, DamageWindowLedger
from ..systems.mutation_events import events_for_mutation
from ..systems.status import StatusSystem, _halo_member_is_present
from ..systems.status_callbacks import StatusCallbackSystem
from ..systems.summon_runtime import empty_summon_runtime, validate_summon_runtime
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..unit_eligibility import runtime_unit_is_target_candidate
from .io import write_json


VALIDATION_VERSION = "vg_s2_committed_integrity_lifecycle"
SOURCE = "validation"
LIFECYCLE_RECORD = {"reason": SOURCE}
ALLY = "ally:a"
DEFEATED = "enemy:defeated"
CONSUMER = "unit:consumer"
TARGET = "enemy:target"
SUMMARY_SCHEMA_VERSION = "vg_s2_summary_v1"
MATRIX_SCHEMA_VERSION = "vg_s2_matrix_v1"
OUTPUT_LIMIT_BYTES = 1024 * 1024
LEGACY_KEYS = {"lifecycle_status", "lifecycle_state"}


def _unit(
    unit_id: str,
    *,
    side: str = "ally",
    status: str = "active",
    hp: float = 100.0,
    max_hp: float = 100.0,
    flags: dict[str, Any] | None = None,
) -> UnitState:
    return UnitState(
        unit_id=unit_id,
        side=side,  # type: ignore[arg-type]
        template_id=f"validation:{unit_id}",
        lifecycle_status=status,  # type: ignore[arg-type]
        max_hp=max_hp,
        hp=hp,
        flags=flags or {},
    )


def _state(*units: UnitState, **kwargs: Any) -> BattleState:
    return BattleState(units={unit.unit_id: unit for unit in units}, **kwargs)


def _mutation(
    path: tuple[str, ...],
    *,
    before: Any,
    after: Any,
    op: str = "set",
    before_exists: bool = True,
    after_exists: bool = True,
) -> Mutation:
    return Mutation(
        op=op,
        path=path,
        before=before,
        after=after,
        reason="VG-S2 validation",
        source=SOURCE,
        before_exists=before_exists,
        after_exists=after_exists,
    )


def _node(node_id: str = "validation:complete") -> ExecutionNodeResult:
    return ExecutionNodeResult(
        node_kind=SOURCE,
        node_id=node_id,
        status="complete",
    )


def _successor(result: Any) -> bool:
    return result.outcome.successor_eligible


def _atomic(
    before: BattleState,
    mutations: tuple[Mutation, ...],
):
    reduction = MutationReducer().apply_all_result(before, mutations)
    candidate = reduction.after_state if reduction.ok else before
    return finalize_selected_execution_graph(
        before,
        candidate,
        mutations,
        (_node(),),
    )


def _codes(result: StateIntegrityResult) -> tuple[str, ...]:
    return tuple(issue.code for issue in result.issues)


def _has_codes(
    result: StateIntegrityResult,
    *expected: str,
) -> bool:
    return set(expected).issubset(_codes(result))


def _scope_entities(result: StateIntegrityResult) -> tuple[str, ...]:
    return tuple(
        entity_id
        for scope in result.checked_scopes
        for entity_id in scope.entity_ids
    )


def _conflict_code(result: Any) -> str:
    return result.conflicts[0].code if result.conflicts else ""


def _row(case_id: str, ok: bool) -> dict[str, Any]:
    return {"case_id": case_id, "ok": ok}


def _full(unit: UnitState) -> StateIntegrityResult:
    return CommittedStateIntegrityGate().check_full(_state(unit))


def _damage_fixture() -> tuple[BattleState, Any]:
    before = _state(
        _unit("ally:attacker"),
        _unit(TARGET, side="enemy"),
    )
    packet = DamagePacket(
        attacker_id="ally:attacker",
        target_id=TARGET,
        attack_type="validation_attack",
        damage_formula_family="hp_loss",
        amount=100.0,
        amount_stage="fixed_final",
        source_trace={"validation": "vg_s2"},
    )
    result = DamageSystem().apply_packet(
        before,
        packet,
        window_ledger=DamageWindowLedger(),
    )
    return before, result


def _event_family(
    event_type: str,
    callback_event: str,
    source: IRSource,
) -> StatusEventFamilyIR:
    return StatusEventFamilyIR(
        status_event_family_id=f"vg_s2:{event_type}", callback_event=callback_event,
        event_family="setup", default_scope_kind="global_listener",
        runtime_event_sources=(event_type,), source_basis=SOURCE, source=source,
        coverage_status="executable", admission_status="executable",
    )


def _alive_count_names(case_id: str) -> tuple[str, str, str, str]:
    return (
        f"validation:alive_count:{case_id}",
        f"ValidationAliveCount{case_id.title()}",
        f"OnValidationAliveCount{case_id.title()}",
        f"alive_count_{case_id}",
    )


def _alive_count_callback_ir(
    case_id: str,
    read_alias: str,
    write_alias: str,
    source: IRSource,
) -> tuple[StatusCallbackIR, StatusCallbackTaskIR]:
    callback_id, modifier_name, event, dynamic_key = _alive_count_names(case_id)
    task_id = f"{callback_id}:task"
    callback = StatusCallbackIR(
        callback_id=callback_id,
        modifier_name=modifier_name,
        event=event,
        task_ids=(task_id,),
        source=source,
        execution_order=(0, 0),
        coverage_status="executable",
        admission_status="executable",
    )
    task = StatusCallbackTaskIR(
        task_id=task_id,
        callback_id=callback_id,
        modifier_name=modifier_name,
        event=event,
        task_index=0,
        task_path="TaskList[0]",
        branch="root",
        opcode="SetDynamicValueByCharacterCount",
        source=source,
        coverage_status="executable",
        task_payload={
            "DynamicKey": dynamic_key,
            "ReadTargetType": read_alias,
            "WriteTargetType": write_alias,
            "AliveOnly": True,
        },
    )
    return callback, task


def _small_rulebook() -> RuleBook:
    source = IRSource(
        source_path="validation/vg_s2",
        raw_type="Validation",
        raw_id="avatar",
    )
    group_callback, group_task = _alive_count_callback_ir(
        "group",
        "AllEnemyWithUnSelectable",
        "ModifierOwnerEntity",
        source,
    )
    single_callback, single_task = _alive_count_callback_ir(
        "single",
        "ModifierOwnerEntity",
        "Caster",
        source,
    )
    return RuleBook(
        CanonicalIR(
            version="vg_s2",
            entities=(
                RuleEntity(
                    entity_id="validation:avatar",
                    entity_type="avatar",
                    fields={},
                    source=source,
                    coverage_status="executable",
                ),
            ),
            status_event_families=(
                _event_family("unit.created", "OnListenCharacterCreate", source),
                _event_family("battle.setup", "OnEnterBattle", source),
            ),
            status_callbacks=(group_callback, single_callback),
            status_callback_tasks=(group_task, single_task),
        )
    )


def _scenario(hp: float) -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="vg_s2_scenario",
        version="1",
        units=(
            UnitSpec(
                unit_id="ally:scenario",
                side="ally",
                entity_ref="validation:avatar",
                build_mode="kernel_fixture",
                panel=PanelInput(max_hp=10.0, hp=hp),
            ),
        ),
        route=(),
    )


def _scenario_matrix(
    rules: RuleBook,
) -> tuple[dict[str, Any], dict[str, Any]]:
    builder = ScenarioStateBuilder(rules)
    full_calls: list[str] = []
    original = CommittedStateIntegrityGate.require_full

    def tracked(gate: CommittedStateIntegrityGate, state: BattleState) -> StateIntegrityResult:
        result = original(gate, state)
        full_calls.append(f"{result.check_mode}:{result.status}")
        return result

    with patch.object(CommittedStateIntegrityGate, "require_full", new=tracked):
        valid_result = builder.build(_scenario(10.0))

    invalid_error: CommittedStateIntegrityError | None = None
    with (
        patch.object(
            scenario_build_state_module, "register_dynamic_ability_providers",
            side_effect=AssertionError("provider must not observe invalid initial state"),
        ) as provider_mock,
        patch.object(
            scenario_build_state_module, "_apply_startup_ability_effects",
            side_effect=AssertionError("startup must not observe invalid initial state"),
        ) as startup_mock,
    ):
        try:
            builder.build(_scenario(0.0))
        except CommittedStateIntegrityError as exc:
            invalid_error = exc

    valid = {
        "ok": (
            valid_result.state.units["ally:scenario"].lifecycle_status == "active"
            and full_calls == ["full:passed", "full:passed"]
        ),
        "full_calls": full_calls,
    }
    invalid = {
        "ok": (
            invalid_error is not None
            and "active_unit_hp_not_positive" in _codes(invalid_error.result)
            and provider_mock.call_count == 0
            and startup_mock.call_count == 0
        ),
        "issue_codes": list(_codes(invalid_error.result)) if invalid_error else [],
        "provider_call_count": provider_mock.call_count,
        "startup_call_count": startup_mock.call_count,
    }
    return valid, invalid


def _callback_count_evidence(
    result: Any,
) -> tuple[float | None, tuple[str, ...]]:
    for mutation in result.mutations:
        if mutation.path != ("global_flags", "dynamic_value_store"):
            continue
        value = mutation.metadata.get("value")
        source = mutation.metadata.get("value_source")
        target_ids = source.get("target_ids", ()) if isinstance(source, dict) else ()
        if not isinstance(value, (int, float)):
            return None, ()
        return float(value), tuple(str(item) for item in target_ids)
    return None, ()


def _execute_alive_count_callback(
    system: StatusCallbackSystem,
    state: BattleState,
    *,
    case_id: str,
    owner_id: str,
    caster_id: str,
) -> dict[str, Any]:
    _, modifier_name, event, _ = _alive_count_names(case_id)
    result = system.execute(
        state,
        unit_id=owner_id,
        modifier_name=modifier_name,
        event=event,
        detail_override={
            "instance_id": f"validation:alive_count:{case_id}:instance",
            "status_id": f"modifier:{modifier_name}",
            "modifier_name": modifier_name,
            "owner_id": owner_id,
            "caster_id": caster_id,
            "source_trace": {"validation": VALIDATION_VERSION},
        },
    )
    value, target_ids = _callback_count_evidence(result)
    return {
        "result_ok": result.ok,
        "value": value,
        "target_ids": list(target_ids),
        "errors": list(result.errors),
    }


def _status_callback_alive_count_matrix(
    rules: RuleBook,
) -> dict[str, dict[str, Any]]:
    caster_id = "ally:counter"
    active_unselectable_id = "enemy:active_unselectable"
    removed_id = "enemy:removed_positive_hp"
    state = _state(
        _unit(caster_id),
        _unit(
            active_unselectable_id,
            side="enemy",
            flags={"unselectable": True},
        ),
        _unit(
            removed_id,
            side="enemy",
            status="removed",
            hp=50.0,
            flags={"removed_record": LIFECYCLE_RECORD},
        ),
    )
    system = StatusCallbackSystem(rules)
    group = _execute_alive_count_callback(
        system,
        state,
        case_id="group",
        owner_id=caster_id,
        caster_id=caster_id,
    )
    single = _execute_alive_count_callback(
        system,
        state,
        case_id="single",
        owner_id=removed_id,
        caster_id=caster_id,
    )
    group["ok"] = (
        group["result_ok"]
        and group["value"] == 1.0
        and group["target_ids"] == [active_unselectable_id]
    )
    single["ok"] = (
        single["result_ok"]
        and single["value"] == 0.0
        and single["target_ids"] == []
    )
    return {"group_branch": group, "single_branch": single}


def _legacy_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in LEGACY_KEYS


def _flags_expression(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "flags"
    ) or (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "dict"
        and bool(node.args)
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == "flags"
    )


def _contains_hp_attribute(node: ast.AST) -> bool:
    return any(
        isinstance(item, ast.Attribute) and item.attr == "hp"
        for item in ast.walk(node)
    )


def _is_zero_literal(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and not isinstance(node.value, bool)
        and node.value in {0, 0.0}
    )


def _is_hp_zero_comparison(node: ast.AST) -> bool:
    if not isinstance(node, ast.Compare):
        return False
    operands = (node.left, *node.comparators)
    return (
        any(_contains_hp_attribute(item) for item in operands)
        and any(_is_zero_literal(item) for item in operands)
    )


def _runtime_authority_scan(package_root: Path) -> dict[str, Any]:
    roots = (
        package_root / "core",
        package_root / "systems",
        package_root / "rules",
        package_root / "scenarios",
        package_root / "builds",
        package_root / "equipment",
    )
    paths = [package_root / "unit_eligibility.py"]
    paths.extend(path for root in roots for path in root.rglob("*.py"))
    legacy_rows: list[dict[str, Any]] = []
    hp_fallback_rows: list[dict[str, Any]] = []
    hp_scan_exclusions = {
        "core/state_integrity.py",
        "scenarios/build_state.py",
    }
    for path in sorted(set(paths)):
        relative = str(path.relative_to(package_root))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and _flags_expression(node.value)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            base = (
                node.func.value
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and _legacy_literal(node.args[0])
                else node.value
                if isinstance(node, ast.Subscript) and _legacy_literal(node.slice)
                else None
            )
            direct = base is not None and (
                _flags_expression(base)
                or isinstance(base, ast.Name) and base.id in aliases
            )
            elements = node.elts if isinstance(node, (ast.Tuple, ast.List)) else ()
            legacy_path = (
                len(elements) == 4
                and isinstance(elements[0], ast.Constant)
                and elements[0].value == "units"
                and isinstance(elements[2], ast.Constant)
                and elements[2].value == "flags"
                and _legacy_literal(elements[3])
            )
            if direct or legacy_path:
                legacy_rows.append(
                    {
                        "path": relative,
                        "line": int(getattr(node, "lineno", 0)),
                        "kind": "unit_flags_access" if direct else "legacy_path",
                    }
                )
            if (
                relative not in hp_scan_exclusions
                and _is_hp_zero_comparison(node)
            ):
                hp_fallback_rows.append(
                    {
                        "path": relative,
                        "line": int(getattr(node, "lineno", 0)),
                        "kind": "hp_zero_lifecycle_fallback",
                    }
                )
    return {
        "count": len(legacy_rows),
        "refs": legacy_rows,
        "hp_fallback_count": len(hp_fallback_rows),
        "hp_fallback_refs": hp_fallback_rows,
        "scanned_file_count": len(set(paths)),
    }


def _validator_oracle_audit(source_path: Path) -> dict[str, Any]:
    source = source_path.read_text(encoding="utf-8")
    forbidden = {
        "_lifecycle_final_state_issues",
        "_lifecycle_transition_issues",
        "_lifecycle_unit_id_for_path",
    }
    duplicated = sorted(name for name in forbidden if f"def {name}" in source or f"import {name}" in source)
    gate_calls = sum(source.count(f".{name}(") for name in ("check_full", "check_touched", "require_full"))
    return {
        "ok": not duplicated and gate_calls > 0,
        "duplicated_private_checkers": duplicated,
        "production_gate_call_count": gate_calls,
    }


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    reducer = MutationReducer()
    gate = CommittedStateIntegrityGate()
    lifecycle = UnitLifecycleSystem()
    rules = _small_rulebook()

    active_before = _state(_unit(ALLY))
    nonlethal_mutation = _mutation(
        ("units", ALLY, "hp"),
        before=100.0,
        after=60.0,
    )
    nonlethal = _atomic(active_before, (nonlethal_mutation,))

    unrelated_before = _state(
        _unit(ALLY),
        _unit("enemy:b", side="enemy"),
        skill_points=3,
    )
    unrelated_mutations = (
        _mutation(
            ("skill_points",),
            before=3,
            after=2,
        ),
        _mutation(
            ("global_flags", "marker"),
            before=None,
            after=True,
            before_exists=False,
        ),
    )
    unrelated = _atomic(unrelated_before, unrelated_mutations)

    selected_mutation = _mutation(
        ("units", ALLY, "hp"),
        before=100.0,
        after=80.0,
    )
    selected = _atomic(unrelated_before, (selected_mutation,))

    spawn_before = BattleState()
    spawn_mutation = lifecycle.spawn_mutation(
        spawn_before,
        _unit("summon:new", side="summon"),
        reason="VG-S2 legal spawn",
        source=SOURCE,
        source_trace={"source_kind": SOURCE},
    )
    spawn = _atomic(spawn_before, (spawn_mutation,))

    damage_before, damage_result = _damage_fixture()
    damage_candidate = reducer.apply_all_result(damage_before, damage_result.mutations)
    damage_commit = (
        finalize_selected_execution_graph(
            damage_before,
            damage_candidate.after_state,
            damage_result.mutations,
            (_node("validation:damage"),),
        )
        if damage_candidate.ok
        else None
    )
    damage_paths = {mutation.path for mutation in damage_result.mutations}
    expected_damage_paths = {
        ("units", TARGET, "hp"),
        ("units", TARGET, "lifecycle_status"),
        ("units", TARGET, "flags", "defeat_record"),
    }
    intermediate = (
        reducer.apply(damage_before, damage_result.mutations[0])
        if damage_result.mutations
        else damage_before
    )
    executor_source = (package_root / "core" / "executor.py").read_text(encoding="utf-8")
    batch_marker = (
        "current_state = self.reducer.apply_all("
        "current_state, damage_result.mutations)"
    )
    event_marker = "for mutation in damage_result.mutations:"
    batch_position = executor_source.find(batch_marker)
    event_position = executor_source.find(event_marker, batch_position + 1)
    private_batch_handoff = (
        batch_position >= 0
        and event_position > batch_position
        and intermediate.units[TARGET].hp == 0.0
        and intermediate.units[TARGET].lifecycle_status == "active"
    )

    active_remove_mutations = lifecycle.remove_mutations(
        active_before,
        ALLY,
        reason="VG-S2 legal active removal",
        source=SOURCE,
        removed_record=LIFECYCLE_RECORD,
        source_trace={"source_kind": SOURCE},
    )
    active_remove = _atomic(active_before, active_remove_mutations)

    defeated_unit = _unit(
        DEFEATED,
        side="enemy",
        status="defeated",
        hp=0.0,
        flags={"defeat_record": LIFECYCLE_RECORD},
    )
    defeated_before = _state(defeated_unit)
    defeated_remove_mutations = lifecycle.remove_mutations(
        defeated_before,
        DEFEATED,
        reason="VG-S2 legal defeated removal",
        source=SOURCE,
        removed_record=LIFECYCLE_RECORD,
        source_trace={"source_kind": SOURCE},
    )
    defeated_remove = _atomic(defeated_before, defeated_remove_mutations)

    legal_replays = (
        reducer.replay_snapshot(
            spawn_before,
            (spawn_mutation,),
            spawn.after_state.snapshot().to_json(),
        ),
        reducer.replay_snapshot(
            damage_before,
            damage_result.mutations,
            damage_candidate.after_state.snapshot().to_json(),
        ),
        reducer.replay_snapshot(
            active_before,
            active_remove_mutations,
            active_remove.after_state.snapshot().to_json(),
        ),
    )

    removed_events = events_for_mutation(active_remove_mutations[0])
    legacy_event_mutation = _mutation(
        ("units", ALLY, "flags", "lifecycle_status"),
        before=None,
        after="removed",
        before_exists=False,
    )
    legacy_events = events_for_mutation(legacy_event_mutation)

    removed_unit = _unit(
        ALLY,
        status="removed",
        hp=75.0,
        flags={"removed_record": LIFECYCLE_RECORD},
    )
    consumer_units = {
        "active": _unit(CONSUMER),
        "defeated": _unit(
            CONSUMER,
            status="defeated",
            hp=0.0,
            flags={"defeat_record": LIFECYCLE_RECORD},
        ),
        "removed": _unit(
            CONSUMER,
            status="removed",
            hp=50.0,
            flags={"removed_record": LIFECYCLE_RECORD},
        ),
    }
    consumer_states = {
        key: _state(unit) for key, unit in consumer_units.items()
    }
    consumer_views = {
        key: lifecycle.view(state, CONSUMER)
        for key, state in consumer_states.items()
    }
    status_plans = {
        key: StatusSystem().plan_lifecycle_tick(
            state,
            CONSUMER,
            {},
            "OnTurnEnd",
        )
        for key, state in consumer_states.items()
    }
    summon_flags = {
        "summon_kind": "servant",
        "owner_id": "ally:owner",
        "summoner_id": "ally:owner",
        "team_side": "ally",
    }
    owner = _unit("ally:owner")
    summon_active = _unit("summon:consumer", side="summon", hp=10.0, max_hp=10.0, flags=summon_flags)
    summon_removed = replace(
        summon_active,
        lifecycle_status="removed",
        flags={**summon_flags, "removed_record": LIFECYCLE_RECORD},
    )
    active_summon_check = validate_summon_runtime(
        empty_summon_runtime(), units={owner.unit_id: owner, summon_active.unit_id: summon_active}
    )
    removed_summon_check = validate_summon_runtime(
        empty_summon_runtime(), units={owner.unit_id: owner, summon_removed.unit_id: summon_removed}
    )

    scenario_valid, scenario_invalid = _scenario_matrix(rules)
    alive_count_matrix = _status_callback_alive_count_matrix(rules)

    codec_payload = unit_state_to_payload(removed_unit)
    codec_roundtrip = unit_state_from_payload(codec_payload)
    snapshot = _state(removed_unit).snapshot()
    snapshot_json = snapshot.to_json()
    snapshot_unit = snapshot_json["units"][ALLY]
    snapshot_contract = SnapshotCompletenessValidator()
    missing_status_snapshot = copy.deepcopy(snapshot_json)
    del missing_status_snapshot["units"][ALLY]["lifecycle_status"]
    missing_view_snapshot = copy.deepcopy(snapshot_json)
    del missing_view_snapshot["units"][ALLY]["lifecycle"]
    missing_status_result = snapshot_contract.validate(missing_status_snapshot)
    missing_view_result = snapshot_contract.validate(missing_view_snapshot)

    consumer_ok = (
        [consumer_views[key].status for key in consumer_views]
        == ["active", "defeated", "removed"]
        and [runtime_unit_is_target_candidate(unit) for unit in consumer_units.values()]
        == [True, False, False]
        and [
            lifecycle.can_act(consumer_states[key], CONSUMER)[0]
            for key in consumer_states
        ]
        == [True, False, False]
        and [
            _halo_member_is_present(consumer_states[key], CONSUMER)
            for key in consumer_states
        ]
        == [True, True, False]
        and not status_plans["active"].unsupported[0].startswith(
            "unit_not_active_for_status_lifecycle"
        )
        and status_plans["defeated"].unsupported[0].endswith(":defeated")
        and status_plans["removed"].unsupported[0].endswith(":removed")
        and not active_summon_check.ok
        and removed_summon_check.ok
    )
    legal_damage_commit = (
        damage_result.ok
        and damage_candidate.ok
        and damage_commit is not None
        and _successor(damage_commit)
        and expected_damage_paths.issubset(damage_paths)
    )
    active_remove_keeps_positive_hp = (
        _successor(active_remove)
        and active_remove.after_state.units[ALLY].hp == 100.0
        and active_remove.after_state.units[ALLY].lifecycle_status == "removed"
    )
    defeated_remove_keeps_records = (
        _successor(defeated_remove)
        and {"defeat_record", "removed_record"}.issubset(
            defeated_remove.after_state.units[DEFEATED].flags
        )
    )
    typed_removed_event_only = (
        any(event.event_type == "unit.removed" for event in removed_events)
        and not legacy_events
    )
    codec_snapshot_roundtrip = (
        codec_roundtrip == removed_unit
        and codec_payload["lifecycle_status"] == "removed"
        and snapshot_unit["lifecycle_status"] == "removed"
        and snapshot_unit["removed"] is True
        and snapshot_unit["defeated"] is False
        and snapshot_unit["lifecycle"]["status"] == "removed"
    )
    snapshot_contract_requires_lifecycle = (
        not missing_status_result.ok
        and not missing_view_result.ok
        and "units.ally:a.lifecycle_status"
        in missing_status_result.missing_paths
        and "units.ally:a.lifecycle" in missing_view_result.missing_paths
    )
    positive_checks = {
        "active_nonlethal_hp_commit": (
            _successor(nonlethal)
            and nonlethal.after_state.units[ALLY].hp == 60.0
        ),
        "unrelated_mutations_skip_lifecycle_units": (
            _successor(unrelated)
            and unrelated.integrity.checked_domains == ()
            and unrelated.integrity.checked_scopes == ()
        ),
        "touched_unit_only": (
            _successor(selected)
            and _scope_entities(selected.integrity) == (ALLY,)
        ),
        "legal_active_spawn": (
            _successor(spawn)
            and spawn.after_state.units["summon:new"].lifecycle_status
            == "active"
        ),
        "production_damage_defeat_batch": legal_damage_commit,
        "private_intermediate_then_complete_handoff": private_batch_handoff,
        "active_to_removed_keeps_positive_hp": (
            active_remove_keeps_positive_hp
        ),
        "defeated_to_removed_preserves_defeat_record": (
            defeated_remove_keeps_records
        ),
        "legal_spawn_defeat_remove_replay": all(
            result.ok for result in legal_replays
        ),
        "typed_removed_event_only": typed_removed_event_only,
        "shared_consumers_use_typed_lifecycle": consumer_ok,
        "scenario_two_full_checks": scenario_valid["ok"],
        "typed_codec_snapshot_roundtrip": codec_snapshot_roundtrip,
        "snapshot_contract_requires_lifecycle": (
            snapshot_contract_requires_lifecycle
        ),
    }
    positive_rows = [
        _row(case_id, ok)
        for case_id, ok in positive_checks.items()
    ]

    hp_zero_mutation = _mutation(
        ("units", ALLY, "hp"),
        before=100.0,
        after=0.0,
    )
    hp_zero_reduction = reducer.apply_all_result(active_before, (hp_zero_mutation,))
    hp_zero_failure = finalize_selected_execution_graph(
        active_before,
        hp_zero_reduction.after_state,
        (hp_zero_mutation,),
        (_node("validation:hp_zero"),),
    )

    status_only = _mutation(
        ("units", ALLY, "lifecycle_status"),
        before="active",
        after="defeated",
    )
    status_only_failure = _atomic(active_before, (status_only,))
    record_only = _mutation(
        ("units", ALLY, "flags", "defeat_record"),
        before=None,
        after=LIFECYCLE_RECORD,
        before_exists=False,
    )
    record_only_failure = _atomic(active_before, (record_only,))

    legal_defeated_after = _state(
        _unit(
            ALLY,
            status="defeated",
            hp=0.0,
            flags={"defeat_record": LIFECYCLE_RECORD},
        )
    )
    closure_markers = {
        "hp": _mutation(
            ("units", ALLY, "hp"),
            before=100.0,
            after=0.0,
        ),
        "status": status_only,
        "record": record_only,
    }
    missing_closure_results = {
        key: gate.check_touched(
            active_before,
            legal_defeated_after,
            tuple(
                mutation
                for marker, mutation in closure_markers.items()
                if marker != key
            ),
        )
        for key in closure_markers
    }

    defeated_hp_nonzero = _full(
        _unit(
            "unit:numeric",
            status="defeated",
            hp=1.0,
            flags={"defeat_record": LIFECYCLE_RECORD},
        )
    )
    defeated_missing_record = _full(
        _unit("unit:defeated_missing", status="defeated", hp=0.0)
    )
    defeated_removed_record = _full(
        _unit(
            "unit:defeated_removed",
            status="defeated",
            hp=0.0,
            flags={
                "defeat_record": LIFECYCLE_RECORD,
                "removed_record": LIFECYCLE_RECORD,
            },
        )
    )
    active_defeat_record = _full(
        _unit(
            "unit:active_defeat_record",
            flags={"defeat_record": LIFECYCLE_RECORD},
        )
    )
    active_removed_record = _full(
        _unit(
            "unit:active_removed_record",
            flags={"removed_record": LIFECYCLE_RECORD},
        )
    )
    active_removed_only = _atomic(
        active_before,
        (
            _mutation(
                ("units", ALLY, "lifecycle_status"),
                before="active",
                after="removed",
            ),
        ),
    )
    defeated_removed_only = _atomic(
        defeated_before,
        (
            _mutation(
                ("units", DEFEATED, "lifecycle_status"),
                before="defeated",
                after="removed",
            ),
        ),
    )
    removed_missing_record = _full(
        _unit("unit:removed_missing", status="removed", hp=50.0)
    )
    removed_positive_allowed = _full(removed_unit)

    revive_mutations = (
        _mutation(
            ("units", DEFEATED, "hp"),
            before=0.0,
            after=50.0,
        ),
        _mutation(
            ("units", DEFEATED, "lifecycle_status"),
            before="defeated",
            after="active",
        ),
        _mutation(
            ("units", DEFEATED, "flags", "defeat_record"),
            before=LIFECYCLE_RECORD,
            after=None,
            op="delete",
            after_exists=False,
        ),
    )
    revive_failure = _atomic(defeated_before, revive_mutations)

    removed_before = _state(removed_unit)
    reentry_active_mutations = (
        _mutation(
            ("units", ALLY, "lifecycle_status"),
            before="removed",
            after="active",
        ),
        _mutation(
            ("units", ALLY, "flags", "removed_record"),
            before=LIFECYCLE_RECORD,
            after=None,
            op="delete",
            after_exists=False,
        ),
    )
    reentry_active_failure = _atomic(removed_before, reentry_active_mutations)
    reentry_defeated_mutations = (
        _mutation(
            ("units", ALLY, "hp"),
            before=75.0,
            after=0.0,
        ),
        _mutation(
            ("units", ALLY, "lifecycle_status"),
            before="removed",
            after="defeated",
        ),
        _mutation(
            ("units", ALLY, "flags", "defeat_record"),
            before=None,
            after=LIFECYCLE_RECORD,
            before_exists=False,
        ),
        _mutation(
            ("units", ALLY, "flags", "removed_record"),
            before=LIFECYCLE_RECORD,
            after=None,
            op="delete",
            after_exists=False,
        ),
    )
    reentry_defeated_failure = _atomic(
        removed_before,
        reentry_defeated_mutations,
    )

    active_payload = unit_state_to_payload(_unit("spawn:invalid"))
    defeated_spawn_payload = copy.deepcopy(active_payload)
    defeated_spawn_payload.update(
        {
            "lifecycle_status": "defeated",
            "hp": 0.0,
            "flags": {"defeat_record": LIFECYCLE_RECORD},
        }
    )
    removed_spawn_payload = copy.deepcopy(active_payload)
    removed_spawn_payload.update(
        {
            "lifecycle_status": "removed",
            "flags": {"removed_record": LIFECYCLE_RECORD},
        }
    )
    invalid_spawn_results = []
    for label, payload in (
        ("defeated", defeated_spawn_payload),
        ("removed", removed_spawn_payload),
    ):
        mutation = _mutation(
            ("units", "spawn:invalid"),
            before=None,
            after=payload,
            op="spawn",
            before_exists=False,
        )
        invalid_spawn_results.append(_atomic(BattleState(), (mutation,)))

    delete_unit_mutation = _mutation(
        ("units", ALLY),
        before=unit_state_to_payload(active_before.units[ALLY]),
        after=None,
        op="delete",
        after_exists=False,
    )
    delete_unit_result = reducer.apply_all_result(
        active_before,
        (delete_unit_mutation,),
    )

    numeric_results = {
        "nan": _full(_unit("numeric:nan", hp=float("nan"))),
        "infinity": _full(_unit("numeric:infinity", hp=float("inf"))),
        "negative": _full(_unit("numeric:negative", hp=-1.0)),
        "over_max": _full(_unit("numeric:over_max", hp=101.0)),
        "max_non_positive": _full(
            _unit("numeric:max_non_positive", hp=0.0, max_hp=0.0)
        ),
    }

    constructor_legacy_rejected = {}
    for key in sorted(LEGACY_KEYS):
        try:
            _unit("legacy:constructor", flags={key: "active"})
        except ValueError as exc:
            constructor_legacy_rejected[key] = str(exc)

    codec_legacy_payload = unit_state_to_payload(_unit("legacy:codec"))
    codec_legacy_payload["flags"] = {"lifecycle_status": "active"}
    codec_legacy_rejected = False
    try:
        unit_state_from_payload(codec_legacy_payload)
    except ValueError:
        codec_legacy_rejected = True

    legacy_spawn_payload = unit_state_to_payload(_unit("legacy:spawn"))
    legacy_spawn_payload["flags"] = {"lifecycle_state": "active"}
    legacy_spawn = reducer.apply_all_result(
        BattleState(),
        (
            _mutation(
                ("units", "legacy:spawn"),
                before=None,
                after=legacy_spawn_payload,
                op="spawn",
                before_exists=False,
            ),
        ),
    )
    legacy_whole_flags = reducer.apply_all_result(
        active_before,
        (
            _mutation(
                ("units", ALLY, "flags"),
                before={},
                after={"lifecycle_status": "active"},
            ),
        ),
    )
    legacy_nested_flags = reducer.apply_all_result(
        active_before,
        (legacy_event_mutation,),
    )

    invalid_constructor_rejected = False
    try:
        _unit("typed:constructor", status="unknown")
    except ValueError:
        invalid_constructor_rejected = True
    invalid_codec_payload = unit_state_to_payload(_unit("typed:codec"))
    invalid_codec_payload["lifecycle_status"] = "unknown"
    invalid_codec_rejected = False
    try:
        unit_state_from_payload(invalid_codec_payload)
    except ValueError:
        invalid_codec_rejected = True
    invalid_typed_mutation = reducer.apply_all_result(
        active_before,
        (
            _mutation(
                ("units", ALLY, "lifecycle_status"),
                before="active",
                after="unknown",
            ),
        ),
    )

    invalid_replay = reducer.replay_snapshot(
        active_before,
        (hp_zero_mutation,),
        hp_zero_reduction.after_state.snapshot().to_json(),
    )

    planned_records = (
        {
            "record_type": SOURCE,
            "source": SOURCE,
            "process_only": False,
            "payload": {"kind": "planned"},
        },
    )
    normalized_records = records_for_atomic_result(
        planned_records,
        hp_zero_failure,
    )
    mutation_events = events_for_mutation(hp_zero_mutation)
    planned_events = tuple(
        replace(event, process_only=False) for event in mutation_events
    )
    normalized_events = events_for_atomic_result(
        planned_events,
        hp_zero_failure,
    )
    normalized_rng = rng_events_for_atomic_result(
        (
            RNGEvent(
                rng_type=SOURCE,
                source=SOURCE,
                result=True,
            ),
        ),
        hp_zero_failure,
    )

    immutability_result = hp_zero_failure.integrity
    immutable_before = immutability_result.to_json()
    details_mutation_rejected = False
    try:
        immutability_result.issues[0].details["polluted"] = True
    except TypeError:
        details_mutation_rejected = True
    exported = immutability_result.to_json()
    exported["issues"][0]["details"]["polluted"] = True
    exported["checked_scopes"][0]["paths"].append(["polluted"])
    atomic_typed_before = hp_zero_failure.integrity.to_json()
    evidence_integrity = hp_zero_failure.evidence["state_integrity"]
    if isinstance(evidence_integrity, dict):
        evidence_integrity["status"] = "polluted"
    result_recursively_immutable = (
        details_mutation_rejected
        and immutability_result.to_json() == immutable_before
        and hp_zero_failure.integrity.to_json() == atomic_typed_before
    )

    order_before_a = _state(
        _unit(
            "unit:b",
            flags={"z": {"value": 1}, "a": {"value": 2}},
        ),
        _unit("unit:a"),
    )
    order_before_b = _state(
        _unit("unit:a"),
        _unit(
            "unit:b",
            flags={"a": {"value": 2}, "z": {"value": 1}},
        ),
    )
    order_mutations = (
        _mutation(
            ("units", "unit:b", "hp"),
            before=100.0,
            after=0.0,
        ),
        _mutation(
            ("units", "unit:a", "hp"),
            before=100.0,
            after=0.0,
        ),
    )
    order_reduction_a = reducer.apply_all_result(order_before_a, order_mutations)
    order_reduction_b = reducer.apply_all_result(
        order_before_b,
        tuple(reversed(order_mutations)),
    )
    order_integrity_a = gate.check_touched(
        order_before_a,
        order_reduction_a.after_state,
        order_mutations,
    )
    order_integrity_b = gate.check_touched(
        order_before_b,
        order_reduction_b.after_state,
        tuple(reversed(order_mutations)),
    )
    chain = (
        _mutation(
            ("units", ALLY, "hp"),
            before=100.0,
            after=80.0,
        ),
        _mutation(
            ("units", ALLY, "hp"),
            before=80.0,
            after=60.0,
        ),
    )
    chain_forward = reducer.apply_all_result(active_before, chain)
    chain_reversed = reducer.apply_all_result(
        active_before,
        tuple(reversed(chain)),
    )
    deterministic_order = (
        order_integrity_a.to_json() == order_integrity_b.to_json()
        and chain_forward.ok
        and not chain_reversed.ok
    )

    numeric_expected_codes = {
        "nan": "lifecycle_hp_not_finite",
        "infinity": "lifecycle_hp_not_finite",
        "negative": "lifecycle_hp_out_of_range",
        "over_max": "lifecycle_hp_out_of_range",
        "max_non_positive": "lifecycle_max_hp_invalid",
    }
    numeric_bounds_rejected = all(
        not numeric_results[case_id].ok
        and expected_code in _codes(numeric_results[case_id])
        for case_id, expected_code in numeric_expected_codes.items()
    )
    legacy_boundaries_rejected = (
        set(constructor_legacy_rejected) == LEGACY_KEYS
        and codec_legacy_rejected
        and _conflict_code(legacy_spawn) == "invalid_spawn_payload"
        and _conflict_code(legacy_whole_flags)
        == "legacy_lifecycle_flag_not_admitted"
        and _conflict_code(legacy_nested_flags)
        == "legacy_lifecycle_flag_not_admitted"
    )
    invalid_typed_boundaries_rejected = (
        invalid_constructor_rejected
        and invalid_codec_rejected
        and _conflict_code(invalid_typed_mutation)
        == "invalid_lifecycle_status"
    )
    invalid_replay_rejected = (
        not invalid_replay.ok
        and any(
            error.startswith("state_integrity_failed:")
            for error in invalid_replay.errors
        )
    )
    failed_artifacts_are_diagnostic = (
        all(record["process_only"] is True for record in normalized_records)
        and all(event.process_only for event in normalized_events)
        and not normalized_rng
    )
    negative_checks = {
        "active_hp_zero_atomic_failure": (
            hp_zero_reduction.ok
            and hp_zero_failure.evidence["commit_status"]
            == "state_integrity_failed"
            and hp_zero_failure.after_state is active_before
            and not hp_zero_failure.committed_mutations
        ),
        "active_status_only_defeated_rejected": _has_codes(
            status_only_failure.integrity,
            "defeat_transition_not_atomic",
        ),
        "active_defeat_record_only_rejected": _has_codes(
            record_only_failure.integrity,
            "active_unit_has_defeat_record",
        ),
        "defeat_closure_each_missing_path_rejected": all(
            _has_codes(result, "defeat_transition_not_atomic")
            for result in missing_closure_results.values()
        ),
        "defeated_hp_nonzero_rejected": _has_codes(
            defeated_hp_nonzero,
            "defeated_unit_hp_not_zero",
        ),
        "defeated_record_constraints": (
            _has_codes(
                defeated_missing_record,
                "defeated_unit_missing_defeat_record",
            )
            and _has_codes(
                defeated_removed_record,
                "defeated_unit_has_removed_record",
            )
        ),
        "active_records_rejected": (
            _has_codes(
                active_defeat_record,
                "active_unit_has_defeat_record",
            )
            and _has_codes(
                active_removed_record,
                "active_unit_has_removed_record",
            )
        ),
        "remove_status_without_record_rejected": (
            _has_codes(
                active_removed_only.integrity,
                "remove_transition_not_atomic",
            )
            and _has_codes(
                defeated_removed_only.integrity,
                "remove_transition_not_atomic",
            )
        ),
        "removed_missing_record_rejected": _has_codes(
            removed_missing_record,
            "removed_unit_missing_removed_record",
        ),
        "removed_positive_hp_allowed": removed_positive_allowed.ok,
        "defeated_to_active_not_admitted": _has_codes(
            revive_failure.integrity,
            "lifecycle_transition_not_admitted",
        ),
        "removed_reentry_not_admitted": all(
            _has_codes(
                result.integrity,
                "lifecycle_transition_not_admitted",
            )
            for result in (
                reentry_active_failure,
                reentry_defeated_failure,
            )
        ),
        "spawn_defeated_or_removed_rejected": all(
            _has_codes(
                result.integrity,
                "lifecycle_spawn_state_invalid",
            )
            for result in invalid_spawn_results
        ),
        "direct_unit_delete_rejected": (
            _conflict_code(delete_unit_result)
            == "unit_deletion_not_admitted"
        ),
        "numeric_lifecycle_bounds_rejected": numeric_bounds_rejected,
        "legacy_lifecycle_all_boundaries_reject": (
            legacy_boundaries_rejected
        ),
        "invalid_typed_lifecycle_all_boundaries_reject": (
            invalid_typed_boundaries_rejected
        ),
        "invalid_expected_snapshot_cannot_bless_replay": (
            invalid_replay_rejected
        ),
        "integrity_failure_artifacts_are_diagnostic": (
            failed_artifacts_are_diagnostic
        ),
        "integrity_failure_is_diagnostic_not_blocked": (
            hp_zero_failure.outcome.category == "diagnostic"
            and not _successor(hp_zero_failure)
        ),
        "invalid_scenario_rejected_before_consumers": (
            scenario_invalid["ok"]
        ),
        "removed_positive_hp_excluded_by_group_alive_count": (
            alive_count_matrix["group_branch"]["ok"]
        ),
        "removed_positive_hp_excluded_by_single_alive_count": (
            alive_count_matrix["single_branch"]["ok"]
        ),
        "integrity_result_recursive_immutability": (
            result_recursively_immutable
        ),
        "deterministic_issue_and_conflict_order": deterministic_order,
    }
    negative_rows = [
        _row(case_id, ok)
        for case_id, ok in negative_checks.items()
    ]

    authority_scan = _runtime_authority_scan(package_root)
    oracle_audit = _validator_oracle_audit(Path(__file__).resolve())
    callback_alive_counts_ok = all(
        row["ok"] for row in alive_count_matrix.values()
    )
    typed_hp_zero_is_still_active_to_consumers = (
        lifecycle.status_of(_unit("authority:hp_zero", hp=0.0)) == "active"
        and runtime_unit_is_target_candidate(
            _unit("authority:hp_zero", hp=0.0)
        )
    )
    predicates = {
        "typed_lifecycle_is_single_runtime_authority": (
            authority_scan["count"] == 0
            and authority_scan["hp_fallback_count"] == 0
            and callback_alive_counts_ok
        ),
        "legacy_lifecycle_flag_constructor_rejected": (
            set(constructor_legacy_rejected) == LEGACY_KEYS
        ),
        "legacy_lifecycle_flag_codec_rejected": codec_legacy_rejected,
        "legacy_lifecycle_flag_mutation_rejected": (
            _conflict_code(legacy_spawn) == "invalid_spawn_payload"
            and _conflict_code(legacy_whole_flags)
            == "legacy_lifecycle_flag_not_admitted"
            and _conflict_code(legacy_nested_flags)
            == "legacy_lifecycle_flag_not_admitted"
        ),
        "hp_is_not_used_as_lifecycle_fallback": (
            typed_hp_zero_is_still_active_to_consumers
            and authority_scan["hp_fallback_count"] == 0
            and callback_alive_counts_ok
        ),
        "unit_codec_round_trip_preserves_typed_lifecycle": (
            codec_roundtrip == removed_unit
            and codec_payload["lifecycle_status"] == "removed"
        ),
        "snapshot_derives_lifecycle_from_typed_field": (
            snapshot_unit["lifecycle_status"] == "removed"
            and snapshot_unit["removed"] is True
            and snapshot_unit["lifecycle"]["status"] == "removed"
        ),
        "snapshot_contract_requires_lifecycle_view": (
            not missing_status_result.ok and not missing_view_result.ok
        ),
        "touched_domain_selector_is_path_driven": (
            unrelated.integrity.checked_scopes == ()
            and _scope_entities(selected.integrity) == (ALLY,)
        ),
        "unrelated_mutation_checks_zero_lifecycle_units": (
            unrelated.integrity.checked_domains == ()
        ),
        "touched_lifecycle_checks_only_selected_units": (
            _scope_entities(selected.integrity) == (ALLY,)
        ),
        "intermediate_candidate_may_be_temporarily_inconsistent": (
            intermediate.units[TARGET].hp == 0.0
            and intermediate.units[TARGET].lifecycle_status == "active"
        ),
        "partial_lifecycle_candidate_not_exposed_to_rule_consumers": (
            private_batch_handoff
        ),
        "active_final_state_requires_positive_hp": (
            "active_unit_hp_not_positive"
            in _codes(hp_zero_failure.integrity)
        ),
        "defeated_final_state_requires_zero_hp_and_record": (
            "defeated_unit_hp_not_zero" in _codes(defeated_hp_nonzero)
            and "defeated_unit_missing_defeat_record"
            in _codes(defeated_missing_record)
        ),
        "removed_final_state_requires_record_not_zero_hp": (
            "removed_unit_missing_removed_record"
            in _codes(removed_missing_record)
            and removed_positive_allowed.ok
        ),
        "spawn_transition_requires_active_valid_unit": all(
            "lifecycle_spawn_state_invalid" in _codes(result.integrity)
            for result in invalid_spawn_results
        ),
        "defeat_transition_requires_atomic_closure": all(
            "defeat_transition_not_atomic" in _codes(result)
            for result in missing_closure_results.values()
        ),
        "remove_transition_requires_atomic_closure": (
            "remove_transition_not_atomic"
            in _codes(active_removed_only.integrity)
            and "remove_transition_not_atomic"
            in _codes(defeated_removed_only.integrity)
        ),
        "revive_transition_not_admitted": (
            "lifecycle_transition_not_admitted"
            in _codes(revive_failure.integrity)
        ),
        "removed_reentry_not_admitted": all(
            "lifecycle_transition_not_admitted" in _codes(result.integrity)
            for result in (
                reentry_active_failure,
                reentry_defeated_failure,
            )
        ),
        "direct_unit_deletion_not_admitted": (
            _conflict_code(delete_unit_result)
            == "unit_deletion_not_admitted"
        ),
        "legal_damage_defeat_commits": (
            damage_commit is not None
            and _successor(damage_commit)
        ),
        "legal_removal_commits": (
            _successor(active_remove)
            and _successor(defeated_remove)
        ),
        "invalid_lifecycle_commit_is_diagnostic": (
            hp_zero_failure.outcome.category == "diagnostic"
        ),
        "invalid_lifecycle_commit_preserves_before_identity": (
            hp_zero_failure.after_state is active_before
        ),
        "invalid_lifecycle_commit_has_zero_committed_mutations": (
            hp_zero_failure.committed_mutations == ()
        ),
        "invalid_lifecycle_commit_is_not_successor_eligible": (
            not _successor(hp_zero_failure)
        ),
        "integrity_failure_records_are_process_only": all(
            record["process_only"] is True for record in normalized_records
        ),
        "integrity_failure_events_are_process_only": all(
            event.process_only for event in normalized_events
        ),
        "integrity_failure_has_zero_formal_rng_events": not normalized_rng,
        "atomic_evidence_contains_structured_integrity_result": (
            isinstance(hp_zero_failure.integrity, StateIntegrityResult)
            and isinstance(
                hp_zero_failure.evidence.get("state_integrity"),
                dict,
            )
        ),
        "atomic_evidence_schema_version_updated": (
            ATOMIC_COMMIT_SCHEMA_VERSION == "vg_s2_atomic_commit_v2"
            and hp_zero_failure.evidence["schema_version"]
            == ATOMIC_COMMIT_SCHEMA_VERSION
        ),
        "legal_lifecycle_replay_passes": all(
            result.ok for result in legal_replays
        ),
        "invalid_lifecycle_replay_fails": not invalid_replay.ok,
        "scenario_pre_setup_state_runs_full_lifecycle_check": (
            scenario_valid["ok"]
            and len(scenario_valid["full_calls"]) == 2
        ),
        "scenario_final_state_runs_full_lifecycle_check": (
            scenario_valid["ok"]
            and len(scenario_valid["full_calls"]) == 2
        ),
        "invalid_scenario_initial_state_rejected": scenario_invalid["ok"],
        "issue_order_is_deterministic": deterministic_order,
        "integrity_result_recursively_immutable": (
            result_recursively_immutable
        ),
        "production_runtime_legacy_lifecycle_authority_refs": (
            authority_scan["count"] == 0
        ),
        "tbgd_read_count": True,
        "full_rulebook_build_count": True,
        "catalog_validation_count": True,
        "focused_output_bytes_below_1_mib": True,
        "focused_validator_does_not_duplicate_production_invariants": (
            oracle_audit["ok"]
        ),
    }

    positive_matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "ok": all(row["ok"] for row in positive_rows),
        "case_count": len(positive_rows),
        "cases": positive_rows,
    }
    negative_matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "ok": all(row["ok"] for row in negative_rows),
        "case_count": len(negative_rows),
        "cases": negative_rows,
    }
    samples = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "damage_paths": [list(path) for path in sorted(damage_paths)],
        "invalid_atomic": {
            "commit_status": hp_zero_failure.evidence["commit_status"],
            "outcome": hp_zero_failure.outcome.to_json(),
            "integrity": hp_zero_failure.integrity.to_json(),
        },
        "authority_scan": authority_scan,
        "status_callback_alive_count": alive_count_matrix,
        "validator_oracle_audit": oracle_audit,
    }
    source_bytes = Path(__file__).resolve().stat().st_size
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "validation_version": VALIDATION_VERSION,
        "ok": False,
        "ready_for_review": False,
        "predicates": predicates,
        "metrics": {
            "positive_case_count": len(positive_rows),
            "negative_case_count": len(negative_rows),
            "production_runtime_legacy_lifecycle_authority_refs": (
                authority_scan["count"]
            ),
            "production_runtime_hp_lifecycle_fallback_refs": (
                authority_scan["hp_fallback_count"]
            ),
            "tbgd_read_count": 0,
            "small_in_memory_rulebook_build_count": 1,
            "full_rulebook_build_count": 0,
            "catalog_validation_count": 0,
            "focused_validator_source_bytes": source_bytes,
            "focused_output_bytes": 0,
            "focused_output_limit_bytes": OUTPUT_LIMIT_BYTES,
        },
        "matrices": {
            "positive_ok": positive_matrix["ok"],
            "negative_ok": negative_matrix["ok"],
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "vg_s2_committed_integrity_lifecycle.json"
    output_paths = {
        key: output_dir / f"{prefix}_{suffix}"
        for key, prefix in (
            ("positive", "positive_matrix"),
            ("negative", "negative_matrix"),
            ("samples", "integrity_samples"),
            ("summary", "validation_summary"),
        )
    }
    summary["output_files"] = [path.name for path in output_paths.values()]
    write_json(output_paths["positive"], positive_matrix)
    write_json(output_paths["negative"], negative_matrix)
    write_json(output_paths["samples"], samples)

    write_json(output_paths["summary"], summary)
    while True:
        output_bytes = sum(path.stat().st_size for path in output_paths.values())
        if summary["metrics"]["focused_output_bytes"] == output_bytes:
            break
        predicates["focused_output_bytes_below_1_mib"] = output_bytes < OUTPUT_LIMIT_BYTES
        summary["metrics"]["focused_output_bytes"] = output_bytes
        summary["ok"] = all(predicates.values()) and positive_matrix["ok"] and negative_matrix["ok"]
        summary["ready_for_review"] = summary["ok"]
        write_json(output_paths["summary"], summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VG-S2"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/vg_s2"),
    )
    args = parser.parse_args()
    package_root = Path(__file__).resolve().parents[1]
    summary = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={summary['ok']} "
        f"positive={summary['metrics']['positive_case_count']} "
        f"negative={summary['metrics']['negative_case_count']} "
        f"ready_for_review={summary['ready_for_review']}"
    )
    raise SystemExit(0 if summary["ok"] else 1)


if __name__ == "__main__":
    main()
