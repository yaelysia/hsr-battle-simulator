"""Component contracts for R07 shared battle-event and rank-default mechanics."""
import json
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR, CharacterDataCardIR, CharacterEidolonSlotIR, EffectIR, IRSource,
    TargetExpressionNodeIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.dynamic_values import (
    character_skill_param_binding_sources,
)
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _condition_target_value_executable, _effect_coverage_status, _effect_payload,
    _status_callback_task_admission, _target_expression_runtime_blocked_reason,
)

_ROOT = Path(__file__).resolve().parents[4]
_TBGD = _ROOT / 'turnbasedgamedata-main'


def test_attach_entity_unselectable_is_a_strict_presentation_free_runtime_flag():
    source = IRSource('Config/ConfigAbility/Avatar/Avatar_Topaz_00_Ability.json',
                      'AbilityTask', 'Topaz_BETag')
    raw = {'$type': 'RPG.GameCore.AttachEntityUnselectable'}
    payload = _effect_payload(raw, 'AttachEntityUnselectable', '', source=source)
    assert _effect_coverage_status('AttachEntityUnselectable', payload) == 'executable'
    for changed in ({**raw, 'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'}},
                    {**raw, 'Unknown': True}):
        assert _effect_coverage_status(
            'AttachEntityUnselectable',
            _effect_payload(changed, 'AttachEntityUnselectable', '', source=source),
        ) == 'blocked'
    rules = RuleBook(CanonicalIR('attach-unselectable'))
    state = BattleState(units={'actor': UnitState('actor', 'ally', 'fixture:actor', hp=10, max_hp=10)})
    effect = EffectIR('effect', 'AttachEntityUnselectable', payload, source, 'executable')
    result = EffectRegistry(StatusSystem(rules)).execute(
        effect, EffectExecutionContext(state, 'actor', 'effect'),
    )
    assert not result.unsupported and len(result.mutations) == 1
    mutation = result.mutations[0]
    assert mutation.path == ('units', 'actor', 'flags', 'target_unselectable')
    assert mutation.after is True
    after = BattleState(units={'actor': UnitState(
        'actor', 'ally', 'fixture:actor', hp=10, max_hp=10,
        flags={'target_unselectable': True},
    )})
    repeated = EffectRegistry(StatusSystem(rules)).execute(
        effect, EffectExecutionContext(after, 'actor', 'effect'),
    )
    assert not repeated.unsupported and repeated.mutations[0].before is True


def test_on_enter_battle_admits_only_executable_setup_effects():
    document = json.loads((_TBGD / 'Config/ConfigAbility/Avatar/Avatar_Castorice_00_Ability.json').read_text())
    task = next(
        task for ability in document['AbilityList'] for task in ability.get('OnStart', ())
        if task.get('$type') == 'RPG.GameCore.SetDynamicValue'
        and task.get('DynamicKey', {}).get('Value') == 'Castorice_IsFirstWaitForSummon'
    ) if any(
        task.get('DynamicKey', {}).get('Value') == 'Castorice_IsFirstWaitForSummon'
        for ability in document['AbilityList'] for task in ability.get('OnStart', ())
    ) else next(
        task for ability in document['AbilityList'] for task in ability.get('OnStart', ())
        if task.get('$type') == 'RPG.GameCore.SetDynamicValue'
    )
    assert _status_callback_task_admission('OnEnterBattle', 'SetDynamicValue', task)[0] == 'executable'
    unknown_opcode = {'$type': 'RPG.GameCore.ChangeBattleEventOwner'}
    assert _status_callback_task_admission(
        'OnEnterBattle', 'ChangeBattleEventOwner', unknown_opcode,
    )[0] == 'blocked'


def test_unowned_rank_zero_baseline_is_runtime_only():
    source = IRSource('synthetic', 'validation', 'rank')
    read = {'Type': 'SkillRank', 'TriggerKey': 'Rank01', 'Index': 0}
    card = CharacterDataCardIR(
        card_id='card', entity_ref='avatar:fixture', profile_id='profile', skill_ids=(),
        skill_formula_binding_ids=(), bounce_policy_ids=(), action_set={}, source=source,
        dynamic_value_bindings={'by_hash': {'123': {'read_info': read}}},
        eidolon_slot_ids=('rank',),
    )
    slot = CharacterEidolonSlotIR(
        'rank', 'card', 'fixture', 1, 'rank-id', (), source,
        semantics={'param_values': [0.1], 'dynamic_value_bindings': {'by_hash': {
            '123': {'read_info': dict(read), 'param_index': 0, 'rank': 1},
        }}},
        coverage_status='executable', blocked_reason='',
    )
    rules = RuleBook(CanonicalIR('rank-default', character_data_cards=(card,),
                                character_eidolon_slots=(slot,)))
    state = BattleState(units={'actor': UnitState('actor', 'ally', 'avatar:fixture', flags={
        'build_mode': 'assembled_character_build',
        'character_build_battle_admission_status': 'admitted',
        'character_data_card_id': 'card',
        'selected_eidolon_slot_ids': (),
    })})
    assert character_skill_param_binding_sources(rules, state, ('actor',)) == ()
    (runtime_source,) = character_skill_param_binding_sources(
        rules, state, ('actor',), include_unowned_rank_defaults=True,
    )
    entry = next(iter(runtime_source['entries'].values()))
    assert entry['value'] == 0.0
    assert entry['binding_role'] == 'declared_rank_param_default'


def test_turn_action_entity_alias_is_a_typed_committed_turn_owner_target():
    source = IRSource(
        'Config/GlobalConfig/TargetAliasConfig.json', 'TargetExpression',
        'CurrentTurnActionEntity',
        evidence={
            'source_raw_type': 'AliasDict',
            'json_path': '$.AliasDict.CurrentTurnActionEntity',
        },
    )
    turn_action = TargetExpressionNodeIR.build(
        'TargetAlias', source, {'alias': 'CurrentTurnActionEntity'},
    )
    caster = TargetExpressionNodeIR.build('TargetAlias', source, {'alias': 'Caster'})
    unknown = TargetExpressionNodeIR.build('TargetAlias', source, {'alias': 'UnknownAlias'})
    assert _condition_target_value_executable(turn_action)
    assert _condition_target_value_executable(caster)
    assert not _condition_target_value_executable(unknown)
    assert _target_expression_runtime_blocked_reason(
        {'$type': 'RPG.GameCore.TargetFetchTurnActionEntity'}
    ) == ''
    node = TargetExpressionNodeIR.build('TargetFetchTurnActionEntity', source, {})
    assert node.expression_kind == 'TargetFetchTurnActionEntity' and node.payload == {}


def test_battle_event_dot_target_operations_and_removed_lifecycle_tracking():
    from hsr.simulator_v8_clean_core.systems.event_dispatch import _lifecycle_removed_instance
    from hsr.simulator_v8_clean_core.tbgd.lowering import _target_alias_chain_admitted
    from hsr.simulator_v8_clean_core.core.model import GameEvent

    # CBattleEvent filter and map operations are formal target-language
    # operations backed by entity.created_battle_events.
    assert _target_alias_chain_admitted('AllTeamMemberWithUnselectable.WithBattleEvent')
    assert _target_alias_chain_admitted('ParamEntityList.GetBattleEvent')
    assert not _target_alias_chain_admitted('AllTeamMemberWithUnselectable.UnknownBattleEventOp')
    remove = GameEvent(
        'status.lifecycle', window='OnDestroy', payload={
            'lifecycle_operation': 'remove',
            'status_instance_id': 'status:gone',
        },
    )
    add = GameEvent(
        'status.lifecycle', window='OnAddModifierSuc', payload={
            'lifecycle_operation': 'add',
            'status_instance_id': 'status:live',
        },
    )
    assert _lifecycle_removed_instance(remove) == 'status:gone'
    assert _lifecycle_removed_instance(add) == ''


def test_lingsha_event_lifetime_counter_is_an_adopted_independent_count():
    from hsr.simulator_v8_clean_core.tbgd.adopted_modifier_counts import (
        ADOPTED_MODIFIER_COUNTS,
    )

    path = (
        "$.GlobalModifiers.MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime"
        "._CallbackList[1].CallbackConfig[0]"
    )
    rule = ADOPTED_MODIFIER_COUNTS[
        ('Config/ConfigAbility/Avatar/Avatar_Lingsha_00_Ability.json', path)
    ]
    assert rule['operation'] == 'Add' and rule['amount'] == 1
    assert rule['modifier_name'] == 'MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime'
    assert rule['target_alias'] == 'ModifierOwnerEntity'
    assert rule['research'] and rule['version'] and rule['condition']
    source = IRSource(
        'Config/ConfigAbility/Avatar/Avatar_Lingsha_00_Ability.json',
        'AbilityTask', 'LifeTimeCounter', {'json_path': path},
    )
    raw = {'$type': 'RPG.GameCore.SetModifierValue', 'ModifyFunction': 'Add'}
    payload = _effect_payload(
        raw, 'SetModifierValue',
        'MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime', source=source,
    )
    standard = payload['standard']
    assert _effect_coverage_status('SetModifierValue', payload) == 'executable'
    assert standard['target_alias'] == 'ModifierOwnerEntity'
    assert standard['value_kind'] == 'independent_count'
    assert standard['modify_function'] == 'Add'
    assert standard['adopted_rule_source']['research'] == rule['research']
    # Omitted fields outside the adopted source shape stay blocked.
    assert _effect_coverage_status(
        'SetModifierValue',
        _effect_payload(
            {**raw, 'Value': {'IsDynamic': False, 'FixedValue': {'Value': 3}}},
            'SetModifierValue',
            'MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime', source=source,
        ),
    ) == 'blocked'


