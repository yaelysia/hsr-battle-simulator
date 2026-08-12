from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from ..ir_types import IRSource, JSONValue
from ..rules.control_flow_contract import (
    CharacterControlFlowContractCatalog,
    CharacterControlFlowNodeIR,
    ControlFlowBranchIR,
    ControlFlowChildSourceIR,
    ControlFlowContractIssueIR,
    ControlFlowFieldResponsibilityIR,
    ControlFlowTemplateDefinitionIR,
    ControlFlowTemplateParameterIR,
    ControlFlowTemplateReferenceIR,
    ControlFlowTerminationIR,
)
from ..rules.expression_ir import is_exact_numeric_expression
from ..rules.ir import (
    CharacterAbilityScopeRecordIR,
    character_ability_scope_record_id,
)
from .character_ability_scope import (
    CharacterAbilityRawSnapshot,
    CharacterAbilityScopeProjectionCatalog,
    character_ability_semantic_kind,
)
from .expression_lowering import lower_numeric_expression


_GLOBAL_TEMPLATE_DIR = "Config/ConfigGlobalTaskListTemplate"
_COMPLETED_OWNERS = frozenset({"excluded", "p9_s4", "p9_s5b", "p9_s6b", "p9_s8a"})
_NON_GAMEPLAY_SEMANTICS = frozenset(
    {"presentation_only", "client_only_excluded", "ai_excluded", "telemetry_excluded"}
)

# These families remain owned by their original gameplay domain. Only source
# occurrences carrying one of these continuation fields join the task graph.
_HYBRID_BRANCH_FIELDS: dict[str, tuple[str, ...]] = {
    "AddBuffPerform": ("TaskList",),
    "AddModifier": ("SuccessTaskList", "FailTaskList"),
    "AddWeakByTeamAttackType": ("OnNoNewWeak",),
    "CharacterChangeModel": ("OnSuccess",),
    "CreateBattleEvent": ("OnBattleEventCreate",),
    "GLOABNLLLEL": ("TaskList",),
    "Remodifier": ("TaskList",),
    "Retarget": ("TaskList", "FailedTaskList"),
    "SortTargets": ("TaskList",),
    "TurnInsertAction": ("OnInsertAbort",),
}
_PRESENTATION_FALLBACK_OWNER = {
    ("FireWaveProjectile", "OnProjectileHitClientOnly"): "p9_s8c",
}


def _rules(
    responsibility: str,
    owner_stage: str,
    *fields: str,
) -> dict[str, tuple[str, str, bool]]:
    return {field: (responsibility, owner_stage, True) for field in fields}


_FIELD_RULES: dict[str, dict[str, tuple[str, str, bool]]] = {
    "AddBuffPerform": {
        **_rules("presentation_excluded", "excluded", "AddPerformTime"),
        **_rules("target_contract", "p9_s5b", "TargetType"),
        **_rules("child_graph", "p9_s8b", "TaskList"),
    },
    "AddModifier": {
        **_rules("numeric_contract", "p9_s10", "Chance", "LayerAddWhenStack", "LifeStepImmediately", "LifeTime", "MaxLayer"),
        **_rules("dynamic_context_contract", "p9_s4", "DynamicValues"),
        **_rules("downstream_gameplay", "p9_s10", "ModifierName"),
        **_rules("target_contract", "p9_s5b", "TargetType"),
        **_rules("child_graph", "p9_s8b", "SuccessTaskList", "FailTaskList"),
    },
    "AddWeakByTeamAttackType": {
        **_rules("numeric_contract", "p9_s10", "AddWeakCountMax", "ResistanceDeltaValue"),
        **_rules("downstream_gameplay", "p9_s10", "PreferWeak", "ReturnWeakType"),
        **_rules("presentation_excluded", "excluded", "BlockUIRefresh"),
        **_rules("target_contract", "p9_s5b", "TargetType"),
        **_rules("child_graph", "p9_s8b", "OnNoNewWeak"),
    },
    "ByCompareDynamicValue": {
        **_rules("condition_contract", "p9_s6b", "CompareType", "ContextScope", "Inverse"),
        **_rules("numeric_contract", "p9_s4", "CompareValue", "DynamicKey"),
        **_rules("target_contract", "p9_s5b", "TargetType"),
    },
    "ByDieAnimFinished": _rules("downstream_gameplay", "p9_s14", "EntityTypeMask", "TeamTypeMask"),
    "CharacterChangeModel": {
        **_rules("presentation_excluded", "excluded", "IsAsyncLoad", "PrefabPath"),
        **_rules("child_graph", "p9_s8b", "OnSuccess"),
    },
    "ConditionLoopExecuteTaskList": {
        **_rules("condition_contract", "p9_s6b", "Predicate"),
        **_rules("child_graph", "p9_s8b", "TaskList"),
        **_rules("numeric_contract", "p9_s8b", "MaxLoopCount"),
    },
    "ConditionLoopExecuteTaskListWithInterval": {
        **_rules("condition_contract", "p9_s6b", "Predicate"),
        **_rules("child_graph", "p9_s8b", "TaskList"),
        **_rules("numeric_contract", "p9_s8b", "MaxLoopCount"),
    },
    "DamagePerformFinish": _rules(
        "downstream_gameplay", "p9_s11", "IsFakeAvatarAttack", "SkipDeathSettlement"
    ),
    "CreateBattleEvent": {
        **_rules("downstream_gameplay", "p9_s9", "AllowDuplicate", "EventID", "IsDynamicPreload", "PropertyFromTarget", "SpecifyCaster", "Team"),
        **_rules("child_graph", "p9_s8b", "OnBattleEventCreate"),
    },
    "FireMultiProjectiles": {
        **_rules("target_contract", "p9_s5b", "CasterTargetType", "TargetType"),
        **_rules("control_structure", "p9_s8c", "ProjectileConfigList"),
        **_rules("child_graph", "p9_s8c", "ProjectileOnHitList"),
    },
    "FireProjectile": {
        **_rules("target_contract", "p9_s5b", "CustomAnchorTarget", "TargetType"),
        **_rules("control_structure", "p9_s8c", "MaxNumber", "Projectile", "WaitProjectileFinish"),
        **_rules("child_graph", "p9_s8c", "OnProjectileHit"),
    },
    "FireWaveProjectile": {
        **_rules("target_contract", "p9_s5b", "CasterTargetType", "TargetType"),
        **_rules("control_structure", "p9_s8c", "Count", "Interval", "Projectile", "WaitProjectileFinish"),
        **_rules("downstream_gameplay", "p9_s11", "PerProjectileDamage"),
        **_rules("presentation_excluded", "excluded", "OnProjectileHitClientOnly"),
    },
    "GoNextTargetInList": {},
    "GLOABNLLLEL": {
        **_rules("control_structure", "p9_s8c", "ByRandom"),
        **_rules("condition_contract", "p9_s6b", "Predicate"),
        **_rules("numeric_contract", "p9_s5b", "MaxNumber"),
        **_rules("target_contract", "p9_s5b", "IncludeLimbo", "TargetType"),
        **_rules("child_graph", "p9_s8b", "TaskList"),
    },
    "IncludeGlobalTaskListTemplate": {
        **_rules("control_structure", "p9_s8a", "Name"),
        **_rules("dynamic_context_contract", "p9_s4", "DynamicStrings", "DynamicValues"),
    },
    "IncludeTaskListTemplate": {
        **_rules("control_structure", "p9_s8a", "Name"),
        **_rules("dynamic_context_contract", "p9_s4", "DynamicStrings", "DynamicValues"),
        **_rules("target_contract", "p9_s5b", "ParamTarget"),
        **_rules("child_graph", "p9_s8b", "TemplateParamSequences"),
    },
    "LoopExecuteTaskList": {
        **_rules("numeric_contract", "p9_s8b", "MaxLoopCount"),
        **_rules("child_graph", "p9_s8b", "TaskList"),
    },
    "LoopExecuteTaskListWithInterval": {
        **_rules("numeric_contract", "p9_s8b", "MaxLoopCount"),
        **_rules("child_graph", "p9_s8b", "TaskList"),
        **_rules("presentation_excluded", "excluded", "PreciseTime"),
    },
    "LoopTargetList": _rules("child_graph", "p9_s8b", "TaskList"),
    "MakeSuccess": _rules("child_graph", "p9_s8b", "Task"),
    "NewFireProjectile": {
        **_rules("presentation_excluded", "excluded", "DisplayData"),
        **_rules("control_structure", "p9_s8c", "MaxNumber", "NewProjectile", "WaitProjectileFinish"),
        **_rules("child_graph", "p9_s8c", "OnProjectileHit"),
        **_rules("target_contract", "p9_s5b", "TargetType"),
    },
    "PauseToTurnEnd": _rules("control_structure", "p9_s13", "Pause"),
    "PerformDelayExecute": {
        **_rules("numeric_contract", "p9_s8c", "Delay"),
        **_rules("child_graph", "p9_s8b", "PerformTaskList"),
        **_rules("target_contract", "p9_s5b", "TargetType"),
    },
    "PredicateTaskList": {
        **_rules("condition_contract", "p9_s6b", "Predicate"),
        **_rules("child_graph", "p9_s8b", "SuccessTaskList", "FailedTaskList"),
    },
    "PredicateToMakeFail": {
        **_rules("condition_contract", "p9_s6b", "Predicate"),
        **_rules("child_graph", "p9_s8b", "OnSuccess"),
    },
    "RandomConfig": {
        **_rules("numeric_contract", "p9_s8c", "OddsList"),
        **_rules("child_graph", "p9_s8c", "TaskList"),
    },
    "SkillPerformFinish": _rules("downstream_gameplay", "p9_s11", "SkipAttackSettlement"),
    "Remodifier": {
        **_rules("condition_contract", "p9_s10", "BehaviorFlagFilter", "CasterFilter", "PredicateFilter", "StatusTypeMask"),
        **_rules("downstream_gameplay", "p9_s10", "ModifierName"),
        **_rules("numeric_contract", "p9_s10", "MaxNumber"),
        **_rules("target_contract", "p9_s5b", "TargetType"),
        **_rules("child_graph", "p9_s8b", "TaskList"),
    },
    "Retarget": {
        **_rules("control_structure", "p9_s8c", "ByRandom", "IgnoreParallelWarning"),
        **_rules("condition_contract", "p9_s6b", "Predicate"),
        **_rules("numeric_contract", "p9_s5b", "MaxNumber"),
        **_rules("target_contract", "p9_s5b", "IncludeLimbo", "TargetType"),
        **_rules("child_graph", "p9_s8b", "TaskList", "FailedTaskList"),
    },
    "SortTargets": {
        **_rules("control_structure", "p9_s5b", "SortConfig"),
        **_rules("numeric_contract", "p9_s5b", "MaxNumber"),
        **_rules("target_contract", "p9_s5b", "IncludeLimbo", "TargetType"),
        **_rules("child_graph", "p9_s8b", "TaskList"),
    },
    "SwitchByCommandType": {},
    "SwitchCaseByAttackDamageType": {
        **_rules("child_graph", "p9_s8b", "CaseTaskList"),
        **_rules("target_contract", "p9_s5b", "Source"),
    },
    "SwitchCaseByDynamicValue": {
        **_rules("child_graph", "p9_s8b", "CaseTaskList"),
        **_rules("child_graph", "p9_s8b", "DefaultTaskList"),
        **_rules("numeric_contract", "p9_s4", "Switch"),
        **_rules("control_structure", "p9_s8b", "CompareType"),
    },
    "TriggerAbility": {
        **_rules("ability_source_contract", "p9_s8b", "AbilityName"),
        **_rules("control_structure", "p9_s8b", "IsSkillPerform"),
        **_rules("target_contract", "p9_s5b", "AbilityInherentTargetType", "TargetType"),
    },
    "TriggerParallelTaskListTemplate": _rules("control_structure", "p9_s8c", "Templates"),
    "TriggerSkipDeadHandler": {},
    "TaskTemplateFetchParamSequence": _rules("control_structure", "p9_s8b", "ParamName"),
    "TurnInsertAction": {
        **_rules("condition_contract", "p9_s6b", "ActivePredicate", "PreCheck"),
        **_rules("dynamic_context_contract", "p9_s4", "DynamicStrings", "DynamicValues"),
        **_rules("target_contract", "p9_s5b", "AutoCastTargetType", "TargetType"),
        **_rules("control_structure", "p9_s13", "AbortBehaviorFlags", "AutoCast", "CanInsertUltraSkill", "CopyAbortContext", "CustomTag", "FollowSameTagNormalAction", "IgnoreBPDec", "PrepareAbilityName", "SkillIndex", "SkillType"),
        **_rules("child_graph", "p9_s8b", "OnInsertAbort"),
    },
    "TurnInsertAbilityCondition": _rules("downstream_gameplay", "p9_s13", "Count", "Type"),
    "WaitAnimState": _rules(
        "presentation_excluded",
        "excluded",
        "AnimStateName",
        "IgnoreStateChangeCheck",
        "NormalizedTimeEnd",
        "SkipWhenStateChange",
        "SyncVCameraTime",
        "TargetType",
        "WaitForFrameEnd",
    ),
    "WaitFor": _rules("condition_contract", "p9_s8b", "Predicate"),
    "WaitFrame": _rules("presentation_excluded", "excluded", "RealFrame", "WaitFrameCount"),
    "WaitFrameForBattleServer": {},
    "WaitCustomString": _rules("control_structure", "p9_s8c", "CustomString", "GoNextImmediately"),
    "WaitForTurnEnd": _rules("control_structure", "p9_s13", "GoNextImmediately"),
    "WaitSecond": _rules("presentation_excluded", "excluded", "IsRealtime", "WaitTime"),
    "WaitTimelineFinish": _rules(
        "presentation_excluded", "excluded", "IgnoreWarning", "TimelineName", "TriggerBeforeFinish"
    ),
}


