from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.ir import EffectIR, IRSource, PassiveMechanismSlotIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.loader import ScenarioLoader
from ..tbgd.lowering import TBGDLowering, _passive_startup_effect_blocked_reason
from ..tbgd.monster_cards import _RowRecord, _passive_slots_for_monster
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_281"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    *,
    example_output: Path | None = None,
) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    slot = _select_executable_passive_slot(rules)
    example_case = _startup_passive_execution_case(package_root.parent, rules, slot)
    coverage_case = _coverage_case(rules)
    boundary_case = _boundary_case(rules)
    checks = {
        "startup_passive_execution": example_case["checks"],
        "coverage": coverage_case["checks"],
        "boundary": boundary_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
        },
        "checks": checks,
        "startup_passive_execution_case": example_case,
        "coverage_case": coverage_case,
        "boundary_case": boundary_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_281.json", result)
    write_json(output_dir / "monster_passive_startup_example_v0_281.json", example_case)
    if example_output is not None:
        write_json(example_output, example_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_281 monster passive startup slice.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--example-output", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir, example_output=args.example_output)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_executable_passive_slot(rules: RuleBook) -> PassiveMechanismSlotIR:
    for slot in rules.ir.passive_mechanism_slots:
        if slot.data_card_kind != "monster" or slot.coverage_status != "executable":
            continue
        startup = slot.semantics.get("startup_admission")
        if not isinstance(startup, dict) or startup.get("admission_status") != "executable":
            continue
        if not startup.get("admitted_tasks"):
            continue
        card = rules.monster_data_card(slot.data_card_id)
        if card is None:
            continue
        return slot
    raise RuntimeError("executable monster passive startup sample not found")


def _startup_passive_execution_case(hsr_root: Path, rules: RuleBook, slot: PassiveMechanismSlotIR) -> dict[str, Any]:
    card = rules.monster_data_card(slot.data_card_id)
    if card is None:
        raise RuntimeError(f"monster card missing for {slot.data_card_id}")
    scenario_path = hsr_root / "simulator_v8_clean_core/scenarios/examples/identity_smoke_v0_204.json"
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    for unit in data["units"]:
        if unit.get("unit_id") == "enemy:target":
            unit["entity_ref"] = slot.owner_entity_ref
            panel = unit.setdefault("panel", {})
            panel["max_hp"] = 10_000
            panel["hp"] = 10_000
            panel["attack"] = 1000
            panel["defense"] = 1000
            panel["speed"] = 100
            panel["toughness"] = 60
            panel["max_toughness"] = 60
    scenario = ScenarioLoader().load_dict(data)
    built = ScenarioStateBuilder(rules).build(scenario)
    enemy = built.state.units["enemy:target"]
    status_details = enemy.flags.get("status_details")
    if not isinstance(status_details, (list, tuple)):
        status_details = ()
    passive_traces = [
        trace
        for trace in built.source_traces
        if isinstance(trace, dict)
        and trace.get("kind") == "monster_passive_startup_ability"
        and trace.get("passive_slot_id") == slot.passive_slot_id
    ]
    matching_details = [
        detail
        for detail in status_details
        if isinstance(detail, dict)
        and isinstance(detail.get("source_trace"), dict)
        and detail["source_trace"].get("effect_id")
    ]
    checks = {
        "slot_executable": slot.coverage_status == "executable",
        "slot_source_is_ability_name_list": slot.source.source_path == "ExcelOutput/MonsterConfig.json"
        and str(slot.source.evidence.get("raw_path", "")).startswith("AbilityNameList["),
        "card_links_passive_slot": slot.passive_slot_id in card.passive_mechanism_slot_ids,
        "status_id_added": any(str(item).startswith("modifier:") for item in enemy.statuses),
        "status_details_added": bool(status_details),
        "startup_trace_applied": any(trace.get("status") == "applied" for trace in passive_traces),
        "startup_trace_has_mutations": any(int(trace.get("mutation_count") or 0) > 0 for trace in passive_traces),
        "status_trace_has_effect_source": bool(matching_details),
        "passive_slot_enabled_flag": slot.passive_slot_id
        in tuple(enemy.flags.get("enabled_passive_mechanism_slot_ids") or ()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "schema_version": "v8_monster_passive_startup_example_v0_281",
        "checks": {"ok": checks["ok"], "checks": checks},
        "identity": {
            "monster_id": card.monster_id,
            "entity_ref": card.entity_ref,
            "display": card.display,
            "passive_slot_id": slot.passive_slot_id,
            "ability_name": slot.semantics.get("ability_name"),
        },
        "slot": slot.to_json(),
        "state_summary": {
            "statuses": list(enemy.statuses),
            "status_detail_count": len(status_details),
            "enabled_passive_mechanism_slot_ids": list(enemy.flags.get("enabled_passive_mechanism_slot_ids") or ()),
        },
        "passive_startup_traces": passive_traces,
    }


def _coverage_case(rules: RuleBook) -> dict[str, Any]:
    slots = tuple(rules.ir.passive_mechanism_slots)
    by_status = Counter(slot.coverage_status for slot in slots)
    by_blocked = Counter(slot.blocked_reason for slot in slots if slot.blocked_reason)
    nested_blocked = Counter()
    for slot in slots:
        startup = slot.semantics.get("startup_admission")
        if not isinstance(startup, dict):
            continue
        for task in startup.get("blocked_tasks") or ():
            if isinstance(task, dict) and task.get("blocked_reason"):
                nested_blocked[str(task["blocked_reason"])] += 1
    checks = {
        "has_passive_slots": bool(slots),
        "all_slots_from_monster_ability_name_list": all(
            slot.source.source_path == "ExcelOutput/MonsterConfig.json"
            and str(slot.source.evidence.get("raw_path", "")).startswith("AbilityNameList[")
            for slot in slots
        ),
        "has_executable_startup_passive": by_status.get("executable", 0) > 0,
        "has_missing_ability_blocked": by_blocked.get("monster_passive_ability_missing", 0) > 0,
        "has_non_startup_or_non_add_modifier_blocked": (
            by_blocked.get("monster_passive_startup_on_start_add_modifier_missing", 0)
            + by_blocked.get("monster_passive_startup_no_admitted_on_start_add_modifier", 0)
        )
        > 0,
        "has_event_trigger_blocked": nested_blocked.get("monster_passive_startup_modifier_has_event_triggers", 0) > 0,
        "monster_skill_modifier_list_not_passive_source": all(
            slot.source.evidence.get("raw_path") != "ModifierList" for slot in slots
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "counts": {
            "total": len(slots),
            "by_status": dict(by_status),
            "by_blocked_reason": dict(by_blocked),
            "nested_blocked_task_reasons": dict(nested_blocked),
        },
    }


def _boundary_case(rules: RuleBook) -> dict[str, Any]:
    ambiguous_slot = _passive_slots_for_monster(
        "synthetic_ambiguous",
        _RowRecord(
            relative_path="ExcelOutput/MonsterConfig.json",
            row_index=-1,
            row={"AbilityNameList": ["SyntheticAmbiguousAbility"]},
        ),
        {
            "SyntheticAmbiguousAbility": (
                "Config/ConfigAbility/Monster/SyntheticA.json",
                "Config/ConfigAbility/Monster/SyntheticB.json",
            )
        },
    )[0]
    dynamic_effect = _synthetic_add_modifier_effect(
        "synthetic_dynamic",
        target_alias="Caster",
        modifier_name="SyntheticModifier",
        dynamic_requests={"DamageRatio": {"hash": 123}},
    )
    bad_target_effect = _synthetic_add_modifier_effect(
        "synthetic_bad_target",
        target_alias="AllEnemy",
        modifier_name="SyntheticModifier",
    )
    trigger_effect = _synthetic_add_modifier_effect(
        "synthetic_trigger_modifier",
        target_alias="Caster",
        modifier_name="SyntheticTriggerModifier",
    )
    checks = {
        "dynamic_value_request_blocked": _passive_startup_effect_blocked_reason(dynamic_effect, set())
        == "monster_passive_startup_dynamic_value_request_not_admitted",
        "target_alias_blocked": _passive_startup_effect_blocked_reason(bad_target_effect, set())
        == "monster_passive_startup_effect_target_alias_not_admitted:AllEnemy",
        "trigger_modifier_blocked": _passive_startup_effect_blocked_reason(
            trigger_effect, {"SyntheticTriggerModifier"}
        )
        == "monster_passive_startup_modifier_has_event_triggers",
        "ambiguous_ability_name_blocked": ambiguous_slot.coverage_status == "blocked"
        and ambiguous_slot.blocked_reason == "monster_passive_ability_ambiguous",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}}


def _synthetic_add_modifier_effect(
    raw_id: str,
    *,
    target_alias: str,
    modifier_name: str,
    dynamic_requests: dict[str, object] | None = None,
) -> EffectIR:
    standard: dict[str, object] = {"target_alias": target_alias, "modifier_name": modifier_name}
    if dynamic_requests is not None:
        standard["dynamic_value_requests"] = dynamic_requests
    return EffectIR(
        effect_id=f"effect:{raw_id}",
        opcode="AddModifier",
        payload={"standard": standard},
        source=IRSource(
            source_path="simulator_v8_clean_core/tools/validate_v0_281.py",
            raw_type="SyntheticEffectForPassiveBoundaryValidation",
            raw_id=raw_id,
            evidence={"process_only": True},
        ),
        coverage_status="executable",
    )


if __name__ == "__main__":
    raise SystemExit(main())
