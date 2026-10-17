"""Observations compare committed state without becoming combat inputs."""
import json
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core.core.model import BattleState, UnitState
from simulator_v8_ui.live import LiveBattle, SessionConflict
from simulator_v8_ui.server import V8UIRequestHandler


def test_observation_is_exact_read_only_and_distinguishes_paths(monkeypatch):
    def forbidden(*_args):
        pytest.fail('observation must not compile battle rules')
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', forbidden)
    battle = LiveBattle(Path('unused'))
    original = BattleState(units={'ally': UnitState(
        'ally', 'ally', 'avatar:example', hp=10.1, energy=0, toughness=3,
        shield_instances=({'remaining': 2.5},),
    )}, event_index=7)
    operations = [{'kind': 'advance'}, {'kind': 'submit', 'command': {'action_id': 'first'}}]
    battle.session_id = 'battle'
    battle.session = SimpleNamespace(state=original, operations=operations,
                                     scenario=SimpleNamespace(scenario_id='scenario'),
                                     scenario_data={'units': []}, rules_fingerprint='a' * 64)
    request = {'session_id': 'battle', 'revision': 2, 'unit_id': 'ally',
               'observed': {'hp': '10.20', 'energy': 0, 'toughness': '2.9', 'shield': '2.50'},
               'game_version': 'recorded version', 'note': 'video 00:10'}
    record = battle.compare_observation(request)
    assert record['measurements'] == {
        'hp': {'observed': '10.20', 'simulated': '10.1', 'difference': '0.10'},
        'energy': {'observed': '0', 'simulated': '0', 'difference': '0'},
        'toughness': {'observed': '2.9', 'simulated': '3', 'difference': '-0.1'},
        'shield': {'observed': '2.50', 'simulated': '2.5', 'difference': '0.00'},
    }
    assert record['revision'] == 2 and record['event_index'] == 7
    assert record['note'] == 'video 00:10' and record['entity_ref'] == 'avatar:example'
    assert record['rules_fingerprint'] == battle.session.rules_fingerprint
    assert battle.session.state is original and battle.session.operations is operations
    assert not battle.steps and not battle.results
    repeat = battle.compare_observation(request)
    assert repeat['operation_path_fingerprint'] == record['operation_path_fingerprint']
    battle.session.operations = [{'kind': 'advance'}, {'kind': 'submit', 'command': {'action_id': 'second'}}]
    branch = battle.compare_observation(request)
    assert branch['operation_path_fingerprint'] != record['operation_path_fingerprint']
    battle.session.scenario_data = {'units': [], 'seed': 2}
    assert battle.compare_observation(request)['scenario_fingerprint'] != record['scenario_fingerprint']

    for patch in ({'unit_id': []}, {'unit_id': 'missing'}, {'observed': {}},
                  {'observed': {'attack': 1}}, {'observed': []}, {'note': []},
                  {'game_version': 'x' * 1001}, *(
                      {'observed': {'hp': value}} for value in
                      (True, None, {}, '', 'NaN', 'Infinity', '-1', '1e101', '1e-101',
                       '0e-9999999999', '1' * 65, '1_0', float('nan'))
                  )):
        with pytest.raises(ValueError):
            battle.compare_observation({**request, **patch})
        assert battle.session.state is original and not battle.steps and not battle.results
    for patch in ({'revision': 1}, {'revision': True}, {'session_id': 'previous'}):
        with pytest.raises(SessionConflict):
            battle.compare_observation({**request, **patch})
    battle.session = None
    with pytest.raises(SessionConflict):
        battle.compare_observation(request)


def test_observation_http_boundary():
    battle = LiveBattle(Path('unused'))
    battle.session_id = 'battle'
    battle.session = SimpleNamespace(
        state=BattleState(units={'ally': UnitState('ally', 'ally', 'avatar:example')}),
        operations=[], scenario=SimpleNamespace(scenario_id='scenario'),
        scenario_data={}, rules_fingerprint='b' * 64,
    )
    class Handler(V8UIRequestHandler):
        def log_message(self, *_args):
            pass
    Handler.battle = battle
    for revision, observed, expected_status in ((0, {'hp': '0'}, 200),
                                               (0, {'hp': 'bad'}, 400),
                                               (1, {'hp': '0'}, 409)):
        payload = json.dumps({'session_id': 'battle', 'revision': revision,
                              'unit_id': 'ally', 'observed': observed}).encode()
        wire = (f'POST /api/battle/observation HTTP/1.0\r\nContent-Length: {len(payload)}\r\n\r\n').encode() + payload
        class Connection:
            output = b''
            def makefile(self, *_args):
                return BytesIO(wire)
            def sendall(self, data):
                self.output += data
        connection = Connection()
        Handler(connection, ('127.0.0.1', 1), object())
        header, body = connection.output.split(b'\r\n\r\n', 1)
        assert int(header.split()[1]) == expected_status, body
        if expected_status == 200:
            assert json.loads(body)['measurements']['hp']['difference'] == '-1.0'
    assert battle.session.operations == [] and not battle.steps
