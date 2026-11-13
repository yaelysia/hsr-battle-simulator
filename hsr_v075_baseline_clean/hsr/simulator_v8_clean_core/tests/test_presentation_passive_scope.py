"""Closed-source proof for visual monster startup controllers."""
from dataclasses import replace
import json
from pathlib import Path
from shutil import copy2

import pytest

from hsr.simulator_v8_clean_core.dynamic_key_hash import tbgd_dynamic_key_hash
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.startup import _passive_runtime_activation
from hsr.simulator_v8_clean_core.tbgd.monster_cards import (
    build_monster_card_ir,
    exclude_presentation_passives,
)


ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
ABILITY = "Config/ConfigAbility/Monster/Monster_AML_Minion01_00_Ability.json"
SIBLING = "Config/ConfigAbility/Monster/Monster_AML_Minion01_01_Ability.json"
COMMON = "Config/ConfigAbility/Monster/Monster_Common_Ability.json"
AVATAR_COMMON = "Config/ConfigAbility/Avatar/Avatar_Common_Ability.json"
ARLAN = "Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json"
GLOBAL = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
SOURCES = {ABILITY, COMMON, AVATAR_COMMON, ARLAN, GLOBAL}
VISUAL = "Monster_AML_Minion01_00_PassiveSkillInitiate"
COMBAT = "Monster_Common_PassiveSkill_StanceBreak_Action"
CONTROLLER = "MMonster_AML_Minion01_00_EffectController"


def test_lieutenant_stance_animation_mapping_is_presentation_only():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason

    source = json.loads((ROOT / 'Config/ConfigAbility/Monster/Monster_W1_Soldier03_00_Ability.json').read_text())
    tasks = [task for ability in source['AbilityList'] for task in ability.get('OnStart', [])
             if task.get('$type') == 'RPG.GameCore.CharacterChangePhase']
    assert tasks and {task['PhaseName'] for task in tasks} == {'Phase1', 'Phase2'}
    for task in tasks:
        assert not _process_only_ability_task_source_blocked_reason(task, 'CharacterChangePhase')
        assert _process_only_ability_task_source_blocked_reason(
            {**task, 'GameplayState': 1}, 'CharacterChangePhase')
    aim = [task for ability in source['AbilityList'] for task in ability.get('OnStart', [])
           if task.get('$type') == 'RPG.GameCore.StartAim']
    assert aim and all(not _process_only_ability_task_source_blocked_reason(t, 'StartAim') for t in aim)

    from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering

    path = ROOT / 'Config/ConfigAbility/Monster/Monster_W1_Soldier03_00_Ability.json'
    lowered = TBGDLowering(ROOT)._lower_ability_file(path, {}, ability_file_order=0)
    resilience = [t for t in lowered.status_callback_tasks if t.opcode == 'SetResilience']
    assert resilience and all(t.blocked_reason == 'source_proven_presentation_only' for t in resilience)
    destroy = next(c for c in lowered.status_callbacks
                   if c.modifier_name == 'MMonster_W1_Soldier03_00_ListenBeingAttacked' and c.event == 'OnDestroy')
    assert destroy.blocked_reason == 'source_proven_presentation_only'


def _copy_sources(tmp_path: Path) -> None:
    for relative in SOURCES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(ROOT / relative, target)


def test_aurumaton_achievement_and_team_formation_have_no_combat_effect():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason
    from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode

    source = json.loads((ROOT / 'Config/ConfigAbility/Monster/Monster_W2_Mecha03_00_Ability.json').read_text())
    found = []

    def visit(value):
        if isinstance(value, dict):
            opcode = value.get('$type', '').split('.')[-1]
            if opcode in {'SetBattleAchievement', 'SetSkillTargetFormationByPos'}:
                assert ability_task_execution_mode(opcode) == 'process_only'
                assert not _process_only_ability_task_source_blocked_reason(value, opcode)
                assert _process_only_ability_task_source_blocked_reason({**value, 'Damage': 1}, opcode)
                found.append(opcode)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(source)
    assert found.count('SetBattleAchievement') == 2 and 'SetSkillTargetFormationByPos' in found


def _slot(name: str, monster_id: str = "8011010"):
    result = build_monster_card_ir(
        ROOT, max_records_per_table=None, monster_ids=frozenset({monster_id})
    )
    return next(
        slot
        for slot in result.passive_mechanism_slots
        if slot.semantics["ability_name"] == name
    )


def _exclude(slot, root: Path, sources: set[str] | None = None):
    return exclude_presentation_passives(
        [slot], root, SOURCES if sources is None else sources
    )[0]


