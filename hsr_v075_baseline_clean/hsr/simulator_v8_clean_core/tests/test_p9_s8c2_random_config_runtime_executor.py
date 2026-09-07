from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core.core.model import BattleState, RNGEvent
from simulator_v8_clean_core.ir_types import IRSource
from simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from simulator_v8_clean_core.rules.task_graph import (
    TaskGraphBranchIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphNumericDefinitionIR,
    TaskGraphWeightedChoiceIR,
    TaskGraphWeightedSelectionIR,
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
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphExecutor,
    TaskGraphLeafResult,
    TaskGraphWeightedSelectionResult,
)


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


def _random_graph(choice_count: int = 3) -> TaskGraphIR:
    entry_kind = "ability_phase_callback"
    owner_id = "p9-s8c2-owner"
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
