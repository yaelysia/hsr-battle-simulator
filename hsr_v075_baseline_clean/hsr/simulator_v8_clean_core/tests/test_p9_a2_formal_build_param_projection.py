from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.builds.character_assembler import (
    assemble_character_build, validate_character_build_admission,
)
from hsr.simulator_v8_clean_core.builds.models import (
    CharacterInitialConditionInput, CharacterMechanismDiagnostic,
)
from hsr.simulator_v8_clean_core.equipment.models import (
    CharacterEquipmentEligibilityIR, EquipmentDefinitionKey,
)
from hsr.simulator_v8_clean_core.rules.ir import (
    ActionDefinitionIR, AvatarProfileIR, AvatarPromotionTierIR, CanonicalIR,
    CharacterDataCardIR, CharacterEidolonSlotIR, IRSource,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.scenarios.build_state import (
    _formal_character_activation, _plan_formal_character_birth,
    _project_character_skill_level_flags,
)
from hsr.simulator_v8_clean_core.scenarios.schema import ScenarioSpec, UnitSpec
from hsr.simulator_v8_clean_core.tools.validate_p8_s2_character_build_base_panel import _build


def _fixture():
    source = IRSource('validation/AvatarConfig.json', 'AvatarConfig', 'fixture',
                     evidence={'promotion_zero_semantic_from_missing_field': True})
    definitions = tuple(
        ActionDefinitionIR(
            definition_id=f'def:{skill}', action_id=f'avatar_skill:{skill}', level=1,
            attack_type='Normal', skill_effect='SingleAttack', target_mode='single',
            bp_need=0, bp_add=0, sp_base=0, sp_multiple_ratio=0,
            param_list=(), show_stance_list=(), show_damage_list=(),
            stance_damage_type=None,
            source=IRSource('validation/AvatarSkillConfig.json', 'AvatarSkillConfig', skill,
                            evidence={'level': 1, 'row_index': index, 'id_key': 'SkillID'}),
            coverage_status='executable', skill_trigger_key=trigger,
        )
        for index, (skill, trigger) in enumerate((('active', 'Attack'), ('empty', '')))
    )
    tier = AvatarPromotionTierIR(
        promotion_tier_id='tier:fixture', avatar_id='fixture', promotion=0,
        promotion_field_present=False, max_level=20, hp_base='100', hp_add='5',
        attack_base='50', attack_add='2', defense_base='40', defense_add='1',
        speed_base='100', critical_chance='0.05', critical_damage='0.5', base_aggro='100',
        source=source, coverage_status='executable',
    )
    profile = AvatarProfileIR(
        avatar_profile_id='profile:fixture', avatar_id='fixture', base_type='FixturePath',
        damage_type='Physical', skill_ids=('active', 'empty'), promotion_tiers=(tier,),
        max_energy='120', max_energy_source=source, source=source, coverage_status='executable',
    )
    card = CharacterDataCardIR(
        card_id='card:fixture', entity_ref='avatar:fixture', profile_id=profile.avatar_profile_id,
        skill_ids=profile.skill_ids, skill_formula_binding_ids=(), bounce_policy_ids=(),
        action_set={'actions': [dict(action_id=d.action_id, raw_skill_id=d.source.raw_id,
                                    level=1, max_level=1, source_trace=d.source.to_json())
                                for d in definitions]},
        source=source, coverage_status='executable',
    )
    eligibility = CharacterEquipmentEligibilityIR(
        definition_key=EquipmentDefinitionKey('character_equipment_eligibility', card.card_id),
        character_card_id=card.card_id, character_profile_id=profile.avatar_profile_id,
        character_path_type='FixturePath', passive_activation_path_types=('FixturePath',),
        source=source, coverage_status='executable', blocked_reason='',
    )
    card = replace(card, equipment_eligibility_id=eligibility.definition_key.definition_identity)
    rules = RuleBook(CanonicalIR(version='fixture', action_definitions=definitions,
                                avatar_profiles=(profile,), character_data_cards=(card,),
                                character_eidolon_slots=tuple(
                                    CharacterEidolonSlotIR(
                                        eidolon_slot_id=f'eidolon:{rank}',
                                        character_data_card_id=card.card_id, avatar_id='fixture',
                                        rank=rank, rank_id=f'rank:{rank}', linked_mechanism_slot_ids=(),
                                        source=source, coverage_status='executable', blocked_reason='',
                                    ) for rank in range(1, 7)
                                ),
                                character_equipment_eligibilities=(eligibility,)))
    build = _build(card.card_id, level=1, promotion=0)
    assembly = assemble_character_build(rules, build)
    assert not validate_character_build_admission(rules, build, assembly)
    unit = UnitSpec('actor', 'ally', card.entity_ref, 'assembled_character_build',
                    level=1, panel=None, character_build=build,
                    initial_condition=CharacterInitialConditionInput('full', '0'))
    return rules, unit, assembly


def test_real_assembly_birth_keeps_empty_trigger_in_complete_ledger():
    rules, unit, assembly = _fixture()
    scenario = ScenarioSpec('fixture', 'fixture', (unit,), ())
    before = repr(scenario)
    plan = _plan_formal_character_birth(rules, scenario, unit, assembly)
    assert plan.flags['skill_levels_by_trigger_key'] == {'Attack': 1}
    for ledger in ('effective_skill_levels_by_action_id', 'effective_skill_level_sources',
                   'effective_skill_level_action_definitions'):
        assert set(plan.flags[ledger]) == {'avatar_skill:active', 'avatar_skill:empty'}
    assert plan.max_hp == 100 and plan.max_energy == 120
    assert repr(scenario) == before


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'identity', 'card', 'level', 'build'])
def test_projection_rejects_inconsistent_identity_without_mutating_inputs(kind):
    rules, unit, assembly = _fixture()
    definitions = rules.ir.action_definitions
    if kind == 'missing':
        rules = RuleBook(replace(rules.ir, action_definitions=definitions[:1]))
    elif kind == 'duplicate':
        rules = RuleBook(replace(rules.ir, action_definitions=(*definitions, replace(definitions[0], definition_id='duplicate'))))
    elif kind == 'identity':
        rules = RuleBook(replace(rules.ir, action_definitions=(replace(definitions[0], definition_id='wrong'), definitions[1])))
    elif kind == 'card':
        unit = replace(unit, entity_ref='avatar:other')
    elif kind == 'level':
        unit = replace(unit, level=2)
    else:
        assembly = replace(assembly, build_id='other')
    before = assembly.to_json()
    with pytest.raises(ValueError):
        _formal_character_activation(rules, unit, assembly)
    assert assembly.to_json() == before