def test_independent_count_add_bootstraps_only_adopted_single_instance_presence():
    source = IRSource(
        'Config/ConfigAbility/Avatar/Avatar_Lingsha_00_Ability.json',
        'AbilityTask', 'LifeTimeCounter',
        {'json_path': '$.GlobalModifiers.MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime'
                      '._CallbackList[1].CallbackConfig[0]'},
    )
    payload = _effect_payload(
        {'$type': 'RPG.GameCore.SetModifierValue', 'ModifyFunction': 'Add'},
        'SetModifierValue', 'MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime', source=source,
    )
    assert payload['standard']['count_bootstrap_policy'] == 'single_instance_presence'
    effect = EffectIR('effect:lingsha-count', 'SetModifierValue', payload, source, 'executable')
    rules = RuleBook(CanonicalIR('modifier-count', effects=(effect,)))
    detail = {
        'instance_id': 'status:counter',
        'status_id': 'modifier:MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime',
        'modifier_name': 'MAvatar_Lingsha_BPSkill_BattleEvent_LifeTime',
        'owner_id': 'event', 'caster_id': 'event', 'source_id': 'caster',
        'stacks': 1, 'max_stacks': 1, 'stack_policy': 'single_instance',
        'lifecycle_state': 'active',
    }
    state = BattleState(units={'event': UnitState(
        'event', 'enemy', 'fixture:event', hp=10, max_hp=10,
        statuses=(detail['status_id'],), flags={'status_details': [detail]},
    )})
    # The formal rule grants the permission; trimming audit links changes nothing.
    for metadata in (
        {'effect_id': effect.effect_id, 'standard': payload['standard']},
        {'effect_id': effect.effect_id},
    ):
        result = StatusSystem(rules).modify_modifier_value(
            state, 'event', detail['modifier_name'], 'independent_count', 'Add', 1,
            caster_id='event', metadata=metadata,
        )
        assert result.ok and not result.unsupported
        after = result.mutations[0].after[0]
        assert after['stacks'] == 2
        assert after['stack_policy'] == 'independent_count'
        assert after['max_stacks'] is None
    # Arbitrary links, a missing rule and another modifier's rule stay fail-closed.
    other_name = 'fixture_other_modifier'
    other = {**detail, 'modifier_name': other_name, 'status_id': f'modifier:{other_name}'}
    other_state = BattleState(units={'event': UnitState(
        'event', 'enemy', 'fixture:event', hp=10, max_hp=10,
        statuses=(other['status_id'],), flags={'status_details': [other]},
    )})
    forged = {'standard': {**payload['standard'],
                           'adopted_rule_source': {'research': 'arbitrary-link'}}}
    for current, name, metadata in (
        (state, detail['modifier_name'], forged),
        (state, detail['modifier_name'], {'effect_id': 'effect:missing', **forged}),
        (other_state, other_name, {'effect_id': effect.effect_id}),
    ):
        rejected = StatusSystem(rules).modify_modifier_value(
            current, 'event', name, 'independent_count', 'Add', 1,
            caster_id='event', metadata=metadata,
        )
        assert not rejected.ok and not rejected.mutations
        assert 'modifier_count_state_not_admitted' in rejected.unsupported


def test_created_battle_event_alias_resolves_creator_and_the_event_itself():
    from hsr.simulator_v8_clean_core.systems.effect import _resolve_target_alias
    from hsr.simulator_v8_clean_core.systems.target import (
        resolve_created_battle_event_targets,
    )

    state = BattleState(units={
        'probe': UnitState('probe', 'ally', 'fixture:probe', hp=100, max_hp=100),
        'event': UnitState(
            'event', 'enemy', 'fixture:event', hp=100, max_hp=100,
            flags={'entity_type': 'battle_event', 'summoner_id': 'probe'},
        ),
    })
    assert resolve_created_battle_event_targets(state, 'probe') == ('event',)
    # A battle-event unit acting as its own ability caster names the same event.
    assert resolve_created_battle_event_targets(state, 'event') == ('event',)
    assert resolve_created_battle_event_targets(state, 'missing') == ()
    assert _resolve_target_alias(
        'CasterSelfCreateBattleEvent', caster_id='probe', owner_id=None,
        param_entity_id=None, current_action_target_id=None, state=state,
    ) == 'event'
    assert _resolve_target_alias(
        'CasterSelfCreateBattleEvent', caster_id='event', owner_id=None,
        param_entity_id=None, current_action_target_id=None, state=state,
    ) == 'event'
    assert _resolve_target_alias(
        'BattleEventCaster', caster_id='event', owner_id=None,
        param_entity_id=None, current_action_target_id=None, state=state,
    ) == 'probe'


def test_owned_servant_identity_is_not_a_declared_zero_or_an_arbitrary_sibling():
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.rules.ir import ServantDefinitionIR, ServantOwnerRelationIR
    from hsr.simulator_v8_clean_core.systems.dynamic_values import character_declared_dynamic_binding_source
    source = IRSource('fixture:owned-identity', 'Component', 'identity')
    card = CharacterDataCardIR('card', 'avatar:owner', 'profile', (), (), (), source, 'executable',
        dynamic_value_bindings={'by_hash': {'7': {'read_info': {'Type': 'None', 'Index': 0},
            'source_path': 'fixture:owner-config', 'value_producer': 'owned_servant_identity', 'logical_name': 'identity'}}})
    relation = ServantOwnerRelationIR('relation', 'avatar:owner', 'card', (), (source,), coverage_status='executable')
    definition = ServantDefinitionIR('servant:91', 'servant:91', 'unit', (), {}, {}, {}, {}, source,
        coverage_status='executable', owner_relations=(relation,))
    rules = RuleBook(CanonicalIR('owned-identity', character_data_cards=(card,), servant_definitions=(definition,)))
    state = BattleState(units={'owner': UnitState('owner', 'ally', 'avatar:owner', hp=10, max_hp=10)})
    binding = character_declared_dynamic_binding_source(rules, state, 'owner')
    assert next(iter(binding['entries'].values()))['value'] == 91
    other = replace(definition, servant_definition_id='servant:92', servant_ref='servant:92',
                    owner_relations=(replace(relation, owner_relation_id='other-relation'),))
    ambiguous = RuleBook(replace(rules.ir, servant_definitions=(definition, other)))
    assert character_declared_dynamic_binding_source(ambiguous, state, 'owner') is None
    missing = RuleBook(replace(rules.ir, servant_definitions=()))
    assert character_declared_dynamic_binding_source(missing, state, 'owner') is None


def test_definition_constant_reads_require_all_levels_and_no_formal_writer():
    from types import SimpleNamespace as Row
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.tbgd.lowering import _bind_definition_constant_parameters
    source = IRSource('fixture:constant-module', 'Component', 'read')
    raw = {'$type': 'RPG.GameCore.SetDynamicValue', 'DynamicKey': 'result',
           'Value': {'IsDynamic': True, 'PostfixExpr': {'OpCodes': 'AQAR', 'FixedValues': [], 'DynamicHashes': [7]}}}
    payload = _effect_payload(raw, 'SetDynamicValue', '', source=source)
    effect = EffectIR('read', 'SetDynamicValue', payload, source, 'executable')
    card = Row(card_id='card', entity_ref='avatar:owner')
    def slot(identifier, value):
        return Row(character_data_card_id='card', mechanism_kind='trace_skill_point_param',
            mechanism_slot_id=identifier, source=source,
            semantics={'param_values': [value], 'dynamic_value_bindings': {'by_hash': {
                '7': {'read_info': {'Type': 'SkillTreeParam', 'TriggerKey': 'point', 'Index': 0}, 'param_index': 0}}}})
    catalog = Row(sources=(), graphs=(), definitions=(Row(owner_avatar_id='owner', source=source),))
    folded = _bind_definition_constant_parameters([effect], [card], [slot('one', 4)], catalog)[0]
    assert folded.payload['standard']['value_expr']['value'] == 4
    assert folded.payload['standard']['compiled_definition_parameter_reads'][0]['definition_sources']
    ambiguous = _bind_definition_constant_parameters([effect], [card], [slot('one', 4), slot('two', 5)], catalog)[0]
    assert ambiguous.payload['standard']['value_expr']['kind'] == 'dynamic_hash'
    operation = {**payload['standard']['dynamic_operation'], 'destination_hash': '7'}
    writer = replace(effect, effect_id='writer', payload={**payload, 'standard': {
        **payload['standard'], 'dynamic_operation': operation}})
    unchanged = _bind_definition_constant_parameters([effect, writer], [card], [slot('one', 4)], catalog)[0]
    assert unchanged.payload['standard']['value_expr']['kind'] == 'dynamic_hash'


