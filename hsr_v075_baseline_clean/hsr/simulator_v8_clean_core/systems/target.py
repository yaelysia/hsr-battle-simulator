from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from ..core.model import BattleState, JSONValue, RNGEvent, TargetResolution
from ..rules.evaluator import EvaluationContext, NumericEvaluationContext, RuleEvaluator
from ..rules.ir import ConditionIR, IRSource, TargetExpressionIR
from .rng import RNGOutcome, RNGRequest, resolve_rng_request, rng_choices_from_payload, rng_mode_from_payload
from .unit_relation import is_dark_team, is_light_team, is_opposing_combat_team, is_same_combat_team
from .unit_lifecycle import UnitLifecycleSystem


@dataclass(frozen=True)
class TargetingResult:
    resolution: TargetResolution
    ok: bool
    errors: tuple[str, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()


@dataclass(frozen=True)
class BounceTargetResult:
    ok: bool
    target_id: str = ""
    rng_event: RNGEvent | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True)
class TargetPolicy:
    policy_id: str = "enemy"
    allow_enemy: bool = True
    allow_ally: bool = False
    allow_self: bool = False
    allow_defeated: bool = False
    target_mode: str = "single"
    selection_mode: str = "explicit"
    bounce_policy: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetEnumerationResult:
    ok: bool
    selectable_target_ids: tuple[str, ...] = ()
    auto_target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    policy: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "selectable_target_ids": list(self.selectable_target_ids),
            "auto_target_ids": list(self.auto_target_ids),
            "blocked_reason": self.blocked_reason,
            "policy": self.policy,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class TargetExpressionResult:
    ok: bool
    target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    expression_id: str = ""
    expression_kind: str = ""
    alias: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    rng_events: tuple[RNGEvent, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "target_ids": list(self.target_ids),
            "blocked_reason": self.blocked_reason,
            "expression_id": self.expression_id,
            "expression_kind": self.expression_kind,
            "alias": self.alias,
            "metadata": self.metadata,
            "rng_events": [event.to_json() for event in self.rng_events],
        }


