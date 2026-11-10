from __future__ import annotations

from dataclasses import dataclass, field, replace
import math

from ..core.model import BattleState, JSONValue, Mutation, UnitState, current_max_hp
from ..rules.ir import ResourceRuleIR
from .unit_stats import effective_unit_stat


@dataclass(frozen=True)
class ResourcePlan:
    skill_point_delta: int = 0
    energy_gain: float = 0.0
    source: str = "resource_system"
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    energy_cost: float | None = 0.0
    blocked_reason: str = ""


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
        new_hp = max(0.0, min(current_max_hp(unit), unit.hp + delta))
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
        effective_delta, regeneration = _effective_energy_delta(unit, delta)
        cap = (
            unit.max_energy
            if unit.max_energy > 0
            else unit.energy + effective_delta
        )
        new_energy = float(max(0.0, min(cap, unit.energy + effective_delta)))
        return Mutation(
            op="set",
            path=("units", unit_id, "energy"),
            before=unit.energy,
            after=new_energy,
            reason="change unit energy",
            source=source,
            metadata={
                "delta": effective_delta,
                "raw_delta": delta,
                "energy_regeneration_rate": (
                    regeneration.to_json() if regeneration is not None else None
                ),
            },
            mutation_id=f"mutation:{unit_id}:energy:{state.event_index}:{delta}",
        )

    def gain_kill_energy(
        self,
        state: BattleState,
        unit_id: str,
        rule: ResourceRuleIR,
        *,
        defeated_event_payload: dict[str, JSONValue],
        metadata: dict[str, JSONValue] | None = None,
        source: str = "combat_executor.resources",
    ) -> Mutation:
        unit = state.units[unit_id]
        if not isinstance(rule.numeric_value, (int, float)) or isinstance(rule.numeric_value, bool):
            raise ValueError("kill energy engine rule numeric value is missing")
        raw_gain = float(rule.numeric_value)
        gain, regeneration = _effective_energy_delta(unit, raw_gain)
        cap = unit.max_energy if unit.max_energy > 0 else unit.energy + gain
        after = float(max(0.0, min(cap, unit.energy + gain)))
        damage_event_id = str(defeated_event_payload.get("damage_event_id") or defeated_event_payload.get("damage_packet_id") or "")
        return Mutation(
            op="set",
            path=("units", unit_id, "energy"),
            before=unit.energy,
            after=after,
            reason="apply common caused-kill energy gain",
            source=source,
            metadata={
                **(metadata or {}),
                "resource_operation": "kill_energy_gain",
                "resource_rule_id": rule.resource_rule_id,
                "resource_rule_kind": rule.rule_kind,
                "resource_rule_operation": rule.operation,
                "resource_rule_source_kind": rule.source_kind,
                "resource_rule_source": rule.source.to_json(),
                "before_energy": unit.energy,
                "after_energy": after,
                "energy_gain": gain,
                "raw_energy_gain": raw_gain,
                "energy_regeneration_rate": (
                    regeneration.to_json() if regeneration is not None else None
                ),
                "defeated_event_payload": defeated_event_payload,
                "kill_credit_owner_id": str(defeated_event_payload.get("kill_credit_owner_id") or ""),
                "kill_credit_source_id": str(defeated_event_payload.get("kill_credit_source_id") or ""),
                "kill_credit_source_kind": str(defeated_event_payload.get("kill_credit_source_kind") or ""),
            },
            mutation_id=f"mutation:kill_energy_gain:{state.event_index}:{unit_id}:{damage_event_id}",
        )

    def plan_action_resources(self, state: BattleState, actor_id: str, plan: ResourcePlan) -> ResourcePlanResult:
        errors: list[str] = []
        mutations: list[Mutation] = []

        if plan.blocked_reason:
            return ResourcePlanResult(False, errors=(plan.blocked_reason,))
        if actor_id not in state.units:
            return ResourcePlanResult(False, errors=(f"unknown actor_id: {actor_id}",))

        special_gate = (plan.metadata or {}).get("special_resource_ultimate_gate")
        if special_gate is not None:
            if not isinstance(special_gate, dict):
                errors.append("ultimate_special_resource_gate_invalid")
            elif special_gate.get("valid") is not True:
                errors.append(str(special_gate.get("blocked_reason") or "ultimate_special_resource_gate_invalid"))
            elif special_gate.get("ready") is not True:
                errors.append("ultimate_special_resource_not_ready")
        if type(plan.energy_cost) not in (int, float) or not math.isfinite(plan.energy_cost):
            errors.append("ultimate_energy_cost_invalid")
        elif plan.energy_cost != 0.0:
            reason = ultimate_energy_blocked_reason(state.units[actor_id], plan.energy_cost)
            if reason:
                errors.append(reason)

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
                    metadata={"delta": plan.skill_point_delta, **_plan_metadata(plan)},
                    mutation_id=f"mutation:{plan.source}:skill_points:{state.event_index}",
                )
            )

        if isinstance(special_gate, dict) and special_gate.get("ready") is True:
            # 特殊资源终结技的消耗：来源用 ModifySkillPropertyByName 把 Skill03 的
            # SPNeed 同步为资源上限，施放时按该值扣除当前资源（同能量消耗）。
            current_key = str(special_gate.get("current_key") or "")
            unit = state.units[actor_id]
            current = unit.resources.get(current_key)
            cost = special_gate.get("maximum")
            if (not current_key or type(current) not in (int, float)
                    or type(cost) not in (int, float) or not math.isfinite(float(cost)) or cost <= 0):
                return ResourcePlanResult(False, errors=("ultimate_special_resource_cost_invalid",))
            after_value = max(0.0, float(current) - float(cost))
            mutations.append(Mutation(
                op="set",
                path=("units", actor_id, "resources", current_key),
                before=current,
                after=after_value,
                reason="consume special-resource ultimate cost",
                source=plan.source,
                metadata={**_plan_metadata(plan), "resource_operation": "ultimate_special_resource_cost",
                          "special_resource_cost": float(cost),
                          "cost_source": "Skill03 SPNeed synchronized to the resource maximum"},
                mutation_id=f"mutation:{plan.source}:special_resource:{state.event_index}:{actor_id}",
            ))
            state = replace(state, units={**state.units, actor_id: replace(
                unit, resources={**unit.resources, current_key: after_value})})

        if plan.energy_cost != 0.0:
            debit = self.change_unit_energy(state, actor_id, -float(plan.energy_cost), plan.source)
            debit = replace(debit, reason="consume action energy cost", metadata={
                **debit.metadata, **_plan_metadata(plan),
                "resource_operation": "ultimate_energy_cost",
                "energy_cost": plan.energy_cost,
            })
            mutations.append(debit)
            state = replace(state, units={
                **state.units, actor_id: replace(state.units[actor_id], energy=debit.after),
            })

        if plan.energy_gain != 0:
            mutations.append(
                self.change_unit_energy(
                    state,
                    actor_id,
                    plan.energy_gain,
                    plan.source,
                )
            )
            if plan.metadata:
                energy_mutation = mutations[-1]
                mutations[-1] = Mutation(
                    op=energy_mutation.op,
                    path=energy_mutation.path,
                    before=energy_mutation.before,
                    after=energy_mutation.after,
                    reason=energy_mutation.reason,
                    source=energy_mutation.source,
                    metadata={**energy_mutation.metadata, **_plan_metadata(plan)},
                    mutation_id=energy_mutation.mutation_id,
                )

        return ResourcePlanResult(True, tuple(mutations), ())


def _plan_metadata(plan: ResourcePlan) -> dict[str, JSONValue]:
    return dict(plan.metadata or {})


def ultimate_energy_blocked_reason(unit: UnitState, cost: float | None) -> str:
    if type(cost) not in (int, float) or not math.isfinite(cost) or cost <= 0:
        return "ultimate_energy_cost_invalid"
    if unit.max_energy <= 0 or unit.energy < cost:
        return "ultimate_energy_not_ready"
    return ""


def _effective_energy_delta(unit: UnitState, delta: float):
    if delta <= 0.0:
        return float(delta), None
    regeneration = effective_unit_stat(unit, "energy_regeneration_rate")
    multiplier = max(0.0, 1.0 + regeneration.value)
    return float(delta) * multiplier, regeneration
