from __future__ import annotations

import argparse
import ast
import json
import resource
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..ir_types import IRSource
from ..rules.ir import (
    AbilityPhaseIR, AbilityTaskIR, ActionDefinitionIR, StatusCallbackTaskIR,
    ExternalTaskTopologyDependencyIR, StandaloneAbilityGraphIR,
    build_external_task_topology_dependency_ledger,
)
from ..rules.task_graph import (
    TaskGraphIR, TaskGraphNodeIR, task_graph_entry_id, task_graph_id,
    task_graph_node_id, task_graph_source_occurrence_id,
)
from ..systems.ability_task_contract import ability_task_runtime_blocked_reason
from ..tbgd.lowering import TBGDLowering, _AbilityFormalTaskSourceContext
from ..tbgd.task_graph_materializer import _FormalTask, _source_topology

SHA = "a" * 64
FIELDS = {"parent_task_id", "child_task_ids", "success_task_ids", "failed_task_ids"}
ALLOWED_READERS = {
    ("core/executor.py", "_legacy_ability_task_damage_reachable_ids"),
    ("core/executor.py", "_legacy_callback_damage_roots"),
    ("core/executor.py", "_callback_damage_selected_branch"),
    ("systems/ability.py", "_execute_legacy_callback"),
    ("systems/ability.py", "_execute_fixed_task_loop"),
    ("systems/ability.py", "_execute_predicate_task"),
    ("systems/ability_task_contract.py", "ability_task_runtime_blocked_reason"),
    ("systems/status.py", "_legacy_on_create_root_tasks"),
    ("systems/status_callbacks.py", "_execute_legacy_callback"),
    ("systems/status_callbacks.py", "_execute_container_task"),
    ("systems/status_callbacks.py", "_execute_random_config_task"),
    ("systems/status_callbacks.py", "_execute_predicate_task"),
    ("systems/status_callbacks.py", "_execute_retarget_task"),
    ("systems/status_callbacks.py", "_execute_remodifier_query_task"),
    ("scenarios/build_state.py", "_legacy_startup_root_tasks"),
}


def _source(path: str, raw_id: str, json_path: str, family: str) -> IRSource:
    return IRSource(path, "AbilityTask", raw_id, {
        "json_path": json_path, "content_sha256": SHA, "source_opcode": family,
    })


def _rejects(callable_: Any) -> bool:
    try:
        callable_()
    except (TypeError, ValueError):
        return True
    return False


def _formal_lowering() -> tuple[AbilityTaskIR, StatusCallbackTaskIR]:
    path = "validation_fixture/p9_s8b6.py.json"
    task = {"$type": "RPG.GameCore.WaitForSeconds"}
    ability = {"Name": "Fixture", "OnStart": [task], "_CallbackList": [{"Event": "OnCreate", "CallbackConfig": [task]}]}
    document = {"AbilityList": [ability]}
    context = _AbilityFormalTaskSourceContext("fixture", {}, {}, {}, {path: document}, {path: SHA})
    lowering = object.__new__(TBGDLowering)
    lowering._character_formal_task_source_context_cache = context
    definition = ActionDefinitionIR(
        "fixture:def", "fixture:action", 1, "Skill", "Skill", "single",
        0, 0, 0, 0, (), (), (), None, _source(path, "definition", "$.Definition", "Definition"),
        "executable", "none", "none",
    )
    lowered = lowering._lower_ability_phase_tasks(
        definition=definition, phase_id="fixture:phase", ability_name="Fixture",
        ability=ability, ability_path=path, ability_index=0, formal_source_context=context,
    )
    status = lowering._lower_status_callback_tasks([task], relative=path, map_name="AbilityList", modifier_name="Fixture", callback_id="fixture:callback", event="OnCreate", callback_index=0, task_list_json_path="$.AbilityList[0]._CallbackList[0].CallbackConfig", queue_priority_lookup={}, formal_source_context=context)
    if len(lowered.ability_tasks) != 1 or len(lowered.ability_root_task_ids) != 1 or len(status.status_callback_tasks) != 1 or len(status.status_callback_root_task_ids) != 1:
        raise AssertionError("formal lowering fixture is not singular")
    return lowered.ability_tasks[0], status.status_callback_tasks[0]


