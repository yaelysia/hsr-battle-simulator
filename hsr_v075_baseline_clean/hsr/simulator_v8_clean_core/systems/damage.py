from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Literal

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, PendingDefeatPlan, RNGEvent
from ..core.settlement import SettlementRecord
from ..rules.engine_rule_registry import (
    ENGINE_RULE_REGISTRY_VERSION,
    KILL_ENERGY_RULE_APPLICABILITY,
    EngineRuleRegistry,
    build_engine_rule_registry,
    engine_rule_admission_reason,
    select_damage_route_rule,
)
from ..rules.ir import ActionDefinitionIR, DamageModifierIR, FormulaIR
from ..rules.rulebook import RuleBook
from .damage_formula import DamageFormulaInput, DirectDamageFormula, resolve_damage_crit
from .damage_pipeline import DamagePipelineResult, DamageStageBucket, DamageStagePipeline
from .mutation_events import events_for_mutation, mutation_backed_event_id
from .resource import ResourceSystem
from .unit_lifecycle import UnitLifecycleSystem
from .shield import HPDamageRoute, ShieldSystem
from .elation import ElationDamageContext
from .scaling_basis import resolve_scaling_basis


DamageFormulaFamily = Literal[
    "direct",
    "additional",
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
    "additional": DamageFamilyPolicy(
        family="additional",
        runtime_status="executable_with_admitted_status_damage_amount",
        record_type="additional_damage",
        uses_direct_multiplier_ledger=False,
        bypasses_normal_multipliers=False,
        source_requirement="executable StatusDamageEmissionIR with admitted additional-damage amount",
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
        runtime_status="executable_with_admitted_elation_inputs",
        record_type="damage",
        uses_direct_multiplier_ledger=False,
        bypasses_normal_multipliers=False,
        source_requirement="executable elation level/multiplier FormulaIR + emission ratio + typed per-hit ElationDamageContext",
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
        lifecycle = UnitLifecycleSystem().view(state, packet.target_id)
        if lifecycle.can_receive_damage:
            return True, "", False
        if lifecycle.is_removed:
            return False, "damage_source_target_removed", False
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
class DamageModifierContribution:
    modifier: DamageModifierIR
    term_index: int
    value: float

    def __post_init__(self) -> None:
        if (type(self.modifier) is not DamageModifierIR
                or self.modifier.coverage_status != "executable" or self.modifier.blocked_reason
                or type(self.term_index) is not int
                or not 0 <= self.term_index < len(self.modifier.modifier_terms)
                or type(self.value) not in (int, float) or not math.isfinite(self.value)):
            raise ValueError("damage modifier contribution is not source-closed and finite")

    def formula_term(self) -> dict[str, JSONValue]:
        return {
            **self.modifier.modifier_terms[self.term_index],
            "value": self.value,
            "source_type": "damage_modifier_ir",
            "source_id": self.modifier.damage_modifier_id,
            "source_task_id": self.modifier.source_task_id,
            "condition": f"{self.modifier.event}_condition_passed",
            "source_trace": self.modifier.source.to_json(),
        }


@dataclass(frozen=True)
class DamagePacket:
    attacker_id: str
    target_id: str
    attack_type: str
    damage_formula_family: DamageFormulaFamily
    amount: float | None = None
    amount_stage: str = "unspecified"
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
    hit_energy_gain: float | None = None
    base_includes_break_bonus: bool = False
    final_formula_type: str = ""
    is_indirect: bool = False
    modifier_contributions: tuple[DamageModifierContribution, ...] = ()
    extra_scaling_ratio: float | None = None
    elation_context: ElationDamageContext | None = None

    def __post_init__(self) -> None:
        if self.damage_formula_family == FOLLOW_UP_ATTACK_TYPE:
            raise ValueError("follow_up is an attack type, not a damage formula family")
        if not isinstance(self.final_formula_type, str):
            raise TypeError("damage packet final formula type must be a string")
        if type(self.is_indirect) is not bool:
            raise TypeError("damage packet indirect marker must be a bool")
        if self.amount is not None and self.amount < 0:
            raise ValueError("damage amount must be non-negative")
        if any(type(item) is not DamageModifierContribution for item in self.modifier_contributions):
            raise TypeError("damage packet modifier contributions must be typed")
        object.__setattr__(self, "modifier_contributions", tuple(self.modifier_contributions))
        if self.elation_context is not None and type(self.elation_context) is not ElationDamageContext:
            raise TypeError("damage packet elation context must be typed")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "attacker_id": self.attacker_id,
            "target_id": self.target_id,
            "amount": self.amount,
            "amount_stage": self.amount_stage,
            "base_includes_break_bonus": self.base_includes_break_bonus,
            "final_formula_type": self.final_formula_type,
            "is_indirect": self.is_indirect,
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
            "extra_scaling_ratio": self.extra_scaling_ratio,
            "scaling_basis": self.scaling_basis,
            "hit_source_trace": self.hit_source_trace,
            "source_trace": self.source_trace,
            "source_frame": source_frame_for_packet(self).to_json(),
            "metadata": self.metadata,
            "hit_energy_gain": self.hit_energy_gain,
            "elation_context": self.elation_context.to_json() if self.elation_context is not None else None,
            "direct_modifier_terms": [item.formula_term() for item in self.modifier_contributions],
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


_DAMAGE_BLOCK_EXCLUDING_DOT_FLAG = "BlockDamageExcludeDot"
def _additional_final_formula_admission(
    packet: DamagePacket,
    rules: RuleBook | None,
) -> str:
    """Bind an additional hit's final formula to its executable formal emission."""

    final = packet.final_formula_type
    if final not in {"", "ByPureDamage"}:
        return f"additional_final_formula_not_admitted:{final}"
    emission = (
        rules.status_damage_emission(packet.status_damage_emission_id)
        if rules is not None and packet.status_damage_emission_id
        else None
    )
    if emission is not None:
        if emission.coverage_status != "executable":
            return "additional_final_formula_emission_not_executable"
        expected_final = str(emission.scaling_expr.get("final_formula_type") or "")
        expected_indirect = emission.scaling_expr.get("is_indirect") is True
        if final != expected_final:
            return "additional_final_formula_emission_mismatch"
        if bool(packet.is_indirect) != expected_indirect:
            return "additional_indirect_emission_mismatch"
        return ""
    if final == "ByPureDamage":
        return "pure_damage_contract_requires_formal_emission"
    return ""


def _damage_request_admission_reason(
    state: BattleState,
    packet: DamagePacket,
    rules: RuleBook | None,
) -> str:
    """Return the structural admission failure of a damage request before side effects.

    Blocking a hit consumes a status and must not turn an invalid packet into a
    successful transaction.  Every supported family therefore performs the same
    definition/formula/context checks that its applier requires, before the block
    status is touched; the applier still repeats them as the final authority.
    """

    family = packet.damage_formula_family
    if packet.target_id not in state.units:
        return "damage_target_missing"
    if family == "direct":
        if packet.action_definition is None:
            return "direct damage requires action_definition"
        if packet.scaling_ratio is None:
            return "direct damage requires hit_profile scaling_ratio"
        if (type(packet.scaling_ratio) not in (int, float)
                or not math.isfinite(packet.scaling_ratio)
                or packet.scaling_ratio < 0):
            return "direct damage requires finite hit_profile scaling_ratio"
        if not isinstance(packet.scaling_basis, dict):
            return "direct damage requires hit_profile scaling_basis"
        basis_result = resolve_scaling_basis(
            state,
            attacker_id=packet.attacker_id,
            target_id=packet.target_id,
            basis=packet.scaling_basis,
            source_trace=packet.source_trace,
        )
        if not basis_result.ok or basis_result.value is None:
            return (
                basis_result.blocked_reason
                or "direct damage scaling_basis_not_admitted"
            )
        extra_basis = packet.scaling_basis.get("extra_scaling_basis")
        if extra_basis is not None or packet.extra_scaling_ratio is not None:
            if (
                type(packet.extra_scaling_ratio) not in (int, float)
                or not math.isfinite(packet.extra_scaling_ratio)
            ):
                return "extra_scaling_ratio_missing_or_invalid"
            extra_result = resolve_scaling_basis(
                state,
                attacker_id=packet.attacker_id,
                target_id=packet.target_id,
                basis=extra_basis,
                source_trace=packet.source_trace,
            )
            if not extra_result.ok or extra_result.value is None:
                return (
                    extra_result.blocked_reason
                    or "extra_scaling_basis_not_admitted"
                )
        return ""
    if family == "elation":
        reason, _ = _elation_admission(state, packet, rules)
        return reason
    if family == "break":
        if packet.amount is None:
            return "break damage requires admitted amount"
        if packet.amount_stage != "family_base":
            return "break damage requires family_base amount stage"
        if not packet.break_damage_emission_id and not packet.status_damage_emission_id:
            return "break damage requires break_damage_emission_id or status_damage_emission_id"
        if not packet.break_template_id:
            return "break damage requires break_template_id"
        if packet.status_damage_emission_id and rules is not None:
            emission = rules.status_damage_emission(
                packet.status_damage_emission_id
            )
            if (
                emission is None
                or emission.coverage_status != "executable"
                or emission.damage_formula_family != "break"
                or packet.base_includes_break_bonus
                is not emission.base_includes_break_bonus
                or (
                    packet.base_includes_break_bonus
                    and emission.break_amount_mode != "value"
                )
            ):
                return "included_break_bonus_emission_mismatch"
        elif packet.base_includes_break_bonus:
            return "included_break_bonus_emission_missing"
        return ""
    if family == "super_break":
        if packet.amount is None:
            return "super break damage requires admitted amount"
        if packet.amount_stage != "family_base":
            return "super break damage requires family_base amount stage"
        if not packet.super_break_emission_id:
            return "super break damage requires super_break_emission_id"
        return ""
    if family in {"dot", "additional"}:
        record_type = "dot_damage" if family == "dot" else "additional_damage"
        if packet.amount is None:
            return f"{record_type} requires admitted amount"
        if packet.amount_stage != "family_base":
            return f"{record_type} requires family_base amount stage"
        if not packet.status_damage_emission_id:
            return f"{record_type} requires status_damage_emission_id"
        if family == "additional":
            return _additional_final_formula_admission(packet, rules)
        return ""
    if family in {"true_damage", "hp_loss"}:
        if packet.amount is None:
            return f"{family} requires fixed amount"
        if packet.amount_stage != "fixed_final":
            return f"{family} requires fixed_final amount stage"
        return ""
    if _family_policy(family).runtime_status == "blocked":
        return ""
    return f"unsupported damage formula family {family!r}"

# Source modifier GlobalModifier_Common_Specific.BlockDamage_Count declares one
# count of "nullify all DMG received except DoT".  Break, additional and
# elation damage are damage received; DoT, true damage and HP-loss operations
# are separate families and bypass the block.
_DAMAGE_BLOCK_EXCLUDING_DOT_FAMILIES = frozenset(
    {"direct", "elation", "break", "super_break", "additional"}
)


def _elation_admission(state: BattleState, packet: DamagePacket, rules: RuleBook | None) -> tuple[str, dict[str, object]]:
    """Return the non-side-effect admission failure for an elation packet.

    Mirrors the real applier contract before any damage/block side effect: the
    context must be the one issued by the formal producer for this actor and
    state, its own blocked_reason must be clear, and the runtime override,
    basis, rules, formula and modifier-term dependencies must be admitted.
    """

    if (
        packet.amount is not None
        or packet.extra_scaling_ratio is not None
        or "elation_formula" in packet.metadata
    ):
        return "elation_base_runtime_override_not_admitted", {}
    if type(packet.elation_context) is not ElationDamageContext:
        return "elation_damage_context_missing", {}
    reason = packet.elation_context.blocked_reason(
        actor_id=packet.attacker_id,
        state=state,
        modifier_terms=tuple(
            item.formula_term() for item in packet.modifier_contributions
        ),
    )
    if reason:
        return reason, {}
    if (
        type(packet.scaling_ratio) not in (int, float)
        or not math.isfinite(packet.scaling_ratio)
        or packet.scaling_ratio < 0
        or packet.scaling_basis.get("kind") != "elation_level_base"
    ):
        return "elation_scaling_ratio_or_basis_not_admitted", {}
    if rules is None or packet.attacker_id not in state.units:
        return "elation_formal_rules_or_actor_missing", {}
    selected: dict[str, FormulaIR] = {}
    for kind in ("elation_level_base", "elation_multiplier_rule"):
        candidates = tuple(
            formula for formula in rules.ir.formulas if formula.kind == kind
        )
        if (
            len(candidates) != 1
            or candidates[0].coverage_status != "executable"
            or rules.formula_resolution(candidates[0].formula_id)[0] is None
        ):
            return f"{kind}_formula_not_admitted", {}
        selected[kind] = candidates[0]
    base_formula = selected["elation_level_base"]
    values = base_formula.expression.get("values")
    raw_base = (
        values.get(str(state.units[packet.attacker_id].level))
        if isinstance(values, dict)
        else None
    )
    try:
        base = float(raw_base) if type(raw_base) in (int, float, str) else math.nan
    except ValueError:
        base = math.nan
    if not math.isfinite(base) or base < 0:
        return "elation_level_base_missing_or_invalid", {}
    for contribution in packet.modifier_contributions:
        term = contribution.formula_term()
        bucket, key = term.get("bucket"), str(term.get("key") or "")
        admitted = (
            (bucket == "crit" and key in {"critical_chance", "critical_damage"})
            or (bucket == "defense" and key == "defender_defence_added_ratio")
            or (bucket == "resistance" and key in {"all_res_pen", *(f"{element}_res_pen" for element in (
                "Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"))})
            or (bucket == "damage_taken" and key == "damage_taken_ratio")
            or (bucket == "damage_reduction" and key == "damage_reduction")
            or (bucket == "base" and key == "attack_added_ratio")
            or (bucket == "damage_bonus" and key == "damage_added_ratio")
            or (bucket == "elation_bonus" and key == "elation_damage_added_ratio")
            or (bucket == "elation_context" and key in {"points", "point_multiplier_enabled"})
            or bucket == "weakness"
        )
        if not admitted:
            return f"elation_transient_modifier_not_admitted:{bucket}:{key}", {}
    base_amount = base * packet.scaling_ratio
    if not math.isfinite(base_amount):
        return "elation_base_amount_not_finite", {}
    return "", {
        "base": base,
        "base_amount": base_amount,
        "base_formula": base_formula,
        "multiplier_rule": selected["elation_multiplier_rule"],
    }

class DamageSystem:
    def __init__(
        self,
        rules: RuleBook | None = None,
        *,
        engine_rules: EngineRuleRegistry | None = None,
    ) -> None:
        self.rules = rules
        self.engine_rules = engine_rules or (
            rules.engine_rule_registry() if rules is not None else build_engine_rule_registry()
        )

    def apply_packet(
        self,
        state: BattleState,
        packet: DamagePacket,
        *,
        window_ledger: DamageWindowLedger | None = None,
    ) -> DamageApplicationResult:
        if "packet_fields" in packet.metadata:
            return _damage_error(packet, "reserved_packet_metadata_field:packet_fields")
        if packet.modifier_contributions and packet.damage_formula_family not in {"direct", "elation"}:
            return _damage_error(packet, "transient_damage_modifiers_require_direct_consumer")
        admission_reason = _damage_request_admission_reason(
            state, packet, self.rules
        )
        if admission_reason:
            return _damage_error(packet, admission_reason)
        dead_target_continuation = False
        if window_ledger is not None:
            admitted, reason, dead_target_continuation = window_ledger.admit_packet(state, packet)
            if not admitted:
                return _damage_source_skip(packet, reason, window_ledger)
        else:
            admitted, reason = _admit_packet_without_window(state, packet)
            if not admitted:
                return _damage_source_skip(packet, reason, None)
        damage_block = self._damage_block_excluding_dot(state, packet)
        if damage_block is not None:
            result = damage_block
        elif packet.damage_formula_family == "direct":
            result = self._apply_direct_damage(state, packet, dead_target_continuation=dead_target_continuation)
        elif packet.damage_formula_family == "elation":
            result = self._apply_elation_damage(state, packet, dead_target_continuation=dead_target_continuation)
        elif packet.damage_formula_family == "break":
            result = self._apply_break_damage(state, packet, dead_target_continuation=dead_target_continuation)
        elif packet.damage_formula_family == "super_break":
            result = self._apply_super_break_damage(state, packet, dead_target_continuation=dead_target_continuation)
        elif packet.damage_formula_family in {"additional", "dot"}:
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
        if result.ok and packet.hit_energy_gain is not None:
            result = self._with_hit_energy(state, packet, result)
        if result.ok:
            result = self._with_pending_defeat(state, packet, result)
        if result.ok:
            hp_events = tuple(
                event
                for mutation in result.mutations
                if mutation.path == ("units", packet.target_id, "hp")
                for event in events_for_mutation(
                    mutation, actor_id=packet.attacker_id, source_id=packet.attacker_id,
                    event_index=state.event_index,
                )
            )
            result = replace(result, events=(*hp_events, *result.events))
        if window_ledger is not None:
            for event in result.events:
                window_ledger.record_defeat_event(event)
        return result

    def _damage_block_excluding_dot(
        self, state: BattleState, packet: DamagePacket
    ) -> DamageApplicationResult | None:
        """Consume a source-declared damage block on an incoming non-DoT hit.

        Modifiers carrying the BlockDamageExcludeDot behavior flag nullify the
        damage of one hit and are consumed by it; DoT damage bypasses them.  The
        block is a native damage-pipeline rule keyed by the behavior flag, not a
        per-character decision.  Consumption goes through the formal status
        lifecycle so every mutation keeps its native settlement record and the
        OnDestroy/cleanup events of the status instance.
        """

        from .status import StatusSystem

        if packet.damage_formula_family not in _DAMAGE_BLOCK_EXCLUDING_DOT_FAMILIES:
            return None
        target = state.units.get(packet.target_id)
        if target is None or target.hp <= 0:
            return None
        details = target.flags.get("status_details")
        if not isinstance(details, (list, tuple)):
            return None
        detail = next(
            (
                item
                for item in details
                if isinstance(item, dict)
                and _DAMAGE_BLOCK_EXCLUDING_DOT_FLAG
                in (item.get("behavior_flags") or ())
                and str(item.get("lifecycle_state") or "active")
                in {"active", "active_partial"}
            ),
            None,
        )
        if detail is None:
            return None
        stacks = detail.get("stacks")
        remaining = (int(stacks) if isinstance(stacks, int) and not isinstance(stacks, bool) else 1) - 1
        status_trace = (
            dict(detail.get("source_trace"))
            if isinstance(detail.get("source_trace"), dict)
            else {}
        )
        block_request = {
            "damage_block_flag": _DAMAGE_BLOCK_EXCLUDING_DOT_FLAG,
            "status_instance_id": detail.get("instance_id"),
            "status_id": detail.get("status_id"),
            "modifier_name": detail.get("modifier_name"),
            "behavior_flags": list(detail.get("behavior_flags") or ()),
            "consumed_stack": bool(remaining <= 0),
            "remaining_stacks": max(0, remaining),
            "damage_request": packet.to_json(),
        }
        trace = {**status_trace, "damage_block": block_request}
        system = StatusSystem(self.rules)
        if remaining > 0:
            try:
                lifecycle = system.modify_modifier_value(
                    state,
                    packet.target_id,
                    str(detail.get("modifier_name") or ""),
                    "Layer",
                    "Add",
                    -1,
                    caster_id=str(detail.get("caster_id") or ""),
                    metadata=trace,
                    status_instance_id=str(detail.get("instance_id") or ""),
                )
            except (TypeError, ValueError):
                lifecycle = None
            if lifecycle is None or not lifecycle.ok:
                # A plain layer count without a stack policy still consumes one
                # instance layer through the same formal lifecycle.
                lifecycle = system.reduce_status_layer(
                    state,
                    target_id=packet.target_id,
                    detail=detail,
                    source="damage_system",
                    source_trace=trace,
                )
        else:
            lifecycle = system.remove_status_instance(
                state,
                target_id=packet.target_id,
                detail=detail,
                source="damage_system",
                source_trace=trace,
            )
        if not lifecycle.ok:
            # The status instance is not consumable through the formal lifecycle
            # (for example a synthetic detail without a stack admission).  Do not
            # invent unrecorded mutations: let the damage chain proceed normally.
            return None
        detail_mutation = next(
            (
                mutation
                for mutation in lifecycle.mutations
                if mutation.path == ("units", packet.target_id, "flags", "status_details")
            ),
            None,
        )
        hp = target.hp
        block_record = SettlementRecord(
            record_type="damage_blocked",
            source="damage_system",
            mutation_id=detail_mutation.stable_id() if detail_mutation is not None else "",
            process_only=False,
            payload={
                **block_request,
                "amount": 0.0,
                "target_before_hp": hp,
                "target_after_hp": hp,
                "status_lifecycle": lifecycle.to_json() if hasattr(lifecycle, "to_json") else {},
            },
            trace=packet.source_trace,
        ).to_json()
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=lifecycle.events,
            mutations=lifecycle.mutations,
            records=(block_record, *lifecycle.records),
        )

    def _with_pending_defeat(
        self, state: BattleState, packet: DamagePacket, result: DamageApplicationResult,
    ) -> DamageApplicationResult:
        terminal = next((event for event in result.events if event.event_type == "unit.defeated"), None)
        if terminal is None:
            return result
        hp = next((mutation for mutation in result.mutations
                   if mutation.path == ("units", packet.target_id, "hp")), None)
        frame = source_frame_for_packet(packet)
        try:
            plan = PendingDefeatPlan(packet.target_id, state.event_index, hp, frame.owner_id,
                                     frame.to_json(), packet.source_trace, terminal)
            lifecycle = UnitLifecycleSystem()
            mutations = lifecycle.begin_limbo_mutations(state, plan)
            root_event = lifecycle.limbo_events(plan)[0]
        except (TypeError, ValueError) as exc:
            return _damage_error(packet, str(exc))
        return replace(result, mutations=(*result.mutations, *mutations),
            events=tuple(root_event if event is terminal else event for event in result.events),
            records=(*result.records, *lifecycle_settlement_records(mutations)))

    def kill_energy_artifacts(
        self, state: BattleState, plan: PendingDefeatPlan, defeat: GameEvent,
    ) -> tuple[tuple[Mutation, ...], tuple[GameEvent, ...], tuple[dict[str, JSONValue], ...]]:
        """Credit only a finalized native lethal cause, after its rescue callbacks."""
        owner = state.units.get(plan.kill_credit_owner_id)
        if owner is None or owner.hp <= 0 or owner.lifecycle_status != "active" or owner.max_energy <= 0:
            return (), (), ()
        rules = tuple(rule for rule in self.engine_rules.resource_rules if rule.rule_kind == "kill_energy_gain")
        if len(rules) != 1:
            raise ValueError("resource_engine_rule_" + ("missing" if not rules else "ambiguous") + ":kill_energy_gain")
        rule = rules[0]
        reason = engine_rule_admission_reason(rule, expected_applicability=KILL_ENERGY_RULE_APPLICABILITY,
                                            numeric_value_required=True)
        if reason:
            raise ValueError(reason)
        mutation = ResourceSystem().gain_kill_energy(
            state, owner.unit_id, rule, defeated_event_payload=defeat.payload,
            source="damage_system.kill_energy", metadata={
                "source_frame": plan.source_frame, "source_trace": plan.source_trace,
                "target_id": owner.unit_id, "defeated_target_id": plan.unit_id,
                "hp_mutation_id": plan.hp_mutation.stable_id(),
                "lifecycle_mutation_id": defeat.payload.get("lifecycle_mutation_id"),
                "energy_capacity": owner.max_energy,
            },
        )
        if mutation.before == mutation.after:
            return (), (), ()
        record = SettlementRecord(
            record_type="kill_energy_gain", source="damage_system.kill_energy",
            mutation_id=mutation.stable_id(), process_only=False,
            payload={"owner_id": owner.unit_id, "defeated_target_id": plan.unit_id,
                     "before_energy": mutation.before, "after_energy": mutation.after,
                     "resource_rule_id": rule.resource_rule_id}, trace=mutation.metadata,
        ).to_json()
        return (mutation,), events_for_mutation(
            mutation, actor_id=owner.unit_id, source_id=owner.unit_id, event_index=state.event_index,
        ), (record,)

    def _with_hit_energy(
        self, state: BattleState, packet: DamagePacket, result: DamageApplicationResult,
    ) -> DamageApplicationResult:
        amount = packet.hit_energy_gain
        if (type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0
                or not packet.damage_emission_id or not packet.source_task_id):
            return _damage_error(packet, "hit_energy_contract_invalid")
        target = state.units[packet.target_id]
        try:
            mutation = ResourceSystem().change_unit_energy(
                state, packet.target_id, amount, "damage_system.hit_energy",
            )
        except ValueError as exc:
            return _damage_error(packet, str(exc))
        mutation = replace(mutation, mutation_id="", metadata={
            **mutation.metadata, "resource_operation": "hit_energy_gain",
            "damage_emission_id": packet.damage_emission_id,
            "source_task_id": packet.source_task_id, "hit_profile_id": packet.hit_profile_id,
            "source_trace": packet.source_trace, "target_id": packet.target_id,
            "source_frame": source_frame_for_packet(packet).to_json(),
            "energy_capacity": target.max_energy,
        })
        record = SettlementRecord(
            record_type="hit_energy_gain", source="damage_system.hit_energy",
            mutation_id=mutation.stable_id(), process_only=False,
            payload={"target_id": packet.target_id, "raw_energy_gain": amount,
                     "before_energy": mutation.before, "after_energy": mutation.after},
            trace=packet.source_trace,
        ).to_json()
        return replace(result, mutations=(*result.mutations, mutation),
                       events=(*result.events, *events_for_mutation(
                           mutation, actor_id=packet.attacker_id,
                           source_id=packet.source_task_id, event_index=state.event_index,
                       )), records=(*result.records, record))

    def _apply_elation_damage(
        self, state: BattleState, packet: DamagePacket, *, dead_target_continuation: bool = False,
    ) -> DamageApplicationResult:
        reason, admitted = _elation_admission(state, packet, self.rules)
        if reason:
            return _damage_error(packet, reason)
        base = float(admitted["base"])
        base_amount = float(admitted["base_amount"])
        base_formula = admitted["base_formula"]
        selected = {
            "elation_level_base": base_formula,
            "elation_multiplier_rule": admitted["multiplier_rule"],
        }
        prepared = replace(packet, amount=base_amount, amount_stage="family_base", metadata={
            **packet.metadata, "elation_formula": {
                "level_base": base, "scaling_ratio": packet.scaling_ratio, "ratio_delta": 0.0,
                "original_multiplier": 1.0, "context": packet.elation_context.to_json(),
                "level_formula_source": base_formula.source.to_json(),
                "multiplier_rule_source": selected["elation_multiplier_rule"].source.to_json(),
            },
        })
        return self._apply_dot_damage(state, prepared, dead_target_continuation=dead_target_continuation,
                                      elation_rule=selected["elation_multiplier_rule"])

    def _apply_dot_damage(
        self,
        state: BattleState,
        packet: DamagePacket,
        *,
        dead_target_continuation: bool = False,
        elation_rule: FormulaIR | None = None,
    ) -> DamageApplicationResult:
        is_dot = packet.damage_formula_family == "dot"
        is_elation = packet.damage_formula_family == "elation"
        record_type = "dot_damage" if is_dot else "damage" if is_elation else "additional_damage"
        if packet.amount is None:
            return _damage_error(packet, f"{record_type} requires admitted amount")
        if not packet.status_damage_emission_id and not (is_elation and packet.damage_emission_id):
            return _damage_error(packet, f"{record_type} requires status_damage_emission_id")
        pure_additional = (
            not is_dot
            and packet.damage_formula_family == "additional"
            and packet.final_formula_type == "ByPureDamage"
        )
        if (
            not is_dot
            and packet.damage_formula_family == "additional"
            and packet.final_formula_type
            and packet.final_formula_type != "ByPureDamage"
        ):
            return _damage_error(
                packet,
                f"additional_final_formula_not_admitted:{packet.final_formula_type}",
            )
        if pure_additional and not packet.is_indirect:
            return _damage_error(
                packet, "pure_damage_contract_requires_indirect_marker"
            )
        critical_bucket = None
        crit_resolution = None
        rng_events = ()
        if not is_dot and not pure_additional:
            try:
                crit_resolution, rng_event, bucket = resolve_damage_crit(
                    state, state.units[packet.attacker_id], packet.target_id,
                    identity={
                        "definition_id": packet.status_damage_emission_id or packet.damage_emission_id,
                        "task_id": packet.source_task_id,
                        "phase_id": (packet.status_callback_id or str(packet.metadata.get("phase_id") or "damage"))
                                    if is_elation else packet.status_callback_id,
                        "status_instance_id": packet.status_instance_id,
                        "derived_event_id": ((packet.metadata.get("derived_event_id") or packet.metadata.get("trigger_event_id")
                                              or packet.status_damage_emission_id or packet.damage_emission_id)
                                             if is_elation else packet.metadata.get("trigger_event_id") or packet.status_damage_emission_id),
                        **({"hit_index": packet.metadata.get("hit_index", 0)} if is_elation else {}),
                    },
                    source_trace=packet.source_trace,
                    crit_mode=_metadata_str(packet.metadata, "crit_mode"),
                    rng_choices=_metadata_dict(packet.metadata, "rng_choices"),
                    rng_mode=_metadata_str(packet.metadata, "rng_mode"),
                    crit_modifier_terms=tuple(item.formula_term() for item in packet.modifier_contributions
                        if item.formula_term().get("bucket") == "crit" and item.formula_term().get("key") == "critical_chance"),
                    crit_damage_modifier_terms=tuple(item.formula_term() for item in packet.modifier_contributions
                        if item.formula_term().get("bucket") == "crit" and item.formula_term().get("key") == "critical_damage"),
                )
            except ValueError as exc:
                return _damage_error(packet, str(exc))
            critical_bucket = DamageStageBucket(
                "critical", True, bucket.multiplier,
                tuple(term.to_json() for term in bucket.applied_terms),
                tuple(term.to_json() for term in bucket.skipped_terms), bucket.metadata,
            )
            rng_events = (rng_event,)
        pipeline = _non_direct_pipeline(
            state,
            packet,
            required_amount_stage="family_base",
            engine_rules=self.engine_rules,
            critical_bucket=critical_bucket,
            elation_rule=elation_rule,
            pure_damage=pure_additional,
        )
        if not pipeline.ok:
            return _damage_error(packet, pipeline.blocked_reason)
        target = state.units[packet.target_id]
        final_damage = pipeline.final_amount
        pipeline_json = pipeline.to_json()
        packet_json = packet.to_json()
        metadata = {
            **_packet_mutation_metadata(packet, packet_json),
            "final_damage": final_damage,
            "producer_base_amount": pipeline.producer_base_amount,
            "damage_pipeline": pipeline_json,
            "normal_multiplier_terms": list(pipeline.applied_terms),
            "uses_direct_multiplier_ledger": False,
            "bypasses_normal_multipliers": pure_additional,
            "final_formula_type": packet.final_formula_type,
            "is_indirect": packet.is_indirect,
            "pure_damage_contract": {
                "applied": pure_additional,
                "bypassed_stages": (
                    ["critical", "damage_bonus"] if pure_additional else []
                ),
                "source": "additional_attack_property.final_formula_type",
            },
            **({"crit_resolution": crit_resolution.to_json()} if crit_resolution is not None else {}),
            **({"elation_formula": packet.metadata["elation_formula"]} if is_elation else {}),
        }
        route = _shield_route(state, packet, final_damage, metadata, self.engine_rules)
        if not route.ok:
            return _damage_error(packet, route.blocked_reason)
        after = target.hp if dead_target_continuation else route.hp_after
        mutation = None if dead_target_continuation or after == target.hp else Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason=f"apply {record_type}",
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
            "bypasses_normal_multipliers": pure_additional,
            "uses_direct_multiplier_ledger": False,
            "final_formula_type": packet.final_formula_type,
            "is_indirect": packet.is_indirect,
            "pure_damage_contract": {
                "applied": pure_additional,
                "bypassed_stages": (
                    ["critical", "damage_bonus"] if pure_additional else []
                ),
                "source": "additional_attack_property.final_formula_type",
            },
            "normal_multiplier_terms": list(pipeline.applied_terms),
            "producer_base_amount": pipeline.producer_base_amount,
            "damage_pipeline": pipeline_json,
            "shared_multiplier_terms": list(pipeline.applied_terms),
            "skipped_multiplier_terms": list(pipeline.skipped_terms),
            "numeric_evaluation": packet.metadata.get("numeric_evaluation", {}),
            **({"damage_emission_id": packet.damage_emission_id,
                "elation_formula": packet.metadata["elation_formula"]} if is_elation else {}),
            "target_before_hp": target.hp,
            "target_after_hp": after,
            "hp_route": _hp_route_json(route),
            **({"crit_resolution": crit_resolution.to_json()} if crit_resolution is not None else {}),
        }
        if dead_target_continuation:
            record_payload["dead_target_continuation"] = True
            record_payload["continuation_reason"] = "same_damage_sequence_after_lethal"
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            rng_events=rng_events,
            events=route.events + _damage_events(
                packet,
                record_type=record_type,
                amount=final_damage,
                before_hp=target.hp,
                after_hp=after,
                is_critical=crit_resolution.is_crit if crit_resolution is not None else False,
            ),
            mutations=((route.shield_mutation,) if route.shield_mutation is not None else ())
            + ((mutation,) if mutation is not None else ()),
            records=(
                *route.records,
                SettlementRecord(
                    record_type=record_type,
                    source="damage_system",
                    mutation_id=(
                        mutation.stable_id()
                        if mutation is not None
                        else route.shield_mutation.stable_id()
                        if route.shield_mutation is not None
                        else None
                    ),
                    process_only=mutation is None and route.shield_mutation is None,
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
            formula_result = DirectDamageFormula(self.engine_rules).calculate(
                DamageFormulaInput(
                    state=state,
                    attacker_id=packet.attacker_id,
                    target_id=packet.target_id,
                    action_definition=packet.action_definition,
                    attack_type=packet.attack_type,
                    element_type=packet.element_type,
                    scaling_ratio=packet.scaling_ratio,
                    extra_scaling_ratio=packet.extra_scaling_ratio,
                    scaling_basis=packet.scaling_basis,
                    source_trace=packet.source_trace,
                    crit_mode=_metadata_str(packet.metadata, "crit_mode"),
                    rng_choices=_metadata_dict(packet.metadata, "rng_choices"),
                    rng_mode=_metadata_str(packet.metadata, "rng_mode"),
                    direct_modifier_terms=tuple(item.formula_term() for item in packet.modifier_contributions),
                    decision_identity={
                        "task_id": packet.source_task_id,
                        "phase_id": str(packet.metadata.get("phase_id") or "damage"),
                        "hit_index": int(packet.metadata.get("hit_index") or 0),
                        "derived_event_id": str(packet.metadata.get("derived_event_id") or packet.damage_emission_id),
                    },
                )
            )
        except ValueError as exc:
            return _damage_error(packet, str(exc))

        target = state.units[packet.target_id]
        final_damage = formula_result.final_damage
        formula_json = formula_result.to_json()
        pipeline_json = _direct_pipeline_json(formula_json, state.event_index)
        packet_json = packet.to_json()
        mutation_metadata = {
            **_packet_mutation_metadata(packet, packet_json),
            "formula_result": formula_json,
            "damage_pipeline": pipeline_json,
            "modifier_ledger": formula_json["modifier_ledger"],
            "crit_resolution": formula_json["crit_resolution"],
            "final_damage": final_damage,
        }
        route = _shield_route(state, packet, final_damage, mutation_metadata, self.engine_rules)
        if not route.ok:
            return _damage_error(packet, route.blocked_reason)
        after = route.hp_after
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
            "damage_pipeline": pipeline_json,
            "modifier_ledger": formula_json["modifier_ledger"],
            "crit_resolution": formula_json["crit_resolution"],
            "target_before_hp": target.hp,
            "target_after_hp": after,
            "hp_route": _hp_route_json(route),
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
                    is_critical=formula_result.crit_resolution.is_crit,
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
        mutation = None if after == target.hp else Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason="apply direct damage formula",
            source="damage_system",
            metadata=mutation_metadata,
        )
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=route.events + _damage_events(
                packet,
                record_type="damage",
                amount=final_damage,
                before_hp=target.hp,
                after_hp=after,
                is_critical=formula_result.crit_resolution.is_crit,
            ),
            mutations=((route.shield_mutation,) if route.shield_mutation is not None else ())
            + ((mutation,) if mutation is not None else ()),
            rng_events=formula_result.rng_events,
            records=(
                *route.records,
                SettlementRecord(
                    record_type="damage",
                    source="damage_system",
                    mutation_id=(
                        mutation.stable_id()
                        if mutation is not None
                        else route.shield_mutation.stable_id()
                        if route.shield_mutation is not None
                        else None
                    ),
                    process_only=mutation is None and route.shield_mutation is None,
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
        if packet.status_damage_emission_id and self.rules is not None:
            emission = self.rules.status_damage_emission(packet.status_damage_emission_id)
            if (emission is None or emission.coverage_status != "executable"
                or emission.damage_formula_family != "break"
                or packet.base_includes_break_bonus is not emission.base_includes_break_bonus
                or (packet.base_includes_break_bonus and emission.break_amount_mode != "value")):
                return _damage_error(packet, "included_break_bonus_emission_mismatch")
        elif packet.base_includes_break_bonus:
            return _damage_error(packet, "included_break_bonus_emission_missing")
        pipeline = _non_direct_pipeline(
            state,
            packet,
            required_amount_stage="family_base",
            engine_rules=self.engine_rules,
        )
        if not pipeline.ok:
            return _damage_error(packet, pipeline.blocked_reason)
        target = state.units[packet.target_id]
        final_damage = pipeline.final_amount
        pipeline_json = pipeline.to_json()
        packet_json = packet.to_json()
        metadata = {
            **_packet_mutation_metadata(packet, packet_json),
            "final_damage": final_damage,
            "producer_base_amount": pipeline.producer_base_amount,
            "damage_pipeline": pipeline_json,
            "normal_multiplier_terms": list(pipeline.applied_terms),
        }
        route = _shield_route(state, packet, final_damage, metadata, self.engine_rules)
        if not route.ok:
            return _damage_error(packet, route.blocked_reason)
        after = target.hp if dead_target_continuation else route.hp_after
        record_type = "break_dot_tick" if packet.status_damage_emission_id else "break_damage"
        reason = "apply break status DOT tick" if packet.status_damage_emission_id else "apply normal break damage"
        mutation = None if dead_target_continuation or after == target.hp else Mutation(
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
            "normal_multiplier_terms": list(pipeline.applied_terms),
            "producer_base_amount": pipeline.producer_base_amount,
            "damage_pipeline": pipeline_json,
            "shared_multiplier_terms": list(pipeline.applied_terms),
            "skipped_multiplier_terms": list(pipeline.skipped_terms),
            "numeric_evaluation": packet.metadata.get("numeric_evaluation", {}),
            "break_base_damage_source": packet.metadata.get("break_base_damage_source", {}),
            "target_before_hp": target.hp,
            "target_after_hp": after,
            "hp_route": _hp_route_json(route),
        }
        if dead_target_continuation:
            record_payload["dead_target_continuation"] = True
            record_payload["continuation_reason"] = "same_damage_sequence_after_lethal"
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=route.events + _damage_events(
                packet,
                record_type=record_type,
                amount=final_damage,
                before_hp=target.hp,
                after_hp=after,
            ),
            mutations=((route.shield_mutation,) if route.shield_mutation is not None else ())
            + ((mutation,) if mutation is not None else ()),
            records=(
                *route.records,
                SettlementRecord(
                    record_type=record_type,
                    source="damage_system",
                    mutation_id=(
                        mutation.stable_id()
                        if mutation is not None
                        else route.shield_mutation.stable_id()
                        if route.shield_mutation is not None
                        else None
                    ),
                    process_only=mutation is None and route.shield_mutation is None,
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
        pipeline = _non_direct_pipeline(
            state,
            packet,
            required_amount_stage="family_base",
            engine_rules=self.engine_rules,
        )
        if not pipeline.ok:
            return _damage_error(packet, pipeline.blocked_reason)
        target = state.units[packet.target_id]
        final_damage = pipeline.final_amount
        pipeline_json = pipeline.to_json()
        packet_json = packet.to_json()
        metadata = {
            **_packet_mutation_metadata(packet, packet_json),
            "final_damage": final_damage,
            "producer_base_amount": pipeline.producer_base_amount,
            "damage_pipeline": pipeline_json,
            "normal_multiplier_terms": list(pipeline.applied_terms),
            "super_break_ledger": packet.metadata.get("super_break_ledger", {}),
        }
        route = _shield_route(state, packet, final_damage, metadata, self.engine_rules)
        if not route.ok:
            return _damage_error(packet, route.blocked_reason)
        after = target.hp if dead_target_continuation else route.hp_after
        mutation = None if dead_target_continuation or after == target.hp else Mutation(
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
            "normal_multiplier_terms": list(pipeline.applied_terms),
            "producer_base_amount": pipeline.producer_base_amount,
            "damage_pipeline": pipeline_json,
            "shared_multiplier_terms": list(pipeline.applied_terms),
            "skipped_multiplier_terms": list(pipeline.skipped_terms),
            "super_break_ledger": packet.metadata.get("super_break_ledger", {}),
            "numeric_evaluation": packet.metadata.get("numeric_evaluation", {}),
            "break_base_damage_source": packet.metadata.get("break_base_damage_source", {}),
            "target_before_hp": target.hp,
            "target_after_hp": after,
            "hp_route": _hp_route_json(route),
        }
        if dead_target_continuation:
            record_payload["dead_target_continuation"] = True
            record_payload["continuation_reason"] = "same_damage_sequence_after_lethal"
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=route.events + _damage_events(
                packet,
                record_type="super_break_damage",
                amount=final_damage,
                before_hp=target.hp,
                after_hp=after,
            ),
            mutations=((route.shield_mutation,) if route.shield_mutation is not None else ())
            + ((mutation,) if mutation is not None else ()),
            records=(
                *route.records,
                SettlementRecord(
                    record_type="super_break_damage",
                    source="damage_system",
                    mutation_id=(
                        mutation.stable_id()
                        if mutation is not None
                        else route.shield_mutation.stable_id()
                        if route.shield_mutation is not None
                        else None
                    ),
                    process_only=mutation is None and route.shield_mutation is None,
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
        pipeline = _non_direct_pipeline(
            state,
            packet,
            required_amount_stage="fixed_final",
            engine_rules=self.engine_rules,
        )
        if not pipeline.ok:
            return _damage_error(packet, pipeline.blocked_reason)
        target = state.units[packet.target_id]
        packet_json = packet.to_json()
        pipeline_json = pipeline.to_json()
        metadata = {
            **_packet_mutation_metadata(packet, packet_json),
            "producer_base_amount": pipeline.producer_base_amount,
            "final_damage": pipeline.final_amount,
            "damage_pipeline": pipeline_json,
        }
        route = _shield_route(state, packet, pipeline.final_amount, metadata, self.engine_rules)
        if not route.ok:
            return _damage_error(packet, route.blocked_reason)
        after = target.hp if dead_target_continuation else route.hp_after
        mutation = None if dead_target_continuation or after == target.hp else Mutation(
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
            "amount": pipeline.final_amount,
            "producer_base_amount": pipeline.producer_base_amount,
            "damage_pipeline": pipeline_json,
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
            "hp_route": _hp_route_json(route),
        }
        if dead_target_continuation:
            record_payload["dead_target_continuation"] = True
            record_payload["continuation_reason"] = "same_damage_sequence_after_lethal"
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            events=route.events + _damage_events(
                packet,
                record_type=record_type,
                amount=pipeline.final_amount,
                before_hp=target.hp,
                after_hp=after,
            ),
            mutations=((route.shield_mutation,) if route.shield_mutation is not None else ())
            + ((mutation,) if mutation is not None else ()),
            records=(
                *route.records,
                SettlementRecord(
                    record_type=record_type,
                    source="damage_system",
                    mutation_id=(
                        mutation.stable_id()
                        if mutation is not None
                        else route.shield_mutation.stable_id()
                        if route.shield_mutation is not None
                        else None
                    ),
                    process_only=mutation is None and route.shield_mutation is None,
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


def _admit_packet_without_window(state: BattleState, packet: DamagePacket) -> tuple[bool, str]:
    if packet.target_id not in state.units:
        return False, "damage_target_missing"
    lifecycle = UnitLifecycleSystem().view(state, packet.target_id)
    if lifecycle.can_receive_damage:
        return True, ""
    if lifecycle.is_removed:
        return False, "damage_source_target_removed"
    return False, "damage_source_target_not_alive"


def _metadata_str(metadata: dict[str, JSONValue], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if isinstance(value, str) else None


def _metadata_dict(metadata: dict[str, JSONValue], key: str) -> dict[str, JSONValue]:
    value = metadata.get(key)
    return {str(item_key): item_value for item_key, item_value in value.items()} if isinstance(value, dict) else {}


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


def _non_direct_pipeline(
    state: BattleState,
    packet: DamagePacket,
    *,
    required_amount_stage: str,
    engine_rules: EngineRuleRegistry,
    critical_bucket: DamageStageBucket | None = None,
    elation_rule: FormulaIR | None = None,
    pure_damage: bool = False,
) -> DamagePipelineResult:
    if packet.amount is None:
        return DamagePipelineResult(
            False,
            packet.damage_formula_family,
            packet.attacker_id,
            packet.target_id,
            0.0,
            0.0,
            (),
            packet.source_trace,
            state.event_index,
            "damage_pipeline_amount_missing",
        )
    if packet.amount_stage != required_amount_stage:
        return DamagePipelineResult(
            False,
            packet.damage_formula_family,
            packet.attacker_id,
            packet.target_id,
            max(0.0, float(packet.amount)),
            0.0,
            (),
            packet.source_trace,
            state.event_index,
            f"damage_amount_stage_mismatch:{packet.amount_stage or 'missing'}:{required_amount_stage}",
        )
    try:
        return DamageStagePipeline(engine_rules).calculate(
            state,
            family=packet.damage_formula_family,
            attacker_id=packet.attacker_id,
            target_id=packet.target_id,
            producer_base_amount=float(packet.amount),
            base_includes_break_bonus=packet.base_includes_break_bonus,
            element_type=packet.element_type,
            attack_type=packet.attack_type,
            source_trace=packet.source_trace,
            critical_bucket=critical_bucket,
            elation_context=packet.elation_context,
            elation_rule=elation_rule,
            modifier_terms=tuple(item.formula_term() for item in packet.modifier_contributions),
            pure_damage=pure_damage,
        )
    except ValueError as exc:
        return DamagePipelineResult(
            False,
            packet.damage_formula_family,
            packet.attacker_id,
            packet.target_id,
            max(0.0, float(packet.amount)),
            0.0,
            (),
            packet.source_trace,
            state.event_index,
            str(exc),
        )


def _shield_route(
    state: BattleState,
    packet: DamagePacket,
    final_damage: float,
    mutation_metadata: dict[str, JSONValue],
    engine_rules: EngineRuleRegistry,
) -> HPDamageRoute:
    if "shield_route" in packet.metadata or "shield_route_source" in packet.metadata:
        return HPDamageRoute(
            False,
            packet.target_id,
            final_damage,
            blocked_reason="damage_route_runtime_override_not_admitted",
        )
    route_rule, route_reason = select_damage_route_rule(packet.damage_formula_family, engine_rules)
    if route_rule is None:
        return HPDamageRoute(False, packet.target_id, final_damage, blocked_reason=route_reason)
    frame = source_frame_for_packet(packet)
    return ShieldSystem(engine_rules).route_damage(
        state,
        target_id=packet.target_id,
        incoming_damage=final_damage,
        damage_family=packet.damage_formula_family,
        damage_route_rule_id=route_rule.damage_route_rule_id,
        damage_route_rule_version=ENGINE_RULE_REGISTRY_VERSION,
        actor_id=packet.attacker_id,
        source_id=frame.source_id,
        mutation_metadata=mutation_metadata,
    )


def _hp_route_json(route: HPDamageRoute) -> dict[str, JSONValue]:
    return {
        "route_policy": route.route_policy,
        "incoming_damage": route.incoming_damage,
        "absorbed_damage": route.absorbed_damage,
        "hp_damage": route.hp_damage,
        "hp_after": route.hp_after,
        "exhausted_instance_ids": list(route.exhausted_instance_ids),
        "evidence": route.evidence,
    }


def _direct_pipeline_json(formula: dict[str, JSONValue], event_index: int) -> dict[str, JSONValue]:
    scaling = formula.get("scaling") if isinstance(formula.get("scaling"), dict) else {}
    multipliers = formula.get("multipliers") if isinstance(formula.get("multipliers"), dict) else {}
    ledger = formula.get("modifier_ledger") if isinstance(formula.get("modifier_ledger"), dict) else {}
    amount = float(scaling.get("base_damage") or 0.0)
    stages: list[dict[str, JSONValue]] = []
    keys = (
        ("critical", "crit"),
        ("damage_bonus", "damage_bonus"),
        ("defense", "defense"),
        ("resistance", "resistance"),
        ("damage_taken", "damage_taken"),
        ("damage_reduction", "damage_reduction"),
        ("toughness_state", "toughness_state"),
    )
    buckets = ledger.get("buckets") if isinstance(ledger.get("buckets"), list) else []
    for stage, key in keys:
        raw_multiplier = multipliers.get(key)
        multiplier = (
            float(raw_multiplier)
            if isinstance(raw_multiplier, (int, float)) and not isinstance(raw_multiplier, bool)
            else 1.0
        )
        before = amount
        amount = max(0.0, amount * multiplier)
        bucket = next(
            (
                item
                for item in buckets
                if isinstance(item, dict) and str(item.get("bucket") or "") in {stage, key}
            ),
            {},
        )
        stages.append(
            {
                "stage": stage,
                "applicable": True,
                "input_amount": before,
                "multiplier": multiplier,
                "output_amount": amount,
                "bucket": bucket,
            }
        )
    return {
        "schema_version": "p7_s12_damage_stage_pipeline_v1",
        "ok": True,
        "family": "direct",
        "input_state_event_index": event_index,
        "producer_base_amount": float(scaling.get("base_damage") or 0.0),
        "stages": stages,
        "final_amount": float(formula.get("final_damage") or amount),
        "applied_terms": ledger.get("applied_terms", []),
        "skipped_terms": ledger.get("skipped_terms", []),
    }


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
    lifecycle_mutation_id: str = "",
    is_critical: bool = False,
) -> tuple[GameEvent, ...]:
    hit_event = _damage_hit_event(
        packet,
        record_type=record_type,
        amount=amount,
        before_hp=before_hp,
        after_hp=after_hp,
        is_critical=is_critical,
    )
    # Attacker and defender callbacks receive different ParamEntity values.
    # Produce both from the typed packet instead of changing listener payloads.
    hit_events = (hit_event,)
    if packet.action_definition is not None:
        hit_events += (replace(hit_event, event_type="damage.attacker_hit",
                              payload={**hit_event.payload, "param_entity_id": packet.target_id}),)
    defeat_event = _damage_defeat_event(
        packet,
        hit_event=hit_event,
        record_type=record_type,
        amount=amount,
        before_hp=before_hp,
        after_hp=after_hp,
        lifecycle_mutation_id=lifecycle_mutation_id,
        is_critical=is_critical,
    )
    if defeat_event is None:
        return hit_events
    return (*hit_events, defeat_event)


def _damage_hit_event(
    packet: DamagePacket,
    *,
    record_type: str,
    amount: float,
    before_hp: float,
    after_hp: float,
    is_critical: bool,
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
            "is_critical": is_critical,
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
    lifecycle_mutation_id: str = "",
    is_critical: bool = False,
) -> GameEvent | None:
    if before_hp <= 0 or after_hp > 0:
        return None
    damage_event_id = str(hit_event.to_json().get("event_id") or "")
    source_frame = source_frame_for_packet(packet)
    return GameEvent(
        event_type="unit.defeated",
        source_id=source_frame.owner_id,
        target_id=packet.target_id,
        event_id=mutation_backed_event_id(
            lifecycle_mutation_id,
            "unit.defeated",
        ),
        window="unit.defeated",
        process_only=True,
        payload={
            "record_type": record_type,
            "damage_event_id": damage_event_id,
            "lethal_damage_event_id": damage_event_id,
            "lifecycle_mutation_id": lifecycle_mutation_id,
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
            "is_critical": is_critical,
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


def _packet_mutation_metadata(packet: DamagePacket, packet_json: dict[str, JSONValue]) -> dict[str, JSONValue]:
    # Keep producer fields separate from custom metadata without nesting the entire packet.
    fields = {key: value for key, value in packet_json.items() if key != "metadata"}
    return {**fields, **packet.metadata, "packet_fields": fields}


def lifecycle_settlement_records(mutations: tuple[Mutation, ...]) -> tuple[dict[str, JSONValue], ...]:
    return tuple(SettlementRecord(
        record_type="unit_lifecycle", source=mutation.source, mutation_id=mutation.stable_id(),
        process_only=False, payload={
            "operation": mutation.metadata.get("lifecycle_operation"), "path": list(mutation.path),
            "before": mutation.before, "after": mutation.after, "reason": mutation.reason,
            "metadata": mutation.metadata,
        }, trace=mutation.metadata.get("source_trace", {}),
    ).to_json() for mutation in mutations)


def _action_definition_summary(action_definition: ActionDefinitionIR | None) -> dict[str, JSONValue] | None:
    if action_definition is None:
        return None
    return {
        "definition_id": action_definition.definition_id,
        "action_id": action_definition.action_id,
        "level": action_definition.level,
        "damage_formula_family": action_definition.damage_formula_family,
    }
