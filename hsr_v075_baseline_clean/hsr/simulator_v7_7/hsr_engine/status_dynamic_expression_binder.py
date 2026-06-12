from __future__ import annotations

"""Conservatively bind StatusIR dynamic expressions to source parameter contexts.

This stays on the compiler side of the boundary.  It consumes StatusIR previews
and TurnBasedGameData source tables, annotates expressions with high-confidence
numeric or symbolic bindings, and leaves uncertain cases unresolved.  The combat
kernel still receives only canonical IR and never interprets raw TBGD hashes.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any
import json
import re

from .dynamic_expression_binder import SkillParameterIndex, evaluate_dynamic_expr
from .tbgd_loader import TBGDSource, unwrap_value


RANK_RE = re.compile(r"Rank(?P<rank>0?[1-6])")
POINT_RE = re.compile(r"Point(?P<point>[A-Z]\d+)")


class StatusDynamicBindingError(RuntimeError):
    pass


def _num(v: Any) -> float | None:
    v = unwrap_value(v)
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except Exception:
        return None


def _param_values(raw: Any) -> list[float]:
    raw = unwrap_value(raw or [])
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


def _expr_hashes(expr: dict[str, Any]) -> list[int]:
    hashes = expr.get("dynamic_hashes")
    if hashes is None and isinstance(expr.get("PostfixExpr"), dict):
        hashes = expr["PostfixExpr"].get("DynamicHashes")
    hashes = unwrap_value(hashes or [])
    out = []
    if isinstance(hashes, list):
        for h in hashes:
            try:
                out.append(int(h))
            except Exception:
                pass
    return out


def _expr_kind(expr: Any) -> str | None:
    if not isinstance(expr, dict):
        return None
    if expr.get("expr_kind"):
        return str(expr.get("expr_kind"))
    if expr.get("IsDynamic") is True and isinstance(expr.get("PostfixExpr"), dict):
        return "raw_tbgd_dynamic"
    return None


def _is_dynamic_expr(obj: Any) -> bool:
    return isinstance(obj, dict) and _expr_kind(obj) in {"tbgd_postfix_dynamic", "raw_tbgd_dynamic"}


def _collect_expr_refs(obj: Any, path: str = "") -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        if _is_dynamic_expr(obj):
            refs.append({"path": path, "expr": obj, "hashes": _expr_hashes(obj)})
        for k, v in obj.items():
            if str(k).endswith("_resolve"):
                continue
            child = f"{path}.{k}" if path else str(k)
            refs.extend(_collect_expr_refs(v, child))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            refs.extend(_collect_expr_refs(v, f"{path}[{i}]"))
    return refs


def _parse_path_tokens(path: str) -> list[Any]:
    """Parse dotted/list paths emitted by _collect_expr_refs.

    Supported examples:
      effects[0].value_expr -> ["effects", 0, "value_expr"]
      [0].effects[0].value_expr -> [0, "effects", 0, "value_expr"]

    The leading bracket form is important because StatusIR binding walks the
    trigger list as the root object.  Earlier code only handled name[index]
    parts, so it counted bindings in the summary but failed to attach
    *_resolve siblings back into the bundle.
    """
    if not path:
        return []
    tokens: list[Any] = []
    for part in path.split('.'):
        if not part:
            continue
        for m in re.finditer(r"([^\[\]]+)|\[(\d+)\]", part):
            if m.group(1) is not None:
                tokens.append(m.group(1))
            else:
                tokens.append(int(m.group(2)))
    return tokens


def _set_path(root: Any, path: str, key_suffix: str, value: Any) -> bool:
    """Set sibling field at a dotted/list path: a.b[0].expr -> a.b[0].expr_resolve."""
    tokens = _parse_path_tokens(path)
    if not tokens:
        return False
    cur = root
    for tok in tokens[:-1]:
        try:
            cur = cur[tok]
        except Exception:
            return False
    last = tokens[-1]
    if not isinstance(last, str) or not isinstance(cur, dict):
        return False
    cur[f"{last}{key_suffix}"] = value
    return True


class SkillTreeParameterIndex:
    def __init__(self, source: TBGDSource):
        self.by_avatar_point: dict[tuple[int, str], dict[str, Any]] = {}
        if "AvatarSkillTreeConfig" not in source.list_excel_tables():
            return
        rows = unwrap_value(source.load_table("AvatarSkillTreeConfig"))
        best: dict[tuple[int, str], dict[str, Any]] = {}
        for r in rows if isinstance(rows, list) else []:
            try:
                aid = int(r.get("AvatarID"))
            except Exception:
                continue
            point = str(r.get("PointTriggerKey") or "")
            if not point:
                continue
            key = (aid, point)
            old = best.get(key)
            # Prefer the row with the longest ParamList; tie-break by higher level.
            if old is None or len(_param_values(r.get("ParamList"))) > len(_param_values(old.get("ParamList"))) or int(r.get("Level", 0) or 0) > int(old.get("Level", 0) or 0):
                best[key] = r
        for key, r in best.items():
            self.by_avatar_point[key] = {
                "avatar_id": key[0],
                "point_trigger_key": key[1],
                "point_id": r.get("PointID"),
                "level": r.get("Level"),
                "ability_name": r.get("AbilityName"),
                "param_list": _param_values(r.get("ParamList")),
            }

    def context(self, avatar_id: int, point: str) -> dict[str, Any] | None:
        return self.by_avatar_point.get((int(avatar_id), str(point)))


class RankParameterIndex:
    def __init__(self, source: TBGDSource):
        self.by_avatar_rank: dict[tuple[int, int], dict[str, Any]] = {}
        self.by_rank_ability: dict[tuple[int, str], dict[str, Any]] = {}
        if "AvatarRankConfig" not in source.list_excel_tables():
            return
        rows = unwrap_value(source.load_table("AvatarRankConfig"))
        for r in rows if isinstance(rows, list) else []:
            try:
                rid = int(r.get("RankID"))
                rank = int(r.get("Rank"))
                aid = rid // 100
            except Exception:
                continue
            ctx = {
                "avatar_id": aid,
                "rank": rank,
                "rank_id": rid,
                "param_list": _param_values(r.get("Param")),
                "rank_ability": list(r.get("RankAbility") or []),
            }
            self.by_avatar_rank[(aid, rank)] = ctx
            for name in ctx["rank_ability"]:
                self.by_rank_ability[(aid, str(name))] = ctx

    def context(self, avatar_id: int, rank: int) -> dict[str, Any] | None:
        return self.by_avatar_rank.get((int(avatar_id), int(rank)))

    def context_by_ability(self, avatar_id: int, ability_name: str) -> dict[str, Any] | None:
        return self.by_rank_ability.get((int(avatar_id), str(ability_name)))


class CharacterDynamicHashIndex:
    """Lazy map ConfigCharacter DynamicValues hashes to concrete parameter contexts."""

    def __init__(self, source: TBGDSource, skill_index: SkillParameterIndex, skill_tree_index: SkillTreeParameterIndex, rank_index: RankParameterIndex):
        self.source = source
        self.skill_index = skill_index
        self.skill_tree_index = skill_tree_index
        self.rank_index = rank_index
        self.by_avatar_hash: dict[tuple[int, int], dict[str, Any]] = {}
        # Hashes explicitly declared by ConfigCharacter.DynamicValues with
        # ReadInfo.Type=None are runtime/property placeholders, not skill
        # ParamList slots.  Keeping them in this separate map prevents later
        # medium-confidence source-action binding from sliding across them and
        # turning runtime values such as Attack/AttackConvert into constants.
        self.by_avatar_runtime_hash: dict[tuple[int, int], dict[str, Any]] = {}
        self._loaded_avatars: set[int] = set()
        self._skill_by_avatar_trigger: dict[tuple[int, str], dict[str, Any]] = {}
        self._avatar_paths: dict[int, list[str]] = {}
        try:
            avatar_rows = source.load_table("AvatarConfig") if "AvatarConfig" in source.list_excel_tables() else []
        except Exception:
            avatar_rows = []
        for r in avatar_rows if isinstance(avatar_rows, list) else []:
            row = unwrap_value(r)
            try:
                aid = int(row.get("AvatarID"))
            except Exception:
                continue
            for sid in row.get("SkillList") or []:
                try:
                    ctx = skill_index.skill_context(int(sid))
                except Exception:
                    continue
                trigger = ctx.get("trigger_key")
                if trigger:
                    self._skill_by_avatar_trigger[(aid, str(trigger))] = ctx
            paths = []
            if row.get("JsonPath"):
                rel = str(row.get("JsonPath")).lstrip("/")
                paths.append(rel)
                if "/Avatar/" in rel:
                    paths.append(rel.replace("/Avatar/", "/Avatar/Advanced/", 1))
            self._avatar_paths[aid] = paths

    def _collect_dynamic_read_infos(self, obj: Any) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        def walk(o: Any) -> None:
            if isinstance(o, dict):
                dv = o.get("DynamicValues")
                if isinstance(dv, dict):
                    for group_val in dv.values():
                        if isinstance(group_val, dict):
                            for k, v in group_val.items():
                                try:
                                    h = int(k)
                                except Exception:
                                    continue
                                ri = v.get("ReadInfo") if isinstance(v, dict) else None
                                if isinstance(ri, dict):
                                    out[h] = unwrap_value(ri)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(obj)
        return out

    def _bind_read_info(self, avatar_id: int, h: int, read_info: dict[str, Any]) -> dict[str, Any] | None:
        typ = str(read_info.get("Type") or "")
        trigger = str(read_info.get("TriggerKey") or "")
        try:
            idx_i = int(read_info.get("Index"))
        except Exception:
            return None
        if typ == "SkillParam":
            ctx = self._skill_by_avatar_trigger.get((avatar_id, trigger))
            if not ctx:
                return None
            params = list(ctx.get("param_list") or [])
            if idx_i < 0 or idx_i >= len(params):
                return None
            return {
                "value": float(params[idx_i]),
                "source": f"ConfigCharacter.DynamicValues[{h}].SkillParam.{trigger}[{idx_i}]",
                "confidence": "high",
                "read_info": read_info,
                "skill_id": ctx.get("skill_id"),
            }
        if typ == "SkillTreeParam":
            ctx = self.skill_tree_index.context(avatar_id, trigger)
            if not ctx:
                return None
            params = list(ctx.get("param_list") or [])
            if idx_i < 0 or idx_i >= len(params):
                return None
            return {
                "value": float(params[idx_i]),
                "source": f"ConfigCharacter.DynamicValues[{h}].SkillTreeParam.{trigger}[{idx_i}]",
                "confidence": "high",
                "read_info": read_info,
                "point_id": ctx.get("point_id"),
            }
        if typ == "SkillRank":
            m = RANK_RE.search(trigger)
            if not m:
                return None
            ctx = self.rank_index.context(avatar_id, int(m.group("rank")))
            if not ctx:
                return None
            params = list(ctx.get("param_list") or [])
            if idx_i < 0 or idx_i >= len(params):
                return None
            return {
                "value": float(params[idx_i]),
                "source": f"ConfigCharacter.DynamicValues[{h}].SkillRank.{trigger}[{idx_i}]",
                "confidence": "high",
                "read_info": read_info,
                "rank": ctx.get("rank"),
                "rank_id": ctx.get("rank_id"),
            }
        return None

    def _load_avatar(self, avatar_id: int) -> None:
        avatar_id = int(avatar_id)
        if avatar_id in self._loaded_avatars:
            return
        self._loaded_avatars.add(avatar_id)
        for rel in self._avatar_paths.get(avatar_id, []):
            try:
                if not self.source.exists(rel):
                    continue
                cfg = unwrap_value(self.source.read_json(rel))
            except Exception:
                continue
            for h, read_info in self._collect_dynamic_read_infos(cfg).items():
                h_i = int(h)
                typ = str((read_info or {}).get("Type") or "")
                if typ in {"", "None"}:
                    self.by_avatar_runtime_hash[(avatar_id, h_i)] = {
                        "kind": "config_character_runtime_dynamic_value",
                        "hash": h_i,
                        "read_info": read_info,
                        "source": f"ConfigCharacter.DynamicValues[{h_i}].{typ or 'None'}",
                    }
                    continue
                bound = self._bind_read_info(avatar_id, h_i, read_info)
                if bound is not None:
                    self.by_avatar_hash[(avatar_id, h_i)] = bound

    def binding(self, avatar_id: int, h: int) -> dict[str, Any] | None:
        self._load_avatar(int(avatar_id))
        return self.by_avatar_hash.get((int(avatar_id), int(h)))

    def runtime_binding(self, avatar_id: int, h: int) -> dict[str, Any] | None:
        self._load_avatar(int(avatar_id))
        return self.by_avatar_runtime_hash.get((int(avatar_id), int(h)))


class StatusBindingIndex:
    def __init__(self, source: TBGDSource):
        self.source = source
        self.skill_index = SkillParameterIndex(source)
        self.skill_tree_index = SkillTreeParameterIndex(source)
        self.rank_index = RankParameterIndex(source)
        self.character_dynamic_index = CharacterDynamicHashIndex(source, self.skill_index, self.skill_tree_index, self.rank_index)


def _iter_dict_values(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dict_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dict_values(v)


def _collect_referenced_points(status: dict[str, Any]) -> list[str]:
    out: list[str] = []
    def add(s: Any):
        if not isinstance(s, str):
            return
        for m in POINT_RE.finditer(s):
            p = m.group("point")
            if p not in out:
                out.append(p)
    add(status.get("status_id"))
    for obj in _iter_dict_values(status.get("triggers", [])):
        for key in ("PointTriggerKey", "point_trigger_key", "source_path", "status_id", "ModifierName", "modifier_name"):
            add(obj.get(key))
    return out


def _declared_dynamic_value_details(status: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    declared = ((status.get("modifier_metadata") or {}).get("dynamic_values_declared") or {})
    for group, keys in declared.items():
        for k in keys or []:
            try:
                out[int(k)] = {"kind": "modifier_dynamic_value", "group": group, "hash": int(k)}
            except Exception:
                pass
    return out


def _bind_hash_sequence(bindings: dict[int, dict[str, Any]], hashes: list[int], params: list[float], source: str, confidence: str, *, symbolic: dict[int, dict[str, Any]] | None = None) -> None:
    """Bind hash[i] to ParamList[i] without shifting across symbolic slots.

    Dynamic values declared by the modifier are runtime placeholders.  If such a
    hash occupies ParamList[i], later hashes must not slide left, otherwise a
    conservative binder turns unknown runtime values into wrong constants.
    """
    symbolic = symbolic or {}
    for i, h in enumerate(hashes):
        if h in bindings or h in symbolic or i >= len(params):
            continue
        bindings[h] = {"value": float(params[i]), "source": f"{source}.ParamList[{i}]", "confidence": confidence}


def infer_status_dynamic_bindings(status: dict[str, Any], index: StatusBindingIndex) -> dict[str, Any]:
    avatar_id = int(status.get("owner_avatar_id"))
    expr_refs = _collect_expr_refs(status.get("triggers", []))
    first_seen_hashes: list[int] = []
    for ref in expr_refs:
        for h in ref.get("hashes") or []:
            if h not in first_seen_hashes:
                first_seen_hashes.append(h)

    symbolic = _declared_dynamic_value_details(status)
    numeric: dict[int, dict[str, Any]] = {}
    contexts: list[dict[str, Any]] = []

    # 0) ConfigCharacter DynamicValues declarations are direct hash -> source
    # parameter bindings.  They cover many passive/maze status DynamicValues that
    # ConfigAbility only references by opaque hashes.
    char_bound = []
    for h in first_seen_hashes:
        if h in numeric or h in symbolic:
            continue
        rec = index.character_dynamic_index.binding(avatar_id, h)
        if rec is not None:
            numeric[h] = dict(rec)
            char_bound.append({"hash": h, **dict(rec)})
    if char_bound:
        contexts.append({"type": "config_character_dynamic_values", "bindings": char_bound})

    char_runtime_bound = []
    for h in first_seen_hashes:
        if h in numeric or h in symbolic:
            continue
        rec = index.character_dynamic_index.runtime_binding(avatar_id, h)
        if rec is not None:
            symbolic[h] = dict(rec)
            char_runtime_bound.append({"hash": h, **dict(rec)})
    if char_runtime_bound:
        contexts.append({"type": "config_character_runtime_dynamic_values", "bindings": char_runtime_bound})

    # 1) Explicit rank contexts have high confidence.  They are usually encoded
    # in status ids such as MAvatar_*_Rank06_* or by RankAbility names.
    rank_ctx = None
    m = RANK_RE.search(str(status.get("status_id") or ""))
    if m:
        rank_ctx = index.rank_index.context(avatar_id, int(m.group("rank")))
    if rank_ctx is None:
        rank_ctx = index.rank_index.context_by_ability(avatar_id, str((status.get("modifier_metadata") or {}).get("defined_in_ability") or ""))
    if rank_ctx and rank_ctx.get("param_list"):
        contexts.append({"type": "avatar_rank", **rank_ctx})
        rank_hashes = [h for h in first_seen_hashes if h not in numeric]
        _bind_hash_sequence(numeric, rank_hashes, list(rank_ctx.get("param_list") or []), f"AvatarRankConfig.Rank{rank_ctx.get('rank')}", "high", symbolic=symbolic)

    # 2) Explicit skill-tree points.  This covers statuses/effects tied to PointB1/B2/B3.
    for point in _collect_referenced_points(status):
        ctx = index.skill_tree_index.context(avatar_id, point)
        if not ctx or not ctx.get("param_list"):
            continue
        contexts.append({"type": "avatar_skill_tree", **ctx})
        point_hashes = [h for h in first_seen_hashes if h not in numeric]
        _bind_hash_sequence(numeric, point_hashes, list(ctx.get("param_list") or []), f"AvatarSkillTreeConfig.{point}", "medium", symbolic=symbolic)

    # 3) Source action params.  This is useful for passive/maze statuses, but it
    # stays medium confidence because source_action_ids can denote discovery
    # context rather than a concrete AddModifier invocation.
    for sid in status.get("source_action_ids") or []:
        try:
            sid_i = int(sid)
        except Exception:
            continue
        ctx = index.skill_index.skill_context(sid_i)
        params = list(ctx.get("param_list") or [])
        if not params:
            continue
        contexts.append({"type": "avatar_skill", "skill_id": sid_i, "trigger_key": ctx.get("trigger_key"), "level": ctx.get("level"), "param_list": params})
        skill_hashes = [h for h in first_seen_hashes if h not in numeric]
        _bind_hash_sequence(numeric, skill_hashes, params, f"AvatarSkillConfig.SkillID{sid_i}", "medium", symbolic=symbolic)
        # Some status formulas mix runtime modifier DynamicValues (for example an
        # attack target count captured earlier in the same callback) with one or
        # more concrete AvatarSkillConfig parameters.  The conservative sequence
        # binder above deliberately refuses to slide later hashes left across a
        # symbolic slot.  For each individual expression, however, if all
        # non-symbolic unbound hashes can be matched one-to-one to the skill
        # ParamList, bind just those concrete hashes while preserving the runtime
        # symbolic hashes.  This covers formulas like runtime_attack_count *
        # SkillP01[0] without reintroducing the old cross-slot misbinding bug.
        for ref in expr_refs:
            hashes = list(ref.get("hashes") or [])
            if not any(h in symbolic for h in hashes):
                continue
            unbound = [h for h in hashes if h not in numeric and h not in symbolic]
            if not unbound or len(unbound) > len(params):
                continue
            for i, h in enumerate(unbound):
                numeric[h] = {
                    "value": float(params[i]),
                    "source": f"AvatarSkillConfig.SkillID{sid_i}.ParamList[{i}] mixed-with-runtime-dynamic",
                    "confidence": "medium",
                    "mixed_symbolic_hashes": [sh for sh in hashes if sh in symbolic],
                }

    return {
        "numeric_bindings": {str(k): v for k, v in sorted(numeric.items())},
        "symbolic_bindings": {str(k): v for k, v in sorted(symbolic.items())},
        "binding_contexts": contexts,
        "first_seen_hashes": first_seen_hashes,
    }



def _symbolic_expression_ir(expr: dict[str, Any], numeric: dict[int, dict[str, Any]], symbolic: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Return an explicit symbolic expression description for unresolved formulas.

    The binder intentionally does not execute unsupported TBGD postfix opcodes in
    the combat kernel.  When all hashes are at least identified, preserve the
    expression as canonical audit IR so later lowering passes can map operands to
    runtime flags/properties without re-reading raw TurnBasedGameData.
    """
    hashes = _expr_hashes(expr)
    fixed_values = []
    try:
        fixed_values = list(_expr_fixed(expr))
    except Exception:
        fixed_values = []
    operands: list[dict[str, Any]] = []
    for h in hashes:
        if h in numeric:
            rec = dict(numeric[h])
            operands.append({
                "kind": "numeric_binding",
                "hash": h,
                "value": rec.get("value"),
                "source": rec.get("source"),
                "confidence": rec.get("confidence"),
                "binding": rec,
            })
        elif h in symbolic:
            operands.append({
                "kind": "runtime_dynamic_value",
                "hash": h,
                "binding": dict(symbolic[h]),
            })
        else:
            operands.append({"kind": "unbound_hash", "hash": h})
    return {
        "format": "hsr_symbolic_dynamic_expression_ir",
        "version": "v0.1",
        "expr_kind": _expr_kind(expr),
        "opcodes": expr.get("opcodes") or (expr.get("PostfixExpr") or {}).get("OpCodes"),
        "fixed_values": fixed_values,
        "dynamic_hashes": hashes,
        "operands": operands,
        "all_hashes_identified": all(op.get("kind") != "unbound_hash" for op in operands),
    }

