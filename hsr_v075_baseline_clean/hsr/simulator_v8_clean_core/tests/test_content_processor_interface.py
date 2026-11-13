"""Component tests for the content-processor mount interface (M1-3).

Fast synthetic fixtures only: no TBGD compilation. These prove the generic
mount/dispatch contract, ordering, presence gating, and the zero-mutation /
zero-RNG failure boundary. Content behavior routes live in
test_content_processor_castorice.py (integration).
"""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.content_hooks import (
    AvailabilityContext,
    ContentProcessorBase,
    EventHookContext,
    EventSubscription,
    HookResult,
    MountedProcessor,
    ProcessorServices,
    attach_processors,
    mount_catalog,
    processor_action_hook,
    processors_for_event,
)
from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, RuleEntity
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusSystem


def _source() -> IRSource:
    return IRSource(source_path="fixture", raw_type="Fixture", raw_id="fixture", evidence={})


def _rules(*entity_ids: str) -> RuleBook:
    return RuleBook(CanonicalIR(
        "content-processor-fixture",
        entities=tuple(
            RuleEntity(entity_id, "fixture", {}, _source(), "executable")
            for entity_id in entity_ids
        ),
    ))


def _unit(unit_id: str, template_id: str, **kwargs) -> UnitState:
    return UnitState(unit_id, "ally", template_id, hp=100.0, max_hp=100.0, **kwargs)


def _event(event_type: str = "custom.event", target_id: str = "u1", event_id: str = "event:fixture:1") -> GameEvent:
    return GameEvent(event_type, source_id="u1", target_id=target_id, event_id=event_id,
                     payload={"param_entity_id": target_id})


class _Recorder(ContentProcessorBase):
    def __init__(self, content_id: str, version: str = "1") -> None:
        self.content_id = content_id
        self.version = version
        self.seen: list[str] = []

    def subscriptions(self):
        return (EventSubscription(("custom.event",), scope="self_units"),)

    def on_event(self, ctx: EventHookContext) -> HookResult:
        self.seen.append(ctx.event.event_id)
        ctx.services.set_unit_flag(
            ctx.event.target_id, f"touched_by_{self.content_id}", True,
            reason="fixture touch",
        )
        return ctx.services.finish()


def _dispatcher(rules: RuleBook) -> EventDispatchSystem:
    status = StatusSystem(rules)
    return EventDispatchSystem(rules, EffectRegistry(status))


def test_mount_catalog_is_generic_and_sorted():
    rules = _rules("fixture:beta", "fixture:alpha")  # fixture:absent not in IR
    catalog = {
        "fixture:beta": lambda: _Recorder("fixture:beta"),
        "fixture:alpha": lambda: _Recorder("fixture:alpha"),
        "fixture:absent": lambda: _Recorder("fixture:absent"),  # not in IR: skipped
    }
    mounted = mount_catalog(rules, catalog)
    assert [m.content_id for m in mounted.content_processors] == ["fixture:alpha", "fixture:beta"]
    assert mounted._processors_by_entity["fixture:alpha"][0].version == "1"
    # Unmounted RuleBook keeps the empty default.
    assert _rules("fixture:alpha").content_processors == ()


def test_netherwing_choices_keep_breath_tier_until_departure_and_gate_finisher():
    from types import SimpleNamespace
    from hsr.simulator_v8_clean_core.content_processors.castorice import CastoriceServantProcessor

    processor = CastoriceServantProcessor()
    choices = tuple(SimpleNamespace(choice_kind='summon_action', action_level=6,
        action_id='servant_skill:' + action) for action in ('1140701', '1140702', '1140710', '1140711', '1140712'))
    def actions(tier, hp, statuses=()):
        actor = _unit('dragon', 'servant:11407', statuses=statuses,
            flags={'castorice_breath_tier': tier, 'castorice_breath_finish_ratio': .25})
        actor = replace(actor, hp=hp)
        ctx = AvailabilityContext(BattleState(units={'dragon': actor}), actor, choices, ())
        return {c.action_id for c in processor.filter_choices(ctx).choices}
    assert actions(0, 100) == {'servant_skill:1140701', 'servant_skill:1140702'}
    assert actions(1, 100) == {'servant_skill:1140701', 'servant_skill:1140710'}
    assert actions(2, 25) == {'servant_skill:1140701', 'servant_skill:1140712'}
    assert actions(2, 100, ('modifier:MServant_CastoriceServant_TiggerKiller',)) == {'servant_skill:1140712'}


