from __future__ import annotations

"""Current-team role mechanism audit.

This report is deliberately separate from the battle kernel.  It answers a
practical question before we build a solver: which public/TBGD-described role
mechanics are represented in the model pack, which ones are executable now, and
which ones still need runtime/lowering work.
"""

from pathlib import Path
from typing import Any
import json
import re

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

TEAM_CHARACTER_FILES = {
    "seele": "models/characters/seele.yaml",
    "sparkle": "models/characters/sparkle.yaml",
    "tribbie": "models/characters/tribbie.yaml",
    "dan_heng_permansor_terrae": "models/characters/dan_heng_permansor_terrae.yaml",
}

# Public kit reference anchors used for the manual checklist.  Keep source names
# human-readable here; the json report is an evidence index, not a citation engine.
PUBLIC_REFERENCE_NOTES = {
    "seele": "Prydwen Seele kit, profile last updated 31/May/2026: skill speed, Novaflare auto-skill, Resurgence, Amplification, Nightshade, Lacerate, Rippling Waves, E1/E2/E3.",
    "sparkle": "Prydwen Sparkle kit, profile last updated 31/May/2026: Dreamdiver 2-turn CRIT DMG + 50% AA, Ultimate SP overflow/Cipher, Figment, A2/A4/A6, E1.",
    "tribbie": "Prydwen Tribbie kit, profile last updated 31/May/2026: Numinosity, Zone additional damage, Talent FUA, A2/A4/A6, E1 true damage.",
    "dan_heng_permansor_terrae": "Prydwen Dan Heng • Permansor Terrae kit, profile last updated 31/May/2026: Bondmate, Souldragon, shields, enhanced action, Sylvanity, Sublimity, Empyreanity.",
}

