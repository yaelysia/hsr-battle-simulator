from __future__ import annotations

from copy import deepcopy
from typing import Any

from .core_rules import (
    coerce_bool,
    coerce_float,
    coerce_numeric_value,
    normalize_flag_values,
    normalize_str_list,
    normalize_triggers,
)

# Canonical simulator effect names.  Anything in this table is accepted at the
# external data boundary and converted before BattleSimulator sees it.
EFFECT_TYPE_ALIASES = {
    # Only aliases that the engine does not already treat with special semantics
    # are rewritten at the schema boundary.  Character-text aliases such as
    # add_buff / launch_follow_up_attack remain intact because BattleSimulator
    # has dedicated behavior for them.
    "summon_entity": "summon_unit",
}

# Common field aliases used by model-pack/generated route YAML.  The normalizer
# keeps old fields too when they are harmless, but guarantees the canonical one exists.
DAMAGE_FIELD_ALIASES = {
    "damage_type": "damage_type",
    "target": "target_policy",
}

QUEUE_POLICY_KEYS = ("queued_action_policy", "queue_policy", "queue_behavior")


def _copy(raw: Any) -> Any:
    return deepcopy(raw)


def _normalize_bool_fields(d: dict[str, Any], fields: list[str], default: bool | None = None) -> None:
    for f in fields:
        if f in d:
            d[f] = coerce_bool(d[f], default=default if default is not None else False)


def _normalize_num_fields(d: dict[str, Any], fields: list[str]) -> None:
    for f in fields:
        if f in d:
            try:
                d[f] = coerce_float(d[f])
            except Exception:
                pass


