from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_261 import run_validation as run_v0_261_validation


VALIDATION_VERSION = "v0_262"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    v261_dir = output_dir / "v0_261_regression"
    v261 = run_v0_261_validation(package_root, tbgd_root, v261_dir)
    static_result = run_static_checks(package_root)
    checks = {
        "character_data_card_boundary": _character_data_card_boundary_checks(ir, rules),
        "direct_damage_uses_card_formula": _direct_damage_card_formula_checks(ir),
        "legacy_text_parser_boundary": _legacy_text_parser_boundary_checks(package_root),
        "v0_261_regression": {"ok": bool(v261.get("ok")), "checks": {"v0_261_ok": bool(v261.get("ok"))}},
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "character_data_card_count": len(ir.character_data_cards),
            "avatar_profile_count": len(ir.avatar_profiles),
            "skill_formula_binding_count": len(ir.skill_formula_bindings),
        },
        "checks": checks,
        "character_data_card_samples": _character_data_card_samples(ir),
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_262.json", result)
    write_json(output_dir / "character_data_card_samples_v0_262.json", result["character_data_card_samples"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 character data card boundary.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _character_data_card_boundary_checks(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    executable_cards = [card for card in ir.character_data_cards if card.coverage_status == "executable"]
    binding_ids = {binding.binding_id for binding in ir.skill_formula_bindings}
    checks = {
        "character_data_cards_exist": bool(ir.character_data_cards),
        "executable_character_data_card_exists": bool(executable_cards),
        "avatar_profiles_exist": bool(ir.avatar_profiles),
        "rulebook_returns_character_data_card": bool(
            executable_cards and rules.character_data_card(executable_cards[0].card_id) is not None
        ),
        "rulebook_returns_card_by_entity": bool(
            executable_cards and rules.character_data_card_for_entity(executable_cards[0].entity_ref) is not None
        ),
        "card_binding_ids_resolve": all(
            binding_id in binding_ids
            for card in executable_cards[:50]
            for binding_id in card.skill_formula_binding_ids
        ),
        "executable_bindings_have_card": all(
            bool(binding.character_data_card_id)
            for binding in ir.skill_formula_bindings
            if binding.coverage_status == "executable"
        ),
        "executable_binding_cards_resolve": all(
            rules.character_data_card(binding.character_data_card_id) is not None
            for binding in ir.skill_formula_bindings[:2000]
            if binding.coverage_status == "executable"
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _direct_damage_card_formula_checks(ir: CanonicalIR) -> dict[str, Any]:
    executable_direct = [
        emission
        for emission in ir.damage_emissions
        if emission.damage_formula_family == "direct" and emission.coverage_status == "executable"
    ]
    blocked_direct = [
        emission
        for emission in ir.damage_emissions
        if emission.damage_formula_family == "direct" and emission.coverage_status == "blocked"
    ]
    checks = {
        "executable_direct_exists": bool(executable_direct),
        "executable_direct_uses_character_data_card_formula": all(
            emission.scaling_basis_expr.get("source_kind") == "character_data_card_skill_formula"
            and bool(emission.scaling_basis_expr.get("character_data_card_id"))
            for emission in executable_direct
        ),
        "no_executable_direct_uses_legacy_text_binding": all(
            emission.scaling_basis_expr.get("source_kind") != "skill_text_param_binding"
            for emission in executable_direct
        ),
        "no_executable_direct_uses_current_scope_attack_basis": all(
            emission.scaling_basis_expr.get("source_kind") != "current_direct_damage_admission"
            for emission in executable_direct
        ),
        "blocked_direct_has_reason": all(bool(emission.blocked_reason) for emission in blocked_direct),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _legacy_text_parser_boundary_checks(package_root: Path) -> dict[str, Any]:
    lowering_path = package_root / "tbgd/lowering.py"
    text = lowering_path.read_text(encoding="utf-8")
    checks = {
        "lowering_has_no_skill_text_parser_patterns": "SKILL_TEXT_DAMAGE_BINDING_PATTERNS" not in text,
        "lowering_has_no_text_map_loader": "def _load_text_map" not in text,
        "lowering_has_no_skill_formula_row_parser": "def _skill_formula_bindings_from_row" not in text,
    }
    return {"ok": all(checks.values()), "checks": checks}


def _character_data_card_samples(ir: CanonicalIR) -> dict[str, Any]:
    executable_cards = [card.to_json() for card in ir.character_data_cards if card.coverage_status == "executable"]
    executable_bindings = [
        binding.to_json()
        for binding in ir.skill_formula_bindings
        if binding.coverage_status == "executable" and binding.character_data_card_id
    ]
    return {
        "executable_character_data_cards": executable_cards[:5],
        "executable_skill_formula_bindings": executable_bindings[:5],
    }


if __name__ == "__main__":
    raise SystemExit(main())
