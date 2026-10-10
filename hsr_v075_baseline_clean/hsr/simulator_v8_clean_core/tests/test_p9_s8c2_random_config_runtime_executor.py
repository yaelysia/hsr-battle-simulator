from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core.core.model import BattleState, GameEvent, RNGEvent, TargetResolution
from simulator_v8_clean_core.ir_types import IRSource
from simulator_v8_clean_core.rules.ir import AbilityTaskIR, CanonicalIR, StatusCallbackIR, StatusCallbackTaskIR
from simulator_v8_clean_core.rules.rulebook import RuleBook
from simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from simulator_v8_clean_core.rules.task_graph import (
    TaskGraphBranchIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphNumericDefinitionIR,
    TaskGraphWeightedChoiceIR,
    TaskGraphWeightedSelectionIR,
    TaskGraphQueryResult,
    task_graph_branch_id,
    task_graph_entry_id,
    task_graph_id,
    task_graph_node_id,
    task_graph_numeric_id,
    task_graph_source_occurrence_id,
    task_graph_weighted_choice_id,
    task_graph_weighted_selection_id,
)
from simulator_v8_clean_core.systems.task_graph import (
    TaskGraphBranchResult,
    TaskGraphConditionResult,
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphExecutor,
    TaskGraphLeafResult,
    TaskGraphTargetResult,
    TaskGraphWeightedSelectionResult,
)
from simulator_v8_clean_core.systems.ability import AbilityTaskSystem, _FormalAbilityInvocation
from simulator_v8_clean_core.systems.effect import EffectRegistry
from simulator_v8_clean_core.systems.status import StatusSystem
from simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem


_DIGEST = "1" * 64
_STATE = BattleState()
_CONTEXT = TaskGraphExecutionContext("p9-s8c2-test")


def _source(json_path: str, family: str, *, raw_id: str = "fixture") -> IRSource:
    return IRSource(
        source_path="tests/p9_s8c2_random_config.json",
        raw_type="P9S8C2Fixture",
        raw_id=raw_id,
        evidence={
            "json_path": json_path,
            "content_sha256": _DIGEST,
            "source_opcode": family,
        },
    )


def _leaf_node(graph_id: str, index: int) -> TaskGraphNodeIR:
    family = f"Leaf{index}"
    source = _source(f"$.Leaf[{index}]", family)
    occurrence_id = task_graph_source_occurrence_id(source, family)
    formal_task_id = f"leaf:{index}"
    return TaskGraphNodeIR(
        graph_node_id=task_graph_node_id(graph_id, formal_task_id, occurrence_id),
        graph_id=graph_id,
        source_occurrence_id=occurrence_id,
        source_contract_node_id="",
        formal_task_id=formal_task_id,
        opcode=family,
        source_family=family,
        node_kind="leaf",
        branches=(),
        references=(),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="materialized",
        owner_domains=("task_graph_execution",),
        source=source,
    )


