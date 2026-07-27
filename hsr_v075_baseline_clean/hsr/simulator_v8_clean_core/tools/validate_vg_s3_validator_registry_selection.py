from __future__ import annotations

import argparse
import ast
import builtins
import contextlib
import importlib
import io
import json
import subprocess
import sys
import time
import types
from collections import Counter
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from .io import write_json


VALIDATION_VERSION = "vg_s3_validator_registry_selection_v2"


@dataclass(frozen=True, slots=True)
class ExpectedMode:
    entry_id: str
    module_name: str
    mode_id: str
    root_function: str
    lifecycle: str
    tier: str
    build_requirement: str
    reads_tbgd: bool
    full_lowering: bool
    rulebook_kind: str
    summary: str
    fixed_argv: tuple[str, ...] = ()
    cli_inputs: tuple[tuple[str, str, bool, bool], ...] = ()
    call_bounds: tuple[tuple[str, int, int | None], ...] = ()
    resource_identity: tuple[str, str, str] | None = None


def _mode(
    entry_id: str,
    module_name: str,
    mode_id: str,
    root_function: str,
    lifecycle: str,
    tier: str,
    build_requirement: str,
    reads_tbgd: bool,
    full_lowering: bool,
    rulebook_kind: str,
    summary: str,
    **kwargs: Any,
) -> ExpectedMode:
    return ExpectedMode(
        entry_id,
        module_name,
        mode_id,
        root_function,
        lifecycle,
        tier,
        build_requirement,
        reads_tbgd,
        full_lowering,
        rulebook_kind,
        summary,
        **kwargs,
    )


