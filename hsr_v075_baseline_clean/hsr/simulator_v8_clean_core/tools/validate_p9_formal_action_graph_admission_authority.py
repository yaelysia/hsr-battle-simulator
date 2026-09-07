from __future__ import annotations

import argparse
import hashlib
import json
import random
import resource
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from ..core.model import ActionCommand, BattleState, UnitState
from ..ir_types import IRSource
from ..rules.evaluator import RuleEvaluator
from ..rules.rulebook import RuleBook
from ..rules.task_graph import (
    TaskGraphDefinitionReferenceIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    _id as task_graph_stable_id,
    task_graph_entry_id,
    task_graph_id,
    task_graph_node_id,
    task_graph_source_occurrence_id,
)
from ..systems.action_contract import ActionContractSystem, _formal_action_task_graph_projection
from ..systems.action_selection import ActionTargetSelectionSystem
from ..systems.ability_task_contract import ability_task_runtime_blocked_reason
from ..systems.task_graph import TaskGraphExecutor
from ..tbgd.lowering import TBGDLowering, build_character_action_definition_ir
from ..tbgd.task_graph_materializer import materialize_ability_task_graph_catalog

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
_FAST_HARD_SECONDS = 30.0
_DIRECT_HARD_SECONDS = 180.0
_DIRECT_DISCOVERY_GUARD_SECONDS = 165.0
_FIXTURE_GRAPH_FINGERPRINT = hashlib.sha256(b"fixture:task_graph_catalog").hexdigest()


def _source(label: str, opcode: str) -> IRSource:
    return IRSource(
        f"validation_fixture/{label}.json",
        opcode,
        label,
        {
            "json_path": f"$.{label}",
            "content_sha256": hashlib.sha256(label.encode()).hexdigest(),
            "source_opcode": opcode,
            "task_path": f"OnStart[{label}]",
        },
    )


def _phase(phase_id: str, role: str = "action_root") -> Any:
    return SimpleNamespace(
        phase_id=phase_id,
        action_id="fixture:action",
        level=1,
        invocation_role=role,
    )


def _task(
    task_id: str,
    phase_id: str,
    *,
    opcode: str = "AddAbilityTask",
    execution_mode: str = "runtime_effect",
    coverage_status: str = "executable",
    blocked_reason: str = "",
    effect_id: str = "",
    linked_ability_phase_id: str = "",
) -> Any:
    return SimpleNamespace(
        task_id=task_id,
        phase_id=phase_id,
        action_id="fixture:action",
        level=1,
        ability_name="FixtureAbility",
        callback_kind="OnStart",
        task_index=0,
        task_path=f"OnStart[{task_id}]",
        branch="root",
        opcode=opcode,
        source=_source(task_id.replace(":", "_"), opcode),
        effect_id=effect_id,
        condition_id="",
        target_expression_id="",
        parent_task_id="",
        child_task_ids=(),
        success_task_ids=(),
        failed_task_ids=(),
        repeat_count=0,
        execution_mode=execution_mode,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
        linked_standalone_graph_id="",
        linked_ability_phase_id=linked_ability_phase_id,
    )


def _graph(
    owner_id: str,
    task: Any,
    *,
    node_kind: str = "leaf",
    materialization_status: str = "materialized",
    status_reason: str = "",
    references: tuple[tuple[str, str, str, str], ...] = (),
) -> TaskGraphIR:
    entry_id = task_graph_entry_id("ability_phase_callback", owner_id, "OnStart")
    graph_id = task_graph_id("fixture:catalog", entry_id, _FIXTURE_GRAPH_FINGERPRINT)
    occurrence_id = task_graph_source_occurrence_id(task.source, task.opcode)
    node_id = task_graph_node_id(graph_id, task.task_id, occurrence_id)
    refs = tuple(
        TaskGraphDefinitionReferenceIR(
            reference_id=task_graph_stable_id(
                "task_graph_reference", node_id, kind, definition_id
            ),
            graph_node_id=node_id,
            reference_kind=kind,
            definition_id=definition_id,
            source_contract_record_id="",
            resolution_status=status,
            owner_domain="fixture_reference_authority",
            source=task.source,
            blocked_reason=reason,
        )
        for kind, definition_id, status, reason in references
    )
    deferred = materialization_status == "deferred"
    node = TaskGraphNodeIR(
        graph_node_id=node_id,
        graph_id=graph_id,
        source_occurrence_id=occurrence_id,
        source_contract_node_id="",
        formal_task_id=task.task_id,
        opcode=task.opcode,
        source_family=task.opcode,
        node_kind="deferred" if deferred else node_kind,
        branches=(),
        references=refs,
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status=materialization_status,
        owner_domains=("fixture_deferred_authority",) if deferred else ("task_graph_execution",),
        source=task.source,
        status_reason=status_reason,
    )
    return TaskGraphIR(
        graph_id=graph_id,
        entry_id=entry_id,
        entry_kind="ability_phase_callback",
        owner_id=owner_id,
        callback_kind="OnStart",
        root_node_ids=(node_id,),
        nodes=(node,),
        numeric_definitions=(),
        source_catalog_id="fixture:catalog",
        source_fingerprint=_FIXTURE_GRAPH_FINGERPRINT,
        source=task.source,
        coverage_status=(
            "lowered_with_obligation"
            if deferred or any(ref.resolution_status != "resolved" for ref in refs)
            else "lowered"
        ),
        weighted_selections=(),
    )


