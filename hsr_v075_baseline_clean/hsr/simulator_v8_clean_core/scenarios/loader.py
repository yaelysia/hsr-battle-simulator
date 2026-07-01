from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import PanelInput, RouteStepSpec, ScenarioSpec, UnitSpec


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
        wave_definition_ref = data.get("wave_definition_ref")
        stage_ref = data.get("stage_ref")
        wave_setup = data.get("wave_setup")
        if isinstance(wave_setup, dict):
            if wave_setup.get("kind") == "tbgd_stage" and wave_setup.get("stage_id") is not None:
                stage_ref = wave_setup.get("stage_id")
            if wave_setup.get("kind") == "wave_definition" and wave_setup.get("wave_definition_id") is not None:
                wave_definition_ref = wave_setup.get("wave_definition_id")
        return ScenarioSpec(
            scenario_id=scenario_id,
            version=version,
            units=units,
            route=route,
            skill_points=int(data.get("skill_points", 3)),
            max_skill_points=int(data.get("max_skill_points", 5)),
            wave_index=int(data.get("wave_index", 0)),
            wave_definition_ref=str(wave_definition_ref) if wave_definition_ref is not None else None,
            stage_ref=str(stage_ref) if stage_ref is not None else None,
            rng_state=str(data.get("rng_state", "deterministic")),
            global_flags=dict(data.get("global_flags", {})),
        )


def _unit(data: Any, index: int) -> UnitSpec:
    if not isinstance(data, dict):
        raise TypeError(f"units[{index}] must be an object")
    panel_data = dict(data.get("panel", {}))
    panel = PanelInput(
        explicit_fields=tuple(str(key) for key in panel_data.keys()),
        max_hp=float(panel_data.get("max_hp", 1.0)),
        hp=float(panel_data["hp"]) if "hp" in panel_data else None,
        attack=float(panel_data.get("attack", 0.0)),
        defense=float(panel_data.get("defense", 0.0)),
        speed=float(panel_data.get("speed", 100.0)),
        energy=float(panel_data.get("energy", 0.0)),
        max_energy=float(panel_data.get("max_energy", 0.0)),
        toughness=float(panel_data.get("toughness", 0.0)),
        max_toughness=float(panel_data.get("max_toughness", 0.0)),
        action_value=float(panel_data.get("action_value", 0.0)),
        resources={str(key): float(value) for key, value in dict(panel_data.get("resources", {})).items()},
        flags=dict(panel_data.get("flags", {})),
        statuses=tuple(str(item) for item in panel_data.get("statuses", ())),
    )
    return UnitSpec(
        unit_id=_required_str(data, "unit_id"),
        side=_required_str(data, "side"),
        entity_ref=_required_str(data, "entity_ref"),
        level=int(data.get("level", 80)),
        eidolon_level=int(data.get("eidolon_level", 0)),
        position=int(data["position"]) if "position" in data else None,
        panel=panel,
    )


def _route_step(data: Any, index: int) -> RouteStepSpec:
    if not isinstance(data, dict):
        raise TypeError(f"route[{index}] must be an object")
    return RouteStepSpec(
        actor_id=_required_str(data, "actor_id"),
        action_ref=_required_str(data, "action_ref"),
        action_level=_required_int(data, "action_level"),
        target_ids=tuple(str(item) for item in _required_list(data, "target_ids")),
        source=str(data.get("source", "manual")),
        queue_name=str(data["queue_name"]) if data.get("queue_name") is not None else None,
        metadata=dict(data.get("metadata", {})),
    )


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _required_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value
