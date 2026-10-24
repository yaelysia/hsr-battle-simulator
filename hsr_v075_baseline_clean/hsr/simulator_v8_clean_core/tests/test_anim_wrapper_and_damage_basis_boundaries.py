"""Component boundaries for the animation wrapper unit and damage basis.

These checks use the typed IR, real lowering and the fixed TBGD source slice.
They do not compile the whole RuleBook, build a session or replay an archive.
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hsr.simulator_v8_clean_core.core.model import (
    BattleState,
    TargetResolution,
    UnitState,
)
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import (
    ActionDefinitionIR,
    AbilityTaskIR,
    CanonicalIR,
    EffectIR,
    HitProfileIR,
    IRSource,
    SkillFormulaBindingIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.ability import (
    AbilityTaskSystem,
    StandaloneAbilityInvocation,
    _FormalAbilityInvocation,
    _damage_targets_for_emission,
)
from hsr.simulator_v8_clean_core.systems.damage_formula import (
    DamageFormulaInput,
    DirectDamageFormula,
)
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering,
    _damage_scaling_basis_expr,
)


ROOT = Path(__file__).resolve().parents[4]
TBGD = ROOT / "turnbasedgamedata-main"
MONSTER_ABILITY = "Config/ConfigAbility/Monster/Monster_W2_Mecha02_00_Ability.json"


def _definition() -> ActionDefinitionIR:
    return ActionDefinitionIR(
        "component:action",
        "standalone_ability:component",
        0,
        "Normal",
        "Attack",
        "self",
        0,
        0,
        0,
        0,
        (),
        (),
        (),
        None,
        IRSource("component", "Ability", "component"),
        "executable",
    )


def _real_wrapper() -> tuple[dict, dict]:
    data = json.loads((TBGD / MONSTER_ABILITY).read_text())
    insert = next(
        ability
        for ability in data["AbilityList"]
        if ability["Name"].endswith("_SkillP01_Insert")
    )
    initiate = next(
        ability
        for ability in data["AbilityList"]
        if ability["Name"].endswith("_SkillP01_Initiate")
    )
    wrapper = next(
        task
        for task in insert["OnStart"]
        if task["$type"].endswith(".TriggerAnimStateWithMove")
    )
    child = next(
        task
        for task in initiate["OnStart"]
        if task["$type"].endswith(".DefineDynamicValue")
    )
    return copy.deepcopy(wrapper), copy.deepcopy(child)


def _fixed_time(value: float) -> dict:
    return {"IsDynamic": False, "FixedValue": {"Value": value}}


def _lower_wrapper(raw: dict):
    lowerer = TBGDLowering(TBGD)
    return lowerer._lower_ability_task_tree(
        raw,
        definition=_definition(),
        phase_id="component:phase",
        ability_name="component",
        ability_path="component/anim-wrapper.json",
        ability_index=0,
        callback_kind="OnStart",
        task_index=0,
        task_path="OnStart[0]",
        branch="root",
        parent_task_id="",
    )


def _ordered_wrapper_part():
    wrapper, child = _real_wrapper()
    wrapper["EventList"] = [
        {
            "NormalizedTime": _fixed_time(0.0),
            "TaskList": [copy.deepcopy(child), copy.deepcopy(child)],
        },
        {
            "NormalizedTime": _fixed_time(1.0),
            "TaskList": [copy.deepcopy(child)],
        },
    ]
    part = _lower_wrapper(wrapper)
    parent = next(
        task
        for task in part.ability_tasks
        if task.opcode == "TriggerAnimStateWithMove"
    )
    return part, parent


# ---------------------------------------------------------------------------
# Lowering: one fail-closed unit with a fixed, ordered source timeline.
# ---------------------------------------------------------------------------


def test_lowering_keeps_source_event_order_in_the_formal_child_ledger():
    part, parent = _ordered_wrapper_part()

    assert parent.coverage_status == "executable"
    assert parent.execution_mode == "runtime_effect"
    assert parent.blocked_reason == ""
    by_id = {task.task_id: task for task in part.ability_tasks}
    assert [
        by_id[child_id].task_path for child_id in parent.child_task_ids
    ] == [
        "OnStart[0].EventList[0].TaskList[0]",
        "OnStart[0].EventList[0].TaskList[1]",
        "OnStart[0].EventList[1].TaskList[0]",
    ]
    # The raw per-event index resets, so it cannot be the runtime order key.
    assert [
        by_id[child_id].task_index for child_id in parent.child_task_ids
    ] == [0, 1, 0]

    wrapper_effect = next(
        effect
        for effect in part.effects
        if effect.effect_id == parent.effect_id
    )
    standard = wrapper_effect.payload["standard"]
    assert standard["operation"] == "anim_wrapper_task_list"
    assert standard["source_shape"] == "animation_timeline_with_gameplay_leaves"
    assert standard["event_list_child_count"] == 3
    assert standard["gameplay_child_count"] == 3
    assert standard["blocked_reason"] == ""


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            lambda wrapper: wrapper.update(
                UnadmittedGameplay={"$type": "RPG.GameCore.SetHP"}
            ),
            "process_only_task_unknown_fields:UnadmittedGameplay",
        ),
        (
            lambda wrapper: wrapper["EventList"][0].update(
                NormalizedTime={"Unresolved": True}
            ),
            "trigger_anim_state_with_move_nested_event_shape_not_admitted",
        ),
        (
            lambda wrapper: wrapper["EventList"][0].update(
                NormalizedTime={
                    "PostfixExpr": {
                        "OpCodes": [1, 0, 17],
                        "FixedValues": [],
                        "DynamicHashes": [1246667513],
                    }
                }
            ),
            "trigger_anim_state_with_move_source_time_not_fixed",
        ),
        (
            lambda wrapper: (
                wrapper["EventList"][0].update(NormalizedTime=_fixed_time(0.8)),
                wrapper["EventList"][1].update(NormalizedTime=_fixed_time(0.1)),
            ),
            "trigger_anim_state_with_move_source_time_not_monotonic",
        ),
    ],
)
def test_lowering_rejects_unadmitted_wrapper_shapes_as_one_blocked_unit(
    mutation, expected_reason
):
    wrapper, child = _real_wrapper()
    wrapper["EventList"] = [
        {
            "NormalizedTime": _fixed_time(0.0),
            "TaskList": [copy.deepcopy(child)],
        },
        {
            "NormalizedTime": _fixed_time(1.0),
            "TaskList": [copy.deepcopy(child)],
        },
    ]
    mutation(wrapper)

    part = _lower_wrapper(wrapper)

    assert [task.opcode for task in part.ability_tasks] == [
        "TriggerAnimStateWithMove"
    ]
    parent = part.ability_tasks[0]
    assert parent.coverage_status == "blocked"
    assert expected_reason in parent.blocked_reason
    assert parent.child_task_ids == ()


def test_pure_presentation_wrapper_keeps_the_strict_process_only_proof():
    wrapper, _child = _real_wrapper()
    wrapper["EventList"] = [wrapper["EventList"][0]]

    part = _lower_wrapper(wrapper)

    parent = part.ability_tasks[0]
    assert parent.opcode == "TriggerAnimStateWithMove"
    assert parent.execution_mode == "process_only"
    assert parent.coverage_status == "audit_only"
    assert parent.blocked_reason == ""
    wrapper_effect = next(
        effect
        for effect in part.effects
        if effect.effect_id == parent.effect_id
    )
    contract = wrapper_effect.payload["process_only_contract"]
    assert contract["source_shape_status"] == "admitted"
    assert contract["blocked_reason"] == ""


# ---------------------------------------------------------------------------
# Runtime: prove the wrapper unit before executing any child, then run the
# formal ledger in source order.
# ---------------------------------------------------------------------------


def _system(tasks, *, effects):
    system = AbilityTaskSystem.__new__(AbilityTaskSystem)
    system.rules = RuleBook(
        CanonicalIR(
            "component:wrapper",
            ability_tasks=tuple(tasks),
            effects=tuple(effects),
        )
    )
    system.reducer = MutationReducer()
    system.event_dispatcher = SimpleNamespace(
        dispatch_event=lambda *_args, **_kwargs: pytest.fail(
            "an animation wrapper leaf must not dispatch an event"
        )
    )
    return system


def _invocation() -> _FormalAbilityInvocation:
    target = "child"
    return _FormalAbilityInvocation(
        "queue_standalone",
        "owner",
        "graph",
        0,
        TargetResolution(
            requested=(target,),
            legal=(target,),
            selected=(target,),
            primary=target,
            reason="component",
            source="component",
        ),
        standalone=StandaloneAbilityInvocation(
            "graph",
            "owner",
            (target,),
            "interrupt_queue",
            "entry",
            "intent",
            "resolution",
        ),
        dispatched_event_ids=set(),
    )


def _battle_state() -> BattleState:
    return BattleState(
        units={
            "owner": UnitState(
                "owner", "ally", "component:owner", hp=100.0, max_hp=100.0
            ),
            "child": UnitState(
                "child", "enemy", "component:child", hp=100.0, max_hp=100.0
            ),
        }
    )


def _run_wrapper(tasks, *, effects):
    calls: list[str] = []

    def execute_leaf(current, task, **_kwargs):
        calls.append(task.task_id)
        return current, [], [], [], []

    system = _system(tasks, effects=effects)
    system._execute_effect_leaf_task = execute_leaf
    parent = next(
        task
        for task in tasks
        if task.opcode == "TriggerAnimStateWithMove"
    )
    result = system._execute_external_legacy_standalone_entries(
        _battle_state(),
        entries=((SimpleNamespace(phase_id=parent.phase_id, ability_name="component"), "OnStart"),),
        invocation=_invocation(),
    )
    return calls, result


def test_runtime_executes_the_formal_child_ledger_in_source_order():
    part, parent = _ordered_wrapper_part()
    by_id = {task.task_id: task for task in part.ability_tasks}
    expected = [
        by_id[child_id].task_id for child_id in parent.child_task_ids
    ]
    naive_sort = [
        task.task_id
        for task in sorted(
            (task for task in part.ability_tasks if task.parent_task_id == parent.task_id),
            key=lambda item: (item.task_index, item.task_path, item.task_id),
        )
    ]
    assert naive_sort != expected

    calls, result = _run_wrapper(part.ability_tasks, effects=part.effects)

    assert calls == expected
    assert [node.node_kind for node in result.node_results] == [
        "external_ability_leaf",
        "external_ability_leaf",
        "external_ability_leaf",
        "external_ability_anim_wrapper",
    ]
    assert all(node.status == "complete" for node in result.node_results)


def test_runtime_never_executes_a_child_of_a_blocked_wrapper():
    part, parent = _ordered_wrapper_part()
    tasks = [
        replace(parent, coverage_status="blocked", blocked_reason="component blocked")
        if task.task_id == parent.task_id
        else task
        for task in part.ability_tasks
    ]

    calls, result = _run_wrapper(tasks, effects=part.effects)

    assert calls == []
    assert [node.status for node in result.node_results] == ["blocked"]
    assert "external_legacy_anim_wrapper_not_admitted" in (
        result.node_results[0].reason_code
    )


def test_runtime_never_executes_an_incomplete_child_ledger():
    part, parent = _ordered_wrapper_part()
    tasks = [
        replace(parent, child_task_ids=parent.child_task_ids[:-1])
        if task.task_id == parent.task_id
        else task
        for task in part.ability_tasks
    ]

    calls, result = _run_wrapper(tasks, effects=part.effects)

    assert calls == []
    assert [node.status for node in result.node_results] == ["blocked"]
    assert "anim_wrapper_child_ledger_count_mismatch" in (
        result.node_results[0].reason_code
    )


def test_runtime_never_executes_a_sibling_when_one_child_is_blocked():
    part, parent = _ordered_wrapper_part()
    first_child = next(
        task for task in part.ability_tasks if task.task_id == parent.child_task_ids[0]
    )
    tasks = [
        replace(first_child, coverage_status="blocked", blocked_reason="component child blocked")
        if task.task_id == first_child.task_id
        else task
        for task in part.ability_tasks
    ]

    calls, result = _run_wrapper(tasks, effects=part.effects)

    assert calls == []
    assert [node.status for node in result.node_results] == ["blocked"]
    assert "anim_wrapper_child_not_admitted" in result.node_results[0].reason_code


def test_runtime_never_executes_a_wrapper_without_its_effect_contract():
    part, parent = _ordered_wrapper_part()

    calls, result = _run_wrapper(part.ability_tasks, effects=())

    assert calls == []
    assert [node.status for node in result.node_results] == ["blocked"]
    assert "anim_wrapper_effect_missing" in result.node_results[0].reason_code

    # A blocked formal EffectIR has no blocked_reason attribute (only
    # link_blocked_reason and the standard payload reason). The contract must
    # report its coverage as an explicit reason instead of raising, and still
    # execute no child.
    blocked_effect = replace(
        next(
            effect
            for effect in part.effects
            if effect.effect_id == parent.effect_id
        ),
        coverage_status="blocked",
        link_blocked_reason="component:source_blocked",
    )
    effects = tuple(
        blocked_effect if effect.effect_id == parent.effect_id else effect
        for effect in part.effects
    )
    calls, result = _run_wrapper(part.ability_tasks, effects=effects)

    assert calls == []
    assert [node.status for node in result.node_results] == ["blocked"]
    assert result.node_results[0].reason_code.endswith(
        "anim_wrapper_effect_not_executable:blocked"
    )


def test_runtime_never_runs_children_of_a_process_only_wrapper():
    part, parent = _ordered_wrapper_part()
    tasks = [
        replace(parent, execution_mode="process_only")
        if task.task_id == parent.task_id
        else task
        for task in part.ability_tasks
    ]

    calls, result = _run_wrapper(tasks, effects=part.effects)

    assert calls == []
    assert [node.status for node in result.node_results] == ["blocked"]


# ---------------------------------------------------------------------------
# Damage semantics: AllTeammate is the caster's team without the caster, and
# ByMaxHP scales from the caster's own Max HP.
# ---------------------------------------------------------------------------


def test_all_teammate_excludes_the_living_caster_and_dead_teammates():
    state = BattleState(
        units={
            "caster": UnitState(
                "caster", "enemy", "component:caster", hp=1000.0, max_hp=1000.0
            ),
            "mate": UnitState(
                "mate", "enemy", "component:mate", hp=1000.0, max_hp=1000.0
            ),
            "dead_mate": UnitState(
                "dead_mate",
                "enemy",
                "component:dead",
                hp=0.0,
                max_hp=1000.0,
                lifecycle_status="defeated",
            ),
            "ally": UnitState(
                "ally", "ally", "component:ally", hp=1000.0, max_hp=1000.0
            ),
        }
    )

    targets = _damage_targets_for_emission(
        "all_teammate",
        TargetResolution(),
        state=state,
        attacker_id="caster",
    )

    assert targets == ("mate",)


def _dragonfish_basis():
    data = json.loads((TBGD / MONSTER_ABILITY).read_text())
    ability = next(
        entry
        for entry in data["AbilityList"]
        if entry["Name"].endswith("_SkillP01_Insert")
    )
    wrapper = next(
        task
        for task in ability["OnStart"]
        if task["$type"].endswith(".TriggerAnimStateWithMove")
    )
    attack = next(
        task
        for event in wrapper["EventList"]
        for task in event["TaskList"]
        if task["$type"].endswith(".DamageByAttackProperty")
    )
    source = IRSource(MONSTER_ABILITY, "ValidationComponent", "task", {"component_input": True})
    task = AbilityTaskIR(
        "task",
        "phase",
        "standalone:component",
        0,
        ability["Name"],
        "OnStart",
        0,
        "$.OnStart[5].EventList[2].TaskList[0]",
        "anim_event",
        "DamageByAttackProperty",
        source,
        effect_id="effect",
        coverage_status="executable",
    )
    effect = EffectIR(
        "effect", task.opcode, attack, source, coverage_status="executable"
    )
    profile = HitProfileIR(
        "profile",
        task.action_id,
        0,
        0,
        "all_teammate",
        numeric_fixed(0.4),
        {"raw_path": "ParamList[0]"},
        numeric_fixed(0),
        {},
        "direct",
        "Fire",
        source,
        coverage_status="executable",
    )
    binding = SkillFormulaBindingIR(
        "binding",
        "",
        "slot",
        task.action_id,
        0,
        0,
        0,
        "damage",
        "all_teammate",
        0.4,
        {
            "kind": "unit_stat",
            "unit_ref": "attacker",
            "stat": "max_hp",
            "dynamic_hash": 1246667513,
        },
        "",
        "",
        "",
        source,
        coverage_status="executable",
        data_card_id="component:card",
        data_card_kind="monster",
        owner_entity_ref="component:fish",
    )
    basis = _damage_scaling_basis_expr(
        task,
        effect,
        profile,
        {"by_key": {}, "by_task": {(task.action_id, 0, 0, task.task_id): binding}},
    )
    return task, basis, binding


def test_by_max_hp_scales_from_the_caster_for_two_different_target_max_hps():
    _task, basis, binding = _dragonfish_basis()

    assert basis["kind"] == "unit_stat"
    assert basis["stat"] == "max_hp"
    assert basis["formula_type"] == "ByMaxHP"
    assert basis["unit_ref"] == "attacker"

    fish = UnitState(
        "fish", "enemy", "component:fish", level=80, hp=2000.0, max_hp=2000.0
    )
    owner = UnitState(
        "owner", "enemy", "component:owner", level=80, hp=20000.0, max_hp=20000.0
    )
    target_a = UnitState(
        "target_a", "ally", "component:a", level=80, hp=5000.0, max_hp=5000.0
    )
    target_b = UnitState(
        "target_b", "ally", "component:b", level=80, hp=8000.0, max_hp=8000.0
    )
    state = BattleState(
        units={
            "fish": fish,
            "owner": owner,
            "target_a": target_a,
            "target_b": target_b,
        }
    )
    definition = ActionDefinitionIR(
        definition_id="component:action",
        action_id="standalone_ability:component",
        level=1,
        attack_type="Normal",
        skill_effect="SingleAttack",
        target_mode="Single",
        bp_need=0.0,
        bp_add=0.0,
        sp_base=0.0,
        sp_multiple_ratio=0.0,
        param_list=(),
        show_stance_list=(),
        show_damage_list=(),
        stance_damage_type="Fire",
        source=IRSource("component", "validation", "action"),
        coverage_status="executable",
    )
    formula = DirectDamageFormula()
    results = {
        target_id: formula.calculate(
            DamageFormulaInput(
                state=state,
                attacker_id="fish",
                target_id=target_id,
                action_definition=definition,
                attack_type="Normal",
                element_type="Fire",
                scaling_ratio=binding.param_value,
                scaling_basis=basis,
                crit_mode="noncrit",
            )
        )
        for target_id in ("target_a", "target_b")
    }

    # Distinct target Max HP: the basis must stay on the caster's own panel.
    assert fish.max_hp != owner.max_hp
    assert target_a.max_hp != target_b.max_hp
    assert results["target_a"].scaling_value == 2000.0
    assert results["target_b"].scaling_value == 2000.0
    assert results["target_a"].base_damage == pytest.approx(2000.0 * 0.4)
    assert results["target_b"].base_damage == pytest.approx(2000.0 * 0.4)
    assert results["target_a"].final_damage == pytest.approx(
        results["target_b"].final_damage
    )
    assert results["target_a"].final_damage != pytest.approx(5000.0 * 0.4)
    assert results["target_b"].final_damage != pytest.approx(8000.0 * 0.4)
