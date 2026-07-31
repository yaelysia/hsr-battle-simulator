from __future__ import annotations
import argparse
import json
import resource
import time
from collections import Counter
from dataclasses import replace
from math import isclose
from pathlib import Path
from typing import Any
from ..core.executor import CombatExecutor
from ..core.model import (
    ActionCommand, ActionSettlement, ActionTransaction, BattleState,
    BattleTransition, Mutation,
)
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..equipment.models import EquipmentBuildInput, RelicInstanceInput
from ..resource_event_contract import (
    TEAM_SKILL_POINT_EVENT_CONTRACT, UNIT_ENERGY_EVENT_CONTRACT,
)
from ..rules.ability_properties import ability_property_stat_name
from ..rules.evaluator import EvaluationContext, RuleEvaluator
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..systems.dynamic_values import binding_source_from_status_detail
from ..systems.effect import EffectExecutionContext
from ..systems.event_dispatch import _ability_property_recheck_unit_ids
from ..systems.mutation_events import events_for_mutation
from ..systems.unit_stats import effective_unit_stat
from ..tbgd.equipment_ability_families import classify_equipment_callback, classify_equipment_condition, classify_equipment_family, classify_equipment_task
from .io import write_json
from .validate_p8_s15_relic_set_dynamic_startup import _blocker_ledger, _build_bundle, _scenario

def validate(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = _build_bundle(tbgd_root)
    partition = _partition(bundle)
    lifecycle = _lifecycle(bundle)
    conditions = _conditions(bundle, lifecycle)
    integrity = _integrity(bundle, lifecycle)
    audit = _audit_replay(bundle, lifecycle)
    handler_hits = _set_handler_hits()
    predicates: dict[str, bool | int] = {
        'current_set_gameplay_inventory_non_empty': partition['gameplay_count'] > 0,
        's16_s17_partition_complete': partition['complete'],
        's16_s17_partition_disjoint': partition['disjoint'],
        's16_family_gap_count': partition['s16_gap_count'],
        's16_unknown_gameplay_count': partition['unknown_count'],
        'conditions_read_runtime_state': conditions['runtime_state'],
        'condition_false_is_not_blocked': conditions['false_legal'],
        'condition_lifecycle_re_evaluates_on_real_events': lifecycle['re_evaluated'],
        'multi_wearer_stacking_source_driven': lifecycle['multi']['ok'],
        'team_and_owner_attribution_correct': lifecycle['team']['ok'],
        'listener_registration_idempotent': integrity['idempotent'],
        'unsupported_selected_branch_blocks_atomically': integrity['atomic_block'],
        'mutation_backed_property_change_rechecks_target': integrity['mutation_backed_recheck'],
        'duplicate_callback_identity_blocked': integrity['duplicate_callback_blocked'],
        'watcher_mutation_source_trace_strict': integrity['source_trace_strict'],
        'max_sp_uses_unit_energy_semantics': integrity['max_sp_semantics'],
        'sampled_mutations_source_audited': audit['source_audit'],
        'sampled_transitions_replay_equal': audit['replay'],
        'set_specific_runtime_handlers': len(handler_hits),
    }
    zero_keys = {
        's16_family_gap_count',
        's16_unknown_gameplay_count',
        'set_specific_runtime_handlers',
    }
    ok = all(
        value == 0 if key in zero_keys else value is True
        for key, value in predicates.items()
    )
    artifacts = {
        'family_partition_p8_s16.json': partition,
        'condition_lifecycle_p8_s16.json': {
            'conditions': conditions,
            'lifecycle': _public_lifecycle(lifecycle),
        },
        'atomic_audit_replay_p8_s16.json': {
            'integrity': integrity,
            'audit_replay': audit,
            'set_specific_handler_hits': handler_hits,
        },
    }
    for name, payload in artifacts.items():
        write_json(output_dir / name, payload)
    fingerprint = _fingerprint(bundle)
    summary = {
        'ok': ok,
        'predicates': predicates,
        'counts': {
            'graphs': len(bundle['graphs']),
            'executable_graphs': sum(
                graph.coverage_status == 'executable' for graph in bundle['graphs']
            ),
            'blocked_graphs': sum(
                graph.coverage_status != 'executable' for graph in bundle['graphs']
            ),
            'watchers': len(bundle['ability_property_watchers']),
            'ranges': len(bundle['ability_property_ranges']),
            's16_families': partition['s16_count'],
            's17_families': partition['s17_count'],
        },
        'source': {
            'fingerprint': fingerprint,
            'file_count': fingerprint.get('file_count', 0),
            'byte_count': fingerprint.get('byte_count', 0),
        },
        'resources': {
            'focused_rulebook_builds': 1,
            'full_lowering_builds': 0,
            'elapsed_seconds': round(time.monotonic() - started, 3),
            'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'artifact_bytes_before_summary': sum(
                (output_dir / name).stat().st_size for name in artifacts
            ),
        },
        's17_inheritance': {
            'blocked_graph_count': partition['blocked_graph_count'],
            'remaining_families': partition['s17_blockers'],
            'partial_execution_allowed': False,
        },
    }
    write_json(
        output_dir
        / 'validation_summary_p8_s16_relic_set_status_condition_listener_closure.json',
        summary,
    )
    return summary

