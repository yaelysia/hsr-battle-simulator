from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from .dynamic_values import binding_source_from_store, status_binding_sources, store_from_state
from .mutation_events import enrich_event_with_mutation_payload


@dataclass(frozen=True)
class ToughnessPacket:
    attacker_id: str
    target_id: str
    toughness_emission_id: str
    source_task_id: str
    hit_profile_id: str
    element_type: str | None
    amount: float | None
    target_group: str
    coverage_status: str
    source_trace: dict[str, JSONValue]
    amount_expr: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "attacker_id": self.attacker_id,
            "target_id": self.target_id,
            "toughness_emission_id": self.toughness_emission_id,
            "source_task_id": self.source_task_id,
            "hit_profile_id": self.hit_profile_id,
            "element_type": self.element_type,
            "amount": self.amount,
            "amount_expr": self.amount_expr,
            "target_group": self.target_group,
            "coverage_status": self.coverage_status,
            "source_trace": self.source_trace,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ToughnessApplicationResult:
    packet: ToughnessPacket
    ok: bool
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    errors: tuple[str, ...] = ()


class ToughnessSystem:
    def apply_packet(self, state: BattleState, packet: ToughnessPacket) -> ToughnessApplicationResult:
        if packet.coverage_status != "executable":
            return _blocked(packet, f"toughness_emission_not_executable:{packet.coverage_status}")
        amount_result = _evaluate_amount(state, packet)
        if not amount_result.ok or amount_result.value is None:
            return _blocked(packet, amount_result.blocked_reason or "toughness_amount_not_executable", amount_result)
        amount = amount_result.value
        if amount <= 0:
            return _skipped(packet, "toughness_amount_not_positive", amount_result=amount_result)
        target = state.units.get(packet.target_id)
        if target is None:
            return _blocked(packet, "target_missing")
        if target.max_toughness <= 0:
            return _skipped(packet, "target_has_no_toughness", amount_result=amount_result)
        if target.toughness <= 0:
            return _skipped(packet, "target_toughness_already_depleted", amount_result=amount_result)
        if bool(target.flags.get("weakness_locked", False)):
            return _skipped(packet, "target_weakness_locked", amount_result=amount_result)
        if bool(target.flags.get("mute_break", False)):
            return _skipped(packet, "target_mute_break", amount_result=amount_result)
        weaknesses = tuple(str(item) for item in target.flags.get("weaknesses", ()) if isinstance(item, str))
        force_stance_damage = bool(target.flags.get("force_stance_damage", False))
        if packet.element_type and packet.element_type not in weaknesses and not force_stance_damage:
            return _skipped(
                packet,
                "element_not_in_target_weaknesses",
                extra={"weaknesses": list(weaknesses)},
                amount_result=amount_result,
            )
        before = target.toughness
        after = max(0.0, before - amount)
        if after == before:
            return _skipped(packet, "toughness_unchanged", amount_result=amount_result)
        metadata = {
            **packet.to_json(),
            **packet.metadata,
            "amount": amount,
            "numeric_evaluation": amount_result.to_json(),
            "weakness_check": {
                "element_type": packet.element_type,
                "weaknesses": list(weaknesses),
                "weakness_locked": bool(target.flags.get("weakness_locked", False)),
                "mute_break": bool(target.flags.get("mute_break", False)),
                "force_stance_damage": force_stance_damage,
                "passed": True,
            },
        }
        mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "toughness"),
            before=before,
            after=after,
            reason="apply toughness damage",
            source="toughness_system",
            metadata=metadata,
        )
        records = [
            SettlementRecord(
                record_type="toughness",
                source="toughness_system",
                mutation_id=mutation.stable_id(),
                process_only=False,
                payload={
                    "amount": amount,
                    "target_before_toughness": before,
                    "target_after_toughness": after,
                    "toughness_emission_id": packet.toughness_emission_id,
                    "source_task_id": packet.source_task_id,
                    "hit_profile_id": packet.hit_profile_id,
                    "element_type": packet.element_type,
                    "numeric_evaluation": amount_result.to_json(),
                    "weakness_check": metadata["weakness_check"],
                },
                trace=packet.source_trace,
            ).to_json()
        ]
        mutations: list[Mutation] = [mutation]
        if after <= 0 and not bool(target.flags.get("broken", False)):
            records.append(
                SettlementRecord(
                    record_type="toughness_depleted_pending_break",
                    source="toughness_system",
                    process_only=True,
                    payload={
                        "target_id": packet.target_id,
                        "toughness_emission_id": packet.toughness_emission_id,
                        "source_task_id": packet.source_task_id,
                        "hit_profile_id": packet.hit_profile_id,
                        "break_element": packet.element_type,
                        "next_system": "break_system",
                    },
                    trace=packet.source_trace,
                ).to_json()
            )
        elif after <= 0:
            records.append(
                SettlementRecord(
                    record_type="toughness_depleted_break_skipped",
                    source="toughness_system",
                    process_only=True,
                    payload={
                        "target_id": packet.target_id,
                        "reason": "target_already_broken",
                        "toughness_emission_id": packet.toughness_emission_id,
                    },
                    trace=packet.source_trace,
                ).to_json()
            )
        hit_event = GameEvent(
            event_type="toughness.hit",
            source_id=packet.attacker_id,
            target_id=packet.target_id,
            window="damage",
            process_only=True,
            payload={
                "callback_events": ["OnBeingStanceDamage"],
                "attacker_id": packet.attacker_id,
                "actor_id": packet.attacker_id,
                "target_id": packet.target_id,
                "current_hit_target_id": packet.target_id,
                "primary_action_target_id": packet.metadata.get("primary_action_target_id"),
                "hit_profile_id": packet.hit_profile_id,
                "toughness_emission_id": packet.toughness_emission_id,
                "source_task_id": packet.source_task_id,
                "target_group": packet.target_group,
                "element_type": packet.element_type,
                "amount": amount,
                "target_before_toughness": before,
                "target_after_toughness": after,
                "weakness_check": metadata["weakness_check"],
                "source_trace": packet.source_trace,
                "per_hit_target_context_available": True,
                "per_hit_listener_admission_partial": True,
            },
        )
        return ToughnessApplicationResult(
            packet=packet,
            ok=True,
            events=(enrich_event_with_mutation_payload(hit_event, mutation),),
            mutations=tuple(mutations),
            records=tuple(records),
        )


