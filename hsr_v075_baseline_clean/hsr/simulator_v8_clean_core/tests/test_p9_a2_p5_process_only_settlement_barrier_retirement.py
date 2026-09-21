from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core.ir_types import IRSource
from simulator_v8_clean_core.rules.control_flow_contract import (
    CharacterControlFlowNodeIR,
    ControlFlowFieldResponsibilityIR,
    ControlFlowTerminationIR,
)
from simulator_v8_clean_core.rules.ir import EffectIR
from simulator_v8_clean_core.rules.task_graph import (
    TaskGraphDefinitionReferenceIR,
    TaskGraphEntryMaterializationIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphSourceDispositionIR,
    task_graph_entry_id,
    task_graph_id,
    task_graph_materialization_id,
    task_graph_node_id,
    task_graph_reference_id,
    task_graph_source_occurrence_id,
)
from simulator_v8_clean_core.tbgd.lowering import (
    _process_only_ability_task_source_blocked_reason,
)
from simulator_v8_clean_core.tbgd.task_graph_materializer import (
    _DefinitionIndexes,
    _FormalTask,
    _is_process_only_settlement_barrier_shape,
    _materialization_dispositions,
    _node_status,
    _references,
)
from simulator_v8_clean_core.tools.validate_p9_a2_p5_process_only_settlement_barrier_retirement import (
    _source_partition,
)


_DIGEST = "1" * 64
_AUDIT_BLOCKER = "task_graph_definition_not_admitted:effect:audit_only"


@pytest.mark.parametrize(
    ("source_reason", "expected"),
    (
        ("", "C"),
        ("raw_source_missing", "C"),
        ("process_only_task_source_type_mismatch", "C"),
        ("process_only_task_unknown_fields", "C"),
        ("process_only_task_source_field_invalid:IsFakeAvatarAttack", "C"),
        ("damage_perform_finish_settlement_payload_not_admitted", "B"),
        ("skill_perform_finish_settlement_payload_not_admitted", "B"),
    ),
)
def test_settlement_denominator_only_admits_explicit_payload_reasons(
    source_reason: str, expected: str
) -> None:
    assert _source_partition(eligible=False, source_reason=source_reason) == expected
    assert _source_partition(eligible=True, source_reason=source_reason) == "A"


def _source(family: str, path: str = "$.Task") -> IRSource:
    return IRSource(
        "tests/settlement_barrier.json",
        "AbilityTask",
        "fixture",
        {"json_path": path, "content_sha256": _DIGEST, "source_opcode": family},
    )


def _control(
    family: str,
    *,
    role: str = "settlement_barrier",
    peer_fields: tuple[str, ...] = (),
    blocked: bool = False,
) -> CharacterControlFlowNodeIR:
    source = _source(family)
    node_id = f"control:{family}"
    responsibilities = tuple(
        ControlFlowFieldResponsibilityIR(
            field_name=field,
            responsibility="downstream_gameplay",
            owner_stage="p9_s11",
            covers_subtree=True,
            source=IRSource(
                source.source_path,
                family,
                f"{node_id}:{field}",
                {
                    "json_path": f"$.Task.{field}",
                    "content_sha256": _DIGEST,
                    "node_id": node_id,
                    "field_name": field,
                },
            ),
        )
        for field in peer_fields
    )
    return CharacterControlFlowNodeIR(
        node_id=node_id,
        scope_record_id=f"scope:{node_id}",
        family=family,
        control_role=role,  # type: ignore[arg-type]
        peer_field_names=peer_fields,
        field_responsibilities=responsibilities,
        branches=(),
        template_reference_ids=(),
        termination=ControlFlowTerminationIR(
            node_id=node_id,
            termination_kind="not_applicable",
            status="not_applicable",
            owner_stage="p9_s8a",
            expression=None,
            blocked_reason="",
            source=source,
        ),
        downstream_stages=("p9_s11",),
        source=source,
        coverage_status="blocked" if blocked else "lowered_with_obligation",  # type: ignore[arg-type]
        blocked_reason="fixture_blocked" if blocked else "",
    )