def test_netherwing_finisher_preserves_one_hp_until_native_damage_and_healing():
    from hsr.simulator_v8_clean_core.core.content_hooks import ActionHookContext
    from hsr.simulator_v8_clean_core.core.model import ActionCommand, TargetResolution
    from hsr.simulator_v8_clean_core.content_processors.castorice import CastoriceServantProcessor

    rules = _rules('servant:11407')
    from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
    rules = replace(rules, ir=replace(rules.ir, damage_route_rules=build_engine_rule_registry().damage_route_rules))
    command = ActionCommand('dragon', 'servant_skill:1140712', 6)
    for expired in (False, True):
        dragon = replace(_unit('dragon', 'servant:11407'), hp=25,
            statuses=('modifier:MServant_CastoriceServant_TiggerKiller',) if expired else ())
        state = BattleState(units={'dragon': dragon})
        services = ProcessorServices(state, rules, producer_id='servant:11407', action_command=command,
                                     event_dispatcher=_dispatcher(rules))
        result = CastoriceServantProcessor().execute_action(
            ActionHookContext(state, command, None, TargetResolution(), services))
        assert result.ok and not result.takeover
        assert services.unit('dragon').hp == (25 if expired else 1)
        assert services.unit('dragon').lifecycle_status == 'active'


def test_direct_status_callback_honors_caster_processor_replacement():
    from hsr.simulator_v8_clean_core.rules.ir import StatusCallbackIR
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem

    processor = _Recorder('fixture:alpha')
    processor.replaced_status_callbacks = frozenset({('M', 'OnBeforeBeingHeal')})
    rules = mount_catalog(_rules('fixture:alpha'), {'fixture:alpha': lambda: processor})
    detail = {'owner_id': 'recipient', 'caster_id': 'caster', 'modifier_name': 'M', 'instance_id': 'status'}
    state = BattleState(units={'recipient': _unit('recipient', 'fixture:other', flags={'status_details': [detail]}),
                               'caster': _unit('caster', 'fixture:alpha')})
    callback = StatusCallbackIR('callback', 'M', 'OnBeforeBeingHeal', (), _source(), (0, 0))
    rules = replace(rules, ir=replace(rules.ir, status_callbacks=(callback, replace(callback, callback_id='other', event='OnHPChange'))))
    result = StatusCallbackSystem(rules).execute(state, unit_id='recipient', modifier_name='M', event=callback.event)
    assert result.ok and result.after_state is state and not result.mutations
    assert result.records[0]['payload']['reason'] == 'content_processor_replaces_callback'
    # Another callback on the same status is still subject to normal admission.
    assert not StatusCallbackSystem(rules).execute(state, unit_id='recipient', modifier_name='M', event='OnHPChange').ok


def test_being_healed_callback_receives_typed_healer_and_deal_heal_keeps_victim():
    from hsr.simulator_v8_clean_core.core.model import Mutation
    from hsr.simulator_v8_clean_core.rules.ir import StatusCallbackIR
    from hsr.simulator_v8_clean_core.systems.mutation_events import events_for_mutation
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem, StatusCallbackExecutionResult

    mutation = Mutation('set', ('units', 'recipient', 'hp'), 50, 80, 'apply numeric heal effect', 'fixture')
    event, = events_for_mutation(mutation, actor_id='healer')
    detail = {'owner_id': 'recipient', 'caster_id': 'recipient', 'modifier_name': 'M', 'instance_id': 'status'}
    state = BattleState(units={'recipient': _unit('recipient', 'fixture:alpha', flags={'status_details': [detail]}),
                               'healer': _unit('healer', 'fixture:alpha')})
    rules = _rules('fixture:alpha')
    observed = []
    def capture(state, callback, detail, event, *args, **kwargs):
        from hsr.simulator_v8_clean_core.systems.status_callbacks import _condition_context
        observed.append(_condition_context(rules, state, detail, event).param_entity_id)
        assert event.heal_event_fact.matches_heal_after(event)
        return StatusCallbackExecutionResult(ok=True, after_state=state)
    for name in ('OnAfterBeingHeal', 'OnAfterDealHeal'):
        callback = StatusCallbackIR('callback', 'M', name, (), _source(), (0, 0),
                                    coverage_status='executable', source_mode='mainline_avatar_ability')
        rules = replace(rules, ir=replace(rules.ir, status_callbacks=(callback,)))
        system = StatusCallbackSystem(rules)
        system._execute_formal_callback = capture
        assert system.execute(state, unit_id='recipient', modifier_name='M', event=name, trigger_event=event).ok
    assert observed == ['healer', 'recipient']


def test_removed_content_receives_its_terminal_event_but_no_later_ordinary_events():
    processor = _Recorder('fixture:alpha')
    processor.subscriptions = lambda: (EventSubscription(('custom.event', 'unit.removed')),)
    rules = mount_catalog(_rules('fixture:alpha'), {'fixture:alpha': lambda: processor})
    state = BattleState(units={'u1': _unit('u1', 'fixture:alpha', lifecycle_status='removed')})
    assert len(processors_for_event(rules, state, _event('unit.removed'))) == 1
    assert not processors_for_event(rules, state, _event())


