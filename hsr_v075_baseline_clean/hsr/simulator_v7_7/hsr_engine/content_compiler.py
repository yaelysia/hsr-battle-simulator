from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections import defaultdict
import json
import re

from .tbgd_loader import TBGDSource, unwrap_value, text_hash
from .core_rules import coerce_float, coerce_numeric_value, normalize_str_list
from .ability_lowering import ability_index, summarize_ability_chain


class ContentCompileError(RuntimeError):
    pass


def _safe_int(v: Any, default: int | None = None) -> int | None:
    try:
        if v is None or v == "":
            return default
        return int(v)
    except Exception:
        return default


def _value(v: Any) -> Any:
    return unwrap_value(v)


def _num(v: Any, default: float | None = None) -> float | None:
    try:
        return coerce_float(_value(v))
    except Exception:
        return default


def _param_list(params: Any) -> list[Any]:
    params = _value(params or [])
    if not isinstance(params, list):
        return []
    out = []
    for p in params:
        if isinstance(p, dict) and "Value" in p:
            out.append(_value(p["Value"]))
        else:
            out.append(_value(p))
    return out


def _prop_list(raw: Any) -> list[dict[str, Any]]:
    raw = _value(raw or [])
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        # TBGD exports sometimes use readable keys, sometimes obfuscated keys.
        prop = item.get("PropertyType") or item.get("FODBMMCKAEN") or item.get("Property") or item.get("Type")
        val = item.get("Value", item.get("MNDFOPKBHKP", item.get("ValueParam")))
        out.append({"property": prop, "value": _value(val), "raw": _value(item)})
    return out


def _resistance_map(raw: Any) -> dict[str, float]:
    raw = _value(raw or [])
    out: dict[str, float] = {}
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        dtype = item.get("DamageType") or item.get("type")
        if not dtype:
            continue
        out[str(dtype)] = _num(item.get("Value"), 0.0) or 0.0
    return out


def _status_stats_from_promotion(row: dict[str, Any]) -> dict[str, Any]:
    row = _value(row or {})
    return {
        "level_max": row.get("MaxLevel"),
        "hp_base": row.get("HPBase"),
        "hp_add": row.get("HPAdd"),
        "atk_base": row.get("AttackBase"),
        "atk_add": row.get("AttackAdd"),
        "def_base": row.get("DefenceBase"),
        "def_add": row.get("DefenceAdd"),
        "spd_base": row.get("SpeedBase"),
        "crit_rate_base": row.get("CriticalChance"),
        "crit_dmg_base": row.get("CriticalDamage"),
        "aggro_base": row.get("BaseAggro"),
    }


def _skill_kind(row: dict[str, Any]) -> str:
    attack_type = str(row.get("AttackType", ""))
    effect = str(row.get("SkillEffect", ""))
    # Keep it conservative: this is classification metadata, not combat execution.
    if "Ultra" in attack_type or "Ultra" in effect:
        return "ultimate"
    if "MazeNormal" in attack_type or "Normal" == attack_type:
        return "basic"
    if "Maze" in attack_type and "Normal" not in attack_type:
        return "skill_or_talent"
    return "unknown"


