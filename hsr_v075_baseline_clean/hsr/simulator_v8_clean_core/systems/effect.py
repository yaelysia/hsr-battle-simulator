from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..core.model import GameEvent, Mutation
from ..rules.ir import EffectIR


@dataclass(frozen=True)
class EffectResult:
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    unsupported: tuple[str, ...] = ()


EffectHandler = Callable[[EffectIR], EffectResult]


class EffectRegistry:
    """Opcode dispatcher for v8 EffectIR handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, EffectHandler] = {}

    def register(self, opcode: str, handler: EffectHandler) -> None:
        self._handlers[opcode] = handler

    def execute(self, effect: EffectIR) -> EffectResult:
        handler = self._handlers.get(effect.opcode)
        if not handler:
            return EffectResult(unsupported=(effect.opcode,))
        return handler(effect)

    def coverage(self, effect: EffectIR) -> str:
        return "executable" if effect.opcode in self._handlers else effect.coverage_status