def _random_graph(
    choice_count: int = 3,
    *,
    entry_kind: str = "ability_phase_callback",
    owner_id: str = "p9-s8c2-owner",
) -> TaskGraphIR:
    callback_kind = "test"
    entry_id = task_graph_entry_id(entry_kind, owner_id, callback_kind)
    source_catalog_id = "p9-s8c2-random-catalog"
    source_fingerprint = "2" * 64
    graph_id = task_graph_id(source_catalog_id, entry_id, source_fingerprint)

    leaves = tuple(_leaf_node(graph_id, index) for index in range(choice_count))
    root_source = _source("$.RandomConfig", "RandomConfig")
    root_occurrence_id = task_graph_source_occurrence_id(root_source, "RandomConfig")
    root_formal_task_id = "random-root"
    root_id = task_graph_node_id(graph_id, root_formal_task_id, root_occurrence_id)

    branches: list[TaskGraphBranchIR] = []
    choices: list[TaskGraphWeightedChoiceIR] = []
    definitions: list[TaskGraphNumericDefinitionIR] = []
    for index, leaf in enumerate(leaves):
        label = f"choice-{index}"
        branch_id = task_graph_branch_id(
            root_id,
            "weighted_choice",
            index,
            label,
            (leaf.graph_node_id,),
        )
        branches.append(
            TaskGraphBranchIR(
                branch_id=branch_id,
                graph_node_id=root_id,
                branch_kind="weighted_choice",
                ordinal=index,
                label=label,
                child_node_ids=(leaf.graph_node_id,),
                source=root_source,
            )
        )
        choice_source = _source(
            f"$.RandomConfig.OddsList[{index}]",
            "RandomConfig",
        )
        weight_occurrence_id = task_graph_source_occurrence_id(
            choice_source,
            "RandomConfig",
        )
        expression = numeric_fixed(float(index + 1))
        definition_id = task_graph_numeric_id(weight_occurrence_id, expression)
        definition = TaskGraphNumericDefinitionIR(
            definition_id=definition_id,
            source_occurrence_id=weight_occurrence_id,
            expression=expression,
            source=choice_source,
        )
        definitions.append(definition)
        choices.append(
            TaskGraphWeightedChoiceIR(
                choice_id=task_graph_weighted_choice_id(
                    root_id,
                    index,
                    branch_id,
                    definition_id,
                ),
                graph_node_id=root_id,
                family="RandomConfig",
                ordinal=index,
                branch_id=branch_id,
                weight_definition_id=definition_id,
                weight_source_occurrence_id=weight_occurrence_id,
                source=choice_source,
            )
        )

    root = TaskGraphNodeIR(
        graph_node_id=root_id,
        graph_id=graph_id,
        source_occurrence_id=root_occurrence_id,
        source_contract_node_id="",
        formal_task_id=root_formal_task_id,
        opcode="RandomConfig",
        source_family="RandomConfig",
        node_kind="branch",
        branches=tuple(branches),
        references=(),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="materialized",
        owner_domains=("task_graph_execution",),
        source=root_source,
    )
    selection = TaskGraphWeightedSelectionIR(
        selection_id=task_graph_weighted_selection_id(root_id, root_occurrence_id),
        graph_node_id=root_id,
        parent_source_occurrence_id=root_occurrence_id,
        family="RandomConfig",
        selection_kind="weighted_single",
        choices=tuple(choices),
        numeric_definitions=tuple(definitions),
        source=root_source,
    )
    return TaskGraphIR(
        graph_id=graph_id,
        entry_id=entry_id,
        entry_kind=entry_kind,
        owner_id=owner_id,
        callback_kind=callback_kind,
        root_node_ids=(root_id,),
        nodes=(root, *leaves),
        numeric_definitions=(),
        source_catalog_id=source_catalog_id,
        source_fingerprint=source_fingerprint,
        source=_source("$.Graph", "Graph"),
        coverage_status="lowered",
        weighted_selections=(selection,),
    )


def test_formal_weighted_consumers_select_branch_and_record_rng() -> None:
    for entry_kind in ("ability_phase_callback", "status_callback"):
        owner_id = "phase" if entry_kind == "ability_phase_callback" else "callback"
        graph = _random_graph(entry_kind=entry_kind, owner_id=owner_id)
        source = _source("$.RandomConfig", "RandomConfig")
        if entry_kind == "ability_phase_callback":
            task = AbilityTaskIR(
                "random-root", owner_id, "action", 1, "ability", "test", 0,
                "root", "root", "RandomConfig", source, coverage_status="executable",
            )
            rules = RuleBook(CanonicalIR("fixture", ability_tasks=(task,)))
        else:
            callback = StatusCallbackIR(
                owner_id, "Modifier", "test", ("random-root",), source,
                (0, 0), coverage_status="executable", admission_status="executable",
            )
            task = StatusCallbackTaskIR(
                "random-root", owner_id, "Modifier", "test", 0, "root",
                "root", "RandomConfig", source, coverage_status="executable",
            )
            rules = RuleBook(CanonicalIR(
                "fixture", status_callbacks=(callback,), status_callback_tasks=(task,),
            ))
        class GraphRules:
            def __getattr__(self, name):
                return getattr(rules, name)

            def query_task_graph(self, graph_id):
                return TaskGraphQueryResult(
                    "resolved", "graph", (graph.graph_id,), graph, "",
                )

            def query_task_graph_node(self, node_id):
                return TaskGraphQueryResult(
                    "resolved", "node", (node_id,),
                    next(node for node in graph.nodes if node.graph_node_id == node_id), "",
                )

        graph_rules = GraphRules()
        if entry_kind == "ability_phase_callback":
            system = AbilityTaskSystem(graph_rules, EffectRegistry(StatusSystem(graph_rules)))
            hooks = system._formal_task_graph_hooks(invocation=_FormalAbilityInvocation(
                "status_nested", "actor", "action", 1, TargetResolution(),
            ))
        else:
            system = StatusCallbackSystem(graph_rules)
            hooks = system._formal_status_hooks(
                callback, {"owner_id": "actor", "instance_id": "status"}, None, None, None,
                [],
            )
        selected: list[str] = []
        hooks = replace(hooks, leaf=lambda request, _state: (
            selected.append(request.formal_task_id) or TaskGraphLeafResult("resolved")
        ))
        result = system.task_graph_executor.execute(_STATE, graph, _CONTEXT, hooks)
        assert result.ok, result.errors
        assert len(result.rng_events) == 1
        choice_id = result.rng_events[0].result["selected_outcome_id"]
        chosen = next(choice for choice in graph.weighted_selections[0].choices if choice.choice_id == choice_id)
        assert selected == [f"leaf:{chosen.ordinal}"]
        alternative = next(choice for choice in graph.weighted_selections[0].choices if choice.choice_id != choice_id)
        choice_key = result.rng_events[0].metadata["choice_key"]
        payload = {"rng_mode": "explicit", "rng_choices": {choice_key: alternative.choice_id}}
        selected.clear()
        if entry_kind == "status_callback":
            hooks = replace(
                system._formal_status_hooks(
                    callback, {"owner_id": "actor", "instance_id": "status"},
                    GameEvent("test", payload=payload), None, None,
                    [],
                ),
                leaf=hooks.leaf,
            )
            context = _CONTEXT
        else:
            context = TaskGraphExecutionContext(_CONTEXT.invocation_id, payload)
        explicit = system.task_graph_executor.execute(_STATE, graph, context, hooks)
        assert explicit.ok, explicit.errors
        assert explicit.rng_events[0].result["selected_outcome_id"] == alternative.choice_id
        assert explicit.rng_events[0].metadata["choice_source"] == "explicit_ledger"
        assert selected == [f"leaf:{alternative.ordinal}"]


