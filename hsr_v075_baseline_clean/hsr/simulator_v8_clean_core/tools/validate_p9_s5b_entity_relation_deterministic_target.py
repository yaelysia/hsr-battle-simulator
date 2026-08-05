from __future__ import annotations

import argparse
import ast
import copy
import json
import resource
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from ..core.model import BattleState, UnitState
from ..core.state_integrity import CommittedStateIntegrityGate
from ..immutable_json import thaw_json
from ..ir_types import IRSource
from ..rules.ir import TargetExpressionIR, TargetExpressionNodeIR
from ..systems.summon_runtime import empty_summon_runtime, validate_summon_runtime
from ..systems.target import TargetExpressionResult, TargetSystem
from ..systems.unit_relation import EntityRelationResolver, TargetEvaluationContext, committed_turn_owner_id
from ..tbgd.character_ability_scope import (
    AVATAR_CONFIG_TABLES,
    AVATAR_ENHANCED_CONFIG_TABLE,
    _CharacterAbilityInventoryManifest,
    build_character_ability_raw_snapshot,
)
from ..tbgd.lowering import TBGDLowering, _lower_summon_monster_intents, _lower_unit_birth_templates
from ..tbgd.monster_cards import build_monster_card_ir
from ..tbgd.target_source import build_target_source_projection, close_target_expression_language


ROOT = Path(__file__).resolve().parents[4]
CORE = Path(__file__).resolve().parents[1]
TBGD = ROOT / "turnbasedgamedata-main"

S5B_KINDS = {
    "TargetAlias", "TargetConcat", "TargetSequence", "TargetFilter", "Retarget", "TargetQuery", "TargetFetchCaster", "TargetFetchModifierOwner", "TargetFetchOwner", "TargetFetchAbilityTarget", "TargetFetchCurrentActionTarget", "TargetFetchParamEntity", "TargetFetchParamEntityList", "TargetFetchActualOwner", "TargetFetchPartner", "TargetFetchUniqueNameEntity", "TargetFetchTeamEntity", "TargetFetchBattleEventEntityList", "TargetFetchTurnOwnerEntity", "TargetFetchNone", "TargetMapAdjoinEntity", "TargetMapSummoner", "TargetMapSummonedMinions", "TargetMapAllTeamMember", "TargetMapEnemyTeamEntity", "TargetRemoveUnselectable", "TargetReverse", "TargetTake", "TargetIndex", "TargetSortByProperty", "TargetSortByPropertyRatio", "TargetSortByFormation", "TargetFilterAliveState", "TargetFilterUnselectable", "TargetFilterEntityType", "TargetFetchAllUnselectable", "TargetFetchAllCustomUnselectable", "TargetMapCreator", "TargetMapAllTeamMemberFromFirstEntity", "TargetSortMonsterRank", "TargetSortByModifierValue", "TargetSortByModifierStatusCount", "TargetSortByActionOrder", "TargetCompute", "TargetSelector",
}
PRODUCTION_CALLERS = ("systems/ability.py", "systems/effect.py", "systems/status.py", "systems/status_callbacks.py")


class _Rules:
    def __init__(self, expressions: Iterable[TargetExpressionIR]) -> None:
        self._expressions = tuple(expressions)

    def target_expressions(self) -> tuple[TargetExpressionIR, ...]:
        return self._expressions


def _write(path: Path, value: Any) -> int:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(encoded); return len(encoded)


def _walk_nodes(node: TargetExpressionNodeIR | None) -> tuple[TargetExpressionNodeIR, ...]:
    if node is None:
        return ()
    nodes = [node]
    nodes.extend(child for item in node.children for child in _walk_nodes(item))
    for item in (node.candidate, node.target, node.query_target, node.query_compare):
        nodes.extend(_walk_nodes(item))
    if node.predicate is not None:
        for value in node.predicate.payload.values():
            nodes.extend(_walk_payload_nodes(value))
    return tuple(nodes)


def _walk_payload_nodes(value: object) -> tuple[TargetExpressionNodeIR, ...]:
    if type(value) is TargetExpressionNodeIR:
        return _walk_nodes(value)
    if isinstance(value, dict):
        return tuple(node for child in value.values() for node in _walk_payload_nodes(child))
    if isinstance(value, (list, tuple)):
        return tuple(node for child in value for node in _walk_payload_nodes(child))
    return ()


def _inventory_paths() -> tuple[str, ...]:
    inventory = {
        relative: (TBGD / relative).read_bytes()
        for relative in (*AVATAR_CONFIG_TABLES, AVATAR_ENHANCED_CONFIG_TABLE)
    }
    manifest = _CharacterAbilityInventoryManifest(inventory)
    return tuple(sorted(candidate.relative_path for candidate in manifest.candidates))


def _runtime() -> dict[str, Any]:
    runtime = empty_summon_runtime()
    entry = {
        "runtime_id": "summon",
        "unit_id": "summon",
        "summon_kind": "servant",
        "owner_id": "owner",
        "summoner_id": "owner",
        "team_side": "ally",
        "status": "active",
        "targetability": {"targetable": True, "source": {}},
        "source_intent_id": "relation_contract",
        "created_event_index": 0,
        "removed_event_index": None,
    }
    runtime["entities"] = {"summon": entry}
    runtime["by_owner"] = {"owner": ["summon"]}
    runtime["servants"] = {"summon": dict(entry)}
    runtime["last_servants"] = ["summon"]
    return runtime


