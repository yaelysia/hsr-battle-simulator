from __future__ import annotations

import json
import time
import tracemalloc
from collections.abc import Mapping
from typing import Any

from ..ir_types import IRSource
from ..rules import (
    TaskGraphNumericDefinitionIR,
    TaskGraphWeightedChoiceIR,
    TaskGraphWeightedSelectionIR,
    task_graph_weighted_choice_id,
    task_graph_weighted_selection_id,
)
from ..rules.task_graph import (
    task_graph_numeric_id,
    task_graph_source_occurrence_id,
)


_FAMILY = "validation_fixture_random_config"
_GRAPH_NODE_ID = "validation_fixture:weighted_random_node"
_SOURCE_PATH = "validation_fixture/p9_s8c1a/RandomConfig.json"
_RAW_TYPE = "validation_fixture"
_RAW_ID = "p9_s8c1a_weighted_selection"
_CONTENT_SHA256 = "1" * 64
_PARENT_JSON_PATH = "$.RandomConfig"


def _source(json_path: str) -> IRSource:
    return IRSource(
        source_path=_SOURCE_PATH,
        raw_type=_RAW_TYPE,
        raw_id=_RAW_ID,
        evidence={
            "json_path": json_path,
            "content_sha256": _CONTENT_SHA256,
        },
    )


def _fixed(value: int) -> dict[str, Any]:
    return {
        "schema_version": "hsr.numeric_expression.v1",
        "kind": "fixed",
        "value": value,
        "supported": True,
    }


def _dynamic(hash_value: int) -> dict[str, Any]:
    return {
        "schema_version": "hsr.numeric_expression.v1",
        "kind": "dynamic_hash",
        "hash": hash_value,
        "supported": True,
    }


def _choice_and_definition(
    ordinal: int,
    expression: Mapping[str, Any],
    branch_id: str,
    *,
    json_path: str | None = None,
) -> tuple[TaskGraphWeightedChoiceIR, TaskGraphNumericDefinitionIR]:
    source = _source(
        json_path
        if json_path is not None
        else f"{_PARENT_JSON_PATH}.OddsList[{ordinal}]"
    )
    occurrence_id = task_graph_source_occurrence_id(source, _FAMILY)
    definition_id = task_graph_numeric_id(occurrence_id, expression)
    definition = TaskGraphNumericDefinitionIR(
        definition_id=definition_id,
        source_occurrence_id=occurrence_id,
        expression=expression,
        source=source,
    )
    choice = TaskGraphWeightedChoiceIR(
        choice_id=task_graph_weighted_choice_id(
            _GRAPH_NODE_ID,
            ordinal,
            branch_id,
            definition_id,
        ),
        graph_node_id=_GRAPH_NODE_ID,
        family=_FAMILY,
        ordinal=ordinal,
        branch_id=branch_id,
        weight_definition_id=definition_id,
        weight_source_occurrence_id=occurrence_id,
        source=source,
    )
    return choice, definition


def _selection(
    choices: tuple[TaskGraphWeightedChoiceIR, ...]
    | list[TaskGraphWeightedChoiceIR],
    definitions: tuple[TaskGraphNumericDefinitionIR, ...]
    | list[TaskGraphNumericDefinitionIR],
) -> TaskGraphWeightedSelectionIR:
    parent_source = _source(_PARENT_JSON_PATH)
    parent_occurrence_id = task_graph_source_occurrence_id(
        parent_source,
        _FAMILY,
    )
    return TaskGraphWeightedSelectionIR(
        selection_id=task_graph_weighted_selection_id(
            _GRAPH_NODE_ID,
            parent_occurrence_id,
        ),
        graph_node_id=_GRAPH_NODE_ID,
        parent_source_occurrence_id=parent_occurrence_id,
        family=_FAMILY,
        selection_kind="weighted_single",
        choices=choices,
        numeric_definitions=definitions,
        source=parent_source,
    )


def _expect_rejected(callable_: Any, subject: str) -> None:
    try:
        callable_()
    except (TypeError, ValueError):
        return
    raise AssertionError(f"{subject} was accepted")