# Independent first-batch oracle. Multi-mode resource facts include static
# call bounds so a duplicated registry label cannot prove itself.
EXPECTED_MODES = (
    _mode(
        "vg.s1.committed_state_immutability.direct",
        "validate_vg_s1_committed_state_immutability",
        "default",
        "run_validation",
        "active_contract",
        "direct",
        "none",
        False,
        False,
        "none",
        "validation_summary_vg_s1_committed_state_immutability.json",
    ),
    _mode(
        "vg.s2.committed_integrity_lifecycle.direct",
        "validate_vg_s2_committed_integrity_lifecycle",
        "default",
        "run_validation",
        "active_contract",
        "direct",
        "small_fixture_rulebook",
        False,
        False,
        "small_fixture",
        "validation_summary_vg_s2_committed_integrity_lifecycle.json",
    ),
    _mode(
        "p7.s2.mutation_reducer_contract.direct",
        "validate_p7_s2_mutation_reducer_contract",
        "default",
        "run_validation",
        "active_contract",
        "direct",
        "none",
        False,
        False,
        "none",
        "validation_summary_p7_s2_mutation_reducer_contract.json",
    ),
    _mode(
        "p7.s3.selected_graph_atomic_commit.direct",
        "validate_p7_s3_selected_graph_atomic_commit",
        "default",
        "run_validation",
        "active_contract",
        "direct",
        "small_fixture_rulebook",
        False,
        False,
        "small_fixture",
        "validation_summary_p7_s3_selected_graph_atomic_commit.json",
    ),
    _mode(
        "p7.s15.rng_identity_replay.direct",
        "validate_p7_s15_rng_identity_replay",
        "default",
        "run_validation",
        "active_contract",
        "direct",
        "none",
        False,
        False,
        "none",
        "validation_summary_p7_s15_rng_identity_replay.json",
    ),
    _mode(
        "p8.s1.equipment_type_contract.direct",
        "validate_p8_s1_equipment_type_contract",
        "default",
        "run_validation",
        "active_contract",
        "direct",
        "small_fixture_rulebook",
        False,
        False,
        "small_fixture",
        "validation_summary_p8_s1_equipment_type_contract.json",
        cli_inputs=(("s0_summary", "--s0-summary", True, True),),
    ),
    _mode(
        "p8.s2.character_build.fixture",
        "validate_p8_s2_character_build_base_panel",
        "fixture_only",
        "run_fixture_contract_validation",
        "active_contract",
        "direct",
        "small_fixture_rulebook",
        False,
        False,
        "small_fixture",
        "validation_summary_p8_s2_fixture_contract.json",
        fixed_argv=("--fixture-only",),
        call_bounds=(("RuleBook", 1, None), ("TBGDLowering", 0, 0)),
    ),
    _mode(
        "p8.s2.character_card_source.catalog",
        "validate_p8_s2_character_build_base_panel",
        "character_card_source_only",
        "run_character_card_source_validation",
        "catalog_audit",
        "catalog",
        "source_inventory",
        True,
        False,
        "focused_source",
        "validation_summary_p8_s2_character_card_source.json",
        fixed_argv=("--character-card-source-only",),
        cli_inputs=(("tbgd_root", "--tbgd-root", False, True),),
        call_bounds=(
            ("RuleBook", 2, 2),
            ("TBGDLowering", 0, 0),
            ("build_character_card_ir", 1, None),
            ("build_character_action_definition_ir", 1, None),
        ),
        resource_identity=(
            "tbgd.character_card_tables",
            "build_character_card_ir+build_character_action_definition_ir",
            "character_card_ir+focused_character_rulebooks",
        ),
    ),
    _mode(
        "p8.s2.character_build.complete_catalog",
        "validate_p8_s2_character_build_base_panel",
        "default",
        "run_validation",
        "catalog_audit",
        "full",
        "full_lowering_rulebook",
        True,
        True,
        "full_lowering",
        "validation_summary_p8_s2_character_build_base_panel.json",
        cli_inputs=(("tbgd_root", "--tbgd-root", False, True),),
        call_bounds=(("RuleBook", 1, None), ("TBGDLowering", 1, None)),
    ),
    _mode(
        "p8.r1.summon_halo.runtime",
        "validate_p8_r1_summon_runtime_halo_lifecycle",
        "runtime_only",
        "_runtime_validation",
        "active_contract",
        "direct",
        "small_fixture_rulebook",
        False,
        False,
        "small_fixture",
        "validation_summary_p8_r1_summon_runtime_halo_lifecycle.json",
        fixed_argv=("--runtime-only",),
        cli_inputs=(("tbgd_root", "--tbgd-root", True, False),),
        call_bounds=(("RuleBook", 1, None), ("build_light_cone_catalog", 0, 0)),
    ),
    _mode(
        "p8.r1.summon_halo.source_catalog",
        "validate_p8_r1_summon_runtime_halo_lifecycle",
        "source_catalog_only",
        "_source_catalog_validation",
        "catalog_audit",
        "catalog",
        "source_inventory",
        True,
        False,
        "none",
        "validation_summary_p8_r1_summon_runtime_halo_lifecycle.json",
        fixed_argv=("--source-catalog-only",),
        cli_inputs=(("tbgd_root", "--tbgd-root", True, True),),
        call_bounds=(("RuleBook", 0, 0), ("build_light_cone_catalog", 1, None)),
        resource_identity=(
            "tbgd.light_cone_catalog_and_ability_files",
            "build_light_cone_catalog",
            "light_cone_catalog+source_hash_matrix",
        ),
    ),
    _mode(
        "p8.s8.light_cone.catalog_startup",
        "validate_p8_s8_light_cone_remaining_gameplay_closure",
        "catalog_startup_only",
        "run_catalog_startup_validation",
        "catalog_audit",
        "catalog",
        "full_lowering_rulebook",
        True,
        True,
        "focused_source",
        "validation_summary_p8_s8_catalog_startup.json",
        fixed_argv=("--catalog-startup-only",),
        cli_inputs=(("tbgd_root", "--tbgd-root", True, True),),
        call_bounds=(
            ("_focused_bundle", 1, None),
            ("RuleBook", 1, None),
            ("TBGDLowering", 1, None),
        ),
    ),
    *(
        _mode(
            entry_id,
            module,
            "default",
            "run_validation",
            "historical_evidence",
            "full",
            "full_lowering_rulebook",
            True,
            True,
            "full_lowering",
            summary,
            cli_inputs=(("tbgd_root", "--tbgd-root", False, True),),
        )
        for entry_id, module, summary in (
            (
                "p7.current_tree.shared_aggregate.history",
                "validate_p7_current_tree_shared_regressions",
                "p7_current_tree_shared_regression_manifest.json",
            ),
            (
                "p1.phase1.aggregate.history",
                "validate_p1_9_phase1_aggregate",
                "validation_summary_p1_9_phase1_aggregate.json",
            ),
            (
                "p2.status.aggregate.history",
                "validate_p2_status_system_complete",
                "validation_summary_p2_status_system_complete.json",
            ),
            (
                "p3.summon.aggregate.history",
                "validate_p3_summon_assistant_servant_complete",
                "validation_summary_p3_summon_assistant_servant_complete.json",
            ),
            (
                "v0.209.full_pipeline.history",
                "validate_v0_209",
                "validation_summary_v0_209.json",
            ),
        )
    ),
)


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    modules, import_probe = _load_governance_modules()
    registry_module, selection_module, cli_module = modules
    registry = registry_module.load_default_registry()
    entry_matrix = _entry_matrix(package_root, registry)
    selection_matrix, manifests = _selection_matrix(registry, selection_module)
    side_effects = _dry_run_probe(cli_module, registry)
    boundary = _static_boundary(package_root)
    scope_audit = _git_scope_audit(package_root)
    immutability = _immutability(registry_module, selection_module, registry)
    negatives = _negative_matrix(
        registry_module,
        selection_module,
        registry,
        manifests,
        side_effects,
        immutability,
    )
    docs = _docs_check(package_root)
    predicates = _predicates(
        registry,
        entry_matrix,
        selection_matrix,
        manifests,
        import_probe,
        side_effects,
        boundary,
        scope_audit,
        immutability,
        negatives,
    )
    ok = (
        _predicates_ok(predicates)
        and entry_matrix["summary"]["ok"]
        and selection_matrix["summary"]["ok"]
        and negatives["summary"]["ok"]
        and boundary["ok"]
        and scope_audit["ok"]
        and docs["ok"]
    )
    result = {
        "version": VALIDATION_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "predicates": predicates,
        "summary": {
            "registered_entry_count": len(registry.entries),
            "entry_matrix_passed": entry_matrix["summary"]["passed"],
            "selection_case_count": selection_matrix["summary"]["case_count"],
            "negative_case_count": negatives["summary"]["case_count"],
            "negative_cases_passed": negatives["summary"]["passed"],
        },
        "registry": {
            "schema_version": registry.schema_version,
            "fingerprint": registry.fingerprint,
        },
        "side_effect_probe": side_effects,
        "static_boundary": boundary,
        "git_scope_audit": scope_audit,
        "immutability": immutability,
        "workflow_docs": docs,
        "resource_budget": {
            **{
                key: side_effects[key]
                for key in (
                    "validator_import_count",
                    "validation_call_count",
                    "subprocess_count",
                    "file_read_count",
                    "tbgd_read_count",
                    "rulebook_build_count",
                    "full_lowering_build_count",
                    "validator_output_directory_count",
                )
            },
            "parallel_worker_count": 0,
            "elapsed_seconds_observed": time.perf_counter() - started,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "summary": (
            "validation_summary_vg_s3_validator_registry_selection.json",
            result,
        ),
        "entries": ("vg_s3_registry_entry_matrix.json", entry_matrix),
        "selection": ("vg_s3_selection_matrix.json", selection_matrix),
        "negative": ("vg_s3_negative_matrix.json", negatives),
    }
    for filename, payload in outputs.values():
        write_json(output_dir / filename, payload)
    return result


def _load_governance_modules() -> tuple[tuple[Any, Any, Any], dict[str, Any]]:
    before = set(sys.modules)
    names = (
        "simulator_v8_clean_core.tools.validation_registry",
        "simulator_v8_clean_core.tools.validation_selection",
        "simulator_v8_clean_core.tools.select_validations",
    )
    loaded = tuple(importlib.import_module(name) for name in names)
    validator_imports = tuple(
        sorted(
            name
            for name in set(sys.modules) - before
            if name.startswith("simulator_v8_clean_core.tools.validate_")
        )
    )
    return loaded, {
        "validator_import_count": len(validator_imports),
        "validator_modules": validator_imports,
    }


def _entry_matrix(package_root: Path, registry: Any) -> dict[str, Any]:
    rows = []
    for expected in EXPECTED_MODES:
        try:
            entry = registry.get(expected.entry_id)
        except KeyError:
            rows.append({"entry_id": expected.entry_id, "ok": False, "reason": "missing"})
            continue
        source_path = package_root / "tools" / f"{expected.module_name}.py"
        source = source_path.read_text(encoding="utf-8")
        flags = _argparse_flags(source)
        actual_inputs = tuple(
            (
                item.input_id,
                item.flag,
                item.cli_required,
                item.semantic_required,
            )
            for item in entry.cli_inputs
        )
        resource = entry.resources
        actual = (
            entry.module.rsplit(".", 1)[-1],
            entry.mode_id,
            entry.lifecycle_classification,
            entry.tier,
            resource.build_requirement,
            resource.reads_tbgd,
            resource.full_lowering_required,
            resource.rulebook_build_kind,
            entry.summary_relative_path,
            entry.fixed_argv,
            actual_inputs,
        )
        wanted = (
            expected.module_name,
            expected.mode_id,
            expected.lifecycle,
            expected.tier,
            expected.build_requirement,
            expected.reads_tbgd,
            expected.full_lowering,
            expected.rulebook_kind,
            expected.summary,
            expected.fixed_argv,
            expected.cli_inputs,
        )
        cli_ok = (
            all(flag in flags for flag in expected.fixed_argv)
            and all(
                flag in flags and flags[flag] is required
                for _input_id, flag, required, _semantic in expected.cli_inputs
            )
            and "--output-dir" in flags
            and _summary_present(source, expected.summary)
        )
        counts = _function_call_counts(source, expected.root_function)
        call_checks = {
            name: (
                counts[name] >= minimum
                and (maximum is None or counts[name] <= maximum)
            )
            for name, minimum, maximum in expected.call_bounds
        }
        identity_ok = (
            expected.resource_identity is None
            or expected.resource_identity
            == (
                resource.source_identity,
                resource.builder_identity,
                resource.artifact_identity,
            )
        )
        rows.append(
            {
                "entry_id": expected.entry_id,
                "ok": actual == wanted
                and cli_ok
                and all(call_checks.values())
                and identity_ok,
                "classification_matches": actual == wanted,
                "cli_contract_matches": cli_ok,
                "resource_call_chain_matches": all(call_checks.values()),
                "resource_identity_matches": identity_ok,
                "observed_calls": {
                    name: counts[name]
                    for name, _minimum, _maximum in expected.call_bounds
                },
                "call_checks": call_checks,
            }
        )
    expected_ids = {item.entry_id for item in EXPECTED_MODES}
    unexpected = sorted(set(registry.entry_ids) - expected_ids)
    return {
        "schema_version": "vg-s3.independent-entry-oracle.v2",
        "summary": {
            "ok": len(rows) == 17
            and not unexpected
            and all(row["ok"] for row in rows),
            "expected": 17,
            "actual": len(registry.entries),
            "passed": sum(row["ok"] for row in rows),
            "unexpected_entry_ids": unexpected,
        },
        "rows": rows,
    }


def _argparse_flags(source: str) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.startswith("--")
        ):
            flags[node.args[0].value] = any(
                keyword.arg == "required"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
    return flags


def _summary_present(source: str, expected: str) -> bool:
    tree = ast.parse(source)
    calls = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and node.args
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "write_json"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "write_json"
        )
    )
    if any(
        any(
            isinstance(node, ast.Constant) and node.value == expected
            for node in ast.walk(call.args[0])
        )
        for call in calls
    ):
        return True
    for function in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        assignments = _direct_assignments(function)
        for mapping_name, value in assignments.items():
            if not isinstance(value, ast.DictComp):
                continue
            summary_values = _dictcomp_summary_values(value, assignments)
            if summary_values != {expected}:
                continue
            if any(
                _writes_mapping_summary(call.args[0], mapping_name)
                for call in calls
                if call in set(ast.walk(function))
            ):
                return True
    return False


