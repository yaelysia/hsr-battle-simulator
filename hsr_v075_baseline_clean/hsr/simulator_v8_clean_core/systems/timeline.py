from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..rules.ir import TimelineRuleIR


@dataclass(frozen=True)
class TimelinePlan:
    open_window: str = "action"
    close_window: str = "idle"
    reset_actor_av: bool = False
    source: str = "timeline_system"
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class TimelinePlanResult:
    mutations: tuple[Mutation, ...]
    events: tuple[GameEvent, ...]


@dataclass(frozen=True)
class TurnAdvancePlan:
    ok: bool
    timeline_rule_id: str
    actor_id: str = ""
    advance_delta: float = 0.0
    skipped_units: tuple[dict[str, JSONValue], ...] = ()
    blocked_reason: str = ""
    plan_id: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "timeline_rule_id": self.timeline_rule_id,
            "actor_id": self.actor_id,
            "advance_delta": self.advance_delta,
            "skipped_units": list(self.skipped_units),
            "blocked_reason": self.blocked_reason,
            "plan_id": self.plan_id,
            "source_trace": self.source_trace,
        }


@dataclass(frozen=True)
class TurnAdvanceResult:
    plan: TurnAdvancePlan
    mutations: tuple[Mutation, ...]
    events: tuple[GameEvent, ...]


