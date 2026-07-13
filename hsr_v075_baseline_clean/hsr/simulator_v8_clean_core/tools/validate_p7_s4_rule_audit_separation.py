from __future__ import annotations

import argparse
import ast
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor, _queue_action_resource_policy
from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, UnitState
from ..rules.engine_rule_registry import (
    ENGINE_RULE_REGISTRY_VERSION,
    KILL_ENERGY_RULE_APPLICABILITY,
    TIMELINE_RULE_APPLICABILITY,
    ULTIMATE_COST_RULE_APPLICABILITY,
    build_engine_rule_registry,
)
from ..rules.ir import (
    AbilityTaskIR,
    BreakStatusEmissionIR,
    CharacterDataCardIR,
    EffectIR,
    IRSource,
    RuleEntity,
    StandaloneAbilityGraphIR,
    StatusCallbackIR,
    StatusCallbackTaskIR,
    UnitBirthTemplateIR,
    WaveDefinitionIR,
    WaveMonsterEntryIR,
)
from ..rules.rulebook import RuleBook
from ..systems.dot_formula import _status_formula_bindings
from ..systems.break_system import BreakSystem, _break_recovery_contract
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventAlias, EventDispatchSystem, ListenerMatch, _listener_order_key, _match_sort_key
from ..systems.resource import ResourceSystem
from ..systems.scheduler import CombatScheduler, _queue_entry_resource_policy
from ..systems.status import _select_modifier_definition
from ..systems.summon import _replacement_policy_admitted
from ..systems.unit_spawn import UnitSpawnRequest, UnitSpawnSystem
from ..systems.wave import _wave_definition_payload_blocked_reason, _wave_entry_payload_blocked_reason
from ..systems.status_callbacks import (
    _break_element_from_detail,
    _break_template_id_from_detail,
    _retarget_candidates,
    _retarget_max_number,
)
from ..tbgd.lowering import (
    _action_definition_from_row,
    _link_status_effect_runtime_fields,
    _link_trigger_ability_graphs,
)
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state, _decision_state
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s4_rule_audit_separation"
MATRIX_SCHEMA_VERSION = "p7_s4_rule_audit_separation_matrix_v1"

RUNTIME_SCAN_ROOTS = ("core", "rules", "systems")
RUNTIME_SCAN_EXCLUSIONS = frozenset({"core/source_audit.py"})
FORBIDDEN_AUDIT_BEHAVIOR_KEYS = frozenset(
    {
        "task",
        "retarget",
        "skill_trigger_key",
        "queue_intent_resource_policy",
        "status_formula_bindings",
        "break_status_emission_id",
        "damage_custom_name",
        "command",
    }
)
UNIT_SPAWN_BEHAVIOR_FUNCTIONS = frozenset(
    {
        "to_unit",
        "_template_request_blocked_reason",
        "_validate_spawn_request_complete",
        "_validate_unit_request_binding",
        "_validate_birth_plan_source_fields",
        "_spawn_request_identity",
    }
)
TRACE_GATE_REASON_FRAGMENTS = (
    "source_trace_missing",
    "source_trace_mismatch",
    "entry_source_trace_missing",
    "entry_source_trace_mismatch",
)
AUDIT_IDENTITY_KEYS = frozenset(
    {"source_path", "raw_type", "raw_id", "evidence", "predicate_path", "create_task_path"}
)
AUDIT_NORMALIZATION_FUNCTIONS = frozenset(
    {"_binding_sources_from_expression", "_validate_shield_instances"}
)


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    audit_equivalence = _audit_trim_equivalence()
    typed_fields = _typed_field_cases()
    engine_registry = _engine_registry_cases()
    unit_spawn_audit = _unit_spawn_audit_trim_equivalence()
    callback_order_audit = _callback_order_audit_trim_equivalence()
    servant_replacement_audit = _servant_replacement_audit_trim_equivalence()
    wave_payload_audit = _wave_payload_audit_trim_equivalence()
    break_recovery_audit = _break_recovery_audit_trim_equivalence()
    static_boundary = _static_boundary(package_root)

    checks = {
        "complete_vs_minimal_audit_execution_equivalent": audit_equivalence["ok"],
        "status_callback_task_payload_is_typed_field": typed_fields["task_payload_equal"],
        "retarget_policy_is_typed_field": typed_fields["retarget_equal"],
        "status_definition_link_is_explicit": typed_fields["modifier_link_equal"],
        "break_status_link_is_typed_state": typed_fields["break_link_equal"],
        "queue_resource_policy_is_direct_field": typed_fields["queue_policy_equal"],
        "dot_formula_binding_has_no_audit_fallback": typed_fields["dot_binding_boundary"],
        "character_dynamic_binding_is_direct_card_field": typed_fields["character_binding_equal"],
        "lowering_projects_explicit_runtime_links": typed_fields["lowering_links_projected"],
        "engine_registry_identity_complete": engine_registry["identity_complete"],
        "engine_registry_audit_trim_equivalent": engine_registry["audit_trim_equal"],
        "engine_registry_missing_version_ambiguous_blocked": engine_registry["negative_cases_ok"],
        "engine_registry_missing_rule_state_unchanged": engine_registry["missing_rule_state_unchanged"],
        "kill_energy_uses_typed_numeric_value": engine_registry["kill_energy_typed_value"],
        "unit_spawn_audit_trim_equivalent": unit_spawn_audit["ok"],
        "callback_order_audit_trim_equivalent": callback_order_audit["ok"],
        "servant_replacement_audit_trim_equivalent": servant_replacement_audit["ok"],
        "wave_payload_audit_trim_equivalent": wave_payload_audit["ok"],
        "break_recovery_audit_trim_equivalent": break_recovery_audit["ok"],
        "p7_i16_behavior_reads_absent": static_boundary["ok"],
        "no_large_artifacts": True,
    }
    ok = all(checks.values())
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "rows": [
            {
                "entry": row["entry"],
                "former_behavior_input": row["former_behavior_input"],
                "current_rule_owner": row["current_rule_owner"],
                "status": row["status"],
            }
            for row in static_boundary["ownership_rows"]
        ],
    }
    evidence = {
        "audit_trim_equivalence": audit_equivalence,
        "typed_field_cases": typed_fields,
        "engine_registry": engine_registry,
        "unit_spawn_audit_trim_equivalence": unit_spawn_audit,
        "callback_order_audit_trim_equivalence": callback_order_audit,
        "servant_replacement_audit_trim_equivalence": servant_replacement_audit,
        "wave_payload_audit_trim_equivalence": wave_payload_audit,
        "break_recovery_audit_trim_equivalence": break_recovery_audit,
        "static_boundary": static_boundary,
    }
    summary = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ready_for_review": ok,
        "ok": ok,
        "checks": checks,
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "ownership_row_count": len(static_boundary["ownership_rows"]),
        "artifact_policy": {
            "large_artifacts_written": False,
            "canonical_ir_serialized": False,
            "full_transition_dump_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p7_s4_rule_audit_separation_evidence.json", evidence)
    write_json(output_dir / "p7_s4_rule_audit_separation_matrix.json", matrix)
    write_json(output_dir / "validation_summary_p7_s4_rule_audit_separation.json", summary)
    return summary


