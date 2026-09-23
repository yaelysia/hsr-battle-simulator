"""Compiler-to-executor bridge tests; fixtures are not real-gameplay evidence."""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.core.model import BattleState
from hsr.simulator_v8_clean_core.ir_types import IRSource
from hsr.simulator_v8_clean_core.rules.ir import EffectIR
from hsr.simulator_v8_clean_core.rules.control_flow_contract import (
    CharacterControlFlowNodeIR,
    ControlFlowBranchIR,
    ControlFlowTerminationIR,
)
from hsr.simulator_v8_clean_core.rules.task_graph import (
    task_graph_entry_id,
    task_graph_id,
    task_graph_source_occurrence_id,
)
from hsr.simulator_v8_clean_core.systems.task_graph import (
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphExecutor,
    TaskGraphWeightedSelectionResult,
)
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    _Blocked,
    _DefinitionIndexes,
    _FormalTask,
    _build_graph,
)

DEFERRED = "ability_task_weighted_selection_caller_deferred_to_pr9"


def _compiled_graph(
    entry_kind="ability_phase_callback", *, role="random_branch",
    stages=("p9_s8c",), execution_mode="runtime_effect", odds=(2, 3),
    source_blocked=False, with_reference=False,
):
    # Small in-memory source/catalog inputs avoid a full TBGD scan. Production
    # _build_graph, numeric lowering, typed IR validation and executor are real.
    raw = {"Task": {"$type": "RandomConfig", "OddsList": list(odds),
                    "ConfigList": [{}, {}]}}
    payload = json.dumps(raw, sort_keys=True).encode()
    digest = hashlib.sha256(payload).hexdigest()
    path = "validation_fixture/a2_weighted_dispatch.json"
    source = IRSource(path, "RandomConfig", "fixture:random", {
        "json_path": "$.Task", "content_sha256": digest,
        "source_opcode": "RandomConfig", "task_path": "fixture[0]",
    })
    control_id = "fixture:control"
    branches = tuple(
        ControlFlowBranchIR(
            branch_id=f"fixture:branch:{i}", node_id=control_id,
            branch_kind="config", ordinal=i, label=f"choice_{i}", children=(),
            source=IRSource(path, "RandomConfig", f"fixture:branch:{i}", {
                "json_path": f"$.Task.ConfigList[{i}]", "content_sha256": digest,
                "node_id": control_id, "branch_kind": "config",
            }),
        ) for i in range(2)
    )
    control = CharacterControlFlowNodeIR(
        node_id=control_id, scope_record_id="fixture:scope", family="RandomConfig",
        control_role=role, peer_field_names=(), field_responsibilities=(),
        branches=branches, template_reference_ids=(),
        termination=ControlFlowTerminationIR(
            control_id, "not_applicable", "not_applicable", "p9_s8c",
            None, "", source,
        ),
        downstream_stages=tuple(sorted(stages)), source=source,
        coverage_status="blocked" if source_blocked else "lowered_with_obligation",
        blocked_reason="fixture_source_gap" if source_blocked else "",
    )
    task = _FormalTask(
        task_id="fixture:task", graph_task_path="fixture[0]", opcode="RandomConfig",
        family="RandomConfig", condition_id="", target_expression_id="",
        effect_id="fixture:effect" if with_reference else "",
        ability_definition_id="", ability_definition_kind="",
        execution_mode=execution_mode, coverage_status="executable", source=source,
    )
    entry_id = task_graph_entry_id(entry_kind, "fixture:owner", "OnStart")
    catalog = SimpleNamespace(catalog_id="fixture:catalog", source_fingerprint=digest)
    effects = {}
    if with_reference:
        effect_source = replace(source, evidence={**source.evidence, "parent_task_id": ""})
        if with_reference == "foreign_source":
            effect_source = replace(effect_source, raw_id="foreign")
        effect = EffectIR(
            effect_id="fixture:effect",
            opcode="RandomConfig" if with_reference in {"owned", "foreign_source"} else "FixtureEffect",
            payload={}, source=effect_source, coverage_status="unsupported",
        )
        effects[effect.effect_id] = (effect,)
    return _build_graph(
        source_catalog=catalog,
        source_snapshot=SimpleNamespace(source_bytes={path: payload}),
        graph_id=task_graph_id(catalog.catalog_id, entry_id, digest),
        entry_id=entry_id, entry_kind=entry_kind, owner_id="fixture:owner",
        callback_kind="OnStart", ordered_task_ids=(task.task_id,), tasks=(task,),
        sources={task.task_id: source},
        occurrences={task.task_id: task_graph_source_occurrence_id(source, task.family)},
        controls={task.task_id: control}, template_by_id={}, refs_by_node={},
        definitions=_DefinitionIndexes({}, {}, effects, {}),
    )


