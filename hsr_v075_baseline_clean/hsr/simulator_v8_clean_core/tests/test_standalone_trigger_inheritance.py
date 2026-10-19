"""TriggerAbility 参数继承只落到具体子伤害任务，缺失或多主基准仍拒绝。"""
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR, CharacterAbilityDefinitionIR, CharacterDataCardIR, EffectIR, IRSource,
    SkillFormulaBindingIR, StandaloneAbilityGraphIR,
)
from hsr.simulator_v8_clean_core.tbgd.character_cards import skill_formula_bindings_from_row
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _action_definition_from_row, _bind_character_queue_damage, _direct_basis_binding,
    _direct_damage_binding_lookup, _dynamic_value_bindings, _effect_payload,
    _link_trigger_ability_graphs, _lower_standalone_hit_profiles,
    _project_standalone_skill_formula_bindings,
)

ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
SKILL_PATH = "ExcelOutput/AvatarSkillConfig.json"
ABILITY_PATH = "Config/ConfigAbility/Avatar/Avatar_Hook_00_Ability.json"
CONFIG_PATH = "Config/ConfigCharacter/Avatar/Avatar_Hook_00_Config.json"
AVATAR_ID = "1109"
PARENT_ABILITY = "Avatar_Hook_00_SkillMazeInLevel"
CHILD_ABILITY = "Avatar_Hook_00_PassiveSkill01_2"


def _walk(node, path, out):
    if isinstance(node, dict):
        value_type = str(node.get("$type", ""))
        opcode = value_type.split(".")[-1] if value_type.startswith("RPG.GameCore.") else ""
        if opcode == "TriggerAbility":
            out.append((path, node, opcode))
        elif "DamageByAttackProperty" in opcode:
            out.append((path, node, "DamageByAttackProperty"))
        for key, value in node.items():
            _walk(value, path + "." + key, out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, path + "[%d]" % index, out)


def _compile_hook():
    content = (ROOT / ABILITY_PATH).read_bytes()
    data = json.loads(content)
    config = json.loads((ROOT / CONFIG_PATH).read_text())
    avatar = next(row for row in json.loads((ROOT / "ExcelOutput/AvatarConfig.json").read_text())
                  if str(row["AvatarID"]) == AVATAR_ID)
    skill_ids = tuple(str(skill_id) for skill_id in avatar.get("SkillList") or ())
    rows = [(index, row) for index, row in enumerate(json.loads((ROOT / SKILL_PATH).read_text()))
            if str(row.get("SkillID")) in skill_ids]
    text_map = json.loads((ROOT / "TextMap/TextMapCHS.json").read_text())
    definitions = [_action_definition_from_row(SKILL_PATH, "avatar_skill", "SkillID", index, row)
                   for index, row in rows]
    bindings = [binding for index, row in rows for binding in skill_formula_bindings_from_row(
        relative_path=SKILL_PATH, entity_type="avatar_skill", id_key="SkillID", row_index=index,
        row=row, text_map=text_map, skill_to_card={str(row["SkillID"]): "card"})]
    source = IRSource(ABILITY_PATH, "StandaloneAbilityList", "shared", {})
    card = CharacterDataCardIR("card", "avatar:%s" % AVATAR_ID, "profile", skill_ids,
        tuple(binding.binding_id for binding in bindings), (), source,
        dynamic_value_bindings=_dynamic_value_bindings(config["DynamicValues"]))
    digest = hashlib.sha256(content).hexdigest()
    graphs, tasks, effects, ability_definitions = [], [], [], []
    for ability_index, ability in enumerate(data["AbilityList"]):
        name = ability.get("Name")
        if not isinstance(name, str):
            continue
        found = []
        _walk(ability, "", found)
        phase_id = "phase:%d" % ability_index
        task_ids = []
        for task_index, (path, node, opcode) in enumerate(found):
            task_id = "task:%d:%d" % (ability_index, task_index)
            effect_id = "effect:%d:%d" % (ability_index, task_index)
            task_ids.append(task_id)
            tasks.append(AbilityTaskIR(task_id, phase_id, "standalone_ability:%s" % name, 0, name,
                "OnStart", task_index, "$.AbilityList[%d]%s" % (ability_index, path), "root",
                opcode, source, effect_id=effect_id, coverage_status="executable"))
            effects.append(EffectIR(effect_id, opcode,
                _effect_payload(node, opcode, "", source=source), source))
        if task_ids:
            graphs.append(StandaloneAbilityGraphIR("graph:%d" % ability_index, name,
                "mainline_avatar", (phase_id,), tuple(task_ids), tuple(task_ids), source))
        ability_source = IRSource(ABILITY_PATH, "AbilityList", name, {
            "source_id": "source", "source_kind": "character_main", "avatar_id": AVATAR_ID,
            "json_path": "$.AbilityList[%d]" % ability_index, "ability_index": ability_index,
            "content_sha256": digest,
        })
        ability_definitions.append(CharacterAbilityDefinitionIR("def:%d" % ability_index,
            "source", AVATAR_ID, name, "character_main", ability_source))
    return {
        "graphs": graphs, "tasks": tasks, "effects": effects, "bindings": bindings,
        "definitions": definitions, "card": card, "ability_definitions": ability_definitions,
    }


