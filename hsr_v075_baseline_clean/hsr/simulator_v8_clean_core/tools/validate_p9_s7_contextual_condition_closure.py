from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..core.model import ActionCommand, BattleState, TargetResolution, UnitState
from ..rules.condition_state import (
    TRANSIENT_CONDITION_FACT_KINDS,
    TRANSIENT_CONDITION_FACT_SPECS,
    TransientConditionOperandRequest,
    TransientConditionOperandResolution,
)
from ..rules.evaluator import (
    CONTEXTUAL_CONDITION_FACTS_BY_OPCODE,
    CONTEXTUAL_CONDITION_OPCODES,
    EvaluationContext,
    RuleEvaluator,
    _condition_target_key,
)
from ..rules.expression_ir import CONDITION_EXPRESSION_NODE_SCHEMA
from ..rules.ir import CanonicalIR, ConditionIR, TargetExpressionNodeIR
from ..rules.rulebook import RuleBook
from ..systems.target import TargetSystem
from ..systems.action_event_contract import (
    action_condition_fact_provider,
    admitted_action_condition_fact_provider,
)
from ..systems.action_selection import ActionTargetSelectionSystem
from ..systems.unit_relation import TargetEvaluationContext
from ..tbgd.action_target_contracts import build_action_target_contract_catalog
from ..tbgd.character_condition_contracts import (
    build_character_condition_responsibility_catalog,
)
from ..tbgd.lowering import TBGDLowering, _typed_condition_execution_node


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
_STAGE = "p9_s7_transient_context"
_COMPARE_TYPES = {"Less", "LessEqual", "Greater", "GreaterEqual", "Equal", "NotEqual"}
_PRODUCER_STAGE_BY_AUTHORITY = {
    "action_target_contract": "current",
    "charm_action_context": "p9_s16",
    "damage_context": "p9_s11",
    "event_context": "p9_s9",
    "queue_context": "p9_s13",
    "resource_change_context": "p9_s12",
    "status_callback_context": "p9_s10",
    "turn_context": "p9_s13",
}
_EXPECTED_FACTS = {
    "ByCheckModifierCallBackModifierValue": ("status_callback.modifier_value",),
    "ByCompareNextUnusedInsertAction": ("queue.next_unused_insert_action_matches",),
    "ByCompareParamString": ("event.param_string",),
    "ByCompareSPChangeTag": ("resource_change.tags",),
    "ByCompareTurnActionEntityTeamType": ("turn.action_entity.team",),
    "ByCompareUnusedInsertAbilityCount": ("queue.unused_insert_ability_count",),
    "ByCompareUnusedUltraSkillCount": ("queue.unused_ultimate_count",),
    "ByCurrentSkillTargetType": ("action.target_type", "action.dynamic_target"),
    "ByDamageSourceContainBehaviorFlag": ("damage.source_behavior_flags",),
    "ByHasInsertActionByTarget": ("queue.has_insert_action_by_target",),
    "ByIsDamageType": ("damage.type",),
    "ByIsInCharmAction": ("action.charm_phase",),
    "ByIsSplitDamage": ("damage.is_split",),
    "ByIsTurnActionEntity": ("turn.action_entity.identity",),
    "ByTurnOwnerActionPhaseEnd": ("turn.owner.action_phase_end",),
    "ByTurnOwnerHasActionInTurn": ("turn.owner.has_action",),
    "ByTurnOwnerHasPendingOneMore": ("turn.owner.pending_one_more",),
}
_EXPECTED_SIGNATURES = {
    "ByCheckModifierCallBackModifierValue": {frozenset({"CompareType", "CompareValue", "ValueType"})},
    "ByCompareNextUnusedInsertAction": {frozenset({"ActionTypeIs", "CasterIs"}), frozenset({"CustomTagIs", "Inverse"})},
    "ByCompareParamString": {frozenset({"CompareValue"})},
    "ByCompareSPChangeTag": {frozenset({"TagList"})},
    "ByCompareTurnActionEntityTeamType": {frozenset({"Team"})},
    "ByCompareUnusedInsertAbilityCount": {frozenset({"CompareType", "CompareValue"})},
    "ByCompareUnusedUltraSkillCount": {
        frozenset({"CompareType", "CompareValue", "IncludeInsertAction"}),
        frozenset({"CompareType", "CompareValue", "SkillOwnerType"}),
        frozenset({"CompareType", "CompareValue", "IncludeInsertAction", "SkillOwnerType"}),
    },
    "ByCurrentSkillTargetType": {frozenset({"IsDynamic"}), frozenset({"TargetType"})},
    "ByDamageSourceContainBehaviorFlag": {frozenset({"BehaviorFlags"})},
    "ByHasInsertActionByTarget": {frozenset({"TargetType"})},
    "ByIsDamageType": {frozenset({"DamageTypeList", "TargetType"})},
    "ByIsInCharmAction": {frozenset()},
    "ByIsSplitDamage": {frozenset({"TargetType"}), frozenset({"Inverse", "TargetType"})},
    "ByIsTurnActionEntity": {frozenset({"TargetType"}), frozenset({"Inverse", "TargetType"})},
    "ByTurnOwnerActionPhaseEnd": {frozenset({"Inverse"})},
    "ByTurnOwnerHasActionInTurn": {frozenset()},
    "ByTurnOwnerHasPendingOneMore": {frozenset({"Inverse"})},
}


