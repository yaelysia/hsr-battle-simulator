"""Real scheduler drain, formal window, per-hit context and snapshot/replay."""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityPhaseIR, AbilityTaskIR, BattleStateTransitionIR, CanonicalIR, DamageEmissionIR,
    EffectIR, FormulaIR, HitProfileIR, IRSource, QueueIntentIR, QueuePriorityIR, QueueResolutionIR, QueueWindowIR,
    StandaloneAbilityGraphIR, StatusCallbackIR, StatusCallbackTaskIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphQueryResult
from hsr.simulator_v8_clean_core.systems.queue import QueueEntry
from hsr.simulator_v8_clean_core.systems.scheduler import CombatScheduler
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import _graph


def test_queue_life_scope_lowering_preserves_explicit_permissions_and_rejects_unknowns():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _queue_intent_from_task

    source = IRSource("validation_fixture/queue_life_scope", "TurnInsertAbility", "fixture")
    def lower(task):
        return _queue_intent_from_task(callback_id="fixture", task_id="fixture", event="OnLimboWaitHeal",
            opcode="TurnInsertAbility", task=task, source=source, queue_priority_lookup={})
    # This input checks field normalization, not complete queue/source admission.
    default = lower({})
    assert default.owner_alive_state == default.target_alive_state == "alive_only"
    assert not default.can_run_on_unselectable_target
    raw = {"OwnerAliveState": "Mask_AliveOrLimbo", "TargetAliveState": "Mask_Alive",
           "CanRunOnUnselectableTarget": True}
    normalized = lower(raw)
    assert normalized.owner_alive_state == "alive_or_limbo" and normalized.target_alive_state == "alive_only"
    assert normalized.to_json()["can_run_on_unselectable_target"] is True
    assert all(normalized.abort_policy[key] == value for key, value in raw.items())
    invalid = lower({**raw, "OwnerAliveState": "Anyone", "CanRunOnUnselectableTarget": 1})
    assert invalid.coverage_status == "blocked"
    assert "owneralivestate_not_admitted" in invalid.blocked_reason
    assert "can_run_on_unselectable_target_not_bool" in invalid.blocked_reason


