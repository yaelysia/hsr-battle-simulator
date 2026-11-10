"""Source-bound battle events on the shared unit/status timeline."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..core.model import BattleState, Mutation, UnitState, UnitStatPool, freeze_json
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from .dynamic_values import binding_source_from_store, store_from_state, upsert_dynamic_value
from .unit_lifecycle import UnitLifecycleSystem
from .unit_stats import effective_unit_stat
from .mutation_events import events_for_mutation


if TYPE_CHECKING:
    from .effect import EffectExecutionContext, EffectResult


@dataclass(frozen=True)
class BattleEventExecutionFact:
    """Native invocation used only to audit event-container writes against IR."""

    effect_id: str
    context: EffectExecutionContext

    def __post_init__(self) -> None:
        from .effect import EffectExecutionContext

        if not self.effect_id or type(self.context) is not EffectExecutionContext:
            raise TypeError("battle event fact requires a formal effect invocation")
        context = self.context
        object.__setattr__(self, "context", replace(context,
            event_payload=freeze_json(context.event_payload) if context.event_payload is not None else None,
            dynamic_values=freeze_json(context.dynamic_values) if context.dynamic_values is not None else None,
            binding_sources=tuple(freeze_json(source) for source in context.binding_sources),
        ))


@dataclass(frozen=True)
class BattleEventRetirementFact:
    effect_id: str
    state: BattleState
    unit_id: str
    dependency_id: str

    def __post_init__(self) -> None:
        if (type(self.state) is not BattleState or not self.effect_id or not self.unit_id
                or not self.dependency_id):
            raise TypeError("event retirement requires a native dependency transition")


def bind_battle_event_fact(effect, context, result: EffectResult, *, source: str) -> EffectResult:
    if result.unsupported or not result.mutations:
        return result
    fact = BattleEventExecutionFact(effect.effect_id, context)
    return replace(result, mutations=tuple(
        replace(mutation, battle_event_fact=fact) if mutation.source == source else mutation
        for mutation in result.mutations
    ))


def _owner_skill_param_speed(
    rules: object,
    owner: UnitState | None,
    binding: dict[str, object],
) -> tuple[float | None, str]:
    """Resolve a speed parameter from the owner's selected skill levels."""

    trigger_key = str(binding.get("trigger_key") or "")
    param_index = binding.get("param_index")
    levels = owner.flags.get("effective_skill_levels_by_action_id") if owner is not None else None
    if (
        not isinstance(levels, dict)
        or not trigger_key
        or type(param_index) is not int
        or param_index < 0
    ):
        return None, "battle_event_owner_skill_param_context_missing"
    matches: list[float] = []
    for action_id, level in sorted(levels.items()):
        if type(level) is not int:
            continue
        action = rules.action_definition(str(action_id), level)
        if action is None or action.skill_trigger_key != trigger_key:
            continue
        params = action.param_list
        if param_index >= len(params):
            continue
        raw = params[param_index]
        value = raw.get("Value") if isinstance(raw, dict) else raw
        if type(value) in (int, float) and math.isfinite(float(value)):
            matches.append(float(value))
    if len(matches) != 1:
        return None, "battle_event_owner_skill_param_missing_or_ambiguous"
    value = matches[0]
    if value <= 0:
        return None, "battle_event_initial_speed_not_positive"
    return value, ""


def _resolve_initial_speed(
    rules: object,
    owner: UnitState | None,
    binding: dict[str, object],
    evaluated_values: dict[str, dict[str, object]],
) -> tuple[float | None, str]:
    kind = str(binding.get("kind") or "")
    if kind == "fixed":
        value = binding.get("value")
        if type(value) in (int, float) and math.isfinite(float(value)) and float(value) > 0:
            return float(value), ""
        return None, "battle_event_initial_speed_not_positive"
    if kind == "creation_parameter":
        entry = evaluated_values.get(str(binding.get("parameter_name") or ""))
        value = entry.get("value") if isinstance(entry, dict) else None
        if type(value) in (int, float) and math.isfinite(float(value)) and float(value) > 0:
            return float(value), ""
        return None, "battle_event_initial_speed_parameter_missing_or_nonpositive"
    if kind == "owner_skill_param":
        return _owner_skill_param_speed(rules, owner, binding)
    return None, ""


