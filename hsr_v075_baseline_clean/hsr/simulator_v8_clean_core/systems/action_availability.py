from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.model import ActionCommand, BattleState, JSONValue, UnitState
from ..rules.ir import ActionDefinitionIR, ActionEventIR, QueueResolutionIR
from ..rules.rulebook import RuleBook
from .action_preflight import (
    action_binding_blocked_reason,
    action_event_blocked_reason,
    action_resource_plan,
    combined_blocked_reason,
    target_policy_for_action,
)
from .enemy_action import EnemyActionCandidate, EnemyActionSystem
from .queue import QueueDrainPlan, QueueSystem
from .resource import ResourceSystem
from .scheduler import (
    _queue_entry_resource_policy,
    _resolution_for_drain_plan,
    queue_plan_requires_external_command,
    select_next_queue_drain_plan,
)
from .status import status_control_gate_for_actor
from .summon import SUMMON_RUNTIME_SCHEMA_VERSION
from .target import TargetEnumerationResult, TargetSystem
from .timeline import TimelineSystem
from .unit_lifecycle import UnitLifecycleSystem
from .wave import WaveSystem


ACTION_AVAILABILITY_SCHEMA_VERSION = "p1_0_action_availability_v1"

ActionAvailabilityMode = Literal[
    "queued_mandatory",
    "queued_selectable",
    "external_selectable",
    "scheduler_required",
    "wave_transition_available",
    "blocked",
    "idle",
]


@dataclass(frozen=True)
class BlockedActionReason:
    reason: str
    scope: str
    actor_id: str = ""
    actor_side: str = ""
    action_id: str = ""
    action_level: int = 0
    queue_name: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "reason": self.reason,
            "scope": self.scope,
            "actor_id": self.actor_id,
            "actor_side": self.actor_side,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "queue_name": self.queue_name,
            "metadata": self.metadata,
            "source_trace": self.source_trace,
        }


@dataclass(frozen=True)
class QueueAvailability:
    has_queue_entries: bool
    selected_plan: dict[str, JSONValue] = field(default_factory=dict)
    mode: Literal["mandatory", "selectable", "blocked", "none"] = "none"
    queue_name: str = ""
    queue_entry_id: str = ""
    window_family: str = ""
    priority_key: str = ""
    priority_value: float | None = None
    drain_order: int | None = None
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "has_queue_entries": self.has_queue_entries,
            "selected_plan": self.selected_plan,
            "mode": self.mode,
            "queue_name": self.queue_name,
            "queue_entry_id": self.queue_entry_id,
            "window_family": self.window_family,
            "priority_key": self.priority_key,
            "priority_value": self.priority_value,
            "drain_order": self.drain_order,
            "blocked_reason": self.blocked_reason,
            "source_trace": self.source_trace,
        }


@dataclass(frozen=True)
class ActorAvailability:
    actor_id: str
    actor_side: str
    turn_state: Literal["active", "preview_next_actor", "blocked"]
    timeline_plan: dict[str, JSONValue] = field(default_factory=dict)
    can_accept_external_command: bool = False
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "actor_id": self.actor_id,
            "actor_side": self.actor_side,
            "turn_state": self.turn_state,
            "timeline_plan": self.timeline_plan,
            "can_accept_external_command": self.can_accept_external_command,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SelectableWindow:
    window_id: str
    window_kind: str
    control: Literal["selectable"] = "selectable"
    actor_id: str = ""
    queue_name: str = ""
    queue_entry_id: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "window_id": self.window_id,
            "window_kind": self.window_kind,
            "control": self.control,
            "actor_id": self.actor_id,
            "queue_name": self.queue_name,
            "queue_entry_id": self.queue_entry_id,
            "metadata": self.metadata,
            "source_trace": self.source_trace,
        }


@dataclass(frozen=True)
class ActionChoice:
    choice_id: str
    choice_kind: Literal["normal_action", "enemy_fixed_sequence", "queue_action", "ultimate_window", "summon_action"]
    control: Literal["external", "mandatory", "selectable"]
    actor_id: str
    actor_side: str
    action_id: str
    action_level: int
    command_template: dict[str, JSONValue]
    auto_target_ids: tuple[str, ...] = ()
    selectable_target_ids: tuple[str, ...] = ()
    target_policy: dict[str, JSONValue] = field(default_factory=dict)
    target_status: Literal["ok", "blocked"] = "blocked"
    target_blocked_reason: str = ""
    resource_status: Literal["ok", "blocked", "not_checked"] = "not_checked"
    resource_blocked_reason: str = ""
    coverage_status: str = "blocked"
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "choice_id": self.choice_id,
            "choice_kind": self.choice_kind,
            "control": self.control,
            "actor_id": self.actor_id,
            "actor_side": self.actor_side,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "command_template": self.command_template,
            "auto_target_ids": list(self.auto_target_ids),
            "selectable_target_ids": list(self.selectable_target_ids),
            "target_policy": self.target_policy,
            "target_status": self.target_status,
            "target_blocked_reason": self.target_blocked_reason,
            "resource_status": self.resource_status,
            "resource_blocked_reason": self.resource_blocked_reason,
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "source_trace": self.source_trace,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ActionAvailabilityView:
    schema_version: str
    mode: ActionAvailabilityMode
    state_phase: str
    current_window: str
    turn_owner_id: str
    requires_scheduler_step: bool
    ordinary_input_blocked: bool
    ordinary_input_blocked_reason: str = ""
    queue: QueueAvailability | None = None
    actor: ActorAvailability | None = None
    choices: tuple[ActionChoice, ...] = ()
    selectable_windows: tuple[SelectableWindow, ...] = ()
    blocked: tuple[BlockedActionReason, ...] = ()
    coverage: dict[str, JSONValue] = field(default_factory=dict)
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "state_phase": self.state_phase,
            "current_window": self.current_window,
            "turn_owner_id": self.turn_owner_id,
            "requires_scheduler_step": self.requires_scheduler_step,
            "ordinary_input_blocked": self.ordinary_input_blocked,
            "ordinary_input_blocked_reason": self.ordinary_input_blocked_reason,
            "queue": self.queue.to_json() if self.queue is not None else None,
            "actor": self.actor.to_json() if self.actor is not None else None,
            "choices": [choice.to_json() for choice in self.choices],
            "selectable_windows": [window.to_json() for window in self.selectable_windows],
            "blocked": [reason.to_json() for reason in self.blocked],
            "coverage": self.coverage,
            "source_trace": self.source_trace,
        }


