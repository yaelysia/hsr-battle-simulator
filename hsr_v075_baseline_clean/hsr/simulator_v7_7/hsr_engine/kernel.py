from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any


KERNEL_TRANSITION_ENCODING = "hsr.kernel.action_transition.v1"
KERNEL_FULL_SCENE_SNAPSHOT_ENCODING = "hsr.kernel.full_scene_snapshot.v1"


def _copy_json_value(value: Any) -> Any:
    return deepcopy(value)


@dataclass
class SourceRef:
    """Stable source identity for anything that can affect battle state."""

    source_type: str = "unknown"
    source_id: str = ""
    owner_id: str = ""
    origin_path: str = ""
    tbgd_ref: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def action(cls, actor_id: str = "", action_id: str = "", origin_path: str = "") -> "SourceRef":
        return cls(
            source_type="action",
            source_id=str(action_id or ""),
            owner_id=str(actor_id or ""),
            origin_path=str(origin_path or ""),
        )

    @classmethod
    def status(cls, owner_id: str = "", status_id: str = "", origin_path: str = "") -> "SourceRef":
        return cls(
            source_type="status",
            source_id=str(status_id or ""),
            owner_id=str(owner_id or ""),
            origin_path=str(origin_path or ""),
        )

    @classmethod
    def route_step(cls, step_type: str = "", origin_path: str = "") -> "SourceRef":
        return cls(
            source_type="route_step",
            source_id=str(step_type or ""),
            origin_path=str(origin_path or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActionRequest:
    """Normalized action input before target resolution and settlement."""

    actor_id: str = ""
    action_id: str = ""
    timing: str = "manual"
    turn_kind: str | None = None
    target_ids: list[str] = field(default_factory=list)
    route_step_index: int | None = None
    extra_turn_type: str | None = None
    source: SourceRef = field(default_factory=SourceRef)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_route_step(cls, step: dict[str, Any], target_ids: list[str]) -> "ActionRequest":
        route_step_index = step.get("_route_step_index")
        try:
            route_step_index = int(route_step_index) if route_step_index is not None else None
        except (TypeError, ValueError):
            route_step_index = None
        actor_id = str(step.get("actor") or "")
        action_id = str(step.get("action") or "")
        origin_path = f"route[{route_step_index}]" if route_step_index is not None else "route[]"
        return cls(
            actor_id=actor_id,
            action_id=action_id,
            timing=str(step.get("timing") or "manual"),
            turn_kind=step.get("turn_kind"),
            target_ids=list(target_ids or []),
            route_step_index=route_step_index,
            extra_turn_type=step.get("extra_turn_type"),
            source=SourceRef.action(actor_id=actor_id, action_id=action_id, origin_path=origin_path),
            metadata={
                "step_type": step.get("type", "action"),
                "target_source": "explicit" if "targets" in step else "auto",
            },
        )

    @classmethod
    def from_route_control_step(cls, step: dict[str, Any]) -> "ActionRequest":
        route_step_index = step.get("_route_step_index")
        try:
            route_step_index = int(route_step_index) if route_step_index is not None else None
        except (TypeError, ValueError):
            route_step_index = None
        step_type = str(step.get("type") or "route_control")
        origin_path = f"route[{route_step_index}]" if route_step_index is not None else "route[]"
        effects = step.get("effects", [])
        effect_count = len(effects) if isinstance(effects, list) else 0
        return cls(
            actor_id=str(step.get("actor") or ""),
            action_id=step_type,
            timing=step_type,
            turn_kind=step.get("turn_kind"),
            target_ids=[],
            route_step_index=route_step_index,
            extra_turn_type=step.get("extra_turn_type"),
            source=SourceRef.route_step(step_type=step_type, origin_path=origin_path),
            metadata={
                "step_type": step_type,
                "effect_count": effect_count,
                "target_source": "effect_targets",
            },
        )

    @classmethod
    def from_queued_action(
        cls,
        item: dict[str, Any],
        target_ids: list[str],
        *,
        queue_name: str,
        queue_index: int,
        target_source: str = "explicit",
    ) -> "ActionRequest":
        actor_id = str(item.get("actor") or "")
        action_id = str(item.get("action") or "")
        origin_path = f"{queue_name}[{queue_index}]"
        return cls(
            actor_id=actor_id,
            action_id=action_id,
            timing="queued",
            turn_kind=item.get("turn_kind"),
            target_ids=list(target_ids or []),
            extra_turn_type=item.get("extra_turn_type"),
            source=SourceRef.action(actor_id=actor_id, action_id=action_id, origin_path=origin_path),
            metadata={
                "step_type": "queued_action",
                "queue_name": str(queue_name or ""),
                "queue_index": int(queue_index),
                "target_source": str(target_source or ""),
                "queued": True,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


@dataclass
class TargetResolution:
    """How action targets were selected for this action request."""

    actor_id: str = ""
    action_id: str = ""
    requested_target_ids: list[str] = field(default_factory=list)
    resolved_target_ids: list[str] = field(default_factory=list)
    method: str = ""
    reason: str = ""
    source: SourceRef = field(default_factory=SourceRef)
    decision_trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StateChange:
    """A normalized state mutation emitted at the same site as the runtime change."""

    sequence: int = 0
    change_type: str = ""
    scope: str = ""
    subject_id: str = ""
    field_path: str = ""
    old_value: Any = None
    new_value: Any = None
    delta: Any = None
    source: SourceRef = field(default_factory=SourceRef)
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["old_value"] = _copy_json_value(self.old_value)
        data["new_value"] = _copy_json_value(self.new_value)
        data["delta"] = _copy_json_value(self.delta)
        data["payload"] = _copy_json_value(self.payload)
        return data


@dataclass
class RNGEvent:
    """A deterministic record of a random/probabilistic branch decision."""

    sequence: int = 0
    event_type: str = ""
    event_id: str = ""
    mode: Any = None
    outcome: Any = None
    probability: dict[str, Any] = field(default_factory=dict)
    source: SourceRef = field(default_factory=SourceRef)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = _copy_json_value(self.mode)
        data["outcome"] = _copy_json_value(self.outcome)
        data["probability"] = _copy_json_value(self.probability)
        data["payload"] = _copy_json_value(self.payload)
        return data


@dataclass
class ActionTransition:
    """Canonical transition record for one action request."""

    encoding: str = KERNEL_TRANSITION_ENCODING
    snapshot_encoding: str = KERNEL_FULL_SCENE_SNAPSHOT_ENCODING
    request: ActionRequest = field(default_factory=ActionRequest)
    target_resolution: TargetResolution | None = None
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None
    state_changes: list[StateChange] = field(default_factory=list)
    rng_events: list[RNGEvent] = field(default_factory=list)

    def capture_before(self, snapshot: dict[str, Any]) -> None:
        self.before_snapshot = _copy_json_value(snapshot)

    def capture_after(self, snapshot: dict[str, Any]) -> None:
        self.after_snapshot = _copy_json_value(snapshot)

    def append_change(self, change: StateChange) -> None:
        change.sequence = len(self.state_changes) + 1
        self.state_changes.append(change)

    def append_rng_event(self, event: RNGEvent) -> None:
        event.sequence = len(self.rng_events) + 1
        self.rng_events.append(event)

    def to_dict(self) -> dict[str, Any]:
        return {
            "encoding": self.encoding,
            "snapshot_encoding": self.snapshot_encoding,
            "request": self.request.to_dict(),
            "target_resolution": self.target_resolution.to_dict() if self.target_resolution else None,
            "before_snapshot": _copy_json_value(self.before_snapshot),
            "after_snapshot": _copy_json_value(self.after_snapshot),
            "state_changes": [change.to_dict() for change in self.state_changes],
            "rng_events": [event.to_dict() for event in self.rng_events],
        }
