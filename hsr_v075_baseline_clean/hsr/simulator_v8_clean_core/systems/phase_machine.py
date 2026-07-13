from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import BattleState, GameEvent, JSONValue, Mutation


COMBAT_PHASE_SCHEMA_VERSION = "p7_s9_combat_phase_machine_v1"
IDLE = "idle"
TIMELINE_ADVANCING = "timeline_advancing"
TURN_BEGIN = "turn_begin"
PRE_ACTION = "pre_action"
AWAITING_DECISION = "awaiting_decision"
ACTION_EXECUTION = "action_execution"
POST_ACTION = "post_action"
TURN_END = "turn_end"
INSERT_WINDOW = "insert_window"
EXTRA_ACTION = "extra_action"
WAVE_TRANSITION = "wave_transition"
ENDED = "ended"


LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    IDLE: (TIMELINE_ADVANCING, INSERT_WINDOW, WAVE_TRANSITION, ENDED),
    TIMELINE_ADVANCING: (TURN_BEGIN, WAVE_TRANSITION, ENDED),
    TURN_BEGIN: (PRE_ACTION, TURN_END),
    PRE_ACTION: (AWAITING_DECISION, TURN_END),
    AWAITING_DECISION: (ACTION_EXECUTION, INSERT_WINDOW, ENDED),
    ACTION_EXECUTION: (POST_ACTION,),
    POST_ACTION: (TURN_END, INSERT_WINDOW, EXTRA_ACTION, ENDED),
    INSERT_WINDOW: (ACTION_EXECUTION, AWAITING_DECISION, TURN_END, EXTRA_ACTION, ENDED),
    EXTRA_ACTION: (ACTION_EXECUTION, POST_ACTION, INSERT_WINDOW, TURN_END, ENDED),
    TURN_END: (IDLE, WAVE_TRANSITION, ENDED),
    WAVE_TRANSITION: (IDLE, TIMELINE_ADVANCING, ENDED),
    ENDED: (),
}


OPERATION_PHASES: dict[str, tuple[str, ...]] = {
    "advance_timeline": (IDLE,),
    "query_decision": (AWAITING_DECISION, INSERT_WINDOW),
    "query_timeline_actor_choice": (IDLE,),
    "submit_turn_action": (AWAITING_DECISION,),
    "submit_insert_action": (INSERT_WINDOW,),
    "execute_action": (ACTION_EXECUTION,),
    "post_action": (POST_ACTION,),
    "end_turn": (TURN_END,),
    "resolve_queue_entry": (IDLE, AWAITING_DECISION, POST_ACTION, INSERT_WINDOW),
    "wave_transition": (WAVE_TRANSITION,),
}

EVENT_PHASES: dict[str, tuple[str, ...]] = {
    "battle.start": (IDLE,),
    "turn.begin": (TURN_BEGIN,),
    "turn.end": (TURN_END,),
    "wave.monster": (WAVE_TRANSITION,),
    "wave.started": (WAVE_TRANSITION,),
    "wave.cleared": (WAVE_TRANSITION,),
    "battle.victory": (WAVE_TRANSITION,),
    "battle.defeat": (WAVE_TRANSITION,),
    "battle.completed": (WAVE_TRANSITION,),
}


@dataclass(frozen=True)
class PhaseTransitionPlan:
    ok: bool
    from_phase: str
    to_phase: str
    actor_id: str = ""
    reason: str = ""
    blocked_reason: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": COMBAT_PHASE_SCHEMA_VERSION,
            "ok": self.ok,
            "from_phase": self.from_phase,
            "to_phase": self.to_phase,
            "actor_id": self.actor_id,
            "reason": self.reason,
            "blocked_reason": self.blocked_reason,
            "allowed_next_phases": list(LEGAL_TRANSITIONS.get(self.from_phase, ())),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class PhaseTransitionResult:
    plan: PhaseTransitionPlan
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()


