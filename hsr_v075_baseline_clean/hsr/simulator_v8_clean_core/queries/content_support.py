"""Read-only, scoped support reporting; reports never grant battle admission."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

from ..builds.character_assembler import assemble_character_build
from ..core.model import BattleState, UnitState
from ..rules.rulebook import RuleBook
from ..scenarios.schema import ScenarioSpec
from ..scenarios.build_state import _formal_character_activation
from ..systems.action_contract import _formal_action_task_graph_projection


def summarize_content_support(scope: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize only the declared checks, retaining unknowns and their scope."""
    return {
        'scope': scope,
        'status': ('blocked' if any(item['status'] == 'blocked' for item in checks)
                   else 'supported' if checks and all(item['status'] == 'supported' for item in checks)
                   else 'unchecked'),
        'checks': checks,
        'blocked_reasons': list(dict.fromkeys(reason for item in checks
                                            if item['status'] == 'blocked' for reason in item['reasons'])),
    }


def _check(scope: str, ref_id: str, coverage: str, reason: str = '', **details: Any) -> dict[str, Any]:
    status = ('blocked' if reason or coverage in {'blocked', 'unsupported', 'partial'}
              else 'supported' if coverage in {'executable', 'lowered', 'admitted', 'resolved'} else 'unchecked')
    return {'kind': scope, 'ref_id': ref_id, 'status': status,
            'reasons': [reason] if reason else [], **details}


def _action_checks(rules: RuleBook, action_id: str, level: int, *, state: BattleState | None = None,
                   actor_id: str = '') -> list[dict[str, Any]]:
    definition = rules.action_definition(action_id, level)
    if definition is None:
        return [_check('compiled_action_definition', action_id, 'blocked', 'action_definition_missing', level=level)]
    checks = [_check('compiled_action_definition', action_id, definition.coverage_status, level=level)]
    # Startup/passive/technique invocations have different authorities; an absent
    # player-action root is not evidence that these abilities are unsupported.
    if definition.attack_type not in {'Normal', 'BPSkill', 'Ultra', 'Insert'} and not action_id.startswith('monster_skill:'):
        checks.append(_check('invocation_and_execution', action_id, 'unchecked', level=level))
        return checks
    target = rules.action_target_contract(action_id, level)
    checks.append(_check('compiled_target_contract', action_id, target.resolution_status,
                         target.blocked_reason, level=level))
    projection = _formal_action_task_graph_projection(
        rules, action_id, level, rules.ability_tasks_for_action(action_id, level),
        state=state, actor_id=actor_id,
    )
    checks.append({
        'kind': 'build_selected_graph_static' if state is not None else 'all_branches_graph_static',
        'ref_id': action_id, 'level': level,
        'status': ('blocked' if projection.blocked_reasons else
                   'supported' if projection.root_graph_ids else 'unchecked'),
        'reasons': list(projection.blocked_reasons),
        'blocker_provenance': list(projection.blocker_provenance),
        'root_graph_ids': list(projection.root_graph_ids),
    })
    return checks


def _configured_build_rows(rules: RuleBook, scenario: ScenarioSpec) -> list[dict[str, Any]]:
    rows = []
    for unit in scenario.units:
        build = unit.character_build
        if build is None:
            continue
        result = assemble_character_build(rules, build)
        reasons = [*result.blocked_reasons, *(item.reason for item in result.unadmitted_mechanism_diagnostics)]
        equipment = result.equipment_assembly_result
        if equipment is not None:
            reasons.extend(item.reason_code for item in equipment.battle_admission_blockers)
            reasons.extend(item.reason for item in equipment.diagnostics)
        checks = [{'kind': 'character_build', 'ref_id': build.character_card_id, 'unit_id': unit.unit_id,
                   'status': 'supported' if result.battle_admission_status == 'admitted' else 'blocked',
                   'reasons': list(dict.fromkeys(reasons)), 'assembly_status': result.assembly_status,
                   'result_fingerprint': result.result_fingerprint}]
        actions = []
        if result.battle_admission_status == 'admitted':
            # Reuse the formal build-selection producer without creating a
            # BattleSession, running birth callbacks or inventing action facts.
            flags, _, _ = _formal_character_activation(rules, unit, result)
            query_state = BattleState(units={unit.unit_id: UnitState(
                unit.unit_id, unit.side, unit.entity_ref, level=unit.level, flags=flags,
            )})
            for skill in result.effective_skill_levels:
                action_id = f'avatar_skill:{skill.skill_id}'
                actions.append(summarize_content_support('build_selected_action_static', _action_checks(
                    rules, action_id, skill.effective_level, state=query_state, actor_id=unit.unit_id,
                )))
        rows.append({
            'kind': 'character_build', 'content_id': f'character_build:{unit.unit_id}:{build.input_fingerprint}',
            'owner_ids': [unit.entity_ref], 'display_name': unit.unit_id,
            'source_checks': [], 'formal_checks': checks, 'actions': actions,
            'build': build.to_json(), 'scenario_id': scenario.scenario_id,
            'execution_evidence': {'status': 'not_executed', 'examples': []},
        })
    return rows


