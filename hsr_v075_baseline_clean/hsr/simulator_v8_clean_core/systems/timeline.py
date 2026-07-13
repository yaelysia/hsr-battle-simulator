from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..rules.ir import TimelineRuleIR
from .unit_lifecycle import UnitLifecycleSystem


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
    tied_actor_ids: tuple[str, ...] = ()
    tie_resolution: dict[str, JSONValue] = field(default_factory=dict)
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
            "tied_actor_ids": list(self.tied_actor_ids),
            "tie_resolution": self.tie_resolution,
            "blocked_reason": self.blocked_reason,
            "plan_id": self.plan_id,
            "source_trace": self.source_trace,
        }


@dataclass(frozen=True)
class TurnAdvanceResult:
    plan: TurnAdvancePlan
    mutations: tuple[Mutation, ...]
    events: tuple[GameEvent, ...]


@dataclass(frozen=True)
class TimelineAdjustmentPlan:
    ok: bool
    operation: str
    unit_id: str
    before_action_value: float
    after_action_value: float
    before_speed: float
    after_speed: float
    source: str
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "operation": self.operation,
            "unit_id": self.unit_id,
            "before_action_value": self.before_action_value,
            "after_action_value": self.after_action_value,
            "before_speed": self.before_speed,
            "after_speed": self.after_speed,
            "source": self.source,
            "metadata": self.metadata,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class TimelineAdjustmentResult:
    plan: TimelineAdjustmentPlan
    mutations: tuple[Mutation, ...]
    events: tuple[GameEvent, ...]
    records: tuple[dict[str, JSONValue], ...] = ()


