from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent
from ..core.settlement import SettlementRecord
from ..rules.ir import ActionDefinitionIR
from .damage_formula import DamageFormulaInput, DirectDamageFormula


DamageFormulaFamily = Literal[
    "direct",
    "dot",
    "break",
    "super_break",
    "true_damage",
    "hp_loss",
    "elation",
]


FOLLOW_UP_ATTACK_TYPE = "follow_up"


@dataclass(frozen=True)
class DamageFamilyPolicy:
    family: str
    runtime_status: str
    record_type: str
    uses_direct_multiplier_ledger: bool
    bypasses_normal_multipliers: bool
    source_requirement: str
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "family": self.family,
            "runtime_status": self.runtime_status,
            "record_type": self.record_type,
            "uses_direct_multiplier_ledger": self.uses_direct_multiplier_ledger,
            "bypasses_normal_multipliers": self.bypasses_normal_multipliers,
            "source_requirement": self.source_requirement,
            "blocked_reason": self.blocked_reason,
        }


DAMAGE_FAMILY_POLICIES: dict[str, DamageFamilyPolicy] = {
    "direct": DamageFamilyPolicy(
        family="direct",
        runtime_status="executable_with_damage_emission",
        record_type="damage",
        uses_direct_multiplier_ledger=True,
        bypasses_normal_multipliers=False,
        source_requirement="executable DamageEmissionIR + HitProfileIR + ActionDefinitionIR",
    ),
    "dot": DamageFamilyPolicy(
        family="dot",
        runtime_status="executable_with_admitted_status_damage_amount",
        record_type="dot_damage",
        uses_direct_multiplier_ledger=False,
        bypasses_normal_multipliers=False,
        source_requirement="executable StatusDamageEmissionIR with final admitted amount",
    ),
    "break": DamageFamilyPolicy(
        family="break",
        runtime_status="executable_with_break_emission",
        record_type="break_damage",
        uses_direct_multiplier_ledger=False,
        bypasses_normal_multipliers=False,
        source_requirement="executable BreakDamageEmissionIR or StatusDamageEmissionIR",
    ),
    "super_break": DamageFamilyPolicy(
        family="super_break",
        runtime_status="executable_with_super_break_emission",
        record_type="super_break_damage",
        uses_direct_multiplier_ledger=False,
        bypasses_normal_multipliers=False,
        source_requirement="executable SuperBreakEmissionIR",
    ),
    "true_damage": DamageFamilyPolicy(
        family="true_damage",
        runtime_status="executable_with_admitted_fixed_amount",
        record_type="damage",
        uses_direct_multiplier_ledger=False,
        bypasses_normal_multipliers=True,
        source_requirement="executable true-damage EffectIR or DamageEmissionIR with admitted amount",
    ),
    "hp_loss": DamageFamilyPolicy(
        family="hp_loss",
        runtime_status="executable_with_admitted_fixed_amount",
        record_type="hp_loss",
        uses_direct_multiplier_ledger=False,
        bypasses_normal_multipliers=True,
        source_requirement="executable hp-loss EffectIR with admitted amount",
    ),
    "elation": DamageFamilyPolicy(
        family="elation",
        runtime_status="blocked",
        record_type="damage_blocked",
        uses_direct_multiplier_ledger=False,
        bypasses_normal_multipliers=False,
        source_requirement="Elation formula inputs admitted from TBGD",
        blocked_reason=(
            "Elation damage is a mainline 4.0 damage formula family, "
            "but the complete TBGD formula inputs are not admitted"
        ),
    ),
}


@dataclass(frozen=True)
class DamageSourceFrame:
    owner_id: str
    source_id: str
    source_kind: str
    sequence_id: str
    target_id: str
    can_continue_after_lethal: bool = False
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "owner_id": self.owner_id,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "sequence_id": self.sequence_id,
            "target_id": self.target_id,
            "can_continue_after_lethal": self.can_continue_after_lethal,
            "source_trace": self.source_trace,
        }