class TargetSystem:
    def __init__(self) -> None:
        self.lifecycle = UnitLifecycleSystem()

    def resolve_target_expression(
        self,
        state: BattleState,
        expression: TargetExpressionIR,
        *,
        caster_id: str,
        owner_id: str | None = None,
        param_entity_id: str | None = None,
        current_action_target_id: str | None = None,
        target_resolution: TargetResolution | None = None,
        event_payload: dict[str, JSONValue] | None = None,
        dynamic_values: dict[str, float] | None = None,
        binding_sources: tuple[dict[str, JSONValue], ...] = (),
    ) -> TargetExpressionResult:
        metadata: dict[str, JSONValue] = {
            "target_expression": expression.to_json(),
            "caster_id": caster_id,
            "owner_id": owner_id,
            "param_entity_id": param_entity_id,
            "current_action_target_id": current_action_target_id,
            "target_resolution": target_resolution.to_json() if target_resolution else None,
            "event_payload": event_payload or {},
        }
        if expression.coverage_status != "executable":
            reason = expression.blocked_reason or f"target_expression_not_executable:{expression.coverage_status}"
            return TargetExpressionResult(
                ok=False,
                blocked_reason=reason,
                expression_id=expression.target_expression_id,
                expression_kind=expression.expression_kind,
                alias=expression.alias,
                metadata=metadata,
            )
        result = _resolve_expression_payload(
            state,
            expression.payload.get("raw") if isinstance(expression.payload, dict) else None,
            expression_kind=expression.expression_kind,
            alias=expression.alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload or {},
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
        )
        metadata["resolution_steps"] = result.steps
        if result.blocked_reason:
            return TargetExpressionResult(
                ok=False,
                blocked_reason=result.blocked_reason,
                expression_id=expression.target_expression_id,
                expression_kind=expression.expression_kind,
                alias=expression.alias,
                metadata=metadata,
                rng_events=result.rng_events,
            )
        return TargetExpressionResult(
            ok=True,
            target_ids=result.target_ids,
            expression_id=expression.target_expression_id,
            expression_kind=expression.expression_kind,
            alias=expression.alias,
            metadata=metadata,
            rng_events=result.rng_events,
        )

    def enumerate_action_targets(
        self,
        state: BattleState,
        actor_id: str,
        policy: TargetPolicy | None = None,
    ) -> TargetEnumerationResult:
        policy = policy or TargetPolicy()
        actor = state.units.get(actor_id)
        policy_payload = _policy_metadata(policy)
        if actor is None:
            return TargetEnumerationResult(
                ok=False,
                blocked_reason="unknown_actor",
                policy=policy_payload,
                metadata={"actor_id": actor_id},
            )
        blocked_reason = _target_mode_blocked_reason(policy)
        if blocked_reason:
            return TargetEnumerationResult(
                ok=False,
                blocked_reason=blocked_reason,
                policy=policy_payload,
                metadata={"actor_id": actor_id},
            )
        if policy.target_mode == "aoe":
            auto_targets = self.enemies_of(state, actor_id, allow_defeated=policy.allow_defeated)
            if not auto_targets:
                return TargetEnumerationResult(
                    ok=False,
                    blocked_reason="target_candidates_empty",
                    policy=policy_payload,
                    metadata={"actor_id": actor_id, "target_mode": policy.target_mode},
                )
            return TargetEnumerationResult(
                ok=True,
                auto_target_ids=auto_targets,
                policy=policy_payload,
                metadata={"actor_id": actor_id, "target_mode": policy.target_mode},
            )
        if policy.target_mode in {"single", "blast", "bounce", "self_or_team"}:
            selectable = tuple(
                unit_id
                for unit_id, unit in sorted(state.units.items())
                if self.lifecycle.can_target(state, unit_id, allow_defeated=policy.allow_defeated)[0]
                and _policy_allows(actor_id, actor, unit_id, unit, policy)
            )
            if not selectable:
                return TargetEnumerationResult(
                    ok=False,
                    blocked_reason="target_candidates_empty",
                    policy=policy_payload,
                    metadata={"actor_id": actor_id, "target_mode": policy.target_mode},
                )
            return TargetEnumerationResult(
                ok=True,
                selectable_target_ids=selectable,
                policy=policy_payload,
                metadata={"actor_id": actor_id, "target_mode": policy.target_mode},
            )
        return TargetEnumerationResult(
            ok=False,
            blocked_reason=f"unsupported_target_mode:{policy.target_mode}",
            policy=policy_payload,
            metadata={"actor_id": actor_id, "target_mode": policy.target_mode},
        )

    def resolve_action_targets(
        self,
        state: BattleState,
        actor_id: str,
        target_ids: tuple[str, ...],
        policy: TargetPolicy | None = None,
    ) -> TargetingResult:
        policy = policy or TargetPolicy()
        if policy.target_mode == "aoe":
            target_ids = self.enemies_of(state, actor_id, allow_defeated=policy.allow_defeated)
        explicit = self.resolve_explicit_targets(state, actor_id, target_ids, policy=policy)
        if not explicit.ok:
            return explicit
        blocked_reason = _target_mode_blocked_reason(policy)
        if blocked_reason:
            resolution = TargetResolution(
                requested=explicit.resolution.requested,
                legal=explicit.resolution.legal,
                selected=(),
                rejected=explicit.resolution.legal,
                reason=blocked_reason,
                source="target_system",
                metadata={
                    **explicit.resolution.metadata,
                    "target_groups": {},
                    "blocked_reason": blocked_reason,
                },
            )
            return TargetingResult(resolution=resolution, ok=False, errors=(blocked_reason,))
        target_groups = _target_groups(state, actor_id, explicit.resolution.legal, policy)
        selected = tuple(
            dict.fromkeys(
                target_id
                for group in target_groups.values()
                for target_id in group
            )
        )
        resolution = TargetResolution(
            requested=explicit.resolution.requested,
            legal=explicit.resolution.legal,
            selected=selected,
            rejected=explicit.resolution.rejected,
            reason="action_targets_resolved",
            source="target_system",
            metadata={
                **explicit.resolution.metadata,
                "target_groups": {key: list(value) for key, value in sorted(target_groups.items())},
            },
        )
        return TargetingResult(resolution=resolution, ok=True)

    def resolve_explicit_targets(
        self,
        state: BattleState,
        actor_id: str,
        target_ids: tuple[str, ...],
        policy: TargetPolicy | None = None,
    ) -> TargetingResult:
        policy = policy or TargetPolicy()
        errors: list[str] = []
        legal: list[str] = []
        rejected: list[str] = []
        metadata: dict[str, JSONValue] = {"policy": _policy_metadata(policy)}

        actor = state.units.get(actor_id)
        if actor is None:
            errors.append(f"unknown actor_id: {actor_id}")
            rejected.extend(target_ids)
            return TargetingResult(
                resolution=TargetResolution(
                    requested=target_ids,
                    legal=(),
                    selected=(),
                    rejected=tuple(rejected),
                    reason="unknown_actor",
                    source="target_system",
                    metadata={"errors": list(errors)},
                ),
                ok=False,
                errors=tuple(errors),
            )

        for target_id in target_ids:
            target = state.units.get(target_id)
            if target is None:
                reason = f"unknown:{target_id}"
                errors.append(reason)
                rejected.append(target_id)
                continue
            target_ok, lifecycle_reason = self.lifecycle.can_target(
                state,
                target_id,
                allow_defeated=policy.allow_defeated,
            )
            if not target_ok:
                reason = f"{lifecycle_reason}:{target_id}"
                errors.append(reason)
                rejected.append(target_id)
                continue
            if not _policy_allows(actor_id, actor, target_id, target, policy):
                reason = f"policy_rejected:{policy.policy_id}:{target_id}"
                errors.append(reason)
                rejected.append(target_id)
                continue
            legal.append(target_id)

        ok = not errors
        if errors:
            metadata["errors"] = list(errors)
        return TargetingResult(
            resolution=TargetResolution(
                requested=target_ids,
                legal=tuple(legal),
                selected=tuple(legal),
                rejected=tuple(rejected),
                reason="explicit_targets_resolved" if ok else "explicit_targets_rejected",
                source="target_system",
                metadata=metadata,
            ),
            ok=ok,
            errors=tuple(errors),
        )

    def enemies_of(self, state: BattleState, actor_id: str, *, allow_defeated: bool = False) -> tuple[str, ...]:
        actor = state.units[actor_id]
        return tuple(
            unit_id
            for unit_id, unit in state.units.items()
            if is_opposing_combat_team(actor, unit) and self.lifecycle.can_target(state, unit_id, allow_defeated=allow_defeated)[0]
        )

    def resolve_bounce_hit_target(
        self,
        state: BattleState,
        *,
        actor_id: str,
        primary_target_id: str,
        bounce_policy: dict[str, JSONValue],
        hit_index: int,
        previous_hit_targets: tuple[str, ...],
        action_id: str,
        action_level: int,
        event_payload: dict[str, JSONValue] | None = None,
    ) -> BounceTargetResult:
        actor = state.units.get(actor_id)
        if actor is None:
            return BounceTargetResult(ok=False, error="unknown_actor")
        if str(bounce_policy.get("coverage_status") or "") != "executable":
            return BounceTargetResult(ok=False, error="bounce_policy_not_executable", metadata={"bounce_policy": bounce_policy})
        live_candidates = tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if is_opposing_combat_team(actor, unit) and self.lifecycle.can_target(state, unit_id)[0]
        )
        all_candidates = tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if is_opposing_combat_team(actor, unit)
        )
        selection_strategy = str(bounce_policy.get("selection_strategy") or "")
        candidate_pool = live_candidates
        candidate_pool_reason = "live_targets"
        if live_candidates and selection_strategy == "prefer_unhit_then_random":
            unhit = tuple(unit_id for unit_id in live_candidates if unit_id not in set(previous_hit_targets))
            if unhit:
                candidate_pool = unhit
                candidate_pool_reason = "live_unhit_targets"
        if not candidate_pool:
            if not bool(bounce_policy.get("continue_on_all_defeated")):
                return BounceTargetResult(
                    ok=False,
                    error="bounce_no_live_target_and_continuation_not_admitted",
                    metadata={"bounce_policy": bounce_policy},
                )
            candidate_pool = all_candidates or (primary_target_id,)
            candidate_pool_reason = "all_targets_defeated_continue_sequence"
        event_id = f"rng:{state.event_index}:{actor_id}:{action_id}:{action_level}:bounce:{hit_index}"
        outcomes = tuple(
            RNGOutcome(
                outcome_id=str(unit_id),
                payload={
                    "selected_target_id": unit_id,
                    "selected_index": index,
                    "candidate_pool": list(candidate_pool),
                    "candidate_pool_reason": candidate_pool_reason,
                    "hit_index": hit_index,
                    "selection_strategy": selection_strategy,
                    "live_target_priority": bool(bounce_policy.get("live_target_priority")),
                    "continue_on_all_defeated": bool(bounce_policy.get("continue_on_all_defeated")),
                    "previous_hit_targets": list(previous_hit_targets),
                    "bounce_policy_id": str(bounce_policy.get("bounce_policy_id") or ""),
                    "value": unit_id,
                },
                weight=1.0,
            )
            for index, unit_id in enumerate(candidate_pool)
        )
        request = RNGRequest(
            rng_type="bounce_target",
            purpose="bounce_target",
            event_id=event_id,
            choice_key=f"bounce:{actor_id}:{action_id}:{action_level}:{hit_index}",
            source="target_system",
            before_state=state.rng_state,
            decision_kind="choice",
            outcomes=outcomes,
            source_trace=bounce_policy.get("source", {}) if isinstance(bounce_policy.get("source"), dict) else {},
            metadata={
                "actor_id": actor_id,
                "action_id": action_id,
                "action_level": action_level,
                "primary_target_id": primary_target_id,
                "candidate_pool": list(candidate_pool),
                "candidate_pool_reason": candidate_pool_reason,
                "previous_hit_targets": list(previous_hit_targets),
            },
            invalid_choice_reason="bounce_target_choice_invalid",
        )
        resolution = resolve_rng_request(
            request,
            rng_choices=rng_choices_from_payload(event_payload),
            rng_mode=rng_mode_from_payload(event_payload, default="deterministic_seed"),
        )
        if not resolution.ok or resolution.selected_outcome is None or resolution.event is None:
            return BounceTargetResult(ok=False, error=resolution.blocked_reason, metadata=resolution.blocked_payload())
        result = dict(resolution.selected_outcome.payload)
        if resolution.roll is not None:
            result["roll"] = resolution.roll
        result["rng_event_id"] = resolution.event.event_id
        result["choice_key"] = request.choice_key
        result["choice_source"] = resolution.choice_source
        return BounceTargetResult(
            ok=True,
            target_id=str(result.get("selected_target_id") or ""),
            rng_event=resolution.event,
            metadata=result,
        )


def _policy_allows(actor_id: str, actor: Any, target_id: str, target: Any, policy: TargetPolicy) -> bool:
    if target_id == actor_id:
        return policy.allow_self
    if is_same_combat_team(actor, target):
        return policy.allow_ally
    if is_opposing_combat_team(actor, target):
        return policy.allow_enemy
    return False


@dataclass(frozen=True)
class _ExpressionResolution:
    target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    steps: list[JSONValue] = field(default_factory=list)
    rng_events: tuple[RNGEvent, ...] = ()


def _resolve_expression_payload(
    state: BattleState,
    raw: JSONValue,
    *,
    expression_kind: str,
    alias: str,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
) -> _ExpressionResolution:
    return _resolve_inline_expression(
        state,
        raw,
        expression_kind=expression_kind,
        alias=alias,
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=param_entity_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload=event_payload,
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        previous_targets=(),
        path="$",
    )


