from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterator

from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    JSONValue,
    Mutation,
    TargetResolution,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..core.settlement import SettlementRecord
from ..core.unit_state_codec import unit_state_from_payload, unit_state_to_payload
from ..immutable_json import thaw_json
from ..ir_types import IRSource
from ..rules.evaluator import EvaluationContext, RuleEvaluator
from ..rules.expression_ir import (
    CONDITION_EXPRESSION_NODE_SCHEMA,
    numeric_dynamic_hash,
    numeric_fixed,
)
from ..rules.ir import (
    CanonicalIR,
    ConditionIR,
    EffectIR,
    RuleEntity,
    StatusEventFamilyIR,
    TargetExpressionIR,
    TargetExpressionNodeIR,
    UnitBirthTemplateIR,
)
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import PanelInput, ScenarioSpec, UnitSpec
from ..systems.status import StatusApplicationResult, StatusSystem
from ..systems.scheduler import CombatScheduler
from ..systems.summon import SummonSystem, SummonTransitionPlan
from ..systems.summon_runtime import (
    SUMMON_RUNTIME_SCHEMA_VERSION,
    empty_summon_runtime,
    validate_summon_runtime,
)
from ..systems.target import TargetPolicy, TargetSystem
from ..systems.unit_spawn import UnitSpawnRequest, UnitSpawnSystem
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..systems.wave import WaveTransitionPlan, WaveTransitionResult
from ..tbgd.light_cone_cards import build_light_cone_catalog
from ..tbgd.lowering import _modifier_addition_effects
from .io import write_json


VALIDATION_VERSION = "p8_r1_summon_runtime_halo_lifecycle_v1"


def _source(tag: str, *, path: str | None = None) -> IRSource:
    return IRSource(
        source_path=path or f"validation/P8-R1/{tag}.json",
        raw_type="ValidationSource",
        raw_id=tag,
        evidence={"validation_scope": "P8-R1", "tag": tag},
    )


def _target_expression(
    expression_id: str,
    alias: str,
    source: IRSource,
) -> TargetExpressionIR:
    return TargetExpressionIR(
        target_expression_id=expression_id,
        expression_kind="TargetAlias",
        alias=alias,
        payload={"TargetType": alias},
        source=source,
        node=TargetExpressionNodeIR(
            expression_kind="TargetAlias",
            alias=alias,
        ),
        coverage_status="executable",
    )


def _standard_payload(
    modifier_name: str,
    expression: TargetExpressionIR,
    *,
    dynamic: bool = False,
    chance: float = 1.0,
) -> dict[str, JSONValue]:
    return {
        "modifier_name": modifier_name,
        "target_alias": expression.alias,
        "target_expression_id": expression.target_expression_id,
        "lifetime": numeric_fixed(2.0),
        "life_step_moment": "ModifierPhase1End",
        "layer_add_when_stack": numeric_fixed(1.0),
        "max_layer": numeric_fixed(8.0),
        "chance": numeric_fixed(chance),
        "chance_field_present": True,
        "dynamic_values": (
            {"power": numeric_dynamic_hash("power")}
            if dynamic
            else {}
        ),
    }


def _definition(
    name: str,
    source: IRSource,
    *,
    additions: tuple[str, ...] = (),
) -> RuleEntity:
    return RuleEntity(
        entity_id=f"modifier_definition:{name}:{source.raw_id}",
        entity_type="modifier_definition",
        fields={
            "modifier_name": name,
            "map_name": "P8R1Fixture",
            "stacking": "ReplaceByCaster",
            "lifetime": 2.0,
            "lifetime_expr": numeric_fixed(2.0),
            "life_step_moment": "ModifierPhase1End",
            "StatusType": "Buff",
            "behavior_flags": [],
            "dynamic_values": {},
            "dynamic_value_bindings": {
                "by_hash": {
                    "power": {
                        "source_scope": "validation",
                        "source_json_path": "$.DynamicValues.power",
                    }
                },
                "by_name": {"power": {"hashes": ["power"]}},
            },
            "callback_dynamic_hashes": {},
            "addition_effect_ids": list(additions),
        },
        source=source,
        coverage_status="lowered",
    )


def _halo_pair(
    tag: str,
    *,
    child_name: str = "SharedHaloChild",
    alive_only: bool = True,
    child_chance: float = 1.0,
    child_alias: str = "CasterServant",
) -> tuple[
    tuple[RuleEntity, RuleEntity],
    tuple[EffectIR, EffectIR, EffectIR],
    tuple[TargetExpressionIR, TargetExpressionIR, TargetExpressionIR],
]:
    source_json_path = f"$.{tag}.AdditionConfig.SubModifierList[0]"
    source = replace(
        _source(tag),
        evidence={
            "validation_scope": "P8-R1",
            "tag": tag,
            "json_path": source_json_path,
            "target_json_path": f"{source_json_path}.TargetType",
        },
    )
    parent_name = f"Parent{tag}"
    parent_target = _target_expression(
        f"target:{tag}:caster",
        "Caster",
        source,
    )
    child_target = _target_expression(
        f"target:{tag}:servant",
        child_alias,
        source,
    )
    remove_target = _target_expression(
        f"target:{tag}:remove",
        "Caster",
        source,
    )
    child_effect_id = f"effect:{tag}:child"
    parent_effect = EffectIR(
        effect_id=f"effect:{tag}:parent",
        opcode="AddModifier",
        payload={"standard": _standard_payload(parent_name, parent_target, dynamic=True)},
        source=source,
        coverage_status="executable",
        owner_modifier_name=parent_name,
        source_mode="mainline",
        modifier_definition_id=(
            f"modifier_definition:{parent_name}:{source.raw_id}"
        ),
    )
    child_standard = {
        **_standard_payload(
            child_name,
            child_target,
            dynamic=True,
            chance=child_chance,
        ),
        "addition_parent_modifier_name": parent_name,
        "addition_source_json_path": source_json_path,
        "is_halo_status": True,
        "is_halo_status_present": True,
        "is_halo_status_source_json_path": (
            f"{source_json_path}.IsHaloStatus"
        ),
        "alive_only": alive_only,
        "alive_only_raw": "True" if alive_only else "False",
        "alive_only_source_json_path": (
            f"{source_json_path}.AliveOnly"
        ),
        "halo_admission_status": "executable",
        "halo_blocked_reason": "",
    }
    child_effect = EffectIR(
        effect_id=child_effect_id,
        opcode="AddModifier",
        payload={"standard": child_standard},
        source=source,
        coverage_status="executable",
        owner_modifier_name=parent_name,
        source_mode="mainline",
        modifier_definition_id=(
            f"modifier_definition:{child_name}:{source.raw_id}"
        ),
    )
    remove_effect = EffectIR(
        effect_id=f"effect:{tag}:remove",
        opcode="RemoveModifier",
        payload={
            "standard": {
                "modifier_name": parent_name,
                "target_alias": remove_target.alias,
                "target_expression_id": remove_target.target_expression_id,
            }
        },
        source=source,
        coverage_status="executable",
        owner_modifier_name=parent_name,
        source_mode="mainline",
    )
    return (
        (
            _definition(parent_name, source, additions=(child_effect_id,)),
            _definition(child_name, source),
        ),
        (parent_effect, child_effect, remove_effect),
        (parent_target, child_target, remove_target),
    )


def _birth_template() -> UnitBirthTemplateIR:
    source = _source("servant_birth")
    return UnitBirthTemplateIR(
        birth_template_id="birth:p8-r1:servant",
        spawn_kind="servant",
        entity_ref="servant:p8-r1",
        unit_field_specs={
            "side": "summon",
            "template_id": {"binding_kind": "request_field", "field": "entity_ref"},
            "level": 1,
            "max_hp": 100.0,
            "hp": 100.0,
            "attack": 10.0,
            "defense": 10.0,
            "speed": 100.0,
            "energy": 0.0,
            "max_energy": 0.0,
            "toughness": 0.0,
            "max_toughness": 0.0,
            "action_value": 100.0,
        },
        flag_specs={
            "owner_id": {"binding_kind": "request_field", "field": "owner_id"},
            "summoner_id": {"binding_kind": "request_field", "field": "summoner_id"},
            "summon_kind": "servant",
            "servant_definition_id": {
                "binding_kind": "request_field",
                "field": "source_id",
            },
            "servant_ref": {"binding_kind": "request_field", "field": "entity_ref"},
            "summon_intent_id": {
                "binding_kind": "request_field",
                "field": "source_id",
            },
            "summon_source_trace": {
                "binding_kind": "request_field",
                "field": "source_trace",
            },
            "servant_definition_source_trace": {
                "binding_kind": "request_field",
                "field": "entry_source_trace",
            },
            "team_side": "ally",
            "lifecycle_source": {
                "admission_status": "executable",
                "presence": "field",
                "targetable": True,
                "actionable": True,
                "timeline_admitted": True,
                "lifetime_policy": "permanent_until_removed",
                "source": source.to_json(),
            },
        },
        resource_specs={},
        request_contract={
            "spawn_kind": "servant",
            "entity_ref": "servant:p8-r1",
            "source_id": "servant-definition:p8-r1",
            "entry_id": "servant-entry:p8-r1",
            "owner_required": True,
            "summoner_matches_owner": True,
            "template_source_role": "entry",
        },
        source=source,
        coverage_status="executable",
    )


