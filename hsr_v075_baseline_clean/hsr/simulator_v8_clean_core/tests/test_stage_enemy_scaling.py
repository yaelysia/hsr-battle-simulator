"""Stage enemy coefficients include both difficulty and EliteGroup sources."""
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering, _wave_level_policy


def test_real_stage_elite_hp_coefficient_and_missing_source_rejection():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    def rows(name):
        return json.loads((root / f"ExcelOutput/{name}.json").read_text())

    index, stage = next((i, row) for i, row in enumerate(rows("StageConfig")) if row["StageID"] == 301008)
    hard_index, hard = next((i, row) for i, row in enumerate(rows("HardLevelGroup"))
                           if row["HardLevelGroup"] == stage["HardLevelGroup"] and row["Level"] == stage["Level"])
    elite_index, elite = next((i, row) for i, row in enumerate(rows("EliteGroup"))
                             if row["EliteGroup"] == stage["EliteGroup"])
    arguments = dict(stage_id=str(stage["StageID"]), stage_row_index=index,
                     level=stage["Level"], hard_level_group=stage["HardLevelGroup"],
                     hard_level_profile={**hard, "_v8_source_path": "ExcelOutput/HardLevelGroup.json", "_v8_row_index": hard_index},
                     elite_group=stage["EliteGroup"])
    result = _wave_level_policy(**arguments, elite_profile={**elite, "_v8_row_index": elite_index})
    assert result["admission_status"] == "executable", result
    assert elite["HPRatio"]["Value"] == 1.25
    assert result["ratios"]["max_hp"] == pytest.approx(hard["HPRatio"]["Value"] * 1.25)
    assert result["ratios"]["attack"] == hard["AttackRatio"]["Value"]
    assert result["source_trace"]["hard_level_profile"]["evidence"]["ratios"]["max_hp"] == hard["HPRatio"]["Value"]
    assert result["source_trace"]["elite_group_profile"]["source_path"] == "ExcelOutput/EliteGroup.json"
    wave = TBGDLowering(root)._lower_wave_definitions([], [], (), stage_ids=frozenset({str(stage["StageID"])}))[0]
    assert wave.level_policy == result
    missing = _wave_level_policy(**arguments)
    assert missing["admission_status"] == "blocked"
    assert "stage_elite_group_profile_missing_or_ambiguous" in missing["blocked_reason"]