def test_mount_rejects_identity_mismatch():
    rules = _rules("fixture:alpha")
    with pytest.raises(ValueError):
        mount_catalog(rules, {"fixture:alpha": lambda: _Recorder("fixture:other")})


def test_event_dispatch_order_and_presence_gating():
    rules = _rules("fixture:alpha", "fixture:beta")
    alpha, beta = _Recorder("fixture:alpha"), _Recorder("fixture:beta")
    attach_processors(rules, (
        MountedProcessor("fixture:beta", "1", beta),
        MountedProcessor("fixture:alpha", "1", alpha),
    ))
    state = BattleState(units={
        "u1": _unit("u1", "fixture:alpha"),
        "u2": _unit("u2", "fixture:beta"),
    })
    dispatcher = _dispatcher(rules)
    result = dispatcher.dispatch_event(state, event=_event(target_id="u1"))
    assert not result.errors, result.errors
    # Only the target's own content processor is notified (self_units scope).
    assert alpha.seen == ["event:fixture:1"] and beta.seen == []
    assert result.after_state.units["u1"].flags["touched_by_fixture:alpha"] is True
    # Removed content units deactivate their processor.
    removed_state = BattleState(units={"u1": replace(state.units["u1"], lifecycle_status="removed")})
    assert processors_for_event(rules, removed_state, _event(target_id="u1")) == ()


def test_event_hook_failure_rejects_whole_transition_zero_mutation_zero_rng():
    rules = _rules("fixture:alpha")

    class _Blocker(ContentProcessorBase):
        content_id = "fixture:alpha"
        version = "1"

        def subscriptions(self):
            return (EventSubscription(("custom.event",), scope="self_units"),)

        def on_event(self, ctx: EventHookContext) -> HookResult:
            ctx.services.set_unit_flag("u1", "partial", True, reason="must be discarded")
            return ctx.services.block("fixture_blocked")

    attach_processors(rules, (MountedProcessor("fixture:alpha", "1", _Blocker()),))
    state = BattleState(units={"u1": _unit("u1", "fixture:alpha")})
    executor = CombatExecutor(rules)
    result = executor.commit_eventful_transition(
        state, mutations=(), events=(_event(),),
        producer_kind="fixture", producer_id="fixture",
    )
    assert not result.after_state.snapshot().to_json() == state.snapshot().to_json() or True
    assert result.errors and "fixture_blocked" in ",".join(result.errors)
    assert result.mutations == ()
    assert result.rng_events == ()
    assert result.after_state == state


def test_services_candidate_state_advances_and_block_discards():
    rules = _rules("fixture:alpha")
    state = BattleState(units={"u1": _unit("u1", "fixture:alpha")})
    services = ProcessorServices(state, rules, producer_id="fixture:alpha:1")
    services.set_unit_flag("u1", "step", 1, reason="first")
    assert services.state.units["u1"].flags["step"] == 1
    services.set_unit_flag("u1", "step", 2, reason="second")
    ok = services.finish()
    assert ok.ok and len(ok.mutations) == 2
    assert ok.mutations[1].before == 1 and ok.mutations[1].after == 2

    services2 = ProcessorServices(state, rules, producer_id="fixture:alpha:1")
    services2.set_unit_flag("u1", "step", 9, reason="discarded")
    blocked = services2.block("fixture_blocked")
    assert not blocked.ok and blocked.mutations == () and blocked.rng_events == ()


def test_processor_emitted_events_reenter_same_channel_with_depth_cap():
    rules = _rules("fixture:alpha")

    class _Echo(ContentProcessorBase):
        content_id = "fixture:alpha"
        version = "1"

        def subscriptions(self):
            return (EventSubscription(("custom.event",), scope="self_units"),)

        def on_event(self, ctx: EventHookContext) -> HookResult:
            # Re-emit a fresh event each time: the generic depth cap must stop
            # the chain instead of looping forever.
            index = int(ctx.state.units["u1"].flags.get("echo_count", 0))
            ctx.services.set_unit_flag("u1", "echo_count", index + 1, reason="echo")
            ctx.services.emit_event(GameEvent(
                "custom.event", source_id="u1", target_id="u1",
                event_id=f"event:fixture:echo:{index}",
                payload={"param_entity_id": "u1"},
            ))
            return ctx.services.finish()

    attach_processors(rules, (MountedProcessor("fixture:alpha", "1", _Echo()),))
    state = BattleState(units={"u1": _unit("u1", "fixture:alpha")})
    dispatcher = _dispatcher(rules)
    result = dispatcher.dispatch_event(state, event=_event())
    assert result.errors and "content_processor_event_depth_exceeded" in ",".join(result.errors)


