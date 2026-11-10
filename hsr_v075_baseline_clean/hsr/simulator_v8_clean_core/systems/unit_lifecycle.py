from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ..core.immutable_json import thaw_json
from ..core.model import (
    BattleState,
    GameEvent,
    JSONValue,
    Mutation,
    PendingDefeatPlan,
    UnitLifecycleStatus,
    UnitState,
    current_max_hp,
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
from .mutation_events import mutation_backed_event_id


# 致命伤阶段只在目标身上有状态监听 OnBeforeMortallyWonded 时作为窗口起点；
# 其余情况下窗口仍从 before_dying 开始（见 DamageSystem._with_pending_defeat）。
MORTAL_WOUND_EVENT = "unit.before_mortally_wounded"
LIMBO_CALLBACKS = (
    (MORTAL_WOUND_EVENT, "OnBeforeMortallyWonded", "before_mortally_wounded"),
    ("unit.before_dying", "OnBeforeDying", "before_dying"),
    ("unit.being_limbo", "OnBeingLimbo", "limbo"),
    ("unit.limbo_wait_heal", "OnLimboWaitHeal", "limbo_waiting"),
)


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
    def death_settlement_blocked_reason(self, state: BattleState) -> str:
        """Read the lifecycle state already produced by the typed damage transaction."""
        for unit in state.units.values():
            if unit.hp <= 0 and unit.lifecycle_status not in {"defeated", "removed"}:
                return f"death_settlement_incomplete:{unit.unit_id}"
        return ""

    """Shared lifecycle gate for target, queue, timeline, damage and snapshots."""

    VALID_STATUSES = {"active", "limbo", "defeated", "removed"}

    def pending_defeat(self, state: BattleState, unit_id: str) -> PendingDefeatPlan | None:
        unit = state.units.get(unit_id)
        if unit is None:
            raise ValueError("pending_defeat_unit_missing")
        raw = unit.flags.get("pending_defeat")
        if raw is None:
            if unit.lifecycle_status == "limbo":
                raise ValueError("limbo_unit_missing_pending_defeat")
            return None
        plan = PendingDefeatPlan.from_json(raw)
        if (unit.lifecycle_status != "limbo" or unit.hp != 0 or plan.unit_id != unit_id
                or plan.event_index > state.event_index):
            raise ValueError("pending_defeat_state_mismatch")
        return plan

    def begin_limbo_mutations(self, state: BattleState, plan: PendingDefeatPlan) -> tuple[Mutation, ...]:
        if type(plan) is not PendingDefeatPlan:
            raise ValueError("pending_defeat_plan_required")
        unit = state.units.get(plan.unit_id)
        if (unit is None or unit.lifecycle_status != "active"
                or unit.hp != plan.hp_mutation.before or plan.event_index != state.event_index
                or "pending_defeat" in unit.flags or "defeat_record" in unit.flags):
            raise ValueError("pending_defeat_begin_state_invalid")
        metadata = {"pending_defeat_id": plan.pending_id,
                    "hp_mutation_id": plan.hp_mutation.stable_id(), "source_frame": plan.source_frame,
                    "source_trace": plan.source_trace, "lifecycle_operation": "unit_enter_limbo"}
        return (
            Mutation("set", ("units", unit.unit_id, "flags", "pending_defeat"), None, plan.to_json(),
                     "retain the native lethal cause", "damage_system", before_exists=False, metadata=metadata),
            self.limbo_status_mutation(plan),
        )

    def limbo_status_mutation(self, plan: PendingDefeatPlan) -> Mutation:
        return Mutation("set", ("units", plan.unit_id, "lifecycle_status"), "active", "limbo",
            "enter the rescue window before final defeat", "damage_system", metadata={
                "pending_defeat_id": plan.pending_id, "hp_mutation_id": plan.hp_mutation.stable_id(),
                "source_frame": plan.source_frame, "source_trace": plan.source_trace,
                "lifecycle_operation": "unit_enter_limbo",
            })

    def limbo_events(self, plan: PendingDefeatPlan) -> tuple[GameEvent, ...]:
        terminal = plan.terminal_event
        if terminal is None:
            raise ValueError("pending_defeat_terminal_event_missing")
        lifecycle_id = self.limbo_status_mutation(plan).stable_id()
        return tuple(GameEvent(
            event_type=event_type, source_id=plan.kill_credit_owner_id, target_id=plan.unit_id,
            event_id=mutation_backed_event_id(lifecycle_id, event_type), window=callback,
            payload={**terminal.payload, "callback_events": [callback], "listener_scope": "owner_local",
                     "death_transition_stage": stage, "lifecycle_mutation_id": lifecycle_id,
                     "pending_defeat_id": plan.pending_id, "param_entity_id": plan.unit_id},
            pending_defeat_plan=plan,
        ) for event_type, callback, stage in LIMBO_CALLBACKS)

    def finalize_pending_defeat_mutations(
        self, state: BattleState, plan: PendingDefeatPlan,
    ) -> tuple[Mutation, ...]:
        if type(plan) is not PendingDefeatPlan:
            raise ValueError("pending_defeat_plan_required")
        current = self.pending_defeat(state, plan.unit_id)
        if current is None or current != plan:
            raise ValueError("pending_defeat_finalization_identity_mismatch")
        unit = state.units[plan.unit_id]
        record: dict[str, JSONValue] = {
            "target_id": plan.unit_id, "defeated_unit_id": plan.unit_id,
            "target_before_hp": plan.hp_mutation.before, "target_after_hp": plan.hp_mutation.after,
            "hp_mutation_id": plan.hp_mutation.stable_id(), "pending_defeat_id": plan.pending_id,
            "kill_credit_owner_id": plan.kill_credit_owner_id,
            "source_frame": thaw_json(plan.source_frame), "source_trace": thaw_json(plan.source_trace),
        }
        metadata = {"pending_defeat_id": plan.pending_id,
                    "hp_mutation_id": plan.hp_mutation.stable_id(), "source_frame": plan.source_frame,
                    "source_trace": plan.source_trace, "defeat_record": record,
                    "lifecycle_operation": "unit_defeat",
                    "lifecycle_status_before": "limbo", "lifecycle_status_after": "defeated"}
        defeated = Mutation("set", ("units", plan.unit_id, "lifecycle_status"), "limbo", "defeated",
                            "finalize a lethal hit after the rescue window", "damage_system", metadata=metadata)
        record_mutation = self.defeat_record_mutation(
            state, plan.unit_id, reason="record final defeat after the rescue window", source="damage_system",
            defeat_record={**record, "lifecycle_mutation_id": defeated.stable_id()},
            source_trace=plan.source_trace,
            metadata={**metadata, "lifecycle_mutation_id": defeated.stable_id()},
        )
        assert record_mutation is not None
        return (defeated, record_mutation, Mutation(
            "delete", ("units", plan.unit_id, "flags", "pending_defeat"), unit.flags["pending_defeat"], None,
            "close the pending lethal cause", "damage_system", after_exists=False,
            metadata={**metadata, "lifecycle_operation": "unit_pending_defeat_closed"},
        ))

    def rescue_from_limbo_mutations(
        self, state: BattleState, plan: PendingDefeatPlan, hp_mutation: Mutation,
    ) -> tuple[Mutation, ...]:
        if type(plan) is not PendingDefeatPlan:
            raise ValueError("pending_defeat_plan_required")
        current = self.pending_defeat(state, plan.unit_id)
        unit = state.units[plan.unit_id]
        if (current is None or current != plan or type(hp_mutation) is not Mutation
                or hp_mutation.op != "set" or hp_mutation.path != ("units", plan.unit_id, "hp")
                or not hp_mutation.before_exists or not hp_mutation.after_exists
                or type(hp_mutation.before) not in (int, float) or hp_mutation.before != unit.hp
                or type(hp_mutation.after) not in (int, float) or not math.isfinite(hp_mutation.after)
                or not 0 < hp_mutation.after <= current_max_hp(unit)):
            raise ValueError("limbo_rescue_requires_its_positive_hp_mutation")
        metadata = {**hp_mutation.metadata, "pending_defeat_id": plan.pending_id,
                    "lethal_hp_mutation_id": plan.hp_mutation.stable_id(),
                    "rescue_hp_mutation_id": hp_mutation.stable_id(), "lifecycle_operation": "unit_limbo_rescued"}
        return (hp_mutation,
            Mutation("set", ("units", plan.unit_id, "lifecycle_status"), "limbo", "active",
                     "restore an admitted pending unit", hp_mutation.source, metadata=metadata),
            Mutation("delete", ("units", plan.unit_id, "flags", "pending_defeat"),
                     unit.flags["pending_defeat"], None, "close a rescued lethal cause", hp_mutation.source,
                     after_exists=False, metadata=metadata))

    def forced_death_mutations(
        self,
        state: BattleState,
        unit_id: str,
        *,
        effect_id: str,
        effect_source: dict[str, JSONValue],
        source_trace: dict[str, JSONValue],
        target_alias: str,
    ) -> tuple[tuple[Mutation, ...], dict[str, JSONValue]]:
        """Produce one formal non-damage death for an active unit.

        ForceKill is lethal without a hit, damage packet or kill credit. The
        produced facts stay at the shared lifecycle boundary: HP reaches 0, the
        lifecycle status becomes defeated, a typed defeat record keeps the
        causal identity, and the caller emits the matching unit.defeated event.
        """

        unit = state.units.get(unit_id)
        if unit is None:
            raise ValueError("forced_death_unit_missing")
        if self.status_of(unit) != "active" or float(unit.hp) <= 0:
            raise ValueError("forced_death_requires_active_target")
        common = {
            "effect_id": effect_id,
            "effect_source": effect_source,
            "source_trace": source_trace,
            "forced_death_kind": "formal_ability_force_kill",
            "forced_death_target_alias": target_alias,
        }
        hp = Mutation(
            "set",
            ("units", unit_id, "hp"),
            unit.hp,
            0.0,
            "formal forced death zeroes HP without a damage packet",
            "effect_system",
            metadata={**common, "lifecycle_operation": "unit_forced_death_hp"},
        )
        record: dict[str, JSONValue] = {
            "target_id": unit_id,
            "defeated_unit_id": unit_id,
            "target_before_hp": unit.hp,
            "target_after_hp": 0.0,
            "hp_mutation_id": hp.stable_id(),
            "forced_death_kind": "formal_ability_force_kill",
            "forced_death_target_alias": target_alias,
            "effect_id": effect_id,
            "effect_source": effect_source,
            "source_trace": source_trace,
        }
        status = Mutation(
            "set",
            ("units", unit_id, "lifecycle_status"),
            unit.lifecycle_status,
            "defeated",
            "formal forced death at the shared lifecycle boundary",
            "effect_system",
            metadata={
                **common,
                "lifecycle_operation": "unit_defeat",
                "lifecycle_status_before": "active",
                "lifecycle_status_after": "defeated",
                "hp_mutation_id": hp.stable_id(),
                "defeat_record": record,
            },
        )
        lifecycle_mutation_id = status.stable_id()
        typed_record = {**record, "lifecycle_mutation_id": lifecycle_mutation_id}
        record_mutation = Mutation(
            "set",
            ("units", unit_id, "flags", "defeat_record"),
            unit.flags.get("defeat_record"),
            typed_record,
            "record the formal forced death cause",
            "effect_system",
            before_exists="defeat_record" in unit.flags,
            metadata={
                **common,
                "lifecycle_operation": "unit_defeat_record",
                "lifecycle_mutation_id": lifecycle_mutation_id,
                "hp_mutation_id": hp.stable_id(),
                "defeat_record": typed_record,
            },
        )
        return (hp, status, record_mutation), typed_record

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
        elif status == "limbo":
            reason = "unit_limbo"
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


def unit_behavior_flags(unit: UnitState) -> frozenset[str]:
    """Active behavior flags carried by the unit's status instances."""

    flags: set[str] = set()
    for detail in unit.flags.get("status_details", ()):
        if not isinstance(detail, dict):
            continue
        if str(detail.get("lifecycle_state") or "active").startswith(
            ("expired", "removed")
        ):
            continue
        for flag in detail.get("behavior_flags", ()):
            if isinstance(flag, str) and flag:
                flags.add(flag)
    return frozenset(flags)


def unit_protected_weakness_types(unit: UnitState) -> frozenset[str]:
    """Weakness types protected by active source-declared status projections."""

    protected: set[str] = set()
    for detail in unit.flags.get("status_details", ()):
        if not isinstance(detail, dict):
            continue
        if str(detail.get("lifecycle_state") or "active").startswith(
            ("expired", "removed")
        ):
            continue
        for element in detail.get("weakness_protection", ()):
            if isinstance(element, str) and element:
                protected.add(element)
    return frozenset(protected)


def _unit_base_type(unit: UnitState) -> str:
    for key in ("avatar_base_type", "path", "base_type"):
        value = unit.flags.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