class CombatPhaseMachine:
    def current_phase(self, state: BattleState) -> str:
        if "combat_phase" not in state.global_flags or state.global_flags.get("combat_phase") is None:
            return IDLE
        value = state.global_flags.get("combat_phase")
        return value if isinstance(value, str) else f"<invalid:{type(value).__name__}>"

    def allowed_next_phases(self, state: BattleState) -> tuple[str, ...]:
        return LEGAL_TRANSITIONS.get(self.current_phase(state), ())

    def operation_blocked_reason(self, state: BattleState, operation: str) -> str:
        allowed = OPERATION_PHASES.get(operation)
        if allowed is None:
            return f"unknown_phase_operation:{operation}"
        current = self.current_phase(state)
        if current not in LEGAL_TRANSITIONS:
            return f"unknown_current_combat_phase:{current}"
        return "" if current in allowed else f"operation_not_allowed_in_phase:{operation}:{current}"

    def event_blocked_reason(self, state: BattleState, event_type: str) -> str:
        allowed = EVENT_PHASES.get(event_type)
        if allowed is None:
            return ""
        current = self.current_phase(state)
        if current not in LEGAL_TRANSITIONS:
            return f"unknown_current_combat_phase:{current}"
        return "" if current in allowed else f"event_not_allowed_in_phase:{event_type}:{current}"

    def transition(
        self,
        state: BattleState,
        to_phase: str,
        *,
        actor_id: str = "",
        reason: str,
        metadata: dict[str, JSONValue] | None = None,
        mutation_source: str = "timeline_system",
    ) -> PhaseTransitionResult:
        current = self.current_phase(state)
        detail = metadata or {}
        if current not in LEGAL_TRANSITIONS:
            return self._blocked(
                current,
                to_phase,
                actor_id,
                reason,
                f"unknown_current_combat_phase:{current}",
                detail,
            )
        if to_phase not in LEGAL_TRANSITIONS:
            return self._blocked(current, to_phase, actor_id, reason, "unknown_combat_phase", detail)
        if to_phase not in LEGAL_TRANSITIONS[current]:
            return self._blocked(
                current,
                to_phase,
                actor_id,
                reason,
                f"illegal_phase_transition:{current}:{to_phase}",
                detail,
            )
        plan = PhaseTransitionPlan(
            ok=True,
            from_phase=current,
            to_phase=to_phase,
            actor_id=actor_id,
            reason=reason,
            metadata=detail,
        )
        before_exists = "combat_phase" in state.global_flags
        mutation = Mutation(
            op="set",
            path=("global_flags", "combat_phase"),
            before=state.global_flags.get("combat_phase"),
            after=to_phase,
            reason=reason,
            source=mutation_source,
            before_exists=before_exists,
            metadata={
                "operation": "combat_phase_transition",
                "phase_contract": COMBAT_PHASE_SCHEMA_VERSION,
                "from_phase": current,
                "to_phase": to_phase,
                "actor_id": actor_id,
                **detail,
            },
            mutation_id=f"mutation:combat_phase:{state.event_index}:{current}:{to_phase}:{actor_id or 'none'}",
        )
        event = GameEvent(
            "combat.phase.changed",
            source_id=actor_id,
            event_id=f"event:{state.event_index}:combat_phase:{current}:{to_phase}:{actor_id or 'none'}",
            window=to_phase,
            process_only=True,
            payload={"phase_transition": plan.to_json()},
        )
        record = {
            "record_type": "combat_phase_transition",
            "source": mutation_source,
            "mutation_id": mutation.stable_id(),
            "process_only": False,
            "payload": {"phase_transition": plan.to_json(), "mutation_path": list(mutation.path)},
            "trace": {},
        }
        return PhaseTransitionResult(plan, (mutation,), (event,), (record,))

    def _blocked(
        self,
        current: str,
        to_phase: str,
        actor_id: str,
        reason: str,
        blocked_reason: str,
        metadata: dict[str, JSONValue],
    ) -> PhaseTransitionResult:
        return PhaseTransitionResult(
            PhaseTransitionPlan(
                ok=False,
                from_phase=current,
                to_phase=to_phase,
                actor_id=actor_id,
                reason=reason,
                blocked_reason=blocked_reason,
                metadata=metadata,
            )
        )
