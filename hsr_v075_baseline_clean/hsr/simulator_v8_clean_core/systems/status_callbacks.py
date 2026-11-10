from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Callable, cast

from ..core.model import BattleState, BreakNotificationFact, GameEvent, JSONValue, Mutation, PendingDefeatPlan, QueueActionStartFact, QueueActionTerminalFact, RNGEvent, StanceCountDownFact, StatusLifecycleFact, TargetResolution, current_max_hp, with_hit_window_invocation_fact
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import (
    ConditionEvaluationResult,
    EvaluationContext,
    NumericEvaluationContext,
    NumericEvaluationResult,
    RuleEvaluator,
)
from ..rules.expression_ir import numeric_dynamic_hashes, numeric_fixed, numeric_missing
from ..rules.condition_state import TransientConditionOperandProvider, TransientConditionOperandRequest, TransientConditionOperandResolution
from ..rules.ir import ActionDelayEmissionIR, ConditionIR, QueueIntentIR, StatusCallbackIR, StatusCallbackTaskIR, StatusDamageEmissionIR
from ..rules.rulebook import RuleBook
from ..rules.task_graph import (
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphNumericDefinitionIR,
    TaskGraphWeightedSelectionIR,
)
from ..rules.value_binding import (
    ValueBindingRequest,
    ValueContext,
    ValueResolver,
    resolve_runtime_numeric_expression,
)
from ..unit_eligibility import (
    runtime_unit_is_dark_team,
    runtime_unit_is_light_team,
    runtime_unit_is_target_candidate,
    runtime_units_are_opposing_combat_teams,
    runtime_units_share_combat_team,
)
from .damage import DamageModifierContribution, DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from .action_event_contract import ActionWindowExpectedScope
from .dot_formula import DotFormula, DotFormulaInput
from .elation import resolve_elation_damage_context
from .dynamic_values import (
    binding_source_from_status_detail,
    binding_source_from_store_for_units,
    binding_source_from_store,
    character_declared_dynamic_binding_source,
    servant_declared_dynamic_binding_source,
    servant_declared_dynamic_binding_source_for_owner,
    character_skill_param_declared_keys,
    character_skill_param_binding_sources,
    find_status_detail,
    status_binding_sources,
    store_from_state,
)
from .effect import (
    EffectExecutionContext,
    EffectRegistry,
    PreHealDispatchResult,
    _resolve_target_alias,
)
from .mutation_events import events_for_mutation, mutation_backed_event_id
from .queue import (
    DeathrattleQueueAdmission,
    LimboRescueQueueAdmission,
    QueueEntry,
    QueueSystem,
    QueueTargetResolver,
    unit_alive_state_blocked_reason,
)
from .rng import (
    RNGOutcome,
    RNGRequest,
    choice_key_for_identity,
    event_id_for_identity,
    resolve_rng_request,
    rng_choices_from_payload,
    rng_mode_from_payload,
)
from .status import (
    StatusLifecyclePlan,
    StatusSystem,
    _hp_cap_clamp_after_attribute_write,
    _map_stack_property,
    status_control_gate_for_actor,
)
from .target import TargetExpressionResult, TargetSystem
from .task_graph import (
    TaskGraphBranchResult,
    TaskGraphConditionResult,
    TaskGraphContinuation,
    TaskGraphCountResult,
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphExecutor,
    TaskGraphGraphResult,
    TaskGraphHookRequest,
    TaskGraphLeafResult,
    TaskGraphNodeProjection,
    TaskGraphSettlementRecord,
    TaskGraphStatusScope,
    TaskGraphTargetResult,
    TaskGraphWeightedSelectionResult,
    TaskGraphTemplateBindingsResult,
    evaluate_task_graph_template_bindings,
    with_template_binding_sources,
    resolve_task_graph_weighted_selection,
)
from .unit_relation import TargetEvaluationContext, committed_turn_owner_id
from .timeline import TimelineSystem
from .toughness_state import read_toughness_segments
from .unit_stats import effective_unit_stat


# Callback events whose damage windows execute while a hit-all callback stack
# is active.  Extra hit windows produced inside them are marked so the source
# ByIsHitAllCallBackStack guard can stop recursive re-application.
HIT_ALL_CALLBACK_EVENTS = frozenset({
    "OnBeforeHitAll",
    "OnAfterHitAll",
    "OnBeforeBeingHitAll",
    "OnAfterBeingHitAll",
})

# Windows whose GameEvent source and target are the attacker and defender of
# one damage request; other events never supply the damage target aliases.
_DAMAGE_ROLE_EVENT_TYPES = frozenset({
    "damage.before_hit",
    "damage.hit",
    "damage.attacker_hit",
    "damage.hit_sequence.before",
    "damage.hit_sequence.after",
    "damage.target_attack.before",
    "damage.target_attack.after",
    "damage.target_hit_sequence.before",
    "damage.target_hit_sequence.after",
})


