import math
import unittest

from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, CanonicalIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.value_binding import (
    StaticValueBindingContext,
    StaticValueBindingResolver,
)


def _definition(*, sp_need=None):
    return ActionDefinitionIR(
        definition_id="synthetic:action",
        action_id="synthetic:action",
        level=1,
        attack_type="Ultra",
        skill_effect="Ultimate",
        target_mode="single",
        bp_need=0.0,
        bp_add=0.0,
        sp_base=0.0,
        sp_multiple_ratio=0.0,
        param_list=(),
        show_stance_list=(),
        show_damage_list=(),
        stance_damage_type=None,
        source=IRSource("synthetic", "action", "test"),
        coverage_status="executable",
        sp_need=sp_need,
    )


class ActionDefinitionSPNeedTest(unittest.TestCase):
    def test_sp_need_round_trips_and_resolves_only_when_present(self):
        definition = _definition(sp_need=120)
        self.assertEqual(definition.sp_need, 120.0)
        self.assertEqual(definition.to_json()["sp_need"], 120.0)

        resolver = StaticValueBindingResolver(
            RuleBook(CanonicalIR(version="synthetic", action_definitions=(definition,)))
        )
        context = StaticValueBindingContext(action_id=definition.action_id, action_level=1)
        resolved = resolver.resolve_action_definition_numeric_field(
            context, field_name="sp_need"
        )
        self.assertTrue(resolved.ok)
        self.assertEqual(resolved.value, 120.0)

        missing = _definition()
        self.assertIsNone(missing.to_json()["sp_need"])
        missing_resolved = StaticValueBindingResolver(
            RuleBook(CanonicalIR(version="synthetic:missing", action_definitions=(missing,)))
        ).resolve_action_definition_numeric_field(context, field_name="sp_need")
        self.assertFalse(missing_resolved.ok)
        self.assertEqual(missing_resolved.blocked_reason, "field_value_not_numeric")

    def test_sp_need_rejects_non_finite_or_non_numeric_values(self):
        for sp_need in (True, float("nan"), float("inf"), -float("inf"), "120"):
            with self.subTest(sp_need=sp_need):
                with self.assertRaises((TypeError, ValueError)):
                    _definition(sp_need=sp_need)

    def test_sp_need_accepts_finite_numbers(self):
        self.assertEqual(_definition(sp_need=-1).sp_need, -1.0)
        self.assertGreater(_definition(sp_need=math.nextafter(0.0, 1.0)).sp_need, 0.0)
