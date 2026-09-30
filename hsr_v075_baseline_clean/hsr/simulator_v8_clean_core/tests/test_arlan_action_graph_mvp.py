"""Source-backed selector mechanism checks; complete action tests use battle catalog."""
from dataclasses import replace
from copy import deepcopy
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.condition_state import ConditionOperandRequest
from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator
from hsr.simulator_v8_clean_core.rules.expression_ir import CONDITION_EXPRESSION_NODE_SCHEMA
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, ConditionIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.condition_state import CommittedConditionFactProvider
from hsr.simulator_v8_clean_core.tbgd.character_cards import (
    CHARACTER_ACTION_DEFINITION_TABLES, build_character_card_ir,
)
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering


@pytest.fixture(scope="module")
def selector_fixture():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    lowerer = TBGDLowering(root)
    catalog = replace(lowerer.build_character_ability_source_graph_catalog(), fingerprint_kind="partial")
    cards = build_character_card_ir(
        root, max_records_per_table=None, skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
        avatar_ids=frozenset({"1008"}), ability_source_graph_catalog=catalog,
        ability_scope_catalog=lowerer._character_ability_scope_catalog,
    )
    card = next(item for item in cards.character_data_cards if item.entity_ref == "avatar:1008")
    fields = {key: tuple(value) for key, value in vars(cards).items()}
    for key in ("character_build_selector_relations", "character_build_selector_gaps"):
        fields[key] = tuple(item for item in fields[key] if item.character_data_card_id == card.card_id)
    rules = RuleBook(CanonicalIR(
        version="source_selector_test", character_ability_source_graph_catalog=catalog, **fields,
    ))
    relation = next(item for item in rules.character_build_selector_relations_for_card(card.card_id)
                    if item.selector_kind == "rank")
    state = BattleState(units={"actor": UnitState("actor", "ally", card.entity_ref, flags={
        "build_mode": "assembled_character_build", "character_build_battle_admission_status": "admitted",
        "character_data_card_id": card.card_id, "selected_eidolon_slot_ids": (),
        "selected_trace_node_ids": (),
    })})
    return rules, relation, state, lowerer