@dataclass(frozen=True)
class StatusCallbackExecutionResult:
    ok: bool
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    events: tuple[GameEvent, ...] = ()
    errors: tuple[str, ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()
    task_graph_projections: tuple[TaskGraphNodeProjection, ...] = ()
    heal_ratio_delta: float = 0.0
    damage_modifiers: tuple[DamageModifierContribution, ...] = ()
    created_unit_ids: tuple[str, ...] = ()
    dispatched_event_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        dispatched = frozenset(self.dispatched_event_ids)
        if any(type(event_id) is not str or not event_id for event_id in dispatched):
            raise ValueError("status callback dispatched event identities are invalid")
        if not self.ok and dispatched:
            raise ValueError("blocked status callback leaks dispatched events")
        object.__setattr__(self, "dispatched_event_ids", dispatched)
        created = tuple(self.created_unit_ids)
        if any(type(unit_id) is not str or not unit_id for unit_id in created) or len(set(created)) != len(created):
            raise ValueError("status callback created unit identities are invalid")
        if not self.ok and created:
            raise ValueError("blocked status callback leaks created units")
        object.__setattr__(self, "created_unit_ids", created)
        if type(self.heal_ratio_delta) not in (int, float) or not math.isfinite(self.heal_ratio_delta):
            raise ValueError("status callback heal ratio must be finite")
        if not self.ok and self.heal_ratio_delta != 0:
            raise ValueError("blocked status callback leaks a heal ratio")
        if any(type(item) is not DamageModifierContribution for item in self.damage_modifiers):
            raise TypeError("status callback damage modifiers must be typed")
        if not self.ok and self.damage_modifiers:
            raise ValueError("blocked status callback leaks damage modifiers")
        object.__setattr__(self, "damage_modifiers", tuple(self.damage_modifiers))
        projections = tuple(self.task_graph_projections)
        if any(type(item) is not TaskGraphNodeProjection for item in projections):
            raise TypeError("status callback task graph projections are invalid")
        if not self.ok and projections:
            raise ValueError("blocked status callback leaks task graph projections")
        object.__setattr__(self, "task_graph_projections", projections)


def status_detail_for_task_graph_scope(
    state: BattleState, scope: TaskGraphStatusScope,
) -> dict[str, JSONValue] | None:
    unit = state.units.get(scope.owner_id)
    details = unit.flags.get("status_details", ()) if unit is not None else ()
    if not isinstance(details, (list, tuple)):
        return None
    matches = tuple(item for item in details
        if isinstance(item, dict) and item.get("instance_id") == scope.instance_id)
    if len(matches) != 1:
        return None
    detail = matches[0]
    if (detail.get("owner_id") != scope.owner_id or detail.get("lifecycle_state") != "active"
            or not detail.get("status_id") or detail["status_id"] not in unit.statuses):
        return None
    return detail


@dataclass(frozen=True)
class TaskGraphStatusConditionProvider:
    state: BattleState
    scope: TaskGraphStatusScope
    invocation_id: str
    window: str
    fallback: TransientConditionOperandProvider | None = None

    def resolve_transient(self, request: TransientConditionOperandRequest) -> TransientConditionOperandResolution:
        if request.fact_kind != "status_callback.modifier_value" and self.fallback is not None:
            return self.fallback.resolve_transient(request)
        reason = "remodifier_condition_request_not_admitted"
        detail = status_detail_for_task_graph_scope(self.state, self.scope)
        if (request.fact_kind == "status_callback.modifier_value"
                and request.invocation_id == self.invocation_id and request.window == self.window
                and not request.subject_ids and set(request.parameters or {}) == {"value_type"}):
            key = {"Layer": "stacks", "LifeTime": "remaining_duration"}.get(request.parameters["value_type"])
            value = detail.get(key) if detail is not None and key is not None else None
            admission = detail.get("duration_admission") if detail is not None else None
            if (detail is not None and key == "remaining_duration" and value is None and detail.get("duration") is None
                    and isinstance(admission, dict) and admission.get("admission_status") == "not_applicable"
                    and admission.get("blocked_reason") == "lifetime_missing"):
                return TransientConditionOperandResolution.resolved("string", "permanent",
                    fact_kind=request.fact_kind, invocation_id=self.invocation_id, window=self.window,
                    source_identity=f"status:{self.scope.owner_id}:{self.scope.instance_id}:permanent")
            if type(value) in (int, float) and math.isfinite(value):
                return TransientConditionOperandResolution.resolved("number", value,
                    fact_kind=request.fact_kind, invocation_id=self.invocation_id, window=self.window,
                    source_identity=f"status:{self.scope.owner_id}:{self.scope.instance_id}:{key}")
            reason = "remodifier_condition_status_value_unavailable"
        return TransientConditionOperandResolution.blocked(reason,
            fact_kind=request.fact_kind, invocation_id=request.invocation_id)


@dataclass(frozen=True)
class QueueEventConditionProvider:
    """Typed queue-event facts for contextual conditions on one invocation.

    The only admitted source is the queue start fact produced by QueueSystem;
    the payload string is never read, so an ordinary event payload cannot
    impersonate the insertion tag.
    """

    state: BattleState
    invocation_id: str
    window: str
    event: GameEvent | None
    owner_id: str = ""
    queue_fact: QueueActionStartFact | QueueActionTerminalFact | None = None

    def resolve_transient(
        self, request: TransientConditionOperandRequest
    ) -> TransientConditionOperandResolution:
        if request.fact_kind != "event.param_string":
            return TransientConditionOperandResolution.blocked(
                "queue_event_condition_fact_not_admitted",
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        if request.invocation_id != self.invocation_id or request.window != self.window:
            return TransientConditionOperandResolution.blocked(
                "queue_event_param_string_identity_mismatch",
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        if request.subject_ids or request.parameters:
            return TransientConditionOperandResolution.blocked(
                "queue_event_param_string_request_not_admitted",
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        fact = self.queue_fact
        event = self.event
        expected_type = (
            "queue.action.before" if type(fact) is QueueActionStartFact
            else "queue.action.after" if type(fact) is QueueActionTerminalFact
            and fact.event_type == "queue.action.after"
            else "queue.action.abort" if type(fact) is QueueActionTerminalFact
            else ""
        )
        if (
            type(fact) not in {QueueActionStartFact, QueueActionTerminalFact}
            or event is None
            or event.event_type != expected_type
            or not fact.matches_dispatch(self.state, event)
        ):
            return TransientConditionOperandResolution.blocked(
                "queue_event_param_string_fact_missing_or_mismatched",
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        if not fact.custom_tag:
            return TransientConditionOperandResolution.blocked(
                "queue_event_param_string_custom_tag_fact_missing",
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        if self.owner_id and self.owner_id != fact.actor_id:
            return TransientConditionOperandResolution.blocked(
                "queue_event_param_string_actor_scope_mismatch",
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        return TransientConditionOperandResolution.resolved(
            "string",
            fact.custom_tag,
            fact_kind=request.fact_kind,
            invocation_id=request.invocation_id,
            window=self.window,
            source_identity=(
                f"queue_event:{event.event_type}:{fact.queue_intent_id}:"
                f"{fact.actor_id}:{fact.custom_tag}"
            ),
        )


def resolve_remodifier_status_scopes(
    state: BattleState, payload: Mapping[str, JSONValue], target_ids: tuple[str, ...],
    *, caster_id: str | None = None, maximum: int | None = None,
    predicate: Callable[[TaskGraphStatusScope], TaskGraphConditionResult] | None = None,
) -> TaskGraphTargetResult:
    """Select live ParamModifier identities; callback ownership stays unchanged."""
    if payload.get("PredicateFilter"):
        return TaskGraphTargetResult("blocked", blocked_reason="remodifier_filter_not_admitted")
    status_type = payload.get("StatusTypeMask")
    if status_type is not None and status_type != "Buff":
        return TaskGraphTargetResult("blocked", blocked_reason="remodifier_status_type_mask_not_admitted")
    if payload.get("predicate_filter_required") and predicate is None:
        return TaskGraphTargetResult("blocked", blocked_reason="remodifier_predicate_consumer_missing")
    name = payload.get("ModifierName")
    flags = payload.get("BehaviorFlagFilter", ())
    if (name is not None and (not isinstance(name, str) or not name)
            or not isinstance(flags, (list, tuple))
            or any(not isinstance(flag, str) or not flag for flag in flags)
            or not name and not flags and not status_type):
        return TaskGraphTargetResult("blocked", blocked_reason="remodifier_filter_invalid")
    scopes: list[TaskGraphStatusScope] = []
    rng_events: list[RNGEvent] = []
    include_limbo = payload.get("IncludeLimbo") is True
    from .unit_lifecycle import UnitLifecycleSystem

    lifecycle = UnitLifecycleSystem()
    for target_id in target_ids:
        unit = state.units.get(target_id)
        if unit is not None and not include_limbo:
            # Source default excludes present-but-inactive (limbo) targets;
            # IncludeLimbo=True admits their status instances for this query.
            view = lifecycle.view(state, target_id)
            if view.is_present and not view.is_active:
                continue
        details = unit.flags.get("status_details", ()) if unit is not None else None
        if not isinstance(details, (list, tuple)):
            return TaskGraphTargetResult("blocked", blocked_reason="remodifier_status_details_invalid")
        for item in sorted((item for item in details if isinstance(item, dict)),
                           key=lambda item: str(item.get("instance_id") or "")):
            if item.get("lifecycle_state") in {"removed", "expired", "inactive"}:
                continue
            if (name and item.get("modifier_name") != name
                    or caster_id is not None and item.get("caster_id") != caster_id
                    or not set(flags).issubset(item.get("behavior_flags", ()))):
                continue
            if status_type:
                if item.get("status_type") not in {"Buff", "Debuff", "Other"}:
                    return TaskGraphTargetResult("blocked", blocked_reason="remodifier_status_type_unknown")
                if item["status_type"] != status_type:
                    continue
            identity = item.get("instance_id")
            if not isinstance(identity, str) or not identity:
                return TaskGraphTargetResult("blocked", blocked_reason="remodifier_status_identity_invalid")
            scope = TaskGraphStatusScope(target_id, identity)
            if status_detail_for_task_graph_scope(state, scope) is None:
                return TaskGraphTargetResult("blocked", blocked_reason="remodifier_status_instance_not_active")
            if predicate is not None:
                result = predicate(scope)
                if result.status != "resolved" or type(result.value) is not bool:
                    return TaskGraphTargetResult("blocked",
                        blocked_reason=result.blocked_reason or "remodifier_predicate_not_resolved")
                rng_events.extend(result.rng_events)
                if not result.value:
                    continue
            scopes.append(scope)
    return TaskGraphTargetResult("resolved", status_scopes=tuple(scopes[:maximum]), rng_events=tuple(rng_events))


def _task_graph_transport_reason(
    continuation: object,
    hooks: object,
) -> str:
    if continuation is not None and type(continuation) is not TaskGraphContinuation:
        return "status_task_graph_continuation_type_invalid"
    if hooks is not None and type(hooks) is not TaskGraphExecutionHooks:
        return "status_nested_ability_hooks_type_invalid"
    if hooks is not None and continuation is None:
        return "status_nested_ability_hooks_without_continuation"
    return ""


def _blocked_task_graph_hook_result(name: str, reason: str) -> object:
    if name == "leaf":
        return TaskGraphLeafResult(
            "blocked", outcome_kind="", blocked_reason=reason
        )
    if name == "condition":
        return TaskGraphConditionResult("blocked", blocked_reason=reason)
    if name == "branch":
        return TaskGraphBranchResult("blocked", blocked_reason=reason)
    if name == "count":
        return TaskGraphCountResult("blocked", blocked_reason=reason)
    if name == "targets":
        return TaskGraphTargetResult("blocked", blocked_reason=reason)
    if name == "graph":
        return TaskGraphGraphResult("blocked", blocked_reason=reason)
    if name == "weighted_selection":
        return TaskGraphWeightedSelectionResult("blocked", blocked_reason=reason)
    if name == "template_bindings":
        return TaskGraphTemplateBindingsResult("blocked", blocked_reason=reason)
    raise ValueError("unknown task graph hook channel")


def _evaluated_stack_property_entry(
    item: dict[str, JSONValue],
    *,
    task_id: str,
    task_path: str,
    value: float,
) -> dict[str, JSONValue]:
    """Return the post-OnStack shape of one computed property entry.

    A formal _runtime_modifiers entry may be delayed (value None plus
    value_mode/deferred_dynamic_hashes) until this task evaluates its dynamic
    expression. Once evaluated it becomes an ordinary applied entry carrying
    the producer identity; the deferred markers must not survive.
    """

    updated = {
        **item,
        "value": value,
        "producer_task_id": task_id,
        "producer_task_path": task_path,
        "applied_reason": "status_stack_property",
    }
    updated.pop("value_mode", None)
    updated.pop("deferred_dynamic_hashes", None)
    return updated


def _status_callback_event_matches_fact(
    callback_event: str,
    fact_event: str,
) -> bool:
    """Admit the dispatcher's formal listener alias family.

    A produced OnModifierAdd fact may be consumed by an OnListenModifierAdd
    listener (and likewise for the other lifecycle companion pairs). Reuse the
    dispatcher companion-key rule instead of requiring an identical name.
    """

    if callback_event == fact_event:
        return True
    from .event_dispatch import _callback_companion_key

    callback_key = _callback_companion_key(callback_event)
    return bool(callback_key) and callback_key == _callback_companion_key(fact_event)


def _limbo_rescue_queue_admission(
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    trigger_event: GameEvent | None,
    intent: QueueIntentIR,
) -> tuple[str, str, "LimboRescueQueueAdmission | None"]:
    """Bind one OnLimboWaitHeal insert to the pending-defeat cause it rescues.

    The pending plan is the only authority that lets a limbo owner enqueue and
    later run its own turn-insert ability.  Source callback/task identity, the
    owner instance, the alive-state mask and the unselectable-target flag all
    have to agree; a normal queue request still needs an active actor.
    """

    plan = getattr(trigger_event, "pending_defeat_plan", None)
    if type(plan) is not PendingDefeatPlan or trigger_event is None:
        return "", "", None
    if trigger_event.event_type != "unit.limbo_wait_heal":
        return "", "", None
    if callback.event != "OnLimboWaitHeal" or task.event != "OnLimboWaitHeal":
        return "", "limbo_rescue_callback_event_not_admitted", None
    if (
        task.coverage_status != "executable"
        or task.blocked_reason
        or callback.coverage_status != "executable"
        or callback.blocked_reason
        or task.task_id != intent.source_task_id
        or callback.callback_id != intent.callback_id
    ):
        return "", "limbo_rescue_source_callback_not_admitted", None
    if str(detail.get("owner_id") or "") != plan.unit_id:
        return "", "limbo_rescue_source_not_pending_unit", None
    if (
        intent.opcode != "TurnInsertAbility"
        or intent.owner_alive_state != "alive_or_limbo"
        or intent.can_run_on_unselectable_target is not True
    ):
        return "", "limbo_rescue_queue_contract_not_admitted", None
    if intent.ability_target_alias and intent.target_alive_state != "alive_or_limbo":
        return "", "limbo_rescue_target_contract_not_admitted", None
    admission = LimboRescueQueueAdmission(
        unit_id=plan.unit_id,
        pending_defeat_id=plan.pending_id,
        lethal_hp_mutation_id=plan.hp_mutation.stable_id(),
        source_event_id=str(trigger_event.event_id or ""),
        source_status_instance_id=str(detail.get("instance_id") or ""),
        source_modifier_name=str(callback.modifier_name or ""),
        ability_name=str(intent.action_ref_or_ability_name or ""),
        queue_intent_id=str(intent.queue_intent_id or ""),
        queue_kind=str(intent.queue_kind or ""),
        source_task_id=str(task.task_id or ""),
    )
    return plan.unit_id, "", admission

class StatusCallbackSystem:
    """Executes admitted modifier-local callbacks from Canonical IR."""

    def __init__(
        self,
        rules: RuleBook,
        *,
        damage: DamageSystem | None = None,
        reducer: MutationReducer | None = None,
        timeline: TimelineSystem | None = None,
        queue: QueueSystem | None = None,
        effect_registry: EffectRegistry | None = None,
    ) -> None:
        self.rules = rules
        self.damage = damage or DamageSystem(rules)
        self.reducer = reducer or MutationReducer()
        self.timeline = timeline or TimelineSystem()
        self.queue = queue or QueueSystem()
        self.queue_targets = QueueTargetResolver()
        self.targets = TargetSystem(rules)
        self.effect_registry = effect_registry or EffectRegistry(StatusSystem(rules))
        self.effect_registry.set_pre_heal_dispatcher(self._dispatch_pre_heal)
        self.evaluator = RuleEvaluator()
        self.value_resolver = ValueResolver(rules)
        self.task_graph_executor = TaskGraphExecutor()

    def execute(
        self,
        state: BattleState,
        *,
        unit_id: str,
        modifier_name: str,
        event: str,
        trigger_event: GameEvent | None = None,
        damage_window_ledger: DamageWindowLedger | None = None,
        detail_override: dict[str, JSONValue] | None = None,
        task_graph_continuation: TaskGraphContinuation | None = None,
        nested_ability_hooks: TaskGraphExecutionHooks | None = None,
    ) -> StatusCallbackExecutionResult:
        result = self._execute(
            state,
            unit_id=unit_id,
            modifier_name=modifier_name,
            event=event,
            trigger_event=trigger_event,
            damage_window_ledger=damage_window_ledger,
            detail_override=detail_override,
            task_graph_continuation=task_graph_continuation,
            nested_ability_hooks=nested_ability_hooks,
        )
        if result.node_results:
            return result
        reason = ",".join(result.errors)
        return replace(
            result,
            node_results=(
                ExecutionNodeResult(
                    node_kind="status_callback",
                    node_id=f"{unit_id}:{modifier_name}:{event}",
                    status="complete" if result.ok else "blocked",
                    reason_code=reason or ("" if result.ok else "status_callback_incomplete"),
                ),
            ),
        )

    def execute_action_window_formal_root(
        self,
        state: BattleState,
        *,
        callback_id: str,
        unit_id: str,
        modifier_name: str,
        event: str,
        trigger_event: GameEvent,
        damage_window_ledger: DamageWindowLedger | None = None,
        detail_override: dict[str, JSONValue] | None = None,
        nested_ability_provider: object,
        expected_window_scope: ActionWindowExpectedScope | None,
    ) -> StatusCallbackExecutionResult:
        from .ability import StatusNestedAbilityContext, StatusNestedAbilityHookProvider

        if type(nested_ability_provider) is not StatusNestedAbilityHookProvider:
            return _selected_callback_blocked(
                state,
                callback_id,
                "action_window_nested_ability_provider_type_invalid",
            )
        if (
            type(trigger_event) is not GameEvent
            or not trigger_event.event_type.startswith("action.window.")
        ):
            return _selected_callback_blocked(
                state,
                callback_id,
                "action_window_formal_root_event_invalid",
            )
        if (
            type(expected_window_scope) is not ActionWindowExpectedScope
            or trigger_event.expected_action_window_scope is not expected_window_scope
            or trigger_event.admitted_action_target_fact is None
        ):
            return _selected_callback_blocked(
                state,
                callback_id,
                "action_window_formal_root_scope_mismatch",
            )
        scope_reason = trigger_event.admitted_action_target_fact.invocation_blocked_reason(
            expected_scope=expected_window_scope
        )
        if scope_reason:
            return _selected_callback_blocked(state, callback_id, scope_reason)
        return self._execute_event_formal_root(state, callback_id=callback_id, unit_id=unit_id,
            modifier_name=modifier_name, event=event, trigger_event=trigger_event,
            damage_window_ledger=damage_window_ledger, detail_override=detail_override,
            nested_ability_provider=nested_ability_provider, expected_window_scope=expected_window_scope)

    def execute_registered_event_formal_root(
        self, state: BattleState, *, callback_id: str, unit_id: str, modifier_name: str,
        event: str, trigger_event: GameEvent, nested_ability_provider: object,
        damage_window_ledger: DamageWindowLedger | None = None,
        detail_override: dict[str, JSONValue] | None = None,
    ) -> StatusCallbackExecutionResult:
        from .ability import StatusNestedAbilityHookProvider

        if type(nested_ability_provider) is not StatusNestedAbilityHookProvider:
            return _selected_callback_blocked(state, callback_id, "registered_event_nested_provider_type_invalid")
        if type(trigger_event) is not GameEvent or trigger_event.event_type.startswith("action.window."):
            return _selected_callback_blocked(state, callback_id, "registered_event_formal_root_event_invalid")
        family = self.rules.status_event_family(event)
        if (family is None or family.coverage_status != "executable"
                or family.admission_status != "executable"
                or family.blocked_reason or family.blocking_dependency
                or trigger_event.event_type not in family.runtime_event_sources):
            return _selected_callback_blocked(state, callback_id, "registered_event_formal_root_source_not_admitted")
        detail = detail_override or find_status_detail(state, unit_id, modifier_name=modifier_name)
        identity = detail.get("instance_id") if detail is not None else None
        current = (status_detail_for_task_graph_scope(state, TaskGraphStatusScope(unit_id, identity))
                   if isinstance(identity, str) and identity else None)
        if current is None:
            return _selected_callback_blocked(state, callback_id, "registered_event_status_instance_not_active")
        return self._execute_event_formal_root(state, callback_id=callback_id, unit_id=unit_id,
            modifier_name=modifier_name, event=event, trigger_event=trigger_event,
            damage_window_ledger=damage_window_ledger, detail_override=current,
            nested_ability_provider=nested_ability_provider, expected_window_scope=None)

    def _execute_event_formal_root(
        self, state: BattleState, *, callback_id: str, unit_id: str, modifier_name: str,
        event: str, trigger_event: GameEvent, nested_ability_provider: object,
        damage_window_ledger: DamageWindowLedger | None,
        detail_override: dict[str, JSONValue] | None,
        expected_window_scope: ActionWindowExpectedScope | None,
    ) -> StatusCallbackExecutionResult:
        from .ability import StatusNestedAbilityContext

        trigger_event_id = trigger_event.event_id or str(
            trigger_event.to_json().get("event_id") or ""
        )
        if not trigger_event_id:
            return _selected_callback_blocked(
                state,
                callback_id,
                "action_window_formal_root_event_identity_missing",
            )
        callback = self.rules.status_callback(callback_id)
        if (
            callback is None
            or callback.modifier_name != modifier_name
            or callback.event != event
            or callback.source_mode not in {"mainline_avatar_ability", "mainline_servant_ability", "mainline_stage_ability"}
        ):
            return _selected_callback_blocked(
                state,
                callback_id,
                "action_window_formal_root_callback_identity_mismatch",
            )
        if callback.coverage_status != "executable":
            return _selected_callback_blocked(
                state,
                callback_id,
                callback.blocked_reason
                or f"status_callback_not_executable:{callback.coverage_status}",
            )
        if callback.admission_status != "executable":
            return _selected_callback_blocked(
                state,
                callback_id,
                callback.blocking_dependency
                or f"listener_not_admitted:{callback.admission_status}",
            )
        detail = detail_override or find_status_detail(
            state,
            unit_id,
            modifier_name=modifier_name,
        )
        if detail is None:
            return _selected_callback_blocked(
                state,
                callback_id,
                "status_detail_missing",
            )
        status_instance_id = str(detail.get("instance_id") or "")
        if (
            str(detail.get("owner_id") or "") != unit_id
            or str(detail.get("modifier_name") or "") != modifier_name
            or not status_instance_id
        ):
            return _selected_callback_blocked(
                state,
                callback_id,
                "status_detail_override_identity_mismatch",
            )
        attached_ids = _trigger_ids_for_event(detail, event)
        if attached_ids is None:
            return _selected_callback_blocked(
                state,
                callback_id,
                "formal_status_instance_callback_ledger_missing",
            )
        if callback_id not in attached_ids:
            return _selected_callback_blocked(
                state,
                callback_id,
                "status_callback_not_attached_to_instance",
            )
        tasks = tuple(self.rules.status_callback_tasks_for_callback(callback_id))
        if not tasks:
            if expected_window_scope is not None:
                resolution, reason = _status_action_window_target_resolution(state, trigger_event, detail)
                if resolution is None:
                    return _selected_callback_blocked(state, callback_id, reason)
            # Empty native CallbackConfig is an admitted observation, not a
            # request to materialize an empty graph. The common callback path
            # still checks the empty root ledger and emits its native envelope.
            result = self._execute_callback(state, callback, detail, trigger_event,
                damage_window_ledger, None, None)
            if not result.ok:
                return result
            return replace(result, node_results=(ExecutionNodeResult(
                node_kind="status_callback", node_id=callback_id, status="complete"),))
        graph_result = self.rules.query_formal_task_graph(
            "status_callback",
            callback_id,
            event,
            (task.task_id for task in tasks),
        )
        graph = graph_result.value
        if (
            graph_result.status != "resolved"
            or type(graph) is not TaskGraphIR
            or callback.task_ids != graph.root_formal_task_ids
        ):
            return _selected_callback_blocked(
                state,
                callback_id,
                graph_result.blocked_reason
                or "formal_status_callback_task_graph_identity_mismatch",
            )
        if expected_window_scope is not None:
            target_resolution, target_reason = _status_action_window_target_resolution(state, trigger_event, detail)
        else:
            queue_fact = trigger_event.queue_action_terminal_fact or trigger_event.queue_action_start_fact
            targets = (queue_fact.target_ids
                if queue_fact is not None else
                (trigger_event.target_id,) if trigger_event.target_id in state.units else ())
            target_resolution = TargetResolution(requested=targets, selectable=targets, legal=targets,
                primary=next(iter(targets), None), impact_group=targets, selected=targets,
                reason="registered_status_event", source="status_callback_system")
            target_reason = ""
        if target_resolution is None:
            return _selected_callback_blocked(state, callback_id, target_reason)
        context = StatusNestedAbilityContext(
            callback_id=callback_id,
            modifier_name=modifier_name,
            status_instance_id=status_instance_id,
            owner_id=unit_id,
            root_graph_id=graph.graph_id,
            trigger_event_id=trigger_event_id,
            target_resolution=target_resolution,
            admitted_action_target_fact=(trigger_event.admitted_action_target_fact
                if expected_window_scope is not None else None),
            expected_action_window_scope=expected_window_scope,
        )
        try:
            nested_ability_hooks = nested_ability_provider.hooks_for(context)
        except (TypeError, ValueError):
            return _selected_callback_blocked(
                state,
                callback_id,
                "action_window_nested_ability_provider_context_rejected",
            )
        staged_damage_ledger = _stage_damage_window_ledger(damage_window_ledger)
        result = self._execute_callback(
            state,
            callback,
            detail,
            trigger_event,
            staged_damage_ledger,
            None,
            nested_ability_hooks,
        )
        if not result.ok:
            return result
        _commit_damage_window_ledger(damage_window_ledger, staged_damage_ledger)
        if result.node_results:
            return result
        return replace(
            result,
            node_results=(
                ExecutionNodeResult(
                    node_kind="status_callback",
                    node_id=callback_id,
                    status="complete",
                ),
            ),
        )

    def execute_callback_id(
        self,
        state: BattleState,
        *,
        callback_id: str,
        watcher_id: str,
        range_id: str,
        branch: str,
        unit_id: str,
        modifier_name: str,
        trigger_event: GameEvent | None = None,
        detail_override: dict[str, JSONValue] | None = None,
        task_graph_continuation: TaskGraphContinuation | None = None,
        nested_ability_hooks: TaskGraphExecutionHooks | None = None,
    ) -> StatusCallbackExecutionResult:
        transport_reason = _task_graph_transport_reason(
            task_graph_continuation,
            nested_ability_hooks,
        )
        if transport_reason:
            return _selected_callback_blocked(state, callback_id, transport_reason)
        callback = self.rules.status_callback(callback_id)
        if callback is None:
            return _selected_callback_blocked(
                state,
                callback_id,
                "status_callback_identity_missing",
            )
        if callback.modifier_name != modifier_name:
            return _selected_callback_blocked(
                state,
                callback_id,
                "status_callback_modifier_identity_mismatch",
            )
        expected_event = {
            "enter": "OnAbilityPropertyRangeEnter",
            "exit": "OnAbilityPropertyRangeExit",
            "change": "OnAbilityPropertyChange",
        }.get(branch)
        evidence = callback.source.evidence
        if (
            expected_event is None
            or callback.scope_kind != "ability_property_range"
            or callback.event != expected_event
            or evidence.get("ability_property_watcher_id") != watcher_id
            or evidence.get("ability_property_range_id") != range_id
            or evidence.get("ability_property_range_branch")
            != (
                "OnEnterRange"
                if branch == "enter"
                else "OnExitRange"
                if branch == "exit"
                else "OnChange"
            )
        ):
            return _selected_callback_blocked(
                state,
                callback_id,
                "ability_property_range_callback_identity_mismatch",
            )
        detail = detail_override or find_status_detail(
            state,
            unit_id,
            modifier_name=modifier_name,
        )
        if detail is None:
            return _selected_callback_blocked(
                state,
                callback_id,
                "status_detail_missing",
            )
        if (
            str(detail.get("owner_id") or "") != unit_id
            or str(detail.get("modifier_name") or "") != modifier_name
            or not str(detail.get("instance_id") or "")
        ):
            return _selected_callback_blocked(
                state,
                callback_id,
                "status_detail_override_identity_mismatch",
            )
        admitted_ids = _trigger_ids_for_event(detail, callback.event)
        if admitted_ids is not None and callback_id not in admitted_ids:
            return _selected_callback_blocked(
                state,
                callback_id,
                "status_callback_not_attached_to_instance",
            )
        result = self._execute_callback(
            state,
            callback,
            detail,
            trigger_event,
            None,
            task_graph_continuation,
            nested_ability_hooks,
        )
        if result.node_results:
            return result
        return replace(
            result,
            node_results=(
                ExecutionNodeResult(
                    node_kind="status_callback",
                    node_id=callback_id,
                    status="complete" if result.ok else "blocked",
                    reason_code=",".join(result.errors),
                ),
            ),
        )

    def _execute(
        self,
        state: BattleState,
        *,
        unit_id: str,
        modifier_name: str,
        event: str,
        trigger_event: GameEvent | None = None,
        damage_window_ledger: DamageWindowLedger | None = None,
        detail_override: dict[str, JSONValue] | None = None,
        task_graph_continuation: TaskGraphContinuation | None = None,
        nested_ability_hooks: TaskGraphExecutionHooks | None = None,
    ) -> StatusCallbackExecutionResult:
        transport_reason = _task_graph_transport_reason(
            task_graph_continuation,
            nested_ability_hooks,
        )
        if transport_reason:
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                errors=(transport_reason,),
            )
        detail = detail_override
        if detail is not None and (
            str(detail.get("owner_id") or "") != unit_id
            or str(detail.get("modifier_name") or "") != modifier_name
            or not str(detail.get("instance_id") or "")
        ):
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        modifier_name=modifier_name,
                        event=event,
                        reason="status_detail_override_identity_mismatch",
                        trace={},
                    ),
                ),
                errors=("status_detail_override_identity_mismatch",),
            )
        if detail is None:
            detail = find_status_detail(state, unit_id, modifier_name=modifier_name)
        if detail is None:
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        modifier_name=modifier_name,
                        event=event,
                        reason="status_detail_missing",
                        trace={},
                    ),
                ),
                errors=("status_detail_missing",),
            )
        callbacks = self.rules.status_callbacks_for_modifier_event(modifier_name, event)
        admitted_callback_ids = _trigger_ids_for_event(detail, event)
        if admitted_callback_ids is not None:
            callbacks = tuple(callback for callback in callbacks if callback.callback_id in admitted_callback_ids)
        callbacks = tuple(sorted(callbacks, key=lambda callback: callback.execution_order))
        if not callbacks:
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        modifier_name=modifier_name,
                        event=event,
                        reason="status_callback_missing",
                        trace=_json_dict(detail.get("source_trace")),
                    ),
                ),
            )

        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        rng_events: list[RNGEvent] = []
        errors: list[str] = []
        events: list[GameEvent] = []
        node_results: list[ExecutionNodeResult] = []
        task_graph_projections: list[TaskGraphNodeProjection] = []
        staged_damage_ledger = _stage_damage_window_ledger(damage_window_ledger)
        heal_ratio_delta = 0.0
        damage_modifiers: list[DamageModifierContribution] = []
        dispatched_event_ids: set[str] = set()
        for callback in callbacks:
            result = self._execute_callback(
                current_state,
                callback,
                detail,
                trigger_event,
                staged_damage_ledger,
                task_graph_continuation,
                nested_ability_hooks,
            )
            current_state = result.after_state
            heal_ratio_delta += result.heal_ratio_delta
            damage_modifiers.extend(result.damage_modifiers)
            dispatched_event_ids.update(result.dispatched_event_ids)
            mutations.extend(result.mutations)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            events.extend(result.events)
            errors.extend(result.errors)
            node_results.extend(result.node_results)
            task_graph_projections.extend(result.task_graph_projections)
        if errors:
            reason = f"status_callback_group_atomic_rollback:{errors[0]}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        modifier_name=modifier_name,
                        event=event,
                        reason=reason,
                        trace=_json_dict(detail.get("source_trace")),
                    ),
                ),
                errors=tuple(errors),
                node_results=(
                    ExecutionNodeResult(
                        node_kind="status_callback_group",
                        node_id=f"{unit_id}:{modifier_name}:{event}",
                        status="blocked",
                        reason_code="status_callback_group_atomic_precheck_failed",
                    ),
                ),
            )
        _commit_damage_window_ledger(
            damage_window_ledger,
            staged_damage_ledger,
        )
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
            node_results=tuple(node_results),
            task_graph_projections=tuple(task_graph_projections),
            heal_ratio_delta=heal_ratio_delta,
            damage_modifiers=tuple(damage_modifiers),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def _execute_callback(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
        task_graph_continuation: TaskGraphContinuation | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
    ) -> StatusCallbackExecutionResult:
        if callback.coverage_status != "executable":
            reason = callback.blocked_reason or f"status_callback_not_executable:{callback.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_callback_blocked_record(callback=callback, detail=detail, reason=reason),),
                errors=(reason,),
            )
        lifecycle_fact = trigger_event.status_lifecycle_fact if trigger_event is not None else None
        # Ability-property watchers are their own change producer: they pass the
        # resolved status detail and may execute from any state-mutating event.
        if callback.scope_kind == "ability_property_range":
            lifecycle_fact = None
        lifecycle_instance_gone = bool(
            getattr(trigger_event, "lifecycle_instance_gone", False)
        )
        lifecycle_fact_matches = lifecycle_fact is not None and (
            type(lifecycle_fact) is StatusLifecycleFact
            and _status_callback_event_matches_fact(
                callback.event, lifecycle_fact.callback_event)
            and (
                lifecycle_fact.matches(state, trigger_event)
                or (
                    # A synchronous listener retired this instance while the
                    # remaining lifecycle notifications of the same batch were
                    # still queued. The producer fact and the exact event are
                    # unchanged; only the live-instance check cannot hold.
                    lifecycle_instance_gone
                    and lifecycle_fact.matches_event(trigger_event)
                )
            )
        )
        if lifecycle_fact is not None and not lifecycle_fact_matches:
            # Producer facts are authoritative; a payload-only instance
            # identity is never allowed to satisfy this callback.
            reason = "status_lifecycle_fact_missing_or_mismatched"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_callback_blocked_record(callback=callback, detail=detail, reason=reason),),
                errors=(reason,),
            )

        formal = callback.source_mode in {"mainline_avatar_ability", "mainline_servant_ability", "mainline_stage_ability"}
        if formal:
            return self._execute_formal_callback(
                state,
                callback,
                detail,
                trigger_event,
                damage_window_ledger,
                task_graph_continuation=task_graph_continuation,
                nested_ability_hooks=nested_ability_hooks,
            )
        entry_result = self.rules.query_task_graph_entry(
            "status_callback",
            callback.callback_id,
            callback.event,
        )
        if entry_result.status == "resolved" or entry_result.candidate_ids:
            return _selected_callback_blocked(
                state,
                callback.callback_id,
                "status_callback_catalog_source_domain_mismatch",
            )
        if callback.source_mode not in {
            "mainline_equipment_ability",
            "mainline_monster_ability",
            "mainline_global_modifier",
        }:
            return _selected_callback_blocked(
                state,
                callback.callback_id,
                "status_callback_legacy_source_domain_not_admitted",
            )
        result = self._execute_legacy_callback(
            state,
            callback,
            detail,
            trigger_event,
            damage_window_ledger,
        )
        if not result.ok:
            return result
        route_record = SettlementRecord(
            record_type="status_callback_legacy_route",
            source="status_callback_system",
            process_only=True,
            payload={
                "callback_id": callback.callback_id,
                "source_mode": callback.source_mode,
            },
            trace={"callback_source": callback.source.to_json()},
        ).to_json()
        return replace(result, records=(route_record, *result.records))

    def _execute_formal_callback(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
        *,
        task_graph_continuation: TaskGraphContinuation | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
    ) -> StatusCallbackExecutionResult:
        attached_ids = _trigger_ids_for_event(detail, callback.event)
        if attached_ids is None:
            return _selected_callback_blocked(
                state,
                callback.callback_id,
                "formal_status_instance_callback_ledger_missing",
            )
        if callback.callback_id not in attached_ids:
            return _selected_callback_blocked(
                state,
                callback.callback_id,
                "status_callback_not_attached_to_instance",
            )
        tasks = tuple(
            self.rules.status_callback_tasks_for_callback(callback.callback_id)
        )
        if callback.event == "OnListenAfterSkillUse" and callback.scope_kind == "global_listener":
            fact = trigger_event.admitted_action_target_fact if trigger_event is not None else None
            scope = trigger_event.expected_action_window_scope if trigger_event is not None else None
            reason = (fact.invocation_blocked_reason(expected_scope=scope) if fact is not None
                      else "status_listener_skill_user_context_missing")
            if reason:
                return _selected_callback_blocked(state, callback.callback_id, reason)
            # The listener's ParamEntity is the skill user. The triggering
            # event still targets its victim; explicit Retarget inside this
            # callback may subsequently replace the parameter as usual.
            trigger_event = replace(trigger_event,
                payload={**trigger_event.payload, "param_entity_id": fact.actor_id})
        callback_record, callback_event = _status_callback_envelope(
            callback,
            detail,
            trigger_event,
        )
        if not tasks:
            entry_result = self.rules.query_task_graph_entry(
                "status_callback",
                callback.callback_id,
                callback.event,
            )
            if (
                callback.task_ids
                or entry_result.status == "resolved"
                or entry_result.candidate_ids
            ):
                return _selected_callback_blocked(
                    state,
                    callback.callback_id,
                    "taskless_status_callback_catalog_mismatch",
                )
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                records=(callback_record,),
                events=(callback_event,),
            )

        formal_task_ids = tuple(task.task_id for task in tasks)
        graph_result = self.rules.query_formal_task_graph(
            "status_callback",
            callback.callback_id,
            callback.event,
            formal_task_ids,
        )
        graph = graph_result.value
        if (
            graph_result.status != "resolved"
            or type(graph) is not TaskGraphIR
            or callback.task_ids != graph.root_formal_task_ids
        ):
            reason = (
                graph_result.blocked_reason
                or "formal_status_callback_task_graph_identity_mismatch"
            )
            return _selected_callback_blocked(state, callback.callback_id, reason)

        trigger_event_id = (
            str(trigger_event.to_json().get("event_id") or "")
            if trigger_event is not None
            else "direct"
        )
        invocation_id = (
            f"status_callback:{state.event_index}:{callback.callback_id}:"
            f"{detail.get('instance_id')}:{trigger_event_id}"
        )
        context_values: dict[str, JSONValue] = {
            "callback_id": callback.callback_id,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "status_instance_id": str(detail.get("instance_id") or ""),
            "owner_id": str(detail.get("owner_id") or ""),
            "trigger_event_id": (
                trigger_event.event_id if trigger_event is not None else ""
            ),
        }
        trigger_payload = trigger_event.payload if trigger_event is not None and isinstance(trigger_event.payload, dict) else {}
        context_values["rng_choices"] = rng_choices_from_payload(trigger_payload)
        context_values["rng_mode"] = rng_mode_from_payload(trigger_payload)
        execution_context = (
            task_graph_continuation.child_context(
                invocation_id,
                context_values,
            )
            if task_graph_continuation is not None
            else TaskGraphExecutionContext(invocation_id, context_values, trigger_event=trigger_event)
        )
        execution_context = replace(execution_context, trigger_event=trigger_event)
        heal_ratios: list[float] = []
        damage_modifiers: list[DamageModifierContribution] = []
        dispatched_event_ids: set[str] = set()
        execution = self.task_graph_executor.execute(
            state,
            graph,
            execution_context,
            self._formal_status_hooks(
                callback,
                detail,
                trigger_event,
                damage_window_ledger,
                nested_ability_hooks,
                heal_ratios,
                damage_modifiers,
                dispatched_event_ids,
            ),
        )
        if not execution.ok:
            reason = (
                execution.errors[0]
                if execution.errors
                else "formal_status_callback_task_graph_execution_blocked"
            )
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        callback=callback,
                        detail=detail,
                        reason=reason,
                    ),
                ),
                errors=(reason,),
                node_results=execution.outcome.node_results,
            )
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=execution.after_state,
            mutations=execution.mutations,
            rng_events=execution.rng_events,
            records=(
                callback_record,
                *(item.to_json() for item in execution.settlement_records),
            ),
            events=(callback_event, *execution.events),
            node_results=execution.outcome.node_results,
            task_graph_projections=execution.node_projections,
            heal_ratio_delta=sum(heal_ratios),
            damage_modifiers=tuple(damage_modifiers),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def execute_insert_abort(
        self,
        state: BattleState,
        *,
        binding: Mapping[str, JSONValue],
        trigger_event: GameEvent | None,
    ) -> StatusCallbackExecutionResult:
        """Run one QueueEntry's formal OnInsertAbort branch before cleanup commits.

        The branch comes from the same source graph that produced the queue
        entry; a missing binding, status instance or graph identity is an
        implementation blocker, never a silent cancellation.
        """

        def blocked(reason: str) -> StatusCallbackExecutionResult:
            return StatusCallbackExecutionResult(
                ok=False, after_state=state, errors=(reason,),
                records=(SettlementRecord(
                    record_type="insert_abort_blocked", source="status_callback_system",
                    process_only=True, payload={"reason": reason, "binding": dict(binding)},
                    trace={"insert_abort_binding": dict(binding)},
                ).to_json(),),
            )

        callback_id = str(binding.get("callback_id") or "")
        event_name = str(binding.get("event") or "")
        graph_id = str(binding.get("graph_id") or "")
        graph_node_id = str(binding.get("graph_node_id") or "")
        owner_id = str(binding.get("owner_id") or "")
        modifier_name = str(binding.get("modifier_name") or "")
        status_instance_id = str(binding.get("status_instance_id") or "")
        child_task_ids = binding.get("child_formal_task_ids")
        if (
            not callback_id or not event_name or not graph_id or not graph_node_id
            or not owner_id or not modifier_name or not status_instance_id
            or not isinstance(child_task_ids, (list, tuple)) or not child_task_ids
            or any(not isinstance(item, str) or not item for item in child_task_ids)
        ):
            return blocked("insert_abort_binding_incomplete")
        callback = self.rules.status_callback(callback_id)
        if callback is None or callback.coverage_status != "executable":
            return blocked("insert_abort_callback_not_executable")
        detail = find_status_detail(state, owner_id, modifier_name=modifier_name)
        if (
            detail is None
            or str(detail.get("instance_id") or "") != status_instance_id
            or str(detail.get("owner_id") or "") != owner_id
        ):
            return blocked("insert_abort_status_instance_missing")
        tasks = tuple(self.rules.status_callback_tasks_for_callback(callback_id))
        graph_result = self.rules.query_formal_task_graph(
            "status_callback",
            callback_id,
            callback.event,
            tuple(task.task_id for task in tasks),
        )
        graph = graph_result.value
        if (
            graph_result.status != "resolved"
            or type(graph) is not TaskGraphIR
            or graph.graph_id != graph_id
        ):
            return blocked("insert_abort_graph_identity_mismatch")
        node_by_id = {item.graph_node_id: item for item in graph.nodes}
        insert_node = node_by_id.get(graph_node_id)
        if insert_node is None or insert_node.opcode != "TurnInsertAction":
            return blocked("insert_abort_node_missing")
        abort_branches = tuple(
            item for item in insert_node.branches if item.branch_kind == "insert_abort"
        )
        if len(abort_branches) != 1 or not abort_branches[0].child_node_ids:
            return blocked("insert_abort_branch_missing")
        child_node_ids = abort_branches[0].child_node_ids
        bound_tasks = [node_by_id[item].formal_task_id for item in child_node_ids]
        if tuple(bound_tasks) != tuple(child_task_ids):
            return blocked("insert_abort_binding_task_mismatch")
        trigger_event_id = (
            str(trigger_event.to_json().get("event_id") or "")
            if trigger_event is not None else "direct"
        )
        invocation_id = (
            f"status_callback:{state.event_index}:{callback_id}:"
            f"{status_instance_id}:insert_abort:{trigger_event_id}"
        )
        execution_context = TaskGraphExecutionContext(
            invocation_id,
            {
                "callback_id": callback.callback_id,
                "modifier_name": callback.modifier_name,
                "event": callback.event,
                "status_instance_id": status_instance_id,
                "owner_id": owner_id,
                "trigger_event_id": (
                    trigger_event.event_id if trigger_event is not None else ""
                ),
                "insert_abort": True,
            },
        )
        hooks = self._formal_status_hooks(
            callback,
            detail,
            trigger_event,
            None,
            None,
            [],
            [],
            set(),
        )
        execution = self.task_graph_executor.execute_selected_nodes(
            state, graph, execution_context, hooks, child_node_ids
        )
        callback_record, callback_event = _status_callback_envelope(
            callback, detail, trigger_event,
        )
        if not execution.ok:
            reason = (
                execution.errors[0] if execution.errors
                else "insert_abort_task_graph_execution_blocked"
            )
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        callback=callback, detail=detail, reason=reason,
                    ),
                ),
                errors=(reason,),
                node_results=execution.outcome.node_results,
            )
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=execution.after_state,
            mutations=execution.mutations,
            rng_events=execution.rng_events,
            records=(
                callback_record,
                *(item.to_json() for item in execution.settlement_records),
            ),
            events=(callback_event, *execution.events),
            node_results=execution.outcome.node_results,
            task_graph_projections=execution.node_projections,
        )

    def _formal_status_hooks(
        self,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
        heal_ratios: list[float],
        damage_modifiers: list[DamageModifierContribution],
        dispatched_event_ids: set[str],
    ) -> TaskGraphExecutionHooks:
        def template_bindings(request, parameters, state):
            task, node, reason = self._formal_status_task_for_request(request, callback)
            if task is None or node is None or node.template_parameters != parameters:
                return TaskGraphTemplateBindingsResult("blocked", blocked_reason=reason or "template_parameter_node_mismatch")
            template_id = task.task_payload.get("committed_break_template_id")
            if template_id is not None:
                fact = trigger_event.stance_count_down_fact if trigger_event is not None else None
                template = self.rules.break_template(template_id) if isinstance(template_id, str) else None
                emissions = self.rules.break_damage_emissions_for_template(template_id) if template is not None else ()
                refs = tuple(item for item in node.references if item.reference_kind == "template")
                if (
                    type(fact) is not StanceCountDownFact or trigger_event is None
                    or not fact.matches(state, trigger_event)
                    or callback.event != "OnTriggerStanceCountDown" or task.event != callback.event
                    or str(detail.get("owner_id") or "") != fact.attacker_id
                    or request.target_ids not in ((), (fact.target_id,))
                    or node.node_kind != "template_call" or task.opcode != "IncludeTaskListTemplate"
                    or len(refs) != 1 or refs[0].resolution_status != "resolved"
                    or template is None or template.template_id != fact.template_id
                    or template.trigger_kind != "stance_count_down" or template.element_type != fact.element_type
                    or template.coverage_status != "executable" or not emissions
                    or any(item.coverage_status != "executable" or item.template_id != template.template_id
                           or item.damage_formula_family != "break"
                           for item in emissions)
                ):
                    return TaskGraphTemplateBindingsResult("blocked", blocked_reason="committed_break_template_fact_missing_or_mismatched")
                return TaskGraphTemplateBindingsResult("resolved", body_consumption_record=TaskGraphSettlementRecord(
                    "break_template_already_applied", "status_callback_system", process_only=True,
                    payload={"callback_id": callback.callback_id, "task_id": task.task_id,
                             "template_id": template.template_id, "target_id": fact.target_id,
                             "attacker_id": fact.attacker_id, "notification_event_id": fact.event_id,
                             "source_mutation_id": fact.source_mutation.stable_id()},
                    trace={"status_task_source": task.source.to_json(), "template_source": template.source.to_json()},
                ))
            if not parameters:
                return TaskGraphTemplateBindingsResult("resolved")
            context = _condition_context(self.rules, state, detail, trigger_event,
                template_binding_sources=request.template_binding_sources)
            return evaluate_task_graph_template_bindings(request, parameters, state,
                binding_sources=context.binding_sources)

        status_hooks = TaskGraphExecutionHooks(
            leaf=lambda request, state: self._execute_formal_status_leaf(
                request,
                state,
                callback,
                detail,
                trigger_event,
                damage_window_ledger,
                heal_ratios,
                damage_modifiers,
                dispatched_event_ids,
            ),
            condition=lambda request, state: self._evaluate_formal_status_condition(
                request, state, callback, detail, trigger_event
            ),
            branch=lambda request, state: self._select_formal_status_branch(
                request, state, callback, detail, trigger_event
            ),
            count=lambda request, definition, state: self._resolve_formal_status_count(
                request, definition, state, callback, detail
            ),
            targets=lambda request, state: self._resolve_formal_status_targets(
                request, state, callback, detail, trigger_event
            ),
            graph=lambda request, state: self._resolve_formal_status_nested_graph(
                request, state, callback
            ),
            weighted_selection=lambda request, selection, state: self._resolve_formal_status_weighted_selection(
                request, selection, state, callback, detail, trigger_event,
            ),
            template_bindings=template_bindings,
        )

        def route(name: str, request: TaskGraphHookRequest, *args: object) -> object:
            graph_result = self.rules.query_task_graph(request.graph_id)
            graph = graph_result.value
            if graph_result.status != "resolved" or type(graph) is not TaskGraphIR:
                selected = None
            elif (
                graph.entry_kind == "status_callback"
                and graph.owner_id == callback.callback_id
            ):
                selected = status_hooks
            elif graph.entry_kind == "ability_phase_callback":
                selected = nested_ability_hooks
            else:
                selected = None
            hook = getattr(selected, name, None) if selected is not None else None
            if hook is None:
                return _blocked_task_graph_hook_result(
                    name, f"status_nested_ability_{name}_context_missing"
                )
            return hook(request, *args)

        return TaskGraphExecutionHooks(
            leaf=lambda request, state: cast(
                TaskGraphLeafResult, route("leaf", request, state)
            ),
            condition=lambda request, state: cast(
                TaskGraphConditionResult, route("condition", request, state)
            ),
            branch=lambda request, state: cast(
                TaskGraphBranchResult, route("branch", request, state)
            ),
            count=lambda request, definition, state: cast(
                TaskGraphCountResult,
                route("count", request, definition, state),
            ),
            targets=lambda request, state: cast(
                TaskGraphTargetResult, route("targets", request, state)
            ),
            graph=lambda request, state: cast(
                TaskGraphGraphResult, route("graph", request, state)
            ),
            weighted_selection=lambda request, selection, state: cast(
                TaskGraphWeightedSelectionResult,
                route("weighted_selection", request, selection, state),
            ),
            template_bindings=lambda request, parameters, state: cast(
                TaskGraphTemplateBindingsResult, route("template_bindings", request, parameters, state)),
        )

    def _resolve_formal_status_nested_graph(
        self,
        request: TaskGraphHookRequest,
        _state: BattleState,
        callback: StatusCallbackIR,
    ) -> TaskGraphGraphResult:
        task, _node, reason = self._formal_status_task_for_request(request, callback)
        if task is None:
            return TaskGraphGraphResult("blocked", blocked_reason=reason)
        if task.opcode != "TriggerAbility":
            return TaskGraphGraphResult(
                "blocked", blocked_reason="status_nested_ability_opcode_mismatch"
            )
        ability_refs = tuple(
            reference
            for reference in request.references
            if reference.reference_kind == "ability"
        )
        if len(ability_refs) != 1 or ability_refs[0].resolution_status != "resolved":
            return TaskGraphGraphResult(
                "blocked",
                blocked_reason="status_nested_ability_reference_not_resolved",
            )
        reference = ability_refs[0]
        if task.linked_ability_phase_id:
            if reference.definition_id != task.linked_ability_phase_id:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason="status_nested_ability_phase_identity_mismatch",
                )
            phase_ids = (task.linked_ability_phase_id,)
        elif task.linked_standalone_graph_id:
            if reference.definition_id != task.linked_standalone_graph_id:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason="status_nested_ability_standalone_identity_mismatch",
                )
            standalone = self.rules.standalone_ability_graph(
                task.linked_standalone_graph_id
            )
            if standalone is None:
                return TaskGraphGraphResult(
                    "blocked", blocked_reason="status_nested_ability_standalone_missing"
                )
            phase_ids = standalone.phase_ids
        else:
            return TaskGraphGraphResult(
                "blocked", blocked_reason="status_nested_ability_target_missing"
            )

        candidates: list[TaskGraphIR] = []
        for phase_id in phase_ids:
            phase = self.rules.ability_phase(phase_id)
            if phase is None or phase.invocation_role != "nested_only":
                continue
            callback_kinds = tuple(
                sorted(
                    {
                        ability_task.callback_kind
                        for ability_task in self.rules.ability_tasks_for_phase(phase_id)
                    }
                )
            )
            for callback_kind in callback_kinds:
                graph_result = self.rules.query_formal_task_graph(
                    "ability_phase_callback",
                    phase_id,
                    callback_kind,
                    (
                        task.task_id
                        for task in self.rules.ability_tasks_for_phase(phase_id)
                        if task.callback_kind == callback_kind
                    ),
                )
                graph = graph_result.value
                if (
                    graph_result.status != "resolved"
                    or type(graph) is not TaskGraphIR
                ):
                    return TaskGraphGraphResult(
                        "blocked",
                        blocked_reason=graph_result.blocked_reason
                        or "status_nested_ability_graph_identity_mismatch",
                    )
                candidates.append(graph)
        if len(candidates) != 1:
            return TaskGraphGraphResult(
                "blocked",
                blocked_reason=(
                    "status_nested_ability_callback_missing"
                    if not candidates
                    else "status_nested_ability_callback_ambiguous"
                ),
            )
        return TaskGraphGraphResult(
            "resolved", reference.definition_id, candidates[0]
        )

    def _formal_status_task_for_request(
        self,
        request: TaskGraphHookRequest,
        callback: StatusCallbackIR,
    ) -> tuple[StatusCallbackTaskIR | None, TaskGraphNodeIR | None, str]:
        node_result = self.rules.query_task_graph_node(request.graph_node_id)
        node = node_result.value
        task = self.rules.status_callback_task(request.formal_task_id)
        if node_result.status != "resolved" or type(node) is not TaskGraphNodeIR:
            return None, None, (
                node_result.blocked_reason
                or "status_callback_task_graph_formal_node_missing"
            )
        if task is None:
            return None, node, "status_callback_task_graph_formal_task_missing"
        if task.coverage_status != "executable" and task.blocked_reason not in {
            "equipment_task_family_non_gameplay", "source_proven_presentation_only",
        }:
            return None, node, (
                task.blocked_reason
                or f"status_callback_task_not_executable:{task.coverage_status}"
            )
        if (
            node.graph_id != request.graph_id
            or node.formal_task_id != task.task_id
            or node.opcode != request.opcode
            or task.callback_id != callback.callback_id
            or task.modifier_name != callback.modifier_name
            or task.event != callback.event
        ):
            return None, node, "status_callback_task_graph_formal_identity_mismatch"
        return task, node, ""

    def _insert_action_cancel_leaf(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
    ) -> TaskGraphLeafResult | None:
        """Legal in-game cancellation of one insertion before it starts.

        Only the source PreCheck decides this branch; an unusable intent,
        window or resolution stays on the implementation-blocked path instead
        of being reported as a normal cancellation.
        """

        if task.opcode != "TurnInsertAction":
            return None
        intents = tuple(
            intent
            for intent in self.rules.queue_intents_for_callback(callback.callback_id)
            if intent.source_task_id == task.task_id
        )
        if len(intents) != 1:
            return None
        intent = intents[0]
        if intent.coverage_status != "executable" or not intent.custom_tag:
            return None
        window = self.rules.queue_window_for_intent(intent.queue_intent_id)
        if (
            window is None
            or window.coverage_status != "executable"
            or window.window_family != "insert_action"
        ):
            return None
        resolution = self.rules.queue_resolution_for_intent(intent.queue_intent_id)
        if resolution is None or resolution.coverage_status != "executable":
            return None
        cancel_reason = _queue_insert_precheck_blocked(state, intent)
        if cancel_reason not in _INSERT_ACTION_LEGAL_CANCEL_REASONS:
            # Unresolved or malformed PreCheck data is an implementation
            # blocker; only a confirmed source condition may clean up as a
            # normal in-game cancellation.
            return None
        return TaskGraphLeafResult(
            "resolved",
            outcome_kind="insert_abort",
            settlement_records=(
                TaskGraphSettlementRecord(
                    record_type="insert_action_cancelled_before_start",
                    source="status_callback_system",
                    process_only=True,
                    payload={
                        "queue_intent_id": intent.queue_intent_id,
                        "callback_id": callback.callback_id,
                        "task_id": task.task_id,
                        "custom_tag": intent.custom_tag,
                        "cancel_reason": cancel_reason,
                        "queue_mutation_id": None,
                        "body_executed": False,
                    },
                    trace={
                        "queue_intent_source": intent.source.to_json(),
                        "queue_window_source": window.source.to_json(),
                        "queue_resolution_source": resolution.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_task_source": task.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                ),
            ),
        )

    def _execute_formal_status_leaf(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
        heal_ratios: list[float],
        damage_modifiers: list[DamageModifierContribution],
        dispatched_event_ids: set[str],
    ) -> TaskGraphLeafResult:
        task, node, reason = self._formal_status_task_for_request(request, callback)
        if task is None or node is None:
            return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=reason)
        if task.opcode in {
            "PredicateTaskList",
            "Retarget",
            "IncludeTaskListTemplate",
            "LoopExecuteTaskList",
            "RandomConfig",
            "Remodifier",
            "TriggerAbility",
        } and task.blocked_reason != "source_proven_presentation_only":
            return TaskGraphLeafResult(
                "blocked",
                outcome_kind="",
                blocked_reason="status_callback_structural_node_reached_leaf",
            )
        insert_cancel = self._insert_action_cancel_leaf(state, callback, task, detail)
        if insert_cancel is not None:
            return insert_cancel
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[TaskGraphSettlementRecord] = []
        created_unit_ids: list[str] = []
        for scoped_event in _formal_status_scoped_events(request, trigger_event):
            result = self._execute_formal_leaf_task(
                current,
                callback,
                task,
                detail,
                scoped_event,
                damage_window_ledger,
                status_scope=request.status_scope,
                template_target_ids=request.template_target_ids,
                template_binding_sources=request.template_binding_sources,
                task_graph_continuation=TaskGraphContinuation.from_hook_request(request),
            )
            if not result.ok:
                return TaskGraphLeafResult(
                    "blocked",
                    outcome_kind="",
                    blocked_reason=(
                        result.errors[0]
                        if result.errors
                        else "status_callback_task_graph_leaf_blocked"
                    ),
                )
            reduction = self.reducer.apply_all_result(current, result.mutations)
            if not reduction.ok or reduction.after_state != result.after_state:
                return TaskGraphLeafResult(
                    "blocked",
                    outcome_kind="",
                    blocked_reason="status_callback_task_graph_leaf_state_mismatch",
                )
            if result.node_results:
                return TaskGraphLeafResult(
                    "blocked",
                    outcome_kind="",
                    blocked_reason="status_callback_task_graph_leaf_nested_result_forbidden",
                )
            try:
                converted = _status_task_graph_settlement_records(result.records)
            except (KeyError, TypeError, ValueError):
                return TaskGraphLeafResult(
                    "blocked",
                    outcome_kind="",
                    blocked_reason="status_callback_task_graph_leaf_settlement_invalid",
                )
            current = result.after_state
            heal_ratios.append(result.heal_ratio_delta)
            damage_modifiers.extend(result.damage_modifiers)
            dispatched_event_ids.update(result.dispatched_event_ids)
            mutations.extend(result.mutations)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
            records.extend(converted)
            created_unit_ids.extend(result.created_unit_ids)
        if task.opcode == "CreateServant" and len(created_unit_ids) != 1:
            return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason="servant_create_target_fact_missing")
        return TaskGraphLeafResult(
            "resolved",
            tuple(mutations),
            tuple(events),
            tuple(rng_events),
            tuple(records),
            outcome_kind="servant_created" if task.opcode == "CreateServant" else "success",
            continuation_target_ids=tuple(created_unit_ids) if task.opcode == "CreateServant" else None,
        )

    def _evaluate_formal_status_condition(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
    ) -> TaskGraphConditionResult:
        task, node, reason = self._formal_status_task_for_request(request, callback)
        if task is None or node is None:
            return TaskGraphConditionResult("blocked", blocked_reason=reason)
        if task.opcode == "SwitchByCommandType" and not task.condition_id:
            # A bare command-type switch carries no predicate; it is a
            # command-phase marker whose implicit branch always runs.
            return TaskGraphConditionResult("resolved", value=True)
        scoped_event = _formal_status_scope_event(request, trigger_event)
        if node.termination_kind == "condition_progress_required":
            return TaskGraphConditionResult(
                "blocked",
                blocked_reason="status_callback_condition_progress_deferred_to_s8c",
            )
        condition = self.rules.condition(task.condition_id) if task.condition_id else None
        references = tuple(
            item for item in request.references if item.reference_kind == "condition"
        )
        if (
            condition is None
            or len(references) != 1
            or references[0].resolution_status != "resolved"
            or references[0].definition_id != condition.condition_id
        ):
            return TaskGraphConditionResult(
                "blocked",
                blocked_reason="status_callback_condition_reference_not_resolved",
            )
        result, rng_events, _ = self._evaluate_callback_condition(
            condition,
            state,
            callback,
            task,
            detail,
            scoped_event,
            selected_target_ids=request.target_ids,
            rng_identity_scope=(request.invocation_id, request.graph_node_id, *request.frame_ids, request.iteration_index),
            transient_condition_provider=_formal_status_transient_provider(
                state,
                request,
                scoped_event,
                str(detail.get("owner_id") or ""),
            ),
            template_target_ids=request.template_target_ids,
            template_binding_sources=request.template_binding_sources,
            immunity_trigger_event=(trigger_event if trigger_event is not None
                                    and trigger_event.event_type == "status.immunity" else None),
        )
        if not result.ok or result.result is None:
            return TaskGraphConditionResult(
                "blocked",
                blocked_reason=(
                    result.reason or "status_callback_condition_not_resolved"
                ),
            )
        return TaskGraphConditionResult("resolved", value=result.result, rng_events=rng_events)

    def _select_formal_status_branch(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
    ) -> TaskGraphBranchResult:
        task, _node, reason = self._formal_status_task_for_request(request, callback)
        if task is None:
            return TaskGraphBranchResult("blocked", blocked_reason=reason)
        return TaskGraphBranchResult(
            "blocked",
            blocked_reason=f"status_callback_branch_not_admitted:{task.opcode}",
        )

    def _resolve_formal_status_count(
        self,
        request: TaskGraphHookRequest,
        definition: TaskGraphNumericDefinitionIR,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
    ) -> TaskGraphCountResult:
        task, _node, reason = self._formal_status_task_for_request(request, callback)
        references = tuple(
            item for item in request.references if item.reference_kind == "numeric"
        )
        if (
            task is None
            or len(references) != 1
            or references[0].resolution_status != "resolved"
            or references[0].definition_id != definition.definition_id
        ):
            return TaskGraphCountResult(
                "blocked",
                blocked_reason=reason or "status_callback_count_reference_not_resolved",
            )
        evaluation = _evaluate_callback_numeric(
            definition.expression,
            state,
            detail,
            task,
            self.rules,
            template_binding_sources=request.template_binding_sources,
        )
        if (
            not evaluation.ok
            or evaluation.value is None
            or evaluation.value < 0
            or not float(evaluation.value).is_integer()
        ):
            return TaskGraphCountResult(
                "blocked",
                blocked_reason=(
                    evaluation.blocked_reason
                    or "status_callback_loop_count_not_nonnegative_integer"
                ),
            )
        return TaskGraphCountResult("resolved", count=int(evaluation.value))

    def _resolve_formal_status_targets(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
    ) -> TaskGraphTargetResult:
        task, _node, reason = self._formal_status_task_for_request(request, callback)
        if task is None:
            return TaskGraphTargetResult("blocked", blocked_reason=reason)
        scoped_event = _formal_status_scope_event(request, trigger_event)
        resolution = self._resolve_retarget_targets(
            state,
            callback,
            task,
            detail,
            scoped_event,
            scope_target_ids=request.target_ids,
            graph_request=request,
        )
        if not resolution.resolved:
            return TaskGraphTargetResult(
                "blocked",
                blocked_reason=(
                    resolution.blocked_reason
                    or "status_callback_target_resolution_failed"
                ),
            )
        if task.opcode == "Remodifier":
            caster_alias = str(task.task_payload.get("CasterFilter") or "")
            caster_id = (_resolve_callback_target_id(state, detail, caster_alias, scoped_event)
                         if caster_alias else None)
            if caster_alias and caster_id not in state.units:
                return TaskGraphTargetResult("blocked", blocked_reason="remodifier_caster_filter_unresolved")
            maximum = None
            if "MaxNumber" in task.task_payload:
                value = _evaluate_callback_numeric(task.task_payload["MaxNumber"], state, detail,
                    task, self.rules,
                    template_binding_sources=request.template_binding_sources)
                if (not value.ok or value.value is None or value.value < 0
                        or not float(value.value).is_integer()):
                    return TaskGraphTargetResult("blocked",
                        blocked_reason=value.blocked_reason or "remodifier_max_number_invalid")
                maximum = int(value.value)
            predicate = None
            if task.task_payload.get("predicate_filter_required"):
                if not task.condition_id or task.task_payload.get("predicate_condition_id") != task.condition_id:
                    return TaskGraphTargetResult("blocked", blocked_reason="remodifier_predicate_reference_mismatched")
                def predicate(scope):
                    return self._evaluate_formal_status_condition(
                        replace(request, status_scope=scope,
                            invocation_id=f"{request.invocation_id}:filter:{scope.owner_id}:{scope.instance_id}"),
                        state, callback, detail, trigger_event,
                    )
            result = resolve_remodifier_status_scopes(state, task.task_payload,
                resolution.target_ids, caster_id=caster_id, maximum=maximum, predicate=predicate)
            return replace(result, rng_events=(*resolution.rng_events, *result.rng_events)) if result.status == "resolved" else result
        return TaskGraphTargetResult(
            "resolved", target_ids=resolution.target_ids, rng_events=resolution.rng_events,
        )

    def _resolve_formal_status_weighted_selection(
        self,
        request: TaskGraphHookRequest,
        selection: TaskGraphWeightedSelectionIR,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
    ) -> TaskGraphWeightedSelectionResult:
        task, node, reason = self._formal_status_task_for_request(request, callback)
        if task is None or node is None:
            return TaskGraphWeightedSelectionResult("blocked", blocked_reason=reason)
        if task.opcode != "RandomConfig" or selection.graph_node_id != node.graph_node_id:
            return TaskGraphWeightedSelectionResult(
                "blocked", blocked_reason="status_callback_weighted_selection_identity_mismatch",
            )
        weights: list[float] = []
        for definition in selection.numeric_definitions:
            evaluation = _evaluate_callback_numeric(
                definition.expression, state, detail, task, self.rules,
                template_binding_sources=request.template_binding_sources,
            )
            if not evaluation.ok or evaluation.value is None or not math.isfinite(evaluation.value):
                return TaskGraphWeightedSelectionResult(
                    "blocked", blocked_reason=evaluation.blocked_reason or "status_callback_weight_not_resolved",
                )
            weights.append(float(evaluation.value))
        payload = trigger_event.payload if trigger_event is not None and isinstance(trigger_event.payload, dict) else {}
        return resolve_task_graph_weighted_selection(
            request, selection, state, tuple(weights),
            rng_choices=rng_choices_from_payload(payload), rng_mode=rng_mode_from_payload(payload),
        )

    def _execute_legacy_callback(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:

        current_state = state
        heal_ratio_delta = 0.0
        damage_modifiers: list[DamageModifierContribution] = []
        dispatched_event_ids: set[str] = set()
        mutations: list[Mutation] = []
        callback_record, callback_event = _status_callback_envelope(callback, detail, trigger_event)
        records: list[dict[str, JSONValue]] = [callback_record]
        rng_events: list[RNGEvent] = []
        errors: list[str] = []
        events = [callback_event]
        tasks = {task.task_id: task for task in self.rules.status_callback_tasks_for_callback(callback.callback_id)}
        roots = tuple(
            sorted(
                (task for task in tasks.values() if not task.parent_task_id),
                key=lambda item: (item.task_index, item.task_path, item.task_id),
            )
        )
        for task in roots:
            result = self._execute_task(current_state, callback, task, detail, trigger_event, tasks, damage_window_ledger)
            current_state = result.after_state
            heal_ratio_delta += result.heal_ratio_delta
            damage_modifiers.extend(result.damage_modifiers)
            dispatched_event_ids.update(result.dispatched_event_ids)
            mutations.extend(result.mutations)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            events.extend(result.events)
            errors.extend(result.errors)
        if errors:
            reason = f"status_callback_atomic_rollback:{errors[0]}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        callback=callback,
                        detail=detail,
                        reason=reason,
                    ),
                ),
                errors=tuple(errors),
                node_results=(
                    ExecutionNodeResult(
                        node_kind="status_callback",
                        node_id=callback.callback_id,
                        status="blocked",
                        reason_code="status_callback_atomic_precheck_failed",
                    ),
                ),
            )
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
            heal_ratio_delta=heal_ratio_delta,
            damage_modifiers=tuple(damage_modifiers),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def _execute_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        if task.blocked_reason in {"equipment_task_family_non_gameplay", "source_proven_presentation_only", "source_proven_no_effect_branches"}:
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                records=(
                    _task_blocked_record(
                        callback,
                        task,
                        detail,
                        "",
                        ok=True,
                        mutation_count=0,
                        record_count=1,
                    ),
                ),
            )
        if task.opcode in {"ResetStance", "SetStanceCount"}:
            return self._execute_ordinary_stance_recovery_task(state, callback, task, detail, trigger_event)
        if task.opcode == "PredicateTaskList":
            return self._execute_predicate_task(state, callback, task, detail, trigger_event, tasks, damage_window_ledger)
        if task.opcode == "Retarget":
            return self._execute_retarget_task(state, callback, task, detail, trigger_event, tasks, damage_window_ledger)
        if task.opcode in {"IncludeTaskListTemplate", "LoopExecuteTaskList", "RandomConfig"}:
            return self._execute_container_task(
                state,
                callback,
                task,
                detail,
                trigger_event,
                tasks,
                damage_window_ledger,
            )
        if task.opcode == "Remodifier":
            return self._execute_remodifier_query_task(
                state,
                callback,
                task,
                detail,
                trigger_event,
                tasks,
                damage_window_ledger,
            )
        return self._execute_formal_leaf_task(
            state,
            callback,
            task,
            detail,
            trigger_event,
            damage_window_ledger,
        )

    def _execute_ordinary_stance_recovery_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
    ) -> StatusCallbackExecutionResult:
        owner_id = str(detail.get("owner_id") or "")
        unit = state.units.get(owner_id)
        source = unit.flags.get("break_source") if unit is not None else None
        template_id = source.get("break_template_id") if isinstance(source, dict) else None
        template = self.rules.break_template(template_id) if isinstance(template_id, str) else None
        card_id = unit.flags.get("monster_data_card_id") if unit is not None else None
        card = self.rules.monster_data_card(card_id) if isinstance(card_id, str) else None
        template_config = card.raw_parameter_blocks.get("template_config") if card is not None else None
        try:
            segments = read_toughness_segments(unit) if unit is not None else None
        except ValueError:
            segments = None
        admitted = (
            callback.event == "OnDestroy"
            and trigger_event is not None
            and trigger_event.event_type == "status.lifecycle"
            and trigger_event.payload.get("callback_event") == "OnDestroy"
            and trigger_event.target_id == owner_id
            and task.coverage_status == "executable"
            and task.task_payload.get("TargetType") == "ModifierOwnerEntity"
            and "Break" in detail.get("behavior_flags", ())
            and unit is not None and unit.side == "enemy"
            and unit.lifecycle_status == "active" and unit.hp > 0
            and segments is not None and segments.maximum_segments > 0
            and isinstance(template_config, dict)
            and type(template_config.get("stance_count")) is int
            and template_config.get("stance_count") == segments.maximum_segments
            and (segments.maximum_segments == 1 or segments.remaining_segments == 0)
            and unit.flags.get("broken") is True
            and isinstance(source, dict)
            and template is not None and template.coverage_status == "executable"
            and unit.max_toughness > 0
        )
        if not admitted:
            reason = "ordinary_stance_recovery_source_not_admitted"
            return StatusCallbackExecutionResult(
                ok=False, after_state=state, errors=(reason,),
                records=(_task_blocked_record(callback, task, detail, reason),),
            )
        if task.opcode == "SetStanceCount":
            if unit.toughness != unit.max_toughness:
                reason = "ordinary_stance_reset_not_committed"
                return StatusCallbackExecutionResult(
                    ok=False, after_state=state, errors=(reason,),
                    records=(_task_blocked_record(callback, task, detail, reason),),
                )
            if segments.maximum_segments == 1:
                return StatusCallbackExecutionResult(
                    ok=True, after_state=state,
                    records=(_task_blocked_record(callback, task, detail, "", ok=True),),
                )
        elif task.opcode != "ResetStance" or unit.toughness != 0:
            reason = "ordinary_stance_reset_requires_depleted_toughness"
            return StatusCallbackExecutionResult(
                ok=False, after_state=state, errors=(reason,),
                records=(_task_blocked_record(callback, task, detail, reason),),
            )
        trace = {
            "callback_source": callback.source.to_json(),
            "task_source": task.source.to_json(),
            "break_source": source,
            "monster_data_card_id": unit.flags.get("monster_data_card_id"),
        }
        mutation = Mutation(
            op="set",
            path=(("units", owner_id, "flags", "stance_segments_remaining")
                  if task.opcode == "SetStanceCount" else ("units", owner_id, "toughness")),
            before=segments.remaining_segments if task.opcode == "SetStanceCount" else unit.toughness,
            after=segments.maximum_segments if task.opcode == "SetStanceCount" else unit.max_toughness,
            reason="restore ordinary toughness before next action",
            source="status_callback_system",
            metadata={
                "ordinary_reset_stance": True,
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "target_id": owner_id,
                "max_toughness": unit.max_toughness,
                "monster_stance_count": segments.maximum_segments,
                "source_trace": trace,
            },
        )
        reduction = self.reducer.apply_all_result(state, (mutation,))
        if not reduction.ok:
            reason = "ordinary_stance_reset_mutation_conflict"
            return StatusCallbackExecutionResult(
                ok=False, after_state=state, errors=(reason,),
                records=(_task_blocked_record(callback, task, detail, reason),),
            )
        return StatusCallbackExecutionResult(
            ok=True, after_state=reduction.after_state,
            mutations=(mutation,),
            records=(SettlementRecord(
                record_type=("ordinary_stance_count_reset" if task.opcode == "SetStanceCount"
                             else "ordinary_stance_reset"), source="status_callback_system",
                mutation_id=mutation.stable_id(),
                payload={"target_id": owner_id, "callback_id": callback.callback_id, "task_id": task.task_id},
                trace=trace,
            ).to_json(),),
        )

    def _execute_formal_leaf_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
        *,
        status_scope: TaskGraphStatusScope | None = None,
        template_target_ids: tuple[str, ...] | None = None,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
        task_graph_continuation: TaskGraphContinuation | None = None,
    ) -> StatusCallbackExecutionResult:
        if task.opcode == "TriggerBreak":
            fact = trigger_event.break_notification_fact if trigger_event is not None else None
            owner_id = str(detail.get("owner_id") or "")
            caster_id = str(detail.get("caster_id") or "")
            if (
                task.coverage_status != "executable" or task.blocked_reason
                or task.event != "OnCreate" or callback.event != "OnCreate"
                or task.task_payload.get("TargetType") != "Caster"
                or trigger_event is None or trigger_event.event_type != "status.lifecycle"
                or type(fact) is not BreakNotificationFact
                or owner_id != caster_id or trigger_event.target_id != owner_id
                or not fact.matches(state, caster_id)
            ):
                reason = "break_trigger_notification_context_missing_or_mismatched"
                return StatusCallbackExecutionResult(
                    ok=False, after_state=state, errors=(reason,),
                    records=(_task_blocked_record(callback, task, detail, reason),),
                )
            # The enclosing ordinary-break producer already owns this target's
            # notification. Re-emitting it from OnCreate would notify twice.
            return StatusCallbackExecutionResult(
                ok=True, after_state=state,
                records=(SettlementRecord(
                    record_type="break_notification", source="status_callback_system",
                    process_only=True,
                    payload={
                        "callback_id": callback.callback_id, "task_id": task.task_id,
                        "target_id": owner_id, "notification_event_id": fact.event_id,
                        "notification_owner": "break_system",
                        "source_mutation_id": fact.source_mutation.stable_id(),
                    },
                    trace={"status_callback_source": callback.source.to_json(),
                           "status_task_source": task.source.to_json()},
                ).to_json(),),
            )
        if task.blocked_reason in {"equipment_task_family_non_gameplay", "source_proven_presentation_only"}:
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                records=(
                    _task_blocked_record(
                        callback,
                        task,
                        detail,
                        "",
                        ok=True,
                        mutation_count=0,
                        record_count=1,
                    ),
                ),
            )
        if task.opcode == "ModifyCurrentSkillDelayCost":
            return self._execute_current_skill_delay_cost_task(
                state,
                callback,
                task,
                detail,
                trigger_event,
                template_binding_sources=template_binding_sources,
            )
        if task.opcode == "SetResilience":
            return self._execute_shield_resilience_sync_task(
                state,
                callback,
                task,
                detail,
            )
        if task.opcode == "AttachSkillTypeDisable":
            unit = state.units.get(str(detail.get("owner_id") or ""))
            active = [item for item in unit.flags.get("status_details", ())
                      if isinstance(item, dict) and item.get("instance_id") == detail.get("instance_id")] if unit else []
            contract = task.task_payload.get("skill_disable_contract", {})
            types = contract.get("skill_types") if isinstance(contract, dict) else None
            admitted = (
                task.coverage_status == "executable" and not task.blocked_reason
                and task.event == callback.event == "OnStack"
                and task.callback_id == callback.callback_id
                and task.modifier_name == callback.modifier_name == detail.get("modifier_name")
                and isinstance(contract, dict)
                and set(contract) == {"operation", "target_alias", "skill_types", "source_shape_admitted"}
                and contract.get("operation") == "attach_status_skill_type_disable"
                and contract.get("source_shape_admitted") is True
                and (contract.get("target_alias") == "ModifierOwnerEntity" or (
                    contract.get("target_alias") == "Caster" and detail.get("caster_id") == detail.get("owner_id")))
                and isinstance(types, list) and bool(types)
                and all(isinstance(item, str) and item in {"Normal", "Skill", "Ultra"} for item in types)
                and len(active) == 1 and active[0].get("lifecycle_state") == "active"
                and active[0].get("status_id") in unit.statuses
                and all(detail.get(key) and active[0].get(key) == detail[key]
                        for key in ("owner_id", "caster_id", "source_id", "status_id", "modifier_name"))
            )
            if not admitted:
                reason = "attached_skill_disable_status_instance_not_admitted"
                return StatusCallbackExecutionResult(False, state, errors=(reason,),
                    records=(_task_blocked_record(callback, task, detail, reason),))
            before = unit.flags["status_details"]
            after = [{**item, "disabled_skill_types": sorted(set(item.get("disabled_skill_types", ())) | set(types))}
                     if item.get("instance_id") == detail["instance_id"] else item for item in before]
            mutation = None if after == before else Mutation(
                "set", ("units", unit.unit_id, "flags", "status_details"), before, after,
                "attach skill restrictions to their source status lifetime", "status_callback_system",
                metadata={"callback_id": callback.callback_id, "task_id": task.task_id,
                          "source_trace": task.source.to_json(), "status_instance_id": detail["instance_id"]},
            )
            after_state = self.reducer.apply_all(state, (mutation,)) if mutation is not None else state
            return StatusCallbackExecutionResult(True, after_state, mutations=(mutation,) if mutation is not None else (), records=(SettlementRecord(
                record_type="status_skill_type_disable", source="status_callback_system",
                mutation_id=mutation.stable_id() if mutation is not None else None, process_only=mutation is None,
                payload={"status_instance_id": detail["instance_id"], "skill_types": types},
                trace={"status_callback_source": callback.source.to_json(), "status_task_source": task.source.to_json()},
            ).to_json(),))
        if task.opcode == "StackStatusResistance":
            installed = tuple(
                item for item in detail.get("modifiers", ())
                if isinstance(item, dict)
                and item.get("opcode") == task.opcode
                and item.get("producer_task_path") == task.task_path
                and item.get("producer_key") == task.task_payload.get("status_resistance_producer_key")
                and bool(item.get("producer_key"))
                and item.get("bucket") == "status_resistance"
                and item.get("key") == "STAT_CTRL"
            )
            if task.coverage_status != "executable" or task.blocked_reason or task.event != "OnStack" or len(installed) != 1:
                reason = "status_resistance_installation_not_admitted"
                return StatusCallbackExecutionResult(
                    ok=False, after_state=state, errors=(reason,),
                    records=(_task_blocked_record(callback, task, detail, reason),),
                )
        if task.opcode == "StackProperty":
            detail = _current_status_detail(state, detail)
            alias = task.task_payload.get("TargetType")
            installed = tuple(
                item for item in detail.get("modifiers", ())
                if isinstance(item, dict)
                and item.get("property") == task.task_payload.get("Property")
                and (item.get("producer_task_id") == task.task_id or (
                    isinstance(item.get("raw_path"), str) and item["raw_path"]
                    and task.task_path.endswith("." + item["raw_path"])))
            )
            holder_target = alias == "ModifierOwnerEntity" or (
                alias == "Caster" and detail.get("caster_id") == detail.get("owner_id")
            )
            refresh_shaped = task.task_payload.get("IsRefresh") is True
            if (task.coverage_status != "executable" or task.blocked_reason
                    or (task.event != "OnStack" and not refresh_shaped)
                    or not holder_target or len(installed) > 1):
                reason = "stack_property_installation_not_admitted"
                return StatusCallbackExecutionResult(
                    ok=False, after_state=state, errors=(reason,),
                    records=(_task_blocked_record(callback, task, detail, reason),),
                )
            value = _evaluate_callback_numeric(
                task.task_payload.get("PropertyValue"), state, detail, task, self.rules,
                template_binding_sources=template_binding_sources,
            )
            if not value.ok or value.value is None:
                reason = value.blocked_reason or "stack_property_value_unresolved"
                return StatusCallbackExecutionResult(
                    ok=False, after_state=state, errors=(reason,),
                    records=(_task_blocked_record(callback, task, detail, reason),),
                )
            mapped = _map_stack_property(str(task.task_payload.get("Property") or ""))
            if not installed and mapped is None:
                reason = "stack_property_name_not_admitted"
                return StatusCallbackExecutionResult(False, state, errors=(reason,),
                    records=(_task_blocked_record(callback, task, detail, reason),))
            if not installed or installed[0].get("value") != value.value:
                owner_id = str(detail["owner_id"])
                unit = state.units[owner_id]
                before = list(unit.flags["status_details"])
                # A preinstalled modifier entry (formal _runtime_modifiers) only
                # carries its raw_path; the producer identity is filled in when
                # this task owns the value, including the in-place update path.
                modifiers = [
                    _evaluated_stack_property_entry(
                        item,
                        task_id=task.task_id,
                        task_path=task.task_path,
                        value=value.value,
                    ) if item == installed[0] else item
                    for item in detail.get("modifiers", ())
                ] if installed else [
                    *detail.get("modifiers", ()),
                    {"bucket": mapped[0], "key": mapped[1], "scope": mapped[2],
                     "value": value.value, "property": task.task_payload["Property"],
                     "producer_task_id": task.task_id, "producer_task_path": task.task_path,
                     "raw_path": task.task_path,
                     "applied_reason": "status_stack_property"},
                ]
                after = [{**item, "modifiers": modifiers} if item.get("instance_id") == detail["instance_id"] else item
                         for item in before]
                mutation = Mutation(
                    "set", ("units", owner_id, "flags", "status_details"), before, after,
                    "evaluate status property at its source task", "status_callback_system",
                    metadata={"callback_id": callback.callback_id, "task_id": task.task_id,
                              "status_instance_id": detail["instance_id"], "source_trace": task.source.to_json(),
                              "numeric_evaluation": value.to_json()},
                )
                clamp = _hp_cap_clamp_after_attribute_write(
                    state,
                    owner_id,
                    list(unit.statuses),
                    list(after),
                    source_trace=task.source.to_json(),
                    status_id=str(detail.get("status_id") or ""),
                    status_instance_id=str(detail["instance_id"]),
                    operation="modify_status_property",
                    attribute_write={
                        "operation": "modify_status_property",
                        "property": str(task.task_payload.get("Property") or ""),
                        "before_value": (
                            installed[0].get("value") if installed else None
                        ),
                        "after_value": value.value,
                        "task_id": task.task_id,
                        "callback_id": callback.callback_id,
                        "modifier_name": task.modifier_name,
                    },
                )
                mutations: tuple[Mutation, ...] = (
                    (mutation, clamp[0]) if clamp is not None else (mutation,)
                )
                reduction = self.reducer.apply_all_result(state, mutations)
                if not reduction.ok:
                    return StatusCallbackExecutionResult(ok=False, after_state=state,
                        errors=("stack_property_mutation_conflict",), records=())
                records: tuple[dict[str, JSONValue], ...] = (
                    SettlementRecord(
                        "status_stack_property", "status_callback_system", mutation_id=mutation.stable_id(),
                        payload={"status_instance_id": detail["instance_id"], "property": task.task_payload["Property"],
                                 "before": installed[0].get("value") if installed else None, "after": value.value,
                                 "numeric_evaluation": value.to_json()}, trace=task.source.to_json(),
                    ).to_json(),
                    *((clamp[1],) if clamp is not None else ()),
                )
                clamp_events = (
                    events_for_mutation(
                        clamp[0],
                        actor_id=owner_id,
                        source_id=owner_id,
                        event_index=state.event_index,
                    )
                    if clamp is not None
                    else ()
                )
                return StatusCallbackExecutionResult(
                    ok=True, after_state=reduction.after_state, mutations=mutations,
                    events=clamp_events, records=records,
                )
        if task.opcode in {"StackProperty", "StackStatusResistance"}:
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                records=(
                    _task_blocked_record(
                        callback,
                        task,
                        detail,
                        "",
                        ok=True,
                        mutation_count=0,
                        record_count=1,
                    ),
                ),
            )
        if task.opcode == "ModifyHealData":
            return self._execute_modify_heal_data_task(
                state,
                callback,
                task,
                detail,
                template_binding_sources=template_binding_sources,
            )
        if task.opcode == "ModifyDamageData":
            return self._execute_damage_modifier_task(
                state,
                callback,
                task,
                detail,
                template_binding_sources=template_binding_sources,
            )
        delay_emissions = [
            emission
            for emission in self.rules.action_delay_emissions_for_callback(callback.callback_id)
            if emission.source_task_id == task.task_id
        ]
        damage_emissions = [
            emission
            for emission in self.rules.status_damage_emissions_for_callback(callback.callback_id)
            if emission.source_task_id == task.task_id
        ]
        queue_intents = [
            intent
            for intent in self.rules.queue_intents_for_callback(callback.callback_id)
            if intent.source_task_id == task.task_id
        ]
        if task.coverage_status != "executable":
            if queue_intents:
                reason = task.blocked_reason or f"status_callback_task_not_executable:{task.coverage_status}"
                return self._blocked_queue_intents(state, callback, task, detail, tuple(queue_intents), reason)
            if delay_emissions:
                return self._execute_delay_emissions(state, callback, task, detail, trigger_event, tuple(delay_emissions))
            if damage_emissions:
                records = tuple(
                    _status_damage_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        emission.blocked_reason or task.blocked_reason or f"status_damage_not_executable:{emission.coverage_status}",
                    )
                    for emission in damage_emissions
                )
                errors = tuple(
                    emission.blocked_reason or task.blocked_reason or f"status_damage_not_executable:{emission.coverage_status}"
                    for emission in damage_emissions
                )
                return StatusCallbackExecutionResult(ok=False, after_state=state, records=records, errors=errors)
            reason = task.blocked_reason or f"status_callback_task_not_executable:{task.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        if damage_emissions:
            return self._execute_damage_emissions(
                state,
                callback,
                task,
                detail,
                trigger_event,
                tuple(damage_emissions),
                damage_window_ledger,
                template_binding_sources=template_binding_sources,
            )
        if delay_emissions:
            return self._execute_delay_emissions(state, callback, task, detail, trigger_event, tuple(delay_emissions),
                template_binding_sources=template_binding_sources)
        if queue_intents:
            return self._execute_queue_intents(
                state,
                callback,
                task,
                detail,
                trigger_event,
                tuple(queue_intents),
                task_graph_continuation=task_graph_continuation,
            )
        if task.effect_id:
            return self._execute_effect_task(state, callback, task, detail, trigger_event, damage_window_ledger,
                status_scope=status_scope, template_target_ids=template_target_ids,
                template_binding_sources=template_binding_sources,
                task_graph_continuation=task_graph_continuation)
        reason = "status_callback_task_has_no_executable_runtime_effect"
        return StatusCallbackExecutionResult(
            ok=False,
            after_state=state,
            records=(_task_blocked_record(callback, task, detail, reason),),
            errors=(reason,),
        )

    def _execute_container_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or f"container_task_not_executable:{task.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        if not task.child_task_ids:
            reason = f"container_child_task_missing:{task.opcode}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        if task.opcode == "IncludeTaskListTemplate":
            return self._execute_child_sequence(
                state,
                callback,
                task,
                detail,
                trigger_event,
                tasks,
                damage_window_ledger,
                task.child_task_ids,
                container_metadata={
                    "container_opcode": task.opcode,
                    "template_name": task.task_payload.get("template_name"),
                },
            )
        if task.opcode == "LoopExecuteTaskList":
            evaluation = _evaluate_callback_numeric(
                task.task_payload.get("MaxLoopCount"),
                state,
                detail,
                task,
                self.rules,
            )
            if not evaluation.ok or evaluation.value is None:
                reason = evaluation.blocked_reason or "loop_count_not_resolved"
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    records=(_task_blocked_record(callback, task, detail, reason),),
                    errors=(reason,),
                )
            loop_count = int(evaluation.value)
            if float(loop_count) != float(evaluation.value) or loop_count < 0:
                reason = "loop_count_must_be_non_negative_integer"
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    records=(_task_blocked_record(callback, task, detail, reason),),
                    errors=(reason,),
                )
            current_state = state
            mutations: list[Mutation] = []
            records: list[dict[str, JSONValue]] = []
            events: list[GameEvent] = []
            rng_events: list[RNGEvent] = []
            heal_ratio_delta = 0.0
            damage_modifiers: list[DamageModifierContribution] = []
            dispatched_event_ids: set[str] = set()
            for loop_index in range(loop_count):
                scoped_event = _callback_scoped_event(
                    trigger_event,
                    callback_scope=f"{task.task_id}:loop",
                    decision_index=loop_index,
                )
                result = self._execute_child_sequence(
                    current_state,
                    callback,
                    task,
                    detail,
                    scoped_event,
                    tasks,
                    damage_window_ledger,
                    task.child_task_ids,
                    container_metadata={
                        "container_opcode": task.opcode,
                        "loop_index": loop_index,
                        "loop_count": loop_count,
                    },
                )
                if not result.ok:
                    reason = result.errors[0] if result.errors else "loop_child_failed"
                    return StatusCallbackExecutionResult(
                        ok=False,
                        after_state=state,
                        records=(_task_blocked_record(callback, task, detail, f"loop_atomic_rollback:{reason}"),),
                        errors=(reason,),
                    )
                current_state = result.after_state
                heal_ratio_delta += result.heal_ratio_delta
                damage_modifiers.extend(result.damage_modifiers)
                dispatched_event_ids.update(result.dispatched_event_ids)
                mutations.extend(result.mutations)
                records.extend(result.records)
                events.extend(result.events)
                rng_events.extend(result.rng_events)
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=current_state,
                mutations=tuple(mutations),
                records=tuple(records),
                events=tuple(events),
                rng_events=tuple(rng_events),
                heal_ratio_delta=heal_ratio_delta,
                damage_modifiers=tuple(damage_modifiers),
                dispatched_event_ids=frozenset(dispatched_event_ids),
            )
        return self._execute_random_config_task(
            state,
            callback,
            task,
            detail,
            trigger_event,
            tasks,
            damage_window_ledger,
        )

    def _execute_random_config_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        raw_weights = task.task_payload.get("OddsList")
        if not isinstance(raw_weights, list) or len(raw_weights) != len(task.child_task_ids):
            reason = "random_config_weight_child_count_mismatch"
            return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        weights: list[float] = []
        for expression in raw_weights:
            evaluation = _evaluate_callback_numeric(
                expression,
                state,
                detail,
                task,
                self.rules,
            )
            if not evaluation.ok or evaluation.value is None or evaluation.value < 0:
                reason = evaluation.blocked_reason or "random_config_weight_not_resolved"
                return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
            weights.append(float(evaluation.value))
        if sum(weights) <= 0:
            reason = "random_config_weights_empty"
            return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        event_payload = trigger_event.payload if trigger_event is not None and isinstance(trigger_event.payload, dict) else {}
        decision_index = event_payload.get("callback_decision_index", 0)
        if type(decision_index) is not int or decision_index < 0:
            decision_index = 0
        identity: dict[str, JSONValue] = {
            "decision_scope": f"status_callback:{callback.callback_id}",
            "decision_index": decision_index,
            "task_id": task.task_id,
            "status_id": str(detail.get("instance_id") or detail.get("status_id") or ""),
            "owner_id": str(detail.get("owner_id") or ""),
            "trigger_event_id": trigger_event.event_id if trigger_event is not None else "",
        }
        choice_key = choice_key_for_identity("status_callback_random_config", identity)
        request = RNGRequest(
            rng_type="status_callback_random_config",
            purpose="select exactly one RandomConfig child",
            event_id=event_id_for_identity(
                "status_callback_random_config",
                identity,
                event_index=state.event_index,
            ),
            choice_key=choice_key,
            source=task.task_id,
            before_state=state.rng_state,
            decision_kind="weighted",
            outcomes=tuple(
                RNGOutcome(
                    outcome_id=f"branch:{index}",
                    payload={"child_task_id": child_id, "branch_index": index},
                    weight=weight,
                )
                for index, (child_id, weight) in enumerate(zip(task.child_task_ids, weights, strict=True))
            ),
            source_trace={
                "callback_source": callback.source.to_json(),
                "task_source": task.source.to_json(),
                "status_source": _json_dict(detail.get("source_trace")),
            },
            identity=identity,
        )
        resolution = resolve_rng_request(
            request,
            rng_choices=rng_choices_from_payload(event_payload),
            rng_mode=rng_mode_from_payload(event_payload),
        )
        if not resolution.ok or resolution.selected_outcome is None:
            reason = resolution.blocked_reason or "random_config_choice_unresolved"
            return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        child_id = resolution.selected_outcome.payload.get("child_task_id")
        if not isinstance(child_id, str) or child_id not in tasks:
            reason = "random_config_selected_child_missing"
            return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        result = self._execute_child_sequence(
            state,
            callback,
            task,
            detail,
            trigger_event,
            tasks,
            damage_window_ledger,
            (child_id,),
            container_metadata={
                "container_opcode": task.opcode,
                "choice_key": choice_key,
                "selected_child_id": child_id,
            },
        )
        if not result.ok:
            return result
        return replace(
            result,
            rng_events=(
                *((resolution.event,) if resolution.event is not None else ()),
                *result.rng_events,
            ),
        )

    def _execute_child_sequence(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        parent_task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
        child_ids: tuple[str, ...],
        *,
        container_metadata: dict[str, JSONValue],
    ) -> StatusCallbackExecutionResult:
        current_state = state
        heal_ratio_delta = 0.0
        damage_modifiers: list[DamageModifierContribution] = []
        dispatched_event_ids: set[str] = set()
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = [
            _task_blocked_record(
                callback,
                parent_task,
                detail,
                "",
                ok=True,
                selected_child_ids=child_ids,
            )
        ]
        payload = records[0].get("payload")
        if isinstance(payload, dict):
            payload["container"] = container_metadata
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        for child_id in child_ids:
            child = tasks.get(child_id)
            if child is None:
                reason = f"missing_child_task:{child_id}"
                return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, parent_task, detail, reason),), errors=(reason,))
            result = self._execute_task(
                current_state,
                callback,
                child,
                detail,
                trigger_event,
                tasks,
                damage_window_ledger,
            )
            if not result.ok:
                reason = result.errors[0] if result.errors else "container_child_failed"
                return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, parent_task, detail, f"container_atomic_rollback:{reason}"),), errors=(reason,))
            current_state = result.after_state
            heal_ratio_delta += result.heal_ratio_delta
            damage_modifiers.extend(result.damage_modifiers)
            dispatched_event_ids.update(result.dispatched_event_ids)
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
        return StatusCallbackExecutionResult(
            True,
            current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=tuple(events),
            rng_events=tuple(rng_events),
            heal_ratio_delta=heal_ratio_delta,
            damage_modifiers=tuple(damage_modifiers),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def _execute_predicate_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        condition = self.rules.condition(task.condition_id) if task.condition_id else None
        if condition is None:
            reason = "missing_predicate_condition"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        result, condition_rng_events, evaluated_event = self._evaluate_callback_condition(
            condition,
            state,
            callback,
            task,
            detail,
            trigger_event,
        )
        if not result.ok or result.result is None:
            reason = f"blocked_condition:{condition.condition_id}:{result.reason}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                rng_events=condition_rng_events,
                records=(_task_blocked_record(callback, task, detail, reason, condition_result=result.to_json()),),
                errors=(reason,),
            )
        selected_child_ids = task.success_task_ids if result.result else task.failed_task_ids
        current_state = state
        heal_ratio_delta = 0.0
        damage_modifiers: list[DamageModifierContribution] = []
        dispatched_event_ids: set[str] = set()
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = [
            _task_blocked_record(
                callback,
                task,
                detail,
                "",
                ok=True,
                condition_result=result.to_json(),
                selected_child_ids=selected_child_ids,
            )
        ]
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = list(condition_rng_events)
        errors: list[str] = []
        precheck_result = self._precheck_selected_queue_group(
            state,
            callback,
            task,
            detail,
            evaluated_event,
            selected_child_ids,
            tasks,
        )
        if precheck_result is not None:
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=tuple(records) + precheck_result.records,
                errors=precheck_result.errors,
            )
        for child_id in selected_child_ids:
            child = tasks.get(child_id)
            if child is None:
                reason = f"missing_child_task:{child_id}"
                records.append(_task_blocked_record(callback, task, detail, reason))
                errors.append(reason)
                continue
            child_result = self._execute_task(
                current_state,
                callback,
                child,
                detail,
                evaluated_event,
                tasks,
                damage_window_ledger,
            )
            current_state = child_result.after_state
            heal_ratio_delta += child_result.heal_ratio_delta
            damage_modifiers.extend(child_result.damage_modifiers)
            dispatched_event_ids.update(child_result.dispatched_event_ids)
            mutations.extend(child_result.mutations)
            rng_events.extend(child_result.rng_events)
            records.extend(child_result.records)
            events.extend(child_result.events)
            errors.extend(child_result.errors)
        if errors:
            reason = f"predicate_child_atomic_rollback:{errors[0]}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _task_blocked_record(
                        callback,
                        task,
                        detail,
                        reason,
                        condition_result=result.to_json(),
                        selected_child_ids=selected_child_ids,
                    ),
                ),
                errors=tuple(errors),
            )
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
            heal_ratio_delta=heal_ratio_delta,
            damage_modifiers=tuple(damage_modifiers),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def _evaluate_callback_condition(
        self,
        condition,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        *,
        selected_target_ids: tuple[str, ...] = (),
        rng_identity_scope: tuple[object, ...] = (),
        transient_condition_provider: TransientConditionOperandProvider | None = None,
        template_target_ids: tuple[str, ...] | None = None,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
        immunity_trigger_event: GameEvent | None = None,
    ) -> tuple[ConditionEvaluationResult, tuple[RNGEvent, ...], GameEvent | None]:
        chance_nodes = _condition_random_chance_nodes(condition)
        if not chance_nodes:
            return (
                self.evaluator.evaluate_condition_result(
                    condition,
                    _condition_context(
                        self.rules,
                        state,
                        detail,
                        trigger_event,
                        condition=condition,
                        targets=self.targets,
                        selected_target_ids=selected_target_ids,
                        transient_condition_provider=transient_condition_provider,
                        template_target_ids=template_target_ids,
                        template_binding_sources=template_binding_sources,
                        immunity_trigger_event=immunity_trigger_event,
                    ),
                ),
                (),
                trigger_event,
            )
        if len(chance_nodes) != 1:
            blocked = ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason="multiple_random_condition_nodes_require_distinct_identity",
                details={"node_paths": [path for path, _ in chance_nodes]},
                source_trace=condition.source.to_json(),
            )
            return blocked, (), trigger_event
        node_path, chance_expr = chance_nodes[0]
        evaluation = _evaluate_callback_numeric(
            chance_expr,
            state,
            detail,
            task,
            self.rules,
            template_binding_sources=template_binding_sources,
        )
        if not evaluation.ok or evaluation.value is None or not 0.0 <= evaluation.value <= 1.0:
            blocked = ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason=evaluation.blocked_reason or "random_condition_chance_out_of_range",
                details={"node_path": node_path, "numeric_evaluation": evaluation.to_json()},
                source_trace=condition.source.to_json(),
            )
            return blocked, (), trigger_event
        payload = trigger_event.payload if trigger_event is not None and isinstance(trigger_event.payload, dict) else {}
        decision_index = payload.get("callback_decision_index", 0)
        if type(decision_index) is not int or decision_index < 0:
            decision_index = 0
        identity: dict[str, JSONValue] = {
            "decision_scope": f"status_condition:{callback.callback_id}",
            "decision_index": decision_index,
            "task_id": task.task_id,
            "status_id": str(detail.get("instance_id") or detail.get("status_id") or ""),
            "condition_id": condition.condition_id,
            "condition_node_path": node_path,
            "owner_id": str(detail.get("owner_id") or ""),
        }
        if rng_identity_scope:
            identity["task_graph_scope"] = list(rng_identity_scope)
        choice_key = choice_key_for_identity("status_condition_chance", identity)
        request = RNGRequest(
            rng_type="status_condition_chance",
            purpose="resolve ByRandomChance",
            event_id=event_id_for_identity(
                "status_condition_chance",
                identity,
                event_index=state.event_index,
            ),
            choice_key=choice_key,
            source=condition.condition_id,
            before_state=state.rng_state,
            decision_kind="probability",
            outcomes=(
                RNGOutcome(
                    outcome_id="pass",
                    payload={"condition_result": True},
                    probability=float(evaluation.value),
                ),
                RNGOutcome(
                    outcome_id="fail",
                    payload={"condition_result": False},
                    probability=1.0 - float(evaluation.value),
                ),
            ),
            source_trace={
                "condition_source": condition.source.to_json(),
                "task_source": task.source.to_json(),
                "status_source": _json_dict(detail.get("source_trace")),
            },
            identity=identity,
        )
        resolution = resolve_rng_request(
            request,
            rng_choices=rng_choices_from_payload(payload),
            rng_mode=rng_mode_from_payload(payload),
        )
        if not resolution.ok or resolution.selected_outcome is None:
            blocked = ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason=resolution.blocked_reason or "random_condition_choice_unresolved",
                details=resolution.blocked_payload(),
                source_trace=condition.source.to_json(),
            )
            return blocked, (), trigger_event
        selected = resolution.selected_outcome.payload.get("condition_result")
        if not isinstance(selected, bool):
            blocked = ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason="random_condition_outcome_invalid",
                details={"selected_outcome": resolution.selected_outcome.to_json()},
                source_trace=condition.source.to_json(),
            )
            return blocked, (), trigger_event
        evaluated_event = _condition_rng_event(
            trigger_event,
            selected=selected,
            choice_key=choice_key,
        )
        result = self.evaluator.evaluate_condition_result(
            condition,
            _condition_context(
                self.rules,
                state,
                detail,
                evaluated_event,
                condition=condition,
                targets=self.targets,
                selected_target_ids=selected_target_ids,
                transient_condition_provider=transient_condition_provider,
                template_target_ids=template_target_ids,
                template_binding_sources=template_binding_sources,
                immunity_trigger_event=immunity_trigger_event,
            ),
        )
        return (
            result,
            ((resolution.event,) if resolution.event is not None else ()),
            evaluated_event,
        )

    def _resolve_retarget_targets(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        *,
        scope_target_ids: tuple[str, ...] = (),
        graph_request: TaskGraphHookRequest | None = None,
    ) -> TargetExpressionResult:
        target_expression_id, target_link_reason = _callback_task_target_expression_id(
            self.rules,
            task,
        )
        if target_link_reason:
            return TargetExpressionResult(
                "blocked",
                blocked_reason=target_link_reason,
            )
        expression = (
            self.rules.target_expression(target_expression_id)
            if target_expression_id
            else None
        )
        if expression is None:
            reason = (
                f"retarget_target_expression_missing:{target_expression_id}"
                if target_expression_id
                else "missing_retarget_target_expression"
            )
            return TargetExpressionResult("blocked", blocked_reason=reason)
        event_payload = (
            dict(trigger_event.payload)
            if trigger_event is not None and isinstance(trigger_event.payload, dict)
            else {}
        )
        event_payload.update(
            {
                "status_instance_id": str(detail.get("instance_id") or ""),
                "status_id": str(detail.get("status_id") or ""),
                "modifier_name": callback.modifier_name,
            }
        )
        if graph_request is not None:
            event_payload.update({
                "task_id": graph_request.formal_task_id,
                "rng_decision_index": graph_request.iteration_index or 0,
                "event_id": (
                    f"{trigger_event.event_id if trigger_event is not None else 'direct'}:"
                    f"{graph_request.invocation_id}:{graph_request.graph_node_id}:"
                    f"{':'.join(graph_request.frame_ids)}"
                ),
            })
        caster_id = str(detail.get("caster_id") or detail.get("owner_id") or "")
        owner_id = str(detail.get("owner_id") or caster_id)
        param_entity_id = _resolve_callback_target_id(
            state,
            detail,
            "ParamEntity",
            trigger_event,
        )
        scoped_ids = scope_target_ids or (
            (param_entity_id,) if param_entity_id else ()
        )
        return self.targets.resolve_target_expression(
            state,
            expression,
            context=TargetEvaluationContext(
                caster_id=caster_id,
                effect_owner_id=owner_id,
                template_entity_ids=graph_request.template_target_ids if graph_request is not None else None,
                parameter_entity_ids=scoped_ids,
                selected_target_ids=scoped_ids,
                current_target_id=(scoped_ids[0] if scoped_ids else None),
                event_source_id=(
                    trigger_event.source_id
                    if trigger_event is not None and trigger_event.source_id in state.units
                    else None
                ),
                event_target_id=(
                    trigger_event.target_id if trigger_event is not None else None
                ),
                turn_owner_id=committed_turn_owner_id(state),
                action_event_id=(
                    trigger_event.event_id if trigger_event is not None else None
                ),
                action_window=(
                    trigger_event.window if trigger_event is not None else None
                ),
                admitted_action_target_fact=(
                    trigger_event.admitted_action_target_fact
                    if trigger_event is not None
                    else None
                ),
                expected_action_window_scope=(
                    trigger_event.expected_action_window_scope
                    if trigger_event is not None
                    else None
                ),
            ),
            condition_event_payload=event_payload,
            binding_sources=with_template_binding_sources(tuple(
                status_binding_sources(
                    state,
                    tuple(
                        unit_id
                        for unit_id in (owner_id, caster_id)
                        if unit_id
                    ),
                )
            ), graph_request.template_binding_sources if graph_request is not None else ()),
        )

    def _execute_retarget_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or f"retarget_task_not_executable:{task.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        resolution = self._resolve_retarget_targets(
            state,
            callback,
            task,
            detail,
            trigger_event,
        )
        if not resolution.resolved:
            reason = resolution.blocked_reason or "retarget_resolution_failed"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                rng_events=resolution.rng_events,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        if not resolution.target_ids:
            record = _task_blocked_record(
                callback,
                task,
                detail,
                "",
                ok=True,
                selected_child_ids=(),
            )
            payload = record.get("payload")
            if isinstance(payload, dict):
                payload["target_expression_resolution"] = resolution.to_json()
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                rng_events=resolution.rng_events,
                records=(record,),
            )
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = list(resolution.rng_events)
        heal_ratio_delta = 0.0
        damage_modifiers: list[DamageModifierContribution] = []
        dispatched_event_ids: set[str] = set()
        for target_index, candidate_id in enumerate(resolution.target_ids):
            retarget_event = _callback_scoped_event(
                _retarget_event(trigger_event, candidate_id),
                callback_scope=f"{task.task_id}:retarget",
                decision_index=target_index,
            )
            child_result = self._execute_child_sequence(
                current_state,
                callback,
                task,
                detail,
                retarget_event,
                tasks,
                damage_window_ledger,
                task.child_task_ids,
                container_metadata={
                    "container_opcode": task.opcode,
                    "retarget_target_id": candidate_id,
                    "retarget_target_index": target_index,
                    "target_expression_id": task.target_expression_id,
                },
            )
            if not child_result.ok:
                reason = child_result.errors[0] if child_result.errors else "retarget_child_failed"
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple(rng_events),
                    records=(_task_blocked_record(callback, task, detail, f"retarget_atomic_rollback:{reason}"),),
                    errors=(reason,),
                )
            current_state = child_result.after_state
            heal_ratio_delta += child_result.heal_ratio_delta
            damage_modifiers.extend(child_result.damage_modifiers)
            dispatched_event_ids.update(child_result.dispatched_event_ids)
            mutations.extend(child_result.mutations)
            rng_events.extend(child_result.rng_events)
            records.extend(child_result.records)
            events.extend(child_result.events)
        summary = _task_blocked_record(
            callback,
            task,
            detail,
            "",
            ok=True,
            selected_child_ids=task.child_task_ids,
        )
        summary_payload = summary.get("payload")
        if isinstance(summary_payload, dict):
            summary_payload["target_expression_resolution"] = resolution.to_json()
        records.insert(0, summary)
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
            heal_ratio_delta=heal_ratio_delta,
            damage_modifiers=tuple(damage_modifiers),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def _execute_effect_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
        *,
        status_scope: TaskGraphStatusScope | None = None,
        template_target_ids: tuple[str, ...] | None = None,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
        task_graph_continuation: TaskGraphContinuation | None = None,
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or f"status_callback_task_not_executable:{task.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        effect = self.rules.effect(task.effect_id)
        if effect is None:
            reason = "status_callback_effect_missing"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        list_result = self._execute_list_target_effect_task(state, callback, task, detail, trigger_event,
            damage_window_ledger, effect, status_scope=status_scope, template_target_ids=template_target_ids,
            template_binding_sources=template_binding_sources)
        if list_result is not None:
            return list_result
        coverage = self.effect_registry.coverage(effect)
        if coverage != "executable":
            reason = f"effect_not_executable:{coverage}"
            result = self.effect_registry.execute(
                effect,
                _effect_context(self.rules, state, task, detail, trigger_event, damage_window_ledger, status_scope, template_target_ids,
                    template_binding_sources),
            )
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                rng_events=result.rng_events,
                records=(*result.records, _task_blocked_record(callback, task, detail, reason)),
                errors=(reason, *result.unsupported),
            )
        context = _effect_context(self.rules, state, task, detail, trigger_event, damage_window_ledger,
                                  status_scope, template_target_ids, template_binding_sources)
        if task_graph_continuation is not None:
            # The task-graph path must stay unique per trigger occurrence. The
            # same task node can run once per hit/window inside one parent
            # invocation; keeping only parent path+task id would reuse one
            # application instance (and status instance) for every occurrence,
            # making repeated lifecycle mutations share a stable identity.
            context = replace(context, task_graph_continuation=task_graph_continuation,
                application_instance_id=(
                    f"status_task:{task_graph_continuation.parent_invocation_id}:"
                    f"{task_graph_continuation.parent_execution_path}:{task.task_id}"
                    + (
                        f":{context.application_instance_id}"
                        if context.application_instance_id else ""
                    )
                ))
        result = self.effect_registry.execute(effect, context)
        after_state = self.reducer.apply_all(state, result.mutations)
        records = (
            *result.records,
            _task_blocked_record(
                callback,
                task,
                detail,
                ",".join(result.unsupported),
                ok=not result.unsupported,
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            ),
        )
        return StatusCallbackExecutionResult(
            ok=not result.unsupported,
            after_state=after_state,
            mutations=result.mutations,
            rng_events=result.rng_events,
            records=records,
            events=result.events,
            errors=result.unsupported,
            created_unit_ids=result.created_unit_ids,
            dispatched_event_ids=result.dispatched_event_ids if not result.unsupported else frozenset(),
        )

    def _execute_current_skill_delay_cost_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        *,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> StatusCallbackExecutionResult:
        # The lowered effect owns the effective operation (an omitted raw
        # ModifyFunction is Add); the runtime does not re-derive that default.
        effect = self.rules.effect(task.effect_id) if task.effect_id else None
        standard = (
            effect.payload.get("standard")
            if effect is not None and isinstance(effect.payload, dict)
            else None
        )
        formal_standard = (
            standard
            if isinstance(standard, dict)
            and standard.get("operation") == "current_skill_delay_cost"
            and not standard.get("blocked_reason")
            else None
        )
        modify_function = (
            formal_standard.get("modify_function")
            if formal_standard is not None
            else task.task_payload.get("ModifyFunction")
        )
        if (task.coverage_status != "executable"
                or not isinstance(modify_function, str)
                or modify_function not in {"Set", "Add"}):
            reason = (task.blocked_reason or "current_skill_delay_cost_not_executable"
                      if task.coverage_status != "executable"
                      else "current_skill_delay_cost_modify_function_not_admitted")
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        owner_id = str(detail.get("owner_id") or "")
        event_payload = (
            trigger_event.payload
            if trigger_event is not None and isinstance(trigger_event.payload, dict)
            else {}
        )
        actor_id = _first_payload_str(
            event_payload,
            ("actor_id", "attacker_id", "damage_attacker_id"),
        ) or (str(trigger_event.source_id or "") if trigger_event is not None else "")
        turn_owner_id = str(state.global_flags.get("turn_owner_id") or "")
        if not owner_id or actor_id != owner_id or turn_owner_id != owner_id:
            reason = "current_skill_delay_cost_actor_not_active_owner"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        evaluation = _evaluate_callback_numeric(
            task.task_payload.get("NormalizedValue"),
            state,
            detail,
            task,
            self.rules,
            template_binding_sources=template_binding_sources,
        )
        if not evaluation.ok or evaluation.value is None:
            reason = evaluation.blocked_reason or "current_skill_delay_cost_value_unresolved"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        identity = ":".join(
            (
                owner_id,
                str(detail.get("instance_id") or ""),
                task.task_id,
                str(trigger_event.event_id or "") if trigger_event is not None else "",
            )
        )
        source_trace = {
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
            "trigger_event": trigger_event.to_json() if trigger_event is not None else {},
        }
        try:
            mutation = self.timeline.register_current_skill_delay_cost(
                state, actor_id=actor_id, identity=identity, modify_function=modify_function,
                normalized_value=evaluation.value, source="status_callback_system",
                metadata={"task_id": task.task_id, "callback_id": callback.callback_id,
                    "status_instance_id": str(detail.get("instance_id") or ""),
                    "numeric_evaluation": evaluation.to_json(), "source_trace": source_trace},
            )
        except ValueError as exc:
            reason = str(exc)
            return StatusCallbackExecutionResult(ok=False, after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        operation_index = mutation.metadata["operation_index"]
        after_state = self.reducer.apply_all(state, (mutation,))
        record = SettlementRecord(
            record_type="turn_action_delay_cost_registered",
            source="status_callback_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "task_id": task.task_id,
                "callback_id": callback.callback_id,
                "actor_id": actor_id,
                "identity": identity,
                "modify_function": modify_function,
                "operation_index": operation_index,
                "normalized_value": float(evaluation.value),
                "numeric_evaluation": evaluation.to_json(),
            },
            trace=source_trace,
        ).to_json()
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=after_state,
            mutations=(mutation,),
            records=(record,),
        )

    def _resolve_remodifier_branch(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
    ) -> tuple[str, dict[str, JSONValue], str]:
        if task.coverage_status != "executable":
            return "", {}, task.blocked_reason or "remodifier_query_not_executable"
        payload = task.task_payload
        target_id = _resolve_callback_target_id(
            state,
            detail,
            str(payload.get("TargetType") or ""),
            trigger_event,
        )
        caster_id = _resolve_callback_target_id(
            state,
            detail,
            str(payload.get("CasterFilter") or ""),
            trigger_event,
        )
        if target_id not in state.units or caster_id not in state.units:
            return "", {}, "remodifier_query_context_unresolved"
        flags = payload.get("BehaviorFlagFilter")
        if not isinstance(flags, list) or not flags or not all(
            isinstance(flag, str) and flag for flag in flags
        ):
            return "", {}, "remodifier_behavior_flag_filter_missing"
        maximum = _evaluate_callback_numeric(
            payload.get("MaxNumber"),
            state,
            detail,
            task,
            self.rules,
        )
        if (
            not maximum.ok
            or maximum.value is None
            or maximum.value < 0
            or not float(maximum.value).is_integer()
        ):
            return (
                "",
                {},
                maximum.blocked_reason or "remodifier_max_number_invalid",
            )
        raw_details = state.units[target_id].flags.get("status_details", ())
        if not isinstance(raw_details, (list, tuple)):
            return "", {}, "remodifier_status_details_invalid"
        required_flags = set(flags)
        matches = tuple(
            sorted(
                (
                    item
                    for item in raw_details
                    if isinstance(item, dict)
                    and item.get("caster_id") == caster_id
                    and required_flags.issubset(
                        {
                            str(flag)
                            for flag in item.get("behavior_flags", ())
                            if isinstance(flag, str)
                        }
                    )
                ),
                key=lambda item: str(item.get("instance_id") or ""),
            )[: int(maximum.value)]
        )
        branch = "success" if matches else "failed"
        return (
            branch,
            {
                "container_opcode": task.opcode,
                "target_id": target_id,
                "caster_id": caster_id,
                "behavior_flags": sorted(required_flags),
                "matched_status_instance_ids": [
                    str(item.get("instance_id") or "") for item in matches
                ],
                "branch": branch,
            },
            "",
        )

    def _execute_remodifier_query_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        branch, metadata, reason = self._resolve_remodifier_branch(
            state,
            callback,
            task,
            detail,
            trigger_event,
        )
        if reason:
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        selected_child_ids = (
            task.success_task_ids if branch == "success" else task.failed_task_ids
        )
        return self._execute_child_sequence(
            state,
            callback,
            task,
            detail,
            trigger_event,
            tasks,
            damage_window_ledger,
            selected_child_ids,
            container_metadata=metadata,
        )

    def _execute_shield_resilience_sync_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or "shield_resilience_sync_not_executable"
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        owner_id = str(detail.get("owner_id") or "")
        modifier_name = str(detail.get("modifier_name") or callback.modifier_name)
        status_instance_id = str(detail.get("instance_id") or "")
        unit = state.units.get(owner_id)
        if unit is None or not modifier_name or not status_instance_id:
            reason = "shield_resilience_status_identity_missing"
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        matching = tuple(
            sorted(
                (
                    item
                    for item in unit.shield_instances
                    if isinstance(item, dict)
                    and item.get("owner_modifier_name") == modifier_name
                    and item.get("status_instance_id") == status_instance_id
                ),
                key=lambda item: str(item.get("instance_id") or ""),
            )
        )
        reset_requested = task.task_payload.get("DoReset") is True
        deferred_init_task_ids: list[str] = []
        if callback.event in {"OnCreate", "OnStack"} and not reset_requested and not matching:
            active_details = tuple(
                item for item in unit.flags.get("status_details", ())
                if isinstance(item, dict) and item.get("instance_id") == status_instance_id
            )
            if (len(active_details) != 1 or "Shield" not in active_details[0].get("behavior_flags", ())
                    or any(not detail.get(key) or active_details[0].get(key) != detail[key]
                           for key in ("owner_id", "modifier_name", "status_id", "caster_id", "source_id"))):
                reason = "shield_resilience_active_status_identity_mismatch"
                return StatusCallbackExecutionResult(
                    False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,),
                )
            admitted_ids = _trigger_ids_for_event(active_details[0], "OnStack")
            for stack_callback in self.rules.status_callbacks_for_modifier_event(modifier_name, "OnStack"):
                if (admitted_ids is None or stack_callback.callback_id not in admitted_ids
                        or stack_callback.coverage_status != "executable"
                        or stack_callback.admission_status != "executable"):
                    continue
                for producer in self.rules.status_callback_tasks_for_callback(stack_callback.callback_id):
                    if (producer.opcode not in ({"InitShield"} if callback.event == "OnCreate" else {"InitShield", "StackShield"})
                            or producer.parent_task_id or producer.coverage_status != "executable"
                            or callback.event == "OnStack" and (stack_callback.callback_id != callback.callback_id
                                or producer.task_index <= task.task_index)):
                        continue
                    effect = self.rules.effect(producer.effect_id)
                    if (effect is not None and effect.owner_modifier_name == modifier_name
                            and self.effect_registry.coverage(effect) == "executable"
                            and effect.payload.get("standard", {}).get("target_alias") == "ModifierOwnerEntity"):
                        deferred_init_task_ids.append(producer.task_id)
            # OnCreate may defer to one OnStack InitShield. Inside OnStack only
            # a later root producer in this very callback may supply the pool.
            # Conditional/multiple producers remain blocked; never create a
            # duplicate shield pool merely to acknowledge SetResilience.
            if len(deferred_init_task_ids) != 1:
                reason = "shield_resilience_on_stack_producer_not_unique"
                return StatusCallbackExecutionResult(
                    False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,),
                )
        if (reset_requested and matching) or (
            not reset_requested and not matching and not deferred_init_task_ids
        ):
            reason = (
                "shield_resilience_removed_instance_still_present"
                if reset_requested
                else "shield_resilience_expected_instance_missing"
            )
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        source_trace = {
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        }
        record = SettlementRecord(
            record_type="shield_resilience_synchronized",
            source="status_callback_system",
            process_only=True,
            payload={
                "owner_id": owner_id,
                "modifier_name": modifier_name,
                "status_instance_id": status_instance_id,
                "task_id": task.task_id,
                "opcode": task.opcode,
                "reset_requested": reset_requested,
                "matching_shield_instance_ids": [
                    str(item.get("instance_id") or "") for item in matching
                ],
                "authoritative_state": "status_instance_then_on_stack_shield" if deferred_init_task_ids else "shield_instances",
                "deferred_init_task_ids": deferred_init_task_ids,
            },
            trace=source_trace,
        ).to_json()
        return StatusCallbackExecutionResult(
            True,
            state,
            records=(record,),
        )

    def _execute_list_target_effect_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
        effect,
        *,
        status_scope: TaskGraphStatusScope | None = None,
        template_target_ids: tuple[str, ...] | None = None,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> StatusCallbackExecutionResult | None:
        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        if not isinstance(standard, dict):
            return None
        # Status application and dispel already consume the canonical target
        # expression as a complete group.  Re-routing them through the
        # per-target adapter would replace the payload alias with ParamEntity
        # while retaining the original expression identity, producing a
        # contradictory source pair (for example
        # ParamEntity:DamageDefenderEntity).
        if effect.opcode in {
            "AddModifier",
            "RemoveModifier",
            "RemoveSelfModifier",
            "DispelStatus",
        }:
            return None
        alias = standard.get("target_alias")
        if alias in {
            "Caster",
            "CurrentActionTarget",
            "LevelEntity",
            "ModifierOwnerEntity",
            "ParamEntity",
        }:
            return None
        target_expression_id = standard.get("target_expression_id")
        if alias in (None, "") and not (
            isinstance(target_expression_id, str) and target_expression_id
        ):
            # Global effects such as team-resource changes intentionally have
            # no target.  They must reach their typed effect executor instead
            # of being mistaken for an unresolved list target.  An omitted
            # TargetType may also be a typed callback-instance binding, which
            # the effect executor admits or rejects on its own contract.
            return None
        expression = (
            self.rules.target_expression(str(target_expression_id))
            if isinstance(target_expression_id, str) and target_expression_id
            else None
        )
        target_rng_events: tuple[RNGEvent, ...] = ()
        target_resolution_payload: dict[str, JSONValue] = {}
        empty_group_admitted = False
        if expression is not None:
            context = _effect_context(
                self.rules,
                state,
                task,
                detail,
                trigger_event,
                damage_window_ledger,
                status_scope,
                template_target_ids,
                template_binding_sources,
            )
            resolution = self.targets.resolve_target_expression(
                state,
                expression,
                context=TargetEvaluationContext(
                    caster_id=context.caster_id,
                    effect_owner_id=context.owner_id,
                    template_entity_ids=context.template_target_ids,
                    parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
                    selected_target_ids=((context.current_action_target_id,) if context.current_action_target_id else ()),
                    current_target_id=context.current_action_target_id,
                    event_source_id=(trigger_event.source_id if trigger_event is not None
                                     and trigger_event.source_id in state.units else None),
                    event_target_id=(trigger_event.target_id if trigger_event is not None else None),
                    turn_owner_id=committed_turn_owner_id(state),
                    action_event_id=(trigger_event.event_id if trigger_event is not None else None),
                    action_window=(trigger_event.window if trigger_event is not None else None),
                    admitted_action_target_fact=(
                        trigger_event.admitted_action_target_fact
                        if trigger_event is not None
                        else None
                    ),
                    expected_action_window_scope=(
                        trigger_event.expected_action_window_scope
                        if trigger_event is not None
                        else None
                    ),
                ),
                target_resolution=context.target_resolution,
                condition_event_payload=context.event_payload,
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
            )
            target_rng_events = resolution.rng_events
            target_resolution_payload = resolution.to_json()
            if not resolution.resolved:
                reason = resolution.blocked_reason or "target_expression_resolution_failed"
                if (
                    str(alias)
                    in {
                        "AllDarkTeam",
                        "AllEnemy",
                        "AllEnemyWithUnSelectable",
                        "AllLightTeam",
                        "AllTeamMember",
                        "AllTeamMemberWithUnselectable",
                        "AllTeammate",
                    }
                    and reason == f"target group empty:{alias}"
                ):
                    target_ids = ()
                    empty_group_admitted = True
                    target_resolution_payload["empty_group_admission"] = (
                        "source_resolved_no_effect"
                    )
                else:
                    return StatusCallbackExecutionResult(
                        ok=False,
                        after_state=state,
                        rng_events=target_rng_events,
                        records=(_task_blocked_record(callback, task, detail, reason),),
                        errors=(reason,),
                    )
            else:
                target_ids = resolution.target_ids
        else:
            target_ids = _list_alias_targets(state, detail, trigger_event, str(alias))
        if not target_ids:
            if empty_group_admitted:
                record = _task_blocked_record(
                    callback,
                    task,
                    detail,
                    "source_resolved_empty_group_no_effect",
                    ok=True,
                )
                payload = record.get("payload")
                if isinstance(payload, dict):
                    payload["target_alias"] = str(alias)
                    payload["resolved_target_ids"] = []
                    payload["state_unchanged"] = True
                    payload["target_expression_resolution"] = (
                        target_resolution_payload
                    )
                return StatusCallbackExecutionResult(
                    ok=True,
                    after_state=state,
                    rng_events=target_rng_events,
                    records=(record,),
                )
            reason = f"list_target_alias_unresolved:{alias}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                rng_events=target_rng_events,
                errors=(reason,),
            )
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = list(target_rng_events)
        errors: list[str] = []
        for target_id in target_ids:
            patched_standard = {**standard, "target_alias": "ParamEntity"}
            patched_effect = replace(effect, payload={**effect.payload, "standard": patched_standard})
            context = _effect_context(self.rules, current_state, task, detail, trigger_event, damage_window_ledger, status_scope, template_target_ids,
                template_binding_sources)
            context = replace(context, param_entity_id=target_id, current_action_target_id=target_id)
            result = self.effect_registry.execute(patched_effect, context)
            if result.unsupported:
                errors.extend(result.unsupported)
                reason = ",".join(errors)
                blocked = _task_blocked_record(callback, task, detail, reason)
                payload = blocked.get("payload")
                if isinstance(payload, dict):
                    payload["target_alias"] = str(alias)
                    payload["resolved_target_ids"] = list(target_ids)
                    payload["failed_target_id"] = target_id
                    payload["target_expression_resolution"] = target_resolution_payload
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple((*rng_events, *result.rng_events)),
                    records=(blocked,),
                    errors=tuple(errors),
                )
            current_state = self.reducer.apply_all(current_state, result.mutations)
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
        summary = _task_blocked_record(
            callback,
            task,
            detail,
            ",".join(errors),
            ok=not errors,
            mutation_count=len(mutations),
            record_count=len(records),
        )
        payload = summary.get("payload")
        if isinstance(payload, dict):
            payload["target_alias"] = str(alias)
            payload["resolved_target_ids"] = list(target_ids)
            payload["target_expression_resolution"] = target_resolution_payload
        records.append(summary)
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
        )

    def _execute_modify_heal_data_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        *,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or "modify_heal_data_not_executable"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        fields = tuple(
            key for key in ("Healer_HealRatio", "Target_HealTakenRatio")
            if key in task.task_payload
        )
        if len(fields) != 1:
            reason = "modify_heal_data_fields_not_admitted"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        field = fields[0]
        evaluation = _evaluate_callback_numeric(
            task.task_payload[field],
            state,
            detail,
            task,
            self.rules,
            template_binding_sources=template_binding_sources,
        )
        if not evaluation.ok or evaluation.value is None:
            reason = (
                evaluation.blocked_reason
                or f"{field.lower()}_evaluation_failed"
            )
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        record = SettlementRecord(
            record_type="heal_modifier",
            source="status_callback_system",
            process_only=True,
            payload={
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "modifier_name": callback.modifier_name,
                "heal_field": field,
                "heal_ratio": float(evaluation.value),
                "numeric_evaluation": evaluation.to_json(),
            },
            trace={
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            },
        ).to_json()
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=state,
            records=(record,),
            heal_ratio_delta=float(evaluation.value),
        )

    def _execute_damage_modifier_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        *,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> StatusCallbackExecutionResult:
        """Evaluate the selected leaf once and return its transient damage facts."""

        modifiers = tuple(
            modifier
            for modifier in self.rules.damage_modifiers_for_callback(
                callback.callback_id
            )
            if modifier.source_task_id == task.task_id
        )
        reason = ""
        if task.coverage_status != "executable":
            reason = task.blocked_reason or "modify_damage_data_not_executable"
        elif len(modifiers) != 1:
            reason = f"damage_modifier_count:{len(modifiers)}"
        else:
            modifier = modifiers[0]
            if modifier.coverage_status != "executable":
                reason = (
                    modifier.blocked_reason
                    or "damage_modifier_not_executable"
                )
            elif (
                modifier.callback_id != callback.callback_id
                or modifier.modifier_name != callback.modifier_name
                or modifier.event != callback.event
            ):
                reason = "damage_modifier_callback_identity_mismatch"
            elif modifier.source.to_json() != task.source.to_json():
                reason = "damage_modifier_source_identity_mismatch"
            elif not modifier.modifier_terms:
                reason = "damage_modifier_terms_missing"
            elif any(
                term.get("coverage_status") != "executable"
                for term in modifier.modifier_terms
            ):
                reason = "damage_modifier_term_not_executable"
        if reason:
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )

        modifier = modifiers[0]
        contributions: list[DamageModifierContribution] = []
        evaluations: list[dict[str, JSONValue]] = []
        for index, term in enumerate(modifier.modifier_terms):
            evaluation = _evaluate_callback_numeric(
                term.get("numeric_expr"), state, detail, task, self.rules,
                template_binding_sources=template_binding_sources,
            )
            if not evaluation.ok or evaluation.value is None:
                reason = evaluation.blocked_reason or "damage_modifier_numeric_blocked"
                return StatusCallbackExecutionResult(
                    ok=False, after_state=state,
                    records=(_task_blocked_record(callback, task, detail, reason),),
                    errors=(reason,),
                )
            contributions.append(DamageModifierContribution(modifier, index, float(evaluation.value)))
            evaluations.append(evaluation.to_json())
        record = SettlementRecord(
            record_type="damage_modifier_task",
            source="status_callback_system",
            process_only=True,
            payload={
                "ok": True,
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "modifier_name": callback.modifier_name,
                "damage_modifier_id": modifier.damage_modifier_id,
                "consumer": "damage_packet_modifier_contributions",
                "evaluations": evaluations,
                "terms": [item.formula_term() for item in contributions],
                "term_count": len(modifier.modifier_terms),
            },
            trace={
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "damage_modifier_source": modifier.source.to_json(),
                "status_instance_source": _json_dict(
                    detail.get("source_trace")
                ),
            },
        ).to_json()
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=state,
            records=(record,),
            damage_modifiers=tuple(contributions),
        )

    def _dispatch_pre_heal(
        self,
        effect,
        context: EffectExecutionContext,
    ) -> PreHealDispatchResult:
        standard = (
            effect.payload.get("standard")
            if isinstance(effect.payload, dict)
            else None
        )
        if not isinstance(standard, dict):
            return PreHealDispatchResult(
                ok=False,
                after_state=context.state,
                errors=("pre_heal_standard_payload_missing",),
            )
        alias = str(standard.get("target_alias") or "")
        selected = (
            tuple(context.target_resolution.selected)
            if context.target_resolution is not None
            else ()
        )
        if len(selected) == 1 and selected[0] in context.state.units:
            # Group/composite heals resolve one target at a time in the group
            # executor; the pre-heal window belongs to that resolved target.
            target_id = selected[0]
        else:
            target_id = _resolve_target_alias(
                alias, caster_id=context.caster_id, owner_id=context.owner_id,
                param_entity_id=context.param_entity_id,
                current_action_target_id=context.current_action_target_id,
                target_resolution=context.target_resolution,
            )
        if not isinstance(target_id, str) or target_id not in context.state.units:
            return PreHealDispatchResult(
                ok=False,
                after_state=context.state,
                errors=(f"pre_heal_target_not_resolved:{alias or 'missing'}",),
            )
        actor = context.state.units.get(context.caster_id)
        if actor is None:
            return PreHealDispatchResult(
                ok=False,
                after_state=context.state,
                errors=("pre_heal_actor_missing",),
            )
        parent_payload = {
            key: value
            for key, value in (context.event_payload or {}).items()
            if key
            not in {
                "callback_event",
                "callback_events",
                "listener_scope",
                "tbgd_event",
            }
        }
        trigger_event = GameEvent(
            event_type="heal.before",
            source_id=context.caster_id,
            target_id=target_id,
            event_id=(
                f"{str((context.event_payload or {}).get('event_id') or f'event:{context.state.event_index}')}:"
                f"heal_before:{effect.effect_id}:{target_id}"
            ),
            window="OnBeforeDealHeal",
            process_only=True,
            payload={
                **parent_payload,
                "actor_id": context.caster_id,
                "source_id": context.source_id,
                "target_id": target_id,
                "param_entity_id": target_id,
                "current_action_target_id": target_id,
                "callback_events": ["OnBeforeDealHeal"],
                "listener_scope": "actor_local",
            },
        )
        current_state = context.state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = [trigger_event]
        rng_events: list[RNGEvent] = []
        heal_ratio = 0.0
        dispatched_event_ids: set[str] = {trigger_event.event_id}
        for holder_id, callback_event, scope, parameter_id in (
            (actor.unit_id, "OnBeforeDealHeal", "actor_local", target_id),
            (target_id, "OnBeforeBeingHeal", "being_hit_target_local", actor.unit_id),
        ):
            holder = current_state.units[holder_id]
            details = holder.flags.get("status_details", ())
            if not isinstance(details, (list, tuple)):
                details = ()
            callback_trigger = replace(
                trigger_event,
                window=callback_event,
                payload={
                    **trigger_event.payload,
                    "param_entity_id": parameter_id,
                    "callback_events": [callback_event],
                    "listener_scope": scope,
                },
            )
            for detail in sorted(
                (item for item in details if isinstance(item, dict)),
                key=lambda item: (
                    str(item.get("modifier_name") or ""),
                    str(item.get("instance_id") or ""),
                ),
            ):
                modifier_name = str(detail.get("modifier_name") or "")
                if not self.rules.status_callbacks_for_modifier_event(modifier_name, callback_event):
                    continue
                result = self.execute(
                    current_state,
                    unit_id=holder_id,
                    modifier_name=modifier_name,
                    event=callback_event,
                    trigger_event=callback_trigger,
                )
                if not result.ok:
                    return PreHealDispatchResult(
                        ok=False,
                        after_state=context.state,
                        rng_events=tuple((*rng_events, *result.rng_events)),
                        records=result.records,
                        errors=result.errors or ("pre_heal_callback_failed",),
                    )
                current_state = result.after_state
                mutations.extend(result.mutations)
                records.extend(result.records)
                events.extend(result.events)
                rng_events.extend(result.rng_events)
                heal_ratio += result.heal_ratio_delta
                dispatched_event_ids.update(result.dispatched_event_ids)
        return PreHealDispatchResult(
            ok=True,
            after_state=current_state,
            heal_ratio=heal_ratio,
            events=tuple(events),
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def _execute_damage_emissions(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        emissions: tuple[StatusDamageEmissionIR, ...],
        damage_window_ledger: DamageWindowLedger | None,
        *,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> StatusCallbackExecutionResult:
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        errors: list[str] = []
        rng_events: list[RNGEvent] = []
        dispatched_event_ids: set[str] = set()
        for emission in emissions:
            if emission.coverage_status != "executable":
                reason = emission.blocked_reason or f"status_damage_not_executable:{emission.coverage_status}"
                records.append(_status_damage_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            if emission.damage_formula_family in {"additional", "elation"}:
                result = self._execute_additional_damage_emission(
                    current_state,
                    callback,
                    task,
                    detail,
                    trigger_event,
                    emission,
                    damage_window_ledger,
                    template_binding_sources=template_binding_sources,
                )
                current_state = result.after_state
                mutations.extend(result.mutations)
                records.extend(result.records)
                events.extend(result.events)
                errors.extend(result.errors)
                rng_events.extend(result.rng_events)
                dispatched_event_ids.update(result.dispatched_event_ids)
                continue
            if emission.damage_formula_family == "dot":
                result = self._execute_dot_damage_emission(
                    current_state,
                    callback,
                    task,
                    detail,
                    trigger_event,
                    emission,
                    damage_window_ledger,
                    template_binding_sources=template_binding_sources,
                )
                current_state = result.after_state
                mutations.extend(result.mutations)
                records.extend(result.records)
                events.extend(result.events)
                errors.extend(result.errors)
                dispatched_event_ids.update(result.dispatched_event_ids)
                continue
            evaluation = self._evaluate_status_damage_amount(current_state, detail, emission, template_binding_sources=template_binding_sources)
            if not evaluation.ok or evaluation.value is None:
                reason = evaluation.blocked_reason or "status_damage_numeric_evaluation_failed"
                records.append(_status_damage_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                errors.append(reason)
                continue
            target_id = str(detail.get("owner_id") or "")
            caster_id = str(detail.get("caster_id") or "")
            if target_id not in current_state.units or caster_id not in current_state.units:
                reason = "status_damage_actor_or_target_missing"
                records.append(_status_damage_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                errors.append(reason)
                continue
            if emission.damage_formula_family == "true_damage":
                packet = DamagePacket(
                    attacker_id=caster_id,
                    target_id=target_id,
                    attack_type=emission.attack_type,
                    damage_formula_family="true_damage",
                    amount=float(evaluation.value),
                    amount_stage="fixed_final",
                    element_type=emission.element_type,
                    status_damage_emission_id=emission.status_damage_emission_id,
                    status_callback_id=callback.callback_id,
                    status_instance_id=str(detail.get("instance_id") or ""),
                    modifier_name=callback.modifier_name,
                    source_task_id=task.task_id,
                    source_frame=DamageSourceFrame(
                        owner_id=caster_id,
                        source_id=f"status_damage:{emission.status_damage_emission_id}",
                        source_kind="status_true_damage",
                        sequence_id=f"status_damage:{str(detail.get('instance_id') or '')}:{emission.status_damage_emission_id}",
                        target_id=target_id,
                        can_continue_after_lethal=False,
                        source_trace={
                            "status_damage_source": emission.source.to_json(),
                            "status_callback_source": callback.source.to_json(),
                            "status_task_source": task.source.to_json(),
                            "status_instance_source": _json_dict(detail.get("source_trace")),
                        },
                    ),
                    source_trace={
                        "status_damage_source": emission.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_task_source": task.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                    metadata={
                        "damage_formula_family": "true_damage",
                        "record_type": "true_damage",
                        "status_damage_emission_id": emission.status_damage_emission_id,
                        "status_callback_id": callback.callback_id,
                        "status_instance_id": str(detail.get("instance_id") or ""),
                        "modifier_name": callback.modifier_name,
                        "source_task_id": task.task_id,
                        "numeric_evaluation": evaluation.to_json(),
                        "normal_multiplier_terms": [],
                        "bypasses_normal_multipliers": True,
                    },
                )
                damage_result = self.damage.apply_packet(
                    current_state,
                    packet,
                    window_ledger=damage_window_ledger,
                )
                current_state = self.reducer.apply_all(current_state, damage_result.mutations)
                mutations.extend(damage_result.mutations)
                records.extend(damage_result.records)
                events.extend(damage_result.events)
                errors.extend(damage_result.errors)
                continue
            break_template_id = _break_template_id_from_detail(detail)
            if not break_template_id:
                reason = "status_damage_break_template_missing"
                records.append(_status_damage_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                errors.append(reason)
                continue
            packet = DamagePacket(
                attacker_id=caster_id,
                target_id=target_id,
                attack_type=emission.attack_type,
                damage_formula_family="break",
                amount=float(evaluation.value),
                amount_stage="family_base",
                base_includes_break_bonus=emission.base_includes_break_bonus,
                element_type=emission.element_type or _break_element_from_detail(detail),
                status_damage_emission_id=emission.status_damage_emission_id,
                status_callback_id=callback.callback_id,
                status_instance_id=str(detail.get("instance_id") or ""),
                modifier_name=callback.modifier_name,
                break_template_id=break_template_id,
                source_task_id=task.task_id,
                source_frame=DamageSourceFrame(
                    owner_id=caster_id,
                    source_id=f"status_damage:{emission.status_damage_emission_id}",
                    source_kind="status_damage",
                    sequence_id=f"status_damage:{str(detail.get('instance_id') or '')}:{emission.status_damage_emission_id}",
                    target_id=target_id,
                    can_continue_after_lethal=False,
                    source_trace={
                        "status_damage_source": emission.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_task_source": task.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                ),
                source_trace={
                    "status_damage_source": emission.source.to_json(),
                    "status_callback_source": callback.source.to_json(),
                    "status_task_source": task.source.to_json(),
                    "status_instance_source": _json_dict(detail.get("source_trace")),
                },
                metadata={
                    "damage_formula_family": "break",
                    "record_type": "break_dot_tick",
                    "status_damage_emission_id": emission.status_damage_emission_id,
                    "status_callback_id": callback.callback_id,
                    "status_instance_id": str(detail.get("instance_id") or ""),
                    "modifier_name": callback.modifier_name,
                    "source_task_id": task.task_id,
                    "damage_source_owner_id": caster_id,
                    "damage_source_id": f"status_damage:{emission.status_damage_emission_id}",
                    "damage_source_kind": "status_damage",
                    "damage_sequence_id": f"status_damage:{str(detail.get('instance_id') or '')}:{emission.status_damage_emission_id}",
                    "can_continue_after_lethal": False,
                    "break_template_id": break_template_id,
                    "numeric_evaluation": evaluation.to_json(),
                    "break_base_damage_source": _break_base_source_from_evaluation(evaluation),
                    "source_trace": {
                        "status_damage_source": emission.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_task_source": task.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                },
            )
            damage_result = self.damage.apply_packet(
                current_state,
                packet,
                window_ledger=damage_window_ledger,
            )
            current_state = self.reducer.apply_all(current_state, damage_result.mutations)
            mutations.extend(damage_result.mutations)
            records.extend(damage_result.records)
            events.extend(damage_result.events)
            errors.extend(damage_result.errors)
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
            dispatched_event_ids=frozenset(dispatched_event_ids) if not errors else frozenset(),
        )

    def _execute_additional_damage_emission(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        emission: StatusDamageEmissionIR,
        damage_window_ledger: DamageWindowLedger | None,
        *,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> StatusCallbackExecutionResult:
        caster_id = str(detail.get("caster_id") or detail.get("owner_id") or "")
        actor = state.units.get(caster_id)
        if actor is None:
            reason = "status_damage_actor_missing"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _status_damage_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        reason,
                    ),
                ),
                errors=(reason,),
            )
        context = _effect_context(self.rules, state, task, detail, trigger_event,
            damage_window_ledger, template_binding_sources=template_binding_sources)
        target_context = TargetEvaluationContext(
            caster_id=context.caster_id, effect_owner_id=context.owner_id,
            parameter_entity_ids=(context.param_entity_id,) if context.param_entity_id else (),
            selected_target_ids=(context.current_action_target_id,) if context.current_action_target_id else (),
            current_target_id=context.current_action_target_id,
            event_source_id=trigger_event.source_id if trigger_event is not None and trigger_event.source_id in state.units else None,
            event_target_id=trigger_event.target_id if trigger_event is not None else None,
            turn_owner_id=committed_turn_owner_id(state),
            action_event_id=trigger_event.event_id if trigger_event is not None and trigger_event.event_id and trigger_event.window else None,
            action_window=trigger_event.window if trigger_event is not None and trigger_event.event_id and trigger_event.window else None,
            admitted_action_target_fact=trigger_event.admitted_action_target_fact if trigger_event is not None else None,
            expected_action_window_scope=trigger_event.expected_action_window_scope if trigger_event is not None else None,
        )
        identities = {"attacker": caster_id, "property_source": caster_id, "element_source": caster_id}
        identity_resolutions: dict[str, JSONValue] = {}
        for role, expression_id in (
            ("attacker", emission.attacker_target_expression_id),
            ("property_source", emission.property_source_target_expression_id),
            ("element_source", emission.element_source_target_expression_id),
        ):
            if not expression_id:
                continue
            identity_expression = self.rules.target_expression(expression_id)
            resolution = (self.targets.resolve_target_expression(state, identity_expression,
                context=target_context, target_resolution=context.target_resolution,
                condition_event_payload=context.event_payload, dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources) if identity_expression is not None else None)
            if resolution is None or not resolution.resolved or len(resolution.target_ids) != 1 or resolution.rng_events:
                reason = (f"status_damage_{role}_target_blocked:{resolution.blocked_reason}"
                    if resolution is not None and resolution.blocked_reason
                    else f"status_damage_{role}_target_not_unique_or_deterministic")
                return StatusCallbackExecutionResult(ok=False, after_state=state,
                    records=(_status_damage_blocked_record(callback, task, detail, emission, reason),), errors=(reason,))
            identities[role] = resolution.target_ids[0]
            identity_resolutions[role] = resolution.to_json()
        # ponytail: split attacker/property sources need a proven property-by-property
        # contract; the common same-unit override already covers this source shape.
        if identities["attacker"] != identities["property_source"]:
            reason = "status_damage_split_property_source_not_admitted"
            return StatusCallbackExecutionResult(ok=False, after_state=state,
                records=(_status_damage_blocked_record(callback, task, detail, emission, reason),), errors=(reason,))
        attacker_id = identities["attacker"]
        actor = state.units.get(attacker_id)
        element_source = state.units.get(identities["element_source"])
        if actor is None or element_source is None:
            reason = "status_damage_identity_unit_missing"
            return StatusCallbackExecutionResult(ok=False, after_state=state, errors=(reason,))
        element_type = emission.element_type or str(element_source.flags.get("damage_type") or "") or None
        if emission.element_source_target_expression_id and element_type not in {
            "Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary",
        }:
            reason = "status_damage_element_source_not_admitted"
            return StatusCallbackExecutionResult(ok=False, after_state=state, errors=(reason,))
        expression = (
            self.rules.target_expression(task.target_expression_id)
            if task.target_expression_id
            else None
        )
        if expression is not None:
            resolution = self.targets.resolve_target_expression(
                state,
                expression,
                context=target_context,
                target_resolution=context.target_resolution,
                condition_event_payload=context.event_payload,
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
            )
            if not resolution.resolved or not resolution.target_ids:
                reason = (
                    resolution.blocked_reason
                    or "additional_damage_target_resolution_failed"
                )
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=resolution.rng_events,
                    records=(
                        _status_damage_blocked_record(
                            callback,
                            task,
                            detail,
                            emission,
                            reason,
                        ),
                    ),
                    errors=(reason,),
                )
            target_ids = resolution.target_ids
            rng_events = list(resolution.rng_events)
        else:
            alias = str(task.task_payload.get("TargetType") or "")
            target_id = _resolve_callback_target_id(
                state, detail, alias, trigger_event
            )
            target_ids = (target_id,) if target_id else ()
            rng_events = []
        if not target_ids:
            reason = "additional_damage_target_missing"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _status_damage_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        reason,
                    ),
                ),
                errors=(reason,),
            )

        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        dispatched_event_ids: set[str] = set()
        if identity_resolutions:
            records.append(SettlementRecord("status_damage_identity", "status_callback_system", process_only=True,
                payload={"status_damage_emission_id": emission.status_damage_emission_id,
                         "parameter_caster_id": caster_id, "roles": identities,
                         "target_resolutions": identity_resolutions},
                trace={"status_damage_source": emission.source.to_json()}).to_json())
        from .event_dispatch import EventDispatchSystem, MAX_CALLBACK_EMITTED_EVENT_DEPTH

        dispatcher = EventDispatchSystem(self.rules, self.effect_registry,
            reducer=self.reducer, damage=self.damage, status_callbacks=self)
        parent_depth = (trigger_event.payload.get("mutation_event_depth", 0) if trigger_event is not None else 0)
        if type(parent_depth) is not int or parent_depth < 0 or parent_depth >= MAX_CALLBACK_EMITTED_EVENT_DEPTH:
            reason = "status_damage_window_depth_exceeded"
            return StatusCallbackExecutionResult(ok=False, after_state=state, errors=(reason,))
        # Extra damage dealt *from inside* a hit-all callback produces another
        # hit window.  Mark those windows so ByIsHitAllCallBackStack can stop
        # the callback from recursively applying its extra hit once more.
        hit_all_callback_stack = callback.event in HIT_ALL_CALLBACK_EVENTS
        for target_id in target_ids:
            if target_id not in current_state.units:
                reason = f"additional_damage_target_missing:{target_id}"
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple(rng_events),
                    records=(
                        _status_damage_blocked_record(
                            callback,
                            task,
                            detail,
                            emission,
                            reason,
                        ),
                    ),
                    errors=(reason,),
                )
            evaluation = self._evaluate_status_damage_amount(
                current_state,
                detail,
                emission,
                target_id=target_id,
                template_binding_sources=template_binding_sources,
            )
            if not evaluation.ok or evaluation.value is None:
                reason = (
                    evaluation.blocked_reason
                    or "additional_damage_numeric_evaluation_failed"
                )
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple(rng_events),
                    records=(
                        _status_damage_blocked_record(
                            callback,
                            task,
                            detail,
                            emission,
                            reason,
                            evaluation=evaluation,
                        ),
                    ),
                    errors=(reason,),
                )
            trace = {
                "status_damage_source": emission.source.to_json(),
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            }
            source_id = f"status_damage:{emission.status_damage_emission_id}"
            sequence_id = (
                f"status_damage:{str(detail.get('instance_id') or '')}:"
                f"{emission.status_damage_emission_id}:{trigger_event.event_id if trigger_event else state.event_index}"
            )
            elation_context = None
            packet = DamagePacket(
                attacker_id=attacker_id,
                target_id=target_id,
                attack_type=emission.attack_type,
                damage_formula_family=emission.damage_formula_family,
                final_formula_type=str(
                    (emission.scaling_expr or {}).get("final_formula_type") or ""
                ),
                is_indirect=(
                    (emission.scaling_expr or {}).get("is_indirect") is True
                ),
                amount=None if emission.damage_formula_family == "elation" else float(evaluation.value),
                amount_stage="unspecified" if emission.damage_formula_family == "elation" else "family_base",
                scaling_ratio=float(evaluation.value) if emission.damage_formula_family == "elation" else None,
                scaling_basis={"kind": "elation_level_base"} if emission.damage_formula_family == "elation" else {},
                elation_context=elation_context,
                element_type=element_type,
                status_damage_emission_id=emission.status_damage_emission_id,
                status_callback_id=callback.callback_id,
                status_instance_id=str(detail.get("instance_id") or ""),
                modifier_name=callback.modifier_name,
                source_task_id=task.task_id,
                source_frame=DamageSourceFrame(
                    owner_id=attacker_id,
                    source_id=source_id,
                    source_kind=f"status_{emission.damage_formula_family}_damage",
                    sequence_id=sequence_id,
                    target_id=target_id,
                    can_continue_after_lethal=False,
                    source_trace=trace,
                ),
                source_trace=trace,
                metadata={
                    "damage_formula_family": emission.damage_formula_family,
                    "record_type": f"{emission.damage_formula_family}_damage",
                    "trigger_event_id": trigger_event.event_id if trigger_event is not None else "",
                    "status_damage_emission_id": emission.status_damage_emission_id,
                    "status_callback_id": callback.callback_id,
                    "status_instance_id": str(detail.get("instance_id") or ""),
                    "modifier_name": callback.modifier_name,
                    "source_task_id": task.task_id,
                    "damage_source_owner_id": attacker_id,
                    "damage_source_id": source_id,
                    "damage_source_kind": f"status_{emission.damage_formula_family}_damage",
                    "damage_sequence_id": sequence_id,
                    "can_continue_after_lethal": False,
                    "numeric_evaluation": evaluation.to_json(),
                    "source_trace": trace,
                },
            )
            hit_modifiers: list[DamageModifierContribution] = []
            for window in ("damage.hit_sequence.before", "damage.before_hit"):
                prepared = dispatcher.dispatch_event(current_state,
                    event=_status_damage_window_event(current_state, packet, window,
                        emission.damage_custom_name, parent_depth + 1,
                        hit_all_callback_stack=hit_all_callback_stack),
                    damage_window_ledger=damage_window_ledger)
                if prepared.errors:
                    reason = "status_damage_pre_hit_blocked:" + prepared.errors[0]
                    return StatusCallbackExecutionResult(ok=False, after_state=state,
                        records=(_status_damage_blocked_record(callback, task, detail, emission, reason),), errors=(reason,))
                current_state = prepared.after_state
                mutations.extend(prepared.mutations)
                records.extend(prepared.records)
                events.extend(prepared.events)
                rng_events.extend(prepared.rng_events)
                dispatched_event_ids.update(prepared.dispatched_event_ids)
                hit_modifiers.extend(prepared.damage_modifiers)
            packet = replace(packet, modifier_contributions=tuple(hit_modifiers))
            if emission.damage_formula_family == "elation":
                try:
                    elation_context = resolve_elation_damage_context(current_state, attacker_id,
                        point_source=str(emission.scaling_expr.get("elation_point_source") or ""),
                        modifier_contributions=packet.modifier_contributions)
                    packet = replace(packet, elation_context=elation_context)
                except ValueError as exc:
                    reason = f"elation_context_blocked:{exc}"
                    return StatusCallbackExecutionResult(ok=False, after_state=state,
                        records=(_status_damage_blocked_record(callback, task, detail, emission, reason),), errors=(reason,))
            damage_result = self.damage.apply_packet(
                current_state,
                packet,
                window_ledger=damage_window_ledger,
            )
            if not damage_result.ok:
                reason = (
                    damage_result.errors[0]
                    if damage_result.errors
                    else "additional_damage_application_failed"
                )
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple((*rng_events, *damage_result.rng_events)),
                    records=damage_result.records,
                    errors=(reason,),
                )
            current_state = self.reducer.apply_all(
                current_state,
                damage_result.mutations,
            )
            mutations.extend(damage_result.mutations)
            records.extend(damage_result.records)
            events.extend(damage_result.events)
            rng_events.extend(damage_result.rng_events)
            completed = dispatcher.dispatch_event(current_state,
                event=_status_damage_window_event(current_state, packet, "damage.hit_sequence.after",
                    emission.damage_custom_name, parent_depth + 1,
                    hit_all_callback_stack=hit_all_callback_stack), damage_window_ledger=damage_window_ledger)
            if completed.errors:
                reason = "status_damage_after_hit_blocked:" + completed.errors[0]
                return StatusCallbackExecutionResult(ok=False, after_state=state,
                    records=(_status_damage_blocked_record(callback, task, detail, emission, reason),), errors=(reason,))
            current_state = completed.after_state
            mutations.extend(completed.mutations)
            records.extend(completed.records)
            events.extend(completed.events)
            rng_events.extend(completed.rng_events)
            dispatched_event_ids.update(completed.dispatched_event_ids)
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def _execute_dot_damage_emission(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        emission: StatusDamageEmissionIR,
        damage_window_ledger: DamageWindowLedger | None,
        *,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> StatusCallbackExecutionResult:
        target_id = str(detail.get("owner_id") or "")
        caster_id = str(detail.get("caster_id") or "")
        if target_id not in state.units or caster_id not in state.units:
            reason = "status_damage_actor_or_target_missing"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_status_damage_blocked_record(callback, task, detail, emission, reason),),
                errors=(reason,),
            )
        trace = {
            "status_damage_source": emission.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        }
        formula_result = DotFormula().calculate(
            DotFormulaInput(
                state=state,
                caster_id=caster_id,
                target_id=target_id,
                status_detail=detail,
                emission=emission,
                source_trace=trace,
                event_payload={
                    **(
                        dict(trigger_event.payload)
                        if trigger_event is not None
                        and isinstance(trigger_event.payload, dict)
                        else {}
                    ),
                    "runtime_event_type": (
                        trigger_event.event_type if trigger_event is not None else ""
                    ),
                    "runtime_event_id": (
                        trigger_event.event_id if trigger_event is not None else ""
                    ),
                },
            )
        )
        if not formula_result.ok:
            reason = formula_result.blocked_reason or "dot_formula_evaluation_failed"
            records = (
                _status_damage_blocked_record(
                    callback,
                    task,
                    detail,
                    emission,
                    reason,
                    evaluation_payload=formula_result.to_json(),
                ),
            )
            return StatusCallbackExecutionResult(ok=False, after_state=state, records=records, errors=(reason,))
        source_id = f"status_damage:{emission.status_damage_emission_id}"
        sequence_id = f"status_damage:{str(detail.get('instance_id') or '')}:{emission.status_damage_emission_id}"
        packet = DamagePacket(
            attacker_id=caster_id,
            target_id=target_id,
            attack_type=emission.attack_type,
            damage_formula_family="dot",
            amount=formula_result.final_damage,
            amount_stage="family_base",
            element_type=emission.element_type,
            status_damage_emission_id=emission.status_damage_emission_id,
            status_callback_id=callback.callback_id,
            status_instance_id=str(detail.get("instance_id") or ""),
            modifier_name=callback.modifier_name,
            source_task_id=task.task_id,
            source_frame=DamageSourceFrame(
                owner_id=caster_id,
                source_id=source_id,
                source_kind="dot",
                sequence_id=sequence_id,
                target_id=target_id,
                can_continue_after_lethal=False,
                source_trace=trace,
            ),
            source_trace=trace,
            metadata={
                "damage_formula_family": "dot",
                "record_type": "dot_damage",
                "status_damage_emission_id": emission.status_damage_emission_id,
                "status_callback_id": callback.callback_id,
                "status_instance_id": str(detail.get("instance_id") or ""),
                "modifier_name": callback.modifier_name,
                "source_task_id": task.task_id,
                "damage_source_owner_id": caster_id,
                "damage_source_id": source_id,
                "damage_source_kind": "dot",
                "damage_sequence_id": sequence_id,
                "can_continue_after_lethal": False,
                "numeric_evaluation": formula_result.primary_numeric_evaluation,
                "dot_formula_result": formula_result.to_json(),
                "source_trace": trace,
            },
        )
        damage_result = self.damage.apply_packet(state, packet, window_ledger=damage_window_ledger)
        after_state = self.reducer.apply_all(state, damage_result.mutations)
        return StatusCallbackExecutionResult(
            ok=not damage_result.errors,
            after_state=after_state,
            mutations=damage_result.mutations,
            records=damage_result.records,
            events=damage_result.events,
            errors=damage_result.errors,
        )

    def _execute_delay_emissions(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        emissions: tuple[ActionDelayEmissionIR, ...],
        *,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> StatusCallbackExecutionResult:
        current_state = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        records = []
        errors = []
        for emission in emissions:
            if emission.coverage_status != "executable":
                reason = emission.blocked_reason or f"action_delay_not_executable:{emission.coverage_status}"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            if emission.opcode not in {"SetActionDelay", "ModifyActionDelay"}:
                reason = f"action_delay_opcode_not_admitted:{emission.opcode}"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            target_alias = str(emission.target_alias or "ModifierOwnerEntity")
            expression_targets: tuple[str, ...] | None = None
            if emission.target_expression_id:
                (
                    expression_targets,
                    expression_reason,
                    expression_source,
                ) = self._callback_expression_targets(
                    current_state, task, detail, trigger_event,
                    emission.target_expression_id,
                )
                if expression_reason:
                    records.append(_action_delay_blocked_record(
                        callback, task, detail, emission, expression_reason,
                    ))
                    errors.append(expression_reason)
                    continue
                if not expression_targets:
                    reason = "callback_target_expression_empty"
                    records.append(_action_delay_blocked_record(
                        callback, task, detail, emission, reason,
                    ))
                    errors.append(reason)
                    continue
                target_ids = expression_targets
                group_alias = True
            else:
                target_ids = _callback_target_group(
                    current_state,
                    detail,
                    trigger_event,
                    target_alias,
                )
                group_alias = target_alias in {
                    "AllEnemy",
                    "AllEnemyWithUnSelectable",
                    "AllLightTeam",
                    "AllLightTeam.RemoveServant",
                    "AllDarkTeam",
                    "AllTeamMember",
                    "AllTeamMemberWithUnselectable",
                    "AllTeammate",
                }
                if not target_ids and not group_alias:
                    target_id = _resolve_callback_target_id(
                        current_state,
                        detail,
                        target_alias,
                        trigger_event,
                    )
                    target_ids = (target_id,) if target_id in current_state.units else ()
            if not target_ids and group_alias:
                records.append(
                    _action_delay_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        "",
                    )
                )
                continue
            if not target_ids:
                reason = f"action_delay_target_not_resolved:{emission.target_alias or 'unknown'}"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            evaluation = _evaluate_callback_numeric(
                emission.delay_expr, current_state, detail, task, self.rules,
                template_binding_sources=template_binding_sources,
            )
            if not evaluation.ok or evaluation.value is None:
                reason = evaluation.blocked_reason or "action_delay_numeric_evaluation_failed"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                errors.append(reason)
                continue
            timeline_rule = None
            if emission.opcode == "ModifyActionDelay":
                timeline_rule, rule_reason = self.rules.select_timeline_rule()
                if timeline_rule is None:
                    reason = rule_reason or "timeline_engine_rule_missing"
                    records.append(_action_delay_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                    errors.append(reason)
                    continue
            for target_id in target_ids:
                operation = "set"
                action_value = float(evaluation.value)
                normalized_value: float | None = None
                if timeline_rule is not None:
                    speed = effective_unit_stat(current_state.units[target_id], "speed")
                    normalized_value = float(evaluation.value)
                    action_value = abs(normalized_value) * self.timeline.full_action_value(
                        speed.value,
                        timeline_rule,
                    )
                    # TBGD ModifyActionDelay stores a signed normalized delta:
                    # negative values advance the unit and positive values
                    # delay it.  TimelineSystem exposes those as explicit
                    # operations instead of an ambiguous signed "add".
                    operation = "advance" if normalized_value < 0.0 else "delay"
                adjustment = self.timeline.adjust_action_value(
                    current_state,
                    target_id,
                    operation=operation,
                    amount=action_value,
                    source="status_callback_system",
                    metadata={
                        "callback_id": callback.callback_id,
                        "task_id": task.task_id,
                        "action_delay_emission_id": emission.action_delay_emission_id,
                        "modifier_name": callback.modifier_name,
                        "event": callback.event,
                        "opcode": emission.opcode,
                        "target_alias": target_alias,
                        "normalized_value": normalized_value,
                        "numeric_evaluation": evaluation.to_json(),
                        "source_trace": {
                            "action_delay_source": emission.source.to_json(),
                            "status_callback_source": callback.source.to_json(),
                            "status_task_source": task.source.to_json(),
                            "status_instance_source": _json_dict(detail.get("source_trace")),
                        },
                    },
                    rule=timeline_rule,
                )
                if not adjustment.plan.ok:
                    reason = adjustment.plan.blocked_reason or "action_delay_timeline_adjustment_blocked"
                    records.extend(adjustment.records)
                    records.append(_action_delay_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                    errors.append(reason)
                    break
                current_state = self.reducer.apply_all(current_state, adjustment.mutations)
                mutations.extend(adjustment.mutations)
                records.extend(adjustment.records)
                mutation = adjustment.mutations[0] if adjustment.mutations else None
                if mutation is not None:
                    events.extend(
                        events_for_mutation(
                            mutation,
                            actor_id=str(detail.get("caster_id") or detail.get("owner_id") or ""),
                            source_id=str(detail.get("source_id") or callback.callback_id),
                            event_index=current_state.event_index,
                        )
                    )
                records.append(
                    SettlementRecord(
                        record_type="action_delay",
                        source="status_callback_system",
                        mutation_id=mutation.stable_id() if mutation is not None else None,
                        process_only=mutation is None,
                        payload={
                            "callback_id": callback.callback_id,
                            "task_id": task.task_id,
                            "action_delay_emission_id": emission.action_delay_emission_id,
                            "modifier_name": callback.modifier_name,
                            "event": callback.event,
                            "target_id": target_id,
                            "operation": operation,
                            "action_value": action_value,
                            "normalized_value": normalized_value,
                            "numeric_evaluation": evaluation.to_json(),
                        },
                        trace={
                            "action_delay_source": emission.source.to_json(),
                            "status_callback_source": callback.source.to_json(),
                            "status_instance_source": _json_dict(detail.get("source_trace")),
                        },
                    ).to_json()
                )
        if errors:
            return StatusCallbackExecutionResult(
                ok=False, after_state=state,
                records=tuple(record for record in records if record.get("process_only") is True),
                errors=tuple(errors),
            )
        return StatusCallbackExecutionResult(
            ok=True, after_state=current_state, mutations=tuple(mutations),
            events=tuple(events), records=tuple(records),
        )

    def _evaluate_status_damage_amount(
        self,
        state: BattleState,
        detail: dict[str, JSONValue],
        emission: StatusDamageEmissionIR,
        *,
        target_id: str | None = None,
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> NumericEvaluationResult:
        caster_id = str(detail.get("caster_id") or "")
        target_id = target_id or str(detail.get("owner_id") or "")
        actor = state.units.get(caster_id)
        target = state.units.get(target_id)
        if actor is None or target is None:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="status_damage",
                bindings={},
                source_trace=emission.source.to_json(),
                blocked_reason="actor_or_target_missing",
            )
        if emission.damage_formula_family == "break" and emission.break_amount_mode == "value":
            context = _condition_context(self.rules, state, detail, None, template_binding_sources=template_binding_sources)
            return RuleEvaluator().evaluate_numeric(
                emission.scaling_expr,
                NumericEvaluationContext(
                    binding_sources=context.binding_sources,
                    source_trace={
                        "status_damage_source": emission.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                ),
            )
        if emission.damage_formula_family in {"additional", "true_damage", "elation"}:
            modifier_owner_id = str(detail.get("owner_id") or "")
            source_unit_ids = tuple(
                dict.fromkeys(
                    unit_id
                    for unit_id in (
                        caster_id,
                        modifier_owner_id,
                        target_id,
                    )
                    if unit_id
                )
            )
            shared_owner_hashes = _unit_scope_dynamic_hashes(
                state, modifier_owner_id
            )
            status_sources = tuple(
                _strip_hashes_from_binding_source(source, shared_owner_hashes)
                for source in status_binding_sources(state, source_unit_ids)
            )
            mirrored_status_instance_ids = tuple(
                str(source.get("status_instance_id") or "")
                for source in status_sources
                if str(source.get("status_instance_id") or "")
            )
            sources = (
                *status_sources,
                binding_source_from_store_for_units(
                    store_from_state(state),
                    source_unit_ids,
                    excluded_status_instance_ids=mirrored_status_instance_ids,
                    # 回调没有能力实例；已结束能力的作用域槽位不可见。
                    excluded_scopes=("ability",),
                ),
            )
            expression = emission.scaling_expr
            additional_mode = ""
            if emission.damage_formula_family == "elation":
                expression = expression.get("elation_percentage")
            if emission.damage_formula_family == "additional":
                percentage = expression.get("damage_percentage")
                value = expression.get("damage_value")
                if isinstance(percentage, dict) and percentage.get("supported") is True:
                    expression = percentage
                    additional_mode = "attack_percentage"
                elif isinstance(value, dict) and value.get("supported") is True:
                    expression = value
                    additional_mode = "fixed_value"
                else:
                    return NumericEvaluationResult(
                        ok=False,
                        value=None,
                        expression_kind="additional_attack_property",
                        bindings={},
                        source_trace=emission.source.to_json(),
                        blocked_reason="additional_damage_numeric_expression_missing",
                    )
            evaluated = RuleEvaluator().evaluate_numeric(
                expression,
                NumericEvaluationContext(
                    binding_sources=sources,
                    source_trace={
                        "status_damage_source": emission.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                ),
            )
            if (
                emission.damage_formula_family != "additional"
                or not evaluated.ok
                or evaluated.value is None
            ):
                return evaluated
            if additional_mode == "attack_percentage":
                attack = effective_unit_stat(actor, "attack")
                amount = attack.value * float(evaluated.value)
                bindings = {
                    **evaluated.bindings,
                    "additional_damage_mode": additional_mode,
                    "attack": attack.to_json(),
                    "ratio": float(evaluated.value),
                }
            else:
                amount = float(evaluated.value)
                bindings = {
                    **evaluated.bindings,
                    "additional_damage_mode": additional_mode,
                }
            return NumericEvaluationResult(
                ok=True,
                value=amount,
                expression_kind="additional_attack_property",
                bindings=bindings,
                source_trace=evaluated.source_trace,
            )
        break_base = self.rules.break_base_damage(actor.level)
        if break_base is None or break_base.coverage_status != "executable":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="status_damage",
                bindings={"actor_level": actor.level},
                source_trace=emission.source.to_json(),
                blocked_reason="break_base_damage_missing_or_not_executable",
            )
        context = _condition_context(self.rules, state, detail, None, template_binding_sources=template_binding_sources)
        evaluated = RuleEvaluator().evaluate_numeric(
            emission.scaling_expr,
            NumericEvaluationContext(
                binding_sources=context.binding_sources,
                source_trace={
                    "status_damage_source": emission.source.to_json(),
                    "status_instance_source": _json_dict(detail.get("source_trace")),
                    "break_base_damage_source": break_base.to_json(),
                },
            ),
        )
        if not evaluated.ok or evaluated.value is None:
            return evaluated
        return replace(
            evaluated,
            value=float(evaluated.value) * break_base.break_base_damage,
            bindings={
                **evaluated.bindings,
                "break_percentage": evaluated.value,
                "break_base_damage": break_base.break_base_damage,
            },
        )

    def _queue_insert_abort_binding(
        self,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        continuation: TaskGraphContinuation | None,
        intent: QueueIntentIR,
    ) -> dict[str, JSONValue] | None:
        """Bind one formal TurnInsertAction node to its delayed abort branch.

        The binding is audit data for the queue entry: the cancellation path
        re-enters the same source graph instead of a character-specific runner.
        """

        if continuation is None or task.opcode != "TurnInsertAction":
            return None
        node_result = self.rules.query_task_graph_node(continuation.parent_graph_node_id)
        node = node_result.value
        if (
            node_result.status != "resolved"
            or type(node) is not TaskGraphNodeIR
            or node.opcode != "TurnInsertAction"
            or node.formal_task_id != task.task_id
        ):
            return None
        abort_branches = tuple(
            branch for branch in node.branches if branch.branch_kind == "insert_abort"
        )
        if len(abort_branches) != 1 or not abort_branches[0].child_node_ids:
            return None
        child_task_ids: list[str] = []
        for child_node_id in abort_branches[0].child_node_ids:
            child_result = self.rules.query_task_graph_node(child_node_id)
            child = child_result.value
            if child_result.status != "resolved" or type(child) is not TaskGraphNodeIR:
                return None
            child_task_ids.append(child.formal_task_id)
        return {
            "callback_id": callback.callback_id,
            "event": callback.event,
            "graph_id": continuation.parent_graph_id,
            "graph_node_id": node.graph_node_id,
            "child_formal_task_ids": child_task_ids,
            "owner_id": str(detail.get("owner_id") or ""),
            "modifier_name": str(detail.get("modifier_name") or ""),
            "status_instance_id": str(detail.get("instance_id") or ""),
            "queue_intent_id": intent.queue_intent_id,
            "custom_tag": intent.custom_tag,
        }

    def _callback_expression_targets(
        self,
        state: BattleState,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        expression_id: str,
    ) -> tuple[tuple[str, ...] | None, str, dict[str, JSONValue]]:
        """Resolve a callback task's target expression with its caster context.

        Simple alias targets keep their alias path; this resolver only covers a
        full target expression (a source-local alias or a composite/filtered
        target) whose ids must be computed before the callback writes state.
        """

        expression = self.rules.target_expression(expression_id)
        if expression is None:
            return None, "callback_target_expression_missing", {}
        if expression.coverage_status != "executable" or expression.blocked_reason:
            return (
                None,
                "callback_target_expression_blocked:"
                + str(expression.blocked_reason or expression.coverage_status),
                {},
            )
        context = _effect_context(self.rules, state, task, detail, trigger_event)
        target_context = TargetEvaluationContext(
            caster_id=context.caster_id,
            effect_owner_id=context.owner_id,
            parameter_entity_ids=(
                (context.param_entity_id,) if context.param_entity_id else ()
            ),
            selected_target_ids=(
                (context.current_action_target_id,)
                if context.current_action_target_id
                else ()
            ),
            current_target_id=context.current_action_target_id,
            event_source_id=(
                trigger_event.source_id
                if trigger_event is not None
                and trigger_event.source_id in state.units
                else None
            ),
            event_target_id=(
                trigger_event.target_id if trigger_event is not None else None
            ),
            turn_owner_id=committed_turn_owner_id(state),
            action_event_id=(
                trigger_event.event_id
                if trigger_event is not None
                and trigger_event.event_id
                and trigger_event.window
                else None
            ),
            action_window=(
                trigger_event.window
                if trigger_event is not None
                and trigger_event.event_id
                and trigger_event.window
                else None
            ),
            admitted_action_target_fact=(
                trigger_event.admitted_action_target_fact
                if trigger_event is not None
                else None
            ),
            expected_action_window_scope=(
                trigger_event.expected_action_window_scope
                if trigger_event is not None
                else None
            ),
        )
        resolution = self.targets.resolve_target_expression(
            state,
            expression,
            context=target_context,
            target_resolution=context.target_resolution,
            condition_event_payload=context.event_payload,
            dynamic_values=context.dynamic_values,
            binding_sources=context.binding_sources,
        )
        if not resolution.resolved:
            return (
                None,
                "callback_target_expression_blocked:"
                + (resolution.blocked_reason or "unresolved"),
                resolution.to_json(),
            )
        return tuple(resolution.target_ids), "", resolution.to_json()

    def _queue_expression_targets(
        self,
        state: BattleState,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        intent: QueueIntentIR,
    ) -> tuple[tuple[str, ...] | None, str, dict[str, JSONValue]]:
        """Resolve a queue insert's full AbilityTarget expression."""

        expression_id = intent.ability_target_expression_id
        if not expression_id:
            return None, "", {}
        targets, reason, source = self._callback_expression_targets(
            state, task, detail, trigger_event, expression_id
        )
        if not reason:
            return targets, "", source
        if reason == "callback_target_expression_missing":
            return None, "queue_ability_target_expression_missing", source
        return (
            None,
            "queue_ability_target_expression_blocked:"
            + reason.removeprefix("callback_target_expression_blocked:"),
            source,
        )

    def _execute_queue_intents(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        intents: tuple[QueueIntentIR, ...],
        *,
        task_graph_continuation: TaskGraphContinuation | None = None,
    ) -> StatusCallbackExecutionResult:
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        errors: list[str] = []
        for intent in intents:
            if intent.coverage_status != "executable":
                reason = intent.blocked_reason or f"queue_intent_not_executable:{intent.coverage_status}"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            window = self.rules.queue_window_for_intent(intent.queue_intent_id)
            if window is None:
                reason = "queue_window_ir_missing"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            if window.coverage_status != "executable":
                reason = window.blocked_reason or f"queue_window_not_executable:{window.coverage_status}"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            deathrattle_admission, deathrattle_admission_reason = (
                _deathrattle_queue_admission(
                    current_state, callback, task, detail, trigger_event, intent
                )
            )
            if deathrattle_admission_reason:
                records.append(_queue_intent_blocked_record(
                    callback, task, detail, intent, deathrattle_admission_reason
                ))
                errors.append(deathrattle_admission_reason)
                continue
            limbo_unit_id, limbo_admission_reason, limbo_admission = (
                _limbo_rescue_queue_admission(
                    callback, task, detail, trigger_event, intent
                )
            )
            if limbo_admission_reason:
                records.append(_queue_intent_blocked_record(
                    callback, task, detail, intent, limbo_admission_reason
                ))
                errors.append(limbo_admission_reason)
                continue
            expression_targets, expression_reason, expression_source = (
                self._queue_expression_targets(
                    current_state, task, detail, trigger_event, intent
                )
            )
            if expression_reason:
                records.append(_queue_intent_blocked_record(
                    callback, task, detail, intent, expression_reason
                ))
                errors.append(expression_reason)
                continue
            target_resolution = self.queue_targets.resolve(
                current_state,
                detail=detail,
                trigger_event=trigger_event,
                actor_alias=intent.actor_target_alias,
                target_alias=intent.ability_target_alias,
                source_trace={
                    "queue_window_source": window.source.to_json(),
                    "queue_intent_source": intent.source.to_json(),
                },
                allow_unselectable_target=intent.can_run_on_unselectable_target,
                deathrattle_admission=deathrattle_admission,
                limbo_unit_id=limbo_unit_id,
                expression_target_ids=expression_targets,
                expression_target_source=expression_source or None,
            )
            if not target_resolution.ok:
                reason = target_resolution.blocked_reason or "queue_target_resolution_failed"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            alive_state_reason = (
                ""
                if deathrattle_admission is not None or limbo_unit_id
                else _queue_intent_alive_state_blocked_reason(
                    current_state, intent, target_resolution
                )
            )
            if alive_state_reason:
                records.append(_queue_intent_blocked_record(
                    callback, task, detail, intent, alive_state_reason
                ))
                errors.append(alive_state_reason)
                continue
            precheck_reason = _queue_insert_precheck_blocked(current_state, intent)
            if precheck_reason:
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, precheck_reason))
                errors.append(precheck_reason)
                continue
            priority_resolution = _queue_priority_value_resolution(
                self.value_resolver,
                intent,
                callback,
                task,
                detail,
            )
            if not priority_resolution.get("ok"):
                reason = (
                    "queue_priority_value_resolution_blocked:"
                    f"{priority_resolution.get('blocked_reason') or 'unknown'}"
                )
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            elation_override_points = None
            override_evaluation = None
            if intent.elation_point_override_expr is not None:
                context = _condition_context(self.rules, current_state, detail, trigger_event)
                override_evaluation = self.evaluator.evaluate_numeric(
                    intent.elation_point_override_expr,
                    NumericEvaluationContext(binding_sources=context.binding_sources,
                                             source_trace=intent.source.to_json()),
                )
                value = override_evaluation.value
                if (not override_evaluation.ok or type(value) not in (int, float)
                        or not math.isfinite(value) or value < 0 and value != -1):
                    reason = "queue_elation_override_blocked:" + (
                        override_evaluation.blocked_reason or "finite_points_or_no_override_sentinel_required")
                    records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                    errors.append(reason)
                    continue
                elation_override_points = None if value == -1 else float(value)
            lifecycle_policy_id = ""
            extra_action_policy_id = ""
            if isinstance(window.window_policy, dict):
                lifecycle_policy_id = str(window.window_policy.get("queue_lifecycle_policy_id") or "")
                extra_action_policy_id = str(window.window_policy.get("extra_action_policy_id") or "")
            queue_name = intent.queue_kind
            source_trace = {
                "queue_intent_source": intent.source.to_json(),
                "queue_window_source": window.source.to_json(),
                "queue_lifecycle_policy_id": lifecycle_policy_id,
                "extra_action_policy_id": extra_action_policy_id,
                "queue_intent_resource_policy": _queue_resource_policy(intent),
                "queue_priority_value_resolution": priority_resolution,
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            }
            entry = QueueEntry(
                entry_id=f"queue_entry:{intent.queue_intent_id}:{len(current_state.queues.get(queue_name, ()))}",
                queue_name=queue_name,
                queue_kind=intent.queue_kind,
                queue_intent_id=intent.queue_intent_id,
                actor_id=target_resolution.actor_id,
                action_or_ability_ref=intent.action_ref_or_ability_name,
                target_ids=target_resolution.target_ids,
                priority_source=intent.priority_source,
                source_trace=source_trace,
                resource_policy=_queue_resource_policy(intent),
                priority_key=str(intent.priority_source.get("priority_key") or ""),
                priority_value=_json_float(priority_resolution.get("value")),
                queue_priority_id=str(intent.priority_source.get("queue_priority_id") or ""),
                priority_source_trace=_json_dict(intent.priority_source.get("source_trace")),
                queue_window_id=window.queue_window_id,
                window_family=window.window_family,
                window_policy=window.window_policy,
                target_resolution=target_resolution.to_json(),
                owner_id=str(detail.get("owner_id") or ""),
                source_id=str(detail.get("source_id") or callback.callback_id),
                expiration_policy={
                    "status": "source_gap_blocked",
                    "blocked_reason": "queue_expiration_policy_source_missing",
                },
                cancel_policy={
                    "abort_behavior_flags": intent.abort_policy.get("AbortBehaviorFlags", []),
                    "actor_removed": "blocked_process_only",
                    "actor_defeated": "blocked_process_only",
                    "target_invalid": "blocked_process_only",
                    "retarget": "source_gap_blocked",
                },
                status="pending",
                drain_status="not_admitted",
                elation_override_points=elation_override_points,
                custom_tag=intent.custom_tag,
                owner_alive_state=intent.owner_alive_state,
                target_alive_state=intent.target_alive_state,
                can_run_on_unselectable_target=intent.can_run_on_unselectable_target,
                deathrattle_admission=(
                    deathrattle_admission.to_json()
                    if deathrattle_admission is not None
                    else None
                ),
                limbo_rescue_admission=(
                    limbo_admission.to_json()
                    if limbo_admission is not None
                    else None
                ),
                insert_abort=self._queue_insert_abort_binding(
                    callback, task, detail, task_graph_continuation, intent
                ),
            )
            mutation = self.queue.enqueue(
                current_state,
                queue_name,
                entry,
                source="queue_system",
                metadata={
                    "queue_intent_id": intent.queue_intent_id,
                    "source_task_id": task.task_id,
                    "callback_id": callback.callback_id,
                    "opcode": intent.opcode,
                    "queue_kind": intent.queue_kind,
                    "queue_priority_id": entry.queue_priority_id,
                    "queue_window_id": entry.queue_window_id,
                    "queue_lifecycle_policy_id": lifecycle_policy_id,
                    "extra_action_policy_id": extra_action_policy_id,
                    "window_family": entry.window_family,
                    "priority_key": entry.priority_key,
                    "priority_value": entry.priority_value,
                    "priority_value_resolution": priority_resolution,
                    "elation_override_evaluation": override_evaluation.to_json() if override_evaluation else None,
                    "admission_result": "executable",
                    "target_resolution": target_resolution.to_json(),
                    "source_trace": source_trace,
                },
            )
            current_state = self.reducer.apply_all(current_state, (mutation,))
            mutations.append(mutation)
            records.append(
                SettlementRecord(
                    record_type="queue_enqueue",
                    source="queue_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        "queue_intent_id": intent.queue_intent_id,
                        "callback_id": callback.callback_id,
                        "task_id": task.task_id,
                        "opcode": intent.opcode,
                        "queue_name": queue_name,
                        "queue_kind": intent.queue_kind,
                        "entry": entry.to_json(),
                        "queue_window": window.to_json(),
                        "priority_value_resolution": priority_resolution,
                        "drain_candidate": False,
                        "drain_blocked_reason": "queue_drain_pending_resolution",
                    },
                    trace=source_trace,
                ).to_json()
            )
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            errors=tuple(errors),
        )

    def _precheck_selected_queue_group(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        parent_task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        selected_child_ids: tuple[str, ...],
        tasks: dict[str, StatusCallbackTaskIR],
    ) -> StatusCallbackExecutionResult | None:
        for child_id in selected_child_ids:
            child = tasks.get(child_id)
            if child is None:
                continue
            intents = tuple(
                intent
                for intent in self.rules.queue_intents_for_callback(callback.callback_id)
                if intent.source_task_id == child.task_id
            )
            if not intents:
                continue
            for intent in intents:
                if intent.coverage_status != "executable":
                    continue
                window = self.rules.queue_window_for_intent(intent.queue_intent_id)
                if window is None or window.coverage_status != "executable":
                    continue
                expression_targets, expression_reason, expression_source = (
                    self._queue_expression_targets(
                        state, child, detail, trigger_event, intent
                    )
                )
                if expression_reason:
                    continue
                target_resolution = self.queue_targets.resolve(
                    state,
                    detail=detail,
                    trigger_event=trigger_event,
                    actor_alias=intent.actor_target_alias,
                    target_alias=intent.ability_target_alias,
                    source_trace={
                        "queue_window_source": window.source.to_json(),
                        "queue_intent_source": intent.source.to_json(),
                    },
                    expression_target_ids=expression_targets,
                    expression_target_source=expression_source or None,
                )
                if not target_resolution.ok:
                    continue
                reason = _queue_insert_precheck_blocked(state, intent)
                if not reason:
                    continue
                records = (
                    _task_blocked_record(
                        callback,
                        parent_task,
                        detail,
                        reason,
                        ok=False,
                        selected_child_ids=selected_child_ids,
                    ),
                    _queue_intent_blocked_record(callback, child, detail, intent, reason),
                )
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    records=records,
                    errors=(reason,),
                )
        return None

    def _blocked_queue_intents(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        intents: tuple[QueueIntentIR, ...],
        reason: str,
    ) -> StatusCallbackExecutionResult:
        blocked_reason = f"queue_task_not_executable:{reason}"
        return StatusCallbackExecutionResult(
            ok=False,
            after_state=state,
            records=tuple(
                _queue_intent_blocked_record(callback, task, detail, intent, blocked_reason)
                for intent in intents
            ),
            errors=(blocked_reason,),
        )


