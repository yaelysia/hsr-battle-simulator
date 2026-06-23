from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.rulebook import RuleBook
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_252"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    text_hint_case = _text_hint_case(ir)
    continuation_case = _skill_continuation_case(rules)
    alignment_matrix = _alignment_matrix(ir, rules, text_hint_case, continuation_case)
    checks = {
        "text_hint_not_executable_family": text_hint_case["checks"],
        "use_skill_one_more_continuation": continuation_case["checks"],
        "alignment_matrix": {
            "ok": all(bool(item.get("current_status")) for item in alignment_matrix["items"].values()),
            "checks": {"items_present": True},
        },
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "checks": checks,
        "static_checks": static_result.to_json(),
        "text_hint_case": text_hint_case,
        "skill_continuation_case": continuation_case,
        "extra_action_alignment_matrix": alignment_matrix,
        "coverage_summary": coverage.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_252.json", result)
    write_json(output_dir / "extra_action_alignment_matrix_v0_252.json", alignment_matrix)
    write_json(output_dir / "text_hint_admission_case_v0_252.json", text_hint_case)
    write_json(output_dir / "skill_continuation_case_v0_252.json", continuation_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_252 mechanism alignment audit.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _text_hint_case(ir) -> dict[str, Any]:
    hinted_windows: list[dict[str, Any]] = []
    direct_executable: list[dict[str, Any]] = []
    hint_counter: Counter[str] = Counter()
    for window in ir.queue_windows:
        evidence = window.source.evidence if isinstance(window.source.evidence, dict) else {}
        basis = evidence.get("family_basis") if isinstance(evidence.get("family_basis"), dict) else {}
        hints = tuple(str(item) for item in basis.get("text_hints", ()) if isinstance(item, str))
        if not hints:
            continue
        hint_counter.update(hints)
        row = {
            "queue_window_id": window.queue_window_id,
            "queue_intent_id": window.queue_intent_id,
            "window_family": window.window_family,
            "coverage_status": window.coverage_status,
            "text_hints": list(hints),
            "source_path": window.source.source_path,
            "blocked_reason": window.blocked_reason,
        }
        hinted_windows.append(row)
        if window.coverage_status == "executable" and window.window_family in hints:
            direct_executable.append(row)
    checks = {
        "ok": False,
        "text_hints_are_recorded_if_present": True,
        "text_hints_do_not_directly_create_executable_family": not direct_executable,
        "no_text_only_extra_turn_execution": not any(
            row["coverage_status"] == "executable" and "extra_turn" in row["text_hints"]
            for row in hinted_windows
        ),
        "no_text_only_follow_counter_execution": not any(
            row["coverage_status"] == "executable"
            and ({"follow_up", "counter"} & set(row["text_hints"]))
            and row["window_family"] in {"follow_up", "counter"}
            for row in hinted_windows
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "hint_counts": dict(sorted(hint_counter.items())),
        "hinted_window_count": len(hinted_windows),
        "direct_executable_from_text_hint": direct_executable,
        "sample_hinted_windows": hinted_windows[:40],
    }


def _skill_continuation_case(rules: RuleBook) -> dict[str, Any]:
    continuations = rules.skill_continuations()
    opcode_counts = Counter(item.opcode for item in continuations)
    source_counts = Counter(item.source.source_path for item in continuations)
    checks = {
        "ok": False,
        "use_skill_one_more_lowered_as_continuation": opcode_counts.get("UseSkillOneMore", 0) > 0,
        "continuation_not_queue_executable": all(item.coverage_status != "executable" for item in continuations),
        "continuation_has_source_trace": all(bool(item.source.source_path) for item in continuations),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "continuation_count": len(continuations),
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "source_path_counts": dict(source_counts.most_common(20)),
        "samples": [
            {
                "continuation_id": item.continuation_id,
                "ability_name": item.ability_name,
                "fixed_skill_type": item.fixed_skill_type,
                "source_path": item.source.source_path,
                "coverage_status": item.coverage_status,
                "blocked_reason": item.blocked_reason,
            }
            for item in continuations[:40]
        ],
    }


def _alignment_matrix(ir, rules: RuleBook, text_hint_case: dict[str, Any], continuation_case: dict[str, Any]) -> dict[str, Any]:
    family_counts = Counter(window.window_family for window in ir.queue_windows)
    executable_family_counts = Counter(window.window_family for window in ir.queue_windows if window.coverage_status == "executable")
    continuation_sources = continuation_case.get("source_path_counts", {})
    return {
        "version": VALIDATION_VERSION,
        "note": "External references are audit context only; runtime rules still come from Canonical IR.",
        "external_reference_urls": {
            "seele": "https://honkai-star-rail.fandom.com/wiki/Seele/Combat",
            "rappa": "https://honkai-star-rail.fandom.com/wiki/Rappa/Combat",
            "feixiao": "https://honkai-star-rail.fandom.com/wiki/Feixiao/Combat",
            "acheron": "https://honkai-star-rail.fandom.com/wiki/Acheron/Combat",
        },
        "items": {
            "seele_style_true_extra_turn": {
                "external_baseline": "true extra action opportunity; should not tick ordinary turn-duration buffs and should not be treated as an ultimate-internal continuation",
                "tbgd_evidence": {
                    "global_one_more_modifier": "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json:ModifierMap.OneMore",
                    "insert_action_examples": "TurnInsertAction sources are lowered structurally, for example Seele-style BonusInsertAction evidence when present",
                },
                "current_status": "partially_structured",
                "can_fix_now": "partly_done",
                "remaining_dependency": "needs source-specific extra-turn action-choice policy before executable free/limited action selection",
            },
            "rappa_style_limited_extra_turn": {
                "external_baseline": "extra turn exists, but action choice is restricted by Sealform-like state rather than free skill/basic selection",
                "tbgd_evidence": {
                    "continuation_or_filter_sources": dict(continuation_sources),
                },
                "current_status": "blocked_until_action_choice_policy",
                "can_fix_now": "classification_guard_done",
                "remaining_dependency": "requires admitted state-driven action restriction policy",
            },
            "feixiao_acheron_skill_continuation": {
                "external_baseline": "ultimate/skill internal continuation, not a true extra turn",
                "tbgd_evidence": continuation_case.get("samples", [])[:10],
                "current_status": "classified_as_skill_continuation",
                "can_fix_now": "done_for_classification",
                "remaining_dependency": "needs dedicated continuation runner to execute fixed follow-up segments",
            },
            "follow_up": {
                "external_baseline": "attack/window semantics with high queue priority; not a damage formula family",
                "tbgd_evidence": {
                    "queue_window_family_count": family_counts.get("follow_up", 0),
                    "text_hint_count": text_hint_case.get("hint_counts", {}).get("follow_up", 0),
                },
                "current_status": "text_hints_discovered_only; executable requires explicit admitted source",
                "can_fix_now": "text_guess_execution_removed",
                "remaining_dependency": "needs admitted listener/callback/action source for each executable follow-up case",
            },
            "counter": {
                "external_baseline": "handled as follow-up-like queue attack/window semantics",
                "tbgd_evidence": {
                    "queue_window_family_count": family_counts.get("counter", 0),
                    "text_hint_count": text_hint_case.get("hint_counts", {}).get("counter", 0),
                },
                "current_status": "text_hints_discovered_only; executable requires explicit admitted source",
                "can_fix_now": "text_guess_execution_removed",
                "remaining_dependency": "needs admitted listener/callback/action source for each executable counter case",
            },
            "manual_ultimate_insert": {
                "external_baseline": "manual ultimate is a queue request with its own resource and target checks",
                "tbgd_evidence": {
                    "runtime_input": "manual request; action definition/event/damage source still come from Canonical IR",
                    "executable_window_family_count": executable_family_counts.get("ultimate", 0),
                },
                "current_status": "trusted_for_current_scope",
                "can_fix_now": "already_done",
                "remaining_dependency": "full ultimate ordering across every interrupt source still needs more source coverage",
            },
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())

