"""One real source-backed battle, including startup, terminal state and replay."""
from pathlib import Path

from hsr.simulator_v8_clean_core.battle_archive import read_archive, verify_archive
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook


def test_real_battle_startup_actions_victory_and_replay():
    root = Path(__file__).resolve().parents[4]
    example = Path(__file__).resolve().parents[1] / "examples/cli/arlan_vs_antimatter.json"
    scenario = read_archive(example)
    rules = build_battle_rulebook(root / "turnbasedgamedata-main", scenario)
    card = rules.monster_data_card_for_entity("monster:8011010")
    slots = rules.passive_mechanism_slots_for_card(card.card_id)
    assert len(slots) == 2
    assert {slot.coverage_status for slot in slots} == {"executable", "skipped_with_reason"}
    session = BattleSession(rules, scenario)
    enemies = [unit for unit in session.state.units.values() if unit.side == "enemy"]
    for enemy in enemies:
        installed = {item["modifier_name"] for item in enemy.flags["status_details"]}
        assert {"Local_ListenStanceBreak", "Local_ListenRedStance", "MonsterAllDamageReduce",
                "TriggerStanceCountDown_Monster"} <= installed
    commands = read_archive(example.with_suffix(".commands.json"))["commands"]
    for command in commands:
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.to_json()
    session.advance()
    assert session.outcome == "victory"
    assert 0 < session.state.units["arlan"].hp < 6
    assert all(session.state.units[enemy.unit_id].hp == 0 for enemy in enemies)
    archive = session.archive()
    assert verify_archive(archive, rules)["ok"]
