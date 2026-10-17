"""The sourced ordinary break predicate chooses exactly one Wind status branch."""

import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, MonsterDataCardIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.break_system import BreakSystem
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.systems.toughness import ToughnessPacket
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering,
    _link_status_effect_runtime_fields,
    _modifier_definition_entity,
    _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language


@pytest.mark.parametrize("rank,selected_branch", [("BigBoss", True), ("Elite", False)])
def test_real_wind_break_predicate_selects_sourced_modifier_branch(rank, selected_branch):
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    lowering = TBGDLowering(root)
    templates, _, status_emissions, effects, targets, conditions = lowering._lower_break_templates()
    template = next(item for item in templates if item.element_type == "Wind")
    branches = tuple(item for item in status_emissions if item.template_id == template.template_id)
    assert len(branches) == 2
    assert [item.condition_expected for item in branches] == [True, False]
    assert [item.source.evidence["json_path"] for item in branches] == [
        "$.TaskListTemplate[9].TaskList[1].SuccessTaskList[0]",
        "$.TaskListTemplate[9].TaskList[1].FailedTaskList[0]",
    ]

    modifier_path = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
    raw = json.loads((root / modifier_path).read_text(encoding="utf-8"))
    modifier = _modifier_definition_entity(
        modifier_path, "ModifierMap", "MCommon_Element_Poison",
        raw["ModifierMap"]["MCommon_Element_Poison"],
    )
    card = MonsterDataCardIR(
        "card:rank-check", "monster:rank-check", "rank-check", "rank-check", rank,
        "", "", (), (), {}, (), (), {}, {}, IRSource("rank-check", "Monster", rank),
        coverage_status="lowered",
    )
    scores = lowering._monster_rank_scores()
    target_definitions = lowering._strict_target_language_definitions()
    parameter_alias = next(
        item.expression for item in target_definitions
        if item.definition_kind == "alias" and item.name == "ParamEntity"
    )
    closed_targets = tuple(
        close_target_expression_language(item, target_definitions) for item in targets
    )
    effects = _link_status_effect_runtime_fields(effects, [modifier], [])
    effects = _synchronize_effect_target_expression_metadata(effects, list(closed_targets))
    rules = RuleBook(CanonicalIR(
        "wind-break-rank-check", entities=(modifier,), monster_data_cards=(card,),
        metadata={"monster_rank_scores": scores}, break_templates=(template,),
        break_status_emissions=branches, effects=tuple(effects),
        target_expressions=(*closed_targets, parameter_alias), conditions=tuple(conditions),
    ))
    state = BattleState(
        units={
            "attacker": UnitState("attacker", "ally", "fixture:attacker", level=80),
            "target": UnitState(
                "target", "enemy", card.entity_ref, max_toughness=300,
                flags={
                    "monster_data_card_id": card.card_id,
                    "monster_rank": rank,
                    "monster_rank_score": scores[rank],
                },
            ),
        },
        global_flags={"monster_rank_scores": scores},
    )
    packet = ToughnessPacket(
        "attacker", "target", "fixture:toughness", "fixture:task", "fixture:hit",
        "Wind", 30, "primary", "executable", {},
    )
    system = BreakSystem(rules, EffectRegistry(StatusSystem(rules)))
    for emission in branches:
        result = system._apply_status_emission(state, packet, template, emission)
        assert result.ok, result.errors
        assert bool(result.mutations) is (emission.condition_expected is selected_branch)
        if result.mutations:
            detail = result.after_state.units["target"].flags["status_details"][0]
            assert detail["stacks"] == (3 if selected_branch else 1)
            if selected_branch:
                repeated = system._apply_status_emission(result.after_state, packet, template, emission)
                assert repeated.ok, repeated.errors
                assert repeated.after_state.units["target"].flags["status_details"][0]["stacks"] == 5