def _hook_inheritance_fixture(child_effect):
    """Compile the real Hook pair, with a component hit request for the child.

    The maze ability owns the parameter and the passive ability is compiled
    without its own card projection (as for a card-less common ability), so the
    only formal binding source for the child hit is the TriggerAbility
    inheritance.
    """
    fixture = _compile_hook()
    tasks = fixture["tasks"]
    parent_graph = next(graph for graph in fixture["graphs"]
                        if graph.ability_name == PARENT_ABILITY)
    updated, projected = _bind_character_queue_damage(
        [parent_graph], tasks, fixture["effects"], fixture["bindings"],
        fixture["definitions"], [fixture["card"]], fixture["ability_definitions"])
    linked = _link_trigger_ability_graphs(tasks, fixture["effects"], fixture["graphs"], [])
    parent_damage = next(task for task in linked
                         if task.ability_name == PARENT_ABILITY
                         and task.opcode == "DamageByAttackProperty")
    child_damage = next(task for task in linked
                        if task.ability_name == CHILD_ABILITY
                        and task.opcode == "DamageByAttackProperty")
    effects_by_id = {effect.effect_id: effect for effect in fixture["effects"]}
    parent_effect = effects_by_id[parent_damage.effect_id]
    child_hit = replace(parent_effect, effect_id=child_damage.effect_id) if child_effect is None \
        else replace(child_effect, effect_id=child_damage.effect_id)
    effects = [effect for effect in fixture["effects"] if effect.effect_id != child_damage.effect_id]
    effects.append(child_hit)
    inherited = _project_standalone_skill_formula_bindings(
        linked, effects, [*fixture["bindings"], *projected])
    return {
        "linked": linked, "effects": effects, "inherited": inherited,
        "parent_damage": parent_damage, "child_damage": child_damage,
        "parent_binding": projected[0],
    }


