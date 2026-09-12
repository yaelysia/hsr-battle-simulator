from __future__ import annotations

import ast
import sys
from dataclasses import replace
from pathlib import Path

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
from simulator_v8_clean_core.rules.ir import (
    AbilityPhaseIR,
    AbilityTaskIR,
    CanonicalIR,
    EffectIR,
)
from simulator_v8_clean_core.rules.task_graph import (
    TaskGraphCatalogIR,
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
    task_graph_source_record_fingerprint,
)
from simulator_v8_clean_core.tbgd.task_graph_materializer import (
    _DefinitionIndexes,
    _FormalTask,
    _is_wait_anim_state_process_only_presentation_shape,
    _node_status,
    _references,
)


_DIGEST = "1" * 64
_SOURCE_FINGERPRINT = "2" * 64
_DEPENDENCY_FINGERPRINT = "3" * 64
_AUDIT_BLOCKER = "task_graph_definition_not_admitted:effect:audit_only"


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
        {"json_path": path, "content_sha256": _DIGEST},
    )


def _task_source(
    family: str = "WaitAnimState",
    *,
    path: str = "$.Wait",
    source_path: str = "tests/wait_anim_state.json",
) -> IRSource:
    return IRSource(
        source_path,
        "AbilityTask",
        "fixture",
        {
            "json_path": path,
            "content_sha256": _DIGEST,
            "source_opcode": family,
            "task_path": "OnStart[0]",
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
        termination_kind=(
            "count_expression" if with_count_termination else "not_applicable"
        ),
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
        source=_task_source(family, path=path, source_path=source_path),
    )


def _process_only_contract(opcode: str = "WaitAnimState") -> dict[str, object]:
    return {
        "schema_version": "ability_process_only_source_shape_v1",
        "opcode": opcode,
        "source_fields": ["$type", "AnimStateName", "NormalizedTimeEnd"],
        "source_field_types": {
            "$type": "str",
            "AnimStateName": "str",
            "NormalizedTimeEnd": "float",
        },
        "source_shape_status": "admitted",
        "blocked_reason": "",
    }


def _effect(
    task: _FormalTask,
    *,
    effect_id: str | None = None,
    opcode: str | None = None,
    source: IRSource | None = None,
    coverage_status: str = "audit_only",
    contract: dict[str, object] | None = None,
) -> EffectIR:
    return EffectIR(
        effect_id=task.effect_id if effect_id is None else effect_id,
        opcode=task.opcode if opcode is None else opcode,
        payload={
            "process_only_contract": (
                _process_only_contract(task.opcode) if contract is None else contract
            )
        },
        source=task.source if source is None else source,
        coverage_status=coverage_status,  # type: ignore[arg-type]
    )


def _indexes(task: _FormalTask, *effects: EffectIR) -> _DefinitionIndexes:
    effect_rows = effects or (_effect(task),)
    return _DefinitionIndexes(
        conditions={},
        targets={},
        effects={task.effect_id: tuple(effect_rows)},
        abilities={},
    )


def _valid_reference(
    task: _FormalTask,
    control: CharacterControlFlowNodeIR,
    *,
    node_id: str = "graph-node",
) -> TaskGraphDefinitionReferenceIR:
    refs = _references(task, control, node_id, task.source, _indexes(task), {})
    assert len(refs) == 1
    return refs[0]


def test_valid_wait_anim_state_retires_s8c_and_keeps_one_audit_effect_reference() -> None:
    control = _control()
    task = _task()
    assert _is_wait_anim_state_process_only_presentation_shape(control, task)
    assert _node_status(control, task) == (
        "leaf",
        "materialized",
        ("task_graph_execution",),
        "",
    )
    refs = _references(task, control, "graph-node", task.source, _indexes(task), {})
    assert len(refs) == 1
    ref = refs[0]
    assert ref.reference_kind == "effect"
    assert ref.definition_id == task.effect_id
    assert ref.resolution_status == "deferred"
    assert ref.blocked_reason == _AUDIT_BLOCKER
    assert ref.source == task.source


def test_two_independent_wait_anim_state_sources_both_use_the_same_gate() -> None:
    rows = (
        (
            _control(node_id="control:a", path="$.Ability.OnStart[0]"),
            _task(path="$.Ability.OnStart[0]"),
        ),
        (
            _control(node_id="control:b", path="$.Ability.OnStart[2]"),
            _task(path="$.Ability.OnStart[2]"),
        ),
    )
    for control, task in rows:
        assert _node_status(control, task)[1] == "materialized"
        refs = _references(task, control, "graph-node", task.source, _indexes(task), {})
        assert [(ref.reference_kind, ref.definition_id) for ref in refs] == [
            ("effect", task.effect_id)
        ]


@pytest.mark.parametrize(
    ("effects", "reason"),
    (
        ((), "task_graph_wait_anim_state_process_only_effect_missing"),
        (
            (
                _effect(
                    _task(),
                    source=IRSource(
                        "tests/wait_anim_state.json",
                        "AbilityTask",
                        "other",
                        {
                            "json_path": "$.Elsewhere",
                            "content_sha256": _DIGEST,
                            "source_opcode": "WaitAnimState",
                            "task_path": "OnStart[0]",
                        },
                    ),
                ),
            ),
            "task_graph_wait_anim_state_process_only_effect_contract_invalid",
        ),
        (
            (_effect(_task(), opcode="WaitSecond"),),
            "task_graph_wait_anim_state_process_only_effect_contract_invalid",
        ),
        (
            (_effect(_task(), coverage_status="executable"),),
            "task_graph_wait_anim_state_process_only_effect_contract_invalid",
        ),
        (
            (
                _effect(
                    _task(),
                    contract={
                        **_process_only_contract(),
                        "source_shape_status": "blocked",
                        "blocked_reason": "fixture",
                    },
                ),
            ),
            "task_graph_wait_anim_state_process_only_effect_contract_invalid",
        ),
    ),
)
def test_wait_anim_state_effect_identity_and_contract_fail_closed(
    effects: tuple[EffectIR, ...],
    reason: str,
) -> None:
    task = _task()
    control = _control()
    indexes = _DefinitionIndexes(
        conditions={},
        targets={},
        effects={task.effect_id: effects} if effects else {},
        abilities={},
    )
    with pytest.raises(RuntimeError, match=reason):
        _references(task, control, "graph-node", task.source, indexes, {})


def test_wait_anim_state_ambiguous_effect_identity_fails_closed() -> None:
    task = _task()
    control = _control()
    indexes = _DefinitionIndexes(
        conditions={},
        targets={},
        effects={task.effect_id: (_effect(task), _effect(task))},
        abilities={},
    )
    with pytest.raises(
        RuntimeError,
        match="task_graph_wait_anim_state_process_only_effect_ambiguous",
    ):
        _references(task, control, "graph-node", task.source, indexes, {})


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
    with pytest.raises(
        RuntimeError,
        match="task_graph_wait_anim_state_source_contract_missing",
    ):
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
def test_s11_process_only_settlement_barrier_is_not_globally_admitted(
    family: str,
) -> None:
    control = _control(family=family, role="settlement_barrier")
    task = _task(family=family)
    assert not _is_wait_anim_state_process_only_presentation_shape(control, task)
    assert _node_status(control, task) == (
        "deferred",
        "deferred",
        ("damage_heal_shield",),
        "task_graph_control_requires_domains:damage_heal_shield",
    )


def test_materialized_wait_anim_node_round_trips_with_audit_reference() -> None:
    control = _control()
    task = _task()
    source_occurrence_id = task_graph_source_occurrence_id(task.source, task.family)
    graph_id = "graph:wait"
    graph_node_id = task_graph_node_id(graph_id, task.task_id, source_occurrence_id)
    reference = _valid_reference(task, control, node_id=graph_node_id)
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
        references=(reference,),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="materialized",
        owner_domains=("task_graph_execution",),
        source=task.source,
    )
    assert TaskGraphNodeIR.from_json(node.to_json()) == node
    assert node.source.evidence["json_path"] == control.source.evidence["json_path"]


