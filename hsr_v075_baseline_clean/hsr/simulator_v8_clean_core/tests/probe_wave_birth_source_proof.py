"""Real-source diagnostic for wave birth; never alters admission or raw data."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from simulator_v8_clean_core.systems.unit_spawn import UnitSpawnRequest, UnitSpawnSystem
from simulator_v8_clean_core.tbgd.lowering import (
    ENTITY_TABLES,
    TBGDLowering,
    _wave_enemy_birth_template,
)
from simulator_v8_clean_core.tbgd.monster_cards import build_monster_card_ir


PIN = "14c1d18f91a8101d610e6c523447a7517de3fae1"
EXPECTED = (
    "unit_birth_template_materialization_invalid:"
    "unit_spawn_plan_unit_flags_monster_rank_source_trace_evidence_missing"
)


def emit(label: str, value: object) -> None:
    print(label + "=" + json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


def main() -> int:
    root = Path("turnbasedgamedata-main").resolve()
    actual = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != PIN:
        raise ValueError(f"TBGD pin mismatch: {actual}")
    emit("pinned_tbgd", actual)
    lowerer = TBGDLowering(root)
    # Use the same producers as build(), restricted to the wave dependency family.
    # Full original tables preserve authored row indices; no synthetic IR or defaults.
    entities = []
    for name in ("MonsterConfig", "MonsterTemplateConfig"):
        relative = f"ExcelOutput/{name}.json"
        entities.extend(lowerer._lower_entity_table(relative, ENTITY_TABLES[relative]))
    profiles = lowerer._lower_combatant_profiles()
    by_entity = {profile.entity_id: profile for profile in profiles}
    for entity_ref in ("monster:1022020", "monster:1023010"):
        profile = by_entity[entity_ref]
        emit("profile", {
            "entity_ref": entity_ref,
            "coverage_status": profile.coverage_status,
            "blocked_reason": profile.blocked_reason,
            "base_stats": profile.base_stats,
        })
    cards = build_monster_card_ir(root, max_records_per_table=None).monster_data_cards
    by_card = {card.entity_ref: card for card in cards}
    definitions = lowerer._lower_wave_definitions(entities, profiles, cards)
    selected = [definition for definition in definitions if definition.stage_id == "103201"]
    if len(selected) != 1:
        raise ValueError(f"Stage103201 definition count: {len(selected)}")
    definition = selected[0]
    emit("definition", {
        "id": definition.wave_definition_id,
        "coverage_status": definition.coverage_status,
        "blocked_reason": definition.blocked_reason,
        "level_policy": definition.level_policy,
    })
    timeline = lowerer._lower_timeline_rules()[0]
    scores = lowerer._monster_rank_scores()
    outcomes = []
    for entry in definition.entries:
        template = _wave_enemy_birth_template(
            definition, entry, by_entity.get(entry.monster_entity_ref),
            by_card.get(entry.monster_entity_ref), timeline, scores,
        )
        request = UnitSpawnRequest(
            spawn_kind="wave_enemy",
            unit_id=f"enemy:stage:{definition.stage_id}:wave:{entry.wave_index}:pos:{entry.position}",
            birth_template_id=entry.birth_template_id,
            entity_ref=entry.monster_entity_ref,
            source_id=definition.wave_definition_id,
            entry_id=entry.entry_id,
            wave_definition_id=definition.wave_definition_id,
            stage_id=definition.stage_id,
            wave_index=entry.wave_index,
            position=entry.position,
            source_trace=definition.source.to_json(),
            entry_source_trace=entry.source.to_json(),
        )
        plan = UnitSpawnSystem().plan(template, request)
        record = {
            "entity_ref": request.entity_ref,
            "entry_id": request.entry_id,
            "unit_id": request.unit_id,
            "position": request.position,
            "birth_template_id": template.birth_template_id,
            "template_status": template.coverage_status,
            "template_blocked_reason": template.blocked_reason,
            "rank_source": template.flag_specs.get("monster_rank_source_trace"),
            "plan.ok": plan.ok,
            "plan.blocked_reason": plan.blocked_reason,
        }
        if plan.ok:
            unit = plan.to_unit(expected_request=request, expected_template=template, owner=None)
            record["materialized_unit_id"] = unit.unit_id
        emit("wave_birth", record)
        outcomes.append(record)
    Path("/tmp/r6a-reproduction.json").write_text(
        json.dumps(outcomes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if outcomes and outcomes[0]["plan.blocked_reason"] == EXPECTED:
        emit("verdict", "R6-G01 reproduced before production edits")
        return 0
    emit("verdict", "NEEDS_REPLAN: inspect actual earlier blocker or successful materialization")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