def test_trigger_ability_inheritance_projects_to_concrete_child_task():
    fixture = _hook_inheritance_fixture(child_effect=None)
    parent_binding = fixture["parent_binding"]
    dynamic_hash = parent_binding.scaling_basis_expr["dynamic_hash"]
    child_task = fixture["child_damage"]
    inherited = [binding for binding in fixture["inherited"]
                 if binding.source.evidence.get("child_task_id") == child_task.task_id]
    assert len(inherited) == 1
    inherited_binding = inherited[0]
    assert inherited_binding.action_id == child_task.action_id
    assert inherited_binding.source.raw_id == child_task.task_id
    assert inherited_binding.scaling_basis_expr["dynamic_hash"] == dynamic_hash
    assert inherited_binding.source.evidence["source_trigger_task_id"]
    assert inherited_binding.source.evidence["parent_action_id"] == parent_binding.action_id
    profiles = _lower_standalone_hit_profiles([child_task], fixture["effects"],
                                              [inherited_binding], {})
    assert profiles[0].coverage_status == "executable", profiles[0].blocked_reason
    assert profiles[0].multiplier_source["skill_formula_binding_id"] == inherited_binding.binding_id
    # The inherited binding belongs to that child task only: the parent's own
    # damage task cannot borrow it.
    foreign = _lower_standalone_hit_profiles([fixture["parent_damage"]], fixture["effects"],
                                             [inherited_binding], {})
    assert foreign[0].coverage_status == "blocked"
    assert foreign[0].blocked_reason == "standalone_damage_skill_formula_binding_missing"


def test_compound_child_hit_does_not_borrow_inherited_binding():
    topaz = json.loads((ROOT / "Config/ConfigAbility/Avatar/Avatar_Topaz_00_Ability.json")
                       .read_text())["AbilityList"][17]["OnStart"][7]
    compound_hit = EffectIR("effect", "DamageByAttackProperty",
        _effect_payload(topaz, "DamageByAttackProperty", "",
                        source=IRSource("Config/ConfigAbility/Avatar/Avatar_Topaz_00_Ability.json",
                                        "AbilityList", "shared", {})),
        IRSource("Config/ConfigAbility/Avatar/Avatar_Topaz_00_Ability.json",
                 "AbilityList", "shared", {}))
    fixture = _hook_inheritance_fixture(child_effect=compound_hit)
    child_task = fixture["child_damage"]
    assert not [binding for binding in fixture["inherited"]
                if binding.source.evidence.get("child_task_id") == child_task.task_id]
    profiles = _lower_standalone_hit_profiles([child_task], fixture["effects"],
                                              fixture["inherited"], {})
    assert profiles[0].coverage_status == "blocked"
    assert profiles[0].blocked_reason == "standalone_damage_skill_formula_binding_missing"


def test_direct_basis_lookup_resolves_each_task_binding():
    source = IRSource("fixture", "X", "x", {"content_sha256": "c" * 64})
    task_one = AbilityTaskIR("task:one", "phase", "standalone_ability:child", 0, "child",
                             "OnStart", 0, "$.x[0]", "root", "DamageByAttackProperty", source,
                             coverage_status="executable")
    task_two = replace(task_one, task_id="task:two", task_path="$.x[1]",
                       effect_id="effect:two")
    bindings = [
        SkillFormulaBindingIR("binding:one", "card", "slot:one", task_one.action_id, 0, 3, 0,
            "direct_damage", "selected", 0.5,
            {"kind": "unit_stat", "unit_ref": "attacker", "stat": "attack",
             "dynamic_hash": "111", "admission_status": "executable"},
            "", "", "", replace(source, raw_id="task:one"), coverage_status="executable"),
        SkillFormulaBindingIR("binding:two", "card", "slot:two", task_two.action_id, 0, 3, 0,
            "direct_damage", "selected", 0.6,
            {"kind": "unit_stat", "unit_ref": "attacker", "stat": "defense",
             "dynamic_hash": "222", "admission_status": "executable"},
            "", "", "", replace(source, raw_id="task:two"), coverage_status="executable"),
    ]
    lookup = _direct_damage_binding_lookup(bindings, [task_one, task_two])
    assert _direct_basis_binding(lookup, task_one, 3).binding_id == "binding:one"
    assert _direct_basis_binding(lookup, task_two, 3).binding_id == "binding:two"


