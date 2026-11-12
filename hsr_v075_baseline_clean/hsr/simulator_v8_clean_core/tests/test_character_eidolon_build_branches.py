"""R05: eidolon prefix selection reaches the real runtime branches."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from hsr.simulator_v8_clean_core.builds.character_assembler import assemble_character_build
from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput
from hsr.simulator_v8_clean_core.equipment.models import EquipmentBuildInput
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_STAGE = '201010110'
_AVATARS = ('1008', '1105', '1110', '1001')


def _template():
    template = json.loads((_CORE / 'examples/cli/arlan_melee_two_waves.json').read_text())
    return {
        'scenario_id': 'r05:eidolon-prefix-branches',
        'version': template['version'],
        'stage_ref': _STAGE,
        'wave_index': 0,
        'route': [],
        'battle_setup': template['battle_setup'],
    }


def _build(avatar_id, *, level=80, promotion=6, eidolon_level=0, trace_ids=()):
    card_id = f'character_data_card:avatar:{avatar_id}'
    return CharacterBuildInput(
        build_id=f'r05:{avatar_id}:e{eidolon_level}',
        character_card_id=card_id,
        level=level,
        promotion=promotion,
        eidolon_level=eidolon_level,
        unlocked_trace_node_ids=tuple(trace_ids),
        equipment_build=EquipmentBuildInput(
            build_id=f'r05:{avatar_id}:equipment',
            character_card_id=card_id,
        ),
    )


def _unit(avatar_id, unit_id, build, position=0, initial=None):
    return {
        'unit_id': unit_id,
        'side': 'ally',
        'entity_ref': f'avatar:{avatar_id}',
        'level': build.level,
        'eidolon_level': build.eidolon_level,
        'position': position,
        'build_mode': 'assembled_character_build',
        'character_build': build.to_json(),
        'initial_condition': initial or {
            'hp_mode': 'full', 'initial_energy': '0', 'initial_resource_values': [],
        },
    }


@lru_cache(maxsize=1)
def _rules():
    scenario = _template()
    scenario['units'] = [
        _unit(avatar_id, f'compile_{index}', _build(avatar_id, level=1, promotion=0), index)
        for index, avatar_id in enumerate(_AVATARS)
    ]
    return build_battle_rulebook(_ROOT / 'turnbasedgamedata-main', scenario)


def _trace(rules, avatar_id, point_id):
    card_id = f'character_data_card:avatar:{avatar_id}'
    for node in rules.ir.character_trace_nodes:
        if node.character_data_card_id == card_id and node.trace_id == str(point_id):
            return node.trace_node_id
    raise KeyError(point_id)


def _session(units):
    scenario = _template()
    scenario['units'] = units
    return BattleSession(_rules(), scenario, diagnostics="full")


def _status(unit, modifier_name):
    return next(
        (detail for detail in (unit.flags.get('status_details') or ())
         if detail.get('modifier_name') == modifier_name),
        None,
    )


def _advance_to(session, actor_id, action_id, *, max_steps=16):
    for _ in range(max_steps):
        if session.outcome:
            return None
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        choices = list(decision.availability.choices)
        if decision.token is not None and decision.token.mode == 'timeline_actor_selectable':
            pick = next((c for c in choices if c.actor_id == actor_id), choices[0])
            session.submit(command_from_json(dict(pick.command_template)))
            continue
        wanted = next(
            (c for c in choices if c.actor_id == actor_id and c.action_id == action_id),
            None,
        )
        if wanted is not None:
            return wanted
        choice = choices[0]
        targets = []
        if choice.target_query and choice.target_query.selection_mode == 'explicit':
            targets = list(choice.target_query.candidate_ids)[:1]
        session.submit(command_from_json({**choice.command_template, 'target_ids': targets}))
    return None


def _cast(session, choice, targets):
    result = session.submit(command_from_json({**choice.command_template, 'target_ids': targets}))
    assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes


def test_assembly_selection_differs_by_eidolon_prefix_and_stays_isolated():
    rules = _rules()
    lynx_e0 = assemble_character_build(
        rules, _build('1110', eidolon_level=0)
    )
    lynx_e6 = assemble_character_build(
        rules, _build('1110', eidolon_level=6)
    )
    assert lynx_e0.assembly_status == lynx_e6.assembly_status == 'assembled'
    assert len(lynx_e0.selected_eidolon_slot_ids) == 0
    assert len(lynx_e6.selected_eidolon_slot_ids) == 6
    assert lynx_e0.selected_eidolon_slot_ids != lynx_e6.selected_eidolon_slot_ids
    assert lynx_e0.result_fingerprint != lynx_e6.result_fingerprint

    session_e0 = _session([_unit('1110', 'lynx', _build('1110', eidolon_level=0))])
    session_e6 = _session([_unit('1110', 'lynx', _build('1110', eidolon_level=6), position=1)])
    assert 'MAvatar_Lynx_00_Rank01_ListenBeforeDealHeal01' not in json.dumps(
        session_e0.state.units['lynx'].flags
    )
    assert 'MAvatar_Lynx_00_Rank01_ListenBeforeDealHeal01' in json.dumps(
        session_e6.state.units['lynx'].flags
    )
    # The E0 instance state is unaffected by the later E6 instance.
    assert list(session_e0.state.units['lynx'].flags.get('selected_eidolon_slot_ids') or ()) == []


def test_arlan_e4_prefix_adds_the_revive_modifier_only_when_selected():
    rules = _rules()
    arlan_e0 = _session([_unit('1008', 'arlan', _build('1008', eidolon_level=0))])
    arlan_e4 = _session([_unit('1008', 'arlan', _build('1008', eidolon_level=4), position=1)])
    assert _status(arlan_e0.state.units['arlan'], 'MAvatar_Arlan_00_PassiveSkill_UnDead') is None
    assert _status(arlan_e4.state.units['arlan'], 'MAvatar_Arlan_00_PassiveSkill_UnDead') is not None


def test_lynx_e4_and_e6_prefixes_change_skill_target_effects():
    rules = _rules()
    arlan = _build('1008', level=80, promotion=6)
    plain = _session([
        _unit('1008', 'arlan', arlan, 0),
        _unit('1110', 'lynx', _build('1110', eidolon_level=0), 1),
    ])
    choice = _advance_to(plain, 'lynx', 'avatar_skill:111002')
    assert choice is not None
    _cast(plain, choice, ['arlan'])
    plain_target = plain.state.units['arlan']
    assert _status(plain_target, 'MAvatar_Lynx_00_Rank04_AddAttackRatio') is None
    assert _status(plain_target, 'MAvatar_Lynx_00_Rank02_Resist') is None

    e6 = _session([
        _unit('1008', 'arlan', arlan, 0),
        _unit('1110', 'lynx', _build('1110', eidolon_level=6), 1),
    ])
    choice = _advance_to(e6, 'lynx', 'avatar_skill:111002')
    assert choice is not None
    _cast(e6, choice, ['arlan'])
    target = e6.state.units['arlan']
    rank04 = _status(target, 'MAvatar_Lynx_00_Rank04_AddAttackRatio')
    assert rank04 is not None
    rank04_modifier = rank04.get('modifiers') or []
    lynx_max_hp = effective_unit_stat(e6.state.units['lynx'], 'max_hp').value
    attack_terms = [
        item for item in rank04_modifier
        if item.get('bucket') == 'attribute' and item.get('key') == 'attack_delta'
    ]
    assert attack_terms and attack_terms[0]['value'] == pytest.approx(
        lynx_max_hp * 0.03, rel=1e-6
    )
    assert _status(target, 'MAvatar_Lynx_00_Rank02_Resist') is not None
    # E6 adds 6% of Lynx Max HP plus 30% Effect RES to the Survival Response.
    hp_convert = effective_unit_stat(target, 'hp_convert').value
    assert hp_convert > lynx_max_hp * 0.05
    assert hp_convert == pytest.approx(lynx_max_hp * 0.115, rel=0.01)
    assert effective_unit_stat(target, 'effect_resistance').value == pytest.approx(0.3)


def test_march_e2_prefix_grants_the_entry_shield_only_when_selected():
    rules = _rules()
    plain = _session([_unit('1001', 'march', _build('1001', eidolon_level=0))])
    e2 = _session([_unit('1001', 'march', _build('1001', eidolon_level=2), position=1)])
    assert _status(plain.state.units['march'], 'MAvatar_March7th_00_Rank02_Shield') is None
    shield = _status(e2.state.units['march'], 'MAvatar_March7th_00_Rank02_Shield')
    assert shield is not None
    assert shield.get('duration') == pytest.approx(3.0)

def test_arlan_e4_consumes_its_formal_revive_after_native_lethal_damage():
    from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
    from hsr.simulator_v8_clean_core.session import BattleSession
    from hsr.simulator_v8_clean_core.systems.damage import (
        DamagePacket,
        DamageSourceFrame,
        DamageSystem,
    )

    rules = _rules()
    scenario = _template()
    scenario['units'] = [_unit('1008', 'arlan', _build('1008', eidolon_level=4))]
    session = BattleSession(rules, scenario, diagnostics="full")
    assert any(
        detail.get('modifier_name') == 'MAvatar_Arlan_00_PassiveSkill_UnDead'
        for detail in session.state.units['arlan'].flags['status_details']
    )
    enemy_id = next(
        unit_id
        for unit_id, unit in session.state.units.items()
        if unit.side == 'enemy'
    )
    packet = DamagePacket(
        attacker_id=enemy_id,
        target_id='arlan',
        attack_type='test',
        damage_formula_family='true_damage',
        amount=session.state.units['arlan'].hp + 1,
        amount_stage='fixed_final',
        source_frame=DamageSourceFrame(
            owner_id=enemy_id,
            source_id=enemy_id,
            source_kind='unit',
            sequence_id='r05:arlan-e4-lethal',
            target_id='arlan',
        ),
        source_trace={'kind': 'validation_fixture', 'scope': 'R05 formal E4 consumer'},
    )
    damage = DamageSystem(rules).apply_packet(session.state, packet)
    assert damage.ok, damage.errors
    result = CombatExecutor(rules).commit_eventful_transition(
        session.state,
        mutations=damage.mutations,
        events=damage.events,
        records=damage.records,
        rng_events=damage.rng_events,
        producer_kind='damage',
        producer_id='r05:arlan-e4-lethal',
        actor_id=enemy_id,
        producer_ok=damage.ok,
        blocked_reason=','.join(damage.errors),
    )
    assert not result.errors, result.errors
    revived = result.after_state.units['arlan']
    assert revived.hp > 0
    assert revived.lifecycle_status == 'active'
    assert 'pending_defeat' not in revived.flags


def test_public_enemy_lethal_hit_runs_e4_rescue():
    from hsr.simulator_v8_clean_core.session import (
        BattleSession,
        command_from_json,
    )

    rules = _rules()
    scenario = _template()
    scenario['units'] = [
        _unit('1008', 'arlan', _build('1008', eidolon_level=4), initial={
            'hp_mode': 'ratio', 'hp_value': '0.001',
            'initial_energy': '0', 'initial_resource_values': [],
        })
    ]
    session = BattleSession(rules, scenario, diagnostics="full")
    for _ in range(8):
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        choice = decision.availability.choices[0]
        if decision.token is not None and decision.token.mode == 'timeline_actor_selectable':
            enemy_choice = next(
                (
                    candidate
                    for candidate in decision.availability.choices
                    if session.state.units[candidate.actor_id].side == 'enemy'
                ),
                choice,
            )
            session.submit(command_from_json(dict(enemy_choice.command_template)))
            continue
        targets = []
        if (
            choice.target_query
            and choice.target_query.selection_mode == 'explicit'
        ):
            candidates = list(choice.target_query.candidate_ids)
            if candidates:
                targets = [candidates[0]]
        result = session.submit(
            command_from_json(
                {**choice.command_template, 'target_ids': targets}
            )
        )
        assert result.transition.outcome.successor_eligible, {
            'actor': choice.actor_id,
            'action': choice.action_id,
            'reasons': result.transition.outcome.reason_codes,
        }
        if choice.actor_id != 'arlan':
            following = session.advance()
            assert following.ready, following.blocked_reason
            unit = session.state.units['arlan']
            assert unit.hp > 1.2, (unit.hp, unit.lifecycle_status)
            assert unit.lifecycle_status == 'active'
            return
    raise AssertionError('no enemy hit reached')


def test_native_e4_rescue_writes_pass_the_source_audit():
    from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    from hsr.simulator_v8_clean_core.session import BattleSession
    from hsr.simulator_v8_clean_core.systems.damage import (
        DamagePacket,
        DamageSourceFrame,
        DamageSystem,
    )

    rules = _rules()
    scenario = _template()
    scenario['units'] = [_unit('1008', 'arlan', _build('1008', eidolon_level=4))]
    session = BattleSession(rules, scenario, diagnostics="full")
    state = session.state
    enemy = next(
        unit_id for unit_id, unit in state.units.items() if unit.side == 'enemy'
    )
    packet = DamagePacket(
        enemy,
        'arlan',
        'test',
        'true_damage',
        amount=state.units['arlan'].hp + 1,
        amount_stage='fixed_final',
        source_frame=DamageSourceFrame(
            owner_id=enemy,
            source_id=enemy,
            source_kind='unit',
            sequence_id='r05:e4:audit',
            target_id='arlan',
        ),
        source_trace={'kind': 'validation_fixture', 'scope': 'native E4 audit'},
    )
    damage = DamageSystem(rules).apply_packet(state, packet)
    assert damage.ok, damage.errors
    result = CombatExecutor(rules).commit_eventful_transition(
        state,
        mutations=damage.mutations,
        events=damage.events,
        records=damage.records,
        rng_events=damage.rng_events,
        producer_kind='damage',
        producer_id='r05:e4:audit',
        actor_id=enemy,
        producer_ok=True,
    )
    assert not result.errors, result.errors
    assert result.after_state.units['arlan'].hp > 0
    initial = {mutation.stable_id() for mutation in damage.mutations}
    writes = tuple(
        mutation
        for mutation in result.mutations
        if mutation.stable_id() not in initial
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(writes, result.records)
    assert audit.ok, [
        {'reason': violation.reason, 'path': violation.path}
        for violation in audit.violations
    ]


def test_limbo_rescue_admission_verifies_its_native_source_identity():
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
    from hsr.simulator_v8_clean_core.immutable_json import thaw_json
    from hsr.simulator_v8_clean_core.session import BattleSession
    from hsr.simulator_v8_clean_core.systems.damage import (
        DamagePacket,
        DamageSourceFrame,
        DamageSystem,
    )
    from hsr.simulator_v8_clean_core.systems.queue import QueueSystem

    rules = _rules()
    scenario = _template()
    scenario['units'] = [_unit('1008', 'arlan', _build('1008', eidolon_level=4))]
    session = BattleSession(rules, scenario, diagnostics="full")
    state = session.state
    enemy = next(
        unit_id for unit_id, unit in state.units.items() if unit.side == 'enemy'
    )
    packet = DamagePacket(
        enemy,
        'arlan',
        'test',
        'true_damage',
        amount=state.units['arlan'].hp + 1,
        amount_stage='fixed_final',
        source_frame=DamageSourceFrame(
            owner_id=enemy,
            source_id=enemy,
            source_kind='unit',
            sequence_id='r05:e4:rescue-identity',
            target_id='arlan',
        ),
        source_trace={'kind': 'validation_fixture', 'scope': 'rescue identity'},
    )
    damage = DamageSystem(rules).apply_packet(state, packet)
    assert damage.ok, damage.errors
    executor = CombatExecutor(rules)
    captured = []
    original = executor._execute_pending_limbo_queue_rescue

    def observe(candidate):
        captured.append(candidate)
        return original(candidate)

    executor._execute_pending_limbo_queue_rescue = observe
    result = executor.commit_eventful_transition(
        state,
        mutations=damage.mutations,
        events=damage.events,
        records=damage.records,
        rng_events=damage.rng_events,
        producer_kind='damage',
        producer_id='r05:e4:rescue-identity',
        actor_id=enemy,
        producer_ok=True,
    )
    assert not result.errors, result.errors
    assert len(captured) == 1
    pending = captured[0]
    queue_name, entry = next(
        (name, entry)
        for name, entries in pending.queues.items()
        for entry in entries
        if entry.get('actor_id') == 'arlan'
        and entry.get('limbo_rescue_admission')
    )
    resolution = rules.queue_resolution_for_intent(entry['queue_intent_id'])
    control = QueueSystem().plan_entry(
        pending, queue_name, entry['entry_id'], resolution, rules=rules
    )
    assert control.ok, control.blocked_reason
    for field in (
        'pending_defeat_id',
        'source_event_id',
        'source_task_id',
        'source_status_instance_id',
        'source_modifier_name',
    ):
        changed = thaw_json(entry)
        changed['limbo_rescue_admission'][field] = 'not-the-native-identity'
        tampered_state = replace(
            pending,
            queues={
                **pending.queues,
                queue_name: [
                    changed
                    if candidate.get('entry_id') == entry['entry_id']
                    else candidate
                    for candidate in pending.queues[queue_name]
                ],
            },
        )
        tampered = QueueSystem().plan_entry(
            tampered_state,
            queue_name,
            entry['entry_id'],
            resolution,
            rules=rules,
        )
        assert not tampered.ok, {'field': field, 'ok': tampered.ok}

    # Audit transport is never runtime authority, even when both copies agree.
    for variant in ('empty_trace', 'joint_instance_forgery'):
        changed = thaw_json(entry)
        if variant == 'empty_trace':
            changed['source_trace'] = {}
        else:
            changed['limbo_rescue_admission']['source_status_instance_id'] = 'nonexistent-instance'
            changed['source_trace']['limbo_rescue_source_status_instance_id'] = 'nonexistent-instance'
        changed = json.loads(json.dumps(changed))
        candidate = replace(pending, queues={
            **pending.queues,
            queue_name: [changed if item.get('entry_id') == entry['entry_id'] else item
                         for item in pending.queues[queue_name]],
        })
        plan = QueueSystem().plan_entry(candidate, queue_name, entry['entry_id'], resolution, rules=rules)
        assert plan.ok is (variant == 'empty_trace'), (variant, plan.blocked_reason)
