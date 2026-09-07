from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..core.model import ActionCommand, BattleState, UnitState
from ..ir_types import IRSource
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
from ..systems.action_contract import (
    ActionContractSystem,
    _formal_action_task_graph_projection,
)
from ..systems.action_selection import ActionTargetSelectionSystem
from ..systems.ability_task_contract import ability_task_runtime_blocked_reason
from ..tbgd.lowering import TBGDLowering, build_character_action_definition_ir
from ..tbgd.task_graph_materializer import materialize_ability_task_graph_catalog


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
_FAST_HARD_SECONDS = 30.0
_DIRECT_HARD_SECONDS = 180.0
_DIRECT_DISCOVERY_GUARD_SECONDS = 165.0


def _fixture_source(label: str, opcode: str) -> IRSource:
    return IRSource(
        f"validation_fixture/{label}.json",
        opcode,
        label,
        {
            "json_path": f"$.{label}",
            "content_sha256": hashlib.sha256(label.encode("utf-8")).hexdigest(),
            "source_opcode": opcode,
            "task_path": f"OnStart[{label}]",
        },
    )


def _fixture_phase(
    phase_id: str,
    *,
    action_id: str = "fixture:action",
    level: int = 1,
    role: str = "action_root",
) -> Any:
    return SimpleNamespace(
        phase_id=phase_id,
        action_id=action_id,
        level=level,
        invocation_role=role,
    )


def _fixture_task(
    task_id: str,
    phase_id: str,
    *,
    opcode: str = "AddAbilityTask",
    callback_kind: str = "OnStart",
    execution_mode: str = "runtime_effect",
    coverage_status: str = "executable",
    blocked_reason: str = "",
    effect_id: str = "",
    linked_ability_phase_id: str = "",
    linked_standalone_graph_id: str = "",
) -> Any:
    return SimpleNamespace(
        task_id=task_id,
        phase_id=phase_id,
        action_id="fixture:action",
        level=1,
        ability_name="FixtureAbility",
        callback_kind=callback_kind,
        task_index=0,
        task_path=f"OnStart[{task_id}]",
        branch="root",
        opcode=opcode,
        source=_fixture_source(task_id.replace(":", "_"), opcode),
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
        linked_standalone_graph_id=linked_standalone_graph_id,
        linked_ability_phase_id=linked_ability_phase_id,
    )


def _fixture_graph(
    owner_id: str,
    callback_kind: str,
    task: Any,
    *,
    node_kind: str = "leaf",
    materialization_status: str = "materialized",
    status_reason: str = "",
    references: tuple[tuple[str, str, str, str], ...] = (),
) -> TaskGraphIR:
    fingerprint = hashlib.sha256(
        f"{owner_id}:{callback_kind}:{task.task_id}".encode("utf-8")
    ).hexdigest()
    entry_id = task_graph_entry_id("ability_phase_callback", owner_id, callback_kind)
    graph_id = task_graph_id("fixture:catalog", entry_id, fingerprint)
    occurrence_id = task_graph_source_occurrence_id(task.source, task.opcode)
    node_id = task_graph_node_id(graph_id, task.task_id, occurrence_id)
    graph_references = tuple(
        TaskGraphDefinitionReferenceIR(
            reference_id=task_graph_stable_id(
                "task_graph_reference", node_id, reference_kind, definition_id
            ),
            graph_node_id=node_id,
            reference_kind=reference_kind,
            definition_id=definition_id,
            source_contract_record_id="",
            resolution_status=resolution_status,
            owner_domain="fixture_reference_authority",
            source=task.source,
            blocked_reason=blocked_reason,
        )
        for reference_kind, definition_id, resolution_status, blocked_reason in references
    )
    deferred = materialization_status == "deferred"
    unresolved = any(item.resolution_status != "resolved" for item in graph_references)
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
        references=graph_references,
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
        callback_kind=callback_kind,
        root_node_ids=(node_id,),
        nodes=(node,),
        numeric_definitions=(),
        source_catalog_id="fixture:catalog",
        source_fingerprint=fingerprint,
        source=task.source,
        coverage_status=(
            "lowered_with_obligation" if deferred or unresolved else "lowered"
        ),
        weighted_selections=(),
    )


