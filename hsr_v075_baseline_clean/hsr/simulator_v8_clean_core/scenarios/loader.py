from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.model import JSONValue
from .schema import (
    BattleSetupSpec,
    InitialStatusSpec,
    InitialSummonSpec,
    ObjectiveSpec,
    PanelInput,
    RNGSetupSpec,
    RouteStepSpec,
    ScenarioSpec,
    SetupResourceSpec,
    TimelineSetupSpec,
    UnitSpec,
    WaveSetupSpec,
)


class ScenarioLoader:
    def load_path(self, path: Path) -> ScenarioSpec:
        data = json.loads(path.read_text(encoding="utf-8"))
        return self.load_dict(data)

    def load_dict(self, data: dict[str, Any]) -> ScenarioSpec:
        if not isinstance(data, dict):
            raise TypeError("scenario root must be an object")
        scenario_id = _required_str(data, "scenario_id")
        version = _required_str(data, "version")
        units_data = _required_list(data, "units")
        route_data = _required_list(data, "route")
        units = tuple(_unit(item, index) for index, item in enumerate(units_data))
        route = tuple(_route_step(item, index) for index, item in enumerate(route_data))
        if not units:
            raise ValueError("scenario.units must not be empty")
        if not route:
            raise ValueError("scenario.route must not be empty")
        battle_setup = _battle_setup(data)
        skill_points = _resolved_skill_points(data, battle_setup)
        max_skill_points = _resolved_max_skill_points(data, battle_setup)
        if skill_points < 0:
            raise ValueError("battle_setup.resources.skill_points must be >= 0")
        if max_skill_points < 0:
            raise ValueError("battle_setup.resources.max_skill_points must be >= 0")
        if skill_points > max_skill_points:
            raise ValueError("battle_setup.resources.skill_points must be <= max_skill_points")
        wave = _resolved_wave_setup(data, battle_setup.wave)
        rng = _resolved_rng_setup(data, battle_setup.rng)
        battle_setup = replace(
            battle_setup,
            resources=SetupResourceSpec(skill_points=skill_points, max_skill_points=max_skill_points),
            wave=wave,
            rng=rng,
        )
        return ScenarioSpec(
            scenario_id=scenario_id,
            version=version,
            units=units,
            route=route,
            skill_points=skill_points,
            max_skill_points=max_skill_points,
            wave_index=wave.wave_index if wave is not None else _optional_int(data, "wave_index", "wave_index", default=0),
            wave_definition_ref=wave.wave_definition_ref if wave is not None else None,
            stage_ref=wave.stage_ref if wave is not None else None,
            rng_state=str(rng.rng_state) if rng is not None and rng.rng_state is not None else "deterministic",
            global_flags=_optional_json_dict(data, "global_flags", "global_flags", default={}),
            battle_setup=battle_setup,
        )


