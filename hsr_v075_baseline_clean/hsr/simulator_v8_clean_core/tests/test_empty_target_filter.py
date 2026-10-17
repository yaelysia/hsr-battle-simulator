"""Unknown predicate is inactive only when the actual candidate pool is empty."""
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.target import TargetSystem, _TargetRelationRuntime, _resolve_transform_expression
from hsr.simulator_v8_clean_core.systems.unit_relation import TargetEvaluationContext
from hsr.simulator_v8_clean_core.tbgd.lowering import _target_expression_from_raw
from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions, close_target_expression_language


def test_real_gridfight_alias_skips_unknown_predicate_only_for_empty_battle_event_pool():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    definitions = build_target_language_definitions(root)
    definition = next(item for item in definitions if item.name == "GridFight_AllBackEndActivedRoleOnly")
    assert definition.coverage_status == "executable", definition.blocked_reason
    predicate = definition.expression.node.children[1].predicate
    assert predicate.coverage_status == "blocked"
    assert "ByCompareGridFightProperty" in predicate.blocked_reason
    assert predicate.source.source_path == "Config/GlobalConfig/TargetAliasConfig.json"
    assert "GridFight_AllBackEndActivedRoleOnly" in predicate.source.evidence["json_path"]
    rules = RuleBook(CanonicalIR("empty-filter", target_expressions=tuple(item.expression for item in definitions)))
    targets = TargetSystem(rules)
    state = BattleState(units={"actor": UnitState("actor", "ally", "fixture", hp=100, max_hp=100)})
    context = TargetEvaluationContext("actor")
    empty = targets.resolve_target_expression(state, definition.expression, context=context)
    assert empty.resolved and empty.target_ids == (), empty.to_json()
    assert "empty_candidate_pool" in str(empty.metadata)
    # Operations receive a formally bound list even when it is empty.
    for alias in ("GridFight_AllBackEndActivedRoleOnly.WithBEServant",
                  "(GridFight_AllBackEndActivedRoleOnly | GridFight_AllBackEndActivedRoleOnly).WithBEServant",
                  "ParamEntityList"):
        expression = _target_expression_from_raw(
            {"$type": "RPG.GameCore.TargetAlias", "Alias": alias}, field_name="",
            expression_id=f"fixture:operation-list:{alias}",
            source=IRSource("validation_fixture/empty_filter.json", "TargetAlias", alias, {"json_path": "$"}),
        )
        expression = close_target_expression_language(expression, definitions)
        resolved = targets.resolve_target_expression(state, expression, context=context)
        if alias == "ParamEntityList":
            assert resolved.blocked_reason == "context_parameter_missing"
        else:
            assert resolved.resolved and resolved.target_ids == (), resolved.to_json()
    operation = next(item for item in definitions if item.definition_kind == "operation" and item.name == "GetBEServant")
    created_map = operation.expression.node.children[0]
    assert created_map.expression_kind == "TargetMapCreatedBattleEvent"
    assert created_map.source.evidence["json_path"].endswith(".GetBEServant.Sequence[0]")
    relation_runtime = _TargetRelationRuntime(context, targets.relations, targets.alias_definitions,
        targets.operation_definitions, targets.scoped_alias_definitions, created_map.source.source_path,
        targets.random_sampler, targets.condition_facts, None)
    # Exercise the actual source map subtree; its later subtype filter is a
    # separate condition consumer and is not part of this relation check.
    for creator in ("actor", "", "missing-creator"):
        event = UnitState("created-event", "summon", "fixture", hp=1, max_hp=1,
            flags={"entity_type": "battle_event", "summoner_id": creator})
        created = replace(state, units={**state.units, event.unit_id: event})
        mapped = _resolve_transform_expression(created, created_map,
            expression_kind=created_map.expression_kind, caster_id=context.caster_id, owner_id=None,
            target_resolution=None, event_payload={}, dynamic_values=None, binding_sources=(),
            candidate_targets=("actor",), path="$", relation_runtime=relation_runtime)
        if creator == "actor":
            assert not mapped.blocked_reason and mapped.target_ids == (event.unit_id,)
        else:
            assert mapped.blocked_reason == "battle_event_creator_missing" and not mapped.target_ids
    nonempty = replace(state, units={**state.units,
        "event": UnitState("event", "summon", "fixture", hp=1, max_hp=1,
                           flags={"entity_type": "battle_event", "owner_id": "actor"})})
    before = nonempty.snapshot().to_json()
    rejected = targets.resolve_target_expression(nonempty, definition.expression, context=context)
    assert rejected.blocked and "ByCompareGridFightProperty" in rejected.blocked_reason, rejected.to_json()
    assert not rejected.target_ids and not rejected.rng_events
    assert nonempty.snapshot().to_json() == before
    # A filter's explicit candidate overrides the preceding sequence pool.
    raw = {"$type": "RPG.GameCore.TargetSequence", "Sequence": [
        {"$type": "RPG.GameCore.TargetFetchNone"},
        {"$type": "RPG.GameCore.TargetFilter", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
         "Predicate": {"$type": "RPG.GameCore.ByCompareGridFightProperty", "PropertyType": "LocationIndex",
                       "CompareType": "Greater", "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 0}}}},
    ]}
    expression = _target_expression_from_raw(raw, field_name="", expression_id="fixture:explicit-candidate",
        source=IRSource("validation_fixture/empty_filter.json", "TargetSequence", "explicit-candidate", {"json_path": "$"}))
    expression = close_target_expression_language(expression, definitions)
    explicit = targets.resolve_target_expression(state, expression, context=context)
    assert explicit.blocked and "ByCompareGridFightProperty" in explicit.blocked_reason
