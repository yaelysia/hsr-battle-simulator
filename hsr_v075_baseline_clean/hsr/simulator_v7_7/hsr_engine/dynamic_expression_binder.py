from __future__ import annotations

"""Bind TurnBasedGameData dynamic postfix expressions to simulator Content IR values.

This module is intentionally a compiler-boundary layer.  It does not execute
combat.  It resolves a conservative subset of dynamic expressions that can be
bound from stable ExcelOutput skill tables, and it leaves all uncertain
expressions symbolic with explicit unresolved metadata.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any
import json

from .core_rules import coerce_float, maybe_float
from .tbgd_loader import TBGDSource, unwrap_value


class DynamicBindingError(RuntimeError):
    pass


def _value(v: Any) -> Any:
    return unwrap_value(v)


def _num(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        return coerce_float(_value(v))
    except Exception:
        return default


def _param_values(raw: Any) -> list[float]:
    raw = _value(raw or [])
    if not isinstance(raw, list):
        return []
    out: list[float] = []
    for item in raw:
        if isinstance(item, dict) and "Value" in item:
            item = item["Value"]
        val = _num(item)
        if val is not None:
            out.append(val)
    return out


def _last_row_at_or_below_level(rows: list[dict[str, Any]], level: int | None = None) -> dict[str, Any] | None:
    if not rows:
        return None
    unwrapped = [_value(r) for r in rows]
    unwrapped.sort(key=lambda r: int(r.get("Level", 0) or 0))
    if level is None:
        return unwrapped[-1]
    best = unwrapped[0]
    for r in unwrapped:
        try:
            if int(r.get("Level", 0) or 0) <= level:
                best = r
        except Exception:
            pass
    return best


def _expr_kind(expr: Any) -> str | None:
    if not isinstance(expr, dict):
        return None
    if expr.get("expr_kind"):
        return str(expr.get("expr_kind"))
    # Raw TBGD dynamic expression shape.
    if expr.get("IsDynamic") is True and isinstance(expr.get("PostfixExpr"), dict):
        return "raw_tbgd_dynamic"
    return None


def _expr_fixed(expr: dict[str, Any]) -> list[float]:
    vals = expr.get("fixed_values")
    if vals is None and isinstance(expr.get("PostfixExpr"), dict):
        vals = expr["PostfixExpr"].get("FixedValues")
    vals = _value(vals or [])
    out = []
    if isinstance(vals, list):
        for v in vals:
            n = _num(v)
            if n is not None:
                out.append(n)
    return out


def _expr_hashes(expr: dict[str, Any]) -> list[int]:
    hashes = expr.get("dynamic_hashes")
    if hashes is None and isinstance(expr.get("PostfixExpr"), dict):
        hashes = expr["PostfixExpr"].get("DynamicHashes")
    hashes = _value(hashes or [])
    out: list[int] = []
    if isinstance(hashes, list):
        for h in hashes:
            try:
                out.append(int(h))
            except Exception:
                pass
    return out


def _fixed_ratio_from_expr(expr: Any) -> float | None:
    if isinstance(expr, dict):
        if expr.get("IsDynamic") is False:
            return _num(expr.get("FixedValue"))
        if not expr.get("expr_kind") and "FixedValue" in expr:
            return _num(expr.get("FixedValue"))
    return _num(expr)


def _raw_fixed_value(expr: Any) -> float | None:
    if isinstance(expr, dict):
        if expr.get("IsDynamic") is False:
            return _num(expr.get("FixedValue"))
        if "FixedValue" in expr and len(expr) == 1:
            return _num(expr.get("FixedValue"))
    return _num(expr)


class SkillParameterIndex:
    def __init__(self, source: TBGDSource):
        rows = source.load_table("AvatarSkillConfig") if "AvatarSkillConfig" in source.list_excel_tables() else []
        self.skill_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            row = _value(r)
            sid = row.get("SkillID")
            try:
                sid_i = int(sid)
            except Exception:
                continue
            self.skill_rows[sid_i].append(row)
        for sid in list(self.skill_rows):
            self.skill_rows[sid].sort(key=lambda x: int(x.get("Level", 0) or 0))

    def row(self, skill_id: int, level: int | None = None) -> dict[str, Any] | None:
        return _last_row_at_or_below_level(self.skill_rows.get(int(skill_id), []), level=level)

    def skill_context(self, skill_id: int, level: int | None = None) -> dict[str, Any]:
        row = self.row(skill_id, level=level) or {}
        params = _param_values(row.get("ParamList"))
        simple_params = _param_values(row.get("SimpleParamList"))
        show_stance = _param_values(row.get("ShowStanceList"))
        show_damage = _param_values(row.get("ShowDamageList"))
        return {
            "skill_id": int(skill_id),
            "level": int(row.get("Level", level or 0) or 0),
            "max_level": int(row.get("MaxLevel", row.get("Level", 0)) or 0),
            "trigger_key": row.get("SkillTriggerKey"),
            "attack_type": row.get("AttackType"),
            "skill_effect": row.get("SkillEffect"),
            "param_list": params,
            "simple_param_list": simple_params,
            "show_stance_list": show_stance,
            "show_damage_list": show_damage,
            "stance_damage_display": _num(row.get("StanceDamageDisplay")),
            "sp_base": _num(row.get("SPBase")),
            "bp_need": _num(row.get("BPNeed")),
            "bp_add": _num(row.get("BPAdd")),
            "sp_multiple_ratio": _num(row.get("SPMultipleRatio")),
            "delay_ratio": _num(row.get("DelayRatio")),
        }


def infer_action_hash_bindings(action: dict[str, Any], skill_ctx: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Infer conservative dynamic-hash bindings for one ActionIR.

    High-confidence binding rules:
    - Unique DamagePercentage hashes are matched to AvatarSkillConfig.ParamList
      in first-seen packet order.  This covers both one-total-multiplier skills
      and split target/adjacent packets such as main target + adjacent target.
    - If a packet has HitSplitRatio, the binder does not change the hash binding;
      the evaluator multiplies the resolved total parameter by the hit split.
    - Unique StanceValue hashes are matched to non-zero ShowStanceList entries in
      first-seen packet order.  This avoids treating display-only zero slots as
      actual packet toughness values.
    """
    bindings: dict[int, dict[str, Any]] = {}
    params = list(skill_ctx.get("param_list") or [])
    stance_values = [v for v in (skill_ctx.get("show_stance_list") or []) if v not in (None, 0, 0.0)]

    def bind(h: int, value: float | None, source: str, confidence: str = "high") -> None:
        if value is None:
            return
        existing = bindings.get(h)
        record = {"value": float(value), "source": source, "confidence": confidence}
        if existing is not None and abs(float(existing.get("value", 0.0)) - float(value)) > 1e-9:
            record["confidence"] = "conflict"
            record["conflict_with"] = existing
        bindings[h] = record

    damage_hashes: list[int] = []
    toughness_hashes: list[int] = []
    for packet in action.get("damage_packets", []) or []:
        if not isinstance(packet, dict):
            continue
        scaling = packet.get("scaling") if isinstance(packet.get("scaling"), dict) else {}
        expr = scaling.get("multiplier_expr")
        if isinstance(expr, dict):
            hashes = _expr_hashes(expr)
            if len(hashes) == 1 and hashes[0] not in damage_hashes:
                damage_hashes.append(hashes[0])
        toughness = packet.get("toughness") if isinstance(packet.get("toughness"), dict) else {}
        tex = toughness.get("toughness_reduction_expr")
        if isinstance(tex, dict):
            hashes = _expr_hashes(tex)
            if len(hashes) == 1 and hashes[0] not in toughness_hashes:
                toughness_hashes.append(hashes[0])

    for i, h in enumerate(damage_hashes):
        if i < len(params):
            bind(h, params[i], f"AvatarSkillConfig.ParamList[{i}] via damage scaling order")
        elif params:
            bind(h, params[0], "AvatarSkillConfig.ParamList[0] fallback via damage scaling", confidence="medium")

    for i, h in enumerate(toughness_hashes):
        if i < len(stance_values):
            bind(h, stance_values[i], f"AvatarSkillConfig.ShowStanceList nonzero[{i}] via toughness order")
        elif stance_values:
            bind(h, stance_values[0], "AvatarSkillConfig.ShowStanceList[0] fallback via toughness", confidence="medium")
    return bindings


