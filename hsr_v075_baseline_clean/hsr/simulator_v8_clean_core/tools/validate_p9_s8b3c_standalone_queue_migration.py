from __future__ import annotations

import argparse
import resource
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.model import (
    ActionCommand,
    BattleState,
    GameEvent,
    JSONValue,
    Mutation,
    RNGEvent,
    TargetResolution,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_contract import TransitionContractValidator
from ..rules.engine_rule_registry import build_engine_rule_registry
from ..rules.ir import (
    CanonicalIR,
    IRSource,
    QueueResolutionIR,
    StandaloneAbilityGraphIR,
)
from ..rules.rulebook import RuleBook
from ..systems import ability as ability_module
from ..systems import scheduler as scheduler_module
from ..systems.ability import AbilityTaskSystem, StandaloneAbilityInvocation
from ..systems.effect import EffectRegistry, EffectResult
from ..systems.queue import QueueEntry
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.task_graph_materializer import materialize_ability_task_graph_catalog
from .io import write_json
from .validate_p9_s8b3a_ability_invocation_formal_catalog import _queue_slice
from .validate_p9_s8b3b_action_callback_migration import (
    _FixtureRules,
    _fixture,
    _invoke,
    _system,
)


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
SHA = "c" * 64


def _source(identity: str) -> IRSource:
    return IRSource(
        "validation_fixture/p9_s8b3c.json",
        "ValidationFixture",
        identity,
        {
            "json_path": f"$.{identity}",
            "content_sha256": SHA,
            "validation_fixture": True,
        },
    )


def _queue_contract() -> tuple[RuleBook, QueueResolutionIR]:
    source = _source("queue")
    intent_id = "validation:queue_intent:standalone"
    engine = build_engine_rule_registry()
    resolution = QueueResolutionIR(
        "validation:queue_resolution:standalone",
        intent_id,
        "FixtureRoot",
        "standalone_ability_graph",
        {
            "standalone_ability_graph_id": "validation:standalone_graph",
            "phase_ids": ["fixture:root"],
            "task_ids": ["fixture:root_task"],
            "executable_task_ids": ["fixture:root_task"],
        },
        source,
        "executable",
    )
    return RuleBook(
        CanonicalIR(
            version="p9_s8b3c_queue_fixture",
            queue_resolutions=(resolution,),
            timeline_rules=engine.timeline_rules,
            resource_rules=engine.resource_rules,
            damage_formula_rules=engine.damage_formula_rules,
            damage_route_rules=engine.damage_route_rules,
            shield_priority_rules=engine.shield_priority_rules,
        )
    ), resolution


class _StandaloneRules:
    def __init__(
        self,
        base: _FixtureRules,
        resolution: Any,
        graph: StandaloneAbilityGraphIR,
        *,
        action_dependent_task: bool = False,
    ) -> None:
        self.base = base
        self.resolution = resolution
        self.graph = graph
        self.action_dependent_task = action_dependent_task

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def queue_resolution(self, identity: str) -> Any:
        return self.resolution if identity == self.resolution.queue_resolution_id else None

    def standalone_ability_graph(self, identity: str) -> StandaloneAbilityGraphIR | None:
        return self.graph if identity == self.graph.standalone_ability_graph_id else None

    def damage_emissions_for_task(self, task_id: str) -> tuple[object, ...]:
        if self.action_dependent_task and task_id == self.base.tasks[1].task_id:
            return (object(),)
        return self.base.damage_emissions_for_task(task_id)


def _queue_fixture(*, cycle: bool = False, action_dependent: bool = False):
    queue_rules, selected = _queue_contract()
    base, definition = _fixture(cycle=cycle)
    phases = (
        replace(base.phases[0], invocation_role="standalone_root"),
        *base.phases[1:],
    )
    base = _FixtureRules(phases, base.tasks, base.effects, base.graphs, base.entries)
    graph = StandaloneAbilityGraphIR(
        "validation:standalone_graph",
        phases[0].ability_name,
        "mainline_avatar",
        (phases[0].phase_id,),
        (base.tasks[0].task_id,),
        (base.tasks[0].task_id,),
        phases[0].source,
        "executable",
    )
    rules = _StandaloneRules(
        base, selected, graph, action_dependent_task=action_dependent
    )
    calls: list[str] = []
    system = _system(base, calls)
    system.rules = rules  # type: ignore[assignment]

    def channel_handler(effect: Any, _context: Any) -> EffectResult:
        calls.append(effect.effect_id)
        mutation = Mutation(
            "set",
            ("global_flags", "fixture_count"),
            None,
            1,
            "fixture",
            "validation_fixture",
            False,
            True,
            mutation_id="fixture:mutation",
        )
        return EffectResult(
            events=(
                GameEvent(
                    "fixture.effect",
                    source_id="ally:actor",
                    event_id="fixture:event",
                    payload={"effect_id": effect.effect_id},
                ),
            ),
            mutations=(mutation,),
            rng_events=(
                RNGEvent(
                    "fixture_rng",
                    "validation_fixture",
                    1,
                    event_id="fixture:rng",
                ),
            ),
            records=(
                SettlementRecord(
                    "fixture_effect",
                    "validation_fixture",
                    mutation.stable_id(),
                    payload={"effect_id": effect.effect_id},
                    trace=effect.source.to_json(),
                ).to_json(),
            ),
        )

    system.effect_registry.register("FixtureSetFlag", channel_handler)
    return queue_rules, rules, system, calls, definition


def _queue_state(*, entry_updates: dict[str, JSONValue] | None = None) -> BattleState:
    source = _source("queue_entry").to_json()
    entry = QueueEntry(
        entry_id="entry:s8b3c",
        queue_name="interrupt_queue",
        queue_kind="turn_insert_ability",
        queue_intent_id="validation:queue_intent:standalone",
        actor_id="ally:actor",
        action_or_ability_ref="FixtureRoot",
        target_ids=("enemy:target",),
        priority_source={
            "priority_ordering_admitted": True,
            "priority_value": 10.0,
            "priority_key": "validation",
            "queue_priority_id": "validation:queue_priority",
            "priority_table": "validation",
            "source_trace": source,
        },
        source_trace=source,
        priority_key="validation",
        priority_value=10.0,
        queue_priority_id="validation:queue_priority",
        priority_source_trace=source,
        queue_window_id="validation:queue_window",
        window_family="insert_action",
        window_policy={
            "window_ordering_admitted": True,
            "source_basis": source,
        },
        target_resolution={
            "ok": True,
            "target_ids": ["enemy:target"],
            "source_trace": source,
        },
        owner_id="ally:actor",
        source_id="validation:queue_source",
    ).to_json()
    if entry_updates:
        entry = {**entry, **entry_updates}
    return BattleState(
        units={
            "ally:actor": UnitState(
                "ally:actor", "ally", "validation:actor", max_hp=100.0, hp=100.0
            ),
            "enemy:target": UnitState(
                "enemy:target", "enemy", "validation:target", max_hp=100.0, hp=100.0
            ),
        },
        queues={"interrupt_queue": (entry,)},
        global_flags={"current_window": "idle", "combat_phase": "idle"},
    )


def _run_scheduler_case(
    *,
    cycle: bool = False,
    entry_updates: dict[str, JSONValue] | None = None,
) -> dict[str, Any]:
    queue_rules, _, system, calls, _ = _queue_fixture(cycle=cycle)
    scheduler = CombatScheduler(queue_rules)
    scheduler.ability_tasks = system
    state = _queue_state(entry_updates=entry_updates)
    commits = 0
    original_commit = scheduler_module.finalize_selected_execution_graph
    original_action = ability_module.ActionCommand
    original_definition = ability_module.ActionDefinitionIR
    temporary_constructions = {"command": 0, "definition": 0}

    def counted(*args: Any, **kwargs: Any):
        nonlocal commits
        commits += 1
        return original_commit(*args, **kwargs)

    def forbidden_command(*_args: Any, **_kwargs: Any):
        temporary_constructions["command"] += 1
        raise AssertionError("queue standalone constructed a temporary action command")

    def forbidden_definition(*_args: Any, **_kwargs: Any):
        temporary_constructions["definition"] += 1
        raise AssertionError("queue standalone constructed a temporary action")

    scheduler_module.finalize_selected_execution_graph = counted
    ability_module.ActionCommand = forbidden_command  # type: ignore[assignment]
    ability_module.ActionDefinitionIR = forbidden_definition  # type: ignore[assignment]
    try:
        result = scheduler.step(state)
    finally:
        scheduler_module.finalize_selected_execution_graph = original_commit
        ability_module.ActionCommand = original_action
        ability_module.ActionDefinitionIR = original_definition
    transition = result.transition
    replay = MutationReducer().replay_snapshot(
        state, transition.transaction.mutations, transition.after.to_json()
    )
    contract = TransitionContractValidator().validate(transition)
    return {
        "result": result,
        "state": state,
        "calls": calls,
        "commit_count": commits,
        "temporary_constructions": temporary_constructions,
        "replay_ok": replay.ok,
        "contract_ok": contract.ok,
    }


def _direct_blockers() -> dict[str, bool]:
    _, rules, system, calls, definition = _queue_fixture(action_dependent=True)
    state = _queue_state()
    invocation = StandaloneAbilityInvocation(
        rules.graph.standalone_ability_graph_id,
        "ally:actor",
        ("enemy:target",),
        "interrupt_queue",
        "entry:s8b3c",
        rules.resolution.queue_intent_id,
        rules.resolution.queue_resolution_id,
    )
    blocked = system._execute_admitted_queue_standalone(state, invocation=invocation)
    wrong = system._execute_admitted_queue_standalone(
        state, invocation=replace(invocation, queue_resolution_id="missing:resolution")
    )
    bypass = system.execute_callback(
        state,
        phases=rules.base.phases,
        callback_kind="OnStart",
        command=ActionCommand(
            "ally:actor", definition.action_id, definition.level, ("enemy:target",)
        ),
        action_definition=definition,
        target_resolution=TargetResolution(
            requested=("enemy:target",),
            legal=("enemy:target",),
            selected=("enemy:target",),
            reason="validation",
            source="validation_fixture",
        ),
    )
    return {
        "action_dependent_leaf": (
            blocked.after_state == state
            and not blocked.mutations
            and any(
                item.reason_code
                == "standalone_ability_damage_context_deferred_to_s8c"
                for item in blocked.node_results
            )
        ),
        "resolution_identity": (
            wrong.after_state == state
            and not wrong.mutations
            and wrong.node_results[0].reason_code
            == "standalone_queue_resolution_identity_mismatch"
        ),
        "standalone_root_bypass": (
            not bypass.mutations
            and not calls
            and bypass.node_results[0].reason_code
            == "standalone_ability_requires_admitted_queue_invocation"
        ),
    }


def _real_source_probe(tbgd_root: Path) -> dict[str, Any]:
    lowering = TBGDLowering(tbgd_root)
    lowering.build_character_ability_source_graph_catalog()
    snapshot = lowering._character_ability_raw_snapshot
    evidence, parts = _queue_slice(lowering, snapshot)
    graphs, phases, tasks, effects, conditions, _, targets = parts
    view = CanonicalIR(
        version="p9_s8b3c_real_source_slice",
        ability_phases=tuple(phases),
        ability_tasks=tuple(tasks),
        standalone_ability_graphs=tuple(graphs),
        queue_intents=(evidence["intent"],),
        queue_resolutions=(evidence["resolution"],),
        effects=tuple(effects),
        conditions=tuple(conditions),
        target_expressions=tuple(targets),
    )
    source_catalog = lowering.build_character_control_flow_contract_catalog(
        snapshot=snapshot,
        scope_catalog=lowering._character_ability_scope_catalog,
    )
    catalog = materialize_ability_task_graph_catalog(
        source_catalog, view, source_snapshot=snapshot
    )
    rules = RuleBook(replace(view, task_graph_catalog=catalog))
    resolution = evidence["resolution"]
    graph_id = str(resolution.resolved_ids["standalone_ability_graph_id"])
    state = BattleState(
        units={
            "actor": UnitState("actor", "ally", "validation:actor"),
            "target": UnitState("target", "enemy", "validation:target"),
        }
    )
    result = AbilityTaskSystem(
        rules, EffectRegistry(StatusSystem(rules))
    )._execute_admitted_queue_standalone(
        state,
        invocation=StandaloneAbilityInvocation(
            graph_id,
            "actor",
            ("target",),
            "validation_queue",
            "validation:real_source_entry",
            resolution.queue_intent_id,
            resolution.queue_resolution_id,
        ),
    )
    blocked = any(item.status != "complete" for item in result.node_results)
    return {
        "ok": bool(result.node_results)
        and (not blocked or (result.after_state == state and not result.mutations)),
        "source_path": evidence["path"],
        "graph_id": graph_id,
        "formal_root_count": sum(
            item.invocation_role == "standalone_root" for item in phases
        ),
        "blocked_reason": next(
            (item.reason_code for item in result.node_results if item.status != "complete"),
            "",
        ),
        "mutation_count": len(result.mutations),
    }


def validate(tbgd_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    success = _run_scheduler_case()
    failure = _run_scheduler_case(cycle=True)
    identity_failure = _run_scheduler_case(
        entry_updates={"action_or_ability_ref": "forged:ability"}
    )
    direct = _direct_blockers()
    full_build_count = 0
    original_build = TBGDLowering.build

    def forbidden_build(*_args: Any, **_kwargs: Any):
        nonlocal full_build_count
        full_build_count += 1
        raise AssertionError("focused validation cannot build full CanonicalIR")

    TBGDLowering.build = forbidden_build
    try:
        real = _real_source_probe(tbgd_root)
    finally:
        TBGDLowering.build = original_build
    action_rules, action_definition = _fixture()
    action_calls: list[str] = []
    action_before, action_result = _invoke(
        _system(action_rules, action_calls), action_rules, action_definition
    )
    success_result, failure_result = success["result"], failure["result"]
    identity_failure_result = identity_failure["result"]
    failure_child = failure_result.transition.coverage.get("child_transition", {})
    failure_nodes = (
        failure_child.get("node_results", [])
        if isinstance(failure_child, dict)
        else []
    )
    checks = {
        "queue_standalone_uses_formal_graph_authority": real["ok"]
        and real["formal_root_count"] == 1,
        "queue_cannot_bypass_graph_admission": direct["resolution_identity"],
        "queue_entry_identity_mismatch_fails_closed": (
            identity_failure_result.transition.transaction.command.action_id
            == "queue:blocked_removed"
            and not identity_failure["calls"]
            and identity_failure_result.transition.coverage.get(
                "queue_terminal_plan", {}
            ).get("blocked_reason")
            == "queue_standalone_entry_identity_mismatch"
            and all(
                mutation.path == ("queues", "interrupt_queue")
                for mutation in identity_failure_result.transition.transaction.mutations
            )
            and identity_failure["replay_ok"]
            and identity_failure["contract_ok"]
        ),
        "standalone_root_cannot_enter_legacy_callback": direct[
            "standalone_root_bypass"
        ],
        "standalone_reuses_action_ability_hooks": action_calls == ["fixture:effect"]
        and action_result.after_state != action_before,
        "standalone_root_is_in_active_graph_stack": any(
            isinstance(item, dict)
            and str(item.get("reason_code") or "").startswith(
                "task_graph_active_cycle:"
            )
            for item in failure_nodes
        ),
        "queue_failure_publishes_no_partial_ability_channels": (
            failure_result.after_state.units == failure["state"].units
            and failure_result.after_state.global_flags
            == failure["state"].global_flags
            and all(
                mutation.path == ("queues", "interrupt_queue")
                for mutation in failure_result.transition.transaction.mutations
            )
            and not any(
                event.event_id == "fixture:event"
                for event in failure_result.transition.transaction.events
            )
            and not failure_result.transition.rng_events
            and not any(
                record.get("record_type") == "fixture_effect"
                for record in failure_result.transition.transaction.settlement.records
            )
            and failure["replay_ok"]
            and failure["contract_ok"]
        ),
        "temporary_action_definition_created": success["temporary_constructions"][
            "definition"
        ]
        > 0,
        "temporary_action_command_created": success["temporary_constructions"][
            "command"
        ]
        > 0,
        "standalone_action_dependent_leaf_fails_closed": direct["action_dependent_leaf"],
        "standalone_child_atomic_commit_count": success["commit_count"] - 1,
        "queue_success_commits_once": success["commit_count"] == 1
        and success_result.after_state.global_flags.get("fixture_count") == 1
        and success["calls"] == ["fixture:effect"]
        and any(event.event_id == "fixture:event" for event in success_result.transition.transaction.events)
        and any(event.event_id == "fixture:rng" for event in success_result.transition.rng_events)
        and any(
            record.get("record_type") == "fixture_effect"
            for record in success_result.transition.transaction.settlement.records
        )
        and success["replay_ok"]
        and success["contract_ok"],
        "full_canonical_build_count": full_build_count,
    }
    ok = all(
        value is True
        for key, value in checks.items()
        if key not in {
            "temporary_action_definition_created",
            "temporary_action_command_created",
            "standalone_child_atomic_commit_count",
            "full_canonical_build_count",
        }
    ) and (
        checks["temporary_action_definition_created"] is False
        and checks["temporary_action_command_created"] is False
        and type(checks["standalone_child_atomic_commit_count"]) is int
        and checks["standalone_child_atomic_commit_count"] == 0
        and type(checks["full_canonical_build_count"]) is int
        and checks["full_canonical_build_count"] == 0
    )
    return {
        "ok": ok,
        "checks": checks,
        "real_source": real,
        "success": {
            "command": success_result.transition.transaction.command.action_id,
            "mutation_count": len(success_result.transition.transaction.mutations),
            "effect_calls": success["calls"],
        },
        "failure": {
            "command": failure_result.transition.transaction.command.action_id,
            "mutation_count": len(failure_result.transition.transaction.mutations),
            "effect_calls_before_rollback": failure["calls"],
        },
        "resource": {
            "wall_seconds": round(time.monotonic() - started, 3),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "full_canonical_build_count": full_build_count,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = validate(args.tbgd_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "validation_summary_p9_s8b3c.json", summary)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
