from __future__ import annotations

"""Conservative Monster ConfigAbility graph audit/lowering.

This is the first database-driven enemy-skill lowering layer.  It does not try

to fully execute every RPG.GameCore node yet.  It scans ConfigAbility/Monster,
classifies nodes, lowers high-confidence combat nodes into a simulator-facing
preview IR, and keeps all unsupported/visual nodes as evidence so later work can
be driven from real graph coverage rather than hand-written boss templates.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any
import json

from .tbgd_loader import TBGDSource, unwrap_value


VISUAL_KEYWORDS = (
    "Anim", "Animation", "Camera", "Timeline", "Audio", "Sound", "VFX", "EffectPerform",
    "TriggerEffect", "WaitAnimState", "TriggerAnimState", "RemoveEffect", "VCamera", "ShowUI",
    "ShowBattleUI", "MakeCharacterHUDVisible", "LookAt", "MoveToTargetPosition", "FireProjectile",
    "RadialBlur", "SetEntityVisible", "SetAttachment", "SkillPerformFinish", "DamagePerformFinish",
)


def _type_name(node: Any) -> str | None:
    if isinstance(node, dict):
        t = node.get("$type") or node.get("Type") or node.get("type")
        if isinstance(t, str):
            return t.split(".")[-1]
    return None


def _raw_type(node: Any) -> str | None:
    if isinstance(node, dict):
        t = node.get("$type") or node.get("Type") or node.get("type")
        return str(t) if t is not None else None
    return None


def _fixed_value(node: Any, default: Any = None) -> Any:
    if isinstance(node, dict):
        if isinstance(node.get("FixedValue"), dict) and "Value" in node["FixedValue"]:
            return _fixed_value(node["FixedValue"], default)
        if "Value" in node and len(node) <= 3:
            return _fixed_value(node.get("Value"), default)
    return default if node is None else node


def _hash_or_value(node: Any) -> Any:
    if isinstance(node, dict):
        if "Hash" in node:
            return node.get("Hash")
        if "Value" in node:
            return node.get("Value")
    return node


def _target_alias(target: Any) -> str:
    if not isinstance(target, dict):
        return "unknown"
    typ = _type_name(target)
    if typ == "TargetAlias":
        return str(target.get("Alias") or "unknown")
    if typ == "TargetSequence":
        aliases = [_target_alias(x) for x in target.get("Sequence") or []]
        aliases = [a for a in aliases if a and a != "unknown"]
        return "+".join(aliases) if aliases else "sequence"
    if typ == "TargetFilter":
        return "filtered:" + _target_alias(target.get("TargetType") or target.get("Target"))
    return typ or "unknown"


def _element_from_attack_data(ap: Any) -> str | None:
    if not isinstance(ap, dict):
        return None
    dt = ap.get("DamageType")
    if isinstance(dt, dict):
        return str(dt.get("DamageType") or dt.get("Value") or "").lower() or None
    if dt:
        return str(dt).lower()
    return None


def _scalar_or_expr(node: Any) -> dict[str, Any] | float | int | str | None:
    if node is None:
        return None
    if isinstance(node, (int, float, str)):
        return node
    if isinstance(node, dict):
        if node.get("IsDynamic") is False:
            return _fixed_value(node.get("FixedValue"), None)
        if "FixedValue" in node:
            return _fixed_value(node.get("FixedValue"), None)
        if "Value" in node and len(node) <= 3:
            return _scalar_or_expr(node.get("Value"))
        if "PostfixExpr" in node:
            return {"expr_type": "postfix", "postfix_expr": deepcopy(node.get("PostfixExpr"))}
        if "DynamicHash" in node:
            return {"dynamic_hash": node.get("DynamicHash")}
    return deepcopy(node)


def _attack_data_ir(ap: Any) -> dict[str, Any]:
    ap = ap if isinstance(ap, dict) else {}
    return {
        "element": _element_from_attack_data(ap),
        "damage_percentage": _scalar_or_expr(ap.get("DamagePercentage")),
        "toughness_ratio": _scalar_or_expr(ap.get("SPHitRatio")),
        "attack_type": ap.get("AttackType"),
        "raw_keys": sorted(ap.keys()),
    }


def _dynamic_key(node: Any) -> Any:
    if isinstance(node, dict):
        for k in ("DynamicKey", "Key", "DynamicValueKey", "ValueKey"):
            if k in node:
                return _hash_or_value(node.get(k))
    return None


def _lower_node(node: dict[str, Any], ability_name: str | None, path: str) -> dict[str, Any] | None:
    typ = _type_name(node)
    raw = _raw_type(node)
    if not typ:
        return None
    base = {"source_node_type": raw, "ability": ability_name, "path": path}

    if typ == "DamageByAttackProperty":
        return {**base, "type": "damage", "target": _target_alias(node.get("TargetType")), "attack": _attack_data_ir(node.get("AttackProperty"))}
    if typ == "AttackData":
        return {**base, "type": "attack_data", "attack": _attack_data_ir(node)}
    if typ == "AddModifier":
        return {**base, "type": "add_status", "target": _target_alias(node.get("TargetType")), "status_id": _hash_or_value(node.get("ModifierName")), "chance": _scalar_or_expr(node.get("Chance")), "lifetime": _scalar_or_expr(node.get("LifeTime")), "dynamic_values": deepcopy(node.get("DynamicValues"))}
    if typ in {"RemoveModifier", "RemoveSelfModifier"}:
        return {**base, "type": "remove_status", "target": _target_alias(node.get("TargetType")), "status_id": _hash_or_value(node.get("ModifierName"))}
    if typ == "DispelStatus":
        return {**base, "type": "dispel_status", "target": _target_alias(node.get("TargetType")), "only_alive": node.get("OnlyAlive"), "silent": node.get("IsSilentDispel")}
    if typ in {"DefineDynamicValue", "SetDynamicValue"}:
        return {**base, "type": "set_dynamic_value", "key": _dynamic_key(node), "value": _scalar_or_expr(node.get("Value"))}
    if typ == "SetDynamicValueByAddValue":
        return {**base, "type": "modify_dynamic_value", "key": _dynamic_key(node), "delta": _scalar_or_expr(node.get("AddValue") or node.get("Value")), "min": _scalar_or_expr(node.get("Min")), "max": _scalar_or_expr(node.get("Max"))}
    if typ in {"SetDynamicValueByProperty", "SetDynamicValueByModifierValue"}:
        return {**base, "type": "set_dynamic_value_from_property", "key": _dynamic_key(node), "target": _target_alias(node.get("ReadTargetType") or node.get("TargetType")), "property": deepcopy(node.get("Value") or node.get("Property"))}
    if typ == "SummonMonster":
        return {**base, "type": "summon_monster", "delay_ratio": _scalar_or_expr(node.get("DelayRatio")), "summon_data": deepcopy(node.get("SummonMonsterDataList") or [])}
    if typ in {"SetMonsterPhase", "CharacterChangePhase"}:
        return {**base, "type": "set_monster_phase", "target": _target_alias(node.get("TargetType")), "phase": _scalar_or_expr(node.get("PhaseNum") or node.get("Phase") or node.get("Value"))}
    if typ in {"SetActionDelay", "ModifyActionDelay"}:
        return {**base, "type": "action_delay", "target": _target_alias(node.get("TargetType")), "value": _scalar_or_expr(node.get("NormalizedValue") or node.get("AddNormalizedValue")), "mode": "set" if typ == "SetActionDelay" else "modify"}
    if typ in {"ForceKill", "SetDieImmediately"}:
        return {**base, "type": "force_defeat", "target": _target_alias(node.get("TargetType"))}
    if typ in {"HealByAttackProperty", "Heal"}:
        return {**base, "type": "heal", "target": _target_alias(node.get("TargetType")), "value": _scalar_or_expr(node.get("HealPercentage") or node.get("Value") or node.get("Amount"))}
    return None


def _node_bucket(raw_type: str | None) -> str:
    if not raw_type:
        return "untyped"
    typ = raw_type.split(".")[-1]
    if any(k in typ for k in VISUAL_KEYWORDS):
        return "visual_timeline"
    if typ in {"DamageByAttackProperty", "AttackData"}:
        return "damage"
    if typ in {"AddModifier", "RemoveModifier", "RemoveSelfModifier", "DispelStatus"}:
        return "status_modifier"
    if "DynamicValue" in typ:
        return "dynamic_value"
    if typ == "SummonMonster":
        return "summon"
    if typ in {"SetMonsterPhase", "CharacterChangePhase", "ForceKill", "SetDieImmediately"}:
        return "phase_or_death"
    if "ActionDelay" in typ:
        return "action_order"
    if typ.startswith("By") or typ in {"PredicateTaskList", "TargetFilter", "TargetAlias", "TargetSequence", "Retarget"}:
        return "predicate_targeting"
    return "other"


def _walk(obj: Any, *, ability_name: str | None, path: str, visit) -> None:
    if isinstance(obj, dict):
        visit(obj, ability_name, path)
        next_ability = ability_name
        if "Name" in obj and any(k in obj for k in ("OnStart", "OnOwnerTurnStart", "OnModifierAdd")):
            next_ability = str(obj.get("Name"))
        for k, v in obj.items():
            _walk(v, ability_name=next_ability, path=f"{path}/{k}", visit=visit)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk(v, ability_name=ability_name, path=f"{path}/{i}", visit=visit)


def lower_monster_ability_file(src: TBGDSource, rel: str, *, max_abilities: int | None = None) -> dict[str, Any]:
    data = unwrap_value(src.read_json(rel))
    node_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    lowered_by_ability: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unlowered_combat: Counter[str] = Counter()
    visual_counts: Counter[str] = Counter()

    def visit(node: dict[str, Any], ability_name: str | None, path: str) -> None:
        raw = _raw_type(node)
        if raw:
            node_counts[raw] += 1
            bucket = _node_bucket(raw)
            bucket_counts[bucket] += 1
            lowered = _lower_node(node, ability_name, path)
            if lowered:
                lowered_by_ability[str(ability_name or "<global>")].append(lowered)
            elif bucket == "visual_timeline":
                visual_counts[raw] += 1
            elif bucket in {"damage", "status_modifier", "dynamic_value", "summon", "phase_or_death", "action_order"}:
                unlowered_combat[raw] += 1

    _walk(data, ability_name=None, path="", visit=visit)
    abilities = data.get("AbilityList") or [] if isinstance(data, dict) else []
    ability_names = [str(a.get("Name")) for a in abilities if isinstance(a, dict) and a.get("Name")]
    ability_rows = []
    selected_names = ability_names[: max_abilities or len(ability_names)]
    for name in selected_names:
        effects = lowered_by_ability.get(name, [])
        if effects:
            ability_rows.append({"ability": name, "lowered_effect_count": len(effects), "effects": effects[:80]})
    return {
        "file": rel,
        "ability_count": len(ability_names),
        "lowered_ability_count": len(ability_rows),
        "node_counts": dict(node_counts.most_common(80)),
        "bucket_counts": dict(bucket_counts.most_common()),
        "lowered_effect_count": sum(len(v) for v in lowered_by_ability.values()),
        "unlowered_combat_node_counts": dict(unlowered_combat.most_common(80)),
        "visual_evidence_counts": dict(visual_counts.most_common(40)),
        "ability_rows": ability_rows,
    }


def _pick_non_knight_samples(file_summaries: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    excluded = ("W4_Hearse", "W4_Claymore", "W5_Ranger")
    wanted_buckets = ["damage", "status_modifier", "dynamic_value", "summon", "phase_or_death", "action_order"]
    scored = []
    for row in file_summaries:
        rel = row.get("file", "")
        if any(x in rel for x in excluded):
            continue
        buckets = row.get("bucket_counts") or {}
        diversity = sum(1 for b in wanted_buckets if buckets.get(b, 0))
        score = diversity * 1000 + row.get("lowered_effect_count", 0)
        if diversity >= 2 and row.get("lowered_effect_count", 0) > 0:
            scored.append((score, rel, row))
    picked = []
    used_prefixes = set()
    for _score, rel, row in sorted(scored, key=lambda x: (-x[0], x[1])):
        prefix = Path(rel).stem.split("_Ability")[0]
        if prefix in used_prefixes:
            continue
        used_prefixes.add(prefix)
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def write_monster_ability_graph_lowering(tbgd_source: str | Path, out_dir: str | Path, *, sample_limit: int = 5, per_file_ability_limit: int = 12, max_files: int | None = None) -> dict[str, Any]:
    src = TBGDSource.open(tbgd_source)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = [f for f in src.list_files("Config/ConfigAbility/Monster/") if f.endswith(".json") and not f.endswith(".layout.json") and "/Camera/" not in f]
    total_file_count = len(files)
    if max_files is not None and max_files >= 0:
        files = files[:max_files]
    global_nodes: Counter[str] = Counter()
    global_buckets: Counter[str] = Counter()
    global_unlowered: Counter[str] = Counter()
    lowered_files = []
    file_summaries = []
    for rel in files:
        try:
            row = lower_monster_ability_file(src, rel, max_abilities=per_file_ability_limit)
        except Exception as exc:
            file_summaries.append({"file": rel, "error": str(exc)})
            continue
        file_summaries.append({k: v for k, v in row.items() if k != "ability_rows"})
        global_nodes.update(row.get("node_counts") or {})
        global_buckets.update(row.get("bucket_counts") or {})
        global_unlowered.update(row.get("unlowered_combat_node_counts") or {})
        if row.get("lowered_effect_count", 0) > 0 and len(lowered_files) < 120:
            lowered_files.append(row)
    non_knight = _pick_non_knight_samples(lowered_files, limit=sample_limit)
    summary = {
        "format": "hsr_monster_ability_graph_lowering",
        "version": "v0.1",
        "source": str(tbgd_source),
        "monster_ability_file_count": len(files),
        "monster_ability_file_total_available": total_file_count,
        "files_with_lowered_effects_sampled": len(lowered_files),
        "node_type_counts_top": dict(global_nodes.most_common(100)),
        "node_bucket_counts": dict(global_buckets.most_common()),
        "unlowered_combat_node_counts_top": dict(global_unlowered.most_common(80)),
        "lowering_policy": {
            "lowered_to_ir": ["DamageByAttackProperty", "AttackData", "AddModifier", "RemoveModifier", "DispelStatus", "DynamicValue", "SummonMonster", "SetMonsterPhase", "ActionDelay", "ForceKill"],
            "visual_evidence_only": list(VISUAL_KEYWORDS),
            "status": "conservative preview IR; runtime binding is explicit and test-driven",
        },
        "non_knight_sample_count": len(non_knight),
        "non_knight_samples": [
            {
                "file": r.get("file"),
                "ability_count": r.get("ability_count"),
                "lowered_effect_count": r.get("lowered_effect_count"),
                "bucket_counts": r.get("bucket_counts"),
                "lowered_abilities": [a.get("ability") for a in r.get("ability_rows", [])[:8]],
            }
            for r in non_knight
        ],
    }
    (out / "monster_ability_lowering_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "monster_ability_lowering_preview.json").write_text(json.dumps({"version": "v0.1", "sampled_files": lowered_files[:60], "non_knight_samples": non_knight}, ensure_ascii=False, indent=2), encoding="utf-8")
    cn_lines = [
        "# Monster ConfigAbility 图审计与保守 lowering v0.1",
        "",
        f"- 扫描敌人 ability 文件：{len(files)} 个。",
        f"- 节点桶统计：`{dict(global_buckets.most_common())}`。",
        "- 本轮 lower 的是高置信战斗节点：伤害、状态增删、动态变量、召唤、转阶段、行动延后、驱散、强制击败。",
        "- 表现类节点继续只保留 evidence，不进入战斗数值。",
        "- 这一步是预览 IR，不等于全敌人技能已经完全 runtime 绑定。",
        "",
        "## 非骑士三样例",
    ]
    for r in non_knight:
        cn_lines.append(f"- `{r.get('file')}`：lowered_effect_count={r.get('lowered_effect_count')}, buckets={r.get('bucket_counts')}")
    cn_lines.append("")
    cn_lines.append("## 当前 unlowered combat-like 节点 Top")
    for k, v in global_unlowered.most_common(20):
        cn_lines.append(f"- `{k}`: {v}")
    (out / "monster_ability_lowering_summary_cn.md").write_text("\n".join(cn_lines) + "\n", encoding="utf-8")
    return summary