class DamageWindowLedger:
    """Tracks defeated targets inside one action/effect resolution window."""

    def __init__(self) -> None:
        self.defeated_targets: dict[str, dict[str, JSONValue]] = {}

    def admit_packet(self, state: BattleState, packet: "DamagePacket") -> tuple[bool, str, bool]:
        target = state.units.get(packet.target_id)
        if target is None:
            return False, "damage_target_missing", False
        if target.hp > 0:
            return True, "", False
        frame = source_frame_for_packet(packet)
        defeat = self.defeated_targets.get(packet.target_id)
        if (
            defeat
            and frame.can_continue_after_lethal
            and str(defeat.get("damage_sequence_id") or "") == frame.sequence_id
        ):
            return True, "dead_target_same_source_continuation", True
        if defeat:
            return False, "damage_source_target_already_defeated_in_window", False
        return False, "damage_source_target_not_alive", False

    def record_defeat_event(self, event: GameEvent) -> None:
        if event.event_type != "unit.defeated":
            return
        target_id = str(event.payload.get("defeated_unit_id") or event.target_id or "")
        if not target_id:
            return
        self.defeated_targets[target_id] = {
            "target_id": target_id,
            "kill_credit_owner_id": str(event.payload.get("kill_credit_owner_id") or ""),
            "kill_credit_source_id": str(event.payload.get("kill_credit_source_id") or ""),
            "kill_credit_source_kind": str(event.payload.get("kill_credit_source_kind") or ""),
            "damage_sequence_id": str(event.payload.get("damage_sequence_id") or ""),
            "damage_event_id": str(event.payload.get("lethal_damage_event_id") or ""),
            "source_trace": event.payload.get("source_trace", {}),
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {"defeated_targets": self.defeated_targets}


@dataclass(frozen=True)
class DamagePacket:
    attacker_id: str
    target_id: str
    attack_type: str
    damage_formula_family: DamageFormulaFamily
    amount: float | None = None
    damage_kind: str = "hp_damage"
    element_type: str | None = None
    action_definition: ActionDefinitionIR | None = None
    damage_emission_id: str = ""
    break_damage_emission_id: str = ""
    super_break_emission_id: str = ""
    status_damage_emission_id: str = ""
    status_callback_id: str = ""
    status_instance_id: str = ""
    modifier_name: str = ""
    break_template_id: str = ""
    source_task_id: str = ""
    hit_profile_id: str = ""
    scaling_ratio: float | None = None
    scaling_basis: dict[str, JSONValue] = field(default_factory=dict)
    hit_source_trace: dict[str, JSONValue] = field(default_factory=dict)
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    source_frame: DamageSourceFrame | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.damage_formula_family == FOLLOW_UP_ATTACK_TYPE:
            raise ValueError("follow_up is an attack type, not a damage formula family")
        if self.amount is not None and self.amount < 0:
            raise ValueError("damage amount must be non-negative")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "attacker_id": self.attacker_id,
            "target_id": self.target_id,
            "amount": self.amount,
            "attack_type": self.attack_type,
            "damage_kind": self.damage_kind,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "action_definition": _action_definition_summary(self.action_definition),
            "damage_emission_id": self.damage_emission_id,
            "break_damage_emission_id": self.break_damage_emission_id,
            "super_break_emission_id": self.super_break_emission_id,
            "status_damage_emission_id": self.status_damage_emission_id,
            "status_callback_id": self.status_callback_id,
            "status_instance_id": self.status_instance_id,
            "modifier_name": self.modifier_name,
            "break_template_id": self.break_template_id,
            "source_task_id": self.source_task_id,
            "hit_profile_id": self.hit_profile_id,
            "scaling_ratio": self.scaling_ratio,
            "scaling_basis": self.scaling_basis,
            "hit_source_trace": self.hit_source_trace,
            "source_trace": self.source_trace,
            "source_frame": source_frame_for_packet(self).to_json(),
            "metadata": self.metadata,
            "bypasses_normal_multipliers": _family_policy(self.damage_formula_family).bypasses_normal_multipliers,
            "uses_direct_multiplier_ledger": _family_policy(self.damage_formula_family).uses_direct_multiplier_ledger,
        }


@dataclass(frozen=True)
class DamageApplicationResult:
    packet: DamagePacket
    ok: bool
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    errors: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "packet": self.packet.to_json(),
            "events": [event.to_json() for event in self.events],
            "mutations": [mutation.to_json() for mutation in self.mutations],
            "rng_events": [event.to_json() for event in self.rng_events],
            "records": list(self.records),
            "errors": list(self.errors),
        }