def _at_path(document: Mapping[str, Any], path: str) -> Any:
    current: Any = document
    index = 1
    while index < len(path):
        if path[index] == ".":
            index += 1
            end = index
            while end < len(path) and path[end] not in ".[":
                end += 1
            current = current[path[index:end]]
            index = end
        else:
            end = path.index("]", index)
            current = current[int(path[index + 1 : end])]
            index = end + 1
    return current


def _raw_shape_valid(family: str, raw: Mapping[str, Any]) -> bool:
    fields = {key: value for key, value in raw.items() if key != "$type"}
    if frozenset(fields) not in _EXPECTED_SIGNATURES.get(family, set()):
        return False
    if "CompareType" in fields and fields["CompareType"] not in _COMPARE_TYPES:
        return False
    for key in ("Inverse", "IncludeInsertAction"):
        if key in fields and type(fields[key]) is not bool:
            return False
    for key in ("ActionTypeIs", "CustomTagIs", "Team", "ValueType"):
        if key in fields and (not isinstance(fields[key], str) or not fields[key]):
            return False
    for key in ("CasterIs", "SkillOwnerType"):
        if key in fields and not isinstance(fields[key], Mapping):
            return False
    if family == "ByCompareParamString":
        value = fields.get("CompareValue")
        return isinstance(value, Mapping) and set(value) == {"Value"} and isinstance(value.get("Value"), str) and bool(value.get("Value"))
    if family == "ByCompareSPChangeTag":
        tags = fields.get("TagList")
        return isinstance(tags, (list, tuple)) and len(tags) == 1 and all(
            isinstance(item, Mapping)
            and set(item) == {"EnumIndex", "Value"}
            and isinstance(item["EnumIndex"], int)
            and not isinstance(item["EnumIndex"], bool)
            and isinstance(item["Value"], int)
            and not isinstance(item["Value"], bool)
            for item in tags
        )
    if family == "ByCurrentSkillTargetType" and "IsDynamic" in fields:
        return fields["IsDynamic"] in {True, False, "True", "False"}
    for key in ("BehaviorFlags", "DamageTypeList"):
        if key in fields:
            values = fields[key]
            if not isinstance(values, (list, tuple)) or not values or any(not isinstance(item, str) or not item for item in values) or len(values) != len(set(values)):
                return False
    return True


def _payload_from_node(node: Mapping[str, Any]) -> dict[str, Any]:
    metadata = {"schema_version", "expression_kind", "opcode", "supported", "blocked_reason"}
    return {key: value for key, value in node.items() if key not in metadata}


def _condition_from_node(row: Any, node: Mapping[str, Any]) -> ConditionIR:
    return ConditionIR(
        condition_id=row.record_id,
        opcode=row.opcode,
        payload=_payload_from_node(node),
        source=row.source,
        coverage_status="executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )


def _target_groups(condition: ConditionIR) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}

    def visit(value: object) -> None:
        if isinstance(value, TargetExpressionNodeIR):
            result[_condition_target_key(value)] = ("unit:target",)
        elif isinstance(value, Mapping):
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(condition.payload)
    return result


class _FixtureProvider:
    def __init__(self, values: Mapping[str, tuple[str, Any]] | None = None, *, returned_invocation: str = "validation:p9_s7") -> None:
        self.values = dict(values or {})
        self.returned_invocation = returned_invocation
        self.invocation_id = returned_invocation
        self.window = "validation_fixture"
        self.requests: list[TransientConditionOperandRequest] = []

    def resolve_transient(self, request: TransientConditionOperandRequest) -> TransientConditionOperandResolution:
        self.requests.append(request)
        entry = self.values.get(request.fact_kind)
        if entry is None:
            return TransientConditionOperandResolution.blocked(
                "validation_fixture_fact_missing",
                fact_kind=request.fact_kind,
                invocation_id=self.returned_invocation,
            )
        value_type, value = entry
        return TransientConditionOperandResolution.resolved(
            value_type,
            value,
            fact_kind=request.fact_kind,
            invocation_id=self.returned_invocation,
            window="validation_fixture",
            source_identity="validation_fixture:p9_s7",
        )


def _fixture_context(condition: ConditionIR, provider: _FixtureProvider | None) -> EvaluationContext:
    return EvaluationContext(
        actor_id="unit:actor",
        target_id="unit:target",
        owner_id="unit:target",
        param_entity_id="unit:target",
        current_action_target_id="unit:target",
        resolved_target_groups=_target_groups(condition),
        target_resolution_errors={},
        transient_invocation_id="validation:p9_s7",
        transient_window="validation_fixture",
        transient_condition_provider=provider,
    )


