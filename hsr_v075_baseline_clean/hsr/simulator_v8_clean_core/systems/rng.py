from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ..core.model import JSONValue, RNGEvent


@dataclass(frozen=True)
class RNGOutcome:
    outcome_id: str
    payload: dict[str, JSONValue] = field(default_factory=dict)
    probability: float | None = None
    weight: float | None = None

    def to_json(self) -> dict[str, JSONValue]:
        data: dict[str, JSONValue] = {
            "outcome_id": self.outcome_id,
            "payload": self.payload,
        }
        if self.probability is not None:
            data["probability"] = self.probability
        if self.weight is not None:
            data["weight"] = self.weight
        return data


@dataclass(frozen=True)
class RNGRequest:
    rng_type: str
    purpose: str
    event_id: str
    choice_key: str
    source: str
    before_state: str
    decision_kind: str
    outcomes: tuple[RNGOutcome, ...]
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    identity: dict[str, JSONValue] = field(default_factory=dict)
    missing_choice_reason: str = "requires_rng_choice"
    invalid_choice_reason: str = "rng_choice_invalid"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "rng_type": self.rng_type,
            "purpose": self.purpose,
            "event_id": self.event_id,
            "choice_key": self.choice_key,
            "source": self.source,
            "before_state": self.before_state,
            "decision_kind": self.decision_kind,
            "outcomes": [outcome.to_json() for outcome in self.outcomes],
            "source_trace": self.source_trace,
            "metadata": self.metadata,
            "identity": self.identity,
        }


@dataclass(frozen=True)
class RNGResolution:
    ok: bool
    request: RNGRequest
    selected_outcome: RNGOutcome | None = None
    event: RNGEvent | None = None
    blocked_reason: str = ""
    choice_source: str = ""
    roll: float | None = None
    raw_choice: JSONValue = None

    @property
    def selected_outcome_id(self) -> str:
        return self.selected_outcome.outcome_id if self.selected_outcome is not None else ""

    def available_rng_outcomes(self) -> dict[str, JSONValue]:
        return available_rng_outcomes(self.request)

    def blocked_payload(self) -> dict[str, JSONValue]:
        return {
            "reason": self.blocked_reason,
            "choice_key": self.request.choice_key,
            "event_id": self.request.event_id,
            "rng_type": self.request.rng_type,
            "purpose": self.request.purpose,
            "available_rng_outcomes": self.available_rng_outcomes(),
            "source_trace": self.request.source_trace,
            "rng_request": self.request.to_json(),
            "raw_choice": self.raw_choice,
        }


@dataclass(frozen=True)
class RNGChoiceLedgerValidation:
    ok: bool
    provided_keys: tuple[str, ...]
    consumed_keys: tuple[str, ...]
    duplicate_provided_keys: tuple[str, ...] = ()
    duplicate_consumed_keys: tuple[str, ...] = ()
    missing_keys: tuple[str, ...] = ()
    extra_keys: tuple[str, ...] = ()
    invalid_identity_event_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "provided_keys": list(self.provided_keys),
            "consumed_keys": list(self.consumed_keys),
            "duplicate_provided_keys": list(self.duplicate_provided_keys),
            "duplicate_consumed_keys": list(self.duplicate_consumed_keys),
            "missing_keys": list(self.missing_keys),
            "extra_keys": list(self.extra_keys),
            "invalid_identity_event_ids": list(self.invalid_identity_event_ids),
        }


def resolve_rng_request(
    request: RNGRequest,
    *,
    rng_choices: dict[str, JSONValue] | None = None,
    rng_mode: str | None = None,
    forced_outcome_id: str | None = None,
    forced_choice_source: str = "forced_command",
) -> RNGResolution:
    if not request.outcomes:
        return RNGResolution(ok=False, request=request, blocked_reason="rng_outcomes_empty")
    if not _identity_is_complete(request.identity):
        return RNGResolution(ok=False, request=request, blocked_reason="rng_decision_identity_incomplete")

    if forced_outcome_id:
        selected = _outcome_by_id(request.outcomes, forced_outcome_id)
        if selected is None:
            return RNGResolution(
                ok=False,
                request=request,
                blocked_reason=request.invalid_choice_reason,
                raw_choice=forced_outcome_id,
            )
        return _resolved(request, selected, choice_source=forced_choice_source)

    choices = rng_choices or {}
    found, raw_choice = _choice_for_request(choices, request)
    if found:
        selected = _outcome_from_choice(request.outcomes, raw_choice)
        if selected is None:
            return RNGResolution(
                ok=False,
                request=request,
                blocked_reason=request.invalid_choice_reason,
                raw_choice=raw_choice,
            )
        return _resolved(request, selected, choice_source="explicit_ledger", raw_choice=raw_choice)

    mode = (rng_mode or "deterministic_seed").lower()
    if mode in {"explicit", "explicit_ledger", "ledger"}:
        return RNGResolution(ok=False, request=request, blocked_reason=request.missing_choice_reason)
    if mode not in {"", "deterministic", "deterministic_seed", "auto"}:
        return RNGResolution(ok=False, request=request, blocked_reason=f"rng_mode_not_admitted:{mode}")

    roll = _deterministic_roll(
        request.before_state,
        request.event_id,
        request.choice_key,
        [outcome.to_json() for outcome in request.outcomes],
    )
    selected = _deterministic_outcome(request.outcomes, roll, request.decision_kind)
    return _resolved(request, selected, choice_source="deterministic_seed", roll=roll)