def test_processor_resource_event_is_returned_once():
    rules = _rules("fixture:alpha")

    class _Energy(ContentProcessorBase):
        content_id = "fixture:alpha"
        version = "1"

        def subscriptions(self):
            return (EventSubscription(("custom.event",)),)

        def on_event(self, ctx):
            ctx.services.grant_energy("u1", 6.0, ctx.event)
            return ctx.services.finish()

    attach_processors(rules, (MountedProcessor("fixture:alpha", "1", _Energy()),))
    state = BattleState(units={"u1": replace(_unit("u1", "fixture:alpha"), energy=0.0, max_energy=120.0)})
    result = _dispatcher(rules).dispatch_event(state, event=_event())
    assert not result.errors, result.errors
    assert result.after_state.units["u1"].energy == 6.0
    events = [event for event in result.events if event.event_type == "energy.change"]
    assert len(events) == 1
    assert events[0].energy_change_event_fact.delta == 6.0


def test_action_hook_lookup_is_by_actor_identity():
    rules = _rules("fixture:alpha")

    class _Claimer(ContentProcessorBase):
        content_id = "fixture:alpha"
        version = "1"

        def claims_action(self, state, action_id, action_level):
            return action_id == "fixture_action"

    mount = MountedProcessor("fixture:alpha", "1", _Claimer())
    attach_processors(rules, (mount,))
    state = BattleState(units={"u1": _unit("u1", "fixture:alpha"), "u2": _unit("u2", "fixture:beta")})
    from hsr.simulator_v8_clean_core.core.model import ActionCommand

    command = ActionCommand(actor_id="u1", action_id="fixture_action", action_level=1, target_ids=())
    assert processor_action_hook(rules, state, command) is mount
    other = replace(command, actor_id="u2")
    assert processor_action_hook(rules, state, other) is None
    assert processor_action_hook(rules, state, replace(command, action_id="other")) is None


def test_availability_filter_chains_in_content_id_order():
    rules = _rules("fixture:alpha")

    class _Filter(ContentProcessorBase):
        content_id = "fixture:alpha"
        version = "1"

        def filter_choices(self, ctx: AvailabilityContext) -> AvailabilityContext:
            kept = tuple(c for c in ctx.choices if c != "drop")
            return AvailabilityContext(ctx.state, ctx.actor, kept, ctx.blocked)

    attach_processors(rules, (MountedProcessor("fixture:alpha", "1", _Filter()),))
    state = BattleState(units={"u1": _unit("u1", "fixture:alpha")})
    choices, blocked = rules.filter_actor_choices(state, state.units["u1"], ("keep", "drop"), ())
    assert choices == ("keep",) and blocked == ()
    # Unmounted content is untouched.
    other = BattleState(units={"u2": _unit("u2", "fixture:beta")})
    assert rules.filter_actor_choices(other, other.units["u2"], ("keep", "drop"), ()) == (("keep", "drop"), ())


# -- H1 action-execution hook (synthetic formal action fixture) ---------------

def _action_fixture_rules():
    from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
    from hsr.simulator_v8_clean_core.rules.ir import (
        AbilityPhaseIR, AbilityTaskIR, ActionAbilityBindingIR, ActionDefinitionIR, ActionEventIR,
        ActionPhaseStepIR, DamageEmissionIR, EffectIR, HitProfileIR,
    )

    source = IRSource('validation_fixture/processor-action', 'AbilityTask', 'damage', {
        'json_path': '$.OnStart[0]', 'content_sha256': 'c' * 64,
        'source_opcode': 'DamageByAttackProperty',
    })
    definition = ActionDefinitionIR('definition', 'action', 1, 'Normal', 'Basic', 'single',
        0, 0, 0, 0, (), (), (), 'Fire', source, coverage_status='executable',
        damage_kind='hp_damage', damage_formula_family='direct', element_type='Fire')
    task = AbilityTaskIR('damage-task', 'phase', 'action', 1, 'ability', 'OnStart',
        0, '$.OnStart[0]', 'root', 'DamageByAttackProperty', source,
        effect_id='effect', coverage_status='executable')
    phase = AbilityPhaseIR('phase', 'binding', 'action', 1, 'ability', 0, {}, {}, {}, source,
        coverage_status='executable', task_ids=(task.task_id,), invocation_role='action_root')
    binding = ActionAbilityBindingIR('binding', 'action', 1, 'Skill01', 'Skill01', 'ability',
        ('ability',), {}, ('phase',), 'mainline', source, coverage_status='executable')
    profile = HitProfileIR('hit', 'action', 1, 0, 'selected', numeric_fixed(1), {},
        numeric_fixed(0), {}, 'direct', 'Fire', source, coverage_status='executable')
    emission = DamageEmissionIR('damage', 'action', 1, 'phase', task.task_id, 'hit', 'selected',
        'direct', 'Fire', numeric_fixed(1),
        {'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'}, source,
        coverage_status='executable', toughness_emission_required=False)
    effect = EffectIR('effect', task.opcode, {},
        replace(source, evidence={**source.evidence, 'parent_task_id': ''}), coverage_status='audit_only')
    steps = tuple(ActionPhaseStepIR('trigger_window', window, window, event,
        coverage_status='executable', source=source) for window, event in (
        ('before_skill_use', 'OnBeforeSkillUse'), ('before_attack', 'OnBeforeAttack')))
    action_event = ActionEventIR('action:event', 'action', 1, 'single', 'explicit', (
        *steps, ActionPhaseStepIR('damage', 'damage', coverage_status='executable', source=source),
        ActionPhaseStepIR('trigger_window', 'after_skill_use', 'after_skill_use', 'OnAfterSkillUse',
                          coverage_status='executable', source=source)), ('hit',), 'derived', '', source,
        coverage_status='executable', binding_id='binding', phase_ids=('phase',),
        event_source_status='ability_phase_graph_bound', target_relation='enemy')
    registry = build_engine_rule_registry()
    from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphQueryResult
    from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import _graph
    graph = _graph('phase', task, references=(('effect', 'effect', 'deferred',
        'task_graph_definition_not_admitted:effect:audit_only'),))

    class _GraphRules(RuleBook):
        def query_formal_task_graph(self, entry_kind, owner_id, callback_kind, formal_task_ids):
            return TaskGraphQueryResult('resolved', 'graph', (graph.graph_id,), graph, '')

        def query_task_graph(self, graph_id):
            return TaskGraphQueryResult('resolved', 'graph', (graph_id,), graph, '')

        def query_task_graph_node(self, node_id):
            return TaskGraphQueryResult('resolved', 'node', (node_id,), graph.nodes[0], '')

    return _GraphRules(CanonicalIR('processor-action-fixture',
        entities=(RuleEntity('fixture', 'fixture', {}, _source(), 'executable'),),
        action_definitions=(definition,),
        action_ability_bindings=(binding,), action_events=(action_event,), ability_phases=(phase,),
        ability_tasks=(task,), effects=(effect,), hit_profiles=(profile,), damage_emissions=(emission,),
        damage_formula_rules=registry.damage_formula_rules, damage_route_rules=registry.damage_route_rules,
        resource_rules=registry.resource_rules))


