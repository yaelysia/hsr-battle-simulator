from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from ..core.model import ActionCommand, BattleState, JSONValue, RNGEvent, TargetResolution
from ..rules.action_target_contract import ActionTargetContractIR
from ..rules.ir import ActionEventIR
from ..rules.rulebook import RuleBook
from .summon_runtime import validate_summon_runtime
from .target import TargetSystem, resolve_action_bounce_policy
from .unit_lifecycle import UnitLifecycleSystem
from .unit_relation import EntityRelationResolver, TargetEvaluationContext


ACTION_TARGET_QUERY_SCHEMA = "p9_s5c2_action_target_query_v1"
ACTION_TARGET_SELECTION_SCHEMA = "p9_s5c2_action_target_selection_v1"
_SELECTION_CONTEXT_ISSUER = object()


def action_target_state_revision(state: BattleState) -> str:
    payload = json.dumps(
        state.snapshot().to_json(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"state:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _fingerprint(prefix: str, value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()}"


def _identity_tuple(value: object, label: str, *, sorted_values: bool) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(f"{label} must be a tuple")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(f"{label} must be a tuple") from exc
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"{label} contains an invalid identity")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} contains duplicate identities")
    if sorted_values and values != tuple(sorted(values)):
        raise ValueError(f"{label} must use canonical order")
    return values


@dataclass(frozen=True)
class ActionTargetQuery:
    status: Literal["resolved", "blocked"]
    actor_id: str
    action_id: str
    action_level: int
    state_revision: str
    contract_id: str = ""
    contract_fingerprint: str = ""
    selection_mode: Literal["", "explicit", "automatic"] = ""
    selection_min: int | None = None
    selection_max: int | None = None
    candidate_ids: tuple[str, ...] = ()
    automatic_target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    query_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not ActionTargetQuery:
            raise TypeError("action target query must not be subclassed")
        if self.status not in {"resolved", "blocked"}:
            raise ValueError("action target query status is invalid")
        if not isinstance(self.actor_id, str) or not self.actor_id:
            raise ValueError("action target query actor identity is required")
        if not isinstance(self.action_id, str) or not self.action_id:
            raise ValueError("action target query action identity is required")
        if (
            not isinstance(self.action_level, int)
            or isinstance(self.action_level, bool)
            or self.action_level <= 0
        ):
            raise ValueError("action target query level is invalid")
        if not isinstance(self.state_revision, str) or not self.state_revision.startswith("state:"):
            raise ValueError("action target query state revision is invalid")
        candidates = _identity_tuple(
            self.candidate_ids,
            "action target candidates",
            sorted_values=True,
        )
        automatic = _identity_tuple(
            self.automatic_target_ids,
            "automatic action targets",
            sorted_values=True,
        )
        if self.status == "blocked":
            if (
                not self.blocked_reason
                or self.contract_id
                or self.contract_fingerprint
                or self.selection_mode
                or self.selection_min is not None
                or self.selection_max is not None
                or candidates
                or automatic
            ):
                raise ValueError("blocked action target query carries executable payload")
        else:
            if self.blocked_reason:
                raise ValueError("resolved action target query carries a blocker")
            if not self.contract_id or not self.contract_fingerprint:
                raise ValueError("resolved action target query lacks contract identity")
            if self.selection_mode not in {"explicit", "automatic"}:
                raise ValueError("resolved action target selection mode is invalid")
            if (
                not isinstance(self.selection_min, int)
                or isinstance(self.selection_min, bool)
                or not isinstance(self.selection_max, int)
                or isinstance(self.selection_max, bool)
                or self.selection_min < 0
                or self.selection_max < self.selection_min
                or not candidates
            ):
                raise ValueError("resolved action target cardinality is invalid")
            if self.selection_mode == "automatic":
                if (self.selection_min, self.selection_max) != (0, 0) or automatic != candidates:
                    raise ValueError("automatic action target query is inconsistent")
            elif automatic or self.selection_min != 1 or self.selection_max < 1:
                raise ValueError("explicit action target query is inconsistent")
        identity = {
            "schema_version": ACTION_TARGET_QUERY_SCHEMA,
            "status": self.status,
            "actor_id": self.actor_id,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "state_revision": self.state_revision,
            "contract_id": self.contract_id,
            "contract_fingerprint": self.contract_fingerprint,
            "selection_mode": self.selection_mode,
            "selection_min": self.selection_min,
            "selection_max": self.selection_max,
            "candidate_ids": list(candidates),
            "automatic_target_ids": list(automatic),
            "blocked_reason": self.blocked_reason,
        }
        object.__setattr__(self, "candidate_ids", candidates)
        object.__setattr__(self, "automatic_target_ids", automatic)
        object.__setattr__(self, "query_fingerprint", _fingerprint("target_query", identity))

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": ACTION_TARGET_QUERY_SCHEMA,
            "status": self.status,
            "actor_id": self.actor_id,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "state_revision": self.state_revision,
            "contract_id": self.contract_id,
            "contract_fingerprint": self.contract_fingerprint,
            "selection_mode": self.selection_mode,
            "selection_min": self.selection_min,
            "selection_max": self.selection_max,
            "candidate_ids": list(self.candidate_ids),
            "automatic_target_ids": list(self.automatic_target_ids),
            "blocked_reason": self.blocked_reason,
            "query_fingerprint": self.query_fingerprint,
        }