def _status_action_window_target_resolution(
    state: BattleState,
    event: GameEvent,
    detail: dict[str, JSONValue],
) -> tuple[TargetResolution | None, str]:
    if type(event) is not GameEvent or not event.event_type.startswith("action.window."):
        return None, "status_action_window_target_event_invalid"
    payload = event.payload
    raw_selected = payload.get("selected_target_ids")
    if not isinstance(raw_selected, (list, tuple)):
        return None, "status_action_window_target_scope_missing"
    selected = tuple(raw_selected)
    if (
        not selected
        or any(type(item) is not str or not item for item in selected)
        or len(selected) != len(set(selected))
        or any(item not in state.units for item in selected)
    ):
        return None, "status_action_window_target_scope_invalid"
    primary = ""
    for key in (
        "primary_action_target_id",
        "primary_target_id",
        "current_hit_target_id",
        "target_id",
        "param_entity_id",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            primary = value
            break
    if not primary and isinstance(event.target_id, str):
        primary = event.target_id
    if not primary:
        primary = selected[0]
    if primary not in state.units:
        return None, "status_action_window_primary_target_invalid"
    if primary not in selected:
        selected = (primary, *selected)
    raw_requested = payload.get("requested_target_ids")
    if isinstance(raw_requested, (list, tuple)):
        requested = tuple(raw_requested)
        if (
            any(type(item) is not str or not item for item in requested)
            or len(requested) != len(set(requested))
        ):
            return None, "status_action_window_requested_target_scope_invalid"
    else:
        requested = selected
    return (
        TargetResolution(
            requested=requested,
            selectable=selected,
            legal=selected,
            primary=primary,
            impact_group=selected,
            selected=selected,
            rejected=(),
            reason="status_action_window_formal_root",
            source="status_callback_system",
            metadata={
                "event_id": event.event_id or str(event.to_json().get("event_id") or ""),
                "status_instance_id": str(detail.get("instance_id") or ""),
                "status_owner_id": str(detail.get("owner_id") or ""),
            },
        ),
        "",
    )


def _queue_resource_policy(intent: QueueIntentIR) -> dict[str, JSONValue]:
    policy = intent.abort_policy.get("resource_policy") if isinstance(intent.abort_policy, dict) else None
    return policy if isinstance(policy, dict) else {}


def _queue_priority_value_resolution(
    value_resolver: ValueResolver,
    intent: QueueIntentIR,
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    source_trace = {
        "queue_intent_source": intent.source.to_json(),
        "queue_priority_source": _json_dict(intent.priority_source.get("source_trace")),
        "status_callback_source": callback.source.to_json(),
        "status_task_source": task.source.to_json(),
        "status_instance_source": _json_dict(detail.get("source_trace")),
    }
    priority_value = intent.priority_source.get("priority_value")
    priority_expression = (
        numeric_fixed(float(priority_value))
        if isinstance(priority_value, (int, float)) and not isinstance(priority_value, bool)
        else numeric_missing("queue_priority_value_not_numeric")
    )
    resolution = value_resolver.resolve(
        ValueBindingRequest(
            binding_kind="runtime_numeric_expression",
            expression=priority_expression,
            required_context_keys=("status_modifier",),
            source_trace=source_trace,
        ),
        ValueContext(
            owner_id=str(detail.get("owner_id") or ""),
            status_id=str(detail.get("status_id") or ""),
            modifier_name=str(detail.get("modifier_name") or callback.modifier_name),
            source_trace=source_trace,
        ),
    )
    return resolution.to_json()


_INSERT_ACTION_LEGAL_CANCEL_REASONS = frozenset({
    "queue_insert_precheck_same_tag_pending",
})


def _deathrattle_queue_admission(
    state: BattleState,
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    trigger_event: GameEvent | None,
    intent: QueueIntentIR,
) -> tuple[DeathrattleQueueAdmission | None, str]:
    """Bind one OnDeathrattle insert to the death instance that produced it.

    Only the unit's own just-recorded death can carry the limited Mask_AliveOrLimbo
    queue authority; the exact source modifier instance, the formal callback and
    its executable OnDeathrattle task, the lethal HP mutation and the death event
    identity all have to agree with the written death record.
    """

    if callback.event != "OnDeathrattle":
        return None, ""
    if (
        not isinstance(task, StatusCallbackTaskIR)
        or task.callback_id != callback.callback_id
        or task.event != "OnDeathrattle"
        or task.task_id not in callback.task_ids
        or task.task_id != intent.source_task_id
        or task.modifier_name != callback.modifier_name
        or callback.coverage_status != "executable"
        or callback.blocked_reason
        or task.coverage_status != "executable"
        or task.blocked_reason
    ):
        return None, "deathrattle_admission_source_callback_not_admitted"
    if trigger_event is None or trigger_event.event_type != "unit.defeated":
        return None, "deathrattle_admission_trigger_event_missing"
    unit_id = str(detail.get("owner_id") or "")
    payload = trigger_event.payload
    defeated_unit_id = str(
        payload.get("defeated_unit_id") or payload.get("target_id") or ""
    )
    death_instance_id = str(payload.get("lifecycle_mutation_id") or "")
    if not unit_id or defeated_unit_id != unit_id or not death_instance_id:
        return None, "deathrattle_admission_death_identity_missing"
    unit = state.units.get(unit_id)
    record = unit.flags.get("defeat_record") if unit is not None else None
    if not isinstance(record, dict):
        return None, "deathrattle_admission_defeat_record_missing"
    if str(record.get("lifecycle_mutation_id") or "") != death_instance_id:
        return None, "deathrattle_admission_death_instance_mismatch"
    event_hp_mutation_id = str(payload.get("hp_mutation_id") or "")
    record_hp_mutation_id = str(record.get("hp_mutation_id") or "")
    if not record_hp_mutation_id or (
        event_hp_mutation_id and event_hp_mutation_id != record_hp_mutation_id
    ):
        return None, "deathrattle_admission_hp_mutation_mismatch"
    if (
        str(record.get("target_id") or "") != unit_id
        or str(record.get("defeated_unit_id") or "") != unit_id
    ):
        return None, "deathrattle_admission_defeat_record_mismatch"
    if trigger_event.event_id != mutation_backed_event_id(
        death_instance_id, "unit.defeated"
    ):
        return None, "deathrattle_admission_source_event_mismatch"
    instance_id = str(detail.get("instance_id") or "")
    modifier_name = str(detail.get("modifier_name") or "")
    if (
        not instance_id
        or not modifier_name
        or str(detail.get("owner_id") or "") != unit_id
    ):
        return None, "deathrattle_admission_source_status_missing"
    if "Deathrattle" not in tuple(detail.get("behavior_flags") or ()):
        return None, "deathrattle_admission_source_flag_missing"
    if modifier_name != callback.modifier_name or modifier_name != task.modifier_name:
        return None, "deathrattle_admission_source_modifier_mismatch"
    if (
        intent.owner_alive_state != "alive_or_limbo"
        or intent.target_alive_state != "alive_or_limbo"
        or intent.can_run_on_unselectable_target is not True
        or not intent.action_ref_or_ability_name
        or intent.coverage_status != "executable"
        or intent.blocked_reason
        or intent.callback_id != callback.callback_id
        or intent.source_task_id != task.task_id
    ):
        return None, "deathrattle_admission_queue_contract_not_admitted"
    return (
        DeathrattleQueueAdmission(
            unit_id=unit_id,
            death_instance_id=death_instance_id,
            hp_mutation_id=record_hp_mutation_id,
            source_event_id=str(trigger_event.event_id or ""),
            source_status_instance_id=instance_id,
            source_modifier_name=modifier_name,
            ability_name=intent.action_ref_or_ability_name,
            queue_intent_id=intent.queue_intent_id,
            queue_kind=intent.queue_kind,
            source_task_id=intent.source_task_id,
        ),
        "",
    )


def _queue_intent_alive_state_blocked_reason(
    state: BattleState,
    intent: QueueIntentIR,
    target_resolution: object,
) -> str:
    """Re-verify the source alive-state masks before the entry is created."""

    actor_id = str(getattr(target_resolution, "actor_id", "") or "")
    target_ids = tuple(getattr(target_resolution, "target_ids", ()) or ())
    reason = unit_alive_state_blocked_reason(
        state, actor_id, intent.owner_alive_state, role="owner"
    )
    if reason:
        return reason
    for target_id in target_ids:
        reason = unit_alive_state_blocked_reason(
            state, target_id, intent.target_alive_state, role="target"
        )
        if reason:
            return reason
    return ""


def _queue_insert_precheck_blocked(state: BattleState, intent: QueueIntentIR) -> str:
    """Count already queued, not yet consumed insert actions with the same tag.

    SameTagInsertUnusedCount compares the pending insertion count for the
    entry's own CustomTag; it is not a permanent per-unit debuff guard. The
    maximum is a fixed source value or the check stays blocked.
    """

    policy = intent.abort_policy.get("insert_once_policy") if isinstance(intent.abort_policy, dict) else None
    if not isinstance(policy, dict):
        return ""
    if policy.get("kind") != "same_tag_insert_unused_count":
        return ""
    custom_tag = str(policy.get("custom_tag") or intent.custom_tag or "")
    if not custom_tag:
        return "queue_insert_precheck_custom_tag_missing"
    maximum = _fixed_precheck_maximum(policy.get("max_count_expr"))
    if maximum is None:
        return "queue_insert_precheck_max_count_unresolved"
    pending = 0
    for entries in state.queues.values():
        if not isinstance(entries, (list, tuple)):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("custom_tag") != custom_tag:
                continue
            if str(entry.get("status") or "pending") != "pending":
                continue
            pending += 1
    if pending >= maximum:
        return "queue_insert_precheck_same_tag_pending"
    return ""


def _fixed_precheck_maximum(expression: object) -> int | None:
    if not isinstance(expression, Mapping):
        return None
    if expression.get("kind") != "fixed":
        return None
    value = expression.get("value")
    if type(value) not in (int, float) or isinstance(value, bool):
        return None
    if value != int(value) or value < 0:
        return None
    return int(value)


def _retarget_candidates(
    state: BattleState,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    trigger_event: GameEvent | None,
) -> tuple[str, ...]:
    policy = task.retarget_policy
    if not isinstance(policy, dict):
        return ()
    alias = str(policy.get("target_alias") or "")
    if alias != "ParamEntityAttackTargetList.SortByHP":
        return ()
    payload = trigger_event.payload if trigger_event is not None and isinstance(trigger_event.payload, dict) else {}
    candidates = _unique_ids(
        payload.get("param_entity_attack_target_ids"),
        payload.get("selected_target_ids"),
        payload.get("target_ids"),
        payload.get("current_hit_target_id"),
        payload.get("primary_target_id"),
        payload.get("target_id"),
    )
    candidates = tuple(unit_id for unit_id in candidates if unit_id in state.units)
    alive_candidates = tuple(unit_id for unit_id in candidates if _unit_alive(state, unit_id))
    if not alive_candidates:
        alive_candidates = _alive_enemy_ids_for_status_owner(state, detail)
    return tuple(sorted(alive_candidates, key=lambda unit_id: (_hp_ratio(state, unit_id), state.units[unit_id].hp, unit_id)))


def _retarget_max_number(task: StatusCallbackTaskIR) -> int:
    policy = task.retarget_policy
    expr = policy.get("max_number_expr") if isinstance(policy, dict) else None
    if isinstance(expr, dict) and expr.get("kind") == "fixed":
        value = expr.get("value")
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return 1


def _retarget_event(event: GameEvent | None, target_id: str) -> GameEvent:
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    payload.update(
        {
            "param_entity_id": target_id,
            "current_hit_target_id": target_id,
            "target_id": target_id,
            "retargeted": True,
            "retarget_source_event_id": event.event_id if event is not None else "",
        }
    )
    if event is not None:
        return replace(
            event,
            target_id=target_id,
            event_id=(
                f"{event.event_id}:retarget:{target_id}"
                if event.event_id
                else f"event:retarget:{target_id}"
            ),
            process_only=True,
            payload=payload,
        )
    return GameEvent(
        "status.retarget",
        target_id=target_id,
        event_id=f"event:retarget:{target_id}",
        window="Retarget",
        process_only=True,
        payload=payload,
    )


def _callback_scoped_event(
    event: GameEvent | None,
    *,
    callback_scope: str,
    decision_index: int,
) -> GameEvent:
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    payload.update(
        {
            "callback_decision_scope": callback_scope,
            "callback_decision_index": decision_index,
        }
    )
    base_id = event.event_id if event is not None else ""
    scoped_id = (
        f"{base_id}:scope:{callback_scope}:{decision_index}"
        if base_id
        else f"event:scope:{callback_scope}:{decision_index}"
    )
    if event is not None:
        return replace(
            event,
            event_id=scoped_id,
            process_only=True,
            payload=payload,
        )
    return GameEvent(
        "status.callback.scope",
        event_id=scoped_id,
        window="status_callback",
        process_only=True,
        payload=payload,
    )


def _condition_rng_event(
    event: GameEvent | None,
    *,
    selected: bool,
    choice_key: str,
) -> GameEvent:
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    payload.update(
        {
            "condition_random_result": selected,
            "condition_random_choice_key": choice_key,
        }
    )
    return GameEvent(
        event.event_type if event is not None else "status.condition.random",
        source_id=event.source_id if event is not None else "",
        target_id=event.target_id if event is not None else "",
        event_id=event.event_id if event is not None else "",
        window=event.window if event is not None else "status_condition",
        process_only=True,
        payload=payload,
    )


def _condition_random_chance_nodes(condition) -> tuple[tuple[str, object], ...]:
    found: list[tuple[str, object]] = []
    if getattr(condition, "opcode", "") == "ByRandomChance":
        found.append(("$", condition.payload.get("Chance")))

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            opcode = value.get("opcode") or value.get("expression_kind")
            if opcode == "ByRandomChance":
                found.append((path, value.get("Chance")))
            for key, item in value.items():
                visit(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(getattr(condition, "payload", {}), "$.payload")
    deduped: list[tuple[str, object]] = []
    seen: set[str] = set()
    for path, expression in found:
        if path not in seen:
            seen.add(path)
            deduped.append((path, expression))
    return tuple(deduped)


def _unique_ids(*values: object) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str):
            if value and value not in result:
                result.append(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item and item not in result:
                    result.append(item)
    return tuple(result)


def _unit_alive(state: BattleState, unit_id: str) -> bool:
    unit = state.units.get(unit_id)
    return bool(
        unit is not None and runtime_unit_is_target_candidate(unit)
    )


def _alive_enemy_ids_for_status_owner(state: BattleState, detail: dict[str, JSONValue]) -> tuple[str, ...]:
    owner_id = str(detail.get("owner_id") or "")
    owner = state.units.get(owner_id)
    if owner is None:
        return ()
    return tuple(
        unit_id
        for unit_id, unit in sorted(state.units.items())
        if runtime_units_are_opposing_combat_teams(owner, unit)
        and runtime_unit_is_target_candidate(unit)
    )


def _hp_ratio(state: BattleState, unit_id: str) -> float:
    unit = state.units[unit_id]
    maximum = current_max_hp(unit)
    return float(unit.hp / maximum) if maximum > 0 else float("inf")


def _break_base_source_from_evaluation(evaluation: NumericEvaluationResult) -> dict[str, JSONValue]:
    direct = evaluation.source_trace.get("break_base_damage_source")
    if isinstance(direct, dict) and isinstance(direct.get("level"), int):
        return direct
    bindings = evaluation.bindings
    operands = bindings.get("dynamic_operands") if isinstance(bindings, dict) else None
    if not isinstance(operands, list):
        return {}
    for operand in operands:
        if not isinstance(operand, dict):
            continue
        binding = operand.get("bindings")
        if not isinstance(binding, dict):
            continue
        entry = binding.get("entry")
        if not isinstance(entry, dict) or entry.get("name") != "CasterBreakBaseDamage":
            continue
        source_trace = entry.get("source_trace")
        if isinstance(source_trace, dict):
            break_base = source_trace.get("break_base_damage")
            return break_base if isinstance(break_base, dict) else source_trace
    return {}


def _break_template_id_from_detail(detail: dict[str, JSONValue]) -> str:
    value = detail.get("break_template_id")
    return str(value) if isinstance(value, str) else ""


def _break_element_from_detail(detail: dict[str, JSONValue]) -> str | None:
    value = detail.get("break_element_type")
    return str(value) if isinstance(value, str) and value else None


def _resolve_callback_target_id(
    state: BattleState,
    detail: dict[str, JSONValue],
    target_alias: str | None,
    event: GameEvent | None,
) -> str:
    alias = target_alias or "ModifierOwnerEntity"
    if alias == "ModifierOwnerEntity":
        return str(detail.get("owner_id") or "")
    if alias == "Caster":
        return str(detail.get("caster_id") or "")
    if alias in {
        "ActualOwner",
        "ModifierOwnerSummoner",
        "ModifierOwnerEntity.GetSummoner",
    }:
        owner_id = str(detail.get("owner_id") or "")
        relation_id = _unit_relation_id_from_state(state, owner_id)
        if relation_id:
            return relation_id
        return _unit_relation_id_from_detail(
            detail,
            owner_id,
            "summoner_id",
            "owner_id",
        )
    if alias in {
        "ParamEntity",
        "CurrentActionTarget",
        "AbilityTargetEntity",
        "DamageDefenderEntity",
    }:
        if event is not None and (event.queue_action_terminal_fact or event.queue_action_start_fact) is not None:
            fact = event.queue_action_terminal_fact or event.queue_action_start_fact
            return fact.actor_id if alias == "ParamEntity" else next(iter(fact.target_ids), "")
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        return _first_payload_str(payload, ("param_entity_id", "current_hit_target_id", "damage_defender_id", "primary_target_id", "target_id")) or (
            str(event.target_id or "") if event is not None else ""
        )
    if alias == "DamageAttackerEntity":
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        return _first_payload_str(payload, ("damage_attacker_id", "actor_id", "source_id")) or (
            str(event.source_id or "") if event is not None else ""
        )
    if alias in {"CurrentTurnOwnerEntity", "CurrentTurnActionEntity"}:
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        return _first_payload_str(
            payload, ("turn_owner_id", "turn_action_entity_id", "actor_id")
        ) or (str(event.source_id or "") if event is not None else "")
    if alias == "ParamEntity2":
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        return _first_payload_str(payload, ("param_entity_2_id", "param_entity2_id", "secondary_target_id"))
    if "." in alias:
        # 点号关系别名（Caster.GetSummoner 等）统一走 effect 层的关系解析。
        return (
            _resolve_target_alias(
                alias,
                caster_id=str(detail.get("caster_id") or ""),
                owner_id=str(detail.get("owner_id") or ""),
                param_entity_id=None,
                current_action_target_id=None,
                state=state,
            )
            or ""
        )
    return ""


def _callback_task_target_expression_id(
    rules: RuleBook,
    task: StatusCallbackTaskIR,
) -> tuple[str, str]:
    if task.target_expression_id:
        return task.target_expression_id, ""
    if not task.effect_id:
        return "", ""
    effect = rules.effect(task.effect_id)
    if effect is None:
        return "", ""
    task_evidence = task.source.evidence
    effect_evidence = effect.source.evidence
    if (
        effect.source.source_path != task.source.source_path
        or effect.source.raw_id != task.source.raw_id
        or any(
            task_evidence.get(key) != effect_evidence.get(key)
            for key in ("callback_id", "task_path", "opcode")
        )
    ):
        return "", "status_callback_target_effect_source_mismatch"
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return "", ""
    expression_id = standard.get("target_expression_id")
    if not isinstance(expression_id, str) or not expression_id:
        return "", ""
    expression = rules.target_expression(expression_id)
    if expression is None:
        return expression_id, ""
    expression_evidence = expression.source.evidence
    if (
        expression.source.source_path != task.source.source_path
        or expression_evidence.get("source_raw_id") != task.source.raw_id
        or any(
            task_evidence.get(key) != expression_evidence.get(key)
            for key in ("callback_id", "task_path", "opcode")
        )
    ):
        return "", "status_callback_target_expression_source_mismatch"
    return expression_id, ""


def _callback_target_group(
    state: BattleState,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
    alias: str,
) -> tuple[str, ...]:
    owner_id = str(detail.get("owner_id") or detail.get("caster_id") or "")
    owner = state.units.get(owner_id)
    if alias in {"AllEnemy", "AllEnemyWithUnSelectable"} and owner is not None:
        include_unselectable = alias == "AllEnemyWithUnSelectable"
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if runtime_units_are_opposing_combat_teams(owner, unit)
            and runtime_unit_is_target_candidate(
                unit,
                include_unselectable=include_unselectable,
            )
        )
    if alias in {
        "AllLightTeam",
        "AllLightTeam.RemoveServant",
        "AllLightTeamWithUnselectable",
        "AllLightTeamWithAllLightTeamUnselectable",
        "AllLightTeamWithAllUnselectableLightTeam",
    }:
        include_unselectable = "WithUnselectable" in alias or "WithAll" in alias
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if runtime_unit_is_light_team(unit)
            and runtime_unit_is_target_candidate(
                unit,
                include_unselectable=include_unselectable,
            )
            and (
                "RemoveServant" not in alias
                or unit.flags.get("summon_kind") != "servant"
            )
        )
    if alias == "AllDarkTeam":
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if runtime_unit_is_dark_team(unit)
            and runtime_unit_is_target_candidate(unit)
        )
    if alias in {
        "AllTeamMember",
        "AllTeamMemberWithUnselectable",
        "AllTeammate",
        "AllTeammateWithUnselectable",
    } and owner is not None:
        include_unselectable = alias in {
            "AllTeamMemberWithUnselectable",
            "AllTeammateWithUnselectable",
        }
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if runtime_units_share_combat_team(owner, unit)
            and runtime_unit_is_target_candidate(
                unit,
                include_unselectable=include_unselectable,
            )
            and (
                alias not in {"AllTeammate", "AllTeammateWithUnselectable"}
                or unit_id != owner_id
            )
        )
    resolved = _resolve_callback_target_id(state, detail, alias, event)
    return (resolved,) if resolved in state.units else ()


