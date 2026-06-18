from __future__ import annotations

from dataclasses import dataclass

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.ir import BreakDamageEmissionIR, BreakStatusEmissionIR, BreakTemplateIR
from ..rules.rulebook import RuleBook
from .damage import DamagePacket, DamageSystem
from .effect import EffectExecutionContext, EffectRegistry
from .status_callbacks import StatusCallbackSystem
from .toughness import ToughnessPacket


@dataclass(frozen=True)
class BreakApplicationResult:
    ok: bool
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    events: tuple[GameEvent, ...] = ()
    errors: tuple[str, ...] = ()


class BreakSystem:
    """Normal weakness-break lifecycle boundary.

    The system only consumes Canonical IR admitted through RuleBook. It does
    not infer break behavior from raw task names or display-only fields.
    """

    def __init__(
        self,
        rules: RuleBook,
        effects: EffectRegistry,
        *,
        reducer: MutationReducer | None = None,
        damage: DamageSystem | None = None,
        status_callbacks: StatusCallbackSystem | None = None,
    ) -> None:
        self.rules = rules
        self.effects = effects
        self.reducer = reducer or MutationReducer()
        self.damage = damage or DamageSystem()
        self.status_callbacks = status_callbacks or StatusCallbackSystem(rules, damage=self.damage, reducer=self.reducer)

    def enter_break(self, state: BattleState, packet: ToughnessPacket) -> BreakApplicationResult:
        target = state.units.get(packet.target_id)
        if target is None:
            return _blocked(state, packet, "target_missing")
        if target.toughness > 0:
            return _blocked(state, packet, "target_toughness_not_depleted")
        if target.max_toughness <= 0:
            return _blocked(state, packet, "target_has_no_toughness")
        if bool(target.flags.get("broken", False)):
            return _skipped(state, packet, "target_already_broken")
        if bool(target.flags.get("weakness_locked", False)):
            return _skipped(state, packet, "target_weakness_locked")
        if bool(target.flags.get("mute_break", False)):
            return _skipped(state, packet, "target_mute_break")
        template = self.rules.break_template_for_element(packet.element_type)
        if template is None:
            return _blocked(state, packet, "break_template_missing")
        if template.coverage_status != "executable":
            return _blocked(
                state,
                packet,
                template.blocked_reason or f"break_template_not_executable:{template.coverage_status}",
                template=template,
            )

        metadata = _break_metadata(packet, template)
        broken_mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "flags", "broken"),
            before=bool(target.flags.get("broken", False)),
            after=True,
            reason="enter weakness break state",
            source="break_system",
            metadata=metadata,
        )
        element_mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "flags", "break_element"),
            before=target.flags.get("break_element"),
            after=packet.element_type,
            reason="record weakness break element",
            source="break_system",
            metadata=metadata,
        )
        source_mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "flags", "break_source"),
            before=target.flags.get("break_source"),
            after={
                "attacker_id": packet.attacker_id,
                "toughness_emission_id": packet.toughness_emission_id,
                "source_task_id": packet.source_task_id,
                "hit_profile_id": packet.hit_profile_id,
                "source_trace": packet.source_trace,
                "break_template_id": template.template_id,
                "break_template_source": template.source.to_json(),
            },
            reason="record weakness break source",
            source="break_system",
            metadata=metadata,
        )
        lifecycle_mutations = (broken_mutation, element_mutation, source_mutation)
        current_state = self.reducer.apply_all(state, lifecycle_mutations)
        records: list[dict[str, JSONValue]] = [
            *_lifecycle_records(packet, template, lifecycle_mutations),
            _break_event_record(packet, template),
        ]
        mutations: list[Mutation] = list(lifecycle_mutations)
        errors: list[str] = []

        for emission in self.rules.break_status_emissions_for_template(template.template_id):
            result = self._apply_status_emission(current_state, packet, template, emission)
            current_state = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            errors.extend(result.errors)

        for emission in self.rules.break_damage_emissions_for_template(template.template_id):
            result = self._apply_break_damage_emission(current_state, packet, template, emission)
            current_state = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            errors.extend(result.errors)

        return BreakApplicationResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=(
                GameEvent(
                    "break.triggered",
                    source_id=packet.attacker_id,
                    window="break",
                    process_only=True,
                    payload={
                        "target_id": packet.target_id,
                        "element_type": packet.element_type,
                        "break_template_id": template.template_id,
                    },
                ),
            ),
            errors=tuple(errors),
        )

    def _apply_break_damage_emission(
        self,
        state: BattleState,
        packet: ToughnessPacket,
        template: BreakTemplateIR,
        emission: BreakDamageEmissionIR,
    ) -> BreakApplicationResult:
        if emission.coverage_status != "executable":
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(
                    _break_damage_blocked_record(
                        packet,
                        template,
                        emission,
                        reason=emission.blocked_reason or f"break_damage_not_executable:{emission.coverage_status}",
                    ),
                ),
                errors=(emission.blocked_reason or f"break_damage_not_executable:{emission.coverage_status}",),
            )
        evaluation = self._evaluate_break_damage_amount(state, packet, template, emission)
        if not evaluation.ok or evaluation.value is None:
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(
                    _break_damage_blocked_record(
                        packet,
                        template,
                        emission,
                        reason=evaluation.blocked_reason or "break_damage_numeric_evaluation_failed",
                        evaluation=evaluation,
                    ),
                ),
                errors=(evaluation.blocked_reason or "break_damage_numeric_evaluation_failed",),
            )
        damage_result = self.damage.apply_packet(
            state,
            DamagePacket(
                attacker_id=packet.attacker_id,
                target_id=packet.target_id,
                attack_type="ElementDamage",
                damage_formula_family="break",
                amount=float(evaluation.value),
                element_type=emission.element_type or packet.element_type,
                break_damage_emission_id=emission.break_damage_emission_id,
                break_template_id=template.template_id,
                source_task_id=emission.source_task_id,
                hit_profile_id=packet.hit_profile_id,
                source_trace={
                    "break_damage_source": emission.source.to_json(),
                    "break_template_source": template.source.to_json(),
                    "toughness_source": packet.source_trace,
                },
                metadata={
                    **packet.metadata,
                    "damage_formula_family": "break",
                    "break_damage_emission_id": emission.break_damage_emission_id,
                    "break_template_id": template.template_id,
                    "source_task_id": emission.source_task_id,
                    "toughness_emission_id": packet.toughness_emission_id,
                    "numeric_evaluation": evaluation.to_json(),
                    "break_template_source": template.source.to_json(),
                    "break_damage_source": emission.source.to_json(),
                    "break_base_damage_source": _break_base_source_from_evaluation(evaluation),
                    "source_trace": {
                        "break_damage_source": emission.source.to_json(),
                        "break_template_source": template.source.to_json(),
                        "toughness_source": packet.source_trace,
                    },
                },
            ),
        )
        after_state = self.reducer.apply_all(state, damage_result.mutations)
        return BreakApplicationResult(
            ok=damage_result.ok,
            after_state=after_state,
            mutations=damage_result.mutations,
            records=damage_result.records,
            events=damage_result.events,
            errors=damage_result.errors,
        )

    def _evaluate_break_damage_amount(
        self,
        state: BattleState,
        packet: ToughnessPacket,
        template: BreakTemplateIR,
        emission: BreakDamageEmissionIR,
    ) -> NumericEvaluationResult:
        actor = state.units.get(packet.attacker_id)
        target = state.units.get(packet.target_id)
        if actor is None or target is None:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="break_damage",
                bindings={},
                source_trace=emission.source.to_json(),
                blocked_reason="actor_or_target_missing",
            )
        break_base = self.rules.break_base_damage(actor.level)
        if break_base is None or break_base.coverage_status != "executable":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="break_damage",
                bindings={"actor_level": actor.level},
                source_trace=emission.source.to_json(),
                blocked_reason="break_base_damage_missing_or_not_executable",
            )
        source = _break_damage_binding_source(packet, template, emission, break_base.to_json(), target.max_toughness)
        return RuleEvaluator().evaluate_numeric(
            emission.scaling_expr,
            NumericEvaluationContext(
                binding_sources=(source,),
                source_trace={
                    "break_damage_source": emission.source.to_json(),
                    "break_template_source": template.source.to_json(),
                    "break_base_damage_source": break_base.source.to_json(),
                },
            ),
        )

    def _apply_status_emission(
        self,
        state: BattleState,
        packet: ToughnessPacket,
        template: BreakTemplateIR,
        emission: BreakStatusEmissionIR,
    ) -> BreakApplicationResult:
        effect = self.rules.effect(emission.effect_id)
        if emission.coverage_status != "executable":
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(
                    _break_status_record(
                        packet,
                        template,
                        emission,
                        reason=emission.blocked_reason or f"break_status_not_executable:{emission.coverage_status}",
                    ),
                ),
                errors=(emission.blocked_reason or f"break_status_not_executable:{emission.coverage_status}",),
            )
        if effect is None:
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(_break_status_record(packet, template, emission, reason="effect_missing"),),
                errors=("effect_missing",),
            )
        result = self.effects.execute(
            effect,
            EffectExecutionContext(
                state=state,
                caster_id=packet.attacker_id,
                source_id=emission.break_status_emission_id,
                owner_id=packet.target_id,
                param_entity_id=packet.target_id,
                current_action_target_id=packet.target_id,
            ),
        )
        after_state = self.reducer.apply_all(state, result.mutations)
        reason = "executed"
        if result.unsupported and result.mutations:
            reason = "executed_partial"
        elif not result.mutations:
            reason = "effect_produced_no_mutation"
        records = [
            _break_status_record(
                packet,
                template,
                emission,
                reason=reason,
                mutation_ids=[mutation.stable_id() for mutation in result.mutations],
            ),
            *result.records,
        ]
        if emission.modifier_name:
            on_stack = self.status_callbacks.execute(
                after_state,
                unit_id=packet.target_id,
                modifier_name=emission.modifier_name,
                event="OnStack",
            )
            after_state = on_stack.after_state
            records.extend(on_stack.records)
            result_mutations = (*result.mutations, *on_stack.mutations)
        else:
            result_mutations = result.mutations
        return BreakApplicationResult(
            ok=bool(result.mutations) or not result.unsupported,
            after_state=after_state,
            mutations=result_mutations,
            records=tuple(records),
            events=result.events,
            errors=() if result.mutations else tuple(str(item) for item in result.unsupported),
        )


