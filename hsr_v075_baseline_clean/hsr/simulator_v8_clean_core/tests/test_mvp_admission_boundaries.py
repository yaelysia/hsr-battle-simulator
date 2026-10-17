from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR, CanonicalIR, EffectIR, IRSource, PassiveMechanismSlotIR,
    StandaloneAbilityGraphIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.session import command_from_json
from hsr.simulator_v8_clean_core.scenarios.build_state import _passive_runtime_activation
from hsr.simulator_v8_clean_core.systems.decision import DecisionSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _admit_passive_startup_slot, _dedupe_entities,
)


def test_timeline_choice_template_can_be_submitted_without_client_repair():
    rules = RuleBook(CanonicalIR(
        version="tie-test", timeline_rules=build_engine_rule_registry().timeline_rules,
    ))
    state = BattleState(units={name: UnitState(
        name, "ally", "validation:tie", max_hp=100, hp=100, action_value=10,
    ) for name in ("first", "second")})
    system = DecisionSystem(rules)
    decision = system.current_decision(state)
    assert decision.ready, decision.blocked_reason
    assert decision.availability.mode == "timeline_actor_selectable"
    choice = decision.availability.choices[0]
    command = command_from_json(dict(choice.command_template))
    result = system.submit(state, decision.token, command)
    assert result.transition.outcome.successor_eligible, result.transition.outcome
    assert result.after_state.global_flags["turn_owner_id"] == choice.actor_id


def test_advance_returns_scheduler_failure_on_the_public_decision(monkeypatch):
    rules = RuleBook(CanonicalIR(
        version="decision-failure", timeline_rules=build_engine_rule_registry().timeline_rules,
    ))
    state = BattleState(units={"actor": UnitState(
        "actor", "ally", "validation:decision", max_hp=100, hp=100, action_value=10,
    )})
    system = DecisionSystem(rules)
    pending = system.current_decision(state)
    failure = system.scheduler.reject_decision_submission(state, "fixture_callback_missing", {})
    monkeypatch.setattr(system.scheduler, "step", lambda current: failure)
    advanced = system.advance_to_decision(state)
    assert advanced.blocked_reason == advanced.decision.blocked_reason == "fixture_callback_missing"
    assert advanced.after_state is state
    assert replace(advanced.decision, blocked_reason=pending.blocked_reason) == pending
    assert advanced.transitions == (failure.transition,)


def test_partial_passive_startup_cannot_be_marked_executable():
    source = IRSource("synthetic:passive", "validation", "passive")
    slot = PassiveMechanismSlotIR(
        "slot", "card", "monster", "monster:fixture", "monster_ability_list_passive",
        "startup_status_system", {}, {"callback_kind": "OnStart"},
        {"ability_name": "passive"}, source, coverage_status="lowered",
    )
    graph = StandaloneAbilityGraphIR(
        "graph", "passive", "mainline_monster", ("phase",), ("ok", "missing"),
        ("ok", "missing"), source, coverage_status="executable",
    )
    task = AbilityTaskIR(
        "ok", "phase", "", 0, "passive", "OnStart", 0, "OnStart[0]", "",
        "AddModifier", source, effect_id="effect", coverage_status="executable",
    )
    effect = EffectIR("effect", "AddModifier", {"standard": {
        "modifier_name": "fixture", "target_alias": "Caster",
    }}, source, "executable")
    result = _admit_passive_startup_slot(
        slot, graphs_by_name={"passive": [graph]},
        tasks_by_phase={"phase": [task, replace(task, task_id="missing", effect_id="absent")]},
        effects_by_id={"effect": effect}, modifiers_with_triggers=set(),
    )
    assert result.coverage_status == "blocked"
    assert result.semantics["startup_admission"]["blocked_tasks"][0]["task_id"] == "missing"


def test_local_modifiers_with_same_name_keep_distinct_source_identities():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    path = root / "Config/ConfigAbility/Monster/Monster_Common_Ability.json"
    lowered = TBGDLowering(root)._lower_ability_file(path, {}, ability_file_order=0)
    definitions = [row for row in lowered.entities
                   if row.fields.get("modifier_name") == "MMonster_SpecialDieEffect"]
    assert len(definitions) == 2
    assert len(_dedupe_entities(definitions)) == 2
    assert len({row.source.evidence["json_path"] for row in definitions}) == 2


def test_missing_passive_definition_cannot_be_treated_as_no_passives():
    card = SimpleNamespace(card_id="card", passive_mechanism_slot_ids=("missing",))
    activation = _passive_runtime_activation(RuleBook(CanonicalIR(version="missing-passive")), card)
    assert activation["flags"]["blocked_passive_mechanism_slots"] == ({
        "passive_slot_id": "missing",
        "blocked_reason": "monster_passive_slot_reference_not_closed",
    },)