def _creation_target(effect, context, registry, field_name: str, alias_key: str):
    standard = effect.payload.get('standard', {})
    if not standard.get(alias_key):
        return context.caster_id, ''
    refs = standard.get('target_expression_refs', {})
    ref = refs.get(field_name) if isinstance(refs, dict) else None
    if not isinstance(ref, dict) or ref.get('coverage_status') != 'executable':
        return '', 'battle_event_creation_target_expression_not_admitted:' + field_name
    from .unit_relation import TargetEvaluationContext

    expression = registry.status_system.rules.target_expression(str(ref.get('target_expression_id') or ''))
    if expression is None:
        return '', 'battle_event_creation_target_expression_missing:' + field_name
    result = registry.targets.resolve_target_expression(
        context.state, expression,
        context=TargetEvaluationContext(
            caster_id=context.caster_id, effect_owner_id=context.owner_id,
            template_entity_ids=context.template_target_ids,
            parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
            selected_target_ids=context.target_resolution.selected if context.target_resolution else (),
            current_target_id=context.current_action_target_id,
            admitted_action_target_fact=context.admitted_action_target_fact,
            expected_action_window_scope=context.expected_action_window_scope,
        ),
        target_resolution=context.target_resolution, condition_event_payload=context.event_payload,
        binding_sources=context.binding_sources,
    )
    if not result.resolved or len(result.target_ids) != 1:
        return '', result.blocked_reason or 'battle_event_creation_target_not_unique:' + field_name
    target_id = result.target_ids[0]
    if target_id not in context.state.units:
        return '', 'battle_event_creation_target_missing:' + field_name
    return target_id, ''


@dataclass(frozen=True)
class _BattleEventPropertySync:
    attack: float | None
    defense: float | None
    resources: dict[str, float]
    values: dict[str, float]
    blocked_reason: str


def _resolve_battle_event_property_sync(
    state: BattleState,
    source_unit_id: str,
    policy: dict[str, object],
) -> _BattleEventPropertySync:
    """Copy declared final properties from the event's property source.

    Birth is the only sync point: the raw protocol exposes a separate
    `SyncBattleEventPropertyValues` operation for later re-copies, so the
    event owns its own immutable panel afterwards and no live alias is created.
    """

    from ..rules.battle_event_properties import battle_event_sync_property_target

    source_unit = state.units.get(source_unit_id)
    if source_unit is None:
        return _BattleEventPropertySync(None, None, {}, {}, "battle_event_property_source_missing")
    property_types = policy.get("runtime_property_types")
    if (
        not isinstance(property_types, (list, tuple))
        or any(not isinstance(item, str) or not item for item in property_types)
    ):
        return _BattleEventPropertySync(None, None, {}, {}, "battle_event_property_sync_policy_invalid")
    attack: float | None = None
    defense: float | None = None
    resources: dict[str, float] = {}
    values: dict[str, float] = {}
    for property_name in property_types:
        target = battle_event_sync_property_target(property_name)
        if target is None:
            return _BattleEventPropertySync(
                None, None, {}, {},
                f"battle_event_property_sync_type_not_admitted:{property_name}",
            )
        channel, runtime_key = target
        if channel == "final_attack":
            value = effective_unit_stat(source_unit, "attack").value
            if not math.isfinite(value):
                return _BattleEventPropertySync(None, None, {}, {}, "battle_event_property_source_attack_invalid")
            attack = float(value)
        elif channel == "effective_stat":
            value = effective_unit_stat(source_unit, runtime_key).value
            if not math.isfinite(value):
                return _BattleEventPropertySync(
                    None, None, {}, {},
                    f"battle_event_property_source_stat_invalid:{runtime_key}",
                )
            if runtime_key == "defense":
                defense = float(value)
            else:
                resources[runtime_key] = float(value)
        elif channel == "resource":
            raw = source_unit.resources.get(runtime_key, 0.0)
            if not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
                return _BattleEventPropertySync(
                    None, None, {}, {},
                    f"battle_event_property_source_resource_invalid:{runtime_key}",
                )
            value = float(raw)
            resources[runtime_key] = value
        else:
            return _BattleEventPropertySync(
                None, None, {}, {},
                f"battle_event_property_sync_channel_not_admitted:{channel}",
            )
        values[property_name] = float(value)
    return _BattleEventPropertySync(attack, defense, resources, values, "")


