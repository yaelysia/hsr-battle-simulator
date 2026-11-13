"""Tooltip glossary references cannot create or substitute combat mechanisms."""
import json
from pathlib import Path

from hsr.simulator_v8_clean_core.tbgd.character_cards import (
    _eidolon_build_bindings,
    _eidolon_mechanism_slots,
    _eidolon_slots_from_avatar_row,
    _trace_nodes_and_slots,
)


def test_real_pela_glossary_keeps_ability_and_missing_sources_stay_blocked(tmp_path):
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    card = "character_data_card:avatar:1106"
    table = "ExcelOutput/AvatarSkillTreeConfig.json"
    row = next(r for r in json.loads((root / table).read_text())
               if r["PointID"] == 1106101 and r["Level"] == 1)
    assert row["ExtraEffectIDList"] == [10000010]
    assert row["AbilityName"] == "Avatar_Pela_SkillTree01"
    path = tmp_path / table
    path.parent.mkdir()
    for has_ability in (True, False):
        path.write_text(json.dumps([{**row, "AbilityName": row["AbilityName"] if has_ability else ""}]))
        nodes, mechanisms = _trace_nodes_and_slots(
            tmp_path, avatar_id_to_card={"1106": card},
            dynamic_value_bindings_by_avatar_version={}, max_records_per_table=None,
        )
        assert nodes[0].extra_effect_ids == ("10000010",)
        assert len(mechanisms) == 1
        assert mechanisms[0].mechanism_kind == ("trace_ability_hook" if has_ability else "trace_unbound")
        assert nodes[0].linked_mechanism_slot_ids == (mechanisms[0].mechanism_slot_id,)
        assert mechanisms[0].coverage_status == "blocked"  # Resolving the ability is still required.


def test_eidolon_glossary_alone_is_not_an_executable_source():
    slots = _eidolon_slots_from_avatar_row(
        "ExcelOutput/AvatarConfig.json", 0, {"AvatarID": 1106, "RankIDList": [110601]},
        "character_data_card:avatar:1106",
        {"110601": ("ExcelOutput/AvatarRankConfig.json", 0, {"ExtraEffectIDList": [10000010]})},
    )
    slot = slots[0]
    assert slot.semantics["extra_effect_id_list"] == [10000010]
    mechanisms = _eidolon_mechanism_slots(slot)
    assert len(mechanisms) == 1 and mechanisms[0].mechanism_kind == "eidolon_unbound"
    assert slot.linked_mechanism_slot_ids == (mechanisms[0].mechanism_slot_id,)
    bindings = _eidolon_build_bindings(slot, {m.mechanism_slot_id: m for m in mechanisms}, None, ())
    assert len(bindings) == 1 and bindings[0].projection_kind == "source_gap"