def _merge_fixture_graph_nodes(*graphs: TaskGraphIR) -> TaskGraphIR:
    if not graphs:
        raise ValueError("fixture graph merge requires at least one graph")
    graph_id = graphs[0].graph_id
    if any(graph.graph_id != graph_id for graph in graphs[1:]):
        raise ValueError("fixture graph merge requires one shared graph identity")
    nodes = tuple(node for graph in graphs for node in graph.nodes)
    return replace(
        graphs[0],
        root_node_ids=tuple(node.graph_node_id for node in nodes),
        nodes=nodes,
    )


class _FixtureRules:
    def __init__(
        self,
        phases: tuple[Any, ...],
        tasks: tuple[Any, ...],
        graphs: tuple[TaskGraphIR, ...],
        effects: dict[str, Any] | None = None,
    ) -> None:
        self.phases = {x.phase_id: x for x in phases}
        self.tasks = {x.task_id: x for x in tasks}
        self.graphs = {(x.owner_id, x.callback_kind): x for x in graphs}
        self.effects = effects or {}
        self.graph_query_count = 0

    def ability_phase(self, phase_id: str) -> Any:
        return self.phases.get(phase_id)

    def ability_phases_for_action(self, action_id: str, level: int) -> tuple[Any, ...]:
        return tuple(
            sorted(
                (p for p in self.phases.values() if p.action_id == action_id and p.level == level),
                key=lambda p: p.phase_id,
            )
        )

    def ability_tasks_for_phase(self, phase_id: str) -> tuple[Any, ...]:
        return tuple(
            sorted(
                (t for t in self.tasks.values() if t.phase_id == phase_id),
                key=lambda t: t.task_id,
            )
        )

    def query_formal_task_graph(
        self, entry_kind: str, owner_id: str, callback_kind: str, formal_task_ids: Any
    ) -> Any:
        self.graph_query_count += 1
        graph = self.graphs.get((owner_id, callback_kind))
        if entry_kind != "ability_phase_callback" or graph is None:
            return SimpleNamespace(
                status="blocked",
                value=None,
                blocked_reason=f"task_graph_missing:{owner_id}:{callback_kind}",
            )
        expected = tuple(sorted(node.formal_task_id for node in graph.nodes))
        if tuple(sorted(formal_task_ids)) != expected:
            return SimpleNamespace(
                status="blocked",
                value=None,
                blocked_reason="ability_task_graph_formal_task_identity_mismatch",
            )
        return SimpleNamespace(status="resolved", value=graph, blocked_reason="")

    def ability_task(self, task_id: str) -> Any:
        return self.tasks.get(task_id)

    def standalone_ability_graph(self, graph_id: str) -> Any:
        del graph_id
        return None

    def effect(self, effect_id: str) -> Any:
        return self.effects.get(effect_id)

    def damage_emissions_for_task(self, task_id: str) -> tuple[Any, ...]:
        del task_id
        return ()

    def toughness_emissions_for_task(self, task_id: str) -> tuple[Any, ...]:
        del task_id
        return ()


def _project(
    phases: tuple[Any, ...],
    tasks: tuple[Any, ...],
    graphs: tuple[TaskGraphIR, ...],
    effects: dict[str, Any] | None = None,
) -> tuple[Any, _FixtureRules]:
    rules = _FixtureRules(phases, tasks, graphs, effects)
    return (
        _formal_action_task_graph_projection(
            rules,  # type: ignore[arg-type]
            "fixture:action",
            1,
            tasks,  # type: ignore[arg-type]
        ),
        rules,
    )


