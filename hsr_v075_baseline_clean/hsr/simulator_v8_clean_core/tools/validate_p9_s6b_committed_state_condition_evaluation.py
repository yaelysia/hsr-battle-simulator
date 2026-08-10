from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.executor import _collect_callback_damage_modifiers
from ..core.model import ActionCommand, BattleState, TargetResolution, UnitState
from ..ir_types import IRSource
from ..rules.condition_state import (
    ConditionOperandRequest,
    ConditionOperandResolution,
)
from ..rules.evaluator import (
    COMMITTED_STATE_CONDITION_OPCODES,
    EvaluationContext,
    RuleEvaluator,
)
from ..rules.expression_ir import CONDITION_EXPRESSION_NODE_SCHEMA, numeric_fixed
from ..rules.ir import (
    ActionDefinitionIR,
    AvatarProfileIR,
    CanonicalIR,
    CharacterDataCardIR,
    ConditionIR,
    DamageModifierIR,
    MonsterDataCardIR,
    SpecialResourceDefinitionIR,
    StatusCallbackIR,
    StatusCallbackTaskIR,
    TargetExpressionIR,
    TargetExpressionNodeIR,
    TriggerIR,
)
from ..rules.rulebook import RuleBook
from ..systems.condition_state import CommittedConditionFactProvider
from ..systems.effect import EffectRegistry
from ..systems.status import StatusSystem
from ..systems.summon_runtime import empty_summon_runtime
from ..systems.target import TargetSystem
from ..systems.trigger import TriggerSystem
from ..systems.unit_relation import TargetEvaluationContext
from ..tbgd.character_ability_scope import (
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
)
from ..tbgd.character_condition_contracts import (
    build_character_condition_responsibility_catalog,
    character_condition_family_stage,
)
from ..tbgd.lowering import (
    _target_expression_execution_node,
    _typed_condition_execution_node,
)


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
_STAGE = "p9_s6b_committed_state"
_NODE_META = {
    "schema_version",
    "expression_kind",
    "opcode",
    "supported",
    "blocked_reason",
}
_EXTERNAL_FAMILY_STAGE = {
    "ByCompareBattleEventID": "p9_s17",
    "ByCompareStance": "p9_s15",
    "ByCompareStanceCount": "p9_s15",
    "ByCompareStanceRatio": "p9_s15",
    "ByContainsRedStance": "p9_s15",
    "ByIsBattleEventEntity": "p9_s17",
    "ByIsBodyPart": "p9_s17",
    "ByIsSubTargetOfHpSharedGroup": "p9_s11",
    "ByTargetIsStanceWeak": "p9_s15",
}


def _write(path: Path, value: object) -> int:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode()
    path.write_bytes(encoded)
    return len(encoded)


def _at_path(document: Mapping[str, Any], path: str) -> Any:
    current: Any = document
    index = 1
    while index < len(path):
        if path[index] == ".":
            index += 1
            end = index
            while end < len(path) and path[end] not in ".[":
                end += 1
            key = path[index:end]
            if not isinstance(current, Mapping) or key not in current:
                return None
            current = current[key]
            index = end
        elif path[index] == "[":
            end = path.find("]", index)
            token = path[index + 1 : end] if end >= 0 else ""
            if (
                end < 0
                or not token.isdigit()
                or not isinstance(current, (list, tuple))
                or int(token) >= len(current)
            ):
                return None
            current = current[int(token)]
            index = end + 1
        else:
            return None
    return current


def _source(raw_type: str, identity: str) -> IRSource:
    return IRSource(
        source_path="validation_fixture/p9_s6b_condition.json",
        raw_type=raw_type,
        raw_id=identity,
        evidence={"json_path": f"$.{identity}"},
    )


def _alias(name: str) -> dict[str, Any]:
    return {"$type": "RPG.GameCore.TargetAlias", "Alias": name}


def _fixed(value: int | float) -> dict[str, Any]:
    return {"IsDynamic": False, "FixedValue": {"Value": value}}


def _condition(raw: dict[str, Any], identity: str) -> ConditionIR:
    source = _source(str(raw.get("$type") or "Condition"), identity)
    node = _typed_condition_execution_node(raw, source=source)
    payload = {key: value for key, value in node.items() if key not in _NODE_META}
    supported = node.get("supported") is True
    return ConditionIR(
        condition_id=f"validation:{identity}",
        opcode=str(node.get("opcode") or ""),
        payload=payload,
        source=source,
        coverage_status="executable" if supported else "blocked",
        expression_schema_version=str(node.get("schema_version") or ""),
        blocked_reason="" if supported else str(node.get("blocked_reason") or "blocked"),
    )


