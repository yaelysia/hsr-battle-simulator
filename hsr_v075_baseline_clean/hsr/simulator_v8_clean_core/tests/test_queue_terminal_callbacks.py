"""One small queue transaction check; no content compilation or full battle."""
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, TargetResolution, UnitState
from hsr.simulator_v8_clean_core.core.transition_outcome import ExecutionNodeResult
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, QueueResolutionIR, StatusCallbackIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskExecutionResult
from hsr.simulator_v8_clean_core.systems.queue import QueueEntry
from hsr.simulator_v8_clean_core.systems.scheduler import CombatScheduler
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering


def test_queue_finish_and_abort_use_distinct_global_callbacks_and_selected_targets(monkeypatch):
    source = IRSource('Config/ConfigGlobalModifier/_queue_terminal_fixture.json', 'ValidationSynthetic', 'queue',
                      {'negative_or_baseline_fixture': True})
    baseline = RuleBook(CanonicalIR('queue-terminal', queue_resolutions=(QueueResolutionIR(
        'resolution', 'intent', 'ability', 'standalone_ability_graph',
        {'standalone_ability_graph_id': 'graph', 'executable_task_ids': ['task']},
        source, coverage_status='executable',
    ),)))
    lowerer = TBGDLowering(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main')
    callbacks, tasks, conditions, effects = [], [], [], []
    for index, event in enumerate(('OnListenInsertAbilityFinish', 'OnListenInsertAbilityAbort',
                                   'OnListenInsertAbilityStart')):
        callback_id = f'queue:listener:{index}'
        # Like the real listener, the observer is a selected target, not the actor.
        raw = {'$type': 'RPG.GameCore.PredicateTaskList', 'Predicate': {
            '$type': 'RPG.GameCore.ByAnd', 'PredicateList': [
                {'$type': 'RPG.GameCore.ByNot', 'Predicate': {
                    '$type': 'RPG.GameCore.ByTargetListIntersects',
                    'FirstTargetType': {'$type': 'RPG.GameCore.TargetFetchParamEntity'},
                    'SecondTargetType': {'$type': 'RPG.GameCore.TargetFetchCaster'},
                }},
                {'$type': 'RPG.GameCore.ByTargetListIntersects',
                 'FirstTargetType': {'$type': 'RPG.GameCore.TargetFetchParamEntityList'},
                 'SecondTargetType': {'$type': 'RPG.GameCore.TargetFetchCaster'}},
            ]}, 'SuccessTaskList': [{'$type': 'RPG.GameCore.SetEnergyBarState',
                'BarType': 1, 'CurrentCount': {'IsDynamic': False, 'FixedValue': {'Value': index + 1}}}],
            'FailedTaskList': []}
        lowered = lowerer._lower_status_callback_tasks(
            [raw], relative=source.source_path, map_name='Modifiers', modifier_name='observer',
            callback_id=callback_id, event=event, callback_index=index,
            task_list_json_path=f'$.callbacks[{index}]', queue_priority_lookup={},
        )
        assert all(task.coverage_status == 'executable' for task in lowered.status_callback_tasks), [
            task.blocked_reason for task in lowered.status_callback_tasks]
        callbacks.append(StatusCallbackIR(
            callback_id, 'observer', event, tuple(task.task_id for task in lowered.status_callback_tasks),
            source, (0, index), coverage_status='executable', admission_status='executable',
            scope_kind='global_listener', source_mode='mainline_global_modifier',
        ))
        tasks.extend(lowered.status_callback_tasks)
        effects.extend(lowered.effects)
        conditions.extend(lowered.conditions)
    rules = RuleBook(replace(baseline.ir, status_callbacks=tuple(callbacks),
                            status_callback_tasks=tuple(tasks), effects=(*baseline.ir.effects, *effects),
                            conditions=(*baseline.ir.conditions, *conditions)))
    entry = QueueEntry('entry', 'interrupt_queue', 'turn_insert_ability', 'intent',
        'ally:actor', 'ability', ('enemy:target',),
        {'priority_ordering_admitted': True, 'priority_value': 1}, source.to_json(),
        queue_window_id='window', window_family='insert_ability',
        target_resolution={'ok': True, 'target_ids': ['enemy:target']},
        cancel_policy={'abort_behavior_flags': ['STAT_CTRL']}).to_json()
    initial = BattleState(units={name: UnitState(name, side, f'fixture:{name}', hp=100, max_hp=100)
                                  for name, side in [('ally:actor', 'ally'), ('enemy:target', 'enemy')]},
                          queues={'interrupt_queue': (entry,)})
    observer = initial.units['enemy:target']
    detail = {'instance_id': 'observer:1', 'modifier_name': 'observer', 'owner_id': observer.unit_id,
              'caster_id': observer.unit_id, 'source_id': 'queue:fixture', 'status_id': 'modifier:observer',
              'source_trace': source.to_json(), 'lifecycle_state': 'active', 'ability_property_watcher_ids': []}
    initial = replace(initial, units={**initial.units, observer.unit_id: replace(
        observer, hp=10000, max_hp=10000, statuses=('modifier:observer',),
        flags={'status_details': [detail]},
    )})
    scheduler = CombatScheduler(rules)
    # Isolate scheduling transport from ability content execution.
    body_calls = []
    def complete_body(state, **kwargs):
        assert state.units[observer.unit_id].flags['mechanism_bars']['1']['current_count'] == 3
        body_calls.append('complete')
        return AbilityTaskExecutionResult(state, node_results=(
            ExecutionNodeResult('ability_task', 'task', 'complete'),))
    monkeypatch.setattr(scheduler.ability_tasks, '_execute_admitted_queue_standalone', complete_body)
    finished = scheduler._try_queue_drain(initial)
    assert finished is not None
    assert finished.transition.outcome.successor_eligible, finished.transition.outcome.to_json()
    finish_events = [event for event in finished.transition.transaction.events
                     if event.event_type in {'queue.action.before', 'queue.action.after', 'queue.action.abort'}]
    assert [event.event_type for event in finish_events] == ['queue.action.before', 'queue.action.after']
    assert finished.after_state.units[observer.unit_id].flags['mechanism_bars']['1']['current_count'] == 1

    actor = initial.units['ally:actor']
    controlled = replace(initial, units={**initial.units, actor.unit_id: replace(actor, flags={
        'status_details': [{'instance_id': 'control:1', 'behavior_flags': ['STAT_CTRL'],
                            'lifecycle_state': 'active', 'ability_property_watcher_ids': []}],
    })})
    aborted = scheduler._try_queue_drain(controlled)
    assert aborted is not None
    assert aborted.transition.outcome.successor_eligible, aborted.transition.outcome.to_json()
    assert not aborted.after_state.queues['interrupt_queue']
    abort_events = [event for event in aborted.transition.transaction.events
                    if event.event_type in {'queue.action.before', 'queue.action.after', 'queue.action.abort'}]
    assert [event.event_type for event in abort_events] == ['queue.action.abort']
    assert body_calls == ['complete']
    assert aborted.after_state.units[observer.unit_id].flags['mechanism_bars']['1']['current_count'] == 2
    assert scheduler._try_queue_drain(aborted.after_state) is None

    # Automatic group actions submit no IDs; their accepted and impact targets are explicit.
    group_targets = (actor.unit_id, observer.unit_id)
    group_entry = {**entry, 'target_ids': [], 'target_resolution': {
        'ok': True, 'actor_id': actor.unit_id, 'submitted_target_ids': [],
        'selected_target_ids': list(group_targets),
    }}
    group_state = replace(initial, queues={'interrupt_queue': (group_entry,)}, units={
        **initial.units, observer.unit_id: replace(initial.units[observer.unit_id], side='ally'),
    })
    command = ActionCommand(actor.unit_id, 'group-action', 1, target_ids=(), source='queue')
    impact = TargetResolution(requested=(), selected=group_targets, impact_group=group_targets,
                              source='action_target_selection_system')
    dequeue = scheduler.queue.dequeue_entry(group_state, 'interrupt_queue', 'entry', 'queue_system')
    after_dequeue = scheduler.reducer.apply_all(group_state, (dequeue,))
    group_finish = scheduler.queue.action_terminal_event(
        after_dequeue, dequeue, completed_command=command, completed_target_resolution=impact,
    )
    assert group_finish.queue_action_terminal_fact.target_ids == group_targets
    group_result = scheduler.event_dispatcher.dispatch_event(after_dequeue, event=group_finish)
    assert not group_result.errors, group_result.errors
    assert group_result.after_state.units[observer.unit_id].flags['mechanism_bars']['1']['current_count'] == 1
    group_controlled = replace(group_state, units={
        **group_state.units, actor.unit_id: controlled.units[actor.unit_id],
    })
    group_abort = scheduler._try_queue_drain(group_controlled)
    assert group_abort is not None and group_abort.transition.outcome.successor_eligible
    group_abort_event = next(event for event in group_abort.transition.transaction.events
                             if event.event_type == 'queue.action.abort')
    assert group_abort_event.queue_action_terminal_fact.target_ids == group_targets
    assert not any(event.event_type == 'queue.action.before'
                   for event in group_abort.transition.transaction.events)
    assert group_abort.after_state.units[observer.unit_id].flags['mechanism_bars']['1']['current_count'] == 2

    malformed = replace(initial, queues={'interrupt_queue': ({**entry, 'priority_source': {}},)})
    invalid = scheduler._try_queue_drain(malformed)
    assert invalid is not None and not invalid.transition.outcome.successor_eligible
    assert invalid.after_state == malformed and not invalid.transition.transaction.mutations
    assert not any(event.event_type in {'queue.action.before', 'queue.action.abort', 'queue.action.after'}
                   for event in invalid.transition.transaction.events)
    blocked_rules = RuleBook(replace(rules.ir, status_callbacks=tuple(
        replace(callback, admission_status='blocked', blocking_dependency='fixture_listener_unavailable')
        for callback in callbacks)))
    rejected = CombatScheduler(blocked_rules)._try_queue_drain(controlled)
    assert rejected is not None
    assert rejected.after_state == controlled and not rejected.transition.transaction.mutations

    # A missing implementation must remain visible; it is not a gameplay cancel.
    def blocked_body(state, **kwargs):
        assert state.units[observer.unit_id].flags['mechanism_bars']['1']['current_count'] == 3
        body_calls.append('blocked')
        return AbilityTaskExecutionResult(state, node_results=(
            ExecutionNodeResult('ability_task', 'task', 'blocked', reason_code='fixture_formula_missing'),))
    monkeypatch.setattr(scheduler.ability_tasks, '_execute_admitted_queue_standalone', blocked_body)
    for _ in range(2):
        blocked = scheduler._try_queue_drain(initial)
        assert blocked is not None and not blocked.transition.outcome.successor_eligible
        assert blocked.after_state == initial
        assert not blocked.transition.transaction.mutations and not blocked.transition.rng_events
        assert any('fixture_formula_missing' in reason for reason in blocked.transition.outcome.reason_codes)
        assert tuple(event.event_type for event in blocked.transition.transaction.events) == (
            'scheduler.blocked', 'queue.drain.blocked')
        assert all(event.process_only for event in blocked.transition.transaction.events)
    assert body_calls == ['complete', 'blocked', 'blocked']