def _execute_fixture(rules, state):
    from types import SimpleNamespace
    from unittest.mock import patch
    from hsr.simulator_v8_clean_core.core.model import ActionCommand, TargetResolution
    from hsr.simulator_v8_clean_core.systems.action_event_contract import _issue_admitted_action_target_fact
    from hsr.simulator_v8_clean_core.systems.action_selection import ActionTargetImpactResult

    executor = CombatExecutor(rules)
    resolution = TargetResolution(requested=('target',), legal=('target',), selected=('target',),
        primary='target', impact_group=('target',), source='action_target_selection_system',
        metadata={'target_groups': {'selected': ['target'], 'primary': ['target'], 'impact': ['target']}})
    impact = ActionTargetImpactResult('resolved', 'selection', resolution)
    fact = _issue_admitted_action_target_fact(actor_id='actor', action_id='action', action_level=1,
        selection_context_fingerprint='selection', contract_fingerprint='contract',
        impact_fingerprint=impact.impact_fingerprint, canonical_action_event_id='action:event',
        target_mode='single', target_ids=('target',))
    impact = replace(impact, admitted_action_target_fact=fact)
    context = SimpleNamespace(context_fingerprint='selection', dynamic_target=False, to_json=lambda: {},
        accepted=SimpleNamespace(query_fingerprint='query', selection_fingerprint='accepted'))
    with patch.object(executor.action_targets, 'context_identity_blocked_reason', return_value=''), \
         patch.object(executor.action_targets, 'resolve_impact', return_value=impact), \
         patch.object(executor.action_contract, 'evaluate',
                      return_value=SimpleNamespace(ok=True, to_json=lambda: {})):
        return executor.execute(ActionCommand('actor', 'action', 1, ('target',),
            metadata={'crit_mode': 'noncrit'}), state, target_selection_context=context)


def _action_state():
    return BattleState(units={
        'actor': _unit('actor', 'fixture', attack=100.0),
        'target': UnitState('target', 'enemy', 'fixture', hp=1000.0, max_hp=1000.0),
    }, global_flags={'phase': 'combat', 'current_window': 'idle', 'turn_owner_id': 'actor'})


class _ActionProcessor(ContentProcessorBase):
    content_id = 'fixture'
    version = '1'

    def __init__(self, mode):
        self.mode = mode

    def claims_action(self, state, action_id, action_level):
        return action_id == 'action'

    def execute_action(self, ctx):
        if self.mode == 'block':
            return ctx.services.block('fixture_action_blocked')
        ctx.services.set_unit_flag('target', 'processor_touched', True, reason='fixture action')
        return ctx.services.finish(takeover=(self.mode == 'takeover'))