_ROLE_BY_FAMILY = {
    "AddBuffPerform": "presentation_child_wrapper",
    "AddModifier": "effect_continuation",
    "AddWeakByTeamAttackType": "effect_continuation",
    "ByCompareDynamicValue": "condition_delegate",
    "ByDieAnimFinished": "condition_delegate",
    "CharacterChangeModel": "effect_continuation",
    "ConditionLoopExecuteTaskList": "conditional_loop",
    "ConditionLoopExecuteTaskListWithInterval": "conditional_loop",
    "DamagePerformFinish": "settlement_barrier",
    "CreateBattleEvent": "event_creation_continuation",
    "FireMultiProjectiles": "projectile_sequence",
    "FireProjectile": "projectile_sequence",
    "FireWaveProjectile": "projectile_sequence",
    "GoNextTargetInList": "target_cursor",
    "GLOABNLLLEL": "target_scope",
    "IncludeGlobalTaskListTemplate": "template_include",
    "IncludeTaskListTemplate": "template_include",
    "LoopExecuteTaskList": "counted_loop",
    "LoopExecuteTaskListWithInterval": "counted_loop",
    "LoopTargetList": "target_loop",
    "MakeSuccess": "wrapped_task",
    "NewFireProjectile": "projectile_sequence",
    "PauseToTurnEnd": "turn_barrier",
    "PerformDelayExecute": "delayed_sequence",
    "PredicateTaskList": "predicate_branch",
    "PredicateToMakeFail": "predicate_branch",
    "RandomConfig": "random_branch",
    "SkillPerformFinish": "settlement_barrier",
    "Remodifier": "status_scope",
    "Retarget": "target_scope",
    "SortTargets": "ordered_target_scope",
    "SwitchByCommandType": "event_switch",
    "SwitchCaseByAttackDamageType": "switch_branch",
    "SwitchCaseByDynamicValue": "switch_branch",
    "TriggerAbility": "ability_trigger",
    "TriggerParallelTaskListTemplate": "parallel_templates",
    "TriggerSkipDeadHandler": "death_barrier",
    "TaskTemplateFetchParamSequence": "template_parameter_fetch",
    "TurnInsertAction": "action_abort_continuation",
    "TurnInsertAbilityCondition": "queue_condition",
    "WaitAnimState": "presentation_barrier",
    "WaitFor": "condition_barrier",
    "WaitFrame": "presentation_barrier",
    "WaitFrameForBattleServer": "server_sync_barrier",
    "WaitCustomString": "custom_sync_barrier",
    "WaitForTurnEnd": "turn_barrier",
    "WaitSecond": "presentation_barrier",
    "WaitTimelineFinish": "presentation_barrier",
}


