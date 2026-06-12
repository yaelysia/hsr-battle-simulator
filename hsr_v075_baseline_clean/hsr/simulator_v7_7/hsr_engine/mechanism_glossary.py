from __future__ import annotations

"""Human-readable mechanism glossary for generated HSR combat artifacts.

This file is intentionally bilingual.  Internal compiler/runtime names remain in
English because they match TurnBasedGameData and source code, while the Chinese
fields explain what the term means in game-mechanism terms.
"""

from pathlib import Path
from typing import Any
import json

GLOSSARY: dict[str, dict[str, Any]] = {
    "RandomConfig": {
        "zh": "随机分支配置",
        "what_it_does": "数据库里表示“从多个候选分支里随机选一个或多个执行”的控制流节点。",
        "why_it_matters": "如果不处理它，模拟器可能会把所有随机分支都执行，导致状态、伤害或语音事件全部触发。",
        "current_policy": "运行时按确定性验证模式选择分支；真实路线可用 events 指定本次随机结果。",
        "example": "随机从 7 个分支里选 2 个；或一次随机选择某个 debuff 分支。",
    },
    "RandomSelectDynamicValue": {
        "zh": "随机选择动态值",
        "what_it_does": "从候选值里随机抽一个，保存成临时变量，后续效果继续引用这个值。",
        "why_it_matters": "它常用于随机目标、随机实体、随机数值。必须保证一次只选一个结果，而不是全部写入。",
        "current_policy": "未指定时取第一个候选；路线 events 可指定索引。",
    },
    "SetDynamicEntityParam": {
        "zh": "设置动态实体参数",
        "what_it_does": "把某个动态选择出来的角色/敌人/召唤物 id 记录下来，供后续效果使用。",
        "why_it_matters": "随机目标或临时目标选择后，后续 debuff/伤害需要知道作用到谁。",
        "current_policy": "记录到 runtime flags / selected entity audit，不直接产生伤害。",
    },
    "TriggerCustomString": {
        "zh": "触发自定义字符串事件",
        "what_it_does": "触发语音、文本、战斗事件字符串等非数值效果。",
        "why_it_matters": "这类分支通常不影响伤害，但不能被误判为 unsupported。",
        "current_policy": "记录 custom_string 日志和 last_custom_string flag。",
    },
    "generated debuff lowering": {
        "zh": "数据库负面状态节点自动转换",
        "what_it_does": "把 TurnBasedGameData 里“给目标挂负面状态”的节点翻译成模拟器可执行的 add_status。",
        "why_it_matters": "负面状态不能无条件添加，带概率时必须先过效果命中/效果抵抗判定。",
        "current_policy": "AddModifier.Chance / ByRandomChance / RandomConfig 分支已接入 chance/effect-hit gate。",
    },
    "effect_hit_gate": {
        "zh": "效果命中门槛 / 负面状态命中判定",
        "what_it_does": "在真正挂 debuff 前，用基础概率、效果命中、目标效果抵抗、特殊抵抗计算是否命中。",
        "why_it_matters": "控制、持续伤害、减速、易伤等负面状态都依赖这个概率门槛。",
        "current_policy": "支持强制 success/resisted，方便真实路线验证固定随机结果。",
    },
    "AttackConvert": {
        "zh": "攻击力转换值 / 同袍固定攻击力加成",
        "what_it_does": "丹恒·腾荒给【同袍】提供固定攻击力加成；数值来自丹恒当前攻击力乘以行迹倍率。",
        "why_it_matters": "它不是攻击百分比，也不是普通增伤；应进入固定攻击力加成桶，并且不能快照。",
        "current_policy": "作为 derived flat ATK modifier 接入，同袍目标获得 atk_add，刷新时替换旧值。",
    },
    "Souldragon fallback": {
        "zh": "龙灵兜底行动模板",
        "what_it_does": "当数据库还没有完整生成龙灵行动时，运行时临时补普通护盾/强化攻击行动。",
        "why_it_matters": "这让龙灵不再是空壳，但仍是丹恒专用兜底，不是最终通用方案。",
        "current_policy": "保留为 fallback，并在通用性审计里标记为需要迁移到 TBGD summon action lowering。",
    },
    "weakness_break_aftermath": {
        "zh": "弱点击破后的元素附加效果",
        "what_it_does": "物理裂伤、火灼烧、雷触电、风风化、冰冻结、量子纠缠、虚数禁锢。",
        "why_it_matters": "这些不是普通直伤；不能吃攻击力、普通增伤或双暴。",
        "current_policy": "基础击破/超击破/击破后 DoT/延迟伤害路径已接入，特殊交互仍需实战校准。",
    },
}


def glossary_report() -> dict[str, Any]:
    return {"format": "hsr_mechanism_glossary", "version": "v0.1", "terms": GLOSSARY}


def write_glossary_report(output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = glossary_report()
    (out / "mechanism_glossary_cn.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 机制术语中文说明", ""]
    for key, rec in GLOSSARY.items():
        lines.append(f"## `{key}`：{rec.get('zh')}")
        lines.append(f"- 作用：{rec.get('what_it_does')}")
        lines.append(f"- 为什么重要：{rec.get('why_it_matters')}")
        lines.append(f"- 当前策略：{rec.get('current_policy')}")
        if rec.get("example"):
            lines.append(f"- 例子：{rec.get('example')}")
        lines.append("")
    (out / "mechanism_glossary_cn.md").write_text("\n".join(lines), encoding="utf-8")
    return report
