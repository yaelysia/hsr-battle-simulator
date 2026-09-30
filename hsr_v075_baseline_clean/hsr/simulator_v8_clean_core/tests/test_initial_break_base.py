"""The real shared expressions produce damage, not an unscaled percentage."""
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.evaluator import NumericEvaluationContext, RuleEvaluator
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.break_system import BreakSystem
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.toughness import ToughnessPacket
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering


@pytest.mark.parametrize("level,toughness,element,expected", [
    (1, 30.0, "Thunder", 54.0 * 0.75),
    (80, 300.0, "Fire", 3767.5535 * 2.0 * 3.0),
])
def test_real_initial_break_expression_uses_level_and_normalized_max_toughness(
    level, toughness, element, expected,
):
    lowering = TBGDLowering(Path(__file__).resolve().parents[4] / "turnbasedgamedata-main")
    templates, emissions, _, _, _, _ = lowering._lower_break_templates()
    rules = RuleBook(CanonicalIR(
        "initial-break-check", break_templates=tuple(templates),
        break_damage_emissions=tuple(emissions),
        break_base_damage=tuple(lowering._lower_break_base_damage()),
    ))
    emission = next(item for item in emissions if item.element_type == element)
    state = BattleState(units={
        "attacker": UnitState("attacker", "ally", "fixture:attacker", level=level),
        "target": UnitState("target", "enemy", "fixture:target", max_toughness=toughness),
    })
    packet = ToughnessPacket(
        "attacker", "target", "fixture:toughness", "fixture:task", "fixture:hit",
        element, toughness, "primary", "executable", {},
    )
    result = BreakSystem(rules, EffectRegistry())._evaluate_break_damage_amount(
        state, packet, rules.break_template(emission.template_id), emission,
    )
    assert result.ok, result.to_json()
    assert result.value == pytest.approx(expected)


def test_real_break_status_templates_bind_stance_and_level_base_before_modifier():
    lowering = TBGDLowering(Path(__file__).resolve().parents[4] / "turnbasedgamedata-main")
    templates, _, _, effects, _, _ = lowering._lower_break_templates()
    rules = RuleBook(CanonicalIR(
        "break-status-binding-check", break_templates=tuple(templates),
        break_base_damage=tuple(lowering._lower_break_base_damage()),
    ))
    system = BreakSystem(rules, EffectRegistry())
    state = BattleState(units={
        "attacker": UnitState("attacker", "ally", "fixture:attacker", level=80),
        "target": UnitState("target", "enemy", "fixture:target", max_toughness=300),
    })
    for element, key, expected in (
        ("Physical", "MDF_DamageMax", 22605.321),
        ("Quantum", "MDF_DamagePercentage", 1.8),
    ):
        template = next(item for item in templates if item.element_type == element)
        effect = next(item for item in effects if item.owner_modifier_name == f"StanceBreak_{element}")
        packet = ToughnessPacket(
            "attacker", "target", "fixture:toughness", "fixture:task", "fixture:hit",
            element, 30, "primary", "executable", {},
        )
        source, error = system._status_binding_source(state, packet, template)
        assert not error
        if element == "Physical":
            base_entry = source["entries"][source["by_name"]["CasterBreakBaseDamage"][0]]
            assert base_entry["owner_id"] == "attacker"
            assert base_entry["source_trace"]["break_base_damage"]["level"] == 80
        expression = effect.payload["standard"]["dynamic_values"][key]
        result = RuleEvaluator().evaluate_numeric(
            expression, NumericEvaluationContext(binding_sources=(source,)),
        )
        assert result.ok, result.to_json()
        assert result.value == pytest.approx(expected)


def test_real_break_shock_percentage_is_preserved_before_level_scaling():
    import json
    from hsr.simulator_v8_clean_core.rules.ir import IRSource
    from hsr.simulator_v8_clean_core.systems.status import StatusInstance
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_damage_emission_from_task

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    relative = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
    modifier = "MCommon_Element_Electric"
    raw = json.loads((root / relative).read_text())["ModifierMap"][modifier]
    task = raw["_CallbackList"][1]["CallbackConfig"][2]
    source = IRSource(relative, "StatusCallbackTask", modifier, {
        "json_path": f"$.ModifierMap.{modifier}._CallbackList[1].CallbackConfig[2]",
    })
    emission = _status_damage_emission_from_task(
        callback_id="fixture:shock", task_id="fixture:shock_damage",
        modifier_name=modifier, event="OnPhase1", task=task, source=source,
    )
    assert emission is not None and emission.coverage_status == "executable"
    detail = StatusInstance(
        "fixture:shock", "modifier:" + modifier, modifier, "target", "fixture:break", "attacker",
        dynamic_values={"__by_hash": {"1486739431": 2.0, "1912601768": 1.0}},
        source_trace=source.to_json(),
    ).to_json()
    state = BattleState(units={
        "attacker": UnitState("attacker", "ally", "fixture:attacker", level=1),
        "target": UnitState("target", "enemy", "fixture:target", flags={"status_details": [detail]}),
    })
    rules = RuleBook(CanonicalIR(
        "shock-check", break_base_damage=tuple(TBGDLowering(root)._lower_break_base_damage()),
    ))
    result = StatusCallbackSystem(rules)._evaluate_status_damage_amount(state, detail, emission)
    assert result.ok, result.to_json()
    assert result.value == 2.0 * 54.0