@dataclass(frozen=True)
class AcceptedActionTargetSelection:
    actor_id: str
    action_id: str
    action_level: int
    state_revision: str
    contract_id: str
    contract_fingerprint: str
    query_fingerprint: str
    selection_mode: Literal["explicit", "automatic"]
    candidate_ids: tuple[str, ...]
    submitted_target_ids: tuple[str, ...]
    selected_target_ids: tuple[str, ...]
    selection_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not AcceptedActionTargetSelection:
            raise TypeError("accepted action target selection must not be subclassed")
        if not all(
            isinstance(value, str) and value
            for value in (
                self.actor_id,
                self.action_id,
                self.state_revision,
                self.contract_id,
                self.contract_fingerprint,
                self.query_fingerprint,
            )
        ):
            raise ValueError("accepted action target selection identity is incomplete")
        if (
            not isinstance(self.action_level, int)
            or isinstance(self.action_level, bool)
            or self.action_level <= 0
        ):
            raise ValueError("accepted action target selection level is invalid")
        if self.selection_mode not in {"explicit", "automatic"}:
            raise ValueError("accepted action target selection mode is invalid")
        candidates = _identity_tuple(
            self.candidate_ids,
            "accepted action target candidates",
            sorted_values=True,
        )
        submitted = _identity_tuple(
            self.submitted_target_ids,
            "submitted action targets",
            sorted_values=False,
        )
        selected = _identity_tuple(
            self.selected_target_ids,
            "selected action targets",
            sorted_values=False,
        )
        if not candidates or not selected or not set(selected).issubset(candidates):
            raise ValueError("accepted action target selection is outside its candidates")
        if self.selection_mode == "automatic":
            if submitted or selected != candidates:
                raise ValueError("automatic action target selection is inconsistent")
        elif submitted != selected:
            raise ValueError("explicit action target submission is inconsistent")
        identity = {
            "schema_version": ACTION_TARGET_SELECTION_SCHEMA,
            "actor_id": self.actor_id,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "state_revision": self.state_revision,
            "contract_id": self.contract_id,
            "contract_fingerprint": self.contract_fingerprint,
            "query_fingerprint": self.query_fingerprint,
            "selection_mode": self.selection_mode,
            "candidate_ids": list(candidates),
            "submitted_target_ids": list(submitted),
            "selected_target_ids": list(selected),
        }
        object.__setattr__(self, "candidate_ids", candidates)
        object.__setattr__(self, "submitted_target_ids", submitted)
        object.__setattr__(self, "selected_target_ids", selected)
        object.__setattr__(
            self,
            "selection_fingerprint",
            _fingerprint("target_selection", identity),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": ACTION_TARGET_SELECTION_SCHEMA,
            "actor_id": self.actor_id,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "state_revision": self.state_revision,
            "contract_id": self.contract_id,
            "contract_fingerprint": self.contract_fingerprint,
            "query_fingerprint": self.query_fingerprint,
            "selection_mode": self.selection_mode,
            "candidate_ids": list(self.candidate_ids),
            "submitted_target_ids": list(self.submitted_target_ids),
            "selected_target_ids": list(self.selected_target_ids),
            "selection_fingerprint": self.selection_fingerprint,
        }


