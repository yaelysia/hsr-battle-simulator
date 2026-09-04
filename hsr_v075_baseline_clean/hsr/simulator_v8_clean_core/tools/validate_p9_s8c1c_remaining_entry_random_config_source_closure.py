from __future__ import annotations

import argparse
import json
import resource
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, Callable, cast

from ..ir_types import IRSource
from ..rules.task_graph import (
    EntryKind,
    TaskGraphBranchIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphWeightedSelectionIR,
    task_graph_branch_id,
    task_graph_entry_id,
    task_graph_id,
    task_graph_node_id,
    task_graph_source_occurrence_id,
)
from ..tbgd.task_graph_materializer import _materialize_weighted_selection


_FAST_HARD_SECONDS = 30.0
_FAST_RSS_LIMIT_KIB = 512 * 1024


@dataclass(frozen=True)
class _FixtureSnapshot:
    source_bytes: Mapping[str, bytes]


def _expect_rejected(action: Callable[[], object], subject: str) -> None:
    try:
        action()
    except (TypeError, ValueError, RuntimeError):
        return
    raise AssertionError(f"{subject} was accepted")


def _fixture(entry_kind: EntryKind) -> tuple[TaskGraphIR, TaskGraphWeightedSelectionIR]:
    raw_parent = {
        "$type": "RandomConfig",
        "OddsList": [2, 3],
        "ConfigList": [{}, {}],
    }
    payload = json.dumps({"Task": raw_parent}, sort_keys=True, separators=(",", ":")).encode()
    source = IRSource(
        "validation_fixture/p9_s8c1c.json",
        "RandomConfig",
        "fixture_random_config",
        {
            "json_path": "$.Task",
            "content_sha256": sha256(payload).hexdigest(),
            "source_opcode": "RandomConfig",
            "task_path": "fixture[0]",
        },
    )
    occurrence_id = task_graph_source_occurrence_id(source, "RandomConfig")
    owner_id = "fixture:status" if entry_kind == "status_callback" else "fixture:phase"
    callback_kind = "OnBeforeBeingHit" if entry_kind == "status_callback" else "OnStart"
    entry_id = task_graph_entry_id(entry_kind, owner_id, callback_kind)
    graph_id = task_graph_id("fixture:source_catalog", entry_id, source.evidence["content_sha256"])
    node_id = task_graph_node_id(graph_id, "fixture:task", occurrence_id)
    branches = tuple(
        TaskGraphBranchIR(
            branch_id=task_graph_branch_id(
                node_id,
                "config",
                ordinal,
                f"choice_{ordinal}",
                (),
            ),
            graph_node_id=node_id,
            branch_kind="config",
            ordinal=ordinal,
            label=f"choice_{ordinal}",
            child_node_ids=(),
            source=source,
        )
        for ordinal in range(2)
    )
    selection = _materialize_weighted_selection(
        cast(Any, _FixtureSnapshot({source.source_path: payload})),
        node_id,
        source,
        occurrence_id,
        branches,
    )
    node = TaskGraphNodeIR(
        graph_node_id=node_id,
        graph_id=graph_id,
        source_occurrence_id=occurrence_id,
        source_contract_node_id="fixture:control",
        formal_task_id="fixture:task",
        opcode="RandomConfig",
        source_family="RandomConfig",
        node_kind="deferred",
        branches=branches,
        references=(),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="deferred",
        owner_domains=("hit_random_sequence",),
        source=source,
        status_reason="fixture_random_config_deferred",
    )
    graph = TaskGraphIR(
        graph_id=graph_id,
        entry_id=entry_id,
        entry_kind=entry_kind,
        owner_id=owner_id,
        callback_kind=callback_kind,
        root_node_ids=(node_id,),
        nodes=(node,),
        numeric_definitions=(),
        source_catalog_id="fixture:source_catalog",
        source_fingerprint=source.evidence["content_sha256"],
        source=source,
        coverage_status="lowered_with_obligation",
        weighted_selections=(selection,),
    )
    return graph, selection


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    ability_graph, _ = _fixture("ability_phase_callback")
    status_graph, status_selection = _fixture("status_callback")

    if not ability_graph.weighted_selections or not status_graph.weighted_selections:
        raise AssertionError("formal entry fixture lost RandomConfig weighted selection")
    if TaskGraphIR.from_json(status_graph.to_json()).to_json() != status_graph.to_json():
        raise AssertionError("status weighted-selection TaskGraphIR codec is unstable")

    _expect_rejected(
        lambda: replace(status_graph, weighted_selections=()),
        "status RandomConfig graph without weighted selection",
    )
    _expect_rejected(
        lambda: replace(
            status_graph,
            weighted_selections=(status_selection, status_selection),
        ),
        "duplicate weighted selection for one RandomConfig node",
    )

    nonrandom_node = replace(
        status_graph.nodes[0],
        source_family="NotRandomConfig",
        opcode="NotRandomConfig",
        source_contract_node_id="",
        source=IRSource(
            status_graph.source.source_path,
            "NotRandomConfig",
            status_graph.source.raw_id,
            {
                **dict(status_graph.source.evidence),
                "source_opcode": "NotRandomConfig",
            },
        ),
    )
    _expect_rejected(
        lambda: replace(status_graph, nodes=(nonrandom_node,)),
        "weighted selection attached to non-RandomConfig node",
    )

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "ok": elapsed <= _FAST_HARD_SECONDS and peak <= _FAST_RSS_LIMIT_KIB,
        "mode": "fast",
        "cases": 5,
        "predicates": {
            "ability_path_preserved": True,
            "status_entry_accepts_weighted_selection": True,
            "status_missing_selection_fail_closed": True,
            "duplicate_selection_fail_closed": True,
            "non_random_selection_fail_closed": True,
        },
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fast",), default="fast")
    args = parser.parse_args()
    result = _run_fast()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