_ROLE_OWNER = {
    "effect_continuation": "p9_s8b",
    "status_scope": "p9_s8b",
    "target_scope": "p9_s8b",
    "ordered_target_scope": "p9_s8b",
    "action_abort_continuation": "p9_s8b",
    "event_creation_continuation": "p9_s8b",
    "template_parameter_fetch": "p9_s8b",
    "conditional_loop": "p9_s8b",
    "counted_loop": "p9_s8b",
    "target_loop": "p9_s8b",
    "wrapped_task": "p9_s8b",
    "predicate_branch": "p9_s8b",
    "switch_branch": "p9_s8b",
    "ability_trigger": "p9_s8b",
    "condition_barrier": "p9_s8b",
    "delayed_sequence": "p9_s8c",
    "custom_sync_barrier": "p9_s8c",
    "server_sync_barrier": "p9_s8c",
    "projectile_sequence": "p9_s8c",
    "random_branch": "p9_s8c",
    "parallel_templates": "p9_s8c",
    "target_cursor": "p9_s8c",
    "presentation_barrier": "p9_s8c",
    "presentation_child_wrapper": "excluded",
    "settlement_barrier": "p9_s11",
    "event_switch": "p9_s9",
    "death_barrier": "p9_s14",
    "queue_condition": "p9_s13",
    "turn_barrier": "p9_s13",
}


@dataclass(frozen=True)
class _TemplateParameterDraft:
    parameter_kind: str
    key: str
    index: int | None
    read_type: str
    declared_value: str
    json_path: str


@dataclass(frozen=True)
class _TemplateDraft:
    template_id: str
    name: str
    scope_kind: str
    namespace_path: str
    task_list_path: str
    source_path: str
    parameters: tuple[_TemplateParameterDraft, ...]
    tasks: tuple[Mapping[str, Any], ...]
    content_sha256: str


@dataclass(frozen=True)
class _TemplateProblem:
    code: str
    source_path: str
    json_path: str
    content_sha256: str
    detail: str


@dataclass(frozen=True)
class _ControlFlowOccurrence:
    occurrence_id: str
    family: str
    semantic_kind: str
    effective_scope: str
    source_path: str
    json_path: str
    content_sha256: str
    raw: Mapping[str, Any]
    source_kind: str
    materialization_role: str


def _stable_id(prefix: str, *parts: object) -> str:
    encoded = json.dumps([str(item) for item in parts], ensure_ascii=True, separators=(",", ":")).encode()
    return f"{prefix}:{sha256(encoded).hexdigest()}"


def _short_type(value: object) -> str:
    return str(value or "").rsplit(".", 1)[-1]


def _typed_subtree_is_non_gameplay(value: object) -> tuple[bool, bool]:
    found = False
    safe = True

    def walk(item: object) -> None:
        nonlocal found, safe
        if isinstance(item, Mapping):
            family = _short_type(item.get("$type"))
            if family:
                found = True
                if character_ability_semantic_kind(family) not in _NON_GAMEPLAY_SEMANTICS:
                    safe = False
            for child in item.values():
                walk(child)
        elif isinstance(item, (tuple, list)):
            for child in item:
                walk(child)

    walk(value)
    return found, safe


def classify_control_flow_materialization_role(
    family: str,
    raw: Mapping[str, Any],
    *,
    occurrence_semantic_kind: str | None = None,
) -> str:
    """Return the occurrence role; an empty string means it is not a task-graph node."""

    if not isinstance(family, str) or not family or not isinstance(raw, Mapping):
        raise TypeError("control-flow materialization classification requires typed source")
    semantic = (
        occurrence_semantic_kind
        if occurrence_semantic_kind is not None
        else character_ability_semantic_kind(family)
    )
    if semantic == "combat_control_flow":
        return "semantic_control"
    if semantic == "simulation_sequence":
        return "semantic_sequence"
    branch_fields = _HYBRID_BRANCH_FIELDS.get(family, ())
    present = tuple(field for field in branch_fields if field in raw)
    if not present:
        return ""
    if semantic == "presentation_only":
        closures = tuple(_typed_subtree_is_non_gameplay(raw[field]) for field in present)
        if closures and all(found and safe for found, safe in closures):
            return "presentation_child_wrapper"
    return "hybrid_child_wrapper"


def _at_path(document: Mapping[str, Any], path: str) -> Any:
    if not path.startswith("$"):
        raise ValueError("control-flow source path must start at the document root")
    value: Any = document
    index = 1
    while index < len(path):
        if path[index] == ".":
            index += 1
            end = index
            while end < len(path) and path[end] not in ".[":
                end += 1
            value = value[path[index:end]]
            index = end
            continue
        if path[index] != "[":
            raise ValueError(f"invalid control-flow source path:{path}")
        end = path.index("]", index)
        token = path[index + 1 : end]
        key: Any = json.loads(token) if token.startswith('"') else int(token)
        value = value[key]
        index = end + 1
    return value


def _object_path(record: CharacterAbilityScopeRecordIR) -> str:
    path = str(record.source.evidence["json_path"])
    return path[: -len(".$type")] if path.endswith(".$type") else path


def _source(
    *,
    source_path: str,
    raw_type: str,
    raw_id: str,
    json_path: str,
    content_sha256: str,
    extra: Mapping[str, JSONValue] | None = None,
) -> IRSource:
    return IRSource(
        source_path=source_path,
        raw_type=raw_type,
        raw_id=raw_id,
        evidence={
            "json_path": json_path,
            "content_sha256": content_sha256,
            **dict(extra or {}),
        },
    )


def classify_control_flow_peer_fields(
    family: str,
    raw: Mapping[str, Any],
    *,
    node_id: str,
    source_path: str,
    json_path: str,
    content_sha256: str,
) -> tuple[tuple[ControlFlowFieldResponsibilityIR, ...], tuple[str, ...]]:
    """Classify every peer field; unknown fields remain explicit and blocking."""

    rules = _FIELD_RULES.get(family)
    materialization_role = classify_control_flow_materialization_role(family, raw)
    fields = tuple(sorted(key for key in raw if key != "$type"))
    blockers: list[str] = []
    responsibilities: list[ControlFlowFieldResponsibilityIR] = []
    for field_name in fields:
        rule = rules.get(field_name) if rules is not None else None
        if rule is None:
            rule = ("unclassified", "p9_s8a", True)
            blockers.append(f"control_flow_peer_field_unclassified:{family}:{field_name}")
        responsibility, owner_stage, covers_subtree = rule
        if (
            field_name in _HYBRID_BRANCH_FIELDS.get(family, ())
            and materialization_role == "presentation_child_wrapper"
        ):
            responsibility, owner_stage = "presentation_excluded", "excluded"
        elif responsibility == "presentation_excluded" and (
            field_name in _HYBRID_BRANCH_FIELDS.get(family, ())
            or (family, field_name) in _PRESENTATION_FALLBACK_OWNER
        ):
            has_typed_child, subtree_is_non_gameplay = _typed_subtree_is_non_gameplay(
                raw[field_name]
            )
            if has_typed_child and not subtree_is_non_gameplay:
                fallback_owner = _PRESENTATION_FALLBACK_OWNER.get(
                    (family, field_name)
                )
                if fallback_owner is None:
                    responsibility, owner_stage = "unclassified", "p9_s8a"
                    blockers.append(
                        f"presentation_exclusion_descendant_not_closed:{family}:{field_name}"
                    )
                else:
                    responsibility, owner_stage = "child_graph", fallback_owner
        responsibilities.append(
            ControlFlowFieldResponsibilityIR(
                field_name=field_name,
                responsibility=cast(Any, responsibility),
                owner_stage=owner_stage,
                covers_subtree=covers_subtree,
                source=_source(
                    source_path=source_path,
                    raw_type=family,
                    raw_id=f"{node_id}:{field_name}",
                    json_path=f"{json_path}.{field_name}",
                    content_sha256=content_sha256,
                    extra={"node_id": node_id, "field_name": field_name},
                ),
            )
        )
    if rules is None:
        blockers.append(f"control_flow_family_unclassified:{family}")
    return tuple(responsibilities), tuple(blockers)


