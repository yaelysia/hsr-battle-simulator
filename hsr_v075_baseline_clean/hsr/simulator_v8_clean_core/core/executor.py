from __future__ import annotations

from .model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    JSONValue,
    Mutation,
)
from .reducer import MutationReducer
from .settlement import SettlementRecord
from ..rules.rulebook import RuleBook
from ..systems.resource import ResourcePlan, ResourceSystem
from ..systems.target import TargetSystem
from ..systems.timeline import TimelinePlan, TimelineSystem


class CombatExecutor:
    """v8 action executor boundary."""

    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.reducer = MutationReducer()
        self.resources = ResourceSystem()
        self.targets = TargetSystem()
        self.timeline = TimelineSystem()

    def execute(self, command: ActionCommand, state: BattleState) -> tuple[BattleState, BattleTransition]:
        before = state.snapshot()
        action_event = GameEvent(
            "action.requested",
            source_id=command.actor_id,
            event_id=f"event:{state.event_index + 1}:action_requested",
            window="action_request",
            process_only=True,
            payload={"action_id": command.action_id, "source": command.source},
        )
        timeline_result = self.timeline.open_action(
            state,
            command.actor_id,
            TimelinePlan(
                reset_actor_av=_metadata_bool(command.metadata, "reset_actor_av", False),
                source="combat_executor.timeline",
            ),
        )
        target_result = self.targets.resolve_explicit_targets(state, command.actor_id, command.target_ids)
        resource_result = self.resources.plan_action_resources(
            state,
            command.actor_id,
            ResourcePlan(
                skill_point_delta=_metadata_int(command.metadata, "skill_point_delta", 0),
                energy_gain=_metadata_float(command.metadata, "energy_gain", 0.0),
                source="combat_executor.resources",
            ),
        )
        events = (action_event, *timeline_result.events)
        timeline_mutations = timeline_result.mutations
        resource_mutations = resource_result.mutations
        mutations = (*timeline_mutations, *resource_mutations)
        after_state = self.reducer.apply_all(state, mutations)

        records: list[dict[str, JSONValue]] = [
            SettlementRecord(
                record_type="process",
                source="combat_executor",
                process_only=True,
                payload={
                    "event": "action.requested",
                    "rule_known": self.rules.has_action(command.action_id),
                },
                trace={"event_id": action_event.event_id},
            ).to_json(),
            SettlementRecord(
                record_type="target_resolution",
                source="target_system",
                process_only=True,
                payload=target_result.resolution.to_json(),
                trace={"errors": list(target_result.errors)},
            ).to_json(),
        ]
        records.extend(_mutation_record("timeline", mutation) for mutation in timeline_mutations)
        records.extend(_mutation_record("resource", mutation) for mutation in resource_mutations)
        if not target_result.ok:
            records.append(
                SettlementRecord(
                    record_type="target_error",
                    source="target_system",
                    process_only=True,
                    payload={"errors": list(target_result.errors)},
                ).to_json()
            )
        if not resource_result.ok:
            records.append(
                SettlementRecord(
                    record_type="resource_error",
                    source="resource_system",
                    process_only=True,
                    payload={"errors": list(resource_result.errors)},
                ).to_json()
            )

        settlement = ActionSettlement(
            action_id=command.action_id,
            actor_id=command.actor_id,
            target_ids=command.target_ids,
            records=tuple(records),
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
            target_resolution=target_result.resolution,
            rng_events=(),
            coverage={
                "executor": "v0_205_action_prelude",
                "target_ok": target_result.ok,
                "resource_ok": resource_result.ok,
                "timeline_mutation_count": len(timeline_mutations),
                "resource_mutation_count": len(resource_mutations),
            },
        )
        return after_state, transition


def _mutation_record(record_type: str, mutation: Mutation) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type=record_type,
        source=mutation.source,
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={
            "path": list(mutation.path),
            "before": mutation.before,
            "after": mutation.after,
            "reason": mutation.reason,
            "metadata": mutation.metadata,
        },
    ).to_json()


def _metadata_bool(metadata: dict[str, JSONValue], key: str, default: bool) -> bool:
    value = metadata.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _metadata_int(metadata: dict[str, JSONValue], key: str, default: int) -> int:
    value = metadata.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return int(value)
    return default


def _metadata_float(metadata: dict[str, JSONValue], key: str, default: float) -> float:
    value = metadata.get(key, default)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, str)):
        return float(value)
    return default