def _resolve_inline_expression(
    state: BattleState,
    raw: JSONValue,
    *,
    expression_kind: str,
    alias: str,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    previous_targets: tuple[str, ...],
    path: str,
) -> _ExpressionResolution:
    if isinstance(raw, dict):
        expression_kind = _inline_expression_kind(raw) or expression_kind
        alias = _inline_target_alias(raw) or alias
    if expression_kind == "TargetAlias":
        alias_result = _resolve_target_alias_resolution(
            state,
            alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            path=path,
        )
        return _inline_result(
            path,
            expression_kind,
            alias,
            alias_result.target_ids,
            alias_result.blocked_reason,
            alias_result.steps,
            alias_result.rng_events,
        )
    if expression_kind == "TargetConcat":
        children = _inline_children(raw, expression_kind)
        if not children:
            return _inline_result(path, expression_kind, alias, (), f"target_expression_children_missing:{expression_kind}")
        selected: tuple[str, ...] = ()
        steps: list[JSONValue] = []
        rng_events: list[RNGEvent] = []
        for index, child in enumerate(children):
            child_result = _resolve_inline_expression(
                state,
                child,
                expression_kind=_inline_expression_kind(child),
                alias=_inline_target_alias(child),
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                previous_targets=(),
                path=f"{path}.{expression_kind}[{index}]",
            )
            steps.extend(child_result.steps)
            rng_events.extend(child_result.rng_events)
            if child_result.blocked_reason:
                return _inline_result(path, expression_kind, alias, (), child_result.blocked_reason, steps, tuple(rng_events))
            selected = _dedupe((*selected, *child_result.target_ids))
        return _inline_result(path, expression_kind, alias, selected, "", steps, tuple(rng_events))
    if expression_kind == "TargetSequence":
        children = _inline_children(raw, expression_kind)
        if not children:
            return _inline_result(path, expression_kind, alias, (), f"target_expression_children_missing:{expression_kind}")
        selected: tuple[str, ...] = ()
        steps: list[JSONValue] = []
        rng_events: list[RNGEvent] = []
        for index, child in enumerate(children):
            child_kind = _inline_expression_kind(child)
            child_path = f"{path}.{expression_kind}[{index}]"
            if child_kind == "TargetFilter":
                child_result = _resolve_filter_expression(
                    state,
                    child,
                    caster_id=caster_id,
                    owner_id=owner_id,
                    param_entity_id=param_entity_id,
                    current_action_target_id=current_action_target_id,
                    target_resolution=target_resolution,
                    event_payload=event_payload,
                    dynamic_values=dynamic_values,
                    binding_sources=binding_sources,
                    candidate_targets=selected,
                    path=child_path,
                )
            elif _is_transform_expression_kind(child_kind):
                child_result = _resolve_transform_expression(
                    state,
                    child,
                    expression_kind=child_kind,
                    caster_id=caster_id,
                    owner_id=owner_id,
                    target_resolution=target_resolution,
                    event_payload=event_payload,
                    dynamic_values=dynamic_values,
                    binding_sources=binding_sources,
                    candidate_targets=selected,
                    path=child_path,
                )
            else:
                child_result = _resolve_inline_expression(
                    state,
                    child,
                    expression_kind=child_kind,
                    alias=_inline_target_alias(child),
                    caster_id=caster_id,
                    owner_id=owner_id,
                    param_entity_id=param_entity_id,
                    current_action_target_id=current_action_target_id,
                    target_resolution=target_resolution,
                    event_payload=event_payload,
                    dynamic_values=dynamic_values,
                    binding_sources=binding_sources,
                    previous_targets=selected,
                    path=child_path,
                )
            steps.extend(child_result.steps)
            rng_events.extend(child_result.rng_events)
            if child_result.blocked_reason:
                return _inline_result(path, expression_kind, alias, (), child_result.blocked_reason, steps, tuple(rng_events))
            selected = child_result.target_ids
        return _inline_result(path, expression_kind, alias, selected, "", steps, tuple(rng_events))
    if expression_kind == "TargetFilter":
        return _resolve_filter_expression(
            state,
            raw,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            candidate_targets=previous_targets,
            path=path,
        )
    if expression_kind == "Retarget":
        return _resolve_retarget_expression(
            state,
            raw,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            path=path,
        )
    if expression_kind.startswith("TargetFetch"):
        return _resolve_fetch_expression(
            state,
            raw,
            expression_kind=expression_kind,
            caster_id=caster_id,
            owner_id=owner_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            path=path,
        )
    if _is_transform_expression_kind(expression_kind):
        return _resolve_transform_expression(
            state,
            raw,
            expression_kind=expression_kind,
            caster_id=caster_id,
            owner_id=owner_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            candidate_targets=previous_targets,
            path=path,
        )
    return _inline_result(path, expression_kind, alias, (), f"target_expression_kind_not_supported:{expression_kind}")


def _resolve_filter_expression(
    state: BattleState,
    raw: JSONValue,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    candidate_targets: tuple[str, ...],
    path: str,
) -> _ExpressionResolution:
    if not isinstance(raw, dict):
        return _inline_result(path, "TargetFilter", "", (), "target_filter_payload_missing")
    explicit_target = _filter_candidate_expression(raw)
    steps: list[JSONValue] = []
    if explicit_target is not None:
        source_result = _resolve_inline_expression(
            state,
            explicit_target,
            expression_kind=_inline_expression_kind(explicit_target),
            alias=_inline_target_alias(explicit_target),
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            previous_targets=(),
            path=f"{path}.source",
        )
        steps.extend(source_result.steps)
        if source_result.blocked_reason:
            return _inline_result(path, "TargetFilter", "", (), source_result.blocked_reason, steps, source_result.rng_events)
        candidate_targets = source_result.target_ids
    if not candidate_targets:
        return _inline_result(path, "TargetFilter", "", (), "target_filter_candidate_missing", steps)
    predicate = raw.get("Predicate")
    if not isinstance(predicate, dict):
        return _inline_result(path, "TargetFilter", "", (), "target_filter_predicate_missing", steps)
    condition = _condition_from_raw(predicate, path)
    evaluator = RuleEvaluator()
    selected: list[str] = []
    condition_results: list[JSONValue] = []
    for candidate_id in candidate_targets:
        result = evaluator.evaluate_condition_result(
            condition,
            EvaluationContext(
                state=state,
                actor_id=caster_id,
                target_id=candidate_id,
                owner_id=owner_id,
                param_entity_id=candidate_id,
                current_action_target_id=current_action_target_id or candidate_id,
                event_payload={**event_payload, "target_id": candidate_id, "param_entity_id": candidate_id},
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
            ),
        )
        condition_results.append(result.to_json())
        if not result.ok or result.result is None:
            return _inline_result(
                path,
                "TargetFilter",
                "",
                (),
                f"target_filter_condition_blocked:{result.reason}",
                [*steps, {"condition_results": condition_results}],
                source_result.rng_events if explicit_target is not None else (),
            )
        if result.result:
            selected.append(candidate_id)
    return _inline_result(
        path,
        "TargetFilter",
        "",
        tuple(selected),
        "",
        [*steps, {"condition_results": condition_results}],
        source_result.rng_events if explicit_target is not None else (),
    )