def _state(runtime: dict[str, Any] | None = None) -> BattleState:
    lifecycle_source = {
        "admission_status": "executable",
        "presence": "field",
        "targetable": True,
        "actionable": True,
        "timeline_admitted": True,
    }
    units = {
        "owner": UnitState("owner", "ally", "avatar:owner", flags={"position": 0}),
        "ally": UnitState("ally", "ally", "avatar:ally", flags={"position": 2}),
        "enemy": UnitState("enemy", "enemy", "monster:enemy", flags={"position": 0, "monster_rank_score": 1.5}),
        "summon": UnitState(
            "summon",
            "summon",
            "servant:runtime",
            flags={
                "position": 1,
                "summon_kind": "servant",
                "owner_id": "owner",
                "summoner_id": "owner",
                "team_side": "ally",
                "lifecycle_source": lifecycle_source,
                "timeline_admitted": True,
            },
        ),
    }
    return BattleState(units=units, global_flags={"summon_runtime": runtime if runtime is not None else _runtime(), "monster_rank_scores": {"Minion": 0.5, "Elite": 1.5}})


def _result_ok(result: TargetExpressionResult, expected: tuple[str, ...]) -> bool:
    return result.resolved and result.target_ids == expected and not result.rng_events


def _summoned_monster_rank_probe() -> dict[str, Any]:
    lowering = TBGDLowering(TBGD)
    sources = tuple(path for path in lowering._ability_files() if b'"$type": "RPG.GameCore.SummonMonster"' in path.read_bytes())
    profiles, cards = lowering._lower_combatant_profiles(), list(build_monster_card_ir(TBGD, max_records_per_table=None).monster_data_cards)
    timeline, scores = lowering._lower_timeline_rules(), lowering._monster_rank_scores()
    counts, representative = Counter(source_count=len(sources), template_count=0, executable_count=0, ranked_executable_count=0), {}
    for path in sources:
        _, _, tasks, effects, _, _, _ = lowering._lower_standalone_ability_graphs([path])
        intents = _lower_summon_monster_intents(ability_tasks=tasks, effects=effects, combatant_profiles=profiles, monster_data_cards=cards)
        templates = _lower_unit_birth_templates(summon_monster_intents=intents, servant_definitions=[], wave_definitions=[], combatant_profiles=profiles, monster_data_cards=cards, timeline_rules=timeline, monster_rank_scores=scores)
        counts["template_count"] += len(templates)
        for template in templates:
            if template.coverage_status == "executable":
                counts["executable_count"] += 1
            if template.coverage_status == "executable" and template.flag_specs.get("monster_rank") and template.flag_specs.get("monster_rank_score") is not None:
                counts["ranked_executable_count"] += 1
                representative = representative or {"source": template.source.to_json(), "rank": template.flag_specs["monster_rank"], "score": template.flag_specs["monster_rank_score"]}
    return {**counts, "representative": representative}


def _alias_probe(alias: str, *, definition_name: str = "") -> TargetExpressionIR:
    source_path, identity = ("Config/GlobalConfig/TargetAliasConfig.json" if definition_name else "Config/Validation/P9S5BTargetProbe.json"), (definition_name or f"probe:{alias}")
    source = IRSource(
        source_path=source_path,
        raw_type="TargetExpression",
        raw_id=identity,
        evidence={
            "json_path": f"$.Probe.{identity}",
            **({"source_raw_id": definition_name} if definition_name else {}),
        },
    )
    node = TargetExpressionNodeIR.build("TargetAlias", source, {"alias": alias})
    return TargetExpressionIR(
        target_expression_id=identity,
        expression_kind="TargetAlias",
        alias=alias,
        source=source,
        node=node,
        coverage_status="executable",
    )


def _ambiguous_definition_result(
    state: BattleState,
    context: TargetEvaluationContext,
) -> TargetExpressionResult:
    name = "validator_collision"

    def expression(kind: str, path: str) -> TargetExpressionIR:
        source = IRSource(
            source_path=path,
            raw_type="TargetExpression",
            raw_id=f"negative:{kind}",
            evidence={"json_path": f"$.Definition.{name}", "source_raw_id": name},
        )
        node = TargetExpressionNodeIR.build(
            "TargetAlias" if kind == "alias" else "TargetReverse",
            source,
            {"alias": name} if kind == "alias" else {},
        )
        return TargetExpressionIR(
            target_expression_id=f"negative:{kind}",
            expression_kind=node.expression_kind,
            alias=node.alias,
            source=source,
            node=node,
            coverage_status="executable",
        )

    alias = expression("alias", "Config/GlobalConfig/TargetAliasConfig.json")
    operation = expression("operation", "Config/GlobalConfig/TargetOperationConfig.json")
    return TargetSystem(_Rules((alias, operation))).resolve_target_expression(
        state, alias, context=context
    )