def _branch_specs(
    family: str,
    raw: Mapping[str, Any],
    path: str,
) -> tuple[
    list[tuple[str, str, str, list[tuple[Mapping[str, Any], str]]]],
    tuple[str, ...],
]:
    result: list[tuple[str, str, str, list[tuple[Mapping[str, Any], str]]]] = []
    blockers: list[str] = []

    def task_list(kind: str, field: str, label: str = "") -> None:
        values = raw.get(field)
        if values is None:
            return
        if not isinstance(values, list):
            blockers.append(f"control_flow_branch_list_invalid:{field}")
            result.append((kind, label, f"{path}.{field}", []))
            return
        if any(not isinstance(item, Mapping) for item in values):
            blockers.append(f"control_flow_branch_child_invalid:{field}")
        result.append(
            (
                kind,
                label,
                f"{path}.{field}",
                [(item, f"{path}.{field}[{index}]") for index, item in enumerate(values) if isinstance(item, Mapping)],
            )
        )

    if family == "PredicateTaskList":
        task_list("success", "SuccessTaskList")
        task_list("failed", "FailedTaskList")
    elif family == "IncludeTaskListTemplate":
        sequences = raw.get("TemplateParamSequences")
        if sequences is not None and not isinstance(sequences, Mapping):
            blockers.append("control_flow_template_param_sequences_invalid")
        elif isinstance(sequences, Mapping):
            for name, sequence in sequences.items():
                entry_path = f"{path}.TemplateParamSequences.{name}"
                if not isinstance(name, str) or not name:
                    blockers.append("control_flow_template_param_sequence_name_invalid")
                    continue
                if not isinstance(sequence, Mapping) or set(sequence) != {"TaskList"}:
                    blockers.append(f"control_flow_template_param_sequence_invalid:{name}")
                    result.append(("template_parameter_sequence", name, entry_path, []))
                    continue
                values = sequence.get("TaskList")
                if not isinstance(values, list):
                    blockers.append(f"control_flow_branch_list_invalid:TemplateParamSequences:{name}")
                    result.append(("template_parameter_sequence", name, entry_path, []))
                    continue
                if any(not isinstance(item, Mapping) for item in values):
                    blockers.append(f"control_flow_branch_child_invalid:TemplateParamSequences:{name}")
                result.append(
                    (
                        "template_parameter_sequence",
                        name,
                        entry_path,
                        [
                            (item, f"{entry_path}.TaskList[{index}]")
                            for index, item in enumerate(values)
                            if isinstance(item, Mapping)
                        ],
                    )
                )
    elif family == "TaskTemplateFetchParamSequence":
        name = raw.get("ParamName")
        if not isinstance(name, str) or not name:
            blockers.append("control_flow_template_param_fetch_name_invalid")
            name = "<missing>"
        result.append(("template_parameter_fetch", name, f"{path}.ParamName", []))
    elif family == "AddModifier":
        task_list("effect_success", "SuccessTaskList")
        task_list("effect_failed", "FailTaskList")
    elif family == "AddWeakByTeamAttackType":
        task_list("no_new_weakness", "OnNoNewWeak")
    elif family == "AddBuffPerform":
        task_list("presentation_continuation", "TaskList")
    elif family == "CharacterChangeModel":
        task_list("effect_success", "OnSuccess")
    elif family == "CreateBattleEvent":
        task_list("event_created", "OnBattleEventCreate")
    elif family in {"Retarget", "GLOABNLLLEL"}:
        task_list("target_scope", "TaskList")
        task_list("target_scope_failed", "FailedTaskList")
    elif family == "Remodifier":
        task_list("status_scope", "TaskList")
    elif family == "SortTargets":
        task_list("ordered_target_scope", "TaskList")
    elif family == "TurnInsertAction":
        task_list("insert_abort", "OnInsertAbort")
    elif family == "PerformDelayExecute":
        task_list("delayed_sequence", "PerformTaskList")
    elif family == "PredicateToMakeFail":
        task_list("success", "OnSuccess")
    elif family in {
        "ConditionLoopExecuteTaskList",
        "ConditionLoopExecuteTaskListWithInterval",
        "LoopExecuteTaskList",
        "LoopExecuteTaskListWithInterval",
        "LoopTargetList",
    }:
        task_list("task_list", "TaskList")
    elif family == "RandomConfig":
        values = raw.get("TaskList")
        if isinstance(values, list):
            for index, item in enumerate(values):
                if not isinstance(item, Mapping):
                    blockers.append(f"control_flow_branch_child_invalid:TaskList[{index}]")
                item_path = f"{path}.TaskList[{index}]"
                result.append(("random_candidate", str(index), item_path, [(item, item_path)] if isinstance(item, Mapping) else []))
        elif values is not None:
            blockers.append("control_flow_branch_list_invalid:TaskList")
            result.append(("random_candidate", "invalid", f"{path}.TaskList", []))
    elif family in {"SwitchCaseByAttackDamageType", "SwitchCaseByDynamicValue"}:
        cases = raw.get("CaseTaskList")
        if isinstance(cases, list):
            for index, case in enumerate(cases):
                if not isinstance(case, Mapping):
                    blockers.append(f"control_flow_case_invalid:CaseTaskList[{index}]")
                    result.append(("case", str(index), f"{path}.CaseTaskList[{index}]", []))
                    continue
                tasks = case.get("TaskList")
                if not isinstance(tasks, list):
                    blockers.append(f"control_flow_branch_list_invalid:CaseTaskList[{index}].TaskList")
                elif any(not isinstance(item, Mapping) for item in tasks):
                    blockers.append(f"control_flow_branch_child_invalid:CaseTaskList[{index}].TaskList")
                label = json.dumps(case.get("Case"), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                result.append(
                    (
                        "case",
                        label,
                        f"{path}.CaseTaskList[{index}]",
                        [(item, f"{path}.CaseTaskList[{index}].TaskList[{child_index}]") for child_index, item in enumerate(tasks) if isinstance(item, Mapping)] if isinstance(tasks, list) else [],
                    )
                )
        elif cases is not None:
            blockers.append("control_flow_branch_list_invalid:CaseTaskList")
            result.append(("case", "invalid", f"{path}.CaseTaskList", []))
        task_list("default", "DefaultTaskList")
    elif family in {"FireProjectile", "NewFireProjectile"}:
        task_list("projectile_hit", "OnProjectileHit")
    elif family == "FireMultiProjectiles":
        rows = raw.get("ProjectileOnHitList")
        if isinstance(rows, list):
            for index, row in enumerate(rows):
                tasks = row.get("OnProjectileHit") if isinstance(row, Mapping) else None
                if not isinstance(row, Mapping):
                    blockers.append(f"control_flow_projectile_hit_row_invalid:{index}")
                elif not isinstance(tasks, list):
                    blockers.append(f"control_flow_branch_list_invalid:ProjectileOnHitList[{index}].OnProjectileHit")
                elif any(not isinstance(item, Mapping) for item in tasks):
                    blockers.append(f"control_flow_branch_child_invalid:ProjectileOnHitList[{index}].OnProjectileHit")
                result.append(
                    (
                        "projectile_hit",
                        str(index),
                        f"{path}.ProjectileOnHitList[{index}]",
                        [(item, f"{path}.ProjectileOnHitList[{index}].OnProjectileHit[{child_index}]") for child_index, item in enumerate(tasks) if isinstance(item, Mapping)] if isinstance(tasks, list) else [],
                    )
                )
        elif rows is not None:
            blockers.append("control_flow_branch_list_invalid:ProjectileOnHitList")
            result.append(("projectile_hit", "invalid", f"{path}.ProjectileOnHitList", []))
    elif family == "MakeSuccess":
        task = raw.get("Task")
        if not isinstance(task, Mapping):
            blockers.append("control_flow_wrapped_task_invalid:Task")
        result.append(("wrapped_task", "", f"{path}.Task", [(task, f"{path}.Task")] if isinstance(task, Mapping) else []))
    return result, tuple(blockers)


def _termination(node_id: str, family: str, raw: Mapping[str, Any], source: IRSource) -> ControlFlowTerminationIR:
    if family in {"LoopExecuteTaskList", "LoopExecuteTaskListWithInterval"}:
        expression = lower_numeric_expression(raw.get("MaxLoopCount"))
        valid = is_exact_numeric_expression(expression) and expression.get("supported") is True
        return ControlFlowTerminationIR(
            node_id,
            "count_expression",
            "source_backed" if valid else "blocked",
            "p9_s8b",
            expression,
            "" if valid else "loop_count_expression_not_lowered",
            source,
        )
    if family in {"ConditionLoopExecuteTaskList", "ConditionLoopExecuteTaskListWithInterval"}:
        if "MaxLoopCount" in raw:
            expression = lower_numeric_expression(raw.get("MaxLoopCount"))
            valid = is_exact_numeric_expression(expression) and expression.get("supported") is True
            return ControlFlowTerminationIR(
                node_id,
                "condition_with_source_cap",
                "source_backed" if valid else "blocked",
                "p9_s8b",
                expression,
                "" if valid else "conditional_loop_cap_not_lowered",
                source,
            )
        return ControlFlowTerminationIR(
            node_id,
            "condition_progress_required",
            "runtime_proof_required",
            "p9_s8b",
            None,
            "",
            source,
        )
    if family == "LoopTargetList":
        return ControlFlowTerminationIR(
            node_id,
            "finite_target_collection",
            "source_backed",
            "p9_s8b",
            None,
            "",
            source,
        )
    return ControlFlowTerminationIR(
        node_id,
        "not_applicable",
        "not_applicable",
        "p9_s8a",
        None,
        "",
        source,
    )


def _template_parameters(
    raw: Mapping[str, Any],
    template_path: str,
) -> tuple[tuple[_TemplateParameterDraft, ...], str]:
    result: list[_TemplateParameterDraft] = []
    dynamic_values = raw.get("DynamicValues")
    if dynamic_values is not None:
        if not isinstance(dynamic_values, Mapping) or set(dynamic_values) != {"Floats"}:
            return (), "dynamic_values_schema_invalid"
        floats = dynamic_values.get("Floats")
        if not isinstance(floats, Mapping):
            return (), "dynamic_float_parameters_invalid"
        for key, value in floats.items():
            if not isinstance(key, str) or not key or not isinstance(value, Mapping) or set(value) != {"ReadInfo"}:
                return (), "dynamic_float_parameter_invalid"
            read_info = value.get("ReadInfo")
            if not isinstance(read_info, Mapping) or set(read_info) != {"Index", "Type"}:
                return (), "dynamic_float_read_info_invalid"
            index = read_info.get("Index")
            read_type = read_info.get("Type")
            if type(index) is not int or index < 0 or not isinstance(read_type, str) or not read_type:
                return (), "dynamic_float_read_info_invalid"
            result.append(
                _TemplateParameterDraft(
                    "dynamic_float",
                    key,
                    index,
                    read_type,
                    "",
                    f"{template_path}.DynamicValues.Floats[{json.dumps(key, ensure_ascii=True)}]",
                )
            )
    dynamic_strings = raw.get("DynamicStrings")
    if dynamic_strings is not None:
        if not isinstance(dynamic_strings, Mapping):
            return (), "dynamic_string_parameters_invalid"
        for key, value in dynamic_strings.items():
            if not isinstance(key, str) or not key or not isinstance(value, str):
                return (), "dynamic_string_parameter_invalid"
            result.append(
                _TemplateParameterDraft(
                    "dynamic_string",
                    key,
                    None,
                    "",
                    value,
                    f"{template_path}.DynamicStrings[{json.dumps(key, ensure_ascii=True)}]",
                )
            )
    return tuple(sorted(result, key=lambda item: (item.parameter_kind, item.key))), ""


def _discover_local_templates(
    snapshot: CharacterAbilityRawSnapshot,
) -> tuple[list[_TemplateDraft], list[_TemplateProblem]]:
    drafts: list[_TemplateDraft] = []
    problems: list[_TemplateProblem] = []
    hashes = {item.source.source_path: item.content_sha256 for item in snapshot.sources}

    def walk(source_path: str, value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for field_name, scope_kind in (("GlobalTemplates", "document_global"), ("TaskListTemplate", "local")):
                raw_templates = value.get(field_name)
                if raw_templates is None:
                    continue
                field_path = f"{path}.{field_name}"
                if not isinstance(raw_templates, list):
                    problems.append(_TemplateProblem("template_collection_invalid", source_path, field_path, hashes[source_path], type(raw_templates).__name__))
                    continue
                for index, raw in enumerate(raw_templates):
                    template_path = f"{field_path}[{index}]"
                    if not isinstance(raw, Mapping):
                        problems.append(_TemplateProblem("template_definition_invalid", source_path, template_path, hashes[source_path], "definition_not_object"))
                        continue
                    unknown_fields = set(raw) - {"Name", "TaskList", "DynamicStrings", "DynamicValues"}
                    if unknown_fields:
                        problems.append(_TemplateProblem("template_field_unclassified", source_path, template_path, hashes[source_path], ",".join(sorted(unknown_fields))))
                        continue
                    name = raw.get("Name")
                    tasks = raw.get("TaskList")
                    if not isinstance(name, str) or not name:
                        problems.append(_TemplateProblem("template_definition_invalid", source_path, f"{template_path}.Name", hashes[source_path], "name_invalid"))
                        continue
                    if not isinstance(tasks, list) or any(not isinstance(item, Mapping) for item in tasks):
                        problems.append(_TemplateProblem("template_definition_invalid", source_path, f"{template_path}.TaskList", hashes[source_path], "task_list_invalid"))
                        continue
                    parameters, parameter_error = _template_parameters(raw, template_path)
                    if parameter_error:
                        problems.append(_TemplateProblem("template_parameter_invalid", source_path, template_path, hashes[source_path], parameter_error))
                        continue
                    drafts.append(
                        _TemplateDraft(
                            template_id=_stable_id("control_flow_template", source_path, template_path, name),
                            name=name,
                            scope_kind=scope_kind,
                            namespace_path=path,
                            task_list_path=f"{template_path}.TaskList",
                            source_path=source_path,
                            parameters=parameters,
                            tasks=tuple(cast(Mapping[str, Any], item) for item in tasks),
                            content_sha256=hashes[source_path],
                        )
                    )
            for key, child in value.items():
                walk(source_path, child, f"{path}.{key}")
        elif isinstance(value, (tuple, list)):
            for index, child in enumerate(value):
                walk(source_path, child, f"{path}[{index}]")

    for source_path, document in snapshot.documents.items():
        walk(source_path, document, "$")
    return drafts, problems


def _discover_shared_templates(
    tbgd_root: Path,
) -> tuple[list[_TemplateDraft], list[_TemplateProblem], str, int]:
    directory = tbgd_root / _GLOBAL_TEMPLATE_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"shared control-flow template directory missing:{_GLOBAL_TEMPLATE_DIR}")
    drafts: list[_TemplateDraft] = []
    problems: list[_TemplateProblem] = []
    digest = sha256()
    read_count = 0
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".layout.json"):
            continue
        raw_bytes = path.read_bytes()
        read_count += 1
        relative = path.relative_to(tbgd_root).as_posix()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative.encode())
        digest.update(len(raw_bytes).to_bytes(8, "big"))
        digest.update(raw_bytes)
        content_sha256 = sha256(raw_bytes).hexdigest()
        document = json.loads(raw_bytes)
        if not isinstance(document, Mapping):
            problems.append(_TemplateProblem("template_document_invalid", relative, "$", content_sha256, "document_not_object"))
            continue
        templates = document.get("TaskListTemplate")
        if not isinstance(templates, list):
            problems.append(_TemplateProblem("template_collection_invalid", relative, "$.TaskListTemplate", content_sha256, type(templates).__name__))
            continue
        for index, raw in enumerate(templates):
            template_path = f"$.TaskListTemplate[{index}]"
            if not isinstance(raw, Mapping):
                problems.append(_TemplateProblem("template_definition_invalid", relative, template_path, content_sha256, "definition_not_object"))
                continue
            unknown_fields = set(raw) - {"Name", "TaskList", "DynamicStrings", "DynamicValues"}
            if unknown_fields:
                problems.append(_TemplateProblem("template_field_unclassified", relative, template_path, content_sha256, ",".join(sorted(unknown_fields))))
                continue
            name = raw.get("Name")
            tasks = raw.get("TaskList")
            if not isinstance(name, str) or not name:
                problems.append(_TemplateProblem("template_definition_invalid", relative, f"{template_path}.Name", content_sha256, "name_invalid"))
                continue
            if not isinstance(tasks, list) or any(not isinstance(item, Mapping) for item in tasks):
                problems.append(_TemplateProblem("template_definition_invalid", relative, f"{template_path}.TaskList", content_sha256, "task_list_invalid"))
                continue
            parameters, parameter_error = _template_parameters(raw, template_path)
            if parameter_error:
                problems.append(_TemplateProblem("template_parameter_invalid", relative, template_path, content_sha256, parameter_error))
                continue
            drafts.append(
                _TemplateDraft(
                    template_id=_stable_id("control_flow_template", relative, template_path, name),
                    name=name,
                    scope_kind="shared_global",
                    namespace_path="$",
                    task_list_path=f"{template_path}.TaskList",
                    source_path=relative,
                    parameters=parameters,
                    tasks=tuple(cast(Mapping[str, Any], item) for item in tasks),
                    content_sha256=content_sha256,
                )
            )
    return drafts, problems, digest.hexdigest(), read_count