def _evaluate_for_status(expr: dict[str, Any], numeric: dict[int, dict[str, Any]], symbolic: dict[int, dict[str, Any]]) -> dict[str, Any]:
    hashes = _expr_hashes(expr)
    if hashes and all(h in symbolic for h in hashes):
        return {
            "status": "symbolic_modifier_dynamic_value",
            "hashes": hashes,
            "bindings": {str(h): symbolic[h] for h in hashes},
            "symbolic_expression_ir": _symbolic_expression_ir(expr, numeric, symbolic),
        }
    value, trace = evaluate_dynamic_expr(expr, numeric)
    if value is not None:
        trace = dict(trace)
        trace["value"] = value
        trace["status"] = f"status_{trace.get('status')}"
        return trace
    missing = []
    for h in hashes:
        if h not in numeric and h not in symbolic:
            missing.append(h)
    if any(h in symbolic for h in hashes):
        return {
            "status": "unresolved_mixed_symbolic_dynamic_expr",
            "hashes": hashes,
            "symbolic_hashes": [h for h in hashes if h in symbolic],
            "numeric_bindings": {str(h): numeric[h] for h in hashes if h in numeric},
            "missing_hashes": missing,
            "symbolic_expression_ir": _symbolic_expression_ir(expr, numeric, symbolic),
        }
    out = {"status": "unresolved_status_dynamic_expr", "hashes": hashes, "missing_hashes": missing, "inner_trace": trace}
    if hashes and not missing:
        out["symbolic_expression_ir"] = _symbolic_expression_ir(expr, numeric, symbolic)
    return out