EXPECTED_MECHANISMS: dict[str, list[dict[str, Any]]] = {
    "seele": [
        {"id": "skill_spd_buff", "zh": "战技速度提升，可叠层取决于星魂", "must_have": ["seele_skill_spd_buff", "speed_pct_delta", "max_stacks_at_e2_or_above"]},
        {"id": "novaflare_auto_skill", "zh": "低血线目标触发自动战技；不耗点不回基础能量", "must_have": ["seele_novaflare_auto_skill", "does_not_consume_skill_point", "does_not_grant_base_energy"]},
        {"id": "resurgence", "zh": "击杀触发增幅与额外回合；额外回合不继续套娃再现", "must_have": ["seele_resurgence_trigger", "enqueue_extra_turn", "context.extra_turn_type != resurgence"]},
        {"id": "amplification_lacerate", "zh": "增幅状态与量子抗性穿透", "must_have": ["seele_amplification", "quantum_res_pen"]},
        {"id": "nightshade", "zh": "击杀后的增伤叠层", "must_have": ["seele_nightshade_dmg_bonus", "max_stacks"]},
        {"id": "rippling_waves", "zh": "普攻后自身行动提前 20%", "must_have": ["seele_rippling_waves_trigger", "advance_percent", "0.2"]},
        {"id": "eidolon_1_2_3", "zh": "当前三星魂：E1/E2/E3 生效", "must_have": ["active_for_user_case", "skill_spd_buff_max_stacks", "talent_level_add"]},
    ],
    "sparkle": [
        {"id": "dreamdiver", "zh": "战技暴伤加成 2 回合并拉条 50%；对自己不拉条", "must_have": ["dreamdiver_crit_dmg_boost", "0.24 * sparkle.current_crit_dmg + 0.45", "advance_percent", "0.5", "target_turns", "2"]},
        {"id": "ultimate_sp_overflow_cipher", "zh": "终结技回复 6 点，溢出记录到 10，并赋予 Cipher", "must_have": ["overflow_record", "max_recorded_overflow", "10", "cipher"]},
        {"id": "figment", "zh": "队友耗点叠加敌方易伤，最高 3 层", "must_have": ["sparkle_talent_figment_on_sp_consumption", "figment", "max_stacks", "3"]},
        {"id": "almanac", "zh": "行迹 A2：普攻额外回能 10；持战技暴伤者耗点时花火回能 1", "must_have": ["trace_extra_energy", "sparkle_almanac_dreamdiver_holder_sp_energy", "amount", "1"]},
        {"id": "artificial_flower", "zh": "行迹 A4：单回合耗 3 点后下次战技不耗点", "must_have": ["sparkle_next_skill_free", "sparkle_artificial_flower"]},
        {"id": "nocturne", "zh": "行迹 A6：全队攻击力 45%；持战技暴伤者全属性抗穿 10%", "must_have": ["sparkle_nocturne_team_atk_buff", "atk_pct", "0.45", "all_type_res_pen", "0.1"]},
        {"id": "eidolon_1", "zh": "一星魂：Cipher 目标攻击力 40%，开战/战技后自身速度 15%", "must_have": ["active_for_user_case", "eidolon_1_cipher_atk_buff", "eidolon_1_spd_buff", "sparkle_e1_battle_start_spd_buff"]},
    ],
    "tribbie": [
        {"id": "numinosity", "zh": "战技/秘技获得 Numinosity，全队全属性抗穿", "must_have": ["numinosity", "all_type_res_pen_at_skill_10", "0.24"]},
        {"id": "ultimate_zone", "zh": "终结技造成量子群伤并展开领域；领域易伤与持续时间", "must_have": ["tribbie_zone_guess_who_lives_here", "enemy_dmg_taken_delta_at_ult_10", "0.3", "owner_turn_start_decrement", "2"]},
        {"id": "zone_additional_damage", "zh": "领域期间队友攻击后按命中目标数造成量子附加伤害", "must_have": ["zone_additional_damage", "highest_hp_among_hit_targets", "0.12"]},
        {"id": "talent_followup", "zh": "其他队友施放终结技后，缇宝每人一次触发群体追击，缇宝终结技后重置", "must_have": ["tribbie_talent_followup_busy_as_tribbie", "after_other_ally_uses_ultimate", "per_trigger_actor", "reset_trigger_usage"]},
        {"id": "a2_dmg_stack", "zh": "行迹 A2：天赋追击后自身增伤 72%，最多 3 层", "must_have": ["tribbie_a2_talent_dmg_bonus", "dmg_bonus", "0.72", "max_stacks", "3"]},
        {"id": "a4_zone_hp", "zh": "行迹 A4：领域期间最大生命按全队生命总和提高", "must_have": ["tribbie_a4_zone_hp_boost", "max_hp_from_team_hp_pct", "0.09"]},
        {"id": "a6_energy", "zh": "行迹 A6：开战回能 30；队友攻击后按命中目标数回能", "must_have": ["tribbie_a6_battle_start_energy", "amount", "30", "energy_per_hit", "1.5"]},
        {"id": "eidolon_1_true_damage", "zh": "一星魂：领域附加伤害后造成该次攻击总伤害 24% 的真实伤害", "must_have": ["eidolon_1_rite_of_sugar_scoop", "after_tribbie_zone_additional_damage", "0.24"]},
    ],
    "dan_heng_permansor_terrae": [
        {"id": "bondmate", "zh": "战技指定同袍并唯一化，召唤龙灵", "must_have": ["bondmate", "only_latest_skill_target", "summon_souldragon_for_target"]},
        {"id": "attack_convert", "zh": "同袍获得丹恒当前攻击力 15% 的实时固定攻击加成", "must_have": ["delta_formula_from_bonus_ability", "0.15 * dan_heng_permansor_terrae.atk"]},
        {"id": "souldragon_normal", "zh": "龙灵普通行动：全队驱散并提供护盾", "must_have": ["normal_action", "dispel_debuff", "provide_shield"]},
        {"id": "souldragon_enhanced", "zh": "终结技强化龙灵：物理追击 + 同袍属性附加伤害", "must_have": ["enhanced_state", "follow_up_attack", "souldragon_enhanced_bondmate_additional_damage"]},
        {"id": "sylvanity", "zh": "开战丹恒拉条；同袍攻击后丹恒回能且龙灵拉条", "must_have": ["sylvanity_battle_start_action_advance", "sylvanity_bondmate_attack", "advance_percent", "0.15"]},
        {"id": "sublimity", "zh": "龙灵行动追加最低护盾目标护盾；强化龙灵追加最高血敌人同袍属性伤害", "must_have": ["extra_shield_and_bondmate_damage", "ally_with_lowest_current_shield", "enemy_highest_current_hp"]},
    ],
}


def _load_yaml(path: Path) -> Any:
    if yaml is None:  # pragma: no cover
        raise RuntimeError("PyYAML is required")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _flatten_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).lower()


