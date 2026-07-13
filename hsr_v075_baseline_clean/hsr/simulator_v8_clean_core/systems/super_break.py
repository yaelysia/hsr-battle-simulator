from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import BattleState, JSONValue, Mutation
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.expression_ir import numeric_dynamic_hashes
from ..rules.ir import SuperBreakEmissionIR
from ..rules.rulebook import RuleBook
from .damage import DamagePacket, DamageSystem


@dataclass(frozen=True)
class SuperBreakPacket:
    attacker_id: str
    target_id: str
    super_break_emission_id: str
    total_stance_damage: float | None = None
    element_type: str | None = None
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "attacker_id": self.attacker_id,
            "target_id": self.target_id,
            "super_break_emission_id": self.super_break_emission_id,
            "total_stance_damage": self.total_stance_damage,
            "element_type": self.element_type,
            "source_trace": self.source_trace,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SuperBreakApplicationResult:
    ok: bool
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    errors: tuple[str, ...] = ()


class SuperBreakSystem:
    """Executes admitted super-break damage emissions.

    This system does not discover listener timing. It only applies a concrete
    emission already selected by higher-level runtime code from Canonical IR.
    """

    def __init__(
        self,
        rules: RuleBook,
        *,
        damage: DamageSystem | None = None,
        reducer: MutationReducer | None = None,
    ) -> None:
        self.rules = rules
        self.damage = damage or DamageSystem(rules)
        self.reducer = reducer or MutationReducer()

    def apply_packet(self, state: BattleState, packet: SuperBreakPacket) -> SuperBreakApplicationResult:
        emission = self.rules.super_break_emission(packet.super_break_emission_id)
        if emission is None:
            return _blocked(state, packet, "super_break_emission_missing")
        if emission.coverage_status != "executable":
            return _blocked(
                state,
                packet,
                emission.blocked_reason or f"super_break_emission_not_executable:{emission.coverage_status}",
                emission=emission,
            )
        target = state.units.get(packet.target_id)
        actor = state.units.get(packet.attacker_id)
        if target is None or actor is None:
            return _blocked(state, packet, "actor_or_target_missing", emission=emission)
        if not bool(target.flags.get("broken", False)):
            return _blocked(state, packet, "target_not_broken_for_super_break", emission=emission)
        evaluation = self._evaluate_amount(state, packet, emission)
        if not evaluation.ok or evaluation.value is None:
            return _blocked(
                state,
                packet,
                evaluation.blocked_reason or "super_break_numeric_evaluation_failed",
                emission=emission,
                evaluation=evaluation,
            )
        damage_result = self.damage.apply_packet(
            state,
            DamagePacket(
                attacker_id=packet.attacker_id,
                target_id=packet.target_id,
                attack_type=emission.attack_type,
                damage_formula_family="super_break",
                amount=float(evaluation.value),
                amount_stage="family_base",
                element_type=packet.element_type or emission.element_type,
                super_break_emission_id=emission.super_break_emission_id,
                break_template_id=emission.template_id,
                source_task_id=emission.source_task_id,
                source_trace={
                    "super_break_source": emission.source.to_json(),
                    "packet_source": packet.source_trace,
                },
                metadata={
                    **packet.metadata,
                    "damage_formula_family": "super_break",
                    "super_break_emission_id": emission.super_break_emission_id,
                    "break_template_id": emission.template_id,
                    "source_task_id": emission.source_task_id,
                    "numeric_evaluation": evaluation.to_json(),
                    "break_base_damage_source": _break_base_source_from_evaluation(evaluation),
                    "total_stance_damage": packet.total_stance_damage,
                    "super_break_ledger": _super_break_ledger(packet, evaluation),
                    "source_trace": {
                        "super_break_source": emission.source.to_json(),
                        "packet_source": packet.source_trace,
                    },
                },
            ),
        )
        after_state = self.reducer.apply_all(state, damage_result.mutations)
        return SuperBreakApplicationResult(
            ok=damage_result.ok,
            after_state=after_state,
            mutations=damage_result.mutations,
            records=damage_result.records,
            errors=damage_result.errors,
        )

    def _evaluate_amount(
        self,
        state: BattleState,
        packet: SuperBreakPacket,
        emission: SuperBreakEmissionIR,
    ) -> NumericEvaluationResult:
        actor = state.units.get(packet.attacker_id)
        if actor is None:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="super_break",
                bindings={},
                source_trace=emission.source.to_json(),
                blocked_reason="actor_missing",
            )
        if packet.total_stance_damage is None:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="super_break",
                bindings={},
                source_trace=emission.source.to_json(),
                blocked_reason="total_stance_damage_missing",
            )
        base = self.rules.break_base_damage(actor.level)
        if base is None or base.coverage_status != "executable":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="super_break",
                bindings={"actor_level": actor.level},
                source_trace=emission.source.to_json(),
                blocked_reason="break_base_damage_missing_or_not_executable",
            )
        return RuleEvaluator().evaluate_numeric(
            emission.scaling_expr,
            NumericEvaluationContext(
                binding_sources=(
                    _super_break_binding_source(packet, emission, base.to_json()),
                ),
                source_trace={
                    "super_break_source": emission.source.to_json(),
                    "break_base_damage_source": base.source.to_json(),
                    "packet_source": packet.source_trace,
                },
            ),
        )