def _assert_plain_json(value: object) -> None:
    if value is None or type(value) in {bool, int, float, str}:
        return
    if type(value) is list:
        for item in value:
            _assert_plain_json(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise AssertionError("JSON object key is not a plain string")
            _assert_plain_json(item)
        return
    raise AssertionError(f"non-plain JSON member:{type(value).__name__}")


def _legal_round_trip() -> TaskGraphWeightedSelectionIR:
    first_choice, first_definition = _choice_and_definition(
        0,
        _fixed(3),
        "validation_fixture:branch:0",
    )
    second_choice, second_definition = _choice_and_definition(
        1,
        _dynamic(90210),
        "validation_fixture:branch:1",
    )
    selection = _selection(
        (first_choice, second_choice),
        (first_definition, second_definition),
    )
    payload = selection.to_json()
    _assert_plain_json(payload)
    if TaskGraphWeightedSelectionIR.from_json(payload).to_json() != payload:
        raise AssertionError("weighted selection round-trip is unstable")
    return selection


def _equal_weights_keep_positional_identity() -> None:
    first_choice, first_definition = _choice_and_definition(
        0,
        _fixed(5),
        "validation_fixture:equal:0",
    )
    second_choice, second_definition = _choice_and_definition(
        1,
        _fixed(5),
        "validation_fixture:equal:1",
    )
    _selection(
        (first_choice, second_choice),
        (first_definition, second_definition),
    )
    if (
        first_choice.weight_source_occurrence_id
        == second_choice.weight_source_occurrence_id
        or first_definition.definition_id == second_definition.definition_id
        or first_choice.choice_id == second_choice.choice_id
    ):
        raise AssertionError("equal positional weights collapsed identity")


def _pairing_mismatch_is_rejected() -> None:
    first_choice, first_definition = _choice_and_definition(
        0,
        _fixed(2),
        "validation_fixture:pair:0",
    )
    second_choice, second_definition = _choice_and_definition(
        1,
        _fixed(7),
        "validation_fixture:pair:1",
    )
    _expect_rejected(
        lambda: _selection(
            (first_choice, second_choice),
            (second_definition, first_definition),
        ),
        "weighted choice/definition mismatch",
    )


def _wrong_parent_path_is_rejected() -> None:
    first_choice, first_definition = _choice_and_definition(
        0,
        _fixed(2),
        "validation_fixture:path:0",
    )
    bad_choice, bad_definition = _choice_and_definition(
        1,
        _fixed(7),
        "validation_fixture:path:1",
        json_path="$.OtherParent.OddsList[1]",
    )
    _expect_rejected(
        lambda: _selection(
            (first_choice, bad_choice),
            (first_definition, bad_definition),
        ),
        "weighted choice outside the parent OddsList path",
    )


def _forged_identity_is_rejected() -> None:
    choice, _definition = _choice_and_definition(
        0,
        _fixed(11),
        "validation_fixture:identity:0",
    )
    _expect_rejected(
        lambda: TaskGraphWeightedChoiceIR(
            choice_id="forged",
            graph_node_id=choice.graph_node_id,
            family=choice.family,
            ordinal=choice.ordinal,
            branch_id=choice.branch_id,
            weight_definition_id=choice.weight_definition_id,
            weight_source_occurrence_id=choice.weight_source_occurrence_id,
            source=choice.source,
        ),
        "forged weighted choice identity",
    )


def _strict_codec_is_exact() -> None:
    choice, definition = _choice_and_definition(
        0,
        _fixed(19),
        "validation_fixture:codec:0",
    )
    payload = _selection((choice,), (definition,)).to_json()

    unknown_field = json.loads(json.dumps(payload))
    unknown_field["unexpected"] = True
    _expect_rejected(
        lambda: TaskGraphWeightedSelectionIR.from_json(unknown_field),
        "weighted selection codec unknown field",
    )

    missing_field = json.loads(json.dumps(payload))
    missing_field.pop("family")
    _expect_rejected(
        lambda: TaskGraphWeightedSelectionIR.from_json(missing_field),
        "weighted selection codec missing field",
    )

    wrong_type = json.loads(json.dumps(payload))
    wrong_type["choices"][0]["ordinal"] = True
    _expect_rejected(
        lambda: TaskGraphWeightedSelectionIR.from_json(wrong_type),
        "weighted selection codec wrong member type",
    )

    forged_identity = json.loads(json.dumps(payload))
    forged_identity["choices"][0]["choice_id"] = "forged"
    _expect_rejected(
        lambda: TaskGraphWeightedSelectionIR.from_json(forged_identity),
        "weighted selection codec forged identity",
    )


def _input_and_output_are_isolated() -> None:
    first_choice, first_definition = _choice_and_definition(
        0,
        _fixed(13),
        "validation_fixture:isolation:0",
    )
    second_choice, second_definition = _choice_and_definition(
        1,
        _dynamic(17),
        "validation_fixture:isolation:1",
    )
    choices = [first_choice, second_choice]
    definitions = [first_definition, second_definition]
    selection = _selection(choices, definitions)
    choices.clear()
    definitions.clear()
    if len(selection.choices) != 2 or len(selection.numeric_definitions) != 2:
        raise AssertionError("constructor retained mutable member containers")

    payload = selection.to_json()
    payload["choices"][0]["source"]["evidence"]["json_path"] = "mutated"
    payload["numeric_definitions"][0]["expression"]["value"] = 999
    fresh = selection.to_json()
    if (
        fresh["choices"][0]["source"]["evidence"]["json_path"]
        != f"{_PARENT_JSON_PATH}.OddsList[0]"
        or fresh["numeric_definitions"][0]["expression"]["value"] != 13
    ):
        raise AssertionError("to_json leaked mutable model state")


def main() -> int:
    tracemalloc.start()
    started = time.perf_counter()
    _legal_round_trip()
    _equal_weights_keep_positional_identity()
    _pairing_mismatch_is_rejected()
    _wrong_parent_path_is_rejected()
    _forged_identity_is_rejected()
    _strict_codec_is_exact()
    _input_and_output_are_isolated()
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "ok": True,
                "fixture_kind": "validation_fixture",
                "cases": 7,
                "elapsed_seconds": round(elapsed, 6),
                "peak_memory_bytes": peak,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
