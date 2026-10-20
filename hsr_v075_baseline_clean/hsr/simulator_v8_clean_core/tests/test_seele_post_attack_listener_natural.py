"""Enhanced Seele's post-action listener consumes the accepted action target table.

The natural route uses the public example inputs: Seele avatar:1102 E0/Lv1/P0 and
Natasha E0/Lv80/promotion6 with empty equipment enter source wave 400020800 wave0.
The first public decision is the enhanced normal attack avatar_skill:1110201, whose
real OnListenAfterAttack listener MAvatar_Advanced_Seele_00_Skill02_AutoInsertListen
runs a ParamEntityAttackTargetList.SortByHP Retarget over that action's admitted
target table. The HP-ratio condition is false on full-HP targets, so the listener
chooses an empty set and has no side effect. Later decisions stay submittable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_REPO_ROOT = Path(__file__).resolve().parents[4]
_EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "cli"
_SCENARIO = _EXAMPLES / "seele_post_attack_listener_natural.json"
_COMMANDS = _EXAMPLES / "seele_post_attack_listener_natural.commands.json"
_CALLBACK = "MAvatar_Advanced_Seele_00_Skill02_AutoInsertListen"


def _records_mentioning(value: object, needle: str) -> list[dict]:
    found: list[dict] = []

    def visit(item: object) -> None:
        if isinstance(item, dict):
            if needle in json.dumps(item, ensure_ascii=False):
                found.append(item)
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return found


@pytest.mark.integration
def test_seele_post_attack_listener_natural_route_continues() -> None:
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    commands = json.loads(_COMMANDS.read_text(encoding="utf-8"))["commands"]
    rules = build_battle_rulebook(_REPO_ROOT / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)

    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    assert [(choice.actor_id, choice.action_id) for choice in decision.availability.choices] == [
        ("seele", "avatar_skill:1110201"),
        ("seele", "avatar_skill:1110202"),
    ]

    first = session.submit(command_from_json(commands[0]))
    assert first.transition.outcome.successor_eligible, first.transition.outcome.reason_codes
    settlement = first.transition.transaction.settlement
    records = list(settlement.records) if settlement is not None else []
    callback_records = _records_mentioning(records, _CALLBACK)
    assert any(
        str(record.get("record_type")) == "status_callback"
        and _CALLBACK in json.dumps(record, ensure_ascii=False)
        for record in callback_records
    ), "the real enhanced listener did not run"
    # Full-HP targets fail the HP-ratio predicate, so the insert branch has no effect.
    assert "modifier:MAvatar_Advanced_Seele_00_Skill02InsertMuteSp" not in session.state.units[
        "seele"
    ].statuses

    for index, command in enumerate(commands[1:], start=1):
        decision = session.advance()
        assert decision.ready, (index, decision.blocked_reason)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (
            index,
            result.transition.outcome.reason_codes,
        )
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