def _break_metadata(packet: ToughnessPacket, template: BreakTemplateIR) -> dict[str, JSONValue]:
    return {
        **packet.to_json(),
        **packet.metadata,
        "break_template_id": template.template_id,
        "break_template_source": template.source.to_json(),
        "source_trace": {
            "toughness_source": packet.source_trace,
            "break_template_source": template.source.to_json(),
        },
        "break_lifecycle": {
            "reason": "toughness_depleted",
            "event_types": ["OnTriggerBreak", "OnBeingBreak"],
            "break_template_id": template.template_id,
            "break_damage_status": "blocked_or_pending_admission",
            "break_status_status": "effect_registry_driven",
        },
    }


def _lifecycle_records(
    packet: ToughnessPacket,
    template: BreakTemplateIR,
    mutations: tuple[Mutation, ...],
) -> tuple[dict[str, JSONValue], ...]:
    records: list[dict[str, JSONValue]] = []
    for mutation in mutations:
        field = mutation.path[-1] if mutation.path else ""
        records.append(
            SettlementRecord(
                record_type="break_lifecycle",
                source="break_system",
                mutation_id=mutation.stable_id(),
                process_only=False,
                payload={
                    "target_id": packet.target_id,
                    "field": field,
                    "event_types": ["OnTriggerBreak", "OnBeingBreak"],
                    "toughness_emission_id": packet.toughness_emission_id,
                    "source_task_id": packet.source_task_id,
                    "hit_profile_id": packet.hit_profile_id,
                    "break_element": packet.element_type,
                    "break_template_id": template.template_id,
                    "break_template_source": template.source.to_json(),
                    "break_damage_status": "blocked_or_pending_admission",
                },
                trace={
                    "toughness_source": packet.source_trace,
                    "break_template_source": template.source.to_json(),
                },
            ).to_json()
        )
    return tuple(records)


