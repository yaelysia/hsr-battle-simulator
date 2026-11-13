"""A callback-emitted lifecycle event is returned once after recursive dispatch."""

from types import SimpleNamespace
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, RNGEvent, UnitState
from hsr.simulator_v8_clean_core.core.executor import _dedupe_events, _EventIdentityConflict
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, StatusCallbackIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import (
    MAX_CALLBACK_EMITTED_EVENT_DEPTH, EventDispatchSystem, EventNormalization, ListenerMatch,
)
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackExecutionResult


def test_synchronous_status_children_keep_executing_action_context():
    from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, EffectIR, StatusCallbackTaskIR
    from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectResult
    from hsr.simulator_v8_clean_core.systems.status_callbacks import _condition_context, _effect_context

    source = IRSource('fixture', 'fixture', 'context-transport')
    action = ActionDefinitionIR('definition', 'action', 1, 'Ultra', 'SingleAttack', 'Single',
                                0, 0, 0, 0, (), (), (), 'Quantum', source)
    rules = RuleBook(CanonicalIR('action-context'))
    state = BattleState(units={'owner': UnitState('owner', 'ally', 'fixture')})
    detail = {'owner_id': 'owner', 'caster_id': 'owner', 'instance_id': 'status'}
    registry = EffectRegistry()
    registry.register('FixtureChild', lambda effect, context: EffectResult(events=(
        GameEvent('status.lifecycle', source_id='owner', target_id='owner', window='OnStack'),)))
    effect = EffectIR('child', 'FixtureChild', {}, source, coverage_status='executable')
    task = StatusCallbackTaskIR('task', 'callback', 'M', 'OnStack', 0, '$.TaskList[0]',
                                'root', 'FixtureChild', source, coverage_status='executable')
    context = EffectExecutionContext(state=state, caster_id='owner', source_id='fixture', action_definition=action)
    for _ in range(2):
        result = registry.execute(effect, context)
        assert not result.unsupported
        event, = result.events
        assert event.action_definition is action
        assert _condition_context(rules, state, detail, event).event_payload['SkillType'] == 'Ultra'
        context = _effect_context(rules, state, task, detail, event)
        assert context.action_definition is action
        assert 'action_definition' not in event.to_json()
    unrelated, = registry.execute(effect, replace(context, action_definition=None)).events
    assert unrelated.action_definition is None
    assert 'SkillType' not in _condition_context(rules, state, detail, unrelated).event_payload


def test_action_producers_distinguish_skill_kind_from_target_shape():
    from hsr.simulator_v8_clean_core.core.model import ActionCommand, TargetResolution
    from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR
    from hsr.simulator_v8_clean_core.systems.ability import _event_payload
    from hsr.simulator_v8_clean_core.systems.trigger import _condition_event_payload

    source = IRSource('fixture', 'fixture', 'action-kind')
    command = ActionCommand('owner', 'action', 1, ('target',))
    targets = TargetResolution(('target',), ('target',), ('target',))
    for attack_type, expected in [('Normal', 'Normal'), ('BPSkill', 'Skill'), ('Ultra', 'Ultra')]:
        action = ActionDefinitionIR('definition', 'action', 1, attack_type, 'SingleAttack', 'Single',
                                    0, 0, 0, 0, (), (), (), 'Quantum', source)
        assert _event_payload(command, action, 'target', targets)['SkillType'] == expected
        assert _condition_event_payload(command=command, action_definition=action,
            primary_target='target', canonical_window='after_attack', tbgd_event='OnAfterAttack')['SkillType'] == expected


def test_replacement_preserves_produced_observer_notification_identity():
    from hsr.simulator_v8_clean_core.tests.test_status_control_resistance import _source_case, _state
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem

    rules, effect, *_ = _source_case()
    system, reducer, state = StatusSystem(rules), MutationReducer(), _state()
    first = system.apply_add_modifier(state, effect, caster_id='holder', source_id='first',
                                     dynamic_values={'1153510288': .7})
    assert first.ok
    state = reducer.apply_all(state, first.mutations)
    notification = next(e for e in first.events if e.window == 'OnModifierAdd')
    replaced = system.apply_add_modifier(state, effect, caster_id='holder', source_id='second',
                                        dynamic_values={'1153510288': .7})
    assert replaced.ok
    state = reducer.apply_all(state, replaced.mutations)
    fact = notification.status_lifecycle_fact
    assert fact.matches_event(notification) and not fact.matches_state(state)
    callback = StatusCallbackIR('observer', 'observer', 'OnModifierAdd', (), IRSource('fixture', 'fixture', 'observer'),
        (0, 0), source_mode='mainline_avatar_ability', coverage_status='executable', admission_status='executable')
    consumer = StatusCallbackSystem(rules)
    consumer._execute_formal_callback = lambda state, *args, **kwargs: StatusCallbackExecutionResult(True, state)
    assert consumer._execute_callback(state, callback, {}, notification, None, None, None).ok
    altered = replace(notification, event_id='different-event')
    assert not consumer._execute_callback(state, callback, {}, altered, None, None, None).ok


def test_nested_lifecycle_event_has_one_identity_and_keeps_callback_rng():
    rules = RuleBook(CanonicalIR("nested-status-lifecycle-check"))
    dispatch = EventDispatchSystem(rules, EffectRegistry())
    state = BattleState(units={"owner": UnitState("owner", "ally", "fixture:owner")})
    parent = GameEvent(
        "status.lifecycle", source_id="owner", target_id="owner", window="OnCreate",
        event_id="parent", payload={"callback_event": "OnCreate", "lifecycle_operation": "add",
                                    "modifier_name": "M", "status_instance_id": "s", "mutation_event_depth": 1},
    )
    child = GameEvent(
        "status.lifecycle", source_id="owner", target_id="owner", window="OnStack",
        event_id="child", payload={"callback_event": "OnStack", "lifecycle_operation": "add",
                                   "modifier_name": "M", "status_instance_id": "s"},
    )
    callback = StatusCallbackIR(
        "callback", "M", "OnCreate", (), IRSource("fixture", "fixture", "M"), (0, 0),
        coverage_status="executable", admission_status="executable",
    )
    match = ListenerMatch(
        "status_callback", "status_local", "OnCreate", "owner", "M", callback,
        status_detail={"owner_id": "owner", "modifier_name": "M", "instance_id": "s"},
    )
    dispatch._resolve_listener_matches = lambda state, *, event, **kwargs: (
        (match,) if event.event_id == "parent" else ()
    )
    dispatch.status_callbacks = SimpleNamespace(execute=lambda state, **kwargs: StatusCallbackExecutionResult(
        True, state, events=(child,), rng_events=(RNGEvent("fixture", "fixture", 1, event_id="rng:1"),),
    ))

    result = dispatch.dispatch_event(state, event=parent)
    assert not result.errors
    assert [event.to_json()["event_id"] for event in result.events] == ["parent", "child"]
    assert [event.to_json()["event_id"] for event in result.rng_events] == ["rng:1"]
    canonical = _dedupe_events(parent, child, *result.events,
                               event_normalizations=result.event_normalizations)
    assert len(canonical) == 2 and canonical[1].payload['mutation_event_depth'] == 2
    for invalid_depth in (0, -1, True, MAX_CALLBACK_EMITTED_EVENT_DEPTH + 1):
        invalid = replace(child, payload={**child.payload, 'mutation_event_depth': invalid_depth})
        try:
            _dedupe_events(child, event_normalizations=(EventNormalization(child, invalid, 'mutation_event_depth'),))
        except _EventIdentityConflict:
            continue
        raise AssertionError('invalid callback depth admitted')
