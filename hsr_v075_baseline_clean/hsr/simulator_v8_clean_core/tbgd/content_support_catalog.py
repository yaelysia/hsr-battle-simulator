"""One batch of existing source preprocessors for the read-only support matrix."""
from __future__ import annotations

import json
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..rules.rulebook import CharacterAbilitySourceGraphQuery
from .character_cards import CHARACTER_ACTION_DEFINITION_TABLES, build_character_card_ir, list_character_choices, _load_text_map
from .light_cone_cards import build_light_cone_catalog
from .lowering import LoweringLimits, TBGDLowering, _positive_int, _stage_config_wave_count, _wave_level_policy
from .monster_cards import build_monster_card_ir
from .relic_cards import build_relic_catalog


def _check(scope: str, ref_id: str, coverage: str, reason: str = '', **details: Any) -> dict[str, Any]:
    # Source preprocessors describe their own boundary, never runtime admission.
    status = ('blocked' if reason or coverage in {'blocked', 'unsupported', 'partial'}
              else 'supported' if coverage in {'executable', 'lowered', 'resolved'} else 'unchecked')
    return {'kind': scope, 'ref_id': ref_id, 'status': status,
            'reasons': [reason] if reason else [], **details}


def _source_ref(source: Any) -> dict[str, Any]:
    evidence = source.evidence
    return {'source_path': source.source_path, 'raw_type': source.raw_type, 'raw_id': source.raw_id,
            'json_path': evidence.get('json_path', ''),
            'row_index': evidence.get('row_index'), 'content_sha256': evidence.get('content_sha256', '')}


def _row(kind: str, identity: str, source: Any, *, owners: list[str] | None = None,
         name: str = '', coverage: str = 'lowered', reason: str = '', **details: Any) -> dict[str, Any]:
    return {'kind': kind, 'content_id': identity, 'owner_ids': owners or [], 'display_name': name or identity,
            'source_checks': [_check('source_definition_preprocessing', identity, coverage, reason,
                                     source=_source_ref(source))], 'formal_checks': [], **details}