def _negative_matrix(expressions: tuple[TargetExpressionIR, ...], definitions: tuple[Any, ...]) -> dict[str, Any]:
    state = _state()
    resolver = EntityRelationResolver()
    context = TargetEvaluationContext(
        caster_id="owner",
        effect_owner_id="owner",
        parameter_entity_ids=("enemy",),
        selected_target_ids=("enemy",),
        current_target_id="enemy",
    )
    malformed = copy.deepcopy(_runtime())
    malformed["entities"]["summon"]["owner_id"] = "ally"
    malformed_state = _state(malformed)
    malformed_result = resolver.resolve(
        malformed_state, "summon.owner", context, subject_ids=("summon",)
    )
    duplicate = copy.deepcopy(_runtime())
    duplicate["by_owner"]["owner"] = ["summon", "summon"]
    duplicate_result = resolver.resolve(
        _state(duplicate), "summon.owned", context, subject_ids=("owner",)
    )
    missing_position_state = BattleState(
        units={
            "owner": UnitState("owner", "ally", "avatar:owner"),
            "ally": UnitState("ally", "ally", "avatar:ally", flags={"position": 1}),
        },
        global_flags={"summon_runtime": empty_summon_runtime()},
    )
    unknown = resolver.resolve(state, "team.same", context, subject_ids=("forged",))
    adjacent_missing = resolver.resolve(
        missing_position_state,
        "formation.adjacent",
        TargetEvaluationContext("owner"),
        subject_ids=("owner",),
    )
    payload_probe = next(
        expression
        for expression in expressions
        if expression.source.source_path.endswith("TargetAliasConfig.json")
        and expression.source.evidence.get("source_raw_id") == "ParamEntity"
    )
    payload_result = TargetSystem(_Rules(expressions)).resolve_target_expression(
        state,
        payload_probe,
        context=context,
        condition_event_payload={"param_entity_id": "forged", "event_source_id": "forged"},
    )
    ambiguous_result = _ambiguous_definition_result(state, context)
    cycle = _alias_probe("validator_cycle", definition_name="validator_cycle")
    cycle_result = TargetSystem(_Rules((*expressions, cycle))).resolve_target_expression(
        state, cycle, context=context
    )
    cross_team_result = resolver.resolve(
        state,
        "context.owner",
        TargetEvaluationContext("owner", effect_owner_id="enemy"),
    )
    owner_expression = next(item for item in expressions if item.source.evidence.get("source_raw_id") == "ModifierOwnerEntity")
    cross_team_owner = TargetSystem(_Rules(expressions)).resolve_target_expression(
        state, owner_expression, context=TargetEvaluationContext("owner", effect_owner_id="enemy")
    )
    defeated_state = replace(state, units={
        **state.units, "enemy": replace(state.units["enemy"], hp=0.0, lifecycle_status="defeated"),
    })
    defeated_owner = TargetSystem(_Rules(expressions)).resolve_target_expression(
        defeated_state, owner_expression, context=TargetEvaluationContext("owner", effect_owner_id="enemy")
    )
    forged_state = replace(state, global_flags={**thaw_json(state.global_flags),
        "target_partner_registry": {"owner": "enemy"}, "target_unique_entity_registry": {"forged": "enemy"}})
    producer_results = [
        TargetSystem(_Rules(expressions)).resolve_target_expression(forged_state, item, context=context)
        for item in expressions
        if item.expression_kind in {"TargetFetchPartner", "TargetFetchUniqueNameEntity"}
    ]
    unclosed_alias = close_target_expression_language(_alias_probe("validator_unknown_alias"), definitions)
    node_source = _alias_probe("validator_node").source
    leaf = TargetExpressionNodeIR.build("TargetFetchNone", node_source, {})
    constructor_rejections = {}
    for name, builder in {
        "duplicate_identity": lambda: TargetEvaluationContext("owner", selected_target_ids=("enemy", "enemy")),
        "contradictory_current": lambda: TargetEvaluationContext(
            "owner", selected_target_ids=("enemy",), current_target_id="ally"
        ),
        "empty_caster": lambda: TargetEvaluationContext(""),
        "compute_intersection": lambda: TargetExpressionNodeIR.build("TargetCompute", node_source, {"children": (leaf, leaf), "compute_type": "Intersection"}),
        "selector_branch_count": lambda: TargetExpressionNodeIR.build("TargetSelector", node_source, {"children": (leaf,), "predicate": None}),
        "lifecycle_mask": lambda: TargetExpressionNodeIR.build("TargetFilterAliveState", node_source, {"alive_state_mask": "Forged"}),
        "entity_type_mask": lambda: TargetExpressionNodeIR.build("TargetFilterEntityType", node_source, {"entity_type_mask": "Forged", "inverse": False}),
        "modifier_sort_status": lambda: TargetExpressionNodeIR.build("TargetSortByModifierStatusCount", node_source, {"buff_status": "Forged", "highest_first": False}),
    }.items():
        try:
            builder()
        except (TypeError, ValueError):
            constructor_rejections[name] = True
        else:
            constructor_rejections[name] = False
    return {
        "context_constructor_rejections": constructor_rejections, "unknown_identity": unknown.to_json(),
        "summon_mirror_conflict": malformed_result.to_json(), "summon_duplicate_index": duplicate_result.to_json(),
        "formation_missing": adjacent_missing.to_json(), "freeform_payload_probe": payload_result.to_json(),
        "ambiguous_definition_name": "validator_collision",
        "ambiguous_definition_result": ambiguous_result.to_json(), "alias_cycle_result": cycle_result.to_json(),
        "cross_team_owner": cross_team_result.to_json(), "cross_team_modifier_owner": cross_team_owner.to_json(),
        "defeated_modifier_owner": defeated_owner.to_json(), "forged_partner_or_unique": [item.to_json() for item in producer_results],
        "unclosed_alias": unclosed_alias.to_json(),
        "ok": (
            all(constructor_rejections.values())
            and unknown.blocked and not unknown.target_ids
            and malformed_result.blocked and not malformed_result.target_ids
            and duplicate_result.blocked and not duplicate_result.target_ids
            and adjacent_missing.blocked and not adjacent_missing.target_ids
            and _result_ok(payload_result, ("enemy",))
            and ambiguous_result.blocked
            and cycle_result.blocked
            and _result_ok(cross_team_result, ("enemy",))
            and _result_ok(cross_team_owner, ("enemy",))
            and _result_ok(defeated_owner, ("enemy",))
            and producer_results and all(item.blocked and not item.target_ids for item in producer_results)
            and unclosed_alias.coverage_status == "blocked"
        ),
    }