def test_target_character_identity_reads_the_formal_unit_not_an_event_payload():
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    from hsr.simulator_v8_clean_core.rules.ir import CombatantActionSetIR
    from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state
    source = IRSource('fixture:unit-identity', 'Component', 'identity')
    raw = {'$type': 'RPG.GameCore.SetDynamicValueByVariateType', 'DynamicKey': 'identity',
           'VariateType': 'TargetCharacterID',
           'ReadTargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'ParamEntity'}}
    payload = _effect_payload(raw, 'SetDynamicValueByVariateType', '', source=source)
    assert payload['standard']['dynamic_operation']['operand']['operand_kind'] == 'unit_identity'
    effect = EffectIR('identity', 'SetDynamicValueByVariateType', payload, source, 'executable')
    rules = RuleBook(CanonicalIR('unit-identity', effects=(effect,), combatant_action_sets=(
        CombatantActionSetIR('identity-card', 'avatar:91', {}, source, 'executable'),)))
    state = BattleState(units={
        'actor': UnitState('actor', 'ally', 'fixture:actor', hp=10, max_hp=10),
        'recipient': UnitState('recipient', 'ally', 'avatar:91', hp=10, max_hp=10),
    })
    context = EffectExecutionContext(state, 'actor', 'identity-call', owner_id='actor',
        ability_instance_id='identity:invocation', param_entity_id='recipient',
        event_payload={'operation_event_id': 'identity:1', 'TargetCharacterID': 999, 'character_id': 999})
    runtime = EffectRegistry(StatusSystem(rules))
    result = runtime.execute(effect, context)
    assert not result.unsupported, result.unsupported
    committed = MutationReducer().apply_all(state, result.mutations)
    assert next(iter(store_from_state(committed)['entries'].values()))['value'] == 91
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, audit.to_json()
    missing = runtime.execute(effect, replace(context, param_entity_id='absent'))
    assert missing.unsupported and not missing.mutations and not missing.rng_events


def test_native_effect_audit_proves_per_target_instantiation_not_its_label():
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    source = IRSource('fixture:target-binding', 'Component', 'bar')
    raw = {'$type': 'RPG.GameCore.SetEnergyBarState',
           'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
           'BarType': 7, 'CurrentCount': {'IsDynamic': False, 'FixedValue': {'Value': 2}}}
    payload = _effect_payload(raw, 'SetEnergyBarState', '', source=source)
    formal = EffectIR('bar', 'SetEnergyBarState', payload, source, 'executable')
    rules = RuleBook(CanonicalIR('native-target-binding', effects=(formal,)))
    bar = {'state': 'Normal', 'current_count': 1., 'max_count': 3.}
    state = BattleState(units={name: UnitState(name, 'ally', 'fixture:' + name, hp=10, max_hp=10,
        flags={'mechanism_bars': {'7': bar}}) for name in ('owner', 'other')})
    context = EffectExecutionContext(state, 'owner', 'bar-call', owner_id='owner',
        param_entity_id='owner', current_action_target_id='owner')
    runtime = EffectRegistry(StatusSystem(rules))
    instantiated = replace(formal, payload={**payload, 'standard': {**payload['standard'], 'target_alias': 'ParamEntity'}})
    for effect in (formal, instantiated):
        result = runtime.execute(effect, context)
        assert not result.unsupported, result.unsupported
        audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
        assert audit.ok, audit.to_json()
    wrong = runtime.execute(instantiated, replace(context, param_entity_id='other', current_action_target_id='other'))
    assert not wrong.unsupported
    assert not RuntimeSourceAuditor(rules).validate_execution(wrong.mutations, wrong.records).ok


def test_event_definition_reference_is_source_backed_empty_or_unique_never_first():
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.rules.ir import TargetExpressionIR
    from hsr.simulator_v8_clean_core.systems.target import TargetSystem
    from hsr.simulator_v8_clean_core.systems.unit_relation import TargetEvaluationContext
    from hsr.simulator_v8_clean_core.tbgd.target_source import _event_definition_aliases, close_target_expression_language
    from hsr.simulator_v8_clean_core.tbgd.lowering import _target_expression_from_raw, TBGDLowering
    definitions, fingerprints = _event_definition_aliases(_TBGD)
    definition = next(item for item in definitions if item.name == 'BattleEvent60021')
    assert definition.source.raw_type == 'BattleEventConfig' and definition.source.raw_id == '60021'
    assert 'ExcelOutput/BattleEventConfig.json' in fingerprints
    source = IRSource('Config/ConfigAbility/Avatar/Avatar_PlayerGirl_30_Ability.json', 'AbilityTask',
        'Avatar_PlayerGirl_30_Skill02_Phase02', {'json_path': '$.AbilityList[5].OnStart[4]'})
    raw = {'$type': 'RPG.GameCore.TargetAlias', 'Alias': definition.name}
    expression = close_target_expression_language(_target_expression_from_raw(
        raw, field_name='TargetType', expression_id='probe', source=source), definitions)
    assert expression.coverage_status == 'executable'
    rules = RuleBook(CanonicalIR('event-reference', target_expressions=(expression, *(item.expression for item in definitions))))
    runtime = TargetSystem(rules)
    state = BattleState(units={'actor': UnitState('actor', 'ally', 'avatar:probe', hp=10, max_hp=10)})
    context = TargetEvaluationContext(caster_id='actor')
    absent = runtime.resolve_target_expression(state, expression, context=context)
    assert absent.resolved and not absent.target_ids and not absent.rng_events
    event = UnitState('event', 'summon', 'battle_event:60021', hp=1, max_hp=1,
                      flags={'entity_type': 'battle_event', 'owner_id': 'actor', 'team_side': 'ally'})
    present = replace(state, units={**state.units, 'event': event})
    assert runtime.resolve_target_expression(present, expression, context=context).target_ids == ('event',)
    twin = replace(event, unit_id='twin')
    ambiguous = runtime.resolve_target_expression(replace(present, units={**present.units, 'twin': twin}), expression, context=context)
    assert ambiguous.blocked and ambiguous.blocked_reason == 'event_definition_reference_ambiguous'
    removed = replace(present, units={**state.units, 'event': replace(event, lifecycle_status='removed')})
    assert not runtime.resolve_target_expression(removed, expression, context=context).target_ids
    lowerer = TBGDLowering(_TBGD)
    predicate = {'$type': 'RPG.GameCore.ByIsTargetValid', 'TargetType': raw, 'AliveOnly': True}
    condition = lowerer._lower_ability_task_condition(predicate, source, 'probe')
    assert condition.coverage_status == 'executable', condition.to_json()
    unknown = lowerer._lower_ability_task_condition({**predicate, 'TargetType': {**raw, 'Alias': 'BattleEvent999999999'}}, source, 'unknown')
    assert unknown.coverage_status != 'executable' and unknown.payload['TargetType'].runtime_blocked_reason


def test_modifier_layer_absence_counts_actual_target_instances_not_foreign_context():
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, _modifier_value_for_condition
    unit = UnitState('owner', 'ally', 'avatar:probe', hp=10, max_hp=10)
    state = BattleState(units={'owner': unit})
    context = EvaluationContext(state=state, owner_id='other', status_detail={
        'owner_id': 'other', 'modifier_name': 'mark', 'stacks': 9})
    assert _modifier_value_for_condition(context, 'owner', 'mark', 'Layer') == (0., 'ok')
    assert _modifier_value_for_condition(context, 'missing', 'mark', 'Layer')[0] is None
    assert _modifier_value_for_condition(context, 'owner', 'mark', 'LifeTime')[0] is None
    def with_stacks(value):
        target = replace(unit, flags={'status_details': [{'modifier_name': 'mark', 'stacks': value}]})
        return replace(context, state=replace(state, units={'owner': target}))
    assert _modifier_value_for_condition(with_stacks(2), 'owner', 'mark', 'Layer') == (2., 'ok')
    assert _modifier_value_for_condition(with_stacks(True), 'owner', 'mark', 'Layer')[0] is None


def test_hp_change_values_require_the_actual_issued_event_and_mutation():
    import pytest
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.core.model import Mutation
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    from hsr.simulator_v8_clean_core.systems.mutation_events import events_for_mutation, native_hp_change_value
    source = IRSource('fixture:hp-listener', 'Component', 'hp-value')
    mutation = Mutation('set', ('units', 'owner', 'hp'), 10., 6., 'realized HP cost', 'effect_system')
    event = events_for_mutation(mutation, actor_id='owner', source_id='hp-cost')[0]
    assert native_hp_change_value(event) == (-4., '')
    heal = events_for_mutation(Mutation('set', ('units', 'owner', 'hp'), 6., 8.,
        'apply numeric heal effect', 'effect_system', metadata={'opcode': 'Heal'}),
        actor_id='owner', source_id='heal')[0]
    assert native_hp_change_value(heal) == (2., '')
    assert native_hp_change_value(replace(heal, heal_event_fact=None))[0] is None
    assert 'hp_change_event_fact' not in event.to_json()
    with pytest.raises(ValueError):
        replace(event.hp_change_event_fact, source_mutation=replace(mutation, before=100., after=96.))
    tampered = replace(event, payload={**event.payload, 'hp_change_amount': -99.})
    assert native_hp_change_value(tampered)[0] is None
    assert native_hp_change_value(replace(event, event_id='another-event'))[0] is None
    state = BattleState(units={'owner': UnitState('owner', 'ally', 'avatar:probe', hp=6, max_hp=10)})
    for opcode in ('SetDynamicValueByChangeValue', 'SetDynamicValueByVariateType'):
        raw = {'$type': 'RPG.GameCore.' + opcode, 'DynamicKey': 'real_delta'}
        if opcode == 'SetDynamicValueByVariateType':
            raw['VariateType'] = 'ParamValue'
        payload = _effect_payload(raw, opcode, '', source=source)
        effect = EffectIR('hp-value:' + opcode, opcode, payload, source, 'executable')
        rules = RuleBook(CanonicalIR('hp-value', effects=(effect,)))
        runtime = EffectRegistry(StatusSystem(rules))
        context = EffectExecutionContext(state, 'owner', 'callback', owner_id='owner',
            trigger_event=event, event_payload={**event.payload, 'event_id': event.event_id,
                'operation_event_id': event.event_id + ':callback', 'param_value': 999.})
        result = runtime.execute(effect, context)
        assert not result.unsupported, result.unsupported
        stores = [item.after for item in result.mutations if item.path[-1] == 'dynamic_value_store']
        assert len(stores) == 1 and next(iter(stores[0]['entries'].values()))['value'] == -4.
        assert RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records).ok
        for invalid in (replace(event, hp_change_event_fact=None), tampered):
            rejected = runtime.execute(effect, replace(context, trigger_event=invalid))
            assert rejected.unsupported and not rejected.mutations and not rejected.rng_events
    from hsr.simulator_v8_clean_core.rules.ir import ConditionIR
    from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator, EvaluationContext, CONDITION_EXPRESSION_NODE_SCHEMA
    from hsr.simulator_v8_clean_core.tbgd.lowering import _numeric_expr_summary
    condition = ConditionIR('hp-negative', 'ByCompareParamValue', {'CompareType': 'Less',
        'CompareValue': _numeric_expr_summary({'IsDynamic': False, 'FixedValue': {'Value': 0}})}, source, 'executable',
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)
    evaluator = RuleEvaluator()
    assert evaluator.evaluate_condition(condition, EvaluationContext(state=state, trigger_event=event,
        event_payload={'event_type': 'hp.change', 'param_value': 999.})) is True
    assert evaluator.evaluate_condition(condition, EvaluationContext(state=state,
        event_payload={'event_type': 'hp.change', 'param_value': -4.})) is None