def _effective_scope_for_semantic(semantic_kind: str) -> str:
    if semantic_kind in _NON_GAMEPLAY_SEMANTICS:
        return "non_gameplay"
    if semantic_kind == "combat_decode_required":
        return "decode_required"
    return "gameplay"


def _scope_control_occurrences(
    snapshot: CharacterAbilityRawSnapshot,
    scope_catalog: CharacterAbilityScopeProjectionCatalog,
    content_hashes: Mapping[str, str],
) -> tuple[_ControlFlowOccurrence, ...]:
    occurrences: list[_ControlFlowOccurrence] = []
    for record in scope_catalog.scope_records:
        if record.materialization_role != "selected" or record.occurrence_kind != "typed_node":
            continue
        source_path = record.source.source_path
        json_path = _object_path(record)
        try:
            raw = _at_path(snapshot.documents[source_path], json_path)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                f"control-flow scope occurrence source missing:{record.record_id}"
            ) from exc
        if not isinstance(raw, Mapping) or _short_type(raw.get("$type")) != record.family:
            raise ValueError(
                f"control-flow scope occurrence source mismatch:{record.record_id}"
            )
        materialization_role = classify_control_flow_materialization_role(
            record.family,
            raw,
            occurrence_semantic_kind=record.semantic_kind,
        )
        if not materialization_role:
            continue
        occurrences.append(
            _ControlFlowOccurrence(
                record.record_id,
                record.family,
                record.semantic_kind,
                record.effective_scope,
                source_path,
                json_path,
                content_hashes[source_path],
                raw,
                "character_scope",
                materialization_role,
            )
        )
    return tuple(sorted(occurrences, key=lambda item: item.occurrence_id))


