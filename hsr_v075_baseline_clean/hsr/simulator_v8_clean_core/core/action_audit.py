from __future__ import annotations

from .action_plan import ActionExecutionPlan
from .model import ActionCommand, GameEvent, JSONValue
from .settlement import SettlementRecord
from ..rules.rulebook import RuleBook
from ..systems.action_selection import ActionTargetImpactResult, ActionTargetSelectionContext


def action_source_records(
    rules: RuleBook,
    command: ActionCommand,
    action_event: GameEvent,
    target_selection_context: ActionTargetSelectionContext,
    target_result: ActionTargetImpactResult,
    action_execution_plan: ActionExecutionPlan,
) -> list[dict[str, JSONValue]]:
    """Observe formal inputs and results; never decide or mutate the action."""
    action_definition = rules.require_action_definition(command.action_id, command.action_level)
    action_definition_trace = rules.action_definition_source_trace(command.action_id, command.action_level) or {}
    action_binding = rules.action_ability_binding(command.action_id, command.action_level)
    ability_phases = rules.ability_phases_for_action(command.action_id, command.action_level)
    ability_tasks = rules.ability_tasks_for_action(command.action_id, command.action_level)
    action_event_ir = rules.require_action_event(command.action_id, command.action_level)
    hit_profiles = rules.hit_profiles_for_action(command.action_id, command.action_level)
    damage_emissions = rules.damage_emissions_for_action(command.action_id, command.action_level)
    toughness_emissions = rules.toughness_emissions_for_action(command.action_id, command.action_level)
    return [
        SettlementRecord(
            record_type="process",
            source="combat_executor",
            process_only=True,
            payload={
                "event": "action.requested",
                "rule_known": rules.has_action(command.action_id),
                "definition_known": True,
            },
            trace={"event_id": action_event.event_id},
        ).to_json(),
        SettlementRecord(
            record_type="action_target_selection_context",
            source="action_target_selection_system",
            process_only=True,
            payload={
                "selection_context": target_selection_context.to_json(),
                "impact": target_result.to_json(),
            },
            trace={
                "action_target_contract": (
                    rules.action_target_contract(
                        command.action_id,
                        command.action_level,
                    ).value.to_json()
                    if rules.action_target_contract(
                        command.action_id,
                        command.action_level,
                    ).value is not None
                    else {}
                ),
            },
        ).to_json(),
        SettlementRecord(
            record_type="action_definition",
            source="rulebook",
            process_only=True,
            payload=action_definition.to_json(),
            trace=action_definition_trace,
        ).to_json(),
        SettlementRecord(
            record_type="action_ability_binding",
            source="rulebook",
            process_only=True,
            payload=action_binding.to_json()
            if action_binding
            else {
                "action_id": command.action_id,
                "action_level": command.action_level,
                "coverage_status": "blocked",
                "blocked_reason": "action_ability_binding_missing",
            },
            trace=action_binding.source.to_json() if action_binding else action_definition.source.to_json(),
        ).to_json(),
        SettlementRecord(
            record_type="ability_phase_graph",
            source="rulebook",
            process_only=True,
            payload={
                "binding_id": action_binding.binding_id if action_binding else "",
                "phase_count": len(ability_phases),
                "phases": [phase.to_json() for phase in ability_phases],
            },
            trace=action_binding.source.to_json() if action_binding else action_definition.source.to_json(),
        ).to_json(),
        SettlementRecord(
            record_type="ability_task_graph",
            source="rulebook",
            process_only=True,
            payload={
                "binding_id": action_binding.binding_id if action_binding else "",
                "task_count": len(ability_tasks),
                "tasks": [task.to_json() for task in ability_tasks],
            },
            trace=action_binding.source.to_json() if action_binding else action_definition.source.to_json(),
        ).to_json(),
        SettlementRecord(
            record_type="action_event_ir",
            source="rulebook",
            process_only=True,
            payload=action_event_ir.to_json(),
            trace=action_event_ir.source.to_json(),
        ).to_json(),
        SettlementRecord(
            record_type="hit_profiles",
            source="rulebook",
            process_only=True,
            payload={"profiles": [profile.to_json() for profile in hit_profiles]},
            trace={"definition_id": action_definition.definition_id},
        ).to_json(),
        SettlementRecord(
            record_type="damage_emissions",
            source="rulebook",
            process_only=True,
            payload={"emissions": [emission.to_json() for emission in damage_emissions]},
            trace={"definition_id": action_definition.definition_id},
        ).to_json(),
        SettlementRecord(
            record_type="toughness_emissions",
            source="rulebook",
            process_only=True,
            payload={"emissions": [emission.to_json() for emission in toughness_emissions]},
            trace={"definition_id": action_definition.definition_id},
        ).to_json(),
        SettlementRecord(
            record_type="action_execution_plan",
            source="combat_executor",
            process_only=True,
            payload=action_execution_plan.to_json(),
            trace={"definition_id": action_definition.definition_id},
        ).to_json(),
    ]
