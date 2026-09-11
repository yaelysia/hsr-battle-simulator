from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..core.model import ActionCommand, BattleState, JSONValue
from ..rules.ir import ActionAdmissionIR, AbilityTaskIR
from ..rules.rulebook import RuleBook
from ..rules.task_graph import TaskGraphIR
from .action_preflight import (
    action_binding_blocked_reason,
    action_event_blocked_reason,
    action_resource_blocked_reason,
    action_resource_plan,
    combined_blocked_reason,
)
from .resource import ResourceSystem
from .status import status_control_gate_for_actor
from .unit_lifecycle import UnitLifecycleSystem
from .ability_task_contract import (
    ability_task_runtime_blocked_reason,
    is_process_only_ability_task,
)


ACTION_SUBMISSION_CONTRACT_SCHEMA = "p7_s6_action_submission_contract_v1"
_ACTION_AUTHORIZATION_ISSUER = object()


@dataclass(frozen=True)
class _ActionAuthorizationSeal:
    issuer: object = field(repr=False, compare=False)
    claims: tuple[object, ...]


@dataclass(frozen=True)
class ActionSubmissionAuthorization:
    submission_mode: str
    actor_id: str
    owner_entity_ref: str
    action_id: str
    action_level: int
    window: str
    source_id: str
    state_revision: str = ""
    selection_context_fingerprint: str = ""
    _seal: _ActionAuthorizationSeal | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self) is not ActionSubmissionAuthorization:
            raise TypeError("action submission authorization must not be subclassed")
        if not all(
            isinstance(value, str) and value
            for value in (
                self.submission_mode,
                self.actor_id,
                self.owner_entity_ref,
                self.action_id,
                self.window,
                self.source_id,
                self.state_revision,
                self.selection_context_fingerprint,
            )
        ):
            raise ValueError("action submission authorization identity is incomplete")
        if (
            not isinstance(self.action_level, int)
            or isinstance(self.action_level, bool)
            or self.action_level <= 0
        ):
            raise ValueError("action submission authorization level is invalid")

    def blocked_reason(
        self,
        command: ActionCommand,
        actual_owner_entity_ref: str,
        actual_state_revision: str,
        actual_selection_context_fingerprint: str,
    ) -> str:
        if not _action_authorization_seal_valid(self):
            return "action_submission_authorization_not_issued"
        if self.state_revision != actual_state_revision:
            return "action_submission_authorization_state_mismatch"
        if self.submission_mode not in {"external_turn", "queue", "insert_window", "trigger", "out_of_combat"}:
            return "action_submission_authorization_mode_invalid"
        if self.actor_id != command.actor_id:
            return "action_submission_authorization_actor_mismatch"
        if self.owner_entity_ref != actual_owner_entity_ref:
            return "action_submission_authorization_owner_mismatch"
        if self.action_id != command.action_id or self.action_level != command.action_level:
            return "action_submission_authorization_action_mismatch"
        if not self.window or not self.source_id or not self.selection_context_fingerprint:
            return "action_submission_authorization_identity_missing"
        if self.selection_context_fingerprint != actual_selection_context_fingerprint:
            return "action_submission_authorization_selection_mismatch"
        return ""


def _issue_action_submission_authorization(
    *,
    state: BattleState,
    submission_mode: str,
    actor_id: str,
    owner_entity_ref: str,
    action_id: str,
    action_level: int,
    window: str,
    source_id: str,
    selection_context_fingerprint: str,
) -> ActionSubmissionAuthorization:
    authorization = ActionSubmissionAuthorization(
        submission_mode=submission_mode,
        actor_id=actor_id,
        owner_entity_ref=owner_entity_ref,
        action_id=action_id,
        action_level=action_level,
        window=window,
        source_id=source_id,
        state_revision=_action_state_revision(state),
        selection_context_fingerprint=selection_context_fingerprint,
    )
    return ActionSubmissionAuthorization(
        **_action_authorization_payload(authorization),
        _seal=_ActionAuthorizationSeal(
            issuer=_ACTION_AUTHORIZATION_ISSUER,
            claims=_action_authorization_claims(authorization),
        ),
    )