def _ordinary_graph() -> TaskGraphIR:
    entry_kind = "ability_phase_callback"
    owner_id = "p9-s8c2-ordinary-owner"
    callback_kind = "test"
    entry_id = task_graph_entry_id(entry_kind, owner_id, callback_kind)
    source_catalog_id = "p9-s8c2-ordinary-catalog"
    source_fingerprint = "3" * 64
    graph_id = task_graph_id(source_catalog_id, entry_id, source_fingerprint)
    leaves = tuple(_leaf_node(graph_id, index) for index in range(2))
    family = "DomainBranch"
    root_source = _source("$.DomainBranch", family, raw_id="ordinary")
    occurrence_id = task_graph_source_occurrence_id(root_source, family)
    root_id = task_graph_node_id(graph_id, "ordinary-root", occurrence_id)
    branches = tuple(
        TaskGraphBranchIR(
            branch_id=task_graph_branch_id(
                root_id,
                "domain",
                index,
                label,
                (leaves[index].graph_node_id,),
            ),
            graph_node_id=root_id,
            branch_kind="domain",
            ordinal=index,
            label=label,
            child_node_ids=(leaves[index].graph_node_id,),
            source=root_source,
        )
        for index, label in enumerate(("skip", "pick"))
    )
    root = TaskGraphNodeIR(
        graph_node_id=root_id,
        graph_id=graph_id,
        source_occurrence_id=occurrence_id,
        source_contract_node_id="",
        formal_task_id="ordinary-root",
        opcode=family,
        source_family=family,
        node_kind="branch",
        branches=branches,
        references=(),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="materialized",
        owner_domains=("task_graph_execution",),
        source=root_source,
    )
    return TaskGraphIR(
        graph_id=graph_id,
        entry_id=entry_id,
        entry_kind=entry_kind,
        owner_id=owner_id,
        callback_kind=callback_kind,
        root_node_ids=(root_id,),
        nodes=(root, *leaves),
        numeric_definitions=(),
        source_catalog_id=source_catalog_id,
        source_fingerprint=source_fingerprint,
        source=_source("$.OrdinaryGraph", "Graph", raw_id="ordinary"),
        coverage_status="lowered",
        weighted_selections=(),
    )


