from __future__ import annotations

import random
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.ir_types import IRSource
from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutor
from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering,
    _StandaloneActionRef,
    _process_only_ability_task_source_blocked_reason,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_a2_p4_set_entity_visible_process_only_retirement import (
    PARTITION_A,
    PARTITION_B,
    PARTITION_C,
    PARTITION_D,
    _producer_partition_kind,
    _source_contract_reasons,
)


def _raw(**extra):
    return {
        "$type": "RPG.GameCore.SetEntityVisible",
        "TargetType": {"$type": "RPG.GameCore.TargetFetchAdvCharacter"},
        **extra,
    }


def _lower(tmp_path: Path, raw: dict):
    lowerer = TBGDLowering(tmp_path)
    return lowerer._lower_ability_task_tree(
        raw,
        definition=_StandaloneActionRef("fixture:action", 0),  # type: ignore[arg-type]
        phase_id="fixture:phase",
        ability_name="FixtureAbility",
        ability_path="Config/ConfigAbility/Avatar/Fixture.json",
        ability_index=None,
        callback_kind="OnStart",
        task_index=0,
        task_path="OnStart[0]",
        branch="root",
        parent_task_id="",
    )


def test_set_entity_visible_uses_process_only_authority() -> None:
    assert ability_task_execution_mode("SetEntityVisible") == "process_only"
    assert ability_task_execution_mode("SetEntityForceVisible") == "runtime_effect"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (_raw(), ""),
        (_raw(UniqueKey="Body"), ""),
        (_raw(Visible=False), ""),
        (_raw(Visible=True, UniqueKey="Body"), ""),
        (_raw(Unexpected=True), "process_only_task_unknown_fields:Unexpected"),
        (
            {**_raw(), "TargetType": "Caster"},
            "process_only_task_field_invalid:TargetType:mapping",
        ),
        (_raw(UniqueKey=7), "process_only_task_field_invalid:UniqueKey:string"),
        (_raw(Visible=1), "process_only_task_field_invalid:Visible:bool"),
    ],
)
def test_set_entity_visible_schema_is_strict(payload: dict, expected: str) -> None:
    assert _process_only_ability_task_source_blocked_reason(
        payload,
        "SetEntityVisible",
    ) == expected


def test_set_entity_visible_source_type_mismatch_fails_closed() -> None:
    payload = _raw()
    payload["$type"] = "RPG.GameCore.SetEntityForceVisible"
    assert (
        _process_only_ability_task_source_blocked_reason(
            payload,
            "SetEntityVisible",
        )
        == "process_only_task_source_type_mismatch"
    )


def test_generic_lowering_keeps_task_effect_identity_and_no_runtime_calls(
    tmp_path: Path,
) -> None:
    forbidden = AssertionError("runtime channel touched")
    with patch.object(
        TaskGraphExecutor,
        "execute",
        side_effect=forbidden,
    ) as execute_mock, patch.object(
        RuleEvaluator,
        "evaluate_condition_result",
        side_effect=forbidden,
    ) as condition_mock, patch.object(
        random,
        "random",
        side_effect=forbidden,
    ) as rng_mock:
        lowered = _lower(tmp_path, _raw(Visible=True, UniqueKey="Body"))

    assert execute_mock.call_count == 0
    assert condition_mock.call_count == 0
    assert rng_mock.call_count == 0
    assert len(lowered.ability_tasks) == 1
    assert len(lowered.effects) == 1
    task = lowered.ability_tasks[0]
    effect = lowered.effects[0]
    assert task.opcode == "SetEntityVisible"
    assert task.execution_mode == "process_only"
    assert task.coverage_status == "audit_only"
    assert task.blocked_reason == ""
    assert task.effect_id == effect.effect_id
    assert effect.opcode == task.opcode
    assert effect.coverage_status == "audit_only"
    assert effect.source == task.source
    contract = effect.payload["process_only_contract"]
    assert contract["schema_version"] == "ability_process_only_source_shape_v1"
    assert contract["opcode"] == "SetEntityVisible"
    assert contract["source_shape_status"] == "admitted"
    assert contract["blocked_reason"] == ""
    assert set(contract["source_field_types"]) == set(contract["source_fields"])


def test_source_identity_mismatch_is_not_silently_accepted() -> None:
    source = IRSource(
        "Config/ConfigAbility/Avatar/Fixture.json",
        "AbilityTask",
        "FixtureAbility",
        {
            "json_path": "$.AbilityList[0].OnStart[0]",
            "content_sha256": "a" * 64,
        },
    )
    assert _source_contract_reasons(
        source,
        source_path="Config/ConfigAbility/Avatar/Other.json",
        json_path="$.AbilityList[0].OnStart[0]",
        content_sha256="a" * 64,
        require_fingerprint=True,
    ) == ["source_location_mismatch"]
    assert _source_contract_reasons(
        source,
        source_path=source.source_path,
        json_path="$.AbilityList[0].OnStart[0]",
        content_sha256="b" * 64,
        require_fingerprint=True,
    ) == [
        "source_content_fingerprint_conflict",
        "source_content_fingerprint_missing_or_mismatch",
    ]


def test_partition_prefers_exact_ability_producer() -> None:
    assert _producer_partition_kind(
        ability_count=1,
        status_count=0,
        template_count=1,
        template_reference_count=1,
    ) == (PARTITION_A, "")


def test_status_callback_is_not_misclassified_as_missing_ability_task() -> None:
    assert _producer_partition_kind(
        ability_count=0,
        status_count=1,
        template_count=0,
        template_reference_count=0,
    ) == (PARTITION_B, "")


def test_unreferenced_template_is_no_formal_producer() -> None:
    assert _producer_partition_kind(
        ability_count=0,
        status_count=0,
        template_count=1,
        template_reference_count=0,
    ) == (PARTITION_C, "")


def test_referenced_template_without_expansion_requires_replan() -> None:
    assert _producer_partition_kind(
        ability_count=0,
        status_count=0,
        template_count=1,
        template_reference_count=1,
    ) == (PARTITION_D, "template_reference_missing_formal_expansion")


def test_ambiguous_formal_producer_fails_closed() -> None:
    assert _producer_partition_kind(
        ability_count=1,
        status_count=1,
        template_count=0,
        template_reference_count=0,
    ) == (PARTITION_D, "formal_producer_kind_ambiguous")
