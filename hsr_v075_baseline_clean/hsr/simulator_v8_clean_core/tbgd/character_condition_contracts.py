from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from ..rules.condition_contract import (
    CharacterConditionResponsibilityCatalog,
    CharacterConditionResponsibilityIR,
    ConditionResponsibilityIssueIR,
)
from ..rules.evaluator import EXECUTABLE_CONDITION_OPCODES
from ..rules.ir import CharacterAbilityScopeRecordIR
from .character_ability_scope import (
    CharacterAbilityRawSnapshot,
    CharacterAbilityScopeProjectionCatalog,
)


@dataclass(frozen=True)
class _ConditionSpec:
    evaluation_stage: str
    authority: str
    required_context: tuple[str, ...]
    producer_stage: str = "current"


def _spec(
    stage: str,
    authority: str,
    *context: str,
    producer: str = "current",
) -> _ConditionSpec:
    return _ConditionSpec(
        evaluation_stage=stage,
        authority=authority,
        required_context=tuple(sorted(context)),
        producer_stage=producer,
    )


_S6 = "p9_s6b_committed_state"
_S7 = "p9_s7_transient_context"

# This registry defines semantics, not source completeness. The complete current
# family denominator is rebuilt from CharacterAbilityScopeProjectionCatalog.
_MISSING_FAMILY_SPECS: dict[str, _ConditionSpec] = {
    "ByAvatarBaseType": _spec(_S6, "unit_definition", "target.unit.base_type"),
    "ByCasterAliveOrLimbo": _spec(_S6, "lifecycle_state", "caster.lifecycle"),
    "ByCheckModifierCallBackModifierValue": _spec(
        _S7,
        "status_callback",
        "status_callback.modifier_value",
        producer="p9_s10",
    ),
    "ByCompareBP": _spec(_S6, "battle_resource", "battle.skill_points"),
    "ByCompareBattleEventID": _spec(
        _S6,
        "unit_definition",
        "target.unit.battle_event_id",
        producer="p9_s17",
    ),
    "ByCompareCurrentSkillEffectIsDamaging": _spec(
        _S7, "action_context", "action.effect_is_damaging"
    ),
    "ByCompareHP": _spec(_S6, "unit_state", "target.unit.hp"),
    "ByCompareMonsterRank": _spec(_S6, "unit_definition", "target.monster.rank"),
    "ByCompareMonsterUniqueID": _spec(
        _S6, "unit_definition", "target.monster.unique_id"
    ),
    "ByCompareNextUnusedInsertAction": _spec(
        _S7, "queue_context", "queue.next_unused_insert_action", producer="p9_s13"
    ),
    "ByCompareParamString": _spec(
        _S7, "event_context", "event.param_string", producer="p9_s9"
    ),
    "ByCompareResistChance": _spec(
        _S6, "status_resistance", "target.status_resistance"
    ),
    "ByCompareSPChangeTag": _spec(
        _S7, "resource_event_context", "resource_change.tags", producer="p9_s12"
    ),
    "ByCompareSomatoType": _spec(_S6, "unit_definition", "target.unit.somato_type"),
    "ByCompareSpecialSPRatio": _spec(
        _S6, "unit_resource", "target.unit.special_resource_ratio"
    ),
    "ByCompareStance": _spec(
        _S6, "toughness_state", "target.toughness.current", producer="p9_s15"
    ),
    "ByCompareStanceCount": _spec(
        _S6, "toughness_state", "target.toughness.segment_count", producer="p9_s15"
    ),
    "ByCompareStanceRatio": _spec(
        _S6, "toughness_state", "target.toughness.ratio", producer="p9_s15"
    ),
    "ByCompareTeamFormationWidth": _spec(
        _S6, "formation_state", "team.formation_width"
    ),
    "ByCompareTurnActionEntityTeamType": _spec(
        _S7, "action_context", "turn.action_entity.team", producer="p9_s13"
    ),
    "ByCompareUnusedInsertAbilityCount": _spec(
        _S7, "queue_context", "queue.unused_insert_ability_count", producer="p9_s13"
    ),
    "ByCompareUnusedUltraSkillCount": _spec(
        _S7, "queue_context", "queue.unused_ultimate_count", producer="p9_s13"
    ),
    "ByContainsRedStance": _spec(
        _S6, "toughness_state", "target.toughness.red_stance", producer="p9_s15"
    ),
    "ByCurrentSkillTargetType": _spec(
        _S7, "action_context", "action.target_contract"
    ),
    "ByDamageSourceContainBehaviorFlag": _spec(
        _S7, "damage_context", "damage.source_behavior_flags", producer="p9_s11"
    ),
    "ByDistance": _spec(_S6, "formation_state", "formation.distance"),
    "ByHasInsertActionByTarget": _spec(
        _S7, "queue_context", "queue.insert_action_targets", producer="p9_s13"
    ),
    "ByHasSummonRelation": _spec(_S6, "entity_relation", "entity.summon_relation"),
    "ByIsBattleEventEntity": _spec(
        _S6, "unit_definition", "target.unit.entity_kind", producer="p9_s17"
    ),
    "ByIsBodyPart": _spec(
        _S6, "entity_relation", "entity.body_part", producer="p9_s17"
    ),
    "ByIsBodyPartOwner": _spec(
        _S6, "entity_relation", "entity.body_part_owner", producer="p9_s17"
    ),
    "ByIsDamageType": _spec(
        _S7, "damage_context", "damage.type", producer="p9_s11"
    ),
    "ByIsEnemy": _spec(_S6, "entity_relation", "entity.combat_team"),
    "ByIsFirstInsertAbilityInQueue": _spec(
        _S7, "queue_context", "queue.first_insert_ability", producer="p9_s13"
    ),
    "ByIsInCharmAction": _spec(
        _S7, "action_context", "action.charm_phase", producer="p9_s16"
    ),
    "ByIsSplitDamage": _spec(
        _S7, "damage_context", "damage.split_semantics", producer="p9_s11"
    ),
    "ByIsSubTargetOfHpSharedGroup": _spec(
        _S6, "entity_relation", "entity.hp_shared_group", producer="p9_s11"
    ),
    "ByIsTargetUnselectable": _spec(
        _S6, "targetability", "target.targetability"
    ),
    "ByIsTurnActionEntity": _spec(
        _S7, "action_context", "turn.action_entity.identity", producer="p9_s13"
    ),
    "ByTargetIsStanceWeak": _spec(
        _S6, "toughness_state", "target.toughness.weakness", producer="p9_s15"
    ),
    "ByTargetListAll": _spec(
        _S6, "target_collection", "target.collection", "target.collection.predicate"
    ),
    "ByTargetListAny": _spec(
        _S6, "target_collection", "target.collection", "target.collection.predicate"
    ),
    "ByTurnOwnerActionPhaseEnd": _spec(
        _S7, "action_context", "turn.owner.action_phase", producer="p9_s13"
    ),
    "ByTurnOwnerHasActionInTurn": _spec(
        _S7, "action_context", "turn.owner.action_history", producer="p9_s13"
    ),
    "ByTurnOwnerHasPendingOneMore": _spec(
        _S7, "action_context", "turn.owner.pending_one_more", producer="p9_s13"
    ),
}


