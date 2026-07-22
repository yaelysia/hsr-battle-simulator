from __future__ import annotations

from dataclasses import dataclass

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.ir import BattleStateTransitionIR
from ..rules.rulebook import RuleBook
from .mutation_events import events_for_mutation


@dataclass(frozen=True)
class BattleStateTransitionRequest:
    trigger_kind: str
    trigger_identity: str
    actor_id: str = ""
    source_id: str = ""


@dataclass(frozen=True)
class BattleStateTransitionResult:
    ok: bool
    after_state: BattleState
    transition_rule: BattleStateTransitionIR | None = None
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    errors: tuple[str, ...] = ()


class BattleStateTransitionSystem:
    """Apply shared battle-state windows from typed Canonical IR rules."""

    def __init__(self, rules: RuleBook):
        self.rules = rules

    def apply(
        self,
        state: BattleState,
        request: BattleStateTransitionRequest,
    ) -> BattleStateTransitionResult:
        if (
            not isinstance(request.trigger_kind, str)
            or not request.trigger_kind
            or not isinstance(request.trigger_identity, str)
            or not request.trigger_identity
        ):
            return self._blocked(state, None, "battle_state_transition_trigger_invalid")
        rule, reason = self.rules.battle_state_transition_resolution_for_trigger(
            request.trigger_kind,
            request.trigger_identity,
        )
        if rule is None:
            return self._blocked(state, None, reason)
        if len(rule.state_path) != 2 or rule.state_path[0] != "global_flags":
            return self._blocked(
                state,
                rule,
                "battle_state_transition_state_path_not_supported",
            )

        flag_name = rule.state_path[1]
        before_exists = flag_name in state.global_flags
        before = state.global_flags.get(flag_name)
        if not before_exists:
            if not rule.allow_missing_before:
                return self._blocked(
                    state,
                    rule,
                    "battle_state_transition_required_before_state_missing",
                )
        elif type(before) is not type(rule.before_value) or before != rule.before_value:
            return self._blocked(
                state,
                rule,
                "battle_state_transition_before_state_mismatch",
            )

        source_trace = rule.source.to_json()
        mutation = Mutation(
            op="set",
            path=rule.state_path,
            before=before if before_exists else None,
            after=rule.after_value,
            before_exists=before_exists,
            after_exists=True,
            reason="apply source-backed shared battle-state transition",
            source="battle_state_transition_system",
            metadata={
                "battle_state_transition_rule_id": rule.transition_rule_id,
                "trigger_kind": rule.trigger_kind,
                "trigger_identity": rule.trigger_identity,
                "runtime_event_type": rule.runtime_event_type,
                "callback_event": rule.callback_event,
                "source_trace": source_trace,
            },
            mutation_id=(
                "mutation:battle_state_transition:"
                f"{state.event_index}:{rule.transition_rule_id}"
            ),
        )
        after_state = MutationReducer().apply(state, mutation)
        events = tuple(
            event
            for event in events_for_mutation(
                mutation,
                actor_id=request.actor_id,
                source_id=request.source_id or request.actor_id,
                event_index=state.event_index,
            )
            if event.event_type == rule.runtime_event_type
            and rule.callback_event in event.payload.get("callback_events", ())
        )
        if len(events) != 1:
            return self._blocked(
                state,
                rule,
                "battle_state_transition_runtime_event_contract_mismatch",
            )
        record = SettlementRecord(
            record_type="battle_state_transition",
            source=mutation.source,
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "battle_state_transition_rule_id": rule.transition_rule_id,
                "trigger_kind": rule.trigger_kind,
                "trigger_identity": rule.trigger_identity,
                "runtime_event_type": rule.runtime_event_type,
                "callback_event": rule.callback_event,
                "state_path": list(rule.state_path),
            },
            trace=source_trace,
        ).to_json()
        return BattleStateTransitionResult(
            ok=True,
            after_state=after_state,
            transition_rule=rule,
            mutations=(mutation,),
            events=events,
            records=(record,),
        )

    def _blocked(
        self,
        state: BattleState,
        rule: BattleStateTransitionIR | None,
        reason: str,
    ) -> BattleStateTransitionResult:
        record = SettlementRecord(
            record_type="battle_state_transition_blocked",
            source="battle_state_transition_system",
            process_only=True,
            payload={
                "reason": reason,
                "battle_state_transition_rule_id": (
                    rule.transition_rule_id if rule is not None else ""
                ),
            },
            trace=(rule.source.to_json() if rule is not None else {}),
        ).to_json()
        return BattleStateTransitionResult(
            ok=False,
            after_state=state,
            transition_rule=rule,
            records=(record,),
            errors=(reason,),
        )
