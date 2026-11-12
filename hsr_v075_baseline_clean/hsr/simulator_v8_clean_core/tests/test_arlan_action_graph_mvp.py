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
    catalog = lowerer.build_character_ability_source_graph_catalog()
    cards = build_character_card_ir(
        root, max_records_per_table=None, skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
        avatar_ids=frozenset({"1008"}), ability_source_graph_catalog=catalog,
        ability_scope_catalog=lowerer._character_ability_scope_catalog,
    )
    card = next(item for item in cards.character_data_cards if item.entity_ref == "avatar:1008")
    fields = {key: tuple(value) for key, value in vars(cards).items()}
    assert {item.character_data_card_id for key in (
        "character_build_selector_relations", "character_build_selector_gaps",
    ) for item in fields[key]} == {card.card_id}
    rules = RuleBook(CanonicalIR(
        version="source_selector_test", character_ability_source_graph_catalog=catalog,
        character_card_scope=("1008",), **fields,
    ))
    relation = next(item for item in rules.character_build_selector_relations_for_card(card.card_id)
                    if item.selector_kind == "rank")
    state = BattleState(units={"actor": UnitState("actor", "ally", card.entity_ref, flags={
        "build_mode": "assembled_character_build", "character_build_battle_admission_status": "admitted",
        "character_data_card_id": card.card_id, "selected_eidolon_slot_ids": (),
        "selected_trace_node_ids": (),
    })})
    return rules, relation, state, lowerer


@pytest.mark.parametrize("scope", [None, ("1008", "1105"), ("1008", "1008"), ()])
def test_selected_card_scope_cannot_hide_missing_or_duplicate_cards(selector_fixture, scope):
    rules, *_ = selector_fixture
    with pytest.raises(ValueError):
        replace(rules.ir, character_card_scope=scope)


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


@pytest.mark.parametrize("family,field", [("WaitTimelineFinish", "TimelineName"), ("WaitSecond", "WaitTime")])
@pytest.mark.parametrize("gameplay_field,with_branch", [(False, False), (True, False), (False, True)])
def test_timeline_wait_only_retires_presentation_responsibility(family, field, gameplay_field, with_branch):
    from hsr.simulator_v8_clean_core.tests.test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement import (
        _control, _responsibility, _task,
    )
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import _node_status

    control = _control(family=family, gameplay_field=gameplay_field, with_branch=with_branch)
    fields = (_responsibility(control.node_id, control.family, field),)
    if gameplay_field:
        fields += (control.field_responsibilities[-1],)
    control = replace(control, peer_field_names=tuple(sorted(item.field_name for item in fields)),
                      field_responsibilities=fields)
    task = _task(family=family)
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
    formation = deepcopy(found["SetSkillTargetFormationByPos"][0])
    formation["TargetFormation"] = {"LocalDelta": {"X": 0, "Y": 0, "Z": 0}, "Yaw": 0}
    assert not _process_only_ability_task_source_blocked_reason(formation, "SetSkillTargetFormationByPos")
    formation["TargetFormation"]["LocalDelta"]["UnknownBehavior"] = True
    assert _process_only_ability_task_source_blocked_reason(formation, "SetSkillTargetFormationByPos")


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


def test_callback_free_monster_projectile_is_only_a_visual_wait():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    raw = json.loads((root / 'Config/ConfigAbility/Monster/Monster_W1_Soldier02_00_Ability.json').read_text())
    phase = next(a for a in raw['AbilityList'] if a['Name'] == 'Monster_W1_CWSoldier_02_Skill02_Phase02')
    projectile = next(t for t in phase['OnStart'] if t['$type'] == 'RPG.GameCore.FireProjectile')
    stop = next(t for t in phase['OnStart'] if t['$type'] == 'RPG.GameCore.StopAim')
    assert not _process_only_ability_task_source_blocked_reason(stop, 'StopAim')
    assert not _process_only_ability_task_source_blocked_reason(projectile, 'FireProjectile')
    for changed in (
        {**projectile, 'OnProjectileHit': []}, {**projectile, 'WaitProjectileFinish': False},
        {**projectile, 'Projectile': {**projectile['Projectile'], 'ColliderTemplate': 'unknown'}},
        {**projectile, 'Projectile': {**projectile['Projectile'], 'UnknownBehavior': 1}},
    ):
        assert _process_only_ability_task_source_blocked_reason(changed, 'FireProjectile')