def _signatures(*variants: str) -> tuple[frozenset[str], ...]:
    return tuple(
        frozenset(variant.split()) if variant else frozenset()
        for variant in variants
    )


_MISSING_FAMILY_SIGNATURES: dict[str, tuple[frozenset[str], ...]] = {
    "ByAvatarBaseType": _signatures(
        "BaseTypeKind BaseTypeList TargetType",
        "BaseTypeList Inverse TargetType",
        "BaseTypeList TargetType",
    ),
    "ByCasterAliveOrLimbo": _signatures("AliveStateMask"),
    "ByCheckModifierCallBackModifierValue": _signatures("CompareType CompareValue ValueType"),
    "ByCompareBP": _signatures("CompareType CompareValue"),
    "ByCompareBattleEventID": _signatures("TargetBattleEventID TargetType"),
    "ByCompareCurrentSkillEffectIsDamaging": _signatures("AccessClientActiveSkill"),
    "ByCompareHP": _signatures("CompareType CompareValue TargetType"),
    "ByCompareMonsterRank": _signatures("CompareType CompareValue TargetType"),
    "ByCompareMonsterUniqueID": _signatures(
        "Inverse TargetMonsterUniqueID TargetType", "TargetMonsterUniqueID TargetType"
    ),
    "ByCompareNextUnusedInsertAction": _signatures(
        "ActionTypeIs CasterIs", "CustomTagIs Inverse"
    ),
    "ByCompareParamString": _signatures("CompareValue"),
    "ByCompareResistChance": _signatures(
        "BehaviorFlagList CompareType CompareValue TargetType"
    ),
    "ByCompareSPChangeTag": _signatures("TagList"),
    "ByCompareSomatoType": _signatures("SomatoTypes Target"),
    "ByCompareSpecialSPRatio": _signatures("CompareType CompareValue TargetType"),
    "ByCompareStance": _signatures("CompareType CompareValue TargetType"),
    "ByCompareStanceCount": _signatures("CompareType CompareValue TargetType"),
    "ByCompareStanceRatio": _signatures(
        "CompareType CompareValue IncludeRedStance TargetType"
    ),
    "ByCompareTeamFormationWidth": _signatures("CompareType CompareValue Team"),
    "ByCompareTurnActionEntityTeamType": _signatures("Team"),
    "ByCompareUnusedInsertAbilityCount": _signatures("CompareType CompareValue"),
    "ByCompareUnusedUltraSkillCount": _signatures(
        "CompareType CompareValue IncludeInsertAction",
        "CompareType CompareValue IncludeInsertAction SkillOwnerType",
        "CompareType CompareValue SkillOwnerType",
    ),
    "ByContainsRedStance": _signatures("TargetType"),
    "ByCurrentSkillTargetType": _signatures("IsDynamic", "TargetType"),
    "ByDamageSourceContainBehaviorFlag": _signatures("BehaviorFlags"),
    "ByDistance": _signatures("CompareType CompareValue From To"),
    "ByHasInsertActionByTarget": _signatures("TargetType"),
    "ByHasSummonRelation": _signatures("ServantType SummonerType"),
    "ByIsBattleEventEntity": _signatures(
        "ExpectSubType Inverse TargetType", "Inverse TargetType", "TargetType"
    ),
    "ByIsBodyPart": _signatures("Inverse TargetType", "TargetType"),
    "ByIsBodyPartOwner": _signatures("TargetType"),
    "ByIsDamageType": _signatures("DamageTypeList TargetType"),
    "ByIsEnemy": _signatures("TargetTypeA TargetTypeB"),
    "ByIsFirstInsertAbilityInQueue": _signatures("Inverse"),
    "ByIsInCharmAction": _signatures(""),
    "ByIsSplitDamage": _signatures("Inverse TargetType", "TargetType"),
    "ByIsSubTargetOfHpSharedGroup": _signatures("TargetType"),
    "ByIsTargetUnselectable": _signatures(
        "Inverse SourceEntity TargetType", "Inverse TargetType", "TargetType"
    ),
    "ByIsTurnActionEntity": _signatures("Inverse TargetType", "TargetType"),
    "ByTargetIsStanceWeak": _signatures(
        "AttackerType Inverse TargetType", "AttackerType TargetType"
    ),
    "ByTargetListAll": _signatures("Predicate TargetType"),
    "ByTargetListAny": _signatures(
        "Inverse Predicate TargetType", "Predicate TargetType"
    ),
    "ByTurnOwnerActionPhaseEnd": _signatures("Inverse"),
    "ByTurnOwnerHasActionInTurn": _signatures(""),
    "ByTurnOwnerHasPendingOneMore": _signatures("Inverse"),
}