def _run(graph, *, provide_hook=True):
    state = BattleState()
    seen = []

    def weighted(request, selection, current_state):
        assert current_state is state
        assert selection == graph.weighted_selections[0]
        assert request.graph_node_id == selection.graph_node_id
        seen.append(request.graph_node_id)
        return TaskGraphWeightedSelectionResult("blocked", blocked_reason=DEFERRED)

    def forbidden(*args):
        raise AssertionError("deferred weighted selection must not run a child or ordinary branch")

    result = TaskGraphExecutor().execute(
        state, graph, TaskGraphExecutionContext("a2-weighted-bridge-fixture"),
        TaskGraphExecutionHooks(
            weighted_selection=weighted if provide_hook else None,
            branch=forbidden, leaf=forbidden,
        ),
    )
    assert not result.ok
    assert result.before_state is state and result.after_state is state
    assert not result.mutations and not result.events and not result.rng_events
    assert not result.settlement_records
    assert all(item.status != "complete" for item in result.node_projections)
    return result, seen


@pytest.mark.parametrize("entry_kind", ["ability_phase_callback", "status_callback"])
@pytest.mark.parametrize("with_reference", [False, "owned"])
def test_materialized_source_reaches_weighted_hook_without_rewriting_node(entry_kind, with_reference):
    graph = _compiled_graph(entry_kind, with_reference=with_reference)
    node = graph.nodes[0]
    assert (node.node_kind, node.materialization_status) == ("branch", "materialized")
    assert node.owner_domains == ("task_graph_execution",)
    assert len(graph.weighted_selections[0].choices) == len(node.branches) == 2
    if with_reference:
        assert len(node.references) == 1
        assert node.references[0].resolution_status == "deferred"
        assert "unsupported" in node.references[0].blocked_reason
        assert graph.coverage_status == "lowered_with_obligation"
    result, seen = _run(graph)
    assert seen == [node.graph_node_id]
    assert result.errors == (DEFERRED,)


@pytest.mark.parametrize("kwargs", [
    {"role": "predicate_branch"},
    {"stages": ("p9_s8c", "p9_s11")},
    {"execution_mode": "process_only"},
    {"with_reference": True},
    {"with_reference": "foreign_source"},
])
def test_unproven_or_additional_obligations_still_block_before_hook(kwargs):
    graph = _compiled_graph(**kwargs)
    assert graph.nodes[0].materialization_status == "deferred"
    result, seen = _run(graph)
    assert not seen
    assert result.errors[0].startswith("task_graph_control_requires_domains:")


def test_missing_hook_does_not_fall_back_to_ordinary_branch():
    result, seen = _run(_compiled_graph(), provide_hook=False)
    assert not seen
    assert result.errors != (DEFERRED,)
    assert "weighted_selection" in result.errors[0]


def test_executor_still_rejects_explicit_deferred_nodes():
    graph = _compiled_graph()
    node = replace(graph.nodes[0], node_kind="deferred", materialization_status="deferred",
                   owner_domains=("hit_random_sequence",), status_reason="fixture_forced_deferred")
    graph = replace(graph, nodes=(node,), coverage_status="lowered_with_obligation")
    result, seen = _run(graph)
    assert not seen and result.errors == ("fixture_forced_deferred",)


def test_missing_weighted_ledger_is_rejected_by_ir():
    with pytest.raises(ValueError):
        replace(_compiled_graph(), weighted_selections=())


def test_malformed_odds_are_rejected_before_dispatch():
    with pytest.raises(_Blocked, match="odds_list_branch_length_mismatch"):
        _compiled_graph(odds=(1,))


def test_blocked_source_is_not_promoted():
    with pytest.raises(_Blocked, match="source_contract_blocked"):
        _compiled_graph(source_blocked=True)
