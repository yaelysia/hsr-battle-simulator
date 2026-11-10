"""Real inline eidolon branches must reach the shared damage consumer once."""
import copy
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.battle_archive import write_archive
from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook
from hsr.simulator_v8_clean_core.tbgd.character_cards import (
    _eidolon_build_bindings, _finalize_selection_bindings,
)

pytestmark = pytest.mark.integration


@lru_cache(maxsize=1)
def _source_case():
    root = Path(__file__).resolve().parents[4]
    scenario = json.loads((Path(__file__).resolve().parents[1]
                           / 'examples/cli/arlan_vs_antimatter.json').read_text())
    return build_battle_rulebook(root / 'turnbasedgamedata-main', scenario), scenario


def test_inline_eidolon_needs_real_selector_evidence_and_preserves_other_gaps():
    rules, _ = _source_case()
    slot = next(s for s in rules.ir.character_eidolon_slots
                if s.avatar_id == '1008' and s.rank == 1)
    relations = rules.character_build_selector_relations_for_selection(slot.eidolon_slot_id)
    assert relations
    assert any(r.selector_json_path.startswith('$.AbilityList[')
               for r in relations)
    mechanisms = {s.mechanism_slot_id: s for s in rules.ir.character_mechanism_slots}
    missing = _eidolon_build_bindings(slot, mechanisms, None, ())
    assert len(missing) == 1 and missing[0].blocked_reason == 'eidolon_slot_has_no_runtime_effect_source'
    assert not _eidolon_build_bindings(slot, mechanisms, None, relations)
    other = replace(missing[0], blocked_reason='eidolon_skill_level_bonus_not_positive_integer')
    assert _finalize_selection_bindings([other], relations) == (other,)


@pytest.mark.parametrize('rank', [0, 1])
def test_arlan_eidolon_damage_condition_and_complete_battle(tmp_path, rank):
    rules, original = _source_case()
    scenario = copy.deepcopy(original)
    unit = scenario['units'][0]
    unit['character_build'] = replace(
        CharacterBuildInput.from_json(unit['character_build']), eidolon_level=rank,
    ).to_json()
    unit['eidolon_level'] = rank
    modifier = next(m for m in rules.ir.damage_modifiers if m.modifier_name == 'MAvatar_Arlan_00_Rank01')
    task = next(t for t in rules.ir.status_callback_tasks if t.task_id == modifier.source_task_id)
    assert modifier.source == task.source
    session = BattleSession(rules, scenario)
    seen = set()
    for _ in range(40):
        decision = session.advance()
        if session.outcome:
            break
        assert decision.ready, decision.blocked_reason
        choices = decision.availability.choices
        queued = [c for c in choices if c.choice_kind == 'ultimate_window']
        requests = [c for c in choices if c.choice_kind == 'manual_ultimate_request']
        normal = [c for c in choices if c.choice_kind == 'timeline_actor'
                  or c.choice_kind == 'normal_action' and
                  (c.actor_side == 'enemy' or c.action_id == 'avatar_skill:100802')]
        choice = (queued or requests or normal)[0]
        targets = [choice.target_query.candidate_ids[0]] if (
            choice.target_query and choice.target_query.selection_mode == 'explicit'
        ) else []
        result = session.submit(command_from_json({**choice.command_template, 'target_ids': targets}))
        assert result.transition.outcome.successor_eligible, (
            result.transition.outcome.reason_codes,
            [child.outcome.reason_codes for child in result.child_transitions],
        )
        actor = session.state.units['arlan']
        for mutation in result.transition.transaction.mutations:
            meta = mutation.metadata
            if (mutation.path[-1] != 'hp' or meta.get('attacker_id') != 'arlan'
                    or meta.get('damage_formula_family') != 'direct'):
                continue
            low_hp_skill = meta['attack_type'] == 'BPSkill' and actor.hp <= actor.max_hp / 2
            terms = [t for t in meta['modifier_ledger']['applied_terms']
                     if t['source_id'] == modifier.damage_modifier_id]
            if rank and low_hp_skill:
                assert len(terms) == 1 and terms[0]['applied_value'] == pytest.approx(0.1)
                assert terms[0]['bucket'] == 'damage_bonus'
                seen.add('eidolon_bonus')
            else:
                assert not terms
            seen.add('low_hp_skill' if low_hp_skill else meta['attack_type'])
    assert session.outcome == 'victory'
    assert {'BPSkill', 'low_hp_skill', 'Ultra'} <= seen
    assert ('eidolon_bonus' in seen) == bool(rank)
    archive = write_archive(tmp_path / f'arlan-e{rank}.json.gz', session.archive())
    print(f'archive: {archive}')


def test_invalid_eidolon_modifier_rolls_back_the_whole_action(monkeypatch):
    rules, original = _source_case()
    scenario = copy.deepcopy(original)
    unit = scenario['units'][0]
    unit['character_build'] = replace(
        CharacterBuildInput.from_json(unit['character_build']), eidolon_level=1,
    ).to_json()
    unit['eidolon_level'] = 1
    session = BattleSession(rules, scenario)
    assert session.advance().ready
    actor = session.state.units['arlan']
    # Boundary fixture: force the branch and corrupt its source identity only.
    session.state = replace(session.state, units={
        **session.state.units, 'arlan': replace(actor, hp=actor.max_hp / 2),
    })
    before = session.state
    snapshot = before.snapshot().to_json()
    original_execute = StatusCallbackSystem._execute_damage_modifier_task

    def invalid_source(self, state, callback, task, detail, **kwargs):
        task = replace(task, source=replace(task.source, raw_id='invalid-source-fixture'))
        return original_execute(self, state, callback, task, detail, **kwargs)

    monkeypatch.setattr(StatusCallbackSystem, '_execute_damage_modifier_task', invalid_source)
    target_id = next(uid for uid, unit in before.units.items() if unit.side == 'enemy')
    result = session.submit(command_from_json({
        'actor_id': 'arlan', 'action_id': 'avatar_skill:100802', 'action_level': 1,
        'target_ids': [target_id],
    }))
    assert not result.transition.outcome.successor_eligible
    reasons = (result.transition.outcome.reason_codes,
               [child.outcome.reason_codes for child in result.child_transitions])
    assert 'damage_modifier_source_identity_mismatch' in str(reasons)
    assert not result.transition.transaction.mutations and not result.transition.rng_events
    assert session.state == before and session.state.snapshot().to_json() == snapshot