_EXISTING_COMMITTED_CHILDREN = frozenset(
    {
        "ByCompareModifierValue",
        "ByCompareTarget",
        "ByContainBehaviorFlag",
        "ByIsContainModifier",
        "ByTargetAliveState",
    }
)


def character_condition_family_stage(opcode: str, raw: Mapping[str, Any]) -> str:
    """Return the planned evaluator stage without claiming source completeness."""

    if opcode in EXECUTABLE_CONDITION_OPCODES:
        return "existing_family"
    spec = _MISSING_FAMILY_SPECS.get(opcode)
    signatures = _MISSING_FAMILY_SIGNATURES.get(opcode)
    if spec is None or signatures is None:
        return "blocked_unclassified"
    signature = frozenset(key for key in raw if key != "$type")
    if signature not in signatures:
        return "blocked_unclassified"
    return spec.evaluation_stage


def character_condition_family_blocked_reason(
    opcode: str, raw: Mapping[str, Any]
) -> str:
    if opcode in EXECUTABLE_CONDITION_OPCODES:
        return ""
    spec = _MISSING_FAMILY_SPECS.get(opcode)
    signatures = _MISSING_FAMILY_SIGNATURES.get(opcode)
    if spec is None or signatures is None:
        return f"condition_family_unclassified:{opcode}"
    signature = frozenset(key for key in raw if key != "$type")
    if signature not in signatures:
        return f"condition_field_signature_unclassified:{opcode}"
    stage = spec.evaluation_stage
    return f"condition_deferred_to_{stage}:{opcode}"


