from __future__ import annotations

import argparse
import inspect
import json
from collections import Counter, defaultdict
from dataclasses import replace
from math import isclose
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..builds.character_assembler import assemble_character_build
from ..builds.models import CharacterInitialConditionInput
from ..core.executor import CombatExecutor
from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    JSONValue,
    Mutation,
    TargetResolution,
    UnitStatPool,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..core.unit_state_codec import unit_state_from_payload, unit_state_to_payload
from ..resource_event_contract import (
    resource_callback_runtime_sources,
    resource_scope_for_callback,
)
from ..rules.evaluator import (
    EvaluationContext,
    NumericEvaluationContext,
    RuleEvaluator,
    _condition_target_ids,
)
from ..rules.ir import (
    CanonicalIR,
    BreakDamageEmissionIR,
    BreakTemplateIR,
    ConditionIR,
    DamageEmissionIR,
    EffectIR,
    HitProfileIR,
    IRSource,
    RuleEntity,
    ActionPhaseStepIR,
    AbilityTaskIR,
    StatusCallbackIR,
    StatusEventFamilyIR,
    TargetExpressionNodeIR,
    TimelineRuleIR,
    ToughnessEmissionIR,
)
from ..rules.expression_ir import numeric_dynamic_hashes, numeric_fixed
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder, _equipment_startup_spec, _startup_dynamic_values
from ..scenarios.schema import BattleSetupSpec, ScenarioSpec, TimelineSetupSpec, UnitSpec
from ..systems.status import (
    StatusSystem,
    _map_stack_property,
    _runtime_modifiers,
    _unit_resource,
)
from ..systems.status_callbacks import (
    StatusCallbackSystem,
    _alive_enemy_ids_for_status_owner,
    _callback_target_group,
    _list_alias_targets,
)
from ..systems.damage import DamagePacket, DamageSourceFrame, DamageSystem
from ..systems.damage_formula import DirectDamageFormula, DamageFormulaInput
from ..systems.decision import DecisionSystem
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.phase_machine import EVENT_PHASES
from ..systems.target import TargetSystem
from ..systems.timeline import TimelineSystem
from ..systems.scaling_basis import resolve_scaling_basis
from ..systems.scheduler import _status_phase1_lifecycle_event
from ..systems.unit_stats import (
    effective_unit_stat,
    status_modifier_has_direct_combat_consumer,
)
from ..tbgd.equipment_ability_families import (
    classify_equipment_callback,
    classify_equipment_condition,
    classify_equipment_family,
    classify_equipment_target,
    classify_equipment_task,
    classify_equipment_value,
    equipment_value_family,
    non_gameplay_evidence,
)
from ..tbgd.light_cone_cards import build_light_cone_catalog
from ..tbgd.expression_lowering import _decode_opcodes, lower_numeric_expression
from ..tbgd.lowering import (
    ABILITY_TASK_CALLBACKS,
    TBGDLowering,
    _block_status_callback_tasks_by_callback,
    _block_status_callbacks_by_event_family,
    _condition_payload_executable,
    _equipment_reachable_modifier_names,
    _equipment_nested_modifier_stage,
    _link_status_effect_runtime_fields,
    _lower_status_event_families,
    _numeric_expr_can_be_runtime_bound,
    _numeric_expr_summary,
    _status_event_blocked_reasons,
    _typed_condition_execution_node,
)
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .validate_p1_4_status_system import _LifecycleResultAdapter, _status_transition
from .validate_p8_s6_light_cone_dynamic_startup import (
    _assembly,
    _character_build,
    _focused_bundle as _s6_focused_bundle,
)
from .validate_p7_s0_kernel_trust_baseline import (
    _base_state as _p7_base_state,
    _source as _p7_fixture_source,
)
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p8_s7_light_cone_status_condition_listener_closure"
SUMMARY_SCHEMA_VERSION = "p8_s7_light_cone_status_condition_listener_closure_summary_v1"


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = _focused_bundle(tbgd_root)
    inventory = _family_inventory(bundle)
    formal = _formal_scenario_matrix(bundle)
    conditions = _condition_matrix(bundle)
    dynamic_tasks = _structured_dynamic_task_matrix(bundle)
    targets = _target_attribution_matrix(bundle, inventory, formal)
    lifecycle = _lifecycle_matrix(bundle, formal)
    events = _event_timing_matrix(bundle, inventory, formal, lifecycle)
    unsupported = _unsupported_atomic_matrix(bundle)
    effective_stats = _effective_stat_consumption_matrix(bundle)
    coverage = _coverage_matrix(
        bundle,
        inventory,
        conditions=conditions,
        dynamic_tasks=dynamic_tasks,
        targets=targets,
        lifecycle=lifecycle,
        events=events,
        effective_stats=effective_stats,
    )
    runtime_boundary = _runtime_boundary()

    predicates = {
        "current_gameplay_inventory_non_empty": inventory["checks"]["gameplay_nonempty"],
        "s7_s8_partition_complete": inventory["checks"]["partition_complete"],
        "s7_s8_partition_disjoint": inventory["checks"]["partition_disjoint"],
        "s7_family_gap_count": coverage["gap_count"],
        "s7_unknown_gameplay_count": inventory["counts"]["unknown"],
        "s7_non_gameplay_has_structured_evidence": inventory["checks"]["non_gameplay_evidence_complete"],
        "condition_false_is_not_blocked": conditions["checks"]["false_is_committed_no_effect"],
        "condition_family_runtime_closed": conditions["ok"],
        "structured_dynamic_task_runtime_closed": dynamic_tasks["ok"],
        "unsupported_selected_branch_blocks_atomically": unsupported["ok"],
        "status_attributes_reach_combat_consumers": effective_stats["ok"],
        "listener_registration_idempotent": formal["checks"]["rebuild_is_deterministic_and_single_provider"],
        "event_family_sources_closed": events["ok"],
        "status_mutations_follow_common_lifecycle": lifecycle["ok"],
        "owner_target_attribution_correct": targets["ok"],
        "all_sampled_mutations_source_audited": lifecycle["checks"]["source_audit"],
        "all_sampled_transitions_replay_equal": lifecycle["checks"]["replay"],
        "equipment_specific_runtime_handlers": runtime_boundary["equipment_specific_runtime_handlers"],
        "formal_s7_graph_enters_battle": formal["checks"]["formal_build_admitted"],
        "formal_scenario_chain_closed": formal["ok"],
        "mixed_s7_s8_graph_remains_blocked": coverage["checks"]["mixed_graphs_blocked"],
    }
    ok = (
        all(
            value is True
            for key, value in predicates.items()
            if key
            not in {
                "s7_family_gap_count",
                "s7_unknown_gameplay_count",
                "equipment_specific_runtime_handlers",
            }
        )
        and predicates["s7_family_gap_count"] == 0
        and predicates["s7_unknown_gameplay_count"] == 0
        and predicates["equipment_specific_runtime_handlers"] == 0
    )
    predicates["ok"] = ok

    artifacts = {
        "family_partition_ledger_p8_s7.json": {
            key: value
            for key, value in inventory.items()
            if not key.startswith("_")
        },
        "family_coverage_matrix_p8_s7.json": coverage,
        "condition_matrix_p8_s7.json": conditions,
        "structured_dynamic_task_matrix_p8_s7.json": dynamic_tasks,
        "target_owner_multi_wearer_attribution_matrix_p8_s7.json": targets,
        "formal_scenario_event_attribution_matrix_p8_s7.json": {
            key: value
            for key, value in formal.items()
            if not key.startswith("_")
        },
        "status_lifecycle_audit_replay_matrix_p8_s7.json": {
            key: value
            for key, value in lifecycle.items()
            if not key.startswith("_")
        },
        "event_timing_matrix_p8_s7.json": events,
        "unsupported_atomic_matrix_p8_s7.json": unsupported,
        "effective_status_stat_consumption_matrix_p8_s7.json": effective_stats,
        "runtime_boundary_p8_s7.json": runtime_boundary,
    }
    for filename, payload in artifacts.items():
        write_json(output_dir / filename, payload)
    artifact_sizes = {
        filename: (output_dir / filename).stat().st_size
        for filename in sorted(artifacts)
    }
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checklist_modified": False,
        "git_commit_created": False,
        "p8_s8_started": False,
        "predicates": predicates,
        "counts": {
            "published_light_cone_count": len(bundle["definitions"]),
            "ability_file_count": len(bundle["equipment_sources"]),
            "equipment_graph_count": len(bundle["graphs"]),
            "s7_executable_graph_count": sum(
                graph.coverage_status == "executable"
                for graph in bundle["graphs"]
            ),
            "s8_blocked_graph_count": sum(
                graph.coverage_status != "executable"
                for graph in bundle["graphs"]
            ),
            "status_callback_count": len(bundle["callbacks"]),
            "status_callback_task_count": len(bundle["callback_tasks"]),
            "family_row_count": len(inventory["rows"]),
            "raw_family_source_node_count": inventory["source_sample_count"],
            "s7_source_node_count": inventory["counts"]["s7"],
            "s8_source_node_count": inventory["counts"]["s8"],
            "non_gameplay_source_node_count": inventory["counts"]["non_gameplay"],
            "unreferenced_source_node_count": inventory["counts"]["unreferenced"],
            "s7_family_row_count": sum(
                row["stage"] == "s7" for row in inventory["rows"]
            ),
            "condition_family_case_count": len(conditions["structural_rows"]),
            "condition_runtime_family_count": len(
                conditions["runtime_family_rows"]
            ),
            "structured_dynamic_task_family_count": len(dynamic_tasks["rows"]),
            "target_family_case_count": len(targets["rows"]),
            "event_family_case_count": len(events["rows"]),
            "lifecycle_case_count": len(lifecycle["audit_replay_samples"]),
            "coverage_gap_count": coverage["gap_count"],
        },
        "resource_scope": {
            "focused_rulebook_build_count": 2,
            "full_canonical_ir_serialized": False,
            "transition_dump_written": False,
            "artifacts": sorted(artifacts),
            "artifact_byte_count": sum(artifact_sizes.values()),
            "artifact_bytes_by_file": artifact_sizes,
        },
        "deferred": {
            "stage": "P8-S8",
            "family_rows": [
                {
                    "kind": row["kind"],
                    "family": row["family"],
                    "raw_count": row["raw_count"],
                }
                for row in inventory["rows"]
                if row["stage"] == "s8"
            ],
            "reason": "damage/heal/shield/resource/action/complex-target/RNG branches remain atomically blocked",
        },
    }
    write_json(
        output_dir
        / "validation_summary_p8_s7_light_cone_status_condition_listener_closure.json",
        summary,
    )
    return summary


def _focused_bundle(tbgd_root: Path) -> dict[str, Any]:
    base = _s6_focused_bundle(tbgd_root)
    return _with_s7_status_closure(base, tbgd_root)


def _with_s7_status_closure(
    base: dict[str, Any],
    tbgd_root: Path,
) -> dict[str, Any]:
    lowering = TBGDLowering(tbgd_root)
    equipment_sources: dict[str, dict[int, Any]] = {}
    for definition in base["definitions"]:
        source = definition.ability_source
        if source is not None:
            equipment_sources.setdefault(source.source.source_path, {})[
                source.record_index
            ] = source.source

    entities = []
    effects = []
    conditions = []
    targets = []
    callbacks = []
    callback_tasks = []
    lowered_by_path: dict[str, Any] = {}
    for order, (relative, selected) in enumerate(sorted(equipment_sources.items())):
        lowered = lowering._lower_ability_file(
            tbgd_root / relative,
            {},
            ability_file_order=order,
            selected_equipment_sources=selected,
        )
        lowered_by_path[relative] = lowered
        entities.extend(lowered.entities)
        effects.extend(lowered.effects)
        conditions.extend(lowered.conditions)
        targets.extend(lowered.target_expressions)
        callbacks.extend(lowered.status_callbacks)
        callback_tasks.extend(lowered.status_callback_tasks)

    event_families = _lower_status_event_families(callbacks, callback_tasks)
    event_blocked = _status_event_blocked_reasons(event_families)
    callbacks = _block_status_callbacks_by_event_family(callbacks, event_blocked)
    callback_blocked = {
        callback.callback_id: event_blocked[callback.event]
        for callback in callbacks
        if callback.event in event_blocked
    }
    callback_tasks = _block_status_callback_tasks_by_callback(
        callback_tasks,
        callback_blocked,
    )
    all_entities = (*base["ir"].entities, *entities)
    all_effects = _link_status_effect_runtime_fields(
        [*base["effects"], *effects],
        list(all_entities),
        callbacks,
    )
    event_families = _lower_status_event_families(callbacks, callback_tasks)
    ir = replace(
        base["ir"],
        entities=tuple(all_entities),
        effects=tuple(all_effects),
        conditions=tuple((*base["conditions"], *conditions)),
        target_expressions=tuple((*base["targets"], *targets)),
        status_callbacks=tuple(callbacks),
        status_callback_tasks=tuple(callback_tasks),
        status_event_families=tuple(event_families),
        metadata={
            **base["ir"].metadata,
            "validation_scope": "p8_s7_focused_equipment_status_condition_listener",
        },
    )
    return {
        **base,
        "ir": ir,
        "rules": RuleBook(ir),
        "equipment_sources": equipment_sources,
        "lowered_by_path": lowered_by_path,
        "entities": tuple(entities),
        "effects": tuple(all_effects),
        "nested_effects": tuple(effects),
        "conditions": tuple((*base["conditions"], *conditions)),
        "nested_conditions": tuple(conditions),
        "targets": tuple((*base["targets"], *targets)),
        "callbacks": tuple(callbacks),
        "callback_tasks": tuple(callback_tasks),
        "event_families": tuple(event_families),
        "tbgd_root": tbgd_root,
    }


def _family_inventory(bundle: dict[str, Any]) -> dict[str, Any]:
    raw_rows = _scan_raw_families(bundle)
    counts = Counter((row["kind"], row["family"], row["stage"]) for row in raw_rows)
    rows = [
        {
            "kind": kind,
            "family": family,
            "stage": stage,
            "raw_count": count,
            "structured_evidence": (
                (
                    "empty callback contains no gameplay task"
                    if kind == "event" and family.endswith(":non_gameplay")
                    else non_gameplay_evidence(
                        kind,
                        family.split(":", 1)[0],
                    )
                    or "descendant of a structurally classified non-gameplay branch"
                )
                if stage == "non_gameplay"
                else (
                    "raw modifier definition is retained, but no exact-name path reaches it from the selected equipment ability root"
                    if stage == "unreferenced"
                    else ""
                )
            ),
        }
        for (kind, family, stage), count in sorted(counts.items())
    ]
    gameplay = [row for row in raw_rows if row["stage"] in {"s7", "s8"}]
    s7_keys = {
        (row["kind"], row["family"], row["source_identity"])
        for row in raw_rows
        if row["stage"] == "s7"
    }
    s8_keys = {
        (row["kind"], row["family"], row["source_identity"])
        for row in raw_rows
        if row["stage"] == "s8"
    }
    checks = {
        "gameplay_nonempty": bool(gameplay),
        "s7_nonempty": bool(s7_keys),
        "s8_nonempty": bool(s8_keys),
        "partition_complete": len(gameplay) == len(s7_keys | s8_keys),
        "partition_disjoint": not (s7_keys & s8_keys),
        "non_gameplay_evidence_complete": all(
            bool(row["structured_evidence"])
            for row in rows
            if row["stage"] == "non_gameplay"
        ),
        "unreferenced_evidence_complete": all(
            bool(row["structured_evidence"])
            for row in rows
            if row["stage"] == "unreferenced"
        ),
    }
    checks["ok"] = all(checks.values())
    catalog_summary = bundle["catalog"].to_summary_json()
    return {
        "schema_version": "p8_s7_family_partition_ledger_v1",
        "ok": checks["ok"] and not any(row["stage"] == "unknown" for row in raw_rows),
        "checks": checks,
        "source_content_fingerprint": catalog_summary["source_content_fingerprint"],
        "counts": Counter(row["stage"] for row in raw_rows),
        "rows": rows,
        "source_sample_count": len(raw_rows),
        "_source_rows": tuple(raw_rows),
    }


def _scan_raw_families(bundle: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lowering = TBGDLowering(Path(bundle["tbgd_root"]))
    linked_modifier_stages = _callback_linked_modifier_stages(bundle)
    for relative, selected in sorted(bundle["equipment_sources"].items()):
        path = Path(bundle["tbgd_root"]) / relative if "tbgd_root" in bundle else None
        if path is None:
            raise ValueError("focused bundle lost tbgd root")
        document = json.loads(path.read_text(encoding="utf-8"))
        modifier_maps = lowering._modifier_maps(
            document,
            selected_ability_indices=frozenset(selected),
        )
        reachable_by_ability = {
            ability_index: _equipment_reachable_modifier_names(
                document,
                ability_index,
            )
            for ability_index in selected
        }
        ability_list = document.get("AbilityList")
        if not isinstance(ability_list, list):
            raise ValueError(f"{relative}: AbilityList missing")
        for ability_index in sorted(selected):
            ability = ability_list[ability_index]
            if not isinstance(ability, dict):
                raise ValueError(f"{relative}: ability row invalid")
            ability_nested_stage = _equipment_nested_modifier_stage(
                tuple(
                    modifier_row
                    for modifier_row in lowering._modifier_maps(
                        document,
                        selected_ability_indices=frozenset({ability_index}),
                    )
                    if modifier_row[1]
                    in reachable_by_ability.get(ability_index, frozenset())
                )
            )
            ability_inherited_stage = (
                ability_nested_stage
                if ability_nested_stage in {"s8", "unknown"}
                else None
            )
            for callback_name in ABILITY_TASK_CALLBACKS:
                raw_tasks = ability.get(callback_name)
                if not isinstance(raw_tasks, list):
                    continue
                for task_index, task in enumerate(raw_tasks):
                    _scan_task(
                        rows,
                        task,
                        f"{relative}#AbilityList[{ability_index}].{callback_name}[{task_index}]",
                        inherited_stage=ability_inherited_stage,
                    )
        for _, modifier_name, modifier, context in modifier_maps:
            referenced_indices = context.get("referenced_by_ability_indices")
            candidate_indices = (
                tuple(
                    index
                    for index in referenced_indices
                    if isinstance(index, int) and not isinstance(index, bool)
                )
                if isinstance(referenced_indices, list)
                else (
                    (context.get("ability_index"),)
                    if isinstance(context.get("ability_index"), int)
                    and not isinstance(context.get("ability_index"), bool)
                    else ()
                )
            )
            modifier_reachable = any(
                modifier_name in reachable_by_ability.get(index, frozenset())
                for index in candidate_indices
            )
            callbacks = modifier.get("_CallbackList")
            if not isinstance(callbacks, list):
                continue
            for callback_index, callback in enumerate(callbacks):
                if not isinstance(callback, dict):
                    rows.append(_family_row("event", "invalid", "unknown", f"{relative}#{modifier_name}:callback:{callback_index}"))
                    continue
                event = str(callback.get("Event") or "")
                tasks = callback.get("CallbackConfig")
                stage = classify_equipment_callback(event, tasks)
                if not modifier_reachable:
                    stage = "unreferenced"
                callback_json_path = (
                    f"{context.get('json_path')}._CallbackList[{callback_index}]"
                )
                linked_stage = linked_modifier_stages.get(
                    (relative, callback_json_path)
                )
                if stage != "unreferenced" and linked_stage in {"s8", "unknown"}:
                    stage = linked_stage
                rows.append(
                    _family_row(
                        "event",
                        f"{event}:{stage}",
                        stage,
                        f"{relative}#{callback_json_path}",
                    )
                )
                if isinstance(tasks, list):
                    for task_index, task in enumerate(tasks):
                        _scan_task(
                            rows,
                            task,
                            f"{relative}#{context.get('json_path')}._CallbackList[{callback_index}].CallbackConfig[{task_index}]",
                            inherited_stage=stage,
                        )
    return rows


def _callback_linked_modifier_stages(
    bundle: dict[str, Any],
) -> dict[tuple[str, str], str]:
    """Classify AddModifier callbacks through their linked modifier definition.

    The raw callback task only names a modifier.  Its StackProperty nodes live
    in that definition and may have a different consumer stage, so classifying
    the callback by the AddModifier opcode alone would admit a partial graph.
    """

    rules: RuleBook = bundle["rules"]
    stages: dict[tuple[str, str], str] = {}
    for callback in bundle["callbacks"]:
        linked_stages: set[str] = set()
        for task in rules.status_callback_tasks_for_callback(
            callback.callback_id
        ):
            effect = rules.effect(task.effect_id) if task.effect_id else None
            if effect is None or effect.opcode != "AddModifier":
                continue
            definition = (
                rules.entity(effect.modifier_definition_id)
                if effect.modifier_definition_id
                else None
            )
            standard = (
                effect.payload.get("standard")
                if isinstance(effect.payload, dict)
                else None
            )
            chance = (
                standard.get("chance")
                if isinstance(standard, dict)
                else None
            )
            if (
                isinstance(chance, dict)
                and chance.get("kind") != "missing"
                and not _modifier_probability_category_has_source(
                    rules,
                    effect,
                    definition,
                )
            ):
                linked_stages.add("s8")
            properties = (
                definition.fields.get("stack_properties")
                if definition is not None
                else None
            )
            if not isinstance(properties, list):
                continue
            for item in properties:
                if not isinstance(item, dict):
                    linked_stages.add("unknown")
                    continue
                property_name = item.get("property")
                linked_stages.add(
                    classify_equipment_task(
                        "StackProperty",
                        {
                            "$type": "StackProperty",
                            "Property": property_name,
                        },
                    )
                )
        stage = (
            "unknown"
            if "unknown" in linked_stages
            else "s8"
            if "s8" in linked_stages
            else "s7"
        )
        if stage == "s7":
            continue
        callback_json_path = callback.source.evidence.get(
            "callback_json_path"
        )
        if isinstance(callback_json_path, str) and callback_json_path:
            stages[(callback.source.source_path, callback_json_path)] = stage
    return stages


def _modifier_probability_category_has_source(
    rules: RuleBook,
    effect: Any,
    definition: Any,
) -> bool:
    """Check raw category evidence needed by an explicit status chance.

    This is deliberately independent of the runtime probability evaluator: a
    callback only stays in S7 when its linked status row or modifier behavior
    flags identify how effect hit/resistance must be applied.
    """

    standard = (
        effect.payload.get("standard")
        if isinstance(effect.payload, dict)
        else None
    )
    modifier_name = (
        standard.get("modifier_name")
        if isinstance(standard, dict)
        else None
    )
    if isinstance(modifier_name, str) and modifier_name:
        status_entity = rules.status_entity_for_modifier(modifier_name)
        if status_entity is not None:
            status_type = str(
                status_entity.fields.get("StatusType")
                or status_entity.fields.get("status_type")
                or ""
            ).strip().lower()
            if status_type in {"buff", "debuff", "other", "control"}:
                return True
    flags = (
        definition.fields.get("behavior_flags")
        if definition is not None
        else None
    )
    normalized = tuple(
        str(flag).strip().lower()
        for flag in flags
        if isinstance(flag, str)
    ) if isinstance(flags, (list, tuple)) else ()
    return any(
        flag in {"shield", "stat_ctrl", "disableaction"}
        or flag.startswith("stat_dot")
        or (
            flag.startswith("stat_")
            and (flag.endswith("up") or flag.endswith("down"))
        )
        for flag in normalized
    )


def _scan_task(
    rows: list[dict[str, str]],
    task: Any,
    identity: str,
    *,
    inherited_stage: str | None,
) -> None:
    if not isinstance(task, dict):
        rows.append(_family_row("task", "invalid", "unknown", identity))
        return
    family = _short_type(task.get("$type"))
    stage = classify_equipment_task(family, task)
    if inherited_stage in {"s8", "non_gameplay", "unreferenced", "unknown"}:
        stage = inherited_stage
    semantic_family = family
    if family == "StackProperty":
        property_name = task.get("Property")
        semantic_family = f"StackProperty:{property_name or 'missing'}"
    rows.append(
        _family_row("task", f"{semantic_family}:{stage}", stage, identity)
    )
    predicate = task.get("Predicate")
    if isinstance(predicate, dict):
        _scan_condition(
            rows,
            predicate,
            f"{identity}.Predicate",
            inherited_stage=stage,
        )
    _scan_targets_and_values(rows, task, identity, inherited_stage=stage)
    for key in ("TaskList", "SuccessTaskList", "FailedTaskList"):
        children = task.get(key)
        if not isinstance(children, list):
            continue
        for index, child in enumerate(children):
            _scan_task(
                rows,
                child,
                f"{identity}.{key}[{index}]",
                inherited_stage=stage,
            )


def _scan_condition(
    rows: list[dict[str, str]],
    condition: dict[str, Any],
    identity: str,
    *,
    inherited_stage: str | None,
) -> None:
    family = _short_type(condition.get("$type"))
    stage = classify_equipment_condition(family, condition)
    if inherited_stage in {"s8", "non_gameplay", "unreferenced", "unknown"}:
        stage = inherited_stage
    rows.append(_family_row("condition", f"{family}:{stage}", stage, identity))
    _scan_targets_and_values(
        rows,
        condition,
        identity,
        inherited_stage=stage,
    )
    children = condition.get("PredicateList")
    if isinstance(children, list):
        for index, child in enumerate(children):
            if isinstance(child, dict):
                _scan_condition(
                    rows,
                    child,
                    f"{identity}.PredicateList[{index}]",
                    inherited_stage=stage,
                )
    child = condition.get("Predicate")
    if isinstance(child, dict):
        _scan_condition(
            rows,
            child,
            f"{identity}.Predicate",
            inherited_stage=stage,
        )


def _scan_targets_and_values(
    rows: list[dict[str, str]],
    value: Any,
    identity: str,
    *,
    inherited_stage: str | None,
) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_targets_and_values(
                rows,
                item,
                f"{identity}[{index}]",
                inherited_stage=inherited_stage,
            )
        return
    if not isinstance(value, dict):
        return
    raw_type = _short_type(value.get("$type"))
    if raw_type.startswith("Target"):
        stage = classify_equipment_target(value)
        if inherited_stage in {"s8", "non_gameplay", "unreferenced", "unknown"}:
            stage = inherited_stage
        family = raw_type
        if raw_type == "TargetAlias":
            family = f"TargetAlias:{value.get('Alias')}"
        rows.append(_family_row("target", family, stage, identity))
        return
    value_stage = classify_equipment_value(value)
    if value_stage != "unknown" and inherited_stage in {
        "s8",
        "non_gameplay",
        "unreferenced",
        "unknown",
    }:
        value_stage = inherited_stage
    if value_stage != "unknown":
        row = _family_row(
            "value",
            equipment_value_family(value),
            value_stage,
            identity,
        )
        lowered_value = lower_numeric_expression(value)
        hashes = numeric_dynamic_hashes(lowered_value)
        evaluation = RuleEvaluator().evaluate_numeric(
            lowered_value,
            NumericEvaluationContext(
                dynamic_values={str(value_hash): 1.0 for value_hash in hashes}
            ),
        )
        row["validated"] = str(
            _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(value))
            and evaluation.ok
            and evaluation.value is not None
        ).lower()
        rows.append(row)
        return
    for key, item in value.items():
        if key == "Predicate" or key == "PredicateList" or key in {
            "TaskList",
            "SuccessTaskList",
            "FailedTaskList",
        }:
            continue
        _scan_targets_and_values(
            rows,
            item,
            f"{identity}.{key}",
            inherited_stage=inherited_stage,
        )