def _unit(data: Any, index: int) -> UnitSpec:
    if not isinstance(data, dict):
        raise TypeError(f"units[{index}] must be an object")
    path = f"units[{index}]"
    panel_data = _optional_json_dict(data, "panel", f"{path}.panel", default={})
    if "hp" in panel_data and "hp_ratio" in panel_data:
        raise ValueError(f"{path}.panel.hp and {path}.panel.hp_ratio cannot both be set")
    if "energy" in panel_data and "energy_ratio" in panel_data:
        raise ValueError(f"{path}.panel.energy and {path}.panel.energy_ratio cannot both be set")
    hp_ratio = _optional_float(panel_data, "hp_ratio", f"{path}.panel.hp_ratio")
    energy_ratio = _optional_float(panel_data, "energy_ratio", f"{path}.panel.energy_ratio")
    _validate_ratio(hp_ratio, f"{path}.panel.hp_ratio")
    _validate_ratio(energy_ratio, f"{path}.panel.energy_ratio")
    side = _required_str(data, "side", f"{path}.side")
    if side not in {"ally", "enemy", "summon"}:
        raise ValueError(f"{path}.side must be one of ['ally', 'enemy', 'summon']")
    level = _optional_int(data, "level", f"{path}.level", default=80)
    if level <= 0:
        raise ValueError(f"{path}.level must be a positive integer")
    eidolon_level = _optional_int(data, "eidolon_level", f"{path}.eidolon_level", default=0)
    if eidolon_level < 0 or eidolon_level > 6:
        raise ValueError(f"{path}.eidolon_level must be between 0 and 6")
    panel = PanelInput(
        explicit_fields=tuple(str(key) for key in panel_data.keys()),
        max_hp=_optional_float(panel_data, "max_hp", f"{path}.panel.max_hp", default=1.0),
        hp=_optional_float(panel_data, "hp", f"{path}.panel.hp"),
        hp_ratio=hp_ratio,
        attack=_optional_float(panel_data, "attack", f"{path}.panel.attack", default=0.0),
        defense=_optional_float(panel_data, "defense", f"{path}.panel.defense", default=0.0),
        speed=_optional_float(panel_data, "speed", f"{path}.panel.speed", default=100.0),
        energy=_optional_float(panel_data, "energy", f"{path}.panel.energy", default=0.0),
        energy_ratio=energy_ratio,
        max_energy=_optional_float(panel_data, "max_energy", f"{path}.panel.max_energy", default=0.0),
        toughness=_optional_float(panel_data, "toughness", f"{path}.panel.toughness", default=0.0),
        max_toughness=_optional_float(panel_data, "max_toughness", f"{path}.panel.max_toughness", default=0.0),
        action_value=_optional_float(panel_data, "action_value", f"{path}.panel.action_value", default=0.0),
        resources=_float_dict(panel_data.get("resources", {}), f"{path}.panel.resources"),
        flags=_optional_json_dict(panel_data, "flags", f"{path}.panel.flags", default={}),
        statuses=tuple(_str_list(panel_data.get("statuses", ()), f"{path}.panel.statuses")),
    )
    return UnitSpec(
        unit_id=_required_str(data, "unit_id", f"{path}.unit_id"),
        side=side,  # type: ignore[arg-type]
        entity_ref=_required_str(data, "entity_ref", f"{path}.entity_ref"),
        level=level,
        eidolon_level=eidolon_level,
        position=_optional_int(data, "position", f"{path}.position") if "position" in data else None,
        panel=panel,
    )


def _route_step(data: Any, index: int) -> RouteStepSpec:
    if not isinstance(data, dict):
        raise TypeError(f"route[{index}] must be an object")
    path = f"route[{index}]"
    return RouteStepSpec(
        actor_id=_required_str(data, "actor_id", f"{path}.actor_id"),
        action_ref=_required_str(data, "action_ref", f"{path}.action_ref"),
        action_level=_required_int(data, "action_level", f"{path}.action_level"),
        target_ids=tuple(_str_list(_required_list(data, "target_ids", f"{path}.target_ids"), f"{path}.target_ids")),
        source=_optional_str(data, "source", f"{path}.source", default="manual"),
        queue_name=_optional_str(data, "queue_name", f"{path}.queue_name"),
        metadata=_optional_json_dict(data, "metadata", f"{path}.metadata", default={}),
    )


def _battle_setup(data: dict[str, Any]) -> BattleSetupSpec:
    if "battle_setup" in data and "setup" in data:
        raise ValueError("battle_setup and setup cannot both be set")
    raw = data.get("battle_setup", data.get("setup", {}))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("battle_setup must be an object")
    resources = _setup_resources(_optional_json_dict(raw, "resources", "battle_setup.resources", default={}))
    wave = _wave_setup(raw.get("wave"), "battle_setup.wave") if raw.get("wave") is not None else None
    timeline = (
        _timeline_setup(raw.get("timeline"), "battle_setup.timeline")
        if raw.get("timeline") is not None
        else None
    )
    rng = _rng_setup(raw.get("rng"), "battle_setup.rng") if raw.get("rng") is not None else None
    initial_statuses = tuple(
        _initial_status(item, index) for index, item in enumerate(_optional_list(raw, "initial_statuses", "battle_setup.initial_statuses", default=[]))
    )
    initial_summons = tuple(
        _initial_summon(item, index) for index, item in enumerate(_optional_list(raw, "initial_summons", "battle_setup.initial_summons", default=[]))
    )
    objective = _objective(raw.get("objective"), "battle_setup.objective") if raw.get("objective") is not None else None
    metadata = _optional_json_dict(raw, "metadata", "battle_setup.metadata", default={})
    return BattleSetupSpec(
        resources=resources,
        wave=wave,
        timeline=timeline,
        rng=rng,
        initial_statuses=initial_statuses,
        initial_summons=initial_summons,
        objective=objective,
        metadata=metadata,
    )