def test_control_node_rng_precedes_selected_child_and_rolls_back() -> None:
    ordinary = _ordinary_graph()
    root = next(node for node in ordinary.nodes if node.node_kind == "branch")
    for control_kind in ("condition", "target_scope"):
        branch_kind = "success" if control_kind == "condition" else "target_scope"
        branch = replace(
            root.branches[1], branch_kind=branch_kind, ordinal=0,
            branch_id=task_graph_branch_id(
                root.graph_node_id, branch_kind, 0,
                root.branches[1].label, root.branches[1].child_node_ids,
            ),
        )
        selected_root = replace(
            root, node_kind="branch" if control_kind == "condition" else "target_scope",
            branches=(branch,),
        )
        graph = replace(ordinary, nodes=tuple(
            selected_root if node.graph_node_id == root.graph_node_id else node
            for node in ordinary.nodes
            if node.graph_node_id == root.graph_node_id
            or node.graph_node_id in branch.child_node_ids
        ))
        event = RNGEvent("test_random", "test", {"choice": "selected"},
                         event_id=f"control:{control_kind}")
        seen: list[str] = []
        hooks = TaskGraphExecutionHooks(
            leaf=lambda request, _state: (
                seen.append(request.formal_task_id) or TaskGraphLeafResult("resolved")
            ),
            condition=lambda _request, _state: TaskGraphConditionResult(
                "resolved", True, rng_events=(event,),
            ),
            targets=lambda _request, _state: TaskGraphTargetResult(
                "resolved", ("target",), rng_events=(event,),
            ),
        )
        result = TaskGraphExecutor().execute(_STATE, graph, _CONTEXT, hooks)
        assert result.ok, result.errors
        assert seen == ["leaf:1"] and result.rng_events == (event,)
        failed = TaskGraphExecutor().execute(
            _STATE, graph, _CONTEXT,
            replace(hooks, leaf=lambda _request, _state: TaskGraphLeafResult(
                "blocked", outcome_kind="", blocked_reason="selected_child_failed",
            )),
        )
        assert not failed.ok and failed.after_state is _STATE and not failed.rng_events


