from __future__ import annotations

from typing import Any, Literal


EquipmentFamilyStage = Literal["s7", "s8", "non_gameplay", "unknown"]

S7_VALUE_FAMILIES = frozenset(
    {
        "fixed_numeric",
        "equipment_rank_parameter_read",
        "postfix_numeric",
    }
)
S8_VALUE_FAMILIES = frozenset({"postfix_numeric_opcode16"})

S7_STACK_PROPERTY_TYPES = frozenset(
    {
        "AttackAddedRatio",
        "AttackDelta",
        "DefenceAddedRatio",
        "DefenseAddedRatio",
        "DefenceDelta",
        "DefenseDelta",
        "SpeedAddedRatio",
        "SpeedDelta",
        "CriticalChanceBase",
        "CriticalDamageBase",
        "StatusProbabilityBase",
        "StatusResistanceBase",
    }
)


# The partition is semantic, not keyed by a light-cone, character, or ability ID.
# Validation compares these sets with the live published catalog so a new raw
# family cannot silently inherit an old classification.
S7_TASK_FAMILIES = frozenset(
    {
        "AddModifier",
        "DefineDynamicValue",
        "DispelStatus",
        "PredicateTaskList",
        "RemoveModifier",
        "RemoveSelfModifier",
        "SetDynamicValue",
        "SetDynamicValueByCharacterCount",
        "SetDynamicValueByCopying",
        "SetDynamicValueByCountOfBaseType",
        "SetDynamicValueByHPRatio",
        "SetDynamicValueByModifierValue",
        "SetDynamicValueByProperty",
        "SetDynamicValueByStatusCount",
        "SetDynamicValueByWeaknessCount",
        "SetModifierDynamicValue",
        "StackProperty",
    }
)

S8_TASK_FAMILIES = frozenset(
    {
        "DamageByAttackProperty",
        "HealHP",
        "IncludeTaskListTemplate",
        "InitShield",
        "JDOLDFECMPL",
        "LoopExecuteTaskList",
        "LoseHPByRatio",
        "ModifyActionDelay",
        "ModifyCurrentSkillDelayCost",
        "ModifyDamageData",
        "ModifyHealData",
        "ModifySPNew",
        "ModifyTeamBoostPoint",
        "ModifyTeamBoostPointMax",
        "RandomConfig",
        "Remodifier",
        "RemoveShield",
        "Retarget",
        "SetDynamicValueByAttackTargetCount",
        "SetDynamicValueByBPChange",
        "SetDynamicValueByDamageDataProperty",
        "SetDynamicValueByHealDataProperty",
        "SetDynamicValueByMaxBP",
        "SetDynamicValueByVariateType",
        "SetResilience",
        "TriggerEffect",
    }
)

NON_GAMEPLAY_TASK_FAMILIES = frozenset(
    {
        "AddBuffPerform",
        "ModifierAttachEffect",
        "SetDynamicValueByPropertyClientOnly",
        "StackStatusDesc",
        "ToggleSkillPreShow",
        "WaitSecond",
    }
)

S7_CONDITION_FAMILIES = frozenset(
    {
        "ByAnd",
        "ByAny",
        "ByAttackType",
        "ByCheckModifierCallBackBehaviorFlag",
        "ByCheckModifierCallBackIsSelf",
        "ByCheckModifierCallBackName",
        "ByCheckModifierCallBackStatusType",
        "ByCompareAbilityProperty",
        "ByCompareCharacterID",
        "ByCompareCharacterNumber",
        "ByCompareCurrentModifierStatusType",
        "ByCompareDynamicValue",
        "ByCompareHPRatio",
        "ByCompareModifierValue",
        "ByCompareTarget",
        "ByCompareTargetCount",
        "ByContainBehaviorFlag",
        "ByCurrentSkillName",
        "ByCurrentSkillType",
        "ByIsContainModifier",
        "ByIsTeammate",
        "ByIsTurnOwnerEntity",
        "ByNot",
        "ByStatusCount",
        "ByTargetAliveState",
        "ByTargetEntityType",
        "ByTargetListIntersects",
        "ByTargetTeam",
    }
)