def _token_present(text: str, token: str) -> bool:
    return str(token).lower() in text


def audit_character_mechanisms(model_pack_root: str | Path) -> dict[str, Any]:
    root = Path(model_pack_root)
    characters: dict[str, Any] = {}
    totals = {"mechanisms": 0, "present": 0, "partial": 0, "missing": 0}
    for cid, rel in TEAM_CHARACTER_FILES.items():
        path = root / rel
        if not path.exists():
            characters[cid] = {"ok": False, "path": rel, "error": "missing_character_file", "mechanisms": []}
            totals["missing"] += len(EXPECTED_MECHANISMS.get(cid, []))
            totals["mechanisms"] += len(EXPECTED_MECHANISMS.get(cid, []))
            continue
        data = _load_yaml(path) or {}
        text = _flatten_text(data)
        rows = []
        for item in EXPECTED_MECHANISMS.get(cid, []):
            tokens = list(item.get("must_have") or [])
            present_tokens = [t for t in tokens if _token_present(text, str(t))]
            missing_tokens = [t for t in tokens if t not in present_tokens]
            if not missing_tokens:
                state = "present"
            elif present_tokens:
                state = "partial"
            else:
                state = "missing"
            totals["mechanisms"] += 1
            totals[state] += 1
            rows.append({
                "id": item["id"],
                "zh": item["zh"],
                "state": state,
                "present_tokens": present_tokens,
                "missing_tokens": missing_tokens,
            })
        characters[cid] = {
            "ok": all(r["state"] == "present" for r in rows),
            "path": rel,
            "public_reference_note": PUBLIC_REFERENCE_NOTES.get(cid),
            "mechanisms": rows,
        }
    high_priority_missing = []
    for cid, info in characters.items():
        for row in info.get("mechanisms", []):
            if row["state"] != "present":
                high_priority_missing.append({"character": cid, **row})
    return {
        "format": "hsr_current_team_character_mechanism_audit",
        "version": "v0.2",
        "scope": "current_team_role_mechanisms_before_solver",
        "model_pack_root": str(root),
        "summary": {
            **totals,
            "ok": totals["missing"] == 0 and totals["partial"] == 0,
            "coverage": 0 if totals["mechanisms"] == 0 else round(totals["present"] / totals["mechanisms"], 4),
        },
        "characters": characters,
        "high_priority_missing_or_partial": high_priority_missing,
        "notes_cn": [
            "这个审计只判断当前模型包是否显式表达机制，不等于全部 runtime 行为已经与真机完全对齐。",
            "present 表示模型包层已经有对应语义；runtime 可执行性需要结合具体 effect 类型和回归路线继续验证。",
            "v0.44 起，sparkle_next_skill_free 的下一次战技 0 耗点已接入通用 cost override runtime hook。",
            "v0.44 起，max_hp_from_team_hp_pct 已按 HPAddedRatio 类资源副作用执行并可在移除状态时回退。",
            "骑士三只作为验收路线之一；这里的优先级按通用角色机制建设排序。",
        ],
    }


def write_character_mechanism_audit(model_pack_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = audit_character_mechanisms(model_pack_root)
    (out / "character_mechanism_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 当前队伍四角色机制完整性审计", ""]
    s = report["summary"]
    lines.append(f"- 覆盖率：{s['present']}/{s['mechanisms']} = {s['coverage']}")
    lines.append(f"- 完整：{s['present']}，部分：{s['partial']}，缺失：{s['missing']}")
    lines.append("")
    for cid, info in report["characters"].items():
        lines.append(f"## {cid}")
        lines.append(f"- 来源说明：{info.get('public_reference_note')}")
        for row in info.get("mechanisms", []):
            mark = "✅" if row["state"] == "present" else ("⚠️" if row["state"] == "partial" else "❌")
            lines.append(f"- {mark} `{row['id']}`：{row['zh']}（{row['state']}）")
            if row.get("missing_tokens"):
                miss = ", ".join(f"`{x}`" for x in row["missing_tokens"])
                lines.append(f"  - 缺少证据 token：{miss}")
        lines.append("")
    lines.append("## 说明")
    for note in report.get("notes_cn", []):
        lines.append(f"- {note}")
    (out / "character_mechanism_audit_cn.md").write_text("\n".join(lines), encoding="utf-8")
    return report