def _partition(bundle: dict[str, Any]) -> dict[str, Any]:
    rules = bundle['rules']
    rows: list[dict[str, Any]] = []
    callback_tasks = tuple(
        task
        for task in rules.ir.status_callback_tasks
        if task.source.evidence.get('equipment_ability_source_admitted') is True
    )
    raw_by_callback: dict[str, list[dict[str, Any]]] = {}
    for task in callback_tasks:
        raw = task.source.evidence.get('task')
        if not task.parent_task_id and isinstance(raw, dict):
            raw_by_callback.setdefault(task.callback_id, []).append(raw)
    callbacks = tuple(
        callback
        for callback in rules.ir.status_callbacks
        if callback.source.evidence.get('equipment_ability_source_admitted') is True
    )
    callback_stages = {
        callback.callback_id: classify_equipment_callback(
            callback.event,
            raw_by_callback.get(callback.callback_id, []),
        )
        for callback in callbacks
    }
    for task in callback_tasks:
        raw = task.source.evidence.get('task')
        stage = classify_equipment_task(task.opcode, raw) if isinstance(raw, dict) else classify_equipment_family('task', task.opcode)
        if callback_stages.get(task.callback_id) == 's8':
            stage = 's8'
        rows.append(_row('task', task.task_id, task.opcode, stage, task))
    for task in rules.ir.ability_tasks:
        context = task.source.evidence.get('ability_source_context')
        if isinstance(context, dict) and context.get('equipment_ability_source_admitted') is True:
            rows.append(_row('task', task.task_id, task.opcode, classify_equipment_family('task', task.opcode), task))
    for condition in rules.ir.conditions:
        if condition.source.evidence.get('equipment_ability_source_admitted') is not True:
            continue
        raw = _raw_node(condition.source.evidence.get('task'), condition.opcode)
        stage = classify_equipment_condition(condition.opcode, raw) if raw is not None else classify_equipment_family('condition', condition.opcode)
        callback_id = condition.source.evidence.get('callback_id')
        if isinstance(callback_id, str) and callback_stages.get(callback_id) == 's8':
            stage = 's8'
        rows.append(_row('condition', condition.condition_id, condition.opcode, stage, condition))
    for callback in callbacks:
        rows.append(_row('event', callback.callback_id, callback.event, callback_stages[callback.callback_id], callback, callback.admission_status))
    for target in rules.ir.target_expressions:
        if target.source.evidence.get('equipment_ability_source_admitted') is True:
            rows.append(_row('target', target.target_expression_id, target.expression_kind, classify_equipment_family('target', target.expression_kind), target))
    rows.extend((_row('watcher', watcher.watcher_id, watcher.property_name, 's7', watcher) for watcher in bundle['ability_property_watchers']))
    rows.extend((_row('range', item.range_id, 'AbilityPropertyRange', 's7', item) for item in bundle['ability_property_ranges']))
    rows = list({(row['kind'], row['identity']): row for row in rows}.values())
    rows.sort(key=lambda row: (row['kind'], row['identity']))
    gameplay = [row for row in rows if row['stage'] in {'s7', 's8'}]
    s16 = [row for row in gameplay if row['stage'] == 's7']
    s17 = [row for row in gameplay if row['stage'] == 's8']
    unknown = [row for row in rows if row['stage'] == 'unknown']
    gaps = [
        row
        for row in s16
        if row['coverage_status'] != 'executable'
        or (
            row['kind'] == 'event'
            and row['admission_status'] != 'executable'
        )
    ]
    ledger = _blocker_ledger(bundle)
    s16_ids = {(row['kind'], row['identity']) for row in s16}
    s17_ids = {(row['kind'], row['identity']) for row in s17}
    classified = [row for row in rows if row['stage'] != 'non_gameplay']
    return {
        'complete': (
            bool(gameplay)
            and not unknown
            and len(gameplay) == len(classified)
            and all(item['stage'] == 's8' for item in ledger['totals'])
            and all(ledger['checks'].values())
        ),
        'disjoint': not s16_ids.intersection(s17_ids),
        'gameplay_count': len(gameplay),
        's16_count': len(s16),
        's17_count': len(s17),
        'unknown_count': len(unknown),
        's16_gap_count': len(gaps),
        'blocked_graph_count': ledger['blocked_graph_count'],
        'family_counts': dict(
            sorted(
                Counter(
                    f"{row['stage']}:{row['kind']}:{row['family']}"
                    for row in rows
                ).items()
            )
        ),
        's16_gaps': gaps[:20],
        'unknown_rows': unknown[:20],
        's17_blockers': [
            {
                key: item[key]
                for key in ('kind', 'family', 'reason', 'dependency_count')
            }
            for item in ledger['totals']
        ],
    }

def _row(kind: str, identity: str, family: str, stage: str, value: Any, admission: str='executable') -> dict[str, Any]:
    return {'kind': kind, 'identity': identity, 'family': family, 'stage': stage, 'coverage_status': value.coverage_status, 'admission_status': admission, 'blocked_reason': value.blocked_reason}

