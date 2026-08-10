from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from ..core.model import JSONValue, RNGEvent
from ..immutable_json import freeze_json, thaw_json
from .rng import (
    RNGOutcome,
    RNGRequest,
    choice_key_for_identity,
    event_id_for_identity,
    resolve_rng_request,
)


TargetRandomMode = Literal["single", "sample_without_replacement", "shuffle"]
_MODES = frozenset({"single", "sample_without_replacement", "shuffle"})
_SOURCE_KINDS = frozenset(
    {"target_expression", "bounce_policy", "random_select_task", "validation_fixture"}
)


def _fingerprint(prefix: str, value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()}"


def target_pool_fingerprint(candidate_ids: Sequence[str]) -> str:
    values = tuple(candidate_ids)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("target random candidate identity is invalid")
    if len(values) != len(set(values)):
        raise ValueError("target random candidate identities must be unique")
    return _fingerprint("target_pool", sorted(values))


def _identity_tuple(value: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(f"{label} must be a sequence of identities")
    values = tuple(value)
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"{label} contains an invalid identity")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} contains duplicate identities")
    return tuple(sorted(values))


def _frozen_object(value: Mapping[str, JSONValue], label: str) -> Mapping[str, JSONValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return cast(Mapping[str, JSONValue], freeze_json(dict(value)))


def _validate_source_trace(value: Mapping[str, JSONValue], source_kind: str) -> None:
    if source_kind == "validation_fixture":
        return
    if set(value) != {"source_path", "raw_type", "raw_id", "evidence"}:
        raise ValueError("target random source trace fields are invalid")
    for key in ("source_path", "raw_type", "raw_id"):
        if not isinstance(value.get(key), str) or not value.get(key):
            raise ValueError("target random source trace identity is invalid")
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("target random source evidence is invalid")


@dataclass(frozen=True)
class TargetRandomPlan:
    mode: TargetRandomMode
    source_kind: Literal[
        "target_expression", "bounce_policy", "random_select_task", "validation_fixture"
    ]
    source_identity: str
    source_trace: Mapping[str, JSONValue]
    evaluation_context: Mapping[str, JSONValue]
    invocation_identity: str
    candidate_ids: tuple[str, ...]
    requested_count: int
    before_state: str
    event_index: int
    schema_version: str = "hsr.target_random_plan.v1"
    plan_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not TargetRandomPlan:
            raise TypeError("target random plan must not be subclassed")
        if self.schema_version != "hsr.target_random_plan.v1":
            raise ValueError("target random plan schema is invalid")
        if self.mode not in _MODES:
            raise ValueError("target random mode is invalid")
        if self.source_kind not in _SOURCE_KINDS:
            raise ValueError("target random source kind is invalid")
        if not isinstance(self.source_identity, str) or not self.source_identity:
            raise ValueError("target random source identity is required")
        if not isinstance(self.invocation_identity, str) or not self.invocation_identity:
            raise ValueError("target random invocation identity is required")
        if not isinstance(self.before_state, str) or not self.before_state:
            raise ValueError("target random before state is required")
        if type(self.event_index) is not int or self.event_index < 0:
            raise ValueError("target random event index is invalid")
        if type(self.requested_count) is not int or self.requested_count < 0:
            raise ValueError("target random requested count is invalid")
        candidates = _identity_tuple(self.candidate_ids, "target random candidates")
        if self.mode == "single" and self.requested_count != 1:
            raise ValueError("single target random plan requires one draw")
        if self.mode == "shuffle" and self.requested_count != len(candidates):
            raise ValueError("shuffle target random count must equal candidate count")
        source_trace = _frozen_object(self.source_trace, "target random source trace")
        _validate_source_trace(source_trace, self.source_kind)
        evaluation_context = _frozen_object(
            self.evaluation_context, "target random evaluation context"
        )
        object.__setattr__(self, "candidate_ids", candidates)
        object.__setattr__(self, "source_trace", source_trace)
        object.__setattr__(self, "evaluation_context", evaluation_context)
        identity = self.identity_payload()
        object.__setattr__(self, "plan_fingerprint", _fingerprint("target_random_plan", identity))

    @property
    def draw_count(self) -> int:
        if self.mode == "single":
            return 1
        return min(self.requested_count, len(self.candidate_ids))

    @property
    def candidate_pool_fingerprint(self) -> str:
        return target_pool_fingerprint(self.candidate_ids)

    def identity_payload(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "source_kind": self.source_kind,
            "source_identity": self.source_identity,
            "source_trace": cast(dict[str, JSONValue], thaw_json(self.source_trace)),
            "evaluation_context": cast(
                dict[str, JSONValue], thaw_json(self.evaluation_context)
            ),
            "invocation_identity": self.invocation_identity,
            "candidate_ids": list(self.candidate_ids),
            "candidate_pool_fingerprint": self.candidate_pool_fingerprint,
            "requested_count": self.requested_count,
            "draw_count": self.draw_count,
            "before_state": self.before_state,
            "event_index": self.event_index,
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {**self.identity_payload(), "plan_fingerprint": self.plan_fingerprint}


@dataclass(frozen=True)
class TargetRandomResult:
    status: Literal["resolved", "blocked"]
    plan_fingerprint: str
    selected_ids: tuple[str, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    blocked_reason: str = ""
    pending_request: Mapping[str, JSONValue] = field(default_factory=dict)
    result_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not TargetRandomResult:
            raise TypeError("target random result must not be subclassed")
        if not isinstance(self.plan_fingerprint, str) or not self.plan_fingerprint:
            raise ValueError("target random result plan identity is required")
        selected = _identity_tuple_preserve_order(self.selected_ids, "target random result")
        if not isinstance(self.rng_events, tuple) or any(
            type(event) is not RNGEvent for event in self.rng_events
        ):
            raise TypeError("target random events must be exact RNGEvent values")
        events = tuple(_frozen_rng_event(event) for event in self.rng_events)
        pending = _frozen_object(self.pending_request, "target random pending request")
        if self.status == "resolved":
            if self.blocked_reason or pending:
                raise ValueError("resolved target random result carries blocked data")
        elif self.status == "blocked":
            if not self.blocked_reason or selected or events:
                raise ValueError("blocked target random result carries executable output")
        else:
            raise ValueError("target random result status is invalid")
        object.__setattr__(self, "selected_ids", selected)
        object.__setattr__(self, "rng_events", events)
        object.__setattr__(self, "pending_request", pending)
        identity = {
            "status": self.status,
            "plan_fingerprint": self.plan_fingerprint,
            "selected_ids": list(selected),
            "rng_events": [event.to_json() for event in events],
            "blocked_reason": self.blocked_reason,
            "pending_request": thaw_json(pending),
        }
        object.__setattr__(self, "result_fingerprint", _fingerprint("target_random_result", identity))

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status": self.status,
            "plan_fingerprint": self.plan_fingerprint,
            "selected_ids": list(self.selected_ids),
            "rng_events": [event.to_json() for event in self.rng_events],
            "blocked_reason": self.blocked_reason,
            "pending_request": cast(dict[str, JSONValue], thaw_json(self.pending_request)),
            "result_fingerprint": self.result_fingerprint,
        }


def _identity_tuple_preserve_order(value: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(f"{label} identities must be a sequence")
    values = tuple(value)
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"{label} contains an invalid identity")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} contains duplicate identities")
    return values


def _frozen_rng_event(event: RNGEvent) -> RNGEvent:
    return RNGEvent(
        rng_type=event.rng_type,
        source=event.source,
        result=cast(JSONValue, freeze_json(event.result)),
        event_id=event.event_id,
        before_state=event.before_state,
        after_state=event.after_state,
        metadata=cast(dict[str, JSONValue], freeze_json(event.metadata)),
    )


class TargetRandomSampler:
    def resolve(
        self,
        plan: TargetRandomPlan,
        *,
        rng_choices: Mapping[str, JSONValue] | None = None,
        rng_mode: str = "deterministic_seed",
    ) -> TargetRandomResult:
        if type(plan) is not TargetRandomPlan:
            raise TypeError("target random sampler requires an exact plan")
        choices = dict(rng_choices or {})
        if any(not isinstance(key, str) or not key for key in choices):
            return _blocked(plan, "target_random_choice_key_invalid")
        if plan.mode == "single" and not plan.candidate_ids:
            return _blocked(plan, "target_random_candidate_pool_empty")
        if plan.draw_count == 0:
            return _resolved_result(plan, (), ())

        remaining = plan.candidate_ids
        selected: list[str] = []
        events: list[RNGEvent] = []
        for draw_index in range(plan.draw_count):
            if len(remaining) == 1:
                selected.append(remaining[0])
                remaining = ()
                continue
            request = _draw_request(plan, remaining, draw_index)
            resolution = resolve_rng_request(
                request,
                rng_choices=choices,
                rng_mode=rng_mode,
            )
            if not resolution.ok or resolution.selected_outcome is None or resolution.event is None:
                return _blocked(
                    plan,
                    resolution.blocked_reason or "target_random_resolution_blocked",
                    pending_request=resolution.blocked_payload(),
                )
            target_id = resolution.selected_outcome.outcome_id
            if target_id not in remaining:
                return _blocked(plan, "target_random_selected_target_not_in_remaining_pool")
            selected.append(target_id)
            remaining = tuple(item for item in remaining if item != target_id)
            events.append(resolution.event)
        return _resolved_result(plan, tuple(selected), tuple(events))


@dataclass(frozen=True)
class TargetRandomReplayResult:
    ok: bool
    resolution: TargetRandomResult
    errors: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "resolution": self.resolution.to_json(),
            "errors": list(self.errors),
        }