def test_bleed_creation_reuses_property_reads_and_retires_only_visual_children():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_callback_task_admission
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    raw = json.loads((root / 'Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json').read_text())
    modifier = raw['ModifierMap']['MCommon_DOT_Tear']
    tasks = next(c['CallbackConfig'] for c in modifier['_CallbackList'] if c['Event'] == 'OnCreate')
    assert _status_callback_task_admission('OnCreate', 'SetDynamicValueByProperty', tasks[1],
                                           source_modifier_name='MCommon_DOT_Tear') == ('executable', '')
    assert _status_callback_task_admission('OnCreate', 'SetDynamicValueByProperty', tasks[2],
                                           source_modifier_name='MCommon_DOT_Tear') == ('executable', '')
    assert _status_callback_task_admission('OnCreate', 'AddBuffPerform', tasks[0])[1] == 'source_proven_presentation_only'
    bad = deepcopy(tasks[0])
    bad['TaskList'].append(tasks[1])
    assert _status_callback_task_admission('OnCreate', 'AddBuffPerform', bad)[1] == 'presentation_task_has_gameplay_or_unknown_child'
    bad = deepcopy(tasks[0])
    bad['TargetType']['UnknownBehavior'] = True
    assert _status_callback_task_admission('OnCreate', 'AddBuffPerform', bad)[1] == 'presentation_task_has_gameplay_or_unknown_child'
    for field in ('root', 'ReadTargetType'):
        bad = deepcopy(tasks[1])
        (bad if field == 'root' else bad[field])['UnknownBehavior'] = True
        assert _status_callback_task_admission('OnCreate', 'SetDynamicValueByProperty', bad)[1] == 'dynamic_property_source_shape_not_admitted'


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


def test_standalone_trigger_excludes_only_resolved_camera_definition(selector_fixture):
    _, _, _, lowerer = selector_fixture
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    _, phases, tasks, effects, *_ = lowerer._lower_standalone_ability_graphs([
        root / "Config/ConfigAbility/Avatar/Avatar_Natasha_00_Ability.json",
    ])
    phase = next(p for p in phases if p.ability_name == "Avatar_Natasha_00_Rank01_InsertSkill_Phase01")
    calls = [t for t in tasks if t.phase_id == phase.phase_id and t.opcode == "TriggerAbility"]
    effect_by_id = {effect.effect_id: effect for effect in effects}
    camera = next(t for t in calls if effect_by_id[t.effect_id].payload["standard"]["ability_name"].endswith("Camera_Self"))
    heal = next(t for t in calls if t is not camera)
    assert camera.execution_mode == "process_only" and camera.coverage_status == "audit_only"
    assert effect_by_id[camera.effect_id].payload["client_only_ability_source"]["source_path"] == (
        "Config/ConfigAbility/Avatar/Camera/Avatar_Natasha_00_Camera.json"
    )
    assert heal.execution_mode == "runtime_effect" and heal.coverage_status == "executable"


def test_healing_action_uses_character_selection_source(selector_fixture):
    from hsr.simulator_v8_clean_core.tbgd.action_target_contracts import build_action_target_contract_catalog
    from hsr.simulator_v8_clean_core.tbgd.lowering import _lower_action_execution_ir

    _, _, _, lowerer = selector_fixture
    definition = next(d for d in lowerer._lower_action_definitions(
        action_ids=frozenset({"avatar_skill:110502"}),
    ) if d.level == 1)
    catalog = build_action_target_contract_catalog(
        lowerer.tbgd_root, definitions=[definition],
        snapshot=lowerer._character_ability_raw_snapshot,
        source_graph_catalog=lowerer.build_character_ability_source_graph_catalog(),
        definition_scope_complete=False,
    )
    binding, phases, lowered = lowerer._avatar_action_binding(definition)
    events, profiles = _lower_action_execution_ir([definition], [binding], phases, [], [], catalog)
    assert not profiles
    assert events[0].target_relation == "ally_or_self"
    assert events[0].target_mode == "self_or_team"
    assert not events[0].blocked_reason
    assert all(step.phase not in {"before_attack", "after_attack"} for step in events[0].phase_steps)
    camera_branch = next(t for t in lowered.ability_tasks
                         if t.opcode == "PredicateTaskList" and t.ability_name.endswith("Phase01"))
    assert camera_branch.execution_mode == "process_only" and not camera_branch.condition_id
    assert next(e for e in lowered.effects if e.effect_id == camera_branch.effect_id).payload[
        "process_only_contract"
    ]["classification"] == "client_only_ability_branch"
    assert all(t.execution_mode == "runtime_effect" for t in lowered.ability_tasks
               if t.opcode == "PredicateTaskList" and t.ability_name.endswith("Phase02"))


