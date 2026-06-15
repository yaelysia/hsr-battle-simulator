from __future__ import annotations

from dataclasses import dataclass

from .identity import IdentityResolver
from .schema import ScenarioSpec
from ..core.model import ActionCommand, BattleState, UnitState
from ..rules.rulebook import RuleBook


@dataclass(frozen=True)
class ScenarioBuildResult:
    state: BattleState
    commands: tuple[ActionCommand, ...]
    source_traces: tuple[dict[str, object], ...]


class ScenarioStateBuilder:
    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.identity = IdentityResolver(rules)

    def build(self, scenario: ScenarioSpec) -> ScenarioBuildResult:
        validation = self.identity.validate(scenario)
        if not validation.ok:
            raise ValueError("; ".join(validation.errors))

        units = {}
        for unit in scenario.units:
            panel = unit.panel
            flags = dict(panel.flags)
            if unit.position is not None:
                flags["position"] = unit.position
            entity = self.rules.require_entity(unit.entity_ref)
            if entity.entity_type == "monster":
                weaknesses = entity.fields.get("StanceWeakList")
                if isinstance(weaknesses, list):
                    flags["weaknesses"] = tuple(str(item) for item in weaknesses)
            units[unit.unit_id] = UnitState(
                unit_id=unit.unit_id,
                side=unit.side,
                template_id=unit.entity_ref,
                level=unit.level,
                max_hp=panel.max_hp,
                hp=panel.hp if panel.hp is not None else panel.max_hp,
                attack=panel.attack,
                defense=panel.defense,
                speed=panel.speed,
                energy=panel.energy,
                max_energy=panel.max_energy,
                toughness=panel.toughness,
                max_toughness=panel.max_toughness,
                action_value=panel.action_value,
                statuses=panel.statuses,
                flags=flags,
                resources=panel.resources,
            )

        global_flags = dict(scenario.global_flags)
        if scenario.route:
            global_flags.setdefault("turn_owner_id", scenario.route[0].actor_id)
        global_flags.setdefault("phase", "scenario")
        global_flags.setdefault("current_window", "idle")
        state = BattleState(
            units=units,
            wave_index=scenario.wave_index,
            skill_points=scenario.skill_points,
            max_skill_points=scenario.max_skill_points,
            global_flags=global_flags,
            rng_state=scenario.rng_state,
        )
        commands = tuple(
            ActionCommand(
                actor_id=step.actor_id,
                action_id=step.action_ref,
                target_ids=step.target_ids,
                source=step.source,
                queue_name=step.queue_name,
                metadata=step.metadata,
            )
            for step in scenario.route
        )
        return ScenarioBuildResult(state=state, commands=commands, source_traces=validation.source_traces)

