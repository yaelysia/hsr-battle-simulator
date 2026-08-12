from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable

from ..rules.ir import CanonicalIR
from ..tbgd.character_control_flow_contracts import _at_path
from ..tbgd.lowering import (
    TBGDLowering,
    _assign_character_ability_invocation_roles,
    _link_trigger_ability_graphs,
    _lower_queue_resolutions,
    build_character_action_definition_ir,
)
from ..tbgd.task_graph_materializer import materialize_ability_task_graph_catalog
from ..tbgd import lowering as lowering_module
from ..tbgd import task_graph_materializer as materializer_module


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
FORMAL_ROLES = {"action_root", "nested_only", "standalone_root"}


def _raises(action: Callable[[], object]) -> bool:
    try:
        action()
    except (KeyError, IndexError, TypeError, ValueError):
        return True
    return False


def _dedupe(values: Iterable[Any], identity: str) -> tuple[Any, ...]:
    result: dict[str, Any] = {}
    for value in values:
        key = getattr(value, identity)
        if key in result and result[key] != value:
            raise ValueError(f"focused definition conflict:{identity}:{key}")
        result[key] = value
    return tuple(result[key] for key in sorted(result))


def _action_slice(lowering: TBGDLowering, source_graph: Any, snapshot: Any, scope: Any) -> tuple[CanonicalIR, Any]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for binding in source_graph.bindings:
        if binding.action_source_id:
            grouped[binding.action_source_id].append(binding)
    actions = {item.action_source_id: item for item in source_graph.action_sources}
    action_counts = Counter(item.action_id for item in source_graph.action_sources)
    definitions: dict[str, list[Any]] = defaultdict(list)
    for definition in build_character_action_definition_ir(lowering.tbgd_root):
        definitions[definition.action_id].append(definition)
    candidates = sorted(
        (
            (actions[source_id], bindings)
            for source_id, bindings in grouped.items()
            if action_counts[actions[source_id].action_id] == 1
            and actions[source_id].action_id in definitions
            and any(item.binding_kind == "entry" for item in bindings)
            and any(item.binding_kind == "phase" for item in bindings)
        ),
        key=lambda item: (item[0].action_id, item[0].owner_avatar_id),
    )
    for action, bindings in candidates:
        definition = min(definitions[action.action_id], key=lambda item: item.level)
        projection = lowering.build_character_action_ability_slice(
            definition,
            snapshot=snapshot,
            scope_catalog=scope,
            source_graph_catalog=source_graph,
        )
        linked = tuple(
            task for task in projection.ability_tasks if task.linked_ability_phase_id
        )
        if linked:
            return projection, (action, tuple(bindings), linked[0])
    raise AssertionError("real action root to nested phase source is required")


def _queue_slice(lowering: TBGDLowering, snapshot: Any) -> tuple[dict[str, Any], tuple[Any, ...]]:
    priorities = lowering._lower_queue_priorities()
    lookup = {
        (item.priority_table, item.priority_key): item
        for item in priorities
        if item.coverage_status == "executable"
    }
    selected = None
    for order, source in enumerate(snapshot.sources):
        path = source.source.source_path
        lowered = lowering._lower_ability_file(
            lowering.tbgd_root / path,
            lookup,
            ability_file_order=order,
            raw_document=snapshot.documents[path],
        )
        intent = next(
            (
                item
                for item in lowered.queue_intents
                if item.opcode == "TurnInsertAbility"
                and item.coverage_status == "executable"
                and item.action_ref_or_ability_name
            ),
            None,
        )
        if intent is not None:
            selected = (path, intent)
            break
    if selected is None:
        raise AssertionError("real executable character queue ability source is required")
    path, intent = selected
    raw = _at_path(snapshot.documents[path], str(intent.source.evidence["json_path"]))
    parts = lowering._lower_standalone_ability_graphs([lowering.tbgd_root / path])
    graphs, phases, tasks, effects, conditions, formulas, targets = parts
    tasks = _link_trigger_ability_graphs(tasks, effects, graphs, phases)
    resolutions = _lower_queue_resolutions(
        queue_intents=[intent],
        action_bindings=[],
        ability_phases=phases,
        standalone_graphs=graphs,
        combatant_action_sets=[],
    )
    phases = _assign_character_ability_invocation_roles(
        phases, tasks, graphs, resolutions
    )
    return {
        "path": path,
        "intent": intent,
        "raw": raw,
        "resolution": resolutions[0],
    }, (graphs, phases, tasks, effects, conditions, formulas, targets)