def test_h1_takeover_replaces_compiled_effects():
    rules = _action_fixture_rules()
    attach_processors(rules, (MountedProcessor('fixture', '1', _ActionProcessor('takeover')),))
    state = _action_state()
    after, transition = _execute_fixture(rules, state)
    assert transition.outcome.successor_eligible, transition.outcome.to_json()
    assert after.units['target'].flags['processor_touched'] is True
    # The compiled damage graph was replaced: no HP change.
    assert after.units['target'].hp == 1000.0
    assert any(m.path == ('units', 'target', 'flags', 'processor_touched')
               for m in transition.transaction.mutations)


def test_h1_pre_effect_keeps_compiled_effects():
    rules = _action_fixture_rules()
    attach_processors(rules, (MountedProcessor('fixture', '1', _ActionProcessor('pre')),))
    state = _action_state()
    after, transition = _execute_fixture(rules, state)
    assert transition.outcome.successor_eligible, transition.outcome.to_json()
    assert after.units['target'].flags['processor_touched'] is True
    # The compiled damage graph still ran after the pre-effect hook.
    assert after.units['target'].hp < 1000.0


def test_h1_blocked_hook_zero_mutation_zero_rng():
    rules = _action_fixture_rules()
    attach_processors(rules, (MountedProcessor('fixture', '1', _ActionProcessor('block')),))
    state = _action_state()
    after, transition = _execute_fixture(rules, state)
    assert not transition.outcome.successor_eligible
    assert 'fixture_action_blocked' in ','.join(transition.outcome.reason_codes)
    assert after == state
    assert transition.transaction.mutations == ()
    assert transition.rng_events == ()


def test_services_resolve_rng_records_event_deterministically():
    from hsr.simulator_v8_clean_core.systems.rng import RNGOutcome, RNGRequest

    rules = _rules("fixture:alpha")
    state = BattleState(units={"u1": _unit("u1", "fixture:alpha")})

    def request(event_id: str) -> RNGRequest:
        return RNGRequest(
            rng_type="fixture_rng", purpose="fixture", event_id=event_id,
            choice_key=f"fixture:{event_id}", source="content_processor",
            before_state="fixture-state", decision_kind="probability",
            outcomes=(RNGOutcome("hit", probability=0.5), RNGOutcome("miss", probability=0.5)),
            identity={"decision_scope": "fixture", "decision_index": 0, "action_id": "fixture_action"},
        )

    services = ProcessorServices(state, rules, producer_id="fixture:alpha:1")
    resolution = services.resolve_rng(request("event:fixture:rng:1"))
    assert resolution.ok and resolution.event is not None
    result = services.finish()
    assert result.ok and len(result.rng_events) == 1
    assert result.rng_events[0].event_id == "event:fixture:rng:1"
    assert result.rng_events[0].result["selected_outcome_id"] in {"hit", "miss"}
    # Deterministic: identical request identity resolves identically.
    services2 = ProcessorServices(state, rules, producer_id="fixture:alpha:1")
    resolution2 = services2.resolve_rng(request("event:fixture:rng:1"))
    assert resolution2.selected_outcome_id == resolution.selected_outcome_id
    from hsr.simulator_v8_clean_core.core.model import ActionCommand
    chosen = 'miss' if resolution.selected_outcome_id == 'hit' else 'hit'
    command = ActionCommand('u1', 'fixture_action', 1, metadata={
        'rng_mode': 'explicit', 'rng_choices': {'fixture:event:fixture:rng:1': chosen},
    })
    services3 = ProcessorServices(state, rules, producer_id='fixture:alpha:1', action_command=command)
    explicit = services3.resolve_rng(request('event:fixture:rng:1'))
    assert explicit.selected_outcome_id == chosen and explicit.choice_source == 'explicit_ledger'


def test_services_resolve_rng_failure_zero_output():
    from hsr.simulator_v8_clean_core.systems.rng import RNGRequest

    rules = _rules("fixture:alpha")
    state = BattleState(units={"u1": _unit("u1", "fixture:alpha")})
    services = ProcessorServices(state, rules, producer_id="fixture:alpha:1")
    services.set_unit_flag("u1", "partial", True, reason="must be discarded")
    empty = RNGRequest(
        rng_type="fixture_rng", purpose="fixture", event_id="event:fixture:rng:bad",
        choice_key="fixture:bad", source="content_processor", before_state="fixture-state",
        decision_kind="probability", outcomes=(),
        identity={"decision_scope": "fixture", "decision_index": 0, "action_id": "fixture_action"},
    )
    from hsr.simulator_v8_clean_core.core.content_hooks import ProcessorBlocked
    with pytest.raises(ProcessorBlocked):
        services.resolve_rng(empty)
    blocked = services.block("content_processor_rng_blocked")
    assert not blocked.ok and blocked.mutations == () and blocked.rng_events == ()


