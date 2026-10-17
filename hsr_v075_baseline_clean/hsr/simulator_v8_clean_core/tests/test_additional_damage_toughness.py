"""Real additional-damage request keeps its sourced absence of toughness."""
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR, CharacterAbilityDefinitionIR, CharacterDataCardIR, EffectIR, IRSource,
    StandaloneAbilityGraphIR,
)
from hsr.simulator_v8_clean_core.tbgd.character_cards import skill_formula_bindings_from_row
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _action_definition_from_row, _admit_damage_ability_tasks, _bind_character_queue_damage,
    _dynamic_value_bindings, _effect_payload, _lower_damage_emissions,
    _lower_standalone_hit_profiles, _lower_toughness_emissions,
)


def test_real_additional_damage_omission_is_admitted_but_insert_is_not():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    path = 'Config/ConfigAbility/Avatar/Avatar_Hook_00_Ability.json'
    content = (root / path).read_bytes()
    index, ability = next((index, item) for index, item in enumerate(json.loads(content)['AbilityList'])
                          if item['Name'] == 'Avatar_Hook_00_PassiveSkill01_2')
    task_index, raw = next((index, item) for index, item in enumerate(ability['OnStart'])
                          if item.get('$type') == 'RPG.GameCore.DamageByAttackProperty')
    assert raw['AttackProperty']['AttackType'] == 'Pursued' and 'StanceValue' not in raw['AttackProperty']
    skill_path = 'ExcelOutput/AvatarSkillConfig.json'
    row_index, row = next((index, item) for index, item in enumerate(json.loads((root / skill_path).read_text()))
                          if item.get('SkillID') == 110904 and item.get('Level') == 1)
    definitions = [_action_definition_from_row(skill_path, 'avatar_skill', 'SkillID', row_index, row)]
    bindings = skill_formula_bindings_from_row(relative_path=skill_path, entity_type='avatar_skill',
        id_key='SkillID', row_index=row_index, row=row,
        text_map=json.loads((root / 'TextMap/TextMapCHS.json').read_text()), skill_to_card={'110904': 'card'})
    source = IRSource(path, 'AbilityList', ability['Name'], {
        'source_id': 'source', 'source_kind': 'character_main', 'avatar_id': '1109',
        'json_path': f'$.AbilityList[{index}]', 'ability_index': index,
        'content_sha256': hashlib.sha256(content).hexdigest(),
    })
    definition = CharacterAbilityDefinitionIR('ability', 'source', '1109', ability['Name'], 'character_main', source)
    config = json.loads((root / 'Config/ConfigCharacter/Avatar/Avatar_Hook_00_Config.json').read_text())
    card = CharacterDataCardIR('card', 'avatar:1109', 'profile', ('110904',),
        tuple(binding.binding_id for binding in bindings), (), source,
        dynamic_value_bindings=_dynamic_value_bindings(config['DynamicValues']))
    action_id = f"standalone_ability:{ability['Name']}"
    task = AbilityTaskIR('task', 'phase', action_id, 0, ability['Name'], 'OnStart', task_index,
        f'$.AbilityList[{index}].OnStart[{task_index}]', 'root', 'DamageByAttackProperty', source,
        effect_id='effect', coverage_status='executable')
    effect = EffectIR('effect', task.opcode, _effect_payload(raw, task.opcode, '', source=source), source)
    graph = StandaloneAbilityGraphIR('graph', ability['Name'], 'mainline_avatar', ('phase',),
        (task.task_id,), (task.task_id,), source)
    updated, projected = _bind_character_queue_damage([graph], [task], [effect], bindings,
        definitions, [card], [definition])
    assert updated[0].action_id == 'avatar_skill:110904' and len(projected) == 1
    assert projected[0].formula_role == 'direct_damage' and projected[0].scaling_basis_expr['attack_type'] == 'Pursued'
    assert projected[0].source.evidence['original_formula_role'] == 'additional_damage'
    assert projected[0].source.evidence['skill_formula_binding_source']['evidence']['param_ref'] == 'ParamList[0]'
    profiles = _lower_standalone_hit_profiles([task], [effect], projected, {action_id: definitions[0]})

    def lower(effect):
        damage = _lower_damage_emissions([task], [effect], profiles, projected, {})
        toughness = _lower_toughness_emissions([task], [effect], profiles, projected)
        return damage, toughness, _admit_damage_ability_tasks([task], damage, toughness, profiles)[0]

    damage, toughness, admitted = lower(effect)
    assert admitted.coverage_status == 'executable', admitted.blocked_reason
    assert len(damage) == 1 and not damage[0].toughness_emission_required and not toughness
    adopted = damage[0].source.evidence['toughness_absence_rule_source']
    assert adopted['raw_type'] == 'AdoptedMechanismRule'
    assert adopted['evidence']['source_kind'] == 'adopted_mechanism_data'
    assert adopted['source_path'].startswith('https://wiki.hoyolab.com/')

    insert_payload = deepcopy(effect.payload)
    insert_payload['AttackProperty']['AttackType'] = 'Insert'
    damage, toughness, refused = lower(replace(effect, payload=insert_payload))
    assert damage[0].toughness_emission_required and refused.coverage_status == 'blocked'
    assert toughness[0].blocked_reason == 'attack_property_stance_value_missing'
    explicit_payload = deepcopy(effect.payload)
    explicit_payload['AttackProperty']['StanceValue'] = {'IsDynamic': False, 'FixedValue': {'Value': 3}}
    damage, toughness, admitted = lower(replace(effect, payload=explicit_payload))
    assert admitted.coverage_status == 'executable', admitted.blocked_reason
    assert damage[0].toughness_emission_required and len(toughness) == 1
    assert toughness[0].toughness_amount_expr['value'] == 3
    assert 'toughness_absence_rule_source' not in damage[0].source.evidence
