"""Application boundary for local, externally controlled battle sessions."""
from __future__ import annotations

import json
import os
from typing import Any

from .builds.manifest import canonical_ir_fingerprint
from .core.audit_policy import diagnostic_detail
from .core.model import ActionCommand, BattleState
from .core.transition_consumer import transition_successor_state
from .rules.rulebook import RuleBook
from .scenarios import ScenarioLoader, ScenarioStateBuilder
from .systems.decision import CurrentDecision, DecisionSystem
from .systems.scheduler import SchedulerStepResult


SESSION_SCHEMA = "hsr_battle_session_v3"


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

    def __init__(
        self, rules: RuleBook, scenario_data: dict[str, Any], *, diagnostics: str | None = None,
    ):
        self.diagnostics = diagnostics if diagnostics is not None else (
            "full" if os.environ.get("HSR_DETAILED_DIAGNOSTICS") == "1" else "compact"
        )
        if not isinstance(self.diagnostics, str) or self.diagnostics not in {"compact", "full"}:
            raise ValueError("diagnostics must be compact or full")
        with diagnostic_detail(self.diagnostics == "full"):
            self._initialize(rules, scenario_data)
        self._history_states: dict[int, BattleState] | None = {0: self.state}

    def _initialize(self, rules: RuleBook, scenario_data: dict[str, Any]) -> None:
        self.rules = rules
        self.scenario_data = json.loads(json.dumps(scenario_data, allow_nan=False))
        self.scenario = ScenarioLoader().load_dict(self.scenario_data)
        self.build = ScenarioStateBuilder(rules).build(self.scenario)
        if self.build.blocked_setup:
            raise ValueError(f"battle setup blocked: {self.build.blocked_setup}")
        self.state = self.build.state
        self.decisions = DecisionSystem(rules)
        self.operations: list[dict[str, Any]] = []
        # The builder derived this manifest from the same RuleBook, so its rule
        # identity already covers the same IR. Component-only scenarios have no
        # formal build manifest and keep the direct fingerprint path.
        manifest = self.build.build_manifest
        self.rules_fingerprint = (
            manifest.rule_identity.canonical_ir_fingerprint
            if manifest is not None
            else canonical_ir_fingerprint(rules.ir)
        )
        self.initial_snapshot = self.state.snapshot().to_json(detach=False)
        self.setup_audit = {
            # Mounted content-processor identities (M1-3): recorded for replay
            # version drift detection; sorted by content_id for determinism.
            # Empty when no processor is mounted, leaving archives unchanged.
            "records": list(self.build.setup_records) + [
                {"record_type": "content_processor_mount", "source": "content_processors",
                 "process_only": True, "payload": {"content_id": m.content_id, "version": m.version}}
                for m in sorted(rules.content_processors, key=lambda item: item.content_id)
            ],
            "mutations": [item.to_json(detach=False) for item in self.build.setup_mutations],
            "events": [item.to_json() for item in self.build.setup_events],
            "rng_events": [item.to_json() for item in self.build.setup_rng_events],
            "source_traces": list(self.build.source_traces),
        }
        timeline = self.scenario.battle_setup.timeline
        explicit = tuple(sorted(set(timeline.action_values) | set(timeline.explicit_overrides))) if timeline else ()
        initialized = self.decisions.scheduler.initialize_timeline(self.state, explicit_overrides=explicit)
        self.initialization = initialized.transition.to_json(detach=False)
        if not initialized.transition.outcome.successor_eligible:
            raise ValueError(f"timeline initialization blocked: {initialized.transition.outcome.reason_codes}")
        self._accept(initialized)

    @property
    def outcome(self) -> str:
        return str(self.state.global_flags.get("battle_outcome") or "")

    def _accept(self, result: SchedulerStepResult) -> None:
        self.state = transition_successor_state(
            self.state, result.after_state, {"outcome": result.transition.outcome.to_json()},
        )

    def advance(self) -> CurrentDecision:
        decision, _ = self.advance_with_transitions()
        return decision

    def advance_with_transitions(self) -> tuple[CurrentDecision, tuple[Any, ...]]:
        """Advance and expose the typed internal transitions for native audit."""

        with diagnostic_detail(self.diagnostics == "full"):
            result = self.decisions.advance_to_decision(self.state)
            self.state = result.after_state
            self.operations.append({
                "kind": "advance",
                "decision_id": result.decision.token.decision_id if result.decision.token else None,
                "blocked_reason": result.blocked_reason,
                "transitions": [transition.to_json(detach=False) for transition in result.transitions],
            })
        if self._history_states is not None:
            self._history_states[len(self.operations)] = self.state
        return result.decision, tuple(result.transitions)

    def submit(self, command: ActionCommand) -> SchedulerStepResult:
        with diagnostic_detail(self.diagnostics == "full"):
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
                "transition": result.transition.to_json(detach=False),
            })
        if self._history_states is not None:
            self._history_states[len(self.operations)] = self.state
        return result

    def fork(self, operation_count: int | None = None) -> "BattleSession":
        """Branch from a retained operation boundary without replay.

        The live state was produced by this kernel, so it needs no
        re-verification: immutable state and setup evidence are shared, and
        the history prefix is copied. Archives of the fork still replay-verify
        from entry. External archives must first pass ``restore_session``;
        their verified operation boundaries are then available for branching.
        """
        count = len(self.operations) if operation_count is None else operation_count
        if type(count) is not int or not 0 <= count <= len(self.operations):
            raise ValueError("fork operation count is outside session history")
        state = self.state if count == len(self.operations) else (self._history_states or {}).get(count)
        if state is None:
            raise ValueError("fork operation boundary state was not retained")
        clone = object.__new__(BattleSession)
        clone.rules = self.rules
        clone.scenario_data = self.scenario_data
        clone.scenario = self.scenario
        clone.build = self.build
        clone.state = state
        clone.diagnostics = self.diagnostics
        clone.decisions = DecisionSystem(self.rules)
        clone.operations = list(self.operations[:count])
        clone._history_states = {i: value for i, value in (self._history_states or {}).items() if i <= count}
        clone.rules_fingerprint = self.rules_fingerprint
        clone.initial_snapshot = self.initial_snapshot
        clone.setup_audit = self.setup_audit
        clone.initialization = self.initialization
        return clone

    def archive(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_SCHEMA,
            "diagnostics": self.diagnostics,
            "canonical_ir_fingerprint": self.rules_fingerprint,
            "scenario": self.scenario_data,
            "initial_snapshot": self.initial_snapshot,
            "setup_audit": self.setup_audit,
            "initialization": self.initialization,
            "operations": self.operations,
            "final_snapshot": self.state.snapshot().to_json(detach=False),
            "outcome": self.outcome,
        }