def _relation_matrix(expressions: tuple[TargetExpressionIR, ...]) -> dict[str, Any]:
    base_state = _state(); state = replace(base_state, global_flags={**thaw_json(base_state.global_flags), "turn_owner_id": "ally"})
    context, resolver = TargetEvaluationContext("owner", effect_owner_id="owner"), EntityRelationResolver()
    runtime_validation = validate_summon_runtime(
        thaw_json(state.global_flags["summon_runtime"]), units=state.units
    )
    owned = resolver.resolve(state, "summon.owned", context, subject_ids=("owner",))
    summoner = resolver.resolve(state, "summon.summoner", context, subject_ids=("summon",))
    mixed_runtime = thaw_json(state.global_flags["summon_runtime"])
    monster_entry = {**mixed_runtime["entities"]["summon"], "runtime_id": "monster_summon", "unit_id": "monster_summon", "summon_kind": "summoned_monster", "owner_id": "enemy", "summoner_id": "enemy", "team_side": "enemy"}
    mixed_runtime["entities"]["monster_summon"] = monster_entry
    mixed_runtime["by_owner"]["enemy"] = ["monster_summon"]
    monster_unit = UnitState("monster_summon", "enemy", "monster:spawned", flags={"position": 1, "summon_kind": "summoned_monster", "owner_id": "enemy", "summoner_id": "enemy", "team_side": "enemy", "lifecycle_source": {"admission_status": "executable", "presence": "field", "targetable": True, "actionable": True, "timeline_admitted": True}})
    mixed_state = replace(state, units={**state.units, "monster_summon": monster_unit, "enemy_far": UnitState("enemy_far", "enemy", "monster:far", flags={"position": 2})}, global_flags={**thaw_json(state.global_flags), "summon_runtime": mixed_runtime})
    adjacent = resolver.resolve(mixed_state, "formation.adjacent", context, subject_ids=("enemy",), options={"counting_option": "IgnoreServant", "side": "Right"})
    enemy_expression = next(
        item for item in expressions
        if any(node.expression_kind == "TargetMapEnemyTeamEntity" for node in _walk_nodes(item.node))
        and item.coverage_status == "executable"
    )
    enemy = TargetSystem(_Rules(expressions)).resolve_target_expression(
        state, enemy_expression, context=context
    )
    empty_owned = resolver.resolve(state, "summon.owned", context, subject_ids=("enemy",))
    reordered_state = BattleState(
        units=dict(reversed(tuple(state.units.items()))),
        global_flags=thaw_json(state.global_flags),
    )
    ordered_a = resolver.resolve(state, "team.same", context, subject_ids=("owner",))
    ordered_b = resolver.resolve(reordered_state, "team.same", context, subject_ids=("owner",))
    limbo_flags = thaw_json(state.units["summon"].flags)
    limbo_flags["lifecycle_source"]["presence"] = "limbo"
    limbo_state = replace(
        state,
        units={
            **state.units,
            "summon": replace(state.units["summon"], flags=limbo_flags),
        },
    )
    alive_only = resolver.resolve(
        limbo_state, "entity.servant", context, options={"mask": "Mask_AliveOnly"}
    )
    alive_or_limbo = resolver.resolve(
        limbo_state, "entity.servant", context, options={"mask": "Mask_AliveOrLimbo"}
    )
    parameter_alias = next(
        str(item.source.evidence.get("source_raw_id"))
        for item in expressions
        if item.source.source_path.endswith("TargetAliasConfig.json")
        and item.node is not None
        and item.node.expression_kind == "TargetFetchParamEntityList"
    )
    operation_definitions = {
        node.expression_kind: item
        for item in expressions
        if item.source.source_path.endswith("TargetOperationConfig.json")
        and item.coverage_status == "executable"
        for node in (item.node,)
        if node is not None and node.expression_kind in {"TargetSortByProperty", "TargetShuffle"}
    }
    sort_definition = operation_definitions["TargetSortByProperty"]
    sort_probe = _alias_probe(
        f"{parameter_alias}.{sort_definition.source.evidence.get('source_raw_id')}"
    )
    ordered_context = TargetEvaluationContext(
        "owner", parameter_entity_ids=("ally", "owner")
    )
    sort_result = TargetSystem(_Rules((*expressions, sort_probe))).resolve_target_expression(
        state, sort_probe, context=ordered_context
    )
    sort_field = {
        "CurrentHP": "hp",
        "MaxHP": "max_hp",
        "CurrentStance": "toughness",
        "MaxStance": "max_toughness",
    }[sort_definition.node.sort_key]
    nonfinite_state = replace(
        state,
        units={
            **state.units,
            "ally": replace(state.units["ally"], **{sort_field: float("nan")}),
        },
    )
    nonfinite_sort = TargetSystem(_Rules((*expressions, sort_probe))).resolve_target_expression(
        nonfinite_state, sort_probe, context=ordered_context
    )
    shuffle_probe = _alias_probe(
        f"{parameter_alias}.{operation_definitions['TargetShuffle'].source.evidence.get('source_raw_id')}"
    )
    shuffle_result = TargetSystem(_Rules((*expressions, shuffle_probe))).resolve_target_expression(
        state, shuffle_probe, context=ordered_context
    )
    unknown_operation = _alias_probe(f"{parameter_alias}.validator_missing_operation")
    unknown_operation_result = TargetSystem(
        _Rules((*expressions, unknown_operation))
    ).resolve_target_expression(state, unknown_operation, context=ordered_context)
    index_results = []
    for item in expressions:
        if (
            item.source.source_path.endswith("TargetOperationConfig.json")
            and item.coverage_status == "executable"
            and item.node is not None
            and item.node.expression_kind == "TargetIndex"
        ):
            probe = _alias_probe(f"{parameter_alias}.{item.source.evidence.get('source_raw_id')}")
            result = TargetSystem(_Rules((*expressions, probe))).resolve_target_expression(
                state, probe, context=ordered_context
            )
            index_results.append(result)
    out_of_range = next((item for item in index_results if item.blocked_reason == "target_index_out_of_range"), None)
    local_rank = next(item for item in expressions if item.source.evidence.get("source_raw_id") == "Cerydra_00_Ultra_TargetList")
    local_rank_result = TargetSystem(_Rules(expressions)).resolve_target_expression(
        state, local_rank, context=context
    )
    turn_owner_expression = next(item for item in expressions if item.node is not None and item.node.expression_kind == "TargetFetchTurnOwnerEntity")
    turn_owner = TargetSystem(_Rules(expressions)).resolve_target_expression(state, turn_owner_expression, context=TargetEvaluationContext("owner", turn_owner_id=committed_turn_owner_id(state)))
    set_state = BattleState(units={"owner": UnitState("owner", "ally", "avatar:owner", flags={"position": 0}), "unselectable": UnitState("unselectable", "ally", "avatar:u", flags={"position": 1, "unselectable": True}), "source_blocked": UnitState("source_blocked", "summon", "servant:blocked", flags={"position": 2, "summon_kind": "servant", "team_side": "ally", "lifecycle_source": {"admission_status": "executable", "presence": "field", "targetable": False, "actionable": True, "timeline_admitted": True}}), "defeated": UnitState("defeated", "ally", "avatar:d", hp=0.0, lifecycle_status="defeated", flags={"position": 3, "unselectable": True, "defeat_record": {"record_type": "damage_defeat", "target_id": "defeated", "defeated_unit_id": "defeated"}}), "active": UnitState("active", "ally", "avatar:a", flags={"position": 4})}, global_flags={"summon_runtime": empty_summon_runtime()})
    set_integrity = CommittedStateIntegrityGate().check_full(set_state)
    team_default = resolver.resolve(set_state, "team.same", TargetEvaluationContext("owner"), subject_ids=("owner",))
    team_allow_unselectable = resolver.resolve(set_state, "team.same", TargetEvaluationContext("owner"), subject_ids=("owner",), options={"allow_unselectable": True})
    unselectable_set = resolver.resolve(set_state, "entity.unselectable", TargetEvaluationContext("owner"))
    selectable_adjacent = resolver.resolve(set_state, "formation.adjacent", TargetEvaluationContext("owner"), subject_ids=("owner",), options={"side": "Right"})
    background_team = resolver.resolve(limbo_state, "team.same", context, subject_ids=("summon",), options={"include_limbo": True, "allow_unselectable": True})
    spawn_rank = _summoned_monster_rank_probe()
    return {
        "summon_runtime_validation": runtime_validation.__dict__,
        "owned_summons": owned.to_json(),
        "summoner": summoner.to_json(),
        "adjacent_ignore_servant": adjacent.to_json(),
        "source_backed_enemy_expression": enemy.to_json(),
        "legal_empty_owned_relation": empty_owned.to_json(),
        "unordered_state_order_a": ordered_a.to_json(),
        "unordered_state_order_b": ordered_b.to_json(),
        "limbo_alive_only": alive_only.to_json(),
        "limbo_alive_or_limbo": alive_or_limbo.to_json(),
        "stable_sort": sort_result.to_json(),
        "nonfinite_sort": nonfinite_sort.to_json(),
        "shuffle_pending_s5d": shuffle_result.to_json(),
        "unknown_operation": unknown_operation_result.to_json(),
        "out_of_range_index": out_of_range.to_json() if out_of_range else {},
        "scoped_alias_alive_rank": local_rank_result.to_json(),
        "committed_turn_owner": turn_owner.to_json(), "team_default": team_default.to_json(), "team_allow_unselectable": team_allow_unselectable.to_json(), "active_unselectable_set": unselectable_set.to_json(),
        "selectable_formation_adjacent": selectable_adjacent.to_json(), "set_fixture_integrity": set_integrity.to_json(), "background_team_subject": background_team.to_json(), "summoned_monster_birth_rank": spawn_rank,
        "ok": (
            runtime_validation.ok and set_integrity.ok
            and _result_ok(owned, ("summon",))
            and _result_ok(summoner, ("owner",))
            and _result_ok(adjacent, ("monster_summon",))
            and _result_ok(enemy, ("enemy",))
            and _result_ok(empty_owned, ())
            and ordered_a.target_ids == ordered_b.target_ids
            and _result_ok(alive_only, ())
            and _result_ok(alive_or_limbo, ("summon",))
            and _result_ok(sort_result, ("ally", "owner"))
            and nonfinite_sort.blocked and not nonfinite_sort.target_ids
            and shuffle_result.blocked and shuffle_result.blocked_reason == "random_target_pending_s5d"
            and unknown_operation_result.blocked and not unknown_operation_result.target_ids
            and out_of_range is not None and not out_of_range.target_ids
            and _result_ok(local_rank_result, ("enemy",))
            and _result_ok(turn_owner, ("ally",)) and _result_ok(team_default, ("active", "owner"))
            and _result_ok(team_allow_unselectable, ("active", "owner", "source_blocked", "unselectable")) and _result_ok(unselectable_set, ("source_blocked", "unselectable")) and _result_ok(selectable_adjacent, ("active",))
            and _result_ok(background_team, ("ally", "owner", "summon")) and spawn_rank["executable_count"] > 0 and spawn_rank["executable_count"] == spawn_rank["ranked_executable_count"]
        ),
    }