def replay_target_random(
    plan: TargetRandomPlan,
    events: tuple[RNGEvent, ...],
) -> TargetRandomReplayResult:
    if not isinstance(events, tuple) or any(type(event) is not RNGEvent for event in events):
        resolution = _blocked(plan, "target_random_replay_events_invalid")
        return TargetRandomReplayResult(False, resolution, (resolution.blocked_reason,))
    choices: dict[str, JSONValue] = {}
    errors: list[str] = []
    choice_sources: set[str] = set()
    for index, event in enumerate(events):
        metadata = event.metadata if isinstance(event.metadata, Mapping) else {}
        result = event.result if isinstance(event.result, Mapping) else {}
        choice_key = metadata.get("choice_key")
        selected = result.get("selected_outcome_id")
        choice_source = metadata.get("choice_source")
        if not isinstance(choice_key, str) or not choice_key:
            errors.append(f"event[{index}]:choice_key_missing")
            continue
        if choice_key in choices:
            errors.append(f"event[{index}]:choice_key_duplicate")
            continue
        if not isinstance(selected, str) or not selected:
            errors.append(f"event[{index}]:selected_outcome_missing")
            continue
        if choice_source not in {"deterministic_seed", "explicit_ledger"}:
            errors.append(f"event[{index}]:choice_source_invalid")
            continue
        choice_sources.add(cast(str, choice_source))
        choices[choice_key] = selected
    if errors:
        resolution = _blocked(plan, "target_random_replay_event_invalid")
        return TargetRandomReplayResult(False, resolution, tuple(errors))
    if len(choice_sources) > 1:
        resolution = _blocked(plan, "target_random_replay_choice_source_mixed")
        return TargetRandomReplayResult(False, resolution, (resolution.blocked_reason,))
    replay_mode = "deterministic_seed" if choice_sources == {"deterministic_seed"} else "explicit"
    replayed = TargetRandomSampler().resolve(
        plan,
        rng_choices={} if replay_mode == "deterministic_seed" else choices,
        rng_mode=replay_mode,
    )
    if not replayed.resolved:
        return TargetRandomReplayResult(False, replayed, (replayed.blocked_reason,))
    expected = [event.to_json() for event in replayed.rng_events]
    actual = [event.to_json() for event in events]
    if expected != actual:
        return TargetRandomReplayResult(
            False,
            replayed,
            ("target_random_replay_event_chain_mismatch",),
        )
    return TargetRandomReplayResult(True, replayed)