class ActionAvailabilitySystem:
    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.timeline = TimelineSystem()
        self.queue = QueueSystem()
        self.enemy_actions = EnemyActionSystem(rules)
        self.targets = TargetSystem()
        self.resources = ResourceSystem()
        self.lifecycle = UnitLifecycleSystem()
        self.wave = WaveSystem(rules)

    def view(self, state: BattleState) -> ActionAvailabilityView:
        state_phase = str(state.global_flags.get("phase", "setup"))
        current_window = str(state.global_flags.get("current_window", "idle"))
        turn_owner_id = str(state.global_flags.get("turn_owner_id") or "")
        battle_outcome = state.global_flags.get("battle_outcome")
        if state_phase == "ended" or isinstance(battle_outcome, str):
            reason = f"battle_ended:{battle_outcome or 'unknown'}"
            blocked = (
                BlockedActionReason(
                    reason=reason,
                    scope="battle",
                    metadata={"battle_outcome": str(battle_outcome or "")},
                ),
            )
            return ActionAvailabilityView(
                schema_version=ACTION_AVAILABILITY_SCHEMA_VERSION,
                mode="blocked",
                state_phase=state_phase,
                current_window=current_window,
                turn_owner_id=turn_owner_id,
                requires_scheduler_step=False,
                ordinary_input_blocked=True,
                ordinary_input_blocked_reason=reason,
                blocked=blocked,
                coverage={"battle_outcome": str(battle_outcome or ""), "selection_controller": "battle_ended"},
            )
        plan = select_next_queue_drain_plan(self.rules, self.queue, state)
        resolution = _resolution_for_drain_plan(self.rules, state, plan) if plan is not None and plan.ok else None
        queue, queue_blocked = self._queue_availability(state, plan, resolution)
        if queue.mode != "none":
            choices = self._queue_choices(state, plan, resolution) if plan is not None else ()
            selectable_windows = self._selectable_windows(plan, resolution) if plan is not None else ()
            blocked = queue_blocked
            mode: ActionAvailabilityMode
            if queue.mode == "blocked":
                mode = "blocked"
            elif queue.mode == "selectable":
                mode = "queued_selectable"
            else:
                mode = "queued_mandatory"
            return ActionAvailabilityView(
                schema_version=ACTION_AVAILABILITY_SCHEMA_VERSION,
                mode=mode,
                state_phase=state_phase,
                current_window=current_window,
                turn_owner_id=turn_owner_id,
                requires_scheduler_step=True,
                ordinary_input_blocked=True,
                ordinary_input_blocked_reason=queue.blocked_reason or f"queue_{queue.mode}_priority",
                queue=queue,
                choices=choices,
                selectable_windows=selectable_windows,
                blocked=blocked,
                coverage={
                    "queue_mode": queue.mode,
                    "choice_count": len(choices),
                    "blocked_count": len(blocked),
                    "selection_controller": "external" if queue.mode == "selectable" else "scheduler_mandatory",
                },
                source_trace=queue.source_trace,
            )

        wave_plan = self.wave.plan_transition(state)
        if wave_plan.status in {"advance_to_next_wave", "battle_victory", "battle_defeat"}:
            blocked = (
                BlockedActionReason(
                    reason="wave_transition_required",
                    scope="wave",
                    metadata={"wave_transition_plan": wave_plan.to_json()},
                    source_trace=wave_plan.source_trace,
                ),
            )
            return ActionAvailabilityView(
                schema_version=ACTION_AVAILABILITY_SCHEMA_VERSION,
                mode="wave_transition_available",
                state_phase=state_phase,
                current_window=current_window,
                turn_owner_id=turn_owner_id,
                requires_scheduler_step=True,
                ordinary_input_blocked=True,
                ordinary_input_blocked_reason="wave_transition_required",
                queue=queue,
                blocked=blocked,
                coverage={
                    "wave_transition": wave_plan.to_json(),
                    "selection_controller": "scheduler_wave_transition",
                },
                source_trace=wave_plan.source_trace,
            )
        if wave_plan.status == "blocked" and wave_plan.blocked_reason != "wave_runtime_not_configured":
            blocked = (
                BlockedActionReason(
                    reason=wave_plan.blocked_reason or "wave_transition_blocked",
                    scope="wave",
                    metadata={"wave_transition_plan": wave_plan.to_json()},
                    source_trace=wave_plan.source_trace,
                ),
            )
            return self._blocked_view(state, state_phase, current_window, turn_owner_id, queue, blocked)

        pending_turn_end = state.global_flags.get("pending_turn_end")
        if isinstance(pending_turn_end, dict):
            blocked = (
                BlockedActionReason(
                    reason="pending_turn_end_requires_scheduler_step",
                    scope="scheduler",
                    actor_id=str(pending_turn_end.get("actor_id") or ""),
                    metadata={"pending_turn_end": pending_turn_end},
                ),
            )
            return ActionAvailabilityView(
                schema_version=ACTION_AVAILABILITY_SCHEMA_VERSION,
                mode="scheduler_required",
                state_phase=state_phase,
                current_window=current_window,
                turn_owner_id=turn_owner_id,
                requires_scheduler_step=True,
                ordinary_input_blocked=True,
                ordinary_input_blocked_reason="pending_turn_end_requires_scheduler_step",
                queue=queue,
                blocked=blocked,
                coverage={"scheduler_step": "complete_deferred_turn_lifecycle"},
            )

        if turn_owner_id:
            actor = state.units.get(turn_owner_id)
            if actor is None:
                blocked = (
                    BlockedActionReason(
                        reason="active_turn_actor_missing",
                        scope="actor",
                        actor_id=turn_owner_id,
                    ),
                )
                return self._blocked_view(
                    state,
                    state_phase,
                    current_window,
                    turn_owner_id,
                    queue,
                    blocked,
                    actor=ActorAvailability(turn_owner_id, "", "blocked", blocked_reason="active_turn_actor_missing"),
                )
            actor_ok, actor_reason = self.lifecycle.can_act(state, turn_owner_id)
            if not actor_ok:
                blocked_reason = f"actor_{actor_reason}"
                blocked = (
                    BlockedActionReason(
                        reason=blocked_reason,
                        scope="actor",
                        actor_id=turn_owner_id,
                        actor_side=actor.side,
                        metadata={"lifecycle": self.lifecycle.view(state, turn_owner_id).to_json()},
                    ),
                )
                return self._blocked_view(
                    state,
                    state_phase,
                    current_window,
                    turn_owner_id,
                    queue,
                    blocked,
                    actor=ActorAvailability(
                        turn_owner_id,
                        actor.side,
                        "blocked",
                        blocked_reason=blocked_reason,
                    ),
                )
            control_gate = _control_gate_for_actor(state, actor)
            if control_gate is not None:
                blocked_reason = control_gate.reason
                blocked = (control_gate,)
                return self._blocked_view(
                    state,
                    state_phase,
                    current_window,
                    turn_owner_id,
                    queue,
                    blocked,
                    actor=ActorAvailability(
                        turn_owner_id,
                        actor.side,
                        "blocked",
                        blocked_reason=blocked_reason,
                    ),
                )
            actor_availability = ActorAvailability(
                actor_id=actor.unit_id,
                actor_side=actor.side,
                turn_state="active",
                timeline_plan={},
                can_accept_external_command=True,
            )
            choices, blocked = self._choices_for_actor(state, actor)
            mode: ActionAvailabilityMode = "external_selectable" if choices else "blocked"
            return ActionAvailabilityView(
                schema_version=ACTION_AVAILABILITY_SCHEMA_VERSION,
                mode=mode,
                state_phase=state_phase,
                current_window=current_window,
                turn_owner_id=turn_owner_id,
                requires_scheduler_step=False,
                ordinary_input_blocked=False if choices else True,
                ordinary_input_blocked_reason="" if choices else "no_executable_actor_choice",
                queue=queue,
                actor=actor_availability,
                choices=choices,
                blocked=blocked,
                coverage={
                    "actor_side": actor.side,
                    "choice_count": len(choices),
                    "blocked_count": len(blocked),
                    "selection_controller": "external",
                },
            )

        timeline_rule = self.rules.default_timeline_rule()
        timeline_plan = self.timeline.plan_next_actor(state, timeline_rule)
        if not timeline_plan.ok:
            blocked = (
                BlockedActionReason(
                    reason=timeline_plan.blocked_reason or "timeline_plan_blocked",
                    scope="timeline",
                    metadata={"timeline_plan": timeline_plan.to_json()},
                    source_trace=timeline_plan.source_trace,
                ),
            )
            return self._blocked_view(state, state_phase, current_window, "", queue, blocked)

        actor = state.units.get(timeline_plan.actor_id)
        actor_view = ActorAvailability(
            actor_id=timeline_plan.actor_id,
            actor_side=actor.side if actor is not None else "",
            turn_state="preview_next_actor",
            timeline_plan=timeline_plan.to_json(),
            can_accept_external_command=False,
        )
        return ActionAvailabilityView(
            schema_version=ACTION_AVAILABILITY_SCHEMA_VERSION,
            mode="scheduler_required",
            state_phase=state_phase,
            current_window=current_window,
            turn_owner_id="",
            requires_scheduler_step=True,
            ordinary_input_blocked=True,
            ordinary_input_blocked_reason="turn_begin_requires_scheduler_step",
            queue=queue,
            actor=actor_view,
            coverage={
                "scheduler_step": "turn_begin_required",
                "timeline_plan": timeline_plan.to_json(),
                "selection_controller": "external_after_turn_begin",
            },
            source_trace=timeline_plan.source_trace,
        )

    def _queue_availability(
        self,
        state: BattleState,
        plan: QueueDrainPlan | None,
        resolution: QueueResolutionIR | None,
    ) -> tuple[QueueAvailability, tuple[BlockedActionReason, ...]]:
        has_entries = any(bool(entries) for entries in state.queues.values())
        if plan is None:
            return QueueAvailability(has_queue_entries=has_entries), ()
        entry_id = str(plan.queue_entry.get("entry_id") or "")
        window = plan.queue_window or {}
        source_trace = plan.source_trace or {}
        blocked_reason = ""
        mode: Literal["mandatory", "selectable", "blocked", "none"]
        if not plan.ok:
            mode = "blocked"
            blocked_reason = plan.blocked_reason or "queue_drain_blocked"
        elif resolution is None:
            mode = "blocked"
            blocked_reason = "queue_resolution_missing"
        else:
            blocked_reason = self._queue_action_boundary_blocked_reason(state, plan, resolution)
            if blocked_reason:
                mode = "blocked"
            elif queue_plan_requires_external_command(plan, resolution):
                mode = "selectable"
            else:
                mode = "mandatory"
        queue = QueueAvailability(
            has_queue_entries=has_entries,
            selected_plan=plan.to_json(),
            mode=mode,
            queue_name=plan.queue_name,
            queue_entry_id=entry_id,
            window_family=str(window.get("window_family") or ""),
            priority_key=plan.priority_key,
            priority_value=plan.priority_value,
            drain_order=plan.drain_order,
            blocked_reason=blocked_reason,
            source_trace=source_trace,
        )
        if mode != "blocked":
            return queue, ()
        return queue, (
            BlockedActionReason(
                reason=blocked_reason,
                scope="queue",
                actor_id=str(plan.queue_entry.get("actor_id") or ""),
                queue_name=plan.queue_name,
                metadata={"drain_plan": plan.to_json(), "queue_resolution": resolution.to_json() if resolution else {}},
                source_trace=source_trace,
            ),
        )

    def _queue_action_boundary_blocked_reason(
        self,
        state: BattleState,
        plan: QueueDrainPlan,
        resolution: QueueResolutionIR,
    ) -> str:
        if resolution.resolved_kind not in {"action_definition", "extra_turn_action_choice"}:
            return ""
        actor_id = str(plan.queue_entry.get("actor_id") or "")
        if not actor_id or actor_id not in state.units:
            return "queue_action_actor_missing"
        actor_ok, actor_reason = self.lifecycle.can_act(state, actor_id)
        if not actor_ok:
            return f"queue_action_actor_{actor_reason}"
        control_gate = _control_gate_for_actor(state, state.units[actor_id])
        if control_gate is not None:
            return f"queue_action_actor_{control_gate.reason}"
        if resolution.resolved_kind == "extra_turn_action_choice" and not plan.resolved_action_id:
            return ""
        action_id = plan.resolved_action_id
        action_level = plan.resolved_action_level
        if not action_id or action_level is None:
            return "queue_action_resolution_missing"
        target_ids = tuple(str(item) for item in plan.queue_entry.get("target_ids", ()) if isinstance(item, str))
        if not target_ids:
            return "queue_action_target_missing"
        invalid_targets = tuple(
            target_id
            for target_id in target_ids
            if not self.lifecycle.can_target(state, target_id, allow_defeated=False)[0]
        )
        if invalid_targets:
            reasons = [
                f"{self.lifecycle.can_target(state, target_id, allow_defeated=False)[1]}:{target_id}"
                for target_id in invalid_targets
            ]
            return f"queue_action_target_lifecycle_blocked:{','.join(reasons)}"
        definition = self.rules.action_definition(action_id, action_level)
        if definition is None:
            return "queue_action_definition_missing"
        action_event = self.rules.action_event(action_id, action_level)
        if action_event is None:
            return "queue_action_event_missing"
        event_reason = self._action_event_admission_reason(action_event)
        if event_reason:
            return f"queue_action_event_not_admitted:{event_reason}"
        resource_policy = _queue_entry_resource_policy(plan)
        if resource_policy.get("ignore_skill_point_delta") is not True and definition.bp_need > state.skill_points:
            return "queue_action_resource_preflight_failed:insufficient_skill_points"
        if plan.queue_intent_id.startswith("manual_ultimate:"):
            actor = state.units[actor_id]
            if actor.max_energy <= 0 or actor.energy < actor.max_energy:
                return "manual_ultimate_energy_not_ready_at_drain"
        if (plan.queue_window or {}).get("ok") is not True:
            return str((plan.queue_window or {}).get("blocked_reason") or "queue_window_not_admitted")
        return ""

    def _queue_choices(
        self,
        state: BattleState,
        plan: QueueDrainPlan | None,
        resolution: QueueResolutionIR | None,
    ) -> tuple[ActionChoice, ...]:
        if plan is None or resolution is None or not plan.ok:
            return ()
        if resolution.resolved_kind not in {"action_definition", "extra_turn_action_choice"}:
            return ()
        actor_id = str(plan.queue_entry.get("actor_id") or "")
        actor = state.units.get(actor_id)
        actor_side = actor.side if actor is not None else ""
        action_id = plan.resolved_action_id or str(plan.queue_entry.get("action_or_ability_ref") or "")
        action_level = int(plan.resolved_action_level or 0)
        target_ids = tuple(str(item) for item in plan.queue_entry.get("target_ids", ()) if isinstance(item, str))
        boundary_reason = self._queue_action_boundary_blocked_reason(state, plan, resolution)
        if boundary_reason:
            return ()
        window_family = str((plan.queue_window or {}).get("window_family") or "")
        control: Literal["mandatory", "selectable"] = "selectable" if queue_plan_requires_external_command(plan, resolution) else "mandatory"
        kind: Literal["queue_action", "ultimate_window"] = "ultimate_window" if window_family == "ultimate" else "queue_action"
        resource_status: Literal["ok", "blocked", "not_checked"] = "not_checked" if not action_id or action_level <= 0 else "ok"
        return (
            ActionChoice(
                choice_id=_stable_choice_id(kind, actor_id, action_id, action_level, control, plan.queue_intent_id),
                choice_kind=kind,
                control=control,
                actor_id=actor_id,
                actor_side=actor_side,
                action_id=action_id,
                action_level=action_level,
                command_template=_command_template(
                    ActionCommand(
                        actor_id=actor_id,
                        action_id=action_id,
                        action_level=action_level,
                        target_ids=target_ids,
                        source="queue",
                        queue_name=plan.queue_name,
                        metadata={
                            "selection_controller": "external" if control == "selectable" else "mandatory",
                            "queue_intent_id": plan.queue_intent_id,
                            "queue_resolution_id": plan.queue_resolution_id,
                            "queue_entry_id": str(plan.queue_entry.get("entry_id") or ""),
                            "queue_window_plan": plan.queue_window or {},
                        },
                    )
                ),
                auto_target_ids=target_ids,
                selectable_target_ids=(),
                target_policy={"source": "queue_target_resolution", "queue_window_plan": plan.queue_window or {}},
                target_status="ok" if target_ids else "blocked",
                target_blocked_reason="" if target_ids else "queue_action_target_missing",
                resource_status=resource_status,
                coverage_status="executable" if action_id and action_level > 0 else "requires_external_selection",
                source_trace=plan.source_trace or {},
                metadata={"queue_resolution": resolution.to_json(), "drain_plan": plan.to_json()},
            ),
        )

    def _selectable_windows(
        self,
        plan: QueueDrainPlan | None,
        resolution: QueueResolutionIR | None,
    ) -> tuple[SelectableWindow, ...]:
        if plan is None or resolution is None or not plan.ok or not queue_plan_requires_external_command(plan, resolution):
            return ()
        window = plan.queue_window or {}
        return (
            SelectableWindow(
                window_id=str(window.get("queue_window_id") or plan.queue_intent_id),
                window_kind=str(window.get("window_family") or "unknown"),
                actor_id=str(plan.queue_entry.get("actor_id") or ""),
                queue_name=plan.queue_name,
                queue_entry_id=str(plan.queue_entry.get("entry_id") or ""),
                metadata={"drain_plan": plan.to_json(), "queue_resolution": resolution.to_json()},
                source_trace=plan.source_trace or {},
            ),
        )

    def _choices_for_actor(
        self,
        state: BattleState,
        actor: UnitState,
    ) -> tuple[tuple[ActionChoice, ...], tuple[BlockedActionReason, ...]]:
        if actor.side == "ally":
            return self._ally_choices(state, actor)
        if actor.side == "enemy":
            return self._enemy_choices(state, actor)
        if actor.side == "summon":
            return self._summon_choices(state, actor)
        return (), (
            BlockedActionReason(
                reason=f"unsupported_actor_side:{actor.side}",
                scope="actor",
                actor_id=actor.unit_id,
                actor_side=actor.side,
            ),
        )

    def _ally_choices(
        self,
        state: BattleState,
        actor: UnitState,
    ) -> tuple[tuple[ActionChoice, ...], tuple[BlockedActionReason, ...]]:
        action_set = self.rules.combatant_action_set(actor.template_id)
        if action_set is None:
            return (), (
                BlockedActionReason(
                    reason="combatant_action_set_missing",
                    scope="action_set",
                    actor_id=actor.unit_id,
                    actor_side=actor.side,
                    metadata={"entity_ref": actor.template_id},
                ),
            )
        if action_set.coverage_status != "executable":
            return (), (
                BlockedActionReason(
                    reason=action_set.blocked_reason or f"combatant_action_set_not_executable:{action_set.coverage_status}",
                    scope="action_set",
                    actor_id=actor.unit_id,
                    actor_side=actor.side,
                    metadata={"combatant_action_set": action_set.to_json()},
                    source_trace=action_set.source.to_json(),
                ),
            )
        choices: list[ActionChoice] = []
        blocked: list[BlockedActionReason] = []
        for skill_index, entry in _sorted_action_set_entries(action_set.skill_index_map):
            action_id = str(entry.get("action_ref") or "")
            level = _default_level(entry)
            reason = self._action_set_entry_blocked_reason(entry, action_id, level)
            if reason:
                blocked.append(
                    BlockedActionReason(
                        reason=reason,
                        scope="normal_action",
                        actor_id=actor.unit_id,
                        actor_side=actor.side,
                        action_id=action_id,
                        action_level=level,
                        metadata={"skill_index": skill_index, "action_set_entry": entry},
                        source_trace=action_set.source.to_json(),
                    )
                )
                continue
            choice, reason = self._normal_action_choice(
                state,
                actor,
                action_id,
                level,
                choice_kind="normal_action",
                source_trace={
                    "combatant_action_set": action_set.source.to_json(),
                    "combatant_action_set_id": action_set.combatant_action_set_id,
                    "skill_index": skill_index,
                    "action_set_entry": entry,
                },
                metadata={"skill_index": skill_index, "combatant_action_set_id": action_set.combatant_action_set_id},
            )
            if choice is not None:
                choices.append(choice)
            else:
                blocked.append(reason)
        return tuple(choices), tuple(blocked)

    def _summon_choices(
        self,
        state: BattleState,
        actor: UnitState,
    ) -> tuple[tuple[ActionChoice, ...], tuple[BlockedActionReason, ...]]:
        if actor.flags.get("timeline_admitted") is not True:
            return (), (
                BlockedActionReason(
                    reason="summon_timeline_not_admitted",
                    scope="summon_action",
                    actor_id=actor.unit_id,
                    actor_side=actor.side,
                    metadata={"timeline_admitted": actor.flags.get("timeline_admitted")},
                ),
                BlockedActionReason(
                    reason="summon_action_admission_missing",
                    scope="summon_action",
                    actor_id=actor.unit_id,
                    actor_side=actor.side,
                    metadata={"timeline_admitted": actor.flags.get("timeline_admitted")},
                ),
            )
        admission_blocker = _summon_action_admission_blocker(state, actor)
        if admission_blocker is not None:
            reason, metadata, source_trace = admission_blocker
            return (), (
                BlockedActionReason(
                    reason=reason,
                    scope="summon_action",
                    actor_id=actor.unit_id,
                    actor_side=actor.side,
                    metadata={
                        "timeline_admitted": actor.flags.get("timeline_admitted"),
                        "team_side": actor.flags.get("team_side"),
                        **metadata,
                    },
                    source_trace=source_trace,
                ),
            )
        action_set = self.rules.combatant_action_set(actor.template_id)
        if action_set is None:
            return (), (
                BlockedActionReason(
                    reason="summon_action_set_missing",
                    scope="summon_action",
                    actor_id=actor.unit_id,
                    actor_side=actor.side,
                    metadata={"entity_ref": actor.template_id},
                ),
            )
        choices: list[ActionChoice] = []
        blocked: list[BlockedActionReason] = []
        for skill_index, entry in _sorted_action_set_entries(action_set.skill_index_map):
            action_id = str(entry.get("action_ref") or "")
            level = _default_level(entry)
            reason = self._action_set_entry_blocked_reason(entry, action_id, level)
            if action_set.coverage_status != "executable":
                reason = action_set.blocked_reason or f"combatant_action_set_not_executable:{action_set.coverage_status}"
            if reason:
                blocked.append(
                    BlockedActionReason(
                        reason=reason,
                        scope="summon_action",
                        actor_id=actor.unit_id,
                        actor_side=actor.side,
                        action_id=action_id,
                        action_level=level,
                        metadata={"skill_index": skill_index, "action_set_entry": entry},
                        source_trace=action_set.source.to_json(),
                    )
                )
                continue
            choice, reason_record = self._normal_action_choice(
                state,
                actor,
                action_id,
                level,
                choice_kind="summon_action",
                source_trace={
                    "combatant_action_set": action_set.source.to_json(),
                    "combatant_action_set_id": action_set.combatant_action_set_id,
                    "skill_index": skill_index,
                    "action_set_entry": entry,
                    "summon_action_admission": dict(actor.flags.get("summon_action_admission", {}))
                    if isinstance(actor.flags.get("summon_action_admission"), dict)
                    else {},
                },
                metadata={
                    "skill_index": skill_index,
                    "combatant_action_set_id": action_set.combatant_action_set_id,
                    "summon_kind": str(actor.flags.get("summon_kind") or ""),
                    "team_side": str(actor.flags.get("team_side") or ""),
                },
            )
            if choice is not None:
                choices.append(choice)
            else:
                blocked.append(reason_record)
        return tuple(choices), tuple(blocked)

    def _enemy_choices(
        self,
        state: BattleState,
        actor: UnitState,
    ) -> tuple[tuple[ActionChoice, ...], tuple[BlockedActionReason, ...]]:
        candidate = self.enemy_actions.next_candidate(state, actor.unit_id)
        if candidate.status != "available":
            return (), (
                BlockedActionReason(
                    reason=candidate.blocked_reason or "enemy_action_candidate_blocked",
                    scope="enemy_fixed_sequence",
                    actor_id=actor.unit_id,
                    actor_side=actor.side,
                    action_id=candidate.action_ref,
                    action_level=candidate.action_level,
                    metadata={"enemy_action_candidate": candidate.to_json()},
                    source_trace=candidate.source_trace,
                ),
            )
        definition = self.rules.action_definition(candidate.action_ref, candidate.action_level)
        if definition is None:
            return (), (
                BlockedActionReason(
                    reason="enemy_action_definition_missing",
                    scope="enemy_fixed_sequence",
                    actor_id=actor.unit_id,
                    actor_side=actor.side,
                    action_id=candidate.action_ref,
                    action_level=candidate.action_level,
                    metadata={"enemy_action_candidate": candidate.to_json()},
                    source_trace=candidate.source_trace,
                ),
            )
        resource_status, resource_reason = self._resource_status(state, actor.unit_id, definition, {})
        if resource_status == "blocked":
            return (), (
                BlockedActionReason(
                    reason=resource_reason,
                    scope="enemy_fixed_sequence_resource",
                    actor_id=actor.unit_id,
                    actor_side=actor.side,
                    action_id=candidate.action_ref,
                    action_level=candidate.action_level,
                    metadata={"enemy_action_candidate": candidate.to_json()},
                    source_trace=candidate.source_trace,
                ),
            )
        return (
            (
                ActionChoice(
                    choice_id=_stable_choice_id(
                        "enemy_fixed_sequence",
                        candidate.actor_id,
                        candidate.action_ref,
                        candidate.action_level,
                        "external",
                        str(candidate.sequence_index),
                    ),
                    choice_kind="enemy_fixed_sequence",
                    control="external",
                    actor_id=candidate.actor_id,
                    actor_side=actor.side,
                    action_id=candidate.action_ref,
                    action_level=candidate.action_level,
                    command_template=_command_template(_command_from_enemy_candidate(candidate)),
                    auto_target_ids=candidate.auto_target_ids,
                    selectable_target_ids=candidate.selectable_target_ids,
                    target_policy=candidate.target_policy,
                    target_status="ok",
                    resource_status=resource_status,
                    resource_blocked_reason=resource_reason,
                    coverage_status="executable",
                    source_trace=candidate.source_trace,
                    metadata={
                        "selection_controller": "external",
                        "candidate_kind": "fixed_sequence_candidate",
                        "enemy_action_candidate": candidate.to_json(),
                    },
                ),
            ),
            (),
        )

    def _normal_action_choice(
        self,
        state: BattleState,
        actor: UnitState,
        action_id: str,
        action_level: int,
        *,
        choice_kind: Literal["normal_action", "summon_action"],
        source_trace: dict[str, JSONValue],
        metadata: dict[str, JSONValue],
    ) -> tuple[ActionChoice | None, BlockedActionReason]:
        definition = self.rules.action_definition(action_id, action_level)
        if definition is None:
            return None, _blocked_action(actor, action_id, action_level, "action_definition_missing", source_trace, metadata)
        if definition.coverage_status != "executable":
            return None, _blocked_action(
                actor,
                action_id,
                action_level,
                f"action_definition_not_executable:{definition.coverage_status}",
                source_trace,
                metadata,
            )
        event = self.rules.action_event(action_id, action_level)
        if event is None:
            return None, _blocked_action(actor, action_id, action_level, "action_event_missing", source_trace, metadata)
        event_reason = self._action_event_admission_reason(event)
        binding_reason = action_binding_blocked_reason(self.rules.action_ability_binding(action_id, action_level))
        target_result = self.targets.enumerate_action_targets(
            state,
            actor.unit_id,
            target_policy_for_action(self.rules, definition, event.target_mode),
        )
        resource_status, resource_reason = self._resource_status(state, actor.unit_id, definition, {})
        blocked_reason = combined_blocked_reason(
            event_reason,
            binding_reason,
            target_result.blocked_reason if not target_result.ok else "",
            resource_reason if resource_status == "blocked" else "",
        )
        if blocked_reason:
            return None, _blocked_action(
                actor,
                action_id,
                action_level,
                blocked_reason,
                {
                    **source_trace,
                    "action_definition": definition.source.to_json(),
                    "action_event": event.source.to_json(),
                },
                {
                    **metadata,
                    "target_enumeration": target_result.to_json(),
                    "resource_status": resource_status,
                    "resource_blocked_reason": resource_reason,
                },
            )
        command = ActionCommand(
            actor_id=actor.unit_id,
            action_id=action_id,
            action_level=action_level,
            target_ids=target_result.auto_target_ids,
            source="manual",
            metadata={"selection_controller": "external", **metadata},
        )
        return (
            ActionChoice(
                choice_id=_stable_choice_id(choice_kind, actor.unit_id, action_id, action_level, "external", ""),
                choice_kind=choice_kind,
                control="external",
                actor_id=actor.unit_id,
                actor_side=actor.side,
                action_id=action_id,
                action_level=action_level,
                command_template=_command_template(command),
                auto_target_ids=target_result.auto_target_ids,
                selectable_target_ids=target_result.selectable_target_ids,
                target_policy=target_result.policy,
                target_status="ok",
                resource_status=resource_status,
                resource_blocked_reason=resource_reason,
                coverage_status="executable",
                source_trace={
                    **source_trace,
                    "action_definition": definition.source.to_json(),
                    "action_event": event.source.to_json(),
                },
                metadata={
                    **metadata,
                    "action_definition": definition.to_json(),
                    "action_event": event.to_json(),
                    "target_enumeration": target_result.to_json(),
                },
            ),
            _blocked_action(actor, action_id, action_level, "", source_trace, metadata),
        )

    def _resource_status(
        self,
        state: BattleState,
        actor_id: str,
        definition: ActionDefinitionIR,
        queue_resource_policy: dict[str, JSONValue],
    ) -> tuple[Literal["ok", "blocked"], str]:
        result = self.resources.plan_action_resources(
            state,
            actor_id,
            action_resource_plan(
                definition,
                source="action_availability.resources",
                metadata={"definition_id": definition.definition_id},
                queue_resource_policy=queue_resource_policy,
            ),
        )
        if result.ok:
            return "ok", ""
        return "blocked", _resource_error_reason(result.errors)

    def _action_event_admission_reason(self, event: ActionEventIR) -> str:
        if event.coverage_status in {"blocked", "audit_only", "discovered_only", "unsupported"}:
            return event.blocked_reason or f"action_event_not_executable:{event.coverage_status}"
        return action_event_blocked_reason(event)

    def _action_set_entry_blocked_reason(self, entry: dict[str, JSONValue], action_id: str, level: int) -> str:
        if entry.get("coverage_status") != "executable":
            return str(entry.get("blocked_reason") or f"action_set_entry_not_executable:{entry.get('coverage_status')}")
        if not action_id:
            return "action_set_entry_action_ref_missing"
        if level <= 0:
            return "action_set_entry_default_level_missing"
        return ""

    def _blocked_view(
        self,
        state: BattleState,
        state_phase: str,
        current_window: str,
        turn_owner_id: str,
        queue: QueueAvailability,
        blocked: tuple[BlockedActionReason, ...],
        *,
        actor: ActorAvailability | None = None,
    ) -> ActionAvailabilityView:
        return ActionAvailabilityView(
            schema_version=ACTION_AVAILABILITY_SCHEMA_VERSION,
            mode="blocked",
            state_phase=state_phase,
            current_window=current_window,
            turn_owner_id=turn_owner_id,
            requires_scheduler_step=False,
            ordinary_input_blocked=True,
            ordinary_input_blocked_reason=blocked[0].reason if blocked else "blocked",
            queue=queue,
            actor=actor,
            blocked=blocked,
            coverage={"blocked_count": len(blocked), "unit_count": len(state.units)},
        )


