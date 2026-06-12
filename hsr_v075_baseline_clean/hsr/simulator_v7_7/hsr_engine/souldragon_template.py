from __future__ import annotations

"""Data-derived Souldragon action template helpers.

This module is a step away from a hard-coded runtime fallback.  It derives the
current Dan Heng PT Souldragon shell/action parameters from TurnBasedGameData
AvatarSkillConfig and emits a small runtime template consumed by the simulator.
The full TBGD action graph can still replace this later, but the fallback is now
parameter-data-driven instead of buried in BattleSimulator constants.
"""

from pathlib import Path
from typing import Any
import json

from .tbgd_loader import TBGDSource
from .ability_lowering import ability_index, summarize_ability_chain


DEFAULT_TEMPLATE = {
    "format": "hsr_souldragon_action_template",
    "version": "v0.3",
    "source": "fallback_defaults_from_known_danheng_pt_skill_params",
    "avatar_id": 1414,
    "normal_skill_id": 141404,
    "enhanced_skill_id": 141403,
    "normal_level": 15,
    "enhanced_level": 15,
    "skill_level": 15,
    "trace_point_level": 1,
    "initial_speed": 165.0,
    "normal_shield_owner_atk_pct": 0.115,
    "normal_shield_flat": 256.25,
    "normal_shield_duration_turns": 3.0,
    "shield_stack_cap_multiplier": 3.0,
    "cleanse_debuff_count": 1.0,
    "skill_shield_owner_atk_pct": 0.23,
    "skill_shield_flat": 512.5,
    "ultimate_shield_owner_atk_pct": 0.23,
    "ultimate_shield_flat": 512.5,
    "enhanced_owner_physical_multiplier": 3.75,
    "enhanced_bondmate_multiplier": 1.0,
    "enhanced_action_count": 2.0,
    "bondmate_attack_energy": 6.0,
    "bondmate_attack_souldragon_advance": 0.15,
    "battle_start_danheng_advance": 0.40,
    "attack_convert_scale": 0.15,
    "notes_cn": {
        "initial_speed": "龙灵初始速度。来自丹恒·腾荒天赋 141404 的第 5 个参数。不是行动延后。",
        "normal_shield": "龙灵普通行动护盾：丹恒攻击力百分比 + 固定值。",
        "enhanced_action": "龙灵强化行动：物理群攻取丹恒攻击力倍率，同袍属性附加伤害取同袍攻击力倍率。",
    },
}


def _param_values(row: dict[str, Any]) -> list[float]:
    out: list[float] = []
    for p in row.get("ParamList") or []:
        if isinstance(p, dict) and "Value" in p:
            try:
                out.append(float(p.get("Value")))
            except Exception:
                out.append(0.0)
    return out


def _load_skill_row(source: TBGDSource, skill_id: int, preferred_level: int | None = None) -> dict[str, Any] | None:
    rows = source.read_json("ExcelOutput/AvatarSkillConfig.json")
    matched = [r for r in rows if isinstance(r, dict) and int(r.get("SkillID", -1)) == int(skill_id)]
    if not matched:
        return None
    if preferred_level is not None:
        exact = [r for r in matched if int(r.get("Level", -1)) == int(preferred_level)]
        if exact:
            return exact[-1]
    # Fall back to highest available level; current combat pack binds Dan Heng PT
    # action params at max data level, so the summon template should use the same
    # max-level source unless the caller explicitly asks otherwise.
    return sorted(matched, key=lambda r: int(r.get("Level", 0)))[-1]


def _load_skill_tree_point(source: TBGDSource, point_id: int, preferred_level: int | None = 1) -> dict[str, Any] | None:
    rows = source.read_json("ExcelOutput/AvatarSkillTreeConfig.json")
    matched = [r for r in rows if isinstance(r, dict) and int(r.get("PointID", -1)) == int(point_id)]
    if not matched:
        return None
    if preferred_level is not None:
        exact = [r for r in matched if int(r.get("Level", -1)) == int(preferred_level)]
        if exact:
            return exact[-1]
    return sorted(matched, key=lambda r: int(r.get("Level", 0)))[-1]