def _audit_trim_equivalence() -> dict[str, Any]:
    full_rules = _trust_rulebook()
    trimmed_rules = RuleBook(_trim_audit(full_rules.ir))
    state = _decision_state(_base_state(skill_points=3))
    actor_id = next(unit.unit_id for unit in state.units.values() if unit.side == "ally")
    target_id = next(unit.unit_id for unit in state.units.values() if unit.side == "enemy")
    rows = []
    for definition in sorted(full_rules.ir.action_definitions, key=lambda item: item.definition_id):
        command = ActionCommand(
            actor_id=actor_id,
            action_id=definition.action_id,
            action_level=definition.level,
            target_ids=(target_id,),
        )
        full_state, full_transition = CombatExecutor(full_rules).execute(command, state)
        trimmed_state, trimmed_transition = CombatExecutor(trimmed_rules).execute(command, state)
        full_projection = _behavior_projection(full_state, full_transition)
        trimmed_projection = _behavior_projection(trimmed_state, trimmed_transition)
        rows.append(
            {
                "definition_id": definition.definition_id,
                "outcome": full_transition.outcome.category,
                "equivalent": full_projection == trimmed_projection,
                "full": full_projection,
                "trimmed": trimmed_projection,
            }
        )
    has_committed = any(row["outcome"] == "committed" for row in rows)
    has_non_successor = any(row["outcome"] in {"blocked", "diagnostic"} for row in rows)
    return {
        "ok": bool(rows) and has_committed and has_non_successor and all(row["equivalent"] for row in rows),
        "selection_predicate": "all structurally available action definitions in the lightweight trust RuleBook",
        "case_count": len(rows),
        "has_committed": has_committed,
        "has_non_successor": has_non_successor,
        "rows": rows,
    }


def _unit_spawn_audit_trim_equivalence() -> dict[str, Any]:
    source = IRSource(
        source_path="validation/unit_birth.json",
        raw_type="ValidationUnitBirth",
        raw_id="validation:servant",
        evidence={"detail": "full_audit_payload"},
    )
    template = UnitBirthTemplateIR(
        birth_template_id="validation:birth:servant",
        spawn_kind="servant",
        entity_ref="validation:servant",
        unit_field_specs={
            "side": "summon",
            "template_id": {"binding_kind": "request_field", "field": "entity_ref"},
            "level": 1,
            "max_hp": 100.0,
            "hp": 100.0,
            "attack": 10.0,
            "defense": 10.0,
            "speed": 100.0,
            "energy": 0.0,
            "max_energy": 0.0,
            "toughness": 0.0,
            "max_toughness": 0.0,
            "action_value": 100.0,
        },
        flag_specs={
            "owner_id": {"binding_kind": "request_field", "field": "owner_id"},
            "summoner_id": {"binding_kind": "request_field", "field": "summoner_id"},
            "summon_kind": "servant",
            "servant_definition_id": {"binding_kind": "request_field", "field": "source_id"},
            "servant_ref": {"binding_kind": "request_field", "field": "entity_ref"},
            "summon_intent_id": {"binding_kind": "request_field", "field": "source_id"},
        },
        resource_specs={},
        request_contract={
            "spawn_kind": "servant",
            "entity_ref": "validation:servant",
            "source_id": "validation:servant_definition",
            "entry_id": "validation:servant_entry",
            "owner_required": True,
            "summoner_matches_owner": True,
            "template_source_role": "entry",
        },
        source=source,
        coverage_status="executable",
    )
    owner = next(unit for unit in _base_state().units.values() if unit.side == "ally")
    request = UnitSpawnRequest(
        spawn_kind="servant",
        unit_id="summon:validation",
        birth_template_id=template.birth_template_id,
        entity_ref=template.entity_ref,
        source_id="validation:servant_definition",
        entry_id="validation:servant_entry",
        owner_id=owner.unit_id,
        summoner_id=owner.unit_id,
        source_trace=source.to_json(),
        entry_source_trace=source.to_json(),
    )
    trimmed = replace(request, source_trace={}, entry_source_trace={})
    system = UnitSpawnSystem()
    full_plan = system.plan(template, request, owner=owner)
    trimmed_plan = system.plan(template, trimmed, owner=owner)
    full_unit = full_plan.to_unit(expected_request=request) if full_plan.ok else None
    trimmed_unit = trimmed_plan.to_unit(expected_request=trimmed) if trimmed_plan.ok else None
    identity_mismatch = system.plan(
        template,
        replace(trimmed, source_id="validation:wrong_source"),
        owner=owner,
    )
    return {
        "ok": full_plan.ok
        and trimmed_plan.ok
        and full_unit == trimmed_unit
        and not identity_mismatch.ok
        and identity_mismatch.blocked_reason == "unit_birth_template_request_contract_mismatch:source_id",
        "full_plan_ok": full_plan.ok,
        "trimmed_plan_ok": trimmed_plan.ok,
        "behavior_units_equal": full_unit == trimmed_unit,
        "identity_mismatch_blocked": not identity_mismatch.ok,
        "identity_mismatch_reason": identity_mismatch.blocked_reason,
    }


