from __future__ import annotations

import argparse
import inspect
import json
import resource
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..core.model import ActionCommand, BattleState, Mutation, TargetResolution, UnitState
from ..core.settlement import SettlementRecord
from ..ir_types import IRSource
from ..rules.engine_rule_registry import build_engine_rule_registry
from ..rules.ir import AbilityPhaseIR, AbilityTaskIR, ActionDefinitionIR, CanonicalIR, EffectIR
from ..rules.rulebook import RuleBook
from ..rules.task_graph import (
    TaskGraphDefinitionReferenceIR,
    TaskGraphEntryMaterializationIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphQueryResult,
    task_graph_entry_id,
    task_graph_id,
    task_graph_materialization_id,
    task_graph_node_id,
    task_graph_reference_id,
    task_graph_source_occurrence_id,
)
from ..systems.ability import AbilityTaskSystem
from ..systems.damage import DamageSystem
from ..systems.effect import EffectRegistry, EffectResult
from ..tbgd.lowering import TBGDLowering, build_character_action_definition_ir
from ..tbgd.task_graph_materializer import materialize_ability_task_graph_catalog


SHA = "b" * 64


def _source(name: str, opcode: str) -> IRSource:
    return IRSource(
        "validation_fixture/p9_s8b3b.json",
        opcode,
        name,
        {"json_path": f"$.{name}", "content_sha256": SHA, "source_opcode": opcode},
    )


@dataclass
class _FixtureRules:
    phases: tuple[AbilityPhaseIR, ...]
    tasks: tuple[AbilityTaskIR, ...]
    effects: tuple[EffectIR, ...]
    graphs: tuple[TaskGraphIR, ...]
    entries: tuple[TaskGraphEntryMaterializationIR, ...]

    def __post_init__(self) -> None:
        self._phases = {item.phase_id: item for item in self.phases}
        self._tasks = {item.task_id: item for item in self.tasks}
        self._effects = {item.effect_id: item for item in self.effects}
        self._graphs = {item.graph_id: item for item in self.graphs}
        self._entries = {
            (item.entry_kind, item.owner_id, item.callback_kind): item
            for item in self.entries
        }
        self._nodes = {
            node.graph_node_id: node for graph in self.graphs for node in graph.nodes
        }

    def engine_rule_registry(self) -> Any:
        return build_engine_rule_registry()

    def ability_tasks_for_phase(self, phase_id: str) -> tuple[AbilityTaskIR, ...]:
        return tuple(item for item in self.tasks if item.phase_id == phase_id)

    def ability_task(self, task_id: str) -> AbilityTaskIR | None:
        return self._tasks.get(task_id)

    def ability_phase(self, phase_id: str) -> AbilityPhaseIR | None:
        return self._phases.get(phase_id)

    def effect(self, effect_id: str) -> EffectIR | None:
        return self._effects.get(effect_id)

    def damage_emissions_for_task(self, _task_id: str) -> tuple[Any, ...]:
        return ()

    def query_task_graph_entry(self, kind: str, owner: str, callback: str) -> TaskGraphQueryResult:
        value = self._entries.get((kind, owner, callback))
        return (
            TaskGraphQueryResult("resolved", "entry", (value.entry_id,), value, "")
            if value is not None
            else TaskGraphQueryResult("blocked", "entry", (), None, "task_graph_missing:entry")
        )

    def query_task_graph(self, graph_id: str) -> TaskGraphQueryResult:
        value = self._graphs.get(graph_id)
        return (
            TaskGraphQueryResult("resolved", "graph", (graph_id,), value, "")
            if value is not None
            else TaskGraphQueryResult("blocked", "graph", (), None, "task_graph_missing:graph")
        )

    def query_task_graph_node(self, node_id: str) -> TaskGraphQueryResult:
        value = self._nodes.get(node_id)
        return (
            TaskGraphQueryResult("resolved", "node", (node_id,), value, "")
            if value is not None
            else TaskGraphQueryResult("blocked", "node", (), None, "task_graph_missing:node")
        )

    def standalone_ability_graph(self, _graph_id: str) -> None:
        return None

    def target_expression_resolution(self, _identity: str) -> tuple[None, str]:
        return None, "target_expression_missing"

    def target_expressions(self) -> tuple[Any, ...]:
        return ()

    def condition(self, _identity: str) -> None:
        return None

    def character_data_card(self, _identity: str) -> None:
        return None

    def character_data_card_for_entity(self, _identity: str) -> None:
        return None


