from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p4_s0_combatant_source_inventory"
MATRIX_SCHEMA_VERSION = "p4_s0_combatant_source_inventory_matrix_v2"
MAX_SOURCE_SAMPLES = 5

CLASSIFICATION_STATES = {
    "executable",
    "boundary_only",
    "source_absent_not_required",
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
    "out_of_scope",
}
GAP_STATES = {
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p4_s0_combatant_source_inventory_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p4_s0_combatant_source_inventory_matrix(matrix)
    checks = {
        "inventory": inventory_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p4_s0_source_inventory_structured_domains",
                "runtime_behavior_changed": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": {
            "domain_count": len(matrix["domain_matrix"]),
            "classification_counts": matrix["classification_counts"],
            "gap_attribution_counts": matrix["gap_attribution_counts"],
            "unclassified_count": matrix["unclassified_count"],
            "raw_count_total": matrix["raw_count_total"],
            "ir_count_total": matrix["ir_count_total"],
            "rulebook_visible_count_total": matrix["rulebook_visible_count_total"],
            "executable_count_total": matrix["executable_count_total"],
            "blocked_or_gap_count_total": matrix["blocked_or_gap_count_total"],
        },
        "domain_matrix": matrix["domain_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s0_combatant_source_inventory.json", result)
    write_json(output_dir / "p4_s0_combatant_source_inventory_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S0 combatant data-card source inventory.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation ok={result['ok']} "
        f"unclassified={result['summary']['unclassified_count']} "
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p4_s0_combatant_source_inventory_matrix(
    tbgd_root: Path,
    ir: CanonicalIR,
    rules: RuleBook,
) -> dict[str, Any]:
    raw = _raw_inventory(tbgd_root)
    raw_samples = _raw_source_samples(tbgd_root)
    rows = _build_source_family_rows(tbgd_root, ir, rules, raw, raw_samples)
    domain_matrix = {row["source_family"]: row for row in rows}

    classification_counts = Counter(row["classification"] for row in domain_matrix.values())
    gap_attribution_counts: Counter[str] = Counter()
    for row in domain_matrix.values():
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_attribution_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "domain_matrix": domain_matrix,
        "classification_counts": dict(sorted(classification_counts.items())),
        "gap_attribution_counts": dict(sorted(gap_attribution_counts.items())),
        "unclassified_count": int(classification_counts.get("unclassified", 0)),
        "raw_count_total": sum(int(row.get("raw_count") or 0) for row in domain_matrix.values()),
        "ir_count_total": sum(int(row.get("ir_count") or 0) for row in domain_matrix.values()),
        "rulebook_visible_count_total": sum(int(row.get("rulebook_visible_count") or 0) for row in domain_matrix.values()),
        "executable_count_total": sum(int(row.get("executable_count") or 0) for row in domain_matrix.values()),
        "blocked_or_gap_count_total": sum(int(row.get("blocked_or_gap_count") or 0) for row in domain_matrix.values()),
        "resource_budget": {
            "rulebook_build_count": 1,
            "subprocess_validation_count": 0,
            "p3_s0_inventory_reused_in_memory": False,
            "p3_backlog_projected_from_current_ir": True,
            "raw_token_scan_count": raw["raw_token_scan_count"],
            "large_artifacts_written": False,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "output_scope": "summary_source_family_matrix_raw_samples_ir_samples_boundary_samples_only",
        },
        "raw_inventory_summary": raw,
    }


def _build_source_family_rows(
    tbgd_root: Path,
    ir: CanonicalIR,
    rules: RuleBook,
    raw: dict[str, int],
    raw_samples: dict[str, list[dict[str, JSONValue]]],
) -> list[dict[str, JSONValue]]:
    excel = tbgd_root / "ExcelOutput"
    config = tbgd_root / "Config"
    config_character = config / "ConfigCharacter"
    config_ability = config / "ConfigAbility"
    global_config = config / "GlobalConfig"
    config_global_modifier = config / "ConfigGlobalModifier"

    action_items = _action_graph_items(ir)
    formula_items = _formula_items(ir)
    passive_items = _passive_listener_items(ir)
    rows: list[dict[str, JSONValue]] = []

    def add(row: dict[str, JSONValue]) -> None:
        rows.append(row)

    add(
        _source_family_row(
            "avatar_config_profile_cards",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/AvatarConfig.json",
            raw_count=raw["AvatarConfig"],
            raw_source_samples=raw_samples["AvatarConfig"],
            ir_container="AvatarProfileIR + CharacterDataCardIR",
            ir_items=_items_by_source((*ir.avatar_profiles, *ir.character_data_cards), raw_types=("AvatarConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.avatar_profile(avatar_id), RuleBook.character_data_card(card_id), character_data_card_for_entity(entity_ref)",
            projection_predicate="IR source.raw_type == AvatarConfig",
            notes="Base avatar rows are the primary character profile/card source.",
            future_owner="CharacterDataCardIR / AvatarProfileIR assembly",
        )
    )
    add(
        _source_family_row(
            "avatar_config_ld_profile_cards",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/AvatarConfigLD.json",
            raw_count=raw["AvatarConfigLD"],
            raw_source_samples=raw_samples["AvatarConfigLD"],
            ir_container="AvatarProfileIR + CharacterDataCardIR",
            ir_items=_items_by_source((*ir.avatar_profiles, *ir.character_data_cards), raw_types=("AvatarConfigLD",)),
            rules=rules,
            rulebook_query_surface="same as AvatarConfig; LD rows must not be silently ignored",
            projection_predicate="IR source.raw_type == AvatarConfigLD",
            notes="LD avatar rows are inventoried separately from base rows.",
            future_owner="CharacterDataCardIR / AvatarProfileIR assembly",
        )
    )
    add(
        _source_family_row(
            "avatar_config_enhanced_profile_cards",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/AvatarConfigEnhanced.json",
            raw_count=raw["AvatarConfigEnhanced"],
            raw_source_samples=raw_samples["AvatarConfigEnhanced"],
            ir_container="AvatarProfileIR + CharacterDataCardIR",
            ir_items=_items_by_source((*ir.avatar_profiles, *ir.character_data_cards), raw_types=("AvatarConfigEnhanced",)),
            rules=rules,
            rulebook_query_surface="same as AvatarConfig; enhanced rows must remain source-traced",
            projection_predicate="IR source.raw_type == AvatarConfigEnhanced",
            notes="Enhanced avatar rows must be visible as enhanced/base override source, not collapsed into unnamed defaults.",
            future_owner="CharacterDataCardIR / AvatarProfileIR assembly",
        )
    )
    add(
        _source_family_row(
            "avatar_promotion_config_profile_stats",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/AvatarPromotionConfig.json",
            raw_count=raw["AvatarPromotionConfig"],
            raw_source_samples=raw_samples["AvatarPromotionConfig"],
            ir_container="AvatarProfileIR.promotion_tiers",
            ir_items=tuple(
                tier
                for profile in ir.avatar_profiles
                for tier in profile.promotion_tiers
                if tier.source.source_path == "ExcelOutput/AvatarPromotionConfig.json"
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.avatar_profile(avatar_id)",
            projection_predicate="AvatarProfileIR.promotion_tiers is non-empty and typed",
            notes="Promotion data is projected into avatar profile stats; S0 records that it is not a standalone runtime rule.",
            future_owner="Character profile/stat assembly",
        )
    )
    add(
        _source_family_row(
            "avatar_skill_config_actions",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/AvatarSkillConfig.json",
            raw_count=raw["AvatarSkillConfig"],
            raw_source_samples=raw_samples["AvatarSkillConfig"],
            ir_container="ActionDefinitionIR / ActionEventIR / ActionAbilityBindingIR / AbilityPhaseIR / AbilityTaskIR",
            ir_items=_items_by_source(action_items, raw_types=("AvatarSkillConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.action_definition/action_event/action_ability_binding/ability_phase/ability_task",
            projection_predicate="action graph IR source.raw_type == AvatarSkillConfig",
            notes="Character skill rows are action sources, not runtime special cases.",
            future_owner="Combatant action set / action availability",
        )
    )
    add(
        _source_family_row(
            "avatar_technique_skill_sources",
            raw_source_kind="json_row_field_value",
            raw_path_or_field="ExcelOutput/AvatarSkillConfig.json:SkillTriggerKey=SkillMaze or AttackType=Maze",
            raw_count=_json_row_field_value_count(
                excel / "AvatarSkillConfig.json",
                {"SkillTriggerKey": ("SkillMaze",), "AttackType": ("Maze",)},
            ),
            raw_source_samples=_json_row_field_value_samples(
                tbgd_root,
                excel / "AvatarSkillConfig.json",
                {"SkillTriggerKey": ("SkillMaze",), "AttackType": ("Maze",)},
            ),
            ir_container="ActionDefinitionIR / ActionEventIR / ActionAbilityBindingIR / AbilityPhaseIR / AbilityTaskIR",
            ir_items=_items_by_source_and_tokens(action_items, raw_types=("AvatarSkillConfig",), tokens=("skillmaze", "maze")),
            rules=rules,
            rulebook_query_surface="same avatar action graph RuleBook accessors; technique remains an action source, not UI/planner logic",
            projection_predicate="AvatarSkillConfig rows with SkillTriggerKey=SkillMaze or AttackType=Maze projected into action graph IR",
            notes="Technique rows are inventoried explicitly so they are not hidden inside generic avatar skill actions.",
            future_owner="P4-S2/P4-S7 technique action availability",
        )
    )
    add(
        _source_family_row(
            "avatar_enhanced_skill_effect_sources",
            raw_source_kind="json_row_field_value",
            raw_path_or_field="ExcelOutput/AvatarSkillConfig.json:SkillEffect=Enhance",
            raw_count=_json_row_field_value_count(excel / "AvatarSkillConfig.json", {"SkillEffect": ("Enhance",)}),
            raw_source_samples=_json_row_field_value_samples(
                tbgd_root,
                excel / "AvatarSkillConfig.json",
                {"SkillEffect": ("Enhance",)},
            ),
            ir_container="ActionDefinitionIR / ActionEventIR / ActionAbilityBindingIR / AbilityPhaseIR / AbilityTaskIR",
            ir_items=_items_by_source_and_tokens(action_items, raw_types=("AvatarSkillConfig",), tokens=("enhance",)),
            rules=rules,
            rulebook_query_surface="same avatar action graph RuleBook accessors; enhanced/replace actions stay data-card sourced",
            projection_predicate="AvatarSkillConfig rows with SkillEffect=Enhance projected into action graph IR",
            notes="Enhanced-form action sources are inventoried separately from ordinary skill rows.",
            future_owner="P4-S2/P4-S7 enhanced/replace action availability",
        )
    )
    add(
        _source_family_row(
            "common_avatar_skill_config_actions",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/CommonAvatarSkillConfig.json",
            raw_count=raw["CommonAvatarSkillConfig"],
            raw_source_samples=raw_samples["CommonAvatarSkillConfig"],
            ir_container="ActionDefinitionIR / ActionEventIR / ActionAbilityBindingIR / AbilityPhaseIR / AbilityTaskIR",
            ir_items=_items_by_source(action_items, raw_types=("CommonAvatarSkillConfig",)),
            rules=rules,
            rulebook_query_surface="same action graph RuleBook accessors as AvatarSkillConfig",
            projection_predicate="action graph IR source.raw_type == CommonAvatarSkillConfig",
            notes="Common avatar skill rows are separate raw sources and must not be hidden under base avatar skills.",
            future_owner="Combatant action set / action availability",
        )
    )
    add(
        _source_family_row(
            "avatar_skilltree_config_trace_slots",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/AvatarSkillTreeConfig.json",
            raw_count=raw["AvatarSkillTreeConfig"],
            raw_source_samples=raw_samples["AvatarSkillTreeConfig"],
            ir_container="CharacterTraceNodeIR + CharacterMechanismSlotIR",
            ir_items=_items_by_source((*ir.character_trace_nodes, *ir.character_mechanism_slots), raw_types=("AvatarSkillTreeConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.character_trace_node / character_mechanism_slot / *_for_card",
            projection_predicate="trace/mechanism IR source.raw_type == AvatarSkillTreeConfig",
            notes="Trace rows are character mechanism slots or blocked trace boundaries.",
            future_owner="Character trace/mechanism admission",
        )
    )
    add(
        _source_family_row(
            "avatar_skilltree_status_add_sources",
            raw_source_kind="json_field_group",
            raw_path_or_field="ExcelOutput/AvatarSkillTreeConfig.json:StatusAddList",
            raw_count=_json_field_count(excel / "AvatarSkillTreeConfig.json", "StatusAddList"),
            raw_source_samples=_json_field_samples(tbgd_root, excel / "AvatarSkillTreeConfig.json", "StatusAddList"),
            ir_container="CharacterTraceNodeIR + CharacterMechanismSlotIR",
            ir_items=_items_by_source_and_tokens(
                (*ir.character_trace_nodes, *ir.character_mechanism_slots),
                raw_types=("AvatarSkillTreeConfig",),
                tokens=("statusaddlist", "status_add", "statusadd"),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.character_trace_node / character_mechanism_slot",
            projection_predicate="AvatarSkillTreeConfig StatusAddList rows projected into character trace/mechanism slots",
            notes="Trace-provided status-add/startup-style inputs are explicit S0 inventory rows, not inferred from generic trace presence.",
            future_owner="P4-S8/P4-S9 trace status/resource admission",
        )
    )
    add(
        _source_family_row(
            "avatar_rank_config_eidolon_slots",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/AvatarRankConfig.json",
            raw_count=raw["AvatarRankConfig"],
            raw_source_samples=raw_samples["AvatarRankConfig"],
            ir_container="CharacterEidolonSlotIR + CharacterMechanismSlotIR",
            ir_items=_items_by_source((*ir.character_eidolon_slots, *ir.character_mechanism_slots), raw_types=("AvatarRankConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.character_eidolon_slot / character_eidolon_slots_for_level / character_mechanism_slot",
            projection_predicate="eidolon/mechanism IR source.raw_type == AvatarRankConfig",
            notes="Eidolon rows are inventory slots until admitted by character mechanism stages.",
            future_owner="Character eidolon/mechanism admission",
        )
    )
    add(
        _source_family_row(
            "config_character_localplayer_sources",
            raw_source_kind="config_file_tree",
            raw_path_or_field="Config/ConfigCharacter/LocalPlayer/**/*.json",
            raw_count=raw["ConfigCharacter.LocalPlayer"],
            raw_source_samples=raw_samples["ConfigCharacter.LocalPlayer"],
            ir_container="CharacterMechanismSlotIR / CharacterTraceNodeIR / CharacterDataCardIR evidence",
            ir_items=_items_by_source_tokens(
                (*ir.character_mechanism_slots, *ir.character_trace_nodes, *ir.character_data_cards),
                path_contains=("Config/ConfigCharacter/LocalPlayer",),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook character card/trace/mechanism accessors where projected",
            projection_predicate="IR source/evidence JSON contains Config/ConfigCharacter/LocalPlayer",
            notes="LocalPlayer config files describe maze/local-player behavior; battle character configs are under Config/ConfigCharacter/Avatar and feed character cards separately.",
            future_owner="maze/local-player character layer",
            forced_classification="out_of_scope",
        )
    )
    add(
        _source_family_row(
            "config_ability_avatar_graphs",
            raw_source_kind="config_file_tree",
            raw_path_or_field="Config/ConfigAbility/Avatar*/Avatar_*.json",
            raw_count=raw["ConfigAbility.AvatarLike"],
            raw_source_samples=raw_samples["ConfigAbility.AvatarLike"],
            ir_container="ActionAbilityBindingIR / AbilityPhaseIR / AbilityTaskIR / StandaloneAbilityGraphIR",
            ir_items=_items_by_source((*ir.action_ability_bindings, *ir.ability_phases, *ir.ability_tasks, *ir.standalone_ability_graphs), path_contains=("Config/ConfigAbility/Avatar",)),
            rules=rules,
            rulebook_query_surface="RuleBook.action_ability_binding, ability_phase, ability_task, standalone_ability_graph",
            projection_predicate="IR source.source_path contains Config/ConfigAbility/Avatar",
            notes="Avatar ability graph files carry executable or blocked action graph details.",
            future_owner="Ability graph lowering/admission",
        )
    )

    add(
        _source_family_row(
            "avatar_servant_config_subcard_sources",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/AvatarServantConfig.json",
            raw_count=raw["AvatarServantConfig"],
            raw_source_samples=raw_samples["AvatarServantConfig"],
            ir_container="ServantDefinitionIR",
            ir_items=_items_by_source(ir.servant_definitions, raw_types=("AvatarServantConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.servant_definition / servant_definitions_for_owner",
            projection_predicate="ServantDefinitionIR.source.raw_type == AvatarServantConfig",
            blocked_boundary_samples=_hook_boundary_samples(
                "character_servant_subcard_hook",
                "CharacterDataCardIR owns servant subcards or derived combatant cards.",
                "missing owner_entity_ref, servant definition, stat source, action set, or lifecycle source keeps the servant boundary blocked/no-op.",
            ),
            notes="Servant definitions are owner-character subcard sources and must not be treated as ordinary buffs.",
            future_owner="Character servant subcard / derived combatant card",
        )
    )
    add(
        _source_family_row(
            "avatar_servant_skill_config_actions",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/AvatarServantSkillConfig.json",
            raw_count=raw["AvatarServantSkillConfig"],
            raw_source_samples=raw_samples["AvatarServantSkillConfig"],
            ir_container="servant action graph IR",
            ir_items=_items_by_source(action_items, raw_types=("AvatarServantSkillConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook action graph accessors for servant skills",
            projection_predicate="action graph IR source.raw_type == AvatarServantSkillConfig",
            notes="Servant skills remain tied to the owner servant subcard/action set.",
            future_owner="Servant action availability",
        )
    )
    add(
        _source_family_row(
            "config_character_servant_sources",
            raw_source_kind="config_file_tree",
            raw_path_or_field="Config/ConfigCharacter/Servant/**/*.json",
            raw_count=raw["ConfigCharacter.Servant"],
            raw_source_samples=raw_samples["ConfigCharacter.Servant"],
            ir_container="ServantDefinitionIR evidence",
            ir_items=_items_by_source_tokens(
                ir.servant_definitions,
                path_contains=("Config/ConfigCharacter/Servant",),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.servant_definition / servant_definitions_for_owner",
            projection_predicate="ServantDefinitionIR source/evidence JSON contains Config/ConfigCharacter/Servant",
            notes="Servant character config files are inventoried as servant subcard evidence.",
            future_owner="Character servant subcard assembly",
        )
    )
    add(
        _source_family_row(
            "config_ability_servant_graphs",
            raw_source_kind="config_file_tree",
            raw_path_or_field="Config/ConfigAbility/Servant/**/*.json",
            raw_count=raw["ConfigAbility.Servant"],
            raw_source_samples=raw_samples["ConfigAbility.Servant"],
            ir_container="servant ability graph IR",
            ir_items=_items_by_source((*ir.action_ability_bindings, *ir.ability_phases, *ir.ability_tasks, *ir.standalone_ability_graphs), path_contains=("Config/ConfigAbility/Servant",)),
            rules=rules,
            rulebook_query_surface="RuleBook action graph and standalone ability graph accessors",
            projection_predicate="IR source path contains Config/ConfigAbility/Servant",
            notes="Servant ability graph files must remain under servant/owner attribution.",
            future_owner="Servant action graph admission",
        )
    )

    add(
        _source_family_row(
            "monster_config_base_cards",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/MonsterConfig.json",
            raw_count=raw["MonsterConfig"],
            raw_source_samples=raw_samples["MonsterConfig"],
            ir_container="MonsterDataCardIR + CombatantProfileIR",
            ir_items=_items_by_source((*ir.monster_data_cards, *ir.combatant_profiles), raw_types=("MonsterConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.monster_data_card / monster_data_card_for_entity / combatant_profile",
            projection_predicate="monster card/profile source.raw_type == MonsterConfig",
            notes="Monster base rows own monster cards, base stats, weaknesses, resistances, skill lists, and summon refs.",
            future_owner="MonsterDataCardIR assembly",
        )
    )
    add(
        _source_family_row(
            "monster_template_config_profiles",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/MonsterTemplateConfig.json",
            raw_count=raw["MonsterTemplateConfig"],
            raw_source_samples=raw_samples["MonsterTemplateConfig"],
            ir_container="CombatantProfileIR / MonsterDataCardIR.template evidence",
            ir_items=_items_by_source((*ir.combatant_profiles, *ir.monster_data_cards), raw_types=("MonsterTemplateConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.combatant_profile and monster card contract evidence",
            projection_predicate="IR source.raw_type == MonsterTemplateConfig",
            notes="Template rows are separate monster stat/stage input sources; gaps must not be hidden by MonsterConfig rows.",
            future_owner="Monster profile/template assembly",
        )
    )
    add(
        _source_family_row(
            "monster_template_unique_config_overrides",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/MonsterTemplateUniqueConfig.json",
            raw_count=raw["MonsterTemplateUniqueConfig"],
            raw_source_samples=raw_samples["MonsterTemplateUniqueConfig"],
            ir_container="MonsterDataCardIR / CombatantProfileIR unique override evidence",
            ir_items=_items_by_source((*ir.monster_data_cards, *ir.combatant_profiles), raw_types=("MonsterTemplateUniqueConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook monster/profile accessors when projected",
            projection_predicate="IR source.raw_type == MonsterTemplateUniqueConfig",
            notes="Unique template overrides are inventoried separately and may remain a lowering/admission gap.",
            future_owner="Future monster template override assembly",
        )
    )
    add(
        _source_family_row(
            "monster_config_skill_list_action_set",
            raw_source_kind="json_field",
            raw_path_or_field="ExcelOutput/MonsterConfig.json:SkillList",
            raw_count=_json_field_count(excel / "MonsterConfig.json", "SkillList"),
            raw_source_samples=_json_field_samples(tbgd_root, excel / "MonsterConfig.json", "SkillList"),
            ir_container="MonsterDataCardIR.skill_ids + CombatantActionSetIR",
            ir_items=(
                *tuple(card for card in ir.monster_data_cards if card.skill_ids),
                *tuple(action_set for action_set in ir.combatant_action_sets if action_set.entity_ref.startswith("monster:")),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.monster_data_card and combatant_action_set(entity_ref)",
            projection_predicate="monster cards with skill_ids and monster combatant action sets",
            notes="Monster SkillList is an action set source; enemy AI still does not enter core.",
            future_owner="Monster action availability",
        )
    )
    add(
        _source_family_row(
            "monster_skill_config_actions",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/MonsterSkillConfig.json",
            raw_count=raw["MonsterSkillConfig"],
            raw_source_samples=raw_samples["MonsterSkillConfig"],
            ir_container="monster action graph IR",
            ir_items=_items_by_source(action_items, raw_types=("MonsterSkillConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook action graph accessors",
            projection_predicate="action graph IR source.raw_type == MonsterSkillConfig",
            notes="Normal monster skill rows are action graph sources.",
            future_owner="Monster action graph admission",
        )
    )
    add(
        _source_family_row(
            "monster_skill_unique_config_actions",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/MonsterSkillUniqueConfig.json",
            raw_count=raw["MonsterSkillUniqueConfig"],
            raw_source_samples=raw_samples["MonsterSkillUniqueConfig"],
            ir_container="monster action graph IR",
            ir_items=_items_by_source(action_items, raw_types=("MonsterSkillUniqueConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook action graph accessors",
            projection_predicate="action graph IR source.raw_type == MonsterSkillUniqueConfig",
            notes="Unique monster skill rows are inventoried separately from normal monster skills.",
            future_owner="Monster action graph admission",
        )
    )
    add(
        _source_family_row(
            "ilbattle_monster_skill_actions",
            raw_source_kind="json_table",
            raw_path_or_field="ExcelOutput/ILBattleMonsterSkill.json",
            raw_count=raw["ILBattleMonsterSkill"],
            raw_source_samples=raw_samples["ILBattleMonsterSkill"],
            ir_container="ILBattle monster action graph IR",
            ir_items=_items_by_source(action_items, raw_types=("ILBattleMonsterSkill",)),
            rules=rules,
            rulebook_query_surface="RuleBook action graph accessors",
            projection_predicate="action graph IR source.raw_type == ILBattleMonsterSkill",
            notes="ILBattle monster skills are their own source family and cannot be inferred from normal monster skills.",
            future_owner="Monster action graph admission",
        )
    )
    add(
        _source_family_row(
            "config_character_monster_sources",
            raw_source_kind="config_file_tree",
            raw_path_or_field="Config/ConfigCharacter/Monster/**/*.json",
            raw_count=raw["ConfigCharacter.Monster"],
            raw_source_samples=raw_samples["ConfigCharacter.Monster"],
            ir_container="MonsterDataCardIR / monster action graph evidence",
            ir_items=_items_by_source((*ir.monster_data_cards, *action_items), path_contains=("Config/ConfigCharacter/Monster",)),
            rules=rules,
            rulebook_query_surface="RuleBook monster card/action graph accessors when projected",
            projection_predicate="IR source path contains Config/ConfigCharacter/Monster",
            notes="Monster character config files are inventoried; lack of projection is not source absence.",
            future_owner="Monster card config assembly",
        )
    )
    add(
        _source_family_row(
            "config_ability_monster_graphs",
            raw_source_kind="config_file_tree",
            raw_path_or_field="Config/ConfigAbility/Monster/**/*.json",
            raw_count=raw["ConfigAbility.Monster"],
            raw_source_samples=raw_samples["ConfigAbility.Monster"],
            ir_container="monster ability graph / passive listener IR",
            ir_items=_items_by_source((*action_items, *passive_items), path_contains=("Config/ConfigAbility/Monster",)),
            rules=rules,
            rulebook_query_surface="RuleBook action graph, passive, callback, queue accessors",
            projection_predicate="IR source path contains Config/ConfigAbility/Monster",
            notes="Monster ability files can feed both active skills and passive/listener slots.",
            future_owner="Monster action/passive admission",
        )
    )
    add(
        _source_family_row(
            "monster_config_override_ai_sequence",
            raw_source_kind="json_field",
            raw_path_or_field="ExcelOutput/MonsterConfig.json:OverrideAISkillSequence",
            raw_count=_json_field_count(excel / "MonsterConfig.json", "OverrideAISkillSequence"),
            raw_source_samples=_json_field_samples(tbgd_root, excel / "MonsterConfig.json", "OverrideAISkillSequence"),
            ir_container="MonsterDataCardIR.action_sequence",
            ir_items=tuple(card for card in ir.monster_data_cards if _card_has_sequence_kind(card, "monster_override")),
            rules=rules,
            rulebook_query_surface="RuleBook.monster_data_card; action_sequence remains externally selected, not AI runtime",
            projection_predicate="MonsterDataCardIR.action_sequence contains sequence_kind == monster_override",
            notes="Override fixed sequences are action candidates only; core still does not auto-select enemy actions.",
            future_owner="Monster action availability / external planner boundary",
        )
    )
    add(
        _source_family_row(
            "monster_template_ai_sequence",
            raw_source_kind="json_field",
            raw_path_or_field="ExcelOutput/MonsterTemplateConfig.json:AISkillSequence",
            raw_count=_json_field_count(excel / "MonsterTemplateConfig.json", "AISkillSequence"),
            raw_source_samples=_json_field_samples(tbgd_root, excel / "MonsterTemplateConfig.json", "AISkillSequence"),
            ir_container="MonsterDataCardIR.action_sequence",
            ir_items=tuple(card for card in ir.monster_data_cards if _card_has_sequence_kind(card, "template_default")),
            rules=rules,
            rulebook_query_surface="RuleBook.monster_data_card; fixed sequence remains action candidate source",
            projection_predicate="MonsterDataCardIR.action_sequence contains sequence_kind == template_default",
            notes="Template fixed sequences are catalogued as candidates, not enemy AI.",
            future_owner="Monster action availability / external planner boundary",
        )
    )
    add(
        _source_family_row(
            "monster_config_ability_name_list_passives",
            raw_source_kind="json_field",
            raw_path_or_field="ExcelOutput/MonsterConfig.json:AbilityNameList",
            raw_count=raw["monster_config_ability_name_list_count"],
            raw_source_samples=raw_samples["MonsterConfig.AbilityNameList"],
            ir_container="PassiveMechanismSlotIR",
            ir_items=tuple(slot for slot in ir.passive_mechanism_slots if slot.data_card_kind == "monster"),
            rules=rules,
            rulebook_query_surface="RuleBook.passive_mechanism_slot / passive_mechanism_slots_for_card / passive_mechanism_slots_for_owner",
            projection_predicate="PassiveMechanismSlotIR.data_card_kind == monster",
            notes="Monster AbilityNameList is a passive entry source, not the full passive system by itself.",
            future_owner="Monster passive/listener admission",
        )
    )
    add(
        _source_family_row(
            "config_global_modifier_listener_sources",
            raw_source_kind="config_file_tree",
            raw_path_or_field="Config/ConfigGlobalModifier/**/*.json",
            raw_count=raw["ConfigGlobalModifier"],
            raw_source_samples=_file_tree_samples(tbgd_root, config_global_modifier),
            ir_container="StatusCallbackIR / StatusCallbackTaskIR / QueueIntentIR / TriggerIR",
            ir_items=_items_by_source((*passive_items, *ir.triggers), path_contains=("Config/ConfigGlobalModifier",)),
            rules=rules,
            rulebook_query_surface="RuleBook.status_callback/status_callback_task/queue_intent/trigger",
            projection_predicate="IR source path contains Config/ConfigGlobalModifier",
            notes="Global modifier listener sources must remain distinct from monster-card owned passives.",
            future_owner="Status listener and passive admission",
        )
    )
    add(
        _source_family_row(
            "monster_passive_start_enter_listener_sources",
            raw_source_kind="recursive_json_event_value",
            raw_path_or_field="Config/ConfigAbility/Monster + ConfigGlobalModifier:Event contains start/enterbattle/create",
            raw_count=_json_tree_field_value_token_count(config_ability / "Monster", "Event", ("start", "enterbattle", "create"))
            + _json_tree_field_value_token_count(config_global_modifier, "Event", ("start", "enterbattle", "create")),
            raw_source_samples=[
                *_json_tree_field_value_token_samples(tbgd_root, config_ability / "Monster", "Event", ("start", "enterbattle", "create")),
                *_json_tree_field_value_token_samples(tbgd_root, config_global_modifier, "Event", ("start", "enterbattle", "create")),
            ][:MAX_SOURCE_SAMPLES],
            ir_container="StatusCallbackIR / StatusCallbackTaskIR / QueueIntentIR / TriggerIR",
            ir_items=_items_by_source_and_tokens(
                (*passive_items, *ir.triggers),
                path_contains=("Config/ConfigAbility/Monster", "Config/ConfigGlobalModifier"),
                tokens=("start", "enterbattle", "create"),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.status_callback/status_callback_task/queue_intent/trigger",
            projection_predicate="listener IR sourced from monster/global modifier files and containing start/enter/create event markers",
            notes="Monster startup/on-enter listener sources are separated from the wider global modifier inventory.",
            future_owner="P4-S6 monster passive/listener admission",
        )
    )
    add(
        _source_family_row(
            "monster_passive_wave_listener_sources",
            raw_source_kind="recursive_json_event_value",
            raw_path_or_field="Config/ConfigAbility/Monster + ConfigGlobalModifier:Event contains wave",
            raw_count=_json_tree_field_value_token_count(config_ability / "Monster", "Event", ("wave",))
            + _json_tree_field_value_token_count(config_global_modifier, "Event", ("wave",)),
            raw_source_samples=[
                *_json_tree_field_value_token_samples(tbgd_root, config_ability / "Monster", "Event", ("wave",)),
                *_json_tree_field_value_token_samples(tbgd_root, config_global_modifier, "Event", ("wave",)),
            ][:MAX_SOURCE_SAMPLES],
            ir_container="StatusCallbackIR / StatusCallbackTaskIR / QueueIntentIR / TriggerIR",
            ir_items=_items_by_source_and_tokens(
                (*passive_items, *ir.triggers),
                path_contains=("Config/ConfigAbility/Monster", "Config/ConfigGlobalModifier"),
                tokens=("wave",),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.status_callback/status_callback_task/queue_intent/trigger",
            projection_predicate="listener IR sourced from monster/global modifier files and containing wave event markers",
            notes="On-wave listener sources stay explicit and must not be treated as absent just because wave runtime is later work.",
            future_owner="P4-S6 monster passive/listener and future wave admission",
        )
    )
    add(
        _source_family_row(
            "monster_passive_death_listener_sources",
            raw_source_kind="recursive_json_event_value",
            raw_path_or_field="Config/ConfigAbility/Monster + ConfigGlobalModifier:Event contains death/die/dying",
            raw_count=_json_tree_field_value_token_count(config_ability / "Monster", "Event", ("death", "die", "dying"))
            + _json_tree_field_value_token_count(config_global_modifier, "Event", ("death", "die", "dying")),
            raw_source_samples=[
                *_json_tree_field_value_token_samples(tbgd_root, config_ability / "Monster", "Event", ("death", "die", "dying")),
                *_json_tree_field_value_token_samples(tbgd_root, config_global_modifier, "Event", ("death", "die", "dying")),
            ][:MAX_SOURCE_SAMPLES],
            ir_container="StatusCallbackIR / StatusCallbackTaskIR / QueueIntentIR / TriggerIR",
            ir_items=_items_by_source_and_tokens(
                (*passive_items, *ir.triggers),
                path_contains=("Config/ConfigAbility/Monster", "Config/ConfigGlobalModifier"),
                tokens=("death", "die", "dying"),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.status_callback/status_callback_task/queue_intent/trigger",
            projection_predicate="listener IR sourced from monster/global modifier files and containing death/die event markers",
            notes="Death listener sources are explicit passive/listener inventory rows.",
            future_owner="P4-S6 monster passive/listener admission",
        )
    )
    add(
        _source_family_row(
            "monster_passive_hit_attack_listener_sources",
            raw_source_kind="recursive_json_event_value",
            raw_path_or_field="Config/ConfigAbility/Monster + ConfigGlobalModifier:Event contains hit/attack/attacked",
            raw_count=_json_tree_field_value_token_count(config_ability / "Monster", "Event", ("hit", "attack", "attacked"))
            + _json_tree_field_value_token_count(config_global_modifier, "Event", ("hit", "attack", "attacked")),
            raw_source_samples=[
                *_json_tree_field_value_token_samples(tbgd_root, config_ability / "Monster", "Event", ("hit", "attack", "attacked")),
                *_json_tree_field_value_token_samples(tbgd_root, config_global_modifier, "Event", ("hit", "attack", "attacked")),
            ][:MAX_SOURCE_SAMPLES],
            ir_container="StatusCallbackIR / StatusCallbackTaskIR / QueueIntentIR / TriggerIR",
            ir_items=_items_by_source_and_tokens(
                (*passive_items, *ir.triggers),
                path_contains=("Config/ConfigAbility/Monster", "Config/ConfigGlobalModifier"),
                tokens=("hit", "attack", "attacked"),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.status_callback/status_callback_task/queue_intent/trigger",
            projection_predicate="listener IR sourced from monster/global modifier files and containing hit/attack event markers",
            notes="On-hit/on-attack listener sources are explicit passive/listener inventory rows.",
            future_owner="P4-S6 monster passive/listener admission",
        )
    )
    add(
        _source_family_row(
            "monster_passive_phase_skill_trigger_sources",
            raw_source_kind="recursive_json_event_value",
            raw_path_or_field="Config/ConfigAbility/Monster + ConfigGlobalModifier:Event contains phase/skill",
            raw_count=_json_tree_field_value_token_count(config_ability / "Monster", "Event", ("phase", "skill"))
            + _json_tree_field_value_token_count(config_global_modifier, "Event", ("phase", "skill")),
            raw_source_samples=[
                *_json_tree_field_value_token_samples(tbgd_root, config_ability / "Monster", "Event", ("phase", "skill")),
                *_json_tree_field_value_token_samples(tbgd_root, config_global_modifier, "Event", ("phase", "skill")),
            ][:MAX_SOURCE_SAMPLES],
            ir_container="StatusCallbackIR / StatusCallbackTaskIR / QueueIntentIR / TriggerIR",
            ir_items=_items_by_source_and_tokens(
                (*passive_items, *ir.triggers),
                path_contains=("Config/ConfigAbility/Monster", "Config/ConfigGlobalModifier"),
                tokens=("phase", "skill"),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.status_callback/status_callback_task/queue_intent/trigger",
            projection_predicate="listener IR sourced from monster/global modifier files and containing phase/skill event markers",
            notes="Phase/skill-trigger listener sources are explicit passive/listener inventory rows.",
            future_owner="P4-S6 monster passive/listener and phase admission",
        )
    )
    add(
        _source_family_row(
            "monster_config_summon_id_list_refs",
            raw_source_kind="json_field",
            raw_path_or_field="ExcelOutput/MonsterConfig.json:SummonIDList",
            raw_count=_json_field_count(excel / "MonsterConfig.json", "SummonIDList"),
            raw_source_samples=_json_field_samples(tbgd_root, excel / "MonsterConfig.json", "SummonIDList"),
            ir_container="MonsterDataCardIR.summon_refs",
            ir_items=tuple(card for card in ir.monster_data_cards if card.summon_refs),
            rules=rules,
            rulebook_query_surface="RuleBook.monster_data_card; summoned unit execution remains a later lifecycle/admission concern",
            projection_predicate="MonsterDataCardIR.summon_refs non-empty",
            forced_classification="boundary_only",
            blocked_boundary_samples=_hook_boundary_samples(
                "monster_summon_ref_boundary",
                "MonsterDataCardIR owns catalog refs; spawn intent/lifecycle admission belongs to later summon stages.",
                "summon refs alone cannot spawn units; missing intent, owner relation, lifecycle, or target source stays state unchanged.",
            ),
            notes="SummonIDList is inventoried as a catalog/lifecycle input, not an executable spawn trigger.",
            future_owner="P4-S6/P4-S10 monster summon lifecycle",
        )
    )

    add(
        _formula_row(
            "avatar_skill_param_formula_sources",
            "ExcelOutput/AvatarSkillConfig.json:ParamList",
            excel / "AvatarSkillConfig.json",
            "ParamList",
            _items_by_source_tokens(formula_items, path_contains=("ExcelOutput/AvatarSkillConfig.json",)),
            rules,
            raw_samples["AvatarSkillConfig"],
            "Character skill formula/parameter binding",
        )
    )
    add(
        _formula_row(
            "monster_skill_param_formula_sources",
            "ExcelOutput/MonsterSkillConfig.json:ParamList",
            excel / "MonsterSkillConfig.json",
            "ParamList",
            _items_by_source_tokens(formula_items, path_contains=("ExcelOutput/MonsterSkillConfig.json",)),
            rules,
            raw_samples["MonsterSkillConfig"],
            "Monster skill formula/parameter binding",
        )
    )
    add(
        _formula_row(
            "ilbattle_skill_param_formula_sources",
            "ExcelOutput/ILBattleMonsterSkill.json:ParamList",
            excel / "ILBattleMonsterSkill.json",
            "ParamList",
            _items_by_source_tokens(formula_items, path_contains=("ExcelOutput/ILBattleMonsterSkill.json",)),
            rules,
            raw_samples["ILBattleMonsterSkill"],
            "ILBattle monster skill formula/parameter binding",
            future_owner="ILBattle special action layer",
            forced_classification="out_of_scope",
        )
    )
    add(
        _source_family_row(
            "avatar_skill_resource_fields",
            raw_source_kind="json_field_group",
            raw_path_or_field="ExcelOutput/AvatarSkillConfig.json:BPNeed/BPAdd/SPBase/SPMultipleRatio",
            raw_count=_json_any_field_count(excel / "AvatarSkillConfig.json", ("BPNeed", "BPAdd", "SPBase", "SPMultipleRatio")),
            raw_source_samples=_json_any_field_samples(tbgd_root, excel / "AvatarSkillConfig.json", ("BPNeed", "BPAdd", "SPBase", "SPMultipleRatio")),
            ir_container="ActionDefinitionIR resource metadata / ResourceRuleIR",
            ir_items=_items_by_source((*ir.action_definitions, *ir.resource_rules), raw_types=("AvatarSkillConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.action_definition / resource_rule",
            projection_predicate="resource-related action definitions from AvatarSkillConfig",
            notes="Skill point and energy fields are source inputs for action availability/resource stages.",
            future_owner="P4-S2/P4-S9 resource admission",
        )
    )
    add(
        _source_family_row(
            "monster_skill_resource_fields",
            raw_source_kind="json_field_group",
            raw_path_or_field="ExcelOutput/MonsterSkillConfig.json:SPHitBase/AI_CD/AI_ICD",
            raw_count=_json_any_field_count(excel / "MonsterSkillConfig.json", ("SPHitBase", "AI_CD", "AI_ICD")),
            raw_source_samples=_json_any_field_samples(tbgd_root, excel / "MonsterSkillConfig.json", ("SPHitBase", "AI_CD", "AI_ICD")),
            ir_container="ActionDefinitionIR resource/cooldown metadata",
            ir_items=_items_by_source(ir.action_definitions, raw_types=("MonsterSkillConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.action_definition",
            projection_predicate="monster action definitions from MonsterSkillConfig",
            notes="Monster skill resource/cooldown fields are inventoried separately from action damage formula.",
            future_owner="P4-S2/P4-S5 resource/cooldown admission",
        )
    )
    add(
        _source_family_row(
            "dynamic_config_ability_fields",
            raw_source_kind="recursive_json_field_occurrence",
            raw_path_or_field="Config/ConfigAbility/**/*.json:DynamicValues/ReadInfo/CustomValue/hash-like fields",
            raw_count=_json_tree_key_count(config_ability, ("DynamicValues", "ReadInfo", "CustomValue", "CustomValues", "Hash", "HashValue")),
            raw_source_samples=_json_tree_key_samples(tbgd_root, config_ability, ("DynamicValues", "ReadInfo", "CustomValue", "CustomValues", "Hash", "HashValue")),
            ir_container="AbilityTaskIR / SkillFormulaBindingIR / SummonMonsterIntentIR dynamic binding candidates",
            ir_items=_dynamic_custom_items(ir),
            rules=rules,
            rulebook_query_surface="RuleBook.ability_task / skill_formula_binding / summon_monster_intent where projected",
            projection_predicate="IR JSON contains dynamic/custom/hash/readinfo tokens",
            notes="This is structured field discovery, not a claim that every dynamic/custom hash is admitted.",
            future_owner="P4-S3 dynamic/custom value binding",
        )
    )
    add(
        _source_family_row(
            "dynamic_avatar_skilltree_param_fields",
            raw_source_kind="json_field_group",
            raw_path_or_field="ExcelOutput/AvatarSkillTreeConfig.json:SkillTreeParam/ParamList/StatusAddList",
            raw_count=_json_any_field_count(excel / "AvatarSkillTreeConfig.json", ("SkillTreeParam", "ParamList", "StatusAddList")),
            raw_source_samples=_json_any_field_samples(tbgd_root, excel / "AvatarSkillTreeConfig.json", ("SkillTreeParam", "ParamList", "StatusAddList")),
            ir_container="CharacterTraceNodeIR / CharacterMechanismSlotIR",
            ir_items=_items_by_source((*ir.character_trace_nodes, *ir.character_mechanism_slots), raw_types=("AvatarSkillTreeConfig",)),
            rules=rules,
            rulebook_query_surface="RuleBook.character_trace_node / character_mechanism_slot",
            projection_predicate="trace/mechanism slots sourced from AvatarSkillTreeConfig",
            notes="Skill tree params feed trace/mechanism slots and remain blocked until admitted by character stages.",
            future_owner="P4-S8 trace/resource/dynamic admission",
        )
    )
    add(
        _source_family_row(
            "dynamic_monster_custom_value_fields",
            raw_source_kind="json_field_group",
            raw_path_or_field="ExcelOutput/MonsterConfig.json:CustomValues/DynamicValues/OverrideSkillParams",
            raw_count=_json_any_field_count(excel / "MonsterConfig.json", ("CustomValues", "DynamicValues", "OverrideSkillParams")),
            raw_source_samples=_json_any_field_samples(tbgd_root, excel / "MonsterConfig.json", ("CustomValues", "DynamicValues", "OverrideSkillParams")),
            ir_container="MonsterDataCardIR.raw_parameter_blocks / SummonMonsterIntentIR",
            ir_items=(
                *tuple(card for card in ir.monster_data_cards if card.raw_parameter_blocks),
                *tuple(ir.summon_monster_intents),
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.monster_data_card / summon_monster_intent",
            projection_predicate="monster cards with raw_parameter_blocks plus summon intents",
            notes="Monster custom/dynamic values are a common binding problem, not summon-specific hardcode.",
            future_owner="P4-S3/P4-S10 dynamic monster/custom value admission",
        )
    )
    add(
        _source_family_row(
            "dynamic_modifier_hash_fields",
            raw_source_kind="recursive_json_field_occurrence",
            raw_path_or_field="Config/ConfigGlobalModifier/**/*.json:Dynamic/Custom/Hash/ReadInfo fields",
            raw_count=_json_tree_key_count(config_global_modifier, ("DynamicValues", "ReadInfo", "CustomValue", "CustomValues", "Hash", "HashValue")),
            raw_source_samples=_json_tree_key_samples(tbgd_root, config_global_modifier, ("DynamicValues", "ReadInfo", "CustomValue", "CustomValues", "Hash", "HashValue")),
            ir_container="StatusCallbackIR / StatusCallbackTaskIR / modifier listener candidates",
            ir_items=_items_by_source(passive_items, path_contains=("Config/ConfigGlobalModifier",)),
            rules=rules,
            rulebook_query_surface="RuleBook status/queue callback accessors",
            projection_predicate="listener IR source path contains Config/ConfigGlobalModifier",
            notes="Modifier dynamic hashes require common dynamic binding admission.",
            future_owner="P4-S3/P4-S6 dynamic/listener admission",
        )
    )

    add(
        _source_family_row(
            "target_battle_target_config",
            raw_source_kind="stage_objective_table",
            raw_path_or_field="ExcelOutput/BattleTargetConfig.json",
            raw_count=raw["BattleTargetConfig"],
            raw_source_samples=raw_samples["BattleTargetConfig"],
            ir_container="stage/environment objective layer",
            ir_items=(),
            rules=rules,
            rulebook_query_surface="not exposed as P4 action target query",
            projection_predicate="BattleTargetConfig rows describe battle objectives, not action target resolution.",
            blocked_boundary_samples=_hook_boundary_samples(
                "stage_environment_objective_boundary",
                "BattleTargetConfig belongs to the later stage/environment objective layer.",
                "P4 action target query must not treat battle-objective rows as TargetExpressionIR fallback.",
            ),
            notes="BattleTargetConfig raw rows are challenge/score objectives and are kept out of P4 action target admission.",
            future_owner="stage/environment objective layer",
            forced_classification="out_of_scope",
        )
    )
    add(
        _target_row("target_alias_config_alias_dict", "Config/GlobalConfig/TargetAliasConfig.json:AliasDict", _json_nested_dict_count(global_config / "TargetAliasConfig.json", "AliasDict"), _json_nested_dict_samples(tbgd_root, global_config / "TargetAliasConfig.json", "AliasDict"), _items_by_source(ir.target_expressions, raw_types=("TargetAliasConfig.AliasDict", "TargetAliasOperationChain")), rules, "Target alias dictionary entries")
    )
    add(
        _target_row("target_operation_config_operation_dict", "Config/GlobalConfig/TargetOperationConfig.json:OperationDict", _json_nested_dict_count(global_config / "TargetOperationConfig.json", "OperationDict"), _json_nested_dict_samples(tbgd_root, global_config / "TargetOperationConfig.json", "OperationDict"), _items_by_source(ir.target_expressions, raw_types=("TargetAliasOperationChain",)), rules, "Target operation dictionary entries")
    )
    add(
        _source_family_row(
            "target_ability_payloads",
            raw_source_kind="recursive_json_field_occurrence",
            raw_path_or_field="Config/ConfigAbility/**/*.json:*Target* fields",
            raw_count=_json_tree_key_contains_count(config_ability, ("target",)),
            raw_source_samples=_json_tree_key_contains_samples(tbgd_root, config_ability, ("target",)),
            ir_container="TargetExpressionIR / AbilityTaskIR target payload evidence",
            ir_items=tuple(
                item
                for item in (*ir.target_expressions, *ir.ability_tasks)
                if "target" in json.dumps(_to_json(item), ensure_ascii=False, sort_keys=True).lower()
            ),
            rules=rules,
            rulebook_query_surface="RuleBook.target_expression / ability_task",
            projection_predicate="IR JSON contains target payload markers",
            blocked_boundary_samples=_hook_boundary_samples(
                "target_query_boundary",
                "Target query belongs to ActionDefinitionIR / TargetExpressionIR.",
                "missing alias, operation, fetch key, sort rule, filter, retarget, owner, caster, or payload blocks resolution with no fallback.",
            ),
            notes="Ability target payloads are inventoried separately from global target registry.",
            future_owner="P4-S4 target admission",
        )
    )

    add(
        _hook_row(
            "equipment_light_cone_build_hook",
            "ExcelOutput/EquipmentConfig.json + EquipmentSkillConfig.json",
            _sum_raw(raw, "EquipmentConfig", "EquipmentSkillConfig"),
            _samples_for_keys(raw_samples, "EquipmentConfig", "EquipmentSkillConfig"),
            rules,
            "future character build/equipment assembly",
            "light cone/equipment sources are reserved build inputs; no P4 runtime mutation is admitted",
        )
    )
    add(
        _hook_row(
            "relic_set_build_hook",
            "ExcelOutput/RelicSetConfig.json + RelicSetSkillConfig.json",
            _sum_raw(raw, "RelicSetConfig", "RelicSetSkillConfig"),
            _samples_for_keys(raw_samples, "RelicSetConfig", "RelicSetSkillConfig"),
            rules,
            "future character build/equipment assembly",
            "relic/set sources are reserved build inputs; no P4 runtime mutation is admitted",
        )
    )
    add(
        _hook_row(
            "monster_stage_override_hook",
            "StageConfig/StageConfigData/BattleEventData monster override inputs",
            _sum_raw(raw, "StageConfig", "StageConfigData", "BattleEventData", "BattleEventDataLD"),
            _samples_for_keys(raw_samples, "StageConfig", "StageConfigData", "BattleEventData", "BattleEventDataLD"),
            rules,
            "future stage/environment and monster override assembly",
            "stage/level/template overrides cannot be filled by UI/planner or monster card defaults",
        )
    )
    add(
        _source_family_row(
            "stage_environment_sources",
            raw_source_kind="json_table_and_config_file_tree",
            raw_path_or_field="StageConfig/StageConfigData/BattleEventData + ConfigAbility/Level,BattleEvent",
            raw_count=_sum_raw(raw, "StageConfig", "StageConfigData", "BattleEventData", "BattleEventDataLD") + raw["ConfigAbility.Level"] + raw["ConfigAbility.BattleEvent"],
            raw_source_samples=_samples_for_keys(raw_samples, "StageConfig", "StageConfigData", "BattleEventData", "BattleEventDataLD", "ConfigAbility.Level", "ConfigAbility.BattleEvent"),
            ir_container="future Stage/Environment layer",
            ir_items=(),
            rules=rules,
            rulebook_query_surface="none in P4; must not be disguised as character/monster runtime",
            projection_predicate="explicit P4 out_of_scope boundary",
            forced_classification="out_of_scope",
            blocked_boundary_samples=_hook_boundary_samples(
                "stage_environment_boundary",
                "Stage/environment/combat event rules belong to a future independent layer.",
                "P4 data cards cannot execute stage/environment effects without that layer; state remains unchanged from these rows.",
            ),
            notes="Stage/environment/combat event rules are outside P4 full implementation.",
            future_owner="future stage/environment layer",
        )
    )
    add(
        _source_family_row(
            "assistant_avatar_sources",
            raw_source_kind="config_file_tree",
            raw_path_or_field="Config/ConfigAbility/Avatar/Assistant/**/*.json",
            raw_count=raw["ConfigAbility.Avatar.Assistant"],
            raw_source_samples=raw_samples["ConfigAbility.Avatar.Assistant"],
            ir_container="AssistantAbilityResolutionIR",
            ir_items=ir.assistant_ability_resolutions,
            rules=rules,
            rulebook_query_surface="RuleBook.assistant_ability_resolution / assistant_ability_resolutions",
            projection_predicate="assistant ability resolution IR",
            forced_classification="out_of_scope",
            blocked_boundary_samples=_hook_boundary_samples(
                "assistant_avatar_boundary",
                "AssistantAvatar / TurnInsertAssistantAbility is independent from P4 character/monster data cards.",
                "P4 does not execute assistant ability queue entries as servant/summoned monster/card mechanisms.",
            ),
            notes="AssistantAvatar remains out of P4 unless a later phase explicitly scopes it.",
            future_owner="future AssistantAvatar phase",
        )
    )
    add(
        _source_family_row(
            "client_visual_config_exclusion",
            raw_source_kind="config_file_tree",
            raw_path_or_field="Config/ConfigAnimZone, Config/Sound, Config/UIAdaption",
            raw_count=_file_count(config / "ConfigAnimZone") + _file_count(config / "Sound") + _file_count(config / "UIAdaption"),
            raw_source_samples=[*_file_tree_samples(tbgd_root, config / "ConfigAnimZone"), *_file_tree_samples(tbgd_root, config / "Sound"), *_file_tree_samples(tbgd_root, config / "UIAdaption")][:MAX_SOURCE_SAMPLES],
            ir_container="none",
            ir_items=(),
            rules=rules,
            rulebook_query_surface="none; visual/client-only configs cannot provide rule facts",
            projection_predicate="explicit client/visual exclusion",
            forced_classification="out_of_scope",
            blocked_boundary_samples=_hook_boundary_samples(
                "client_visual_exclusion",
                "Client, animation, audio, and UI config are not rule sources.",
                "These sources cannot create actions, targets, status, damage, or mutations.",
            ),
            notes="Pure client/visual sources are recorded so they are not silently mistaken for missing combat sources.",
            future_owner="UI/client display only",
        )
    )
    add(
        _source_family_row(
            "ui_only_sources",
            raw_source_kind="workspace_ui_layer",
            raw_path_or_field="simulator_v8_ui",
            raw_count=0,
            raw_source_samples=[],
            ir_container="none",
            ir_items=(),
            rules=rules,
            rulebook_query_surface="none; UI consumes core facts only",
            projection_predicate="explicit UI-only boundary",
            forced_classification="out_of_scope",
            blocked_boundary_samples=_hook_boundary_samples(
                "ui_only_boundary",
                "UI can display readiness and audit facts only.",
                "UI-only rows cannot create rule facts, actions, targets, or mutations.",
            ),
            notes="UI-only display remains outside rule source inventory.",
            future_owner="simulator_v8_ui presentation layer",
        )
    )
    add(_p3_source_family_row("p3_summon_target_backlog", _summon_target_backlog_row(ir, rules), "P4-S4/P4-S10 target admission"))
    add(_p3_source_family_row("p3_summoned_monster_intent_backlog", _summoned_monster_intent_backlog_row(ir, rules), "P4-S3/P4-S10 dynamic/custom monster intent admission"))

    return rows


def _source_family_row(
    source_family: str,
    *,
    raw_source_kind: str,
    raw_path_or_field: str,
    raw_count: int,
    raw_source_samples: Iterable[dict[str, JSONValue]],
    ir_container: str,
    ir_items: Iterable[Any],
    rules: RuleBook,
    rulebook_query_surface: str,
    projection_predicate: str,
    notes: str,
    future_owner: str,
    forced_classification: str = "",
    blocked_boundary_samples: Iterable[dict[str, JSONValue]] = (),
) -> dict[str, JSONValue]:
    items = tuple(ir_items)
    status_counts = Counter(_coverage_status(item) for item in items)
    executable_count = int(status_counts.get("executable", 0))
    rulebook_visible_count = _rulebook_visible_count(items, rules)
    rulebook_gap_count = max(len(items) - rulebook_visible_count, 0)
    non_executable_count = max(len(items) - executable_count, 0)
    classification = forced_classification or _source_family_classification(
        raw_count=raw_count,
        ir_count=len(items),
        executable_count=executable_count,
        non_executable_count=non_executable_count,
        rulebook_gap_count=rulebook_gap_count,
    )
    blocked_or_gap_count = _blocked_or_gap_count(
        classification,
        raw_count=raw_count,
        ir_count=len(items),
        non_executable_count=non_executable_count,
        rulebook_gap_count=rulebook_gap_count,
    )
    gap_attribution = _source_family_gap_attribution(
        classification,
        raw_count=raw_count,
        ir_count=len(items),
        non_executable_count=non_executable_count,
        rulebook_gap_count=rulebook_gap_count,
    )
    boundary_samples = [
        *_limit_samples(blocked_boundary_samples),
        *_blocked_item_samples(items),
    ][:MAX_SOURCE_SAMPLES]
    if classification in GAP_STATES and blocked_or_gap_count > 0 and not boundary_samples:
        boundary_samples = [
            {
                "item_id": source_family,
                "coverage_status": classification,
                "blocked_reason": (
                    f"{source_family} has {classification}; see raw_path_or_field and projection_predicate"
                ),
                "source_trace": _limit_samples(raw_source_samples)[:1],
                "expected_behavior": "blocked_or_process_only_no_rule_mutation_until_admitted",
            }
        ]
    return {
        "source_family": source_family,
        "source_domain": source_family,
        "raw_source_kind": raw_source_kind,
        "raw_path_or_field": raw_path_or_field,
        "raw_count": int(raw_count),
        "raw_source_samples": _limit_samples(raw_source_samples),
        "ir_container": ir_container,
        "ir_count": len(items),
        "rulebook_query_surface": rulebook_query_surface,
        "rulebook_visible_count": rulebook_visible_count,
        "projection_predicate": projection_predicate,
        "classification": classification if classification in CLASSIFICATION_STATES else "unclassified",
        "executable_count": executable_count,
        "blocked_or_gap_count": blocked_or_gap_count,
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "gap_attribution": gap_attribution,
        "sample_source_trace": _source_trace(_first(items)),
        "blocked_boundary_samples": boundary_samples,
        "notes": notes,
        "future_owner": future_owner,
        "source_origin": "p4_s0_source_family_inventory",
        "raw_ir_mismatch_attribution": _raw_ir_mismatch_attribution(raw_count, len(items), classification),
    }


def _formula_row(
    source_family: str,
    raw_path_or_field: str,
    path: Path,
    field_name: str,
    ir_items: Iterable[Any],
    rules: RuleBook,
    raw_source_samples: Iterable[dict[str, JSONValue]],
    notes: str,
    future_owner: str = "P4-S3 formula/dynamic binding admission",
    forced_classification: str = "",
) -> dict[str, JSONValue]:
    return _source_family_row(
        source_family,
        raw_source_kind="json_field",
        raw_path_or_field=raw_path_or_field,
        raw_count=_json_field_count(path, field_name),
        raw_source_samples=raw_source_samples,
        ir_container="SkillFormulaBindingIR / DamageEmissionIR / ToughnessEmissionIR",
        ir_items=ir_items,
        rules=rules,
        rulebook_query_surface="RuleBook.skill_formula_binding / damage_emission / toughness_emission",
        projection_predicate=f"formula-related IR source points at {path.name}",
        notes=notes,
        future_owner=future_owner,
        forced_classification=forced_classification,
    )


def _target_row(
    source_family: str,
    raw_path_or_field: str,
    raw_count: int,
    raw_source_samples: Iterable[dict[str, JSONValue]],
    ir_items: Iterable[Any],
    rules: RuleBook,
    notes: str,
) -> dict[str, JSONValue]:
    return _source_family_row(
        source_family,
        raw_source_kind="target_registry_or_table",
        raw_path_or_field=raw_path_or_field,
        raw_count=raw_count,
        raw_source_samples=raw_source_samples,
        ir_container="TargetExpressionIR",
        ir_items=ir_items,
        rules=rules,
        rulebook_query_surface="RuleBook.target_expression / target_expressions",
        projection_predicate="TargetExpressionIR source matches registry/table source",
        blocked_boundary_samples=_hook_boundary_samples(
            "target_query_boundary",
            "Target query belongs to ActionDefinitionIR / TargetExpressionIR.",
            "missing alias, operation, fetch key, sort rule, filter, retarget, owner, caster, or payload blocks resolution with no fallback.",
        ),
        notes=notes,
        future_owner="P4-S4 target admission",
    )


def _hook_row(
    source_family: str,
    raw_path_or_field: str,
    raw_count: int,
    raw_source_samples: Iterable[dict[str, JSONValue]],
    rules: RuleBook,
    future_owner: str,
    blocked_reason: str,
) -> dict[str, JSONValue]:
    return _source_family_row(
        source_family,
        raw_source_kind="future_hook_source",
        raw_path_or_field=raw_path_or_field,
        raw_count=raw_count,
        raw_source_samples=raw_source_samples,
        ir_container="future hook only",
        ir_items=(),
        rules=rules,
        rulebook_query_surface="none in P4 runtime; hook is boundary-only",
        projection_predicate="explicit P4 future hook boundary",
        forced_classification="boundary_only",
        blocked_boundary_samples=_hook_boundary_samples(
            source_family,
            future_owner,
            blocked_reason,
        ),
        notes=blocked_reason,
        future_owner=future_owner,
    )


def _p3_source_family_row(source_family: str, p3_row: dict[str, Any], future_owner: str) -> dict[str, JSONValue]:
    gap_attribution = dict(p3_row.get("gap_attribution") or {})
    classification = _classification_from_p3_row(str(p3_row.get("classification") or "unclassified"), gap_attribution)
    blocked_or_gap_count = int(
        p3_row.get("blocked_count")
        or p3_row.get("gap_count")
        or sum(int(value or 0) for value in gap_attribution.values())
    )
    return {
        "source_family": source_family,
        "source_domain": source_family,
        "raw_source_kind": "p3_inherited_ir_backlog",
        "raw_path_or_field": "current CanonicalIR inherited from P3 backlog",
        "raw_count": int(p3_row.get("raw_count") or 0),
        "raw_source_samples": [],
        "ir_container": "TargetExpressionIR" if "target" in source_family else "SummonMonsterIntentIR",
        "ir_count": int(p3_row.get("ir_count") or 0),
        "rulebook_query_surface": "RuleBook.target_expression" if "target" in source_family else "RuleBook.summon_monster_intent",
        "rulebook_visible_count": int(p3_row.get("rulebook_visible_count") or p3_row.get("ir_count") or 0),
        "projection_predicate": "P3 backlog projected from current IR; not recomputed by P3 aggregate",
        "classification": classification if classification in CLASSIFICATION_STATES else "unclassified",
        "executable_count": int(p3_row.get("executable_count") or 0),
        "blocked_or_gap_count": blocked_or_gap_count,
        "coverage_status_counts": dict(p3_row.get("coverage_status_counts") or {}),
        "gap_attribution": gap_attribution,
        "gap_reason_token_counts": list(p3_row.get("gap_reason_token_counts") or []),
        "sample_source_trace": dict(p3_row.get("sample_source_trace") or {}),
        "blocked_boundary_samples": _p3_gap_boundary_samples(source_family, p3_row),
        "notes": "P3 inherited backlog is an explicit P4 input and cannot be hidden under wider executable rows.",
        "future_owner": future_owner,
        "source_origin": "p3_s0_inherited",
        "raw_ir_mismatch_attribution": "raw count is inherited from current IR projection rather than raw TBGD rescan",
    }


def _source_family_classification(
    *,
    raw_count: int,
    ir_count: int,
    executable_count: int,
    non_executable_count: int,
    rulebook_gap_count: int,
) -> str:
    if raw_count <= 0 and ir_count <= 0:
        return "source_absent_not_required"
    if raw_count > 0 and ir_count <= 0:
        return "lowering_gap"
    if rulebook_gap_count > 0:
        return "validation_gap"
    if ir_count > 0 and executable_count == ir_count:
        return "executable"
    if non_executable_count > 0:
        return "admission_gap"
    return "unclassified"


def _blocked_or_gap_count(
    classification: str,
    *,
    raw_count: int,
    ir_count: int,
    non_executable_count: int,
    rulebook_gap_count: int,
) -> int:
    if classification == "lowering_gap":
        return max(raw_count - ir_count, 1)
    if classification == "validation_gap":
        return max(rulebook_gap_count, 1)
    if classification in {"admission_gap", "source_gap_blocked", "implementation_missing"}:
        return max(non_executable_count, 1)
    return 0


def _source_family_gap_attribution(
    classification: str,
    *,
    raw_count: int,
    ir_count: int,
    non_executable_count: int,
    rulebook_gap_count: int,
) -> dict[str, int]:
    if classification == "lowering_gap":
        return {"lowering_gap": max(raw_count - ir_count, 1)}
    if classification == "validation_gap":
        return {"validation_gap": max(rulebook_gap_count, 1)}
    if classification in {"admission_gap", "source_gap_blocked", "implementation_missing"}:
        return {classification: max(non_executable_count, 1)}
    return {}


def _raw_ir_mismatch_attribution(raw_count: int, ir_count: int, classification: str) -> str:
    if raw_count == 0 and ir_count > 0:
        return "IR has projected rows but S0 raw scanner found no matching raw source; this must be explained before review."
    if raw_count > 0 and ir_count == 0:
        return f"raw source exists but no matching IR projection; classified as {classification}"
    return ""


def _action_graph_items(ir: CanonicalIR) -> tuple[Any, ...]:
    return (
        *ir.action_definitions,
        *ir.action_events,
        *ir.action_ability_bindings,
        *ir.ability_phases,
        *ir.ability_tasks,
        *ir.hit_profiles,
        *ir.damage_emissions,
        *ir.toughness_emissions,
        *ir.queue_intents,
        *ir.queue_windows,
    )


def _formula_items(ir: CanonicalIR) -> tuple[Any, ...]:
    return (
        *ir.skill_formula_bindings,
        *ir.damage_emissions,
        *ir.toughness_emissions,
        *ir.status_damage_emissions,
        *ir.damage_modifiers,
        *ir.action_delay_emissions,
    )


def _passive_listener_items(ir: CanonicalIR) -> tuple[Any, ...]:
    return (
        *ir.passive_mechanism_slots,
        *ir.status_callbacks,
        *ir.status_callback_tasks,
        *ir.status_damage_emissions,
        *ir.damage_modifiers,
        *ir.action_delay_emissions,
        *ir.queue_intents,
        *ir.queue_resolutions,
        *ir.queue_windows,
    )


def _items_by_source(
    items: Iterable[Any],
    *,
    raw_types: Iterable[str] = (),
    path_contains: Iterable[str] = (),
) -> tuple[Any, ...]:
    raw_type_set = {str(item) for item in raw_types}
    path_tokens = tuple(str(item) for item in path_contains)
    selected: list[Any] = []
    for item in items:
        source = getattr(item, "source", None)
        raw_type = str(getattr(source, "raw_type", "") or "")
        source_path = str(getattr(source, "source_path", "") or "")
        if raw_type_set and raw_type not in raw_type_set:
            continue
        if path_tokens and not any(token in source_path for token in path_tokens):
            continue
        selected.append(item)
    return tuple(selected)


def _items_by_source_tokens(
    items: Iterable[Any],
    *,
    raw_types: Iterable[str] = (),
    path_contains: Iterable[str] = (),
) -> tuple[Any, ...]:
    raw_type_tokens = tuple(str(item) for item in raw_types)
    path_tokens = tuple(str(item) for item in path_contains)
    selected: list[Any] = []
    for item in items:
        source = getattr(item, "source", None)
        source_json = _to_json(source) if source is not None else _to_json(item)
        blob = json.dumps(source_json, ensure_ascii=False, sort_keys=True)
        if raw_type_tokens and not any(token in blob for token in raw_type_tokens):
            continue
        if path_tokens and not any(token in blob for token in path_tokens):
            continue
        selected.append(item)
    return tuple(selected)


def _items_by_source_and_tokens(
    items: Iterable[Any],
    *,
    raw_types: Iterable[str] = (),
    path_contains: Iterable[str] = (),
    tokens: Iterable[str],
) -> tuple[Any, ...]:
    token_set = tuple(str(token).lower() for token in tokens)
    selected: list[Any] = []
    for item in _items_by_source(items, raw_types=raw_types, path_contains=path_contains):
        blob = json.dumps(_to_json(item), ensure_ascii=False, sort_keys=True).lower()
        if any(token in blob for token in token_set):
            selected.append(item)
    return tuple(selected)


def _rulebook_visible_count(items: Iterable[Any], rules: RuleBook) -> int:
    return sum(1 for item in items if _rulebook_visible(item, rules))


def _rulebook_visible(item: Any, rules: RuleBook) -> bool:
    kind = type(item).__name__
    if kind == "AvatarProfileIR":
        return bool(rules.avatar_profile(getattr(item, "avatar_id", "")))
    if kind == "CharacterDataCardIR":
        return bool(rules.character_data_card(getattr(item, "card_id", "")))
    if kind == "MonsterDataCardIR":
        return bool(rules.monster_data_card(getattr(item, "card_id", "")))
    if kind == "CombatantProfileIR":
        return bool(rules.combatant_profile(getattr(item, "entity_id", "")))
    if kind == "CombatantActionSetIR":
        return bool(rules.combatant_action_set(getattr(item, "entity_ref", "")))
    if kind == "ActionDefinitionIR":
        return bool(rules.action_definition(getattr(item, "action_id", ""), int(getattr(item, "level", 0) or 0)))
    if kind == "ActionEventIR":
        return bool(rules.action_event(getattr(item, "action_id", ""), int(getattr(item, "level", 0) or 0)))
    if kind == "ActionAbilityBindingIR":
        return bool(rules.action_ability_binding_by_id(getattr(item, "binding_id", "")))
    if kind == "AbilityPhaseIR":
        return bool(rules.ability_phase(getattr(item, "phase_id", "")))
    if kind == "AbilityTaskIR":
        return bool(rules.ability_task(getattr(item, "task_id", "")))
    if kind == "HitProfileIR":
        return bool(rules.hit_profile(getattr(item, "hit_profile_id", "")))
    if kind == "SkillFormulaBindingIR":
        return bool(rules.skill_formula_binding(getattr(item, "binding_id", "")))
    if kind == "CharacterMechanismSlotIR":
        return bool(rules.character_mechanism_slot(getattr(item, "mechanism_slot_id", "")))
    if kind == "CharacterTraceNodeIR":
        return bool(rules.character_trace_node(getattr(item, "trace_node_id", "")))
    if kind == "CharacterEidolonSlotIR":
        return bool(rules.character_eidolon_slot(getattr(item, "eidolon_slot_id", "")))
    if kind == "BouncePolicyIR":
        return bool(rules.bounce_policy(getattr(item, "bounce_policy_id", "")))
    if kind == "DamageEmissionIR":
        return bool(rules.damage_emission(getattr(item, "damage_emission_id", "")))
    if kind == "ToughnessEmissionIR":
        return bool(rules.toughness_emission(getattr(item, "toughness_emission_id", "")))
    if kind == "StatusDamageEmissionIR":
        return bool(rules.status_damage_emission(getattr(item, "status_damage_emission_id", "")))
    if kind == "DamageModifierIR":
        return bool(rules.damage_modifier(getattr(item, "damage_modifier_id", "")))
    if kind == "ActionDelayEmissionIR":
        return bool(rules.action_delay_emission(getattr(item, "action_delay_emission_id", "")))
    if kind == "PassiveMechanismSlotIR":
        return bool(rules.passive_mechanism_slot(getattr(item, "passive_slot_id", "")))
    if kind == "StatusCallbackIR":
        return bool(rules.status_callback(getattr(item, "callback_id", "")))
    if kind == "StatusCallbackTaskIR":
        return bool(rules.status_callback_task(getattr(item, "task_id", "")))
    if kind == "QueueIntentIR":
        return bool(rules.queue_intent(getattr(item, "queue_intent_id", "")))
    if kind == "QueueResolutionIR":
        return bool(rules.queue_resolution(getattr(item, "queue_resolution_id", "")))
    if kind == "QueueWindowIR":
        return bool(rules.queue_window(getattr(item, "queue_window_id", "")))
    if kind == "TriggerIR":
        return bool(rules.trigger(getattr(item, "trigger_id", "")))
    if kind == "TargetExpressionIR":
        return bool(rules.target_expression(getattr(item, "target_expression_id", "")))
    if kind == "ServantDefinitionIR":
        return bool(rules.servant_definition(getattr(item, "servant_definition_id", "")))
    if kind == "SummonMonsterIntentIR":
        return bool(rules.summon_monster_intent(getattr(item, "summon_intent_id", "")))
    if kind == "AssistantAbilityResolutionIR":
        return bool(rules.assistant_ability_resolution(getattr(item, "assistant_resolution_id", "")))
    if kind == "StandaloneAbilityGraphIR":
        return bool(rules.standalone_ability_graph(getattr(item, "standalone_ability_graph_id", "")))
    return False


def _card_has_sequence_kind(card: Any, sequence_kind: str) -> bool:
    for step in getattr(card, "action_sequence", ()) or ():
        if isinstance(step, dict) and step.get("sequence_kind") == sequence_kind:
            return True
    return False


def validate_p4_s0_combatant_source_inventory_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    domain_matrix = matrix.get("domain_matrix", {})
    required_domains = {
        "avatar_config_profile_cards",
        "avatar_config_ld_profile_cards",
        "avatar_config_enhanced_profile_cards",
        "avatar_promotion_config_profile_stats",
        "avatar_skill_config_actions",
        "avatar_technique_skill_sources",
        "avatar_enhanced_skill_effect_sources",
        "common_avatar_skill_config_actions",
        "avatar_skilltree_config_trace_slots",
        "avatar_skilltree_status_add_sources",
        "avatar_rank_config_eidolon_slots",
        "config_character_localplayer_sources",
        "config_ability_avatar_graphs",
        "avatar_servant_config_subcard_sources",
        "avatar_servant_skill_config_actions",
        "config_character_servant_sources",
        "config_ability_servant_graphs",
        "monster_config_base_cards",
        "monster_template_config_profiles",
        "monster_template_unique_config_overrides",
        "monster_config_skill_list_action_set",
        "monster_skill_config_actions",
        "monster_skill_unique_config_actions",
        "ilbattle_monster_skill_actions",
        "config_character_monster_sources",
        "config_ability_monster_graphs",
        "monster_config_override_ai_sequence",
        "monster_template_ai_sequence",
        "monster_config_ability_name_list_passives",
        "config_global_modifier_listener_sources",
        "monster_passive_start_enter_listener_sources",
        "monster_passive_wave_listener_sources",
        "monster_passive_death_listener_sources",
        "monster_passive_hit_attack_listener_sources",
        "monster_passive_phase_skill_trigger_sources",
        "monster_config_summon_id_list_refs",
        "avatar_skill_param_formula_sources",
        "monster_skill_param_formula_sources",
        "ilbattle_skill_param_formula_sources",
        "avatar_skill_resource_fields",
        "monster_skill_resource_fields",
        "dynamic_config_ability_fields",
        "dynamic_avatar_skilltree_param_fields",
        "dynamic_monster_custom_value_fields",
        "dynamic_modifier_hash_fields",
        "target_battle_target_config",
        "target_alias_config_alias_dict",
        "target_operation_config_operation_dict",
        "target_ability_payloads",
        "equipment_light_cone_build_hook",
        "relic_set_build_hook",
        "monster_stage_override_hook",
        "stage_environment_sources",
        "assistant_avatar_sources",
        "client_visual_config_exclusion",
        "ui_only_sources",
        "p3_summon_target_backlog",
        "p3_summoned_monster_intent_backlog",
    }
    old_broad_domains = {
        "character_base_config",
        "character_action_sources",
        "character_mechanism_sources",
        "servant_character_subcard_sources",
        "monster_base_config",
        "monster_skill_action_graph",
        "monster_passive_listener_sources",
        "combatant_action_set_sources",
        "formula_parameter_sources",
        "dynamic_custom_value_sources",
        "target_expression_sources",
        "summoned_monster_intent_backlog",
        "summon_target_backlog",
        "equipment_build_input_hook",
        "monster_template_stage_override_hook",
    }
    classifications = [str(row.get("classification") or "") for row in domain_matrix.values()]
    required_boundary_samples = {
        "equipment_light_cone_build_hook",
        "relic_set_build_hook",
        "avatar_servant_config_subcard_sources",
        "monster_config_summon_id_list_refs",
        "target_alias_config_alias_dict",
        "target_operation_config_operation_dict",
        "monster_stage_override_hook",
        "stage_environment_sources",
        "assistant_avatar_sources",
        "ui_only_sources",
    }
    rows_missing_required_columns = [
        key
        for key, row in domain_matrix.items()
        if not all(
            column in row
            for column in (
                "source_family",
                "raw_source_kind",
                "raw_path_or_field",
                "raw_count",
                "ir_container",
                "ir_count",
                "rulebook_query_surface",
                "rulebook_visible_count",
                "classification",
                "gap_attribution",
                "sample_source_trace",
            )
        )
    ]
    raw_ir_mismatch_rows = [
        key
        for key, row in domain_matrix.items()
        if int(row.get("raw_count") or 0) == 0
        and int(row.get("ir_count") or 0) > 0
        and not row.get("raw_ir_mismatch_attribution")
    ]
    missing_raw_sample_rows = [
        key
        for key, row in domain_matrix.items()
        if int(row.get("raw_count") or 0) > 0
        and not row.get("raw_source_samples")
        and row.get("source_origin") != "p3_s0_inherited"
    ]
    missing_ir_trace_rows = [
        key
        for key, row in domain_matrix.items()
        if int(row.get("ir_count") or 0) > 0 and not row.get("sample_source_trace")
    ]
    gap_rows_without_attribution = [
        key
        for key, row in domain_matrix.items()
        if row.get("classification") in GAP_STATES and not row.get("gap_attribution")
    ]
    gap_rows_without_boundary_sample = [
        key
        for key, row in domain_matrix.items()
        if row.get("classification") in GAP_STATES and int(row.get("blocked_or_gap_count") or 0) > 0 and not row.get("blocked_boundary_samples")
    ]
    checks = {
        "required_domains_present": required_domains.issubset(set(domain_matrix)),
        "old_broad_domain_rows_absent": not (set(domain_matrix) & old_broad_domains),
        "required_columns_present": not rows_missing_required_columns,
        "all_domains_classified": all(classification in CLASSIFICATION_STATES for classification in classifications),
        "unclassified_zero": matrix.get("unclassified_count") == 0,
        "character_and_monster_present": domain_matrix.get("avatar_config_profile_cards", {}).get("raw_count", 0) > 0
        and domain_matrix.get("monster_config_base_cards", {}).get("raw_count", 0) > 0,
        "rulebook_visibility_recorded": all("rulebook_visible_count" in row for row in domain_matrix.values()),
        "raw_source_samples_recorded": not missing_raw_sample_rows,
        "ir_source_traces_sampled_by_domain": not missing_ir_trace_rows,
        "raw_ir_mismatch_attributed": not raw_ir_mismatch_rows,
        "gap_rows_have_attribution": not gap_rows_without_attribution,
        "gap_rows_have_blocked_boundary_sample": not gap_rows_without_boundary_sample,
        "required_blocked_boundary_samples_present": all(
            domain_matrix.get(key, {}).get("blocked_boundary_samples") for key in required_boundary_samples
        ),
        "p3_backlog_projected": domain_matrix.get("p3_summoned_monster_intent_backlog", {}).get("source_origin") == "p3_s0_inherited"
        and domain_matrix.get("p3_summon_target_backlog", {}).get("source_origin") == "p3_s0_inherited",
        "future_hooks_recorded": domain_matrix.get("equipment_light_cone_build_hook", {}).get("classification") == "boundary_only"
        and domain_matrix.get("relic_set_build_hook", {}).get("classification") == "boundary_only"
        and domain_matrix.get("stage_environment_sources", {}).get("classification") == "out_of_scope",
        "no_large_artifacts": matrix.get("resource_budget", {}).get("large_artifacts_written") is False
        and matrix.get("resource_budget", {}).get("full_ir_written") is False
        and matrix.get("resource_budget", {}).get("full_transition_dump_written") is False,
    }
    diagnostics = {
        "raw_ir_mismatch_rows": raw_ir_mismatch_rows,
        "missing_raw_sample_rows": missing_raw_sample_rows,
        "missing_ir_trace_rows": missing_ir_trace_rows,
        "gap_rows_without_attribution": gap_rows_without_attribution,
        "gap_rows_without_boundary_sample": gap_rows_without_boundary_sample,
        "rows_missing_required_columns": rows_missing_required_columns,
        "old_broad_domain_rows_present": sorted(set(domain_matrix) & old_broad_domains),
        "missing_required_domains": sorted(required_domains - set(domain_matrix)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks, "diagnostics": diagnostics}


def _raw_inventory(tbgd_root: Path) -> dict[str, int]:
    excel = tbgd_root / "ExcelOutput"
    config_character = tbgd_root / "Config" / "ConfigCharacter"
    config_ability = tbgd_root / "Config" / "ConfigAbility"
    config_global_modifier = tbgd_root / "Config" / "ConfigGlobalModifier"
    global_config = tbgd_root / "Config" / "GlobalConfig"
    dynamic_config_scan = _token_file_inventory(
        (config_ability, excel),
        tbgd_root,
        ("dynamic", "customvalue", "custom_value", "readinfo", "hash"),
    )
    passive_listener_monster_scan = _token_file_inventory(
        (config_ability / "Monster",),
        tbgd_root,
        ("onstart", "onenterbattle", "onwave", "ondeath", "onhit", "modifier", "trigger", "abilitynamelist"),
    )
    passive_listener_global_scan = _token_file_inventory(
        (config_global_modifier,),
        tbgd_root,
        ("onstart", "onenterbattle", "onwave", "ondeath", "onhit", "modifier", "trigger"),
    )
    target_config_scan = _token_file_inventory(
        (config_ability, global_config),
        tbgd_root,
        ("target", "targetalias", "targetoperation", "fetch", "sort", "retarget"),
    )
    raw = {
        "AvatarConfig": _json_count(excel / "AvatarConfig.json"),
        "AvatarConfigLD": _json_count(excel / "AvatarConfigLD.json"),
        "AvatarConfigEnhanced": _json_count(excel / "AvatarConfigEnhanced.json"),
        "AvatarPromotionConfig": _json_count(excel / "AvatarPromotionConfig.json"),
        "AvatarSkillConfig": _json_count(excel / "AvatarSkillConfig.json"),
        "CommonAvatarSkillConfig": _json_count(excel / "CommonAvatarSkillConfig.json"),
        "AvatarSkillTreeConfig": _json_count(excel / "AvatarSkillTreeConfig.json"),
        "AvatarRankConfig": _json_count(excel / "AvatarRankConfig.json"),
        "AvatarServantConfig": _json_count(excel / "AvatarServantConfig.json"),
        "AvatarServantSkillConfig": _json_count(excel / "AvatarServantSkillConfig.json"),
        "MonsterConfig": _json_count(excel / "MonsterConfig.json"),
        "MonsterTemplateConfig": _json_count(excel / "MonsterTemplateConfig.json"),
        "MonsterTemplateUniqueConfig": _json_count(excel / "MonsterTemplateUniqueConfig.json"),
        "MonsterSkillConfig": _json_count(excel / "MonsterSkillConfig.json"),
        "MonsterSkillUniqueConfig": _json_count(excel / "MonsterSkillUniqueConfig.json"),
        "ILBattleMonsterSkill": _json_count(excel / "ILBattleMonsterSkill.json"),
        "EquipmentConfig": _json_count(excel / "EquipmentConfig.json"),
        "EquipmentSkillConfig": _json_count(excel / "EquipmentSkillConfig.json"),
        "RelicSetConfig": _json_count(excel / "RelicSetConfig.json"),
        "RelicSetSkillConfig": _json_count(excel / "RelicSetSkillConfig.json"),
        "StageConfig": _json_count(excel / "StageConfig.json"),
        "StageConfigData": _json_count(excel / "StageConfigData.json"),
        "BattleEventData": _json_count(excel / "BattleEventData.json"),
        "BattleEventDataLD": _json_count(excel / "BattleEventDataLD.json"),
        "BattleTargetConfig": _json_count(excel / "BattleTargetConfig.json"),
        "TargetAliasConfig": _json_count(global_config / "TargetAliasConfig.json"),
        "TargetOperationConfig": _json_count(global_config / "TargetOperationConfig.json"),
        "ConfigCharacter.LocalPlayer": _file_count(config_character / "LocalPlayer"),
        "ConfigCharacter.Monster": _file_count(config_character / "Monster"),
        "ConfigCharacter.Servant": _file_count(config_character / "Servant"),
        "ConfigAbility.Monster": _file_count(config_ability / "Monster"),
        "ConfigAbility.Servant": _file_count(config_ability / "Servant"),
        "ConfigAbility.Level": _file_count(config_ability / "Level"),
        "ConfigAbility.BattleEvent": _file_count(config_ability / "BattleEvent"),
        "ConfigAbility.Avatar.Assistant": _file_count(config_ability / "Avatar" / "Assistant"),
        "ConfigAbility.AvatarLike": _avatar_like_ability_file_count(config_ability),
        "ConfigGlobalModifier": _file_count(config_global_modifier),
        "ConfigAbility.dynamic_custom_file_match_count": dynamic_config_scan["Config/ConfigAbility"]["count"],
        "ExcelOutput.dynamic_custom_file_match_count": dynamic_config_scan["ExcelOutput"]["count"],
        "ConfigAbility.Monster.passive_listener_file_match_count": passive_listener_monster_scan["Config/ConfigAbility/Monster"]["count"],
        "ConfigGlobalModifier.passive_listener_file_match_count": passive_listener_global_scan["Config/ConfigGlobalModifier"]["count"],
        "ConfigAbility.target_file_match_count": target_config_scan["Config/ConfigAbility"]["count"]
        + target_config_scan["Config/GlobalConfig"]["count"],
        "monster_config_ability_name_list_count": 0,
        "monster_config_passive_like_skill_count": 0,
        "raw_token_scan_count": dynamic_config_scan["_scanned_file_count"]
        + passive_listener_monster_scan["_scanned_file_count"]
        + passive_listener_global_scan["_scanned_file_count"]
        + target_config_scan["_scanned_file_count"],
    }
    monster_rows = _load_json(excel / "MonsterConfig.json")
    for _raw_id, row in _iter_json_rows(monster_rows):
        if isinstance(row, dict):
            ability_names = row.get("AbilityNameList")
            if isinstance(ability_names, list) and ability_names:
                raw["monster_config_ability_name_list_count"] += 1
            skill_list = row.get("SkillList")
            if isinstance(skill_list, list) and any(_skill_ref_looks_passive(item) for item in skill_list):
                raw["monster_config_passive_like_skill_count"] += 1
    return raw


def _raw_source_samples(tbgd_root: Path) -> dict[str, list[dict[str, JSONValue]]]:
    excel = tbgd_root / "ExcelOutput"
    config_character = tbgd_root / "Config" / "ConfigCharacter"
    config_ability = tbgd_root / "Config" / "ConfigAbility"
    config_global_modifier = tbgd_root / "Config" / "ConfigGlobalModifier"
    global_config = tbgd_root / "Config" / "GlobalConfig"
    samples: dict[str, list[dict[str, JSONValue]]] = {
        "AvatarConfig": _json_table_samples(tbgd_root, excel / "AvatarConfig.json"),
        "AvatarConfigLD": _json_table_samples(tbgd_root, excel / "AvatarConfigLD.json"),
        "AvatarConfigEnhanced": _json_table_samples(tbgd_root, excel / "AvatarConfigEnhanced.json"),
        "AvatarPromotionConfig": _json_table_samples(tbgd_root, excel / "AvatarPromotionConfig.json"),
        "AvatarSkillConfig": _json_table_samples(tbgd_root, excel / "AvatarSkillConfig.json"),
        "CommonAvatarSkillConfig": _json_table_samples(tbgd_root, excel / "CommonAvatarSkillConfig.json"),
        "AvatarSkillTreeConfig": _json_table_samples(tbgd_root, excel / "AvatarSkillTreeConfig.json"),
        "AvatarRankConfig": _json_table_samples(tbgd_root, excel / "AvatarRankConfig.json"),
        "AvatarServantConfig": _json_table_samples(tbgd_root, excel / "AvatarServantConfig.json"),
        "AvatarServantSkillConfig": _json_table_samples(tbgd_root, excel / "AvatarServantSkillConfig.json"),
        "MonsterConfig": _json_table_samples(tbgd_root, excel / "MonsterConfig.json"),
        "MonsterTemplateConfig": _json_table_samples(tbgd_root, excel / "MonsterTemplateConfig.json"),
        "MonsterTemplateUniqueConfig": _json_table_samples(tbgd_root, excel / "MonsterTemplateUniqueConfig.json"),
        "MonsterSkillConfig": _json_table_samples(tbgd_root, excel / "MonsterSkillConfig.json"),
        "MonsterSkillUniqueConfig": _json_table_samples(tbgd_root, excel / "MonsterSkillUniqueConfig.json"),
        "ILBattleMonsterSkill": _json_table_samples(tbgd_root, excel / "ILBattleMonsterSkill.json"),
        "EquipmentConfig": _json_table_samples(tbgd_root, excel / "EquipmentConfig.json"),
        "EquipmentSkillConfig": _json_table_samples(tbgd_root, excel / "EquipmentSkillConfig.json"),
        "RelicSetConfig": _json_table_samples(tbgd_root, excel / "RelicSetConfig.json"),
        "RelicSetSkillConfig": _json_table_samples(tbgd_root, excel / "RelicSetSkillConfig.json"),
        "StageConfig": _json_table_samples(tbgd_root, excel / "StageConfig.json"),
        "StageConfigData": _json_table_samples(tbgd_root, excel / "StageConfigData.json"),
        "BattleEventData": _json_table_samples(tbgd_root, excel / "BattleEventData.json"),
        "BattleEventDataLD": _json_table_samples(tbgd_root, excel / "BattleEventDataLD.json"),
        "BattleTargetConfig": _json_table_samples(tbgd_root, excel / "BattleTargetConfig.json"),
        "TargetAliasConfig": _json_table_samples(tbgd_root, global_config / "TargetAliasConfig.json"),
        "TargetOperationConfig": _json_table_samples(tbgd_root, global_config / "TargetOperationConfig.json"),
        "ConfigCharacter.LocalPlayer": _file_tree_samples(tbgd_root, config_character / "LocalPlayer"),
        "ConfigCharacter.Monster": _file_tree_samples(tbgd_root, config_character / "Monster"),
        "ConfigCharacter.Servant": _file_tree_samples(tbgd_root, config_character / "Servant"),
        "ConfigAbility.Monster": _file_tree_samples(tbgd_root, config_ability / "Monster"),
        "ConfigAbility.Servant": _file_tree_samples(tbgd_root, config_ability / "Servant"),
        "ConfigAbility.Level": _file_tree_samples(tbgd_root, config_ability / "Level"),
        "ConfigAbility.BattleEvent": _file_tree_samples(tbgd_root, config_ability / "BattleEvent"),
        "ConfigAbility.Avatar.Assistant": _file_tree_samples(tbgd_root, config_ability / "Avatar" / "Assistant"),
        "ConfigAbility.AvatarLike": _avatar_like_ability_file_samples(tbgd_root, config_ability),
        "MonsterConfig.AbilityNameList": _monster_config_field_samples(tbgd_root, "AbilityNameList"),
        "MonsterConfig.PassiveLikeSkillList": _monster_config_passive_like_samples(tbgd_root),
    }
    dynamic_config_scan = _token_file_inventory(
        (config_ability, excel),
        tbgd_root,
        ("dynamic", "customvalue", "custom_value", "readinfo", "hash"),
    )
    passive_listener_monster_scan = _token_file_inventory(
        (config_ability / "Monster",),
        tbgd_root,
        ("onstart", "onenterbattle", "onwave", "ondeath", "onhit", "modifier", "trigger", "abilitynamelist"),
    )
    passive_listener_global_scan = _token_file_inventory(
        (config_global_modifier,),
        tbgd_root,
        ("onstart", "onenterbattle", "onwave", "ondeath", "onhit", "modifier", "trigger"),
    )
    target_config_scan = _token_file_inventory(
        (config_ability, global_config),
        tbgd_root,
        ("target", "targetalias", "targetoperation", "fetch", "sort", "retarget"),
    )
    samples["ConfigAbility.dynamic_custom"] = dynamic_config_scan["Config/ConfigAbility"]["samples"]
    samples["ExcelOutput.dynamic_custom"] = dynamic_config_scan["ExcelOutput"]["samples"]
    samples["ConfigAbility.Monster.passive_listener"] = passive_listener_monster_scan["Config/ConfigAbility/Monster"]["samples"]
    samples["ConfigGlobalModifier.passive_listener"] = passive_listener_global_scan["Config/ConfigGlobalModifier"]["samples"]
    samples["ConfigAbility.target"] = [
        *target_config_scan["Config/ConfigAbility"]["samples"],
        *target_config_scan["Config/GlobalConfig"]["samples"],
    ][:MAX_SOURCE_SAMPLES]
    return samples


def _json_table_samples(tbgd_root: Path, path: Path) -> list[dict[str, JSONValue]]:
    if not path.exists():
        return []
    count = _json_count(path)
    return [
        {
            "source_path": _relative_to_root(path, tbgd_root),
            "sample_kind": "json_table",
            "raw_type": path.stem,
            "row_count": count,
        }
    ]


def _file_tree_samples(tbgd_root: Path, path: Path) -> list[dict[str, JSONValue]]:
    if not path.exists():
        return []
    samples: list[dict[str, JSONValue]] = []
    for item in sorted(path.rglob("*.json")):
        if ".layout." in item.name:
            continue
        samples.append(
            {
                "source_path": _relative_to_root(item, tbgd_root),
                "sample_kind": "config_json_file",
                "raw_type": item.stem,
            }
        )
        if len(samples) >= MAX_SOURCE_SAMPLES:
            break
    return samples


def _avatar_like_ability_file_samples(tbgd_root: Path, config_ability: Path) -> list[dict[str, JSONValue]]:
    if not config_ability.exists():
        return []
    samples: list[dict[str, JSONValue]] = []
    for item in sorted(config_ability.rglob("*.json")):
        if ".layout." in item.name or not item.name.startswith("Avatar_"):
            continue
        samples.append(
            {
                "source_path": _relative_to_root(item, tbgd_root),
                "sample_kind": "avatar_like_ability_file",
                "raw_type": item.stem,
            }
        )
        if len(samples) >= MAX_SOURCE_SAMPLES:
            break
    return samples


def _monster_config_field_samples(tbgd_root: Path, field_name: str) -> list[dict[str, JSONValue]]:
    path = tbgd_root / "ExcelOutput" / "MonsterConfig.json"
    data = _load_json(path)
    rows = _iter_json_rows(data)
    if not rows:
        return []
    samples: list[dict[str, JSONValue]] = []
    for raw_id, row in sorted(rows, key=lambda item: str(item[0])):
        if not isinstance(row, dict):
            continue
        value = row.get(field_name)
        if isinstance(value, list) and value:
            samples.append(
                {
                    "source_path": _relative_to_root(path, tbgd_root),
                    "sample_kind": "json_table_field",
                    "raw_type": path.stem,
                    "raw_id": str(raw_id),
                    "field": field_name,
                }
            )
        if len(samples) >= MAX_SOURCE_SAMPLES:
            break
    return samples


def _monster_config_passive_like_samples(tbgd_root: Path) -> list[dict[str, JSONValue]]:
    path = tbgd_root / "ExcelOutput" / "MonsterConfig.json"
    data = _load_json(path)
    rows = _iter_json_rows(data)
    if not rows:
        return []
    samples: list[dict[str, JSONValue]] = []
    for raw_id, row in sorted(rows, key=lambda item: str(item[0])):
        if not isinstance(row, dict):
            continue
        skill_list = row.get("SkillList")
        if isinstance(skill_list, list) and any(_skill_ref_looks_passive(item) for item in skill_list):
            samples.append(
                {
                    "source_path": _relative_to_root(path, tbgd_root),
                    "sample_kind": "json_table_field",
                    "raw_type": path.stem,
                    "raw_id": str(raw_id),
                    "field": "SkillList",
                    "match": "passive_like_skill_ref",
                }
            )
        if len(samples) >= MAX_SOURCE_SAMPLES:
            break
    return samples


def _token_file_inventory(
    roots: Iterable[Path],
    tbgd_root: Path,
    tokens: Iterable[str],
) -> dict[str, Any]:
    token_set = tuple(str(token).lower() for token in tokens)
    result: dict[str, Any] = {"_scanned_file_count": 0}
    for root in roots:
        label = _relative_to_root(root, tbgd_root)
        count = 0
        samples: list[dict[str, JSONValue]] = []
        paths = (root,) if root.is_file() else sorted(root.rglob("*.json")) if root.exists() else ()
        for item in paths:
            if ".layout." in item.name or "TextMap" in item.as_posix():
                continue
            result["_scanned_file_count"] += 1
            try:
                text = item.read_text(encoding="utf-8")
            except Exception:
                continue
            lowered = text.lower()
            matched = [token for token in token_set if token in lowered]
            if not matched:
                continue
            count += 1
            if len(samples) < MAX_SOURCE_SAMPLES:
                samples.append(
                    {
                        "source_path": _relative_to_root(item, tbgd_root),
                        "sample_kind": "token_matched_json_file",
                        "matched_tokens": matched[:8],
                    }
                )
        result[label] = {"count": count, "samples": samples}
    return result


def _samples_for_keys(samples: dict[str, list[dict[str, JSONValue]]], *keys: str) -> list[dict[str, JSONValue]]:
    selected: list[dict[str, JSONValue]] = []
    for key in keys:
        selected.extend(samples.get(key, ()))
        if len(selected) >= MAX_SOURCE_SAMPLES:
            break
    return selected[:MAX_SOURCE_SAMPLES]


def _limit_samples(samples: Iterable[dict[str, JSONValue]]) -> list[dict[str, JSONValue]]:
    return [dict(sample) for sample in list(samples)[:MAX_SOURCE_SAMPLES]]


def _blocked_item_samples(items: Iterable[Any]) -> list[dict[str, JSONValue]]:
    samples: list[dict[str, JSONValue]] = []
    for item in items:
        status = _coverage_status(item)
        reason = str(getattr(item, "blocked_reason", "") or "")
        if status not in {"blocked", "audit_only", "discovered_only"} and not reason:
            continue
        sample = {
            "item_id": _item_identifier(item),
            "coverage_status": status,
            "blocked_reason": reason or "non_executable_or_audit_only_item",
            "source_trace": _source_trace(item),
            "expected_behavior": "blocked_or_process_only_no_rule_mutation_until_admitted",
        }
        samples.append(sample)
        if len(samples) >= MAX_SOURCE_SAMPLES:
            break
    return samples


def _hook_boundary_samples(hook: str, owner: str, blocked_reason: str) -> list[dict[str, JSONValue]]:
    return [
        {
            "hook": hook,
            "owner": owner,
            "blocked_reason": blocked_reason,
            "state_effect": "state_unchanged",
            "mutation_allowed": False,
            "transition_executed_in_s0": False,
        }
    ]


def _p3_gap_boundary_samples(source_domain: str, row: dict[str, Any]) -> list[dict[str, JSONValue]]:
    gap_attribution = dict(row.get("gap_attribution") or {})
    if not gap_attribution:
        return []
    return [
        {
            "hook": source_domain,
            "gap_attribution": gap_attribution,
            "blocked_reason": "inherited_p3_backlog_must_remain_blocked_until_p4_admission",
            "state_effect": "state_unchanged_for_unadmitted_entries",
            "mutation_allowed": False,
            "transition_executed_in_s0": False,
        }
    ]


def _item_identifier(item: Any) -> str:
    for attr in (
        "card_id",
        "profile_id",
        "combatant_action_set_id",
        "definition_id",
        "action_id",
        "binding_id",
        "phase_id",
        "task_id",
        "mechanism_slot_id",
        "passive_slot_id",
        "target_expression_id",
        "summon_intent_id",
        "servant_definition_id",
    ):
        value = getattr(item, attr, "")
        if value:
            return str(value)
    return type(item).__name__


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _domain_from_items(
    source_domain: str,
    *,
    raw_count: int,
    ir_items: Iterable[Any],
    rulebook_visible_count: int,
    raw_source_samples: Iterable[dict[str, JSONValue]] = (),
    blocked_boundary_samples: Iterable[dict[str, JSONValue]] = (),
    notes: str,
    future_owner: str,
) -> dict[str, JSONValue]:
    items = tuple(ir_items)
    status_counts = Counter(_coverage_status(item) for item in items)
    executable_count = int(status_counts.get("executable", 0))
    blocked_or_gap_count = len(items) - executable_count
    classification = _domain_classification(raw_count, len(items), status_counts)
    gap_attribution = _gap_attribution(classification, raw_count, len(items), blocked_or_gap_count, status_counts)
    boundary_samples = [
        *_limit_samples(blocked_boundary_samples),
        *_blocked_item_samples(items),
    ][:MAX_SOURCE_SAMPLES]
    return {
        "source_domain": source_domain,
        "classification": classification,
        "raw_count": int(raw_count),
        "ir_count": len(items),
        "rulebook_visible_count": int(rulebook_visible_count),
        "executable_count": executable_count,
        "blocked_or_gap_count": blocked_or_gap_count,
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "gap_attribution": gap_attribution,
        "raw_source_samples": _limit_samples(raw_source_samples),
        "sample_source_trace": _source_trace(_first(items)),
        "blocked_boundary_samples": boundary_samples,
        "notes": notes,
        "future_owner": future_owner,
        "source_origin": "p4_s0_inventory",
        "raw_ir_mismatch_attribution": ""
        if raw_count or not items
        else "raw scanner did not find this domain; S0 validation should fail unless this field is explicitly explained",
    }


def _p3_projection_row(
    source_domain: str,
    p3_row: dict[str, Any],
    *,
    notes: str,
    future_owner: str,
) -> dict[str, JSONValue]:
    gap_attribution = dict(p3_row.get("gap_attribution") or {})
    classification = _classification_from_p3_row(str(p3_row.get("classification") or "unclassified"), gap_attribution)
    return {
        "source_domain": source_domain,
        "classification": classification if classification in CLASSIFICATION_STATES else "unclassified",
        "raw_count": int(p3_row.get("raw_count") or 0),
        "ir_count": int(p3_row.get("ir_count") or 0),
        "rulebook_visible_count": int(p3_row.get("rulebook_visible_count") or p3_row.get("ir_count") or 0),
        "executable_count": int(p3_row.get("executable_count") or 0),
        "blocked_or_gap_count": int(p3_row.get("blocked_count") or p3_row.get("gap_count") or sum(int(v or 0) for v in gap_attribution.values())),
        "coverage_status_counts": dict(p3_row.get("coverage_status_counts") or {}),
        "gap_attribution": gap_attribution,
        "gap_reason_token_counts": list(p3_row.get("gap_reason_token_counts") or []),
        "sample_source_trace": dict(p3_row.get("sample_source_trace") or {}),
        "raw_source_samples": [],
        "blocked_boundary_samples": _p3_gap_boundary_samples(source_domain, p3_row),
        "notes": notes,
        "future_owner": future_owner,
        "source_origin": "p3_s0_inherited",
    }


def _summoned_monster_intent_backlog_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    intents = tuple(ir.summon_monster_intents)
    status_counts = Counter(_coverage_status(intent) for intent in intents)
    gap_attribution = _gap_attribution(
        _domain_classification(len(intents), len(intents), status_counts),
        len(intents),
        len(intents),
        len(intents) - int(status_counts.get("executable", 0)),
        status_counts,
    )
    return {
        "classification": _classification_from_p3_row(
            "executable" if status_counts.get("executable", 0) else "admission_gap",
            gap_attribution,
        ),
        "raw_count": len(intents),
        "ir_count": len(intents),
        "rulebook_visible_count": len(rules.summon_monster_intents()),
        "executable_count": int(status_counts.get("executable", 0)),
        "blocked_count": len(intents) - int(status_counts.get("executable", 0)),
        "gap_count": sum(int(value or 0) for value in gap_attribution.values()),
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "gap_attribution": gap_attribution,
        "sample_source_trace": _source_trace(_first(intents)),
    }


def _summon_target_backlog_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    expressions = tuple(
        expression
        for expression in ir.target_expressions
        if _target_expression_is_summon_related(expression)
    )
    status_counts = Counter(_coverage_status(expression) for expression in expressions)
    gap_attribution = _gap_attribution(
        _domain_classification(len(expressions), len(expressions), status_counts),
        len(expressions),
        len(expressions),
        len(expressions) - int(status_counts.get("executable", 0)),
        status_counts,
    )
    return {
        "classification": _classification_from_p3_row(
            "executable" if status_counts.get("executable", 0) else "admission_gap",
            gap_attribution,
        ),
        "raw_count": len(expressions),
        "ir_count": len(expressions),
        "rulebook_visible_count": sum(1 for expression in expressions if rules.target_expression(expression.target_expression_id)),
        "executable_count": int(status_counts.get("executable", 0)),
        "blocked_count": len(expressions) - int(status_counts.get("executable", 0)),
        "gap_count": sum(int(value or 0) for value in gap_attribution.values()),
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "gap_attribution": gap_attribution,
        "sample_source_trace": _source_trace(_first(expressions)),
    }


def _target_expression_is_summon_related(expression: Any) -> bool:
    blob = json.dumps(_to_json(expression), ensure_ascii=False, sort_keys=True).lower()
    return any(token in blob for token in ("summon", "servant", "owner", "casterservant", "friendservant"))


def _boundary_row(
    source_domain: str,
    *,
    raw_count: int,
    classification: str,
    notes: str,
    future_owner: str,
    raw_source_samples: Iterable[dict[str, JSONValue]] = (),
    sample_source_trace: dict[str, JSONValue] | None = None,
    blocked_boundary_samples: Iterable[dict[str, JSONValue]] = (),
    ir_count: int = 0,
    rulebook_visible_count: int = 0,
) -> dict[str, JSONValue]:
    return {
        "source_domain": source_domain,
        "classification": classification,
        "raw_count": int(raw_count),
        "ir_count": int(ir_count),
        "rulebook_visible_count": int(rulebook_visible_count),
        "executable_count": 0,
        "blocked_or_gap_count": 0,
        "coverage_status_counts": {},
        "gap_attribution": {},
        "raw_source_samples": _limit_samples(raw_source_samples),
        "sample_source_trace": dict(sample_source_trace or {}),
        "blocked_boundary_samples": _limit_samples(blocked_boundary_samples),
        "notes": notes,
        "future_owner": future_owner,
        "source_origin": "p4_s0_boundary",
        "raw_ir_mismatch_attribution": ""
        if raw_count or not ir_count
        else "boundary row has IR visibility without raw source sample",
    }


def _domain_classification(raw_count: int, ir_count: int, status_counts: Counter[str]) -> str:
    if ir_count == 0:
        return "source_absent_not_required" if raw_count == 0 else "lowering_gap"
    if status_counts.get("blocked", 0) > 0:
        return "admission_gap"
    if status_counts.get("audit_only", 0) > 0 or status_counts.get("discovered_only", 0) > 0:
        return "boundary_only"
    if status_counts.get("executable", 0) == ir_count:
        return "executable"
    if status_counts.get("executable", 0) > 0:
        return "admission_gap"
    return "unclassified"


def _classification_from_p3_row(default_classification: str, gap_attribution: dict[str, Any]) -> str:
    for gap_kind in ("implementation_missing", "lowering_gap", "validation_gap", "source_gap_blocked", "admission_gap"):
        if int(gap_attribution.get(gap_kind) or 0) > 0:
            return gap_kind
    return default_classification


def _gap_attribution(
    classification: str,
    raw_count: int,
    ir_count: int,
    blocked_or_gap_count: int,
    status_counts: Counter[str],
) -> dict[str, int]:
    if classification not in GAP_STATES:
        return {}
    if classification == "lowering_gap":
        return {"lowering_gap": max(raw_count - ir_count, 1)}
    if classification == "admission_gap":
        return {"admission_gap": max(blocked_or_gap_count, int(status_counts.get("blocked", 0)), 1)}
    return {classification: max(blocked_or_gap_count, 1)}


def _character_action_items(ir: CanonicalIR, rules: RuleBook) -> tuple[Any, ...]:
    character_refs = {card.entity_ref for card in ir.character_data_cards}
    action_refs: set[tuple[str, int]] = set()
    items: list[Any] = []
    for action_set in ir.combatant_action_sets:
        if action_set.entity_ref not in character_refs:
            continue
        items.append(action_set)
        for entry in action_set.skill_index_map.values():
            if isinstance(entry, dict):
                action_id = str(entry.get("action_ref") or "")
                level = int(entry.get("default_level") or entry.get("level") or 0)
                if action_id and level > 0:
                    action_refs.add((action_id, level))
    for action_id, level in sorted(action_refs):
        definition = rules.action_definition(action_id, level)
        event = rules.action_event(action_id, level)
        if definition is not None:
            items.append(definition)
        if event is not None:
            items.append(event)
    return tuple(items)


def _monster_action_items(ir: CanonicalIR) -> tuple[Any, ...]:
    items: list[Any] = []
    for item in (
        *ir.action_definitions,
        *ir.action_events,
        *ir.action_ability_bindings,
        *ir.ability_phases,
        *ir.ability_tasks,
        *ir.damage_emissions,
        *ir.toughness_emissions,
    ):
        source_path = getattr(getattr(item, "source", None), "source_path", "")
        source_mode = str(getattr(item, "source_mode", ""))
        action_id = str(getattr(item, "action_id", ""))
        if "/Monster/" in source_path or "MonsterSkill" in source_path or action_id.startswith(("monster_skill:", "ilbattle_monster_skill:")) or source_mode.startswith("monster"):
            items.append(item)
    return tuple(items)


def _monster_passive_items(ir: CanonicalIR) -> tuple[Any, ...]:
    items: list[Any] = []
    for item in (*ir.passive_mechanism_slots, *ir.status_callbacks, *ir.status_callback_tasks, *ir.queue_intents):
        source_path = getattr(getattr(item, "source", None), "source_path", "")
        owner = str(getattr(item, "owner_entity_ref", ""))
        data_kind = str(getattr(item, "data_card_kind", ""))
        if "/Monster/" in source_path or "Monster" in source_path or owner.startswith("monster:") or data_kind == "monster":
            items.append(item)
    return tuple(items)


def _dynamic_custom_items(ir: CanonicalIR) -> tuple[Any, ...]:
    items: list[Any] = []
    for item in (*ir.ability_tasks, *ir.skill_formula_bindings, *ir.summon_monster_intents):
        blob = json.dumps(_to_json(item), ensure_ascii=False, sort_keys=True).lower()
        if any(token in blob for token in ("dynamic", "customvalue", "custom_value", "readinfo", "hash")):
            items.append(item)
    return tuple(items)


def _coverage_status(item: Any) -> str:
    return str(getattr(item, "coverage_status", "") or "unclassified")


def _source_trace(item: Any | None) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    if source is None:
        return {}
    return source.to_json()


def _first(items: Iterable[Any]) -> Any | None:
    for item in items:
        return item
    return None


def _to_json(item: Any) -> Any:
    to_json = getattr(item, "to_json", None)
    return to_json() if callable(to_json) else item


def _sum_raw(raw: dict[str, int], *keys: str) -> int:
    return sum(int(raw.get(key) or 0) for key in keys)


def _json_field_count(path: Path, field_name: str) -> int:
    return _json_any_field_count(path, (field_name,))


def _json_field_samples(tbgd_root: Path, path: Path, field_name: str) -> list[dict[str, JSONValue]]:
    return _json_any_field_samples(tbgd_root, path, (field_name,))


def _json_any_field_count(path: Path, field_names: Iterable[str]) -> int:
    field_set = {str(field) for field in field_names}
    data = _load_json(path)
    rows = _iter_json_rows(data)
    count = 0
    for _raw_id, row in rows:
        if not isinstance(row, dict):
            continue
        if any(_field_has_value(row.get(field)) for field in field_set):
            count += 1
    return count


def _json_any_field_samples(
    tbgd_root: Path,
    path: Path,
    field_names: Iterable[str],
) -> list[dict[str, JSONValue]]:
    field_set = tuple(str(field) for field in field_names)
    data = _load_json(path)
    samples: list[dict[str, JSONValue]] = []
    for raw_id, row in _iter_json_rows(data):
        if not isinstance(row, dict):
            continue
        matched = [field for field in field_set if _field_has_value(row.get(field))]
        if not matched:
            continue
        samples.append(
            {
                "source_path": _relative_to_root(path, tbgd_root),
                "sample_kind": "json_table_field",
                "raw_type": path.stem,
                "raw_id": str(raw_id),
                "fields": matched,
            }
        )
        if len(samples) >= MAX_SOURCE_SAMPLES:
            break
    return samples


def _json_row_field_value_count(path: Path, field_values: dict[str, Iterable[str]]) -> int:
    expected = {field: {str(value) for value in values} for field, values in field_values.items()}
    data = _load_json(path)
    count = 0
    for _raw_id, row in _iter_json_rows(data):
        if not isinstance(row, dict):
            continue
        if any(str(row.get(field)) in values for field, values in expected.items()):
            count += 1
    return count


def _json_row_field_value_samples(
    tbgd_root: Path,
    path: Path,
    field_values: dict[str, Iterable[str]],
) -> list[dict[str, JSONValue]]:
    expected = {field: {str(value) for value in values} for field, values in field_values.items()}
    data = _load_json(path)
    samples: list[dict[str, JSONValue]] = []
    for raw_id, row in _iter_json_rows(data):
        if not isinstance(row, dict):
            continue
        matched = [
            {"field": field, "value": str(row.get(field))}
            for field, values in expected.items()
            if str(row.get(field)) in values
        ]
        if not matched:
            continue
        samples.append(
            {
                "source_path": _relative_to_root(path, tbgd_root),
                "sample_kind": "json_table_field_value",
                "raw_type": path.stem,
                "raw_id": str(raw_id),
                "matched": matched,
            }
        )
        if len(samples) >= MAX_SOURCE_SAMPLES:
            break
    return samples


def _json_nested_dict_count(path: Path, key: str) -> int:
    data = _load_json(path)
    if isinstance(data, dict):
        value = data.get(key)
        return len(value) if isinstance(value, dict) else 0
    return 0


def _json_nested_dict_samples(tbgd_root: Path, path: Path, key: str) -> list[dict[str, JSONValue]]:
    data = _load_json(path)
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, dict):
        return []
    samples: list[dict[str, JSONValue]] = []
    for item_key in sorted(value)[:MAX_SOURCE_SAMPLES]:
        samples.append(
            {
                "source_path": _relative_to_root(path, tbgd_root),
                "sample_kind": "json_nested_dict_entry",
                "raw_type": path.stem,
                "dict_key": key,
                "entry_key": str(item_key),
            }
        )
    return samples


def _json_tree_key_count(root: Path, key_names: Iterable[str]) -> int:
    key_set = {str(key) for key in key_names}
    count = 0
    for path in _iter_json_files(root):
        data = _load_json(path)
        count += _count_matching_keys(data, lambda key: key in key_set)
    return count


def _json_tree_key_samples(
    tbgd_root: Path,
    root: Path,
    key_names: Iterable[str],
) -> list[dict[str, JSONValue]]:
    key_set = {str(key) for key in key_names}
    return _json_tree_sample_matching_keys(tbgd_root, root, lambda key: key in key_set)


def _json_tree_key_contains_count(root: Path, tokens: Iterable[str]) -> int:
    token_set = tuple(str(token).lower() for token in tokens)
    count = 0
    for path in _iter_json_files(root):
        data = _load_json(path)
        count += _count_matching_keys(data, lambda key: any(token in key.lower() for token in token_set))
    return count


def _json_tree_key_contains_samples(
    tbgd_root: Path,
    root: Path,
    tokens: Iterable[str],
) -> list[dict[str, JSONValue]]:
    token_set = tuple(str(token).lower() for token in tokens)
    return _json_tree_sample_matching_keys(
        tbgd_root,
        root,
        lambda key: any(token in key.lower() for token in token_set),
    )


def _json_tree_field_value_token_count(root: Path, field_name: str, tokens: Iterable[str]) -> int:
    token_set = tuple(str(token).lower() for token in tokens)
    count = 0
    for path in _iter_json_files(root):
        data = _load_json(path)
        count += _count_matching_field_values(
            data,
            field_name,
            lambda value: any(token in str(value).lower() for token in token_set),
        )
    return count


def _json_tree_field_value_token_samples(
    tbgd_root: Path,
    root: Path,
    field_name: str,
    tokens: Iterable[str],
) -> list[dict[str, JSONValue]]:
    token_set = tuple(str(token).lower() for token in tokens)
    samples: list[dict[str, JSONValue]] = []
    for path in _iter_json_files(root):
        data = _load_json(path)
        for json_path, value in _iter_matching_field_value_paths(
            data,
            field_name,
            lambda item: any(token in str(item).lower() for token in token_set),
        ):
            samples.append(
                {
                    "source_path": _relative_to_root(path, tbgd_root),
                    "sample_kind": "recursive_json_field_value",
                    "json_path": json_path,
                    "field": field_name,
                    "value": str(value),
                    "matched_tokens": [token for token in token_set if token in str(value).lower()][:8],
                }
            )
            if len(samples) >= MAX_SOURCE_SAMPLES:
                return samples
    return samples


def _json_tree_sample_matching_keys(
    tbgd_root: Path,
    root: Path,
    predicate: Any,
) -> list[dict[str, JSONValue]]:
    samples: list[dict[str, JSONValue]] = []
    for path in _iter_json_files(root):
        data = _load_json(path)
        for json_path, key in _iter_matching_key_paths(data, predicate):
            samples.append(
                {
                    "source_path": _relative_to_root(path, tbgd_root),
                    "sample_kind": "recursive_json_key",
                    "json_path": json_path,
                    "field": key,
                }
            )
            if len(samples) >= MAX_SOURCE_SAMPLES:
                return samples
    return samples


def _iter_json_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        candidates = (root,)
    elif root.exists():
        candidates = sorted(root.rglob("*.json"))
    else:
        candidates = ()
    for path in candidates:
        if ".layout." in path.name or "TextMap" in path.as_posix():
            continue
        yield path


def _iter_json_rows(data: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(data, dict):
        return tuple((str(key), value) for key, value in data.items())
    if isinstance(data, list):
        return tuple((str(index), value) for index, value in enumerate(data))
    return ()


def _field_has_value(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, dict, tuple, set)) and not value:
        return False
    return True


def _count_matching_keys(data: Any, predicate: Any) -> int:
    count = 0
    if isinstance(data, dict):
        for key, value in data.items():
            if predicate(str(key)):
                count += 1
            count += _count_matching_keys(value, predicate)
    elif isinstance(data, list):
        for value in data:
            count += _count_matching_keys(value, predicate)
    return count


def _count_matching_field_values(data: Any, field_name: str, predicate: Any) -> int:
    count = 0
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key) == field_name and predicate(value):
                count += 1
            count += _count_matching_field_values(value, field_name, predicate)
    elif isinstance(data, list):
        for value in data:
            count += _count_matching_field_values(value, field_name, predicate)
    return count


def _iter_matching_key_paths(data: Any, predicate: Any, prefix: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}"
            if predicate(str(key)):
                yield path, str(key)
            yield from _iter_matching_key_paths(value, predicate, path)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            yield from _iter_matching_key_paths(value, predicate, f"{prefix}[{index}]")


def _iter_matching_field_value_paths(
    data: Any,
    field_name: str,
    predicate: Any,
    prefix: str = "$",
) -> Iterable[tuple[str, Any]]:
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}"
            if str(key) == field_name and predicate(value):
                yield path, value
            yield from _iter_matching_field_value_paths(value, field_name, predicate, path)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            yield from _iter_matching_field_value_paths(value, field_name, predicate, f"{prefix}[{index}]")


def _json_count(path: Path) -> int:
    data = _load_json(path)
    if isinstance(data, dict):
        return len(data)
    if isinstance(data, list):
        return len(data)
    return 1 if data is not None else 0


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _file_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*.json") if ".layout." not in item.name)


def _avatar_like_ability_file_count(config_ability: Path) -> int:
    if not config_ability.exists():
        return 0
    return sum(
        1
        for item in config_ability.rglob("*.json")
        if ".layout." not in item.name and item.name.startswith("Avatar_")
    )


def _skill_ref_looks_passive(value: Any) -> bool:
    if isinstance(value, dict):
        blob = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    else:
        blob = str(value).lower()
    return "passive" in blob


if __name__ == "__main__":
    raise SystemExit(main())
