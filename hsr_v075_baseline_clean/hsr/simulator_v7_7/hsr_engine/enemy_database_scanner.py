from __future__ import annotations

"""Scan TurnBasedGameData enemy-side data and emit a generic enemy template.

This module is intentionally source-facing.  It does not claim that every enemy
ability graph is executable.  It summarizes what an enemy template must carry so
later runtime/lowering work can be driven from observed database structure rather
than from a single hand-written boss.
"""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import json
import re
import zipfile

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

from .tbgd_loader import TBGDSource, unwrap_value, text_hash


def _read_table(src: TBGDSource, table: str) -> list[dict[str, Any]]:
    try:
        rows = src.load_table(table)
    except Exception:
        return []
    return [unwrap_value(r) for r in rows if isinstance(r, dict)]


def _hash_text_maps(src: TBGDSource) -> tuple[dict[str, str], dict[str, str]]:
    def read(rel: str) -> dict[str, str]:
        try:
            raw = src.read_json(rel)
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}
    return read("TextMap/TextMapCHS.json"), read("TextMap/TextMapEN.json")


def _name_from_hash(hash_obj: Any, text_chs: dict[str, str], text_en: dict[str, str]) -> dict[str, Any]:
    h = text_hash(hash_obj)
    if h is None:
        return {"hash": None, "chs": None, "en": None}
    return {"hash": h, "chs": text_chs.get(str(h)), "en": text_en.get(str(h))}


def _counter_ratio(counter: Counter[str], n: int = 20) -> dict[str, int]:
    return dict(counter.most_common(n))


def _walk_types(obj: Any, counter: Counter[str], event_counter: Counter[str] | None = None) -> None:
    if isinstance(obj, dict):
        t = obj.get("$type") or obj.get("Type") or obj.get("type")
        if isinstance(t, str):
            counter[t] += 1
        if event_counter is not None:
            for k, v in obj.items():
                if isinstance(k, str) and k.startswith("On"):
                    event_counter[k] += len(v) if isinstance(v, list) else 1
        for v in obj.values():
            _walk_types(v, counter, event_counter)
    elif isinstance(obj, list):
        for v in obj:
            _walk_types(v, counter, event_counter)


COMBAT_NODE_PATTERNS: dict[str, list[str]] = {
    "damage": ["Damage", "AttackData"],
    "heal_or_shield": ["Heal", "Shield", "HP", "Recover"],
    "modifier_status": ["Modifier", "Status", "Dispel"],
    "summon": ["Summon"],
    "phase_or_death": ["SetMonsterPhase", "ForceKill", "Die", "SetDieImmediately"],
    "dynamic_value": ["DynamicValue", "SetModifierDynamicValue"],
    "action_order": ["ActionDelay", "Advance", "Delay"],
    "predicate": ["Predicate", "ByCompare", "ByIs", "ByRandom", "ByAnd", "ByAny"],
    "targeting": ["Retarget", "TargetAlias", "SkillTarget", "Formation"],
    "visual_timeline": ["Camera", "Timeline", "Anim", "Audio", "UI", "Visible", "Effect"],
}


def _classify_node_type(t: str) -> list[str]:
    out = []
    for group, pats in COMBAT_NODE_PATTERNS.items():
        if any(p in t for p in pats):
            out.append(group)
    return out or ["other"]


def _skill_param_list(row: dict[str, Any]) -> list[Any]:
    params = row.get("ParamList") or []
    if not isinstance(params, list):
        return []
    out = []
    for p in params:
        if isinstance(p, dict) and "Value" in p:
            out.append(p["Value"])
        else:
            out.append(p)
    return out


def _ability_file_prefix_from_json_config(json_config: str | None) -> str | None:
    if not json_config:
        return None
    stem = Path(json_config).stem
    # Monster_W4_Hearse_00_Config -> Monster_W4_Hearse_00
    return re.sub(r"_Config$", "", stem)


def _read_rel_json(src: TBGDSource, rel: str) -> Any:
    return src.read_json(rel)


