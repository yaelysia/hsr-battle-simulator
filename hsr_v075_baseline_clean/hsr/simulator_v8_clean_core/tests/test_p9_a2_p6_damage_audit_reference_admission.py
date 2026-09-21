from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.ir_types import IRSource
from hsr.simulator_v8_clean_core.systems.ability_task_contract import (
    ability_task_runtime_blocked_reason,
)
from hsr.simulator_v8_clean_core.systems.action_contract import (
    _formal_action_task_graph_projection,
    _is_emission_backed_damage_audit_reference,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import (
    _FixtureRules,
    _graph,
    _phase,
    _task,
)


AUDIT_BLOCKER = "task_graph_definition_not_admitted:effect:audit_only"


class _DamageRules(_FixtureRules):
    def __init__(
        self,
        phase: object,
        task: object,
        graph: object,
        effect: object,
        *,
        damage_emissions: tuple[object, ...] | None = None,
        toughness_emissions: tuple[object, ...] | None = None,
        profiles: dict[str, object] | None = None,
    ) -> None:
        super().__init__((phase,), (task,), (graph,), {task.effect_id: effect})
        self._damage_emissions = damage_emissions if damage_emissions is not None else (
            SimpleNamespace(
                damage_emission_id="fixture:damage",
                action_id=task.action_id,
                level=task.level,
                phase_id=task.phase_id,
                coverage_status="executable",
                blocked_reason="",
                hit_profile_id="fixture:profile",
            ),
        )
        self._toughness_emissions = toughness_emissions if toughness_emissions is not None else (
            SimpleNamespace(
                toughness_emission_id="fixture:toughness",
                action_id=task.action_id,
                level=task.level,
                phase_id=task.phase_id,
                coverage_status="executable",
                blocked_reason="",
                hit_profile_id="fixture:profile",
            ),
        )
        self._profiles = profiles if profiles is not None else {
            "fixture:profile": SimpleNamespace(
                action_id=task.action_id,
                level=task.level,
                coverage_status="executable",
                blocked_reason="",
            )
        }

    def damage_emissions_for_task(self, task_id: str) -> tuple[object, ...]:
        return self._damage_emissions if task_id in self.tasks else ()

    def toughness_emissions_for_task(self, task_id: str) -> tuple[object, ...]:
        return self._toughness_emissions if task_id in self.tasks else ()

    def hit_profile(self, profile_id: str) -> object | None:
        return self._profiles.get(profile_id)


def _effect_source(task: object, **extra_evidence: object) -> IRSource:
    return IRSource(
        task.source.source_path,
        task.source.raw_type,
        task.source.raw_id,
        {**task.source.evidence, "parent_task_id": "", **extra_evidence},
    )


def _fixture(
    *,
    opcode: str = "DamageByAttackProperty",
    execution_mode: str = "runtime_effect",
    coverage_status: str = "executable",
    blocked_reason: str = "",
    node_kind: str = "leaf",
    reference_definition_id: str = "fixture:effect",
    effect_opcode: str | None = None,
    effect_coverage: str = "audit_only",
    effect_source: IRSource | None = None,
    extra_references: tuple[tuple[str, str, str, str], ...] = (),
    damage_emissions: tuple[object, ...] | None = None,
    toughness_emissions: tuple[object, ...] | None = None,
    profiles: dict[str, object] | None = None,
) -> tuple[object, object, object, _DamageRules]:
    phase = _phase("fixture:phase")
    task = _task(
        "fixture:task",
        phase.phase_id,
        opcode=opcode,
        execution_mode=execution_mode,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
        effect_id="fixture:effect",
    )
    effect = SimpleNamespace(
        opcode=effect_opcode or task.opcode,
        coverage_status=effect_coverage,
        source=effect_source or _effect_source(task),
        payload={
            "process_only_contract": {
                "schema_version": "ability_process_only_source_shape_v1",
                "opcode": task.opcode,
                "source_fields": ["$type"],
                "source_field_types": {"$type": "str"},
                "source_shape_status": "admitted",
                "blocked_reason": "",
            }
        },
    )
    graph = _graph(
        phase.phase_id,
        task,
        node_kind=node_kind,
        references=(
            (
                "effect",
                reference_definition_id,
                "deferred",
                AUDIT_BLOCKER,
            ),
            *extra_references,
        ),
    )
    rules = _DamageRules(
        phase,
        task,
        graph,
        effect,
        damage_emissions=damage_emissions,
        toughness_emissions=toughness_emissions,
        profiles=profiles,
    )
    return task, effect, graph, rules


def _predicate(task: object, graph: object, rules: _DamageRules) -> bool:
    node = graph.nodes[0]
    unresolved = tuple(
        reference
        for reference in node.references
        if reference.resolution_status != "resolved"
    )
    return _is_emission_backed_damage_audit_reference(
        rules, task, node, unresolved  # type: ignore[arg-type]
    )


def _project(task: object, rules: _DamageRules) -> object:
    return _formal_action_task_graph_projection(
        rules,  # type: ignore[arg-type]
        task.action_id,
        task.level,
        (task,),  # type: ignore[arg-type]
    )


def test_exact_precanonical_damage_audit_reference_is_admitted_without_mutation() -> None:
    task, effect, graph, rules = _fixture()
    reference_before = graph.nodes[0].references[0]
    source_before = effect.source

    assert ability_task_runtime_blocked_reason(
        rules, task, topology_authority="task_graph"  # type: ignore[arg-type]
    ) == ""
    assert _predicate(task, graph, rules)
    projection = _project(task, rules)

    assert AUDIT_BLOCKER not in projection.blocked_reasons
    assert graph.nodes[0].references[0] == reference_before
    assert graph.nodes[0].references[0].resolution_status == "deferred"
    assert effect.source == source_before
    assert effect.coverage_status == "audit_only"


@pytest.mark.parametrize(
    "source",
    (
        IRSource("fixture/foreign.json", "DamageByAttackProperty", "fixture:task", {}),
        None,
    ),
)
def test_arbitrary_or_additional_effect_source_delta_remains_blocked(
    source: IRSource | None,
) -> None:
    task, _effect, _graph_value, _rules = _fixture()
    mismatched = source or _effect_source(task, unrelated=True)
    task, _effect, graph, rules = _fixture(effect_source=mismatched)
    assert not _predicate(task, graph, rules)
    assert AUDIT_BLOCKER in _project(task, rules).blocked_reasons


@pytest.mark.parametrize(
    "evidence",
    (
        {"parent_task_id": "fixture:parent"},
        {"parent_task_id": "", "child_task_count": 0},
    ),
)
def test_nonempty_parent_or_child_topology_delta_remains_blocked(
    evidence: dict[str, object],
) -> None:
    task, _effect, _graph_value, _rules = _fixture()
    source = IRSource(
        task.source.source_path,
        task.source.raw_type,
        task.source.raw_id,
        {**task.source.evidence, **evidence},
    )
    task, _effect, graph, rules = _fixture(effect_source=source)
    assert not _predicate(task, graph, rules)
    assert AUDIT_BLOCKER in _project(task, rules).blocked_reasons


def test_canonical_task_source_with_topology_evidence_remains_blocked() -> None:
    task, effect, graph, rules = _fixture()
    task.source = IRSource(
        task.source.source_path,
        task.source.raw_type,
        task.source.raw_id,
        {**task.source.evidence, "parent_task_id": ""},
    )
    effect.source = _effect_source(task)
    assert not _predicate(task, graph, rules)


@pytest.mark.parametrize(
    ("change", "value"),
    (
        ("opcode", "AddAbilityTask"),
        ("execution_mode", "process_only"),
        ("coverage_status", "blocked"),
        ("blocked_reason", "fixture_blocked"),
        ("parent_task_id", "fixture:parent"),
    ),
)
def test_wrong_task_identity_is_not_accepted(change: str, value: str) -> None:
    task, _effect, graph, rules = _fixture()
    setattr(task, change, value)
    assert not _predicate(task, graph, rules)


@pytest.mark.parametrize(
    ("effect_opcode", "effect_coverage", "reference_definition_id"),
    (
        ("AddAbilityTask", "audit_only", "fixture:effect"),
        (None, "executable", "fixture:effect"),
        (None, "unsupported", "fixture:effect"),
        (None, "audit_only", "fixture:other"),
    ),
)
def test_wrong_effect_or_reference_identity_remains_blocked(
    effect_opcode: str | None,
    effect_coverage: str,
    reference_definition_id: str,
) -> None:
    task, _effect, graph, rules = _fixture(
        effect_opcode=effect_opcode,
        effect_coverage=effect_coverage,
        reference_definition_id=reference_definition_id,
    )
    assert not _predicate(task, graph, rules)
    assert AUDIT_BLOCKER in _project(task, rules).blocked_reasons


def test_additional_unresolved_reference_remains_blocked() -> None:
    task, _effect, graph, rules = _fixture(
        extra_references=(("target", "fixture:target", "deferred", "fixture_target_blocked"),)
    )
    assert not _predicate(task, graph, rules)
    assert "fixture_target_blocked" in _project(task, rules).blocked_reasons


def test_wrong_node_shape_or_owner_domains_are_not_accepted() -> None:
    task, _effect, graph, rules = _fixture(node_kind="branch")
    assert not _predicate(task, graph, rules)
    exact_task, _effect, exact_graph, exact_rules = _fixture()
    node = exact_graph.nodes[0]
    wrong_node = SimpleNamespace(
        **{
            **node.__dict__,
            "owner_domains": ("damage_heal_shield",),
        }
    )
    unresolved = tuple(
        reference
        for reference in wrong_node.references
        if reference.resolution_status != "resolved"
    )
    assert not _is_emission_backed_damage_audit_reference(
        exact_rules,
        exact_task,  # type: ignore[arg-type]
        wrong_node,  # type: ignore[arg-type]
        unresolved,
    )


def test_missing_or_invalid_damage_support_remains_blocked() -> None:
    task, _effect, graph, rules = _fixture(damage_emissions=())
    assert not _predicate(task, graph, rules)
    assert AUDIT_BLOCKER in _project(task, rules).blocked_reasons

    bad_emission = SimpleNamespace(
        damage_emission_id="fixture:damage",
        action_id=task.action_id,
        level=task.level,
        phase_id=task.phase_id,
        coverage_status="blocked",
        blocked_reason="fixture_damage_blocked",
        hit_profile_id="fixture:profile",
    )
    task, _effect, _graph_value, rules = _fixture(damage_emissions=(bad_emission,))
    projection = _project(task, rules)
    assert "fixture_damage_blocked" in projection.blocked_reasons
    assert AUDIT_BLOCKER in projection.blocked_reasons

    task, _effect, _graph_value, rules = _fixture(profiles={})
    projection = _project(task, rules)
    assert "hit_profile_missing_or_not_executable" in projection.blocked_reasons

    mismatched_toughness = SimpleNamespace(
        toughness_emission_id="fixture:toughness",
        action_id=task.action_id,
        level=task.level,
        phase_id=task.phase_id,
        coverage_status="executable",
        blocked_reason="",
        hit_profile_id="fixture:other_profile",
    )
    task, _effect, _graph_value, rules = _fixture(
        toughness_emissions=(mismatched_toughness,),
        profiles={
            "fixture:profile": SimpleNamespace(
                action_id="fixture:action", level=1, coverage_status="executable"
            ),
            "fixture:other_profile": SimpleNamespace(
                action_id="fixture:action", level=1, coverage_status="executable"
            ),
        },
    )
    projection = _project(task, rules)
    assert "damage_toughness_hit_profile_set_mismatch" in projection.blocked_reasons


def test_process_only_reference_behavior_is_unchanged() -> None:
    task, effect, graph, rules = _fixture(
        opcode="AuditTask",
        execution_mode="process_only",
        coverage_status="audit_only",
    )
    effect.source = task.source
    assert not _predicate(task, graph, rules)
    assert _project(task, rules).blocked_reasons == ()