def _source_topology_probe() -> bool:
    path = "validation_fixture/shared_template.json"
    task_by_id, sources, controls = {}, {}, {}
    for index in range(2):
        root_id, child_id = f"root:{index}", f"child:{index}"
        root_source = _source(path, "root", "$.Template.Root", "PredicateTaskList")
        child_source = _source(path, "child", "$.Template.Child", "WaitForSeconds")
        root_path = f"OnStart[{index}]"
        task_by_id[root_id] = _FormalTask(root_id, root_path, "PredicateTaskList", "PredicateTaskList", "", "", "", "", "", "runtime_effect", "executable", root_source)
        task_by_id[child_id] = _FormalTask(child_id, f"{root_path}.formal_branch[0].child[0]", "WaitForSeconds", "WaitForSeconds", "", "", "", "", "", "process_only", "audit_only", child_source)
        sources[root_id], sources[child_id] = root_source, child_source
        child_record = SimpleNamespace(source=_source(path, "child", "$.Template.Child.$type", "WaitForSeconds"), family="WaitForSeconds", ordinal=0)
        branch = SimpleNamespace(branch_kind="success", label="SuccessTaskList", children=(child_record,), source=root_source)
        controls[root_id] = SimpleNamespace(branches=(branch,), control_role="predicate_branch")
    topology, roots = _source_topology(task_by_id, tuple(task_by_id), sources, controls, {}, {})
    return roots == ("root:0", "root:1") and tuple(row.child_task_ids for root in roots for row in topology[root]) == (("child:0",), ("child:1",))


def _graph_codec() -> tuple[bool, bool]:
    source = _source("validation_fixture/graph.json", "node", "$.Node", "WaitForSeconds")
    entry = task_graph_entry_id("ability_phase_callback", "fixture:phase", "OnStart")
    graph_id = task_graph_id("fixture:catalog", entry, SHA)
    occurrence = task_graph_source_occurrence_id(source, "WaitForSeconds")
    node_id = task_graph_node_id(graph_id, "fixture:task", occurrence)
    node = TaskGraphNodeIR(node_id, graph_id, occurrence, "", "fixture:task", "WaitForSeconds", "WaitForSeconds", "leaf", (), (), "not_applicable", "not_applicable", "", "materialized", ("task_graph_execution",), source)
    graph = TaskGraphIR(graph_id, entry, "ability_phase_callback", "fixture:phase", "OnStart", (node_id,), (node,), (), "fixture:catalog", SHA, source, "lowered")
    payload = node.to_json(); payload["parent_task_id"] = ""
    return TaskGraphIR.from_json(graph.to_json()).root_formal_task_ids == ("fixture:task",), _rejects(lambda: TaskGraphNodeIR.from_json(payload))


def _external_ledger() -> tuple[bool, bool]:
    source = _source("validation_fixture/external.json", "task", "$.Task", "WaitForSeconds")
    graph = StandaloneAbilityGraphIR("external:graph", "External", "mainline_monster", ("external:phase",), ("external:task",), ("external:task",), source, "executable")
    phase = AbilityPhaseIR("external:phase", graph.standalone_ability_graph_id, "external:action", 1, "External", 0, {}, {}, {}, source, "executable", "", ("external:task",), "external_legacy")
    task = AbilityTaskIR("external:task", phase.phase_id, phase.action_id, 1, "External", "OnStart", 0, "OnStart[0]", "root", "WaitForSeconds", source, child_task_ids=("external:child",), coverage_status="executable")
    ledger = build_external_task_topology_dependency_ledger(action_ability_bindings=(), ability_phases=(phase,), ability_tasks=(task,), standalone_ability_graphs=(graph,), status_callbacks=(), status_callback_tasks=())
    raw = json.loads(json.dumps(ledger[0].to_json())); restored = ExternalTaskTopologyDependencyIR.from_json(raw)
    raw["source"]["evidence"]["json_path"] = "$.Tampered"
    exact = len(ledger) == 1 and restored.to_json() == ledger[0].to_json() and restored.source.evidence["json_path"] == "$.Task"
    invalid = _rejects(lambda: build_external_task_topology_dependency_ledger(action_ability_bindings=(), ability_phases=(phase,), ability_tasks=(task,), standalone_ability_graphs=(graph, graph), status_callbacks=(), status_callback_tasks=()))
    invalid &= _rejects(lambda: build_external_task_topology_dependency_ledger(action_ability_bindings=(), ability_phases=(), ability_tasks=(task,), standalone_ability_graphs=(graph,), status_callbacks=(), status_callback_tasks=()))
    return exact, invalid


