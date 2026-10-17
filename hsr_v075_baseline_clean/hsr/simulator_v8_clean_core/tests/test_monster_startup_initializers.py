"""Source-bound linear startup leaves; these are not complete boss battle tests."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state
from hsr.simulator_v8_clean_core.systems.startup import _apply_startup_ability_effects
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _admit_passive_startup_slot, _passive_startup_effect_blocked_reason,
    _link_status_effect_runtime_fields, _process_only_ability_task_source_blocked_reason,
    _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.monster_cards import build_monster_card_ir
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language


def test_explicit_monster_initializers_execute_in_order_and_keep_source():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    graphs, phases, tasks, effects, conditions, formulas, targets, _ = TBGDLowering(root)._lower_standalone_ability_graphs([
        root / 'Config/ConfigAbility/Monster/Monster_W1_Gepard_00_Ability.json',
    ])
    graph = next(g for g in graphs if g.ability_name == 'Monster_W1_Gepard_00_PassiveSkillInitiate')
    selected = tuple(t for t in tasks if t.phase_id in graph.phase_ids and t.opcode == 'DefineDynamicValue')
    assert len(selected) == 2
    selected_effects = tuple(e for t in selected for e in effects if e.effect_id == t.effect_id)
    assert all(_passive_startup_effect_blocked_reason(e, set()) == '' for e in selected_effects)
    card_ir = build_monster_card_ir(root, max_records_per_table=None, monster_ids=frozenset({'1004020'}))
    slot = next(s for s in card_ir.passive_mechanism_slots if s.semantics.get('ability_name') == graph.ability_name)
    admitted = _admit_passive_startup_slot(
        slot, graphs_by_name={graph.ability_name: [graph]},
        tasks_by_phase={p.phase_id: [t for t in tasks if t.phase_id == p.phase_id] for p in phases},
        effects_by_id={e.effect_id: e for e in effects}, modifiers_with_triggers=set(),
    )
    assert admitted.coverage_status == 'executable', admitted.blocked_reason
    assert {t.task_id for t in selected}.issubset(admitted.linked_ir_ids['admitted_task_ids'])
    original = selected_effects[0]
    for field, value in (('FutureField', True), ('ContextScope', 'Global'), ('ResetValue', {}),
                         ('TargetType', {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'LevelEntity'}),
                         ('DynamicKey', {'Value': 'counter', 'FutureField': True})):
        payload = {**original.payload, field: value}
        assert _passive_startup_effect_blocked_reason(replace(original, payload=payload), set())
    missing = {key: value for key, value in original.payload.items() if key != 'ResetValue'}
    assert _passive_startup_effect_blocked_reason(replace(original, payload=missing), set())
    ir = CanonicalIR('monster-startup-initializer-check', standalone_ability_graphs=tuple(graphs),
                     ability_phases=tuple(phases), ability_tasks=tuple(tasks), effects=tuple(effects),
                     conditions=tuple(conditions), formulas=tuple(formulas), target_expressions=tuple(targets))
    rules = RuleBook(ir)
    state = BattleState(units={'owner': UnitState('owner', 'enemy', 'fixture', hp=100, max_hp=100)})
    before = deepcopy(state.snapshot().to_json())
    spec = {'kind': 'monster_passive_startup_ability', 'unit_id': 'owner', 'ability_name': graph.ability_name,
            'graph_ref_id': graph.standalone_ability_graph_id,
            'admitted_task_ids': tuple(t.task_id for t in selected)}
    result = _apply_startup_ability_effects(state, rules, [spec])
    assert not result.blocked, [item.get('reason') for item in result.blocked]
    entries = store_from_state(result.state)['entries']
    assert len(entries) == 2
    assert {entry['name']: entry['value'] for entry in entries.values()} == {
        'Gepard_SummonCounter': 1, 'Gepard_AICounter': 1,
    }
    assert all(entry['target_id'] == 'owner' and entry['scope_kind'] == 'unit' for entry in entries.values())
    assert [trace['task_id'] for trace in result.source_traces] == [task.task_id for task in selected]
    assert state.snapshot().to_json() == before
    assert MutationReducer().apply_all(state, result.mutations).snapshot().to_json() == result.state.snapshot().to_json()
    rejected = _apply_startup_ability_effects(state, rules, [{**spec, 'unit_id': 'missing'}])
    assert rejected.blocked and not rejected.mutations and not rejected.rng_events
    assert rejected.state.snapshot().to_json() == before


def test_info_bar_startup_skips_only_visual_leaf_and_keeps_marker(monkeypatch):
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    path = root / 'Config/ConfigAbility/Monster/Monster_Common_Ability.json'
    lowerer = TBGDLowering(root)
    graphs, phases, tasks, effects, conditions, formulas, targets, _ = lowerer._lower_standalone_ability_graphs([path])
    graph = next(g for g in graphs if g.ability_name == 'Monster_Common_BossInfoBar')
    source = next(a for a in json.loads(path.read_text())['AbilityList'] if a['Name'] == graph.ability_name)
    visual = source['OnStart'][0]
    assert not _process_only_ability_task_source_blocked_reason(visual, 'ShowBossInfoBar')
    for changed in ({**visual, 'OnFinish': []}, {**visual, 'IsShow': 1},
                    {key: value for key, value in visual.items() if key != 'IsShow'},
                    {**visual, 'TargetType': {**visual['TargetType'], 'Unknown': True}}):
        assert _process_only_ability_task_source_blocked_reason(changed, 'ShowBossInfoBar')

    lowered = lowerer._lower_ability_file(path, {}, ability_file_order=0)
    marker = next(entity for entity in lowered.entities
                  if entity.fields.get('modifier_name') == 'MCommon_BOSSInfoBar_Active')
    linked_effects = _link_status_effect_runtime_fields(effects, [marker], [])
    definitions = lowerer._strict_target_language_definitions()
    targets = [close_target_expression_language(target, definitions) for target in targets]
    linked_effects = _synchronize_effect_target_expression_metadata(linked_effects, targets)
    cards = build_monster_card_ir(root, max_records_per_table=None, monster_ids=frozenset({'1004020'}))
    slot = next(s for s in cards.passive_mechanism_slots if s.semantics.get('ability_name') == graph.ability_name)
    args = dict(graphs_by_name={graph.ability_name: [graph]},
                tasks_by_phase={p.phase_id: [t for t in tasks if t.phase_id == p.phase_id] for p in phases},
                effects_by_id={effect.effect_id: effect for effect in linked_effects}, modifiers_with_triggers=set())
    admitted = _admit_passive_startup_slot(slot, **args)
    assert admitted.coverage_status == 'executable', admitted.blocked_reason
    proof = admitted.semantics['startup_admission']['presentation_tasks']
    assert len(proof) == 1 and proof[0]['source']['source_path'].endswith('Monster_Common_Ability.json')
    visual_task = next(task for task in tasks if task.task_id == proof[0]['task_id'])
    assert visual_task.execution_mode == 'process_only' and visual_task.coverage_status == 'audit_only'
    assert visual_task.task_id not in admitted.linked_ir_ids['admitted_task_ids']
    assert len(admitted.linked_ir_ids['admitted_task_ids']) == 1
    # A blocked or unproven visual leaf must still block the whole startup slot.
    bad_effects = {**args['effects_by_id'], visual_task.effect_id: replace(
        args['effects_by_id'][visual_task.effect_id], coverage_status='blocked',
    )}
    assert _admit_passive_startup_slot(slot, **{**args, 'effects_by_id': bad_effects}).coverage_status == 'blocked'
    ir = CanonicalIR('monster-info-bar-startup-check', entities=(marker,),
                     standalone_ability_graphs=(graph,), ability_phases=tuple(p for p in phases if p.phase_id in graph.phase_ids),
                     ability_tasks=tuple(t for t in tasks if t.phase_id in graph.phase_ids),
                     effects=tuple(linked_effects), conditions=tuple(conditions), formulas=tuple(formulas),
                     target_expressions=(*targets, *(definition.expression for definition in definitions)))
    state = BattleState(units={'owner': UnitState('owner', 'enemy', 'fixture')})
    result = _apply_startup_ability_effects(state, RuleBook(ir), [{
        'kind': 'monster_passive_startup_ability', 'unit_id': 'owner', 'ability_name': graph.ability_name,
        'graph_ref_id': graph.standalone_ability_graph_id,
        'admitted_task_ids': admitted.linked_ir_ids['admitted_task_ids'],
    }])
    assert not result.blocked, [item.get('reason') for item in result.blocked]
    assert 'modifier:MCommon_BOSSInfoBar_Active' in result.state.units['owner'].statuses
    assert not state.units['owner'].statuses
    assert len(result.source_traces) == 1 and result.source_traces[0]['task_id'] != visual_task.task_id
    assert MutationReducer().apply_all(state, result.mutations).snapshot().to_json() == result.state.snapshot().to_json()
    # The marker is externally observable: never classify the complete passive as visual.
    event_source = json.loads((root / 'Config/ConfigAbility/BattleEventAbility_2.json').read_text())
    listener = next(a for a in event_source['AbilityList'] if a['Name'] == 'BattleEventAbility_Challenge_Month_42_Level')
    assert 'MCommon_BOSSInfoBar_Active' in json.dumps(listener)

    # Exercise the shared post-spawn boundary with one real admitted passive.
    # This checks birth wiring, not a complete source monster summon action.
    from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
    from hsr.simulator_v8_clean_core.core.model import RNGEvent
    from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
    from hsr.simulator_v8_clean_core.systems.status import StatusApplicationResult, StatusSystem
    from hsr.simulator_v8_clean_core.systems.summon import SummonSystem, SummonTransitionPlan
    from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem

    card = replace(cards.monster_data_cards[0], passive_mechanism_slot_ids=(admitted.passive_slot_id,))
    rules = RuleBook(replace(ir, monster_data_cards=(card,), passive_mechanism_slots=(admitted,)))
    system = SummonSystem(rules)
    plan = SummonTransitionPlan(True, 'spawn_summoned_monster', owner_id='owner', unit_ids=('child',))
    child = UnitState('child', 'enemy', card.entity_ref, flags={'monster_data_card_id': card.card_id})
    birth = UnitLifecycleSystem().spawn_mutation(state, child, reason='bounded birth check',
                                               source='validation', source_trace=card.source.to_json())
    seen = []
    dispatch = EventDispatchSystem.dispatch_event
    rng = RNGEvent('validation', 'birth_rng_transport', 0.5)

    def track_dispatch(self, candidate, *, event, **kwargs):
        seen.append(str(event.to_json()['event_id']))
        dispatched = dispatch(self, candidate, event=event, **kwargs)
        return replace(dispatched, rng_events=(*dispatched.rng_events, rng))

    monkeypatch.setattr(EventDispatchSystem, 'dispatch_event', track_dispatch)
    spawned = system._with_halo_reconciliation(state, plan, (birth,), (), ())
    assert spawned.plan.ok and spawned.dispatched_event_ids and spawned.rng_events
    assert spawned.dispatched_event_ids.issubset(seen)
    counts = {event_id: seen.count(event_id) for event_id in spawned.dispatched_event_ids}
    committed = CombatExecutor(rules).commit_eventful_transition(
        state, mutations=spawned.mutations, events=spawned.events, records=spawned.records,
        rng_events=spawned.rng_events, dispatched_event_ids=spawned.dispatched_event_ids,
        producer_kind='summon_system', producer_id='bounded-birth', actor_id='owner',
    )
    assert not committed.errors, committed.errors
    assert all(seen.count(event_id) == count for event_id, count in counts.items())
    assert 'modifier:MCommon_BOSSInfoBar_Active' in committed.after_state.units['child'].statuses
    assert 'child' not in state.units and all(event in committed.rng_events for event in spawned.rng_events)
    # A failure after startup must discard the birth and its consumed RNG too.
    monkeypatch.setattr(StatusSystem, 'reconcile_halo_relations',
                        lambda *_: StatusApplicationResult(ok=False, unsupported=('test_halo_failure',)))
    rejected = system._with_halo_reconciliation(state, plan, (birth,), (), ())
    assert not rejected.plan.ok and not rejected.mutations and not rejected.events and not rejected.rng_events
    assert not rejected.dispatched_event_ids and 'child' not in state.units
