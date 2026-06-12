from __future__ import annotations

from pathlib import Path
from typing import Any
from collections import Counter, defaultdict
import json
import zipfile

from .tbgd_loader import TBGDSource, unwrap_value
from .ability_lowering import classify_inventory


class AbilityGraphIntakeError(RuntimeError):
    pass


def _category_from_path(rel: str) -> str:
    parts = rel.split("/")
    try:
        idx = parts.index("ConfigAbility")
        if len(parts) > idx + 1:
            return parts[idx + 1]
    except ValueError:
        pass
    return "unknown"


def _walk_types(obj: Any, counter: Counter[str], event_counter: Counter[str] | None = None) -> None:
    if isinstance(obj, dict):
        t = obj.get("$type") or obj.get("Type") or obj.get("type")
        if isinstance(t, str):
            counter[t] += 1
        for k, v in obj.items():
            if event_counter is not None and isinstance(k, str) and k.startswith("On"):
                if isinstance(v, list):
                    event_counter[k] += len(v)
                else:
                    event_counter[k] += 1
            _walk_types(v, counter, event_counter)
    elif isinstance(obj, list):
        for item in obj:
            _walk_types(item, counter, event_counter)


def _event_keys_in_ability(ability: dict[str, Any]) -> list[str]:
    return sorted(k for k, v in ability.items() if isinstance(k, str) and k.startswith("On") and isinstance(v, list))


def _character_slot_summary(data: dict[str, Any]) -> dict[str, Any]:
    skill_list = data.get("SkillList", []) if isinstance(data.get("SkillList"), list) else []
    skill_abilities = data.get("SkillAbilityList", []) if isinstance(data.get("SkillAbilityList"), list) else []
    ability_list = data.get("AbilityList", []) if isinstance(data.get("AbilityList"), list) else []
    slots = []
    for s in skill_list:
        if not isinstance(s, dict):
            continue
        slots.append({
            "name": s.get("Name"),
            "skill_type": s.get("SkillType"),
            "use_type": s.get("UseType"),
            "target_type": (s.get("TargetInfo") or {}).get("TargetType") if isinstance(s.get("TargetInfo"), dict) else None,
            "entry_ability": s.get("EntryAbility"),
        })
    return {
        "skill_slots": slots,
        "skill_ability_refs": [x for x in skill_abilities if isinstance(x, str)],
        "passive_ability_refs": [x for x in ability_list if isinstance(x, str)],
    }


