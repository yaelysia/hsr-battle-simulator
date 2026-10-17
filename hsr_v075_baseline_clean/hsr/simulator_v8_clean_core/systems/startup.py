"""Shared source-bound startup for initial setup and subsequent unit births."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.ir import AbilityPhaseIR, AbilityTaskIR
from ..rules.engine_rule_registry import EngineRuleRegistry, engine_numeric_binding_source
from ..rules.expression_ir import numeric_dynamic_hashes
from ..rules.rulebook import RuleBook
from ..rules.task_graph import TaskGraphIR
from .ability import AbilityTaskSystem, CharacterStartupInvocation, CharacterBuildStartupInvocation
from .effect import EffectExecutionContext, EffectRegistry
from .event_dispatch import EventDispatchSystem
from .status import StatusSystem
from .dynamic_values import store_from_state, upsert_dynamic_value


@dataclass(frozen=True)
class _SetupApplyResult:
    state: BattleState
    records: tuple[dict[str, JSONValue], ...] = ()
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    blocked: tuple[dict[str, JSONValue], ...] = ()
    source_traces: tuple[dict[str, JSONValue], ...] = ()
    dispatched_event_ids: frozenset[str] = frozenset()


def _passive_runtime_activation(rules: RuleBook, card: object | None) -> dict[str, Any]:
    if card is None:
        return {"flags": {}, "startup_specs": []}
    card_id = str(getattr(card, "card_id", ""))
    if not card_id:
        return {"flags": {}, "startup_specs": []}
    slots = rules.passive_mechanism_slots_for_card(card_id)
    enabled_slot_ids: list[str] = []
    blocked_slots: list[dict[str, Any]] = []
    source_traces: list[dict[str, Any]] = []
    startup_specs: list[dict[str, Any]] = []
    for slot in slots:
        source_traces.append(slot.source.to_json())
        if slot.mechanism_kind in {"presentation_only", "empty_ability_declaration"} and slot.coverage_status == "skipped_with_reason":
            continue
        if slot.coverage_status != "executable":
            blocked_slots.append(
                {
                    "passive_slot_id": slot.passive_slot_id,
                    "blocked_reason": slot.blocked_reason or f"passive_slot_not_executable:{slot.coverage_status}",
                    "source": slot.source.to_json(),
                }
            )
            continue
        startup_admission = slot.semantics.get("startup_admission")
        if not isinstance(startup_admission, dict) or startup_admission.get("admission_status") != "executable":
            blocked_slots.append(
                {
                    "passive_slot_id": slot.passive_slot_id,
                    "blocked_reason": "passive_startup_admission_not_executable",
                    "source": slot.source.to_json(),
                }
            )
            continue
        ability_name = str(slot.semantics.get("ability_name") or slot.linked_ir_ids.get("ability_name") or "")
        admitted_task_ids = tuple(
            str(item.get("task_id"))
            for item in _dict_items(startup_admission.get("admitted_tasks"))
            if item.get("task_id")
        )
        enabled_slot_ids.append(slot.passive_slot_id)
        startup_specs.append(
            {
                "kind": "monster_passive_startup_ability",
                "slot": slot,
                "slot_id": slot.passive_slot_id,
                "slot_id_field": "passive_slot_id",
                "ability_name": ability_name,
                "param_values": (),
                "dynamic_value_bindings": {},
                "dynamic_value_binding_mode": "no_dynamic_values_admitted",
                "admitted_task_ids": admitted_task_ids,
            }
        )
    expected_slot_ids = set(getattr(card, "passive_mechanism_slot_ids", ()))
    actual_slot_ids = {slot.passive_slot_id for slot in slots}
    for slot_id in sorted(expected_slot_ids ^ actual_slot_ids):
        blocked_slots.append({
            "passive_slot_id": slot_id,
            "blocked_reason": "monster_passive_slot_reference_not_closed",
        })
    flags: dict[str, Any] = {
        # Formal monster passives own their reduction properties. The numeric
        # pipeline must not add a second implicit unbroken-toughness reduction.
        "toughness_reduction_mode": "status",
        "passive_activation_policy": {
            "kind": "monster_ability_name_list_startup",
            "source_field": "MonsterConfig.AbilityNameList",
            "event_trigger_execution_admitted": False,
        },
        "passive_source_traces": tuple(source_traces),
    }
    template_config = getattr(card, "raw_parameter_blocks", {}).get("template_config")
    stance_count = template_config.get("stance_count") if isinstance(template_config, dict) else None
    if type(stance_count) is int and stance_count > 0:
        flags["monster_stance_count"] = stance_count
        if stance_count > 1:
            flags["stance_segments_remaining"] = stance_count
    if enabled_slot_ids:
        flags["enabled_passive_mechanism_slot_ids"] = tuple(enabled_slot_ids)
    if blocked_slots:
        flags["blocked_passive_mechanism_slots"] = tuple(blocked_slots)
    return {"flags": flags, "startup_specs": startup_specs}


def apply_monster_startup(
    state: BattleState, rules: RuleBook, unit_ids: tuple[str, ...],
) -> _SetupApplyResult:
    """Activate source-bound passives on newly materialized monsters atomically."""
    mutations: list[Mutation] = []
    records: list[dict[str, JSONValue]] = []
    specs: list[dict[str, Any]] = []
    blocked: list[dict[str, JSONValue]] = []
    for unit_id in unit_ids:
        unit = state.units.get(unit_id)
        card = rules.monster_data_card_for_entity(unit.template_id) if unit else None
        if card is None or unit.flags.get("monster_data_card_id") != card.card_id:
            blocked.append({"unit_id": unit_id, "reason": "monster_startup_card_missing_or_mismatched"})
            continue
        activation = _passive_runtime_activation(rules, card)
        blocked.extend({"unit_id": unit_id, **item} for item in
                       activation["flags"].get("blocked_passive_mechanism_slots", ()))
        specs.extend({"unit_id": unit_id, **spec} for spec in activation["startup_specs"])
        mutation = Mutation(
            op="set", path=("units", unit_id, "flags"), before=dict(unit.flags),
            after={**unit.flags, **activation["flags"]},
            reason="initialize source-bound monster passives", source="monster_startup",
            metadata={"monster_data_card_id": card.card_id, "source_trace": card.source.to_json()},
        )
        mutations.append(mutation)
        records.append(SettlementRecord(
            record_type="monster_startup", source="monster_startup", mutation_id=mutation.stable_id(),
            payload={"unit_id": unit_id, "monster_data_card_id": card.card_id},
            trace=card.source.to_json(),
        ).to_json())
    if blocked:
        return _SetupApplyResult(state, blocked=tuple(blocked))
    initialized = MutationReducer().apply_all(state, tuple(mutations))
    result = _apply_startup_ability_effects(initialized, rules, specs)
    if result.blocked:
        return _SetupApplyResult(state, blocked=result.blocked, source_traces=result.source_traces)
    return _SetupApplyResult(
        result.state, records=(*records, *result.records), mutations=(*mutations, *result.mutations),
        events=result.events, rng_events=result.rng_events, source_traces=result.source_traces,
        dispatched_event_ids=result.dispatched_event_ids,
    )


def apply_servant_startup(
    state: BattleState, rules: RuleBook, unit_ids: tuple[str, ...],
    initial_values: dict[str, JSONValue] | None = None,
) -> _SetupApplyResult:
    specs: list[dict[str, Any]] = []
    mutations: list[Mutation] = []
    records: list[dict[str, JSONValue]] = []
    current = state
    for unit_id in unit_ids:
        unit = current.units[unit_id]
        definition = rules.servant_definition(str(unit.flags.get("servant_definition_id") or ""))
        abilities = definition.action_set.get("startup_abilities") if definition else None
        if not isinstance(abilities, list) or not all(isinstance(name, str) and name for name in abilities):
            return _SetupApplyResult(state, blocked=({"unit_id": unit_id, "reason": "servant_startup_declaration_missing"},))
        if initial_values:
            store = store_from_state(current)
            try:
                for name, entry in initial_values.items():
                    store = upsert_dynamic_value(
                        store, scope="unit", owner_id=unit_id, value_name=name,
                        hash_key=entry["hash"], value=entry["value"], source_id=unit_id,
                        source_trace=unit.flags.get("summon_source_trace", {}),
                    )
            except (KeyError, TypeError, ValueError) as exc:
                return _SetupApplyResult(state, blocked=({"unit_id": unit_id, "reason": f"servant_initial_dynamic_values_invalid:{exc}"},))
            mutation = Mutation(
                op="set", path=("global_flags", "dynamic_value_store"),
                before=current.global_flags.get("dynamic_value_store"), after=store,
                before_exists="dynamic_value_store" in current.global_flags,
                source="servant_startup", reason="bind CreateServant parameters before passive startup",
                metadata={"unit_id": unit_id, "values": initial_values,
                          "source_trace": unit.flags.get("summon_source_trace", {})},
            )
            current = MutationReducer().apply_all(current, (mutation,))
            mutations.append(mutation)
            records.append(SettlementRecord(
                record_type="dynamic_value_store", source="servant_startup", mutation_id=mutation.stable_id(),
                payload=mutation.metadata, trace=unit.flags.get("summon_source_trace", {}),
            ).to_json())
        specs.extend({"unit_id": unit_id, "kind": "formal_servant_passive", "ability_name": name} for name in abilities)
    result = _apply_startup_ability_effects(current, rules, specs)
    if result.blocked:
        return _SetupApplyResult(state, blocked=result.blocked, source_traces=result.source_traces)
    return _SetupApplyResult(
        result.state, records=(*records, *result.records), mutations=(*mutations, *result.mutations),
        events=result.events, rng_events=result.rng_events, source_traces=result.source_traces,
        dispatched_event_ids=result.dispatched_event_ids,
    )


def _string_items(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item))
    return ()


def _dict_items(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _legacy_startup_root_tasks(
    tasks: tuple[AbilityTaskIR, ...],
) -> tuple[AbilityTaskIR, ...]:
    return tuple(task for task in tasks if not task.parent_task_id)


def _startup_root_tasks(
    rules: RuleBook,
    phase: AbilityPhaseIR,
    tasks: tuple[AbilityTaskIR, ...],
) -> tuple[tuple[AbilityTaskIR, ...], str]:
    if phase.invocation_role == "external_legacy":
        return _legacy_startup_root_tasks(tasks), ""
    if phase.invocation_role not in {
        "action_root",
        "nested_only",
        "standalone_root",
        "build_startup",
        "unbound_definition",
    }:
        return (), "startup_ability_phase_invocation_role_not_admitted"
    graph_result = rules.query_formal_task_graph(
        "ability_phase_callback",
        phase.phase_id,
        "OnStart",
        (task.task_id for task in tasks),
    )
    graph = graph_result.value
    if graph_result.status != "resolved" or type(graph) is not TaskGraphIR:
        return (), (
            graph_result.blocked_reason or "startup_ability_task_graph_missing"
        )
    tasks_by_id = {task.task_id: task for task in tasks}
    roots = tuple(
        tasks_by_id[task_id] for task_id in graph.root_formal_task_ids
    )
    return roots, ""


def _apply_startup_ability_effects(
    state: BattleState,
    rules: RuleBook,
    startup_specs: list[dict[str, Any]],
) -> _SetupApplyResult:
    if not startup_specs:
        return _SetupApplyResult(state)
    reducer = MutationReducer()
    status_system = StatusSystem(rules)
    effect_registry = EffectRegistry(status_system)
    event_dispatch = EventDispatchSystem(
        rules,
        effect_registry,
        reducer=reducer,
    )
    ability_tasks = AbilityTaskSystem(
        rules, effect_registry, reducer=reducer, event_dispatcher=event_dispatch,
    )
    current = state
    traces: list[dict[str, JSONValue]] = []
    records: list[dict[str, JSONValue]] = []
    mutations: list[Mutation] = []
    events: list[GameEvent] = []
    rng_events: list[RNGEvent] = []
    dispatched_event_ids: set[str] = set()
    blocked: list[dict[str, JSONValue]] = []
    for spec in startup_specs:
        unit_id = str(spec.get("unit_id") or "")
        ability_name = str(spec.get("ability_name") or "")
        slot = spec.get("slot")
        kind = str(spec.get("kind") or "startup_ability")
        if kind in {"formal_character_passive", "formal_character_build", "formal_servant_passive", "formal_stage"}:
            if kind == "formal_stage":
                result = ability_tasks.execute_stage_startup(
                    current, actor_id=unit_id, wave_definition_id=spec["wave_definition_id"],
                )
            elif kind == "formal_servant_passive":
                result = ability_tasks.execute_servant_startup(current, actor_id=unit_id, ability_name=ability_name)
            elif kind == "formal_character_passive":
                result = ability_tasks.execute_character_startup(
                    current, invocation=CharacterStartupInvocation(
                        unit_id, spec["action_id"], spec["action_level"], spec["binding_id"],
                    ),
                )
            else:
                result = ability_tasks.execute_character_build_startup(
                    current, invocation=CharacterBuildStartupInvocation(
                        unit_id, spec["graph_ref_id"], spec["build_binding_ids"],
                    ),
                )
            failures = tuple(node for node in result.node_results if node.status != "complete")
            ok = bool(result.node_results) and not failures
            trace = {
                "kind": kind, "unit_id": unit_id, "ability_name": ability_name,
                "binding_id": spec.get("binding_id"), "build_binding_ids": spec.get("build_binding_ids"),
                **({"wave_definition_id": spec["wave_definition_id"]} if kind == "formal_stage" else {}),
                "status": "applied" if ok else "blocked",
                "reason": ";".join(node.reason_code for node in failures) if failures else "" if ok else "character_startup_graph_not_executed",
            }
            traces.append(trace)
            records.extend(result.records)
            if ok:
                current = result.after_state
                mutations.extend(result.mutations)
                events.extend(result.events)
                rng_events.extend(result.rng_events)
                dispatched_event_ids.update(result.dispatched_event_ids or ())
                dispatched_event_ids.update(str(event.to_json()["event_id"]) for event in result.events
                                            if event.event_type == "status.callback")
            else:
                blocked.append(trace)
            continue
        slot_id = str(spec.get("slot_id") or getattr(slot, "eidolon_slot_id", "") or getattr(slot, "mechanism_slot_id", ""))
        slot_id_field = str(spec.get("slot_id_field") or "slot_id")
        trace_node_id = str(spec.get("trace_node_id") or "")
        graph_ref_id = spec.get("graph_ref_id")
        if isinstance(graph_ref_id, str) and graph_ref_id:
            referenced_graph = rules.standalone_ability_graph(graph_ref_id)
            graphs = (
                (referenced_graph,)
                if referenced_graph is not None
                and referenced_graph.coverage_status == "executable"
                and referenced_graph.ability_name == ability_name
                else ()
            )
        else:
            graphs = tuple(
                graph
                for graph in rules.standalone_ability_graphs_by_name(ability_name)
                if graph.coverage_status == "executable"
            )
        if len(graphs) != 1:
            trace = _startup_trace_payload(
                    kind=kind,
                    unit_id=unit_id,
                    ability_name=ability_name,
                    slot_id=slot_id,
                    slot_id_field=slot_id_field,
                    trace_node_id=trace_node_id,
                    status="blocked",
                    reason="startup_ability_graph_missing_or_ambiguous",
                    extra={"graph_count": len(graphs)},
                )
            traces.append(trace)
            blocked.append(trace)
            continue
        graph = graphs[0]
        admitted_task_ids = set(_string_items(spec.get("admitted_task_ids")))
        candidate_task_count = 0
        for phase_id in graph.phase_ids:
            phase = rules.ability_phase(phase_id)
            phase_tasks = tuple(
                task
                for task in rules.ability_tasks_for_phase(phase_id)
                if task.callback_kind == "OnStart"
            )
            if phase is None:
                topology_reason = "startup_ability_phase_missing"
                root_tasks: tuple[AbilityTaskIR, ...] = ()
            elif not phase_tasks:
                continue
            else:
                root_tasks, topology_reason = _startup_root_tasks(
                    rules,
                    phase,
                    phase_tasks,
                )
                if admitted_task_ids:
                    root_tasks = tuple(
                        task
                        for task in root_tasks
                        if task.task_id in admitted_task_ids
                    )
            if topology_reason:
                trace = _startup_blocked_trace(
                    kind,
                    unit_id,
                    ability_name,
                    slot_id,
                    slot_id_field,
                    trace_node_id,
                    graph,
                    phase_id,
                    topology_reason,
                )
                traces.append(trace)
                blocked.append(trace)
                continue
            for task in root_tasks:
                if (task.opcode != "AddModifier" and not (
                    kind == "monster_passive_startup_ability" and task.opcode == "DefineDynamicValue"
                )) or not task.effect_id:
                    continue
                candidate_task_count += 1
                effect = rules.effect(task.effect_id)
                if effect is None:
                    trace = _startup_blocked_trace(
                            kind,
                            unit_id,
                            ability_name,
                            slot_id,
                            slot_id_field,
                            trace_node_id,
                            graph,
                            task.task_id,
                            "startup_effect_missing",
                        )
                    traces.append(trace)
                    blocked.append(trace)
                    continue
                coverage = effect_registry.coverage(effect)
                if coverage != "executable":
                    trace = _startup_blocked_trace(
                            kind,
                            unit_id,
                            ability_name,
                            slot_id,
                            slot_id_field,
                            trace_node_id,
                            graph,
                            task.task_id,
                            f"startup_effect_not_executable:{coverage}",
                        )
                    traces.append(trace)
                    blocked.append(trace)
                    continue
                dynamic_values, binding_trace = _startup_dynamic_values(
                    effect.payload.get("standard"),
                    spec,
                    rules.engine_rule_registry(),
                )
                if binding_trace.get("admission_status") == "blocked":
                    trace = _startup_blocked_trace(
                            kind,
                            unit_id,
                            ability_name,
                            slot_id,
                            slot_id_field,
                            trace_node_id,
                            graph,
                            task.task_id,
                            str(binding_trace.get("blocked_reason") or "startup_dynamic_value_binding_blocked"),
                            binding_trace=binding_trace,
                        )
                    traces.append(trace)
                    blocked.append(trace)
                    continue
                before_task = current
                if task.opcode == "DefineDynamicValue":
                    result = effect_registry.execute(effect, EffectExecutionContext(
                        state=before_task, caster_id=unit_id, owner_id=unit_id,
                        source_id=f"{kind}:{slot_id}:{ability_name}:{task.task_id}",
                        param_entity_id=unit_id, current_action_target_id=unit_id,
                        dynamic_values=dynamic_values, include_ambient_status_bindings=False,
                        event_payload={"operation_event_id": f"startup:{before_task.event_index}:{unit_id}:{slot_id}:{task.task_id}"},
                    ))
                    effect_ok = not result.unsupported
                else:
                    result = status_system.apply_add_modifier(
                        before_task,
                        effect,
                        application_instance_id=(
                            f"startup:{before_task.event_index}:{unit_id}:{slot_id}:{ability_name}:{task.task_id}"
                        ),
                        caster_id=unit_id,
                        source_id=f"{kind}:{slot_id}:{ability_name}:{task.task_id}",
                        owner_id=unit_id,
                        param_entity_id=unit_id,
                        current_action_target_id=unit_id,
                        dynamic_values=dynamic_values,
                        binding_sources=(),
                        retained_runtime_hashes=tuple(
                            sorted(
                                {
                                    str(binding["hash"])
                                    for binding in binding_trace.get("bindings", ())
                                    if isinstance(binding, dict)
                                    and isinstance(binding.get("hash"), (str, int))
                                    and str(binding["hash"]) in dynamic_values
                                }
                            )
                        ),
                    )
                    effect_ok = result.ok
                candidate_state = reducer.apply_all(before_task, result.mutations)
                task_mutations: list[Mutation] = list(result.mutations)
                task_records: list[dict[str, JSONValue]] = list(result.records)
                task_events: list[GameEvent] = []  # The dispatcher returns the normalized lifecycle events.
                task_rng_events: list[RNGEvent] = list(result.rng_events)
                listener_mutation_count = 0
                listener_record_count = 0
                listener_dispatch_count = 0
                listener_errors: list[str] = []
                task_dispatched_event_ids: set[str] = set()
                if effect_ok:
                    for lifecycle_event in result.events:
                        listener_dispatch_count += 1
                        dispatch_result = event_dispatch.dispatch_event(
                            candidate_state,
                            event=lifecycle_event,
                        )
                        candidate_state = dispatch_result.after_state
                        task_mutations.extend(dispatch_result.mutations)
                        task_records.extend(dispatch_result.records)
                        task_events.extend(dispatch_result.events)
                        task_rng_events.extend(dispatch_result.rng_events)
                        task_dispatched_event_ids.update(dispatch_result.dispatched_event_ids)
                        task_dispatched_event_ids.update(str(event.to_json()["event_id"]) for event in dispatch_result.events
                                                         if event.event_type == "status.callback")
                        listener_mutation_count += len(dispatch_result.mutations)
                        listener_record_count += len(dispatch_result.records)
                        listener_errors.extend(dispatch_result.errors)
                startup_ok = effect_ok and not listener_errors
                current = candidate_state if startup_ok else before_task
                if startup_ok:
                    mutations.extend(task_mutations)
                    records.extend(task_records)
                    events.extend(task_events)
                    rng_events.extend(task_rng_events)
                    dispatched_event_ids.update(task_dispatched_event_ids)
                trace = _startup_trace_payload(
                        kind=kind,
                        unit_id=unit_id,
                        ability_name=ability_name,
                        slot_id=slot_id,
                        slot_id_field=slot_id_field,
                        trace_node_id=trace_node_id,
                        status="applied" if startup_ok else "blocked",
                        reason=(
                            ";".join(listener_errors)
                            if listener_errors
                            else (
                                ";".join(result.unsupported)
                                if not effect_ok
                                else ""
                            )
                        ),
                        extra={
                            "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                            "task_id": task.task_id,
                            "effect_id": effect.effect_id,
                            "mutation_count": len(result.mutations),
                            "listener_mutation_count": listener_mutation_count,
                            "listener_record_count": listener_record_count,
                            "listener_dispatch_count": listener_dispatch_count,
                            "listener_errors": listener_errors,
                            "unsupported": list(result.unsupported),
                            "dynamic_value_binding": binding_trace,
                            "source": getattr(slot, "source", None).to_json() if getattr(slot, "source", None) else {},
                        },
                    )
                traces.append(trace)
                if not startup_ok:
                    blocked.append(trace)
                    reason = str(trace.get("reason") or "startup_ability_atomic_rollback")
                    records.append(
                        SettlementRecord(
                            record_type="startup_ability_blocked",
                            source="scenario_state_builder",
                            process_only=True,
                            payload={
                                "reason": reason,
                                "unit_id": unit_id,
                                "ability_name": ability_name,
                                "task_id": task.task_id,
                                "state_unchanged": True,
                            },
                            trace={
                                "ability_graph_source": graph.source.to_json(),
                                "task_source": task.source.to_json(),
                                "effect_source": effect.source.to_json(),
                            },
                        ).to_json()
                    )
        if candidate_task_count == 0:
            trace = _startup_trace_payload(
                    kind=kind,
                    unit_id=unit_id,
                    ability_name=ability_name,
                    slot_id=slot_id,
                    slot_id_field=slot_id_field,
                    trace_node_id=trace_node_id,
                    status="blocked",
                    reason="startup_ability_has_no_admitted_on_start_effect",
                    extra={"standalone_ability_graph_id": graph.standalone_ability_graph_id},
                )
            traces.append(trace)
            blocked.append(trace)
    return _SetupApplyResult(
        state=current,
        records=tuple(records),
        mutations=tuple(mutations),
        events=tuple(events),
        rng_events=tuple(rng_events),
        blocked=tuple(blocked),
        source_traces=tuple(traces),
        dispatched_event_ids=frozenset(dispatched_event_ids),
    )


def _startup_dynamic_values(
    standard: object,
    spec: dict[str, Any],
    engine_rules: EngineRuleRegistry,
) -> tuple[dict[str, float], dict[str, object]]:
    if not isinstance(standard, dict):
        return {}, {"admission_status": "not_applicable", "reason": "standard_payload_missing"}
    params = tuple(_number_items(spec.get("param_values")))
    configured_bindings = spec.get("dynamic_value_bindings")
    configured_by_hash = configured_bindings.get("by_hash") if isinstance(configured_bindings, dict) else None
    if not isinstance(configured_by_hash, dict):
        configured_by_hash = {}
    requests = standard.get("dynamic_value_requests")
    if not isinstance(requests, dict):
        requests = {}
    hash_requests, fixed_request_names = _startup_numeric_hash_requests(
        standard,
        requests,
    )
    if spec.get("dynamic_value_binding_mode") == "configured_by_hash_required":
        requested_hashes = {str(item["hash"]) for item in hash_requests}
        for hash_key in sorted(configured_by_hash):
            if hash_key in requested_hashes:
                continue
            hash_requests.append(
                {
                    "name": f"graph_parameter:{hash_key}",
                    "hash": hash_key,
                    "expose_name": False,
                    "numeric_fields": ["graph_parameter_binding"],
                }
            )
    if not hash_requests:
        if configured_by_hash:
            return _eidolon_configured_dynamic_values(params, configured_by_hash, spec)
        return {}, {
            "admission_status": "not_applicable",
            "reason": (
                "all_startup_numeric_values_are_fixed_in_ir"
                if fixed_request_names
                else "no_startup_dynamic_value_requests"
            ),
            "fixed_request_names": fixed_request_names,
        }
    dynamic_values: dict[str, float] = {}
    bindings: list[dict[str, object]] = []
    pending_requests: list[dict[str, object]] = []
    for request in hash_requests:
        engine_binding, engine_reason = engine_numeric_binding_source(
            request.get("expression"),
            engine_rules,
        )
        if engine_reason:
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": engine_reason,
                "request_name": request["name"],
                "hash": str(request["hash"]),
            }
        by_hash = (
            engine_binding.get("by_hash")
            if isinstance(engine_binding, dict)
            else None
        )
        hash_key = str(request["hash"])
        entry_key = by_hash.get(hash_key) if isinstance(by_hash, dict) else None
        entries = (
            engine_binding.get("entries")
            if isinstance(engine_binding, dict)
            else None
        )
        entry = entries.get(entry_key) if isinstance(entries, dict) else None
        value = entry.get("value") if isinstance(entry, dict) else None
        if (
            isinstance(entry_key, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            dynamic_values[hash_key] = float(value)
            bindings.append(
                {
                    "name": request["name"],
                    "hash": hash_key,
                    "value": float(value),
                    "numeric_fields": list(request["numeric_fields"]),
                    "binding_source_kind": "engine_numeric_convention",
                    "binding_source": entry,
                }
            )
            continue
        pending_requests.append(request)
    hash_requests = pending_requests
    for index, request in enumerate(hash_requests):
        name = request["name"]
        raw_hash = request["hash"]
        configured = configured_by_hash.get(str(raw_hash))
        param_index = index
        binding_source_kind = "startup_param_request_order"
        if isinstance(configured, dict):
            configured_index = configured.get("param_index")
            if not isinstance(configured_index, int):
                return {}, {
                    "admission_status": "blocked",
                    "blocked_reason": "startup_dynamic_value_binding_param_index_missing",
                    "request_name": name,
                    "hash": str(raw_hash),
                    "binding": configured,
                }
            param_index = configured_index
            binding_source_kind = "character_config_dynamic_value_read_info"
        elif spec.get("dynamic_value_binding_mode") == "configured_by_hash_required":
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "startup_dynamic_value_binding_hash_missing",
                "request_name": name,
                "hash": str(raw_hash),
            }
        elif len(params) != len(hash_requests):
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "startup_param_binding_missing",
                "param_count": len(params),
                "request_count": len(hash_requests),
                "request_names": [item["name"] for item in hash_requests],
                "hash": str(raw_hash),
            }
        if param_index < 0 or param_index >= len(params):
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "startup_dynamic_value_binding_param_index_out_of_range",
                "request_name": name,
                "hash": str(raw_hash),
                "param_index": param_index,
                "param_count": len(params),
            }
        value = float(params[param_index])
        if request["expose_name"]:
            dynamic_values[name] = value
        dynamic_values[str(raw_hash)] = value
        bindings.append(
            {
                "name": name,
                "hash": str(raw_hash),
                "param_index": param_index,
                "value": value,
                "numeric_fields": list(request["numeric_fields"]),
                "binding_source_kind": binding_source_kind,
                "binding_source": configured if isinstance(configured, dict) else {},
            }
        )
    return dynamic_values, {
        "admission_status": "executable",
        "source_kind": f"{str(spec.get('kind') or 'startup_ability')}_param_to_dynamic_value_request",
        "bindings": bindings,
        "fixed_request_names": fixed_request_names,
        "slot_id": str(spec.get("slot_id") or ""),
        "trace_node_id": str(spec.get("trace_node_id") or ""),
        "eidolon_slot_id": str(getattr(spec.get("slot"), "eidolon_slot_id", "")),
        "rank_id": str(getattr(spec.get("slot"), "rank_id", "")),
    }


def _startup_numeric_hash_requests(
    standard: dict[str, object],
    requests: dict[str, object],
) -> tuple[list[dict[str, object]], list[str]]:
    """Collect every typed numeric hash consumed while adding a status.

    ``DynamicValues`` is only one consumer.  Duration, stack, refresh and
    chance expressions are evaluated by the same generic status application
    and must use the same source-backed parameter bindings.  Requests are
    deduplicated by hash while retaining every field that consumes it.
    """

    fixed_request_names: list[str] = []
    rows_by_hash: dict[str, dict[str, object]] = {}

    def add(name: str, expression: object, *, expose_name: bool) -> None:
        if isinstance(expression, dict) and expression.get("kind") == "fixed":
            fixed_request_names.append(name)
            return
        hashes = tuple(numeric_dynamic_hashes(expression))
        for raw_hash in hashes:
            hash_key = str(raw_hash)
            row = rows_by_hash.get(hash_key)
            if row is None:
                rows_by_hash[hash_key] = {
                    "name": name,
                    "hash": raw_hash,
                    "expression": expression,
                    "expose_name": expose_name and len(hashes) == 1,
                    "numeric_fields": [name],
                }
                continue
            fields = row["numeric_fields"]
            if isinstance(fields, list) and name not in fields:
                fields.append(name)
            if expose_name and len(hashes) == 1:
                row["name"] = name
                row["expose_name"] = True

    for name, request in requests.items():
        if not isinstance(request, dict):
            continue
        expression = request.get("expr")
        raw_hash = request.get("hash")
        if raw_hash is not None and not numeric_dynamic_hashes(expression):
            expression = {
                "schema_version": "hsr.numeric_expression.v1",
                "kind": "dynamic_hash",
                "supported": True,
                "hash": raw_hash,
            }
        add(str(name), expression, expose_name=True)

    for field_name in ("lifetime", "layer_add_when_stack", "max_layer", "chance"):
        add(field_name, standard.get(field_name), expose_name=False)

    return list(rows_by_hash.values()), sorted(set(fixed_request_names))


def _eidolon_configured_dynamic_values(
    params: tuple[float, ...],
    configured_by_hash: dict[str, object],
    spec: dict[str, Any],
) -> tuple[dict[str, float], dict[str, object]]:
    dynamic_values: dict[str, float] = {}
    bindings: list[dict[str, object]] = []
    for hash_key, configured in configured_by_hash.items():
        if not isinstance(configured, dict):
            continue
        param_index = configured.get("param_index")
        if not isinstance(param_index, int):
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "eidolon_configured_dynamic_value_param_index_missing",
                "hash": str(hash_key),
                "binding": configured,
            }
        if param_index < 0 or param_index >= len(params):
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "eidolon_configured_dynamic_value_param_index_out_of_range",
                "hash": str(hash_key),
                "param_index": param_index,
                "param_count": len(params),
            }
        value = float(params[param_index])
        dynamic_values[str(hash_key)] = value
        bindings.append(
            {
                "hash": str(hash_key),
                "param_index": param_index,
                "value": value,
                "binding_source_kind": "character_config_dynamic_value_read_info",
                "binding_source": configured,
            }
        )
    return dynamic_values, {
        "admission_status": "executable",
        "source_kind": "eidolon_rank_param_to_rank_ability_configured_dynamic_values",
        "bindings": bindings,
        "eidolon_slot_id": str(getattr(spec.get("slot"), "eidolon_slot_id", "")),
        "rank_id": str(getattr(spec.get("slot"), "rank_id", "")),
    }


def _startup_trace_payload(
    *,
    kind: str,
    unit_id: str,
    ability_name: str,
    slot_id: str,
    slot_id_field: str,
    trace_node_id: str,
    status: str,
    reason: str = "",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": kind,
        "unit_id": unit_id,
        "ability_name": ability_name,
        "slot_id": slot_id,
        slot_id_field: slot_id,
        "status": status,
    }
    if trace_node_id:
        payload["trace_node_id"] = trace_node_id
    if reason:
        payload["reason"] = reason
    if extra:
        payload.update(extra)
    return payload


def _startup_blocked_trace(
    kind: str,
    unit_id: str,
    ability_name: str,
    slot_id: str,
    slot_id_field: str,
    trace_node_id: str,
    graph: object,
    task_id: str,
    reason: str,
    *,
    binding_trace: dict[str, object] | None = None,
) -> dict[str, object]:
    return _startup_trace_payload(
        kind=kind,
        unit_id=unit_id,
        ability_name=ability_name,
        slot_id=slot_id,
        slot_id_field=slot_id_field,
        trace_node_id=trace_node_id,
        status="blocked",
        reason=reason,
        extra={
            "standalone_ability_graph_id": str(getattr(graph, "standalone_ability_graph_id", "")),
            "task_id": task_id,
            "dynamic_value_binding": binding_trace or {},
        },
    )


def _number_items(value: object) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[float] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            result.append(float(item))
    return tuple(result)