class TimelineSystem:
    def initialize_action_values(
        self,
        state: BattleState,
        rule: TimelineRuleIR,
        *,
        explicit_overrides: tuple[str, ...] = (),
    ) -> TurnAdvanceResult:
        metadata = _timeline_metadata(rule, "timeline_initialize", "initialize_action_values")
        explicit = set(explicit_overrides)
        mutations: list[Mutation] = []
        for unit_id, unit in sorted(state.units.items()):
            if unit_id in explicit:
                continue
            action_value = self.full_action_value(unit.speed, rule)
            mutations.append(
                Mutation(
                    op="set",
                    path=("units", unit_id, "action_value"),
                    before=unit.action_value,
                    after=action_value,
                    reason="initialize action value from speed",
                    source="timeline_system",
                    metadata={**metadata, "unit_id": unit_id, "speed": unit.speed},
                    mutation_id=f"mutation:timeline:init_av:{unit_id}:{action_value}",
                )
            )
        plan = TurnAdvancePlan(
            ok=True,
            timeline_rule_id=rule.timeline_rule_id,
            plan_id="turn_advance_plan:initialize_action_values",
            source_trace=rule.source.to_json(),
        )
        return TurnAdvanceResult(plan, tuple(mutations), ())

    def full_action_value(self, speed: float, rule: TimelineRuleIR) -> float:
        effective_speed = max(float(speed), 1.0)
        return float(rule.base_action_gauge) / effective_speed

    def plan_next_actor(self, state: BattleState, rule: TimelineRuleIR) -> TurnAdvancePlan:
        candidates: list[tuple[float, str]] = []
        skipped: list[dict[str, JSONValue]] = []
        for unit_id, unit in sorted(state.units.items()):
            if unit.hp <= 0:
                skipped.append({"unit_id": unit_id, "reason": "unit_dead_or_zero_hp"})
                continue
            if unit.flags.get("action_disabled") is True:
                skipped.append({"unit_id": unit_id, "reason": "action_disabled"})
                continue
            if unit.side == "summon" and unit.flags.get("timeline_admitted") is not True:
                skipped.append({"unit_id": unit_id, "reason": "summon_timeline_not_admitted"})
                continue
            candidates.append((max(0.0, float(unit.action_value)), unit_id))
        if not candidates:
            return TurnAdvancePlan(
                ok=False,
                timeline_rule_id=rule.timeline_rule_id,
                blocked_reason="no_admitted_actor",
                skipped_units=tuple(skipped),
                plan_id=f"turn_advance_plan:{state.event_index}:blocked",
                source_trace=rule.source.to_json(),
            )
        advance_delta, actor_id = sorted(candidates, key=lambda item: (item[0], item[1]))[0]
        return TurnAdvancePlan(
            ok=True,
            timeline_rule_id=rule.timeline_rule_id,
            actor_id=actor_id,
            advance_delta=advance_delta,
            skipped_units=tuple(skipped),
            plan_id=f"turn_advance_plan:{state.event_index}:{actor_id}",
            source_trace=rule.source.to_json(),
        )

    def advance_to_next_actor(self, state: BattleState, plan: TurnAdvancePlan) -> TurnAdvanceResult:
        if not plan.ok:
            return TurnAdvanceResult(plan, (), ())
        metadata = _timeline_metadata_from_plan(plan, "timeline_advance", "advance_to_next_actor")
        mutations: list[Mutation] = []
        for unit_id, unit in sorted(state.units.items()):
            after = max(0.0, float(unit.action_value) - float(plan.advance_delta))
            if after == unit.action_value:
                continue
            mutations.append(
                Mutation(
                    op="set",
                    path=("units", unit_id, "action_value"),
                    before=unit.action_value,
                    after=after,
                    reason="advance timeline to next actor",
                    source="timeline_system",
                    metadata={**metadata, "unit_id": unit_id},
                    mutation_id=f"mutation:timeline:advance:{plan.plan_id}:{unit_id}:{after}",
                )
            )
        global_av = float(state.global_flags.get("global_av", 0.0)) + float(plan.advance_delta)
        mutations.extend(
            (
                Mutation(
                    op="set",
                    path=("global_flags", "global_av"),
                    before=state.global_flags.get("global_av"),
                    after=global_av,
                    reason="advance global action value",
                    source="timeline_system",
                    metadata=metadata,
                    mutation_id=f"mutation:timeline:global_av:{plan.plan_id}:{global_av}",
                ),
                Mutation(
                    op="set",
                    path=("global_flags", "last_advanced_delta"),
                    before=state.global_flags.get("last_advanced_delta"),
                    after=float(plan.advance_delta),
                    reason="record timeline advance delta",
                    source="timeline_system",
                    metadata=metadata,
                    mutation_id=f"mutation:timeline:last_delta:{plan.plan_id}",
                ),
            )
        )
        event = GameEvent(
            "timeline.advanced",
            source_id=plan.actor_id,
            event_id=f"event:{state.event_index}:timeline_advanced:{plan.actor_id}",
            window="timeline",
            process_only=True,
            payload={"turn_advance_plan": plan.to_json()},
        )
        return TurnAdvanceResult(plan, tuple(mutations), (event,))

    def begin_turn(self, state: BattleState, plan: TurnAdvancePlan, *, turn_kind: str = "regular") -> TurnAdvanceResult:
        if not plan.ok:
            return TurnAdvanceResult(plan, (), ())
        next_turn_index = int(state.global_flags.get("turn_sequence_index", 0)) + 1
        metadata = _timeline_metadata_from_plan(plan, "turn_begin", "begin_turn")
        active_turn = {
            "actor_id": plan.actor_id,
            "turn_kind": turn_kind,
            "turn_sequence_index": next_turn_index,
            "timeline_rule_id": plan.timeline_rule_id,
        }
        mutations = (
            Mutation(
                op="set",
                path=("global_flags", "turn_sequence_index"),
                before=state.global_flags.get("turn_sequence_index"),
                after=next_turn_index,
                reason="increment turn sequence",
                source="timeline_system",
                metadata=metadata,
                mutation_id=f"mutation:timeline:turn_sequence:{plan.plan_id}:{next_turn_index}",
            ),
            Mutation(
                op="set",
                path=("global_flags", "active_turn"),
                before=state.global_flags.get("active_turn"),
                after=active_turn,
                reason="begin turn",
                source="timeline_system",
                metadata=metadata,
                mutation_id=f"mutation:timeline:active_turn:{plan.plan_id}:{next_turn_index}",
            ),
            Mutation(
                op="set",
                path=("global_flags", "current_window"),
                before=state.global_flags.get("current_window"),
                after="turn_begin",
                reason="open turn begin window",
                source="timeline_system",
                metadata=metadata,
                mutation_id=f"mutation:timeline:turn_window:{plan.plan_id}:begin",
            ),
            Mutation(
                op="set",
                path=("global_flags", "turn_owner_id"),
                before=state.global_flags.get("turn_owner_id"),
                after=plan.actor_id,
                reason="set active turn owner",
                source="timeline_system",
                metadata=metadata,
                mutation_id=f"mutation:timeline:turn_owner:{plan.plan_id}",
            ),
        )
        event = GameEvent(
            "turn.begin",
            source_id=plan.actor_id,
            event_id=f"event:{state.event_index}:turn_begin:{plan.actor_id}:{next_turn_index}",
            window="turn_begin",
            process_only=True,
            payload={"turn_advance_plan": plan.to_json(), "turn_kind": turn_kind},
        )
        return TurnAdvanceResult(plan, mutations, (event,))

    def end_turn(self, state: BattleState, actor_id: str, rule: TimelineRuleIR, *, turn_kind: str = "regular") -> TurnAdvanceResult:
        unit = state.units[actor_id]
        plan = TurnAdvancePlan(
            ok=True,
            timeline_rule_id=rule.timeline_rule_id,
            actor_id=actor_id,
            plan_id=f"turn_advance_plan:{state.event_index}:{actor_id}:end",
            source_trace=rule.source.to_json(),
        )
        metadata = _timeline_metadata_from_plan(plan, "turn_end", "end_turn")
        reset_av = self.full_action_value(unit.speed, rule) if turn_kind == "regular" else unit.action_value
        mutations = (
            Mutation(
                op="set",
                path=("units", actor_id, "action_value"),
                before=unit.action_value,
                after=reset_av,
                reason="reset actor action value after turn",
                source="timeline_system",
                metadata={**metadata, "speed": unit.speed, "turn_kind": turn_kind},
                mutation_id=f"mutation:timeline:end_turn_reset:{actor_id}:{state.event_index}:{reset_av}",
            ),
            Mutation(
                op="set",
                path=("global_flags", "current_window"),
                before=state.global_flags.get("current_window"),
                after="idle",
                reason="close turn window",
                source="timeline_system",
                metadata=metadata,
                mutation_id=f"mutation:timeline:turn_window:{actor_id}:{state.event_index}:idle",
            ),
            Mutation(
                op="set",
                path=("global_flags", "active_turn"),
                before=state.global_flags.get("active_turn"),
                after=None,
                reason="clear active turn",
                source="timeline_system",
                metadata=metadata,
                mutation_id=f"mutation:timeline:active_turn_clear:{actor_id}:{state.event_index}",
            ),
        )
        event = GameEvent(
            "turn.end",
            source_id=actor_id,
            event_id=f"event:{state.event_index}:turn_end:{actor_id}",
            window="turn_end",
            process_only=True,
            payload={"turn_kind": turn_kind, "timeline_rule": rule.to_json()},
        )
        return TurnAdvanceResult(plan, mutations, (event,))

    def set_action_value(
        self,
        state: BattleState,
        unit_id: str,
        action_value: float,
        source: str,
        metadata: dict[str, JSONValue] | None = None,
    ) -> Mutation:
        unit = state.units[unit_id]
        return Mutation(
            op="set",
            path=("units", unit_id, "action_value"),
            before=unit.action_value,
            after=max(0.0, action_value),
            reason="set action value",
            source=source,
            metadata=metadata or {},
            mutation_id=f"mutation:{unit_id}:action_value:{state.event_index}:{action_value}",
        )

    def advance_action_value(
        self,
        state: BattleState,
        unit_id: str,
        delta: float,
        source: str,
        metadata: dict[str, JSONValue] | None = None,
    ) -> Mutation:
        unit = state.units[unit_id]
        return self.set_action_value(state, unit_id, unit.action_value + delta, source, metadata)

    def open_action(self, state: BattleState, actor_id: str, plan: TimelinePlan) -> TimelinePlanResult:
        next_event_index = state.event_index + 1
        metadata = dict(plan.metadata)
        events = (
            GameEvent(
                "timeline.action_window_opened",
                source_id=actor_id,
                event_id=f"event:{next_event_index}:action_window_opened",
                window=plan.open_window,
                process_only=True,
                payload={
                    "previous_window": state.global_flags.get("current_window", "idle"),
                    "metadata": metadata,
                },
            ),
        )
        mutations: list[Mutation] = [
            Mutation(
                op="set",
                path=("event_index",),
                before=state.event_index,
                after=next_event_index,
                reason="action transaction opened",
                source=plan.source,
                metadata=metadata,
                mutation_id=f"mutation:timeline:event_index:{next_event_index}",
            ),
            Mutation(
                op="set",
                path=("global_flags", "current_window"),
                before=state.global_flags.get("current_window"),
                after=plan.open_window,
                reason="open action window",
                source=plan.source,
                metadata=metadata,
                mutation_id=f"mutation:timeline:current_window:{next_event_index}",
            ),
            Mutation(
                op="set",
                path=("global_flags", "turn_owner_id"),
                before=state.global_flags.get("turn_owner_id"),
                after=actor_id,
                reason="set action owner",
                source=plan.source,
                metadata=metadata,
                mutation_id=f"mutation:timeline:turn_owner:{next_event_index}",
            ),
        ]
        if plan.reset_actor_av:
            mutations.append(self.set_action_value(state, actor_id, 0.0, plan.source, metadata))
        return TimelinePlanResult(tuple(mutations), events)


def _timeline_metadata(rule: TimelineRuleIR, phase: str, operation: str) -> dict[str, JSONValue]:
    return {
        "timeline_rule_id": rule.timeline_rule_id,
        "turn_advance_plan_id": operation,
        "timeline_phase": phase,
        "operation": operation,
        "source_trace": rule.source.to_json(),
    }


def _timeline_metadata_from_plan(plan: TurnAdvancePlan, phase: str, operation: str) -> dict[str, JSONValue]:
    return {
        "timeline_rule_id": plan.timeline_rule_id,
        "turn_advance_plan_id": plan.plan_id,
        "timeline_phase": phase,
        "operation": operation,
        "source_trace": plan.source_trace,
    }