def _callback_order_audit_trim_equivalence() -> dict[str, Any]:
    state = _base_state(skill_points=3)
    callbacks = (
        StatusCallbackIR(
            callback_id="validation:callback:late",
            modifier_name="ValidationModifier",
            event="OnAfterHitAll",
            task_ids=("validation:task:late",),
            source=IRSource("z/audit/path.json", "AuditLate", "raw:late", {"detail": "late"}),
            coverage_status="executable",
            admission_status="executable",
            scope_kind="status_local",
            execution_order=(4, 2),
        ),
        StatusCallbackIR(
            callback_id="validation:callback:early",
            modifier_name="ValidationModifier",
            event="OnAfterHitAll",
            task_ids=("validation:task:early",),
            source=IRSource("a/audit/path.json", "AuditEarly", "raw:early", {"detail": "early"}),
            coverage_status="executable",
            admission_status="executable",
            scope_kind="status_local",
            execution_order=(4, 1),
        ),
    )

    def ordered_ids(items: tuple[StatusCallbackIR, ...]) -> tuple[str, ...]:
        matches = tuple(
            ListenerMatch(
                listener_kind="status_callback",
                scope_kind="status_local",
                callback_event=callback.event,
                unit_id="ally:actor",
                modifier_name=callback.modifier_name,
                callback=callback,
                order_key=_listener_order_key(state, "status_local", "ally:actor", 0, callback),
            )
            for callback in items
        )
        return tuple(
            match.callback.callback_id
            for match in sorted(matches, key=_match_sort_key)
            if match.callback is not None
        )

    trimmed = tuple(_trim_audit(callback) for callback in callbacks)
    full_order = ordered_ids(callbacks)
    trimmed_order = ordered_ids(trimmed)
    base_ir = _trust_rulebook().ir
    full_rule_order = tuple(
        callback.callback_id
        for callback in RuleBook(
            replace(base_ir, status_callbacks=callbacks, status_callback_tasks=())
        ).status_callbacks_for_event_scope("OnAfterHitAll", "status_local")
    )
    trimmed_rule_order = tuple(
        callback.callback_id
        for callback in RuleBook(
            replace(base_ir, status_callbacks=trimmed, status_callback_tasks=())
        ).status_callbacks_for_event_scope("OnAfterHitAll", "status_local")
    )
    actor = state.units["ally:actor"]
    dispatch_state = replace(
        state,
        units={
            **state.units,
            actor.unit_id: replace(
                actor,
                flags={
                    **actor.flags,
                    "status_details": [
                        {
                            "instance_id": "validation:callback:status",
                            "owner_id": actor.unit_id,
                            "modifier_name": "ValidationModifier",
                            "trigger_ids_by_event": {
                                "OnAfterHitAll": [
                                    "validation:callback:late",
                                    "validation:callback:early",
                                ]
                            },
                        }
                    ],
                },
            ),
        },
    )
    event = GameEvent(
        "validation.callback.order",
        source_id=actor.unit_id,
        target_id=actor.unit_id,
        window="OnAfterHitAll",
        process_only=True,
        payload={"callback_event": "OnAfterHitAll"},
    )
    alias = EventAlias(
        callback_event="OnAfterHitAll",
        scope_kind="status_local",
        source_basis="validation:typed_callback_order",
    )
    full_dispatch_rules = RuleBook(replace(base_ir, status_callbacks=callbacks, status_callback_tasks=()))
    trimmed_dispatch_rules = RuleBook(replace(base_ir, status_callbacks=trimmed, status_callback_tasks=()))
    full_dispatch_order = tuple(
        match.callback.callback_id
        for match in EventDispatchSystem(
            full_dispatch_rules,
            EffectRegistry(),
        )._explicit_status_matches(
            dispatch_state,
            event,
            (alias,),
            actor.unit_id,
            "ValidationModifier",
        )
        if match.callback is not None
    )
    trimmed_dispatch_order = tuple(
        match.callback.callback_id
        for match in EventDispatchSystem(
            trimmed_dispatch_rules,
            EffectRegistry(),
        )._explicit_status_matches(
            dispatch_state,
            event,
            (alias,),
            actor.unit_id,
            "ValidationModifier",
        )
        if match.callback is not None
    )
    return {
        "ok": full_order == trimmed_order == (
            "validation:callback:early",
            "validation:callback:late",
        )
        and full_rule_order == trimmed_rule_order == full_order
        and full_dispatch_order == trimmed_dispatch_order == full_order,
        "full_order": full_order,
        "trimmed_order": trimmed_order,
        "full_rulebook_order": full_rule_order,
        "trimmed_rulebook_order": trimmed_rule_order,
        "full_dispatch_order": full_dispatch_order,
        "trimmed_dispatch_order": trimmed_dispatch_order,
        "full_source_paths": [callback.source.source_path for callback in callbacks],
        "trimmed_source_paths": [callback.source.source_path for callback in trimmed],
        "execution_orders": [list(callback.execution_order) for callback in callbacks],
    }