def _raw_node(value: Any, opcode: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if str(value.get('$type') or '').rsplit('.', 1)[-1] == opcode:
            return value
        for child in value.values():
            found = _raw_node(child, opcode)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _raw_node(child, opcode)
            if found is not None:
                return found
    return None

def _lifecycle(bundle: dict[str, Any]) -> dict[str, Any]:
    case = _speed_case(bundle)
    multi = _multi_wearer(bundle, case)
    team = _team_attribution(bundle)
    re_evaluated = (
        case['results'] == [False, True, False]
        and case['speed_before'] < case['speed_after_add']
        and isclose(
            case['speed_before'],
            case['speed_after_remove'],
            rel_tol=0.0,
            abs_tol=1e-09,
        )
        and not case['add_commit'].errors
        and not case['remove_commit'].errors
    )
    return {'re_evaluated': re_evaluated, 'case': case, 'multi': multi, 'team': team}

def _speed_case(bundle: dict[str, Any]) -> dict[str, Any]:
    rules = bundle['rules']
    thresholds = _thresholds(bundle)
    graph_status = {graph.ability_name: graph.coverage_status for graph in bundle['graphs']}
    conditions = [item for item in rules.ir.conditions if item.opcode == 'ByCompareAbilityProperty' and item.payload.get('Property') == 'Speed' and (item.coverage_status == 'executable')]
    for watcher in sorted(bundle['ability_property_watchers'], key=lambda item: item.watcher_id):
        source = watcher.source.evidence.get('equipment_ability_source')
        ability = str(source.get('raw_id') or '') if isinstance(source, dict) else ''
        watcher_threshold = thresholds.get(ability)
        condition = next((item for item in conditions if item.source.raw_id == watcher.modifier_name and item.source.evidence.get('equipment_ability_source') == source), None)
        if watcher.property_name != 'Speed' or watcher.coverage_status != 'executable' or watcher_threshold is None or (watcher_threshold.require_count != 2) or (graph_status.get(ability) != 'executable') or (condition is None):
            continue
        for source_case in _speed_sources(bundle):
            if source_case['threshold'].set_key == watcher_threshold.set_key:
                continue
            templates = (*_templates(bundle['catalog'], source_case['threshold'].set_key, source_case['threshold'].require_count), *_templates(bundle['catalog'], watcher_threshold.set_key, watcher_threshold.require_count))
            foot = next((item for item in templates if item.slot_key.definition_identity == 'FOOT' and _main_affix(bundle, item, 'SpeedDelta').property_type == 'SpeedDelta'), None)
            if foot is None:
                continue
            zero = _run_speed_level(bundle, watcher, condition, source_case, templates, 0)
            if zero is None or zero['speed_after_add'] <= zero['speed_before']:
                continue
            threshold = _dynamic_compare_value(condition, zero['watcher_detail'])
            ratio = zero['speed_after_add'] / zero['speed_before'] - 1.0
            level_add = float(_main_affix(bundle, foot, 'SpeedDelta').level_add)
            levels = [level for level in range(foot.max_level + 1) if zero['speed_before'] + level_add * level < threshold <= (zero['speed_before'] + level_add * level) * (1.0 + ratio)]
            for level in levels:
                result = zero if level == 0 else _run_speed_level(bundle, watcher, condition, source_case, templates, level)
                if result is not None and result['results'] == [False, True, False] and (not result['add_commit'].errors) and (not result['remove_commit'].errors):
                    result.pop('watcher_detail', None)
                    return result
    raise ValueError('no structural 4+2 speed lifecycle case')

def _run_speed_level(bundle: dict[str, Any], watcher: Any, condition: Any, source_case: dict[str, Any], templates: tuple[Any, ...], level: int) -> dict[str, Any] | None:
    rules = bundle['rules']
    equipment = _equipment(bundle, templates, f'speed:{level}', speed_level=level)
    built = ScenarioStateBuilder(rules).build(_scenario(bundle['card'], equipment, f'speed:{level}'))
    unit_id = f'ally:speed:{level}'
    watcher_detail = _detail(built.state, unit_id, watcher.modifier_name)
    parent = _detail(built.state, unit_id, source_case['add'].source.raw_id)
    if built.blocked_setup or watcher_detail is None or parent is None:
        return None
    first = _evaluate(condition, built.state, unit_id, watcher_detail)
    added = _execute(rules, built.state, unit_id, source_case['add'], parent)
    watcher_after = _detail(added.after_state, unit_id, watcher.modifier_name)
    parent_after = _detail(added.after_state, unit_id, source_case['add'].source.raw_id)
    if watcher_after is None or parent_after is None:
        return None
    second = _evaluate(condition, added.after_state, unit_id, watcher_after)
    removed = _execute(rules, added.after_state, unit_id, source_case['remove'], parent_after)
    watcher_final = _detail(removed.after_state, unit_id, watcher.modifier_name)
    if watcher_final is None:
        return None
    third = _evaluate(condition, removed.after_state, unit_id, watcher_final)
    if not all(item.ok for item in (first, second, third)):
        return None
    return {
        'unit_id': unit_id, 'equipment': equipment, 'watcher': watcher,
        'watcher_detail': watcher_detail, 'condition': condition,
        'add_effect': source_case['add'], 'remove_effect': source_case['remove'],
        'before': built.state, 'add_commit': added, 'remove_commit': removed,
        'results': [first.result, second.result, third.result], 'speed_level': level,
        'speed_before': _speed(built.state, unit_id),
        'speed_after_add': _speed(added.after_state, unit_id),
        'speed_after_remove': _speed(removed.after_state, unit_id),
    }

def _dynamic_compare_value(condition: Any, detail: dict[str, Any]) -> float:
    expression = condition.payload.get('CompareValue')
    dynamic_values = detail.get('dynamic_values')
    if not isinstance(expression, dict) or expression.get('kind') != 'dynamic_hash' or not isinstance(dynamic_values, dict):
        raise ValueError('speed condition has no dynamic comparison value')
    value = dynamic_values.get(str(expression.get('hash')))
    if not isinstance(value, (int, float)):
        raise ValueError('speed condition dynamic comparison value is missing')
    return float(value)

def _speed_sources(bundle: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    rules = bundle['rules']
    thresholds = _thresholds(bundle)
    graph_status = {graph.ability_name: graph.coverage_status for graph in bundle['graphs']}
    effects = [effect for effect in rules.ir.effects if effect.source.evidence.get('equipment_ability_source_admitted') is True]
    rows = []
    for add in effects:
        standard = add.payload.get('standard')
        definition = rules.entity(add.modifier_definition_id) if add.modifier_definition_id else None
        properties = {item.get('property') for item in (definition.fields.get('stack_properties', ()) if definition is not None else ()) if isinstance(item, dict)}
        source = add.source.evidence.get('equipment_ability_source')
        ability = str(source.get('raw_id') or '') if isinstance(source, dict) else ''
        threshold = thresholds.get(ability)
        if (
            add.opcode != 'AddModifier'
            or add.coverage_status != 'executable'
            or not isinstance(standard, dict)
            or standard.get('target_alias') != 'Caster'
            or 'SpeedAddedRatio' not in properties
            or threshold is None
            or threshold.require_count != 4
            or graph_status.get(ability) != 'executable'
        ):
            continue
        remove = next(
            (
                effect
                for effect in effects
                if effect.opcode == 'RemoveModifier'
                and effect.coverage_status == 'executable'
                and effect.source.evidence.get('equipment_ability_source')
                == source
                and isinstance(effect.payload.get('standard'), dict)
                and effect.payload['standard'].get('target_alias') == 'Caster'
                and effect.payload['standard'].get('modifier_name')
                == standard.get('modifier_name')
            ),
            None,
        )
        if remove is not None:
            rows.append({'threshold': threshold, 'add': add, 'remove': remove})
    return tuple(sorted(rows, key=lambda row: row['add'].effect_id))

def _multi_wearer(bundle: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    rules = bundle['rules']
    base = _scenario(bundle['card'], case['equipment'], 'multi:a')
    original = base.units[0]

    def clone(unit_id: str, suffix: str) -> Any:
        equipment = replace(case['equipment'], build_id=f'validation:p8_s16:multi:{suffix}', relics=tuple((replace(relic, instance_id=f'{relic.instance_id}:{suffix}') for relic in case['equipment'].relics)))
        return replace(original, unit_id=unit_id, character_build=replace(original.character_build, build_id=f'validation:p8_s16:character:{suffix}', equipment_build=equipment))
    first = clone('ally:multi:a', 'a')
    second = clone('ally:multi:b', 'b')
    built = ScenarioStateBuilder(rules).build(replace(base, scenario_id='validation:p8_s16:multi', units=(first, second)))
    before = built.state
    speed_b = _speed(before, second.unit_id)
    parent_a = _detail(before, first.unit_id, case['add_effect'].source.raw_id)
    if built.blocked_setup or parent_a is None:
        return {'ok': False, 'reason': 'first_wearer_source_missing'}
    commit_a = _execute(rules, before, first.unit_id, case['add_effect'], parent_a)
    parent_b = _detail(commit_a.after_state, second.unit_id, case['add_effect'].source.raw_id)
    if parent_b is None:
        return {'ok': False, 'reason': 'second_wearer_source_missing'}
    watcher_name = case['watcher'].modifier_name
    a = _evaluate(case['condition'], commit_a.after_state, first.unit_id, _detail(commit_a.after_state, first.unit_id, watcher_name))
    b_before = _evaluate(case['condition'], commit_a.after_state, second.unit_id, _detail(commit_a.after_state, second.unit_id, watcher_name))
    commit_b = _execute(rules, commit_a.after_state, second.unit_id, case['add_effect'], parent_b)
    b_after = _evaluate(case['condition'], commit_b.after_state, second.unit_id, _detail(commit_b.after_state, second.unit_id, watcher_name))
    ok = (
        not commit_a.errors
        and not commit_b.errors
        and a.ok
        and a.result is True
        and b_before.ok
        and b_before.result is False
        and b_after.ok
        and b_after.result is True
        and isclose(
            speed_b,
            _speed(commit_a.after_state, second.unit_id),
            rel_tol=0.0,
            abs_tol=1e-09,
        )
        and _speed(commit_b.after_state, second.unit_id) > speed_b
    )
    return {'ok': ok, 'unit_ids': [first.unit_id, second.unit_id], 'results': [a.result, b_before.result, b_after.result], 'before_a': before, 'before_b': commit_a.after_state, 'commit_a': commit_a, 'commit_b': commit_b}

def _team_attribution(bundle: dict[str, Any]) -> dict[str, Any]:
    rules = bundle['rules']
    thresholds = _thresholds(bundle)
    graph_status = {graph.ability_name: graph.coverage_status for graph in bundle['graphs']}
    aliases = {'AllLightTeam', 'AllTeammate', 'AllTeamMember'}
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        standard = effect.payload.get('standard')
        source = effect.source.evidence.get('equipment_ability_source')
        ability = str(source.get('raw_id') or '') if isinstance(source, dict) else ''
        threshold = thresholds.get(ability)
        if effect.opcode != 'AddModifier' or effect.coverage_status != 'executable' or (not isinstance(standard, dict)) or (standard.get('target_alias') not in aliases) or (threshold is None) or (graph_status.get(ability) != 'executable'):
            continue
        equipment = _equipment(bundle, _templates(bundle['catalog'], threshold.set_key, threshold.require_count), 'team:wearer')
        base = _scenario(bundle['card'], equipment, 'team:wearer')
        wearer = base.units[0]
        teammate = replace(
            wearer,
            unit_id='ally:team:mate',
            character_build=replace(
                wearer.character_build,
                build_id='validation:p8_s16:character:team:mate',
                equipment_build=EquipmentBuildInput(
                    build_id='validation:p8_s16:team:empty',
                    character_card_id=bundle['card'].card_id,
                ),
            ),
        )
        built = ScenarioStateBuilder(rules).build(replace(base, scenario_id='validation:p8_s16:team', units=(wearer, teammate)))
        parent = _detail(built.state, wearer.unit_id, effect.source.raw_id)
        if built.blocked_setup or parent is None:
            continue
        commit = _execute(rules, built.state, wearer.unit_id, effect, parent)
        if commit.errors:
            continue
        modifier = str(standard.get('modifier_name') or '')
        details = {unit_id: _detail(commit.after_state, unit_id, modifier) for unit_id in (wearer.unit_id, teammate.unit_id)}
        if not all(details.values()):
            continue
        ok = all((detail is not None and detail.get('owner_id') == unit_id and (detail.get('caster_id') == wearer.unit_id) and (detail.get('source_id') == parent.get('source_id')) for (unit_id, detail) in details.items()))
        return {'ok': ok, 'wearer_id': wearer.unit_id, 'target_ids': sorted(details), 'target_alias': standard.get('target_alias'), 'modifier_name': modifier, 'before': built.state, 'commit': commit}
    return {'ok': False, 'reason': 'team_attribution_case_missing'}

def _conditions(bundle: dict[str, Any], lifecycle: dict[str, Any]) -> dict[str, Any]:
    rules = bundle['rules']
    evaluator = RuleEvaluator()
    case = lifecycle['case']
    state = case['before']
    unit_id = case['unit_id']
    rows = [{'opcode': case['condition'].opcode, 'has_true': True, 'has_false': True, 'false_is_legal': True, 'results': case['results'], 'source': case['condition'].source.to_json(), 'input_kind': 'formal_eventful_lifecycle'}]
    attack = _condition(rules, 'ByAttackType')
    expected = str(attack.payload['AttackTypes'][0])
    rows.append(_pair(evaluator, attack, EvaluationContext(event_payload={'AttackType': expected}), EvaluationContext(event_payload={'AttackType': '__other__'})))
    team = _condition(rules, 'ByTargetTeam')
    ally = state.units[unit_id]
    enemy_id = 'enemy:p8_s16:condition'
    team_state = replace(state, units={**state.units, enemy_id: replace(ally, unit_id=enemy_id, side='enemy')})
    rows.append(
        _pair(
            evaluator,
            team,
            EvaluationContext(
                state=team_state,
                actor_id=unit_id,
                owner_id=unit_id,
                target_id=unit_id,
                param_entity_id=unit_id,
            ),
            EvaluationContext(
                state=team_state,
                actor_id=unit_id,
                owner_id=unit_id,
                target_id=enemy_id,
                param_entity_id=enemy_id,
            ),
        )
    )
    wave = _condition(rules, 'ByCompareWaveCount')
    rows.append(_result_row(wave, tuple((evaluator.evaluate_condition_result(wave, EvaluationContext(state=replace(state, wave_index=index))) for index in range(5)))))
    count = _condition(rules, 'ByStatusCount')
    clean = _without_category(state, unit_id, 'debuff')
    rows.append(
        _pair(
            evaluator,
            count,
            EvaluationContext(
                state=_with_status(clean, unit_id, status_category='debuff'),
                target_id=unit_id,
                event_payload={'damage_defender_id': unit_id},
            ),
            EvaluationContext(
                state=clean,
                target_id=unit_id,
                event_payload={'damage_defender_id': unit_id},
            ),
        )
    )
    behavior = _condition(rules, 'ByContainBehaviorFlag')
    flags = _behavior_flags(behavior.payload)
    clean_flags = _without_behavior_flags(state, unit_id, flags)
    rows.append(
        _pair(
            evaluator,
            behavior,
            EvaluationContext(
                state=_with_status(
                    clean_flags,
                    unit_id,
                    behavior_flags=(flags[0],),
                ),
                actor_id=unit_id,
                owner_id=unit_id,
            ),
            EvaluationContext(
                state=clean_flags,
                actor_id=unit_id,
                owner_id=unit_id,
            ),
        )
    )
    rows.append(_hp_ratio(bundle))
    required = {'ByCompareAbilityProperty', 'ByCompareHPRatio', 'ByAttackType', 'ByStatusCount', 'ByTargetTeam', 'ByCompareWaveCount', 'ByContainBehaviorFlag'}
    return {'runtime_state': required.issubset({str(row.get('opcode') or '') for row in rows}) and all((row['has_true'] and row['has_false'] for row in rows)), 'false_legal': all((row['false_is_legal'] for row in rows)), 'rows': rows}

def _hp_ratio(bundle: dict[str, Any]) -> dict[str, Any]:
    rules = bundle['rules']
    thresholds = _thresholds(bundle)
    graph_status = {graph.ability_name: graph.coverage_status for graph in bundle['graphs']}
    for condition in sorted((item for item in rules.ir.conditions if item.opcode == 'ByCompareHPRatio' and item.coverage_status == 'executable'), key=lambda item: item.condition_id):
        source = condition.source.evidence.get('equipment_ability_source')
        ability = str(source.get('raw_id') or '') if isinstance(source, dict) else ''
        threshold = thresholds.get(ability)
        if threshold is None or graph_status.get(ability) != 'executable':
            continue
        equipment = _equipment(bundle, _templates(bundle['catalog'], threshold.set_key, threshold.require_count), 'hp-ratio')
        built = ScenarioStateBuilder(rules).build(_scenario(bundle['card'], equipment, 'hp-ratio'))
        unit_id = 'ally:hp-ratio'
        detail = _detail(built.state, unit_id, condition.source.raw_id)
        if built.blocked_setup or detail is None:
            continue
        results = []
        for ratio in (0.1, 0.5, 0.9, 1.0):
            unit = built.state.units[unit_id]
            candidate = replace(unit, hp=unit.max_hp * ratio)
            state = replace(built.state, units={**built.state.units, unit_id: candidate})
            results.append(_evaluate(condition, state, unit_id, detail))
        return _result_row(condition, tuple(results))
    raise ValueError('no executable formal HP ratio condition case')

def _condition(rules: Any, opcode: str) -> Any:
    candidates = [condition for condition in rules.ir.conditions if condition.opcode == opcode and condition.coverage_status == 'executable' and (condition.source.evidence.get('equipment_ability_source_admitted') is True)]
    if not candidates:
        raise ValueError(f'condition sample missing:{opcode}')
    return min(candidates, key=lambda item: item.condition_id)

def _pair(evaluator: RuleEvaluator, condition: Any, first: EvaluationContext, second: EvaluationContext) -> dict[str, Any]:
    return _result_row(condition, (evaluator.evaluate_condition_result(condition, first), evaluator.evaluate_condition_result(condition, second)))

def _result_row(condition: Any, results: tuple[Any, ...]) -> dict[str, Any]:
    has_true = any((item.ok and item.result is True for item in results))
    has_false = any((item.ok and item.result is False for item in results))
    return {
        'opcode': condition.opcode,
        'has_true': has_true,
        'has_false': has_false,
        'false_is_legal': has_false,
        'results': [
            {
                'ok': item.ok,
                'result': item.result,
                'reason': item.reason,
            }
            for item in results
        ],
        'source': condition.source.to_json(),
        'input_kind': 'committed_state_or_event_input',
    }

def _integrity(bundle: dict[str, Any], lifecycle: dict[str, Any]) -> dict[str, Any]:
    case = lifecycle['case']
    after_add = case['add_commit'].after_state
    unit_id = case['unit_id']
    trigger = next((event for event in case['add_commit'].events if event.event_type == 'status.lifecycle' and event.target_id == unit_id))
    executor = CombatExecutor(bundle['rules'])
    system = executor.event_dispatcher.ability_property_watchers
    first = system.reconcile(after_add, unit_ids=(unit_id,), trigger_event=trigger)
    second = system.reconcile(first.after_state, unit_ids=(unit_id,), trigger_event=replace(trigger, event_id=f'{trigger.event_id}:repeat'))
    forged = _remove_watcher_identity(after_add, unit_id, case['watcher'].modifier_name)
    blocked = executor.event_dispatcher.dispatch_event(forged, event=replace(trigger, event_id=f'{trigger.event_id}:forged'))
    baseline = after_add.snapshot().to_json()
    mutation_backed_recheck = _mutation_backed_recheck(after_add, unit_id)
    duplicate_callback_blocked = _duplicate_callback_blocked(
        bundle['rules'],
        case['watcher'],
    )
    source_trace = _source_trace_negative(bundle['rules'], case)
    return {
        'idempotent': (
            first.ok
            and second.ok
            and first.after_state.snapshot().to_json() == baseline
            and second.after_state.snapshot().to_json() == baseline
            and not first.mutations
            and not second.mutations
            and not first.events
            and not second.events
        ),
        'atomic_block': (
            'ability_property_watcher_instance_identity_missing' in blocked.errors
            and blocked.after_state.snapshot().to_json()
            == forged.snapshot().to_json()
            and not blocked.mutations
            and not blocked.events
            and not blocked.rng_events
        ),
        'mutation_backed_recheck': mutation_backed_recheck['ok'],
        'duplicate_callback_blocked': duplicate_callback_blocked,
        'source_trace_strict': source_trace['ok'],
        'max_sp_semantics': (
            ability_property_stat_name('MaxSP') == 'max_energy'
            and UNIT_ENERGY_EVENT_CONTRACT.payload_resource == 'energy'
            and TEAM_SKILL_POINT_EVENT_CONTRACT.payload_resource
            == 'skill_points'
        ),
        'repeat_mutation_counts': [len(first.mutations), len(second.mutations)],
        'blocked_errors': list(blocked.errors),
        'mutation_backed_recheck_evidence': mutation_backed_recheck,
        'source_trace_negative': source_trace,
    }

def _mutation_backed_recheck(state: BattleState, unit_id: str) -> dict[str, Any]:
    mutation = Mutation(
        op='set',
        path=('units', unit_id, 'shield_instances'),
        before=[],
        after=[{
            'instance_id': 'validation:p8_s16:shield',
            'remaining': 1.0,
        }],
        reason='validation formal mutation-backed watcher recheck',
        source='validation_fixture',
    )
    events = events_for_mutation(mutation, event_index=0)
    event = next((item for item in events if item.event_type == 'shield.change'), None)
    selected = _ability_property_recheck_unit_ids(
        state, event, (),
    ) if event is not None else ()
    return {
        'ok': event is not None and selected == (unit_id,),
        'event_type': event.event_type if event is not None else '',
        'event_target_id': event.target_id if event is not None else '',
        'selected_unit_ids': list(selected),
    }

def _duplicate_callback_blocked(rules: RuleBook, watcher: Any) -> bool:
    ranges = rules.ability_property_ranges_for_watcher(watcher.watcher_id)
    callback_id = next(
        (
            callback_id
            for item in ranges
            for callback_id in (
                item.enter_callback_id,
                item.exit_callback_id,
            )
            if callback_id
        ),
        '',
    )
    callback = rules.status_callback(callback_id) if callback_id else None
    if callback is None:
        return False
    try:
        RuleBook(
            replace(
                rules.ir,
                status_callbacks=(
                    *rules.ir.status_callbacks,
                    replace(
                        callback,
                        modifier_name=f'{callback.modifier_name}:forged',
                    ),
                ),
            )
        )
    except ValueError as exc:
        return str(exc).startswith('status_callback_identity_duplicate:')
    return False

def _source_trace_negative(rules: RuleBook, case: dict[str, Any]) -> dict[str, Any]:
    original = next(
        (
            mutation
            for mutation in case['add_commit'].mutations
            if mutation.source == 'ability_property_watcher_system'
        ),
        None,
    )
    if original is None:
        return {'ok': False, 'reason': 'watcher_mutation_missing'}
    forged = replace(original, metadata={
        **original.metadata,
        'source_trace': {'watcher_sources': []},
    })
    records = tuple(
        {**record, 'mutation_id': forged.stable_id()}
        for record in case['add_commit'].records
        if record.get('mutation_id') == original.stable_id()
    )
    transition = BattleTransition(
        transaction=ActionTransaction(
            command=ActionCommand(
                actor_id=case['unit_id'],
                action_id='equipment_effect',
                action_level=0,
                source='equipment_effect',
            ),
            before=case['before'].snapshot(),
            mutations=(forged,),
            settlement=ActionSettlement(
                action_id='equipment_effect',
                actor_id=case['unit_id'],
                target_ids=(),
                records=records,
            ),
        ),
        after=case['add_commit'].after_state.snapshot(),
    )
    audited = RuntimeSourceAuditor(rules).validate_transition(transition)
    reasons = [item.reason for item in audited.violations]
    return {
        'ok': not audited.ok and (
            'ability_property_watcher_source_trace_mismatch' in reasons
        ),
        'violation_reasons': reasons,
    }

def _audit_replay(bundle: dict[str, Any], lifecycle: dict[str, Any]) -> dict[str, Any]:
    case = lifecycle['case']
    samples = (
        ('speed_add', case['before'], case['add_commit']),
        (
            'speed_remove',
            case['add_commit'].after_state,
            case['remove_commit'],
        ),
        (
            'multi_wearer',
            lifecycle['multi']['before_a'],
            lifecycle['multi']['commit_a'],
        ),
        ('team', lifecycle['team']['before'], lifecycle['team']['commit']),
    )
    rows = []
    for (name, before, result) in samples:
        replay = MutationReducer().replay_snapshot(before, tuple(result.mutations), result.after_state.snapshot().to_json())
        transition = BattleTransition(
            transaction=ActionTransaction(
                command=ActionCommand(
                    actor_id='validation:p8_s16',
                    action_id='equipment_effect',
                    action_level=0,
                    source='equipment_effect',
                ),
                before=before.snapshot(),
                events=tuple(result.events),
                mutations=tuple(result.mutations),
                settlement=ActionSettlement(
                    action_id='equipment_effect',
                    actor_id='validation:p8_s16',
                    target_ids=(),
                    records=tuple(result.records),
                ),
            ),
            after=result.after_state.snapshot(),
            rng_events=tuple(result.rng_events),
        )
        audited = RuntimeSourceAuditor(bundle['rules']).validate_transition(transition)
        rows.append(
            {
                'name': name,
                'mutation_count': len(result.mutations),
                'source_audit_ok': audited.ok,
                'audit_violations': [
                    violation.to_json()
                    for violation in audited.violations[:5]
                ],
                'replay_ok': replay.ok,
                'replay_errors': list(replay.errors),
            }
        )
    return {'source_audit': bool(rows) and all((row['source_audit_ok'] for row in rows)), 'replay': bool(rows) and all((row['replay_ok'] for row in rows)), 'rows': rows}

def _execute(rules: Any, state: BattleState, unit_id: str, effect: Any, detail: dict[str, Any]) -> Any:
    executor = CombatExecutor(rules)
    source = binding_source_from_status_detail(detail, detail.get('dynamic_values'))
    if source is None:
        raise ValueError('selected status has no source-backed dynamic binding')
    result = executor.effects.execute(effect, EffectExecutionContext(state=state, caster_id=unit_id, owner_id=unit_id, source_id=str(detail.get('source_id') or ''), binding_sources=(source,), include_ambient_status_bindings=False))
    return executor.commit_eventful_transition(
        state,
        mutations=result.mutations,
        events=result.events,
        records=result.records,
        rng_events=result.rng_events,
        producer_kind='effect',
        producer_id=effect.effect_id,
        producer_ok=not result.unsupported,
        blocked_reason=','.join(result.unsupported),
    )

def _thresholds(bundle: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for threshold in bundle['dynamic_thresholds']:
        source = threshold.ability_source
        if source is None:
            continue
        if source.ability_name in result:
            raise ValueError(f'duplicate relic ability threshold:{source.ability_name}')
        result[source.ability_name] = threshold
    return result

def _templates(catalog: Any, set_key: Any, count: int) -> tuple[Any, ...]:
    by_slot = {}
    for template in catalog.template_definitions:
        if template.set_key != set_key or template.publication_status != 'published' or template.mode != 'BASIC':
            continue
        current = by_slot.get(template.slot_key)
        score = (template.max_level, template.rarity, template.definition_key.stable_id)
        if current is None or score > (current.max_level, current.rarity, current.definition_key.stable_id):
            by_slot[template.slot_key] = template
    selected = tuple((by_slot[key] for key in sorted(by_slot, key=lambda item: item.stable_id)))
    if len(selected) < count:
        raise ValueError(f'relic set template count incomplete:{set_key.stable_id}')
    return selected[:count]

def _equipment(bundle: dict[str, Any], templates: tuple[Any, ...], tag: str, *, speed_level: int | None=None) -> EquipmentBuildInput:
    relics = []
    for (index, template) in enumerate(templates):
        preferred = 'SpeedDelta' if template.slot_key.definition_identity == 'FOOT' and speed_level is not None else ''
        affix = _main_affix(bundle, template, preferred)
        level = speed_level if speed_level is not None and affix.property_type == 'SpeedDelta' else 0
        relics.append(RelicInstanceInput(instance_id=f'validation:p8_s16:{tag}:relic:{index}', template_key=template.definition_key, slot_key=template.slot_key, level=level, main_affix_key=affix.definition_key))
    return EquipmentBuildInput(build_id=f'validation:p8_s16:{tag}', character_card_id=bundle['card'].card_id, relics=tuple(relics))

def _main_affix(bundle: dict[str, Any], template: Any, preferred: str) -> Any:
    groups = {item.definition_key: item for item in bundle['catalog'].main_affix_group_definitions}
    affixes = {item.definition_key: item for item in bundle['catalog'].main_affix_definitions}
    candidates = tuple((affixes[key] for key in groups[template.main_affix_group_key].affix_keys))
    return next((item for item in candidates if item.property_type == preferred), candidates[0])

def _detail(state: BattleState, unit_id: str, modifier_name: str) -> dict[str, Any] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    return next((detail for detail in unit.flags.get('status_details', ()) if isinstance(detail, dict) and detail.get('modifier_name') == modifier_name), None)

def _evaluate(condition: Any, state: BattleState, unit_id: str, detail: dict[str, Any] | None) -> Any:
    source = (
        binding_source_from_status_detail(detail, detail.get('dynamic_values'))
        if detail is not None
        else None
    )
    return RuleEvaluator().evaluate_condition_result(
        condition,
        EvaluationContext(
            state=state,
            actor_id=unit_id,
            owner_id=unit_id,
            target_id=unit_id,
            param_entity_id=unit_id,
            status_detail=detail,
            binding_sources=(source,) if source is not None else (),
        ),
    )

def _speed(state: BattleState, unit_id: str) -> float:
    return effective_unit_stat(state.units[unit_id], 'speed').value

def _replace_details(state: BattleState, unit_id: str, details: list[dict[str, Any]]) -> BattleState:
    unit = state.units[unit_id]
    updated = replace(unit, flags={**unit.flags, 'status_details': details})
    return replace(state, units={**state.units, unit_id: updated})

def _with_status(state: BattleState, unit_id: str, *, status_category: str='buff', behavior_flags: tuple[str, ...]=()) -> BattleState:
    details = [dict(item) for item in state.units[unit_id].flags.get('status_details', ()) if isinstance(item, dict)]
    details.append(
        {
            'instance_id': f'validation:p8_s16:condition:{len(details)}',
            'status_id': 'validation:condition',
            'modifier_name': 'validation_condition_state',
            'owner_id': unit_id,
            'source_id': 'validation:committed_state_fixture',
            'caster_id': unit_id,
            'status_category': status_category,
            'behavior_flags': list(behavior_flags),
            'ability_property_watcher_ids': [],
        }
    )
    return _replace_details(state, unit_id, details)

def _without_category(state: BattleState, unit_id: str, category: str) -> BattleState:
    details = [dict(item) for item in state.units[unit_id].flags.get('status_details', ()) if isinstance(item, dict) and str(item.get('status_category') or '').lower() != category.lower()]
    return _replace_details(state, unit_id, details)

def _without_behavior_flags(state: BattleState, unit_id: str, flags: tuple[str, ...]) -> BattleState:
    removed = set(flags)
    details = []
    for item in state.units[unit_id].flags.get('status_details', ()):
        if isinstance(item, dict):
            details.append({**item, 'behavior_flags': [flag for flag in item.get('behavior_flags', ()) if flag not in removed]})
    return _replace_details(state, unit_id, details)

def _remove_watcher_identity(state: BattleState, unit_id: str, modifier_name: str) -> BattleState:
    details = []
    found = False
    for item in state.units[unit_id].flags.get('status_details', ()):
        copied = dict(item)
        if copied.get('modifier_name') == modifier_name:
            copied.pop('ability_property_watcher_ids', None)
            found = True
        details.append(copied)
    if not found:
        raise ValueError('watcher detail missing for atomic negative')
    return _replace_details(state, unit_id, details)

def _behavior_flags(payload: dict[str, Any]) -> tuple[str, ...]:
    plural = payload.get('Flags')
    if isinstance(plural, (list, tuple)):
        values = tuple((item for item in plural if isinstance(item, str) and item))
        if values:
            return values
    singular = payload.get('Flag')
    return (singular,) if isinstance(singular, str) and singular else ()

def _fingerprint(bundle: dict[str, Any]) -> dict[str, Any]:
    values = {json.dumps(graph.source.evidence.get('source_fingerprint'), sort_keys=True, separators=(',', ':')) for graph in bundle['graphs']}
    if len(values) != 1:
        raise ValueError('focused relic graph fingerprints conflict')
    return json.loads(next(iter(values)))

def _set_handler_hits() -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[1]
    files = (
        root / 'rules' / 'ability_properties.py',
        root / 'rules' / 'evaluator.py',
        root / 'systems' / 'ability_property_watchers.py',
        root / 'systems' / 'event_dispatch.py',
        root / 'systems' / 'status.py',
        root / 'systems' / 'status_callbacks.py',
        root / 'systems' / 'target.py',
        root / 'systems' / 'unit_stats.py',
    )
    hits = []
    for path in files:
        text = path.read_text(encoding='utf-8')
        for marker in ('MRelic_', 'relic_set_handlers', 'relic_set_handler'):
            if marker in text:
                hits.append({'path': str(path.relative_to(root)), 'marker': marker, 'count': text.count(marker)})
    return hits

def _public_lifecycle(value: dict[str, Any]) -> dict[str, Any]:
    case = value['case']
    return {
        're_evaluated': value['re_evaluated'],
        'speed_case': {
            'watcher_id': case['watcher'].watcher_id,
            'condition_id': case['condition'].condition_id,
            'add_effect_id': case['add_effect'].effect_id,
            'remove_effect_id': case['remove_effect'].effect_id,
            'speed_level': case['speed_level'],
            'speed_before': case['speed_before'],
            'speed_after_add': case['speed_after_add'],
            'speed_after_remove': case['speed_after_remove'],
            'condition_results': case['results'],
            'add_mutations': len(case['add_commit'].mutations),
            'remove_mutations': len(case['remove_commit'].mutations),
        },
        'multi_wearer': {
            key: item
            for key, item in value['multi'].items()
            if key
            not in {'before_a', 'before_b', 'commit_a', 'commit_b'}
        },
        'team_attribution': {
            key: item
            for key, item in value['team'].items()
            if key not in {'before', 'commit'}
        },
    }

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('--tbgd-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    return parser.parse_args()

def main() -> int:
    args = _parse_args()
    summary = validate(args.tbgd_root, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary['ok'] else 1
if __name__ == '__main__':
    raise SystemExit(main())
