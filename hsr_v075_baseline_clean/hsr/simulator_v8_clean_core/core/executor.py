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
    TargetResolution,
)
from .reducer import MutationReducer
from .settlement import SettlementRecord
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
                event_id=f"event:{state.event_index + 1}:action_requested",
                window="action_request",
                process_only=True,
                payload={"action_id": command.action_id, "source": command.source},
            ),
        )
        target_resolution = TargetResolution(
            requested=command.target_ids,
            legal=tuple(unit_id for unit_id in command.target_ids if unit_id in state.units),
            selected=tuple(unit_id for unit_id in command.target_ids if unit_id in state.units),
            rejected=tuple(unit_id for unit_id in command.target_ids if unit_id not in state.units),
            reason="explicit_targets_checked",
            source="combat_executor",
        )
        mutations = (
            Mutation(
                op="set",
                path=("event_index",),
                before=state.event_index,
                after=state.event_index + 1,
                reason="action transaction opened",
                source="combat_executor",
                mutation_id=f"mutation:{state.event_index + 1}:event_index",
            ),
        )
        after_state = self.reducer.apply_all(state, mutations)
        settlement = ActionSettlement(
            action_id=command.action_id,
            actor_id=command.actor_id,
            target_ids=command.target_ids,
            records=(
                SettlementRecord(
                    record_type="process",
                    source="combat_executor",
                    process_only=True,
                    payload={
                        "event": "action.requested",
                        "rule_known": self.rules.has_action(command.action_id),
                    },
                    trace={"event_id": events[0].event_id},
                ).to_json(),
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
            target_resolution=target_resolution,
            rng_events=(),
            coverage={"executor": "v0_200_transaction_contract"},
        )
        return after_state, transition
