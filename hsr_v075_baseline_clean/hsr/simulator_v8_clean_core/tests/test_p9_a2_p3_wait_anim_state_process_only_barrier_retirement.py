from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core.ir_types import IRSource
from simulator_v8_clean_core.rules.control_flow_contract import (
    CharacterControlFlowNodeIR,
    ControlFlowBranchIR,
    ControlFlowFieldResponsibilityIR,
    ControlFlowTerminationIR,
)
from simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from simulator_v8_clean_core.rules.task_graph import (
    TaskGraphNodeIR,
    task_graph_node_id,
    task_graph_source_occurrence_id,
)
from simulator_v8_clean_core.tbgd.task_graph_materializer import (
    _DefinitionIndexes,
    _FormalTask,
    _is_wait_anim_state_process_only_presentation_shape,
    _node_status,
    _references,
)


_DIGEST = "1" * 64


def _node_source(
    node_id: str,
    family: str,
    *,
    path: str = "$.Wait",
    source_path: str = "tests/wait_anim_state.json",
) -> IRSource:
    return IRSource(
        source_path,
        family,
        node_id,
        {
            "json_path": path,
            "content_sha256": _DIGEST,
        },
    )


def _responsibility(
    node_id: str,
    family: str,
    field_name: str,
    *,
    responsibility: str = "presentation_excluded",
    owner_stage: str = "excluded",
    path: str = "$.Wait",
    source_path: str = "tests/wait_anim_state.json",
) -> ControlFlowFieldResponsibilityIR:
    return ControlFlowFieldResponsibilityIR(
        field_name=field_name,
        responsibility=responsibility,  # type: ignore[arg-type]
        owner_stage=owner_stage,
        covers_subtree=True,
        source=IRSource(
            source_path,
            family,
            f"{node_id}:{field_name}",
            {
                "json_path": f"{path}.{field_name}",
                "content_sha256": _DIGEST,
                "node_id": node_id,
                "field_name": field_name,
            },
        ),
    )


def _control(
    *,
    family: str = "WaitAnimState",
    role: str = "presentation_barrier",
    gameplay_field: bool = False,
    with_branch: bool = False,
    with_count_termination: bool = False,
    blocked: bool = False,
    node_id: str = "control:wait",
    path: str = "$.Wait",
    source_path: str = "tests/wait_anim_state.json",
) -> CharacterControlFlowNodeIR:
    source = _node_source(
        node_id,
        family,
        path=path,
        source_path=source_path,
    )
    fields = [
        _responsibility(
            node_id,
            family,
            "AnimStateName",
            path=path,
            source_path=source_path,
        ),
        _responsibility(
            node_id,
            family,
            "NormalizedTimeEnd",
            path=path,
            source_path=source_path,
        ),
    ]
    stages = {"p9_s8c" if role == "presentation_barrier" else "p9_s11"}
    if gameplay_field:
        fields.append(
            _responsibility(
                node_id,
                family,
                "GameplayField",
                responsibility="downstream_gameplay",
                owner_stage="p9_s11",
                path=path,
                source_path=source_path,
            )
        )
        stages.add("p9_s11")
    branches: tuple[ControlFlowBranchIR, ...] = ()
    if with_branch:
        branch_id = f"{node_id}:branch"
        branches = (
            ControlFlowBranchIR(
                branch_id=branch_id,
                node_id=node_id,
                branch_kind="task_list",
                ordinal=0,
                label="",
                children=(),
                source=IRSource(
                    source_path,
                    family,
                    branch_id,
                    {
                        "json_path": f"{path}.TaskList",
                        "content_sha256": _DIGEST,
                        "node_id": node_id,
                        "branch_kind": "task_list",
                    },
                ),
            ),
        )
    termination = ControlFlowTerminationIR(
        node_id=node_id,
        termination_kind="count_expression" if with_count_termination else "not_applicable",
        status="source_backed" if with_count_termination else "not_applicable",
        owner_stage="p9_s8c" if with_count_termination else "p9_s8a",
        expression=numeric_fixed(1.0) if with_count_termination else None,
        blocked_reason="",
        source=source,
    )
    if blocked:
        coverage_status = "blocked"
        blocked_reason = "fixture_source_contract_blocked"
    else:
        coverage_status = "lowered_with_obligation" if stages else "lowered"
        blocked_reason = ""
    return CharacterControlFlowNodeIR(
        node_id=node_id,
        scope_record_id=f"scope:{node_id}",
        family=family,
        control_role=role,
        peer_field_names=tuple(sorted(item.field_name for item in fields)),
        field_responsibilities=tuple(fields),
        branches=branches,
        template_reference_ids=(),
        termination=termination,
        downstream_stages=tuple(sorted(stages)),
        source=source,
        coverage_status=coverage_status,  # type: ignore[arg-type]
        blocked_reason=blocked_reason,
    )


