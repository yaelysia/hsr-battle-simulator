from __future__ import annotations

from dataclasses import dataclass

from ..core.model import BattleState, Mutation


@dataclass(frozen=True)
class ResourcePlan:
    skill_point_delta: int = 0
    energy_gain: float = 0.0
    source: str = "resource_system"


@dataclass(frozen=True)
class ResourcePlanResult:
    ok: bool
    mutations: tuple[Mutation, ...] = ()
    errors: tuple[str, ...] = ()


class ResourceSystem:
    def set_skill_points(self, state: BattleState, value: int, source: str) -> Mutation:
        clamped = max(0, min(value, state.max_skill_points))
        return Mutation(
            op="set",
            path=("skill_points",),
            before=state.skill_points,
            after=clamped,
            reason="set team skill points",
            source=source,
            mutation_id=f"mutation:skill_points:set:{state.event_index}:{clamped}",
        )

    def change_unit_hp(self, state: BattleState, unit_id: str, delta: float, source: str) -> Mutation:
        unit = state.units[unit_id]
        new_hp = max(0.0, min(unit.max_hp, unit.hp + delta))
        return Mutation(
            op="set",
            path=("units", unit_id, "hp"),
            before=unit.hp,
            after=new_hp,
            reason="change unit hp",
            source=source,
            metadata={"delta": delta},
            mutation_id=f"mutation:{unit_id}:hp:{state.event_index}:{delta}",
        )

    def change_unit_energy(self, state: BattleState, unit_id: str, delta: float, source: str) -> Mutation:
        unit = state.units[unit_id]
        cap = unit.max_energy if unit.max_energy > 0 else unit.energy + delta
        new_energy = max(0.0, min(cap, unit.energy + delta))
        return Mutation(
            op="set",
            path=("units", unit_id, "energy"),
            before=unit.energy,
            after=new_energy,
            reason="change unit energy",
            source=source,
            metadata={"delta": delta},
            mutation_id=f"mutation:{unit_id}:energy:{state.event_index}:{delta}",
        )

    def plan_action_resources(self, state: BattleState, actor_id: str, plan: ResourcePlan) -> ResourcePlanResult:
        errors: list[str] = []
        mutations: list[Mutation] = []

        if actor_id not in state.units:
            return ResourcePlanResult(False, errors=(f"unknown actor_id: {actor_id}",))

        if plan.skill_point_delta < 0 and state.skill_points + plan.skill_point_delta < 0:
            errors.append(
                "insufficient skill points: "
                f"current={state.skill_points}, delta={plan.skill_point_delta}"
            )

        if errors:
            return ResourcePlanResult(False, errors=tuple(errors))

        if plan.skill_point_delta != 0:
            after = max(0, min(state.max_skill_points, state.skill_points + plan.skill_point_delta))
            mutations.append(
                Mutation(
                    op="set",
                    path=("skill_points",),
                    before=state.skill_points,
                    after=after,
                    reason="apply action skill point delta",
                    source=plan.source,
                    metadata={"delta": plan.skill_point_delta},
                    mutation_id=f"mutation:{plan.source}:skill_points:{state.event_index}",
                )
            )

        if plan.energy_gain != 0:
            mutations.append(
                self.change_unit_energy(
                    state,
                    actor_id,
                    plan.energy_gain,
                    plan.source,
                )
            )

        return ResourcePlanResult(True, tuple(mutations), ())