def _scan_monster_ability_graphs(src: TBGDSource, *, sample_limit: int = 10) -> dict[str, Any]:
    files = [
        f for f in src.list_files("Config/ConfigAbility/Monster/")
        if f.endswith(".json") and not f.endswith(".layout.json") and "/Camera/" not in f
    ]
    type_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    samples_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    file_rows: list[dict[str, Any]] = []
    zf = zipfile.ZipFile(src.zip_path) if src.zip_path else None

    def read(rel: str) -> Any:
        if zf is not None:
            with zf.open(src.prefix + rel) as f:
                return json.load(f)
        return src.read_json(rel)

    for rel in files:
        try:
            data = read(rel)
        except Exception:
            continue
        local_types: Counter[str] = Counter()
        local_events: Counter[str] = Counter()
        _walk_types(data, local_types, local_events)
        _walk_types(data, type_counts, event_counts)
        stem = Path(rel).stem
        m = re.match(r"(Monster_[A-Za-z0-9]+_[A-Za-z0-9]+)", stem)
        family = m.group(1) if m else "unknown"
        category_counts[family] += 1
        # samples by node type, compact only.
        def collect(obj: Any, ability: str | None = None):
            if isinstance(obj, dict):
                t = obj.get("$type") or obj.get("Type") or obj.get("type")
                if isinstance(t, str) and len(samples_by_type[t]) < sample_limit:
                    samples_by_type[t].append({"file": rel, "ability": ability, "keys": sorted(obj.keys())[:40]})
                for v in obj.values():
                    collect(v, ability)
            elif isinstance(obj, list):
                for it in obj:
                    collect(it, ability)
        if isinstance(data, dict):
            for ab in (data.get("AbilityList") or [])[:80]:
                if isinstance(ab, dict):
                    collect(ab, ab.get("Name"))
        file_rows.append({
            "path": rel,
            "ability_count": len(data.get("AbilityList") or []) if isinstance(data, dict) else 0,
            "top_node_types": dict(local_types.most_common(20)),
            "event_keys": dict(local_events.most_common(20)),
        })
    if zf is not None:
        zf.close()

    classified = Counter()
    rows = []
    for t, c in type_counts.most_common(250):
        groups = _classify_node_type(t)
        for g in groups:
            classified[g] += c
        rows.append({"node_type": t, "count": c, "groups": groups, "samples": samples_by_type.get(t, [])})
    return {
        "monster_ability_file_count": len(files),
        "monster_ability_family_count": len(category_counts),
        "event_key_counts": dict(event_counts.most_common(80)),
        "node_group_counts": dict(classified.most_common()),
        "top_node_types": rows[:120],
        "file_rows_sample": file_rows[:200],
    }


