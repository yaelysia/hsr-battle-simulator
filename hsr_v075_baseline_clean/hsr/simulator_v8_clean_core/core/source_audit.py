from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from typing import Any

from .model import BattleTransition, JSONValue, Mutation, PendingDefeatPlan, freeze_json
from ..rules.ir import IRSource
from ..rules.rulebook import RuleBook


NON_MUTATING_STATUSES = {
    "audit_only",
    "blocked",
    "discovered_only",
    "skipped_with_reason",
    "unsupported",
}

MUTATION_SOURCE_POLICIES: dict[str, dict[str, JSONValue]] = {
    "scenario_setup": {
        "required_ir": ["ScenarioSpec typed initial condition"],
        "required_metadata": ["setup_operation", "source_kind", "scenario_id"],
        "coverage_required": "typed scenario initial condition; never TBGD or engine-rule evidence",
    },
    "combat_executor.timeline": {
        "required_ir": ["ActionDefinitionIR", "ActionEventIR"],
        "required_metadata": ["action_id", "action_level", "definition_id", "action_event_id", "source_trace"],
        "coverage_required": "ActionDefinitionIR executable; ActionEventIR traceable",
    },
    "timeline_system": {
        "required_ir": ["TimelineRuleIR + TurnAdvancePlan"],
        "required_metadata": ["timeline_rule_id", "turn_advance_plan_id", "source_trace"],
        "coverage_required": "TimelineRuleIR executable or explicit engine_convention",
    },
    "battle_state_transition_system": {
        "required_ir": ["BattleStateTransitionIR"],
        "required_metadata": [
            "battle_state_transition_rule_id",
            "trigger_kind",
            "trigger_identity",
            "runtime_event_type",
            "callback_event",
            "source_trace",
        ],
        "coverage_required": "source-backed shared battle-state transition executable",
    },
    "combat_executor.resources": {
        "required_ir": ["ActionDefinitionIR", "ActionEventIR", "ResourceRuleIR for admitted resource operation"],
        "required_metadata": ["action_id", "action_level", "definition_id", "action_event_id", "source_trace"],
        "coverage_required": "ActionDefinitionIR executable; ActionEventIR traceable",
    },
    "damage_system": {
        "required_ir": ["DamageEmissionIR + AbilityTaskIR + HitProfileIR", "BreakDamageEmissionIR + BreakBaseDamageIR for break", "StatusDamageEmissionIR + StatusCallbackIR for DOT/break DOT tick", "SuperBreakEmissionIR + BreakBaseDamageIR for super-break", "or EffectIR for hp_loss/true_damage"],
        "required_metadata": ["damage_emission_id/source_task_id/hit_profile_id or break_damage_emission_id or status_damage_emission_id or super_break_emission_id or effect_id", "source_trace", "source_frame"],
        "coverage_required": "executable",
    },
    "damage_system.hit_energy": {
        "required_ir": ["DamageEmissionIR.hit_energy_gain + AbilityTaskIR + HitProfileIR"],
        "required_metadata": ["damage_emission_id", "source_task_id", "hit_profile_id", "target_id",
                              "raw_delta", "delta", "energy_regeneration_rate", "source_trace"],
        "coverage_required": "executable single-request hit energy",
    },
    "damage_system.kill_energy": {
        "required_ir": ["Executable lethal damage source + ResourceRuleIR"],
        "required_metadata": ["source_frame", "resource_rule_id", "hp_mutation_id",
                              "lifecycle_mutation_id", "energy_regeneration_rate"],
        "coverage_required": "executable caused-kill energy",
    },
    "toughness_system": {
        "required_ir": ["ToughnessEmissionIR + AbilityTaskIR + HitProfileIR"],
        "required_metadata": ["toughness_emission_id", "source_task_id", "hit_profile_id", "source_trace"],
        "coverage_required": "executable",
    },
    "break_system": {
        "required_ir": ["BreakTemplateIR + ToughnessEmissionIR + AbilityTaskIR + HitProfileIR"],
        "required_metadata": ["break_template_id", "toughness_emission_id", "source_task_id", "hit_profile_id", "source_trace", "break_lifecycle"],
        "coverage_required": "executable break template and executable toughness emission",
    },
    "status_system": {
        "required_ir": ["EffectIR", "ModifierDefinition"],
        "required_metadata": ["lifecycle_plan"],
        "coverage_required": "executable; duration tick/expire also require executable duration admission",
    },
    "effect_system": {
        "required_ir": ["EffectIR"],
        "required_metadata": ["effect_id", "effect_source"],
        "coverage_required": "executable",
    },
    "status_callback_system": {
        "required_ir": ["StatusCallbackIR + StatusCallbackTaskIR + StatusDamageEmissionIR or ActionDelayEmissionIR"],
        "required_metadata": ["callback_id", "task_id", "source_trace"],
        "coverage_required": "executable for mutating paths; blocked paths process-only",
    },
    "ability_property_watcher_system": {
        "required_ir": ["AbilityPropertyWatcherIR + AbilityPropertyRangeIR"],
        "required_metadata": [
            "unit_id",
            "status_instance_id",
            "trigger_event_id",
            "watcher_ids",
            "watcher_state",
            "source_trace",
        ],
        "coverage_required": "source-backed executable watcher and canonical range state",
    },
    "event_dispatch_system": {
        "required_ir": ["TriggerIR or StatusCallbackIR"],
        "required_metadata": ["event", "listener_kind", "scope"],
        "coverage_required": "process-only dispatch records; mutating listener effects keep their underlying source",
    },
    "ability_provider_registry": {
        "required_ir": ["LightConeDefinitionIR + EquipmentMechanismRefIR + StandaloneAbilityGraphIR"],
        "required_metadata": ["owner_unit_id", "provider_ids", "providers", "source_trace"],
        "coverage_required": "resolved equipment mechanism and executable canonical ability graph",
    },
    "queue_system": {
        "required_ir": ["QueueIntentIR + QueuePriorityIR + QueueWindowIR for enqueue; QueueIntentIR + QueueResolutionIR + QueuePriorityIR + QueueWindowIR + QueueWindowPlan for dequeue; extra_turn additionally requires QueueLifecyclePolicyIR + ExtraActionPolicyIR"],
        "required_metadata": ["queue_name", "queue_operation", "queue_intent_id", "queue_window_id", "target_resolution", "source_trace"],
        "coverage_required": "executable",
    },
    "enemy_action_system": {
        "required_ir": ["MonsterDataCardIR.action_sequence + ActionDefinitionIR"],
        "required_metadata": ["monster_data_card_id", "sequence_index", "action_id", "action_level", "source_trace"],
        "coverage_required": "fixed sequence candidate available and action executed successfully",
    },
    "wave_system": {
        "required_ir": ["WaveDefinitionIR / WaveMonsterEntryIR"],
        "required_metadata": ["source_trace", "wave_transition_plan or wave_definition_id"],
        "coverage_required": "executable wave definition or traceable battle outcome",
    },
    "monster_startup": {
        "required_ir": ["MonsterDataCardIR + PassiveMechanismSlotIR"],
        "required_metadata": ["monster_data_card_id", "source_trace"],
        "coverage_required": "source-bound passive startup admission",
    },
    "summon_system": {
        "required_ir": ["SummonMonsterIntentIR or ServantDefinitionIR"],
        "required_metadata": ["summon_operation", "summon_plan or intent_id", "source_trace"],
        "coverage_required": "executable for mutating spawn/remove/cleanup paths",
    },
    "combat_executor.queue": {
        "required_ir": ["QueueIntentIR + QueuePriorityIR + QueueWindowIR for enqueue; QueueIntentIR + QueueResolutionIR + QueuePriorityIR + QueueWindowIR + QueueWindowPlan for dequeue; extra_turn additionally requires QueueLifecyclePolicyIR + ExtraActionPolicyIR"],
        "required_metadata": ["queue_name", "queue_operation", "queue_intent_id", "queue_window_id", "target_resolution", "source_trace"],
        "coverage_required": "executable",
    },
}


@dataclass(frozen=True)
class SourceAuditViolation:
    mutation_id: str
    source: str
    path: tuple[str, ...]
    reason: str
    missing_field: str = ""
    details: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "mutation_id": self.mutation_id,
            "source": self.source,
            "path": list(self.path),
            "reason": self.reason,
            "missing_field": self.missing_field,
            "details": self.details,
        }


@dataclass(frozen=True)
class SourceAuditResult:
    ok: bool
    checked_mutations: int
    checked_records: int
    violations: tuple[SourceAuditViolation, ...] = ()
    traces: tuple[dict[str, JSONValue], ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "checked_mutations": self.checked_mutations,
            "checked_records": self.checked_records,
            "violations": [violation.to_json() for violation in self.violations],
            "traces": list(self.traces),
        }


