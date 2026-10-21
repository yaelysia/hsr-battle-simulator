"""Dropping evidence construction for a settled bucket keeps the retained catalog.

Once a raw type keeps the first 16 compatible structures, later nodes cannot clear or
promote that bucket, so they must be walked only for AbilityList candidates and child
nodes. The full file range, SHA manifests, candidate ordering and the first compatible
promotion are unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from hsr.simulator_v8_clean_core.tbgd import character_source_resolution as resolver

_CAPACITY = 16
_DEFINE_TYPE = "RPG.GameCore.DefineDynamicValue"
_REQUESTED = "Avatar_Test_00_Skill01"


def _incompatible_definition() -> dict[str, object]:
    """DefineDynamicValue with a usable target alias but no dynamic key role."""
    return {
        "$type": _DEFINE_TYPE,
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Target"},
        "DynamicKey": {},
    }


def _compatible_definition(alias: str = "Target") -> dict[str, object]:
    return {
        "$type": _DEFINE_TYPE,
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": alias},
        "DynamicKey": {"Value": "Stack"},
    }


def _write_package(root: Path, name: str, document: object) -> None:
    directory = root / resolver.PACKAGE_SEARCH_ROOT
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(document), encoding="utf-8")


def test_full_incompatible_bucket_still_promotes_later_compatible_evidence(
    tmp_path: Path,
) -> None:
    nodes = [_incompatible_definition() for _ in range(_CAPACITY)]
    nodes.append(_compatible_definition("Promoted"))
    _write_package(tmp_path, "definitions.json", {"Rows": nodes})
    result = resolver._package_index(tmp_path, frozenset())
    evidence = result[3][_DEFINE_TYPE]
    assert len(evidence) == 1
    assert {"target_alias", "dynamic_key"}.issubset(
        evidence[0].field_role_mapping.values()
    )
    assert evidence[0].source.evidence["json_path"] == "$.Rows[16]"


def test_settled_bucket_keeps_evidence_and_still_finds_nested_candidates(
    tmp_path: Path,
) -> None:
    compatible = [_compatible_definition(f"Target{index}") for index in range(_CAPACITY)]
    extras = [
        {**_compatible_definition("Later"), "AbilityList": [{"Name": _REQUESTED}]},
        _incompatible_definition(),
        {"Nested": [{"AbilityList": [{"Name": _REQUESTED}]}]},
    ]
    baseline_root = tmp_path / "baseline"
    extended_root = tmp_path / "extended"
    _write_package(baseline_root, "000-base.json", compatible)
    _write_package(extended_root, "000-base.json", compatible)
    _write_package(extended_root, "001-extra.json", extras)
    requested = frozenset({_REQUESTED})
    baseline = resolver._package_index(baseline_root, requested)
    with mock.patch.object(
        resolver,
        "_equivalent_evidence",
        wraps=resolver._equivalent_evidence,
    ) as spy:
        extended = resolver._package_index(extended_root, requested)
    assert len(baseline[3][_DEFINE_TYPE]) == _CAPACITY
    assert _REQUESTED not in baseline[2]
    assert extended[3] == baseline[3]
    built = [
        call
        for call in spy.call_args_list
        if call.kwargs["raw_type"] == _DEFINE_TYPE
    ]
    assert len(built) == _CAPACITY
    candidates = extended[2][_REQUESTED]
    assert {candidate.source.evidence["json_path"] for candidate in candidates} == {
        "$[0].AbilityList[0]",
        "$[2].Nested[0].AbilityList[0]",
    }
    assert [candidate.candidate_id for candidate in candidates] == sorted(
        candidate.candidate_id for candidate in candidates
    )
    assert resolver.PACKAGE_SEARCH_ROOT in next(iter(extended[0]))
    assert len(extended[0]) == 2