S8_CONDITION_FAMILIES = frozenset(
    {
        "ByCharacterDamageType",
        "ByCompareChangeValue",
        "ByCompareParamValue",
        "ByCompareSPRatio",
        "ByCompareWaveCount",
        "ByContainsParamFlag",
        "ByHasStanceWeak",
        "ByInTurnBasedGameModeState",
        "ByIsDamageCritical",
        "ByIsPropertyValueMinOrMax",
        "ByIsTargetValid",
        "ByIsTopActionDelayTarget",
        "ByRandomChance",
    }
)

S7_EVENT_FAMILIES = frozenset(
    {
        "OnAddModifierSuc",
        "OnAfterAttack",
        "OnAfterBeingAttacked",
        "OnAfterBeingHitAll",
        "OnAfterHit",
        "OnAfterHitAll",
        "OnAfterSkillUse",
        "OnBeforeAttack",
        "OnBeforeBeingAttacked",
        "OnBeforeBeingBreak",
        "OnBeforeBeingHitAll",
        "OnBeforeDying",
        "OnBeforeHit",
        "OnBeforeHitAll",
        "OnBeforeSkillUse",
        "OnCreate",
        "OnDeathrattle",
        "OnDestroy",
        "OnEnterBattle",
        "OnHPChange",
        "OnListenAfterAttack",
        "OnListenBeforeAttack",
        "OnListenBeforeSkillUse",
        "OnListenBreak",
        "OnListenCharacterDie",
        "OnListenHPChange",
        "OnListenModifierAdd",
        "OnListenModifierOnStack",
        "OnListenModifierRemove",
        "OnListenTurnEnd",
        "OnListenTurnPhase1Begin",
        "OnModifierAdd",
        "OnModifierRemove",
        "OnPhase1",
        "OnStack",
        "OnTriggerBreak",
        "OnTriggerDeath",
    }
)

S8_EVENT_FAMILIES = frozenset(
    {
        "OnAfterDealHeal",
        "OnBeforeDealHeal",
        "OnDefenderPrepareAttackData",
        "OnCustomEvent",
        "OnListenAvatarBaseTypeChange",
        "OnListenBpChange",
        "OnListenElationTimeEnd",
        "OnListenElationTimeStart",
        "OnListenCharacterCreate",
        "OnListenCharacterEscape",
        "OnPhase2",
        "OnSPChange",
        "OnSnapshotCreate",
        "OnStackWeakness",
        "OnUltraSkillPrepare",
    }
)

NON_GAMEPLAY_EVENT_FAMILIES = frozenset({"OnAimAtTargetsRefresh_CL"})

S7_TARGET_FAMILIES = frozenset({"TargetAlias", "TargetFetchActualOwner"})
S8_TARGET_FAMILIES = frozenset({"TargetConcat", "TargetFilter", "TargetSequence"})


def classify_equipment_family(kind: str, raw_family: str) -> EquipmentFamilyStage:
    groups = {
        "task": (S7_TASK_FAMILIES, S8_TASK_FAMILIES, NON_GAMEPLAY_TASK_FAMILIES),
        "condition": (
            S7_CONDITION_FAMILIES,
            S8_CONDITION_FAMILIES,
            frozenset(),
        ),
        "event": (S7_EVENT_FAMILIES, S8_EVENT_FAMILIES, NON_GAMEPLAY_EVENT_FAMILIES),
        "target": (S7_TARGET_FAMILIES, S8_TARGET_FAMILIES, frozenset()),
    }
    selected = groups.get(kind)
    if selected is None:
        return "unknown"
    if raw_family in selected[0]:
        return "s7"
    if raw_family in selected[1]:
        return "s8"
    if raw_family in selected[2]:
        return "non_gameplay"
    return "unknown"


