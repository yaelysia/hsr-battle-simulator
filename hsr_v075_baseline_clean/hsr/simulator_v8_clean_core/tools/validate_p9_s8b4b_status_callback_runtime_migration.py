from __future__ import annotations

import argparse
import json
import resource
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..core.model import BattleState, UnitState
from ..ir_types import IRSource
from ..rules.ir import CanonicalIR, StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..systems.damage import DamageWindowLedger
from ..systems.status_callbacks import (
    StatusCallbackExecutionResult,
    StatusCallbackSystem,
)
from ..systems.target import TargetExpressionResult
from ..systems.task_graph import TaskGraphExecutor, TaskGraphLeafResult
from ..tbgd.lowering import TBGDLowering
from ..tbgd.task_graph_materializer import materialize_status_callback_task_graph


@dataclass(frozen=True)
class _RealCase:
    rules: RuleBook
    callback: StatusCallbackIR
    opcodes: tuple[str, ...]


class _CountingExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.delegate = TaskGraphExecutor()

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return self.delegate.execute(*args, **kwargs)


def _state() -> BattleState:
    return BattleState(
        units={
            "owner": UnitState("owner", "ally", "avatar:fixture"),
            "target": UnitState("target", "enemy", "monster:fixture"),
        }
    )


def _detail(callback: StatusCallbackIR, *, ledger: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "instance_id": "status:fixture",
        "status_id": "status:fixture",
        "owner_id": "owner",
        "caster_id": "owner",
        "modifier_name": callback.modifier_name,
        "source_trace": {"kind": "validation_fixture"},
    }
    if ledger:
        result["trigger_ids_by_event"] = {callback.event: [callback.callback_id]}
    return result


def _taskless_rules(
    source_mode: str,
    *,
    property_range: bool = False,
) -> tuple[RuleBook, StatusCallbackIR]:
    event = "OnAbilityPropertyRangeEnter" if property_range else "OnProbe"
    evidence: dict[str, Any] = {
        "json_path": "$.callback",
        "callback_json_path": "$.callback",
        "content_sha256": "a" * 64,
    }
    if property_range:
        evidence.update(
            {
                "ability_property_watcher_id": "watcher:fixture",
                "ability_property_range_id": "range:fixture",
                "ability_property_range_branch": "OnEnterRange",
            }
        )
    callback = StatusCallbackIR(
        f"status_callback:fixture:{source_mode}:{event}",
        "ModifierFixture",
        event,
        (),
        IRSource(
            "validation_fixture/status_callback.json",
            "StatusCallback",
            event,
            evidence,
        ),
        (0, 0),
        "executable",
        scope_kind="ability_property_range" if property_range else "status_local",
        source_mode=source_mode,
        admission_status="executable",
    )
    return RuleBook(CanonicalIR("p9_s8b4b_taskless", status_callbacks=(callback,))), callback


