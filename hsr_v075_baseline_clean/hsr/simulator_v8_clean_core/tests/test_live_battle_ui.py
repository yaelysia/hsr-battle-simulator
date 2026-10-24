"""UI transport must preserve real decision templates and battle history."""
import gzip
import json
import sys
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_ui.live import LiveBattle, SessionConflict
from simulator_v8_ui.report import build_action_prompt, build_battlefield_view
from simulator_v8_ui.server import V8UIRequestHandler
from simulator_v8_clean_core.archive_json import decode_archive_json, encode_archive_json
from simulator_v8_clean_core.battle_archive import _json_equal


def test_multiple_actors_and_control_commands_remain_available():
    choices = [
        {'choice_id': 'enemy', 'actor_id': 'enemy', 'action_id': 'enemy:attack',
         'action_level': 1, 'choice_kind': 'normal_action', 'target_query': None,
         'command_template': {'actor_id': 'enemy', 'metadata': {'selection': 'original'}}},
        {'choice_id': 'ultimate', 'actor_id': 'ally', 'action_id': 'control:ultimate',
         'action_level': 1, 'choice_kind': 'manual_ultimate_request', 'target_query': None,
         'command_template': {'actor_id': 'ally', 'queue_name': 'ultimate',
                              'metadata': {'control': 'request', 'action': 'ally:ultimate'}}},
    ]
    prompt = build_action_prompt({}, {}, {'ready': True, 'availability': {'choices': choices}})
    assert prompt['available'] and len(prompt['slots']) == 2
    assert [slot['command_template'] for slot in prompt['slots']] == [c['command_template'] for c in choices]


def test_listing_and_empty_read_do_not_compile(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('listing must not compile the complete catalog')
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', forbidden)
    battle = LiveBattle(Path('unused'))
    assert battle.view() == {'session_id': None}
    assert any(item['case_id'] == 'arlan_vs_antimatter' for item in battle.examples()['examples'])
    with pytest.raises(SessionConflict):
        battle.submit({'session_id': 'lost', 'revision': 0, 'command': {}})
    with pytest.raises(SessionConflict):
        battle.resume({'session_id': 'lost', 'revision': 0, 'archive': {}})
    with pytest.raises(ValueError, match='配置对象'):
        battle.prepare_builds({})


def test_resume_accepts_exact_archive_text_and_preserves_numeric_types(monkeypatch):
    from types import SimpleNamespace

    battle = LiveBattle(Path('unused'))
    captured = {}
    candidate = SimpleNamespace(operations=[{'kind': 'advance'}], advance=lambda: None)

    def fake_restore(archive, rules):
        captured['archive'] = archive
        return candidate

    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', lambda *_: object())
    monkeypatch.setattr('simulator_v8_ui.live.restore_session', fake_restore)
    monkeypatch.setattr(battle, 'view', lambda: {'ok': True})
    archive = {'scenario': {'units': []}, 'value': 1.0, 'count': 1}
    text = json.dumps(encode_archive_json(archive), ensure_ascii=False)
    assert '1.0' in text
    with pytest.raises(ValueError, match='其中一种'):
        battle.resume({'archive': {}, 'archive_text': text})
    with pytest.raises(ValueError, match='有效 JSON'):
        battle.resume({'archive_text': '{'})
    assert battle.resume({'archive_text': text}) == {'ok': True}
    resumed = captured['archive']
    assert type(resumed['value']) is float and resumed['value'] == 1.0
    assert type(resumed['count']) is int and resumed['count'] == 1
    assert battle.restored_operation_count == 1 and battle.session is candidate
    battle.session = None
    battle.session_id = None
    assert battle.resume({'archive': json.loads(text)}) == {'ok': True}
    assert captured['archive'] == resumed


def test_full_support_inventory_is_lazy_cached_and_keeps_unknown_formal_admission(monkeypatch):
    calls = []
    catalog = {'rows': [{'kind': 'character_action', 'content_id': 'fixture:action',
        'source_checks': [{'kind': 'source_graph', 'ref_id': 'fixture:action',
                           'status': 'blocked', 'reasons': ['fixture:missing_target_context']}]}]}
    monkeypatch.setattr('simulator_v8_ui.live.build_content_support_catalog',
                        lambda root: calls.append(root) or catalog)
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook',
                        lambda *args, **kwargs: pytest.fail('support must not compile battle IR'))
    battle = LiveBattle(Path('unused'))
    battle.view()
    assert calls == []
    first = battle.support()
    row = first['rows'][0]
    assert row['known_source_gaps'] == ['fixture:missing_target_context']
    assert row['formal_status'] == 'unchecked'
    row['known_source_gaps'].clear()
    assert battle.support()['rows'][0]['known_source_gaps'] == ['fixture:missing_target_context']
    assert battle.support(kind='character')['rows'] == []
    selected = battle.support(content_id='fixture:action')
    assert len(selected['rows']) == 1 and selected['summary'] == first['summary']
    assert calls == [Path('unused')]
    assert battle.session is None


def test_view_keeps_the_automatic_advance_error_on_refresh():
    from types import SimpleNamespace
    from simulator_v8_clean_core.core.model import BattleState
    from simulator_v8_clean_core.rules.ir import CanonicalIR
    from simulator_v8_clean_core.rules.rulebook import RuleBook

    pending = {'ready': False, 'blocked_reason': 'operation_not_allowed_in_phase:query_decision:idle',
               'availability': {'choices': []}}
    battle = LiveBattle(Path('unused'))
    battle.session = SimpleNamespace(
        state=BattleState(), rules=RuleBook(CanonicalIR('fixture:blocked-view')),
        scenario=SimpleNamespace(scenario_id='fixture:blocked-view'), scenario_data={'units': []}, outcome='',
        decisions=SimpleNamespace(current_decision=lambda state: SimpleNamespace(to_json=lambda: dict(pending))),
        operations=[{'kind': 'advance', 'blocked_reason': 'fixture:expiry_callback_blocked'}],
    )
    for _ in range(2):
        view = battle.view()
        assert view['decision']['blocked_reason'] == 'fixture:expiry_callback_blocked'
        assert not view['action_prompt']['available']
        assert view['content_support']['scope'] == 'current_decision'
        assert view['content_support']['status'] == 'blocked'
        assert view['content_support']['blocked_reasons'] == ['fixture:expiry_callback_blocked']
    assert pending['blocked_reason'].startswith('operation_not_allowed_in_phase:')


