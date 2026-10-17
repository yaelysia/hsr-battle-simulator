"""Real Fu Xuan immunity and marker callbacks with stated component inputs."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource, RuleEntity
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry, EffectResult
from hsr.simulator_v8_clean_core.systems.scheduler import CombatScheduler
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tests.test_status_shared_immunity import ROOT, _formal_immunity_source, _sources
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _attach_target_expressions_to_effect_payload, _dedupe_target_expressions,
    _effect_coverage_status, _effect_payload, _link_status_effect_runtime_fields,
    _lower_status_event_families, _modifier_definition_entity, _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    attach_task_graph_catalog, build_complete_task_graph_catalog,
    materialize_status_callback_task_graph, merge_task_graph_slices,
)


def test_real_fuxuan_protection_lasts_for_the_skill_and_clears_at_formal_turn_end():
    relative = 'Config/ConfigAbility/Avatar/Avatar_FuXuan_00_Ability.json'
    protection_name, marker_name = 'MAvatar_FuXuan_00_Tree02', 'MAvatar_FuXuan_00_Tree02TeamCheck'
    immunity_rules, _, _, _, _, frozen_flags = _sources()
    document = json.loads((ROOT / relative).read_text())
    with TemporaryDirectory() as temporary:
        lowering, source_catalog, lowered, languages = _formal_immunity_source(Path(temporary), relative, 1208)
        callbacks = tuple(row for row in lowered.status_callbacks if row.modifier_name in {protection_name, marker_name})
        callback_ids = {row.callback_id for row in callbacks}
        tasks = tuple(row for row in lowered.status_callback_tasks if row.callback_id in callback_ids)
        assert all(row.coverage_status == row.admission_status == 'executable'
            for row in callbacks if row.event in {'OnImmuneDebuff', 'OnListenTurnEnd'})
        protection = next(row for row in lowered.entities if row.fields.get('modifier_name') == protection_name)
        marker = next(row for row in lowered.entities if row.fields.get('modifier_name') == marker_name)
        entities = [*immunity_rules, protection, marker]
        expressions = [close_target_expression_language(row, languages) for row in lowered.target_expressions]
        expressions.extend(row.expression for row in languages)
        raw_grant = document['AbilityList'][3]['OnStart'][7]['SuccessTaskList'][0]
        assert raw_grant['ModifierName']['Value'] == protection_name
        requests = [('grant', raw_grant, protection, IRSource(relative, 'AbilityTask', 'actual_protection_grant', {
            'json_path': '$.AbilityList[3].OnStart[7].SuccessTaskList[0]', 'source_opcode': 'AddModifier'}))]
        for name, flags in (('noncontrol', ()), ('control', frozen_flags)):
            definition = _modifier_definition_entity('validation_fixture/fuxuan.json', 'ModifierMap', name,
                {'BehaviorFlagList': list(flags)}, source_context={'json_path': '$.ModifierMap.' + name})
            entities.extend((definition, RuleEntity('fixture:type:' + name, 'status',
                {'ModifierName': name, 'StatusType': 'Debuff'},
                IRSource('validation_fixture/fuxuan_types.json', 'StatusConfig', name), 'lowered')))
            requests.append((name, {'$type': 'RPG.GameCore.AddModifier', 'ModifierName': {'Value': name},
                'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'ParamEntity'},
                'Chance': {'IsDynamic': False, 'FixedValue': {'Value': 1.}}}, definition,
                IRSource('validation_fixture/fuxuan_requests.json', 'AddModifier', name, {'json_path': '$.' + name})))
        effects = []
        for name, raw, definition, source in requests:
            payload, targets = _attach_target_expressions_to_effect_payload(
                _effect_payload(raw, 'AddModifier', ''), raw, effect_id='fixture:' + name, source=source,
                target_language_definitions=languages)
            expressions.extend(targets)
            effects.append(EffectIR('fixture:' + name, 'AddModifier', payload, source,
                _effect_coverage_status('AddModifier', payload), modifier_definition_id=definition.entity_id))
        # Link the real marker grant and complete callback ledger without
        # overriding each callback's source admission.
        effects = _link_status_effect_runtime_fields([*lowered.effects, *effects],
            list({row.entity_id: row for row in (*lowered.entities, *entities)}.values()), list(callbacks))
        expressions = list(_dedupe_target_expressions(expressions).values())
        canonical = CanonicalIR('fuxuan-immunity-component', entities=tuple(entities),
            effects=tuple(_synchronize_effect_target_expression_metadata(effects, expressions)),
            conditions=tuple(lowered.conditions), target_expressions=tuple(expressions),
            status_callbacks=callbacks, status_callback_tasks=tasks,
            status_event_families=tuple(_lower_status_event_families(callbacks, tasks)),
            timeline_rules=build_engine_rule_registry().timeline_rules)
        snapshot = lowering._character_ability_raw_snapshot
        catalog = merge_task_graph_slices(build_complete_task_graph_catalog(source_catalog, snapshot),
            (materialize_status_callback_task_graph(source_catalog, canonical,
                callback_id=row.callback_id, source_snapshot=snapshot) for row in callbacks))
        rules = RuleBook(attach_task_graph_catalog(canonical, catalog))

    registry, reducer = EffectRegistry(StatusSystem(rules)), MutationReducer()
    allies = ('fx', 'ally:a', 'ally:b')
    state = BattleState(units={unit_id: UnitState(unit_id, 'enemy' if unit_id == 'enemy' else 'ally',
        'fixture:' + unit_id, hp=1000, max_hp=1000, speed=100,
        resources={'effect_hit_rate': 100.}) for unit_id in (*allies, 'enemy')}, global_flags={
            'active_turn': {'actor_id': 'enemy', 'turn_kind': 'regular', 'turn_sequence_index': 1},
            'turn_owner_id': 'enemy', 'turn_sequence_index': 1, 'combat_phase': 'post_action',
        })
    grant = registry.execute(rules.effect('fixture:grant'), EffectExecutionContext(
        state, 'fx', 'fixture:fx-protection', application_instance_id='fixture:fx-protection'))
    assert not grant.unsupported, grant.unsupported
    current = reducer.apply_all(state, grant.mutations)
    protection_id, marker_id = 'modifier:' + protection_name, 'modifier:' + marker_name
    assert all(protection_id in current.units[unit_id].statuses for unit_id in allies)
    mutations, records = list(grant.mutations), list(grant.records)

    def attempt(current, kind, target, hit):
        return registry.execute(rules.effect('fixture:' + kind), EffectExecutionContext(
            current, 'enemy', 'fixture:enemy-skill', param_entity_id=target,
            application_instance_id='fixture:enemy-skill:' + hit))

    noncontrol = attempt(current, 'noncontrol', 'ally:a', 'noncontrol')
    assert not noncontrol.unsupported and noncontrol.mutations, noncontrol.unsupported
    current = reducer.apply_all(current, noncontrol.mutations)
    mutations.extend(noncontrol.mutations); records.extend(noncontrol.records)
    assert all(marker_id not in unit.statuses for unit in current.units.values())
    for target in ('ally:a', 'ally:b'):
        immune = attempt(current, 'control', target, target)
        assert not immune.unsupported and not immune.rng_events, immune.unsupported
        current = reducer.apply_all(current, immune.mutations)
        mutations.extend(immune.mutations); records.extend(immune.records)
        assert 'modifier:control' not in current.units[target].statuses
        assert all(protection_id in current.units[unit_id].statuses for unit_id in allies)
        assert all(marker_id not in current.units[unit_id].statuses for unit_id in ('ally:a', 'ally:b', 'enemy'))
    marker_details = [row for row in current.units['fx'].flags['status_details'] if row['modifier_name'] == marker_name]
    assert len(marker_details) == 1 and marker_details[0]['caster_id'] == marker_details[0]['owner_id'] == 'fx'
    before_cleanup = current
    scheduler = CombatScheduler(rules)
    ended = scheduler.end_current_turn(current)
    assert ended.transition.outcome.successor_eligible, ended.transition.outcome.to_json()
    current = ended.after_state
    assert all(protection_id not in current.units[unit_id].statuses for unit_id in allies)
    assert marker_id not in current.units['fx'].statuses
    assert any(event.event_type == 'turn.end' for event in ended.transition.transaction.events)
    mutations.extend(ended.transition.transaction.mutations)
    records.extend(ended.transition.transaction.settlement.records)
    after = attempt(current, 'control', 'ally:a', 'after-cleanup')
    assert not after.unsupported, after.unsupported
    assert 'modifier:control' in reducer.apply_all(current, after.mutations).units['ally:a'].statuses
    audit = RuntimeSourceAuditor(rules).validate_execution(
        tuple([*mutations, *after.mutations]), tuple([*records, *after.records]))
    assert audit.ok, audit.to_json()

    # Fail the final real cleanup consumer after the all-team removal ran.
    failed_scheduler = CombatScheduler(rules)
    consume_registry = failed_scheduler.event_dispatcher.status_callbacks.effect_registry
    execute = consume_registry.execute

    def fail_self(effect, context):
        return EffectResult(unsupported=('fixture_marker_cleanup_failed',)) if effect.opcode == 'RemoveSelfModifier' else execute(effect, context)

    consume_registry.execute = fail_self
    failed = failed_scheduler.end_current_turn(before_cleanup)
    assert not failed.transition.outcome.successor_eligible
    assert failed.after_state == before_cleanup
    assert not failed.transition.transaction.mutations and not failed.transition.rng_events