def _setup_resources(data: dict[str, Any]) -> SetupResourceSpec:
    return SetupResourceSpec(
        skill_points=_optional_int(data, "skill_points", "battle_setup.resources.skill_points"),
        max_skill_points=_optional_int(data, "max_skill_points", "battle_setup.resources.max_skill_points"),
    )


def _wave_setup(raw: Any, path: str) -> WaveSetupSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    kind = _optional_str(raw, "kind", f"{path}.kind", default="none")
    if kind == "tbgd_stage":
        kind = "stage"
    if kind not in {"none", "stage", "wave_definition"}:
        raise ValueError(f"{path}.kind must be one of ['none', 'stage', 'wave_definition']")
    stage_ref = _optional_str(raw, "stage_ref", f"{path}.stage_ref")
    wave_definition_ref = _optional_str(raw, "wave_definition_ref", f"{path}.wave_definition_ref")
    if raw.get("stage_id") is not None:
        stage_ref = _optional_str(raw, "stage_id", f"{path}.stage_id")
    if raw.get("wave_definition_id") is not None:
        wave_definition_ref = _optional_str(raw, "wave_definition_id", f"{path}.wave_definition_id")
    wave_index = _optional_int(raw, "wave_index", f"{path}.wave_index", default=0)
    if wave_index < 0:
        raise ValueError(f"{path}.wave_index must be >= 0")
    if kind == "stage" and not stage_ref:
        raise ValueError(f"{path}.stage_ref must be set when kind is 'stage'")
    if kind == "wave_definition" and not wave_definition_ref:
        raise ValueError(f"{path}.wave_definition_ref must be set when kind is 'wave_definition'")
    if kind == "none" and (stage_ref or wave_definition_ref):
        raise ValueError(f"{path}.kind must be 'stage' or 'wave_definition' when a wave reference is set")
    return WaveSetupSpec(
        kind=kind,  # type: ignore[arg-type]
        stage_ref=stage_ref,
        wave_definition_ref=wave_definition_ref,
        wave_index=wave_index,
    )


def _timeline_setup(raw: Any, path: str) -> TimelineSetupSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    mode = _optional_str(raw, "mode", f"{path}.mode", default="runtime_initialize")
    if mode not in {"runtime_initialize", "explicit_action_values"}:
        raise ValueError(f"{path}.mode must be one of ['runtime_initialize', 'explicit_action_values']")
    action_values = _float_dict(raw.get("action_values", {}), f"{path}.action_values")
    for unit_id, value in action_values.items():
        if value < 0:
            raise ValueError(f"{path}.action_values[{unit_id!r}] must be >= 0")
    return TimelineSetupSpec(
        mode=mode,  # type: ignore[arg-type]
        global_av=_optional_float(raw, "global_av", f"{path}.global_av", default=0.0),
        turn_owner_id=_optional_str(raw, "turn_owner_id", f"{path}.turn_owner_id"),
        action_values=action_values,
        explicit_overrides=tuple(_str_list(raw.get("explicit_overrides", ()), f"{path}.explicit_overrides")),
    )


