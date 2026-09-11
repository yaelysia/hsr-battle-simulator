"""Real pinned wave-source regression; no full character/equipment lowering.

Requires the repository's pinned TBGD checkout. The subsequent-wave test starts
at a cleared-wave boundary: its inert ally is a fixture, not a character build
or evidence that attacks, AI, StageAbility or an entire battle were executed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core import BASELINE_VERSION
from simulator_v8_clean_core.core.model import BattleState, UnitState
from simulator_v8_clean_core.core.reducer import MutationReducer
from simulator_v8_clean_core.rules.ir import (
    CanonicalIR,
    WaveDefinitionIR,
    WaveMonsterEntryIR,
)
from simulator_v8_clean_core.rules.rulebook import RuleBook
from simulator_v8_clean_core.scenarios.build_state import _wave_unit_spec
from simulator_v8_clean_core.systems.unit_spawn import (
    UnitSpawnPlan,
    UnitSpawnRequest,
    UnitSpawnSystem,
    _required_source_trace_identity,
)
from simulator_v8_clean_core.systems.wave import WAVE_RUNTIME_SCHEMA_VERSION, WaveSystem
from simulator_v8_clean_core.tbgd.lowering import (
    ENTITY_TABLES,
    TBGDLowering,
    _lower_unit_birth_templates,
)
from simulator_v8_clean_core.tbgd.monster_cards import build_monster_card_ir


@dataclass(frozen=True, repr=False)
class WaveSources:
    rules: RuleBook
    raw_stages: list[dict]
    rank_table: dict


@pytest.fixture(scope="module")
def wave_sources() -> WaveSources:
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    assert (root / "ExcelOutput/StageConfig.json").is_file(), (
        "pinned TBGD checkout required"
    )
    lowerer = TBGDLowering(root)
    # The same family producers used by build(); all original rows are kept so
    # row indices and provenance are not changed by fixture filtering.
    entities = []
    for name in ("MonsterConfig", "MonsterTemplateConfig"):
        relative = f"ExcelOutput/{name}.json"
        entities.extend(lowerer._lower_entity_table(relative, ENTITY_TABLES[relative]))
    profiles = lowerer._lower_combatant_profiles()
    cards = build_monster_card_ir(root, max_records_per_table=None).monster_data_cards
    waves = lowerer._lower_wave_definitions(entities, profiles, cards)
    timeline = lowerer._lower_timeline_rules()
    templates = _lower_unit_birth_templates(
        summon_monster_intents=[],
        servant_definitions=[],
        wave_definitions=waves,
        combatant_profiles=profiles,
        monster_data_cards=cards,
        timeline_rules=timeline,
        monster_rank_scores=lowerer._monster_rank_scores(),
    )
    rules = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            entities=tuple(entities),
            combatant_profiles=tuple(profiles),
            monster_data_cards=tuple(cards),
            wave_definitions=tuple(waves),
            unit_birth_templates=tuple(templates),
            timeline_rules=tuple(timeline),
        )
    )
    return WaveSources(
        rules,
        json.loads((root / "ExcelOutput/StageConfig.json").read_text()),
        json.loads((root / "Config/GlobalConfig/GameCoreConstValue.json").read_text())[
            "MonsterRankScore"
        ],
    )


def request_for(
    definition: WaveDefinitionIR, entry: WaveMonsterEntryIR
) -> UnitSpawnRequest:
    return UnitSpawnRequest(
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


def first_wave(sources: WaveSources):
    definition = sources.rules.wave_definition_for_stage("103201")
    assert definition is not None and definition.coverage_status == "executable"
    return definition, sources.rules.wave_entries_for_wave(
        definition.wave_definition_id, 0
    )


def materialize(
    sources: WaveSources, definition: WaveDefinitionIR, entry: WaveMonsterEntryIR
):
    template = sources.rules.unit_birth_template(entry.birth_template_id)
    assert template is not None and template.coverage_status == "executable"
    request = request_for(definition, entry)
    before = deepcopy(template.to_json())
    plan = UnitSpawnSystem().plan(template, request)
    assert plan.ok, plan.blocked_reason
    unit = plan.to_unit(
        expected_request=request, expected_template=template, owner=None
    )
    assert template.to_json() == before
    proof = unit.flags["monster_rank_source_trace"]
    rank = proof["raw_id"]
    assert proof["source_path"] == "Config/GlobalConfig/GameCoreConstValue.json"
    assert proof["raw_type"] == "MonsterRankScore"
    assert proof["evidence"] == {
        "raw_path": f"MonsterRankScore.{rank}.Value",
        "rank": rank,
        "value": sources.rank_table[rank]["Value"],
    }
    assert unit.unit_id == request.unit_id and unit.template_id == request.entity_ref
    for key in ("stage_id", "wave_definition_id", "wave_index", "position"):
        assert unit.flags[key] == getattr(request, key)
    assert unit.flags["wave_entry_id"] == request.entry_id
    assert unit.flags["wave_entry_source_trace"] == entry.source.to_json()
    print(
        json.dumps(
            {
                "stage": definition.stage_id,
                "entry": entry.entry_id,
                "unit": unit.unit_id,
                "template": template.birth_template_id,
                "plan.ok": plan.ok,
                "plan.blocked_reason": plan.blocked_reason,
                "rank_proof": proof,
            },
            sort_keys=True,
        )
    )
    return unit


def test_real_first_wave_and_duplicate_slots(wave_sources: WaveSources) -> None:
    definition, entries = first_wave(wave_sources)
    assert [(e.position, e.monster_raw_id) for e in entries] == [
        (0, "1022020"),
        (1, "1023010"),
        (2, "1022020"),
    ]
    units = [materialize(wave_sources, definition, entry) for entry in entries]
    assert entries[0].birth_template_id == entries[2].birth_template_id
    assert len({e.entry_id for e in entries}) == len({u.unit_id for u in units}) == 3
    # Also exercise the actual initial-wave consumer, not only a manual request.
    for entry, unit in zip(entries, units, strict=True):
        spec = _wave_unit_spec(wave_sources.rules, definition, entry, unit.unit_id)
        assert spec.panel is not None and spec.panel.flags == unit.flags
        assert spec.panel.max_hp == unit.max_hp and spec.panel.speed == unit.speed


@pytest.mark.parametrize("field", ["evidence", "source_path", "raw_type", "raw_id"])
def test_invalid_proof_rejected(wave_sources: WaveSources, field: str) -> None:
    definition, entries = first_wave(wave_sources)
    original = wave_sources.rules.unit_birth_template(entries[0].birth_template_id)
    assert original is not None
    flags = deepcopy(original.flag_specs)
    if field == "evidence":
        del flags["monster_rank_source_trace"][field]
    else:
        flags["monster_rank_source_trace"][field] = ""
    proof = flags["monster_rank_source_trace"]
    assert proof in formal_source_objects(flags)
    with pytest.raises(ValueError, match=f"catalog_source_{field}_missing"):
        _required_source_trace_identity(proof, "catalog_source")
    template = replace(original, flag_specs=flags)
    before = deepcopy(template.to_json())
    plan = UnitSpawnSystem().plan(template, request_for(definition, entries[0]))
    assert not plan.ok and not plan.unit
    assert plan.blocked_reason.endswith(f"monster_rank_source_trace_{field}_missing")
    assert template.to_json() == before
    print("negative=" + plan.blocked_reason)


@pytest.mark.parametrize(
    "field", ["stage_id", "wave_definition_id", "entity_ref", "source_trace"]
)
def test_request_mismatch_rejected(wave_sources: WaveSources, field: str) -> None:
    definition, entries = first_wave(wave_sources)
    template = wave_sources.rules.unit_birth_template(entries[0].birth_template_id)
    assert template is not None
    request = request_for(definition, entries[0])
    value = (
        {**request.source_trace, "raw_id": "invalid:stage"}
        if field == "source_trace"
        else "invalid:identity"
    )
    malformed = replace(request, **{field: value})
    plan = UnitSpawnSystem().plan(template, malformed)
    assert not plan.ok and not plan.unit and "mismatch" in plan.blocked_reason
    print("negative=" + plan.blocked_reason)


def test_real_subsequent_wave(wave_sources: WaveSources) -> None:
    ordinary = {
        str(row["StageID"])
        for row in wave_sources.raw_stages
        if row.get("StageType") == "Mainline"
    }
    candidates = [
        w
        for w in wave_sources.rules.ir.wave_definitions
        if w.stage_id in ordinary
        and w.coverage_status == "executable"
        and w.wave_count > 1
        and not w.stage_ability_refs
    ]
    assert candidates, "real ordinary multi-wave denominator must not be empty"
    definition = min(candidates, key=lambda w: (len(w.entries), int(w.stage_id)))
    initial = [
        materialize(wave_sources, definition, entry)
        for entry in definition.entries
        if entry.wave_index == 0
    ]
    assert initial
    # Explicit cleared-wave boundary fixture, not fabricated TBGD stage content.
    ally = UnitState(
        unit_id="fixture:inert_ally", side="ally", template_id="fixture:inert_ally"
    )
    units = {
        unit.unit_id: replace(unit, hp=0.0, lifecycle_status="defeated")
        for unit in initial
    }
    units[ally.unit_id] = ally
    state = BattleState(
        units=units,
        global_flags={
            "wave_runtime": {
                "schema_version": WAVE_RUNTIME_SCHEMA_VERSION,
                "wave_definition_id": definition.wave_definition_id,
                "stage_id": definition.stage_id,
                "current_wave_index": 0,
                "total_waves": definition.wave_count,
                "current_wave_unit_ids": [unit.unit_id for unit in initial],
                "status": "active",
                "started_wave_indices": [0],
                "cleared_wave_indices": [],
                "source_trace": definition.source.to_json(),
            }
        },
    )
    before = state.snapshot().to_json()
    system = WaveSystem(wave_sources.rules)
    plan = system.plan_transition(state)
    assert plan.ok and plan.status == "advance_to_next_wave", plan.blocked_reason
    assert plan.spawn_requests
    for request, encoded in zip(
        plan.spawn_requests, plan.spawn_unit_plans, strict=True
    ):
        template = wave_sources.rules.unit_birth_template(request.birth_template_id)
        assert template is not None
        unit = UnitSpawnPlan.from_json(encoded).to_unit(
            expected_request=request, expected_template=template, owner=None
        )
        assert unit.flags["monster_rank_source_trace"]["evidence"]
    result = system.apply_transition(state, plan)
    assert result.plan.ok and result.mutations, result.plan.blocked_reason
    assert state.snapshot().to_json() == before
    after = MutationReducer().apply_all(state, result.mutations)
    assert after.wave_index == 1
    assert all(
        after.units[unit.unit_id].lifecycle_status == "removed" for unit in initial
    )
    for request in plan.spawn_requests:
        assert after.units[request.unit_id].lifecycle_status == "active"
        assert after.units[request.unit_id].flags["wave_entry_id"] == request.entry_id
    replay = MutationReducer().replay_snapshot(
        state, result.mutations, after.snapshot().to_json()
    )
    assert replay.ok, replay.errors
    print(
        json.dumps(
            {
                "subsequent_stage": definition.stage_id,
                "wave": 1,
                "spawned": [r.unit_id for r in plan.spawn_requests],
                "mutation_count": len(result.mutations),
                "replay_ok": replay.ok,
            },
            sort_keys=True,
        )
    )


def formal_source_objects(value: object) -> Iterator[Mapping]:
    """Walk JSON containers, stopping at the formal consumer's identity boundary."""
    if isinstance(value, dict):
        if {"source_path", "raw_type", "raw_id"} <= value.keys():
            yield value
            return
        for nested in value.values():
            yield from formal_source_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from formal_source_objects(nested)


