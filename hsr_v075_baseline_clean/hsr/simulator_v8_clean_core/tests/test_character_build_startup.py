"""Selected source-bound startup, hit energy and one-use queued self-healing."""
import copy
import json
from collections import Counter
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.battle_archive import write_archive
from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput
from hsr.simulator_v8_clean_core.core.model import ActionCommand, TargetResolution
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem, CharacterBuildStartupInvocation
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook
from hsr.simulator_v8_clean_core.tbgd.lowering import _status_callback_task_admission


@lru_cache(maxsize=1)
def _source_case():
    root = Path(__file__).resolve().parents[4]
    scenario = json.loads((Path(__file__).resolve().parents[1]
                           / 'examples/cli/arlan_natasha_vs_antimatter.json').read_text())
    return build_battle_rulebook(root / 'turnbasedgamedata-main', scenario), scenario


def _scenario(original, rank):
    scenario = copy.deepcopy(original)
    unit = next(u for u in scenario['units'] if u['entity_ref'] == 'avatar:1105')
    unit['eidolon_level'] = rank
    unit['character_build'] = replace(
        CharacterBuildInput.from_json(unit['character_build']), eidolon_level=rank,
    ).to_json()
    return scenario


def _installed(state):
    return Counter(detail['modifier_name'] for detail in state.units['natasha'].flags['status_details'])


