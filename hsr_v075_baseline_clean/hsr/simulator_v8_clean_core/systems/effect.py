from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..rules.ir import EffectIR
from .status import StatusSystem


@dataclass(frozen=True)
class EffectResult:
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    unsupported: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectExecutionContext:
    state: BattleState
    caster_id: str
    source_id: str
    owner_id: str | None = None
    param_entity_id: str | None = None
    current_action_target_id: str | None = None


EffectHandler = Callable[[EffectIR, EffectExecutionContext | None], EffectResult]


class EffectRegistry:
    """Opcode dispatcher for v8 EffectIR handlers."""

    def __init__(self, status_system: StatusSystem | None = None) -> None:
        self.status_system = status_system
        self._handlers: dict[str, EffectHandler] = {}
        if status_system is not None:
            self.register("AddModifier", self._execute_add_modifier)

    def register(self, opcode: str, handler: EffectHandler) -> None:
        self._handlers[opcode] = handler

    def execute(self, effect: EffectIR, context: EffectExecutionContext | None = None) -> EffectResult:
        handler = self._handlers.get(effect.opcode)
        if not handler:
            return EffectResult(unsupported=(effect.opcode,))
        return handler(effect, context)

    def coverage(self, effect: EffectIR) -> str:
        return "executable" if effect.opcode in self._handlers else effect.coverage_status

    def _execute_add_modifier(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        if self.status_system is None:
            return EffectResult(unsupported=("AddModifier requires StatusSystem",))
        if context is None:
            return EffectResult(unsupported=("AddModifier requires EffectExecutionContext",))
        result = self.status_system.apply_add_modifier(
            context.state,
            effect,
            caster_id=context.caster_id,
            source_id=context.source_id,
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
        )
        return EffectResult(
            mutations=result.mutations,
            records=result.records,
            unsupported=result.unsupported,
        )