def content_support_matrix(catalog: dict[str, Any], *, rules: RuleBook | None = None,
                           scenario: ScenarioSpec | None = None) -> dict[str, Any]:
    """Merge one source inventory with available formal IR and selected builds.

    Whole-directory source checks and selected-IR checks remain separate. Neither
    a source definition nor a statically admitted graph proves a complete battle.
    """
    if scenario is not None and rules is None:
        raise ValueError('selected build support requires its formal RuleBook')
    rows = deepcopy(catalog['rows'])
    source_gaps = {check['ref_id']: check for row in rows for check in row['source_checks']
                   if check['kind'] == 'source_ability_linkage_gap'}
    for row in rows:
        gap_ids = dict.fromkeys(gap_id for check in row['source_checks'] for gap_id in check.get('gap_ids', ()))
        present = {check['ref_id'] for check in row['source_checks']}
        row['source_checks'].extend(deepcopy(source_gaps[gap_id]) for gap_id in gap_ids
                                    if gap_id in source_gaps and gap_id not in present)
    if rules is not None:
        ir = rules.ir
        compiled = {}
        for values, identity in (
            (ir.character_data_cards, 'card_id'), (ir.monster_data_cards, 'card_id'),
            (ir.character_trace_nodes, 'trace_node_id'), (ir.character_eidolon_slots, 'eidolon_slot_id'),
            (ir.wave_definitions, 'wave_definition_id'),
        ):
            compiled.update((getattr(value, identity), value) for value in values)
        for values in (ir.light_cone_definitions, ir.relic_set_definitions, ir.relic_set_thresholds,
                       ir.relic_template_definitions):
            compiled.update((value.definition_key.stable_id, value) for value in values)
        actions = defaultdict(list)
        for definition in ir.action_definitions:
            actions[definition.action_id].append(definition.level)
        action_cache = {}
        for row in rows:
            formal = row.setdefault('formal_checks', [])
            value = compiled.get(row['content_id'])
            if value is not None:
                formal.append(_check('compiled_definition', row['content_id'], value.coverage_status,
                                     value.blocked_reason, source=value.source.to_json()))
                if row['kind'] == 'stage':
                    formal[:] = [check for check in formal if check['kind'] != 'full_stage_environment']
                    uncompiled = value.stage_environment_blocked_reason == 'stage_environment_not_compiled'
                    formal.append(_check('full_stage_environment', row['content_id'],
                        'unchecked' if uncompiled else value.stage_environment_status,
                        '' if uncompiled else value.stage_environment_blocked_reason,
                        phase_ids=list(value.stage_startup_phase_ids)))
                if row['kind'] in {'character', 'monster', 'trace', 'eidolon', 'light_cone',
                                   'relic_set', 'relic_set_threshold', 'relic_template', 'stage'}:
                    formal.append(_check('complete_content_behavior', row['content_id'], 'unchecked'))
            if row['kind'] in {'character_action', 'monster_action'} and row['content_id'] in actions:
                action_id = row['content_id']
                if action_id not in action_cache:
                    action_cache[action_id] = [check for level in sorted(set(actions[action_id]))
                                              for check in _action_checks(rules, action_id, level)]
                formal.extend(deepcopy(action_cache[action_id]))
        if scenario is not None:
            rows.extend(_configured_build_rows(rules, scenario))
    summary = defaultdict(lambda: {'source': Counter(), 'formal': Counter(), 'evidence': Counter()})
    for row in rows:
        source = summarize_content_support('source_preprocessing', row['source_checks'])
        formal = summarize_content_support('formal_static_admission', row.get('formal_checks', []))
        row['source_status'], row['formal_status'] = source['status'], formal['status']
        row['known_source_gaps'] = source['blocked_reasons']
        row['formal_blocked_reasons'] = formal['blocked_reasons']
        evidence = row.setdefault('execution_evidence', {'status': 'not_executed', 'examples': []})
        summary[row['kind']]['source'][source['status']] += 1
        summary[row['kind']]['formal'][formal['status']] += 1
        summary[row['kind']]['evidence'][evidence['status']] += 1
    return {
        'schema_version': 'hsr.content_support_matrix.v1',
        'source_fingerprints': deepcopy(catalog.get('source_fingerprints', {})),
        'check_scope': {'source': 'source preprocessing and linkage only',
                        'formal': 'available compiled IR; selected build checks do not execute combat',
                        'execution': 'examples are references, not passing evidence'},
        'summary': {kind: {channel: dict(counts) for channel, counts in channels.items()}
                    for kind, channels in sorted(summary.items())},
        'rows': rows,
    }
