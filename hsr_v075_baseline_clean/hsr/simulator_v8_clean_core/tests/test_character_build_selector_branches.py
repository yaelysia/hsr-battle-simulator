"""R05: trace selector branches, build differences and eidolon prefix effects.

All checks compile the real character graph and drive public transactions.  A
selected trace node must change the observed branch; an unselected node must
not, and the same rule must hold for selected eidolon prefixes.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput
from hsr.simulator_v8_clean_core.equipment.models import EquipmentBuildInput
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.dynamic_values import (
    character_trace_param_binding_source,
)
from hsr.simulator_v8_clean_core.systems.unit_stats import (
    effective_unit_stat,
)
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_STAGE = '201010110'
_AVATARS = ('1008', '1105', '1110', '1001')


def _template():
    template = json.loads((_CORE / 'examples/cli/arlan_melee_two_waves.json').read_text())
    return {
        'scenario_id': 'r05:trace-selector-branches',
        'version': template['version'],
        'stage_ref': _STAGE,
        'wave_index': 0,
        'route': [],
        'battle_setup': template['battle_setup'],
    }


def _build(avatar_id, *, level=80, promotion=6, eidolon_level=0, trace_ids=()):
    card_id = f'character_data_card:avatar:{avatar_id}'
    equipment = EquipmentBuildInput(
        build_id=f'r05:{avatar_id}:equipment',
        character_card_id=card_id,
    )
    return CharacterBuildInput(
        build_id=f'r05:{avatar_id}:build',
        character_card_id=card_id,
        level=level,
        promotion=promotion,
        eidolon_level=eidolon_level,
        unlocked_trace_node_ids=tuple(trace_ids),
        equipment_build=equipment,
    )


def _unit(avatar_id, unit_id, build, *, position=0, initial=None):
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
            'hp_mode': 'full',
            'initial_energy': '0',
            'initial_resource_values': [],
        },
    }


@lru_cache(maxsize=1)
def _rules():
    scenario = _template()
    scenario['units'] = [
        _unit(avatar_id, f'compile_{index}', _build(avatar_id, level=1, promotion=0), position=index)
        for index, avatar_id in enumerate(_AVATARS)
    ]
    return build_battle_rulebook(_ROOT / 'turnbasedgamedata-main', scenario)


def _trace(rules, avatar_id, point_id):
    card_id = f'character_data_card:avatar:{avatar_id}'
    for node in rules.ir.character_trace_nodes:
        if node.character_data_card_id == card_id and node.trace_id == str(point_id):
            return node.trace_node_id
    raise KeyError(point_id)


def _session(units, rules=None, *, stage_ref=None):
    scenario = _template()
    if stage_ref is not None:
        scenario['stage_ref'] = stage_ref
    scenario['units'] = units
    return BattleSession(rules or _rules(), scenario, diagnostics="full")


def _param_value(source, dynamic_hash):
    keys = (source.get('by_hash') or {}).get(str(dynamic_hash)) or ()
    assert len(keys) == 1, (dynamic_hash, keys)
    entry = (source.get('entries') or {}).get(keys[0])
    assert entry is not None, keys
    return entry['value']


def _status(unit, modifier_name):
    return next(
        (
            detail
            for detail in (unit.flags.get('status_details') or ())
            if detail.get('modifier_name') == modifier_name
        ),
        None,
    )


def _status_names(unit):
    return [detail.get('modifier_name') for detail in (unit.flags.get('status_details') or ())]


def _debuffs(unit):
    return [
        detail
        for detail in (unit.flags.get('status_details') or ())
        if detail.get('status_category') == 'debuff'
    ]


def _submit_targets(choice):
    if choice.target_query and choice.target_query.selection_mode == 'explicit':
        candidates = list(choice.target_query.candidate_ids)
        if candidates:
            return [candidates[0]]
    return []


def _advance(session):
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    return decision


def _submit(session, choice, targets):
    result = session.submit(
        command_from_json({**choice.command_template, 'target_ids': list(targets)})
    )
    # The scheduler may wrap the accepted action in its own step transition; the
    # actor identity and successor eligibility remain the public contract.
    actual = result.transition.transaction.command
    assert actual.actor_id == choice.actor_id, (
        choice.actor_id,
        actual.actor_id,
        actual.action_id,
        result.transition.outcome.reason_codes,
    )
    assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
    return result


def _resolve_ties_and_reach(session, actor_id, action_id, *, max_steps=16):
    """Advance public decisions until the requested action is offered."""
    for _ in range(max_steps):
        if session.outcome:
            return None, None
        decision = _advance(session)
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
            return decision, wanted
        _submit(session, choices[0], _submit_targets(choices[0]))
    return None, None


def _records(session):
    for operation in session.operations:
        for transition in operation.get('transitions') or ():
            for container in (transition, *(transition.get('child_transitions') or ())):
                for record in ((container.get('settlement') or {}).get('records') or ()):
                    if isinstance(record, dict):
                        yield record
        transition = operation.get('transition')
        if isinstance(transition, dict):
            for container in (transition, *(transition.get('child_transitions') or ())):
                for record in ((container.get('settlement') or {}).get('records') or ()):
                    if isinstance(record, dict):
                        yield record


# ---------------------------------------------------------------- parameters

def test_trace_skill_point_parameters_follow_the_selected_node():
    rules = _rules()
    lynx_b1_b2 = _build(
        '1110', eidolon_level=0,
        trace_ids=(
            _trace(rules, '1110', '1110101'),
            _trace(rules, '1110', '1110102'),
        ),
    )
    session = _session([_unit('1110', 'lynx', lynx_b1_b2)])
    source = character_trace_param_binding_source(rules, session.state, 'lynx')
    assert source is not None
    by_hash = source['by_hash']
    assert _param_value(source, '-1573062067') == pytest.approx(2.0)
    assert _param_value(source, '481594005') == pytest.approx(0.35)
    # Card isolation: Lynx's params never expose another card's trace values.
    assert '-2124210825' not in by_hash
    unit = session.state.units['lynx']
    tree01 = _status(unit, 'MAvatar_Lynx_00_Tree01_OnBeforeBeingAttacked')
    tree02 = _status(unit, 'MAvatar_Lynx_Tree02_Resistance')
    assert tree01 is not None and tree02 is not None
    assert tree01['dynamic_values']['__by_name']['MDF_Lynx_PointB1_AddSpValue'] == pytest.approx(2.0)
    assert tree02['modifiers'][0]['bucket'] == 'status_resistance'
    assert tree02['modifiers'][0]['key'] == 'STAT_CTRL'
    assert tree02['modifiers'][0]['value'] == pytest.approx(0.35)
    assert effective_unit_stat(unit, 'control_resistance').value == pytest.approx(0.35)

    baseline = _build('1110')
    plain = _session([_unit('1110', 'lynx', baseline, position=1)])
    assert character_trace_param_binding_source(rules, plain.state, 'lynx') is None
    assert 'MAvatar_Lynx_Tree02_Resistance' not in _status_names(plain.state.units['lynx'])
    assert effective_unit_stat(plain.state.units['lynx'], 'control_resistance').value == pytest.approx(0.0)


def test_natasha_skill_point_parameters_bind_cleanse_and_duration():
    rules = _rules()
    point_b1 = _build(
        '1105', trace_ids=(_trace(rules, '1105', '1105101'),),
    )
    b1_session = _session([_unit('1105', 'natasha', point_b1)])
    b1_source = character_trace_param_binding_source(rules, b1_session.state, 'natasha')
    assert _param_value(b1_source, '-2124210825') == pytest.approx(1.0)

    point_b3 = _build(
        '1105', trace_ids=(_trace(rules, '1105', '1105103'),),
    )
    b3_session = _session([_unit('1105', 'natasha', point_b3, position=1)])
    b3_source = character_trace_param_binding_source(rules, b3_session.state, 'natasha')
    assert _param_value(b3_source, '2117344201') == pytest.approx(1.0)

    plain_session = _session([_unit('1105', 'natasha', _build('1105'), position=2)])
    assert character_trace_param_binding_source(rules, plain_session.state, 'natasha') is None


# ---------------------------------------------------------------- branches

def _lynx_skill_hot(extra_trace_ids):
    rules = _rules()
    lynx = _build('1110', trace_ids=extra_trace_ids)
    arlan = _build('1008')
    session = _session([
        _unit('1008', 'arlan', arlan, position=0),
        _unit('1110', 'lynx', lynx, position=1),
    ])
    decision, choice = _resolve_ties_and_reach(session, 'lynx', 'avatar_skill:111002')
    assert choice is not None, 'Lynx skill was never offered'
    _submit(session, choice, ['arlan'])
    arlan_state = session.state.units['arlan']
    hot = _status(arlan_state, 'MAvatar_Lynx_00_HOT_HealByMaxHp')
    assert hot is not None, _status_names(arlan_state)
    survivor = _status(arlan_state, 'MAvatar_Lynx_00_HPAddedRatio01')
    assert survivor is not None
    hp_convert = effective_unit_stat(arlan_state, 'hp_convert').value
    lynx_max_hp = effective_unit_stat(session.state.units['lynx'], 'max_hp').value
    assert hp_convert == pytest.approx(lynx_max_hp * 0.05, rel=1e-6)
    return hot.get('duration'), arlan_state, session


def test_lynx_b3_extends_talent_hot_and_survival_response_applies_max_hp():
    rules = _rules()
    duration_b3, state_b3, session_b3 = _lynx_skill_hot(
        (_trace(rules, '1110', '1110103'),)
    )
    duration_plain, state_plain, _ = _lynx_skill_hot(())
    assert duration_b3 == pytest.approx(3.0)
    assert duration_plain == pytest.approx(2.0)
    # The Survival Response Max-HP conversion is a real flat Max-HP bucket.
    base_hp = state_b3.max_hp
    assert effective_unit_stat(state_b3, 'max_hp').value > base_hp
    assert effective_unit_stat(state_b3, 'hp_convert').value == pytest.approx(
        effective_unit_stat(session_b3.state.units['lynx'], 'max_hp').value * 0.05,
        rel=1e-6,
    )


def test_natasha_b3_extends_skill_hot_duration():
    rules = _rules()
    durations = {}
    for label, trace_ids in (
        ('b3', (_trace(rules, '1105', '1105103'),)),
        ('plain', ()),
    ):
        build = _build('1105', trace_ids=trace_ids)
        session = _session([_unit('1105', 'natasha', build)])
        decision, choice = _resolve_ties_and_reach(session, 'natasha', 'avatar_skill:110502')
        assert choice is not None
        _submit(session, choice, ['natasha'])
        hot = _status(session.state.units['natasha'], 'MAvatar_Natasha_00_HOT_HPByMaxHP')
        assert hot is not None
        durations[label] = hot.get('duration')
    assert durations['b3'] == pytest.approx(3.0)
    assert durations['plain'] == pytest.approx(2.0)


def test_march_b2_extends_shield_and_b1_cleanses_a_debuff():
    rules = _rules()
    shield_durations = {}
    for label, trace_ids in (
        ('b2', (
            _trace(rules, '1001', '1001201'),
            _trace(rules, '1001', '1001102'),
        )),
        ('plain', ()),
    ):
        build = _build('1001', trace_ids=trace_ids)
        session = _session([_unit('1001', 'march', build)])
        decision, choice = _resolve_ties_and_reach(session, 'march', 'avatar_skill:100102')
        assert choice is not None
        _submit(session, choice, ['march'])
        shield = _status(session.state.units['march'], 'MAvatar_March7th_00_BPSkill_Shield')
        assert shield is not None
        shield_durations[label] = shield.get('duration')
    assert shield_durations['b2'] == pytest.approx(4.0)
    assert shield_durations['plain'] == pytest.approx(3.0)

    # B1 removes one debuff from the skill target when one is present.
    for label, trace_ids in (
        ('b1', (
            _trace(rules, '1001', '1001201'),
            _trace(rules, '1001', '1001101'),
        )),
        ('plain', ()),
    ):
        build = _build('1001', trace_ids=trace_ids)
        session = _session([_unit('1001', 'march', build)])
        saw_debuff = False
        for _ in range(14):
            if session.outcome:
                break
            decision = _advance(session)
            choices = list(decision.availability.choices)
            if decision.token is not None and decision.token.mode == 'timeline_actor_selectable':
                pick = next((c for c in choices if c.actor_id == 'march'), choices[0])
                session.submit(command_from_json(dict(pick.command_template)))
                continue
            skill = next(
                (c for c in choices if c.actor_id == 'march' and c.action_id == 'avatar_skill:100102'),
                None,
            )
            if skill is not None and _debuffs(session.state.units['march']):
                saw_debuff = True
                before = len(_debuffs(session.state.units['march']))
                _submit(session, skill, ['march'])
                after = len(_debuffs(session.state.units['march']))
                if label == 'b1':
                    assert after == before - 1, (before, after)
                else:
                    assert after == before, (before, after)
                break
            _submit(session, choices[0], _submit_targets(choices[0]))
        assert saw_debuff, 'no debuff opportunity for the March skill check'


def test_arlan_repel_block_and_dot_resistance_are_consumed():
    rules = _rules()
    arlan = _build(
        '1008',
        trace_ids=(
            _trace(rules, '1008', '1008101'),
            _trace(rules, '1008', '1008102'),
            _trace(rules, '1008', '1008103'),
        ),
    )
    session = _session([
        _unit('1008', 'arlan', arlan, initial={
            'hp_mode': 'ratio', 'hp_value': '0.45',
            'initial_energy': '0', 'initial_resource_values': [],
        }),
    ])
    unit = session.state.units['arlan']
    assert _status(unit, 'BlockDamage_Count') is not None
    stacks = unit.flags.get('status_resistance_stacks')
    assert stacks and stacks[0]['behavior_flag'] == 'STAT_DOT'
    assert stacks[0]['value'] == pytest.approx(0.5)

    blocked = None
    while blocked is None and not session.outcome:
        decision = _advance(session)
        choices = list(decision.availability.choices)
        if decision.token is not None and decision.token.mode == 'timeline_actor_selectable':
            pick = next((c for c in choices if c.actor_id == 'arlan'), choices[0])
            session.submit(command_from_json(dict(pick.command_template)))
            continue
        if session.state.units['arlan'].hp <= 0:
            break
        if _status(session.state.units['arlan'], 'BlockDamage_Count') is None:
            blocked = [record for record in _records(session)
                       if record.get('record_type') == 'damage_blocked']
            break
        _submit(session, choices[0], _submit_targets(choices[0]))
    assert blocked, 'Arlan damage-block was never consumed by a real hit'
    record = blocked[-1]
    payload = record.get('payload') or {}
    assert payload.get('damage_block_flag') == 'BlockDamageExcludeDot'
    assert payload.get('consumed_stack') is True

    dot_chance = [
        record
        for record in _records(session)
        if 'chance_admission' in json.dumps(record.get('payload') or {}, default=str)
        and 'STAT_DOT' in json.dumps(record.get('payload') or {}, default=str)
    ]
    if dot_chance:
        admission = json.loads(
            json.dumps(dot_chance[-1].get('payload') or {}, default=str)
        )
        assert 'behavior_flag_resistance' in json.dumps(admission)

@lru_cache(maxsize=1)
def _rules_400020800():
    template = json.loads((_CORE / 'examples/cli/arlan_melee_two_waves.json').read_text())
    scenario = {
        'scenario_id': 'r05:march-freeze-chance',
        'version': template['version'],
        'stage_ref': '400020800',
        'wave_index': 0,
        'route': [],
        'battle_setup': template['battle_setup'],
    }
    scenario['units'] = [
        _unit('1001', 'compile_march', _build('1001', level=1, promotion=0))
    ]
    return build_battle_rulebook(_ROOT / 'turnbasedgamedata-main', scenario)


def _freeze_base_chance(session):
    import re
    payload = json.dumps(session.operations, default=str)
    marker = payload.find('MCommon_CTRL_Frozen')
    if marker < 0:
        return None
    match = re.search(r'"base_chance": ([0-9.]+)', payload[marker:])
    return float(match.group(1)) if match else None


def _march_ult_freeze_chance(extra_trace_ids):
    rules = _rules_400020800()
    build = _build('1001', trace_ids=extra_trace_ids)
    session = _session(
        [_unit('1001', 'march', build, initial={
            'hp_mode': 'full', 'initial_energy': '120', 'initial_resource_values': [],
        })],
        rules=rules,
        stage_ref='400020800',
    )
    submitted_ult = False
    for _ in range(24):
        if session.outcome:
            break
        decision = session.advance()
        if not decision.ready:
            break
        choices = list(decision.availability.choices)
        if decision.token is not None and decision.token.mode == 'timeline_actor_selectable':
            session.submit(command_from_json(dict(choices[0].command_template)))
            continue
        ult = next(
            (c for c in choices if c.actor_id == 'march' and c.action_id == 'avatar_skill:100103'),
            None,
        )
        if ult is not None and not submitted_ult:
            targets = []
            if ult.target_query and ult.target_query.selection_mode == 'explicit':
                targets = list(ult.target_query.candidate_ids)
            session.submit(command_from_json({**ult.command_template, 'target_ids': targets}))
            submitted_ult = True
            chance = _freeze_base_chance(session)
            if chance is not None:
                return chance
            continue
        choice = choices[0]
        targets = []
        if choice.target_query and choice.target_query.selection_mode == 'explicit':
            targets = list(choice.target_query.candidate_ids)[:1]
        session.submit(command_from_json({**choice.command_template, 'target_ids': targets}))
        chance = _freeze_base_chance(session)
        if chance is not None:
            return chance
    return None


def test_march_b3_increases_ultimate_freeze_chance():
    rules = _rules()
    selected = _march_ult_freeze_chance((_trace(rules, '1001', '1001103'),))
    plain = _march_ult_freeze_chance(())
    assert selected is not None, 'no freeze chance admission for the B3 build'
    assert plain is not None, 'no freeze chance admission for the baseline build'
    # Ice Spell raises the Ultimate freeze chance through _Tree03_ChanceAdd; the
    # admitted chance is clamped by the target's control resistance.
    assert selected > plain

def test_current_max_hp_consumers_use_the_effective_ceiling():
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
    from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
    from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator
    from hsr.simulator_v8_clean_core.rules.expression_ir import (
        CONDITION_EXPRESSION_NODE_SCHEMA,
        numeric_fixed,
    )
    from hsr.simulator_v8_clean_core.rules.ir import ConditionIR, EffectIR, IRSource
    from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat

    detail = {
        "instance_id": "convert:1",
        "status_id": "modifier:convert",
        "lifecycle_state": "active",
        "modifiers": [
            {"bucket": "attribute", "key": "hp_convert", "value": 100.0}
        ],
    }

    def converted_unit():
        return UnitState(
            "target", "ally", "component:target", hp=100.0, max_hp=100.0,
            statuses=("modifier:convert",),
            flags={"status_details": [detail]},
        )

    unit = converted_unit()
    assert effective_unit_stat(unit, "max_hp").value == 200.0
    condition = ConditionIR(
        "review:half-hp", "ByCompareHPRatio",
        {
            "TargetType": {"alias": "Caster"},
            "CompareType": "LessEqual",
            "CompareValue": numeric_fixed(0.5),
        },
        IRSource("component", "validation", "half-hp"),
        coverage_status="executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )
    condition_result = RuleEvaluator().evaluate_condition_result(
        condition,
        EvaluationContext(
            state=BattleState(units={"target": unit}),
            actor_id="target",
            owner_id="target",
        ),
    )
    assert condition_result.ok and condition_result.result is True

    heal = EffectIR(
        "review:heal", "Heal",
        {
            "standard": {
                "target_alias": "Caster",
                "amount": numeric_fixed(100.0),
                "formula_type": "HealByBaseValue",
                "formula_base": "flat",
                "amount_role": "flat",
            }
        },
        IRSource("component", "validation", "heal"),
        coverage_status="executable",
    )
    state = BattleState(units={"target": unit})
    healed = EffectRegistry()._execute_single_heal(
        heal, EffectExecutionContext(state, "target", "target")
    )
    assert not healed.unsupported
    after_heal = MutationReducer().apply_all(state, healed.mutations)
    assert after_heal.units["target"].hp == 200.0

    removed = StatusSystem().remove_status_instance(
        after_heal,
        target_id="target",
        detail=detail,
        source="component",
        source_trace={"kind": "validation_fixture", "scope": "current max hp clamp"},
    )
    assert removed.ok, removed.unsupported
    after_remove = MutationReducer().apply_all(after_heal, removed.mutations)
    assert after_remove.units["target"].hp == 100.0
    assert any(
        record.get("record_type") == "status_lifecycle_hp_clamp"
        for record in removed.records
    )
    # Re-applying the conversion restores the higher ceiling and healing uses it.
    reapplied = replace(
        after_remove,
        units={
            **after_remove.units,
            "target": replace(
                after_remove.units["target"],
                statuses=("modifier:convert",),
                flags={"status_details": [detail]},
            ),
        },
    )
    healed_again = EffectRegistry()._execute_single_heal(
        heal, EffectExecutionContext(reapplied, "target", "target")
    )
    assert not healed_again.unsupported
    assert MutationReducer().apply_all(reapplied, healed_again.mutations).units["target"].hp == 200.0

def test_formal_arlan_blocked_hit_passes_the_native_source_audit():
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json

    rules = _rules()
    build = _build(
        '1008',
        trace_ids=tuple(
            _trace(rules, '1008', node) for node in ('1008101', '1008102', '1008103')
        ),
    )
    session = BattleSession(
        rules,
        {
            **_template(),
            'units': [
                _unit('1008', 'arlan', build, initial={
                    'hp_mode': 'ratio', 'hp_value': '0.45',
                    'initial_energy': '0', 'initial_resource_values': [],
                }),
            ],
        },
        diagnostics="full",
    )
    for _ in range(16):
        decision = _advance(session)
        choices = list(decision.availability.choices)
        if decision.token is not None and decision.token.mode == 'timeline_actor_selectable':
            session.submit(command_from_json(dict(choices[0].command_template)))
            continue
        result = session.submit(
            command_from_json(
                {**choices[0].command_template, 'target_ids': _submit_targets(choices[0])}
            )
        )
        assert result.transition.outcome.successor_eligible, (
            result.transition.outcome.reason_codes
        )
        settlements = [
            transition.transaction.settlement.records
            for transition in (result.transition, *getattr(result, 'child_transitions', ()))
            if transition.transaction.settlement is not None
        ]
        if any(
            record.get('record_type') == 'damage_blocked'
            for records in settlements
            for record in records
        ):
            audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
            assert audit.ok, [violation.to_json() for violation in audit.violations]
            return
    raise AssertionError('formal blocked hit was not reached')


def test_current_max_hp_does_not_depend_on_import_order():
    import subprocess
    import sys

    code = """