def test_property_change_value_uses_the_actual_watcher_not_hp_or_transport():
    import pytest
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.core.model import Mutation
    from hsr.simulator_v8_clean_core.rules.ir import AbilityPropertyWatcherIR, AbilityPropertyRangeIR, StatusCallbackIR
    from hsr.simulator_v8_clean_core.systems.ability_property_watchers import AbilityPropertyWatcherSystem
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackExecutionResult
    from hsr.simulator_v8_clean_core.systems.mutation_events import events_for_mutation
    source = IRSource('fixture:property-watcher', 'Component', 'watcher')
    watcher = AbilityPropertyWatcherIR('watcher', 'marker', 'Speed', ('range',), source, coverage_status='executable')
    interval = AbilityPropertyRangeIR('range', 'watcher', 0, None, None, True, True, '', '', source,
        coverage_status='executable', change_callback_id='change')
    raw = {'$type': 'RPG.GameCore.SetDynamicValueByChangeValue', 'DynamicKey': 'difference'}
    payload = _effect_payload(raw, 'SetDynamicValueByChangeValue', '', source=source)
    effect = EffectIR('read-difference', 'SetDynamicValueByChangeValue', payload, source, 'executable')
    callback_source = IRSource(source.source_path, source.raw_type, source.raw_id, {
        'ability_property_watcher_id': 'watcher', 'ability_property_range_id': 'range',
        'ability_property_range_branch': 'OnChange'})
    callback = StatusCallbackIR('change', 'marker', 'OnAbilityPropertyChange', (), callback_source, (0, 0),
        coverage_status='executable', admission_status='executable', scope_kind='ability_property_range')
    rules = RuleBook(CanonicalIR('property-change', effects=(effect,), status_callbacks=(callback,),
        ability_property_watchers=(watcher,), ability_property_ranges=(interval,)))
    detail = {'instance_id': 'instance', 'status_id': 'status', 'modifier_name': 'marker', 'owner_id': 'owner',
              'caster_id': 'owner', 'source_id': 'marker-source', 'ability_property_watcher_ids': ['watcher'],
              'ability_property_watcher_state': {'watcher': ['range']}}
    unit = UnitState('owner', 'ally', 'avatar:probe', hp=10, max_hp=10, speed=100,
                     flags={'status_details': [detail]})
    before = BattleState(units={'owner': unit})
    after = replace(before, units={'owner': replace(unit, hp=6, speed=120)})
    event = events_for_mutation(Mutation('set', ('units', 'owner', 'hp'), 10., 6., 'cost', 'fixture'),
                                actor_id='owner', source_id='cost')[0]
    captured = []
    class Capture:
        def execute_callback_id(self, state, **kwargs):
            captured.append(kwargs['trigger_event'])
            return StatusCallbackExecutionResult(True, state)
    result = AbilityPropertyWatcherSystem(rules, status_callbacks=Capture()).reconcile(
        after, unit_ids=('owner',), trigger_event=event, before_state=before)
    assert result.ok, result.errors
    assert len(captured) == 1
    native = captured[0]
    fact = native.ability_property_change_fact
    assert fact.delta == 20 and fact.matches_event(native)
    with pytest.raises(ValueError):
        replace(fact, before=0., after=20.)
    runtime = EffectRegistry(StatusSystem(rules))
    context = EffectExecutionContext(after, 'owner', 'watcher', owner_id='owner', trigger_event=native,
        event_payload={**native.payload, 'event_id': native.event_id, 'operation_event_id': native.event_id + ':change'})
    read = runtime.execute(effect, context)
    assert not read.unsupported, read.unsupported
    store = next(item.after for item in read.mutations if item.path[-1] == 'dynamic_value_store')
    assert next(iter(store['entries'].values()))['value'] == 20
    rejected = runtime.execute(effect, replace(context, trigger_event=replace(native, ability_property_change_fact=None)))
    assert rejected.unsupported and not rejected.mutations


def test_existence_conditions_distinguish_resolved_empty_from_unknown_relationship():
    from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator
    from hsr.simulator_v8_clean_core.systems.target import TargetSystem
    from hsr.simulator_v8_clean_core.systems.unit_relation import TargetEvaluationContext
    source = IRSource('validation_fixture/empty-servant', 'Predicate', 'existence', {'json_path': '$.Predicate'})
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    lowerer = TBGDLowering(root)
    definitions = lowerer._strict_target_language_definitions()
    rules = RuleBook(CanonicalIR('empty-servant', target_expressions=tuple(item.expression for item in definitions)))
    targets = TargetSystem(rules)
    from hsr.simulator_v8_clean_core.systems.summon import _empty_runtime
    owner = UnitState('owner', 'ally', 'avatar:1', hp=10, max_hp=10)
    state = BattleState(units={'owner': owner}, global_flags={'summon_runtime': _empty_runtime()})
    for opcode in ('ByHaveEnemyAlive', 'ByIsContainModifier'):
        raw = {'$type': 'RPG.GameCore.' + opcode,
            'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'CasterServant'}}
        if opcode == 'ByIsContainModifier':raw['ModifierName'] = {'Value': 'marker'}
        condition = lowerer._lower_ability_task_condition(raw, source, opcode)
        context = targets.condition_evaluation_context(state, condition,
            context=TargetEvaluationContext('owner', effect_owner_id='owner'))
        assert not context.target_resolution_errors, context.target_resolution_errors
        assert RuleEvaluator().evaluate_condition(condition, context) is False
        assert RuleEvaluator().evaluate_condition(replace(condition, payload={**condition.payload, 'Inverse': True}), context) is True
        # No formal target resolver means an unknown relation, not proof of absence.
        assert RuleEvaluator().evaluate_condition(condition, EvaluationContext(state=state, actor_id='owner')) is None
    raw = {'$type': 'RPG.GameCore.ByHaveEnemyAlive',
        'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'}}
    condition = lowerer._lower_ability_task_condition(raw, source, 'team-presence')
    summon = UnitState('summon', 'summon', 'servant:2', hp=10, max_hp=10,
        flags={'owner_id': 'owner', 'team_side': 'ally', 'summon_kind': 'servant'})
    for opponent, expected in ((None, False), (UnitState('enemy', 'enemy', 'monster:3', hp=10), True),
                               (UnitState('enemy', 'enemy', 'monster:3', hp=10, lifecycle_status='limbo'), False)):
        units = {'owner': owner, 'summon': summon}
        if opponent is not None:units['enemy'] = opponent
        current = BattleState(units=units)
        context = targets.condition_evaluation_context(current, condition,
            context=TargetEvaluationContext('summon', effect_owner_id='owner'))
        assert RuleEvaluator().evaluate_condition(condition, context) is expected


def test_identity_comparison_reads_canonical_combatants_not_profile_flags():
    from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering
    from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator
    source = IRSource('validation_fixture/identity-condition', 'Predicate', 'identity', {'json_path': '$.Predicate'})
    raw = {'$type': 'RPG.GameCore.ByCompareCharacterID',
        'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
        'TargetCharacterID': {'IsDynamic': False, 'FixedValue': {'Value': 1415}}}
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    condition = TBGDLowering(root)._lower_ability_task_condition(raw, source, 'identity-condition')
    assert condition.coverage_status == 'executable', condition.to_json()
    for reference, expected in [('avatar:1415', True), ('servant:11415', False), ('monster:8011010', False),
                                ('fixture:unknown', None)]:
        unit = UnitState('turn', 'enemy', reference, flags={'character_id': 1415, 'avatar_id': 1415, 'profile_id': '1415'})
        state = BattleState(units={'turn': unit})
        result = RuleEvaluator().evaluate_condition(condition, EvaluationContext(state=state, actor_id='turn'))
        assert result is expected, (reference, result)


def test_critical_damage_conversion_is_an_independent_additive_bucket():
    from hsr.simulator_v8_clean_core.systems.status import _map_stack_property
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat, ability_property_value
    assert _map_stack_property('CriticalDamageConvert') == ('crit', 'critical_damage_convert', 'actor')
    unit = UnitState('owner', 'ally', 'avatar:probe', resources={'critical_damage': .5}, flags={
        'status_details': [{'instance_id': 'conversion', 'modifiers': [
            {'bucket': 'crit', 'key': 'critical_damage_convert', 'value': .3},
            {'bucket': 'crit', 'key': 'critical_damage', 'value': .2}]}]})
    assert effective_unit_stat(unit, 'critical_damage').value == 1.
    assert ability_property_value(unit, 'CriticalDamageConvert') == .3
    assert ability_property_value(unit, 'CriticalDamageBase') == .7
    assert effective_unit_stat(unit, 'critical_damage_convert').base_value == 0.