def test_drain_starts_and_ends_formal_moment_and_failed_body_publishes_neither():
    source = IRSource("validation_fixture/queue", "AbilityTask", "queue", {
        "json_path": "$.OnStart[0]", "source_opcode": "DamageByAttackProperty", "content_sha256": "c" * 64})
    tasks, phases, effects, profiles, emissions, standalones, resolutions, graphs = [], [], [], [], [], [], [], {}
    for name, point_source in (("start", "moment"), ("end", "echo")):
        action_id = f"standalone_ability:{name}"
        task = AbilityTaskIR(f"task:{name}", f"phase:{name}", action_id, 0, name, "OnStart", 0,
            "$.OnStart[0]", "root", "DamageByAttackProperty", source,
            effect_id=f"effect:{name}", coverage_status="executable")
        tasks.append(task)
        phases.append(AbilityPhaseIR(task.phase_id, "", action_id, 0, name, 0, {}, {}, {}, source,
            coverage_status="executable", task_ids=(task.task_id,), invocation_role="standalone_root"))
        effect = EffectIR(task.effect_id, task.opcode, {},
            replace(source, evidence={**source.evidence, "parent_task_id": ""}), coverage_status="audit_only")
        effects.append(effect)
        profiles.append(HitProfileIR(f"hit:{name}", action_id, 0, 0, "selected", numeric_fixed(1), {},
            numeric_fixed(0), {}, "elation", "Fire", source, coverage_status="executable"))
        emissions.append(DamageEmissionIR(f"damage:{name}", action_id, 0, task.phase_id, task.task_id,
            f"hit:{name}", "selected", "elation", "Fire", numeric_fixed(1),
            {"kind": "elation_level_base", "elation_point_source": point_source,
             "admission_status": "executable", "attack_type": "ElationDamage"},
            source, coverage_status="executable", toughness_emission_required=False))
        standalones.append(StandaloneAbilityGraphIR(f"standalone:{name}", name, "mainline_avatar",
            (task.phase_id,), (task.task_id,), (task.task_id,), source, "executable"))
        resolutions.append(QueueResolutionIR(f"resolution:{name}", f"intent:{name}", name,
            "standalone_ability_graph", {"standalone_ability_graph_id": f"standalone:{name}",
            "phase_ids": [task.phase_id], "task_ids": [task.task_id], "executable_task_ids": [task.task_id]},
            source, coverage_status="executable"))
        graphs[task.phase_id] = _graph(task.phase_id, task, references=(("effect", effect.effect_id,
            "deferred", "task_graph_definition_not_admitted:effect:audit_only"),))
    class GraphRules(RuleBook):
        def query_formal_task_graph(self, entry_kind, owner_id, callback_kind, formal_task_ids):
            graph = graphs[owner_id]
            return TaskGraphQueryResult("resolved", "graph", (graph.graph_id,), graph, "")

        def query_task_graph(self, graph_id):
            graph = next(value for value in graphs.values() if value.graph_id == graph_id)
            return TaskGraphQueryResult("resolved", "graph", (graph_id,), graph, "")

        def query_task_graph_node(self, node_id):
            node = next(node for graph in graphs.values() for node in graph.nodes if node.graph_node_id == node_id)
            return TaskGraphQueryResult("resolved", "node", (node_id,), node, "")
    registry = build_engine_rule_registry()
    transitions = (
        BattleStateTransitionIR("window:start", "turn_insert_action_priority", "priority:start",
            ("global_flags", "elation_time_active"), False, True, "elation.time.started", "OnListenElationTimeStart",
            source, coverage_status="executable", allow_missing_before=True),
        BattleStateTransitionIR("window:end", "turn_insert_ability", "end",
            ("global_flags", "elation_time_active"), True, False, "elation.time.ended", "OnListenElationTimeEnd",
            source, coverage_status="executable"),
    )
    rules = GraphRules(CanonicalIR("queue-window", ability_tasks=tuple(tasks), ability_phases=tuple(phases),
        effects=tuple(effects), hit_profiles=tuple(profiles), damage_emissions=tuple(emissions),
        standalone_ability_graphs=tuple(standalones), queue_resolutions=tuple(resolutions),
        battle_state_transitions=transitions, damage_formula_rules=registry.damage_formula_rules,
        damage_route_rules=registry.damage_route_rules, resource_rules=registry.resource_rules,
        formulas=(FormulaIR("formula:elation_level_base", "elation_level_base", {"values": {"80": 100}}, source, "executable"),
            FormulaIR("formula:elation_multiplier_rule", "elation_multiplier_rule",
                      {"punchline_numerator": 5., "punchline_offset": 240.}, source, "executable"))))
    def entry(name):
        return QueueEntry(f"entry:{name}", "interrupt_queue", "turn_insert_ability", f"intent:{name}",
            "actor", name, ("target",), {"priority_ordering_admitted": True, "priority_value": 1,
                "queue_priority_id": f"priority_ir:{name}"}, source.to_json(),
            queue_priority_id=f"priority_ir:{name}",
            priority_key="priority:start" if name == "start" else "", queue_window_id=f"window:{name}",
            window_family="insert_ability", target_resolution={"ok": True, "target_ids": ["target"]},
            elation_override_points=40. if name == "start" else None).to_json()
    state = BattleState(units={"actor": UnitState("actor", "ally", "fixture", hp=1000, max_hp=1000,
        resources={"elation_echo_point": 7}), "target": UnitState("target", "enemy", "fixture", hp=10000, max_hp=10000)},
        queues={"interrupt_queue": (entry("start"), entry("end"))})
    intent = QueueIntentIR("intent:start", "queue:task", "queue:callback", "", "TurnInsertAbility", "interrupt_queue",
        {"priority_ordering_admitted": True, "priority_value": 1., "priority_key": "priority:start",
         "queue_priority_id": "priority_ir:start"},
        "Caster", "start", numeric_fixed(0), "ParamEntity", True, {}, source,
        coverage_status="executable", elation_point_override_expr=numeric_fixed(40))
    window = QueueWindowIR("window:start", intent.queue_intent_id, intent.queue_kind, "insert_ability",
                           "priority:start", 1., {}, source, coverage_status="executable")
    end_intent = replace(intent, queue_intent_id="intent:end", action_ref_or_ability_name="end",
        priority_source={"priority_ordering_admitted": True, "priority_value": 1., "queue_priority_id": "priority_ir:end"},
        elation_point_override_expr=None)
    rules = GraphRules(replace(rules.ir, queue_intents=(intent, end_intent),
        queue_windows=(window, replace(window, queue_window_id="window:end", queue_intent_id="intent:end", priority_key="")),
        queue_priorities=tuple(QueuePriorityIR(f"priority_ir:{name}", "fixture", name, 1., source) for name in ("start", "end"))))
    callback = StatusCallbackIR("queue:callback", "Fixture", "OnAfterAttack", ("queue:task",),
                                source, (0, 0), coverage_status="executable")
    task = StatusCallbackTaskIR("queue:task", callback.callback_id, "Fixture", callback.event, 0,
        "root", "root", "TurnInsertAbility", source, coverage_status="executable")
    detail = {"owner_id": "actor", "caster_id": "actor", "modifier_name": "Fixture", "status_id": "modifier:Fixture"}
    empty = replace(state, queues={})
    produced = StatusCallbackSystem(rules)._execute_queue_intents(empty, callback, task, detail,
        GameEvent("fixture", source_id="actor", target_id="target"), (intent,))
    assert produced.ok, produced.errors
    checked = RuntimeSourceAuditor(rules).validate_execution(produced.mutations, produced.records)
    assert checked.ok, checked.to_json()
    assert produced.after_state.queues["interrupt_queue"][0]["elation_override_points"] == 40
    assert "elation_time_active" not in produced.after_state.global_flags
    sentinel = StatusCallbackSystem(rules)._execute_queue_intents(empty, callback, task, detail,
        GameEvent("fixture", source_id="actor", target_id="target"),
        (replace(intent, elation_point_override_expr=numeric_fixed(-1)),))
    assert sentinel.ok and sentinel.after_state.queues["interrupt_queue"][0]["elation_override_points"] is None
    state = replace(produced.after_state, queues={"interrupt_queue": (
        produced.after_state.queues["interrupt_queue"][0], entry("end"))})
    initial = state.snapshot().to_json()
    started = CombatScheduler(rules)._try_queue_drain(state)
    assert started.transition.outcome.successor_eligible, started.transition.outcome.to_json()
    assert started.after_state.global_flags["elation_time_active"] is True
    damage = next(row["payload"] for row in started.transition.transaction.settlement.records if row["record_type"] == "damage")
    assert damage["elation_formula"]["context"]["points"] == 40
    assert damage["elation_formula"]["context"]["source_kind"] == "moment"
    assert any(event.event_type == "elation.time.started" for event in started.transition.transaction.events)
    checked = RuntimeSourceAuditor(rules).validate_execution(started.transition.transaction.mutations,
        started.transition.transaction.settlement.records)
    assert checked.ok, checked.to_json()
    assert MutationReducer().replay_snapshot(state, started.transition.transaction.mutations,
                                             started.after_state.snapshot().to_json()).ok
    ended = CombatScheduler(rules)._try_queue_drain(started.after_state)
    assert ended.transition.outcome.successor_eligible, ended.transition.outcome.to_json()
    assert ended.after_state.global_flags["elation_time_active"] is False
    assert any(event.event_type == "elation.time.ended" for event in ended.transition.transaction.events)
    checked = RuntimeSourceAuditor(rules).validate_execution(ended.transition.transaction.mutations,
        ended.transition.transaction.settlement.records)
    assert checked.ok, checked.to_json()
    failed = CombatScheduler(GraphRules(replace(rules.ir, formulas=())))._try_queue_drain(state)
    assert "elation_time_active" not in failed.after_state.global_flags
    assert failed.after_state.units["target"].hp == state.units["target"].hp
    assert not failed.transition.rng_events
    assert state.snapshot().to_json() == initial