class TimelineSystem:
    def __init__(self) -> None:
        self.lifecycle = UnitLifecycleSystem()

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

    def plan_next_actor(
        self,
        state: BattleState,
        rule: TimelineRuleIR,
        *,
        tie_choice_actor_id: str = "",
        tie_choice_id: str = "",
        tie_choice_source: dict[str, JSONValue] | None = None,
    ) -> TurnAdvancePlan:
        candidates: list[tuple[float, str, dict[str, JSONValue] | None]] = []
        skipped: list[dict[str, JSONValue]] = []
        for unit_id, unit in state.units.items():
            can_act, lifecycle_reason = self.lifecycle.can_act(state, unit_id)
            if not can_act:
                skipped.append({"unit_id": unit_id, "reason": lifecycle_reason})
                continue
            if unit.flags.get("action_disabled") is True:
                skipped.append({"unit_id": unit_id, "reason": "action_disabled"})
                continue
            if unit.flags.get("on_field") is False or unit.flags.get("off_field") is True:
                skipped.append({"unit_id": unit_id, "reason": "unit_off_field"})
                continue
            if unit.flags.get("backline") is True:
                skipped.append({"unit_id": unit_id, "reason": "unit_backline"})
                continue
            if unit.side == "summon" and unit.flags.get("timeline_admitted") is not True:
                skipped.append({"unit_id": unit_id, "reason": "summon_timeline_not_admitted"})
                continue
            candidates.append(
                (max(0.0, float(unit.action_value)), unit_id, _timeline_priority(unit.flags))
            )
        if not candidates:
            return TurnAdvancePlan(
                ok=False,
                timeline_rule_id=rule.timeline_rule_id,
                blocked_reason="no_admitted_actor",
                skipped_units=tuple(skipped),
                plan_id=f"turn_advance_plan:{state.event_index}:blocked",
                source_trace=rule.source.to_json(),
            )
        advance_delta = min(item[0] for item in candidates)
        tied = tuple(item for item in candidates if isclose(item[0], advance_delta, rel_tol=0.0, abs_tol=1e-9))
        tie_resolution: dict[str, JSONValue] = {
            "mode": "single_minimum",
            "candidate_count": len(tied),
        }
        if len(tied) == 1:
            actor_id = tied[0][1]
        else:
            tied_actor_ids = tuple(item[1] for item in tied)
            if tie_choice_actor_id:
                source = tie_choice_source if isinstance(tie_choice_source, dict) else {}
                expected_choice_id = timeline_tie_choice_id(state, rule, tie_choice_actor_id)
                if tie_choice_actor_id not in tied_actor_ids or tie_choice_id != expected_choice_id:
                    return TurnAdvancePlan(
                        ok=False,
                        timeline_rule_id=rule.timeline_rule_id,
                        advance_delta=advance_delta,
                        skipped_units=tuple(skipped),
                        tied_actor_ids=tied_actor_ids,
                        blocked_reason="timeline_tie_explicit_choice_invalid",
                        plan_id=f"turn_advance_plan:{state.event_index}:tie_blocked",
                        source_trace=rule.source.to_json(),
                    )
                actor_id = tie_choice_actor_id
                tie_resolution = {
                    "mode": "explicit_choice",
                    "actor_id": actor_id,
                    "choice_id": tie_choice_id,
                    "source_trace": source,
                }
            else:
                priorities = {item[1]: item[2] for item in tied}
                if any(priority is None for priority in priorities.values()):
                    return TurnAdvancePlan(
                        ok=False,
                        timeline_rule_id=rule.timeline_rule_id,
                        advance_delta=advance_delta,
                        skipped_units=tuple(skipped),
                        tied_actor_ids=tied_actor_ids,
                        tie_resolution={
                            "mode": "priority",
                            "priorities": {
                                unit_id: priority or {"status": "missing"}
                                for unit_id, priority in priorities.items()
                            },
                        },
                        blocked_reason="timeline_tie_priority_missing",
                        plan_id=f"turn_advance_plan:{state.event_index}:tie_blocked",
                        source_trace=rule.source.to_json(),
                    )
                priority_values = [float(priority["value"]) for priority in priorities.values() if priority]
                minimum_priority = min(priority_values)
                winners = tuple(
                    unit_id
                    for unit_id, priority in priorities.items()
                    if priority is not None and isclose(float(priority["value"]), minimum_priority, rel_tol=0.0, abs_tol=1e-9)
                )
                if len(winners) != 1:
                    return TurnAdvancePlan(
                        ok=False,
                        timeline_rule_id=rule.timeline_rule_id,
                        advance_delta=advance_delta,
                        skipped_units=tuple(skipped),
                        tied_actor_ids=tied_actor_ids,
                        tie_resolution={"mode": "priority", "priorities": priorities},
                        blocked_reason="timeline_tie_priority_ambiguous",
                        plan_id=f"turn_advance_plan:{state.event_index}:tie_blocked",
                        source_trace=rule.source.to_json(),
                    )
                actor_id = winners[0]
                tie_resolution = {
                    "mode": "priority",
                    "actor_id": actor_id,
                    "priorities": priorities,
                }
        return TurnAdvancePlan(
            ok=True,
            timeline_rule_id=rule.timeline_rule_id,
            actor_id=actor_id,
            advance_delta=advance_delta,
            skipped_units=tuple(skipped),
            tied_actor_ids=tuple(item[1] for item in tied),
            tie_resolution=tie_resolution,
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
                    before_exists="global_av" in state.global_flags,
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
                    before_exists="last_advanced_delta" in state.global_flags,
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
                before_exists="turn_sequence_index" in state.global_flags,
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
                before_exists="active_turn" in state.global_flags,
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
                before_exists="current_window" in state.global_flags,
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
                before_exists="turn_owner_id" in state.global_flags,
                metadata=metadata,
                mutation_id=f"mutation:timeline:turn_owner:{plan.plan_id}",
            ),
        )
        return TurnAdvanceResult(plan, mutations, ())

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
                before_exists="current_window" in state.global_flags,
                metadata=metadata,
                mutation_id=f"mutation:timeline:turn_window:{actor_id}:{state.event_index}:idle",
            ),
            Mutation(
                op="delete",
                path=("global_flags", "active_turn"),
                before=state.global_flags.get("active_turn"),
                after=None,
                reason="clear active turn",
                source="timeline_system",
                after_exists=False,
                metadata=metadata,
                mutation_id=f"mutation:timeline:active_turn_clear:{actor_id}:{state.event_index}",
            ),
            Mutation(
                op="delete",
                path=("global_flags", "turn_owner_id"),
                before=state.global_flags.get("turn_owner_id"),
                after=None,
                reason="consume active decision owner at turn end",
                source="timeline_system",
                before_exists="turn_owner_id" in state.global_flags,
                after_exists=False,
                metadata=metadata,
                mutation_id=f"mutation:timeline:turn_owner_clear:{actor_id}:{state.event_index}",
            ),
        )
        return TurnAdvanceResult(plan, mutations, ())

    def open_decision_window(self, state: BattleState, plan: TurnAdvancePlan) -> TurnAdvanceResult:
        metadata = _timeline_metadata_from_plan(plan, "turn_decision", "open_decision_window")
        mutation = Mutation(
            op="set",
            path=("global_flags", "current_window"),
            before=state.global_flags.get("current_window"),
            after="turn_active",
            reason="open external decision window after turn begin",
            source="timeline_system",
            before_exists="current_window" in state.global_flags,
            metadata=metadata,
            mutation_id=f"mutation:timeline:turn_window:{plan.plan_id}:decision",
        )
        event = GameEvent(
            "turn.decision.opened",
            source_id=plan.actor_id,
            event_id=f"event:{state.event_index}:turn_decision:{plan.actor_id}",
            window="turn_active",
            process_only=True,
            payload={"turn_advance_plan": plan.to_json(), "selection_controller": "external"},
        )
        return TurnAdvanceResult(plan, (mutation,), (event,))

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

    def adjust_action_value(
        self,
        state: BattleState,
        unit_id: str,
        *,
        operation: str,
        amount: float = 0.0,
        source: str,
        metadata: dict[str, JSONValue] | None = None,
        rule: TimelineRuleIR | None = None,
    ) -> TimelineAdjustmentResult:
        unit = state.units[unit_id]
        before = max(0.0, float(unit.action_value))
        if operation == "advance":
            after = max(0.0, before - max(0.0, float(amount)))
        elif operation == "delay":
            after = before + max(0.0, float(amount))
        elif operation == "set":
            after = max(0.0, float(amount))
        elif operation == "immediate_action":
            after = 0.0
        elif operation == "extra_action":
            after = before
        else:
            plan = TimelineAdjustmentPlan(
                ok=False,
                operation=operation,
                unit_id=unit_id,
                before_action_value=before,
                after_action_value=before,
                before_speed=float(unit.speed),
                after_speed=float(unit.speed),
                source=source,
                metadata=metadata or {},
                blocked_reason="unsupported_timeline_adjustment",
            )
            return TimelineAdjustmentResult(
                plan,
                (),
                (),
                (
                    SettlementRecord(
                        record_type="timeline_adjustment_blocked",
                        source=source,
                        process_only=True,
                        payload={"timeline_adjustment_plan": plan.to_json()},
                        trace=_source_trace(metadata),
                    ).to_json(),
                ),
            )
        adjustment_metadata = {
            **(metadata or {}),
            **(
                {
                    "timeline_rule_id": rule.timeline_rule_id,
                    "turn_advance_plan_id": f"timeline_adjustment:{operation}:{state.event_index}:{unit_id}",
                    "source_trace": rule.source.to_json(),
                }
                if rule is not None
                else {}
            ),
            "timeline_adjustment": {
                "operation": operation,
                "amount": float(amount),
                "before_remaining_action_value": before,
                "after_remaining_action_value": after,
            },
        }
        plan = TimelineAdjustmentPlan(
            ok=True,
            operation=operation,
            unit_id=unit_id,
            before_action_value=before,
            after_action_value=after,
            before_speed=float(unit.speed),
            after_speed=float(unit.speed),
            source=source,
            metadata=adjustment_metadata,
        )
        mutations = (
            ()
            if isclose(after, before, rel_tol=0.0, abs_tol=1e-12)
            else (self.set_action_value(state, unit_id, after, source, adjustment_metadata),)
        )
        event = GameEvent(
            "timeline.action_value.adjusted",
            source_id=unit_id,
            target_id=unit_id,
            event_id=f"event:{state.event_index}:timeline_adjustment:{unit_id}:{operation}",
            window="timeline",
            process_only=True,
            payload={"timeline_adjustment_plan": plan.to_json()},
        )
        return TimelineAdjustmentResult(
            plan,
            mutations,
            (event,),
            _timeline_adjustment_records(plan, mutations),
        )

    def change_speed_preserving_progress(
        self,
        state: BattleState,
        unit_id: str,
        *,
        new_speed: float,
        rule: TimelineRuleIR,
        source: str,
        metadata: dict[str, JSONValue] | None = None,
    ) -> TimelineAdjustmentResult:
        unit = state.units[unit_id]
        old_speed = max(float(unit.speed), 1.0)
        effective_new_speed = max(float(new_speed), 1.0)
        before = max(0.0, float(unit.action_value))
        after = before * old_speed / effective_new_speed
        old_full = self.full_action_value(old_speed, rule)
        new_full = self.full_action_value(effective_new_speed, rule)
        progress = 1.0 - (before / old_full)
        adjustment_metadata = {
            **(metadata or {}),
            "timeline_rule_id": rule.timeline_rule_id,
            "turn_advance_plan_id": f"timeline_adjustment:speed_change:{state.event_index}:{unit_id}",
            "source_trace": rule.source.to_json(),
            "timeline_adjustment": {
                "operation": "speed_change",
                "old_speed": old_speed,
                "new_speed": effective_new_speed,
                "old_full_action_value": old_full,
                "new_full_action_value": new_full,
                "progress_completed": progress,
                "before_remaining_action_value": before,
                "after_remaining_action_value": after,
                "invariant": "remaining_after=remaining_before*old_speed/new_speed",
            },
        }
        plan = TimelineAdjustmentPlan(
            ok=True,
            operation="speed_change",
            unit_id=unit_id,
            before_action_value=before,
            after_action_value=after,
            before_speed=float(unit.speed),
            after_speed=effective_new_speed,
            source=source,
            metadata=adjustment_metadata,
        )
        mutations = (
            Mutation(
                op="set",
                path=("units", unit_id, "speed"),
                before=unit.speed,
                after=effective_new_speed,
                reason="change speed while preserving elapsed timeline progress",
                source=source,
                metadata=adjustment_metadata,
                mutation_id=f"mutation:timeline:speed:{unit_id}:{state.event_index}:{effective_new_speed}",
            ),
            self.set_action_value(state, unit_id, after, source, adjustment_metadata),
        )
        event = GameEvent(
            "timeline.speed.changed",
            source_id=unit_id,
            target_id=unit_id,
            event_id=f"event:{state.event_index}:timeline_speed_changed:{unit_id}",
            window="timeline",
            process_only=True,
            payload={"timeline_adjustment_plan": plan.to_json()},
        )
        return TimelineAdjustmentResult(
            plan,
            mutations,
            (event,),
            _timeline_adjustment_records(plan, mutations),
        )

    def advance_action_value(
        self,
        state: BattleState,
        unit_id: str,
        delta: float,
        source: str,
        metadata: dict[str, JSONValue] | None = None,
    ) -> Mutation:
        operation = "delay" if delta >= 0.0 else "advance"
        result = self.adjust_action_value(
            state,
            unit_id,
            operation=operation,
            amount=abs(float(delta)),
            source=source,
            metadata=metadata,
        )
        if result.mutations:
            return result.mutations[0]
        return self.set_action_value(
            state,
            unit_id,
            state.units[unit_id].action_value,
            source,
            result.plan.metadata,
        )

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
                before_exists="current_window" in state.global_flags,
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
                before_exists="turn_owner_id" in state.global_flags,
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