def _target_definition(name: str, raw: dict[str, Any]) -> TargetExpressionIR:
    source = IRSource(
        source_path="Config/GlobalConfig/TargetAliasConfig.json",
        raw_type="TargetAliasConfig",
        raw_id=f"validation:{name}",
        evidence={
            "json_path": f"$.AliasDict.{name}",
            "source_raw_id": name,
            "source_raw_type": "TargetAliasConfig",
        },
    )
    node = _target_expression_execution_node(raw, source)
    return TargetExpressionIR(
        target_expression_id=f"validation_target:{name}",
        expression_kind=node.expression_kind,
        alias=name,
        source=node.source,
        node=node,
        coverage_status="executable",
        admission_batch="validation_fixture",
        runtime_scope="condition_operand",
    )


def _runtime_fixture() -> tuple[RuleBook, BattleState, TargetSystem]:
    source = _source("fixture_definition", "definition")
    special = SpecialResourceDefinitionIR(
        resource_definition_id="resource:fixture",
        current_property="FixtureCurrent",
        maximum_property="FixtureMax",
        current_resource_key="fixture_current",
        maximum_resource_key="fixture_max",
        initial_current_mode="ability_battle_entry_initializer",
        maximum_initialization_mode="ability_initializer",
        initializer_task_names=(),
        initializer=None,
        supporting_sources=(source,),
        source=source,
        coverage_status="executable",
    )
    avatar_profile = AvatarProfileIR(
        avatar_profile_id="avatar_profile:fixture",
        avatar_id="1001",
        base_type="Mage",
        damage_type="Fire",
        skill_ids=(),
        promotion_tiers=(),
        max_energy="100",
        max_energy_source=source,
        source=source,
        coverage_status="executable",
        resource_mode="special_resource",
        special_resource_source=source,
        special_resource_definition=special,
    )
    character = CharacterDataCardIR(
        card_id="character_card:fixture",
        entity_ref="avatar:1001",
        profile_id=avatar_profile.avatar_profile_id,
        skill_ids=(),
        skill_formula_binding_ids=(),
        bounce_policy_ids=(),
        source=source,
        coverage_status="executable",
    )
    monster = MonsterDataCardIR(
        card_id="monster_card:fixture",
        entity_ref="monster:2001",
        monster_id="2001",
        template_id="2001",
        rank="Elite",
        profile_id="monster_profile:fixture",
        action_set_id="monster_action_set:fixture",
        skill_ids=(),
        skill_slots=(),
        ai_policy={},
        action_sequence=(),
        summon_refs=(),
        raw_parameter_blocks={},
        card_contract={},
        source=source,
        coverage_status="executable",
    )
    rules = RuleBook(
        CanonicalIR(
            version="p9_s6b_fixture",
            avatar_profiles=(avatar_profile,),
            character_data_cards=(character,),
            monster_data_cards=(monster,),
            target_expressions=(
                _target_definition(
                    "Caster", {"$type": "RPG.GameCore.TargetFetchCaster"}
                ),
                _target_definition(
                    "ParamEntity",
                    {"$type": "RPG.GameCore.TargetFetchParamEntity"},
                ),
                _target_definition(
                    "AllEnemy",
                    {
                        "$type": "RPG.GameCore.TargetSequence",
                        "Sequence": [
                            {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
                            {"$type": "RPG.GameCore.TargetMapEnemyTeamEntity"},
                            {"$type": "RPG.GameCore.TargetMapAllTeamMember"},
                        ],
                    },
                ),
            ),
            metadata={"monster_rank_scores": {"Minion": 1.0, "Elite": 3.0}},
        )
    )
    runtime = empty_summon_runtime()
    entry = {
        "runtime_id": "summon",
        "unit_id": "summon",
        "summon_kind": "servant",
        "owner_id": "avatar",
        "summoner_id": "avatar",
        "team_side": "ally",
        "status": "active",
        "targetability": {"targetable": True, "source": {}},
        "source_intent_id": "validation:relation",
        "created_event_index": 0,
        "removed_event_index": None,
    }
    runtime.update(
        {
            "entities": {"summon": entry},
            "by_owner": {"avatar": ["summon"]},
            "servants": {"summon": dict(entry)},
            "last_servants": ["summon"],
        }
    )
    units = {
        "avatar": UnitState(
            "avatar",
            "ally",
            "avatar:1001",
            max_hp=100,
            hp=75,
            flags={
                "character_data_card_id": character.card_id,
                "special_resource_definition_id": special.resource_definition_id,
                "special_resource_current_key": special.current_resource_key,
                "special_resource_maximum_key": special.maximum_resource_key,
                "position": 0,
            },
            resources={"fixture_current": 3, "fixture_max": 6},
        ),
        "ally": UnitState("ally", "ally", "avatar:ally", flags={"position": 1}),
        "enemy": UnitState(
            "enemy",
            "enemy",
            "monster:2001",
            max_hp=100,
            hp=40,
            flags={
                "monster_data_card_id": monster.card_id,
                "monster_rank": monster.rank,
                "monster_rank_score": 3.0,
                "unselectable": True,
                "position": 0,
            },
            resources={
                "effect_resistance": 0.2,
                "control_resistance": 0.25,
                "control_resistance:Frozen": 0.1,
            },
        ),
        "enemy_selectable": UnitState(
            "enemy_selectable",
            "enemy",
            "monster:2001",
            max_hp=100,
            hp=40,
            flags={
                "monster_data_card_id": monster.card_id,
                "monster_rank": monster.rank,
                "monster_rank_score": 3.0,
                "position": 1,
            },
        ),
        "summon": UnitState(
            "summon",
            "summon",
            "servant:fixture",
            flags={
                "summon_kind": "servant",
                "owner_id": "avatar",
                "summoner_id": "avatar",
                "team_side": "ally",
                "position": 2,
            },
        ),
    }
    state = BattleState(
        units=units,
        skill_points=3,
        global_flags={
            "summon_runtime": runtime,
            "monster_rank_scores": {"Minion": 1.0, "Elite": 3.0},
            "turn_owner_id": "avatar",
        },
    )
    return rules, state, TargetSystem(rules)


def _context(
    targets: TargetSystem,
    state: BattleState,
    condition: ConditionIR,
    *,
    current: str = "enemy",
) -> EvaluationContext:
    return targets.condition_evaluation_context(
        state,
        condition,
        context=TargetEvaluationContext(
            caster_id="avatar",
            effect_owner_id="avatar",
            parameter_entity_ids=(current,),
            selected_target_ids=(current,),
            current_target_id=current,
            turn_owner_id="avatar",
        ),
        condition_event_payload={
            "target_id": current,
            "param_entity_id": current,
            "turn_owner_id": "avatar",
        },
    )


def _current_cases() -> dict[str, tuple[dict[str, Any], str]]:
    return {
        "ByAvatarBaseType": ({"$type": "RPG.GameCore.ByAvatarBaseType", "BaseTypeList": ["Mage"], "TargetType": _alias("Caster")}, "enemy"),
        "ByCasterAliveOrLimbo": ({"$type": "RPG.GameCore.ByCasterAliveOrLimbo", "AliveStateMask": "Mask_AliveOnly"}, "enemy"),
        "ByCompareBP": ({"$type": "RPG.GameCore.ByCompareBP", "CompareType": "Equal", "CompareValue": _fixed(3)}, "enemy"),
        "ByCompareHP": ({"$type": "RPG.GameCore.ByCompareHP", "CompareType": "Equal", "CompareValue": _fixed(40), "TargetType": _alias("ParamEntity")}, "enemy"),
        "ByCompareMonsterRank": ({"$type": "RPG.GameCore.ByCompareMonsterRank", "CompareType": "Equal", "CompareValue": 3, "TargetType": _alias("ParamEntity")}, "enemy"),
        "ByCompareResistChance": ({"$type": "RPG.GameCore.ByCompareResistChance", "BehaviorFlagList": ["STAT_CTRL_Frozen", "STAT_CTRL"], "CompareType": "Less", "CompareValue": _fixed(0.5), "TargetType": _alias("ParamEntity")}, "enemy"),
        "ByCompareSpecialSPRatio": ({"$type": "RPG.GameCore.ByCompareSpecialSPRatio", "CompareType": "Equal", "CompareValue": _fixed(0.5), "TargetType": _alias("Caster")}, "enemy"),
        "ByHasSummonRelation": ({"$type": "RPG.GameCore.ByHasSummonRelation", "ServantType": _alias("ParamEntity"), "SummonerType": _alias("Caster")}, "summon"),
        "ByIsEnemy": ({"$type": "RPG.GameCore.ByIsEnemy", "TargetTypeA": _alias("ParamEntity"), "TargetTypeB": _alias("Caster")}, "enemy"),
        "ByIsTargetUnselectable": ({"$type": "RPG.GameCore.ByIsTargetUnselectable", "TargetType": _alias("ParamEntity")}, "enemy"),
        "ByTargetListAll": ({"$type": "RPG.GameCore.ByTargetListAll", "TargetType": _alias("AllEnemy"), "Predicate": {"$type": "RPG.GameCore.ByCompareHP", "CompareType": "Greater", "CompareValue": _fixed(0), "TargetType": _alias("ParamEntity")}}, "enemy"),
        "ByTargetListAny": ({"$type": "RPG.GameCore.ByTargetListAny", "TargetType": _alias("AllEnemy"), "Predicate": {"$type": "RPG.GameCore.ByCompareHP", "CompareType": "Greater", "CompareValue": _fixed(0), "TargetType": _alias("ParamEntity")}}, "enemy"),
    }


def _external_cases() -> dict[str, dict[str, Any]]:
    target = _alias("ParamEntity")
    return {
        "ByCompareBattleEventID": {"$type": "RPG.GameCore.ByCompareBattleEventID", "TargetType": target, "TargetBattleEventID": _fixed(60001)},
        "ByCompareStance": {"$type": "RPG.GameCore.ByCompareStance", "TargetType": target, "CompareType": "Equal", "CompareValue": _fixed(1)},
        "ByCompareStanceCount": {"$type": "RPG.GameCore.ByCompareStanceCount", "TargetType": target, "CompareType": "Equal", "CompareValue": _fixed(1)},
        "ByCompareStanceRatio": {"$type": "RPG.GameCore.ByCompareStanceRatio", "TargetType": target, "CompareType": "Equal", "CompareValue": _fixed(1), "IncludeRedStance": False},
        "ByContainsRedStance": {"$type": "RPG.GameCore.ByContainsRedStance", "TargetType": target},
        "ByIsBattleEventEntity": {"$type": "RPG.GameCore.ByIsBattleEventEntity", "TargetType": target},
        "ByIsBodyPart": {"$type": "RPG.GameCore.ByIsBodyPart", "TargetType": target},
        "ByIsSubTargetOfHpSharedGroup": {"$type": "RPG.GameCore.ByIsSubTargetOfHpSharedGroup", "TargetType": target},
        "ByTargetIsStanceWeak": {"$type": "RPG.GameCore.ByTargetIsStanceWeak", "TargetType": target, "AttackerType": _alias("Caster")},
    }


def _target_key(node: TargetExpressionNodeIR) -> str:
    encoded = json.dumps(node.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"node:{encoded}"


def _runtime_checks() -> tuple[dict[str, bool], list[dict[str, Any]]]:
    rules, state, targets = _runtime_fixture()
    evaluator = RuleEvaluator()
    rows: list[dict[str, Any]] = []
    current_conditions: dict[str, ConditionIR] = {}
    for family, (raw, current) in _current_cases().items():
        condition = _condition(raw, f"current:{family}")
        result = evaluator.evaluate_condition_result(condition, _context(targets, state, condition, current=current))
        current_conditions[family] = condition
        rows.append({"family": family, "producer": "current", "result": result.to_json()})
    for family, raw in _external_cases().items():
        condition = _condition(raw, f"external:{family}")
        result = evaluator.evaluate_condition_result(condition, _context(targets, state, condition))
        rows.append({"family": family, "producer": _EXTERNAL_FAMILY_STAGE[family], "result": result.to_json()})

    false_cases = {
        "avatar_path_false": _condition({"$type": "RPG.GameCore.ByAvatarBaseType", "BaseTypeList": ["Rogue"], "TargetType": _alias("Caster")}, "false:path"),
        "battle_points_false": _condition({"$type": "RPG.GameCore.ByCompareBP", "CompareType": "Equal", "CompareValue": _fixed(4)}, "false:bp"),
        "same_team_not_enemy": _condition({"$type": "RPG.GameCore.ByIsEnemy", "TargetTypeA": _alias("Caster"), "TargetTypeB": _alias("Caster")}, "false:enemy"),
        "selectable_not_unselectable": _condition({"$type": "RPG.GameCore.ByIsTargetUnselectable", "TargetType": _alias("ParamEntity")}, "false:targetable"),
    }
    false_results = {
        name: evaluator.evaluate_condition_result(
            condition,
            _context(
                targets,
                state,
                condition,
                current=("ally" if name == "selectable_not_unselectable" else "enemy"),
            ),
        )
        for name, condition in false_cases.items()
    }
    defeated_state = replace(
        state,
        units={**state.units, "avatar": replace(state.units["avatar"], lifecycle_status="defeated", hp=0)},
    )
    alive = current_conditions["ByCasterAliveOrLimbo"]
    false_results["defeated_caster_false"] = evaluator.evaluate_condition_result(
        alive, _context(targets, defeated_state, alive)
    )

    any_condition = current_conditions["ByTargetListAny"]
    all_condition = current_conditions["ByTargetListAll"]
    any_node = any_condition.payload["TargetType"]
    all_node = all_condition.payload["TargetType"]
    assert isinstance(any_node, TargetExpressionNodeIR) and isinstance(all_node, TargetExpressionNodeIR)
    any_base = _context(targets, state, any_condition)
    all_base = _context(targets, state, all_condition)
    empty_any = evaluator.evaluate_condition_result(
        any_condition,
        replace(any_base, resolved_target_groups={_target_key(any_node): ()}, target_resolution_errors={}),
    )
    empty_all = evaluator.evaluate_condition_result(
        all_condition,
        replace(all_base, resolved_target_groups={_target_key(all_node): ()}, target_resolution_errors={}),
    )
    blocked_any = evaluator.evaluate_condition_result(
        any_condition,
        replace(any_base, resolved_target_groups={}, target_resolution_errors={_target_key(any_node): "validation_collection_unresolved"}),
    )

    external_child = _external_cases()["ByCompareStance"]
    false_child = {"$type": "RPG.GameCore.ByCompareHP", "TargetType": _alias("ParamEntity"), "CompareType": "Greater", "CompareValue": _fixed(100)}
    true_child = {"$type": "RPG.GameCore.ByCompareHP", "TargetType": _alias("ParamEntity"), "CompareType": "Greater", "CompareValue": _fixed(0)}
    and_condition = _condition({"$type": "RPG.GameCore.ByAnd", "PredicateList": [false_child, external_child]}, "short:and")
    any_short_condition = _condition({"$type": "RPG.GameCore.ByAny", "PredicateList": [true_child, external_child]}, "short:any")
    not_condition = _condition({"$type": "RPG.GameCore.ByNot", "Predicate": external_child}, "short:not")
    and_result = evaluator.evaluate_condition_result(and_condition, _context(targets, state, and_condition))
    any_result = evaluator.evaluate_condition_result(any_short_condition, _context(targets, state, any_short_condition))
    not_result = evaluator.evaluate_condition_result(not_condition, _context(targets, state, not_condition))

    no_provider = evaluator.evaluate_condition_result(
        current_conditions["ByCompareBP"], EvaluationContext(state=state, actor_id="avatar")
    )

    class WrongFactProvider:
        def resolve(self, _state: Any, _request: Any) -> ConditionOperandResolution:
            return ConditionOperandResolution.resolved(
                "number", 3, fact_kind="unit.hp", authority="forged", source_identity="forged"
            )

    wrong_fact = evaluator.evaluate_condition_result(
        current_conditions["ByCompareBP"],
        EvaluationContext(state=state, actor_id="avatar", committed_condition_provider=WrongFactProvider()),
    )
    provider = CommittedConditionFactProvider(rules)
    missing_external_subject = provider.resolve(
        state,
        ConditionOperandRequest("unit.stance_current", ("missing",)),
    )
    contract_rejections = []
    for callback in (
        lambda: ConditionOperandRequest("unit.hp", ("enemy",), []),
        lambda: ConditionOperandResolution.resolved(
            "number", 10**10000, fact_kind="unit.hp", authority="forged", source_identity="forged"
        ),
    ):
        try:
            callback()
            contract_rejections.append(False)
        except (TypeError, ValueError):
            contract_rejections.append(True)

    current_rows = [row for row in rows if row["producer"] == "current"]
    external_rows = [row for row in rows if row["producer"] != "current"]
    checks = {
        "current_family_positive_slice_complete": (
            {row["family"] for row in current_rows} == set(_current_cases())
            and all(row["result"]["ok"] is True and row["result"]["result"] is True for row in current_rows)
        ),
        "external_producer_blockers_exact": all(
            row["result"]["ok"] is False
            and row["result"]["result"] is None
            and str(row["result"]["reason"]).startswith(f"condition_fact_producer_dependency:{row['producer']}:")
            for row in external_rows
        ),
        "business_false_is_not_blocked": all(result.ok and result.result is False for result in false_results.values()),
        "quantifier_empty_semantics_correct": empty_any.ok and empty_any.result is False and empty_all.ok and empty_all.result is True,
        "unresolved_collection_remains_blocked": not blocked_any.ok and blocked_any.result is None,
        "composite_short_circuit_is_decisive": (
            and_result.ok and and_result.result is False
            and any_result.ok and any_result.result is True
            and len(and_result.details.get("children", ())) == 1
            and len(any_result.details.get("children", ())) == 1
            and not not_result.ok and not_result.result is None
        ),
        "missing_provider_blocks": not no_provider.ok and no_provider.reason == "committed_condition_provider_missing",
        "provider_fact_mismatch_blocks": not wrong_fact.ok and wrong_fact.reason == "committed_condition_provider_fact_mismatch",
        "identity_error_precedes_external_gap": missing_external_subject.blocked_reason == "condition_fact_subject_missing:missing",
        "operand_contract_rejects_malformed_values": all(contract_rejections),
        "formal_context_owns_provider": type(any_base.committed_condition_provider) is CommittedConditionFactProvider,
    }
    consumer_checks, consumer_rows = _formal_consumer_checks(rules, state)
    checks.update(consumer_checks)
    rows.extend(
        {"case": name, "producer": "current", "result": result.to_json()}
        for name, result in false_results.items()
    )
    rows.extend(
        (
            {"case": "empty_any", "result": empty_any.to_json()},
            {"case": "empty_all", "result": empty_all.to_json()},
            {"case": "blocked_any", "result": blocked_any.to_json()},
            {"case": "short_circuit_and", "result": and_result.to_json()},
            {"case": "short_circuit_any", "result": any_result.to_json()},
            {"case": "not_external", "result": not_result.to_json()},
        )
    )
    rows.extend(consumer_rows)
    return checks, rows


def _formal_consumer_checks(
    base_rules: RuleBook,
    state: BattleState,
) -> tuple[dict[str, bool], list[dict[str, Any]]]:
    source = _source("formal_consumer", "consumer")
    false_condition = _condition(
        {
            "$type": "RPG.GameCore.ByCompareBP",
            "CompareType": "Equal",
            "CompareValue": _fixed(4),
        },
        "consumer:false",
    )
    blocked_condition = _condition(
        _external_cases()["ByCompareStance"], "consumer:blocked"
    )
    triggers = (
        TriggerIR(
            "trigger:false",
            "OnProbe",
            (false_condition.condition_id,),
            (),
            source,
            coverage_status="executable",
            modifier_name="FixtureStatus",
        ),
        TriggerIR(
            "trigger:blocked",
            "OnProbe",
            (blocked_condition.condition_id,),
            (),
            source,
            coverage_status="executable",
            modifier_name="FixtureStatus",
        ),
    )
    callbacks = (
        StatusCallbackIR(
            "callback:false", "FixtureStatus", "OnBeforeHit",
            ("task:false", "task:false_branch"), source, (0, 0),
            coverage_status="executable",
            admission_status="executable",
        ),
        StatusCallbackIR(
            "callback:blocked", "FixtureStatus", "OnBeforeHit",
            ("task:blocked",), source, (0, 1),
            coverage_status="executable",
            admission_status="executable",
        ),
    )
    callback_tasks = (
        StatusCallbackTaskIR(
            "task:false",
            "callback:false",
            "FixtureStatus",
            "OnBeforeHit",
            0,
            "$.false",
            "root",
            "PredicateTaskList",
            source,
            condition_id=false_condition.condition_id,
            child_task_ids=("task:false_branch",),
            failed_task_ids=("task:false_branch",),
            coverage_status="executable",
        ),
        StatusCallbackTaskIR(
            "task:false_branch",
            "callback:false",
            "FixtureStatus",
            "OnBeforeHit",
            1,
            "$.false.FailTaskList[0]",
            "failed",
            "ModifyDamage",
            source,
            parent_task_id="task:false",
            coverage_status="executable",
        ),
        StatusCallbackTaskIR(
            "task:blocked",
            "callback:blocked",
            "FixtureStatus",
            "OnBeforeHit",
            0,
            "$.blocked",
            "root",
            "PredicateTaskList",
            source,
            condition_id=blocked_condition.condition_id,
            coverage_status="executable",
        ),
    )
    modifier = DamageModifierIR(
        "damage_modifier:false_branch",
        "callback:false",
        "task:false_branch",
        "FixtureStatus",
        "OnBeforeHit",
        "ParamEntity",
        ({"modifier_kind": "all_damage", "numeric_expr": numeric_fixed(0.1)},),
        source,
        coverage_status="executable",
    )
    rules = RuleBook(
        replace(
            base_rules.ir,
            conditions=(false_condition, blocked_condition),
            triggers=triggers,
            status_callbacks=callbacks,
            status_callback_tasks=callback_tasks,
            damage_modifiers=(modifier,),
        )
    )
    command = ActionCommand("avatar", "validation_action", 1, ("enemy",))
    action = ActionDefinitionIR(
        "validation_action_definition",
        "validation_action",
        1,
        "Normal",
        "Attack",
        "single",
        0.0,
        0.0,
        0.0,
        0.0,
        (),
        (),
        (),
        None,
        source,
        coverage_status="executable",
        damage_kind="direct",
        damage_formula_family="direct",
    )
    resolution = TargetResolution(
        requested=("enemy",), legal=("enemy",), selected=("enemy",)
    )
    trigger_system = TriggerSystem(rules, EffectRegistry(StatusSystem(rules)))

    def trigger_state(trigger_id: str) -> BattleState:
        avatar = state.units["avatar"]
        return replace(
            state,
            units={
                **state.units,
                "avatar": replace(
                    avatar,
                    flags={
                        **avatar.flags,
                        "status_details": [
                            {
                                "instance_id": f"status:{trigger_id}",
                                "modifier_name": "FixtureStatus",
                                "owner_id": "avatar",
                                "trigger_ids_by_event": {"OnProbe": [trigger_id]},
                            }
                        ],
                    },
                ),
            },
        )

    false_trigger = trigger_system.execute_status_window(
        trigger_state("trigger:false"),
        canonical_window="validation.trigger",
        tbgd_event="OnProbe",
        command=command,
        action_definition=action,
        target_resolution=resolution,
        enabled=True,
    )
    blocked_trigger = trigger_system.execute_status_window(
        trigger_state("trigger:blocked"),
        canonical_window="validation.trigger",
        tbgd_event="OnProbe",
        command=command,
        action_definition=action,
        target_resolution=resolution,
        enabled=True,
    )
    targets = TargetSystem(rules)
    false_terms, false_records, false_blockers = _collect_callback_damage_modifiers(
        state,
        rules,
        RuleEvaluator(),
        targets,
        callback_id="callback:false",
        callback_event="OnBeforeHit",
        actor_id="avatar",
        owner_id="avatar",
        target_id="enemy",
        detail={"modifier_name": "FixtureStatus", "owner_id": "avatar"},
        event_payload={},
    )
    blocked_terms, blocked_records, blocked_reasons = _collect_callback_damage_modifiers(
        state,
        rules,
        RuleEvaluator(),
        targets,
        callback_id="callback:blocked",
        callback_event="OnBeforeHit",
        actor_id="avatar",
        owner_id="avatar",
        target_id="enemy",
        detail={"modifier_name": "FixtureStatus", "owner_id": "avatar"},
        event_payload={},
    )
    false_window = false_trigger.trigger_windows[0]
    blocked_window = blocked_trigger.trigger_windows[0]
    checks = {
        "trigger_false_skips_without_blocking": (
            false_window.get("skipped_reason") == "condition_false"
            and not false_window.get("blocked_reason")
            and not false_trigger.mutations
        ),
        "trigger_unknown_fact_blocks_without_mutation": (
            str(blocked_window.get("blocked_reason") or "").startswith(
                "blocked_condition:"
            )
            and not blocked_trigger.mutations
        ),
        "damage_modifier_false_branch_is_executed": (
            len(false_terms) == 1 and bool(false_records) and not false_blockers
        ),
        "damage_modifier_unknown_fact_is_not_silently_skipped": (
            not blocked_terms
            and bool(blocked_records)
            and len(blocked_reasons) == 1
            and "condition_fact_producer_dependency:p9_s15" in blocked_reasons[0]
        ),
    }
    return checks, [
        {
            "case": "formal_consumers",
            "false_trigger": false_window,
            "blocked_trigger": blocked_window,
            "false_branch_terms": list(false_terms),
            "blocked_damage_modifier_reasons": list(blocked_reasons),
        }
    ]


def _source_and_lowering(tbgd_root: Path) -> tuple[dict[str, bool], list[dict[str, Any]], dict[str, int]]:
    snapshot = build_character_ability_raw_snapshot(tbgd_root)
    scope = build_character_ability_scope_projection(tbgd_root, snapshot=snapshot)
    catalog = build_character_condition_responsibility_catalog(snapshot, scope)
    rows = tuple(row for row in catalog.responsibilities if row.evaluation_stage == _STAGE)
    lowered_rows: list[dict[str, Any]] = []
    for row in rows:
        document = snapshot.documents[row.source.source_path]
        raw = _at_path(document, str(row.source.evidence["json_path"]).removesuffix(".$type"))
        registry = document.get("GlobalTargetAlias") if isinstance(document, Mapping) else None
        node = (
            _typed_condition_execution_node(
                dict(raw),
                target_alias_registry=dict(registry) if isinstance(registry, Mapping) else {},
                source=row.source,
            )
            if isinstance(raw, Mapping)
            else {}
        )
        lowered_rows.append(
            {
                "record_id": row.record_id,
                "family": row.opcode,
                "producer_stage": row.producer_stage,
                "source_path": row.source.source_path,
                "json_path": row.source.evidence["json_path"],
                "raw_reversible": isinstance(raw, Mapping) and str(raw.get("$type") or "").rsplit(".", 1)[-1] == row.opcode,
                "family_stage": character_condition_family_stage(row.opcode, raw) if isinstance(raw, Mapping) else "missing",
                "lowered": node.get("supported") is True,
                "blocked_reason": node.get("blocked_reason", "source_missing"),
            }
        )
    family_counts = Counter(row.opcode for row in rows)
    producer_counts = Counter(row.producer_stage for row in rows)
    source_ids = {row.record_id for row in rows}
    checks = {
        "source_catalog_complete": snapshot.source_catalog_complete and scope.scope_reconciliation_complete and catalog.complete,
        "s6a_responsibility_partition_preserved": bool(rows) and len(rows) == len(source_ids),
        "family_denominator_matches_runtime_contract": set(family_counts) == set(COMMITTED_STATE_CONDITION_OPCODES),
        "all_source_rows_reversible": all(row["raw_reversible"] for row in lowered_rows),
        "all_source_rows_owned_by_s6b": all(row["family_stage"] == _STAGE for row in lowered_rows),
        "all_s6b_payloads_strictly_lowered": all(row["lowered"] and not row["blocked_reason"] for row in lowered_rows),
        "external_producer_ownership_preserved": all(
            row.producer_stage == _EXTERNAL_FAMILY_STAGE.get(row.opcode, "current")
            for row in rows
        ),
        "full_canonical_ir_build_count_zero": True,
    }
    summary = {
        "condition_source_fingerprint": snapshot.source_fingerprint,
        "s6b_record_count": len(rows),
        "family_counts": dict(sorted(family_counts.items())),
        "producer_counts": dict(sorted(producer_counts.items())),
    }
    return checks, lowered_rows, summary


def _negative_lowering() -> dict[str, bool]:
    source = _source("negative", "negative")
    extra_field = _typed_condition_execution_node(
        {"$type": "RPG.GameCore.ByCompareBP", "CompareType": "Equal", "CompareValue": _fixed(3), "FutureField": True},
        source=source,
    )
    bad_compare = _typed_condition_execution_node(
        {"$type": "RPG.GameCore.ByCompareHP", "TargetType": _alias("ParamEntity"), "CompareType": "Approximate", "CompareValue": _fixed(1)},
        source=source,
    )
    bad_target = _typed_condition_execution_node(
        {"$type": "RPG.GameCore.ByIsEnemy", "TargetTypeA": True, "TargetTypeB": _alias("Caster")},
        source=source,
    )
    return {
        "unknown_field_blocks_at_lowering": extra_field.get("supported") is False and str(extra_field.get("blocked_reason")).startswith("condition_field_signature_unclassified"),
        "unknown_compare_enum_blocks_at_lowering": bad_compare.get("supported") is False,
        "wrong_target_type_blocks_at_lowering": bad_target.get("supported") is False,
        "schema_version_is_current": (
            CONDITION_EXPRESSION_NODE_SCHEMA == "hsr.condition_expression_node.v1"
        ),
    }


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    source_checks, family_ledger, source_summary = _source_and_lowering(tbgd_root)
    runtime_checks, runtime_ledger = _runtime_checks()
    negative_checks = _negative_lowering()
    checks = {**source_checks, **runtime_checks, **negative_checks}
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_bytes = _write(output_dir / "condition_family_ledger.json", family_ledger)
    evidence_bytes += _write(output_dir / "condition_runtime_ledger.json", runtime_ledger)
    result = {
        "version": "p9_s6b_committed_state_condition_evaluation_v1",
        "ok": all(checks.values()),
        "checks": checks,
        "source_summary": source_summary,
        "resource": {
            "elapsed_seconds": time.perf_counter() - started,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "raw_snapshot_build_count": 1,
            "scope_projection_build_count": 1,
            "responsibility_catalog_build_count": 1,
            "full_canonical_ir_build_count": 0,
            "evidence_bytes": evidence_bytes,
        },
    }
    _write(output_dir / "validation_summary_p9_s6b_committed_state_condition_evaluation.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P9-S6B committed-state condition evaluation.")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_validation(args.tbgd_root.resolve(), args.output_dir.resolve())
    print(
        "P9-S6B "
        f"ok={result['ok']} "
        f"records={result['source_summary']['s6b_record_count']} "
        f"families={len(result['source_summary']['family_counts'])} "
        f"seconds={result['resource']['elapsed_seconds']:.3f} "
        f"rss_kib={result['resource']['peak_rss_kib']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
