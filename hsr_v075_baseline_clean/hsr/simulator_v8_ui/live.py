"""Local UI transport; BattleSession remains the sole battle authority."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Any
from uuid import uuid4

from simulator_v8_clean_core.archive_json import decode_archive_json
from simulator_v8_clean_core.battle_archive import fork_session, restore_session, verify_archive, write_archive
from simulator_v8_clean_core.build_types import canonical_json_fingerprint
from simulator_v8_clean_core.builds.character_assembler import assemble_character_build, _current_card_trace_nodes
from simulator_v8_clean_core.builds.models import CharacterBuildInput, CharacterInitialConditionInput
from simulator_v8_clean_core.equipment.models import (
    EquipmentBuildInput, EquipmentDefinitionKey, LightConeInstanceInput, RelicInstanceInput, RelicSubAffixRollInput,
)
from simulator_v8_clean_core.queries.equipment import EquipmentQueryService
from simulator_v8_clean_core.queries.content_support import (
    content_support_matrix, summarize_content_support as _content_support,
)
from simulator_v8_clean_core.rules.rulebook import RuleBook
from simulator_v8_clean_core.scenarios.loader import ScenarioLoader
from simulator_v8_clean_core.session import BattleSession, command_from_json, command_to_json
from simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook, list_stage_choices
from simulator_v8_clean_core.tbgd.character_cards import _load_text_map, list_character_choices
from simulator_v8_clean_core.tbgd.content_support_catalog import build_content_support_catalog
from simulator_v8_clean_core.tbgd.relic_cards import load_relic_set_display_names

from .report import (
    blocked_records, build_action_prompt, build_battlefield_view, build_event_replay_view,
    build_step_report, damage_records, panel_source_breakdown, settlement_records,
    transition_summary,
)


EXAMPLES_ROOT = Path(__file__).resolve().parents[1] / 'simulator_v8_clean_core/examples/cli'


class SessionConflict(ValueError):
    pass


def _request_archive(request: dict[str, Any]) -> Any:
    """Accept the archive object or its exact JSON text.

    Browser JSON.parse/stringify rewrites ``1.0`` as ``1``; the archive graph
    distinguishes float and integer scalars, so a round-tripped object no longer
    matches the session it was exported from. The text form keeps the original
    number spelling and is decoded here, once, by Python's JSON parser.
    """
    archive = request.get('archive')
    text = request.get('archive_text')
    if archive is not None and text is not None:
        raise ValueError('归档只能以对象或原文提供其中一种。')
    if text is not None:
        if not isinstance(text, str) or not text:
            raise ValueError('归档原文必须是非空 JSON 文本。')
        try:
            archive = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f'归档原文不是有效 JSON：{exc.msg}（第 {exc.lineno} 行第 {exc.colno} 列）') from exc
    return archive


class LiveBattle:
    def __init__(self, tbgd_root: Path):
        self.tbgd_root = tbgd_root
        # Ponytail: one local battle, serialized to bound compiler/state memory.
        # Multi-user hosting needs a bounded session store and per-session locks.
        self.lock = RLock()
        self.session: BattleSession | None = None
        self.session_id: str | None = None
        self.steps: list[dict[str, Any]] = []
        self.results: list[tuple[Any, Any]] = []
        self.restored_operation_count = 0
        self.display_text: dict[str, str] | None = None
        self.character_choices: list[dict[str, str]] | None = None
        self.stage_choices: list[dict[str, Any]] | None = None
        self.support_catalog: dict[str, Any] | None = None

    def support(self, kind: str = '', content_id: str = '') -> dict[str, Any]:
        """Load the full source matrix on demand; reuse the running battle's IR."""
        if not isinstance(kind, str) or not isinstance(content_id, str):
            raise ValueError('内容种类与身份必须是文本。')
        with self.lock:
            if self.support_catalog is None:
                self.support_catalog = build_content_support_catalog(self.tbgd_root)
            report = content_support_matrix(
                self.support_catalog,
                rules=self.session.rules if self.session is not None else None,
                scenario=self.session.scenario if self.session is not None else None,
            )
            if kind or content_id:
                report['rows'] = [row for row in report['rows']
                                  if (not kind or row['kind'] == kind)
                                  and (not content_id or row['content_id'] == content_id)]
                report['filter'] = {'kind': kind, 'content_id': content_id,
                                    'summary_scope': 'complete directory before filtering'}
            return report

    def stages(self, query: str = '') -> dict[str, Any]:
        with self.lock:
            if not isinstance(query, str) or len(query) > 100:
                raise ValueError('关卡搜索词应为不超过 100 字的文本。')
            if self.stage_choices is None:
                if self.display_text is None:
                    self.display_text = _load_text_map(self.tbgd_root)
                self.stage_choices = list_stage_choices(self.tbgd_root, self.display_text)
            needle = query.strip().casefold()
            matches = [item for item in self.stage_choices if needle in item['stage_id']
                       or needle in item['name'].casefold()]
            return {'stages': deepcopy(matches[:100]), 'total': len(matches)}

    def configure_stage(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            data = request.get('scenario')
            if not isinstance(data, dict):
                raise ValueError('需要提供战斗配置对象。')
            scenario = ScenarioLoader().load_dict(data)
            stage_id = request.get('stage_id')
            self.stages(stage_id)
            matches = [item for item in self.stage_choices if item['stage_id'] == stage_id]
            if len(matches) != 1 or not matches[0]['wave_count']:
                raise ValueError('所选关卡没有唯一的来源波次目录项。')
            setup, timeline = scenario.battle_setup, scenario.battle_setup.timeline
            if (scenario.route or setup.initial_statuses or setup.initial_summons or setup.objective
                    or timeline and (timeline.mode != 'runtime_initialize' or timeline.turn_owner_id
                                     or timeline.action_values or timeline.explicit_overrides or timeline.global_av)):
                raise ValueError('配置含路线、预置效果、目标或自定义时间线，请先处理这些关联再替换波次。')
            stage_scope = setup.metadata.get('stage_scope')
            if stage_scope not in ('wave_only', 'full_stage'):
                raise ValueError('请明确选择 wave_only 或 full_stage 范围；完整关卡环境将在开战时校验准入。')
            draft = deepcopy(data)
            draft['units'] = [unit for unit in draft['units'] if unit['side'] != 'enemy']
            draft.pop('wave_definition_ref', None)
            draft.pop('wave_setup', None)
            draft.update(stage_ref=stage_id, wave_index=0)
            draft['battle_setup']['wave'] = {'kind': 'stage', 'stage_ref': stage_id, 'wave_index': 0}
            draft['battle_setup']['metadata']['scope'] = (
                f'仅使用关卡 {stage_id} 的敌方波次，不包含完整关卡环境。'
                if stage_scope == 'wave_only' else
                f'采用关卡 {stage_id} 的敌方波次与完整关卡环境；开战时校验环境准入。'
            )
            ScenarioLoader().load_dict(draft)
            return {'scenario': draft, 'stage': matches[0]}

    def characters(self) -> dict[str, Any]:
        with self.lock:
            if self.character_choices is None:
                self.character_choices = list_character_choices(self.tbgd_root)
            return {'characters': [{**deepcopy(item), 'support_status': 'unchecked'}
                                   for item in self.character_choices],
                    'content_support': _content_support('source_catalog', [])}

    def configure_character(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            data = request.get('scenario')
            if not isinstance(data, dict):
                raise ValueError('需要提供战斗配置对象。')
            scenario = ScenarioLoader().load_dict(data)
            operation = request.get('operation', 'replace')
            if operation not in ('replace', 'add', 'remove'):
                raise ValueError('角色操作必须为切换、新增或移除。')
            matches = [unit for unit in scenario.units if unit.unit_id == request.get('unit_id')]
            if operation != 'add' and (len(matches) != 1 or matches[0].character_build is None or matches[0].side != 'ally'):
                raise ValueError('需要唯一的正式我方角色位置。')
            if scenario.route or scenario.battle_setup.initial_statuses or scenario.battle_setup.initial_summons:
                raise ValueError('配置含预置路线、状态或召唤物，请先在 JSON 中处理这些关联，再变更队员。')
            draft = deepcopy(data)
            if operation in ('add', 'remove'):
                party = [unit for unit in scenario.units if unit.side == 'ally']
                if (not 1 <= len(party) <= 4 or any(unit.character_build is None for unit in party)
                        or len({unit.unit_id for unit in scenario.units}) != len(scenario.units)):
                    raise ValueError('队伍需要 1–4 名身份唯一的正式我方角色。')
                positions = [unit.position for unit in party]
                if any(type(position) is not int or position < 0 for position in positions) or len(set(positions)) != len(party):
                    raise ValueError('现有我方站位缺失或重复，请先修正配置。')
                if operation == 'add' and len(party) == 4:
                    raise ValueError('队伍已满，最多 4 名队员。')
                if operation == 'remove':
                    if len(party) == 1:
                        raise ValueError('队伍至少保留 1 名队员。')
                    draft['units'] = [unit for unit in draft['units'] if unit['unit_id'] != matches[0].unit_id]
                ordered = sorted((unit for unit in draft['units'] if unit['side'] == 'ally'), key=lambda unit: unit['position'])
                for position, unit in enumerate(ordered):
                    unit['position'] = position
                if operation == 'remove':
                    ScenarioLoader().load_dict(draft)
                    return {'scenario': draft}
            choices = [item for item in self.characters()['characters'] if item['entity_ref'] == request.get('entity_ref')]
            if len(choices) != 1:
                raise ValueError('角色不在当前来源目录中。')
            choice = choices[0]
            if operation == 'add':
                existing_ids = {unit.unit_id for unit in scenario.units}
                unit_id = next(f'ally_{index}' for index in range(1, len(existing_ids) + 2) if f'ally_{index}' not in existing_ids)
                position = len(party)
            else:
                unit_id, position = matches[0].unit_id, matches[0].position
            card_id = choice['character_card_id']
            build = CharacterBuildInput(
                build_id=f'{unit_id}:build', character_card_id=card_id, level=1, promotion=0,
                eidolon_level=0, unlocked_trace_node_ids=(),
                equipment_build=EquipmentBuildInput(f'{unit_id}:equipment', card_id),
            )
            configured = {
                'unit_id': unit_id, 'side': 'ally', 'entity_ref': choice['entity_ref'],
                'level': 1, 'eidolon_level': 0, 'position': position,
                'build_mode': 'assembled_character_build', 'character_build': build.to_json(),
                'initial_condition': CharacterInitialConditionInput(hp_mode='full', initial_energy='0').to_json(),
            }
            if operation == 'add':
                draft['units'].append(configured)
            else:
                index = next(index for index, item in enumerate(draft['units']) if item['unit_id'] == unit_id)
                draft['units'][index] = configured
            ScenarioLoader().load_dict(draft)
            return {'scenario': draft}

    def configure_party_order(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            data = request.get('scenario')
            if not isinstance(data, dict):
                raise ValueError('需要提供战斗配置对象。')
            scenario = ScenarioLoader().load_dict(data)
            party = [unit for unit in scenario.units if unit.side == 'ally']
            if (len(party) < 2 or any(unit.character_build is None for unit in party)
                    or len({unit.unit_id for unit in scenario.units}) != len(scenario.units)):
                raise ValueError('需要至少两名身份唯一的正式我方角色。')
            positions = [unit.position for unit in party]
            if any(type(position) is not int for position in positions) or len(set(positions)) != len(party):
                raise ValueError('现有我方站位缺失或重复，请先修正配置。')
            order = request.get('unit_ids')
            if (not isinstance(order, list) or not all(isinstance(item, str) for item in order)
                    or len(order) != len(party) or set(order) != {unit.unit_id for unit in party}):
                raise ValueError('站位顺序必须恰好包含每名现有我方角色一次。')
            assigned = dict(zip(order, sorted(positions)))
            draft = deepcopy(data)
            for unit in draft['units']:
                if unit['unit_id'] in assigned:
                    unit['position'] = assigned[unit['unit_id']]
            ScenarioLoader().load_dict(draft)
            return {'scenario': draft}

    def configure_initial_condition(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            data = request.get('scenario')
            if not isinstance(data, dict):
                raise ValueError('需要提供战斗配置对象。')
            scenario = ScenarioLoader().load_dict(data)
            matches = [unit for unit in scenario.units if unit.unit_id == request.get('unit_id')]
            if len(matches) != 1 or matches[0].character_build is None or matches[0].initial_condition is None:
                raise ValueError('需要唯一的正式角色初始条件。')
            raw = request.get('initial_condition')
            if not isinstance(raw, dict) or set(raw) != {'hp_mode', 'hp_value', 'initial_energy'}:
                raise ValueError('初始条件字段不完整或包含未知字段。')
            unit = matches[0]
            condition = CharacterInitialConditionInput.from_json({
                **raw, 'initial_resource_values': unit.initial_condition.to_json()['initial_resource_values'],
            })
            draft = deepcopy(data)
            next(row for row in draft['units'] if row['unit_id'] == unit.unit_id)['initial_condition'] = condition.to_json()
            return {'scenario': draft}

    @staticmethod
    def examples() -> dict[str, Any]:
        examples = []
        for path in sorted(EXAMPLES_ROOT.glob('*.json')):
            data = json.loads(path.read_text(encoding='utf-8'))
            if 'units' in data and 'battle_setup' in data:
                examples.append({'case_id': path.stem, 'scenario': data})
        return {'examples': examples}

    def _check(self, request: dict[str, Any]) -> BattleSession:
        if self.session is None:
            raise SessionConflict('当前没有战斗，请先开始战斗。')
        if (request.get('session_id') != self.session_id
                or type(request.get('revision')) is not int
                or request['revision'] != len(self.session.operations)):
            raise SessionConflict('战斗已更新，请刷新当前战斗后重新选择动作。')
        return self.session

    def prepare_builds(self, request: dict[str, Any], *, rules: RuleBook | None = None) -> dict[str, Any]:
        """Read-only draft assembly; no BattleSession or birth effects are created."""
        with self.lock:
            data = request.get('scenario')
            if not isinstance(data, dict):
                raise ValueError('需要提供战斗配置对象。')
            scenario = ScenarioLoader().load_dict(data)
            include_equipment = request.get('include_equipment', False)
            if type(include_equipment) is not bool:
                raise ValueError('include_equipment 必须是布尔值。')
            if rules is None:
                rules = (build_battle_rulebook(self.tbgd_root, data, include_equipment=True)
                         if include_equipment else build_battle_rulebook(self.tbgd_root, data))
            units = []
            for unit in scenario.units:
                build = unit.character_build
                if build is None:
                    continue
                card = rules.character_data_card(build.character_card_id)
                if card is None:
                    raise ValueError(f'角色卡不存在：{build.character_card_id}')
                result = assemble_character_build(rules, build)
                equipment = result.equipment_assembly_result
                traces = []
                for node in _current_card_trace_nodes(rules, card):
                    labels = []
                    for skill_id in node.level_up_skill_ids:
                        action = rules.action_definition(f'avatar_skill:{skill_id}', node.level)
                        labels.append({'Normal': '普攻', 'BPSkill': '战技', 'Ultra': '终结技', 'Talent': '天赋',
                                       'Passive': '天赋', 'Maze': '秘技'}.get(
                            action.attack_type if action else '', f'技能 {skill_id}'))
                    traces.append({
                        'trace_node_id': node.trace_node_id, 'trace_id': node.trace_id,
                        'label': ' / '.join(labels) or ('额外能力' if node.extra_effect_ids else '属性行迹'),
                        'level': node.level, 'default_unlocked': node.default_unlocked,
                        'required_promotion': node.required_promotion,
                        'required_character_level': node.required_character_level,
                        'prerequisite_trace_ids': list(node.prerequisite_trace_ids),
                        'coverage_status': node.coverage_status, 'blocked_reason': node.blocked_reason,
                    })
                units.append({
                    'unit_id': unit.unit_id, 'character_card_id': card.card_id, 'traces': traces,
                    'assembly_status': result.assembly_status, 'battle_admission_status': result.battle_admission_status,
                    'blocked_reasons': list(result.blocked_reasons),
                    'mechanism_reasons': [item.reason for item in result.unadmitted_mechanism_diagnostics]
                                        + ([item.reason_code for item in equipment.battle_admission_blockers]
                                           + [item.reason for item in equipment.diagnostics] if equipment else []),
                    'base_panel': {key: getattr(result.base_panel, key) for key in ('max_hp', 'attack', 'defense', 'speed')}
                                  if result.base_panel else None,
                    'skill_levels': [{'skill_id': item.skill_id, 'base_level': item.base_level,
                                      'eidolon_level_bonus': item.eidolon_level_bonus,
                                      'effective_level': item.effective_level} for item in result.effective_skill_levels],
                    'relic_stats': [{'slot': item.slot_key.definition_identity,
                                     'properties': [{'property_type': affix.property_type, 'value': affix.exact_value}
                                                    for affix in (item.main_affix, *item.sub_affixes)]}
                                    for item in equipment.relic_selections] if equipment else [],
                })
            response = {'units': units, 'content_support': _content_support('configured_builds', [
                {'kind': 'character_build', 'unit_id': unit['unit_id'], 'ref_id': unit['character_card_id'],
                 'status': 'supported' if unit['battle_admission_status'] == 'admitted' else 'blocked',
                 'reasons': list(dict.fromkeys([*unit['blocked_reasons'], *unit['mechanism_reasons']]))}
                for unit in units
            ])}
            if include_equipment:
                if self.display_text is None:
                    self.display_text = _load_text_map(self.tbgd_root)
                response['light_cones'] = [{
                    'definition_identity': cone.raw_equipment_id,
                    'name': self.display_text.get(cone.equipment_name_hash, cone.raw_equipment_id),
                    'path_type': cone.path_type, 'rarity': cone.rarity,
                    'coverage_status': cone.coverage_status, 'blocked_reason': cone.blocked_reason,
                } for cone in rules.ir.light_cone_definitions]
                names = load_relic_set_display_names(self.tbgd_root, self.display_text)
                response['relic_slots'] = [slot.raw_slot_type for slot in rules.ir.relic_slot_definitions]
                response['relic_templates'] = [{
                    'definition_identity': item.raw_relic_id,
                    'name': names.get(item.set_key.definition_identity, item.set_key.definition_identity),
                    'slot': item.slot_key.definition_identity, 'rarity': item.rarity,
                    'max_level': item.max_level, 'coverage_status': item.coverage_status,
                    'blocked_reason': item.blocked_reason,
                } for item in rules.ir.relic_template_definitions]
            return response

    def relic_affixes(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            data = request.get('scenario')
            if not isinstance(data, dict):
                raise ValueError('需要提供战斗配置对象。')
            ScenarioLoader().load_dict(data)
            rules = build_battle_rulebook(self.tbgd_root, data, include_equipment=True)
            view = EquipmentQueryService(rules).get_relic_template_affixes(request.get('template_identity'))
            if view.resolution_status != 'resolved':
                raise ValueError(view.blocked_reason)
            return {
                'template_identity': view.requested_identity,
                'main_affixes': [{'definition_identity': item.definition_identity,
                                  'property_type': item.snapshot['property_type']}
                                 for item in view.legal_main_affixes],
                'sub_affixes': [{'definition_identity': item.definition_identity,
                                 'property_type': item.snapshot['property_type']}
                                for item in view.legal_sub_affixes],
            }

    def configure_relic(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            data = request.get('scenario')
            if not isinstance(data, dict):
                raise ValueError('需要提供战斗配置对象。')
            scenario = ScenarioLoader().load_dict(data)
            matches = [unit for unit in scenario.units if unit.unit_id == request.get('unit_id')]
            if len(matches) != 1 or matches[0].character_build is None:
                raise ValueError('需要唯一的正式角色构筑。')
            unit = matches[0]
            build = unit.character_build
            slot = EquipmentDefinitionKey('relic_slot', request.get('slot_identity'))
            rules = build_battle_rulebook(self.tbgd_root, data, include_equipment=True)
            if rules.relic_slot_definition(slot.definition_identity).resolution_status != 'resolved':
                raise ValueError('遗器部位不存在或尚未支持。')
            previous = [item for item in build.equipment_build.relics if item.slot_key == slot]
            if len(previous) > 1:
                raise ValueError('该部位存在多个遗器，请先修正配置。')
            raw = request.get('relic')
            if 'relic' not in request or raw is not None and (
                not isinstance(raw, dict) or set(raw) != {'template_identity', 'level', 'main_affix_identity', 'sub_affixes'}
            ):
                raise ValueError('遗器选择字段不完整或包含未知字段。')
            relics = [item for item in build.equipment_build.relics if item.slot_key != slot]
            if raw is not None:
                template = rules.relic_template_definition(raw['template_identity'])
                if template.resolution_status != 'resolved' or template.value.slot_key != slot:
                    raise ValueError('遗器模板与所选部位不匹配或尚未支持。')
                if not isinstance(raw['sub_affixes'], list) or any(
                    not isinstance(item, dict) or set(item) != {'definition_identity', 'count', 'step'}
                    for item in raw['sub_affixes']
                ):
                    raise ValueError('副词条选择字段不完整或包含未知字段。')
                relics.append(RelicInstanceInput(
                    previous[0].instance_id if previous else f'{unit.unit_id}:relic:{slot.definition_identity}',
                    template.value.definition_key, slot, raw['level'],
                    EquipmentDefinitionKey('relic_main_affix', raw['main_affix_identity']),
                    tuple(RelicSubAffixRollInput(EquipmentDefinitionKey('relic_sub_affix', item['definition_identity']),
                                               item['count'], item['step']) for item in raw['sub_affixes']),
                ))
            configured = replace(build, equipment_build=replace(build.equipment_build, relics=tuple(relics)))
            draft = deepcopy(data)
            next(item for item in draft['units'] if item['unit_id'] == unit.unit_id)['character_build'] = configured.to_json()
            return {'scenario': draft, **self.prepare_builds({'scenario': draft}, rules=rules)}

    def configure_light_cone(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            data = request.get('scenario')
            if not isinstance(data, dict):
                raise ValueError('需要提供战斗配置对象。')
            scenario = ScenarioLoader().load_dict(data)
            matches = [unit for unit in scenario.units if unit.unit_id == request.get('unit_id')]
            if len(matches) != 1 or matches[0].character_build is None:
                raise ValueError('需要唯一的正式角色构筑。')
            unit = matches[0]
            build = unit.character_build
            raw = request.get('light_cone')
            if 'light_cone' not in request or raw is not None and (
                not isinstance(raw, dict) or set(raw) != {'definition_identity', 'level', 'promotion', 'superimposition'}
            ):
                raise ValueError('光锥选择字段不完整或包含未知字段。')
            previous = build.equipment_build.light_cone
            cone = None if raw is None else LightConeInstanceInput(
                instance_id=previous.instance_id if previous else f'{unit.unit_id}:light-cone',
                definition_key=EquipmentDefinitionKey('light_cone', raw['definition_identity']),
                level=raw['level'], promotion=raw['promotion'], superimposition=raw['superimposition'],
            )
            configured = replace(build, equipment_build=replace(build.equipment_build, light_cone=cone))
            draft = deepcopy(data)
            next(row for row in draft['units'] if row['unit_id'] == unit.unit_id)['character_build'] = configured.to_json()
            return {'scenario': draft, **self.prepare_builds({'scenario': draft})}

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.session is not None:
                self._check(request)
            elif request.get('session_id') is not None:
                raise SessionConflict('服务已重启，请刷新后重新开始。')
            scenario = request.get('scenario')
            if not isinstance(scenario, dict):
                raise ValueError('需要提供战斗配置对象。')
            rules = build_battle_rulebook(self.tbgd_root, scenario)
            candidate = BattleSession(rules, scenario)
            candidate.advance()
            self.session = candidate
            self.session_id = uuid4().hex
            self.steps = []
            self.results = []
            self.restored_operation_count = 0
            return self.view()

    def resume(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.session is not None:
                self._check(request)
            elif request.get('session_id') is not None:
                raise SessionConflict('服务已重启，请刷新后重新载入归档。')
            archive = decode_archive_json(_request_archive(request))
            scenario = archive.get('scenario')
            if not isinstance(scenario, dict):
                raise ValueError('归档缺少战斗配置。')
            rules = build_battle_rulebook(self.tbgd_root, scenario)
            candidate = restore_session(archive, rules)
            restored_count = len(candidate.operations)
            candidate.advance()
            self.session = candidate
            self.session_id = uuid4().hex
            self.steps = []
            self.results = []
            self.restored_operation_count = restored_count
            return self.view()

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            session = self._check(request)
            decision = session.decisions.current_decision(session.state)
            if (decision.token is None
                    or request.get('decision_id') != decision.token.decision_id):
                raise SessionConflict('决策已变化，请刷新当前战斗后重新选择。')
            command = command_from_json(request.get('command'))
            before = session.state
            result = session.submit(command)
            self.results.append((before, result))
            transition = result.transition.to_json(detach=False)
            records = settlement_records(transition)
            self.steps.append({
                'route_index': len(self.steps), 'input_command': command_to_json(command),
                'transition': transition_summary(transition),
                'transition_outcome': transition['outcome'],
                'damage_records': [{key: record.get(key) for key in (
                    'record_type', 'amount', 'final_damage', 'damage_formula_family',
                    'target_before_hp', 'target_after_hp',
                )} for record in damage_records(records)],
                'blocked_records': blocked_records(records, transition),
            })
            if result.transition.outcome.successor_eligible:
                session.advance()
            return self.view()

    def fork(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            session = self._check(request)
            index = request.get('operation_index')
            if (type(index) is not int or not 0 <= index < len(session.operations)
                    or session.operations[index]['kind'] != 'submit'):
                raise ValueError('请选择历史中的一次动作提交。')
            candidate = fork_session(session, index)
            candidate.advance()
            self.session = candidate
            self.session_id = uuid4().hex
            self.steps = []
            self.results = []
            self.restored_operation_count = index
            return self.view()

    def view(self) -> dict[str, Any]:
        with self.lock:
            if self.session is None:
                return {'session_id': None}
            session = self.session
            snapshot = session.state.snapshot().to_json(detach=False)
            decision = session.decisions.current_decision(session.state).to_json()
            if not decision['ready'] and session.operations:
                last = session.operations[-1]
                if last['kind'] == 'advance' and last.get('blocked_reason'):
                    decision['blocked_reason'] = last['blocked_reason']
            prompt = build_action_prompt(snapshot, session.scenario_data, decision)
            for slot in prompt['slots']:
                definition = session.rules.action_definition(slot['action_ref'], slot['action_level'])
                if definition and slot['choice_kind'] == 'normal_action':
                    label = {'Normal': '普攻', 'BPSkill': '战技', 'Ultra': '终结技'}.get(
                        definition.attack_type, definition.attack_type,
                    )
                    slot['display_label'] = f"{label} · {slot['action_ref']}"
            events = build_event_replay_view(self.steps)
            for event, step in zip(events, self.steps):
                event['mutation_count'] = step['transition']['mutation_count']
                event['event_count'] = step['transition']['event_count']
            checks = [
                {'kind': 'action_choice', 'unit_id': slot['actor_id'], 'ref_id': slot['action_ref'],
                 'status': 'supported' if slot['available'] else 'blocked',
                 'reasons': [slot['blocked_reason']] if slot.get('blocked_reason') else []}
                for slot in prompt['slots']
            ]
            if not prompt['available'] and not session.outcome:
                checks.append({'kind': 'decision', 'unit_id': '', 'ref_id': '', 'status': 'blocked',
                               'reasons': [prompt['reason']]})
            elif not prompt['available']:
                # The battle ended: no action choice exists, but the last submission
                # was successful. Do not report the current decision as continuable.
                checks.append({'kind': 'decision', 'unit_id': '', 'ref_id': '', 'status': 'unchecked',
                               'reasons': [f'战斗已结束：{session.outcome}']})
            if self.steps:
                last_step = self.steps[-1]
                outcome = last_step['transition_outcome']
                checks.append({
                    'kind': 'last_submission', 'unit_id': last_step['input_command']['actor_id'],
                    'ref_id': last_step['input_command']['action_id'],
                    'status': 'supported' if outcome['successor_eligible'] else 'blocked',
                    'reasons': list(outcome.get('reason_codes') or ()) if not outcome['successor_eligible'] else [],
                })
            return {
                'session_id': self.session_id, 'revision': len(session.operations),
                'scenario_id': session.scenario.scenario_id, 'scenario': session.scenario_data,
                'outcome': session.outcome, 'validation': {'ok': True},
                'restored_operation_count': self.restored_operation_count,
                'fork_choices': [{'operation_index': index, 'actor_id': operation['command']['actor_id'],
                                  'action_id': operation['command']['action_id'],
                                  'target_ids': list(operation['command']['target_ids'])}
                                 for index, operation in enumerate(session.operations) if operation['kind'] == 'submit'],
                'decision': decision,
                'content_support': _content_support('current_decision', checks),
                'battlefield_view': build_battlefield_view(snapshot, session.scenario_data),
                'action_prompt': prompt,
                'panel_source_breakdown': panel_source_breakdown(snapshot, session.scenario_data),
                'steps': list(self.steps), 'event_replay_view': events,
                'blocked_records': [r for step in self.steps for r in step['blocked_records']],
            }

    def compare_observation(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            session = self._check(request)
            unit_id, observed = request.get('unit_id'), request.get('observed')
            if not isinstance(unit_id, str) or unit_id not in session.state.units:
                raise ValueError('请选择当前战斗中的单位。')
            if (not isinstance(observed, dict) or not observed
                    or set(observed) - {'hp', 'energy', 'toughness', 'shield'}):
                raise ValueError('至少填写一项生命、能量、韧性或护盾观测值。')
            metadata = {key: request.get(key, '') for key in ('game_version', 'note')}
            if any(not isinstance(value, str) or len(value) > 1000 for value in metadata.values()):
                raise ValueError('游戏版本和备注应为不超过 1000 字的文本。')
            unit = session.state.units[unit_id].to_snapshot(detach=False)
            measurements = {}
            for field, raw in observed.items():
                if type(raw) not in (str, int, float) or len(str(raw)) > 64:
                    raise ValueError(f'{field} 观测值应为不超过 64 个字符的数字。')
                if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', str(raw).strip()):
                    raise ValueError(f'{field} 观测值不是有效数字。')
                try:
                    actual, expected = Decimal(str(raw).strip()), Decimal(str(unit[field]))
                except InvalidOperation as exc:
                    raise ValueError(f'{field} 观测值不是有效数字。') from exc
                # Bound audit input/output size; this is not a combat value cap.
                if any(not value.is_finite() or abs(value.adjusted()) > 100
                       or abs(value.as_tuple().exponent) > 100 for value in (actual, expected)) or actual < 0:
                    raise ValueError(f'{field} 需要有限、非负且指数在 ±100 内的数字。')
                with localcontext() as context:
                    context.prec = 256
                    difference = actual - expected
                measurements[field] = {'observed': str(raw).strip(), 'simulated': str(expected),
                                       'difference': format(difference, 'f')}
            return {
                'captured_at': datetime.now(timezone.utc).isoformat(),
                'session_id': self.session_id, 'revision': len(session.operations),
                'scenario_id': session.scenario.scenario_id, 'event_index': session.state.event_index,
                'rules_fingerprint': session.rules_fingerprint,
                'scenario_fingerprint': canonical_json_fingerprint(session.scenario_data),
                'operation_path_fingerprint': canonical_json_fingerprint({'operations': [
                    {'kind': operation['kind'], 'command': operation.get('command')}
                    for operation in session.operations
                ]}),
                'unit_id': unit_id, 'entity_ref': unit['template_id'],
                'measurements': measurements, **metadata,
            }

    def detail(self, request: dict[str, Any], index: int) -> dict[str, Any]:
        with self.lock:
            session = self._check(request)
            if not 0 <= index < len(self.results):
                raise ValueError('该步骤不存在。')
            before, result = self.results[index]
            return build_step_report(
                route_index=index, command=result.transition.transaction.command,
                before_state=before, after_state=result.after_state,
                transition=result.transition, child_transitions=result.child_transitions,
                rules=session.rules, scenario_data=session.scenario_data,
                include_raw_transition=False,
            )

    def download(self, request: dict[str, Any]) -> bytes:
        with self.lock:
            session = self._check(request)
            with TemporaryDirectory(prefix='hsr-ui-archive-') as directory:
                path = write_archive(Path(directory) / 'battle.json.gz', session.archive())
                return path.read_bytes()

    def replay(self, envelope: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            archive = decode_archive_json(envelope)
            scenario = archive.get('scenario')
            if not isinstance(scenario, dict):
                raise ValueError('归档缺少战斗配置。')
            rules = build_battle_rulebook(self.tbgd_root, scenario)
            return verify_archive(archive, rules)
