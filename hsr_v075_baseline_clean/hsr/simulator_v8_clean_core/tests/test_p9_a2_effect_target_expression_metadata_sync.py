from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.rules.ir import EffectIR, IRSource
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _synchronize_effect_target_expression_metadata,
    _target_expression_from_raw,
)


PRE_CLOSURE_REASON = "target_alias_requires_source_closure:Caster"


def _expression(*, coverage_status: str = "executable", blocked_reason: str = ""):
    task_source = IRSource(
        "fixture/ability.json",
        "AbilityTask",
        "fixture:task",
        {"json_path": "$.AbilityList[0].OnStart[0]"},
    )
    expression = _target_expression_from_raw(
        {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
        field_name="TargetType",
        expression_id="target_expression:fixture:TargetType",
        source=task_source,
    )
    assert expression is not None
    return replace(
        expression,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _effect(expression, *, source=None, include_main_source: bool = True) -> EffectIR:
    reference = {
        "target_expression_id": expression.target_expression_id,
        "expression_kind": expression.expression_kind,
        "alias": expression.alias,
        "coverage_status": "blocked",
        "blocked_reason": PRE_CLOSURE_REASON,
        "source": dict(source or expression.source.to_json()),
    }
    standard = {
        "target_expression_id": expression.target_expression_id,
        "target_expression_kind": expression.expression_kind,
        "target_expression_coverage_status": "blocked",
        "target_expression_blocked_reason": PRE_CLOSURE_REASON,
        "target_expression_refs": {"TargetType": dict(reference)},
    }
    if include_main_source:
        standard["target_expression_source"] = dict(source or expression.source.to_json())
    return EffectIR(
        effect_id="effect:fixture",
        opcode="AddModifier",
        payload={
            "standard": standard,
            "target_expression_refs": {"TargetType": dict(reference)},
        },
        source=IRSource("fixture/ability.json", "AbilityTask", "fixture:effect", {"json_path": "$.AbilityList[0].OnStart[0]"}),
        coverage_status="audit_only",
        modifier_definition_id="modifier:fixture",
        status_callback_ids=("callback:fixture",),
        source_mode="mainline_avatar_ability",
        link_blocked_reason="fixture:link",
        owner_modifier_name="MFixture",
    )


def test_finalized_expression_refreshes_existing_metadata_without_effect_promotion() -> None:
    expression = _expression()
    effect = _effect(expression)

    synced = _synchronize_effect_target_expression_metadata([effect], [expression])[0]
    standard = synced.payload["standard"]
    assert standard["target_expression_id"] == expression.target_expression_id
    assert standard["target_expression_coverage_status"] == "executable"
    assert standard["target_expression_blocked_reason"] == ""
    assert standard["target_expression_source"] == expression.source.to_json()
    assert standard["target_expression_refs"]["TargetType"]["coverage_status"] == "executable"
    assert synced.payload["target_expression_refs"]["TargetType"]["blocked_reason"] == ""
    assert synced.coverage_status == effect.coverage_status
    assert synced.source == effect.source
    assert synced.effect_id == effect.effect_id
    assert synced.opcode == effect.opcode
    assert synced.status_callback_ids == effect.status_callback_ids
    assert synced.link_blocked_reason == effect.link_blocked_reason


def test_missing_main_source_uses_the_existing_exact_reference_proof() -> None:
    expression = _expression()
    effect = _effect(expression, include_main_source=False)

    synced = _synchronize_effect_target_expression_metadata([effect], [expression])[0]
    assert synced.payload["standard"]["target_expression_coverage_status"] == "executable"
    assert synced.payload["standard"]["target_expression_source"] == expression.source.to_json()


def test_source_mismatch_does_not_promote_main_or_reference_metadata() -> None:
    expression = _expression()
    effect = _effect(
        expression,
        source={"source_path": "fixture/foreign.json", "raw_type": "TargetExpression", "raw_id": expression.target_expression_id, "evidence": {"json_path": "$.foreign"}},
    )

    synced = _synchronize_effect_target_expression_metadata([effect], [expression])[0]
    assert synced == effect


def test_finalized_blocker_propagates_without_effect_coverage_promotion() -> None:
    expression = _expression(
        coverage_status="blocked",
        blocked_reason="target_language_dependency_blocked:alias:Caster",
    )
    effect = _effect(expression)

    synced = _synchronize_effect_target_expression_metadata([effect], [expression])[0]
    assert synced.payload["standard"]["target_expression_coverage_status"] == "blocked"
    assert synced.payload["standard"]["target_expression_blocked_reason"] == expression.blocked_reason
    assert synced.coverage_status == "audit_only"


def test_missing_and_unresolved_references_are_preserved() -> None:
    expression = _expression()
    effect = _effect(expression)
    payload = dict(effect.payload)
    standard = dict(payload["standard"])
    refs = dict(standard["target_expression_refs"])
    refs["OtherTarget"] = {
        "target_expression_id": "target_expression:missing",
        "coverage_status": "blocked",
        "blocked_reason": "fixture:missing",
        "source": expression.source.to_json(),
    }
    standard["target_expression_refs"] = refs
    payload["standard"] = standard
    payload["target_expression_refs"] = dict(refs)
    effect = replace(effect, payload=payload)
    no_reference = replace(effect, effect_id="effect:no-reference", payload={"standard": {}})

    synced, untouched = _synchronize_effect_target_expression_metadata(
        [effect, no_reference],
        [expression],
    )
    assert synced.payload["standard"]["target_expression_refs"]["TargetType"]["coverage_status"] == "executable"
    assert synced.payload["standard"]["target_expression_refs"]["OtherTarget"] == refs["OtherTarget"]
    assert untouched == no_reference


if __name__ == "__main__":
    test_finalized_expression_refreshes_existing_metadata_without_effect_promotion()
    test_missing_main_source_uses_the_existing_exact_reference_proof()
    test_source_mismatch_does_not_promote_main_or_reference_metadata()
    test_finalized_blocker_propagates_without_effect_coverage_promotion()
    test_missing_and_unresolved_references_are_preserved()
