"""Processor combat wiring; component handlers are not game-value evidence."""
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from hsr.simulator_v8_clean_core.core.content_hooks import (
    ContentProcessorBase, EventSubscription, MountedProcessor, attach_processors,
)
from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
from hsr.simulator_v8_clean_core.core.model import GameEvent
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSourceFrame
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.toughness import ToughnessPacket
from hsr.simulator_v8_clean_core.tests.test_content_processor_interface import (
    _action_fixture_rules, _action_state, _execute_fixture,
)
from hsr.simulator_v8_clean_core.tests.test_damage_modifier_transport import _case


class _DamageProcessor(ContentProcessorBase):
    content_id = 'fixture'
    version = 'component'

    def __init__(self, modifiers=(), *, deplete=False):
        self.modifiers = modifiers
        self.deplete = deplete

    def claims_action(self, state, action_id, action_level):
        return action_id == 'action'

    def execute_action(self, ctx):
        ctx.services.apply_damage(DamagePacket(
            'actor', 'actor', 'hp_loss', 'hp_loss', amount=5,
            amount_stage='fixed_final', damage_kind='hp_loss'))
        ctx.services.apply_damage(DamagePacket(
            'actor', 'target', 'Normal', 'direct', element_type='Fire',
            scaling_ratio=1,
            scaling_basis={'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'},
            action_definition=ctx.action_definition,
            source_frame=DamageSourceFrame('actor', 'fixture:body', 'effect_damage',
                'fixture:sequence', 'target', can_continue_after_lethal=False),
            metadata={'crit_mode': 'noncrit'}, modifier_contributions=self.modifiers))
        if self.deplete:
            from hsr.simulator_v8_clean_core.systems.rng import RNGOutcome, RNGRequest

            ctx.services.resolve_rng(RNGRequest(
                rng_type='fixture_rng', purpose='rollback', event_id='fixture:before-break',
                choice_key='fixture:before-break', source='content_processor', before_state='fixture-seed',
                decision_kind='probability', outcomes=(RNGOutcome('hit', probability=1),),
                identity={'decision_scope': 'fixture', 'decision_index': 0, 'action_id': 'action'}))
            ctx.services.apply_toughness(ToughnessPacket(
                'actor', 'target', 'fixture:toughness', 'fixture:task', 'fixture:hit',
                'Fire', 1, 'selected', 'executable', {}))
        return ctx.services.finish(takeover=True)


@pytest.mark.parametrize('packet_modifier', ['none', 'same', 'other'])
def test_before_attack_contributions_merge_once_and_do_not_scale_hp_cost(packet_modifier):
    _, produced, _ = _case()
    assert produced.ok and len(produced.damage_modifiers) == 1
    term = produced.damage_modifiers[0]
    own = (() if packet_modifier == 'none' else (term,) if packet_modifier == 'same'
           else (replace(term, modifier=replace(term.modifier, damage_modifier_id='packet:modifier'),
                         value=0.2),))
    processor = _DamageProcessor(own)
    rules = _action_fixture_rules()
    attach_processors(rules, (MountedProcessor('fixture', processor.version, processor),))
    dispatch = EventDispatchSystem.dispatch_action_window_listeners

    def with_modifier(self, state, **kwargs):
        result = dispatch(self, state, **kwargs)
        assert not result.errors
        return (replace(result, damage_modifiers=produced.damage_modifiers)
                if kwargs['event'].event_type == 'action.window.before_attack' else result)

    before = _action_state()
    with patch.object(EventDispatchSystem, 'dispatch_action_window_listeners', with_modifier):
        after, transition = _execute_fixture(rules, before)
    assert transition.outcome.successor_eligible, transition.outcome.reason_codes
    assert before.units['actor'].hp - after.units['actor'].hp == 5
    assert before.units['target'].hp - after.units['target'].hp == pytest.approx(
        130 if packet_modifier == 'other' else 110)