def _resolve_retarget_expression(
    state: BattleState,
    raw: JSONValue,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    path: str,
) -> _ExpressionResolution:
    if not isinstance(raw, dict):
        return _inline_result(path, "Retarget", "", (), "retarget_payload_missing")
    target_expr = raw.get("TargetType")
    if not isinstance(target_expr, dict):
        return _inline_result(path, "Retarget", "", (), "retarget_target_type_missing")
    source_result = _resolve_inline_expression(
        state,
        target_expr,
        expression_kind=_inline_expression_kind(target_expr),
        alias=_inline_target_alias(target_expr),
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=param_entity_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload=event_payload,
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        previous_targets=(),
        path=f"{path}.TargetType",
    )
    if source_result.blocked_reason:
        return _inline_result(path, "Retarget", "", (), source_result.blocked_reason, source_result.steps, source_result.rng_events)
    candidate_targets = source_result.target_ids
    steps = list(source_result.steps)
    rng_events = list(source_result.rng_events)
    predicate = raw.get("Predicate")
    if isinstance(predicate, dict):
        filter_result = _resolve_filter_expression(
            state,
            {"$type": "RPG.GameCore.TargetFilter", "Predicate": predicate},
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            candidate_targets=candidate_targets,
            path=f"{path}.Predicate",
        )
        steps.extend(filter_result.steps)
        rng_events.extend(filter_result.rng_events)
        if filter_result.blocked_reason:
            return _inline_result(path, "Retarget", "", (), filter_result.blocked_reason, steps, tuple(rng_events))
        candidate_targets = filter_result.target_ids
    max_number, max_step, max_reason = _positive_int_from_numeric(
        raw.get("MaxNumber"),
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        source_trace={"target_expression_path": path, "field": "MaxNumber"},
        missing_default=len(candidate_targets),
    )
    steps.append(max_step)
    if max_reason:
        return _inline_result(path, "Retarget", "", (), f"retarget_max_number_blocked:{max_reason}", steps, tuple(rng_events))
    if raw.get("ByRandom") is True:
        random_result = _select_random_targets(
            state,
            candidate_targets,
            event_payload=event_payload,
            path=f"{path}.ByRandom",
            source_trace={"target_expression_path": path, "expression_kind": "Retarget"},
        )
        steps.extend(random_result.steps)
        rng_events.extend(random_result.rng_events)
        if random_result.blocked_reason:
            return _inline_result(path, "Retarget", "", (), random_result.blocked_reason, steps, tuple(rng_events))
        candidate_targets = random_result.target_ids
    selected = candidate_targets[: max_number]
    if not selected:
        return _inline_result(path, "Retarget", "", (), "retarget_candidate_missing", steps, tuple(rng_events))
    return _inline_result(path, "Retarget", "", selected, "", steps, tuple(rng_events))


def _is_transform_expression_kind(kind: str) -> bool:
    return kind in {
        "TargetMapAdjoinEntity",
        "TargetReverse",
        "TargetShuffle",
        "TargetTake",
        "TargetIndex",
    } or kind.startswith("TargetSort")


def _resolve_fetch_expression(
    state: BattleState,
    raw: JSONValue,
    *,
    expression_kind: str,
    caster_id: str,
    owner_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    path: str,
) -> _ExpressionResolution:
    payload = raw if isinstance(raw, dict) else {}
    if expression_kind == "TargetFetchCaster":
        return _validated_target_result(state, path, expression_kind, (caster_id,), "target_fetch_caster")
    if expression_kind in {"TargetFetchModifierOwner", "TargetFetchOwner"}:
        if not owner_id:
            return _inline_result(path, expression_kind, "", (), "target_fetch_owner_missing")
        return _validated_target_result(state, path, expression_kind, (owner_id,), "target_fetch_owner")
    if expression_kind in {"TargetFetchAbilityTarget", "TargetFetchCurrentActionTarget"}:
        target_ids: tuple[str, ...] = ()
        if current_action_target_id:
            target_ids = (current_action_target_id,)
        elif target_resolution is not None and target_resolution.selected:
            target_ids = tuple(target_resolution.selected)
        if not target_ids:
            return _inline_result(path, expression_kind, "", (), "target_fetch_ability_target_missing")
        return _validated_target_result(state, path, expression_kind, target_ids, "target_fetch_ability_target")
    if expression_kind == "TargetFetchParamEntityList":
        target_ids, reason = _target_ids_from_payload(
            state,
            event_payload,
            ("param_entity_ids", "param_entity_list", "param_entities"),
            missing_reason="param_entity_list_missing",
        )
        if reason:
            return _inline_result(path, expression_kind, "", (), reason)
        return _validated_target_result(state, path, expression_kind, target_ids, "target_fetch_param_entity_list")
    if expression_kind == "TargetFetchPartner":
        return _resolve_partner_fetch(state, payload, caster_id=caster_id, path=path)
    if expression_kind == "TargetFetchUniqueNameEntity":
        unique_name = str(payload.get("UniqueName") or "")
        if not unique_name:
            return _inline_result(path, expression_kind, "", (), "unique_entity_key_missing")
        return _resolve_unique_entity(state, unique_name, path=path)
    return _inline_result(path, expression_kind, "", (), f"target_fetch_not_supported:{expression_kind}")


def _resolve_transform_expression(
    state: BattleState,
    raw: JSONValue,
    *,
    expression_kind: str,
    caster_id: str,
    owner_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    candidate_targets: tuple[str, ...],
    path: str,
) -> _ExpressionResolution:
    payload = raw if isinstance(raw, dict) else {}
    if not candidate_targets:
        return _inline_result(path, expression_kind, "", (), f"target_transform_candidate_missing:{expression_kind}")
    if expression_kind == "TargetReverse":
        return _inline_result(
            path,
            expression_kind,
            "",
            tuple(reversed(candidate_targets)),
            "",
            [{"operation": "reverse", "candidate_pool_before": list(candidate_targets)}],
        )
    if expression_kind in {"TargetTake", "TargetIndex"}:
        return _resolve_take_expression(
            candidate_targets,
            payload,
            expression_kind=expression_kind,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            path=path,
        )
    if expression_kind == "TargetMapAdjoinEntity":
        return _resolve_adjacent_expression(state, candidate_targets, payload, path=path)
    if expression_kind == "TargetShuffle":
        return _select_random_targets(
            state,
            candidate_targets,
            event_payload=event_payload,
            path=path,
            source_trace={"target_expression_path": path, "expression_kind": expression_kind},
        )
    if expression_kind.startswith("TargetSort"):
        return _resolve_sort_expression(state, candidate_targets, payload, expression_kind=expression_kind, path=path)
    return _inline_result(path, expression_kind, "", (), f"target_transform_not_supported:{expression_kind}")


def _resolve_target_alias_resolution(
    state: BattleState,
    alias: str,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    path: str,
) -> _ExpressionResolution:
    concat_alias = _safe_concat_alias(alias)
    if concat_alias:
        selected: tuple[str, ...] = ()
        steps: list[JSONValue] = []
        for index, child_alias in enumerate(concat_alias):
            child = _resolve_target_alias_resolution(
                state,
                child_alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                path=f"{path}.alias_concat[{index}]",
            )
            steps.extend(child.steps)
            if child.blocked_reason:
                return _inline_result(path, "TargetAlias", alias, (), child.blocked_reason, steps)
            selected = _dedupe((*selected, *child.target_ids))
        return _inline_result(path, "TargetAlias", alias, selected, "", steps)

    expanded = _safe_alias_expansion(alias)
    if expanded is not None:
        base_alias, operations = expanded
        base = _resolve_target_alias_resolution(
            state,
            base_alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            path=f"{path}.alias_base",
        )
        steps = list(base.steps)
        if base.blocked_reason:
            return _inline_result(path, "TargetAlias", alias, (), base.blocked_reason, steps)
        current = base.target_ids
        for index, operation in enumerate(operations):
            result = _apply_alias_operation(
                state,
                current,
                operation,
                path=f"{path}.alias_op[{index}]",
            )
            steps.extend(result.steps)
            if result.blocked_reason:
                return _inline_result(path, "TargetAlias", alias, (), result.blocked_reason, steps)
            current = result.target_ids
        return _inline_result(path, "TargetAlias", alias, current, "", steps)

    target_ids, reason = _resolve_target_alias_ids(
        state,
        alias,
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=param_entity_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload=event_payload,
    )
    return _inline_result(path, "TargetAlias", alias, target_ids, reason)


def _resolve_target_alias_ids(
    state: BattleState,
    alias: str,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
) -> tuple[tuple[str, ...], str]:
    if alias in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget", "AbilityTargetEntity"}:
        target_id = _resolve_single_alias(
            alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
        )
        if target_id is None:
            return (), f"unsupported_or_missing_target_alias:{alias}"
        if target_id not in state.units:
            return (), f"target unit {target_id!r} is not in state"
        return (target_id,), ""
    if alias in {"SkillTargetEntityList", "ParamEntitySkillTargetEntityList"}:
        return _target_ids_from_resolution_or_payload(state, target_resolution, event_payload)
    if alias == "ParamEntityList":
        return _target_ids_from_payload(
            state,
            event_payload,
            ("param_entity_ids", "param_entity_list", "param_entities"),
            missing_reason="param_entity_list_missing",
        )
    if alias in {"AllEnemy", "AllTeamMember", "AllLightTeam", "AllDarkTeam", "AllTeammate", "TeamFormation", "AllEnemyWithUnSelectable"}:
        return _resolve_group_alias(state, caster_id, alias)
    if alias == "LastSummonMonsters":
        return _last_summon_monsters(state)
    if alias == "CasterSummonedMinions":
        return _caster_summoned_minions(state, caster_id)
    return (), f"target_alias_not_admitted:{alias or 'missing'}"


