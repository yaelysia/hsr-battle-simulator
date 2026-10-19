"""Real Phainon ultimate OnStack filter extending the turn owner's buffs."""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status import StatusInstance
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutionContext, TaskGraphLeafResult
from hsr.simulator_v8_clean_core.tests.test_status_shared_immunity import _formal_immunity_source
from hsr.simulator_v8_clean_core.tbgd.lowering import _modifier_definition_entity
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    attach_task_graph_catalog, materialize_status_callback_task_graph,
)

ULTRA = "MAvatar_Phainon_00_Ultra"
CALLBACK_PATH = "$.GlobalModifiers.MAvatar_Phainon_00_Ultra._CallbackList[2].CallbackConfig[1]"


def _status(identity, name, kind, remaining, caster):
    return StatusInstance(identity, "modifier:" + name, name, "turn_owner", "fixture:" + identity, caster,
        duration=remaining, remaining_duration=remaining, status_type=kind,
        status_category=kind.lower(), duration_unit="turn", life_step_moment="ModifierPhase1End",
        duration_admission=({"admission_status": "not_applicable", "blocked_reason": "lifetime_missing"}
            if remaining is None else {"admission_status": "executable", "source_kind": "component_fixture"})
    ).to_json()


def _rules(tmp_path):
    relative = "Config/ConfigAbility/Avatar/Avatar_Phainon_00_Ability.json"
    lowering, sources, lowered, languages = _formal_immunity_source(tmp_path, relative, 1408)
    outer = next(row for row in lowered.status_callback_tasks
                 if row.opcode == "PredicateTaskList"
                 and row.source.evidence.get("json_path") == CALLBACK_PATH)
    remodifier = next(row for row in lowered.status_callback_tasks
                      if row.opcode == "Remodifier"
                      and row.source.evidence.get("json_path") == CALLBACK_PATH + ".SuccessTaskList[0]")
    children = tuple(row for row in lowered.status_callback_tasks
                     if row.task_path.startswith(remodifier.task_path + ".formal_branch"))
    assert len(children) == 1 and children[0].opcode == "SetModifierValue"
    assert outer.condition_id and all(row.coverage_status == "executable"
                                      for row in (outer, remodifier, *children))
    callback = replace(next(row for row in lowered.status_callbacks if row.callback_id == outer.callback_id),
                       task_ids=(outer.task_id,))
    fixture_definitions = tuple(_modifier_definition_entity(
        "validation_fixture/phainon_turn_owner_buffs.json", "ModifierMap", name, {},
        source_context={"json_path": "$.ModifierMap." + name})
        for name in ("SharedBuff", "Debuff", "PermanentBuff", "ZeroBuff"))
    canonical = CanonicalIR("phainon-buff-lifetime-component",
        entities=(*lowered.entities, *fixture_definitions), effects=tuple(lowered.effects),
        conditions=tuple(lowered.conditions), status_callbacks=(callback,),
        status_callback_tasks=(outer, remodifier, *children),
        target_expressions=tuple(close_target_expression_language(row, languages)
            for row in lowered.target_expressions) + tuple(row.expression for row in languages))
    catalog = materialize_status_callback_task_graph(sources, canonical, callback_id=callback.callback_id,
        source_snapshot=lowering._character_ability_raw_snapshot)
    assert len(catalog.graphs) == 1, catalog.entries
    graph = catalog.graphs[0]
    assert all(row.materialization_status == "materialized" for row in graph.nodes)
    return RuleBook(attach_task_graph_catalog(canonical, catalog)), graph, callback