def _build_real_cases(tbgd_root: Path) -> tuple[dict[str, _RealCase], dict[str, Any]]:
    lowering = TBGDLowering(tbgd_root)
    lowering.build_character_ability_source_graph_catalog()
    snapshot = lowering._character_ability_raw_snapshot
    controls = lowering.build_character_control_flow_contract_catalog(
        snapshot=snapshot,
        scope_catalog=lowering._character_ability_scope_catalog,
    )
    context = lowering._character_formal_task_source_context()
    priorities = {
        (item.priority_table, item.priority_key): item
        for item in lowering._lower_queue_priorities()
        if item.coverage_status == "executable"
    }
    selected: dict[str, tuple[tuple[Any, ...], Any, Any, tuple[Any, ...]]] = {}
    for order, source in enumerate(snapshot.sources):
        relative = source.source.source_path
        lowered = lowering._lower_ability_file(
            tbgd_root / relative,
            priorities,
            ability_file_order=order,
            raw_document=snapshot.documents[relative],
            formal_status_source_context=context,
        )
        by_callback: dict[str, list[Any]] = {}
        for task in lowered.status_callback_tasks:
            by_callback.setdefault(task.callback_id, []).append(task)
        for callback in lowered.status_callbacks:
            tasks = tuple(by_callback.get(callback.callback_id, ()))
            if callback.coverage_status != "executable" or not tasks:
                continue
            opcodes = tuple(task.opcode for task in tasks)
            kinds = []
            if (
                len(tasks) == 1
                and tasks[0].coverage_status == "executable"
                and tasks[0].opcode
                not in {
                    "PredicateTaskList",
                    "Retarget",
                    "IncludeTaskListTemplate",
                    "LoopExecuteTaskList",
                    "RandomConfig",
                    "Remodifier",
                    "TriggerAbility",
                }
            ):
                kinds.append("leaf")
            if (
                "Retarget" in opcodes
                and all(task.coverage_status == "executable" for task in tasks)
                and all(
                    task.task_payload.get("ByRandom") is not True
                    for task in tasks
                    if task.opcode == "Retarget"
                )
            ):
                kinds.append("retarget")
            if "Remodifier" in opcodes:
                kinds.append("remodifier")
            if "RandomConfig" in opcodes:
                kinds.append("random")
            for kind in kinds:
                key = (len(tasks), relative, callback.callback_id)
                if kind not in selected or key < selected[kind][0]:
                    selected[kind] = (key, lowered, callback, tasks)
    if set(selected) != {"leaf", "retarget", "remodifier", "random"}:
        raise AssertionError(f"real status callback shapes are incomplete:{sorted(selected)}")

    cases: dict[str, _RealCase] = {}
    for kind, (_key, lowered, callback, tasks) in selected.items():
        effect_ids = {task.effect_id for task in tasks if task.effect_id}
        condition_ids = {task.condition_id for task in tasks if task.condition_id}
        target_ids = {task.target_expression_id for task in tasks if task.target_expression_id}
        view = CanonicalIR(
            f"p9_s8b4b_{kind}",
            status_callbacks=(callback,),
            status_callback_tasks=tasks,
            effects=tuple(item for item in lowered.effects if item.effect_id in effect_ids),
            conditions=tuple(item for item in lowered.conditions if item.condition_id in condition_ids),
            target_expressions=tuple(
                item
                for item in lowered.target_expressions
                if item.target_expression_id in target_ids
            ),
        )
        catalog = materialize_status_callback_task_graph(
            controls,
            view,
            callback_id=callback.callback_id,
            source_snapshot=snapshot,
        )
        cases[kind] = _RealCase(
            RuleBook(replace(view, task_graph_catalog=catalog)),
            callback,
            tuple(sorted(task.opcode for task in tasks)),
        )
    return cases, {
        kind: {
            "callback_id": case.callback.callback_id,
            "source_path": case.callback.source.source_path,
            "task_count": len(case.opcodes),
            "opcodes": list(case.opcodes),
        }
        for kind, case in sorted(cases.items())
    }


def _execute(system: StatusCallbackSystem, case: _RealCase):
    return system.execute(
        _state(),
        unit_id="owner",
        modifier_name=case.callback.modifier_name,
        event=case.callback.event,
        detail_override=_detail(case.callback),
    )


def _graph_nodes(case: _RealCase, opcode: str) -> tuple[Any, ...]:
    entry = case.rules.query_task_graph_entry(
        "status_callback", case.callback.callback_id, case.callback.event
    )
    graph = case.rules.query_task_graph(entry.value.graph_id)
    return tuple(node for node in graph.value.nodes if node.opcode == opcode)