def _formal_fixture(
    references: tuple[TaskGraphDefinitionReferenceIR, ...],
    *,
    graph_coverage: str = "lowered_with_obligation",
) -> CanonicalIR:
    task_source = _task_source()
    control = _control()
    task_id = "ability_task:fixture:wait"
    phase_id = "ability_phase:fixture:wait"
    callback_kind = "OnStart"
    ability_task = AbilityTaskIR(
        task_id=task_id,
        phase_id=phase_id,
        action_id="fixture:action",
        level=1,
        ability_name="FixtureAbility",
        callback_kind=callback_kind,
        task_index=0,
        task_path="OnStart[0]",
        branch="root",
        opcode="WaitAnimState",
        source=task_source,
        effect_id="effect:wait",
        execution_mode="process_only",
        coverage_status="audit_only",
    )
    effect = EffectIR(
        effect_id=ability_task.effect_id,
        opcode=ability_task.opcode,
        payload={"process_only_contract": _process_only_contract()},
        source=task_source,
        coverage_status="audit_only",
    )
    phase = AbilityPhaseIR(
        phase_id=phase_id,
        binding_id="binding:fixture",
        action_id=ability_task.action_id,
        level=1,
        ability_name=ability_task.ability_name,
        phase_index=0,
        target_info={},
        opcode_summary={},
        callback_summaries={},
        source=task_source,
        coverage_status="audit_only",
        task_ids=(task_id,),
        invocation_role="action_root",
    )
    source_occurrence_id = task_graph_source_occurrence_id(
        task_source,
        "WaitAnimState",
    )
    source_catalog_id = "control_catalog:fixture"
    entry_id = task_graph_entry_id("ability_phase_callback", phase_id, callback_kind)
    graph_id = task_graph_id(source_catalog_id, entry_id, _SOURCE_FINGERPRINT)
    graph_node_id = task_graph_node_id(graph_id, task_id, source_occurrence_id)
    normalized_refs = tuple(
        replace(
            ref,
            graph_node_id=graph_node_id,
            reference_id=task_graph_reference_id(
                graph_node_id,
                ref.reference_kind,
                ref.definition_id,
            ),
            source=task_source,
        )
        for ref in references
    )
    node = TaskGraphNodeIR(
        graph_node_id=graph_node_id,
        graph_id=graph_id,
        source_occurrence_id=source_occurrence_id,
        source_contract_node_id=control.node_id,
        formal_task_id=task_id,
        opcode=ability_task.opcode,
        source_family="WaitAnimState",
        node_kind="leaf",
        branches=(),
        references=normalized_refs,
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="materialized",
        owner_domains=("task_graph_execution",),
        source=task_source,
    )
    materialization_id = task_graph_materialization_id(
        entry_id,
        (task_id,),
        (source_occurrence_id,),
    )
    entry = TaskGraphEntryMaterializationIR(
        materialization_id=materialization_id,
        entry_id=entry_id,
        entry_kind="ability_phase_callback",
        owner_id=phase_id,
        callback_kind=callback_kind,
        graph_id=graph_id,
        formal_task_ids=(task_id,),
        source_occurrence_ids=(source_occurrence_id,),
        status="materialized",
        source=task_source,
    )
    graph = TaskGraphIR(
        graph_id=graph_id,
        entry_id=entry_id,
        entry_kind="ability_phase_callback",
        owner_id=phase_id,
        callback_kind=callback_kind,
        root_node_ids=(graph_node_id,),
        nodes=(node,),
        numeric_definitions=(),
        source_catalog_id=source_catalog_id,
        source_fingerprint=_SOURCE_FINGERPRINT,
        source=task_source,
        coverage_status=graph_coverage,  # type: ignore[arg-type]
    )
    disposition = TaskGraphSourceDispositionIR(
        source_record_id=control.node_id,
        source_kind="control_node",
        source_occurrence_id=source_occurrence_id,
        family="WaitAnimState",
        disposition="materialized",
        owner_domains=(),
        formal_materialization_ids=(materialization_id,),
        source=control.source,
    )
    catalog = TaskGraphCatalogIR(
        scope_mode="formal_slice",
        source_catalog_id=source_catalog_id,
        snapshot_id="snapshot:fixture",
        scope_catalog_id="scope:fixture",
        source_fingerprint=_SOURCE_FINGERPRINT,
        dependency_fingerprint=_DEPENDENCY_FINGERPRINT,
        source_record_count=1,
        source_record_fingerprint=task_graph_source_record_fingerprint(
            (control.node_id,)
        ),
        source_dispositions=(disposition,),
        entry_materializations=(entry,),
        graphs=(graph,),
        selected_entry_ids=(entry_id,),
        source_ledger_complete=True,
    )
    return CanonicalIR(
        version="fixture",
        effects=(effect,),
        ability_phases=(phase,),
        ability_tasks=(ability_task,),
        task_graph_catalog=catalog,
    )