def evaluate_dynamic_expr(expr: Any, bindings: dict[int, dict[str, Any]], *, implicit_fixed_multiplier: float | None = None) -> tuple[float | None, dict[str, Any]]:
    fixed = _raw_fixed_value(expr)
    if fixed is not None:
        return fixed, {"status": "resolved_fixed"}
    if not isinstance(expr, dict) or _expr_kind(expr) not in {"tbgd_postfix_dynamic", "raw_tbgd_dynamic"}:
        return None, {"status": "not_dynamic_expr"}

    hashes = _expr_hashes(expr)
    fixed_values = _expr_fixed(expr)
    if not hashes:
        # Some dynamic-looking expressions are constants.
        if len(fixed_values) == 1:
            return fixed_values[0], {"status": "resolved_fixed_values_only"}
        return None, {"status": "unresolved_no_hash", "fixed_values": fixed_values}

    if len(hashes) == 1 and hashes[0] in bindings:
        val = float(bindings[hashes[0]]["value"])
        if len(fixed_values) == 0:
            if implicit_fixed_multiplier is not None:
                return float(implicit_fixed_multiplier) * val, {"status": "resolved_hit_split_times_hash", "hash": hashes[0], "hit_split_ratio": float(implicit_fixed_multiplier), "binding": bindings[hashes[0]]}
            return val, {"status": "resolved_hash", "hash": hashes[0], "binding": bindings[hashes[0]]}
        if len(fixed_values) == 1:
            return float(fixed_values[0]) * val, {
                "status": "resolved_fixed_times_hash",
                "hash": hashes[0],
                "fixed": float(fixed_values[0]),
                "binding": bindings[hashes[0]],
            }
    return None, {
        "status": "unresolved_dynamic_expr",
        "hashes": hashes,
        "fixed_values": fixed_values,
        "missing_hashes": [h for h in hashes if h not in bindings],
    }