def _direct_assignments(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, ast.AST]:
    grouped: dict[str, list[ast.AST]] = {}
    for statement in function.body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                grouped.setdefault(target.id, []).append(statement.value)
    return {
        name: values[0]
        for name, values in grouped.items()
        if len(values) == 1
    }


def _static_string(
    node: ast.AST,
    bindings: dict[str, str],
    assignments: dict[str, ast.AST],
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in bindings:
            return bindings[node.id]
        if node.id in seen or node.id not in assignments:
            return None
        return _static_string(
            assignments[node.id],
            bindings,
            assignments,
            seen | {node.id},
        )
    if isinstance(node, ast.FormattedValue):
        return _static_string(node.value, bindings, assignments, seen)
    if isinstance(node, ast.JoinedStr):
        parts = [
            _static_string(value, bindings, assignments, seen)
            for value in node.values
        ]
        return None if any(part is None for part in parts) else "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _static_string(node.right, bindings, assignments, seen)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left, bindings, assignments, seen)
        right = _static_string(node.right, bindings, assignments, seen)
        return None if left is None or right is None else left + right
    return None


def _dictcomp_summary_values(
    node: ast.DictComp,
    assignments: dict[str, ast.AST],
) -> set[str]:
    if len(node.generators) != 1 or node.generators[0].ifs:
        return set()
    generator = node.generators[0]
    target = generator.target
    if not (
        isinstance(target, (ast.Tuple, ast.List))
        and all(isinstance(item, ast.Name) for item in target.elts)
    ):
        return set()
    try:
        items = ast.literal_eval(generator.iter)
    except (ValueError, TypeError):
        return set()
    values = set()
    for item in items:
        if not (
            isinstance(item, (tuple, list))
            and len(item) == len(target.elts)
            and all(isinstance(part, str) for part in item)
        ):
            return set()
        bindings = {
            name.id: part
            for name, part in zip(target.elts, item)
        }
        if _static_string(node.key, bindings, assignments) != "summary":
            continue
        value = _static_string(node.value, bindings, assignments)
        if value is not None:
            values.add(value)
    return values


def _writes_mapping_summary(node: ast.AST, mapping_name: str) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == mapping_name
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "summary"
    )


def _function_call_counts(source: str, root: str) -> Counter[str]:
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if root not in functions:
        return Counter()
    counts: Counter[str] = Counter()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited or name not in functions:
            return
        visited.add(name)
        local_calls: set[str] = set()
        for node in ast.walk(functions[name]):
            if not isinstance(node, ast.Call):
                continue
            call_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if call_name:
                counts[call_name] += 1
                if call_name in functions:
                    local_calls.add(call_name)
        for called in sorted(local_calls):
            visit(called)

    visit(root)
    return counts


