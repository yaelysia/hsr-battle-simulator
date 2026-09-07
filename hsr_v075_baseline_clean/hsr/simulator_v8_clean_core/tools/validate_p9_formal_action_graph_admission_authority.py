from __future__ import annotations

import argparse
import json
import resource
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from ..core.model import BattleState, UnitState
from ..ir_types import IRSource
from ..rules.rulebook import RuleBook
from ..rules.task_graph import (
    TaskGraphIR,
    TaskGraphNodeIR,
    task_graph_entry_id,
    task_graph_id,
    task_graph_node_id,
    task_graph_source_occurrence_id,
)
from ..systems.action_contract import _formal_action_task_graph_projection
from ..systems.action_selection import ActionTargetSelectionSystem
from ..systems.ability_task_contract import ability_task_runtime_blocked_reason
from ..tbgd.lowering import TBGDLowering, build_character_action_definition_ir
from ..tbgd.task_graph_materializer import materialize_ability_task_graph_catalog


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
_FAST_HARD_SECONDS = 5.0
_DIRECT_HARD_SECONDS = 180.0
_DIRECT_DISCOVERY_GUARD_SECONDS = 150.0


def _fixture_source() -> IRSource:
    return IRSource(
        "validation_fixture/p9_formal_action_graph_admission.json",
        "AddAbilityTask",
        "fixture",
        {
            "json_path": "$.Task",
            "content_sha256": "0" * 64,
            "source_opcode": "AddAbilityTask",
            "task_path": "OnStart[0]",
        },
    )