def _call_audit() -> dict[str, Any]:
    callers: list[dict[str, Any]] = []
    old_entry_calls: list[str] = []
    missing_context: list[str] = []
    target_system_constructions: list[str] = []
    context_turn_owner_fields: list[str] = []
    for relative in PRODUCTION_CALLERS:
        path = CORE / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "TargetEvaluationContext":
                if "turn_owner_id" in {item.arg for item in node.keywords}:
                    context_turn_owner_fields.append(f"{relative}:{node.lineno}")
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "TargetSystem":
                target_system_constructions.append(f"{relative}:{node.lineno}")
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "resolve_expression_node":
                old_entry_calls.append(f"{relative}:{node.lineno}")
            if node.func.attr != "resolve_target_expression":
                continue
            keywords = {item.arg for item in node.keywords if item.arg}
            location = f"{relative}:{node.lineno}"
            callers.append({"location": location, "keywords": sorted(keywords)})
            if "context" not in keywords:
                missing_context.append(location)
    target_source = (CORE / "systems/target.py").read_text(encoding="utf-8")
    target_tree = ast.parse(target_source)
    relation_source = (CORE / "systems/unit_relation.py").read_text(encoding="utf-8")
    forbidden_parallel = tuple(
        name for name in (
            "_resolve_single_alias", "_target_ids_from_payload", "_summoners_for_targets",
            "_summoned_minions_for_targets", "_resolve_adjacent_expression",
            "_safe_alias_expansion", "_select_random_targets",
            "_resolve_partner_fetch", "_resolve_unique_entity",
        )
        if name in target_source
    )
    freeform_relation_reads = sum(
        target_source.count(pattern)
        for pattern in ("event_payload.get(\"owner_id\"", "event_payload.get(\"summoner_id\"",
                        "event_payload.get(\"param_entity", "event_payload.get(\"event_source")
    )
    character_specific = sum(
        relation_source.count(pattern)
        for pattern in ("template_id ==", "unit_id == \"", "character_name", "skill_name")
    )
    callback_tree = ast.parse((CORE / "systems/status_callbacks.py").read_text(encoding="utf-8"))
    condition_context = next(node for node in ast.walk(callback_tree)
                             if isinstance(node, ast.FunctionDef) and node.name == "_condition_context")
    event_context_fields = []
    for call in ast.walk(condition_context):
        if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "TargetEvaluationContext":
            event_context_fields.append(sorted(item.arg for item in call.keywords if item.arg))
    class _IndexedRules(_Rules):
        def target_language_expressions(self) -> tuple[TargetExpressionIR, ...]:
            return self._expressions
        def target_expressions(self) -> tuple[TargetExpressionIR, ...]:
            raise AssertionError("full target expression scan")
    indexed_lookup_ok = bool(TargetSystem(_IndexedRules(())).alias_definitions == {})
    return {
        "production_callers": callers,
        "old_entry_calls": old_entry_calls,
        "missing_context": missing_context,
        "forbidden_parallel_helpers": forbidden_parallel,
        "freeform_event_payload_relation_reads": freeform_relation_reads,
        "character_specific_relation_handlers": character_specific,
        "single_expression_entry": target_source.count("def resolve_target_expression(") == 1,
        "single_relation_entry": relation_source.count("    def resolve(\n") == 1,
        "random_target_execution_count": target_source.count("_select_random_targets"),
        "target_system_constructions": target_system_constructions,
        "condition_context_event_fields": event_context_fields,
        "context_turn_owner_fields": context_turn_owner_fields,
        "indexed_language_lookup_avoids_full_scan": indexed_lookup_ok,
        "rule_evaluator_constructions": sum(isinstance(node, ast.Call) and getattr(node.func, "id", "") == "RuleEvaluator" for node in ast.walk(target_tree)),
        "ok": (
            bool(callers) and not old_entry_calls and not missing_context
            and not forbidden_parallel and freeform_relation_reads == 0
            and character_specific == 0
            and target_source.count("def resolve_target_expression(") == 1
            and relation_source.count("    def resolve(\n") == 1
            and target_source.count("_select_random_targets") == 0
            and len(target_system_constructions) == 3
            and event_context_fields and all({"event_source_id", "event_target_id"}.issubset(fields) for fields in event_context_fields)
            and len(context_turn_owner_fields) == 11
            and indexed_lookup_ok
        ),
    }