def _command_from_enemy_candidate(candidate: EnemyActionCandidate) -> ActionCommand:
    return ActionCommand(
        actor_id=candidate.actor_id,
        action_id=candidate.action_ref,
        action_level=candidate.action_level,
        target_ids=candidate.auto_target_ids,
        source="manual",
        metadata={
            "selection_controller": "external",
            "candidate_kind": "fixed_sequence_candidate",
            "enemy_action_candidate": {
                "monster_data_card_id": candidate.monster_data_card_id,
                "sequence_index": candidate.sequence_index,
                "source_trace": candidate.source_trace,
            },
        },
    )


def _command_template(command: ActionCommand) -> dict[str, JSONValue]:
    return {
        "actor_id": command.actor_id,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "target_ids": list(command.target_ids),
        "source": command.source,
        "queue_name": command.queue_name,
        "metadata": command.metadata,
    }


def _control_gate_for_actor(state: BattleState, actor: UnitState) -> BlockedActionReason | None:
    gate = status_control_gate_for_actor(actor)
    if gate is None:
        return None
    metadata = gate.get("metadata") if isinstance(gate.get("metadata"), dict) else {}
    source_trace = gate.get("source_trace") if isinstance(gate.get("source_trace"), dict) else {}
    return BlockedActionReason(
        reason=str(gate.get("reason") or "status_control_gate"),
        scope=str(gate.get("scope") or "status_control"),
        actor_id=str(gate.get("actor_id") or actor.unit_id),
        actor_side=str(gate.get("actor_side") or actor.side),
        metadata=metadata,
        source_trace=source_trace,
    )


