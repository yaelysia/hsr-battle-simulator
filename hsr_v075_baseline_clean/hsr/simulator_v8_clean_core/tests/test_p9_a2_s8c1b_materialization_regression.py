"""S8C1B Harness classification tests; not evidence of real gameplay execution."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.rules.ir import AbilityTaskIR, EffectIR
from hsr.simulator_v8_clean_core.tests.test_p9_a2_weighted_materialization_dispatch import (
    _compiled_graph,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection import (
    _run_fast,
    _verify_materialization_contract,
)


def _case(*, role="random_branch", stages=("p9_s8c",),
          execution_mode="runtime_effect", with_reference=False):
    graph = _compiled_graph(
        role=role, stages=stages, execution_mode=execution_mode,
        with_reference=with_reference,
    )
    node = graph.nodes[0]
    task = AbilityTaskIR(
        task_id=node.formal_task_id, phase_id=graph.owner_id,
        action_id="avatar_skill:fixture", level=1, ability_name="fixture",
        callback_kind=graph.callback_kind, task_index=0,
        task_path=node.source.evidence["task_path"], branch="root",
        opcode="RandomConfig", source=node.source,
        effect_id="fixture:effect" if with_reference else "",
        execution_mode=execution_mode, coverage_status="executable",
    )
    control = SimpleNamespace(
        node_id=node.source_contract_node_id, family="RandomConfig",
        control_role=role, coverage_status="lowered_with_obligation",
        downstream_stages=stages, source=node.source,
    )
    effects = ()
    if with_reference:
        effect_source = replace(
            node.source,
            evidence={**node.source.evidence, "parent_task_id": ""},
        )
        if with_reference == "foreign_source":
            effect_source = replace(effect_source, raw_id="foreign")
        effects = (EffectIR(
            effect_id=task.effect_id,
            opcode="RandomConfig" if with_reference in {"owned", "foreign_source"} else "FixtureEffect",
            payload={}, source=effect_source, coverage_status="unsupported",
        ),)
    return graph, node, SimpleNamespace(nodes=(control,)), SimpleNamespace(
        ability_tasks=(task,), effects=effects,
    )


@pytest.mark.parametrize("with_reference", [False, "owned"])
def test_source_closed_compiler_output_is_accepted_without_erasing_obligations(with_reference):
    graph, node, catalog, canonical = _case(with_reference=with_reference)
    before = graph.to_json()
    evidence = _verify_materialization_contract(graph, node, catalog, canonical)
    assert evidence["dispatch_ready"] is True
    assert evidence["gameplay_rng_executed"] is False
    assert evidence["retained_reference_count"] == int(bool(with_reference))
    assert graph.to_json() == before
    if with_reference:
        assert node.references[0].resolution_status == "deferred"
        assert graph.coverage_status == "lowered_with_obligation"


@pytest.mark.parametrize("kwargs", [
    {"role": "predicate_branch"},
    {"stages": ("p9_s8c", "p9_s11")},
    {"execution_mode": "process_only"},
    {"with_reference": True},
    {"with_reference": "foreign_source"},
])
def test_remaining_obligations_require_deferred_not_either_state(kwargs):
    graph, node, catalog, canonical = _case(**kwargs)
    assert _verify_materialization_contract(graph, node, catalog, canonical)["dispatch_ready"] is False
    promoted = replace(
        node, node_kind="branch", materialization_status="materialized",
        owner_domains=("task_graph_execution",), status_reason="",
    )
    with pytest.raises(AssertionError, match="selective materialization mismatch"):
        _verify_materialization_contract(graph, promoted, catalog, canonical)


def test_eligible_node_cannot_silently_revert_to_old_deferred_shape():
    graph, node, catalog, canonical = _case()
    stale = replace(
        node, node_kind="deferred", materialization_status="deferred",
        owner_domains=("hit_random_sequence",),
        status_reason="task_graph_control_requires_domains:hit_random_sequence",
    )
    with pytest.raises(AssertionError, match="selective materialization mismatch"):
        _verify_materialization_contract(graph, stale, catalog, canonical)


@pytest.mark.parametrize("kind", [
    "missing_control", "duplicate_task", "wrong_source", "wrong_task_digest", "blocked_source",
])
def test_harness_rejects_missing_ambiguous_or_mismatched_source_authority(kind):
    graph, node, catalog, canonical = _case()
    if kind == "missing_control":
        catalog.nodes = ()
    elif kind == "duplicate_task":
        canonical.ability_tasks *= 2
    elif kind == "wrong_source":
        control = catalog.nodes[0]
        control.source = replace(control.source, source_path="validation_fixture/foreign.json")
    elif kind == "wrong_task_digest":
        task = canonical.ability_tasks[0]
        canonical.ability_tasks = (replace(
            task, source=replace(task.source, evidence={
                **task.source.evidence, "content_sha256": "foreign",
            }),
        ),)
    else:
        catalog.nodes[0].coverage_status = "blocked"
    with pytest.raises(AssertionError):
        _verify_materialization_contract(graph, node, catalog, canonical)


def test_harness_rejects_own_effect_coverage_promotion():
    graph, node, catalog, canonical = _case(with_reference="owned")
    reference = replace(node.references[0], resolution_status="resolved", blocked_reason="")
    forged = replace(node, references=(reference,))
    with pytest.raises(AssertionError, match="own-effect obligation was changed"):
        _verify_materialization_contract(graph, forged, catalog, canonical)


def test_original_source_codec_fast_negatives_are_preserved():
    result = _run_fast()
    assert result["ok"] and result["cases"] == 6