@dataclass(frozen=True)
class _SelectionContextSeal:
    issuer: object = field(repr=False, compare=False)
    claims: tuple[object, ...]


@dataclass(frozen=True)
class ActionTargetSelectionContext:
    accepted: AcceptedActionTargetSelection
    impact_sub_target: Literal["default", "adjacent", "all_teammate"]
    adjacent_target_count: int | None
    dynamic_target: bool
    context_fingerprint: str = field(init=False)
    _seal: _SelectionContextSeal | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self) is not ActionTargetSelectionContext:
            raise TypeError("action target selection context must not be subclassed")
        if type(self.accepted) is not AcceptedActionTargetSelection:
            raise TypeError("selection context requires an exact accepted selection")
        if self.impact_sub_target not in {"default", "adjacent", "all_teammate"}:
            raise ValueError("selection context impact sub-target is invalid")
        if self.adjacent_target_count is not None and (
            not isinstance(self.adjacent_target_count, int)
            or isinstance(self.adjacent_target_count, bool)
            or self.adjacent_target_count <= 0
            or self.impact_sub_target != "adjacent"
        ):
            raise ValueError("selection context adjacent count is invalid")
        if type(self.dynamic_target) is not bool:
            raise TypeError("selection context dynamic target flag must be boolean")
        identity = {
            "accepted": self.accepted.to_json(),
            "impact_sub_target": self.impact_sub_target,
            "adjacent_target_count": self.adjacent_target_count,
            "dynamic_target": self.dynamic_target,
        }
        object.__setattr__(
            self,
            "context_fingerprint",
            _fingerprint("target_context", identity),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "accepted": self.accepted.to_json(),
            "impact_sub_target": self.impact_sub_target,
            "adjacent_target_count": self.adjacent_target_count,
            "dynamic_target": self.dynamic_target,
            "context_fingerprint": self.context_fingerprint,
        }


@dataclass(frozen=True)
class ActionTargetSelectionDecision:
    status: Literal["accepted", "blocked"]
    query: ActionTargetQuery
    context: ActionTargetSelectionContext | None = None
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not ActionTargetSelectionDecision:
            raise TypeError("action target selection decision must not be subclassed")
        if type(self.query) is not ActionTargetQuery:
            raise TypeError("action target selection decision requires an exact query")
        if self.status == "accepted":
            if (
                type(self.context) is not ActionTargetSelectionContext
                or self.blocked_reason
                or not self.query.resolved
            ):
                raise ValueError("accepted action target selection decision is inconsistent")
        elif self.status == "blocked":
            if self.context is not None or not self.blocked_reason:
                raise ValueError("blocked action target selection decision is inconsistent")
        else:
            raise ValueError("action target selection decision status is invalid")

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status": self.status,
            "query": self.query.to_json(),
            "context": self.context.to_json() if self.context is not None else None,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ActionTargetImpactResult:
    status: Literal["resolved", "blocked"]
    context_fingerprint: str
    resolution: TargetResolution
    blocked_reason: str = ""
    impact_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not ActionTargetImpactResult:
            raise TypeError("action target impact result must not be subclassed")
        if not isinstance(self.context_fingerprint, str) or not self.context_fingerprint:
            raise ValueError("action target impact context identity is required")
        if type(self.resolution) is not TargetResolution:
            raise TypeError("action target impact requires an exact target resolution")
        if self.status == "resolved":
            if self.blocked_reason or not self.resolution.selected or not self.resolution.impact_group:
                raise ValueError("resolved action target impact is inconsistent")
        elif self.status == "blocked":
            if not self.blocked_reason or self.resolution.selected or self.resolution.impact_group:
                raise ValueError("blocked action target impact carries executable targets")
        else:
            raise ValueError("action target impact status is invalid")
        identity = {
            "status": self.status,
            "context_fingerprint": self.context_fingerprint,
            "resolution": self.resolution.to_json(),
            "blocked_reason": self.blocked_reason,
        }
        object.__setattr__(
            self,
            "impact_fingerprint",
            _fingerprint("target_impact", identity),
        )

    @property
    def ok(self) -> bool:
        return self.status == "resolved"

    @property
    def errors(self) -> tuple[str, ...]:
        return () if self.ok else (self.blocked_reason,)

    @property
    def rng_events(self) -> tuple[RNGEvent, ...]:
        return ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status": self.status,
            "context_fingerprint": self.context_fingerprint,
            "resolution": self.resolution.to_json(),
            "blocked_reason": self.blocked_reason,
            "impact_fingerprint": self.impact_fingerprint,
        }


