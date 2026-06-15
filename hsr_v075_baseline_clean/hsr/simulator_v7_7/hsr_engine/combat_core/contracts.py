from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from hsr_engine.kernel import ActionRequest, ActionTransition, SourceRef, StateChange
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
    legacy_context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def begin(cls, action_input: ActionInput, legacy_context: dict[str, Any] | None = None) -> "ActionTransaction":
        settlement = SettlementCollector()
        settlement.begin_action(action_input.to_request())
        return cls(
            action_input=action_input,
            transition=settlement.transition,
            settlement=settlement,
            legacy_context=dict(legacy_context or {}),
        )

    def to_legacy_context(self) -> dict[str, Any]:
        ctx = dict(self.legacy_context)
        ctx.setdefault("_settlement", self.settlement)
        ctx.setdefault("actor_id", self.action_input.actor_id)
        ctx.setdefault("target_id", self.action_input.target_ids[0] if self.action_input.target_ids else "")
        ctx.setdefault("action", self.action_input.action)
        return ctx


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