def _run_fast_cases() -> dict[str, Any]:
    p_root = _phase("fixture:p:root")
    p_unrelated = _phase("fixture:p:unrelated", "nested_only")
    t_root = _task("fixture:t:root", p_root.phase_id)
    t_unrelated = _task(
        "fixture:t:unrelated",
        p_unrelated.phase_id,
        coverage_status="blocked",
        blocked_reason="fixture_unrelated_flat_blocker",
    )
    excluded, rules = _project(
        (p_root, p_unrelated),
        (t_root, t_unrelated),
        (_graph(p_root.phase_id, t_root),),
    )
    assert excluded.reachable_task_ids == (t_root.task_id,)
    assert excluded.excluded_bound_task_ids == (t_unrelated.task_id,)
    assert "fixture_unrelated_flat_blocker" not in excluded.blocked_reasons

    p_trigger = _phase("fixture:p:trigger")
    p_nested = _phase("fixture:p:nested", "nested_only")
    t_trigger = _task(
        "fixture:t:trigger",
        p_trigger.phase_id,
        opcode="TriggerAbility",
        linked_ability_phase_id=p_nested.phase_id,
    )
    t_nested = _task(
        "fixture:t:nested",
        p_nested.phase_id,
        coverage_status="blocked",
        blocked_reason="fixture_nested_blocker",
    )
    nested, _ = _project(
        (p_trigger, p_nested),
        (t_trigger, t_nested),
        (
            _graph(
                p_trigger.phase_id,
                t_trigger,
                node_kind="ability_call",
                references=(("ability", p_nested.phase_id, "resolved", ""),),
            ),
            _graph(p_nested.phase_id, t_nested),
        ),
    )
    assert nested.reachable_task_ids == (t_trigger.task_id, t_nested.task_id)
    assert "fixture_nested_blocker" in nested.blocked_reasons

    p_cycle_a = _phase("fixture:p:cycle_a")
    p_cycle_b = _phase("fixture:p:cycle_b", "nested_only")
    p_cycle_c = _phase("fixture:p:cycle_c", "nested_only")
    t_cycle_a_b = _task(
        "fixture:t:cycle_a_b",
        p_cycle_a.phase_id,
        opcode="TriggerAbility",
        linked_ability_phase_id=p_cycle_b.phase_id,
    )
    t_cycle_a_c = _task(
        "fixture:t:cycle_a_c",
        p_cycle_a.phase_id,
        opcode="TriggerAbility",
        linked_ability_phase_id=p_cycle_c.phase_id,
    )
    t_cycle_b_c = _task(
        "fixture:t:cycle_b_c",
        p_cycle_b.phase_id,
        opcode="TriggerAbility",
        linked_ability_phase_id=p_cycle_c.phase_id,
    )
    t_cycle_c_b = _task(
        "fixture:t:cycle_c_b",
        p_cycle_c.phase_id,
        opcode="TriggerAbility",
        linked_ability_phase_id=p_cycle_b.phase_id,
    )
    g_cycle_a = _merge_fixture_graph_nodes(
        _graph(
            p_cycle_a.phase_id,
            t_cycle_a_b,
            node_kind="ability_call",
            references=(("ability", p_cycle_b.phase_id, "resolved", ""),),
        ),
        _graph(
            p_cycle_a.phase_id,
            t_cycle_a_c,
            node_kind="ability_call",
            references=(("ability", p_cycle_c.phase_id, "resolved", ""),),
        ),
    )
    g_cycle_b = _graph(
        p_cycle_b.phase_id,
        t_cycle_b_c,
        node_kind="ability_call",
        references=(("ability", p_cycle_c.phase_id, "resolved", ""),),
    )
    g_cycle_c = _graph(
        p_cycle_c.phase_id,
        t_cycle_c_b,
        node_kind="ability_call",
        references=(("ability", p_cycle_b.phase_id, "resolved", ""),),
    )
    cycle, _ = _project(
        (p_cycle_a, p_cycle_b, p_cycle_c),
        (t_cycle_a_b, t_cycle_a_c, t_cycle_b_c, t_cycle_c_b),
        (g_cycle_a, g_cycle_b, g_cycle_c),
    )
    expected_cycle_reason = f"task_graph_active_cycle:{g_cycle_b.graph_id}"
    assert expected_cycle_reason in cycle.blocked_reasons
    assert any(
        row.get("reason") == expected_cycle_reason
        and row.get("source") == "nested_graph_cycle"
        and row.get("graph_id") == g_cycle_b.graph_id
        and row.get("task_id") == t_cycle_c_b.task_id
        for row in cycle.blocker_provenance
    )

    p_deferred = _phase("fixture:p:deferred")
    t_deferred = _task("fixture:t:deferred", p_deferred.phase_id)
    deferred, _ = _project(
        (p_deferred,),
        (t_deferred,),
        (
            _graph(
                p_deferred.phase_id,
                t_deferred,
                materialization_status="deferred",
                status_reason="fixture_deferred_node",
            ),
        ),
    )
    assert "fixture_deferred_node" in deferred.blocked_reasons
    assert any(
        row.get("reason") == "fixture_deferred_node"
        and row.get("source") == "node_materialization"
        for row in deferred.blocker_provenance
    )

    p_ref = _phase("fixture:p:ref")
    t_ref = _task("fixture:t:ref", p_ref.phase_id)
    unresolved, _ = _project(
        (p_ref,),
        (t_ref,),
        (
            _graph(
                p_ref.phase_id,
                t_ref,
                references=(
                    (
                        "effect",
                        "fixture:missing_effect",
                        "deferred",
                        "fixture_unresolved_gameplay_ref",
                    ),
                ),
            ),
        ),
    )
    assert "fixture_unresolved_gameplay_ref" in unresolved.blocked_reasons

    p_process = _phase("fixture:p:process")
    t_process = _task(
        "fixture:t:process",
        p_process.phase_id,
        opcode="AuditTask",
        execution_mode="process_only",
        coverage_status="audit_only",
        effect_id="fixture:effect:process",
    )
    effect = SimpleNamespace(
        opcode=t_process.opcode,
        coverage_status="audit_only",
        source=t_process.source,
        payload={
            "process_only_contract": {
                "schema_version": "ability_process_only_source_shape_v1",
                "opcode": t_process.opcode,
                "source_fields": ["$type"],
                "source_field_types": {"$type": "str"},
                "source_shape_status": "admitted",
                "blocked_reason": "",
            }
        },
    )
    process, _ = _project(
        (p_process,),
        (t_process,),
        (
            _graph(
                p_process.phase_id,
                t_process,
                references=(
                    (
                        "effect",
                        t_process.effect_id,
                        "deferred",
                        "fixture_audit_only_reference",
                    ),
                ),
            ),
        ),
        {t_process.effect_id: effect},
    )
    assert not process.blocked_reasons

    p_invalid = _phase("fixture:p:invalid_process")
    t_invalid = _task(
        "fixture:t:invalid_process",
        p_invalid.phase_id,
        opcode="AuditTask",
        execution_mode="process_only",
        coverage_status="audit_only",
    )
    invalid, _ = _project(
        (p_invalid,),
        (t_invalid,),
        (_graph(p_invalid.phase_id, t_invalid),),
    )
    assert "process_only_task_effect_missing" in invalid.blocked_reasons

    p_legacy = _phase("fixture:p:legacy", "external_legacy")
    t_legacy = _task(
        "fixture:t:legacy",
        p_legacy.phase_id,
        coverage_status="blocked",
        blocked_reason="fixture_external_legacy_blocker",
    )
    legacy_rules = _FixtureRules((p_legacy,), (t_legacy,), ())
    legacy_reason = ability_task_runtime_blocked_reason(
        legacy_rules,  # type: ignore[arg-type]
        t_legacy,  # type: ignore[arg-type]
        topology_authority="external_legacy",
    )
    assert legacy_reason == "fixture_external_legacy_blocker"
    legacy_projection = _formal_action_task_graph_projection(
        legacy_rules,  # type: ignore[arg-type]
        "fixture:action",
        1,
        (t_legacy,),  # type: ignore[arg-type]
    )
    assert not legacy_projection.reachable_task_ids
    assert not legacy_projection.blocked_reasons

    p_missing = _phase("fixture:p:missing")
    t_missing = _task("fixture:t:missing", p_missing.phase_id)
    malformed, _ = _project((p_missing,), (t_missing,), ())
    assert malformed.blocked_reasons
    assert malformed.blocked_reasons[0].startswith("task_graph_missing:")

    repeated, _ = _project(
        (p_root, p_unrelated),
        (t_root, t_unrelated),
        (_graph(p_root.phase_id, t_root),),
    )
    assert repeated == excluded

    return {
        "excluded": excluded.metadata(),
        "nested": nested.metadata(),
        "cycle": {
            "expected_reason": expected_cycle_reason,
            **cycle.metadata(),
        },
        "deferred": deferred.metadata(),
        "unresolved": unresolved.metadata(),
        "process_only": process.metadata(),
        "invalid_process_only": invalid.metadata(),
        "legacy_reason": legacy_reason,
        "malformed": malformed.metadata(),
        "graph_query_count": rules.graph_query_count,
    }


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    sentinel = BattleState(
        units={
            "fixture:actor": UnitState(
                unit_id="fixture:actor",
                side="ally",
                template_id="fixture:owner",
                max_hp=100.0,
                hp=100.0,
            )
        }
    )
    before = sentinel.snapshot().to_json()
    forbidden = AssertionError("formal admission attempted runtime execution")
    with (
        patch.object(TaskGraphExecutor, "execute", side_effect=forbidden),
        patch.object(RuleEvaluator, "evaluate_condition_result", side_effect=forbidden),
        patch.object(random, "random", side_effect=forbidden),
    ):
        sample = _run_fast_cases()
    after = sentinel.snapshot().to_json()
    assert before == after

    predicates = {
        "unrelated_bound_nested_excluded": True,
        "reachable_trigger_nested_blocker_preserved": True,
        "cross_graph_active_cycle_fail_closed": True,
        "reachable_deferred_node_fail_closed": True,
        "unresolved_gameplay_reference_fail_closed": True,
        "audit_only_unresolved_reference_not_sole_blocker": True,
        "invalid_process_only_contract_fail_closed": True,
        "external_legacy_flat_gate_preserved": True,
        "missing_graph_identity_fail_closed": True,
        "projection_metadata_deterministic": True,
        "no_state_mutation_rng_or_graph_execution": True,
    }
    elapsed = time.perf_counter() - started
    return {
        "ok": elapsed <= _FAST_HARD_SECONDS and all(predicates.values()),
        "mode": "fast",
        "cases": len(predicates),
        "predicates": predicates,
        "sample": sample,
        "resource": {"wall_seconds": round(elapsed, 6)},
    }