def test_healing_visual_effects_and_voice_reject_nested_gameplay():
    from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    raw = json.loads((root / "Config/ConfigAbility/Avatar/Avatar_Natasha_00_Ability.json").read_text())
    families = {"TriggerEffect", "CharacterPlayVO", "SetNoShadowCaster",
                "SyncCharLightAndCameraDir", "TriggerUINotify", "StartAim"}
    found = []

    def walk(value):
        if isinstance(value, dict):
            if str(value.get("$type", "")).split(".")[-1] in families:
                found.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(raw)
    assert {t["$type"].split(".")[-1] for t in found} == families
    for task in found:
        opcode = task["$type"].split(".")[-1]
        assert ability_task_execution_mode(opcode) == "process_only"
        assert not _process_only_ability_task_source_blocked_reason(task, opcode)
        assert _process_only_ability_task_source_blocked_reason({
            **task, "TaskList": [{"$type": "RPG.GameCore.HealHP"}],
        }, opcode)


def test_serval_visual_mount_and_empty_animation_range_reject_nested_gameplay():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    raw = json.loads((root / "Config/ConfigAbility/Avatar/Avatar_Serval_00_Ability.json").read_text())
    tasks = [t for ability in raw["AbilityList"] for t in ability.get("OnStart", [])]
    effect = next(t for t in tasks if t.get("AttachPoint") == "Origin")
    animation = next(t for t in tasks if t.get("$type") == "RPG.GameCore.TriggerAnimStateWithMove"
                     and t.get("MovingRangeList") == [])
    assert effect["AttachPoint"] == "Origin"
    assert animation["MovingRangeList"] == []
    hide = [t for t in tasks if t.get("$type") == "RPG.GameCore.HideLevelStage"]
    assert len(hide) == 2
    for task in (effect, animation, *hide):
        opcode = task["$type"].split(".")[-1]
        assert not _process_only_ability_task_source_blocked_reason(task, opcode)
        assert _process_only_ability_task_source_blocked_reason({
            **task, "TaskList": [{"$type": "RPG.GameCore.HealHP"}],
        }, opcode)


@pytest.mark.parametrize('gender', ['Boy', 'Girl'])
def test_memory_skill_optional_mission_event_condition_closes_real_source_alias(selector_fixture, gender):
    from hsr.simulator_v8_clean_core.ir_types import IRSource

    _, _, _, lowerer = selector_fixture
    relative = f"Config/ConfigAbility/Avatar/Avatar_Player{gender}_30_Ability.json"
    document = json.loads((lowerer.tbgd_root / relative).read_text())
    index, ability, task_index, task = next(
        (i, ability, j, task) for i, ability in enumerate(document['AbilityList'])
        for j, task in enumerate(ability.get('OnStart', ()))
        if task.get('Predicate', {}).get('TargetType', {}).get('Alias') == 'BattleEvent60021')
    source = IRSource(relative, 'AbilityTask', ability['Name'],
        {'json_path': f'$.AbilityList[{index}].OnStart[{task_index}]'})
    # The Boy document scopes its own TargetSequence alias; the Girl document
    # declares none and resolves the same name through the canonical
    # BattleEventConfig row 60021 registration. Neither path may be granted by
    # syntax alone: the registered definition is the source of the admission.
    registry = document.get('GlobalTargetAlias') or {}
    condition = lowerer._lower_ability_task_condition(
        task['Predicate'], source, f'component:optional-event:{gender}',
        target_alias_registry=registry,
    )
    assert condition is not None and condition.coverage_status == 'executable', condition.to_json()
    assert condition.payload['TargetType'].payload['alias'] == 'BattleEvent60021'
    definitions = [item for item in lowerer._strict_target_language_definitions()
                   if item.definition_kind == 'alias' and item.name == 'BattleEvent60021']
    if gender == 'Boy':
        assert 'BattleEvent60021' in registry
    else:
        assert 'BattleEvent60021' not in registry
        canonical = [item for item in definitions
                     if item.source.source_path == 'ExcelOutput/BattleEventConfig.json']
        assert len(canonical) == 1
        assert canonical[0].source.raw_id == '60021'
        assert canonical[0].expression.expression_kind == 'EventDefinitionReference'
    unknown = deepcopy(task['Predicate'])
    unknown['TargetType']['Alias'] = 'UnregisteredOptionalEvent'
    missing = lowerer._lower_ability_task_condition(
        unknown, source, f'component:unknown-event:{gender}',
        target_alias_registry=registry,
    )
    assert missing is None or missing.coverage_status != 'executable'


