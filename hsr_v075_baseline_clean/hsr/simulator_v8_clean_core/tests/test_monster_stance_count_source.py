"""Monster stance count comes from the selected TBGD template card."""

from pathlib import Path

from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, RuleEntity, StatusEventFamilyIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.scenarios.build_state import ScenarioStateBuilder
from hsr.simulator_v8_clean_core.scenarios.schema import PanelInput, ScenarioSpec, UnitSpec
from hsr.simulator_v8_clean_core.tbgd.monster_cards import build_monster_card_ir


def test_real_monster_template_stance_counts_reach_initial_units():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    cards = tuple(build_monster_card_ir(
        root, max_records_per_table=None,
        monster_ids=frozenset({"1002011", "4034013", "7001010"}),
    ).monster_data_cards)
    expected = {"1002011": 1, "4034013": 2, "7001010": 1}
    assert {card.monster_id: card.raw_parameter_blocks["template_config"]["stance_count"]
            for card in cards} == expected
    assert all(card.source.evidence["template_source"]["raw_id"] == card.template_id for card in cards)
    assert {card.source.evidence["template_source"]["source_path"] for card in cards} == {
        "ExcelOutput/MonsterTemplateConfig.json",
        "ExcelOutput/MonsterTemplateUniqueConfig.json",
    }

    enter_battle = StatusEventFamilyIR(
        "test:enter_battle", "OnEnterBattle", "battle_start", "status_local",
        ("battle.setup",), "StatusCallbackIR.event",
        IRSource("test:scenario", "StatusEventFamily", "OnEnterBattle"),
        coverage_status="executable", admission_status="executable",
    )
    rules = RuleBook(CanonicalIR(
        "monster-stance-count-check",
        entities=tuple(RuleEntity(card.entity_ref, "monster", {}, card.source) for card in cards),
        monster_data_cards=cards,
        status_event_families=(enter_battle,),
        metadata={"monster_rank_scores": {"Minion": 0.5, "MinionLv2": 1.0, "LittleBoss": 2.0}},
    ))
    scenario = ScenarioSpec("monster-stance-count-check", "1", tuple(
        UnitSpec(
            card.monster_id, "enemy", card.entity_ref, "kernel_fixture",
            panel=PanelInput(
                max_hp=100, attack=10, defense=10, speed=100,
                toughness=10, max_toughness=10,
                flags={"monster_stance_count": 99},
            ),
        ) for card in cards
    ), ())
    state = ScenarioStateBuilder(rules).build(scenario).state
    assert {unit_id: state.units[unit_id].flags["monster_stance_count"]
            for unit_id in expected} == expected