def build_character_condition_responsibility_catalog(
    snapshot: CharacterAbilityRawSnapshot,
    scope_catalog: CharacterAbilityScopeProjectionCatalog,
) -> CharacterConditionResponsibilityCatalog:
    if type(snapshot) is not CharacterAbilityRawSnapshot:
        raise TypeError("condition responsibility requires an exact raw snapshot")
    if type(scope_catalog) is not CharacterAbilityScopeProjectionCatalog:
        raise TypeError("condition responsibility requires an exact scope catalog")
    if (
        snapshot.source_fingerprint != scope_catalog.source_fingerprint
        or snapshot.snapshot_id != scope_catalog.snapshot_id
        or not snapshot.source_catalog_complete
        or not scope_catalog.scope_reconciliation_complete
    ):
        raise ValueError("condition responsibility source catalog is not closed")

    nodes, parents = _index_source_nodes(snapshot)
    records_by_source: dict[str, list[CharacterAbilityScopeRecordIR]] = defaultdict(list)
    for record in scope_catalog.scope_records:
        records_by_source[record.source.source_path].append(record)

    condition_records = tuple(
        sorted(
            (
                record
                for record in scope_catalog.gameplay_records
                if record.occurrence_kind == "typed_node"
                and record.source.evidence.get("nominal_semantic_kind")
                == "combat_condition"
            ),
            key=lambda item: item.record_id,
        )
    )
    existing_ids: list[str] = []
    responsibilities: list[CharacterConditionResponsibilityIR] = []
    issues: list[ConditionResponsibilityIssueIR] = []
    for record in condition_records:
        if record.family in EXECUTABLE_CONDITION_OPCODES:
            existing_ids.append(record.record_id)
            continue
        source_path = record.source.source_path
        json_path = str(record.source.evidence["json_path"])
        node_path = json_path.removesuffix(".$type")
        raw = nodes.get((source_path, node_path))
        if not isinstance(raw, Mapping):
            issues.append(
                ConditionResponsibilityIssueIR(
                    "condition_source_node_missing",
                    record.record_id,
                    f"{source_path}:{node_path}",
                )
            )
            responsibilities.append(_blocked_row(record, ()))
            continue
        signature = tuple(sorted(key for key in raw if key != "$type"))
        spec = _MISSING_FAMILY_SPECS.get(record.family)
        signatures = _MISSING_FAMILY_SIGNATURES.get(record.family)
        if spec is None or signatures is None:
            issues.append(
                ConditionResponsibilityIssueIR(
                    "condition_family_unclassified",
                    record.record_id,
                    record.family,
                )
            )
            responsibilities.append(_blocked_row(record, signature))
            continue
        if frozenset(signature) not in signatures:
            issues.append(
                ConditionResponsibilityIssueIR(
                    "condition_field_signature_unclassified",
                    record.record_id,
                    ",".join(signature) or "<empty>",
                )
            )
            responsibilities.append(_blocked_row(record, signature))
            continue
        presentation_basis = _presentation_scope_basis(
            source_path,
            node_path,
            nodes,
            parents,
            records_by_source[source_path],
        )
        if presentation_basis:
            responsibilities.append(
                CharacterConditionResponsibilityIR(
                    record_id=record.record_id,
                    opcode=record.family,
                    evaluation_stage="excluded_non_gameplay",
                    authority="presentation_only",
                    required_context=(),
                    producer_stage="none",
                    field_signature=signature,
                    scope_basis=presentation_basis,
                    source=record.source,
                )
            )
            continue
        resolved_spec, nested_issue = _resolved_spec(raw, spec)
        if nested_issue:
            issues.append(
                ConditionResponsibilityIssueIR(
                    "condition_nested_responsibility_unclassified",
                    record.record_id,
                    nested_issue,
                )
            )
            responsibilities.append(_blocked_row(record, signature))
            continue
        responsibilities.append(
            CharacterConditionResponsibilityIR(
                record_id=record.record_id,
                opcode=record.family,
                evaluation_stage=cast(Any, resolved_spec.evaluation_stage),
                authority=cast(Any, resolved_spec.authority),
                required_context=resolved_spec.required_context,
                producer_stage=resolved_spec.producer_stage,
                field_signature=signature,
                scope_basis="scope_catalog_gameplay_candidate",
                source=record.source,
            )
        )

    return CharacterConditionResponsibilityCatalog(
        source_fingerprint=snapshot.source_fingerprint,
        condition_record_ids=tuple(sorted(record.record_id for record in condition_records)),
        existing_family_record_ids=tuple(sorted(existing_ids)),
        responsibilities=tuple(responsibilities),
        issues=tuple(issues),
    )


