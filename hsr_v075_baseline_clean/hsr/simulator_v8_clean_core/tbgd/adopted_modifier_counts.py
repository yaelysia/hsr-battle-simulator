"""Adopted content data; executable consumers do not identify these source names.

KQM March 7th guide (version 1.5): two Counters per turn, E4 adds one.
https://hsr.keqingmains.com/march-7th/
https://srl.keqingmains.com/characters/ice/march_7th

These entries resolve only the listed omitted fields. Count=3 is not a MaxLayer
contract. Explicit reset expressions remain authoritative; a completed Counter
consumes one use. This does not define arbitrary SetModifierValue defaults.

KQM Beginner's Guide, Elements / Quantum (page version unspecified): ordinary
Entanglement starts at one damage stack, gains one when hit, and caps at five.
https://hsr.keqingmains.com/misc/beginner-guide/
The raw formula adds one to MDF_BeingHitDamageValue. Its two unassigned local
parameters therefore receive 5 (maximum total stacks) and 1 (per-hit increment).
These are adopted content parameters, not values claimed to exist in TBGD.

KQM Asta guide (version 1.4): Charging gains one per different enemy hit, plus
one for Fire Weakness, and caps at five. Each count grants the talent's ATK
bonus; TBGD already multiplies that bonus by the count in its property formula.
https://hsr.keqingmains.com/asta/
The listed setters update an independent count, without multiplying the
already-totaled property contribution or declaring arbitrary Count=MaxLayer.
"""

SOURCE = "Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json"
MODIFIER = "MAvatar_March7th_00_Passive_CanAttack"
RESEARCH = "https://hsr.keqingmains.com/march-7th/"
BASE_VALUE = {"IsDynamic": True, "PostfixExpr": {
    "OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [1299003598],
}}
EXTRA_VALUE = {"IsDynamic": True, "PostfixExpr": {
    "OpCodes": "AQAAAAIR", "FixedValues": [{"Value": 1}], "DynamicHashes": [1299003598],
}}
_RESET = {"$type": "RPG.GameCore.SetModifierValue", "ModifierName": {"Value": MODIFIER}}

ADOPTED_MODIFIER_COUNTS = {
    (SOURCE, f"{prefix}.{branch}[0]"): {
        "expected_task": {**_RESET, "Value": value},
        "operation": "Set", "research": RESEARCH, "version": "1.5",
    }
    for prefix in (
        "$.AbilityList[7].OnStart[3]",
        "$.AbilityList[7].Modifiers.MAvatar_March7th_00_Passive._CallbackList[0].CallbackConfig[1]",
    )
    for branch, value in (("SuccessTaskList", EXTRA_VALUE), ("FailedTaskList", BASE_VALUE))
}
ADOPTED_MODIFIER_COUNTS[(SOURCE, "$.AbilityList[8].OnStart[10]")] = {
    "expected_task": {**_RESET, "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
                      "ModifyFunction": "Add"},
    "operation": "Add", "amount": -1, "research": RESEARCH, "version": "1.5",
}
ADOPTED_MODIFIER_COUNTS[(SOURCE, "$.AbilityList[8].OnStart[11].SuccessTaskList[0]")] = {
    "expected_task": {
        "$type": "RPG.GameCore.SetDynamicValueByModifierValue", "ModifierName": MODIFIER,
        "Multiplier": {"IsDynamic": False, "FixedValue": {"Value": 1}},
        "DynamicKey": "Mar7th_00_Passive_CounterView", "ContextScope": "ContextCaster",
    },
    "operation": "Read", "research": RESEARCH, "version": "1.5",
}