def _timeline_priority(flags: dict[str, JSONValue]) -> dict[str, JSONValue] | None:
    value = flags.get("timeline_priority")
    if not isinstance(value, dict):
        return None
    priority = value.get("value")
    if not isinstance(priority, (int, float)) or isinstance(priority, bool):
        return None
    source_trace = value.get("source_trace") if isinstance(value.get("source_trace"), dict) else {}
    return {
        "value": float(priority),
        "priority_id": str(value.get("priority_id") or ""),
        "source_trace": source_trace,
    }


def timeline_tie_choice_id(state: BattleState, rule: TimelineRuleIR, actor_id: str) -> str:
    """Stable behavioral identity for an external tied-actor choice."""

    return f"timeline_choice:{state.event_index}:{rule.timeline_rule_id}:{actor_id}"


def _source_trace(metadata: dict[str, JSONValue] | None) -> dict[str, JSONValue]:
    trace = metadata.get("source_trace") if isinstance(metadata, dict) else None
    return trace if isinstance(trace, dict) else {}


def _timeline_adjustment_records(
    plan: TimelineAdjustmentPlan,
    mutations: tuple[Mutation, ...],
) -> tuple[dict[str, JSONValue], ...]:
    return tuple(
        SettlementRecord(
            record_type="timeline_adjustment",
            source=mutation.source,
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "timeline_adjustment_plan": plan.to_json(),
                "mutation_path": list(mutation.path),
            },
            trace=_source_trace(plan.metadata),
        ).to_json()
        for mutation in mutations
    )
