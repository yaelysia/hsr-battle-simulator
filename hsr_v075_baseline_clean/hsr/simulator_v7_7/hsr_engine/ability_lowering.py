from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from .tbgd_loader import unwrap_value

VISUAL_OR_TIMELINE_TYPES = {
    "RPG.GameCore.LookAt", "RPG.GameCore.WaitAnimState", "RPG.GameCore.WaitSecond",
    "RPG.GameCore.TriggerAnimState", "RPG.GameCore.TriggerAnimStateWithMove",
    "RPG.GameCore.SetEntityVisible", "RPG.GameCore.GlobalMainIntensityEffect",
    "RPG.GameCore.RadialBlurEffect", "RPG.GameCore.VCameraConfigChange",
    "RPG.GameCore.ShowUIPage", "RPG.GameCore.ShowBattleUI", "RPG.GameCore.HideLevelStage",
    "RPG.GameCore.MoveToTargetPosition", "RPG.GameCore.SkillPerformFinish",
    "RPG.GameCore.DamagePerformFinish", "RPG.GameCore.DebugLog",
    "RPG.GameCore.FireProjectile", "RPG.GameCore.ChangeCameraState",
    "RPG.GameCore.PlayTimeline", "RPG.GameCore.PlayEffect",
    "RPG.GameCore.SyncCharLightAndCameraDir", "RPG.GameCore.WaitTimelineFinish",
    "RPG.GameCore.SetAttachmentScale", "RPG.GameCore.ScaleCharacterModel",
    "RPG.GameCore.MoveTeam", "RPG.GameCore.StopAim", "RPG.GameCore.TargetTimeSlow",
    "RPG.GameCore.ClearTargetTimeSlow", "RPG.GameCore.ShowActionBarEffect",
    "RPG.GameCore.ShowAttackTime", "RPG.GameCore.TryStartConnectUltraSkillFrameCapture",
    "RPG.GameCore.TriggerEnergyBarEffect", "RPG.GameCore.SetTeamFormation",
    "RPG.GameCore.SetSkillTargetFormationByPos", "RPG.GameCore.PreloadBattleEventByID",
    "RPG.GameCore.TriggerSkipDeadHandler",
    # Camera/pose/UI helpers seen across many avatar ability graphs. They do
    # not carry numeric combat fields; keep them as evidence-only visual nodes.
    "RPG.GameCore.AlignTargetToTeamCenter", "RPG.GameCore.ShowBonusUIEffect",
}

TARGETING_TYPES = {
    "RPG.GameCore.TargetAlias", "RPG.GameCore.Retarget", "RPG.GameCore.TargetFilter",
    "RPG.GameCore.TargetSequence", "RPG.GameCore.TargetFetchPartner",
}

CONDITION_TYPES = {
    "RPG.GameCore.PredicateTaskList", "RPG.GameCore.ByCompareDynamicValue",
    "RPG.GameCore.ByIsContainModifier", "RPG.GameCore.ByAnd", "RPG.GameCore.ByAny",
    "RPG.GameCore.ByTargetTeam", "RPG.GameCore.ByContainBehaviorFlag",
    "RPG.GameCore.ByCompareMonsterID", "RPG.GameCore.ByCheckModifierCallBackName",
    "RPG.GameCore.ByCurrentSkillType", "RPG.GameCore.ByRankActivated",
    "RPG.GameCore.ByCompareBattleEventID", "RPG.GameCore.ByCompareTarget",
    "RPG.GameCore.ByCompareMonsterPhase", "RPG.GameCore.ByCheckCustomValueBool",
    "RPG.GameCore.ByAttackType", "RPG.GameCore.ByCompareCharacterID",
    "RPG.GameCore.ByCompareMonsterRank", "RPG.GameCore.ByCompareHPRatio",
    "RPG.GameCore.ByCharacterDamageType", "RPG.GameCore.ByCompareModifierValue",
    "RPG.GameCore.ByCompareWaveCount", "RPG.GameCore.BySkillPointActivated",
    "RPG.GameCore.ByIsInsertAction", "RPG.GameCore.ByIsCurrentSkillActive",
    "RPG.GameCore.ByTargetListIntersects", "RPG.GameCore.ByTargetEntityType",
    "RPG.GameCore.ByHasStanceWeak", "RPG.GameCore.ByCompareCharacterNumber",
    "RPG.GameCore.ByIsTeamLocationIndexType", "RPG.GameCore.ByCurrentSkillName",
    "RPG.GameCore.ByTargetAliveState", "RPG.GameCore.ByNot",
    "RPG.GameCore.ByHaveEnemyAlive", "RPG.GameCore.ByCompareParamValue",
    "RPG.GameCore.ByCompareParamString", "RPG.GameCore.ByIsTargetValid",
    "RPG.GameCore.ByIsTurnOwnerEntity", "RPG.GameCore.ByIsTurnActionEntity",
}

ACTION_CHAIN_TYPES = {
    "RPG.GameCore.TriggerAbility", "RPG.GameCore.TurnInsertAbility",
    "RPG.GameCore.TurnInsertAction", "RPG.GameCore.TurnInsertAbilityCondition",
    "RPG.GameCore.OwnerEntityAddAbility", "RPG.GameCore.TriggerEffect",
    "RPG.GameCore.IncludeTaskListTemplate", "RPG.GameCore.ModifierAttachEffect",
    "RPG.GameCore.RemoveEffect", "RPG.GameCore.CreateBattleEvent",
}