def _write_json(root: Path, relative: str, value: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_real_8011010_visual_controller_is_skipped_only_with_closed_scope(tmp_path):
    _copy_sources(tmp_path)

    result = _exclude(_slot(VISUAL), tmp_path)

    assert result.mechanism_kind == "presentation_only"
    assert result.runtime_system == "none"
    assert result.coverage_status == "skipped_with_reason"
    assert result.blocked_reason == "presentation_only_closed_source_scope"
    scope = result.semantics["presentation_scope"]
    assert CONTROLLER in scope["private_identities"]
    assert "TimeSlowSpeed" in scope["private_identities"]
    assert len(scope["source_fingerprints"]) == len(SOURCES)


@pytest.mark.parametrize("monster_id,suffix", [("8001040", "02"), ("8001050", "03")])
def test_visual_on_start_controller_does_not_block_monster_entry(tmp_path, monster_id, suffix):
    _copy_sources(tmp_path)
    relative = f"Config/ConfigAbility/Monster/Monster_XP_Minion01_{suffix}_Ability.json"
    copy2(ROOT / relative, tmp_path / relative)
    slot = _slot(f"Monster_XP_Minion01_{suffix}_PassiveSkillInitiate", monster_id)
    result = _exclude(slot, tmp_path, SOURCES | {relative})

    assert result.mechanism_kind == "presentation_only"
    assert result.coverage_status == "skipped_with_reason"
    card = build_monster_card_ir(
        ROOT, max_records_per_table=None, monster_ids=frozenset({monster_id}),
    ).monster_data_cards[0]
    card = replace(card, passive_mechanism_slot_ids=(result.passive_slot_id,))
    rules = RuleBook(CanonicalIR("visual-startup", monster_data_cards=(card,), passive_mechanism_slots=(result,)))
    activation = _passive_runtime_activation(rules, card)
    assert not activation["startup_specs"]
    assert not activation["flags"].get("blocked_passive_mechanism_slots")


def test_visual_controller_with_battle_opcode_remains_a_passive_slot(tmp_path):
    _copy_sources(tmp_path)
    path = tmp_path / ABILITY
    document = json.loads(path.read_text(encoding="utf-8"))
    definition = next(item for item in document["AbilityList"] if item["Name"] == VISUAL)
    controller = definition["Modifiers"][CONTROLLER]
    controller["_CallbackList"][0]["CallbackConfig"].append(
        {"$type": "RPG.GameCore.DamageByAttackProperty"}
    )
    path.write_text(json.dumps(document), encoding="utf-8")

    result = _exclude(_slot(VISUAL), tmp_path)

    assert result.mechanism_kind != "presentation_only"
    assert result.coverage_status == "lowered"
    assert not result.blocked_reason


@pytest.mark.parametrize(
    "token",
    (
        CONTROLLER,
        "TimeSlowSpeed",
        str(tbgd_dynamic_key_hash("TimeSlowSpeed")),
    ),
)
def test_visual_controller_is_not_skipped_when_private_identity_escapes(tmp_path, token):
    _copy_sources(tmp_path)
    external = "Config/PresentationScopeEscape.json"
    _write_json(tmp_path, external, {"external_reference": token})

    result = _exclude(_slot(VISUAL), tmp_path, SOURCES | {external})

    assert result.mechanism_kind != "presentation_only"
    assert result.coverage_status == "lowered"
    assert not result.blocked_reason


def test_common_stance_break_passive_is_never_classified_as_presentation(tmp_path):
    _copy_sources(tmp_path)

    result = _exclude(_slot(COMBAT), tmp_path)

    assert result.mechanism_kind == "monster_ability_list_passive"
    assert result.coverage_status == "lowered"
    assert not result.blocked_reason


def test_two_visual_controllers_can_share_local_key_but_not_escape_it(tmp_path):
    _copy_sources(tmp_path)
    copy2(ROOT / SIBLING, tmp_path / SIBLING)
    slots = [
        _slot(VISUAL),
        _slot("Monster_AML_Minion01_01_PassiveSkillInitiate", "8011020"),
    ]
    sources = SOURCES | {SIBLING}

    admitted = exclude_presentation_passives(slots, tmp_path, sources)
    assert all(slot.mechanism_kind == "presentation_only" for slot in admitted)

    external = "Config/PresentationScopeEscape.json"
    _write_json(tmp_path, external, {"external_reference": "TimeSlowSpeed"})
    blocked = exclude_presentation_passives(slots, tmp_path, sources | {external})
    assert all(slot.mechanism_kind == "monster_ability_list_passive" for slot in blocked)