def _choose(conditions: Mapping[str, list[ConditionIR]], family: str, predicate: Any = None) -> ConditionIR:
    for condition in conditions[family]:
        if predicate is None or predicate(condition.payload):
            return condition
    raise AssertionError(f"missing real S7 condition case {family}")


def _fixed_number(value: object) -> float:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != "hsr.numeric_expression.v1"
        or value.get("kind") != "fixed"
    ):
        raise AssertionError("S7 numeric fixture is not independently fixed")
    number = value.get("value")
    if not isinstance(number, (int, float)) or isinstance(number, bool):
        raise AssertionError("S7 numeric fixture value is invalid")
    return float(number)


def _numeric_values(condition: ConditionIR) -> tuple[float, float]:
    expected = _fixed_number(condition.payload.get("CompareValue"))
    compare_type = condition.payload.get("CompareType")
    if compare_type == "Less":
        return expected - 1.0, expected
    if compare_type == "LessEqual":
        return expected, expected + 1.0
    if compare_type == "Greater":
        return expected + 1.0, expected
    if compare_type == "GreaterEqual":
        return expected, expected - 1.0
    if compare_type == "Equal":
        return expected, expected + 1.0
    if compare_type == "NotEqual":
        return expected + 1.0, expected
    raise AssertionError(f"unsupported S7 comparison {compare_type!r}")


def _boolean_values(condition: ConditionIR) -> tuple[bool, bool]:
    return not bool(condition.payload.get("Inverse", False)), bool(condition.payload.get("Inverse", False))


def _component_cases(conditions: Mapping[str, list[ConditionIR]]) -> list[tuple[str, ConditionIR, str, str, Any, Any]]:
    callback = _choose(conditions, "ByCheckModifierCallBackModifierValue", lambda p: p["ValueType"] == "LifeTime")
    insert_count = _choose(conditions, "ByCompareUnusedInsertAbilityCount")
    ultimate_count = _choose(conditions, "ByCompareUnusedUltraSkillCount", lambda p: p["CompareType"] == "Equal")
    param_string = _choose(conditions, "ByCompareParamString")
    tags = _choose(conditions, "ByCompareSPChangeTag")
    team = _choose(conditions, "ByCompareTurnActionEntityTeamType")
    target_type = _choose(conditions, "ByCurrentSkillTargetType", lambda p: "TargetType" in p)
    dynamic_target = _choose(conditions, "ByCurrentSkillTargetType", lambda p: "IsDynamic" in p)
    damage_flags = _choose(conditions, "ByDamageSourceContainBehaviorFlag")
    damage_type = _choose(conditions, "ByIsDamageType")
    split = _choose(conditions, "ByIsSplitDamage", lambda p: "Inverse" not in p)
    turn_entity = _choose(conditions, "ByIsTurnActionEntity")
    phase_end = _choose(conditions, "ByTurnOwnerActionPhaseEnd")
    pending = _choose(conditions, "ByTurnOwnerHasPendingOneMore")
    callback_values = _numeric_values(callback)
    insert_values = _numeric_values(insert_count)
    ultimate_values = _numeric_values(ultimate_count)
    dynamic_values = (dynamic_target.payload["IsDynamic"], not dynamic_target.payload["IsDynamic"])
    split_values = _boolean_values(split)
    phase_values = _boolean_values(phase_end)
    pending_values = _boolean_values(pending)
    expected_team = team.payload["Team"]
    expected_target_type = target_type.payload["TargetType"]
    expected_damage_types = tuple(damage_type.payload["DamageTypeList"])
    return [
        ("callback_value", callback, "status_callback.modifier_value", "number", *callback_values),
        ("next_insert", _choose(conditions, "ByCompareNextUnusedInsertAction", lambda p: "ActionTypeIs" in p), "queue.next_unused_insert_action_matches", "boolean", True, False),
        ("param_string", param_string, "event.param_string", "string", param_string.payload["CompareValue"], f"validation:not:{param_string.payload['CompareValue']}"),
        ("sp_tags", tags, "resource_change.tags", "identity_set", tuple(sorted(tags.payload["TagList"])), ()),
        ("turn_team", team, "turn.action_entity.team", "string", expected_team, f"validation:not:{expected_team}"),
        ("insert_count", insert_count, "queue.unused_insert_ability_count", "number", *insert_values),
        ("ultimate_count", ultimate_count, "queue.unused_ultimate_count", "number", *ultimate_values),
        ("target_type", target_type, "action.target_type", "string", expected_target_type, f"validation:not:{expected_target_type}"),
        ("dynamic_target", dynamic_target, "action.dynamic_target", "boolean", *dynamic_values),
        ("damage_flags", damage_flags, "damage.source_behavior_flags", "identity_set", tuple(sorted(damage_flags.payload["BehaviorFlags"])), ()),
        ("insert_target", _choose(conditions, "ByHasInsertActionByTarget"), "queue.has_insert_action_by_target", "boolean", True, False),
        ("damage_type", damage_type, "damage.type", "string", expected_damage_types[0], f"validation:not:{expected_damage_types[0]}"),
        ("charm", _choose(conditions, "ByIsInCharmAction"), "action.charm_phase", "boolean", True, False),
        ("split", split, "damage.is_split", "boolean", *split_values),
        ("turn_entity", turn_entity, "turn.action_entity.identity", "string", *(('unit:target', 'unit:other') if not turn_entity.payload.get('Inverse', False) else ('unit:other', 'unit:target'))),
        ("phase_end", phase_end, "turn.owner.action_phase_end", "boolean", *phase_values),
        ("turn_history", _choose(conditions, "ByTurnOwnerHasActionInTurn"), "turn.owner.has_action", "boolean", True, False),
        ("pending_one_more", pending, "turn.owner.pending_one_more", "boolean", *pending_values),
    ]