class RuntimeSourceAuditor:
    """Audit runtime mutations back to executable Canonical IR nodes."""

    def __init__(self, rules: RuleBook):
        self.rules = rules

    def validate_transition(self, transition: BattleTransition) -> SourceAuditResult:
        records = (
            transition.transaction.settlement.records
            if transition.transaction.settlement
            else ()
        )
        return self.validate_execution(transition.transaction.mutations, records)

    def validate_execution(
        self,
        mutations: tuple[Mutation, ...],
        records: tuple[dict[str, JSONValue], ...],
    ) -> SourceAuditResult:
        """Audit a committed production result before it is wrapped as a transition."""

        records_by_mutation = _records_by_mutation_id(records)
        violations: list[SourceAuditViolation] = []
        traces: list[dict[str, JSONValue]] = []
        mutations_by_id = {mutation.stable_id(): mutation for mutation in mutations}
        for mutation in mutations:
            mutation_records = records_by_mutation.get(mutation.stable_id(), ())
            if not mutation_records:
                violations.append(_violation(mutation, "mutation_has_no_settlement_record"))
                continue
            if (mutation.source == "damage_system"
                    and mutation.metadata.get("lifecycle_operation") in {
                        "unit_enter_limbo", "unit_defeat", "unit_defeat_record", "unit_pending_defeat_closed"}):
                trace = self._audit_damage_lifecycle_mutation(
                    mutation, mutation_records, mutations_by_id, violations,
                )
            else:
                trace = self._audit_mutation(mutation, mutation_records, violations)
            if mutation.source == "damage_system.kill_energy":
                metadata = mutation.metadata
                target = metadata.get("defeated_target_id")
                hp = mutations_by_id.get(str(metadata.get("hp_mutation_id")))
                lifecycle = mutations_by_id.get(str(metadata.get("lifecycle_mutation_id")))
                if (hp is None or hp.source != "damage_system" or hp.path != ("units", target, "hp")
                        or type(hp.before) not in (int, float) or hp.before <= 0
                        or type(hp.after) not in (int, float) or hp.after != 0
                        or hp.metadata.get("source_frame") != metadata.get("source_frame")
                        or lifecycle is None or lifecycle.path != ("units", target, "lifecycle_status")
                        or lifecycle.after != "defeated"):
                    violations.append(_violation(mutation, "kill_energy_lethal_mutation_lineage_invalid"))
            if trace:
                traces.append(trace)
        return SourceAuditResult(
            ok=not violations,
            checked_mutations=len(mutations),
            checked_records=sum(len(value) for value in records_by_mutation.values()),
            violations=tuple(violations),
            traces=tuple(traces),
        )

    def policy_matrix(self) -> dict[str, JSONValue]:
        return {source: dict(policy) for source, policy in sorted(MUTATION_SOURCE_POLICIES.items())}

    def _audit_damage_lifecycle_mutation(
        self, mutation: Mutation, records: tuple[dict[str, JSONValue], ...],
        mutations_by_id: dict[str, Mutation], violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        hp = mutations_by_id.get(str(metadata.get("hp_mutation_id")))
        defeat = metadata.get("defeat_record")
        defeat = defeat if isinstance(defeat, dict) else {}
        target = defeat.get("target_id")
        operation = metadata.get("lifecycle_operation")
        pending_id = metadata.get("pending_defeat_id")
        # ponytail: linear scan per lifecycle mutation; index by pending_id if
        # large batches of simultaneous deaths make transaction auditing costly.
        pending_changes = tuple(item for item in mutations_by_id.values()
            if item.path == ("units", mutation.path[1], "flags", "pending_defeat")
            and item.metadata.get("pending_defeat_id") == pending_id) if len(mutation.path) > 1 else ()
        try:
            pending = next((item.after if item.after_exists else item.before for item in pending_changes), None)
            plan = PendingDefeatPlan.from_json(pending)
            pending_valid = (pending_id == plan.pending_id and hp == plan.hp_mutation
                and metadata.get("source_frame") == plan.source_frame
                and metadata.get("source_trace") == plan.source_trace)
        except ValueError:
            pending_valid = False
        if operation in {"unit_enter_limbo", "unit_pending_defeat_closed"}:
            target = mutation.path[1] if len(mutation.path) > 1 else None
            valid_path = (
                (mutation.path == ("units", target, "lifecycle_status")
                 and mutation.op == "set" and mutation.before == "active" and mutation.after == "limbo")
                or (mutation.path == ("units", target, "flags", "pending_defeat")
                    and mutation.op == "set" and not mutation.before_exists and mutation.after_exists)
                if operation == "unit_enter_limbo" else
                mutation.path == ("units", target, "flags", "pending_defeat")
                and mutation.op == "delete" and mutation.before_exists and not mutation.after_exists)
            if not pending_valid or not valid_path:
                violations.append(_violation(mutation, "damage_lifecycle_lethal_mutation_lineage_invalid"))
            return _trace(mutation, records, {"hp_mutation_id": str(metadata.get("hp_mutation_id") or ""),
                                              "lifecycle_operation": str(operation)})
        status = mutations_by_id.get(str(metadata.get("lifecycle_mutation_id")))
        valid_path = (mutation.path == ("units", target, "lifecycle_status")
                      and mutation.before == "limbo" and mutation.after == "defeated"
                      and metadata.get("lifecycle_status_before") == "limbo"
                      if operation == "unit_defeat" else
                      mutation.path == ("units", target, "flags", "defeat_record")
                      and isinstance(mutation.after, dict)
                      and status is not None and status.source == "damage_system"
                      and status.path == ("units", target, "lifecycle_status") and status.after == "defeated"
                      and mutation.after == {**defeat, "lifecycle_mutation_id": status.stable_id()}
                      and status.metadata.get("hp_mutation_id") == metadata.get("hp_mutation_id"))
        if (not pending_valid or hp is None or hp.source != "damage_system" or hp.op != "set"
                or hp.path != ("units", target, "hp")
                or type(hp.before) not in (int, float) or not math.isfinite(hp.before) or hp.before <= 0
                or type(hp.after) not in (int, float) or hp.after != 0
                or mutation.op != "set" or not valid_path
                or defeat.get("defeated_unit_id") != target
                or defeat.get("hp_mutation_id") != hp.stable_id()
                or defeat.get("target_before_hp") != hp.before or defeat.get("target_after_hp") != hp.after
                or hp.metadata.get("source_frame") != metadata.get("source_frame")
                or defeat.get("source_frame") != metadata.get("source_frame")
                or hp.metadata.get("source_trace") != metadata.get("source_trace")):
            violations.append(_violation(mutation, "damage_lifecycle_lethal_mutation_lineage_invalid"))
        return _trace(mutation, records, {"hp_mutation_id": str(metadata.get("hp_mutation_id") or ""),
                                          "lifecycle_operation": str(operation or "")})

    def _audit_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        if mutation.source == "combat_executor.timeline":
            return self._audit_action_source_mutation(mutation, records, violations, require_action_event=True)
        if mutation.source == "timeline_system":
            return self._audit_timeline_rule_mutation(mutation, records, violations)
        if mutation.source == "battle_state_transition_system":
            return self._audit_battle_state_transition_mutation(
                mutation,
                records,
                violations,
            )
        if mutation.source == "combat_executor.resources":
            return self._audit_action_source_mutation(mutation, records, violations, require_action_event=True)
        if mutation.source == "damage_system":
            return self._audit_damage_mutation(mutation, records, violations)
        if mutation.source == "damage_system.kill_energy":
            metadata = mutation.metadata
            trace = _trace(mutation, records, {"hp_mutation_id": str(metadata.get("hp_mutation_id") or "")})
            rule, blocked = self.rules.select_resource_rule("kill_energy_gain")
            if rule is None:
                violations.append(_violation(mutation, "kill_energy_rule_not_admitted", details={"reason": blocked}))
                return trace
            _audit_source(rule.source, rule.coverage_status, mutation, violations, executable_required=False)
            frame = metadata.get("source_frame")
            frame = frame if isinstance(frame, dict) else {}
            defeat = metadata.get("defeated_event_payload")
            defeat = defeat if isinstance(defeat, dict) else {}
            owner = frame.get("owner_id")
            if (not isinstance(owner, str) or not owner
                    or mutation.path != ("units", owner, "energy")
                    or metadata.get("target_id") != owner
                    or metadata.get("resource_operation") != "kill_energy_gain"
                    or metadata.get("resource_rule_id") != rule.resource_rule_id
                    or metadata.get("resource_rule_source") != rule.source.to_json()
                    or metadata.get("resource_rule_kind") != rule.rule_kind
                    or metadata.get("resource_rule_operation") != rule.operation
                    or metadata.get("resource_rule_source_kind") != rule.source_kind
                    or defeat.get("source_frame") != frame
                    or metadata.get("kill_credit_owner_id") != owner
                    or defeat.get("kill_credit_owner_id") != owner
                    or metadata.get("kill_credit_source_id") != frame.get("source_id")
                    or metadata.get("kill_credit_source_kind") != frame.get("source_kind")
                    or defeat.get("kill_credit_source_id") != frame.get("source_id")
                    or defeat.get("kill_credit_source_kind") != frame.get("source_kind")
                    or metadata.get("defeated_target_id") != defeat.get("target_id")
                    or metadata.get("lifecycle_mutation_id") != defeat.get("lifecycle_mutation_id")):
                violations.append(_violation(mutation, "kill_energy_source_contract_mismatch"))
            raw = metadata.get("raw_energy_gain")
            gain = metadata.get("energy_gain")
            regeneration = metadata.get("energy_regeneration_rate")
            rate = regeneration.get("value") if isinstance(regeneration, dict) else None
            if raw == 0:
                rate = 0.0
            capacity = metadata.get("energy_capacity")
            if (any(type(value) not in (int, float) or not math.isfinite(value)
                    for value in (raw, gain, rate, capacity, mutation.before, mutation.after))
                    or raw != rule.numeric_value or capacity <= 0
                    or not math.isclose(gain, raw * max(0.0, 1.0 + rate))
                    or not math.isclose(mutation.after, max(0.0, min(capacity, mutation.before + gain)))
                    or metadata.get("before_energy") != mutation.before
                    or metadata.get("after_energy") != mutation.after
                    or (raw > 0 and (regeneration.get("stat") != "energy_regeneration_rate"
                                     or not isinstance(regeneration.get("source_terms"), list)))):
                violations.append(_violation(mutation, "kill_energy_regeneration_lineage_invalid"))
            return trace
        if mutation.source == "damage_system.hit_energy":
            trace = self._audit_damage_mutation(mutation, records, violations)
            metadata = mutation.metadata
            emission = self.rules.damage_emission(str(metadata.get("damage_emission_id") or ""))
            raw = metadata.get("raw_delta")
            target_id = metadata.get("target_id")
            if (emission is None or emission.hit_energy_gain is None
                    or type(raw) not in (int, float) or not math.isfinite(raw)
                    or raw != emission.hit_energy_gain or raw < 0
                    or metadata.get("resource_operation") != "hit_energy_gain"
                    or not isinstance(target_id, str) or not target_id
                    or mutation.path != ("units", target_id, "energy")):
                violations.append(_violation(mutation, "hit_energy_source_contract_mismatch"))
                return trace
            regeneration = metadata.get("energy_regeneration_rate")
            rate = regeneration.get("value") if isinstance(regeneration, dict) else None
            if raw == 0:
                rate = 0.0
            delta = metadata.get("delta")
            capacity = metadata.get("energy_capacity")
            numbers = (rate, delta, capacity, mutation.before, mutation.after)
            if (any(type(value) not in (int, float) or not math.isfinite(value) for value in numbers)
                    or not math.isclose(delta, raw * max(0.0, 1.0 + rate))
                    or not math.isclose(mutation.after, max(0.0, min(
                        capacity if capacity > 0 else mutation.before + delta,
                        mutation.before + delta,
                    )))
                    or (raw > 0 and (regeneration.get("stat") != "energy_regeneration_rate"
                                     or not isinstance(regeneration.get("source_terms"), list)))):
                violations.append(_violation(mutation, "hit_energy_regeneration_lineage_invalid"))
            return trace
        if mutation.source == "toughness_system":
            return self._audit_toughness_mutation(mutation, records, violations)
        if mutation.source == "break_system":
            return self._audit_break_mutation(mutation, records, violations)
        if mutation.source == "status_callback_system":
            return self._audit_status_callback_mutation(mutation, records, violations)
        if mutation.source == "ability_property_watcher_system":
            return self._audit_ability_property_watcher_mutation(
                mutation,
                records,
                violations,
            )
        if mutation.source == "status_system":
            return self._audit_status_mutation(mutation, records, violations)
        if mutation.source == "effect_system":
            return self._audit_effect_mutation(mutation, records, violations)
        if mutation.source == "ability_provider_registry":
            return self._audit_ability_provider_mutation(
                mutation, records, violations
            )
        if mutation.source == "scenario_setup":
            return self._audit_scenario_setup_mutation(
                mutation, records, violations
            )
        if mutation.source in {"queue_system", "combat_executor.queue"}:
            return self._audit_queue_mutation(mutation, records, violations)
        if mutation.source == "enemy_action_system":
            return self._audit_enemy_action_mutation(mutation, records, violations)
        if mutation.source == "wave_system":
            return self._audit_wave_mutation(mutation, records, violations)
        if mutation.source == "monster_startup":
            return self._audit_monster_startup_mutation(mutation, records, violations)
        if mutation.source == "summon_system":
            return self._audit_summon_mutation(mutation, records, violations)
        violations.append(_violation(mutation, "unsupported_mutation_source", details={"records": list(records)}))
        return _trace(mutation, records, {})

    def _audit_monster_startup_mutation(
        self, mutation: Mutation, records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        from ..systems.startup import _passive_runtime_activation

        card_id = _required_str(mutation, mutation.metadata, "monster_data_card_id", violations)
        card = self.rules.monster_data_card(card_id) if card_id else None
        if card is None:
            violations.append(_violation(mutation, "monster_startup_card_missing"))
        else:
            _audit_source(card.source, card.coverage_status, mutation, violations, executable_required=False)
            activation = _passive_runtime_activation(self.rules, card)
            if (mutation.op != "set" or len(mutation.path) != 3
                    or mutation.path[0] != "units" or mutation.path[2] != "flags"
                    or not isinstance(mutation.before, dict)
                    or mutation.before.get("monster_data_card_id") != card.card_id
                    or mutation.after != freeze_json({**mutation.before, **activation["flags"]})
                    or activation["flags"].get("blocked_passive_mechanism_slots")
                    or mutation.metadata.get("source_trace") != card.source.to_json()):
                violations.append(_violation(mutation, "monster_startup_source_binding_invalid"))
        return _trace(mutation, records, {"monster_data_card_id": card_id})

    def _audit_scenario_setup_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        operation = _required_str(mutation, metadata, "setup_operation", violations)
        source_kind = _required_str(mutation, metadata, "source_kind", violations)
        scenario_id = _required_str(mutation, metadata, "scenario_id", violations)
        if source_kind and source_kind != "scenario_initial_condition":
            violations.append(
                _violation(
                    mutation,
                    "scenario_setup_source_kind_invalid",
                    details={"source_kind": source_kind},
                )
            )
        allowed_paths = {
            "timeline_global_av": ("global_flags", "global_av"),
            "timeline_policy": ("global_flags", "timeline_setup_policy"),
            "timeline_turn_owner": ("global_flags", "turn_owner_id"),
        }
        expected_path = allowed_paths.get(operation or "")
        if operation == "explicit_action_value":
            expected_path = (
                ("units", str(metadata.get("unit_id") or ""), "action_value")
                if metadata.get("unit_id")
                else None
            )
        if expected_path is None or mutation.path != expected_path:
            violations.append(
                _violation(
                    mutation,
                    "scenario_setup_path_invalid",
                    details={
                        "setup_operation": operation or "",
                        "expected": list(expected_path or ()),
                        "actual": list(mutation.path),
                    },
                )
            )
        matching_records = tuple(
            record
            for record in records
            if record.get("record_type") == "scenario_setup_mutation"
            and record.get("source") == "scenario_setup"
            and isinstance(record.get("payload"), dict)
            and record["payload"].get("setup_operation") == operation
            and record["payload"].get("path") == list(mutation.path)
            and record["payload"].get("after") == mutation.after
            and isinstance(record.get("trace"), dict)
            and record["trace"].get("source_kind")
            == "scenario_initial_condition"
            and record["trace"].get("scenario_id") == scenario_id
        )
        if not matching_records:
            violations.append(
                _violation(
                    mutation,
                    "scenario_setup_settlement_mismatch",
                    details={"setup_operation": operation or ""},
                )
            )
        return _trace(
            mutation,
            records,
            {
                "setup_operation": operation or "",
                "source_kind": source_kind or "",
                "scenario_id": scenario_id or "",
            },
        )

    def _audit_ability_provider_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        owner_unit_id = _required_str(
            mutation, metadata, "owner_unit_id", violations
        )
        provider_ids = metadata.get("provider_ids")
        providers = metadata.get("providers")
        _require_dict(mutation, metadata, "source_trace", violations)
        expected_path = (
            "units",
            owner_unit_id,
            "flags",
            "ability_providers",
        ) if owner_unit_id else ()
        if expected_path and mutation.path != expected_path:
            violations.append(
                _violation(
                    mutation,
                    "ability_provider_registry_path_invalid",
                    details={
                        "expected": list(expected_path),
                        "actual": list(mutation.path),
                    },
                )
            )
        if (
            not isinstance(provider_ids, (list, tuple))
            or not provider_ids
            or not all(isinstance(item, str) and item for item in provider_ids)
        ):
            violations.append(
                _violation(
                    mutation,
                    "ability_provider_ids_invalid",
                    missing_field="provider_ids",
                )
            )
            provider_ids = ()
        if (
            not isinstance(providers, (list, tuple))
            or not providers
            or not all(isinstance(item, dict) for item in providers)
        ):
            violations.append(
                _violation(
                    mutation,
                    "ability_provider_payloads_invalid",
                    missing_field="providers",
                )
            )
            providers = ()
        actual_provider_ids = tuple(
            str(provider.get("provider_id") or "")
            for provider in providers
            if isinstance(provider, dict)
        )
        if tuple(provider_ids) != actual_provider_ids:
            violations.append(
                _violation(
                    mutation,
                    "ability_provider_ids_do_not_match_payloads",
                    details={
                        "provider_ids": list(provider_ids),
                        "payload_provider_ids": list(actual_provider_ids),
                    },
                )
            )
        settlement_provider_ids = tuple(
            str(record.get("provider_id") or "")
            for record in records
            if record.get("record_type") == "ability_provider_registration"
            and record.get("source") == "ability_provider_registry"
            and record.get("mutation_id") == mutation.stable_id()
            and record.get("unit_id") == owner_unit_id
        )
        if tuple(provider_ids) != settlement_provider_ids:
            violations.append(
                _violation(
                    mutation,
                    "ability_provider_settlement_mismatch",
                    details={
                        "provider_ids": list(provider_ids),
                        "settlement_provider_ids": list(settlement_provider_ids),
                    },
                )
            )
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            graph_ref_id = str(provider.get("graph_ref_id") or "")
            graph = self.rules.standalone_ability_graph(graph_ref_id)
            provider_source = provider.get("source")
            if (
                graph is None
                or graph.coverage_status != "executable"
                or provider_source != graph.source.to_json()
            ):
                violations.append(
                    _violation(
                        mutation,
                        "ability_provider_graph_missing_partial_or_wrong_source",
                        details={"graph_ref_id": graph_ref_id},
                    )
                )
            else:
                _audit_source(
                    graph.source,
                    graph.coverage_status,
                    mutation,
                    violations,
                    executable_required=True,
                )
            mechanism_key = provider.get("mechanism_key")
            mechanism_identity = (
                mechanism_key.get("definition_identity")
                if isinstance(mechanism_key, dict)
                else None
            )
            mechanism_resolution = (
                self.rules.equipment_mechanism_ref(mechanism_identity)
                if isinstance(mechanism_identity, str) and mechanism_identity
                else None
            )
            mechanism = (
                mechanism_resolution.value
                if mechanism_resolution is not None
                and mechanism_resolution.resolution_status == "resolved"
                else None
            )
            if mechanism is None or mechanism.graph_ref_id != graph_ref_id:
                violations.append(
                    _violation(
                        mutation,
                        "ability_provider_mechanism_reference_unresolved",
                        details={
                            "mechanism_identity": mechanism_identity or "",
                            "graph_ref_id": graph_ref_id,
                        },
                    )
                )
            definition_key = provider.get("target_definition_key")
            definition_identity = (
                definition_key.get("definition_identity")
                if isinstance(definition_key, dict)
                else None
            )
            definition_kind = (
                definition_key.get("definition_kind")
                if isinstance(definition_key, dict)
                else None
            )
            definition_resolution = None
            if isinstance(definition_identity, str) and definition_identity:
                if definition_kind == "light_cone":
                    definition_resolution = self.rules.light_cone_definition(
                        definition_identity
                    )
                elif definition_kind == "relic_set_threshold":
                    definition_resolution = self.rules.relic_set_threshold(
                        definition_identity
                    )
            definition = (
                definition_resolution.value
                if definition_resolution is not None
                and definition_resolution.resolution_status == "resolved"
                else None
            )
            if (
                definition is None
                or mechanism_key not in (
                    key.to_json() for key in definition.mechanism_ref_ids
                )
            ):
                violations.append(
                    _violation(
                        mutation,
                        "ability_provider_target_definition_mismatch",
                        details={
                            "definition_kind": str(definition_kind or ""),
                            "definition_identity": definition_identity or "",
                            "mechanism_identity": mechanism_identity or "",
                        },
                    )
                )
        return _trace(
            mutation,
            records,
            {
                "owner_unit_id": owner_unit_id or "",
                "provider_ids": list(provider_ids),
            },
        )

    def _audit_action_source_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
        *,
        require_action_event: bool,
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        action_id = _required_str(mutation, metadata, "action_id", violations)
        action_level = _required_int(mutation, metadata, "action_level", violations)
        definition_id = _required_str(mutation, metadata, "definition_id", violations)
        if action_id and action_level is not None:
            definition = self.rules.action_definition(action_id, action_level)
            if definition is None:
                violations.append(_violation(mutation, "action_definition_missing", details={"action_id": action_id, "level": action_level}))
            elif definition.definition_id != definition_id:
                violations.append(
                    _violation(
                        mutation,
                        "action_definition_id_mismatch",
                        details={"expected": definition.definition_id, "actual": definition_id},
                    )
                )
            else:
                _audit_source(definition.source, definition.coverage_status, mutation, violations, executable_required=True)
        action_event_id = _required_str(mutation, metadata, "action_event_id", violations) if require_action_event else ""
        if action_id and action_level is not None and action_event_id:
            event = self.rules.action_event(action_id, action_level)
            if event is None:
                violations.append(_violation(mutation, "action_event_missing", details={"action_id": action_id, "level": action_level}))
            elif event.action_event_id != action_event_id:
                violations.append(
                    _violation(
                        mutation,
                        "action_event_id_mismatch",
                        details={"expected": event.action_event_id, "actual": action_event_id},
                    )
                )
            else:
                _audit_source(event.source, event.coverage_status, mutation, violations, check_status=False)
        resource_operation = _first_str(metadata.get("resource_operation"))
        resource_rule_id = _first_str(metadata.get("resource_rule_id"))
        if resource_operation in {"ultimate_energy_cost", "kill_energy_gain"}:
            if not resource_rule_id:
                violations.append(_violation(mutation, "resource_rule_id_missing", missing_field="resource_rule_id"))
            else:
                rule = self.rules.resource_rule(resource_rule_id)
                if rule is None:
                    violations.append(_violation(mutation, "resource_rule_missing", details={"resource_rule_id": resource_rule_id}))
                else:
                    if rule.coverage_status != "executable":
                        violations.append(
                            _violation(
                                mutation,
                                "resource_rule_not_executable",
                                details={"resource_rule_id": resource_rule_id, "coverage_status": rule.coverage_status},
                            )
                        )
                    if rule.source_kind not in {"tbgd", "engine_convention"}:
                        violations.append(
                            _violation(
                                mutation,
                                "resource_rule_source_kind_not_admitted",
                                details={"resource_rule_id": resource_rule_id, "source_kind": rule.source_kind},
                            )
                        )
                    _audit_source(rule.source, rule.coverage_status, mutation, violations, executable_required=False)
        _require_dict(mutation, metadata, "source_trace", violations)
        return _trace(
            mutation,
            records,
            {
                "action_id": action_id or "",
                "action_level": action_level if action_level is not None else "",
                "definition_id": definition_id or "",
                "action_event_id": action_event_id or "",
                "resource_operation": resource_operation,
                "resource_rule_id": resource_rule_id,
            },
        )

    def _audit_enemy_action_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        actor_id = _required_str(mutation, metadata, "actor_id", violations)
        expected_path = ("units", actor_id, "flags", "enemy_action_sequence_cursor") if actor_id else ()
        if expected_path and mutation.path != expected_path:
            violations.append(
                _violation(
                    mutation,
                    "enemy_action_cursor_path_invalid",
                    details={"expected": list(expected_path), "actual": list(mutation.path)},
                )
            )
        card_id = _required_str(mutation, metadata, "monster_data_card_id", violations)
        sequence_index = _required_int(mutation, metadata, "sequence_index", violations)
        action_id = _required_str(mutation, metadata, "action_id", violations)
        action_level = _required_int(mutation, metadata, "action_level", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        card = self.rules.monster_data_card(card_id) if card_id else None
        if card is None:
            violations.append(_violation(mutation, "monster_data_card_missing", details={"monster_data_card_id": card_id}))
        else:
            _audit_source(card.source, card.coverage_status, mutation, violations, executable_required=False)
            if str(card.ai_policy.get("admission_status") or "") != "executable":
                violations.append(
                    _violation(
                        mutation,
                        "enemy_ai_policy_not_executable",
                        details={"monster_data_card_id": card.card_id, "ai_policy": card.ai_policy},
                    )
                )
            if sequence_index is None or sequence_index < 0 or sequence_index >= len(card.action_sequence):
                violations.append(
                    _violation(
                        mutation,
                        "enemy_action_sequence_index_invalid",
                        details={"sequence_index": sequence_index if sequence_index is not None else -1, "sequence_length": len(card.action_sequence)},
                    )
                )
            elif action_id:
                step = card.action_sequence[sequence_index]
                if str(step.get("action_ref") or "") != action_id:
                    violations.append(
                        _violation(
                            mutation,
                            "enemy_action_sequence_action_mismatch",
                            details={"expected": step.get("action_ref"), "actual": action_id},
                        )
                    )
                if str(step.get("coverage_status") or "") == "blocked":
                    violations.append(
                        _violation(
                            mutation,
                            "enemy_action_sequence_step_blocked_produced_mutation",
                            details={"step": step},
                        )
                    )
        definition = self.rules.action_definition(action_id, action_level) if action_id and action_level is not None else None
        if definition is None:
            violations.append(_violation(mutation, "action_definition_missing", details={"action_id": action_id, "level": action_level}))
        else:
            _audit_source(definition.source, definition.coverage_status, mutation, violations, executable_required=True)
        return _trace(
            mutation,
            records,
            {
                "actor_id": actor_id,
                "monster_data_card_id": card_id,
                "sequence_index": sequence_index if sequence_index is not None else -1,
                "action_id": action_id,
                "action_level": action_level if action_level is not None else -1,
            },
        )

    def _audit_timeline_rule_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        timeline_rule_id = _required_str(mutation, metadata, "timeline_rule_id", violations)
        plan_id = _required_str(mutation, metadata, "turn_advance_plan_id", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        if timeline_rule_id:
            rule = self.rules.timeline_rule(timeline_rule_id)
            if rule is None:
                violations.append(_violation(mutation, "timeline_rule_missing", details={"timeline_rule_id": timeline_rule_id}))
            else:
                if rule.coverage_status != "executable":
                    violations.append(
                        _violation(
                            mutation,
                            "timeline_rule_not_executable",
                            details={"timeline_rule_id": timeline_rule_id, "coverage_status": rule.coverage_status},
                        )
                    )
                if rule.source_kind not in {"tbgd", "engine_convention"}:
                    violations.append(
                        _violation(
                            mutation,
                            "timeline_rule_source_kind_not_admitted",
                            details={"timeline_rule_id": timeline_rule_id, "source_kind": rule.source_kind},
                        )
                    )
                _audit_source(rule.source, rule.coverage_status, mutation, violations, executable_required=False)
        return _trace(
            mutation,
            records,
            {
                "timeline_rule_id": timeline_rule_id or "",
                "turn_advance_plan_id": plan_id or "",
            },
        )

    def _audit_battle_state_transition_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        transition_rule_id = _required_str(
            mutation,
            metadata,
            "battle_state_transition_rule_id",
            violations,
        )
        trigger_kind = _required_str(
            mutation,
            metadata,
            "trigger_kind",
            violations,
        )
        trigger_identity = _required_str(
            mutation,
            metadata,
            "trigger_identity",
            violations,
        )
        runtime_event_type = _required_str(
            mutation,
            metadata,
            "runtime_event_type",
            violations,
        )
        callback_event = _required_str(
            mutation,
            metadata,
            "callback_event",
            violations,
        )
        _require_dict(
            mutation,
            metadata,
            "source_trace",
            violations,
        )
        source_trace = (
            metadata.get("source_trace")
            if isinstance(metadata.get("source_trace"), dict)
            else {}
        )
        rule = (
            self.rules.battle_state_transition(transition_rule_id)
            if transition_rule_id
            else None
        )
        if rule is None:
            violations.append(
                _violation(
                    mutation,
                    "battle_state_transition_rule_missing",
                    details={"transition_rule_id": transition_rule_id or ""},
                )
            )
        else:
            if rule.coverage_status != "executable":
                violations.append(
                    _violation(
                        mutation,
                        "battle_state_transition_rule_not_executable",
                        details={
                            "transition_rule_id": rule.transition_rule_id,
                            "coverage_status": rule.coverage_status,
                        },
                    )
                )
            moment_operation = metadata.get("elation_operation")
            moment_transition = moment_operation in {"start_moment", "end_moment"}
            value_matches = (
                self._audit_elation_moment_value(mutation, rule)
                if moment_transition else (
                    tuple(mutation.path) == rule.state_path
                    and type(mutation.after) is type(rule.after_value)
                    and mutation.after == rule.after_value
                )
            )
            contract_matches = (
                value_matches
                and trigger_kind == rule.trigger_kind
                and trigger_identity == rule.trigger_identity
                and runtime_event_type == rule.runtime_event_type
                and callback_event == rule.callback_event
                and source_trace == rule.source.to_json()
            )
            if not contract_matches:
                violations.append(
                    _violation(
                        mutation,
                        "battle_state_transition_contract_mismatch",
                        details={
                            "transition_rule_id": rule.transition_rule_id,
                            "expected_path": list(rule.state_path),
                            "expected_runtime_event_type": (
                                rule.runtime_event_type
                            ),
                            "expected_callback_event": rule.callback_event,
                        },
                    )
                )
            if moment_transition:
                pass  # The ledger has its own before/after contract above.
            elif mutation.before_exists:
                if (
                    type(mutation.before) is not type(rule.before_value)
                    or mutation.before != rule.before_value
                ):
                    violations.append(
                        _violation(
                            mutation,
                            "battle_state_transition_before_value_mismatch",
                        )
                    )
            elif not rule.allow_missing_before:
                violations.append(
                    _violation(
                        mutation,
                        "battle_state_transition_missing_before_not_admitted",
                    )
                )
            _audit_source(
                rule.source,
                rule.coverage_status,
                mutation,
                violations,
                executable_required=False,
            )
        return _trace(
            mutation,
            records,
            {
                "battle_state_transition_rule_id": transition_rule_id or "",
                "trigger_kind": trigger_kind or "",
                "trigger_identity": trigger_identity or "",
            },
        )

    @staticmethod
    def _audit_elation_moment_value(mutation: Mutation, rule) -> bool:
        from ..systems.elation import validate_elation_runtime

        if (mutation.op != "set" or mutation.path != ("global_flags", "elation_runtime")
                or rule.state_path != ("global_flags", "elation_time_active")
                or type(rule.after_value) is not bool
                or rule.before_value is not (not rule.after_value)):
            return False
        before = mutation.before if mutation.before_exists else {
            "schema_version": "hsr.elation_runtime.v1", "base_points": 0.0, "moments": {},
            "active_moment_id": "", "moment_sequence": 0,
        }
        after = mutation.after
        if validate_elation_runtime(before) or validate_elation_runtime(after):
            return False
        if after["base_points"] != before["base_points"]:
            return False
        if rule.after_value:
            identity = after["active_moment_id"]
            if (mutation.metadata.get("elation_operation") != "start_moment"
                    or before["active_moment_id"] or not identity
                    or after["moment_sequence"] != before["moment_sequence"] + 1
                    or identity in before["moments"]):
                return False
            row = after["moments"][identity]
            return (
                {key: value for key, value in after["moments"].items() if key != identity} == before["moments"]
                and row["points"] == before["base_points"]
                and (not rule.participant_team or row["team"] == rule.participant_team)
                and row["source_trace"] == rule.source.to_json()
            )
        identity = before["active_moment_id"]
        return (
            mutation.metadata.get("elation_operation") == "end_moment" and bool(identity)
            and not after["active_moment_id"]
            and after["moment_sequence"] == before["moment_sequence"]
            and after["moments"] == {
                identity: {**before["moments"][identity], "active": False},
            }
        )

    def _audit_wave_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        _require_dict(mutation, metadata, "source_trace", violations)
        plan = metadata.get("wave_transition_plan") if isinstance(metadata.get("wave_transition_plan"), dict) else {}
        removed_record = metadata.get("removed_record") if isinstance(metadata.get("removed_record"), dict) else {}
        wave_definition_id = _first_str(
            plan.get("wave_definition_id") if isinstance(plan, dict) else None,
            removed_record.get("wave_definition_id") if isinstance(removed_record, dict) else None,
            metadata.get("wave_definition_id"),
        )
        if wave_definition_id:
            definition = self.rules.wave_definition(wave_definition_id)
            if definition is None:
                violations.append(_violation(mutation, "wave_definition_missing", details={"wave_definition_id": wave_definition_id}))
            else:
                _audit_source(definition.source, definition.coverage_status, mutation, violations, executable_required=True)
        elif not metadata.get("outcome"):
            violations.append(_violation(mutation, "wave_definition_id_missing", missing_field="wave_definition_id"))
        return _trace(
            mutation,
            records,
            {
                "wave_definition_id": wave_definition_id,
                "lifecycle_operation": str(metadata.get("lifecycle_operation") or ""),
                "status_cleanup_operation": str(metadata.get("status_cleanup_operation") or ""),
                "outcome": str(metadata.get("outcome") or ""),
            },
        )

    def _audit_summon_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        _require_dict(mutation, metadata, "source_trace", violations)
        plan = metadata.get("summon_plan") if isinstance(metadata.get("summon_plan"), dict) else {}
        plan_metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        removed_record = metadata.get("removed_record") if isinstance(metadata.get("removed_record"), dict) else {}
        operation = _first_str(
            metadata.get("summon_operation"),
            plan.get("operation"),
            removed_record.get("summon_operation"),
        )
        intent_ids = _summon_audit_intent_ids(metadata, plan, plan_metadata, removed_record)
        if not intent_ids:
            violations.append(
                _violation(
                    mutation,
                    "summon_source_ir_missing",
                    missing_field="intent_id",
                    details={"operation": operation, "metadata": metadata},
                )
            )
        for intent_id in intent_ids:
            servant_definition = self.rules.servant_definition(intent_id)
            if servant_definition is not None:
                _audit_source(servant_definition.source, servant_definition.coverage_status, mutation, violations, executable_required=True)
                continue
            summon_intent = self.rules.summon_monster_intent(intent_id)
            if summon_intent is not None:
                _audit_source(summon_intent.source, summon_intent.coverage_status, mutation, violations, executable_required=True)
                continue
            violations.append(
                _violation(
                    mutation,
                    "summon_source_ir_missing",
                    details={"operation": operation, "intent_id": intent_id},
                )
            )
        if operation == "remove_summon":
            admission = metadata.get("remove_admission")
            if not isinstance(admission, dict):
                admission = removed_record.get("remove_admission")
            if not isinstance(admission, dict):
                admission = plan_metadata.get("remove_admission")
            if (
                not isinstance(admission, dict)
                or admission.get("coverage_status") != "executable"
                or admission.get("remove_source_admitted") is not True
            ):
                violations.append(
                    _violation(
                        mutation,
                        "summon_remove_source_not_admitted",
                        missing_field="remove_admission",
                        details={"operation": operation, "admission": admission if isinstance(admission, dict) else {}},
                    )
                )
        if operation == "owner_removed_cleanup":
            admissions = plan_metadata.get("remove_admissions")
            if isinstance(admissions, list) and admissions:
                for admission in admissions:
                    if not isinstance(admission, dict):
                        violations.append(_violation(mutation, "summon_remove_admission_invalid", details={"admission": admission}))
                        continue
                    if admission.get("coverage_status") != "executable" or admission.get("remove_source_admitted") is not True:
                        violations.append(
                            _violation(
                                mutation,
                                "summon_remove_source_not_admitted",
                                details={"operation": operation, "admission": admission},
                            )
                        )
        is_unit_spawn = (
            mutation.op == "spawn"
            and len(mutation.path) == 2
            and mutation.path[0] == "units"
        )
        if is_unit_spawn:
            if not isinstance(mutation.after, Mapping):
                violations.append(
                    _violation(
                        mutation,
                        "summon_spawn_payload_invalid",
                        missing_field="mutation.after",
                        details={"payload_type": type(mutation.after).__name__},
                    )
                )
            else:
                unit_spawn_after = mutation.after
                unit_spawn_flags = unit_spawn_after.get("flags")
                if not isinstance(unit_spawn_flags, Mapping):
                    violations.append(
                        _violation(
                            mutation,
                            "summon_spawn_payload_flags_missing",
                            missing_field="mutation.after.flags",
                        )
                    )
                    unit_spawn_flags = {}
                unit_summon_kind = str(unit_spawn_flags.get("summon_kind") or "")
                if unit_summon_kind == "summoned_monster":
                    if operation != "spawn_summoned_monster":
                        violations.append(
                            _violation(
                                mutation,
                                "summon_spawn_operation_label_missing_or_mismatched",
                                details={"summon_operation": operation},
                            )
                        )
                    # The birth audit is driven by the actual spawned unit and the
                    # formal summon definition, never by a metadata label.
                    self._audit_summoned_monster_birth_stats(mutation, records, violations)
                elif unit_summon_kind == "servant":
                    if operation != "servant_spawn":
                        violations.append(
                            _violation(
                                mutation,
                                "summon_spawn_operation_label_missing_or_mismatched",
                                details={"summon_operation": operation, "summon_kind": unit_summon_kind},
                            )
                        )
                    self._audit_servant_spawn_mutation(mutation, records, violations)
                else:
                    violations.append(
                        _violation(
                            mutation,
                            "summon_spawn_unit_kind_missing_or_unrecognized",
                            details={
                                "summon_kind": _deep_json_copy(unit_spawn_flags.get("summon_kind")),
                            },
                        )
                    )
        return _trace(
            mutation,
            records,
            {
                "summon_operation": operation,
                "intent_ids": list(intent_ids),
                "lifecycle_operation": str(metadata.get("lifecycle_operation") or ""),
                "status_cleanup_operation": str(metadata.get("status_cleanup_operation") or ""),
                "queue_cleanup_operation": str(metadata.get("queue_cleanup_operation") or ""),
                "turn_owner_cleanup_operation": str(metadata.get("turn_owner_cleanup_operation") or ""),
            },
        )

    def _audit_summoned_monster_birth_stats(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> None:
        """Rebuild a summoned monster's birth panel from the formal summon chain.

        Accepted authorities are the compiled intent -> entry -> birth template
        chain, the battle stage level policy it was resolved against and the
        native settlement plan recorded for this mutation. Metadata labels, unit
        flags and recorded numbers are compared against those facts instead of
        being trusted as their own source.
        """

        metadata = mutation.metadata
        after = mutation.after if isinstance(mutation.after, Mapping) else None
        if not isinstance(after, Mapping):
            violations.append(_violation(mutation, "summon_birth_payload_missing", missing_field="mutation.after"))
            return
        flags = after.get("flags") if isinstance(after.get("flags"), Mapping) else {}
        intent_id = _first_str(
            flags.get("summon_intent_id"),
            metadata.get("summon_intent_id"),
        )
        intent = self.rules.summon_monster_intent(intent_id) if intent_id else None
        if intent is None or intent.coverage_status != "executable":
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_intent_missing_or_blocked",
                    details={"summon_intent_id": intent_id},
                )
            )
            return
        entry_id = _first_str(flags.get("summon_entry_id"), metadata.get("summon_entry_id"))
        entries = tuple(entry for entry in intent.entries if entry.entry_id == entry_id)
        if len(entries) != 1:
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_entry_missing_or_ambiguous",
                    details={"summon_entry_id": entry_id},
                )
            )
            return
        entry = entries[0]
        template = self.rules.unit_birth_template(entry.birth_template_id)
        if template is None or template.coverage_status != "executable":
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_template_missing_or_blocked",
                    details={"birth_template_id": entry.birth_template_id},
                )
            )
            return
        expected_profile_id = _first_str(template.flag_specs.get("combatant_profile_id"))
        policy_profile_id = _first_str(entry.level_policy.get("profile_id"))
        if not expected_profile_id or expected_profile_id != policy_profile_id:
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_profile_binding_mismatch",
                    details={"template_profile_id": expected_profile_id, "entry_policy_profile_id": policy_profile_id},
                )
            )
        if (
            _first_str(flags.get("combatant_profile_id")) != expected_profile_id
            or _first_str(metadata.get("combatant_profile_id")) != expected_profile_id
        ):
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_profile_identity_mismatch",
                    details={
                        "template_profile_id": expected_profile_id,
                        "unit_profile_id": _deep_json_copy(flags.get("combatant_profile_id")),
                        "record_profile_id": _deep_json_copy(metadata.get("combatant_profile_id")),
                    },
                )
            )
        if after.get("template_id") != entry.monster_entity_ref or after.get("unit_id") != mutation.path[1]:
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_unit_identity_mismatch",
                    details={
                        "entry_entity_ref": entry.monster_entity_ref,
                        "unit_template_id": _deep_json_copy(after.get("template_id")),
                        "mutation_unit_id": _deep_json_copy(after.get("unit_id")),
                        "path_unit_id": str(mutation.path[1]),
                    },
                )
            )
        if (
            _first_str(flags.get("summon_intent_id")) != intent.summon_intent_id
            or _first_str(metadata.get("summon_intent_id")) != intent.summon_intent_id
            or _first_str(flags.get("summon_entry_id")) != entry.entry_id
            or _first_str(metadata.get("summon_entry_id")) != entry.entry_id
        ):
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_intent_identity_mismatch",
                    details={"summon_intent_id": intent.summon_intent_id, "summon_entry_id": entry.entry_id},
                )
            )
        context = metadata.get("summon_level_context")
        if not isinstance(context, Mapping) or context.get("admission_status") != "executable":
            violations.append(
                _violation(
                    mutation,
                    "summon_level_context_missing",
                    missing_field="summon_level_context",
                )
            )
            return
        context_identity = _audit_level_context_identity(context)
        carried_context = flags.get("summon_level_context")
        if (
            not isinstance(carried_context, Mapping)
            or _audit_level_context_identity(carried_context) != context_identity
        ):
            violations.append(
                _violation(
                    mutation,
                    "summon_level_context_carried_mismatch",
                    details={
                        "record": _deep_json_copy(context),
                        "unit_flags": _deep_json_copy(carried_context),
                    },
                )
            )
        wave_definition_id = str(context.get("wave_definition_id") or "")
        definition = self.rules.wave_definition(wave_definition_id) if wave_definition_id else None
        if definition is None:
            violations.append(
                _violation(
                    mutation,
                    "summon_level_context_wave_definition_missing",
                    details={"wave_definition_id": wave_definition_id},
                )
            )
            return
        policy = definition.level_policy if isinstance(definition.level_policy, Mapping) else {}
        if policy.get("admission_status") != "executable":
            violations.append(
                _violation(
                    mutation,
                    "summon_battle_level_policy_not_executable",
                    details={"level_policy": _deep_json_copy(policy)},
                )
            )
            return
        if str(context.get("stage_id") or "") != str(definition.stage_id):
            violations.append(
                _violation(
                    mutation,
                    "summon_level_context_stage_mismatch",
                    details={
                        "context_stage_id": _deep_json_copy(context.get("stage_id")),
                        "wave_stage_id": definition.stage_id,
                    },
                )
            )
        for field_name in ("level", "hard_level_group", "elite_group"):
            if context.get(field_name) != policy.get(field_name):
                violations.append(
                    _violation(
                        mutation,
                        f"summon_level_context_{field_name}_mismatch",
                        details={
                            "context": _deep_json_copy(context.get(field_name)),
                            "level_policy": _deep_json_copy(policy.get(field_name)),
                        },
                    )
                )
        if after.get("level") != context.get("level"):
            violations.append(
                _violation(
                    mutation,
                    "summon_level_context_unit_level_mismatch",
                    details={
                        "unit_level": _deep_json_copy(after.get("level")),
                        "context_level": _deep_json_copy(context.get("level")),
                    },
                )
            )
        policy_ratios = policy.get("ratios") if isinstance(policy.get("ratios"), Mapping) else {}
        context_ratios = context.get("ratios") if isinstance(context.get("ratios"), Mapping) else {}
        scaling = flags.get("summon_stat_scaling")
        scaling_ratios = (
            scaling.get("ratios")
            if isinstance(scaling, Mapping) and isinstance(scaling.get("ratios"), Mapping)
            else {}
        )
        resolved_ratios: dict[str, float] = {}
        for field_name in _SUMMON_BIRTH_STAT_FIELDS:
            expected_ratio = _audit_number(policy_ratios.get(field_name))
            if expected_ratio is None:
                violations.append(
                    _violation(
                        mutation,
                        f"summon_level_ratio_missing:{field_name}",
                        details={"level_policy_ratio": None},
                    )
                )
                continue
            resolved_ratios[field_name] = expected_ratio
            for label, candidate in (
                ("context", _audit_number(context_ratios.get(field_name))),
                ("unit_flags", _audit_number(scaling_ratios.get(field_name))),
            ):
                if candidate is None or not math.isclose(
                    candidate, expected_ratio, rel_tol=1e-9, abs_tol=1e-9
                ):
                    violations.append(
                        _violation(
                            mutation,
                            f"summon_level_ratio_mismatch:{field_name}:{label}",
                            details={
                                "level_policy_ratio": expected_ratio,
                                "recorded_ratio": candidate,
                            },
                        )
                    )
        expected_source_tree = _audit_source_tree(policy.get("source_trace"))
        if not expected_source_tree:
            violations.append(
                _violation(
                    mutation,
                    "summon_level_source_trace_missing",
                    missing_field="level_policy.source_trace",
                )
            )
        for label, candidate in (
            ("context", context.get("source_trace")),
            (
                "carried_context",
                carried_context.get("source_trace")
                if isinstance(carried_context, Mapping)
                else None,
            ),
            ("unit_flags", flags.get("summon_level_source_trace")),
            ("record", metadata.get("summon_level_source_trace")),
            ("unit_scaling", scaling.get("source_trace") if isinstance(scaling, Mapping) else None),
        ):
            actual_tree = _audit_source_tree(candidate)
            if actual_tree != expected_source_tree:
                violations.append(
                    _violation(
                        mutation,
                        f"summon_level_source_trace_mismatch:{label}",
                        details={
                            "expected_tree": _deep_json_copy(expected_source_tree),
                            "actual_tree": _deep_json_copy(actual_tree),
                        },
                    )
                )
        expected_context_identity = context_identity
        if (
            not isinstance(scaling, Mapping)
            or _audit_scaling_summary_identity(scaling) != expected_context_identity
        ):
            violations.append(
                _violation(
                    mutation,
                    "summon_stat_scaling_summary_mismatch:unit_flags",
                    details={
                        "unit_scaling": _deep_json_copy(scaling),
                        "expected_context": _deep_json_copy(context),
                    },
                )
            )
        profile = (
            self.rules.combatant_profile_by_profile_id(expected_profile_id)
            if expected_profile_id
            else None
        )
        if profile is None or profile.coverage_status != "executable":
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_combatant_profile_missing_or_blocked",
                    details={"combatant_profile_id": expected_profile_id},
                )
            )
            return
        base_values = {
            "max_hp": _audit_number(profile.base_stats.get("max_hp")),
            "attack": _audit_number(profile.base_stats.get("attack")),
            "defense": _audit_number(profile.base_stats.get("defense")),
            "speed": _audit_number(profile.base_stats.get("speed")),
            "max_toughness": _audit_number(profile.toughness_profile.get("max_toughness")),
        }
        expected_panel: dict[str, float] = {}
        for field_name in _SUMMON_BIRTH_STAT_FIELDS:
            spec = template.unit_field_specs.get(field_name)
            template_base = _audit_number(spec.get("base_value")) if isinstance(spec, Mapping) else None
            if (
                not isinstance(spec, Mapping)
                or spec.get("binding_kind") != "level_context_scaled_stat"
                or spec.get("field_name") != field_name
                or template_base is None
            ):
                violations.append(
                    _violation(
                        mutation,
                        f"summon_birth_template_scaling_binding_invalid:{field_name}",
                        details={"spec": _deep_json_copy(spec)},
                    )
                )
            base_value = base_values[field_name]
            ratio = resolved_ratios.get(field_name)
            if (
                template_base is None
                or base_value is None
                or not math.isclose(template_base, base_value, rel_tol=1e-9, abs_tol=1e-9)
            ):
                violations.append(
                    _violation(
                        mutation,
                        f"summon_birth_template_base_mismatch:{field_name}",
                        details={"template_base": template_base, "profile_base": base_value},
                    )
                )
            if base_value is None or ratio is None:
                continue
            expected_panel[field_name] = base_value * ratio
            actual_value = _audit_number(after.get(field_name))
            if actual_value is None or not math.isclose(
                actual_value, expected_panel[field_name], rel_tol=1e-9, abs_tol=1e-9
            ):
                violations.append(
                    _violation(
                        mutation,
                        f"summoned_monster_birth_stat_mismatch:{field_name}",
                        details={
                            "base_value": base_value,
                            "ratio": ratio,
                            "expected_value": expected_panel[field_name],
                            "actual_value": actual_value,
                        },
                    )
                )
        max_hp = _audit_number(after.get("max_hp"))
        hp = _audit_number(after.get("hp"))
        if max_hp is None or hp is None or not math.isclose(hp, max_hp, rel_tol=1e-9, abs_tol=1e-9):
            violations.append(
                _violation(
                    mutation,
                    "summoned_monster_birth_hp_not_full",
                    details={"hp": hp, "max_hp": max_hp},
                )
            )
        max_toughness = _audit_number(after.get("max_toughness"))
        toughness = _audit_number(after.get("toughness"))
        if (
            max_toughness is None
            or toughness is None
            or not math.isclose(toughness, max_toughness, rel_tol=1e-9, abs_tol=1e-9)
        ):
            violations.append(
                _violation(
                    mutation,
                    "summoned_monster_birth_toughness_not_full",
                    details={"toughness": toughness, "max_toughness": max_toughness},
                )
            )
        action_spec = template.unit_field_specs.get("action_value")
        template_gauge = _audit_number(action_spec.get("base_action_gauge")) if isinstance(action_spec, Mapping) else None
        template_multiplier = _audit_number(action_spec.get("multiplier")) if isinstance(action_spec, Mapping) else None
        timeline_rule = next(
            (
                rule
                for rule in self.rules.ir.timeline_rules
                if rule.coverage_status == "executable"
            ),
            None,
        )
        timeline_gauge = _audit_number(timeline_rule.base_action_gauge) if timeline_rule is not None else None
        if (
            not isinstance(action_spec, Mapping)
            or action_spec.get("binding_kind") != "timeline_action_value"
            or action_spec.get("speed_field") != "speed"
            or template_gauge is None
            or timeline_gauge is None
            or not math.isclose(template_gauge, timeline_gauge, rel_tol=1e-9, abs_tol=1e-9)
        ):
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_action_value_binding_invalid",
                    details={
                        "action_value_spec": _deep_json_copy(action_spec),
                        "timeline_base_action_gauge": timeline_gauge,
                    },
                )
            )
            return
        intent_delay = intent.delay_policy if isinstance(intent.delay_policy, Mapping) else {}
        recorded_delay = (
            metadata.get("summon_delay_policy")
            if isinstance(metadata.get("summon_delay_policy"), Mapping)
            else {}
        )
        if intent_delay.get("admission_status") != "executable":
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_delay_policy_not_admitted",
                    details={"delay_policy": _deep_json_copy(intent_delay)},
                )
            )
            return
        if not _audit_value_equal(recorded_delay, intent_delay):
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_delay_policy_mismatch",
                    details={
                        "recorded": _deep_json_copy(recorded_delay),
                        "intent": _deep_json_copy(intent_delay),
                    },
                )
            )
        intent_multiplier = _audit_number(intent_delay.get("value"))
        if (
            template_multiplier is None
            or intent_multiplier is None
            or not math.isclose(template_multiplier, intent_multiplier, rel_tol=1e-9, abs_tol=1e-9)
        ):
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_delay_ratio_binding_mismatch",
                    details={
                        "template_multiplier": template_multiplier,
                        "intent_value": intent_multiplier,
                    },
                )
            )
        expected_speed = expected_panel.get("speed")
        action_value = _audit_number(after.get("action_value"))
        expected_action_value = (
            timeline_gauge / expected_speed * template_multiplier
            if expected_speed is not None
            and expected_speed > 0
            and template_multiplier is not None
            else None
        )
        if (
            expected_action_value is None
            or action_value is None
            or not math.isclose(
                action_value, expected_action_value, rel_tol=1e-9, abs_tol=1e-9
            )
        ):
            violations.append(
                _violation(
                    mutation,
                    "summoned_monster_birth_action_value_mismatch",
                    details={
                        "expected_speed": expected_speed,
                        "delay_ratio": template_multiplier,
                        "expected_action_value": expected_action_value,
                        "actual_action_value": action_value,
                    },
                )
            )
        unit_id = str(mutation.path[1])
        plan = _audit_summon_spawn_plan(records, mutation)
        if not isinstance(plan, Mapping):
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_settlement_plan_missing",
                    missing_field="summon_plan",
                )
            )
            return
        plan_unit_ids = plan.get("unit_ids")
        if (
            not isinstance(plan_unit_ids, (list, tuple))
            or unit_id not in plan_unit_ids
        ):
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_settlement_plan_unit_ids_mismatch",
                    details={"unit_id": unit_id, "plan_unit_ids": _deep_json_copy(plan_unit_ids)},
                )
            )
        if plan.get("operation") != "spawn_summoned_monster" or plan.get("ok") is not True:
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_settlement_plan_invalid",
                    details={
                        "operation": _deep_json_copy(plan.get("operation")),
                        "ok": _deep_json_copy(plan.get("ok")),
                    },
                )
            )
        plan_metadata = plan.get("metadata") if isinstance(plan.get("metadata"), Mapping) else {}
        plan_context = plan_metadata.get("summon_level_context")
        if (
            not isinstance(plan_context, Mapping)
            or _audit_level_context_identity(plan_context) != expected_context_identity
            or _audit_source_tree(plan_context.get("source_trace")) != expected_source_tree
        ):
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_settlement_context_mismatch",
                    details={
                        "plan_context": _deep_json_copy(plan_context),
                        "record": _deep_json_copy(context),
                    },
                )
            )
        plan_unit = _audit_plan_list_item(plan_metadata.get("unit_spawn_plans"), unit_id)
        if plan_unit is None:
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_settlement_unit_missing",
                    details={"unit_id": unit_id},
                )
            )
        else:
            plan_payload = plan_unit.get("unit") if isinstance(plan_unit.get("unit"), Mapping) else {}
            for key in (
                "unit_id",
                "template_id",
                "side",
                "level",
                "max_hp",
                "hp",
                "attack",
                "defense",
                "speed",
                "energy",
                "max_energy",
                "toughness",
                "max_toughness",
                "action_value",
            ):
                if not _audit_value_equal(plan_payload.get(key), after.get(key)):
                    violations.append(
                        _violation(
                            mutation,
                            f"summon_birth_settlement_unit_mismatch:{key}",
                            details={
                                "settlement": _deep_json_copy(plan_payload.get(key)),
                                "unit": _deep_json_copy(after.get(key)),
                            },
                        )
                    )
            plan_flags = (
                plan_payload.get("flags")
                if isinstance(plan_payload.get("flags"), Mapping)
                else {}
            )
            for key in (
                "summon_kind",
                "owner_id",
                "summoner_id",
                "summon_intent_id",
                "summon_entry_id",
                "combatant_profile_id",
                "stage_id",
                "hard_level_group",
            ):
                if not _audit_value_equal(plan_flags.get(key), flags.get(key)):
                    violations.append(
                        _violation(
                            mutation,
                            f"summon_birth_settlement_flag_mismatch:{key}",
                            details={
                                "settlement": _deep_json_copy(plan_flags.get(key)),
                                "unit": _deep_json_copy(flags.get(key)),
                            },
                        )
                    )
            plan_flag_context = plan_flags.get("summon_level_context")
            if (
                not isinstance(plan_flag_context, Mapping)
                or _audit_level_context_identity(plan_flag_context) != expected_context_identity
                or _audit_source_tree(plan_flag_context.get("source_trace")) != expected_source_tree
            ):
                violations.append(
                    _violation(
                        mutation,
                        "summon_birth_settlement_flag_context_mismatch",
                        details={"settlement_context": _deep_json_copy(plan_flag_context)},
                    )
                )
            plan_scaling = plan_flags.get("summon_stat_scaling")
            if (
                not isinstance(plan_scaling, Mapping)
                or _audit_scaling_summary_identity(plan_scaling) != expected_context_identity
                or _audit_source_tree(plan_scaling.get("source_trace")) != expected_source_tree
            ):
                violations.append(
                    _violation(
                        mutation,
                        "summon_birth_settlement_scaling_mismatch",
                        details={"settlement_scaling": _deep_json_copy(plan_scaling)},
                    )
                )
        plan_request = _audit_plan_list_item(plan_metadata.get("unit_spawn_requests"), unit_id)
        if plan_request is None:
            violations.append(
                _violation(
                    mutation,
                    "summon_birth_settlement_request_missing",
                    details={"unit_id": unit_id},
                )
            )
        else:
            plan_request_context = plan_request.get("level_context")
            if (
                not isinstance(plan_request_context, Mapping)
                or _audit_level_context_identity(plan_request_context) != expected_context_identity
                or _audit_source_tree(plan_request_context.get("source_trace")) != expected_source_tree
            ):
                violations.append(
                    _violation(
                        mutation,
                        "summon_birth_settlement_request_context_mismatch",
                        details={"request_level_context": _deep_json_copy(plan_request.get("level_context"))},
                    )
                )
            request_expectations = {
                "spawn_kind": "summoned_monster",
                "unit_id": unit_id,
                "owner_id": _first_str(flags.get("owner_id")),
                "summoner_id": _first_str(flags.get("summoner_id")),
                "source_id": intent.summon_intent_id,
                "entry_id": entry.entry_id,
                "birth_template_id": template.birth_template_id,
                "entity_ref": entry.monster_entity_ref,
                "entry_index": flags.get("summon_entry_index"),
                "copy_index": flags.get("summon_entry_copy_index"),
                "spawn_index": flags.get("summon_spawn_index"),
            }
            for key, expected in request_expectations.items():
                if not _audit_value_equal(plan_request.get(key), expected):
                    violations.append(
                        _violation(
                            mutation,
                            f"summon_birth_settlement_request_mismatch:{key}",
                            details={
                                "settlement": _deep_json_copy(plan_request.get(key)),
                                "expected": _deep_json_copy(expected),
                            },
                        )
                    )

    def _audit_servant_spawn_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> None:
        """A servant birth must resolve a formal ServantDefinitionIR and plan.

        The spawn kind alone is not evidence: the unit must carry an admitted
        servant definition identity, and the native settlement plan of this very
        mutation must agree with the born payload.
        """

        metadata = mutation.metadata
        after = mutation.after if isinstance(mutation.after, Mapping) else {}
        flags = after.get("flags") if isinstance(after.get("flags"), Mapping) else {}
        definition_id = _first_str(
            flags.get("servant_definition_id"),
            metadata.get("servant_definition_id"),
            metadata.get("intent_id"),
        )
        definition = self.rules.servant_definition(definition_id) if definition_id else None
        if definition is None or definition.coverage_status != "executable":
            violations.append(
                _violation(
                    mutation,
                    "servant_spawn_definition_missing_or_blocked",
                    details={"servant_definition_id": definition_id},
                )
            )
            return
        _audit_source(definition.source, definition.coverage_status, mutation, violations, executable_required=True)
        if (
            _first_str(flags.get("servant_ref")) != definition.servant_ref
            or after.get("template_id") != definition.servant_ref
            or _first_str(flags.get("summon_intent_id")) != definition.servant_definition_id
        ):
            violations.append(
                _violation(
                    mutation,
                    "servant_spawn_definition_identity_mismatch",
                    details={
                        "servant_definition_id": definition.servant_definition_id,
                        "servant_ref": definition.servant_ref,
                        "unit_servant_ref": _deep_json_copy(flags.get("servant_ref")),
                        "unit_template_id": _deep_json_copy(after.get("template_id")),
                        "unit_summon_intent_id": _deep_json_copy(flags.get("summon_intent_id")),
                    },
                )
            )
        unit_id = str(mutation.path[1])
        plan = _audit_summon_spawn_plan(records, mutation)
        if not isinstance(plan, Mapping):
            violations.append(
                _violation(
                    mutation,
                    "servant_spawn_settlement_plan_missing",
                    missing_field="summon_plan",
                )
            )
            return
        plan_unit_ids = plan.get("unit_ids")
        if not isinstance(plan_unit_ids, (list, tuple)) or unit_id not in plan_unit_ids:
            violations.append(
                _violation(
                    mutation,
                    "servant_spawn_settlement_plan_unit_ids_mismatch",
                    details={"unit_id": unit_id, "plan_unit_ids": _deep_json_copy(plan_unit_ids)},
                )
            )
        if plan.get("operation") != "servant_spawn" or plan.get("ok") is not True:
            violations.append(
                _violation(
                    mutation,
                    "servant_spawn_settlement_plan_invalid",
                    details={
                        "operation": _deep_json_copy(plan.get("operation")),
                        "ok": _deep_json_copy(plan.get("ok")),
                    },
                )
            )
        plan_metadata = plan.get("metadata") if isinstance(plan.get("metadata"), Mapping) else {}
        plan_unit = _audit_plan_list_item(plan_metadata.get("unit_spawn_plans"), unit_id)
        if plan_unit is None:
            violations.append(
                _violation(
                    mutation,
                    "servant_spawn_settlement_unit_missing",
                    details={"unit_id": unit_id},
                )
            )
        else:
            plan_payload = plan_unit.get("unit") if isinstance(plan_unit.get("unit"), Mapping) else {}
            for key in (
                "unit_id",
                "template_id",
                "side",
                "level",
                "max_hp",
                "hp",
                "attack",
                "defense",
                "speed",
                "energy",
                "max_energy",
                "max_toughness",
                "toughness",
                "action_value",
            ):
                if not _audit_value_equal(plan_payload.get(key), after.get(key)):
                    violations.append(
                        _violation(
                            mutation,
                            f"servant_spawn_settlement_unit_mismatch:{key}",
                            details={
                                "settlement": _deep_json_copy(plan_payload.get(key)),
                                "unit": _deep_json_copy(after.get(key)),
                            },
                        )
                    )
            plan_flags = plan_payload.get("flags") if isinstance(plan_payload.get("flags"), Mapping) else {}
            for key in (
                "summon_kind",
                "owner_id",
                "summoner_id",
                "servant_definition_id",
                "servant_ref",
                "summon_intent_id",
            ):
                if not _audit_value_equal(plan_flags.get(key), flags.get(key)):
                    violations.append(
                        _violation(
                            mutation,
                            f"servant_spawn_settlement_flag_mismatch:{key}",
                            details={
                                "settlement": _deep_json_copy(plan_flags.get(key)),
                                "unit": _deep_json_copy(flags.get(key)),
                            },
                        )
                    )
        plan_request = _audit_plan_list_item(plan_metadata.get("unit_spawn_requests"), unit_id)
        if plan_request is None:
            violations.append(
                _violation(
                    mutation,
                    "servant_spawn_settlement_request_missing",
                    details={"unit_id": unit_id},
                )
            )
        else:
            expectations = {
                "spawn_kind": "servant",
                "unit_id": unit_id,
                "owner_id": _first_str(flags.get("owner_id")),
                "summoner_id": _first_str(flags.get("summoner_id")),
                "source_id": definition.servant_definition_id,
                "entry_id": definition.servant_definition_id,
                "entity_ref": definition.servant_ref,
            }
            for key, expected in expectations.items():
                if not _audit_value_equal(plan_request.get(key), expected):
                    violations.append(
                        _violation(
                            mutation,
                            f"servant_spawn_settlement_request_mismatch:{key}",
                            details={
                                "settlement": _deep_json_copy(plan_request.get(key)),
                                "expected": _deep_json_copy(expected),
                            },
                        )
                    )

    def _audit_damage_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        _require_dict(mutation, metadata, "source_frame", violations)
        if metadata.get("damage_formula_family") == "elation":
            self._audit_elation_formula(mutation, violations)
            if metadata.get("status_damage_emission_id"):
                return self._audit_status_direct_damage_mutation(
                    mutation, records, violations, expected_family="elation",
                )
        if metadata.get("damage_formula_family") == "dot" and metadata.get("status_damage_emission_id"):
            return self._audit_status_dot_damage_mutation(mutation, records, violations)
        if metadata.get("damage_formula_family") == "true_damage" and metadata.get("status_damage_emission_id"):
            return self._audit_status_direct_damage_mutation(
                mutation,
                records,
                violations,
                expected_family="true_damage",
            )
        if metadata.get("damage_formula_family") == "additional" and metadata.get("status_damage_emission_id"):
            return self._audit_status_direct_damage_mutation(
                mutation,
                records,
                violations,
                expected_family="additional",
            )
        if metadata.get("damage_formula_family") == "break" and metadata.get("status_damage_emission_id"):
            return self._audit_status_callback_damage_mutation(mutation, records, violations)
        if metadata.get("damage_formula_family") == "break":
            return self._audit_break_damage_mutation(mutation, records, violations)
        if metadata.get("damage_formula_family") == "super_break":
            return self._audit_super_break_damage_mutation(mutation, records, violations)
        effect_id = _first_str(metadata.get("effect_id"))
        if effect_id and metadata.get("damage_formula_family") in {"hp_loss", "true_damage"}:
            self._audit_effect_id(mutation, effect_id, violations)
            if not isinstance(metadata.get("effect_source"), dict):
                violations.append(_violation(mutation, "effect_source_missing", missing_field="effect_source"))
            _require_dict(mutation, metadata, "source_trace", violations)
            evaluation = metadata.get("numeric_evaluation")
            if not isinstance(evaluation, dict):
                violations.append(_violation(mutation, "numeric_evaluation_missing", missing_field="numeric_evaluation"))
            elif evaluation.get("ok") is False:
                violations.append(_violation(mutation, "mutation_has_failed_numeric_evaluation", details={"numeric_evaluation": evaluation}))
            elif evaluation.get("ok") is True:
                _audit_dynamic_numeric_binding(mutation, evaluation, violations)
            return _trace(
                mutation,
                records,
                {
                    "effect_id": effect_id,
                    "opcode": str(metadata.get("opcode") or ""),
                    "damage_formula_family": str(metadata.get("damage_formula_family") or ""),
                },
            )
        emission_id = _required_str(mutation, metadata, "damage_emission_id", violations)
        task_id = _required_str(mutation, metadata, "source_task_id", violations)
        hit_profile_id = _required_str(mutation, metadata, "hit_profile_id", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        if emission_id:
            emission = self.rules.damage_emission(emission_id)
            if emission is None:
                violations.append(_violation(mutation, "damage_emission_missing", details={"damage_emission_id": emission_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                if task_id and emission.source_task_id != task_id:
                    violations.append(_violation(mutation, "damage_emission_task_mismatch", details={"expected": emission.source_task_id, "actual": task_id}))
                if hit_profile_id and emission.hit_profile_id != hit_profile_id:
                    violations.append(_violation(mutation, "damage_emission_hit_profile_mismatch", details={"expected": emission.hit_profile_id, "actual": hit_profile_id}))
        if task_id:
            task = self.rules.ability_task(task_id)
            if task is None:
                violations.append(_violation(mutation, "ability_task_missing", details={"source_task_id": task_id}))
            else:
                _audit_source(task.source, task.coverage_status, mutation, violations, check_status=False)
        if hit_profile_id:
            profile = self.rules.hit_profile(hit_profile_id)
            if profile is None:
                violations.append(_violation(mutation, "hit_profile_missing", details={"hit_profile_id": hit_profile_id}))
            else:
                _audit_source(profile.source, profile.coverage_status, mutation, violations, check_status=False)
        if metadata.get("damage_formula_family") == "direct":
            formula_result = metadata.get("formula_result")
            scaling = formula_result.get("scaling") if isinstance(formula_result, dict) else None
            basis_result = scaling.get("basis_result") if isinstance(scaling, dict) else None
            if not isinstance(basis_result, dict):
                violations.append(_violation(mutation, "scaling_basis_result_missing", missing_field="formula_result.scaling.basis_result"))
            elif basis_result.get("ok") is not True:
                violations.append(_violation(mutation, "scaling_basis_result_not_ok", details={"basis_result": basis_result}))
        return _trace(mutation, records, {"damage_emission_id": emission_id or "", "source_task_id": task_id or "", "hit_profile_id": hit_profile_id or ""})

    def _audit_elation_formula(
        self, mutation: Mutation, violations: list[SourceAuditViolation],
    ) -> None:
        formula = self.rules.formula("formula:elation_multiplier_rule")
        level_table = self.rules.formula("formula:elation_level_base")
        for definition in (formula, level_table):
            if definition is None:
                violations.append(_violation(mutation, "elation_formula_definition_missing"))
            else:
                _audit_source(definition.source, definition.coverage_status, mutation, violations,
                              executable_required=True)
        facts = mutation.metadata.get("elation_formula")
        if not isinstance(facts, dict):
            violations.append(_violation(mutation, "elation_formula_facts_missing"))
        elif level_table is not None and facts.get("level_formula_source") != level_table.source.to_json():
            violations.append(_violation(mutation, "elation_level_formula_source_mismatch"))

    def _audit_break_damage_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        emission_id = _required_str(mutation, metadata, "break_damage_emission_id", violations)
        template_id = _required_str(mutation, metadata, "break_template_id", violations)
        task_id = _required_str(mutation, metadata, "source_task_id", violations)
        break_base_source = metadata.get("break_base_damage_source")
        if not isinstance(break_base_source, dict):
            violations.append(_violation(mutation, "break_base_damage_source_missing", missing_field="break_base_damage_source"))
        else:
            level = break_base_source.get("level")
            if isinstance(level, int):
                base = self.rules.break_base_damage(level)
                if base is None:
                    violations.append(_violation(mutation, "break_base_damage_ir_missing", details={"level": level}))
                else:
                    _audit_source(base.source, base.coverage_status, mutation, violations, executable_required=True)
            else:
                violations.append(_violation(mutation, "break_base_damage_level_missing", missing_field="break_base_damage_source.level"))
        _require_dict(mutation, metadata, "source_trace", violations)
        evaluation = metadata.get("numeric_evaluation")
        if not isinstance(evaluation, dict):
            violations.append(_violation(mutation, "numeric_evaluation_missing", missing_field="numeric_evaluation"))
        elif evaluation.get("ok") is False:
            violations.append(_violation(mutation, "mutation_has_failed_numeric_evaluation", details={"numeric_evaluation": evaluation}))
        elif evaluation.get("ok") is True:
            _audit_dynamic_numeric_binding(mutation, evaluation, violations)
        if template_id:
            template = self.rules.break_template(template_id)
            if template is None:
                violations.append(_violation(mutation, "break_template_missing", details={"break_template_id": template_id}))
            else:
                _audit_source(template.source, template.coverage_status, mutation, violations, executable_required=True)
        if emission_id:
            emission = self.rules.break_damage_emission(emission_id)
            if emission is None:
                violations.append(_violation(mutation, "break_damage_emission_missing", details={"break_damage_emission_id": emission_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                if template_id and emission.template_id != template_id:
                    violations.append(_violation(mutation, "break_damage_template_mismatch", details={"expected": emission.template_id, "actual": template_id}))
                if task_id and emission.source_task_id != task_id:
                    violations.append(_violation(mutation, "break_damage_task_mismatch", details={"expected": emission.source_task_id, "actual": task_id}))
        return _trace(
            mutation,
            records,
            {
                "break_damage_emission_id": emission_id or "",
                "break_template_id": template_id or "",
                "source_task_id": task_id or "",
            },
        )

    def _audit_status_callback_damage_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        emission_id = _required_str(mutation, metadata, "status_damage_emission_id", violations)
        callback_id = _required_str(mutation, metadata, "status_callback_id", violations)
        task_id = _required_str(mutation, metadata, "source_task_id", violations)
        template_id = _required_str(mutation, metadata, "break_template_id", violations)
        _required_str(mutation, metadata, "status_instance_id", violations)
        _required_str(mutation, metadata, "modifier_name", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        source_emission = self.rules.status_damage_emission(emission_id) if emission_id else None
        if source_emission is not None:
            if metadata.get("base_includes_break_bonus") is not source_emission.base_includes_break_bonus:
                violations.append(_violation(mutation, "included_break_bonus_emission_mismatch"))
            if source_emission.base_includes_break_bonus:
                pipeline = metadata.get("damage_pipeline")
                stages = pipeline.get("stages") if isinstance(pipeline, dict) else None
                break_stage = next(
                    (stage for stage in stages if isinstance(stage, dict) and stage.get("stage") == "break_bonus"),
                    None,
                ) if isinstance(stages, list) else None
                if not isinstance(break_stage, dict) or break_stage.get("applicable") is not False:
                    violations.append(_violation(mutation, "included_break_bonus_stage_not_skipped"))
        if source_emission is None or source_emission.break_amount_mode != "value":
            break_base_source = metadata.get("break_base_damage_source")
            if not isinstance(break_base_source, dict):
                violations.append(_violation(mutation, "break_base_damage_source_missing", missing_field="break_base_damage_source"))
            else:
                level = break_base_source.get("level")
                if isinstance(level, int):
                    base = self.rules.break_base_damage(level)
                    if base is None:
                        violations.append(_violation(mutation, "break_base_damage_ir_missing", details={"level": level}))
                    else:
                        _audit_source(base.source, base.coverage_status, mutation, violations, executable_required=True)
                else:
                    violations.append(_violation(mutation, "break_base_damage_level_missing", missing_field="break_base_damage_source.level"))
        evaluation = metadata.get("numeric_evaluation")
        if not isinstance(evaluation, dict):
            violations.append(_violation(mutation, "numeric_evaluation_missing", missing_field="numeric_evaluation"))
        elif evaluation.get("ok") is False:
            violations.append(_violation(mutation, "mutation_has_failed_numeric_evaluation", details={"numeric_evaluation": evaluation}))
        elif evaluation.get("ok") is True:
            _audit_dynamic_numeric_binding(mutation, evaluation, violations)
        if template_id:
            template = self.rules.break_template(template_id)
            if template is None:
                violations.append(_violation(mutation, "break_template_missing", details={"break_template_id": template_id}))
            else:
                _audit_source(template.source, template.coverage_status, mutation, violations, executable_required=True)
        if callback_id:
            callback = self.rules.status_callback(callback_id)
            if callback is None:
                violations.append(_violation(mutation, "status_callback_missing", details={"status_callback_id": callback_id}))
            else:
                _audit_source(callback.source, callback.coverage_status, mutation, violations, executable_required=True)
        if task_id:
            task = self.rules.status_callback_task(task_id)
            if task is None:
                violations.append(_violation(mutation, "status_callback_task_missing", details={"source_task_id": task_id}))
            else:
                _audit_source(task.source, task.coverage_status, mutation, violations, executable_required=True)
                if callback_id and task.callback_id != callback_id:
                    violations.append(_violation(mutation, "status_callback_task_callback_mismatch", details={"expected": task.callback_id, "actual": callback_id}))
        if emission_id:
            emission = self.rules.status_damage_emission(emission_id)
            if emission is None:
                violations.append(_violation(mutation, "status_damage_emission_missing", details={"status_damage_emission_id": emission_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                if callback_id and emission.callback_id != callback_id:
                    violations.append(_violation(mutation, "status_damage_callback_mismatch", details={"expected": emission.callback_id, "actual": callback_id}))
                if task_id and emission.source_task_id != task_id:
                    violations.append(_violation(mutation, "status_damage_task_mismatch", details={"expected": emission.source_task_id, "actual": task_id}))
        return _trace(
            mutation,
            records,
            {
                "status_damage_emission_id": emission_id or "",
                "status_callback_id": callback_id or "",
                "source_task_id": task_id or "",
                "break_template_id": template_id or "",
            },
        )

    def _audit_status_dot_damage_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        emission_id = _required_str(mutation, metadata, "status_damage_emission_id", violations)
        callback_id = _required_str(mutation, metadata, "status_callback_id", violations)
        task_id = _required_str(mutation, metadata, "source_task_id", violations)
        _required_str(mutation, metadata, "status_instance_id", violations)
        _required_str(mutation, metadata, "modifier_name", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        evaluation = metadata.get("numeric_evaluation")
        if not isinstance(evaluation, dict):
            violations.append(_violation(mutation, "numeric_evaluation_missing", missing_field="numeric_evaluation"))
        elif evaluation.get("ok") is False:
            violations.append(_violation(mutation, "mutation_has_failed_numeric_evaluation", details={"numeric_evaluation": evaluation}))
        elif evaluation.get("ok") is True:
            _audit_dynamic_numeric_binding(mutation, evaluation, violations)
        dot_formula = metadata.get("dot_formula_result")
        if isinstance(dot_formula, dict):
            evaluations = dot_formula.get("numeric_evaluations")
            if isinstance(evaluations, dict):
                for key, nested in evaluations.items():
                    if isinstance(nested, dict) and nested.get("ok") is True:
                        _audit_dynamic_numeric_binding(mutation, nested, violations)
        if callback_id:
            callback = self.rules.status_callback(callback_id)
            if callback is None:
                violations.append(_violation(mutation, "status_callback_missing", details={"status_callback_id": callback_id}))
            else:
                _audit_source(callback.source, callback.coverage_status, mutation, violations, executable_required=True)
        if task_id:
            task = self.rules.status_callback_task(task_id)
            if task is None:
                violations.append(_violation(mutation, "status_callback_task_missing", details={"source_task_id": task_id}))
            else:
                _audit_source(task.source, task.coverage_status, mutation, violations, executable_required=True)
                if callback_id and task.callback_id != callback_id:
                    violations.append(_violation(mutation, "status_callback_task_callback_mismatch", details={"expected": task.callback_id, "actual": callback_id}))
        if emission_id:
            emission = self.rules.status_damage_emission(emission_id)
            if emission is None:
                violations.append(_violation(mutation, "status_damage_emission_missing", details={"status_damage_emission_id": emission_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                if emission.damage_formula_family != "dot":
                    violations.append(
                        _violation(
                            mutation,
                            "status_damage_family_mismatch",
                            details={"expected": "dot", "actual": emission.damage_formula_family},
                        )
                    )
                if callback_id and emission.callback_id != callback_id:
                    violations.append(_violation(mutation, "status_damage_callback_mismatch", details={"expected": emission.callback_id, "actual": callback_id}))
                if task_id and emission.source_task_id != task_id:
                    violations.append(_violation(mutation, "status_damage_task_mismatch", details={"expected": emission.source_task_id, "actual": task_id}))
        return _trace(
            mutation,
            records,
            {
                "status_damage_emission_id": emission_id or "",
                "status_callback_id": callback_id or "",
                "source_task_id": task_id or "",
                "damage_formula_family": "dot",
            },
        )

    def _audit_status_direct_damage_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
        *,
        expected_family: str,
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        emission_id = _required_str(mutation, metadata, "status_damage_emission_id", violations)
        callback_id = _required_str(mutation, metadata, "status_callback_id", violations)
        task_id = _required_str(mutation, metadata, "source_task_id", violations)
        _required_str(mutation, metadata, "status_instance_id", violations)
        _required_str(mutation, metadata, "modifier_name", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        evaluation = metadata.get("numeric_evaluation")
        if not isinstance(evaluation, dict):
            violations.append(_violation(mutation, "numeric_evaluation_missing", missing_field="numeric_evaluation"))
        elif evaluation.get("ok") is False:
            violations.append(_violation(mutation, "mutation_has_failed_numeric_evaluation", details={"numeric_evaluation": evaluation}))
        elif evaluation.get("ok") is True:
            _audit_dynamic_numeric_binding(mutation, evaluation, violations)
        if callback_id:
            callback = self.rules.status_callback(callback_id)
            if callback is None:
                violations.append(_violation(mutation, "status_callback_missing", details={"status_callback_id": callback_id}))
            else:
                _audit_source(callback.source, callback.coverage_status, mutation, violations, executable_required=True)
        if task_id:
            task = self.rules.status_callback_task(task_id)
            if task is None:
                violations.append(_violation(mutation, "status_callback_task_missing", details={"source_task_id": task_id}))
            else:
                _audit_source(task.source, task.coverage_status, mutation, violations, executable_required=True)
                if callback_id and task.callback_id != callback_id:
                    violations.append(_violation(mutation, "status_callback_task_callback_mismatch", details={"expected": task.callback_id, "actual": callback_id}))
        if emission_id:
            emission = self.rules.status_damage_emission(emission_id)
            if emission is None:
                violations.append(_violation(mutation, "status_damage_emission_missing", details={"status_damage_emission_id": emission_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                if emission.damage_formula_family != expected_family:
                    violations.append(
                        _violation(
                            mutation,
                            "status_damage_family_mismatch",
                            details={"expected": expected_family, "actual": emission.damage_formula_family},
                        )
                    )
                if callback_id and emission.callback_id != callback_id:
                    violations.append(_violation(mutation, "status_damage_callback_mismatch", details={"expected": emission.callback_id, "actual": callback_id}))
                if task_id and emission.source_task_id != task_id:
                    violations.append(_violation(mutation, "status_damage_task_mismatch", details={"expected": emission.source_task_id, "actual": task_id}))
        return _trace(
            mutation,
            records,
            {
                "status_damage_emission_id": emission_id or "",
                "status_callback_id": callback_id or "",
                "source_task_id": task_id or "",
                "damage_formula_family": expected_family,
            },
        )

    def _audit_super_break_damage_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        emission_id = _required_str(mutation, metadata, "super_break_emission_id", violations)
        task_id = _required_str(mutation, metadata, "source_task_id", violations)
        _required_str(mutation, metadata, "break_template_id", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        break_base_source = metadata.get("break_base_damage_source")
        if not isinstance(break_base_source, dict):
            violations.append(_violation(mutation, "break_base_damage_source_missing", missing_field="break_base_damage_source"))
        else:
            level = break_base_source.get("level")
            if isinstance(level, int):
                base = self.rules.break_base_damage(level)
                if base is None:
                    violations.append(_violation(mutation, "break_base_damage_ir_missing", details={"level": level}))
                else:
                    _audit_source(base.source, base.coverage_status, mutation, violations, executable_required=True)
            else:
                violations.append(_violation(mutation, "break_base_damage_level_missing", missing_field="break_base_damage_source.level"))
        evaluation = metadata.get("numeric_evaluation")
        if not isinstance(evaluation, dict):
            violations.append(_violation(mutation, "numeric_evaluation_missing", missing_field="numeric_evaluation"))
        elif evaluation.get("ok") is False:
            violations.append(_violation(mutation, "mutation_has_failed_numeric_evaluation", details={"numeric_evaluation": evaluation}))
        elif evaluation.get("ok") is True:
            _audit_dynamic_numeric_binding(mutation, evaluation, violations)
        if emission_id:
            emission = self.rules.super_break_emission(emission_id)
            if emission is None:
                violations.append(_violation(mutation, "super_break_emission_missing", details={"super_break_emission_id": emission_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                if task_id and emission.source_task_id != task_id:
                    violations.append(_violation(mutation, "super_break_task_mismatch", details={"expected": emission.source_task_id, "actual": task_id}))
        return _trace(
            mutation,
            records,
            {
                "super_break_emission_id": emission_id or "",
                "source_task_id": task_id or "",
            },
        )

    def _audit_toughness_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        emission_id = _required_str(mutation, metadata, "toughness_emission_id", violations)
        task_id = _required_str(mutation, metadata, "source_task_id", violations)
        hit_profile_id = _required_str(mutation, metadata, "hit_profile_id", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        evaluation = metadata.get("numeric_evaluation")
        if not isinstance(evaluation, dict):
            violations.append(_violation(mutation, "numeric_evaluation_missing", missing_field="numeric_evaluation"))
        elif evaluation.get("ok") is False:
            violations.append(_violation(mutation, "mutation_has_failed_numeric_evaluation", details={"numeric_evaluation": evaluation}))
        elif evaluation.get("ok") is True:
            _audit_dynamic_numeric_binding(mutation, evaluation, violations)
        if emission_id:
            emission = self.rules.toughness_emission(emission_id)
            if emission is None:
                violations.append(_violation(mutation, "toughness_emission_missing", details={"toughness_emission_id": emission_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                if task_id and emission.source_task_id != task_id:
                    violations.append(_violation(mutation, "toughness_emission_task_mismatch", details={"expected": emission.source_task_id, "actual": task_id}))
                if hit_profile_id and emission.hit_profile_id != hit_profile_id:
                    violations.append(_violation(mutation, "toughness_emission_hit_profile_mismatch", details={"expected": emission.hit_profile_id, "actual": hit_profile_id}))
        if task_id:
            task = self.rules.ability_task(task_id)
            if task is None:
                violations.append(_violation(mutation, "ability_task_missing", details={"source_task_id": task_id}))
            else:
                _audit_source(task.source, task.coverage_status, mutation, violations, check_status=False)
        if hit_profile_id:
            profile = self.rules.hit_profile(hit_profile_id)
            if profile is None:
                violations.append(_violation(mutation, "hit_profile_missing", details={"hit_profile_id": hit_profile_id}))
            else:
                _audit_source(profile.source, profile.coverage_status, mutation, violations, check_status=False)
        return _trace(
            mutation,
            records,
            {
                "toughness_emission_id": emission_id or "",
                "source_task_id": task_id or "",
                "hit_profile_id": hit_profile_id or "",
            },
        )

    def _audit_break_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
        *,
        ordinary_recovery: bool = False,
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        if isinstance(metadata.get("break_recovery"), dict) and not ordinary_recovery:
            return self._audit_break_recovery_mutation(mutation, records, violations)
        template_id = _required_str(mutation, metadata, "break_template_id", violations)
        emission_id = _required_str(mutation, metadata, "toughness_emission_id", violations)
        task_id = _required_str(mutation, metadata, "source_task_id", violations)
        hit_profile_id = _required_str(mutation, metadata, "hit_profile_id", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        _require_dict(mutation, metadata, "break_lifecycle", violations)
        if template_id:
            template = self.rules.break_template(template_id)
            if template is None:
                violations.append(_violation(mutation, "break_template_missing", details={"break_template_id": template_id}))
            else:
                _audit_source(template.source, template.coverage_status, mutation, violations, executable_required=True)
        if emission_id:
            emission = self.rules.toughness_emission(emission_id)
            if emission is None:
                violations.append(_violation(mutation, "toughness_emission_missing", details={"toughness_emission_id": emission_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                if task_id and emission.source_task_id != task_id:
                    violations.append(_violation(mutation, "toughness_emission_task_mismatch", details={"expected": emission.source_task_id, "actual": task_id}))
                if hit_profile_id and emission.hit_profile_id != hit_profile_id:
                    violations.append(_violation(mutation, "toughness_emission_hit_profile_mismatch", details={"expected": emission.hit_profile_id, "actual": hit_profile_id}))
        if task_id:
            task = self.rules.ability_task(task_id)
            if task is None:
                violations.append(_violation(mutation, "ability_task_missing", details={"source_task_id": task_id}))
            else:
                _audit_source(task.source, task.coverage_status, mutation, violations, check_status=False)
        if hit_profile_id:
            profile = self.rules.hit_profile(hit_profile_id)
            if profile is None:
                violations.append(_violation(mutation, "hit_profile_missing", details={"hit_profile_id": hit_profile_id}))
            else:
                _audit_source(profile.source, profile.coverage_status, mutation, violations, check_status=False)
        return _trace(
            mutation,
            records,
            {
                "toughness_emission_id": emission_id or "",
                "break_template_id": template_id or "",
                "source_task_id": task_id or "",
                "hit_profile_id": hit_profile_id or "",
                "break_lifecycle": metadata.get("break_lifecycle") if isinstance(metadata.get("break_lifecycle"), dict) else {},
            },
        )

    def _audit_break_recovery_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        recovery = metadata.get("break_recovery")
        if not isinstance(recovery, dict):
            violations.append(_violation(mutation, "break_recovery_missing", missing_field="break_recovery"))
            return _trace(mutation, records, {})
        if recovery.get("kind") == "ordinary_before_action":
            _required_str(mutation, recovery, "trigger_kind", violations)
            return self._audit_break_mutation(
                mutation, records, violations, ordinary_recovery=True,
            )
        emission_id = _required_str(mutation, recovery, "break_status_emission_id", violations)
        _required_str(mutation, recovery, "status_instance_id", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        if emission_id:
            emission = self.rules.break_status_emission(emission_id)
            if emission is None:
                violations.append(_violation(mutation, "break_status_emission_missing", details={"break_status_emission_id": emission_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                effect = self.rules.effect(emission.effect_id)
                if effect is None:
                    violations.append(_violation(mutation, "effect_ir_missing", details={"effect_id": emission.effect_id}))
                else:
                    _audit_source(effect.source, effect.coverage_status, mutation, violations, executable_required=True)
        return _trace(
            mutation,
            records,
            {
                "break_status_emission_id": emission_id or "",
                "break_recovery": recovery,
            },
        )

    def _audit_status_callback_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        if metadata.get("ordinary_reset_stance") is True:
            callback = self.rules.status_callback(str(metadata.get("callback_id") or ""))
            task = self.rules.status_callback_task(str(metadata.get("task_id") or ""))
            trace = metadata.get("source_trace")
            trace = trace if isinstance(trace, dict) else {}
            card = self.rules.monster_data_card(str(trace.get("monster_data_card_id") or ""))
            template_config = card.raw_parameter_blocks.get("template_config") if card is not None else None
            break_source = trace.get("break_source")
            break_source = break_source if isinstance(break_source, dict) else {}
            template = self.rules.break_template(str(break_source.get("break_template_id") or ""))
            if callback is None or task is None or card is None or template is None:
                violations.append(_violation(mutation, "ordinary_stance_reset_source_missing"))
            else:
                _audit_source(callback.source, callback.coverage_status, mutation, violations, executable_required=True)
                _audit_source(task.source, task.coverage_status, mutation, violations, executable_required=True)
                _audit_source(card.source, card.coverage_status, mutation, violations, check_status=False)
                _audit_source(template.source, template.coverage_status, mutation, violations, executable_required=True)
                maximum_segments = template_config.get("stance_count") if isinstance(template_config, dict) else None
                count_reset = task.opcode == "SetStanceCount"
                expected_path = (("units", metadata.get("target_id"), "flags", "stance_segments_remaining")
                                 if count_reset else ("units", metadata.get("target_id"), "toughness"))
                expected_after = maximum_segments if count_reset else metadata.get("max_toughness")
                expected_record = "ordinary_stance_count_reset" if count_reset else "ordinary_stance_reset"
                if (task.callback_id != callback.callback_id or task.opcode not in {"ResetStance", "SetStanceCount"}
                        or callback.event != "OnDestroy"
                        or task.task_payload.get("TargetType") != "ModifierOwnerEntity"
                        or type(maximum_segments) is not int or maximum_segments <= 0
                        or metadata.get("monster_stance_count") != maximum_segments
                        or count_reset and maximum_segments <= 1
                        or mutation.path != expected_path
                        or mutation.before != 0 or mutation.after != expected_after
                        or not any(record.get("record_type") == expected_record
                                   and record.get("mutation_id") == mutation.stable_id() for record in records)):
                    violations.append(_violation(mutation, "ordinary_stance_reset_contract_mismatch"))
            return _trace(mutation, records, {"callback_id": metadata.get("callback_id"), "task_id": metadata.get("task_id")})
        if metadata.get("dynamic_key") or metadata.get("property"):
            return self._audit_status_callback_dynamic_value_mutation(mutation, records, violations)
        if any(
            record.get("record_type") == "status_stack_property"
            and record.get("mutation_id") == mutation.stable_id()
            for record in records
        ):
            return self._audit_status_stack_property_mutation(mutation, records, violations)
        callback_id = _required_str(mutation, metadata, "callback_id", violations)
        task_id = _required_str(mutation, metadata, "task_id", violations)
        is_current_skill_delay_cost = mutation.path == (
            "global_flags",
            "turn_action_delay_cost_modifiers",
        )
        delay_id = (
            None
            if is_current_skill_delay_cost
            else _required_str(
                mutation,
                metadata,
                "action_delay_emission_id",
                violations,
            )
        )
        _require_dict(mutation, metadata, "source_trace", violations)
        evaluation = metadata.get("numeric_evaluation")
        if not isinstance(evaluation, dict):
            violations.append(_violation(mutation, "numeric_evaluation_missing", missing_field="numeric_evaluation"))
        elif evaluation.get("ok") is False:
            violations.append(_violation(mutation, "mutation_has_failed_numeric_evaluation", details={"numeric_evaluation": evaluation}))
        elif evaluation.get("ok") is True:
            _audit_dynamic_numeric_binding(mutation, evaluation, violations)
        if callback_id:
            callback = self.rules.status_callback(callback_id)
            if callback is None:
                violations.append(_violation(mutation, "status_callback_missing", details={"callback_id": callback_id}))
            else:
                _audit_source(callback.source, callback.coverage_status, mutation, violations, executable_required=True)
        if task_id:
            task = self.rules.status_callback_task(task_id)
            if task is None:
                violations.append(_violation(mutation, "status_callback_task_missing", details={"task_id": task_id}))
            else:
                _audit_source(task.source, task.coverage_status, mutation, violations, executable_required=True)
                if callback_id and task.callback_id != callback_id:
                    violations.append(_violation(mutation, "status_callback_task_callback_mismatch", details={"expected": task.callback_id, "actual": callback_id}))
                if is_current_skill_delay_cost and task.opcode != "ModifyCurrentSkillDelayCost":
                    violations.append(
                        _violation(
                            mutation,
                            "current_skill_delay_cost_task_opcode_mismatch",
                            details={"actual": task.opcode},
                        )
                    )
        if delay_id:
            emission = self.rules.action_delay_emission(delay_id)
            if emission is None:
                violations.append(_violation(mutation, "action_delay_emission_missing", details={"action_delay_emission_id": delay_id}))
            else:
                _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
                if callback_id and emission.callback_id != callback_id:
                    violations.append(_violation(mutation, "action_delay_callback_mismatch", details={"expected": emission.callback_id, "actual": callback_id}))
                if task_id and emission.source_task_id != task_id:
                    violations.append(_violation(mutation, "action_delay_task_mismatch", details={"expected": emission.source_task_id, "actual": task_id}))
        return _trace(
            mutation,
            records,
            {
                "callback_id": callback_id or "",
                "task_id": task_id or "",
                "action_delay_emission_id": delay_id or "",
            },
        )

    def _audit_status_callback_dynamic_value_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        callback_id = _required_str(mutation, metadata, "callback_id", violations)
        task_id = _required_str(mutation, metadata, "task_id", violations)
        _required_str(mutation, metadata, "dynamic_key", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        if callback_id:
            callback = self.rules.status_callback(callback_id)
            if callback is None:
                violations.append(_violation(mutation, "status_callback_missing", details={"callback_id": callback_id}))
            else:
                _audit_source(callback.source, callback.coverage_status, mutation, violations, executable_required=True)
        if task_id:
            task = self.rules.status_callback_task(task_id)
            if task is None:
                violations.append(_violation(mutation, "status_callback_task_missing", details={"task_id": task_id}))
            else:
                _audit_source(task.source, task.coverage_status, mutation, violations, executable_required=True)
                if callback_id and task.callback_id != callback_id:
                    violations.append(_violation(mutation, "status_callback_task_callback_mismatch", details={"expected": task.callback_id, "actual": callback_id}))
        for alias in metadata.get("dynamic_hash_aliases", ()):
            if not isinstance(alias, dict):
                continue
            alias_task_id = _first_str(alias.get("source_task_id"))
            if not alias_task_id:
                continue
            task = self.rules.status_callback_task(alias_task_id)
            if task is None:
                violations.append(_violation(mutation, "dynamic_hash_alias_task_missing", details={"source_task_id": alias_task_id}))
            else:
                _audit_source(task.source, task.coverage_status, mutation, violations, executable_required=True)
        return _trace(
            mutation,
            records,
            {
                "callback_id": callback_id or "",
                "task_id": task_id or "",
                "dynamic_key": str(metadata.get("dynamic_key") or ""),
                "property": str(metadata.get("property") or ""),
            },
        )

    def _audit_status_stack_property_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        callback_id = _required_str(mutation, metadata, "callback_id", violations)
        task_id = _required_str(mutation, metadata, "task_id", violations)
        instance_id = _required_str(mutation, metadata, "status_instance_id", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        evaluation = metadata.get("numeric_evaluation")
        value = (
            evaluation.get("value")
            if isinstance(evaluation, dict) and evaluation.get("ok") is True
            else None
        )
        if (
            type(value) not in (int, float)
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            violations.append(
                _violation(mutation, "status_stack_property_numeric_evaluation_invalid")
            )
            value = None
        callback = self.rules.status_callback(callback_id) if callback_id else None
        if callback is None:
            violations.append(
                _violation(mutation, "status_callback_missing",
                           details={"callback_id": callback_id})
            )
        else:
            _audit_source(callback.source, callback.coverage_status, mutation,
                          violations, executable_required=True)
        task = self.rules.status_callback_task(task_id) if task_id else None
        property_name = ""
        if task is None:
            violations.append(
                _violation(mutation, "status_callback_task_missing",
                           details={"task_id": task_id})
            )
        else:
            _audit_source(task.source, task.coverage_status, mutation,
                          violations, executable_required=True)
            property_name = str(task.task_payload.get("Property") or "")
            if (
                task.callback_id != callback_id
                or task.opcode != "StackProperty"
                or not property_name
            ):
                violations.append(
                    _violation(mutation, "status_stack_property_task_contract_mismatch",
                               details={"callback_id": callback_id, "task_id": task_id})
                )
        from ..systems.status import _map_stack_property

        property_mapping = _map_stack_property(property_name) if property_name else None
        target_id = str(mutation.path[1]) if len(mutation.path) > 1 else ""
        after_details = mutation.after if isinstance(mutation.after, list) else []
        before_details = mutation.before if isinstance(mutation.before, list) else []
        after_matches = [
            item for item in after_details
            if isinstance(item, dict) and item.get("instance_id") == instance_id
        ]
        before_matches = [
            item for item in before_details
            if isinstance(item, dict) and item.get("instance_id") == instance_id
        ]
        expected_before_value: JSONValue = None
        if (
            mutation.op != "set"
            or mutation.path != ("units", target_id, "flags", "status_details")
            or len(after_matches) != 1
            or len(before_matches) != 1
        ):
            violations.append(
                _violation(mutation, "status_stack_property_mutation_path_invalid",
                           details={"path": list(mutation.path),
                                    "instance_id": instance_id})
            )
        else:
            after = after_matches[0]
            before = before_matches[0]
            installed = [
                item for item in after.get("modifiers", ())
                if isinstance(item, dict) and item.get("producer_task_id") == task_id
            ]
            identity_ok = (
                task is not None
                and value is not None
                and len(installed) == 1
                and installed[0].get("property") == property_name
                and installed[0].get("value") == value
                and installed[0].get("producer_task_path") == task.task_path
                and installed[0].get("applied_reason") == "status_stack_property"
            )
            non_modifier_unchanged = (
                {key: item for key, item in after.items() if key != "modifiers"}
                == {key: item for key, item in before.items() if key != "modifiers"}
            )
            sibling_unchanged = (
                len(after_details) == len(before_details)
                and all(
                    after_detail == before_detail
                    for before_detail, after_detail in zip(before_details, after_details)
                    if not (
                        isinstance(before_detail, dict)
                        and before_detail.get("instance_id") == instance_id
                    )
                )
            )
            if not sibling_unchanged:
                violations.append(
                    _violation(mutation, "status_stack_property_sibling_instance_changed")
                )
            if (
                value is None
                or not identity_ok
                or not non_modifier_unchanged
                or not sibling_unchanged
            ):
                violations.append(
                    _violation(mutation, "status_stack_property_settlement_mismatch")
                )
            else:
                entry = installed[0]
                raw_path = entry.get("raw_path")
                before_modifiers = list(before.get("modifiers", ()))
                after_modifiers = list(after.get("modifiers", ()))
                before_entries = [
                    item for item in before_modifiers
                    if isinstance(item, dict)
                    and item.get("raw_path") == raw_path
                    and item.get("property") == property_name
                ] if isinstance(raw_path, str) and raw_path else []
                if (
                    not isinstance(raw_path, str)
                    or not raw_path
                    or len(before_entries) > 1
                ):
                    violations.append(
                        _violation(mutation, "status_stack_property_entry_identity_invalid")
                    )
                elif before_entries:
                    # Formal _runtime_modifiers entries carry raw_path only and
                    # may still be delayed (value None + value_mode /
                    # deferred_dynamic_hashes). The evaluated shape must be the
                    # ordinary applied entry with the producer identity.
                    before_entry = before_entries[0]
                    expected_before_value = before_entry.get("value")
                    excluded = {
                        "value",
                        "applied_reason",
                        "value_mode",
                        "deferred_dynamic_hashes",
                        "producer_task_id",
                        "producer_task_path",
                    }
                    unchanged_before = {
                        key: item for key, item in before_entry.items()
                        if key not in excluded
                    }
                    unchanged_after = {
                        key: item for key, item in entry.items()
                        if key not in excluded
                    }
                    dropped = set(before_entry) - set(entry)
                    added = set(entry) - set(before_entry)
                    before_others = [
                        item for item in before_modifiers if item != before_entry
                    ]
                    after_others = [
                        item for item in after_modifiers if item != entry
                    ]
                    if (
                        unchanged_before != unchanged_after
                        or entry.get("value") != value
                        or entry.get("applied_reason") != "status_stack_property"
                        or entry.get("producer_task_id") != task_id
                        or entry.get("producer_task_path") != task.task_path
                        or property_mapping is None
                        or entry.get("bucket") != property_mapping[0]
                        or entry.get("key") != property_mapping[1]
                        or entry.get("scope") != property_mapping[2]
                        or "value_mode" in entry
                        or "deferred_dynamic_hashes" in entry
                        or not dropped <= {"value_mode", "deferred_dynamic_hashes"}
                        or not added <= {"producer_task_id", "producer_task_path"}
                        or before_others != after_others
                    ):
                        violations.append(
                            _violation(mutation, "status_stack_property_settlement_mismatch")
                        )
                elif (
                    property_mapping is None
                    or set(entry) != {
                        "bucket",
                        "key",
                        "scope",
                        "value",
                        "property",
                        "producer_task_id",
                        "producer_task_path",
                        "raw_path",
                        "applied_reason",
                    }
                    or entry.get("bucket") != property_mapping[0]
                    or entry.get("key") != property_mapping[1]
                    or entry.get("scope") != property_mapping[2]
                    or entry.get("raw_path") != task.task_path
                    or entry.get("value") != value
                    or after_modifiers != [*before_modifiers, entry]
                ):
                    # First authoritative write appends exactly one complete
                    # applied entry mapped from the formal Property, with no
                    # delayed marker left behind.
                    violations.append(
                        _violation(mutation, "status_stack_property_settlement_mismatch")
                    )
        matching_records = tuple(
            record
            for record in records
            if record.get("record_type") == "status_stack_property"
            and record.get("source") == "status_callback_system"
            and record.get("mutation_id") == mutation.stable_id()
            and isinstance(record.get("payload"), dict)
            and record["payload"].get("status_instance_id") == instance_id
            and record["payload"].get("property") == property_name
            and record["payload"].get("before") == expected_before_value
            and record["payload"].get("after") == value
        )
        if not matching_records:
            violations.append(
                _violation(mutation, "status_stack_property_record_missing")
            )
        return _trace(
            mutation,
            records,
            {
                "callback_id": callback_id or "",
                "task_id": task_id or "",
                "status_instance_id": instance_id or "",
                "property": property_name,
            },
        )

    def _audit_ability_property_watcher_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        unit_id = _required_str(mutation, metadata, "unit_id", violations)
        instance_id = _required_str(
            mutation,
            metadata,
            "status_instance_id",
            violations,
        )
        trigger_event_id = _required_str(
            mutation,
            metadata,
            "trigger_event_id",
            violations,
        )
        watcher_ids = metadata.get("watcher_ids")
        watcher_state = metadata.get("watcher_state")
        source_trace = metadata.get("source_trace")
        _require_dict(mutation, metadata, "source_trace", violations)
        expected_path = (
            "units",
            unit_id,
            "flags",
            "status_details",
        ) if unit_id else ()
        if expected_path and mutation.path != expected_path:
            violations.append(
                _violation(
                    mutation,
                    "ability_property_watcher_path_invalid",
                    details={
                        "expected": list(expected_path),
                        "actual": list(mutation.path),
                    },
                )
            )
        if (
            not isinstance(watcher_ids, (list, tuple))
            or not watcher_ids
            or any(
                not isinstance(watcher_id, str) or not watcher_id
                for watcher_id in watcher_ids
            )
            or tuple(watcher_ids) != tuple(sorted(set(watcher_ids)))
        ):
            violations.append(
                _violation(
                    mutation,
                    "ability_property_watcher_ids_invalid",
                    missing_field="watcher_ids",
                )
            )
            watcher_ids = ()
        if (
            not isinstance(watcher_state, dict)
            or set(watcher_state) != set(watcher_ids)
        ):
            violations.append(
                _violation(
                    mutation,
                    "ability_property_watcher_state_invalid",
                    missing_field="watcher_state",
                )
            )
            watcher_state = {}

        watcher_sources: list[dict[str, JSONValue]] = []
        for watcher_id in watcher_ids:
            watcher = self.rules.ability_property_watcher(watcher_id)
            active_range_ids = watcher_state.get(watcher_id)
            if watcher is None:
                violations.append(
                    _violation(
                        mutation,
                        "ability_property_watcher_missing",
                        details={"watcher_id": watcher_id},
                    )
                )
                continue
            _audit_source(
                watcher.source,
                watcher.coverage_status,
                mutation,
                violations,
                executable_required=True,
            )
            watcher_sources.append(watcher.source.to_json())
            if (
                not isinstance(active_range_ids, (list, tuple))
                or any(
                    not isinstance(range_id, str) or not range_id
                    for range_id in active_range_ids
                )
            ):
                violations.append(
                    _violation(
                        mutation,
                        "ability_property_watcher_active_ranges_invalid",
                        details={"watcher_id": watcher_id},
                    )
                )
                continue
            active_range_id_set = set(active_range_ids)
            if (
                len(active_range_ids) != len(active_range_id_set)
                or tuple(active_range_ids)
                != tuple(
                    range_id
                    for range_id in watcher.range_ids
                    if range_id in active_range_id_set
                )
            ):
                violations.append(
                    _violation(
                        mutation,
                        "ability_property_watcher_active_ranges_invalid",
                        details={"watcher_id": watcher_id},
                    )
                )

        expected_source_trace = {
            "watcher_sources": watcher_sources,
        }
        if source_trace != expected_source_trace:
            violations.append(
                _violation(
                    mutation,
                    "ability_property_watcher_source_trace_mismatch",
                    details={
                        "expected": expected_source_trace,
                        "actual": (
                            source_trace
                            if isinstance(source_trace, dict)
                            else {}
                        ),
                    },
                )
            )

        matching_records = tuple(
            record
            for record in records
            if record.get("record_type") == "ability_property_watcher_state"
            and record.get("source") == "ability_property_watcher_system"
            and isinstance(record.get("payload"), dict)
            and record["payload"].get("unit_id") == unit_id
            and record["payload"].get("status_instance_id") == instance_id
            and record["payload"].get("watcher_ids") == list(watcher_ids)
            and record["payload"].get("watcher_state") == watcher_state
            and isinstance(record.get("trace"), dict)
            and record["trace"].get("trigger_event_id") == trigger_event_id
            and record["trace"].get("watcher_sources") == watcher_sources
        )
        if not matching_records:
            violations.append(
                _violation(
                    mutation,
                    "ability_property_watcher_settlement_mismatch",
                )
            )
        return _trace(
            mutation,
            records,
            {
                "unit_id": unit_id or "",
                "status_instance_id": instance_id or "",
                "trigger_event_id": trigger_event_id or "",
                "watcher_ids": list(watcher_ids),
            },
        )

    def _audit_status_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        lifecycle = metadata.get("lifecycle_plan")
        if not isinstance(lifecycle, dict):
            violations.append(_violation(mutation, "status_lifecycle_result_missing", missing_field="lifecycle_plan"))
            return _trace(mutation, records, {})
        source_trace = lifecycle.get("source_trace")
        if not isinstance(source_trace, dict):
            violations.append(_violation(mutation, "status_lifecycle_source_trace_missing", missing_field="lifecycle_plan.source_trace"))
            return _trace(mutation, records, {"lifecycle_plan": lifecycle})
        effect_id = _first_str(source_trace.get("effect_id"), source_trace.get("effect"))
        if not effect_id:
            violations.append(_violation(mutation, "status_effect_id_missing", missing_field="lifecycle_plan.source_trace.effect_id"))
        else:
            self._audit_effect_id(mutation, effect_id, violations)
            self._audit_break_status_source(mutation, effect_id, source_trace, violations)
        modifier_name = _first_str(source_trace.get("modifier_name"), lifecycle.get("modifier_name"))
        if modifier_name and self.rules.modifier_definition(modifier_name) is None:
            violations.append(_violation(mutation, "modifier_definition_missing", details={"modifier_name": modifier_name}))
        if lifecycle.get("operation") in {"tick", "expire"}:
            duration_admission = source_trace.get("duration_admission")
            if not isinstance(duration_admission, dict):
                violations.append(
                    _violation(
                        mutation,
                        "status_duration_admission_missing",
                        missing_field="lifecycle_plan.source_trace.duration_admission",
                    )
                )
            elif duration_admission.get("admission_status") != "executable":
                violations.append(
                    _violation(
                        mutation,
                        "status_duration_admission_not_executable",
                        details={"duration_admission": duration_admission},
                    )
                )
        if mutation.path == ("global_flags", "dynamic_value_store"):
            self._audit_status_dynamic_value_cleanup(
                mutation,
                records,
                violations,
                lifecycle,
            )
        return _trace(mutation, records, {"effect_id": effect_id or "", "modifier_name": modifier_name or "", "lifecycle_plan": lifecycle})

    def _audit_status_dynamic_value_cleanup(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
        lifecycle: dict[str, JSONValue],
    ) -> None:
        """Audit the exact diff of a status-lifecycle dynamic value cleanup.

        The mutation replaces the whole store, so the lifecycle source alone is
        not enough: the after store must be exactly the before store with the
        removed instance's ``status`` scoped entries (and their operation
        ledger rows) dropped. Otherwise a legitimate removal source could carry
        unrelated value/index changes into the global store.
        """
        from ..systems.dynamic_values import (
            normalized_dynamic_value_store,
            remove_status_instance_entries,
        )

        metadata = mutation.metadata
        instance_id = metadata.get("status_instance_id")
        existing = lifecycle.get("existing_detail")
        existing_instance = (
            existing.get("instance_id") if isinstance(existing, dict) else None
        )
        if (
            not isinstance(instance_id, str)
            or not instance_id
            or instance_id != existing_instance
        ):
            violations.append(
                _violation(
                    mutation,
                    "status_dynamic_value_cleanup_instance_mismatch",
                    details={
                        "status_instance_id": instance_id,
                        "lifecycle_instance_id": existing_instance,
                    },
                )
            )
            return
        if mutation.op != "set" or not mutation.before_exists:
            violations.append(
                _violation(
                    mutation,
                    "status_dynamic_value_cleanup_operation_invalid",
                    details={"op": mutation.op, "before_exists": mutation.before_exists},
                )
            )
            return
        if not isinstance(mutation.before, dict) or not isinstance(mutation.after, dict):
            violations.append(
                _violation(
                    mutation,
                    "status_dynamic_value_cleanup_store_missing",
                    details={"before_type": type(mutation.before).__name__,
                             "after_type": type(mutation.after).__name__},
                )
            )
            return
        try:
            before = normalized_dynamic_value_store(mutation.before)
            after = normalized_dynamic_value_store(mutation.after)
        except (TypeError, ValueError) as exc:
            violations.append(
                _violation(
                    mutation,
                    "status_dynamic_value_cleanup_store_invalid",
                    details={"error": str(exc)},
                )
            )
            return
        expected = remove_status_instance_entries(before, instance_id)
        if expected is None or expected != after:
            violations.append(
                _violation(
                    mutation,
                    "status_dynamic_value_cleanup_diff_mismatch",
                    details={
                        "status_instance_id": instance_id,
                        "before_entry_count": len(before["entries"]),
                        "after_entry_count": len(after["entries"]),
                    },
                )
            )
            return
        removed_entry_count = len(before["entries"]) - len(after["entries"])
        cleanup_records = [
            record
            for record in records
            if isinstance(record, dict)
            and record.get("record_type") == "status_dynamic_value_cleanup"
        ]
        if len(cleanup_records) != 1:
            violations.append(
                _violation(
                    mutation,
                    "status_dynamic_value_cleanup_record_mismatch",
                    details={"record_count": len(cleanup_records)},
                )
            )
            return
        record = cleanup_records[0]
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if (
            record.get("source") != "status_system"
            or payload.get("status_instance_id") != instance_id
            or payload.get("operation") != lifecycle.get("operation")
            or payload.get("removed_entry_count") != removed_entry_count
            or removed_entry_count <= 0
        ):
            violations.append(
                _violation(
                    mutation,
                    "status_dynamic_value_cleanup_record_mismatch",
                    details={
                        "record_source": record.get("source"),
                        "payload": payload,
                        "removed_entry_count": removed_entry_count,
                    },
                )
            )

    def _audit_break_status_source(
        self,
        mutation: Mutation,
        effect_id: str,
        source_trace: dict[str, JSONValue],
        violations: list[SourceAuditViolation],
    ) -> None:
        effect_source = source_trace.get("effect_source")
        if not isinstance(effect_source, dict):
            return
        evidence = effect_source.get("evidence")
        if not isinstance(evidence, dict):
            return
        emission_id = _first_str(evidence.get("break_status_emission_id"))
        if not emission_id:
            return
        emission = self.rules.break_status_emission(emission_id)
        if emission is None:
            violations.append(_violation(mutation, "break_status_emission_missing", details={"break_status_emission_id": emission_id}))
            return
        _audit_source(emission.source, emission.coverage_status, mutation, violations, executable_required=True)
        if emission.effect_id != effect_id:
            violations.append(
                _violation(
                    mutation,
                    "break_status_emission_effect_mismatch",
                    details={"expected": emission.effect_id, "actual": effect_id},
                )
            )

    def _audit_effect_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        effect_id = _required_str(mutation, metadata, "effect_id", violations)
        if effect_id:
            self._audit_effect_id(mutation, effect_id, violations)
        if not isinstance(metadata.get("effect_source"), dict):
            violations.append(_violation(mutation, "effect_source_missing", missing_field="effect_source"))
        evaluation = metadata.get("numeric_evaluation")
        evaluations = metadata.get("numeric_evaluations")
        if isinstance(evaluation, dict) and evaluation.get("ok") is False:
            violations.append(_violation(mutation, "mutation_has_failed_numeric_evaluation", details={"numeric_evaluation": evaluation}))
        if isinstance(evaluation, dict) and evaluation.get("ok") is True:
            _audit_dynamic_numeric_binding(mutation, evaluation, violations)
        if isinstance(evaluations, dict):
            failed = {
                str(key): value
                for key, value in evaluations.items()
                if isinstance(value, dict) and value.get("ok") is False
            }
            ok_values = {
                str(key): value
                for key, value in evaluations.items()
                if isinstance(value, dict) and value.get("ok") is True
            }
            standard = metadata.get("standard")
            has_fixed_mechanism_state = (
                metadata.get("opcode") in {"SetEnergyBarState", "SetMonsterEnergyBarState", "SetSummonerEnergyBarState"}
                and isinstance(standard, dict)
                and (standard.get("state") is not None or standard.get("active") is not None)
            )
            if failed and not ok_values and not has_fixed_mechanism_state:
                violations.append(_violation(mutation, "mutation_has_only_failed_numeric_evaluations", details={"numeric_evaluations": failed}))
            for value in ok_values.values():
                if isinstance(value, dict):
                    _audit_dynamic_numeric_binding(mutation, value, violations)
        return _trace(mutation, records, {"effect_id": effect_id or "", "opcode": str(metadata.get("opcode") or "")})

    def _audit_queue_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        _required_str(mutation, metadata, "queue_name", violations)
        _required_str(mutation, metadata, "queue_operation", violations)
        _required_str(mutation, metadata, "queue_intent_id", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        operation = str(metadata.get("queue_operation") or "")
        queue_intent_id = metadata.get("queue_intent_id")
        if isinstance(queue_intent_id, str) and queue_intent_id.startswith("manual_ultimate:"):
            return self._audit_manual_ultimate_queue_mutation(mutation, records, violations)
        if isinstance(queue_intent_id, str) and queue_intent_id:
            intent = self.rules.queue_intent(queue_intent_id)
            if intent is None:
                violations.append(_violation(mutation, "queue_intent_ir_missing", details={"queue_intent_id": queue_intent_id}))
            else:
                _audit_source(intent.source, intent.coverage_status, mutation, violations, executable_required=True)
        else:
            violations.append(
                _violation(
                    mutation,
                    "queue_source_ir_missing",
                    missing_field="queue_intent_id",
                    details={"metadata": metadata},
                )
            )
        queue_priority_id = metadata.get("queue_priority_id")
        if isinstance(queue_priority_id, str) and queue_priority_id:
            priority = self.rules.queue_priority(queue_priority_id)
            if priority is None:
                violations.append(_violation(mutation, "queue_priority_ir_missing", details={"queue_priority_id": queue_priority_id}))
            else:
                _audit_source(priority.source, priority.coverage_status, mutation, violations, executable_required=True)
        else:
            violations.append(
                _violation(
                    mutation,
                    "queue_priority_ir_missing",
                    missing_field="queue_priority_id",
                    details={"metadata": metadata},
                )
            )
        queue_window_id = metadata.get("queue_window_id")
        window = None
        if isinstance(queue_window_id, str) and queue_window_id:
            window = self.rules.queue_window(queue_window_id)
            if window is None:
                violations.append(_violation(mutation, "queue_window_ir_missing", details={"queue_window_id": queue_window_id}))
            else:
                _audit_source(window.source, window.coverage_status, mutation, violations, executable_required=True)
                if isinstance(queue_intent_id, str) and queue_intent_id and window.queue_intent_id != queue_intent_id:
                    violations.append(
                        _violation(
                            mutation,
                            "queue_window_intent_mismatch",
                            details={"expected": queue_intent_id, "actual": window.queue_intent_id},
                        )
                    )
        else:
            violations.append(
                _violation(
                    mutation,
                    "queue_window_ir_missing",
                    missing_field="queue_window_id",
                    details={"metadata": metadata},
                )
            )
        window_family = ""
        if window is not None:
            window_family = window.window_family
        elif isinstance(metadata.get("window_family"), str):
            window_family = str(metadata.get("window_family") or "")
        if window_family == "extra_turn":
            policy_id = _first_str(metadata.get("queue_lifecycle_policy_id"))
            window_plan = metadata.get("queue_window_plan")
            if not policy_id and isinstance(window_plan, dict):
                policy = window_plan.get("window_policy")
                if isinstance(policy, dict):
                    policy_id = _first_str(policy.get("queue_lifecycle_policy_id"))
            if not policy_id:
                violations.append(
                    _violation(
                        mutation,
                        "queue_lifecycle_policy_missing",
                        missing_field="queue_lifecycle_policy_id",
                        details={"metadata": metadata},
                    )
                )
            else:
                lifecycle_policy = self.rules.queue_lifecycle_policy(policy_id)
                if lifecycle_policy is None:
                    violations.append(
                        _violation(
                            mutation,
                            "queue_lifecycle_policy_ir_missing",
                            details={"queue_lifecycle_policy_id": policy_id},
                        )
                    )
                elif lifecycle_policy.coverage_status != "executable":
                    violations.append(
                        _violation(
                            mutation,
                            "queue_lifecycle_policy_not_executable",
                            details={
                                "queue_lifecycle_policy_id": policy_id,
                                "coverage_status": lifecycle_policy.coverage_status,
                                "blocked_reason": lifecycle_policy.blocked_reason,
                            },
                        )
                    )
                else:
                    _audit_source(lifecycle_policy.source, lifecycle_policy.coverage_status, mutation, violations, executable_required=True)
            extra_action_policy_id = _first_str(metadata.get("extra_action_policy_id"))
            if not extra_action_policy_id and isinstance(window_plan, dict):
                policy = window_plan.get("window_policy")
                if isinstance(policy, dict):
                    extra_action_policy_id = _first_str(policy.get("extra_action_policy_id"))
            if not extra_action_policy_id:
                violations.append(
                    _violation(
                        mutation,
                        "extra_action_policy_missing",
                        missing_field="extra_action_policy_id",
                        details={"metadata": metadata},
                    )
                )
            else:
                extra_policy = self.rules.extra_action_policy(extra_action_policy_id)
                if extra_policy is None:
                    violations.append(
                        _violation(
                            mutation,
                            "extra_action_policy_ir_missing",
                            details={"extra_action_policy_id": extra_action_policy_id},
                        )
                    )
                elif extra_policy.coverage_status != "executable":
                    violations.append(
                        _violation(
                            mutation,
                            "extra_action_policy_not_executable",
                            details={
                                "extra_action_policy_id": extra_action_policy_id,
                                "coverage_status": extra_policy.coverage_status,
                                "blocked_reason": extra_policy.blocked_reason,
                            },
                        )
                    )
                else:
                    _audit_source(extra_policy.source, extra_policy.coverage_status, mutation, violations, executable_required=True)
        target_resolution = metadata.get("target_resolution")
        if operation == "enqueue":
            if not isinstance(target_resolution, dict):
                violations.append(_violation(mutation, "queue_target_resolution_missing", missing_field="target_resolution"))
            elif target_resolution.get("ok") is not True:
                violations.append(
                    _violation(
                        mutation,
                        "queue_target_resolution_not_admitted",
                        details={"target_resolution": target_resolution},
                    )
                )
        queue_resolution_id = metadata.get("queue_resolution_id")
        if operation == "terminal_remove":
            terminal_plan = metadata.get("queue_terminal_plan")
            if not isinstance(terminal_plan, dict):
                violations.append(
                    _violation(
                        mutation,
                        "queue_terminal_plan_missing",
                        missing_field="queue_terminal_plan",
                    )
                )
            else:
                disposition = str(terminal_plan.get("disposition") or "")
                if disposition not in {"cancelled", "blocked_removed"}:
                    violations.append(
                        _violation(
                            mutation,
                            "queue_terminal_disposition_invalid",
                            details={"disposition": disposition},
                        )
                    )
                if terminal_plan.get("monotonic_progress") is not True:
                    violations.append(
                        _violation(
                            mutation,
                            "queue_terminal_progress_missing",
                            details={"queue_terminal_plan": terminal_plan},
                        )
                    )
                if not str(terminal_plan.get("blocked_reason") or ""):
                    violations.append(
                        _violation(
                            mutation,
                            "queue_terminal_reason_missing",
                            missing_field="queue_terminal_plan.blocked_reason",
                        )
                    )
            if isinstance(queue_resolution_id, str) and queue_resolution_id:
                resolution = self.rules.queue_resolution(queue_resolution_id)
                if resolution is None:
                    violations.append(
                        _violation(
                            mutation,
                            "queue_resolution_ir_missing",
                            details={"queue_resolution_id": queue_resolution_id},
                        )
                    )
                else:
                    _audit_source(
                        resolution.source,
                        resolution.coverage_status,
                        mutation,
                        violations,
                        executable_required=True,
                    )
            return _trace(
                mutation,
                records,
                {
                    "queue_name": str(metadata.get("queue_name") or ""),
                    "queue_operation": operation,
                    "queue_intent_id": str(queue_intent_id or ""),
                    "queue_resolution_id": str(queue_resolution_id or ""),
                    "queue_priority_id": str(queue_priority_id or ""),
                    "queue_window_id": str(queue_window_id or ""),
                    "terminal_disposition": str(metadata.get("queue_terminal_disposition") or ""),
                },
            )
        if operation == "dequeue":
            _required_str(mutation, metadata, "queue_resolution_id", violations)
            window_plan = metadata.get("queue_window_plan")
            if not isinstance(window_plan, dict):
                violations.append(_violation(mutation, "queue_window_plan_missing", missing_field="queue_window_plan"))
            elif window_plan.get("ok") is not True:
                violations.append(
                    _violation(
                        mutation,
                        "queue_window_plan_not_admitted",
                        details={"queue_window_plan": window_plan},
                    )
                )
            elif queue_window_id and window_plan.get("queue_window_id") != queue_window_id:
                violations.append(
                    _violation(
                        mutation,
                        "queue_window_plan_id_mismatch",
                        details={"queue_window_id": queue_window_id, "queue_window_plan": window_plan},
                    )
                )
            plan_target_resolution = window_plan.get("target_resolution") if isinstance(window_plan, dict) else None
            if not isinstance(plan_target_resolution, dict):
                violations.append(_violation(mutation, "queue_target_resolution_missing", missing_field="queue_window_plan.target_resolution"))
            elif plan_target_resolution.get("ok") is not True:
                violations.append(
                    _violation(
                        mutation,
                        "queue_target_resolution_not_admitted",
                        details={"target_resolution": plan_target_resolution},
                    )
                )
            if isinstance(queue_resolution_id, str) and queue_resolution_id:
                resolution = self.rules.queue_resolution(queue_resolution_id)
                if resolution is None:
                    violations.append(
                        _violation(mutation, "queue_resolution_ir_missing", details={"queue_resolution_id": queue_resolution_id})
                    )
                else:
                    _audit_source(resolution.source, resolution.coverage_status, mutation, violations, executable_required=True)
        return _trace(
            mutation,
            records,
            {
                "queue_name": str(metadata.get("queue_name") or ""),
                "queue_operation": operation,
                "queue_intent_id": str(queue_intent_id or ""),
                "queue_resolution_id": str(queue_resolution_id or ""),
                "queue_priority_id": str(queue_priority_id or ""),
                "queue_window_id": str(queue_window_id or ""),
            },
        )

    def _audit_manual_ultimate_queue_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        _required_str(mutation, metadata, "queue_name", violations)
        _required_str(mutation, metadata, "queue_operation", violations)
        _required_str(mutation, metadata, "queue_intent_id", violations)
        _required_str(mutation, metadata, "queue_window_id", violations)
        _require_dict(mutation, metadata, "manual_input_source", violations)
        _require_dict(mutation, metadata, "target_resolution", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        action_id = _required_str(mutation, metadata, "action_id", violations)
        action_level = _required_int(mutation, metadata, "action_level", violations)
        definition_id = _required_str(mutation, metadata, "definition_id", violations)
        action_event_id = _required_str(mutation, metadata, "action_event_id", violations)
        target_resolution = metadata.get("target_resolution")
        if isinstance(target_resolution, dict) and target_resolution.get("ok") is not True:
            violations.append(_violation(mutation, "manual_ultimate_target_resolution_not_admitted", details={"target_resolution": target_resolution}))
        if action_id and action_level is not None:
            definition = self.rules.action_definition(action_id, action_level)
            if definition is None:
                violations.append(_violation(mutation, "manual_ultimate_action_definition_missing", details={"action_id": action_id, "level": action_level}))
            elif definition.definition_id != definition_id:
                violations.append(_violation(mutation, "manual_ultimate_definition_id_mismatch", details={"expected": definition.definition_id, "actual": definition_id}))
            else:
                _audit_source(definition.source, definition.coverage_status, mutation, violations, executable_required=True)
            action_event = self.rules.action_event(action_id, action_level)
            if action_event is None:
                violations.append(_violation(mutation, "manual_ultimate_action_event_missing", details={"action_id": action_id, "level": action_level}))
            elif action_event.action_event_id != action_event_id:
                violations.append(_violation(mutation, "manual_ultimate_action_event_id_mismatch", details={"expected": action_event.action_event_id, "actual": action_event_id}))
            else:
                _audit_source(action_event.source, action_event.coverage_status, mutation, violations, check_status=False)
        return _trace(
            mutation,
            records,
            {
                "queue_name": str(metadata.get("queue_name") or ""),
                "queue_operation": str(metadata.get("queue_operation") or ""),
                "queue_intent_id": str(metadata.get("queue_intent_id") or ""),
                "queue_window_id": str(metadata.get("queue_window_id") or ""),
                "manual_ultimate": True,
                "action_id": action_id or "",
                "action_level": action_level if action_level is not None else "",
            },
        )

    def _audit_effect_id(self, mutation: Mutation, effect_id: str, violations: list[SourceAuditViolation]) -> None:
        effect = self.rules.effect(effect_id)
        if effect is None:
            violations.append(_violation(mutation, "effect_ir_missing", details={"effect_id": effect_id}))
            return
        _audit_source(effect.source, effect.coverage_status, mutation, violations, executable_required=True)


def _records_by_mutation_id(
    records: tuple[dict[str, JSONValue], ...],
) -> dict[str, tuple[dict[str, JSONValue], ...]]:
    by_id: dict[str, list[dict[str, JSONValue]]] = {}
    for record in records:
        mutation_id = record.get("mutation_id") if isinstance(record, dict) else None
        if isinstance(mutation_id, str) and mutation_id:
            by_id.setdefault(mutation_id, []).append(record)
    return {key: tuple(value) for key, value in by_id.items()}


_SUMMON_BIRTH_STAT_FIELDS = ("max_hp", "attack", "defense", "speed", "max_toughness")


def _audit_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _deep_json_copy(value: object) -> JSONValue:
    if isinstance(value, Mapping):
        return {str(key): _deep_json_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_json_copy(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _audit_level_context_identity(context: object) -> tuple[JSONValue, ...]:
    """Behavioral identity of a level context; source traces compare separately."""

    if not isinstance(context, Mapping) or not context:
        return ()
    ratios = context.get("ratios") if isinstance(context.get("ratios"), Mapping) else {}
    return (
        str(context.get("kind") or ""),
        str(context.get("admission_status") or ""),
        str(context.get("stage_id") or ""),
        str(context.get("wave_definition_id") or ""),
        context.get("level"),
        context.get("hard_level_group"),
        context.get("elite_group"),
        tuple(
            (name, _audit_number(ratios.get(name)))
            for name in _SUMMON_BIRTH_STAT_FIELDS
        ),
    )


def _audit_scaling_summary_identity(scaling: object) -> tuple[JSONValue, ...]:
    """Project the recorded scaling summary onto the level context identity."""

    if not isinstance(scaling, Mapping):
        return ()
    return _audit_level_context_identity(
        {
            "kind": scaling.get("level_context_kind"),
            "admission_status": "executable",
            "stage_id": scaling.get("stage_id"),
            "wave_definition_id": scaling.get("wave_definition_id"),
            "level": scaling.get("level"),
            "hard_level_group": scaling.get("hard_level_group"),
            "elite_group": scaling.get("elite_group"),
            "ratios": scaling.get("ratios"),
        }
    )


def _audit_plan_list_item(values: object, unit_id: str) -> Mapping | None:
    if not isinstance(values, (list, tuple)):
        return None
    for item in values:
        if isinstance(item, Mapping) and item.get("unit_id") == unit_id:
            return item
    return None


def _audit_value_equal(left: object, right: object) -> bool:
    return _deep_json_copy(left) == _deep_json_copy(right)


def _audit_source_tree(
    source: object,
    *,
    path: str = "",
) -> dict[str, tuple[JSONValue, ...]]:
    """Flatten a nested source trace into path -> identity plus evidence.

    The battle level policy references a stage node and one difficulty row node
    (and the elite node when declared). Comparing only top-level identity would
    silently treat both sides as empty, so every node keeps its own path and the
    evidence it was selected from.
    """

    result: dict[str, tuple[JSONValue, ...]] = {}
    if not isinstance(source, Mapping):
        return result
    identity_keys = ("source_path", "raw_type", "raw_id")
    if all(
        isinstance(source.get(key), str) and str(source.get(key)).strip()
        for key in identity_keys
    ):
        result[path or "~"] = (
            str(source.get("source_path")),
            str(source.get("raw_type")),
            str(source.get("raw_id")),
            _deep_json_copy(source.get("evidence")),
        )
        return result
    for key, value in source.items():
        child = f"{path}/{key}" if path else str(key)
        if isinstance(value, Mapping):
            result.update(_audit_source_tree(value, path=child))
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                result.update(_audit_source_tree(item, path=f"{child}[{index}]"))
    return result


def _audit_summon_spawn_plan(
    records: tuple[dict[str, JSONValue], ...],
    mutation: Mutation,
) -> Mapping | None:
    """Return the native summon settlement plan of this mutation, if any.

    The plan is only accepted from the producer that actually emitted it: the
    settlement record must be a `summon_transition` from `summon_system`, carry
    this mutation id in its own plan identity, and agree with its operation and
    ok flag. An arbitrary record that merely contains a plan is not proof.
    """

    mutation_id = mutation.stable_id()
    for record in records:
        if not isinstance(record, Mapping):
            return None
        if record.get("mutation_id") != mutation_id:
            return None
        if record.get("record_type") != "summon_transition":
            return None
        if record.get("source") != "summon_system":
            return None
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            return None
        plan = payload.get("plan")
        if not isinstance(plan, Mapping):
            return None
        payload_mutation_ids = payload.get("mutation_ids")
        if (
            not isinstance(payload_mutation_ids, (list, tuple))
            or mutation_id not in payload_mutation_ids
        ):
            return None
        if payload.get("operation") != plan.get("operation"):
            return None
        if payload.get("ok") is not plan.get("ok"):
            return None
        trace = record.get("trace")
        if not isinstance(trace, Mapping):
            return None
        return plan
    return None


def _audit_source(
    source: IRSource,
    coverage_status: str,
    mutation: Mutation,
    violations: list[SourceAuditViolation],
    *,
    executable_required: bool = False,
    check_status: bool = True,
) -> None:
    if not source.source_path:
        violations.append(_violation(mutation, "source_path_missing", missing_field="source.source_path"))
    if not source.raw_type:
        violations.append(_violation(mutation, "source_raw_type_missing", missing_field="source.raw_type"))
    if not source.raw_id:
        violations.append(_violation(mutation, "source_raw_id_missing", missing_field="source.raw_id"))
    if "Missing" in source.raw_type or "Missing" in source.raw_id:
        violations.append(_violation(mutation, "placeholder_source_not_allowed", details={"source": source.to_json()}))
    if executable_required and coverage_status != "executable":
        violations.append(_violation(mutation, "source_ir_not_executable", details={"coverage_status": coverage_status, "source": source.to_json()}))
    elif check_status and coverage_status in NON_MUTATING_STATUSES:
        violations.append(_violation(mutation, "non_mutating_ir_produced_mutation", details={"coverage_status": coverage_status, "source": source.to_json()}))


def _audit_dynamic_numeric_binding(
    mutation: Mutation,
    evaluation: dict[str, JSONValue],
    violations: list[SourceAuditViolation],
    *,
    template_depth: int = 0,
) -> None:
    if evaluation.get("expression_kind") == "postfix_expr":
        _audit_postfix_dynamic_numeric_binding(mutation, evaluation, violations, template_depth=template_depth)
        return
    if evaluation.get("expression_kind") != "dynamic_hash":
        return
    bindings = evaluation.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        violations.append(_violation(mutation, "dynamic_numeric_binding_missing", missing_field="numeric_evaluation.bindings"))
        return
    source_type = str(bindings.get("source_type") or "")
    if source_type == "explicit_dynamic_values":
        violations.append(
            _violation(
                mutation,
                "manual_dynamic_value_binding_not_allowed_for_trusted_mutation",
                missing_field="numeric_evaluation.bindings.source_type",
                details={"bindings": bindings},
            )
        )
        return
    if source_type not in {
        "status_instance",
        "dynamic_value_store",
        "break_template_runtime_value",
        "character_skill_param_slot",
        "task_template_parameter",
    }:
        violations.append(
            _violation(
                mutation,
                "dynamic_numeric_binding_source_not_trusted",
                missing_field="numeric_evaluation.bindings.source_type",
                details={"bindings": bindings},
            )
        )
        return
    entry = bindings.get("entry")
    if not isinstance(entry, dict):
        violations.append(_violation(mutation, "dynamic_numeric_binding_entry_missing", missing_field="numeric_evaluation.bindings.entry"))
        return
    if not isinstance(entry.get("source_trace"), dict):
        violations.append(_violation(mutation, "dynamic_numeric_binding_source_trace_missing", missing_field="numeric_evaluation.bindings.entry.source_trace"))
    elif source_type == "task_template_parameter":
        _audit_template_parameter_binding(mutation, entry, violations, template_depth)


def _audit_postfix_dynamic_numeric_binding(
    mutation: Mutation,
    evaluation: dict[str, JSONValue],
    violations: list[SourceAuditViolation],
    *,
    template_depth: int = 0,
) -> None:
    bindings = evaluation.get("bindings")
    if not isinstance(bindings, dict):
        violations.append(_violation(mutation, "postfix_numeric_binding_missing", missing_field="numeric_evaluation.bindings"))
        return
    operands = bindings.get("dynamic_operands")
    if not isinstance(operands, list) or not operands:
        violations.append(_violation(mutation, "postfix_dynamic_operands_missing", missing_field="numeric_evaluation.bindings.dynamic_operands"))
        return
    for operand in operands:
        if not isinstance(operand, dict):
            violations.append(_violation(mutation, "postfix_dynamic_operand_invalid", details={"operand": operand}))
            continue
        if operand.get("ok") is not True:
            violations.append(_violation(mutation, "postfix_dynamic_operand_unresolved", details={"operand": operand}))
            continue
        operand_bindings = operand.get("bindings")
        if not isinstance(operand_bindings, dict):
            violations.append(_violation(mutation, "postfix_dynamic_operand_binding_missing", details={"operand": operand}))
            continue
        source_type = str(operand_bindings.get("source_type") or "")
        if source_type not in {
            "status_instance",
            "dynamic_value_store",
            "break_template_runtime_value",
            "character_skill_param_slot",
            "task_template_parameter",
        }:
            violations.append(
                _violation(
                    mutation,
                    "postfix_dynamic_binding_source_not_trusted",
                    missing_field="numeric_evaluation.bindings.dynamic_operands.bindings.source_type",
                    details={"bindings": operand_bindings},
                )
            )
            continue
        entry = operand_bindings.get("entry")
        if not isinstance(entry, dict):
            violations.append(_violation(mutation, "postfix_dynamic_binding_entry_missing", details={"bindings": operand_bindings}))
            continue
        if not isinstance(entry.get("source_trace"), dict):
            violations.append(
                _violation(
                    mutation,
                    "postfix_dynamic_binding_source_trace_missing",
                    missing_field="numeric_evaluation.bindings.dynamic_operands.bindings.entry.source_trace",
                )
            )
        elif source_type == "task_template_parameter":
            _audit_template_parameter_binding(mutation, entry, violations, template_depth)


def _audit_template_parameter_binding(
    mutation: Mutation, entry: dict[str, JSONValue], violations: list[SourceAuditViolation], depth: int,
) -> None:
    trace = entry["source_trace"]
    source = trace.get("parameter_source")
    evaluation = trace.get("numeric_evaluation")
    if (depth >= 32 or not isinstance(source, dict) or not isinstance(evaluation, dict)
            or any(not isinstance(source.get(key), str) or not source[key]
                   for key in ("source_path", "raw_type", "raw_id"))
            or not isinstance(source.get("evidence"), dict)
            or evaluation.get("ok") is not True
            or type(entry.get("value")) not in (int, float) or not math.isfinite(entry["value"])
            or entry["value"] != evaluation.get("value")):
        violations.append(_violation(mutation, "task_template_parameter_binding_invalid"))
        return
    _audit_source(IRSource(source["source_path"], source["raw_type"], source["raw_id"], source["evidence"]),
                  "executable", mutation, violations, executable_required=True)
    _audit_dynamic_numeric_binding(mutation, evaluation, violations, template_depth=depth + 1)


def _required_str(
    mutation: Mutation,
    metadata: dict[str, JSONValue],
    key: str,
    violations: list[SourceAuditViolation],
) -> str:
    value = metadata.get(key)
    if isinstance(value, str) and value:
        return value
    violations.append(_violation(mutation, "required_metadata_missing", missing_field=key))
    return ""


def _required_int(
    mutation: Mutation,
    metadata: dict[str, JSONValue],
    key: str,
    violations: list[SourceAuditViolation],
) -> int | None:
    value = metadata.get(key)
    if isinstance(value, int):
        return value
    violations.append(_violation(mutation, "required_metadata_missing", missing_field=key))
    return None


def _require_dict(
    mutation: Mutation,
    metadata: dict[str, JSONValue],
    key: str,
    violations: list[SourceAuditViolation],
) -> None:
    if not isinstance(metadata.get(key), dict):
        violations.append(_violation(mutation, "required_metadata_missing", missing_field=key))


def _first_str(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""


def _summon_audit_intent_ids(*sources: dict[str, JSONValue]) -> tuple[str, ...]:
    values: list[str] = []
    for source in sources:
        for key in ("intent_id", "summon_intent_id", "servant_definition_id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                values.append(value)
        raw_intent_ids = source.get("intent_ids")
        if isinstance(raw_intent_ids, list):
            values.extend(str(item) for item in raw_intent_ids if isinstance(item, str) and item)
    return tuple(dict.fromkeys(values))


def _trace(
    mutation: Mutation,
    records: tuple[dict[str, JSONValue], ...],
    origin: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    return {
        "mutation": mutation.to_json(detach=False),
        "settlement_records": list(records),
        "origin": origin,
    }


def _violation(
    mutation: Mutation,
    reason: str,
    *,
    missing_field: str = "",
    details: dict[str, JSONValue] | None = None,
) -> SourceAuditViolation:
    return SourceAuditViolation(
        mutation_id=mutation.stable_id(),
        source=mutation.source,
        path=mutation.path,
        reason=reason,
        missing_field=missing_field,
        details=details or {},
    )