def test_break_failure_discards_the_whole_processor_action():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _lower_status_event_families

    rules = _action_fixture_rules()  # Deliberately no admitted break template.
    rules = type(rules)(replace(rules.ir, status_event_families=tuple(_lower_status_event_families([], []))))
    processor = _DamageProcessor(deplete=True)
    attach_processors(rules, (MountedProcessor('fixture', processor.version, processor),))
    before = _action_state()
    before = replace(before, units={**before.units, 'target': replace(
        before.units['target'], toughness=1, max_toughness=1, flags={'weaknesses': ['Fire']})})
    after, transition = _execute_fixture(rules, before)
    assert not transition.outcome.successor_eligible
    assert 'break_template_missing' in transition.outcome.reason_codes
    assert after == before
    assert not transition.transaction.mutations and not transition.rng_events


@pytest.mark.integration
@pytest.mark.parametrize('hook', ['action', 'event'])
def test_processor_depletion_enters_break_and_dispatches_each_notification_once(hook):
    from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
    from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

    root = Path(__file__).resolve().parents[4]
    scenario = json.loads((Path(__file__).resolve().parents[1]
                          / 'examples/cli/arlan_vs_antimatter.json').read_text())
    rules = build_battle_rulebook(root / 'turnbasedgamedata-main', scenario)

    class Processor(ContentProcessorBase):
        content_id = 'avatar:1008'
        version = 'component'

        def claims_action(self, state, action_id, action_level):
            return action_id == 'avatar_skill:100801'

        def apply(self, ctx):
            target_id = next(uid for uid, unit in ctx.state.units.items() if unit.side == 'enemy')
            emission = next(item for item in rules.toughness_emissions_for_action('avatar_skill:100801', 1)
                            if item.coverage_status == 'executable')
            ctx.services.apply_toughness(ToughnessPacket(
                'arlan', target_id, emission.toughness_emission_id, emission.source_task_id,
                emission.hit_profile_id, 'Thunder', 1, emission.target_group,
                emission.coverage_status, emission.source.to_json()))

        def execute_action(self, ctx):
            self.apply(ctx)
            return ctx.services.finish(takeover=True)

        def subscriptions(self):
            return (EventSubscription(('custom.event', 'toughness.before_hit',
                                       'toughness.hit', 'break.triggered')),)

        def on_event(self, ctx):
            if ctx.event.event_type == 'custom.event':
                self.apply(ctx)
            else:
                key = 'seen:' + ctx.event.event_type
                ctx.services.set_unit_flag('arlan', key,
                    ctx.state.units['arlan'].flags.get(key, 0) + 1, reason='count notifications')
            return ctx.services.finish()

    processor = Processor()
    attach_processors(rules, (MountedProcessor(processor.content_id, processor.version, processor),))
    session = BattleSession(rules, scenario)
    assert session.advance().ready
    target_id = next(uid for uid, unit in session.state.units.items() if unit.side == 'enemy')
    before = replace(session.state, units={**session.state.units, target_id: replace(
        session.state.units[target_id], hp=10000, max_hp=10000, toughness=1,
        flags={**session.state.units[target_id].flags, 'weaknesses': ['Thunder']})})
    if hook == 'action':
        session.state = before
        submitted = session.submit(command_from_json({
            'actor_id': 'arlan', 'action_id': 'avatar_skill:100801', 'action_level': 1,
            'target_ids': [target_id], 'metadata': {'crit_mode': 'noncrit'}}))
        assert submitted.transition.outcome.successor_eligible, submitted.transition.outcome.reason_codes
        after = session.state
        events = submitted.transition.transaction.events
    else:
        committed = CombatExecutor(rules).commit_eventful_transition(
            before, mutations=(), events=(GameEvent('custom.event', source_id='arlan',
                target_id=target_id, event_id='fixture:request-toughness'),),
            producer_kind='fixture', producer_id='processor-toughness')
        assert not committed.errors, committed.errors
        after, events = committed.after_state, committed.events
    unit = after.units[target_id]
    assert unit.toughness == 0 and unit.flags['broken'] is True
    assert unit.hp < before.units[target_id].hp  # Actual shared break damage.
    assert 'modifier:StanceBreakState' in unit.statuses
    assert unit.action_value > before.units[target_id].action_value
    for event_type in ('toughness.before_hit', 'toughness.hit', 'break.triggered'):
        assert after.units['arlan'].flags['seen:' + event_type] == 1
        assert sum(event.event_type == event_type for event in events) == 1