def _summon_action_admission_blocker(
    state: BattleState,
    actor: UnitState,
) -> tuple[str, dict[str, JSONValue], dict[str, JSONValue]] | None:
    summon_source_trace = (
        dict(actor.flags.get("summon_source_trace", {}))
        if isinstance(actor.flags.get("summon_source_trace"), dict)
        else {}
    )
    if actor.flags.get("summon_action_admitted") is not True:
        return "summon_action_admission_missing", {}, summon_source_trace
    runtime = state.global_flags.get("summon_runtime")
    if not isinstance(runtime, dict) or runtime.get("schema_version") != SUMMON_RUNTIME_SCHEMA_VERSION:
        return "summon_runtime_state_missing", {}, summon_source_trace
    entities = runtime.get("entities")
    if not isinstance(entities, dict):
        return "summon_runtime_entities_missing", {}, summon_source_trace
    runtime_entity = entities.get(actor.unit_id)
    if not isinstance(runtime_entity, dict):
        return "summon_runtime_entity_missing", {}, summon_source_trace
    runtime_source_trace = runtime_entity.get("source_trace")
    if not isinstance(runtime_source_trace, dict) or not runtime_source_trace:
        return "summon_runtime_source_trace_missing", {"runtime_entity": runtime_entity}, summon_source_trace
    source_intent_id = actor.flags.get("summon_intent_id")
    if source_intent_id is not None and runtime_entity.get("source_intent_id") != source_intent_id:
        return "summon_runtime_source_binding_mismatch", {"runtime_entity": runtime_entity}, runtime_source_trace
    admission = actor.flags.get("summon_action_admission")
    if not isinstance(admission, dict) or admission.get("coverage_status") != "executable":
        return "summon_action_source_not_admitted", {"runtime_entity": runtime_entity}, runtime_source_trace
    admission_source_trace = admission.get("source_trace")
    if not isinstance(admission_source_trace, dict) or not admission_source_trace:
        return "summon_action_source_trace_missing", {"runtime_entity": runtime_entity, "admission": admission}, runtime_source_trace
    return None