def test_view_marks_ended_battle_as_no_pending_choice():
    from types import SimpleNamespace
    from simulator_v8_clean_core.core.model import BattleState
    from simulator_v8_clean_core.rules.ir import CanonicalIR
    from simulator_v8_clean_core.rules.rulebook import RuleBook

    pending = {'ready': False, 'blocked_reason': 'operation_not_allowed_in_phase:query_decision:ended',
               'availability': {'choices': []}}
    battle = LiveBattle(Path('unused'))
    battle.session = SimpleNamespace(
        state=BattleState(), rules=RuleBook(CanonicalIR('fixture:ended-view')),
        scenario=SimpleNamespace(scenario_id='fixture:ended-view'), scenario_data={'units': []},
        outcome='victory', operations=[],
        decisions=SimpleNamespace(current_decision=lambda state: SimpleNamespace(to_json=lambda: dict(pending))),
    )
    battle.steps = [{
        'route_index': 0, 'input_command': {'actor_id': 'ally', 'action_id': 'fixture:attack'},
        'transition': {'mutation_count': 0, 'event_count': 0},
        'transition_outcome': {'successor_eligible': True, 'reason_codes': []},
        'damage_records': [], 'blocked_records': [],
    }]
    view = battle.view()
    assert view['content_support']['status'] == 'unchecked'
    decision = next(check for check in view['content_support']['checks'] if check['kind'] == 'decision')
    assert decision['status'] == 'unchecked' and '战斗已结束' in decision['reasons'][0]


def test_support_summary_keeps_build_admission_separate_from_action_execution(monkeypatch):
    from types import SimpleNamespace

    battle = LiveBattle(Path('unused'))
    scenario = deepcopy(next(item['scenario'] for item in battle.examples()['examples']
                             if item['case_id'] == 'arlan_vs_antimatter'))
    assembly = SimpleNamespace(
        equipment_assembly_result=None, assembly_status='assembled', battle_admission_status='admitted',
        blocked_reasons=(), unadmitted_mechanism_diagnostics=(), base_panel=None, effective_skill_levels=(),
    )
    monkeypatch.setattr('simulator_v8_ui.live.assemble_character_build', lambda *_: assembly)
    monkeypatch.setattr('simulator_v8_ui.live._current_card_trace_nodes', lambda *_: ())
    rules = SimpleNamespace(character_data_card=lambda card_id: SimpleNamespace(card_id=card_id))
    preview = battle.prepare_builds({'scenario': scenario}, rules=rules)['content_support']
    assert preview['scope'] == 'configured_builds' and preview['status'] == 'supported'
    assert [item['kind'] for item in preview['checks']] == ['character_build']
    assembly.battle_admission_status = 'blocked'
    assembly.unadmitted_mechanism_diagnostics = (SimpleNamespace(reason='fixture:missing_mechanism'),)
    blocked = battle.prepare_builds({'scenario': scenario}, rules=rules)['content_support']
    assert blocked['status'] == 'blocked'
    assert blocked['blocked_reasons'] == ['fixture:missing_mechanism']
    assert preview['status'] == 'supported' and battle.session is None


def test_case_save_failure_keeps_existing_json_and_cleans_temporary(tmp_path, monkeypatch):
    from simulator_v8_ui.server import _write_json

    path = tmp_path / 'saved.scenario.json'
    _write_json(path, {'name': '旧配置'})
    before = path.read_bytes()
    with pytest.raises(TypeError):
        _write_json(path, {'invalid': object()})
    with pytest.raises(ValueError):
        _write_json(path, {'invalid': float('nan')})
    assert path.read_bytes() == before
    def fail_replace(*_args):
        raise OSError('interrupted before publish')
    with monkeypatch.context() as scoped:
        scoped.setattr('simulator_v8_ui.server.os.replace', fail_replace)
        with pytest.raises(OSError, match='interrupted'):
            _write_json(path, {'name': '未完成配置'})
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]
    _write_json(path, {'name': '新配置'})
    assert json.loads(path.read_text()) == {'name': '新配置'}


@pytest.mark.integration
def test_build_preview_uses_formal_trace_selection_without_replacing_battle(monkeypatch):
    from simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

    root = Path(__file__).resolve().parents[4]
    battle = LiveBattle(root / 'turnbasedgamedata-main')
    scenario = deepcopy(next(item['scenario'] for item in battle.examples()['examples']
                             if item['case_id'] == 'arlan_vs_antimatter'))
    unit = next(unit for unit in scenario['units'] if unit.get('character_build'))
    unit['level'] = 80
    unit['character_build'].update(level=80, promotion=6)
    unit['character_build'].pop('input_fingerprint', None)
    rules = build_battle_rulebook(battle.tbgd_root, scenario)
    # Same source scope for every selection; reuse this one real rulebook.
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', lambda *_: rules)
    unchanged = object()
    battle.session = unchanged  # A read-only preview must not inspect or replace an active session.
    baseline = battle.prepare_builds({'scenario': scenario})['units'][0]
    assert baseline['battle_admission_status'] == 'admitted'
    trace = next(node for node in baseline['traces'] if node['label'] == '战技' and node['level'] == 2)
    unit['character_build']['unlocked_trace_node_ids'] = [trace['trace_node_id']]
    upgraded = battle.prepare_builds({'scenario': scenario})['units'][0]
    assert upgraded['battle_admission_status'] == 'admitted'
    before = {skill['skill_id']: skill['base_level'] for skill in baseline['skill_levels']}
    changed = [skill for skill in upgraded['skill_levels'] if skill['base_level'] != before[skill['skill_id']]]
    assert len(changed) == 1 and changed[0]['base_level'] == 2
    unit['character_build']['unlocked_trace_node_ids'].append('unknown:trace')
    rejected = battle.prepare_builds({'scenario': scenario})['units'][0]
    assert rejected['assembly_status'] == 'blocked'
    assert 'unknown_trace_node:unknown:trace' in rejected['blocked_reasons']
    assert battle.session is unchanged and battle.session_id is None and not battle.steps