class DamageSystem:
    def apply_packet(
        self,
        state: BattleState,
        packet: DamagePacket,
        *,
        window_ledger: DamageWindowLedger | None = None,
    ) -> DamageApplicationResult:
        dead_target_continuation = False
        if window_ledger is not None:
            admitted, reason, dead_target_continuation = window_ledger.admit_packet(state, packet)
            if not admitted:
                return _damage_source_skip(packet, reason, window_ledger)
        if packet.damage_formula_family == "direct":
            result = self._apply_direct_damage(state, packet, dead_target_continuation=dead_target_continuation)
        elif packet.damage_formula_family == "break":
            result = self._apply_break_damage(state, packet, dead_target_continuation=dead_target_continuation)
        elif packet.damage_formula_family == "super_break":
            result = self._apply_super_break_damage(state, packet, dead_target_continuation=dead_target_continuation)
        elif packet.damage_formula_family == "dot":
            result = self._apply_dot_damage(state, packet, dead_target_continuation=dead_target_continuation)
        elif packet.damage_formula_family in {"true_damage", "hp_loss"}:
            result = self._apply_fixed_hp_delta(state, packet, dead_target_continuation=dead_target_continuation)
        elif _family_policy(packet.damage_formula_family).runtime_status == "blocked":
            result = self._blocked_family(packet)
        else:
            result = DamageApplicationResult(
                packet=packet,
                ok=False,
                records=(
                    SettlementRecord(
                        record_type="damage_error",
                        source="damage_system",
                        process_only=True,
                        payload={
                            "error": "unsupported_damage_formula_family",
                            "damage_formula_family": packet.damage_formula_family,
                        },
                        trace=packet.source_trace,
                    ).to_json(),
                ),
                errors=(f"unsupported damage formula family {packet.damage_formula_family!r}",),
            )
        if window_ledger is not None:
            for event in result.events:
                window_ledger.record_defeat_event(event)
        return result

    def _apply_dot_damage(
        self,
        state: BattleState,
        packet: DamagePacket,
        *,
        dead_target_continuation: bool = False,
    ) -> DamageApplicationResult:
        if packet.amount is None:
            return _damage_error(packet, "dot damage requires admitted amount")
        if not packet.status_damage_emission_id:
            return _damage_error(packet, "dot damage requires status_damage_emission_id")
        target = state.units[packet.target_id]
        final_damage = float(packet.amount)
        after = max(0.0, target.hp - final_damage)
        packet_json = packet.to_json()
        metadata = {
            **packet_json,
            **packet.metadata,
            "packet_metadata": packet.metadata,
            "final_damage": final_damage,
            "normal_multiplier_terms": [],
            "uses_direct_multiplier_ledger": False,
            "bypasses_normal_multipliers": False,
        }
        mutation = None if dead_target_continuation else Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason="apply dot damage",
            source="damage_system",
            metadata=metadata,
        )
        record_payload: dict[str, JSONValue] = {
            "amount": final_damage,
            "final_damage": final_damage,
            "attack_type": packet.attack_type,
            "SkillType": packet.metadata.get("SkillType"),
            "skill_type": packet.metadata.get("skill_type"),
            "is_current_skill_active": packet.metadata.get("is_current_skill_active"),
            "damage_kind": packet.damage_kind,
            "damage_formula_family": packet.damage_formula_family,
            "element_type": packet.element_type,
            "status_damage_emission_id": packet.status_damage_emission_id,
            "status_callback_id": packet.status_callback_id,
            "status_instance_id": packet.status_instance_id,
            "modifier_name": packet.modifier_name,
            "source_task_id": packet.source_task_id,
            "packet_metadata": packet.metadata,
            "source_frame": packet_json["source_frame"],
            "bypasses_normal_multipliers": False,
            "uses_direct_multiplier_ledger": False,
            "normal_multiplier_terms": [],
            "numeric_evaluation": packet.metadata.get("numeric_evaluation", {}),
            "target_before_hp": target.hp,
            "target_after_hp": after,
        }
        if dead_target_continuation:
            record_payload["dead_target_continuation"] = True
            record_payload["continuation_reason"] = "same_damage_sequence_after_lethal"
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=_damage_events(
                packet,
                record_type="dot_damage",
                amount=final_damage,
                before_hp=target.hp,
                after_hp=after,
            ),
            mutations=(mutation,) if mutation is not None else (),
            records=(
                SettlementRecord(
                    record_type="dot_damage",
                    source="damage_system",
                    mutation_id=mutation.stable_id() if mutation is not None else None,
                    process_only=mutation is None,
                    payload=record_payload,
                    trace=packet.source_trace,
                ).to_json(),
            ),
        )

    def _apply_direct_damage(
        self,
        state: BattleState,
        packet: DamagePacket,
        *,
        dead_target_continuation: bool = False,
    ) -> DamageApplicationResult:
        if packet.action_definition is None:
            return _damage_error(packet, "direct damage requires action_definition")
        if packet.scaling_ratio is None:
            return _damage_error(packet, "direct damage requires hit_profile scaling_ratio")
        try:
            formula_result = DirectDamageFormula().calculate(
                DamageFormulaInput(
                    state=state,
                    attacker_id=packet.attacker_id,
                    target_id=packet.target_id,
                    action_definition=packet.action_definition,
                    attack_type=packet.attack_type,
                    element_type=packet.element_type,
                    scaling_ratio=packet.scaling_ratio,
                    scaling_basis=packet.scaling_basis,
                    source_trace=packet.source_trace,
                    crit_mode=_metadata_str(packet.metadata, "crit_mode"),
                    direct_modifier_terms=_direct_modifier_terms_from_metadata(packet.metadata),
                )
            )
        except ValueError as exc:
            return _damage_error(packet, str(exc))

        target = state.units[packet.target_id]
        final_damage = formula_result.final_damage
        after = max(0.0, target.hp - final_damage)
        formula_json = formula_result.to_json()
        packet_json = packet.to_json()
        record_payload: dict[str, JSONValue] = {
            "amount": final_damage,
            "final_damage": final_damage,
            "attack_type": packet.attack_type,
            "SkillType": packet.metadata.get("SkillType"),
            "skill_type": packet.metadata.get("skill_type"),
            "damage_kind": packet.damage_kind,
            "damage_formula_family": packet.damage_formula_family,
            "element_type": packet.element_type,
            "damage_emission_id": packet.damage_emission_id,
            "source_task_id": packet.source_task_id,
            "hit_profile_id": packet.hit_profile_id,
            "scaling_ratio": packet.scaling_ratio,
            "hit_source_trace": packet.hit_source_trace,
            "packet_metadata": packet.metadata,
            "hit_index": packet.metadata.get("hit_index"),
            "target_group": packet.metadata.get("target_group"),
            "target_selection_policy": packet.metadata.get("target_selection_policy", {}),
            "source_frame": packet_json["source_frame"],
            "bypasses_normal_multipliers": False,
            "normal_multiplier_terms": formula_json["modifier_ledger"]["applied_terms"],
            "formula_result": formula_json,
            "modifier_ledger": formula_json["modifier_ledger"],
            "crit_resolution": formula_json["crit_resolution"],
            "target_before_hp": target.hp,
            "target_after_hp": after,
        }
        if dead_target_continuation:
            record_payload["dead_target_continuation"] = True
            record_payload["continuation_reason"] = "same_damage_sequence_after_lethal"
            return DamageApplicationResult(
                packet=packet,
                ok=True,
                events=_damage_events(
                    packet,
                    record_type="damage",
                    amount=final_damage,
                    before_hp=target.hp,
                    after_hp=target.hp,
                ),
                rng_events=formula_result.rng_events,
                records=(
                    SettlementRecord(
                        record_type="damage",
                        source="damage_system",
                        process_only=True,
                        payload=record_payload,
                        trace=packet.source_trace,
                    ).to_json(),
                ),
            )
        mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason="apply direct damage formula",
            source="damage_system",
            metadata={
                **packet_json,
                **packet.metadata,
                "packet_metadata": packet.metadata,
                "formula_result": formula_json,
                "modifier_ledger": formula_json["modifier_ledger"],
                "crit_resolution": formula_json["crit_resolution"],
                "final_damage": final_damage,
            },
        )
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=_damage_events(
                packet,
                record_type="damage",
                amount=final_damage,
                before_hp=target.hp,
                after_hp=after,
            ),
            mutations=(mutation,),
            rng_events=formula_result.rng_events,
            records=(
                SettlementRecord(
                    record_type="damage",
                    source="damage_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload=record_payload,
                    trace=packet.source_trace,
                ).to_json(),
            ),
        )

    def _apply_break_damage(
        self,
        state: BattleState,
        packet: DamagePacket,
        *,
        dead_target_continuation: bool = False,
    ) -> DamageApplicationResult:
        if packet.amount is None:
            return _damage_error(packet, "break damage requires admitted amount")
        if not packet.break_damage_emission_id and not packet.status_damage_emission_id:
            return _damage_error(packet, "break damage requires break_damage_emission_id or status_damage_emission_id")
        if not packet.break_template_id:
            return _damage_error(packet, "break damage requires break_template_id")
        target = state.units[packet.target_id]
        final_damage = float(packet.amount)
        after = max(0.0, target.hp - final_damage)
        packet_json = packet.to_json()
        metadata = {
            **packet_json,
            **packet.metadata,
            "packet_metadata": packet.metadata,
            "final_damage": final_damage,
            "normal_multiplier_terms": [],
        }
        record_type = "break_dot_tick" if packet.status_damage_emission_id else "break_damage"
        reason = "apply break status DOT tick" if packet.status_damage_emission_id else "apply normal break damage"
        mutation = None if dead_target_continuation else Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason=reason,
            source="damage_system",
            metadata=metadata,
        )
        record_payload: dict[str, JSONValue] = {
            "amount": final_damage,
            "final_damage": final_damage,
            "attack_type": packet.attack_type,
            "SkillType": packet.metadata.get("SkillType"),
            "skill_type": packet.metadata.get("skill_type"),
            "damage_kind": packet.damage_kind,
            "damage_formula_family": packet.damage_formula_family,
            "element_type": packet.element_type,
            "break_template_id": packet.break_template_id,
            "break_damage_emission_id": packet.break_damage_emission_id,
            "status_damage_emission_id": packet.status_damage_emission_id,
            "status_callback_id": packet.status_callback_id,
            "status_instance_id": packet.status_instance_id,
            "modifier_name": packet.modifier_name,
            "source_task_id": packet.source_task_id,
            "hit_profile_id": packet.hit_profile_id,
            "packet_metadata": packet.metadata,
            "source_frame": packet_json["source_frame"],
            "bypasses_normal_multipliers": False,
            "normal_multiplier_terms": [],
            "numeric_evaluation": packet.metadata.get("numeric_evaluation", {}),
            "break_base_damage_source": packet.metadata.get("break_base_damage_source", {}),
            "target_before_hp": target.hp,
            "target_after_hp": after,
        }
        if dead_target_continuation:
            record_payload["dead_target_continuation"] = True
            record_payload["continuation_reason"] = "same_damage_sequence_after_lethal"
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=_damage_events(
                packet,
                record_type=record_type,
                amount=final_damage,
                before_hp=target.hp,
                after_hp=after,
            ),
            mutations=(mutation,) if mutation is not None else (),
            records=(
                SettlementRecord(
                    record_type=record_type,
                    source="damage_system",
                    mutation_id=mutation.stable_id() if mutation is not None else None,
                    process_only=mutation is None,
                    payload=record_payload,
                    trace=packet.source_trace,
                ).to_json(),
            ),
        )

    def _apply_super_break_damage(
        self,
        state: BattleState,
        packet: DamagePacket,
        *,
        dead_target_continuation: bool = False,
    ) -> DamageApplicationResult:
        if packet.amount is None:
            return _damage_error(packet, "super break damage requires admitted amount")
        if not packet.super_break_emission_id:
            return _damage_error(packet, "super break damage requires super_break_emission_id")
        target = state.units[packet.target_id]
        final_damage = float(packet.amount)
        after = max(0.0, target.hp - final_damage)
        packet_json = packet.to_json()
        metadata = {
            **packet_json,
            **packet.metadata,
            "packet_metadata": packet.metadata,
            "final_damage": final_damage,
            "normal_multiplier_terms": [],
            "super_break_ledger": packet.metadata.get("super_break_ledger", {}),
        }
        mutation = None if dead_target_continuation else Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason="apply super break damage",
            source="damage_system",
            metadata=metadata,
        )
        record_payload: dict[str, JSONValue] = {
            "amount": final_damage,
            "final_damage": final_damage,
            "attack_type": packet.attack_type,
            "damage_kind": packet.damage_kind,
            "damage_formula_family": packet.damage_formula_family,
            "element_type": packet.element_type,
            "super_break_emission_id": packet.super_break_emission_id,
            "break_template_id": packet.break_template_id,
            "source_task_id": packet.source_task_id,
            "packet_metadata": packet.metadata,
            "source_frame": packet_json["source_frame"],
            "bypasses_normal_multipliers": False,
            "normal_multiplier_terms": [],
            "super_break_ledger": packet.metadata.get("super_break_ledger", {}),
            "numeric_evaluation": packet.metadata.get("numeric_evaluation", {}),
            "break_base_damage_source": packet.metadata.get("break_base_damage_source", {}),
            "target_before_hp": target.hp,
            "target_after_hp": after,
        }
        if dead_target_continuation:
            record_payload["dead_target_continuation"] = True
            record_payload["continuation_reason"] = "same_damage_sequence_after_lethal"
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=_damage_events(
                packet,
                record_type="super_break_damage",
                amount=final_damage,
                before_hp=target.hp,
                after_hp=after,
            ),
            mutations=(mutation,) if mutation is not None else (),
            records=(
                SettlementRecord(
                    record_type="super_break_damage",
                    source="damage_system",
                    mutation_id=mutation.stable_id() if mutation is not None else None,
                    process_only=mutation is None,
                    payload=record_payload,
                    trace=packet.source_trace,
                ).to_json(),
            ),
        )

    def _apply_fixed_hp_delta(
        self,
        state: BattleState,
        packet: DamagePacket,
        *,
        dead_target_continuation: bool = False,
    ) -> DamageApplicationResult:
        if packet.amount is None:
            return _damage_error(packet, f"{packet.damage_formula_family} requires fixed amount")
        target = state.units[packet.target_id]
        after = max(0.0, target.hp - packet.amount)
        packet_json = packet.to_json()
        metadata = {**packet_json, **packet.metadata, "packet_metadata": packet.metadata}
        mutation = None if dead_target_continuation else Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason="apply damage packet",
            source="damage_system",
            metadata=metadata,
        )
        policy = _family_policy(packet.damage_formula_family)
        record_type = policy.record_type
        record_payload: dict[str, JSONValue] = {
            "amount": packet.amount,
            "attack_type": packet.attack_type,
            "damage_kind": packet.damage_kind,
            "damage_formula_family": packet.damage_formula_family,
            "element_type": packet.element_type,
            "damage_emission_id": packet.damage_emission_id,
            "source_task_id": packet.source_task_id,
            "hit_profile_id": packet.hit_profile_id,
            "packet_metadata": packet.metadata,
            "source_frame": packet_json["source_frame"],
            "bypasses_normal_multipliers": policy.bypasses_normal_multipliers,
            "uses_direct_multiplier_ledger": policy.uses_direct_multiplier_ledger,
            "normal_multiplier_terms": [],
            "target_before_hp": target.hp,
            "target_after_hp": after,
        }
        if dead_target_continuation:
            record_payload["dead_target_continuation"] = True
            record_payload["continuation_reason"] = "same_damage_sequence_after_lethal"
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=_damage_events(
                packet,
                record_type=record_type,
                amount=float(packet.amount),
                before_hp=target.hp,
                after_hp=after,
            ),
            mutations=(mutation,) if mutation is not None else (),
            records=(
                SettlementRecord(
                    record_type=record_type,
                    source="damage_system",
                    mutation_id=mutation.stable_id() if mutation is not None else None,
                    process_only=mutation is None,
                    payload=record_payload,
                    trace=packet.source_trace,
                ).to_json(),
            ),
        )

    def _blocked_family(self, packet: DamagePacket) -> DamageApplicationResult:
        policy = _family_policy(packet.damage_formula_family)
        reason = policy.blocked_reason or f"{packet.damage_formula_family} damage family is not executable"
        return DamageApplicationResult(
            packet=packet,
            ok=False,
            records=(
                SettlementRecord(
                    record_type="damage_blocked",
                    source="damage_system",
                    process_only=True,
                    payload={
                        "damage_formula_family": packet.damage_formula_family,
                        "attack_type": packet.attack_type,
                        "reason": reason,
                        "family_policy": policy.to_json(),
                    },
                    trace=packet.source_trace,
                ).to_json(),
            ),
            errors=(reason,),
        )


