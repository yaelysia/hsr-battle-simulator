"""In-memory session branching for the reasoner (M1-2c)."""
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.battle_archive import read_json_object, verify_archive
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration


def _session() -> BattleSession:
    root = Path(__file__).resolve().parents[4]
    example = Path(__file__).resolve().parents[1] / 'examples/cli/arlan_vs_antimatter.json'
    scenario = read_json_object(example)
    rules = build_battle_rulebook(root / 'turnbasedgamedata-main', scenario)
    return BattleSession(rules, scenario)


def _first_ally_choice(session: BattleSession):
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    return next(
        choice for choice in decision.availability.choices
        if choice.choice_kind == 'normal_action' and choice.actor_side == 'ally'
    )


def test_fork_shares_state_and_replays_through_the_formal_boundary():
    session = _session()
    choice = _first_ally_choice(session)
    query = choice.target_query
    targets = [query.candidate_ids[0]] if query and query.selection_mode == 'explicit' else []
    command = command_from_json({**choice.command_template, 'target_ids': targets})
    fork = session.fork()
    assert fork.state is session.state
    assert fork.operations == session.operations and fork.operations is not session.operations
    original_state = session.state
    result = session.submit(command)
    assert result.transition.outcome.successor_eligible
    assert fork.state is original_state
    fork_result = fork.submit(command)
    assert fork_result.transition.outcome.successor_eligible
    assert fork.state.snapshot().to_json() == session.state.snapshot().to_json()
    assert fork.rules_fingerprint == session.rules_fingerprint
    report = verify_archive(fork.archive(), fork.rules)
    assert report['ok'], report['errors']


def test_fork_explores_a_different_branch_without_touching_the_original():
    session = _session()
    choice = _first_ally_choice(session)
    query = choice.target_query
    assert query is not None and len(query.candidate_ids) >= 2
    fork = session.fork()
    command_a = command_from_json({**choice.command_template, 'target_ids': [query.candidate_ids[0]]})
    command_b = command_from_json({**choice.command_template, 'target_ids': [query.candidate_ids[1]]})
    assert session.submit(command_a).transition.outcome.successor_eligible
    assert fork.submit(command_b).transition.outcome.successor_eligible
    assert session.state.snapshot().to_json() != fork.state.snapshot().to_json()
    report = verify_archive(fork.archive(), fork.rules)
    assert report['ok'], report['errors']