def test_character_catalog_and_switch_do_not_compile_or_carry_old_build(monkeypatch):
    from simulator_v8_clean_core.scenarios.loader import ScenarioLoader

    def forbidden(*args, **kwargs):
        pytest.fail('character discovery and draft selection must not compile battle graphs')
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', forbidden)
    root = Path(__file__).resolve().parents[4]
    battle = LiveBattle(root / 'turnbasedgamedata-main')
    choices = battle.characters()['characters']
    assert len(choices) == 92 and len({item['entity_ref'] for item in choices}) == 92
    assert all(item['coverage_status'] == 'discovered_only' for item in choices)
    assert all(item['support_status'] == 'unchecked' for item in choices)
    assert battle.characters()['content_support'] == {
        'scope': 'source_catalog', 'status': 'unchecked', 'checks': [], 'blocked_reasons': [],
    }
    selected = next(item for item in choices if item['entity_ref'] == 'avatar:1103')
    assert selected['name'] == '希露瓦'
    choices.clear()
    assert len(battle.characters()['characters']) == 92
    scenario = deepcopy(next(item['scenario'] for item in battle.examples()['examples']
                             if item['case_id'] == 'arlan_fleet_vs_antimatter'))
    original = deepcopy(scenario)
    sentinel = object()
    battle.session = sentinel
    request = {'scenario': scenario, 'unit_id': 'arlan', 'entity_ref': selected['entity_ref']}
    draft = battle.configure_character(request)['scenario']
    unit = ScenarioLoader().load_dict(draft).units[0]
    assert unit.entity_ref == 'avatar:1103' and unit.unit_id == 'arlan' and unit.position == 0
    assert unit.character_build.character_card_id == selected['character_card_id']
    assert unit.character_build.equipment_build.relics == ()
    assert not unit.character_build.unlocked_trace_node_ids
    assert draft['battle_setup'] == original['battle_setup'] and draft['stage_ref'] == original['stage_ref']
    assert scenario == original and battle.session is sentinel and not battle.steps
    for invalid in ('unknown', None, 1103):
        with pytest.raises(ValueError, match='目录'):
            battle.configure_character({**request, 'entity_ref': invalid})
    with pytest.raises(ValueError, match='角色位置'):
        battle.configure_character({**request, 'unit_id': 'unknown'})


