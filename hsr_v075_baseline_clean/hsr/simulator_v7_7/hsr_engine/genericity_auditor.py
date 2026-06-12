from __future__ import annotations

"""Audit where current implementation is generic vs fallback/special-case.

The goal is not to fail the simulator.  It produces a refactor checklist so
future work does not accidentally turn character-specific fallbacks into core
combat rules.
"""

from pathlib import Path
from typing import Any
import json
import re

GENERICITY_ITEMS: list[dict[str, Any]] = [
    {
        "area": "Souldragon fallback",
        "zh": "龙灵兜底行动模板",
        "current_state": "运行时遇到 souldragon 且没有 actions 时，会补一套默认普通/强化行动。",
        "genericity": "semi_generic_character_fallback",
        "risk": "丹恒专用知识留在 runtime，后续如果其他召唤物也走 fallback，容易扩散硬编码。",
        "target_design": "从 TBGD 的召唤/附属单位 Action Graph 生成 SummonActionIR；fallback 只作为验证兜底。",
        "priority": "high",
    },
    {
        "area": "AttackConvert",
        "zh": "同袍固定攻击力加成",
        "current_state": "已经从 audit-only 改成 derived flat ATK modifier。",
        "genericity": "data_driven_derived_property_with_character_context",
        "risk": "如果 source/target/refresh policy 写死，会限制其他 derived property。",
        "target_design": "derived_property IR：source、target、value_expr、bucket、refresh_policy 全部显式化。",
        "priority": "high",
    },
    {
        "area": "RandomConfig lowering",
        "zh": "随机分支配置转换",
        "current_state": "支持常见字段 RandomCount/RandomUnique/RandomMaskKey/TriggerCustomString 等。",
        "genericity": "generic_control_flow_with_source_shape_adapters",
        "risk": "遇到少见字段时仍可能需要补 source shape。",
        "target_design": "所有随机/概率节点统一 lower 成 random_choice / random_select / chance_gate。",
        "priority": "medium",
    },
    {
        "area": "generated debuff lowering",
        "zh": "数据库负面状态节点自动转换",
        "current_state": "AddModifier.Chance、ByRandomChance 分支能转成 effect_hit gate。",
        "genericity": "partially_generic_status_application",
        "risk": "复杂 target filter / condition composition 还可能漏接。",
        "target_design": "所有 add debuff 节点统一输出 add_status + status_application_gate + target_selector。",
        "priority": "medium",
    },
    {
        "area": "break formula",
        "zh": "击破/超击破公式",
        "current_state": "基础公式与击破后元素效果可执行。",
        "genericity": "generic_formula_module_needs_calibration_report",
        "risk": "系数如果没有报告化/对照化，后续难定位偏差。",
        "target_design": "break_formula_audit 输出公式项、数据库来源、待实战校准项。",
        "priority": "high",
    },
    {
        "area": "enemy mechanisms",
        "zh": "敌人机制",
        "current_state": "已有模型包敌人数据和部分历史实现，但缺统一盘点报告。",
        "genericity": "inventory_missing",
        "risk": "重复做或误判没做；真实流程验证时不知道哪个机制缺。",
        "target_design": "enemy_mechanism_inventory：列出敌人、技能、状态、触发、召唤/阶段/随机/击破关键词覆盖。",
        "priority": "high",
    },
]


def audit_code_signals(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    files = [root / "hsr_simulator_prototype_v7_7.py"] + sorted((root / "hsr_engine").glob("*.py"))
    signals: dict[str, list[str]] = {"fallback": [], "hardcoded_souldragon": [], "attack_convert": [], "random_config": []}
    for p in files:
        if not p.exists():
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            low = line.lower()
            if "fallback" in low:
                signals["fallback"].append(f"{p.relative_to(root)}:{i}:{line.strip()[:180]}")
            if "souldragon" in low:
                signals["hardcoded_souldragon"].append(f"{p.relative_to(root)}:{i}:{line.strip()[:180]}")
            if "attackconvert" in line:
                signals["attack_convert"].append(f"{p.relative_to(root)}:{i}:{line.strip()[:180]}")
            if "RandomConfig" in line or "random_choice" in line:
                signals["random_config"].append(f"{p.relative_to(root)}:{i}:{line.strip()[:180]}")
    return {k: v[:80] for k, v in signals.items()}


def genericity_audit_report(simulator_root: str | Path) -> dict[str, Any]:
    return {
        "format": "hsr_genericity_audit_report",
        "version": "v0.1",
        "summary_cn": "把当前实现里偏通用、半通用、角色专用兜底的地方分开，避免后续补丁堆积。",
        "items": GENERICITY_ITEMS,
        "code_signals": audit_code_signals(simulator_root),
    }


def write_genericity_audit(simulator_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = genericity_audit_report(simulator_root)
    (out / "genericity_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 通用性整改清单", ""]
    for item in report["items"]:
        lines.append(f"## {item['area']}：{item['zh']}")
        lines.append(f"- 当前状态：{item['current_state']}")
        lines.append(f"- 通用性分类：`{item['genericity']}`")
        lines.append(f"- 风险：{item['risk']}")
        lines.append(f"- 目标设计：{item['target_design']}")
        lines.append(f"- 优先级：{item['priority']}")
        lines.append("")
    (out / "genericity_audit_cn.md").write_text("\n".join(lines), encoding="utf-8")
    return report