def available_rng_outcomes(request: RNGRequest) -> dict[str, JSONValue]:
    return {
        "choice_key": request.choice_key,
        "event_id": request.event_id,
        "rng_type": request.rng_type,
        "purpose": request.purpose,
        "decision_kind": request.decision_kind,
        "outcomes": [outcome.to_json() for outcome in request.outcomes],
        "source_trace": request.source_trace,
    }


def rng_choices_from_payload(payload: dict[str, JSONValue] | None) -> dict[str, JSONValue]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("rng_choices")
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    ledger = payload.get("rng_choice_ledger")
    if isinstance(ledger, list):
        choices: dict[str, JSONValue] = {}
        for entry in ledger:
            if not isinstance(entry, dict):
                continue
            key = entry.get("choice_key")
            if isinstance(key, str) and key and key not in choices:
                choices[key] = entry.get("choice")
        return choices
    return {}


def validate_rng_choice_ledger(
    payload: dict[str, JSONValue] | None,
    events: tuple[RNGEvent, ...],
) -> RNGChoiceLedgerValidation:
    payload = payload if isinstance(payload, dict) else {}
    provided_sequence: list[str] = []
    raw_choices = payload.get("rng_choices")
    if isinstance(raw_choices, dict):
        provided_sequence.extend(str(key) for key in raw_choices)
    raw_ledger = payload.get("rng_choice_ledger")
    if isinstance(raw_ledger, list):
        provided_sequence.extend(
            str(entry.get("choice_key"))
            for entry in raw_ledger
            if isinstance(entry, dict) and isinstance(entry.get("choice_key"), str) and entry.get("choice_key")
        )
    consumed_sequence: list[str] = []
    invalid_identity: list[str] = []
    event_ids_by_key: dict[str, str] = {}
    for event in events:
        result = event.result if isinstance(event.result, dict) else {}
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        key = result.get("choice_key") or metadata.get("choice_key")
        identity = metadata.get("decision_identity")
        if not isinstance(key, str) or not key:
            invalid_identity.append(event.event_id)
            continue
        if not isinstance(identity, dict) or not _identity_is_complete(identity):
            invalid_identity.append(event.event_id)
        consumed_sequence.append(key)
        event_ids_by_key[event.event_id] = key
    duplicate_provided = _duplicates(provided_sequence)
    duplicate_consumed = _duplicates(consumed_sequence)
    provided = tuple(dict.fromkeys(provided_sequence))
    consumed = tuple(dict.fromkeys(consumed_sequence))
    explicit = str(payload.get("rng_mode") or "").lower() in {"explicit", "explicit_ledger", "ledger"}
    normalized_provided = tuple(event_ids_by_key.get(key, key) for key in provided)
    missing = tuple(sorted(set(consumed).difference(normalized_provided))) if explicit else ()
    extra = tuple(sorted(set(normalized_provided).difference(consumed))) if provided else ()
    ok = not duplicate_provided and not duplicate_consumed and not missing and not extra and not invalid_identity
    return RNGChoiceLedgerValidation(
        ok,
        provided,
        consumed,
        duplicate_provided,
        duplicate_consumed,
        missing,
        extra,
        tuple(invalid_identity),
    )


def rng_mode_from_payload(payload: dict[str, JSONValue] | None, *, default: str = "deterministic_seed") -> str:
    if isinstance(payload, dict):
        raw = payload.get("rng_mode")
        if isinstance(raw, str) and raw:
            return raw
    return default


def merge_rng_result_payload(event: RNGEvent, payload: dict[str, JSONValue]) -> RNGEvent:
    result = event.result if isinstance(event.result, dict) else {}
    return RNGEvent(
        rng_type=event.rng_type,
        source=event.source,
        event_id=event.event_id,
        before_state=event.before_state,
        after_state=event.after_state,
        result={**result, **payload},
        metadata=event.metadata,
    )


