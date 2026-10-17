"""Declared summon dependencies are loaded, not spawned or implicitly admitted."""
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.tbgd.monster_cards import (
    _RowRecord, _monster_scope_with_summons, build_monster_card_ir,
)


def test_scope_follows_declared_edges_once_and_preserves_missing_ids():
    rows = {key: _RowRecord('source.json', index, {'SummonIDList': refs})
            for index, (key, refs) in enumerate((('1', [2, 2]), ('2', [1, 3]),
                                               ('3', [0, 99]), ('4', [])))}
    assert _monster_scope_with_summons(rows, frozenset({'1'})) == frozenset({'0', '1', '2', '3', '99'})
    assert rows['1'].row['SummonIDList'] == [2, 2]  # Duplicate spawn declarations are not rewritten.
    assert _monster_scope_with_summons(rows, frozenset()) == frozenset()
    assert _monster_scope_with_summons(rows, frozenset({'4'})) == frozenset({'4'})
    for invalid in (None, {}, '2', [True], ['2'], [2.5]):
        bad = {**rows, '2': _RowRecord('source.json', 1, {'SummonIDList': invalid})}
        with pytest.raises(ValueError, match='monster_summon_dependency_shape_invalid:source.json:2'):
            _monster_scope_with_summons(bad, frozenset({'1'}))


def test_real_gray_bear_card_scope_includes_declared_child_without_changing_card_query():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    selected = frozenset({'1013010'})
    direct = build_monster_card_ir(root, max_records_per_table=None, monster_ids=selected)
    expanded = build_monster_card_ir(root, max_records_per_table=None, monster_ids=selected,
                                     include_summon_dependencies=True)
    assert [card.monster_id for card in direct.monster_data_cards] == ['1013010']
    assert {card.monster_id for card in expanded.monster_data_cards} == {'1013010', '1012021'}
    assert direct.monster_data_cards[0] == next(card for card in expanded.monster_data_cards if card.monster_id == '1013010')
    child = next(card for card in expanded.monster_data_cards if card.monster_id == '1012021')
    assert child.skill_ids and child.passive_mechanism_slot_ids
    assert set(child.passive_mechanism_slot_ids) <= {slot.passive_slot_id for slot in expanded.passive_mechanism_slots}


@pytest.mark.integration
def test_battle_scope_loads_child_actions_but_keeps_actual_startup_blocked():
    from hsr.simulator_v8_clean_core.session import BattleSession
    from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

    root = Path(__file__).resolve().parents[4]
    scenario = json.loads((Path(__file__).resolve().parents[1] / 'examples/cli/arlan_vs_antimatter.json').read_text())
    scenario.update(stage_ref='2013110', wave_index=0)
    scenario.pop('wave_definition_ref', None)
    scenario['battle_setup']['wave'] = {'kind': 'stage', 'stage_ref': '2013110', 'wave_index': 0}
    rules = build_battle_rulebook(root / 'turnbasedgamedata-main', scenario)
    assert set(rules.ir.metadata['content_scope']['monster_ids']) == {'1013010', '1012021'}
    child = next(card for card in rules.ir.monster_data_cards if card.monster_id == '1012021')
    assert any(profile.entity_id == child.entity_ref for profile in rules.ir.combatant_profiles)
    assert any(action_set.entity_ref == child.entity_ref for action_set in rules.ir.combatant_action_sets)
    assert set(child.skill_ids) <= {action.action_id.split(':', 1)[1]
                                   for action in rules.ir.action_definitions if action.action_id.startswith('monster_skill:')}
    with pytest.raises(ValueError, match='monster_passive_startup_root_on_start_has_unadmitted_tasks'):
        BattleSession(rules, scenario)