def _condition(relation, *, inverse=False):
    return ConditionIR(
        "test:selector", "ByRankActivated", {
            "build_selector": {"selector_kind": "rank", "selector_key": "",
                               "selector_hash": relation.selector_hash},
            "Inverse": inverse,
        }, relation.selector_source, "executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )


@pytest.mark.parametrize("selected,inverse,expected", [
    (False, False, False), (True, False, True), (False, True, True), (True, True, False),
])
def test_source_rank_selection_and_inverse_once(selector_fixture, selected, inverse, expected):
    rules, relation, state, _ = selector_fixture
    actor = state.units["actor"]
    state = replace(state, units={"actor": replace(actor, flags={
        **actor.flags, "selected_eidolon_slot_ids": relation.selection_ref_ids if selected else (),
    })})
    before = state.snapshot().to_json()
    result = RuleEvaluator().evaluate_condition_result(_condition(relation, inverse=inverse), EvaluationContext(
        state=state, actor_id="actor", committed_condition_provider=CommittedConditionFactProvider(rules),
    ))
    assert result.ok and result.result is expected, result.to_json()
    assert state.snapshot().to_json() == before


@pytest.mark.parametrize("invalid", ["missing_selection", "wrong_owner", "unknown_hash", "unadmitted"])
def test_selector_missing_source_or_build_context_is_blocked(selector_fixture, invalid):
    rules, relation, state, _ = selector_fixture
    actor = state.units["actor"]
    flags = dict(actor.flags)
    if invalid == "missing_selection":
        flags.pop("selected_eidolon_slot_ids")
    if invalid == "unadmitted":
        flags["character_build_battle_admission_status"] = "blocked"
    state = replace(state, units={"actor": replace(
        actor, flags=flags, template_id="avatar:wrong" if invalid == "wrong_owner" else actor.template_id,
    )})
    request = ConditionOperandRequest("unit.build_selector", ("actor",), {
        "selector_kind": "rank", "selector_key": "",
        "selector_hash": 0 if invalid == "unknown_hash" else relation.selector_hash,
    })
    before = state.snapshot().to_json()
    result = CommittedConditionFactProvider(rules).resolve(state, request)
    assert result.status == "blocked" and result.value is None
    assert state.snapshot().to_json() == before


@pytest.mark.parametrize("gameplay_field,with_branch", [(False, False), (True, False), (False, True)])
def test_timeline_wait_only_retires_presentation_responsibility(gameplay_field, with_branch):
    from hsr.simulator_v8_clean_core.tests.test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement import (
        _control, _responsibility, _task,
    )
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import _node_status

    control = _control(family="WaitTimelineFinish", gameplay_field=gameplay_field, with_branch=with_branch)
    fields = (_responsibility(control.node_id, control.family, "TimelineName"),)
    if gameplay_field:
        fields += (control.field_responsibilities[-1],)
    control = replace(control, peer_field_names=tuple(sorted(item.field_name for item in fields)),
                      field_responsibilities=fields)
    task = _task(family="WaitTimelineFinish")
    kind, status, owners, reason = _node_status(control, task)
    if gameplay_field or with_branch:
        assert status == "deferred" and reason
    else:
        assert (kind, status, owners, reason) == ("leaf", "materialized", ("task_graph_execution",), "")


def test_actual_presentation_tasks_reject_unknown_nested_gameplay():
    from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    raw = json.loads((root / "Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json").read_text())
    families = {"MoveToTargetList", "MoveStageOnTargetForward", "SetTeamRootOffset",
                "SetSkillTargetFormationByPos", "ShowBattleUI", "TargetTimeSlow", "WaitTimelineFinish"}
    found = {}

    def walk(value):
        if isinstance(value, dict):
            family = str(value.get("$type", "")).split(".")[-1]
            if family in families:
                found.setdefault(family, []).append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(raw)
    assert set(found) == families
    for family, tasks in found.items():
        assert ability_task_execution_mode(family) == "process_only"
        for task in tasks:
            assert not _process_only_ability_task_source_blocked_reason(task, family)
            bad = {**task, "TaskList": [{"$type": "RPG.GameCore.HealHP"}]}
            assert _process_only_ability_task_source_blocked_reason(bad, family)
    bad = deepcopy(found["MoveToTargetList"][0])
    bad["MovingRangeList"][0]["TargetType"]["TaskList"] = []
    assert _process_only_ability_task_source_blocked_reason(bad, "MoveToTargetList")


def test_rank_raw_lowering_keeps_strict_selector_identity(selector_fixture):
    from hsr.simulator_v8_clean_core.tbgd.lowering import _typed_condition_payload, _condition_payload_executable
    _, relation, _, _ = selector_fixture
    raw = {"TriggerKey": {"Hash": relation.selector_hash}, "Inverse": True}
    payload = _typed_condition_payload("ByRankActivated", raw, source=relation.selector_source)
    assert _condition_payload_executable("ByRankActivated", payload)
    assert payload["build_selector"]["selector_hash"] == relation.selector_hash
    assert not _condition_payload_executable("ByRankActivated", {**payload, "Unknown": True})
    payload = _typed_condition_payload("ByRankActivated", {"TriggerKey": {"Hash": True}}, source=relation.selector_source)
    assert not _condition_payload_executable("ByRankActivated", payload)


def test_monster_aim_tasks_are_strict_presentation_shapes():
    from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    raw = json.loads((root / "Config/ConfigAbility/Monster/Monster_AML_Minion01_00_Ability.json").read_text())
    tasks = [task for ability in raw["AbilityList"] for task in ability.get("OnStart", [])
             if task.get("$type") in {"RPG.GameCore.StartAim", "RPG.GameCore.StopAim"}]
    assert len(tasks) == 2
    for task in tasks:
        family = task["$type"].split(".")[-1]
        assert ability_task_execution_mode(family) == "process_only"
        assert not _process_only_ability_task_source_blocked_reason(task, family)
        assert _process_only_ability_task_source_blocked_reason({**task, "TaskList": []}, family)


def test_selected_materialization_keeps_source_denominator_and_complete_guard(selector_fixture):
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
        materialize_character_runtime_task_graph_catalog, materialize_selected_character_task_graphs,
    )
    rules, _, _, lowerer = selector_fixture
    catalog = lowerer.build_character_control_flow_contract_catalog()
    snapshot = lowerer._character_ability_raw_snapshot
    with pytest.raises(ValueError, match="complete"):
        materialize_character_runtime_task_graph_catalog(
            catalog, rules.ir, source_snapshot=snapshot, definition_scope_complete=False,
        )
    # A source-selected file cannot silently lose its raw status callbacks.
    with pytest.raises(ValueError, match="callback source denominator is incomplete"):
        materialize_selected_character_task_graphs(
            catalog, rules.ir, source_snapshot=snapshot,
            selected_source_paths=frozenset({"Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json"}),
        )


