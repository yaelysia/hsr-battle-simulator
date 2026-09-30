"""Compile the complete source graphs selected by a local battle scenario."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..rules.rulebook import RuleBook
from ..scenarios.loader import ScenarioLoader
from .lowering import TBGDLowering


def build_battle_rulebook(root: Path, scenario_data: dict[str, Any]) -> RuleBook:
    scenario = ScenarioLoader().load_dict(scenario_data)
    avatars = frozenset(unit.entity_ref.split(":", 1)[1] for unit in scenario.units
                        if unit.entity_ref.startswith("avatar:"))
    monsters = {unit.entity_ref.split(":", 1)[1] for unit in scenario.units
                if unit.entity_ref.startswith("monster:")}
    if not avatars:
        raise ValueError("CLI battle requires at least one character")
    if any(unit.entity_ref.startswith("avatar:") and unit.build_mode != "assembled_character_build"
           for unit in scenario.units):
        raise ValueError("CLI characters require assembled_character_build")
    stage_id = scenario.stage_ref
    if not stage_id and scenario.wave_definition_ref:
        prefix = "wave_definition:stage:"
        if not scenario.wave_definition_ref.startswith(prefix):
            raise ValueError("unsupported wave definition identity")
        stage_id = scenario.wave_definition_ref[len(prefix):]
    if not stage_id:
        raise ValueError("CLI battle requires a source wave or stage reference")
    if scenario.battle_setup.metadata.get("stage_scope") != "wave_only":
        raise ValueError("CLI currently requires metadata.stage_scope=wave_only; full level templates are not supported")
    rows = json.loads((root / "ExcelOutput/StageConfig.json").read_text(encoding="utf-8"))
    selected = [row for row in rows if str(row.get("StageID")) == stage_id]
    if len(selected) != 1:
        raise ValueError("stage source is missing or ambiguous")
    waves = selected[0].get("MonsterList", [])
    if not isinstance(waves, list) or len(waves) != 1:
        raise ValueError("CLI requires exactly one wave; passive startup on later waves is not admitted")
    for wave in waves:
        if not isinstance(wave, dict):
            raise ValueError("stage monster wave must be an object")
        monsters.update(str(value) for value in wave.values())
    equipment = any(unit.character_build is not None and (
        unit.character_build.equipment_build.light_cone is not None
        or unit.character_build.equipment_build.relics
    ) for unit in scenario.units)
    ir = TBGDLowering(root).build(
        avatar_ids=avatars, monster_ids=frozenset(monsters),
        stage_ids=frozenset({stage_id}), include_equipment=equipment,
    )
    return RuleBook(ir)