def _rng_setup(raw: Any, path: str) -> RNGSetupSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    return RNGSetupSpec(
        rng_state=_optional_str(raw, "rng_state", f"{path}.rng_state"),
        rng_mode=_optional_str(raw, "rng_mode", f"{path}.rng_mode"),
        rng_choices=_optional_json_dict(raw, "rng_choices", f"{path}.rng_choices", default={}),
    )


def _initial_status(raw: Any, index: int) -> InitialStatusSpec:
    path = f"battle_setup.initial_statuses[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    return InitialStatusSpec(
        target_id=_required_str(raw, "target_id", f"{path}.target_id"),
        source_id=_required_str(raw, "source_id", f"{path}.source_id"),
        effect_ref=_optional_str(raw, "effect_ref", f"{path}.effect_ref"),
        owner_id=_optional_str(raw, "owner_id", f"{path}.owner_id"),
        caster_id=_optional_str(raw, "caster_id", f"{path}.caster_id"),
        param_entity_id=_optional_str(raw, "param_entity_id", f"{path}.param_entity_id"),
        current_action_target_id=_optional_str(raw, "current_action_target_id", f"{path}.current_action_target_id"),
        dynamic_values=_float_dict(raw.get("dynamic_values", {}), f"{path}.dynamic_values"),
        rng_choices=_optional_json_dict(raw, "rng_choices", f"{path}.rng_choices", default={}),
        rng_mode=_optional_str(raw, "rng_mode", f"{path}.rng_mode"),
        metadata=_optional_json_dict(raw, "metadata", f"{path}.metadata", default={}),
    )


def _initial_summon(raw: Any, index: int) -> InitialSummonSpec:
    path = f"battle_setup.initial_summons[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    kind = _optional_str(raw, "kind", f"{path}.kind", default="summoned_monster")
    if kind not in {"summoned_monster", "battle_unit_summon", "servant"}:
        raise ValueError(f"{path}.kind must be one of ['summoned_monster', 'battle_unit_summon', 'servant']")
    return InitialSummonSpec(
        kind=kind,  # type: ignore[arg-type]
        owner_id=_required_str(raw, "owner_id", f"{path}.owner_id"),
        summon_intent_ref=_optional_str(raw, "summon_intent_ref", f"{path}.summon_intent_ref"),
        unit_id=_optional_str(raw, "unit_id", f"{path}.unit_id"),
        entity_ref=_optional_str(raw, "entity_ref", f"{path}.entity_ref"),
        position=_optional_int(raw, "position", f"{path}.position") if "position" in raw else None,
        metadata=_optional_json_dict(raw, "metadata", f"{path}.metadata", default={}),
    )


def _objective(raw: Any, path: str) -> ObjectiveSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    return ObjectiveSpec(
        objective_id=_required_str(raw, "objective_id", f"{path}.objective_id"),
        kind=_required_str(raw, "kind", f"{path}.kind"),
        payload=_optional_json_dict(raw, "payload", f"{path}.payload", default={}),
    )


def _resolved_skill_points(data: dict[str, Any], setup: BattleSetupSpec) -> int:
    return _resolve_optional_int_alias(
        _optional_int(data, "skill_points", "skill_points") if "skill_points" in data else None,
        setup.resources.skill_points,
        "skill_points",
        "battle_setup.resources.skill_points",
        default=3,
    )


def _resolved_max_skill_points(data: dict[str, Any], setup: BattleSetupSpec) -> int:
    return _resolve_optional_int_alias(
        _optional_int(data, "max_skill_points", "max_skill_points") if "max_skill_points" in data else None,
        setup.resources.max_skill_points,
        "max_skill_points",
        "battle_setup.resources.max_skill_points",
        default=5,
    )


