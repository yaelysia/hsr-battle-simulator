"""Source-bound passive battle events on the shared unit/status timeline."""
from __future__ import annotations

import math
from dataclasses import replace

from ..core.model import Mutation, UnitState, UnitStatPool
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from .dynamic_values import binding_source_from_store, store_from_state, upsert_dynamic_value
from .unit_lifecycle import UnitLifecycleSystem
from .unit_stats import effective_unit_stat
from .mutation_events import events_for_mutation


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
    owner = context.state.units.get(context.caster_id)
    if owner is None or not definition.get('phase_ids') or standard.get('blocked_reason'):
        return blocked('battle_event_create_definition_or_owner_missing')
    unit_id = f"{definition['entity_ref']}:{context.caster_id}:{context.state.event_index}:{len(context.state.units)}"
    store = store_from_state(context.state)
    for name, entry in standard.get('dynamic_values', {}).items():
        evaluated = _evaluate_numeric(effect, context, entry['expression'])
        if not evaluated.ok or type(evaluated.value) not in (int, float) or not math.isfinite(evaluated.value):
            return blocked('battle_event_parameter_unresolved:' + name)
        store = upsert_dynamic_value(store, scope='unit', owner_id=unit_id, value_name=name,
                                    hash_key=entry['hash'], value=float(evaluated.value), source_id=effect.effect_id,
                                    source_trace=effect.source.to_json())
    initial_speed = _evaluate_numeric(effect, replace(context, caster_id=unit_id, owner_id=unit_id,
        binding_sources=(binding_source_from_store(store, visible_scope={'target_id': unit_id}),)),
        definition.get('speed_expression', {}))
    if not initial_speed.ok or initial_speed.value is None or not math.isfinite(initial_speed.value) or initial_speed.value <= 0:
        return blocked(initial_speed.blocked_reason or 'battle_event_initial_speed_unresolved')
    # Event containers have no combat HP/DEF/energy. Positive schema HP only
    # keeps them alive for timeline scheduling; neutral allegiance excludes
    # them from teams, attacks and victory conditions.
    unit = UnitState(unit_id, 'summon', definition['entity_ref'], level=owner.level,
                     hp=1.0, max_hp=1.0, attack=float(definition.get('properties', {}).get('attack', 0)),
                     defense=0.0, speed=float(initial_speed.value), max_energy=0.0, action_value=0.0,
                     stat_pools=(UnitStatPool('speed', float(initial_speed.value)),),
                     flags={'entity_type': 'battle_event', 'timeline_admitted': True, 'owner_id': context.caster_id,
                            'summoner_id': context.caster_id, 'battle_event_team': standard['team'],
                            'battle_event_definition': definition, 'unselectable': True,
                            'status_produced_base_stats': ['speed'],
                            'battle_event_source': effect.source.to_json()})
    metadata = {'effect_id': effect.effect_id, 'opcode': effect.opcode, 'source_trace': effect.source.to_json()}
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
    dispatcher = EventDispatchSystem(rules, registry, reducer=reducer)
    abilities = AbilityTaskSystem(rules, registry, reducer=reducer, event_dispatcher=dispatcher)
    startup = abilities.execute_battle_event_startup(current, actor_id=unit_id,
                                                    phase_ids=tuple(definition['phase_ids']))
    failure = next((node for node in startup.node_results if node.status in {'blocked', 'unsupported'}), None)
    if failure is not None:
        return blocked(failure.reason_code or 'battle_event_startup_blocked')
    current = startup.after_state
    speed = effective_unit_stat(current.units[unit_id], 'speed').value
    rule, reason = rules.select_timeline_rule()
    if rule is None or not math.isfinite(speed) or speed <= 0:
        return blocked(reason or 'battle_event_initial_speed_not_positive')
    delay = TimelineSystem().set_action_value(current, unit_id, TimelineSystem().full_action_value(speed, rule),
                                             'battle_event_system', metadata)
    mutations.extend((*startup.mutations, delay))
    records = tuple(SettlementRecord('battle_event_birth', 'battle_event_system', mutation.stable_id(), False,
                                     {'unit_id': unit_id, 'entity_ref': definition['entity_ref']},
                                     effect.source.to_json()).to_json() for mutation in (spawn, bind, delay))
    return EffectResult(mutations=tuple(mutations),
                        events=(*events_for_mutation(spawn, actor_id=context.caster_id, source_id=effect.effect_id,
                                                     event_index=context.state.event_index), *startup.events),
                        rng_events=startup.rng_events, records=(*records, *startup.records),
                        dispatched_event_ids=startup.dispatched_event_ids or frozenset())
