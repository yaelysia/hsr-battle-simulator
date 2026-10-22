"""Conditional monster passive startup roots execute their admitted branch atomically."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.expression_ir import (
    CONDITION_EXPRESSION_NODE_SCHEMA,
    numeric_fixed,
    numeric_missing,
)
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityPhaseIR,
    AbilityTaskIR,
    CanonicalIR,
    ConditionIR,
    EffectIR,
    IRSource,
    MonsterDataCardIR,
    PassiveMechanismSlotIR,
    RuleEntity,
    StandaloneAbilityGraphIR,
    TargetExpressionIR,
    TargetExpressionNodeIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.dynamic_values import (
    store_from_state,
    upsert_dynamic_value,
)
from hsr.simulator_v8_clean_core.systems.startup import (
    _apply_startup_ability_effects,
    _passive_runtime_activation,
)
from hsr.simulator_v8_clean_core.tbgd.expression_lowering import (
    lower_dynamic_value_operation_spec,
)

SOURCE_PATH = "fixture/Monster_Fixture_Ability.json"
ABILITY_NAME = "Monster_Fixture_Passive"
PHASE_ID = "ability_phase:fixture:on_start"
ACTION_ID = "fixture:action"
CONDITION_ID = "condition:fixture:monster-id"
CONDITION_PATH = "$.AbilityList[0].OnStart[1].Predicate"
DYNAMIC_NAME = "FixtureCounter"
DYNAMIC_HASH = "-1000001"


def _source(raw_type: str, raw_id: str, json_path: str) -> IRSource:
    return IRSource(SOURCE_PATH, raw_type, raw_id, {"json_path": json_path})


def _caster_node(source: IRSource) -> TargetExpressionNodeIR:
    return TargetExpressionNodeIR.build(
        "TargetFetchCaster", source, {"name": "", "unique_name": ""}
    )


def _target_expression() -> TargetExpressionIR:
    source = _source(
        "RPG.GameCore.AddModifier",
        "fixture:add_modifier:TargetType",
        "$.AbilityList[0].OnStart[2].TargetType",
    )
    return TargetExpressionIR(
        "target_expression:fixture:caster",
        "TargetFetchCaster",
        "Caster",
        source,
        node=_caster_node(source),
        coverage_status="executable",
    )


def _condition(monster_id: int = 1003010) -> ConditionIR:
    condition_source = _source(
        "RPG.GameCore.PredicateTaskList", "condition:fixture:monster-id", CONDITION_PATH,
    )
    target_source = _source(
        "RPG.GameCore.TargetAlias",
        "condition:fixture:monster-id:TargetType",
        f"{CONDITION_PATH}.TargetType",
    )
    return ConditionIR(
        condition_id=CONDITION_ID,
        opcode="ByCompareMonsterID",
        payload={
            "TargetType": _caster_node(target_source),
            "TargetMonsterID": numeric_fixed(float(monster_id)),
            "CompareType": "Equal",
        },
        source=condition_source,
        coverage_status="executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )


def _definition(modifier_name: str) -> RuleEntity:
    return RuleEntity(
        entity_id=f"modifier_definition:{modifier_name}",
        entity_type="modifier_definition",
        fields={
            "modifier_name": modifier_name,
            "status_type": "Buff",
            "behavior_flags": [],
            "lifetime_expr": numeric_missing(),
            "max_layer_expr": numeric_missing(),
            "layer_add_when_stack_expr": numeric_missing(),
        },
        source=_source(
            "RPG.GameCore.StatusConfig", f"fixture:{modifier_name}", "$.fixture.modifier",
        ),
        coverage_status="executable",
    )


def _add_modifier_effect(
    effect_id: str,
    modifier_name: str,
    target_expression: TargetExpressionIR,
) -> EffectIR:
    return EffectIR(
        effect_id,
        "AddModifier",
        {
            "standard": {
                "modifier_name": modifier_name,
                "target_alias": "Caster",
                "target_expression_id": target_expression.target_expression_id,
                "target_expression_coverage_status": "executable",
                "inherit_caster": "effect_caster",
                "lifetime": numeric_missing(),
                "max_layer": numeric_missing(),
                "layer_add_when_stack": numeric_missing(),
                "chance": numeric_missing(),
                "omitted_chance_semantics": "guaranteed_no_resistance",
                "omitted_chance_semantics_source": {
                    "kind": "engine_rule",
                    "rule_id": "fixture",
                },
                "blocked_reason": "",
            }
        },
        _source("RPG.GameCore.AddModifier", effect_id, "$.AbilityList[0].OnStart[2]"),
        coverage_status="executable",
        source_mode="mainline",
        modifier_definition_id=f"modifier_definition:{modifier_name}",
    )


def _define_dynamic_effect(
    effect_id: str,
    *,
    value: float,
    explicit_reset: bool,
) -> EffectIR:
    standard = {
        "kind": "dynamic_value_store",
        "opcode": "DefineDynamicValue",
        "target_alias": "Caster",
        "status_scope": "TargetEntity",
        "value_name": DYNAMIC_NAME,
        "hash": DYNAMIC_HASH,
        "value_expr": numeric_fixed(float(value)),
        "value_source_basis": (
            "explicit_tbgd_field"
            if explicit_reset
            else "tbgd_define_dynamic_value_missing_reset_defaults_to_zero"
        ),
        "raw_formula_fields": {
            "DynamicKey": {"Value": DYNAMIC_NAME},
            "ResetValue": (
                {"IsDynamic": False, "FixedValue": {"Value": value}}
                if explicit_reset
                else None
            ),
            "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
            "ContextScope": "TargetEntity",
        },
    }
    standard["dynamic_operation"] = lower_dynamic_value_operation_spec(
        "DefineDynamicValue", standard
    )
    return EffectIR(
        effect_id,
        "DefineDynamicValue",
        {"standard": standard},
        _source("RPG.GameCore.DefineDynamicValue", effect_id, "$.AbilityList[0].OnStart[3]"),
        coverage_status="executable",
        source_mode="mainline",
    )


def _task(
    task_id: str,
    opcode: str,
    *,
    effect_id: str = "",
    condition_id: str = "",
    index: int = 0,
    parent: str = "",
) -> AbilityTaskIR:
    return AbilityTaskIR(
        task_id=task_id,
        phase_id=PHASE_ID,
        action_id=ACTION_ID,
        level=1,
        ability_name=ABILITY_NAME,
        callback_kind="OnStart",
        task_index=index,
        task_path=f"OnStart[{index}]",
        branch="root",
        opcode=opcode,
        source=_source(
            f"RPG.GameCore.{opcode}", task_id, f"$.AbilityList[0].OnStart[{index}]",
        ),
        effect_id=effect_id,
        condition_id=condition_id,
        parent_task_id=parent,
        coverage_status="executable",
    )


def _rules(
    *,
    effects: tuple[EffectIR, ...],
    tasks: tuple[AbilityTaskIR, ...],
    condition: ConditionIR,
    definitions: tuple[RuleEntity, ...],
    target_expression: TargetExpressionIR,
) -> RuleBook:
    phase = AbilityPhaseIR(
        phase_id=PHASE_ID,
        binding_id="fixture:binding",
        action_id=ACTION_ID,
        level=1,
        ability_name=ABILITY_NAME,
        phase_index=0,
        target_info={},
        opcode_summary={},
        callback_summaries={},
        source=_source("RPG.GameCore.AbilityPhase", PHASE_ID, "$.AbilityList[0]"),
        coverage_status="executable",
        task_ids=tuple(task.task_id for task in tasks),
        # The external-legacy role is the hand-built root provider: roots are the
        # parentless tasks, so no compiled task-graph catalog is needed.
        invocation_role="external_legacy",
    )
    graph = StandaloneAbilityGraphIR(
        standalone_ability_graph_id="standalone_ability_graph:fixture",
        ability_name=ABILITY_NAME,
        source_mode="mainline_monster",
        phase_ids=(PHASE_ID,),
        task_ids=tuple(task.task_id for task in tasks),
        executable_task_ids=tuple(task.task_id for task in tasks),
        source=_source("RPG.GameCore.Ability", ABILITY_NAME, "$.AbilityList[0]"),
        coverage_status="executable",
    )
    return RuleBook(
        CanonicalIR(
            "fixture-conditional-startup",
            entities=definitions,
            standalone_ability_graphs=(graph,),
            ability_phases=(phase,),
            ability_tasks=tasks,
            effects=effects,
            conditions=(condition,),
            target_expressions=(target_expression,),
        )
    )


def _state(
    template_id: str = "monster:1003010",
    *,
    global_flags: dict | None = None,
) -> BattleState:
    return BattleState(
        units={
            "owner": UnitState(
                "owner", "enemy", template_id, hp=100.0, max_hp=100.0,
            ),
        },
        global_flags=global_flags or {},
    )


def _spec(
    *,
    admitted_tasks: tuple[dict, ...],
    admitted_task_ids: tuple[str, ...],
) -> dict:
    return {
        "kind": "monster_passive_startup_ability",
        "unit_id": "owner",
        "ability_name": ABILITY_NAME,
        "slot_id": "fixture:slot",
        "slot_id_field": "passive_slot_id",
        "admitted_task_ids": admitted_task_ids,
        "admitted_tasks": admitted_tasks,
    }


def _predicate_entry(
    root: AbilityTaskIR,
    *,
    success_ids: tuple[str, ...],
    failed_ids: tuple[str, ...],
    branch_tasks: tuple[dict, ...],
) -> dict:
    return {
        "task_id": root.task_id,
        "kind": "predicate_branch",
        "condition_id": CONDITION_ID,
        "condition_opcode": "ByCompareMonsterID",
        "success_task_ids": list(success_ids),
        "failed_task_ids": list(failed_ids),
        "branch_tasks": list(branch_tasks),
    }


def _two_branch_case():
    target_expression = _target_expression()
    success_effect = _add_modifier_effect(
        "effect:fixture:success", "FixtureSuccessModifier", target_expression,
    )
    failed_effect = _add_modifier_effect(
        "effect:fixture:failed", "FixtureFailedModifier", target_expression,
    )
    root = _task("task:fixture:predicate", "PredicateTaskList", condition_id=CONDITION_ID)
    success = _task(
        "task:fixture:success", "AddModifier",
        effect_id=success_effect.effect_id, index=1, parent=root.task_id,
    )
    failed = _task(
        "task:fixture:failed", "AddModifier",
        effect_id=failed_effect.effect_id, index=2, parent=root.task_id,
    )
    root = replace(
        root,
        success_task_ids=(success.task_id,),
        failed_task_ids=(failed.task_id,),
    )
    rules = _rules(
        effects=(success_effect, failed_effect),
        tasks=(root, success, failed),
        condition=_condition(1003010),
        definitions=(
            _definition("FixtureSuccessModifier"),
            _definition("FixtureFailedModifier"),
        ),
        target_expression=target_expression,
    )
    entry = _predicate_entry(
        root,
        success_ids=(success.task_id,),
        failed_ids=(failed.task_id,),
        branch_tasks=(
            {"task_id": success.task_id, "effect_id": success_effect.effect_id},
            {"task_id": failed.task_id, "effect_id": failed_effect.effect_id},
        ),
    )
    spec = _spec(
        admitted_tasks=(entry,),
        # Lowering admits only the predicate root itself; branch leaves are
        # admitted by the predicate entry's branch_tasks ledger.
        admitted_task_ids=(root.task_id,),
    )
    return rules, spec


def test_true_branch_applies_only_the_success_add_modifier():
    rules, spec = _two_branch_case()
    state = _state("monster:1003010")
    before = deepcopy(state.snapshot().to_json())

    result = _apply_startup_ability_effects(state, rules, [spec])

    assert not result.blocked, [item.get("reason") for item in result.blocked]
    assert result.state.units["owner"].statuses == ("modifier:FixtureSuccessModifier",)
    assert [trace["task_id"] for trace in result.source_traces] == [
        "task:fixture:predicate", "task:fixture:success",
    ]
    branch_trace = result.source_traces[0]
    assert branch_trace["status"] == "applied"
    assert branch_trace["condition_branch"] == "success"
    assert branch_trace["condition_evaluation"]["ok"] is True
    assert branch_trace["condition_evaluation"]["result"] is True
    assert branch_trace["condition_id"] == CONDITION_ID
    assert branch_trace["applied_task_ids"] == ["task:fixture:success"]
    assert result.source_traces[1]["status"] == "applied"
    assert state.snapshot().to_json() == before
    assert (
        MutationReducer().apply_all(state, result.mutations).snapshot().to_json()
        == result.state.snapshot().to_json()
    )


def test_false_branch_applies_only_the_failed_add_modifier():
    rules, spec = _two_branch_case()
    state = _state("monster:9999999")

    result = _apply_startup_ability_effects(state, rules, [spec])

    assert not result.blocked, [item.get("reason") for item in result.blocked]
    assert result.state.units["owner"].statuses == ("modifier:FixtureFailedModifier",)
    branch_trace = result.source_traces[0]
    assert branch_trace["condition_branch"] == "failed"
    assert branch_trace["condition_evaluation"]["ok"] is True
    assert branch_trace["condition_evaluation"]["result"] is False
    assert branch_trace["applied_task_ids"] == ["task:fixture:failed"]
    assert [trace["task_id"] for trace in result.source_traces] == [
        "task:fixture:predicate", "task:fixture:failed",
    ]


def test_undecidable_condition_blocks_the_whole_startup_without_state_change():
    rules, spec = _two_branch_case()
    # No numeric monster identity in template_id or flags: the evaluator
    # refuses to guess the caster's monster id.
    state = _state("fixture-unit")
    before = deepcopy(state.snapshot().to_json())

    result = _apply_startup_ability_effects(state, rules, [spec])

    assert result.blocked, "undecidable condition must block the startup"
    reason = str(result.blocked[0].get("reason") or "")
    assert reason.startswith(f"blocked_condition:{CONDITION_ID}:")
    assert "target_monster_id_missing" in reason
    assert not result.mutations
    assert not result.events
    assert not result.rng_events
    assert result.state.snapshot().to_json() == before
    assert len(result.source_traces) == 1
    trace = result.source_traces[0]
    assert trace["status"] == "blocked"
    assert "condition_evaluation" in trace
    assert trace["condition_evaluation"]["ok"] is False
    assert trace["condition_evaluation"]["result"] is None
    assert "condition_branch" not in trace


def test_branch_leaf_missing_from_the_admission_ledger_is_skipped():
    target_expression = _target_expression()
    admitted_effect = _add_modifier_effect(
        "effect:fixture:admitted", "FixtureAdmittedModifier", target_expression,
    )
    unadmitted_effect = _add_modifier_effect(
        "effect:fixture:unadmitted", "FixtureUnadmittedModifier", target_expression,
    )
    root = _task("task:fixture:predicate", "PredicateTaskList", condition_id=CONDITION_ID)
    admitted = _task(
        "task:fixture:admitted", "AddModifier",
        effect_id=admitted_effect.effect_id, index=1, parent=root.task_id,
    )
    unadmitted = _task(
        "task:fixture:unadmitted", "AddModifier",
        effect_id=unadmitted_effect.effect_id, index=2, parent=root.task_id,
    )
    root = replace(
        root,
        success_task_ids=(admitted.task_id, unadmitted.task_id),
        failed_task_ids=(),
    )
    rules = _rules(
        effects=(admitted_effect, unadmitted_effect),
        tasks=(root, admitted, unadmitted),
        condition=_condition(1003010),
        definitions=(
            _definition("FixtureAdmittedModifier"),
            _definition("FixtureUnadmittedModifier"),
        ),
        target_expression=target_expression,
    )
    entry = _predicate_entry(
        root,
        success_ids=(admitted.task_id, unadmitted.task_id),
        failed_ids=(),
        branch_tasks=(
            {"task_id": admitted.task_id, "effect_id": admitted_effect.effect_id},
        ),
    )
    result = _apply_startup_ability_effects(
        _state("monster:1003010"),
        rules,
        [_spec(admitted_tasks=(entry,), admitted_task_ids=(root.task_id,))],
    )
    assert not result.blocked, [item.get("reason") for item in result.blocked]
    assert result.state.units["owner"].statuses == ("modifier:FixtureAdmittedModifier",)
    assert [trace["task_id"] for trace in result.source_traces] == [
        "task:fixture:predicate", "task:fixture:admitted",
    ]
    assert result.source_traces[0]["applied_task_ids"] == ["task:fixture:admitted"]


def test_non_add_modifier_branch_leaf_blocks_the_startup():
    target_expression = _target_expression()
    dynamic_effect = _define_dynamic_effect(
        "effect:fixture:dynamic", value=0.0, explicit_reset=False,
    )
    root = _task("task:fixture:predicate", "PredicateTaskList", condition_id=CONDITION_ID)
    dynamic = _task(
        "task:fixture:dynamic", "DefineDynamicValue",
        effect_id=dynamic_effect.effect_id, index=1, parent=root.task_id,
    )
    root = replace(root, success_task_ids=(dynamic.task_id,), failed_task_ids=())
    rules = _rules(
        effects=(dynamic_effect,),
        tasks=(root, dynamic),
        condition=_condition(1003010),
        definitions=(),
        target_expression=target_expression,
    )
    entry = _predicate_entry(
        root,
        success_ids=(dynamic.task_id,),
        failed_ids=(),
        branch_tasks=(
            {"task_id": dynamic.task_id, "effect_id": dynamic_effect.effect_id},
        ),
    )
    state = _state("monster:1003010")
    before = deepcopy(state.snapshot().to_json())

    result = _apply_startup_ability_effects(
        state, rules,
        [_spec(admitted_tasks=(entry,), admitted_task_ids=(root.task_id,))],
    )

    assert result.blocked
    assert result.blocked[0]["reason"] == (
        "startup_condition_branch_opcode_not_admitted:DefineDynamicValue"
    )
    assert not result.mutations
    assert result.state.snapshot().to_json() == before
    assert "condition_evaluation" in result.source_traces[0]


def test_condition_root_without_admission_entry_blocks_instead_of_guessing():
    target_expression = _target_expression()
    effect = _add_modifier_effect(
        "effect:fixture:success", "FixtureSuccessModifier", target_expression,
    )
    root = _task("task:fixture:predicate", "PredicateTaskList", condition_id=CONDITION_ID)
    child = _task(
        "task:fixture:success", "AddModifier",
        effect_id=effect.effect_id, index=1, parent=root.task_id,
    )
    root = replace(root, success_task_ids=(child.task_id,), failed_task_ids=())
    rules = _rules(
        effects=(effect,),
        tasks=(root, child),
        condition=_condition(1003010),
        definitions=(_definition("FixtureSuccessModifier"),),
        target_expression=target_expression,
    )
    state = _state("monster:1003010")
    before = deepcopy(state.snapshot().to_json())

    result = _apply_startup_ability_effects(
        state, rules,
        [_spec(admitted_tasks=(), admitted_task_ids=(root.task_id,))],
    )

    assert result.blocked
    assert result.blocked[0]["reason"] == "startup_condition_root_admission_missing"
    assert not result.mutations
    assert result.state.snapshot().to_json() == before


def _seed_dynamic_store(state: BattleState, value: float) -> BattleState:
    store = upsert_dynamic_value(
        store_from_state(state),
        scope="unit",
        owner_id="owner",
        value=value,
        value_name=DYNAMIC_NAME,
        hash_key=DYNAMIC_HASH,
        source_id="fixture:seed",
        source_trace={"source": "fixture"},
    )
    return replace(state, global_flags={**state.global_flags, "dynamic_value_store": store})


def _leaf_startup(rules: RuleBook, task: AbilityTaskIR, *, policy: str) -> dict:
    return _spec(
        admitted_tasks=(
            {
                "task_id": task.task_id,
                "effect_id": task.effect_id,
                "dynamic_value_reset_policy": policy,
            },
        ),
        admitted_task_ids=(task.task_id,),
    )


def _define_rules(effect: EffectIR, task: AbilityTaskIR, *, target_expression: TargetExpressionIR):
    return _rules(
        effects=(effect,),
        tasks=(task,),
        condition=_condition(1003010),
        definitions=(),
        target_expression=target_expression,
    )


def test_initialize_zero_only_leaf_is_blocked_when_the_value_already_exists():
    target_expression = _target_expression()
    effect = _define_dynamic_effect("effect:fixture:dynamic", value=0.0, explicit_reset=False)
    task = _task("task:fixture:dynamic", "DefineDynamicValue", effect_id=effect.effect_id)
    rules = _define_rules(effect, task, target_expression=target_expression)
    state = _seed_dynamic_store(_state("monster:1003010"), 5.0)
    before = deepcopy(state.snapshot().to_json())

    result = _apply_startup_ability_effects(
        state,
        rules,
        [_leaf_startup(rules, task, policy="initialize_zero_only_when_absent")],
    )

    assert result.blocked
    trace = result.blocked[0]
    assert trace["reason"] == "startup_dynamic_value_redefinition_not_admitted"
    assert trace["dynamic_value_reset_policy"] == "initialize_zero_only_when_absent"
    assert trace["existing_dynamic_value"]["name"] == DYNAMIC_NAME
    assert trace["existing_dynamic_value"]["value"] == 5.0
    assert trace["state_unchanged"] is True
    assert not result.mutations
    assert not result.events
    assert result.state.snapshot().to_json() == before
    stored = store_from_state(result.state)
    assert [entry["value"] for entry in stored["entries"].values()] == [5.0]


def test_initialize_zero_only_leaf_initializes_an_absent_value():
    target_expression = _target_expression()
    effect = _define_dynamic_effect("effect:fixture:dynamic", value=0.0, explicit_reset=False)
    task = _task("task:fixture:dynamic", "DefineDynamicValue", effect_id=effect.effect_id)
    rules = _define_rules(effect, task, target_expression=target_expression)
    state = _state("monster:1003010")

    result = _apply_startup_ability_effects(
        state,
        rules,
        [_leaf_startup(rules, task, policy="initialize_zero_only_when_absent")],
    )

    assert not result.blocked, [item.get("reason") for item in result.blocked]
    entries = store_from_state(result.state)["entries"]
    assert len(entries) == 1
    entry = next(iter(entries.values()))
    assert entry["name"] == DYNAMIC_NAME
    assert entry["hash"] == DYNAMIC_HASH
    assert entry["value"] == 0.0
    assert entry["scope_kind"] == "unit"
    assert entry["target_id"] == "owner"
    assert result.source_traces[0]["status"] == "applied"
    assert result.source_traces[0]["task_id"] == task.task_id


def test_explicit_reset_leaf_and_add_modifier_still_execute_in_source_order():
    target_expression = _target_expression()
    reset_effect = _define_dynamic_effect(
        "effect:fixture:reset", value=1.0, explicit_reset=True,
    )
    modifier_effect = _add_modifier_effect(
        "effect:fixture:modifier", "FixtureSuccessModifier", target_expression,
    )
    define_task = _task(
        "task:fixture:define", "DefineDynamicValue",
        effect_id=reset_effect.effect_id, index=0,
    )
    modifier_task = _task(
        "task:fixture:modifier", "AddModifier",
        effect_id=modifier_effect.effect_id, index=1,
    )
    rules = _rules(
        effects=(reset_effect, modifier_effect),
        tasks=(define_task, modifier_task),
        condition=_condition(1003010),
        definitions=(_definition("FixtureSuccessModifier"),),
        target_expression=target_expression,
    )
    state = _seed_dynamic_store(_state("monster:1003010"), 5.0)

    result = _apply_startup_ability_effects(
        state,
        rules,
        [
            _spec(
                admitted_tasks=(
                    {
                        "task_id": define_task.task_id,
                        "effect_id": define_task.effect_id,
                        "dynamic_value_reset_policy": "explicit_reset_value",
                    },
                    {"task_id": modifier_task.task_id, "effect_id": modifier_task.effect_id},
                ),
                admitted_task_ids=(define_task.task_id, modifier_task.task_id),
            )
        ],
    )

    assert not result.blocked, [item.get("reason") for item in result.blocked]
    assert [trace["task_id"] for trace in result.source_traces] == [
        define_task.task_id, modifier_task.task_id,
    ]
    assert all(trace["status"] == "applied" for trace in result.source_traces)
    assert result.state.units["owner"].statuses == ("modifier:FixtureSuccessModifier",)
    assert [entry["value"] for entry in store_from_state(result.state)["entries"].values()] == [1.0]


def _card_and_slot(
    *,
    admitted_entry: dict,
    admitted_task_ids: tuple[str, ...],
) -> tuple[MonsterDataCardIR, PassiveMechanismSlotIR]:
    card_source = _source("fixture/MonsterConfig.json", "MonsterDataCard", "$.fixture.card")
    slot_id = "passive_mechanism_slot:fixture:owner"
    card = MonsterDataCardIR(
        card_id="monster_data_card:fixture:owner",
        entity_ref="monster:1003010",
        monster_id="1003010",
        template_id="monster:1003010",
        rank="Normal",
        profile_id="",
        action_set_id="",
        skill_ids=(),
        skill_slots=(),
        ai_policy={},
        action_sequence=(),
        summon_refs=(),
        raw_parameter_blocks={},
        card_contract={},
        source=card_source,
        coverage_status="executable",
        passive_mechanism_slot_ids=(slot_id,),
    )
    slot = PassiveMechanismSlotIR(
        passive_slot_id=slot_id,
        data_card_id=card.card_id,
        data_card_kind="monster",
        owner_entity_ref=card.entity_ref,
        mechanism_kind="monster_ability_list_passive",
        runtime_system="monster_startup",
        linked_ir_ids={
            "ability_name": ABILITY_NAME,
            "admitted_task_ids": list(admitted_task_ids),
        },
        activation={"kind": "monster_passive_startup_ability"},
        semantics={
            "ability_name": ABILITY_NAME,
            "startup_admission": {
                "admission_status": "executable",
                "admitted_tasks": [admitted_entry],
            },
        },
        source=card_source,
        coverage_status="executable",
    )
    return card, slot


def test_passive_runtime_activation_exposes_the_conditional_admission_ledger():
    rules, manual_spec = _two_branch_case()
    entry = manual_spec["admitted_tasks"][0]
    card, slot = _card_and_slot(
        admitted_entry=entry,
        admitted_task_ids=manual_spec["admitted_task_ids"],
    )
    rules = RuleBook(
        replace(
            rules.ir,
            monster_data_cards=(card,),
            passive_mechanism_slots=(slot,),
        )
    )
    activation = _passive_runtime_activation(rules, card)
    assert len(activation["startup_specs"]) == 1
    startup_spec = activation["startup_specs"][0]
    assert startup_spec["kind"] == "monster_passive_startup_ability"
    assert startup_spec["admitted_tasks"] == (entry,)
    assert startup_spec["admitted_task_ids"] == manual_spec["admitted_task_ids"]
    specs = [{"unit_id": "owner", **startup_spec}]
    result = _apply_startup_ability_effects(_state("monster:1003010"), rules, specs)
    assert not result.blocked, [item.get("reason") for item in result.blocked]
    assert result.state.units["owner"].statuses == ("modifier:FixtureSuccessModifier",)
    assert result.source_traces[0]["condition_branch"] == "success"