def classify_equipment_task(
    raw_family: str,
    raw_task: dict[str, Any],
) -> EquipmentFamilyStage:
    """Classify semantic branches that share a raw task type."""

    semantic_stage: EquipmentFamilyStage | None = None
    if raw_family == "StackProperty":
        property_type = raw_task.get("Property")
        if not isinstance(property_type, str) or not property_type:
            return "unknown"
        semantic_stage = (
            "s7" if property_type in S7_STACK_PROPERTY_TYPES else "s8"
        )
    if raw_family == "SetDynamicValueByCountOfBaseType":
        base_types = raw_task.get("BaseTypeList")
        if isinstance(base_types, list) and base_types:
            return "s8"
    if raw_family == "SetDynamicValueByProperty":
        if raw_task.get("Value") == "MaxSP":
            return "s8"
    if raw_family == "SetDynamicValue" and _contains_postfix_opcode(
        raw_task.get("Value"),
        16,
    ):
        return "s8"
    predicate = raw_task.get("Predicate")
    if isinstance(predicate, dict):
        predicate_stage = classify_equipment_condition(
            _short_type(predicate.get("$type")),
            predicate,
        )
        if predicate_stage in {"s8", "unknown"}:
            return predicate_stage
    for child_list_key in (
        "TaskList",
        "SuccessTaskList",
        "FailedTaskList",
    ):
        children = raw_task.get(child_list_key)
        if children is None:
            continue
        if not isinstance(children, list):
            return "unknown"
        for child in children:
            if not isinstance(child, dict):
                return "unknown"
            child_stage = classify_equipment_task(
                _short_type(child.get("$type")),
                child,
            )
            if child_stage == "unknown":
                return "unknown"
            if child_stage == "s8":
                return "s8"
    for key, value in raw_task.items():
        target_stage = _embedded_target_stage(key, value)
        if target_stage in {"s8", "unknown"}:
            return target_stage
    return semantic_stage or classify_equipment_family("task", raw_family)


def classify_equipment_condition(
    raw_family: str,
    raw_condition: dict[str, Any],
) -> EquipmentFamilyStage:
    """Classify a condition branch, including nested predicates and targets."""

    stage = classify_equipment_family("condition", raw_family)
    if stage != "s7":
        return stage
    if raw_family == "ByTargetAliveState":
        if raw_condition.get("AliveStateMask") == "Mask_AliveOrRevivable":
            return "s8"
        return "unknown"
    child_values: list[Any] = []
    if raw_family in {"ByAnd", "ByAny"}:
        child_values.extend(raw_condition.get("PredicateList") or ())
    elif raw_family == "ByNot":
        child_values.append(raw_condition.get("Predicate"))
    for child in child_values:
        if not isinstance(child, dict):
            return "unknown"
        child_family = _short_type(child.get("$type"))
        child_stage = classify_equipment_condition(child_family, child)
        if child_stage == "unknown":
            return "unknown"
        if child_stage == "s8":
            return "s8"
    for key, value in raw_condition.items():
        target_stage = _embedded_target_stage(key, value)
        if target_stage in {"s8", "unknown"}:
            return target_stage
    return "s7"


def classify_equipment_callback(
    raw_event: str,
    raw_tasks: Any,
) -> EquipmentFamilyStage:
    """Classify the executable callback branch, not only its event label."""

    event_stage = classify_equipment_family("event", raw_event)
    if event_stage != "s7":
        return event_stage
    if not isinstance(raw_tasks, list):
        return "unknown"
    if not raw_tasks:
        return "non_gameplay"
    task_stages: list[EquipmentFamilyStage] = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            return "unknown"
        task_stages.append(
            classify_equipment_task(_short_type(task.get("$type")), task)
        )
    if "unknown" in task_stages:
        return "unknown"
    if "s8" in task_stages:
        return "s8"
    if all(stage == "non_gameplay" for stage in task_stages):
        return "non_gameplay"
    return "s7"


