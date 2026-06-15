from __future__ import annotations

from dataclasses import dataclass

from ..core.model import BattleState, GameEvent, Mutation


@dataclass(frozen=True)
class TimelinePlan:
    open_window: str = "action"
    close_window: str = "idle"
    reset_actor_av: bool = False
    source: str = "timeline_system"


@dataclass(frozen=True)
class TimelinePlanResult:
    mutations: tuple[Mutation, ...]
    events: tuple[GameEvent, ...]


class TimelineSystem:
    def set_action_value(self, state: BattleState, unit_id: str, action_value: float, source: str) -> Mutation:
        unit = state.units[unit_id]
        return Mutation(
            op="set",
            path=("units", unit_id, "action_value"),
            before=unit.action_value,
            after=max(0.0, action_value),
            reason="set action value",
            source=source,
            mutation_id=f"mutation:{unit_id}:action_value:{state.event_index}:{action_value}",
        )

    def advance_action_value(self, state: BattleState, unit_id: str, delta: float, source: str) -> Mutation:
        unit = state.units[unit_id]
        return self.set_action_value(state, unit_id, unit.action_value + delta, source)

    def open_action(self, state: BattleState, actor_id: str, plan: TimelinePlan) -> TimelinePlanResult:
        next_event_index = state.event_index + 1
        events = (
            GameEvent(
                "timeline.action_window_opened",
                source_id=actor_id,
                event_id=f"event:{next_event_index}:action_window_opened",
                window=plan.open_window,
                process_only=True,
                payload={"previous_window": state.global_flags.get("current_window", "idle")},
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
                mutation_id=f"mutation:timeline:event_index:{next_event_index}",
            ),
            Mutation(
                op="set",
                path=("global_flags", "current_window"),
                before=state.global_flags.get("current_window"),
                after=plan.open_window,
                reason="open action window",
                source=plan.source,
                mutation_id=f"mutation:timeline:current_window:{next_event_index}",
            ),
            Mutation(
                op="set",
                path=("global_flags", "turn_owner_id"),
                before=state.global_flags.get("turn_owner_id"),
                after=actor_id,
                reason="set action owner",
                source=plan.source,
                mutation_id=f"mutation:timeline:turn_owner:{next_event_index}",
            ),
        ]
        if plan.reset_actor_av:
            mutations.append(self.set_action_value(state, actor_id, 0.0, plan.source))
        return TimelinePlanResult(tuple(mutations), events)