def _fixture(cycle: bool = False) -> tuple[_FixtureRules, ActionDefinitionIR]:
    action_id, root_phase_id, nested_phase_id = "fixture:action", "fixture:root", "fixture:nested"
    root_source, leaf_source = _source("root", "TriggerAbility"), _source("leaf", "FixtureSetFlag")
    cycle_source = _source("cycle", "TriggerAbility")
    root_task = AbilityTaskIR(
        "fixture:root_task", root_phase_id, action_id, 1, "FixtureRoot", "OnStart", 0,
        "OnStart[0]", "root", "TriggerAbility", root_source,
        coverage_status="executable", linked_ability_phase_id=nested_phase_id,
    )
    leaf_task = AbilityTaskIR(
        "fixture:leaf_task", nested_phase_id, action_id, 1, "FixtureNested", "OnStart", 0,
        "OnStart[0]", "root", "FixtureSetFlag", leaf_source,
        effect_id="fixture:effect", coverage_status="executable",
    )
    cycle_task = AbilityTaskIR(
        "fixture:cycle_task", nested_phase_id, action_id, 1, "FixtureNested", "OnStart", 1,
        "OnStart[1]", "root", "TriggerAbility", cycle_source,
        coverage_status="executable", linked_ability_phase_id=nested_phase_id,
    )
    tasks = (root_task, leaf_task, *((cycle_task,) if cycle else ()))
    phases = (
        AbilityPhaseIR(root_phase_id, "fixture:binding", action_id, 1, "FixtureRoot", 0, {}, {}, {}, root_source, "executable", task_ids=(root_task.task_id,), invocation_role="action_root"),
        AbilityPhaseIR(nested_phase_id, "fixture:binding", action_id, 1, "FixtureNested", 1, {}, {}, {}, leaf_source, "executable", task_ids=tuple(item.task_id for item in tasks[1:]), invocation_role="nested_only"),
    )
    effect = EffectIR("fixture:effect", "FixtureSetFlag", {}, leaf_source, "executable")
    entries: list[TaskGraphEntryMaterializationIR] = []
    graphs: list[TaskGraphIR] = []
    for phase, selected in ((phases[0], (root_task,)), (phases[1], tasks[1:])):
        entry_id = task_graph_entry_id("ability_phase_callback", phase.phase_id, "OnStart")
        graph_id = task_graph_id("fixture:catalog", entry_id, SHA)
        occurrences = tuple(task_graph_source_occurrence_id(item.source, item.opcode) for item in selected)
        node_ids = tuple(task_graph_node_id(graph_id, item.task_id, occurrence) for item, occurrence in zip(selected, occurrences))
        nodes = []
        for item, occurrence, node_id in zip(selected, occurrences, node_ids):
            kind = "ability_call" if item.opcode == "TriggerAbility" else "leaf"
            ref_kind = "ability" if kind == "ability_call" else "effect"
            definition_id = item.linked_ability_phase_id if kind == "ability_call" else item.effect_id
            reference = TaskGraphDefinitionReferenceIR(
                task_graph_reference_id(node_id, ref_kind, definition_id), node_id,
                ref_kind, definition_id, "", "resolved", "ability_graph_resolution" if kind == "ability_call" else "event_effect_execution", item.source,
            )
            nodes.append(TaskGraphNodeIR(
                node_id, graph_id, occurrence, "", item.task_id, item.opcode, item.opcode,
                kind, (), (reference,), "not_applicable", "not_applicable", "",
                "materialized", ("task_graph_execution",), item.source,
            ))
        graph = TaskGraphIR(
            graph_id, entry_id, "ability_phase_callback", phase.phase_id, "OnStart",
            node_ids, tuple(nodes), (), "fixture:catalog", SHA, selected[0].source, "lowered",
        )
        materialization_id = task_graph_materialization_id(entry_id, tuple(item.task_id for item in selected), occurrences)
        entries.append(TaskGraphEntryMaterializationIR(
            materialization_id, entry_id, "ability_phase_callback", phase.phase_id,
            "OnStart", graph_id, tuple(item.task_id for item in selected), occurrences,
            "materialized", selected[0].source,
        ))
        graphs.append(graph)
    definition = ActionDefinitionIR(
        "fixture:definition", action_id, 1, "Skill", "Skill", "single", 0, 0, 0, 0,
        (), (), (), None, root_source, "executable", "none", "none",
    )
    return _FixtureRules(phases, tasks, (effect,), tuple(graphs), tuple(entries)), definition