def _task(
    family: str,
    *,
    coverage_status: str = "audit_only",
    effect_id: str = "effect:fixture",
    execution_mode: str = "process_only",
) -> _FormalTask:
    return _FormalTask(
        task_id=f"task:{family}",
        graph_task_path="OnStart[0]",
        opcode=family,
        family=family,
        condition_id="",
        target_expression_id="",
        effect_id=effect_id,
        ability_definition_id="",
        ability_definition_kind="",
        execution_mode=execution_mode,
        coverage_status=coverage_status,
        source=_source(family),
    )


def _effect(task: _FormalTask, *, contract: object | None = None) -> EffectIR:
    return EffectIR(
        effect_id=task.effect_id,
        opcode=task.opcode,
        payload={
            "process_only_contract": contract
            if contract is not None
            else {
                "schema_version": "ability_process_only_source_shape_v1",
                "opcode": task.opcode,
                "source_fields": ["$type"],
                "source_field_types": {"$type": "str"},
                "source_shape_status": "admitted",
                "blocked_reason": "",
            }
        },
        source=task.source,
        coverage_status="audit_only",
    )


def _indexes(task: _FormalTask, effect: EffectIR | None = None) -> _DefinitionIndexes:
    return _DefinitionIndexes(
        conditions={},
        targets={},
        effects={task.effect_id: (() if effect is None else (effect,))},
        abilities={},
    )


@pytest.mark.parametrize("family", ("DamagePerformFinish", "SkillPerformFinish"))
def test_no_payload_settlement_barrier_is_a_materialized_audit_leaf(family: str) -> None:
    control = _control(family)
    task = _task(family)
    assert control.peer_field_names == ()
    assert control.field_responsibilities == ()
    assert _is_process_only_settlement_barrier_shape(control, task)
    assert _node_status(control, task) == (
        "leaf", "materialized", ("task_graph_execution",), ""
    )
    references = _references(task, control, "node:fixture", task.source, _indexes(task, _effect(task)), {})
    assert len(references) == 1
    reference = references[0]
    assert reference.reference_kind == "effect"
    assert reference.definition_id == task.effect_id
    assert reference.resolution_status == "deferred"
    assert reference.blocked_reason == _AUDIT_BLOCKER
    assert reference.source == task.source


@pytest.mark.parametrize(
    ("family", "payload", "reason"),
    (
        ("DamagePerformFinish", {"IsFakeAvatarAttack": True}, "damage_perform_finish_settlement_payload_not_admitted"),
        ("DamagePerformFinish", {"SkipDeathSettlement": True}, "damage_perform_finish_settlement_payload_not_admitted"),
        ("SkillPerformFinish", {"SkipAttackSettlement": True}, "skill_perform_finish_settlement_payload_not_admitted"),
    ),
)
def test_settlement_payload_source_shapes_remain_closed(
    family: str, payload: dict[str, object], reason: str
) -> None:
    assert _process_only_ability_task_source_blocked_reason(
        {"$type": f"RPG.GameCore.{family}", **payload}, family
    ) == reason
    control = _control(family, peer_fields=tuple(payload))
    task = _task(family)
    assert not _is_process_only_settlement_barrier_shape(control, task)
    assert _node_status(control, task)[1:] == (
        "deferred",
        ("damage_heal_shield",),
        "task_graph_control_requires_domains:damage_heal_shield",
    )


def test_wrong_control_role_or_blocked_contract_is_not_retired() -> None:
    task = _task("DamagePerformFinish")
    for control in (
        _control("DamagePerformFinish", role="presentation_barrier"),
        _control("DamagePerformFinish", blocked=True),
    ):
        assert not _is_process_only_settlement_barrier_shape(control, task)
        assert _node_status(control, task)[1] == "deferred"
    assert not _is_process_only_settlement_barrier_shape(
        _control("DamagePerformFinish"), _task("DamagePerformFinish", coverage_status="blocked")
    )


def test_malformed_process_only_contract_fails_closed() -> None:
    task = _task("DamagePerformFinish")
    with pytest.raises(
        RuntimeError,
        match="task_graph_process_only_settlement_barrier_effect_contract_invalid",
    ):
        _references(
            task,
            _control(task.family),
            "node:fixture",
            task.source,
            _indexes(task, _effect(task, contract={"source_shape_status": "blocked"})),
            {},
        )


