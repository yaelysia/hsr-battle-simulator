from __future__ import annotations

"""Generate executable exact-route harness skeletons for enemy templates.

This turns the enemy mechanism inventory into runnable simulator cases.  The
cases are intentionally small: one dummy ally, one enemy, zero or one enemy
first action, and route expectations checking HP/toughness/phase/summon hints.
They are not real battle replays, but they give exact-route validation files a
concrete starting point instead of a plain checklist.
"""

from pathlib import Path
from typing import Any
import json

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to generate enemy route harnesses")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _enemy_files(model_pack_dir: str | Path) -> list[Path]:
    root = Path(model_pack_dir)
    return sorted((root / "models" / "enemies").glob("*.yaml"))


def _first_enemy_action(unit_template: dict[str, Any]) -> dict[str, Any] | None:
    skills = unit_template.get("skills") or []
    for sk in skills:
        if not isinstance(sk, dict):
            continue
        dmg_type = sk.get("damage_type")
        params = sk.get("params") or []
        if dmg_type and params:
            mult = 0.0
            try:
                mult = float(params[0])
            except Exception:
                mult = 0.0
            return {
                "id": str(sk.get("trigger_key") or sk.get("skill_id") or "enemy_skill"),
                "action_type": "enemy_skill",
                "tags": ["enemy_action", "generated_harness", "consumes_regular_action"],
                "target_policy": "first_ally",
                "damage_packets": [{
                    "id": str(sk.get("skill_id") or "enemy_packet"),
                    "element": str(dmg_type).lower(),
                    "scaling_stat": "atk",
                    "multiplier": mult,
                    "can_crit": False,
                }],
                "metadata": {
                    "source_skill_id": sk.get("skill_id"),
                    "source_skill_name_cn": sk.get("name_chs"),
                    "summary_cn": sk.get("description_chs"),
                },
            }
    return None




def _enemy_actions(unit_template: dict[str, Any]) -> dict[str, Any]:
    actions: dict[str, Any] = {}
    for sk in unit_template.get("skills") or []:
        if not isinstance(sk, dict):
            continue
        action_id = str(sk.get("trigger_key") or sk.get("skill_id") or f"skill_{len(actions)+1}")
        dmg_type = sk.get("damage_type")
        params = sk.get("params") or []
        packets = []
        if dmg_type and params:
            try:
                mult = float(params[0])
            except Exception:
                mult = 0.0
            packets.append({
                "id": str(sk.get("skill_id") or action_id),
                "element": str(dmg_type).lower(),
                "scaling_stat": "atk",
                "multiplier": mult,
                "can_crit": False,
            })
        actions[action_id] = {
            "id": action_id,
            "action_type": "enemy_skill",
            "tags": ["enemy_action", "generated_harness", "consumes_regular_action"],
            "target_policy": "first_ally" if packets else "self",
            "damage_packets": packets,
            "metadata": {
                "source_skill_id": sk.get("skill_id"),
                "source_skill_name_cn": sk.get("name_chs"),
                "summary_cn": sk.get("description_chs"),
            },
        }
    return actions

def _ally_probe_actions(enemy_id: str) -> dict[str, Any]:
    return {
        "physical_probe": {
            "id": "physical_probe", "action_type": "test_attack", "tags": ["attack", "generated_harness_probe"], "target_policy": "manual",
            "damage_packets": [{"id": "physical_probe_packet", "element": "physical", "scaling_stat": "atk", "multiplier": 1.0, "toughness_reduction": 30, "can_crit": False}],
        },
        "fire_probe": {
            "id": "fire_probe", "action_type": "test_attack", "tags": ["attack", "generated_harness_probe", "fire"], "target_policy": "manual",
            "damage_packets": [{"id": "fire_probe_packet", "element": "fire", "scaling_stat": "atk", "multiplier": 1.0, "toughness_reduction": 30, "can_crit": False}],
        },
        "break_probe": {
            "id": "break_probe", "action_type": "test_attack", "tags": ["attack", "generated_harness_probe", "break_test"], "target_policy": "manual",
            "damage_packets": [{"id": "break_probe_packet", "element": "quantum", "scaling_stat": "atk", "multiplier": 0.1, "toughness_reduction": 9999, "can_crit": False}],
        },
    }