def _request(selection: Any, **kwargs: Any) -> Any:
    return selection.SelectionRequest(
        intent=kwargs.get("intent", "direct"),
        entry_ids=tuple(kwargs.get("entry_ids", ())),
        triggers=tuple(kwargs.get("triggers", ())),
        domains=tuple(kwargs.get("domains", ())),
        output_root=kwargs.get("output_root", "/tmp/vg_s3_selection"),
        external_inputs=tuple(
            selection.ExternalInputValue(input_id, value)
            for input_id, value in kwargs.get("inputs", ())
        ),
        heavy_plan_confirmed=kwargs.get("heavy", False),
    )


def _select(registry: Any, selection: Any, **kwargs: Any) -> Any:
    return selection.build_selection_manifest(
        registry, _request(selection, **kwargs)
    )


def _selection_matrix(
    registry: Any, selection: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    cases = {
        "direct_exact": _select(
            registry,
            selection,
            entry_ids=("vg.s1.committed_state_immutability.direct",),
        ),
        "direct_trigger": _select(
            registry,
            selection,
            triggers=("lifecycle_contract_changed",),
            inputs=(("tbgd_root", "/tmp/vg_s3_not_read"),),
        ),
        "domain_narrow": _select(
            registry,
            selection,
            triggers=("lifecycle_contract_changed",),
            domains=("committed_integrity",),
        ),
        "catalog_heavy": _select(
            registry,
            selection,
            intent="catalog",
            entry_ids=("p8.s8.light_cone.catalog_startup",),
            inputs=(("tbgd_root", "/tmp/vg_s3_not_read"),),
            heavy=True,
        ),
        "p8_source_pair": _select(
            registry,
            selection,
            intent="catalog",
            entry_ids=(
                "p8.s2.character_card_source.catalog",
                "p8.r1.summon_halo.source_catalog",
            ),
            inputs=(("tbgd_root", "/tmp/vg_s3_not_read"),),
            heavy=True,
        ),
        "fixture": _select(
            registry,
            selection,
            entry_ids=("p8.s2.character_build.fixture",),
        ),
        "runtime": _select(
            registry,
            selection,
            entry_ids=("p8.r1.summon_halo.runtime",),
            inputs=(("tbgd_root", "/tmp/vg_s3_cli_only"),),
        ),
        "history_blocked": _select(
            registry,
            selection,
            entry_ids=("p7.current_tree.shared_aggregate.history",),
        ),
        "missing_input": _select(
            registry,
            selection,
            entry_ids=("p8.s1.equipment_type_contract.direct",),
        ),
    }
    permutation_a = _select(
        registry,
        selection,
        entry_ids=(
            "p8.r1.summon_halo.runtime",
            "p8.s1.equipment_type_contract.direct",
        ),
        inputs=(
            ("tbgd_root", "/tmp/vg_s3_tbgd"),
            ("s0_summary", "/tmp/vg_s3_s0.json"),
        ),
    )
    permutation_b = _select(
        registry,
        selection,
        entry_ids=(
            "p8.s1.equipment_type_contract.direct",
            "p8.r1.summon_halo.runtime",
        ),
        inputs=(
            ("s0_summary", "/tmp/vg_s3_s0.json"),
            ("tbgd_root", "/tmp/vg_s3_tbgd"),
        ),
    )
    cases["permutation_a"] = permutation_a
    cases["permutation_b"] = permutation_b
    expected_ok = {
        "history_blocked": False,
        "missing_input": False,
    }
    rows = []
    for case_id, manifest in cases.items():
        wanted = expected_ok.get(case_id, True)
        atomic = wanted or (
            bool(manifest.blocked_issues)
            and not manifest.selected_entries
            and not manifest.build_groups
        )
        rows.append(
            {
                "case_id": case_id,
                "ok": manifest.ok is wanted and atomic,
                "actual_ok": manifest.ok,
                "selected": [
                    item.entry_id for item in manifest.selected_entries
                ],
                "issue_codes": [item.code for item in manifest.blocked_issues],
            }
        )
    source_pair = cases["p8_source_pair"]
    source_groups_separate = (
        source_pair.ok
        and len(source_pair.build_groups) == 2
        and all(len(group.entry_ids) == 1 for group in source_pair.build_groups)
        and len(
            {
                (
                    group.source_identity,
                    group.builder_identity,
                    group.artifact_identity,
                )
                for group in source_pair.build_groups
            }
        )
        == 2
    )
    checks = {
        "trigger_only_active_direct": {
            item.entry_id for item in cases["direct_trigger"].selected_entries
        }
        == {
            "p8.r1.summon_halo.runtime",
            "vg.s2.committed_integrity_lifecycle.direct",
        },
        "domain_narrows": [
            item.entry_id for item in cases["domain_narrow"].selected_entries
        ]
        == ["vg.s2.committed_integrity_lifecycle.direct"],
        "fixture_flag_preserved": "--fixture-only"
        in cases["fixture"].selected_entries[0].argv,
        "runtime_cli_semantics_separate": (
            "--runtime-only" in cases["runtime"].selected_entries[0].argv
            and cases["runtime"].selected_entries[0].reads_tbgd is False
            and cases["runtime"].selected_entries[0]
            .cli_inputs[0]
            .semantic_required
            is False
        ),
        "source_build_groups_separate": source_groups_separate,
        "permutation_stable": permutation_a.to_json() == permutation_b.to_json(),
    }
    return (
        {
            "schema_version": "vg-s3.selection-matrix.v2",
            "summary": {
                "ok": all(row["ok"] for row in rows)
                and all(checks.values()),
                "case_count": len(rows),
                "passed": sum(row["ok"] for row in rows),
            },
            "checks": checks,
            "rows": rows,
        },
        cases,
    )


class _ValidatorSentinel(types.ModuleType):
    def __init__(self, name: str, counts: dict[str, int]) -> None:
        super().__init__(name)
        self._counts = counts

    def __getattr__(self, _name: str) -> Callable[..., Any]:
        def called(*_args: Any, **_kwargs: Any) -> Any:
            self._counts["validation_call_count"] += 1
            raise AssertionError("dry-run called a validator")

        return called


def _dry_run_probe(cli_module: Any, registry: Any) -> dict[str, Any]:
    counts = {
        "validator_import_count": 0,
        "production_import_count": 0,
        "validation_call_count": 0,
        "subprocess_count": 0,
        "file_read_count": 0,
        "tbgd_read_count": 0,
        "rulebook_build_count": 0,
        "full_lowering_build_count": 0,
        "validator_output_directory_count": 0,
        "file_write_count": 0,
    }
    original_import = builtins.__import__
    original_import_module = importlib.import_module
    validator_names = {entry.module for entry in registry.entries}

    class FakeRuleBook:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            counts["rulebook_build_count"] += 1

    class FakeLowering:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def build(self) -> None:
            counts["full_lowering_build_count"] += 1

    fake_rules = types.ModuleType("simulator_v8_clean_core.rules")
    fake_rules.__path__ = []
    fake_rulebook = types.ModuleType(
        "simulator_v8_clean_core.rules.rulebook"
    )
    fake_rulebook.RuleBook = FakeRuleBook
    fake_tbgd = types.ModuleType("simulator_v8_clean_core.tbgd")
    fake_tbgd.__path__ = []
    fake_lowering = types.ModuleType(
        "simulator_v8_clean_core.tbgd.lowering"
    )
    fake_lowering.TBGDLowering = FakeLowering
    sentinels: dict[str, Any] = {
        name: _ValidatorSentinel(name, counts) for name in validator_names
    }
    sentinels.update(
        {
            fake_rules.__name__: fake_rules,
            fake_rulebook.__name__: fake_rulebook,
            fake_tbgd.__name__: fake_tbgd,
            fake_lowering.__name__: fake_lowering,
        }
    )

    def classify(name: str) -> None:
        if name in validator_names:
            counts["validator_import_count"] += 1
        if name.startswith(
            (
                "simulator_v8_clean_core.rules",
                "simulator_v8_clean_core.tbgd",
            )
        ):
            counts["production_import_count"] += 1

    def guarded_import(
        name: str,
        globals_value: Any = None,
        locals_value: Any = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        classify(name)
        return original_import(
            name, globals_value, locals_value, fromlist, level
        )

    def guarded_import_module(name: str, package: str | None = None) -> Any:
        classify(name)
        return original_import_module(name, package)

    def subprocess_call(*_args: Any, **_kwargs: Any) -> Any:
        counts["subprocess_count"] += 1
        raise AssertionError("dry-run spawned subprocess")

    def file_read(path: Any, *_args: Any, **_kwargs: Any) -> Any:
        text = str(path)
        counts["file_read_count"] += 1
        if "tbgd" in text.lower() or "turnbasedgamedata" in text.lower():
            counts["tbgd_read_count"] += 1
        raise AssertionError("dry-run read a file")

    def mkdir(path: Any, *_args: Any, **_kwargs: Any) -> Any:
        counts["validator_output_directory_count"] += 1
        raise AssertionError(f"dry-run created directory: {path}")

    def file_write(path: Any, *_args: Any, **_kwargs: Any) -> Any:
        counts["file_write_count"] += 1
        raise AssertionError(f"dry-run wrote file: {path}")

    stdout = io.StringIO()
    error = ""
    return_code: int | None = None
    try:
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(sys.modules, sentinels))
            stack.enter_context(
                mock.patch("builtins.__import__", new=guarded_import)
            )
            stack.enter_context(
                mock.patch.object(
                    importlib, "import_module", new=guarded_import_module
                )
            )
            for name in ("Popen", "run", "call", "check_call", "check_output"):
                stack.enter_context(
                    mock.patch.object(subprocess, name, new=subprocess_call)
                )
            stack.enter_context(mock.patch("builtins.open", new=file_read))
            for name in ("open", "read_text", "read_bytes"):
                stack.enter_context(
                    mock.patch.object(Path, name, new=file_read)
                )
            stack.enter_context(mock.patch.object(Path, "mkdir", new=mkdir))
            for name in ("write_text", "write_bytes"):
                stack.enter_context(
                    mock.patch.object(Path, name, new=file_write)
                )
            with contextlib.redirect_stdout(stdout):
                return_code = cli_module.main(
                    [
                        "select",
                        "--dry-run",
                        "--intent",
                        "direct",
                        "--id",
                        "vg.s1.committed_state_immutability.direct",
                        "--output-root",
                        "/tmp/vg_s3_side_effect_probe",
                    ]
                )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "ok": return_code == 0
        and not error
        and all(value == 0 for value in counts.values()),
        "cli_return_code": return_code,
        "stdout": stdout.getvalue().strip(),
        "error": error,
        **counts,
    }