def _skill_rows_by_id(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    by_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        row = _value(r)
        sid = _safe_int(row.get("SkillID"))
        if sid is None:
            continue
        by_id[sid].append(row)
    for sid in list(by_id):
        by_id[sid].sort(key=lambda x: _safe_int(x.get("Level"), 0) or 0)
    return by_id


@dataclass
class ContentCompiler:
    """Compile raw TurnBasedGameData catalogs into simulator-facing Content IR.

    This compiler is deliberately a boundary layer.  It does not execute combat
    and it does not parse RPG.GameCore ability graphs into effects yet; it emits
    stable template IR plus compile_status markers.  The Combat Kernel must never
    depend on raw TurnBasedGameData field names.
    """

    source: TBGDSource
    include_ability_previews: bool = False
    ability_preview_avatar_ids: set[int] = field(default_factory=set)

    def _table(self, name: str, default: Any = None) -> Any:
        try:
            return self.source.load_table(name)
        except Exception:
            return [] if default is None else default

    def _candidate_ability_paths(self, character_json_path: str | None) -> list[str]:
        if not character_json_path:
            return []
        rel = str(character_json_path).replace("\\", "/")
        out: list[str] = []
        if rel.startswith("Config/ConfigCharacter/"):
            ability_rel = rel.replace("Config/ConfigCharacter/", "Config/ConfigAbility/", 1)
            if ability_rel.endswith("_Config.json"):
                ability_rel = ability_rel[: -len("_Config.json")] + "_Ability.json"
            out.append(ability_rel)
        # Some content has already supplied an ability path or a nearby naming variant.
        if rel.startswith("Config/ConfigAbility/"):
            out.append(rel)
        dedup: list[str] = []
        for x in out:
            if x and x not in dedup:
                dedup.append(x)
        return dedup

    def _load_character_and_ability_index(self, character_json_path: str | None) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str | None]:
        character_config: dict[str, Any] = {}
        if character_json_path:
            try:
                character_config = _value(self.source.read_json(str(character_json_path)))
            except Exception:
                character_config = {}
        ability_idx: dict[str, dict[str, Any]] = {}
        ability_path: str | None = None
        for candidate in self._candidate_ability_paths(character_json_path):
            try:
                if self.source.exists(candidate):
                    ability_file = _value(self.source.read_json(candidate))
                    ability_idx = ability_index(ability_file if isinstance(ability_file, dict) else {})
                    ability_path = candidate
                    break
            except Exception:
                continue
        return character_config, ability_idx, ability_path

    def _skill_slots_by_name(self, character_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for slot in character_config.get("SkillList", []) if isinstance(character_config.get("SkillList", []), list) else []:
            if not isinstance(slot, dict):
                continue
            name = slot.get("Name")
            if not name:
                continue
            target_info = slot.get("TargetInfo", {}) if isinstance(slot.get("TargetInfo", {}), dict) else {}
            out[str(name)] = {
                "slot_name": name,
                "skill_type": slot.get("SkillType"),
                "use_type": slot.get("UseType"),
                "target_type": target_info.get("TargetType"),
                "entry_ability": slot.get("EntryAbility"),
                "prepare_ability": slot.get("PrepareAbility"),
            }
        return out

    def compile_avatar_templates(self) -> list[dict[str, Any]]:
        avatars = [_value(r) for r in self._table("AvatarConfig")]
        promotions = [_value(r) for r in self._table("AvatarPromotionConfig")]
        skill_rows = _skill_rows_by_id(self._table("AvatarSkillConfig"))
        tree_rows = [_value(r) for r in self._table("AvatarSkillTreeConfig")]

        promo_by_avatar: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for p in promotions:
            aid = _safe_int(p.get("AvatarID"))
            if aid is not None:
                promo_by_avatar[aid].append(p)
        for aid in promo_by_avatar:
            promo_by_avatar[aid].sort(key=lambda x: _safe_int(x.get("MaxLevel"), 0) or 0)

        tree_by_avatar: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for r in tree_rows:
            aid = _safe_int(r.get("AvatarID"))
            if aid is not None:
                tree_by_avatar[aid].append(r)

        out = []
        for row in avatars:
            aid = _safe_int(row.get("AvatarID"))
            if aid is None:
                continue
            max_promo = promo_by_avatar.get(aid, [{}])[-1] if promo_by_avatar.get(aid) else {}
            include_preview = self.include_ability_previews or aid in self.ability_preview_avatar_ids
            if include_preview:
                character_config, ability_idx, ability_path = self._load_character_and_ability_index(row.get("JsonPath"))
                skill_slots = self._skill_slots_by_name(character_config)
            else:
                character_config, ability_idx, ability_path, skill_slots = {}, {}, None, {}
            skill_ids = [_safe_int(x) for x in _value(row.get("SkillList", []))]
            skill_ids = [x for x in skill_ids if x is not None]
            actions = []
            for sid in skill_ids:
                levels = skill_rows.get(sid, [])
                representative = levels[-1] if levels else {}
                trigger_key = representative.get("SkillTriggerKey")
                slot = skill_slots.get(str(trigger_key), {})
                entry_ability = slot.get("entry_ability")
                ability_summary = summarize_ability_chain(ability_idx, entry_ability, max_depth=4, max_lowered=60, max_nodes=1500) if include_preview and ability_idx and entry_ability else {"entry_ability": entry_ability, "found": False, "preview_included": False}
                actions.append({
                    "action_id": sid,
                    "kind_hint": _skill_kind(representative),
                    "damage_type": representative.get("StanceDamageType") or row.get("DamageType"),
                    "attack_type": representative.get("AttackType"),
                    "skill_effect": representative.get("SkillEffect"),
                    "trigger_key": trigger_key,
                    "character_slot": slot,
                    "entry_ability": entry_ability,
                    "ability_graph_summary": ability_summary,
                    "max_level": representative.get("MaxLevel"),
                    "levels": [
                        {
                            "level": lvl.get("Level"),
                            "bp_need": _value(lvl.get("BPNeed")),
                            "sp_multiple_ratio": _value(lvl.get("SPMultipleRatio")),
                            "delay_ratio": _value(lvl.get("DelayRatio")),
                            "stance_damage_display": lvl.get("StanceDamageDisplay"),
                            "stance_damage_type": lvl.get("StanceDamageType"),
                            "param_list": _param_list(lvl.get("ParamList")),
                            "simple_param_list": _param_list(lvl.get("SimpleParamList")),
                            "show_stance_list": _param_list(lvl.get("ShowStanceList")),
                            "show_damage_list": _param_list(lvl.get("ShowDamageList")),
                            "extra_effect_ids": _value(lvl.get("ExtraEffectIDList", [])),
                            "simple_extra_effect_ids": _value(lvl.get("SimpleExtraEffectIDList", [])),
                        }
                        for lvl in levels
                    ],
                    "compile_status": "metadata_only_pending_ability_graph",
                })
            out.append({
                "template_id": f"avatar:{aid}",
                "source": {"dataset": "TurnBasedGameData", "table": "AvatarConfig", "id": aid},
                "unit_kind": "avatar",
                "avatar_id": aid,
                "name_hash": text_hash(row.get("AvatarName")),
                "full_name_hash": text_hash(row.get("AvatarFullName")),
                "rarity": row.get("Rarity"),
                "element": row.get("DamageType"),
                "path": row.get("AvatarBaseType"),
                "max_energy": _value(row.get("SPNeed")),
                "stats_at_max_promotion": _status_stats_from_promotion(max_promo),
                "rank_ids": _value(row.get("RankIDList", [])),
                "skill_ids": skill_ids,
                "actions": actions,
                "skill_tree_points": [
                    {
                        "point_id": tr.get("PointID"),
                        "point_type": tr.get("PointType"),
                        "max_level": tr.get("MaxLevel"),
                        "default_unlock": tr.get("DefaultUnlock"),
                        "level_up_skill_ids": _value(tr.get("LevelUpSkillID", [])),
                        "status_add_list": _value(tr.get("StatusAddList", [])),
                        "ability_name": tr.get("AbilityName"),
                        "param_list": _param_list(tr.get("ParamList")),
                    }
                    for tr in tree_by_avatar.get(aid, [])
                ],
                "config_paths": {
                    "character": row.get("JsonPath"),
                    "ability": ability_path,
                    "ai": row.get("AIPath"),
                },
                "compile_status": "template_metadata_ready_actions_with_targeted_ability_preview" if include_preview else "template_metadata_ready_actions_pending_ability_graph_preview",
            })
        return out

    def compile_light_cone_templates(self) -> list[dict[str, Any]]:
        rows = [_value(r) for r in self._table("EquipmentConfig")]
        skills = [_value(r) for r in self._table("EquipmentSkillConfig")]
        by_skill: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for s in skills:
            sid = _safe_int(s.get("SkillID"))
            if sid is not None:
                by_skill[sid].append(s)
        for sid in by_skill:
            by_skill[sid].sort(key=lambda x: _safe_int(x.get("Level"), 0) or 0)
        out = []
        for row in rows:
            eid = _safe_int(row.get("EquipmentID"))
            if eid is None:
                continue
            skill_id = _safe_int(row.get("SkillID"))
            skill_levels = by_skill.get(skill_id or -1, [])
            out.append({
                "template_id": f"light_cone:{eid}",
                "source": {"dataset": "TurnBasedGameData", "table": "EquipmentConfig", "id": eid},
                "equipment_id": eid,
                "name_hash": text_hash(row.get("EquipmentName")),
                "rarity": row.get("Rarity"),
                "path": row.get("AvatarBaseType"),
                "max_promotion": row.get("MaxPromotion"),
                "max_rank": row.get("MaxRank"),
                "skill_id": skill_id,
                "skill": {
                    "levels": [
                        {
                            "level": s.get("Level"),
                            "ability_name": s.get("AbilityName"),
                            "param_list": _param_list(s.get("ParamList")),
                            "ability_property": _value(s.get("AbilityProperty", [])),
                        }
                        for s in skill_levels
                    ],
                    "compile_status": "params_ready_effects_pending_ability_graph",
                },
            })
        return out

    def compile_relic_set_templates(self) -> list[dict[str, Any]]:
        rows = [_value(r) for r in self._table("RelicSetConfig")]
        skills = [_value(r) for r in self._table("RelicSetSkillConfig")]
        by_set: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for s in skills:
            sid = _safe_int(s.get("SetID"))
            if sid is not None:
                by_set[sid].append(s)
        for sid in by_set:
            by_set[sid].sort(key=lambda x: _safe_int(x.get("RequireNum"), 0) or 0)
        out = []
        for row in rows:
            sid = _safe_int(row.get("SetID"))
            if sid is None:
                continue
            out.append({
                "template_id": f"relic_set:{sid}",
                "source": {"dataset": "TurnBasedGameData", "table": "RelicSetConfig", "id": sid},
                "set_id": sid,
                "name_hash": text_hash(row.get("SetName")),
                "release": row.get("Release"),
                "release_version": row.get("ReleaseVersion"),
                "set_skill_list": _value(row.get("SetSkillList", [])),
                "bonuses": [
                    {
                        "require_num": s.get("RequireNum"),
                        "property_modifiers": _prop_list(s.get("PropertyList")),
                        "ability_name": s.get("AbilityName"),
                        "ability_param_list": _param_list(s.get("AbilityParamList")),
                        "compile_status": "property_modifiers_ready_ability_effects_pending_ability_graph" if s.get("AbilityName") else "property_modifiers_ready",
                    }
                    for s in by_set.get(sid, [])
                ],
            })
        return out

    def compile_enemy_templates(self) -> list[dict[str, Any]]:
        rows = [_value(r) for r in self._table("MonsterConfig")]
        skill_rows = _skill_rows_by_id(self._table("MonsterSkillConfig"))
        out = []
        for row in rows:
            mid = _safe_int(row.get("MonsterID"))
            if mid is None:
                continue
            skill_ids = [_safe_int(x) for x in _value(row.get("SkillList", []))]
            skill_ids = [x for x in skill_ids if x is not None]
            skills = []
            for sid in skill_ids:
                levels = skill_rows.get(sid, [])
                rep = levels[-1] if levels else {}
                skills.append({
                    "action_id": sid,
                    "damage_type": rep.get("DamageType"),
                    "attack_type": rep.get("AttackType"),
                    "trigger_key": rep.get("SkillTriggerKey"),
                    "phase_list": _value(rep.get("PhaseList", [])),
                    "ai_cd": rep.get("AI_CD"),
                    "ai_icd": rep.get("AI_ICD"),
                    "levels": [
                        {
                            "level": lvl.get("Level"),
                            "sp_hit_base": _value(lvl.get("SPHitBase")),
                            "delay_ratio": _value(lvl.get("DelayRatio")),
                            "param_list": _param_list(lvl.get("ParamList")),
                            "modifier_list": _value(lvl.get("ModifierList", [])),
                            "extra_effect_ids": _value(lvl.get("ExtraEffectIDList", [])),
                        }
                        for lvl in levels
                    ],
                    "compile_status": "metadata_only_pending_ability_graph",
                })
            out.append({
                "template_id": f"enemy:{mid}",
                "source": {"dataset": "TurnBasedGameData", "table": "MonsterConfig", "id": mid},
                "monster_id": mid,
                "monster_template_id": row.get("MonsterTemplateID"),
                "name_hash": text_hash(row.get("MonsterName")),
                "hard_level_group": row.get("HardLevelGroup"),
                "elite_group": row.get("EliteGroup"),
                "weaknesses": normalize_str_list(row.get("StanceWeakList", [])),
                "resistances": _resistance_map(row.get("DamageTypeResistance")),
                "debuff_resist": _value(row.get("DebuffResist", [])),
                "summon_ids": _value(row.get("SummonIDList", [])),
                "ability_names": _value(row.get("AbilityNameList", [])),
                "skill_ids": skill_ids,
                "actions": skills,
                "override_ai_path": row.get("OverrideAIPath"),
                "override_ai_skill_sequence": _value(row.get("OverrideAISkillSequence", [])),
                "compile_status": "template_metadata_ready_actions_pending_ability_graph_and_level_scaling",
            })
        return out

    def compile_stage_templates(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = [_value(r) for r in self._table("StageConfig")]
        if limit is not None:
            rows = rows[:limit]
        out = []
        for row in rows:
            sid = _safe_int(row.get("StageID"))
            if sid is None:
                continue
            out.append({
                "template_id": f"stage:{sid}",
                "source": {"dataset": "TurnBasedGameData", "table": "StageConfig", "id": sid},
                "stage_id": sid,
                "stage_type": row.get("StageType"),
                "name_hash": text_hash(row.get("StageName")),
                "hard_level_group": row.get("HardLevelGroup"),
                "level": row.get("Level"),
                "monster_waves": _value(row.get("MonsterList", [])),
                "stage_config_data": _value(row.get("StageConfigData", [])),
                "stage_ability_config": _value(row.get("StageAbilityConfig", [])),
                "trial_avatar_list": _value(row.get("TrialAvatarList", [])),
                "compile_status": "stage_wave_metadata_ready_stage_abilities_pending_ability_graph",
            })
        return out

    def compile_bundle(self, *, include_stage_rows: int | None = 500) -> dict[str, Any]:
        avatars = self.compile_avatar_templates()
        light_cones = self.compile_light_cone_templates()
        relic_sets = self.compile_relic_set_templates()
        enemies = self.compile_enemy_templates()
        stages = self.compile_stage_templates(limit=include_stage_rows)
        manifest = {
            "format": "hsr_content_ir_bundle",
            "version": "0.4",
            "source": str(self.source.zip_path or self.source.root),
            "counts": {
                "avatars": len(avatars),
                "light_cones": len(light_cones),
                "relic_sets": len(relic_sets),
                "enemies": len(enemies),
                "stages_included": len(stages),
                "stages_limit": include_stage_rows,
            },
            "kernel_boundary": "Combat Kernel consumes Content IR only; raw TurnBasedGameData fields are compiler input, not runtime rules.",
            "compile_status": "template_metadata_ready_targeted_ability_previews_available" if self.include_ability_previews or self.ability_preview_avatar_ids else "template_metadata_ready_ability_graph_compilation_pending",
        }
        return {
            "manifest": manifest,
            "avatars": avatars,
            "light_cones": light_cones,
            "relic_sets": relic_sets,
            "enemies": enemies,
            "stages": stages,
        }


def write_content_ir_bundle(source_path: str | Path, out_dir: str | Path, *, include_stage_rows: int | None = 500) -> dict[str, Any]:
    src = TBGDSource.open(source_path)
    compiler = ContentCompiler(src)
    bundle = compiler.compile_bundle(include_stage_rows=include_stage_rows)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "MANIFEST.content_ir.json").write_text(json.dumps(bundle["manifest"], ensure_ascii=False, indent=2), encoding="utf-8")
    for key in ("avatars", "light_cones", "relic_sets", "enemies", "stages"):
        (out / f"{key}.content_ir.json").write_text(json.dumps(bundle[key], ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle["manifest"]


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Compile TurnBasedGameData into canonical HSR Content IR bundle")
    parser.add_argument("source", help="Path to turnbasedgamedata-main.zip or extracted directory")
    parser.add_argument("--output-dir", "-o", required=True, help="Write Content IR JSON bundle to this directory")
    parser.add_argument("--stage-limit", type=int, default=500, help="Number of StageConfig rows to include; use -1 for all")
    args = parser.parse_args(argv)
    limit = None if args.stage_limit < 0 else args.stage_limit
    manifest = write_content_ir_bundle(args.source, args.output_dir, include_stage_rows=limit)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