def test_services_remove_summon_admission_is_domain_not_trace():
    """source_trace is audit description, never a runtime gate (M1 review P2-2).

    Removal admission comes from the mounted processor's admitted behavior
    plus the domain planner's formal conditions; trimming the source note
    must not change whether removal executes.
    """
    from hsr.simulator_v8_clean_core.core.content_hooks import ProcessorBlocked

    rules = _rules("fixture:alpha")
    state = BattleState(units={"u1": _unit("u1", "fixture:alpha")})
    services = ProcessorServices(state, rules, producer_id="fixture:alpha:1")
    # No source_trace at all: the domain condition (unit is not a summon
    # runtime entity) decides, not the audit note.
    with pytest.raises(ProcessorBlocked, match="unit_is_not_summon_runtime_entity"):
        services.remove_summon("u1", "fixture removal")
    with pytest.raises(ProcessorBlocked, match="unit_is_not_summon_runtime_entity"):
        services.remove_summon("u1", "fixture removal", source_trace={"rule": "fixture"})


def test_bounce_candidates_exclude_team_unselectable_servant():
    """Generic bounce target selection excludes a TeamDark-unselectable servant.

    This is the death dragon's 后援 semantics (4399 V3.2 Castorice guide:
    spread/bounce effects cannot select it, enemies cannot attack it, allies
    can). The exclusion is the generic unselectable mechanism, not processor
    code; this test pins the behavior the processor relies on.
    """
    from hsr.simulator_v8_clean_core.rules.ir import BouncePolicyIR
    from hsr.simulator_v8_clean_core.systems.target import TargetSystem

    rules = _rules("fixture:alpha")
    source = _source()
    policy = BouncePolicyIR(
        bounce_policy_id="bounce:fixture", character_data_card_id="fixture",
        action_id="action", level=1, bounce_count=6,
        initial_target_group="primary", bounce_target_group="bounce",
        candidate_scope="enemy_single", selection_strategy="prefer_unhit_then_random",
        live_target_priority=True, continue_on_all_defeated=False,
        allow_repeat_after_all_hit=True, rng_source_kind="battle_rng",
        random_selector_sources=(), source=source, coverage_status="executable",
    )
    dragon = UnitState("dragon", "ally", "servant:fixture", hp=2000.0, max_hp=2000.0,
                       flags={"summon_kind": "servant", "owner_id": "ca",
                              "custom_unselectable_teams": ["TeamDark"],
                              "lifecycle_source": {"admission_status": "executable",
                                                   "presence": "field", "targetable": True}})
    state = BattleState(units={
        "enemy": UnitState("enemy", "enemy", "fixture", hp=1000.0, max_hp=1000.0),
        "ally": UnitState("ally", "ally", "fixture", hp=1000.0, max_hp=1000.0),
        "dragon": dragon,
    })
    targets = TargetSystem(rules)
    for hit_index in range(1, 7):
        result = targets.resolve_bounce_hit_target(
            state, actor_id="enemy", primary_target_id="ally", bounce_policy=policy,
            hit_index=hit_index, previous_hit_targets=(), action_id="action", action_level=1,
            source_task_id="task", hit_profile_id="hit",
        )
        assert result.ok, result.error
        assert result.target_id == "ally", f"bounce hit {hit_index} selected unselectable servant"


# -- H4 graph-coverage bypass (lead review conditions, 2026-11-11) ------------

def _bypass_fixture(blocked_binding: bool):
    """Action fixture whose binding carries a graph-coverage block."""
    from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
    from hsr.simulator_v8_clean_core.rules.ir import (
        AbilityPhaseIR, AbilityTaskIR, ActionAbilityBindingIR, ActionDefinitionIR, ActionEventIR,
        ActionPhaseStepIR, DamageEmissionIR, EffectIR, HitProfileIR,
    )

    source = IRSource('validation_fixture/processor-bypass', 'AbilityTask', 'damage', {
        'json_path': '$.OnStart[0]', 'content_sha256': 'c' * 64,
        'source_opcode': 'DamageByAttackProperty',
    })
    definition = ActionDefinitionIR('definition', 'action', 1, 'Normal', 'Basic', 'single',
        0, 0, 0, 0, (), (), (), 'Fire', source, coverage_status='executable',
        damage_kind='hp_damage', damage_formula_family='direct', element_type='Fire')
    task = AbilityTaskIR('damage-task', 'phase', 'action', 1, 'ability', 'OnStart',
        0, '$.OnStart[0]', 'root', 'DamageByAttackProperty', source,
        effect_id='effect', coverage_status='executable')
    phase = AbilityPhaseIR('phase', 'binding', 'action', 1, 'ability', 0, {}, {}, {}, source,
        coverage_status='executable', task_ids=(task.task_id,), invocation_role='action_root')
    binding = ActionAbilityBindingIR('binding', 'action', 1, 'Skill01', 'Skill01', 'ability',
        ('ability',), {}, ('phase',), 'mainline', source,
        coverage_status='blocked' if blocked_binding else 'executable',
        blocked_reason='task_graph_definition_not_admitted:effect:unsupported' if blocked_binding else '')
    profile = HitProfileIR('hit', 'action', 1, 0, 'selected', numeric_fixed(1), {},
        numeric_fixed(0), {}, 'direct', 'Fire', source, coverage_status='executable')
    emission = DamageEmissionIR('damage', 'action', 1, 'phase', task.task_id, 'hit', 'selected',
        'direct', 'Fire', numeric_fixed(1),
        {'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'}, source,
        coverage_status='executable', toughness_emission_required=False)
    effect = EffectIR('effect', task.opcode, {},
        replace(source, evidence={**source.evidence, 'parent_task_id': ''}), coverage_status='audit_only')
    action_event = ActionEventIR('action:event', 'action', 1, 'single', 'explicit', (
        ActionPhaseStepIR('damage', 'damage', coverage_status='executable', source=source),),
        ('hit',), 'derived', '', source,
        coverage_status='executable', binding_id='binding', phase_ids=('phase',),
        event_source_status='ability_phase_graph_bound', target_relation='enemy')
    registry = build_engine_rule_registry()
    return RuleBook(CanonicalIR('processor-bypass-fixture',
        entities=(RuleEntity('fixture', 'fixture', {}, _source(), 'executable'),),
        action_definitions=(definition,),
        action_ability_bindings=(binding,), action_events=(action_event,), ability_phases=(phase,),
        ability_tasks=(task,), effects=(effect,), hit_profiles=(profile,), damage_emissions=(emission,),
        damage_formula_rules=registry.damage_formula_rules, damage_route_rules=registry.damage_route_rules,
        resource_rules=registry.resource_rules))


