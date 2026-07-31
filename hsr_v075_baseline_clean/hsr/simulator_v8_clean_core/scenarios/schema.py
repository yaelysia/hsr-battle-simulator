from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..builds.models import CharacterBuildInput, CharacterInitialConditionInput
from ..core.model import JSONValue, UnitSide


@dataclass(frozen=True)
class PanelInput:
    explicit_fields: tuple[str, ...] = (
        "max_hp",
        "hp",
        "hp_ratio",
        "attack",
        "defense",
        "speed",
        "energy",
        "energy_ratio",
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
    hp_ratio: float | None = None
    attack: float = 0.0
    defense: float = 0.0
    speed: float = 100.0
    energy: float = 0.0
    energy_ratio: float | None = None
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
    build_mode: Literal["kernel_fixture", "assembled_character_build"]
    level: int = 80
    eidolon_level: int = 0
    position: int | None = None
    panel: PanelInput | None = field(default_factory=PanelInput)
    character_build: CharacterBuildInput | None = None
    initial_condition: CharacterInitialConditionInput | None = None


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
class SetupResourceSpec:
    skill_points: int | None = None
    max_skill_points: int | None = None


@dataclass(frozen=True)
class WaveSetupSpec:
    kind: Literal["none", "stage", "wave_definition"] = "none"
    stage_ref: str | None = None
    wave_definition_ref: str | None = None
    wave_index: int = 0


@dataclass(frozen=True)
class InitialStatusSpec:
    target_id: str
    source_id: str
    effect_ref: str | None = None
    owner_id: str | None = None
    caster_id: str | None = None
    param_entity_id: str | None = None
    current_action_target_id: str | None = None
    dynamic_values: dict[str, float] = field(default_factory=dict)
    rng_choices: dict[str, JSONValue] = field(default_factory=dict)
    rng_mode: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class InitialSummonSpec:
    kind: Literal["summoned_monster", "battle_unit_summon", "servant"] = "summoned_monster"
    owner_id: str = ""
    summon_intent_ref: str | None = None
    servant_spawn_source_id: str | None = None
    unit_id: str | None = None
    entity_ref: str | None = None
    position: int | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class TimelineSetupSpec:
    mode: Literal["runtime_initialize", "explicit_action_values"] = "runtime_initialize"
    global_av: float = 0.0
    turn_owner_id: str | None = None
    action_values: dict[str, float] = field(default_factory=dict)
    explicit_overrides: tuple[str, ...] = ()


@dataclass(frozen=True)
class RNGSetupSpec:
    rng_state: str | None = "deterministic"
    rng_mode: str | None = None
    rng_choices: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectiveSpec:
    objective_id: str
    kind: str
    payload: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class BattleSetupSpec:
    world_level: int | None = None
    resources: SetupResourceSpec = field(default_factory=SetupResourceSpec)
    wave: WaveSetupSpec | None = None
    timeline: TimelineSetupSpec | None = None
    rng: RNGSetupSpec | None = None
    initial_statuses: tuple[InitialStatusSpec, ...] = ()
    initial_summons: tuple[InitialSummonSpec, ...] = ()
    objective: ObjectiveSpec | None = None
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
    wave_definition_ref: str | None = None
    stage_ref: str | None = None
    rng_state: str = "deterministic"
    global_flags: dict[str, JSONValue] = field(default_factory=dict)
    battle_setup: BattleSetupSpec = field(default_factory=BattleSetupSpec)


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
