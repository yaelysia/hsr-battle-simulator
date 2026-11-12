"""Project selected equipment and its table/ability dependencies before lowering."""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from .equipment_discovery import PRIMARY_TABLE_ROLES, build_primary_equipment_source_fingerprint, discover_primary_equipment_paths
from .light_cone_cards import LIGHT_CONE_TABLE_ROLES, build_light_cone_catalog_from_documents
from .relic_cards import RELIC_TABLE_ROLES, build_relic_catalog_from_documents


def build_equipment_scope(root: Path, light_cone_ids: frozenset[str], relic_template_ids: frozenset[str]):
    root = root.resolve()
    discovery = discover_primary_equipment_paths(root)
    roles = (LIGHT_CONE_TABLE_ROLES if light_cone_ids else ()) + (RELIC_TABLE_ROLES if relic_template_ids else ())
    raw_sources = {}
    rows = {}
    indexes = {}
    for role in roles:
        path = discovery['table_paths'][role]
        raw = path.read_bytes()
        raw_sources[PRIMARY_TABLE_ROLES[role]] = raw
        document = json.loads(raw, parse_float=Decimal)
        if not isinstance(document, list) or any(not isinstance(row, dict) for row in document):
            raise ValueError(f'equipment table must contain object rows:{role}')
        rows[role] = document
        indexes[role] = list(range(len(document)))

    def select(role, key, identities):
        retained = [(index, row) for index, row in zip(indexes[role], rows[role])
                    if str(row.get(key)) in identities]
        indexes[role] = [index for index, _ in retained]
        rows[role] = [row for _, row in retained]

    if light_cone_ids:
        missing = light_cone_ids - {str(row.get('EquipmentID')) for row in rows['equipment_config']}
        if missing:
            raise ValueError(f'light cone source missing:{sorted(missing)}')
        select('equipment_config', 'EquipmentID', light_cone_ids)
        select('equipment_promotion_config', 'EquipmentID', light_cone_ids)
        select('equipment_skill_config', 'SkillID', {str(row.get('SkillID')) for row in rows['equipment_config']})
    if relic_template_ids:
        missing = relic_template_ids - {str(row.get('ID')) for row in rows['relic_config']}
        if missing:
            raise ValueError(f'relic template source missing:{sorted(missing)}')
        sets = {str(row.get('SetID')) for row in rows['relic_config'] if str(row.get('ID')) in relic_template_ids}
        # Keep each selected set's complete slot/rarity membership; it defines
        # domains and allowed affix groups, not just the equipped slot.
        select('relic_config', 'SetID', sets)
        select('relic_set_config', 'SetID', sets)
        select('relic_set_skill_config', 'SetID', sets)
        select('relic_base_type', 'Type', {'None', *(str(row.get('Type')) for row in rows['relic_config'])})
        select('relic_main_affix_config', 'GroupID', {str(row.get('MainAffixGroup')) for row in rows['relic_config']})
        select('relic_sub_affix_config', 'GroupID', {str(row.get('SubAffixGroup')) for row in rows['relic_config']})

    required_names = {row['AbilityName'] for role in ('equipment_skill_config', 'relic_set_skill_config')
                      for row in rows.get(role, ()) if row.get('AbilityName')}
    documents = {}
    definitions = defaultdict(list)
    # Discover definitions once for both catalogs. File names do not encode
    # ability ownership; references may point to a definition in another file.
    if required_names:
        for path in discovery['ability_paths']:
            relative = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            document = json.loads(raw, parse_float=Decimal)
            documents[relative] = (raw, document)
            for ability in document.get('AbilityList', ()):
                if isinstance(ability, dict) and isinstance(ability.get('Name'), str):
                    definitions[ability['Name']].append((relative, ability))
            for name, modifier in document.get('Modifiers', {}).items():
                definitions[name].append((relative, modifier))

    def strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for value in node.values():
                yield from strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from strings(value)

    pending = list(required_names)
    visited = set()
    selected_paths = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        for relative, definition in definitions.get(name, ()):
            selected_paths.add(relative)
            pending.extend(value for value in strings(definition) if value in definitions and value not in visited)
    abilities = tuple((path, documents[path][1]) for path in sorted(selected_paths))
    raw_sources.update((path, documents[path][0]) for path in selected_paths)
    fingerprint = build_primary_equipment_source_fingerprint(sorted(raw_sources.items()))
    common = dict(ability_documents=abilities, source_content_fingerprint=fingerprint,
                  source_kind='tbgd', source_row_indexes=indexes)
    light_cones = build_light_cone_catalog_from_documents(
        equipment_rows=rows['equipment_config'], promotion_rows=rows['equipment_promotion_config'],
        skill_rows=rows['equipment_skill_config'], **common,
    ) if light_cone_ids else None
    relics = build_relic_catalog_from_documents(
        relic_rows=rows['relic_config'], base_type_rows=rows['relic_base_type'],
        main_affix_rows=rows['relic_main_affix_config'], sub_affix_rows=rows['relic_sub_affix_config'],
        set_rows=rows['relic_set_config'], set_skill_rows=rows['relic_set_skill_config'],
        require_full_catalog=False, **common,
    ) if relic_template_ids else None
    return light_cones, relics
