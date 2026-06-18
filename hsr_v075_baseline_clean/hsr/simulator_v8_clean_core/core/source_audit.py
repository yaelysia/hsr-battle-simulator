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
    "combat_executor.timeline": {
        "required_ir": ["ActionDefinitionIR", "ActionEventIR"],
        "required_metadata": ["action_id", "action_level", "definition_id", "action_event_id", "source_trace"],
        "coverage_required": "ActionDefinitionIR executable; ActionEventIR traceable",
    },
    "combat_executor.resources": {
        "required_ir": ["ActionDefinitionIR", "ActionEventIR"],
        "required_metadata": ["action_id", "action_level", "definition_id", "action_event_id", "source_trace"],
        "coverage_required": "ActionDefinitionIR executable; ActionEventIR traceable",
    },
    "damage_system": {
        "required_ir": ["DamageEmissionIR + AbilityTaskIR + HitProfileIR", "BreakDamageEmissionIR + BreakBaseDamageIR for break", "StatusDamageEmissionIR + StatusCallbackIR for break DOT tick", "or EffectIR for hp_loss"],
        "required_metadata": ["damage_emission_id/source_task_id/hit_profile_id or break_damage_emission_id or status_damage_emission_id or effect_id", "source_trace"],
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
        "coverage_required": "executable",
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
    "queue_system": {
        "required_ir": ["ActionDefinitionIR or EffectIR"],
        "required_metadata": ["queue_name", "queue_operation", "source_trace"],
        "coverage_required": "executable",
    },
    "combat_executor.queue": {
        "required_ir": ["ActionDefinitionIR or EffectIR"],
        "required_metadata": ["queue_name", "queue_operation", "source_trace"],
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
        records = _records_by_mutation_id(transition)
        violations: list[SourceAuditViolation] = []
        traces: list[dict[str, JSONValue]] = []
        for mutation in transition.transaction.mutations:
            mutation_records = records.get(mutation.stable_id(), ())
            if not mutation_records:
                violations.append(_violation(mutation, "mutation_has_no_settlement_record"))
                continue
            trace = self._audit_mutation(mutation, mutation_records, violations)
            if trace:
                traces.append(trace)
        return SourceAuditResult(
            ok=not violations,
            checked_mutations=len(transition.transaction.mutations),
            checked_records=sum(len(value) for value in records.values()),
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
        if mutation.source == "combat_executor.resources":
            return self._audit_action_source_mutation(mutation, records, violations, require_action_event=True)
        if mutation.source == "damage_system":
            return self._audit_damage_mutation(mutation, records, violations)
        if mutation.source == "toughness_system":
            return self._audit_toughness_mutation(mutation, records, violations)
        if mutation.source == "break_system":
            return self._audit_break_mutation(mutation, records, violations)
        if mutation.source == "status_system":
            return self._audit_status_mutation(mutation, records, violations)
        if mutation.source == "effect_system":
            return self._audit_effect_mutation(mutation, records, violations)
        if mutation.source in {"queue_system", "combat_executor.queue"}:
            return self._audit_queue_mutation(mutation, records, violations)
        violations.append(_violation(mutation, "unsupported_mutation_source", details={"records": list(records)}))
        return _trace(mutation, records, {})

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
        _require_dict(mutation, metadata, "source_trace", violations)
        return _trace(
            mutation,
            records,
            {
                "action_id": action_id or "",
                "action_level": action_level if action_level is not None else "",
                "definition_id": definition_id or "",
                "action_event_id": action_event_id or "",
            },
        )

    def _audit_damage_mutation(
        self,
        mutation: Mutation,
        records: tuple[dict[str, JSONValue], ...],
        violations: list[SourceAuditViolation],
    ) -> dict[str, JSONValue]:
        metadata = mutation.metadata
        if metadata.get("damage_formula_family") == "break" and metadata.get("status_damage_emission_id"):
            return self._audit_status_callback_damage_mutation(mutation, records, violations)
        if metadata.get("damage_formula_family") == "break":
            return self._audit_break_damage_mutation(mutation, records, violations)
        effect_id = _first_str(metadata.get("effect_id"))
        if effect_id and metadata.get("damage_formula_family") == "hp_loss":
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
                    "damage_formula_family": "hp_loss",
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
        template_id = _required_str(mutation, metadata, "break_template_id", violations)
        emission_id = _required_str(mutation, metadata, "toughness_emission_id", violations)
        task_id = _required_str(mutation, metadata, "source_task_id", violations)
        hit_profile_id = _required_str(mutation, metadata, "hit_profile_id", violations)
        _require_dict(mutation, metadata, "source_trace", violations)
        _require_dict(mutation, metadata, "break_lifecycle", violations)
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
        _require_dict(mutation, metadata, "source_trace", violations)
        effect_id = metadata.get("effect_id")
        action_id = metadata.get("action_id")
        action_level = metadata.get("action_level")
        if isinstance(effect_id, str) and effect_id:
            self._audit_effect_id(mutation, effect_id, violations)
        elif isinstance(action_id, str) and isinstance(action_level, int):
            self._audit_action_source_mutation(mutation, records, violations, require_action_event=False)
        else:
            violations.append(
                _violation(
                    mutation,
                    "queue_source_ir_missing",
                    missing_field="effect_id|action_id+action_level",
                    details={"metadata": metadata},
                )
            )
        return _trace(
            mutation,
            records,
            {
                "queue_name": str(metadata.get("queue_name") or ""),
                "queue_operation": str(metadata.get("queue_operation") or ""),
                "effect_id": str(effect_id or ""),
                "action_id": str(action_id or ""),
                "action_level": action_level if isinstance(action_level, int) else "",
            },
        )

    def _audit_effect_id(self, mutation: Mutation, effect_id: str, violations: list[SourceAuditViolation]) -> None:
        effect = self.rules.effect(effect_id)
        if effect is None:
            violations.append(_violation(mutation, "effect_ir_missing", details={"effect_id": effect_id}))
            return
        _audit_source(effect.source, effect.coverage_status, mutation, violations, executable_required=True)


def _records_by_mutation_id(transition: BattleTransition) -> dict[str, tuple[dict[str, JSONValue], ...]]:
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
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
    if source_type not in {"status_instance", "dynamic_value_store", "break_template_runtime_value"}:
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
        if source_type not in {"status_instance", "dynamic_value_store", "break_template_runtime_value"}:
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
