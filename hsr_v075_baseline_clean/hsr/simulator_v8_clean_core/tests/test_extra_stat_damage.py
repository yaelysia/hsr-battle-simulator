"""Real extra-DEF source plus a small numerical discriminator, without full compilation."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState, UnitStatPool
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR, ActionDefinitionIR, EffectIR, HitProfileIR, IRSource, SkillFormulaBindingIR,
)
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _damage_scaling_basis_expr, _direct_damage_binding_lookup,
)


def _walk(value, path='$'):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk(child, f'{path}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f'{path}[{index}]')


def test_source_extra_defense_reaches_shared_damage_and_uses_current_stat():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    filename = 'Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json'
    path, raw = next((path, node) for path, node in _walk(json.loads((root / filename).read_text()))
                     if node.get('$type') == 'RPG.GameCore.DamageByAttackProperty'
                     and node.get('AttackProperty', {}).get('ExtraFormulaType') == 'ByDefence')
    source = IRSource(filename, 'AbilityTask', path, {'json_path': path})
    effect = EffectIR('effect', 'DamageByAttackProperty', raw, source)
    task = AbilityTaskIR('task', 'phase', 'action', 1, 'fixture', 'OnStart', 0, path,
                         'root', effect.opcode, source, effect_id=effect.effect_id)
    profile = HitProfileIR('hit', 'action', 1, 0, 'selected', {}, {}, {}, {}, 'direct', 'Ice', source)
    binding = SkillFormulaBindingIR('binding', 'fixture:card', 'slot', 'action', 1, 0, 0,
        'direct_damage', 'selected', 0.5,
        {'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack', 'admission_status': 'executable'},
        '', '', '', source, coverage_status='executable')
    direct_basis_bindings = _direct_damage_binding_lookup([binding])
    basis = _damage_scaling_basis_expr(task, effect, profile, direct_basis_bindings)
    assert basis['extra_scaling_basis']['stat'] == 'defense'
    assert 'extra_damage_ratio_expr' in basis
    action = ActionDefinitionIR('definition', 'action', 1, 'Insert', 'SingleAttack', 'Single',
                                0, 0, 0, 0, (), (), (), 'Ice', source)
    actor = UnitState('actor', 'ally', 'fixture', level=80, hp=1000, max_hp=1000,
                      attack=1000, defense=200, stat_pools=(UnitStatPool('defense', 100, 0.5, 50),))
    target = UnitState('target', 'enemy', 'fixture', hp=10000, max_hp=10000, defense=200)
    packet = DamagePacket('actor', 'target', 'Insert', 'direct', action_definition=action,
        scaling_ratio=0.5, scaling_basis=basis, extra_scaling_ratio=0.3,
        source_trace=source.to_json(), metadata={'crit_mode': 'noncrit'})
    system = DamageSystem()
    for buff, expected_defense in ((0, 200), (0.2, 220)):
        current_actor = replace(actor, flags={'status_details': [{'instance_id': 'defense-buff',
            'modifiers': [{'bucket': 'attribute', 'key': 'defense_added_ratio', 'value': buff}]}]})
        state = BattleState(units={'actor': current_actor, 'target': target})
        before = state.snapshot().to_json()
        baseline = system.apply_packet(state, replace(packet, extra_scaling_ratio=0))
        actual = system.apply_packet(state, packet)
        assert baseline.ok and actual.ok, actual.errors
        damage = lambda result: next(m.before - m.after for m in result.mutations if m.path[-1] == 'hp')
        assert damage(actual) / damage(baseline) == pytest.approx((500 + 0.3 * expected_defense) / 500)
        formula = next(record['payload']['formula_result'] for record in actual.records
                       if record['record_type'] == 'damage')
        base = next(bucket for bucket in formula['modifier_ledger']['buckets'] if bucket['bucket'] == 'base')
        assert base['metadata']['extra_damage'] == pytest.approx(0.3 * expected_defense)
        assert state.snapshot().to_json() == before
        missing = system.apply_packet(state, replace(packet, extra_scaling_ratio=None))
        assert not missing.ok and not missing.mutations and not missing.rng_events

    unknown = replace(effect, payload={**raw, 'AttackProperty': {
        **raw['AttackProperty'], 'ExtraFormulaType': 'UnmappedFormula',
    }})
    assert _damage_scaling_basis_expr(task, unknown, profile, direct_basis_bindings)['kind'] == 'missing'
