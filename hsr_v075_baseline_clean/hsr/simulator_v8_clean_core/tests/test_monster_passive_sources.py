"""Source discovery checks only; no claim of executable monster passives."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.tbgd.monster_cards import (
    _RowRecord, _monster_ability_name_index, _monster_card, _passive_slots_for_monster, build_monster_card_ir,
)


ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
CONFIG = "Config/ConfigCharacter/Monster/Monster_AML_Minion01_00_Config.json"
ABILITY = "Config/ConfigAbility/Monster/Monster_AML_Minion01_00_Ability.json"
COMMON = "Config/ConfigAbility/Monster/Monster_Common_Ability.json"


def test_real_monster_card_preserves_both_passive_entry_edges_and_actual_callbacks():
    result = build_monster_card_ir(ROOT, max_records_per_table=None, monster_ids=frozenset({"8011010"}))
    card = result.monster_data_cards[0]
    slots = result.passive_mechanism_slots
    assert len(slots) == len(card.passive_mechanism_slot_ids) == 2
    assert {s.activation["callback_kind"] for s in slots} == {"OnStart", "OnAdd"}
    for slot in slots:
        assert slot.coverage_status == "lowered" and not slot.blocked_reason
        edges = slot.source.evidence["source_edges"]
        assert len(edges) == 2
        assert any(e["raw_path"].startswith("SkillList[") for e in edges)
        assert any(e["raw_path"].startswith("AbilityList[") for e in edges)
        assert all(e["template_source"]["character_config_path"] == CONFIG for e in edges)
        assert slot.source.evidence["root_callback_sources"]


def test_real_monster_catalog_does_not_turn_ai_strategies_into_battle_constraints():
    cards = build_monster_card_ir(ROOT, max_records_per_table=None).monster_data_cards
    assert cards and any(card.action_sequence for card in cards)
    assert any(card.ai_policy['admission_status'] == 'executable' for card in cards)
    assert any(card.ai_policy['admission_status'] == 'blocked' and not card.blocked_reason for card in cards)
    assert all(card.ai_policy['candidate_constraint_admitted'] is False for card in cards)
    assert all(card.ai_policy['selection_controller'] == 'external' for card in cards)
    assert all('monster_ai_' not in card.blocked_reason for card in cards)


def test_source_empty_passive_has_no_runtime_behavior(tmp_path):
    source = json.loads((ROOT / COMMON).read_text())
    declaration = next(a for a in source['AbilityList'] if a['Name'] == 'Monster_Common_Fever_Action')
    assert declaration == {'Name': declaration['Name'], 'TargetInfo': {'TargetType': 'Caster'}}
    config_path = 'Config/ConfigCharacter/Monster/Monster_W1_Soldier01_00_Config.json'
    for relative in (COMMON, config_path):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    monster = _RowRecord('ExcelOutput/MonsterConfig.json', 0,
                         {'MonsterID': 1002040, 'MonsterTemplateID': 1002040, 'AbilityNameList': []})
    template = _RowRecord('ExcelOutput/MonsterTemplateConfig.json', 0, {'JsonConfig': config_path})
    def slot():
        return next(s for s in _slots((tmp_path, monster, template))
                    if s.semantics['ability_name'] == declaration['Name'])
    result = slot()
    assert result.mechanism_kind == 'empty_ability_declaration'
    assert result.coverage_status == 'skipped_with_reason' and result.runtime_system == 'none'
    declaration['OnStart'] = []
    (tmp_path / COMMON).write_text(json.dumps(source))
    assert slot().mechanism_kind == 'empty_ability_declaration'
    assert slot().runtime_system == 'none'
    # An unknown field could carry inherited/native behavior; it is not empty.
    declaration['UnknownBehavior'] = 'unresolved'
    (tmp_path / COMMON).write_text(json.dumps(source))
    assert slot().coverage_status == 'blocked'


@pytest.fixture
def source_case(tmp_path):
    for relative in (CONFIG, ABILITY, COMMON):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    monster = _RowRecord("ExcelOutput/MonsterConfig.json", 0, {"MonsterID": 8011010,
                          "MonsterTemplateID": 8011010, "AbilityNameList": []})
    template = _RowRecord("ExcelOutput/MonsterTemplateConfig.json", 0, {"JsonConfig": CONFIG})
    return tmp_path, monster, template


def _slots(case, index=None):
    root, monster, template = case
    return _passive_slots_for_monster("8011010", monster, index if index is not None else _monster_ability_name_index(root),
                                     tbgd_root=root, template_record=template)


def test_external_control_keeps_missing_battle_skill_blocked(source_case):
    root, monster, template = source_case
    monster = _RowRecord(monster.relative_path, monster.row_index,
                         {**monster.row, 'SkillList': [801101001]})
    card = _monster_card(root, '8011010', monster, {'8011010': template}, {}, {})
    assert card.coverage_status == 'blocked' and card.blocked_reason == 'monster_skill_definition_missing'


def test_three_sources_deduplicate_passive_and_exclude_known_active(source_case):
    root, monster, template = source_case
    config = json.loads((root / CONFIG).read_text())
    passive_name = config["AbilityList"][0]
    monster = _RowRecord(monster.relative_path, monster.row_index,
                         {**monster.row, "AbilityNameList": [passive_name]})
    # Entry and linked phase from the normal skill are definitions, not startup passives.
    config["AbilityList"] += config["SkillAbilityList"][0]["AbilityList"]
    (root / CONFIG).write_text(json.dumps(config))
    slots = _slots((root, monster, template))
    assert len(slots) == 2 and all(not s.blocked_reason for s in slots)
    slot = next(s for s in slots if s.semantics["ability_name"] == passive_name)
    assert len(slot.source.evidence["source_edges"]) == 3


@pytest.mark.parametrize("case", ["missing", "ambiguous", "unknown_activation", "active_conflict", "missing_config"])
def test_source_gaps_remain_blocked(source_case, case):
    root, monster, template = source_case
    config = json.loads((root / CONFIG).read_text())
    name = config["AbilityList"][0]
    index = _monster_ability_name_index(root)
    if case == "missing":
        index.pop(name)
    elif case == "ambiguous":
        index[name] = (*index[name], *index[name])
    elif case == "unknown_activation":
        config["SkillList"] = [skill for skill in config["SkillList"] if skill.get("EntryAbility") != name]
    elif case == "active_conflict":
        skill = deepcopy(config["SkillList"][0])
        skill["EntryAbility"] = name
        config["SkillList"].append(skill)
    (root / CONFIG).write_text(json.dumps(config))
    if case == "missing_config":
        (root / CONFIG).unlink()
    slots = _slots((root, monster, template), index)
    blocked = [s for s in slots if s.coverage_status == "blocked"]
    assert blocked and all(s.blocked_reason for s in blocked)