def _family_row(kind: str, family: str, stage: str, source_identity: str) -> dict[str, str]:
    return {
        "kind": kind,
        "family": family,
        "stage": stage,
        "source_identity": source_identity,
    }


def _coverage_matrix(
    bundle: dict[str, Any],
    inventory: dict[str, Any],
    *,
    conditions: dict[str, Any],
    dynamic_tasks: dict[str, Any],
    targets: dict[str, Any],
    lifecycle: dict[str, Any],
    events: dict[str, Any],
    effective_stats: dict[str, Any],
) -> dict[str, Any]:
    raw_rows = _scan_raw_families(bundle)
    indexes = _coverage_source_indexes(bundle)
    validation_families = _runtime_validation_families(
        conditions=conditions,
        dynamic_tasks=dynamic_tasks,
        targets=targets,
        lifecycle=lifecycle,
        events=events,
        effective_stats=effective_stats,
    )
    source_rows = [
        _source_coverage_row(row, indexes, validation_families)
        for row in raw_rows
    ]
    grouped_rows: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        grouped_rows[(row["kind"], row["family"], row["stage"])].append(row)
    rows = []
    for (kind, family, stage), members in sorted(grouped_rows.items()):
        raw_count = len(members)
        lowered_count = sum(row["lowered"] is True for row in members)
        admitted_count = sum(row["admitted"] is True for row in members)
        executable_count = sum(row["executable"] is True for row in members)
        validated_count = sum(row["validated"] is True for row in members)
        gap = sum(
            not (
                row["lowered"] is True
                and row["admitted"] is True
                and row["executable"] is True
                and row["validated"] is True
            )
            for row in members
            if stage == "s7"
        )
        rows.append(
            {
                "kind": kind,
                "family": family,
                "stage": stage,
                "raw_count": raw_count,
                "lowered_count": lowered_count,
                "admitted_count": admitted_count,
                "executable_count": executable_count,
                "validated_count": validated_count,
                "gap_count": gap,
            }
        )
    mixed_graphs = tuple(
        graph for graph in bundle["graphs"] if graph.coverage_status != "executable"
    )
    checks = {
        "s7_counts_equal": all(
            row["raw_count"]
            == row["lowered_count"]
            == row["admitted_count"]
            == row["executable_count"]
            == row["validated_count"]
            for row in rows if row["stage"] == "s7"
        ),
        "source_identities_unique": len(source_rows)
        == len(
            {
                (row["kind"], row["family"], row["source_identity"])
                for row in source_rows
            }
        ),
        "every_s7_source_linked_individually": all(
            row["lowered"]
            and row["admitted"]
            and row["executable"]
            and row["validated"]
            and bool(row["lowered_node_ids"])
            for row in source_rows
            if row["stage"] == "s7"
        ),
        "mixed_graphs_nonempty": bool(mixed_graphs),
        "mixed_graphs_blocked": bool(mixed_graphs)
        and all(
            graph.blocked_reason
            == "equipment_ability_nested_modifier_graph_deferred_to_p8_s8"
            for graph in mixed_graphs
        ),
        "pure_s7_graphs_nonempty": any(
            graph.coverage_status == "executable" for graph in bundle["graphs"]
        ),
    }
    gap_count = sum(row["gap_count"] for row in rows)
    checks["ok"] = all(checks.values()) and gap_count == 0
    return {
        "schema_version": "p8_s7_family_coverage_matrix_v2",
        "ok": checks["ok"],
        "gap_count": gap_count,
        "checks": checks,
        "rows": rows,
        "source_rows": source_rows,
    }


def _coverage_source_indexes(bundle: dict[str, Any]) -> dict[str, Any]:
    selected_task_ids = _selected_executable_task_ids(bundle)
    tasks: dict[str, list[Any]] = defaultdict(list)
    for task in (*bundle["tasks"], *bundle["callback_tasks"]):
        identity = _task_source_identity(task)
        if identity:
            tasks[identity].append(task)
    callbacks: dict[str, list[Any]] = defaultdict(list)
    for callback in bundle["callbacks"]:
        identity = _callback_source_identity(callback)
        if identity:
            callbacks[identity].append(callback)
    conditions: dict[str, list[Any]] = defaultdict(list)
    for condition in bundle["nested_conditions"]:
        identity = _task_source_identity_from_source(condition.source)
        if identity:
            conditions[f"{identity}.Predicate"].append(condition)
    targets: dict[str, list[Any]] = defaultdict(list)
    for target in bundle["targets"]:
        identity = _task_source_identity_from_source(target.source)
        field_name = target.source.evidence.get("target_expression_field")
        if identity and isinstance(field_name, str) and field_name:
            targets[f"{identity}.{field_name}"].append(target)
    return {
        "tasks": tasks,
        "callbacks": callbacks,
        "conditions": conditions,
        "targets": targets,
        "selected_task_ids": selected_task_ids,
    }


def _source_coverage_row(
    raw_row: dict[str, str],
    indexes: dict[str, Any],
    validation_families: dict[str, set[str]],
) -> dict[str, Any]:
    kind = raw_row["kind"]
    family = raw_row["family"]
    stage = raw_row["stage"]
    identity = _normalize_source_identity(raw_row["source_identity"])
    base_family = family.split(":", 1)[0]
    linked: list[Any] = []
    if kind == "task":
        linked = list(indexes["tasks"].get(identity, ()))
    elif kind == "event":
        linked = list(indexes["callbacks"].get(identity, ()))
    elif kind == "condition":
        owner_identity = _longest_source_prefix(identity, indexes["conditions"])
        linked = [
            condition
            for condition in indexes["conditions"].get(owner_identity, ())
            if _condition_has_family(condition, base_family)
        ]
    elif kind == "target":
        linked = list(indexes["targets"].get(identity, ()))
        if not linked:
            owner_identity = _longest_source_prefix(identity, indexes["conditions"])
            linked = [
                condition
                for condition in indexes["conditions"].get(owner_identity, ())
                if _condition_has_target_family(condition, family)
            ]
    elif kind == "value":
        owner_identity = _longest_source_prefix(identity, indexes["tasks"])
        linked = list(indexes["tasks"].get(owner_identity, ()))

    node_ids = [_coverage_node_id(node) for node in linked]
    lowered = len(linked) == 1
    selected_task_ids: set[str] = indexes["selected_task_ids"]
    if kind in {"task", "value"}:
        admitted = lowered and linked[0].task_id in selected_task_ids
        executable = admitted and linked[0].coverage_status == "executable"
    elif kind == "event":
        admitted = lowered and linked[0].admission_status == "executable"
        executable = admitted and linked[0].coverage_status == "executable"
    elif kind == "condition":
        admitted = lowered and linked[0].coverage_status == "executable"
        executable = admitted and _condition_payload_executable(
            linked[0].opcode, linked[0].payload
        )
    elif kind == "target":
        admitted = lowered and linked[0].coverage_status == "executable"
        executable = admitted
    else:
        admitted = False
        executable = False
    runtime_family = (
        family
        if kind == "target"
        else family.rsplit(":", 1)[0]
        if kind == "task"
        else base_family
    )
    runtime_validated = runtime_family in validation_families.get(kind, set())
    if kind == "value":
        runtime_validated = raw_row.get("validated") == "true"
    validated = executable and runtime_validated
    if stage != "s7":
        admitted = False
        executable = False
        validated = raw_row.get("validated") == "true" if kind == "value" else lowered
    gap_reasons = []
    if stage == "s7":
        if not lowered:
            gap_reasons.append(f"lowered_node_count:{len(linked)}")
        if not admitted:
            gap_reasons.append("not_admitted")
        if not executable:
            gap_reasons.append("not_executable")
        if not validated:
            gap_reasons.append("runtime_validation_missing")
    return {
        **raw_row,
        "source_identity": identity,
        "lowered": lowered,
        "admitted": admitted,
        "executable": executable,
        "validated": validated,
        "lowered_node_ids": node_ids,
        "gap_reasons": gap_reasons,
    }


def _runtime_validation_families(
    *,
    conditions: dict[str, Any],
    dynamic_tasks: dict[str, Any],
    targets: dict[str, Any],
    lifecycle: dict[str, Any],
    events: dict[str, Any],
    effective_stats: dict[str, Any],
) -> dict[str, set[str]]:
    condition_families = {
        row["family"]
        for row in conditions["runtime_family_rows"]
        if row["true_result_count"] > 0
        and row["false_result_count"] > 0
        and row["unadmitted_blocked"] is True
    }
    dynamic_families = {
        row["family"] for row in dynamic_tasks["rows"] if row.get("ok") is True
    }
    task_families = set(dynamic_families)
    if lifecycle["checks"].get("add"):
        task_families.add("AddModifier")
    if lifecycle["checks"].get("remove_families"):
        task_families.update({"RemoveModifier", "RemoveSelfModifier"})
    if conditions.get("ok"):
        task_families.add("PredicateTaskList")
    if effective_stats.get("ok"):
        task_families.update({"DefineDynamicValue", "SetModifierDynamicValue"})
    return {
        "task": task_families,
        "event": {
            row["event"]
            for row in events["rows"]
            if row.get("dispatch_chain_ok") is True
        },
        "condition": condition_families,
        "target": {
            f"TargetAlias:{row['alias']}"
            for row in targets["rows"]
            if row.get("ok") is True
        },
        "value": {"runtime_numeric_expression"},
    }


def _task_source_identity(task: Any) -> str:
    return _task_source_identity_from_source(task.source)


def _task_source_identity_from_source(source: Any) -> str:
    evidence = source.evidence if isinstance(source.evidence, dict) else {}
    callback_path = evidence.get("callback_json_path")
    task_path = evidence.get("task_path")
    if isinstance(callback_path, str) and isinstance(task_path, str):
        return _normalize_source_identity(
            f"{source.source_path}#{callback_path}.{task_path}"
        )
    ability_context = evidence.get("ability_source_context")
    ability_path = (
        ability_context.get("ability_json_path")
        if isinstance(ability_context, dict)
        else None
    )
    if isinstance(ability_path, str) and isinstance(task_path, str):
        return _normalize_source_identity(
            f"{source.source_path}#{ability_path}.{task_path}"
        )
    return ""


def _callback_source_identity(callback: Any) -> str:
    callback_path = callback.source.evidence.get("callback_json_path")
    if not isinstance(callback_path, str):
        return ""
    return _normalize_source_identity(
        f"{callback.source.source_path}#{callback_path}"
    )


def _normalize_source_identity(identity: str) -> str:
    return identity.replace("#$.", "#")


def _longest_source_prefix(identity: str, mapping: dict[str, Any]) -> str:
    candidates = [
        key for key in mapping if identity == key or identity.startswith(f"{key}.")
    ]
    return max(candidates, key=len, default="")


def _condition_has_family(condition: ConditionIR, family: str) -> bool:
    return condition.opcode == family or any(
        node.get("opcode") == family
        for node in _typed_condition_nodes(condition.payload)
    )


def _condition_has_target_family(condition: ConditionIR, family: str) -> bool:
    alias = family.removeprefix("TargetAlias:")
    return alias in _condition_target_aliases(condition.payload)


