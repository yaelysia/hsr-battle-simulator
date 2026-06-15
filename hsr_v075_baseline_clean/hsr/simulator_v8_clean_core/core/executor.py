from __future__ import annotations

from dataclasses import replace

from .model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    Mutation,
)
from .reducer import MutationReducer
from ..rules.rulebook import RuleBook


class CombatExecutor:
    """Minimal v8 action executor.

    v0_200 establishes the transaction and mutation contract. Full HSR action
    lifecycle systems are attached behind this boundary in later checkpoints.
    """

    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.reducer = MutationReducer()

    def execute(self, command: ActionCommand, state: BattleState) -> tuple[BattleState, BattleTransition]:
        before = state.snapshot()
        events = (
            GameEvent(
                "action.requested",
                source_id=command.actor_id,
                payload={"action_id": command.action_id, "source": command.source},
            ),
        )
        mutations = (
            Mutation(
                op="set",
                path=("event_index",),
                before=state.event_index,
                after=state.event_index + 1,
                reason="action transaction opened",
                source="combat_executor",
            ),
        )
        after_state = self.reducer.apply_all(state, mutations)
        settlement = ActionSettlement(
            action_id=command.action_id,
            actor_id=command.actor_id,
            target_ids=command.target_ids,
            records=(
                {
                    "record_type": "process",
                    "event": "action.requested",
                    "process_only": True,
                    "rule_known": self.rules.has_action(command.action_id),
                },
            ),
        )
        transaction = ActionTransaction(
            command=command,
            before=before,
            events=events,
            mutations=mutations,
            settlement=settlement,
        )
        transition = BattleTransition(
            transaction=transaction,
            after=after_state.snapshot(),
            coverage={"executor": "v0_200_transaction_contract"},
        )
        return after_state, transition