def _scan_monster_character_configs(src: TBGDSource, template_by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    files = [f for f in src.list_files("Config/ConfigCharacter/Monster/") if f.endswith(".json") and not f.endswith(".layout.json")]
    target_types: Counter[str] = Counter()
    use_types: Counter[str] = Counter()
    skill_types: Counter[str] = Counter()
    somato: Counter[str] = Counter()
    armor: Counter[str] = Counter()
    phase_counts: Counter[str] = Counter()
    dynamic_read_types: Counter[str] = Counter()
    sample_rows = []
    zf = zipfile.ZipFile(src.zip_path) if src.zip_path else None

    def read(rel: str) -> Any:
        if zf is not None:
            with zf.open(src.prefix + rel) as f:
                return json.load(f)
        return src.read_json(rel)

    for rel in files:
        try:
            data = read(rel)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        somato[str(data.get("SomatoType"))] += 1
        armor[str(data.get("ArmorType"))] += 1
        if data.get("MaxMonsterPhase") is not None:
            phase_counts[str(data.get("MaxMonsterPhase"))] += 1
        for sk in data.get("SkillList") or []:
            if not isinstance(sk, dict):
                continue
            target_types[str((sk.get("TargetInfo") or {}).get("TargetType"))] += 1
            use_types[str(sk.get("UseType"))] += 1
            skill_types[str(sk.get("SkillType"))] += 1
        dyn = data.get("DynamicValues") or {}
        if isinstance(dyn, dict):
            for group in dyn.values():
                if isinstance(group, dict):
                    for item in group.values():
                        if isinstance(item, dict):
                            ri = item.get("ReadInfo") or {}
                            if isinstance(ri, dict):
                                dynamic_read_types[str(ri.get("Type"))] += 1
        if len(sample_rows) < 80:
            sample_rows.append({
                "path": rel,
                "somato_type": data.get("SomatoType"),
                "armor_type": data.get("ArmorType"),
                "max_monster_phase": data.get("MaxMonsterPhase"),
                "skill_slots": [
                    {"name": s.get("Name"), "skill_type": s.get("SkillType"), "use_type": s.get("UseType"), "target_type": (s.get("TargetInfo") or {}).get("TargetType"), "entry_ability": s.get("EntryAbility")}
                    for s in (data.get("SkillList") or [])[:10] if isinstance(s, dict)
                ],
                "ability_refs_sample": (data.get("AbilityList") or [])[:10],
                "skill_ability_refs_sample": (data.get("SkillAbilityList") or [])[:5],
            })
    if zf is not None:
        zf.close()
    return {
        "monster_character_config_file_count": len(files),
        "target_type_counts": _counter_ratio(target_types, 40),
        "use_type_counts": _counter_ratio(use_types, 40),
        "skill_type_counts": _counter_ratio(skill_types, 40),
        "somato_type_counts": _counter_ratio(somato, 40),
        "armor_type_counts": _counter_ratio(armor, 40),
        "max_monster_phase_counts": _counter_ratio(phase_counts, 20),
        "dynamic_value_read_type_counts": _counter_ratio(dynamic_read_types, 40),
        "config_samples": sample_rows,
    }


def build_enemy_database_scan(source_path: str | Path) -> dict[str, Any]:
    src = TBGDSource.open(source_path)
    text_chs, text_en = _hash_text_maps(src)
    monsters = _read_table(src, "MonsterConfig")
    templates = _read_table(src, "MonsterTemplateConfig")
    skills = _read_table(src, "MonsterSkillConfig")
    extra_effects = _read_table(src, "ExtraEffectConfig")
    stages = _read_table(src, "StageConfig")

    template_by_id = {int(r.get("MonsterTemplateID")): r for r in templates if r.get("MonsterTemplateID") is not None}
    skill_by_id = {int(r.get("SkillID")): r for r in skills if r.get("SkillID") is not None}
    monster_by_id = {int(r.get("MonsterID")): r for r in monsters if r.get("MonsterID") is not None}
    extra_by_id = {int(r.get("ExtraEffectID")): r for r in extra_effects if r.get("ExtraEffectID") is not None}

    rank_counts: Counter[str] = Counter()
    stance_base_counter: Counter[str] = Counter()
    stance_count_counter: Counter[str] = Counter()
    weakness_counter: Counter[str] = Counter()
    weakness_set_counter: Counter[str] = Counter()
    res_counter: Counter[str] = Counter()
    summon_count_counter: Counter[str] = Counter()
    ability_count_counter: Counter[str] = Counter()
    custom_value_keys: Counter[str] = Counter()
    dynamic_value_keys: Counter[str] = Counter()
    override_ai_count = 0
    template_json_prefixes = Counter()
    for r in monsters:
        tmpl = template_by_id.get(int(r.get("MonsterTemplateID", -1))) or {}
        rank_counts[str(tmpl.get("Rank"))] += 1
        stance_base_counter[str(tmpl.get("StanceBase"))] += 1
        stance_count_counter[str(tmpl.get("StanceCount"))] += 1
        weak = [str(x) for x in (r.get("StanceWeakList") or [])]
        for w in weak:
            weakness_counter[w] += 1
        weakness_set_counter["|".join(sorted(weak)) if weak else "none"] += 1
        for rr in r.get("DamageTypeResistance") or []:
            if isinstance(rr, dict):
                res_counter[f"{rr.get('DamageType')}={rr.get('Value')}" ] += 1
        summon_count_counter[str(len(r.get("SummonIDList") or []))] += 1
        ability_count_counter[str(len(r.get("AbilityNameList") or []))] += 1
        for cv in r.get("CustomValues") or []:
            if isinstance(cv, dict):
                for k in cv.keys():
                    custom_value_keys[str(k)] += 1
        for dv in r.get("DynamicValues") or []:
            if isinstance(dv, dict):
                for k in dv.keys():
                    dynamic_value_keys[str(k)] += 1
        if r.get("OverrideAIPath") or r.get("OverrideAISkillSequence"):
            override_ai_count += 1
        pref = _ability_file_prefix_from_json_config(tmpl.get("JsonConfig"))
        if pref:
            template_json_prefixes[pref] += 1

    skill_trigger_counts: Counter[str] = Counter()
    skill_damage_type_counts: Counter[str] = Counter()
    skill_attack_type_counts: Counter[str] = Counter()
    skill_phase_counts: Counter[str] = Counter()
    skill_param_len_counts: Counter[str] = Counter()
    skill_extra_effect_counts: Counter[str] = Counter()
    for s in skills:
        skill_trigger_counts[str(s.get("SkillTriggerKey"))] += 1
        skill_damage_type_counts[str(s.get("DamageType"))] += 1
        skill_attack_type_counts[str(s.get("AttackType"))] += 1
        skill_phase_counts["|".join(str(x) for x in (s.get("PhaseList") or [])) or "none"] += 1
        skill_param_len_counts[str(len(_skill_param_list(s)))] += 1
        for eid in s.get("ExtraEffectIDList") or []:
            try:
                er = extra_by_id[int(eid)]
            except Exception:
                er = {}
            nm = _name_from_hash(er.get("ExtraEffectName"), text_chs, text_en) if er else {"chs": None, "en": None}
            skill_extra_effect_counts[nm.get("chs") or str(eid)] += 1

    stage_monsters: Counter[str] = Counter()
    stage_wave_sizes: Counter[str] = Counter()
    stage_ability_configs: Counter[str] = Counter()
    for st in stages:
        for mac in st.get("MonsterList") or []:
            if isinstance(mac, dict):
                ids = [int(v) for v in mac.values() if isinstance(v, int)]
                stage_wave_sizes[str(len(ids))] += 1
                for mid in ids:
                    stage_monsters[str(mid)] += 1
        for ac in st.get("StageAbilityConfig") or []:
            stage_ability_configs[str(ac)] += 1

    # Representative rows keep raw IDs/text to guide per-enemy template generation.
    representative_monsters = []
    for r in monsters[:200]:
        mid = int(r.get("MonsterID"))
        tmpl = template_by_id.get(int(r.get("MonsterTemplateID", -1))) or {}
        representative_monsters.append({
            "monster_id": mid,
            "template_id": r.get("MonsterTemplateID"),
            "name": _name_from_hash(r.get("MonsterName"), text_chs, text_en),
            "rank": tmpl.get("Rank"),
            "json_config": tmpl.get("JsonConfig"),
            "ai_path": tmpl.get("AIPath") or r.get("OverrideAIPath"),
            "weaknesses": r.get("StanceWeakList") or [],
            "summons": r.get("SummonIDList") or [],
            "skill_ids": r.get("SkillList") or [],
        })

    ability_scan = _scan_monster_ability_graphs(src)
    character_scan = _scan_monster_character_configs(src, template_by_id)

    generic_template = {
        "kind": "enemy_template",
        "schema_version": "enemy_common_template_v0.1",
        "id": "<stable_enemy_id>",
        "source_identity": {
            "monster_id": "MonsterConfig.MonsterID",
            "monster_template_id": "MonsterConfig.MonsterTemplateID -> MonsterTemplateConfig.MonsterTemplateID",
            "rank": "MonsterTemplateConfig.Rank",
            "name_hashes": ["MonsterConfig.MonsterName", "MonsterTemplateConfig.MonsterName"],
            "text_map": ["TextMapCHS", "TextMapEN"],
            "source_trace_required": True,
        },
        "stat_model": {
            "base": ["AttackBase", "DefenceBase", "HPBase", "SpeedBase", "StanceBase", "StatusResistanceBase", "InitialDelayRatio"],
            "stage_scaling": ["StageConfig.Level", "StageConfig.HardLevelGroup", "MonsterConfig.*ModifyRatio", "EliteGroup/SpecialGroup multipliers when present"],
            "runtime_fields": ["level", "hp", "max_hp", "atk", "def", "speed", "initial_delay_ratio", "toughness", "max_toughness"],
        },
        "defense_model": {
            "weaknesses": "MonsterConfig.StanceWeakList",
            "resistance": "MonsterConfig.DamageTypeResistance",
            "debuff_resistance": "MonsterConfig.DebuffResist + StatusResistanceBase",
            "toughness": "MonsterTemplateConfig.StanceBase * MonsterConfig.StanceModifyRatio * stage ratios",
            "special_layers": "core_mechanics/statuses, e.g. armor layers, force field, toughness protection",
        },
        "skills": {
            "source": "MonsterConfig.SkillList -> MonsterSkillConfig.SkillID",
            "fields": ["SkillTriggerKey", "SkillTypeDesc", "SkillTag", "DamageType", "AttackType", "SPHitBase", "DelayRatio", "AI_CD", "AI_ICD", "PhaseList", "ParamList", "ExtraEffectIDList"],
            "targeting_source": "ConfigCharacter/Monster/*_Config.json SkillList.TargetInfo + AIPath decisions",
            "ability_graph_source": "ConfigAbility/Monster/*_Ability.json EntryAbility/SkillAbilityList",
            "runtime_action_shape": ["action_type", "target_policy", "damage_packets", "status_effects", "summon_effects", "phase_effects", "mechanic_hooks"],
        },
        "ai_model": {
            "source": ["MonsterTemplateConfig.AIPath", "MonsterTemplateConfig.AISkillSequence", "MonsterConfig.OverrideAIPath", "MonsterConfig.OverrideAISkillSequence"],
            "runtime_fields": ["decision_sequence", "cooldown", "icd", "condition_tree", "target_selection", "rng_policy"],
        },
        "phase_model": {
            "source": ["ConfigCharacter.MaxMonsterPhase", "ConfigCharacter.PhaseList", "skill PhaseList", "ability graph SetMonsterPhase", "hp_bars when modeled"],
            "runtime_fields": ["current_phase", "hp_bars", "on_hp_bar_depleted", "phase_transition_action", "carry_over_damage_policy"],
        },
        "summon_model": {
            "source": ["MonsterConfig.SummonIDList", "ConfigAbility SummonMonster", "CustomValues SummonID*"],
            "runtime_fields": ["summon_templates", "owner", "corresponding_target", "shared_hp", "linked_statuses", "summon_count_policy"],
        },
        "modifier_status_model": {
            "source": ["AddModifier/RemoveModifier/ModifierAttachEffect", "ExtraEffectConfig", "GlobalModifiers", "DynamicValues/CustomValues"],
            "runtime_fields": ["status_id", "tags", "duration", "stacks", "modifiers", "on_apply", "on_remove", "trigger_callbacks", "dynamic_values"],
        },
        "graph_lowering_policy": {
            "combat_relevant": ["Damage/AttackData", "Add/RemoveModifier", "SummonMonster", "SetMonsterPhase", "SetDynamicValue", "ActionDelay", "DispelStatus", "Retarget/target aliases when target policy changes"],
            "evidence_only_by_default": ["Camera", "Timeline", "Anim", "Audio", "UI", "formation-only nodes unless they alter target set"],
            "unknown_policy": "preserve evidence and mark as unlowered_relevant until data-site/text comparison or route test resolves it",
        },
        "validation_contract": {
            "required": ["source_trace", "node_coverage_summary", "exact_route_harness", "mechanic-specific expectations"],
            "stage_case_example": "arbitration_4_3_knight_3 can validate phase/summon/armor/force-field patterns but must not define the whole schema",
        },
    }

    scan = {
        "format": "hsr_tbgd_enemy_database_scan",
        "version": "v0.1",
        "source": str(source_path),
        "tables": {
            "MonsterConfig": len(monsters),
            "MonsterTemplateConfig": len(templates),
            "MonsterSkillConfig": len(skills),
            "ExtraEffectConfig": len(extra_effects),
            "StageConfig": len(stages),
        },
        "monster_summary": {
            "rank_counts": _counter_ratio(rank_counts, 30),
            "weakness_counts": _counter_ratio(weakness_counter, 20),
            "weakness_set_counts": _counter_ratio(weakness_set_counter, 30),
            "summon_count_distribution": _counter_ratio(summon_count_counter, 20),
            "ability_name_count_distribution": _counter_ratio(ability_count_counter, 20),
            "override_ai_monster_count": override_ai_count,
            "custom_value_key_counts": _counter_ratio(custom_value_keys, 80),
            "dynamic_value_key_counts": _counter_ratio(dynamic_value_keys, 80),
        },
        "template_summary": {
            "stance_count_distribution": _counter_ratio(stance_count_counter, 20),
            "json_config_prefix_count": len(template_json_prefixes),
        },
        "skill_summary": {
            "trigger_key_counts": _counter_ratio(skill_trigger_counts, 80),
            "damage_type_counts": _counter_ratio(skill_damage_type_counts, 20),
            "attack_type_counts": _counter_ratio(skill_attack_type_counts, 20),
            "phase_list_counts": _counter_ratio(skill_phase_counts, 30),
            "param_len_counts": _counter_ratio(skill_param_len_counts, 30),
            "extra_effect_name_counts": _counter_ratio(skill_extra_effect_counts, 80),
        },
        "stage_usage_summary": {
            "unique_monsters_referenced_by_stages": len(stage_monsters),
            "top_stage_monsters": _counter_ratio(stage_monsters, 30),
            "stage_wave_size_counts": _counter_ratio(stage_wave_sizes, 20),
            "stage_ability_config_counts": _counter_ratio(stage_ability_configs, 30),
        },
        "monster_character_config_scan": character_scan,
        "monster_ability_graph_scan": ability_scan,
        "representative_monsters_sample": representative_monsters,
        "generic_enemy_template": generic_template,
    }
    return scan


def _knight3_mapping_from_model_pack(model_pack_dir: str | Path) -> dict[str, Any]:
    base = Path(model_pack_dir)
    enemy_dir = base / "models" / "enemies"
    rows = []
    for path in sorted(enemy_dir.glob("*.yaml")):
        if yaml is None:
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        unit = data.get("unit") if isinstance(data, dict) else None
        if not isinstance(unit, dict):
            continue
        rows.append({
            "file": str(path.relative_to(base)),
            "id": unit.get("id"),
            "cn_name": unit.get("cn_name"),
            "template_id": unit.get("template_id"),
            "role": (unit.get("raw") or {}).get("identity", {}).get("role_in_stage"),
            "level": unit.get("level"),
            "hp": unit.get("hp"),
            "speed": unit.get("speed"),
            "toughness": unit.get("toughness"),
            "weaknesses": unit.get("weaknesses"),
            "core_mechanic_keys": sorted((unit.get("core_mechanics") or {}).keys()),
            "skill_count": len(unit.get("skills") or []),
            "source_trace": ((unit.get("raw") or {}).get("raw_source_trace") or {}),
        })
    return {
        "format": "hsr_knight3_existing_enemy_mapping",
        "version": "v0.1",
        "summary_cn": "沿用既有骑士三敌人模板作为验收样例，不把骑士三写成通用敌人 schema。",
        "enemy_count": len(rows),
        "rows": rows,
        "coverage_notes_cn": [
            "破晓战队•赤焰：力场、被火击立即行动、受击计数后失意。",
            "天谴先锋：战甲层数、受击掉层、破甲自伤/延后/回能、召唤天谴斗士、蓄力后分摊攻击。",
            "天谴之矛：共享/联动蛮神，阶段转化，征服或被征服，受征服/畏怖，吸收召唤物强化蛮神。",
        ],
    }


def write_enemy_database_scan(source_path: str | Path, output_dir: str | Path, *, model_pack_dir: str | Path | None = None) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    scan = build_enemy_database_scan(source_path)
    (out / "enemy_database_scan_summary.json").write_text(json.dumps(scan, ensure_ascii=False, indent=2), encoding="utf-8")
    template = scan["generic_enemy_template"]
    if yaml is not None:
        (out / "enemy_common_template_v0_1.yaml").write_text(yaml.safe_dump(template, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        (out / "enemy_common_template_v0_1.json").write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 敌人通用模板 v0.1",
        "",
        "## 数据库扫描摘要",
        "",
        f"- MonsterConfig：{scan['tables']['MonsterConfig']} 行",
        f"- MonsterTemplateConfig：{scan['tables']['MonsterTemplateConfig']} 行",
        f"- MonsterSkillConfig：{scan['tables']['MonsterSkillConfig']} 行",
        f"- ConfigCharacter/Monster：{scan['monster_character_config_scan']['monster_character_config_file_count']} 个",
        f"- ConfigAbility/Monster：{scan['monster_ability_graph_scan']['monster_ability_file_count']} 个（不含 Camera/layout）",
        "",
        "## 通用敌人模板必须包含",
        "",
        "1. 身份与来源：MonsterID、TemplateID、Rank、TextMap 名称、Stage 来源、ConfigCharacter/Ability/AI 路径。",
        "2. 数值模型：base stats、HardLevel/Elite/Stage 修正、HP/ATK/DEF/SPD/韧性、初始延迟。",
        "3. 防御模型：弱点、抗性、控制/负面抵抗、韧性保护、战甲/力场/减伤层。",
        "4. 技能模型：SkillID、TriggerKey、PhaseList、ParamList、SPHitBase、伤害类型、目标策略、ExtraEffect。",
        "5. AI 模型：AIPath、AISkillSequence、冷却/内置冷却、条件树、目标选择和随机策略。",
        "6. 阶段模型：MaxMonsterPhase、PhaseList、HP bars、转阶段触发和转阶段插队。",
        "7. 召唤模型：SummonIDList、SummonMonster 图节点、对应角色/共享生命/绑定状态。",
        "8. 状态/动态值模型：AddModifier/RemoveModifier、GlobalModifiers、CustomValues、DynamicValues。",
        "9. 图 lower 策略：数值节点转 runtime，镜头/UI/纯时间轴节点保留 evidence；未知节点不丢弃。",
        "10. 验证契约：每个机制需要 source_trace、node coverage、exact-route harness 和机制级断言。",
        "",
        "## 敌人 ability graph 节点组统计",
        "",
    ]
    for k, v in scan["monster_ability_graph_scan"]["node_group_counts"].items():
        lines.append(f"- `{k}`：{v}")
    lines += ["", "## 高频技能 TriggerKey", ""]
    for k, v in list(scan["skill_summary"]["trigger_key_counts"].items())[:30]:
        lines.append(f"- `{k}`：{v}")
    (out / "enemy_common_template_cn.md").write_text("\n".join(lines), encoding="utf-8")

    if model_pack_dir is not None:
        mapping = _knight3_mapping_from_model_pack(model_pack_dir)
        (out / "knight3_existing_enemy_mapping_v0_1.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        md = ["# 骑士三既有敌人机制映射", "", mapping["summary_cn"], ""]
        for r in mapping["rows"]:
            md.append(f"- `{r['id']}` / {r['cn_name']}：template={r['template_id']}，level={r['level']}，hp={r['hp']}，speed={r['speed']}，toughness={r['toughness']}，机制：{', '.join(r['core_mechanic_keys'])}")
        md += ["", "## 覆盖说明", ""] + [f"- {x}" for x in mapping["coverage_notes_cn"]]
        (out / "knight3_existing_enemy_mapping_cn.md").write_text("\n".join(md), encoding="utf-8")
    return scan


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Scan TurnBasedGameData enemy database and emit generic enemy template")
    parser.add_argument("source", help="turnbasedgamedata-main.zip or extracted TurnBasedGameData root")
    parser.add_argument("--output-dir", "-o", required=True)
    parser.add_argument("--model-pack", help="Optional model pack directory for existing Knight III mapping")
    args = parser.parse_args(argv)
    result = write_enemy_database_scan(args.source, args.output_dir, model_pack_dir=args.model_pack)
    print(json.dumps({
        "format": result["format"],
        "version": result["version"],
        "tables": result["tables"],
        "monster_ability_file_count": result["monster_ability_graph_scan"]["monster_ability_file_count"],
        "monster_character_config_file_count": result["monster_character_config_scan"]["monster_character_config_file_count"],
        "top_node_groups": result["monster_ability_graph_scan"]["node_group_counts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