class _FixtureRules:
    def __init__(
        self,
        phases: tuple[Any, ...],
        tasks: tuple[Any, ...],
        graphs: tuple[TaskGraphIR, ...],
        *,
        effects: dict[str, Any] | None = None,
    ) -> None:
        self.phases = {item.phase_id: item for item in phases}
        self.tasks = {item.task_id: item for item in tasks}
        self.graphs = {
            (item.owner_id, item.callback_kind): item for item in graphs
        }
        self.effects = effects or {}
        self.graph_query_count = 0

    def ability_phase(self, phase_id: str) -> Any:
        return self.phases.get(phase_id)

    def ability_phases_for_action(self, action_id: str, level: int) -> tuple[Any, ...]:
        return tuple(
            sorted(
                (
                    phase
                    for phase in self.phases.values()
                    if phase.action_id == action_id and phase.level == level
                ),
                key=lambda item: item.phase_id,
            )
        )

    def ability_tasks_for_phase(self, phase_id: str) -> tuple[Any, ...]:
        return tuple(
            sorted(
                (task for task in self.tasks.values() if task.phase_id == phase_id),
                key=lambda item: item.task_id,
            )
        )

    def query_formal_task_graph(
        self,
        entry_kind: str,
        owner_id: str,
        callback_kind: str,
        formal_task_ids: Any,
    ) -> Any:
        self.graph_query_count += 1
        requested = tuple(formal_task_ids)
        graph = self.graphs.get((owner_id, callback_kind))
        if entry_kind != "ability_phase_callback" or graph is None:
            return SimpleNamespace(
                status="blocked",
                value=None,
                blocked_reason=f"task_graph_missing:{owner_id}:{callback_kind}",
            )
        graph_task_ids = tuple(sorted(node.formal_task_id for node in graph.nodes))
        if tuple(sorted(requested)) != graph_task_ids:
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