def _resolve_single_alias(
    alias: str,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
) -> str | None:
    if alias == "Caster":
        return caster_id
    if alias == "ModifierOwnerEntity":
        return owner_id or caster_id
    if alias == "ParamEntity":
        return param_entity_id
    if alias in {"CurrentActionTarget", "AbilityTargetEntity"}:
        if current_action_target_id:
            return current_action_target_id
        if alias == "AbilityTargetEntity" and target_resolution is not None and target_resolution.selected:
            return target_resolution.selected[0]
    return None


def _resolve_group_alias(
    state: BattleState,
    caster_id: str,
    alias: str,
) -> tuple[tuple[str, ...], str]:
    caster = state.units.get(caster_id)
    if caster is None:
        return (), "caster_missing_for_group_target"
    targets: list[str] = []
    for unit_id, unit in sorted(state.units.items()):
        if not UnitLifecycleSystem().can_target(state, unit_id)[0]:
            continue
        if alias in {"AllEnemy", "AllEnemyWithUnSelectable"} and is_opposing_combat_team(caster, unit):
            targets.append(unit_id)
        elif alias in {"AllTeamMember", "TeamFormation"} and is_same_combat_team(caster, unit):
            targets.append(unit_id)
        elif alias == "AllLightTeam" and is_light_team(unit):
            targets.append(unit_id)
        elif alias == "AllDarkTeam" and is_dark_team(unit):
            targets.append(unit_id)
        elif alias == "AllTeammate" and is_same_combat_team(caster, unit) and unit_id != caster_id:
            targets.append(unit_id)
    if not targets:
        return (), f"target group empty:{alias}"
    return tuple(dict.fromkeys(targets)), ""


def _validated_target_result(
    state: BattleState,
    path: str,
    expression_kind: str,
    target_ids: tuple[str, ...],
    operation: str,
    *,
    allow_defeated: bool = False,
    metadata: dict[str, JSONValue] | None = None,
) -> _ExpressionResolution:
    selected: list[str] = []
    skipped: list[JSONValue] = []
    lifecycle = UnitLifecycleSystem()
    for target_id in target_ids:
        if target_id not in state.units:
            skipped.append({"target_id": target_id, "reason": "unit_missing"})
            continue
        ok, reason = lifecycle.can_target(state, target_id, allow_defeated=allow_defeated)
        if not ok:
            skipped.append({"target_id": target_id, "reason": reason})
            continue
        selected.append(target_id)
    step = {
        "operation": operation,
        "candidate_pool_before": list(target_ids),
        "selected_targets": selected,
        "skipped_targets": skipped,
        "allow_defeated": allow_defeated,
    }
    if metadata:
        step.update(metadata)
    if skipped:
        return _inline_result(path, expression_kind, "", (), f"target_lifecycle_blocked:{operation}", [step])
    if not selected:
        return _inline_result(path, expression_kind, "", (), f"target_candidates_empty:{operation}", [step])
    return _inline_result(path, expression_kind, "", _dedupe(tuple(selected)), "", [step])


def _resolve_partner_fetch(state: BattleState, payload: dict[str, JSONValue], *, caster_id: str, path: str) -> _ExpressionResolution:
    registry = state.global_flags.get("target_partner_registry")
    if not isinstance(registry, dict):
        return _inline_result(path, "TargetFetchPartner", "", (), "target_partner_registry_missing")
    name = str(payload.get("Name") or "")
    lookup_keys = (name, f"{caster_id}:{name}") if name else (caster_id,)
    matched_key = ""
    target_ids: tuple[str, ...] = ()
    for key in lookup_keys:
        if not key:
            continue
        candidate_ids = _ids_from_registry_value(registry.get(key))
        if candidate_ids:
            matched_key = key
            target_ids = candidate_ids
            break
    step = {
        "operation": "target_fetch_partner",
        "name": name,
        "lookup_keys": list(lookup_keys),
        "matched_registry_key": matched_key,
        "candidate_pool_before": list(target_ids),
    }
    if not target_ids:
        return _inline_result(path, "TargetFetchPartner", "", (), "target_partner_missing", [step])
    return _validated_target_result(
        state,
        path,
        "TargetFetchPartner",
        target_ids,
        "target_fetch_partner",
        metadata={
            "name": name,
            "lookup_keys": list(lookup_keys),
            "matched_registry_key": matched_key,
        },
    )


def _resolve_unique_entity(state: BattleState, unique_name: str, *, path: str) -> _ExpressionResolution:
    registry = state.global_flags.get("target_unique_entity_registry")
    if not isinstance(registry, dict):
        return _inline_result(path, "TargetFetchUniqueNameEntity", "", (), "target_unique_entity_registry_missing")
    target_ids = _ids_from_registry_value(registry.get(unique_name))
    step = {"operation": "target_fetch_unique_entity", "unique_name": unique_name, "candidate_pool_before": list(target_ids)}
    if not target_ids:
        return _inline_result(path, "TargetFetchUniqueNameEntity", "", (), "unique_entity_missing", [step])
    if len(target_ids) > 1:
        return _inline_result(path, "TargetFetchUniqueNameEntity", "", (), "unique_entity_ambiguous", [step])
    return _validated_target_result(state, path, "TargetFetchUniqueNameEntity", target_ids, "target_fetch_unique_entity")


def _ids_from_registry_value(value: JSONValue) -> tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if isinstance(item, str) and item)
    if isinstance(value, dict):
        unit_id = value.get("unit_id")
        if isinstance(unit_id, str) and unit_id:
            return (unit_id,)
        unit_ids = value.get("unit_ids")
        if isinstance(unit_ids, list):
            return tuple(str(item) for item in unit_ids if isinstance(item, str) and item)
    return ()


def _resolve_sort_expression(
    state: BattleState,
    candidate_targets: tuple[str, ...],
    payload: dict[str, JSONValue],
    *,
    expression_kind: str,
    path: str,
) -> _ExpressionResolution:
    values: dict[str, float] = {}
    skipped: list[JSONValue] = []
    sort_key = ""
    if expression_kind == "TargetSortByProperty":
        sort_key = str(payload.get("PropertyType") or "")
        value_getter = _property_sort_value
    elif expression_kind == "TargetSortByPropertyRatio":
        sort_key = str(payload.get("PropertyRatioType") or "")
        value_getter = _property_ratio_sort_value
    elif expression_kind == "TargetSortByFormation":
        sort_key = "formation_position"
        value_getter = _formation_sort_value
    else:
        return _inline_result(path, expression_kind, "", (), f"target_sort_not_supported:{expression_kind}")
    for target_id in candidate_targets:
        unit = state.units.get(target_id)
        if unit is None:
            skipped.append({"target_id": target_id, "reason": "unit_missing"})
            continue
        value, reason = value_getter(unit, sort_key)
        if reason:
            skipped.append({"target_id": target_id, "reason": reason})
            continue
        values[target_id] = value
    step = {
        "operation": "target_sort",
        "sort_kind": expression_kind,
        "sort_key": sort_key,
        "candidate_pool_before": list(candidate_targets),
        "sort_values": values,
        "skipped_targets": skipped,
        "tie_breaker": "unit_id",
    }
    if skipped:
        return _inline_result(path, expression_kind, "", (), f"target_sort_value_blocked:{sort_key or 'missing'}", [step])
    if not values:
        return _inline_result(path, expression_kind, "", (), "target_sort_candidate_missing", [step])
    highest_first = bool(payload.get("HighestFirst"))
    if "HighestFirst" not in payload:
        step["direction_source"] = "tbgd_target_operation_default_lowest_first"
    step["direction"] = "desc" if highest_first else "asc"
    ordered = tuple(
        sorted(
            candidate_targets,
            key=lambda target_id: (
                -values[target_id] if highest_first else values[target_id],
                target_id,
            ),
        )
    )
    step["selected_targets"] = list(ordered)
    return _inline_result(path, expression_kind, "", ordered, "", [step])


