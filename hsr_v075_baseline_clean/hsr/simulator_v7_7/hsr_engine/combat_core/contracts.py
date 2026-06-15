from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from copy import deepcopy

from hsr_engine.kernel import ActionRequest, ActionTransition, ProcessEvent, RNGEvent, SourceRef, StateChange
from hsr_engine.settlement import ActionSettlement, SettlementCollector


@dataclass
class ActionInput:
    """Normalized action execution input for the parallel combat core."""

    actor_id: str = ""
    action_id: str = ""
    target_ids: list[str] = field(default_factory=list)
    action: dict[str, Any] = field(default_factory=dict)
    timing: str = "manual"
    turn_kind: str | None = None
    source: SourceRef = field(default_factory=SourceRef)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_request(self) -> ActionRequest:
        return ActionRequest(
            actor_id=self.actor_id,
            action_id=self.action_id,
            timing=self.timing,
            turn_kind=self.turn_kind,
            target_ids=list(self.target_ids),
            source=self.source,
            metadata=dict(self.metadata),
        )


@dataclass
class ActionTransaction:
    """Single action transaction boundary: request, transition, and settlement."""

    action_input: ActionInput = field(default_factory=ActionInput)
    transition: ActionTransition = field(default_factory=ActionTransition)
    settlement: SettlementCollector = field(default_factory=SettlementCollector)
    action: dict[str, Any] = field(default_factory=dict)
    actor: Any = None
    events: dict[str, Any] = field(default_factory=dict)
    requested_target_ids: list[str] = field(default_factory=list)
    resolved_target_ids: list[str] = field(default_factory=list)
    phase_locked_targets: set[str] = field(default_factory=set)
    state_changes: list[StateChange] = field(default_factory=list)
    rng_events: list[RNGEvent] = field(default_factory=list)
    process_events: list[ProcessEvent] = field(default_factory=list)
    settlement_payload: dict[str, Any] = field(default_factory=dict)
    state_store: Any = None
    state_mutator: Any = None
    rule_evaluator: Any = None
    effect_registry: Any = None
    legacy_context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def begin(
        cls,
        action_input: ActionInput,
        legacy_context: dict[str, Any] | None = None,
        *,
        settlement: SettlementCollector | None = None,
        action: dict[str, Any] | None = None,
        actor: Any = None,
        events: dict[str, Any] | None = None,
        state_store: Any = None,
        state_mutator: Any = None,
        rule_evaluator: Any = None,
        effect_registry: Any = None,
    ) -> "ActionTransaction":
        settlement = settlement or SettlementCollector()
        if not settlement.transition.request.action_id:
            settlement.begin_action(action_input.to_request())
        return cls(
            action_input=action_input,
            transition=settlement.transition,
            settlement=settlement,
            action=deepcopy(action or action_input.action or {}),
            actor=actor,
            events=deepcopy(events or {}),
            requested_target_ids=list(action_input.target_ids or []),
            resolved_target_ids=list(action_input.target_ids or []),
            state_store=state_store,
            state_mutator=state_mutator,
            rule_evaluator=rule_evaluator,
            effect_registry=effect_registry,
            legacy_context=dict(legacy_context or {}),
        )

    @classmethod
    def from_legacy_action(
        cls,
        *,
        action: dict[str, Any],
        targets: list[str],
        events: dict[str, Any],
        legacy_context: dict[str, Any],
        actor: Any = None,
        state_store: Any = None,
        state_mutator: Any = None,
        rule_evaluator: Any = None,
        effect_registry: Any = None,
    ) -> "ActionTransaction":
        settlement = legacy_context.get("_settlement") if isinstance(legacy_context, dict) else None
        if not isinstance(settlement, SettlementCollector):
            settlement = None
        action_input = ActionInput(
            actor_id=str(action.get("actor_id") or getattr(actor, "id", "") or ""),
            action_id=str(action.get("id") or ""),
            target_ids=list(targets or []),
            action=deepcopy(action or {}),
            timing=str(legacy_context.get("timing") or legacy_context.get("queued") and "queued" or "manual"),
            turn_kind=legacy_context.get("turn_kind"),
            metadata=deepcopy(legacy_context.get("metadata") or {}),
        )
        return cls.begin(
            action_input,
            legacy_context=legacy_context,
            settlement=settlement,
            action=action,
            actor=actor,
            events=events,
            state_store=state_store,
            state_mutator=state_mutator,
            rule_evaluator=rule_evaluator,
            effect_registry=effect_registry,
        )

    def to_legacy_context(self) -> dict[str, Any]:
        ctx = dict(self.legacy_context)
        ctx.setdefault("_settlement", self.settlement)
        ctx.setdefault("_transaction", self)
        ctx.setdefault("actor_id", self.action_input.actor_id)
        ctx.setdefault("target_id", self.action_input.target_ids[0] if self.action_input.target_ids else "")
        ctx.setdefault("targets", list(self.resolved_target_ids or self.action_input.target_ids))
        ctx.setdefault("action", self.action_input.action)
        ctx.setdefault("events", deepcopy(self.events))
        ctx.setdefault("phase_locked_targets", self.phase_locked_targets)
        ctx.setdefault("_state_store", self.state_store)
        ctx.setdefault("_state_mutator", self.state_mutator)
        ctx.setdefault("_rule_evaluator", self.rule_evaluator)
        ctx.setdefault("_effect_registry", self.effect_registry)
        return ctx

    def bind_targets(self, target_ids: list[str]) -> None:
        self.resolved_target_ids = list(target_ids or [])
        self.action_input.target_ids = list(target_ids or [])
        self.transition.request.target_ids = list(target_ids or [])

    def sync_from_transition(self) -> None:
        self.state_changes = list(self.transition.state_changes)
        self.rng_events = list(self.transition.rng_events)
        self.process_events = list(self.transition.process_events)


class StateView(Protocol):
    """Read side of battle state required by combat core modules."""

    units: dict[str, Any]

    def unit(self, unit_id: str) -> Any:
        ...


class StateMutator(Protocol):
    """Write side of battle state. Implementations must emit StateChange."""

    def commit_state_change(self, change: StateChange, ctx: dict[str, Any] | None = None) -> StateChange:
        ...


class RuleDataView(Protocol):
    """Rule query surface exposed to combat core modules."""

    def applicable_status_modifiers(self, unit: Any, ctx: dict[str, Any]) -> list[tuple[Any, dict[str, Any]]]:
        ...

    def contextual_stat(self, unit: Any, name: str, ctx: dict[str, Any]) -> float:
        ...