def _selection_result(
    selection: TaskGraphWeightedSelectionIR,
    index: int = 1,
    *,
    event_id: str = "p9-s8c2-selection-rng",
    choice_id: str | None = None,
    ordinal: int | None = None,
    branch_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> TaskGraphWeightedSelectionResult:
    choice = selection.choices[index]
    return TaskGraphWeightedSelectionResult(
        status="resolved",
        selection_id=selection.selection_id,
        graph_node_id=selection.graph_node_id,
        choice_id=choice.choice_id if choice_id is None else choice_id,
        ordinal=choice.ordinal if ordinal is None else ordinal,
        branch_id=choice.branch_id if branch_id is None else branch_id,
        rng_event=RNGEvent(
            rng_type="weighted_single",
            source="p9-s8c2-test",
            result={"choice_id": choice.choice_id},
            event_id=event_id,
            metadata={} if metadata is None else metadata,
        ),
    )


def _assert_atomic_block(result: object, state: BattleState = _STATE) -> None:
    assert result.ok is False
    assert result.before_state is state
    assert result.after_state is state
    assert result.mutations == ()
    assert result.events == ()
    assert result.rng_events == ()
    assert result.settlement_records == ()


def test_selected_only_branch_executes_and_emits_selection_rng_first() -> None:
    graph = _random_graph()
    seen: list[str] = []

    def leaf(request, _state):
        seen.append(request.formal_task_id)
        return TaskGraphLeafResult(status="resolved")

    def weighted(_request, selection, _state):
        return _selection_result(selection, 1)

    def forbidden_branch(*_args):
        raise AssertionError("ordinary branch hook must not select RandomConfig")

    result = TaskGraphExecutor().execute(
        _STATE,
        graph,
        _CONTEXT,
        TaskGraphExecutionHooks(
            leaf=leaf,
            branch=forbidden_branch,
            weighted_selection=weighted,
        ),
    )

    assert result.ok is True
    assert seen == ["leaf:1"]
    assert [event.to_json()["event_id"] for event in result.rng_events] == [
        "p9-s8c2-selection-rng"
    ]
    projected_formal_ids = [item.formal_task_id for item in result.node_projections]
    assert projected_formal_ids == ["random-root", "leaf:1"]
    assert "leaf:0" not in projected_formal_ids
    assert "leaf:2" not in projected_formal_ids


def test_weighted_selection_identity_and_projection_path_are_stable() -> None:
    graph = _random_graph()

    def leaf(_request, _state):
        return TaskGraphLeafResult(status="resolved")

    def weighted(_request, selection, _state):
        return _selection_result(selection, 1, event_id="stable-rng")

    hooks = TaskGraphExecutionHooks(leaf=leaf, weighted_selection=weighted)
    first = TaskGraphExecutor().execute(_STATE, graph, _CONTEXT, hooks)
    second = TaskGraphExecutor().execute(_STATE, graph, _CONTEXT, hooks)

    assert first.ok is True and second.ok is True
    assert first.rng_events == second.rng_events
    assert first.node_projections == second.node_projections
    leaf_projection = next(
        item for item in first.node_projections if item.formal_task_id == "leaf:1"
    )
    selection = graph.weighted_selections[0]
    choice = selection.choices[1]
    assert f"selection:{selection.selection_id}" in leaf_projection.path
    assert f"choice:{choice.choice_id}" in leaf_projection.path
    assert f"branch:{choice.branch_id}:{choice.ordinal}" in leaf_projection.path


def test_stale_choice_blocks_without_formal_channel_leakage() -> None:
    graph = _random_graph()

    def weighted(_request, selection, _state):
        return _selection_result(selection, 1, choice_id="stale-choice")

    result = TaskGraphExecutor().execute(
        _STATE,
        graph,
        _CONTEXT,
        TaskGraphExecutionHooks(weighted_selection=weighted),
    )

    _assert_atomic_block(result)
    assert result.errors == ("task_graph_weighted_selection_choice_not_unique",)


@pytest.mark.parametrize(
    ("ordinal_offset", "foreign_branch"),
    ((1, False), (0, True)),
)
def test_ordinal_or_branch_mismatch_blocks_atomically(
    ordinal_offset: int,
    foreign_branch: bool,
) -> None:
    graph = _random_graph()

    def weighted(_request, selection, _state):
        choice = selection.choices[1]
        return _selection_result(
            selection,
            1,
            ordinal=choice.ordinal + ordinal_offset,
            branch_id="foreign-branch" if foreign_branch else choice.branch_id,
        )

    result = TaskGraphExecutor().execute(
        _STATE,
        graph,
        _CONTEXT,
        TaskGraphExecutionHooks(weighted_selection=weighted),
    )

    _assert_atomic_block(result)
    assert result.errors == (
        "task_graph_weighted_selection_choice_identity_mismatch",
    )


def test_missing_weighted_hook_never_falls_back_to_branch_hook() -> None:
    graph = _random_graph()
    branch_called = False

    def branch(_request, _state):
        nonlocal branch_called
        branch_called = True
        return TaskGraphBranchResult(status="resolved", branch_kind="weighted_choice")

    result = TaskGraphExecutor().execute(
        _STATE,
        graph,
        _CONTEXT,
        TaskGraphExecutionHooks(branch=branch),
    )

    _assert_atomic_block(result)
    assert branch_called is False
    assert result.errors == ("task_graph_hook_missing:weighted_selection",)


def test_duplicate_rng_identity_with_selected_leaf_rolls_back_atomically() -> None:
    graph = _random_graph()

    def weighted(_request, selection, _state):
        return _selection_result(selection, 1, event_id="shared-rng")

    def leaf(_request, _state):
        return TaskGraphLeafResult(
            status="resolved",
            rng_events=(
                RNGEvent(
                    rng_type="leaf",
                    source="p9-s8c2-test",
                    result="leaf",
                    event_id="shared-rng",
                ),
            ),
        )

    result = TaskGraphExecutor().execute(
        _STATE,
        graph,
        _CONTEXT,
        TaskGraphExecutionHooks(leaf=leaf, weighted_selection=weighted),
    )

    _assert_atomic_block(result)
    assert result.errors == ("task_graph_duplicate_rng_identity:shared-rng",)


def test_weighted_rng_reserved_execution_identity_is_rejected() -> None:
    graph = _random_graph()

    def weighted(_request, selection, _state):
        return _selection_result(
            selection,
            1,
            metadata={"task_graph_execution_id": "forged"},
        )

    result = TaskGraphExecutor().execute(
        _STATE,
        graph,
        _CONTEXT,
        TaskGraphExecutionHooks(weighted_selection=weighted),
    )

    _assert_atomic_block(result)
    assert result.errors == (
        "task_graph_weighted_selection_forged_execution_identity",
    )


def test_non_random_config_branch_keeps_existing_branch_hook_behavior() -> None:
    graph = _ordinary_graph()
    seen: list[str] = []
    weighted_called = False

    def leaf(request, _state):
        seen.append(request.formal_task_id)
        return TaskGraphLeafResult(status="resolved")

    def branch(_request, _state):
        return TaskGraphBranchResult(
            status="resolved",
            branch_kind="domain",
            label="pick",
        )

    def weighted(*_args):
        nonlocal weighted_called
        weighted_called = True
        raise AssertionError("ordinary branch must not use weighted selection")

    result = TaskGraphExecutor().execute(
        _STATE,
        graph,
        _CONTEXT,
        TaskGraphExecutionHooks(
            leaf=leaf,
            branch=branch,
            weighted_selection=weighted,
        ),
    )

    assert result.ok is True
    assert weighted_called is False
    assert seen == ["leaf:1"]
    assert result.rng_events == ()