def test_skill_target_formation_presentation_extras_are_admitted():
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _process_only_ability_task_source_blocked_reason,
    )

    task = {
        '$type': 'RPG.GameCore.SetSkillTargetFormationByPos',
        'Team': 'TeamDark',
        'CustomTargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'AllDarkTeam'},
        'CustomCenterTargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
        'CenterOffset': {'X': 0, 'Y': 0, 'Z': 0.5},
        'CenterRootYaw': 180,
        'TargetFormation': {},
        'LeftSideFormations': [{'LocalDelta': {'X': 3, 'Y': 0, 'Z': 0}, 'Yaw': -30}],
        'RightSideFormations': [{'LocalDelta': {'X': -3.5, 'Y': 0, 'Z': 0}, 'Yaw': 20}],
    }
    assert _process_only_ability_task_source_blocked_reason(
        task, 'SetSkillTargetFormationByPos', action_id='avatar_skill:122202',
    ) == ''
    assert _process_only_ability_task_source_blocked_reason(
        {**task, 'CenterRootYaw': 'east'}, 'SetSkillTargetFormationByPos',
        action_id='avatar_skill:122202',
    )
    assert _process_only_ability_task_source_blocked_reason(
        {**task, 'UnknownLayout': 1}, 'SetSkillTargetFormationByPos',
        action_id='avatar_skill:122202',
    ) == 'process_only_task_unknown_fields:UnknownLayout'
    reset = {key: value for key, value in task.items() if key in
             {'$type', 'CustomTargetType', 'CustomCenterTargetType', 'TargetFormation'}}
    assert _process_only_ability_task_source_blocked_reason(reset, 'SetSkillTargetFormationByPos') == ''
    assert _process_only_ability_task_source_blocked_reason(
        {**reset, 'LeftSideFormations': [{'$type': 'RPG.GameCore.ModifySPNew'}]},
        'SetSkillTargetFormationByPos') == 'skill_target_formation_offset_shape_not_admitted'

def test_mechanism_bar_progress_display_and_dotted_relation_target_keep_source_shape():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _standard_mechanism_bar_payload

    task = {
        '$type': 'RPG.GameCore.SetSummonerEnergyBarState',
        'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster.GetSummoner'},
        'Active': 'True',
        'BarType': 'Progress',
        'MaxCount': {'IsDynamic': True, 'PostfixExpr': {'OpCodes': 'AQAR', 'FixedValues': [],
                                                        'DynamicHashes': [1283247492]}},
        'CurrentCount': {'IsDynamic': True, 'PostfixExpr': {'OpCodes': 'AQAR', 'FixedValues': [],
                                                            'DynamicHashes': [582796324]}},
        'ProgressBarTypeConfig': {'ProgressColor': '#6cd5ff'},
    }
    payload = _standard_mechanism_bar_payload(task, 'SetSummonerEnergyBarState')
    assert 'blocked_reason' not in payload
    assert payload['target_alias'] == 'Caster.GetSummoner'
    assert payload['raw_formula_fields']['ProgressBarTypeConfig'] == {'ProgressColor': '#6cd5ff'}
    for display in ({'ProgressColor': ''}, {'ProgressColor': 1},
                    {'ProgressColor': '#fff', 'FutureColor': '#000'}):
        blocked = _standard_mechanism_bar_payload(
            {**task, 'ProgressBarTypeConfig': display}, 'SetSummonerEnergyBarState')
        assert blocked['blocked_reason'] == 'mechanism_bar_progress_display_not_admitted'
    for alias in ('Caster.GetOwner', 'Unknown.GetSummoner', 'Caster.GetServant.Deep'):
        blocked = _standard_mechanism_bar_payload(
            {**task, 'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': alias}},
            'SetSummonerEnergyBarState')
        assert blocked['blocked_reason'] == 'mechanism_bar_target_not_admitted'

def test_temporary_lock_target_is_a_client_input_projection_not_a_combat_effect():
    from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _process_only_ability_task_source_blocked_reason,
    )

    assert ability_task_execution_mode('SetUseTemporaryLockTarget') == 'process_only'
    task = {
        '$type': 'RPG.GameCore.SetUseTemporaryLockTarget',
        'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
        'IsEnable': True,
    }
    assert _process_only_ability_task_source_blocked_reason(
        task, 'SetUseTemporaryLockTarget') == ''
    without_toggle = {key: value for key, value in task.items() if key != 'IsEnable'}
    assert _process_only_ability_task_source_blocked_reason(
        without_toggle, 'SetUseTemporaryLockTarget') == ''
    assert _process_only_ability_task_source_blocked_reason(
        {**task, 'FutureFlag': 1}, 'SetUseTemporaryLockTarget'
    ).startswith('process_only_task_unknown_fields')
    assert _process_only_ability_task_source_blocked_reason(
        {**task, 'IsEnable': 'yes'}, 'SetUseTemporaryLockTarget'
    ).startswith('process_only_task_field_invalid:IsEnable')
    assert _process_only_ability_task_source_blocked_reason(
        {**task, 'TargetType': 'Caster'}, 'SetUseTemporaryLockTarget'
    ).startswith('process_only_task_field_invalid:TargetType')

def test_camera_timeline_wait_is_presentation_not_a_combat_boundary():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_callback_presentation_only

    document = json.loads((_TBGD / 'Config/ConfigAbility/Avatar/Camera/Avatar_Cyrene_00_Camera.json').read_text())
    ability = next(item for item in document['AbilityList']
                   if item['Name'] == 'Avatar_Cyrene_00_Skill02_Camera')
    assert _status_callback_presentation_only(ability['OnStart'])
    assert any(task['$type'].endswith('WaitTimelineFinish') for task in ability['OnStart'])

def test_client_only_dynamic_value_is_presentation_for_every_action_kind():
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _process_only_ability_task_source_blocked_reason,
    )

    task = {
        '$type': 'RPG.GameCore.SetDynamicValueClientOnly',
        'Value': {'IsDynamic': False, 'FixedValue': {'Value': 1}},
        'DynamicKey': {'Value': '_CL_Is_S03_Ready'},
    }
    for action_id in ('avatar_skill:141303', 'servant_skill:1140901', ''):
        assert _process_only_ability_task_source_blocked_reason(
            task, 'SetDynamicValueClientOnly', action_id=action_id) == ''
    assert _process_only_ability_task_source_blocked_reason(
        {**task, 'Extra': 1}, 'SetDynamicValueClientOnly',
        action_id='avatar_skill:141303').startswith('client_only_dynamic_value')
    property_task = {
        '$type': 'RPG.GameCore.SetDynamicValueByPropertyClientOnly',
        'DynamicKey': 'MDF_PreShowHP',
        'ReadTargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
        'Value': 'MaxHP',
    }
    assert _process_only_ability_task_source_blocked_reason(
        property_task, 'SetDynamicValueByPropertyClientOnly',
        action_id='avatar_skill:141303') == ''


def test_set_modifier_value_without_value_type_uses_the_layer_default():
    source = IRSource(
        'Config/ConfigAbility/Avatar/Avatar_Evernight_00_Ability.json',
        'AbilityTask', 'Avatar_Evernight_00_Skill03_Phase02',
        {'json_path': '$.AbilityList[13].OnStart[5].SuccessTaskList[0]'},
    )
    raw = {
        '$type': 'RPG.GameCore.SetModifierValue',
        'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
        'ModifierName': {'Value': 'MAvatar_Evernight_00_UltraMode_Energy'},
        'ModifyFunction': 'Add',
        'Value': {'IsDynamic': True, 'PostfixExpr': {
            'OpCodes': 'AQAR', 'FixedValues': [], 'DynamicHashes': [1490816357]}},
    }
    payload = _effect_payload(
        raw, 'SetModifierValue', '', source=source,
        allow_implicit_modifier_layer=True,
    )
    standard = payload['standard']
    assert standard['blocked_reason'] == ''
    assert standard['value_kind'] == 'Layer'
    assert standard['adopted_rule_source']['behavior'] == 'layer count'
    lifetime = {**raw, 'ValueType': 'LifeTime'}
    lifetime_payload = _effect_payload(
        lifetime, 'SetModifierValue', '', source=source,
        allow_implicit_modifier_layer=True,
    )
    assert lifetime_payload['standard']['value_kind'] == 'LifeTime'
    unknown = {**raw, 'Extra': 1}
    assert _effect_payload(
        unknown, 'SetModifierValue', '', source=source,
        allow_implicit_modifier_layer=True,
    )['standard']['blocked_reason']


