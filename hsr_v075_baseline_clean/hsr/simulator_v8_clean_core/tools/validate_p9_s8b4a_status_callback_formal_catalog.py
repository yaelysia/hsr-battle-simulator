from __future__ import annotations

import argparse
import gc
import json
import resource
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.character_control_flow_contracts import _at_path
from ..tbgd.lowering import (
    TBGDLowering, _link_status_trigger_ability_graphs, _short_gamecore_type,
    build_character_action_definition_ir,
)
from ..tbgd.task_graph_materializer import (
    _ordered_status_task_ids, _validate_status_callback_denominator,
    materialize_character_runtime_task_graph_catalog,
)
from ..tbgd import task_graph_materializer as materializer_module


DEFAULT_TBGD = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"


def _raises(action: Callable[[], object]) -> bool:
    try:
        action()
    except (KeyError, TypeError, ValueError): return True
    return False


def _dedupe(values: Iterable[Any], field: str) -> tuple[Any, ...]:
    result: dict[str, Any] = {}
    for value in values:
        identity = getattr(value, field)
        existing = result.get(identity)
        if existing is not None and existing != value:
            raise ValueError(f"focused definition conflict:{field}:{identity}")
        result[identity] = value
    return tuple(result[key] for key in sorted(result))


def _raw_callback_paths(document: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()

    def visit(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            callbacks = value.get("_CallbackList")
            if isinstance(callbacks, Sequence) and not isinstance(callbacks, str):
                for index, callback in enumerate(callbacks):
                    if isinstance(callback, Mapping):
                        result.add(f"{path}._CallbackList[{index}]")
            watchers = value.get("OnAbilityPropertyChange")
            if isinstance(watchers, Sequence) and not isinstance(watchers, str):
                for watcher_index, watcher in enumerate(watchers):
                    ranges = watcher.get("Ranges") if isinstance(watcher, Mapping) else None
                    if not isinstance(ranges, Sequence) or isinstance(ranges, str):
                        continue
                    for range_index, item in enumerate(ranges):
                        if not isinstance(item, Mapping):
                            continue
                        base = (
                            f"{path}.OnAbilityPropertyChange[{watcher_index}]"
                            f".Ranges[{range_index}]"
                        )
                        for branch in ("OnEnterRange", "OnExitRange"):
                            tasks = item.get(branch)
                            if (
                                isinstance(tasks, Sequence)
                                and not isinstance(tasks, str)
                                and tasks
                            ):
                                result.add(f"{base}.{branch}")
            for key, child in value.items():
                visit(child, f"{path}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, str):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(document, "$")
    return result


def _select_action_slice(
    lowering: TBGDLowering, source_graph: Any, snapshot: Any, scope: Any,
) -> CanonicalIR:
    definitions: dict[str, list[Any]] = defaultdict(list)
    for definition in build_character_action_definition_ir(lowering.tbgd_root):
        definitions[definition.action_id].append(definition)
    counts: dict[str, int] = defaultdict(int)
    for action in source_graph.action_sources:
        counts[action.action_id] += 1
    actions = sorted(
        source_graph.action_sources,
        key=lambda item: (item.action_id, item.owner_avatar_id),
    )
    for action in actions:
        if counts[action.action_id] != 1:
            continue
        for definition in sorted(
            definitions.get(action.action_id, ()), key=lambda item: item.level
        ):
            projection = lowering.build_character_action_ability_slice(
                definition,
                snapshot=snapshot,
                scope_catalog=scope,
                source_graph_catalog=source_graph,
            )
            if any(phase.invocation_role == "action_root" for phase in projection.ability_phases):
                return projection
    raise AssertionError("a real formal character action slice is required")


def validate(tbgd_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    counters = defaultdict(int)
    original_build = TBGDLowering.build
    original_prepare = materializer_module._prepare_materialization

    def forbidden_build(_self: TBGDLowering) -> object:
        counters["full_canonical_build"] += 1
        raise AssertionError("focused status catalog cannot build full CanonicalIR")

    def counted_prepare(*args: Any, **kwargs: Any) -> Any:
        counters["source_context_prepare"] += 1
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
        watchers: list[Any] = []
        raw_callback_keys: set[tuple[str, str]] = set()
        for order, source in enumerate(snapshot.sources):
            relative = source.source.source_path
            raw_callback_keys.update(
                (relative, path)
                for path in _raw_callback_paths(snapshot.documents[relative])
            )
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
            watchers.extend(lowered.ability_property_watchers)

        status_definition_ids_unique = (
            len(effects) == len({item.effect_id for item in effects})
            and len(conditions) == len({item.condition_id for item in conditions})
        )
        callback_keys = {
            (item.source.source_path, str(item.source.evidence.get("callback_json_path") or ""))
            for item in callbacks
        }
        effects_by_id = {item.effect_id: item for item in effects}
        trigger_names = {
            standard.get("ability_name")
            for task in tasks
            if task.opcode == "TriggerAbility"
            and (effect := effects_by_id.get(task.effect_id)) is not None
            and isinstance((standard := effect.payload.get("standard")), Mapping)
            and isinstance(standard.get("ability_name"), str)
        }
        trigger_paths = {
            item.source.source_path
            for item in source_graph.definitions
            if item.ability_name in trigger_names
        }
        standalone = lowering._lower_standalone_ability_graphs(
            tuple(tbgd_root / path for path in sorted(trigger_paths))
        )
        graphs, phases, ability_tasks, extra_effects, extra_conditions, _, extra_targets = standalone
        effects.extend(extra_effects)
        conditions.extend(extra_conditions)
        targets.extend(extra_targets)
        tasks = _link_status_trigger_ability_graphs(tasks, callbacks, effects, graphs)
        action = _select_action_slice(lowering, source_graph, snapshot, scope)
        view = CanonicalIR(
            version=action.version,
            action_ability_bindings=action.action_ability_bindings,
            ability_phases=_dedupe((*action.ability_phases, *phases), "phase_id"),
            ability_tasks=_dedupe((*action.ability_tasks, *ability_tasks), "task_id"),
            standalone_ability_graphs=tuple(graphs),
            status_callbacks=tuple(callbacks),
            status_callback_tasks=tuple(tasks),
            effects=_dedupe((*action.effects, *effects), "effect_id"),
            conditions=_dedupe((*action.conditions, *conditions), "condition_id"),
            target_expressions=_dedupe(
                (*action.target_expressions, *targets), "target_expression_id"
            ),
        )
        source_documents = context.documents
        del action, context, lowering, source_graph, scope, standalone, lowered
        gc.collect()
        catalog = materialize_character_runtime_task_graph_catalog(
            controls,
            view,
            source_snapshot=snapshot,
            definition_scope_complete=True,
        )
        installed = replace(view, task_graph_catalog=catalog)
        rules = RuleBook(installed)
    finally:
        TBGDLowering.build = original_build
        materializer_module._prepare_materialization = original_prepare

    status_entries = tuple(item for item in catalog.entry_materializations if item.entry_kind == "status_callback")
    ability_entries = tuple(item for item in catalog.entry_materializations if item.entry_kind == "ability_phase_callback")
    status_graphs = tuple(item for item in catalog.graphs if item.entry_kind == "status_callback")
    task_callbacks = {item.callback_id for item in tasks}
    taskless_callbacks = {item.callback_id for item in callbacks if item.callback_id not in task_callbacks}
    blocked_watcher_ids = {item.watcher_id for item in watchers if item.coverage_status == "blocked"}
    blocked_watcher_callbacks = tuple(
        item for item in callbacks
        if item.source.evidence.get("ability_property_watcher_id") in blocked_watcher_ids
    )
    reused_sources: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for task in tasks:
        reused_sources[(
            task.source.source_path,
            str(task.source.evidence.get("json_path") or ""),
            str(task.source.evidence.get("raw_opcode") or ""),
        )].append(task)
    reused = tuple(items for items in reused_sources.values() if len(items) > 1)
    source_exact = all(
        isinstance((raw := _at_path(source_documents[task.source.source_path], str(task.source.evidence["json_path"]))), Mapping)
        and _short_gamecore_type(raw.get("$type")) == task.source.evidence.get("raw_opcode") for task in tasks
    )
    entry_queries = tuple(
        rules.query_task_graph_entry(item.entry_kind, item.owner_id, item.callback_kind)
        for item in catalog.entry_materializations
    )
    graph_queries = tuple(rules.query_task_graph(item.graph_id) for item in catalog.graphs)
    predicates = {
        "raw_callback_denominator_matches_projection": raw_callback_keys == callback_keys
        and len(callbacks) == len(callback_keys),
        "status_callback_source_and_graph_positions_are_distinct": bool(reused) and all(
            task.source.evidence.get("json_path")
            and task.source.evidence.get("graph_task_path")
            for task in tasks
        ) and any(item.source.evidence["json_path"] != item.task_path for items in reused for item in items),
        "shared_template_expansions_have_unique_graph_positions": bool(reused) and all(
            len({item.task_id for item in items}) == len(items)
            and len({item.task_path for item in items}) == len(items)
            for items in reused
        ),
        "status_callback_task_topology_is_closed": sum(
            len(item.nodes) for item in status_graphs
        ) == len(tasks),
        "task_bearing_character_callbacks_have_exactly_one_entry": {
            item.owner_id for item in status_entries
        } == task_callbacks,
        "taskless_callbacks_have_no_synthetic_graph": bool(taskless_callbacks)
        and not taskless_callbacks.intersection(item.owner_id for item in status_entries),
        "blocked_watcher_branches_are_catalogued_but_not_admitted": bool(blocked_watcher_callbacks)
        and all(item.coverage_status == item.admission_status == "blocked" for item in blocked_watcher_callbacks),
        "status_callback_domain_follows_character_owner": all(
            item.source_mode == "mainline_avatar_ability" for item in callbacks
        ),
        "status_graphs_are_all_materialized": all(item.status == "materialized" for item in status_entries)
        and len(status_entries) == len({item.graph_id for item in status_entries}),
        "ability_and_status_entries_share_one_production_catalog": bool(ability_entries)
        and bool(status_entries),
        "status_entry_queries_are_unique_and_source_closed": all(
            item.status == "resolved" and item.value is not None for item in entry_queries
        ) and all(item.status == "resolved" and item.value is not None for item in graph_queries),
        "status_task_sources_reverse_to_raw": source_exact,
        "status_definition_graph_identities_are_unique": status_definition_ids_unique,
        "trigger_ability_references_are_closed": bool(trigger_names)
        and all(
            bool(item.linked_standalone_graph_id or item.linked_ability_phase_id)
            for item in tasks
            if item.opcode == "TriggerAbility"
        ),
        "catalog_build_prepares_source_once": counters["source_context_prepare"] == 1,
        "full_canonical_build_count_is_zero": counters["full_canonical_build"] == 0,
        "limited_catalog_cannot_masquerade_as_complete": _raises(
            lambda: materialize_character_runtime_task_graph_catalog(
                controls,
                view,
                source_snapshot=snapshot,
                definition_scope_complete=False,
            )
        ),
        "invalid_status_ability_link_is_rejected": _raises(
            lambda: replace(next(item for item in tasks if item.opcode != "TriggerAbility"), linked_standalone_graph_id="forged")
        ),
        "status_task_owner_scope_mismatch_is_rejected": _raises(
            lambda: _ordered_status_task_ids(
                next(item for item in callbacks if item.callback_id == tasks[0].callback_id),
                (replace(tasks[0], source=replace(tasks[0].source, evidence={
                    **tasks[0].source.evidence, "admission_source_path": "forged",
                })),),
            )
        ),
        "duplicate_formal_task_identity_is_rejected": _raises(lambda: replace(
            installed, status_callback_tasks=(*installed.status_callback_tasks, tasks[0]),
        )),
        "missing_callback_source_is_rejected_by_production": _raises(
            lambda: _validate_status_callback_denominator(snapshot, tuple(callbacks[1:]))
        ),
    }
    elapsed = time.monotonic() - started
    summary = {
        "ok": all(predicates.values()),
        "predicates": predicates,
        "counts": {
            "raw_callbacks": len(raw_callback_keys),
            "callbacks": len(callbacks),
            "taskless_callbacks": len(taskless_callbacks),
            "blocked_watcher_callbacks": len(blocked_watcher_callbacks),
            "status_tasks": len(tasks),
            "status_entries": len(status_entries),
            "status_graphs": len(status_graphs),
            "ability_entries": len(ability_entries),
            "reused_source_occurrences": len(reused),
            "trigger_ability_tasks": sum(item.opcode == "TriggerAbility" for item in tasks),
            **dict(counters),
        },
        "resource": {
            "wall_seconds": round(elapsed, 3),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.tbgd_root.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "validation_summary_p9_s8b4a_status_callback_formal_catalog.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__": raise SystemExit(main())