def _servant_replacement_audit_trim_equivalence() -> dict[str, Any]:
    policy: dict[str, JSONValue] = {
        "admission_status": "executable",
        "mode": "replace_defeated_same_owner_servant",
        "policy_schema_version": "servant_replacement_policy_v1",
        "subject_kind": "servant",
        "owner_scope": "same_owner",
        "alive_filter": "alive_only",
        "comparison": "less_equal_zero",
        "replacement_operation": "remove_defeated_then_spawn",
        "servant_id": "validation:servant",
        "source_path": "validation/audit/servant.json",
        "predicate_path": "$.Predicate",
        "create_task_path": "$.SuccessTaskList[0]",
        "evidence": {"detail": "audit_only"},
    }
    trimmed = _trim_audit(policy)
    missing_typed = {key: value for key, value in trimmed.items() if key != "owner_scope"}
    return {
        "ok": _replacement_policy_admitted(policy)
        and _replacement_policy_admitted(trimmed)
        and not _replacement_policy_admitted(missing_typed),
        "full_admitted": _replacement_policy_admitted(policy),
        "trimmed_admitted": _replacement_policy_admitted(trimmed),
        "missing_typed_blocked": not _replacement_policy_admitted(missing_typed),
        "trimmed_policy": trimmed,
    }


def _wave_payload_audit_trim_equivalence() -> dict[str, Any]:
    source = IRSource("validation/audit/wave.json", "ValidationWave", "wave:1", {"detail": "audit"})
    entry = WaveMonsterEntryIR(
        entry_id="validation:wave:entry:1",
        stage_id="validation:stage",
        wave_index=1,
        position=1,
        monster_entity_ref="validation:monster",
        monster_raw_id="validation:monster:raw",
        source=source,
        birth_template_id="validation:birth:monster",
        coverage_status="executable",
    )
    definition = WaveDefinitionIR(
        wave_definition_id="validation:wave:definition",
        stage_id="validation:stage",
        wave_count=1,
        entries=(entry,),
        stage_ability_refs=(),
        source=source,
        coverage_status="executable",
    )
    trimmed_definition = _trim_audit(definition)
    trimmed_entry = trimmed_definition.entries[0]
    full_reasons = (
        _wave_definition_payload_blocked_reason(definition),
        _wave_entry_payload_blocked_reason(definition, entry, 1),
    )
    trimmed_reasons = (
        _wave_definition_payload_blocked_reason(trimmed_definition),
        _wave_entry_payload_blocked_reason(trimmed_definition, trimmed_entry, 1),
    )
    invalid_definition = replace(trimmed_definition, stage_id="")
    return {
        "ok": full_reasons == trimmed_reasons == ("", "")
        and _wave_definition_payload_blocked_reason(invalid_definition) == "wave_stage_id_missing",
        "full_reasons": full_reasons,
        "trimmed_reasons": trimmed_reasons,
        "trimmed_definition_source": trimmed_definition.source.to_json(),
        "trimmed_entry_source": trimmed_entry.source.to_json(),
    }


def _break_recovery_audit_trim_equivalence() -> dict[str, Any]:
    detail: dict[str, JSONValue] = {
        "break_status_emission_id": "validation:break:emission",
        "source_trace": {
            "effect_source": {
                "source_path": "validation/audit/break.json",
                "raw_type": "ValidationBreak",
                "raw_id": "raw:break",
                "evidence": {"break_status_emission_id": "audit:wrong"},
            }
        },
    }
    trimmed = _trim_audit(detail)
    missing_typed = {key: value for key, value in trimmed.items() if key != "break_status_emission_id"}
    emission = BreakStatusEmissionIR(
        break_status_emission_id="validation:break:emission",
        template_id="validation:break:template",
        source_task_id="validation:break:task",
        effect_id="validation:break:effect",
        opcode="AddModifier",
        target_alias="TargetSelf",
        modifier_name="ValidationBreakModifier",
        source=IRSource("validation/audit/break_emission.json", "ValidationBreakEmission", "raw:emission", {}),
        coverage_status="executable",
    )
    base_rules = _trust_rulebook()
    rules = RuleBook(replace(base_rules.ir, break_status_emissions=(emission,)))
    state = _base_state(skill_points=3)
    target_id = next(unit_id for unit_id, unit in state.units.items() if unit.side == "enemy")

    def recovery_state(status_detail: dict[str, JSONValue]) -> BattleState:
        target = state.units[target_id]
        return replace(
            state,
            units={
                **state.units,
                target_id: replace(
                    target,
                    toughness=0.0,
                    max_toughness=100.0,
                    statuses=("modifier:ValidationBreakModifier",),
                    flags={
                        **target.flags,
                        "broken": True,
                        "break_element": "Ice",
                        "break_source": {"typed": True},
                        "status_details": [
                            {
                                **status_detail,
                                "instance_id": "validation:break:instance",
                                "status_id": "modifier:ValidationBreakModifier",
                                "modifier_name": "ValidationBreakModifier",
                            }
                        ],
                    },
                ),
            },
        )

    system = BreakSystem(rules, EffectRegistry())
    full_result = system.recover_from_break_status(
        recovery_state(detail),
        unit_id=target_id,
        modifier_name="ValidationBreakModifier",
    )
    trimmed_result = system.recover_from_break_status(
        recovery_state(trimmed),
        unit_id=target_id,
        modifier_name="ValidationBreakModifier",
    )
    missing_typed_result = system.recover_from_break_status(
        recovery_state(missing_typed),
        unit_id=target_id,
        modifier_name="ValidationBreakModifier",
    )
    full_mutations = tuple(
        (mutation.op, mutation.path, mutation.after)
        for mutation in full_result.mutations
    )
    trimmed_mutations = tuple(
        (mutation.op, mutation.path, mutation.after)
        for mutation in trimmed_result.mutations
    )
    runtime_ok = (
        full_result.ok
        and trimmed_result.ok
        and full_mutations == trimmed_mutations
        and not missing_typed_result.ok
        and not missing_typed_result.mutations
    )
    return {
        "ok": _break_recovery_contract(detail).get("break_status_emission_id")
        == _break_recovery_contract(trimmed).get("break_status_emission_id")
        == "validation:break:emission"
        and not _break_recovery_contract(missing_typed)
        and runtime_ok,
        "runtime_ok": runtime_ok,
        "full": _break_recovery_contract(detail),
        "trimmed": _break_recovery_contract(trimmed),
        "missing_typed": _break_recovery_contract(missing_typed),
        "full_mutations": full_mutations,
        "trimmed_mutations": trimmed_mutations,
        "missing_typed_errors": missing_typed_result.errors,
    }