S7_SIMPLE_TARGET_ALIASES = frozenset(
    {
        "AllDarkTeam",
        "AllEnemy",
        "AllEnemyWithUnSelectable",
        "AllLightTeam",
        "AllTeamMember",
        "AllTeammate",
        "AllUnselectable",
        "AttackTargetList",
        "Caster",
        "CurrentActionTarget",
        "CurrentTurnOwnerEntity",
        "DamageAttackerEntity",
        "DamageDefenderEntity",
        "ModifierOwnerEntity",
        "ParamEntity",
        "ParamEntity2",
        "ParamEntityAttackTargetList",
        "ParamEntitySkillTargetEntityList",
        "SkillSubTargetEntityList",
        "SkillTargetEntityList",
    }
)


def classify_equipment_target(raw_target: Any) -> EquipmentFamilyStage:
    return _target_stage_from_value(raw_target)


def equipment_value_family(raw_value: Any) -> str:
    if not isinstance(raw_value, dict):
        return "unknown"
    if raw_value.get("Type") == "SkillEquip":
        return "equipment_rank_parameter_read"
    if raw_value.get("IsDynamic") is False and "FixedValue" in raw_value:
        return "fixed_numeric"
    if raw_value.get("IsDynamic") is True and isinstance(
        raw_value.get("PostfixExpr"), dict
    ):
        return (
            "postfix_numeric_opcode16"
            if _contains_postfix_opcode(raw_value, 16)
            else "postfix_numeric"
        )
    return "unknown"


def classify_equipment_value(raw_value: Any) -> EquipmentFamilyStage:
    family = equipment_value_family(raw_value)
    if family in S7_VALUE_FAMILIES:
        return "s7"
    if family in S8_VALUE_FAMILIES:
        return "s8"
    return "unknown"


def _embedded_target_stage(
    key: str,
    value: Any,
) -> EquipmentFamilyStage | None:
    if isinstance(value, dict):
        raw_family = _short_type(value.get("$type"))
        if raw_family.startswith("Target"):
            return _target_stage_from_value(value)
    if key.endswith("TargetType") and value is not None:
        return "unknown"
    return None


def _target_stage_from_value(value: Any) -> EquipmentFamilyStage:
    if value is None:
        return "s7"
    if not isinstance(value, dict):
        return "unknown"
    raw_family = _short_type(value.get("$type"))
    if raw_family == "TargetAlias":
        alias = value.get("Alias")
        if not isinstance(alias, str) or not alias:
            return "unknown"
        return "s7" if alias in S7_SIMPLE_TARGET_ALIASES else "s8"
    return classify_equipment_family("target", raw_family)


def _contains_postfix_opcode(value: Any, wanted: int) -> bool:
    import base64

    if not isinstance(value, dict):
        return False
    postfix = value.get("PostfixExpr")
    if not isinstance(postfix, dict):
        return False
    opcodes = postfix.get("OpCodes")
    if isinstance(opcodes, list):
        return wanted in opcodes
    if not isinstance(opcodes, str) or not opcodes:
        return False
    try:
        decoded = base64.b64decode(
            opcodes + "=" * ((4 - len(opcodes) % 4) % 4),
            validate=True,
        )
    except (TypeError, ValueError):
        return False
    return wanted in decoded


def _short_type(value: Any) -> str:
    return str(value or "").rsplit(".", 1)[-1]


def non_gameplay_evidence(kind: str, raw_family: str) -> str:
    evidence = {
        ("task", "AddBuffPerform"): "presentation-only buff performance task",
        ("task", "ModifierAttachEffect"): "presentation-only modifier attachment effect",
        ("task", "SetDynamicValueByPropertyClientOnly"): "raw type explicitly declares client-only property read",
        ("task", "StackStatusDesc"): "status description stacking only",
        ("task", "ToggleSkillPreShow"): "skill pre-show UI state only",
        ("task", "WaitSecond"): "presentation timing wait without battle-state semantics",
        ("event", "OnAimAtTargetsRefresh_CL"): "raw event explicitly declares client-only target preview refresh",
    }
    return evidence.get((kind, raw_family), "")