def validate(output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    source_paths = _inventory_paths()
    snapshot = build_character_ability_raw_snapshot(TBGD, source_paths=source_paths)
    projection = build_target_source_projection(TBGD, snapshot=snapshot)
    expressions = tuple(TBGDLowering(TBGD)._lower_global_target_expressions(snapshot))
    all_blocked = [
        (item.dependency_stages, item.blocked_reason,
         item.family if hasattr(item, "family") else item.expression.expression_kind,
         item.source.source_path, item.source.raw_id, str(item.source.evidence.get("json_path") or ""))
        for item in (*projection.records, *projection.language_definitions)
        if item.coverage_status == "blocked"
    ]
    blocked_gameplay = [item for item in projection.records
        if item.responsibility == "s5a_effect_target" and item.coverage_status == "blocked"]
    unowned_gameplay = [item.record_id for item in blocked_gameplay if not item.dependency_stages]
    s5b_gameplay = [item.record_id for item in blocked_gameplay
        if "p9_s5b_entity_relation_deterministic_target" in item.dependency_stages]
    gaps: dict[str, dict[str, Any]] = {}
    grouped: dict[tuple[tuple[str, ...], str, str], list[tuple[Any, ...]]] = defaultdict(list)
    for item in all_blocked:
        grouped[(item[0], item[2], item[1])].append(item)
    for (stages, family, reason), items in sorted(grouped.items()):
        key = f"{'+'.join(stages)}:{family}:{reason}"
        gaps[key] = {
            "dependency_stages": list(stages),
            "family": family,
            "reason": reason,
            "count": len(items),
            "representative": {
                "source_path": items[0][3],
                "record_identity": items[0][4],
                "json_path": items[0][5],
            },
        }
    operator_counts = Counter(node.expression_kind for definition in projection.language_definitions for node in _walk_nodes(definition.expression.node))
    executable_operator_counts = Counter(node.expression_kind for definition in projection.language_definitions if definition.coverage_status == "executable" for node in _walk_nodes(definition.expression.node))
    body_part_executable_count = sum(1 for item in (*projection.records, *projection.language_definitions)
        if item.coverage_status == "executable" and item.expression is not None for node in _walk_nodes(item.expression.node)
        if node.expression_kind in {"TargetMapPartEntity", "TargetMapPartToOwner"})
    negative = _negative_matrix(expressions, projection.language_definitions)
    relations = _relation_matrix(expressions)
    calls = _call_audit()
    source_contract = {
        "inventory_candidate_count": len(source_paths),
        "snapshot_source_count": len(snapshot.sources),
        "source_filter_applied_before_ability_read": snapshot.build_counters.get("source_filter_applied_before_ability_read"),
        "full_canonical_ir_build_count": projection.build_counters.get("full_canonical_ir_build_count"),
        "record_count": len(projection.records),
        "language_definition_count": len(projection.language_definitions),
        "blocked_count": len(all_blocked),
        "blocked_gameplay_count": len(blocked_gameplay),
        "blocked_gameplay_unowned_count": len(unowned_gameplay),
        "blocked_gameplay_s5b_count": len(s5b_gameplay),
        "blocked_gap_ledger_count": sum(item["count"] for item in gaps.values()),
    }
    predicates = {
        "single_entity_relation_resolver": calls["single_relation_entry"],
        "relation_sources_are_committed_and_typed": relations["ok"],
        "freeform_event_payload_relation_reads": calls["freeform_event_payload_relation_reads"],
        "summon_relation_uses_validated_runtime": relations["summon_runtime_validation"]["ok"],
        "relation_mirror_conflicts_fail_closed": negative["summon_mirror_conflict"]["status"] == "blocked",
        "cross_team_modifier_owner_resolved": negative["cross_team_modifier_owner"]["status"] == "resolved",
        "defeated_identity_not_lifecycle_filtered": negative["defeated_modifier_owner"]["status"] == "resolved",
        "partner_unique_require_typed_producer": bool(negative["forged_partner_or_unique"]) and all(
            item["status"] == "blocked" and not item["target_ids"] for item in negative["forged_partner_or_unique"]),
        "target_language_uses_strict_source_closure": negative["unclosed_alias"]["coverage_status"] == "blocked",
        "formal_lowering_reuses_s5a_closure": {item.fingerprint for item in expressions} == {item.expression.fingerprint for item in projection.language_definitions},
        "formal_event_identity_migrated": bool(calls["condition_context_event_fields"]) and all(
            {"event_source_id", "event_target_id"}.issubset(fields) for fields in calls["condition_context_event_fields"]),
        "hot_path_avoids_full_expression_scan": calls["indexed_language_lookup_avoids_full_scan"],
        "deterministic_target_operators_owned_by_s5b_closed": (not s5b_gameplay and not unowned_gameplay
            and relations["committed_turn_owner"]["status"] == "resolved" and relations["summoned_monster_birth_rank"]["executable_count"] > 0 and relations["summoned_monster_birth_rank"]["executable_count"] == relations["summoned_monster_birth_rank"]["ranked_executable_count"]
            and all(negative["context_constructor_rejections"].values()) and relations["team_default"]["target_ids"] != relations["team_allow_unselectable"]["target_ids"]
            and relations["active_unselectable_set"]["target_ids"] == ["source_blocked", "unselectable"] and relations["selectable_formation_adjacent"]["target_ids"] == ["active"] and relations["adjacent_ignore_servant"]["target_ids"] == ["monster_summon"] and relations["background_team_subject"]["status"] == "resolved" and len(calls["context_turn_owner_fields"]) == 11),
        "target_aliases_source_backed": not calls["forbidden_parallel_helpers"],
        "target_alias_cycles_or_ambiguities_blocked": (bool(negative["ambiguous_definition_name"])
            and negative["ambiguous_definition_result"].get("status") == "blocked" and negative["alias_cycle_result"].get("status") == "blocked"),
        "target_order_stable_and_duplicates_removed": (relations["unordered_state_order_a"]["target_ids"] == relations["unordered_state_order_b"]["target_ids"] and relations["stable_sort"]["status"] == "resolved"),
        "legal_missing_relation_resolves_empty": (relations["legal_empty_owned_relation"]["status"] == "resolved" and not relations["legal_empty_owned_relation"]["target_ids"]),
        "damaged_relation_returns_no_partial_targets": not negative["summon_mirror_conflict"]["target_ids"],
        "predicate_evaluator_not_duplicated": calls["rule_evaluator_constructions"] <= 3,
        "body_part_synthetic_producer_count": body_part_executable_count,
        "random_target_execution_count": calls["random_target_execution_count"],
        "character_specific_relation_handlers": calls["character_specific_relation_handlers"],
    }
    operator_matrix = {
        "observed": dict(sorted(operator_counts.items())),
        "executable": dict(sorted(executable_operator_counts.items())),
        "s5b_kinds": sorted(S5B_KINDS),
        "blocked_gameplay_s5b_count": len(s5b_gameplay),
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    evidence_bytes = 0
    for name, value in (
        ("source_contract.json", source_contract),
        ("relation_matrix.json", relations),
        ("negative_cases.json", negative),
        ("operator_matrix.json", operator_matrix),
        ("call_path_audit.json", calls),
        ("dependency_ledger.json", gaps),
    ):
        evidence_bytes += _write(output_dir / name, value)
    elapsed = time.monotonic() - started
    rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    ok = (
        source_contract["source_filter_applied_before_ability_read"] is True
        and source_contract["full_canonical_ir_build_count"] == 0
        and source_contract["inventory_candidate_count"] == source_contract["snapshot_source_count"]
        and source_contract["blocked_count"] == source_contract["blocked_gap_ledger_count"]
        and not s5b_gameplay and not unowned_gameplay
        and negative["ok"] and relations["ok"] and calls["ok"]
        and all(
            value is True or (type(value) is int and value == 0)
            for value in predicates.values()
        )
        and elapsed < 300 and rss_kib < 768 * 1024 and evidence_bytes < 2 * 1024 * 1024
    )
    summary = {
        "ok": ok,
        "predicates": predicates,
        "source_contract": source_contract,
        "resource": {
            "elapsed_seconds": elapsed,
            "peak_rss_kib": rss_kib,
            "evidence_bytes": evidence_bytes,
        },
        "output_dir": str(output_dir),
    }
    _write(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
