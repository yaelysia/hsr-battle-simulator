"""A real Remodifier subtree with explicit preinstalled component statuses."""
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


def test_real_remodifier_filters_buffs_and_extends_each_exact_instance(tmp_path):
    relative = "Config/ConfigAbility/Avatar/Avatar_SilverWolf999_00_Ability.json"
    path = "$.GlobalModifiers.MAvatar_SilverWolf999_00_Ultra._CallbackList[0].CallbackConfig[2].SuccessTaskList[0]"
    lowering, sources, lowered, languages = _formal_immunity_source(tmp_path, relative, 1506)
    root = next(row for row in lowered.status_callback_tasks
                if row.opcode == "Remodifier" and row.source.evidence.get("json_path") == path)
    children = tuple(row for row in lowered.status_callback_tasks
                     if row.task_path.startswith(root.task_path + ".formal_branch"))
    assert len(children) == 1 and children[0].opcode == "SetModifierValue"
    assert root.condition_id and all(row.coverage_status == "executable" for row in (root, *children))
    # Execute only this source subtree; the character's complete OnCreate and
    # its rank/build admission are outside this component check.
    callback = replace(next(row for row in lowered.status_callbacks if row.callback_id == root.callback_id),
                       task_ids=(root.task_id,))
    fixture_definitions = tuple(_modifier_definition_entity("validation_fixture/remodifier_inputs.json",
        "ModifierMap", name, {}, source_context={"json_path": "$.ModifierMap." + name})
        for name in ("SharedBuff", "Debuff", "PermanentBuff", "ZeroBuff"))
    canonical = CanonicalIR("remodifier-lifetime-component", entities=(*lowered.entities, *fixture_definitions),
        effects=tuple(lowered.effects), conditions=tuple(lowered.conditions),
        status_callbacks=(callback,), status_callback_tasks=(root, *children),
        target_expressions=tuple(close_target_expression_language(row, languages)
            for row in lowered.target_expressions) + tuple(row.expression for row in languages))
    catalog = materialize_status_callback_task_graph(sources, canonical, callback_id=callback.callback_id,
        source_snapshot=lowering._character_ability_raw_snapshot)
    assert len(catalog.graphs) == 1, catalog.entries
    graph = catalog.graphs[0]
    assert all(row.materialization_status == "materialized" for row in graph.nodes)
    rules = RuleBook(attach_task_graph_catalog(canonical, catalog))

    own = StatusInstance("listener", "modifier:" + callback.modifier_name, callback.modifier_name,
                         "holder", "fixture:listener", "caster").to_json()

    def status(identity, name, kind, remaining, caster):
        return StatusInstance(identity, "modifier:" + name, name, "caster", "fixture:" + identity, caster,
            duration=remaining, remaining_duration=remaining, status_type=kind,
            status_category=kind.lower(), duration_unit="turn", life_step_moment="ModifierPhase1End",
            duration_admission=({"admission_status": "not_applicable", "blocked_reason": "lifetime_missing"}
                if remaining is None else {"admission_status": "executable", "source_kind": "component_fixture"})
        ).to_json()

    details = [status("buff:1", "SharedBuff", "Buff", 2., "caster"),
        status("buff:2", "SharedBuff", "Buff", 5., "other"),
        status("debuff", "Debuff", "Debuff", 3., "other"),
        status("permanent", "PermanentBuff", "Buff", None, "other"),
        status("zero", "ZeroBuff", "Buff", 0., "other")]
    holder = UnitState("holder", "ally", "fixture:holder", hp=100, max_hp=100,
        statuses=(own["status_id"],), flags={"status_details": [own]})
    caster = UnitState("caster", "ally", "fixture:caster", hp=100, max_hp=100,
        statuses=tuple(dict.fromkeys(row["status_id"] for row in details)), flags={"status_details": details})
    state = BattleState(units={"holder": holder, "caster": caster,
        "other": UnitState("other", "ally", "fixture:other", hp=100, max_hp=100)})
    system = StatusCallbackSystem(rules)
    event = GameEvent("fixture:trigger", event_id="component:trigger", source_id="holder", target_id="holder")
    hooks = system._formal_status_hooks(callback, own, event, None, None, [], [], set())
    result = system.task_graph_executor.execute(state, graph,
        TaskGraphExecutionContext("component:remodifier"), hooks)
    assert result.ok, result.errors
    after = result.after_state.units["caster"].flags["status_details"]
    assert [row["remaining_duration"] for row in after] == [3., 6., 3., None, 0.]
    for before, updated in zip(details, after):
        assert {key: value for key, value in updated.items() if key != "remaining_duration"} == {
            key: value for key, value in before.items() if key != "remaining_duration"}
    assert result.after_state.units["holder"] == holder and not result.rng_events
    audit = RuntimeSourceAuditor(rules).validate_execution(
        result.mutations, tuple(row.to_json() for row in result.settlement_records))
    assert audit.ok, audit.to_json()

    # The first instance was already changed in the executor's working state.
    failed_hooks = replace(hooks, leaf=lambda request, current: (
        TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason="fixture:late-instance-failure")
        if request.status_scope.instance_id == "buff:2" else hooks.leaf(request, current)))
    failed = system.task_graph_executor.execute(state, graph,
        TaskGraphExecutionContext("component:remodifier"), failed_hooks)
    assert not failed.ok and failed.after_state == state
    assert not failed.mutations and not failed.events and not failed.rng_events