class ActionTargetSelectionSystem:
    """The single producer of action target queries and accepted contexts."""

    def __init__(self, rules: RuleBook) -> None:
        self.rules = rules
        self.lifecycle = UnitLifecycleSystem()
        self.relations = EntityRelationResolver()
        self.expressions = TargetSystem(rules)

    def query(
        self,
        state: BattleState,
        actor_id: str,
        action_id: str,
        action_level: int,
    ) -> ActionTargetQuery:
        revision = action_target_state_revision(state)
        actor = state.units.get(actor_id)
        if actor is None:
            return self._blocked_query(
                actor_id,
                action_id,
                action_level,
                revision,
                "action_target_actor_missing",
            )
        actor_ok, actor_reason = self.lifecycle.can_act(state, actor_id)
        if not actor_ok:
            return self._blocked_query(
                actor_id,
                action_id,
                action_level,
                revision,
                f"action_target_actor_{actor_reason}",
            )
        contract_query = self.rules.action_target_contract(action_id, action_level)
        if contract_query.resolution_status != "resolved" or contract_query.value is None:
            return self._blocked_query(
                actor_id,
                action_id,
                action_level,
                revision,
                contract_query.blocked_reason or "action_target_contract_blocked",
            )
        contract = contract_query.value
        if contract.allow_duplicates:
            return self._blocked_query(
                actor_id,
                action_id,
                action_level,
                revision,
                "action_target_duplicate_selection_semantics_not_admitted",
            )
        candidates, reason = self._candidate_ids(state, actor_id, contract)
        if reason:
            return self._blocked_query(
                actor_id,
                action_id,
                action_level,
                revision,
                reason,
            )
        if not candidates:
            return self._blocked_query(
                actor_id,
                action_id,
                action_level,
                revision,
                "action_target_candidates_empty",
            )
        automatic = candidates if contract.selection_mode == "automatic" else ()
        return ActionTargetQuery(
            status="resolved",
            actor_id=actor_id,
            action_id=action_id,
            action_level=action_level,
            state_revision=revision,
            contract_id=contract.contract_id,
            contract_fingerprint=contract.contract_fingerprint,
            selection_mode=contract.selection_mode,
            selection_min=contract.selection_min,
            selection_max=contract.selection_max,
            candidate_ids=candidates,
            automatic_target_ids=automatic,
        )

    def accept(
        self,
        state: BattleState,
        query: ActionTargetQuery,
        submitted_target_ids: tuple[str, ...],
    ) -> ActionTargetSelectionDecision:
        if type(query) is not ActionTargetQuery:
            raise TypeError("action target acceptance requires an exact query")
        try:
            submitted = _identity_tuple(
                submitted_target_ids,
                "submitted action targets",
                sorted_values=False,
            )
        except (TypeError, ValueError) as exc:
            return ActionTargetSelectionDecision(
                status="blocked",
                query=query,
                blocked_reason=str(exc),
            )
        current = self.query(
            state,
            query.actor_id,
            query.action_id,
            query.action_level,
        )
        if not query.resolved:
            return ActionTargetSelectionDecision(
                status="blocked",
                query=current,
                blocked_reason=query.blocked_reason or "action_target_query_blocked",
            )
        if current.query_fingerprint != query.query_fingerprint:
            return ActionTargetSelectionDecision(
                status="blocked",
                query=current,
                blocked_reason="action_target_query_stale",
            )
        contract_query = self.rules.action_target_contract(
            query.action_id,
            query.action_level,
        )
        contract = contract_query.value
        if contract_query.resolution_status != "resolved" or contract is None:
            return ActionTargetSelectionDecision(
                status="blocked",
                query=current,
                blocked_reason=contract_query.blocked_reason or "action_target_contract_blocked",
            )
        if query.selection_mode == "automatic":
            if submitted:
                return ActionTargetSelectionDecision(
                    status="blocked",
                    query=current,
                    blocked_reason="automatic_action_rejects_submitted_targets",
                )
            selected = query.automatic_target_ids
        else:
            count = len(submitted)
            minimum = query.selection_min or 0
            maximum = query.selection_max or 0
            if count < minimum:
                return ActionTargetSelectionDecision(
                    status="blocked",
                    query=current,
                    blocked_reason=f"action_target_selection_too_few:{count}:{minimum}",
                )
            if count > maximum:
                return ActionTargetSelectionDecision(
                    status="blocked",
                    query=current,
                    blocked_reason=f"action_target_selection_too_many:{count}:{maximum}",
                )
            unknown = tuple(item for item in submitted if item not in query.candidate_ids)
            if unknown:
                return ActionTargetSelectionDecision(
                    status="blocked",
                    query=current,
                    blocked_reason=f"action_target_not_in_candidates:{','.join(unknown)}",
                )
            selected = submitted
        accepted = AcceptedActionTargetSelection(
            actor_id=query.actor_id,
            action_id=query.action_id,
            action_level=query.action_level,
            state_revision=query.state_revision,
            contract_id=query.contract_id,
            contract_fingerprint=query.contract_fingerprint,
            query_fingerprint=query.query_fingerprint,
            selection_mode=query.selection_mode,  # type: ignore[arg-type]
            candidate_ids=query.candidate_ids,
            submitted_target_ids=submitted,
            selected_target_ids=selected,
        )
        unsigned = ActionTargetSelectionContext(
            accepted=accepted,
            impact_sub_target=contract.impact_sub_target,  # type: ignore[arg-type]
            adjacent_target_count=contract.adjacent_target_count,
            dynamic_target=bool(contract.dynamic_target),
        )
        context = ActionTargetSelectionContext(
            accepted=accepted,
            impact_sub_target=unsigned.impact_sub_target,
            adjacent_target_count=unsigned.adjacent_target_count,
            dynamic_target=unsigned.dynamic_target,
            _seal=_SelectionContextSeal(
                issuer=_SELECTION_CONTEXT_ISSUER,
                claims=self._context_claims(unsigned),
            ),
        )
        return ActionTargetSelectionDecision(
            status="accepted",
            query=current,
            context=context,
        )

    def context_blocked_reason(
        self,
        state: BattleState,
        command: ActionCommand,
        context: ActionTargetSelectionContext | None,
    ) -> str:
        identity_reason = self.context_identity_blocked_reason(command, context)
        if identity_reason:
            return identity_reason
        assert context is not None
        if context.accepted.state_revision != action_target_state_revision(state):
            return "action_target_selection_state_mismatch"
        current = self.query(
            state,
            command.actor_id,
            command.action_id,
            command.action_level,
        )
        if not current.resolved:
            return current.blocked_reason or "action_target_query_blocked"
        if current.query_fingerprint != context.accepted.query_fingerprint:
            return "action_target_selection_query_mismatch"
        contract_query = self.rules.action_target_contract(
            command.action_id,
            command.action_level,
        )
        contract = contract_query.value
        if contract_query.resolution_status != "resolved" or contract is None:
            return contract_query.blocked_reason or "action_target_contract_blocked"
        if (
            contract.contract_id != context.accepted.contract_id
            or contract.contract_fingerprint != context.accepted.contract_fingerprint
            or contract.impact_sub_target != context.impact_sub_target
            or contract.adjacent_target_count != context.adjacent_target_count
            or bool(contract.dynamic_target) != context.dynamic_target
        ):
            return "action_target_selection_contract_mismatch"
        return ""

    def context_identity_blocked_reason(
        self,
        command: ActionCommand,
        context: ActionTargetSelectionContext | None,
    ) -> str:
        if type(context) is not ActionTargetSelectionContext:
            return "action_target_selection_context_required"
        seal = context._seal
        if (
            type(seal) is not _SelectionContextSeal
            or seal.issuer is not _SELECTION_CONTEXT_ISSUER
            or seal.claims != self._context_claims(context)
        ):
            return "action_target_selection_context_not_issued"
        accepted = context.accepted
        if accepted.actor_id != command.actor_id:
            return "action_target_selection_actor_mismatch"
        if (
            accepted.action_id != command.action_id
            or accepted.action_level != command.action_level
        ):
            return "action_target_selection_action_mismatch"
        if (
            accepted.selection_mode == "explicit"
            and accepted.submitted_target_ids != command.target_ids
        ):
            return "action_target_selection_submission_mismatch"
        if accepted.selection_mode == "automatic" and command.target_ids:
            return "automatic_action_rejects_submitted_targets"
        return ""

    def resolve_impact(
        self,
        state: BattleState,
        command: ActionCommand,
        context: ActionTargetSelectionContext,
        action_event: ActionEventIR,
    ) -> ActionTargetImpactResult:
        if type(action_event) is not ActionEventIR:
            raise TypeError("action target impact requires an exact action event")
        reason = self.context_identity_blocked_reason(command, context)
        if reason:
            return self._blocked_impact(command, context, reason)
        contract_query = self.rules.action_target_contract(
            command.action_id,
            command.action_level,
        )
        contract = contract_query.value
        if contract_query.resolution_status != "resolved" or contract is None:
            return self._blocked_impact(
                command,
                context,
                contract_query.blocked_reason or "action_target_contract_blocked",
            )
        if contract.contract_fingerprint != context.accepted.contract_fingerprint:
            return self._blocked_impact(
                command,
                context,
                "action_target_impact_contract_mismatch",
            )
        target_mode = str(action_event.target_mode or "")
        if target_mode == "bounce":
            actor = state.units.get(command.actor_id)
            bounce_policy = resolve_action_bounce_policy(
                self.rules,
                command.action_id,
                command.action_level,
                actor_entity_ref=actor.template_id if actor is not None else "",
            )
            if not bounce_policy.resolved:
                return self._blocked_impact(
                    command,
                    context,
                    bounce_policy.blocked_reason,
                )
        elif context.dynamic_target:
            return self._blocked_impact(
                command,
                context,
                "action_dynamic_target_control_flow_deferred_to_p9_s8",
            )
        if target_mode not in {"single", "self_or_team", "aoe", "blast", "bounce"}:
            return self._blocked_impact(
                command,
                context,
                f"action_impact_mode_not_supported:{target_mode or 'missing'}",
            )
        selected = context.accepted.selected_target_ids
        impact = list(selected)
        adjacent: list[str] = []
        teammate: list[str] = []
        if context.impact_sub_target == "all_teammate":
            for target_id in selected:
                result = self.relations.resolve(
                    state,
                    "team.same",
                    TargetEvaluationContext(caster_id=command.actor_id),
                    subject_ids=(target_id,),
                )
                if result.blocked:
                    return self._blocked_impact(command, context, result.blocked_reason)
                teammate.extend(result.target_ids)
            impact = list(_ordered_unique((*selected, *teammate)))
        elif context.impact_sub_target == "adjacent" or target_mode == "blast":
            limit = context.adjacent_target_count or 2
            for target_id in selected:
                result = self.relations.resolve(
                    state,
                    "formation.adjacent",
                    TargetEvaluationContext(caster_id=command.actor_id),
                    subject_ids=(target_id,),
                )
                if result.blocked:
                    return self._blocked_impact(command, context, result.blocked_reason)
                adjacent.extend(result.target_ids[:limit])
            impact = list(_ordered_unique((*selected, *adjacent)))
        elif target_mode == "aoe":
            impact = list(context.accepted.candidate_ids)
        groups = {
            "primary": selected[:1],
            "selected": selected,
            "impact": tuple(impact),
        }
        if adjacent:
            groups["adjacent"] = tuple(
                item for item in _ordered_unique(adjacent) if item not in selected
            )
        if teammate:
            groups["all_teammate"] = _ordered_unique(teammate)
        resolution = TargetResolution(
            requested=command.target_ids,
            selectable=context.accepted.candidate_ids,
            legal=selected,
            primary=selected[0] if selected else None,
            impact_group=tuple(impact),
            selected=selected,
            rejected=(),
            reason="action_target_selection_and_impact_resolved",
            source="action_target_selection_system",
            metadata={
                "selection_context_fingerprint": context.context_fingerprint,
                "selection_fingerprint": context.accepted.selection_fingerprint,
                "contract_fingerprint": context.accepted.contract_fingerprint,
                "query_fingerprint": context.accepted.query_fingerprint,
                "target_groups": {
                    key: list(value) for key, value in sorted(groups.items())
                },
                "impact_source": {
                    "action_event_id": action_event.action_event_id,
                    "action_event_source": action_event.source.to_json(),
                    "target_mode": target_mode,
                    "impact_sub_target": context.impact_sub_target,
                    "adjacent_target_count": context.adjacent_target_count,
                    "bounce_policy_id": (
                        bounce_policy.policy.bounce_policy_id
                        if target_mode == "bounce"
                        and bounce_policy.policy is not None
                        else ""
                    ),
                    "bounce_policy_source": (
                        bounce_policy.policy.source.to_json()
                        if target_mode == "bounce"
                        and bounce_policy.policy is not None
                        else {}
                    ),
                },
            },
        )
        return ActionTargetImpactResult(
            status="resolved",
            context_fingerprint=context.context_fingerprint,
            resolution=resolution,
        )

    def _candidate_ids(
        self,
        state: BattleState,
        actor_id: str,
        contract: ActionTargetContractIR,
    ) -> tuple[tuple[str, ...], str]:
        context = TargetEvaluationContext(
            caster_id=actor_id,
            effect_owner_id=actor_id,
            turn_owner_id=_optional_identity(state.global_flags.get("turn_owner_id")),
        )
        if contract.candidate_relation == "self":
            candidates = (actor_id,)
        else:
            relation = (
                "team.opposing"
                if contract.candidate_relation == "enemy"
                else "team.same"
            )
            relation_result = self.relations.resolve(
                state,
                relation,  # type: ignore[arg-type]
                context,
                subject_ids=(actor_id,),
                options={
                    "include_limbo": contract.candidate_alive_state == "alive_or_limbo",
                },
            )
            if relation_result.blocked:
                return (), relation_result.blocked_reason
            candidates = relation_result.target_ids
        candidates, reason = self._apply_servant_policy(
            state,
            actor_id,
            contract,
            candidates,
        )
        if reason:
            return (), reason
        if contract.avoid_self:
            candidates = tuple(item for item in candidates if item != actor_id)
        if contract.selection_filter is not None:
            filter_result = self.expressions.resolve_target_expression(
                state,
                contract.selection_filter,
                context=context,
            )
            if filter_result.blocked:
                return (), filter_result.blocked_reason
            if filter_result.rng_events:
                return (), "action_target_filter_rng_deferred_to_p9_s5d"
            admitted = set(filter_result.target_ids)
            candidates = tuple(item for item in candidates if item in admitted)
        return tuple(sorted(candidates)), ""

    def _apply_servant_policy(
        self,
        state: BattleState,
        actor_id: str,
        contract: ActionTargetContractIR,
        candidates: tuple[str, ...],
    ) -> tuple[tuple[str, ...], str]:
        has_servant_units = any(
            str(unit.flags.get("summon_kind") or "") == "servant"
            and unit.lifecycle_status != "removed"
            for unit in state.units.values()
        )
        requires_runtime = has_servant_units or any(
            (
                contract.friend_servant_policy != "default",
                contract.enemy_servant_policy != "default",
                contract.servant_selection != "none",
                bool(contract.merge_servant_selection_to_summoner),
            )
        )
        if not requires_runtime:
            return candidates, ""
        runtime = state.global_flags.get("summon_runtime")
        validation = validate_summon_runtime(runtime, units=state.units)
        if not validation.ok:
            return (), validation.reason or "summon_runtime_invalid"
        assert isinstance(runtime, Mapping)
        raw_servants = runtime.get("servants")
        if not isinstance(raw_servants, Mapping):
            return (), "summon_runtime_servants_malformed"
        servant_entries = {
            unit_id: entry
            for unit_id, entry in raw_servants.items()
            if isinstance(unit_id, str)
            and isinstance(entry, Mapping)
            and entry.get("status") == "active"
        }
        selected = list(candidates)
        if contract.candidate_relation == "ally_or_self":
            if contract.friend_servant_policy == "forbidden":
                selected = [item for item in selected if item not in servant_entries]
            elif contract.friend_servant_policy == "allow_when_summoner_unselectable":
                base = set(selected)
                selected = [
                    item
                    for item in selected
                    if item not in servant_entries
                    or str(servant_entries[item].get("summoner_id") or "") not in base
                ]
        elif (
            contract.candidate_relation == "enemy"
            and contract.enemy_servant_policy == "forbidden"
        ):
            selected = [item for item in selected if item not in servant_entries]
        if contract.merge_servant_selection_to_summoner:
            base = set(selected)
            merged: list[str] = []
            for item in selected:
                entry = servant_entries.get(item)
                if entry is None:
                    merged.append(item)
                    continue
                summoner_id = str(entry.get("summoner_id") or "")
                if not summoner_id or summoner_id not in state.units:
                    return (), "action_target_servant_summoner_missing"
                merged.append(summoner_id if summoner_id in base else item)
            selected = list(_ordered_unique(merged))
        return tuple(selected), ""

    @staticmethod
    def _blocked_query(
        actor_id: str,
        action_id: str,
        action_level: int,
        revision: str,
        reason: str,
    ) -> ActionTargetQuery:
        return ActionTargetQuery(
            status="blocked",
            actor_id=actor_id,
            action_id=action_id,
            action_level=action_level,
            state_revision=revision,
            blocked_reason=reason,
        )

    @staticmethod
    def _context_claims(context: ActionTargetSelectionContext) -> tuple[object, ...]:
        return (
            context.accepted.selection_fingerprint,
            context.impact_sub_target,
            context.adjacent_target_count,
            context.dynamic_target,
            context.context_fingerprint,
        )

    @staticmethod
    def _blocked_impact(
        command: ActionCommand,
        context: ActionTargetSelectionContext,
        reason: str,
    ) -> ActionTargetImpactResult:
        return ActionTargetImpactResult(
            status="blocked",
            context_fingerprint=context.context_fingerprint,
            resolution=TargetResolution(
                requested=command.target_ids,
                selectable=context.accepted.candidate_ids,
                selected=(),
                impact_group=(),
                rejected=command.target_ids,
                reason=reason,
                source="action_target_selection_system",
                metadata={
                    "selection_context_fingerprint": context.context_fingerprint,
                    "blocked_reason": reason,
                },
            ),
            blocked_reason=reason,
        )


def _ordered_unique(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _optional_identity(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "ACTION_TARGET_QUERY_SCHEMA",
    "ACTION_TARGET_SELECTION_SCHEMA",
    "AcceptedActionTargetSelection",
    "ActionTargetImpactResult",
    "ActionTargetQuery",
    "ActionTargetSelectionContext",
    "ActionTargetSelectionDecision",
    "ActionTargetSelectionSystem",
    "action_target_state_revision",
]