def _immutability(registry_module: Any, selection: Any, registry: Any) -> dict[str, Any]:
    frozen_checks = []
    entry = registry.entries[0]
    for target, field, value in (
        (registry, "entries", ()),
        (entry, "entry_id", "changed"),
        (entry.resources, "reads_tbgd", True),
    ):
        try:
            setattr(target, field, value)
            frozen_checks.append(False)
        except (FrozenInstanceError, AttributeError, TypeError):
            frozen_checks.append(True)
    registry_payload = registry.to_json()
    fingerprint = registry.fingerprint
    registry_payload["entries"].clear()
    exported_copy_isolated = registry.fingerprint == fingerprint

    manifest = _select(
        registry,
        selection,
        entry_ids=("vg.s1.committed_state_immutability.direct",),
    )
    plan = manifest.selected_entries[0]
    group = manifest.build_groups[0]
    argv = list(plan.argv)
    domains = list(plan.domains)
    rendered_inputs = list(plan.cli_inputs)
    entry_ids = list(group.entry_ids)
    selected = [replace(plan, argv=argv, domains=domains, cli_inputs=rendered_inputs)]
    groups = [replace(group, entry_ids=entry_ids)]
    excluded = list(manifest.excluded_entries)
    external_manifest = replace(
        manifest,
        selected_entries=selected,
        build_groups=groups,
        excluded_entries=excluded,
    )
    before = external_manifest.to_json()
    argv.append("--injected")
    domains.append("lifecycle")
    rendered_inputs.clear()
    entry_ids.append("injected.entry")
    selected.clear()
    groups.clear()
    excluded.clear()
    selection_alias_isolated = external_manifest.to_json() == before

    entries = [entry]
    copied_registry = registry_module.ValidationRegistry(entries)
    entries.clear()
    registry_alias_isolated = len(copied_registry.entries) == 1
    checks = {
        "frozen_assignments_rejected": all(frozen_checks),
        "exported_json_copy_isolated": exported_copy_isolated,
        "registry_source_list_isolated": registry_alias_isolated,
        "selection_nested_lists_isolated": selection_alias_isolated,
    }
    return {"ok": all(checks.values()), "checks": checks}


