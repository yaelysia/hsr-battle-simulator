"""Compile the complete source graphs selected by a local battle scenario."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..rules.rulebook import RuleBook
from ..scenarios.loader import ScenarioLoader
from .lowering import TBGDLowering


def list_stage_choices(root: Path, text_map: dict[str, str]) -> list[dict[str, Any]]:
    """Source discovery for configuration; admission remains with the compiler."""
    rows = json.loads((root / 'ExcelOutput/StageConfig.json').read_text(encoding='utf-8'))
    choices = []
    seen = set()
    for row in rows:
        stage_id = str(row['StageID'])
        if stage_id in seen:
            raise ValueError(f'duplicate stage source identity:{stage_id}')
        seen.add(stage_id)
        choices.append({
            'stage_id': stage_id, 'name': text_map.get(str(row.get('StageName', {}).get('Hash')), stage_id),
            'stage_type': row.get('StageType', ''), 'level': row.get('Level'),
            'wave_count': len(row.get('MonsterList', [])),
            'coverage_status': 'discovered_only', 'source_path': 'ExcelOutput/StageConfig.json',
        })
    return choices


def build_battle_rulebook(root: Path, scenario_data: dict[str, Any], *, include_equipment: bool = False) -> RuleBook:
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
    stage_scope = scenario.battle_setup.metadata.get("stage_scope")
    if stage_scope not in {"wave_only", "full_stage"}:
        raise ValueError("CLI requires metadata.stage_scope=wave_only or full_stage")
    rows = json.loads((root / "ExcelOutput/StageConfig.json").read_text(encoding="utf-8"))
    selected = [row for row in rows if str(row.get("StageID")) == stage_id]
    if len(selected) != 1:
        raise ValueError("stage source is missing or ambiguous")
    waves = selected[0].get("MonsterList", [])
    if not isinstance(waves, list) or not waves:
        raise ValueError("CLI requires at least one source wave")
    for wave in waves:
        if not isinstance(wave, dict):
            raise ValueError("stage monster wave must be an object")
        monsters.update(str(value) for value in wave.values())
    equipment = include_equipment or any(unit.character_build is not None and (
        unit.character_build.equipment_build.light_cone is not None
        or unit.character_build.equipment_build.relics
    ) for unit in scenario.units)
    ir = TBGDLowering(root).build(
        avatar_ids=avatars, monster_ids=frozenset(monsters),
        stage_ids=frozenset({stage_id}), include_equipment=equipment,
        include_stage_environment=stage_scope == "full_stage",
    )
    rules = RuleBook(ir)
    if stage_scope == "full_stage":
        definition = rules.wave_definition_for_stage(stage_id)
        if definition is None or definition.stage_environment_status != "executable":
            reason = definition.stage_environment_blocked_reason if definition else "stage_environment_definition_missing"
            raise ValueError(f"stage environment blocked: {reason}")
    return rules
