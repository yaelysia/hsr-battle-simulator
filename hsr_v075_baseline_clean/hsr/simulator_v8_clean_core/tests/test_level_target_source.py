"""Resolve the real LevelEntity source definition through its typed primitive."""

import json
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, TargetExpressionNodeIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.target import TargetSystem
from hsr.simulator_v8_clean_core.systems.unit_relation import TargetEvaluationContext
from hsr.simulator_v8_clean_core.tbgd.lowering import _attach_target_expressions_to_effect_payload
from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions


def test_common_root_resolves_unique_level_anchor_via_real_source_language():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    definitions = build_target_language_definitions(root)
    level = next(item for item in definitions if item.definition_kind == "alias" and item.name == "LevelEntity")
    assert level.coverage_status == "executable", level.blocked_reason
    assert level.expression.node.expression_kind == "TargetFetchLevelEntity"
    assert level.source.evidence["json_path"] == "$.AliasDict.LevelEntity"
    assert TargetExpressionNodeIR.from_json(level.expression.node.to_json()) == level.expression.node
    relative = "Config/ConfigAbility/Level/Level_BattleCommonRule_Ability.json"
    tasks = json.loads((root / relative).read_text())["AbilityList"][0]["OnAdd"]
    expressions = []
    for index, task in enumerate(tasks):
        _, targets = _attach_target_expressions_to_effect_payload(
            {"standard": {}}, task, effect_id=f"root:{index}",
            source=IRSource(relative, "AddModifier", str(index), {"json_path": f"$.AbilityList[0].OnAdd[{index}]"}),
            target_language_definitions=definitions,
        )
        assert len(targets) == 1 and targets[0].coverage_status == "executable"
        expressions.extend(targets)
    system = TargetSystem(RuleBook(CanonicalIR(
        "level-target-source", target_expressions=tuple([
            *(item.expression for item in definitions), *expressions,
        ]),
    )))
    caster = UnitState("caster", "ally", "fixture:caster")
    anchor = UnitState("environment:stage", "ally", "system_entity:level",
                       flags={"system_entity_kind": "level", "unselectable": True})
    valid = BattleState(units={caster.unit_id: caster, anchor.unit_id: anchor})
    context = TargetEvaluationContext(caster.unit_id)
    for expression in expressions:
        result = system.resolve_target_expression(valid, expression, context=context)
        assert result.resolved and result.target_ids == (anchor.unit_id,), result.blocked_reason
        # The familiar identity and ordinary event payload cannot manufacture an anchor.
        missing = replace(valid, units={caster.unit_id: caster, "level:global": UnitState("level:global", "ally", "fixture")})
        result = system.resolve_target_expression(missing, expression, context=context,
            condition_event_payload={"level_entity_id": "level:global"})
        assert result.blocked_reason == "target_level_entity_missing" and not result.target_ids
        other = replace(anchor, unit_id="environment:other")
        conflict = replace(valid, units={**valid.units, other.unit_id: other})
        result = system.resolve_target_expression(conflict, expression, context=context)
        assert result.blocked_reason == "target_level_entity_ambiguous" and not result.target_ids