def _property_sort_value(unit: Any, sort_key: str) -> tuple[float, str]:
    if sort_key == "CurrentHP":
        return float(unit.hp), ""
    if sort_key == "MaxHP":
        if unit.max_hp <= 0:
            return 0.0, "max_hp_non_positive"
        return float(unit.max_hp), ""
    if sort_key == "CurrentStance":
        return float(unit.toughness), ""
    if sort_key == "MaxStance":
        if unit.max_toughness <= 0:
            return 0.0, "max_toughness_non_positive"
        return float(unit.max_toughness), ""
    return 0.0, f"target_sort_property_not_admitted:{sort_key or 'missing'}"


def _property_ratio_sort_value(unit: Any, sort_key: str) -> tuple[float, str]:
    if sort_key == "HPRatio":
        if unit.max_hp <= 0:
            return 0.0, "max_hp_non_positive"
        return float(unit.hp) / float(unit.max_hp), ""
    if sort_key == "StanceRatio":
        if unit.max_toughness <= 0:
            return 0.0, "max_toughness_non_positive"
        return float(unit.toughness) / float(unit.max_toughness), ""
    return 0.0, f"target_sort_ratio_not_admitted:{sort_key or 'missing'}"


def _formation_sort_value(unit: Any, sort_key: str) -> tuple[float, str]:
    position = _position(unit.flags.get("position"))
    if position is None:
        return 0.0, "target_position_missing"
    return float(position), ""


def _resolve_take_expression(
    candidate_targets: tuple[str, ...],
    payload: dict[str, JSONValue],
    *,
    expression_kind: str,
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    path: str,
) -> _ExpressionResolution:
    if expression_kind == "TargetTake":
        count, numeric_step, reason = _positive_int_from_numeric(
            payload.get("Count"),
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            source_trace={"target_expression_path": path, "field": "Count"},
            missing_default=None,
        )
        if reason:
            return _inline_result(path, expression_kind, "", (), f"target_take_count_blocked:{reason}", [numeric_step])
        selected = candidate_targets[:count]
        return _inline_result(
            path,
            expression_kind,
            "",
            selected,
            "" if selected else "target_take_selected_empty",
            [{"operation": "target_take", "count": count, "candidate_pool_before": list(candidate_targets), "selected_targets": list(selected), "numeric_evaluation": numeric_step}],
        )
    index_type = str(payload.get("IndexType") or "IndexStrict")
    if index_type == "Last":
        index = len(candidate_targets) - 1
        numeric_step = {"operation": "target_index", "index_type": index_type, "index": index}
    elif index_type == "First":
        index = 0
        numeric_step = {"operation": "target_index", "index_type": index_type, "index": index}
    else:
        index_value = payload.get("IndexValue")
        if index_value is None:
            index = 0
            numeric_step = {"operation": "target_index", "index_type": index_type, "index": index, "index_source": "tbgd_select1_default_zero"}
        else:
            index, numeric_step, reason = _non_negative_int_from_numeric(
                index_value,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                source_trace={"target_expression_path": path, "field": "IndexValue"},
            )
            if reason:
                return _inline_result(path, expression_kind, "", (), f"target_index_blocked:{reason}", [numeric_step])
    if index < 0 or index >= len(candidate_targets):
        return _inline_result(path, expression_kind, "", (), "target_index_out_of_range", [numeric_step])
    selected = (candidate_targets[index],)
    return _inline_result(
        path,
        expression_kind,
        "",
        selected,
        "",
        [{"operation": "target_index", "candidate_pool_before": list(candidate_targets), "selected_targets": list(selected), "index": index, "index_type": index_type, "numeric_evaluation": numeric_step}],
    )


def _resolve_adjacent_expression(
    state: BattleState,
    candidate_targets: tuple[str, ...],
    payload: dict[str, JSONValue],
    *,
    path: str,
) -> _ExpressionResolution:
    side_type = str(payload.get("SideType") or "Both")
    selected: list[str] = []
    skipped: list[JSONValue] = []
    for primary_id in candidate_targets:
        primary = state.units.get(primary_id)
        if primary is None:
            skipped.append({"target_id": primary_id, "reason": "unit_missing"})
            continue
        position = _position(primary.flags.get("position"))
        if position is None:
            skipped.append({"target_id": primary_id, "reason": "target_position_missing"})
            continue
        wanted = set()
        if side_type in {"Both", "", "Left"}:
            wanted.add(position - 1)
        if side_type in {"Both", "", "Right"}:
            wanted.add(position + 1)
        if not wanted:
            skipped.append({"target_id": primary_id, "reason": f"target_adjacent_side_not_admitted:{side_type}"})
            continue
        for unit_id, unit in state.units.items():
            if unit_id == primary_id or not is_same_combat_team(primary, unit):
                continue
            unit_position = _position(unit.flags.get("position"))
            if unit_position not in wanted:
                continue
            ok, reason = UnitLifecycleSystem().can_target(state, unit_id)
            if not ok:
                skipped.append({"target_id": unit_id, "primary_target_id": primary_id, "reason": reason})
                continue
            selected.append(unit_id)
    ordered = tuple(
        sorted(
            _dedupe(tuple(selected)),
            key=lambda target_id: (_position(state.units[target_id].flags.get("position")) or 0, target_id),
        )
    )
    step = {
        "operation": "target_adjacent",
        "side_type": side_type,
        "candidate_pool_before": list(candidate_targets),
        "selected_targets": list(ordered),
        "skipped_targets": skipped,
        "position_source": "UnitState.flags.position",
    }
    if skipped and not ordered:
        return _inline_result(path, "TargetMapAdjoinEntity", "", (), "target_adjacent_blocked", [step])
    return _inline_result(path, "TargetMapAdjoinEntity", "", ordered, "" if ordered else "target_adjacent_empty", [step])


def _select_random_targets(
    state: BattleState,
    candidate_targets: tuple[str, ...],
    *,
    event_payload: dict[str, JSONValue],
    path: str,
    source_trace: dict[str, JSONValue],
) -> _ExpressionResolution:
    choices = rng_choices_from_payload(event_payload)
    legacy_choices = event_payload.get("target_random_choices")
    if not choices and isinstance(legacy_choices, dict):
        legacy_choice = legacy_choices.get(path)
        if legacy_choice is None:
            legacy_choice = legacy_choices.get("default")
        if legacy_choice is not None:
            choices = {path: legacy_choice}
    outcomes = tuple(
        RNGOutcome(
            outcome_id=str(target_id),
            payload={
                "selected_target_id": target_id,
                "selected_index": index,
                "candidate_pool": list(candidate_targets),
                "value": target_id,
            },
            weight=1.0,
        )
        for index, target_id in enumerate(candidate_targets)
    )
    event_id = f"rng:{state.event_index}:target_random:{_stable_path(path)}:{len(candidate_targets)}"
    request = RNGRequest(
        rng_type="target_random",
        purpose="target_random",
        event_id=event_id,
        choice_key=path,
        source="target_system",
        before_state=state.rng_state,
        decision_kind="choice",
        outcomes=outcomes,
        source_trace=source_trace,
        metadata={"candidate_pool": list(candidate_targets), "path": path},
        invalid_choice_reason="target_random_choice_invalid",
    )
    resolution = resolve_rng_request(
        request,
        rng_choices=choices,
        rng_mode=rng_mode_from_payload(event_payload, default="explicit_ledger"),
    )
    if not resolution.ok:
        return _inline_result(
            path,
            "TargetShuffle",
            "",
            (),
            resolution.blocked_reason,
            [
                {
                    "operation": "target_random",
                    "candidate_pool_before": list(candidate_targets),
                    "choice_key": path,
                    "available_rng_outcomes": resolution.available_rng_outcomes(),
                    "raw_choice": resolution.raw_choice,
                }
            ],
        )
    if resolution.selected_outcome is None or resolution.event is None:
        return _inline_result(path, "TargetShuffle", "", (), "target_random_choice_invalid")
    selected_id = str(resolution.selected_outcome.payload.get("selected_target_id") or "")
    selected_index = int(resolution.selected_outcome.payload.get("selected_index") or 0)
    step = {
        "operation": "target_random",
        "candidate_pool_before": list(candidate_targets),
        "selected_targets": [selected_id],
        "selected_index": selected_index,
        "rng_event_id": event_id,
        "choice_key": path,
        "choice_source": resolution.choice_source,
    }
    return _inline_result(path, "TargetShuffle", "", (selected_id,), "", [step], (resolution.event,))


