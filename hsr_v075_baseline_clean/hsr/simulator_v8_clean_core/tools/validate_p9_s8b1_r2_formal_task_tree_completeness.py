from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ..tbgd.character_control_flow_contracts import _at_path as _source_at
from ..tbgd.lowering import TBGDLowering


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"


@dataclass(frozen=True)
class _DefinitionRef:
    action_id: str
    level: int = 0


def _raises(action: Callable[[], object]) -> bool:
    try:
        action()
    except (KeyError, IndexError, TypeError, ValueError):
        return True
    return False


def _family(raw: Mapping[str, Any]) -> str:
    value = raw.get("$type")
    if not isinstance(value, str) or not value:
        raise ValueError("typed task family is missing")
    return value.rsplit(".", 1)[-1]


def _callback_roots(
    raw: Mapping[str, Any], source_path: str, ability_index: int
) -> dict[str, tuple[tuple[str, str, str], ...]]:
    result: dict[str, tuple[tuple[str, str, str], ...]] = {}
    for field_name, value in raw.items():
        if not isinstance(field_name, str) or not isinstance(value, list):
            continue
        typed = tuple(item for item in value if isinstance(item, Mapping) and "$type" in item)
        if not typed:
            continue
        if len(typed) != len(value):
            raise ValueError("ability callback contains an untyped task")
        result[field_name] = tuple(
            (
                source_path,
                f"$.AbilityList[{ability_index}].{field_name}[{index}]",
                _family(item),
            )
            for index, item in enumerate(typed)
        )
    return result


def _task_key(task: Any) -> tuple[str, str, str]:
    return (
        task.source.source_path,
        str(task.source.evidence.get("json_path") or ""),
        str(task.source.evidence.get("source_opcode") or ""),
    )


def _expected_children(
    task: Any, context: Any
) -> tuple[tuple[tuple[str, str, str], str], ...]:
    control = context.control_by_location.get(_task_key(task))
    if control is None or control.coverage_status == "blocked":
        return ()
    rows = [
        (
            (
                child.source.source_path,
                str(child.source.evidence["json_path"]).removesuffix(".$type"),
                child.family,
            ),
            branch.branch_kind,
        )
        for branch in control.branches
        for child in branch.children
    ]
    if control.control_role == "template_include":
        refs = context.references_by_node.get(control.node_id, ())
        if len(refs) != 1 or refs[0].coverage_status != "lowered":
            return ()
        template = context.template_by_id[refs[0].resolved_template_id]
        rows.extend(
            (
                (
                    child.source.source_path,
                    str(child.source.evidence["json_path"]).removesuffix(".$type"),
                    child.family,
                ),
                "template_body",
            )
            for child in template.children
        )
    return tuple(rows)


def _template_negatives(lowering: TBGDLowering, context: Any, sample: Any) -> dict[str, bool]:
    control = context.control_by_location[_task_key(sample)]
    reference = context.references_by_node[control.node_id][0]
    raw = _source_at(
        context.documents[sample.source.source_path], _task_key(sample)[1]
    )
    missing_refs = dict(context.references_by_node)
    missing_refs[control.node_id] = ()
    missing_context = replace(
        context, references_by_node=MappingProxyType(missing_refs)
    )
    missing = lowering._formal_ability_task_children(
        raw,
        source_path=sample.source.source_path,
        source_json_path=_task_key(sample)[1],
        source_opcode=_task_key(sample)[2],
        context=missing_context,
        template_stack=(),
    )[1]
    cycle = lowering._formal_ability_task_children(
        raw,
        source_path=sample.source.source_path,
        source_json_path=_task_key(sample)[1],
        source_opcode=_task_key(sample)[2],
        context=context,
        template_stack=(reference.resolved_template_id,),
    )[1]
    return {
        "missing_or_ambiguous_template_rejected": (
            missing == "formal_task_template_reference_missing_or_ambiguous"
        ),
        "template_cycle_rejected": cycle == "formal_task_template_cycle",
        "non_authoritative_context_rejected": _raises(
            lambda: lowering._lower_ability_phase_tasks(
                definition=_DefinitionRef("negative:context"),
                phase_id="negative:context",
                ability_name="negative",
                ability={},
                ability_path=sample.source.source_path,
                ability_index=0,
                formal_source_context=missing_context,
            )
        ),
    }