def test_parameter_propagation_passes_through_intermediate_ability():
    """A damage ability passes its parameter through a trigger-only ability."""
    fixture = _compile_hook()
    tasks = fixture["tasks"]
    effects = fixture["effects"]
    graphs = fixture["graphs"]
    parent_graph = next(graph for graph in graphs if graph.ability_name == PARENT_ABILITY)
    updated, projected = _bind_character_queue_damage(
        [parent_graph], tasks, effects, fixture["bindings"], fixture["definitions"],
        [fixture["card"]], fixture["ability_definitions"])
    parent_binding = projected[0]
    dynamic_hash = parent_binding.scaling_basis_expr["dynamic_hash"]
    linked = _link_trigger_ability_graphs(tasks, effects, graphs, [])
    middle_name = "Avatar_Hook_00_Skill01_Phase01"
    grandchild_name = "Avatar_Hook_00_Skill01_Phase02"
    middle_graph = next(graph for graph in graphs if graph.ability_name == middle_name)
    parent_trigger = next(task for task in linked
                          if task.ability_name == PARENT_ABILITY
                          and task.opcode == "TriggerAbility")
    middle_effects = {effect.effect_id: effect for effect in effects}
    parent_trigger_effect = middle_effects[parent_trigger.effect_id]
    # Component input: point the real parent trigger at the real trigger-only
    # middle ability so the formal chain becomes parent -> middle -> grandchild.
    redirected_effect = replace(parent_trigger_effect, effect_id="effect:redirected", payload={
        **parent_trigger_effect.payload,
        "standard": {**parent_trigger_effect.payload["standard"], "ability_name": middle_name},
    })
    redirected_trigger = replace(parent_trigger, task_id="task:redirected",
                                 effect_id="effect:redirected",
                                 linked_standalone_graph_id=middle_graph.standalone_ability_graph_id)
    effects_with_redirect = [effect for effect in effects
                             if effect.effect_id != parent_trigger.effect_id]
    effects_with_redirect.append(redirected_effect)
    linked_with_redirect = [task for task in linked if task.task_id != parent_trigger.task_id]
    linked_with_redirect.append(redirected_trigger)
    grandchild_damage = next(task for task in linked_with_redirect
                             if task.ability_name == grandchild_name
                             and task.opcode == "DamageByAttackProperty")
    # Component input: the grandchild hit consumes the parent parameter.
    grandchild_hit = replace(effects_by_id_of(effects_with_redirect)[grandchild_damage.effect_id],
                             effect_id=grandchild_damage.effect_id)
    parent_damage_effect = effects_by_id_of(effects_with_redirect)[
        next(task for task in linked_with_redirect
             if task.ability_name == PARENT_ABILITY
             and task.opcode == "DamageByAttackProperty").effect_id]
    effects_with_redirect = [effect for effect in effects_with_redirect
                             if effect.effect_id != grandchild_damage.effect_id]
    effects_with_redirect.append(replace(parent_damage_effect,
                                         effect_id=grandchild_damage.effect_id))
    inherited = _project_standalone_skill_formula_bindings(
        linked_with_redirect, effects_with_redirect, [*fixture["bindings"], *projected])
    materialized = [binding for binding in inherited
                    if binding.source.evidence.get("child_task_id") == grandchild_damage.task_id]
    assert len(materialized) == 1
    assert materialized[0].source.raw_id == grandchild_damage.task_id
    assert materialized[0].scaling_basis_expr["dynamic_hash"] == dynamic_hash
    assert materialized[0].source.evidence["source_trigger_task_id"] == "task:0:1"
    assert materialized[0].source.evidence["parent_action_id"] == (
        "standalone_ability:%s" % middle_name)
    assert materialized[0].source.evidence["source_binding_id"] == parent_binding.binding_id
    # The trigger-only middle ability forwards the parameter but owns no
    # materialized binding of its own.
    assert not [binding for binding in inherited
                if binding.source.evidence.get("child_action_id")
                == "standalone_ability:%s" % middle_name]
    profiles = _lower_standalone_hit_profiles([grandchild_damage], effects_with_redirect,
                                              materialized, {})
    assert profiles[0].coverage_status == "executable", profiles[0].blocked_reason


def effects_by_id_of(effects):
    return {effect.effect_id: effect for effect in effects}