def _selection_blocked(case_id: str, manifest: Any, code: str) -> dict[str, Any]:
    codes = [issue.code for issue in manifest.blocked_issues]
    return {
        "case_id": case_id,
        "ok": (
            not manifest.ok
            and codes == [code]
            and not manifest.selected_entries
            and not manifest.build_groups
        ),
        "expected_code": code,
        "actual_codes": codes,
    }


def _error_case(
    case_id: str,
    action: Callable[[], Any],
    expected_code: str,
    error_types: tuple[type[Exception], ...],
) -> dict[str, Any]:
    actual = ""
    try:
        action()
    except error_types as exc:
        actual = str(getattr(exc, "code", ""))
    return {
        "case_id": case_id,
        "ok": actual == expected_code,
        "expected_code": expected_code,
        "actual_code": actual,
    }


def _negative_matrix(
    registry_module: Any,
    selection: Any,
    registry: Any,
    manifests: dict[str, Any],
    side_effects: dict[str, Any],
    immutability: dict[str, Any],
) -> dict[str, Any]:
    registry_error = (registry_module.RegistryContractError,)
    selection_error = (selection.SelectionContractError,)
    base = registry.get("vg.s1.committed_state_immutability.direct")
    other = registry.get("p7.s2.mutation_reducer_contract.direct")
    catalog = registry.get("p8.s8.light_cone.catalog_startup")
    history = registry.get("p7.current_tree.shared_aggregate.history")
    rows = [
        _error_case(
            "01_duplicate_entry_id",
            lambda: registry_module.ValidationRegistry(
                (base, replace(other, entry_id=base.entry_id))
            ),
            "duplicate_entry_id",
            registry_error,
        ),
        _error_case(
            "02_duplicate_module_mode",
            lambda: registry_module.ValidationRegistry(
                (base, replace(other, module=base.module, mode_id=base.mode_id))
            ),
            "duplicate_mode_identity",
            registry_error,
        ),
        _error_case(
            "03_unknown_lifecycle",
            lambda: replace(base, lifecycle_classification="future"),
            "unknown_lifecycle",
            registry_error,
        ),
        _error_case(
            "04_unknown_tier",
            lambda: replace(base, tier="smoke"),
            "unknown_tier",
            registry_error,
        ),
        _error_case(
            "05_unknown_domain",
            lambda: replace(base, domains=("unknown",)),
            "unknown_domain",
            registry_error,
        ),
        _error_case(
            "06_direct_full_lowering",
            lambda: replace(
                base,
                resources=registry_module.ResourceRequirement(
                    "full_lowering_rulebook",
                    True,
                    True,
                    "full_lowering",
                    "tbgd.full_tree",
                    "test.builder",
                    "test.artifact",
                ),
            ),
            "direct_heavy_resource_conflict",
            registry_error,
        ),
        _error_case(
            "07_historical_selectable",
            lambda: replace(history, current_selectable=True),
            "selectability_conflict",
            registry_error,
        ),
        _error_case(
            "08_catalog_selectable",
            lambda: replace(catalog, current_selectable=True),
            "selectability_conflict",
            registry_error,
        ),
        _error_case(
            "09_source_without_tbgd_input",
            lambda: replace(catalog, cli_inputs=()),
            "tbgd_semantic_input_missing",
            registry_error,
        ),
        _error_case(
            "10_dangling_replacement",
            lambda: registry_module.ValidationRegistry(
                (
                    replace(
                        history,
                        replacement_status="complete",
                        replaced_by=("missing.entry",),
                    ),
                )
            ),
            "replacement_dangling",
            registry_error,
        ),
    ]
    cycle_a = registry.get("p1.phase1.aggregate.history")
    cycle_b = registry.get("p2.status.aggregate.history")
    rows.append(
        _error_case(
            "11_replacement_cycle",
            lambda: registry_module.ValidationRegistry(
                (
                    replace(cycle_a, replaced_by=(cycle_b.entry_id,)),
                    replace(cycle_b, replaced_by=(cycle_a.entry_id,)),
                )
            ),
            "replacement_cycle",
            registry_error,
        )
    )
    blocked_cases = (
        (
            "12_empty_request",
            _select(registry, selection),
            "empty_selection_request",
        ),
        (
            "13_unknown_entry",
            _select(registry, selection, entry_ids=("missing.entry",)),
            "unknown_entry_id",
        ),
        (
            "14_unknown_trigger",
            _select(registry, selection, triggers=("missing",)),
            "unknown_trigger",
        ),
        (
            "15_domain_only",
            _select(registry, selection, domains=("lifecycle",)),
            "domain_only_request_forbidden",
        ),
        (
            "16_direct_catalog",
            _select(registry, selection, entry_ids=(catalog.entry_id,)),
            "direct_entry_not_current_selectable",
        ),
        (
            "17_direct_history",
            manifests["history_blocked"],
            "direct_entry_not_current_selectable",
        ),
        (
            "18_catalog_without_heavy",
            _select(
                registry,
                selection,
                intent="catalog",
                entry_ids=("p8.s8.light_cone.catalog_startup",),
                inputs=(("tbgd_root", "/tmp/not_read"),),
            ),
            "catalog_heavy_plan_confirmation_required",
        ),
        (
            "19_missing_cli_input",
            manifests["missing_input"],
            "missing_required_cli_input",
        ),
    )
    rows.extend(
        _selection_blocked(case_id, manifest, code)
        for case_id, manifest, code in blocked_cases
    )
    collision_registry = registry_module.ValidationRegistry(
        (base, replace(other, output_subdir=base.output_subdir))
    )
    rows.extend(
        (
            _selection_blocked(
                "20_output_collision",
                _select(
                    collision_registry,
                    selection,
                    entry_ids=(base.entry_id, other.entry_id),
                ),
                "validator_output_directory_collision",
            ),
            _selection_blocked(
                "21_output_escape",
                _select(
                    registry,
                    selection,
                    entry_ids=(base.entry_id,),
                    output_root="/tmp/root/../escape",
                ),
                "output_root_escape_forbidden",
            ),
            _selection_blocked(
                "22_module_override",
                _select(
                    registry,
                    selection,
                    entry_ids=(base.entry_id,),
                    inputs=(("module", "/tmp/override"),),
                ),
                "command_structure_override_forbidden",
            ),
            _error_case(
                "23_shell_token",
                lambda: replace(base, fixed_argv=("--run;echo",)),
                "invalid_cli_flag",
                registry_error,
            ),
            {
                "case_id": "24_order_nondeterminism",
                "ok": manifests["permutation_a"].to_json()
                == manifests["permutation_b"].to_json(),
            },
            {
                "case_id": "25_validator_import",
                "ok": side_effects["validator_import_count"] == 0,
            },
            {
                "case_id": "26_execution_or_subprocess",
                "ok": side_effects["validation_call_count"] == 0
                and side_effects["subprocess_count"] == 0,
            },
            {
                "case_id": "27_tbgd_rulebook_lowering",
                "ok": side_effects["tbgd_read_count"] == 0
                and side_effects["rulebook_build_count"] == 0
                and side_effects["full_lowering_build_count"] == 0,
            },
            _error_case(
                "28_shared_build_claim",
                lambda: selection.CandidateBuildGroup(
                    "group",
                    "source_inventory",
                    "source",
                    "builder",
                    "artifact",
                    "none",
                    False,
                    ("entry",),
                    "unproven",
                    adapter_status="implemented",
                ),
                "shared_build_claim_forbidden",
                selection_error,
            ),
            _error_case(
                "29_historical_current_predicate",
                lambda: replace(
                    history,
                    current_contract_predicates=("old_gap",),
                ),
                "historical_current_predicate",
                registry_error,
            ),
            {
                "case_id": "30_external_container_alias",
                "ok": immutability["checks"]["selection_nested_lists_isolated"]
                and immutability["checks"]["registry_source_list_isolated"],
            },
            {
                "case_id": "31_source_groups_not_falsely_shared",
                "ok": len(manifests["p8_source_pair"].build_groups) == 2,
            },
        )
    )
    shared_a = replace(
        base.resources,
        shared_build_key="shared.test",
    )
    shared_b = replace(
        other.resources,
        source_identity="different.source",
        shared_build_key="shared.test",
    )
    rows.append(
        _error_case(
            "32_shared_key_identity_conflict",
            lambda: registry_module.ValidationRegistry(
                (
                    replace(base, resources=shared_a),
                    replace(other, resources=shared_b),
                )
            ),
            "shared_build_identity_conflict",
            registry_error,
        )
    )
    rows.extend(
        (
            _error_case(
                "33_missing_input_mutable_scalar",
                lambda: selection.MissingInput(
                    ["entry"],
                    "input",
                    "--input",
                    True,
                    True,
                ),
                "invalid_type",
                selection_error,
            ),
            _error_case(
                "34_excluded_entry_mutable_scalar",
                lambda: selection.ExcludedEntry(
                    "entry",
                    ["reason"],
                ),
                "invalid_type",
                selection_error,
            ),
        )
    )
    composed_summary = """
def run(output_dir):
    suffix = "exact.json"
    output_paths = {
        key: output_dir / f"{prefix}_{suffix}"
        for key, prefix in (("summary", "validation_summary"),)
    }
    write_json(output_paths["summary"], {})
"""
    unrelated_summary = """
first = "validation_summary"
second = "exact.json"
write_json(output_dir / "different.json", {})
"""
    rows.append(
        {
            "case_id": "35_summary_evidence_requires_exact_dataflow",
            "ok": (
                _summary_present(
                    composed_summary,
                    "validation_summary_exact.json",
                )
                and not _summary_present(
                    unrelated_summary,
                    "validation_summary_exact.json",
                )
            ),
        }
    )
    extra_blocker = types.SimpleNamespace(
        ok=False,
        blocked_issues=(
            selection.SelectionIssue("expected", "expected"),
            selection.SelectionIssue("unexpected", "unexpected"),
        ),
        selected_entries=(),
        build_groups=(),
    )
    rows.append(
        {
            "case_id": "36_additional_blocker_is_not_exact_evidence",
            "ok": not _selection_blocked(
                "probe",
                extra_blocker,
                "expected",
            )["ok"],
        }
    )
    return {
        "schema_version": "vg-s3.negative-matrix.v2",
        "summary": {
            "ok": all(row["ok"] for row in rows),
            "case_count": len(rows),
            "passed": sum(row["ok"] for row in rows),
        },
        "rows": rows,
    }