def _no_legacy(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("formal status callback reached the legacy child interpreter")


def validate(tbgd_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    cases, source_selection = _build_real_cases(tbgd_root)

    leaf_system = StatusCallbackSystem(cases["leaf"].rules)
    counter = _CountingExecutor()
    leaf_system.task_graph_executor = counter
    leaf_system._execute_child_sequence = _no_legacy
    leaf_system._execute_formal_leaf_task = (
        lambda state, *_args, **_kwargs: StatusCallbackExecutionResult(True, state)
    )
    leaf = _execute(leaf_system, cases["leaf"])

    retarget_system = StatusCallbackSystem(cases["retarget"].rules)
    retarget_system._execute_child_sequence = _no_legacy
    leaf_targets: list[str] = []
    def scoped_leaf(state: BattleState, *_args: Any) -> StatusCallbackExecutionResult:
        leaf_targets.append(_args[-2].target_id)
        return StatusCallbackExecutionResult(True, state)
    retarget_system._execute_formal_leaf_task = scoped_leaf
    retarget_system._resolve_retarget_targets = lambda *_args, **_kwargs: (
        TargetExpressionResult("resolved", target_ids=("target", "owner"))
    )
    retarget = _execute(retarget_system, cases["retarget"])

    empty_system = StatusCallbackSystem(cases["retarget"].rules)
    empty_system._execute_formal_leaf_task = lambda state, *_: StatusCallbackExecutionResult(
        True, state
    )
    empty_system._resolve_retarget_targets = lambda *_args, **_kwargs: (
        TargetExpressionResult("resolved")
    )
    empty = _execute(empty_system, cases["retarget"])

    blocked_system = StatusCallbackSystem(cases["retarget"].rules)
    blocked_system._resolve_retarget_targets = lambda *_args, **_kwargs: (
        TargetExpressionResult("blocked", blocked_reason="fixture_target_blocked")
    )
    blocked_state = _state()
    blocked = blocked_system.execute(
        blocked_state,
        unit_id="owner",
        modifier_name=cases["retarget"].callback.modifier_name,
        event=cases["retarget"].callback.event,
        detail_override=_detail(cases["retarget"].callback),
    )
    ledger = DamageWindowLedger()
    ledger_system = StatusCallbackSystem(cases["leaf"].rules)
    def blocked_leaf(*args: Any) -> TaskGraphLeafResult:
        args[-1].defeated_targets["target"] = {"target_id": "target"}
        return TaskGraphLeafResult(
            "blocked", outcome_kind="", blocked_reason="fixture_leaf_blocked"
        )
    ledger_system._execute_formal_status_leaf = blocked_leaf
    ledger_failure = ledger_system.execute(
        _state(),
        unit_id="owner",
        modifier_name=cases["leaf"].callback.modifier_name,
        event=cases["leaf"].callback.event,
        damage_window_ledger=ledger,
        detail_override=_detail(cases["leaf"].callback),
    )

    range_rules, range_callback = _taskless_rules(
        "mainline_avatar_ability", property_range=True
    )
    range_system = StatusCallbackSystem(range_rules)
    range_detail = _detail(range_callback)
    normal_range = range_system.execute(
        _state(),
        unit_id="owner",
        modifier_name=range_callback.modifier_name,
        event=range_callback.event,
        detail_override=range_detail,
    )
    selected_range = range_system.execute_callback_id(
        _state(),
        callback_id=range_callback.callback_id,
        watcher_id="watcher:fixture",
        range_id="range:fixture",
        branch="enter",
        unit_id="owner",
        modifier_name=range_callback.modifier_name,
        detail_override=range_detail,
    )
    missing_ledger = range_system.execute(
        _state(),
        unit_id="owner",
        modifier_name=range_callback.modifier_name,
        event=range_callback.event,
        detail_override=_detail(range_callback, ledger=False),
    )

    external_rules, external_callback = _taskless_rules("mainline_global_modifier")
    external = StatusCallbackSystem(external_rules).execute(
        _state(),
        unit_id="owner",
        modifier_name=external_callback.modifier_name,
        event=external_callback.event,
        detail_override=_detail(external_callback),
    )
    unknown_rules, unknown_callback = _taskless_rules("validation_fixture")
    unknown = StatusCallbackSystem(unknown_rules).execute(
        _state(),
        unit_id="owner",
        modifier_name=unknown_callback.modifier_name,
        event=unknown_callback.event,
        detail_override=_detail(unknown_callback),
    )

    random_nodes = _graph_nodes(cases["random"], "RandomConfig")
    remodifier_nodes = _graph_nodes(cases["remodifier"], "Remodifier")
    nested_hook = leaf_system._formal_status_hooks(
        cases["leaf"].callback,
        _detail(cases["leaf"].callback),
        None,
        None,
    ).graph
    nested = nested_hook(None, _state()) if nested_hook is not None else None

    checks = {
        "character_status_callback_uses_shared_executor_only": leaf.ok
        and counter.calls == 1
        and not any(item.get("record_type") == "status_callback_legacy_route" for item in leaf.records),
        "formal_status_leaf_has_no_child_runner": leaf.ok and bool(leaf.node_results),
        "retarget_and_deterministic_selection_do_not_execute_children": retarget.ok
        and leaf_targets == ["target", "owner"],
        "empty_targets_blocked_targets_and_resolution_failure_are_distinct": empty.ok
        and not blocked.ok
        and blocked.errors == ("fixture_target_blocked",),
        "selected_callback_failure_is_atomic": blocked.after_state is blocked_state
        and not blocked.mutations
        and not blocked.events
        and not blocked.rng_events
        and not ledger_failure.ok
        and not ledger.defeated_targets,
        "all_formal_callers_share_one_admission_boundary": normal_range.ok
        and selected_range.ok
        and not missing_ledger.ok,
        "external_content_legacy_path_is_explicit_and_bounded": external.ok
        and any(item.get("record_type") == "status_callback_legacy_route" for item in external.records)
        and not unknown.ok,
        "random_and_timing_nodes_remain_s8c_blocked": len(random_nodes) == 1
        and random_nodes[0].node_kind == "deferred"
        and random_nodes[0].materialization_status != "materialized",
        "remodifier_remains_s10_blocked": len(remodifier_nodes) == 1
        and remodifier_nodes[0].node_kind == "deferred"
        and remodifier_nodes[0].status_reason.endswith("status_lifecycle"),
        "nested_ability_requires_s8b5_context": nested is not None
        and nested.status == "blocked"
        and nested.blocked_reason.endswith("deferred_to_s8b5"),
        "real_source_graph_reaches_formal_executor": counter.calls == 1,
    }
    return {
        "ok": all(checks.values()),
        "predicates": checks,
        "source_selection": source_selection,
        "resource": {
            "wall_seconds": round(time.monotonic() - started, 3),
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.tbgd_root.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "validation_summary_p9_s8b4b_status_callback_runtime_migration.json"
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