def _enemy_core_statuses(unit: dict[str, Any]) -> list[dict[str, Any]]:
    mechanics = unit.get("core_mechanics") or {}
    statuses: list[dict[str, Any]] = []
    if "daybreak_force_field" in mechanics:
        cfg = mechanics.get("daybreak_force_field") or {}
        statuses.append({
            "id": "daybreak_force_field",
            "tags": ["enemy_core_mechanic", "force_field", "daybreak_force_field"],
            "modifiers": {
                "control_immunity": True,
                "toughness_lock": True,
                "immediate_action_on_hit_by_element": {"element": "fire", "action": "Skill04", "target_policy": "first_ally"},
                "count_attacks_taken": {"threshold": int((cfg.get("source_param_list") or [7])[0] or 7), "action": "Skill05", "target_policy": "self"},
            },
        })
    if "armor_polis_protector" in mechanics:
        cfg = mechanics.get("armor_polis_protector") or {}
        statuses.append({
            "id": "armor_polis_protector",
            "tags": ["enemy_core_mechanic", "armor_layers"],
            "stacks": int(cfg.get("layers", 6) or 6),
            "max_stacks": int(cfg.get("layers", 6) or 6),
            "modifiers": {
                "armor_layers": {
                    "layers": int(cfg.get("layers", 6) or 6),
                    "damage_reduction_per_layer": float(cfg.get("damage_reduction_per_layer", 0.2) or 0.2),
                    "on_hit_lose_layers": int(cfg.get("on_hit_lose_layers", 1) or 1),
                    "on_break_self_imaginary_damage_max_hp_ratio": float(cfg.get("on_break_self_imaginary_damage_max_hp_ratio", 0.0) or 0.0),
                    "on_break_action_delay_ratio": float(cfg.get("on_break_action_delay_ratio", 0.0) or 0.0),
                    "on_break_energy_restore_max_energy_ratio_to_breaker": float(cfg.get("on_break_energy_restore_max_energy_ratio_to_breaker", 0.0) or 0.0),
                }
            },
        })
    if "phase_transition" in mechanics:
        statuses.append({
            "id": "phase_transition_immediate_action",
            "tags": ["enemy_core_mechanic", "phase_transition"],
            "modifiers": {"phase_transition_immediate_action": True},
        })
    return statuses


def _apply_enemy_core_flags(enemy: dict[str, Any], mechanics: dict[str, Any]) -> None:
    flags = enemy.setdefault("flags", {})
    if "phase_transition" in mechanics:
        flags.setdefault("phase_transition_immediate_action", True)
        # Lance has semantic phase HP: first bar depletion queues immediate action.
        enemy.setdefault("hp_bars_total", 2)
        enemy.setdefault("hp_bars_remaining", 2)
        enemy.setdefault("hp_model", {"type": "phase_hp", "carry_over_damage": False, "bars": [{"hp": enemy.get("max_hp", enemy.get("hp", 1))}, {"hp": enemy.get("max_hp", enemy.get("hp", 1))}]})
    if "summon_conquer_or_be_conquered" in mechanics:
        flags.setdefault("can_summon_corresponding_conquer_or_be_conquered", True)
    if "shared_hp_with_savage_god" in mechanics:
        flags.setdefault("shared_hp_with_savage_god", True)


def _enemy_mechanic_setup_steps(enemy_id: str, unit: dict[str, Any]) -> list[dict[str, Any]]:
    mechanics = unit.get("core_mechanics") or {}
    steps: list[dict[str, Any]] = []
    if "summon_conquer_or_be_conquered" in mechanics:
        cfg = mechanics.get("summon_conquer_or_be_conquered") or {}
        steps.append({
            "type": "apply_effects",
            "effects": [{"type": "spawn_corresponding_summons", "unit_id": "conquer_or_be_conquered", "count": cfg.get("count", 1) if isinstance(cfg.get("count"), int) else 1, "per_ally": False, "hp": 1000, "max_hp": 1000, "speed": 100}],
            "expect": {"event_counts": {"summon": {"min": 1}}},
        })
    return steps


def _enemy_mechanic_probe_steps(enemy_id: str, unit: dict[str, Any]) -> list[dict[str, Any]]:
    mechanics = unit.get("core_mechanics") or {}
    steps: list[dict[str, Any]] = []
    if "daybreak_force_field" in mechanics:
        steps.append({
            "actor": "dummy_ally", "action": "fire_probe", "targets": [enemy_id], "auto_resolve_queues_after": True,
            "expect": {"event_counts": {"enemy_mechanic": {"min": 1}}, "units": {enemy_id: {"toughness": {"gte": 0}}}},
        })
    if "armor_polis_protector" in mechanics:
        steps.append({
            "actor": "dummy_ally", "action": "physical_probe", "targets": [enemy_id],
            "expect": {"event_counts": {"enemy_mechanic": {"min": 1}}, "units": {enemy_id: {"hp": {"lt": unit.get("hp", unit.get("max_hp", 1))}}}},
        })
    if "phase_transition" in mechanics:
        steps.append({
            "type": "apply_effects",
            "effects": [{"type": "damage_unit", "target": enemy_id, "amount": unit.get("max_hp", unit.get("hp", 1)) * 2, "ignore_shield": True}],
            "expect": {"event_counts": {"hp_bar": {"min": 1}, "enemy_mechanic": {"min": 1}}},
        })
    return steps

