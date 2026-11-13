"""Component contract: permanent-status reapplication uses the committed source identity."""
from hsr.simulator_v8_clean_core.systems.status import (
    _same_definition_permanent_reapplication,
)

_MISSING = {"kind": "missing"}
_SOURCE_ID = "ability_task:ability_phase:avatar_skill:x:OnStart:OnStart[0]:AddModifier"


def test_status_instance_isolates_mutable_inputs_and_shares_unchanged_evidence():
    from dataclasses import replace
    import pytest
    from hsr.simulator_v8_clean_core.systems.status import StatusInstance

    evidence = {'source': {'values': [1, 2]}}
    instance = StatusInstance('instance', 'status', 'marker', 'owner', 'source', 'caster', source_trace=evidence)
    evidence['source']['values'].append(3)
    assert instance.source_trace['source']['values'] == [1, 2]
    assert replace(instance, stacks=2).source_trace is instance.source_trace
    assert instance.to_json()['source_trace'] is instance.source_trace
    with pytest.raises(TypeError):
        instance.source_trace['source']['values'].append(4)


def test_replacing_halo_parent_retires_old_projections_before_rebuilding():
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
    from hsr.simulator_v8_clean_core.rules.ir import IRSource
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
    from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.tests.test_status_control_resistance import _source_case, _state
    from hsr.simulator_v8_clean_core.tbgd.lowering import _attach_target_expressions_to_effect_payload
    from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions
    from pathlib import Path

    original, effect, definition, *_ = _source_case()
    source = IRSource('fixture/halo_replace.json', 'Modifier', 'parent', {'json_path': '$.Parent'})
    parent = replace(definition, source=source, fields={**definition.fields, 'modifier_name': 'parent',
        'stacking': 'ReplaceByCaster', 'life_step_moment': 'TurnEnd', 'behavior_flags': [],
        'stack_properties': [], 'dynamic_values': {}, 'dynamic_value_bindings': {},
        'addition_effect_ids': ['child-effect']})
    child = replace(parent, entity_id='child-definition', source=replace(source, raw_id='child'),
                    fields={**parent.fields, 'modifier_name': 'child', 'addition_effect_ids': []})
    parent_effect = replace(effect, source=source, status_callback_ids=(),
        payload={**effect.payload, 'standard': {**effect.payload['standard'], 'modifier_name': 'parent',
            'dynamic_values': {}, 'dynamic_value_requests': [], 'lifetime': numeric_fixed(2)}})
    child_source = replace(source, raw_id='parent:child', evidence={'json_path': '$.Parent.AdditionConfig[0]'})
    child_effect = replace(parent_effect, effect_id='child-effect', source=child_source,
        owner_modifier_name='parent', modifier_definition_id=child.entity_id,
        payload={**parent_effect.payload, 'standard': {**parent_effect.payload['standard'], 'modifier_name': 'child',
            'addition_parent_modifier_name': 'parent', 'addition_source_json_path': '$.Parent.AdditionConfig[0]',
            'is_halo_status_present': True, 'is_halo_status': True, 'halo_admission_status': 'executable',
            'is_halo_status_source_json_path': '$.Parent.AdditionConfig[0].IsHaloStatus'}})
    child_payload, child_targets = _attach_target_expressions_to_effect_payload(child_effect.payload,
        {'$type': 'RPG.GameCore.AddModifier', 'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'}},
        effect_id=child_effect.effect_id, source=child_source,
        target_language_definitions=build_target_language_definitions(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'))
    child_effect = replace(child_effect, payload=child_payload)
    rules = RuleBook(replace(original.ir, entities=(parent, child), effects=(parent_effect, child_effect),
                             status_callbacks=(), status_callback_tasks=(),
                             target_expressions=(*original.ir.target_expressions, *child_targets)))
    system, reducer = StatusSystem(rules), MutationReducer()
    state = _state()
    old_parent = None
    for source_id in ('first-skill', 'second-skill'):
        result = system.apply_add_modifier(state, parent_effect, caster_id='holder', source_id=source_id)
        assert result.ok, result.unsupported
        state = reducer.apply_all(state, result.mutations)
        details = state.units['holder'].flags['status_details']
        parents = [d for d in details if d['modifier_name'] == 'parent']
        children = [d for d in details if d['modifier_name'] == 'child']
        assert len(parents) == len(children) == 1
        relation, = parents[0]['halo_relations']
        assert relation['parent_instance_id'] == parents[0]['instance_id']
        if old_parent is not None:
            assert parents[0]['instance_id'] != old_parent
        old_parent = parents[0]['instance_id']
        assert system.reconcile_halo_relations(state).ok


def test_non_alive_halo_keeps_existing_members_during_limbo():
    from dataclasses import replace
    from pathlib import Path
    from hsr.simulator_v8_clean_core.rules.ir import IRSource
    from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
    from hsr.simulator_v8_clean_core.systems.status import _defeated_halo_member_remains_related
    from hsr.simulator_v8_clean_core.systems.target import TargetSystem
    from hsr.simulator_v8_clean_core.tests.test_status_control_resistance import _source_case, _state
    from hsr.simulator_v8_clean_core.tbgd.lowering import _attach_target_expressions_to_effect_payload
    from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions

    rules, effect, *_ = _source_case()
    raw = {'$type': 'RPG.GameCore.AddModifier',
           'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'AllTeamMember'}}
    _, expressions = _attach_target_expressions_to_effect_payload(effect.payload, raw,
        effect_id=effect.effect_id, source=IRSource('fixture:halo', 'AddModifier', 'halo', {'json_path': '$.halo'}),
        target_language_definitions=build_target_language_definitions(
            Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'))
    expression, = expressions
    rules = RuleBook(replace(rules.ir, target_expressions=(*rules.ir.target_expressions, expression)))
    state = _state()
    wounded = replace(state.units['holder'], hp=0, lifecycle_status='limbo')
    state = replace(state, units={**state.units, 'holder': wounded})
    kwargs = dict(caster_id='holder', owner_id='holder', dynamic_values={}, binding_sources=())
    assert _defeated_halo_member_remains_related(TargetSystem(rules), state, expression,
        target_id='holder', **kwargs) == (True, '')
    assert state.units['holder'] is wounded and wounded.hp == 0


def _standard(**overrides):
    standard = {
        "lifetime": _MISSING,
        "layer_add_when_stack": _MISSING,
        "max_layer": _MISSING,
        "chance": _MISSING,
    }
    standard.update(overrides)
    return standard


def _detail(**overrides):
    detail = {
        "caster_id": "caster",
        "source_id": _SOURCE_ID,
        # The audit trace must never decide this behavior.
        "source_trace": {"effect_source": {"source_path": "forged"}, "effect_id": "x"},
    }
    detail.update(overrides)
    return detail


def _same(detail, *, source_id=_SOURCE_ID, refresh=None, standard=None):
    return _same_definition_permanent_reapplication(
        detail,
        caster_id="caster",
        standard=standard or _standard(),
        refresh_admission=refresh or {"admission_status": "not_applicable"},
        source_id=source_id,
    )


def test_same_committed_source_replaces_while_the_audit_trace_is_ignored():
    assert _same(_detail()) is True
    # A different committed task identity cannot be replaced by a matching trace.
    assert _same(_detail(source_trace={"effect_source": {"source_path": "forged"}}),
                 source_id="ability_task:other") is False
    # A matching committed task identity still replaces despite a changed trace.
    assert _same(_detail(source_trace={"effect_source": {"source_path": "changed"}})) is True


def test_different_caster_missing_lifetime_or_refresh_admission_never_replaces():
    assert _same(_detail(caster_id="other")) is False
    assert _same(_detail(), standard=_standard(lifetime={"kind": "fixed", "value": 2})) is False
    assert _same(_detail(), refresh={"admission_status": "refresh"}) is False
    assert _same(_detail(), source_id="") is False
    assert _same(None) is False


def test_parameterless_permanent_listener_reapplication_emits_no_add_event():
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
    from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.tests.test_status_control_resistance import _source_case, _state

    rules, effect, definition, *_ = _source_case()
    # Synthetic listener using the existing formal Caster target expression.
    definition = replace(definition, fields={
        **definition.fields,
        'modifier_name': 'fixture_listener', 'max_layer_expr': _MISSING,
        'behavior_flags': [], 'stack_properties': [], 'dynamic_values': {},
        'dynamic_value_bindings': {},
        'layer_add_when_stack_expr': _MISSING, 'callback_events': ['OnModifierRemove'],
    })
    effect = replace(effect, status_callback_ids=(), payload={**effect.payload,
        'standard': {**effect.payload['standard'], 'modifier_name': 'fixture_listener',
                     'dynamic_values': {}, 'dynamic_value_requests': []}})
    rules = RuleBook(replace(rules.ir, entities=(definition,), effects=(effect,),
                             status_callbacks=(), status_callback_tasks=()))
    system = StatusSystem(rules)
    first = system.apply_add_modifier(_state(), effect, caster_id='holder', source_id='same-task')
    assert first.ok and first.events
    state = MutationReducer().apply_all(_state(), first.mutations)
    repeated = system.apply_add_modifier(state, effect, caster_id='holder', source_id='same-task')
    assert repeated.ok and not repeated.mutations and not repeated.events
    assert repeated.lifecycle_result.operation == 'idempotent'