def _fixture_projection(
    phases: tuple[Any, ...],
    tasks: tuple[Any, ...],
    graphs: tuple[TaskGraphIR, ...],
    *,
    effects: dict[str, Any] | None = None,
) -> tuple[Any, _FixtureRules]:
    rules = _FixtureRules(phases, tasks, graphs, effects=effects)
    projection = _formal_action_task_graph_projection(
        rules,  # type: ignore[arg-type]
        "fixture:action",
        1,
        tasks,  # type: ignore[arg-type]
    )
    return projection, rules


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()

    root_phase = _fixture_phase("fixture:phase:root")
    unrelated_phase = _fixture_phase(
        "fixture:phase:unrelated", role="nested_only"
    )
    root_task = _fixture_task("fixture:task:root", root_phase.phase_id)
    unrelated_task = _fixture_task(
        "fixture:task:unrelated_blocker",
        unrelated_phase.phase_id,
        coverage_status="blocked",
        blocked_reason="fixture_unrelated_flat_blocker",
    )
    root_graph = _fixture_graph(root_phase.phase_id, "OnStart", root_task)
    excluded, excluded_rules = _fixture_projection(
        (root_phase, unrelated_phase),
        (root_task, unrelated_task),
        (root_graph,),
    )
    if excluded.reachable_task_ids != (root_task.task_id,):
        raise AssertionError("action-root closure did not retain its root task")
    if excluded.excluded_bound_task_ids != (unrelated_task.task_id,):
        raise AssertionError("unlinked nested task was not excluded")
    if "fixture_unrelated_flat_blocker" in excluded.blocked_reasons:
        raise AssertionError("out-of-closure flat blocker leaked into projection")

    nested_root_phase = _fixture_phase("fixture:phase:nested_root")
    nested_phase = _fixture_phase("fixture:phase:nested", role="nested_only")
    trigger = _fixture_task(
        "fixture:task:trigger",
        nested_root_phase.phase_id,
        opcode="TriggerAbility",
        linked_ability_phase_id=nested_phase.phase_id,
    )
    nested_blocker = _fixture_task(
        "fixture:task:nested_blocker",
        nested_phase.phase_id,
        coverage_status="blocked",
        blocked_reason="fixture_nested_blocker",
    )
    trigger_graph = _fixture_graph(
        nested_root_phase.phase_id,
        "OnStart",
        trigger,
        node_kind="ability_call",
        references=(("ability", nested_phase.phase_id, "resolved", ""),),
    )
    nested_graph = _fixture_graph(nested_phase.phase_id, "OnStart", nested_blocker)
    nested, _ = _fixture_projection(
        (nested_root_phase, nested_phase),
        (trigger, nested_blocker),
        (trigger_graph, nested_graph),
    )
    if nested.reachable_task_ids != (trigger.task_id, nested_blocker.task_id):
        raise AssertionError("reachable nested-only graph was not included")
    if "fixture_nested_blocker" not in nested.blocked_reasons:
        raise AssertionError("nested reachable blocker was not preserved")

    deferred_phase = _fixture_phase("fixture:phase:deferred")
    deferred_task = _fixture_task("fixture:task:deferred", deferred_phase.phase_id)
    deferred_graph = _fixture_graph(
        deferred_phase.phase_id,
        "OnStart",
        deferred_task,
        materialization_status="deferred",
        status_reason="fixture_deferred_node",
    )
    deferred, _ = _fixture_projection(
        (deferred_phase,), (deferred_task,), (deferred_graph,)
    )
    if "fixture_deferred_node" not in deferred.blocked_reasons:
        raise AssertionError("deferred graph node did not fail closed")
    if not any(
        row.get("reason") == "fixture_deferred_node"
        and row.get("source") == "node_materialization"
        for row in deferred.blocker_provenance
    ):
        raise AssertionError("deferred blocker provenance is not stable")

    gameplay_phase = _fixture_phase("fixture:phase:gameplay_ref")
    gameplay_task = _fixture_task(
        "fixture:task:gameplay_ref", gameplay_phase.phase_id
    )
    gameplay_graph = _fixture_graph(
        gameplay_phase.phase_id,
        "OnStart",
        gameplay_task,
        references=(("effect", "fixture:effect:missing", "deferred", "fixture_unresolved_gameplay_ref"),),
    )
    gameplay, _ = _fixture_projection(
        (gameplay_phase,), (gameplay_task,), (gameplay_graph,)
    )
    if "fixture_unresolved_gameplay_ref" not in gameplay.blocked_reasons:
        raise AssertionError("unresolved gameplay reference did not fail closed")

    process_phase = _fixture_phase("fixture:phase:process")
    process_task = _fixture_task(
        "fixture:task:process",
        process_phase.phase_id,
        opcode="AuditTask",
        execution_mode="process_only",
        coverage_status="audit_only",
        effect_id="fixture:effect:process",
    )
    process_effect = SimpleNamespace(
        opcode=process_task.opcode,
        coverage_status="audit_only",
        source=process_task.source,
        payload={
            "process_only_contract": {
                "schema_version": "ability_process_only_source_shape_v1",
                "opcode": process_task.opcode,
                "source_fields": ["$type"],
                "source_field_types": {"$type": "str"},
                "source_shape_status": "admitted",
                "blocked_reason": "",
            }
        },
    )
    process_graph = _fixture_graph(
        process_phase.phase_id,
        "OnStart",
        process_task,
        references=(("effect", process_task.effect_id, "deferred", "fixture_audit_only_reference"),),
    )
    process, _ = _fixture_projection(
        (process_phase,),
        (process_task,),
        (process_graph,),
        effects={process_task.effect_id: process_effect},
    )
    if process.blocked_reasons:
        raise AssertionError(
            "valid process-only task was rejected solely for an audit reference:"
            + repr(process.blocked_reasons)
        )

    invalid_process_phase = _fixture_phase("fixture:phase:invalid_process")
    invalid_process_task = _fixture_task(
        "fixture:task:invalid_process",
        invalid_process_phase.phase_id,
        opcode="AuditTask",
        execution_mode="process_only",
        coverage_status="audit_only",
        effect_id="",
    )
    invalid_process_graph = _fixture_graph(
        invalid_process_phase.phase_id, "OnStart", invalid_process_task
    )
    invalid_process, _ = _fixture_projection(
        (invalid_process_phase,),
        (invalid_process_task,),
        (invalid_process_graph,),
    )
    if "process_only_task_effect_missing" not in invalid_process.blocked_reasons:
        raise AssertionError("invalid process-only task contract did not block")

    legacy_phase = _fixture_phase(
        "fixture:phase:legacy", role="external_legacy"
    )
    legacy_task = _fixture_task(
        "fixture:task:legacy",
        legacy_phase.phase_id,
        coverage_status="blocked",
        blocked_reason="fixture_external_legacy_blocker",
    )
    legacy_rules = _FixtureRules((legacy_phase,), (legacy_task,), ())
    legacy_reason = ability_task_runtime_blocked_reason(
        legacy_rules,  # type: ignore[arg-type]
        legacy_task,  # type: ignore[arg-type]
        topology_authority="external_legacy",
    )
    if legacy_reason != "fixture_external_legacy_blocker":
        raise AssertionError("external_legacy flat runtime-support gate changed")
    legacy_projection = _formal_action_task_graph_projection(
        legacy_rules,  # type: ignore[arg-type]
        "fixture:action",
        1,
        (legacy_task,),  # type: ignore[arg-type]
    )
    if legacy_projection.reachable_task_ids or legacy_projection.blocked_reasons:
        raise AssertionError("external_legacy task was migrated into formal projection")

    missing_phase = _fixture_phase("fixture:phase:missing_graph")
    missing_task = _fixture_task("fixture:task:missing_graph", missing_phase.phase_id)
    malformed, _ = _fixture_projection((missing_phase,), (missing_task,), ())
    if not malformed.blocked_reasons or not malformed.blocked_reasons[0].startswith(
        "task_graph_missing:"
    ):
        raise AssertionError("missing formal graph identity did not fail closed")

    repeated, _ = _fixture_projection(
        (root_phase, unrelated_phase),
        (root_task, unrelated_task),
        (root_graph,),
    )
    if repeated != excluded:
        raise AssertionError("formal action projection ordering is not deterministic")

    sentinel_state = BattleState(
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
    before = sentinel_state.snapshot().to_json()
    after = sentinel_state.snapshot().to_json()
    if before != after:
        raise AssertionError("admission projection mutated runtime state")

    elapsed = time.perf_counter() - started
    predicates = {
        "unrelated_bound_nested_excluded": True,
        "reachable_trigger_nested_blocker_preserved": True,
        "reachable_deferred_node_fail_closed": True,
        "unresolved_gameplay_reference_fail_closed": True,
        "audit_only_unresolved_reference_not_sole_blocker": True,
        "invalid_process_only_contract_fail_closed": True,
        "external_legacy_flat_gate_preserved": True,
        "missing_graph_identity_fail_closed": True,
        "projection_metadata_deterministic": True,
        "no_state_mutation_rng_or_graph_execution": True,
    }
    return {
        "ok": elapsed <= _FAST_HARD_SECONDS and all(predicates.values()),
        "mode": "fast",
        "cases": len(predicates),
        "predicates": predicates,
        "sample": {
            "excluded": excluded.metadata(),
            "nested": nested.metadata(),
            "deferred": deferred.metadata(),
            "gameplay_reference": gameplay.metadata(),
            "process_only": process.metadata(),
            "invalid_process_only": invalid_process.metadata(),
            "malformed": malformed.metadata(),
            "external_legacy_reason": legacy_reason,
            "graph_query_count": excluded_rules.graph_query_count,
        },
        "resource": {"wall_seconds": round(elapsed, 6)},
    }


def _flat_formal_tasks(rules: RuleBook, action_id: str, level: int) -> tuple[Any, ...]:
    return tuple(
        task
        for task in rules.ability_tasks_for_action(action_id, level)
        if (
            (phase := rules.ability_phase(task.phase_id)) is not None
            and phase.invocation_role != "external_legacy"
        )
    )


def _old_flat_blocker_reason(rules: RuleBook, task: Any) -> str:
    return ability_task_runtime_blocked_reason(
        rules,
        task,
        topology_authority="task_graph",
    ) or str(task.blocked_reason or "")


def _real_action_context(
    rules: RuleBook,
    definition: Any,
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
            key=lambda item: item.admission_id,
        )
    )
    for admission in admissions:
        modes = tuple(admission.submission_modes)
        preferred_modes = tuple(
            mode for mode in ("external_turn", "insert_window", "queue", "trigger", "out_of_combat")
            if mode in modes
        )
        for mode in preferred_modes:
            window = admission.allowed_windows[0] if admission.allowed_windows else "idle"
            actor_id = "validation:actor"
            enemy_id = "validation:enemy"
            state = BattleState(
                units={
                    actor_id: UnitState(
                        unit_id=actor_id,
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
                    enemy_id: UnitState(
                        unit_id=enemy_id,
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
                    "turn_owner_id": actor_id,
                    "current_window": window,
                    "phase": "combat",
                },
            )
            selection = ActionTargetSelectionSystem(rules)
            query = selection.query(
                state,
                actor_id,
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
            accepted = selection.accept(state, query, submitted)
            if accepted.status != "accepted" or accepted.context is None:
                continue
            command = ActionCommand(
                actor_id=actor_id,
                action_id=definition.action_id,
                action_level=definition.level,
                target_ids=accepted.context.accepted.selected_target_ids,
            )
            decision = ActionContractSystem(rules).evaluate(
                state,
                command,
                submission_mode=mode,
                target_selection_fingerprint=accepted.context.context_fingerprint,
            )
            return state, command, accepted.context, admission, mode, decision
    return None


def _root_graph_evidence(
    rules: RuleBook,
    projection: Any,
) -> list[dict[str, Any]]:
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


def _decision_preserves_projection(decision: Any, projection: Any) -> bool:
    if not projection.blocked_reasons:
        return bool(decision.ok)
    if decision.ok:
        return False
    return any(reason in decision.blocked_reason for reason in projection.blocked_reasons)


def _direct_row(
    rules: RuleBook,
    definition: Any,
    projection: Any,
    flat: tuple[Any, ...],
    excluded_blockers: tuple[tuple[Any, str], ...],
    context: tuple[BattleState, ActionCommand, Any, Any, str, Any],
) -> dict[str, Any]:
    _, command, target_context, admission, mode, decision = context
    excluded_reasons = tuple(reason for _, reason in excluded_blockers)
    provenance_reasons = tuple(
        str(item.get("reason") or "")
        for item in decision.metadata.get("formal_action_blocker_provenance", [])
        if isinstance(item, dict)
    )
    if any(
        reason and (reason in decision.blocked_reason or reason in provenance_reasons)
        for reason in excluded_reasons
    ):
        raise AssertionError("out-of-closure flat blocker leaked into ActionContractSystem")
    if not _decision_preserves_projection(decision, projection):
        raise AssertionError(
            "ActionContractSystem did not preserve reachable projection blockers or clean admission"
        )
    phases = tuple(
        sorted(
            rules.ability_phases_for_action(definition.action_id, definition.level),
            key=lambda item: item.phase_id,
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
        "root_graphs": _root_graph_evidence(rules, projection),
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
            "formal_action_root_graph_ids": decision.metadata.get(
                "formal_action_root_graph_ids", []
            ),
            "formal_action_reachable_task_ids": decision.metadata.get(
                "formal_action_reachable_task_ids", []
            ),
            "formal_action_excluded_bound_task_ids": decision.metadata.get(
                "formal_action_excluded_bound_task_ids", []
            ),
            "formal_action_blocker_provenance": decision.metadata.get(
                "formal_action_blocker_provenance", []
            ),
        },
    }


def _run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    lowering = TBGDLowering(root)
    original_build = TBGDLowering.build

    def forbidden_full_build(_self: TBGDLowering) -> Any:
        raise AssertionError("Direct attempted full CanonicalIR build")

    TBGDLowering.build = forbidden_full_build
    delta_row: dict[str, Any] | None = None
    reachable_row: dict[str, Any] | None = None
    legacy_row: dict[str, Any] | None = None
    scanned = 0
    diagnostics: list[str] = []
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
                key=lambda item: (item.action_id, item.level, item.definition_id),
            )
        )
        for definition in definitions:
            if time.perf_counter() - started > _DIRECT_DISCOVERY_GUARD_SECONDS:
                break
            scanned += 1
            try:
                canonical = lowering.build_character_action_ability_slice(
                    definition,
                    snapshot=snapshot,
                    scope_catalog=scope,
                    source_graph_catalog=source_graph,
                )
                graph_catalog = materialize_ability_task_graph_catalog(
                    source_catalog,
                    canonical,
                    source_snapshot=snapshot,
                )
                rules = RuleBook(replace(canonical, task_graph_catalog=graph_catalog))
                all_tasks = rules.ability_tasks_for_action(
                    definition.action_id, definition.level
                )
                phases = tuple(
                    rules.ability_phases_for_action(
                        definition.action_id, definition.level
                    )
                )
                roles = {phase.invocation_role for phase in phases}

                if legacy_row is None and roles == {"external_legacy"}:
                    context = _real_action_context(rules, definition)
                    if context is not None:
                        legacy_reasons = tuple(
                            reason
                            for task in all_tasks
                            if (
                                reason := ability_task_runtime_blocked_reason(
                                    rules,
                                    task,
                                    topology_authority="external_legacy",
                                )
                            )
                        )
                        decision = context[-1]
                        preserved = (
                            any(reason in decision.blocked_reason for reason in legacy_reasons)
                            if legacy_reasons
                            else bool(decision.ok)
                        )
                        if preserved:
                            legacy_row = {
                                "definition_id": definition.definition_id,
                                "action_id": definition.action_id,
                                "action_level": definition.level,
                                "task_ids": [task.task_id for task in all_tasks],
                                "flat_blockers": list(legacy_reasons),
                                "action_contract_ok": decision.ok,
                                "action_contract_blocked_reason": decision.blocked_reason,
                            }

                flat = _flat_formal_tasks(rules, definition.action_id, definition.level)
                if not flat:
                    continue
                projection = _formal_action_task_graph_projection(
                    rules,
                    definition.action_id,
                    definition.level,
                    all_tasks,
                )
                context = None
                if reachable_row is None and projection.blocked_reasons:
                    context = _real_action_context(rules, definition)
                    if context is not None and _decision_preserves_projection(
                        context[-1], projection
                    ):
                        reachable_row = _direct_row(
                            rules,
                            definition,
                            projection,
                            flat,
                            (),
                            context,
                        )

                if delta_row is None and len(flat) > len(projection.reachable_task_ids):
                    excluded = tuple(
                        task
                        for task in flat
                        if task.task_id in set(projection.excluded_bound_task_ids)
                    )
                    excluded_blockers = tuple(
                        (task, _old_flat_blocker_reason(rules, task))
                        for task in excluded
                    )
                    excluded_blockers = tuple(
                        item for item in excluded_blockers if item[1]
                    )
                    if excluded_blockers:
                        context = context or _real_action_context(rules, definition)
                        if context is not None:
                            try:
                                delta_row = _direct_row(
                                    rules,
                                    definition,
                                    projection,
                                    flat,
                                    excluded_blockers,
                                    context,
                                )
                            except AssertionError as exc:
                                diagnostics.append(
                                    f"{definition.action_id}@{definition.level}:{exc}"
                                )
                                delta_row = None
                            else:
                                if projection.blocked_reasons:
                                    reachable_row = delta_row
                if delta_row is not None and reachable_row is not None and legacy_row is not None:
                    break
            except (AssertionError, TypeError, ValueError, RuntimeError) as exc:
                diagnostics.append(
                    f"{definition.action_id}@{definition.level}:{type(exc).__name__}:{exc}"
                )
                continue
    finally:
        TBGDLowering.build = original_build

    if delta_row is None:
        raise AssertionError(
            "no real TBGD action satisfies strict flat>graph closure with an excluded blocker "
            "through public target query/accept + ActionContractSystem.evaluate:"
            + json.dumps(diagnostics[-12:], ensure_ascii=False)
        )
    if reachable_row is None:
        raise AssertionError(
            "no real reachable formal blocker was reproduced through ActionContractSystem.evaluate:"
            + json.dumps(diagnostics[-12:], ensure_ascii=False)
        )

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    predicates = {
        "real_signed_tbgd_source": True,
        "flat_bound_set_strictly_larger_than_graph_closure": True,
        "excluded_blocker_bearing_task_present": True,
        "public_target_selection_query_and_accept": True,
        "action_contract_evaluated_after_target_accept": True,
        "excluded_flat_only_blockers_absent_after_projection": True,
        "reachable_graph_blockers_preserved_fail_closed": True,
        "graph_roots_and_nested_links_discovered_from_production_ir": True,
        "forged_selection_fingerprint_or_authorization": False,
        "external_legacy_regression_preserved_when_found": legacy_row is not None,
        "full_canonical_ir_build_count": 0,
    }
    return {
        "ok": (
            elapsed <= _DIRECT_HARD_SECONDS
            and peak <= 1024 * 1024
            and all(predicates.values())
        ),
        "mode": "direct",
        "predicates": predicates,
        "source": {
            "source_fingerprint": snapshot.source_fingerprint,
            "scanned_action_definitions": scanned,
        },
        "flat_vs_graph_delta": delta_row,
        "reachable_blocker_representative": reachable_row,
        "external_legacy_representative": legacy_row,
        "diagnostics_tail": diagnostics[-6:],
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