def validate(tbgd_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    counters = Counter()
    original_build = TBGDLowering.build
    original_control = lowering_module.build_character_control_flow_contract_catalog
    original_merge = materializer_module._materialization_dispositions

    def forbidden_build(_self: TBGDLowering) -> object:
        counters["full_build"] += 1
        raise AssertionError("focused validation cannot build full CanonicalIR")

    def counted_control(*args: Any, **kwargs: Any) -> Any:
        counters["control_source_scan"] += 1
        return original_control(*args, **kwargs)

    def counted_merge(*args: Any, **kwargs: Any) -> Any:
        counters["source_ledger_merge"] += 1
        return original_merge(*args, **kwargs)

    TBGDLowering.build = forbidden_build
    lowering_module.build_character_control_flow_contract_catalog = counted_control
    materializer_module._materialization_dispositions = counted_merge
    try:
        lowering = TBGDLowering(tbgd_root)
        source_graph = lowering.build_character_ability_source_graph_catalog()
        snapshot = lowering._character_ability_raw_snapshot
        scope = lowering._character_ability_scope_catalog
        action, action_evidence = _action_slice(lowering, source_graph, snapshot, scope)
        queue_evidence, standalone = _queue_slice(lowering, snapshot)
        graphs, phases, tasks, effects, conditions, _, targets = standalone
        all_phases = _dedupe((*action.ability_phases, *phases), "phase_id")
        all_tasks = _dedupe((*action.ability_tasks, *tasks), "task_id")
        view = CanonicalIR(
            version=action.version,
            action_ability_bindings=action.action_ability_bindings,
            ability_phases=all_phases,
            ability_tasks=all_tasks,
            standalone_ability_graphs=tuple(graphs),
            queue_intents=(queue_evidence["intent"],),
            queue_resolutions=(queue_evidence["resolution"],),
            effects=_dedupe((*action.effects, *effects), "effect_id"),
            conditions=_dedupe((*action.conditions, *conditions), "condition_id"),
            target_expressions=_dedupe(
                (*action.target_expressions, *targets), "target_expression_id"
            ),
        )
        source_catalog = lowering.build_character_control_flow_contract_catalog(
            snapshot=snapshot, scope_catalog=scope
        )
        counters["formal_catalog_build"] += 1
        catalog = materialize_ability_task_graph_catalog(
            source_catalog, view, source_snapshot=snapshot
        )
        installed = replace(view, task_graph_catalog=catalog)

        action_source, action_bindings, linked_task = action_evidence
        binding_kinds = {
            item.ability_name: item.binding_kind for item in action_bindings
        }
        action_roles = {
            phase.ability_name: phase.invocation_role
            for phase in action.ability_phases
        }
        expected_entries = {
            (phase.phase_id, task.callback_kind)
            for phase in all_phases
            if phase.invocation_role in FORMAL_ROLES
            for task in all_tasks
            if task.phase_id == phase.phase_id
        }
        actual_entries = {
            (item.owner_id, item.callback_kind)
            for item in catalog.entry_materializations
        }
        root_phases = tuple(
            phase for phase in phases if phase.invocation_role == "standalone_root"
        )
        unbound_phases = tuple(
            phase for phase in phases if phase.invocation_role == "unbound_definition"
        )
        raw = queue_evidence["raw"]
        raw_name = (
            raw.get("AbilityName", {}).get("Value")
            if isinstance(raw, dict) and isinstance(raw.get("AbilityName"), dict)
            else None
        )
        broken_task = replace(
            linked_task,
            linked_ability_phase_id="missing:formal_phase",
        )
        broken_view = replace(
            view,
            ability_tasks=tuple(
                broken_task if item.task_id == linked_task.task_id else item
                for item in view.ability_tasks
            ),
        )
        predicates = {
            "ability_phase_invocation_role_is_typed": _raises(
                lambda: replace(all_phases[0], invocation_role="invalid")
            )
            and _raises(
                lambda: replace(
                    all_phases[0],
                    invocation_role="unbound_definition",
                    task_ids=(),
                )
            ),
            "action_root_and_nested_phase_are_not_conflated": (
                action_roles
                and all(
                    action_roles.get(name)
                    == ("action_root" if kind == "entry" else "nested_only")
                    for name, kind in binding_kinds.items()
                    if kind in {"entry", "phase", "passive"}
                    and name in action_roles
                )
                and action_roles.get(
                    next(
                        phase.ability_name
                        for phase in action.ability_phases
                        if phase.phase_id == linked_task.linked_ability_phase_id
                    )
                )
                == "nested_only"
            ),
            "trigger_ability_target_is_unique_and_typed": (
                bool(linked_task.linked_ability_phase_id)
                and not linked_task.linked_standalone_graph_id
                and _raises(
                    lambda: replace(
                        linked_task,
                        linked_standalone_graph_id=graphs[0].standalone_ability_graph_id,
                    )
                )
            ),
            "queue_root_matches_real_source": (
                isinstance(raw, dict)
                and str(raw.get("$type", "")).endswith("TurnInsertAbility")
                and raw_name == queue_evidence["intent"].action_ref_or_ability_name
                and len(root_phases) == 1
                and root_phases[0].binding_id
                == queue_evidence["resolution"].resolved_ids.get(
                    "standalone_ability_graph_id"
                )
            ),
            "unbound_definitions_are_not_formal_entries": (
                bool(unbound_phases)
                and not {
                    phase.phase_id for phase in unbound_phases
                }
                & {item.owner_id for item in catalog.entry_materializations}
            ),
            "formal_phase_callback_denominator_complete": (
                bool(expected_entries) and expected_entries == actual_entries
            ),
            "formal_catalog_installed_once": (
                counters["formal_catalog_build"] == 1
                and installed.task_graph_catalog == catalog
                and catalog.scope_mode == "formal_catalog"
            ),
            "control_flow_source_scan_count": counters["control_source_scan"],
            "formal_catalog_build_count": counters["formal_catalog_build"],
            "complete_source_ledger_merge_count": counters["source_ledger_merge"],
            "complete_source_ledger_not_copied_per_graph": (
                all(
                    "source_dispositions" not in item.to_json()
                    for item in catalog.entry_materializations
                )
                and len(catalog.source_dispositions)
                == len(source_catalog.nodes)
                + len(source_catalog.template_definitions)
                + len(source_catalog.template_references)
            ),
            "blocked_formal_entry_rejects_catalog": _raises(
                lambda: materialize_ability_task_graph_catalog(
                    source_catalog, broken_view, source_snapshot=snapshot
                )
            ),
            "limited_catalog_cannot_masquerade_as_complete": _raises(
                lambda: replace(
                    catalog,
                    entry_materializations=catalog.entry_materializations[:-1],
                )
            ),
            "external_content_not_claimed_by_character_catalog": all(
                phase.invocation_role != "external_legacy"
                for phase in all_phases
                if phase.phase_id in {item.owner_id for item in catalog.entry_materializations}
            ),
            "runtime_behavior_changed": False,
            "full_canonical_ir_build_count": counters["full_build"],
        }
        ok = all(
            value is True if isinstance(value, bool) else value == 1
            for key, value in predicates.items()
            if key
            not in {
                "runtime_behavior_changed",
                "full_canonical_ir_build_count",
            }
        ) and predicates["runtime_behavior_changed"] is False and predicates[
            "full_canonical_ir_build_count"
        ] == 0
        return {
            "ok": ok,
            "predicates": predicates,
            "counts": {
                "formal_phase_count": sum(
                    item.invocation_role in FORMAL_ROLES for item in all_phases
                ),
                "unbound_definition_count": len(unbound_phases),
                "entry_count": len(catalog.entry_materializations),
                "graph_count": len(catalog.graphs),
                "source_record_count": len(catalog.source_dispositions),
            },
            "samples": {
                "action_id": action_source.action_id,
                "action_level": action.action_definitions[0].level,
                "nested_target_phase_id": linked_task.linked_ability_phase_id,
                "queue_source_path": queue_evidence["path"],
                "queue_ability_name": queue_evidence["intent"].action_ref_or_ability_name,
            },
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    finally:
        TBGDLowering.build = original_build
        lowering_module.build_character_control_flow_contract_catalog = original_control
        materializer_module._materialization_dispositions = original_merge


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.tbgd_root.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "validation_summary_p9_s8b3a_ability_invocation_formal_catalog.json"
    output.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