def _shared_template_control_occurrences(
    drafts: tuple[_TemplateDraft, ...],
) -> tuple[_ControlFlowOccurrence, ...]:
    occurrences: dict[str, _ControlFlowOccurrence] = {}

    def walk(draft: _TemplateDraft, value: object, path: str) -> None:
        if isinstance(value, Mapping):
            family = _short_type(value.get("$type"))
            if family:
                materialization_role = classify_control_flow_materialization_role(
                    family,
                    value,
                )
                if materialization_role:
                    occurrence_id = character_ability_scope_record_id(
                        "typed_node",
                        draft.source_path,
                        f"{path}.$type",
                        family,
                    )
                    occurrence = _ControlFlowOccurrence(
                        occurrence_id,
                        family,
                        character_ability_semantic_kind(family)
                        or "combat_decode_required",
                        _effective_scope_for_semantic(
                            character_ability_semantic_kind(family)
                            or "combat_decode_required"
                        ),
                        draft.source_path,
                        path,
                        draft.content_sha256,
                        value,
                        "shared_template",
                        materialization_role,
                    )
                    prior = occurrences.setdefault(occurrence_id, occurrence)
                    if prior != occurrence:
                        raise ValueError(
                            f"shared template control-flow occurrence conflicts:{occurrence_id}"
                        )
            for field_name, child in value.items():
                walk(draft, child, f"{path}.{field_name}")
        elif isinstance(value, (tuple, list)):
            for index, child in enumerate(value):
                walk(draft, child, f"{path}[{index}]")

    for draft in drafts:
        if draft.scope_kind != "shared_global":
            continue
        for index, task in enumerate(draft.tasks):
            walk(draft, task, f"{draft.task_list_path}[{index}]")
    return tuple(sorted(occurrences.values(), key=lambda item: item.occurrence_id))


def _scope_child(
    record_lookup: Mapping[tuple[str, str], CharacterAbilityScopeRecordIR],
    *,
    source_path: str,
    raw: Mapping[str, Any],
    path: str,
    ordinal: int,
    content_sha256: str,
    external: bool = False,
) -> ControlFlowChildSourceIR | None:
    family = _short_type(raw.get("$type"))
    if not family:
        return None
    json_path = f"{path}.$type"
    record = record_lookup.get((source_path, json_path))
    if record is not None:
        return ControlFlowChildSourceIR(
            record.record_id,
            record.family,
            record.semantic_kind,
            record.effective_scope,
            ordinal,
            _source(
                source_path=source_path,
                raw_type=record.family,
                raw_id=record.record_id,
                json_path=json_path,
                content_sha256=content_sha256,
                extra={"scope_record_id": record.record_id},
            ),
        )
    if not external:
        return None
    semantic = character_ability_semantic_kind(family)
    semantic_kind = semantic or "combat_decode_required"
    effective_scope = _effective_scope_for_semantic(semantic_kind)
    record_id = character_ability_scope_record_id("typed_node", source_path, json_path, family)
    return ControlFlowChildSourceIR(
        record_id,
        family,
        semantic_kind,
        effective_scope,
        ordinal,
        _source(
            source_path=source_path,
            raw_type=family,
            raw_id=record_id,
            json_path=json_path,
            content_sha256=content_sha256,
            extra={"scope_record_id": record_id, "external_template_source": True},
        ),
    )


def _template_ir(
    draft: _TemplateDraft,
    record_lookup: Mapping[tuple[str, str], CharacterAbilityScopeRecordIR],
) -> ControlFlowTemplateDefinitionIR:
    parameters = tuple(
        ControlFlowTemplateParameterIR(
            parameter_id=_stable_id(
                "control_flow_template_parameter",
                draft.template_id,
                item.parameter_kind,
                item.key,
            ),
            template_id=draft.template_id,
            parameter_kind=cast(Any, item.parameter_kind),
            key=item.key,
            index=item.index,
            read_type=item.read_type,
            declared_value=item.declared_value,
            source=_source(
                source_path=draft.source_path,
                raw_type="ControlFlowTemplateParameter",
                raw_id=_stable_id(
                    "control_flow_template_parameter",
                    draft.template_id,
                    item.parameter_kind,
                    item.key,
                ),
                json_path=item.json_path,
                content_sha256=draft.content_sha256,
                extra={
                    "template_id": draft.template_id,
                    "parameter_kind": item.parameter_kind,
                    "parameter_key": item.key,
                },
            ),
        )
        for item in draft.parameters
    )
    children = tuple(
        child
        for index, raw in enumerate(draft.tasks)
        if (
            child := _scope_child(
                record_lookup,
                source_path=draft.source_path,
                raw=raw,
                path=f"{draft.task_list_path}[{index}]",
                ordinal=index,
                content_sha256=draft.content_sha256,
                external=draft.scope_kind == "shared_global",
            )
        )
        is not None
    )
    return ControlFlowTemplateDefinitionIR(
        draft.template_id,
        draft.name,
        cast(Any, draft.scope_kind),
        draft.namespace_path,
        parameters,
        children,
        _source(
            source_path=draft.source_path,
            raw_type="ControlFlowTaskTemplate",
            raw_id=draft.template_id,
            json_path=draft.task_list_path.removesuffix(".TaskList"),
            content_sha256=draft.content_sha256,
            extra={"template_name": draft.name, "scope_kind": draft.scope_kind},
        ),
    )


def _template_candidates(
    *,
    family: str,
    name: str,
    source_path: str,
    node_path: str,
    drafts: tuple[_TemplateDraft, ...],
) -> tuple[_TemplateDraft, ...]:
    same_source = tuple(item for item in drafts if item.source_path == source_path and item.name == name)
    if family == "IncludeGlobalTaskListTemplate":
        return tuple(
            item
            for item in drafts
            if item.name == name
            and (
                (item.source_path == source_path and item.scope_kind == "document_global")
                or item.scope_kind == "shared_global"
            )
        )
    local = tuple(
        item
        for item in same_source
        if item.scope_kind == "local" and (node_path == item.namespace_path or node_path.startswith(f"{item.namespace_path}."))
    )
    if local:
        longest = max(len(item.namespace_path) for item in local)
        return tuple(item for item in local if len(item.namespace_path) == longest)
    document = tuple(item for item in same_source if item.scope_kind == "document_global")
    if document:
        return document
    return tuple(item for item in drafts if item.scope_kind == "shared_global" and item.name == name)


