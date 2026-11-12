"""Public behavior references, not external game-value acceptance or audit snapshots."""
import json
import copy
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from hsr.simulator_v8_clean_core.battle_archive import fork_session, read_archive, restore_session, write_archive
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook


def battle_observation(snapshot):
    """Keep player-visible values; omit opaque ids and implementation/audit trees."""
    return {
        'skill_points': snapshot['skill_points'],
        'wave_index': snapshot['wave_index'],
        'outcome': snapshot['global_flags'].get('battle_outcome', ''),
        'rng_state': snapshot['rng_state'],
        'units': {uid: {key: unit[key] for key in (
            'hp', 'energy', 'toughness', 'action_value', 'lifecycle_status', 'statuses')}
            for uid, unit in sorted(snapshot['units'].items())},
    }


def choice_observation(availability):
    return [(c.actor_id, c.action_id, c.action_level, c.choice_kind, c.resource_status,
             (c.target_query.selection_mode, c.target_query.selection_min, c.target_query.selection_max,
              c.target_query.candidate_ids, c.target_query.automatic_target_ids) if c.target_query else None)
            for c in availability.choices]


@pytest.mark.integration
def test_public_route_numbers_modes_and_history_branch(tmp_path):
    root = Path(__file__).resolve().parents[4]
    core = Path(__file__).resolve().parents[1]
    scenario = json.loads((core / 'examples/cli/arlan_vs_antimatter.json').read_text())
    commands = json.loads((core / 'examples/cli/arlan_vs_antimatter.commands.json').read_text())['commands']
    reference = json.loads((Path(__file__).parent / 'golden/arlan_vs_antimatter.json').read_text())
    rules = build_battle_rulebook(root / 'turnbasedgamedata-main', scenario)
    assert not rules.ir.light_cone_definitions and not rules.ir.relic_template_definitions
    results = {}
    for mode in ('compact', 'full'):
        started = time.perf_counter()
        session = BattleSession(rules, scenario, diagnostics=mode)
        after_states = []
        metadata_bytes = []
        for index, raw in enumerate(commands):
            decision = session.advance()
            assert decision.ready, decision.blocked_reason
            assert any(choice.actor_id == raw['actor_id'] and choice.action_id == raw['action_id']
                       for choice in decision.availability.choices)
            if index == 2:
                boundary, boundary_state = len(session.operations), session.state
            result = session.submit(command_from_json(raw))
            assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
            metadata_bytes.extend(len(json.dumps(m.metadata, ensure_ascii=False).encode())
                                  for m in result.transition.transaction.mutations if m.source == 'damage_system')
            actual = battle_observation(session.state.snapshot().to_json())
            assert actual == reference['after_submits'][index]
            after_states.append(actual)
        session.advance()
        assert session.outcome == 'victory'
        original_final = session.state
        with patch.object(BattleSession, '__init__', side_effect=AssertionError('fork rebuilt the session')):
            branch = fork_session(session, boundary)
        assert branch.state is boundary_state
        assert len(branch.operations) == boundary
        assert branch.submit(command_from_json(commands[2])).transition.outcome.successor_eligible
        assert battle_observation(branch.state.snapshot().to_json()) == after_states[2]
        assert session.state is original_final
        path = write_archive(tmp_path / (mode + '.json.gz'), session.archive())
        print(mode, {'seconds': time.perf_counter() - started, 'archive_bytes': path.stat().st_size,
                     'max_damage_metadata_bytes': max(metadata_bytes), 'metadata_bytes': sum(metadata_bytes)})
        restored = restore_session(read_archive(path), rules)
        assert restored.diagnostics == mode
        assert battle_observation(restored.state.snapshot().to_json()) == battle_observation(session.state.snapshot().to_json())
        historical = fork_session(restored, boundary)
        assert historical.submit(command_from_json(commands[2])).transition.outcome.successor_eligible
        assert battle_observation(historical.state.snapshot().to_json()) == after_states[2]
        results[mode] = after_states
    assert results['compact'] == results['full']


@pytest.mark.integration
def test_fixed_compile_scope_reuses_rules_without_changing_battles():
    root = Path(__file__).resolve().parents[4]
    core = Path(__file__).resolve().parents[1]
    first = json.loads((core / 'examples/cli/arlan_vs_antimatter.json').read_text())
    second = json.loads((core / 'examples/cli/arlan_natasha_vs_antimatter.json').read_text())
    pool = {'avatar_ids': ['1008', '1105'],
            'stage_ids': sorted({first['stage_ref'], second['stage_ref']})}
    fingerprints = []
    for name, original in (('arlan_vs_antimatter', first), ('arlan_natasha_vs_antimatter', second)):
        scoped = copy.deepcopy(original)
        scoped['battle_setup']['metadata']['compile_scope'] = pool
        started = time.perf_counter()
        rules = build_battle_rulebook(root / 'turnbasedgamedata-main', scoped)
        build_seconds = time.perf_counter() - started
        pooled = BattleSession(rules, scoped)
        fingerprints.append(pooled.rules_fingerprint)
        narrow = BattleSession(build_battle_rulebook(root / 'turnbasedgamedata-main', original), original)
        commands = json.loads((core / 'examples/cli' / (name + '.commands.json')).read_text())['commands']
        for command in commands:
            left, right = pooled.advance(), narrow.advance()
            assert left.ready and right.ready
            assert choice_observation(left.availability) == choice_observation(right.availability)
            for session in (pooled, narrow):
                result = session.submit(command_from_json(command))
                assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
            assert battle_observation(pooled.state.snapshot().to_json()) == battle_observation(narrow.state.snapshot().to_json())
        print(name, {'pooled_rulebook_build_seconds': build_seconds})
    assert fingerprints[0] == fingerprints[1]