def _lowered_preview(source: TBGDSource, ability_name: str, *, max_depth: int = 5) -> dict[str, Any]:
    ability_file = source.read_json("Config/ConfigAbility/Avatar/Avatar_DanHengPT_00_Ability.json")
    idx = ability_index(ability_file)
    summary = summarize_ability_chain(idx, ability_name, max_depth=max_depth, max_lowered=320, max_nodes=16000)
    return summary


def _source_nodes(items: list[dict[str, Any]], limit: int = 16) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "type": it.get("type"),
            "source_node_type": it.get("source_node_type"),
            "source_path": it.get("source_path"),
            "status_id": it.get("status_id"),
            "target_policy": it.get("target_policy"),
            "ability_name": it.get("ability_name"),
            "action_id": it.get("action_id"),
        })
        if len(out) >= limit:
            break
    return out


def _graph_cleanse_effect(t: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    lowered = summary.get("lowered_preview") or []
    dispel_nodes = [x for x in lowered if isinstance(x, dict) and x.get("type") == "dispel_status"]
    eff = _cleanse_effect(t)
    eff.update({
        "source_template": "souldragon_tbgd_action_graph",
        "source_ability": summary.get("entry_ability"),
        "source_graph_nodes": _source_nodes(dispel_nodes, 4),
        "cn": "由 TBGD 龙灵插入行动图中的 DispelStatus 推导：龙灵行动驱散我方负面效果。",
    })
    return eff


def _graph_shield_effect(t: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    lowered = summary.get("lowered_preview") or []
    shield_nodes = [x for x in lowered if isinstance(x, dict) and (
        x.get("type") == "include_task_list_template" and str(x.get("template_id")) in {"DanHengPT_BE_AddShield", "DanHengPT_AddShield", "DanHengPT_Skill03_AddShield"}
        or x.get("type") == "add_status" and str(x.get("status_id")) == "MAvatar_DanHengPT_00_Shield"
    )]
    eff = _shield_effect(t)
    eff.update({
        "source_template": "souldragon_tbgd_action_graph",
        "source_ability": summary.get("entry_ability"),
        "source_graph_nodes": _source_nodes(shield_nodes, 8),
        "cn": "由 TBGD 龙灵插入行动图中的 DanHengPT_BE_AddShield 推导：龙灵行动后给全队上护盾。",
    })
    return eff


def _graph_insert_physical_packets(t: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    lowered = summary.get("lowered_preview") or []
    # InsertAttack graph contains four DamageByAttackProperty physical hit nodes
    # with HitSplitRatio=0.25.  Keep them as four packets instead of collapsing
    # them into a single 1.0 packet, so hit count/toughness/trace can match the
    # original action graph.
    raw = []
    for x in lowered:
        if not isinstance(x, dict) or x.get("type") != "damage_packet":
            continue
        if x.get("source_node_type") != "RPG.GameCore.DamageByAttackProperty":
            continue
        if str(x.get("damage_type") or "").lower() != "physical":
            continue
        if str(x.get("attack_type") or "").lower() != "insert":
            continue
        raw.append(x)
    packets: list[dict[str, Any]] = []
    total_mult = float(t.get("enhanced_owner_physical_multiplier", 1.0))
    total_toughness = float(t.get("enhanced_toughness_reduction", 60.0))
    for i, x in enumerate(raw[:4], start=1):
        split = x.get("hit_split_ratio_expr")
        try:
            split_f = float(split)
        except Exception:
            split_f = 1.0 / max(1, min(4, len(raw) or 4))
        packets.append({
            "id": f"souldragon_graph_physical_hit_{i}",
            "element": "physical",
            "damage_type": "follow_up_damage",
            "attack_type": "Insert",
            "target_policy": "all_enemies",
            "scaling_stat": "owner.atk",
            "multiplier": total_mult * split_f,
            "toughness_reduction": total_toughness * split_f,
            "can_crit": True,
            "source_template": "souldragon_tbgd_action_graph",
            "source_ability": summary.get("entry_ability"),
            "source_node_type": x.get("source_node_type"),
            "source_path": x.get("source_path"),
            "source_dynamic_expr": {
                "damage": ((x.get("scaling") or {}).get("multiplier_expr") if isinstance(x.get("scaling"), dict) else None),
                "toughness": ((x.get("toughness") or {}).get("toughness_reduction_expr") if isinstance(x.get("toughness"), dict) else None),
                "hit_split_ratio": split,
            },
            "cn": "由 TBGD BE_InsertAttack 图中的 4 个物理 Insert 命中节点推导。",
        })
    if packets:
        return packets
    return [{
        "id": "souldragon_graph_physical_hit_1",
        "element": "physical",
        "damage_type": "follow_up_damage",
        "attack_type": "Insert",
        "target_policy": "all_enemies",
        "scaling_stat": "owner.atk",
        "multiplier": total_mult,
        "toughness_reduction": total_toughness,
        "can_crit": True,
        "source_template": "souldragon_tbgd_action_graph_fallback_no_packet_nodes",
    }]


def _graph_bondmate_packet(t: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    lowered = summary.get("lowered_preview") or []
    pursued = [x for x in lowered if isinstance(x, dict) and x.get("type") == "damage_packet" and x.get("source_node_type") == "RPG.GameCore.DamageByAttackProperty" and str(x.get("attack_type") or "").lower() == "pursued" and x.get("damage_type") is None]
    # There are several Pursued nodes in the graph: some are conditional/rank or
    # extra-hit branches.  For the base 0-eidolon route, keep the all-enemy owner
    # add-damage node as the graph source while preserving the existing semantic
    # target/scaling as bondmate.element + bondmate.atk.
    all_enemy = [x for x in pursued if x.get("target_policy") == "all_enemies"]
    src = (all_enemy or pursued or [{}])[0]
    return {
        "id": "souldragon_graph_bondmate_additional",
        "element": "bondmate.element",
        "damage_type": "additional_damage",
        "attack_type": "Pursued",
        "target_policy": "all_enemies",
        "scaling_stat": "bondmate.atk",
        "multiplier": float(t.get("enhanced_bondmate_multiplier", 1.0)),
        "can_crit": False,
        "source_template": "souldragon_tbgd_action_graph",
        "source_ability": summary.get("entry_ability"),
        "source_node_type": src.get("source_node_type"),
        "source_path": src.get("source_path"),
        "source_dynamic_expr": ((src.get("scaling") or {}).get("multiplier_expr") if isinstance(src.get("scaling"), dict) else None),
        "cn": "由 TBGD BE_InsertAttack 图中的 Pursued 附加伤害节点推导；元素与攻击力跟随【同袍】。",
    }


def souldragon_graph_actions(source: TBGDSource, template: dict[str, Any]) -> dict[str, Any]:
    shield_summary = _lowered_preview(source, "Avatar_DanHengPT_00_BE_InsertShield_Phase01")
    attack_summary = _lowered_preview(source, "Avatar_DanHengPT_00_BE_InsertAttack_Phase01")
    passive_summary = _lowered_preview(source, "Avatar_DanHengPT_00_BE_PassiveSkill", max_depth=3)
    t = {**DEFAULT_TEMPLATE, **template}
    normal_effects = [_graph_cleanse_effect(t, shield_summary), _graph_shield_effect(t, shield_summary)]
    enhanced_effects = [_graph_cleanse_effect(t, attack_summary), _graph_shield_effect(t, attack_summary)]
    enhanced_packets = _graph_insert_physical_packets(t, attack_summary) + [_graph_bondmate_packet(t, attack_summary)]
    normal = {
        "id": "normal",
        "action_type": "summon",
        "tags": ["souldragon_action", "summon_action", "consumes_regular_action", "support", "tbgd_graph_derived_summon_action_ir"],
        "target_policy": "all_allies",
        "damage_packets": [],
        "effects": normal_effects,
        "source_ability_graph": {
            "entry_ability": "Avatar_DanHengPT_00_BE_InsertShield_Phase01",
            "ordered_abilities": shield_summary.get("ordered_abilities"),
            "lowering_coverage": shield_summary.get("lowering_coverage"),
        },
    }
    enhanced = {
        "id": "enhanced",
        "action_type": "summon",
        "tags": ["souldragon_action", "souldragon_enhanced", "summon_action", "followup_damage", "attack", "consumes_regular_action", "tbgd_graph_derived_summon_action_ir"],
        "target_policy": "all_enemies",
        "effects_before_damage": enhanced_effects,
        "damage_packets": enhanced_packets,
        "effects": [],
        "source_ability_graph": {
            "entry_ability": "Avatar_DanHengPT_00_BE_InsertAttack_Phase01",
            "ordered_abilities": attack_summary.get("ordered_abilities"),
            "lowering_coverage": attack_summary.get("lowering_coverage"),
        },
    }
    return {
        "normal": normal,
        "enhanced": enhanced,
        "graph_evidence": {
            "passive_router": {
                "entry_ability": "Avatar_DanHengPT_00_BE_PassiveSkill",
                "lowering_coverage": passive_summary.get("lowering_coverage"),
                "enqueue_actions": [x for x in passive_summary.get("lowered_preview", []) if isinstance(x, dict) and x.get("type") == "enqueue_action"],
                "cn": "BEModifier 的 OnPhase1 根据 BoostEnergy 状态选择插入强化攻击，否则插入普通护盾行动。",
            },
            "normal_source": {
                "entry_ability": "Avatar_DanHengPT_00_BE_InsertShield_Phase01",
                "lowering_coverage": shield_summary.get("lowering_coverage"),
                "unlowered_combat_node_types": shield_summary.get("unlowered_combat_node_types"),
            },
            "enhanced_source": {
                "entry_ability": "Avatar_DanHengPT_00_BE_InsertAttack_Phase01",
                "lowering_coverage": attack_summary.get("lowering_coverage"),
                "unlowered_combat_node_types": attack_summary.get("unlowered_combat_node_types"),
                "physical_hit_packet_count": len([p for p in enhanced_packets if str(p.get("element")) == "physical"]),
            },
        },
    }

def derive_souldragon_action_template(tbgd_source: str | Path | TBGDSource, *, normal_level: int | None = None, enhanced_level: int | None = None) -> dict[str, Any]:
    source = tbgd_source if isinstance(tbgd_source, TBGDSource) else TBGDSource.open(tbgd_source)
    normal = _load_skill_row(source, 141404, preferred_level=normal_level)
    enhanced = _load_skill_row(source, 141403, preferred_level=enhanced_level)
    skill = _load_skill_row(source, 141402, preferred_level=normal_level)
    trace_b = _load_skill_tree_point(source, 1414102, preferred_level=1)
    trace_attack_convert = _load_skill_tree_point(source, 1414101, preferred_level=1)
    template = dict(DEFAULT_TEMPLATE)
    template["source"] = "TurnBasedGameData.ExcelOutput.AvatarSkillConfig"
    template["normal_level"] = int(normal.get("Level", normal_level or DEFAULT_TEMPLATE["normal_level"])) if normal else (normal_level or DEFAULT_TEMPLATE["normal_level"])
    template["enhanced_level"] = int(enhanced.get("Level", enhanced_level or DEFAULT_TEMPLATE["enhanced_level"])) if enhanced else (enhanced_level or DEFAULT_TEMPLATE["enhanced_level"])
    template["skill_level"] = int(skill.get("Level", template["normal_level"])) if skill else template["normal_level"]
    normal_params = _param_values(normal or {})
    enhanced_params = _param_values(enhanced or {})
    skill_params = _param_values(skill or {})
    trace_b_params = _param_values(trace_b or {})
    trace_attack_convert_params = _param_values(trace_attack_convert or {})
    template["raw_param_lists"] = {
        "141404": normal_params,
        "141403": enhanced_params,
        "141402": skill_params,
        "1414102": trace_b_params,
        "1414101": trace_attack_convert_params,
    }
    # 141404 max data level: [shield_atk_pct, shield_flat, duration, cap, speed, cleanse]
    if len(normal_params) >= 5:
        template["normal_shield_owner_atk_pct"] = float(normal_params[0])
        template["normal_shield_flat"] = float(normal_params[1])
        template["normal_shield_duration_turns"] = float(normal_params[2]) if len(normal_params) > 2 else template["normal_shield_duration_turns"]
        template["shield_stack_cap_multiplier"] = float(normal_params[3]) if len(normal_params) > 3 else template["shield_stack_cap_multiplier"]
        template["initial_speed"] = float(normal_params[4])
        template["cleanse_debuff_count"] = float(normal_params[5]) if len(normal_params) > 5 else template["cleanse_debuff_count"]
    # 141402 skill shield: [atk_pct, flat, duration, cap]
    if len(skill_params) >= 4:
        template["skill_shield_owner_atk_pct"] = float(skill_params[0])
        template["skill_shield_flat"] = float(skill_params[1])
        template["shield_stack_cap_multiplier"] = float(skill_params[3])
    # 141403 ultimate/enhanced: [ult_dmg, dragon_phys, enhanced_count, shield_pct, shield_flat, duration, cap, bondmate_add]
    if len(enhanced_params) >= 8:
        template["enhanced_owner_physical_multiplier"] = float(enhanced_params[1])
        template["enhanced_bondmate_multiplier"] = float(enhanced_params[7])
        template["enhanced_action_count"] = float(enhanced_params[2])
        template["ultimate_shield_owner_atk_pct"] = float(enhanced_params[3])
        template["ultimate_shield_flat"] = float(enhanced_params[4])
        template["shield_stack_cap_multiplier"] = float(enhanced_params[6])
    if len(trace_b_params) >= 3:
        template["battle_start_danheng_advance"] = float(trace_b_params[0])
        template["bondmate_attack_energy"] = float(trace_b_params[1])
        template["bondmate_attack_souldragon_advance"] = float(trace_b_params[2])
    if trace_attack_convert_params:
        template["attack_convert_scale"] = float(trace_attack_convert_params[0])
    template["derived_actions"] = souldragon_template_actions(template)
    try:
        graph = souldragon_graph_actions(source, template)
        template["graph_derived_actions"] = {"normal": graph["normal"], "enhanced": graph["enhanced"]}
        template["graph_lowering_evidence"] = graph["graph_evidence"]
        actions = template["graph_derived_actions"]
        source_label = "tbgd_action_graph_lowered_souldragon"
    except Exception as exc:
        template["graph_lowering_error"] = str(exc)
        actions = template["derived_actions"]
        source_label = "data_derived_souldragon_template_graph_lowering_failed"
    template["summon_action_ir"] = {
        "format": "hsr_summon_action_ir",
        "version": "v0.3",
        "source": source_label,
        "owner_ref": "owner",
        "attached_ref": "bondmate",
        "actions": actions,
        "lifecycle": {
            "remove_when_owner_defeated": True,
            "remove_when_attached_target_defeated": True,
            "enhanced_action_count": template.get("enhanced_action_count"),
        },
        "cn": "龙灵行动优先由 TBGD BE_InsertShield/BE_InsertAttack 能力图 lower 得到；参数仍来自 AvatarSkillConfig。",
    }
    return template


def _shield_effect(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "modify_shield",
        "target": "all_allies",
        "source": "owner",
        "source_stat": "atk",
        "source_stat_pct": float(t["normal_shield_owner_atk_pct"]),
        "amount": float(t["normal_shield_flat"]),
        "shield_cap_source": "dan_heng_skill_shield",
        "shield_cap_source_stat_pct": float(t.get("skill_shield_owner_atk_pct", t["normal_shield_owner_atk_pct"])),
        "shield_cap_flat": float(t.get("skill_shield_flat", t["normal_shield_flat"])),
        "shield_cap_multiplier": float(t.get("shield_stack_cap_multiplier", 3.0)),
        "duration_turns": float(t.get("normal_shield_duration_turns", 3.0)),
        "source_template": "souldragon_action_template",
    }


def _cleanse_effect(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "cleanse_debuffs",
        "target": "all_allies",
        "count": int(float(t.get("cleanse_debuff_count", 1))),
        "source_template": "souldragon_action_template",
    }


def souldragon_template_actions(template: dict[str, Any] | None = None) -> dict[str, Any]:
    t = {**DEFAULT_TEMPLATE, **(template or {})}
    common_effects = [_cleanse_effect(t), _shield_effect(t)]
    return {
        "normal": {
            "id": "normal",
            "action_type": "summon",
            "tags": ["souldragon_action", "summon_action", "consumes_regular_action", "support", "data_derived_summon_action_ir"],
            "target_policy": "all_allies",
            "damage_packets": [],
            "effects": common_effects,
        },
        "enhanced": {
            "id": "enhanced",
            "action_type": "summon",
            "tags": ["souldragon_action", "souldragon_enhanced", "summon_action", "followup_damage", "attack", "consumes_regular_action", "data_derived_summon_action_ir"],
            "target_policy": "all_enemies",
            "effects_before_damage": common_effects,
            "damage_packets": [
                {
                    "id": "souldragon_enhanced_physical",
                    "element": "physical",
                    "damage_type": "follow_up_damage",
                    "target_policy": "all_enemies",
                    "scaling_stat": "owner.atk",
                    "multiplier": float(t["enhanced_owner_physical_multiplier"]),
                    "can_crit": True,
                    "source_template": "souldragon_action_template",
                },
                {
                    "id": "souldragon_enhanced_bondmate",
                    "element": "bondmate.element",
                    "damage_type": "additional_damage",
                    "target_policy": "all_enemies",
                    "scaling_stat": "bondmate.atk",
                    "multiplier": float(t["enhanced_bondmate_multiplier"]),
                    "can_crit": False,
                    "source_template": "souldragon_action_template",
                },
            ],
            "effects": [],
        },
    }

def load_souldragon_action_template(path: str | Path | None = None) -> dict[str, Any]:
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    candidates.append(Path(__file__).with_name("data") / "souldragon_action_template.json")
    for p in candidates:
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    if "derived_actions" not in data:
                        data["derived_actions"] = souldragon_template_actions(data)
                    return {**DEFAULT_TEMPLATE, **data}
        except Exception:
            continue
    data = dict(DEFAULT_TEMPLATE)
    data["derived_actions"] = souldragon_template_actions(data)
    return data


def write_souldragon_action_template(tbgd_source: str | Path | TBGDSource, output_dir: str | Path) -> dict[str, Any]:
    template = derive_souldragon_action_template(tbgd_source)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "souldragon_action_template.json").write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 龙灵行动模板（数据派生 fallback）",
        "",
        "这个文件把丹恒·腾荒龙灵 fallback 行动从运行时代码常量中抽出来，改成由 TurnBasedGameData 参数表生成的模板。",
        "",
        f"- 龙灵初始速度：{template['initial_speed']}",
        f"- 普通行动护盾：{template['normal_shield_owner_atk_pct']} × 丹恒攻击力 + {template['normal_shield_flat']}",
        f"- 强化物理伤害：{template['enhanced_owner_physical_multiplier']} × 丹恒攻击力",
        f"- 强化同袍附加伤害：{template['enhanced_bondmate_multiplier']} × 同袍攻击力",
        f"- 同袍固定攻击力加成 AttackConvert：{template.get('attack_convert_scale', 0.15)} × 丹恒当前攻击力，非快照",
        "",
        "当前模板已优先从 TBGD 的 BE_InsertShield / BE_InsertAttack 能力图生成 summon_action_ir；如果图解析失败才回退到参数派生模板。",
    ]
    (out / "souldragon_action_template_cn.md").write_text("\n".join(lines), encoding="utf-8")
    return template