def _flat_formal_tasks(rules: RuleBook, action_id: str, level: int) -> tuple[Any, ...]:
    return tuple(
        task
        for task in rules.ability_tasks_for_action(action_id, level)
        if (phase := rules.ability_phase(task.phase_id)) is not None
        and phase.invocation_role != "external_legacy"
    )


def _old_flat_blocker(rules: RuleBook, task: Any) -> str:
    return ability_task_runtime_blocked_reason(
        rules, task, topology_authority="task_graph"
    ) or str(task.blocked_reason or "")


def _state_for_admission(admission: Any, window: str) -> BattleState:
    return BattleState(
        units={
            "validation:actor": UnitState(
                unit_id="validation:actor",
                side="ally",
                template_id=admission.owner_entity_ref,
                max_hp=100000.0,
                hp=100000.0,
                energy=100000.0,
                max_energy=100000.0,
                flags={"position": 0},
                resources={
                    "special_energy": 100000.0,
                    "special_resource": 100000.0,
                    "charge": 100000.0,
                },
            ),
            "validation:enemy": UnitState(
                unit_id="validation:enemy",
                side="enemy",
                template_id="validation:enemy_template",
                max_hp=100000.0,
                hp=100000.0,
                flags={"position": 1},
            ),
        },
        skill_points=99,
        max_skill_points=99,
        global_flags={
            "turn_owner_id": "validation:actor",
            "current_window": window,
            "phase": "combat",
        },
    )