def _resolved_wave_setup(data: dict[str, Any], setup_wave: WaveSetupSpec | None) -> WaveSetupSpec | None:
    root_stage = _optional_str(data, "stage_ref", "stage_ref") if "stage_ref" in data else None
    root_definition = (
        _optional_str(data, "wave_definition_ref", "wave_definition_ref") if "wave_definition_ref" in data else None
    )
    if root_stage and root_definition:
        raise ValueError("stage_ref and wave_definition_ref cannot both be set")
    root_wave_index = _optional_int(data, "wave_index", "wave_index") if "wave_index" in data else None
    legacy_wave = _wave_setup(data["wave_setup"], "wave_setup") if data.get("wave_setup") is not None else None
    wave = setup_wave or legacy_wave
    if wave is None:
        if root_stage:
            return WaveSetupSpec(kind="stage", stage_ref=root_stage, wave_index=root_wave_index or 0)
        if root_definition:
            return WaveSetupSpec(
                kind="wave_definition",
                wave_definition_ref=root_definition,
                wave_index=root_wave_index or 0,
            )
        return WaveSetupSpec(kind="none", wave_index=root_wave_index or 0)
    if legacy_wave is not None and setup_wave is not None and legacy_wave != setup_wave:
        raise ValueError("wave_setup and battle_setup.wave cannot describe different waves")
    if root_wave_index is not None and root_wave_index != wave.wave_index:
        raise ValueError("wave_index and battle_setup.wave.wave_index cannot differ")
    if root_stage and (wave.kind != "stage" or wave.stage_ref != root_stage):
        raise ValueError("stage_ref and battle_setup.wave cannot differ")
    if root_definition and (wave.kind != "wave_definition" or wave.wave_definition_ref != root_definition):
        raise ValueError("wave_definition_ref and battle_setup.wave cannot differ")
    return wave


def _resolved_rng_setup(data: dict[str, Any], setup_rng: RNGSetupSpec | None) -> RNGSetupSpec:
    root_rng_state = _optional_str(data, "rng_state", "rng_state") if "rng_state" in data else None
    if setup_rng is None:
        return RNGSetupSpec(rng_state=root_rng_state or "deterministic")
    if setup_rng.rng_state is None:
        return replace(setup_rng, rng_state=root_rng_state or "deterministic")
    if root_rng_state is not None and root_rng_state != setup_rng.rng_state:
        raise ValueError("rng_state and battle_setup.rng.rng_state cannot differ")
    return setup_rng


def _resolve_optional_int_alias(
    root_value: int | None,
    setup_value: int | None,
    root_path: str,
    setup_path: str,
    *,
    default: int,
) -> int:
    if root_value is not None and setup_value is not None and root_value != setup_value:
        raise ValueError(f"{root_path} and {setup_path} cannot differ")
    if setup_value is not None:
        return setup_value
    if root_value is not None:
        return root_value
    return default


def _required_str(data: dict[str, Any], key: str, path: str | None = None) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path or key} must be a non-empty string")
    return value


def _optional_str(data: dict[str, Any], key: str, path: str, *, default: str | None = None) -> str | None:
    value = data.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _required_list(data: dict[str, Any], key: str, path: str | None = None) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{path or key} must be a list")
    return value


def _optional_list(data: dict[str, Any], key: str, path: str, *, default: list[Any]) -> list[Any]:
    value = data.get(key, default)
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _required_int(data: dict[str, Any], key: str, path: str | None = None) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path or key} must be an integer")
    return value


def _optional_int(data: dict[str, Any], key: str, path: str, *, default: int | None = None) -> int | None:
    value = data.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    return value


def _optional_float(data: dict[str, Any], key: str, path: str, *, default: float | None = None) -> float | None:
    value = data.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a number")
    return float(value)


def _validate_ratio(value: float | None, path: str) -> None:
    if value is None:
        return
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{path} must be between 0 and 1")


def _float_dict(raw: Any, path: str) -> dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    result: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path}.{key} must be a number")
        result[str(key)] = float(value)
    return result


def _optional_json_dict(
    data: dict[str, Any],
    key: str,
    path: str,
    *,
    default: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    value = data.get(key, default)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return dict(value)


def _str_list(raw: Any, path: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{path} must be a list")
    result: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item:
            raise ValueError(f"{path}[{index}] must be a non-empty string")
        result.append(item)
    return result