def test_hit_all_callback_stack_condition_requires_the_native_window_fact():
    from dataclasses import replace as _replace
    from hsr.simulator_v8_clean_core.core.model import ActionCommand, GameEvent
    from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, ConditionIR
    from hsr.simulator_v8_clean_core.rules.evaluator import (
        CONDITION_EXPRESSION_NODE_SCHEMA, EvaluationContext, RuleEvaluator,
    )
    from hsr.simulator_v8_clean_core.systems.action_event_contract import damage_listener_window_event
    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSourceFrame
    from hsr.simulator_v8_clean_core.systems.status_callbacks import _status_damage_window_event

    source = IRSource(
        'Config/ConfigAbility/Avatar/Avatar_Cyrene_00_Ability.json',
        'Predicate', 'MAvatar_Cyrene_00_Skill02_Buff',
        {'json_path': '$.GlobalModifiers.MAvatar_Cyrene_00_Skill02_Buff'},
    )
    condition = ConditionIR(
        'hit-all-stack', 'ByIsHitAllCallBackStack', {'Inverse': True},
        source, 'executable',
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )
    state = BattleState(units={
        'owner': UnitState('owner', 'ally', 'avatar:1415', hp=10, max_hp=10),
        'enemy': UnitState('enemy', 'enemy', 'fixture:enemy', hp=10, max_hp=10),
    })
    evaluator = RuleEvaluator()

    def evaluate(event, payload=None, checked=condition):
        return evaluator.evaluate_condition(checked, EvaluationContext(
            state=state, trigger_event=event,
            event_payload=event.payload if payload is None and event is not None else payload,
        ))

    action = ActionDefinitionIR('check:attack', 'check:attack', 1, 'Normal', 'SingleAttack', 'single',
        0, 0, 0, 0, (), (), (), None, IRSource('fixture', 'action', 'attack'))
    command = ActionCommand(actor_id='owner', action_id=action.action_id, action_level=1, target_ids=('enemy',))
    outer = damage_listener_window_event(state, command, action, event_type='damage.hit_sequence.after',
        target_id='enemy', selected_target_ids=('enemy',), primary_target_id='enemy',
        source_trace={}, sequence_id='task')
    # The outer native hit-all window is outside the stack, so the guard passes.
    assert evaluate(outer) is True
    # A hit window produced inside the callback stack blocks re-entry.
    frame = DamageSourceFrame('owner', 'status_damage:fixture', 'status_direct_damage', 'sequence', 'enemy')
    packet = DamagePacket('owner', 'enemy', 'Normal', 'direct', source_frame=frame, source_task_id='task')
    nested = _status_damage_window_event(state, packet, 'damage.hit_sequence.after', '', 1,
                                         hit_all_callback_stack=True)
    assert evaluate(nested) is False
    # A dispatcher payload copy on the same event keeps the native binding.
    assert evaluate(_replace(outer, payload={**outer.payload, 'mutation_event_depth': 1})) is True

    # No producer, a changed transport value or a misplaced event are all rejected.
    tampered = {**outer.payload, 'hit_all_callback_stack': True}
    cleared = {key: value for key, value in nested.payload.items() if key != 'hit_all_callback_stack'}
    for event, payload in (
        (None, {}),
        (None, {'hit_all_callback_stack': True}),
        (GameEvent(outer.event_type, source_id='owner', target_id='enemy', event_id=outer.event_id,
                   window=outer.window, payload=dict(outer.payload)), None),
        (_replace(outer, payload=tampered), None),
        (outer, tampered),
        (_replace(nested, payload=cleared), None),
        (nested, {}),
        (_replace(outer, event_id='event:other'), None),
        (_replace(outer, target_id='owner'), None),
    ):
        assert evaluate(event, payload) is None, (event, payload)
    forged = _replace(condition, payload={'Inverse': True, 'HitAll': True})
    assert evaluate(outer, checked=forged) is None
    from hsr.simulator_v8_clean_core.tbgd.lowering import _condition_payload_executable
    assert _condition_payload_executable(
        'ByIsHitAllCallBackStack', {'Inverse': True}, local_aliases=frozenset())
    assert not _condition_payload_executable(
        'ByIsHitAllCallBackStack', {'HitAll': True}, local_aliases=frozenset())


def test_fight_finish_uses_combat_teams_and_lifecycle():
    from hsr.simulator_v8_clean_core.rules.evaluator import (
        CONDITION_EXPRESSION_NODE_SCHEMA, EvaluationContext, RuleEvaluator,
    )
    from hsr.simulator_v8_clean_core.rules.ir import ConditionIR

    def condition(payload):
        return ConditionIR('fight-finish', 'ByCheckFightFinish', payload,
            IRSource('component', 'condition', 'fight-finish'), 'executable',
            expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)

    owner = UnitState('owner', 'ally', 'avatar:fixture', hp=10, max_hp=10)
    servant = UnitState('servant', 'summon', 'servant:fixture', hp=10, max_hp=10,
                        flags={'owner_id': 'owner', 'summon_kind': 'servant', 'team_side': 'ally'})
    container = UnitState('level', 'neutral', 'system:level', hp=10, max_hp=10,
                          flags={'system_entity_kind': 'level'})
    event = UnitState('event', 'enemy', 'fixture:event', hp=10, max_hp=10,
                      flags={'entity_type': 'battle_event'})
    defeated = UnitState('enemy', 'enemy', 'monster:fixture', hp=0, max_hp=10,
                         lifecycle_status='defeated')
    alive = UnitState('enemy', 'enemy', 'monster:fixture', hp=10, max_hp=10)
    bystanders = {'owner': owner, 'servant': servant, 'level': container, 'event': event}

    def evaluate(enemy, payload=None, actor_id='owner'):
        result = RuleEvaluator().evaluate_condition_result(condition(payload or {}), EvaluationContext(
            state=BattleState(units={**bystanders, 'enemy': enemy}), actor_id=actor_id))
        assert result.ok, result.to_json()
        return result.result

    assert evaluate(defeated) is True
    assert evaluate(alive) is False
    assert evaluate(defeated, {'Inverse': True}) is False
    assert evaluate(alive, {'Inverse': True}) is True
    # A servant judges opposition through its own combat team as well.
    assert evaluate(alive, actor_id='servant') is False
    neutral = RuleEvaluator().evaluate_condition_result(condition({}), EvaluationContext(
        state=BattleState(units={**bystanders, 'enemy': alive}), actor_id='level'))
    assert not neutral.ok


def test_action_admission_reads_invocation_roles_not_audit_paths():
    from types import SimpleNamespace

    from hsr.simulator_v8_clean_core.systems.action_contract import _formal_action_task_graph_projection

    def projection(path, role):
        phase = SimpleNamespace(phase_id='phase', invocation_role=role,
                                source=IRSource(path, 'AbilityPhase', 'phase'))
        rules = SimpleNamespace(ability_phases_for_action=lambda *_: (phase,))
        return _formal_action_task_graph_projection(rules, 'action', 1, ())

    avatar = 'Config/ConfigAbility/Avatar/fixture.json'
    camera = 'Config/ConfigAbility/Camera/fixture.json'
    for role in ('build_startup', 'standalone_root', 'nested_only', 'unbound_definition'):
        ordinary = projection(avatar, role)
        assert ordinary.blocked_reasons, role
        assert projection(camera, role).blocked_reasons == ordinary.blocked_reasons, role
    # L0's formal presentation classification is what makes a camera phase inert.
    assert not projection(camera, 'non_gameplay_noop').blocked_reasons


def test_condition_context_aliases_close_only_for_their_typed_producers():
    from hsr.simulator_v8_clean_core.core.model import ActionCommand, GameEvent
    from hsr.simulator_v8_clean_core.rules.evaluator import (
        CONDITION_EXPRESSION_NODE_SCHEMA, RuleEvaluator,
    )
    from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, ConditionIR
    from hsr.simulator_v8_clean_core.systems.action_event_contract import damage_listener_window_event
    from hsr.simulator_v8_clean_core.systems.status import StatusInstance
    from hsr.simulator_v8_clean_core.systems.status_callbacks import _condition_context
    from hsr.simulator_v8_clean_core.systems.target import TargetSystem
    from hsr.simulator_v8_clean_core.tbgd.lowering import _typed_condition_payload
    from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions

    definitions = build_target_language_definitions(_TBGD)
    source = IRSource('Config/ConfigAbility/Equip/EquipmemtAbility.json', 'Predicate', 'context-alias',
                      {'json_path': '$.AbilityList[0].Predicate'})

    def node(alias):
        return _typed_condition_payload(
            'ByIsTargetValid',
            {'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': alias}},
            source=source, target_language_definitions=definitions,
        )['TargetType']

    for alias in ('DamageDefenderEntity', 'ParamEntity2'):
        assert node(alias).expression_kind == 'TargetAlias' and node(alias).alias == alias
    # Unknown aliases stay rejected by the same closure.
    assert node('FixtureUnknownAlias').expression_kind == 'TargetUnsupported'

    rules = RuleBook(CanonicalIR('context-alias', target_expressions=tuple(
        item.expression for item in definitions)))
    listener = StatusInstance('listener', 'modifier:listener', 'listener', 'owner', 'passive', 'owner').to_json()
    state = BattleState(units={
        'owner': UnitState('owner', 'ally', 'fixture:owner', hp=10, max_hp=10,
            statuses=(listener['status_id'],), flags={'status_details': [listener]}),
        'enemy': UnitState('enemy', 'enemy', 'fixture:enemy', hp=10, max_hp=10),
    })

    def resolve(alias, event):
        condition = ConditionIR('alias', 'ByIsTargetValid', {'TargetType': node(alias)}, source,
                                'executable', expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)
        context = _condition_context(rules, state, listener, event, condition=condition,
                                     targets=TargetSystem(rules))
        return condition, context

    action = ActionDefinitionIR('check:attack', 'check:attack', 1, 'Normal', 'SingleAttack', 'single',
        0, 0, 0, 0, (), (), (), None, IRSource('fixture', 'action', 'attack'))
    command = ActionCommand(actor_id='owner', action_id=action.action_id, action_level=1, target_ids=('enemy',))
    window = damage_listener_window_event(state, command, action, event_type='damage.hit_sequence.before',
        target_id='enemy', selected_target_ids=('enemy',), primary_target_id='enemy', source_trace={})
    condition, context = resolve('DamageDefenderEntity', window)
    assert tuple(context.resolved_target_groups.values()) == (('enemy',),)
    assert RuleEvaluator().evaluate_condition_result(condition, context).result is True

    defeat = GameEvent('unit.defeated', source_id='owner', target_id='enemy', event_id='event:defeat',
                       window='unit.defeated')
    _, context = resolve('ParamEntity2', defeat)
    assert tuple(context.resolved_target_groups.values()) == (('owner',),)

    # Without the producer the alias fails closed, and payload copies cannot stand in.
    forged = GameEvent('fixture.window', source_id='owner', target_id='enemy', event_id='event:forged',
                       window='fixture.window',
                       payload={'damage_defender_id': 'enemy', 'param_entity_2_id': 'enemy'})
    for alias in ('DamageDefenderEntity', 'ParamEntity2'):
        for event in (None, forged):
            condition, context = resolve(alias, event)
            assert context.target_resolution_errors and not context.resolved_target_groups
            assert not RuleEvaluator().evaluate_condition_result(condition, context).ok


