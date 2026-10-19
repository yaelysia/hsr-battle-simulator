"""继承绑定的作用域、唯一性、顺序无关与终止性契约。

组件输入（fixture 图/任务/声明）在用例中明确标注；生产者与消费者均调用正式实现。
"""
from dataclasses import replace

from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR, EffectIR, IRSource, SkillFormulaBindingIR, StandaloneAbilityGraphIR,
)
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _direct_basis_binding, _direct_damage_binding_lookup, _effect_payload,
    _link_trigger_ability_graphs, _lower_standalone_hit_profiles,
    _project_standalone_skill_formula_bindings, _standalone_binding_for_damage_task,
)

SOURCE = IRSource("fixture/ability", "StandaloneAbilityList", "shared", {})
INHERITANCE_HASH = "836547932"


def _damage_effect(effect_id, hash_value=INHERITANCE_HASH):
    return EffectIR(effect_id, "DamageByAttackProperty", _effect_payload(
        {"$type": "RPG.GameCore.DamageByAttackProperty",
         "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "ParamEntity"},
         "AttackProperty": {
             "$type": "RPG.GameCore.AttackData",
             "AttackType": "Insert",
             "DamagePercentage": {"IsDynamic": True, "PostfixExpr": {
                 "OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [int(hash_value)]}},
         }}, "DamageByAttackProperty", "", source=SOURCE), SOURCE)


def _damage_task(ability, index, effect_id):
    return AbilityTaskIR("task:%s:%d" % (ability, index), "phase:%s" % ability,
                         "standalone_ability:%s" % ability, 0, ability, "OnStart", index,
                         "$.AbilityList[%s].OnStart[%d]" % (ability, index), "root",
                         "DamageByAttackProperty", SOURCE, effect_id=effect_id,
                         coverage_status="executable")


def _trigger_task(ability, index, child):
    return AbilityTaskIR("trigger:%s:%d" % (ability, index), "phase:%s" % ability,
                         "standalone_ability:%s" % ability, 0, ability, "OnStart", index,
                         "$.AbilityList[%s].OnStart[%d]" % (ability, index), "root",
                         "TriggerAbility", SOURCE,
                         effect_id="trigger-effect:%s:%d" % (ability, index),
                         coverage_status="executable",
                         linked_standalone_graph_id="graph:%s" % child)


def _trigger_effect(ability, index, child):
    return EffectIR("trigger-effect:%s:%d" % (ability, index), "TriggerAbility",
                    _effect_payload({"$type": "RPG.GameCore.TriggerAbility",
                                     "AbilityName": {"Value": child}}, "TriggerAbility",
                                    "", source=SOURCE), SOURCE)


def _graph(ability, task_ids):
    return StandaloneAbilityGraphIR("graph:%s" % ability, ability, "mainline_avatar",
                                    ("phase:%s" % ability,), tuple(task_ids), tuple(task_ids),
                                    SOURCE)


def _declaration(action_id, raw_id, hash_value=INHERITANCE_HASH, *, path="fixture/skill",
                 stat="attack", binding_id=None):
    return SkillFormulaBindingIR(
        binding_id=binding_id or "parent:%s" % raw_id, character_data_card_id="card",
        data_card_id="card", data_card_kind="", owner_entity_ref="",
        formula_slot_id="slot:%s" % raw_id, action_id=action_id, level=0, param_index=3,
        sequence_order=0, formula_role="direct_damage", target_group_hint="", param_value=1.0,
        scaling_basis_expr={"kind": "unit_stat", "unit_ref": "attacker", "stat": stat,
                            "admission_status": "executable", "dynamic_hash": hash_value},
        text_hash="", skill_text="", matched_text="fixture",
        source=IRSource(path, "AvatarSkillConfig", raw_id,
                        {"source_id": "fixture", "row_index": 0, "level": 1}),
        coverage_status="executable", blocked_reason="")


def _chain(*abilities):
    """Component input: A -> B -> ... chain; each ability hits the same parameter.

    The first ability owns the parameter; later abilities only trigger the next
    one and hit the inherited parameter in their own damage task.
    """
    tasks, effects, graphs, damage_task_ids = [], [], [], {}
    for position, ability in enumerate(abilities):
        child = abilities[position + 1] if position + 1 < len(abilities) else None
        ability_tasks = []
        if child is not None:
            trigger = _trigger_task(ability, 0, child)
            ability_tasks.append(trigger)
            tasks.append(trigger)
            effects.append(_trigger_effect(ability, 0, child))
        damage = _damage_task(ability, len(ability_tasks), "effect:%s" % ability)
        damage_task_ids[ability] = damage.task_id
        ability_tasks.append(damage)
        tasks.append(damage)
        effects.append(_damage_effect("effect:%s" % ability))
        graphs.append(_graph(ability, [task.task_id for task in ability_tasks]))
    return tasks, effects, graphs, damage_task_ids


def test_multiple_child_tasks_of_one_hash_each_own_binding():
    tasks, effects, graphs, damage_ids = _chain("A", "B")
    declaration = _declaration("standalone_ability:A", damage_ids["A"])
    linked = _link_trigger_ability_graphs(tasks, effects, graphs, [])
    second = _damage_task("B", 1, "effect:B:second")
    effects = [*effects, _damage_effect("effect:B:second")]
    linked = [*linked, second]
    inherited = _project_standalone_skill_formula_bindings(linked, effects, [declaration])
    materialized = [binding for binding in inherited
                    if binding.source.evidence.get("child_task_id")
                    in {damage_ids["B"], second.task_id}]
    assert {binding.source.raw_id for binding in materialized} == {
        damage_ids["B"], second.task_id}
    for binding in materialized:
        assert binding.action_id == "standalone_ability:B"
        assert binding.scaling_basis_expr["dynamic_hash"] == INHERITANCE_HASH
    assert len({binding.binding_id for binding in materialized}) == 2


def test_own_binding_is_reused_before_inherited_copy():
    declaration = _declaration("standalone_ability:B", "task:B:0")
    inherited = replace(declaration,
                        binding_id="skill_formula_binding:standalone_ability:B:0:direct_damage"
                                   ":hash:%s:task:task_B_0" % INHERITANCE_HASH,
                        source=IRSource("fixture/ability",
                                        "StandaloneSkillFormulaBindingProjection", "task:B:0",
                                        {"projection_kind":
                                         "trigger_ability_parameter_inheritance",
                                         "child_task_id": "task:B:0",
                                         "dynamic_hash": INHERITANCE_HASH}))
    own = replace(declaration, binding_id="own:task:B:0",
                  source=IRSource("fixture/skill", "CharacterQueuedSkillParam", "task:B:0",
                                  {"dynamic_hash": INHERITANCE_HASH}))
    task = _damage_task("B", 0, "effect:B")
    effect = _damage_effect("effect:B")
    for order in ((own, inherited), (inherited, own)):
        assert _standalone_binding_for_damage_task(order, effect).binding_id == "own:task:B:0"
        lookup = _direct_damage_binding_lookup(list(order), [task])
        assert _direct_basis_binding(lookup, task, 3).binding_id == "own:task:B:0"


def test_conflicting_inherited_declarations_are_refused_order_independently():
    tasks, effects, graphs, damage_ids = _chain("A", "B")
    linked = _link_trigger_ability_graphs(tasks, effects, graphs, [])
    declaration = _declaration("standalone_ability:A", damage_ids["A"])
    conflicting = _declaration("standalone_ability:A", damage_ids["A"],
                               path="fixture/other_skill", stat="defense",
                               binding_id="parent:conflicting")
    for inputs in ([declaration, conflicting], [conflicting, declaration]):
        inherited = _project_standalone_skill_formula_bindings(linked, effects, list(inputs))
        assert not [binding for binding in inherited
                    if binding.source.evidence.get("child_task_id") == damage_ids["B"]]
        profiles = _lower_standalone_hit_profiles([_damage_task("B", 0, "effect:B")],
                                                  effects, inherited, {})
        assert profiles[0].coverage_status == "blocked"
        assert profiles[0].blocked_reason == "standalone_damage_skill_formula_binding_missing"
    forward = _project_standalone_skill_formula_bindings(linked, effects, [declaration])
    backward = _project_standalone_skill_formula_bindings(
        list(reversed(linked)), list(reversed(effects)), [declaration])
    assert [binding.binding_id for binding in forward] == [
        binding.binding_id for binding in backward]
    assert {binding.source.raw_id for binding in forward} == {damage_ids["B"]}


def test_propagation_cycle_terminates_and_depth_limit_keeps_refusal():
    tasks, effects, graphs, damage_ids = _chain("A", "B")
    back = _trigger_task("B", 2, "A")
    tasks = [*tasks, back]
    effects = [*effects, _trigger_effect("B", 2, "A")]
    declaration = _declaration("standalone_ability:A", damage_ids["A"])
    linked = _link_trigger_ability_graphs(tasks, effects, graphs, [])
    inherited = _project_standalone_skill_formula_bindings(linked, effects, [declaration])
    assert {binding.source.raw_id for binding in inherited} == {damage_ids["B"]}
    # Depth limit: a consumer beyond the supported propagation depth stays
    # without a binding instead of a partial admit.
    deep_tasks, deep_effects, deep_graphs, deep_ids = _chain("A", "H1", "H2", "H3", "H4", "C")
    deep_linked = _link_trigger_ability_graphs(deep_tasks, deep_effects, deep_graphs, [])
    deep_inherited = _project_standalone_skill_formula_bindings(
        deep_linked, deep_effects, [declaration])
    assert {binding.source.raw_id for binding in deep_inherited} == {
        deep_ids["H1"], deep_ids["H2"], deep_ids["H3"], deep_ids["H4"]}
