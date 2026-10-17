"""Remodifier iterates live instances without changing the callback's owner."""
from dataclasses import replace
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from simulator_v8_clean_core.rules.ir import CanonicalIR
from simulator_v8_clean_core.rules.rulebook import RuleBook
from simulator_v8_clean_core.systems.status import StatusInstance
from simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem, TaskGraphStatusConditionProvider
from simulator_v8_clean_core.systems.task_graph import TaskGraphExecutionContext, TaskGraphStatusScope, TaskGraphLeafResult
from simulator_v8_clean_core.rules.condition_state import TransientConditionOperandRequest
from simulator_v8_clean_core.tbgd.lowering import TBGDLowering, _status_callback_task_admission
from simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from simulator_v8_clean_core.tbgd.task_graph_materializer import materialize_status_callback_task_graph, attach_task_graph_catalog


def test_real_named_remodifier_copies_each_source_instance_into_original_status(tmp_path):
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    relative = "Config/ConfigAbility/Avatar/Avatar_Cerydra_00_Ability.json"
    # Keep exact source bytes but use a two-file inventory, so this check does
    # not rebuild the whole character catalog.
    for name in ("AvatarConfig", "AvatarConfigLD", "AvatarConfigEnhanced", "AvatarServantConfig"):
        rows = json.loads((root / f"ExcelOutput/{name}.json").read_text()) if name == "AvatarConfig" else []
        rows = [row for row in rows if row.get("AvatarID") == 1412]
        path = tmp_path / f"ExcelOutput/{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
    for relative_path in (relative, "Config/ConfigAbility/Avatar/Avatar_Common_Ability.json",
            "Config/GlobalConfig/TargetAliasConfig.json", "Config/GlobalConfig/TargetOperationConfig.json"):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / relative_path).read_bytes())
    for source in (root / "Config/ConfigGlobalTaskListTemplate").glob("*.json"):
        if source.name.endswith(".layout.json"):
            continue
        path = tmp_path / source.relative_to(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.read_bytes())
    lowerer = TBGDLowering(tmp_path)
    source_catalog = lowerer.build_character_control_flow_contract_catalog()
    lowered = lowerer._lower_ability_file(tmp_path / relative, {}, ability_file_order=0,
        formal_status_source_context=lowerer._character_formal_task_source_context())
    definitions = lowerer._strict_target_language_definitions()
    task = next(row for row in lowered.status_callback_tasks
                if row.opcode == "Remodifier" and row.event == "OnBeforeSkillUse")
    callback = next(row for row in lowered.status_callbacks if row.callback_id == task.callback_id)
    children = sorted((row for row in lowered.status_callback_tasks
                       if row.task_path.startswith(task.task_path + ".formal_branch")), key=lambda row: row.task_index)
    assert task.coverage_status == "executable" and all(row.coverage_status == "executable" for row in children)
    assert _status_callback_task_admission(callback.event, "Remodifier",
        {**task.source.evidence["task"], "StatusTypeMask": "Buff|Debuff"})[0] == "blocked"
    callback = replace(callback, task_ids=(task.task_id,))
    canonical = CanonicalIR("remodifier-source-check", status_callbacks=(callback,),
        status_callback_tasks=(task, *children), effects=tuple(lowered.effects),
        target_expressions=tuple(close_target_expression_language(row, definitions)
            for row in lowered.target_expressions) + tuple(row.expression for row in definitions))
    catalog = materialize_status_callback_task_graph(source_catalog, canonical,
        callback_id=callback.callback_id, source_snapshot=lowerer._character_ability_raw_snapshot)
    assert len(catalog.graphs) == 1, catalog.entries
    graph = catalog.graphs[0]
    assert all(node.materialization_status == "materialized" for node in graph.nodes)
    rules = RuleBook(attach_task_graph_catalog(canonical, catalog))

    own = StatusInstance("listener", "modifier:" + callback.modifier_name, callback.modifier_name,
        "holder", "source:listener", "caster", dynamic_values={
            "MDF_Windfury_Flag": 0, "MDF_Windfury_Flag_Sum": 0,
            "__by_hash": {"1909050563": 0, "797038063": 0},
            "__definition_bindings": {"by_name": {
                "MDF_Windfury_Flag": {"hashes": ["1909050563"]},
                "MDF_Windfury_Flag_Sum": {"hashes": ["797038063"]},
            }},
        }).to_json()
    windfury = [StatusInstance(f"wind:{i}", "modifier:MCommon_Windfury", "MCommon_Windfury",
        "holder", f"source:{i}", f"caster:{i}", stacks=i + 1,
        dynamic_values={"Windfury_Flag": value}).to_json() for i, value in enumerate((2, 3))]
    holder = UnitState("holder", "ally", "fixture:holder", hp=100, max_hp=100,
        statuses=(own["status_id"], windfury[0]["status_id"]), flags={"status_details": [own, *windfury]})
    state = BattleState(units={"holder": holder,
        "caster": UnitState("caster", "ally", "fixture:caster", hp=100, max_hp=100)})
    system = StatusCallbackSystem(rules)
    template_targets = []
    execute_effect = system.effect_registry.execute

    def record_context(effect, context):
        template_targets.append(context.template_target_ids)
        return execute_effect(effect, context)

    system.effect_registry.execute = record_context
    event = GameEvent("fixture:trigger", event_id="trigger", source_id="holder", target_id="holder")
    hooks = system._formal_status_hooks(callback, own, event, None, None, [], [], set())
    result = system.task_graph_executor.execute(state, graph,
        TaskGraphExecutionContext("scope-check", template_target_ids=("holder", "caster")), hooks)
    assert result.ok, result.errors
    assert template_targets and all(value == ("holder", "caster") for value in template_targets)
    after = result.after_state.units["holder"].flags["status_details"]
    assert after[0]["dynamic_values"]["__by_name"]["MDF_Windfury_Flag_Sum"] == 5
    assert after[1:] == windfury
    assert own["dynamic_values"]["MDF_Windfury_Flag_Sum"] == 0

    scope = TaskGraphStatusScope("holder", "wind:1")
    provider = TaskGraphStatusConditionProvider(state, scope, "condition", "scope")
    request = TransientConditionOperandRequest("status_callback.modifier_value", "condition", "scope",
        parameters={"value_type": "Layer"})
    assert provider.resolve_transient(request).value == 2
    removed = replace(state, units={**state.units, "holder": replace(holder,
        flags={"status_details": [own, windfury[0]]})})
    assert replace(provider, state=removed).resolve_transient(request).status == "blocked"

    failed_rules = replace(hooks, leaf=lambda request, current: (
        TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason="late-child-failure")
        if request.status_scope.instance_id == "wind:1" else hooks.leaf(request, current)))
    failed = system.task_graph_executor.execute(state, graph, TaskGraphExecutionContext("scope-check"), failed_rules)
    assert not failed.ok and failed.after_state == state and not failed.mutations