EFFECT_TYPES = {
    "RPG.GameCore.AddModifier", "RPG.GameCore.RemoveModifier", "RPG.GameCore.RemoveSelfModifier",
    "RPG.GameCore.SetDynamicValue", "RPG.GameCore.SetDynamicValueByProperty",
    "RPG.GameCore.SetDynamicValueByAddValue", "RPG.GameCore.SetDynamicValueByCopying",
    "RPG.GameCore.SetDynamicValueByModifierValue", "RPG.GameCore.SetModifierDynamicValue",
    "RPG.GameCore.SetDynamicValueByCurrentBP", "RPG.GameCore.SetDynamicValueByMaxBP",
    "RPG.GameCore.SetDynamicValueByVariateType", "RPG.GameCore.SetDynamicValueByAttackTargetCount",
    "RPG.GameCore.SetDynamicValueByShield",
    "RPG.GameCore.DefineDynamicValue", "RPG.GameCore.StackProperty",
    "RPG.GameCore.AttackData", "RPG.GameCore.DamageByAttackProperty",
    "RPG.GameCore.ModifyDamageData", "RPG.GameCore.ModifySPNew",
    "RPG.GameCore.SetActionDelay", "RPG.GameCore.ModifyActionDelay",
    "RPG.GameCore.SetEnergyBarState", "RPG.GameCore.CharacterChangePhase",
    "RPG.GameCore.SetModifierDynamicValue", "RPG.GameCore.ModifyTeamBoostPoint",
    "RPG.GameCore.ModifyTeamBoostPointMax", "RPG.GameCore.ModifyCurrentSkillDelayCost",
    "RPG.GameCore.ModifySkillPropertyByName", "RPG.GameCore.ForceKill",
    "RPG.GameCore.SummonMonster", "RPG.GameCore.SummonUnit",
    "RPG.GameCore.DispelStatus", "RPG.GameCore.ModifyVersusBarProperty",
    "RPG.GameCore.HealHP", "RPG.GameCore.AddHealData", "RPG.GameCore.ModifyHP",
}

# Stable mapping from game target aliases to Content IR target policies.  Unknown
# aliases stay symbolic so the compiler can surface them as backlog rather than
# silently choosing the wrong target.
TARGET_ALIAS_MAP = {
    "Caster": "self",
    "Owner": "self",
    "AbilityTargetEntity": "selected_target",
    "AbilityTargetEntityList": "selected_targets",
    "SkillTargetEntityList": "selected_targets",
    "AbilityTargetAndAdjoinEntity": "selected_target_and_adjacent",
    "AbilityTargetAdjoinEntity": "selected_target_adjacent",
    "AllEnemy": "all_enemies",
    "AllEnemyEntity": "all_enemies",
    "AllTeam": "all_allies",
    "AllAliveTeam": "all_allies",
    "Team": "all_allies",
    "TeamFormation": "team_formation",
    "ModifierOwnerEntity": "modifier_owner",
    "ModifierSourceEntity": "modifier_source",
}

LOWERABLE_TYPES = {
    "RPG.GameCore.AddModifier", "RPG.GameCore.RemoveModifier", "RPG.GameCore.RemoveSelfModifier",
    "RPG.GameCore.SetDynamicValue", "RPG.GameCore.ModifySPNew", "RPG.GameCore.DamageByAttackProperty",
    "RPG.GameCore.AttackData", "RPG.GameCore.HealHP", "RPG.GameCore.SetActionDelay",
    "RPG.GameCore.ModifyActionDelay", "RPG.GameCore.TurnInsertAbility", "RPG.GameCore.SummonMonster",
    "RPG.GameCore.DispelStatus", "RPG.GameCore.ModifyDamageData", "RPG.GameCore.TriggerAbility",
    "RPG.GameCore.TriggerEffect", "RPG.GameCore.RemoveEffect", "RPG.GameCore.IncludeTaskListTemplate",
    "RPG.GameCore.DefineDynamicValue", "RPG.GameCore.SetDynamicValueByProperty",
    "RPG.GameCore.SetDynamicValueByAddValue", "RPG.GameCore.SetDynamicValueByCopying",
    "RPG.GameCore.SetDynamicValueByModifierValue", "RPG.GameCore.SetModifierDynamicValue",
    "RPG.GameCore.SetDynamicValueByCurrentBP", "RPG.GameCore.SetDynamicValueByMaxBP",
    "RPG.GameCore.SetDynamicValueByVariateType", "RPG.GameCore.SetDynamicValueByAttackTargetCount",
    "RPG.GameCore.SetDynamicValueByShield",
    "RPG.GameCore.StackProperty",
    "RPG.GameCore.ModifierAttachEffect", "RPG.GameCore.OwnerEntityAddAbility",
    "RPG.GameCore.CreateBattleEvent", "RPG.GameCore.ModifyVersusBarProperty",
    "RPG.GameCore.SetEnergyBarState", "RPG.GameCore.CharacterChangePhase",
    "RPG.GameCore.SetModifierDynamicValue", "RPG.GameCore.ModifyTeamBoostPoint",
    "RPG.GameCore.ModifyTeamBoostPointMax", "RPG.GameCore.ModifyCurrentSkillDelayCost",
    "RPG.GameCore.ModifySkillPropertyByName", "RPG.GameCore.ForceKill",
    "RPG.GameCore.TurnInsertAction", "RPG.GameCore.TurnInsertAbilityCondition",
    "RPG.GameCore.ChangeBattleEventOwner",
    "RPG.GameCore.RandomConfig", "RPG.GameCore.RandomSelectDynamicValue",
    "RPG.GameCore.SetDynamicEntityParam", "RPG.GameCore.TriggerCustomString",
    "RPG.GameCore.PredicateTaskList", "RPG.GameCore.ByAnd", "RPG.GameCore.ByAny",
    "RPG.GameCore.ByCompareDynamicValue", "RPG.GameCore.ByIsContainModifier",
    "RPG.GameCore.ByCompareModifierValue", "RPG.GameCore.ByCompareHPRatio",
    "RPG.GameCore.ByTargetTeam", "RPG.GameCore.ByAttackType", "RPG.GameCore.ByCurrentSkillType",
    "RPG.GameCore.ByRankActivated", "RPG.GameCore.BySkillPointActivated",
    "RPG.GameCore.ByIsInsertAction", "RPG.GameCore.ByIsCurrentSkillActive",
    "RPG.GameCore.ByCompareWaveCount", "RPG.GameCore.ByCharacterDamageType",
    "RPG.GameCore.ByTargetListIntersects", "RPG.GameCore.ByTargetEntityType",
    "RPG.GameCore.ByHasStanceWeak", "RPG.GameCore.ByCompareCharacterNumber",
    "RPG.GameCore.ByIsTeamLocationIndexType", "RPG.GameCore.ByCurrentSkillName",
    "RPG.GameCore.ByTargetAliveState", "RPG.GameCore.ByNot",
    "RPG.GameCore.ByHaveEnemyAlive", "RPG.GameCore.ByCompareParamValue",
    "RPG.GameCore.ByCompareParamString", "RPG.GameCore.ByIsTargetValid",
    "RPG.GameCore.ByIsTurnOwnerEntity", "RPG.GameCore.ByIsTurnActionEntity",
    "RPG.GameCore.ByContainBehaviorFlag", "RPG.GameCore.ByCheckModifierCallBackName",
    "RPG.GameCore.ByCompareTarget", "RPG.GameCore.ByCompareMonsterPhase",
    "RPG.GameCore.ByCheckCustomValueBool", "RPG.GameCore.ByCompareBattleEventID",
    "RPG.GameCore.ByCompareMonsterID", "RPG.GameCore.ByCompareCharacterID",
    "RPG.GameCore.ByCompareMonsterRank",
}


