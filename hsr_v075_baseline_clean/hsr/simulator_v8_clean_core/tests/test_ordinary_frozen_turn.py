"""Ordinary turn entry keeps control and callback RNG through the scheduler."""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, Mutation, RNGEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
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


@pytest.mark.parametrize('modifier, control_kind, consumes_turn', [
    ('MCommon_Element_Frozen', 'CTRL_Frozen', True),
    ('MCommon_Element_Entangle', 'Entangle', False),
    ('MCommon_Element_Confine', 'Confine', False),
])
def test_expiring_control_consumes_only_its_required_turn(modifier, control_kind, consumes_turn):
    scheduler, state = _scheduler("ally")
    source = IRSource(
        "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json",
        "Modifiers", modifier,
    ).to_json()
    detail = {
        "status_id": f"modifier:{modifier}",
        "modifier_name": modifier,
        "instance_id": "test:frozen:1",
        "owner_id": "holder",
        "status_category": "control",
        "control_kind": control_kind,
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
    assert bool(step.transition.coverage.get("control_skip", {}).get("consumed")) is consumes_turn
    assert step.after_state.units["holder"].statuses == ()
    assert step.after_state.global_flags["combat_phase"] == ("turn_end" if consumes_turn else "awaiting_decision")


def test_removed_turn_owner_closes_without_dispatching_another_turn_end():
    from hsr.simulator_v8_clean_core.systems.action_availability import ActionAvailabilitySystem
    from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem

    scheduler, state = _scheduler('ally')
    state = scheduler.advance_to_next_turn(state).after_state
    removals = UnitLifecycleSystem().remove_mutations(state, 'holder',
        reason='completed summoned action', source='test', removed_record={}, source_trace={})
    state = MutationReducer().apply_all(state, removals)
    assert state.units['holder'].hp > 0  # Muted retirement does not imply lethal HP.
    assert ActionAvailabilitySystem(scheduler.rules).view(state).requires_scheduler_step
    result = scheduler.step(state)
    assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
    assert result.after_state.global_flags['combat_phase'] == 'idle'
    assert not result.after_state.global_flags.get('turn_owner_id')
    assert not any(e.event_type == 'turn.end' for e in result.transition.transaction.events)
    from hsr.simulator_v8_clean_core.systems.event_dispatch import _status_details_for_modifier
    from hsr.simulator_v8_clean_core.systems.trigger import _iter_status_details
    retired = replace(state.units['holder'], flags={'status_details': [
        {'modifier_name': 'remaining_listener', 'owner_id': 'holder'}]})
    state = replace(state, units={'holder': retired})
    assert _status_details_for_modifier(state, 'remaining_listener') == ()
    assert _iter_status_details(state) == ()


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


def test_lifecycle_sweep_skips_a_later_instance_removed_by_an_earlier_callback():
    from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchResult

    scheduler, state = _scheduler('ally')
    def detail(name):
        return {'status_id': f'modifier:{name}', 'modifier_name': name,
                'instance_id': f'fixture:{name}', 'owner_id': 'holder',
                'trigger_ids_by_event': {'OnPhase1': [f'fixture:{name}:phase']}}
    first, later, added = (detail(name) for name in ('first', 'later', 'added'))
    state = replace(state, units={'holder': replace(state.units['holder'],
        statuses=(first['status_id'], later['status_id']), flags={'status_details': [first, later]})})
    calls = []

    def dispatch(current, *, modifier_name, **kwargs):
        calls.append(modifier_name)
        if modifier_name != 'first':
            return EventDispatchResult(current, errors=('status_detail_missing',))
        mutations = (
            Mutation('set', ('units', 'holder', 'statuses'), list(current.units['holder'].statuses),
                     [first['status_id'], added['status_id']], 'fixture callback', 'fixture'),
            Mutation('set', ('units', 'holder', 'flags', 'status_details'), [first, later],
                     [first, added], 'fixture callback', 'fixture'),
        )
        return EventDispatchResult(MutationReducer().apply_all(current, mutations), mutations=mutations)

    scheduler.event_dispatcher.dispatch_status_callback = dispatch
    sweep = scheduler._apply_status_lifecycle_tick(state, 'ModifierPhase1End', actor_id='holder')
    assert not sweep.errors and calls == ['first']
    assert sweep.after_state.units['holder'].flags['status_details'] == [first, added]
    assert MutationReducer().replay_snapshot(state, sweep.mutations, sweep.after_state.snapshot().to_json()).ok


def test_expiry_pins_destroy_to_the_instance_and_broadcasts_removal_notifications():
    from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchResult

    scheduler, state = _scheduler('ally')
    detail = {'status_id': 'modifier:expired', 'modifier_name': 'expired',
              'instance_id': 'fixture:expired', 'owner_id': 'holder', 'caster_id': 'holder',
              'remaining_duration': 1, 'life_step_moment': 'ModifierPhase1End',
              'duration_admission': {'admission_status': 'executable', 'tick_owner_policy': 'holder'}}
    state = replace(state, units={'holder': replace(state.units['holder'],
        statuses=(detail['status_id'],), flags={'status_details': [detail]})})
    calls = []
    def explicit(current, *, event, modifier_name, **kwargs):
        calls.append(('instance', event.window))
        assert event.window == 'OnDestroy' and modifier_name == 'expired'
        return EventDispatchResult(current, events=(event,))
    def broadcast(current, *, event, **kwargs):
        calls.append(('broadcast', event.window))
        assert not kwargs
        return EventDispatchResult(current, events=(event,))
    scheduler.event_dispatcher.dispatch_status_callback = explicit
    scheduler.event_dispatcher.dispatch_event = broadcast
    sweep = scheduler._apply_status_lifecycle_tick(state, 'ModifierPhase1End', actor_id='holder')
    assert not sweep.errors and sweep.after_state.units['holder'].statuses == ()
    assert calls == [('instance', 'OnDestroy'), ('broadcast', 'OnModifierRemove'),
                     ('broadcast', 'OnListenModifierRemove')]


def test_pre_action_removal_closes_the_turn_without_requesting_an_action():
    from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem

    scheduler, state = _scheduler('summon')
    state = replace(state, units={'holder': replace(state.units['holder'], flags={
        'entity_type': 'battle_event', 'timeline_admitted': True, 'status_details': [{
            'status_id': 'fixture:timer', 'modifier_name': 'timer', 'instance_id': 'timer:1',
            'trigger_ids_by_event': {'OnPhase1': ['fixture:expiry']},
        }],
    })})
    original = scheduler.event_dispatcher.dispatch_status_callback
    calls = []

    def expire(current, *, event, **kwargs):
        calls.append(event.window)
        result = original(current, event=event, **kwargs)
        mutations = UnitLifecycleSystem().remove_mutations(
            current, 'holder', reason='fixture expiry', source='fixture',
            source_trace={'source_path': 'fixture:timer'}, removed_record={'reason': 'fixture expiry'},
        )
        return replace(result, after_state=MutationReducer().apply_all(current, mutations),
                       mutations=mutations, errors=())

    scheduler.event_dispatcher.dispatch_status_callback = expire
    step = scheduler.advance_to_next_turn(state)
    assert step.transition.outcome.successor_eligible, step.transition.outcome.reason_codes
    assert calls == ['OnPhase1']
    assert step.after_state.units['holder'].lifecycle_status == 'removed'
    assert step.after_state.units['holder'].hp == 100
    assert step.transition.transaction.command.action_id == 'timeline:consume_removed_turn'
    assert step.after_state.global_flags['combat_phase'] == 'idle'
    assert 'turn_owner_id' not in step.after_state.global_flags
    assert MutationReducer().replay_snapshot(state, step.transition.transaction.mutations,
                                             step.after_state.snapshot().to_json()).ok


@pytest.mark.parametrize('applied_during_begin, remaining', [(False, 1), (True, 2)])
def test_turn_begin_does_not_retroactively_tick_a_new_status(applied_during_begin, remaining):
    scheduler, state = _scheduler('ally')
    detail = {
        'status_id': 'modifier:fixture', 'modifier_name': 'fixture',
        'instance_id': 'fixture:status', 'owner_id': 'holder',
        'remaining_duration': 2, 'life_step_moment': 'ModifierPhase1End',
        'duration_admission': {'admission_status': 'executable', 'tick_owner_policy': 'holder'},
    }
    if applied_during_begin:
        original = scheduler.event_dispatcher.dispatch_event

        def dispatch(current, *, event, **kwargs):
            result = original(current, event=event, **kwargs)
            if event.event_type != 'turn.begin':
                return result
            mutations = (
                Mutation('set', ('units', 'holder', 'statuses'), [], [detail['status_id']], 'fixture callback', 'fixture'),
                Mutation('set', ('units', 'holder', 'flags', 'status_details'), None, [detail],
                         'fixture callback', 'fixture', before_exists=False),
            )
            return replace(result, after_state=MutationReducer().apply_all(result.after_state, mutations),
                           mutations=(*result.mutations, *mutations))

        scheduler.event_dispatcher.dispatch_event = dispatch
    else:
        state = replace(state, units={'holder': replace(state.units['holder'],
            statuses=(detail['status_id'],), flags={'status_details': [detail]})})
    step = scheduler.advance_to_next_turn(state)
    assert step.transition.outcome.successor_eligible, step.transition.outcome.reason_codes
    actual = step.after_state.units['holder'].flags['status_details'][0]
    assert actual['remaining_duration'] == remaining
    assert MutationReducer().replay_snapshot(state, step.transition.transaction.mutations,
                                             step.after_state.snapshot().to_json()).ok
    next_tick = scheduler.status.apply_lifecycle_tick(step.after_state, 'holder', actual, 'ModifierPhase1End')
    assert next_tick.ok and next_tick.operation == ('tick' if applied_during_begin else 'expire')


def test_halo_projection_uses_the_casters_parent_clock():
    from pathlib import Path
    from hsr.simulator_v8_clean_core.rules.ir import EffectIR
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _attach_target_expressions_to_effect_payload, _modifier_addition_effects,
        _modifier_definition_entity, _standard_add_modifier_payload,
        _synchronize_effect_target_expression_metadata,
    )
    from hsr.simulator_v8_clean_core.tbgd.target_source import (
        build_target_language_definitions, close_target_expression_language,
    )
    # Structured lifecycle fixture: the timed caster status owns permanent projections.
    relative = 'Config/ConfigGlobalModifier/fixture_halo.json'
    context = {'json_path': '$.ModifierMap.Parent'}
    raw = {'Stacking': 'ReplaceByCaster', 'LifeTime': {'FixedValue': {'Value': 2}},
           'LifeStepMoment': 'ModifierPhase1End', 'AdditionConfig': {'SubModifierList': [
               {'Name': 'Child', 'TargetType': {'$type': 'RPG.GameCore.TargetAlias',
                'Alias': 'AllEnemyWithUnSelectable'}, 'IsHaloStatus': True}]}}
    additions, expressions = _modifier_addition_effects(relative, 'ModifierMap', 'Parent', raw, source_context=context)
    parent = _modifier_definition_entity(relative, 'ModifierMap', 'Parent', raw,
        source_context=context, addition_effect_ids=(additions[0].effect_id,))
    child = _modifier_definition_entity(relative, 'ModifierMap', 'Child', {'Stacking': 'ReplaceByCaster'},
        source_context={'json_path': '$.ModifierMap.Child'})
    request = {'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
               'ModifierName': {'Value': 'Parent'}}
    source = IRSource(relative, 'AddModifier', 'fixture:parent', {'json_path': '$.OnStart[0]'})
    payload, root_expressions = _attach_target_expressions_to_effect_payload(
        {'standard': _standard_add_modifier_payload(request)}, request, effect_id='fixture:parent', source=source)
    languages = build_target_language_definitions(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main')
    expressions = [close_target_expression_language(row, languages) for row in (*expressions, *root_expressions)]
    effects = _synchronize_effect_target_expression_metadata([
        EffectIR('fixture:parent', 'AddModifier', payload, source, 'executable',
                 modifier_definition_id=parent.entity_id, source_mode='mainline'),
        replace(additions[0], modifier_definition_id=child.entity_id, source_mode='mainline'),
    ], expressions)
    rules = RuleBook(CanonicalIR('fixture:halo', entities=(parent, child), effects=tuple(effects),
                                target_expressions=(*expressions, *(row.expression for row in languages))))
    owner = UnitState('ally:owner', 'ally', 'avatar:fixture', hp=100, max_hp=100)
    member = UnitState('enemy', 'enemy', 'monster:fixture', hp=100, max_hp=100)
    state = BattleState(units={owner.unit_id: owner, member.unit_id: member})
    status = StatusSystem(rules)
    addition = status.apply_add_modifier(state, effects[0],
        caster_id='ally:owner', owner_id='ally:owner', source_id='fixture:halo')
    assert addition.ok, addition.unsupported
    wrong_source = replace(effects[1].source, evidence={**effects[1].source.evidence, 'json_path': '$.wrong'})
    wrong_rules = RuleBook(replace(rules.ir, effects=(effects[0], replace(effects[1], source=wrong_source))))
    rejected = StatusSystem(wrong_rules).apply_add_modifier(state, effects[0],
        caster_id='ally:owner', owner_id='ally:owner', source_id='fixture:halo')
    assert not rejected.ok and not rejected.mutations
    current = MutationReducer().apply_all(state, addition.mutations)
    projection = current.units['enemy'].flags['status_details'][0]
    assert projection['remaining_duration'] is None
    for _ in range(3):
        tick = status.apply_lifecycle_tick(current, 'enemy', projection, 'ModifierPhase1End')
        assert tick.ok and tick.operation == 'tick_skipped' and not tick.mutations
    mutations = list(addition.mutations)
    for expected in (1, 0):
        parent = current.units['ally:owner'].flags['status_details'][0]
        tick = status.apply_lifecycle_tick(current, 'ally:owner', parent, 'ModifierPhase1End')
        assert tick.ok, tick.unsupported
        mutations.extend(tick.mutations)
        current = MutationReducer().apply_all(current, tick.mutations)
        assert bool(current.units['enemy'].statuses) == bool(expected)
        if expected:
            assert current.units['ally:owner'].flags['status_details'][0]['remaining_duration'] == expected
            assert current.units['enemy'].flags['status_details'][0]['remaining_duration'] is None
    assert MutationReducer().replay_snapshot(state, mutations, current.snapshot().to_json()).ok


def test_defeated_waiting_actor_closes_turn_without_status_ticks_or_callbacks():
    scheduler, state = _scheduler("enemy")
    state = replace(state, units={"holder": replace(state.units["holder"], hp=0, lifecycle_status="defeated")},
                    global_flags={"turn_owner_id": "holder", "combat_phase": "awaiting_decision",
                                  "active_turn": {"actor_id": "holder", "turn_kind": "regular"}})

    def unexpected(*args, **kwargs):
        raise AssertionError("a defeated holder must not execute TurnEnd status callbacks")

    scheduler._apply_status_lifecycle_tick = unexpected
    scheduler.event_dispatcher.dispatch_event = unexpected
    assert scheduler.action_availability(state).requires_scheduler_step
    step = scheduler.step(state)
    assert step.transition.outcome.successor_eligible, step.transition.outcome.reason_codes
    assert step.after_state.global_flags["combat_phase"] == "idle"
    assert not step.after_state.global_flags.get("turn_owner_id")
    assert step.after_state.units["holder"].hp == 0
    assert step.transition.coverage["phase_machine"]["path"] == ["awaiting_decision", "turn_end", "idle"]
    living = replace(state, units={"holder": replace(state.units["holder"], hp=100, lifecycle_status="active")})
    assert "turn_end" not in scheduler.phases.allowed_next_phases(living)
