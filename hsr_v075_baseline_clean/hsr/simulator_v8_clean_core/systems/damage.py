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


EXECUTABLE_DAMAGE_FAMILIES: frozenset[str] = frozenset({"direct", "true_damage", "hp_loss"})
BLOCKED_DAMAGE_FAMILIES: frozenset[str] = frozenset({"dot", "break", "super_break", "elation"})
FOLLOW_UP_ATTACK_TYPE = "follow_up"


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
    source_task_id: str = ""
    hit_profile_id: str = ""
    scaling_ratio: float | None = None
    hit_source_trace: dict[str, JSONValue] = field(default_factory=dict)
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
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
            "source_task_id": self.source_task_id,
            "hit_profile_id": self.hit_profile_id,
            "scaling_ratio": self.scaling_ratio,
            "hit_source_trace": self.hit_source_trace,
            "source_trace": self.source_trace,
            "metadata": self.metadata,
            "bypasses_normal_multipliers": self.damage_formula_family in {"true_damage", "hp_loss"},
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
    def apply_packet(self, state: BattleState, packet: DamagePacket) -> DamageApplicationResult:
        if packet.damage_formula_family == "direct":
            return self._apply_direct_damage(state, packet)
        if packet.damage_formula_family in {"true_damage", "hp_loss"}:
            return self._apply_fixed_hp_delta(state, packet)
        if packet.damage_formula_family in BLOCKED_DAMAGE_FAMILIES:
            return self._blocked_family(packet)
        return DamageApplicationResult(
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

    def _apply_direct_damage(self, state: BattleState, packet: DamagePacket) -> DamageApplicationResult:
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
                    source_trace=packet.source_trace,
                    crit_mode=_metadata_str(packet.metadata, "crit_mode"),
                )
            )
        except ValueError as exc:
            return _damage_error(packet, str(exc))

        target = state.units[packet.target_id]
        final_damage = formula_result.final_damage
        after = max(0.0, target.hp - final_damage)
        formula_json = formula_result.to_json()
        mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason="apply direct damage formula",
            source="damage_system",
            metadata={
                **packet.to_json(),
                "formula_result": formula_json,
                "modifier_ledger": formula_json["modifier_ledger"],
                "crit_resolution": formula_json["crit_resolution"],
                "final_damage": final_damage,
            },
        )
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            mutations=(mutation,),
            rng_events=formula_result.rng_events,
            records=(
                SettlementRecord(
                    record_type="damage",
                    source="damage_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        "amount": final_damage,
                        "final_damage": final_damage,
                        "attack_type": packet.attack_type,
                        "damage_kind": packet.damage_kind,
                        "damage_formula_family": packet.damage_formula_family,
                        "element_type": packet.element_type,
                        "damage_emission_id": packet.damage_emission_id,
                        "source_task_id": packet.source_task_id,
                        "hit_profile_id": packet.hit_profile_id,
                        "scaling_ratio": packet.scaling_ratio,
                        "hit_source_trace": packet.hit_source_trace,
                        "packet_metadata": packet.metadata,
                        "bypasses_normal_multipliers": False,
                        "normal_multiplier_terms": formula_json["modifier_ledger"]["applied_terms"],
                        "formula_result": formula_json,
                        "modifier_ledger": formula_json["modifier_ledger"],
                        "crit_resolution": formula_json["crit_resolution"],
                        "target_before_hp": target.hp,
                        "target_after_hp": after,
                    },
                    trace=packet.source_trace,
                ).to_json(),
            ),
        )

    def _apply_fixed_hp_delta(self, state: BattleState, packet: DamagePacket) -> DamageApplicationResult:
        if packet.amount is None:
            return _damage_error(packet, f"{packet.damage_formula_family} requires fixed amount")
        target = state.units[packet.target_id]
        after = max(0.0, target.hp - packet.amount)
        mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason="apply damage packet",
            source="damage_system",
            metadata=packet.to_json(),
        )
        record_type = "hp_loss" if packet.damage_formula_family == "hp_loss" else "damage"
        bypasses_normal_multipliers = packet.damage_formula_family in {"true_damage", "hp_loss"}
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            mutations=(mutation,),
            records=(
                SettlementRecord(
                    record_type=record_type,
                    source="damage_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        "amount": packet.amount,
                        "attack_type": packet.attack_type,
                        "damage_kind": packet.damage_kind,
                        "damage_formula_family": packet.damage_formula_family,
                        "element_type": packet.element_type,
                        "damage_emission_id": packet.damage_emission_id,
                        "source_task_id": packet.source_task_id,
                        "bypasses_normal_multipliers": bypasses_normal_multipliers,
                        "normal_multiplier_terms": [],
                        "target_before_hp": target.hp,
                        "target_after_hp": after,
                    },
                    trace=packet.source_trace,
                ).to_json(),
            ),
        )

    def _blocked_family(self, packet: DamagePacket) -> DamageApplicationResult:
        reason = (
            "Elation damage is a mainline 4.0 damage formula family, "
            "but its complete formula is not executable in v0_209"
            if packet.damage_formula_family == "elation"
            else f"{packet.damage_formula_family} damage family is not executable in v0_209"
        )
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


def _metadata_str(metadata: dict[str, JSONValue], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if isinstance(value, str) else None


def _action_definition_summary(action_definition: ActionDefinitionIR | None) -> dict[str, JSONValue] | None:
    if action_definition is None:
        return None
    return {
        "definition_id": action_definition.definition_id,
        "action_id": action_definition.action_id,
        "level": action_definition.level,
        "damage_formula_family": action_definition.damage_formula_family,
    }