def node_type(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    t = node.get("$type") or node.get("Type") or node.get("type")
    return str(t) if t is not None else None


def classify_node_type(t: str | None) -> str:
    if not t or str(t) in {"None", "null"}:
        return "container_or_literal"
    if t in VISUAL_OR_TIMELINE_TYPES:
        return "visual_or_timeline"
    if t in TARGETING_TYPES:
        return "targeting"
    if t in CONDITION_TYPES or t.startswith("RPG.GameCore.By"):
        return "condition"
    if t in ACTION_CHAIN_TYPES:
        return "action_chain"
    if t in EFFECT_TYPES:
        return "effect"
    if t.startswith("RPG.GameCore."):
        return "unknown_gamecore"
    return "external_or_unknown"


def is_combat_relevant_type(t: str | None) -> bool:
    cat = classify_node_type(t)
    return cat not in {"visual_or_timeline", "targeting", "container_or_literal"}


def value_expr(raw: Any) -> Any:
    """Return a stable expression object from TBGD dynamic/fixed value wrappers."""
    raw = unwrap_value(raw)
    if isinstance(raw, dict):
        if raw.get("IsDynamic") is False and "FixedValue" in raw:
            fv = raw.get("FixedValue")
            return unwrap_value(fv.get("Value") if isinstance(fv, dict) else fv)
        if raw.get("IsDynamic") is True:
            expr = raw.get("PostfixExpr") or {}
            return {
                "expr_kind": "tbgd_postfix_dynamic",
                "opcodes": expr.get("OpCodes"),
                "fixed_values": unwrap_value(expr.get("FixedValues", [])),
                "dynamic_hashes": unwrap_value(expr.get("DynamicHashes", [])),
            }
        if set(raw.keys()) == {"Value"}:
            return unwrap_value(raw["Value"])
        if "Hash" in raw and len(raw) == 1:
            return {"hash": raw.get("Hash")}
    return raw


def name_value(raw: Any) -> str | None:
    raw = unwrap_value(raw)
    if isinstance(raw, dict):
        v = raw.get("Value") or raw.get("Name") or raw.get("Hash")
        return str(v) if v is not None else None
    if raw is None:
        return None
    return str(raw)


def target_policy(raw: Any) -> str | None:
    raw = unwrap_value(raw)
    if isinstance(raw, dict):
        t = node_type(raw)
        if t == "RPG.GameCore.TargetAlias":
            alias = raw.get("Alias")
            return TARGET_ALIAS_MAP.get(str(alias), f"tbgd_alias:{alias}")
        if "TargetType" in raw:
            return target_policy(raw.get("TargetType"))
    if isinstance(raw, str):
        return TARGET_ALIAS_MAP.get(raw, f"tbgd_alias:{raw}")
    return None


def attack_data_to_packet(raw: dict[str, Any]) -> dict[str, Any]:
    raw = unwrap_value(raw or {})
    dmg_type = raw.get("DamageType")
    if isinstance(dmg_type, dict):
        dmg_type = dmg_type.get("DamageType")
    stance_type = raw.get("StanceDamageType")
    if isinstance(stance_type, dict):
        stance_type = stance_type.get("DamageType")
    return {
        "type": "damage_packet",
        "damage_type": dmg_type,
        "attack_type": raw.get("AttackType"),
        "scaling": {
            "stat": "atk",
            "multiplier_expr": value_expr(raw.get("DamagePercentage")),
        },
        "toughness": {
            "toughness_reduction_expr": value_expr(raw.get("StanceValue")),
            "stance_damage_type": stance_type,
        },
        "sp_hit_ratio_expr": value_expr(raw.get("SPHitRatio")),
        "hit_split_ratio_expr": value_expr(raw.get("HitSplitRatio")),
        "hit_animation": raw.get("HitAnimation"),
        "source_node_type": "RPG.GameCore.AttackData",
    }


def compare_op(raw: Any) -> str | None:
    if raw is None:
        return None
    table = {
        "Equal": "==", "NotEqual": "!=", "Less": "<", "LessEqual": "<=",
        "Greater": ">", "GreaterEqual": ">=", "GreaterThan": ">", "LessThan": "<",
    }
    return table.get(str(raw), str(raw))


def lower_condition(node: Any) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    t = node_type(node)
    inv = bool(node.get("Inverse", False))
    out: dict[str, Any] | None = None
    if t == "RPG.GameCore.ByAnd":
        out = {"type": "all", "conditions": [c for c in (lower_condition(x) for x in node.get("PredicateList", [])) if c is not None]}
    elif t == "RPG.GameCore.ByAny":
        out = {"type": "any", "conditions": [c for c in (lower_condition(x) for x in node.get("PredicateList", [])) if c is not None]}
    elif t == "RPG.GameCore.ByCompareDynamicValue":
        out = {
            "type": "compare_dynamic_value",
            "key": name_value(node.get("DynamicKey")),
            "op": compare_op(node.get("CompareType")),
            "value_expr": value_expr(node.get("CompareValue")),
        }
    elif t == "RPG.GameCore.ByRandomChance":
        out = {
            "type": "random_chance",
            "chance_expr": value_expr(node.get("Chance")),
            "source_node_type": t,
        }
    elif t == "RPG.GameCore.ByIsContainModifier":
        out = {"type": "has_status", "target_policy": target_policy(node.get("TargetType")), "status_id": name_value(node.get("ModifierName"))}
    elif t == "RPG.GameCore.ByCompareModifierValue":
        out = {
            "type": "compare_status_value",
            "target_policy": target_policy(node.get("TargetType")),
            "status_id": name_value(node.get("ModifierName")),
            "value_type": node.get("ValueType"),
            "op": compare_op(node.get("CompareType")),
            "value_expr": value_expr(node.get("CompareValue")),
        }
    elif t == "RPG.GameCore.ByCompareHPRatio":
        out = {"type": "compare_hp_ratio", "target_policy": target_policy(node.get("TargetType")), "op": compare_op(node.get("CompareType")), "value_expr": value_expr(node.get("CompareValue"))}
    elif t == "RPG.GameCore.ByTargetTeam":
        out = {"type": "target_team", "target_policy": target_policy(node.get("TargetType")), "team": node.get("Team", node.get("TargetTeam"))}
    elif t in {"RPG.GameCore.ByAttackType", "RPG.GameCore.ByCurrentSkillType"}:
        out = {"type": "action_type", "action_type": node.get("AttackType", node.get("SkillType", node.get("CurrentSkillType")))}
    elif t == "RPG.GameCore.ByRankActivated":
        out = {"type": "eidolon_or_rank_active", "trigger_key": name_value(node.get("TriggerKey"))}
    elif t == "RPG.GameCore.BySkillPointActivated":
        out = {"type": "skill_point_activated"}
    elif t == "RPG.GameCore.ByIsInsertAction":
        out = {"type": "is_insert_action"}
    elif t == "RPG.GameCore.ByIsCurrentSkillActive":
        out = {"type": "is_current_skill_active", "target_policy": target_policy(node.get("TargetType"))}
    elif t == "RPG.GameCore.ByCompareWaveCount":
        out = {"type": "compare_wave_count", "op": compare_op(node.get("CompareType")), "value_expr": value_expr(node.get("CompareValue"))}
    elif t == "RPG.GameCore.ByCharacterDamageType":
        out = {"type": "character_damage_type", "target_policy": target_policy(node.get("TargetType")), "damage_type": node.get("DamageType")}
    elif t == "RPG.GameCore.ByContainBehaviorFlag":
        out = {"type": "contains_behavior_flag", "target_policy": target_policy(node.get("TargetType")), "flag": node.get("Flag", node.get("BehaviorFlag"))}
    elif t == "RPG.GameCore.ByCheckModifierCallBackName":
        out = {"type": "modifier_callback_name", "callback": node.get("CallbackName"), "status_id": name_value(node.get("ModifierName"))}
    elif t == "RPG.GameCore.ByCompareTarget":
        out = {"type": "compare_target", "left": target_policy(node.get("TargetType")), "right": target_policy(node.get("TargetType2", node.get("CompareTarget"))), "op": compare_op(node.get("CompareType"))}
    elif t == "RPG.GameCore.ByCompareMonsterPhase":
        out = {"type": "compare_monster_phase", "target_policy": target_policy(node.get("TargetType")), "op": compare_op(node.get("CompareType")), "value_expr": value_expr(node.get("CompareValue"))}
    elif t == "RPG.GameCore.ByCheckCustomValueBool":
        out = {"type": "custom_bool", "key": name_value(node.get("CustomValueKey", node.get("DynamicKey"))), "expected": value_expr(node.get("Value", True))}
    elif t == "RPG.GameCore.ByCompareBattleEventID":
        out = {"type": "compare_battle_event_id", "event_id": name_value(node.get("BattleEventID")), "op": compare_op(node.get("CompareType"))}
    elif t == "RPG.GameCore.ByCompareMonsterID":
        out = {"type": "compare_monster_id", "target_policy": target_policy(node.get("TargetType")), "monster_id": name_value(node.get("MonsterID")), "op": compare_op(node.get("CompareType"))}
    elif t == "RPG.GameCore.ByCompareCharacterID":
        out = {"type": "compare_character_id", "target_policy": target_policy(node.get("TargetType")), "character_id": name_value(node.get("CharacterID")), "op": compare_op(node.get("CompareType"))}
    elif t == "RPG.GameCore.ByCompareMonsterRank":
        out = {"type": "compare_monster_rank", "target_policy": target_policy(node.get("TargetType")), "rank": node.get("Rank", node.get("MonsterRank")), "op": compare_op(node.get("CompareType"))}
    elif t == "RPG.GameCore.ByTargetListIntersects":
        out = {"type": "target_lists_intersect", "first": target_policy(node.get("FirstTargetType")), "second": target_policy(node.get("SecondTargetType")), "first_alive_only": node.get("FirstTargetAliveOnly"), "second_alive_only": node.get("SecondTargetAliveOnly")}
    elif t == "RPG.GameCore.ByTargetEntityType":
        out = {"type": "target_entity_type", "target_policy": target_policy(node.get("TargetType")), "entity_type_mask": node.get("EntityTypeMask")}
    elif t == "RPG.GameCore.ByHasStanceWeak":
        out = {"type": "has_weakness", "target_policy": target_policy(node.get("TargetType")), "weakness_type": node.get("WeakType")}
    elif t == "RPG.GameCore.ByCompareCharacterNumber":
        out = {"type": "compare_character_number", "target_policy": target_policy(node.get("TargetType")), "predicate": lower_condition(node.get("Predicate")), "op": compare_op(node.get("CompareType")), "value_expr": value_expr(node.get("CompareNumber"))}
    elif t == "RPG.GameCore.ByIsTeamLocationIndexType":
        out = {"type": "team_location_index_type", "target_policy": target_policy(node.get("TargetType")), "team_type": node.get("TeamType"), "index_type": node.get("Type")}
    elif t == "RPG.GameCore.ByCurrentSkillName":
        out = {"type": "current_skill_name", "skill_name": name_value(node.get("SkillName")), "access_client_active_skill": node.get("AccessClientActiveSkill")}
    elif t == "RPG.GameCore.ByTargetAliveState":
        out = {"type": "target_alive_state", "target_policy": target_policy(node.get("TargetType")), "alive_state": node.get("AliveState", node.get("TargetAliveState"))}
    elif t == "RPG.GameCore.ByNot":
        out = {"type": "not", "condition": lower_condition(node.get("Predicate", node.get("Condition")))}
    elif t == "RPG.GameCore.ByHaveEnemyAlive":
        out = {"type": "any_enemy_alive", "target_policy": target_policy(node.get("TargetType"))}
    elif t == "RPG.GameCore.ByCompareParamValue":
        out = {"type": "compare_param_value", "param": name_value(node.get("ParamName", node.get("Param"))), "op": compare_op(node.get("CompareType")), "value_expr": value_expr(node.get("CompareValue", node.get("Value")))}
    elif t == "RPG.GameCore.ByCompareParamString":
        out = {"type": "compare_param_string", "param": name_value(node.get("ParamName", node.get("Param"))), "op": compare_op(node.get("CompareType")), "value": name_value(node.get("CompareValue", node.get("Value")))}
    elif t == "RPG.GameCore.ByIsTargetValid":
        out = {"type": "is_target_valid", "target_policy": target_policy(node.get("TargetType"))}
    elif t == "RPG.GameCore.ByIsTurnOwnerEntity":
        out = {"type": "is_turn_owner_entity", "target_policy": target_policy(node.get("TargetType"))}
    elif t == "RPG.GameCore.ByIsTurnActionEntity":
        out = {"type": "is_turn_action_entity", "target_policy": target_policy(node.get("TargetType"))}
    elif str(t).startswith("RPG.GameCore.ByCompare"):
        out = {
            "type": "generic_compare_condition",
            "predicate_name": str(t).rsplit('.', 1)[-1],
            "target_policy": target_policy(node.get("TargetType")),
            "op": compare_op(node.get("CompareType")),
            "value_expr": value_expr(node.get("CompareValue", node.get("Value", node.get("CompareNumber")))),
            "raw_keys": sorted([k for k in node.keys() if k != "$type"]),
        }
    elif str(t).startswith("RPG.GameCore.By"):
        out = {
            "type": "generic_predicate_condition",
            "predicate_name": str(t).rsplit('.', 1)[-1],
            "target_policy": target_policy(node.get("TargetType")),
            "raw_keys": sorted([k for k in node.keys() if k != "$type"]),
        }
    if out is not None:
        out["source_node_type"] = t
        if inv:
            return {"type": "not", "condition": out, "source_node_type": t}
    return out


def lower_node(node: Any) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    t = node_type(node)
    if not t:
        return None
    if t not in LOWERABLE_TYPES and not str(t).startswith("RPG.GameCore.By"):
        return None

    if t == "RPG.GameCore.PredicateTaskList":
        return {
            "type": "conditional_branch",
            "condition": lower_condition(node.get("Predicate")),
            "success_task_count": len(node.get("SuccessTaskList", [])) if isinstance(node.get("SuccessTaskList"), list) else 0,
            "failed_task_count": len(node.get("FailedTaskList", [])) if isinstance(node.get("FailedTaskList"), list) else 0,
            "source_node_type": t,
        }

    cond = lower_condition(node)
    if cond is not None:
        return cond

    if t == "RPG.GameCore.RandomConfig":
        return {
            "type": "random_config",
            "odds_exprs": [value_expr(x) for x in node.get("OddsList", [])] if isinstance(node.get("OddsList"), list) else [],
            "choice_count": len(node.get("TaskList", [])) if isinstance(node.get("TaskList"), list) else 0,
            "random_count_expr": value_expr(node.get("RandomCount")) if node.get("RandomCount") is not None else None,
            "random_unique": bool(node.get("RandomUnique", False)),
            "random_mask_key": name_value(node.get("RandomMaskKey")) if node.get("RandomMaskKey") is not None else None,
            "auto_reset_random_mask": bool(node.get("AutoResetRandomMask", True)) if node.get("AutoResetRandomMask") is not None else None,
            "random_mask_target_policy": target_policy(node.get("RandomMaskTarget")) if node.get("RandomMaskTarget") is not None else None,
            "source_node_type": t,
        }

    if t == "RPG.GameCore.RandomSelectDynamicValue":
        return {
            "type": "random_select_dynamic_value",
            "key": name_value(node.get("DynamicKey")),
            "value_exprs": [value_expr(x) for x in node.get("ValueList", [])] if isinstance(node.get("ValueList"), list) else [],
            "context_scope": node.get("ContextScope"),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.SetDynamicEntityParam":
        return {
            "type": "set_dynamic_entity_param",
            "key": name_value(node.get("DynamicKey")),
            "target_policy": target_policy(node.get("ReadTargetType", node.get("TargetType"))),
            "param_target_policy": target_policy(node.get("ParamTargetType")),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.TriggerCustomString":
        return {
            "type": "trigger_custom_string",
            "custom_string": name_value(node.get("CustomString")) or node.get("CustomString"),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.AttackData":
        return attack_data_to_packet(node)

    if t == "RPG.GameCore.DamageByAttackProperty":
        packet = attack_data_to_packet(node.get("AttackProperty", {}))
        packet["target_policy"] = target_policy(node.get("TargetType"))
        packet["can_trigger_last_kill"] = bool(node.get("CanTriggerLastKill", False))
        packet["source_node_type"] = t
        return packet

    if t == "RPG.GameCore.AddModifier":
        return {
            "type": "add_status",
            "target_policy": target_policy(node.get("TargetType")),
            "status_id": name_value(node.get("ModifierName")),
            "reference_modifier": node.get("ReferenceModifierName"),
            "chance_expr": value_expr(node.get("Chance")) if "Chance" in node else None,
            "duration_expr": value_expr(node.get("LifeTime")) if "LifeTime" in node else None,
            "max_stacks_expr": value_expr(node.get("MaxLayer")) if "MaxLayer" in node else None,
            "dynamic_values": {k: value_expr(v) for k, v in unwrap_value(node.get("DynamicValues", {})).items()} if isinstance(unwrap_value(node.get("DynamicValues", {})), dict) else {},
            "source_node_type": t,
        }

    if t in {"RPG.GameCore.RemoveModifier", "RPG.GameCore.RemoveSelfModifier"}:
        return {
            "type": "remove_status",
            "target_policy": target_policy(node.get("TargetType")) or ("self" if t.endswith("RemoveSelfModifier") else None),
            "status_id": name_value(node.get("ModifierName")),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.SetDynamicValue":
        return {
            "type": "set_flag",
            "key": name_value(node.get("DynamicKey")),
            "value_expr": value_expr(node.get("Value")),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.ModifySPNew":
        return {
            "type": "modify_skill_points",
            "target_policy": target_policy(node.get("TargetType")),
            "delta_expr": value_expr(node.get("AddValue")),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.HealHP":
        return {
            "type": "heal_unit",
            "target_policy": target_policy(node.get("TargetType")),
            "formula_type": node.get("FormulaType"),
            "heal_pct_expr": value_expr(node.get("HealPercentage")),
            "flat_expr": value_expr(node.get("ModifyValue")),
            "source_node_type": t,
        }

    if t in {"RPG.GameCore.SetActionDelay", "RPG.GameCore.ModifyActionDelay"}:
        # TBGD uses several field names for action-value/delay mutations:
        # - ModifyActionDelay commonly stores additive normalized delay in
        #   AddNormalizedValue.
        # - SetActionDelay commonly stores absolute normalized delay in
        #   NormalizedValue.
        # Older lowering only looked at DelayRatio/ActionDelayRatio/Value, which
        # silently dropped real status callbacks such as Seele Rippling Waves and
        # Dan Heng Permansor Terrae battle-event setup.
        raw_delay = (
            node.get("AddNormalizedValue")
            if node.get("AddNormalizedValue") is not None else
            node.get("NormalizedValue")
            if node.get("NormalizedValue") is not None else
            node.get("AddDelayRatio")
            if node.get("AddDelayRatio") is not None else
            node.get("DelayRatio", node.get("ActionDelayRatio", node.get("Value")))
        )
        return {
            "type": "modify_action_value",
            "target_policy": target_policy(node.get("TargetType")),
            "delay_expr": value_expr(raw_delay),
            "mode": "set" if t == "RPG.GameCore.SetActionDelay" else "add",
            "source_node_type": t,
        }

    if t == "RPG.GameCore.TurnInsertAbility":
        return {
            "type": "enqueue_action",
            "actor_policy": target_policy(node.get("TargetType")) or "self",
            "action_id": name_value(node.get("AbilityName")),
            "target_policy": target_policy(node.get("AbilityTarget")),
            "priority": node.get("InsertAbilityPriority"),
            "show_in_action_bar": node.get("ShowInActionBar"),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.SummonMonster":
        return {
            "type": "summon_unit",
            "monster_id": name_value(node.get("MonsterID")) or name_value(node.get("NPCMonsterID")),
            "target_policy": target_policy(node.get("TargetType")),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.DispelStatus":
        return {
            "type": "dispel_status",
            "target_policy": target_policy(node.get("TargetType")),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.ModifyDamageData":
        fields = {k: value_expr(v) for k, v in node.items() if k != "$type"}
        return {"type": "modify_damage_data", "fields": fields, "source_node_type": t}

    if t == "RPG.GameCore.TriggerAbility":
        return {
            "type": "trigger_ability",
            "actor_policy": target_policy(node.get("TargetType")) or "self",
            "ability_name": name_value(node.get("AbilityName")),
            "is_skill_perform": node.get("IsSkillPerform"),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.TriggerEffect":
        return {
            "type": "trigger_effect",
            "target_policy": target_policy(node.get("TargetType")),
            "effect_id": name_value(node.get("EffectID", node.get("EffectName"))),
            "effect_path": name_value(node.get("EffectPath")) or node.get("EffectPath"),
            "source_node_type": t,
        }
    if t == "RPG.GameCore.RemoveEffect":
        return {
            "type": "remove_effect",
            "target_policy": target_policy(node.get("TargetType")),
            "effect_id": name_value(node.get("EffectID", node.get("EffectName"))),
            "effect_path": name_value(node.get("EffectPath")) or node.get("EffectPath"),
            "source_node_type": t,
        }
    if t == "RPG.GameCore.IncludeTaskListTemplate":
        return {
            "type": "include_task_list_template",
            "template_id": name_value(node.get("TemplateName", node.get("TaskListTemplate", node.get("Name")))),
            "dynamic_values": {str(k): value_expr(v) for k, v in unwrap_value(node.get("DynamicValues", {})).items()} if isinstance(unwrap_value(node.get("DynamicValues", {})), dict) else {},
            "target_policy": target_policy(node.get("ParamTarget", node.get("TargetType"))),
            "source_node_type": t,
        }
    if t == "RPG.GameCore.DefineDynamicValue":
        return {"type": "define_flag", "key": name_value(node.get("DynamicKey")), "value_expr": value_expr(node.get("Value")), "source_node_type": t}
    if t == "RPG.GameCore.SetDynamicValueByProperty":
        return {
            "type": "set_flag_from_property",
            "key": name_value(node.get("DynamicKey")),
            "target_policy": target_policy(node.get("ReadTargetType", node.get("TargetType"))),
            "property": name_value(node.get("Property", node.get("Value"))),
            "source_node_type": t,
        }
    if t == "RPG.GameCore.SetDynamicValueByAddValue":
        return {"type": "add_flag_value", "key": name_value(node.get("DynamicKey")), "delta_expr": value_expr(node.get("AddValue", node.get("Value"))), "source_node_type": t}
    if t == "RPG.GameCore.SetDynamicValueByCopying":
        return {
            "type": "copy_flag",
            "key": name_value(node.get("DynamicKey", node.get("ToDynamicKey"))),
            "source_key": name_value(node.get("SourceDynamicKey", node.get("FromDynamicKey"))),
            "target_policy": target_policy(node.get("ToTargetType", node.get("TargetType"))),
            "source_target_policy": target_policy(node.get("FromTargetType")),
            "source_status_id": name_value(node.get("FromModifierName")),
            "target_context_scope": node.get("TargetContextScope"),
            "source_node_type": t,
        }
    if t == "RPG.GameCore.SetDynamicValueByModifierValue":
        return {
            "type": "set_flag_from_status_value",
            "key": name_value(node.get("DynamicKey")),
            "target_policy": target_policy(node.get("TargetType")),
            "status_id": name_value(node.get("ModifierName")),
            "value_type": node.get("ValueType"),
            "source_node_type": t,
        }
    if t == "RPG.GameCore.StackProperty":
        return {"type": "stack_property", "target_policy": target_policy(node.get("TargetType")), "property": node.get("Property"), "value_expr": value_expr(node.get("Value")), "source_node_type": t}
    if t == "RPG.GameCore.ModifierAttachEffect":
        return {"type": "attach_effect_to_status", "status_id": name_value(node.get("ModifierName")), "effect_id": name_value(node.get("EffectName", node.get("EffectID"))), "source_node_type": t}
    if t == "RPG.GameCore.OwnerEntityAddAbility":
        return {"type": "owner_add_ability", "ability_name": name_value(node.get("AbilityName")), "target_policy": target_policy(node.get("TargetType")), "source_node_type": t}
    if t == "RPG.GameCore.CreateBattleEvent":
        return {"type": "create_battle_event", "battle_event_id": name_value(node.get("BattleEventID")), "source_node_type": t}
    if t == "RPG.GameCore.ModifyVersusBarProperty":
        return {"type": "modify_versus_bar", "property": node.get("Property"), "value_expr": value_expr(node.get("Value")), "source_node_type": t}

    if t == "RPG.GameCore.SetEnergyBarState":
        return {
            "type": "set_energy_bar_state",
            "target_policy": target_policy(node.get("TargetType")) or "self",
            "bar_type": node.get("BarType"),
            "current_state": node.get("CurrentState"),
            "current_count_expr": value_expr(node.get("CurrentCount")),
            "max_count_expr": value_expr(node.get("MaxCount")),
            "active": node.get("Active"),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.CharacterChangePhase":
        return {
            "type": "change_phase",
            "target_policy": target_policy(node.get("TargetType")) or "self",
            "phase_name": name_value(node.get("PhaseName")),
            "phase_anim_config": node.get("PhaseAnimConfig"),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.SetModifierDynamicValue":
        return {
            "type": "set_status_dynamic_value",
            "target_policy": target_policy(node.get("TargetType")),
            "status_id": name_value(node.get("ModifierName")),
            "key": name_value(node.get("DynamicKey")),
            "value_expr": value_expr(node.get("NewValue", node.get("Value"))),
            "source_node_type": t,
        }


    if t == "RPG.GameCore.SetDynamicValueByShield":
        return {
            "type": "set_flag_from_shield",
            "key": name_value(node.get("DynamicKey")),
            "target_policy": target_policy(node.get("TargetType")),
            "value_semantics": "current_shield_value",
            "source_node_type": t,
        }

    if t in {"RPG.GameCore.SetDynamicValueByCurrentBP", "RPG.GameCore.SetDynamicValueByMaxBP", "RPG.GameCore.SetDynamicValueByVariateType", "RPG.GameCore.SetDynamicValueByAttackTargetCount"}:
        return {
            "type": "set_flag_from_context_value",
            "context_value_type": t.rsplit('.', 1)[-1],
            "key": name_value(node.get("DynamicKey")),
            "target_policy": target_policy(node.get("TargetType")),
            "variate_type": node.get("VariateType"),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.ModifyTeamBoostPoint":
        return {"type": "modify_skill_points", "delta_expr": value_expr(node.get("ModifyValue", node.get("AddValue", node.get("Value")))), "modify_function": node.get("ModifyFunction"), "resource_alias": "team_boost_point", "source_node_type": t}

    if t == "RPG.GameCore.ModifyTeamBoostPointMax":
        return {"type": "modify_skill_point_cap", "delta_expr": value_expr(node.get("ModifyValue", node.get("AddValue", node.get("Value")))), "modify_function": node.get("ModifyFunction"), "resource_alias": "team_boost_point", "source_node_type": t}

    if t == "RPG.GameCore.ModifyCurrentSkillDelayCost":
        return {"type": "modify_current_skill_delay_cost", "value_expr": value_expr(node.get("Value", node.get("AddValue"))), "source_node_type": t}

    if t == "RPG.GameCore.ModifySkillPropertyByName":
        return {"type": "modify_skill_property", "skill_name": name_value(node.get("SkillName")), "property": node.get("Property"), "value_expr": value_expr(node.get("Value", node.get("AddValue"))), "source_node_type": t}

    if t == "RPG.GameCore.ForceKill":
        return {"type": "force_defeat", "target_policy": target_policy(node.get("TargetType")), "source_node_type": t}

    if t == "RPG.GameCore.TurnInsertAction":
        return {
            "type": "enqueue_turn_action",
            "actor_policy": target_policy(node.get("TargetType")) or "self",
            "action_id": name_value(node.get("PrepareAbilityName", node.get("AbilityName"))),
            "action_type": node.get("ActionType", node.get("SkillType")),
            "extra_turn_type": name_value(node.get("CustomTag")),
            "target_policy": target_policy(node.get("AutoCastTargetType", node.get("TargetType"))),
            "auto_cast": node.get("AutoCast"),
            "priority": node.get("Priority", node.get("InsertActionPriority")),
            "source_node_type": t,
        }

    if t == "RPG.GameCore.TurnInsertAbilityCondition":
        return {"type": "conditional_enqueue_action", "actor_policy": target_policy(node.get("TargetType")) or "self", "action_id": name_value(node.get("AbilityName")), "condition": lower_condition(node.get("Predicate", node.get("Condition"))), "priority": node.get("Priority", node.get("InsertAbilityPriority")), "source_node_type": t}

    if t == "RPG.GameCore.ChangeBattleEventOwner":
        return {"type": "change_battle_event_owner", "event_id": name_value(node.get("BattleEventID", node.get("EventID"))), "owner_policy": target_policy(node.get("TargetType")), "source_node_type": t}

    return None


def walk_nodes(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            child = f"{path}.{k}" if path else str(k)
            yield from walk_nodes(v, child)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_nodes(v, f"{path}[{i}]")


def ability_index(ability_file: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {a.get("Name"): a for a in ability_file.get("AbilityList", []) if isinstance(a, dict) and a.get("Name")}


def referenced_ability_names(node: Any) -> list[str]:
    names = []
    if isinstance(node, dict):
        t = node_type(node)
        if t in {"RPG.GameCore.TriggerAbility", "RPG.GameCore.TurnInsertAbility", "RPG.GameCore.OwnerEntityAddAbility"}:
            n = name_value(node.get("AbilityName"))
            if n:
                names.append(n)
        for v in node.values():
            names.extend(referenced_ability_names(v))
    elif isinstance(node, list):
        for x in node:
            names.extend(referenced_ability_names(x))
    return names


def summarize_ability_chain(index: dict[str, dict[str, Any]], entry_name: str | None, *, max_depth: int = 4, max_lowered: int = 80, max_nodes: int = 3000) -> dict[str, Any]:
    if not entry_name:
        return {"entry_ability": None, "found": False}
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(entry_name, 0)]
    ordered: list[str] = []
    node_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    lowered: list[dict[str, Any]] = []
    unresolved_refs: list[str] = []
    unlowered_relevant: Counter[str] = Counter()

    scanned_nodes = 0
    truncated = False
    while queue:
        name, depth = queue.pop(0)
        if name in visited or depth > max_depth:
            continue
        if scanned_nodes >= max_nodes:
            truncated = True
            break
        ability = index.get(name)
        if ability is None:
            unresolved_refs.append(name)
            continue
        visited.add(name)
        ordered.append(name)
        for key, value in ability.items():
            if isinstance(key, str) and key.startswith("On"):
                event_counts[key] += len(value) if isinstance(value, list) else 1
        refs_from_this_ability: list[str] = []
        for path, node in walk_nodes(ability):
            scanned_nodes += 1
            if scanned_nodes >= max_nodes:
                truncated = True
                break
            t = node_type(node)
            if not t:
                continue
            node_counts[t] += 1
            cat = classify_node_type(t)
            category_counts[cat] += 1
            low = lower_node(node)
            if low is not None:
                if low.get("type") in {"trigger_ability", "enqueue_action"} and low.get("ability_name"):
                    refs_from_this_ability.append(str(low["ability_name"]))
                if len(lowered) < max_lowered:
                    low["source_path"] = path
                    lowered.append(low)
            elif is_combat_relevant_type(t):
                unlowered_relevant[t] += 1
        # Follow only ability references discovered by lower_node while scanning,
        # so large callback/template trees are not walked a second time.
        for ref in refs_from_this_ability:
            # Camera/cutin/timeline abilities are visual-only and are often not present
            # in the same ability index.  Treat them as nonblocking references rather
            # than unresolved combat dependencies.
            if any(token in ref for token in ("Camera", "CutIn", "Timeline")):
                continue
            if ref not in visited:
                queue.append((ref, depth + 1))

    return {
        "entry_ability": entry_name,
        "found": entry_name in visited,
        "visited_abilities": ordered,
        "unresolved_refs": sorted(set(unresolved_refs)),
        "event_counts": dict(event_counts.most_common()),
        "category_counts": dict(category_counts.most_common()),
        "top_node_types": dict(node_counts.most_common(30)),
        "lowered_preview": lowered,
        "truncated": truncated,
        "scanned_nodes": scanned_nodes,
        "unlowered_combat_node_types": dict(unlowered_relevant.most_common(30)),
        "lowering_coverage": {
            "lowered_count": len(lowered),
            "unlowered_relevant_count": sum(unlowered_relevant.values()),
            "coverage_estimate": (len(lowered) / max(1, len(lowered) + sum(unlowered_relevant.values()))),
        },
    }


def classify_inventory(counter: dict[str, int] | Counter[str]) -> dict[str, Any]:
    by_category: Counter[str] = Counter()
    by_lowering_status: Counter[str] = Counter()
    rows = []
    for t, count in sorted(counter.items(), key=lambda x: (-x[1], x[0])):
        cat = classify_node_type(t if t != "None" else None)
        if cat == "visual_or_timeline":
            status = "ignore_visual_timeline"
        elif cat == "targeting":
            status = "normalized_targeting"
        elif t in LOWERABLE_TYPES or str(t).startswith("RPG.GameCore.By"):
            status = "lowerer_available"
        elif cat in {"condition", "action_chain", "effect"}:
            status = "combat_relevant_backlog"
        else:
            status = "nonblocking_or_unknown"
        by_category[cat] += count
        by_lowering_status[status] += count
        rows.append({"node_type": t, "count": count, "category": cat, "lowering_status": status})
    return {
        "category_counts": dict(by_category.most_common()),
        "lowering_status_counts": dict(by_lowering_status.most_common()),
        "node_type_rows": rows,
    }