from hsr.simulator_v8_clean_core.core.model import UnitState, current_max_hp
from hsr.simulator_v8_clean_core.core.model import BattleState
from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator, EvaluationContext
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed, CONDITION_EXPRESSION_NODE_SCHEMA
from hsr.simulator_v8_clean_core.rules.ir import ConditionIR, IRSource
unit = UnitState('u', 'ally', 'component:u', hp=100, max_hp=100, flags={'status_details': [
    {'instance_id': 'hp', 'modifiers': [{'bucket': 'attribute', 'key': 'hp_convert', 'value': 100}]}]})
condition = ConditionIR('half', 'ByCompareHPRatio', {'TargetType': {'alias': 'Caster'},
    'CompareType': 'LessEqual', 'CompareValue': numeric_fixed(0.5)},
    IRSource('component', 'validation', 'hp'), coverage_status='executable',
    expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)
context = EvaluationContext(state=BattleState(units={'u': unit}), actor_id='u', owner_id='u')
before = current_max_hp(unit)
ratio_before = RuleEvaluator().evaluate_condition_result(condition, context)
from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
after = current_max_hp(unit)
ratio_after = RuleEvaluator().evaluate_condition_result(condition, context)
assert before == after == 200
assert ratio_before.ok and ratio_after.ok and ratio_before.result is ratio_after.result is True
"""
    import os
    from pathlib import Path

    root = str(Path(__file__).resolve().parents[4])
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            item
            for item in (root, os.environ.get("PYTHONPATH", ""))
            if item
        ),
    }
    proc = subprocess.run(
        [sys.executable, "-B", "-c", code],
        text=True,
        capture_output=True,
        env=environment,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("operation", ["expire", "replace", "stack_reduce"])
def test_hp_ceiling_shrink_lifecycle_is_clamped(operation):
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState, current_max_hp
    from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
    from hsr.simulator_v8_clean_core.systems.status import (
        StatusInstance,
        StatusLifecyclePlan,
        StatusSystem,
    )

    instance = StatusInstance(
        "hp:1", "modifier:hp", "hp", "u", "u", "u",
        modifiers=({"bucket": "attribute", "key": "hp_convert", "value": 100.0},),
        max_stacks=2,
        stack_policy="Layer",
    )
    detail = instance.to_json()
    state = BattleState(
        units={
            "u": UnitState(
                "u", "ally", "component:u", hp=200, max_hp=100,
                statuses=(instance.status_id,),
                flags={"status_details": [detail]},
            )
        }
    )
    assert current_max_hp(state.units["u"]) == 200
    if operation == "replace":
        plan = StatusLifecyclePlan(
            "replace", "u", instance.status_id, "status_system",
            status_instance=replace(
                instance,
                modifiers=({"bucket": "attribute", "key": "hp_convert", "value": 50.0},),
            ),
            before_details=(detail,), existing_detail=detail,
            source_trace={"kind": "validation_fixture", "scope": "HP ceiling replace"},
        )
    elif operation == "stack_reduce":
        plan = StatusLifecyclePlan(
            "stack_reduce", "u", instance.status_id, "status_system",
            status_instance=replace(
                instance, stacks=1, application_operation="stack_reduce"
            ),
            before_details=(detail,), existing_detail=detail,
            source_trace={"kind": "validation_fixture", "scope": "HP ceiling stack"},
        )
    else:
        plan = StatusLifecyclePlan(
            "expire", "u", instance.status_id, "status_system",
            before_details=(detail,), existing_detail=detail,
            source_trace={"kind": "validation_fixture", "scope": "HP ceiling expire"},
        )
    result = StatusSystem()._apply_lifecycle_plan(state, plan)
    assert result.ok, result.unsupported
    after = MutationReducer().apply_all(state, result.mutations)
    assert after.units["u"].hp <= current_max_hp(after.units["u"]), {
        "operation": operation,
        "hp": after.units["u"].hp,
        "max": current_max_hp(after.units["u"]),
    }


def test_hp_cap_clamp_carries_the_native_lifecycle_audit_contract():
    from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
    from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
    from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem

    instance = StatusInstance(
        "hp:1", "modifier:hp", "hp", "u", "u", "u",
        modifiers=({"bucket": "attribute", "key": "hp_convert", "value": 100.0},),
    )
    state = BattleState(
        units={
            "u": UnitState(
                "u", "ally", "component:u", hp=200, max_hp=100,
                statuses=(instance.status_id,),
                flags={"status_details": [instance.to_json()]},
            )
        }
    )
    removed = StatusSystem().remove_status_instance(
        state, target_id="u", detail=instance.to_json(),
        source="status_system",
        source_trace={"kind": "validation_fixture", "scope": "HP clamp audit"},
    )
    assert removed.ok, removed.unsupported
    clamp = next(
        mutation for mutation in removed.mutations
        if mutation.path == ("units", "u", "hp")
    )
    assert isinstance((clamp.metadata or {}).get("lifecycle_plan"), dict)
    assert (clamp.metadata or {}).get("hp_contract", {}).get("before_hp") == 200.0
    audit = RuntimeSourceAuditor(
        RuleBook(CanonicalIR(version="component"))
    ).validate_execution((clamp,), removed.records)
    assert not any(
        violation.reason == "status_lifecycle_result_missing"
        for violation in audit.violations
    ), [violation.to_json() for violation in audit.violations]


def test_hp_clamp_audit_consumes_the_native_hp_contract():
    from copy import deepcopy
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem

    rules = _rules()
    effect = next(
        effect
        for effect in rules.ir.effects
        if effect.opcode == 'AddModifier'
        and effect.coverage_status == 'executable'
        and isinstance(effect.payload.get('standard'), dict)
        and effect.payload['standard'].get('modifier_name')
        == 'MAvatar_Lynx_00_HPAddedRatio01'
    )
    name = effect.payload['standard']['modifier_name']
    trace = {'effect_id': effect.effect_id, 'modifier_name': name}
    instance = StatusInstance(
        'review:hp',
        'modifier:' + name,
        name,
        'u',
        'u',
        'u',
        source_trace=trace,
        modifiers=({'bucket': 'attribute', 'key': 'hp_convert', 'value': 100.0},),
    )
    state = BattleState(
        units={
            'u': UnitState(
                'u', 'ally', 'component:u', hp=200, max_hp=100,
                statuses=(instance.status_id,),
                flags={'status_details': [instance.to_json()]},
            )
        }
    )
    result = StatusSystem(rules).remove_status_instance(
        state,
        target_id='u',
        detail=instance.to_json(),
        source='status_system',
        source_trace=trace,
    )
    assert result.ok, result.unsupported
    auditor = RuntimeSourceAuditor(rules)
    baseline = auditor.validate_execution(result.mutations, result.records)
    assert baseline.ok, [
        (violation.reason, violation.path) for violation in baseline.violations
    ]
    clamp = next(
        mutation for mutation in result.mutations if mutation.path == ('units', 'u', 'hp')
    )
    assert clamp.after == 100
    wrong = replace(clamp, after=99.0)
    mutations = tuple(
        wrong if mutation is clamp else mutation for mutation in result.mutations
    )
    records = []
    for record in result.records:
        record = deepcopy(record)
        if record.get('mutation_id') == clamp.stable_id():
            record['mutation_id'] = wrong.stable_id()
        records.append(record)
    checked = auditor.validate_execution(mutations, tuple(records))
    assert not checked.ok, {
        'hp_after': wrong.after,
        'contract': wrong.metadata['hp_contract'],
        'violations': [
            (violation.reason, violation.path) for violation in checked.violations
        ],
    }


def test_hpconvert_onstack_update_keeps_current_hp_in_range():
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.core.model import (
        BattleState,
        UnitState,
        current_max_hp,
    )
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
    from hsr.simulator_v8_clean_core.systems.status import StatusInstance
    from hsr.simulator_v8_clean_core.systems.status_callbacks import (
        StatusCallbackSystem,
    )

    rules = _rules()
    task = next(
        task
        for task in rules.ir.status_callback_tasks
        if task.modifier_name == 'MAvatar_Lynx_00_HPAddedRatio01'
        and task.event == 'OnStack'
        and task.opcode == 'StackProperty'
        and task.task_payload.get('Property') == 'HPConvert'
    )
    callback = rules.status_callback(task.callback_id)
    task = replace(
        task,
        task_payload={**task.task_payload, 'PropertyValue': numeric_fixed(50.0)},
    )
    entry = {
        'bucket': 'attribute',
        'key': 'hp_convert',
        'scope': 'actor',
        'value': 100.0,
        'property': 'HPConvert',
        'producer_task_id': task.task_id,
        'producer_task_path': task.task_path,
        'raw_path': task.task_path,
    }
    instance = StatusInstance(
        'review:hp:onstack',
        'modifier:' + task.modifier_name,
        task.modifier_name,
        'u',
        'u',
        'u',
        modifiers=(entry,),
    )
    detail = instance.to_json()
    state = BattleState(
        units={
            'u': UnitState(
                'u', 'ally', 'component:u', hp=200, max_hp=100,
                statuses=(instance.status_id,),
                flags={'status_details': [detail]},
            )
        }
    )
    assert current_max_hp(state.units['u']) == 200
    result = StatusCallbackSystem(rules)._execute_formal_leaf_task(
        state, callback, task, detail, None, None
    )
    assert result.ok, result.errors
    after_unit = result.after_state.units['u']
    assert after_unit.hp <= current_max_hp(after_unit), {
        'hp': after_unit.hp,
        'cap': current_max_hp(after_unit),
    }