def _system(rules: _FixtureRules, calls: list[str]) -> AbilityTaskSystem:
    registry = EffectRegistry()

    def handler(effect: EffectIR, _context: Any) -> EffectResult:
        calls.append(effect.effect_id)
        mutation = Mutation("set", ("global_flags", "fixture_count"), None, 1, "fixture", "validation_fixture", False, True, mutation_id="fixture:mutation")
        record = SettlementRecord("fixture_effect", "validation_fixture", mutation.stable_id(), payload={"effect_id": effect.effect_id}, trace=effect.source.to_json()).to_json()
        return EffectResult(mutations=(mutation,), records=(record,))

    registry.register("FixtureSetFlag", handler)
    return AbilityTaskSystem(rules, registry, damage=DamageSystem())  # type: ignore[arg-type]


def _invoke(system: AbilityTaskSystem, rules: _FixtureRules, definition: ActionDefinitionIR) -> Any:
    state = BattleState(units={
        "actor": UnitState("actor", "ally", "fixture:actor"),
        "target": UnitState("target", "enemy", "fixture:target"),
    })
    command = ActionCommand("actor", definition.action_id, 1, ("target",))
    resolution = TargetResolution(("target",), ("target",), ("target",), "target", ("target",), ("target",), (), "fixture", "validation_fixture")
    return state, system.execute_callback(state, phases=rules.phases, callback_kind="OnStart", command=command, action_definition=definition, target_resolution=resolution)


def _real_source_probe(root: Path) -> tuple[bool, dict[str, Any]]:
    lowering = TBGDLowering(root)
    source_graph = lowering.build_character_ability_source_graph_catalog()
    snapshot, scope = lowering._character_ability_raw_snapshot, lowering._character_ability_scope_catalog
    actions = {item.action_source_id: item for item in source_graph.action_sources}
    grouped: dict[str, list[Any]] = defaultdict(list)
    for binding in source_graph.bindings:
        if binding.action_source_id:
            grouped[binding.action_source_id].append(binding)
    definitions: dict[str, list[ActionDefinitionIR]] = defaultdict(list)
    for definition in build_character_action_definition_ir(root):
        definitions[definition.action_id].append(definition)
    counts = Counter(item.action_id for item in source_graph.action_sources)
    selected = None
    for source_id, bindings in sorted(grouped.items()):
        action = actions[source_id]
        if counts[action.action_id] != 1 or action.action_id not in definitions or not {"entry", "phase"} <= {item.binding_kind for item in bindings}:
            continue
        definition = min(definitions[action.action_id], key=lambda item: item.level)
        view = lowering.build_character_action_ability_slice(definition, snapshot=snapshot, scope_catalog=scope, source_graph_catalog=source_graph)
        linked = next((item for item in view.ability_tasks if item.linked_ability_phase_id), None)
        if linked is not None:
            selected = view, definition, linked
            break
    if selected is None:
        return False, {"reason": "real_action_root_nested_source_missing"}
    view, definition, linked = selected
    controls = lowering.build_character_control_flow_contract_catalog(snapshot=snapshot, scope_catalog=scope)
    catalog = materialize_ability_task_graph_catalog(controls, view, source_snapshot=snapshot)
    rules = RuleBook(replace(view, task_graph_catalog=catalog))
    system = AbilityTaskSystem(rules, EffectRegistry(), damage=DamageSystem())
    state = BattleState(units={"actor": UnitState("actor", "ally", "fixture:actor"), "target": UnitState("target", "enemy", "fixture:target")})
    result = system.execute_callback(state, phases=view.ability_phases, callback_kind=linked.callback_kind, command=ActionCommand("actor", definition.action_id, definition.level, ("target",)), action_definition=definition, target_resolution=TargetResolution(("target",), ("target",), ("target",), "target", ("target",), ("target",), (), "real_source_probe", "target_system"))
    honest = result.after_state is state and not result.mutations and not result.events and not result.rng_events and any(item.status == "blocked" for item in result.node_results)
    return honest, {"action_id": definition.action_id, "level": definition.level, "linked_phase_id": linked.linked_ability_phase_id, "blocked_reason": next((item.reason_code for item in reversed(result.node_results) if item.status == "blocked"), "")}