def _damage_error(packet: DamagePacket, error: str) -> DamageApplicationResult:
    return DamageApplicationResult(
        packet=packet,
        ok=False,
        records=(
            SettlementRecord(
                record_type="damage_error",
                source="damage_system",
                process_only=True,
                payload={
                    "error": error,
                    "damage_formula_family": packet.damage_formula_family,
                },
                trace=packet.source_trace,
            ).to_json(),
        ),
        errors=(error,),
    )


def _damage_source_skip(
    packet: DamagePacket,
    reason: str,
    window_ledger: DamageWindowLedger | None,
) -> DamageApplicationResult:
    source_frame = source_frame_for_packet(packet)
    return DamageApplicationResult(
        packet=packet,
        ok=True,
        records=(
            SettlementRecord(
                record_type="damage_source_skipped",
                source="damage_system",
                process_only=True,
                payload={
                    "reason": reason,
                    "target_id": packet.target_id,
                    "attacker_id": packet.attacker_id,
                    "damage_formula_family": packet.damage_formula_family,
                    "attack_type": packet.attack_type,
                    "damage_emission_id": packet.damage_emission_id,
                    "status_damage_emission_id": packet.status_damage_emission_id,
                    "source_task_id": packet.source_task_id,
                    "hit_profile_id": packet.hit_profile_id,
                    "source_frame": source_frame.to_json(),
                    "damage_window_ledger": window_ledger.to_json() if window_ledger is not None else {},
                },
                trace=packet.source_trace,
            ).to_json(),
        ),
    )