def _break_event_record(packet: ToughnessPacket, template: BreakTemplateIR) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="break_event",
        source="break_system",
        process_only=True,
        payload={
            "actor_id": packet.attacker_id,
            "target_id": packet.target_id,
            "element_type": packet.element_type,
            "events": ["OnTriggerBreak", "OnBeingBreak"],
            "toughness_emission_id": packet.toughness_emission_id,
            "break_template_id": template.template_id,
            "global_listener_status": "blocked_not_admitted",
            "being_hit_listener_status": "blocked_not_admitted",
            "per_hit_trigger_status": "blocked_not_admitted",
        },
        trace={
            "toughness_source": packet.source_trace,
            "break_template_source": template.source.to_json(),
        },
    ).to_json()


def _break_status_record(
    packet: ToughnessPacket,
    template: BreakTemplateIR,
    emission: BreakStatusEmissionIR,
    *,
    reason: str,
    mutation_ids: list[str] | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="break_status",
        source="break_system",
        process_only=True,
        payload={
            "reason": reason,
            "target_id": packet.target_id,
            "break_template_id": template.template_id,
            "break_status_emission_id": emission.break_status_emission_id,
            "effect_id": emission.effect_id,
            "opcode": emission.opcode,
            "modifier_name": emission.modifier_name,
            "coverage_status": emission.coverage_status,
            "mutation_ids": mutation_ids or [],
        },
        trace={
            "break_status_source": emission.source.to_json(),
            "break_template_source": template.source.to_json(),
        },
    ).to_json()