def _static_boundary(package_root: Path) -> dict[str, Any]:
    files = (
        "validation_registry.py",
        "validation_selection.py",
        "select_validations.py",
    )
    forbidden = ("core", "systems", "rules", "tbgd", "scenarios", "builds")
    rows = []
    for filename in files:
        path = package_root / "tools" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        bad_imports = sorted(
            name
            for name in imports
            if any(
                name == root
                or name.startswith(f"{root}.")
                or f".{root}." in name
                for root in forbidden
            )
        )
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]
        run_calls = sum(
            (
                isinstance(node.func, ast.Name)
                and node.func.id == "run_validation"
            )
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "run_validation"
            )
            for node in calls
        )
        shell_true = sum(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for node in calls
            for keyword in node.keywords
        )
        rows.append(
            {
                "path": f"tools/{filename}",
                "ok": not bad_imports and run_calls == 0 and shell_true == 0,
                "forbidden_imports": bad_imports,
                "run_validation_calls": run_calls,
                "shell_true_calls": shell_true,
            }
        )
    return {"ok": all(row["ok"] for row in rows), "rows": rows}


def _git_scope_audit(package_root: Path) -> dict[str, Any]:
    def run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", "-C", str(repo_root), *args),
            check=False,
            capture_output=True,
            text=True,
        )

    root_result = run_git(package_root, "rev-parse", "--show-toplevel")
    if root_result.returncode != 0:
        return {
            "ok": False,
            "audit_available": False,
            "error": root_result.stderr.strip(),
            "changed_paths": [],
            "production_paths": [],
        }
    repo_root = Path(root_result.stdout.strip())
    diff_result = run_git(repo_root, "diff", "--name-only", "-z", "HEAD", "--")
    untracked_result = run_git(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
    )
    if diff_result.returncode != 0 or untracked_result.returncode != 0:
        return {
            "ok": False,
            "audit_available": False,
            "error": "\n".join(
                value
                for value in (
                    diff_result.stderr.strip(),
                    untracked_result.stderr.strip(),
                )
                if value
            ),
            "changed_paths": [],
            "production_paths": [],
        }
    changed = tuple(
        sorted(
            {
                path
                for output in (diff_result.stdout, untracked_result.stdout)
                for path in output.split("\0")
                if path
            }
        )
    )
    package_prefix = (
        "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/"
    )
    production = tuple(
        path
        for path in changed
        if path.startswith(package_prefix)
        and path.endswith(".py")
        and not path.startswith(f"{package_prefix}tools/")
    )
    return {
        "ok": not production,
        "audit_available": True,
        "error": "",
        "audit_basis": "git diff HEAD plus untracked non-ignored files",
        "changed_paths": list(changed),
        "production_paths": list(production),
    }