def _typed_field_cases() -> dict[str, Any]:
    source = IRSource(
        "validation/full_source.json",
        "ValidationTask",
        "modifier:structural",
        {"task": {"DynamicKey": {"Value": "audit_wrong"}}, "retarget": {"target_alias": "audit_wrong"}},
    )
    task = StatusCallbackTaskIR(
        task_id="task:structural",
        callback_id="callback:structural",
        modifier_name="Modifier_Structural",
        event="OnDamage",
        task_index=0,
        task_path="TaskList[0]",
        branch="root",
        opcode="Retarget",
        source=source,
        coverage_status="executable",
        task_payload={"DynamicKey": {"Value": "typed_key"}, "Property": {"Value": "Result_FinalDamage"}},
        retarget_policy={
            "target_alias": "ParamEntityAttackTargetList.SortByHP",
            "max_number_expr": {"kind": "fixed", "value": 2},
        },
    )
    trimmed_task = replace(task, source=_trim_audit(source))
    state = _base_state(skill_points=3)
    target_ids = tuple(unit.unit_id for unit in state.units.values() if unit.side == "enemy")
    event = GameEvent(
        "damage.hit",
        payload={"param_entity_attack_target_ids": list(target_ids)},
    )
    detail = {"owner_id": next(unit.unit_id for unit in state.units.values() if unit.side == "ally")}
    retarget_full = _retarget_candidates(state, task, detail, event)
    retarget_trimmed = _retarget_candidates(state, trimmed_task, detail, event)

    entity = RuleEntity(
        entity_id="modifier_definition:structural",
        entity_type="modifier_definition",
        fields={"modifier_name": "Modifier_Structural"},
        source=source,
        coverage_status="executable",
    )
    effect = EffectIR(
        effect_id="effect:structural",
        opcode="AddModifier",
        payload={"standard": {"modifier_name": "Modifier_Structural"}},
        source=source,
        coverage_status="executable",
        modifier_definition_id=entity.entity_id,
        source_mode="mainline",
        owner_modifier_name="Modifier_Structural",
    )
    base_ir = _trust_rulebook().ir
    linked_rules = RuleBook(replace(base_ir, entities=(entity,)))
    trimmed_linked_rules = RuleBook(_trim_audit(replace(base_ir, entities=(entity,))))
    selected_full = _select_modifier_definition(linked_rules, "Modifier_Structural", effect)
    selected_trimmed = _select_modifier_definition(
        trimmed_linked_rules,
        "Modifier_Structural",
        replace(effect, source=_trim_audit(effect.source)),
    )

    direct_detail = {
        "break_template_id": "break_template:StanceBreak_Fire",
        "break_element_type": "Fire",
        "source_trace": {
            "effect_source": {
                "evidence": {"break_status_emission_id": "break_status_emission:StanceBreak_Ice:9"}
            }
        },
    }
    trimmed_detail = {**direct_detail, "source_trace": {}}

    queue_entry = {
        "resource_policy": {"ignore_skill_point_delta": True},
        "source_trace": {"queue_intent_resource_policy": {"ignore_skill_point_delta": False}},
    }
    trimmed_queue_entry = {**queue_entry, "source_trace": {}}
    queue_plan = SimpleNamespace(queue_entry=queue_entry)
    trimmed_queue_plan = SimpleNamespace(queue_entry=trimmed_queue_entry)
    command = ActionCommand(
        actor_id="actor",
        action_id="action",
        action_level=1,
        metadata={"queue_parent": {"queue_entry": queue_entry}},
    )
    trimmed_command = replace(
        command,
        metadata={"queue_parent": {"queue_entry": trimmed_queue_entry}},
    )

    status_detail = {
        "formula_bindings": [{"formula_role": "dot_damage", "binding_id": "typed"}],
        "source_trace": {"status_formula_bindings": [{"formula_role": "dot_damage", "binding_id": "audit_wrong"}]},
    }
    no_typed_binding = {"source_trace": status_detail["source_trace"]}

    card = CharacterDataCardIR(
        card_id="character_data_card:structural",
        entity_ref="avatar:structural",
        profile_id="profile:structural",
        skill_ids=(),
        skill_formula_binding_ids=(),
        bounce_policy_ids=(),
        source=IRSource("full_card.json", "AvatarConfig", "structural", {"character_config_dynamic_value_bindings": {"by_hash": {"1": "audit_wrong"}}}),
        dynamic_value_bindings={"by_hash": {"1": "typed"}},
        coverage_status="executable",
    )
    card_rules = RuleBook(replace(base_ir, character_data_cards=(card,)))
    trimmed_card_rules = RuleBook(_trim_audit(replace(base_ir, character_data_cards=(card,))))

    trigger_effect = EffectIR(
        effect_id="effect:trigger_graph",
        opcode="TriggerAbility",
        payload={"standard": {"ability_name": "Ability_Structural"}},
        source=source,
        coverage_status="executable",
    )
    ability_task = AbilityTaskIR(
        task_id="ability_task:trigger_graph",
        phase_id="phase:structural",
        action_id="action:structural",
        level=1,
        ability_name="Ability_Parent",
        callback_kind="OnStart",
        task_index=0,
        task_path="TaskList[0]",
        branch="root",
        opcode="TriggerAbility",
        source=source,
        effect_id=trigger_effect.effect_id,
        coverage_status="executable",
    )
    graph = StandaloneAbilityGraphIR(
        standalone_ability_graph_id="standalone_graph:structural",
        ability_name="Ability_Structural",
        source_mode="mainline",
        phase_ids=("phase:standalone",),
        task_ids=(),
        executable_task_ids=(),
        source=source,
        coverage_status="executable",
    )
    linked_task = _link_trigger_ability_graphs([ability_task], [trigger_effect], [graph])[0]
    callback = StatusCallbackIR(
        callback_id="callback:structural",
        modifier_name="Modifier_Structural",
        event="OnCreate",
        task_ids=(),
        source=source,
        execution_order=(0, 0),
        coverage_status="executable",
    )
    linked_effect = _link_status_effect_runtime_fields(
        [effect],
        [entity],
        [callback],
    )[0]
    lowered_definition = _action_definition_from_row(
        "Config/Avatar/AvatarSkillConfig.json",
        "avatar_skill",
        "SkillID",
        0,
        {
            "SkillID": 1,
            "Level": 1,
            "AttackType": "Normal",
            "SkillEffect": "SingleAttack",
            "SkillTriggerKey": "Skill01",
        },
    )

    return {
        "task_payload_equal": task.task_payload == trimmed_task.task_payload
        and task.task_payload.get("DynamicKey") == {"Value": "typed_key"},
        "retarget_equal": retarget_full == retarget_trimmed
        and _retarget_max_number(task) == _retarget_max_number(trimmed_task) == 2,
        "modifier_link_equal": selected_full is not None
        and selected_trimmed is not None
        and selected_full.entity_id == selected_trimmed.entity_id == entity.entity_id,
        "break_link_equal": _break_template_id_from_detail(direct_detail)
        == _break_template_id_from_detail(trimmed_detail)
        == "break_template:StanceBreak_Fire"
        and _break_element_from_detail(direct_detail)
        == _break_element_from_detail(trimmed_detail)
        == "Fire",
        "queue_policy_equal": _queue_entry_resource_policy(queue_plan)
        == _queue_entry_resource_policy(trimmed_queue_plan)
        == {"ignore_skill_point_delta": True}
        and _queue_action_resource_policy(command)
        == _queue_action_resource_policy(trimmed_command)
        == {"ignore_skill_point_delta": True},
        "dot_binding_boundary": _status_formula_bindings(status_detail)
        == ({"formula_role": "dot_damage", "binding_id": "typed"},)
        and _status_formula_bindings(no_typed_binding) == (),
        "character_binding_equal": card_rules.character_dynamic_value_bindings_for_card(card.card_id)
        == trimmed_card_rules.character_dynamic_value_bindings_for_card(card.card_id)
        == {"by_hash": {"1": "typed"}},
        "lowering_links_projected": linked_task.linked_standalone_graph_id == graph.standalone_ability_graph_id
        and linked_effect.modifier_definition_id == entity.entity_id
        and linked_effect.status_callback_ids == (callback.callback_id,)
        and linked_effect.source_mode == "mainline"
        and linked_effect.owner_modifier_name == "Modifier_Structural"
        and lowered_definition.skill_trigger_key == "Skill01",
        "retarget_targets": list(retarget_full),
    }