def enemy_exact_route_case(enemy_template_file: str | Path) -> dict[str, Any]:
    raw = _load_yaml(Path(enemy_template_file))
    unit = (raw.get("unit") or {}) if isinstance(raw.get("unit"), dict) else raw
    enemy_id = str(unit.get("id") or raw.get("id") or Path(enemy_template_file).stem)
    enemy = {
        "side": "enemy",
        "name": unit.get("cn_name") or unit.get("name") or enemy_id,
        "hp": unit.get("hp", unit.get("max_hp", 1000)),
        "max_hp": unit.get("max_hp", unit.get("hp", 1000)),
        "speed": unit.get("speed", 100),
        "level": unit.get("level", 80),
        "toughness": unit.get("toughness", 0),
        "max_toughness": unit.get("max_toughness", unit.get("toughness", 0)),
        "stats": unit.get("stats", {"atk": 1000, "def": 1000}),
        "res": unit.get("res", {}),
        "weaknesses": unit.get("weaknesses", []),
        "flags": {
            "enemy_template_id": unit.get("template_id"),
            "mechanism_harness": True,
        },
        "actions": {},
    }
    mechanics = unit.get("core_mechanics") or {}
    _apply_enemy_core_flags(enemy, mechanics)
    core_statuses = _enemy_core_statuses(unit)
    if core_statuses:
        enemy.setdefault("statuses", []).extend(core_statuses)
    first_action = _first_enemy_action(unit)
    route: list[dict[str, Any]] = []
    route.extend(_enemy_mechanic_setup_steps(enemy_id, unit))
    route.extend(_enemy_mechanic_probe_steps(enemy_id, unit))
    enemy["actions"].update(_enemy_actions(unit))
    if first_action:
        route.append({
            "actor": enemy_id,
            "action": first_action["id"],
            "targets": ["dummy_ally"],
            "expect": {
                "event_counts": {"damage": {"min": 1}},
                "units": {"dummy_ally": {"hp": {"lt": 100000}}},
            },
        })
    else:
        enemy["actions"]["noop"] = {"id": "noop", "action_type": "enemy_skill", "tags": ["consumes_regular_action", "generated_harness"], "target_policy": "self", "damage_packets": []}
        route.append({"actor": enemy_id, "action": "noop", "targets": [], "expect": {"event_counts": {"damage": 0}}})

    mechanics = unit.get("core_mechanics") or {}
    notes = []
    if mechanics:
        notes.append("该敌人存在 core_mechanics，生成的 harness 只做第一行动 smoke；特殊机制需要在真实路线里逐条补 expect。")
    return {
        "metadata": {
            "format": "hsr_enemy_exact_route_harness_case",
            "version": "v0.2",
            "source_enemy_file": str(enemy_template_file),
            "enemy_id": enemy_id,
            "enemy_cn_name": enemy.get("name"),
            "core_mechanic_keys": sorted(str(k) for k in mechanics.keys()),
            "notes_cn": notes,
        },
        "global": {"flags": {}, "skill_points": 3},
        "units": {
            "dummy_ally": {"side": "ally", "hp": 100000, "max_hp": 100000, "speed": 100, "level": 80, "energy": 0, "max_energy": 100, "stat_base": {"atk": 1000}, "stats": {"def": 0}, "weaknesses": [], "actions": _ally_probe_actions(enemy_id), "tags": ["not_on_timeline", "harness_dummy_target"]},
            enemy_id: enemy,
        },
        "route": route,
    }


def write_enemy_route_harness(model_pack_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    cases_dir = out / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for f in _enemy_files(model_pack_dir):
        case = enemy_exact_route_case(f)
        name = f"{case['metadata']['enemy_id']}.enemy_harness.yaml"
        path = cases_dir / name
        if yaml is None:
            path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(case, allow_unicode=True, sort_keys=False), encoding="utf-8")
        cases.append({
            "enemy_id": case["metadata"]["enemy_id"],
            "enemy_cn_name": case["metadata"].get("enemy_cn_name"),
            "case_file": str(path),
            "core_mechanic_keys": case["metadata"].get("core_mechanic_keys", []),
            "route_step_count": len(case.get("route") or []),
        })
    summary = {
        "format": "hsr_enemy_exact_route_harness_bundle",
        "version": "v0.2",
        "case_count": len(cases),
        "cases": cases,
        "summary_cn": "为现有敌人模板生成带 core_mechanics 骨架的可执行 exact-route harness。仍不是完整敌人复刻，但已把力场、护甲层、阶段转化、召唤等核心机制转成可跑断言入口。",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "enemy_route_harness_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 敌人 exact-route 骨架", "", summary["summary_cn"], ""]
    for c in cases:
        lines.append(f"- {c['enemy_cn_name']} / `{c['enemy_id']}`：`{Path(c['case_file']).name}`，机制键：{', '.join(c['core_mechanic_keys']) or '无'}")
    (out / "enemy_route_harness_cn.md").write_text("\n".join(lines), encoding="utf-8")
    return summary
