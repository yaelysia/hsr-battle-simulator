from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.model import (
    BattleState,
    JSONValue,
    Mutation,
    UnitLifecycleStatus,
    UnitState,
)
from ..unit_eligibility import (
    runtime_unit_is_on_field,
    runtime_unit_lifecycle_status,
    runtime_unit_source_is_targetable,
)
from ..unit_presence import (
    unit_departure_blocked_reason,
    unit_is_departed,
)
from ..core.unit_state_codec import unit_state_to_payload


@dataclass(frozen=True)
class UnitLifecycleView:
    unit_id: str
    status: UnitLifecycleStatus
    hp: float
    is_present: bool
    is_active: bool
    is_defeated: bool
    is_removed: bool
    can_be_action_actor: bool
    can_be_targeted_alive: bool
    can_receive_damage: bool
    can_keep_queue_entries: bool
    blocked_reason: str = ""
    metadata: dict[str, JSONValue] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "unit_id": self.unit_id,
            "status": self.status,
            "hp": self.hp,
            "is_present": self.is_present,
            "is_active": self.is_active,
            "is_defeated": self.is_defeated,
            "is_removed": self.is_removed,
            "can_be_action_actor": self.can_be_action_actor,
            "can_be_targeted_alive": self.can_be_targeted_alive,
            "can_receive_damage": self.can_receive_damage,
            "can_keep_queue_entries": self.can_keep_queue_entries,
            "blocked_reason": self.blocked_reason,
            "metadata": self.metadata or {},
        }


