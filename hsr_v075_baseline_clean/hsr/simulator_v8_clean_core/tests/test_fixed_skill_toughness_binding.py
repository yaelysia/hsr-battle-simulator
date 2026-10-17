"""Real single, blast and AoE hits retain their source weights and target slots."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.rules.evaluator import NumericEvaluationContext, RuleEvaluator
from hsr.simulator_v8_clean_core.rules.ir import EffectIR, IRSource
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _action_definition_from_row,
    _hit_profiles_from_definition,
    _numeric_expr_summary,
    _stance_expr,
    _toughness_amount_expr,
)


def test_fixed_skill_toughness_uses_target_slots_and_preserves_hit_weights():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    table = "ExcelOutput/AvatarSkillConfig.json"
    rows = json.loads((root / table).read_text())
    definitions = {
        row["SkillID"]: _action_definition_from_row(table, "avatar_skill", "SkillID", index, row)
        for index, row in enumerate(rows)
        if row.get("Level") == 1 and row.get("SkillID") in {
            100801, 100802, 100803, 110301, 110302, 110303,
        }
    }
    abilities = {
        name: json.loads((root / f"Config/ConfigAbility/Avatar/Avatar_{name}_00_Ability.json").read_text())
        for name in ("Arlan", "Serval")
    }
    cases = (
        ("Arlan", 100801, 1, "selected", (3, 5), 30),
        ("Arlan", 100802, 3, "selected", (4,), 60),
        ("Arlan", 100803, 6, "primary", (3, 6, 9), 60),
        ("Arlan", 100803, 6, "adjacent", (4, 7, 10), 60),
        ("Serval", 110301, 1, "selected", (3,), 30),
        ("Serval", 110302, 3, "primary", (3,), 60),
        ("Serval", 110302, 3, "adjacent", (5,), 30),
        ("Serval", 110303, 6, "selected", (2,), 60),
    )
    for name, skill_id, phase, group, indices, expected in cases:
        definition = definitions[skill_id]
        profile = next(item for item in _hit_profiles_from_definition(definition) if item.target_group == group)
        total = 0.0
        for index in indices:
            task = abilities[name]["AbilityList"][phase]["OnStart"][index]
            path = f"$.AbilityList[{phase}].OnStart[{index}]"
            if "SuccessTaskList" in task:
                task = task["SuccessTaskList"][0]
                path += ".SuccessTaskList[0]"
            source = IRSource(
                f"Config/ConfigAbility/Avatar/Avatar_{name}_00_Ability.json",
                "AbilityTask", task["$type"], {"json_path": path},
            )
            effect = EffectIR(path, "Attack", task, source)
            expression = _toughness_amount_expr(effect, profile)
            original = _numeric_expr_summary(task["AttackProperty"]["StanceValue"])
            assert all(expression[key] == value for key, value in original.items())
            result = RuleEvaluator().evaluate_numeric(
                expression, NumericEvaluationContext(binding_sources=(expression["binding_source"],)),
            )
            assert result.ok, result.to_json()
            total += result.value
            assert profile.stance_source["show_stance_audit_only"] is False
        assert total == pytest.approx(expected), (skill_id, group, total)

    # A display total does not define per-bounce or additional dynamic operands.
    assert _stance_expr(replace(definitions[110302], target_mode="bounce"))["kind"] == "audit_only"
    unsupported = replace(effect, payload={
        "AttackProperty": {"StanceValue": {"IsDynamic": True, "PostfixExpr": {
            "OpCodes": "AQAAAAQR", "FixedValues": [{"Value": 1}], "DynamicHashes": [999],
        }}},
    })
    assert "binding_source" not in _toughness_amount_expr(unsupported, profile)
