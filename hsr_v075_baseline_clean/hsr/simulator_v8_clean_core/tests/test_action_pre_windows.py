"""Action orchestration with a formal damage graph; synthetic inputs are not game evidence."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, TargetResolution, UnitState
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityPhaseIR, AbilityTaskIR, ActionAbilityBindingIR, ActionDefinitionIR, ActionEventIR,
    ActionPhaseStepIR, CanonicalIR, DamageEmissionIR, DamageModifierIR, EffectIR, HitProfileIR, IRSource,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphQueryResult
from hsr.simulator_v8_clean_core.systems.action_event_contract import _issue_admitted_action_target_fact
from hsr.simulator_v8_clean_core.systems.action_selection import ActionTargetImpactResult
from hsr.simulator_v8_clean_core.systems.damage import DamageModifierContribution
from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import _graph


def test_before_attack_modifier_reaches_the_first_formal_onstart_damage():
    source = IRSource('validation_fixture/action-order', 'AbilityTask', 'damage', {
        'json_path': '$.OnStart[0]', 'content_sha256': 'c' * 64,
        'source_opcode': 'DamageByAttackProperty',
    })
    definition = ActionDefinitionIR('definition', 'action', 1, 'Normal', 'Basic', 'single',
        0, 0, 0, 0, (), (), (), 'Fire', source, coverage_status='executable',
        damage_kind='hp_damage', damage_formula_family='direct', element_type='Fire')
    task = AbilityTaskIR('damage-task', 'phase', 'action', 1, 'ability', 'OnStart',
        0, '$.OnStart[0]', 'root', 'DamageByAttackProperty', source,
        effect_id='effect', coverage_status='executable')
    phase = AbilityPhaseIR('phase', 'binding', 'action', 1, 'ability', 0, {}, {}, {}, source,
        coverage_status='executable', task_ids=(task.task_id,), invocation_role='action_root')
    binding = ActionAbilityBindingIR('binding', 'action', 1, 'Skill01', 'Skill01', 'ability',
        ('ability',), {}, ('phase',), 'mainline', source, coverage_status='executable')
    profile = HitProfileIR('hit', 'action', 1, 0, 'selected', numeric_fixed(1), {},
        numeric_fixed(0), {}, 'direct', 'Fire', source, coverage_status='executable')
    emission = DamageEmissionIR('damage', 'action', 1, 'phase', task.task_id, 'hit', 'selected',
        'direct', 'Fire', numeric_fixed(1),
        {'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'}, source,
        coverage_status='executable', toughness_emission_required=False)
    effect = EffectIR('effect', task.opcode, {},
        replace(source, evidence={**source.evidence, 'parent_task_id': ''}), coverage_status='audit_only')
    graph = _graph('phase', task, references=(('effect', 'effect', 'deferred',
        'task_graph_definition_not_admitted:effect:audit_only'),))
    steps = tuple(ActionPhaseStepIR('trigger_window', window, window, event,
        coverage_status='executable', source=source) for window, event in (
        ('before_skill_use', 'OnBeforeSkillUse'), ('before_attack', 'OnBeforeAttack')))
    action_event = ActionEventIR('action:event', 'action', 1, 'single', 'explicit', (
        *steps, ActionPhaseStepIR('damage', 'damage', coverage_status='executable', source=source),
        ActionPhaseStepIR('trigger_window', 'after_skill_use', 'after_skill_use', 'OnAfterSkillUse',
                          coverage_status='executable', source=source)), ('hit',), 'derived', '', source,
        coverage_status='executable', binding_id='binding', phase_ids=('phase',),
        event_source_status='ability_phase_graph_bound', target_relation='enemy')

    class GraphRules(RuleBook):
        def query_formal_task_graph(self, entry_kind, owner_id, callback_kind, formal_task_ids):
            assert (entry_kind, owner_id, callback_kind, tuple(formal_task_ids)) == (
                'ability_phase_callback', 'phase', 'OnStart', (task.task_id,))
            return TaskGraphQueryResult('resolved', 'graph', (graph.graph_id,), graph, '')

        def query_task_graph(self, graph_id):
            return TaskGraphQueryResult('resolved', 'graph', (graph_id,), graph, '')

        def query_task_graph_node(self, node_id):
            return TaskGraphQueryResult('resolved', 'node', (node_id,), graph.nodes[0], '')

    registry = build_engine_rule_registry()
    rules = GraphRules(CanonicalIR('validation', action_definitions=(definition,),
        action_ability_bindings=(binding,), action_events=(action_event,), ability_phases=(phase,),
        ability_tasks=(task,), effects=(effect,), hit_profiles=(profile,), damage_emissions=(emission,),
        damage_formula_rules=registry.damage_formula_rules, damage_route_rules=registry.damage_route_rules,
        resource_rules=registry.resource_rules))
    state = BattleState(units={
        'actor': UnitState('actor', 'ally', 'fixture', hp=1000, max_hp=1000, attack=100),
        'target': UnitState('target', 'enemy', 'fixture', hp=1000, max_hp=1000),
    }, global_flags={'phase': 'combat', 'current_window': 'idle', 'turn_owner_id': 'actor'})
    resolution = TargetResolution(requested=('target',), legal=('target',), selected=('target',),
        primary='target', impact_group=('target',), source='action_target_selection_system',
        metadata={'target_groups': {'selected': ['target'], 'primary': ['target'], 'impact': ['target']}})
    impact = ActionTargetImpactResult('resolved', 'selection', resolution)
    fact = _issue_admitted_action_target_fact(actor_id='actor', action_id='action', action_level=1,
        selection_context_fingerprint='selection', contract_fingerprint='contract',
        impact_fingerprint=impact.impact_fingerprint, canonical_action_event_id='action:event',
        target_mode='single', target_ids=('target',))
    impact = replace(impact, admitted_action_target_fact=fact)
    context = SimpleNamespace(context_fingerprint='selection', dynamic_target=False, to_json=lambda: {},
        accepted=SimpleNamespace(query_fingerprint='query', selection_fingerprint='accepted'))
    modifier = DamageModifierIR('bonus', 'callback', 'bonus-task', 'status', 'OnBeforeAttack', 'Caster',
        ({'coverage_status': 'executable', 'bucket': 'damage_bonus', 'key': 'damage_added_ratio',
          'numeric_expr': numeric_fixed(0.5)},), source, coverage_status='executable')

    def execute(with_bonus):
        executor = CombatExecutor(rules)
        dispatch = executor.event_dispatcher.dispatch_action_window_listeners
        windows = []

        def listen(current, *, event, **kwargs):
            windows.append(event.event_type)
            result = dispatch(current, event=event, **kwargs)
            if event.event_type == 'action.window.before_attack' and with_bonus:
                result = replace(result, damage_modifiers=(DamageModifierContribution(modifier, 0, 0.5),))
            return result

        # This check isolates execution ordering from the independently tested
        # submission gates and listener matching. The graph and packets are real.
        with patch.object(executor.action_targets, 'context_identity_blocked_reason', return_value=''), \
             patch.object(executor.action_targets, 'resolve_impact', return_value=impact), \
             patch.object(executor.action_contract, 'evaluate',
                          return_value=SimpleNamespace(ok=True, to_json=lambda: {})), \
             patch.object(executor.event_dispatcher, 'dispatch_action_window_listeners', side_effect=listen):
            after, transition = executor.execute(ActionCommand('actor', 'action', 1, ('target',),
                metadata={'crit_mode': 'noncrit'}), state, target_selection_context=context)
        assert transition.outcome.successor_eligible, transition.outcome.to_json()
        after_attack = [event for event in transition.transaction.events
                        if event.event_type == 'damage.target_attack.after']
        assert len(after_attack) == 1 and after_attack[0].target_id == 'target'
        assert after_attack[0].hit_window_invocation_fact.target_status_instance_ids == ()
        records = transition.transaction.settlement.records
        damage_index = next(i for i, row in enumerate(records) if row['record_type'] == 'damage')
        for window in ('before_skill_use', 'before_attack'):
            before = next(i for i, row in enumerate(records) if row['record_type'] == 'trigger_window'
                          and row['payload'].get('canonical_window') == window)
            assert before < damage_index
        assert windows[:2] == ['action.window.before_skill_use', 'action.window.before_attack']
        return state.units['target'].hp - after.units['target'].hp

    baseline, boosted = execute(False), execute(True)
    assert abs(boosted - baseline * 1.5) < 1e-10
