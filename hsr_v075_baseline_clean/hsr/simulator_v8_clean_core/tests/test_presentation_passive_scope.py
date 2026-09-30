"""Closed-source proof for visual monster startup controllers."""
import json
from pathlib import Path
from shutil import copy2

import pytest

from hsr.simulator_v8_clean_core.dynamic_key_hash import tbgd_dynamic_key_hash
from hsr.simulator_v8_clean_core.tbgd.monster_cards import (
    build_monster_card_ir,
    exclude_presentation_passives,
)


ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
ABILITY = "Config/ConfigAbility/Monster/Monster_AML_Minion01_00_Ability.json"
COMMON = "Config/ConfigAbility/Monster/Monster_Common_Ability.json"
AVATAR_COMMON = "Config/ConfigAbility/Avatar/Avatar_Common_Ability.json"
ARLAN = "Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json"
GLOBAL = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
SOURCES = {ABILITY, COMMON, AVATAR_COMMON, ARLAN, GLOBAL}
VISUAL = "Monster_AML_Minion01_00_PassiveSkillInitiate"
COMBAT = "Monster_Common_PassiveSkill_StanceBreak_Action"
CONTROLLER = "MMonster_AML_Minion01_00_EffectController"


def _copy_sources(tmp_path: Path) -> None:
    for relative in SOURCES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(ROOT / relative, target)


def _slot(name: str):
    result = build_monster_card_ir(
        ROOT, max_records_per_table=None, monster_ids=frozenset({"8011010"})
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