def _draw_request(
    plan: TargetRandomPlan,
    remaining: tuple[str, ...],
    draw_index: int,
) -> RNGRequest:
    remaining_fingerprint = target_pool_fingerprint(remaining)
    identity: dict[str, JSONValue] = {
        "decision_scope": "target_random",
        "decision_index": draw_index,
        "target_expression_id": plan.source_identity,
        "source_kind": plan.source_kind,
        "source_identity": plan.source_identity,
        "evaluation_context_fingerprint": _fingerprint(
            "target_random_context", thaw_json(plan.evaluation_context)
        ),
        "invocation_identity": plan.invocation_identity,
        "candidate_pool_fingerprint": plan.candidate_pool_fingerprint,
        "remaining_pool_fingerprint": remaining_fingerprint,
        "draw_index": draw_index,
        "draw_count": plan.draw_count,
        "plan_fingerprint": plan.plan_fingerprint,
    }
    choice_key = choice_key_for_identity("target_random", identity)
    event_id = event_id_for_identity(
        "target_random", identity, event_index=plan.event_index + draw_index
    )
    outcomes = tuple(
        RNGOutcome(
            outcome_id=target_id,
            payload={
                "selected_target_id": target_id,
                "selected_index": index,
                "candidate_pool_fingerprint": plan.candidate_pool_fingerprint,
                "remaining_pool_fingerprint": remaining_fingerprint,
                "draw_index": draw_index,
                "draw_count": plan.draw_count,
                "value": target_id,
            },
            weight=1.0,
        )
        for index, target_id in enumerate(remaining)
    )
    source_trace = cast(dict[str, JSONValue], thaw_json(plan.source_trace))
    return RNGRequest(
        rng_type="target_random",
        purpose=plan.mode,
        event_id=event_id,
        choice_key=choice_key,
        source="target_random_sampler",
        before_state=plan.before_state,
        decision_kind="choice",
        outcomes=outcomes,
        source_trace=source_trace,
        metadata={
            "plan_fingerprint": plan.plan_fingerprint,
            "source_kind": plan.source_kind,
            "source_identity": plan.source_identity,
            "invocation_identity": plan.invocation_identity,
            "candidate_pool": list(plan.candidate_ids),
            "candidate_pool_fingerprint": plan.candidate_pool_fingerprint,
            "remaining_pool": list(remaining),
            "remaining_pool_fingerprint": remaining_fingerprint,
            "draw_index": draw_index,
            "draw_count": plan.draw_count,
        },
        identity=identity,
        invalid_choice_reason="target_random_choice_invalid",
    )


def _blocked(
    plan: TargetRandomPlan,
    reason: str,
    *,
    pending_request: Mapping[str, JSONValue] | None = None,
) -> TargetRandomResult:
    return TargetRandomResult(
        status="blocked",
        plan_fingerprint=plan.plan_fingerprint,
        blocked_reason=reason,
        pending_request=pending_request or {},
    )


def _resolved_result(
    plan: TargetRandomPlan,
    selected_ids: tuple[str, ...],
    events: tuple[RNGEvent, ...],
) -> TargetRandomResult:
    return TargetRandomResult(
        status="resolved",
        plan_fingerprint=plan.plan_fingerprint,
        selected_ids=selected_ids,
        rng_events=events,
    )