def _template_references_for_node(
    node_id: str,
    family: str,
    raw: Mapping[str, Any],
    *,
    source_path: str,
    node_path: str,
    content_sha256: str,
    drafts: tuple[_TemplateDraft, ...],
) -> tuple[ControlFlowTemplateReferenceIR, ...]:
    requests: list[tuple[str, str, str]] = []
    if family in {"IncludeTaskListTemplate", "IncludeGlobalTaskListTemplate"}:
        name = raw.get("Name")
        requests.append((str(name) if isinstance(name, str) else "<missing>", f"{node_path}.Name", "document_or_shared_global" if family == "IncludeGlobalTaskListTemplate" else "local_document_or_shared_global"))
    elif family == "TriggerParallelTaskListTemplate":
        templates = raw.get("Templates")
        if isinstance(templates, list):
            for index, item in enumerate(templates):
                name = item.get("Name") if isinstance(item, Mapping) else None
                requests.append((str(name) if isinstance(name, str) else "<missing>", f"{node_path}.Templates[{index}].Name", "parallel_local"))
        else:
            requests.append(("<missing>", f"{node_path}.Templates", "parallel_local"))
    references: list[ControlFlowTemplateReferenceIR] = []
    for index, (name, field_path, kind) in enumerate(requests):
        candidates = () if name == "<missing>" else _template_candidates(
            family=family,
            name=name,
            source_path=source_path,
            node_path=node_path,
            drafts=drafts,
        )
        candidate_ids = tuple(sorted(item.template_id for item in candidates))
        reason = "" if len(candidate_ids) == 1 else (
            f"control_flow_template_missing:{name}" if not candidate_ids else f"control_flow_template_ambiguous:{name}"
        )
        reference_id = _stable_id("control_flow_template_ref", node_id, index, name, field_path)
        references.append(
            ControlFlowTemplateReferenceIR(
                reference_id,
                node_id,
                name,
                cast(Any, kind),
                candidate_ids,
                candidate_ids[0] if len(candidate_ids) == 1 else "",
                _source(
                    source_path=source_path,
                    raw_type=family,
                    raw_id=reference_id,
                    json_path=field_path,
                    content_sha256=content_sha256,
                    extra={"node_id": node_id, "template_name": name},
                ),
                "lowered" if not reason else "blocked",
                reason,
            )
        )
    return tuple(references)


def _cycle_reference_ids(
    references: tuple[ControlFlowTemplateReferenceIR, ...],
    drafts: tuple[_TemplateDraft, ...],
) -> frozenset[str]:
    draft_by_id = {item.template_id: item for item in drafts}
    owner_by_reference: dict[str, str] = {}
    for reference in references:
        owner_candidates = tuple(
            item
            for item in drafts
            if item.source_path == reference.source.source_path
            and str(reference.source.evidence["json_path"]).startswith(f"{item.task_list_path}[")
        )
        if owner_candidates:
            owner_by_reference[reference.reference_id] = max(owner_candidates, key=lambda item: len(item.task_list_path)).template_id
    edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for reference in references:
        owner = owner_by_reference.get(reference.reference_id)
        if owner and reference.coverage_status == "lowered" and reference.resolved_template_id in draft_by_id:
            edges[owner].append((reference.resolved_template_id, reference.reference_id))
    state: dict[str, int] = {}
    cycle_refs: set[str] = set()

    def walk(template_id: str, stack_nodes: list[str], stack_edges: list[str]) -> None:
        state[template_id] = 1
        stack_nodes.append(template_id)
        for target, reference_id in edges.get(template_id, ()):
            target_state = state.get(target, 0)
            if target_state == 0:
                stack_edges.append(reference_id)
                walk(target, stack_nodes, stack_edges)
                stack_edges.pop()
            elif target_state == 1:
                cycle_start = stack_nodes.index(target)
                cycle_refs.update(stack_edges[cycle_start:])
                cycle_refs.add(reference_id)
        stack_nodes.pop()
        state[template_id] = 2

    for template_id in draft_by_id:
        if state.get(template_id, 0) == 0:
            walk(template_id, [], [])
    return frozenset(cycle_refs)