def test_hit_energy_admission_keeps_target_and_numeric_validation():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    data = json.loads((root / 'Config/ConfigAbility/Avatar/Avatar_Natasha_00_Ability.json').read_text())
    ability = next(a for a in data['AbilityList'] if a['Name'] == 'Avatar_Natasha_00_Rank04')
    callback = ability['Modifiers']['MAvatar_Natasha_00_Rank04_Check']['_CallbackList'][0]
    task = callback['CallbackConfig'][0]
    assert _status_callback_task_admission(callback['Event'], 'ModifySPNew', task) == ('executable', '')
    for invalid in (
        {**task, 'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'MissingAlias'}},
        {**task, 'AddValue': {'UnrecognizedValue': 5}},
    ):
        assert _status_callback_task_admission(callback['Event'], 'ModifySPNew', invalid)[0] == 'blocked'
    assert _status_callback_task_admission('OnUnknownEvent', 'ModifySPNew', task)[0] == 'blocked'


@pytest.mark.integration
def test_build_startup_only_accepts_selected_owner_and_formal_entry():
    rules, original = _source_case()
    states = {rank: BattleSession(rules, _scenario(original, rank)).state for rank in (0, 1, 4)}
    for rank, state in states.items():
        assert _installed(state)['MAvatar_Natasha_00_Rank01_Check'] == (rank >= 1)
        assert _installed(state)['MAvatar_Natasha_00_Rank04_Check'] == (rank >= 4)
    slot = next(slot for slot in rules.ir.character_eidolon_slots
                if slot.avatar_id == '1105' and slot.rank == 4)
    bindings = tuple(b.build_binding_id for b in slot.build_bindings if b.dynamic_ref_kind == 'direct_ability')
    graph, reason = rules.character_build_startup_graph(bindings)
    assert graph is not None, reason
    assert rules.character_build_startup_graph(bindings * 2)[0] is None
    phases = tuple(rules.ability_phase(key) for key in graph.phase_ids)
    assert {phase.invocation_role for phase in phases} == {'build_startup'}
    effects = EffectRegistry(StatusSystem(rules))
    runtime = AbilityTaskSystem(rules, effects, event_dispatcher=EventDispatchSystem(rules, effects))
    for state, invocation, expected in (
        (states[0], CharacterBuildStartupInvocation('natasha', graph.standalone_ability_graph_id, bindings),
         'character_build_startup_selection_not_admitted'),
        (states[4], CharacterBuildStartupInvocation('arlan', graph.standalone_ability_graph_id, bindings),
         'character_build_startup_selection_not_admitted'),
        (states[4], CharacterBuildStartupInvocation('natasha', 'wrong-graph-fixture', bindings),
         'character_build_startup_graph_identity_mismatch'),
    ):
        result = runtime.execute_character_build_startup(state, invocation=invocation)
        assert result.after_state == state and not result.mutations and not result.rng_events
        assert expected in {node.reason_code for node in result.node_results}
    result = runtime.execute_callback(
        states[4], phases=phases, callback_kind='OnStart',
        command=ActionCommand('natasha', 'avatar_skill:110501', 1),
        action_definition=rules.action_definition('avatar_skill:110501', 1),
        target_resolution=TargetResolution(),
    )
    assert result.after_state == states[4] and not result.mutations and not result.rng_events
    assert 'character_build_ability_requires_startup_invocation' in {node.reason_code for node in result.node_results}


@pytest.mark.integration
def test_selected_eidolons_natural_hits_self_heal_and_complete_battle(tmp_path):
    rules, original = _source_case()
    session = BattleSession(rules, _scenario(original, 4))
    energy_task = next(task for task in rules.ir.status_callback_tasks
                       if task.modifier_name == 'MAvatar_Natasha_00_Rank04_Check' and task.opcode == 'ModifySPNew')
    heal_graph = next(graph for graph in rules.ir.standalone_ability_graphs
                      if graph.ability_name == 'Avatar_Natasha_00_Rank01_InsertSkill_Phase02')
    heal_effects = {task.effect_id for phase_id in heal_graph.phase_ids
                    for task in rules.ability_tasks_for_phase(phase_id) if task.opcode == 'HealHP'}
    assert len(heal_effects) == 1
    hits = heals = 0
    for _ in range(36):
        before = session.state
        decision = session.advance()
        after = session.state
        if after.units['natasha'].hp > before.units['natasha'].hp:
            assert before.units['natasha'].hp <= before.units['natasha'].max_hp * 0.3
            assert after.units['natasha'].hp == after.units['natasha'].max_hp
            assert _installed(before)['MAvatar_Natasha_00_Rank01_Check'] == 1
            assert _installed(after)['MAvatar_Natasha_00_Rank01_Check'] == 0
            # Inspect only the authoritative transactions, not duplicate audit projections.
            mutations = [mutation for transition in session.operations[-1]['transitions']
                         for mutation in transition['mutations']]
            self_heals = [m for m in mutations if m['path'] == ['units', 'natasha', 'hp']
                          and m['metadata'].get('effect_id') in heal_effects]
            assert len(self_heals) == 1
            heals += 1
        if session.outcome:
            break
        assert decision.ready, decision.blocked_reason
        choices = decision.availability.choices
        queued = [c for c in choices if c.choice_kind in ('ultimate_window', 'queue_action')]
        normal = [c for c in choices if c.choice_kind == 'timeline_actor'
                  or c.choice_kind == 'normal_action' and
                  (c.actor_side == 'enemy' or c.action_id in ('avatar_skill:100801', 'avatar_skill:110502'))]
        choice = (queued or normal)[0]
        targets = []
        if choice.target_query and choice.target_query.selection_mode == 'explicit':
            targets = ['natasha' if choice.actor_side == 'enemy'
                       else 'arlan' if choice.action_id == 'avatar_skill:110502'
                       else choice.target_query.candidate_ids[0]]
        before = session.state
        result = session.submit(command_from_json({**choice.command_template, 'target_ids': targets}))
        assert result.transition.outcome.successor_eligible, (
            result.transition.outcome.reason_codes, [child.outcome.reason_codes for child in result.child_transitions],
        )
        if choice.choice_kind == 'normal_action' and choice.actor_side == 'enemy':
            hits += 1
            energy = [m for m in result.transition.transaction.mutations
                      if m.path == ('units', 'natasha', 'energy')]
            extra = [m for m in energy if m.metadata.get('effect_id') == energy_task.effect_id]
            assert len(extra) == 1
            assert extra[0].metadata['amount'] == pytest.approx(5)
            if before.units['natasha'].energy + 15 <= before.units['natasha'].max_energy:
                assert session.state.units['natasha'].energy - before.units['natasha'].energy == pytest.approx(15)
    assert session.outcome == 'victory' and hits == 5 and heals == 1
    assert _installed(session.state)['MAvatar_Natasha_00_Rank04_Check'] == 1
    archive = write_archive(tmp_path / 'natasha-e4-startup.json.gz', session.archive())
    print(f'archive: {archive}')
