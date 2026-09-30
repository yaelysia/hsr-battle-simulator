"""Application boundary for local, externally controlled battle sessions."""
from __future__ import annotations

import json
from typing import Any

from .builds.manifest import canonical_ir_fingerprint
from .core.model import ActionCommand
from .core.transition_consumer import transition_successor_state
from .rules.rulebook import RuleBook
from .scenarios import ScenarioLoader, ScenarioStateBuilder
from .systems.decision import CurrentDecision, DecisionSystem
from .systems.scheduler import SchedulerStepResult


SESSION_SCHEMA = "hsr_battle_session_v1"


def command_from_json(value: dict[str, Any]) -> ActionCommand:
    if not isinstance(value, dict):
        raise TypeError("command must be an object")
    allowed = {"actor_id", "action_id", "action_level", "target_ids", "source", "queue_name", "metadata"}
    if set(value) - allowed:
        raise ValueError("command contains unknown fields")
    targets = value.get("target_ids", [])
    if not isinstance(targets, list):
        raise TypeError("command.target_ids must be an array")
    return ActionCommand(
        actor_id=value["actor_id"], action_id=value["action_id"],
        action_level=value["action_level"], target_ids=tuple(targets),
        source=value.get("source", "manual"), queue_name=value.get("queue_name"),
        metadata=value.get("metadata", {}),
    )


def command_to_json(command: ActionCommand) -> dict[str, Any]:
    return {
        "actor_id": command.actor_id, "action_id": command.action_id,
        "action_level": command.action_level, "target_ids": list(command.target_ids),
        "source": command.source, "queue_name": command.queue_name,
        "metadata": command.metadata,
    }


class BattleSession:
    """Own session history; all combat decisions and mutations stay in the core."""

    def __init__(self, rules: RuleBook, scenario_data: dict[str, Any]):
        self.rules = rules
        self.scenario_data = json.loads(json.dumps(scenario_data, allow_nan=False))
        self.scenario = ScenarioLoader().load_dict(self.scenario_data)
        self.build = ScenarioStateBuilder(rules).build(self.scenario)
        if self.build.blocked_setup:
            raise ValueError(f"battle setup blocked: {self.build.blocked_setup}")
        self.state = self.build.state
        self.decisions = DecisionSystem(rules)
        self.operations: list[dict[str, Any]] = []
        self.rules_fingerprint = canonical_ir_fingerprint(rules.ir)
        self.initial_snapshot = self.state.snapshot().to_json()
        self.setup_audit = {
            "records": list(self.build.setup_records),
            "mutations": [item.to_json() for item in self.build.setup_mutations],
            "events": [item.to_json() for item in self.build.setup_events],
            "rng_events": [item.to_json() for item in self.build.setup_rng_events],
            "source_traces": list(self.build.source_traces),
        }
        timeline = self.scenario.battle_setup.timeline
        explicit = tuple(sorted(set(timeline.action_values) | set(timeline.explicit_overrides))) if timeline else ()
        initialized = self.decisions.scheduler.initialize_timeline(self.state, explicit_overrides=explicit)
        self.initialization = initialized.transition.to_json()
        if not initialized.transition.outcome.successor_eligible:
            raise ValueError(f"timeline initialization blocked: {initialized.transition.outcome.reason_codes}")
        self._accept(initialized)

    @property
    def outcome(self) -> str:
        return str(self.state.global_flags.get("battle_outcome") or "")

    def _accept(self, result: SchedulerStepResult) -> None:
        self.state = transition_successor_state(
            self.state, result.after_state, result.transition.to_json(),
        )

    def advance(self) -> CurrentDecision:
        result = self.decisions.advance_to_decision(self.state)
        self.state = result.after_state
        self.operations.append({
            "kind": "advance",
            "decision_id": result.decision.token.decision_id if result.decision.token else None,
            "blocked_reason": result.blocked_reason,
            "transitions": [transition.to_json() for transition in result.transitions],
        })
        return result.decision

    def submit(self, command: ActionCommand) -> SchedulerStepResult:
        decision = self.decisions.current_decision(self.state)
        if not decision.ready or decision.token is None:
            result = self.decisions.scheduler.reject_decision_submission(
                self.state, decision.blocked_reason or "decision_not_ready",
                {"command": command_to_json(command)},
            )
        else:
            result = self.decisions.submit(self.state, decision.token, command)
        self._accept(result)
        self.operations.append({
            "kind": "submit", "command": command_to_json(command),
            "transition": result.transition.to_json(),
        })
        return result

    def archive(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_SCHEMA,
            "canonical_ir_fingerprint": self.rules_fingerprint,
            "scenario": self.scenario_data,
            "initial_snapshot": self.initial_snapshot,
            "setup_audit": self.setup_audit,
            "initialization": self.initialization,
            "operations": self.operations,
            "final_snapshot": self.state.snapshot().to_json(),
            "outcome": self.outcome,
        }
