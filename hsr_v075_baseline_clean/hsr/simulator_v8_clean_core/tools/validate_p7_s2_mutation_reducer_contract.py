from __future__ import annotations

import argparse
import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, Mutation, UnitState
from ..core.reducer import MutationConflictError, MutationReducer
from ..core.unit_state_codec import unit_state_from_payload, unit_state_to_payload
from ..systems.unit_lifecycle import UnitLifecycleSystem
from .io import write_json
from .snapshot_replay import run_snapshot_replay_check


VALIDATION_VERSION = "p7_s2_mutation_reducer_contract"
MATRIX_SCHEMA_VERSION = "p7_s2_mutation_reducer_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    reducer = MutationReducer()
    state = _base_state()
    normal_chain = _normal_chain_case(reducer, state)
    wrong_before = _wrong_before_case(reducer, state)
    repeated_path = _repeated_path_case(reducer, state)
    invalid_op = _conflict_case(
        reducer,
        state,
        (
            _mutation(
                op="add",
                path=("skill_points",),
                before=3,
                after=2,
                mutation_id="mutation:validation:invalid_op",
            ),
        ),
        "invalid_op",
    )
    invalid_path = _conflict_case(
        reducer,
        state,
        (
            _mutation(
                op="set",
                path=("unsupported_root",),
                before=None,
                after=1,
                mutation_id="mutation:validation:invalid_path",
            ),
        ),
        "invalid_path",
    )
    invalid_after = _invalid_after_case(reducer, state)
    path_presence = _path_presence_case(reducer, state)
    delete = _delete_case(reducer, state)
    spawn = _spawn_case(reducer, state)
    alias_pollution = _alias_pollution_case(reducer, state)
    unit_codec = _unit_codec_case(package_root)
    replay = _replay_case(reducer, state)
    boundary = _production_boundary_case(package_root)
    snapshot_replay = run_snapshot_replay_check()

    cases = {
        "normal_chain": normal_chain,
        "wrong_before_atomic_rollback": wrong_before,
        "repeated_path_conflict": repeated_path,
        "invalid_op": invalid_op,
        "invalid_path": invalid_path,
        "invalid_after": invalid_after,
        "path_presence": path_presence,
        "delete": delete,
        "spawn": spawn,
        "mutation_alias_pollution": alias_pollution,
        "unit_state_codec_single_source": unit_codec,
        "tampered_replay": replay,
        "production_boundary": boundary,
        "snapshot_replay_direct": snapshot_replay,
    }
    checks = {
        "normal_chain_applies_in_order": normal_chain["ok"],
        "wrong_before_rolls_back_entire_batch": wrong_before["ok"],
        "same_path_requires_continuous_before": repeated_path["ok"],
        "invalid_op_is_rejected": invalid_op["ok"],
        "invalid_path_is_rejected": invalid_path["ok"],
        "invalid_after_is_rejected": invalid_after["ok"],
        "missing_and_null_are_distinct": path_presence["ok"],
        "delete_has_explicit_presence_semantics": delete["ok"],
        "spawn_has_explicit_operation_semantics": spawn["ok"],
        "mutation_and_applied_state_reject_alias_pollution": alias_pollution["ok"],
        "unit_state_codec_is_shared_and_strict": unit_codec["ok"],
        "replay_checks_before_order_after_and_types": replay["ok"],
        "production_mutation_ops_are_structural": boundary["ok"],
        "snapshot_replay_direct_regression": bool(snapshot_replay["ok"]),
    }
    ok = all(checks.values())
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "rows": [
            {
                "case": name,
                "ok": bool(case.get("ok")),
                "conflict_codes": _case_conflict_codes(case),
                "state_unchanged": case.get("state_unchanged"),
            }
            for name, case in cases.items()
        ],
        "summary": {
            "row_count": len(cases),
            "passed_row_count": sum(1 for case in cases.values() if case.get("ok") is True),
            "failed_rows": [name for name, case in cases.items() if case.get("ok") is not True],
        },
    }
    summary = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "p7_s2_ready_for_review": ok,
        "p7_all_fixed": False,
        "p7_done_eligible": False,
        "checks": checks,
        "matrix_summary": matrix["summary"],
        "conflict_code_coverage": sorted(
            {
                code
                for case in cases.values()
                for code in _case_conflict_codes(case)
            }
        ),
        "resource_budget": {
            "tbgd_read_count": 0,
            "full_rulebook_build_count": 0,
            "minimal_in_memory_rulebook_build_count": 1,
            "large_artifacts_written": False,
            "full_transition_dump_written": False,
            "output_scope": "summary_matrix_compact_case_evidence",
        },
        "deferred": {
            "p7_s3_selected_execution_graph_atomic_commit": True,
            "p7_s4_runtime_rule_audit_input_separation": True,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p7_s2_mutation_reducer_matrix.json", matrix)
    write_json(output_dir / "p7_s2_mutation_reducer_cases.json", {"cases": cases})
    write_json(output_dir / "validation_summary_p7_s2_mutation_reducer_contract.json", summary)
    return summary


def _base_state() -> BattleState:
    return BattleState(
        units={
            "ally:actor": UnitState(
                unit_id="ally:actor",
                side="ally",
                template_id="validation:actor",
                max_hp=1000.0,
                hp=1000.0,
                energy=20.0,
                max_energy=100.0,
                flags={"nullable": None},
            )
        },
        skill_points=3,
        max_skill_points=5,
        global_flags={"nullable": None},
    )


def _mutation(
    *,
    op: str,
    path: tuple[str, ...],
    before: Any,
    after: Any,
    before_exists: bool = True,
    after_exists: bool = True,
    mutation_id: str,
) -> Mutation:
    return Mutation(
        op=op,
        path=path,
        before=before,
        after=after,
        reason="P7-S2 reducer contract validation",
        source="validation",
        before_exists=before_exists,
        after_exists=after_exists,
        mutation_id=mutation_id,
    )


def _normal_mutations() -> tuple[Mutation, ...]:
    return (
        _mutation(
            op="set",
            path=("skill_points",),
            before=3,
            after=2,
            mutation_id="mutation:validation:chain:0",
        ),
        _mutation(
            op="set",
            path=("skill_points",),
            before=2,
            after=1,
            mutation_id="mutation:validation:chain:1",
        ),
        _mutation(
            op="set",
            path=("event_index",),
            before=0,
            after=1,
            mutation_id="mutation:validation:chain:2",
        ),
    )


def _normal_chain_case(reducer: MutationReducer, state: BattleState) -> dict[str, Any]:
    result = reducer.apply_all_result(state, _normal_mutations())
    return {
        "ok": result.ok
        and result.applied_count == 3
        and result.after_state.skill_points == 1
        and result.after_state.event_index == 1,
        "result": result.to_json(),
        "after": result.after_state.snapshot().to_json(),
    }


def _wrong_before_case(reducer: MutationReducer, state: BattleState) -> dict[str, Any]:
    mutations = (
        _mutation(
            op="set",
            path=("event_index",),
            before=0,
            after=1,
            mutation_id="mutation:validation:rollback:first",
        ),
        _mutation(
            op="set",
            path=("skill_points",),
            before=4,
            after=2,
            mutation_id="mutation:validation:rollback:stale",
        ),
        _mutation(
            op="set",
            path=("wave_index",),
            before=0,
            after=1,
            mutation_id="mutation:validation:rollback:last",
        ),
    )
    result = reducer.apply_all_result(state, mutations)
    raised_result = None
    try:
        reducer.apply_all(state, mutations)
    except MutationConflictError as exc:
        raised_result = exc.result
    return {
        "ok": not result.ok
        and result.after_state == state
        and result.applied_count == 0
        and _first_conflict_code(result) == "before_value_mismatch"
        and result.conflicts[0].mutation_index == 1
        and raised_result == result,
        "state_unchanged": result.after_state == state,
        "result": result.to_json(),
        "production_exception_carries_result": raised_result == result,
    }


def _repeated_path_case(reducer: MutationReducer, state: BattleState) -> dict[str, Any]:
    mutations = (
        _normal_mutations()[0],
        _mutation(
            op="set",
            path=("skill_points",),
            before=3,
            after=1,
            mutation_id="mutation:validation:repeat:stale",
        ),
    )
    result = reducer.apply_all_result(state, mutations)
    conflict = result.conflicts[0] if result.conflicts else None
    return {
        "ok": not result.ok
        and result.after_state == state
        and conflict is not None
        and conflict.code == "same_path_before_value_mismatch"
        and conflict.prior_mutation_index == 0
        and conflict.prior_mutation_id == _normal_mutations()[0].stable_id(),
        "state_unchanged": result.after_state == state,
        "result": result.to_json(),
    }


def _invalid_after_case(reducer: MutationReducer, state: BattleState) -> dict[str, Any]:
    wrong_type = reducer.apply_all_result(
        state,
        (
            _mutation(
                op="set",
                path=("skill_points",),
                before=3,
                after=True,
                mutation_id="mutation:validation:after:bool",
            ),
        ),
    )
    wrong_presence = reducer.apply_all_result(
        state,
        (
            _mutation(
                op="set",
                path=("global_flags", "nullable"),
                before=None,
                after=None,
                after_exists=False,
                mutation_id="mutation:validation:after:presence",
            ),
        ),
    )
    return {
        "ok": _first_conflict_code(wrong_type) == "invalid_after_type"
        and _first_conflict_code(wrong_presence) == "invalid_after_presence"
        and wrong_type.after_state == state
        and wrong_presence.after_state == state,
        "state_unchanged": wrong_type.after_state == state and wrong_presence.after_state == state,
        "wrong_type": wrong_type.to_json(),
        "wrong_presence": wrong_presence.to_json(),
    }


def _path_presence_case(reducer: MutationReducer, state: BattleState) -> dict[str, Any]:
    existing_null = _mutation(
        op="set",
        path=("global_flags", "nullable"),
        before=None,
        after="updated",
        before_exists=True,
        mutation_id="mutation:validation:presence:existing_null",
    )
    missing = _mutation(
        op="set",
        path=("global_flags", "missing"),
        before=None,
        after="created",
        before_exists=False,
        mutation_id="mutation:validation:presence:missing",
    )
    existing_result = reducer.apply_all_result(state, (existing_null,))
    missing_result = reducer.apply_all_result(state, (missing,))
    false_missing = reducer.apply_all_result(state, (replace(existing_null, before_exists=False),))
    false_existing = reducer.apply_all_result(state, (replace(missing, before_exists=True),))
    return {
        "ok": existing_result.ok
        and missing_result.ok
        and existing_result.after_state.global_flags["nullable"] == "updated"
        and missing_result.after_state.global_flags["missing"] == "created"
        and _first_conflict_code(false_missing) == "before_presence_mismatch"
        and _first_conflict_code(false_existing) == "before_presence_mismatch",
        "existing_null": existing_result.to_json(),
        "missing": missing_result.to_json(),
        "false_missing": false_missing.to_json(),
        "false_existing": false_existing.to_json(),
    }


def _delete_case(reducer: MutationReducer, state: BattleState) -> dict[str, Any]:
    deletion = _mutation(
        op="delete",
        path=("global_flags", "nullable"),
        before=None,
        after=None,
        after_exists=False,
        mutation_id="mutation:validation:delete:existing",
    )
    result = reducer.apply_all_result(state, (deletion,))
    missing_delete = reducer.apply_all_result(
        state,
        (
            replace(
                deletion,
                path=("global_flags", "missing"),
                before_exists=False,
                mutation_id="mutation:validation:delete:missing",
            ),
        ),
    )
    return {
        "ok": result.ok
        and "nullable" not in result.after_state.global_flags
        and _first_conflict_code(missing_delete) == "invalid_delete"
        and missing_delete.after_state == state,
        "state_unchanged": missing_delete.after_state == state,
        "delete_existing": result.to_json(),
        "delete_missing": missing_delete.to_json(),
    }


def _spawn_case(reducer: MutationReducer, state: BattleState) -> dict[str, Any]:
    unit = UnitState(
        unit_id="summon:validation",
        side="summon",
        template_id="validation:summon",
        max_hp=200.0,
        hp=200.0,
    )
    mutation = UnitLifecycleSystem().spawn_mutation(
        state,
        unit,
        reason="P7-S2 spawn validation",
        source="validation",
        source_trace={"source_kind": "validation"},
    )
    result = reducer.apply_all_result(state, (mutation,))
    wrong_op = reducer.apply_all_result(state, (replace(mutation, op="set"),))
    existing_state = result.after_state
    existing_spawn = reducer.apply_all_result(existing_state, (mutation,))
    return {
        "ok": mutation.op == "spawn"
        and not mutation.before_exists
        and result.ok
        and "summon:validation" in result.after_state.units
        and _first_conflict_code(wrong_op) == "invalid_op_path"
        and _first_conflict_code(existing_spawn) == "before_presence_mismatch",
        "spawn": result.to_json(),
        "wrong_op": wrong_op.to_json(),
        "existing_spawn": existing_spawn.to_json(),
    }


def _alias_pollution_case(reducer: MutationReducer, state: BattleState) -> dict[str, Any]:
    before_input = {"nested": {"values": [1]}}
    after_input = {"nested": {"values": [2]}}
    metadata_input = {"source_trace": {"paths": ["validation/alias"]}}
    alias_state = replace(state, global_flags={"alias_target": {"nested": {"values": [1]}}})
    mutation = Mutation(
        op="set",
        path=("global_flags", "alias_target"),
        before=before_input,
        after=after_input,
        reason="P7-S2 alias pollution validation",
        source="validation",
        metadata=metadata_input,
        mutation_id="",
    )
    stable_id_before = mutation.stable_id()
    mutation_json_before = mutation.to_json()
    result = reducer.apply_all_result(alias_state, (mutation,))
    state_value_before_pollution = result.after_state.global_flags.get("alias_target")

    before_input["nested"]["values"].append(99)
    after_input["nested"]["values"][0] = 999
    metadata_input["source_trace"]["paths"].append("validation/polluted")

    direct_after_mutation_rejected = False
    direct_metadata_mutation_rejected = False
    try:
        mutation.after["nested"]["values"].append(3)  # type: ignore[index,union-attr]
    except TypeError:
        direct_after_mutation_rejected = True
    try:
        mutation.metadata["source_trace"] = {}  # type: ignore[index]
    except TypeError:
        direct_metadata_mutation_rejected = True

    exported = mutation.to_json()
    exported_after = exported.get("after")
    if isinstance(exported_after, dict):
        nested = exported_after.get("nested")
        if isinstance(nested, dict) and isinstance(nested.get("values"), list):
            nested["values"].append(4)

    mutation_json_after = mutation.to_json()
    state_value_after_pollution = result.after_state.global_flags.get("alias_target")
    return {
        "ok": result.ok
        and stable_id_before == mutation.stable_id()
        and mutation_json_before == mutation_json_after
        and state_value_before_pollution == {"nested": {"values": [2]}}
        and state_value_after_pollution == {"nested": {"values": [2]}}
        and direct_after_mutation_rejected
        and direct_metadata_mutation_rejected
        and exported != mutation_json_after,
        "stable_id_before": stable_id_before,
        "stable_id_after": mutation.stable_id(),
        "mutation_json_before": mutation_json_before,
        "mutation_json_after": mutation_json_after,
        "state_value_after_external_pollution": state_value_after_pollution,
        "direct_after_mutation_rejected": direct_after_mutation_rejected,
        "direct_metadata_mutation_rejected": direct_metadata_mutation_rejected,
        "export_mutation_is_detached": exported != mutation_json_after,
    }


def _unit_codec_case(package_root: Path) -> dict[str, Any]:
    unit = UnitState(
        unit_id="summon:codec",
        side="summon",
        template_id="validation:codec",
        max_hp=200.0,
        hp=150.0,
        speed=120.0,
        statuses=("validation:status",),
        flags={"nested": {"values": [1]}},
        resources={"shield": 10.0},
    )
    payload = unit_state_to_payload(unit)
    round_trip = unit_state_from_payload(payload)
    normalized_numeric_payload = {**payload, "attack": 5}
    normalized_numeric = unit_state_to_payload(unit_state_from_payload(normalized_numeric_payload))
    missing_rejected = _codec_payload_rejected({key: value for key, value in payload.items() if key != "speed"})
    extra_rejected = _codec_payload_rejected({**payload, "unexpected": 1})
    invalid_range_rejected = _codec_payload_rejected({**payload, "hp": 201.0})

    definitions: list[dict[str, Any]] = []
    legacy_definitions: list[dict[str, Any]] = []
    checked_paths = (
        package_root / "core" / "unit_state_codec.py",
        package_root / "core" / "reducer.py",
        package_root / "systems" / "unit_lifecycle.py",
        package_root / "systems" / "unit_spawn.py",
    )
    for path in checked_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            record = {
                "path": path.relative_to(package_root).as_posix(),
                "line": node.lineno,
                "name": node.name,
            }
            if node.name in {"unit_state_to_payload", "unit_state_from_payload"}:
                definitions.append(record)
            if node.name in {"_unit_payload", "_unit_from_payload", "unit_from_payload"}:
                legacy_definitions.append(record)
    definition_names = {(item["path"], item["name"]) for item in definitions}
    expected_definitions = {
        ("core/unit_state_codec.py", "unit_state_to_payload"),
        ("core/unit_state_codec.py", "unit_state_from_payload"),
    }
    return {
        "ok": unit_state_to_payload(round_trip) == payload
        and normalized_numeric["attack"] == 5.0
        and missing_rejected
        and extra_rejected
        and invalid_range_rejected
        and definition_names == expected_definitions
        and not legacy_definitions,
        "round_trip_payload": payload,
        "normalized_numeric_attack": normalized_numeric["attack"],
        "missing_field_rejected": missing_rejected,
        "extra_field_rejected": extra_rejected,
        "invalid_range_rejected": invalid_range_rejected,
        "codec_definitions": definitions,
        "legacy_codec_definitions": legacy_definitions,
    }


def _codec_payload_rejected(payload: dict[str, Any]) -> bool:
    try:
        unit_state_from_payload(payload)
    except (TypeError, ValueError):
        return True
    return False


def _replay_case(reducer: MutationReducer, state: BattleState) -> dict[str, Any]:
    mutations = _normal_mutations()
    after = reducer.apply_all(state, mutations)
    expected = after.snapshot().to_json()
    valid = reducer.replay_snapshot(state, mutations, expected)
    tampered_before = reducer.replay_snapshot(
        state,
        (mutations[0], replace(mutations[1], before=3), mutations[2]),
        expected,
    )
    tampered_order = reducer.replay_snapshot(
        state,
        (mutations[1], mutations[0], mutations[2]),
        expected,
    )
    tampered_after = reducer.replay_snapshot(
        state,
        (mutations[0], replace(mutations[1], after=0), mutations[2]),
        expected,
    )
    wrong_snapshot_type = {**expected, "skill_points": True}
    typed_snapshot = reducer.replay_snapshot(state, mutations, wrong_snapshot_type)
    return {
        "ok": valid.ok
        and not tampered_before.ok
        and bool(tampered_before.conflicts)
        and not tampered_order.ok
        and bool(tampered_order.conflicts)
        and not tampered_after.ok
        and tampered_after.errors == ("snapshot_mismatch:resources.skill_points",)
        and not typed_snapshot.ok
        and typed_snapshot.errors == ("snapshot_mismatch:skill_points",),
        "valid": valid.to_json(),
        "tampered_before": tampered_before.to_json(),
        "tampered_order": tampered_order.to_json(),
        "tampered_after": tampered_after.to_json(),
        "typed_snapshot": typed_snapshot.to_json(),
    }


def _conflict_case(
    reducer: MutationReducer,
    state: BattleState,
    mutations: tuple[Mutation, ...],
    expected_code: str,
) -> dict[str, Any]:
    result = reducer.apply_all_result(state, mutations)
    return {
        "ok": not result.ok
        and result.after_state == state
        and result.applied_count == 0
        and _first_conflict_code(result) == expected_code,
        "state_unchanged": result.after_state == state,
        "result": result.to_json(),
    }


def _production_boundary_case(package_root: Path) -> dict[str, Any]:
    parse_errors: list[dict[str, Any]] = []
    mutation_sites: list[dict[str, Any]] = []
    invalid_literal_ops: list[dict[str, Any]] = []
    legacy_delete_sites: list[dict[str, Any]] = []
    legacy_spawn_sites: list[dict[str, Any]] = []
    positional_constructor_sites: list[dict[str, Any]] = []
    roots = (package_root / "core", package_root / "systems")
    for path in sorted(source for root in roots for source in root.rglob("*.py")):
        relative = path.relative_to(package_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError) as exc:
            parse_errors.append({"path": relative, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_leaf(node.func) != "Mutation":
                continue
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            op = _literal_string(keywords.get("op"))
            path_value = _literal_path(keywords.get("path"))
            after_is_none = isinstance(keywords.get("after"), ast.Constant) and keywords["after"].value is None
            site = {"path": relative, "line": node.lineno, "op": op, "mutation_path": list(path_value)}
            mutation_sites.append(site)
            if node.args:
                positional_constructor_sites.append({**site, "positional_argument_count": len(node.args)})
            if op and op not in {"set", "delete", "spawn"}:
                invalid_literal_ops.append(site)
            if op == "set" and after_is_none:
                legacy_delete_sites.append(site)
            if len(path_value) == 2 and path_value[0] == "units" and op != "spawn":
                legacy_spawn_sites.append(site)
    return {
        "ok": not parse_errors
        and bool(mutation_sites)
        and not invalid_literal_ops
        and not legacy_delete_sites
        and not legacy_spawn_sites
        and not positional_constructor_sites,
        "scanned_file_count": sum(1 for root in roots for _ in root.rglob("*.py")),
        "mutation_site_count": len(mutation_sites),
        "parse_errors": parse_errors,
        "invalid_literal_ops": invalid_literal_ops,
        "legacy_set_after_none_sites": legacy_delete_sites,
        "legacy_unit_root_set_sites": legacy_spawn_sites,
        "positional_constructor_sites": positional_constructor_sites,
    }


def _first_conflict_code(result: Any) -> str:
    return result.conflicts[0].code if result.conflicts else ""


def _case_conflict_codes(case: dict[str, Any]) -> list[str]:
    codes: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            conflicts = value.get("conflicts")
            if isinstance(conflicts, list):
                for conflict in conflicts:
                    if isinstance(conflict, dict) and isinstance(conflict.get("code"), str):
                        codes.add(conflict["code"])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(case)
    return sorted(codes)


def _call_leaf(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _literal_string(node: ast.expr | None) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def _literal_path(node: ast.expr | None) -> tuple[str, ...]:
    if not isinstance(node, ast.Tuple):
        return ()
    values: list[str] = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            values.append(item.value)
        else:
            values.append("<dynamic>")
    return tuple(values)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S2 checked Mutation reducer contract.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/hsr_v8_p7_s2_mutation_reducer_contract"),
    )
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir.resolve())
    matrix = result["matrix_summary"]
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"cases={matrix['passed_row_count']}/{matrix['row_count']} "
        f"conflicts={len(result['conflict_code_coverage'])}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