def test_serval_passive_keeps_whole_retarget_and_shared_damage_source(selector_fixture):
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_callback_task_admission
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
        _DefinitionIndexes, _formal_source, _node_status, _references, _status_task,
    )
    from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language

    _, _, _, lowerer = selector_fixture
    relative = "Config/ConfigAbility/Avatar/Avatar_Serval_00_Ability.json"
    raw = json.loads((lowerer.tbgd_root / relative).read_text())
    index, ability = next((i, a) for i, a in enumerate(raw["AbilityList"])
                          if "Avatar_Serval_Passive01Modifier" in a.get("Modifiers", {}))
    modifier = "Avatar_Serval_Passive01Modifier"
    config = ability["Modifiers"][modifier]["_CallbackList"][0]["CallbackConfig"]
    lowered = lowerer._lower_status_callback_tasks(
        config, relative=relative, map_name="Modifiers", modifier_name=modifier,
        callback_id="test:serval-passive", event="OnAfterAttack", callback_index=0,
        task_list_json_path=f"$.AbilityList[{index}].Modifiers.{modifier}._CallbackList[0].CallbackConfig",
        queue_priority_lookup={}, formal_source_context=lowerer._character_formal_task_source_context(),
    )
    tasks = lowered.status_callback_tasks
    retarget = next(t for t in tasks if t.opcode == "Retarget")
    expression = next(e for e in lowered.target_expressions if e.target_expression_id == retarget.target_expression_id)
    expression = close_target_expression_language(expression, lowerer._strict_target_language_definitions())
    assert expression.coverage_status == "executable" and expression.node.expression_kind == "Retarget"
    assert expression.node.by_random and expression.node.predicate.opcode == "ByContainBehaviorFlag"
    assert not expression.node.max_number_expr
    damage = next(t for t in tasks if t.opcode == "DamageByAttackProperty")
    assert damage.coverage_status == "executable" and not damage.blocked_reason
    emission = next(e for e in lowered.status_damage_emissions if e.source_task_id == damage.task_id)
    assert emission.coverage_status == "executable" and emission.damage_formula_family == "additional"
    control = next(c for c in lowerer._character_formal_task_source_context_cache.control_by_location.values()
                   if c.source.source_path == retarget.source.source_path
                   and c.source.evidence["json_path"] == retarget.source.evidence["json_path"])
    formal = _status_task(retarget)
    source = _formal_source(formal, {formal.source.source_path: control.source.evidence['content_sha256']})
    references = _references(formal, control, 'test:node', source, _DefinitionIndexes(
        {c.condition_id: (c,) for c in lowered.conditions},
        {expression.target_expression_id: (expression,)}, {}, {},
    ), {})
    assert _node_status(control, formal, references) == (
        "target_scope", "materialized", ("task_graph_execution",), "",
    )
    deferred = tuple(replace(ref, resolution_status='deferred', blocked_reason='target_not_admitted')
                     for ref in references)
    assert _node_status(control, formal, deferred)[0:2] == ('deferred', 'deferred')
    finish = next(t for t in tasks if t.opcode == "DamagePerformFinish")
    assert finish.blocked_reason == "source_proven_presentation_only"
    effect = next(e for e in lowered.effects if e.effect_id == finish.effect_id)
    assert effect.coverage_status == "audit_only" and effect.source == finish.source
    assert _status_callback_task_admission("OnAfterAttack", "DamagePerformFinish", {
        "$type": "RPG.GameCore.DamagePerformFinish", "SkipDeathSettlement": True,
    })[0] == "blocked"