def _break_damage_blocked_record(
    packet: ToughnessPacket,
    template: BreakTemplateIR,
    emission: BreakDamageEmissionIR,
    *,
    reason: str,
    evaluation: NumericEvaluationResult | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="break_damage_blocked",
        source="break_system",
        process_only=True,
        payload={
            "reason": reason,
            "target_id": packet.target_id,
            "break_template_id": template.template_id,
            "break_damage_emission_id": emission.break_damage_emission_id,
            "source_task_id": emission.source_task_id,
            "damage_formula_family": emission.damage_formula_family,
            "coverage_status": emission.coverage_status,
            "scaling_expr": emission.scaling_expr,
            "blocking_dependency": reason,
            "numeric_evaluation": evaluation.to_json() if evaluation else {},
        },
        trace={
            "break_damage_source": emission.source.to_json(),
            "break_template_source": template.source.to_json(),
        },
    ).to_json()


def _break_damage_binding_source(
    packet: ToughnessPacket,
    template: BreakTemplateIR,
    emission: BreakDamageEmissionIR,
    break_base_damage: dict[str, JSONValue],
    target_stance: float,
) -> dict[str, JSONValue]:
    hashes = _postfix_dynamic_hashes(emission.scaling_expr)
    entries: dict[str, JSONValue] = {}
    if len(hashes) >= 1:
        entries["break_base_damage"] = {
            "scope": "break_template",
            "owner_id": packet.attacker_id,
            "name": "CasterBreakBaseDamage",
            "hash": str(hashes[0]),
            "value": float(break_base_damage.get("break_base_damage") or 0.0),
            "source_trace": {
                "dynamic_key": "CasterBreakBaseDamage",
                "break_base_damage": break_base_damage,
                "break_template_source": template.source.to_json(),
            },
        }
    if len(hashes) >= 2:
        entries["target_stance"] = {
            "scope": "break_template",
            "owner_id": packet.target_id,
            "name": "TargetStance",
            "hash": str(hashes[1]),
            "value": float(target_stance),
            "source_trace": {
                "dynamic_key": "TargetStance",
                "target_field": "max_toughness",
                "toughness_source": packet.source_trace,
                "break_template_source": template.source.to_json(),
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


def _postfix_dynamic_hashes(expression: dict[str, JSONValue]) -> list[JSONValue]:
    raw = expression.get("raw")
    if not isinstance(raw, dict):
        return []
    postfix = raw.get("PostfixExpr")
    if not isinstance(postfix, dict):
        return []
    hashes = postfix.get("DynamicHashes")
    return list(hashes) if isinstance(hashes, list) else []


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


def _blocked(
    state: BattleState,
    packet: ToughnessPacket,
    reason: str,
    *,
    template: BreakTemplateIR | None = None,
) -> BreakApplicationResult:
    return BreakApplicationResult(
        ok=False,
        after_state=state,
        records=(
            SettlementRecord(
                record_type="break_lifecycle_blocked",
                source="break_system",
                process_only=True,
                payload={
                    "reason": reason,
                    "target_id": packet.target_id,
                    "element_type": packet.element_type,
                    "toughness_emission_id": packet.toughness_emission_id,
                    "break_template_id": template.template_id if template else "",
                },
                trace={
                    "toughness_source": packet.source_trace,
                    "break_template_source": template.source.to_json() if template else {},
                },
            ).to_json(),
        ),
        errors=(reason,),
    )


def _skipped(state: BattleState, packet: ToughnessPacket, reason: str) -> BreakApplicationResult:
    return BreakApplicationResult(
        ok=True,
        after_state=state,
        records=(
            SettlementRecord(
                record_type="break_lifecycle_skipped",
                source="break_system",
                process_only=True,
                payload={
                    "reason": reason,
                    "target_id": packet.target_id,
                    "element_type": packet.element_type,
                    "toughness_emission_id": packet.toughness_emission_id,
                },
                trace=packet.source_trace,
            ).to_json(),
        ),
    )
