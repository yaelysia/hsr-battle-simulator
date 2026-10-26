"""R05: ordinary-party battle routes for the four ordinary characters.

Scenario A exercises Arlan's trace branches and Natasha's cleanse/HoT prefixes;
scenario B exercises Lynx's Survival Response/HoT branches and March's
shield/counter/Ultimate freeze prefixes.  Both routes are replayed command by
command through the public decision boundary and audited with the native
RuntimeSourceAuditor.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from hsr.simulator_v8_clean_core.battle_archive import replay_archive, write_archive
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_EXAMPLES = _CORE / 'examples/cli'


def _records(transitions):
    for transition in transitions:
        children = getattr(transition, 'child_transitions', ()) or ()
        for container in (transition, *children):
            settlement = container.transaction.settlement
            for record in (settlement.records if settlement is not None else ()):
                if isinstance(record, dict):
                    yield record


def _module_scenario(name):
    return (
        json.loads((_EXAMPLES / f'{name}.json').read_text(encoding='utf-8')),
        json.loads((_EXAMPLES / f'{name}.commands.json').read_text(encoding='utf-8'))[
            'commands'
        ],
    )


def _rules_factory(scenario):
    return build_battle_rulebook(_ROOT / 'turnbasedgamedata-main', scenario)


def _run_route(name, tmp_path):
    scenario, commands = _module_scenario(name)
    rules = _rules_factory(scenario)
    session = BattleSession(rules, scenario)
    auditor = RuntimeSourceAuditor(rules)
    records: list[dict] = []
    audited = 0
    submitted = 0

    def audit(transition, label):
        nonlocal audited
        result = auditor.validate_transition(transition)
        assert result.ok, (label, result.violations)
        audited += 1

    while submitted < len(commands):
        decision, advance_transitions = session.advance_with_transitions()
        assert decision.ready, (submitted, decision.blocked_reason)
        for transition in advance_transitions:
            action = transition.transaction.command.action_id
            if action == 'wave:transition' or action.startswith('scheduler:'):
                audit(transition, f'advance:{action}')
        records.extend(_records(advance_transitions))
        command = commands[submitted]
        result = session.submit(command_from_json(command))
        submitted += 1
        transition = result.transition
        assert transition.outcome.successor_eligible, (
            submitted, transition.outcome.reason_codes,
        )
        assert command['actor_id'] == transition.transaction.command.actor_id
        audit(transition, f'submit:{submitted}')
        children = tuple(getattr(result, 'child_transitions', ()) or ())
        for index, child in enumerate(children):
            audit(child, f'submit:{submitted}:child:{index}')
        records.extend(_records((transition, *children)))
        if session.outcome:
            break

    final_decision, final_transitions = session.advance_with_transitions()
    for transition in final_transitions:
        action = transition.transaction.command.action_id
        if action == 'wave:transition' or action.startswith('scheduler:'):
            audit(transition, f'final:{action}')
    records.extend(_records(final_transitions))
    assert session.outcome == 'victory', session.outcome
    assert submitted == len(commands)
    archive_path = write_archive(tmp_path / f'{name}.json.gz', session.archive())
    return session, records, audited, archive_path


def test_r05_arlan_natasha_route_covers_trace_branches(tmp_path):
    session, records, audited, archive_path = _run_route(
        'r05_arlan_natasha_trace_curriculum', tmp_path
    )
    assert audited > 0
    ledger = json.dumps(session.operations, default=str)
    # A6 Repel installs the non-DoT damage block modifier at the low-HP entry,
    # a real incoming hit consumes it, and that transition passes the native
    # source audit above.
    assert 'BlockDamageExcludeDot' in ledger
    blocked = [
        record for record in records if record.get('record_type') == 'damage_blocked'
    ]
    assert blocked, 'formal route did not record a damage_blocked settlement'
    assert blocked[-1].get('payload', {}).get('damage_block_flag') == 'BlockDamageExcludeDot'
    # A4 Endurance halves the incoming DoT application chance.
    assert '"behavior_flag_resistance": 0.5' in ledger
    # A2 Revival resolves its OnTriggerDeath heal after the low-HP kill.
    assert 'M_Arlan_Tree01' in ledger

    # A6 Recuperation: the skill's continuous healing lasts one extra turn (3).
    ledger = json.dumps(session.archive(), default=str)
    assert '"MAvatar_Natasha_00_HOT_HPByMaxHP"' in ledger
    assert '"duration": 3.0' in ledger

    replay = replay_archive(archive_path, _rules_factory)
    assert replay['errors'] == [], replay['errors']
    assert replay['ok'] and replay['step_count'] > 0


def test_r05_lynx_march_route_covers_survival_and_shield_branches(tmp_path):
    session, records, audited, archive_path = _run_route(
        'r05_lynx_march_survival_counter', tmp_path
    )
    assert audited > 0
    ledger = json.dumps(session.archive(), default=str)
    operations = json.dumps(session.operations, default=str)
    # Lynx A6 extends the Talent HoT while Survival Response applies the
    # converted Max HP bucket to March.
    assert 'MAvatar_Lynx_00_HOT_HealByMaxHp' in ledger
    assert '"duration": 3.0' in ledger
    assert 'MAvatar_Lynx_00_HPAddedRatio01' in ledger
    # March E2 grants a shield on battle entry; the A4 counter insert ability
    # then resolves its DEF-based extra damage ratio in its own execution scope.
    assert 'MAvatar_March7th_00_Rank02_Shield' in ledger
    assert 'extra_scaling_ratio' in operations
    assert 'counter' in operations

    replay = replay_archive(archive_path, _rules_factory)
    assert replay['errors'] == [], replay['errors']
    assert replay['ok'] and replay['step_count'] > 0
