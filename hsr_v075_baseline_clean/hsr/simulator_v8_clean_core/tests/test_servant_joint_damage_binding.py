"""A joint skill's servant hit reads the creation argument, not the owner's hit."""
import json
from pathlib import Path

from hsr.simulator_v8_clean_core.rules.ir import AbilityTaskIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.value_binding import resolve_runtime_numeric_expression
from hsr.simulator_v8_clean_core.tbgd.character_cards import skill_formula_bindings_from_row
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _action_definition_from_row, _effect_payload, _hit_profiles_from_skill_formula_bindings,
    _lower_damage_emissions,
)
from hsr.simulator_v8_clean_core.tests.test_standalone_task_binding import _walk_damage_tasks


def test_castorice_joint_hit_uses_the_servant_parameter_forwarded_at_creation():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    skill_path = 'ExcelOutput/AvatarSkillConfig.json'
    index, row = next((i, r) for i, r in enumerate(json.loads((root / skill_path).read_text()))
                      if r.get('SkillID') == 140709 and r.get('Level') == 10)
    definition = _action_definition_from_row(skill_path, 'avatar_skill', 'SkillID', index, row)
    bindings = skill_formula_bindings_from_row(relative_path=skill_path, entity_type='avatar_skill',
        id_key='SkillID', row_index=index, row=row, skill_to_card={'140709': 'card'},
        text_map=json.loads((root / 'TextMap/TextMapCHS.json').read_text()))
    path = 'Config/ConfigAbility/Servant/Servant_CastoriceServant_00_Ability.json'
    ability_index, ability = next((i, a) for i, a in enumerate(json.loads((root / path).read_text())['AbilityList'])
        if a.get('Name') == 'Servant_CastoriceServant_Together_Phase01')
    damage = []
    _walk_damage_tasks(ability, f'$.AbilityList[{ability_index}]', damage)
    location, raw = next((p, r) for p, r in damage if '.FailedTaskList' in p)
    source = IRSource(path, 'DamageByAttackProperty', 'joint-hit', {'json_path': location})
    effect = EffectIR('hit', 'DamageByAttackProperty', _effect_payload(raw, 'DamageByAttackProperty', '', source=source), source)
    task = AbilityTaskIR('task', 'phase', definition.action_id, 10, ability['Name'], 'OnStart', 0,
                        location, 'root', effect.opcode, source, effect_id=effect.effect_id, coverage_status='executable')
    profiles = _hit_profiles_from_skill_formula_bindings(definition, bindings)
    owner_path = 'Config/ConfigAbility/Avatar/Avatar_Castorice_00_Ability.json'
    def creation(node, path='$'):
        if isinstance(node, dict):
            if node.get('$type') == 'RPG.GameCore.CreateServant' and 'Castorice_Skill21_P3_HPPercentage' in node.get('DynamicValues', {}):
                return node, path
            for key, value in node.items():
                found = creation(value, path + '.' + key)
                if found: return found
        elif isinstance(node, list):
            for i, value in enumerate(node):
                found = creation(value, path + f'[{i}]')
                if found: return found
    create_raw, create_path = creation(json.loads((root / owner_path).read_text()))
    create_source = IRSource(owner_path, 'CreateServant', 'create', {'json_path': create_path})
    create = EffectIR('create', 'CreateServant', _effect_payload(create_raw, 'CreateServant', '', source=create_source), create_source)
    emissions = _lower_damage_emissions([task], [effect, create], profiles, bindings, {})
    assert len(emissions) == 1
    expression = emissions[0].scaling_ratio_expr
    assert 'binding_source' not in expression
    result = resolve_runtime_numeric_expression(expression,
        binding_sources=({'source_type': 'creation_argument', 'by_hash': {'602935177': {'value': .5}}},), source_trace={})
    assert result.ok and result.value == .5, result.blocked_reason


def test_native_servant_bounce_uses_configured_enemy_pool_without_outer_bounces():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    path = 'ExcelOutput/AvatarServantSkillConfig.json'
    index, row = next((i, r) for i, r in enumerate(json.loads((root / path).read_text()))
                      if r.get('SkillID') == 1140712 and r.get('Level') == 6)
    config = json.loads((root / 'Config/ConfigCharacter/Servant/Servant_CastoriceServant_00_Config.json').read_text())
    skill = next(s for s in config['SkillList'] if s['Name'] == row['SkillTriggerKey'])
    definition = _action_definition_from_row(path, 'servant_skill', 'SkillID', index, row,
        servant_target_source={'target_type': skill['TargetInfo']['TargetType']})
    assert row['SkillEffect'] == 'Bounce'
    assert definition.target_mode == 'aoe' and definition.target_relation == 'enemy'
    # Other bounce skills retain their existing policy path.
    assert _action_definition_from_row(path, 'servant_skill', 'SkillID', index, row).target_mode == 'bounce'