def test_template_bearing_or_runtime_effect_shape_is_not_retired() -> None:
    control = _control("DamagePerformFinish")
    assert not _is_process_only_settlement_barrier_shape(
        replace(control, template_reference_ids=("template:fixture",)),
        _task(control.family),
    )
    assert not _is_process_only_settlement_barrier_shape(
        control,
        _task(control.family, execution_mode="runtime_effect"),
    )
    assert not _is_process_only_settlement_barrier_shape(
        _control("DamageByAttackProperty"),
        _task("DamageByAttackProperty", execution_mode="runtime_effect"),
    )


def test_effect_source_mismatch_fails_closed() -> None:
    task = _task("SkillPerformFinish")
    with pytest.raises(
        RuntimeError,
        match="task_graph_process_only_settlement_barrier_effect_contract_invalid",
    ):
        _references(
            task,
            _control(task.family),
            "node:fixture",
            task.source,
            _indexes(
                task,
                replace(
                    _effect(task),
                    source=_source(task.family, "$.Other"),
                ),
            ),
            {},
        )


def test_disposition_retires_only_the_matching_settlement_owner() -> None:
    family = "DamagePerformFinish"
    control = _control(family)
    task = _task(family)
    occurrence_id = task_graph_source_occurrence_id(task.source, family)
    entry_id = task_graph_entry_id("ability_phase_callback", "phase:fixture", "OnStart")
    graph_id = task_graph_id("control_catalog:fixture", entry_id, "2" * 64)
    node_id = task_graph_node_id(graph_id, task.task_id, occurrence_id)
    reference = TaskGraphDefinitionReferenceIR(
        reference_id=task_graph_reference_id(node_id, "effect", task.effect_id),
        graph_node_id=node_id,
        reference_kind="effect",
        definition_id=task.effect_id,
        source_contract_record_id="",
        resolution_status="deferred",
        owner_domain="event_effect_execution",
        source=task.source,
        blocked_reason=_AUDIT_BLOCKER,
    )
    node = TaskGraphNodeIR(
        graph_node_id=node_id,
        graph_id=graph_id,
        source_occurrence_id=occurrence_id,
        source_contract_node_id=control.node_id,
        formal_task_id=task.task_id,
        opcode=family,
        source_family=family,
        node_kind="leaf",
        branches=(),
        references=(reference,),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="materialized",
        owner_domains=("task_graph_execution",),
        source=task.source,
    )
    materialization_id = task_graph_materialization_id(entry_id, (task.task_id,), (occurrence_id,))
    entry = TaskGraphEntryMaterializationIR(
        materialization_id=materialization_id,
        entry_id=entry_id,
        entry_kind="ability_phase_callback",
        owner_id="phase:fixture",
        callback_kind="OnStart",
        graph_id=graph_id,
        formal_task_ids=(task.task_id,),
        source_occurrence_ids=(occurrence_id,),
        status="materialized",
        source=task.source,
    )
    graph = TaskGraphIR(
        graph_id=graph_id,
        entry_id=entry_id,
        entry_kind="ability_phase_callback",
        owner_id="phase:fixture",
        callback_kind="OnStart",
        root_node_ids=(node_id,),
        nodes=(node,),
        numeric_definitions=(),
        source_catalog_id="control_catalog:fixture",
        source_fingerprint="2" * 64,
        source=task.source,
        coverage_status="lowered_with_obligation",
    )
    base = TaskGraphSourceDispositionIR(
        source_record_id=control.node_id,
        source_kind="control_node",
        source_occurrence_id=occurrence_id,
        family=family,
        disposition="deferred",
        owner_domains=("damage_heal_shield", "task_graph_execution"),
        formal_materialization_ids=(),
        source=control.source,
        blocked_reason="",
    )
    result = _materialization_dispositions((base,), (entry,), (graph,))
    assert result[0].disposition == "materialized"
    assert result[0].owner_domains == ()
    assert result[0].formal_materialization_ids == (materialization_id,)