def _normalize_effect(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    eff = _copy(raw)
    etype = eff.get("type")
    if isinstance(etype, str):
        eff["type"] = EFFECT_TYPE_ALIASES.get(etype, etype)

    raw_type = raw.get("type")

    # Status aliases.
    if "status_id" not in eff:
        for k in ("buff_id", "debuff_id"):
            if k in eff:
                eff["status_id"] = eff[k]
                break
    if eff.get("type") == "add_status" and "status" not in eff and "status_id" in eff:
        eff["status"] = {"id": eff["status_id"]}

    # Action aliases.
    if "action" not in eff and "action_id" in eff:
        eff["action"] = eff["action_id"]
    if "actor" not in eff and "actor_id" in eff:
        eff["actor"] = eff["actor_id"]

    # Target aliases are left data-driven but normalized from scalar/list ambiguity.
    if "targets" in eff and isinstance(eff["targets"], str):
        eff["targets"] = [eff["targets"]]

    _normalize_bool_fields(
        eff,
        [
            "affected_by_err",
            "grant_if_defeated",
            "ignore_shield",
            "allow_dead_actor",
            "carry_across_wave",
        ],
    )
    _normalize_num_fields(
        eff,
        [
            "amount",
            "percent",
            "advance_percent",
            "delay_percent",
            "target_max_hp_pct",
            "target_max_energy_pct",
            "source_max_energy_pct",
            "shield",
            "shield_amount",
            "toughness",
            "toughness_reduction",
        ],
    )

    # Normalize nested effect containers recursively.
    for key in ("effects", "effects_if_true", "effects_if_false", "on_depleted"):
        if key in eff:
            eff[key] = normalize_effects(eff[key])
    if "effect" in eff and "effects" not in eff:
        eff["effects"] = normalize_effects(eff["effect"])
    return eff


def normalize_effects(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        maybe = _normalize_effect(raw)
        return [maybe] if maybe is not None else []
    if isinstance(raw, list):
        out = []
        for item in raw:
            maybe = _normalize_effect(item)
            if maybe is not None:
                out.append(maybe)
        return out
    return []


def normalize_status_def(raw: Any, default_id: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    st = _copy(raw)
    if default_id is not None:
        st.setdefault("id", default_id)
    st["tags"] = normalize_str_list(st.get("tags", []))
    if "duration" in st and isinstance(st["duration"], dict):
        _normalize_bool_fields(st["duration"], ["extra_turn_consumes", "extra_turn_consumes_duration"])
        _normalize_num_fields(st["duration"], ["value"])
    if "stack_rule" in st and isinstance(st["stack_rule"], dict):
        _normalize_num_fields(st["stack_rule"], ["max_stacks"])
        _normalize_bool_fields(st["stack_rule"], ["refresh_duration"])
    if "modifiers" in st and isinstance(st["modifiers"], dict):
        for k, v in list(st["modifiers"].items()):
            parsed = coerce_numeric_value(v)
            st["modifiers"][k] = parsed
    return st


def normalize_damage_packet(raw: Any, *, action_level: int | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    p = _copy(raw)

    if "target" in p and "target_policy" not in p:
        p["target_policy"] = p["target"]
    if "targets" in p and isinstance(p["targets"], str):
        p["targets"] = [p["targets"]]

    # Model-pack nested scaling block.
    scaling = p.get("scaling") if isinstance(p.get("scaling"), dict) else {}
    if scaling:
        p.setdefault("scaling_stat", scaling.get("stat", scaling.get("scaling_stat")))
        if "multiplier" not in p:
            if "multiplier" in scaling:
                p["multiplier"] = scaling["multiplier"]
            elif isinstance(scaling.get("multiplier_by_level"), dict):
                table = scaling["multiplier_by_level"]
                explicit_level = action_level if action_level is not None else p.get("level")
                if explicit_level is not None:
                    level_key = str(int(coerce_float(explicit_level)))
                    p["multiplier"] = table.get(level_key, table.get(explicit_level, next(iter(table.values()))))
                else:
                    numeric_items = []
                    for lvl, val in table.items():
                        try:
                            numeric_items.append((coerce_float(lvl), val))
                        except Exception:
                            pass
                    p["multiplier"] = sorted(numeric_items)[-1][1] if numeric_items else next(iter(table.values()))
            elif "flat_damage" in scaling:
                p["flat_damage"] = scaling["flat_damage"]
        if "multiplier_by_reference" in scaling and "multiplier_by_reference" not in p:
            p["multiplier_by_reference"] = scaling["multiplier_by_reference"]

    crit = p.get("crit") if isinstance(p.get("crit"), dict) else {}
    if crit:
        p.setdefault("can_crit", crit.get("can_crit"))
        p.setdefault("forced_crit", crit.get("forced_crit"))

    toughness = p.get("toughness") if isinstance(p.get("toughness"), dict) else {}
    if toughness:
        for k in ("toughness_reduction", "ignore_weakness_for_toughness"):
            if k in toughness and k not in p:
                p[k] = toughness[k]

    # Canonical booleans and numerics.
    _normalize_bool_fields(p, ["can_crit", "forced_crit", "ignore_shield", "ignore_weakness_for_toughness"])
    _normalize_num_fields(
        p,
        [
            "multiplier",
            "flat_damage",
            "def_ignore",
            "res_pen",
            "crit_rate_add",
            "crit_dmg_add",
            "dmg_bonus_multiplier",
            "dmg_bonus_add",
            "toughness_reduction",
            "damage_taken",
        ],
    )

    # hit_model.hits is represented internally by multiple packets.  This helper
    # returns only a single packet; expansion is handled at action level.
    return p


def expand_action_damage_packets(action: dict[str, Any]) -> list[dict[str, Any]]:
    packets_raw: list[Any] = []
    if "damage_packets" in action:
        raw = action.get("damage_packets")
        if isinstance(raw, list):
            packets_raw.extend(raw)
        elif isinstance(raw, dict):
            packets_raw.append(raw)
    if "damage_packet" in action:
        packets_raw.append(action.get("damage_packet"))

    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(packets_raw, start=1):
        p = normalize_damage_packet(raw, action_level=action.get("level"))
        if p is None:
            continue
        hit_model = p.get("hit_model") if isinstance(p.get("hit_model"), dict) else action.get("hit_model")
        hits = hit_model.get("hits") if isinstance(hit_model, dict) else None
        if isinstance(hits, list) and hits:
            base_multiplier = coerce_float(p.get("multiplier", 0.0), 0.0)
            total_weight = sum(coerce_float(h, 0.0) for h in hits) or 1.0
            for h_i, h in enumerate(hits, start=1):
                hp = _copy(p)
                hp["id"] = f"{p.get('id', f'packet_{idx}')}_hit_{h_i}"
                hp["multiplier"] = base_multiplier * coerce_float(h, 0.0) / total_weight
                hp.pop("hit_model", None)
                out.append(hp)
        else:
            out.append(p)
    return out


def normalize_action(raw: Any, default_id: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    action = _copy(raw)
    if default_id is not None:
        action.setdefault("id", default_id)
    action["tags"] = normalize_str_list(action.get("tags", []))

    if "action_id" in action and "id" not in action:
        action["id"] = action["action_id"]
    if "target" in action and "target_policy" not in action:
        action["target_policy"] = action["target"]
    if "targets" in action and isinstance(action["targets"], str):
        action["targets"] = [action["targets"]]

    if "skill_point_delta" in action:
        action.setdefault("cost", {})
        if isinstance(action["cost"], dict) and "skill_points" not in action["cost"]:
            action["cost"]["skill_points"] = int(coerce_float(action["skill_point_delta"]))

    # Queue-policy aliases share one canonical container while preserving original data.
    for key in QUEUE_POLICY_KEYS:
        if isinstance(action.get(key), dict):
            q = _copy(action[key])
            _normalize_bool_fields(q, ["carry_across_wave"])
            action.setdefault("queued_action_policy", q)
            break

    for key in (
        "effects_after_action_start",
        "effects_before_damage",
        "effects_after_damage",
        "effects",
        "effects_on_action_end",
    ):
        if key in action:
            action[key] = normalize_effects(action[key])
    if "effect" in action and "effects" not in action:
        action["effects"] = normalize_effects(action["effect"])

    action["damage_packets"] = expand_action_damage_packets(action)
    action.pop("damage_packet", None)
    return action


def normalize_unit(raw: Any, unit_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    unit = _copy(raw)
    unit.setdefault("id", unit_id)
    unit["tags"] = normalize_str_list(unit.get("tags", []))
    unit["weaknesses"] = normalize_str_list(unit.get("weaknesses", []))
    unit["flags"] = normalize_flag_values(unit.get("flags", {}))
    _normalize_bool_fields(unit, ["alive", "is_broken", "carry_over_damage"])
    _normalize_num_fields(unit, ["hp", "max_hp", "shield", "speed", "remaining_av", "level", "energy", "max_energy"])

    for key in ("stats", "stat_base", "base_stats", "stat_pct", "pct_stats", "stat_flat", "flat_stats", "res", "resistance"):
        if isinstance(unit.get(key), dict):
            for k, v in list(unit[key].items()):
                parsed = coerce_numeric_value(v)
                unit[key][k] = parsed

    if isinstance(unit.get("hp_model"), dict):
        hp_model = unit["hp_model"]
        _normalize_bool_fields(hp_model, ["carry_over_damage"])
        if isinstance(hp_model.get("bars"), list):
            bars = []
            for b in hp_model["bars"]:
                if isinstance(b, dict):
                    nb = _copy(b)
                    _normalize_num_fields(nb, ["hp"])
                    if "on_depleted" in nb:
                        nb["on_depleted"] = normalize_effects(nb["on_depleted"])
                    bars.append(nb)
            hp_model["bars"] = bars

    statuses = unit.get("statuses", [])
    if isinstance(statuses, list):
        unit["statuses"] = [normalize_status_def(s) for s in statuses if isinstance(s, dict)]

    if isinstance(unit.get("status_effects"), dict):
        unit["status_effects"] = {sid: normalize_status_def(s, sid) for sid, s in unit["status_effects"].items()}
    if isinstance(unit.get("status_definitions"), dict):
        unit["status_definitions"] = {sid: normalize_status_def(s, sid) for sid, s in unit["status_definitions"].items()}

    if isinstance(unit.get("actions"), dict):
        unit["actions"] = {aid: normalize_action(a, aid) for aid, a in unit["actions"].items()}

    unit["triggers"] = normalize_triggers(unit.get("triggers", []))
    return unit


def normalize_route_step(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    step = _copy(raw)
    if "action" not in step and "action_id" in step:
        step["action"] = step["action_id"]
    if "targets" in step and isinstance(step["targets"], str):
        step["targets"] = [step["targets"]]
    _normalize_bool_fields(step, ["resolve_initial_queues", "auto_resolve_queues_before", "auto_resolve_queues_after", "resolve_empty_turn"])
    return step


def canonicalize_case(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert supported external/model-pack YAML variants into simulator IR.

    This is intentionally a pure, deterministic preprocessing pass.  The battle
    engine should not need to know whether data came from a hand-written route,
    a Dimbreath-derived model pack, or a video-checkpoint generator.
    """
    case = _copy(raw or {})
    top_flags = normalize_flag_values(case.get("flags", {})) if "flags" in case else {}
    if isinstance(case.get("global"), dict):
        case["global"] = _copy(case["global"])
        global_flags = normalize_flag_values(case["global"].get("flags", {}))
        merged_flags = dict(top_flags)
        merged_flags.update(global_flags)
        case["global"]["flags"] = merged_flags
        _normalize_num_fields(case["global"], ["av", "cycle", "skill_points", "skill_point_cap", "wave_index"])
    else:
        case["global"] = {"flags": top_flags}
    if "flags" in case:
        case["flags"] = top_flags

    if isinstance(case.get("status_effects"), dict):
        case["status_effects"] = {sid: normalize_status_def(s, sid) for sid, s in case["status_effects"].items()}

    if isinstance(case.get("units"), dict):
        case["units"] = {uid: normalize_unit(unit, uid) for uid, unit in case["units"].items()}

    if isinstance(case.get("waves"), list):
        waves = []
        for wave in case["waves"]:
            if not isinstance(wave, dict):
                continue
            nw = _copy(wave)
            if isinstance(nw.get("units"), dict):
                nw["units"] = {uid: normalize_unit(unit, uid) for uid, unit in nw["units"].items()}
            waves.append(nw)
        case["waves"] = waves

    case["triggers"] = normalize_triggers(case.get("triggers", []))
    for key in ("initial_effects", "battle_start_effects", "setup_effects"):
        if key in case:
            case[key] = normalize_effects(case[key])
    if isinstance(case.get("route"), list):
        case["route"] = [s for s in (normalize_route_step(x) for x in case["route"]) if s is not None]
    return case
