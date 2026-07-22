from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceEventContract:
    """Authoritative mapping between resource state, events and callbacks."""

    contract_id: str
    resource_kind: str
    payload_resource: str
    state_path_pattern: tuple[str, ...]
    before_event_type: str
    after_event_type: str
    before_callback_events: tuple[str, ...]
    after_callback_events: tuple[str, ...]
    scope_kind: str

    def matches_state_path(self, path: tuple[str, ...]) -> bool:
        if len(path) != len(self.state_path_pattern):
            return False
        return all(
            expected == "{unit_id}" or expected == actual
            for expected, actual in zip(self.state_path_pattern, path, strict=True)
        )

    @property
    def production_event_types(self) -> tuple[str, ...]:
        return tuple(
            event_type
            for event_type in (self.before_event_type, self.after_event_type)
            if event_type
        )

    @property
    def callback_events(self) -> tuple[str, ...]:
        return (*self.before_callback_events, *self.after_callback_events)


TEAM_SKILL_POINT_EVENT_CONTRACT = ResourceEventContract(
    contract_id="resource_event:team_skill_points:v1",
    resource_kind="team_skill_points",
    payload_resource="skill_points",
    state_path_pattern=("skill_points",),
    before_event_type="",
    after_event_type="bp.change",
    before_callback_events=(),
    after_callback_events=("OnListenBpChange",),
    scope_kind="global_listener",
)

UNIT_ENERGY_EVENT_CONTRACT = ResourceEventContract(
    contract_id="resource_event:unit_energy:v1",
    resource_kind="unit_energy",
    payload_resource="energy",
    state_path_pattern=("units", "{unit_id}", "energy"),
    before_event_type="energy.before_change",
    after_event_type="energy.change",
    before_callback_events=("OnBeforeEnergyPointChange",),
    after_callback_events=("OnEnergyPointChange", "OnSPChange"),
    scope_kind="being_hit_target_local",
)

RESOURCE_EVENT_CONTRACTS = (
    TEAM_SKILL_POINT_EVENT_CONTRACT,
    UNIT_ENERGY_EVENT_CONTRACT,
)

# This name is intentionally unavailable to production dispatch.  Validators
# may forge it to prove the retired SP=team-skill-point interpretation fails.
RETIRED_RESOURCE_EVENT_TYPES = frozenset({"sp.change"})


def resource_event_contract_for_path(
    path: tuple[str, ...],
) -> ResourceEventContract | None:
    matches = tuple(
        contract
        for contract in RESOURCE_EVENT_CONTRACTS
        if contract.matches_state_path(path)
    )
    if len(matches) > 1:
        raise ValueError(f"ambiguous resource event path contract: {path!r}")
    return matches[0] if matches else None


def resource_event_contract_for_event(
    event_type: str,
) -> ResourceEventContract | None:
    matches = tuple(
        contract
        for contract in RESOURCE_EVENT_CONTRACTS
        if event_type in contract.production_event_types
    )
    if len(matches) > 1:
        raise ValueError(f"ambiguous resource event type contract: {event_type}")
    return matches[0] if matches else None


def resource_event_contract_for_callback(
    callback_event: str,
) -> ResourceEventContract | None:
    matches = tuple(
        contract
        for contract in RESOURCE_EVENT_CONTRACTS
        if callback_event in contract.callback_events
    )
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous resource callback event contract: {callback_event}"
        )
    return matches[0] if matches else None


def resource_production_event_types() -> frozenset[str]:
    return frozenset(
        event_type
        for contract in RESOURCE_EVENT_CONTRACTS
        for event_type in contract.production_event_types
    )


def resource_callback_runtime_sources() -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for contract in RESOURCE_EVENT_CONTRACTS:
        for callback_event in contract.before_callback_events:
            result[callback_event] = (contract.before_event_type,)
        for callback_event in contract.after_callback_events:
            result[callback_event] = (contract.after_event_type,)
    return result


def resource_scope_for_event(event_type: str) -> str:
    contract = resource_event_contract_for_event(event_type)
    return contract.scope_kind if contract is not None else ""


def resource_scope_for_callback(callback_event: str) -> str:
    contract = resource_event_contract_for_callback(callback_event)
    return contract.scope_kind if contract is not None else ""


def _validate_contracts() -> None:
    event_types = [
        event_type
        for contract in RESOURCE_EVENT_CONTRACTS
        for event_type in contract.production_event_types
    ]
    callback_events = [
        callback_event
        for contract in RESOURCE_EVENT_CONTRACTS
        for callback_event in contract.callback_events
    ]
    if len(event_types) != len(set(event_types)):
        raise ValueError("resource production event types must be unique")
    if len(callback_events) != len(set(callback_events)):
        raise ValueError("resource callback events must be unique")
    if RETIRED_RESOURCE_EVENT_TYPES & set(event_types):
        raise ValueError("retired resource events cannot be production events")


_validate_contracts()
