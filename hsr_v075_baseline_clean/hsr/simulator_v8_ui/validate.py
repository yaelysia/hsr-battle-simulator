from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

from simulator_v8_clean_core import BASELINE_VERSION
from simulator_v8_clean_core.scenarios import ScenarioLoader, ScenarioStateBuilder
from simulator_v8_clean_core.systems.scheduler import CombatScheduler
from simulator_v8_clean_core.tools.io import write_json

from .report import build_step_report
from .runner import UIRunOptions, UIRunner, load_json_file


VALIDATION_VERSION = "v0_275"


def run_validation(output_dir: Path) -> dict[str, Any]:
    package_root = Path(__file__).resolve().parent
    hsr_root = package_root.parent
    scenario_path = package_root / "cases" / "identity_smoke_v0_204.scenario.json"
    scenario_data = load_json_file(scenario_path)
    observations = {"observed_damage": {"route_index": 0, "value": 0, "note": "validation sidecar only"}}

    runner = UIRunner(hsr_root=hsr_root)
    scheduler_report = runner.run_data(
        scenario_data,
        options=UIRunOptions(mode="scheduler", write_tmp_report=True),
        observations=observations,
    )
    executor_report = runner.run_data(
        scenario_data,
        options=UIRunOptions(mode="executor", write_tmp_report=True),
        observations=observations,
    )
    unknown_target_report = runner.run_data(
        _scenario_with_unknown_target(scenario_data),
        options=UIRunOptions(mode="scheduler", write_tmp_report=False),
        observations=observations,
    )
    missing_action_report = runner.run_data(
        _scenario_with_missing_action(scenario_data),
        options=UIRunOptions(mode="scheduler", write_tmp_report=False),
        observations=observations,
    )
    enemy_skip_report = runner.run_data(
        _scenario_with_enemy_first(scenario_data),
        options=UIRunOptions(mode="scheduler", write_tmp_report=False, max_auto_skip_turns=5),
        observations=observations,
    )
    blocked_queue = _blocked_queue_report(runner, scenario_data)
    catalog = runner.catalog()
    reverse_dependency = _reverse_dependency_check(hsr_root / "simulator_v8_clean_core")

    checks = {
        "scheduler_report": _report_checks(scheduler_report, expect_valid=True),
        "executor_report": _report_checks(executor_report, expect_valid=True),
        "unknown_target_process_only": _invalid_report_checks(unknown_target_report),
        "missing_action_process_only": _invalid_report_checks(missing_action_report),
        "blocked_queue_process_only": {
            "ok": (
                bool(blocked_queue["blocked_records"])
                and _step_mutation_count(blocked_queue) == 0
                and "observed_damage" not in str(blocked_queue.get("input_command", {}).get("metadata", {}))
            ),
            "blocked_records": blocked_queue["blocked_records"],
            "mutation_count": _step_mutation_count(blocked_queue),
        },
        "enemy_ai_auto_skip": _enemy_auto_skip_checks(enemy_skip_report),
        "catalog_action_slots": _catalog_action_slot_checks(catalog, scenario_data),
        "catalog_trace_nodes": _catalog_trace_node_checks(catalog, scenario_data),
        "observations_sidecar_only": {
            "ok": not _report_command_metadata_contains(scheduler_report, "observed_damage")
            and not _report_command_metadata_contains(executor_report, "observed_damage"),
        },
        "reverse_dependency": reverse_dependency,
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "checks": checks,
        "reports": {
            "scheduler": {
                "scenario_id": scheduler_report.get("scenario_id"),
                "tmp_report_path": scheduler_report.get("run_artifacts", {}).get("tmp_report_path"),
                "step_count": len(scheduler_report.get("steps", [])),
            },
            "executor": {
                "scenario_id": executor_report.get("scenario_id"),
                "tmp_report_path": executor_report.get("run_artifacts", {}).get("tmp_report_path"),
                "step_count": len(executor_report.get("steps", [])),
            },
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_275.json", result)
    write_json(output_dir / "scheduler_report_v0_275.json", scheduler_report)
    write_json(output_dir / "executor_report_v0_275.json", executor_report)
    write_json(output_dir / "unknown_target_report_v0_275.json", unknown_target_report)
    write_json(output_dir / "missing_action_report_v0_275.json", missing_action_report)
    write_json(output_dir / "enemy_skip_report_v0_275.json", enemy_skip_report)
    write_json(output_dir / "blocked_queue_step_v0_275.json", blocked_queue)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证 v8 UI 测试台。")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_validation(args.output_dir)
    print(f"v8 {VALIDATION_VERSION} UI validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _report_checks(report: dict[str, Any], *, expect_valid: bool) -> dict[str, Any]:
    steps = report.get("steps", [])
    first = steps[0] if steps else {}
    damage_records = first.get("damage_records", []) if isinstance(first, dict) else []
    source_audit = first.get("source_audit", {}) if isinstance(first, dict) else {}
    replay = first.get("replay", {}) if isinstance(first, dict) else {}
    transition = first.get("transition", {}) if isinstance(first, dict) else {}
    ok = (
        report.get("schema_version") == "v8_ui_report_v0_1"
        and bool(report.get("validation", {}).get("ok")) is expect_valid
        and bool(steps)
        and bool(report.get("battlefield_view", {}).get("units"))
        and bool(report.get("action_prompt"))
        and bool(report.get("event_replay_view"))
        and isinstance(report.get("auto_skip_records"), list)
        and isinstance(report.get("coverage_gap_records"), list)
        and isinstance(report.get("process_notice_records"), list)
        and bool(first.get("before_panel_summary"))
        and bool(first.get("after_panel_summary"))
        and bool(damage_records)
        and bool(source_audit)
        and bool(replay)
        and isinstance(transition, dict)
        and bool(transition.get("settlement"))
    )
    return {
        "ok": ok,
        "step_count": len(steps),
        "damage_record_count": len(damage_records),
        "battlefield_units": len(report.get("battlefield_view", {}).get("units", [])),
        "action_prompt_available": report.get("action_prompt", {}).get("available"),
        "event_replay_count": len(report.get("event_replay_view", [])),
        "coverage_gap_count": len(report.get("coverage_gap_records", [])),
        "process_notice_count": len(report.get("process_notice_records", [])),
        "source_audit_ok": source_audit.get("ok"),
        "replay_ok": replay.get("ok"),
    }


def _invalid_report_checks(report: dict[str, Any]) -> dict[str, Any]:
    steps = report.get("steps", [])
    mutation_count = sum(_step_mutation_count(step) for step in steps if isinstance(step, dict))
    blocked_count = sum(len(step.get("blocked_records", [])) for step in steps if isinstance(step, dict))
    return {
        "ok": report.get("validation", {}).get("ok") is False and mutation_count == 0 and blocked_count > 0,
        "mutation_count": mutation_count,
        "blocked_count": blocked_count,
        "validation_errors": report.get("validation", {}).get("errors", []),
    }


def _catalog_action_slot_checks(catalog: dict[str, Any], scenario_data: dict[str, Any]) -> dict[str, Any]:
    action_slots = catalog.get("action_slots_by_entity", {})
    ally = next(
        (
            unit
            for unit in scenario_data.get("units", [])
            if isinstance(unit, dict) and unit.get("side") == "ally"
        ),
        {},
    )
    entity_ref = ally.get("entity_ref")
    slots = action_slots.get(entity_ref, []) if isinstance(action_slots, dict) else []
    slot_names = {slot.get("slot") for slot in slots if isinstance(slot, dict)}
    disabled_slots = [slot for slot in slots if isinstance(slot, dict) and not slot.get("available")]
    return {
        "ok": (
            catalog.get("schema_version") == "v8_ui_catalog_v0_3"
            and {"basic", "skill", "ultimate"}.issubset(slot_names)
            and all("source_kind" in slot and "source_trace" in slot for slot in slots if isinstance(slot, dict))
        ),
        "entity_ref": entity_ref,
        "slot_names": sorted(str(item) for item in slot_names),
        "disabled_slot_count": len(disabled_slots),
    }


def _catalog_trace_node_checks(catalog: dict[str, Any], scenario_data: dict[str, Any]) -> dict[str, Any]:
    trace_nodes = catalog.get("trace_nodes_by_entity", {})
    ally = next(
        (
            unit
            for unit in scenario_data.get("units", [])
            if isinstance(unit, dict) and unit.get("side") == "ally"
        ),
        {},
    )
    entity_ref = ally.get("entity_ref")
    nodes = trace_nodes.get(entity_ref, []) if isinstance(trace_nodes, dict) else []
    first = nodes[0] if nodes and isinstance(nodes[0], dict) else {}
    return {
        "ok": (
            catalog.get("schema_version") == "v8_ui_catalog_v0_3"
            and bool(nodes)
            and "trace_node_id" in first
            and "linked_mechanism_slot_ids" in first
            and "default_enabled" in first
            and "mapped_terms" in first
        ),
        "entity_ref": entity_ref,
        "trace_node_count": len(nodes),
        "first_trace_node_id": first.get("trace_node_id"),
    }


def _enemy_auto_skip_checks(report: dict[str, Any]) -> dict[str, Any]:
    auto_skip = report.get("auto_skip_records", [])
    events = report.get("event_replay_view", [])
    prompt = report.get("action_prompt", {})
    enemy_ai_records = [
        item
        for item in auto_skip
        if isinstance(item, dict) and item.get("reason") == "enemy_ai_missing"
    ]
    return {
        "ok": (
            bool(report.get("validation", {}).get("ok"))
            and bool(enemy_ai_records)
            and prompt.get("available") is True
            and str(prompt.get("current_unit_id", "")).startswith("ally:")
            and any(
                isinstance(event, dict) and event.get("event_kind") == "auto_skip_enemy_turn"
                for event in events
            )
            and not any(
                isinstance(item, dict) and item.get("reason") == "enemy_ai_missing"
                for item in report.get("blocked_records", [])
            )
        ),
        "auto_skip_count": len(auto_skip),
        "prompt": prompt,
        "event_count": len(events),
    }


def _blocked_queue_report(runner: UIRunner, scenario_data: dict[str, Any]) -> dict[str, Any]:
    scenario = ScenarioLoader().load_dict(scenario_data)
    build = ScenarioStateBuilder(runner.rules).build(scenario)
    command = build.commands[0]
    result = CombatScheduler(runner.rules).enqueue_manual_ultimate(build.state, command)
    return build_step_report(
        route_index=0,
        command=command,
        before_state=build.state,
        after_state=result.after_state,
        transition=result.transition,
        child_transitions=result.child_transitions,
        rules=runner.rules,
        scenario_data=scenario_data,
        include_raw_transition=True,
    )


def _reverse_dependency_check(core_root: Path) -> dict[str, Any]:
    scanned = []
    offenders = []
    for directory in ("core", "systems", "tbgd"):
        for path in sorted((core_root / directory).rglob("*.py")):
            scanned.append(path.as_posix())
            text = path.read_text(encoding="utf-8")
            if "simulator_v8_ui" in text:
                offenders.append(path.as_posix())
    return {"ok": not offenders, "scanned_files": len(scanned), "offenders": offenders}


def _scenario_with_unknown_target(scenario: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(scenario)
    updated["route"][0]["target_ids"] = ["enemy:missing"]
    return updated


def _scenario_with_missing_action(scenario: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(scenario)
    updated["route"][0]["action_ref"] = "avatar_skill:missing"
    return updated


def _scenario_with_enemy_first(scenario: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(scenario)
    for unit in updated.get("units", []):
        if not isinstance(unit, dict):
            continue
        panel = unit.setdefault("panel", {})
        if unit.get("side") == "ally":
            panel["speed"] = 100
        elif unit.get("side") == "enemy":
            panel["speed"] = 101
    return updated


def _step_mutation_count(step: dict[str, Any]) -> int:
    transition = step.get("transition") if isinstance(step, dict) else {}
    if not isinstance(transition, dict):
        return 0
    mutations = transition.get("mutations")
    return len(mutations) if isinstance(mutations, list) else 0


def _report_command_metadata_contains(report: dict[str, Any], token: str) -> bool:
    for step in report.get("steps", []):
        if token in str(step.get("input_command", {}).get("metadata", {})):
            return True
        transition = step.get("transition", {})
        if isinstance(transition, dict) and token in str(transition.get("command", {}).get("metadata", {})):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