def test_local_after_attack_is_not_repeated_by_each_target_listener():
    from hsr.simulator_v8_clean_core.core.model import GameEvent
    from hsr.simulator_v8_clean_core.systems.event_dispatch import _event_aliases
    from hsr.simulator_v8_clean_core.tbgd.lowering import _lower_status_event_families
    from hsr.simulator_v8_clean_core.rules.ir import IRSource, StatusCallbackIR

    callbacks = [StatusCallbackIR("test:" + event, "synthetic:passive", event, (),
                                 IRSource("synthetic:callback", "test", event), (0, 0))
                 for event in ("OnAfterAttack", "OnListenAfterAttack")]
    rules = RuleBook(CanonicalIR(version="test:after-attack", status_callbacks=tuple(callbacks),
                                status_event_families=tuple(_lower_status_event_families(callbacks, []))))
    for event_type, window, expected in (
        ("action.window.after_attack", "OnAfterAttack", {"OnAfterAttack"}),
        ("action.after_attack", "OnListenAfterAttack", {"OnListenAfterAttack"}),
    ):
        event = GameEvent(event_type, source_id="actor", target_id="enemy", window=window)
        assert {alias.callback_event for alias in _event_aliases(event, rules)} == expected


def test_serval_ultimate_retarget_uses_formal_target_scope(selector_fixture):
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
        _DefinitionIndexes, _ability_task, _formal_source, _node_status, _references,
    )
    from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language

    _, _, _, lowerer = selector_fixture
    definition = next(d for d in lowerer._lower_action_definitions(
        action_ids=frozenset({"avatar_skill:110303"}),
    ) if d.level == 1)
    _, _, lowered = lowerer._avatar_action_binding(definition)
    for task in (t for t in lowered.ability_tasks if t.opcode == "Retarget"):
        assert task.coverage_status == "executable" and not task.effect_id
        formal = _ability_task(task)
        expression = next(e for e in lowered.target_expressions
                          if e.target_expression_id == formal.target_expression_id)
        expression = close_target_expression_language(expression, lowerer._strict_target_language_definitions())
        assert expression.coverage_status == "executable" and expression.node.expression_kind == "Retarget"
        control = lowerer._character_formal_task_source_context_cache.control_by_location[
            (task.source.source_path, task.source.evidence["json_path"], "Retarget")]
        source = _formal_source(formal, {formal.source.source_path: control.source.evidence['content_sha256']})
        references = _references(formal, control, 'test:node', source, _DefinitionIndexes(
            {c.condition_id: (c,) for c in lowered.conditions},
            {expression.target_expression_id: (expression,)}, {}, {},
        ), {})
        assert _node_status(control, formal, references)[0:2] == ("target_scope", "materialized")
    extension = next(e for e in lowered.effects if e.opcode == "SetModifierValueByBehaviorFlag")
    assert extension.coverage_status == "executable"
    assert extension.payload["standard"]["operation"] == "extend_modifier_lifetime"


@pytest.mark.parametrize('avatar', ['Natasha', 'Mar_7th'])
def test_single_projectile_keeps_hit_tasks_and_blocks_async_or_collision_shapes(avatar):
    from hsr.simulator_v8_clean_core.tbgd.lowering import _effect_payload, _effect_coverage_status

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    raw = json.loads((root / f"Config/ConfigAbility/Avatar/Avatar_{avatar}_00_Ability.json").read_text())
    projectile = next(task for ability in raw["AbilityList"] for task in ability.get("OnStart", [])
                      if task.get("$type") == "RPG.GameCore.FireProjectile")
    payload = _effect_payload(projectile, "FireProjectile", "")
    assert _effect_coverage_status("FireProjectile", payload) == "executable"
    assert payload["OnProjectileHit"] == projectile["OnProjectileHit"]
    for changed in (
        {**projectile, "WaitProjectileFinish": False},
        {**projectile, "Projectile": {**projectile["Projectile"], "IgnoreTargetHitbox": False}},
        {**projectile, "OnProjectileMiss": []},
        {**projectile, "Projectile": {**projectile["Projectile"], "FlySpeed": {"FixedValue": {"Value": 0}}}},
    ):
        assert _effect_coverage_status("FireProjectile", _effect_payload(changed, "FireProjectile", "")) == "blocked"