def _fixture_effect_reference(
    definition_id: str = "effect:wait",
) -> TaskGraphDefinitionReferenceIR:
    return TaskGraphDefinitionReferenceIR(
        reference_id=task_graph_reference_id("placeholder", "effect", definition_id),
        graph_node_id="placeholder",
        reference_kind="effect",
        definition_id=definition_id,
        source_contract_record_id="",
        resolution_status="deferred",
        owner_domain="event_effect_execution",
        source=_task_source(),
        blocked_reason=_AUDIT_BLOCKER,
    )


@pytest.mark.parametrize(
    ("references", "coverage"),
    (
        ((), "lowered"),
        ((_fixture_effect_reference(), _fixture_effect_reference("effect:wrong")), "lowered_with_obligation"),
        ((_fixture_effect_reference("effect:wrong"),), "lowered_with_obligation"),
    ),
)
def test_canonical_rejects_zero_multiple_or_wrong_effect_reference(
    references: tuple[TaskGraphDefinitionReferenceIR, ...],
    coverage: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="task graph formal definition references are inconsistent",
    ):
        _formal_fixture(references, graph_coverage=coverage)


def test_direct_validator_proves_formal_denominator_and_explicit_zero_channels() -> None:
    validator = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "validate_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py"
    )
    text = validator.read_text(encoding="utf-8")
    module = ast.parse(text)
    denominator = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "formal_wait_anim_denominator"
    )
    denominator_text = ast.get_source_segment(text, denominator)
    assert denominator_text is not None
    for token in (
        "canonical = lowerer.build()",
        "catalog = canonical.task_graph_catalog",
        "catalog.entry_materializations",
        'entry.entry_kind != "ability_phase_callback"',
        "RuleBook(canonical)",
    ):
        assert token in denominator_text
    assert "build_character_action_ability_slice(" not in denominator_text
    for token in (
        '"formal_wait_anim_denominator"',
        '"formal_channel_counts"',
        '"mutation_count"',
        '"event_count"',
        '"rng_event_count"',
        '"settlement_record_count"',
        '"replay_mutation_count"',
        "TaskGraphExecutionResult.__dataclass_fields__",
    ):
        assert token in text
    assert "def _source_denominator(" not in text


def test_direct_validator_scopes_status_lowering_to_formal_sources() -> None:
    validator = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "validate_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py"
    )
    text = validator.read_text(encoding="utf-8")
    module = ast.parse(text)
    builder = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and node.name == "_FormalTaskGraphViewBuilder"
    )
    builder_text = ast.get_source_segment(text, builder)
    assert builder_text is not None
    assert "relative not in formal_status_root_paths" in builder_text
    assert "formal_status_source_context=self.formal_context" in builder_text
    assert "if relative in formal_status_root_paths\n                    else None" not in builder_text