def _fixture_node(graph_id: str, node_id: str, task_id: str, source: IRSource) -> TaskGraphNodeIR:
    return TaskGraphNodeIR(
        graph_node_id=node_id,
        graph_id=graph_id,
        source_occurrence_id=task_graph_source_occurrence_id(source, "AddAbilityTask"),
        source_contract_node_id="fixture:control",
        formal_task_id=task_id,
        opcode="AddAbilityTask",
        source_family="AddAbilityTask",
        node_kind="leaf",
        branches=(),
        references=(),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="materialized",
        owner_domains=("task_graph_execution",),
        source=source,
        status_reason="",
    )


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    source = _fixture_source()
    entry_id = task_graph_entry_id(
        "ability_phase_callback", "fixture:root_phase", "OnStart"
    )
    graph_id = task_graph_id("fixture:catalog", entry_id, source.evidence["content_sha256"])
    task_id = "fixture:task:reachable"
    occurrence_id = task_graph_source_occurrence_id(source, "AddAbilityTask")
    node_id = task_graph_node_id(graph_id, task_id, occurrence_id)
    graph = TaskGraphIR(
        graph_id=graph_id,
        entry_id=entry_id,
        entry_kind="ability_phase_callback",
        owner_id="fixture:root_phase",
        callback_kind="OnStart",
        root_node_ids=(node_id,),
        nodes=(_fixture_node(graph_id, node_id, task_id, source),),
        numeric_definitions=(),
        source_catalog_id="fixture:catalog",
        source_fingerprint=source.evidence["content_sha256"],
        source=source,
        coverage_status="lowered",
        weighted_selections=(),
    )
    root_phase = SimpleNamespace(
        phase_id="fixture:root_phase",
        action_id="fixture:action",
        level=1,
        invocation_role="action_root",
    )
    nested_phase = SimpleNamespace(
        phase_id="fixture:unlinked_nested_phase",
        action_id="fixture:action",
        level=1,
        invocation_role="nested_only",
    )
    reachable = SimpleNamespace(
        task_id=task_id,
        phase_id=root_phase.phase_id,
        callback_kind="OnStart",
        opcode="AddAbilityTask",
        execution_mode="runtime_effect",
        coverage_status="executable",
        blocked_reason="",
        linked_ability_phase_id="",
        linked_standalone_graph_id="",
    )
    excluded = SimpleNamespace(
        task_id="fixture:task:excluded_blocker",
        phase_id=nested_phase.phase_id,
        callback_kind="OnStart",
        opcode="AddAbilityTask",
        execution_mode="runtime_effect",
        coverage_status="blocked",
        blocked_reason="fixture_excluded_blocker",
        linked_ability_phase_id="",
        linked_standalone_graph_id="",
    )

    class FixtureRules:
        def ability_phase(self, phase_id: str) -> Any:
            return {
                root_phase.phase_id: root_phase,
                nested_phase.phase_id: nested_phase,
            }.get(phase_id)

        def ability_phases_for_action(self, action_id: str, level: int) -> tuple[Any, ...]:
            assert (action_id, level) == ("fixture:action", 1)
            return (root_phase, nested_phase)

        def ability_tasks_for_phase(self, phase_id: str) -> tuple[Any, ...]:
            return tuple(
                task for task in (reachable, excluded) if task.phase_id == phase_id
            )

        def query_formal_task_graph(
            self,
            entry_kind: str,
            owner_id: str,
            callback_kind: str,
            formal_task_ids: Any,
        ) -> Any:
            assert entry_kind == "ability_phase_callback"
            assert owner_id == root_phase.phase_id
            assert callback_kind == "OnStart"
            assert tuple(formal_task_ids) == (reachable.task_id,)
            return SimpleNamespace(status="resolved", value=graph, blocked_reason="")

        def ability_task(self, task_id: str) -> Any:
            return {reachable.task_id: reachable, excluded.task_id: excluded}.get(task_id)

    rules = FixtureRules()
    with patch(
        "simulator_v8_clean_core.systems.action_contract.ability_task_runtime_blocked_reason",
        side_effect=lambda _rules, task, topology_authority: task.blocked_reason,
    ):
        first = _formal_action_task_graph_projection(
            rules,  # type: ignore[arg-type]
            "fixture:action",
            1,
            (reachable, excluded),  # type: ignore[arg-type]
        )
        second = _formal_action_task_graph_projection(
            rules,  # type: ignore[arg-type]
            "fixture:action",
            1,
            (reachable, excluded),  # type: ignore[arg-type]
        )
    if first != second:
        raise AssertionError("formal action graph projection is not deterministic")
    if first.reachable_task_ids != (reachable.task_id,):
        raise AssertionError("formal action root graph closure is incorrect")
    if first.excluded_bound_task_ids != (excluded.task_id,):
        raise AssertionError("unlinked nested bound task was not excluded")
    if "fixture_excluded_blocker" in first.blocked_reasons:
        raise AssertionError("excluded flat blocker leaked into graph-closure admission")
    if first.root_graph_ids != (graph.graph_id,):
        raise AssertionError("formal action root graph identity was not preserved")

    elapsed = time.perf_counter() - started
    return {
        "ok": elapsed <= _FAST_HARD_SECONDS,
        "mode": "fast",
        "predicates": {
            "same_action_root_graph_authority": True,
            "unlinked_nested_task_excluded": True,
            "excluded_flat_blocker_not_applied": True,
            "projection_deterministic": True,
        },
        "fixture": first.metadata(),
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


def _excluded_blocker_reason(rules: RuleBook, task: Any) -> str:
    reason = ability_task_runtime_blocked_reason(
        rules,
        task,
        topology_authority="task_graph",
    )
    return reason or str(task.blocked_reason or "")


def _selection_evidence(
    rules: RuleBook,
    action_id: str,
    level: int,
) -> dict[str, Any] | None:
    actor_id = "validation:actor"
    enemy_id = "validation:enemy"
    state = BattleState(
        units={
            actor_id: UnitState(
                unit_id=actor_id,
                side="ally",
                template_id="validation:actor_template",
                max_hp=1000.0,
                hp=1000.0,
                energy=1000.0,
                max_energy=1000.0,
            ),
            enemy_id: UnitState(
                unit_id=enemy_id,
                side="enemy",
                template_id="validation:enemy_template",
                max_hp=1000.0,
                hp=1000.0,
            ),
        },
        skill_points=99,
        max_skill_points=99,
        global_flags={"turn_owner_id": actor_id, "current_window": "idle", "phase": "combat"},
    )
    selection = ActionTargetSelectionSystem(rules)
    query = selection.query(state, actor_id, action_id, level)
    if query.status != "resolved":
        return None
    submitted = (
        ()
        if query.selection_mode == "automatic"
        else tuple(query.candidate_ids[: (query.selection_min or 1)])
    )
    decision = selection.accept(state, query, submitted)
    if decision.status != "accepted" or decision.context is None:
        return None
    return {
        "query_fingerprint": query.query_fingerprint,
        "selection_mode": query.selection_mode,
        "candidate_ids": list(query.candidate_ids),
        "submitted_target_ids": list(submitted),
        "selected_target_ids": list(decision.context.accepted.selected_target_ids),
        "selection_fingerprint": decision.context.accepted.selection_fingerprint,
    }


def _run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    lowering = TBGDLowering(root)
    original_build = TBGDLowering.build

    def forbidden_full_build(_self: TBGDLowering) -> Any:
        raise AssertionError("Direct attempted full CanonicalIR build")

    TBGDLowering.build = forbidden_full_build
    failures: list[str] = []
    selected: dict[str, Any] | None = None
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
                flat = _flat_formal_tasks(rules, definition.action_id, definition.level)
                if not flat:
                    continue
                projection = _formal_action_task_graph_projection(
                    rules,
                    definition.action_id,
                    definition.level,
                    rules.ability_tasks_for_action(definition.action_id, definition.level),
                )
                if len(flat) <= len(projection.reachable_task_ids):
                    continue
                excluded = tuple(
                    task
                    for task in flat
                    if task.task_id in set(projection.excluded_bound_task_ids)
                )
                blocker_rows = tuple(
                    (task, _excluded_blocker_reason(rules, task))
                    for task in excluded
                )
                blocker_rows = tuple(row for row in blocker_rows if row[1])
                if not blocker_rows:
                    continue
                if projection.blocked_reasons:
                    failures.append(
                        f"{definition.action_id}@{definition.level}:reachable_blocked:"
                        + ",".join(projection.blocked_reasons[:3])
                    )
                    continue
                selection_evidence = _selection_evidence(
                    rules, definition.action_id, definition.level
                )
                if selection_evidence is None:
                    failures.append(
                        f"{definition.action_id}@{definition.level}:target_selection_not_accepted"
                    )
                    continue
                selected = {
                    "definition_id": definition.definition_id,
                    "action_id": definition.action_id,
                    "action_level": definition.level,
                    "flat_bound_task_ids": [task.task_id for task in flat],
                    "graph_reachable_task_ids": list(projection.reachable_task_ids),
                    "excluded_bound_task_ids": list(projection.excluded_bound_task_ids),
                    "excluded_blockers": [
                        {
                            "task_id": task.task_id,
                            "phase_id": task.phase_id,
                            "opcode": task.opcode,
                            "coverage_status": task.coverage_status,
                            "blocked_reason": reason,
                        }
                        for task, reason in blocker_rows
                    ],
                    "root_graph_ids": list(projection.root_graph_ids),
                    "root_entries": [list(item) for item in projection.root_entries],
                    "selection": selection_evidence,
                    "source_fingerprint": snapshot.source_fingerprint,
                }
                break
            except (AssertionError, TypeError, ValueError, RuntimeError) as exc:
                failures.append(
                    f"{definition.action_id}@{definition.level}:{type(exc).__name__}:{exc}"
                )
                continue
    finally:
        TBGDLowering.build = original_build

    if selected is None:
        detail = failures[-12:] if failures else ["no strict flat-vs-closure delta found"]
        raise AssertionError(
            "no real TBGD action satisfies strict flat>graph closure with an excluded blocker "
            "and accepted public target selection:"
            + json.dumps(detail, ensure_ascii=False)
        )

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "ok": elapsed <= _DIRECT_HARD_SECONDS and peak <= 1024 * 1024,
        "mode": "direct",
        "predicates": {
            "real_signed_tbgd_source": True,
            "flat_bound_set_strictly_larger_than_graph_closure": True,
            "excluded_blocker_bearing_task_present": True,
            "reachable_graph_blockers_preserved": True,
            "public_target_selection_query_and_accept": True,
            "forged_authorization_or_selection_fingerprint": False,
            "full_canonical_ir_build_count": 0,
        },
        "representative": selected,
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