def _blocked(
    packet: ToughnessPacket,
    reason: str,
    amount_result: NumericEvaluationResult | None = None,
) -> ToughnessApplicationResult:
    return ToughnessApplicationResult(
        packet=packet,
        ok=False,
        records=(
            SettlementRecord(
                record_type="toughness_emission_blocked",
                source="toughness_system",
                process_only=True,
                payload={
                    **packet.to_json(),
                    "reason": reason,
                    "numeric_evaluation": amount_result.to_json() if amount_result else {},
                },
                trace=packet.source_trace,
            ).to_json(),
        ),
        errors=(reason,),
    )


def _skipped(
    packet: ToughnessPacket,
    reason: str,
    *,
    extra: dict[str, JSONValue] | None = None,
    amount_result: NumericEvaluationResult | None = None,
) -> ToughnessApplicationResult:
    return ToughnessApplicationResult(
        packet=packet,
        ok=True,
        records=(
            SettlementRecord(
                record_type="toughness_skipped",
                source="toughness_system",
                process_only=True,
                payload={
                    **packet.to_json(),
                    "reason": reason,
                    "numeric_evaluation": amount_result.to_json() if amount_result else {},
                    **(extra or {}),
                },
                trace=packet.source_trace,
            ).to_json(),
        ),
    )


def _evaluate_amount(state: BattleState, packet: ToughnessPacket) -> NumericEvaluationResult:
    if packet.amount is not None:
        return RuleEvaluator().evaluate_numeric(
            {"kind": "fixed", "value": packet.amount},
            NumericEvaluationContext(source_trace=packet.source_trace),
        )
    unit_ids = tuple(
        unit_id
        for unit_id in (packet.attacker_id, packet.target_id, str(packet.metadata.get("primary_action_target_id") or ""))
        if unit_id
    )
    return RuleEvaluator().evaluate_numeric(
        packet.amount_expr,
        NumericEvaluationContext(
            binding_sources=(
                *status_binding_sources(state, unit_ids),
                binding_source_from_store(store_from_state(state)),
            ),
            source_trace=packet.source_trace,
        ),
    )