# The listener is attached to every teammate, while remaining Counters belong
# to the talent's caster. Only this verified omitted target is projected.
ADOPTED_MODIFIER_COUNT_CONDITIONS = {
    (SOURCE, "$.GlobalModifiers.MAvatar_March7th_00_BPSkill_Shield_Counter._CallbackList[0].CallbackConfig[0].Predicate.PredicateList[2]"): {
        "expected_payload": {"ModifierName": MODIFIER, "CompareType": "Greater",
                             "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 0}}},
        "target_alias": "Caster", "research": RESEARCH, "version": "1.5",
    },
}

ENTANGLE_SOURCE = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
ENTANGLE_MODIFIER = "MCommon_Element_Entangle"
ENTANGLE_RESEARCH = "https://hsr.keqingmains.com/misc/beginner-guide/"
_ENTANGLE_PREFIX = f"$.ModifierMap.{ENTANGLE_MODIFIER}._CallbackList"
_ENTANGLE_INCREMENT = {"IsDynamic": True, "PostfixExpr": {
    "OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [560166466],
}}
_ENTANGLE_MAXIMUM = {"IsDynamic": True, "PostfixExpr": {
    "OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [808921108],
}}
for path, function, value in (
    ("[2].CallbackConfig[4].SuccessTaskList[0]", "Set", {"IsDynamic": True, "PostfixExpr": {
        "OpCodes": "AQABAQIR", "FixedValues": [], "DynamicHashes": [-434232686, 560166466],
    }}),
    ("[2].CallbackConfig[4].FailedTaskList[0]", "Set", _ENTANGLE_MAXIMUM),
    ("[4].CallbackConfig[0].SuccessTaskList[0].FailedTaskList[1].SuccessTaskList[1]", "Add", _ENTANGLE_INCREMENT),
    ("[4].CallbackConfig[0].SuccessTaskList[0].FailedTaskList[1].FailedTaskList[1]", "Set", _ENTANGLE_MAXIMUM),
):
    ADOPTED_MODIFIER_COUNTS[(ENTANGLE_SOURCE, _ENTANGLE_PREFIX + path)] = {
        "expected_task": {"$type": "RPG.GameCore.SetModifierValue", "Value": value,
                          **({"ModifyFunction": "Add"} if function == "Add" else {})},
        "operation": function, "target_alias": "ModifierOwnerEntity",
        "modifier_name": ENTANGLE_MODIFIER, "research": ENTANGLE_RESEARCH,
        "version": "unspecified", "condition": "ordinary weakness-break Entanglement",
    }

LINGSHA_SOURCE = "Config/ConfigAbility/Avatar/Avatar_Lingsha_00_Ability.json"
# AvatarSkillConfig 122204, ParamList[4] is 5 at every skill level in 14c1d18f;
# its description explicitly caps Fuyuan's remaining actions at this value.
# The native increment leaves omit that clamp. Keep the actual +3 expression.
ADOPTED_DYNAMIC_MAXIMUMS = {
    (LINGSHA_SOURCE, "Lingsha_AttackTime"): {
        "expected_value": {"IsDynamic": True, "PostfixExpr": {
            "OpCodes": "AQABAQIR", "FixedValues": [], "DynamicHashes": [592537088, 121154993]}},
        "maximum": 5,
        "basis": "AvatarSkillConfig:122204.ParamList[4]及天赋描述，固定14c1d18f，全部技能等级",
    },
}
ADOPTED_PRESENCE_COUNTS = {
    (LINGSHA_SOURCE, "MAvatar_Lingsha_BPSkill_BattleEvent"): {
        "expected_count": {"IsDynamic": True, "PostfixExpr": {
            "OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [-584750360]}},
        "basis": "固定源码Count为BattleEvent_Lingsha_00_IndexID；该标记仅供Lingsha_BattleEventEntity存在性查询。正式单位身份已由出生系统提供，索引不是增益层数或剩余次数。",
    },
}
COMMON_ENTANGLE_SOURCE = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
# The native delayed-damage formula reads (MDF_BeingHitDamageValue + 1);
# these setters mirror that count on the callback's own status instance.
# Actual amounts remain the native expressions. Monster parameters are verified
# at https://honkai-star-rail.fandom.com/wiki/Voidranger%3A_Trampler (version unspecified).
for path, operation, opcodes, hashes in (
    ("[2].CallbackConfig[3]", "Set", "AQAAAAIR", [-434232686]),
    ("[4].CallbackConfig[0].SuccessTaskList[0].FailedTaskList[2]", "Add", "AAAR", []),
    ("[5].CallbackConfig[1].FailedTaskList[2]", "Add", "AAAR", []),
):
    ADOPTED_MODIFIER_COUNTS[(COMMON_ENTANGLE_SOURCE, "$.ModifierMap.MCommon_Entangle._CallbackList" + path)] = {
        "expected_task": {"$type": "RPG.GameCore.SetModifierValue",
            "Value": {"IsDynamic": True, "PostfixExpr": {"OpCodes": opcodes,
                "FixedValues": [{"Value": 1}], "DynamicHashes": hashes}},
            **({"ModifyFunction": "Add"} if operation == "Add" else {})},
        "operation": operation, "target_alias": "ModifierOwnerEntity", "modifier_name": "MCommon_Entangle",
        "research": "Fixed TBGD common Entanglement: own count mirrors delayed-damage stack expression",
        "version": "14c1d18f", "condition": "monster-applied common Entanglement; numeric expressions unchanged",
    }

LINGSHA_MODIFIER = "MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime"
LINGSHA_RESEARCH = (
    "TBGD fixed source shape: the modifier's own OnPhase1 SetModifierValue{ModifyFunction:Add} "
    "with omitted target/modifier/value type is the battle-event attack-time counter; the same "
    "callback reads hash 652368890 into _AttackTime/Lingsha_AttackTime and ShowAttackTime"
)
ADOPTED_MODIFIER_COUNTS[(
    LINGSHA_SOURCE,
    f"$.GlobalModifiers.{LINGSHA_MODIFIER}._CallbackList[1].CallbackConfig[0]",
)] = {
    "expected_task": {"$type": "RPG.GameCore.SetModifierValue", "ModifyFunction": "Add"},
    "operation": "Add",
    "amount": -1,
    "bootstrap_single_instance": True,
    "modifier_name": LINGSHA_MODIFIER,
    "target_alias": "ModifierOwnerEntity",
    "research": LINGSHA_RESEARCH,
    "version": "fixed TBGD 14c1d18f91a8101d610e6c523447a7517de3fae1",
    "condition": (
        "remaining attacks decrease by one per phase, matching the same callback's explicit _AttackTime - 1; omitted target/modifier "
        "resolve to the callback's own modifier on its owner"
    ),
}

ADOPTED_MODIFIER_INITIAL_VALUES = {
    ("Config/ConfigAbility/Monster/Monster_W1_Mecha03_01_Ability.json", "Monster_W1_Mecha03_01_Frozen"): {
        "expected_slot": {"ReadInfo": {"Type": "None", "Index": 0}},
        "by_hash": {"-797864550": 1.0},
        "research": "https://honkai-star-rail.fandom.com/wiki/Frigid_Prowler",
        "version": "unspecified; pinned TBGD 14c1d18f supplies 12% SPD / 20% Ice RES and max 3",
        "condition": "ordinary Deep Freeze adds one stack per successful application; native LayerAddWhenStack slot is unassigned",
    },
    (ENTANGLE_SOURCE, ENTANGLE_MODIFIER): {
        "expected_slot": {"ReadInfo": {"Type": "None", "Index": 0}},
        "by_hash": {"808921108": 5.0, "560166466": 1.0},
        "research": ENTANGLE_RESEARCH, "version": "unspecified",
        "condition": "ordinary weakness-break Entanglement",
    },
}

ASTA_SOURCE = "Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json"
ASTA_RESEARCH = "https://hsr.keqingmains.com/asta/"
for path, modifier, amount, target in (
    ("$.GlobalModifiers.MAvatar_Asta_00_Passive_Charge._CallbackList[1].CallbackConfig[0]",
     "MAvatar_Asta_00_Passive_Charge", {"IsDynamic": True, "PostfixExpr": {
         "OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [-2027709849],
     }}, None),
    ("$.GlobalModifiers.MAvatar_Asta_00_TeamAttackUP._CallbackList[0].CallbackConfig[0]",
     "MAvatar_Asta_00_TeamAttackUP", {"IsDynamic": True, "PostfixExpr": {
         "OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [1434785956],
     }}, None),
    ("$.AbilityList[7].Modifiers.M_Asta_Passive._CallbackList[0].CallbackConfig[0].FailedTaskList[1].FailedTaskList[0]",
     "MAvatar_Asta_00_Passive_Charge", {"IsDynamic": False, "FixedValue": {"Value": 0}}, "Caster"),
):
    ADOPTED_MODIFIER_COUNTS[(ASTA_SOURCE, path)] = {
        "expected_task": {"$type": "RPG.GameCore.SetModifierValue", "ModifierName": {"Value": modifier},
                          "Value": amount, **({"TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": target}}
                                              if target else {})},
        "operation": "Set", "target_alias": "ModifierOwnerEntity",
        "research": ASTA_RESEARCH, "version": "1.4",
        "condition": "Charging count; source property formula already multiplies per-count talent bonus",
    }