def _super_break_binding_source(
    packet: SuperBreakPacket,
    emission: SuperBreakEmissionIR,
    break_base_damage: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    hashes = numeric_dynamic_hashes(emission.scaling_expr)
    entries: dict[str, JSONValue] = {}
    if len(hashes) >= 1:
        entries["break_base_damage"] = {
            "scope": "super_break_template",
            "owner_id": packet.attacker_id,
            "name": "CasterBreakBaseDamage",
            "hash": str(hashes[0]),
            "value": float(break_base_damage.get("break_base_damage") or 0.0),
            "source_trace": {
                "dynamic_key": "CasterBreakBaseDamage",
                "break_base_damage": break_base_damage,
                "super_break_source": emission.source.to_json(),
            },
        }
    if len(hashes) >= 2 and packet.total_stance_damage is not None:
        entries["total_stance_damage"] = {
            "scope": "super_break_template",
            "owner_id": packet.target_id,
            "name": "TotalStanceDamageOnTarget",
            "hash": str(hashes[1]),
            "value": float(packet.total_stance_damage),
            "source_trace": {
                "dynamic_key": "TotalStanceDamageOnTarget",
                "packet_source": packet.source_trace,
                "super_break_source": emission.source.to_json(),
            },
        }
    return {
        "source_type": "break_template_runtime_value",
        "entries": entries,
        "by_hash": {
            str(item["hash"]): [key]
            for key, item in entries.items()
            if isinstance(item, dict) and isinstance(item.get("hash"), str)
        },
        "by_name": {
            str(item["name"]): [key]
            for key, item in entries.items()
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        },
    }


def _break_base_source_from_evaluation(evaluation: NumericEvaluationResult) -> dict[str, JSONValue]:
    bindings = evaluation.bindings
    operands = bindings.get("dynamic_operands") if isinstance(bindings, dict) else None
    if not isinstance(operands, list):
        return {}
    for operand in operands:
        if not isinstance(operand, dict):
            continue
        binding = operand.get("bindings")
        if not isinstance(binding, dict):
            continue
        entry = binding.get("entry")
        if not isinstance(entry, dict) or entry.get("name") != "CasterBreakBaseDamage":
            continue
        source_trace = entry.get("source_trace")
        if isinstance(source_trace, dict):
            break_base = source_trace.get("break_base_damage")
            return break_base if isinstance(break_base, dict) else source_trace
    return {}


def _super_break_ledger(packet: SuperBreakPacket, evaluation: NumericEvaluationResult) -> dict[str, JSONValue]:
    return {
        "family": "super_break",
        "bypasses_direct_crit_ledger": True,
        "total_stance_damage": packet.total_stance_damage,
        "numeric_evaluation": evaluation.to_json(),
        "terms": [
            {
                "bucket": "super_break_formula",
                "source_type": "super_break_emission",
                "source_id": packet.super_break_emission_id,
                "applied_value": evaluation.value,
                "applied_reason": "admitted_super_break_postfix_formula",
            }
        ],
    }


def _blocked(
    state: BattleState,
    packet: SuperBreakPacket,
    reason: str,
    *,
    emission: SuperBreakEmissionIR | None = None,
    evaluation: NumericEvaluationResult | None = None,
) -> SuperBreakApplicationResult:
    return SuperBreakApplicationResult(
        ok=False,
        after_state=state,
        records=(
            SettlementRecord(
                record_type="super_break_blocked",
                source="super_break_system",
                process_only=True,
                payload={
                    **packet.to_json(),
                    "reason": reason,
                    "coverage_status": emission.coverage_status if emission else "",
                    "numeric_evaluation": evaluation.to_json() if evaluation else {},
                    "blocking_dependency": reason,
                },
                trace={
                    "super_break_source": emission.source.to_json() if emission else {},
                    "packet_source": packet.source_trace,
                },
            ).to_json(),
        ),
        errors=(reason,),
    )