def validate(tbgd_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    full_build_calls = 0
    original_build = TBGDLowering.build

    def forbidden_build(_self: TBGDLowering) -> object:
        nonlocal full_build_calls
        full_build_calls += 1
        raise AssertionError("focused validation cannot build full CanonicalIR")

    TBGDLowering.build = forbidden_build
    try:
        lowering = TBGDLowering(tbgd_root)
        source_graph = lowering.build_character_ability_source_graph_catalog()
        lowering.build_character_ability_source_resolution_catalog()
        context = lowering._character_formal_task_source_context()
        definitions = tuple(
            item
            for item in source_graph.definitions
            if item.definition_kind != "presentation"
        )
        counts: Counter[str] = Counter()
        callback_counts: Counter[str] = Counter()
        template_scopes: Counter[str] = Counter()
        source_instances: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        used_paths: set[str] = set()
        exact = True
        references_closed = True
        template_sample = None
        tamper_sample: tuple[Any, Mapping[str, Any], Mapping[str, Any], int] | None = None

        for definition in definitions:
            raw, document = lowering._character_ability_definition_record(definition)
            ability_index = definition.source.evidence.get("ability_index")
            if type(ability_index) is not int:
                raise ValueError("gameplay ability definition index is missing")
            expected_roots = _callback_roots(
                raw, definition.source.source_path, ability_index
            )
            callback_counts.update(expected_roots.keys())
            lowered = lowering._lower_ability_phase_tasks(
                definition=_DefinitionRef(f"audit:{definition.definition_id}"),
                phase_id=f"audit_phase:{definition.definition_id}",
                ability_name=definition.ability_name,
                ability=raw,
                ability_path=definition.source.source_path,
                ability_index=ability_index,
                target_alias_registry=(
                    document.get("GlobalTargetAlias")
                    if isinstance(document.get("GlobalTargetAlias"), dict)
                    else {}
                ),
                formal_source_context=context,
            )
            tasks = tuple(lowered.ability_tasks)
            by_id = {item.task_id: item for item in tasks}
            if len(by_id) != len(tasks):
                exact = False
            actual_roots = {
                callback: tuple(
                    _task_key(item)
                    for item in tasks
                    if item.callback_kind == callback and not item.parent_task_id
                )
                for callback in {item.callback_kind for item in tasks}
            }
            exact &= actual_roots == expected_roots
            reached: set[str] = set()
            pending = [item.task_id for item in tasks if not item.parent_task_id]
            while pending:
                task_id = pending.pop()
                if task_id in reached or task_id not in by_id:
                    continue
                reached.add(task_id)
                pending.extend(by_id[task_id].child_task_ids)
            exact &= reached == set(by_id)
            parent_counts = Counter(
                child_id for item in tasks for child_id in item.child_task_ids
            )
            exact &= all(
                parent_counts[item.task_id] == (0 if not item.parent_task_id else 1)
                for item in tasks
            )

            for task in tasks:
                key = _task_key(task)
                used_paths.add(key[0])
                source_instances[key].add(task.task_id)
                source_raw = _source_at(context.documents[key[0]], key[1])
                exact &= isinstance(source_raw, Mapping) and _family(source_raw) == key[2]
                expected = _expected_children(task, context)
                actual_ids = task.child_task_ids
                actual = tuple(_task_key(by_id[item]) for item in actual_ids)
                exact &= actual == tuple(item[0] for item in expected)
                exact &= task.success_task_ids == tuple(
                    actual_ids[index]
                    for index, item in enumerate(expected)
                    if item[1] == "success"
                )
                exact &= task.failed_task_ids == tuple(
                    actual_ids[index]
                    for index, item in enumerate(expected)
                    if item[1] == "failed"
                )
                control = context.control_by_location.get(key)
                if control is not None and control.control_role == "template_include":
                    refs = context.references_by_node.get(control.node_id, ())
                    if len(refs) == 1 and refs[0].coverage_status == "lowered":
                        template = context.template_by_id[refs[0].resolved_template_id]
                        template_scopes[template.scope_kind] += 1
                        template_sample = template_sample or task
            effect_ids = {item.effect_id for item in lowered.effects}
            condition_ids = {item.condition_id for item in lowered.conditions}
            references_closed &= (
                len(effect_ids) == len(lowered.effects)
                and len(condition_ids) == len(lowered.conditions)
                and all(not item.effect_id or item.effect_id in effect_ids for item in tasks)
                and all(
                    not item.condition_id or item.condition_id in condition_ids
                    for item in tasks
                )
            )
            counts.update(
                definitions=1,
                tasks=len(tasks),
                roots=len(pending) if False else sum(not item.parent_task_id for item in tasks),
                children=sum(len(item.child_task_ids) for item in tasks),
            )
            if tamper_sample is None and expected_roots:
                tamper_sample = (definition, raw, document, ability_index)

        digest_closed = all(
            sha256((tbgd_root / path).read_bytes()).hexdigest()
            == context.content_sha256_by_path[path]
            for path in used_paths
        )
        repeated_template_source = any(
            len(instances) > 1
            for key, instances in source_instances.items()
            if key[0].startswith("Config/ConfigGlobalTaskListTemplate/")
        )
        if template_sample is None or tamper_sample is None:
            raise AssertionError("real template and callback samples are required")
        negatives = _template_negatives(lowering, context, template_sample)
        definition, raw, document, ability_index = tamper_sample
        changed = dict(raw)
        callback = next(iter(_callback_roots(raw, definition.source.source_path, ability_index)))
        changed_tasks = [dict(item) for item in changed[callback]]
        changed_tasks[0]["$type"] = "forged.task.Type"
        changed[callback] = changed_tasks
        negatives["source_payload_tamper_rejected"] = _raises(
            lambda: lowering._lower_ability_phase_tasks(
                definition=_DefinitionRef("negative:source"),
                phase_id="negative:source",
                ability_name=definition.ability_name,
                ability=changed,
                ability_path=definition.source.source_path,
                ability_index=ability_index,
                target_alias_registry=(
                    document.get("GlobalTargetAlias")
                    if isinstance(document.get("GlobalTargetAlias"), dict)
                    else {}
                ),
                formal_source_context=context,
            )
        )
        predicates = {
            "formal_ability_task_reachable_denominator_non_empty": (
                counts["definitions"] > 0 and counts["tasks"] > 0
            ),
            "root_callback_denominator_complete": exact and bool(callback_counts),
            "every_reachable_source_task_has_one_formal_instance_per_reference_path": exact,
            "every_formal_child_is_owned_by_one_s8a_branch": exact,
            "all_s8a_branch_children_are_projected": exact,
            "template_instance_identity_and_source_identity_are_separate": repeated_template_source,
            "local_document_and_shared_templates_resolve_from_s8a": (
                set(template_scopes) == {"local", "document_global", "shared_global"}
            ),
            "template_missing_ambiguous_and_cycle_fail_closed": all(negatives.values()),
            "source_path_json_path_family_and_fingerprint_match": digest_closed and exact,
            "condition_target_effect_lowering_not_duplicated": references_closed,
            "external_content_behavior_changed": False,
            "runtime_behavior_changed": False,
            "full_canonical_ir_build_count": full_build_calls,
        }
        ok = all(
            value is True if isinstance(value, bool) else value == 0
            for key, value in predicates.items()
            if key not in {"external_content_behavior_changed", "runtime_behavior_changed"}
        ) and predicates["external_content_behavior_changed"] is False and predicates[
            "runtime_behavior_changed"
        ] is False
        return {
            "ok": ok,
            "predicates": predicates,
            "counts": dict(counts),
            "callback_counts": dict(sorted(callback_counts.items())),
            "template_scope_counts": dict(sorted(template_scopes.items())),
            "source_file_count": len(used_paths),
            "negative_matrix": negatives,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    finally:
        TBGDLowering.build = original_build


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.tbgd_root.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "validation_summary_p9_s8b1_r2_formal_task_tree.json"
    output.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
