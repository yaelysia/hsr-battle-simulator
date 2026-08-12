from __future__ import annotations

import argparse
import json
import resource
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable

from ..rules.ir import CanonicalIR
from ..tbgd import task_graph_materializer as materializer_module
from ..tbgd.lowering import (
    TBGDLowering,
    _assign_character_ability_invocation_roles,
    _link_status_trigger_ability_graphs,
    _status_trigger_ability_phase_roots,
)
from ..tbgd.task_graph_materializer import materialize_ability_task_graph_catalog


DEFAULT_TBGD = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"


def _dedupe(values: Iterable[Any], identity: str) -> tuple[Any, ...]:
    result: dict[str, Any] = {}
    for value in values:
        key = getattr(value, identity)
        previous = result.get(key)
        if previous is not None and previous != value:
            raise ValueError(f"focused definition conflict:{identity}:{key}")
        result[key] = value
    return tuple(result[key] for key in sorted(result))


def _raises(action: Callable[[], object]) -> bool:
    try:
        action()
    except (TypeError, ValueError):
        return True
    return False


def _source_key(value: Any) -> tuple[str, str]:
    return value.source.source_path, str(value.source.evidence.get("json_path") or "")


def validate(tbgd_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    counters = defaultdict(int)
    original_build = TBGDLowering.build
    original_prepare = materializer_module._prepare_materialization

    def forbidden_build(_self: TBGDLowering) -> object:
        counters["full_canonical_build"] += 1
        raise AssertionError("S8B5B must not build full CanonicalIR")

    def counted_prepare(*args: Any, **kwargs: Any) -> Any:
        counters["materialization_prepare"] += 1
        return original_prepare(*args, **kwargs)

    TBGDLowering.build = forbidden_build
    materializer_module._prepare_materialization = counted_prepare
    try:
        lowering = TBGDLowering(tbgd_root)
        source_graph = lowering.build_character_ability_source_graph_catalog()
        snapshot = lowering._character_ability_raw_snapshot
        scope = lowering._character_ability_scope_catalog
        controls = lowering.build_character_control_flow_contract_catalog(
            snapshot=snapshot, scope_catalog=scope
        )
        context = lowering._character_formal_task_source_context()
        priorities = lowering._lower_queue_priorities()
        priority_lookup = {
            (item.priority_table, item.priority_key): item
            for item in priorities
            if item.coverage_status == "executable"
        }
        callbacks: list[Any] = []
        tasks: list[Any] = []
        effects: list[Any] = []
        conditions: list[Any] = []
        targets: list[Any] = []
        for order, source in enumerate(snapshot.sources):
            relative = source.source.source_path
            lowered = lowering._lower_ability_file(
                tbgd_root / relative,
                priority_lookup,
                ability_file_order=order,
                raw_document=snapshot.documents[relative],
                formal_status_source_context=context,
            )
            callbacks.extend(lowered.status_callbacks)
            tasks.extend(lowered.status_callback_tasks)
            effects.extend(lowered.effects)
            conditions.extend(lowered.conditions)
            targets.extend(lowered.target_expressions)

        callback_by_id = {item.callback_id: item for item in callbacks}
        if len(callback_by_id) != len(callbacks):
            raise ValueError("focused status callback identities are not unique")
        effects_by_id = {item.effect_id: item for item in effects}
        trigger_names = {
            standard.get("ability_name")
            for task in tasks
            if task.opcode == "TriggerAbility"
            and (effect := effects_by_id.get(task.effect_id)) is not None
            and isinstance((standard := effect.payload.get("standard")), dict)
            and isinstance(standard.get("ability_name"), str)
        }
        trigger_paths = {
            item.source.source_path
            for item in source_graph.definitions
            if item.ability_name in trigger_names
        }
        standalone = lowering._lower_standalone_ability_graphs(
            [tbgd_root / path for path in sorted(trigger_paths)]
        )
        graphs, phases, ability_tasks, extra_effects, extra_conditions, _, extra_targets = standalone
        effects.extend(extra_effects)
        conditions.extend(extra_conditions)
        targets.extend(extra_targets)
        linked_tasks = _link_status_trigger_ability_graphs(tasks, callbacks, effects, graphs)
        parent_snapshot = (
            tuple((item.task_id, item.coverage_status, item.blocked_reason) for item in linked_tasks),
            tuple(
                (item.callback_id, item.coverage_status, item.blocked_reason)
                for item in callbacks
            ),
        )
        assigned_phases = _assign_character_ability_invocation_roles(
            phases,
            ability_tasks,
            graphs,
            [],
            status_callback_tasks=linked_tasks,
            status_callbacks=callbacks,
        )
        view = CanonicalIR(
            version="p9_s8b5b_focused",
            ability_phases=tuple(assigned_phases),
            ability_tasks=tuple(ability_tasks),
            standalone_ability_graphs=tuple(graphs),
            status_callbacks=tuple(callbacks),
            status_callback_tasks=tuple(linked_tasks),
            effects=_dedupe(effects, "effect_id"),
            conditions=_dedupe(conditions, "condition_id"),
            target_expressions=_dedupe(targets, "target_expression_id"),
        )
        catalog = materialize_ability_task_graph_catalog(
            controls, view, source_snapshot=snapshot
        )
    finally:
        TBGDLowering.build = original_build
        materializer_module._prepare_materialization = original_prepare

    avatar_callbacks = {
        item.callback_id: item
        for item in callbacks
        if item.source_mode == "mainline_avatar_ability"
    }
    callback_prefixes = {
        (
            item.source.source_path,
            str(item.source.evidence.get("callback_json_path") or ""),
        )
        for item in avatar_callbacks.values()
    }
    raw_denominator = {
        _source_key(node)
        for node in controls.nodes
        if node.family == "TriggerAbility"
        and any(
            node.source.source_path == source_path
            and str(node.source.evidence.get("json_path") or "").startswith(prefix)
            for source_path, prefix in callback_prefixes
            if prefix
        )
    }
    avatar_trigger_tasks = tuple(
        item
        for item in linked_tasks
        if item.opcode == "TriggerAbility" and item.callback_id in avatar_callbacks
    )
    typed_denominator = {_source_key(item) for item in avatar_trigger_tasks}
    graphs_by_id = {item.standalone_ability_graph_id: item for item in graphs}
    phases_by_id = {item.phase_id: item for item in assigned_phases}
    graph_by_phase = {
        phase_id: graph for graph in graphs for phase_id in graph.phase_ids
    }
    target_phase_ids = {
        phase_id
        for task in avatar_trigger_tasks
        for phase_id in (
            graphs_by_id[task.linked_standalone_graph_id].phase_ids
            if task.linked_standalone_graph_id in graphs_by_id
            else (task.linked_ability_phase_id,)
        )
        if phase_id
    }
    entries_by_phase = defaultdict(list)
    for entry in catalog.entry_materializations:
        entries_by_phase[entry.owner_id].append(entry)
    blocked_parents = tuple(
        item
        for item in avatar_trigger_tasks
        if item.coverage_status != "executable"
        or avatar_callbacks[item.callback_id].coverage_status != "executable"
    )
    parent_after = (
        tuple((item.task_id, item.coverage_status, item.blocked_reason) for item in linked_tasks),
        tuple(
            (item.callback_id, item.coverage_status, item.blocked_reason)
            for item in callbacks
        ),
    )
    external_targets = {
        phase_id
        for task in linked_tasks
        if task.opcode == "TriggerAbility"
        and task.callback_id not in avatar_callbacks
        and task.linked_standalone_graph_id in graphs_by_id
        for phase_id in graphs_by_id[task.linked_standalone_graph_id].phase_ids
    }
    root_graphs = {
        item.standalone_ability_graph_id: item for item in graphs
    }
    root_phases = {item.phase_id: item for item in phases}
    root_by_phase = {
        phase_id: graph for graph in graphs for phase_id in graph.phase_ids
    }
    sample_task = avatar_trigger_tasks[0]
    sample_owner = avatar_callbacks[sample_task.callback_id]
    missing_target_rejected = _raises(
        lambda: _status_trigger_ability_phase_roots(
            root_phases,
            root_graphs,
            root_by_phase,
            [replace(sample_task, linked_standalone_graph_id="missing", linked_ability_phase_id="")],
            [sample_owner],
        )
    )
    external_owner_ignored = not _status_trigger_ability_phase_roots(
        root_phases,
        root_graphs,
        root_by_phase,
        [sample_task],
        [replace(sample_owner, source_mode="mainline_equipment_ability")],
    )
    predicates = {
        "all_status_trigger_ability_links_are_typed": bool(raw_denominator)
        and raw_denominator == typed_denominator
        and all(bool(item.linked_standalone_graph_id) ^ bool(item.linked_ability_phase_id) for item in avatar_trigger_tasks),
        "status_linked_phases_are_nested_only": bool(target_phase_ids)
        and all(phases_by_id[item].invocation_role == "nested_only" for item in target_phase_ids),
        "status_linked_phases_are_not_root_entries": all(
            phases_by_id[item].invocation_role not in {"action_root", "standalone_root"}
            for item in target_phase_ids
        ),
        "blocked_parent_does_not_delete_nested_definition": bool(blocked_parents)
        and all(entries_by_phase[item] for item in target_phase_ids),
        "blocked_parent_is_not_promoted_to_executable": parent_snapshot == parent_after,
        "external_content_not_claimed_by_character_catalog": external_owner_ignored
        and all(
            item in target_phase_ids or phases_by_id[item].invocation_role != "nested_only"
            for item in external_targets
        ),
        "missing_or_ambiguous_target_fails_closed": missing_target_rejected,
        "full_canonical_ir_build_count": counters["full_canonical_build"] == 0,
    }
    source_matrix = [
        {
            "task_id": item.task_id,
            "source_path": item.source.source_path,
            "json_path": item.source.evidence.get("json_path"),
            "parent_status": item.coverage_status,
            "target_phase_ids": list(
                graphs_by_id[item.linked_standalone_graph_id].phase_ids
                if item.linked_standalone_graph_id
                else (item.linked_ability_phase_id,)
            ),
        }
        for item in avatar_trigger_tasks
    ]
    return {
        "ok": all(predicates.values()),
        "predicates": predicates,
        "manual_review_required": {"runtime_behavior_changed": False},
        "counts": {
            "raw_status_trigger_count": len(raw_denominator),
            "typed_status_trigger_count": len(typed_denominator),
            "nested_phase_count": len(target_phase_ids),
            "nested_entry_count": sum(len(entries_by_phase[item]) for item in target_phase_ids),
            "blocked_parent_count": len(blocked_parents),
            **dict(counters),
        },
        "source_matrix": source_matrix,
        "elapsed_seconds": time.monotonic() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.tbgd_root.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "validation_summary_p9_s8b5b.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