def _unit_base_type(unit) -> str:
    for key in ("avatar_base_type", "path", "base_type"):
        value = unit.flags.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _status_dynamic_value(detail: dict[str, JSONValue], key: str) -> float | None:
    values = detail.get("dynamic_values")
    if not isinstance(values, dict):
        return None
    direct = values.get(key)
    if isinstance(direct, (int, float)):
        return float(direct)
    by_name = values.get("__by_name")
    if isinstance(by_name, dict):
        value = by_name.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _unit_relation_id_from_detail(
    detail: dict[str, JSONValue],
    owner_id: str,
    *keys: str,
) -> str:
    source_trace = detail.get("source_trace")
    for container in (detail, source_trace if isinstance(source_trace, dict) else {}):
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value:
                return value
    return owner_id


def _unit_relation_id_from_state(state: BattleState, unit_id: str) -> str:
    unit = state.units.get(unit_id)
    if unit is None:
        return ""
    for key in ("summoner_id", "owner_id"):
        value = unit.flags.get(key)
        if isinstance(value, str) and value in state.units:
            return value
    runtime = state.global_flags.get("summon_runtime")
    if not isinstance(runtime, dict):
        return ""
    for collection_key in ("entities", "servants"):
        collection = runtime.get(collection_key)
        if not isinstance(collection, dict):
            continue
        entry = collection.get(unit_id)
        if not isinstance(entry, dict):
            continue
        owner_id = entry.get("owner_id")
        if isinstance(owner_id, str) and owner_id in state.units:
            return owner_id
    return ""