def build_character_control_flow_contract_catalog(
    tbgd_root: Path,
    *,
    snapshot: CharacterAbilityRawSnapshot,
    scope_catalog: CharacterAbilityScopeProjectionCatalog,
) -> CharacterControlFlowContractCatalog:
    if type(snapshot) is not CharacterAbilityRawSnapshot or type(scope_catalog) is not CharacterAbilityScopeProjectionCatalog:
        raise TypeError("control-flow catalog requires exact S0 source types")
    if (
        not snapshot.source_catalog_complete
        or snapshot.snapshot_id != scope_catalog.snapshot_id
        or snapshot.source_fingerprint != scope_catalog.source_fingerprint
        or scope_catalog.fingerprint_kind != "complete"
        or scope_catalog.source_filter
        or scope_catalog.family_filter
    ):
        raise ValueError("control-flow catalog requires one complete matching source closure")

    selected_records = tuple(item for item in scope_catalog.scope_records if item.materialization_role == "selected")
    ancestor_context_count = sum(
        item.semantic_kind in {"combat_control_flow", "simulation_sequence"}
        and item.materialization_role == "ancestor_context"
        for item in scope_catalog.scope_records
    )
    content_hashes = {item.source.source_path: item.content_sha256 for item in snapshot.sources}
    record_lookup = {
        (item.source.source_path, str(item.source.evidence["json_path"])): item
        for item in selected_records
    }
    local_drafts, local_template_problems = _discover_local_templates(snapshot)
    shared_drafts, shared_template_problems, dependency_fingerprint, dependency_read_count = _discover_shared_templates(tbgd_root)
    drafts = tuple(sorted((*local_drafts, *shared_drafts), key=lambda item: item.template_id))
    scope_occurrences = _scope_control_occurrences(
        snapshot,
        scope_catalog,
        content_hashes,
    )
    shared_occurrences = _shared_template_control_occurrences(drafts)
    occurrence_groups: dict[str, list[_ControlFlowOccurrence]] = defaultdict(list)
    for occurrence in (*scope_occurrences, *shared_occurrences):
        occurrence_groups[occurrence.occurrence_id].append(occurrence)
    conflicts = {
        occurrence_id: values
        for occurrence_id, values in occurrence_groups.items()
        if len(values) != 1
    }
    if conflicts:
        raise ValueError(
            f"control-flow source occurrence materialized multiple times:{next(iter(sorted(conflicts)))}"
        )
    occurrences = tuple(
        sorted(
            (values[0] for values in occurrence_groups.values()),
            key=lambda item: item.occurrence_id,
        )
    )
    templates = tuple(_template_ir(item, record_lookup) for item in drafts)
    issues: list[ControlFlowContractIssueIR] = []
    for problem in (*local_template_problems, *shared_template_problems):
        subject = _stable_id("control_flow_template_problem", problem.source_path, problem.json_path, problem.code)
        issues.append(
            ControlFlowContractIssueIR(
                problem.code,
                subject,
                "p9_s8a",
                problem.detail,
                _source(
                    source_path=problem.source_path,
                    raw_type="ControlFlowTaskTemplate",
                    raw_id=subject,
                    json_path=problem.json_path,
                    content_sha256=problem.content_sha256,
                ),
            )
        )
    definition_groups: dict[tuple[str, ...], list[_TemplateDraft]] = defaultdict(list)
    for draft in drafts:
        key = (
            (draft.scope_kind, draft.name)
            if draft.scope_kind == "shared_global"
            else (draft.scope_kind, draft.source_path, draft.namespace_path, draft.name)
        )
        definition_groups[key].append(draft)
    for key, candidates in definition_groups.items():
        if len(candidates) < 2:
            continue
        for draft in candidates:
            issues.append(
                ControlFlowContractIssueIR(
                    "template_definition_ambiguous",
                    draft.template_id,
                    "p9_s8a",
                    ":".join(key),
                    next(item.source for item in templates if item.template_id == draft.template_id),
                )
            )
    nodes: list[CharacterControlFlowNodeIR] = []
    references: list[ControlFlowTemplateReferenceIR] = []

    for occurrence in occurrences:
        node_id = _stable_id("character_control_flow_node", occurrence.occurrence_id)
        node_path = occurrence.json_path
        source_path = occurrence.source_path
        content_sha256 = occurrence.content_sha256
        node_source = _source(
            source_path=source_path,
            raw_type=occurrence.family,
            raw_id=node_id,
            json_path=node_path,
            content_sha256=content_sha256,
            extra={
                "scope_record_id": occurrence.occurrence_id,
                "source_kind": occurrence.source_kind,
                "materialization_role": occurrence.materialization_role,
            },
        )
        blockers: list[str] = []
        raw = occurrence.raw
        responsibilities, field_blockers = classify_control_flow_peer_fields(
            occurrence.family,
            raw,
            node_id=node_id,
            source_path=source_path,
            json_path=node_path,
            content_sha256=content_sha256,
        )
        blockers.extend(field_blockers)
        for reason in field_blockers:
            issues.append(ControlFlowContractIssueIR("field_unclassified", node_id, "p9_s8a", reason, node_source))
        branches: list[ControlFlowBranchIR] = []
        branch_specs, branch_blockers = _branch_specs(occurrence.family, raw, node_path)
        blockers.extend(branch_blockers)
        for reason in branch_blockers:
            issues.append(ControlFlowContractIssueIR("branch_source_invalid", node_id, "p9_s8a", reason, node_source))
        for branch_index, (branch_kind, label, branch_path, child_specs) in enumerate(branch_specs):
            children: list[ControlFlowChildSourceIR] = []
            for child_index, (child_raw, child_path) in enumerate(child_specs):
                child = _scope_child(
                    record_lookup,
                    source_path=source_path,
                    raw=child_raw,
                    path=child_path,
                    ordinal=child_index,
                    content_sha256=content_sha256,
                    external=occurrence.source_kind == "shared_template",
                )
                if child is None:
                    reason = f"control_flow_child_source_missing:{child_path}"
                    blockers.append(reason)
                    issues.append(ControlFlowContractIssueIR("child_source_missing", node_id, "p9_s8a", reason, node_source))
                else:
                    children.append(child)
            branch_id = _stable_id("control_flow_branch", node_id, branch_index, branch_kind, label)
            branches.append(
                ControlFlowBranchIR(
                    branch_id,
                    node_id,
                    branch_kind,
                    branch_index,
                    label,
                    tuple(children),
                    _source(
                        source_path=source_path,
                        raw_type=occurrence.family,
                        raw_id=branch_id,
                        json_path=branch_path,
                        content_sha256=content_sha256,
                        extra={"node_id": node_id, "branch_kind": branch_kind},
                    ),
                )
            )
        node_references = _template_references_for_node(
            node_id,
            occurrence.family,
            raw,
            source_path=source_path,
            node_path=node_path,
            content_sha256=content_sha256,
            drafts=drafts,
        )
        references.extend(node_references)
        termination = _termination(node_id, occurrence.family, raw, node_source)
        if termination.status == "blocked":
            blockers.append(termination.blocked_reason)
            issues.append(ControlFlowContractIssueIR("termination_source_invalid", node_id, "p9_s8a", termination.blocked_reason, node_source))
        role = _ROLE_BY_FAMILY.get(occurrence.family, "unclassified")
        if (
            role == "presentation_child_wrapper"
            and occurrence.materialization_role != "presentation_child_wrapper"
        ):
            role = "effect_continuation"
        if role == "unclassified":
            blockers.append(f"control_flow_role_unclassified:{occurrence.family}")
        stages = {
            item.owner_stage
            for item in responsibilities
            if item.owner_stage not in _COMPLETED_OWNERS
        }
        role_owner = _ROLE_OWNER.get(role)
        if role_owner and role_owner not in _COMPLETED_OWNERS:
            stages.add(role_owner)
        if termination.status == "runtime_proof_required":
            stages.add(termination.owner_stage)
        blocked_reference = next((item for item in node_references if item.coverage_status == "blocked"), None)
        if blocked_reference is not None:
            blockers.append(blocked_reference.blocked_reason)
            issues.append(ControlFlowContractIssueIR("template_reference_blocked", node_id, "p9_s8a", blocked_reference.blocked_reason, blocked_reference.source))
        nodes.append(
            CharacterControlFlowNodeIR(
                node_id,
                occurrence.occurrence_id,
                occurrence.family,
                role,
                tuple(sorted(key for key in raw if key != "$type")),
                responsibilities,
                tuple(branches),
                tuple(sorted(item.reference_id for item in node_references)),
                termination,
                tuple(sorted(stages)),
                node_source,
                "blocked" if blockers else "lowered_with_obligation" if stages else "lowered",
                blockers[0] if blockers else "",
            )
        )

    cycle_ids = _cycle_reference_ids(tuple(references), drafts)
    if cycle_ids:
        updated_references: list[ControlFlowTemplateReferenceIR] = []
        affected_nodes: set[str] = set()
        for reference in references:
            if reference.reference_id in cycle_ids:
                affected_nodes.add(reference.node_id)
                updated_references.append(replace(reference, resolved_template_id="", coverage_status="blocked", blocked_reason="control_flow_template_cycle"))
                issues.append(ControlFlowContractIssueIR("template_cycle", reference.reference_id, "p9_s8a", "control_flow_template_cycle", reference.source))
            else:
                updated_references.append(reference)
        references = updated_references
        nodes = [
            replace(node, coverage_status="blocked", blocked_reason="control_flow_template_cycle")
            if node.node_id in affected_nodes
            else node
            for node in nodes
        ]

    fetch_names_by_template: dict[str, set[str]] = {
        item.template_id: set() for item in templates
    }
    for node in nodes:
        node_path = str(node.source.evidence["json_path"])
        owner_candidates = tuple(
            item
            for item in templates
            if item.source.source_path == node.source.source_path
            and node_path.startswith(f'{item.source.evidence["json_path"]}.TaskList[')
        )
        if not owner_candidates:
            continue
        owner = max(
            owner_candidates,
            key=lambda item: len(str(item.source.evidence["json_path"])),
        )
        fetch_names_by_template[owner.template_id].update(
            branch.label
            for branch in node.branches
            if branch.branch_kind == "template_parameter_fetch"
        )
    node_by_id = {item.node_id: item for item in nodes}
    closed_references: list[ControlFlowTemplateReferenceIR] = []
    parameter_blocked_nodes: dict[str, str] = {}
    for reference in references:
        if reference.coverage_status != "lowered":
            closed_references.append(reference)
            continue
        caller = node_by_id[reference.node_id]
        provided = {
            branch.label
            for branch in caller.branches
            if branch.branch_kind == "template_parameter_sequence"
        }
        required = fetch_names_by_template[reference.resolved_template_id]
        if provided == required:
            closed_references.append(reference)
            continue
        missing = sorted(required - provided)
        extra = sorted(provided - required)
        reason = (
            "control_flow_template_parameter_subgraph_missing"
            if missing
            else "control_flow_template_parameter_subgraph_unconsumed"
        )
        detail = json.dumps(
            {"missing": missing, "unconsumed": extra},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        closed_references.append(
            replace(
                reference,
                resolved_template_id="",
                coverage_status="blocked",
                blocked_reason=reason,
            )
        )
        parameter_blocked_nodes[reference.node_id] = reason
        issues.append(
            ControlFlowContractIssueIR(
                "template_parameter_subgraph_not_closed",
                reference.reference_id,
                "p9_s8a",
                detail,
                reference.source,
            )
        )
    references = closed_references
    nodes = [
        replace(node, coverage_status="blocked", blocked_reason=reason)
        if (reason := parameter_blocked_nodes.get(node.node_id)) is not None
        and node.coverage_status != "blocked"
        else node
        for node in nodes
    ]

    family_counts = Counter(item.family for item in nodes)
    return CharacterControlFlowContractCatalog(
        snapshot_id=snapshot.snapshot_id,
        scope_catalog_id=scope_catalog.catalog_id,
        source_fingerprint=snapshot.source_fingerprint,
        dependency_fingerprint=dependency_fingerprint,
        nodes=tuple(nodes),
        template_definitions=templates,
        template_references=tuple(references),
        issues=tuple(issues),
        denominator_record_ids=tuple(
            sorted(item.occurrence_id for item in occurrences)
        ),
        direct_record_count=len(occurrences),
        ancestor_context_count=ancestor_context_count,
        family_counts=dict(sorted(family_counts.items())),
        build_counters={
            **dict(snapshot.build_counters),
            "scope_projection_build_count": 1,
            "control_flow_contract_build_count": 1,
            "shared_template_source_read_count": dependency_read_count,
            "scope_control_occurrence_count": len(scope_occurrences),
            "shared_template_control_occurrence_count": len(shared_occurrences),
            "hybrid_control_occurrence_count": sum(
                item.materialization_role
                in {"hybrid_child_wrapper", "presentation_child_wrapper"}
                for item in occurrences
            ),
            "template_parameter_sequence_branch_count": sum(
                branch.branch_kind == "template_parameter_sequence"
                for node in nodes
                for branch in node.branches
            ),
            "template_parameter_fetch_count": sum(
                branch.branch_kind == "template_parameter_fetch"
                for node in nodes
                for branch in node.branches
            ),
            "full_canonical_ir_build_count": 0,
        },
    )