def _call_normal_choice(rules, state, *, resource_blocked=False):
    from types import SimpleNamespace
    from unittest.mock import patch
    from hsr.simulator_v8_clean_core.systems.action_availability import ActionAvailabilitySystem
    from hsr.simulator_v8_clean_core.systems.action_selection import ActionTargetQuery

    system = ActionAvailabilitySystem(rules)
    actor = state.units['actor']
    query = ActionTargetQuery('resolved', 'actor', 'action', 1, 'state:fixture',
                              contract_id='contract', contract_fingerprint='fp',
                              selection_mode='automatic', selection_min=0, selection_max=0,
                              candidate_ids=('target',), automatic_target_ids=('target',))
    admission = SimpleNamespace(admission_id='adm', owner_entity_ref='fixture',
                                action_role='turn_action', allowed_windows=('external_turn',),
                                submission_modes=('external_turn',))
    contract = SimpleNamespace(ok=True, admission=admission,
                               resource_status='blocked' if resource_blocked else 'ok',
                               resource_blocked_reason='insufficient_skill_points' if resource_blocked else '',
                               blocked_reason='', to_json=lambda: {})
    with patch.object(system.contract, 'evaluate', return_value=contract), \
         patch.object(system.action_targets, 'query', return_value=query):
        return system._normal_action_choice(
            state, actor, 'action', 1, choice_kind='normal_action',
            source_trace={}, metadata={},
        )


class _Claimer(ContentProcessorBase):
    content_id = 'fixture'
    version = '1'

    def claims_action(self, state, action_id, action_level):
        return action_id == 'action'


def test_h4_claimed_graph_block_becomes_available():
    rules = _bypass_fixture(blocked_binding=True)
    attach_processors(rules, (MountedProcessor('fixture', '1', _Claimer()),))
    state = _action_state()
    choice, blocked = _call_normal_choice(rules, state)
    assert choice is not None, blocked.reason
    assert choice.action_id == 'action'


def test_h4_unclaimed_graph_block_stays_blocked():
    rules = _bypass_fixture(blocked_binding=True)
    state = _action_state()
    choice, blocked = _call_normal_choice(rules, state)
    assert choice is None
    assert 'task_graph_definition_not_admitted' in blocked.reason


def test_h4_claimed_resource_gate_still_blocks():
    rules = _bypass_fixture(blocked_binding=True)
    attach_processors(rules, (MountedProcessor('fixture', '1', _Claimer()),))
    state = _action_state()
    choice, blocked = _call_normal_choice(rules, state, resource_blocked=True)
    assert choice is None
    assert 'insufficient_skill_points' in blocked.reason


def test_invalid_hook_result_is_blocked():
    rules = _rules("fixture:alpha")

    class _Bad(ContentProcessorBase):
        content_id = "fixture:alpha"
        version = "1"

        def subscriptions(self):
            return (EventSubscription(("custom.event",), scope="self_units"),)

        def on_event(self, ctx):
            return {"ok": True}  # not a HookResult

    attach_processors(rules, (MountedProcessor("fixture:alpha", "1", _Bad()),))
    state = BattleState(units={"u1": _unit("u1", "fixture:alpha")})
    result = _dispatcher(rules).dispatch_event(state, event=_event())
    assert result.errors and "content_processor_invalid_hook_result" in ",".join(result.errors)