def _resolve_queue_alias(detail: dict[str, JSONValue], event: GameEvent | None, target_alias: str | None) -> str:
    alias = target_alias or ""
    payload = event.payload if event is not None else {}
    if alias == "ModifierOwnerEntity":
        return str(detail.get("owner_id") or "")
    if alias == "Caster":
        return str(detail.get("caster_id") or "")
    if alias in {"ParamEntity", "CurrentActionTarget", "AbilityTargetEntity"}:
        for key in ("current_hit_target_id", "target_id", "primary_action_target_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return str(event.target_id or "") if event is not None else ""
    if alias == "DamageAttackerEntity":
        for key in ("attacker_id", "actor_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return str(event.source_id or "") if event is not None else ""
    return ""


def _queue_intent_blocked_record(
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    intent: QueueIntentIR,
    reason: str,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="queue_intent_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "callback_id": callback.callback_id,
            "task_id": task.task_id,
            "queue_intent_id": intent.queue_intent_id,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "opcode": intent.opcode,
            "queue_kind": intent.queue_kind,
            "blocking_dependency": reason,
        },
        trace={
            "queue_intent_source": intent.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    ).to_json()


def _action_delay_blocked_record(
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    emission: ActionDelayEmissionIR,
    reason: str,
    *,
    evaluation: NumericEvaluationResult | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="action_delay_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "callback_id": callback.callback_id,
            "task_id": task.task_id,
            "action_delay_emission_id": emission.action_delay_emission_id,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "opcode": emission.opcode,
            "target_alias": emission.target_alias or "",
            "numeric_evaluation": evaluation.to_json() if evaluation else {},
            "blocking_dependency": reason,
        },
        trace={
            "action_delay_source": emission.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    ).to_json()


def _status_damage_blocked_record(
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    emission: StatusDamageEmissionIR,
    reason: str,
    *,
    evaluation: NumericEvaluationResult | None = None,
    evaluation_payload: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="dot_damage_blocked" if emission.damage_formula_family == "dot" else "break_dot_tick_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "callback_id": callback.callback_id,
            "task_id": task.task_id,
            "status_damage_emission_id": emission.status_damage_emission_id,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "attack_type": emission.attack_type,
            "damage_formula_family": emission.damage_formula_family,
            "numeric_evaluation": evaluation_payload or (evaluation.to_json() if evaluation else {}),
            "blocking_dependency": reason,
        },
        trace={
            "status_damage_source": emission.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    ).to_json()


def _callback_blocked_record(
    *,
    reason: str,
    modifier_name: str = "",
    event: str = "",
    trace: dict[str, JSONValue] | None = None,
    callback: StatusCallbackIR | None = None,
    detail: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="status_callback_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "callback_id": callback.callback_id if callback else "",
            "modifier_name": callback.modifier_name if callback else modifier_name,
            "event": callback.event if callback else event,
            "blocking_dependency": reason,
        },
        trace={
            "status_callback_source": callback.source.to_json() if callback else {},
            "status_instance_source": _json_dict(detail.get("source_trace")) if detail else (trace or {}),
        },
    ).to_json()


def _task_blocked_record(
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    reason: str,
    *,
    ok: bool = False,
    condition_result: dict[str, JSONValue] | None = None,
    selected_child_ids: tuple[str, ...] = (),
    mutation_count: int = 0,
    record_count: int = 0,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="status_callback_task_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "ok": ok,
            "callback_id": callback.callback_id,
            "task_id": task.task_id,
            "opcode": task.opcode,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "condition_id": task.condition_id,
            "condition_result": condition_result or {},
            "selected_child_ids": list(selected_child_ids),
            "mutation_count": mutation_count,
            "record_count": record_count,
            "blocking_dependency": reason,
        },
        trace={
            "status_task_source": task.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    ).to_json()


def _evaluate_callback_numeric(
    expression: object,
    state: BattleState,
    detail: dict[str, JSONValue],
    task: StatusCallbackTaskIR,
    rules: RuleBook,
    *,
    template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
) -> NumericEvaluationResult:
    source_trace = {
        "status_task_source": task.source.to_json(),
        "status_instance_source": _json_dict(detail.get("source_trace")),
    }
    context = _condition_context(rules, state, detail, None, template_binding_sources=template_binding_sources)
    return resolve_runtime_numeric_expression(
        cast(JSONValue, expression),
        binding_sources=context.binding_sources,
        source_trace=source_trace,
    )


def _formal_status_transient_provider(
    state: BattleState,
    request: TaskGraphHookRequest,
    scoped_event: GameEvent | None,
    owner_id: str,
) -> TransientConditionOperandProvider | None:
    queue_fact = None
    if scoped_event is not None:
        if scoped_event.event_type == "queue.action.before":
            queue_fact = scoped_event.queue_action_start_fact
        elif scoped_event.event_type in {"queue.action.after", "queue.action.abort"}:
            queue_fact = scoped_event.queue_action_terminal_fact
    queue_provider = (
        QueueEventConditionProvider(
            state,
            request.invocation_id,
            request.graph_node_id,
            scoped_event,
            owner_id,
            queue_fact,
        )
        if queue_fact is not None
        else None
    )
    if request.status_scope is None:
        return queue_provider
    status_provider = TaskGraphStatusConditionProvider(
        state, request.status_scope, request.invocation_id, request.graph_node_id,
        fallback=queue_provider,
    )
    return status_provider


_UNIT_SCOPE_DYNAMIC_KINDS = frozenset({"unit", "combat"})


def _slot_hash(key: object) -> str:
    text = str(key or "")
    if not text:
        return ""
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return text
    from ..dynamic_key_hash import tbgd_dynamic_key_hash

    return str(tbgd_dynamic_key_hash(text))


def _unit_scope_dynamic_hashes(state: BattleState, owner_id: str) -> frozenset[str]:
    """Hashes this owner already holds as committed unit-scope dynamic values."""

    if not owner_id:
        return frozenset()
    store = store_from_state(state)
    entries = store.get("entries") if isinstance(store, dict) else None
    if not isinstance(entries, dict):
        return frozenset()
    hashes: set[str] = set()
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("scope") or entry.get("scope_kind") or "") not in _UNIT_SCOPE_DYNAMIC_KINDS:
            continue
        entry_target = str(entry.get("target_id") or entry.get("owner_id") or "")
        if entry_target != owner_id:
            continue
        hash_key = str(entry.get("hash") or "")
        if hash_key:
            hashes.add(hash_key)
    return frozenset(hashes)