def test_visual_effect_placement_flags_are_presentation_metadata():
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _process_only_ability_task_source_blocked_reason,
    )

    task = {
        '$type': 'RPG.GameCore.TriggerEffect',
        'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'AllTeamCenter'},
        'Flags': ['Field'],
        'EffectPath': 'Effects/Eff_Prefab/Eff_Avatar/Eff_Cyrene_00/Eff_Cyrene_00_BattleArea.prefab',
        'ForceSimulateImmediately': False,
    }
    assert _process_only_ability_task_source_blocked_reason(task, 'TriggerEffect') == ''
    for flags in ([], ['Field', 'Field'], 'Field', [1], ['']):
        reason = _process_only_ability_task_source_blocked_reason(
            {**task, 'Flags': flags}, 'TriggerEffect')
        assert reason.startswith('process_only_task_field_invalid:Flags'), reason


def test_sub_modifier_predicate_is_lowered_not_dropped():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _modifier_addition_effects

    gate = {'$type': 'RPG.GameCore.ByCompareDynamicValue', 'DynamicKey': {'Value': 'MDF_Gate'},
            'CompareType': 'Greater', 'CompareValue': {'IsDynamic': False, 'FixedValue': {'Value': 0}}}
    sub = {'Name': 'Child', 'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'ModifierOwnerEntity'},
           'IsHaloStatus': True, 'AliveOnly': 'False'}
    context = {'json_path': '$.GlobalModifiers.Parent'}

    def lower(raw):
        conditions = []
        effects, _ = _modifier_addition_effects(
            'Config/ConfigAbility/Avatar/fixture.json', 'GlobalModifiers', 'Parent',
            {'AdditionConfig': {'SubModifierList': [raw]}},
            source_context=context, conditions_out=conditions,
        )
        return effects[0], conditions

    gated, conditions = lower({**sub, 'Predicate': gate})
    assert [item.opcode for item in conditions] == ['ByCompareDynamicValue']
    assert gated.payload['standard']['addition_condition_id'] == conditions[0].condition_id
    plain, none = lower(sub)
    assert not none and 'addition_condition_id' not in plain.payload['standard']
    blocked, none = lower({**sub, 'Predicate': {'$type': 'RPG.GameCore.ByUnknownFixture'}})
    assert not none and blocked.coverage_status == 'blocked'


def test_set_action_delay_admits_only_positive_fixed_normalized_values():
    source = IRSource('fixture', 'AbilityTask', 'delay')

    def payload(value, **extra):
        return _effect_payload({
            '$type': 'RPG.GameCore.SetActionDelay',
            'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
            'NormalizedValue': {'IsDynamic': False, 'FixedValue': {'Value': value}}, **extra,
        }, 'SetActionDelay', '', source=source)

    one = payload(1)
    assert one['standard']['operation'] == 'set_action_delay_normalized'
    assert _effect_coverage_status('SetActionDelay', one) == 'executable'
    assert payload(0)['standard']['operation'] == 'set_action_delay_zero'
    assert _effect_coverage_status('SetActionDelay', payload(-1)) == 'blocked'
    assert _effect_coverage_status('SetActionDelay', payload(1, Unknown=1)) == 'blocked'


def test_target_validity_means_existence_not_selectability():
    from hsr.simulator_v8_clean_core.rules.evaluator import (
        CONDITION_EXPRESSION_NODE_SCHEMA, EvaluationContext, RuleEvaluator,
    )
    from hsr.simulator_v8_clean_core.rules.ir import ConditionIR

    state = BattleState(units={
        'event': UnitState('event', 'summon', 'battle_event:1', hp=1, max_hp=1,
                           flags={'entity_type': 'battle_event', 'target_unselectable': True}),
        'gone': UnitState('gone', 'summon', 'battle_event:2', hp=1, max_hp=1,
                          lifecycle_status='removed', flags={'entity_type': 'battle_event'}),
    })

    def valid(unit_id):
        key = 'target-node'
        condition = ConditionIR('valid', 'ByIsTargetValid', {'TargetType': {'Alias': key}},
            IRSource('component', 'condition', 'valid'), 'executable',
            expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)
        from hsr.simulator_v8_clean_core.rules.evaluator import _condition_target_key
        return RuleEvaluator().evaluate_condition_result(condition, EvaluationContext(
            state=state, actor_id=unit_id,
            resolved_target_groups={_condition_target_key({'Alias': key}): (unit_id,)},
        )).result

    assert valid('event') is True
    assert valid('gone') is False


def test_regarded_attack_type_is_a_typed_owner_flag():
    from hsr.simulator_v8_clean_core.unit_eligibility import runtime_regarded_attack_type

    source = IRSource('fixture', 'AbilityTask', 'regard')
    target = {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'ModifierOwnerEntity'}

    def payload(opcode, **fields):
        return _effect_payload({'$type': f'RPG.GameCore.{opcode}', 'TargetType': target, **fields},
                               opcode, '', source=source)

    add = payload('AddRegardAsAttackType', OriginalAttackType='Normal', RegardAttackType='Insert')
    clear = payload('ClearRegardAsAttackType', OriginalAttackType='Normal')
    assert _effect_coverage_status('AddRegardAsAttackType', add) == 'executable'
    assert _effect_coverage_status('ClearRegardAsAttackType', clear) == 'executable'
    assert _effect_coverage_status('AddRegardAsAttackType', payload(
        'AddRegardAsAttackType', OriginalAttackType='Normal', RegardAttackType='Fixture')) == 'blocked'

    rules = RuleBook(CanonicalIR('regard'))
    state = BattleState(units={'owner': UnitState('owner', 'ally', 'fixture:owner', hp=1, max_hp=1)})
    registry = EffectRegistry(StatusSystem(rules))
    effect = EffectIR('add', 'AddRegardAsAttackType', add, source, 'executable')
    result = registry.execute(effect, EffectExecutionContext(state, 'owner', 'add', owner_id='owner'))
    assert not result.unsupported and result.mutations[0].after == {'Normal': 'Insert'}
    flagged = UnitState('owner', 'ally', 'fixture:owner', hp=1, max_hp=1,
                        flags={'regard_attack_types': {'Normal': 'Insert'}})
    assert runtime_regarded_attack_type(flagged, 'Normal') == 'Insert'
    assert runtime_regarded_attack_type(flagged, 'Ultra') == 'Ultra'
    assert runtime_regarded_attack_type(None, 'Normal') == 'Normal'


def test_omitted_stacking_replaces_only_within_one_caster():
    from hsr.simulator_v8_clean_core.systems.status import _replacement_status_detail

    mine = {'status_id': 'modifier:m', 'caster_id': 'a'}
    assert _replacement_status_detail([mine], status_id='modifier:m', stacking='', caster_id='a') is mine
    assert _replacement_status_detail([mine], status_id='modifier:m', stacking='', caster_id='b') is None
    assert _replacement_status_detail([mine], status_id='modifier:m', stacking='Multiple', caster_id='a') is None


def test_stance_column_binding_requires_the_raw_operand_of_the_only_column():
    from types import SimpleNamespace

    from hsr.simulator_v8_clean_core.tbgd.lowering import _stance_expr

    definition = SimpleNamespace(
        show_stance_list=({'Value': 15}, {'Value': 0}, {'Value': 0}), target_mode='random',
        source=IRSource('ExcelOutput/AvatarSkillConfig.json', 'AvatarSkillConfig', '1'),
    )
    bound = _stance_expr(definition, 'selected', raw_stance_hash='1659254037')
    assert bound['value'] == 15 and bound['source_kind'] == 'adopted_fixed_skill_toughness'
    for wrong in ('1182064154', '999', ''):
        assert _stance_expr(definition, 'selected', raw_stance_hash=wrong).get('source_kind') != (
            'adopted_fixed_skill_toughness')


def test_nested_graph_noop_result_is_explicit():
    import pytest
    from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphGraphResult

    assert TaskGraphGraphResult('resolved', 'definition', noop=True).graph is None
    with pytest.raises(ValueError):
        TaskGraphGraphResult('resolved', 'definition')


def test_ability_target_group_is_the_selected_target_set():
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        DAMAGE_EMISSION_TARGET_ALIASES,
        _damage_emission_target_group_blocked_reason,
        _standalone_target_group,
    )

    assert "AbilityTargetGroup" in DAMAGE_EMISSION_TARGET_ALIASES
    assert _standalone_target_group("AbilityTargetGroup") == "selected"
    assert _damage_emission_target_group_blocked_reason("AbilityTargetGroup", "selected") == ""
    assert _damage_emission_target_group_blocked_reason("AbilityTargetGroup", "primary")


def test_near_target_order_breaks_only_ties_with_its_anchor():
    from hsr.simulator_v8_clean_core.systems.timeline import _near_target_yields

    after = {'near_type': 'After', 'anchor_id': 'owner'}
    state = BattleState(units={
        'owner': UnitState('owner', 'ally', 'avatar:owner', hp=10, max_hp=10),
        'dragon': UnitState('dragon', 'summon', 'servant:dragon', hp=10, max_hp=10,
                            flags={'timeline_near_target': after}),
        'enemy': UnitState('enemy', 'enemy', 'monster:enemy', hp=10, max_hp=10),
    })
    assert _near_target_yields(state, 'dragon', {'owner', 'dragon'})
    assert not _near_target_yields(state, 'owner', {'owner', 'dragon'})
    # Without its anchor in the tie the order says nothing.
    assert not _near_target_yields(state, 'dragon', {'dragon', 'enemy'})