def bind_status_ir_bundle(status_ir_bundle: dict[str, Any], source: TBGDSource) -> dict[str, Any]:
    index = StatusBindingIndex(source)
    bundle = deepcopy(status_ir_bundle)
    summary = Counter()
    unresolved_hashes = Counter()
    status_summaries = []

    for status in bundle.get("statuses", []) or []:
        inferred = infer_status_dynamic_bindings(status, index)
        numeric = {int(k): v for k, v in (inferred.get("numeric_bindings") or {}).items()}
        symbolic = {int(k): v for k, v in (inferred.get("symbolic_bindings") or {}).items()}
        expr_refs = _collect_expr_refs(status.get("triggers", []))
        resolved_count = 0
        symbolic_count = 0
        path_set_failures = 0
        for ref in expr_refs:
            trace = _evaluate_for_status(ref["expr"], numeric, symbolic)
            summary[f"expr_{trace.get('status')}"] += 1
            if str(trace.get("status", "")).startswith("status_resolved"):
                resolved_count += 1
            elif trace.get("status") == "symbolic_modifier_dynamic_value":
                symbolic_count += 1
            for h in trace.get("missing_hashes") or []:
                unresolved_hashes[int(h)] += 1
            if not _set_path(status.get("triggers", []), ref["path"], "_resolve", trace):
                path_set_failures += 1
        status["dynamic_binding"] = inferred
        status["dynamic_binding_summary"] = {
            "dynamic_expression_count": len(expr_refs),
            "numeric_binding_count": len(numeric),
            "symbolic_binding_count": len(symbolic),
            "resolved_expression_count": resolved_count,
            "symbolic_expression_count": symbolic_count,
            "unresolved_expression_count": len(expr_refs) - resolved_count - symbolic_count,
            "resolve_attachment_failure_count": path_set_failures,
        }
        status_summaries.append({
            "owner_avatar_id": status.get("owner_avatar_id"),
            "namespace": status.get("namespace"),
            "status_id": status.get("status_id"),
            **status["dynamic_binding_summary"],
        })

    total_expr = sum(s.get("dynamic_expression_count", 0) for s in status_summaries)
    total_resolved = sum(s.get("resolved_expression_count", 0) for s in status_summaries)
    total_symbolic = sum(s.get("symbolic_expression_count", 0) for s in status_summaries)
    total_attach_failures = sum(s.get("resolve_attachment_failure_count", 0) for s in status_summaries)
    bundle["format"] = "hsr_bound_status_ir_bundle"
    bundle["version"] = "v0.2"
    bundle["source_status_ir_version"] = status_ir_bundle.get("version")
    bundle["binding_summary"] = {
        "format": "hsr_bound_status_ir_summary",
        "version": "v0.2",
        "status_count": len(bundle.get("statuses", []) or []),
        "dynamic_expression_count": total_expr,
        "resolved_expression_count": total_resolved,
        "symbolic_expression_count": total_symbolic,
        "unresolved_expression_count": total_expr - total_resolved - total_symbolic,
        "resolve_attachment_failure_count": total_attach_failures,
        "expression_status_counts": dict(summary.most_common()),
        "unresolved_hashes_top": {str(k): v for k, v in unresolved_hashes.most_common(50)},
        "top_statuses_by_unresolved_expression_count": sorted(status_summaries, key=lambda x: x.get("unresolved_expression_count", 0), reverse=True)[:20],
        "statuses": status_summaries,
    }
    return bundle


def write_bound_status_ir_bundle(status_ir_bundle_path: str | Path, output_dir: str | Path, tbgd_source: str | Path | TBGDSource) -> dict[str, Any]:
    src = tbgd_source if isinstance(tbgd_source, TBGDSource) else TBGDSource.open(tbgd_source)
    status_ir = json.loads(Path(status_ir_bundle_path).read_text(encoding="utf-8"))
    bound = bind_status_ir_bundle(status_ir, src)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bound_status_ir_bundle.json").write_text(json.dumps(bound, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = bound.get("binding_summary", {})
    (out_dir / "bound_status_ir_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