def _without_unit_scoped_slots(
    dynamic_values: object,
    unit_hashes: frozenset[str],
) -> tuple[object, frozenset[str]]:
    """Drop per-instance defaults already superseded by a unit-scope writer.

    A shared ability-level slot must be read from its committed unit-scope
    value; the status instance keeps the declared default only until the first
    writer wins.  The current instance's copy would otherwise shadow (or turn
    ambiguous) the shared value.
    """

    if not isinstance(dynamic_values, dict) or not unit_hashes:
        return dynamic_values, frozenset()
    filtered: dict[str, object] = {}
    dropped: set[str] = set()
    for key, value in dynamic_values.items():
        if str(key) in {
            "__by_hash",
            "__by_name",
            "__evaluations",
            "__definition_bindings",
            "__dynamic_value_requests",
        }:
            continue
        hash_key = _slot_hash(key)
        if hash_key in unit_hashes:
            dropped.add(hash_key)
            continue
        filtered[str(key)] = value
    by_hash = dynamic_values.get("__by_hash")
    if isinstance(by_hash, dict):
        filtered["__by_hash"] = {
            str(key): value
            for key, value in by_hash.items()
            if str(key) not in unit_hashes
        }
    by_name = dynamic_values.get("__by_name")
    if isinstance(by_name, dict):
        filtered["__by_name"] = {
            str(key): value
            for key, value in by_name.items()
            if _slot_hash(key) not in unit_hashes
        }
    for meta in (
        "__evaluations",
        "__definition_bindings",
        "__dynamic_value_requests",
    ):
        if meta in dynamic_values:
            filtered[meta] = dynamic_values[meta]
    return filtered, frozenset(dropped)