def bind_action_ir_bundle(action_bundle: dict[str, Any], source: TBGDSource, *, skill_level_overrides: dict[int, int] | None = None) -> dict[str, Any]:
    index = SkillParameterIndex(source)
    skill_level_overrides = skill_level_overrides or {}
    bundle = deepcopy(action_bundle)

    summary = Counter()
    unresolved_hashes = Counter()
    action_summaries: list[dict[str, Any]] = []

    for avatar in bundle.get("avatars", []) or []:
        for action in avatar.get("actions", []) or []:
            try:
                sid = int(action.get("action_id"))
            except Exception:
                continue
            ctx = index.skill_context(sid, level=skill_level_overrides.get(sid))
            action["skill_parameter_context"] = ctx
            action["energy_gain"] = {"base": ctx.get("sp_base"), "source": "AvatarSkillConfig.SPBase"} if ctx.get("sp_base") is not None else None
            bp_need = ctx.get("bp_need")
            bp_add = ctx.get("bp_add")
            if bp_need is not None and bp_need > 0:
                action["skill_point_delta"] = -float(bp_need)
            elif bp_add is not None and bp_add > 0:
                action["skill_point_delta"] = float(bp_add)
            bindings = infer_action_hash_bindings(action, ctx)
            action["dynamic_hash_bindings"] = {str(k): v for k, v in sorted(bindings.items())}

            total_mult = 0.0
            total_toughness = 0.0
            packet_resolved = 0
            packet_total = 0
            used_damage_hashes: list[int] = []
            used_toughness_hashes: list[int] = []
            for packet in action.get("damage_packets", []) or []:
                if not isinstance(packet, dict):
                    continue
                packet_total += 1
                scaling = packet.get("scaling") if isinstance(packet.get("scaling"), dict) else {}
                if isinstance(scaling.get("multiplier_expr"), dict):
                    for h in _expr_hashes(scaling.get("multiplier_expr")):
                        if h not in used_damage_hashes:
                            used_damage_hashes.append(h)
                    hit_split = _fixed_ratio_from_expr(packet.get("hit_split_ratio_expr"))
                    val, trace = evaluate_dynamic_expr(scaling.get("multiplier_expr"), bindings, implicit_fixed_multiplier=hit_split)
                    scaling["multiplier_resolve"] = trace
                    summary[f"expr_{trace.get('status')}"] += 1
                    if val is not None:
                        scaling["multiplier"] = val
                        total_mult += val
                        packet_resolved += 1
                    else:
                        for h in trace.get("missing_hashes", []) or []:
                            unresolved_hashes[h] += 1
                toughness = packet.get("toughness") if isinstance(packet.get("toughness"), dict) else {}
                if isinstance(toughness.get("toughness_reduction_expr"), dict):
                    for h in _expr_hashes(toughness.get("toughness_reduction_expr")):
                        if h not in used_toughness_hashes:
                            used_toughness_hashes.append(h)
                    hit_split = _fixed_ratio_from_expr(packet.get("hit_split_ratio_expr"))
                    val, trace = evaluate_dynamic_expr(toughness.get("toughness_reduction_expr"), bindings, implicit_fixed_multiplier=hit_split)
                    toughness["toughness_reduction_resolve"] = trace
                    summary[f"expr_{trace.get('status')}"] += 1
                    if val is not None:
                        toughness["toughness_reduction"] = val
                        total_toughness += val
                    else:
                        for h in trace.get("missing_hashes", []) or []:
                            unresolved_hashes[h] += 1
            if packet_total:
                action["damage_packet_binding_summary"] = {
                    "packet_count": packet_total,
                    "resolved_multiplier_packet_count": packet_resolved,
                    "total_resolved_multiplier": total_mult,
                    "expected_total_multiplier_from_param0": (ctx.get("param_list") or [None])[0],
                    "expected_total_multiplier_from_bound_unique_hashes": sum(float(bindings[h]["value"]) for h in used_damage_hashes if h in bindings),
                    "total_resolved_toughness_reduction": total_toughness,
                    "expected_total_toughness_from_show_stance0": (ctx.get("show_stance_list") or [None])[0],
                    "expected_total_toughness_from_bound_unique_hashes": sum(float(bindings[h]["value"]) for h in used_toughness_hashes if h in bindings),
                }
            action_summaries.append({
                "avatar_id": avatar.get("avatar_id"),
                "action_id": sid,
                "trigger_key": action.get("trigger_key"),
                "packet_count": packet_total,
                "resolved_multiplier_packet_count": packet_resolved,
                "total_multiplier": total_mult if packet_total else None,
                "expected_param0": (ctx.get("param_list") or [None])[0],
                "expected_multiplier_bound_hash_sum": sum(float(bindings[h]["value"]) for h in used_damage_hashes if h in bindings) if packet_total else None,
                "total_toughness": total_toughness if packet_total else None,
                "expected_stance0": (ctx.get("show_stance_list") or [None])[0],
                "expected_toughness_bound_hash_sum": sum(float(bindings[h]["value"]) for h in used_toughness_hashes if h in bindings) if packet_total else None,
            })

    bundle["binding_summary"] = {
        "format": "hsr_bound_action_ir_summary",
        "version": "v0.8",
        "expression_status_counts": dict(summary),
        "unresolved_hashes_top": {str(k): v for k, v in unresolved_hashes.most_common(50)},
        "actions": action_summaries,
    }
    return bundle


def write_bound_action_ir_bundle(tbgd_source: str | Path, action_ir_bundle_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    src = TBGDSource.open(tbgd_source)
    action_bundle = json.loads(Path(action_ir_bundle_path).read_text(encoding="utf-8"))
    bound = bind_action_ir_bundle(action_bundle, src)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bound_action_ir_bundle.json").write_text(json.dumps(bound, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = bound.get("binding_summary", {})
    (out_dir / "bound_action_ir_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
