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

ADOPTED_MODIFIER_INITIAL_VALUES = {
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