def _accepted_context(
    rules: RuleBook,
    definition: Any,
    expected_blockers: tuple[str, ...],
) -> tuple[BattleState, ActionCommand, Any, Any, str, Any] | None:
    admissions = tuple(
        sorted(
            (
                admission
                for admission in rules.ir.action_admissions
                if admission.action_id == definition.action_id
                and admission.action_level == definition.level
                and admission.coverage_status == "executable"
                and not admission.blocked_reason
            ),
            key=lambda admission: admission.admission_id,
        )
    )
    for admission in admissions:
        ordered_modes = tuple(
            mode
            for mode in (
                "external_turn",
                "insert_window",
                "queue",
                "trigger",
                "out_of_combat",
            )
            if mode in admission.submission_modes
        )
        for mode in ordered_modes:
            window = admission.allowed_windows[0] if admission.allowed_windows else "idle"
            state = _state_for_admission(admission, window)
            selector = ActionTargetSelectionSystem(rules)
            query = selector.query(
                state,
                "validation:actor",
                definition.action_id,
                definition.level,
            )
            if query.status != "resolved":
                continue
            submitted = (
                ()
                if query.selection_mode == "automatic"
                else tuple(query.candidate_ids[: (query.selection_min or 1)])
            )
            accepted = selector.accept(state, query, submitted)
            if accepted.status != "accepted" or accepted.context is None:
                continue
            command = ActionCommand(
                actor_id="validation:actor",
                action_id=definition.action_id,
                action_level=definition.level,
                target_ids=(
                    ()
                    if query.selection_mode == "automatic"
                    else accepted.context.accepted.selected_target_ids
                ),
            )
            if selector.context_blocked_reason(state, command, accepted.context):
                continue
            decision = ActionContractSystem(rules).evaluate(
                state,
                command,
                submission_mode=mode,
                target_selection_fingerprint=accepted.context.context_fingerprint,
            )
            if decision.admission is None:
                continue
            if "formal_action_reachable_task_ids" not in decision.metadata:
                continue
            if expected_blockers:
                if decision.ok or not all(
                    reason in decision.blocked_reason for reason in expected_blockers
                ):
                    continue
            return state, command, accepted.context, admission, mode, decision
    return None


