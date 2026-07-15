from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..scenarios import PanelInput, ScenarioSpec, ScenarioStateBuilder, UnitSpec
from ..rules.ir import CharacterDataCardIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_267"
SEELE_ENTITY_REF = "avatar:1102"
ENHANCED_SEELE_RANK_IDS = ("1110201", "1110202", "1110203", "1110204", "1110205", "1110206")


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    card = _seele_card(rules)
    card_case = _eidolon_card_case(rules, card)
    activation_case = _eidolon_activation_case(rules, card)
    checks = {
        "eidolon_card": card_case["checks"],
        "eidolon_activation": activation_case["checks"],
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
                "sample_card": "Seele is the user-requested example card; core/runtime code is checked separately for no name special case.",
                "eidolon_slots": "Selected from CharacterDataCardIR.eidolon_slot_ids and AvatarRankConfig evidence.",
                "activation": "Selected by scenario unit eidolon_level, not by independent rank toggles.",
            },
        },
        "checks": checks,
        "eidolon_card_case": card_case,
        "eidolon_activation_case": activation_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_267.json", result)
    write_json(output_dir / "eidolon_activation_matrix_v0_267.json", activation_case["matrix"])
    write_json(output_dir / "seele_eidolon_slots_v0_267.json", card_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_267 character eidolon switch contract.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _seele_card(rules: RuleBook) -> CharacterDataCardIR:
    card = rules.character_data_card_for_entity(SEELE_ENTITY_REF)
    if card is None:
        raise RuntimeError("Seele character data card missing")
    return card


def _eidolon_card_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    slots = rules.character_eidolon_slots_for_card(card.card_id)
    mechanism_slots = rules.character_mechanism_slots_for_card(card.card_id)
    eidolon_effect_slots = [
        slot for slot in mechanism_slots if slot.mechanism_kind.startswith("eidolon_")
    ]
    rank_ids = tuple(slot.rank_id for slot in slots)
    checks = {
        "enhanced_seele_card": card.source.evidence.get("version_kind") == "enhanced",
        "schema_version_v0_267": card.schema_version == "v0_267",
        "six_eidolon_slots": len(slots) == 6,
        "rank_ids_use_enhanced": rank_ids == ENHANCED_SEELE_RANK_IDS,
        "slots_are_prefix_toggle_sources": all(
            slot.coverage_status == "executable"
            and slot.activation.get("kind") == "eidolon_prefix_toggle"
            and slot.activation.get("prefix_closed") is True
            for slot in slots
        ),
        "slots_have_rank_config_evidence": all(
            slot.source.source_path.endswith("AvatarRankConfig.json")
            and slot.source.evidence.get("rank_config_source_path")
            and slot.source.evidence.get("param_values") is not None
            for slot in slots
        ),
        "effect_slots_classified_without_fake_runtime": len(eidolon_effect_slots) == 6
        and all(
            (
                slot.coverage_status == "executable"
                and bool(slot.semantics)
                and bool(slot.source.source_path)
            )
            or (slot.coverage_status != "executable" and bool(slot.blocked_reason))
            for slot in eidolon_effect_slots
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "card": card.to_json(),
        "eidolon_slots": [slot.to_json() for slot in slots],
        "eidolon_effect_slots": [slot.to_json() for slot in eidolon_effect_slots],
    }


def _eidolon_activation_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    e0 = _state_for_eidolon_level(rules, 0)
    e3 = _state_for_eidolon_level(rules, 3)
    e6 = _state_for_eidolon_level(rules, 6)
    invalid_error = ""
    try:
        _state_for_eidolon_level(rules, 7)
    except ValueError as exc:
        invalid_error = str(exc)
    rulebook_e6_slots = rules.character_eidolon_slots_for_level(card.card_id, 6)
    flags0 = dict(e0.units["ally:seele"].flags)
    flags3 = dict(e3.units["ally:seele"].flags)
    flags6 = dict(e6.units["ally:seele"].flags)
    checks = {
        "e0_has_no_enabled_slots": tuple(flags0.get("enabled_eidolon_ranks", ())) == (),
        "e3_enables_prefix_1_to_3": tuple(flags3.get("enabled_eidolon_ranks", ())) == (1, 2, 3),
        "e6_enables_prefix_1_to_6": tuple(flags6.get("enabled_eidolon_ranks", ())) == (1, 2, 3, 4, 5, 6),
        "e6_rank_ids_include_all_previous": tuple(flags6.get("enabled_eidolon_rank_ids", ())) == ENHANCED_SEELE_RANK_IDS,
        "independent_rank_toggle_not_allowed": flags6.get("eidolon_activation_policy", {}).get("independent_rank_toggle_allowed") is False,
        "rulebook_level_expansion_prefix_closed": tuple(slot.rank for slot in rulebook_e6_slots) == (1, 2, 3, 4, 5, 6),
        "enabled_mechanism_slots_expand_with_level": len(tuple(flags6.get("enabled_eidolon_mechanism_slot_ids", ()))) == 6,
        "invalid_level_rejected": "eidolon_level must be between 0 and 6" in invalid_error,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    matrix = {
        "levels": {
            "0": _activation_summary(flags0),
            "3": _activation_summary(flags3),
            "6": _activation_summary(flags6),
        },
        "invalid_level_error": invalid_error,
        "policy": flags6.get("eidolon_activation_policy", {}),
    }
    return {"checks": {"ok": checks["ok"], "checks": checks}, "matrix": matrix}


def _state_for_eidolon_level(rules: RuleBook, eidolon_level: int):
    scenario = ScenarioSpec(
        scenario_id=f"eidolon_level_{eidolon_level}",
        version=VALIDATION_VERSION,
        units=(
            UnitSpec(
                unit_id="ally:seele",
                side="ally",
                build_mode="kernel_fixture",
                entity_ref=SEELE_ENTITY_REF,
                level=80,
                eidolon_level=eidolon_level,
                panel=PanelInput(
                    explicit_fields=("max_hp", "hp", "attack", "defense", "speed", "energy", "max_energy"),
                    max_hp=3000.0,
                    hp=3000.0,
                    attack=1200.0,
                    defense=500.0,
                    speed=115.0,
                    energy=0.0,
                    max_energy=120.0,
                ),
            ),
        ),
        route=(),
    )
    return ScenarioStateBuilder(rules).build(scenario).state


def _activation_summary(flags: dict[str, Any]) -> dict[str, Any]:
    return {
        "character_data_card_id": flags.get("character_data_card_id", ""),
        "eidolon_level_requested": flags.get("eidolon_level_requested", 0),
        "enabled_eidolon_ranks": list(flags.get("enabled_eidolon_ranks", ())),
        "enabled_eidolon_slot_ids": list(flags.get("enabled_eidolon_slot_ids", ())),
        "enabled_eidolon_rank_ids": list(flags.get("enabled_eidolon_rank_ids", ())),
        "enabled_eidolon_mechanism_slot_ids": list(flags.get("enabled_eidolon_mechanism_slot_ids", ())),
    }


if __name__ == "__main__":
    raise SystemExit(main())