def _positive_int_from_numeric(
    value: JSONValue,
    *,
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    source_trace: dict[str, JSONValue],
    missing_default: int | None,
) -> tuple[int, dict[str, JSONValue], str]:
    if value is None and missing_default is not None:
        return missing_default, {"operation": "numeric_default", "value": missing_default, "source_trace": source_trace}, ""
    result = RuleEvaluator().evaluate_numeric(
        value,
        NumericEvaluationContext(
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            source_trace=source_trace,
        ),
    )
    step = {"operation": "numeric_evaluation", "numeric_evaluation": result.to_json()}
    if not result.ok or result.value is None:
        return 0, step, result.blocked_reason or "numeric_not_executable"
    if int(result.value) != float(result.value) or result.value <= 0:
        return 0, step, "numeric_not_positive_integer"
    return int(result.value), step, ""


def _non_negative_int_from_numeric(
    value: JSONValue,
    *,
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    source_trace: dict[str, JSONValue],
) -> tuple[int, dict[str, JSONValue], str]:
    result = RuleEvaluator().evaluate_numeric(
        value,
        NumericEvaluationContext(
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            source_trace=source_trace,
        ),
    )
    step = {"operation": "numeric_evaluation", "numeric_evaluation": result.to_json()}
    if not result.ok or result.value is None:
        return 0, step, result.blocked_reason or "numeric_not_executable"
    if int(result.value) != float(result.value) or result.value < 0:
        return 0, step, "numeric_not_non_negative_integer"
    return int(result.value), step, ""


def _safe_concat_alias(alias: str) -> tuple[str, ...]:
    return {
        "AbilityTargetAndAdjoinEntity": ("AbilityTargetEntity", "AbilityTargetAdjoinEntity"),
        "CasterWithAbilityTargetAndAdjoinEntity": ("Caster", "AbilityTargetAndAdjoinEntity"),
    }.get(alias, ())


def _safe_alias_expansion(alias: str) -> tuple[str, tuple[dict[str, JSONValue], ...]] | None:
    direct: dict[str, tuple[str, tuple[dict[str, JSONValue], ...]]] = {
        "AbilityTargetAdjoinEntity": ("AbilityTargetEntity", ({"kind": "TargetMapAdjoinEntity"},)),
        "AbilityTargetLeftEntity": ("AbilityTargetEntity", ({"kind": "TargetMapAdjoinEntity", "SideType": "Left"},)),
        "AbilityTargetRightEntity": ("AbilityTargetEntity", ({"kind": "TargetMapAdjoinEntity", "SideType": "Right"},)),
        "ParamEntityAdjoinEntity": ("ParamEntity", ({"kind": "TargetMapAdjoinEntity"},)),
        "CasterAdjoinEntity": ("Caster", ({"kind": "TargetMapAdjoinEntity"},)),
        "ModifierOwnerEntityAdjoinEntity": ("ModifierOwnerEntity", ({"kind": "TargetMapAdjoinEntity"},)),
    }
    if alias in direct:
        return direct[alias]
    if not _safe_dot_alias(alias):
        return None
    parts = tuple(part for part in alias.split(".") if part)
    if len(parts) < 2:
        return None
    base_alias = parts[0]
    operations: list[dict[str, JSONValue]] = []
    for op in parts[1:]:
        operation = _dot_alias_operation(op)
        if operation is None:
            return None
        operations.append(operation)
    return base_alias, tuple(operations)


def _safe_dot_alias(alias: str) -> bool:
    if "." not in alias:
        return False
    return not any(token in alias for token in (" ", "+", "-", "|", "(", ")"))


def _dot_alias_operation(op: str) -> dict[str, JSONValue] | None:
    mapping: dict[str, dict[str, JSONValue]] = {
        "GetAliveOnly": {"kind": "GetAliveOnly"},
        "SortByHP": {"kind": "TargetSortByProperty", "PropertyType": "CurrentHP"},
        "SortByHPRatio": {"kind": "TargetSortByPropertyRatio", "PropertyRatioType": "HPRatio"},
        "SortByMaxHP": {"kind": "TargetSortByProperty", "PropertyType": "MaxHP"},
        "SortByStance": {"kind": "TargetSortByProperty", "PropertyType": "CurrentStance"},
        "SortByStanceRatio": {"kind": "TargetSortByPropertyRatio", "PropertyRatioType": "StanceRatio"},
        "SortByFormation": {"kind": "TargetSortByFormation"},
        "Reverse": {"kind": "TargetReverse"},
        "Select1": {"kind": "TargetIndex", "IndexType": "IndexStrict"},
        "SelectLast": {"kind": "TargetIndex", "IndexType": "Last"},
        "GetAdjoinEntity": {"kind": "TargetMapAdjoinEntity"},
    }
    return mapping.get(op)


def _apply_alias_operation(
    state: BattleState,
    candidate_targets: tuple[str, ...],
    operation: dict[str, JSONValue],
    *,
    path: str,
) -> _ExpressionResolution:
    kind = str(operation.get("kind") or "")
    if kind == "GetAliveOnly":
        selected: list[str] = []
        skipped: list[JSONValue] = []
        lifecycle = UnitLifecycleSystem()
        for target_id in candidate_targets:
            ok, reason = lifecycle.can_target(state, target_id)
            if ok:
                selected.append(target_id)
            else:
                skipped.append({"target_id": target_id, "reason": reason})
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            tuple(selected),
            "" if selected else "target_alive_filter_empty",
            [{"operation": "GetAliveOnly", "candidate_pool_before": list(candidate_targets), "selected_targets": selected, "skipped_targets": skipped}],
        )
    if kind == "TargetReverse":
        return _inline_result(path, kind, "", tuple(reversed(candidate_targets)), "", [{"operation": "Reverse", "candidate_pool_before": list(candidate_targets)}])
    if kind in {"TargetSortByProperty", "TargetSortByPropertyRatio", "TargetSortByFormation"}:
        return _resolve_sort_expression(state, candidate_targets, operation, expression_kind=kind, path=path)
    if kind in {"TargetIndex", "TargetTake"}:
        return _resolve_take_expression(candidate_targets, operation, expression_kind=kind, dynamic_values=None, binding_sources=(), path=path)
    if kind == "TargetMapAdjoinEntity":
        return _resolve_adjacent_expression(state, candidate_targets, operation, path=path)
    return _inline_result(path, "TargetAliasOperation", "", (), f"target_alias_operation_not_supported:{kind or 'missing'}")


def _stable_path(path: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in path)[:80]


def _inline_expression_kind(raw: JSONValue) -> str:
    if not isinstance(raw, dict):
        return ""
    node_type = str(raw.get("$type") or "")
    if node_type.startswith("RPG.GameCore."):
        return node_type.removeprefix("RPG.GameCore.")
    if raw.get("Alias") is not None:
        return "TargetAlias"
    return ""


def _inline_target_alias(raw: JSONValue) -> str:
    if isinstance(raw, dict):
        alias = raw.get("Alias")
        if isinstance(alias, str):
            return alias
    return ""


