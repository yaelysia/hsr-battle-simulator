"""Ordinary turn entry keeps control and callback RNG through the scheduler."""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, RNGEvent, UnitState
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import (
    ENGINE_RULE_REGISTRY_VERSION,
    TIMELINE_RULE_APPLICABILITY,
)
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, TimelineRuleIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.scheduler import CombatScheduler


def _scheduler(side: str) -> tuple[CombatScheduler, BattleState]:
    rule = TimelineRuleIR(
        "test:ordinary_turn", 10000, "base_action_gauge_div_speed",
        "base_action_gauge_div_speed", "engine_convention",
        IRSource("fixture:ordinary_turn", "TimelineRule", "ordinary_turn"),
        registry_version=ENGINE_RULE_REGISTRY_VERSION,
        applicability=TIMELINE_RULE_APPLICABILITY,
    )
    unit = UnitState(
        "holder", side, "test:holder", hp=100, max_hp=100,
        speed=100, action_value=0,
    )
    return CombatScheduler(RuleBook(CanonicalIR(
        "test:ordinary_turn", timeline_rules=(rule,),
    ))), BattleState(units={"holder": unit})


def test_expiring_frozen_status_still_consumes_current_action():
    scheduler, state = _scheduler("enemy")
    source = IRSource(
        "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json",
        "Modifiers", "MCommon_Element_Frozen",
    ).to_json()
    detail = {
        "status_id": "modifier:MCommon_Element_Frozen",
        "modifier_name": "MCommon_Element_Frozen",
        "instance_id": "test:frozen:1",
        "owner_id": "holder",
        "status_category": "control",
        "control_kind": "CTRL_Frozen",
        "lifecycle_state": "active",
        "remaining_duration": 1.0,
        "life_step_moment": "ModifierPhase1End",
        "duration_admission": {
            "admission_status": "executable",
            "tick_owner_policy": "holder",
            "life_step_moment": "ModifierPhase1End",
            "source_trace": source,
        },
        "source_trace": {"modifier_definition": source},
    }
    actor = replace(
        state.units["holder"],
        statuses=(detail["status_id"],),
        flags={"status_details": [detail]},
    )
    step = scheduler.advance_to_next_turn(replace(
        state, units={"holder": actor},
    ))
    assert step.transition.outcome.successor_eligible
    assert step.transition.coverage["control_skip"]["consumed"] is True
    assert step.after_state.units["holder"].statuses == ()
    assert step.after_state.global_flags["combat_phase"] == "turn_end"


def test_turn_begin_callback_rng_reaches_formal_transition():
    scheduler, state = _scheduler("ally")
    original = scheduler.event_dispatcher.dispatch_event
    expected = RNGEvent("test:turn_begin", "test:callback", {"selected": 1})

    def dispatch(current, *, event, **kwargs):
        result = original(current, event=event, **kwargs)
        return replace(result, rng_events=(*result.rng_events, expected)) if event.event_type == "turn.begin" else result

    scheduler.event_dispatcher.dispatch_event = dispatch
    step = scheduler.advance_to_next_turn(state)
    assert step.transition.outcome.successor_eligible
    assert step.transition.rng_events == (expected,)