def _strip_hashes_from_binding_source(
    source: dict[str, JSONValue],
    hashes: frozenset[str],
) -> dict[str, JSONValue]:
    """Remove slots superseded by a committed owner-scope writer."""

    entries = source.get("entries")
    if not isinstance(entries, dict) or not hashes:
        return source
    kept = {
        key: entry
        for key, entry in entries.items()
        if not (
            isinstance(entry, dict)
            and str(entry.get("hash") or "") in hashes
        )
    }
    if len(kept) == len(entries):
        return source
    by_hash: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for key, entry in sorted(kept.items()):
        if not isinstance(entry, dict):
            continue
        hash_key = entry.get("hash")
        name = entry.get("name")
        if isinstance(hash_key, str) and hash_key:
            by_hash.setdefault(hash_key, []).append(str(key))
        if isinstance(name, str) and name:
            by_name.setdefault(name, []).append(str(key))
    return {
        **{key: value for key, value in source.items()
           if key not in {"entries", "by_hash", "by_name"}},
        "entries": dict(sorted(kept.items())),
        "by_hash": {key: value for key, value in sorted(by_hash.items())},
        "by_name": {key: value for key, value in sorted(by_name.items())},
    }


def _event_damage_identity_ids(
    state: BattleState,
    event: GameEvent | None,
) -> tuple[str | None, str | None]:
    """Damage roles from a damage window's own typed event identities."""

    if event is None or event.event_type not in _DAMAGE_ROLE_EVENT_TYPES:
        return None, None
    # A committed hit's event source is the damage-source owner, not necessarily
    # the attacker, so those windows name only the defender.
    attacker_known = event.event_type not in {"damage.hit", "damage.attacker_hit"}
    return (
        event.source_id if attacker_known and event.source_id in state.units else None,
        event.target_id if event.target_id in state.units else None,
    )