def _blocked_row(
    record: CharacterAbilityScopeRecordIR,
    signature: tuple[str, ...],
) -> CharacterConditionResponsibilityIR:
    return CharacterConditionResponsibilityIR(
        record_id=record.record_id,
        opcode=record.family,
        evaluation_stage="blocked_unclassified",
        authority="unclassified",
        required_context=(),
        producer_stage="none",
        field_signature=signature,
        scope_basis="source_responsibility_unclassified",
        source=record.source,
    )


def _resolved_spec(
    raw: Mapping[str, Any],
    base_spec: _ConditionSpec,
) -> tuple[_ConditionSpec, str]:
    opcode = _short_type(raw.get("$type"))
    children: list[Mapping[str, Any]] = []
    if opcode in {"ByAnd", "ByAny"}:
        values = raw.get("PredicateList")
        if not isinstance(values, (list, tuple)):
            return base_spec, f"{opcode}:predicate_list_invalid"
        children.extend(value for value in values if isinstance(value, Mapping))
        if len(children) != len(values):
            return base_spec, f"{opcode}:predicate_child_invalid"
    elif opcode == "ByNot":
        child = raw.get("Predicate")
        if not isinstance(child, Mapping):
            return base_spec, f"{opcode}:predicate_child_invalid"
        children.append(child)
    elif opcode in {"ByTargetListAny", "ByTargetListAll"}:
        child = raw.get("Predicate")
        if not isinstance(child, Mapping):
            return base_spec, f"{opcode}:predicate_child_invalid"
        children.append(child)
    if not children:
        return base_spec, ""

    stage = base_spec.evaluation_stage
    contexts = set(base_spec.required_context)
    producer = base_spec.producer_stage

    def merge_child_spec(child_spec: _ConditionSpec) -> str:
        nonlocal stage, producer
        child_producer = child_spec.producer_stage
        if (
            producer != "current"
            and child_producer != "current"
            and producer != child_producer
        ):
            return f"multiple_condition_producers:{producer},{child_producer}"
        if producer == "current" and child_producer != "current":
            producer = child_producer
        if child_spec.evaluation_stage == _S7:
            stage = _S7
        return ""

    for child in children:
        child_opcode = _short_type(child.get("$type"))
        if child_opcode in _MISSING_FAMILY_SPECS:
            child_signature = frozenset(key for key in child if key != "$type")
            if child_signature not in _MISSING_FAMILY_SIGNATURES[child_opcode]:
                return base_spec, f"{child_opcode}:field_signature_unclassified"
            child_spec, issue = _resolved_spec(
                child, _MISSING_FAMILY_SPECS[child_opcode]
            )
            if issue:
                return base_spec, issue
            contexts.update(child_spec.required_context)
            if issue := merge_child_spec(child_spec):
                return base_spec, issue
        elif child_opcode in {"ByAnd", "ByAny", "ByNot", "ByCompareDynamicValue"}:
            child_spec, issue = _resolved_spec(
                child,
                _spec(_S6, "unit_state", "condition.composite_child"),
            )
            if issue:
                return base_spec, issue
            contexts.update(child_spec.required_context)
            if issue := merge_child_spec(child_spec):
                return base_spec, issue
        elif child_opcode in EXECUTABLE_CONDITION_OPCODES:
            if child_opcode not in _EXISTING_COMMITTED_CHILDREN:
                return base_spec, f"{child_opcode}:nested_context_unclassified"
            contexts.add(f"condition.child:{child_opcode}")
        else:
            return base_spec, f"{child_opcode or '<missing>'}:family_unclassified"
    return _ConditionSpec(
        evaluation_stage=stage,
        authority=base_spec.authority,
        required_context=tuple(sorted(contexts)),
        producer_stage=producer,
    ), ""