def _metadata_str(metadata: dict[str, JSONValue], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if isinstance(value, str) else None


def _direct_modifier_terms_from_metadata(metadata: dict[str, JSONValue]) -> tuple[dict[str, JSONValue], ...]:
    value = metadata.get("direct_modifier_terms")
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def source_frame_for_packet(packet: DamagePacket) -> DamageSourceFrame:
    if packet.source_frame is not None:
        return packet.source_frame
    metadata = packet.metadata
    owner_id = _metadata_str(metadata, "damage_source_owner_id") or _metadata_str(metadata, "kill_credit_owner_id")
    source_id = _metadata_str(metadata, "damage_source_id") or _metadata_str(metadata, "kill_credit_source_id")
    source_kind = _metadata_str(metadata, "damage_source_kind") or _metadata_str(metadata, "kill_credit_source_kind")
    sequence_id = _metadata_str(metadata, "damage_sequence_id")
    if not owner_id:
        owner_id = packet.attacker_id
    if not source_id:
        source_id = _default_source_id(packet)
    if not source_kind:
        source_kind = _default_source_kind(packet)
    if not sequence_id:
        sequence_id = f"{owner_id}:{source_id}"
    can_continue = bool(metadata.get("can_continue_after_lethal", False))
    trace = metadata.get("damage_source_trace")
    return DamageSourceFrame(
        owner_id=owner_id,
        source_id=source_id,
        source_kind=source_kind,
        sequence_id=sequence_id,
        target_id=packet.target_id,
        can_continue_after_lethal=can_continue,
        source_trace=trace if isinstance(trace, dict) else packet.source_trace,
    )


def _family_policy(family: str) -> DamageFamilyPolicy:
    key = str(family or "")
    return DAMAGE_FAMILY_POLICIES.get(
        key,
        DamageFamilyPolicy(
            family=key or "unknown",
            runtime_status="unsupported",
            record_type="damage_error",
            uses_direct_multiplier_ledger=False,
            bypasses_normal_multipliers=False,
            source_requirement="unsupported damage formula family",
            blocked_reason=f"unsupported damage formula family {family!r}",
        ),
    )


def _default_source_id(packet: DamagePacket) -> str:
    for value in (
        packet.damage_emission_id,
        packet.status_damage_emission_id,
        packet.break_damage_emission_id,
        packet.super_break_emission_id,
        packet.metadata.get("effect_id"),
        packet.source_task_id,
        packet.hit_profile_id,
    ):
        if isinstance(value, str) and value:
            return value
    if packet.action_definition is not None:
        return f"{packet.action_definition.action_id}:level:{packet.action_definition.level}"
    return f"{packet.damage_formula_family}:{packet.attack_type}"


def _default_source_kind(packet: DamagePacket) -> str:
    if packet.status_damage_emission_id:
        return "status_damage"
    if packet.metadata.get("effect_id"):
        return "effect_damage"
    if packet.break_damage_emission_id:
        return "break_damage"
    if packet.super_break_emission_id:
        return "super_break_damage"
    if packet.damage_formula_family == "hp_loss":
        return "hp_loss"
    return "action_damage"


def _damage_events(
    packet: DamagePacket,
    *,
    record_type: str,
    amount: float,
    before_hp: float,
    after_hp: float,
) -> tuple[GameEvent, ...]:
    hit_event = _damage_hit_event(
        packet,
        record_type=record_type,
        amount=amount,
        before_hp=before_hp,
        after_hp=after_hp,
    )
    defeat_event = _damage_defeat_event(
        packet,
        hit_event=hit_event,
        record_type=record_type,
        amount=amount,
        before_hp=before_hp,
        after_hp=after_hp,
    )
    if defeat_event is None:
        return (hit_event,)
    return (hit_event, defeat_event)


def _damage_hit_event(
    packet: DamagePacket,
    *,
    record_type: str,
    amount: float,
    before_hp: float,
    after_hp: float,
) -> GameEvent:
    source_frame = source_frame_for_packet(packet)
    return GameEvent(
        event_type="damage.hit",
        source_id=source_frame.owner_id,
        target_id=packet.target_id,
        window=str(packet.metadata.get("window") or "damage"),
        process_only=True,
        payload={
            "record_type": record_type,
            "attacker_id": packet.attacker_id,
            "actor_id": packet.attacker_id,
            "param_entity_id": packet.attacker_id,
            "damage_attacker_id": packet.attacker_id,
            "damage_source_owner_id": source_frame.owner_id,
            "damage_source_id": source_frame.source_id,
            "damage_source_kind": source_frame.source_kind,
            "damage_sequence_id": source_frame.sequence_id,
            "source_frame": source_frame.to_json(),
            "target_id": packet.target_id,
            "current_hit_target_id": packet.target_id,
            "primary_action_target_id": packet.metadata.get("primary_action_target_id"),
            "selected_target_ids": [packet.target_id],
            "target_ids": [packet.target_id],
            "hit_index": packet.metadata.get("hit_index"),
            "target_group": packet.metadata.get("target_group"),
            "damage_custom_name": packet.metadata.get("damage_custom_name"),
            "custom_name": packet.metadata.get("damage_custom_name"),
            "amount": amount,
            "target_before_hp": before_hp,
            "target_after_hp": after_hp,
            "attack_type": packet.attack_type,
            "SkillType": packet.metadata.get("SkillType"),
            "skill_type": packet.metadata.get("skill_type"),
            "damage_kind": packet.damage_kind,
            "damage_formula_family": packet.damage_formula_family,
            "element_type": packet.element_type,
            "damage_emission_id": packet.damage_emission_id,
            "break_damage_emission_id": packet.break_damage_emission_id,
            "super_break_emission_id": packet.super_break_emission_id,
            "status_damage_emission_id": packet.status_damage_emission_id,
            "status_callback_id": packet.status_callback_id,
            "source_task_id": packet.source_task_id,
            "hit_profile_id": packet.hit_profile_id,
            "source_trace": packet.source_trace,
            "is_current_skill_active": bool(packet.metadata.get("is_current_skill_active", False)),
            "is_insert_action": bool(packet.metadata.get("is_insert_action", False)),
            "per_hit_target_context_available": True,
            "per_hit_listener_admission_partial": True,
        },
    )


def _damage_defeat_event(
    packet: DamagePacket,
    *,
    hit_event: GameEvent,
    record_type: str,
    amount: float,
    before_hp: float,
    after_hp: float,
) -> GameEvent | None:
    if before_hp <= 0 or after_hp > 0:
        return None
    damage_event_id = str(hit_event.to_json().get("event_id") or "")
    source_frame = source_frame_for_packet(packet)
    return GameEvent(
        event_type="unit.defeated",
        source_id=source_frame.owner_id,
        target_id=packet.target_id,
        window="unit.defeated",
        process_only=True,
        payload={
            "record_type": record_type,
            "damage_event_id": damage_event_id,
            "lethal_damage_event_id": damage_event_id,
            "attacker_id": packet.attacker_id,
            "actor_id": source_frame.owner_id,
            "killer_id": source_frame.owner_id,
            "kill_credit_owner_id": source_frame.owner_id,
            "kill_credit_source_id": source_frame.source_id,
            "kill_credit_source_kind": source_frame.source_kind,
            "damage_sequence_id": source_frame.sequence_id,
            "source_frame": source_frame.to_json(),
            "target_id": packet.target_id,
            "defeated_unit_id": packet.target_id,
            "current_hit_target_id": packet.target_id,
            "primary_action_target_id": packet.metadata.get("primary_action_target_id"),
            "primary_target_id": packet.metadata.get("primary_action_target_id") or packet.target_id,
            "hit_index": packet.metadata.get("hit_index"),
            "target_group": packet.metadata.get("target_group"),
            "damage_custom_name": packet.metadata.get("damage_custom_name"),
            "custom_name": packet.metadata.get("damage_custom_name"),
            "amount": amount,
            "target_before_hp": before_hp,
            "target_after_hp": after_hp,
            "caused_by_damage": True,
            "defeated_by_damage": True,
            "kill_credit_rule": "hp_transition_positive_to_zero",
            "attack_type": packet.attack_type,
            "SkillType": packet.metadata.get("SkillType"),
            "skill_type": packet.metadata.get("skill_type"),
            "damage_kind": packet.damage_kind,
            "damage_formula_family": packet.damage_formula_family,
            "element_type": packet.element_type,
            "damage_emission_id": packet.damage_emission_id,
            "break_damage_emission_id": packet.break_damage_emission_id,
            "super_break_emission_id": packet.super_break_emission_id,
            "status_damage_emission_id": packet.status_damage_emission_id,
            "status_callback_id": packet.status_callback_id,
            "source_task_id": packet.source_task_id,
            "hit_profile_id": packet.hit_profile_id,
            "source_trace": packet.source_trace,
            "is_current_skill_active": bool(packet.metadata.get("is_current_skill_active", False)),
            "is_insert_action": bool(packet.metadata.get("is_insert_action", False)),
        },
    )


def _action_definition_summary(action_definition: ActionDefinitionIR | None) -> dict[str, JSONValue] | None:
    if action_definition is None:
        return None
    return {
        "definition_id": action_definition.definition_id,
        "action_id": action_definition.action_id,
        "level": action_definition.level,
        "damage_formula_family": action_definition.damage_formula_family,
    }