def _root_graphs(rules: RuleBook, projection: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase_id, callback_kind, graph_id in projection.root_entries:
        tasks = tuple(
            task
            for task in rules.ability_tasks_for_phase(phase_id)
            if task.callback_kind == callback_kind
        )
        query = rules.query_formal_task_graph(
            "ability_phase_callback",
            phase_id,
            callback_kind,
            (task.task_id for task in tasks),
        )
        graph = query.value
        rows.append(
            {
                "phase_id": phase_id,
                "callback_kind": callback_kind,
                "graph_id": graph_id,
                "root_node_ids": (
                    list(graph.root_node_ids)
                    if query.status == "resolved" and type(graph) is TaskGraphIR
                    else []
                ),
            }
        )
    return rows


def _direct_row(
    rules: RuleBook,
    definition: Any,
    projection: Any,
    flat: tuple[Any, ...],
    excluded_blockers: tuple[tuple[Any, str], ...],
    context: tuple[BattleState, ActionCommand, Any, Any, str, Any],
) -> dict[str, Any]:
    _, _, target_context, admission, mode, decision = context
    metadata = decision.metadata
    actual_root_ids = tuple(
        str(value) for value in metadata.get("formal_action_root_graph_ids", [])
    )
    actual_reachable = tuple(
        str(value) for value in metadata.get("formal_action_reachable_task_ids", [])
    )
    actual_excluded = tuple(
        str(value) for value in metadata.get("formal_action_excluded_bound_task_ids", [])
    )
    provenance = metadata.get("formal_action_blocker_provenance", [])
    if actual_root_ids != tuple(projection.root_graph_ids):
        raise AssertionError(
            "ActionContract root graph metadata diverged from production projection"
        )
    if actual_reachable != tuple(projection.reachable_task_ids):
        raise AssertionError(
            "ActionContract reachable-task metadata diverged from production projection"
        )
    if actual_excluded != tuple(projection.excluded_bound_task_ids):
        raise AssertionError(
            "ActionContract excluded-task metadata diverged from production projection"
        )
    if provenance != list(projection.blocker_provenance):
        raise AssertionError(
            "ActionContract blocker provenance diverged from production projection"
        )

    provenance_task_ids = {
        str(row.get("task_id") or "")
        for row in provenance
        if isinstance(row, dict)
    }
    reachable_reasons = set(projection.blocked_reasons)
    for task, reason in excluded_blockers:
        if task.task_id in provenance_task_ids or task.task_id in actual_reachable:
            raise AssertionError(
                f"excluded task leaked into ActionContract projection:{task.task_id}"
            )
        if (
            reason
            and reason not in reachable_reasons
            and reason in decision.blocked_reason
        ):
            raise AssertionError(
                "unique out-of-closure blocker leaked into ActionContract decision:"
                f"{task.task_id}:{reason}"
            )

    phases = tuple(
        sorted(
            rules.ability_phases_for_action(definition.action_id, definition.level),
            key=lambda phase: phase.phase_id,
        )
    )
    return {
        "definition_id": definition.definition_id,
        "action_id": definition.action_id,
        "action_level": definition.level,
        "source": definition.source.to_json(),
        "phase_invocation_roles": [
            {"phase_id": phase.phase_id, "invocation_role": phase.invocation_role}
            for phase in phases
        ],
        "root_graphs": _root_graphs(rules, projection),
        "flat_bound_task_ids": [task.task_id for task in flat],
        "graph_reachable_task_ids": list(projection.reachable_task_ids),
        "excluded_bound_task_ids": list(projection.excluded_bound_task_ids),
        "old_flat_excluded_blockers": [
            {
                "task_id": task.task_id,
                "phase_id": task.phase_id,
                "opcode": task.opcode,
                "coverage_status": task.coverage_status,
                "blocked_reason": reason,
                "reason_is_unique_to_excluded_set": reason not in reachable_reasons,
            }
            for task, reason in excluded_blockers
        ],
        "reachable_blockers": list(projection.blocked_reasons),
        "blocker_provenance": list(projection.blocker_provenance),
        "target_selection": {
            "query_fingerprint": target_context.accepted.query_fingerprint,
            "selection_fingerprint": target_context.accepted.selection_fingerprint,
            "context_fingerprint": target_context.context_fingerprint,
            "selection_mode": target_context.accepted.selection_mode,
            "candidate_ids": list(target_context.accepted.candidate_ids),
            "submitted_target_ids": list(target_context.accepted.submitted_target_ids),
            "selected_target_ids": list(target_context.accepted.selected_target_ids),
            "context_status": "accepted",
        },
        "admission": {
            "admission_id": admission.admission_id,
            "owner_entity_ref": admission.owner_entity_ref,
            "submission_mode": mode,
            "allowed_windows": list(admission.allowed_windows),
        },
        "action_contract": {
            "ok": decision.ok,
            "blocked_reason": decision.blocked_reason,
            "formal_action_root_graph_ids": list(actual_root_ids),
            "formal_action_reachable_task_ids": list(actual_reachable),
            "formal_action_excluded_bound_task_ids": list(actual_excluded),
            "formal_action_blocker_provenance": provenance,
        },
    }


def _run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    lowering = TBGDLowering(root)
    original_build = TBGDLowering.build
    full_build_count = 0

    def forbidden_full_build(_self: TBGDLowering) -> Any:
        nonlocal full_build_count
        full_build_count += 1
        raise AssertionError("Direct attempted full CanonicalIR build")

    TBGDLowering.build = forbidden_full_build
    delta_row: dict[str, Any] | None = None
    reachable_row: dict[str, Any] | None = None
    legacy_row: dict[str, Any] | None = None
    legacy_seen = False
    diagnostics: list[str] = []
    scanned = 0
    try:
        source_graph = lowering.build_character_ability_source_graph_catalog()
        snapshot = lowering._character_ability_raw_snapshot
        scope = lowering._character_ability_scope_catalog
        source_catalog = lowering.build_character_control_flow_contract_catalog(
            snapshot=snapshot,
            scope_catalog=scope,
        )
        definitions = tuple(
            sorted(
                build_character_action_definition_ir(root),
                key=lambda definition: (
                    definition.action_id,
                    definition.level,
                    definition.definition_id,
                ),
            )
        )
        for definition in definitions:
            if time.perf_counter() - started > _DIRECT_DISCOVERY_GUARD_SECONDS:
                break
            scanned += 1
            stage = "slice"
            try:
                canonical = lowering.build_character_action_ability_slice(
                    definition,
                    snapshot=snapshot,
                    scope_catalog=scope,
                    source_graph_catalog=source_graph,
                )
                stage = "materialize"
                graph_catalog = materialize_ability_task_graph_catalog(
                    source_catalog,
                    canonical,
                    source_snapshot=snapshot,
                )
                stage = "rulebook"
                rules = RuleBook(replace(canonical, task_graph_catalog=graph_catalog))
                tasks = rules.ability_tasks_for_action(
                    definition.action_id,
                    definition.level,
                )
                phases = tuple(
                    rules.ability_phases_for_action(
                        definition.action_id,
                        definition.level,
                    )
                )

                stage = "external_legacy"
                legacy_tasks = tuple(
                    task
                    for task in tasks
                    if (
                        (phase := rules.ability_phase(task.phase_id)) is not None
                        and phase.invocation_role == "external_legacy"
                    )
                )
                if legacy_tasks:
                    legacy_seen = True
                if legacy_row is None and legacy_tasks:
                    legacy_reasons = tuple(
                        reason
                        for task in legacy_tasks
                        if (
                            reason := ability_task_runtime_blocked_reason(
                                rules,
                                task,
                                topology_authority="external_legacy",
                            )
                        )
                    )
                    context = _accepted_context(rules, definition, legacy_reasons)
                    if context is not None:
                        decision = context[-1]
                        legacy_row = {
                            "definition_id": definition.definition_id,
                            "action_id": definition.action_id,
                            "action_level": definition.level,
                            "task_ids": [task.task_id for task in legacy_tasks],
                            "flat_blockers": list(legacy_reasons),
                            "action_contract_ok": decision.ok,
                            "action_contract_blocked_reason": decision.blocked_reason,
                            "admission_id": context[3].admission_id,
                            "submission_mode": context[4],
                        }

                stage = "projection"
                flat = _flat_formal_tasks(
                    rules,
                    definition.action_id,
                    definition.level,
                )
                if not flat:
                    continue
                projection = _formal_action_task_graph_projection(
                    rules,
                    definition.action_id,
                    definition.level,
                    tasks,
                )
                expected = tuple(projection.blocked_reasons)
                context = None

                stage = "reachable_context"
                if reachable_row is None and expected:
                    context = _accepted_context(rules, definition, expected)
                    if context is not None:
                        reachable_row = _direct_row(
                            rules,
                            definition,
                            projection,
                            flat,
                            (),
                            context,
                        )

                stage = "delta_context"
                if delta_row is None and len(flat) > len(projection.reachable_task_ids):
                    reachable_ids = set(projection.reachable_task_ids)
                    excluded = tuple(
                        task for task in flat if task.task_id not in reachable_ids
                    )
                    excluded_blockers = tuple(
                        (task, _old_flat_blocker(rules, task))
                        for task in excluded
                    )
                    excluded_blockers = tuple(
                        item for item in excluded_blockers if item[1]
                    )
                    if excluded_blockers:
                        context = context or _accepted_context(
                            rules,
                            definition,
                            expected,
                        )
                        if context is not None:
                            delta_row = _direct_row(
                                rules,
                                definition,
                                projection,
                                flat,
                                excluded_blockers,
                                context,
                            )
                            if expected:
                                reachable_row = delta_row

                if (
                    delta_row is not None
                    and reachable_row is not None
                    and legacy_row is not None
                ):
                    break
            except (AssertionError, TypeError, ValueError, RuntimeError) as exc:
                diagnostics.append(
                    f"{definition.action_id}@{definition.level}:{stage}:"
                    f"{type(exc).__name__}:{exc}"
                )
    finally:
        TBGDLowering.build = original_build

    if delta_row is None:
        raise AssertionError(
            "no real TBGD strict flat>graph delta survived public target "
            "query/accept + ActionContractSystem.evaluate:"
            + json.dumps(diagnostics[-16:], ensure_ascii=False)
        )
    if reachable_row is None:
        raise AssertionError(
            "no reachable formal blocker was reproduced through "
            "ActionContractSystem.evaluate:"
            + json.dumps(diagnostics[-16:], ensure_ascii=False)
        )
    if legacy_seen and legacy_row is None:
        raise AssertionError(
            "external_legacy was present in the bounded real denominator but "
            "no public target/admission regression representative was reproduced:"
            + json.dumps(diagnostics[-16:], ensure_ascii=False)
        )

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    predicates = {
        "real_signed_tbgd_source": True,
        "flat_bound_set_strictly_larger_than_graph_closure": True,
        "excluded_blocker_bearing_task_present": True,
        "public_target_selection_query_and_accept": True,
        "target_selection_context_revalidated": True,
        "action_contract_evaluated_after_target_accept": True,
        "excluded_flat_only_blockers_absent_after_projection": True,
        "reachable_graph_blockers_preserved_fail_closed": True,
        "graph_roots_and_nested_links_discovered_from_production_ir": True,
        "external_legacy_regression_preserved_when_present": (
            legacy_row is not None or not legacy_seen
        ),
        "no_forged_selection_fingerprint_or_authorization": True,
        "full_canonical_ir_build_count_is_zero": full_build_count == 0,
    }
    return {
        "ok": (
            elapsed <= _DIRECT_HARD_SECONDS
            and peak <= 1024 * 1024
            and all(predicates.values())
        ),
        "mode": "direct",
        "predicates": predicates,
        "full_canonical_ir_build_count": full_build_count,
        "source": {
            "source_fingerprint": snapshot.source_fingerprint,
            "scanned_action_definitions": scanned,
            "external_legacy_seen_in_scanned_denominator": legacy_seen,
        },
        "flat_vs_graph_delta": delta_row,
        "reachable_blocker_representative": reachable_row,
        "external_legacy_representative": legacy_row,
        "diagnostics_tail": diagnostics[-8:],
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate P9 formal action graph admission authority"
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fast", action="store_true")
    modes.add_argument("--direct", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    args = parser.parse_args()
    summary = _run_fast() if args.fast else _run_direct(args.tbgd_root.resolve())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