def test_death_barrier_verifies_real_damage_lifecycle_without_new_mutations():
    from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
    from hsr.simulator_v8_clean_core.rules.ir import EffectIR, IRSource
    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
    from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
    from hsr.simulator_v8_clean_core.tbgd.lowering import _effect_payload, _effect_coverage_status

    raw = {"$type": "RPG.GameCore.TriggerSkipDeadHandler"}
    source = IRSource("Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json",
                      "AbilityTask", "Avatar_Arlan_Skill03_Phase02", {"json_path": "$.AbilityList[6].OnStart[12]"})
    payload = _effect_payload(raw, "TriggerSkipDeadHandler", "")
    effect = EffectIR("test:death-barrier", "TriggerSkipDeadHandler", payload, source,
                      _effect_coverage_status("TriggerSkipDeadHandler", payload))
    state = BattleState(units={"actor": UnitState("actor", "ally", "test:actor", hp=100, max_hp=100),
                               "enemy": UnitState("enemy", "enemy", "test:enemy", hp=20, max_hp=20)})
    registry = EffectRegistry()
    before = registry.execute(effect, EffectExecutionContext(state, "actor", effect.effect_id))
    assert not before.unsupported and not before.mutations and not before.events
    produced = DamageSystem().apply_packet(state, DamagePacket(
        "actor", "enemy", "Normal", "true_damage", 30, "fixed_final", source_trace={"kind": "mechanism_test"},
    ))
    assert produced.ok, produced.errors
    hp_event = next(event for event in produced.events if event.event_type == "hp.change")
    hp_mutation = next(mutation for mutation in produced.mutations if mutation.path[-1] == "hp")
    assert hp_event.payload["mutation_id"] == hp_mutation.stable_id()
    assert sum(event.event_type == "hp.change" for event in produced.events) == 1
    after = MutationReducer().apply_all(state, produced.mutations)
    assert after.units["enemy"].hp == 0 and after.units["enemy"].lifecycle_status == "defeated"
    passed = registry.execute(effect, EffectExecutionContext(after, "actor", effect.effect_id))
    assert not passed.unsupported and not passed.mutations and not passed.events and not passed.rng_events
    assert passed.records[0]["source"] == "unit_lifecycle"
    incomplete = MutationReducer().apply_all(state, tuple(m for m in produced.mutations if m.path[-1] == "hp"))
    failed = registry.execute(effect, EffectExecutionContext(incomplete, "actor", effect.effect_id))
    assert failed.unsupported and "death_settlement_incomplete" in str(failed.records)
    assert not failed.mutations and not failed.events and not failed.rng_events
    bad_payload = _effect_payload({**raw, "SuccessTaskList": []}, "TriggerSkipDeadHandler", "")
    assert _effect_coverage_status("TriggerSkipDeadHandler", bad_payload) == "blocked"


def test_hp_loss_produces_one_mutation_backed_event_before_next_task():
    from hsr.simulator_v8_clean_core.core.executor import _eventful_transition_events
    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
    state = BattleState(units={"actor": UnitState("actor", "ally", "test:actor", hp=100, max_hp=100)})
    packet = DamagePacket("actor", "actor", "Skill", "hp_loss", 15, "fixed_final")
    result = DamageSystem().apply_packet(state, packet)
    assert result.ok and result.events[0].event_type == "hp.change"
    assert result.events[0].payload["mutation_id"] == result.mutations[0].stable_id()
    events = _eventful_transition_events(state, result.mutations, result.events,
                                        producer_id="synthetic:hp-loss", actor_id="actor")
    assert sum(event.event_type == "hp.change" for event in events) == 1
    unchanged = DamageSystem().apply_packet(state, replace(packet, amount=0))
    assert unchanged.ok and not any(event.event_type == "hp.change" for event in unchanged.events)