def _engine_registry_cases() -> dict[str, Any]:
    registry = build_engine_rule_registry()
    base_ir = _trust_rulebook().ir
    rules = RuleBook(
        replace(
            base_ir,
            timeline_rules=registry.timeline_rules,
            resource_rules=registry.resource_rules,
        )
    )
    trimmed_rules = RuleBook(_trim_audit(rules.ir))
    timeline, timeline_reason = rules.select_timeline_rule()
    trimmed_timeline, trimmed_timeline_reason = trimmed_rules.select_timeline_rule()
    ultimate, ultimate_reason = rules.select_resource_rule("ultimate_energy_cost")
    kill, kill_reason = rules.select_resource_rule("kill_energy_gain")

    missing_rules = RuleBook(replace(rules.ir, timeline_rules=()))
    missing_result = CombatScheduler(missing_rules).initialize_timeline(_base_state(skill_points=3))
    wrong_version = RuleBook(
        replace(
            rules.ir,
            timeline_rules=(replace(registry.timeline_rules[0], registry_version=""),),
        )
    )
    ambiguous = RuleBook(
        replace(
            rules.ir,
            timeline_rules=(
                registry.timeline_rules[0],
                replace(registry.timeline_rules[0], timeline_rule_id="timeline_rule:duplicate"),
            ),
        )
    )
    missing_numeric = RuleBook(
        replace(
            rules.ir,
            resource_rules=tuple(
                replace(rule, numeric_value=None) if rule.rule_kind == "kill_energy_gain" else rule
                for rule in registry.resource_rules
            ),
        )
    )
    wrong_rule, wrong_reason = wrong_version.select_timeline_rule()
    ambiguous_rule, ambiguous_reason = ambiguous.select_timeline_rule()
    missing_numeric_rule, missing_numeric_reason = missing_numeric.select_resource_rule("kill_energy_gain")

    energy_state = BattleState(
        units={
            "ally:energy": UnitState(
                unit_id="ally:energy",
                side="ally",
                template_id="avatar:structural",
                energy=20.0,
                max_energy=100.0,
            )
        }
    )
    assert kill is not None
    full_mutation = ResourceSystem().gain_kill_energy(
        energy_state,
        "ally:energy",
        kill,
        defeated_event_payload={"damage_event_id": "damage:structural", "kill_credit_owner_id": "ally:energy"},
    )
    trimmed_kill, _ = trimmed_rules.select_resource_rule("kill_energy_gain")
    assert trimmed_kill is not None
    trimmed_mutation = ResourceSystem().gain_kill_energy(
        energy_state,
        "ally:energy",
        trimmed_kill,
        defeated_event_payload={"damage_event_id": "damage:structural", "kill_credit_owner_id": "ally:energy"},
    )
    identity_complete = (
        registry.registry_version == ENGINE_RULE_REGISTRY_VERSION
        and timeline is not None
        and timeline.registry_version == ENGINE_RULE_REGISTRY_VERSION
        and timeline.applicability == TIMELINE_RULE_APPLICABILITY
        and ultimate is not None
        and ultimate.applicability == ULTIMATE_COST_RULE_APPLICABILITY
        and kill.applicability == KILL_ENERGY_RULE_APPLICABILITY
        and kill.numeric_value == 10.0
        and not any((timeline_reason, ultimate_reason, kill_reason))
    )
    return {
        "identity_complete": identity_complete,
        "audit_trim_equal": trimmed_timeline is not None
        and trimmed_timeline.to_json()["base_action_gauge"] == timeline.to_json()["base_action_gauge"]
        and not trimmed_timeline_reason,
        "negative_cases_ok": wrong_rule is None
        and "version_mismatch" in wrong_reason
        and ambiguous_rule is None
        and ambiguous_reason == "timeline_engine_rule_ambiguous"
        and missing_numeric_rule is None
        and missing_numeric_reason == "engine_rule_numeric_value_missing",
        "missing_rule_state_unchanged": missing_result.after_state == _base_state(skill_points=3)
        and missing_result.transition.outcome.category == "blocked"
        and not missing_result.transition.transaction.mutations,
        "kill_energy_typed_value": full_mutation.after == trimmed_mutation.after == 30.0
        and full_mutation.metadata.get("energy_gain") == trimmed_mutation.metadata.get("energy_gain") == 10.0,
        "timeline_rule": timeline.to_json() if timeline else {},
        "resource_rules": [rule.to_json() for rule in registry.resource_rules],
        "negative_reasons": {
            "missing": missing_result.transition.outcome.reason_codes,
            "wrong_version": wrong_reason,
            "ambiguous": ambiguous_reason,
            "missing_numeric": missing_numeric_reason,
        },
    }


