from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

from .tbgd_loader import TBGDSource, unwrap_value, text_hash
from .content_compiler import ContentCompiler, _safe_int
from .ability_lowering import lower_node, summarize_ability_chain
from .core_rules import normalize_str_list


class ActionIRCompileError(RuntimeError):
    pass


ACTION_EFFECT_TYPES = {
    "add_status", "remove_status", "set_flag", "add_flag_value", "copy_flag",
    "set_flag_from_property", "set_flag_from_status_value", "modify_skill_points",
    "heal_unit", "modify_action_value", "enqueue_action", "summon_unit", "dispel_status",
    "modify_damage_data", "trigger_effect", "remove_effect", "include_task_template",
    "attach_effect_to_status", "owner_add_ability", "create_battle_event", "modify_versus_bar",
    "set_energy_bar_state", "change_phase", "set_status_dynamic_value", "stack_property",
    "set_flag_from_shield",
}

CONTROL_TYPES = {"conditional_branch"}
CONDITION_TYPES = {
    "all", "any", "not", "compare_dynamic_value", "has_status", "compare_status_value",
    "compare_hp_ratio", "target_team", "action_type", "eidolon_or_rank_active",
    "skill_point_activated", "is_insert_action", "is_current_skill_active", "compare_wave_count",
    "character_damage_type", "contains_behavior_flag", "modifier_callback_name", "compare_target",
    "compare_monster_phase", "custom_bool", "compare_battle_event_id", "compare_monster_id",
    "compare_character_id", "compare_monster_rank", "target_lists_intersect", "target_entity_type",
    "has_weakness", "compare_character_number", "team_location_index_type", "current_skill_name",
}