def build_ability_graph_inventory(source_path: str | Path, *, sample_limit: int = 5, include_camera: bool = False) -> dict[str, Any]:
    src = TBGDSource.open(source_path)
    files = src.list_files("Config/ConfigAbility/")
    ability_files = [
        f for f in files
        if f.endswith(".json")
        and not f.endswith(".layout.json")
        and (include_camera or "/Camera/" not in f)
    ]
    character_files = [
        f for f in src.list_files("Config/ConfigCharacter/")
        if f.endswith(".json") and not f.endswith(".layout.json")
    ]

    # Reading thousands of small JSON files from a zip is much faster if the zip
    # handle stays open.  Fall back to TBGDSource.read_json for directory input.
    zf = zipfile.ZipFile(src.zip_path) if src.zip_path else None

    def read_rel(rel: str) -> Any:
        if zf is not None:
            with zf.open(src.prefix + rel) as f:
                return json.load(f)
        return src.read_json(rel)

    type_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    file_summaries: list[dict[str, Any]] = []
    samples_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for rel in ability_files:
        try:
            data = read_rel(rel)
        except Exception:
            continue
        category = _category_from_path(rel)
        category_counts[category] += 1
        local_types: Counter[str] = Counter()
        local_events: Counter[str] = Counter()
        _walk_types(data, type_counts, event_counts)
        _walk_types(data, local_types, local_events)
        ability_list = data.get("AbilityList", []) if isinstance(data, dict) else []
        global_mods = data.get("GlobalModifiers", {}) if isinstance(data, dict) else {}
        file_summaries.append({
            "path": rel,
            "category": category,
            "ability_count": len(ability_list) if isinstance(ability_list, list) else 0,
            "global_modifier_count": len(global_mods) if isinstance(global_mods, dict) else 0,
            "event_keys": sorted(local_events.keys()),
            "top_node_types": dict(local_types.most_common(20)),
        })
        # Store a few compact samples per node type, without embedding huge subgraphs.
        def collect_samples(obj: Any, ability_name: str | None = None):
            if isinstance(obj, dict):
                t = obj.get("$type") or obj.get("Type") or obj.get("type")
                if isinstance(t, str) and len(samples_by_type[t]) < sample_limit:
                    samples_by_type[t].append({
                        "file": rel,
                        "ability": ability_name,
                        "keys": sorted(list(obj.keys()))[:40],
                    })
                for k, v in obj.items():
                    collect_samples(v, ability_name=ability_name)
            elif isinstance(obj, list):
                for item in obj:
                    collect_samples(item, ability_name=ability_name)
        if isinstance(ability_list, list):
            for ability in ability_list[:50]:
                if isinstance(ability, dict):
                    collect_samples(ability, ability.get("Name"))
        if isinstance(global_mods, dict):
            collect_samples(global_mods, None)

    # Character configs summarize slot -> EntryAbility refs, which are required to join action data to ability graphs.
    char_summaries = []
    char_categories = Counter()
    for rel in character_files:
        try:
            data = read_rel(rel)
        except Exception:
            continue
        parts = rel.split("/")
        cat = parts[2] if len(parts) > 2 else "unknown"
        char_categories[cat] += 1
        ss = _character_slot_summary(data) if isinstance(data, dict) else {}
        char_summaries.append({
            "path": rel,
            "category": cat,
            **ss,
        })

    if zf is not None:
        zf.close()

    lowering_profile = classify_inventory(type_counts)

    return {
        "format": "hsr_ability_graph_inventory",
        "version": "0.2",
        "source": str(source_path),
        "ability_file_count": len(ability_files),
        "character_config_file_count": len(character_files),
        "ability_file_categories": dict(category_counts.most_common()),
        "character_config_categories": dict(char_categories.most_common()),
        "rpg_gamecore_type_counts": dict(type_counts.most_common(300)),
        "event_key_counts": dict(event_counts.most_common(120)),
        "file_summaries_sample": file_summaries[:200],
        "node_type_samples": dict(samples_by_type),
        "character_slot_summaries_sample": char_summaries[:200],
        "lowering_profile": lowering_profile,
        "lowering_backlog": [
            "Continue lowering combat_relevant_backlog node types by frequency using lowering_profile.node_type_rows.",
            "Lower TriggerAbility chains into ActionIR phase references.",
            "Separate visual/camera/timeline nodes from combat-relevant nodes.",
            "Map GlobalModifiers callbacks into StatusIR/TriggerIR/ModifierIR.",
            "Join CharacterConfig SkillList EntryAbility with AvatarSkillConfig SkillID rows.",
        ],
    }


def write_ability_graph_inventory(source_path: str | Path, out_dir: str | Path, *, sample_limit: int = 5, include_camera: bool = False) -> dict[str, Any]:
    inventory = build_ability_graph_inventory(source_path, sample_limit=sample_limit, include_camera=include_camera)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ability_graph_inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        k: inventory[k]
        for k in [
            "format", "version", "source", "ability_file_count", "character_config_file_count",
            "ability_file_categories", "character_config_categories", "event_key_counts", "lowering_backlog"
        ]
    }
    compact["top_rpg_gamecore_types"] = dict(list(inventory["rpg_gamecore_type_counts"].items())[:80])
    compact["lowering_profile"] = {
        "category_counts": inventory["lowering_profile"]["category_counts"],
        "lowering_status_counts": inventory["lowering_profile"]["lowering_status_counts"],
        "top_rows": inventory["lowering_profile"]["node_type_rows"][:80],
    }
    (out / "ability_lowering_table.json").write_text(json.dumps(inventory["lowering_profile"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "ability_graph_inventory_summary.json").write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    return compact


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Inventory TurnBasedGameData ConfigAbility / ConfigCharacter graphs before lowering")
    parser.add_argument("source", help="Path to turnbasedgamedata-main.zip or extracted directory")
    parser.add_argument("--output-dir", "-o", required=True)
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--include-camera", action="store_true")
    args = parser.parse_args(argv)
    summary = write_ability_graph_inventory(args.source, args.output_dir, sample_limit=args.sample_limit, include_camera=args.include_camera)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