def _resolved(
    request: RNGRequest,
    selected: RNGOutcome,
    *,
    choice_source: str,
    roll: float | None = None,
    raw_choice: JSONValue = None,
) -> RNGResolution:
    selected_payload = selected.payload
    threshold = selected.probability if request.decision_kind == "probability" else None
    result: dict[str, JSONValue] = {
        "schema": "v8_rng_decision_v1",
        "decision_kind": request.decision_kind,
        "purpose": request.purpose,
        "choice_key": request.choice_key,
        "choice_source": choice_source,
        "outcomes": [outcome.to_json() for outcome in request.outcomes],
        "selected_outcome_id": selected.outcome_id,
        "selected_payload": selected_payload,
        "available_rng_outcomes": available_rng_outcomes(request),
        "source_trace": request.source_trace,
        "decision_identity": request.identity,
    }
    if selected_payload:
        result.update(selected_payload)
    if roll is not None:
        result["roll"] = roll
    if threshold is not None:
        result["threshold"] = threshold
    event = RNGEvent(
        rng_type=request.rng_type,
        source=request.source,
        event_id=request.event_id,
        before_state=request.before_state,
        after_state=request.before_state,
        result=result,
        metadata={
            **request.metadata,
            "schema": "v8_rng_decision_v1",
            "decision_kind": request.decision_kind,
            "purpose": request.purpose,
            "choice_key": request.choice_key,
            "choice_source": choice_source,
            "source_trace": request.source_trace,
            "decision_identity": request.identity,
            "available_rng_outcomes": available_rng_outcomes(request),
        },
    )
    return RNGResolution(
        ok=True,
        request=request,
        selected_outcome=selected,
        event=event,
        choice_source=choice_source,
        roll=roll,
        raw_choice=raw_choice,
    )


def _choice_for_request(choices: dict[str, JSONValue], request: RNGRequest) -> tuple[bool, JSONValue]:
    for key in (request.choice_key, request.event_id):
        if key in choices:
            return True, choices[key]
    return False, None


def choice_key_for_identity(rng_type: str, identity: dict[str, JSONValue]) -> str:
    stable = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:16]
    return f"rng:{rng_type}:{digest}"


def event_id_for_identity(rng_type: str, identity: dict[str, JSONValue], *, event_index: int) -> str:
    """Build an event id from the same complete identity used by the choice key."""

    stable = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:16]
    return f"rng_event:{event_index}:{rng_type}:{digest}"


def _identity_is_complete(identity: dict[str, JSONValue]) -> bool:
    return (
        isinstance(identity, dict)
        and isinstance(identity.get("decision_scope"), str)
        and bool(identity.get("decision_scope"))
        and type(identity.get("decision_index")) is int
        and int(identity["decision_index"]) >= 0
        and any(
            isinstance(identity.get(key), str) and bool(identity.get(key))
            for key in ("action_id", "task_id", "status_id", "target_expression_id", "derived_event_id")
        )
    )


def _duplicates(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


def _outcome_from_choice(outcomes: tuple[RNGOutcome, ...], raw_choice: JSONValue) -> RNGOutcome | None:
    if isinstance(raw_choice, bool):
        return _outcome_by_id(outcomes, "success" if raw_choice else "fail")
    if isinstance(raw_choice, int):
        if 0 <= raw_choice < len(outcomes):
            return outcomes[raw_choice]
        return None
    if isinstance(raw_choice, str):
        by_id = _outcome_by_id(outcomes, raw_choice)
        if by_id is not None:
            return by_id
        for outcome in outcomes:
            if raw_choice in {
                str(outcome.payload.get("selected_target_id") or ""),
                str(outcome.payload.get("selected_status_instance_id") or ""),
                str(outcome.payload.get("selected") or ""),
                str(outcome.payload.get("value") or ""),
            }:
                return outcome
        return None
    if isinstance(raw_choice, dict):
        for key in ("outcome_id", "selected_outcome_id", "id"):
            value = raw_choice.get(key)
            if isinstance(value, str):
                selected = _outcome_by_id(outcomes, value)
                if selected is not None:
                    return selected
        for key in ("index", "selected_index"):
            value = raw_choice.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(outcomes):
                return outcomes[value]
        for key in ("target_id", "selected_target_id", "status_instance_id", "selected"):
            value = raw_choice.get(key)
            if isinstance(value, str):
                selected = _outcome_from_choice(outcomes, value)
                if selected is not None:
                    return selected
    return None


def _outcome_by_id(outcomes: tuple[RNGOutcome, ...], outcome_id: str) -> RNGOutcome | None:
    for outcome in outcomes:
        if outcome.outcome_id == outcome_id:
            return outcome
    return None


def _deterministic_outcome(outcomes: tuple[RNGOutcome, ...], roll: float, decision_kind: str) -> RNGOutcome:
    if decision_kind == "probability":
        cumulative = 0.0
        for outcome in outcomes:
            probability = outcome.probability
            if probability is None:
                continue
            cumulative += max(0.0, min(1.0, probability))
            if roll < cumulative:
                return outcome
        return outcomes[-1]
    weighted = [max(0.0, float(outcome.weight)) if outcome.weight is not None else 1.0 for outcome in outcomes]
    total = sum(weighted)
    if total <= 0:
        index = min(len(outcomes) - 1, int(roll * len(outcomes)))
        return outcomes[index]
    threshold = roll * total
    cumulative = 0.0
    for outcome, weight in zip(outcomes, weighted):
        cumulative += weight
        if threshold < cumulative:
            return outcome
    return outcomes[-1]


def _deterministic_roll(rng_state: str, event_id: str, choice_key: str, outcomes: list[dict[str, JSONValue]]) -> float:
    raw = json.dumps(
        {
            "rng_state": rng_state,
            "event_id": event_id,
            "choice_key": choice_key,
            "outcomes": outcomes,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return int(digest, 16) / float(0xFFFFFFFFFFFF)
