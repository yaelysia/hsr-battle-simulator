from __future__ import annotations

from ..core.model import GameEvent
from ..rules.rulebook import RuleBook


class TriggerSystem:
    def match(self, rules: RuleBook, event: GameEvent) -> tuple[str, ...]:
        return tuple(trigger.trigger_id for trigger in rules.triggers_for_event(event.event_type))