def test_ability_scoped_reads_prefer_the_current_ability_instance():
    from hsr.simulator_v8_clean_core.rules.evaluator import _scope_filtered_binding_sources

    source = {'source_type': 'dynamic_value_store', 'entries': {
        'a': {'scope': 'ability', 'hash': '7', 'name': 'slot', 'value': 0.0},
        'u': {'scope': 'unit', 'hash': '7', 'name': 'slot', 'value': 49.0},
    }, 'by_hash': {'7': ['a', 'u']}, 'by_name': {'slot': ['a', 'u']}}
    (scoped,) = _scope_filtered_binding_sources((source,), 'ContextTaskTemplate')
    assert set(scoped['entries']) == {'a'} and scoped['by_hash'] == {'7': ['a']}
    # Other scopes keep every committed source untouched.
    assert _scope_filtered_binding_sources((source,), 'TargetEntity') == (source,)


def test_client_only_predicate_with_presentation_subtree_is_presentation():
    from dataclasses import replace as _replace
    from hsr.simulator_v8_clean_core.rules.ir import StatusCallbackTaskIR
    from hsr.simulator_v8_clean_core.tbgd.lowering import _retire_client_only_presentation_predicates

    source = IRSource('fixture:client-only', 'Component', 'branch')
    base = StatusCallbackTaskIR('root', 'cb', 'M', 'OnStack', 0, 'P', 'root', 'PredicateTaskList', source,
                                coverage_status='blocked',
                                blocked_reason='condition_not_executable:unsupported:ByIsAutoBattle')
    child = _replace(base, task_id='child', opcode='SetTargetAlwaysAutoBattle', task_path='P.formal_branch[0].child[0]',
                     blocked_reason='source_proven_presentation_only')
    tasks = [base, child]
    _retire_client_only_presentation_predicates(tasks)
    assert tasks[0].blocked_reason == 'source_proven_presentation_only'
    gameplay = [base, _replace(child, blocked_reason='', coverage_status='executable', opcode='AddModifier')]
    _retire_client_only_presentation_predicates(gameplay)
    assert gameplay[0].blocked_reason.startswith('condition_not_executable')


def test_team_scoped_unselectable_hides_only_from_that_team():
    from hsr.simulator_v8_clean_core.unit_eligibility import (
        runtime_unit_is_unselectable, runtime_unit_is_unselectable_for,
    )

    source = IRSource('fixture:servant', 'AbilityTask', 'Unselectable')
    raw = {'$type': 'RPG.GameCore.StackCustomUnselectable', 'TeamTypes': 'TeamDark'}
    payload = _effect_payload(raw, 'StackCustomUnselectable', '', source=source)
    assert _effect_coverage_status('StackCustomUnselectable', payload) == 'executable'
    conditioned = {**raw, 'Condition': {'$type': 'RPG.GameCore.ByIsContainModifier'}}
    assert _effect_coverage_status(
        'StackCustomUnselectable', _effect_payload(conditioned, 'StackCustomUnselectable', '', source=source),
    ) == 'blocked'
    rules = RuleBook(CanonicalIR('custom-unselectable'))
    state = BattleState(units={'dragon': UnitState('dragon', 'summon', 'servant:dragon', hp=10, max_hp=10)})
    effect = EffectIR('effect', 'StackCustomUnselectable', payload, source, 'executable')
    result = EffectRegistry(StatusSystem(rules)).execute(
        effect, EffectExecutionContext(state, 'dragon', 'effect', owner_id='dragon'),
    )
    assert not result.unsupported and result.records
    dragon = UnitState('dragon', 'summon', 'servant:dragon', hp=10, max_hp=10,
                       flags={'team_side': 'ally', 'custom_unselectable_teams': ['TeamDark']})
    enemy = UnitState('enemy', 'enemy', 'monster:enemy', hp=10, max_hp=10)
    ally = UnitState('ally', 'ally', 'avatar:ally', hp=10, max_hp=10)
    assert runtime_unit_is_unselectable_for(dragon, enemy)
    assert not runtime_unit_is_unselectable_for(dragon, ally)
    assert not runtime_unit_is_unselectable(dragon)


def test_reinit_property_replaces_base_and_locks_component_bounds():
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat

    unit = UnitState('dragon', 'summon', 'servant:dragon', hp=10, max_hp=100, flags={'property_reinit': {
        'BaseHP': {'stat': 'max_hp', 'component': 'base_value', 'value': 500.0, 'min': None, 'max': None},
        'HPAddedRatio': {'stat': 'max_hp', 'component': 'ratio', 'value': 0.0, 'min': 0.0, 'max': 0.0},
    }})
    stat = effective_unit_stat(unit, 'max_hp')
    assert stat.base_value == 500.0 and stat.value == 500.0


def test_idempotent_set_hp_returns_one_settlement_record():
    source = IRSource('fixture:set-hp', 'AbilityTask', 'SetHP')
    payload = {'standard': {'target_alias': 'Caster', 'amount': {'kind': 'fixed', 'value': 10.0}}}
    rules = RuleBook(CanonicalIR('set-hp'))
    state = BattleState(units={'actor': UnitState('actor', 'ally', 'fixture:actor', hp=10, max_hp=10)})
    effect = EffectIR('effect', 'SetHP', payload, source, 'executable')
    result = EffectRegistry(StatusSystem(rules)).execute(effect, EffectExecutionContext(state, 'actor', 'effect'))
    assert not result.unsupported and not result.mutations
    assert len(result.records) == 1 and isinstance(result.records[0], dict)


def test_document_presentation_scope_removes_keys_read_by_gameplay():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _document_presentation_scope
    effect = {'$type': 'RPG.GameCore.TriggerEffect', 'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
              'EffectPath': 'fx.prefab'}

    def write(key, scope=None):
        return {'$type': 'RPG.GameCore.SetDynamicValue', 'DynamicKey': {'Value': key},
                'Value': {'IsDynamic': False, 'FixedValue': {'Value': 1}},
                **({'ContextScope': scope} if scope else {})}

    data = {'AbilityList': [
        {'Name': 'Visual', 'TargetInfo': {'TargetType': 'Caster'},
         'OnStart': [write('#CL_Flag'), write('Local', 'ContextTaskTemplate'), effect]},
        {'Name': 'Leaky', 'TargetInfo': {'TargetType': 'Caster'}, 'OnStart': [write('Shared'), effect]},
        {'Name': 'Gameplay', 'TargetInfo': {'TargetType': 'Caster'}, 'OnStart': [
            {'$type': 'RPG.GameCore.ModifySP', 'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
             'ModifyValue': {'IsDynamic': True, 'PostfixExpr': {'OpCodes': 'AQAR', 'FixedValues': [], 'DynamicHashes': [
                 __import__('hsr.simulator_v8_clean_core.dynamic_key_hash', fromlist=['x']).tbgd_dynamic_key_hash('Shared')]}}}]},
    ]}
    scope = _document_presentation_scope(data, camera_ability_names=frozenset(),
                                         externally_referenced_keys=lambda keys: frozenset())
    assert 'Visual' in scope.abilities and {'#CL_Flag', 'Local'} <= scope.dynamic_keys
    # A key read by a gameplay task keeps its writer gameplay.
    assert 'Shared' not in scope.dynamic_keys and 'Leaky' not in scope.abilities
    assert 'Gameplay' not in scope.abilities
    # A persistent key named by another document is never presentation-local.
    external = _document_presentation_scope(
        {'AbilityList': [{'Name': 'Leaky', 'TargetInfo': {'TargetType': 'Caster'}, 'OnStart': [write('Other'), effect]}]},
        camera_ability_names=frozenset(), externally_referenced_keys=lambda keys: frozenset(keys))
    assert 'Leaky' not in external.abilities


def test_character_id_group_condition_reads_the_compiled_group_or_blocks():
    from hsr.simulator_v8_clean_core.rules.evaluator import (
        CONDITION_EXPRESSION_NODE_SCHEMA, EvaluationContext, RuleEvaluator,
    )
    from hsr.simulator_v8_clean_core.rules.ir import ConditionIR
    from hsr.simulator_v8_clean_core.tbgd.lowering import _character_id_groups, _with_character_id_groups
    groups = _character_id_groups(_TBGD)
    assert 1415 in groups['Chrysos']['ids']
    raw = {'$type': 'RPG.GameCore.ByIsInCharacterIDGroup',
           'TargetType': {'alias': 'Caster'}, 'Group': 'Chrysos'}
    state = BattleState(units={
        'heir': UnitState('heir', 'ally', 'avatar:1415', hp=1, max_hp=1),
        'other': UnitState('other', 'ally', 'avatar:1105', hp=1, max_hp=1),
    })
    source = IRSource('fixture', 'Condition', 'group')

    def check(payload, actor):
        condition = ConditionIR('c', 'ByIsInCharacterIDGroup', payload, source, 'executable',
                                expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)
        return RuleEvaluator().evaluate_condition(condition, EvaluationContext(state=state, actor_id=actor))

    compiled = _with_character_id_groups(raw, groups)
    assert check(compiled, 'heir') is True
    assert check(compiled, 'other') is False
    assert check({**compiled, 'Inverse': True}, 'other') is True
    # Without the compiled group the condition fails closed.
    assert check(raw, 'heir') is None


def test_ability_scoped_dynamic_values_are_invisible_without_an_ability_instance():
    from hsr.simulator_v8_clean_core.systems.dynamic_values import binding_source_from_store, upsert_dynamic_value
    store = upsert_dynamic_value(None, scope='ability', owner_id='cy', value=1.0, value_name='_X', hash_key='7',
                                 ability_instance_id='ability_action:1')
    store = upsert_dynamic_value(store, scope='unit', owner_id='cy', value=2.0, value_name='_X', hash_key='7')
    assert len(binding_source_from_store(store, excluded_scopes=('ability',))['by_hash']['7']) == 1
    assert len(binding_source_from_store(store)['by_hash']['7']) == 2