def create_battle_event(effect, context, registry):
    # Local imports keep the effect -> birth -> startup dependency acyclic.
    from .ability import AbilityTaskSystem
    from .effect import EffectResult, _evaluate_numeric, _unsupported_effect
    from .event_dispatch import EventDispatchSystem
    from .timeline import TimelineSystem

    def blocked(reason):
        return _unsupported_effect(effect, reason)

    if context is None or registry.status_system is None:
        return blocked('battle_event_create_context_missing')
    rules = registry.status_system.rules
    standard = effect.payload.get('standard', {})
    definition = standard.get('definition', {})
    if not isinstance(definition, dict):
        definition = {}
    owner = context.state.units.get(context.caster_id)
    if standard.get("blocked_reason"):
        return blocked(str(standard["blocked_reason"]))
    if (
        owner is None
        or not definition.get('phase_ids')
        or not definition.get('entity_ref')
    ):
        return blocked('battle_event_create_definition_or_owner_missing')
    property_overrides = definition.get("property_overrides", ())
    if (not isinstance(property_overrides, (list, tuple))
            or any(not isinstance(item, dict) for item in property_overrides)):
        return blocked("battle_event_property_declaration_invalid")
    property_sync_policy = definition.get("property_sync_policy") or {}
    if not isinstance(property_sync_policy, dict):
        return blocked("battle_event_property_sync_policy_invalid")
    declared_sync_types = property_sync_policy.get("declared_property_types") or ()
    if (not isinstance(declared_sync_types, (list, tuple))
            or any(not isinstance(item, str) or not item for item in declared_sync_types)):
        return blocked("battle_event_property_sync_policy_invalid")
    if (
        definition.get("actionable")
        and (
            declared_sync_types
            or definition.get("owner_sync_property_types")
            or definition.get("property_from_target_alias")
            or standard.get("property_from_target_alias")
            or any(
                item.get("property_type") != "BaseAttack"
                or item.get("value_present") is False
                for item in property_overrides
            )
        )
        and property_sync_policy.get("kind") != "birth_snapshot"
    ):
        # Legacy or hand-built IR that declares sync without a typed policy
        # cannot silently become a fixed-panel event.
        return blocked("battle_event_property_semantics_not_admitted")
    caster_id, capture_reason = _creation_target(
        effect, context, registry, 'SpecifyCaster', 'specify_caster_alias',
    )
    if capture_reason:
        return blocked(capture_reason)
    property_source_id = str(context.caster_id or "")
    if property_sync_policy.get("kind") == "birth_snapshot":
        if property_sync_policy.get("source") == "property_from_target":
            property_source_id, capture_reason = _creation_target(
                effect, context, registry, 'PropertyFromTarget', 'property_from_target_alias',
            )
            if capture_reason:
                return blocked(capture_reason)
        elif property_sync_policy.get("source") != "creator":
            return blocked("battle_event_property_source_kind_not_admitted")
        property_sync = _resolve_battle_event_property_sync(
            context.state, property_source_id, property_sync_policy,
        )
        if property_sync.blocked_reason:
            return blocked(property_sync.blocked_reason)
    else:
        property_sync = _BattleEventPropertySync(None, None, {}, {}, "")
    team = str(standard.get('team') or '')
    team_side = {'TeamLight': 'ally', 'TeamDark': 'enemy'}.get(team, 'neutral')
    unit_id = f"{definition['entity_ref']}:{context.caster_id}:{context.state.event_index}:{len(context.state.units)}"
    store = store_from_state(context.state)
    evaluated_values: dict[str, dict[str, object]] = {}
    for name, entry in standard.get('dynamic_values', {}).items():
        evaluated = _evaluate_numeric(effect, context, entry['expression'])
        if not evaluated.ok or type(evaluated.value) not in (int, float) or not math.isfinite(evaluated.value):
            return blocked('battle_event_parameter_unresolved:' + name)
        evaluated_values[name] = {'value': float(evaluated.value), 'hash': entry.get('hash')}
        store = upsert_dynamic_value(store, scope='unit', owner_id=unit_id, value_name=name,
                                    hash_key=entry['hash'], value=float(evaluated.value), source_id=effect.effect_id,
                                    source_trace=effect.source.to_json())
    speed_binding = (
        definition.get('speed_binding')
        if isinstance(definition.get('speed_binding'), dict)
        else {}
    )
    initial_speed, speed_reason = _resolve_initial_speed(
        rules, owner, speed_binding, evaluated_values,
    )
    if initial_speed is None and str(speed_binding.get('kind') or '') == 'dynamic_hash_expression':
        legacy = _evaluate_numeric(effect, replace(context, caster_id=unit_id, owner_id=unit_id,
            binding_sources=(binding_source_from_store(store, visible_scope={'target_id': unit_id}),)),
            speed_binding.get('expression', {}))
        if legacy.ok and legacy.value is not None and math.isfinite(float(legacy.value)) and float(legacy.value) > 0:
            initial_speed, speed_reason = float(legacy.value), ""
        else:
            speed_reason = legacy.blocked_reason or 'battle_event_initial_speed_unresolved'
    if initial_speed is None and not speed_binding:
        legacy = _evaluate_numeric(effect, replace(context, caster_id=unit_id, owner_id=unit_id,
            binding_sources=(binding_source_from_store(store, visible_scope={'target_id': unit_id}),)),
            definition.get('speed_expression', {}))
        if legacy.ok and legacy.value is not None and math.isfinite(float(legacy.value)) and float(legacy.value) > 0:
            initial_speed, speed_reason = float(legacy.value), ""
        else:
            speed_reason = legacy.blocked_reason or 'battle_event_initial_speed_unresolved'
    if initial_speed is None:
        return blocked(speed_reason or 'battle_event_initial_speed_binding_missing')
    timeline_admitted = definition.get('timeline_admitted') is not False and speed_binding != {}
    lifecycle_source = {
        'admission_status': 'executable',
        'presence': 'field',
        'targetable': False,
        'actionable': False,
        'timeline_admitted': bool(timeline_admitted),
        'owner_removed_policy': str(definition.get('owner_removed_policy') or 'remove'),
        'lifetime_policy': str(definition.get('lifetime_policy') or 'source_removal_or_owner_removed'),
        'source_trace': definition.get('lifecycle_source') or {},
    }
    # Event containers keep a nominal positive HP so the shared lifecycle keeps
    # them on field.  Their damage panel is the birth snapshot declared by the
    # source, not a fabricated copy of the owner's live panel.
    declared_attack = float((definition.get('properties') or {}).get('attack', 0) or 0)
    unit = UnitState(unit_id, 'summon', definition['entity_ref'], level=owner.level,
                     hp=1.0, max_hp=1.0,
                     attack=(
                         property_sync.attack
                         if property_sync.attack is not None
                         else declared_attack
                     ),
                     defense=(
                         property_sync.defense
                         if property_sync.defense is not None
                         else 0.0
                     ),
                     resources=dict(property_sync.resources),
                     speed=float(initial_speed), max_energy=0.0, action_value=0.0,
                     stat_pools=(UnitStatPool('speed', float(initial_speed)),),
                     flags={
                         'entity_type': 'battle_event',
                         'timeline_admitted': bool(timeline_admitted),
                         'owner_id': caster_id,
                         'summoner_id': caster_id,
                          'creation_source_unit_id': context.caster_id,
                          'battle_event_creation_effect_id': effect.effect_id,
                          'property_source_id': property_source_id,
                         'team_side': team_side,
                         'battle_event_team': standard['team'],
                         'battle_event_definition': definition,
                         'battle_event_kind': str(definition.get('battle_event_kind') or ''),
                         'battle_event_actionable': bool(definition.get('actionable')),
                         'battle_event_speed_binding': speed_binding,
                         'battle_event_lifecycle_source': lifecycle_source,
                         'lifecycle_source': lifecycle_source,
                         'specify_caster_alias': str(definition.get('specify_caster_alias') or ''),
                         'property_from_target_alias': str(definition.get('property_from_target_alias') or ''),
                         'unselectable': True,
                         'status_produced_base_stats': (
                             ['speed']
                             if definition.get('startup_produces_base_speed') is True
                             else []
                         ),
                         'battle_event_source': effect.source.to_json(),
                         'battle_event_property_sync': {
                             'kind': str(property_sync_policy.get('kind') or ''),
                             'source': str(property_sync_policy.get('source') or ''),
                             'source_unit_id': property_source_id,
                             'declared_property_types': [
                                 str(item) for item in property_sync_policy.get('declared_property_types') or ()
                             ],
                             'runtime_property_types': [
                                 str(item) for item in property_sync_policy.get('runtime_property_types') or ()
                             ],
                             'unsupported_declared_property_types': [
                                 str(item) for item in property_sync_policy.get('unsupported_declared_property_types') or ()
                             ],
                             'explicit_property_values': dict(
                                 property_sync_policy.get('explicit_property_values') or {}
                             ),
                             'resolved_values': dict(property_sync.values),
                             'source_trace': list(property_sync_policy.get('source_trace') or ()),
                         },
                     })
    metadata = {'effect_id': effect.effect_id, 'opcode': effect.opcode,
                'source_trace': effect.source.to_json(),
                'battle_event_kind': str(definition.get('battle_event_kind') or ''),
                'battle_event_speed_binding': speed_binding}
    spawn = UnitLifecycleSystem().spawn_mutation(context.state, unit, source='battle_event_system',
        reason='create source-bound battle event', source_trace=effect.source.to_json(), metadata=metadata)
    reducer = MutationReducer()
    current = reducer.apply_all(context.state, (spawn,))
    mutations = [spawn]
    bind = Mutation('set', ('global_flags', 'dynamic_value_store'), current.global_flags.get('dynamic_value_store'),
                    store, 'bind battle event birth parameters', 'battle_event_system',
                    before_exists='dynamic_value_store' in current.global_flags, metadata=metadata)
    current = reducer.apply_all(current, (bind,))
    mutations.append(bind)
    if timeline_admitted:
        rule, reason = rules.select_timeline_rule()
        if rule is None:
            return blocked(reason or 'battle_event_timeline_rule_missing')
        initial_delay = TimelineSystem().set_action_value(
            current, unit_id, TimelineSystem().full_action_value(initial_speed, rule),
            'battle_event_system', metadata,
        )
        current = reducer.apply_all(current, (initial_delay,))
        mutations.append(initial_delay)
    birth_mutations = tuple(mutations)
    dispatcher = EventDispatchSystem(rules, registry, reducer=reducer)
    abilities = AbilityTaskSystem(rules, registry, reducer=reducer, event_dispatcher=dispatcher)
    startup = abilities.execute_battle_event_startup(current, actor_id=unit_id,
                                                    phase_ids=tuple(definition['phase_ids']))
    failure = next((node for node in startup.node_results if node.status in {'blocked', 'unsupported'}), None)
    if failure is not None:
        return blocked(failure.reason_code or 'battle_event_startup_blocked')
    current = startup.after_state
    mutations.extend(startup.mutations)
    records = [SettlementRecord('battle_event_birth', 'battle_event_system', mutation.stable_id(), False,
                                {'unit_id': unit_id, 'entity_ref': definition['entity_ref'],
                                 'property_source_id': property_source_id,
                                 'property_sync_values': dict(property_sync.values)},
                                effect.source.to_json()).to_json() for mutation in birth_mutations]
    startup_wrote_action_value = any(
        mutation.path == ('units', unit_id, 'action_value')
        for mutation in startup.mutations
    )
    if timeline_admitted and not startup_wrote_action_value:
        speed = effective_unit_stat(current.units[unit_id], 'speed').value
        if not math.isfinite(speed) or speed <= 0:
            # A creation parameter or fixed source already established the
            # event's speed; an empty startup passive cannot replace it with
            # zero when the timeline entry is created.
            speed = float(initial_speed)
        rule, reason = rules.select_timeline_rule()
        if rule is None or not math.isfinite(speed) or speed <= 0:
            return blocked(reason or 'battle_event_initial_speed_not_positive')
        full_action_value = TimelineSystem().full_action_value(speed, rule)
        if current.units[unit_id].action_value != full_action_value:
            delay = TimelineSystem().set_action_value(
                current, unit_id, full_action_value, 'battle_event_system', metadata,
            )
            mutations.append(delay)
            records.append(SettlementRecord('battle_event_birth', 'battle_event_system', delay.stable_id(), False,
                                            {'unit_id': unit_id, 'entity_ref': definition['entity_ref']},
                                            effect.source.to_json()).to_json())
    return bind_battle_event_fact(effect, context, EffectResult(mutations=tuple(mutations),
                        events=(*events_for_mutation(spawn, actor_id=context.caster_id, source_id=effect.effect_id,
                                                     event_index=context.state.event_index), *startup.events),
                        rng_events=startup.rng_events, records=(*records, *startup.records),
                        dispatched_event_ids=startup.dispatched_event_ids or frozenset()),
                         source='battle_event_system')