def _task(
    *,
    family: str = "WaitAnimState",
    opcode: str | None = None,
    execution_mode: str = "process_only",
    coverage_status: str = "audit_only",
    effect_id: str = "effect:wait",
    path: str = "$.Wait",
    source_path: str = "tests/wait_anim_state.json",
) -> _FormalTask:
    opcode = family if opcode is None else opcode
    return _FormalTask(
        task_id=f"task:{family}:{path}",
        graph_task_path="OnStart[0]",
        opcode=opcode,
        family=family,
        condition_id="",
        target_expression_id="",
        effect_id=effect_id,
        ability_definition_id="",
        ability_definition_kind="",
        execution_mode=execution_mode,
        coverage_status=coverage_status,
        source=IRSource(
            source_path,
            "AbilityTask",
            "fixture",
            {
                "json_path": path,
                "content_sha256": _DIGEST,
                "source_opcode": family,
            },
        ),
    )


def test_valid_wait_anim_state_retires_s8c_and_has_no_gameplay_reference() -> None:
    control = _control()
    task = _task()
    assert _is_wait_anim_state_process_only_presentation_shape(control, task)
    assert _node_status(control, task) == (
        "leaf",
        "materialized",
        ("task_graph_execution",),
        "",
    )
    indexes = _DefinitionIndexes(
        conditions={},
        targets={},
        effects={task.effect_id: (SimpleNamespace(coverage_status="audit_only"),)},
        abilities={},
    )
    assert _references(task, control, "graph-node", task.source, indexes, {}) == ()


def test_two_independent_wait_anim_state_sources_both_use_the_same_gate() -> None:
    rows = (
        (_control(node_id="control:a", path="$.Ability.OnStart[0]"), _task(path="$.Ability.OnStart[0]")),
        (_control(node_id="control:b", path="$.Ability.OnStart[2]"), _task(path="$.Ability.OnStart[2]")),
    )
    assert all(
        _node_status(control, task)[1] == "materialized"
        for control, task in rows
    )


def test_blocked_process_only_source_contract_is_not_retired() -> None:
    task = _task(coverage_status="blocked")
    control = _control()
    assert not _is_wait_anim_state_process_only_presentation_shape(control, task)
    assert _node_status(control, task)[1:] == (
        "deferred",
        ("hit_random_sequence",),
        "task_graph_control_requires_domains:hit_random_sequence",
    )


@pytest.mark.parametrize(
    "control",
    (
        _control(gameplay_field=True),
        _control(with_branch=True),
        _control(with_count_termination=True),
    ),
)
def test_gameplay_field_branch_or_termination_cannot_use_presentation_retirement(
    control: CharacterControlFlowNodeIR,
) -> None:
    task = _task()
    assert not _is_wait_anim_state_process_only_presentation_shape(control, task)
    kind, status, domains, reason = _node_status(control, task)
    assert kind == "deferred"
    assert status == "deferred"
    assert "hit_random_sequence" in domains
    assert reason.startswith("task_graph_control_requires_domains:")


def test_missing_exact_wait_anim_control_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="task_graph_wait_anim_state_source_contract_missing"):
        _node_status(None, _task())


def test_non_wait_anim_presentation_barrier_is_unchanged() -> None:
    control = _control(family="WaitSecond")
    task = _task(family="WaitSecond")
    assert not _is_wait_anim_state_process_only_presentation_shape(control, task)
    assert _node_status(control, task) == (
        "deferred",
        "deferred",
        ("hit_random_sequence",),
        "task_graph_control_requires_domains:hit_random_sequence",
    )


@pytest.mark.parametrize("family", ("DamagePerformFinish", "SkillPerformFinish"))
def test_s11_process_only_settlement_barrier_is_not_globally_admitted(family: str) -> None:
    control = _control(family=family, role="settlement_barrier")
    task = _task(family=family)
    assert not _is_wait_anim_state_process_only_presentation_shape(control, task)
    assert _node_status(control, task) == (
        "deferred",
        "deferred",
        ("damage_heal_shield",),
        "task_graph_control_requires_domains:damage_heal_shield",
    )


def test_materialized_wait_anim_node_round_trips_with_source_identity() -> None:
    control = _control()
    task = _task()
    source_occurrence_id = task_graph_source_occurrence_id(task.source, task.family)
    graph_id = "graph:wait"
    graph_node_id = task_graph_node_id(graph_id, task.task_id, source_occurrence_id)
    node = TaskGraphNodeIR(
        graph_node_id=graph_node_id,
        graph_id=graph_id,
        source_occurrence_id=source_occurrence_id,
        source_contract_node_id=control.node_id,
        formal_task_id=task.task_id,
        opcode=task.opcode,
        source_family=task.family,
        node_kind="leaf",
        branches=(),
        references=(),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="materialized",
        owner_domains=("task_graph_execution",),
        source=task.source,
    )
    assert TaskGraphNodeIR.from_json(node.to_json()) == node
    assert node.source.evidence["json_path"] == control.source.evidence["json_path"]