def _sorted_action_set_entries(skill_index_map: dict[str, JSONValue]) -> tuple[tuple[str, dict[str, JSONValue]], ...]:
    entries: list[tuple[str, dict[str, JSONValue]]] = []
    for key, value in skill_index_map.items():
        if isinstance(value, dict):
            entries.append((str(key), value))
    return tuple(sorted(entries, key=lambda item: (_skill_index_sort_key(item[0]), item[0])))


def _skill_index_sort_key(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 9999


def _default_level(entry: dict[str, JSONValue]) -> int:
    default_level = entry.get("default_level")
    if isinstance(default_level, bool):
        return 0
    if isinstance(default_level, int):
        return default_level
    if isinstance(default_level, float):
        return int(default_level)
    return 0


def _stable_choice_id(kind: str, actor_id: str, action_id: str, action_level: int, control: str, suffix: str) -> str:
    parts = ("choice", kind, control, actor_id, action_id or "pending_action", str(action_level), suffix)
    return ":".join(part.replace(":", "_") for part in parts if part != "")


def _blocked_action(
    actor: UnitState,
    action_id: str,
    action_level: int,
    reason: str,
    source_trace: dict[str, JSONValue],
    metadata: dict[str, JSONValue],
) -> BlockedActionReason:
    return BlockedActionReason(
        reason=reason,
        scope="normal_action",
        actor_id=actor.unit_id,
        actor_side=actor.side,
        action_id=action_id,
        action_level=action_level,
        metadata=metadata,
        source_trace=source_trace,
    )


def _resource_error_reason(errors: tuple[str, ...]) -> str:
    for error in errors:
        if error.startswith("insufficient skill points"):
            return "insufficient_skill_points"
        if error.startswith("unknown actor_id"):
            return "resource_unknown_actor"
    return "resource_plan_failed"