@pytest.mark.parametrize('gender', ['Boy', 'Girl'])
def test_selected_trace_projectile_keeps_real_hit_branch_and_rejects_other_outcomes(gender):
    from hsr.simulator_v8_clean_core.tbgd.lowering import _effect_payload, _effect_coverage_status
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import _is_single_projectile_impact_shape
    from types import SimpleNamespace

    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    path = root / f'Config/ConfigAbility/Avatar/Avatar_Player{gender}_30_Ability.json'
    data = json.loads(path.read_text())
    projectile = next(task for ability in data['AbilityList'] for task in ability.get('OnStart', [])
                      if task.get('$type') == 'RPG.GameCore.NewFireProjectile')
    payload = _effect_payload(projectile, 'NewFireProjectile', '')
    assert _effect_coverage_status('NewFireProjectile', payload) == 'executable', payload['standard'].get('blocked_reason', str(payload['standard']))
    assert payload['OnProjectileHit'] == projectile['OnProjectileHit']
    assert payload['NewProjectile'] == projectile['NewProjectile']
    assert payload['standard']['completion_branch'] == 'projectile_hit'
    control = SimpleNamespace(family='NewFireProjectile', control_role='projectile_sequence')
    formal = SimpleNamespace(opcode='NewFireProjectile', family='NewFireProjectile',
                             execution_mode='runtime_effect', coverage_status='executable')
    assert _is_single_projectile_impact_shape(control, formal)
    for changed in (
        {**projectile, 'OnProjectileMiss': []},
        {**projectile, 'WaitProjectileFinish': False},
        {**projectile, 'MaxNumber': {'Value': 2}},
        {**projectile, 'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'AllEnemy'}},
        {**projectile, 'NewProjectile': {**projectile['NewProjectile'], 'IgnoreTargetHitbox': False}},
        {**projectile, 'NewProjectile': {**projectile['NewProjectile'], 'CollisionTaskList': []}},
    ):
        assert _effect_coverage_status('NewFireProjectile',
                                      _effect_payload(changed, 'NewFireProjectile', '')) == 'blocked'


@pytest.mark.parametrize('action_id', ['avatar_skill:800701', 'avatar_skill:800801'])
def test_memory_projectile_formal_parent_keeps_hit_children(selector_fixture, action_id):
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
        _DefinitionIndexes, _ability_task, _formal_source, _node_status, _references,
    )

    _, _, _, lowerer = selector_fixture
    definition = next(d for d in lowerer._lower_action_definitions(action_ids=frozenset({action_id}))
                      if d.level == 1)
    _, _, lowered = lowerer._avatar_action_binding(definition)
    from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _synchronize_effect_target_expression_metadata, _readmit_target_closure_effects,
        _readmit_target_closure_tasks,
    )
    targets = [close_target_expression_language(expression, lowerer._strict_target_language_definitions())
               for expression in lowered.target_expressions]
    synchronized = _synchronize_effect_target_expression_metadata(lowered.effects, targets)
    readmitted, ids = _readmit_target_closure_effects(synchronized)
    tasks = _readmit_target_closure_tasks(lowered.ability_tasks, ids)
    parents = tuple(t for t in tasks if t.opcode == 'NewFireProjectile')
    assert parents
    effects = {effect.effect_id: (effect,) for effect in readmitted}
    for task in parents:
        assert task.coverage_status == 'executable' and task.execution_mode == 'runtime_effect', (task.blocked_reason, task.execution_mode, effects[task.effect_id][0].payload['standard'])
        assert not task.child_task_ids  # Legacy topology is deliberately empty.
        hit_path = task.source.evidence['json_path'] + '.OnProjectileHit['
        assert any(child.opcode == 'DamageByAttackProperty'
                   and child.source.evidence['json_path'].startswith(hit_path)
                   for child in tasks)
        formal = _ability_task(task)
        control = lowerer._character_formal_task_source_context_cache.control_by_location[
            (task.source.source_path, task.source.evidence['json_path'], 'NewFireProjectile')]
        assert len(control.branches) == 1 and control.branches[0].branch_kind == 'projectile_hit'
        assert control.branches[0].children
        source = _formal_source(formal, {formal.source.source_path: control.source.evidence['content_sha256']})
        references = _references(formal, control, 'test:projectile', source,
                                 _DefinitionIndexes({}, {}, effects, {}), {})
        assert _node_status(control, formal, references)[0:2] == ('sequence', 'materialized')