def _action_state_revision(state: BattleState) -> str:
    payload = json.dumps(
        state.snapshot().to_json(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"state:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _action_authorization_payload(
    authorization: ActionSubmissionAuthorization,
) -> dict[str, object]:
    return {
        "submission_mode": authorization.submission_mode,
        "actor_id": authorization.actor_id,
        "owner_entity_ref": authorization.owner_entity_ref,
        "action_id": authorization.action_id,
        "action_level": authorization.action_level,
        "window": authorization.window,
        "source_id": authorization.source_id,
        "state_revision": authorization.state_revision,
        "selection_context_fingerprint": authorization.selection_context_fingerprint,
    }


def _action_authorization_claims(
    authorization: ActionSubmissionAuthorization,
) -> tuple[object, ...]:
    payload = _action_authorization_payload(authorization)
    return tuple(payload[key] for key in (
        "submission_mode",
        "actor_id",
        "owner_entity_ref",
        "action_id",
        "action_level",
        "window",
        "source_id",
        "state_revision",
        "selection_context_fingerprint",
    ))


def _action_authorization_seal_valid(authorization: ActionSubmissionAuthorization) -> bool:
    seal = authorization._seal
    return (
        type(seal) is _ActionAuthorizationSeal
        and seal.issuer is _ACTION_AUTHORIZATION_ISSUER
        and seal.claims == _action_authorization_claims(authorization)
    )


@dataclass(frozen=True)
class ActionContractDecision:
    ok: bool
    actor_id: str
    owner_entity_ref: str
    action_id: str
    action_level: int
    submission_mode: str
    current_window: str
    admission: ActionAdmissionIR | None = None
    blocked_reason: str = ""
    resource_status: str = "not_checked"
    resource_blocked_reason: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": ACTION_SUBMISSION_CONTRACT_SCHEMA,
            "ok": self.ok,
            "actor_id": self.actor_id,
            "owner_entity_ref": self.owner_entity_ref,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "submission_mode": self.submission_mode,
            "current_window": self.current_window,
            "admission": self.admission.to_json() if self.admission is not None else None,
            "blocked_reason": self.blocked_reason,
            "resource_status": self.resource_status,
            "resource_blocked_reason": self.resource_blocked_reason,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class _FormalActionGraphAdmissionProjection:
    root_graph_ids: tuple[str, ...]
    root_entries: tuple[tuple[str, str, str], ...]
    reachable_task_ids: tuple[str, ...]
    excluded_bound_task_ids: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    blocker_provenance: tuple[dict[str, JSONValue], ...]

    def metadata(self) -> dict[str, JSONValue]:
        return {
            "formal_action_root_graph_ids": list(self.root_graph_ids),
            "formal_action_root_entries": [
                {
                    "phase_id": phase_id,
                    "callback_kind": callback_kind,
                    "graph_id": graph_id,
                }
                for phase_id, callback_kind, graph_id in self.root_entries
            ],
            "formal_action_reachable_task_ids": list(self.reachable_task_ids),
            "formal_action_excluded_bound_task_ids": list(
                self.excluded_bound_task_ids
            ),
            "formal_action_blocker_provenance": list(self.blocker_provenance),
        }


def _stable_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _formal_action_task_graph_projection(
    rules: RuleBook,
    action_id: str,
    action_level: int,
    tasks: tuple[AbilityTaskIR, ...],
) -> _FormalActionGraphAdmissionProjection:
    root_graph_ids: list[str] = []
    root_entries: list[tuple[str, str, str]] = []
    reachable_task_ids: list[str] = []
    blocked_reasons: list[str] = []
    blocker_provenance: list[dict[str, JSONValue]] = []

    def block(
        reason: str,
        *,
        phase_id: str = "",
        callback_kind: str = "",
        graph_id: str = "",
        graph_node_id: str = "",
        task_id: str = "",
        source: str,
    ) -> None:
        stable_reason = reason or "formal_action_task_graph_identity_mismatch"
        if stable_reason not in blocked_reasons:
            blocked_reasons.append(stable_reason)
        row: dict[str, JSONValue] = {
            "reason": stable_reason,
            "source": source,
            "phase_id": phase_id,
            "callback_kind": callback_kind,
            "graph_id": graph_id,
            "graph_node_id": graph_node_id,
            "task_id": task_id,
        }
        if row not in blocker_provenance:
            blocker_provenance.append(row)

    formal_bound_task_ids: list[str] = []
    for task in sorted(tasks, key=lambda item: item.task_id):
        phase = rules.ability_phase(task.phase_id)
        if phase is None:
            block(
                "ability_task_phase_missing",
                phase_id=task.phase_id,
                task_id=task.task_id,
                source="bound_task_phase",
            )
            continue
        if phase.invocation_role != "external_legacy":
            formal_bound_task_ids.append(task.task_id)

    action_phases = tuple(
        sorted(
            rules.ability_phases_for_action(action_id, action_level),
            key=lambda item: item.phase_id,
        )
    )
    roles = {phase.invocation_role for phase in action_phases}
    if "action_root" in roles:
        invalid_roles = sorted(
            roles.difference({"action_root", "nested_only", "non_gameplay_noop"})
        )
        if invalid_roles:
            block(
                f"ability_action_invocation_roles_mixed:{','.join(invalid_roles)}",
                source="action_invocation_role",
            )
            return _FormalActionGraphAdmissionProjection(
                root_graph_ids=(),
                root_entries=(),
                reachable_task_ids=(),
                excluded_bound_task_ids=tuple(sorted(set(formal_bound_task_ids))),
                blocked_reasons=_stable_unique(blocked_reasons),
                blocker_provenance=tuple(blocker_provenance),
            )
    elif "standalone_root" in roles:
        block(
            "standalone_ability_requires_admitted_queue_invocation",
            source="action_invocation_role",
        )
    elif "nested_only" in roles and "external_legacy" not in roles:
        block(
            "ability_nested_only_cannot_be_action_root",
            source="action_invocation_role",
        )
    elif "unbound_definition" in roles:
        block(
            "unbound_ability_not_action_admitted",
            source="action_invocation_role",
        )

    root_phases = tuple(
        phase for phase in action_phases if phase.invocation_role == "action_root"
    )
    if not root_phases:
        return _FormalActionGraphAdmissionProjection(
            root_graph_ids=(),
            root_entries=(),
            reachable_task_ids=(),
            excluded_bound_task_ids=tuple(sorted(set(formal_bound_task_ids))),
            blocked_reasons=_stable_unique(blocked_reasons),
            blocker_provenance=tuple(blocker_provenance),
        )

    pending_graphs: list[tuple[TaskGraphIR, str, str, bool, tuple[str, ...]]] = []
    for phase in root_phases:
        if phase.action_id != action_id or phase.level != action_level:
            block(
                "ability_action_phase_identity_mismatch",
                phase_id=phase.phase_id,
                source="action_root_phase",
            )
            continue
        phase_tasks = rules.ability_tasks_for_phase(phase.phase_id)
        callbacks = tuple(
            sorted({task.callback_kind for task in phase_tasks if task.callback_kind})
        )
        for callback_kind in callbacks:
            selected = tuple(
                task for task in phase_tasks if task.callback_kind == callback_kind
            )
            graph_result = rules.query_formal_task_graph(
                "ability_phase_callback",
                phase.phase_id,
                callback_kind,
                (task.task_id for task in selected),
            )
            graph = graph_result.value
            if graph_result.status != "resolved" or type(graph) is not TaskGraphIR:
                block(
                    graph_result.blocked_reason
                    or "ability_action_task_graph_identity_mismatch",
                    phase_id=phase.phase_id,
                    callback_kind=callback_kind,
                    source="action_root_graph",
                )
                continue
            root_graph_ids.append(graph.graph_id)
            root_entries.append((phase.phase_id, callback_kind, graph.graph_id))
            pending_graphs.append(
                (graph, phase.phase_id, callback_kind, True, (graph.graph_id,))
            )

    visited_graph_ids: set[str] = set()
    nested_edges_by_graph_id: dict[
        str, list[tuple[TaskGraphIR, str, str, str, str]]
    ] = {}
    while pending_graphs:
        graph, expected_phase_id, expected_callback_kind, is_root, active_path = (
            pending_graphs.pop(0)
        )
        if graph.graph_id in visited_graph_ids:
            continue
        visited_graph_ids.add(graph.graph_id)
        expected_phase = rules.ability_phase(expected_phase_id)
        expected_role = "action_root" if is_root else "nested_only"
        if (
            expected_phase is None
            or expected_phase.invocation_role != expected_role
            or graph.entry_kind != "ability_phase_callback"
            or graph.owner_id != expected_phase_id
            or graph.callback_kind != expected_callback_kind
        ):
            block(
                "ability_task_graph_formal_task_identity_mismatch",
                phase_id=expected_phase_id,
                callback_kind=expected_callback_kind,
                graph_id=graph.graph_id,
                source="graph_entry_identity",
            )
            continue

        # TaskGraphIR itself is the structural-topology authority: its constructor
        # rejects cycles, unreachable nodes, dangling children and ambiguous parents.
        # Admission therefore scans the canonical node set instead of re-walking
        # branch edges or evaluating runtime branch/condition/count/target hooks.
        for node in graph.nodes:
            task = rules.ability_task(node.formal_task_id)
            if (
                task is None
                or task.phase_id != graph.owner_id
                or task.callback_kind != graph.callback_kind
            ):
                block(
                    "ability_task_graph_formal_task_identity_mismatch",
                    phase_id=graph.owner_id,
                    callback_kind=graph.callback_kind,
                    graph_id=graph.graph_id,
                    graph_node_id=node.graph_node_id,
                    task_id=node.formal_task_id,
                    source="graph_task_identity",
                )
                continue

            reachable_task_ids.append(task.task_id)
            if node.materialization_status != "materialized":
                block(
                    node.status_reason or "ability_task_graph_node_not_materialized",
                    phase_id=graph.owner_id,
                    callback_kind=graph.callback_kind,
                    graph_id=graph.graph_id,
                    graph_node_id=node.graph_node_id,
                    task_id=task.task_id,
                    source="node_materialization",
                )
            runtime_reason = ability_task_runtime_blocked_reason(
                rules,
                task,
                topology_authority="task_graph",
            )
            if runtime_reason:
                block(
                    runtime_reason,
                    phase_id=graph.owner_id,
                    callback_kind=graph.callback_kind,
                    graph_id=graph.graph_id,
                    graph_node_id=node.graph_node_id,
                    task_id=task.task_id,
                    source="ability_task_runtime_support",
                )
            if not is_process_only_ability_task(task):
                unresolved = tuple(
                    reference
                    for reference in node.references
                    if reference.resolution_status != "resolved"
                )
                if unresolved:
                    block(
                        unresolved[0].blocked_reason
                        or "ability_task_graph_leaf_reference_not_resolved",
                        phase_id=graph.owner_id,
                        callback_kind=graph.callback_kind,
                        graph_id=graph.graph_id,
                        graph_node_id=node.graph_node_id,
                        task_id=task.task_id,
                        source="graph_reference",
                    )

            process_only = is_process_only_ability_task(task)
            nested_node = node.node_kind == "ability_call" or (
                task.opcode == "TriggerAbility" and not process_only
            )
            if not nested_node:
                continue
            if (
                node.node_kind != "ability_call"
                or task.opcode != "TriggerAbility"
                or process_only
            ):
                block(
                    "ability_task_graph_nested_identity_mismatch",
                    phase_id=graph.owner_id,
                    callback_kind=graph.callback_kind,
                    graph_id=graph.graph_id,
                    graph_node_id=node.graph_node_id,
                    task_id=task.task_id,
                    source="nested_node_identity",
                )
                continue

            ability_refs = tuple(
                reference
                for reference in node.references
                if reference.reference_kind == "ability"
            )
            if len(ability_refs) != 1 or ability_refs[0].resolution_status != "resolved":
                block(
                    "ability_task_graph_nested_reference_not_resolved",
                    phase_id=graph.owner_id,
                    callback_kind=graph.callback_kind,
                    graph_id=graph.graph_id,
                    graph_node_id=node.graph_node_id,
                    task_id=task.task_id,
                    source="nested_reference",
                )
                continue

            reference = ability_refs[0]
            phase_ids: tuple[str, ...] = ()
            if task.linked_ability_phase_id:
                if reference.definition_id != task.linked_ability_phase_id:
                    block(
                        "ability_task_graph_nested_phase_identity_mismatch",
                        phase_id=graph.owner_id,
                        callback_kind=graph.callback_kind,
                        graph_id=graph.graph_id,
                        graph_node_id=node.graph_node_id,
                        task_id=task.task_id,
                        source="nested_reference_identity",
                    )
                    continue
                phase_ids = (task.linked_ability_phase_id,)
            elif task.linked_standalone_graph_id:
                if reference.definition_id != task.linked_standalone_graph_id:
                    block(
                        "ability_task_graph_nested_standalone_identity_mismatch",
                        phase_id=graph.owner_id,
                        callback_kind=graph.callback_kind,
                        graph_id=graph.graph_id,
                        graph_node_id=node.graph_node_id,
                        task_id=task.task_id,
                        source="nested_reference_identity",
                    )
                    continue
                standalone = rules.standalone_ability_graph(
                    task.linked_standalone_graph_id
                )
                if standalone is None:
                    block(
                        "ability_task_graph_nested_standalone_missing",
                        phase_id=graph.owner_id,
                        callback_kind=graph.callback_kind,
                        graph_id=graph.graph_id,
                        graph_node_id=node.graph_node_id,
                        task_id=task.task_id,
                        source="nested_standalone",
                    )
                    continue
                phase_ids = standalone.phase_ids
            else:
                block(
                    "ability_task_graph_nested_target_missing",
                    phase_id=graph.owner_id,
                    callback_kind=graph.callback_kind,
                    graph_id=graph.graph_id,
                    graph_node_id=node.graph_node_id,
                    task_id=task.task_id,
                    source="nested_target",
                )
                continue

            candidates: list[tuple[TaskGraphIR, str]] = []
            for phase_id in phase_ids:
                phase = rules.ability_phase(phase_id)
                if phase is None or phase.invocation_role != "nested_only":
                    continue
                nested_tasks = tuple(
                    candidate
                    for candidate in rules.ability_tasks_for_phase(phase_id)
                    if candidate.callback_kind == task.callback_kind
                )
                if not nested_tasks:
                    continue
                nested_result = rules.query_formal_task_graph(
                    "ability_phase_callback",
                    phase_id,
                    task.callback_kind,
                    (candidate.task_id for candidate in nested_tasks),
                )
                nested_graph = nested_result.value
                if nested_result.status != "resolved" or type(nested_graph) is not TaskGraphIR:
                    block(
                        nested_result.blocked_reason
                        or "ability_task_graph_nested_graph_missing",
                        phase_id=phase_id,
                        callback_kind=task.callback_kind,
                        graph_id=graph.graph_id,
                        graph_node_id=node.graph_node_id,
                        task_id=task.task_id,
                        source="nested_graph",
                    )
                    continue
                if (
                    nested_graph.source_catalog_id != graph.source_catalog_id
                    or nested_graph.source_fingerprint != graph.source_fingerprint
                ):
                    block(
                        "task_graph_nested_graph_authority_mismatch",
                        phase_id=phase_id,
                        callback_kind=task.callback_kind,
                        graph_id=nested_graph.graph_id,
                        graph_node_id=node.graph_node_id,
                        task_id=task.task_id,
                        source="nested_graph_authority",
                    )
                    continue
                candidates.append((nested_graph, phase_id))

            if len(candidates) != 1:
                block(
                    "ability_task_graph_nested_callback_missing"
                    if not candidates
                    else "ability_task_graph_nested_callback_ambiguous",
                    phase_id=graph.owner_id,
                    callback_kind=graph.callback_kind,
                    graph_id=graph.graph_id,
                    graph_node_id=node.graph_node_id,
                    task_id=task.task_id,
                    source="nested_callback",
                )
                continue

            nested_graph, nested_phase_id = candidates[0]
            nested_edges_by_graph_id.setdefault(graph.graph_id, []).append(
                (
                    nested_graph,
                    nested_phase_id,
                    task.callback_kind,
                    node.graph_node_id,
                    task.task_id,
                )
            )
            if nested_graph.graph_id in active_path:
                block(
                    f"task_graph_active_cycle:{nested_graph.graph_id}",
                    phase_id=nested_phase_id,
                    callback_kind=task.callback_kind,
                    graph_id=nested_graph.graph_id,
                    graph_node_id=node.graph_node_id,
                    task_id=task.task_id,
                    source="nested_graph_cycle",
                )
                continue
            pending_graphs.append(
                (
                    nested_graph,
                    nested_phase_id,
                    task.callback_kind,
                    False,
                    (*active_path, nested_graph.graph_id),
                )
            )

    # Static support collection is globally de-duplicated above. Runtime graph
    # re-entry is path-sensitive, so cycle detection must be a separate DFS over
    # the resolved nested-graph edge relation rather than reuse that global set.
    cycle_state: dict[str, int] = {}

    def detect_nested_graph_cycles(graph_id: str) -> None:
        cycle_state[graph_id] = 1
        for (
            nested_graph,
            nested_phase_id,
            callback_kind,
            graph_node_id,
            task_id,
        ) in nested_edges_by_graph_id.get(graph_id, ()):
            nested_state = cycle_state.get(nested_graph.graph_id, 0)
            if nested_state == 1:
                block(
                    f"task_graph_active_cycle:{nested_graph.graph_id}",
                    phase_id=nested_phase_id,
                    callback_kind=callback_kind,
                    graph_id=nested_graph.graph_id,
                    graph_node_id=graph_node_id,
                    task_id=task_id,
                    source="nested_graph_cycle",
                )
                continue
            if nested_state == 0:
                detect_nested_graph_cycles(nested_graph.graph_id)
        cycle_state[graph_id] = 2

    for root_graph_id in _stable_unique(root_graph_ids):
        if cycle_state.get(root_graph_id, 0) == 0:
            detect_nested_graph_cycles(root_graph_id)

    reachable = _stable_unique(reachable_task_ids)
    excluded = tuple(sorted(set(formal_bound_task_ids) - set(reachable)))
    return _FormalActionGraphAdmissionProjection(
        root_graph_ids=_stable_unique(root_graph_ids),
        root_entries=tuple(dict.fromkeys(root_entries)),
        reachable_task_ids=reachable,
        excluded_bound_task_ids=excluded,
        blocked_reasons=_stable_unique(blocked_reasons),
        blocker_provenance=tuple(blocker_provenance),
    )


class ActionContractSystem:
    """Shared ownership/role/window/resource gate for query and submission."""

    def __init__(self, rules: RuleBook) -> None:
        self.rules = rules
        self.lifecycle = UnitLifecycleSystem()
        self.resources = ResourceSystem()

    def evaluate(
        self,
        state: BattleState,
        command: ActionCommand,
        *,
        submission_mode: str | None = None,
        authorization: ActionSubmissionAuthorization | None = None,
        target_selection_fingerprint: str = "",
        queue_resource_policy: dict[str, JSONValue] | None = None,
    ) -> ActionContractDecision:
        actor = state.units.get(command.actor_id)
        owner_entity_ref = actor.template_id if actor is not None else ""
        mode = authorization.submission_mode if authorization is not None else (
            submission_mode or submission_mode_for_command(command)
        )
        current_window = authorization.window if authorization is not None else _current_window(state)
        base = {
            "actor_id": command.actor_id,
            "owner_entity_ref": owner_entity_ref,
            "action_id": command.action_id,
            "action_level": command.action_level,
            "submission_mode": mode,
            "current_window": current_window,
        }
        if actor is None:
            return ActionContractDecision(**base, ok=False, blocked_reason="action_actor_missing")
        if authorization is not None:
            authorization_reason = authorization.blocked_reason(
                command,
                owner_entity_ref,
                _action_state_revision(state),
                target_selection_fingerprint,
            )
            if authorization_reason:
                return ActionContractDecision(
                    **base,
                    ok=False,
                    blocked_reason=authorization_reason,
                    metadata={"authorization_source_id": authorization.source_id},
                )
        actor_ok, actor_reason = self.lifecycle.can_act(state, actor.unit_id)
        if not actor_ok:
            return ActionContractDecision(
                **base,
                ok=False,
                blocked_reason=f"action_actor_{actor_reason}",
            )
        control_gate = status_control_gate_for_actor(actor)
        if control_gate is not None:
            return ActionContractDecision(
                **base,
                ok=False,
                blocked_reason=str(control_gate.get("reason") or "status_control_gate"),
                metadata={"control_gate": control_gate},
            )
        admission, reason = self.rules.action_admission_resolution(
            owner_entity_ref,
            command.action_id,
            command.action_level,
            mode,
        )
        if admission is None:
            return ActionContractDecision(**base, ok=False, blocked_reason=reason)
        if mode == "external_turn":
            turn_owner_id = str(state.global_flags.get("turn_owner_id") or "")
            if turn_owner_id != actor.unit_id:
                return ActionContractDecision(
                    **base,
                    ok=False,
                    admission=admission,
                    blocked_reason="action_actor_not_turn_owner",
                    metadata={"turn_owner_id": turn_owner_id},
                )
            if current_window not in admission.allowed_windows:
                return ActionContractDecision(
                    **base,
                    ok=False,
                    admission=admission,
                    blocked_reason=f"action_window_not_admitted:{current_window}",
                )
        elif mode == "insert_window" and current_window not in admission.allowed_windows:
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason=f"action_window_not_admitted:{current_window}",
            )
        definition = self.rules.action_definition(command.action_id, command.action_level)
        if definition is None:
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason="action_definition_missing",
            )
        if admission.resource_gate_kind == "ultimate_energy" and (
            actor.max_energy <= 0 or actor.energy < actor.max_energy
        ):
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason="ultimate_energy_not_ready",
                resource_status="blocked",
                resource_blocked_reason="ultimate_energy_not_ready",
                metadata={"energy": actor.energy, "max_energy": actor.max_energy},
            )
        resource_result = self.resources.plan_action_resources(
            state,
            actor.unit_id,
            action_resource_plan(
                definition,
                source="action_contract.resource_gate",
                metadata={"admission_id": admission.admission_id},
                queue_resource_policy=queue_resource_policy or {},
            ),
        )
        if not resource_result.ok:
            resource_reason = action_resource_blocked_reason(resource_result.errors)
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason=resource_reason,
                resource_status="blocked",
                resource_blocked_reason=resource_reason,
            )
        binding_reason = action_binding_blocked_reason(
            self.rules.action_ability_binding(command.action_id, command.action_level)
        )
        event_reason = action_event_blocked_reason(
            self.rules.action_event(command.action_id, command.action_level)
        )
        selected_tasks = self.rules.ability_tasks_for_action(
            command.action_id,
            command.action_level,
        )
        projection = _formal_action_task_graph_projection(
            self.rules,
            command.action_id,
            command.action_level,
            selected_tasks,
        )
        legacy_task_reasons = tuple(
            reason
            for task in selected_tasks
            if (
                (phase := self.rules.ability_phase(task.phase_id)) is not None
                and phase.invocation_role == "external_legacy"
                and (
                    reason := ability_task_runtime_blocked_reason(
                        self.rules,
                        task,
                        topology_authority="external_legacy",
                    )
                )
            )
        )
        graph_reason = combined_blocked_reason(
            binding_reason,
            event_reason,
            *legacy_task_reasons,
            *projection.blocked_reasons,
        )
        projection_metadata = projection.metadata()
        if graph_reason:
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason=graph_reason,
                resource_status="ok",
                metadata={
                    "selected_task_ids": [task.task_id for task in selected_tasks],
                    **projection_metadata,
                },
            )
        return ActionContractDecision(
            **base,
            ok=True,
            admission=admission,
            resource_status="ok",
            metadata={
                "action_role": admission.action_role,
                "allowed_windows": list(admission.allowed_windows),
                "submission_modes": list(admission.submission_modes),
                **projection_metadata,
            },
        )


def submission_mode_for_command(command: ActionCommand) -> str:
    del command
    return "external_turn"


def _current_window(state: BattleState) -> str:
    return str(state.global_flags.get("current_window") or "idle")