def _state(turn_owner="turn_owner"):
    listener = StatusInstance("listener", "modifier:" + ULTRA, ULTRA, "phainon", "fixture:ultra", "phainon").to_json()
    details = [
        _status("buff:1", "SharedBuff", "Buff", 2.0, "phainon"),
        _status("buff:2", "SharedBuff", "Buff", 5.0, "other"),
        _status("debuff", "Debuff", "Debuff", 3.0, "other"),
        _status("permanent", "PermanentBuff", "Buff", None, "other"),
        _status("zero", "ZeroBuff", "Buff", 0.0, "other"),
    ]
    turn_owner_unit = UnitState(turn_owner, "ally", "fixture:" + turn_owner, hp=100, max_hp=100,
        statuses=tuple(dict.fromkeys(row["status_id"] for row in details)), flags={"status_details": details})
    return BattleState(global_flags={"turn_owner_id": turn_owner}, units={
        "phainon": UnitState("phainon", "ally", "fixture:phainon", hp=100, max_hp=100,
            statuses=(listener["status_id"],), flags={"status_details": [listener]}),
        turn_owner: turn_owner_unit,
        "other": UnitState("other", "ally", "fixture:other", hp=100, max_hp=100),
        "enemy": UnitState("enemy", "enemy", "fixture:enemy", hp=100, max_hp=100),
    })


def test_real_phainon_onstack_extends_each_positive_buff_on_turn_owner(tmp_path):
    rules, graph, callback = _rules(tmp_path)
    state = _state()
    system = StatusCallbackSystem(rules)
    listener = state.units["phainon"].flags["status_details"][0]
    event = GameEvent("fixture:trigger", event_id="component:trigger", source_id="phainon", target_id="phainon")
    hooks = system._formal_status_hooks(callback, listener, event, None, None, [], [], set())
    result = system.task_graph_executor.execute(state, graph,
        TaskGraphExecutionContext("component:phainon"), hooks)
    assert result.ok, result.errors
    after = result.after_state.units["turn_owner"].flags["status_details"]
    assert [row["remaining_duration"] for row in after] == [3.0, 6.0, 3.0, None, 0.0]
    for before, updated in zip(state.units["turn_owner"].flags["status_details"], after):
        if before["instance_id"] in {"buff:1", "buff:2"}:
            continue
        assert updated == before
    assert result.after_state.units["phainon"] == state.units["phainon"]
    assert result.after_state.units["other"] == state.units["other"]
    assert result.after_state.units["enemy"] == state.units["enemy"]
    assert not result.rng_events
    audit = RuntimeSourceAuditor(rules).validate_execution(
        result.mutations, tuple(row.to_json() for row in result.settlement_records))
    assert audit.ok, audit.to_json()

    # The committed turn owner must be a team member; an enemy turn owner is
    # rejected by the source PredicateTaskList before any Remodifier runs.
    enemy_turn = BattleState(global_flags={"turn_owner_id": "enemy"},
        units={**state.units, "turn_owner": replace(state.units["turn_owner"], unit_id="turn_owner")})
    hooks = system._formal_status_hooks(callback, listener, event, None, None, [], [], set())
    skipped = system.task_graph_executor.execute(enemy_turn, graph,
        TaskGraphExecutionContext("component:phainon-enemy"), hooks)
    assert skipped.ok and skipped.after_state == enemy_turn
    assert not skipped.mutations and not skipped.events


def test_real_phainon_onstack_instance_failure_rolls_back_the_whole_subtree(tmp_path):
    rules, graph, callback = _rules(tmp_path)
    state = _state()
    system = StatusCallbackSystem(rules)
    listener = state.units["phainon"].flags["status_details"][0]
    event = GameEvent("fixture:trigger", event_id="component:trigger", source_id="phainon", target_id="phainon")
    hooks = system._formal_status_hooks(callback, listener, event, None, None, [], [], set())
    failed_hooks = replace(hooks, leaf=lambda request, current: (
        TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason="fixture:late-instance-failure")
        if request.status_scope.instance_id == "buff:2" else hooks.leaf(request, current)))
    failed = system.task_graph_executor.execute(state, graph,
        TaskGraphExecutionContext("component:phainon"), failed_hooks)
    assert not failed.ok and failed.after_state == state
    assert not failed.mutations and not failed.rng_events
