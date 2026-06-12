from __future__ import annotations

"""Compile model-pack enemy templates into canonical simulator units.

The scanner introduced the generic enemy template shape.  This module is the
next, executable layer: it consumes the existing YAML enemy templates and emits
runtime-ready units/actions/statuses while keeping source evidence and coverage
notes.  It is deliberately conservative.  Text/graph-derived mechanics are
compiled only when the model template exposes an explicit core_mechanics key;
unknown mechanisms remain as evidence instead of being guessed.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any

from .tbgd_loader import TBGDSource, unwrap_value
from .enemy_ability_graph_lowerer import lower_monster_ability_file
import json
import re
import zipfile

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


ELEMENT_NORMALIZATION = {
    "Physical": "physical",
    "Fire": "fire",
    "Ice": "ice",
    "Thunder": "lightning",
    "Lightning": "lightning",
    "Wind": "wind",
    "Quantum": "quantum",
    "Imaginary": "imaginary",
}


TBGD_ZIP_CANDIDATES = (
    Path("/mnt/data/turnbasedgamedata-main.zip"),
    Path("/mnt/data/TurnBasedGameData-main.zip"),
    Path("/mnt/TurnBasedGameData-main.zip"),
)

# Full TurnBasedGameData zip files are large.  ConfigAI lookup is used by many
# regression checks, so cache both the zip directory and decoded JSON configs
# instead of rebuilding the namelist for every enemy template compile.
_TBGD_ZIP_HANDLE_CACHE: dict[str, tuple[zipfile.ZipFile, set[str]]] = {}
_TBGD_JSON_CONFIG_CACHE: dict[str, dict[str, Any] | None] = {}


def _fixed_value(node: Any, default: Any = None) -> Any:
    if not isinstance(node, dict):
        return default
    if isinstance(node.get("FixedValue"), dict) and "Value" in node["FixedValue"]:
        return node["FixedValue"].get("Value")
    if "Value" in node:
        return node.get("Value")
    return default


def _score_value(node: Any, default: float = 0.0) -> float:
    """Read ConfigAI score values such as SuccessScore/CheckScore.

    TBGD stores scores as {"Value": n} in current Monster ConfigAI files.
    Keep this tiny and permissive so unknown score nodes simply become 0
    rather than turning the AI decision unsupported.
    """
    raw = _fixed_value(node, default) if isinstance(node, dict) else node
    try:
        return float(raw)
    except Exception:
        return float(default)



def _hash_key(node: Any, prefix: str = "custom_bool") -> str:
    """Return a stable runtime flag key for hashed TBGD custom values.

    Many ConfigAI predicates store only a numeric hash.  The real game resolves
    this through engine-side custom values; the simulator keeps the hash as an
    explicit flag key so exact-route tests/model templates can set it without
    pretending to know the original string name.
    """
    if isinstance(node, dict):
        if "Hash" in node:
            return f"{prefix}:{node.get('Hash')}"
        if "Value" in node:
            return f"{prefix}:{node.get('Value')}"
    return f"{prefix}:{node}"


def _target_type_alias(target_type: Any) -> str:
    if isinstance(target_type, dict):
        typ = str(target_type.get("$type", "")).split(".")[-1]
        if typ == "TargetAlias":
            return str(target_type.get("Alias") or "")
        if typ == "TargetSequence":
            for item in target_type.get("Sequence") or []:
                alias = _target_type_alias(item)
                if alias:
                    return alias
    return ""


def _compare_op(compare_type: Any) -> str:
    mapping = {
        "Equal": "==",
        "NotEqual": "!=",
        "Greater": ">",
        "GreaterEqual": ">=",
        "Less": "<",
        "LessEqual": "<=",
    }
    return mapping.get(str(compare_type), "==")


def _zip_handle_and_names(zp: Path) -> tuple[zipfile.ZipFile, set[str]]:
    key = str(zp.resolve())
    cached = _TBGD_ZIP_HANDLE_CACHE.get(key)
    if cached is not None:
        return cached
    z = zipfile.ZipFile(zp)
    cached = (z, set(z.namelist()))
    _TBGD_ZIP_HANDLE_CACHE[key] = cached
    return cached


def _read_tbgd_json_config(config_path: str | None) -> dict[str, Any] | None:
    if not config_path:
        return None
    rel = str(config_path).replace("\\", "/").lstrip("/")
    cache_key = rel
    if cache_key in _TBGD_JSON_CONFIG_CACHE:
        return deepcopy(_TBGD_JSON_CONFIG_CACHE[cache_key])
    suffixes = [rel]
    if not rel.startswith("turnbasedgamedata-main/"):
        suffixes.append("turnbasedgamedata-main/" + rel)
    for zp in TBGD_ZIP_CANDIDATES:
        if not zp.exists():
            continue
        try:
            z, names = _zip_handle_and_names(zp)
            target = None
            for cand in suffixes:
                if cand in names:
                    target = cand
                    break
            if target is None:
                matches = [n for n in names if n.endswith(rel)]
                target = matches[0] if matches else None
            if target:
                data = json.loads(z.read(target).decode("utf-8"))
                _TBGD_JSON_CONFIG_CACHE[cache_key] = data
                return deepcopy(data)
        except Exception:
            continue
    _TBGD_JSON_CONFIG_CACHE[cache_key] = None
    return None


def _target_index_from_target_sequence(target_type: Any) -> int | None:
    if not isinstance(target_type, dict):
        return None
    typ = str(target_type.get("$type", "")).split(".")[-1]
    if typ == "TargetSequence":
        for item in target_type.get("Sequence") or []:
            if isinstance(item, dict) and str(item.get("$type", "")).endswith("TargetIndex"):
                return _target_index_from_target_sequence(item)
    if typ == "TargetIndex":
        val = _fixed_value(target_type.get("IndexValue"), None)
        try:
            return int(val) if val is not None else 0
        except Exception:
            return 0
    return None




def _target_sequence_info(target_type: Any) -> dict[str, Any]:
    """Lower common ConfigAI TargetSequence into deterministic target semantics.

    v0.54 keeps TargetFilter predicates as executable subconditions.  This is
    needed for predicates such as ByCompareTargetCount(AllDarkTeam ->
    TargetFilter(ByCheckCustomValueBool)), otherwise enemy AI branches that ask
    "how many units with this custom flag exist" always count the full side.
    """
    info = {
        "side": _target_side_from_target_type(target_type),
        "alias": _target_type_alias(target_type),
        "formation_index": None,
        "formation_order": "asc",
        "filters": [],
    }
    if not isinstance(target_type, dict):
        return info
    typ = str(target_type.get("$type", "")).split(".")[-1]
    if typ == "TargetSequence":
        for item in target_type.get("Sequence") or []:
            if not isinstance(item, dict):
                continue
            item_typ = str(item.get("$type", "")).split(".")[-1]
            if item_typ == "TargetAlias":
                info["alias"] = str(item.get("Alias") or info.get("alias") or "")
                info["side"] = _target_side_from_target_type(item)
            elif item_typ == "TargetSortByFormation":
                info["formation_order"] = "desc" if bool(item.get("HighestFirst", False)) else "asc"
            elif item_typ == "TargetIndex":
                info["formation_index"] = _target_index_from_target_sequence(item)
            elif item_typ == "TargetFilter":
                info.setdefault("filters", []).append(_lower_ai_predicate(item.get("Predicate")))
        return info
    if typ == "TargetIndex":
        info["formation_index"] = _target_index_from_target_sequence(target_type)
    if typ == "TargetFilter":
        info.setdefault("filters", []).append(_lower_ai_predicate(target_type.get("Predicate")))
    return info


def _ai_variables_from_config(ai_config: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(ai_config, dict):
        return out
    for var in ai_config.get("VariableList") or []:
        if not isinstance(var, dict):
            continue
        name = str(var.get("Name") or "")
        if not name:
            continue
        typ = str(var.get("$type", "")).split(".")[-1]
        if typ == "AIVariableBool":
            out[name] = bool(var.get("Value", False))
        else:
            out[name] = var.get("Value")
    return out


def _skill_usability_from_axis(axis: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(axis, dict):
        return None
    typ = str(axis.get("$type", "")).split(".")[-1]
    if typ != "CheckSkillUsabilityAxis":
        return None
    skill = str(axis.get("SkillName") or "")
    if not skill:
        return None
    return {
        "skill": skill,
        "initial_cd": int(axis.get("InitialCD", 0) or 0),
        "cd": int(axis.get("CD", 0) or 0),
        "source_axis": typ,
    }

def _target_side_from_target_type(target_type: Any) -> str:
    if not isinstance(target_type, dict):
        return "ally"
    typ = str(target_type.get("$type", "")).split(".")[-1]
    if typ == "TargetSequence":
        for item in target_type.get("Sequence") or []:
            side = _target_side_from_target_type(item)
            if side:
                return side
    if typ == "TargetAlias":
        alias = str(target_type.get("Alias") or "")
        if alias in {"Caster", "Self"}:
            return "actor"
        if "LightTeam" in alias or "Ally" in alias:
            return "ally"
        if "Dark" in alias or "Enemy" in alias:
            return "enemy"
    return "ally"



def _target_alias_policy(alias: str) -> str:
    alias_s = str(alias or "")
    if alias_s in {"Caster", "Self"}:
        return "self"
    if alias_s in {"AllLightTeam", "AllAlly", "AllAllyTeam", "AllPlayer"} or "LightTeam" in alias_s:
        return "all_allies"
    if alias_s in {"AllDarkTeam", "AllEnemy", "AllMonster", "AllTeammate"} or "DarkTeam" in alias_s:
        return "all_enemies"
    if "Summoner" in alias_s:
        return "summoner"
    return "first_ally"


def _lower_ai_selector(selector: Any) -> dict[str, Any]:
    """Lower common ConfigAI target selectors into deterministic target policies.

    This is still a conservative baseline.  Selectors either filter candidates
    or rank them deterministically; unsupported score/random details remain
    visible in the lowered selector instead of being guessed.
    """
    if not isinstance(selector, dict):
        return {"type": "default", "target_policy": "first_ally"}
    typ = str(selector.get("$type", "")).split(".")[-1]
    inverse = bool(selector.get("InverseResultFlag", False))
    if typ == "AIModifierNameSelector":
        return {
            "type": "target_with_status",
            "status_id": str(selector.get("ModifierName") or ""),
            "target_policy": "all_allies",
            "target_side": "ally",
            "inverse": inverse,
            "source_selector": typ,
        }
    if typ == "AITaskTargetTypeSelector":
        target_type = selector.get("TargetType") or {}
        policy = _target_alias_policy((target_type.get("Alias") if isinstance(target_type, dict) else None) or "")
        side = _target_side_from_target_type(target_type)
        info = _target_sequence_info(target_type)
        return {"type": "target_policy", "target_policy": policy, "target_side": side, "target_sequence": info, "inverse": inverse, "source_selector": typ}
    if typ == "AIMonsterIDSelector":
        return {"type": "monster_id", "monster_ids": [str(x) for x in selector.get("MonsterIDList") or []], "target_policy": "all_enemies", "target_side": "enemy", "inverse": inverse, "source_selector": typ}
    if typ == "AIMonsterRankSelector":
        ranks = [str(x) for x in selector.get("MonsterRankList") or []]
        return {"type": "monster_rank", "ranks": ranks, "property_strategy": str(selector.get("PropertyStrategy") or ""), "target_policy": "all_enemies", "target_side": "enemy", "inverse": inverse, "source_selector": typ}
    if typ == "AIPropertySelector":
        return {
            "type": "property_extreme",
            "property": str(selector.get("Property") or "CurrentHP"),
            "strategy": str(selector.get("PropertyStrategy") or "MinRatio"),
            "target_policy": "all_allies",
            "target_side": "ally",
            "inverse": inverse,
            "source_selector": typ,
        }
    if typ == "AIBehaviorFlagSelector":
        return {"type": "behavior_flag", "flag": str(selector.get("BehaviorFlag") or ""), "target_policy": "all_enemies", "target_side": "enemy", "inverse": inverse, "source_selector": typ}
    if typ == "AICustomStringTagSelector":
        return {"type": "custom_string_tag", "tag": str(selector.get("CustomStringTag") or ""), "target_policy": "all_enemies", "target_side": "enemy", "inverse": inverse, "source_selector": typ}
    if typ == "AIComplexSkillAISelector":
        return {"type": "complex_skill_source", "skill": str(selector.get("UseSourceInSkillConfig") or ""), "target_policy": "all_allies", "target_side": "ally", "inverse": inverse, "source_selector": typ}
    if typ == "AIComposeSelector":
        compose = str(selector.get("ComposeType") or "ByAnd")
        return {"type": "compose", "compose": "any" if compose == "ByOr" else "all", "selectors": [_lower_ai_selector(x) for x in selector.get("SelectorList") or []], "source_selector": typ, "inverse": inverse}
    return {"type": "unsupported_selector", "selector_type": typ}



def _dynamic_value_key_from_node(node: Any, default: str = "AIFlag") -> str:
    """Resolve ConfigAI dynamic-value keys into explicit runtime unit flags.

    Named DynamicKey values are preserved directly.  Hash-only expressions are
    exposed as ``dynamic_hash:<hash>`` so exact-route tests can seed them without
    pretending to recover engine-private names.
    """
    if isinstance(node, str):
        return node
    if node is not None and not isinstance(node, dict):
        return str(node)
    if isinstance(node, dict):
        if "Value" in node:
            return str(node.get("Value"))
        if "Hash" in node:
            return f"dynamic_hash:{node.get('Hash')}"
        expr = node.get("PostfixExpr") if isinstance(node.get("PostfixExpr"), dict) else None
        if isinstance(expr, dict):
            hashes = expr.get("DynamicHashes") or []
            if hashes:
                return f"dynamic_hash:{hashes[0]}"
        dyn_key = node.get("DynamicKey") if isinstance(node.get("DynamicKey"), dict) else None
        if isinstance(dyn_key, dict):
            return _dynamic_value_key_from_node(dyn_key, default=default)
    return str(default)


def _effect_target_from_target_type(target_type: Any) -> str:
    alias = _target_type_alias(target_type)
    if alias in {"Caster", "Self"}:
        return "actor"
    if alias == "ParamEntity":
        return "param_entity"
    policy = _target_alias_policy(alias)
    if policy == "all_allies":
        return "all_allies"
    if policy == "all_enemies":
        return "all_enemies"
    if policy == "self":
        return "actor"
    return "actor"


def _switch_dynamic_condition(switch_node: Any, case_node: Any) -> dict[str, Any]:
    key = _dynamic_value_key_from_node(switch_node, default="switch_dynamic_value")
    return {
        "left": f"unit:actor:flags.{key}",
        "op": "==",
        "right": _fixed_value(case_node, 0),
        "source_predicate": "SwitchCaseByDynamicValue",
    }

def _target_count_spec(target_type: Any, alive_only: Any = True) -> dict[str, Any]:
    info = _target_sequence_info(target_type)
    alias = info.get("alias") or ((target_type.get("Alias") if isinstance(target_type, dict) else None) or "")
    return {
        "side": info.get("side", "ally"),
        "alias": alias,
        "formation_order": info.get("formation_order", "asc"),
        "formation_index": info.get("formation_index"),
        "filters": deepcopy(info.get("filters") or []),
        "alive_only": bool(alive_only),
        "target_policy": _target_alias_policy(alias) if alias else None,
    }


def _lower_ai_predicate(pred: Any) -> dict[str, Any]:
    if not isinstance(pred, dict):
        return {"unsupported_ai_predicate": str(pred)}
    typ = str(pred.get("$type", "")).split(".")[-1]
    if typ in {"ByAnd", "ByAny"}:
        items = [_lower_ai_predicate(p) for p in pred.get("PredicateList") or []]
        return {"all" if typ == "ByAnd" else "any": items}
    if typ == "ByCompareMonsterPhase":
        return {
            "left": "unit:actor:flags.current_phase",
            "op": _compare_op(pred.get("CompareType")),
            "right": _fixed_value(pred.get("CompareValue"), 1),
            "source_predicate": typ,
        }
    if typ == "ByCompareDynamicValue":
        key = ((pred.get("DynamicKey") or {}).get("Value")) or "AIFlag"
        return {
            "left": f"unit:actor:flags.{key}",
            "op": _compare_op(pred.get("CompareType")),
            "right": _fixed_value(pred.get("CompareValue"), 0),
            "source_predicate": typ,
        }
    if typ == "ByTargetAliveState":
        mask = str(pred.get("AliveStateMask") or "Mask_AliveOnly")
        seq_info = _target_sequence_info(pred.get("TargetType"))
        return {
            "target_alive_state": {
                "side": seq_info.get("side", "ally"),
                "formation_index": seq_info.get("formation_index"),
                "formation_order": seq_info.get("formation_order", "asc"),
                "alive": mask != "Mask_DeadOnly",
                "mask": mask,
            },
            "source_predicate": typ,
        }
    if typ == "ByNot":
        return {"not": _lower_ai_predicate(pred.get("Predicate"))}
    if typ == "ByCompareSkillUsageLimit":
        return {
            "enemy_skill_usage_delay_ready": {
                "skill": str(pred.get("IDFromTriggerKey") or ""),
                "action_delay": _fixed_value(pred.get("ActionDelay"), 0),
            },
            "source_predicate": typ,
        }
    if typ == "ByIsContainModifier":
        raw_name = pred.get("ModifierName")
        status_id = ((raw_name or {}).get("Value") if isinstance(raw_name, dict) else raw_name) or ""
        return {
            "unit_has_status": {
                "target": "param_entity" if _target_type_alias(pred.get("TargetType")) == "ParamEntity" else "actor",
                "status_id": str(status_id),
                "inverse": bool(pred.get("Inverse", False)),
            },
            "source_predicate": typ,
        }
    if typ == "ByRandomChance":
        return {
            "chance_gate": {"chance": _fixed_value(pred.get("Chance"), 0.0), "event_id": f"enemy_ai:{typ}"},
            "source_predicate": typ,
        }
    if typ == "ByCompareHPRatio":
        tt = pred.get("TargetType")
        info = _target_sequence_info(tt)
        return {
            "target_hp_ratio": {
                "target_policy": _target_alias_policy(info.get("alias") or "Caster"),
                "side": info.get("side", _target_side_from_target_type(tt)),
                "filters": deepcopy(info.get("filters") or []),
                "op": _compare_op(pred.get("CompareType")),
                "value": _fixed_value(pred.get("CompareValue"), 0.0),
            },
            "source_predicate": typ,
        }
    if typ == "ByCompareTargetCount":
        spec = _target_count_spec(pred.get("TargetType"), pred.get("AliveOnly", True))
        spec.update({"op": _compare_op(pred.get("CompareType")), "value": _fixed_value(pred.get("Number"), 0)})
        return {"target_count": spec, "source_predicate": typ}
    if typ == "ByCheckCustomValueBool":
        return {
            "unit_custom_value_bool": {
                "target": "param_entity" if _target_type_alias(pred.get("TargetType")) == "ParamEntity" else "actor",
                "key": _hash_key(pred.get("Key"), "custom_bool"),
                "inverse": bool(pred.get("Inverse", False)),
            },
            "source_predicate": typ,
        }
    if typ in {"ByCompareMonsterID", "ByCompareMonsterTemplateID"}:
        key = "monster_id" if typ == "ByCompareMonsterID" else "monster_template_id"
        value_node = pred.get("TargetMonsterID") if typ == "ByCompareMonsterID" else pred.get("TargetMonsterTemplateID")
        return {
            "unit_identity_compare": {
                "target": "param_entity" if _target_type_alias(pred.get("TargetType")) == "ParamEntity" else "actor",
                "field": key,
                "op": "!=" if bool(pred.get("Inverse", False)) else "==",
                "value": _fixed_value(value_node, None),
            },
            "source_predicate": typ,
        }
    if typ == "ByCompareMonsterRank":
        return {
            "unit_identity_compare": {
                "target": "param_entity" if _target_type_alias(pred.get("TargetType")) == "ParamEntity" else "actor",
                "field": "rank",
                "op": _compare_op(pred.get("CompareType")),
                "value": _fixed_value(pred.get("CompareValue"), pred.get("CompareValue")),
            },
            "source_predicate": typ,
        }
    if typ == "ByCompareModifierValue":
        return {
            "modifier_value_compare": {
                "target": "actor",
                "status_id": str(pred.get("ModifierName") or ""),
                "value_type": str(pred.get("ValueType") or "Layer"),
                "op": _compare_op(pred.get("CompareType")),
                "value": _fixed_value(pred.get("CompareValue"), 0),
            },
            "source_predicate": typ,
        }
    if typ == "ByContainBehaviorFlag":
        return {
            "unit_behavior_flag": {
                "target": "param_entity" if _target_type_alias(pred.get("TargetType")) == "ParamEntity" else "actor",
                "flag": str(pred.get("Flag") or ""),
                "inverse": bool(pred.get("Inverse", False)),
            },
            "source_predicate": typ,
        }
    if typ == "ByCompareCharacterNumber":
        spec = _target_count_spec(pred.get("TargetType"), True)
        spec["filters"] = [_lower_ai_predicate(pred.get("Predicate"))]
        spec.update({"op": _compare_op(pred.get("CompareType")), "value": _fixed_value(pred.get("CompareNumber"), 0)})
        return {"target_count": spec, "source_predicate": typ}
    if typ == "ByCompareAliveEnemyNumber":
        return {
            "alive_enemy_number": {
                "op": _compare_op(pred.get("CompareType")),
                "value": _fixed_value(pred.get("CompareValue"), 0),
            },
            "source_predicate": typ,
        }
    if typ == "ByCompareBP":
        return {
            "battle_point_compare": {
                "op": _compare_op(pred.get("CompareType")),
                "value": _fixed_value(pred.get("CompareValue"), 0),
            },
            "source_predicate": typ,
        }
    if typ == "ByCompareTarget":
        left_alias = _target_type_alias(pred.get("TargetType")) or "ParamEntity"
        right_alias = _target_type_alias(pred.get("CompareType")) or "Caster"
        return {
            "target_identity_compare": {
                "left": "param_entity" if left_alias == "ParamEntity" else "actor",
                "right": "actor" if right_alias in {"Caster", "Self"} else str(right_alias),
                "inverse": bool(pred.get("Inverse", False)),
            },
            "source_predicate": typ,
        }
    return {"unsupported_ai_predicate": typ}


def _and_conditions(*conds: Any) -> Any:
    flat = []
    for cond in conds:
        if cond in (None, {}, True):
            continue
        if isinstance(cond, dict) and set(cond.keys()) == {"all"}:
            flat.extend(cond.get("all") or [])
        else:
            flat.append(cond)
    if not flat:
        return True
    if len(flat) == 1:
        return flat[0]
    return {"all": flat}


def _not_condition(cond: Any) -> Any:
    if cond in (None, {}, True):
        return False
    return {"not": cond}


def _effect_from_define_dynamic_value(task: dict[str, Any]) -> dict[str, Any] | None:
    key = _dynamic_value_key_from_node(task.get("DynamicKey"), default="AIFlag")
    if not key:
        return None
    value_node = task.get("ResetValue") if "ResetValue" in task else task.get("Value")
    return {
        "type": "set_unit_flag",
        "target": _effect_target_from_target_type(task.get("TargetType")),
        "key": str(key),
        "value": _fixed_value(value_node, 0),
        "source_task": str(task.get("$type", "DefineDynamicValue")).split(".")[-1],
    }


def _effect_from_set_dynamic_value_by_add_value(task: dict[str, Any]) -> dict[str, Any] | None:
    key = _dynamic_value_key_from_node(task.get("Key") or task.get("DynamicKey"), default="AIFlag")
    if not key:
        return None
    out = {
        "type": "modify_unit_counter",
        "target": _effect_target_from_target_type(task.get("TargetType")),
        "key": str(key),
        "amount": _fixed_value(task.get("AddValue"), 0),
        "source_task": "SetDynamicValueByAddValue",
    }
    if task.get("Min") is not None:
        out["min"] = _fixed_value(task.get("Min"), 0)
    if task.get("Max") is not None:
        out["max"] = _fixed_value(task.get("Max"), 0)
    return out


def _effect_from_set_dynamic_value_by_copying(task: dict[str, Any]) -> dict[str, Any] | None:
    key = _dynamic_value_key_from_node(task.get("DynamicKey") or task.get("Key"), default="AIFlag")
    source_key = _dynamic_value_key_from_node(task.get("ReadDynamicKey") or task.get("SourceKey") or task.get("CopyKey"), default="AIFlag")
    if not key:
        return None
    return {
        "type": "copy_unit_flag",
        "target": _effect_target_from_target_type(task.get("TargetType")),
        "key": str(key),
        "source_key": str(source_key),
        "source_target": _effect_target_from_target_type(task.get("ReadTargetType") or task.get("SourceTargetType") or task.get("TargetType")),
        "source_task": "SetDynamicValueByCopying",
    }


def _effect_from_set_dynamic_value_by_character_count(task: dict[str, Any]) -> dict[str, Any] | None:
    key = _dynamic_value_key_from_node(task.get("DynamicKey"), default="character_count")
    return {
        "type": "set_unit_flag_from_target_count",
        "target": _effect_target_from_target_type(task.get("TargetType")),
        "key": str(key),
        "target_spec": _target_count_spec(task.get("ReadTargetType") or task.get("TargetType"), True),
        "filters": [_lower_ai_predicate(task.get("Predicate"))] if task.get("Predicate") is not None else [],
        "source_task": "SetDynamicValueByCharacterCount",
    }


def _effect_from_add_modifier(task: dict[str, Any]) -> dict[str, Any] | None:
    raw_name = task.get("ModifierName")
    name = ((raw_name or {}).get("Value") if isinstance(raw_name, dict) else raw_name)
    if not name:
        return None
    return {
        "type": "add_status",
        "target": _effect_target_from_target_type(task.get("TargetType")),
        "status": {"id": str(name), "tags": ["enemy_ai_modifier"], "modifiers": {str(name): True}},
        "source_task": "AddModifier",
    }


def _effect_from_remove_modifier(task: dict[str, Any]) -> dict[str, Any] | None:
    raw_name = task.get("ModifierName")
    name = ((raw_name or {}).get("Value") if isinstance(raw_name, dict) else raw_name)
    if not name:
        return None
    return {"type": "remove_status", "target": _effect_target_from_target_type(task.get("TargetType")), "status_id": str(name), "source_task": "RemoveModifier"}


def _ai_decisions_from_tasks(task_list: list[Any], base_condition: Any, pre_effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    effects = [deepcopy(e) for e in pre_effects]
    for task in task_list or []:
        if not isinstance(task, dict):
            continue
        typ = str(task.get("$type", "")).split(".")[-1]
        if typ in {"DefineDynamicValue", "SetDynamicValue"}:
            eff = _effect_from_define_dynamic_value(task)
            if eff:
                effects.append(eff)
            continue
        if typ == "SetDynamicValueByAddValue":
            eff = _effect_from_set_dynamic_value_by_add_value(task)
            if eff:
                effects.append(eff)
            continue
        if typ == "SetDynamicValueByCopying":
            eff = _effect_from_set_dynamic_value_by_copying(task)
            if eff:
                effects.append(eff)
            continue
        if typ == "SetDynamicValueByCharacterCount":
            eff = _effect_from_set_dynamic_value_by_character_count(task)
            if eff:
                effects.append(eff)
            continue
        if typ == "AddModifier":
            eff = _effect_from_add_modifier(task)
            if eff:
                effects.append(eff)
            continue
        if typ == "RemoveModifier":
            eff = _effect_from_remove_modifier(task)
            if eff:
                effects.append(eff)
            continue
        if typ == "UseSkill":
            skill = str(task.get("SkillName") or "")
            if skill:
                decisions.append({"skill": skill, "condition": deepcopy(base_condition), "pre_effects": deepcopy(effects)})
            continue
        if typ == "SelectAISkillTarget":
            skill = str(task.get("SkillName") or "")
            if skill:
                decisions.append({
                    "skill": skill,
                    "condition": deepcopy(base_condition),
                    "pre_effects": deepcopy(effects),
                    "target_selector": _lower_ai_selector(task.get("Selector")),
                    "source_task": "SelectAISkillTarget",
                })
            continue
        if typ == "UseSequencedSkill":
            decisions.append({"skill": "__sequenced_skill__", "condition": deepcopy(base_condition), "pre_effects": deepcopy(effects), "source_task": "UseSequencedSkill"})
            continue
        if typ == "RandomConfig":
            odds = [_fixed_value(x, 1.0) for x in task.get("OddsList") or []]
            for branch_idx, branch in enumerate(task.get("TaskList") or []):
                nested = [branch] if isinstance(branch, dict) else (branch if isinstance(branch, list) else [])
                rows = _ai_decisions_from_tasks(nested, base_condition, effects)
                for row in rows:
                    row["random_branch_index"] = branch_idx
                    row["random_weight"] = float(odds[branch_idx]) if branch_idx < len(odds) else 1.0
                    row.setdefault("source_task", "RandomConfig")
                    decisions.append(row)
            continue
        if typ == "Retarget":
            pred = _lower_ai_predicate(task.get("Predicate"))
            target_spec = _target_count_spec(task.get("TargetType"), True)
            target_spec.setdefault("filters", []).append(pred)
            target_spec.update({"op": ">=", "value": 1})
            retarget_cond = {"target_count": target_spec, "source_predicate": "RetargetHasCandidate"}
            selector = {
                "type": "target_policy",
                "target_policy": target_spec.get("target_policy") or ("all_enemies" if target_spec.get("side") == "enemy" else "all_allies"),
                "target_side": target_spec.get("side", "ally"),
                "target_sequence": target_spec,
                "source_selector": "Retarget",
            }
            for row in _ai_decisions_from_tasks(task.get("TaskList") or [], _and_conditions(base_condition, retarget_cond), effects):
                row.setdefault("target_selector", deepcopy(selector))
                row.setdefault("source_task", "Retarget")
                decisions.append(row)
            decisions.extend(_ai_decisions_from_tasks(task.get("FailedTaskList") or [], _and_conditions(base_condition, _not_condition(retarget_cond)), effects))
            continue
        if typ == "SwitchCaseByDynamicValue":
            for case in task.get("CaseTaskList") or []:
                if not isinstance(case, dict):
                    continue
                case_cond = _switch_dynamic_condition(task.get("Switch"), case.get("Case"))
                decisions.extend(_ai_decisions_from_tasks(case.get("TaskList") or [], _and_conditions(base_condition, case_cond), effects))
            if task.get("DefaultTaskList"):
                decisions.extend(_ai_decisions_from_tasks(task.get("DefaultTaskList") or [], base_condition, effects))
            continue
        if typ == "PredicateTaskList":
            pred = _lower_ai_predicate(task.get("Predicate"))
            decisions.extend(_ai_decisions_from_tasks(task.get("SuccessTaskList") or [], _and_conditions(base_condition, pred), effects))
            decisions.extend(_ai_decisions_from_tasks(task.get("FailedTaskList") or [], _and_conditions(base_condition, _not_condition(pred)), effects))
            continue
        if typ == "SequenceConfig":
            decisions.extend(_ai_decisions_from_tasks(task.get("TaskList") or [], base_condition, effects))
            continue
    return decisions


def _extract_ai_decisions_from_config(ai_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(ai_config, dict):
        return []
    out: list[dict[str, Any]] = []

    def visit_decision(node: Any, path: str) -> None:
        if isinstance(node, list):
            for i, item in enumerate(node):
                visit_decision(item, f"{path}[{i}]")
            return
        if not isinstance(node, dict):
            return
        typ = str(node.get("$type", "")).split(".")[-1]
        if typ == "AIDecisionConfig":
            conds: list[Any] = []
            skill_cd_specs: list[dict[str, Any]] = []
            score_axes: list[dict[str, Any]] = []
            base_score = 0.0
            for axis in node.get("ConsiderAxisList") or []:
                if not isinstance(axis, dict):
                    continue
                axis_type = str(axis.get("$type", "")).split(".")[-1]
                axis_predicate = None
                if axis.get("Predicate") is not None:
                    axis_predicate = _lower_ai_predicate(axis.get("Predicate"))
                    # Existing v0.50-v0.55 behavior treated axis predicates as
                    # availability gates.  Keep that conservative contract while
                    # also preserving SuccessScore for deterministic scoring.
                    conds.append(axis_predicate)
                cd_spec = _skill_usability_from_axis(axis)
                if cd_spec:
                    skill_cd_specs.append(cd_spec)
                    axis_predicate = {"enemy_skill_cooldown_ready": cd_spec}
                    conds.append(axis_predicate)
                if axis_type == "ChoseSequencedSkillAxis":
                    # Common sequence AI has no explicit predicate, only a score
                    # saying the sequenced skill branch is preferred when present.
                    base_score += _score_value(axis.get("CheckScore"), 0.0)
                if axis.get("SuccessScore") is not None:
                    score_axes.append({
                        "condition": deepcopy(axis_predicate) if axis_predicate is not None else True,
                        "score": _score_value(axis.get("SuccessScore"), 0.0),
                        "source_axis": axis_type,
                        "score_field": "SuccessScore",
                    })
                if axis.get("CheckScore") is not None and axis_type != "ChoseSequencedSkillAxis":
                    score_axes.append({
                        "condition": deepcopy(axis_predicate) if axis_predicate is not None else True,
                        "score": _score_value(axis.get("CheckScore"), 0.0),
                        "source_axis": axis_type,
                        "score_field": "CheckScore",
                    })
            base = _and_conditions(*conds)
            root = node.get("RootTask") or {}
            tasks = root.get("TaskList") if isinstance(root, dict) else []
            rows = _ai_decisions_from_tasks(tasks or [], base, [])
            for j, row in enumerate(rows):
                row.setdefault("decision_name", node.get("DecisionName"))
                row.setdefault("source_path", f"{path}/RootTask#{j}")
                row.setdefault("score_evaluator_type", node.get("ScoreEvaluatorType") or "DefaultDSE")
                if base_score:
                    row["ai_score_base"] = base_score
                if score_axes:
                    row["ai_score_axes"] = deepcopy(score_axes)
                if skill_cd_specs:
                    row.setdefault("skill_usability", deepcopy(skill_cd_specs))
                out.append(row)
            return
        for key, val in node.items():
            if isinstance(val, (dict, list)):
                visit_decision(val, f"{path}/{key}")

    visit_decision(ai_config.get("DecisionList") or [], "/DecisionList")
    return out

def _enemy_ai_decisions_from_tbgd(unit: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = unit.get("raw") if isinstance(unit.get("raw"), dict) else {}
    ai_path = ((raw.get("ai") or {}).get("ai_path"))
    if not ai_path:
        for p in (raw.get("raw_source_trace") or {}).get("config_paths") or []:
            if "ConfigAI/" in str(p):
                ai_path = str(p)
                break
    cfg = _read_tbgd_json_config(ai_path)
    decisions = _extract_ai_decisions_from_config(cfg)
    ai_vars = _ai_variables_from_config(cfg)
    cd_cfg: dict[str, dict[str, Any]] = {}
    initial_cd: dict[str, int] = {}
    for d in decisions:
        for spec in d.get("skill_usability") or []:
            skill = str(spec.get("skill") or "")
            if not skill:
                continue
            cd_cfg[skill] = {"initial_cd": int(spec.get("initial_cd", 0) or 0), "cd": int(spec.get("cd", 0) or 0)}
            if int(spec.get("initial_cd", 0) or 0) > 0:
                initial_cd[skill] = int(spec.get("initial_cd", 0) or 0)
    audit = {
        "ai_path": ai_path,
        "tbgd_config_available": cfg is not None,
        "decision_count": len(decisions),
        "predicate_types_lowered": sorted({str(deepcopy(d.get("condition"))).split("source_predicate': '")[-1].split("'")[0] for d in decisions if "source_predicate" in str(d.get("condition"))}),
        "ai_variables": ai_vars,
        "skill_cooldown_config": cd_cfg,
        "initial_skill_cooldowns": initial_cd,
    }
    return decisions, audit


def _load_yaml(path: str | Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to compile enemy templates")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _norm_element(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value)
    return ELEMENT_NORMALIZATION.get(s, s.lower())


def _skill_multiplier(skill: dict[str, Any]) -> float | None:
    params = skill.get("params") or []
    if not params:
        return None
    try:
        return float(params[0])
    except Exception:
        return None


def _target_policy_from_skill(skill: dict[str, Any]) -> str:
    tag = str(skill.get("tag_chs") or skill.get("skill_tag") or "")
    desc = str(skill.get("description_chs") or "")
    name = str(skill.get("name_chs") or "")
    # Enemy targeting must preserve formation semantics because sweep/spread/split
    # patterns change hit count, toughness, hit-taken energy, and triggered hooks.
    # Exact route replay may still pass explicit targets; these policies are the
    # deterministic fallback used by generated enemy actions and auto-probes.
    if "分摊" in tag or "分摊" in desc or "平均分摊" in desc:
        return "all_allies_split"
    if "横扫" in tag or "连续目标" in desc:
        if "右侧" in desc or "右侧" in name:
            return "three_consecutive_allies_from_right"
        return "three_consecutive_allies_from_left"
    if "群攻" in tag or "全体" in desc:
        return "all_allies"
    if "扩散" in tag or "相邻" in desc:
        return "selected_ally_and_adjacent"
    if "召唤" in tag or "强化" in tag or "天赋" in tag:
        return "self"
    return "first_ally"


def _damage_packet_from_skill(skill: dict[str, Any]) -> dict[str, Any] | None:
    element = _norm_element(skill.get("damage_type"))
    mult = _skill_multiplier(skill)
    if not element or mult is None:
        return None
    target_policy = _target_policy_from_skill(skill)
    packet = {
        "id": str(skill.get("skill_id") or skill.get("trigger_key") or "enemy_damage"),
        "element": element,
        "scaling_stat": "atk",
        "multiplier": mult,
        "can_crit": False,
        "source_skill_id": skill.get("skill_id"),
        "target_pattern": target_policy,
    }
    if target_policy == "all_allies_split":
        packet["split_damage_across_targets"] = True
        packet["split_damage_semantics"] = "even_distribution"
    tough_display = skill.get("toughness_damage_display_basic_atk_10_scale")
    if tough_display is not None:
        packet["toughness_reduction_display_basic_atk_10_scale"] = tough_display
        # Existing model-pack fields store toughness as "basic-attack=10" display
        # scale.  Preserve a runtime value for smoke/harness use while retaining
        # the original display-scale evidence.
        try:
            packet["toughness_reduction"] = float(tough_display) * 3.0
        except Exception:
            pass
    return packet


def _status_daybreak_force_field(mechanics: dict[str, Any]) -> dict[str, Any]:
    cfg = mechanics.get("daybreak_force_field") or {}
    params = cfg.get("source_param_list") or []
    threshold = 7
    try:
        threshold = int(params[0])
    except Exception:
        pass
    return {
        "id": "daybreak_force_field",
        "tags": ["enemy_core_mechanic", "force_field", "daybreak_force_field"],
        "modifiers": {
            "control_immunity": True,
            "toughness_lock": True,
            "immediate_action_on_hit_by_element": {"element": "fire", "action": "Skill04", "target_policy": "first_ally"},
            "count_attacks_taken": {"threshold": threshold, "action": "Skill05", "target_policy": "self"},
        },
    }


def _status_armor_polis(mechanics: dict[str, Any]) -> dict[str, Any]:
    cfg = mechanics.get("armor_polis_protector") or {}
    layers = int(cfg.get("layers", 6) or 6)
    return {
        "id": "armor_polis_protector",
        "tags": ["enemy_core_mechanic", "armor_layers", "polis_protector"],
        "stacks": layers,
        "max_stacks": layers,
        "modifiers": {
            "armor_layers": {
                "layers": layers,
                "damage_reduction_per_layer": float(cfg.get("damage_reduction_per_layer", 0.2) or 0.2),
                "on_hit_lose_layers": int(cfg.get("on_hit_lose_layers", 1) or 1),
                "on_break_self_imaginary_damage_max_hp_ratio": float(cfg.get("on_break_self_imaginary_damage_max_hp_ratio", 0.0) or 0.0),
                "on_break_action_delay_ratio": float(cfg.get("on_break_action_delay_ratio", 0.0) or 0.0),
                "on_break_energy_restore_max_energy_ratio_to_breaker": float(cfg.get("on_break_energy_restore_max_energy_ratio_to_breaker", 0.0) or 0.0),
                "post_break_extra_imaginary_damage_max_hp_ratio_when_hit": float(cfg.get("post_break_extra_imaginary_damage_max_hp_ratio_when_hit", 0.0) or 0.0),
                "restore_full_layers_at_own_turn_end": bool(cfg.get("restore_full_layers_at_own_turn_end", False)),
            }
        },
    }




def _status_titanic_corpus(mechanics: dict[str, Any]) -> dict[str, Any]:
    cfg = mechanics.get("titanic_corpus") or {}
    layers = int(cfg.get("layers", 12) or 12)
    return {
        "id": "titanic_corpus",
        "tags": ["enemy_core_mechanic", "titanic_corpus", "armor_layers"],
        "stacks": layers,
        "max_stacks": layers,
        "modifiers": {
            "titanic_corpus": {
                "layers": layers,
                "damage_reduction": float(cfg.get("damage_taken_reduction", 0.3) or 0.3),
                "on_layers_zero_self_damage_max_hp_ratio": float(cfg.get("on_layers_zero_self_damage_max_hp_ratio", 0.1) or 0.1),
                "on_layers_zero_action_delay_ratio": float(cfg.get("on_break_action_delay_ratio", cfg.get("action_delay_ratio", 0.1)) or 0.1),
                "all_allies_energy_restore_max_energy_ratio": float(cfg.get("all_allies_energy_restore_max_energy_ratio", 0.15) or 0.15),
                "next_attack_damage_increase": float(cfg.get("next_attack_damage_increase", 0.2) or 0.2),
                "base_chance_imprison_targets": float(cfg.get("base_chance_imprison_targets", 0.8) or 0.8),
            },
            "damage_reduction": float(cfg.get("damage_taken_reduction", 0.3) or 0.3),
            "next_attack_dmg_bonus_add": float(cfg.get("next_attack_damage_increase", 0.2) or 0.2),
        },
    }


def _status_savage_god_glory(mechanics: dict[str, Any], stacks: int = 1) -> dict[str, Any]:
    cfg = mechanics.get("glory") or {}
    return {
        "id": "savage_god_glory",
        "tags": ["enemy_core_mechanic", "glory", "buff"],
        "stacks": int(stacks),
        "max_stacks": int(cfg.get("max_stacks", 2) or 2),
        "modifiers": {
            "dmg_bonus_add": float(cfg.get("damage_dealt_increase_per_stack", 0.3) or 0.3),
            "err_bonus_add": float(cfg.get("energy_regeneration_rate_increase_per_stack", 0.1) or 0.1),
            "glory_removes_titanic_corpus_layers_on_attack": bool(cfg.get("attacks_remove_titanic_corpus_layers_equal_to_glory_stacks", True)),
        },
    }


def _legacy_skill_to_model_skill(skill: dict[str, Any]) -> dict[str, Any]:
    out = dict(skill or {})
    if "params" not in out and "param_list" in out:
        out["params"] = out.get("param_list") or []
    if "toughness_damage_display_basic_atk_10_scale" not in out:
        out["toughness_damage_display_basic_atk_10_scale"] = out.get("sp_hit_display_basic_atk_10_scale")
    return out


def _unit_from_legacy_enemy_template(raw: dict[str, Any], fallback_id: str | None = None) -> dict[str, Any]:
    ident = raw.get("identity") or {}
    stats = raw.get("stage_scaled_stats") or {}
    monster_id = ident.get("monster_id") or fallback_id or ident.get("monster_template_id")
    unit_id = str(fallback_id or ident.get("role_in_stage") or ident.get("name_en") or monster_id or "enemy_summon").lower().replace(" ", "_").replace(",", "").replace("/", "_")
    unit = {
        "id": unit_id,
        "monster_id": monster_id,
        "monster_template_id": ident.get("monster_template_id", monster_id),
        "name": ident.get("name_en") or str(monster_id),
        "cn_name": ident.get("name_chs") or str(monster_id),
        "side": "enemy",
        "level": stats.get("level", 95),
        "hp": stats.get("hp_raw", stats.get("hp_display_rounded", 1000)),
        "max_hp": stats.get("hp_raw", stats.get("hp_display_rounded", 1000)),
        "speed": stats.get("speed_raw", stats.get("speed_display", 100)),
        "toughness": stats.get("toughness_internal"),
        "max_toughness": stats.get("toughness_internal"),
        "stats": {"atk": stats.get("attack_raw", 1000), "def": stats.get("defence_raw", 0)},
        "weaknesses": raw.get("weaknesses") or [],
        "res": raw.get("damage_type_resistance") or {},
        "tags": ["enemy_summon", "compiled_from_legacy_enemy_template"],
        "flags": {
            "monster_id": monster_id,
            "monster_template_id": ident.get("monster_template_id", monster_id),
            "legacy_role_in_stage": ident.get("role_in_stage"),
        },
        "actions": {},
        "statuses": [],
        "core_mechanics": raw.get("core_mechanics") or {},
        "source_trace": raw.get("raw_source_trace") or {},
    }
    mechanics = unit["core_mechanics"]
    if "does_not_act" in mechanics:
        unit["flags"]["does_not_act"] = True
        unit["tags"].append("does_not_act")
    if "on_fatal_attack_consumes_lance_hp" in mechanics:
        cfg = mechanics.get("on_fatal_attack_consumes_lance_hp") or {}
        unit["flags"]["owner_hp_consumption_ratio_on_fatal"] = float(cfg.get("lance_hp_consumption_ratio_from_raw_params", 0.135) or 0.135)
    if "corresponding_conquered_attacker_bonus" in mechanics:
        unit["statuses"].append({"id": "corresponding_conquered_attacker_bonus", "tags": ["enemy_core_mechanic", "corresponding_summon"], "modifiers": {"damage_taken_from_corresponding_conquered_attacker_add": 1.2}})
    if "armor_polis_protector" in mechanics:
        unit["statuses"].append(_status_armor_polis({"armor_polis_protector": mechanics.get("armor_polis_protector") or {}}))
    if "titanic_corpus" in mechanics:
        unit["flags"]["has_titanic_corpus_mechanic"] = True
    if "glory" in mechanics:
        unit["flags"]["supports_glory_after_action_clear"] = True
    for skill in raw.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        ms = _legacy_skill_to_model_skill(skill)
        action_id = str(ms.get("trigger_key") or ms.get("skill_id") or f"Skill{len(unit['actions'])+1:02d}")
        packet = _damage_packet_from_skill(ms)
        unit["actions"][action_id] = {
            "id": action_id,
            "action_type": "enemy_skill",
            "tags": ["enemy_action", "compiled_from_legacy_summon_template"],
            "target_policy": _target_policy_from_skill(ms),
            "phase_list": deepcopy(ms.get("phase_list") or []),
            "damage_packets": [packet] if packet else [],
            "effects": _effects_for_skill(ms, mechanics, None),
            "metadata": {"source_skill_id": ms.get("skill_id"), "source_skill_name_cn": ms.get("name_chs"), "summary_cn": ms.get("description_chs"), "params": ms.get("params")},
        }
    return unit


def _load_legacy_summon_registry(model_pack_dir: str | Path) -> dict[int, dict[str, Any]]:
    legacy_dir = Path(model_pack_dir) / "legacy_sources"
    registry: dict[int, dict[str, Any]] = {}
    if yaml is None or not legacy_dir.exists():
        return registry
    patterns = [
        "enemy_template_conquer_or_be_conquered_v2_4.yaml",
        "enemy_template_savage_god_mad_king_v2_4.yaml",
        "enemy_template_furiae_warrior_v2_4.yaml",
    ]
    for name in patterns:
        path = legacy_dir / name
        if not path.exists():
            continue
        raw = _load_yaml(path)
        ident = raw.get("identity") or {}
        mid = ident.get("monster_id") or ident.get("monster_template_id")
        try:
            unit = _unit_from_legacy_enemy_template(raw)
            if str(mid) == "4014012":
                unit.setdefault("flags", {})["shared_hp_group_id"] = "lance_savage_god_shared_hp"
                unit.setdefault("flags", {})["shared_hp_body_role"] = "savage_god"
            registry[int(mid)] = unit
        except Exception:
            continue
    return registry


def _summon_effect_payload(base_id: str, summon_monster_id: Any, registry: dict[int, dict[str, Any]] | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = fallback or {}
    eff = {"type": "spawn_corresponding_summons", "unit_id": base_id, "summon_monster_id": summon_monster_id}
    template = None
    try:
        template = (registry or {}).get(int(summon_monster_id))
    except Exception:
        template = None
    if template:
        eff["unit_template"] = deepcopy(template)
        eff["hp"] = template.get("hp")
        eff["max_hp"] = template.get("max_hp")
        eff["speed"] = template.get("speed")
        eff["level"] = template.get("level")
        eff["atk"] = (template.get("stats") or {}).get("atk")
        eff["def"] = (template.get("stats") or {}).get("def")
        eff["template_source"] = "legacy_enemy_template_v2_4"
    else:
        eff.update(fallback)
        eff.setdefault("hp", 1000)
        eff.setdefault("max_hp", eff.get("hp", 1000))
        eff.setdefault("speed", 100)
        eff["template_source"] = "fallback_placeholder"
    return eff



def _first_existing_tbgd_source() -> Path | None:
    for zp in TBGD_ZIP_CANDIDATES:
        if zp.exists():
            return zp
    return None

_ABILITY_LOWERING_CACHE: dict[str, dict[str, Any]] = {}
_CHARACTER_ENTRY_ABILITY_CACHE: dict[str, dict[str, str]] = {}
_TBGD_SOURCE_CACHE: dict[str, tuple[TBGDSource, set[str]]] = {}


def _ability_file_from_entry_ability(entry_ability: str) -> str | None:
    """Infer ConfigAbility/Monster file from a CharacterConfig EntryAbility.

    Examples:
      Monster_W4_Claymore_00_Skill01_Phase01 -> Monster_W4_Claymore_00_Ability.json
      Monster_W5_Ranger_00_Skill02_Phase01   -> Monster_W5_Ranger_00_Ability.json
      Monster_AML_Boss_00_Part1_IF_Skill01_Phase02 -> Monster_AML_Boss_00_Part1_Ability_IF.json
    """
    if not entry_ability:
        return None
    m = re.search(r"_(?:Skill|PassiveSkill|Insert|Phase|Trigger|Stage|Talent)", entry_ability)
    stem = entry_ability[:m.start()] if m else entry_ability
    # Current data mostly stores IF suffix after Ability rather than before it.
    candidates = []
    if stem.endswith("_IF"):
        candidates.append(f"Config/ConfigAbility/Monster/{stem[:-3]}_Ability_IF.json")
    candidates.append(f"Config/ConfigAbility/Monster/{stem}_Ability.json")
    candidates.append(f"Config/ConfigAbility/Monster/{stem}_Ability_IF.json")
    # Return the most likely path; existence is checked by the reader.
    return candidates[0]


def _entry_abilities_from_character_config(config_path: str | None) -> dict[str, str]:
    if not config_path:
        return {}
    if config_path in _CHARACTER_ENTRY_ABILITY_CACHE:
        return deepcopy(_CHARACTER_ENTRY_ABILITY_CACHE[config_path])
    cfg = _read_tbgd_json_config(config_path)
    out: dict[str, str] = {}
    if isinstance(cfg, dict):
        for row in cfg.get("SkillList") or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("Name") or "")
            entry = str(row.get("EntryAbility") or "")
            if name and entry:
                out[name] = entry
    _CHARACTER_ENTRY_ABILITY_CACHE[config_path] = deepcopy(out)
    return out


def _cached_tbgd_source_and_monster_ability_files(src_path: Path) -> tuple[TBGDSource, set[str]]:
    key = str(src_path.resolve())
    cached = _TBGD_SOURCE_CACHE.get(key)
    if cached is not None:
        return cached
    src = TBGDSource.open(src_path)
    files = set(src.list_files("Config/ConfigAbility/Monster/"))
    cached = (src, files)
    _TBGD_SOURCE_CACHE[key] = cached
    return cached


def _read_lowered_ability_file(rel: str) -> dict[str, Any] | None:
    src_path = _first_existing_tbgd_source()
    if src_path is None or not rel:
        return None
    key = f"{src_path.resolve()}::{rel}"
    if key in _ABILITY_LOWERING_CACHE:
        return deepcopy(_ABILITY_LOWERING_CACHE[key])
    candidates = [rel]
    # IF naming is not always recoverable from EntryAbility; try both common names.
    if rel.endswith("_Ability_IF.json"):
        candidates.append(rel.replace("_Ability_IF.json", "_Ability.json"))
    elif rel.endswith("_Ability.json"):
        candidates.append(rel.replace("_Ability.json", "_Ability_IF.json"))
    try:
        src, files = _cached_tbgd_source_and_monster_ability_files(src_path)
        chosen = None
        for cand in candidates:
            if cand in files:
                chosen = cand
                break
        if chosen is None:
            _ABILITY_LOWERING_CACHE[key] = None
            return None
        lowered = lower_monster_ability_file(src, chosen)
        _ABILITY_LOWERING_CACHE[key] = deepcopy(lowered)
        return deepcopy(lowered)
    except Exception:
        _ABILITY_LOWERING_CACHE[key] = None
        return None


def _runtime_target_from_tbgd_alias(alias: Any) -> str:
    a = str(alias or "").lower()
    if not a or a in {"unknown", "caster", "self", "actor"}:
        return "actor"
    # For an enemy actor, GameCore "Enemy" means the opposing player side.
    if "allenemy" in a or "enemyselect" in a or a in {"enemy", "target"}:
        return "all_allies" if "all" in a else "target"
    if "allteammember" in a or "allteam" in a or "team" in a:
        return "all_enemies"
    if "filtered" in a:
        return "target"
    return "target"


def _numeric_or_none(value: Any) -> float | None:
    if isinstance(value, dict):
        # Dynamic / postfix expressions are kept as metadata only for now.
        return None
    try:
        return float(value)
    except Exception:
        return None


def _ability_ir_effect_to_runtime(effect: dict[str, Any], action_id: str) -> tuple[str, dict[str, Any] | None]:
    """Convert conservative Monster ability preview IR into simulator effects.

    Returns (kind, payload): kind is 'packet', 'effect', or 'evidence'.  Dynamic
    formulas that are not executable yet remain evidence to avoid fake numbers.
    """
    et = effect.get("type")
    target = _runtime_target_from_tbgd_alias(effect.get("target"))
    src_meta = {"source": "monster_config_ability_graph", "source_ability": effect.get("ability"), "source_path": effect.get("path"), "source_node_type": effect.get("source_node_type")}
    if et == "damage":
        attack = effect.get("attack") or {}
        mult = _numeric_or_none(attack.get("damage_percentage"))
        if mult is None:
            return "evidence", {**src_meta, "reason": "dynamic_damage_percentage", "ir": deepcopy(effect)}
        packet = {
            "id": f"{action_id}_ability_graph_damage",
            "element": attack.get("element") or "physical",
            "scaling_stat": "atk",
            "multiplier": mult,
            "can_crit": False,
            "target_policy": target,
            "ability_graph_source": src_meta,
        }
        tough = _numeric_or_none(attack.get("toughness_ratio"))
        if tough is not None:
            packet["toughness_reduction"] = tough * 30.0
            packet["toughness_ratio_source"] = tough
        return "packet", packet
    if et == "add_status":
        status_id = effect.get("status_id") or f"ability_status_{action_id}"
        st = {"id": str(status_id), "tags": ["enemy_ability_graph_status"], "modifiers": {}, "source": src_meta}
        life = _numeric_or_none(effect.get("lifetime"))
        if life is not None and life > 0:
            st["duration"] = {"type": "holder_turns", "value": int(life)}
        return "effect", {"type": "add_status", "target": target, "status": st, "ability_graph_source": src_meta}
    if et == "remove_status":
        return "effect", {"type": "remove_status", "target": target, "status_id": str(effect.get("status_id") or ""), "ability_graph_source": src_meta}
    if et == "dispel_status":
        return "effect", {"type": "dispel_status_categories", "target": target, "categories": ["debuff", "control"], "ability_graph_source": src_meta}
    if et == "set_dynamic_value":
        key = effect.get("key")
        if key is None:
            return "evidence", {**src_meta, "reason": "missing_dynamic_key", "ir": deepcopy(effect)}
        value = effect.get("value", 0)
        if value is None:
            value = 0
        return "effect", {"type": "set_unit_flag", "target": "actor", "key": f"dynamic:{key}", "value": value, "ability_graph_source": src_meta}
    if et == "modify_dynamic_value":
        key = effect.get("key")
        if key is None:
            return "evidence", {**src_meta, "reason": "missing_dynamic_key", "ir": deepcopy(effect)}
        out = {"type": "modify_unit_counter", "target": "actor", "key": f"dynamic:{key}", "amount": effect.get("delta", 0), "ability_graph_source": src_meta}
        if effect.get("min") is not None:
            out["min"] = effect.get("min")
        if effect.get("max") is not None:
            out["max"] = effect.get("max")
        return "effect", out
    if et == "set_dynamic_value_from_property":
        return "evidence", {**src_meta, "reason": "property_expression_not_bound_yet", "ir": deepcopy(effect)}
    if et == "summon_monster":
        nested = []
        for idx, row in enumerate(effect.get("summon_data") or []):
            mid = row.get("MonsterID") or row.get("MonsterId") or row.get("monster_id") or row.get("ID")
            entity = f"monster_{mid or idx+1}"
            nested.append({"summon_entity": entity, "unit": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100, "tags": ["enemy_summon", "ability_graph_summon"], "flags": {"summon_monster_id": mid}}})
        if not nested:
            nested.append({"summon_entity": f"{action_id}_summon", "unit": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100, "tags": ["enemy_summon", "ability_graph_summon"]}})
        return "effect", {"type": "summon", "effects": nested, "ability_graph_source": src_meta}
    if et == "set_monster_phase":
        phase_value = effect.get("phase", 1)
        if phase_value is None:
            return "evidence", {**src_meta, "reason": "unbound_phase_value", "ir": deepcopy(effect)}
        return "effect", {"type": "set_unit_flag", "target": target if target != "target" else "actor", "key": "current_phase", "value": phase_value, "ability_graph_source": src_meta}
    if et == "action_delay":
        value = effect.get("value", 0)
        return "effect", {"type": "set_action_delay" if effect.get("mode") == "set" else "delay_action", "target": target, "percent": value, "ability_graph_source": src_meta}
    if et == "force_defeat":
        return "effect", {"type": "force_defeat", "target": target, "ability_graph_source": src_meta}
    if et == "heal":
        value = _numeric_or_none(effect.get("value"))
        return "effect", {"type": "heal_unit", "target": target, "amount": value or 0.0, "ability_graph_source": src_meta}
    return "evidence", {**src_meta, "reason": "unmapped_ir_type", "ir": deepcopy(effect)}


def _dedupe_effect_key(eff: dict[str, Any]) -> tuple[Any, ...]:
    st = eff.get("status") if isinstance(eff.get("status"), dict) else {}
    return (eff.get("type"), eff.get("target"), eff.get("status_id") or st.get("id"), eff.get("key"), eff.get("action"), eff.get("summon_monster_id"))


def _ability_graph_runtime_bindings_for_unit(unit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    trace = (unit.get("raw") or {}).get("raw_source_trace") or {}
    config_paths = list(trace.get("config_paths") or [])
    char_paths = [p for p in config_paths if "Config/ConfigCharacter/Monster/" in str(p)]
    bindings: dict[str, dict[str, Any]] = {}
    for cfg_path in char_paths:
        for skill_name, entry in _entry_abilities_from_character_config(str(cfg_path)).items():
            rel = _ability_file_from_entry_ability(entry)
            lowered = _read_lowered_ability_file(rel) if rel else None
            if not lowered:
                continue
            ability_rows = lowered.get("ability_rows") or []
            # Match exact EntryAbility first; then phase-insensitive SkillName prefix.
            matched = []
            for row in ability_rows:
                an = str(row.get("ability") or "")
                if an == entry or an.startswith(entry) or (skill_name and re.search(rf"_{re.escape(skill_name)}(?:_|$)", an)):
                    matched.append(row)
            if not matched:
                continue
            packets: list[dict[str, Any]] = []
            effects: list[dict[str, Any]] = []
            evidence: list[dict[str, Any]] = []
            for row in matched:
                for ir in row.get("effects") or []:
                    kind, payload = _ability_ir_effect_to_runtime(ir, skill_name)
                    if payload is None:
                        continue
                    if kind == "packet":
                        packets.append(payload)
                    elif kind == "effect":
                        effects.append(payload)
                    else:
                        evidence.append(payload)
            if packets or effects or evidence:
                bindings.setdefault(skill_name, {"entry_abilities": [], "packets": [], "effects": [], "evidence": [], "ability_file": rel})
                bindings[skill_name]["entry_abilities"].append(entry)
                bindings[skill_name]["packets"].extend(packets)
                bindings[skill_name]["effects"].extend(effects)
                bindings[skill_name]["evidence"].extend(evidence)
    return bindings


def _apply_ability_graph_binding_to_action(action: dict[str, Any], action_id: str, binding: dict[str, Any]) -> dict[str, int]:
    packets = deepcopy(binding.get("packets") or [])
    effects = deepcopy(binding.get("effects") or [])
    evidence = deepcopy(binding.get("evidence") or [])
    bound_damage = 0
    # Avoid double damage when MonsterSkillConfig already supplies an explicit damage packet.
    if packets and not action.get("damage_packets"):
        action.setdefault("damage_packets", []).extend(packets)
        bound_damage = len(packets)
    existing_keys = {_dedupe_effect_key(e) for e in action.get("effects") or [] if isinstance(e, dict)}
    added_effects = []
    for eff in effects:
        key = _dedupe_effect_key(eff)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        added_effects.append(eff)
    action.setdefault("effects", []).extend(added_effects)
    meta = action.setdefault("metadata", {})
    meta["monster_ability_graph_binding"] = {
        "ability_file": binding.get("ability_file"),
        "entry_abilities": binding.get("entry_abilities"),
        "runtime_damage_packets_added": bound_damage,
        "runtime_effects_added": len(added_effects),
        "damage_packets_kept_as_evidence": max(0, len(packets) - bound_damage),
        "evidence_count": len(evidence),
        "binding_policy": "non_damage_runtime_always; damage_runtime_only_when_no_MonsterSkillConfig_packet",
    }
    if evidence or (packets and not bound_damage):
        meta["monster_ability_graph_evidence"] = {"packets": packets if not bound_damage else [], "evidence": evidence[:20]}
    return {"packets_added": bound_damage, "effects_added": len(added_effects), "evidence_count": len(evidence) + max(0, len(packets) - bound_damage)}

def _initial_core_statuses(unit: dict[str, Any]) -> list[dict[str, Any]]:
    mechanics = unit.get("core_mechanics") or {}
    statuses: list[dict[str, Any]] = []
    if "daybreak_force_field" in mechanics:
        # The real enemy applies this by skill; the compiled initial status is
        # useful for exact-route probes and for stages that begin after the buff.
        statuses.append(_status_daybreak_force_field(mechanics))
    if "armor_polis_protector" in mechanics:
        statuses.append(_status_armor_polis(mechanics))
    if "phase_transition" in mechanics:
        statuses.append({
            "id": "phase_transition_immediate_action",
            "tags": ["enemy_core_mechanic", "phase_transition"],
            "modifiers": {"phase_transition_immediate_action": True},
        })
    return statuses


def _effects_for_skill(skill: dict[str, Any], mechanics: dict[str, Any], summon_registry: dict[int, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    sid = skill.get("skill_id")
    effects: list[dict[str, Any]] = []

    if "daybreak_force_field" in mechanics and sid == (mechanics.get("daybreak_force_field") or {}).get("source_skill_id"):
        effects.append({"type": "add_enemy_core_status", "target": "actor", "status": _status_daybreak_force_field(mechanics)})

    if "despondent" in mechanics and sid == (mechanics.get("despondent") or {}).get("source_skill_id"):
        cfg = mechanics.get("despondent") or {}
        params = cfg.get("source_param_list") or []
        dmg_taken = float(params[0]) if len(params) > 0 else 0.3
        fire_res = float(params[1]) if len(params) > 1 else 0.4
        duration = int(params[2]) if len(params) > 2 else 2
        effects.extend([
            {"type": "remove_status", "target": "actor", "status_id": "daybreak_force_field"},
            {"type": "add_status", "target": "actor", "status": {"id": "despondent", "tags": ["enemy_core_mechanic", "debuff", "despondent"], "duration": {"type": "holder_turns", "value": duration}, "modifiers": {"damage_taken_add": dmg_taken, "resistance_delta": {"fire": -fire_res}}}},
        ])

    if "summon_furiae_warrior" in mechanics and sid == (mechanics.get("summon_furiae_warrior") or {}).get("source_skill_id"):
        cfg = mechanics.get("summon_furiae_warrior") or {}
        effects.append({**_summon_effect_payload("furiae_warrior", cfg.get("summon_monster_id"), summon_registry, {"hp": 1000, "max_hp": 1000, "speed": 100}), "count": 1, "per_ally": False})

    if "charge_then_split_attack" in mechanics and sid == (mechanics.get("charge_then_split_attack") or {}).get("charge_skill_id"):
        cfg = mechanics.get("charge_then_split_attack") or {}
        raw_follow = cfg.get("followup_skill_id", "Skill04")
        # Legacy mechanism records may store the numeric SkillID while runtime
        # action definitions are keyed by TriggerKey.  Furiae Praetor's charged
        # follow-up is Skill04 in both MonsterSkillConfig and legacy templates.
        try:
            follow = "Skill04" if int(raw_follow) == 401301004 else str(raw_follow)
        except Exception:
            follow = str(raw_follow)
        effects.extend([
            {"type": "set_unit_flag", "target": "actor", "key": "forced_next_enemy_action", "value": follow, "metadata": {"mechanic": "charge_then_split_attack"}},
            {"type": "add_status", "target": "actor", "status": {"id": "charging", "tags": ["enemy_core_mechanic", "charging"], "modifiers": {"forced_next_enemy_action": follow}}},
        ])

    if "summon_conquer_or_be_conquered" in mechanics and sid == (mechanics.get("summon_conquer_or_be_conquered") or {}).get("source_skill_id"):
        cfg = mechanics.get("summon_conquer_or_be_conquered") or {}
        ratio = float(cfg.get("max_restorable_hp_reduction_ratio", 0.5) or 0.5)
        effects.extend([
            {**_summon_effect_payload("conquer_or_be_conquered", cfg.get("summon_monster_id"), summon_registry, {"hp": 1000, "max_hp": 1000, "speed": 100}), "per_ally": True, "apply_correspondence": True},
            {"type": "add_status", "target": "all_allies", "status": {"id": "conquered", "tags": ["enemy_core_mechanic", "debuff", "conquered"], "modifiers": {}}},
            {"type": "reduce_recoverable_hp_cap", "target": "all_allies", "ratio": ratio},
        ])

    if "fear_bestowed_by_strife" in mechanics and sid == (mechanics.get("fear_bestowed_by_strife") or {}).get("source_skill_id"):
        cfg = mechanics.get("fear_bestowed_by_strife") or {}
        effects.append({"type": "add_status", "target": "all_allies", "status": {"id": "fear_bestowed_by_strife", "tags": ["enemy_core_mechanic", "debuff", "fear"], "modifiers": {"damage_taken_add": float(cfg.get("damage_taken_increase", 0.1) or 0.1)}}})

    if "absorb_remaining_conquer_or_be_conquered" in mechanics and sid == (mechanics.get("absorb_remaining_conquer_or_be_conquered") or {}).get("source_skill_id"):
        effects.extend([
            {"type": "absorb_remaining_summons", "target": "all_enemies", "summon_tag": "enemy_summon", "summon_id_contains": "conquer_or_be_conquered", "store_count_flag": "absorbed_conquer_or_be_conquered_count"},
            {"type": "add_toughness_protection", "target": "actor", "status_id": "savage_god_toughness_protection"},
            {"type": "dispel_status_categories", "target": "actor", "categories": ["control", "weakness_break"]},
        ])

    if "savage_god_hp_based_aoe" in mechanics and sid == (mechanics.get("savage_god_hp_based_aoe") or {}).get("source_skill_id"):
        params = mechanics.get("savage_god_hp_based_aoe", {}).get("params") or skill.get("params") or []
        hp_pct = float(params[0]) if params else 0.9
        effects.append({"type": "hp_based_damage", "target": "all_allies", "element": "imaginary", "target_max_hp_pct": hp_pct, "ignore_defense": True, "ignore_shield": False, "source": "savage_god_hp_based_aoe"})

    if "charge_then_split_attack" in mechanics and sid == (mechanics.get("charge_then_split_attack") or {}).get("followup_skill_id"):
        # Drowned in the Crimson Sea absorbs active Furiae Warriors before its split attack.
        effects.append({"type": "absorb_remaining_summons", "target": "all_enemies", "summon_tag": "enemy_summon", "summon_id_contains": "furiae_warrior", "store_count_flag": "absorbed_furiae_warrior_count"})
        params = skill.get("params") or []
        if len(params) > 1:
            effects.append({"type": "add_status", "target": "all_allies", "status": {"id": "furiae_praetor_vulnerability", "tags": ["enemy_core_mechanic", "debuff", "vulnerability"], "modifiers": {"damage_taken_add": float(params[1]) / 4.0}}})

    if "titanic_corpus" in mechanics and sid == (mechanics.get("titanic_corpus") or {}).get("source_skill_id"):
        effects.append({"type": "add_status", "target": "actor", "status": _status_titanic_corpus(mechanics)})
        if "glory" in mechanics:
            effects.append({"type": "add_status", "target": "all_allies", "status": _status_savage_god_glory(mechanics, stacks=1)})
            effects.append({"type": "set_unit_flag", "target": "actor", "key": "clear_glory_after_next_savage_action", "value": "armed"})

    return effects



def _ai_sequence_from_unit(unit: dict[str, Any]) -> tuple[list[str], str, dict[str, Any]]:
    """Return a deterministic baseline AI sequence from model-pack ConfigAI evidence.

    v0.48 used raw skill order, which lost duplicated AI decisions and could
    select phase-2-only actions too early.  The model pack already preserves
    ConfigAI skill references under raw.ai.skill_trigger_references, so v0.49
    prefers that source while keeping the old skill-order fallback for templates
    that do not yet carry AI evidence.
    """
    raw_ai = (unit.get("raw") or {}).get("ai") if isinstance(unit.get("raw"), dict) else None
    action_ids = {str(s.get("trigger_key") or s.get("skill_id")) for s in (unit.get("skills") or []) if isinstance(s, dict)}
    seq: list[str] = []
    if isinstance(raw_ai, dict):
        for ref in raw_ai.get("skill_trigger_references") or []:
            if not isinstance(ref, dict):
                continue
            aid = str(ref.get("skill_trigger_key") or "")
            if aid and aid in action_ids:
                seq.append(aid)
        if seq:
            return seq, "model_pack_config_ai_skill_references_v0_49", {
                "ai_path": raw_ai.get("ai_path"),
                "decision_count": raw_ai.get("decision_count"),
                "reference_count": len(raw_ai.get("skill_trigger_references") or []),
                "duplicates_preserved": len(seq) != len(set(seq)),
            }
    for skill in unit.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        aid = str(skill.get("trigger_key") or skill.get("skill_id") or "")
        tag = str(skill.get("tag_chs") or "")
        desc = str(skill.get("description_chs") or "")
        if aid and "天赋" not in tag and "不会行动" not in desc:
            seq.append(aid)
    return seq, "model_pack_skill_order_fallback_v0_49", {"duplicates_preserved": len(seq) != len(set(seq))}

def compile_enemy_template(data_or_path: dict[str, Any] | str | Path, summon_registry: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    raw = _load_yaml(data_or_path) if not isinstance(data_or_path, dict) else deepcopy(data_or_path)
    unit = raw.get("unit") if isinstance(raw.get("unit"), dict) else raw
    mechanics = unit.get("core_mechanics") or {}
    enemy_id = str(unit.get("id") or raw.get("id") or "enemy")
    compiled_unit = {
        "side": "enemy",
        "name": unit.get("cn_name") or unit.get("name") or enemy_id,
        "hp": unit.get("hp", unit.get("max_hp", 1000)),
        "max_hp": unit.get("max_hp", unit.get("hp", 1000)),
        "speed": unit.get("speed", 100),
        "level": unit.get("level", 80),
        "toughness": unit.get("toughness", 0),
        "max_toughness": unit.get("max_toughness", unit.get("toughness", 0)),
        "stats": deepcopy(unit.get("stats", {"atk": 1000, "def": 1000})),
        "res": {_norm_element(k) or str(k): v for k, v in (unit.get("res") or {}).items()},
        "weaknesses": [_norm_element(x) or str(x).lower() for x in (unit.get("weaknesses") or [])],
        "tags": ["compiled_enemy_template"],
        "flags": {
            "enemy_template_id": unit.get("template_id"),
            "monster_id": (unit.get("raw") or {}).get("identity", {}).get("monster_id"),
            "rank": (unit.get("raw") or {}).get("identity", {}).get("rank"),
            "core_mechanic_keys": sorted(str(k) for k in mechanics.keys()),
        },
        "actions": {},
        "statuses": _initial_core_statuses(unit),
    }
    if "phase_transition" in mechanics:
        compiled_unit["flags"]["phase_transition_immediate_action"] = True
        compiled_unit["hp_bars_total"] = 2
        compiled_unit["hp_bars_remaining"] = 2
        compiled_unit["hp_model"] = {"type": "phase_hp", "carry_over_damage": False, "bars": [{"hp": compiled_unit["max_hp"]}, {"hp": compiled_unit["max_hp"]}]}
    if "shared_hp_with_savage_god" in mechanics:
        compiled_unit["flags"]["shared_hp_with_savage_god"] = True
        compiled_unit["flags"]["shared_hp_group_id"] = "lance_savage_god_shared_hp"
        compiled_unit["flags"]["shared_hp_partner_monster_id"] = (mechanics.get("shared_hp_with_savage_god") or {}).get("shared_with_monster_id")
    if "summon_conquer_or_be_conquered" in mechanics:
        compiled_unit["flags"]["can_summon_corresponding_conquer_or_be_conquered"] = True

    # Deterministic baseline AI sequence.  Prefer ConfigAI-derived references
    # preserved by the model pack; fall back to skill order when AI evidence is
    # unavailable.  Duplicates are intentionally kept because some enemy AIs use
    # repeated decisions in different phase/flag branches.
    ai_sequence, ai_source, ai_audit = _ai_sequence_from_unit(unit)
    if ai_sequence:
        compiled_unit["flags"]["enemy_ai_sequence"] = ai_sequence
        compiled_unit["flags"]["enemy_ai_sequence_index"] = 0
        compiled_unit["flags"]["enemy_ai_sequence_source"] = ai_source
        compiled_unit["flags"]["enemy_ai_audit"] = ai_audit
        # Most HSR monster AIs are primarily scripted sequences.  ScoreEvaluator
        # is a branch/fallback ranker, not a global free-skill chooser.
        compiled_unit["flags"].setdefault("enemy_ai_mode", "scripted_sequence_first")
        compiled_unit["flags"].setdefault("current_phase", 1)

    ai_decisions, ai_decision_audit = _enemy_ai_decisions_from_tbgd(unit)
    if ai_decisions:
        compiled_unit["flags"]["enemy_ai_decisions"] = ai_decisions
        compiled_unit["flags"]["enemy_ai_decision_source"] = "tbgd_config_ai_filter_selector_score_baseline_v0_57"
        compiled_unit["flags"]["enemy_ai_decision_audit"] = ai_decision_audit
        compiled_unit["flags"].setdefault("AIFlag", 1)
        compiled_unit["flags"].setdefault("current_phase", 1)
        if ai_decision_audit.get("ai_variables"):
            for k, v in (ai_decision_audit.get("ai_variables") or {}).items():
                compiled_unit["flags"].setdefault(str(k), v)
        if ai_decision_audit.get("skill_cooldown_config"):
            compiled_unit["flags"]["enemy_skill_cooldown_config"] = deepcopy(ai_decision_audit.get("skill_cooldown_config"))
        if ai_decision_audit.get("initial_skill_cooldowns"):
            compiled_unit["flags"]["enemy_skill_cooldowns"] = deepcopy(ai_decision_audit.get("initial_skill_cooldowns"))

    ability_graph_bindings = _ability_graph_runtime_bindings_for_unit(unit)

    coverage = {"skill_count": 0, "compiled_action_count": 0, "damage_action_count": 0, "effect_action_count": 0, "core_mechanics": sorted(str(k) for k in mechanics.keys()), "uncompiled_mechanic_keys": [], "ai_decision_count": len(ai_decisions), "ability_graph_bound_action_count": 0, "ability_graph_effect_count": 0, "ability_graph_damage_packet_count": 0, "ability_graph_evidence_count": 0}
    for skill in unit.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        coverage["skill_count"] += 1
        action_id = str(skill.get("trigger_key") or skill.get("skill_id") or f"Skill{coverage['skill_count']:02d}")
        packet = _damage_packet_from_skill(skill)
        effects = _effects_for_skill(skill, mechanics, summon_registry)
        action = {
            "id": action_id,
            "action_type": "enemy_skill",
            "tags": ["enemy_action", "compiled_from_enemy_template"],
            "target_policy": _target_policy_from_skill(skill),
            "phase_list": deepcopy(skill.get("phase_list") or []),
            "damage_packets": [packet] if packet else [],
            "effects": effects,
            "metadata": {
                "source_skill_id": skill.get("skill_id"),
                "source_skill_name_cn": skill.get("name_chs"),
                "summary_cn": skill.get("description_chs"),
                "phase_list": skill.get("phase_list"),
                "params": skill.get("params"),
            },
        }
        binding_delta = None
        if action_id in ability_graph_bindings:
            binding_delta = _apply_ability_graph_binding_to_action(action, action_id, ability_graph_bindings[action_id])
            coverage["ability_graph_bound_action_count"] += 1
            coverage["ability_graph_effect_count"] += int(binding_delta.get("effects_added", 0))
            coverage["ability_graph_damage_packet_count"] += int(binding_delta.get("packets_added", 0))
            coverage["ability_graph_evidence_count"] += int(binding_delta.get("evidence_count", 0))
        compiled_unit["actions"][action_id] = action
        coverage["compiled_action_count"] += 1
        if action.get("damage_packets"):
            coverage["damage_action_count"] += 1
        if action.get("effects"):
            coverage["effect_action_count"] += 1

    known = {
        "daybreak_force_field", "despondent", "armor_polis_protector", "summon_furiae_warrior",
        "phase_transition", "phase_two_extra_action", "shared_hp_with_savage_god", "summon_conquer_or_be_conquered",
        "fear_bestowed_by_strife", "savage_god_hp_based_aoe", "absorb_remaining_conquer_or_be_conquered",
        "charge_then_split_attack", "titanic_corpus", "glory", "split_damage_ultimate",
    }
    coverage["uncompiled_mechanic_keys"] = [k for k in coverage["core_mechanics"] if k not in known]
    return {
        "kind": "compiled_enemy_template",
        "schema_version": "enemy_template_compiler_v0.13",
        "id": enemy_id,
        "unit": compiled_unit,
        "coverage": coverage,
        "source_trace": (unit.get("raw") or {}).get("raw_source_trace", {}),
    }


def compile_enemy_model_pack(model_pack_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    units_dir = out / "compiled_enemies"
    units_dir.mkdir(parents=True, exist_ok=True)
    enemy_dir = Path(model_pack_dir) / "models" / "enemies"
    summon_registry = _load_legacy_summon_registry(model_pack_dir)
    rows: list[dict[str, Any]] = []
    for path in sorted(enemy_dir.glob("*.yaml")):
        compiled = compile_enemy_template(path, summon_registry=summon_registry)
        out_file = units_dir / f"{compiled['id']}.compiled_enemy.yaml"
        if yaml is not None:
            out_file.write_text(yaml.safe_dump(compiled, allow_unicode=True, sort_keys=False), encoding="utf-8")
        else:
            out_file.write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
        row = {
            "id": compiled["id"],
            "file": str(out_file),
            **compiled["coverage"],
        }
        rows.append(row)
    summary = {
        "format": "hsr_compiled_enemy_template_bundle",
        "version": "v0.13",
        "source_model_pack": str(model_pack_dir),
        "compiled_count": len(rows),
        "compiled_summon_template_count": len(summon_registry),
        "compiled_summon_template_ids": sorted(str(k) for k in summon_registry.keys()),
        "rows": rows,
        "summary_cn": "将 model_pack 敌人模板编译成 runtime 可直接挂载的 unit/actions/statuses。当前覆盖通用伤害、初始核心状态、力场、战甲、阶段插队、召唤、受征服/畏怖、吸收召唤物等样例机制；v0.11 在 v0.10 的评分 baseline 上明确固定序列优先；v0.12 细化连续行动链；v0.13 将 Monster ConfigAbility 高置信 preview IR 接入编译器：非伤害效果直接进入 runtime，伤害在无 MonsterSkillConfig 伤害包时才作为 runtime packet，避免重复结算。",
    }
    out.mkdir(parents=True, exist_ok=True)
    summons_dir = out / "compiled_enemy_summons"
    summons_dir.mkdir(parents=True, exist_ok=True)
    for mid, tmpl in sorted(summon_registry.items()):
        summon_file = summons_dir / f"{mid}.compiled_enemy_summon.yaml"
        if yaml is not None:
            summon_file.write_text(yaml.safe_dump({"kind": "compiled_enemy_summon_template", "schema_version": "enemy_template_compiler_v0.13", "monster_id": mid, "unit": tmpl}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        else:
            summon_file.write_text(json.dumps({"kind": "compiled_enemy_summon_template", "schema_version": "enemy_template_compiler_v0.13", "monster_id": mid, "unit": tmpl}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "enemy_template_compiler_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 敌人模板编译器 v0.13", "", summary["summary_cn"], "", f"- 已编译召唤物模板：{len(summon_registry)} 个（{', '.join(summary['compiled_summon_template_ids']) or '无'}）", ""]
    for r in rows:
        lines.append(f"- `{r['id']}`：技能 {r['skill_count']}，动作 {r['compiled_action_count']}，伤害动作 {r['damage_action_count']}，效果动作 {r['effect_action_count']}，未编译机制：{', '.join(r['uncompiled_mechanic_keys']) or '无'}")
    (out / "enemy_template_compiler_cn.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Compile model-pack enemy templates into runtime units")
    parser.add_argument("model_pack")
    parser.add_argument("--output-dir", "-o", required=True)
    args = parser.parse_args(argv)
    result = compile_enemy_model_pack(args.model_pack, args.output_dir)
    print(json.dumps({"version": result["version"], "compiled_count": result["compiled_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