def _dedupe_damage_packets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove nested AttackData duplicates when a wrapping DamageByAttackProperty was lowered."""
    out: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, Any, Any, Any]] = set()
    for item in items:
        if item.get("source_node_type") == "RPG.GameCore.AttackData" and str(item.get("source_path", "")).endswith(".AttackProperty"):
            # The parent DamageByAttackProperty already carries target/can-kill metadata.
            continue
        key = (
            json.dumps(item.get("scaling"), sort_keys=True, ensure_ascii=False, default=str),
            item.get("target_policy"),
            item.get("damage_type"),
            item.get("source_path"),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(item)
    return out


def lowerings_to_action_ir(action: dict[str, Any]) -> dict[str, Any]:
    summary = action.get("ability_graph_summary") or {}
    lowered = list(summary.get("lowered_preview") or [])
    damage_packets: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    status_definition_hints: list[dict[str, Any]] = []
    control_flow: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    ability_refs: list[dict[str, Any]] = []
    unsupported: Counter[str] = Counter()
    for item in lowered:
        typ = item.get("type")
        source_path = str(item.get("source_path", ""))
        # Nodes under an ability's Modifiers/GlobalModifiers block are status
        # definitions, not effects that happen immediately when the action is
        # used.  Keep them for the future StatusIR compiler but do not emit
        # them as direct ActionIR damage/effects.
        if source_path.startswith("Modifiers.") or source_path.startswith("GlobalModifiers."):
            status_definition_hints.append(item)
            continue
        if typ == "damage_packet":
            damage_packets.append(item)
        elif typ == "trigger_ability":
            ability_refs.append(item)
        elif typ in ACTION_EFFECT_TYPES:
            effects.append(item)
        elif typ in CONTROL_TYPES:
            control_flow.append(item)
        elif typ in CONDITION_TYPES:
            conditions.append(item)
        else:
            unsupported[str(typ)] += 1
    damage_packets = _dedupe_damage_packets(damage_packets)
    levels = action.get("levels") or []
    max_level = levels[-1] if levels else {}
    tags = []
    kind = action.get("kind_hint") or "unknown"
    if kind and kind != "unknown":
        tags.append(kind)
    attack_type = str(action.get("attack_type") or "")
    if "Ultra" in attack_type or kind == "ultimate":
        tags.append("ultimate")
    if attack_type == "Normal" or kind == "basic":
        tags.extend(["attack", "basic"])
    elif kind.startswith("skill"):
        tags.extend(["skill"])
    return {
        "action_id": action.get("action_id"),
        "trigger_key": action.get("trigger_key"),
        "entry_ability": action.get("entry_ability"),
        "kind": kind,
        "tags": sorted(set(tags)),
        "damage_type": action.get("damage_type"),
        "attack_type": action.get("attack_type"),
        "cost_hints": {
            "bp_need": max_level.get("bp_need"),
            "sp_multiple_ratio": max_level.get("sp_multiple_ratio"),
            "delay_ratio": max_level.get("delay_ratio"),
        },
        "display_hints": {
            "stance_damage_display": max_level.get("stance_damage_display"),
            "show_stance_list": max_level.get("show_stance_list"),
            "show_damage_list": max_level.get("show_damage_list"),
        },
        "damage_packets": damage_packets,
        "effects": effects,
        "control_flow": control_flow,
        "conditions_seen": conditions[:40],
        "ability_references": ability_refs,
        "status_definition_hints": status_definition_hints[:80],
        "status_definition_hint_count": len(status_definition_hints),
        "unresolved_refs": summary.get("unresolved_refs", []),
        "unlowered_combat_node_types": summary.get("unlowered_combat_node_types", {}),
        "coverage": summary.get("lowering_coverage", {}),
        "unsupported_lowered_types": dict(unsupported),
        "ir_status": _ir_status(damage_packets, effects, summary),
    }


def _ir_status(damage_packets: list[dict[str, Any]], effects: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    cov = summary.get("lowering_coverage", {}) if isinstance(summary, dict) else {}
    unresolved = summary.get("unresolved_refs", []) if isinstance(summary, dict) else []
    unlowered = cov.get("unlowered_relevant_count", 0) or 0
    if unresolved:
        return "partial_unresolved_ability_refs"
    if unlowered:
        return "partial_unlowered_combat_nodes"
    if damage_packets or effects:
        return "candidate_executable_ir"
    return "metadata_only_no_runtime_effects_detected"


def compile_target_avatar_action_ir(source_path: str | Path, avatar_ids: list[int], *, max_depth: int = 5, max_lowered: int = 160, max_nodes: int = 4000) -> dict[str, Any]:
    src = TBGDSource.open(source_path)
    compiler = ContentCompiler(src, include_ability_previews=False, ability_preview_avatar_ids=set(avatar_ids))
    avatars = [a for a in compiler.compile_avatar_templates() if _safe_int(a.get("avatar_id")) in set(avatar_ids)]
    # Re-summarize with wider limits than the lightweight content compiler preview.
    out_avatars = []
    for av in avatars:
        cfg_path = (av.get("config_paths") or {}).get("character")
        character_config, ability_idx, ability_path = compiler._load_character_and_ability_index(cfg_path)
        slots = compiler._skill_slots_by_name(character_config)
        actions = []
        for act in av.get("actions", []):
            trig = act.get("trigger_key")
            slot = slots.get(str(trig), {})
            entry = slot.get("entry_ability") or act.get("entry_ability")
            action_copy = dict(act)
            action_copy["character_slot"] = slot
            action_copy["entry_ability"] = entry
            action_copy["ability_graph_summary"] = summarize_ability_chain(ability_idx, entry, max_depth=max_depth, max_lowered=max_lowered, max_nodes=max_nodes) if entry else {"entry_ability": entry, "found": False}
            actions.append(lowerings_to_action_ir(action_copy))
        out_avatars.append({
            "template_id": av.get("template_id"),
            "avatar_id": av.get("avatar_id"),
            "name_hash": av.get("name_hash"),
            "element": av.get("element"),
            "path": av.get("path"),
            "max_energy": av.get("max_energy"),
            "config_paths": {"character": cfg_path, "ability": ability_path},
            "actions": actions,
            "compile_status": "targeted_action_ir_candidates_ready",
        })
    return {
        "format": "hsr_targeted_action_ir_bundle",
        "version": "0.7",
        "source": str(source_path),
        "avatar_ids": avatar_ids,
        "avatars": out_avatars,
        "summary": summarize_bundle(out_avatars),
    }


def summarize_bundle(avatars: list[dict[str, Any]]) -> dict[str, Any]:
    status = Counter()
    packets = 0
    effects = 0
    unlowered = Counter()
    unresolved = 0
    for av in avatars:
        for a in av.get("actions", []):
            status[a.get("ir_status", "unknown")] += 1
            packets += len(a.get("damage_packets", []))
            effects += len(a.get("effects", []))
            unresolved += len(a.get("unresolved_refs", []))
            unlowered.update(a.get("unlowered_combat_node_types", {}))
    return {
        "avatar_count": len(avatars),
        "action_count": sum(len(a.get("actions", [])) for a in avatars),
        "ir_status_counts": dict(status.most_common()),
        "damage_packet_count": packets,
        "effect_count": effects,
        "unresolved_ref_count": unresolved,
        "top_unlowered_combat_node_types": dict(unlowered.most_common(20)),
    }


def write_target_avatar_action_ir(source_path: str | Path, out_dir: str | Path, avatar_ids: list[int], *, max_depth: int = 5, max_lowered: int = 160, max_nodes: int = 4000) -> dict[str, Any]:
    bundle = compile_target_avatar_action_ir(source_path, avatar_ids, max_depth=max_depth, max_lowered=max_lowered, max_nodes=max_nodes)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "targeted_action_ir_bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "targeted_action_ir_summary.json").write_text(json.dumps(bundle["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle["summary"]


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Compile selected TBGD avatars into candidate executable ActionIR")
    parser.add_argument("source")
    parser.add_argument("--avatar-id", action="append", type=int, required=True)
    parser.add_argument("--output-dir", "-o", required=True)
    parser.add_argument("--max-depth", type=int, default=5)
    args = parser.parse_args(argv)
    summary = write_target_avatar_action_ir(args.source, args.output_dir, args.avatar_id, max_depth=args.max_depth)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