def test_voice_only_retarget_is_excluded_but_healing_child_is_kept(selector_fixture):
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason

    _, _, _, lowerer = selector_fixture
    definition = next(d for d in lowerer._lower_action_definitions(
        action_ids=frozenset({"avatar_skill:110502"}),
    ) if d.level == 1)
    _, _, lowered = lowerer._avatar_action_binding(definition)
    task = next(t for t in lowered.ability_tasks if t.opcode == "Retarget")
    assert task.execution_mode == "process_only" and task.coverage_status == "audit_only"
    raw = json.loads((lowerer.tbgd_root / task.source.source_path).read_text())
    phase = next(p for p in raw["AbilityList"] if p["Name"] == task.ability_name)
    retarget = next(t for t in phase["OnStart"] if t["$type"] == "RPG.GameCore.Retarget")
    assert not _process_only_ability_task_source_blocked_reason(retarget, "Retarget")
    with_heal = {**retarget, "TaskList": [
        *retarget["TaskList"], {"$type": "RPG.GameCore.HealHP"},
    ]}
    assert _process_only_ability_task_source_blocked_reason(with_heal, "Retarget")
    unknown = {**retarget, "Unknown": True}
    assert _process_only_ability_task_source_blocked_reason(unknown, "Retarget")


def test_turn_heal_uses_shared_effect_and_validated_presentation_admission():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_callback_task_admission

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    raw = json.loads((root / "Config/ConfigAbility/Avatar/Avatar_Natasha_00_Ability.json").read_text())
    tasks = raw["GlobalModifiers"]["MAvatar_Natasha_00_HOT_HPByMaxHP"]["_CallbackList"][0][
        "CallbackConfig"
    ][0]["SuccessTaskList"]
    visual, heal = tasks
    assert _status_callback_task_admission("OnPhase1", "HealHP", heal) == ("executable", "")
    assert _status_callback_task_admission("OnPhase1", "TriggerEffect", visual) == (
        "blocked", "source_proven_presentation_only",
    )
    assert _status_callback_task_admission("OnPhase1", "TriggerEffect", {
        **visual, "UnknownGameplay": True,
    })[1] != "source_proven_presentation_only"


def test_death_barrier_verifies_real_damage_lifecycle_without_new_mutations():
    from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
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
    pending = MutationReducer().apply_all(state, produced.mutations)
    assert pending.units["enemy"].hp == 0 and pending.units["enemy"].lifecycle_status == "limbo"
    waiting = registry.execute(effect, EffectExecutionContext(pending, "actor", effect.effect_id))
    assert waiting.unsupported and not waiting.mutations
    settled = CombatExecutor(RuleBook(CanonicalIR("death-barrier-check"))).commit_eventful_transition(
        state, mutations=produced.mutations, events=produced.events, records=produced.records,
        producer_kind="damage", producer_id="test:death-barrier", actor_id="actor",
    )
    assert not settled.errors, settled.errors
    after = settled.after_state
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

def test_servant_camera_triggers_do_not_block_an_avatar_action_binding(selector_fixture):
    # The ultimate triggers servant camera abilities that live in the servant's
    # camera document. They are presentation graphs, not unresolved gameplay
    # definitions, and the action binding stays executable.
    _, _, _, lowerer = selector_fixture
    definition = next(
        item for item in lowerer._lower_action_definitions(
            action_ids=frozenset({'avatar_skill:141503'}))
        if item.level == 1
    )
    binding, phases, lowered = lowerer._avatar_action_binding(definition)
    assert binding.coverage_status == 'executable', binding.blocked_reason
    assert binding.blocked_reason == ''
    assert phases and any(phase.coverage_status == 'lowered' for phase in phases)
    # The fixed source still contains Ready_Camera. Its parent VisualPrepare is
    # excluded as a whole presentation graph, so the child is not expanded into
    # a separate effect by _avatar_action_binding's dependency walk.
    parent_name = 'Servant_CyreneServant_00_Skill01_VisualPrepare'
    parent = next(effect for effect in lowered.effects
                  if effect.payload.get('client_only_ability_source', {}).get('ability_name') == parent_name)
    assert parent.coverage_status == 'audit_only'
    document = json.loads((lowerer.tbgd_root / 'Config/ConfigAbility/Servant/Servant_CyreneServant_00_Ability.json').read_text())
    raw_parent = next(ability for ability in document['AbilityList'] if ability['Name'] == parent_name)
    assert any(task.get('AbilityName', {}).get('Value') == 'Servant_CyreneServant_00_Skill01_Ready_Camera'
               for task in raw_parent['OnStart'])