def _condition_target_aliases(value: object) -> set[str]:
    aliases: set[str] = set()
    if isinstance(value, TargetExpressionNodeIR):
        if value.alias:
            aliases.add(value.alias)
        for child in value.children:
            aliases.update(_condition_target_aliases(child))
        for child in (
            value.candidate,
            value.target,
            value.query_target,
            value.query_compare,
        ):
            if child is not None:
                aliases.update(_condition_target_aliases(child))
        if value.predicate is not None:
            aliases.update(_condition_target_aliases(value.predicate.payload))
        return aliases
    if isinstance(value, ConditionIR):
        return _condition_target_aliases(value.payload)
    if isinstance(value, dict):
        for key in ("alias", "Alias"):
            alias = value.get(key)
            if isinstance(alias, str) and alias:
                aliases.add(alias)
        for child in value.values():
            aliases.update(_condition_target_aliases(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            aliases.update(_condition_target_aliases(child))
    return aliases


def _coverage_node_id(node: Any) -> str:
    for field_name in (
        "task_id",
        "callback_id",
        "condition_id",
        "target_expression_id",
    ):
        value = getattr(node, field_name, None)
        if isinstance(value, str) and value:
            return value
    return type(node).__name__


def _validated_s7_count(
    bundle: dict[str, Any],
    kind: str,
    family: str,
    raw_count: int,
    raw_validated_count: int,
) -> int:
    base_family = family.split(":", 1)[0]
    if kind == "task":
        selected_task_ids = _selected_executable_task_ids(bundle)
        callback_count = sum(
            task.opcode == base_family
            and task.coverage_status == "executable"
            and task.task_id in selected_task_ids
            and classify_equipment_task(
                task.opcode,
                task.source.evidence.get("task", {}),
            )
            == "s7"
            for task in bundle["callback_tasks"]
        )
        top_count = sum(
            task.opcode == base_family
            and task.coverage_status == "executable"
            and task.task_id in selected_task_ids
            for task in bundle["tasks"]
        )
        return min(raw_count, callback_count + top_count)
    if kind == "event":
        event = base_family
        family_rows = [
            row
            for row in bundle["event_families"]
            if row.callback_event == event
        ]
        if (
            len(family_rows) != 1
            or family_rows[0].coverage_status != "executable"
            or family_rows[0].admission_status != "executable"
            or not family_rows[0].runtime_event_sources
        ):
            return 0
        return min(raw_count, sum(
            callback.event == event
            and callback.coverage_status == "executable"
            and callback.admission_status == "executable"
            for callback in bundle["callbacks"]
            if classify_equipment_family("event", callback.event) == "s7"
        ))
    if kind == "condition":
        return min(
            raw_count,
            _condition_family_structurally_valid_count(bundle, base_family),
        )
    if kind == "target":
        if not family.startswith("TargetAlias:"):
            return 0
        alias = family.removeprefix("TargetAlias:")
        return min(
            raw_count,
            sum(
                target.expression_kind == "TargetAlias"
                and target.alias == alias
                and target.coverage_status == "executable"
                for target in bundle["targets"]
            ),
        )
    if kind == "value":
        return min(raw_count, raw_validated_count)
    return 0


def _condition_family_structurally_valid_count(
    bundle: dict[str, Any],
    family: str,
) -> int:
    selected_task_ids = _selected_executable_task_ids(bundle)
    executable_condition_ids = {
        task.condition_id
        for task in (*bundle["tasks"], *bundle["callback_tasks"])
        if task.task_id in selected_task_ids
        and task.coverage_status == "executable"
        and task.condition_id
    }
    count = 0
    for condition in bundle["nested_conditions"]:
        if (
            condition.condition_id not in executable_condition_ids
            or condition.coverage_status != "executable"
        ):
            continue
        if (
            condition.opcode == family
            and _condition_payload_executable(condition.opcode, condition.payload)
        ):
            count += 1
        count += sum(
            node.get("opcode") == family and node.get("supported") is True
            for node in _typed_condition_nodes(condition.payload)
        )
    return count


def _selected_executable_task_ids(bundle: dict[str, Any]) -> set[str]:
    executable_phase_ids = {
        phase_id
        for graph in bundle["graphs"]
        if graph.coverage_status == "executable"
        for phase_id in graph.phase_ids
    }
    executable_callback_ids = {
        callback.callback_id
        for callback in bundle["callbacks"]
        if callback.coverage_status == "executable"
        and callback.admission_status == "executable"
    }
    return {
        task.task_id
        for task in bundle["tasks"]
        if task.phase_id in executable_phase_ids
        and task.coverage_status == "executable"
    } | {
        task.task_id
        for task in bundle["callback_tasks"]
        if task.callback_id in executable_callback_ids
        and task.coverage_status == "executable"
    }


def _typed_condition_nodes(value: object) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if (
            isinstance(value.get("opcode"), str)
            and value.get("schema_version") == "hsr.condition_expression_node.v1"
        ):
            rows.append(value)
        for child in value.values():
            rows.extend(_typed_condition_nodes(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            rows.extend(_typed_condition_nodes(child))
    return tuple(rows)


def _formal_scenario_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    cards = {
        card.card_id: card for card in bundle["characters"].character_data_cards
    }
    eligibilities = bundle["characters"].character_equipment_eligibilities
    eligible_by_path: dict[str, list[Any]] = defaultdict(list)
    for eligibility in eligibilities:
        eligible_by_path[eligibility.character_path_type].append(eligibility)
    graph_by_id = {
        graph.standalone_ability_graph_id: graph for graph in bundle["graphs"]
    }
    candidates = []
    for definition in bundle["definitions"]:
        if not definition.mechanism_ref_ids:
            continue
        mechanism = rules.equipment_mechanism_ref(
            definition.mechanism_ref_ids[0].definition_identity
        ).value
        if mechanism is None:
            continue
        graph = graph_by_id.get(mechanism.graph_ref_id)
        if graph is None or graph.coverage_status != "executable":
            continue
        for eligibility in eligible_by_path.get(definition.path_type, ()):
            card = cards.get(eligibility.character_card_id)
            if card is not None:
                candidates.append((definition, card))
    errors = []
    for definition, card in sorted(
        candidates,
        key=lambda item: (
            0 if _definition_startup_has_duration(bundle, item[0]) else 1,
            item[0].ability_source.source.source_path,
            item[0].ability_source.record_index,
            item[1].card_id,
        ),
    ):
        equipment_build, equipment_result = _assembly(
            rules,
            card.card_id,
            definition,
            instance_id="validation:p8_s7:formal-light-cone",
            rank=1,
        )
        character_build = _character_build(
            card.card_id,
            "formal-s7",
            equipment_build,
        )
        character_result = assemble_character_build(rules, character_build)
        peer_card = next(
            (
                cards[item.character_card_id]
                for item in eligible_by_path.get(definition.path_type, ())
                if item.character_card_id != card.card_id
                and item.character_card_id in cards
            ),
            None,
        )
        if peer_card is None:
            continue
        peer_equipment_build, peer_equipment_result = _assembly(
            rules,
            peer_card.card_id,
            definition,
            instance_id="validation:p8_s7:formal-light-cone:peer",
            rank=1,
        )
        peer_character_build = _character_build(
            peer_card.card_id,
            "formal-s7-peer",
            peer_equipment_build,
        )
        peer_character_result = assemble_character_build(
            rules,
            peer_character_build,
        )
        if (
            equipment_result.battle_admission_status != "admitted"
            or character_result.battle_admission_status != "admitted"
            or peer_equipment_result.battle_admission_status != "admitted"
            or peer_character_result.battle_admission_status != "admitted"
        ):
            continue
        scenario = ScenarioSpec(
            scenario_id="validation:p8_s7:formal-status-listener",
            version=BASELINE_VERSION,
            units=(
                UnitSpec(
                    unit_id="ally:wearer",
                    side="ally",
                    entity_ref=card.entity_ref,
                    build_mode="assembled_character_build",
                    level=character_build.level,
                    eidolon_level=character_build.eidolon_level,
                    panel=None,
                    character_build=character_build,
                    initial_condition=CharacterInitialConditionInput(
                        hp_mode="full",
                        initial_energy="0",
                    ),
                ),
                UnitSpec(
                    unit_id="ally:wearer:peer",
                    side="ally",
                    entity_ref=peer_card.entity_ref,
                    build_mode="assembled_character_build",
                    level=peer_character_build.level,
                    eidolon_level=peer_character_build.eidolon_level,
                    panel=None,
                    character_build=peer_character_build,
                    initial_condition=CharacterInitialConditionInput(
                        hp_mode="full",
                        initial_energy="0",
                    ),
                ),
            ),
            route=(),
            battle_setup=BattleSetupSpec(
                timeline=TimelineSetupSpec(mode="runtime_initialize")
            ),
        )
        try:
            built = ScenarioStateBuilder(rules).build(scenario)
            rebuilt = ScenarioStateBuilder(rules).build(scenario)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        wearer_ids = ("ally:wearer", "ally:wearer:peer")
        providers_by_wearer = {
            wearer_id: built.state.units[wearer_id].flags.get(
                "ability_providers", ()
            )
            for wearer_id in wearer_ids
        }
        details_by_wearer = {
            wearer_id: built.state.units[wearer_id].flags.get(
                "status_details", ()
            )
            for wearer_id in wearer_ids
        }
        providers = providers_by_wearer["ally:wearer"]
        details = details_by_wearer["ally:wearer"]
        startup_traces = tuple(
            trace
            for trace in built.source_traces
            if trace.get("kind") == "formal_equipment_ability"
        )
        checks = {
            "formal_build_admitted": True,
            "provider_registered_once": all(
                isinstance(items, (list, tuple)) and len(items) == 1
                for items in providers_by_wearer.values()
            ),
            "startup_status_applied": all(
                isinstance(items, (list, tuple)) and bool(items)
                for items in details_by_wearer.values()
            ),
            "status_owned_by_wearer": all(
                isinstance(detail, dict)
                and detail.get("owner_id") == wearer_id
                and detail.get("caster_id") == wearer_id
                for wearer_id, wearer_details in details_by_wearer.items()
                for detail in wearer_details
            ),
            "multi_wearer_instances_do_not_alias": len(
                {
                    str(detail.get("instance_id") or "")
                    for wearer_details in details_by_wearer.values()
                    for detail in wearer_details
                    if isinstance(detail, dict)
                }
            )
            == sum(len(items) for items in details_by_wearer.values()),
            "startup_listeners_registered": isinstance(details, (list, tuple))
            and any(
                isinstance(detail, dict)
                and isinstance(detail.get("trigger_ids_by_event"), dict)
                and bool(detail.get("trigger_ids_by_event"))
                for detail in details
            ),
            "duration_source_admitted": isinstance(details, (list, tuple))
            and any(
                isinstance(detail, dict)
                and isinstance(detail.get("duration_admission"), dict)
                and detail["duration_admission"].get("admission_status")
                == "executable"
                for detail in details
            ),
            "rebuild_is_deterministic_and_single_provider": (
                built.state.snapshot().to_json()
                == rebuilt.state.snapshot().to_json()
                and all(
                    len(
                        rebuilt.state.units[wearer_id].flags.get(
                            "ability_providers", ()
                        )
                    )
                    == 1
                    for wearer_id in wearer_ids
                )
            ),
        }
        setup_replay = _public_setup_replay(built)
        setup_source_audit = _public_setup_source_audit(
            built,
            bundle["rules"],
        )
        setup_mutation_ids = {
            mutation.stable_id() for mutation in built.setup_mutations
        }
        recorded_mutation_ids = {
            str(record.get("mutation_id") or "")
            for record in built.setup_records
            if isinstance(record, dict) and record.get("mutation_id")
        }
        checks.update(
            {
                "public_setup_mutations_replay_final_state": setup_replay["ok"],
                "public_setup_mutations_have_settlement": bool(setup_mutation_ids)
                and setup_mutation_ids <= recorded_mutation_ids,
                "public_setup_mutations_source_audited": setup_source_audit["ok"],
                "startup_events_exported": bool(built.setup_events),
            }
        )
        checks["ok"] = all(checks.values())
        return {
            "schema_version": "p8_s7_formal_scenario_event_attribution_v1",
            "ok": checks["ok"],
            "checks": checks,
            "definition_identity": definition.definition_key.definition_identity,
            "character_card_id": card.card_id,
            "peer_character_card_id": peer_card.card_id,
            "graph_ref_id": equipment_result.dynamic_mechanisms[0].graph_ref_id,
            "equipment_result": equipment_result.to_json(),
            "character_result": character_result.to_json(),
            "peer_character_result": peer_character_result.to_json(),
            "startup_traces": startup_traces,
            "public_setup_replay": setup_replay,
            "public_setup_source_audit": setup_source_audit,
            "setup_mutation_count": len(built.setup_mutations),
            "setup_record_count": len(built.setup_records),
            "setup_event_count": len(built.setup_events),
            "setup_rng_event_count": len(built.setup_rng_events),
            "status_details": details,
            "errors_before_sample": errors,
        "_built": built,
        "_scenario": scenario,
        "_character_build": character_build,
        "_equipment_result": equipment_result,
        "_unit_id": "ally:wearer",
        }
    raise ValueError(f"no naturally admitted P8-S7 formal scenario: {errors[:5]}")


def _public_setup_replay(built: Any) -> dict[str, Any]:
    reducer = MutationReducer()
    current = built.state
    try:
        for mutation in reversed(built.setup_mutations):
            inverse = _inverse_setup_mutation(mutation)
            current = reducer.apply(current, inverse)
        replay = reducer.replay_snapshot(
            current,
            built.setup_mutations,
            built.state.snapshot().to_json(),
        )
    except (ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": replay.ok,
        "mutation_count": len(built.setup_mutations),
        "errors": list(replay.errors),
        "reconstructed_before_snapshot": current.snapshot().to_json(),
    }


def _public_setup_source_audit(
    built: Any,
    rules: RuleBook,
) -> dict[str, Any]:
    reducer = MutationReducer()
    before_state = built.state
    try:
        for mutation in reversed(built.setup_mutations):
            before_state = reducer.apply(
                before_state,
                _inverse_setup_mutation(mutation),
            )
    except (ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}
    transition = BattleTransition(
        transaction=ActionTransaction(
            command=ActionCommand(
                actor_id="scenario:setup",
                action_id="scenario:setup",
                action_level=0,
                source="scenario_setup",
            ),
            before=before_state.snapshot(),
            events=tuple(built.setup_events),
            mutations=tuple(built.setup_mutations),
            settlement=ActionSettlement(
                action_id="scenario:setup",
                actor_id="scenario:setup",
                target_ids=(),
                records=tuple(built.setup_records),
            ),
        ),
        after=built.state.snapshot(),
        rng_events=tuple(built.setup_rng_events),
    )
    result = RuntimeSourceAuditor(rules).validate_transition(transition)
    return {
        "ok": result.ok,
        "checked_mutations": result.checked_mutations,
        "checked_records": result.checked_records,
        "violation_count": len(result.violations),
        "violations": [
            violation.to_json() for violation in result.violations[:8]
        ],
        "trace_count": len(result.traces),
    }


def _inverse_setup_mutation(mutation: Mutation) -> Mutation:
    if mutation.op == "spawn":
        raise ValueError("setup replay probe does not accept spawn mutations")
    if mutation.op == "delete":
        return replace(
            mutation,
            op="set",
            before=None,
            after=mutation.before,
            before_exists=False,
            after_exists=True,
            mutation_id="",
        )
    if mutation.before_exists:
        return replace(
            mutation,
            op="set",
            before=mutation.after,
            after=mutation.before,
            before_exists=True,
            after_exists=True,
            mutation_id="",
        )
    return replace(
        mutation,
        op="delete",
        before=mutation.after,
        after=None,
        before_exists=True,
        after_exists=False,
        mutation_id="",
    )


def _definition_startup_has_duration(
    bundle: dict[str, Any],
    definition: Any,
) -> bool:
    if not definition.mechanism_ref_ids:
        return False
    mechanism = bundle["rules"].equipment_mechanism_ref(
        definition.mechanism_ref_ids[0].definition_identity
    ).value
    if mechanism is None:
        return False
    graph = bundle["rules"].standalone_ability_graph(mechanism.graph_ref_id)
    if graph is None or graph.coverage_status != "executable":
        return False
    for phase_id in graph.phase_ids:
        for task in bundle["rules"].ability_tasks_for_phase(phase_id):
            effect = bundle["rules"].effect(task.effect_id) if task.effect_id else None
            standard = effect.payload.get("standard") if effect is not None else None
            if (
                isinstance(standard, dict)
                and isinstance(standard.get("lifetime"), dict)
                and standard["lifetime"].get("kind") != "missing"
            ):
                return True
    return False


def _condition_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    evaluator = RuleEvaluator()
    state = BattleState(
        units={
            "enemy:removed": UnitState(
                unit_id="enemy:removed",
                side="enemy",
                template_id="validation:enemy-removed",
                max_hp=100.0,
                hp=100.0,
                flags={"lifecycle_status": "removed"},
            ),
            "ally:wearer": UnitState(
                unit_id="ally:wearer",
                side="ally",
                template_id="validation:ally",
                max_hp=100.0,
                hp=100.0,
                flags={"character_id": 1},
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="validation:enemy",
                max_hp=100.0,
                hp=50.0,
                flags={"monster_id": 2},
            ),
        },
        global_flags={"turn_owner_id": "ally:wearer"},
    )
    sample = next(
        condition
        for condition in bundle["nested_conditions"]
        if condition.opcode == "ByTargetTeam"
        and condition.coverage_status == "executable"
    )
    team = sample.payload.get("Team")
    true_target = "enemy:target" if team == "TeamDark" else "ally:wearer"
    false_target = "ally:wearer" if true_target == "enemy:target" else "enemy:target"
    true_result = evaluator.evaluate_condition_result(
        sample,
        EvaluationContext(
            state=state,
            actor_id="ally:wearer",
            owner_id="ally:wearer",
            target_id=true_target,
            param_entity_id=true_target,
            current_action_target_id=true_target,
        ),
    )
    false_result = evaluator.evaluate_condition_result(
        sample,
        EvaluationContext(
            state=state,
            actor_id="ally:wearer",
            owner_id="ally:wearer",
            target_id=false_target,
            param_entity_id=false_target,
            current_action_target_id=false_target,
        ),
    )
    malformed = replace(
        sample,
        payload={"TargetType": "UnknownTarget", "Team": team},
    )
    blocked_result = evaluator.evaluate_condition_result(
        malformed,
        EvaluationContext(state=state, actor_id="ally:wearer"),
    )
    selected_task_ids = _selected_executable_task_ids(bundle)
    executable_condition_ids = {
        task.condition_id
        for task in (*bundle["tasks"], *bundle["callback_tasks"])
        if task.task_id in selected_task_ids and task.condition_id
    }
    s7_conditions = tuple(
        condition
        for condition in bundle["nested_conditions"]
        if condition.coverage_status == "executable"
        and condition.condition_id in executable_condition_ids
    )
    structural_rows = [
        {
            "condition_id": condition.condition_id,
            "opcode": condition.opcode,
            "source": condition.source.to_json(),
            "payload_executable": _condition_payload_executable(
                condition.opcode,
                condition.payload,
            ),
        }
        for condition in s7_conditions
    ]
    runtime_family_rows = _condition_runtime_family_rows(s7_conditions)
    missing_event_context_rows = []
    for family in ("ByCurrentSkillType", "ByAttackType"):
        candidate = next(
            (condition for condition in s7_conditions if condition.opcode == family),
            None,
        )
        if candidate is None:
            missing_event_context_rows.append(
                {"family": family, "ok": False, "reason": "real_condition_missing"}
            )
            continue
        missing = evaluator.evaluate_condition_result(
            candidate,
            EvaluationContext(
                state=state,
                actor_id="ally:wearer",
                owner_id="ally:wearer",
                target_id="enemy:target",
                param_entity_id="enemy:target",
                event_payload={},
            ),
        )
        missing_event_context_rows.append(
            {
                "family": family,
                "ok": not missing.ok and missing.result is None,
                "result": missing.to_json(),
                "source": candidate.source.to_json(),
            }
        )
    revivable_condition = next(
        (
            condition
            for condition in bundle["nested_conditions"]
            if condition.opcode == "ByTargetAliveState"
            and condition.payload.get("AliveStateMask")
            == "Mask_AliveOrRevivable"
        ),
        None,
    )
    revivable_result = (
        evaluator.evaluate_condition_result(
            replace(revivable_condition, coverage_status="executable"),
            EvaluationContext(
                state=state,
                actor_id="ally:wearer",
                owner_id="ally:wearer",
                target_id="enemy:target",
                param_entity_id="enemy:target",
            ),
        )
        if revivable_condition is not None
        else None
    )
    revivable_row = {
        "ok": revivable_condition is not None
        and classify_equipment_condition(
            "ByTargetAliveState",
            dict(revivable_condition.payload),
        )
        == "s8"
        and not _condition_payload_executable(
            "ByTargetAliveState",
            dict(revivable_condition.payload),
        )
        and revivable_result is not None
        and not revivable_result.ok
        and revivable_result.result is None
        and revivable_result.reason
        == "revivable_lifecycle_state_not_available",
        "condition": (
            revivable_condition.to_json()
            if revivable_condition is not None
            else None
        ),
        "runtime_result": (
            revivable_result.to_json() if revivable_result is not None else None
        ),
        "expected_stage": "s8",
    }
    checks = {
        "true_branch_committed": true_result.ok and true_result.result is True,
        "false_is_committed_no_effect": false_result.ok
        and false_result.result is False,
        "missing_structure_blocked": not blocked_result.ok
        and blocked_result.result is None,
        "all_executable_condition_payloads_typed": all(
            row["payload_executable"] for row in structural_rows
        ),
        "all_condition_sources_real": all(
            row["source"]["source_path"].startswith("Config/ConfigAbility/Equip/")
            for row in structural_rows
        ),
        "all_condition_families_execute_true_and_false": bool(
            runtime_family_rows
        )
        and all(
            row["true_result_count"] > 0 and row["false_result_count"] > 0
            for row in runtime_family_rows
        ),
        "all_condition_families_fail_closed_when_unadmitted": all(
            row["unadmitted_blocked"] is True for row in runtime_family_rows
        ),
        "skill_and_attack_type_missing_context_blocked": all(
            row["ok"] is True for row in missing_event_context_rows
        ),
        "alive_or_revivable_is_deferred_and_fail_closed": revivable_row["ok"],
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s7_condition_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "true": true_result.to_json(),
        "false": false_result.to_json(),
        "blocked": blocked_result.to_json(),
        "structural_rows": structural_rows,
        "runtime_family_rows": runtime_family_rows,
        "missing_event_context_rows": missing_event_context_rows,
        "alive_or_revivable": revivable_row,
    }


def _condition_runtime_family_rows(
    conditions: tuple[ConditionIR, ...],
) -> list[dict[str, Any]]:
    evaluator = RuleEvaluator()
    by_family: dict[str, list[tuple[ConditionIR, str]]] = defaultdict(list)
    for condition in conditions:
        by_family[condition.opcode].append((condition, "root"))
        for index, node in enumerate(_typed_condition_nodes(condition.payload)):
            opcode = node.get("opcode")
            if not isinstance(opcode, str) or not opcode:
                continue
            payload = {
                key: value
                for key, value in node.items()
                if key
                not in {
                    "blocked_reason",
                    "expression_kind",
                    "opcode",
                    "schema_version",
                    "supported",
                }
            }
            by_family[opcode].append(
                (
                    replace(
                        condition,
                        condition_id=f"{condition.condition_id}:node:{index}:{opcode}",
                        opcode=opcode,
                        payload=payload,
                    ),
                    f"typed_node[{index}]",
                )
            )
    rows: list[dict[str, Any]] = []
    for family, candidates in sorted(by_family.items()):
        results: list[dict[str, Any]] = []
        for condition, node_path in candidates:
            for context_index, context in enumerate(
                _condition_probe_contexts(condition)
            ):
                result = evaluator.evaluate_condition_result(condition, context)
                results.append(
                    {
                        "condition_id": condition.condition_id,
                        "node_path": node_path,
                        "context_index": context_index,
                        "ok": result.ok,
                        "result": result.result,
                        "reason": result.reason,
                        "source_path": condition.source.source_path,
                    }
                )
        representative = candidates[0][0]
        blocked = evaluator.evaluate_condition_result(
            replace(
                representative,
                coverage_status="blocked",
                blocked_reason="validation_unadmitted_condition",
            ),
            _condition_probe_contexts(representative)[0],
        )
        rows.append(
            {
                "family": family,
                "real_source_count": len(candidates),
                "true_result_count": sum(
                    row["ok"] is True and row["result"] is True
                    for row in results
                ),
                "false_result_count": sum(
                    row["ok"] is True and row["result"] is False
                    for row in results
                ),
                "blocked_probe_count": sum(
                    row["ok"] is False and row["result"] is None
                    for row in results
                ),
                "unadmitted_blocked": not blocked.ok
                and blocked.result is None,
                "representative_source": {
                    "source_path": representative.source.source_path,
                    "raw_type": representative.source.raw_type,
                    "raw_id": representative.source.raw_id,
                    "callback_json_path": representative.source.evidence.get(
                        "callback_json_path"
                    ),
                    "task_path": representative.source.evidence.get("task_path"),
                },
                "sample_results": results[:8],
            }
        )
    return rows


def _condition_probe_contexts(
    condition: ConditionIR,
) -> tuple[EvaluationContext, ...]:
    payload = condition.payload
    modifier_names = _condition_string_values(payload, "ModifierName")
    behavior_flags = {
        *_condition_string_values(payload, "Flag"),
        "Shield",
        "STAT_TriggerBattleCharacter",
    }
    dynamic_names = _condition_string_values(payload, "DynamicKey")
    dynamic_hashes = _condition_dynamic_hashes(payload)
    expected_character_ids = _condition_fixed_values(
        payload,
        "TargetCharacterID",
    )
    character_id = int(expected_character_ids[0]) if expected_character_ids else 1313
    skill_types = _condition_string_values(payload, "SkillType")
    attack_types = _condition_list_strings(payload, "AttackTypes")
    skill_names = _condition_string_values(payload, "SkillName")
    status_types = {
        *_condition_string_values(payload, "TargetStatusType"),
        *_condition_string_values(payload, "StatusType"),
    }
    expected_team_dark = "TeamDark" in _condition_string_values(payload, "Team")

    contexts: list[EvaluationContext] = []
    for mode in range(4):
        rich = mode in {0, 2}
        alive = mode != 3
        param_id = (
            ("enemy:target" if expected_team_dark else "ally:wearer")
            if rich
            else ("ally:wearer" if expected_team_dark else "enemy:target")
        )
        stacks = (0, 1, 3, 1)[mode]
        detail = {
            "instance_id": "validation:p8_s7:condition-status",
            "modifier_name": min(modifier_names, default="validation_modifier"),
            "owner_id": "ally:wearer",
            "caster_id": "ally:wearer",
            "stacks": stacks,
            "max_stacks": 3,
            "duration": 2,
            "remaining_duration": 2,
            "status_type": min(status_types, default="Debuff"),
            "status_category": "debuff",
            "behavior_flags": sorted(behavior_flags if rich else ()),
            "dynamic_values": {
                key: (1.0 if rich else 2.0) for key in dynamic_names
            },
        }
        status_details = [
            {**detail, "modifier_name": modifier_name}
            for modifier_name in sorted(modifier_names or {"validation_modifier"})
        ]
        wearer = UnitState(
            unit_id="ally:wearer",
            side="ally",
            template_id=f"avatar:{character_id}",
            max_hp=100.0,
            hp=100.0 if alive and rich else (1.0 if alive else 0.0),
            shield_instances=(
                ({"shield_id": "validation:shield", "remaining": 10.0},)
                if rich
                else ()
            ),
            statuses=tuple(sorted(modifier_names)) if rich else (),
            flags={
                "character_id": character_id if rich else character_id + 1,
                "behavior_flags": sorted(behavior_flags if rich else ()),
                "status_details": status_details if rich else [],
            },
            resources={"break_damage_added_ratio": 1.0 if rich else 0.0},
        )
        teammate = UnitState(
            unit_id="ally:teammate",
            side="ally",
            template_id="validation:teammate",
            flags={"behavior_flags": sorted(behavior_flags if rich else ())},
        )
        enemy = UnitState(
            unit_id="enemy:target",
            side="enemy",
            template_id="validation:enemy",
            max_hp=100.0,
            hp=100.0 if alive else 0.0,
            flags={
                "behavior_flags": sorted(behavior_flags if rich else ()),
                "status_details": status_details if rich else [],
            },
        )
        state = BattleState(
            units={
                wearer.unit_id: wearer,
                teammate.unit_id: teammate,
                enemy.unit_id: enemy,
            }
        )
        dynamic_values = {
            **{str(value_hash): 1.0 for value_hash in dynamic_hashes},
            **{
                key: (1.0 if rich else 2.0)
                for key in dynamic_names
            },
        }
        event_payload = {
            "SkillType": min(skill_types, default="Ultra") if rich else "Other",
            "skill_type": min(skill_types, default="Ultra") if rich else "Other",
            "AttackType": min(attack_types, default="Normal") if rich else "Other",
            "attack_type": min(attack_types, default="Normal") if rich else "Other",
            "skill_name": min(skill_names, default="Skill11") if rich else "Other",
            "modifier_name": min(modifier_names, default="validation_modifier") if rich else "Other",
            "status_type": min(status_types, default="Debuff") if rich else "Other",
            "behavior_flags": sorted(behavior_flags if rich else ()),
            "is_self": rich,
            "status_instance_id": detail["instance_id"] if rich else "other",
            "turn_owner_id": "ally:wearer" if rich else "enemy:target",
            "damage_defender_id": param_id,
            "current_hit_target_id": param_id,
            "param_entity_skill_target_ids": [param_id],
            "skill_target_ids": [param_id],
            "attack_target_ids": [param_id],
            "selected_target_ids": [param_id],
            "target_ids": [param_id],
        }
        contexts.append(
            EvaluationContext(
                state=state,
                actor_id="ally:wearer",
                target_id=param_id,
                owner_id="ally:wearer",
                param_entity_id=param_id,
                current_action_target_id=param_id,
                status_detail=detail,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                resolved_target_groups={
                    "AttackTargetList": (param_id,),
                    "ParamEntitySkillTargetEntityList": (param_id,),
                    "SkillTargetEntityList": (param_id,),
                },
            )
        )
    return tuple(contexts)


def _condition_string_values(value: object, key: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        if key in value:
            raw = value[key]
            if isinstance(raw, str) and raw:
                result.add(raw)
            elif isinstance(raw, dict):
                nested = raw.get("Value")
                if isinstance(nested, str) and nested:
                    result.add(nested)
        for child in value.values():
            result.update(_condition_string_values(child, key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.update(_condition_string_values(child, key))
    return result


def _condition_list_strings(value: object, key: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        raw = value.get(key)
        if isinstance(raw, (list, tuple)):
            result.update(item for item in raw if isinstance(item, str) and item)
        for child in value.values():
            result.update(_condition_list_strings(child, key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.update(_condition_list_strings(child, key))
    return result


def _condition_dynamic_hashes(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        if value.get("kind") == "dynamic_hash":
            result.add(str(value.get("hash")))
        for child in value.values():
            result.update(_condition_dynamic_hashes(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.update(_condition_dynamic_hashes(child))
    return result


def _condition_fixed_values(value: object, key: str) -> list[float]:
    result: list[float] = []
    if isinstance(value, dict):
        raw = value.get(key)
        if isinstance(raw, dict) and raw.get("kind") == "fixed":
            fixed = raw.get("value")
            if isinstance(fixed, (int, float)) and not isinstance(fixed, bool):
                result.append(float(fixed))
        for child in value.values():
            result.extend(_condition_fixed_values(child, key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.extend(_condition_fixed_values(child, key))
    return result


def _structured_dynamic_task_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    selected_task_ids = _selected_executable_task_ids(bundle)
    context_families = {
        "SetDynamicValueByCharacterCount",
        "SetDynamicValueByHPRatio",
        "SetDynamicValueByProperty",
    }
    effect_families = {
        "DefineDynamicValue",
        "SetDynamicValue",
        "SetDynamicValueByModifierValue",
    }
    callbacks_by_id = {
        callback.callback_id: callback for callback in bundle["callbacks"]
    }
    tasks_by_id = {
        task.task_id: task for task in bundle["callback_tasks"]
    }
    system = StatusCallbackSystem(rules)
    rows: list[dict[str, Any]] = []
    for family in sorted(context_families):
        candidates = sorted(
            (
                task
                for task in bundle["callback_tasks"]
                if task.task_id in selected_task_ids
                and task.opcode == family
                and task.callback_id in callbacks_by_id
            ),
            key=lambda item: item.task_id,
        )
        if not candidates:
            rows.append(
                {
                    "family": family,
                    "ok": False,
                    "reason": "real_executable_task_missing",
                }
            )
            continue
        task = candidates[0]
        callback = callbacks_by_id[task.callback_id]
        detail = {
            "instance_id": f"validation:p8_s7:{family}",
            "status_id": f"modifier:{callback.modifier_name}",
            "modifier_name": callback.modifier_name,
            "owner_id": "ally:wearer",
            "caster_id": "ally:wearer",
            "stacks": 1,
            "max_stacks": 3,
            "dynamic_values": {},
            "trigger_ids_by_event": {callback.event: [callback.callback_id]},
            "source_trace": {"callback_source": callback.source.to_json()},
        }
        state = BattleState(
            units={
                "ally:wearer": UnitState(
                    unit_id="ally:wearer",
                    side="ally",
                    template_id="validation:wearer",
                    max_hp=100.0,
                    hp=50.0,
                    speed=123.0,
                    resources={"effect_resistance": 0.4},
                    flags={"status_details": [detail]},
                ),
                "enemy:target": UnitState(
                    unit_id="enemy:target",
                    side="enemy",
                    template_id="validation:enemy",
                    max_hp=100.0,
                    hp=100.0,
                ),
            }
        )
        trigger_event = GameEvent(
            event_id=f"validation:p8_s7:{family}:event",
            event_type=callback.event,
            source_id="ally:wearer",
            target_id="enemy:target",
            window=callback.event,
            process_only=True,
            payload={
                "actor_id": "ally:wearer",
                "target_id": "enemy:target",
                "selected_target_ids": ["enemy:target"],
            },
        )
        result = system._execute_task(
            state,
            callback,
            task,
            detail,
            trigger_event,
            tasks_by_id,
            None,
        )
        missing_state = BattleState()
        missing = system._execute_task(
            missing_state,
            callback,
            task,
            {**detail, "owner_id": "missing:owner", "caster_id": "missing:owner"},
            trigger_event,
            tasks_by_id,
            None,
        )
        forged_payload = dict(task.task_payload)
        if family in {
            "SetDynamicValueByCharacterCount",
            "SetDynamicValueByHPRatio",
            "SetDynamicValueByProperty",
        }:
            forged_payload["ReadTargetType"] = "ValidationUnknownExplicitTarget"
        forged_task = replace(
            task,
            task_id=f"{task.task_id}:validation-explicit-target",
            task_payload=forged_payload,
        )
        explicit_target_missing = system._execute_task(
            state,
            callback,
            forged_task,
            detail,
            trigger_event,
            {**tasks_by_id, forged_task.task_id: forged_task},
            None,
        )
        expected_value = {
            "SetDynamicValueByCharacterCount": 1.0,
            "SetDynamicValueByHPRatio": 0.5,
            "SetDynamicValueByProperty": (
                123.0
                if task.task_payload.get("SourceProperty") == "Speed"
                else (
                    100.0
                    if task.task_payload.get("SourceProperty") == "MaxHP"
                    else 0.4
                )
            ),
        }[family]
        mutation_values = [
            mutation.metadata.get("value") for mutation in result.mutations
        ]
        checks = {
            "real_source": callback.source.source_path.startswith(
                "Config/ConfigAbility/Equip/"
            ),
            "committed": result.ok and bool(result.mutations),
            "expected_value": expected_value in mutation_values,
            "missing_context_blocked": not missing.ok
            and missing.after_state == missing_state
            and not missing.mutations,
            "explicit_unresolved_target_blocked_without_owner_fallback": (
                not explicit_target_missing.ok
                and explicit_target_missing.after_state == state
                and not explicit_target_missing.mutations
            ),
        }
        rows.append(
            {
                "family": family,
                "ok": all(checks.values()),
                "checks": checks,
                "task_id": task.task_id,
                "callback_id": callback.callback_id,
                "source": task.source.to_json(),
                "mutation_values": mutation_values,
                "missing_context_errors": list(missing.errors),
                "explicit_target_errors": list(explicit_target_missing.errors),
            }
        )
    for family in sorted(effect_families):
        rows.append(
            _dynamic_effect_runtime_row(
                bundle,
                family,
                selected_task_ids=selected_task_ids,
            )
        )
    stack_rows = _stack_property_runtime_rows(
        bundle,
        selected_task_ids=selected_task_ids,
    )
    rows.extend(stack_rows)
    required_families = context_families | effect_families | {
        row["family"] for row in stack_rows
    }
    return {
        "schema_version": "p8_s7_structured_dynamic_task_matrix_v2",
        "ok": len(rows) == len(required_families)
        and all(row.get("ok") is True for row in rows),
        "rows": rows,
    }


def _dynamic_effect_runtime_row(
    bundle: dict[str, Any],
    family: str,
    *,
    selected_task_ids: set[str],
) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    candidates = sorted(
        (
            task
            for task in (*bundle["tasks"], *bundle["callback_tasks"])
            if task.task_id in selected_task_ids
            and task.opcode == family
            and task.effect_id
            and task.source.source_path.startswith("Config/ConfigAbility/Equip/")
        ),
        key=lambda item: item.task_id,
    )
    if not candidates:
        return {
            "family": family,
            "ok": False,
            "reason": "real_executable_effect_task_missing",
        }
    task = candidates[0]
    effect = rules.effect(task.effect_id)
    standard = effect.payload.get("standard") if effect is not None else None
    if effect is None or not isinstance(standard, dict):
        return {
            "family": family,
            "ok": False,
            "reason": "real_effect_or_standard_payload_missing",
            "task_id": task.task_id,
        }
    source_modifier = standard.get("source_modifier")
    status_detail = {
        "instance_id": "validation:p8_s7:dynamic-effect-source",
        "status_id": f"modifier:{source_modifier or 'validation'}",
        "modifier_name": str(source_modifier or "validation"),
        "owner_id": "ally:wearer",
        "caster_id": "ally:wearer",
        "stacks": 2,
        "duration": 2,
        "remaining_duration": 2,
        "source_trace": {"effect_source": effect.source.to_json()},
    }
    unit = UnitState(
        unit_id="ally:wearer",
        side="ally",
        template_id="validation:dynamic-effect-owner",
        max_hp=100.0,
        hp=100.0,
        flags={"status_details": [status_detail]},
    )
    state = BattleState(units={unit.unit_id: unit})
    dynamic_hashes = numeric_dynamic_hashes(standard)
    context = EffectExecutionContext(
        state=state,
        caster_id=unit.unit_id,
        source_id=f"validation:p8_s7:{task.task_id}",
        owner_id=unit.unit_id,
        param_entity_id=unit.unit_id,
        current_action_target_id=unit.unit_id,
        dynamic_values={str(value_hash): 1.0 for value_hash in dynamic_hashes},
    )
    registry = EffectRegistry(StatusSystem(rules))
    result = registry.execute(effect, context)
    missing_context = registry.execute(effect, None)
    checks = {
        "real_equipment_source": effect.source.source_path.startswith(
            "Config/ConfigAbility/Equip/"
        ),
        "effect_is_exactly_linked": effect.effect_id == task.effect_id
        and effect.opcode == family,
        "effect_admitted": registry.coverage(effect) == "executable",
        "runtime_write_committed": not result.unsupported
        and bool(result.mutations)
        and all(
            mutation.metadata.get("effect_id") == effect.effect_id
            for mutation in result.mutations
        ),
        "missing_context_is_fail_closed": bool(missing_context.unsupported)
        and not missing_context.mutations,
    }
    return {
        "family": family,
        "ok": all(checks.values()),
        "checks": checks,
        "task_id": task.task_id,
        "effect_id": effect.effect_id,
        "source": task.source.to_json(),
        "effect_source": effect.source.to_json(),
        "mutation_count": len(result.mutations),
        "unsupported": list(result.unsupported),
        "missing_context_unsupported": list(missing_context.unsupported),
    }


def _stack_property_runtime_rows(
    bundle: dict[str, Any],
    *,
    selected_task_ids: set[str],
) -> list[dict[str, Any]]:
    rules: RuleBook = bundle["rules"]
    callbacks_by_id = {
        callback.callback_id: callback for callback in bundle["callbacks"]
    }
    stat_by_key = {
        "attack_added_ratio": "attack",
        "attack_delta": "attack",
        "defense_added_ratio": "defense",
        "defense_delta": "defense",
        "speed_added_ratio": "speed",
        "speed_delta": "speed",
        "critical_chance": "critical_chance",
        "critical_damage": "critical_damage",
        "effect_hit_rate": "effect_hit_rate",
        "effect_resistance": "effect_resistance",
    }
    candidates = sorted(
        (
            task
            for task in bundle["callback_tasks"]
            if task.task_id in selected_task_ids
            and task.opcode == "StackProperty"
            and task.callback_id in callbacks_by_id
            and task.source.source_path.startswith("Config/ConfigAbility/Equip/")
        ),
        key=lambda item: item.task_id,
    )
    rows: list[dict[str, Any]] = []
    properties = sorted(
        {
            str(task.task_payload.get("Property") or "")
            for task in candidates
            if task.task_payload.get("Property")
        }
    )
    if not properties:
        return [
            {
                "family": "StackProperty:missing",
                "ok": False,
                "reason": "real_executable_stack_property_task_missing",
            }
        ]
    for property_name in properties:
        selected = None
        property_candidates = [
            task
            for task in candidates
            if task.task_payload.get("Property") == property_name
        ]
        for task in property_candidates:
            callback = callbacks_by_id[task.callback_id]
            definitions = rules.modifier_definitions(callback.modifier_name)
            for definition in definitions:
                runtime_modifiers, unsupported = _runtime_modifiers(
                    definition,
                    {
                        str(value_hash): 1.0
                        for item in definition.fields.get("stack_properties", ())
                        if isinstance(item, dict)
                        for value_hash in numeric_dynamic_hashes(
                            item.get("value_expr")
                        )
                    },
                )
                matches = [
                    modifier
                    for modifier in runtime_modifiers
                    if modifier.get("property") == property_name
                    and modifier.get("key") in stat_by_key
                ]
                if not unsupported and len(matches) == 1:
                    selected = (task, callback, definition, matches[0])
                    break
            if selected is not None:
                break
        family = f"StackProperty:{property_name}"
        if selected is None:
            rows.append(
                {
                    "family": family,
                    "ok": False,
                    "reason": "real_stack_property_not_materialized",
                    "candidate_count": len(property_candidates),
                }
            )
            continue
        task, callback, definition, modifier = selected
        detail = {
            "instance_id": f"validation:p8_s7:real-stack-property:{property_name}",
            "modifier_name": callback.modifier_name,
            "owner_id": "ally:wearer",
            "caster_id": "ally:wearer",
            "source_trace": {"task_source": task.source.to_json()},
            "modifiers": [modifier],
        }
        unit = UnitState(
            unit_id="ally:wearer",
            side="ally",
            template_id="validation:stack-property-owner",
            max_hp=100.0,
            hp=100.0,
            attack=100.0,
            defense=100.0,
            speed=100.0,
            resources={
                "critical_chance": 0.0,
                "critical_damage": 0.0,
                "effect_hit_rate": 0.0,
                "effect_resistance": 0.0,
            },
            flags={"status_details": [detail]},
        )
        mapped_key = str(modifier.get("key") or "")
        stat = stat_by_key.get(mapped_key)
        effective = effective_unit_stat(unit, stat) if stat is not None else None
        checks = {
            "real_equipment_source": task.source.source_path.startswith(
                "Config/ConfigAbility/Equip/"
            ),
            "definition_matches_callback_modifier": definition.fields.get(
                "modifier_name"
            )
            == callback.modifier_name,
            "task_property_materialized_once": modifier.get("property")
            == task.task_payload.get("Property"),
            "materialized_modifier_has_raw_path": bool(modifier.get("raw_path")),
            "mapped_combat_stat_consumed": effective is not None
            and any(
                term.get("key") == mapped_key for term in effective.source_terms
            ),
        }
        rows.append(
            {
                "family": family,
                "ok": all(checks.values()),
                "checks": checks,
                "task_id": task.task_id,
                "callback_id": callback.callback_id,
                "definition_id": definition.entity_id,
                "source": task.source.to_json(),
                "materialized_modifier": modifier,
                "effective_stat": (
                    effective.to_json() if effective is not None else None
                ),
            }
        )
    return rows


def _target_attribution_matrix(
    bundle: dict[str, Any],
    inventory: dict[str, Any],
    formal: dict[str, Any],
) -> dict[str, Any]:
    aliases = sorted(
        row["family"].removeprefix("TargetAlias:")
        for row in inventory["rows"]
        if row["stage"] == "s7"
        and row["kind"] == "target"
        and row["family"].startswith("TargetAlias:")
    )
    state = BattleState(
        units={
            "ally:wearer": UnitState(
                unit_id="ally:wearer",
                side="ally",
                template_id="validation:ally-wearer",
                max_hp=100.0,
                hp=100.0,
            ),
            "ally:peer": UnitState(
                unit_id="ally:peer",
                side="ally",
                template_id="validation:ally-peer",
                max_hp=100.0,
                hp=100.0,
            ),
            "ally:summon": UnitState(
                unit_id="ally:summon",
                side="summon",
                template_id="validation:ally-summon",
                max_hp=100.0,
                hp=100.0,
                flags={
                    "team_side": "ally",
                    "summon_kind": "summoned_monster",
                    "lifecycle_status": "active",
                    "lifecycle_source": {
                        "admission_status": "executable",
                        "presence": "field",
                        "targetable": True,
                    },
                },
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="validation:enemy-target",
                max_hp=100.0,
                hp=100.0,
            ),
            "enemy:peer": UnitState(
                unit_id="enemy:peer",
                side="enemy",
                template_id="validation:enemy-peer",
                max_hp=100.0,
                hp=100.0,
            ),
            "enemy:summon": UnitState(
                unit_id="enemy:summon",
                side="summon",
                template_id="validation:enemy-summon",
                max_hp=100.0,
                hp=100.0,
                flags={
                    "team_side": "enemy",
                    "summon_kind": "summoned_monster",
                    "lifecycle_status": "active",
                    "lifecycle_source": {
                        "admission_status": "executable",
                        "presence": "field",
                        "targetable": True,
                    },
                },
            ),
            "enemy:hidden": UnitState(
                unit_id="enemy:hidden",
                side="enemy",
                template_id="validation:enemy-hidden",
                max_hp=100.0,
                hp=100.0,
                flags={"unselectable": True},
            ),
            "enemy:hidden-alt": UnitState(
                unit_id="enemy:hidden-alt",
                side="enemy",
                template_id="validation:enemy-hidden-alt",
                max_hp=100.0,
                hp=100.0,
                flags={"target_unselectable": True},
            ),
            "enemy:hidden-is": UnitState(
                unit_id="enemy:hidden-is",
                side="enemy",
                template_id="validation:enemy-hidden-is",
                max_hp=100.0,
                hp=100.0,
                flags={"is_unselectable": True},
            ),
            "enemy:hidden-false": UnitState(
                unit_id="enemy:hidden-false",
                side="enemy",
                template_id="validation:enemy-hidden-false",
                max_hp=100.0,
                hp=100.0,
                flags={"selectable": False},
            ),
            "enemy:defeated": UnitState(
                unit_id="enemy:defeated",
                side="enemy",
                template_id="validation:enemy-defeated",
                max_hp=100.0,
                hp=0.0,
                flags={"lifecycle_status": "defeated"},
            ),
            "enemy:removed": UnitState(
                unit_id="enemy:removed",
                side="enemy",
                template_id="validation:enemy-removed",
                max_hp=100.0,
                hp=100.0,
                flags={"lifecycle_status": "removed"},
            ),
            "enemy:departed-summon": UnitState(
                unit_id="enemy:departed-summon",
                side="enemy",
                template_id="validation:enemy-departed-summon",
                max_hp=100.0,
                hp=100.0,
                flags={
                    "summon_kind": "summoned_monster",
                    "lifecycle_source": {
                        "admission_status": "executable",
                        "presence": "reserve",
                    },
                },
            ),
        }
    )
    expected = {
        "Caster": ("ally:wearer",),
        "ModifierOwnerEntity": ("ally:peer",),
        "ParamEntity": ("enemy:target",),
        "AttackTargetList": ("enemy:target",),
        "SkillTargetEntityList": ("enemy:target",),
        "AllEnemy": ("enemy:peer", "enemy:summon", "enemy:target"),
        "AllEnemyWithUnSelectable": (
            "enemy:hidden",
            "enemy:hidden-alt",
            "enemy:hidden-false",
            "enemy:hidden-is",
            "enemy:peer",
            "enemy:summon",
            "enemy:target",
        ),
        "AllLightTeam": ("ally:peer", "ally:summon", "ally:wearer"),
        "AllDarkTeam": ("enemy:peer", "enemy:summon", "enemy:target"),
        "AllTeamMember": ("ally:peer", "ally:summon", "ally:wearer"),
        "AllTeammate": ("ally:peer", "ally:summon"),
    }
    target_resolution = TargetResolution(
        requested=("enemy:target",),
        legal=("enemy:target",),
        selected=("enemy:target",),
        reason="p8_s7_target_attribution",
        source="validation_fixture",
    )
    rows = []
    reordered_state = replace(
        state,
        units=dict(reversed(tuple(state.units.items()))),
    )
    target_system = TargetSystem()
    for alias in aliases:
        candidates = [
            target
            for target in bundle["targets"]
            if target.expression_kind == "TargetAlias"
            and target.alias == alias
            and target.coverage_status == "executable"
            and target.source.source_path in bundle["equipment_sources"]
        ]
        if not candidates:
            rows.append(
                {
                    "alias": alias,
                    "ok": False,
                    "blocked_reason": "real_equipment_target_expression_missing",
                }
            )
            continue
        expression = sorted(
            candidates,
            key=lambda item: (
                item.source.source_path,
                item.target_expression_id,
            ),
        )[0]
        result = target_system.resolve_target_expression(
            state,
            expression,
            caster_id="ally:wearer",
            owner_id="ally:peer",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
            target_resolution=target_resolution,
            event_payload={
                "attack_target_ids": ["enemy:target"],
                "selected_target_ids": ["enemy:target"],
                "target_ids": ["enemy:target"],
            },
        )
        reordered_result = target_system.resolve_target_expression(
            reordered_state,
            expression,
            caster_id="ally:wearer",
            owner_id="ally:peer",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
            target_resolution=target_resolution,
            event_payload={
                "attack_target_ids": ["enemy:target"],
                "selected_target_ids": ["enemy:target"],
                "target_ids": ["enemy:target"],
            },
        )
        expected_ids = expected.get(alias)
        rows.append(
            {
                "alias": alias,
                "ok": result.ok
                and expected_ids is not None
                and result.target_ids == expected_ids
                and reordered_result.target_ids == expected_ids,
                "expected_target_ids": list(expected_ids or ()),
                "result": result.to_json(),
                "reordered_result": reordered_result.to_json(),
                "source": expression.source.to_json(),
            }
        )
    shared_filter_rows = []
    for alias in (
        "AllEnemy",
        "AllEnemyWithUnSelectable",
        "AllLightTeam",
        "AllDarkTeam",
        "AllTeamMember",
        "AllTeammate",
    ):
        expected_ids = expected[alias]
        context = EvaluationContext(
            state=state,
            actor_id="ally:wearer",
            owner_id="ally:wearer",
            target_id="enemy:target",
        )
        condition_ids, condition_details = _condition_target_ids(
            {"alias": alias},
            context,
        )
        reordered_condition_ids, _ = _condition_target_ids(
            {"alias": alias},
            replace(context, state=reordered_state),
        )
        callback_ids = _callback_target_group(
            state,
            {"owner_id": "ally:wearer"},
            None,
            alias,
        )
        reordered_callback_ids = _callback_target_group(
            reordered_state,
            {"owner_id": "ally:wearer"},
            None,
            alias,
        )
        shared_filter_rows.append(
            {
                "alias": alias,
                "expected_target_ids": list(expected_ids),
                "condition_target_ids": list(condition_ids or ()),
                "reordered_condition_target_ids": list(
                    reordered_condition_ids or ()
                ),
                "condition_details": condition_details,
                "callback_target_ids": list(callback_ids),
                "reordered_callback_target_ids": list(
                    reordered_callback_ids
                ),
                "ok": condition_ids == expected_ids
                and reordered_condition_ids == expected_ids
                and callback_ids == expected_ids
                and reordered_callback_ids == expected_ids,
            }
        )
    callback_retarget_fallback = _alive_enemy_ids_for_status_owner(
        state,
        {"owner_id": "ally:wearer"},
    )
    reordered_callback_retarget_fallback = _alive_enemy_ids_for_status_owner(
        reordered_state,
        {"owner_id": "ally:wearer"},
    )
    callback_list_alias = _list_alias_targets(
        state,
        {"owner_id": "ally:wearer"},
        None,
        "AllEnemyWithUnSelectable",
    )
    reordered_callback_list_alias = _list_alias_targets(
        reordered_state,
        {"owner_id": "ally:wearer"},
        None,
        "AllEnemyWithUnSelectable",
    )
    checks = {
        "all_s7_target_aliases_executed": bool(rows)
        and len(rows) == len(aliases)
        and all(row["ok"] is True for row in rows),
        "wearer_owner_and_enemy_are_distinct": expected["Caster"]
        != expected["ModifierOwnerEntity"]
        != expected["ParamEntity"],
        "multi_wearer_status_and_provider_instances_isolated": formal[
            "checks"
        ]["multi_wearer_instances_do_not_alias"]
        and formal["checks"]["status_owned_by_wearer"]
        and formal["checks"]["provider_registered_once"],
        "ordinary_enemy_group_excludes_unselectable": expected["AllEnemy"]
        != expected["AllEnemyWithUnSelectable"]
        and "enemy:hidden" not in expected["AllEnemy"]
        and "enemy:hidden" in expected["AllEnemyWithUnSelectable"],
        "alternate_unselectable_flags_are_normalized": all(
            unit_id not in expected["AllEnemy"]
            and unit_id in expected["AllEnemyWithUnSelectable"]
            for unit_id in (
                "enemy:hidden",
                "enemy:hidden-alt",
                "enemy:hidden-false",
                "enemy:hidden-is",
            )
        ),
        "lifecycle_exclusion_fixtures_exist": all(
            unit_id in state.units
            for unit_id in (
                "enemy:defeated",
                "enemy:removed",
                "enemy:departed-summon",
            )
        ),
        "defeated_removed_and_departed_units_are_excluded": all(
            unit_id not in expected["AllEnemyWithUnSelectable"]
            for unit_id in (
                "enemy:defeated",
                "enemy:removed",
                "enemy:departed-summon",
            )
        ),
        "both_active_summon_allegiances_are_exercised": (
            "ally:summon" in expected["AllLightTeam"]
            and "ally:summon" in expected["AllTeamMember"]
            and "ally:summon" not in expected["AllEnemy"]
            and "enemy:summon" in expected["AllDarkTeam"]
            and "enemy:summon" in expected["AllEnemy"]
            and "enemy:summon" not in expected["AllLightTeam"]
        ),
        "target_condition_and_callback_filters_agree": bool(
            shared_filter_rows
        )
        and all(row["ok"] is True for row in shared_filter_rows),
        "callback_auxiliary_target_paths_share_filter_and_order": (
            callback_retarget_fallback == expected["AllEnemy"]
            and reordered_callback_retarget_fallback == expected["AllEnemy"]
            and callback_list_alias == expected["AllEnemyWithUnSelectable"]
            and reordered_callback_list_alias
            == expected["AllEnemyWithUnSelectable"]
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s7_target_owner_multi_wearer_attribution_v3",
        "ok": checks["ok"],
        "checks": checks,
        "fixture_unit_ids": sorted(state.units),
        "active_summon_allegiances": {
            "ally:summon": "ally",
            "enemy:summon": "enemy",
        },
        "removed_fixture_id": "enemy:removed",
        "rows": rows,
        "shared_filter_rows": shared_filter_rows,
        "callback_auxiliary_paths": {
            "retarget_fallback": list(callback_retarget_fallback),
            "reordered_retarget_fallback": list(
                reordered_callback_retarget_fallback
            ),
            "with_unselectable_list_alias": list(callback_list_alias),
            "reordered_with_unselectable_list_alias": list(
                reordered_callback_list_alias
            ),
        },
    }


def _event_timing_matrix(
    bundle: dict[str, Any],
    inventory: dict[str, Any],
    formal: dict[str, Any],
    lifecycle: dict[str, Any],
) -> dict[str, Any]:
    production = _production_event_chain(bundle, formal, lifecycle)
    raw_counts = {
        row["family"].split(":", 1)[0]: row["raw_count"]
        for row in inventory["rows"]
        if row["stage"] == "s7" and row["kind"] == "event"
    }
    rows = []
    for event, raw_count in sorted(raw_counts.items()):
        admitted_raw_sources = {
            row["source_identity"]
            for row in inventory["_source_rows"]
            if row["kind"] == "event"
            and row["stage"] == "s7"
            and row["family"].split(":", 1)[0] == event
        }
        families = [
            family
            for family in bundle["event_families"]
            if family.callback_event == event
        ]
        callbacks = [
            callback
            for callback in bundle["callbacks"]
            if callback.event == event
            and callback.coverage_status == "executable"
            and callback.admission_status == "executable"
            and (
                f"{callback.source.source_path}#"
                f"{callback.source.evidence.get('callback_json_path')}"
            )
            in admitted_raw_sources
        ]
        family = families[0] if len(families) == 1 else None
        source_links = [
            _event_callback_source_link(bundle, callback)
            for callback in callbacks
        ]
        dispatch_probes: list[dict[str, Any]] = []
        if family is not None:
            for callback in callbacks:
                probe = _event_family_dispatch_probe(
                    bundle,
                    family,
                    callback,
                    production,
                )
                dispatch_probes.append(probe)
                if probe.get("ok") is True:
                    break
        successful_dispatch_probes = [
            probe for probe in dispatch_probes if probe.get("ok") is True
        ]
        failed_dispatch_probes = [
            probe for probe in dispatch_probes if probe.get("ok") is not True
        ]
        callback_identities = {
            str(link.get("callback_id") or "")
            for link in source_links
        }
        source_link_complete = (
            len(source_links) == raw_count
            and all(link.get("ok") is True for link in source_links)
            and len(callback_identities) == raw_count
            and "" not in callback_identities
        )
        rows.append(
            {
                "event": event,
                "raw_callback_count": raw_count,
                "admitted_callback_count": len(callbacks),
                "ok": family is not None
                and family.coverage_status == "executable"
                and family.admission_status == "executable"
                and bool(family.runtime_event_sources)
                and bool(family.source_basis)
                and len(callbacks) == raw_count
                and source_link_complete
                and bool(successful_dispatch_probes),
                "source_link_complete": source_link_complete,
                "dispatch_chain_ok": bool(successful_dispatch_probes),
                "dispatch_probe_count": len(dispatch_probes),
                "successful_dispatch_probe_count": len(successful_dispatch_probes),
                "failed_dispatch_probe_count": len(failed_dispatch_probes),
                "dispatch_probe_samples": successful_dispatch_probes[:1],
                "failed_dispatch_probe_samples": failed_dispatch_probes[:4],
                "callback_source_link_count": len(source_links),
                "callback_source_link_samples": source_links[:2],
                "event_family": family.to_json() if family is not None else None,
                "callback_source_samples": [
                    callback.source.to_json()
                    for callback in callbacks[:2]
                ],
            }
        )
    listener_dispatch_rows = lifecycle["listener_dispatch"]
    checks = {
        "all_s7_event_families_have_runtime_sources": bool(rows)
        and all(row["ok"] is True for row in rows),
        "formal_on_start_applied_once_per_wearer": len(
            formal["startup_traces"]
        )
        == 2
        and all(
            row.get("status") == "applied"
            and int(row.get("mutation_count") or 0) > 0
            for row in formal["startup_traces"]
        ),
        "real_on_stack_listener_dispatched": bool(listener_dispatch_rows)
        and any(
            int(row.get("record_count") or 0) > 0
            and not row.get("errors")
            for row in listener_dispatch_rows
        ),
        "event_phase_families_present": all(
            any(token in event for event in raw_counts)
            for token in (
                "EnterBattle",
                "HPChange",
                "BeforeAttack",
                "AfterAttack",
                "BeingAttacked",
                "TriggerDeath",
            )
        ),
        "production_transitions_committed_audited_and_replayable": production[
            "ok"
        ],
        "every_callback_source_linked_without_blanket_execution_claim": bool(rows)
        and all(row["source_link_complete"] is True for row in rows),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s7_event_timing_matrix_v3",
        "ok": checks["ok"],
        "checks": checks,
        "rows": rows,
        "real_listener_dispatch": listener_dispatch_rows,
        "production_event_chain": {
            key: value
            for key, value in production.items()
            if not key.startswith("_")
        },
    }


def _event_callback_source_link(
    bundle: dict[str, Any],
    callback: StatusCallbackIR,
) -> dict[str, Any]:
    source = callback.source
    evidence = source.evidence
    callback_json_path = evidence.get("callback_json_path")
    declared_event = evidence.get("event")
    rules: RuleBook = bundle["rules"]
    resolved = rules.status_callback(callback.callback_id)
    tasks = rules.status_callback_tasks_for_callback(callback.callback_id)
    expected_task_ids = tuple(callback.task_ids)
    actual_task_ids = tuple(task.task_id for task in tasks)
    tasks_by_id = {task.task_id: task for task in tasks}

    def is_reachable_from_callback_root(task: Any) -> bool:
        current = task
        visited: set[str] = set()
        while current.task_id not in expected_task_ids:
            if not current.parent_task_id or current.parent_task_id in visited:
                return False
            visited.add(current.parent_task_id)
            parent = tasks_by_id.get(current.parent_task_id)
            if parent is None:
                return False
            current = parent
        return True

    task_sources_nested = all(
        task.callback_id == callback.callback_id
        and task.event == callback.event
        and task.modifier_name == callback.modifier_name
        and task.source.source_path == source.source_path
        and task.source.evidence.get("callback_id") == callback.callback_id
        and task.source.evidence.get("event") == callback.event
        and isinstance(task.source.evidence.get("task_path"), str)
        and bool(task.source.evidence.get("task_path"))
        and is_reachable_from_callback_root(task)
        for task in tasks
    )
    identity_parts = (
        source.source_path,
        source.raw_type,
        source.raw_id,
        callback_json_path,
        callback.event,
    )
    stable_source_identity = "|".join(
        str(value) for value in identity_parts if isinstance(value, str)
    )
    raw_container_matches_path = (
        source.raw_type == "Modifiers"
        and isinstance(callback_json_path, str)
        and callback_json_path.startswith("$.AbilityList[")
    ) or (
        source.raw_type == "GlobalModifiers"
        and isinstance(callback_json_path, str)
        and callback_json_path.startswith("$.GlobalModifiers.")
    )
    ok = (
        resolved == callback
        and source.source_path.startswith("Config/ConfigAbility/Equip/")
        and raw_container_matches_path
        and isinstance(source.raw_id, str)
        and bool(source.raw_id)
        and isinstance(callback_json_path, str)
        and declared_event == callback.event
        and set(expected_task_ids) <= set(actual_task_ids)
        and bool(tasks)
        and task_sources_nested
        and len(identity_parts) == 5
        and all(isinstance(value, str) and value for value in identity_parts)
    )
    return {
        "ok": ok,
        "callback_id": callback.callback_id,
        "callback_event": callback.event,
        "stable_source_identity": stable_source_identity,
        "callback_source": source.to_json(),
        "expected_task_ids": list(expected_task_ids),
        "actual_task_ids": list(actual_task_ids),
        "task_sources_nested_under_callback": task_sources_nested,
        "rulebook_resolution_exact": resolved == callback,
    }
def _production_event_chain(
    bundle: dict[str, Any],
    formal: dict[str, Any],
    lifecycle: dict[str, Any],
) -> dict[str, Any]:
    fixture_ir = _trust_rulebook().ir
    source = _p7_fixture_source("p8_s7_production_event_action")
    action_id = next(
        admission.action_id
        for admission in fixture_ir.action_admissions
        if admission.coverage_status == "executable"
        and admission.action_role == "turn_action"
    )
    level = next(
        admission.action_level
        for admission in fixture_ir.action_admissions
        if admission.action_id == action_id
    )
    hit_profile_ids = (
        "validation:p8_s7:production-hit:0",
        "validation:p8_s7:production-hit:1",
    )
    definitions = tuple(
        replace(
            definition,
            damage_kind="hp_damage",
            damage_formula_family="direct",
            param_list=(1.0,),
            show_damage_list=(1.0,),
        )
        if definition.action_id == action_id and definition.level == level
        else definition
        for definition in fixture_ir.action_definitions
    )
    phase_steps = (
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="before_skill_use",
            canonical_window="before_skill_use",
            tbgd_event="OnBeforeSkillUse",
            coverage_status="lowered",
            source=source,
        ),
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="before_attack",
            canonical_window="before_attack",
            tbgd_event="OnBeforeAttack",
            coverage_status="lowered",
            source=source,
        ),
        ActionPhaseStepIR(
            kind="damage",
            phase="damage",
            canonical_window="damage",
            tbgd_event="action_damage_plan",
            coverage_status="lowered",
            source=source,
        ),
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="after_attack",
            canonical_window="after_attack",
            tbgd_event="OnAfterAttack",
            coverage_status="lowered",
            source=source,
        ),
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="after_skill_use",
            canonical_window="after_skill_use",
            tbgd_event="OnAfterSkillUse",
            coverage_status="lowered",
            source=source,
        ),
    )
    action_events = tuple(
        replace(
            event,
            phase_steps=phase_steps,
            hit_profile_ids=hit_profile_ids,
        )
        if event.action_id == action_id and event.level == level
        else event
        for event in fixture_ir.action_events
    )
    hit_profiles = tuple(
        HitProfileIR(
            hit_profile_id=hit_profile_id,
            action_id=action_id,
            level=level,
            hit_index=index,
            target_group="primary",
            multiplier_expr=numeric_fixed(0.5),
            multiplier_source={
                "source_kind": "character_data_card_skill_formula",
                "validation_fixture": True,
            },
            stance_expr=numeric_fixed(1.0),
            stance_source={"source_kind": "validation_fixture"},
            damage_formula_family="direct",
            element_type="Fire",
            source=source,
            coverage_status="executable",
            numeric_fidelity_status="exact",
        )
        for index, hit_profile_id in enumerate(hit_profile_ids)
    )
    damage_emissions = tuple(
        DamageEmissionIR(
            damage_emission_id=f"validation:p8_s7:production-damage:{index}",
            action_id=action_id,
            level=level,
            phase_id=f"{action_id}:phase",
            source_task_id=f"validation:p8_s7:production-damage-task:{index}",
            hit_profile_id=hit_profile_id,
            target_group="primary",
            damage_formula_family="direct",
            element_type="Fire",
            scaling_ratio_expr=numeric_fixed(0.5),
            scaling_basis_expr={
                "kind": "unit_stat",
                "unit_ref": "attacker",
                "stat": "attack",
            },
            source=source,
            coverage_status="executable",
        )
        for index, hit_profile_id in enumerate(hit_profile_ids)
    )
    toughness_emission = ToughnessEmissionIR(
        toughness_emission_id="validation:p8_s7:production-toughness",
        action_id=action_id,
        level=level,
        phase_id=f"{action_id}:phase",
        source_task_id="validation:p8_s7:production-toughness-task",
        hit_profile_id=hit_profile_ids[0],
        target_group="primary",
        element_type="Fire",
        toughness_amount_expr=numeric_fixed(1.0),
        source=source,
        coverage_status="executable",
    )
    break_damage_emission = BreakDamageEmissionIR(
        break_damage_emission_id="validation:p8_s7:production-break-damage",
        template_id="validation:p8_s7:break-template",
        source_task_id="validation:p8_s7:production-break-damage-task",
        element_type="Fire",
        damage_formula_family="break",
        scaling_expr=numeric_fixed(1.0),
        source=source,
        coverage_status="executable",
    )
    production_source_tasks = (
        *(
            AbilityTaskIR(
                task_id=damage_emission.source_task_id,
                phase_id="validation:p8_s7:audit-source-phase",
                action_id="validation:p8_s7:audit-source-action",
                level=level,
                ability_name="validation:p8_s7:production-action",
                callback_kind="OnAttack",
                task_index=index,
                task_path=f"validation/p8_s7/production_damage/{index}",
                branch="root",
                opcode="DamageByAttackProperty",
                source=source,
                coverage_status="executable",
            )
            for index, damage_emission in enumerate(damage_emissions)
        ),
        AbilityTaskIR(
            task_id=toughness_emission.source_task_id,
            phase_id="validation:p8_s7:audit-source-phase",
            action_id="validation:p8_s7:audit-source-action",
            level=level,
            ability_name="validation:p8_s7:production-action",
            callback_kind="OnAttack",
            task_index=len(damage_emissions),
            task_path="validation/p8_s7/production_toughness",
            branch="root",
            opcode="DamageStance",
            source=source,
            coverage_status="executable",
        ),
        AbilityTaskIR(
            task_id=break_damage_emission.source_task_id,
            phase_id="validation:p8_s7:audit-source-phase",
            action_id="validation:p8_s7:audit-source-action",
            level=level,
            ability_name="validation:p8_s7:production-action",
            callback_kind="OnBreak",
            task_index=len(damage_emissions) + 1,
            task_path="validation/p8_s7/production_break_damage",
            branch="root",
            opcode="DamageByBreak",
            source=source,
            coverage_status="executable",
        ),
    )
    event_families = list(bundle["ir"].status_event_families)
    existing_callback_events = {
        family.callback_event for family in event_families
    }
    resource_event_rows = tuple(
        (
            callback_event,
            runtime_sources[0],
            resource_scope_for_callback(callback_event),
        )
        for callback_event, runtime_sources in sorted(
            resource_callback_runtime_sources().items()
        )
    )
    for callback_event, runtime_event, scope_kind in (
        ("OnBeforeBeingStanceDamage", "toughness.before_hit", "global_listener"),
        ("OnBeingStanceDamage", "toughness.hit", "global_listener"),
        ("OnBeingBreak", "break.triggered", "global_listener"),
        ("OnListenAfterAttack", "action.after_attack", "global_listener"),
        ("OnListenHPChange", "hp.change", "global_listener"),
        *resource_event_rows,
    ):
        if callback_event in existing_callback_events:
            continue
        event_families.append(
            StatusEventFamilyIR(
                status_event_family_id=(
                    f"validation:p8_s7:event-family:{callback_event}"
                ),
                callback_event=callback_event,
                event_family="validation_production_dependency",
                default_scope_kind=scope_kind,
                runtime_event_sources=(runtime_event,),
                source_basis="kernel_fixture_production_event_dependency",
                source=source,
                coverage_status="executable",
                admission_status="executable",
            )
        )
    base_ir = bundle["ir"]
    base_status_producer_effect = next(
        effect
        for effect in sorted(
            base_ir.effects,
            key=lambda item: (item.source.source_path, item.effect_id),
        )
        if effect.opcode == "AddModifier"
        and effect.coverage_status == "executable"
        and isinstance(effect.payload.get("standard"), dict)
        and effect.payload["standard"].get("target_alias") == "ParamEntity"
        and effect.payload["standard"].get("target_expression_id")
        and not effect.payload["standard"].get("dynamic_value_requests")
    )
    producer_modifier_name = "ValidationP8S7EventProducerDebuff"
    producer_definition_id = f"modifier_definition:{producer_modifier_name}"
    producer_standard = {
        **base_status_producer_effect.payload["standard"],
        "modifier_name": producer_modifier_name,
        "dynamic_values": {},
        "dynamic_value_requests": {},
        "lifetime": numeric_fixed(2.0),
        "life_step_moment": "ModifierPhase1End",
        "duration_admission": {
            "admission_status": "executable",
            "blocked_reason": "",
            "life_step_moment": "ModifierPhase1End",
            "lifetime_expr": numeric_fixed(2.0),
        },
        "layer_add_when_stack": numeric_fixed(1.0),
        "max_layer": numeric_fixed(2.0),
        "chance": numeric_fixed(1.0),
        "chance_field_present": True,
    }
    status_producer_effect = replace(
        base_status_producer_effect,
        effect_id="validation:p8_s7:status-event-producer-effect",
        payload={
            **base_status_producer_effect.payload,
            "standard": producer_standard,
        },
        source=source,
        modifier_definition_id=producer_definition_id,
        status_callback_ids=(),
        owner_modifier_name="",
    )
    status_producer_definition = RuleEntity(
        entity_id=producer_definition_id,
        entity_type="modifier_definition",
        fields={
            "modifier_name": producer_modifier_name,
            "StatusType": "Debuff",
            "behavior_flags": ["STAT_DefenceDown"],
        },
        source=source,
        coverage_status="executable",
    )
    production_ir = replace(
        base_ir,
        entities=(*base_ir.entities, status_producer_definition),
        effects=(*base_ir.effects, status_producer_effect),
        action_definitions=definitions,
        action_ability_bindings=fixture_ir.action_ability_bindings,
        ability_phases=fixture_ir.ability_phases,
        ability_tasks=(*fixture_ir.ability_tasks, *production_source_tasks),
        action_events=action_events,
        combatant_action_sets=fixture_ir.combatant_action_sets,
        action_admissions=fixture_ir.action_admissions,
        timeline_rules=fixture_ir.timeline_rules,
        resource_rules=fixture_ir.resource_rules,
        damage_formula_rules=fixture_ir.damage_formula_rules,
        damage_route_rules=fixture_ir.damage_route_rules,
        shield_priority_rules=fixture_ir.shield_priority_rules,
        hit_profiles=hit_profiles,
        damage_emissions=damage_emissions,
        toughness_emissions=(toughness_emission,),
        break_templates=(
            BreakTemplateIR(
                template_id="validation:p8_s7:break-template",
                element_type="Fire",
                task_names=(),
                source=source,
                coverage_status="executable",
            ),
        ),
        break_damage_emissions=(break_damage_emission,),
        status_event_families=tuple(event_families),
    )
    rules = RuleBook(production_ir)

    def execute_turn(
        *,
        target_hp: float,
        target_toughness: float,
        attack_type: str = "Normal",
        target_id: str = "enemy:target",
        target_mode: str = "single",
        target_relation: str = "enemy",
    ) -> Any:
        # Produce each skill-type context through the real decision/scheduler/
        # executor chain.  Merely rewriting an emitted event payload would not
        # prove that the runtime producer preserves the action definition.
        case_ir = replace(
            production_ir,
            action_definitions=tuple(
                replace(
                    definition,
                    attack_type=attack_type,
                    target_mode=target_mode,
                    target_relation=target_relation,
                )
                if definition.action_id == action_id and definition.level == level
                else definition
                for definition in production_ir.action_definitions
            ),
            action_events=tuple(
                replace(
                    event,
                    target_mode=target_mode,
                    target_relation=target_relation,
                )
                if event.action_id == action_id and event.level == level
                else event
                for event in production_ir.action_events
            ),
        )
        case_rules = RuleBook(case_ir)
        decision_system = DecisionSystem(case_rules)
        initial = _p7_base_state(target_hp=target_hp)
        target = initial.units["enemy:target"]
        target = replace(
            target,
            max_hp=max(target.max_hp, target_hp),
            hp=target_hp,
            toughness=target_toughness,
            max_toughness=max(1.0, target_toughness),
            flags={**target.flags, "weaknesses": ["Fire"], "action_disabled": True},
        )
        initial = replace(initial, units={**initial.units, target.unit_id: target})
        advance = decision_system.advance_to_decision(initial)
        choices = tuple(
            choice
            for choice in advance.decision.availability.choices
            if choice.action_id == action_id
            and target_id in choice.selectable_target_ids
        )
        if not advance.decision.ready or len(choices) != 1:
            return {
                "ok": False,
                "reason": "production_action_decision_missing",
                "advance": advance,
                "submit": None,
                "rules": case_rules,
                "attack_type": attack_type,
            }
        choice = choices[0]
        command = ActionCommand(
            actor_id=choice.actor_id,
            action_id=choice.action_id,
            action_level=choice.action_level,
            target_ids=(target_id,),
            source="manual",
            metadata={
                **dict(choice.command_template.get("metadata") or {}),
                # The production chain must exercise the critical-hit event
                # payload consumed by real equipment callbacks.  The common
                # damage formula still produces the outcome; this only fixes
                # the controllable RNG branch for the focused probe.
                "crit_mode": "forced_crit",
            },
        )
        submit = decision_system.submit(
            advance.after_state,
            advance.decision.token,
            command,
        )
        transitions = (*advance.transitions, submit.transition)
        return {
            "ok": submit.transition.outcome.successor_eligible,
            "advance": advance,
            "submit": submit,
            "transitions": transitions,
            "rules": case_rules,
            "attack_type": attack_type,
        }

    ordinary = execute_turn(target_hp=1000.0, target_toughness=100.0)
    breaking = execute_turn(target_hp=1000.0, target_toughness=0.5)
    skill = execute_turn(
        target_hp=1000.0,
        target_toughness=100.0,
        attack_type="Skill",
    )
    ultimate = execute_turn(
        target_hp=1000.0,
        target_toughness=100.0,
        attack_type="Ultra",
    )
    self_target_ultimate = execute_turn(
        target_hp=1000.0,
        target_toughness=100.0,
        attack_type="Ultra",
        target_id="ally:actor",
        target_mode="self_or_team",
        target_relation="self",
    )
    production_cases = (
        ordinary,
        breaking,
        skill,
        ultimate,
        self_target_ultimate,
    )
    transitions = tuple(
        transition
        for case in production_cases
        for transition in case.get("transitions", ())
    )
    defeat_state = _p7_base_state(target_hp=1.0)
    defeat_packet = DamagePacket(
        attacker_id="ally:actor",
        target_id="enemy:target",
        attack_type="Normal",
        damage_formula_family="hp_loss",
        amount=2.0,
        amount_stage="fixed_final",
        damage_kind="hp_damage",
        source_trace=source.to_json(),
        source_frame=DamageSourceFrame(
            owner_id="ally:actor",
            source_id="validation:p8_s7:production-defeat",
            source_kind="kernel_fixture",
            sequence_id="validation:p8_s7:production-defeat-sequence",
            target_id="enemy:target",
            source_trace=source.to_json(),
        ),
        metadata={
            "validation_fixture": True,
            "damage_source_owner_id": "ally:actor",
            "damage_source_id": "validation:p8_s7:production-defeat",
            "damage_source_kind": "kernel_fixture",
            "damage_sequence_id": "validation:p8_s7:production-defeat-sequence",
        },
    )
    defeat_result = DamageSystem(rules).apply_packet(
        defeat_state,
        defeat_packet,
    )
    defeat_after = MutationReducer().apply_all(
        defeat_state,
        defeat_result.mutations,
    )
    defeat_replay = MutationReducer().replay_snapshot(
        defeat_state,
        defeat_result.mutations,
        defeat_after.snapshot().to_json(),
    )
    defeat_mutation_ids = {
        mutation.stable_id() for mutation in defeat_result.mutations
    }
    defeat_record_ids = {
        str(record.get("mutation_id") or "")
        for record in defeat_result.records
        if isinstance(record, dict) and record.get("mutation_id")
    }
    formal_events = tuple(formal["_built"].setup_events)
    lifecycle_events = tuple(lifecycle.get("_production_events") or ())
    events = tuple(
        event
        for transition in transitions
        for event in transition.transaction.events
    ) + tuple(defeat_result.events) + formal_events + lifecycle_events
    by_type: dict[str, list[GameEvent]] = defaultdict(list)
    for event in events:
        by_type[event.event_type].append(event)
    produced_callback_event_counts = Counter(
        family.callback_event
        for event in events
        for family in rules.status_event_families_for_runtime_event(
            event.event_type
        )
        if family.coverage_status == "executable"
        and family.admission_status == "executable"
    )
    audits = [
        RuntimeSourceAuditor(case["rules"]).validate_transition(transition)
        for case in production_cases
        for transition in case.get("transitions", ())
    ]
    replay_rows = []
    for transition in transitions:
        before_state = next(
            (
                case["advance"].after_state
                for case in production_cases
                if case.get("submit") is not None
                and case["submit"].transition is transition
            ),
            None,
        )
        if before_state is None:
            replay_rows.append(True)
            continue
        replay_rows.append(
            MutationReducer().replay_snapshot(
                before_state,
                transition.transaction.mutations,
                transition.after.to_json(),
            ).ok
        )
    equipment_callback_events = {
        callback.event
        for callback in bundle["callbacks"]
        if callback.coverage_status == "executable"
        and callback.admission_status == "executable"
        and callback.source.source_path.startswith("Config/ConfigAbility/Equip/")
    }
    required_sources = {
        family.runtime_event_sources[0]
        for family in bundle["event_families"]
        if family.callback_event in equipment_callback_events
        and family.coverage_status == "executable"
        and family.runtime_event_sources
    }
    timing_event_types = {
        "damage.hit_sequence.before",
        "damage.target_attack.before",
        "damage.target_hit_sequence.before",
        "damage.before_hit",
        "damage.hit",
        "damage.target_hit_sequence.after",
        "damage.target_attack.after",
        "damage.hit_sequence.after",
    }
    ordinary_events = (
        ordinary["submit"].transition.transaction.events
        if ordinary.get("submit") is not None
        else ()
    )
    ordinary_timing_sequence = tuple(
        event.event_type
        for event in ordinary_events
        if event.event_type in timing_event_types
    )
    expected_timing_sequence = (
        "damage.hit_sequence.before",
        "damage.target_attack.before",
        "damage.target_hit_sequence.before",
        "damage.before_hit",
        "damage.hit",
        "damage.before_hit",
        "damage.hit",
        "damage.target_hit_sequence.after",
        "damage.target_attack.after",
        "damage.hit_sequence.after",
    )
    ordinary_callback_counts = Counter(
        family.callback_event
        for event in ordinary_events
        for family in rules.status_event_families_for_runtime_event(
            event.event_type
        )
        if family.coverage_status == "executable"
        and family.admission_status == "executable"
    )
    expected_callback_counts = {
        "OnBeforeHitAll": 1,
        "OnBeforeBeingAttacked": 1,
        "OnBeforeBeingHitAll": 1,
        "OnBeforeHit": 2,
        "OnAfterHit": 2,
        "OnAfterBeingHitAll": 1,
        "OnAfterBeingAttacked": 1,
        "OnAfterHitAll": 1,
    }
    expected_runtime_event_counts = {
        "damage.hit_sequence.before": 1,
        "damage.target_attack.before": 1,
        "damage.target_hit_sequence.before": 1,
        "damage.before_hit": 2,
        "damage.hit": 2,
        "damage.target_hit_sequence.after": 1,
        "damage.target_attack.after": 1,
        "damage.hit_sequence.after": 1,
    }
    ordinary_timing_counts = Counter(ordinary_timing_sequence)
    checks = {
        "ordinary_production_turn_committed": ordinary["ok"],
        "breaking_production_turn_committed": breaking["ok"],
        "skill_production_turn_committed": skill["ok"],
        "ultimate_production_turn_committed": ultimate["ok"],
        "self_target_ultimate_production_turn_committed": (
            self_target_ultimate["ok"]
        ),
        "defeat_production_chain_closed": defeat_result.ok
        and defeat_after.units["enemy:target"].hp == 0.0
        and any(event.event_type == "unit.defeated" for event in defeat_result.events)
        and bool(defeat_mutation_ids)
        and defeat_mutation_ids <= defeat_record_ids
        and defeat_replay.ok,
        "required_runtime_event_types_produced": required_sources <= set(by_type),
        "production_transitions_source_audited": bool(audits)
        and all(result.ok for result in audits),
        "production_transitions_replayable": bool(replay_rows)
        and all(replay_rows),
        "formal_setup_event_source_included": bool(formal_events)
        and "battle.setup" in by_type
        and "status.lifecycle" in by_type,
        "common_status_lifecycle_event_source_included": bool(lifecycle_events)
        and all(event.event_type == "status.lifecycle" for event in lifecycle_events),
        "two_hit_listener_windows_have_distinct_counts": all(
            ordinary_callback_counts.get(callback_event, 0) == expected_count
            for callback_event, expected_count in expected_callback_counts.items()
        )
        and all(
            ordinary_timing_counts.get(event_type, 0) == expected_count
            for event_type, expected_count in expected_runtime_event_counts.items()
        ),
        "two_hit_listener_windows_have_canonical_order": (
            ordinary_timing_sequence == expected_timing_sequence
        ),
        "skill_and_ultimate_contexts_come_from_action_producer": all(
            any(
                event.event_type in {
                    "action.window.before_skill_use",
                    "action.window.after_skill_use",
                }
                and event.payload.get("skill_type") == case["attack_type"]
                for transition in case.get("transitions", ())
                for event in transition.transaction.events
            )
            for case in (skill, ultimate)
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s7_production_event_chain_v2",
        "ok": checks["ok"],
        "checks": checks,
        "produced_event_type_counts": dict(
            sorted((key, len(value)) for key, value in by_type.items())
        ),
        "produced_callback_event_counts": dict(
            sorted(produced_callback_event_counts.items())
        ),
        "two_hit_window_probe": {
            "expected_event_sequence": list(expected_timing_sequence),
            "actual_event_sequence": list(ordinary_timing_sequence),
            "expected_callback_counts": expected_callback_counts,
            "actual_callback_counts": dict(
                sorted(ordinary_callback_counts.items())
            ),
            "expected_runtime_event_counts": expected_runtime_event_counts,
            "actual_runtime_event_counts": dict(
                sorted(ordinary_timing_counts.items())
            ),
        },
        "required_runtime_event_types": sorted(required_sources),
        "transition_count": len(transitions),
        "ordinary_outcome": (
            ordinary["submit"].transition.outcome.to_json()
            if ordinary.get("submit") is not None
            else {"reason": ordinary.get("reason", "")}
        ),
        "breaking_outcome": (
            breaking["submit"].transition.outcome.to_json()
            if breaking.get("submit") is not None
            else {"reason": breaking.get("reason", "")}
        ),
        "defeat_production": {
            "ok": defeat_result.ok,
            "event_types": [event.event_type for event in defeat_result.events],
            "mutation_count": len(defeat_result.mutations),
            "record_count": len(defeat_result.records),
            "errors": list(defeat_result.errors),
            "replay_ok": defeat_replay.ok,
            "all_mutations_have_settlement": defeat_mutation_ids
            <= defeat_record_ids,
        },
        "audit_violation_counts": [len(result.violations) for result in audits],
        "audit_violation_samples": [
            [violation.to_json() for violation in result.violations[:4]]
            for result in audits
        ],
        "replay_results": replay_rows,
        "_rules": rules,
        "_events_by_type": by_type,
    }


def _event_family_dispatch_probe(
    bundle: dict[str, Any],
    family: Any,
    callback: StatusCallbackIR,
    production: dict[str, Any],
) -> dict[str, Any]:
    if not family.runtime_event_sources:
        return {"ok": False, "reason": "runtime_event_source_missing"}
    events_by_type: dict[str, list[GameEvent]] = production["_events_by_type"]
    produced = [
        (event_type, event)
        for event_type in family.runtime_event_sources
        for event in events_by_type.get(event_type, ())
    ]
    if not produced:
        return {
            "ok": False,
            "reason": "runtime_event_not_produced_by_focused_chain",
            "runtime_event_sources": list(family.runtime_event_sources),
        }
    rules: RuleBook = production["_rules"]
    dynamic_values = _callback_probe_dynamic_values(bundle, callback)
    related_status_names = _callback_related_status_names(bundle, callback)
    attempts: list[dict[str, Any]] = []
    for event_type, event in produced:
        owner_ids = tuple(
            dict.fromkeys(
                item
                for item in (
                    event.source_id,
                    event.target_id,
                    "ally:wearer" if event_type == "battle.setup" else "",
                )
                if isinstance(item, str) and item and not item.startswith("scenario:")
            )
        )
        for owner_id in owner_ids:
            phases = EVENT_PHASES.get(event_type, ()) or ("",)
            for phase in phases:
                state = _callback_fixture_state(
                    callback,
                    owner_id=owner_id,
                    event=event,
                    dynamic_values=dynamic_values,
                    related_status_names=related_status_names,
                )
                if phase:
                    state = replace(
                        state,
                        global_flags={
                            **state.global_flags,
                            "combat_phase": phase,
                        },
                    )
                result = EventDispatchSystem(
                    rules,
                    EffectRegistry(StatusSystem(rules)),
                ).dispatch_event(
                    state,
                    event=event,
                    unit_id=owner_id,
                    modifier_name=callback.modifier_name,
                )
                listener_payloads = [
                    record.get("payload")
                    for record in result.listener_records
                    if isinstance(record, dict)
                    and isinstance(record.get("payload"), dict)
                ]
                listener_ids = {
                    str(payload.get("listener_id") or "")
                    for payload in listener_payloads
                }
                statuses = {
                    str(payload.get("status") or "")
                    for payload in listener_payloads
                    if str(payload.get("listener_id") or "")
                    == callback.callback_id
                }
                audit = _event_dispatch_probe_audit(
                    rules,
                    state,
                    event,
                    result,
                )
                ok = (
                    callback.callback_id in listener_ids
                    and "blocked" not in statuses
                    and bool(statuses & {"matched", "executed", "skipped"})
                    and not result.errors
                    and audit["ok"]
                )
                attempt = {
                    "ok": ok,
                    "runtime_event_source": event_type,
                    "production_event_id": event.event_id,
                    "production_callback_events": list(
                        event.payload.get("callback_events", ())
                        if isinstance(
                            event.payload.get("callback_events"),
                            (list, tuple),
                        )
                        else ()
                    ),
                    "phase_from_runtime_contract": phase,
                    "owner_id": owner_id,
                    "callback_event": family.callback_event,
                    "callback_id": callback.callback_id,
                    "listener_ids": sorted(listener_ids),
                    "listener_statuses": sorted(statuses),
                    "mutation_count": len(result.mutations),
                    "record_count": len(result.records),
                    "event_count": len(result.events),
                    "rng_event_count": len(result.rng_events),
                    "errors": list(result.errors),
                    "source_audit_replay": audit,
                    "event_was_not_reconstructed": event
                    in events_by_type[event_type],
                }
                if ok:
                    return attempt
                attempts.append(attempt)
    return {
        "ok": False,
        "reason": "no_real_production_event_context_executed_callback",
        "callback_event": family.callback_event,
        "callback_id": callback.callback_id,
        "attempt_count": len(attempts),
        "attempt_samples": attempts[:4],
    }


def _event_dispatch_probe_audit(
    rules: RuleBook,
    before_state: BattleState,
    event: GameEvent,
    result: Any,
) -> dict[str, Any]:
    replay = MutationReducer().replay_snapshot(
        before_state,
        result.mutations,
        result.after_state.snapshot().to_json(),
    )
    transition = BattleTransition(
        transaction=ActionTransaction(
            command=ActionCommand(
                actor_id=event.source_id or "event:producer",
                action_id="event:dispatch",
                action_level=0,
                source="status_callback",
            ),
            before=before_state.snapshot(),
            events=(event, *result.events),
            mutations=tuple(result.mutations),
            settlement=ActionSettlement(
                action_id="event:dispatch",
                actor_id=event.source_id or "event:producer",
                target_ids=((event.target_id,) if event.target_id else ()),
                records=tuple(result.records),
            ),
        ),
        after=result.after_state.snapshot(),
        rng_events=tuple(result.rng_events),
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    return {
        "ok": replay.ok and audit.ok,
        "replay_ok": replay.ok,
        "source_audit_ok": audit.ok,
        "audit_violations": [
            violation.to_json() for violation in audit.violations[:4]
        ],
    }


def _lifecycle_matrix(bundle: dict[str, Any], formal: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    state: BattleState = formal["_built"].state
    unit_id = str(formal["_unit_id"])
    detail = next(
        item
        for item in state.units[unit_id].flags.get("status_details", ())
        if isinstance(item, dict)
    )
    system = StatusSystem(rules)
    reducer = MutationReducer()

    selection = formal["_equipment_result"].dynamic_mechanisms[0]
    startup_spec = _equipment_startup_spec(rules, selection)
    startup_graph = rules.standalone_ability_graph(selection.graph_ref_id)
    if startup_graph is None:
        raise ValueError("formal S7 selection lost its admitted startup graph")
    startup_task = next(
        task
        for phase_id in startup_graph.phase_ids
        for task in rules.ability_tasks_for_phase(phase_id)
        if task.callback_kind == "OnStart"
        and not task.parent_task_id
        and task.opcode == "AddModifier"
        and task.effect_id
    )
    startup_effect = rules.effect(startup_task.effect_id)
    if startup_effect is None:
        raise ValueError("formal S7 startup task lost its effect")
    _, startup_binding = _startup_dynamic_values(
        startup_effect.payload.get("standard"),
        startup_spec,
    )
    stack_sample = _find_real_status_reapplication(bundle, "stack")
    replace_sample = _find_real_status_reapplication(bundle, "replace")
    remove_samples = {
        opcode: _find_real_status_removal(bundle, opcode=opcode)
        for opcode in ("RemoveModifier", "RemoveSelfModifier")
    }
    remove_sample = remove_samples["RemoveModifier"]
    dispatcher = EventDispatchSystem(rules, EffectRegistry(system))
    dispatch_state = stack_sample["after_second"]
    dispatch_results = []
    for event in stack_sample["second"].events:
        modifier_name = str(event.payload.get("modifier_name") or "")
        if not modifier_name or not _status_has_listener_for_event(
            dispatch_state,
            event.target_id,
            modifier_name,
            event.window,
        ):
            continue
        dispatched = dispatcher.dispatch_event(
            dispatch_state,
            event=event,
            unit_id=event.target_id,
            modifier_name=modifier_name,
        )
        dispatch_state = dispatched.after_state
        dispatch_results.append(dispatched)
    expiring_detail = {
        **detail,
        "remaining_duration": 1.0,
        "duration": max(float(detail.get("duration") or 1.0), 1.0),
        "life_step_moment": str(
            detail.get("life_step_moment") or "ModifierPhase1End"
        ),
    }
    expiring_state = _replace_status_detail(
        state,
        unit_id,
        str(detail.get("instance_id") or ""),
        expiring_detail,
    )
    expiry = system.apply_lifecycle_tick(
        expiring_state,
        unit_id,
        expiring_detail,
        str(expiring_detail["life_step_moment"]),
    )
    after_expiry = reducer.apply_all(expiring_state, expiry.mutations)
    sampled_results = (
        (
            "add",
            stack_sample["before"],
            stack_sample["first"],
            stack_sample["before_second"],
        ),
        (
            "replace_refresh",
            replace_sample["before_second"],
            replace_sample["second"],
            replace_sample["after_second"],
        ),
        (
            "stack",
            stack_sample["before_second"],
            stack_sample["second"],
            stack_sample["after_second"],
        ),
        *(
            (
                f"remove:{opcode}",
                sample["before_remove"],
                sample["remove"],
                sample["after_remove"],
            )
            for opcode, sample in sorted(remove_samples.items())
        ),
        ("expiry", expiring_state, expiry, after_expiry),
    )
    audit_rows = []
    for name, before, result, after in sampled_results:
        transition = _status_transition(
            before,
            _LifecycleResultAdapter(result),
            f"validation:p8_s7:{name}",
        )
        audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        replay = reducer.replay_snapshot(
            before,
            result.mutations,
            after.snapshot().to_json(),
        )
        audit_rows.append(
            {
                "operation": name,
                "source_audit": {
                    "ok": audit.ok,
                    "checked_mutations": audit.checked_mutations,
                    "checked_records": audit.checked_records,
                    "violation_count": len(audit.violations),
                    "violations": [
                        {
                            "mutation_id": violation.mutation_id,
                            "source": violation.source,
                            "path": list(violation.path),
                            "reason": violation.reason,
                            "missing_field": violation.missing_field,
                        }
                        for violation in audit.violations
                    ],
                },
                "replay": {
                    "ok": replay.ok,
                    "errors": list(replay.errors),
                    "conflict_count": len(replay.conflicts),
                },
            }
        )
    operations = Counter(
        str(trace.get("status") or "") for trace in formal["startup_traces"]
    )
    phase1_callback = next(
        (
            callback
            for callback in bundle["callbacks"]
            if callback.event == "OnPhase1"
            and callback.coverage_status == "executable"
            and callback.admission_status == "executable"
        ),
        None,
    )
    phase1_event = None
    if phase1_callback is not None:
        phase1_state = _callback_fixture_state(
            phase1_callback,
            dynamic_values=_callback_probe_dynamic_values(bundle, phase1_callback),
        )
        phase1_detail = next(
            item
            for item in phase1_state.units["ally:wearer"].flags.get(
                "status_details", ()
            )
            if isinstance(item, dict)
        )
        phase1_event = _status_phase1_lifecycle_event(
            phase1_state,
            "ally:wearer",
            phase1_detail,
            "ModifierPhase1End",
        )
    checks = {
        "add": bool(formal["status_details"])
        and stack_sample["first"].ok
        and stack_sample["first"].lifecycle_result is not None
        and stack_sample["first"].lifecycle_result.operation == "add"
        and bool(stack_sample["first"].mutations),
        "stack": stack_sample["second"].ok
        and stack_sample["second"].lifecycle_result is not None
        and stack_sample["second"].lifecycle_result.operation == "stack"
        and bool(stack_sample["second"].mutations),
        "refresh_by_source_declared_replace": replace_sample["second"].ok
        and replace_sample["second"].lifecycle_result is not None
        and replace_sample["second"].lifecycle_result.operation == "replace"
        and bool(replace_sample["second"].mutations),
        "remove_families": all(
            sample["remove"].ok
            and sample["remove"].lifecycle_result is not None
            and sample["remove"].lifecycle_result.operation == "remove"
            and bool(sample["remove"].mutations)
            and sample["remove_effect"].opcode == opcode
            for opcode, sample in remove_samples.items()
        ),
        "expiry": expiry.ok
        and expiry.operation == "expire"
        and bool(expiry.mutations),
        "listener_dispatched_at_real_lifecycle_event": bool(dispatch_results)
        and any(
            result.listener_records or result.records or result.mutations
            for result in dispatch_results
        )
        and not any(result.errors for result in dispatch_results),
        "listener_not_duplicated": all(
            len(
                {
                    str(row.get("callback_id") or "")
                    for row in result.listener_records
                    if isinstance(row, dict) and row.get("callback_id")
                }
            )
            == len(
                [
                    row
                    for row in result.listener_records
                    if isinstance(row, dict) and row.get("callback_id")
                ]
            )
            for result in dispatch_results
        ),
        "phase1_event_comes_from_scheduler_producer": phase1_event is not None
        and phase1_event.event_type == "status.lifecycle"
        and phase1_event.payload.get("callback_event") == "OnPhase1",
        "startup_dynamic_binding_source_real": startup_binding.get(
            "admission_status"
        )
        == "executable",
        "common_status_system_source": all(
            mutation.source == "status_system"
            for _, _, result, _ in sampled_results
            for mutation in result.mutations
        ),
        "source_audit": all(
            row["source_audit"]["ok"] is True for row in audit_rows
        ),
        "replay": all(row["replay"]["ok"] is True for row in audit_rows),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s7_status_lifecycle_audit_replay_v1",
        "ok": checks["ok"],
        "checks": checks,
        "startup_operation_counts": operations,
        "add": _compact_lifecycle_result(stack_sample["first"]),
        "refresh_by_source_declared_replace": _compact_lifecycle_result(
            replace_sample["second"]
        ),
        "stack": _compact_lifecycle_result(stack_sample["second"]),
        "remove": {
            opcode: _compact_lifecycle_result(sample["remove"])
            for opcode, sample in sorted(remove_samples.items())
        },
        "listener_dispatch": [
            {
                "mutation_count": len(result.mutations),
                "record_count": len(result.records),
                "listener_records": [
                    {
                        "callback_id": row.get("callback_id"),
                        "status": row.get("status"),
                        "reason": row.get("reason"),
                    }
                    for row in result.listener_records
                    if isinstance(row, dict)
                ],
                "errors": list(result.errors),
            }
            for result in dispatch_results
        ],
        "expiry": _compact_lifecycle_result(expiry),
        "audit_replay_samples": audit_rows,
        "mutation_samples": [
            _compact_mutation_evidence(mutation)
            for _, _, result, _ in sampled_results
            for mutation in result.mutations
        ],
        "_production_events": tuple(
            event
            for _, _, result, _ in sampled_results
            for event in result.events
        ) + ((phase1_event,) if phase1_event is not None else ()),
    }


def _compact_lifecycle_result(result: object) -> dict[str, Any]:
    lifecycle = getattr(result, "lifecycle_result", None)
    operation = getattr(lifecycle, "operation", None) or getattr(
        result, "operation", ""
    )
    mutations = tuple(getattr(result, "mutations", ()) or ())
    events = tuple(getattr(result, "events", ()) or ())
    return {
        "ok": bool(getattr(result, "ok", False)),
        "operation": str(operation or ""),
        "mutation_count": len(mutations),
        "mutation_ids": [mutation.stable_id() for mutation in mutations],
        "event_windows": [str(event.window) for event in events],
        "unsupported": list(getattr(result, "unsupported", ()) or ()),
    }


def _compact_mutation_evidence(mutation: object) -> dict[str, Any]:
    metadata = getattr(mutation, "metadata", {})
    source_paths: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            source_path = value.get("source_path")
            if isinstance(source_path, str) and source_path:
                source_paths.add(source_path)
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    collect(metadata)
    return {
        "mutation_id": mutation.stable_id(),
        "source": str(getattr(mutation, "source", "")),
        "op": str(getattr(mutation, "op", "")),
        "path": list(getattr(mutation, "path", ()) or ()),
        "reason": str(getattr(mutation, "reason", "")),
        "source_paths": sorted(source_paths),
    }


def _status_has_listener_for_event(
    state: BattleState,
    unit_id: str,
    modifier_name: str,
    event: str,
) -> bool:
    unit = state.units.get(unit_id)
    if unit is None:
        return False
    for detail in unit.flags.get("status_details", ()):
        if (
            not isinstance(detail, dict)
            or detail.get("modifier_name") != modifier_name
        ):
            continue
        by_event = detail.get("trigger_ids_by_event")
        return (
            isinstance(by_event, dict)
            and isinstance(by_event.get(event), (list, tuple))
            and bool(by_event[event])
        )
    return False


def _find_real_status_reapplication(
    bundle: dict[str, Any],
    operation: str,
) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    system = StatusSystem(rules)
    reducer = MutationReducer()
    for effect in sorted(bundle["nested_effects"], key=lambda item: item.effect_id):
        if effect.opcode != "AddModifier" or effect.coverage_status != "executable":
            continue
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict) or standard.get("target_alias") not in {
            "Caster",
            "ModifierOwnerEntity",
        }:
            continue
        dynamic_values = _equipment_effect_dynamic_values(bundle, effect)
        before = _lifecycle_fixture_state()
        source_id = f"validation:p8_s7:real:{effect.effect_id}"
        first = system.apply_add_modifier(
            before,
            effect,
            caster_id="ally:wearer",
            source_id=source_id,
            owner_id="ally:wearer",
            param_entity_id="ally:wearer",
            current_action_target_id="ally:wearer",
            dynamic_values=dynamic_values,
        )
        if not first.ok or not first.mutations:
            continue
        before_second = reducer.apply_all(before, first.mutations)
        second = system.apply_add_modifier(
            before_second,
            effect,
            caster_id="ally:wearer",
            source_id=source_id,
            owner_id="ally:wearer",
            param_entity_id="ally:wearer",
            current_action_target_id="ally:wearer",
            dynamic_values=dynamic_values,
        )
        if (
            second.ok
            and second.lifecycle_result is not None
            and second.lifecycle_result.operation == operation
            and second.mutations
        ):
            return {
                "effect": effect,
                "before": before,
                "first": first,
                "before_second": before_second,
                "second": second,
                "after_second": reducer.apply_all(
                    before_second,
                    second.mutations,
                ),
            }
    raise ValueError(f"no real equipment status {operation} sample")


def _find_real_status_removal(
    bundle: dict[str, Any],
    *,
    opcode: str | None = None,
) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    system = StatusSystem(rules)
    reducer = MutationReducer()
    adds_by_modifier: dict[str, list[EffectIR]] = defaultdict(list)
    removes_by_modifier: dict[str, list[EffectIR]] = defaultdict(list)
    selected_task_ids = _selected_executable_task_ids(bundle)
    selected_effect_ids = {
        task.effect_id
        for task in (*bundle["tasks"], *bundle["callback_tasks"])
        if task.task_id in selected_task_ids and task.effect_id
    }
    for effect in bundle["effects"]:
        if (
            effect.coverage_status != "executable"
            or effect.effect_id not in selected_effect_ids
            or not effect.source.source_path.startswith(
                "Config/ConfigAbility/Equip/"
            )
        ):
            continue
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            continue
        modifier_name = str(standard.get("modifier_name") or "")
        if not modifier_name:
            continue
        if effect.opcode == "AddModifier":
            adds_by_modifier[modifier_name].append(effect)
        elif effect.opcode in {"RemoveModifier", "RemoveSelfModifier"}:
            if opcode is not None and effect.opcode != opcode:
                continue
            removes_by_modifier[modifier_name].append(effect)
    for modifier_name in sorted(set(adds_by_modifier) & set(removes_by_modifier)):
        for add_effect in sorted(
            adds_by_modifier[modifier_name], key=lambda item: item.effect_id
        ):
            add_standard = add_effect.payload.get("standard")
            if not isinstance(add_standard, dict) or add_standard.get(
                "target_alias"
            ) not in {"Caster", "ModifierOwnerEntity"}:
                continue
            before = _lifecycle_fixture_state()
            add = system.apply_add_modifier(
                before,
                add_effect,
                caster_id="ally:wearer",
                source_id=f"validation:p8_s7:add:{add_effect.effect_id}",
                owner_id="ally:wearer",
                param_entity_id="ally:wearer",
                current_action_target_id="ally:wearer",
                dynamic_values=_equipment_effect_dynamic_values(
                    bundle,
                    add_effect,
                ),
            )
            if not add.ok or not add.mutations:
                continue
            before_remove = reducer.apply_all(before, add.mutations)
            for remove_effect in sorted(
                removes_by_modifier[modifier_name],
                key=lambda item: item.effect_id,
            ):
                remove_standard = remove_effect.payload.get("standard")
                if not isinstance(remove_standard, dict) or remove_standard.get(
                    "target_alias"
                ) not in {"Caster", "ModifierOwnerEntity"}:
                    continue
                remove = system.apply_remove_modifier(
                    before_remove,
                    remove_effect,
                    caster_id="ally:wearer",
                    source_id=f"validation:p8_s7:remove:{remove_effect.effect_id}",
                    owner_id="ally:wearer",
                    param_entity_id="ally:wearer",
                    current_action_target_id="ally:wearer",
                    dynamic_values=_equipment_effect_dynamic_values(
                        bundle,
                        remove_effect,
                    ),
                )
                if (
                    remove.ok
                    and remove.lifecycle_result is not None
                    and remove.lifecycle_result.operation == "remove"
                    and remove.mutations
                ):
                    return {
                        "add_effect": add_effect,
                        "remove_effect": remove_effect,
                        "before_remove": before_remove,
                        "remove": remove,
                        "after_remove": reducer.apply_all(
                            before_remove,
                            remove.mutations,
                        ),
                    }
    raise ValueError(
        "no real paired equipment AddModifier/removal sample: "
        + str(opcode or "any")
    )


def _equipment_effect_dynamic_values(
    bundle: dict[str, Any],
    effect: EffectIR,
) -> dict[str, float]:
    ability_name = str(effect.source.evidence.get("ability_name") or "")
    definitions = [
        definition
        for definition in bundle["definitions"]
        if definition.ability_source.ability_name == ability_name
        and definition.ability_source.source.source_path
        == effect.source.source_path
        and definition.mechanism_ref_ids
    ]
    if len(definitions) != 1:
        return {}
    definition = definitions[0]
    rank = next(
        (
            item
            for item in definition.superimposition_levels
            if item.level == 1
        ),
        None,
    )
    if rank is None:
        return {}
    mechanism = bundle["rules"].equipment_mechanism_ref(
        definition.mechanism_ref_ids[0].definition_identity
    ).value
    if mechanism is None:
        return {}
    values: dict[str, float] = {}
    for read_id in mechanism.parameter_binding_ids:
        read = bundle["rules"].equipment_ability_parameter_read(read_id)
        if (
            read is None
            or read.parameter_index < 0
            or read.parameter_index >= len(rank.parameters)
        ):
            continue
        values[read.dynamic_hash] = float(
            rank.parameters[read.parameter_index].exact_value
        )
    return values


def _lifecycle_fixture_state() -> BattleState:
    return BattleState(
        units={
            "ally:wearer": UnitState(
                unit_id="ally:wearer",
                side="ally",
                template_id="validation:ally",
                max_hp=100.0,
                hp=100.0,
                flags={"character_id": 1},
            ),
            "ally:peer": UnitState(
                unit_id="ally:peer",
                side="ally",
                template_id="validation:ally-peer",
                max_hp=100.0,
                hp=100.0,
                flags={"character_id": 2},
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="validation:enemy",
                max_hp=100.0,
                hp=100.0,
                flags={"monster_id": 1},
            ),
        },
        global_flags={"turn_owner_id": "ally:wearer"},
    )


def _unsupported_atomic_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    callback = next(
        callback
        for callback in bundle["callbacks"]
        if callback.coverage_status != "executable"
        and callback.blocked_reason
        not in {
            "equipment_event_family_non_gameplay",
        }
    )
    state = _callback_fixture_state(callback)
    result = StatusCallbackSystem(bundle["rules"]).execute(
        state,
        unit_id="ally:wearer",
        modifier_name=callback.modifier_name,
        event=callback.event,
        trigger_event=GameEvent(
            event_type="validation.unsupported",
            source_id="ally:wearer",
            target_id="enemy:target",
            window=callback.event,
            process_only=True,
            payload={
                "actor_id": "ally:wearer",
                "target_id": "enemy:target",
                "selected_target_ids": ["enemy:target"],
            },
        ),
    )
    checks = {
        "blocked": not result.ok and bool(result.errors),
        "state_unchanged": result.after_state == state,
        "no_mutations": not result.mutations,
        "source_preserved": callback.source.source_path.startswith(
            "Config/ConfigAbility/Equip/"
        ),
    }
    good_task = next(
        task
        for task in bundle["callback_tasks"]
        if task.opcode == "SetDynamicValueByHPRatio"
        and task.coverage_status == "executable"
        and not task.parent_task_id
        and bundle["rules"].status_callback(task.callback_id) is not None
    )
    good_callback = bundle["rules"].status_callback(good_task.callback_id)
    assert good_callback is not None
    bad_task = replace(
        good_task,
        task_id=f"{good_task.task_id}:validation-partial-failure",
        task_index=good_task.task_index + 10000,
        task_path=f"{good_task.task_path}.validation-partial-failure",
        task_payload={
            **good_task.task_payload,
            "ReadTargetType": "ValidationUnknownExplicitTarget",
        },
    )
    partial_ir = replace(
        bundle["ir"],
        status_callback_tasks=tuple(
            task
            for task in bundle["ir"].status_callback_tasks
            if task.callback_id != good_callback.callback_id
        )
        + (good_task, bad_task),
    )
    partial_state = _callback_fixture_state(good_callback)
    wearer = partial_state.units["ally:wearer"]
    partial_state = replace(
        partial_state,
        units={
            **partial_state.units,
            "ally:wearer": replace(wearer, max_hp=100.0, hp=50.0),
        },
    )
    partial_result = StatusCallbackSystem(RuleBook(partial_ir)).execute(
        partial_state,
        unit_id="ally:wearer",
        modifier_name=good_callback.modifier_name,
        event=good_callback.event,
        trigger_event=GameEvent(
            event_type="validation.partial_failure",
            source_id="ally:wearer",
            target_id="enemy:target",
            window=good_callback.event,
            process_only=True,
            payload={
                "actor_id": "ally:wearer",
                "target_id": "enemy:target",
                "selected_target_ids": ["enemy:target"],
            },
        ),
    )
    partial_records_process_only = bool(partial_result.records) and all(
        record.get("process_only") is True
        and not record.get("mutation_id")
        for record in partial_result.records
        if isinstance(record, dict)
    )
    checks.update(
        {
            "partial_execution_failure_rolls_back_state": (
                not partial_result.ok
                and partial_result.after_state == partial_state
            ),
            "partial_execution_failure_discards_mutations_events_and_rng": (
                not partial_result.mutations
                and not partial_result.events
                and not partial_result.rng_events
            ),
            "partial_execution_failure_keeps_only_process_records": (
                partial_records_process_only
            ),
        }
    )
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s7_unsupported_atomic_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "callback": callback.to_json(),
        "errors": list(result.errors),
        "records": list(result.records),
        "partial_execution": {
            "callback_id": good_callback.callback_id,
            "first_task_id": good_task.task_id,
            "failing_task_id": bad_task.task_id,
            "errors": list(partial_result.errors),
            "records": list(partial_result.records),
            "mutation_count": len(partial_result.mutations),
            "event_count": len(partial_result.events),
            "rng_event_count": len(partial_result.rng_events),
        },
    }


def _callback_probe_dynamic_values(
    bundle: dict[str, Any],
    callback: StatusCallbackIR,
) -> dict[str, float]:
    keys: set[str] = set()

    def collect(value: object, field_name: str = "") -> None:
        if isinstance(value, dict):
            if value.get("kind") == "dynamic_hash" and value.get("hash") is not None:
                keys.add(str(value["hash"]))
            for key, child in value.items():
                collect(child, str(key))
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                collect(child, field_name)
            return
        if not isinstance(value, str) or not value:
            return
        lowered_field = field_name.lower()
        if (
            "dynamicvalue" in lowered_field
            or "dynamic_value" in lowered_field
            or value.startswith(("MDF_", "Modifier_", "SkillEquip_", "_"))
        ):
            keys.add(value)

    for task in bundle["callback_tasks"]:
        if task.callback_id != callback.callback_id:
            continue
        collect(task.task_payload)
        if task.condition_id:
            condition = bundle["rules"].condition(task.condition_id)
            if condition is not None:
                collect(condition.payload)
        if task.effect_id:
            effect = bundle["rules"].effect(task.effect_id)
            if effect is not None:
                collect(effect.payload)
                if effect.modifier_definition_id:
                    definition = bundle["rules"].entity(
                        effect.modifier_definition_id
                    )
                    if definition is not None:
                        collect(definition.fields)
    for definition in bundle["rules"].modifier_definitions(
        callback.modifier_name
    ):
        collect(definition.fields)
    return {key: 1.0 for key in sorted(keys)}


def _callback_related_status_names(
    bundle: dict[str, Any],
    callback: StatusCallbackIR,
) -> tuple[str, ...]:
    names: set[str] = set()
    for task in bundle["callback_tasks"]:
        if task.callback_id != callback.callback_id or not task.effect_id:
            continue
        effect = bundle["rules"].effect(task.effect_id)
        if effect is None or effect.opcode not in {
            "RemoveModifier",
            "RemoveSelfModifier",
        }:
            continue
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            continue
        modifier_name = standard.get("modifier_name")
        if isinstance(modifier_name, str) and modifier_name:
            names.add(modifier_name)
    return tuple(sorted(names))


def _callback_fixture_state(
    callback: StatusCallbackIR,
    *,
    owner_id: str = "ally:wearer",
    event: GameEvent | None = None,
    dynamic_values: dict[str, float] | None = None,
    related_status_names: tuple[str, ...] = (),
) -> BattleState:
    detail = {
        "instance_id": "validation:p8_s7:blocked-status",
        "status_id": f"modifier:{callback.modifier_name}",
        "modifier_name": callback.modifier_name,
        "owner_id": owner_id,
        "source_id": "validation:p8_s7:blocked-source",
        "caster_id": owner_id,
        "stacks": 1,
        "max_stacks": 8,
        "duration": 2,
        "remaining_duration": 2,
        "life_step_moment": "ModifierPhase1End",
        "status_type": str(
            (event.payload.get("callback_status_type") if event is not None else "")
            or "Buff"
        ),
        "behavior_flags": tuple(
            event.payload.get("callback_behavior_flags", ())
            if event is not None
            and isinstance(event.payload.get("callback_behavior_flags"), (list, tuple))
            else ()
        ),
        "dynamic_values": dict(dynamic_values or {}),
        "trigger_ids_by_event": {callback.event: [callback.callback_id]},
        "source_trace": {"callback_source": callback.source.to_json()},
    }
    participant_ids = {
        owner_id,
        "ally:wearer",
        "enemy:target",
    }
    if event is not None:
        participant_ids.update(
            item
            for item in (event.source_id, event.target_id)
            if isinstance(item, str) and item and not item.startswith("scenario:")
        )
    units: dict[str, UnitState] = {}
    for unit_id in sorted(participant_ids):
        side = "enemy" if unit_id.startswith("enemy:") else "ally"
        flags: dict[str, JSONValue] = {
            "character_id": 1 if side == "ally" else 2,
            "monster_id": 2 if side == "enemy" else 0,
        }
        if unit_id == owner_id:
            flags["status_details"] = [detail]
        if related_status_names:
            flags["status_details"] = [
                *(
                    flags.get("status_details", [])
                    if isinstance(flags.get("status_details"), list)
                    else []
                ),
                *(
                    {
                        "instance_id": (
                            f"validation:p8_s7:related:{unit_id}:{modifier_name}"
                        ),
                        "status_id": f"modifier:{modifier_name}",
                        "modifier_name": modifier_name,
                        "owner_id": unit_id,
                        "caster_id": owner_id,
                        "source_id": "validation:p8_s7:related-status-source",
                        "stacks": 1,
                        "duration": 2,
                        "remaining_duration": 2,
                        "source_trace": {
                            "validation_basis": (
                                "real callback remove target positive context"
                            )
                        },
                    }
                    for modifier_name in related_status_names
                    if modifier_name != callback.modifier_name
                ),
            ]
        units[unit_id] = UnitState(
            unit_id=unit_id,
            side=side,
            template_id=f"validation:{side}",
            level=80,
            max_hp=100.0,
            hp=50.0 if unit_id == owner_id else 100.0,
            attack=100.0,
            defense=100.0,
            speed=100.0,
            toughness=10.0,
            max_toughness=10.0,
            resources={
                "critical_chance": 0.5,
                "critical_damage": 0.5,
                "effect_hit_rate": 0.5,
                "effect_resistance": 0.0,
            },
            flags=flags,
        )
    return BattleState(
        units=units,
        global_flags={
            "turn_owner_id": (
                str(event.payload.get("turn_owner_id") or event.source_id or owner_id)
                if event is not None
                else owner_id
            ),
        },
    )


def _replace_status_detail(
    state: BattleState,
    unit_id: str,
    instance_id: str,
    replacement: dict[str, JSONValue],
) -> BattleState:
    unit = state.units[unit_id]
    details = [
        replacement
        if isinstance(item, dict) and item.get("instance_id") == instance_id
        else item
        for item in unit.flags.get("status_details", ())
    ]
    return replace(
        state,
        units={
            **state.units,
            unit_id: replace(unit, flags={**unit.flags, "status_details": details}),
        },
    )


def _effective_stat_consumption_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    detail = {
        "instance_id": "validation:p8_s7:effective-stats",
        "status_id": "modifier:validation_effective_stats",
        "modifier_name": "validation_effective_stats",
        "owner_id": "ally:wearer",
        "caster_id": "ally:wearer",
        "source_trace": {"validation_basis": "typed runtime modifier contract"},
        "modifiers": [
            {"bucket": "attribute", "key": "attack_added_ratio", "value": 0.2, "raw_path": "validation.attack"},
            {"bucket": "attribute", "key": "speed_added_ratio", "value": 0.1, "raw_path": "validation.speed_ratio"},
            {"bucket": "attribute", "key": "speed_delta", "value": -5.0, "raw_path": "validation.speed_delta"},
            {"bucket": "crit", "key": "critical_chance", "value": 0.25, "raw_path": "validation.crit_rate"},
            {"bucket": "crit", "key": "critical_damage", "value": 0.5, "raw_path": "validation.crit_damage"},
            {"bucket": "status_probability", "key": "effect_hit_rate", "value": 0.3, "raw_path": "validation.effect_hit"},
            {"bucket": "status_probability", "key": "effect_resistance", "value": 0.4, "raw_path": "validation.effect_resistance"},
        ],
    }
    defense_detail = {
        **detail,
        "instance_id": "validation:p8_s7:defense-down",
        "owner_id": "enemy:target",
        "modifiers": [
            {"bucket": "attribute", "key": "defense_added_ratio", "value": -0.16, "raw_path": "validation.defense_down"},
        ],
    }
    actor = UnitState(
        unit_id="ally:wearer",
        side="ally",
        template_id="validation:actor",
        level=80,
        max_hp=1000.0,
        hp=1000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        resources={
            "critical_chance": 0.05,
            "critical_damage": 0.5,
            "effect_hit_rate": 0.1,
            "effect_resistance": 0.2,
        },
        flags={"status_details": [detail]},
    )
    pooled_actor = replace(
        actor,
        attack=130.0,
        stat_pools=(
            UnitStatPool(
                property_type="attack",
                base_value=100.0,
                static_percentage=0.2,
                static_flat=10.0,
                base_contribution_ids=("validation:base-attack",),
                percentage_contribution_ids=("validation:static-ratio",),
                flat_contribution_ids=("validation:static-flat",),
            ),
        ),
    )
    speed_pool = UnitStatPool(
        property_type="speed",
        base_value=100.0,
        base_contribution_ids=("validation:base-speed",),
    )
    canonical_two_pool_actor = replace(
        pooled_actor,
        stat_pools=(*pooled_actor.stat_pools, speed_pool),
    )

    def rejects_unit_state(factory) -> bool:
        try:
            factory()
        except (TypeError, ValueError):
            return True
        return False

    duplicate_pool_rejected = rejects_unit_state(
        lambda: replace(
            pooled_actor,
            stat_pools=(*pooled_actor.stat_pools, *pooled_actor.stat_pools),
        )
    )
    noncanonical_pool_order_rejected = rejects_unit_state(
        lambda: replace(
            canonical_two_pool_actor,
            stat_pools=tuple(reversed(canonical_two_pool_actor.stat_pools)),
        )
    )
    contradictory_panel_rejected = rejects_unit_state(
        lambda: replace(pooled_actor, attack=200.0)
    )
    canonical_pool_payload = unit_state_to_payload(canonical_two_pool_actor)
    duplicate_pool_payload = {
        **canonical_pool_payload,
        "stat_pools": [
            *canonical_pool_payload["stat_pools"],
            canonical_pool_payload["stat_pools"][0],
        ],
    }
    noncanonical_pool_payload = {
        **canonical_pool_payload,
        "stat_pools": list(reversed(canonical_pool_payload["stat_pools"])),
    }
    contradictory_panel_payload = {
        **canonical_pool_payload,
        "attack": 200.0,
    }
    duplicate_pool_payload_rejected = rejects_unit_state(
        lambda: unit_state_from_payload(duplicate_pool_payload)
    )
    noncanonical_pool_payload_rejected = rejects_unit_state(
        lambda: unit_state_from_payload(noncanonical_pool_payload)
    )
    contradictory_panel_payload_rejected = rejects_unit_state(
        lambda: unit_state_from_payload(contradictory_panel_payload)
    )
    canonical_pool_round_trip = unit_state_from_payload(
        canonical_pool_payload
    )
    target = UnitState(
        unit_id="enemy:target",
        side="enemy",
        template_id="validation:target",
        level=80,
        max_hp=1000.0,
        hp=1000.0,
        defense=100.0,
        speed=100.0,
        flags={"status_details": [defense_detail]},
    )
    state = BattleState(units={actor.unit_id: actor, target.unit_id: target})
    attack_basis = resolve_scaling_basis(
        state,
        attacker_id=actor.unit_id,
        target_id=target.unit_id,
        basis={"kind": "unit_stat", "unit_ref": "attacker", "stat": "attack"},
    )
    defense_basis = resolve_scaling_basis(
        state,
        attacker_id=actor.unit_id,
        target_id=target.unit_id,
        basis={"kind": "unit_stat", "unit_ref": "target", "stat": "defense"},
    )
    timeline_rule = TimelineRuleIR(
        timeline_rule_id="validation:p8_s7:timeline",
        base_action_gauge=10000.0,
        initial_action_value_rule="base_action_gauge / speed",
        turn_reset_rule="base_action_gauge / speed",
        source_kind="kernel_fixture",
        source=IRSource(
            source_path="validation/p8_s7/effective_status_stats",
            raw_type="KernelFixture",
            raw_id="timeline",
            evidence={"purpose": "effective speed consumer probe"},
        ),
    )
    timeline_result = TimelineSystem().initialize_action_values(state, timeline_rule)
    actor_av_mutation = next(
        mutation
        for mutation in timeline_result.mutations
        if mutation.path == ("units", actor.unit_id, "action_value")
    )
    effective_speed = effective_unit_stat(actor, "speed")
    expected_action_value = TimelineSystem().full_action_value(
        effective_speed.value,
        timeline_rule,
    )
    action_definition = next(
        action
        for action in bundle["ir"].action_definitions
        if action.coverage_status == "executable"
    )
    damage_result = DirectDamageFormula().calculate(
        DamageFormulaInput(
            state=state,
            attacker_id=actor.unit_id,
            target_id=target.unit_id,
            action_definition=action_definition,
            attack_type="Normal",
            element_type=None,
            scaling_ratio=1.0,
            scaling_basis={"kind": "unit_stat", "unit_ref": "attacker", "stat": "attack"},
            crit_mode="forced_crit",
            source_trace={"validation": "p8_s7_effective_status_stats"},
        )
    )
    raw_negation_rows = _raw_equipment_negation_rows(bundle)
    synthetic_negation = lower_numeric_expression(
        {
            "PostfixExpr": {
                "OpCodes": [0, 0, 14, 17],
                "FixedValues": [{"Value": 0.16}],
            }
        }
    )
    synthetic_negation_result = RuleEvaluator().evaluate_numeric(
        synthetic_negation,
        NumericEvaluationContext(),
    )
    defense_bucket = next(
        bucket
        for bucket in damage_result.modifier_ledger.buckets
        if bucket.bucket == "defense"
    )
    pooled_attack = effective_unit_stat(pooled_actor, "attack")
    raw_stack_rows = [
        row
        for row in _scan_raw_families(bundle)
        if row["kind"] == "task" and row["family"].startswith("StackProperty:")
    ]
    stack_semantic_rows = []
    for row in raw_stack_rows:
        property_name = row["family"].split(":", 2)[1]
        semantic_stage = classify_equipment_task(
            "StackProperty",
            {"$type": "StackProperty", "Property": property_name},
        )
        mapped = _map_stack_property(property_name)
        has_direct_consumer = bool(
            mapped is not None
            and status_modifier_has_direct_combat_consumer(mapped[0], mapped[1])
        )
        stack_semantic_rows.append(
            {
                "source_identity": row["source_identity"],
                "property": property_name,
                "semantic_stage": semantic_stage,
                "selected_graph_stage": row["stage"],
                "mapped_bucket": mapped[0] if mapped is not None else None,
                "mapped_key": mapped[1] if mapped is not None else None,
                "direct_s7_consumer": has_direct_consumer,
                "selected_for_s7_runtime": row["stage"] == "s7",
                "ok": (semantic_stage == "s7") == has_direct_consumer,
            }
        )
    checks = {
        "attack_status_changes_scaling_basis": attack_basis.ok and attack_basis.value == 120.0,
        "defense_status_changes_scaling_and_damage_formula": defense_basis.ok
        and defense_basis.value == 84.0
        and defense_bucket.metadata.get("effective_defense") == 84.0,
        "speed_status_changes_timeline_action_value": isclose(
            effective_speed.value, 105.0, rel_tol=0.0, abs_tol=1e-12
        )
        and isclose(
            float(actor_av_mutation.after),
            float(expected_action_value),
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "crit_status_changes_damage_formula": isclose(
            damage_result.crit_resolution.crit_rate,
            0.3,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and isclose(
            damage_result.crit_resolution.crit_damage,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "status_probability_reads_effective_hit_and_resistance": _unit_resource(
            state, actor.unit_id, "effect_hit_rate"
        ) is not None
        and isclose(
            float(_unit_resource(state, actor.unit_id, "effect_hit_rate")),
            0.4,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and _unit_resource(state, actor.unit_id, "effect_resistance") is not None
        and isclose(
            float(_unit_resource(state, actor.unit_id, "effect_resistance")),
            0.6,
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "static_and_dynamic_pools_merge_once": isclose(
            pooled_attack.value,
            150.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and pooled_attack.base_value == 100.0
        and pooled_attack.static_ratio == 0.2
        and pooled_attack.static_flat == 10.0
        and pooled_attack.ratio_delta == 0.2,
        "duplicate_stat_pool_property_rejected": duplicate_pool_rejected
        and duplicate_pool_payload_rejected,
        "stat_pool_order_is_canonical_and_fail_closed": (
            noncanonical_pool_order_rejected
            and noncanonical_pool_payload_rejected
            and tuple(
                pool.property_type
                for pool in canonical_pool_round_trip.stat_pools
            )
            == ("attack", "speed")
        ),
        "stat_pool_panel_value_must_recompute_exactly": (
            contradictory_panel_rejected
            and contradictory_panel_payload_rejected
            and canonical_pool_round_trip.attack == 130.0
            and canonical_pool_round_trip.speed == 100.0
        ),
        "stack_property_semantics_partitioned_by_real_consumer": bool(
            stack_semantic_rows
        )
        and all(row["ok"] is True for row in stack_semantic_rows),
        "deferred_stack_property_sources_remain_non_executable": any(
            row["semantic_stage"] == "s8" for row in stack_semantic_rows
        )
        and all(
            row["direct_s7_consumer"] is False
            for row in stack_semantic_rows
            if row["semantic_stage"] == "s8"
        )
        and all(
            row["selected_for_s7_runtime"] is False
            for row in stack_semantic_rows
            if row["selected_graph_stage"] == "s8"
        ),
        "unary_opcode_14_is_negation": synthetic_negation_result.ok
        and synthetic_negation_result.value == -0.16,
        "all_real_equipment_opcode_14_nodes_lower_to_negate": bool(raw_negation_rows)
        and all(row["ok"] is True for row in raw_negation_rows),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s7_effective_status_stat_consumption_v2",
        "ok": checks["ok"],
        "checks": checks,
        "effective_attack": effective_unit_stat(actor, "attack").to_json(),
        "effective_defense": effective_unit_stat(target, "defense").to_json(),
        "effective_speed": effective_speed.to_json(),
        "pooled_attack": pooled_attack.to_json(),
        "stat_pool_invariant_negatives": {
            "duplicate_model_rejected": duplicate_pool_rejected,
            "duplicate_payload_rejected": duplicate_pool_payload_rejected,
            "noncanonical_model_rejected": noncanonical_pool_order_rejected,
            "noncanonical_payload_rejected": noncanonical_pool_payload_rejected,
            "contradictory_model_rejected": contradictory_panel_rejected,
            "contradictory_payload_rejected": contradictory_panel_payload_rejected,
            "canonical_round_trip": unit_state_to_payload(
                canonical_pool_round_trip
            ),
        },
        "stack_property_semantic_rows": stack_semantic_rows,
        "timeline_action_value": actor_av_mutation.after,
        "damage_formula": damage_result.to_json(),
        "synthetic_negation": synthetic_negation_result.to_json(),
        "real_negation_rows": raw_negation_rows,
    }


def _raw_equipment_negation_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative, selected in sorted(bundle["equipment_sources"].items()):
        document = json.loads(
            (Path(bundle["tbgd_root"]) / relative).read_text(encoding="utf-8")
        )
        abilities = document.get("AbilityList")
        if not isinstance(abilities, list):
            continue
        for ability_index in sorted(selected):
            _collect_raw_negation_rows(
                abilities[ability_index],
                f"{relative}#$.AbilityList[{ability_index}]",
                rows,
            )
    return rows


def _collect_raw_negation_rows(
    value: object,
    path: str,
    rows: list[dict[str, Any]],
) -> None:
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_raw_negation_rows(child, f"{path}[{index}]", rows)
        return
    if not isinstance(value, dict):
        return
    postfix = value.get("PostfixExpr")
    if isinstance(postfix, dict):
        opcodes = _decode_opcodes(postfix.get("OpCodes"))
        opcode_14_count = opcodes.count(14) if opcodes is not None else 0
        if opcode_14_count:
            lowered = lower_numeric_expression(value)
            instructions = lowered.get("instructions")
            negate_count = (
                sum(
                    isinstance(item, dict) and item.get("opcode") == "negate"
                    for item in instructions
                )
                if isinstance(instructions, list)
                else (opcode_14_count if lowered.get("kind") == "fixed" else 0)
            )
            rows.append(
                {
                    "source_identity": path,
                    "opcode_14_count": opcode_14_count,
                    "negate_instruction_count": negate_count,
                    "ok": lowered.get("supported") is not False
                    and negate_count == opcode_14_count,
                    "lowered": lowered,
                }
            )
    for key, child in value.items():
        _collect_raw_negation_rows(child, f"{path}.{key}", rows)


def _runtime_boundary() -> dict[str, Any]:
    package_root = Path(__file__).resolve().parents[1]
    runtime_files = (
        package_root / "systems",
        package_root / "scenarios",
    )
    handler_hits = []
    raw_reads = []
    for directory in runtime_files:
        for path in directory.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "light_cone_handlers" in source or "equipment_handlers" in source:
                handler_hits.append(path.relative_to(package_root).as_posix())
            if "Config/ConfigAbility/Equip/" in source:
                raw_reads.append(path.relative_to(package_root).as_posix())
    return {
        "schema_version": "p8_s7_runtime_boundary_v1",
        "equipment_specific_runtime_handlers": len(handler_hits),
        "runtime_raw_equipment_reads": len(raw_reads),
        "handler_hits": handler_hits,
        "raw_read_hits": raw_reads,
        "shared_runtime_symbols": {
            "status": inspect.getsourcefile(StatusSystem),
            "callbacks": inspect.getsourcefile(StatusCallbackSystem),
            "evaluator": inspect.getsourcefile(RuleEvaluator),
        },
    }


def _short_type(value: Any) -> str:
    return str(value or "").rsplit(".", 1)[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=VALIDATION_VERSION)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    tbgd_root = args.tbgd_root.resolve() if args.tbgd_root else find_tbgd_root(Path.cwd())
    summary = run_validation(tbgd_root, args.output_dir.resolve())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