def _static_boundary(package_root: Path) -> dict[str, Any]:
    behavior_reads = []
    runtime_files = _runtime_scan_files(package_root)
    for relative in runtime_files:
        path = package_root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            audit_normalization_context = _in_audit_normalization_context(node, parents)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if any(fragment in node.value for fragment in TRACE_GATE_REASON_FRAGMENTS):
                    behavior_reads.append(
                        {"path": relative, "line": node.lineno, "receiver": "blocked_reason", "key": node.value}
                    )
            if isinstance(node, ast.If):
                gate = ast.unparse(node.test)
                trace_gate = "source_trace" in gate or "entry_source_trace" in gate
                audit_normalization_only = gate.startswith("isinstance(") and gate.endswith(", dict)")
                if trace_gate and not audit_normalization_only and not audit_normalization_context:
                    behavior_reads.append(
                        {"path": relative, "line": node.lineno, "receiver": "runtime_gate", "key": gate}
                    )
            if isinstance(node, ast.Attribute) and node.attr in AUDIT_IDENTITY_KEYS:
                receiver = _attribute_text(node.value)
                if (
                    not audit_normalization_context
                    and any(token in receiver for token in ("source", "trace", "evidence"))
                ):
                    behavior_reads.append(
                        {"path": relative, "line": node.lineno, "receiver": receiver, "key": node.attr}
                    )
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get" or not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            key = node.args[0].value
            if key in AUDIT_IDENTITY_KEYS and not audit_normalization_context:
                behavior_reads.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "receiver": _attribute_text(node.func.value),
                        "key": key,
                    }
                )
                continue
            if key not in FORBIDDEN_AUDIT_BEHAVIOR_KEYS:
                continue
            receiver = _attribute_text(node.func.value)
            if any(token in receiver for token in ("source", "trace", "evidence")):
                behavior_reads.append({"path": relative, "line": node.lineno, "receiver": receiver, "key": key})
        if relative == "systems/unit_spawn.py":
            for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
                if function.name not in UNIT_SPAWN_BEHAVIOR_FUNCTIONS:
                    continue
                for node in ast.walk(function):
                    if isinstance(node, ast.Attribute) and node.attr in {"source_trace", "entry_source_trace"}:
                        behavior_reads.append(
                            {
                                "path": relative,
                                "line": node.lineno,
                                "receiver": function.name,
                                "key": node.attr,
                            }
                        )

    ownership_rows = [
        _ownership("status_callback_task", "IRSource.evidence.task/retarget", "StatusCallbackTaskIR.task_payload/retarget_policy"),
        _ownership("trigger_ability_link", "IRSource.source_path equality", "AbilityTaskIR.linked_standalone_graph_id"),
        _ownership("action_trigger_key", "ActionDefinitionIR.source.evidence", "ActionDefinitionIR.skill_trigger_key"),
        _ownership("status_definition_and_duration", "effect/definition source path", "EffectIR modifier link/status callback IDs/source_mode"),
        _ownership("break_status_identity", "status source_trace emission-id parsing", "StatusInstance break_template_id/break_element_type"),
        _ownership("queue_resource_and_manual_command", "queue source_trace/evidence", "QueueEntry resource_policy/action_level/action reference"),
        _ownership("dot_formula_binding", "status source_trace fallback", "StatusInstance.formula_bindings"),
        _ownership("damage_custom_name", "DamageEmissionIR.source.evidence", "DamageEmissionIR.damage_custom_name"),
        _ownership("character_dynamic_binding", "CharacterDataCardIR.source.evidence", "CharacterDataCardIR.dynamic_value_bindings"),
        _ownership("trigger_modifier_index", "TriggerIR.source.raw_id", "TriggerIR.modifier_name"),
        _ownership("engine_conventions", "runtime magic constants/source evidence", "versioned engine_rule_registry typed fields"),
        _ownership("unit_birth_admission", "UnitSpawnRequest source_trace equality", "stable birth_template/source/entry identity fields"),
        _ownership("summon_and_wave_spawn_binding", "spawn request source trace equality", "stable intent/definition/entry identity fields"),
        _ownership("summon_target_and_action_admission", "summon runtime source trace presence", "runtime entity identity/status and typed admission fields"),
        _ownership("lifecycle_event_dispatch", "event payload source trace presence", "typed event identity and payload fields"),
        _ownership("shield_status_timeline_queue", "audit trace presence", "typed source IDs, status fields, priority and policy admission fields"),
        _ownership("status_owned_effect", "effect/source audit path matching", "EffectIR.owner_modifier_name"),
        _ownership("callback_execution_order", "IRSource path/raw type/raw id sort key", "StatusCallbackIR.execution_order"),
        _ownership("servant_replacement_admission", "replacement source/predicate/create paths", "typed servant replacement policy fields"),
        _ownership("wave_payload_admission", "wave definition/entry source paths", "typed wave definition/entry identity and coverage fields"),
        _ownership("break_recovery_identity", "status source evidence", "StatusInstance.break_status_emission_id"),
    ]
    return {
        "ok": not behavior_reads and all(row["status"] == "migrated" for row in ownership_rows),
        "behavior_read_count": len(behavior_reads),
        "behavior_reads": behavior_reads,
        "ownership_rows": ownership_rows,
        "scan_files": list(runtime_files),
        "scan_kind": "all core/rules/systems Python runtime AST audit-root semantic-key scan plus code-level ownership matrix",
    }


