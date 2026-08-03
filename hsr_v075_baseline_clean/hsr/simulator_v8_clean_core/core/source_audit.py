from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import BattleTransition, JSONValue, Mutation
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
        for mutation in mutations:
            mutation_records = records_by_mutation.get(mutation.stable_id(), ())
            if not mutation_records:
                violations.append(_violation(mutation, "mutation_has_no_settlement_record"))
                continue
            trace = self._audit_mutation(mutation, mutation_records, violations)
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
        if mutation.source == "summon_system":
            return self._audit_summon_mutation(mutation, records, violations)
        violations.append(_violation(mutation, "unsupported_mutation_source", details={"records": list(records)}))
        return _trace(mutation, records, {})

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
            contract_matches = (
                tuple(mutation.path) == rule.state_path
                and trigger_kind == rule.trigger_kind
                and trigger_identity == rule.trigger_identity
                and runtime_event_type == rule.runtime_event_type
                and callback_event == rule.callback_event
                and type(mutation.after) is type(rule.after_value)
                and mutation.after == rule.after_value
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
            if mutation.before_exists:
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

    def _audit_damage_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        _require_dict(mutation, metadata, "source_frame", violations)
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
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        if isinstance(metadata.get("break_recovery"), dict):
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
        if metadata.get("dynamic_key") or metadata.get("property"):
            return self._audit_status_callback_dynamic_value_mutation(mutation, records, violations)
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
        return _trace(mutation, records, {"effect_id": effect_id or "", "modifier_name": modifier_name or "", "lifecycle_plan": lifecycle})

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
) -> None:
    if evaluation.get("expression_kind") == "postfix_expr":
        _audit_postfix_dynamic_numeric_binding(mutation, evaluation, violations)
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


def _audit_postfix_dynamic_numeric_binding(
    mutation: Mutation,
    evaluation: dict[str, JSONValue],
    violations: list[SourceAuditViolation],
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
        "mutation": mutation.to_json(),
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