def _fixture(
    *,
    child_chance: float = 1.0,
    include_enemy_halo: bool = False,
) -> tuple[RuleBook, BattleState, dict[str, EffectIR]]:
    pair_a = _halo_pair("A", child_chance=child_chance)
    pair_b = _halo_pair(
        "B",
        alive_only=False,
        child_chance=child_chance,
    )
    pair_c = (
        _halo_pair(
            "C",
            child_chance=child_chance,
            child_alias="AllEnemyWithUnSelectable",
        )
        if include_enemy_halo
        else None
    )
    template = _birth_template()
    avatar_source = _source("owner")
    ir = CanonicalIR(
        version=VALIDATION_VERSION,
        entities=(
            RuleEntity(
                entity_id="avatar:p8-r1-owner",
                entity_type="avatar",
                fields={},
                source=avatar_source,
                coverage_status="lowered",
            ),
            *pair_a[0],
            *pair_b[0],
            *(pair_c[0] if pair_c is not None else ()),
        ),
        unit_birth_templates=(template,),
        status_event_families=(
            StatusEventFamilyIR(
                status_event_family_id="event-family:p8-r1:battle-setup",
                callback_event="OnEnterBattle",
                event_family="battle_setup",
                default_scope_kind="global_listener",
                runtime_event_sources=("battle.setup",),
                source_basis="validation_structured_event_family",
                source=_source("battle_setup_event_family"),
                coverage_status="executable",
                admission_status="executable",
            ),
            *(
                StatusEventFamilyIR(
                    status_event_family_id=(
                        "event-family:p8-r1:status-lifecycle:"
                        f"{callback_event}"
                    ),
                    callback_event=callback_event,
                    event_family="status_lifecycle",
                    default_scope_kind="owner_local",
                    runtime_event_sources=("status.lifecycle",),
                    source_basis=(
                        "validation_structured_status_lifecycle_family"
                    ),
                    source=_source(
                        f"status_lifecycle_{callback_event}"
                    ),
                    coverage_status="executable",
                    admission_status="executable",
                )
                for callback_event in (
                    "OnDestroy",
                    "OnModifierRemove",
                    "OnListenModifierRemove",
                    "OnCreate",
                    "OnStack",
                    "OnModifierAdd",
                    "OnAddModifierSuc",
                    "OnListenModifierAdd",
                )
            ),
        ),
        effects=(
            *pair_a[1],
            *pair_b[1],
            *(pair_c[1] if pair_c is not None else ()),
        ),
        target_expressions=(
            *pair_a[2],
            *pair_b[2],
            *(pair_c[2] if pair_c is not None else ()),
        ),
    )
    rules = RuleBook(ir)
    owner = UnitState(
        unit_id="ally:owner",
        side="ally",
        template_id="avatar:p8-r1-owner",
        max_hp=1000.0,
        hp=1000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        flags={},
    )
    other_owner = replace(owner, unit_id="ally:other-owner")
    state = BattleState(
        units={
            owner.unit_id: owner,
            other_owner.unit_id: other_owner,
        },
        global_flags={"summon_runtime": empty_summon_runtime()},
    )
    effects = {
        effect.effect_id: effect
        for effect in (
            *pair_a[1],
            *pair_b[1],
            *(pair_c[1] if pair_c is not None else ()),
        )
    }
    return rules, state, effects


def _reduce(
    state: BattleState,
    result: StatusApplicationResult,
) -> BattleState:
    if not result.ok:
        raise AssertionError(";".join(result.unsupported) or "status result blocked")
    reduction = MutationReducer().apply_all_result(state, result.mutations)
    if not reduction.ok:
        raise AssertionError(";".join(reduction.errors))
    return reduction.after_state


def _status_transition(
    state: BattleState,
    result: Any,
    action_id: str,
) -> BattleTransition:
    after = MutationReducer().apply_all(state, result.mutations)
    command = ActionCommand(
        actor_id="ally:owner",
        action_id=action_id,
        action_level=0,
    )
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=state.snapshot(),
            events=result.events,
            mutations=result.mutations,
            settlement=ActionSettlement(
                action_id=action_id,
                actor_id=command.actor_id,
                target_ids=(),
                records=result.records,
            ),
        ),
        after=after.snapshot(),
        target_resolution=TargetResolution(
            reason=action_id,
            source="p8_r1_validation",
        ),
        rng_events=tuple(getattr(result, "rng_events", ())),
        coverage={"validation": VALIDATION_VERSION},
    )


def _details(state: BattleState, unit_id: str) -> list[dict[str, JSONValue]]:
    raw = state.units[unit_id].flags.get("status_details")
    return [
        dict(item)
        for item in raw
        if isinstance(item, dict)
    ] if isinstance(raw, (list, tuple)) else []


def _details_named(
    state: BattleState,
    unit_id: str,
    name: str,
) -> list[dict[str, JSONValue]]:
    return [
        detail
        for detail in _details(state, unit_id)
        if detail.get("modifier_name") == name
    ]


def _detail_halo_relation_id(detail: dict[str, JSONValue]) -> str:
    source_trace = detail.get("source_trace")
    projection = (
        source_trace.get("halo_projection")
        if isinstance(source_trace, dict)
        else None
    )
    relation_id = (
        projection.get("relation_id")
        if isinstance(projection, dict)
        else None
    )
    return relation_id if isinstance(relation_id, str) else ""


def _spawn_plan(
    rules: RuleBook,
    state: BattleState,
    unit_id: str,
) -> SummonTransitionPlan:
    template = rules.unit_birth_template("birth:p8-r1:servant")
    if template is None:
        raise AssertionError("fixture birth template missing")
    source = template.source
    request = UnitSpawnRequest(
        spawn_kind="servant",
        unit_id=unit_id,
        birth_template_id=template.birth_template_id,
        entity_ref=template.entity_ref,
        source_id="servant-definition:p8-r1",
        entry_id="servant-entry:p8-r1",
        owner_id="ally:owner",
        summoner_id="ally:owner",
        source_trace=source.to_json(),
        entry_source_trace=source.to_json(),
    )
    spawn_plan = UnitSpawnSystem().plan(
        template,
        request,
        owner=state.units["ally:owner"],
    )
    if not spawn_plan.ok:
        raise AssertionError(spawn_plan.blocked_reason)
    return SummonTransitionPlan(
        ok=True,
        operation="servant_spawn",
        actor_id="ally:owner",
        owner_id="ally:owner",
        unit_ids=(unit_id,),
        intent_id="servant-definition:p8-r1",
        entry_ids=("servant-entry:p8-r1",),
        spawn_requests=(request,),
        source_trace=source.to_json(),
        metadata={
            "unit_spawn_plans": [spawn_plan.to_json()],
            "replacement_unit_ids": [],
            "replacement_policy": {},
        },
    )


def _apply_spawn(
    rules: RuleBook,
    state: BattleState,
    unit_id: str,
) -> tuple[BattleState, dict[str, JSONValue]]:
    result = SummonSystem(rules).apply_spawn_servant(
        state,
        _spawn_plan(rules, state, unit_id),
    )
    if not result.plan.ok:
        raise AssertionError(result.plan.blocked_reason)
    reduction = MutationReducer().apply_all_result(state, result.mutations)
    if not reduction.ok:
        raise AssertionError(";".join(reduction.errors))
    return reduction.after_state, {
        "mutation_count": len(result.mutations),
        "event_types": [event.event_type for event in result.events],
        "record_count": len(result.records),
        "mutation_paths": [list(mutation.path) for mutation in result.mutations],
    }