def retire_battle_event(rules, state: BattleState, unit_id: str, dependency_id: str):
    """Retire one source-declared dependent container through existing domains.

    The declaration comes from the creating EffectIR, never from a source trace
    or a removed-record payload. Status OnDestroy runs before departure. The
    whole candidate (including callbacks and RNG) is discarded on any failure.
    """
    from .ability import AbilityTaskSystem
    from .dynamic_values import remove_unit_entries
    from .effect import EffectRegistry, EffectResult
    from .event_dispatch import EventDispatchSystem
    from .queue import QueueSystem
    from .status import StatusSystem

    def blocked(reason):
        return EffectResult(unsupported=(reason,))

    unit = state.units.get(unit_id)
    if unit is None or unit.flags.get('entity_type') != 'battle_event':
        return blocked('battle_event_retirement_unit_missing')
    if UnitLifecycleSystem().status_of(unit) == 'removed':
        return EffectResult()
    effect_id = str(unit.flags.get('battle_event_creation_effect_id') or '')
    effect = rules.effect(effect_id)
    if effect is None or effect.coverage_status != 'executable' or effect.opcode != 'CreateBattleEvent':
        return blocked('battle_event_retirement_creation_rule_missing')
    definition = effect.payload.get('standard', {}).get('definition', {})
    if definition.get('entity_ref') != unit.template_id:
        return blocked('battle_event_retirement_definition_mismatch')
    policy = definition.get('terminal_dependency_policy', {})
    if not policy:
        return EffectResult()  # Passive form timers use their explicit source callbacks.
    roles = policy.get('retire_on_terminal_dependency')
    if (policy.get('admission_status') != 'executable' or not isinstance(roles, (list, tuple))
            or not roles or any(role not in {'owner_id', 'creation_source_unit_id'} for role in roles)):
        return blocked('battle_event_terminal_dependency_policy_not_admitted')
    if dependency_id not in {unit.flags.get(role) for role in roles}:
        return EffectResult()
    dependency = state.units.get(dependency_id)
    if dependency is None or UnitLifecycleSystem().status_of(dependency) not in {'defeated', 'removed'}:
        return blocked('battle_event_dependency_not_terminal')
    trace = {'creation_effect': effect.source.to_json(), 'registered_lifecycle': policy.get('source', {})}
    reducer = MutationReducer()
    statuses = StatusSystem(rules)
    registry = EffectRegistry(statuses)
    dispatcher = EventDispatchSystem(rules, registry, reducer=reducer)
    # Install the same formal nested-ability transport used by ordinary dispatch.
    abilities = AbilityTaskSystem(rules, registry, reducer=reducer, event_dispatcher=dispatcher)
    current = state
    mutations, records, events, rng_events = [], [], [], []
    dispatched_ids = set()

    def apply(result, *, emit_events=True):
        nonlocal current
        reduced = reducer.apply_all_result(current, result.mutations)
        if not reduced.ok:
            raise ValueError('battle_event_retirement_reduction_failed')
        current = reduced.after_state
        mutations.extend(result.mutations)
        records.extend(result.records)
        if emit_events:
            events.extend(result.events)
        rng_events.extend(getattr(result, 'rng_events', ()))
        dispatched_ids.update(getattr(result, 'dispatched_event_ids', ()))

    try:
        details = tuple(unit.flags.get('status_details', ()))
        for detail in details:
            if not isinstance(detail, dict) or detail.get('lifecycle_state', 'active') not in {'active', 'active_partial'}:
                continue
            # Earlier OnDestroy callbacks may already remove or update a sibling
            # status. Consume the current exact instance, not its stale snapshot.
            detail = next((candidate for candidate in current.units[unit_id].flags.get('status_details', ())
                           if isinstance(candidate, dict)
                           and candidate.get('instance_id') == detail.get('instance_id')), None)
            if detail is None:
                continue
            removed = statuses.remove_status_instance(current, target_id=unit_id, detail=detail,
                source='battle_event_system', source_trace=trace)
            if not removed.ok:
                return blocked('battle_event_status_retirement_failed:' + ','.join(removed.unsupported))
            # Dispatch returns the canonical event itself. Do not also expose
            # its pre-normalization copy with the same identity to the ledger.
            apply(removed, emit_events=False)
            for event in removed.events:
                if event.event_id and event.event_id in dispatched_ids:
                    continue
                dispatched = dispatcher.dispatch_event(current, event=event)
                if dispatched.errors:
                    return blocked('battle_event_status_departure_callback_failed:' + ';'.join(dispatched.errors))
                apply(dispatched)
        metadata = {'effect_id': effect_id, 'unit_id': unit_id, 'dependency_id': dependency_id,
                    'source_trace': trace, 'retirement_operation': 'terminal_dependency'}
        removed_mutations = UnitLifecycleSystem().remove_mutations(
            current, unit_id, reason='source-declared companion dependency departed',
            source='battle_event_system', source_trace=trace, removed_record=metadata,
        )
        for mutation in removed_mutations:
            current = reducer.apply_all(current, (mutation,))
            mutations.append(mutation)
            records.append(SettlementRecord('battle_event_retirement', 'battle_event_system',
                mutation.stable_id(), False, mutation.metadata, trace).to_json())
            events.extend(events_for_mutation(mutation, actor_id=unit_id, source_id=effect_id,
                                              event_index=state.event_index))
        cleanup = remove_unit_entries(store_from_state(current), unit_id)
        if cleanup is not None:
            mutation = Mutation('set', ('global_flags', 'dynamic_value_store'),
                current.global_flags.get('dynamic_value_store'), cleanup,
                'retire departed event dynamic slots and operation ledger', 'battle_event_system',
                before_exists='dynamic_value_store' in current.global_flags, metadata=metadata)
            current = reducer.apply_all(current, (mutation,))
            mutations.append(mutation)
            records.append(SettlementRecord('battle_event_retirement', 'battle_event_system',
                mutation.stable_id(), False, mutation.metadata, trace).to_json())
        queue_mutations, queue_events, queue_records = QueueSystem().abort_unused_insert_entries_for_unit(
            current, unit_id, reason='queue_source_battle_event_retired', source_trace=trace,
            include_source_owned=True,
        )
        current = reducer.apply_all(current, queue_mutations)
        mutations.extend(queue_mutations)
        events.extend(queue_events)
        records.extend(queue_records)
        if current.global_flags.get('turn_owner_id') == unit_id:
            mutation = Mutation('delete', ('global_flags', 'turn_owner_id'), unit_id, None,
                'retire departed event turn ownership', 'battle_event_system',
                after_exists=False, metadata=metadata)
            current = reducer.apply_all(current, (mutation,))
            mutations.append(mutation)
            records.append(SettlementRecord('battle_event_retirement', 'battle_event_system',
                mutation.stable_id(), False, mutation.metadata, trace).to_json())
        halos = statuses.reconcile_halo_relations(current)
        if halos.unsupported:
            return blocked('battle_event_halo_retirement_failed:' + ';'.join(halos.unsupported))
        apply(halos)
    except (KeyError, TypeError, ValueError) as exc:
        return blocked('battle_event_retirement_invalid:' + str(exc))
    fact = BattleEventRetirementFact(effect_id, state, unit_id, dependency_id)
    return EffectResult(mutations=tuple(replace(mutation, battle_event_fact=fact) for mutation in mutations),
        events=tuple(events), records=tuple(records), rng_events=tuple(rng_events),
        dispatched_event_ids=frozenset(dispatched_ids))
