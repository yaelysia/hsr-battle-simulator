from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, UnitState
from ..core.reducer import MutationReducer
from ..rules.rulebook import RuleBook
from ..systems.damage import DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_255 import _automatic_kill_to_extra_turn_case


VALIDATION_VERSION = "v0_256"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    source_window = _damage_source_window_case()
    automatic_chain = _automatic_kill_to_extra_turn_case(ir, rules)
    checks = {
        "damage_source_window": source_window["checks"],
        "automatic_kill_to_extra_turn_regression": automatic_chain["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": {
                "source_window_unit_case": (
                    "Unit-level source-frame validation modeled after v7.7 kill-credit regressions: "
                    "primary source sequence can continue after lethal; derived/additional and DoT sources stop."
                ),
                "automatic_extra_turn_regression": (
                    "Reuses v0_255 structured TBGD selector for real unit.defeated -> death callback -> extra-turn queue."
                ),
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "damage_source_window_case": source_window,
        "automatic_kill_to_extra_turn_case": automatic_chain,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_256.json", result)
    write_json(output_dir / "damage_source_window_case_v0_256.json", source_window)
    write_json(output_dir / "automatic_kill_extra_turn_regression_v0_256.json", automatic_chain)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 damage source windows and concrete kill attribution.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _damage_source_window_case() -> dict[str, Any]:
    primary_case = _primary_source_continuation_case()
    derived_case = _derived_source_skip_case()
    dot_case = _dot_source_order_case()
    checks = {
        "primary_source_continuation": primary_case["checks"],
        "derived_source_skip": derived_case["checks"],
        "dot_source_order": dot_case["checks"],
    }
    ok = all(item["ok"] for item in checks.values())
    return {
        "checks": {"ok": ok, "checks": checks},
        "primary_source_continuation": primary_case,
        "derived_source_skip": derived_case,
        "dot_source_order": dot_case,
    }


def _primary_source_continuation_case() -> dict[str, Any]:
    state = _state_with_victim(hp=150.0)
    reducer = MutationReducer()
    damage = DamageSystem()
    ledger = DamageWindowLedger()
    packets = (
        _packet("ally:attacker", "enemy:victim", 50.0, source_id="action:basic", source_kind="primary_action_damage", sequence_id="seq:basic", can_continue=True),
        _packet("ally:attacker", "enemy:victim", 100.0, source_id="action:basic", source_kind="primary_action_damage", sequence_id="seq:basic", can_continue=True),
        _packet("ally:attacker", "enemy:victim", 100.0, source_id="action:basic", source_kind="primary_action_damage", sequence_id="seq:basic", can_continue=True),
    )
    results = []
    current = state
    for packet in packets:
        result = damage.apply_packet(current, packet, window_ledger=ledger)
        current = reducer.apply_all(current, result.mutations)
        results.append(result)
    defeat_events = _events_of_type(results, "unit.defeated")
    third_records = list(results[2].records)
    third_payload = third_records[0].get("payload", {}) if third_records else {}
    checks = {
        "three_packets_resolved": len(results) == 3,
        "only_second_packet_defeated": len(defeat_events) == 1 and defeat_events[0].payload.get("amount") == 100.0,
        "third_packet_has_damage_record": bool(third_records),
        "third_packet_has_no_hp_mutation": not results[2].mutations,
        "third_packet_marked_dead_target_continuation": third_payload.get("dead_target_continuation") is True,
        "kill_credit_source_is_action": bool(defeat_events and defeat_events[0].payload.get("kill_credit_source_id") == "action:basic"),
        "kill_credit_owner_is_attacker": bool(defeat_events and defeat_events[0].payload.get("kill_credit_owner_id") == "ally:attacker"),
        "final_hp_zero": current.units["enemy:victim"].hp == 0.0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "events": [[event.to_json() for event in result.events] for result in results],
        "records": [list(result.records) for result in results],
        "mutations": [[mutation.to_json() for mutation in result.mutations] for result in results],
        "ledger": ledger.to_json(),
    }


def _derived_source_skip_case() -> dict[str, Any]:
    state = _state_with_victim(hp=10.0)
    reducer = MutationReducer()
    damage = DamageSystem()
    ledger = DamageWindowLedger()
    primary = damage.apply_packet(
        state,
        _packet("ally:seele", "enemy:victim", 20.0, source_id="action:skill", source_kind="primary_action_damage", sequence_id="seq:skill", can_continue=True),
        window_ledger=ledger,
    )
    after_primary = reducer.apply_all(state, primary.mutations)
    derived = damage.apply_packet(
        after_primary,
        _packet("ally:tribbie", "enemy:victim", 100.0, source_id="additional:zone", source_kind="additional_damage", sequence_id="seq:zone", can_continue=False),
        window_ledger=ledger,
    )
    primary_defeat_events = _events_of_type((primary,), "unit.defeated")
    derived_defeat_events = _events_of_type((derived,), "unit.defeated")
    derived_record = derived.records[0] if derived.records else {}
    checks = {
        "primary_killed_target": len(primary_defeat_events) == 1,
        "derived_has_no_mutation": not derived.mutations,
        "derived_has_no_defeat_event": not derived_defeat_events,
        "derived_skip_record": derived_record.get("record_type") == "damage_source_skipped",
        "derived_skip_reason": derived_record.get("payload", {}).get("reason") == "damage_source_target_already_defeated_in_window",
        "kill_credit_stays_primary_source": primary_defeat_events[0].payload.get("kill_credit_source_id") == "action:skill",
        "derived_did_not_steal_owner": primary_defeat_events[0].payload.get("kill_credit_owner_id") == "ally:seele",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "primary_events": [event.to_json() for event in primary.events],
        "derived_events": [event.to_json() for event in derived.events],
        "derived_records": list(derived.records),
        "ledger": ledger.to_json(),
    }


def _dot_source_order_case() -> dict[str, Any]:
    state = _state_with_victim(hp=15.0)
    reducer = MutationReducer()
    damage = DamageSystem()
    ledger = DamageWindowLedger()
    kafka = damage.apply_packet(
        state,
        _packet("ally:kafka", "enemy:victim", 20.0, source_id="dot:shock_from_kafka", source_kind="dot", sequence_id="seq:dot:kafka", can_continue=False),
        window_ledger=ledger,
    )
    after_kafka = reducer.apply_all(state, kafka.mutations)
    sampo = damage.apply_packet(
        after_kafka,
        _packet("ally:sampo", "enemy:victim", 20.0, source_id="dot:wind_from_sampo", source_kind="dot", sequence_id="seq:dot:sampo", can_continue=False),
        window_ledger=ledger,
    )
    defeat_events = _events_of_type((kafka, sampo), "unit.defeated")
    sampo_record = sampo.records[0] if sampo.records else {}
    checks = {
        "first_dot_kills": len(_events_of_type((kafka,), "unit.defeated")) == 1,
        "second_dot_skipped": sampo_record.get("record_type") == "damage_source_skipped",
        "second_dot_no_mutation": not sampo.mutations,
        "only_one_defeat_event": len(defeat_events) == 1,
        "kill_credit_owner_is_dot_applier": defeat_events[0].payload.get("kill_credit_owner_id") == "ally:kafka",
        "kill_credit_source_is_killing_dot": defeat_events[0].payload.get("kill_credit_source_id") == "dot:shock_from_kafka",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "kafka_events": [event.to_json() for event in kafka.events],
        "sampo_events": [event.to_json() for event in sampo.events],
        "sampo_records": list(sampo.records),
        "ledger": ledger.to_json(),
    }


def _state_with_victim(*, hp: float) -> BattleState:
    return BattleState(
        units={
            "ally:attacker": UnitState("ally:attacker", "ally", "avatar:attacker", hp=1000.0, max_hp=1000.0),
            "ally:seele": UnitState("ally:seele", "ally", "avatar:seele", hp=1000.0, max_hp=1000.0),
            "ally:tribbie": UnitState("ally:tribbie", "ally", "avatar:tribbie", hp=1000.0, max_hp=1000.0),
            "ally:kafka": UnitState("ally:kafka", "ally", "avatar:kafka", hp=1000.0, max_hp=1000.0),
            "ally:sampo": UnitState("ally:sampo", "ally", "avatar:sampo", hp=1000.0, max_hp=1000.0),
            "enemy:victim": UnitState("enemy:victim", "enemy", "monster:victim", hp=hp, max_hp=max(100.0, hp)),
        },
        skill_points=5,
        max_skill_points=5,
    )


def _packet(
    owner_id: str,
    target_id: str,
    amount: float,
    *,
    source_id: str,
    source_kind: str,
    sequence_id: str,
    can_continue: bool,
) -> DamagePacket:
    return DamagePacket(
        attacker_id=owner_id,
        target_id=target_id,
        attack_type="validation_damage",
        damage_formula_family="hp_loss",
        amount=amount,
        damage_kind="hp_loss",
        source_frame=DamageSourceFrame(
            owner_id=owner_id,
            source_id=source_id,
            source_kind=source_kind,
            sequence_id=sequence_id,
            target_id=target_id,
            can_continue_after_lethal=can_continue,
            source_trace={"validation": VALIDATION_VERSION, "source_id": source_id},
        ),
        source_trace={"validation": VALIDATION_VERSION, "source_id": source_id},
        metadata={
            "damage_source_owner_id": owner_id,
            "damage_source_id": source_id,
            "damage_source_kind": source_kind,
            "damage_sequence_id": sequence_id,
            "can_continue_after_lethal": can_continue,
            "is_current_skill_active": source_kind == "primary_action_damage",
            "is_insert_action": False,
            "primary_action_target_id": target_id,
        },
    )


def _events_of_type(results, event_type: str) -> list:
    return [event for result in results for event in result.events if event.event_type == event_type]


if __name__ == "__main__":
    raise SystemExit(main())
