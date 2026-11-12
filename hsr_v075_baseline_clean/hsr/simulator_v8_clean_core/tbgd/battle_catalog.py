"""Compile the complete source graphs selected by a local battle scenario."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..content_processors import mount_catalog_processors
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
    avatars = {unit.entity_ref.split(":", 1)[1] for unit in scenario.units
               if unit.entity_ref.startswith("avatar:")}
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
    # A fixed pool lets multiple teams/stages share one existing IR cache slot.
    # It is persisted with the scenario so replay rebuilds the same RuleBook.
    pool = scenario.battle_setup.metadata.get("compile_scope", {})
    if not isinstance(pool, dict) or set(pool) - {
        "avatar_ids", "stage_ids", "include_equipment", "include_stage_environment",
        "light_cone_ids", "relic_template_ids",
    }:
        raise ValueError("invalid compile_scope")
    for name in ("avatar_ids", "stage_ids", "light_cone_ids", "relic_template_ids"):
        values = pool.get(name, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.isdecimal() for v in values):
            raise ValueError(f"compile_scope.{name} requires source ID strings")
    for name in ("include_equipment", "include_stage_environment"):
        if name in pool and type(pool[name]) is not bool:
            raise ValueError(f"compile_scope.{name} requires a boolean")
    avatars.update(pool.get("avatar_ids", []))
    stages = {stage_id, *pool.get("stage_ids", [])}
    rows = json.loads((root / "ExcelOutput/StageConfig.json").read_text(encoding="utf-8"))
    for selected_stage in sorted(stages):
        selected = [row for row in rows if str(row.get("StageID")) == selected_stage]
        if len(selected) != 1:
            raise ValueError("stage source is missing or ambiguous")
        waves = selected[0].get("MonsterList", [])
        if not isinstance(waves, list) or not waves:
            raise ValueError("CLI requires at least one source wave")
        for wave in waves:
            if not isinstance(wave, dict):
                raise ValueError("stage monster wave must be an object")
            monsters.update(str(value) for value in wave.values())
    light_cones = set(pool.get('light_cone_ids', ()))
    relic_templates = set(pool.get('relic_template_ids', ()))
    for unit in scenario.units:
        if unit.character_build is not None:
            build = unit.character_build.equipment_build
            if build.light_cone is not None:
                light_cones.add(build.light_cone.definition_key.definition_identity)
            relic_templates.update(relic.template_key.definition_identity for relic in build.relics)
    full_equipment = include_equipment or pool.get('include_equipment', False)
    equipment = full_equipment or bool(light_cones or relic_templates)
    ir = TBGDLowering(root).build(
        avatar_ids=frozenset(avatars), monster_ids=frozenset(monsters),
        stage_ids=frozenset(stages), include_equipment=equipment,
        light_cone_ids=None if full_equipment else frozenset(light_cones),
        relic_template_ids=None if full_equipment else frozenset(relic_templates),
        include_stage_environment=stage_scope == "full_stage" or pool.get("include_stage_environment", False),
    )
    rules = RuleBook(ir)
    # Assembly: mount content-specific processors for content present in the
    # compiled IR (generic catalog lookup; no content branching in the kernel).
    rules = mount_catalog_processors(rules)
    if stage_scope == "full_stage":
        definition = rules.wave_definition_for_stage(stage_id)
        if definition is None or definition.stage_environment_status != "executable":
            reason = definition.stage_environment_blocked_reason if definition else "stage_environment_definition_missing"
            raise ValueError(f"stage environment blocked: {reason}")
    return rules
