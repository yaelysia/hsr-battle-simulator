from __future__ import annotations

"""Inventory enemy-side mechanisms already present in the model pack.

This is a review/reporting tool.  It helps avoid redoing enemy work by showing
which enemy templates already contain HP bars, summons, triggers, statuses,
randomness, weakness/toughness, and other special-mechanism hints.
"""

from pathlib import Path
from typing import Any
from collections import Counter
import json

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

KEYWORD_GROUPS: dict[str, list[str]] = {
    "phase_hp": ["hp_bars", "hp_model", "phase", "phase_hp", "after_hp_bar_depleted"],
    "summon_or_attached": ["summon", "summoned", "attached", "minion", "召唤", "附属"],
    "toughness_break": ["toughness", "stance", "weakness", "break", "韧性", "击破"],
    "random": ["random", "chance", "RandomConfig", "ByRandomChance", "随机", "概率"],
    "debuff": ["debuff", "effect_hit", "effect_res", "StatusResistance", "负面", "抵抗"],
    "action_order": ["advance", "delay", "action_delay", "remaining_av", "拉条", "推条"],
    "shield_or_damage_reduction": ["shield", "damage_reduction", "reduce", "护盾", "减伤"],
}


def _read_yaml_or_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except Exception:
            return None
    if yaml is None:
        return None
    try:
        return yaml.safe_load(text)
    except Exception:
        return None


def _textify(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


def _collect_unit_stats(obj: Any) -> dict[str, int]:
    stats = {"actions": 0, "statuses": 0, "triggers": 0, "effects": 0, "damage_packets": 0}
    def walk(x: Any):
        if isinstance(x, dict):
            if isinstance(x.get("actions"), dict):
                stats["actions"] += len(x["actions"])
            if isinstance(x.get("statuses"), list):
                stats["statuses"] += len(x["statuses"])
            if isinstance(x.get("triggers"), list):
                stats["triggers"] += len(x["triggers"])
            for key in ("effects", "effects_on_apply", "effects_on_remove", "effects_after_damage", "effects_after_action_start"):
                if isinstance(x.get(key), list):
                    stats["effects"] += len(x[key])
            if isinstance(x.get("damage_packets"), list):
                stats["damage_packets"] += len(x["damage_packets"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return stats


def analyze_enemy_mechanisms(model_pack_dir: str | Path) -> dict[str, Any]:
    base = Path(model_pack_dir)
    enemy_dir = base / "models" / "enemies"
    files = sorted([p for p in enemy_dir.rglob("*") if p.suffix.lower() in {".yaml", ".yml", ".json"}]) if enemy_dir.exists() else []
    rows: list[dict[str, Any]] = []
    group_counts: Counter[str] = Counter()
    for p in files:
        obj = _read_yaml_or_json(p)
        if obj is None:
            continue
        text = _textify(obj).lower()
        groups = []
        for group, kws in KEYWORD_GROUPS.items():
            if any(str(kw).lower() in text for kw in kws):
                groups.append(group)
                group_counts[group] += 1
        row = {
            "file": str(p.relative_to(base)),
            "name": obj.get("name") if isinstance(obj, dict) else None,
            "id": obj.get("id") if isinstance(obj, dict) else None,
            "mechanism_groups": groups,
            "counts": _collect_unit_stats(obj),
        }
        rows.append(row)
    # Stage/compiled-case hints: useful because some enemy mechanisms are encoded in battles/stages.
    stage_files = sorted([p for p in (base / "stages").rglob("*") if p.suffix.lower() in {".yaml", ".yml", ".json"}]) if (base / "stages").exists() else []
    battle_files = sorted([p for p in (base / "battles").rglob("*") if p.suffix.lower() in {".yaml", ".yml", ".json"}]) if (base / "battles").exists() else []
    stage_rows = []
    for p in stage_files + battle_files:
        obj = _read_yaml_or_json(p)
        if obj is None:
            continue
        text = _textify(obj).lower()
        groups = [g for g, kws in KEYWORD_GROUPS.items() if any(str(kw).lower() in text for kw in kws)]
        if groups:
            stage_rows.append({"file": str(p.relative_to(base)), "mechanism_groups": groups})
    return {
        "format": "hsr_enemy_mechanism_inventory",
        "version": "v0.1",
        "summary_cn": "盘点模型包里已经存在的敌人机制痕迹，避免误以为敌人机制完全没做。",
        "enemy_file_count": len(files),
        "enemy_count_with_mechanism_hints": sum(1 for r in rows if r["mechanism_groups"]),
        "mechanism_group_counts": dict(group_counts.most_common()),
        "enemy_rows": rows,
        "stage_or_battle_rows_with_hints": stage_rows,
        "next_step_cn": "真实流程验证时，优先选择 mechanism_groups 多的敌人逐项写 expect，确认已有机制是否和游戏一致。",
    }


def write_enemy_mechanism_inventory(model_pack_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = analyze_enemy_mechanisms(model_pack_dir)
    (out / "enemy_mechanism_inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 敌人机制盘点", "", f"敌人文件数：{report['enemy_file_count']}", f"带机制痕迹敌人文件数：{report['enemy_count_with_mechanism_hints']}", "", "## 机制组统计", ""]
    for k, v in report["mechanism_group_counts"].items():
        lines.append(f"- `{k}`：{v}")
    lines.append("\n## 敌人条目\n")
    for r in report["enemy_rows"][:200]:
        if r["mechanism_groups"]:
            lines.append(f"- `{r['file']}`：{', '.join(r['mechanism_groups'])}；actions={r['counts']['actions']} statuses={r['counts']['statuses']} triggers={r['counts']['triggers']}")
    (out / "enemy_mechanism_inventory_cn.md").write_text("\n".join(lines), encoding="utf-8")
    return report