def _runtime_reads(root: Path) -> list[dict[str, object]]:
    rows = []
    paths = [*root.joinpath("core").rglob("*.py"), *root.joinpath("systems").rglob("*.py"), *root.joinpath("scenarios").rglob("*.py"), root / "rules/rulebook.py"]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8")); parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node): parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load) or node.attr not in FIELDS: continue
            owner = node
            while owner in parents and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)): owner = parents[owner]
            rows.append({"path": str(path.relative_to(root)), "function": getattr(owner, "name", "<module>"), "field": node.attr, "line": node.lineno})
    return sorted(rows, key=lambda row: (str(row["path"]), int(row["line"])))


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", required=True); args = parser.parse_args()
    started = time.perf_counter(); root = Path(__file__).resolve().parents[1]; output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    formal_tasks = _formal_lowering(); graph_roundtrip, old_payload_rejected = _graph_codec(); ledger_exact, duplicate_owner_rejected = _external_ledger(); reads = _runtime_reads(root)
    loop = AbilityTaskIR("loop", "phase", "action", 1, "Ability", "OnStart", 0, "OnStart[0]", "root", "LoopExecuteTaskListWithInterval", _source("validation_fixture/loop.json", "loop", "$.Loop", "LoopExecuteTaskListWithInterval"), repeat_count=1, coverage_status="executable")
    plan = root.joinpath("P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md").read_text(encoding="utf-8"); s8c = root.joinpath("docs/p9_execution_cards/P9-S8C_HIT_BARRIER_RANDOM_SEQUENCE.md").read_text(encoding="utf-8")
    reader_pairs = {(str(row["path"]), str(row["function"])) for row in reads}
    unexpected_readers = reader_pairs - ALLOWED_READERS
    checks = {
        "p9_character_legacy_runtime_fallback_count": len(unexpected_readers),
        "p9_status_legacy_runtime_fallback_count": len(unexpected_readers),
        "external_content_legacy_dependency_ledger_complete": ledger_exact and duplicate_owner_rejected,
        "uncovered_content_domain_was_not_broken": ability_task_runtime_blocked_reason(None, loop, topology_authority="task_graph") == "" and ability_task_runtime_blocked_reason(None, loop, topology_authority="external_legacy") == "loop_task_list_missing_or_empty",
        "task_graph_source_audit_remains_complete": _source_topology_probe() and graph_roundtrip,
        "formal_task_legacy_topology_population_count": sum(bool(getattr(task, field)) or field in task.source.evidence for task in formal_tasks for field in FIELDS),
        "task_graph_json_rejects_legacy_topology_payload": old_payload_rejected,
        "s8b_substage_ledger_is_complete": all(f"- [x] P9-{stage} " in plan for stage in ("S8B1", "S8B2", "S8B1-R2", "S8B3A", "S8B3B", "S8B3C", "S8B3", "S8B4A", "S8B4B", "S8B4", "S8B5A", "S8B5B", "S8B5C", "S8B5")),
        "s8c_obligations_remain_precise_and_unexecuted": "硬前置：P9-S8B1 至 P9-S8B6" in s8c and "- [ ] P9-S8C " in plan,
        "prior_substage_main_rerun_count": 0,
    }
    ok = all(value if type(value) is bool else type(value) is int and value == 0 for value in checks.values())
    summary = {"ok": ok, "checks": checks, "runtime_legacy_read_count": len(reads), "elapsed_seconds": round(time.perf_counter() - started, 6), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    output.joinpath("runtime_legacy_dependency_ledger.json").write_text(json.dumps(reads, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.joinpath("validation_summary_p9_s8b6_legacy_topology_retirement.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False)); return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
