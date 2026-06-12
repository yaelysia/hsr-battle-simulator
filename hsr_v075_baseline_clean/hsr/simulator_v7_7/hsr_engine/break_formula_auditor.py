from __future__ import annotations

"""Break-formula audit/reporting helper with Chinese explanations."""

from pathlib import Path
from typing import Any
import json

from .break_formula import (
    break_base_damage,
    element_break_multiplier,
    max_toughness_multiplier,
    break_dot_base_damage,
)

ELEMENTS = ["physical", "fire", "ice", "thunder", "wind", "quantum", "imaginary"]

CN_ELEMENT = {
    "physical": "物理",
    "fire": "火",
    "ice": "冰",
    "thunder": "雷",
    "wind": "风",
    "quantum": "量子",
    "imaginary": "虚数",
}

BREAK_EFFECT_CN = {
    "physical": "裂伤：按目标最大生命计算并受击破基数上限限制",
    "fire": "灼烧：击破后持续伤害",
    "ice": "冻结：阻止一次行动，解除时造成冻结解除伤害",
    "thunder": "触电：击破后持续伤害",
    "wind": "风化：击破后持续伤害，精英/Boss 初始层数更高",
    "quantum": "纠缠：行动延后并叠层，目标回合开始时结算延迟伤害",
    "imaginary": "禁锢：行动延后并降低速度，不产生击破后伤害",
}


def break_formula_audit_report(level: int = 80, max_toughness_values: list[int] | None = None) -> dict[str, Any]:
    mts = max_toughness_values or [30, 60, 90, 120, 150, 180]
    rows = []
    for e in ELEMENTS:
        rows.append({
            "element": e,
            "element_cn": CN_ELEMENT[e],
            "break_multiplier": element_break_multiplier(e),
            "aftermath_cn": BREAK_EFFECT_CN[e],
            "eats_atk": False,
            "eats_crit": False,
            "eats_normal_damage_bonus": False,
            "current_support": "base_formula_and_aftermath" if e != "imaginary" else "action_delay_speed_down_no_damage",
        })
    toughness_rows = [
        {"max_toughness": mt, "max_toughness_cn": f"最大韧性 {mt}", "multiplier": max_toughness_multiplier(mt)}
        for mt in mts
    ]
    dot_examples = []
    for kind in ["bleed", "burn", "shock", "wind_shear", "freeze_thaw", "entanglement"]:
        val, audit = break_dot_base_damage(kind, level=level, max_toughness=120, max_hp=100000, elite_or_boss=False, stacks=3 if kind in {"wind_shear", "entanglement"} else 1)
        dot_examples.append({"kind": kind, "base_damage_before_be_def_res": val, "audit": audit})
    return {
        "format": "hsr_break_formula_audit",
        "version": "v0.1",
        "summary_cn": "把击破/超击破/击破后元素效果拆成可核对表，避免只说 break_formula 这种内部名。",
        "level": level,
        "level_break_base_damage": break_base_damage(level),
        "core_boundaries_cn": [
            "击破/超击破不吃攻击力。",
            "击破/超击破不吃普通增伤。",
            "击破/超击破不吃双暴。",
            "普通击破、击破后 DoT/延迟伤害、超击破应走独立公式路径。",
        ],
        "element_rows": rows,
        "max_toughness_multiplier_rows": toughness_rows,
        "dot_or_delayed_base_examples": dot_examples,
        "needs_real_battle_calibration_cn": [
            "物理裂伤普通/精英/Boss 上限是否完全对齐当前版本。",
            "纠缠层数、攻击增层、结算时机是否与实战一致。",
            "冻结解除后的行动提前/延后边界。",
            "超击破来源、削韧值折算、独立增伤桶叠加。",
        ],
    }


def write_break_formula_audit(output_dir: str | Path, level: int = 80) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = break_formula_audit_report(level=level)
    (out / "break_formula_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 击破公式校准表", "", f"等级：{level}", f"等级击破基础值：{report['level_break_base_damage']}", "", "## 公式边界", ""]
    for x in report["core_boundaries_cn"]:
        lines.append(f"- {x}")
    lines.append("\n## 元素击破效果\n")
    for r in report["element_rows"]:
        lines.append(f"- {r['element_cn']} `{r['element']}`：倍率 {r['break_multiplier']}；{r['aftermath_cn']}；不吃攻击/普通增伤/双暴。")
    lines.append("\n## 最大韧性倍率示例\n")
    for r in report["max_toughness_multiplier_rows"]:
        lines.append(f"- {r['max_toughness_cn']}：{r['multiplier']}")
    (out / "break_formula_audit_cn.md").write_text("\n".join(lines), encoding="utf-8")
    return report