def _round_trip_state(state: BattleState) -> BattleState:
    payload = json.loads(
        json.dumps(
            {
                "units": {
                    unit_id: unit_state_to_payload(unit)
                    for unit_id, unit in state.units.items()
                },
                "global_flags": state.global_flags,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return replace(
        state,
        units={
            unit_id: unit_state_from_payload(unit)
            for unit_id, unit in payload["units"].items()
        },
        global_flags=payload["global_flags"],
    )


def _wave_halo_reconciliation_case() -> dict[str, JSONValue]:
    rules, initial_state, effects = _fixture(
        include_enemy_halo=True
    )
    source = _source("wave_halo_reconciliation")
    old_enemy = UnitState(
        unit_id="enemy:old-wave",
        side="enemy",
        template_id="monster:p8-r1-old-wave",
        max_hp=100.0,
        hp=100.0,
        attack=10.0,
        defense=10.0,
        speed=100.0,
        flags={},
    )
    state_with_old_enemy = replace(
        initial_state,
        units={
            **initial_state.units,
            old_enemy.unit_id: old_enemy,
        },
    )
    parent_result = StatusSystem(rules).apply_add_modifier(
        state_with_old_enemy,
        effects["effect:C:parent"],
        caster_id="ally:owner",
        owner_id="ally:owner",
        source_id="source:C",
        dynamic_values={"power": 5.0},
    )
    before_wave = _reduce(state_with_old_enemy, parent_result)
    new_enemy = replace(
        old_enemy,
        unit_id="enemy:new-wave",
        template_id="monster:p8-r1-new-wave",
        flags={},
    )
    lifecycle = UnitLifecycleSystem()
    remove_mutations = lifecycle.remove_mutations(
        before_wave,
        old_enemy.unit_id,
        reason="replace wave fixture enemy",
        source="wave_system",
        removed_record={
            "reason": "wave_transition",
            "unit_id": old_enemy.unit_id,
        },
        source_trace=source.to_json(),
    )
    spawn_mutation = lifecycle.spawn_mutation(
        before_wave,
        new_enemy,
        reason="spawn wave fixture enemy",
        source="wave_system",
        source_trace=source.to_json(),
    )
    wave_mutations = (*remove_mutations, spawn_mutation)
    plan = WaveTransitionPlan(
        ok=True,
        status="advance_to_next_wave",
        wave_definition_id="wave:p8-r1",
        current_wave_index=0,
        next_wave_index=1,
        cleared_unit_ids=(old_enemy.unit_id,),
        remove_unit_ids=(old_enemy.unit_id,),
        source_trace=source.to_json(),
    )
    records = tuple(
        SettlementRecord(
            record_type="wave_fixture_lifecycle",
            source="wave_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={"mutation_path": list(mutation.path)},
            trace=source.to_json(),
        ).to_json()
        for mutation in wave_mutations
    )

    class _FixtureWaveSystem:
        def plan_transition(
            self,
            state: BattleState,
        ) -> WaveTransitionPlan:
            return plan

        def apply_transition(
            self,
            state: BattleState,
            selected_plan: WaveTransitionPlan,
        ) -> WaveTransitionResult:
            return WaveTransitionResult(
                selected_plan,
                wave_mutations,
                (),
                records,
            )

    scheduler = CombatScheduler(rules)
    scheduler.wave = _FixtureWaveSystem()  # type: ignore[assignment]
    step = scheduler._try_wave_transition(before_wave)
    after_wave = step.after_state if step is not None else before_wave
    old_child_count = len(
        _details_named(
            after_wave,
            old_enemy.unit_id,
            "SharedHaloChild",
        )
    ) if old_enemy.unit_id in after_wave.units else 0
    new_child_count = (
        len(
            _details_named(
                after_wave,
                new_enemy.unit_id,
                "SharedHaloChild",
            )
        )
        if new_enemy.unit_id in after_wave.units
        else 0
    )
    transition = step.transition if step is not None else None
    mutation_ids = (
        {
            mutation.stable_id()
            for mutation in transition.transaction.mutations
        }
        if transition is not None
        else set()
    )
    settled_mutation_ids = (
        {
            str(record.get("mutation_id") or "")
            for record in transition.transaction.settlement.records
            if isinstance(record, dict)
            and record.get("process_only") is False
        }
        if transition is not None
        else set()
    )
    lifecycle_dispatch_record_count = (
        sum(
            1
            for record in transition.transaction.settlement.records
            if isinstance(record, dict)
            and record.get("record_type") == "event_dispatch"
            and isinstance(record.get("payload"), dict)
            and isinstance(record["payload"].get("event"), dict)
            and record["payload"]["event"].get("event_type")
            == "status.lifecycle"
        )
        if transition is not None
        else 0
    )
    lifecycle_events = (
        tuple(
            event
            for event in transition.transaction.events
            if event.event_type == "status.lifecycle"
        )
        if transition is not None
        else ()
    )
    lifecycle_event_ids = tuple(
        event.event_id for event in lifecycle_events
    )
    replay = (
        MutationReducer().replay_snapshot(
            before_wave,
            transition.transaction.mutations,
            transition.after.to_json(),
        )
        if transition is not None
        else None
    )
    checks = {
        "wave_transition_committed": bool(
            transition is not None
            and transition.outcome.successor_eligible
        ),
        "old_wave_member_projection_removed": old_child_count == 0,
        "new_wave_member_projection_added": new_child_count == 1,
        "halo_lifecycle_events_dispatched": bool(
            transition is not None
            and any(
                event.event_type == "status.lifecycle"
                for event in transition.transaction.events
            )
            and any(
                node.node_kind == "event_dispatch"
                for node in transition.outcome.node_results
            )
        ),
        "wave_halo_transition_replay_equal": bool(
            replay is not None and replay.ok
        ),
        "wave_halo_mutations_all_settled": bool(
            mutation_ids
            and mutation_ids.issubset(settled_mutation_ids)
        ),
        "wave_halo_lifecycle_dispatch_records_present": (
            lifecycle_dispatch_record_count > 0
        ),
        "wave_halo_lifecycle_event_identities_unique": (
            bool(lifecycle_event_ids)
            and len(lifecycle_event_ids) == len(set(lifecycle_event_ids))
        ),
        "wave_halo_lifecycle_event_count_matches_dispatch_count": (
            len(lifecycle_events) == lifecycle_dispatch_record_count
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "old_child_count": old_child_count,
        "new_child_count": new_child_count,
        "mutation_count": (
            len(transition.transaction.mutations)
            if transition is not None
            else 0
        ),
        "event_types": (
            [
                event.event_type
                for event in transition.transaction.events
            ]
            if transition is not None
            else []
        ),
        "lifecycle_dispatch_record_count": (
            lifecycle_dispatch_record_count
        ),
        "lifecycle_event_count": len(lifecycle_events),
        "lifecycle_event_ids": list(lifecycle_event_ids),
        "outcome": (
            transition.outcome.to_json()
            if transition is not None
            else None
        ),
        "replay": (
            {
                "ok": replay.ok,
                "errors": list(replay.errors),
                "conflicts": [
                    conflict.to_json()
                    for conflict in replay.conflicts
                ],
            }
            if replay is not None
            else None
        ),
    }


def _runtime_validation() -> dict[str, JSONValue]:
    rules, initial_state, effects = _fixture()
    status = StatusSystem(rules)
    target = TargetSystem()
    canonical = empty_summon_runtime()
    wave_halo_case = _wave_halo_reconciliation_case()

    scenario = ScenarioSpec(
        scenario_id="p8-r1-initialization",
        version=VALIDATION_VERSION,
        units=(
            UnitSpec(
                unit_id="ally:fixture",
                side="ally",
                build_mode="kernel_fixture",
                entity_ref="avatar:p8-r1-owner",
                level=1,
                panel=PanelInput(
                    explicit_fields=(
                        "max_hp",
                        "hp",
                        "attack",
                        "defense",
                        "speed",
                        "energy",
                        "max_energy",
                    ),
                    max_hp=100.0,
                    hp=100.0,
                    attack=10.0,
                    defense=10.0,
                    speed=100.0,
                    energy=0.0,
                    max_energy=0.0,
                ),
            ),
        ),
        route=(),
    )
    built = ScenarioStateBuilder(rules).build(scenario)
    setup_types = [
        str(record.get("record_type") or "")
        for record in built.setup_records
        if isinstance(record, dict)
    ]
    built_runtime = built.state.global_flags.get("summon_runtime")

    servant_expression = rules.target_expression("target:A:servant")
    if servant_expression is None:
        raise AssertionError("servant target expression missing")
    empty_target = target.resolve_target_expression(
        initial_state,
        servant_expression,
        caster_id="ally:owner",
        owner_id="ally:owner",
    )
    required_action_targets = target.enumerate_action_targets(
        initial_state,
        "ally:owner",
        TargetPolicy(
            policy_id="p8_r1_required_single_enemy",
            allow_enemy=True,
            allow_ally=False,
            allow_self=False,
            target_relation="enemy",
            selection_min=1,
            selection_max=1,
        ),
    )
    missing_state = replace(initial_state, global_flags={})
    missing_target = target.resolve_target_expression(
        missing_state,
        servant_expression,
        caster_id="ally:owner",
        owner_id="ally:owner",
    )
    malformed_runtime = thaw_json(canonical)
    malformed_runtime["by_owner"] = []
    malformed_state = replace(
        initial_state,
        global_flags={"summon_runtime": malformed_runtime},
    )
    malformed_target = target.resolve_target_expression(
        malformed_state,
        servant_expression,
        caster_id="ally:owner",
        owner_id="ally:owner",
    )

    condition = ConditionIR(
        condition_id="condition:p8-r1:empty-intersection",
        opcode="ByTargetListIntersects",
        payload={
            "FirstTargetType": {"alias": "CasterServant"},
            "SecondTargetType": {"alias": "SkillTargetEntityList"},
        },
        source=_source("empty_condition"),
        coverage_status="executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )
    condition_result = RuleEvaluator().evaluate_condition_result(
        condition,
        EvaluationContext(
            state=initial_state,
            actor_id="ally:owner",
            resolved_target_groups={
                "alias:CasterServant": (),
                "alias:SkillTargetEntityList": ("ally:owner",),
            },
        ),
    )

    empty_parent_result = status.apply_add_modifier(
        initial_state,
        effects["effect:A:parent"],
        caster_id="ally:owner",
        owner_id="ally:owner",
        source_id="source:A",
        dynamic_values={"power": 2.0},
    )
    state = _reduce(initial_state, empty_parent_result)
    empty_group_records = [
        record
        for record in empty_parent_result.records
        if isinstance(record, dict)
        and record.get("record_type") == "status_halo_empty_group"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("state_unchanged") is True
    ]
    parent_a = _details_named(state, "ally:owner", "ParentA")
    empty_relation = (
        parent_a[0].get("halo_relations", [])
        if len(parent_a) == 1
        else []
    )

    state, spawn_one = _apply_spawn(rules, state, "servant:one")
    state_after_spawn_one = state
    child_one = _details_named(state, "servant:one", "SharedHaloChild")
    child_one_power = (
        child_one[0].get("dynamic_values", {}).get("power")
        if len(child_one) == 1
        and isinstance(child_one[0].get("dynamic_values"), dict)
        else None
    )
    runtime_after_spawn = state.global_flags.get("summon_runtime")
    target_after_spawn = target.resolve_target_expression(
        state,
        servant_expression,
        caster_id="ally:owner",
        owner_id="ally:owner",
    )
    idempotent = status.reconcile_halo_relations(state)

    update_before = state
    update = status.apply_add_modifier(
        state,
        effects["effect:A:parent"],
        caster_id="ally:owner",
        owner_id="ally:owner",
        source_id="source:A",
        dynamic_values={"power": 3.0},
    )
    audit_transition = _status_transition(
        update_before,
        update,
        "p8-r1:halo-parent-refresh",
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(
        audit_transition
    )
    replay = MutationReducer().replay_snapshot(
        update_before,
        update.mutations,
        audit_transition.after.to_json(),
    )
    tampered_mutations = list(update.mutations)
    tampered_after = json.loads(
        json.dumps(tampered_mutations[-1].after)
    )
    if isinstance(tampered_after, list):
        for detail in tampered_after:
            if not isinstance(detail, dict):
                continue
            relations = detail.get("halo_relations")
            if isinstance(relations, list) and relations:
                relations[0]["source_raw_id"] = "forged-replay-source"
                break
    tampered_mutations[-1] = replace(
        tampered_mutations[-1],
        after=tampered_after,
    )
    tampered_replay = MutationReducer().replay_snapshot(
        update_before,
        tuple(tampered_mutations),
        audit_transition.after.to_json(),
    )
    state = _reduce(state, update)
    updated_child = _details_named(state, "servant:one", "SharedHaloChild")
    updated_power = (
        updated_child[0].get("dynamic_values", {}).get("power")
        if len(updated_child) == 1
        and isinstance(updated_child[0].get("dynamic_values"), dict)
        else None
    )
    state, spawn_two = _apply_spawn(rules, state, "servant:two")
    late_child = _details_named(state, "servant:two", "SharedHaloChild")
    late_power = (
        late_child[0].get("dynamic_values", {}).get("power")
        if len(late_child) == 1
        and isinstance(late_child[0].get("dynamic_values"), dict)
        else None
    )

    defeated_unit = replace(
        state.units["servant:one"],
        hp=0.0,
        lifecycle_status="defeated",
        flags={
            **state.units["servant:one"].flags,
            "defeat_record": {"reason": "halo_lifecycle_fixture"},
        },
    )
    defeated_state = replace(
        state,
        units={**state.units, "servant:one": defeated_unit},
    )
    defeated_result = status.reconcile_halo_relations(defeated_state)
    defeated_after = _reduce(defeated_state, defeated_result)
    defeated_child_count = len(
        _details_named(defeated_after, "servant:one", "SharedHaloChild")
    )
    revived_unit = replace(
        defeated_after.units["servant:one"],
        hp=100.0,
        lifecycle_status="active",
        flags={
            key: value
            for key, value in defeated_after.units["servant:one"].flags.items()
            if key != "defeat_record"
        },
    )
    revived_state = replace(
        defeated_after,
        units={**defeated_after.units, "servant:one": revived_unit},
    )
    revived_result = status.reconcile_halo_relations(revived_state)
    state = _reduce(revived_state, revived_result)
    revived_child_count = len(
        _details_named(state, "servant:one", "SharedHaloChild")
    )

    state = _reduce(
        state,
        status.apply_add_modifier(
            state,
            effects["effect:B:parent"],
            caster_id="ally:owner",
            owner_id="ally:owner",
            source_id="source:B",
            dynamic_values={"power": 4.0},
        ),
    )
    two_source_child_count = len(
        _details_named(state, "servant:two", "SharedHaloChild")
    )
    servant_two_defeated = replace(
        state.units["servant:two"],
        hp=0.0,
        lifecycle_status="defeated",
        flags={
            **state.units["servant:two"].flags,
            "defeat_record": {"reason": "alive_only_halo_fixture"},
        },
    )
    alive_policy_before = replace(
        state,
        units={**state.units, "servant:two": servant_two_defeated},
    )
    alive_policy_result = status.reconcile_halo_relations(
        alive_policy_before
    )
    alive_policy_after = _reduce(
        alive_policy_before,
        alive_policy_result,
    )
    defeated_two_children = _details_named(
        alive_policy_after,
        "servant:two",
        "SharedHaloChild",
    )
    defeated_two_relation_ids = {
        _detail_halo_relation_id(detail)
        for detail in defeated_two_children
    }

    moved_runtime = thaw_json(
        alive_policy_after.global_flags.get("summon_runtime")
    )
    assert isinstance(moved_runtime, dict)
    moved_runtime["entities"]["servant:two"]["owner_id"] = (
        "ally:other-owner"
    )
    moved_runtime["servants"]["servant:two"]["owner_id"] = (
        "ally:other-owner"
    )
    moved_runtime["by_owner"]["ally:owner"].remove("servant:two")
    moved_runtime["by_owner"]["ally:other-owner"] = ["servant:two"]
    moved_unit = replace(
        alive_policy_after.units["servant:two"],
        flags={
            **alive_policy_after.units["servant:two"].flags,
            "owner_id": "ally:other-owner",
        },
    )
    moved_state = replace(
        alive_policy_after,
        units={**alive_policy_after.units, "servant:two": moved_unit},
        global_flags={
            **alive_policy_after.global_flags,
            "summon_runtime": moved_runtime,
        },
    )
    moved_relation_result = status.reconcile_halo_relations(moved_state)
    moved_relation_after = _reduce(
        moved_state,
        moved_relation_result,
    )
    moved_relation_child_count = len(
        _details_named(
            moved_relation_after,
            "servant:two",
            "SharedHaloChild",
        )
    )

    servant_two_revived = replace(
        alive_policy_after.units["servant:two"],
        hp=100.0,
        lifecycle_status="active",
        flags={
            key: value
            for key, value in alive_policy_after.units["servant:two"].flags.items()
            if key != "defeat_record"
        },
    )
    alive_policy_revived = replace(
        alive_policy_after,
        units={
            **alive_policy_after.units,
            "servant:two": servant_two_revived,
        },
    )
    state = _reduce(
        alive_policy_revived,
        status.reconcile_halo_relations(alive_policy_revived),
    )
    integrity_base_state = state
    parent_a_details = _details_named(
        integrity_base_state,
        "ally:owner",
        "ParentA",
    )
    parent_a_relations = (
        parent_a_details[0].get("halo_relations", [])
        if len(parent_a_details) == 1
        else []
    )
    parent_a_relation_id = (
        str(parent_a_relations[0].get("relation_id") or "")
        if isinstance(parent_a_relations, list)
        and len(parent_a_relations) == 1
        and isinstance(parent_a_relations[0], dict)
        else ""
    )
    missing_child_details = [
        detail
        for detail in _details(integrity_base_state, "servant:one")
        if _detail_halo_relation_id(detail) != parent_a_relation_id
    ]
    missing_child_unit = replace(
        integrity_base_state.units["servant:one"],
        flags={
            **integrity_base_state.units["servant:one"].flags,
            "status_details": missing_child_details,
        },
    )
    missing_child_state = replace(
        integrity_base_state,
        units={
            **integrity_base_state.units,
            "servant:one": missing_child_unit,
        },
    )
    missing_child_result = status.reconcile_halo_relations(
        missing_child_state
    )
    missing_child_after = (
        _reduce(missing_child_state, missing_child_result)
        if missing_child_result.ok
        else missing_child_state
    )
    restored_child_count = sum(
        1
        for detail in _details(missing_child_after, "servant:one")
        if _detail_halo_relation_id(detail) == parent_a_relation_id
    )

    duplicate_child_details = _details(
        integrity_base_state,
        "servant:one",
    )
    duplicate_candidate = next(
        (
            thaw_json(detail)
            for detail in duplicate_child_details
            if _detail_halo_relation_id(detail) == parent_a_relation_id
        ),
        None,
    )
    duplicate_child_state = integrity_base_state
    if duplicate_candidate is not None:
        duplicate_child_state = replace(
            integrity_base_state,
            units={
                **integrity_base_state.units,
                "servant:one": replace(
                    integrity_base_state.units["servant:one"],
                    flags={
                        **integrity_base_state.units[
                            "servant:one"
                        ].flags,
                        "status_details": [
                            *duplicate_child_details,
                            duplicate_candidate,
                        ],
                    },
                ),
            },
        )
    duplicate_child_result = status.reconcile_halo_relations(
        duplicate_child_state
    )

    forged_evidence_details = thaw_json(
        _details(integrity_base_state, "ally:owner")
    )
    for detail in forged_evidence_details:
        if detail.get("modifier_name") != "ParentA":
            continue
        relations = detail.get("halo_relations")
        if not isinstance(relations, list) or not relations:
            continue
        source = relations[0].get("source")
        evidence = (
            source.get("evidence")
            if isinstance(source, dict)
            else None
        )
        if isinstance(evidence, dict):
            evidence["json_path"] = "$.forged.record.position"
        break
    forged_evidence_state = replace(
        integrity_base_state,
        units={
            **integrity_base_state.units,
            "ally:owner": replace(
                integrity_base_state.units["ally:owner"],
                flags={
                    **integrity_base_state.units["ally:owner"].flags,
                    "status_details": forged_evidence_details,
                },
            ),
        },
    )
    forged_evidence_result = status.reconcile_halo_relations(
        forged_evidence_state
    )

    removed_parent = replace(
        integrity_base_state.units["ally:owner"],
        lifecycle_status="removed",
        flags={
            **integrity_base_state.units["ally:owner"].flags,
            "removed_record": {"reason": "halo_parent_fixture"},
        },
    )
    removed_parent_state = replace(
        integrity_base_state,
        units={
            **integrity_base_state.units,
            "ally:owner": removed_parent,
        },
    )
    removed_parent_result = status.reconcile_halo_relations(
        removed_parent_state
    )
    removed_parent_after = (
        _reduce(removed_parent_state, removed_parent_result)
        if removed_parent_result.ok
        else removed_parent_state
    )
    removed_parent_child_count = sum(
        1
        for unit_id in ("servant:one", "servant:two")
        for detail in _details(removed_parent_after, unit_id)
        if _detail_halo_relation_id(detail)
    )

    atomic_update_details = thaw_json(_details(state, "ally:owner"))
    for detail in atomic_update_details:
        if detail.get("modifier_name") == "ParentA":
            detail["dynamic_values"] = {
                **dict(detail.get("dynamic_values") or {}),
                "power": 7.0,
            }
    atomic_update_owner = state.units["ally:owner"]
    atomic_update_state = replace(
        state,
        units={
            **state.units,
            "ally:owner": replace(
                atomic_update_owner,
                flags={
                    **atomic_update_owner.flags,
                    "status_details": atomic_update_details,
                },
            ),
        },
    )
    atomic_update_success = status.reconcile_halo_relations(
        atomic_update_state
    )
    atomic_failure_details = thaw_json(atomic_update_details)
    for detail in atomic_failure_details:
        if detail.get("modifier_name") != "ParentB":
            continue
        relations = detail.get("halo_relations")
        if isinstance(relations, list) and relations:
            relations[0]["source_raw_type"] = "ForgedSourceType"
            source = relations[0].get("source")
            if isinstance(source, dict):
                source["raw_type"] = "ForgedSourceType"
            break
    atomic_failure_owner = atomic_update_state.units["ally:owner"]
    atomic_failure_state = replace(
        atomic_update_state,
        units={
            **atomic_update_state.units,
            "ally:owner": replace(
                atomic_failure_owner,
                flags={
                    **atomic_failure_owner.flags,
                    "status_details": atomic_failure_details,
                },
            ),
        },
    )
    atomic_failure = status.reconcile_halo_relations(
        atomic_failure_state
    )
    state = _reduce(
        state,
        status.apply_remove_modifier(
            state,
            effects["effect:A:remove"],
            caster_id="ally:owner",
            owner_id="ally:owner",
            source_id="source:A",
        ),
    )
    after_remove_child = _details_named(
        state,
        "servant:two",
        "SharedHaloChild",
    )
    after_remove_parent_a = _details_named(state, "ally:owner", "ParentA")
    after_remove_parent_b = _details_named(state, "ally:owner", "ParentB")

    round_tripped = _round_trip_state(state)
    round_trip_reconcile = status.reconcile_halo_relations(round_tripped)

    corrupt = thaw_json(round_tripped.global_flags)
    corrupt_units = dict(round_tripped.units)
    owner_flags = dict(corrupt_units["ally:owner"].flags)
    owner_details = thaw_json(_details(round_tripped, "ally:owner"))
    for detail in owner_details:
        relations = detail.get("halo_relations")
        if isinstance(relations, list) and relations:
            relations[0]["source_raw_id"] = "forged"
            break
    owner_flags["status_details"] = owner_details
    corrupt_units["ally:owner"] = replace(
        corrupt_units["ally:owner"],
        flags=owner_flags,
    )
    corrupt_state = replace(
        round_tripped,
        units=corrupt_units,
        global_flags=corrupt,
    )
    failed_reconcile = status.reconcile_halo_relations(corrupt_state)
    failed_spawn = SummonSystem(rules).apply_spawn_servant(
        corrupt_state,
        _spawn_plan(rules, corrupt_state, "servant:failed"),
    )

    bad_runtime_rows: list[dict[str, JSONValue]] = []
    for label, mutate in (
        ("wrong_schema", lambda raw: raw.__setitem__("schema_version", "wrong")),
        ("bad_owner_index", lambda raw: raw.__setitem__("by_owner", [])),
    ):
        raw = thaw_json(canonical)
        mutate(raw)
        validation = validate_summon_runtime(raw, units=initial_state.units)
        bad_runtime_rows.append(
            {"case": label, "ok": validation.ok, "reason": validation.reason}
        )
    contradictory_runtime = thaw_json(runtime_after_spawn)
    assert isinstance(contradictory_runtime, dict)
    contradictory_runtime["by_owner"]["ally:owner"] = []
    contradictory_validation = validate_summon_runtime(
        contradictory_runtime,
        units=state_after_spawn_one.units,
    )
    bad_runtime_rows.append(
        {
            "case": "active_entity_missing_from_owner_index",
            "ok": contradictory_validation.ok,
            "reason": contradictory_validation.reason,
        }
    )
    removed_runtime_unit = replace(
        state_after_spawn_one.units["servant:one"],
        lifecycle_status="removed",
        flags={
            **state.units["servant:one"].flags,
            "removed_record": {"reason": "summon_runtime_fixture"},
        },
    )
    removed_runtime_validation = validate_summon_runtime(
        runtime_after_spawn,
        units={
            **state_after_spawn_one.units,
            "servant:one": removed_runtime_unit,
        },
    )
    bad_runtime_rows.append(
        {
            "case": "active_runtime_entity_points_to_removed_unit",
            "ok": removed_runtime_validation.ok,
            "reason": removed_runtime_validation.reason,
        }
    )
    ownerless_runtime = thaw_json(runtime_after_spawn)
    assert isinstance(ownerless_runtime, dict)
    ownerless_runtime["entities"]["servant:one"]["owner_id"] = ""
    ownerless_validation = validate_summon_runtime(
        ownerless_runtime,
        units=state_after_spawn_one.units,
    )
    bad_runtime_rows.append(
        {
            "case": "active_runtime_entity_owner_empty",
            "ok": ownerless_validation.ok,
            "reason": ownerless_validation.reason,
        }
    )
    wrong_kind_unit = replace(
        state_after_spawn_one.units["servant:one"],
        flags={
            **state.units["servant:one"].flags,
            "summon_kind": "summoned_monster",
        },
    )
    wrong_kind_validation = validate_summon_runtime(
        runtime_after_spawn,
        units={
            **state_after_spawn_one.units,
            "servant:one": wrong_kind_unit,
        },
    )
    bad_runtime_rows.append(
        {
            "case": "runtime_entity_unit_kind_mismatch",
            "ok": wrong_kind_validation.ok,
            "reason": wrong_kind_validation.reason,
        }
    )
    missing_servant_index = thaw_json(runtime_after_spawn)
    assert isinstance(missing_servant_index, dict)
    missing_servant_index["servants"].pop("servant:one")
    missing_servant_validation = validate_summon_runtime(
        missing_servant_index,
        units=state_after_spawn_one.units,
    )
    bad_runtime_rows.append(
        {
            "case": "servant_entity_missing_from_servant_index",
            "ok": missing_servant_validation.ok,
            "reason": missing_servant_validation.reason,
        }
    )
    rng_rules, rng_initial_state, rng_effects = _fixture(
        child_chance=0.5
    )
    rng_parent_result = StatusSystem(rng_rules).apply_add_modifier(
        rng_initial_state,
        rng_effects["effect:A:parent"],
        caster_id="ally:owner",
        owner_id="ally:owner",
        source_id="source:A",
        dynamic_values={"power": 2.0},
    )
    rng_parent_state = _reduce(
        rng_initial_state,
        rng_parent_result,
    )
    rng_spawn_result = SummonSystem(rng_rules).apply_spawn_servant(
        rng_parent_state,
        _spawn_plan(
            rng_rules,
            rng_parent_state,
            "servant:rng-channel",
        ),
    )
    inactive_registry = thaw_json(runtime_after_spawn)
    assert isinstance(inactive_registry, dict)
    inactive_registry["entities"]["servant:one"]["status"] = "removed"
    inactive_registry["servants"]["servant:one"]["status"] = "removed"
    inactive_registry["by_owner"]["ally:owner"].remove("servant:one")
    inactive_registry_validation = validate_summon_runtime(
        inactive_registry,
        units=state_after_spawn_one.units,
    )
    bad_runtime_rows.append(
        {
            "case": "active_unit_has_inactive_runtime_entity",
            "ok": inactive_registry_validation.ok,
            "reason": inactive_registry_validation.reason,
        }
    )
    owner_missing_validation = validate_summon_runtime(
        runtime_after_spawn,
        units={
            unit_id: unit
            for unit_id, unit in state_after_spawn_one.units.items()
            if unit_id != "ally:owner"
        },
    )
    bad_runtime_rows.append(
        {
            "case": "active_entity_owner_unit_missing",
            "ok": owner_missing_validation.ok,
            "reason": owner_missing_validation.reason,
        }
    )
    jointly_forged_owner_runtime = thaw_json(runtime_after_spawn)
    jointly_forged_owner_runtime["entities"]["servant:one"][
        "owner_id"
    ] = "ally:forged-owner"
    jointly_forged_owner_runtime["servants"]["servant:one"][
        "owner_id"
    ] = "ally:forged-owner"
    jointly_forged_owner_runtime["by_owner"].pop("ally:owner")
    jointly_forged_owner_runtime["by_owner"][
        "ally:forged-owner"
    ] = ["servant:one"]
    jointly_forged_owner_unit = replace(
        state_after_spawn_one.units["servant:one"],
        flags={
            **state_after_spawn_one.units["servant:one"].flags,
            "owner_id": "ally:forged-owner",
        },
    )
    jointly_forged_owner_validation = validate_summon_runtime(
        jointly_forged_owner_runtime,
        units={
            **state_after_spawn_one.units,
            "servant:one": jointly_forged_owner_unit,
        },
    )
    bad_runtime_rows.append(
        {
            "case": "runtime_and_unit_owner_simultaneously_forged",
            "ok": jointly_forged_owner_validation.ok,
            "reason": jointly_forged_owner_validation.reason,
        }
    )
    summoner_mismatch_runtime = thaw_json(runtime_after_spawn)
    summoner_mismatch_runtime["entities"]["servant:one"][
        "summoner_id"
    ] = "ally:forged-summoner"
    summoner_mismatch_runtime["servants"]["servant:one"][
        "summoner_id"
    ] = "ally:forged-summoner"
    summoner_mismatch_validation = validate_summon_runtime(
        summoner_mismatch_runtime,
        units=state_after_spawn_one.units,
    )
    bad_runtime_rows.append(
        {
            "case": "runtime_unit_summoner_mismatch",
            "ok": summoner_mismatch_validation.ok,
            "reason": summoner_mismatch_validation.reason,
        }
    )
    missing_summoner_runtime = thaw_json(runtime_after_spawn)
    missing_summoner_runtime["entities"]["servant:one"][
        "summoner_id"
    ] = "ally:missing-summoner"
    missing_summoner_runtime["servants"]["servant:one"][
        "summoner_id"
    ] = "ally:missing-summoner"
    missing_summoner_unit = replace(
        state_after_spawn_one.units["servant:one"],
        flags={
            **state_after_spawn_one.units["servant:one"].flags,
            "summoner_id": "ally:missing-summoner",
        },
    )
    missing_summoner_validation = validate_summon_runtime(
        missing_summoner_runtime,
        units={
            **state_after_spawn_one.units,
            "servant:one": missing_summoner_unit,
        },
    )
    bad_runtime_rows.append(
        {
            "case": "active_entity_summoner_unit_missing",
            "ok": missing_summoner_validation.ok,
            "reason": missing_summoner_validation.reason,
        }
    )
    forged_team_runtime = thaw_json(runtime_after_spawn)
    forged_team_runtime["entities"]["servant:one"][
        "team_side"
    ] = "enemy"
    forged_team_runtime["servants"]["servant:one"][
        "team_side"
    ] = "enemy"
    forged_team_unit = replace(
        state_after_spawn_one.units["servant:one"],
        flags={
            **state_after_spawn_one.units["servant:one"].flags,
            "team_side": "enemy",
        },
    )
    forged_team_validation = validate_summon_runtime(
        forged_team_runtime,
        units={
            **state_after_spawn_one.units,
            "servant:one": forged_team_unit,
        },
    )
    bad_runtime_rows.append(
        {
            "case": "runtime_and_unit_team_side_simultaneously_forged",
            "ok": forged_team_validation.ok,
            "reason": forged_team_validation.reason,
        }
    )
    required_relationship_negative_cases = {
        "active_entity_owner_unit_missing",
        "runtime_and_unit_owner_simultaneously_forged",
        "runtime_unit_summoner_mismatch",
        "active_entity_summoner_unit_missing",
        "runtime_and_unit_team_side_simultaneously_forged",
    }
    relationship_negative_rows = {
        str(row["case"]): row for row in bad_runtime_rows
    }

    checks: dict[str, bool] = {
        "formal_state_has_canonical_empty_summon_runtime": (
            built_runtime == canonical
            and validate_summon_runtime(
                built_runtime,
                units=built.state.units,
            ).ok
        ),
        "summon_runtime_initialized_before_provider_and_setup_events": (
            "setup_summon_runtime" in setup_types
            and (
                "ability_provider_registered" not in setup_types
                or setup_types.index("setup_summon_runtime")
                < setup_types.index("ability_provider_registered")
            )
        ),
        "missing_or_malformed_summon_runtime_blocked": (
            not missing_target.ok
            and not malformed_target.ok
            and all(not row["ok"] for row in bad_runtime_rows)
        ),
        "summon_runtime_active_registry_is_bidirectional": (
            not inactive_registry_validation.ok
            and inactive_registry_validation.reason
            == "summon_runtime_active_unit_entity_not_active"
        ),
        "summon_runtime_relationship_identity_is_bidirectional": (
            required_relationship_negative_cases.issubset(
                relationship_negative_rows
            )
            and all(
                relationship_negative_rows[case]["ok"] is False
                for case in required_relationship_negative_cases
            )
            and owner_missing_validation.reason
            == "summon_runtime_active_entity_owner_unit_missing"
            and jointly_forged_owner_validation.reason
            == "summon_runtime_active_entity_owner_unit_missing"
            and summoner_mismatch_validation.reason
            == "summon_runtime_entity_unit_summoner_mismatch"
            and missing_summoner_validation.reason
            == "summon_runtime_active_entity_summoner_unit_missing"
            and forged_team_validation.reason
            == "summon_runtime_entity_owner_combat_team_mismatch"
        ),
        "summon_halo_rng_channel_is_not_dropped": (
            rng_spawn_result.plan.ok
            and len(rng_spawn_result.rng_events) == 1
            and rng_spawn_result.rng_events[0].rng_type
            == "status_apply"
        ),
        "wave_transition_reconciles_and_dispatches_halo_lifecycle": (
            wave_halo_case["ok"] is True
        ),
        "valid_empty_servant_group_resolved": (
            empty_target.ok and empty_target.target_ids == ()
        ),
        "resolved_empty_condition_evaluates_false": (
            condition_result.ok and condition_result.result is False
        ),
        "resolved_empty_group_effect_is_audited_no_effect": (
            len(empty_relation) == 1
            and empty_relation[0].get("current_member_ids") == []
            and len(empty_group_records) == 1
        ),
        "required_action_with_empty_target_group_unavailable": (
            empty_target.ok
            and not empty_target.target_ids
            and not required_action_targets.ok
            and required_action_targets.blocked_reason
            == "target_candidates_empty"
        ),
        "halo_relation_persists_without_current_member": (
            len(empty_relation) == 1
        ),
        "spawn_event_observes_registered_owner_relation": (
            validate_summon_runtime(
                runtime_after_spawn,
                units=state_after_spawn_one.units,
            ).ok
            and target_after_spawn.ok
            and target_after_spawn.target_ids == ("servant:one",)
            and spawn_one["event_types"][-1:] == ["summon.spawned"]
        ),
        "late_spawn_receives_active_halo": len(late_child) == 1,
        "late_spawn_uses_current_parent_stack_and_values": (
            child_one_power == 2.0
            and updated_power == 3.0
            and late_power == 3.0
        ),
        "halo_reconciliation_idempotent": (
            idempotent.ok and len(idempotent.mutations) == 0
        ),
        "missing_halo_child_is_restored_from_canonical_relation": (
            missing_child_result.ok
            and bool(missing_child_result.mutations)
            and restored_child_count == 1
        ),
        "duplicate_halo_child_projection_is_blocked": (
            not duplicate_child_result.ok
            and not duplicate_child_result.mutations
            and "halo_projection_identity_duplicate"
            in duplicate_child_result.unsupported
        ),
        "halo_relation_full_source_evidence_is_verified": (
            not forged_evidence_result.ok
            and not forged_evidence_result.mutations
            and "halo_child_source_binding_mismatch"
            in forged_evidence_result.unsupported
        ),
        "removed_halo_source_cleans_all_children": (
            removed_parent_result.ok
            and bool(removed_parent_result.mutations)
            and removed_parent_child_count == 0
        ),
        "ineligible_member_does_not_retain_halo_child": (
            defeated_child_count == 0
        ),
        "reeligible_member_is_reconciled": revived_child_count == 1,
        "parent_removal_cleans_halo_children": (
            not after_remove_parent_a
            and len(after_remove_parent_b) == 1
            and len(after_remove_child) == 1
        ),
        "same_named_independent_status_preserved": (
            two_source_child_count == 2
            and len(after_remove_child) == 1
        ),
        "multiple_halo_sources_isolated": (
            two_source_child_count == 2
            and len(after_remove_child) == 1
        ),
        "alive_only_false_retains_defeated_related_member": (
            len(defeated_two_children) == 1
            and any(
                relation_id.startswith("halo_relation:")
                for relation_id in defeated_two_relation_ids
            )
        ),
        "owner_relation_change_removes_non_alive_halo_member": (
            moved_relation_child_count == 0
        ),
        "failed_reconciliation_state_unchanged": (
            not failed_reconcile.ok
            and not failed_reconcile.mutations
            and all(
                record.get("process_only") is True
                for record in failed_reconcile.records
            )
            and not failed_spawn.plan.ok
            and not failed_spawn.mutations
            and not failed_spawn.events
            and all(
                record.get("process_only") is True
                for record in failed_spawn.records
            )
            and bool(atomic_update_success.mutations)
            and not atomic_failure.ok
            and not atomic_failure.mutations
            and not atomic_failure.events
            and not atomic_failure.rng_events
            and all(
                record.get("process_only") is True
                for record in atomic_failure.records
            )
        ),
        "snapshot_round_trip_preserves_halo_semantics": (
            validate_summon_runtime(
                round_tripped.global_flags.get("summon_runtime"),
                units=round_tripped.units,
            ).ok
            and round_trip_reconcile.ok
            and not round_trip_reconcile.mutations
        ),
        "sampled_halo_mutations_source_audited": (
            source_audit.ok
            and source_audit.checked_mutations == len(update.mutations)
        ),
        "sampled_halo_transitions_replay_equal": replay.ok,
        "tampered_halo_relation_replay_rejected": (
            not tampered_replay.ok
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "initialization_order": {
            "setup_record_types": setup_types,
            "summon_runtime_schema_version": (
                built_runtime.get("schema_version")
                if isinstance(built_runtime, dict)
                else None
            ),
        },
        "target_consumers": {
            "resolved_empty": empty_target.to_json(),
            "missing_runtime": missing_target.to_json(),
            "malformed_runtime": malformed_target.to_json(),
            "empty_condition": condition_result.to_json(),
            "required_action_empty_enumeration": (
                required_action_targets.to_json()
            ),
        },
        "lifecycle": {
            "empty_relation": empty_relation,
            "empty_group_records": empty_group_records,
            "spawn_one": spawn_one,
            "spawn_two": spawn_two,
            "child_dynamic_values": {
                "initial": child_one_power,
                "updated": updated_power,
                "late_spawn": late_power,
            },
            "defeated_child_count": defeated_child_count,
            "revived_child_count": revived_child_count,
            "two_source_child_count": two_source_child_count,
            "defeated_two_child_count": len(defeated_two_children),
            "defeated_two_relation_ids": sorted(
                defeated_two_relation_ids
            ),
            "moved_relation_child_count": moved_relation_child_count,
            "after_source_a_remove_child_count": len(after_remove_child),
            "round_trip_reconcile_mutation_count": len(
                round_trip_reconcile.mutations
            ),
            "missing_child_restore_mutation_count": len(
                missing_child_result.mutations
            ),
            "restored_child_count": restored_child_count,
            "duplicate_child_unsupported": list(
                duplicate_child_result.unsupported
            ),
            "forged_evidence_unsupported": list(
                forged_evidence_result.unsupported
            ),
            "removed_parent_child_count": removed_parent_child_count,
            "summon_halo_rng_event_count": len(
                rng_spawn_result.rng_events
            ),
            "wave_halo_reconciliation": wave_halo_case,
        },
        "audit_replay": {
            "source_audit": {
                key: value
                for key, value in source_audit.to_json().items()
                if key
                in {
                    "ok",
                    "checked_mutations",
                    "checked_records",
                    "violations",
                }
            },
            "replay": {
                key: value
                for key, value in replay.to_json().items()
                if key in {"ok", "errors", "conflicts"}
            },
            "tampered_replay": {
                key: value
                for key, value in tampered_replay.to_json().items()
                if key in {"ok", "errors", "conflicts"}
            },
        },
        "negative_rows": [
            *bad_runtime_rows,
            {
                "case": "missing_halo_child_projection",
                "ok": missing_child_result.ok,
                "mutation_count": len(missing_child_result.mutations),
                "restored_child_count": restored_child_count,
            },
            {
                "case": "duplicate_halo_child_projection",
                "ok": duplicate_child_result.ok,
                "unsupported": list(duplicate_child_result.unsupported),
            },
            {
                "case": "forged_halo_source_evidence_position",
                "ok": forged_evidence_result.ok,
                "unsupported": list(forged_evidence_result.unsupported),
            },
            {
                "case": "removed_halo_source",
                "ok": removed_parent_result.ok,
                "mutation_count": len(removed_parent_result.mutations),
                "remaining_projection_count": (
                    removed_parent_child_count
                ),
            },
            {
                "case": "corrupt_halo_source_identity",
                "ok": failed_reconcile.ok,
                "unsupported": list(failed_reconcile.unsupported),
            },
            {
                "case": "later_relation_failure_discards_prior_effects",
                "ok": atomic_failure.ok,
                "pre_failure_mutation_count": len(
                    atomic_update_success.mutations
                ),
                "failure_mutation_count": len(atomic_failure.mutations),
                "failure_event_count": len(atomic_failure.events),
                "failure_rng_event_count": len(atomic_failure.rng_events),
                "failure_record_types": [
                    record.get("record_type")
                    for record in atomic_failure.records
                ],
                "all_failure_records_process_only": all(
                    record.get("process_only") is True
                    for record in atomic_failure.records
                ),
                "unsupported": list(atomic_failure.unsupported),
            },
            {
                "case": "spawn_with_corrupt_halo_relation",
                "ok": failed_spawn.plan.ok,
                "blocked_reason": failed_spawn.plan.blocked_reason,
                "mutation_count": len(failed_spawn.mutations),
                "event_count": len(failed_spawn.events),
                "all_records_process_only": all(
                    record.get("process_only") is True
                    for record in failed_spawn.records
                ),
            },
            {
                "case": "tampered_halo_relation_replay",
                "ok": tampered_replay.ok,
                "errors": list(tampered_replay.errors),
            },
        ],
    }


def _walk_dicts(
    value: object,
    path: str = "$",
) -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        yield path, value
        for key, item in value.items():
            yield from _walk_dicts(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_dicts(item, f"{path}[{index}]")


def _equipment_specific_halo_handler_hits() -> list[dict[str, JSONValue]]:
    package_root = Path(__file__).resolve().parents[1]
    hits: list[dict[str, JSONValue]] = []
    for area in ("core", "systems", "scenarios"):
        for path in sorted((package_root / area).glob("*.py")):
            lines = path.read_text(encoding="utf-8").splitlines()
            normalized_file = "".join(
                character
                for line in lines
                for character in line.lower()
                if character.isalnum()
            )
            if "halo" not in normalized_file or not (
                "lightcone" in normalized_file
                or "equipment" in normalized_file
            ):
                continue
            hits.append(
                {
                    "path": path.relative_to(package_root).as_posix(),
                    "line": 0,
                    "text": (
                        "production file contains both halo and equipment/"
                        "light-cone concepts"
                    ),
                }
            )
    return hits


def _source_catalog_validation(tbgd_root: Path) -> dict[str, JSONValue]:
    catalog = build_light_cone_catalog(tbgd_root)
    definitions = catalog.canonical_definitions
    selected_record_indexes: dict[str, set[int]] = {}
    for definition in definitions:
        ability_source = definition.ability_source
        if ability_source is None:
            continue
        selected_record_indexes.setdefault(
            ability_source.source.source_path,
            set(),
        ).add(ability_source.record_index)
    source_paths = sorted(selected_record_indexes)
    rows: list[dict[str, JSONValue]] = []
    invalid_rows: list[dict[str, JSONValue]] = []
    ordinary_rows: list[dict[str, JSONValue]] = []
    file_hashes: dict[str, str] = {}
    for relative_path in source_paths:
        path = tbgd_root / relative_path
        raw_bytes = path.read_bytes()
        file_hashes[relative_path] = hashlib.sha256(raw_bytes).hexdigest()
        document = json.loads(raw_bytes)
        ability_list = (
            document.get("AbilityList")
            if isinstance(document, dict)
            else None
        )
        if not isinstance(ability_list, list):
            continue
        selected_records = [
            (
                f"$.AbilityList[{record_index}]",
                ability_list[record_index],
            )
            for record_index in sorted(
                selected_record_indexes[relative_path]
            )
            if 0 <= record_index < len(ability_list)
        ]
        for record_path, record in selected_records:
            for json_path, modifier in _walk_dicts(record, record_path):
                addition = modifier.get("AdditionConfig")
                sub_modifiers = (
                    addition.get("SubModifierList")
                    if isinstance(addition, dict)
                    else None
                )
                if not isinstance(sub_modifiers, list):
                    continue
                true_indexes = [
                    index
                    for index, item in enumerate(sub_modifiers)
                    if isinstance(item, dict)
                    and item.get("IsHaloStatus") is True
                ]
                if not true_indexes:
                    continue
                parent_name = json_path.rsplit(".", 1)[-1]
                effects, expressions = _modifier_addition_effects(
                    relative_path,
                    "P8R1SourceCatalog",
                    parent_name,
                    modifier,
                    source_context={"json_path": json_path},
                )
                expression_by_id = {
                    expression.target_expression_id: expression
                    for expression in expressions
                }
                for index in true_indexes:
                    source_json_path = (
                        f"{json_path}.AdditionConfig.SubModifierList[{index}]"
                    )
                    candidates = [
                        effect
                        for effect in effects
                        if isinstance(effect.payload.get("standard"), dict)
                        and effect.payload["standard"].get(
                            "addition_source_json_path"
                        )
                        == source_json_path
                    ]
                    raw = sub_modifiers[index]
                    effect = candidates[0] if len(candidates) == 1 else None
                    standard = (
                        effect.payload.get("standard")
                        if effect is not None
                        and isinstance(effect.payload.get("standard"), dict)
                        else {}
                    )
                    expression = expression_by_id.get(
                        str(standard.get("target_expression_id") or "")
                    )
                    raw_dynamic_values = (
                        raw.get("DynamicValues")
                        if isinstance(raw.get("DynamicValues"), dict)
                        else {}
                    )
                    lowered_dynamic_values = (
                        standard.get("dynamic_values")
                        if isinstance(standard.get("dynamic_values"), dict)
                        else {}
                    )
                    raw_dynamic_keys = sorted(
                        str(key) for key in raw_dynamic_values
                    )
                    lowered_dynamic_keys = sorted(
                        str(key) for key in lowered_dynamic_values
                    )
                    parent_dynamic_definitions = (
                        modifier.get("DynamicValues")
                        if isinstance(
                            modifier.get("DynamicValues"),
                            dict,
                        )
                        else {}
                    )
                    parent_dynamic_floats = (
                        parent_dynamic_definitions.get("Floats")
                        if isinstance(
                            parent_dynamic_definitions.get("Floats"),
                            dict,
                        )
                        else {}
                    )
                    parent_runtime_dynamic_inputs: list[
                        tuple[str, list[str]]
                    ] = []
                    for task_path, candidate in _walk_dicts(
                        record,
                        record_path,
                    ):
                        opcode = str(candidate.get("$type") or "")
                        raw_modifier_name = candidate.get("ModifierName")
                        candidate_modifier_name = (
                            raw_modifier_name.get("Value")
                            if isinstance(raw_modifier_name, dict)
                            else raw_modifier_name
                        )
                        candidate_dynamic_values = candidate.get(
                            "DynamicValues"
                        )
                        if (
                            opcode.rsplit(".", 1)[-1] == "AddModifier"
                            and candidate_modifier_name == parent_name
                            and isinstance(
                                candidate_dynamic_values,
                                dict,
                            )
                            and candidate_dynamic_values
                        ):
                            parent_runtime_dynamic_inputs.append(
                                (
                                    f"{task_path}.DynamicValues",
                                    sorted(
                                        str(key)
                                        for key in (
                                            candidate_dynamic_values
                                        )
                                    ),
                                )
                            )
                    uses_parent_dynamic_values = bool(
                        parent_runtime_dynamic_inputs
                    )
                    row = {
                        "source_path": relative_path,
                        "source_json_path": source_json_path,
                        "parent_modifier_name": parent_name,
                        "child_modifier_name": raw.get("Name"),
                        "target_type": raw.get("TargetType"),
                        "alive_only_raw": raw.get("AliveOnly"),
                        "has_chance_field": any(
                            key in raw for key in ("Chance", "BaseChance")
                        ),
                        "has_nested_addition": "AdditionConfig" in raw,
                        "raw_dynamic_value_count": len(
                            raw_dynamic_values
                        ),
                        "lowered_dynamic_value_count": len(
                            lowered_dynamic_values
                        ),
                        "raw_dynamic_value_keys": raw_dynamic_keys,
                        "lowered_dynamic_value_keys": (
                            lowered_dynamic_keys
                        ),
                        "dynamic_value_source_json_paths": [
                            f"{source_json_path}.DynamicValues.{key}"
                            for key in raw_dynamic_keys
                        ],
                        "parent_dynamic_definition_count": len(
                            parent_dynamic_floats
                        ),
                        "parent_dynamic_definition_source_json_path": (
                            f"{json_path}.DynamicValues.Floats"
                            if uses_parent_dynamic_values
                            else ""
                        ),
                        "parent_runtime_dynamic_input_count": sum(
                            len(keys)
                            for _, keys in (
                                parent_runtime_dynamic_inputs
                            )
                        ),
                        "parent_runtime_dynamic_input_sources": [
                            {
                                "source_json_path": path,
                                "keys": keys,
                            }
                            for path, keys in (
                                parent_runtime_dynamic_inputs
                            )
                        ],
                        "dynamic_projection_mode": (
                            "submodifier_dynamic_values"
                            if raw_dynamic_values
                            else (
                                "parent_status_dynamic_value_passthrough"
                                if uses_parent_dynamic_values
                                else "none"
                            )
                        ),
                        "dynamic_values_projected": (
                            raw_dynamic_keys == lowered_dynamic_keys
                            and all(
                                isinstance(
                                    lowered_dynamic_values.get(key),
                                    dict,
                                )
                                for key in lowered_dynamic_keys
                            )
                        ),
                        "candidate_count": len(candidates),
                        "effect_id": effect.effect_id if effect is not None else "",
                        "effect_coverage_status": (
                            effect.coverage_status if effect is not None else ""
                        ),
                        "is_halo_status": standard.get("is_halo_status"),
                        "halo_admission_status": standard.get(
                            "halo_admission_status"
                        ),
                        "is_halo_status_source_json_path": standard.get(
                            "is_halo_status_source_json_path"
                        ),
                        "target_expression_id": standard.get(
                            "target_expression_id"
                        ),
                        "target_expression_coverage": (
                            expression.coverage_status
                            if expression is not None
                            else ""
                        ),
                        "source_identity_matches": bool(
                            effect is not None
                            and expression is not None
                            and effect.source.source_path == relative_path
                            and expression.source.source_path == relative_path
                            and isinstance(effect.source.evidence, dict)
                            and isinstance(expression.source.evidence, dict)
                            and expression.source.evidence.get("json_path")
                            == source_json_path
                            and expression.source.evidence.get("source_raw_type")
                            == effect.source.raw_type
                            and expression.source.evidence.get("source_raw_id")
                            == effect.source.raw_id
                            and expression.source.evidence.get(
                                "target_expression_field"
                            )
                            == "TargetType"
                            and expression.source.evidence.get("target_json_path")
                            == f"{source_json_path}.TargetType"
                        ),
                    }
                    row["ok"] = bool(
                        len(candidates) == 1
                        and effect is not None
                        and effect.coverage_status == "executable"
                        and standard.get("is_halo_status") is True
                        and standard.get("halo_admission_status") == "executable"
                        and standard.get("is_halo_status_source_json_path")
                        == f"{source_json_path}.IsHaloStatus"
                        and expression is not None
                        and expression.coverage_status == "executable"
                        and row["source_identity_matches"]
                        and row["dynamic_values_projected"]
                        and not row["has_chance_field"]
                        and not row["has_nested_addition"]
                    )
                    rows.append(row)

    for value in ("true", 1, {"value": True}, [True]):
        effects, _ = _modifier_addition_effects(
            "validation/P8-R1/invalid_halo.json",
            "P8R1Invalid",
            "ParentInvalid",
            {
                "AdditionConfig": {
                    "SubModifierList": [
                        {
                            "Name": "ChildInvalid",
                            "TargetType": "CasterServant",
                            "IsHaloStatus": value,
                        }
                    ]
                }
            },
            source_context={"json_path": "$.ParentInvalid"},
        )
        effect = effects[0] if len(effects) == 1 else None
        standard = (
            effect.payload.get("standard")
            if effect is not None
            and isinstance(effect.payload.get("standard"), dict)
            else {}
        )
        invalid_rows.append(
            {
                "raw_type": type(value).__name__,
                "effect_count": len(effects),
                "coverage_status": (
                    effect.coverage_status if effect is not None else ""
                ),
                "link_blocked_reason": (
                    effect.link_blocked_reason if effect is not None else ""
                ),
                "is_halo_status": standard.get("is_halo_status"),
                "halo_admission_status": standard.get(
                    "halo_admission_status"
                ),
                "blocked_reason": standard.get("halo_blocked_reason"),
                "ok": bool(
                    effect is not None
                    and effect.coverage_status == "blocked"
                    and standard.get("is_halo_status") is False
                    and standard.get("halo_admission_status") == "blocked"
                ),
            }
        )

    for label, raw in (
        (
            "missing",
            {
                "Name": "ChildOrdinaryMissing",
                "TargetType": "CasterServant",
            },
        ),
        (
            "false",
            {
                "Name": "ChildOrdinaryFalse",
                "TargetType": "CasterServant",
                "IsHaloStatus": False,
            },
        ),
    ):
        effects, _ = _modifier_addition_effects(
            "validation/P8-R1/ordinary_addition.json",
            "P8R1Ordinary",
            "ParentOrdinary",
            {"AdditionConfig": {"SubModifierList": [raw]}},
            source_context={"json_path": "$.ParentOrdinary"},
        )
        effect = effects[0] if len(effects) == 1 else None
        standard = (
            effect.payload.get("standard")
            if effect is not None
            and isinstance(effect.payload.get("standard"), dict)
            else {}
        )
        ordinary_rows.append(
            {
                "case": label,
                "effect_count": len(effects),
                "coverage_status": (
                    effect.coverage_status if effect is not None else ""
                ),
                "is_halo_status": standard.get("is_halo_status"),
                "halo_admission_status": standard.get(
                    "halo_admission_status"
                ),
                "ok": bool(
                    effect is not None
                    and standard.get("is_halo_status") is False
                    and standard.get("halo_admission_status") == "ordinary"
                    and standard.get("halo_blocked_reason") == ""
                ),
            }
        )

    handler_hits = _equipment_specific_halo_handler_hits()
    checks = {
        "published_light_cone_halo_sources_non_empty": bool(rows),
        "published_light_cone_halo_projection_gap_free": all(
            row["ok"] for row in rows
        ),
        "halo_source_flag_strictly_typed": (
            bool(invalid_rows)
            and all(row["ok"] for row in invalid_rows)
            and all(row["ok"] for row in ordinary_rows)
        ),
        "published_halo_dynamic_values_projected": all(
            row["dynamic_values_projected"] for row in rows
        ),
        "equipment_specific_halo_handler_count_is_zero": not handler_hits,
    }
    return {
        "ok": (
            catalog.catalog_complete
            and all(checks.values())
        ),
        "checks": checks,
        "catalog": catalog.to_summary_json(),
        "published_definition_count": len(definitions),
        "ability_source_file_count": len(source_paths),
        "halo_source_count": len(rows),
        "halo_projection_gap_count": sum(
            1 for row in rows if not row["ok"]
        ),
        "halo_dynamic_source_count": sum(
            1
            for row in rows
            if row["raw_dynamic_value_count"] > 0
            or row["parent_runtime_dynamic_input_count"] > 0
        ),
        "halo_dynamic_projection_gap_count": sum(
            1
            for row in rows
            if row["raw_dynamic_value_count"] > 0
            and not row["dynamic_values_projected"]
        ),
        "equipment_specific_halo_handlers": len(handler_hits),
        "equipment_specific_halo_handler_hits": handler_hits,
        "source_file_hashes": file_hashes,
        "rows": rows,
        "invalid_type_rows": invalid_rows,
        "ordinary_addition_rows": ordinary_rows,
    }


def run_validation(
    tbgd_root: Path,
    output_dir: Path,
    *,
    runtime_only: bool,
    source_catalog_only: bool,
) -> dict[str, JSONValue]:
    runtime_result = (
        None if source_catalog_only else _runtime_validation()
    )
    source_result = (
        None
        if runtime_only
        else _source_catalog_validation(tbgd_root)
    )
    predicates: dict[str, JSONValue] = {}
    if runtime_result is not None:
        predicates.update(runtime_result["checks"])
    if source_result is not None:
        predicates.update(
            {
                "published_light_cone_halo_sources_non_empty": bool(
                    source_result["halo_source_count"]
                ),
                "published_light_cone_halo_projection_gap_count": (
                    source_result["halo_projection_gap_count"]
                ),
                "halo_source_flag_strictly_typed": source_result[
                    "checks"
                ]["halo_source_flag_strictly_typed"],
                "published_halo_dynamic_values_projected": (
                    source_result["checks"][
                        "published_halo_dynamic_values_projected"
                    ]
                ),
                "halo_dynamic_source_count": source_result[
                    "halo_dynamic_source_count"
                ],
                "halo_dynamic_projection_gap_count": source_result[
                    "halo_dynamic_projection_gap_count"
                ],
                "equipment_specific_halo_handlers": source_result[
                    "equipment_specific_halo_handlers"
                ],
            }
        )
    mode = (
        "runtime_only"
        if runtime_only
        else (
            "source_catalog_only"
            if source_catalog_only
            else "combined"
        )
    )
    result: dict[str, JSONValue] = {
        "version": VALIDATION_VERSION,
        "mode": mode,
        "ok": bool(
            (runtime_result is None or runtime_result["ok"])
            and (source_result is None or source_result["ok"])
        ),
        "predicates": predicates,
        "runtime": runtime_result,
        "source_catalog": source_result,
        "resource_policy": {
            "full_tbgd_lowering_count": 0,
            "full_s8_aggregate_count": 0,
            "catalog_builder_count": 0 if runtime_only else 1,
            "large_ir_artifact_written": False,
        },
        "catalog_startup": {
            "status": "not_run_in_focused_validator",
            "reason": (
                "The execution card keeps formal 162-card startup as a "
                "separate resource-capped S8 --catalog-startup-only regression."
            ),
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir
        / "validation_summary_p8_r1_summon_runtime_halo_lifecycle.json",
        result,
    )
    if runtime_result is not None:
        write_json(
            output_dir / "target_consumer_matrix_p8_r1.json",
            runtime_result["target_consumers"],
        )
        write_json(
            output_dir / "lifecycle_matrix_p8_r1.json",
            runtime_result["lifecycle"],
        )
        write_json(
            output_dir / "negative_matrix_p8_r1.json",
            runtime_result["negative_rows"],
        )
    if source_result is not None:
        write_json(
            output_dir / "halo_source_shape_matrix_p8_r1.json",
            source_result,
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--runtime-only", action="store_true")
    mode.add_argument("--source-catalog-only", action="store_true")
    args = parser.parse_args()
    result = run_validation(
        args.tbgd_root.resolve(),
        args.output_dir.resolve(),
        runtime_only=args.runtime_only,
        source_catalog_only=args.source_catalog_only,
    )
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "mode": result["mode"],
                "output_dir": args.output_dir.as_posix(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
