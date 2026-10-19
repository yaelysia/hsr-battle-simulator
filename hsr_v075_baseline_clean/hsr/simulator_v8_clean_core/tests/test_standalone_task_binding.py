"""独立复合伤害逐任务绑定倍率、基准、等级、目标与削韧来源。"""
import hashlib
import json
from pathlib import Path

from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hashes
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR, CharacterAbilityDefinitionIR, CharacterDataCardIR, EffectIR, IRSource,
    StandaloneAbilityGraphIR,
)
from hsr.simulator_v8_clean_core.rules.value_binding import resolve_runtime_numeric_expression
from hsr.simulator_v8_clean_core.tbgd.character_cards import skill_formula_bindings_from_row
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _action_definition_from_row, _admit_damage_ability_tasks, _bind_character_queue_damage,
    _damage_percentage_dynamic_hash, _dynamic_value_bindings, _effect_payload,
    _lower_damage_emissions, _lower_standalone_hit_profiles, _lower_toughness_emissions,
    _numeric_expr_summary, _skill_param_numeric_binding_source, _value_field,
)

ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
SKILL_PATH = "ExcelOutput/AvatarSkillConfig.json"


def _walk_damage_tasks(node, path, out):
    if isinstance(node, dict):
        if str(node.get("$type", "")).endswith("DamageByAttackProperty"):
            out.append((path, node))
        for key, value in node.items():
            _walk_damage_tasks(value, path + "." + key, out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_damage_tasks(value, path + "[%d]" % index, out)


def _compile(ability_file, ability_name, avatar_id):
    """Compile one real multi-task standalone ability through the formal chain."""
    config_rel = "Config/ConfigCharacter/Avatar/%s_Config.json" % ability_file
    ability_rel = "Config/ConfigAbility/Avatar/%s_Ability.json" % ability_file
    config = json.loads((ROOT / config_rel).read_text())
    content = (ROOT / ability_rel).read_bytes()
    data = json.loads(content)
    avatar_row = next(row for row in json.loads((ROOT / "ExcelOutput/AvatarConfig.json").read_text())
                      if str(row["AvatarID"]) == avatar_id)
    skill_ids = tuple(str(skill_id) for skill_id in avatar_row.get("SkillList") or ())
    rows = [(index, row) for index, row in enumerate(json.loads((ROOT / SKILL_PATH).read_text()))
            if str(row.get("SkillID")) in skill_ids]
    text_map = json.loads((ROOT / "TextMap/TextMapCHS.json").read_text())
    definitions = [_action_definition_from_row(SKILL_PATH, "avatar_skill", "SkillID", index, row)
                   for index, row in rows]
    bindings = [binding for index, row in rows for binding in skill_formula_bindings_from_row(
        relative_path=SKILL_PATH, entity_type="avatar_skill", id_key="SkillID", row_index=index,
        row=row, text_map=text_map, skill_to_card={str(row["SkillID"]): "card"})]
    ability_index, ability = next((index, item) for index, item in enumerate(data["AbilityList"])
                                  if item.get("Name") == ability_name)
    source = IRSource(ability_rel, "StandaloneAbilityList", "shared", {})
    card = CharacterDataCardIR("card", "avatar:%s" % avatar_id, "profile", skill_ids,
        tuple(binding.binding_id for binding in bindings), (), source,
        dynamic_value_bindings=_dynamic_value_bindings(config["DynamicValues"]))
    ability_source = IRSource(ability_rel, "AbilityList", ability_name, {
        "source_id": "source", "source_kind": "character_main", "avatar_id": avatar_id,
        "json_path": "$.AbilityList[%d]" % ability_index, "ability_index": ability_index,
        "content_sha256": hashlib.sha256(content).hexdigest(),
    })
    definition = CharacterAbilityDefinitionIR("def", "source", avatar_id, ability_name,
        "character_main", ability_source)
    found = []
    _walk_damage_tasks(ability, "", found)
    tasks, effects, task_ids = [], [], []
    for task_index, (path, node) in enumerate(found):
        task_id = "task:%d" % task_index
        task_ids.append(task_id)
        tasks.append(AbilityTaskIR(task_id, "phase", "standalone_ability:%s" % ability_name, 0,
            ability_name, "OnStart", 0, "$.AbilityList[%d]%s" % (ability_index, path), "root",
            "DamageByAttackProperty", source, effect_id="effect:%d" % task_index,
            coverage_status="executable"))
        effects.append(EffectIR("effect:%d" % task_index, "DamageByAttackProperty",
            _effect_payload(node, "DamageByAttackProperty", "", source=source), source))
    graph = StandaloneAbilityGraphIR("graph", ability_name, "mainline_avatar", ("phase",),
        tuple(task_ids), tuple(task_ids), source)
    updated, projected = _bind_character_queue_damage([graph], tasks, effects, bindings,
        definitions, [card], [definition])
    action_definitions = {action.action_id: action for action in definitions}
    profiles = _lower_standalone_hit_profiles(tasks, effects, projected, action_definitions)
    damage = _lower_damage_emissions(tasks, effects, profiles, projected, {})
    toughness = _lower_toughness_emissions(tasks, effects, profiles, projected)
    admitted = {task.task_id: task for task in _admit_damage_ability_tasks(
        tasks, damage, toughness, profiles)}
    return {
        "graph": updated[0], "projected": projected, "tasks": tasks, "effects": effects,
        "profiles": profiles, "damage": damage, "toughness": toughness, "admitted": admitted,
        "definitions": definitions, "config": config, "config_rel": config_rel, "rows": rows,
    }


def test_ashveil_insert_enhance_binds_each_task_independently():
    # Real source: the success branch reads the talent parameter while the
    # failed branch reads the ultimate parameter of the same ability.
    bundle = _compile("Avatar_Ashveil_00", "Avatar_Ashveil_00_Insert_Enhance", "1504")
    projected = bundle["projected"]
    tasks = {task.task_id: task for task in bundle["tasks"]}
    assert set(tasks) == {"task:0", "task:1"}
    assert {binding.source.raw_id for binding in projected} == set(tasks)
    by_task = {binding.source.raw_id: binding for binding in projected}
    assert by_task["task:0"].source.evidence["action_id"] == "avatar_skill:150404"
    assert by_task["task:1"].source.evidence["action_id"] == "avatar_skill:150403"
    for task_id, binding in by_task.items():
        evidence = binding.source.evidence
        reads = evidence["parameter_reads"]
        assert set(reads) == {binding.scaling_basis_expr["dynamic_hash"]}
        assert evidence["task_source"] == tasks[task_id].source.to_json()
        assert evidence["skill_formula_binding_source"]
        assert evidence["level_selection"] == "assembled_character_effective_skill_level"
        assert binding.scaling_basis_expr["stat"] == "attack"
        assert binding.scaling_basis_expr["attack_type"] == "Insert"
    # Each task carries its own target selection and its own stance action.
    profiles = {profile.target_selection_policy["task_id"]: profile for profile in bundle["profiles"]}
    assert set(profiles) == set(tasks)
    assert all(profile.target_group == "selected" for profile in profiles.values())
    assert profiles["task:0"].stance_expr["value"] == 15
    assert profiles["task:1"].stance_expr["value"] == 90
    assert profiles["task:0"].stance_source["raw_path"] == "ShowStanceList[0]"
    assert profiles["task:1"].stance_source["raw_path"] == "ShowStanceList[0]"
    for task_id, action_id in (("task:0", "avatar_skill:150404"), ("task:1", "avatar_skill:150403")):
        action_sources = [action.source.to_json() for action in bundle["definitions"]
                          if action.action_id == action_id]
        assert profiles[task_id].stance_source["source"] in action_sources
    toughness = {emission.source_task_id: emission for emission in bundle["toughness"]}
    assert toughness["task:0"].coverage_status == "executable"
    assert toughness["task:0"].toughness_amount_expr["binding_source"]["values"]["1659254037"] == 15
    # The failed branch omits StanceValue: its missing toughness binding blocks
    # that task atomically instead of defaulting to the display stance table.
    assert toughness["task:1"].blocked_reason == "attack_property_stance_value_missing"
    assert bundle["admitted"]["task:0"].coverage_status == "executable"
    assert bundle["admitted"]["task:1"].coverage_status == "blocked"
    assert "attack_property_stance_value_missing" in bundle["admitted"]["task:1"].blocked_reason
    assert all(emission.coverage_status != "executable" for emission in bundle["damage"]
               if emission.source_task_id == "task:1")
    # Skill levels stay independent: each multiplier only follows its own skill.
    def values_at(talent_level, ultimate_level):
        selected = {row["SkillTriggerKey"]: row for _, row in bundle["rows"]
                    if row["Level"] == (talent_level if row["SkillTriggerKey"] == "SkillP01"
                                        else ultimate_level)}
        source_binding, _ = _skill_param_numeric_binding_source(
            character_config=bundle["config"], skill_row=selected["SkillP01"],
            skill_trigger_key="SkillP01", character_path=bundle["config_rel"],
            skill_rows_by_trigger_key=selected)
        results = []
        for task_id in ("task:0", "task:1"):
            expression = next(profile.multiplier_expr for profile in bundle["profiles"]
                              if profile.target_selection_policy["task_id"] == task_id)
            value = resolve_runtime_numeric_expression(expression,
                binding_sources=(source_binding,), source_trace={})
            assert value.ok, value.to_json()
            results.append(value.value)
        return tuple(results)

    base = values_at(1, 1)
    assert values_at(1, 2)[0] == base[0]
    assert values_at(2, 1)[1] == base[1]

    def param_by_level(trigger_key, index):
        result = {}
        for _, row in bundle["rows"]:
            if row["SkillTriggerKey"] == trigger_key:
                result[row["Level"]] = _value_field(
                    next(action for action in bundle["definitions"]
                         if action.action_id.removeprefix("avatar_skill:") == str(row["SkillID"])
                         and action.level == row["Level"]).param_list[index])
        return result

    talent_params = param_by_level("SkillP01", 3)
    ultimate_params = param_by_level("Skill03", 3)
    talent_pair = next(pair for pair in ((a, b) for a in talent_params for b in talent_params)
                       if talent_params[pair[0]] != talent_params[pair[1]])
    ultimate_pair = next(pair for pair in ((a, b) for a in ultimate_params for b in ultimate_params)
                         if ultimate_params[pair[0]] != ultimate_params[pair[1]])
    assert values_at(talent_pair[0], 1)[0] != values_at(talent_pair[1], 1)[0]
    assert values_at(1, ultimate_pair[0])[1] != values_at(1, ultimate_pair[1])[1]


def test_hook_skill21_phase02_tasks_block_without_cross_task_leakage():
    # Real source: Skill21 primary/adjacent hits and the talent's additional
    # damage in one standalone ability.
    bundle = _compile("Avatar_Hook_00", "Avatar_Hook_00_Skill21_Phase02", "1109")
    projected = bundle["projected"]
    assert {binding.source.raw_id for binding in projected} == {"task:2"}
    binding = projected[0]
    assert binding.source.evidence["action_id"] == "avatar_skill:110904"
    assert binding.source.evidence["original_formula_role"] == "additional_damage"
    assert binding.scaling_basis_expr["attack_type"] == "Pursued"
    admitted = bundle["admitted"]
    assert admitted["task:2"].coverage_status == "executable", admitted["task:2"].blocked_reason
    damage = {emission.source_task_id: emission for emission in bundle["damage"]}
    assert not damage["task:2"].toughness_emission_required
    assert damage["task:2"].source.evidence["toughness_absence_rule_source"]["raw_type"] == "AdoptedMechanismRule"
    # The two main hits lack the raw attack type and the adjacent hit also lacks
    # an admitted target alias: both stay atomically blocked without borrowing
    # the talent parameter binding of the third task.
    for task_id in ("task:0", "task:1"):
        assert admitted[task_id].coverage_status == "blocked"
        assert all(emission.coverage_status != "executable" for emission in bundle["damage"]
                   if emission.source_task_id == task_id)
        assert all(emission.coverage_status != "executable" for emission in bundle["toughness"]
                   if emission.source_task_id == task_id)
    profiles = {profile.target_selection_policy["task_id"]: profile for profile in bundle["profiles"]}
    assert profiles["task:0"].blocked_reason == "standalone_damage_skill_formula_binding_missing"
    assert "standalone_damage_target_alias_not_admitted:AbilityTargetAdjoinEntity" in profiles["task:1"].blocked_reason


def test_yukong_skill01_phase02_multi_main_tasks_stay_unbound():
    # Real source: one single-parameter basic-attack hit plus three compound hits
    # reading both the basic attack and the talent parameters.
    bundle = _compile("Avatar_Yukong_00", "Avatar_Yukong_00_Skill01_Phase02", "1207")
    projected = bundle["projected"]
    assert bundle["graph"].action_id == "avatar_skill:120701"
    assert {binding.source.raw_id for binding in projected} == {"task:0"}
    binding = projected[0]
    assert binding.source.evidence["action_id"] == "avatar_skill:120701"
    profiles = {profile.target_selection_policy["task_id"]: profile for profile in bundle["profiles"]}
    assert profiles["task:0"].coverage_status == "executable"
    assert profiles["task:0"].stance_expr["value"] == 30
    assert profiles["task:0"].stance_source["raw_path"] == "ShowStanceList[0]"
    toughness = {emission.source_task_id: emission for emission in bundle["toughness"]}
    assert toughness["task:0"].coverage_status == "executable"
    assert toughness["task:0"].toughness_amount_expr["binding_source"]["values"]["1659254037"] == 30
    assert bundle["admitted"]["task:0"].coverage_status == "executable"
    # Each compound hit reads two executable direct-damage parameters of two
    # skills; the main basis is not unique, so those tasks stay unbound even
    # though both candidates share the attack basis.
    effects = {effect.effect_id: effect for effect in bundle["effects"]}
    for task in bundle["tasks"]:
        if task.task_id == "task:0":
            continue
        hashes = set(numeric_dynamic_hashes(_numeric_expr_summary(
            effects[task.effect_id].payload["AttackProperty"]["DamagePercentage"])))
        assert len(hashes) == 2
        assert bundle["admitted"][task.task_id].coverage_status == "blocked"
        assert profiles[task.task_id].blocked_reason == "standalone_damage_skill_formula_binding_missing"
        assert all(emission.coverage_status != "executable" for emission in bundle["damage"]
                   if emission.source_task_id == task.task_id)
