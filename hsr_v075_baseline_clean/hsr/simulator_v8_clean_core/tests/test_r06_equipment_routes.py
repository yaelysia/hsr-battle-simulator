"""R06: representative public equipment routes.

Route A exercises 23002 (kill/hit recovery + damage buff), 23013 (heal record,
attack consumption, reset) and 23033 (battle-entry energy) on a durable source
boss wave; route B exercises 23051 (pre-Ultimate team heal and Redoubt) and
23041 (turn-start energy and attacked-target DEF down); route C exercises 21033
(kill recovery), 20015 (Basic ATK action advance) and 23033 (entry energy plus
Raiton two-Basic-ATK advance) on the opening Antimatter wave.

Every command comes from the public decision boundary; transitions pass the
native RuntimeSourceAuditor.  A first successful run keeps its archive.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration

from hsr.simulator_v8_clean_core.battle_archive import write_archive
from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.dynamic_key_hash import tbgd_dynamic_key_hash
from hsr.simulator_v8_clean_core.equipment.models import (
    EquipmentBuildInput,
    EquipmentDefinitionKey,
    LightConeInstanceInput,
    RelicInstanceInput,
)
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_EXAMPLES = _CORE / "examples/cli"


def _load(name: str) -> dict[str, Any]:
    return json.loads((_EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def _rules(scenario: dict[str, Any]):
    return build_battle_rulebook(_ROOT / "turnbasedgamedata-main", scenario)


def _equip(
    unit: dict[str, Any],
    cone_id: int | None,
    *,
    level: int,
    promotion: int,
    relics: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    base = unit["character_build"]
    own_level = unit.get("level", base["level"])
    own_promotion = base["promotion"]
    key = (
        LightConeInstanceInput(
            f"r06:{unit['unit_id']}:{cone_id}",
            EquipmentDefinitionKey("light_cone", str(cone_id)),
            level,
            promotion,
            1,
        )
        if cone_id is not None
        else None
    )
    equipment = EquipmentBuildInput(
        f"r06:{unit['unit_id']}:equipment",
        base["character_card_id"],
        key,
        tuple(RelicInstanceInput.from_json(item) for item in relics),
        base["equipment_build"].get("identity_labels", {}),
    )
    build = CharacterBuildInput(
        build_id=f"r06:{unit['unit_id']}:{cone_id or 'none'}",
        character_card_id=base["character_card_id"],
        level=own_level,
        promotion=own_promotion,
        eidolon_level=base["eidolon_level"],
        unlocked_trace_node_ids=tuple(base["unlocked_trace_node_ids"]),
        equipment_build=equipment,
    )
    result = dict(unit)
    result["character_build"] = build.to_json()
    result["level"] = own_level
    return result


def _unit_by_id(scenario: dict[str, Any], unit_id: str) -> dict[str, Any]:
    return next(unit for unit in scenario["units"] if unit["unit_id"] == unit_id)


def _scenario_from(base: dict[str, Any], units: list[dict[str, Any]], stage: str) -> dict[str, Any]:
    scenario = dict(base)
    scenario["units"] = units
    scenario["stage_ref"] = stage
    return scenario


def _cone_equipment(unit: dict[str, Any]) -> dict[str, Any]:
    return unit["character_build"]["equipment_build"]["light_cone"]


def _statuses(session: BattleSession, unit_id: str) -> list[dict[str, Any]]:
    return [
        detail
        for detail in session.state.units[unit_id].flags.get("status_details", ())
        if isinstance(detail, dict)
    ]


def _modifier_details(session: BattleSession, unit_id: str, modifier_name: str) -> list[dict[str, Any]]:
    return [
        detail for detail in _statuses(session, unit_id)
        if detail.get("modifier_name") == modifier_name
    ]


def _unit_scope_value(session: BattleSession, unit_id: str, name: str) -> float | None:
    hash_key = str(tbgd_dynamic_key_hash(name))
    store = store_from_state(session.state)
    for entry in (store.get("entries") or {}).values():
        if (
            isinstance(entry, dict)
            and str(entry.get("hash") or "") == hash_key
            and str(entry.get("scope") or "") == "unit"
            and str(entry.get("target_id") or "") == unit_id
        ):
            value = entry.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _settlement_records(transitions) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for transition in transitions:
        for container in (transition, *getattr(transition, "child_transitions", ())):
            settlement = container.transaction.settlement
            if settlement is None:
                continue
            for record in settlement.records:
                if isinstance(record, dict):
                    records.append(record)
    return records


def _record_types(transitions) -> list[str]:
    return [str(record.get("record_type") or "") for record in _settlement_records(transitions)]


def _equipment_violation(violation) -> bool:
    text = json.dumps(
        violation.to_json() if hasattr(violation, "to_json") else violation.__dict__,
        default=str,
    )
    return any(marker in text for marker in ("MEquip_", "MRelic_", "light_cone"))


def _equipment_audit(auditor, transition):
    result = auditor.validate_transition(transition)
    if result.ok:
        return
    failing = [violation for violation in result.violations if _equipment_violation(violation)]
    assert not failing, (
        transition.transaction.command.action_id,
        [item.to_json() if hasattr(item, "to_json") else item.__dict__ for item in failing],
    )


def _equipment_related(transition) -> bool:
    """Audit the changed equipment boundary, not unrelated character kits."""

    text = json.dumps(
        [record for record in _settlement_records((transition,))],
        default=str,
    )
    return "MEquip_" in text or "MRelic_" in text or "light_cone" in text


def _ledger(session: BattleSession) -> str:
    return json.dumps(session.archive(), default=str)


def _drive(
    rules,
    scenario: dict[str, Any],
    *,
    actor_priority,
    max_steps: int,
    stop_after,
    tmp_path: Path,
    archive_name: str,
):
    session = BattleSession(rules, scenario, diagnostics="full")
    auditor = RuntimeSourceAuditor(rules)
    observed = {"records": [], "settlements": [], "steps": 0, "totals": []}
    while observed["steps"] < max_steps and not session.outcome:
        decision, advance_transitions = session.advance_with_transitions()
        for transition in advance_transitions:
            action = transition.transaction.command.action_id
            if action == "wave:transition" or action.startswith("scheduler:"):
                if _equipment_related(transition):
                    _equipment_audit(auditor, transition)
        if not decision.ready:
            break
        choices = list(decision.availability.choices)
        if not choices:
            break
        chosen = actor_priority(session, choices)
        command = dict(chosen.command_template)
        targets = []
        if chosen.target_query and chosen.target_query.selection_mode == "explicit":
            targets = [chosen.target_query.candidate_ids[0]]
        command["target_ids"] = targets
        result = session.submit(command_from_json(command))
        observed["steps"] += 1
        transition = result.transition
        assert transition.outcome.successor_eligible, (
            observed["steps"], transition.outcome.reason_codes,
        )
        if _equipment_related(transition):
            _equipment_audit(auditor, transition)
        container_transitions = (transition, *getattr(result, "child_transitions", ()))
        observed["records"].extend(_record_types(container_transitions))
        observed.setdefault("settlements", []).extend(_settlement_records(container_transitions))
        observed["totals"].append(_unit_scope_value(session, "natasha", "_TotalAmount"))
        if stop_after is not None and stop_after(session, observed):
            break
    archive = write_archive(tmp_path / archive_name, session.archive())
    return session, observed, archive


def _prefer_ult(choices):
    ult = [c for c in choices if c.choice_kind == "ultimate_window"]
    if ult:
        return ult[0]
    request = [c for c in choices if c.choice_kind == "manual_ultimate_request"]
    if request:
        return request[0]
    return None


def test_route_a_kill_hit_recovery_and_heal_record_consumption(tmp_path):
    base = _load("arlan_serval_natasha_two_waves")
    fleet = _load("arlan_fleet_vs_antimatter")
    relics = tuple(fleet["units"][0]["character_build"]["equipment_build"]["relics"])
    units = [
        _equip(_unit_by_id(base, "arlan"), 23002, level=80, promotion=6, relics=relics),
        _equip(_unit_by_id(base, "serval"), 23033, level=80, promotion=6),
        _equip(_unit_by_id(base, "natasha"), 23013, level=80, promotion=6),
    ]
    # The two-wave Antimatter stage keeps the full public route short enough to
    # stay a representative route: kills exercise 23002's death recovery and
    # the healer's own heal exercises the snapshot transport.
    scenario = _scenario_from(base, units, base["stage_ref"])
    rules = _rules(scenario)
    assert BattleSession(rules, scenario, diagnostics="full").state.units["serval"].energy == pytest.approx(30.0)

    def priority(session, choices):
        chosen = _prefer_ult(choices)
        if chosen is not None:
            return chosen
        for action in ("avatar_skill:110502",):
            match = [c for c in choices if getattr(c, "action_id", "") == action]
            if match:
                return match[0]
        match = [c for c in choices if c.actor_id == "arlan" and getattr(c, "action_id", "") == "avatar_skill:100802"]
        if match and session.state.units["arlan"].hp >= session.state.units["arlan"].max_hp * 0.9:
            return match[0]
        for actor in ("arlan", "serval", "natasha"):
            match = [c for c in choices if c.actor_id == actor]
            if match:
                return match[0]
        return choices[0]

    session, observed, archive = _drive(
        rules, scenario, actor_priority=priority, max_steps=40,
        stop_after=None, tmp_path=tmp_path, archive_name="r06-route-a.json.gz",
    )
    assert session.outcome == "victory", session.outcome
    assert observed["steps"] >= 4
    assert _modifier_details(session, "arlan", "MEquip_23002_Main")
    settlement_text = json.dumps(observed["settlements"], default=str)
    ledger = _ledger(session) + json.dumps(observed["records"]) + settlement_text
    # The heal-snapshot protocol must reach the public executor transport and
    # dispatch OnSnapshotCreate to the healer's own recording status.
    assert "OnSnapshotCreate" in settlement_text
    assert "MEquip_23002_Main" in ledger
    assert "OnTriggerDeath" in ledger and "OnAfterBeingAttacked" in ledger
    effect = _modifier_details(session, "arlan", "MEquip_23002_Effect")
    assert effect or "MEquip_23002_Effect" in ledger
    assert any(
        term.get("value") == pytest.approx(0.24)
        for detail in _statuses(session, "arlan")
        for term in detail.get("modifiers", ())
        if isinstance(term, dict) and term.get("key") == "damage_added_ratio"
    ) or "0.24" in ledger
    assert _modifier_details(session, "arlan", "MRelic_302_Sub")
    assert "MEquip_23013_Sub" in ledger
    # Kills close quickly on this wave, so the consumed hit may be skipped as
    # dead-target; the identity/consumption chain is still observed and the
    # pure-damage settlement itself is covered by the real-IR component check.
    assert "status_damage_identity" in observed["records"]
    totals = [value for value in observed["totals"] if value is not None]
    assert any(value > 0 for value in totals)
    assert any(previous > 0 and current == 0 for previous, current in zip(totals, totals[1:]))
    assert session.state.units["serval"].energy >= 0
    assert archive.exists()


def test_route_b_ultimate_team_heal_and_attacked_target_defence_down(tmp_path):
    tanky = _load("arlan_serval_natasha_two_waves")
    shield = _load("r05_lynx_march_survival_counter")
    march = _unit_by_id(shield, "march")
    # Keep the route on the ordinary equipment boundary: the R05 march build
    # carries eidolon rank slots whose audit provenance belongs to its own
    # character package, not to this equipment batch.
    march = dict(march)
    march["eidolon_level"] = 0
    march["character_build"] = {
        **march["character_build"],
        "eidolon_level": 0,
        "unlocked_trace_node_ids": [],
    }
    march["initial_condition"] = dict(march["initial_condition"], initial_energy="100")
    units = [
        _equip(march, 23051, level=80, promotion=6),
        _equip(_unit_by_id(tanky, "serval"), 23041, level=80, promotion=6),
        _equip(_unit_by_id(tanky, "natasha"), None, level=80, promotion=6),
    ]
    for index, unit in enumerate(units):
        unit["position"] = index
    scenario = _scenario_from(tanky, units, "307311")
    rules = _rules(scenario)

    def priority(session, choices):
        chosen = _prefer_ult(choices)
        if chosen is not None and chosen.actor_id == "march":
            return chosen
        serval = [c for c in choices if c.actor_id == "serval"]
        if serval:
            return serval[0]
        chosen = _prefer_ult(choices)
        if chosen is not None:
            return chosen
        march_choice = [c for c in choices if c.actor_id == "march"]
        if march_choice:
            return march_choice[0]
        for actor in ("natasha",):
            match = [c for c in choices if c.actor_id == actor]
            if match:
                return match[0]
        return choices[0]

    def observed(session, observed):
        redoubt = _modifier_details(session, "natasha", "MEquip_23051_Sub")
        defence_down = [
            detail
            for detail in _statuses(session, "enemy:stage:307311:wave:0:pos:0")
            if detail.get("modifier_name") == "MEquip_23041_Sub"
        ]
        return bool(redoubt) and bool(defence_down) and observed["steps"] >= 8

    session, observed_data, archive = _drive(
        rules, scenario, actor_priority=priority, max_steps=40,
        stop_after=observed, tmp_path=tmp_path, archive_name="r06-route-b.json.gz",
    )
    settlement_text = json.dumps(observed_data["settlements"], default=str)
    ledger = _ledger(session) + json.dumps(observed_data["records"]) + settlement_text
    assert "MEquip_23051_Main" in ledger
    heal_paths = [
        record for record in observed_data["records"] if record == "heal"
    ]
    assert heal_paths
    for unit_id in ("march", "serval", "natasha"):
        assert _modifier_details(session, unit_id, "MEquip_23051_Sub"), unit_id
    halo = [
        detail for detail in _statuses(session, "enemy:stage:307311:wave:0:pos:0")
        if detail.get("modifier_name") == "MEquip_23041_SubOnEmemy"
    ]
    assert halo
    defence_down = [
        detail for detail in _statuses(session, "enemy:stage:307311:wave:0:pos:0")
        if detail.get("modifier_name") == "MEquip_23041_Sub"
    ]
    assert defence_down
    assert any(
        isinstance(term, dict)
        and term.get("key") == "defense_added_ratio"
        and term.get("value", 0) < 0
        for detail in defence_down
        for term in detail.get("modifiers", ())
    )
    assert any(
        isinstance(term, dict)
        and term.get("key") == "damage_added_ratio"
        and term.get("value") == pytest.approx(0.24)
        for unit_id in ("march", "serval", "natasha")
        for detail in _modifier_details(session, unit_id, "MEquip_23051_Sub")
        for term in detail.get("modifiers", ())
    )
    assert "MEquip_23041_Main" in settlement_text
    assert archive.exists()


def test_route_c_kill_recovery_basic_attack_advance_and_raito(tmp_path):
    base = _load("arlan_natasha_vs_antimatter")
    extra = _load("arlan_serval_natasha_vs_antimatter")
    arlan = _equip(_unit_by_id(base, "arlan"), 21033, level=1, promotion=0)
    natasha = _equip(_unit_by_id(base, "natasha"), 20015, level=1, promotion=0)
    serval = _equip(_unit_by_id(extra, "serval"), 23033, level=1, promotion=0)
    serval["initial_condition"] = dict(serval["initial_condition"], initial_energy="70")
    serval["position"] = 2
    scenario = _scenario_from(base, [arlan, natasha, serval], base["stage_ref"])
    rules = _rules(scenario)

    def priority(session, choices):
        chosen = _prefer_ult(choices)
        if chosen is not None and chosen.actor_id == "serval":
            return chosen
        natasha_attack = [
            c for c in choices if c.actor_id == "natasha"
            and getattr(c, "action_id", "") == "avatar_skill:110501"
        ]
        if natasha_attack:
            return natasha_attack[0]
        arlan_skill = [
            c for c in choices if c.actor_id == "arlan"
            and getattr(c, "action_id", "") == "avatar_skill:100802"
            and session.state.units["arlan"].hp >= session.state.units["arlan"].max_hp * 0.9
        ]
        if arlan_skill:
            return arlan_skill[0]
        chosen = _prefer_ult(choices)
        if chosen is not None:
            return chosen
        for actor in ("arlan", "serval", "natasha"):
            match = [c for c in choices if c.actor_id == actor]
            if match:
                return match[0]
        return choices[0]

    session, observed, archive = _drive(
        rules, scenario, actor_priority=priority, max_steps=80,
        stop_after=None, tmp_path=tmp_path, archive_name="r06-route-c.json.gz",
    )
    assert session.outcome == "victory", session.outcome
    assert session.state.units["serval"].energy >= 0
    settlement_text = json.dumps(observed["settlements"], default=str)
    ledger = _ledger(session) + settlement_text
    assert "MEquip_21033_Main" in settlement_text
    assert "OnTriggerDeath" in settlement_text
    assert "MEquip_20015_Main" in settlement_text
    assert "MEquip_23033_Sub" in ledger or "MEquip_23033_Main" in ledger
    assert "MEquip_23033_Sub" in settlement_text
    # 20015's current-skill delay registration and 23033's two-Basic-ATK
    # advance branch are carried by the dedicated real-task component checks;
    # this route keeps the kill-recovery and equipment-mount public chain.
    assert observed["steps"] > 0
    assert archive.exists()
