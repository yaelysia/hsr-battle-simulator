from __future__ import annotations

"""Lower BoundStatusIR into simulator-facing status templates and triggers.

This module is intentionally conservative: it emits executable simulator effects
only for IR nodes whose target/timing/value semantics can be represented by the
current route validator.  Unsupported or uncertain nodes are preserved in audit
fields instead of being guessed.
"""

from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from .tbgd_loader import TBGDSource, unwrap_value
import json



# Conservative rank predicate hash hints observed from current target-team ConfigAbility.
# These are compiler-layer hints only; runtime still evaluates against owner.rank
# supplied by the status template integration owner map.  Unknown rank hashes stay
# unsupported instead of being guessed.
RANK_TRIGGER_KEY_HINTS = {
    "1686351920": 6,      # Sparkle Rank06 branch in Avatar_Sparkle_00_Rank06_BP
    "-1445815962": 1,     # Tribbie Rank01 insert-action branch in Avatar_Tribbie_00 ability graph
}

EVENT_TO_TIMING = {
    "ModifierAffectedPreshowConfig": "preshow_audit",
    "ModifierCreateEntityPreshowConfig": "preshow_audit",
    "OnEnterBattle": "battle_start",
    "OnListenCharacterCreate": "battle_start",
    "OnCreate": "status_create",
    "OnDestroy": "status_destroy",
    "OnStack": "status_stack",
    "OnModifierOnStack": "status_stack",
    "OnPhase1": "battle_start",
    "OnListenTurnEnd": "owner_turn_end",
    "OnActionEnd": "action_end",
    "OnAfterSkillUse": "action_end",
    "OnListenAfterSkillUse": "action_end",
    "OnBeforeSkillUse": "before_action_check",
    "OnActionPhaseBegin": "action_start",
    "OnInsertActionStart": "extra_turn_start",
    "OnAfterBeingAttacked": "after_damage",
    "OnAfterAttack": "after_damage",
    "OnTriggerDeath": "after_defeat_enemy",
    "OnTriggerDeathrattle": "after_defeat_enemy",
    "OnWaveMonster": "wave_start",
    "OnCustomEvent": "custom_event",
    "OnListenInsertAbilityFinish": "action_end",
    "OnListenBpChange": "after_skill_point_consumed",
}

EXECUTABLE_TIMINGS = {
    "battle_start", "wave_start", "preshow_audit",
    "owner_turn_end", "action_end", "before_action_check",
    "action_start", "extra_turn_start",
    "after_damage", "after_defeat_enemy", "after_skill_point_consumed",
    "status_create", "status_destroy", "status_stack",
    "custom_event",
    "ability_property_change", "status_dynamic_value_change",
    "status_dynamic_value_enter_range", "status_dynamic_value_exit_range",
}

TARGET_POLICY_MAP = {
    "self": "actor",
    "caster": "actor",
    "Caster": "actor",
    "modifier_owner": "actor",
    "ModifierOwnerEntity": "actor",
    "tbgd_alias:ParamEntity": "target",
    "target": "target",
    "selected_target": "target",
    "all_enemies": "all_enemies",
    "all_allies": "all_allies",
    "tbgd_alias:AllLightTeam": "all_allies",
    "tbgd_alias:AllPlayer": "all_allies",
    "tbgd_alias:AllEnemy": "all_enemies",
}


def _resolved_value(obj: Any, resolve: Any = None) -> float | int | None:
    if isinstance(resolve, dict) and str(resolve.get("status", "")).startswith("status_resolved"):
        return resolve.get("value")
    if isinstance(resolve, dict) and resolve.get("status") == "resolved_fixed":
        return resolve.get("value")
    if isinstance(obj, dict):
        if obj.get("IsDynamic") is False and "FixedValue" in obj:
            return obj.get("FixedValue")
        if set(obj.keys()) == {"FixedValue"}:
            return obj.get("FixedValue")
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return obj
    return None


def _target(policy: Any, default: str = "actor") -> str:
    if policy is None:
        return default
    if policy in TARGET_POLICY_MAP:
        return TARGET_POLICY_MAP[policy]
    text = str(policy)
    # TBGD target aliases can be composed strings such as
    # "AllLightTeamWithAllLightTeamUnselectable.RemoveBattleEvent.RemoveServant - Caster".
    # Keep the meaning canonical at the template boundary instead of leaking the
    # raw alias into the kernel.
    if "AllLightTeam" in text or "AllPlayer" in text:
        if "- Caster" in text or "RemoveCaster" in text:
            return "all_allies_except_actor"
        return "all_allies"
    if "AllEnemy" in text:
        return "all_enemies"
    return text


