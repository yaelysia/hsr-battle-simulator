from __future__ import annotations

"""Compile flattened modifier/status hints into canonical StatusIR previews.

This is a compiler-boundary module.  It consumes ActionIR/BoundActionIR
`status_definition_hints` that were intentionally kept out of direct action
execution, groups them by source modifier definition, and emits structured
StatusIR/TriggerIR/EffectIR candidates.  It does not execute combat and it does
not ask the Combat Kernel to understand raw TurnBasedGameData paths.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any
import json
import re

from .tbgd_loader import TBGDSource, unwrap_value


STATUS_PATH_RE = re.compile(r"^(?P<namespace>Modifiers|GlobalModifiers)\.(?P<status_id>[^.]+)\.(?P<rest>.*)$")
CALLBACK_RE = re.compile(r"^(?P<callback>_CallbackList\[(?P<callback_index>\d+)\])(?P<tail>.*)$")
DYNAMIC_VALUE_RE = re.compile(
    r"^(?P<root>OnDynamicValueChange\[(?P<dynamic_index>\d+)\]\.Ranges\[(?P<range_index>\d+)\]\.(?P<range_event>OnEnterRange|OnExitRange|OnChange)\[(?P<event_index>\d+)\])(?P<tail>.*)$"
)
ABILITY_PROPERTY_RE = re.compile(
    r"^(?P<root>OnAbilityPropertyChange\[(?P<property_index>\d+)\]\.Ranges\[(?P<range_index>\d+)\]\.OnChange\[(?P<event_index>\d+)\])(?P<tail>.*)$"
)
PRESHOW_RE = re.compile(r"^(?P<root>ModifierAffectedPreshowConfig|ModifierCreateEntityPreshowConfig)(?P<tail>.*)$")
CONDITIONAL_TASK_RE = re.compile(
    r"(?P<branch_root>.*?CallbackConfig\[(?P<branch_index>\d+)\])(?:\.(?P<branch_part>Predicate|SuccessTaskList\[(?P<success_index>\d+)\]|FailedTaskList\[(?P<failed_index>\d+)\]).*)?$"
)

# These types are runtime effects when they appear inside a status definition.
STATUS_EFFECT_TYPES = {
    "add_status", "remove_status", "set_flag", "add_flag_value", "copy_flag",
    "set_flag_from_property", "set_flag_from_status_value", "set_flag_from_context_value",
    "define_flag", "set_status_dynamic_value", "stack_property",
    "modify_skill_points", "modify_skill_point_cap", "modify_current_skill_delay_cost",
    "modify_skill_property", "heal_unit", "modify_action_value", "enqueue_action",
    "conditional_enqueue_action", "enqueue_turn_action", "summon_unit", "dispel_status",
    "modify_damage_data", "trigger_effect", "remove_effect", "include_task_template",
    "include_task_list_template", "attach_effect_to_status", "owner_add_ability",
    "create_battle_event", "modify_versus_bar", "set_energy_bar_state", "change_phase",
    "force_defeat", "damage_packet", "conditional_branch",
    "random_config", "random_select_dynamic_value", "set_dynamic_entity_param", "trigger_custom_string",
}

STATUS_CONDITION_TYPES = {
    "all", "any", "not", "compare_dynamic_value", "has_status", "compare_status_value",
    "compare_hp_ratio", "target_team", "action_type", "eidolon_or_rank_active",
    "skill_point_activated", "is_insert_action", "is_current_skill_active", "compare_wave_count",
    "character_damage_type", "contains_behavior_flag", "modifier_callback_name", "compare_target",
    "compare_monster_phase", "custom_bool", "compare_battle_event_id", "compare_monster_id",
    "compare_character_id", "compare_monster_rank", "target_lists_intersect", "target_entity_type",
    "has_weakness", "compare_character_number", "team_location_index_type", "current_skill_name",
    "target_alive_state", "any_enemy_alive", "compare_param_value", "compare_param_string",
    "is_target_valid", "is_turn_owner_entity", "is_turn_action_entity", "generic_compare_condition",
    "generic_predicate_condition",
}


class StatusIRCompileError(RuntimeError):
    pass


def _parse_status_source_path(source_path: str) -> dict[str, Any] | None:
    m = STATUS_PATH_RE.match(str(source_path or ""))
    if not m:
        return None
    rest = m.group("rest")
    out: dict[str, Any] = {
        "namespace": m.group("namespace"),
        "status_id": m.group("status_id"),
        "rest": rest,
        "event_root": rest.split(".", 1)[0] if rest else "",
        "event_kind": "unknown_status_definition_member",
        "tail": "",
    }

    cm = CALLBACK_RE.match(rest)
    if cm:
        out.update({
            "event_kind": "modifier_callback",
            "event_root": cm.group("callback"),
            "callback_index": int(cm.group("callback_index")),
            "tail": (cm.group("tail") or "").lstrip("."),
        })
        return out

    dm = DYNAMIC_VALUE_RE.match(rest)
    if dm:
        out.update({
            "event_kind": "dynamic_value_range",
            "event_root": dm.group("root"),
            "dynamic_index": int(dm.group("dynamic_index")),
            "range_index": int(dm.group("range_index")),
            "range_event": dm.group("range_event"),
            "event_index": int(dm.group("event_index")),
            "tail": (dm.group("tail") or "").lstrip("."),
        })
        return out

    am = ABILITY_PROPERTY_RE.match(rest)
    if am:
        out.update({
            "event_kind": "ability_property_change",
            "event_root": am.group("root"),
            "property_index": int(am.group("property_index")),
            "range_index": int(am.group("range_index")),
            "event_index": int(am.group("event_index")),
            "tail": (am.group("tail") or "").lstrip("."),
        })
        return out

    pm = PRESHOW_RE.match(rest)
    if pm:
        root = pm.group("root")
        out.update({
            "event_kind": "preshow_condition" if "Preshow" in root else "status_definition_config",
            "event_root": root,
            "tail": (pm.group("tail") or "").lstrip("."),
        })
        return out

    return out


def _condition_signature(cond: Any) -> str:
    try:
        return json.dumps(cond, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return str(cond)


def _dedupe_conditions(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cond in conditions:
        sig = _condition_signature(cond)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(cond)
    return out


def _sort_key_for_hint(hint: dict[str, Any]) -> tuple[int, str]:
    path = str(hint.get("source_path") or "")
    nums = [int(x) for x in re.findall(r"\[(\d+)\]", path)]
    # Stable enough for arrays; path keeps sibling names deterministic.
    weight = 0
    mul = 1
    for n in nums[:6]:
        weight += n * mul
        mul *= 100
    return weight, path


def _branch_membership(tail: str) -> dict[str, Any] | None:
    m = CONDITIONAL_TASK_RE.match(tail or "")
    if not m:
        return None
    root = m.group("branch_root")
    if "CallbackConfig" not in root:
        return None
    part = m.group("branch_part") or "branch_root"
    return {
        "branch_root": root,
        "branch_index": int(m.group("branch_index")),
        "branch_part": part,
        "success_index": int(m.group("success_index")) if m.group("success_index") is not None else None,
        "failed_index": int(m.group("failed_index")) if m.group("failed_index") is not None else None,
    }



def _random_config_parent_for_tail(tail: str, random_roots: list[str]) -> tuple[str, int] | None:
    for root in sorted(random_roots, key=len, reverse=True):
        prefix = root + ".TaskList["
        if tail.startswith(prefix):
            rest = tail[len(prefix):]
            idx_s = rest.split("]", 1)[0]
            try:
                return root, int(idx_s)
            except Exception:
                return root, 0
    return None


def _compile_trigger(trigger_meta: dict[str, Any], hints: list[dict[str, Any]]) -> dict[str, Any]:
    hints = sorted(hints, key=_sort_key_for_hint)
    conditions: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    control_flow: list[dict[str, Any]] = []
    raw_condition_items: list[dict[str, Any]] = []
    unsupported: Counter[str] = Counter()
    branch_groups: dict[str, dict[str, Any]] = {}
    random_configs: dict[str, dict[str, Any]] = {}
    for h in hints:
        if str(h.get("type")) == "random_config":
            tail = str(h.get("_status_path", {}).get("tail") or "")
            random_configs[tail] = deepcopy({k: v for k, v in h.items() if not k.startswith("_status_")})
    random_choice_groups: dict[str, dict[str, Any]] = {
        root: {
            "type": "random_choice",
            "event_id": f"random_choice:{trigger_meta.get('status_id')}:{root}",
            "odds_exprs": rc.get("odds_exprs", []),
            "choice_count": rc.get("choice_count", 0),
            "random_count_expr": rc.get("random_count_expr"),
            "random_unique": rc.get("random_unique"),
            "random_mask_key": rc.get("random_mask_key"),
            "auto_reset_random_mask": rc.get("auto_reset_random_mask"),
            "random_mask_target_policy": rc.get("random_mask_target_policy"),
            "choices": defaultdict(list),
            "source_node_type": "RPG.GameCore.RandomConfig",
            "source_path_tail": root,
        } for root, rc in random_configs.items()
    }

    for hint in hints:
        typ = str(hint.get("type"))
        tail = str(hint.get("_status_path", {}).get("tail") or "")
        item = deepcopy({k: v for k, v in hint.items() if not k.startswith("_status_")})
        is_branch_member = (
            typ == "conditional_branch"
            or ".Predicate" in tail
            or ".SuccessTaskList" in tail
            or ".FailedTaskList" in tail
        )
        bm = _branch_membership(tail) if is_branch_member else None
        random_parent = _random_config_parent_for_tail(tail, list(random_configs.keys())) if typ != "random_config" else None
        if random_parent and typ in STATUS_EFFECT_TYPES:
            root, choice_index = random_parent
            random_choice_groups[root]["choices"][choice_index].append(item)
            continue

        if bm:
            bg = branch_groups.setdefault(bm["branch_root"], {
                "branch_root": bm["branch_root"],
                "branch_index": bm["branch_index"],
                "condition": None,
                "success_effects": [],
                "failed_effects": [],
                "observed_condition_nodes": [],
            })
            if typ == "conditional_branch" and item.get("condition") is not None:
                bg["condition"] = item.get("condition")
            elif bm["branch_part"] == "Predicate" and typ in STATUS_CONDITION_TYPES:
                bg["observed_condition_nodes"].append(item)
            elif bm["success_index"] is not None and typ in STATUS_EFFECT_TYPES:
                bg["success_effects"].append(item)
            elif bm["failed_index"] is not None and typ in STATUS_EFFECT_TYPES:
                bg["failed_effects"].append(item)

        if typ == "random_config":
            continue
        if typ == "conditional_branch":
            control_flow.append(item)
            if item.get("condition") is not None:
                conditions.append(item["condition"])
        elif typ in STATUS_CONDITION_TYPES:
            raw_condition_items.append(item)
            # Path-level predicate nodes are useful for audit but usually duplicate
            # the condition already attached to conditional_branch.  Keep them in
            # raw_condition_items and only promote non-branch preshow conditions to
            # trigger conditions.
            if "Predicate" not in tail and trigger_meta.get("event_kind") == "preshow_condition":
                conditions.append(item)
        elif typ in STATUS_EFFECT_TYPES:
            effects.append(item)
        else:
            unsupported[typ] += 1

    for bg in branch_groups.values():
        bg["observed_condition_nodes"] = _dedupe_conditions(bg["observed_condition_nodes"])

    for rg in random_choice_groups.values():
        choice_rows = []
        max_count = max(int(rg.get("choice_count") or 0), (max(rg["choices"].keys()) + 1 if rg["choices"] else 0))
        for i in range(max_count):
            choice_rows.append({"index": i, "effects": rg["choices"].get(i, [])})
        if choice_rows:
            eff = {k: v for k, v in rg.items() if k != "choices"}
            eff["choices"] = choice_rows
            effects.append(eff)

    trigger_id = f"{trigger_meta.get('event_kind')}:{trigger_meta.get('event_root')}"
    return {
        "trigger_id": trigger_id,
        "trigger_kind": trigger_meta.get("event_kind"),
        "event_root": trigger_meta.get("event_root"),
        "event_metadata": {k: v for k, v in trigger_meta.items() if k not in {"namespace", "status_id", "rest", "tail"}},
        "conditions": _dedupe_conditions(conditions),
        "effects": effects,
        "control_flow": control_flow,
        "branch_groups": sorted(branch_groups.values(), key=lambda x: (x.get("branch_index", 0), x.get("branch_root", ""))),
        "raw_condition_items": raw_condition_items,
        "unsupported_hint_types": dict(unsupported),
        "hint_count": len(hints),
    }



def _dynamic_value_keys(raw: Any) -> dict[str, list[str]]:
    raw = unwrap_value(raw or {})
    out: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return out
    for group, vals in raw.items():
        vals = unwrap_value(vals)
        if isinstance(vals, dict):
            out[str(group)] = sorted(str(k) for k in vals.keys())
        elif isinstance(vals, list):
            out[str(group)] = [str(i) for i, _ in enumerate(vals)]
        else:
            out[str(group)] = []
    return out


def _extract_modifier_metadata(modifier: dict[str, Any]) -> dict[str, Any]:
    modifier = unwrap_value(modifier or {})
    callbacks = []
    for i, cb in enumerate(modifier.get("_CallbackList", []) if isinstance(modifier.get("_CallbackList", []), list) else []):
        if not isinstance(cb, dict):
            continue
        cfg = cb.get("CallbackConfig") if isinstance(cb.get("CallbackConfig"), list) else []
        callbacks.append({
            "callback_index": i,
            "event": cb.get("Event"),
            "priority": cb.get("Priority"),
            "callback_config_count": len(cfg),
        })
    dyn_changes = []
    for i, change in enumerate(modifier.get("OnDynamicValueChange", []) if isinstance(modifier.get("OnDynamicValueChange", []), list) else []):
        ranges = change.get("Ranges", []) if isinstance(change, dict) and isinstance(change.get("Ranges", []), list) else []
        dyn_changes.append({"dynamic_index": i, "range_count": len(ranges)})
    prop_changes = []
    for i, change in enumerate(modifier.get("OnAbilityPropertyChange", []) if isinstance(modifier.get("OnAbilityPropertyChange", []), list) else []):
        ranges = change.get("Ranges", []) if isinstance(change, dict) and isinstance(change.get("Ranges", []), list) else []
        prop_changes.append({"property_index": i, "range_count": len(ranges)})
    return {
        "behavior_flags": modifier.get("BehaviorFlagList") or [],
        "stacking": modifier.get("Stacking"),
        "max_layer": modifier.get("MaxLayer") or modifier.get("MaxLevel"),
        "lifetime": modifier.get("LifeTime"),
        "dynamic_values_declared": _dynamic_value_keys(modifier.get("DynamicValues")),
        "has_modifier_affected_preshow_config": isinstance(modifier.get("ModifierAffectedPreshowConfig"), dict),
        "has_modifier_create_entity_preshow_config": isinstance(modifier.get("ModifierCreateEntityPreshowConfig"), dict),
        "callbacks": callbacks,
        "dynamic_value_change_watchers": dyn_changes,
        "ability_property_change_watchers": prop_changes,
    }


def _modifier_metadata_by_avatar(bound_action_bundle: dict[str, Any], source: TBGDSource | None) -> dict[tuple[Any, str, str], dict[str, Any]]:
    if source is None:
        return {}
    out: dict[tuple[Any, str, str], dict[str, Any]] = {}
    for avatar in bound_action_bundle.get("avatars", []) or []:
        avatar_id = avatar.get("avatar_id")
        ability_path = ((avatar.get("config_paths") or {}).get("ability"))
        if not ability_path:
            continue
        try:
            ability_file = unwrap_value(source.read_json(str(ability_path)))
        except Exception:
            continue
        for ability in ability_file.get("AbilityList", []) if isinstance(ability_file.get("AbilityList", []), list) else []:
            if not isinstance(ability, dict):
                continue
            for namespace in ("Modifiers", "GlobalModifiers"):
                mods = ability.get(namespace, {})
                if not isinstance(mods, dict):
                    continue
                for status_id, modifier in mods.items():
                    if not isinstance(modifier, dict):
                        continue
                    key = (avatar_id, namespace, str(status_id))
                    meta = _extract_modifier_metadata(modifier)
                    meta["defined_in_ability"] = ability.get("Name")
                    meta["ability_path"] = str(ability_path)
                    out[key] = meta
        top_global = ability_file.get("GlobalModifiers", {}) if isinstance(ability_file, dict) else {}
        if isinstance(top_global, dict):
            for status_id, modifier in top_global.items():
                if isinstance(modifier, dict):
                    key = (avatar_id, "GlobalModifiers", str(status_id))
                    meta = _extract_modifier_metadata(modifier)
                    meta["defined_in_ability"] = "<file.GlobalModifiers>"
                    meta["ability_path"] = str(ability_path)
                    out[key] = meta
    return out


def _callback_event_lookup(modifier_meta: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not modifier_meta:
        return {}
    out = {}
    for cb in modifier_meta.get("callbacks", []) or []:
        try:
            out[int(cb.get("callback_index"))] = cb
        except Exception:
            pass
    return out



def _collect_dynamic_expression_refs(obj: Any, path: str = "") -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        is_dynamic = obj.get("expr_kind") or obj.get("IsDynamic") is True
        if is_dynamic:
            hashes = obj.get("dynamic_hashes")
            fixed_values = obj.get("fixed_values")
            if hashes is None and isinstance(obj.get("PostfixExpr"), dict):
                hashes = obj["PostfixExpr"].get("DynamicHashes")
                fixed_values = obj["PostfixExpr"].get("FixedValues")
            refs.append({
                "path": path,
                "expr_kind": obj.get("expr_kind") or ("raw_tbgd_dynamic" if obj.get("IsDynamic") is True else None),
                "opcodes": obj.get("opcodes") or (obj.get("PostfixExpr") or {}).get("OpCodes") if isinstance(obj.get("PostfixExpr"), dict) else obj.get("opcodes"),
                "dynamic_hashes": unwrap_value(hashes or []),
                "fixed_values": unwrap_value(fixed_values or []),
            })
        for k, v in obj.items():
            child = f"{path}.{k}" if path else str(k)
            refs.extend(_collect_dynamic_expression_refs(v, child))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            refs.extend(_collect_dynamic_expression_refs(v, f"{path}[{i}]"))
    return refs


def _summarize_dynamic_expression_refs(refs: list[dict[str, Any]]) -> dict[str, Any]:
    hash_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    for ref in refs:
        kind_counts[str(ref.get("expr_kind"))] += 1
        for h in ref.get("dynamic_hashes") or []:
            hash_counts[str(h)] += 1
    return {
        "dynamic_expression_count": len(refs),
        "dynamic_hash_counts": dict(hash_counts.most_common()),
        "expr_kind_counts": dict(kind_counts.most_common()),
        "sample_refs": refs[:12],
    }



def _aggregate_dynamic_hash_counts(statuses: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for status in statuses:
        for h, c in ((status.get("dynamic_expression_summary") or {}).get("dynamic_hash_counts") or {}).items():
            try:
                counts[str(h)] += int(c)
            except Exception:
                counts[str(h)] += 1
    return dict(counts.most_common(50))

def compile_status_ir_bundle(bound_action_bundle: dict[str, Any], source: TBGDSource | None = None) -> dict[str, Any]:
    statuses: dict[tuple[int | str, str, str], dict[str, Any]] = {}
    invalid_paths: list[str] = []
    type_counts: Counter[str] = Counter()
    event_kind_counts: Counter[str] = Counter()
    modifier_meta = _modifier_metadata_by_avatar(bound_action_bundle, source)

    for avatar in bound_action_bundle.get("avatars", []) or []:
        avatar_id = avatar.get("avatar_id")
        for action in avatar.get("actions", []) or []:
            action_id = action.get("action_id")
            trigger_key = action.get("trigger_key")
            for raw_hint in action.get("status_definition_hints") or []:
                if not isinstance(raw_hint, dict):
                    continue
                source_path = str(raw_hint.get("source_path") or "")
                meta = _parse_status_source_path(source_path)
                if meta is None:
                    invalid_paths.append(source_path)
                    continue
                hint = deepcopy(raw_hint)
                hint["_status_path"] = meta
                type_counts[str(hint.get("type"))] += 1
                event_kind_counts[str(meta.get("event_kind"))] += 1
                key = (avatar_id, str(meta["namespace"]), str(meta["status_id"]))
                status = statuses.setdefault(key, {
                    "status_id": meta["status_id"],
                    "namespace": meta["namespace"],
                    "owner_avatar_id": avatar_id,
                    "source_action_ids": [],
                    "source_trigger_keys": [],
                    "_trigger_hints": defaultdict(list),
                })
                if action_id not in status["source_action_ids"]:
                    status["source_action_ids"].append(action_id)
                if trigger_key not in status["source_trigger_keys"]:
                    status["source_trigger_keys"].append(trigger_key)
                tkey = (meta.get("event_kind"), meta.get("event_root"))
                status["_trigger_hints"][tkey].append(hint)

    out_statuses: list[dict[str, Any]] = []
    for status in statuses.values():
        trigger_hints = status.pop("_trigger_hints")
        mkey = (status.get("owner_avatar_id"), status.get("namespace"), status.get("status_id"))
        raw_meta = modifier_meta.get(mkey, {})
        if raw_meta:
            status["modifier_metadata"] = raw_meta
        cb_events = _callback_event_lookup(raw_meta)
        triggers = []
        for (_kind, _root), hints in sorted(trigger_hints.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
            meta = hints[0].get("_status_path") or {}
            trig = _compile_trigger(meta, hints)
            if meta.get("event_kind") == "modifier_callback" and meta.get("callback_index") in cb_events:
                trig["event_name"] = cb_events[meta.get("callback_index")].get("event")
                trig["event_priority"] = cb_events[meta.get("callback_index")].get("priority")
                trig["callback_config_count"] = cb_events[meta.get("callback_index")].get("callback_config_count")
            triggers.append(trig)
        status["triggers"] = triggers
        status["trigger_count"] = len(triggers)
        status["hint_count"] = sum(t.get("hint_count", 0) for t in triggers)
        dyn_refs = _collect_dynamic_expression_refs({"triggers": triggers, "modifier_metadata": status.get("modifier_metadata", {})})
        status["dynamic_expression_summary"] = _summarize_dynamic_expression_refs(dyn_refs)
        status["status_ir_status"] = "candidate_status_ir" if triggers else "metadata_only"
        out_statuses.append(status)

    out_statuses.sort(key=lambda s: (str(s.get("owner_avatar_id")), str(s.get("namespace")), str(s.get("status_id"))))
    summary = {
        "format": "hsr_status_ir_summary",
        "version": "v0.2",
        "status_count": len(out_statuses),
        "trigger_count": sum(s.get("trigger_count", 0) for s in out_statuses),
        "hint_count": sum(s.get("hint_count", 0) for s in out_statuses),
        "invalid_source_path_count": len(invalid_paths),
        "invalid_source_paths_sample": invalid_paths[:20],
        "hint_type_counts": dict(type_counts.most_common()),
        "event_kind_counts": dict(event_kind_counts.most_common()),
        "metadata_enriched_status_count": sum(1 for s in out_statuses if s.get("modifier_metadata")),
        "callback_event_name_counts": dict(Counter(t.get("event_name") for s in out_statuses for t in s.get("triggers", []) if t.get("event_name")).most_common()),
        "dynamic_expression_count": sum((s.get("dynamic_expression_summary") or {}).get("dynamic_expression_count", 0) for s in out_statuses),
        "top_dynamic_hash_counts": _aggregate_dynamic_hash_counts(out_statuses),
        "top_statuses_by_hint_count": [
            {
                "owner_avatar_id": s.get("owner_avatar_id"),
                "namespace": s.get("namespace"),
                "status_id": s.get("status_id"),
                "hint_count": s.get("hint_count"),
                "trigger_count": s.get("trigger_count"),
            }
            for s in sorted(out_statuses, key=lambda x: x.get("hint_count", 0), reverse=True)[:20]
        ],
    }
    return {
        "format": "hsr_status_ir_bundle",
        "version": "v0.2",
        "source_action_ir_format": bound_action_bundle.get("format"),
        "source_action_ir_version": bound_action_bundle.get("version"),
        "avatar_ids": bound_action_bundle.get("avatar_ids"),
        "statuses": out_statuses,
        "summary": summary,
    }


def write_status_ir_bundle(bound_action_ir_bundle_path: str | Path, output_dir: str | Path, tbgd_source: str | Path | TBGDSource | None = None) -> dict[str, Any]:
    bundle = json.loads(Path(bound_action_ir_bundle_path).read_text(encoding="utf-8"))
    src = tbgd_source if isinstance(tbgd_source, TBGDSource) or tbgd_source is None else TBGDSource.open(tbgd_source)
    status_ir = compile_status_ir_bundle(bundle, source=src)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "status_ir_bundle.json").write_text(json.dumps(status_ir, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "status_ir_summary.json").write_text(json.dumps(status_ir.get("summary", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return status_ir.get("summary", {})
