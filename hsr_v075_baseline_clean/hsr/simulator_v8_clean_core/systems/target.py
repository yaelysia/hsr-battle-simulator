from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..core.model import BattleState, JSONValue, RNGEvent, TargetResolution
from ..rules.ir import TargetExpressionIR


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
    ) -> TargetExpressionResult:
        metadata: dict[str, JSONValue] = {
            "target_expression": expression.to_json(),
            "caster_id": caster_id,
            "owner_id": owner_id,
            "param_entity_id": param_entity_id,
            "current_action_target_id": current_action_target_id,
            "target_resolution": target_resolution.to_json() if target_resolution else None,
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
        if expression.expression_kind != "TargetAlias":
            reason = f"target_expression_kind_not_supported:{expression.expression_kind}"
            return TargetExpressionResult(
                ok=False,
                blocked_reason=reason,
                expression_id=expression.target_expression_id,
                expression_kind=expression.expression_kind,
                alias=expression.alias,
                metadata=metadata,
            )
        target_ids, reason = _resolve_target_alias_ids(
            state,
            expression.alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
        )
        if reason:
            return TargetExpressionResult(
                ok=False,
                blocked_reason=reason,
                expression_id=expression.target_expression_id,
                expression_kind=expression.expression_kind,
                alias=expression.alias,
                metadata=metadata,
            )
        return TargetExpressionResult(
            ok=True,
            target_ids=target_ids,
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
                if (policy.allow_defeated or unit.hp > 0)
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
            if target.hp <= 0 and not policy.allow_defeated:
                reason = f"defeated:{target_id}"
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
            if unit.side != actor.side and (allow_defeated or unit.hp > 0)
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
            if unit.side != actor.side and unit.hp > 0
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


def _resolve_target_alias_ids(
    state: BattleState,
    alias: str,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
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
    if alias in {"AllEnemy", "AllTeamMember", "AllLightTeam", "AllTeammate"}:
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
        if unit.hp <= 0:
            continue
        if alias == "AllEnemy" and unit.side != caster.side:
            targets.append(unit_id)
        elif alias in {"AllTeamMember", "AllLightTeam"} and unit.side == caster.side:
            targets.append(unit_id)
        elif alias == "AllTeammate" and unit.side == caster.side and unit_id != caster_id:
            targets.append(unit_id)
    if not targets:
        return (), f"target group empty:{alias}"
    return tuple(dict.fromkeys(targets)), ""


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
        and unit.hp > 0
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
