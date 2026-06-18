from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.model import JSONValue, UnitSide


@dataclass(frozen=True)
class PanelInput:
    explicit_fields: tuple[str, ...] = (
        "max_hp",
        "hp",
        "attack",
        "defense",
        "speed",
        "energy",
        "max_energy",
        "toughness",
        "max_toughness",
        "action_value",
        "resources",
        "flags",
        "statuses",
    )
    max_hp: float = 1.0
    hp: float | None = None
    attack: float = 0.0
    defense: float = 0.0
    speed: float = 100.0
    energy: float = 0.0
    max_energy: float = 0.0
    toughness: float = 0.0
    max_toughness: float = 0.0
    action_value: float = 0.0
    resources: dict[str, float] = field(default_factory=dict)
    flags: dict[str, JSONValue] = field(default_factory=dict)
    statuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnitSpec:
    unit_id: str
    side: UnitSide
    entity_ref: str
    level: int = 80
    position: int | None = None
    panel: PanelInput = field(default_factory=PanelInput)


@dataclass(frozen=True)
class RouteStepSpec:
    actor_id: str
    action_ref: str
    action_level: int
    target_ids: tuple[str, ...]
    source: Literal["manual", "ai", "queue"] = "manual"
    queue_name: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    version: str
    units: tuple[UnitSpec, ...]
    route: tuple[RouteStepSpec, ...]
    skill_points: int = 3
    max_skill_points: int = 5
    wave_index: int = 0
    rng_state: str = "deterministic"
    global_flags: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()
    source_traces: tuple[dict[str, JSONValue], ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "source_traces": list(self.source_traces),
        }