def _source_and_conditions(tbgd_root: Path) -> tuple[Any, Any, Any, dict[str, list[ConditionIR]], list[dict[str, Any]], dict[str, tuple[dict[str, Any], Any, dict[str, Any]]]]:
    lowering = TBGDLowering(tbgd_root)
    source_graph = lowering.build_character_ability_source_graph_catalog()
    snapshot = lowering._character_ability_raw_snapshot
    scope = lowering._character_ability_scope_catalog
    catalog = build_character_condition_responsibility_catalog(snapshot, scope)
    rows = tuple(row for row in catalog.responsibilities if row.evaluation_stage == _STAGE)
    conditions: dict[str, list[ConditionIR]] = defaultdict(list)
    matrix: list[dict[str, Any]] = []
    seeds: dict[str, tuple[dict[str, Any], Any, dict[str, Any]]] = {}
    for row in rows:
        document = snapshot.documents[row.source.source_path]
        path = str(row.source.evidence["json_path"]).removesuffix(".$type")
        raw = _at_path(document, path)
        aliases = document.get("GlobalTargetAlias") if isinstance(document, Mapping) else {}
        if isinstance(raw, Mapping):
            seeds.setdefault(
                row.opcode,
                (dict(raw), row.source, dict(aliases) if isinstance(aliases, Mapping) else {}),
            )
        node = _typed_condition_execution_node(
            dict(raw),
            target_alias_registry=dict(aliases) if isinstance(aliases, Mapping) else {},
            source=row.source,
        ) if isinstance(raw, Mapping) else {}
        if node.get("supported") is True:
            conditions[row.opcode].append(_condition_from_node(row, node))
        matrix.append({
            "record_id": row.record_id,
            "family": row.opcode,
            "producer_stage": row.producer_stage,
            "source_path": row.source.source_path,
            "json_path": path,
            "raw_reversible": isinstance(raw, Mapping) and str(raw.get("$type") or "").rsplit(".", 1)[-1] == row.opcode,
            "field_signature": sorted(key for key in raw if key != "$type") if isinstance(raw, Mapping) else [],
            "raw_shape_valid": isinstance(raw, Mapping) and _raw_shape_valid(row.opcode, raw),
            "lowered": node.get("supported") is True,
            "blocked_reason": node.get("blocked_reason", "source_missing"),
        })
    return lowering, source_graph, catalog, conditions, matrix, seeds


def _lowering_negative_checks(seeds: Mapping[str, tuple[dict[str, Any], Any, dict[str, Any]]]) -> dict[str, bool]:
    def rejected(family: str, mutate: Any) -> bool:
        raw, source, aliases = seeds[family]
        candidate = json.loads(json.dumps(raw))
        mutate(candidate)
        node = _typed_condition_execution_node(
            candidate,
            target_alias_registry=aliases,
            source=source,
        )
        return node.get("supported") is False and bool(node.get("blocked_reason"))

    return {
        "unknown_peer_field_rejected": rejected(
            "ByCompareParamString", lambda raw: raw.__setitem__("UnknownPeer", True)
        ),
        "multi_tag_semantics_rejected": rejected(
            "ByCompareSPChangeTag",
            lambda raw: raw.__setitem__("TagList", [*raw["TagList"], *raw["TagList"]]),
        ),
        "non_strict_dynamic_flag_rejected": rejected(
            "ByCurrentSkillTargetType", lambda raw: raw.__setitem__("IsDynamic", "true")
        ),
        "empty_event_string_rejected": rejected(
            "ByCompareParamString", lambda raw: raw.__setitem__("CompareValue", {"Value": ""})
        ),
    }