@pytest.mark.parametrize('level', [True, 0, -1])
def test_formal_level_type_rejects_illegal_values(level):
    _, _, assembly = _fixture()
    with pytest.raises((ValueError, TypeError)):
        replace(assembly.effective_skill_levels[0], effective_level=level)


def test_same_trigger_same_level_is_idempotent():
    rules, unit, _ = _fixture()
    definitions = rules.ir.action_definitions
    rules = RuleBook(replace(rules.ir, action_definitions=(definitions[0], replace(definitions[1], skill_trigger_key='Attack'))))
    assembly = assemble_character_build(rules, unit.character_build)
    flags, _, _ = _formal_character_activation(rules, unit, assembly)
    assert flags['skill_levels_by_trigger_key'] == {'Attack': 1}
    assert len(flags['effective_skill_level_sources']) == 2


def test_same_trigger_different_effective_levels_is_rejected():
    rules, unit, _ = _fixture()
    active, empty = rules.ir.action_definitions
    source = replace(empty.source, evidence={**empty.source.evidence, 'level': 2})
    empty = replace(empty, level=2, skill_trigger_key='Attack', source=source)
    card = rules.ir.character_data_cards[0]
    actions = [dict(action) for action in card.action_set['actions']]
    actions[1].update(level=2, max_level=2, source_trace=source.to_json())
    card = replace(card, action_set={'actions': actions})
    rules = RuleBook(replace(rules.ir, action_definitions=(active, empty), character_data_cards=(card,)))
    assembly = assemble_character_build(rules, unit.character_build)
    assert not validate_character_build_admission(rules, unit.character_build, assembly)
    before = assembly.to_json()
    with pytest.raises(ValueError, match='trigger level is ambiguous'):
        _formal_character_activation(rules, unit, assembly)
    assert assembly.to_json() == before