def _dedupe_effects(effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for eff in effects:
        auditless = {k: v for k, v in eff.items() if not str(k).startswith("source_")}
        sig = json.dumps(auditless, sort_keys=True, ensure_ascii=False, default=str)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(eff)
    return out




def _expr_hashes_for_hint(expr: Any) -> list[int]:
    if not isinstance(expr, dict):
        return []
    hashes = expr.get("dynamic_hashes")
    if hashes is None and isinstance(expr.get("PostfixExpr"), dict):
        hashes = expr["PostfixExpr"].get("DynamicHashes")
    hashes = unwrap_value(hashes or [])
    out: list[int] = []
    if isinstance(hashes, list):
        for h in hashes:
            try:
                out.append(int(h))
            except Exception:
                pass
    return out


def _target_from_raw_target_type(raw: Any, default: str = "actor") -> str:
    raw = unwrap_value(raw)
    if isinstance(raw, dict):
        alias = raw.get("Alias") or raw.get("TargetType") or raw.get("Value")
        if alias is not None:
            return _target(alias, default)
    return _target(raw, default)


def _collect_modifier_property_hints_from_ability(ability: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Collect audit-only StackProperty hints from raw modifier definitions.

    These hints are still compiler-side metadata.  They describe which property a
    status would stack on OnStack and which raw dynamic hashes feed that property,
    but they do not make the combat kernel interpret raw TBGD fields.
    """
    ability = unwrap_value(ability)
    out: dict[str, list[dict[str, Any]]] = {}

    def scan_modifier(modifier_id: str, modifier: Any, base_path: str) -> None:
        if not isinstance(modifier, dict):
            return
        hints: list[dict[str, Any]] = []
        callbacks = modifier.get("_CallbackList") or []
        if not isinstance(callbacks, list):
            return
        for ci, cb in enumerate(callbacks):
            if not isinstance(cb, dict) or str(cb.get("Event")) != "OnStack":
                continue
            for ti, task in enumerate(cb.get("CallbackConfig") or []):
                if not isinstance(task, dict):
                    continue
                if str(task.get("$type")) != "RPG.GameCore.StackProperty":
                    continue
                prop = task.get("Property")
                if not prop:
                    continue
                value_expr = task.get("PropertyValue")
                hints.append({
                    "property": str(prop),
                    "target": _target_from_raw_target_type(task.get("TargetType"), "actor"),
                    "value_expr_hashes": _expr_hashes_for_hint(value_expr),
                    "source_path": f"{base_path}._CallbackList[{ci}].CallbackConfig[{ti}]",
                    "source_node_type": "RPG.GameCore.StackProperty",
                })
        if hints:
            out.setdefault(str(modifier_id), []).extend(hints)

    def walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for bucket in ("Modifiers", "GlobalModifiers"):
                val = obj.get(bucket)
                if isinstance(val, dict):
                    for mid, mod in val.items():
                        scan_modifier(str(mid), mod, f"{path+'.' if path else ''}{bucket}.{mid}")
            for k, v in obj.items():
                walk(v, f"{path+'.' if path else ''}{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(ability)
    # Dedupe repeated definitions reached through nested walk.
    for mid, hints in list(out.items()):
        seen = set(); deduped = []
        for h in hints:
            sig = json.dumps(h, sort_keys=True, ensure_ascii=False, default=str)
            if sig in seen:
                continue
            seen.add(sig); deduped.append(h)
        out[mid] = deduped
    return out


def _collect_status_property_hints(source: TBGDSource | str | Path | None, owner_avatar_ids: list[int]) -> dict[str, list[dict[str, Any]]]:
    if source is None:
        return {}
    src = source if isinstance(source, TBGDSource) else TBGDSource.open(source)
    avatar_paths: dict[int, list[str]] = {}
    try:
        rows = src.load_table("AvatarConfig") if "AvatarConfig" in src.list_excel_tables() else []
    except Exception:
        rows = []
    wanted = {int(x) for x in owner_avatar_ids}
    for r in rows if isinstance(rows, list) else []:
        row = unwrap_value(r)
        try:
            aid = int(row.get("AvatarID"))
        except Exception:
            continue
        if aid not in wanted:
            continue
        rel = str(row.get("JsonPath") or "").lstrip("/")
        paths = []
        if rel:
            paths.append(rel)
            if "/Avatar/" in rel:
                paths.append(rel.replace("/Avatar/", "/Avatar/Advanced/", 1))
            # AvatarConfig.JsonPath points to ConfigCharacter, while combat
            # modifier definitions live in ConfigAbility/Avatar/*_Ability.json.
            name = Path(rel).name
            if name.endswith("_Config.json"):
                ability_name = name[:-len("_Config.json")] + "_Ability.json"
                paths.append(f"Config/ConfigAbility/Avatar/{ability_name}")
        avatar_paths[aid] = paths
    merged: dict[str, list[dict[str, Any]]] = {}
    for aid, paths in avatar_paths.items():
        for rel in paths:
            try:
                if not src.exists(rel):
                    continue
                hints = _collect_modifier_property_hints_from_ability(src.read_json(rel))
            except Exception:
                continue
            for sid, items in hints.items():
                for item in items:
                    rec = dict(item)
                    rec["owner_avatar_id"] = aid
                    merged.setdefault(sid, []).append(rec)
    for sid, hints in list(merged.items()):
        seen = set(); deduped = []
        for h in hints:
            sig = json.dumps(h, sort_keys=True, ensure_ascii=False, default=str)
            if sig in seen:
                continue
            seen.add(sig); deduped.append(h)
        merged[sid] = deduped
    return merged


def _attach_property_hints_to_effects(effects: list[dict[str, Any]], property_hints: dict[str, list[dict[str, Any]]]) -> None:
    for eff in effects or []:
        if not isinstance(eff, dict):
            continue
        if eff.get("type") == "add_status" and isinstance(eff.get("status"), dict):
            sid = str(eff["status"].get("id") or "")
            if sid in property_hints and "property_hints" not in eff["status"]:
                eff["status"]["property_hints"] = deepcopy(property_hints[sid])
        for key in ("effects", "effects_if_true", "effects_if_false"):
            nested = eff.get(key)
            if isinstance(nested, list):
                _attach_property_hints_to_effects(nested, property_hints)

def _effect_list_signature(effects: list[dict[str, Any]]) -> str:
    try:
        return json.dumps([{k: v for k, v in e.items() if not str(k).startswith("source_")} for e in effects], sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return str(effects)


def _compare_condition(left: str, op: Any, right: Any) -> dict[str, Any]:
    return {"left": left, "op": op or "==", "right": right}


def _convert_condition(cond: Any) -> tuple[Any, list[str]]:
    if cond in (None, {}, True):
        return {}, []
    if isinstance(cond, dict):
        typ = cond.get("type")
        if "all" in cond or typ == "all":
            raw_items = cond.get("all") if "all" in cond else cond.get("conditions")
            items = []
            reasons = []
            for c in raw_items or []:
                cc, rr = _convert_condition(c)
                items.append(cc); reasons.extend(rr)
            return {"all": items}, reasons
        if "any" in cond or typ == "any":
            raw_items = cond.get("any") if "any" in cond else cond.get("conditions")
            items = []
            reasons = []
            for c in raw_items or []:
                cc, rr = _convert_condition(c)
                items.append(cc); reasons.extend(rr)
            return {"any": items}, reasons
        if "not" in cond or typ == "not":
            cc, rr = _convert_condition(cond.get("not", cond.get("condition")))
            return {"not": cc}, rr
        if typ == "action_type":
            action_type = cond.get("action_type") or cond.get("skill_type") or cond.get("value")
            if action_type:
                tag = {
                    "Normal": "basic_use",
                    "BPSkill": "skill_use",
                    "Skill": "skill_use",
                    "Ultra": "ultimate_use",
                    "Ultimate": "ultimate_use",
                }.get(str(action_type), str(action_type))
                return {"action_has_tag": tag}, []
        if typ == "has_status":
            status_id = cond.get("status_id") or cond.get("modifier_name")
            target = _target(cond.get("target_policy") or cond.get("target"), "actor")
            if status_id:
                return f"{target} has {status_id}", []
        if typ == "target_alive_state":
            target = _target(cond.get("target_policy"), "target")
            if target == "actor":
                return "actor.alive == true", []
            return "target.is_alive == true", []
        if typ == "any_enemy_alive":
            return {"any_enemy_alive": True}, []
        if typ == "compare_wave_count":
            val = _resolved_value(cond.get("value_expr"), cond.get("value_expr_resolve"))
            if val is not None:
                # TBGD wave count is 1-based, while the simulator's internal
                # wave_index is 0-based.  Expose a 1-based canonical condition
                # name so generated templates do not silently fail on wave 1.
                return _compare_condition("battle.wave_number", cond.get("op") or "==", val), []
        if typ == "compare_dynamic_value":
            key = cond.get("key") or cond.get("dynamic_key")
            op = cond.get("op") or cond.get("compare_type") or "=="
            val = _resolved_value(cond.get("value_expr"), cond.get("value_expr_resolve"))
            if key and val is not None:
                return _compare_condition(f"flag:{key}", op, val), []
        if typ == "random_chance":
            chance = _resolved_value(cond.get("chance_expr"), cond.get("chance_expr_resolve"))
            if chance is not None:
                return {"chance_gate": {"base_chance": chance, "mode": "success", "source": "ByRandomChance"}}, []
            return {"raw_condition_ir": deepcopy(cond)}, ["condition_random_chance_unresolved"]
        if typ == "skill_point_activated":
            return "skill_point_activated", []
        if typ == "is_insert_action":
            return {"action_has_tag": "insert_action"}, []
        if typ == "is_current_skill_active":
            return "current_skill_active", []
        if typ == "contains_behavior_flag":
            flag = cond.get("flag") or cond.get("behavior_flag") or cond.get("value")
            if flag:
                return {"action_has_tag": str(flag)}, []
        if typ == "target_team":
            team = cond.get("team") or cond.get("target_team") or cond.get("value")
            if team:
                return _compare_condition("target.team", "==", team), []
        if typ == "target_lists_intersect":
            raw = deepcopy(cond)
            return {"target_lists_intersect": {
                "first": _target(raw.get("first"), "actor"),
                "second": _target(raw.get("second"), "target"),
                "first_alive_only": raw.get("first_alive_only"),
                "second_alive_only": raw.get("second_alive_only"),
            }}, []
        if typ == "target_entity_type":
            raw = deepcopy(cond)
            ent = raw.get("entity_type_mask") or raw.get("entity_type") or raw.get("value")
            return {"target_entity_type": {"target": _target(raw.get("target_policy"), "target"), "entity_type_mask": ent}}, []
        if typ == "eidolon_or_rank_active":
            key = str(cond.get("trigger_key") or cond.get("rank_trigger_key") or "")
            required = RANK_TRIGGER_KEY_HINTS.get(key)
            if required is not None:
                return _compare_condition("owner.rank", ">=", required), []
            return {"raw_condition_ir": deepcopy(cond)}, ["unsupported_condition:eidolon_or_rank_active"]
        if typ == "modifier_callback_name":
            status_id = cond.get("status_id") or cond.get("modifier_name")
            if status_id:
                return _compare_condition("trigger.status_id", "==", status_id), []
        if typ == "compare_status_value":
            key = cond.get("key") or cond.get("status_value") or cond.get("value_key") or cond.get("value_type")
            status_id = cond.get("status_id") or cond.get("modifier_name")
            val = _resolved_value(cond.get("value_expr"), cond.get("value_expr_resolve"))
            if key and status_id and val is not None:
                target = _target(cond.get("target_policy"), "actor")
                return _compare_condition(f"status:{target}:{status_id}:{key}", cond.get("op") or "==", val), []
            if key and val is not None:
                return _compare_condition(f"status:{key}", cond.get("op") or "==", val), ["condition_compare_status_value_needs_kernel_binding"]
        if typ == "compare_param_string":
            val = cond.get("value") or cond.get("param_string") or cond.get("param")
            if val:
                return _compare_condition("context.extra_turn_type", cond.get("op") or "==", val), []
        if typ == "compare_param_value":
            val = _resolved_value(cond.get("value_expr"), cond.get("value_expr_resolve"))
            if val is not None:
                param = cond.get('param') or cond.get('param_name') or cond.get('variate_type')
                # OnListenBpChange supplies the consumed SP delta through runtime
                # context.  When TBGD leaves ParamName blank, compare against the
                # canonical skill_point_delta context rather than emitting an
                # unbound param:unknown predicate.
                if not param or str(param).lower() in {"unknown", "none", ""}:
                    return _compare_condition("context.skill_point_delta", cond.get("op") or "==", val), []
                return _compare_condition(f"param:{param}", cond.get("op") or "==", val), ["condition_compare_param_value_needs_kernel_binding"]
        return {"raw_condition_ir": deepcopy(cond)}, [f"unsupported_condition:{typ or 'unknown'}"]
    return cond, []


def _convert_damage_packet(eff: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    mult = None
    scaling = eff.get("scaling") if isinstance(eff.get("scaling"), dict) else {}
    if isinstance(scaling, dict):
        mult = _resolved_value(scaling.get("multiplier_expr"), scaling.get("multiplier_expr_resolve"))
    if mult is None:
        return None, ["damage_packet_multiplier_unresolved"]
    packet = {
        "id": eff.get("id") or "status_damage_packet",
        "element": str(eff.get("damage_type") or "none").lower(),
        "damage_type": "follow_up_damage" if str(eff.get("attack_type")) == "Pursued" else "status_damage",
        "scaling_stat": scaling.get("stat", "atk"),
        "multiplier": mult,
        "can_crit": True,
        "forced_crit": False,
        "target_policy": _target(eff.get("target_policy"), "target"),
    }
    tough = eff.get("toughness") if isinstance(eff.get("toughness"), dict) else {}
    tv = _resolved_value(tough.get("toughness_reduction_expr"), tough.get("toughness_reduction_expr_resolve"))
    if tv is not None:
        packet["toughness_reduction"] = tv
    return packet, []


def _convert_effect(eff: dict[str, Any], current_status_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    typ = eff.get("type")
    reasons: list[str] = []
    if typ == "set_flag":
        val = _resolved_value(eff.get("value_expr"), eff.get("value_expr_resolve"))
        if val is None:
            val = eff.get("value", True)
        return [{"type": "set_flag", "key": eff.get("key"), "value": val}], []
    if typ == "remove_status":
        return [{"type": "remove_status", "target": _target(eff.get("target_policy"), "actor"), "status_id": eff.get("status_id") or current_status_id}], []
    if typ == "add_status":
        status_id = eff.get("status_id") or eff.get("modifier_name")
        if not status_id:
            return [], ["add_status_missing_status_id"]
        status = {"id": status_id}
        duration = _resolved_value(eff.get("duration_expr"), eff.get("duration_expr_resolve"))
        if duration is not None:
            status["duration"] = {"type": "owner_turns", "value": int(duration) if float(duration).is_integer() else duration, "extra_turn_consumes_duration": False}
        elif eff.get("duration_expr") is not None:
            reasons.append("add_status_duration_unresolved")
        dyn_values = eff.get("dynamic_values") or {}
        resolved_dyn = {}
        symbolic_dyn = {}
        unresolved_dyn = {}
        if isinstance(dyn_values, dict):
            for k, v in dyn_values.items():
                # Sibling *_resolve entries are binder annotations for the real
                # dynamic value keys; they are not dynamic values themselves.
                if str(k).endswith("_resolve"):
                    continue
                val = _resolved_value(v, eff.get(f"dynamic_values.{k}_resolve") or (v.get("_resolve") if isinstance(v, dict) else None))
                # The binder stores sibling fields inside dynamic_values as key_resolve.
                if val is None and isinstance(dyn_values.get(f"{k}_resolve"), dict):
                    val = _resolved_value(v, dyn_values.get(f"{k}_resolve"))
                if val is not None:
                    resolved_dyn[k] = val
                else:
                    trace = dyn_values.get(f"{k}_resolve") if isinstance(dyn_values.get(f"{k}_resolve"), dict) else None
                    trace_status = str((trace or {}).get("status") or "")
                    # Runtime modifier DynamicValues and fully-declared but not-yet-lowered
                    # dynamic formulas are safe to preserve as symbolic status values.
                    # Do not block the surrounding trigger just because the numeric
                    # formula is not executable yet; the kernel will keep them under
                    # modifiers.symbolic_dynamic_values instead of treating them as
                    # numeric combat modifiers.  Expressions with genuinely missing
                    # hashes stay unresolved and block execution.
                    missing = list((trace or {}).get("missing_hashes") or [])
                    if trace_status in {"symbolic_modifier_dynamic_value", "unresolved_mixed_symbolic_dynamic_expr", "unresolved_status_dynamic_expr"} and not missing:
                        symbolic_dyn[k] = {"expr": v, "resolve": trace}
                    else:
                        unresolved_dyn[k] = v
        if resolved_dyn:
            status["dynamic_values"] = resolved_dyn
        if symbolic_dyn:
            status["symbolic_dynamic_values"] = symbolic_dyn
        if unresolved_dyn:
            reasons.append("add_status_dynamic_values_unresolved")
            status["unresolved_dynamic_values"] = unresolved_dyn
        out = {"type": "add_status", "target": _target(eff.get("target_policy"), "actor"), "status": status}
        chance = _resolved_value(eff.get("chance_expr"), eff.get("chance_expr_resolve"))
        if chance is not None:
            out["effect_hit"] = {"base_chance": chance, "mode": "success", "source": "AddModifier.Chance"}
        elif eff.get("chance_expr") is not None:
            reasons.append("add_status_chance_unresolved")
        return [out], reasons
    if typ == "modify_skill_points":
        amount = _resolved_value(eff.get("delta_expr"), eff.get("delta_expr_resolve"))
        if amount is None:
            # Attack target count is produced by a preceding
            # SetDynamicValueByAttackTargetCount in the same generated trigger.
            # Lower it into a runtime context/flag based SP delta instead of
            # blocking the whole trigger.
            if eff.get("modify_function") == "Add" and eff.get("source_node_type") == "RPG.GameCore.ModifyTeamBoostPoint":
                return [{"type": "modify_skill_points_from_flag", "flag": "MDF_AttackCount", "scale": 1}], []
            trace = eff.get("delta_expr_resolve") if isinstance(eff.get("delta_expr_resolve"), dict) else {}
            if eff.get("source_node_type") == "RPG.GameCore.ModifySPNew" and trace.get("status") == "unresolved_mixed_symbolic_dynamic_expr" and not trace.get("missing_hashes"):
                nums = list((trace.get("numeric_bindings") or {}).values())
                syms = list(trace.get("symbolic_hashes") or [])
                if len(nums) == 1 and len(syms) == 1:
                    return [{"type": "modify_skill_points_from_flag", "flag": "MDF_AttackCount", "scale": nums[0].get("value", 1)}], []
            return [], ["modify_skill_points_delta_unresolved"]
        return [{"type": "modify_skill_points", "amount": amount}], []
    if typ == "modify_skill_point_cap":
        amount = _resolved_value(eff.get("delta_expr"), eff.get("delta_expr_resolve"))
        if amount is None:
            return [], ["modify_skill_point_cap_delta_unresolved"]
        return [{"type": "modify_skill_point_cap", "amount": amount}], []
    if typ == "modify_action_value":
        amount = _resolved_value(eff.get("delay_expr"), eff.get("delay_expr_resolve"))
        if amount is None:
            return [], ["modify_action_value_delay_unresolved"]
        target = _target(eff.get("target_policy"), "actor")
        mode = str(eff.get("mode") or ("set" if eff.get("source_node_type") == "RPG.GameCore.SetActionDelay" else "add"))
        # AddNormalizedValue is a normalized action-delay ratio for small values
        # in hand-checked cases, but several real TBGD rank/trace parameters are
        # stored as large table values such as 165. Executing those as 16500% AV
        # would corrupt the route. Keep large additive values symbolic until the
        # compiler has a verified unit conversion for that source field.
        try:
            amount_f = float(amount)
        except Exception:
            amount_f = None
        if mode != "set" and amount_f is not None and abs(amount_f) > 1.0:
            return [], ["modify_action_value_additive_scale_ambiguous"]
        if mode == "set":
            return [{"type": "set_action_delay", "target": target, "percent": amount}], []
        return [{"type": "delay_action", "target": target, "percent": amount}], []
    if typ == "conditional_enqueue_action":
        # This node is a precheck/gate around a nested TurnInsertAction.  When the
        # concrete launch_action is already present in the same branch, this node
        # should not make the entire trigger non-executable.  If it ever carries
        # an explicit action_id, lower it like a normal queued launch.
        action_id = eff.get("action_id") or eff.get("action")
        if not action_id:
            return [], []
        return [{"type": "launch_action", "actor": _target(eff.get("actor_policy"), "actor"), "action": action_id, "target_policy": _target(eff.get("target_policy"), "target"), "queue": "immediate_queue"}], []
    if typ == "set_flag_from_context_value":
        key = eff.get("key")
        if not key:
            return [], ["set_flag_from_context_value_missing_key"]
        return [{"type": "set_flag_from_context_value", "key": key, "context_value_type": eff.get("context_value_type"), "variate_type": eff.get("variate_type"), "target": _target(eff.get("target_policy"), "actor")}], []
    if typ == "set_flag_from_property":
        key = eff.get("key")
        prop = eff.get("property")
        if not key or not prop:
            return [], ["set_flag_from_property_missing_key_or_property"]
        return [{"type": "set_flag_from_property", "key": key, "property": prop, "target": _target(eff.get("target_policy"), "actor")}], []
    if typ == "copy_flag":
        key = eff.get("key")
        source_key = eff.get("source_key")
        if not key or not source_key:
            return [], ["copy_flag_missing_key_or_source_key"]
        out = {
            "type": "copy_flag",
            "key": key,
            "source_key": source_key,
            "target": _target(eff.get("target_policy"), "actor"),
            "source_target": _target(eff.get("source_target_policy"), "actor"),
        }
        if eff.get("source_status_id"):
            out["source_status_id"] = eff.get("source_status_id")
        if eff.get("target_context_scope"):
            out["target_context_scope"] = eff.get("target_context_scope")
        return [out], []
    if typ == "set_flag_from_status_value":
        key = eff.get("key")
        status_id = eff.get("status_id")
        if not key or not status_id:
            return [], ["set_flag_from_status_value_missing_key_or_status_id"]
        return [{"type": "set_flag_from_status_value", "key": key, "status_id": status_id, "value_type": eff.get("value_type"), "target": _target(eff.get("target_policy"), "actor")}], []
    if typ == "include_task_list_template":
        template_id = str(eff.get("template_id") or "")
        dyn = eff.get("dynamic_values") or {}
        # TBGD's common ReduceActionDelay template takes Arg0_NormalizedValue.
        # Treat it as SetActionDelay on the ParamTarget; keep unknown templates
        # symbolic instead of guessing.
        if template_id == "ReduceActionDelay":
            raw_amount = dyn.get("Arg0_NormalizedValue") if isinstance(dyn, dict) else None
            amount = _resolved_value(raw_amount, (raw_amount.get("_resolve") if isinstance(raw_amount, dict) else None))
            if amount is None and isinstance(dyn, dict) and isinstance(dyn.get("Arg0_NormalizedValue_resolve"), dict):
                amount = _resolved_value(raw_amount, dyn.get("Arg0_NormalizedValue_resolve"))
            if amount is None:
                return [], ["include_task_list_template_reduce_action_delay_unresolved"]
            return [{"type": "set_action_delay", "target": _target(eff.get("target_policy"), "actor"), "percent": amount}], []
        return [], [f"unsupported_include_task_list_template:{template_id or 'unknown'}"]
    if typ == "trigger_effect":
        # RPG.GameCore.TriggerEffect is usually a visual/performance side effect.
        # When it names a logical effect id, expose it as a custom runtime event;
        # when it only has EffectPath, record it as visual-only and do not let it
        # make an otherwise executable combat trigger non-executable.
        effect_id = eff.get("effect_id") or eff.get("id") or eff.get("effect_name")
        effect_path = eff.get("effect_path") or eff.get("path")
        if effect_id:
            return [{"type": "trigger_custom_event", "custom_event_id": str(effect_id), "target": _target(eff.get("target_policy"), "actor")}], []
        if effect_path:
            return [{"type": "record_visual_effect", "effect_path": str(effect_path), "target": _target(eff.get("target_policy"), "actor")}], []
        return [], ["trigger_effect_missing_effect_id_or_path"]
    if typ == "force_defeat":
        return [{"type": "force_defeat", "target": _target(eff.get("target_policy"), "target")}], []
    if typ == "set_energy_bar_state":
        effects = []
        target = _target(eff.get("target_policy"), "actor")
        if eff.get("current_state") is not None:
            effects.append({"type": "set_unit_flag", "target": target, "key": "energy_bar_state", "value": eff.get("current_state")})
        count = _resolved_value(eff.get("current_count_expr"), eff.get("current_count_expr_resolve"))
        if count is not None:
            effects.append({"type": "set_unit_flag", "target": target, "key": "energy_bar_count", "value": count})
        if not effects:
            return [], ["set_energy_bar_state_no_executable_fields"]
        return effects, []
    if typ == "modify_skill_property":
        # Runtime can safely record skill-property modifications as owner-local
        # flags even when the exact downstream property consumer is not lowered
        # yet.  If all fields are absent, keep a typed audit marker instead of
        # blocking neighbouring TurnInsertAction effects.
        return [{"type": "record_skill_property_modifier", "skill_name": eff.get("skill_name"), "property": eff.get("property"), "value": _resolved_value(eff.get("value_expr"), eff.get("value_expr_resolve")), "target": _target(eff.get("target_policy"), "actor")}], []
    if typ == "damage_packet":
        packet, rr = _convert_damage_packet(eff)
        if packet is None:
            return [], rr
        return [{"type": "deal_damage", "damage_packet": packet, "target": packet.pop("target_policy", "target")}], []
    if typ == "enqueue_action":
        action_id = eff.get("action_id")
        if not action_id:
            return [], ["enqueue_action_missing_action_id"]
        return [{"type": "launch_action", "actor": _target(eff.get("actor_policy"), "actor"), "action": action_id, "target_policy": _target(eff.get("target_policy"), "target"), "queue": "immediate_queue"}], []
    if typ == "enqueue_turn_action":
        action_id = eff.get("action_id")
        actor = _target(eff.get("actor_policy"), "actor")
        target_policy = _target(eff.get("target_policy"), "target") if eff.get("target_policy") is not None else None
        extra_turn_type = eff.get("extra_turn_type")
        if action_id:
            return [{"type": "launch_action", "actor": actor, "action": action_id, "target_policy": target_policy, "queue": "immediate_queue", "turn_kind": "extra_turn", "extra_turn_type": extra_turn_type}], []
        if extra_turn_type:
            return [{"type": "enqueue_extra_turn", "actor": actor, "queue": "immediate_queue", "turn_kind": "extra_turn", "extra_turn_type": extra_turn_type}], []
        skill_type = eff.get("action_type") or eff.get("skill_type")
        if skill_type:
            return [{"type": "enqueue_extra_turn_by_skill_type", "actor": actor, "skill_type": skill_type, "target_policy": target_policy, "queue": "immediate_queue", "turn_kind": "extra_turn"}], []
        return [], ["enqueue_turn_action_missing_action_id"]

    if typ == "random_select_dynamic_value":
        values = []
        for raw in eff.get("value_exprs") or []:
            values.append(_resolved_value(raw, raw.get("_resolve") if isinstance(raw, dict) else None))
        if not eff.get("key") or not values:
            return [], ["random_select_dynamic_value_missing_key_or_values"]
        return [{"type": "random_select_flag", "key": eff.get("key"), "values": values, "event_id": eff.get("event_id"), "context_scope": eff.get("context_scope")}], []
    if typ == "set_dynamic_entity_param":
        if not eff.get("key"):
            return [], ["set_dynamic_entity_param_missing_key"]
        return [{"type": "set_dynamic_entity_param", "key": eff.get("key"), "target": _target(eff.get("target_policy"), "actor"), "param_target": _target(eff.get("param_target_policy"), "target")}], []
    if typ == "trigger_custom_string":
        if not eff.get("custom_string"):
            return [], ["trigger_custom_string_missing_value"]
        return [{"type": "trigger_custom_string", "custom_string": eff.get("custom_string")}], []
    if typ == "random_choice":
        rr = []
        choices = []
        for choice in eff.get("choices") or []:
            converted = []
            for ne in choice.get("effects") or []:
                ce, er = _convert_effect(ne, current_status_id); converted.extend(ce); rr.extend(er)
            choices.append({"index": choice.get("index", len(choices)), "effects": converted})
        if not choices:
            return [], ["random_choice_no_choices"]
        odds = []
        for raw in eff.get("odds_exprs") or []:
            odds.append(_resolved_value(raw, raw.get("_resolve") if isinstance(raw, dict) else None))
        random_count = _resolved_value(eff.get("random_count_expr"), eff.get("random_count_expr", {}).get("_resolve") if isinstance(eff.get("random_count_expr"), dict) else None) if eff.get("random_count_expr") is not None else 1
        return [{"type": "random_choice", "event_id": eff.get("event_id"), "odds": odds, "choices": choices, "random_count": random_count, "random_unique": eff.get("random_unique"), "random_mask_key": eff.get("random_mask_key"), "auto_reset_random_mask": eff.get("auto_reset_random_mask"), "random_mask_target": _target(eff.get("random_mask_target_policy"), "actor") if eff.get("random_mask_target_policy") is not None else None, "source": eff.get("source_node_type")}], rr
    if typ == "conditional_branch":
        cond, cr = _convert_condition(eff.get("condition"))
        converted_true = []
        converted_false = []
        rr = list(cr)
        for ne in eff.get("effects_if_true", eff.get("effects", [])) or []:
            ce, er = _convert_effect(ne, current_status_id); converted_true.extend(ce); rr.extend(er)
        for ne in eff.get("effects_if_false", []) or []:
            ce, er = _convert_effect(ne, current_status_id); converted_false.extend(ce); rr.extend(er)
        if isinstance(cond, dict) and isinstance(cond.get("chance_gate"), dict) and any(e.get("type") == "add_status" for e in converted_true):
            cond = deepcopy(cond)
            cond["chance_gate"]["use_effect_hit"] = True
            cond["chance_gate"]["source"] = "ByRandomChance.add_status_branch"
        return [{"type": "conditional_branch", "condition": cond, "effects_if_true": converted_true, "effects_if_false": converted_false}], rr
    return [], [f"unsupported_effect:{typ or 'unknown'}"]


def _effect_source_path(eff: dict[str, Any]) -> str:
    return str(eff.get("source_path") or eff.get("source") or "")


def _is_branch_member_effect(eff: dict[str, Any]) -> bool:
    path = _effect_source_path(eff)
    return ".SuccessTaskList[" in path or ".FailedTaskList[" in path


def _convert_branch_group(bg: dict[str, Any], current_status_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    cond, reasons = _convert_condition(bg.get("condition"))
    true_effects: list[dict[str, Any]] = []
    false_effects: list[dict[str, Any]] = []
    for eff in bg.get("success_effects", []) or []:
        ce, rr = _convert_effect(eff, current_status_id)
        true_effects.extend(ce); reasons.extend(rr)
    for eff in bg.get("failed_effects", []) or []:
        ce, rr = _convert_effect(eff, current_status_id)
        false_effects.extend(ce); reasons.extend(rr)
    true_effects = _dedupe_effects(true_effects)
    false_effects = _dedupe_effects(false_effects)
    # If both branches lower to the same effects, the predicate does not affect
    # runtime combat semantics.  Drop the condition and its unsupported reasons
    # instead of making an otherwise deterministic trigger non-executable.
    if true_effects and false_effects and _effect_list_signature(true_effects) == _effect_list_signature(false_effects):
        return true_effects, []
    if not true_effects and not false_effects:
        return [], reasons + ["branch_group_no_executable_effects"]
    return [{
        "type": "conditional_branch",
        "condition": cond,
        "effects_if_true": true_effects,
        "effects_if_false": false_effects,
        "source_branch_root": bg.get("branch_root"),
        "source_branch_index": bg.get("branch_index"),
    }], reasons


def _convert_trigger(status: dict[str, Any], trig: dict[str, Any]) -> dict[str, Any]:
    event_name = trig.get("event_name") or trig.get("event_root")
    event_text = str(event_name)
    timing = EVENT_TO_TIMING.get(event_text, None)
    reasons: list[str] = []
    if timing is None and event_text.startswith("OnAbilityPropertyChange"):
        timing = "ability_property_change"
    if timing is None and event_text.startswith("OnDynamicValueChange"):
        if ".OnEnterRange" in event_text:
            timing = "status_dynamic_value_enter_range"
        elif ".OnExitRange" in event_text:
            timing = "status_dynamic_value_exit_range"
        else:
            timing = "status_dynamic_value_change"
    if timing is None:
        reasons.append(f"unmapped_event:{event_name}")
        timing = f"unmapped:{event_name}"
    elif timing not in EXECUTABLE_TIMINGS:
        reasons.append(f"non_runtime_timing:{timing}")
    conds = trig.get("conditions") or []
    if len(conds) == 1:
        condition, rr = _convert_condition(conds[0])
        reasons.extend(rr)
    elif len(conds) > 1:
        converted = []
        for c in conds:
            cc, rr = _convert_condition(c); converted.append(cc); reasons.extend(rr)
        condition = {"all": converted}
    else:
        condition = {}
    effects = []
    if timing == "preshow_audit":
        effects.append({
            "type": "record_preshow_event",
            "event_name": event_name,
            "status_id": status.get("status_id"),
            "owner_avatar_id": status.get("owner_avatar_id"),
            "condition": deepcopy(condition),
        })
    status_id = str(status.get("status_id"))
    # Branch member effects are represented by branch_groups below; converting
    # them again as direct effects would make conditional effects unconditional.
    # Some watcher triggers preserve PredicateTaskList conditions in the trigger
    # condition but do not have a materialized branch_group yet; in that case,
    # keep their success-list effects under the trigger-level condition rather
    # than dropping them entirely.
    has_branch_groups = bool(trig.get("branch_groups"))
    for eff in trig.get("effects") or []:
        if has_branch_groups and _is_branch_member_effect(eff):
            continue
        ce, rr = _convert_effect(eff, status_id)
        effects.extend(ce); reasons.extend(rr)
    for bg in trig.get("branch_groups") or []:
        ce, rr = _convert_branch_group(bg, status_id)
        effects.extend(ce); reasons.extend(rr)
    effects = _dedupe_effects(effects)
    if not effects:
        reasons.append("no_executable_effects")
    return {
        "id": f"{status.get('owner_avatar_id')}:{status.get('status_id')}:{trig.get('trigger_id')}",
        "owner_avatar_id": status.get("owner_avatar_id"),
        "status_id": status.get("status_id"),
        "timing": timing,
        "source_event_name": event_name,
        "condition": condition,
        "effects": effects,
        "executable": not reasons,
        "unsupported_reasons": sorted(set(reasons)),
        "source_trigger_id": trig.get("trigger_id"),
    }



def _iter_effects_recursive(effects: list[dict[str, Any]]):
    for eff in effects or []:
        if not isinstance(eff, dict):
            continue
        yield eff
        for key in ("effects", "effects_if_true", "effects_if_false"):
            nested = eff.get(key)
            if isinstance(nested, list):
                yield from _iter_effects_recursive(nested)


def _runtime_operand_indexes(expr_ir: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for i, op in enumerate(expr_ir.get("operands") or []):
        if isinstance(op, dict) and op.get("kind") == "runtime_dynamic_value":
            out.append(i)
    return out


def _annotate_runtime_dynamic_value_keys(triggers: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach conservative runtime flag-key hints to symbolic operands.

    This remains in the template/compiler boundary: the kernel receives canonical
    runtime keys, not raw ConfigCharacter hash interpretation.  For now the only
    materialized pattern is Dan Heng PT's AttackConvert delta, where the same
    generated status owns both property snapshots:

      DanHengPT_Attack        <- SetDynamicValueByProperty(Attack)
      DanHengPT_ConvertAttack <- SetDynamicValueByProperty(AttackConvert)
      MDF_AttackDelta         <- (ConvertAttack - Attack) * PointB1[0]

    The resulting value is still only a status DynamicValue unless a later,
    separately proven property consumer maps AttackConvert to a simulator stat
    bucket.
    """
    flag_sources: dict[tuple[str, str], dict[str, str]] = {}
    for trig in triggers:
        if not isinstance(trig, dict):
            continue
        scope = (str(trig.get("owner_avatar_id")), str(trig.get("status_id")))
        props = flag_sources.setdefault(scope, {})
        for eff in _iter_effects_recursive(trig.get("effects") or []):
            if eff.get("type") == "set_flag_from_property" and eff.get("key") and eff.get("property"):
                props[str(eff.get("property"))] = str(eff.get("key"))
    annotated = 0
    skipped = 0
    for trig in triggers:
        if not isinstance(trig, dict):
            continue
        scope = (str(trig.get("owner_avatar_id")), str(trig.get("status_id")))
        props = flag_sources.get(scope, {})
        for eff in _iter_effects_recursive(trig.get("effects") or []):
            if eff.get("type") != "add_status":
                continue
            status = eff.get("status") if isinstance(eff.get("status"), dict) else {}
            hints = status.get("property_hints") if isinstance(status.get("property_hints"), list) else []
            if not any(isinstance(h, dict) and h.get("property") == "AttackConvert" for h in hints):
                continue
            symbolic = status.get("symbolic_dynamic_values") if isinstance(status.get("symbolic_dynamic_values"), dict) else {}
            for key, rec in symbolic.items():
                resolve = rec.get("resolve") if isinstance(rec, dict) and isinstance(rec.get("resolve"), dict) else {}
                expr_ir = resolve.get("symbolic_expression_ir") if isinstance(resolve, dict) else None
                if not isinstance(expr_ir, dict):
                    continue
                runtime_indexes = _runtime_operand_indexes(expr_ir)
                if expr_ir.get("opcodes") != "AQABAQMBAgQR" or len(runtime_indexes) != 2:
                    skipped += 1
                    continue
                attack_key = props.get("Attack")
                convert_key = props.get("AttackConvert")
                if not attack_key or not convert_key:
                    skipped += 1
                    continue
                # The proven postfix shape is dynamic0 dynamic1 sub dynamic2 mul.
                # For AttackConvert delta, dynamic0 is the converted attack
                # snapshot and dynamic1 is base attack.  Do not apply a formula
                # bucket here; just enable numeric DynamicValue materialization.
                operands = expr_ir.get("operands") or []
                operands[runtime_indexes[0]]["runtime_value_key"] = convert_key
                operands[runtime_indexes[1]]["runtime_value_key"] = attack_key
                rec.setdefault("runtime_operand_key_audit", []).append({
                    "applied": True,
                    "dynamic_value_key": str(key),
                    "pattern": "attack_convert_minus_attack_times_param",
                    "operand_0_key": convert_key,
                    "operand_1_key": attack_key,
                })
                annotated += 1
    return {"annotated_runtime_operand_count": annotated, "skipped_runtime_operand_count": skipped}

def compile_status_template_bundle(bound_status_ir_bundle: dict[str, Any], *, tbgd_source: TBGDSource | str | Path | None = None) -> dict[str, Any]:
    owner_avatar_ids = [int(s.get("owner_avatar_id")) for s in bound_status_ir_bundle.get("statuses", []) or [] if s.get("owner_avatar_id") is not None]
    property_hints = _collect_status_property_hints(tbgd_source, owner_avatar_ids)
    templates: dict[str, dict[str, Any]] = {}
    triggers: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    timing_counts: Counter[str] = Counter()
    for status in bound_status_ir_bundle.get("statuses", []) or []:
        sid = str(status.get("status_id"))
        meta = status.get("modifier_metadata") or {}
        template = {
            "id": sid,
            "source_namespace": status.get("namespace"),
            "owner_avatar_id": status.get("owner_avatar_id"),
            "tags": list(meta.get("behavior_flags") or []),
            "stack_rule": {},
            "source_status_ir_status": status.get("status_ir_status"),
        }
        if meta.get("max_layer") is not None:
            template["max_stacks"] = meta.get("max_layer")
            template["stack_rule"]["max_stacks"] = meta.get("max_layer")
        if meta.get("lifetime") is not None:
            template["duration"] = {"type": "owner_turns", "value": meta.get("lifetime"), "extra_turn_consumes_duration": False}
        if sid in property_hints:
            template["property_hints"] = deepcopy(property_hints[sid])
        templates[sid] = template
        for trig in status.get("triggers", []) or []:
            rt = _convert_trigger(status, trig)
            _attach_property_hints_to_effects(rt.get("effects", []), property_hints)
            triggers.append(rt)
            timing_counts[rt["timing"]] += 1
            for r in rt.get("unsupported_reasons") or []:
                reason_counts[r] += 1
    runtime_operand_key_summary = _annotate_runtime_dynamic_value_keys(triggers)
    executable = [t for t in triggers if t.get("executable")]
    return {
        "format": "hsr_status_template_bundle",
        "version": "v0.2",
        "source_format": bound_status_ir_bundle.get("format"),
        "source_version": bound_status_ir_bundle.get("version"),
        "status_templates": templates,
        "triggers": triggers,
        "summary": {
            "format": "hsr_status_template_summary",
            "version": "v0.2",
            "status_template_count": len(templates),
            "trigger_count": len(triggers),
            "executable_trigger_count": len(executable),
            "non_executable_trigger_count": len(triggers) - len(executable),
            "timing_counts": dict(timing_counts.most_common()),
            "unsupported_reason_counts": dict(reason_counts.most_common()),
            "property_hint_status_count": len(property_hints),
            "property_hint_count": sum(len(v) for v in property_hints.values()),
            "runtime_operand_key_summary": runtime_operand_key_summary,
            "top_non_executable_triggers": [
                {"id": t.get("id"), "timing": t.get("timing"), "reasons": t.get("unsupported_reasons")} for t in triggers if not t.get("executable")
            ][:20],
        },
    }


def write_status_template_bundle(bound_status_ir_bundle_path: str | Path, output_dir: str | Path, tbgd_source: TBGDSource | str | Path | None = None) -> dict[str, Any]:
    source = json.loads(Path(bound_status_ir_bundle_path).read_text(encoding="utf-8"))
    bundle = compile_status_template_bundle(source, tbgd_source=tbgd_source)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "status_template_bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = bundle.get("summary", {})
    (out_dir / "status_template_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
