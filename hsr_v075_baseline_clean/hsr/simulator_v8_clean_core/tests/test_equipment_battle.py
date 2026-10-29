"""Source equipment closure, threshold boundaries and an unmodified real battle."""
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.battle_archive import write_archive
from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput
from hsr.simulator_v8_clean_core.core.model import GameEvent
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.ability_property_watchers import AbilityPropertyWatcherSystem
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration


@lru_cache(maxsize=1)
def _case():
    scenario = json.loads((Path(__file__).resolve().parents[1]
                           / 'examples/cli/arlan_fleet_vs_antimatter.json').read_text())
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    return build_battle_rulebook(root, scenario), scenario


def _buffs(state):
    return [d for d in state.units['arlan'].flags['status_details']
            if d['modifier_name'] == 'MRelic_302_Sub']


def test_equipment_graph_source_closure_and_speed_threshold():
    rules, scenario = _case()
    graphs = [g for g in rules.ir.standalone_ability_graphs if g.source_mode == 'mainline_equipment']
    assert len(graphs) == 224
    # R06 closed the previously deferred equipment graphs: every published
    # light cone / relic-set graph must now pass the same static runtime
    # closure.  Runtime and numeric evidence is separate (see the R06 routes and
    # component checks) and is not implied by this assertion.
    blocked = {g.ability_name for g in graphs if rules._equipment_graph_runtime_closure_reason(g)}
    assert blocked == set()
    for name in ('Ability20005', 'Ability21002', 'Ability21032', 'Ability21036',
                 'Ability21056', 'Ability53021', 'Ability23006'):
        assert name not in blocked
    graph = next(g for g in graphs if g.ability_name == 'Ability53021')
    for phase_id in graph.phase_ids:
        for task in rules.ability_tasks_for_phase(phase_id):
            effect = rules.effect(task.effect_id)
            assert effect is not None and effect.coverage_status == 'executable'
            target = rules.target_expression(effect.payload['standard']['target_expression_id'])
            assert target.source.evidence['json_path'].endswith('.OnStart[0].TargetType')
    high = BattleSession(rules, scenario).state
    assert high.units['arlan'].speed > 120 and len(_buffs(high)) == 1
    build = CharacterBuildInput.from_json(scenario['units'][0]['character_build'])
    slow_build = replace(build, equipment_build=replace(build.equipment_build, relics=tuple(
        r for r in build.equipment_build.relics if r.slot_key.definition_identity != 'FOOT'
    )))
    slow_scenario = {**scenario, 'units': [{**scenario['units'][0], 'character_build': slow_build.to_json()}]}
    low = BattleSession(rules, slow_scenario).state
    assert low.units['arlan'].speed < 120 and not _buffs(low)

    # Explicit boundary fixture only: sweep effective speed, preserving source-built statuses.
    watchers = AbilityPropertyWatcherSystem(rules, status_callbacks=StatusCallbackSystem(rules))
    current = high
    for index, (speed, active) in enumerate(((119.999, False), (119.999, False), (120., True), (120., True))):
        unit = current.units['arlan']
        # The synthetic speed replaces its static pool only in this boundary fixture.
        unit = replace(unit, speed=speed, stat_pools=tuple(p for p in unit.stat_pools if p.property_type != 'speed'))
        current = replace(current, units={**current.units, 'arlan': unit})
        result = watchers.reconcile(current, unit_ids=('arlan',), trigger_event=GameEvent(
            event_type='fixture.speed_changed', event_id=f'fixture:{index}',
            source_id='fixture:boundary', target_id='arlan', window='fixture',
        ))
        assert result.ok, result.errors
        current = result.after_state
        assert len(_buffs(current)) == int(active)
        if index in (1, 3):
            assert not result.mutations
        if not active:
            without = effective_unit_stat(current.units['arlan'], 'attack').value
    assert effective_unit_stat(current.units['arlan'], 'attack').value == pytest.approx(without * 1.08)


def test_equipped_battle_completes_with_formal_archive(tmp_path):
    rules, scenario = _case()
    session = BattleSession(rules, scenario)
    for _ in range(24):
        decision = session.advance()
        if session.outcome:
            break
        assert decision.ready, decision.blocked_reason
        choices = decision.availability.choices
        chosen = ([c for c in choices if c.choice_kind == 'ultimate_window']
                  or [c for c in choices if c.choice_kind == 'manual_ultimate_request']
                  or [c for c in choices if c.choice_kind == 'timeline_actor'
                      or c.choice_kind == 'normal_action' and
                      (c.actor_side == 'enemy' or c.action_id == 'avatar_skill:100802')])
        choice = chosen[0]
        targets = ([choice.target_query.candidate_ids[0]]
                   if choice.target_query and choice.target_query.selection_mode == 'explicit' else [])
        result = session.submit(command_from_json({**choice.command_template, 'target_ids': targets}))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        assert len(_buffs(session.state)) == 1
    assert session.outcome == 'victory'
    archive = write_archive(tmp_path / 'equipment-battle.json.gz', session.archive())
    print(f'archive: {archive}')