def test_static_projection_matches_formal_flags_without_admission_fields():
    rules, unit, assembly = _fixture()
    before = assembly.to_json()
    projected = _project_character_skill_level_flags(rules, assembly)
    formal_flags, _, _ = _formal_character_activation(rules, unit, assembly)
    assert set(projected) == {
        'effective_skill_levels_by_action_id', 'skill_levels_by_trigger_key',
        'effective_skill_level_sources', 'effective_skill_level_action_definitions',
    }
    assert projected == {key: formal_flags[key] for key in projected}
    assert assembly.to_json() == before


def test_static_projection_returns_fresh_ledgers():
    rules, _, assembly = _fixture()
    before = assembly.to_json()
    expected = _project_character_skill_level_flags(rules, assembly)
    projected = _project_character_skill_level_flags(rules, assembly)
    projected['skill_levels_by_trigger_key']['Attack'] = 99
    projected['effective_skill_levels_by_action_id'].clear()
    projected['effective_skill_level_sources'].clear()
    projected['effective_skill_level_action_definitions'].clear()
    assert _project_character_skill_level_flags(rules, assembly) == expected
    assert assembly.to_json() == before


def test_static_projection_does_not_grant_blocked_build_birth_admission():
    rules, unit, assembly = _fixture()
    # This unit fixture checks the separation, not real-owner source closure.
    diagnostic = CharacterMechanismDiagnostic(
        diagnostic_id='diagnostic:deferred',
        mechanism_kind='character_dynamic_graph_root',
        target_ref_id='root:fixture',
        reason='character_dynamic_graph_runtime_semantics_pending_p9_s4_s17',
        source=rules.ir.character_data_cards[0].source,
    )
    blocked = replace(
        assembly, battle_admission_status='blocked',
        unadmitted_mechanism_diagnostics=(diagnostic,),
    )
    before = blocked.to_json()
    assert _project_character_skill_level_flags(rules, blocked) == (
        _project_character_skill_level_flags(rules, assembly)
    )
    with pytest.raises(ValueError, match='admission mismatch'):
        _formal_character_activation(rules, unit, blocked)
    scenario = ScenarioSpec('fixture', 'fixture', (unit,), ())
    with pytest.raises(ValueError):
        _plan_formal_character_birth(rules, scenario, unit, blocked)
    assert blocked.to_json() == before
    assert blocked.battle_admission_status == 'blocked'
    assert blocked.unadmitted_mechanism_diagnostics == (diagnostic,)


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'identity', 'source', 'coverage'])
def test_static_projection_independently_checks_canonical_definitions(kind):
    rules, _, assembly = _fixture()
    active, empty = rules.ir.action_definitions
    if kind == 'missing':
        definitions = (empty,)
    elif kind == 'duplicate':
        definitions = (active, empty, replace(active, definition_id='duplicate'))
    elif kind == 'identity':
        definitions = (replace(active, definition_id='wrong'), empty)
    elif kind == 'source':
        definitions = (replace(active, source=replace(active.source, raw_id='wrong')), empty)
    else:
        definitions = (replace(active, coverage_status='blocked'), empty)
    rules = RuleBook(replace(rules.ir, action_definitions=definitions))
    before = assembly.to_json()
    with pytest.raises(ValueError):
        _project_character_skill_level_flags(rules, assembly)
    assert assembly.to_json() == before


def test_static_projection_rejects_failed_assembly():
    rules, _, _ = _fixture()
    failed = assemble_character_build(rules, _build('card:missing', level=1, promotion=0))
    assert failed.assembly_status == 'blocked'
    with pytest.raises(ValueError, match='requires an assembled result'):
        _project_character_skill_level_flags(rules, failed)


def test_static_projection_rejects_untyped_result():
    rules, _, _ = _fixture()
    with pytest.raises(ValueError, match='requires an assembled result'):
        _project_character_skill_level_flags(rules, object())