def test_party_members_use_fresh_builds_and_preserve_running_session(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('editing party membership must not compile battle graphs')
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', forbidden)
    battle = LiveBattle(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main')
    scenario = next(item['scenario'] for item in battle.examples()['examples']
                    if item['case_id'] == 'arlan_fleet_vs_antimatter')
    scenario['units'][0]['unit_id'] = 'ally_1'
    original = deepcopy(scenario)
    sentinel = object()
    battle.session = sentinel
    for entity_ref in ('avatar:1103', 'avatar:1105', 'avatar:1001'):
        scenario = battle.configure_character({'scenario': scenario, 'operation': 'add', 'entity_ref': entity_ref})['scenario']
        added = scenario['units'][-1]
        assert added['level'] == 1 and added['eidolon_level'] == 0
        assert added['character_build']['unlocked_trace_node_ids'] == []
        assert added['character_build']['equipment_build']['relics'] == []
        assert added['initial_condition']['hp_mode'] == 'full'
    assert scenario['units'][0] == original['units'][0]
    assert [unit['unit_id'] for unit in scenario['units']] == ['ally_1', 'ally_2', 'ally_3', 'ally_4']
    assert [unit['position'] for unit in scenario['units']] == [0, 1, 2, 3]
    full = deepcopy(scenario)
    with pytest.raises(ValueError, match='最多 4'):
        battle.configure_character({'scenario': scenario, 'operation': 'add', 'entity_ref': 'avatar:1103'})
    for unit_id in ('ally_2', 'ally_1', 'ally_4'):
        scenario = battle.configure_character({'scenario': scenario, 'operation': 'remove', 'unit_id': unit_id})['scenario']
        assert [unit['position'] for unit in scenario['units']] == list(range(len(scenario['units'])))
    assert full['units'][2]['character_build'] == scenario['units'][0]['character_build']
    assert full['battle_setup'] == scenario['battle_setup'] == original['battle_setup']
    with pytest.raises(ValueError, match='至少保留 1'):
        battle.configure_character({'scenario': scenario, 'operation': 'remove', 'unit_id': 'ally_3'})
    linked = deepcopy(scenario)
    linked['route'] = [{'actor_id': 'ally_3', 'action_ref': 'avatar_skill:110501', 'action_level': 1, 'target_ids': []}]
    with pytest.raises(ValueError, match='预置路线'):
        battle.configure_character({'scenario': linked, 'operation': 'add', 'entity_ref': 'avatar:1103'})
    invalid = deepcopy(full)
    invalid['units'][1]['position'] = 0
    with pytest.raises(ValueError, match='站位'):
        battle.configure_character({'scenario': invalid, 'operation': 'remove', 'unit_id': 'ally_2'})
    assert battle.session is sentinel and not battle.steps
    assert [unit['position'] for unit in full['units']] == [0, 1, 2, 3]


def test_party_order_preserves_builds_and_rejects_incomplete_positions(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('changing existing positions must not compile battle graphs')
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', forbidden)
    battle = LiveBattle(Path('unused'))
    scenario = next(item['scenario'] for item in battle.examples()['examples']
                    if item['case_id'] == 'arlan_serval_natasha_vs_antimatter')
    original = deepcopy(scenario)
    sentinel = object()
    battle.session = sentinel
    order = ['serval', 'natasha', 'arlan']
    request = {'scenario': scenario, 'unit_ids': order}
    draft = battle.configure_party_order(request)['scenario']
    assert {unit['unit_id']: unit['position'] for unit in draft['units']} == dict(zip(order, (0, 1, 2)))
    # Unit identities, construction order and every non-position field remain intact.
    restored = deepcopy(draft)
    for changed, old in zip(restored['units'], original['units']):
        changed['position'] = old['position']
    assert restored == original and scenario == original and battle.session is sentinel
    for invalid in (None, True, 'arlan', [], order[:2], order + ['extra'],
                    ['arlan', 'arlan', 'natasha'], ['arlan', 'enemy', 'natasha'],
                    ['arlan', True, 'natasha'], ['arlan', {}, 'natasha']):
        with pytest.raises(ValueError, match='恰好'):
            battle.configure_party_order({**request, 'unit_ids': invalid})
    for position in (None, 1, True):
        invalid = deepcopy(scenario)
        invalid['units'][0]['position'] = position
        with pytest.raises((ValueError, TypeError)):
            battle.configure_party_order({**request, 'scenario': invalid})
    invalid = deepcopy(scenario)
    invalid['units'][0]['unit_id'] = invalid['units'][1]['unit_id']
    with pytest.raises(ValueError, match='身份唯一'):
        battle.configure_party_order({**request, 'scenario': invalid})
    assert battle.session is sentinel and not battle.steps and scenario == original
    battlefield = build_battlefield_view({'units': {
        'late': {'side': 'ally', 'position': 2}, 'early': {'side': 'ally', 'position': 0},
    }}, {'units': [{'unit_id': 'early', 'side': 'ally', 'position': 3}]})
    assert [(unit['unit_id'], unit['position']) for unit in battlefield['ally_units']] == [('early', 0), ('late', 2)]


@pytest.mark.integration
def test_real_pela_skill_uses_declared_accumulator_and_toughness():
    battle = LiveBattle(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main')
    scenario = next(item['scenario'] for item in battle.examples()['examples']
                    if item['case_id'] == 'arlan_natasha_vs_antimatter')
    scenario = battle.configure_character({'scenario': scenario, 'unit_id': 'natasha',
                                           'entity_ref': 'avatar:1106'})['scenario']
    view = battle.start({'scenario': scenario})
    assert view['decision']['ready']
    before = battle.session.state.snapshot().to_json()
    choice = next(choice for choice in view['decision']['availability']['choices']
                  if choice['action_id'] == 'avatar_skill:110602')
    view = battle.submit({
        'session_id': view['session_id'], 'revision': view['revision'],
        'decision_id': view['decision']['token']['decision_id'],
        'command': {**choice['command_template'], 'target_ids': [choice['target_query']['candidate_ids'][0]]},
    })
    outcome = view['steps'][-1]['transition_outcome']
    assert outcome['successor_eligible'], outcome['reason_codes']
    assert battle.session.state.skill_points == before['skill_points'] - 1
    assert battle.session.state.units['natasha'].energy > before['units']['natasha']['energy']
    target_id = choice['target_query']['candidate_ids'][0]
    assert battle.session.state.units[target_id].hp < before['units'][target_id]['hp']


@pytest.mark.integration
def test_group_ultimate_targets_trigger_talent_and_ordinary_attack_consumes_it():
    battle = LiveBattle(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main')
    scenario = next(item['scenario'] for item in battle.examples()['examples']
                    if item['case_id'] == 'arlan_natasha_vs_antimatter')
    scenario = battle.configure_character({'scenario': scenario, 'unit_id': 'arlan',
                                           'entity_ref': 'avatar:1002'})['scenario']
    next(unit for unit in scenario['units'] if unit['unit_id'] == 'natasha')['initial_condition']['initial_energy'] = '90'
    view = battle.start({'scenario': scenario})
    enhanced = False
    priority = {'ultimate_window': 0, 'manual_ultimate_request': 1, 'queued_action': 2, 'timeline_actor': 3}
    for _ in range(12):
        decision = view['decision']
        assert decision['ready'], decision['blocked_reason']
        choices = decision['availability']['choices']
        choice = min((choice for choice in choices if choice['choice_kind'] in priority
                      or choice['choice_kind'] == 'normal_action' and choice['action_id'] == 'avatar_skill:100201'),
                     key=lambda choice: priority.get(choice['choice_kind'], 4))
        query = choice.get('target_query') or {}
        targets = query['candidate_ids'][:1] if query.get('selection_mode') == 'explicit' else []
        view = battle.submit({
            'session_id': view['session_id'], 'revision': view['revision'],
            'decision_id': decision['token']['decision_id'],
            'command': {**choice['command_template'], 'target_ids': targets},
        })
        outcome = view['steps'][-1]['transition_outcome']
        assert outcome['successor_eligible'], outcome['reason_codes']
        names = {detail['modifier_name'] for detail in battle.session.state.units['arlan'].flags['status_details']}
        if 'MAvatar_DanHeng_00_Passive_SelfBeingTargetEnhance' in names:
            enhanced = True
        if choice['action_id'] == 'avatar_skill:100201':
            assert enhanced, 'The automatic group heal must notify every accepted ally target.'
            assert 'MAvatar_DanHeng_00_Passive_SelfBeingTargetEnhance' not in names
            assert 'MAvatar_DanHeng_00_Passive_BeginTargetEnhanceCD' in names
            break
    else:
        pytest.fail('The selected battle never reached the ordinary attack.')


@pytest.mark.integration
def test_selected_character_uses_its_own_formal_actions_and_archive(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[4]
    battle = LiveBattle(root / 'turnbasedgamedata-main')
    scenario = deepcopy(next(item['scenario'] for item in battle.examples()['examples']
                             if item['case_id'] == 'arlan_vs_antimatter'))
    scenario = battle.configure_character({'scenario': scenario, 'unit_id': 'arlan',
                                           'entity_ref': 'avatar:1103'})['scenario']
    # A deliberately strong configured character shortens the transport check;
    # damage and legal actions still come from the selected source card.
    unit = scenario['units'][0]
    unit['level'] = 80
    unit['character_build'].update(level=80, promotion=6)
    unit['character_build'].pop('input_fingerprint')
    scenario = battle.configure_initial_condition({
        'scenario': scenario, 'unit_id': 'arlan',
        'initial_condition': {'hp_mode': 'ratio', 'hp_value': '0.5', 'initial_energy': '30'},
    })['scenario']
    view = battle.start({'scenario': scenario})
    actor = battle.session.state.units['arlan']
    assert actor.hp == actor.max_hp * 0.5 and actor.energy == 30
    original_session = battle.session
    with monkeypatch.context() as patch:
        patch.setattr('simulator_v8_ui.live.build_battle_rulebook', lambda *_args: original_session.rules)
        for condition in (
            {'hp_mode': 'absolute', 'hp_value': str(actor.max_hp + 1), 'initial_energy': '0'},
            {'hp_mode': 'full', 'initial_energy': str(actor.max_energy + 1)},
            {'hp_mode': 'ratio', 'hp_value': '1e-400', 'initial_energy': '0'},
            {'hp_mode': 'full', 'initial_energy': '1e-400'},
        ):
            invalid = deepcopy(scenario)
            invalid['units'][0]['initial_condition'] = condition
            with pytest.raises(ValueError, match='initial (HP|energy)'):
                battle.start({'scenario': invalid, **{key: view[key] for key in ('session_id', 'revision')}})
            assert battle.session is original_session and battle.session_id == view['session_id']
    used = []
    for _ in range(12):
        if view['outcome']:
            break
        assert view['decision']['ready'], view['decision']['blocked_reason']
        choices = view['decision']['availability']['choices']
        selected = ([choice for choice in choices if choice['choice_kind'] == 'ultimate_window']
                    or [choice for choice in choices if choice['choice_kind'] == 'manual_ultimate_request']
                    or [choice for choice in choices if choice['choice_kind'] == 'timeline_actor'
                        or choice['choice_kind'] == 'normal_action' and (
                            choice['actor_side'] == 'enemy' or choice['action_id'] == 'avatar_skill:110302')])
        choice = selected[0]
        used.append(choice['action_id'])
        query = choice['target_query']
        targets = [query['candidate_ids'][0]] if query and query['selection_mode'] == 'explicit' else []
        view = battle.submit({
            'session_id': view['session_id'], 'revision': view['revision'],
            'decision_id': view['decision']['token']['decision_id'],
            'command': {**choice['command_template'], 'target_ids': targets},
        })
        assert view['steps'][-1]['transition_outcome']['successor_eligible']
    assert view['outcome'] == 'victory'
    assert 'avatar_skill:110302' in used and all(not action.startswith('avatar_skill:1008') for action in used)
    archive = tmp_path / 'selected-character-battle.json.gz'
    archive.write_bytes(battle.download({key: view[key] for key in ('session_id', 'revision')}))
    print(f'archive: {archive}')

    original = battle.session
    original_snapshot = original.state.snapshot().to_json(detach=False)
    identity = {key: view[key] for key in ('session_id', 'revision')}
    cutoff = view['fork_choices'][0]['operation_index']
    for invalid in (True, -1, len(original.operations), 0):
        with pytest.raises(ValueError, match='历史'):
            battle.fork({**identity, 'operation_index': invalid})
        assert battle.session is original
    saved_decision = original.operations[0]['decision_id']
    original.operations[0]['decision_id'] = 'tampered'
    with pytest.raises(ValueError, match=r'operation\[0\]_mismatch'):
        battle.fork({**identity, 'operation_index': cutoff})
    assert battle.session is original and battle.session_id == identity['session_id']
    original.operations[0]['decision_id'] = saved_decision
    view = battle.fork({**identity, 'operation_index': cutoff})
    assert battle.session is not original and view['session_id'] != identity['session_id']
    assert view['restored_operation_count'] == cutoff and view['outcome'] == ''
    assert not view['steps'] and not view['fork_choices']
    assert _json_equal(original.state.snapshot().to_json(detach=False), original_snapshot)
    # The branch changes the first input from skill to basic, then finishes normally.
    for index in range(12):
        if view['outcome']:
            break
        assert view['decision']['ready'], view['decision']['blocked_reason']
        choices = view['decision']['availability']['choices']
        action = 'avatar_skill:110301' if index == 0 else 'avatar_skill:110302'
        selected = ([choice for choice in choices if choice['choice_kind'] == 'ultimate_window']
                    or [choice for choice in choices if choice['choice_kind'] == 'manual_ultimate_request']
                    or [choice for choice in choices if choice['choice_kind'] == 'timeline_actor'
                        or choice['choice_kind'] == 'normal_action' and (
                            choice['actor_side'] == 'enemy' or choice['action_id'] == action)])
        choice = selected[0]
        if index == 0:
            assert choice['action_id'] == 'avatar_skill:110301'
        query = choice['target_query']
        targets = [query['candidate_ids'][0]] if query and query['selection_mode'] == 'explicit' else []
        view = battle.submit({
            'session_id': view['session_id'], 'revision': view['revision'],
            'decision_id': view['decision']['token']['decision_id'],
            'command': {**choice['command_template'], 'target_ids': targets},
        })
        assert view['steps'][-1]['transition_outcome']['successor_eligible']
    assert view['outcome'] == 'victory'
    assert _json_equal(original.state.snapshot().to_json(detach=False), original_snapshot)
    branch_archive = tmp_path / 'selected-character-branch.json.gz'
    branch_archive.write_bytes(battle.download({key: view[key] for key in ('session_id', 'revision')}))
    print(f'branch archive: {branch_archive}')


def test_stage_catalog_and_switch_preserve_party_without_compiling(monkeypatch):
    from simulator_v8_clean_core.scenarios.loader import ScenarioLoader

    def forbidden(*_args, **_kwargs):
        pytest.fail('stage discovery and selection must not compile battle graphs')
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', forbidden)
    battle = LiveBattle(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main')
    catalog = battle.stages()
    assert catalog['total'] == 28380 and len(catalog['stages']) == 100
    choice = battle.stages('201010110')['stages'][0]
    assert choice['wave_count'] == 2 and choice['coverage_status'] == 'discovered_only'
    choice['name'] = 'caller mutation'
    assert battle.stages('201010110')['stages'][0]['name'] != 'caller mutation'
    assert not battle.stages('no-such-stage')['stages']
    scenario = deepcopy(next(item['scenario'] for item in battle.examples()['examples']
                             if item['case_id'] == 'arlan_fleet_vs_antimatter'))
    party = deepcopy(scenario['units'])
    scenario['units'].append({'unit_id': 'old-enemy', 'side': 'enemy', 'entity_ref': 'monster:8011010',
                              'build_mode': 'kernel_fixture'})
    original = deepcopy(scenario)
    sentinel = object()
    battle.session = sentinel
    request = {'scenario': scenario, 'stage_id': '201010110'}
    draft = battle.configure_stage(request)['scenario']
    assert draft['units'] == party and scenario == original
    assert draft['stage_ref'] == '201010110' and draft['wave_index'] == 0
    assert draft['battle_setup']['metadata']['stage_scope'] == 'wave_only'
    assert '不包含完整关卡环境' in draft['battle_setup']['metadata']['scope']
    assert ScenarioLoader().load_dict(draft).stage_ref == '201010110'
    assert battle.session is sentinel and battle.session_id is None
    full = deepcopy(scenario)
    full['battle_setup']['metadata']['stage_scope'] = 'full_stage'
    full_before = deepcopy(full)
    complete = battle.configure_stage({'scenario': full, 'stage_id': '301008'})['scenario']
    assert complete['units'] == party and full == full_before
    assert complete['stage_ref'] == '301008' and complete['battle_setup']['wave']['stage_ref'] == '301008'
    assert complete['battle_setup']['metadata']['stage_scope'] == 'full_stage'
    assert '完整关卡环境；开战时校验环境准入' in complete['battle_setup']['metadata']['scope']
    assert battle.session is sentinel
    for scope in (None, 'unknown'):
        full['battle_setup']['metadata']['stage_scope'] = scope
        with pytest.raises(ValueError, match='wave_only 或 full_stage'):
            battle.configure_stage({'scenario': full, 'stage_id': '301008'})
    for bad in ('unknown', None, True, 201010110):
        with pytest.raises(ValueError):
            battle.configure_stage({**request, 'stage_id': bad})
    scenario['battle_setup']['timeline']['turn_owner_id'] = 'old-enemy'
    with pytest.raises(ValueError, match='关联'):
        battle.configure_stage(request)
    assert battle.session is sentinel and scenario['units'] == original['units']


@pytest.mark.integration
def test_selected_stage_runs_source_waves_and_saves_archive(tmp_path):
    from simulator_v8_clean_core.systems.unit_relation import EntityRelationResolver, TargetEvaluationContext

    battle = LiveBattle(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main')
    scenario = deepcopy(next(item['scenario'] for item in battle.examples()['examples']
                             if item['case_id'] == 'arlan_serval_natasha_vs_antimatter'))
    for unit in scenario['units']:
        unit['level'] = 80
        unit['character_build'].update(level=80, promotion=6)
        unit['character_build'].pop('input_fingerprint', None)
    scenario = battle.configure_stage({'scenario': scenario, 'stage_id': '201010110'})['scenario']
    order = ['serval', 'natasha', 'arlan']
    scenario = battle.configure_party_order({'scenario': scenario, 'unit_ids': order})['scenario']
    view = battle.start({'scenario': scenario})
    assert {uid: battle.session.state.units[uid].flags['position'] for uid in order} == dict(zip(order, (0, 1, 2)))
    assert [unit['unit_id'] for unit in view['battlefield_view']['ally_units']] == order
    adjacent = EntityRelationResolver().resolve(
        battle.session.state, 'formation.adjacent', TargetEvaluationContext('natasha'), subject_ids=('natasha',),
    )
    assert not adjacent.blocked_reason and adjacent.target_ids == ('serval', 'arlan')
    before_observation = battle.session.state
    observed = battle.compare_observation({
        **{key: view[key] for key in ('session_id', 'revision')}, 'unit_id': 'arlan',
        'observed': {'hp': str(before_observation.units['arlan'].hp)},
        'note': 'API integration check; not an in-game observation',
    })
    assert float(observed['measurements']['hp']['difference']) == 0
    assert battle.session.state is before_observation and len(battle.session.operations) == view['revision']
    waves = set()
    for _ in range(16):
        waves.add(battle.session.state.wave_index)
        if view['outcome']:
            break
        assert view['decision']['ready'], view['decision']['blocked_reason']
        choices = view['decision']['availability']['choices']
        selected = ([c for c in choices if c['choice_kind'] == 'ultimate_window']
                    or [c for c in choices if c['choice_kind'] == 'manual_ultimate_request' and c['actor_id'] == 'arlan']
                    or [c for c in choices if c['choice_kind'] == 'timeline_actor'
                        or c['choice_kind'] == 'normal_action' and (
                            c['actor_side'] == 'enemy' or c['action_id'] in {'avatar_skill:100802', 'avatar_skill:110302'})]
                    or [c for c in choices if c['action_id'] == 'avatar_skill:110501'])
        choice = selected[0]
        query = choice['target_query']
        # The external route avoids the separately tracked gunner snapshot gap.
        targets = sorted(query['candidate_ids'], key=lambda uid:
                         battle.session.state.units[uid].template_id != 'monster:1002050')[:1] \
                  if query and query['selection_mode'] == 'explicit' else []
        view = battle.submit({
            'session_id': view['session_id'], 'revision': view['revision'],
            'decision_id': view['decision']['token']['decision_id'],
            'command': {**choice['command_template'], 'target_ids': targets},
        })
        assert view['steps'][-1]['transition_outcome']['successor_eligible']
    assert waves == {0, 1} and view['outcome'] == 'victory'
    enemies = [unit for unit in battle.session.state.units.values() if unit.side == 'enemy']
    assert len(enemies) == 5 and all(unit.unit_id.startswith('enemy:stage:201010110:') for unit in enemies)
    archive = tmp_path / 'selected-stage-battle.json.gz'
    archive.write_bytes(battle.download({key: view[key] for key in ('session_id', 'revision')}))
    final_state = battle.session.state
    final_observed = battle.compare_observation({
        **{key: view[key] for key in ('session_id', 'revision')}, 'unit_id': enemies[0].unit_id,
        'observed': {'hp': '0'}, 'note': 'API integration check; not an in-game observation',
    })
    assert float(final_observed['measurements']['hp']['difference']) == 0
    assert battle.session.state is final_state and len(battle.session.operations) == view['revision']
    (tmp_path / 'observations.json').write_text(json.dumps({'comparisons': [observed, final_observed]}))
    print(f'archive: {archive}')


@pytest.mark.integration
def test_equipment_forms_preserve_build_and_replay_battle(monkeypatch, tmp_path):
    from simulator_v8_clean_core.scenarios.loader import ScenarioLoader
    from simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

    root = Path(__file__).resolve().parents[4]
    battle = LiveBattle(root / 'turnbasedgamedata-main')
    examples = {item['case_id']: item['scenario'] for item in battle.examples()['examples']}
    rules = build_battle_rulebook(battle.tbgd_root, examples['arlan_vs_antimatter'], include_equipment=True)
    assert len(rules.ir.character_data_cards) == 1 and rules.ir.light_cone_definitions
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', lambda *_, **__: rules)
    scenario = examples['arlan_fleet_vs_antimatter']
    original = deepcopy(scenario)
    options = battle.prepare_builds({'scenario': scenario, 'include_equipment': True})
    choice = next(item for item in options['light_cones'] if item['definition_identity'] == '20002')
    assert choice['path_type'] == 'Warrior' and choice['name'] != '20002'
    request = {'scenario': scenario, 'unit_id': 'arlan', 'light_cone': {
        'definition_identity': choice['definition_identity'], 'level': 1, 'promotion': 0, 'superimposition': 1,
    }}
    response = battle.configure_light_cone(request)
    assert response['units'][0]['battle_admission_status'] == 'admitted', response['units'][0]['mechanism_reasons']
    assert float(response['units'][0]['base_panel']['attack']) > float(options['units'][0]['base_panel']['attack'])
    configured = ScenarioLoader().load_dict(response['scenario']).units[0].character_build
    previous = ScenarioLoader().load_dict(scenario).units[0].character_build
    assert configured.equipment_build.light_cone.definition_key.definition_identity == '20002'
    assert configured.equipment_build.relics == previous.equipment_build.relics
    assert configured.input_fingerprint != previous.input_fingerprint
    removed = battle.configure_light_cone({**request, 'scenario': response['scenario'], 'light_cone': None})
    assert ScenarioLoader().load_dict(removed['scenario']).units[0].character_build == previous
    for invalid in ({**request['light_cone'], 'level': True}, {**request['light_cone'], 'unknown': 1}):
        with pytest.raises((TypeError, ValueError)):
            battle.configure_light_cone({**request, 'light_cone': invalid})
    assert scenario == original and battle.session is None and not battle.steps
    # Select real template affixes, edit one finished relic, preserve the other slots and cone.
    template = next(item for item in options['relic_templates'] if item['definition_identity'] == '61014')
    assert template['slot'] == 'FOOT' and template['name'] != '101'
    affixes = battle.relic_affixes({'scenario': response['scenario'], 'template_identity': '61014'})
    main = next(item for item in affixes['main_affixes'] if item['property_type'] == 'SpeedDelta')
    sub = next(item for item in affixes['sub_affixes'] if item['property_type'] == 'AttackDelta')
    relic_request = {'scenario': response['scenario'], 'unit_id': 'arlan', 'slot_identity': 'FOOT', 'relic': {
        'template_identity': '61014', 'level': 15, 'main_affix_identity': main['definition_identity'],
        'sub_affixes': [{'definition_identity': sub['definition_identity'], 'count': 2, 'step': 1}],
    }}
    response = battle.configure_relic(relic_request)
    assert response['units'][0]['battle_admission_status'] == 'admitted', response['units'][0]['mechanism_reasons']
    edited = ScenarioLoader().load_dict(response['scenario']).units[0].character_build
    assert edited.equipment_build.light_cone == configured.equipment_build.light_cone
    assert edited.unlocked_trace_node_ids == configured.unlocked_trace_node_ids
    assert [item for item in edited.equipment_build.relics if item.slot_key.definition_identity != 'FOOT'] == [
        item for item in configured.equipment_build.relics if item.slot_key.definition_identity != 'FOOT']
    edited_foot = next(item for item in edited.equipment_build.relics if item.slot_key.definition_identity == 'FOOT')
    assert edited_foot.instance_id == next(item for item in configured.equipment_build.relics if item.slot_key.definition_identity == 'FOOT').instance_id
    assert edited.input_fingerprint != configured.input_fingerprint
    assert any(prop['property_type'] == 'AttackDelta' and float(prop['value']) > 0
               for item in response['units'][0]['relic_stats'] for prop in item['properties'])
    duplicate = battle.configure_relic({**relic_request, 'relic': {
        **relic_request['relic'], 'sub_affixes': relic_request['relic']['sub_affixes'] * 2,
    }})
    assert duplicate['units'][0]['assembly_status'] == 'blocked'
    assert any('duplicate' in reason for reason in duplicate['units'][0]['mechanism_reasons'])
    for invalid in ({**relic_request['relic'], 'level': True}, {**relic_request['relic'], 'unknown': 1}):
        with pytest.raises((TypeError, ValueError)):
            battle.configure_relic({**relic_request, 'relic': invalid})
    with pytest.raises(ValueError, match='部位'):
        battle.configure_relic({**relic_request, 'slot_identity': 'HEAD'})
    with pytest.raises(ValueError):
        battle.relic_affixes({'scenario': scenario, 'template_identity': 'unknown'})
    removed_relic = battle.configure_relic({**relic_request, 'scenario': response['scenario'], 'relic': None})
    without_foot = ScenarioLoader().load_dict(removed_relic['scenario']).units[0].character_build
    assert len(without_foot.equipment_build.relics) == len(edited.equipment_build.relics) - 1
    assert without_foot.equipment_build.light_cone == edited.equipment_build.light_cone
    assert scenario == original and battle.session is None and not battle.steps
    view = battle.start({'scenario': response['scenario']})
    for _ in range(24):
        if view['outcome']:
            break
        assert view['decision']['ready'], view['decision']['blocked_reason']
        choices = view['decision']['availability']['choices']
        selected = ([choice for choice in choices if choice['choice_kind'] == 'ultimate_window']
                    or [choice for choice in choices if choice['choice_kind'] == 'manual_ultimate_request']
                    or [choice for choice in choices if choice['choice_kind'] == 'timeline_actor'
                        or choice['choice_kind'] == 'normal_action' and (
                            choice['actor_side'] == 'enemy' or choice['action_id'] == 'avatar_skill:100802')])
        choice = selected[0]
        query = choice['target_query']
        targets = [query['candidate_ids'][0]] if query and query['selection_mode'] == 'explicit' else []
        view = battle.submit({
            'session_id': view['session_id'], 'revision': view['revision'],
            'decision_id': view['decision']['token']['decision_id'],
            'command': {**choice['command_template'], 'target_ids': targets},
        })
        assert view['steps'][-1]['transition_outcome']['successor_eligible']
    assert view['outcome'] == 'victory'
    identity = {key: view[key] for key in ('session_id', 'revision')}
    detail = battle.detail(identity, 0)
    assert detail['source_audit']['ok'] and detail['replay']['ok']
    archive = tmp_path / 'equipment-form-battle.json.gz'
    archive.write_bytes(battle.download(identity))
    print(f'archive: {archive}')


@pytest.mark.integration
def test_http_live_battle_atomic_requests_victory_and_archive(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[4]
    battle = LiveBattle(root / 'turnbasedgamedata-main')
    class Handler(V8UIRequestHandler):
        def log_message(self, *_args):
            pass
    Handler.battle = battle

    def request(path, body=None):
        # Exercise the HTTP parser, routes and serialization without a listening socket.
        payload = json.dumps(body).encode() if body is not None else b''
        wire = (f"{'POST' if body is not None else 'GET'} {path} HTTP/1.0\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n").encode() + payload
        class Connection:
            output = b''
            def makefile(self, *_args):
                return BytesIO(wire)
            def sendall(self, data):
                self.output += bytes(data)
        connection = Connection()
        Handler(connection, ('127.0.0.1', 1), object())
        header, content = connection.output.split(b'\r\n\r\n', 1)
        status = int(header.split(b' ', 2)[1])
        return status, content if status == 200 and path.startswith('/api/battle/archive') else json.loads(content)

    def identity(view):
        return {key: view[key] for key in ('session_id', 'revision')}

    def submit(view, command):
        return request('/api/battle/submit', {**identity(view),
                       'decision_id': view['decision']['token']['decision_id'], 'command': command})

    status, examples = request('/api/battle/examples')
    assert status == 200
    scenario = next(item['scenario'] for item in examples['examples'] if item['case_id'] == 'arlan_vs_antimatter')
    status, view = request('/api/battle', {'scenario': scenario})
    assert status == 200, view
    assert view['decision']['ready']
    first = view
    saved_state = battle.session.state
    first_choice = next(c for c in view['decision']['availability']['choices'] if c['action_id'] == 'avatar_skill:100801')
    invalid = {**first_choice['command_template'], 'target_ids': ['arlan']}
    status, view = submit(view, invalid)
    assert status == 200 and not view['steps'][-1]['transition_outcome']['successor_eligible']
    rejected = battle.results[-1][1].transition
    assert not rejected.transaction.mutations and not rejected.rng_events
    assert battle.session.state == saved_state
    operations = len(battle.session.operations)
    assert submit(first, invalid)[0] == 409
    assert request('/api/battle', {'scenario': scenario})[0] == 409
    assert len(battle.session.operations) == operations
    assert submit(view, {})[0] == 400
    assert len(battle.session.operations) == operations
    assert request('/api/battle', {**identity(view), 'scenario': {}})[0] == 400
    assert battle.session.state == saved_state
    assert len(battle.session.operations) == operations
    status, current = request('/api/battle')
    assert status == 200 and current['revision'] == view['revision']

    # Import verifies the entire history before replacing the existing battle.
    query = f"session_id={view['session_id']}&revision={view['revision']}"
    status, saved = request(f'/api/battle/archive?{query}')
    assert status == 200
    envelope = json.loads(gzip.decompress(saved))
    old_session = battle.session
    saved_operations = list(old_session.operations)
    rules = old_session.rules
    bad = decode_archive_json(envelope)
    bad['outcome'] = 'victory'
    with monkeypatch.context() as patch:
        patch.setattr('simulator_v8_ui.live.build_battle_rulebook', lambda *_: rules)
        assert request('/api/battle/resume', {'archive': envelope})[0] == 409
        status, failure = request('/api/battle/resume', {**identity(view), 'archive': encode_archive_json(bad)})
        assert status == 400 and 'outcome_mismatch' in failure['error']
        assert battle.session is old_session and len(old_session.operations) == operations
        status, restored = request('/api/battle/resume', {**identity(view), 'archive': envelope})
    assert status == 200, restored
    assert restored['session_id'] != view['session_id']
    assert restored['restored_operation_count'] == operations and restored['revision'] == operations + 1
    assert _json_equal(battle.session.operations[:operations], saved_operations)
    assert _json_equal(battle.session.state.snapshot().to_json(detach=False),
                       old_session.state.snapshot().to_json(detach=False))
    assert submit(view, invalid)[0] == 409
    view = restored

    # Existing rulebook and session are reused by all ordinary requests.
    def no_compile(*_args, **_kwargs):
        pytest.fail('a command/query/download must not compile or rebuild the battle')
    monkeypatch.setattr('simulator_v8_ui.live.build_battle_rulebook', no_compile)
    ally_actions = 0
    off_turn = False
    for _ in range(40):
        if view['outcome']:
            break
        assert view['decision']['ready'], view['decision']['blocked_reason']
        choices = view['decision']['availability']['choices']
        slots = view['action_prompt']['slots']
        assert len(slots) == len(choices)
        assert [s['command_template'] for s in slots] == [c['command_template'] for c in choices]
        turn = view['decision']['availability']['turn_owner_id']
        queued = [c for c in choices if c['choice_kind'] == 'ultimate_window']
        requests = [c for c in choices if c['choice_kind'] == 'manual_ultimate_request']
        if queued:
            choice = queued[0]
        elif requests and turn and battle.session.state.units[turn].side == 'enemy':
            choice = requests[0]
            off_turn = True
            assert len({c['actor_id'] for c in choices}) > 1
        else:
            action = 'avatar_skill:100801' if ally_actions < 2 else 'avatar_skill:100802'
            choice = next(c for c in reversed(choices) if c['choice_kind'] == 'timeline_actor'
                          or c['choice_kind'] == 'normal_action' and
                          (c['actor_side'] == 'enemy' or c['action_id'] == action))
        targets = []
        query = choice['target_query']
        if query and query['selection_mode'] == 'explicit':
            target_index = ally_actions % len(query['candidate_ids']) if (
                choice['actor_side'] == 'ally' and choice['choice_kind'] == 'normal_action'
            ) else -1
            targets = [query['candidate_ids'][target_index]]
        status, view = submit(view, {**choice['command_template'], 'target_ids': targets})
        assert status == 200, view
        assert view['steps'][-1]['transition_outcome']['successor_eligible'], view['steps'][-1]
        if choice['actor_side'] == 'ally' and choice['choice_kind'] == 'normal_action':
            ally_actions += 1
    assert view['outcome'] == 'victory' and off_turn
    query = f"session_id={view['session_id']}&revision={view['revision']}"
    status, detail = request(f'/api/battle/steps/1?{query}')
    assert status == 200, detail
    assert detail['source_audit']['ok'] and detail['replay']['ok'], detail
    status, archive = request(f'/api/battle/archive?{query}')
    assert status == 200
    path = tmp_path / 'ui-live-battle.json.gz'
    path.write_bytes(archive)
    envelope = json.loads(gzip.decompress(archive))
    assert envelope['format'] == 'hsr_battle_archive_v2'
    assert request('/api/battle')[1]['revision'] == view['revision']
    print(f'archive: {path}')