def _event_passive_entity_ids(
    state: BattleState,
    event: GameEvent | None,
) -> tuple[str, ...] | None:
    """The event's second entity from its native producer, or None without one.

    An empty tuple means the producer ran and named no unit (for example a
    defeat without a unit killer); None keeps the target fail-closed.
    """

    if event is None:
        return None
    if event.event_type == "unit.defeated":
        entity_id = event.source_id
    elif type(event.status_lifecycle_fact) is StatusLifecycleFact:
        if not event.status_lifecycle_fact.matches_event(event):
            return None
        entity_id = event.status_lifecycle_fact.caster_id
    elif (
        type(event.status_lifecycle_plan) is StatusLifecyclePlan
        and event.status_lifecycle_plan.target_id == event.target_id
        and isinstance(event.status_lifecycle_plan.existing_detail, dict)
    ):
        entity_id = event.status_lifecycle_plan.existing_detail.get("caster_id")
    else:
        return None
    return (entity_id,) if isinstance(entity_id, str) and entity_id in state.units else ()


def _condition_context(
    rules: RuleBook,
    state: BattleState,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
    *,
    condition: ConditionIR | None = None,
    targets: TargetSystem | None = None,
    selected_target_ids: tuple[str, ...] = (),
    transient_condition_provider: TransientConditionOperandProvider | None = None,
    template_target_ids: tuple[str, ...] | None = None,
    template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    immunity_trigger_event: GameEvent | None = None,
) -> EvaluationContext:
    detail = _current_status_detail(state, detail)
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    if event is not None:
        payload.setdefault("event_id", event.event_id)
        payload.setdefault("event_source_id", event.source_id)
        payload.setdefault("event_type", event.event_type)
        payload.setdefault("event_target_id", event.target_id)
        payload.setdefault("event_window", event.window)
    owner_id = str(detail.get("owner_id") or "")
    caster_id = str(detail.get("caster_id") or owner_id)
    target_id = (
        selected_target_ids[0]
        if selected_target_ids
        else _first_payload_str(
            payload,
            ("current_hit_target_id", "primary_target_id", "target_id"),
        )
        or (str(event.target_id or "") if event is not None else "")
    )
    param_entity_id = _first_payload_str(payload, ("param_entity_id",)) or target_id
    scoped_target_ids = selected_target_ids or (
        (target_id,) if target_id else ()
    )
    queue_fact = (event.queue_action_terminal_fact or event.queue_action_start_fact) if event is not None else None
    if queue_fact is not None:
        param_entity_id = queue_fact.actor_id
        scoped_target_ids = selected_target_ids or queue_fact.target_ids
        target_id = next(iter(scoped_target_ids), "")
    if selected_target_ids:
        payload["retarget_target_ids"] = list(selected_target_ids)
    current_status_binding_source = binding_source_from_status_detail(
        detail,
        _without_unit_scoped_slots(
            detail.get("dynamic_values"),
            _unit_scope_dynamic_hashes(state, owner_id),
        )[0],
    )
    current_status_instance_id = str(detail.get("instance_id") or "")
    current_hashes = tuple(
        str(key)
        for key in (
            current_status_binding_source.get("by_hash", {}).keys()
            if current_status_binding_source is not None
            and isinstance(current_status_binding_source.get("by_hash"), dict)
            else ()
        )
    )
    current_names = tuple(
        str(key)
        for key in (
            current_status_binding_source.get("by_name", {}).keys()
            if current_status_binding_source is not None
            and isinstance(current_status_binding_source.get("by_name"), dict)
            else ()
        )
    )
    callback_binding_sources = _callback_binding_sources(
        rules,
        state,
        detail,
        current_status_binding_source,
        current_status_instance_id,
        current_hashes,
        current_names,
    )
    if condition is not None and condition.payload.get("ContextScope") == "ContextCaster":
        caster_source = binding_source_from_store(
            store_from_state(state), visible_scope={"target_id": caster_id},
        )
        caster_hashes, caster_names = _binding_source_keys(caster_source)
        caster_keys = {*caster_hashes, *caster_names}
        # ContextCaster reads the current unit slot. Status-local initialization
        # only supplies the declared initial value until that slot has a writer.
        callback_binding_sources = (
            caster_source,
            *({**source,
               "by_hash": {key: entries for key, entries in source.get("by_hash", {}).items()
                           if key not in caster_keys},
               "by_name": {key: entries for key, entries in source.get("by_name", {}).items()
                           if key not in caster_keys},
               } for source in callback_binding_sources
              if source.get("source_type") != "dynamic_value_store"),
        )
    callback_binding_sources = with_template_binding_sources(callback_binding_sources, template_binding_sources)
    if condition is not None and targets is not None:
        damage_attacker_id, damage_defender_id = _event_damage_identity_ids(state, event)
        context = targets.condition_evaluation_context(
            state,
            condition,
            context=TargetEvaluationContext(
                caster_id=caster_id,
                effect_owner_id=owner_id or None,
                template_entity_ids=template_target_ids,
                parameter_entity_ids=(
                    (param_entity_id,)
                    if queue_fact is not None or "param_entity_id" in payload
                    else scoped_target_ids
                ),
                parameter_entity_list_ids=(queue_fact.target_ids if queue_fact is not None else scoped_target_ids),
                selected_target_ids=scoped_target_ids,
                current_target_id=target_id or None,
                # Event emitters (setup, timeline, etc.) need not be units.
                event_source_id=(event.source_id if event is not None
                                 and event.source_id in state.units else None),
                event_target_id=(event.target_id if event is not None else None),
                damage_attacker_id=damage_attacker_id,
                damage_defender_id=damage_defender_id,
                passive_entity_ids=_event_passive_entity_ids(state, event),
                turn_owner_id=committed_turn_owner_id(state),
                action_event_id=(event.event_id if event is not None else None),
                action_window=(event.window if event is not None else None),
                admitted_action_target_fact=(
                    event.admitted_action_target_fact if event is not None else None
                ),
                expected_action_window_scope=(
                    event.expected_action_window_scope if event is not None else None
                ),
            ),
            condition_event_payload=payload,
            binding_sources=callback_binding_sources,
            status_detail=detail,
            transient_condition_provider=transient_condition_provider,
        )
        return replace(context, trigger_event=immunity_trigger_event or event)
    return EvaluationContext(
        state=state,
        actor_id=caster_id,
        target_id=target_id or None,
        owner_id=owner_id,
        param_entity_id=param_entity_id or None,
        current_action_target_id=target_id or None,
        status_detail=detail,
        event_payload=payload,
        # Status parameters are source-backed runtime bindings.  Passing the
        # same values through ``dynamic_values`` would make the evaluator label
        # them as unauditable ``explicit_dynamic_values`` and would let that
        # ad-hoc channel shadow the real status-instance source.
        dynamic_values=None,
        binding_sources=callback_binding_sources,
        committed_condition_provider=(
            targets.condition_facts if targets is not None else None
        ),
        trigger_event=immunity_trigger_event or event,
    )


def _effect_context(
    rules: RuleBook,
    state: BattleState,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
    damage_window_ledger: DamageWindowLedger | None = None,
    status_scope: TaskGraphStatusScope | None = None,
    template_target_ids: tuple[str, ...] | None = None,
    template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
) -> EffectExecutionContext:
    detail = _current_status_detail(state, detail)
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    if event is not None:
        payload.setdefault("event_source_id", event.source_id)
        payload.setdefault("event_type", event.event_type)
        payload.setdefault("event_target_id", event.target_id)
        payload.setdefault("event_window", event.window)
    payload.setdefault("status_instance_id", str(detail.get("instance_id") or ""))
    payload.setdefault("status_id", str(detail.get("status_id") or ""))
    payload.setdefault("modifier_name", str(detail.get("modifier_name") or ""))
    payload.setdefault("status_source_id", str(detail.get("source_id") or ""))
    status_source_trace = _json_dict(detail.get("source_trace"))
    payload.setdefault(
        "status_instance_source",
        status_source_trace,
    )
    if event is not None:
        payload.setdefault("event_id", event.event_id)
        payload.setdefault(
            "operation_event_id",
            ":".join(
                (
                    "status_callback_operation",
                    event.event_id,
                    str(detail.get("instance_id") or ""),
                    task.task_id,
                )
            ),
        )
    payload.setdefault("task_id", task.task_id)
    owner_id = str(detail.get("owner_id") or "")
    caster_id = str(detail.get("caster_id") or owner_id)
    target_id = _first_payload_str(payload, ("current_hit_target_id", "primary_target_id", "target_id")) or (
        str(event.target_id or "") if event is not None else ""
    )
    param_entity_id = _first_payload_str(payload, ("param_entity_id",)) or target_id
    queue_fact = (event.queue_action_terminal_fact or event.queue_action_start_fact) if event is not None else None
    if queue_fact is not None:
        param_entity_id = queue_fact.actor_id
        target_id = next(iter(queue_fact.target_ids), "")
    current_status_instance_id = str(detail.get("instance_id") or "")
    current_status_binding_source = binding_source_from_status_detail(
        detail,
        _without_unit_scoped_slots(
            detail.get("dynamic_values"),
            _unit_scope_dynamic_hashes(state, owner_id),
        )[0],
    )
    current_hashes, current_names = _binding_source_keys(
        current_status_binding_source
    )
    callback_binding_sources = _callback_binding_sources(
        rules,
        state,
        detail,
        current_status_binding_source,
        current_status_instance_id,
        current_hashes,
        current_names,
        include_ambient=False,
    )
    return EffectExecutionContext(
        state=state,
        application_instance_id=(
            f"status_event:{event.event_id}:{current_status_instance_id}:{task.task_id}"
            if event is not None and event.event_id else ""
        ),
        param_status_scope=status_scope,
        template_target_ids=template_target_ids,
        caster_id=caster_id,
        # The callback task remains part of the audit trace, but it is not the
        # semantic owner of a child status.  All callbacks emitted by the same
        # status instance must therefore share the parent status identity;
        # otherwise OnStack and a later listener can manufacture two sources
        # for the same equipment effect.
        source_id=(
            f"status_callback_status:{current_status_instance_id}"
            if current_status_instance_id
            else f"status_callback_task:{task.task_id}"
        ),
        owner_id=owner_id,
        param_entity_id=param_entity_id or None,
        current_action_target_id=target_id or None,
        event_payload=payload,
        trigger_event=event,
        heal_event_fact=(
            event.heal_event_fact if event is not None else None
        ),
        death_instance_id=(
            str(event.payload.get("lifecycle_mutation_id") or "")
            if event is not None and event.event_type == "unit.defeated"
            else ""
        ),
        dynamic_values=None,
        binding_sources=with_template_binding_sources(callback_binding_sources, template_binding_sources),
        include_ambient_status_bindings=False,
        status_lifecycle_plan=(
            event.status_lifecycle_plan
            if event is not None and event.event_type == "status.lifecycle"
            and event.window == "OnDestroy" else None
        ),
        shadowed_status_instance_ids=(
            (current_status_instance_id,) if current_status_instance_id else ()
        ),
        damage_window_ledger=damage_window_ledger,
        admitted_action_target_fact=(
            event.admitted_action_target_fact if event is not None else None
        ),
        expected_action_window_scope=(
            event.expected_action_window_scope if event is not None else None
        ),
        shield_exhaustion_fact=(
            event.shield_exhaustion_fact if event is not None else None
        ),
        status_lifecycle_fact=(
            event.status_lifecycle_fact
            if event is not None and event.event_type == "status.lifecycle"
            else None
        ),
    )


def _callback_binding_sources(
    rules: RuleBook,
    state: BattleState,
    detail: dict[str, JSONValue],
    current_status_binding_source: dict[str, JSONValue] | None,
    current_status_instance_id: str,
    current_hashes: tuple[str, ...],
    current_names: tuple[str, ...],
    *,
    include_ambient: bool = True,
) -> tuple[dict[str, JSONValue], ...]:
    """Compose callback bindings without allowing outer-action ownership to leak in."""

    caster_id = str(detail.get("caster_id") or detail.get("owner_id") or "")
    declared_source = None
    if caster_id:
        declared_source = character_declared_dynamic_binding_source(
            rules,
            state,
            caster_id,
            excluded_hashes=current_hashes,
        ) or servant_declared_dynamic_binding_source(
            rules,
            state,
            caster_id,
            excluded_hashes=current_hashes,
        )
    character_sources = character_skill_param_binding_sources(
        rules,
        state,
        (caster_id,) if caster_id else (),
        excluded_hashes=current_hashes,
        excluded_names=current_names,
        include_unowned_rank_defaults=True,
    )
    declared_hashes, declared_names = character_skill_param_declared_keys(
        rules,
        state,
        caster_id,
    ) if caster_id else ((), ())
    caster_character_hashes = tuple(
        str(key)
        for source in character_sources
        for key in (
            source.get("by_hash", {}).keys()
            if isinstance(source.get("by_hash"), dict)
            else ()
        )
    )
    caster_character_names = tuple(
        str(key)
        for source in character_sources
        for key in (
            source.get("by_name", {}).keys()
            if isinstance(source.get("by_name"), dict)
            else ()
        )
    )
    master_character_sources: tuple[dict[str, JSONValue], ...] = ()
    caster_unit = state.units.get(caster_id) if caster_id else None
    master_id = (
        str(caster_unit.flags.get("owner_id") or "")
        if caster_unit is not None and isinstance(caster_unit.flags, dict)
        else ""
    )
    if master_id and master_id != caster_id:
        # A servant's callbacks may read the master's declared skill-param and
        # skill-rank slots (both configs declare the same hashes; only the
        # character card owns the unowned-rank zero baseline).
        master_character_sources = character_skill_param_binding_sources(
            rules,
            state,
            (master_id,),
            excluded_hashes=(*current_hashes, *caster_character_hashes),
            excluded_names=(*current_names, *caster_character_names),
            include_unowned_rank_defaults=True,
        )
    related_units = {
        str(detail.get("target_id") or ""),
        str(detail.get("owner_id") or ""),
        str(detail.get("primary_target_id") or ""),
        str(detail.get("current_hit_target_id") or ""),
    } - {caster_id, ""}
    caster_unit = state.units.get(caster_id)
    if caster_unit is not None:
        caster_owner_id = caster_unit.flags.get("owner_id")
        if isinstance(caster_owner_id, str) and caster_owner_id:
            related_units.add(caster_owner_id)
    projected_sources: list[dict[str, JSONValue]] = []
    projected_hashes: list[str] = []
    for related_unit_id in sorted(related_units | {caster_id}):
        if not related_unit_id:
            continue
        projected = character_declared_dynamic_binding_source(
            rules,
            state,
            related_unit_id,
            excluded_hashes=current_hashes,
        )
        if projected is None:
            projected = servant_declared_dynamic_binding_source_for_owner(
                rules,
                state,
                related_unit_id,
                excluded_hashes=current_hashes,
            )
        if projected is None:
            continue
        projected_sources.append(projected)
        projected_hashes.extend(
            str(key)
            for key in (
                projected.get("by_hash", {}).keys()
                if isinstance(projected.get("by_hash"), dict)
                else ()
            )
        )
    if projected_hashes:
        # The projected target-unit baseline owns those declared slots; the
        # caster-side declared source must not bind them a second time.
        declared_source = character_declared_dynamic_binding_source(
            rules,
            state,
            caster_id,
            excluded_hashes=(*current_hashes, *projected_hashes),
        ) or servant_declared_dynamic_binding_source(
            rules,
            state,
            caster_id,
            excluded_hashes=(*current_hashes, *projected_hashes),
        )
    declared_sources = (
        ([declared_source] if declared_source is not None else [])
        + projected_sources
    )
    explicit_sources = (
        *((current_status_binding_source,) if current_status_binding_source is not None else ()),
        *declared_sources,
        *character_sources,
        *master_character_sources,
    )
    if not include_ambient:
        return explicit_sources
    shadowed_hashes = tuple(
        dict.fromkeys(
            (*current_hashes, *declared_hashes)
            + tuple(
                str(key)
                for source in explicit_sources
                for key in (
                    source.get("by_hash", {}).keys()
                    if isinstance(source.get("by_hash"), dict)
                    else ()
                )
            )
        )
    )
    shadowed_names = tuple(
        dict.fromkeys(
            (*current_names, *declared_names)
            + tuple(
                str(key)
                for source in explicit_sources
                for key in (
                    source.get("by_name", {}).keys()
                    if isinstance(source.get("by_name"), dict)
                    else ()
                )
            )
        )
    )
    owner_id = str(detail.get("owner_id") or "")
    return (
        *explicit_sources,
        binding_source_from_store_for_units(
            store_from_state(state),
            tuple(unit_id for unit_id in (caster_id, owner_id) if unit_id),
            excluded_status_instance_ids=(current_status_instance_id,),
            excluded_hashes=shadowed_hashes,
            excluded_names=shadowed_names,
            excluded_scopes=("character_skill_param", "character_rank_param"),
        ),
    )


def _binding_source_keys(
    source: dict[str, JSONValue] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(
            str(key)
            for key in (
                source.get("by_hash", {}).keys()
                if source is not None and isinstance(source.get("by_hash"), dict)
                else ()
            )
        ),
        tuple(
            str(key)
            for key in (
                source.get("by_name", {}).keys()
                if source is not None and isinstance(source.get("by_name"), dict)
                else ()
            )
        ),
    )
def _current_status_detail(
    state: BattleState,
    detail: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    owner_id = str(detail.get("owner_id") or "")
    instance_id = str(detail.get("instance_id") or "")
    unit = state.units.get(owner_id)
    if unit is None or not instance_id:
        return detail
    current_details = unit.flags.get("status_details", ())
    if not isinstance(current_details, (list, tuple)):
        return detail
    current = next(
        (
            item
            for item in current_details
            if isinstance(item, dict) and item.get("instance_id") == instance_id
        ),
        None,
    )
    if current is not None:
        return current
    # A destroyed instance no longer contributes properties, but its callback
    # can still read the local variables it just wrote to the scoped store.
    values = dict(detail.get("dynamic_values") or {})
    by_name = dict(values.get("__by_name") or {})
    by_hash = dict(values.get("__by_hash") or {})
    for entry in store_from_state(state)["entries"].values():
        if entry.get("scope_kind") != "status" or entry.get("status_instance_id") != instance_id:
            continue
        for key, index in ((entry.get("name"), by_name), (entry.get("hash"), by_hash)):
            if key:
                values[key] = index[key] = entry["value"]
    return {**detail, "dynamic_values": {**values, "__by_name": by_name, "__by_hash": by_hash}}


def _definition_dynamic_hash_aliases(
    detail: dict[str, JSONValue],
    *,
    dynamic_key: str,
    source_task_id: str,
) -> tuple[dict[str, JSONValue], ...]:
    dynamic_values = detail.get("dynamic_values")
    definition_bindings = (
        dynamic_values.get("__definition_bindings")
        if isinstance(dynamic_values, dict)
        else None
    )
    by_hash = (
        definition_bindings.get("by_hash")
        if isinstance(definition_bindings, dict)
        else None
    )
    by_name = (
        definition_bindings.get("by_name")
        if isinstance(definition_bindings, dict)
        else None
    )
    named_binding = (
        by_name.get(dynamic_key) if isinstance(by_name, dict) else None
    )
    named_hashes = (
        named_binding.get("hashes")
        if isinstance(named_binding, dict)
        else None
    )
    if isinstance(named_hashes, (list, tuple)) and named_hashes:
        return tuple(
            {
                "hash": str(hash_key),
                "dynamic_key": dynamic_key,
                "source_kind": "document_unique_dynamic_key_hash_evidence",
                "source_task_id": source_task_id,
                "definition_binding": named_binding,
            }
            for hash_key in named_hashes
            if isinstance(hash_key, (str, int))
        )
    if not isinstance(by_hash, dict):
        return ()
    candidates: list[tuple[str, dict[str, JSONValue]]] = []
    for hash_key, binding in by_hash.items():
        if not isinstance(binding, dict):
            continue
        read_info = binding.get("read_info")
        if (
            isinstance(read_info, dict)
            and str(read_info.get("Type") or "") == "None"
        ):
            candidates.append((str(hash_key), binding))
    if len(candidates) != 1:
        return ()
    hash_key, binding = candidates[0]
    return (
        {
            "hash": hash_key,
            "dynamic_key": dynamic_key,
            "source_kind": "unique_modifier_internal_dynamic_slot",
            "source_task_id": source_task_id,
            "definition_binding": binding,
        },
    )


def _dynamic_hash_aliases_for_context_task(
    detail: dict[str, JSONValue],
    *,
    task: StatusCallbackTaskIR,
    tasks: dict[str, StatusCallbackTaskIR],
) -> tuple[dict[str, JSONValue], ...]:
    """Bind a callback-local dynamic name to its exact definition hash.

    Some TBGD modifier definitions expose several ``Type=None`` hash slots
    without a named table.  In those records the task graph itself carries
    the lossless relationship: every writer of the same DynamicKey refers to
    that slot in its typed numeric expression.  We admit the relationship
    only when the graph and definition intersect in exactly one hash.
    """

    payload = task.task_payload
    dynamic_key = payload.get("DynamicKey") or payload.get("ToDynamicKey")
    if not isinstance(dynamic_key, str) or not dynamic_key:
        return ()
    direct = _definition_dynamic_hash_aliases(
        detail,
        dynamic_key=dynamic_key,
        source_task_id=task.task_id,
    )
    if direct:
        return direct

    dynamic_values = detail.get("dynamic_values")
    definition_bindings = (
        dynamic_values.get("__definition_bindings")
        if isinstance(dynamic_values, dict)
        else None
    )
    definition_by_hash = (
        definition_bindings.get("by_hash")
        if isinstance(definition_bindings, dict)
        else None
    )
    callback_by_hash = (
        definition_bindings.get("callback_by_hash")
        if isinstance(definition_bindings, dict)
        else None
    )
    if not isinstance(definition_by_hash, dict) and not isinstance(
        callback_by_hash,
        dict,
    ):
        return ()

    referenced_hashes: set[str] = set()
    contributing_task_ids: list[str] = []
    for candidate in tasks.values():
        candidate_payload = candidate.task_payload
        candidate_key = candidate_payload.get("DynamicKey") or candidate_payload.get(
            "ToDynamicKey"
        )
        if candidate_key != dynamic_key:
            continue
        candidate_hashes = _numeric_hashes_in_payload(candidate_payload)
        if candidate_hashes:
            contributing_task_ids.append(candidate.task_id)
            referenced_hashes.update(candidate_hashes)

    candidates: dict[str, dict[str, JSONValue]] = {}
    for hash_key, binding in (
        definition_by_hash.items()
        if isinstance(definition_by_hash, dict)
        else ()
    ):
        if str(hash_key) not in referenced_hashes or not isinstance(binding, dict):
            continue
        read_info = binding.get("read_info")
        if (
            isinstance(read_info, dict)
            and str(read_info.get("Type") or "") == "None"
        ):
            candidates[str(hash_key)] = binding
    resolved_hashes = {
        str(hash_key)
        for hash_key in (
            dynamic_values.get("__by_hash", {}).keys()
            if isinstance(dynamic_values, dict)
            and isinstance(dynamic_values.get("__by_hash"), dict)
            else ()
        )
    }
    for hash_key, binding in (
        callback_by_hash.items()
        if isinstance(callback_by_hash, dict)
        else ()
    ):
        if (
            str(hash_key) in referenced_hashes
            and str(hash_key) not in resolved_hashes
            and isinstance(binding, dict)
        ):
            candidates[str(hash_key)] = binding
    used_unique_unresolved_fallback = False
    if not candidates and isinstance(callback_by_hash, dict):
        unresolved_callback_hashes = {
            str(hash_key): binding
            for hash_key, binding in callback_by_hash.items()
            if str(hash_key) not in resolved_hashes and isinstance(binding, dict)
        }
        if len(unresolved_callback_hashes) == 1:
            candidates.update(unresolved_callback_hashes)
            used_unique_unresolved_fallback = True
    if len(candidates) != 1:
        return ()
    hash_key, binding = next(iter(candidates.items()))
    source_kind = (
        "unique_unresolved_modifier_callback_dynamic_slot"
        if used_unique_unresolved_fallback
        else "callback_task_graph_unique_dynamic_slot"
    )
    return (
        {
            "hash": hash_key,
            "dynamic_key": dynamic_key,
            "source_kind": source_kind,
            "source_task_id": task.task_id,
            "contributing_task_ids": sorted(contributing_task_ids),
            "definition_binding": binding,
        },
    )


def _numeric_hashes_in_payload(value: JSONValue) -> set[str]:
    hashes = {
        str(hash_key)
        for hash_key in numeric_dynamic_hashes(value)
        if isinstance(hash_key, (str, int)) and not isinstance(hash_key, bool)
    }
    if isinstance(value, dict):
        for child in value.values():
            hashes.update(_numeric_hashes_in_payload(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            hashes.update(_numeric_hashes_in_payload(child))
    return hashes


def _first_payload_str(payload: dict[str, JSONValue], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _list_alias_targets(
    state: BattleState,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
    alias: str,
) -> tuple[str, ...]:
    payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
    if alias == "ParamEntitySkillTargetEntityList":
        for key in ("selected_target_ids", "target_ids", "skill_target_ids", "requested_target_ids"):
            value = payload.get(key)
            if isinstance(value, (list, tuple)):
                result = tuple(str(item) for item in value if isinstance(item, str) and item in state.units)
                if result:
                    return result
        fallback = _first_payload_str(payload, ("current_hit_target_id", "primary_target_id", "target_id"))
        return (fallback,) if fallback and fallback in state.units else ()
    if alias == "AllEnemyWithUnSelectable":
        return _callback_target_group(state, detail, event, alias)
    return ()


def _value_field(value: object) -> object:
    if isinstance(value, dict) and "Value" in value:
        return value.get("Value")
    return value


def _is_runtime_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _status_callback_envelope(
    callback: StatusCallbackIR,
    detail: dict[str, JSONValue],
    trigger_event: GameEvent | None,
) -> tuple[dict[str, JSONValue], GameEvent]:
    trigger_event_id = str(trigger_event.to_json()["event_id"]) if trigger_event is not None else ""
    record = SettlementRecord(
        record_type="status_callback",
        source="status_callback_system",
        process_only=True,
        payload={
            "callback_id": callback.callback_id,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "task_ids": list(callback.task_ids),
        },
        trace={
            "callback_source": callback.source.to_json(),
            "status_source": _json_dict(detail.get("source_trace")),
            "trigger_event_id": trigger_event_id,
        },
    ).to_json()
    event = GameEvent(
        "status.callback",
        source_id=str(detail.get("caster_id") or ""),
        target_id=str(detail.get("owner_id") or ""),
        window=callback.event,
        process_only=True,
        payload={
            "callback_id": callback.callback_id,
            "modifier_name": callback.modifier_name,
            "status_instance_id": str(detail.get("instance_id") or ""),
            "trigger_event_id": trigger_event_id,
        },
    )
    return record, event


def _status_task_graph_settlement_records(
    records: tuple[dict[str, JSONValue], ...],
) -> tuple[TaskGraphSettlementRecord, ...]:
    required = {
        "record_type",
        "source",
        "mutation_id",
        "process_only",
        "payload",
        "trace",
    }
    converted: list[TaskGraphSettlementRecord] = []
    for record in records:
        if type(record) is not dict or set(record) != required:
            raise ValueError("status callback settlement record shape is invalid")
        payload = record.get("payload")
        trace = record.get("trace")
        if not isinstance(payload, Mapping) or not isinstance(trace, Mapping):
            raise TypeError("status callback settlement payload is invalid")
        converted.append(
            TaskGraphSettlementRecord(
                record_type=cast(str, record["record_type"]),
                source=cast(str, record["source"]),
                mutation_id=cast(str | None, record["mutation_id"]),
                process_only=cast(bool, record["process_only"]),
                payload=dict(payload),
                trace=dict(trace),
            )
        )
    return tuple(converted)


def _formal_status_scope_event(
    request: TaskGraphHookRequest,
    trigger_event: GameEvent | None,
) -> GameEvent | None:
    trigger_event = _formal_status_parameter_event(request, trigger_event)
    if not request.target_ids:
        return trigger_event
    event = _retarget_event(trigger_event, request.target_ids[0])
    payload = dict(event.payload)
    payload["retarget_target_ids"] = list(request.target_ids)
    iteration = request.iteration_index if request.iteration_index is not None else "root"
    return _callback_scoped_event(
        replace(event, payload=payload),
        callback_scope=f"{request.graph_node_id}:targets:{iteration}",
        decision_index=0,
    )


def _formal_status_scoped_events(
    request: TaskGraphHookRequest,
    trigger_event: GameEvent | None,
) -> tuple[GameEvent | None, ...]:
    trigger_event = _formal_status_parameter_event(request, trigger_event)
    if not request.target_ids:
        return (trigger_event,)
    iteration = request.iteration_index if request.iteration_index is not None else "root"
    return tuple(
        _callback_scoped_event(
            _retarget_event(trigger_event, target_id),
            callback_scope=f"{request.graph_node_id}:target:{iteration}",
            decision_index=index,
        )
        for index, target_id in enumerate(request.target_ids)
    )


def _formal_status_parameter_event(
    request: TaskGraphHookRequest, trigger_event: GameEvent | None,
) -> GameEvent | None:
    if request.status_scope is None:
        return trigger_event
    return _callback_scoped_event(trigger_event,
        callback_scope=f"{request.graph_node_id}:modifier:{request.status_scope.owner_id}:{request.status_scope.instance_id}",
        decision_index=0)


def _trigger_ids_for_event(detail: dict[str, JSONValue], event: str) -> tuple[str, ...] | None:
    mapping = detail.get("trigger_ids_by_event")
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(event)
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _status_damage_window_event(
    state: BattleState, packet: DamagePacket, event_type: str, custom_name: str, depth: int,
    *, hit_all_callback_stack: bool = False,
) -> GameEvent:
    """Produce a hit window from the formal packet, without creating an attack."""
    frame = packet.source_frame
    if type(frame) is not DamageSourceFrame:
        raise ValueError("status_damage_window_source_frame_missing")
    payload = {
        "actor_id": packet.attacker_id, "attacker_id": packet.attacker_id,
        "damage_attacker_id": packet.attacker_id, "param_entity_id": packet.target_id,
        "target_id": packet.target_id, "current_hit_target_id": packet.target_id,
        "primary_target_id": packet.target_id, "selected_target_ids": [packet.target_id],
        "attack_type": packet.attack_type, "damage_formula_family": packet.damage_formula_family,
        "damage_custom_name": custom_name, "damage_sequence_source_task_id": packet.source_task_id,
        "source_trace": packet.source_trace, "mutation_event_depth": depth,
    }
    if hit_all_callback_stack:
        payload["hit_all_callback_stack"] = True
    return with_hit_window_invocation_fact(
        GameEvent(event_type, source_id=packet.attacker_id, target_id=packet.target_id,
            event_id=f"event:{state.event_index}:{event_type}:{frame.sequence_id}:{packet.target_id}",
            window=event_type, process_only=True, payload=payload),
        sequence_id=packet.source_task_id or "",
        in_callback_stack=hit_all_callback_stack,
    )


def _stage_damage_window_ledger(
    ledger: DamageWindowLedger | None,
) -> DamageWindowLedger | None:
    if ledger is None:
        return None
    staged = DamageWindowLedger()
    staged.defeated_targets = {
        target_id: dict(record)
        for target_id, record in ledger.defeated_targets.items()
    }
    return staged


def _commit_damage_window_ledger(
    ledger: DamageWindowLedger | None,
    staged: DamageWindowLedger | None,
) -> None:
    if ledger is not None and staged is not None:
        ledger.defeated_targets = {
            target_id: dict(record)
            for target_id, record in staged.defeated_targets.items()
        }


def _selected_callback_blocked(
    state: BattleState,
    callback_id: str,
    reason: str,
) -> StatusCallbackExecutionResult:
    return StatusCallbackExecutionResult(
        ok=False,
        after_state=state,
        records=(
            SettlementRecord(
                record_type="status_callback_blocked",
                source="status_callback_system",
                process_only=True,
                payload={
                    "callback_id": callback_id,
                    "reason": reason,
                },
                trace={},
            ).to_json(),
        ),
        errors=(reason,),
        node_results=(
            ExecutionNodeResult(
                node_kind="status_callback",
                node_id=callback_id,
                status="blocked",
                reason_code=reason,
            ),
        ),
    )


def _json_dict(value: object) -> dict[str, JSONValue]:
    return value if isinstance(value, dict) else {}


def _json_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