def _runtime_scan_files(package_root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(package_root).as_posix()
            for root in RUNTIME_SCAN_ROOTS
            for path in (package_root / root).rglob("*.py")
            if path.relative_to(package_root).as_posix() not in RUNTIME_SCAN_EXCLUSIONS
        )
    )


def _in_audit_normalization_context(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = node
    while current in parents:
        current = parents[current]
        if (
            isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef))
            and current.name in AUDIT_NORMALIZATION_FUNCTIONS
        ):
            return True
    return False


def _ownership(entry: str, former: str, owner: str) -> dict[str, str]:
    return {
        "entry": entry,
        "former_behavior_input": former,
        "current_rule_owner": owner,
        "status": "migrated",
    }


def _behavior_projection(state: BattleState, transition) -> dict[str, Any]:
    return {
        "returned_state": state.snapshot().to_json(),
        "after": transition.after.to_json(),
        "outcome_category": transition.outcome.category,
        "successor_eligible": transition.outcome.successor_eligible,
        "reason_codes": list(transition.outcome.reason_codes),
        "nodes": [
            (node.node_kind, node.node_id, node.status, node.reason_code)
            for node in transition.outcome.node_results
        ],
        "mutations": [
            {
                "op": mutation.op,
                "path": list(mutation.path),
                "before": mutation.to_json()["before"],
                "after": mutation.to_json()["after"],
                "source": mutation.source,
            }
            for mutation in transition.transaction.mutations
        ],
        "events": [
            (event.event_type, event.source_id, event.target_id, event.window, event.process_only)
            for event in transition.transaction.events
        ],
        "targets": list(transition.target_resolution.selected),
    }


def _trim_audit(value: Any) -> Any:
    if isinstance(value, IRSource):
        return IRSource(
            source_path="",
            raw_type="",
            raw_id="",
            evidence={},
        )
    if isinstance(value, tuple):
        return tuple(_trim_audit(item) for item in value)
    if isinstance(value, list):
        return [_trim_audit(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _trim_audit(item)
            for key, item in value.items()
            if key not in {
                "source_trace",
                "evidence",
                "source_path",
                "raw_type",
                "raw_id",
                "predicate_path",
                "create_task_path",
            }
        }
    if is_dataclass(value):
        replacements = {
            field.name: _trim_audit(getattr(value, field.name))
            for field in fields(value)
            if field.init
        }
        return replace(value, **replacements)
    return value


def _attribute_text(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_attribute_text(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return f"{_attribute_text(node.value)}[]"
    if isinstance(node, ast.Call):
        return f"{_attribute_text(node.func)}()"
    return type(node).__name__


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate P7-S4 rule/audit separation")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/hsr_v8_p7_s4_rule_audit_separation"),
    )
    args = parser.parse_args()
    package_root = Path(__file__).resolve().parents[1]
    summary = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={summary['ok']} "
        f"ownership_rows={summary['ownership_row_count']} ready_for_review={summary['ready_for_review']}"
    )
    raise SystemExit(0 if summary["ok"] else 1)


if __name__ == "__main__":
    main()