def _legacy_unchanged() -> bool:
    source = _source("legacy", "LegacyNoop")
    task = AbilityTaskIR(
        "fixture:legacy_task", "fixture:legacy_phase", "fixture:legacy_action", 1,
        "FixtureLegacy", "OnStart", 0, "OnStart[0]", "root", "LegacyNoop", source,
        effect_id="fixture:legacy_effect", execution_mode="process_only", coverage_status="audit_only",
    )
    phase = AbilityPhaseIR(
        task.phase_id, "fixture:legacy_binding", task.action_id, 1, task.ability_name, 0,
        {}, {}, {}, source, "audit_only", task_ids=(task.task_id,), invocation_role="external_legacy",
    )
    effect = EffectIR(
        task.effect_id, task.opcode,
        {"process_only_contract": {"schema_version": "ability_process_only_source_shape_v1", "opcode": task.opcode, "source_fields": ["$type"], "source_field_types": {"$type": "str"}, "source_shape_status": "admitted", "blocked_reason": ""}},
        source, "audit_only",
    )
    rules = _FixtureRules((phase,), (task,), (effect,), (), ())
    definition = ActionDefinitionIR(
        "fixture:legacy_definition", task.action_id, 1, "Skill", "Skill", "none",
        0, 0, 0, 0, (), (), (), None, source, "audit_only", "none", "none",
    )
    state = BattleState(units={"actor": UnitState("actor", "ally", "fixture:actor")})
    result = _system(rules, []).execute_callback(
        state, phases=(phase,), callback_kind="OnStart",
        command=ActionCommand("actor", task.action_id, 1), action_definition=definition,
        target_resolution=TargetResolution(reason="legacy_fixture"),
    )
    return result.after_state is state and len(result.task_records) == 1 and result.task_records[0].get("ok") is True


def validate(root: Path) -> dict[str, Any]:
    started = time.monotonic()
    calls: list[str] = []
    rules, definition = _fixture()
    state, success = _invoke(_system(rules, calls), rules, definition)
    cycle_calls: list[str] = []
    cycle_rules, cycle_definition = _fixture(cycle=True)
    cycle_state, cycle = _invoke(_system(cycle_rules, cycle_calls), cycle_rules, cycle_definition)
    missing_rules, missing_definition = _fixture()
    missing_rules.entries = ()
    missing_rules.__post_init__()
    missing_state, missing = _invoke(_system(missing_rules, []), missing_rules, missing_definition)
    real_ok, real = _real_source_probe(root)
    leaf_source = inspect.getsource(AbilityTaskSystem._execute_formal_leaf)
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "simulator_v8_clean_core/systems/status_callbacks.py"], check=False).returncode != 0
    predicates = {
        "character_action_uses_shared_executor_only": success.after_state.global_flags.get("fixture_count") == 1 and len(success.mutations) == 1,
        "nested_phase_not_executed_as_parallel_root": calls == ["fixture:effect"],
        "ability_leaf_has_no_child_runner": all(token not in leaf_source for token in ("_execute_task(", "child_task_ids", "_execute_trigger_ability_task", "self.reducer", "after_state")),
        "character_graph_missing_does_not_fallback": missing.after_state is missing_state and not missing.mutations and not missing.events and not missing.rng_events,
        "selected_path_failure_is_atomic": cycle.after_state is cycle_state and not cycle.mutations and not cycle.events and not cycle.rng_events,
        "active_graph_cycle_is_blocked": any("task_graph_active_cycle" in item.reason_code for item in cycle.node_results) and cycle_calls == ["fixture:effect"],
        "real_source_blocker_is_honest": real_ok,
        "external_legacy_behavior_changed": not _legacy_unchanged(),
        "status_callback_behavior_changed": changed,
    }
    return {"ok": all(value is True for key, value in predicates.items() if not key.endswith("_changed")) and not predicates["external_legacy_behavior_changed"] and not predicates["status_callback_behavior_changed"], "predicates": predicates, "real_source": real, "resource": {"elapsed_seconds": round(time.monotonic() - started, 3), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.tbgd_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "validation_summary_p9_s8b3b_action_callback_migration.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