def build_content_support_catalog(root: Path) -> dict[str, Any]:
    """No CanonicalIR compilation, BattleSession, battle, or per-card rebuild."""
    lowerer = TBGDLowering(root, LoweringLimits(max_records_per_table=None))
    graph = lowerer.build_character_ability_source_graph_catalog()
    controls = lowerer.build_character_control_flow_contract_catalog()
    cards = build_character_card_ir(root, max_records_per_table=None,
        skill_tables=CHARACTER_ACTION_DEFINITION_TABLES, ability_source_graph_catalog=graph,
        ability_scope_catalog=lowerer._character_ability_scope_catalog)
    names = {item['character_card_id']: item for item in list_character_choices(root)}
    rows, by_id = [], {}

    def add(row):
        if row['content_id'] in by_id:
            raise ValueError(f"duplicate support content identity:{row['content_id']}")
        rows.append(row)
        by_id[row['content_id']] = row
        return row

    for card in cards.character_data_cards:
        add(_row('character', card.card_id, card.source, owners=[card.entity_ref],
            name=names.get(card.card_id, {}).get('name', card.entity_ref), coverage=card.coverage_status,
            reason=card.blocked_reason, entity_ref=card.entity_ref, action_ids=[f'avatar_skill:{item}' for item in card.skill_ids],
            shared_graph_refs=[ref.graph_id for ref in card.ability_source_graph_refs if ref.reference_kind != 'owned']))
    action_query = CharacterAbilitySourceGraphQuery(graph)
    relevant_gap_ids = set()
    for action in graph.action_sources:
        owner = f'avatar:{action.owner_avatar_id}'
        query = action_query.query_action(action.owner_avatar_id, action.action_id)
        relevant_gap_ids.update(query.gap_ids)
        row = add(_row('character_action', action.action_id, action.config_source, owners=[owner],
            coverage='resolved' if query.status == 'resolved' else 'blocked', reason=query.blocked_reason,
            levels=list(action.levels), action_kind=action.action_kind, ability_definition_ids=list(query.definition_ids)))
        row['source_checks'][0]['kind'] = 'source_action_ability_linkage'
        row['source_checks'][0]['gap_ids'] = list(query.gap_ids)
    for node in cards.character_trace_nodes:
        add(_row('trace', node.trace_node_id, node.source, owners=[f'avatar:{node.avatar_id}'],
            coverage=node.coverage_status, reason=node.blocked_reason, level=node.level,
            trace_id=node.trace_id, default_unlocked=node.default_unlocked))
    for node in cards.character_eidolon_slots:
        add(_row('eidolon', node.eidolon_slot_id, node.source, owners=[f'avatar:{node.avatar_id}'],
            coverage=node.coverage_status, reason=node.blocked_reason, rank=node.rank))
    for gap in graph.gaps:
        if gap.gap_id not in relevant_gap_ids:
            continue
        owner = by_id.get(f'character_data_card:avatar:{gap.owner_avatar_id}')
        if owner is not None:
            owner['source_checks'].append(_check('source_ability_linkage_gap', gap.gap_id, 'blocked',
                gap.blocked_reason, source=_source_ref(gap.source), gap_kind=gap.gap_kind))
    for gap in cards.character_build_selector_gaps:
        owner = by_id.get(gap.character_data_card_id)
        if owner is not None:
            owner['source_checks'].append(_check('source_build_selector_gap', gap.selector_gap_id, 'blocked',
                gap.blocked_reason, source=_source_ref(gap.selector_source)))
    owners_by_path = {source.source.source_path: source.avatar_id for source in graph.sources if source.avatar_id}
    control_groups = defaultdict(list)
    for node in controls.nodes:
        control_groups[node.source.source_path].append(node)
    for path, nodes in sorted(control_groups.items()):
        avatar = owners_by_path.get(path)
        owner = by_id.get(f'character_data_card:avatar:{avatar}') if avatar else None
        if owner is None:
            owner = add(_row('shared_control_flow', f'control_flow_source:{path}', nodes[0].source))
        blockers = [node for node in nodes if node.blocked_reason or node.coverage_status == 'blocked']
        owner['source_checks'].append(_check('source_control_flow_structure', path,
            'blocked' if blockers else 'lowered', node_count=len(nodes),
            **({'reason': 'source_control_flow_contract_gaps'} if blockers else {})))
        for node in blockers:
            owner['source_checks'].append(_check('source_control_flow_node', node.node_id, node.coverage_status,
                node.blocked_reason, family=node.family, downstream_stages=list(node.downstream_stages),
                source=_source_ref(node.source)))
    for issue in controls.issues:
        avatar = owners_by_path.get(issue.source.source_path)
        owner = by_id.get(f'character_data_card:avatar:{avatar}') if avatar else by_id.get(
            f'control_flow_source:{issue.source.source_path}')
        if owner is not None:
            owner['source_checks'].append(_check('source_control_flow_issue', issue.subject, 'blocked',
                issue.code, detail=issue.detail, source=_source_ref(issue.source)))
    # Release the frozen raw trees before reading the other source families.
    source_fingerprints = {'character_abilities': graph.source_fingerprint,
                           'control_flow_dependencies': controls.dependency_fingerprint}
    del graph, controls, lowerer, cards, action_query, control_groups

    monsters = build_monster_card_ir(root, max_records_per_table=None)
    monster_actions = {}
    for card in monsters.monster_data_cards:
        display = card.display.get('localized_names', {})
        add(_row('monster', card.card_id, card.source, owners=[card.entity_ref],
            name=display.get('CHS') or card.entity_ref, coverage=card.coverage_status, reason=card.blocked_reason,
            entity_ref=card.entity_ref, action_ids=[f'monster_skill:{item}' for item in card.skill_ids]))
        for slot in card.skill_slots:
            action_id = str(slot['action_ref'])
            if action_id not in monster_actions:
                source = slot.get('source_trace', {})
                monster_actions[action_id] = {
                    'kind': 'monster_action', 'content_id': action_id, 'owner_ids': [], 'display_name': action_id,
                    'source_checks': [_check('source_monster_skill_slot', action_id,
                        str(slot.get('coverage_status') or 'unchecked'), str(slot.get('blocked_reason') or ''),
                        source=source)], 'formal_checks': [],
                }
            monster_actions[action_id]['owner_ids'].append(card.entity_ref)
    for action in monster_actions.values():
        add(action)
    monster_refs = {card.entity_ref for card in monsters.monster_data_cards}
    del monsters

    cones = build_light_cone_catalog(root)
    text_map = _load_text_map(root)
    for cone in cones.diagnostic_definitions:
        add(_row('light_cone', cone.definition_key.stable_id, cone.source,
            name=text_map.get(cone.equipment_name_hash, cone.raw_equipment_id),
            coverage=cone.coverage_status, reason=cone.blocked_reason,
            publication_status=cone.publication_status, path_type=cone.path_type))
    source_fingerprints['light_cones'] = dict(cones.source_content_fingerprint)
    del cones
    relics = build_relic_catalog(root)
    for kind, values in (('relic_set', relics.diagnostic_catalog.set_definitions),
                         ('relic_set_threshold', relics.diagnostic_catalog.set_thresholds),
                         ('relic_template', relics.diagnostic_catalog.template_definitions)):
        for value in values:
            add(_row(kind, value.definition_key.stable_id, value.source,
                coverage=value.coverage_status, reason=value.blocked_reason))
    source_fingerprints['relics'] = dict(relics.source_content_fingerprint)
    del relics

    stages_path = root / 'ExcelOutput/StageConfig.json'
    stage_content = stages_path.read_bytes()
    hard_levels = TBGDLowering(root, LoweringLimits(max_records_per_table=None))._hard_level_profiles()
    elite_profiles = lowerer._elite_group_profiles()
    source_fingerprints['stage_config'] = sha256(stage_content).hexdigest()
    elite_path = root / 'ExcelOutput/EliteGroup.json'
    source_fingerprints['elite_groups'] = sha256(elite_path.read_bytes() if elite_path.exists() else b'').hexdigest()
    for index, stage in enumerate(json.loads(stage_content)):
        stage_id = str(stage['StageID'])
        identity = f'wave_definition:stage:{stage_id}'
        waves = stage.get('MonsterList')
        declared = _stage_config_wave_count(stage.get('StageConfigData'))
        reasons = []
        if not isinstance(waves, list) or not waves:
            reasons.append('stage_wave_entries_missing')
            waves = []
        if declared <= 0:
            reasons.append('stage_wave_count_missing')
        elif declared != len(waves):
            reasons.append('stage_wave_count_monster_list_mismatch')
        refs = []
        for wave in waves:
            if not isinstance(wave, dict):
                reasons.append('stage_monster_wave_not_object')
                continue
            for monster in wave.values():
                ref = f'monster:{monster}'
                refs.append(ref)
                if ref not in monster_refs:
                    reasons.append(f'wave_monster_entity_missing:{monster}')
        level, hard = _positive_int(stage.get('Level')), _positive_int(stage.get('HardLevelGroup'))
        elite = elite_profiles.get(_positive_int(stage.get('EliteGroup')), ())
        policy = _wave_level_policy(stage_id=stage_id, stage_row_index=index, level=level,
            hard_level_group=hard, hard_level_profile=hard_levels.get((hard, level)),
            elite_group=stage.get('EliteGroup'), elite_profile=elite[0] if len(elite) == 1 else None)
        if policy['blocked_reason']:
            reasons.append(str(policy['blocked_reason']))
        row = {'kind': 'stage', 'content_id': identity, 'owner_ids': [],
               'display_name': text_map.get(str(stage.get('StageName', {}).get('Hash')), stage_id),
               'source_checks': [{'kind': 'stage_wave_source_structure', 'ref_id': identity,
                    'status': 'blocked' if reasons else 'supported', 'reasons': list(dict.fromkeys(reasons)),
                    'source': {'source_path': 'ExcelOutput/StageConfig.json', 'row_index': index}}],
               'formal_checks': [], 'stage_id': stage_id, 'wave_count': len(waves),
               'monster_refs': list(dict.fromkeys(refs)), 'stage_ability_refs': stage.get('StageAbilityConfig', [])}
        row['formal_checks'].append(_check('full_stage_environment', identity, 'unchecked',
            requires='selected_stage_environment_compilation', applies_to='full_stage_only; wave_only remains separate'))
        add(row)

    examples_root = Path(__file__).resolve().parents[1] / 'examples/cli'
    for path in sorted(examples_root.glob('*.json')):
        example = json.loads(path.read_text())
        if not isinstance(example.get('units'), list) or 'battle_setup' not in example:
            continue
        identities = {unit.get('character_build', {}).get('character_card_id') for unit in example['units']}
        identities.add(f"wave_definition:stage:{example.get('stage_ref', '')}")
        commands_path = path.with_name(path.stem + '.commands.json')
        if commands_path.exists():
            identities.update(item.get('action_id') for item in json.loads(commands_path.read_text()).get('commands', []))
        for identity in identities:
            row = by_id.get(identity)
            if row is not None:
                evidence = row.setdefault('execution_evidence', {'status': 'example_available_not_verified', 'examples': []})
                evidence['examples'].append({'scenario_path': str(path.relative_to(Path(__file__).resolve().parents[1])),
                    'commands_path': str(commands_path.relative_to(Path(__file__).resolve().parents[1])) if commands_path.exists() else None,
                    'scope': 'saved configuration/route; not a passing execution result'})
    return {'rows': sorted(rows, key=lambda row: (row['kind'], row['content_id'])),
            'source_fingerprints': source_fingerprints}