def test_catalog_stops_at_identity_not_at_evidence_key() -> None:
    locator = {"source_path": "fixture.json", "raw_type": "Fixture", "raw_id": "1"}
    proof = {**locator, "evidence": {"template_source": locator}}
    # A key named evidence in an ordinary container is not an exclusion rule.
    payload = {"evidence": [proof], "sibling": {"nested": proof}}
    sources = list(formal_source_objects(payload))
    assert sources == [proof, proof]
    for source in sources:
        _required_source_trace_identity(source, "catalog_source")


def test_wave_enemy_consumer_source_proof_catalog(wave_sources: WaveSources) -> None:
    templates = wave_sources.rules.ir.unit_birth_templates
    assert templates and all(t.spawn_kind == "wave_enemy" for t in templates)
    # Independent raw StageConfig roster denominator, before any runtime admission.
    expected = {
        f"unit_birth_template:wave:{row['StageID']}:{monster}"
        for row in wave_sources.raw_stages
        for wave in row.get("MonsterList", [])
        for key, monster in wave.items()
        if key.startswith("Monster")
    }
    actual = {t.birth_template_id for t in templates}
    assert expected == actual, {
        "missing": sorted(expected - actual)[:5],
        "unexpected": sorted(actual - expected)[:5],
    }
    assert len(templates) == len(actual) == len(expected) == 59940
    count = missing = 0
    digest = sha256()
    for template in sorted(templates, key=lambda t: t.birth_template_id):
        payload = template.to_json()
        for source in formal_source_objects(payload):
            count += 1
            missing += not isinstance(source.get("evidence"), Mapping)
            # Reuse the production identity/evidence validator, including empty
            # or non-string identity rejection; evidence payload is not recursed.
            _required_source_trace_identity(source, "catalog_source")
        # Compare actual parent/candidate birth arithmetic and request identities,
        # without copying the large, repetitive audit payload or any formula.
        neutral = {
            "id": template.birth_template_id,
            "entity_ref": template.entity_ref,
            "fields": template.unit_field_specs,
            "resources": template.resource_specs,
            "request_contract": template.request_contract,
            "coverage_status": template.coverage_status,
            "blocked_reason": template.blocked_reason,
        }
        digest.update(
            json.dumps(neutral, sort_keys=True, separators=(",", ":")).encode()
        )
    print(
        json.dumps(
            {
                "wave_enemy_template_count": len(templates),
                "formal_consumer_source_identity_count": count,
                "missing_formal_evidence_count": missing,
                "behavior_and_identity_sha256": digest.hexdigest(),
            },
            sort_keys=True,
        )
    )
    assert count > 0 and missing == 0
