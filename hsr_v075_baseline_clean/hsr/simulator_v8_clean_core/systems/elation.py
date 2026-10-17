"""Shared Punchline accounting and source-bound per-hit Elation inputs."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..immutable_json import freeze_json, thaw_json
from ..rules.expression_ir import (
    DYNAMIC_VALUE_OPERATION_SCHEMA, NumericOperandIR, is_exact_numeric_expression, numeric_fixed,
)
from ..unit_eligibility import (
    runtime_unit_combat_team, runtime_unit_is_active,
)
from .mutation_events import mutation_backed_event_id
from .unit_stats import effective_unit_stat

if TYPE_CHECKING:
    from .damage import DamageModifierContribution


_SCHEMA = 'hsr.elation_runtime.v1'
# TBGD GameCoreConstValue.ElationPointMax; an absent battle counter starts at zero.
_MAX_POINTS = 9999
_AUTHORITY = object()


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validate_elation_runtime(value: object) -> str:
    """Return an empty string only for the canonical, serializable store."""
    if not isinstance(value, dict) or set(value) != {
        'schema_version', 'base_points', 'moments', 'active_moment_id', 'moment_sequence',
    } or value['schema_version'] != _SCHEMA:
        return 'elation_runtime_schema_invalid'
    moments = value['moments']
    if not _number(value['base_points']) or not 0 <= value['base_points'] <= _MAX_POINTS:
        return 'elation_runtime_base_points_invalid'
    if not isinstance(moments, dict) or type(value['moment_sequence']) is not int or value['moment_sequence'] < 0:
        return 'elation_runtime_moments_invalid'
    for identity, row in moments.items():
        if not isinstance(identity, str) or not identity or not isinstance(row, dict) or set(row) != {
            'scope_id', 'team', 'points', 'override_points', 'participant_ids', 'active', 'source_trace',
        }:
            return 'elation_moment_schema_invalid'
        participants = row['participant_ids']
        if (row['scope_id'] != identity or row['team'] not in ('ally', 'enemy')
                or type(row['active']) is not bool or not _number(row['points']) or row['points'] < 0
                or (row['override_points'] is not None and (
                    not _number(row['override_points']) or row['override_points'] < 0))
                or not isinstance(participants, list) or not participants
                or any(not isinstance(unit_id, str) or not unit_id for unit_id in participants)
                or len(participants) != len(set(participants)) or not isinstance(row['source_trace'], dict)
                or not row['source_trace']):
            return 'elation_moment_value_invalid'
    active = value['active_moment_id']
    if not isinstance(active, str) or (active and (active not in moments or not moments[active]['active'])):
        return 'elation_moment_active_identity_invalid'
    if tuple(key for key, row in moments.items() if row['active']) != ((active,) if active else ()):
        return 'elation_moment_active_scope_invalid'
    return ''


def _runtime(state: BattleState) -> dict:
    value = state.global_flags.get('elation_runtime')
    if value is None and 'elation_runtime' not in state.global_flags:
        return {'schema_version': _SCHEMA, 'base_points': 0., 'moments': {},
                'active_moment_id': '', 'moment_sequence': 0}
    reason = validate_elation_runtime(value)
    if reason:
        raise ValueError(reason)
    return thaw_json(value)


def _team(state: BattleState, actor_id: str) -> str:
    unit = state.units.get(actor_id)
    if unit is None:
        raise ValueError('elation_actor_missing')
    team = runtime_unit_combat_team(unit)
    if team == 'neutral':
        raise ValueError('elation_actor_combat_team_missing')
    return team


@dataclass(frozen=True, init=False)
class ElationDamageContext:
    actor_id: str
    points: float
    source_kind: Literal['echo', 'moment']
    scope_id: str
    source_terms: tuple
    _modifier_contributions: tuple[DamageModifierContribution, ...]
    _state: BattleState
    _authority: object

    def __init__(self, *_args, **_kwargs):
        raise TypeError('elation context must be produced from committed battle state')

    def blocked_reason(
        self, *, actor_id: str, state: BattleState | None = None,
        modifier_terms: tuple[dict[str, JSONValue], ...] | None = None,
    ) -> str:
        if type(self) is not ElationDamageContext or getattr(self, '_authority', None) is not _AUTHORITY:
            return 'elation_context_authority_invalid'
        if self.actor_id != actor_id:
            return 'elation_context_actor_mismatch'
        if not _number(self.points) or self.points < 0 or not self.scope_id or self.source_kind not in {'echo', 'moment'}:
            return 'elation_context_value_invalid'
        if state is None:
            return 'elation_context_state_missing'
        own_terms = tuple(item.formula_term() for item in self._modifier_contributions)
        if modifier_terms is not None and tuple(
            term for term in modifier_terms if term.get('bucket') in {'elation_bonus', 'elation_context'}
        ) != own_terms:
            return 'elation_context_modifier_mismatch'
        # Evaluated hit overrides are valid only at their immutable pre-hit boundary.
        if own_terms and state is not self._state:
            return 'elation_context_stale'
        try:
            expected = resolve_elation_damage_context(
                state, actor_id, point_source=self.source_kind,
                modifier_contributions=self._modifier_contributions,
            )
        except (TypeError, ValueError) as exc:
            return str(exc)
        if expected.to_json() != self.to_json():
            return 'elation_context_stale'
        return ''

    def to_json(self) -> dict[str, JSONValue]:
        return {'actor_id': self.actor_id, 'points': self.points, 'source_kind': self.source_kind,
                'scope_id': self.scope_id, 'source_terms': [thaw_json(term) for term in self.source_terms],
                'modifier_terms': [item.formula_term() for item in self._modifier_contributions]}


def resolve_elation_damage_context(
    state: BattleState, actor_id: str, *, point_source: Literal['echo', 'moment'],
    modifier_contributions: tuple[DamageModifierContribution, ...] = (),
) -> ElationDamageContext:
    """Produce N for this hit; a window boolean never supplies its tally.

    Adopted 4.0 piecewise rule: https://honkai-star-rail.fandom.com/wiki/Elation_DMG
    Direct moment damage uses its tally; indirect certified-banger damage uses
    the actor's echo even during a moment. The compiled emission selects one.
    """
    team = _team(state, actor_id)
    if point_source == 'echo':
        stat = effective_unit_stat(state.units[actor_id], 'elation_echo_point')
        points, scope_id = stat.value, f'unit:{actor_id}'
        terms = ({'base_value': stat.base_value, 'stat': stat.stat}, *stat.source_terms)
    elif point_source == 'moment':
        runtime = _runtime(state)
        scope_id = runtime['active_moment_id']
        row = runtime['moments'].get(scope_id)
        if (not isinstance(row, dict) or row['team'] != team or actor_id not in row['participant_ids']
                or state.global_flags.get('elation_time_active') is not True):
            raise ValueError('elation_moment_scope_missing_or_actor_not_admitted')
        points = row['override_points'] if row['override_points'] is not None else row['points']
        terms = ({'moment_id': scope_id, 'source_trace': row['source_trace'],
                  'accumulated_points': row['points'], 'override_points': row['override_points']},)
    else:
        raise ValueError('elation_point_source_not_admitted')
    if not _number(points) or points < 0:
        raise ValueError('elation_points_invalid')
    # Import at the consumer boundary: DamagePacket itself imports this context.
    from .damage import DamageModifierContribution

    relevant = []
    overrides: dict[str, float] = {}
    for contribution in modifier_contributions:
        if type(contribution) is not DamageModifierContribution:
            raise TypeError('elation_modifier_contribution_not_typed')
        term = contribution.formula_term()
        bucket, key = term.get('bucket'), term.get('key')
        if bucket not in {'elation_bonus', 'elation_context'}:
            continue
        if (bucket == 'elation_bonus' and key != 'elation_damage_added_ratio') or (
            bucket == 'elation_context' and key not in {'points', 'point_multiplier_enabled'}
        ):
            raise ValueError(f'elation_transient_modifier_not_admitted:{bucket}:{key}')
        relevant.append(contribution)
        if bucket == 'elation_context':
            if key in overrides and overrides[key] != contribution.value:
                raise ValueError(f'elation_context_override_conflict:{key}')
            overrides[key] = contribution.value
    if 'point_multiplier_enabled' in overrides and (
        overrides['point_multiplier_enabled'] != 0 or 'points' not in overrides
    ):
        raise ValueError('elation_point_multiplier_override_not_admitted')
    if 'points' in overrides:
        points = overrides['points']
        if points < 0:
            raise ValueError('elation_points_invalid')
    # The adopted Certified Banger formula uses the explicitly supplied N here;
    # native enable=0 with explicit N does not remove the final Punchline factor.
    # https://honkai-star-rail.fandom.com/wiki/Certified_Banger (4.0+, page version unspecified)
    if relevant:
        terms = (*terms, {'hit_modifier_terms': [item.formula_term() for item in relevant]})
    context = object.__new__(ElationDamageContext)
    for name, value in (('actor_id', actor_id), ('points', float(points)), ('source_kind', point_source),
                        ('scope_id', scope_id), ('source_terms', tuple(freeze_json(term) for term in terms)),
                        ('_modifier_contributions', tuple(relevant)), ('_state', state),
                        ('_authority', _AUTHORITY)):
        object.__setattr__(context, name, value)
    return context


def elation_effect_is_executable(effect) -> bool:
    standard = effect.payload.get('standard')
    if (effect.opcode != 'ElationOperation' or effect.coverage_status != 'executable'
            or not isinstance(standard, dict) or standard.get('kind') != 'elation' or standard.get('blocked_reason')):
        return False
    operation = standard.get('elation_operation')
    if operation in ('add_points', 'set_points'):
        return is_exact_numeric_expression(standard.get('amount_expr')) and standard.get('amount_expr', {}).get('supported') is True
    if operation not in ('read_points', 'convert_echo'):
        return False
    if not isinstance(standard.get('destination_dynamic_key'), str) or not standard['destination_dynamic_key']:
        return False
    if not isinstance(standard.get('destination_dynamic_hash'), str) or not standard['destination_dynamic_hash']:
        return False
    if standard.get('target_alias') not in ('Caster', 'ParamEntity', 'ModifierOwnerEntity', 'CurrentActionTarget'):
        return False
    if operation == 'read_points':
        return standard.get('point_type') in ('base', 'effective')
    return (standard.get('target_alias') == 'ModifierOwnerEntity'
            and standard.get('recipient_target_alias') in ('Caster', 'ParamEntity', 'ModifierOwnerEntity')
            and is_exact_numeric_expression(standard.get('amount_expr'))
            and standard.get('amount_expr', {}).get('supported') is True)


def _runtime_mutation(state: BattleState, runtime: dict, *, source: str, metadata: dict, reason: str) -> Mutation:
    invalid = validate_elation_runtime(runtime)
    if invalid:
        raise ValueError(invalid)
    return Mutation('set', ('global_flags', 'elation_runtime'), state.global_flags.get('elation_runtime'), runtime,
                    reason, source, before_exists='elation_runtime' in state.global_flags, metadata=metadata)


def elation_points_event_for_mutation(mutation: Mutation, *, actor_id: str = '', source_id: str = '') -> tuple[GameEvent, ...]:
    """The event is projected from the admitted store mutation, never vice versa."""
    if (mutation.path != ('global_flags', 'elation_runtime') or mutation.source != 'effect_system'
            or mutation.metadata.get('opcode') != 'ElationOperation'
            or mutation.metadata.get('elation_operation') not in ('add_points', 'set_points')
            or not isinstance(mutation.metadata.get('effect_source'), dict)
            or not mutation.metadata.get('effect_id')
            or validate_elation_runtime(mutation.after)):
        return ()
    before = mutation.before if mutation.before_exists else {
        'schema_version': _SCHEMA, 'base_points': 0., 'moments': {}, 'active_moment_id': '', 'moment_sequence': 0,
    }
    if validate_elation_runtime(before):
        return ()
    previous, current = before['base_points'], mutation.after['base_points']
    if previous == current:
        return ()
    caster = actor_id or str(mutation.metadata.get('caster_id') or '')
    return (GameEvent('elation.points.changed', source_id=source_id or caster,
        event_id=mutation_backed_event_id(mutation.stable_id(), 'elation.points.changed'),
        window='OnElationPointChange', payload={
            'callback_events': ['OnElationPointChange'], 'listener_scope': 'global_listener',
            'mutation_backed_event': True, 'mutation_id': mutation.stable_id(),
            'mutation_path': list(mutation.path), 'actor_id': caster, 'pool': 'battle',
            'before': previous, 'after': current, 'delta': current - previous,
            'source': mutation.source, 'source_trace': mutation.metadata['effect_source'],
        }),)


def elation_moment_mutation(state: BattleState, request, rule) -> Mutation:
    """Produce a formal window ledger beside its typed transition flag."""
    runtime = _runtime(state)
    starting = rule.after_value is True
    if starting:
        if runtime['active_moment_id']:
            raise ValueError('elation_moment_already_active')
        team = rule.participant_team or _team(state, request.actor_id)
        if team not in ('ally', 'enemy'):
            raise ValueError('elation_participant_team_not_admitted')
        override = request.elation_override_points
        if override is not None and (not _number(override) or override < 0):
            raise ValueError('elation_moment_override_invalid')
        # Keep only the latest completed window beside the active one; complete
        # historical snapshots already belong to settlement/replay.
        completed = tuple(runtime['moments'])
        runtime['moments'] = ({completed[-1]: runtime['moments'][completed[-1]]} if completed else {})
        runtime['moment_sequence'] += 1
        scope_id = f'elation:{team}:{runtime["moment_sequence"]}:{state.event_index}'
        participants = sorted(unit_id for unit_id, unit in state.units.items()
            if runtime_unit_combat_team(unit) == team and runtime_unit_is_active(unit))
        if not participants:
            raise ValueError('elation_moment_participants_missing')
        points = runtime['base_points']
        runtime['moments'][scope_id] = {'scope_id': scope_id, 'team': team, 'points': points,
            'override_points': override, 'participant_ids': participants, 'active': True,
            'source_trace': rule.source.to_json()}
        runtime['active_moment_id'] = scope_id
    else:
        scope_id = runtime['active_moment_id']
        if not scope_id:
            raise ValueError('elation_moment_end_scope_missing')
        runtime['moments'][scope_id]['active'] = False
        runtime['active_moment_id'] = ''
        runtime['moments'] = {scope_id: runtime['moments'][scope_id]}
    return _runtime_mutation(state, runtime, source='battle_state_transition_system',
        metadata={'battle_state_transition_rule_id': rule.transition_rule_id,
                  'trigger_kind': rule.trigger_kind, 'trigger_identity': rule.trigger_identity,
                  'runtime_event_type': rule.runtime_event_type, 'callback_event': rule.callback_event,
                  'source_trace': rule.source.to_json(),
                  'elation_operation': 'start_moment' if starting else 'end_moment'},
        reason='update formal Elation moment ledger')


def execute_elation_operation(state: BattleState, rules, effect, context):
    # The registry imports this module; use its existing typed dynamic planner
    # locally rather than introducing a second dynamic-value interpreter.
    from .effect import EffectResult, _evaluate_numeric, _execute_dynamic_value_operation, _effect_metadata, _resolve_target_alias

    if context is None or context.state != state or not elation_effect_is_executable(effect):
        return EffectResult(unsupported=('elation_operation_context_or_contract_invalid',))
    standard = effect.payload['standard']
    operation = standard['elation_operation']
    try:
        runtime = _runtime(state)
        if operation == 'read_points':
            value = runtime['base_points']
            moment = runtime['moments'].get(runtime['active_moment_id'])
            if standard['point_type'] == 'effective' and moment is not None:
                value = moment['override_points'] if moment['override_points'] is not None else moment['points']
        else:
            if operation == 'convert_echo':
                recipient_id = _resolve_target_alias(standard['recipient_target_alias'], caster_id=context.caster_id,
                    owner_id=context.owner_id, param_entity_id=context.param_entity_id,
                    current_action_target_id=context.current_action_target_id, target_resolution=context.target_resolution)
                if recipient_id not in state.units:
                    return EffectResult(unsupported=('elation_echo_recipient_missing',))
            evaluated = _evaluate_numeric(effect, context, standard['amount_expr'])
            if not evaluated.ok or not _number(evaluated.value):
                return EffectResult(unsupported=(evaluated.blocked_reason or 'elation_amount_unresolved',))
            value = float(evaluated.value)
        if operation in {'add_points', 'set_points'}:
            before = runtime['base_points']
            after = min(_MAX_POINTS, max(0., before + value if operation == 'add_points' else value))
            runtime['base_points'] = after
            moment = runtime['moments'].get(runtime['active_moment_id'])
            if moment is not None:
                moment['points'] = after
            metadata = _effect_metadata(effect, context, standard, value, evaluated)
            metadata['elation_operation'] = operation
            mutation = _runtime_mutation(state, runtime, source='effect_system', metadata=metadata,
                                         reason='apply canonical Punchline operation')
            record = SettlementRecord('elation_points', 'effect_system', mutation.stable_id(), False,
                {'pool': 'battle', 'operation': operation, 'before': before, 'after': after}, effect.source.to_json())
            events = elation_points_event_for_mutation(mutation, actor_id=context.caster_id, source_id=context.source_id)
            return EffectResult(mutations=(mutation,), events=events, records=(record.to_json(),))
        if value < 0:
            return EffectResult(unsupported=('elation_echo_grant_negative',))
        operand = NumericOperandIR(f'{effect.effect_id}:elation_value', 'expression',
            {'formula_role': 'elation_points'},
            expression=standard['amount_expr'] if operation == 'convert_echo' else numeric_fixed(value),
            coverage_status='executable')
        spec = {'schema_version': DYNAMIC_VALUE_OPERATION_SCHEMA, 'operation_kind': 'set',
            'destination_key': standard['destination_dynamic_key'],
            'destination_hash': standard['destination_dynamic_hash'], 'target_alias': standard['target_alias'],
            'scope_kind': 'contextual', 'lifecycle': 'execution_context', 'operand': operand.to_json(),
            'minimum': None, 'maximum': None, 'coverage_status': 'executable', 'blocked_reason': ''}
        result = _execute_dynamic_value_operation(replace(effect, payload={**effect.payload,
            'standard': {**standard, 'dynamic_operation': spec}}), context)
        if operation == 'read_points' and not result.unsupported:
            read_record = SettlementRecord('elation_read_points', 'effect_system', process_only=True,
                payload={'pool': 'battle', 'point_type': standard['point_type'], 'value': value,
                         'base_points': runtime['base_points'],
                         'moment_id': runtime['active_moment_id']}, trace=effect.source.to_json())
            return replace(result, records=(*result.records, read_record.to_json()))
        return result
    except (TypeError, ValueError) as exc:
        return EffectResult(unsupported=(str(exc),))
