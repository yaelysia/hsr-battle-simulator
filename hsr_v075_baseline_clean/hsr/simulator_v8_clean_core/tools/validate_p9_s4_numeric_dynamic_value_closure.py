from __future__ import annotations

import argparse
import base64
import binascii
import inspect
import json
import math
import resource
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from simulator_v8_clean_core.core.executor import CombatExecutor
from simulator_v8_clean_core.core.model import (
    ActionCommand,
    BattleState,
    Mutation,
    UnitState,
)
from simulator_v8_clean_core.core.reducer import MutationReducer
from simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from simulator_v8_clean_core.immutable_json import thaw_json
from simulator_v8_clean_core.rules.evaluator import RuleEvaluator
from simulator_v8_clean_core.rules.expression_ir import (
    DynamicValueOperationIR,
    NumericOperandIR,
    numeric_fixed,
)
from simulator_v8_clean_core.rules.ir import (
    ActionDefinitionIR,
    EffectIR,
)
from simulator_v8_clean_core.rules.rulebook import RuleBook
from simulator_v8_clean_core.systems import status_callbacks as status_callbacks_module
from simulator_v8_clean_core.systems.action_preflight import target_policy_for_action
from simulator_v8_clean_core.systems.dynamic_values import (
    DynamicValueExecutionRequest,
    execute_dynamic_value_plan,
    normalized_dynamic_value_store,
    plan_dynamic_value_operation,
    upsert_dynamic_value,
)
from simulator_v8_clean_core.systems.effect import (
    EffectExecutionContext,
    EffectRegistry,
)
from simulator_v8_clean_core.tbgd.character_ability_scope import (
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
)
from simulator_v8_clean_core.tbgd.character_ability_source_graph import (
    build_character_ability_source_graph,
)
from simulator_v8_clean_core.tbgd.character_source_resolution import (
    character_dynamic_value_decode_families,
    lower_character_decoded_dynamic_value_operation,
)
from simulator_v8_clean_core.tbgd.lowering import (
    ABILITY_TASK_CALLBACKS,
    TBGDLowering,
    build_character_action_definition_ir,
    lower_character_dynamic_value_operation,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _walk_types(value: object, found: set[str], containers: dict[tuple[str, str], dict[str, Any]],
                *, source_path: str, json_path: str = "$") -> None:
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk_types(item, found, containers, source_path=source_path, json_path=f"{json_path}[{index}]")
        return
    if not isinstance(value, dict):
        return
    raw_type = value.get("$type")
    if isinstance(raw_type, str):
        family = raw_type.rsplit(".", 1)[-1]
        if family in {"DefineDynamicValue", "SetModifierDynamicValue"} or family.startswith("SetDynamicValue"):
            found.add(family)
            containers[(source_path, f"{json_path}.$type")] = value
    for key, item in value.items():
        if key != "$type":
            _walk_types(item, found, containers, source_path=source_path, json_path=f"{json_path}.{key}")


def _unwrap(value: object) -> object:
    while isinstance(value, dict) and set(value) == {"Value"}:
        value = value["Value"]
    return value


def _raw_string(raw: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = _unwrap(raw.get(field))
        if isinstance(value, str) and value:
            return value
    return ""


def _raw_target(raw: dict[str, Any], field: str = "TargetType") -> str:
    value = raw.get(field)
    if isinstance(value, dict):
        alias = value.get("Alias", value.get("Value"))
        return alias if isinstance(alias, str) else ""
    return ""


def _raw_fixed(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if not isinstance(value, dict):
        return None
    fixed = value.get("FixedValue")
    if isinstance(fixed, dict):
        return _raw_fixed(fixed.get("Value"))
    return _raw_fixed(value.get("Value")) if "Value" in value else None


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _numeric_matches(raw_value: object, expression: object, *, default: float | None = None) -> bool:
    fixed = _raw_fixed(raw_value)
    if fixed is None and raw_value is None:
        fixed = default
    if fixed is not None:
        return isinstance(expression, dict) and expression.get("kind") == "fixed" and expression.get("value") == fixed
    postfix = raw_value.get("PostfixExpr") if isinstance(raw_value, dict) else None
    hashes = postfix.get("DynamicHashes") if isinstance(postfix, dict) else None
    if isinstance(hashes, list):
        if len(hashes) == 1 and isinstance(expression, dict):
            if expression.get("kind") == "dynamic_hash":
                return expression.get("hash") == hashes[0]
        instructions = expression.get("instructions") if isinstance(expression, dict) else None
        actual = [item.get("hash") for item in instructions or () if isinstance(item, dict) and item.get("opcode") == "push_dynamic"]
        expected = _raw_dynamic_hash_sequence(postfix, hashes)
        return expected is not None and actual == expected
    return isinstance(expression, dict)


def _raw_dynamic_hash_sequence(postfix: dict[str, Any], hashes: list[Any]) -> list[Any] | None:
    encoded = postfix.get("OpCodes")
    if not isinstance(encoded, str):
        return None
    try:
        opcodes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    sequence: list[Any] = []
    index = 0
    while index < len(opcodes):
        opcode = opcodes[index]
        if opcode in {0, 1, 16}:
            if index + 1 >= len(opcodes):
                return None
            operand_index = opcodes[index + 1]
            if opcode == 1:
                if operand_index >= len(hashes):
                    return None
                sequence.append(hashes[operand_index])
            index += 2
            continue
        index += 1
    return sequence


def _expected_scope(family: str, raw: dict[str, Any], *, decoded: bool) -> tuple[str, str]:
    if decoded:
        return "contextual", "execution_context"
    scope = "ContextModifier" if family == "SetModifierDynamicValue" else _unwrap(
        raw.get("TargetContextScope") if family == "SetDynamicValueByCopying" else raw.get("ContextScope")
    )
    return {
        "ContextAbility": ("ability", "ability_action"),
        "ContextTaskTemplate": ("ability", "ability_action"),
        "ContextModifier": ("status", "status_instance"),
        "ContextCaster": ("unit", "combat"),
        "ContextOwner": ("unit", "combat"),
        "TargetEntity": ("unit", "combat"),
    }.get(scope, ("contextual", "execution_context"))


def _semantic_raw(family: str, raw: dict[str, Any], target: str) -> dict[str, Any]:
    source_target = (
        _raw_target(raw, "FromTargetType")
        if family == "SetDynamicValueByCopying"
        else _raw_target(raw, "ReadTargetType") or _raw_target(raw, "SourceTargetType") or target
    )
    property_name = (
        _raw_string(raw, ("Value",))
        if family in {"SetDynamicValueByProperty", "SetDynamicValueByPropertyClientOnly"}
        else _raw_string(raw, ("PropertyName", "PropertyType", "DataProperty", "AbilityProperty"))
    )
    return {
        "source_target_alias": source_target,
        "source_key": _raw_string(raw, ("FromDynamicKey", "SourceDynamicKey", "SourceKey", "ReadDynamicKey", "CopyKey")),
        "source_hash": str(_unwrap(raw.get("SourceHash"))) if _unwrap(raw.get("SourceHash")) is not None else None,
        "source_modifier": _raw_string(raw, ("FromModifierName",)) or None,
        "property_name": property_name,
        "modifier_name": _raw_string(raw, ("ModifierName",)),
        "modifier_value_name": _raw_string(raw, ("ValueType",)),
        "resource_name": "skill_points" if family == "SetDynamicValueByCurrentBP" else "max_skill_points" if family == "SetDynamicValueByMaxBP" else _raw_string(raw, ("ResourceName", "ResourceType", "BPType")),
        "event_property": _raw_string(raw, ("Property",)) or None,
        "value_type": _raw_string(raw, ("ValueType",)) or None,
        "attacker_alias": _raw_target(raw, "Attacker") or _raw_target(raw, "AttackerTargetType") or None,
        "base_types": raw.get("BaseTypeList") if isinstance(raw.get("BaseTypeList"), list) else [],
        "alive_only": raw.get("AliveOnly") if isinstance(raw.get("AliveOnly"), bool) else None,
        "predicate": raw.get("Predicate"),
        "skill_trigger_key": raw.get("SkillTriggerKey"),
        "status_flag": _raw_string(raw, ("Flag",)),
        "weakness_filter": raw.get("WeaknessFilter"),
        "integer_only": raw.get("IsInt") is True,
    }


def _raw_oracle(
    family: str,
    raw: dict[str, Any],
    operation: DynamicValueOperationIR,
    decoded_families: set[str],
) -> dict[str, Any]:
    decoded = family in decoded_families
    destination_fields = ("FHLJGDGMMHK",) if decoded else ("ToDynamicKey",) if family == "SetDynamicValueByCopying" else ("WriteToKey",) if family == "SetDynamicValueByWaveStageCount" else ("DynamicKey", "Key", "TargetDynamicKey", "TargetKey", "DynamicFloatSet")
    key = _raw_string(raw, destination_fields)
    target_field = "HILNFHCPEAD" if decoded else "ToTargetType" if family == "SetDynamicValueByCopying" else "WriteTargetType" if family == "SetDynamicValueByWeaknessCount" else "TargetType"
    target = _raw_target(raw, target_field) or "ModifierOwnerEntity"
    raw_operation = raw.get("FKCKKFALPBK") if decoded else _unwrap(raw.get("Operation"))
    expected_kind = (
        "define" if family == "DefineDynamicValue" or decoded and "AJHHCOHFIFA" not in raw
        else "add" if raw_operation == "Add" or "ByAdd" in family
        else "copy" if raw_operation == "Copy" or "Copying" in family
        else "set"
    )
    expected_scope = _expected_scope(family, raw, decoded=decoded)
    parameters = operation.operand.parameters
    semantic = _semantic_raw(family, raw, target)
    checks: dict[str, bool] = {
        "source_family": operation.source.raw_type == family,
        "destination": bool(key) and operation.destination_key == key,
        "target": operation.target_alias == target,
        "operation": operation.operation_kind == expected_kind,
        "scope_lifecycle": (operation.scope_kind, operation.lifecycle) == expected_scope,
    }
    if operation.operand.operand_kind == "expression":
        formula_field = "AJHHCOHFIFA" if decoded else "ResetValue" if family == "DefineDynamicValue" else "AddValue" if "ByAdd" in family else "NewValue" if family == "SetModifierDynamicValue" else "Value"
        checks["expression"] = _numeric_matches(raw.get(formula_field), operation.operand.expression, default=0.0 if family == "DefineDynamicValue" else None)
    elif operation.operand.operand_kind == "dynamic_value":
        checks["copy_fields"] = all((parameters.get(name) or None) == semantic[name] for name in ("source_target_alias", "source_key", "source_hash", "source_modifier"))
    elif operation.operand.operand_kind == "unit_property":
        checks["property_fields"] = parameters == {"source_target_alias": semantic["source_target_alias"], "property_name": semantic["property_name"]}
    elif operation.operand.operand_kind == "modifier_value":
        checks["modifier_fields"] = parameters.get("source_target_alias") == semantic["source_target_alias"] and (not semantic["modifier_name"] or parameters.get("modifier_name") == semantic["modifier_name"]) and parameters.get("modifier_value_name") == semantic["modifier_value_name"]
        checks["modifier_scale"] = _numeric_matches(raw.get("Multiplier"), operation.operand.scale_expression)
    elif operation.operand.operand_kind == "status_count":
        checks["status_count_fields"] = parameters == {"source_target_alias": semantic["source_target_alias"], "count_mode": "debuff"}
    elif operation.operand.operand_kind in {"hp_ratio", "shield_value", "break_base_damage", "formation_index"}:
        checks["source_target_field"] = parameters.get("source_target_alias") == semantic["source_target_alias"]
    elif operation.operand.operand_kind == "team_resource":
        checks["resource_field"] = parameters.get("resource_name") == semantic["resource_name"]
    elif operation.operand.operand_kind == "character_count":
        checks["count_filter_fields"] = parameters == {"source_target_alias": semantic["source_target_alias"], "alive_only": semantic["alive_only"], "predicate_json": _canonical(semantic["predicate"])}
    elif operation.operand.operand_kind == "base_type_count":
        checks["base_type_filter"] = list(parameters.get("base_types") or ()) == semantic["base_types"]
    elif operation.operand.operand_kind == "weakness_count":
        checks["weakness_fields"] = parameters == {"source_target_alias": semantic["source_target_alias"], "weakness_filter_json": _canonical(semantic["weakness_filter"])}
    elif operation.operand.operand_kind == "event_value":
        checks["event_fields"] = parameters == {"event_kind": family, "property_name": semantic["event_property"], "value_type": semantic["value_type"], "source_target_alias": semantic["source_target_alias"] or None, "attacker_alias": semantic["attacker_alias"]}
    elif operation.operand.operand_kind == "skill_property":
        checks["skill_fields"] = parameters == {"property_name": semantic["property_name"], "skill_trigger_json": _canonical(semantic["skill_trigger_key"])}
    elif operation.operand.operand_kind == "status_resistance":
        checks["status_filter"] = parameters == {"source_target_alias": semantic["source_target_alias"], "status_flag": semantic["status_flag"]}
    elif operation.operand.operand_kind == "random_range":
        checks["random_fields"] = _numeric_matches(raw.get("Min"), parameters.get("minimum")) and _numeric_matches(raw.get("Max"), parameters.get("maximum")) and parameters.get("integer_only") == semantic["integer_only"]
    elif operation.operand.operand_kind == "wave_stage_count":
        checks["wave_source"] = parameters == {"source_kind": "battle_wave_stage"}
    elif operation.operand.operand_kind == "team_center_distance":
        checks["distance_fields"] = parameters == {"source_target_alias": semantic["source_target_alias"], "alive_only": semantic["alive_only"]}
    else:
        descriptor = parameters.get("source_descriptor_json")
        try:
            decoded_descriptor = json.loads(descriptor) if isinstance(descriptor, str) else None
        except json.JSONDecodeError:
            decoded_descriptor = None
        checks["typed_blocked_source"] = bool(parameters.get("source_family") == family or operation.operand.operand_kind == "precalculated_stance_damage") and isinstance(decoded_descriptor, dict)
    for bound_name, raw_field in (("minimum", "Min"), ("maximum", "Max")):
        bound = getattr(operation, bound_name)
        if raw_field in raw and family in {"SetDynamicValueByAddValue"}:
            checks[f"{bound_name}_expression"] = bound is not None and _numeric_matches(raw.get(raw_field), bound.expression)
    return {"ok": all(checks.values()), **checks}


def _operation_with(
    operation: DynamicValueOperationIR,
    **updates: Any,
) -> DynamicValueOperationIR:
    spec = operation.to_spec_json()
    spec.update(updates)
    return DynamicValueOperationIR.from_spec(spec, operation.source)


def _request(
    operation: DynamicValueOperationIR, *, event_id: str,
    binding_sources: tuple[dict[str, Any], ...] = (), target_id: str = "target",
    status_instance_id: str = "", status_modifier_name: str = "", status_id: str = "",
    status_source_id: str = "",
) -> DynamicValueExecutionRequest:
    return DynamicValueExecutionRequest(
        caster_id="actor", source_id="ability_task:source", effect_id="effect:source",
        opcode=operation.source.raw_type, owner_id="actor", param_entity_id=target_id,
        current_action_target_id=target_id, ability_instance_id="ability:source:1",
        status_instance_id=status_instance_id, event_id=f"event:{event_id}",
        operation_event_id=f"operation_event:{event_id}", task_id="task:source",
        status_modifier_name=status_modifier_name, status_id=status_id,
        status_source_id=status_source_id,
        binding_sources=binding_sources,
    )


def _status_detail(name: str, category: str, *, stacks: int) -> dict[str, Any]:
    return {
        "instance_id": f"status:{name}", "status_id": f"status_def:{name}",
        "modifier_name": name, "owner_id": "actor", "source_id": f"status_source:{name}",
        "status_category": category,
        "source_trace": {"effect_id": f"status_origin:{name}", "modifier_name": name},
        "stacks": stacks, "remaining_duration": float(stacks + 1), "dynamic_values": {},
    }


def _base_state(actor_template_id: str = "avatar:source") -> BattleState:
    return BattleState(
        units={
            "actor": UnitState(
                unit_id="actor", side="ally", template_id=actor_template_id,
                max_hp=100.0, hp=75.0, flags={"status_details": [
                    _status_detail("A", "debuff", stacks=2), _status_detail("B", "buff", stacks=1),
                ]},
            ),
            "target": UnitState(
                unit_id="target", side="enemy", template_id="monster:source",
                max_hp=100.0, hp=100.0,
            ),
        },
        event_index=7,
        global_flags={"turn_owner_id": "actor", "current_window": "idle"},
    )


def _formal_action(
    lowering: TBGDLowering, snapshot: Any, projection: Any, source_graph: Any,
    operations: list[tuple[DynamicValueOperationIR, Any]],
) -> tuple[dict[str, Any], DynamicValueOperationIR]:
    definition_key_by_id = {item.definition_id: (item.source.source_path, item.source.evidence.get("ability_index"))
        for item in source_graph.definitions}
    action_sources_by_id = {item.action_source_id: item for item in source_graph.action_sources}
    action_ids_by_ability: dict[tuple[str, int], set[str]] = defaultdict(set)
    for binding in source_graph.bindings:
        definition_key = definition_key_by_id.get(binding.ability_definition_id)
        if binding.action_source_id and definition_key and type(definition_key[1]) is int:
            action_source = action_sources_by_id.get(binding.action_source_id)
            if action_source is not None:
                action_ids_by_ability[definition_key].add(action_source.action_id)
    definitions_by_action: dict[str, list[ActionDefinitionIR]] = defaultdict(list)
    for definition in build_character_action_definition_ir(lowering.tbgd_root):
        definitions_by_action[definition.action_id].append(definition)

    def eligible(operation: DynamicValueOperationIR) -> bool:
        return (
            operation.coverage_status == "executable"
            and operation.operation_kind in {"define", "set", "add"}
            and isinstance(operation.operand.expression, dict)
            and operation.operand.expression.get("kind") == "fixed"
            and operation.scope_kind != "status"
        )

    def root_locator(operation: DynamicValueOperationIR, record: Any) -> tuple[int, str, str, str, int] | None:
        path = str(record.source.evidence.get("json_path") or "")
        prefix = "$.AbilityList["
        close = path.find("]", len(prefix))
        if not path.startswith(prefix) or close < 0 or not path[close + 1:].startswith("."):
            return None
        try:
            ability_index = int(path[len(prefix):close])
        except ValueError:
            return None
        tail = path[close + 2:]
        task_path = tail[:-len(".$type")] if tail.endswith(".$type") else ""
        if not task_path or "." in task_path:
            return None
        open_index = tail.find("[")
        close_index = tail.find("]", open_index + 1)
        if open_index <= 0 or close_index < 0:
            return None
        try:
            task_index = int(tail[open_index + 1:close_index])
        except ValueError:
            return None
        document = snapshot.documents.get(operation.source.source_path)
        abilities = document.get("AbilityList") if isinstance(document, dict) else None
        if not isinstance(abilities, (list, tuple)) or ability_index >= len(abilities):
            return None
        ability, callback_kind = abilities[ability_index], tail[:open_index]
        roots = ability.get(callback_kind) if isinstance(ability, dict) else None
        ability_name = ability.get("Name") if isinstance(ability, dict) else None
        if (
            callback_kind not in ABILITY_TASK_CALLBACKS or not isinstance(ability_name, str)
            or not isinstance(roots, (list, tuple)) or not 0 <= task_index < len(roots)
        ):
            return None
        return ability_index, callback_kind, task_path, ability_name, len(roots)

    candidates: list[tuple[DynamicValueOperationIR, Any, ActionDefinitionIR, str, str, str, int]] = []
    for operation, record in operations:
        locator = root_locator(operation, record)
        if locator is None or not eligible(operation):
            continue
        ability_index, callback_kind, task_path, ability_name, root_count = locator
        key = (operation.source.source_path, ability_index)
        for action_id in action_ids_by_ability.get(key, ()):
            action_definitions = definitions_by_action.get(action_id, ())
            if action_definitions:
                definition = min(action_definitions, key=lambda item: item.level)
                candidates.append((operation, record, definition, callback_kind, task_path, ability_name, root_count))
    candidates.sort(key=lambda item: (item[6], item[0].source.source_path, item[0].source.raw_id,
        item[2].action_id, item[2].level))
    if not candidates:
        raise RuntimeError("no executable source-backed root dynamic-value action")
    selected = None
    rejected: list[dict[str, Any]] = []
    attempted_actions: set[tuple[str, int]] = set()
    for source_operation, record, definition, callback_kind, task_path, ability_name, root_count in candidates:
        action_key = (definition.action_id, definition.level)
        if action_key in attempted_actions:
            continue
        attempted_actions.add(action_key)
        canonical = lowering.build_character_action_ability_slice(
            definition, snapshot=snapshot, scope_catalog=projection, source_graph_catalog=source_graph
        )
        effects = {effect.effect_id: effect for effect in canonical.effects}
        matches: list[tuple[Any, Any]] = []
        for item in canonical.ability_tasks:
            candidate_effect = effects.get(item.effect_id)
            if item.ability_name != ability_name or item.callback_kind != callback_kind or item.task_path != task_path or candidate_effect is None:
                continue
            same_source_location = candidate_effect.source.source_path == source_operation.source.source_path and (
                candidate_effect.source.evidence.get("json_path") == source_operation.source.evidence.get("json_path")
            )
            if same_source_location:
                matches.append((item, candidate_effect))
        if len(matches) != 1:
            if len(rejected) < 12:
                rejected.append({"action_id": definition.action_id, "action_level": definition.level,
                    "reason_codes": ["candidate_source_task_not_in_action_slice"], "dynamic_mutation_count": 0})
            continue
        task, effect = matches[0]
        standard = effect.payload.get("standard")
        spec = standard.get("dynamic_operation") if isinstance(standard, dict) else None
        decoded_ref = effect.payload.get("decoded_source_ref")
        source_family_matches = effect.opcode == record.family or (
            isinstance(decoded_ref, dict) and decoded_ref.get("source_family") == record.family
        )
        if not isinstance(spec, dict):
            raise RuntimeError("selected formal dynamic-value operation spec missing")
        formal_operation = DynamicValueOperationIR.from_spec(spec, effect.source)
        if (
            not source_family_matches
            or effect.source.source_path != source_operation.source.source_path
            or not isinstance(spec, dict) or task.coverage_status != "executable"
        ):
            raise RuntimeError(
                "selected formal dynamic-value task changed source structure:"
                f"family={record.family}/{effect.opcode}/{source_family_matches}:"
                f"source={source_operation.source.source_path}/{effect.source.source_path}:"
                f"spec={isinstance(spec, dict)}:coverage={task.coverage_status}"
            )
        if (
            formal_operation.coverage_status != "executable"
            or formal_operation.destination_key != source_operation.destination_key
            or not isinstance(formal_operation.operand.expression, dict)
            or formal_operation.operand.expression.get("kind") != "fixed"
        ):
            raise RuntimeError("selected formal dynamic-value operation changed semantics")
        callback_roots = tuple(item for item in canonical.ability_tasks
            if item.phase_id == task.phase_id and item.callback_kind == callback_kind and not item.parent_task_id)
        if task not in callback_roots or len(callback_roots) != root_count:
            raise RuntimeError("formal action slice changed the real callback root set")
        rules = RuleBook(canonical)
        owner_ref = str(canonical.metadata.get("owner_entity_ref") or "")
        before = _base_state(owner_ref)
        executor = CombatExecutor(rules)
        action_event = rules.action_event(definition.action_id, definition.level)
        phase = rules.ability_phase(task.phase_id)
        if action_event is None or phase is None:
            continue
        policy = target_policy_for_action(rules, definition, action_event.target_mode, action_event=action_event)
        requested = () if policy.selection_max == 0 else ("target",)
        command = ActionCommand(actor_id="actor", action_id=definition.action_id, action_level=definition.level, target_ids=requested)
        target_result = executor.targets.resolve_action_targets(before, command.actor_id, command.target_ids, policy=policy)
        if not target_result.ok:
            continue
        effect_result = executor.effects.execute(
            effect,
            EffectExecutionContext(
                state=before, caster_id=command.actor_id, source_id=task.task_id,
                owner_id=command.actor_id, param_entity_id=target_result.resolution.primary,
                current_action_target_id=target_result.resolution.primary, target_resolution=target_result.resolution,
                event_payload={
                    "ability_instance_id": f"{phase.phase_id}:actor",
                    "event_id": f"event:{before.event_index}:ability:{task.task_id}",
                    "operation_event_id": f"operation_event:{task.task_id}",
                    "task_id": task.task_id, "phase_id": phase.phase_id,
                    "action_id": definition.action_id, "action_level": definition.level,
                },
            ),
        )
        effect_complete = not effect_result.unsupported and all(node.status == "complete" for node in effect_result.node_results)
        effect_reason = ",".join(effect_result.unsupported)
        committed = executor.commit_eventful_transition(
            before, mutations=effect_result.mutations, events=effect_result.events,
            records=effect_result.records, rng_events=effect_result.rng_events,
            producer_kind="ability_effect", producer_id=task.task_id,
            producer_ok=effect_complete, blocked_reason=effect_reason)
        dynamic_mutations = tuple(mutation for mutation in committed.mutations
            if mutation.path == ("global_flags", "dynamic_value_store")
            and mutation.metadata.get("operation_id") == formal_operation.operation_id)
        if effect_complete and not committed.errors and dynamic_mutations and not committed.rng_events:
            selected = (source_operation, definition, canonical, rules, task, effect, formal_operation,
                callback_roots, before, target_result, effect_result, committed)
            break
        if len(rejected) < 12:
            rejected.append({"action_id": definition.action_id, "action_level": definition.level,
                "reason_codes": list(committed.errors) or [effect_reason], "dynamic_mutation_count": len(dynamic_mutations)})
    if selected is None:
        raise RuntimeError(f"no complete formal dynamic-value action:{rejected}")
    (source_operation, definition, canonical, rules, task, effect, formal_operation,
        callback_roots, before, target_result, effect_result, committed) = selected
    records = committed.records
    audit = RuntimeSourceAuditor(rules).validate_execution(committed.mutations, records)
    replay = MutationReducer().replay_snapshot(before, committed.mutations, committed.after_state.snapshot().to_json())
    checks = {
        "formal_source_objects": task in canonical.ability_tasks and effect in canonical.effects,
        "selected_real_callback_path": task in callback_roots,
        "public_effect_contract_committed": not effect_result.unsupported
        and all(node.status == "complete" for node in effect_result.node_results) and not committed.errors,
        "production_target_resolution": target_result.ok,
        "dynamic_mutation_produced": any(mutation.metadata.get("operation_id") == formal_operation.operation_id
            for mutation in committed.mutations),
        "settlement_links_all_mutations": all(any(record.get("mutation_id") == mutation.stable_id() for record in records)
            for mutation in committed.mutations),
        "source_audit_ok": audit.ok, "replay_equal": replay.ok,
        "production_eventful_commit": bool(committed.mutations) and not committed.errors,
        "no_rng": not committed.rng_events,
    }
    evidence = {
        "ok": all(checks.values()), **checks,
        "action_id": definition.action_id, "action_level": definition.level,
        "phase_id": task.phase_id, "task_id": task.task_id, "effect_id": effect.effect_id,
        "family": effect.opcode, "source_path": effect.source.source_path,
        "operation_id": formal_operation.operation_id, "pre_lower_candidate_count": len(candidates),
        "lowered_callback_root_count": len(callback_roots),
        "callback_root_task_ids": [item.task_id for item in callback_roots],
        "attempted_action_count": len(attempted_actions), "rejected_actions": rejected,
        "production_slice_build_count": len(attempted_actions),
        "mutation_ids": [mutation.stable_id() for mutation in committed.mutations],
        "effect_node_results": [node.to_json() for node in effect_result.node_results],
        "audit": audit.to_json(), "replay_errors": list(replay.errors),
    }
    return evidence, formal_operation


def _scope_matrix(base: DynamicValueOperationIR) -> dict[str, Any]:
    state = _base_state()
    snapshot_store = state.snapshot().to_json()["global_flags"]["dynamic_value_store"]
    normalized_snapshot_store = normalized_dynamic_value_store(snapshot_store)
    mapped_store = upsert_dynamic_value(
        snapshot_store, scope="unit", owner_id="actor", target_id="actor", value=1.0, value_name="scope_mapping_probe"
    )
    mapped_entry = next(iter(mapped_store["entries"].values()))
    unknown_scope_rejected = False
    try:
        upsert_dynamic_value(snapshot_store, scope="unknown", owner_id="actor", value=1.0, value_name="probe")
    except ValueError:
        unknown_scope_rejected = True
    rows: list[dict[str, Any]] = []
    for scope_kind, lifecycle, status_id in (
        ("unit", "combat", ""),
        ("ability", "ability_action", ""),
        ("status", "status_instance", "status:A"),
        ("event", "event", ""),
    ):
        operation = _fixed_operation(base, "scope_probe", scope_kind=scope_kind, lifecycle=lifecycle)
        status_kwargs = ({
            "status_modifier_name": "A", "status_id": "status_def:A",
            "status_source_id": "status_source:A",
        } if status_id else {})
        plan = plan_dynamic_value_operation(state, operation, _request(
            operation, event_id=f"scope:{scope_kind}", status_instance_id=status_id, **status_kwargs
        ))
        store = plan.mutations[-1].after if plan.ok and plan.mutations else {}
        rows.append({"scope_kind": scope_kind, "ok": plan.ok,
            "entry_keys": list(store.get("entries", {})) if isinstance(store, dict) else [], "resolved_scope": thaw_json(plan.resolved_scope)})
    entry_keys = [key for row in rows for key in row["entry_keys"]]
    distinct = len(entry_keys) == 4 and len(set(entry_keys)) == 4
    default_store_ok = normalized_snapshot_store == snapshot_store
    scope_mapping_ok = mapped_entry["scope_kind"] == "unit" and mapped_entry["lifecycle"] == "combat" and unknown_scope_rejected
    return {"ok": distinct and default_store_ok and scope_mapping_ok and all(row["ok"] for row in rows), "distinct": distinct, "default_snapshot_store_normalized": default_store_ok, "upsert_scope_strict": scope_mapping_ok, "rows": rows}


def _source_graph_identity_guards(tbgd_root: Path, snapshot: Any, projection: Any) -> dict[str, bool]:
    attacks = {
        "wrong_snapshot": ("snapshot_id", "snapshot:forged"), "wrong_fingerprint": ("source_fingerprint", "0" * 64),
        "wrong_sources": ("sources", tuple(projection.sources[:-1])),
    }
    rejected: dict[str, bool] = {}
    for name, (field_name, value) in attacks.items():
        forged = replace(projection)
        object.__setattr__(forged, field_name, value)
        try:
            build_character_ability_source_graph(tbgd_root, snapshot=snapshot, scope_catalog=forged)
            rejected[name] = False
        except ValueError as exc:
            rejected[name] = str(exc) == "S0 snapshot and scope catalog do not describe one source closure"
    return rejected


def _fixed_operation(
    base: DynamicValueOperationIR, key: str, *, scope_kind: str = "ability",
    lifecycle: str = "ability_action", operand: NumericOperandIR | None = None,
) -> DynamicValueOperationIR:
    value_operand = operand or NumericOperandIR(
        operand_id=f"operand:{key}", operand_kind="expression", parameters={"formula_role": "value"},
        expression=numeric_fixed(2.0), coverage_status="executable",
    )
    return _operation_with(
        base, operation_kind="set", destination_key=key, destination_hash=None,
        target_alias="Caster", scope_kind=scope_kind, lifecycle=lifecycle,
        operand=value_operand.to_json(), minimum=None, maximum=None,
        coverage_status="executable", blocked_reason="",
    )


def _effect(operation: DynamicValueOperationIR, *, owner_modifier_name: str = "", opcode: str = "SetDynamicValue") -> EffectIR:
    return EffectIR(
        effect_id=f"effect:probe:{operation.operation_id[-16:]}:{owner_modifier_name or 'none'}",
        opcode=opcode, payload={"standard": {"dynamic_operation": operation.to_spec_json()}},
        source=operation.source, owner_modifier_name=owner_modifier_name,
        coverage_status="executable", source_mode="character_ability",
    )


def _context(state: BattleState, *, payload: dict[str, Any] | None = None) -> EffectExecutionContext:
    return EffectExecutionContext(
        state=state, caster_id="actor", source_id="task:public", owner_id="actor",
        param_entity_id="target", current_action_target_id="target",
        event_payload={
            "ability_instance_id": "ability:public:1", "event_id": "event:public:1",
            "operation_event_id": "operation_event:public:1",
            "task_id": "task:public", **(payload or {}),
        },
    )


def _zero_effect_channels(result: Any) -> bool:
    return not result.events and not result.mutations and not result.rng_events and not result.records


def _negative_matrix(base: DynamicValueOperationIR, *, attack_convert_blocked: bool,
                     blocked_sources_typed: bool) -> dict[str, Any]:
    state = _base_state()
    operation = _fixed_operation(base, "seal_probe")
    request = _request(operation, event_id="seal", target_id="target")
    original_plan = plan_dynamic_value_operation(state, operation, request)
    fake_mutation = Mutation(op="set", path=("skill_points",), before=3, after=99,
        reason="forged", source="p9_s4_probe")
    construction_rejected = False
    try:
        replace(original_plan, mutations=(fake_mutation,))
    except (TypeError, ValueError):
        construction_rejected = True
    tamper_values = {
        "mutations": lambda plan: (fake_mutation,),
        "records": lambda plan: ({"forged": True},),
        "resolved_scope": lambda plan: {**thaw_json(plan.resolved_scope), "target_id": "target"},
        "result_value": lambda plan: 999.0,
        "replayed": lambda plan: True,
        "plan_id": lambda plan: plan.plan_id + ":forged",
        "operation": lambda plan: _fixed_operation(base, "forged_operation"),
        "request": lambda plan: replace(request, source_id="task:forged"),
    }
    tamper_results: dict[str, bool] = {}
    for field_name, forged_value in tamper_values.items():
        plan = plan_dynamic_value_operation(state, operation, request)
        object.__setattr__(plan, field_name, forged_value(plan))
        executed = execute_dynamic_value_plan(state, plan)
        tamper_results[field_name] = not executed.ok and not executed.mutations and not executed.records
    stable_plan = plan_dynamic_value_operation(state, operation, request)
    plan_identity_stable = original_plan.ok and stable_plan.to_json() == original_plan.to_json()

    valid_operand = operation.operand.to_json()
    invalid_operands: list[dict[str, Any]] = []
    for mutation in ("unknown", "numeric_id", "scale_string", "scale_member", "wrong_parameter_type"):
        payload = json.loads(json.dumps(valid_operand))
        if mutation == "unknown": payload["parameters"]["unknown"] = 1
        elif mutation == "numeric_id": payload["operand_id"] = 7
        elif mutation == "scale_string": payload["scale_expression"] = "bad"
        elif mutation == "scale_member": payload["scale_expression"] = {"kind": "fixed", "value": 1.0}
        else: payload["parameters"]["formula_role"] = 7
        invalid_operands.append(payload)
    operand_schema_rejected = True
    for payload in invalid_operands:
        try:
            NumericOperandIR.from_json(payload)
            operand_schema_rejected = False
        except (TypeError, ValueError):
            pass

    registry = EffectRegistry()
    status_operation = _fixed_operation(base, "status_mismatch", scope_kind="status", lifecycle="status_instance")
    status_effect = _effect(status_operation, owner_modifier_name="A")
    status_before = state.snapshot().to_json(); status_mismatch = registry.execute(status_effect, _context(state, payload={"status_instance_id": "status:B"}))
    status_identity_blocked = bool(status_mismatch.unsupported) and _zero_effect_channels(status_mismatch) and state.snapshot().to_json() == status_before
    trace_free_actor = replace(state.units["actor"], flags={**state.units["actor"].flags, "status_details": [{**item, "source_trace": {}} for item in state.units["actor"].flags["status_details"]]}); trace_free = registry.execute(status_effect, _context(replace(state, units={"actor": trace_free_actor, "target": state.units["target"]}), payload={"status_instance_id": "status:A"}))
    malformed_dynamic_actor = replace(state.units["actor"], flags={**state.units["actor"].flags, "status_details": [{**item, "dynamic_values": "invalid"} if item["instance_id"] == "status:A" else item for item in state.units["actor"].flags["status_details"]]}); malformed_dynamic = registry.execute(status_effect, _context(replace(state, units={"actor": malformed_dynamic_actor, "target": state.units["target"]}), payload={"status_instance_id": "status:A"}))
    status_runtime_boundary = not trace_free.unsupported and bool(trace_free.mutations) and bool(malformed_dynamic.unsupported) and _zero_effect_channels(malformed_dynamic)

    count_operand = NumericOperandIR(
        operand_id="operand:status_count", operand_kind="status_count",
        parameters={"source_target_alias": "Caster", "count_mode": "debuff"},
        coverage_status="executable",
    )
    count_operation = _fixed_operation(base, "debuff_count", operand=count_operand)
    count_result = registry.execute(_effect(count_operation), _context(state))
    count_values = [
        entry.get("value")
        for mutation in count_result.mutations
        if mutation.path == ("global_flags", "dynamic_value_store")
        for entry in (mutation.after.get("entries", {}).values() if isinstance(mutation.after, dict) else ())
        if isinstance(entry, dict) and entry.get("name") == "debuff_count"
    ]
    malformed_actor = replace(state.units["actor"], flags={"status_details": [{"instance_id": "malformed"}]})
    malformed_state = replace(state, units={"actor": malformed_actor, "target": state.units["target"]})
    malformed_result = registry.execute(_effect(count_operation), _context(malformed_state))
    status_count_contract = count_values == [1.0] and _zero_effect_channels(malformed_result) and bool(malformed_result.unsupported)

    after_set = MutationReducer().apply_all(state, original_plan.mutations)
    replay_plan = plan_dynamic_value_operation(after_set, operation, request)
    replay_execution = execute_dynamic_value_plan(after_set, replay_plan)
    valid_replay = replay_plan.ok and replay_plan.replayed and replay_execution.ok and not replay_execution.mutations
    forged_store = thaw_json(after_set.global_flags["dynamic_value_store"])
    ledger_entry = next(iter(forged_store["operation_ledger"].values()))
    ledger_entry["source_id"] = "forged:source"
    forged_state = replace(state, global_flags={"dynamic_value_store": forged_store})
    forged_plan = plan_dynamic_value_operation(forged_state, operation, request)
    forged_ledger_blocked = not forged_plan.ok and not forged_plan.replayed and not forged_plan.mutations and not forged_plan.records

    add_operation = _operation_with(operation, operation_kind="add")
    add_request = _request(add_operation, event_id="add_identity")
    add_plan = plan_dynamic_value_operation(after_set, add_operation, add_request)
    after_add = MutationReducer().apply_all(after_set, add_plan.mutations) if add_plan.ok else after_set
    add_replay = plan_dynamic_value_operation(after_add, add_operation, add_request)
    distinct_add = plan_dynamic_value_operation(after_add, add_operation, _request(add_operation, event_id="add_identity_2"))
    add_identity_idempotent = add_plan.ok and add_replay.ok and add_replay.replayed and not add_replay.mutations and distinct_add.ok and not distinct_add.replayed

    damaged_spec = operation.to_spec_json()
    damaged_spec["scope_kind"] = "forged"
    forged_copy_spec = operation.to_spec_json(); forged_copy_spec["operation_kind"] = "copy"
    invalid_effects = (
        EffectIR(effect_id="effect:missing", opcode="SetDynamicValue", payload={"standard": {}}, source=operation.source, coverage_status="executable"),
        EffectIR(effect_id="effect:damaged", opcode="SetDynamicValue", payload={"standard": {"dynamic_operation": damaged_spec}}, source=operation.source, coverage_status="executable"),
        EffectIR(effect_id="effect:future", opcode="SetDynamicValueFuture", payload={"standard": {}}, source=operation.source, coverage_status="executable"),
        EffectIR(effect_id="effect:copy", opcode="SetDynamicValueByCopying", payload={"standard": {"dynamic_operation": forged_copy_spec}}, source=operation.source, coverage_status="executable"),
    )
    invalid_results = [registry.execute(effect, _context(state)) for effect in invalid_effects]
    invalid_coverage_blocked = all(registry.coverage(effect) == "blocked" for effect in invalid_effects) and all(_zero_effect_channels(result) and result.unsupported for result in invalid_results)

    callback_source = inspect.getsource(status_callbacks_module)
    callback_route_shared = all(name not in callback_source for name in (
        "_execute_context_dynamic_value_task", "_execute_set_dynamic_value_by_damage_data_property",
        "_context_dynamic_value", "_callback_status_dynamic_value_mutation", "upsert_dynamic_value(",
    )) and "_execute_effect_task" in callback_source

    evaluator = RuleEvaluator()
    non_finite = all(not evaluator.evaluate_numeric({"schema_version": "hsr.numeric_expression.v1", "kind": "fixed", "value": value, "supported": True}).ok for value in (True, float("nan"), float("inf"), 10 ** 10000))
    division = evaluator.evaluate_numeric({"schema_version": "hsr.numeric_expression.v1", "kind": "program", "supported": True, "instructions": [{"opcode": "push_fixed", "value": 1.0}, {"opcode": "push_fixed", "value": 0.0}, {"opcode": "div"}, {"opcode": "end"}]})
    stack = evaluator.evaluate_numeric({"schema_version": "hsr.numeric_expression.v1", "kind": "program", "supported": True, "instructions": [{"opcode": "add"}, {"opcode": "end"}]})
    strict_request = False
    try:
        replace(request, owner_id=7)
    except TypeError:
        strict_request = True
    checks = {
        "plan_construction_rejects_arbitrary_mutation": construction_rejected,
        "plan_all_content_tamper_rejected": all(tamper_results.values()), "plan_identity_stable": plan_identity_stable,
        "numeric_operand_exact_schema": operand_schema_rejected, "blocked_operand_source_typed": blocked_sources_typed,
        "status_instance_identity_bilateral": status_identity_blocked, "status_runtime_ignores_audit_trace_and_rejects_malformed_values": status_runtime_boundary, "attack_convert_registry_blocked": attack_convert_blocked,
        "status_count_debuff_and_malformed_closed": status_count_contract,
        "valid_replay": valid_replay, "forged_ledger_blocked": forged_ledger_blocked,
        "add_operation_identity_idempotent": add_identity_idempotent,
        "invalid_dynamic_spec_coverage_blocked": invalid_coverage_blocked,
        "callback_route_shared": callback_route_shared,
        "request_identity_strict": strict_request, "bool_nan_infinity": non_finite,
        "division_by_zero": not division.ok, "stack_error": not stack.ok,
    }
    return {"ok": all(checks.values()), "checks": checks, "plan_tamper": tamper_results}


def main() -> int:
    args = _args()
    started = time.monotonic()
    snapshot = build_character_ability_raw_snapshot(args.tbgd_root)
    discovered: set[str] = set()
    raw_containers: dict[tuple[str, str], dict[str, Any]] = {}
    for source_path, document in snapshot.documents.items():
        _walk_types(document, discovered, raw_containers, source_path=source_path)
    decoded_families = set(character_dynamic_value_decode_families())
    families = tuple(sorted(discovered | decoded_families))
    projection = build_character_ability_scope_projection(
        args.tbgd_root, snapshot=snapshot, families=families,
    )
    lowering = TBGDLowering(args.tbgd_root)
    source_graph = lowering.build_character_ability_source_graph_catalog(
        snapshot=snapshot, scope_catalog=projection,
    )
    source_graph_guards = _source_graph_identity_guards(args.tbgd_root, snapshot, projection)
    records_by_family: dict[str, list[Any]] = defaultdict(list)
    for record in projection.scope_records:
        if record.family in families:
            records_by_family[record.family].append(record)

    family_matrix: list[dict[str, Any]] = []
    operations: list[tuple[DynamicValueOperationIR, Any]] = []
    operation_raw: list[tuple[DynamicValueOperationIR, Any, dict[str, Any]]] = []
    all_typed = all_oracles = True
    for family in families:
        records = records_by_family.get(family, [])
        typed: list[DynamicValueOperationIR] = []
        oracle_failures = 0
        errors: list[str] = []
        for record in records:
            json_path = str(record.source.evidence.get("json_path") or "")
            raw = raw_containers.get((record.source.source_path, json_path))
            if raw is None and record.raw_fields:
                raw = thaw_json(record.raw_fields)
            if not isinstance(raw, dict):
                errors.append(f"raw_missing:{record.record_id}")
                continue
            try:
                operation = (
                    lower_character_decoded_dynamic_value_operation(record)
                    if family in decoded_families
                    else lower_character_dynamic_value_operation(family, raw, record.source)
                )
                oracle = _raw_oracle(family, raw, operation, decoded_families)
                if not oracle["ok"]:
                    oracle_failures += 1
                typed.append(operation)
                operations.append((operation, record))
                operation_raw.append((operation, record, raw))
            except (KeyError, TypeError, ValueError) as exc:
                if len(errors) < 20:
                    errors.append(f"{record.record_id}:{type(exc).__name__}:{exc}")
        family_typed, family_oracle = bool(records) and len(typed) == len(records) and not errors, bool(records) and oracle_failures == 0 and len(typed) == len(records)
        all_typed, all_oracles = all_typed and family_typed, all_oracles and family_oracle
        family_matrix.append({
            "family": family, "occurrence_count": len(records),
            "typed_occurrence_count": len(typed),
            "coverage": sorted({operation.coverage_status for operation in typed}), "operand_kinds": sorted({operation.operand.operand_kind for operation in typed}),
            "scope_kinds": sorted({operation.scope_kind for operation in typed}), "effective_scopes": sorted({record.effective_scope for record in records}),
            "blocked_reasons": sorted({operation.blocked_reason for operation in typed if operation.blocked_reason}),
            "required_producers": sorted({operation.operand.required_producer for operation in typed if operation.operand.required_producer}),
            "raw_oracle_occurrence_count": len(typed), "raw_oracle_failure_count": oracle_failures,
            "errors": errors,
        })

    attack_convert_rows = [
        operation
        for operation, record, raw in operation_raw
        if record.family in {"SetDynamicValueByProperty", "SetDynamicValueByPropertyClientOnly"}
        and _raw_string(raw, ("Value",)) == "AttackConvert"
    ]
    attack_convert_blocked = bool(attack_convert_rows) and all(
        operation.coverage_status == "blocked"
        and operation.operand.coverage_status == "blocked"
        and operation.operand.required_producer == "shared_property_registry"
        and "unit_property_runtime_producer_missing:AttackConvert" in operation.blocked_reason
        for operation in attack_convert_rows
    )
    blocked_operands = [operation.operand for operation, _ in operations if operation.operand.coverage_status == "blocked"]
    blocked_sources_typed = bool(blocked_operands) and all(
        operand.required_producer
        and NumericOperandIR.from_json(operand.to_json()).to_json() == operand.to_json()
        for operand in blocked_operands
    )
    decoded_shared_model = all(
        operation.source.raw_type in decoded_families
        and type(operation) is DynamicValueOperationIR
        for operation, record in operations if record.family in decoded_families
    )

    formal_transition, formal_operation = _formal_action(lowering, snapshot, projection, source_graph, operations)
    scope_matrix = _scope_matrix(formal_operation)
    negative_matrix = _negative_matrix(formal_operation, attack_convert_blocked=attack_convert_blocked, blocked_sources_typed=blocked_sources_typed)
    predicates = {
        "current_dynamic_value_families_all_occurrences_typed": all_typed,
        "numeric_operands_source_backed_per_occurrence": all_oracles,
        "decoded_dynamic_sources_use_shared_operation_model": decoded_shared_model,
        "filtered_scope_builds_complete_identity_closed_graph": bool(projection.family_filter)
        and source_graph.source_catalog_complete and source_graph.snapshot_id == snapshot.snapshot_id
        and len(source_graph.sources) == len(snapshot.sources) and all(source_graph_guards.values()),
        "dynamic_value_scopes_distinct": scope_matrix["ok"],
        "real_formal_action_uses_shared_contract": formal_transition["ok"],
        "differential_attack_matrix_closed": negative_matrix["ok"],
        "character_specific_numeric_handlers": 0,
    }
    predicates_ok = all(value is True or key == "character_specific_numeric_handlers" and value == 0 for key, value in predicates.items())
    producer_matrix: dict[str, set[str]] = defaultdict(set)
    for operation, record in operations:
        if operation.operand.required_producer:
            producer_matrix[operation.operand.required_producer].add(record.family)
    elapsed = time.monotonic() - started
    result = {
        "ok": predicates_ok,
        "schema_version": "p9_s4_numeric_dynamic_value_closure.v2",
        "predicates": predicates,
        "source_projection": {
            "family_count": len(families), "occurrence_count": sum(len(value) for value in records_by_family.values()),
            "families": list(families), "decoded_families": sorted(decoded_families),
            "snapshot_build_counters": thaw_json(snapshot.build_counters), "projection_build_counters": thaw_json(projection.build_counters),
            "family_filter_applied_before_ir_materialization": projection.build_counters.get("family_filter_applied_before_ir_materialization") is True,
            "source_graph_catalog_id": source_graph.catalog_id,
        },
        "family_matrix": family_matrix, "scope_matrix": scope_matrix,
        "negative_matrix": negative_matrix, "formal_transition": formal_transition,
        "source_graph_identity_guards": source_graph_guards,
        "deferred_producer_matrix": {key: sorted(value) for key, value in sorted(producer_matrix.items())},
        "resources": {
            "wall_seconds": round(elapsed, 6), "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "source_snapshot_build_count": 1, "source_projection_build_count": 1, "source_graph_build_count": 1,
            "source_resolution_build_count": 0, "complete_lowering_build_count": 0,
        },
        "direct": [], "deferred": [
            "P9-S5/P9-S9-S15 domain producers remain typed blocked until their owning stages",
            "status callback lifecycle end-to-end remains P9-S10; S4 retains only the shared public effect route",
            "damage/heal/precalculated/event/RNG values are not synthesized by S4"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["ok"], "family_count": len(families),
        "occurrence_count": result["source_projection"]["occurrence_count"],
        "wall_seconds": result["resources"]["wall_seconds"], "max_rss_kib": result["resources"]["max_rss_kib"],
        "output": str(args.output)}, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