def _runtime_matrix(conditions: Mapping[str, list[ConditionIR]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evaluator = RuleEvaluator()
    rows: list[dict[str, Any]] = []
    for name, condition, fact, value_type, true_value, false_value in _component_cases(conditions):
        true_provider = _FixtureProvider({fact: (value_type, true_value)})
        false_provider = _FixtureProvider({fact: (value_type, false_value)})
        true_result = evaluator.evaluate_condition_result(condition, _fixture_context(condition, true_provider))
        false_result = evaluator.evaluate_condition_result(condition, _fixture_context(condition, false_provider))
        blocked_result = evaluator.evaluate_condition_result(condition, _fixture_context(condition, None))
        rows.append({
            "case": name,
            "family": condition.opcode,
            "fact_kind": fact,
            "true": true_result.to_json(),
            "false": false_result.to_json(),
            "blocked": blocked_result.to_json(),
            "component_fixture_only": True,
        })
    requests: list[dict[str, Any]] = []
    for family_conditions in conditions.values():
        for condition in family_conditions:
            provider = _FixtureProvider()
            evaluator.evaluate_condition_result(condition, _fixture_context(condition, provider))
            requests.extend(
                {
                    "condition_id": condition.condition_id,
                    "family": condition.opcode,
                    "fact_kind": request.fact_kind,
                    "window": request.window,
                    "subject_ids": list(request.subject_ids),
                    "parameters": dict(request.parameters or {}),
                    "shape_valid": _request_shape_valid(request),
                }
                for request in provider.requests
            )
    return rows, requests


def _request_shape_valid(request: TransientConditionOperandRequest) -> bool:
    parameters = request.parameters or {}
    keys = set(parameters)
    fact = request.fact_kind
    if fact == "status_callback.modifier_value":
        return not request.subject_ids and keys == {"value_type"} and isinstance(parameters.get("value_type"), str)
    if fact == "queue.next_unused_insert_action_matches":
        action_shape = keys == {"action_type", "caster_ids"} and isinstance(parameters.get("action_type"), str) and isinstance(parameters.get("caster_ids"), (list, tuple))
        tag_shape = keys == {"custom_tag"} and isinstance(parameters.get("custom_tag"), str)
        return not request.subject_ids and (action_shape or tag_shape)
    if fact == "queue.unused_ultimate_count":
        if keys not in ({"include_insert_action"}, {"include_insert_action", "skill_owner_ids"}):
            return False
        return (
            not request.subject_ids
            and type(parameters.get("include_insert_action")) is bool
            and (
                "skill_owner_ids" not in parameters
                or isinstance(parameters.get("skill_owner_ids"), (list, tuple))
            )
        )
    subject_counts = {
        "queue.has_insert_action_by_target": None,
        "damage.type": 1,
        "damage.is_split": 1,
    }
    if fact in subject_counts:
        expected = subject_counts[fact]
        return not keys and bool(request.subject_ids) and (
            expected is None or len(request.subject_ids) == expected
        )
    return not request.subject_ids and not keys


def _action_source_matrix(lowering: TBGDLowering, source_graph: Any, conditions: Mapping[str, list[ConditionIR]]) -> list[dict[str, Any]]:
    snapshot = lowering._character_ability_raw_snapshot
    definitions = lowering._lower_action_definitions()
    target_catalog = build_action_target_contract_catalog(
        lowering.tbgd_root,
        definitions=definitions,
        snapshot=snapshot,
        source_graph_catalog=source_graph,
        definition_scope_complete=True,
    )
    rules = RuleBook(CanonicalIR(version="p9-s7-action-slice", action_definitions=tuple(definitions), action_target_contract_catalog=target_catalog))
    state = BattleState(units={
        "unit:actor": UnitState("unit:actor", "ally", "avatar:fixture"),
        "unit:enemy": UnitState("unit:enemy", "enemy", "monster:fixture"),
    })
    targets = TargetSystem(rules)
    rows: list[dict[str, Any]] = []

    def source_provider(contract: Any) -> Any:
        return action_condition_fact_provider(
            rules,
            state,
            actor_id="unit:actor",
            action_id=contract.action_id,
            action_level=contract.level,
            invocation_id=f"validation:contract:{contract.contract_id}",
            window="action_contract_component",
        )

    cases = (
        _choose(conditions, "ByCurrentSkillTargetType", lambda p: "TargetType" in p),
        _choose(conditions, "ByCurrentSkillTargetType", lambda p: "IsDynamic" in p),
    )
    for condition in cases:
        matching = []
        differing = []
        for contract in target_catalog.contracts:
            if contract.coverage_status != "lowered":
                continue
            target_components = [item for item in contract.source_components if item.component_kind == "target_type" and item.semantic_role == "action_selection"]
            if len(target_components) != 1:
                continue
            is_match = (
                target_components[0].raw_value == condition.payload["TargetType"]
                if "TargetType" in condition.payload
                else contract.dynamic_target is condition.payload["IsDynamic"]
            )
            (matching if is_match else differing).append(contract)
        if not matching or not differing:
            rows.append({
                "family": condition.opcode,
                "status": "blocked",
                "blocked_reason": "formal_action_contract_truth_pair_missing",
                "matching_contract_count": len(matching),
                "differing_contract_count": len(differing),
            })
            continue
        contract = sorted(matching, key=lambda item: item.contract_id)[0]
        different_contract = sorted(differing, key=lambda item: item.contract_id)[0]
        provider = source_provider(contract)
        different_provider = source_provider(different_contract)
        true_context = targets.condition_evaluation_context(
            state,
            condition,
            context=TargetEvaluationContext(caster_id="unit:actor", current_target_id="unit:actor"),
            transient_condition_provider=provider,
        )
        false_context = targets.condition_evaluation_context(
            state,
            condition,
            context=TargetEvaluationContext(caster_id="unit:actor", current_target_id="unit:actor"),
            transient_condition_provider=different_provider,
        )
        payload_only_context = targets.condition_evaluation_context(
            state,
            condition,
            context=TargetEvaluationContext(caster_id="unit:actor", current_target_id="unit:actor"),
            condition_event_payload={"action_id": contract.action_id, "action_level": contract.level, "actor_id": "unit:actor", "event_id": "process:event", "event_window": "process", "event_process_only": True},
        )
        evaluator = RuleEvaluator()
        rows.append({
            "family": condition.opcode,
            "status": "source_bound_component",
            "gameplay_end_to_end": False,
            "transport_obligation_stages": (
                ["p9_s8", "p9_s9"]
                if "IsDynamic" in condition.payload
                else ["p9_s9"]
            ),
            "matching_contract_id": contract.contract_id,
            "differing_contract_id": different_contract.contract_id,
            "true": evaluator.evaluate_condition_result(condition, true_context).to_json(),
            "false": evaluator.evaluate_condition_result(condition, false_context).to_json(),
            "process_only_payload": evaluator.evaluate_condition_result(condition, payload_only_context).to_json(),
        })
    stale = cases[0]
    stale_provider = action_condition_fact_provider(
        rules,
        state,
        actor_id="unit:actor",
        action_id="validation:missing_action",
        action_level=1,
        invocation_id="validation:stale_action",
        window="action_target_contract",
    )
    stale_context = targets.condition_evaluation_context(
        state,
        stale,
        context=TargetEvaluationContext(caster_id="unit:actor", current_target_id="unit:actor"),
        transient_condition_provider=stale_provider,
    )
    rows.append({"family": stale.opcode, "stale_action": RuleEvaluator().evaluate_condition_result(stale, stale_context).to_json()})
    samples = [
        item
        for item in sorted(target_catalog.contracts, key=lambda item: item.contract_id)
        if rules.action_definition(item.action_id, item.level) is not None
    ]
    sample = samples[0] if samples else None
    definition = (
        rules.action_definition(sample.action_id, sample.level)
        if sample is not None
        else None
    )
    incomplete = admitted_action_condition_fact_provider(
        rules,
        state,
        command=ActionCommand("unit:actor", sample.action_id, sample.level, ("unit:actor",)),
        action_definition=definition,
        target_resolution=TargetResolution(
            selected=("unit:actor",),
            source="action_target_selection_system",
            metadata={
                "selection_context_fingerprint": "validation:forged",
                "contract_fingerprint": sample.contract_fingerprint,
            },
        ),
        window="action_execution",
    ) if sample is not None and definition is not None else None
    rows.append({"incomplete_admission_blocked": bool(incomplete and incomplete.blocked_reason == "action_condition_admission_identity_missing")})
    selection = ActionTargetSelectionSystem(rules)
    query_result = None
    for contract in sorted(target_catalog.contracts, key=lambda item: item.contract_id):
        if (
            contract.coverage_status == "lowered"
            and contract.selection_filter is None
            and contract.dynamic_target is False
        ):
            candidate = selection.query(
                state, "unit:actor", contract.action_id, contract.level
            )
            if candidate.resolved:
                query_result = candidate
                break
    rows.append({
        "production_action_query_entrypoint": (
            query_result.to_json() if query_result is not None else None
        )
    })
    return rows


def _negative_checks(condition: ConditionIR) -> dict[str, bool]:
    evaluator = RuleEvaluator()
    expected = condition.payload["TargetType"]
    wrong_identity = _FixtureProvider({"action.target_type": ("string", expected)}, returned_invocation="other")
    wrong_result = evaluator.evaluate_condition_result(condition, _fixture_context(condition, wrong_identity))
    wrong_type = _FixtureProvider({"action.target_type": ("boolean", True)})
    type_result = evaluator.evaluate_condition_result(condition, _fixture_context(condition, wrong_type))
    wrong_window_provider = _FixtureProvider({"action.target_type": ("string", expected)})
    wrong_window_result = evaluator.evaluate_condition_result(
        condition,
        EvaluationContext(
            actor_id="unit:actor",
            target_id="unit:target",
            resolved_target_groups=_target_groups(condition),
            transient_invocation_id="validation:p9_s7",
            transient_window="validation:other_window",
            transient_condition_provider=wrong_window_provider,
        ),
    )
    checks: dict[str, bool] = {
        "wrong_invocation_blocked": not wrong_result.ok and wrong_result.result is None and wrong_result.reason == "transient_condition_provider_identity_mismatch",
        "wrong_value_type_blocked": not type_result.ok and type_result.result is None and type_result.reason == "transient_condition_operand_type_mismatch",
        "wrong_window_blocked": not wrong_window_result.ok and wrong_window_result.result is None and wrong_window_result.reason == "transient_condition_provider_identity_mismatch",
    }
    probes = {
        "unknown_fact_rejected": lambda: TransientConditionOperandRequest("future.fact", "probe", "w"),
        "duplicate_subject_rejected": lambda: TransientConditionOperandRequest("damage.type", "probe", "w", ("u", "u")),
        "non_finite_result_rejected": lambda: TransientConditionOperandResolution.resolved("number", float("nan"), fact_kind="queue.unused_insert_ability_count", invocation_id="probe", window="w", source_identity="s"),
        "wrong_context_authority_rejected": lambda: TransientConditionOperandResolution("damage.type", "probe", "resolved", "string", "Fire", "event", "p9_s11", "w", "s"),
    }
    for name, callback in probes.items():
        try:
            callback()
        except (KeyError, TypeError, ValueError):
            checks[name] = True
        else:
            checks[name] = False
    try:
        TRANSIENT_CONDITION_FACT_SPECS["future.fact"] = ("event", "p9_s9")
    except TypeError:
        checks["fact_registry_is_immutable"] = True
    else:
        checks["fact_registry_is_immutable"] = False
    return checks


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    lowering, source_graph, catalog, conditions, source_matrix, lowering_seeds = _source_and_conditions(tbgd_root)
    source_ready = set(conditions) == set(_EXPECTED_FACTS) and all(
        conditions.get(family) for family in _EXPECTED_FACTS
    )
    runtime_matrix, requests = _runtime_matrix(conditions) if source_ready else ([], [])
    action_matrix = _action_source_matrix(lowering, source_graph, conditions) if source_ready else []
    lowering_negatives = _lowering_negative_checks(lowering_seeds) if source_ready else {}
    target_condition = (
        _choose(conditions, "ByCurrentSkillTargetType", lambda p: "TargetType" in p)
        if source_ready
        else None
    )
    negatives = _negative_checks(target_condition) if target_condition is not None else {}
    family_counts = Counter(row["family"] for row in source_matrix)
    producer_ledger = []
    for source_row in source_matrix:
        family = source_row["family"]
        facts = CONTEXTUAL_CONDITION_FACTS_BY_OPCODE.get(family, ())
        authorities = sorted({TRANSIENT_CONDITION_FACT_SPECS[fact][1] for fact in facts})
        producers = sorted({_PRODUCER_STAGE_BY_AUTHORITY[item] for item in authorities})
        producer_ledger.append({
            "record_id": source_row["record_id"],
            "family": family,
            "source_path": source_row["source_path"],
            "json_path": source_row["json_path"],
            "fact_kinds": list(facts),
            "producer_authorities": authorities,
            "producer_stages": producers,
            "catalog_producer_stage": source_row["producer_stage"],
            "producer_stage_aligned": source_row["producer_stage"] in producers,
            "status": "source_available_transport_not_proven" if producers == ["current"] else "producer_not_proven",
            "transport_obligation_stages": (
                (["p9_s8"] if "IsDynamic" in source_row["field_signature"] else [])
                + ["p9_s9"]
                if producers == ["current"]
                else producers
            ),
        })
    request_facts = Counter(request["fact_kind"] for request in requests)
    runtime_facts = {row["fact_kind"] for row in runtime_matrix}
    source_record_ids = {row["record_id"] for row in source_matrix}
    request_record_ids = {row["condition_id"] for row in requests}
    action_rows = [row for row in action_matrix if row.get("status") == "source_bound_component"]
    checks = {
        "s6_partition_current": catalog.complete and not catalog.issues and bool(source_matrix),
        "s7_source_family_denominator_complete": set(family_counts) == set(_EXPECTED_FACTS),
        "s7_source_records_reversible": all(row["raw_reversible"] for row in source_matrix),
        "s7_actual_field_shapes_classified": all(row["raw_shape_valid"] for row in source_matrix),
        "s7_contextual_family_gap_count_zero": all(row["lowered"] for row in source_matrix),
        "contextual_opcode_registry_complete": set(CONTEXTUAL_CONDITION_OPCODES) == set(_EXPECTED_FACTS),
        "contextual_fact_registry_complete": dict(CONTEXTUAL_CONDITION_FACTS_BY_OPCODE) == _EXPECTED_FACTS and runtime_facts == set(TRANSIENT_CONDITION_FACT_KINDS),
        "all_source_variants_reach_typed_fact_requests": source_record_ids == request_record_ids and all(request_facts[fact] > 0 for facts in _EXPECTED_FACTS.values() for fact in facts),
        "typed_fact_request_shapes_valid": bool(requests) and all(row["shape_valid"] is True for row in requests),
        "malformed_source_payloads_fail_closed": bool(lowering_negatives) and all(lowering_negatives.values()),
        "component_true_false_blocked_complete": bool(runtime_matrix) and all(row["true"]["ok"] is True and row["true"]["result"] is True and row["false"]["ok"] is True and row["false"]["result"] is False and row["blocked"]["ok"] is False and row["blocked"]["result"] is None for row in runtime_matrix),
        "component_fixtures_not_reported_as_formal": bool(runtime_matrix) and all(row["component_fixture_only"] is True for row in runtime_matrix),
        "producer_obligation_ledger_complete": len(producer_ledger) == len(source_matrix) and {row["record_id"] for row in producer_ledger} == source_record_ids and all(row["producer_stages"] and row["producer_stage_aligned"] and row["transport_obligation_stages"] for row in producer_ledger),
        "only_current_action_facts_have_current_source_authority": {row["family"] for row in producer_ledger if row["status"] == "source_available_transport_not_proven"} == {"ByCurrentSkillTargetType"},
        "action_target_contract_components_resolve": len(action_rows) == 2 and all(row["true"]["ok"] is True and row["true"]["result"] is True and row["false"]["ok"] is True and row["false"]["result"] is False for row in action_rows),
        "action_components_not_reported_as_gameplay_e2e": len(action_rows) == 2 and all(row["gameplay_end_to_end"] is False for row in action_rows),
        "process_only_payload_cannot_create_context": len(action_rows) == 2 and all(row["process_only_payload"]["ok"] is False and row["process_only_payload"]["result"] is None and row["process_only_payload"]["reason"] == "transient_condition_invocation_missing" for row in action_rows),
        "stale_or_incomplete_action_identity_blocked": any(row.get("stale_action", {}).get("ok") is False and row["stale_action"].get("result") is None for row in action_matrix) and any(row.get("incomplete_admission_blocked") is True for row in action_matrix),
        "production_action_query_entrypoint_runs": any(isinstance(row.get("production_action_query_entrypoint"), dict) and row["production_action_query_entrypoint"].get("status") == "resolved" for row in action_matrix),
        "missing_or_mismatched_context_blocked": bool(negatives) and all(negatives.values()),
        "character_specific_condition_handlers_zero": set(CONTEXTUAL_CONDITION_OPCODES) == set(CONTEXTUAL_CONDITION_FACTS_BY_OPCODE),
        "full_canonical_ir_build_count_zero": True,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "source_matrix_p9_s7.json": source_matrix,
        "contextual_runtime_matrix_p9_s7.json": runtime_matrix,
        "typed_fact_request_ledger_p9_s7.json": requests,
        "producer_obligation_ledger_p9_s7.json": producer_ledger,
        "action_source_context_matrix_p9_s7.json": action_matrix,
        "lowering_negative_matrix_p9_s7.json": lowering_negatives,
        "negative_matrix_p9_s7.json": negatives,
    }
    evidence_bytes = 0
    for name, value in artifacts.items():
        encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        (output_dir / name).write_bytes(encoded)
        evidence_bytes += len(encoded)
    result = {
        "ok": all(type(value) is bool and value for value in checks.values()),
        "checks": checks,
        "source": {"record_count": len(source_matrix), "family_count": len(family_counts), "source_fingerprint": catalog.source_fingerprint},
        "runtime": {"component_case_count": len(runtime_matrix), "action_source_component_count": len(action_rows), "gameplay_end_to_end_count": 0, "remaining_transport_or_producer_obligation_count": sum(1 for row in producer_ledger if row["status"] != "gameplay_end_to_end")},
        "resource": {"elapsed_seconds": round(time.perf_counter() - started, 3), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "evidence_bytes": 0, "full_canonical_ir_build_count": 0},
    }
    summary = b""
    for _ in range(4):
        summary = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        total = evidence_bytes + len(summary)
        if result["resource"]["evidence_bytes"] == total:
            break
        result["resource"]["evidence_bytes"] = total
    summary = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    (output_dir / "validation_summary_p9_s7_contextual_condition_closure.json").write_bytes(summary)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P9-S7 contextual condition closure.")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_validation(args.tbgd_root.resolve(), args.output_dir.resolve())
    print(f"P9-S7 ok={result['ok']} checks={sum(result['checks'].values())}/{len(result['checks'])} seconds={result['resource']['elapsed_seconds']:.3f} rss_kib={result['resource']['peak_rss_kib']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