def _docs_check(package_root: Path) -> dict[str, Any]:
    path = package_root / "docs" / "AGENT_WORKFLOW_AND_VALIDATION.md"
    text = path.read_text(encoding="utf-8")
    markers = (
        "simulator_v8_clean_core.tools.select_validations",
        "select --dry-run",
        "registry entry ID",
        "未登记",
        "source_identity",
    )
    checks = {marker: marker in text for marker in markers}
    return {"ok": all(checks.values()), "markers": checks}


def _predicates(
    registry: Any,
    entry_matrix: dict[str, Any],
    selection_matrix: dict[str, Any],
    manifests: dict[str, Any],
    import_probe: dict[str, Any],
    side_effects: dict[str, Any],
    boundary: dict[str, Any],
    scope_audit: dict[str, Any],
    immutability: dict[str, Any],
    negatives: dict[str, Any],
) -> dict[str, Any]:
    reversed_registry = type(registry)(tuple(reversed(registry.entries)))
    direct = manifests["direct_trigger"]
    catalog = manifests["catalog_heavy"]
    history = manifests["history_blocked"]
    missing = manifests["missing_input"]
    negative_ok = {row["case_id"]: row["ok"] for row in negatives["rows"]}
    groups_plan_only = all(
        group.adapter_status == "not_implemented"
        and group.grouping_only is True
        and group.shared_build_executed is False
        for group in catalog.build_groups
    )
    return {
        "registry_entry_identity_is_module_plus_mode": len(
            {entry.mode_identity for entry in registry.entries}
        )
        == len(registry.entries),
        "registry_entries_are_unique": len(set(registry.entry_ids)) == 17,
        "registry_is_recursively_immutable": immutability["ok"],
        "registry_json_and_fingerprint_are_deterministic": (
            registry.canonical_json() == reversed_registry.canonical_json()
            and registry.fingerprint == reversed_registry.fingerprint
        ),
        "registry_load_imports_no_validator_modules": (
            import_probe["validator_import_count"] == 0
        ),
        "first_batch_inventory_matches_independent_oracle": (
            entry_matrix["summary"]["ok"]
        ),
        "lifecycle_tier_and_resource_dimensions_are_separate": all(
            hasattr(entry.resources, "source_identity")
            and hasattr(entry.resources, "rulebook_build_kind")
            and hasattr(entry.resources, "full_lowering_required")
            for entry in registry.entries
        ),
        "mode_specific_resource_classification_is_correct": all(
            row["resource_call_chain_matches"]
            and row["resource_identity_matches"]
            for row in entry_matrix["rows"]
        ),
        "direct_selection_contains_only_active_direct_entries": (
            direct.ok
            and all(
                item.lifecycle_classification == "active_contract"
                and item.tier == "direct"
                for item in direct.selected_entries
            )
        ),
        "catalog_requires_exact_explicit_heavy_plan": (
            catalog.ok and negative_ok["18_catalog_without_heavy"]
        ),
        "historical_entries_are_not_current_selectable": (
            not history.ok and negative_ok["17_direct_history"]
        ),
        "empty_unknown_and_ambiguous_requests_fail_closed": all(
            negative_ok[name]
            for name in (
                "12_empty_request",
                "13_unknown_entry",
                "14_unknown_trigger",
            )
        ),
        "domain_only_request_cannot_expand_to_all_validators": negative_ok[
            "15_domain_only"
        ],
        "missing_required_cli_inputs_are_reported": (
            not missing.ok
            and bool(missing.missing_required_inputs)
            and negative_ok["19_missing_cli_input"]
        ),
        "dry_run_executes_no_validation": (
            side_effects["validation_call_count"] == 0
        ),
        "dry_run_spawns_no_subprocess": side_effects["subprocess_count"] == 0,
        "dry_run_reads_no_tbgd": side_effects["tbgd_read_count"] == 0,
        "dry_run_builds_no_rulebook": side_effects["rulebook_build_count"] == 0,
        "dry_run_creates_no_validator_output_directories": side_effects[
            "validator_output_directory_count"
        ]
        == 0,
        "selection_order_and_fingerprint_are_deterministic": selection_matrix[
            "checks"
        ]["permutation_stable"],
        "rendered_commands_are_structured_argv": all(
            type(item.module) is str and type(item.argv) is tuple
            for item in (*direct.selected_entries, *catalog.selected_entries)
        ),
        "shared_build_requirement_is_only_a_plan": (
            groups_plan_only
            and selection_matrix["checks"]["source_build_groups_separate"]
        ),
        "full_lowering_build_count": side_effects[
            "full_lowering_build_count"
        ],
        "production_behavior_changed": (
            not scope_audit["audit_available"]
            or bool(scope_audit["production_paths"])
        ),
    }


def _predicates_ok(predicates: dict[str, Any]) -> bool:
    for name, value in predicates.items():
        if name == "production_behavior_changed":
            if value is not False:
                return False
        elif name == "full_lowering_build_count":
            if type(value) is not int or value != 0:
                return False
        elif value is not True:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate VG-S3 registry and pure selection."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir)
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "ready_for_review": result["ready_for_review"],
                "entry_count": result["summary"]["registered_entry_count"],
                "negative_case_count": result["summary"][
                    "negative_case_count"
                ],
                "full_lowering_build_count": result["resource_budget"][
                    "full_lowering_build_count"
                ],
                "output_dir": args.output_dir.as_posix(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