class UnitLifecycleSystem:
    """Shared lifecycle gate for target, queue, timeline, damage and snapshots."""

    VALID_STATUSES = {"active", "defeated", "removed"}

    def view(self, state: BattleState, unit_id: str) -> UnitLifecycleView:
        unit = state.units.get(unit_id)
        if unit is None:
            return UnitLifecycleView(
                unit_id=unit_id,
                status="removed",
                hp=0.0,
                is_present=False,
                is_active=False,
                is_defeated=False,
                is_removed=True,
                can_be_action_actor=False,
                can_be_targeted_alive=False,
                can_receive_damage=False,
                can_keep_queue_entries=False,
                blocked_reason="unit_missing",
            )
        status = self.status_of(unit)
        is_active = status == "active"
        is_defeated = status == "defeated"
        is_removed = status == "removed"
        summon_kind = str(unit.flags.get("summon_kind") or "")
        lifecycle_source = unit.flags.get("lifecycle_source")
        lifecycle_source = lifecycle_source if isinstance(lifecycle_source, dict) else {}
        presence = str(lifecycle_source.get("presence") or "") if summon_kind else "field"
        source_admitted = lifecycle_source.get("admission_status") == "executable" if summon_kind else True
        departure_reason = unit_departure_blocked_reason(unit)
        is_departed = unit_is_departed(unit)
        is_present = runtime_unit_is_on_field(unit)
        targetable = runtime_unit_source_is_targetable(unit)
        actionable = lifecycle_source.get("actionable") is True if summon_kind else True
        timeline_admitted = (
            lifecycle_source.get("timeline_admitted") is True or unit.flags.get("timeline_admitted") is True
            if summon_kind
            else True
        )
        can_act = is_active and is_present and actionable and timeline_admitted
        can_target = is_active and is_present and targetable
        reason = ""
        if is_removed:
            reason = "unit_removed"
        elif is_defeated:
            reason = "unit_defeated"
        elif departure_reason:
            reason = departure_reason
        elif is_departed:
            reason = "unit_departed"
        elif summon_kind and not source_admitted:
            reason = "summon_lifecycle_source_not_admitted"
        elif summon_kind and not is_present:
            reason = f"summon_presence_not_field:{presence or 'missing'}"
        elif summon_kind and not targetable:
            reason = "summon_targetable_not_admitted"
        elif summon_kind and not actionable:
            reason = "summon_actionable_not_admitted"
        elif summon_kind and not timeline_admitted:
            reason = "summon_timeline_not_admitted"
        return UnitLifecycleView(
            unit_id=unit_id,
            status=status,
            hp=float(unit.hp),
            is_present=is_present,
            is_active=is_active,
            is_defeated=is_defeated,
            is_removed=is_removed,
            can_be_action_actor=can_act,
            can_be_targeted_alive=can_target,
            can_receive_damage=can_target,
            can_keep_queue_entries=not is_removed and (not summon_kind or can_act),
            blocked_reason=reason,
            metadata={
                "lifecycle_status": unit.lifecycle_status,
                "lifecycle_authority": "unit_state.lifecycle_status",
                "summon_kind": summon_kind,
                "presence": presence,
                "departed": is_departed,
                "departure_blocked_reason": departure_reason,
                "targetable": targetable,
                "actionable": actionable,
                "timeline_admitted": timeline_admitted,
                "lifecycle_source": lifecycle_source,
            },
        )

    def status_of(self, unit: UnitState) -> UnitLifecycleStatus:
        return runtime_unit_lifecycle_status(unit)  # type: ignore[return-value]

    def can_act(self, state: BattleState, unit_id: str) -> tuple[bool, str]:
        view = self.view(state, unit_id)
        return view.can_be_action_actor, "" if view.can_be_action_actor else view.blocked_reason

    def can_target(
        self,
        state: BattleState,
        unit_id: str,
        *,
        allow_defeated: bool = False,
    ) -> tuple[bool, str]:
        view = self.view(state, unit_id)
        if view.is_removed or not view.is_present:
            return False, view.blocked_reason
        if view.is_defeated and not allow_defeated:
            return False, "unit_defeated"
        if view.is_defeated and allow_defeated:
            return True, ""
        return view.can_be_targeted_alive, "" if view.can_be_targeted_alive else view.blocked_reason

    def can_receive_damage(self, state: BattleState, unit_id: str) -> tuple[bool, str]:
        view = self.view(state, unit_id)
        return view.can_receive_damage, "" if view.can_receive_damage else view.blocked_reason

    def with_status(self, unit: UnitState, status: UnitLifecycleStatus) -> UnitState:
        return replace(unit, lifecycle_status=status)

    def spawn_mutation(
        self,
        state: BattleState,
        unit: UnitState,
        *,
        reason: str,
        source: str,
        source_trace: dict[str, JSONValue],
        metadata: dict[str, JSONValue] | None = None,
    ) -> Mutation:
        unit = self.with_status(unit, "active")
        return Mutation(
            op="spawn",
            path=("units", unit.unit_id),
            before=None,
            after=unit_state_to_payload(unit),
            reason=reason,
            source=source,
            before_exists=False,
            metadata={
                **(metadata or {}),
                "lifecycle_operation": "unit_spawn",
                "lifecycle_status_before": None,
                "lifecycle_status_after": "active",
                "source_trace": source_trace,
            },
        )

    def defeat_mutation(
        self,
        state: BattleState,
        unit_id: str,
        *,
        reason: str,
        source: str,
        source_trace: dict[str, JSONValue],
        defeat_record: dict[str, JSONValue],
        metadata: dict[str, JSONValue] | None = None,
    ) -> Mutation | None:
        unit = state.units.get(unit_id)
        if unit is None:
            return None
        before_status = self.status_of(unit)
        if before_status != "active":
            return None
        return Mutation(
            op="set",
            path=("units", unit_id, "lifecycle_status"),
            before=unit.lifecycle_status,
            after="defeated",
            reason=reason,
            source=source,
            before_exists=True,
            metadata={
                **(metadata or {}),
                "lifecycle_operation": "unit_defeat",
                "lifecycle_status_before": before_status,
                "lifecycle_status_after": "defeated",
                "defeat_record": defeat_record,
                "source_trace": source_trace,
            },
        )

    def defeat_record_mutation(
        self,
        state: BattleState,
        unit_id: str,
        *,
        reason: str,
        source: str,
        defeat_record: dict[str, JSONValue],
        source_trace: dict[str, JSONValue],
        metadata: dict[str, JSONValue] | None = None,
    ) -> Mutation | None:
        unit = state.units.get(unit_id)
        if unit is None:
            return None
        return Mutation(
            op="set",
            path=("units", unit_id, "flags", "defeat_record"),
            before=unit.flags.get("defeat_record"),
            after=defeat_record,
            reason=reason,
            source=source,
            before_exists="defeat_record" in unit.flags,
            metadata={
                **(metadata or {}),
                "lifecycle_operation": "unit_defeat_record",
                "source_trace": source_trace,
            },
        )

    def remove_mutations(
        self,
        state: BattleState,
        unit_id: str,
        *,
        reason: str,
        source: str,
        removed_record: dict[str, JSONValue],
        source_trace: dict[str, JSONValue],
    ) -> tuple[Mutation, ...]:
        unit = state.units.get(unit_id)
        if unit is None:
            return ()
        before_status = self.status_of(unit)
        common = {
            "source_trace": source_trace,
            "removed_record": removed_record,
            # OnListenAvatarBaseTypeChange observes the effective roster
            # composition.  Keep the departing unit's typed path on the
            # trusted lifecycle mutation because the unit may no longer be
            # queryable after the mutation is reduced.
            "removed_unit_base_type": _unit_base_type(unit),
        }
        return (
            Mutation(
                op="set",
                path=("units", unit_id, "lifecycle_status"),
                before=unit.lifecycle_status,
                after="removed",
                reason=reason,
                source=source,
                before_exists=True,
                metadata={
                    **common,
                    "lifecycle_operation": "unit_remove",
                    "lifecycle_status_before": before_status,
                    "lifecycle_status_after": "removed",
                },
            ),
            Mutation(
                op="set",
                path=("units", unit_id, "flags", "removed_record"),
                before=unit.flags.get("removed_record"),
                after=removed_record,
                reason=reason,
                source=source,
                before_exists="removed_record" in unit.flags,
                metadata={**common, "lifecycle_operation": "unit_remove_record"},
            ),
        )

    def revive_blocked(self, state: BattleState, unit_id: str, *, reason: str = "unit_revive_source_missing") -> dict[str, JSONValue]:
        return {
            "ok": False,
            "operation": "unit_revive",
            "unit_id": unit_id,
            "blocked_reason": reason,
            "state_unchanged": True,
        }


def _unit_base_type(unit: UnitState) -> str:
    for key in ("avatar_base_type", "path", "base_type"):
        value = unit.flags.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