def _inline_children(raw: JSONValue, expression_kind: str) -> tuple[JSONValue, ...]:
    if not isinstance(raw, dict):
        return ()
    key = "Targets" if expression_kind == "TargetConcat" else "Sequence"
    children = raw.get(key)
    if not isinstance(children, list):
        return ()
    return tuple(item for item in children if isinstance(item, dict))


def _filter_candidate_expression(raw: dict[str, JSONValue]) -> JSONValue | None:
    for key in ("TargetType", "Target", "Targets"):
        value = raw.get(key)
        if isinstance(value, dict):
            return value
    return None


def _condition_from_raw(predicate: dict[str, JSONValue], path: str) -> ConditionIR:
    opcode = _inline_expression_kind(predicate) or "UnknownCondition"
    payload = {key: value for key, value in predicate.items() if key != "$type"}
    return ConditionIR(
        condition_id=f"inline_target_filter_condition:{path}:{opcode}",
        opcode=opcode,
        payload=payload,
        source=IRSource(
            source_path="CanonicalIR.TargetExpressionIR.payload",
            raw_type="TargetFilterPredicate",
            raw_id=path,
            evidence={"predicate": predicate},
        ),
        coverage_status="executable",
    )


def _target_ids_from_resolution_or_payload(
    state: BattleState,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
) -> tuple[tuple[str, ...], str]:
    if target_resolution is not None and target_resolution.selected:
        target_ids = _existing_targets(state, target_resolution.selected)
        if target_ids:
            return target_ids, ""
        return (), "skill_target_entity_list_units_missing"
    return _target_ids_from_payload(
        state,
        event_payload,
        ("selected_target_ids", "skill_target_ids", "target_ids", "requested_target_ids"),
        missing_reason="skill_target_entity_list_missing",
    )


def _target_ids_from_payload(
    state: BattleState,
    event_payload: dict[str, JSONValue],
    keys: tuple[str, ...],
    *,
    missing_reason: str,
) -> tuple[tuple[str, ...], str]:
    for key in keys:
        value = event_payload.get(key)
        if isinstance(value, (list, tuple)):
            target_ids = _existing_targets(state, tuple(str(item) for item in value if isinstance(item, str)))
            if target_ids:
                return target_ids, ""
    return (), missing_reason


def _existing_targets(state: BattleState, target_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(target_id for target_id in target_ids if target_id in state.units))


def _last_summon_monsters(state: BattleState) -> tuple[tuple[str, ...], str]:
    runtime = state.global_flags.get("summon_runtime")
    if not isinstance(runtime, dict) or runtime.get("schema_version") != "p1_3_summon_runtime_v1":
        return (), "summon_runtime_missing"
    raw = runtime.get("last_summon_monsters")
    if not isinstance(raw, list):
        return (), "last_summon_monsters_missing"
    lifecycle = UnitLifecycleSystem()
    target_ids = tuple(
        str(item)
        for item in raw
        if isinstance(item, str)
        and item in state.units
        and lifecycle.can_target(state, item, allow_defeated=False)[0]
    )
    if not target_ids:
        return (), "last_summon_monsters_empty"
    return tuple(dict.fromkeys(target_ids)), ""


def _caster_summoned_minions(state: BattleState, caster_id: str) -> tuple[tuple[str, ...], str]:
    runtime = state.global_flags.get("summon_runtime")
    if not isinstance(runtime, dict) or runtime.get("schema_version") != "p1_3_summon_runtime_v1":
        return (), "summon_runtime_missing"
    by_owner = runtime.get("by_owner")
    if not isinstance(by_owner, dict):
        return (), "summon_runtime_by_owner_missing"
    raw = by_owner.get(caster_id)
    if not isinstance(raw, list):
        return (), "caster_summoned_minions_missing"
    lifecycle = UnitLifecycleSystem()
    target_ids = tuple(
        str(item)
        for item in raw
        if isinstance(item, str)
        and item in state.units
        and lifecycle.can_target(state, item, allow_defeated=False)[0]
    )
    if not target_ids:
        return (), "caster_summoned_minions_empty"
    return tuple(dict.fromkeys(target_ids)), ""


def _dedupe(target_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(target_ids))


def _fixed_positive_int(value: JSONValue) -> int | None:
    if isinstance(value, dict):
        fixed = value.get("FixedValue")
        if isinstance(fixed, dict):
            raw = fixed.get("Value")
            if isinstance(raw, (int, float)) and raw > 0:
                return int(raw)
        raw = value.get("Value")
        if isinstance(raw, (int, float)) and raw > 0:
            return int(raw)
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


def _inline_result(
    path: str,
    expression_kind: str,
    alias: str,
    target_ids: tuple[str, ...],
    blocked_reason: str,
    steps: list[JSONValue] | None = None,
    rng_events: tuple[RNGEvent, ...] = (),
) -> _ExpressionResolution:
    step: dict[str, JSONValue] = {
        "path": path,
        "expression_kind": expression_kind,
        "alias": alias,
        "target_ids": list(target_ids),
        "blocked_reason": blocked_reason,
    }
    return _ExpressionResolution(
        target_ids=target_ids,
        blocked_reason=blocked_reason,
        steps=[*(steps or []), step],
        rng_events=rng_events,
    )


def _policy_metadata(policy: TargetPolicy) -> dict[str, JSONValue]:
    return {
        "policy_id": policy.policy_id,
        "allow_enemy": policy.allow_enemy,
        "allow_ally": policy.allow_ally,
        "allow_self": policy.allow_self,
        "allow_defeated": policy.allow_defeated,
        "target_mode": policy.target_mode,
        "selection_mode": policy.selection_mode,
        "bounce_policy": policy.bounce_policy,
    }


def _target_groups(
    state: BattleState,
    actor_id: str,
    legal: tuple[str, ...],
    policy: TargetPolicy,
) -> dict[str, tuple[str, ...]]:
    if not legal:
        return {}
    if policy.target_mode == "blast":
        primary = legal[0]
        adjacent = _adjacent_units(state, actor_id, primary, legal)
        return {"primary": (primary,), "adjacent": adjacent, "selected": (primary, *adjacent)}
    if policy.target_mode == "bounce":
        primary = legal[0]
        return {"primary": (primary,), "selected": (primary,)}
    return {"selected": legal}


def _target_mode_blocked_reason(policy: TargetPolicy) -> str:
    if policy.target_mode == "bounce":
        if str(policy.bounce_policy.get("coverage_status") or "") == "executable":
            return ""
        reason = str(policy.bounce_policy.get("blocked_reason") or "bounce_policy_not_executable")
        return reason
    if policy.target_mode == "unknown":
        return "unknown_target_mode_not_executable"
    if policy.target_mode not in {"single", "aoe", "blast", "self_or_team"}:
        return f"unsupported_target_mode:{policy.target_mode}"
    return ""


def _deterministic_roll(rng_state: str, event_id: str, candidates: tuple[str, ...], previous: tuple[str, ...]) -> float:
    raw = "|".join((rng_state, event_id, ",".join(candidates), ",".join(previous)))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(0xFFFFFFFFFFFF)


def _adjacent_units(
    state: BattleState,
    actor_id: str,
    primary_id: str,
    legal: tuple[str, ...],
) -> tuple[str, ...]:
    primary = state.units.get(primary_id)
    if primary is None:
        return ()
    position = _position(primary.flags.get("position"))
    if position is None:
        return ()
    actor = state.units.get(actor_id)
    if actor is None:
        return ()
    candidates = [
        unit_id
        for unit_id, unit in state.units.items()
        if unit_id != primary_id
        and is_opposing_combat_team(actor, unit)
        and UnitLifecycleSystem().can_target(state, unit_id)[0]
        and _position(unit.flags.get("position")) in {position - 1, position + 1}
    ]
    legal_set = set(legal)
    ordered = sorted(
        candidates,
        key=lambda unit_id: (
            abs((_position(state.units[unit_id].flags.get("position")) or position) - position),
            _position(state.units[unit_id].flags.get("position")) or 0,
            unit_id,
        ),
    )
    return tuple(unit_id for unit_id in ordered if unit_id not in legal_set or unit_id != primary_id)


def _position(value: JSONValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
