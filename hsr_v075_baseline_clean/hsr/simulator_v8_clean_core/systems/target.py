from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..core.model import BattleState, JSONValue, RNGEvent, TargetResolution
from ..rules.evaluator import EvaluationContext, RuleEvaluator
from ..rules.ir import ConditionIR, IRSource, TargetExpressionIR
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

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "target_ids": list(self.target_ids),
            "blocked_reason": self.blocked_reason,
            "expression_id": self.expression_id,
            "expression_kind": self.expression_kind,
            "alias": self.alias,
            "metadata": self.metadata,
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
            )
        return TargetExpressionResult(
            ok=True,
            target_ids=result.target_ids,
            expression_id=expression.target_expression_id,
            expression_kind=expression.expression_kind,
            alias=expression.alias,
            metadata=metadata,
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
                and _policy_allows(actor_id, actor.side, unit_id, unit.side, policy)
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
            if not _policy_allows(actor_id, actor.side, target_id, target.side, policy):
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
            if unit.side != actor.side and self.lifecycle.can_target(state, unit_id, allow_defeated=allow_defeated)[0]
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
    ) -> BounceTargetResult:
        actor = state.units.get(actor_id)
        if actor is None:
            return BounceTargetResult(ok=False, error="unknown_actor")
        if str(bounce_policy.get("coverage_status") or "") != "executable":
            return BounceTargetResult(ok=False, error="bounce_policy_not_executable", metadata={"bounce_policy": bounce_policy})
        live_candidates = tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if unit.side != actor.side and self.lifecycle.can_target(state, unit_id)[0]
        )
        all_candidates = tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if unit.side != actor.side
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
        roll = _deterministic_roll(state.rng_state, event_id, tuple(candidate_pool), tuple(previous_hit_targets))
        selected_index = min(len(candidate_pool) - 1, int(roll * len(candidate_pool))) if candidate_pool else 0
        selected = candidate_pool[selected_index]
        result = {
            "selected_target_id": selected,
            "candidate_pool": list(candidate_pool),
            "candidate_pool_reason": candidate_pool_reason,
            "roll": roll,
            "selected_index": selected_index,
            "hit_index": hit_index,
            "selection_strategy": selection_strategy,
            "live_target_priority": bool(bounce_policy.get("live_target_priority")),
            "continue_on_all_defeated": bool(bounce_policy.get("continue_on_all_defeated")),
            "previous_hit_targets": list(previous_hit_targets),
            "bounce_policy_id": str(bounce_policy.get("bounce_policy_id") or ""),
        }
        rng_event = RNGEvent(
            rng_type="bounce_target",
            source="target_system",
            event_id=event_id,
            before_state=state.rng_state,
            after_state=state.rng_state,
            result=result,
            metadata={
                "actor_id": actor_id,
                "action_id": action_id,
                "action_level": action_level,
                "primary_target_id": primary_target_id,
                "source_trace": bounce_policy.get("source", {}),
            },
        )
        return BounceTargetResult(ok=True, target_id=selected, rng_event=rng_event, metadata=result)


def _policy_allows(actor_id: str, actor_side: str, target_id: str, target_side: str, policy: TargetPolicy) -> bool:
    if target_id == actor_id:
        return policy.allow_self
    if target_side == actor_side:
        return policy.allow_ally
    return policy.allow_enemy


@dataclass(frozen=True)
class _ExpressionResolution:
    target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    steps: list[JSONValue] = field(default_factory=list)


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
        return _inline_result(path, expression_kind, alias, target_ids, reason)
    if expression_kind in {"TargetConcat", "TargetSequence"}:
        children = _inline_children(raw, expression_kind)
        if not children:
            return _inline_result(path, expression_kind, alias, (), f"target_expression_children_missing:{expression_kind}")
        selected: tuple[str, ...] = ()
        steps: list[JSONValue] = []
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
            if child_result.blocked_reason:
                return _inline_result(path, expression_kind, alias, (), child_result.blocked_reason, steps)
            selected = _dedupe((*selected, *child_result.target_ids))
        return _inline_result(path, expression_kind, alias, selected, "", steps)
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
            return _inline_result(path, "TargetFilter", "", (), source_result.blocked_reason, steps)
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
            )
        if result.result:
            selected.append(candidate_id)
    return _inline_result(path, "TargetFilter", "", tuple(selected), "", [*steps, {"condition_results": condition_results}])


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
    if raw.get("ByRandom") is True:
        return _inline_result(path, "Retarget", "", (), "retarget_random_not_admitted")
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
        return _inline_result(path, "Retarget", "", (), source_result.blocked_reason, source_result.steps)
    candidate_targets = source_result.target_ids
    steps = list(source_result.steps)
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
        if filter_result.blocked_reason:
            return _inline_result(path, "Retarget", "", (), filter_result.blocked_reason, steps)
        candidate_targets = filter_result.target_ids
    max_number = _fixed_positive_int(raw.get("MaxNumber"))
    if raw.get("MaxNumber") is not None and max_number is None:
        return _inline_result(path, "Retarget", "", (), "retarget_max_number_not_fixed_positive", steps)
    selected = candidate_targets[: max_number or len(candidate_targets)]
    if not selected:
        return _inline_result(path, "Retarget", "", (), "retarget_candidate_missing", steps)
    return _inline_result(path, "Retarget", "", selected, "", steps)


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
        if alias in {"AllEnemy", "AllEnemyWithUnSelectable"} and unit.side != caster.side:
            targets.append(unit_id)
        elif alias in {"AllTeamMember", "TeamFormation"} and unit.side == caster.side:
            targets.append(unit_id)
        elif alias == "AllLightTeam" and unit.side in {"ally", "summon"}:
            targets.append(unit_id)
        elif alias == "AllDarkTeam" and unit.side == "enemy":
            targets.append(unit_id)
        elif alias == "AllTeammate" and unit.side == caster.side and unit_id != caster_id:
            targets.append(unit_id)
    if not targets:
        return (), f"target group empty:{alias}"
    return tuple(dict.fromkeys(targets)), ""


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
        and unit.side != actor.side
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