def _short_type(value: object) -> str:
    return str(value or "").rsplit(".", 1)[-1]


def _child_path(path: str, key: object) -> str:
    return f"{path}.{key}"


def _index_source_nodes(
    snapshot: CharacterAbilityRawSnapshot,
) -> tuple[
    dict[tuple[str, str], Mapping[str, Any]],
    dict[tuple[str, str], str | None],
]:
    nodes: dict[tuple[str, str], Mapping[str, Any]] = {}
    parents: dict[tuple[str, str], str | None] = {}

    def walk(source_path: str, value: Any, path: str, parent: str | None) -> None:
        if isinstance(value, Mapping):
            nodes[(source_path, path)] = value
            parents[(source_path, path)] = parent
            for key, child in value.items():
                walk(source_path, child, _child_path(path, key), path)
        elif isinstance(value, (list, tuple)):
            parents[(source_path, path)] = parent
            for index, child in enumerate(value):
                walk(source_path, child, f"{path}[{index}]", path)

    for source_path, document in snapshot.documents.items():
        walk(source_path, document, "$", None)
    return nodes, parents


def _presentation_scope_basis(
    source_path: str,
    node_path: str,
    nodes: Mapping[tuple[str, str], Mapping[str, Any]],
    parents: Mapping[tuple[str, str], str | None],
    source_records: list[CharacterAbilityScopeRecordIR],
) -> str:
    current = parents.get((source_path, node_path))
    while current is not None:
        if current.rsplit(".", 1)[-1] == "ModifierAffectedPreshowConfig":
            return "presentation_structural_container:ModifierAffectedPreshowConfig"
        container = nodes.get((source_path, current))
        if isinstance(container, Mapping) and (
            node_path.startswith(f"{current}.Predicate")
            or node_path.startswith(f"{current}.Condition")
        ):
            branch_prefixes = tuple(
                f"{current}.{key}"
                for key in ("TaskList", "SuccessTaskList", "FailedTaskList")
                if key in container
            )
            if branch_prefixes:
                controlled = tuple(
                    record
                    for record in source_records
                    if any(
                        str(record.source.evidence["json_path"]).startswith(prefix)
                        for prefix in branch_prefixes
                    )
                )
                semantic_sinks = tuple(
                    record
                    for record in controlled
                    if (
                        record.source.evidence.get("nominal_semantic_kind")
                        not in {"combat_condition", "contextual_data"}
                        and not (
                            record.source.evidence.get("nominal_semantic_kind")
                            == "combat_control_flow"
                            and record.family == "PredicateTaskList"
                        )
                    )
                )
                if semantic_sinks and all(
                    record.effective_scope == "non_gameplay"
                    for record in semantic_sinks
                ):
                    return "presentation_only_controlled_task_branches"
        current = parents.get((source_path, current))
    return ""


def condition_responsibility_registry_families() -> tuple[str, ...]:
    return tuple(sorted(_MISSING_FAMILY_SPECS))
