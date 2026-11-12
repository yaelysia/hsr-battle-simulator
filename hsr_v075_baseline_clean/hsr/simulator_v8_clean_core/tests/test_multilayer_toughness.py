"""Real monster layers/common break sources; incoming hits are typed fixtures."""
import json
from pathlib import Path

from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityPhaseIR, AbilityTaskIR, CanonicalIR, EffectIR, HitProfileIR, IRSource, RuleEntity, StatusCallbackIR, ToughnessEmissionIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.break_system import BreakApplicationResult, BreakSystem
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.startup import _passive_runtime_activation
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem
from hsr.simulator_v8_clean_core.systems.toughness import ToughnessPacket, ToughnessSystem
from hsr.simulator_v8_clean_core.systems.toughness_state import read_toughness_segments
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _attach_target_expressions_to_effect_payload, _combatant_profile_from_monster,
    _dedupe_target_expressions, _effect_coverage_status, _effect_payload,
    _link_status_effect_runtime_fields, _lower_status_event_families,
    _modifier_definition_entity, _status_callback_scope_kind, _status_callback_source_admitted,
    _status_callback_source_mode, _synchronize_effect_target_expression_metadata, STATUS_EVENT_RUNTIME_SOURCES,
)
from hsr.simulator_v8_clean_core.tbgd.monster_cards import build_monster_card_ir
from hsr.simulator_v8_clean_core.tbgd.character_ability_scope import build_character_ability_raw_snapshot
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    attach_task_graph_catalog, build_complete_task_graph_catalog,
    materialize_status_callback_task_graph, merge_task_graph_slices,
)


def _component(directory):
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    lowerer = TBGDLowering(root)
    common = "Config/ConfigAbility/Monster/Monster_Common_Ability.json"
    specific = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
    lowered = lowerer._lower_ability_file(root / common, {}, ability_file_order=0)
    lowered.merge(lowerer._lower_ability_file(root / specific, {}, ability_file_order=1))
    avatar_common = "Config/ConfigAbility/Avatar/Avatar_Common_Ability.json"
    # This explicitly projected fixture inventory only satisfies the S0/S1
    # owned/shared assembly contract. Its table row positions are not original
    # evidence. No Arlan card/build is lowered; execution source bytes and the
    # real monster card/template inputs below remain unchanged.
    for table in ("AvatarConfig", "AvatarConfigLD", "AvatarConfigEnhanced", "AvatarServantConfig"):
        path = directory / f"ExcelOutput/{table}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([row for row in json.loads((root / f"ExcelOutput/{table}.json").read_text())
                                   if row.get("AvatarID") == 1008]))
    for relative in (avatar_common, "Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json",
                     "Config/GlobalConfig/TargetAliasConfig.json",
                     "Config/GlobalConfig/TargetOperationConfig.json",
                     "Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json"):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / relative).read_bytes())
    wrapper_lowerer = TBGDLowering(directory)
    snapshot = build_character_ability_raw_snapshot(directory)
    source_catalog = wrapper_lowerer.build_character_control_flow_contract_catalog(snapshot=snapshot)
    break_sources = wrapper_lowerer._lower_break_templates()
    name = "TriggerStanceCountDown_Monster"
    modifier = json.loads((root / avatar_common).read_text())["GlobalModifiers"][name]
    raw_callback = modifier["_CallbackList"][0]
    callback_path = f"$.GlobalModifiers.{name}._CallbackList[0]"
    wrapper = wrapper_lowerer._lower_status_callback_tasks(raw_callback["CallbackConfig"],
        relative=avatar_common, map_name="GlobalModifiers", modifier_name=name,
        callback_id="component:countdown-callback", event=raw_callback["Event"], callback_index=0,
        task_list_json_path=callback_path + ".CallbackConfig", queue_priority_lookup={},
        source_context={"json_path": f"$.GlobalModifiers.{name}", "modifier_callback_index": 0,
                        "callback_json_path": callback_path},
        formal_source_context=wrapper_lowerer._character_formal_task_source_context())
    admitted = (_status_callback_source_admitted(avatar_common)
        and raw_callback["Event"] in STATUS_EVENT_RUNTIME_SOURCES
        and any(task.coverage_status == "executable" for task in wrapper.status_callback_tasks))
    status = "executable" if admitted else "blocked"
    callback = StatusCallbackIR("component:countdown-callback", name, raw_callback["Event"],
        tuple(wrapper.status_callback_root_task_ids), IRSource(avatar_common, "GlobalModifiers", name, {
            "json_path": f"$.GlobalModifiers.{name}", "callback_json_path": callback_path,
            "modifier_callback_index": 0, "event": raw_callback["Event"]}), (0, 0),
        coverage_status=status, admission_status=status, scope_kind=_status_callback_scope_kind(raw_callback["Event"]),
        source_mode=_status_callback_source_mode(avatar_common))
    assert admitted
    includes = [task for task in wrapper.status_callback_tasks if task.opcode == "IncludeTaskListTemplate"]
    assert len(includes) == 7 and all(task.task_payload.get("committed_break_template_id") for task in includes)
    lowered.merge(wrapper)
    lowered.status_callbacks.append(callback)
    lowered.entities.append(_modifier_definition_entity(avatar_common, "GlobalModifiers", name, modifier,
        source_context={"json_path": f"$.GlobalModifiers.{name}"}))
    templates, damage, statuses, effects, targets, conditions = break_sources
    card = build_monster_card_ir(root, max_records_per_table=None,
        monster_ids=frozenset({"3025010"})).monster_data_cards[0]
    monster = next(row for row in json.loads((root / "ExcelOutput/MonsterConfig.json").read_text())
                   if row["MonsterID"] == 3025010)
    template = next(row for row in json.loads((root / "ExcelOutput/MonsterTemplateConfig.json").read_text())
                    if row["MonsterTemplateID"] == 3025010)
    profile = _combatant_profile_from_monster("3025010", monster, "3025010", template)
    language = lowerer._strict_target_language_definitions()
    grants = []
    document = json.loads((root / common).read_text())
    for index in (0, 2):
        raw = document["AbilityList"][0]["OnStart"][index]
        source = IRSource(common, "AbilityTask", "Monster_Common_PassiveSkill_StanceBreak_Action", {
            "json_path": f"$.AbilityList[0].OnStart[{index}]", "source_opcode": "AddModifier"})
        effect_id = f"component:common-grant:{index}"
        payload, expressions = _attach_target_expressions_to_effect_payload(
            _effect_payload(raw, "AddModifier", ""), raw, effect_id=effect_id,
            source=source, target_language_definitions=language)
        effects.append(EffectIR(effect_id, "AddModifier", payload, source,
            _effect_coverage_status("AddModifier", payload)))
        grants.append(effect_id)
        targets.extend(expressions)
    targets = list(_dedupe_target_expressions([
        *(close_target_expression_language(row, language) for row in (*lowered.target_expressions, *targets)),
        *(row.expression for row in language)]).values())
    effects = _synchronize_effect_target_expression_metadata(_link_status_effect_runtime_fields(
        [*lowered.effects, *effects], lowered.entities, lowered.status_callbacks,
        lowered.ability_property_watchers), targets)
    # These two hits are explicit component inputs, not a claimed character build.
    tasks, profiles, toughness = [], [], []
    for index, amount in enumerate((450., 90.)):
        source = IRSource("validation_fixture/multilayer_hits", "ToughnessHit", str(index))
        task_id, profile_id = f"component:hit-task:{index}", f"component:hit-profile:{index}"
        tasks.append(AbilityTaskIR(task_id, "component:phase", "component:action", 1,
            "component:incoming-hit", "OnStart", index, f"$.Hits[{index}]", "main",
            "DamageByAttackProperty", source, coverage_status="executable"))
        profiles.append(HitProfileIR(profile_id, "component:action", 1, index, "primary",
            numeric_fixed(0.), {}, numeric_fixed(amount), {}, "direct", "Fire", source,
            coverage_status="executable"))
        toughness.append(ToughnessEmissionIR(f"component:toughness:{index}", "component:action", 1,
            "component:phase", task_id, profile_id, "primary", "Fire", numeric_fixed(amount),
            source, coverage_status="executable"))
    canonical = CanonicalIR("multilayer-source-component",
        character_ability_source_graph_catalog=wrapper_lowerer.build_character_ability_source_graph_catalog(
            snapshot=snapshot, scope_catalog=wrapper_lowerer._character_ability_scope_catalog),
        character_card_scope=(),
        entities=(*lowered.entities, RuleEntity(card.entity_ref, "monster", {}, card.source)),
        monster_data_cards=(card,), combatant_profiles=(profile,),
        ability_phases=(AbilityPhaseIR("component:phase", "component:binding", "component:action", 1,
            "component:incoming-hit", 0, {}, {}, {}, IRSource("validation_fixture/multilayer_hits", "AbilityPhase", "hits"),
            task_ids=tuple(row.task_id for row in tasks), invocation_role="unbound_definition"),),
        ability_tasks=tuple(tasks), hit_profiles=tuple(profiles), toughness_emissions=tuple(toughness),
        effects=tuple(effects), conditions=(*lowered.conditions, *conditions),
        status_callbacks=tuple(lowered.status_callbacks), status_callback_tasks=tuple(lowered.status_callback_tasks),
        status_event_families=tuple(_lower_status_event_families(lowered.status_callbacks, lowered.status_callback_tasks)),
        status_damage_emissions=tuple(lowered.status_damage_emissions), damage_modifiers=tuple(lowered.damage_modifiers),
        action_delay_emissions=tuple(lowered.action_delay_emissions),
        ability_property_watchers=tuple(lowered.ability_property_watchers),
        ability_property_ranges=tuple(lowered.ability_property_ranges), target_expressions=tuple(targets),
        break_templates=tuple(templates), break_damage_emissions=tuple(damage), break_status_emissions=tuple(statuses),
        damage_formula_rules=tuple(lowerer._lower_damage_formula_rules()),
        damage_route_rules=tuple(lowerer._lower_damage_route_rules()),
        break_base_damage=tuple(lowerer._lower_break_base_damage()), timeline_rules=tuple(lowerer._lower_timeline_rules()),
        metadata={"monster_rank_scores": lowerer._monster_rank_scores()})
    snapshot = wrapper_lowerer._character_ability_raw_snapshot
    graph = materialize_status_callback_task_graph(source_catalog, canonical,
        callback_id=callback.callback_id, source_snapshot=snapshot)
    assert len(graph.graphs) == 1, tuple(row.blocked_reason for row in graph.entry_materializations)
    catalog = merge_task_graph_slices(build_complete_task_graph_catalog(source_catalog, snapshot), (graph,))
    return RuleBook(attach_task_graph_catalog(canonical, catalog)), card, profile, grants, callback


def test_real_three_layer_monster_overflows_then_breaks_and_recovers_atomically(tmp_path):
    rules, card, profile, grants, callback = _component(tmp_path)
    final = rules.break_template_for_element("Fire")
    middle = rules.break_template_for_element("Fire", trigger_kind="stance_count_down")
    assert final.trigger_kind == "weakness_break" and middle.trigger_kind == "stance_count_down"
    assert final.source.source_path == middle.source.source_path == (
        "Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json")
    assert not rules.break_status_emissions_for_template(middle.template_id)
    maximum = profile.toughness_profile["max_toughness"]
    assert maximum == 180.
    flags = _passive_runtime_activation(rules, card)["flags"]
    enemy = UnitState("enemy", "enemy", card.entity_ref, level=80, hp=100000, max_hp=100000,
        speed=100, toughness=maximum, max_toughness=maximum, flags={**flags,
            "monster_data_card_id": card.card_id, "monster_rank": card.rank,
            "monster_rank_score": rules.ir.metadata["monster_rank_scores"][card.rank],
            "weaknesses": tuple(profile.weaknesses)})
    assert read_toughness_segments(enemy).maximum_segments == read_toughness_segments(enemy).remaining_segments == 3
    # Only this real source listener is installed on the fixture attacker.
    listener = StatusInstance("component:countdown-listener", "modifier:" + callback.modifier_name,
        callback.modifier_name, "actor", "component:listener", "actor",
        trigger_ids_by_event={callback.event: (callback.callback_id,)}).to_json()
    state = BattleState(units={"enemy": enemy,
        "actor": UnitState("actor", "ally", "fixture:attacker", level=80, hp=1000, max_hp=1000,
            resources={"effect_hit_rate": 100.}, statuses=(listener["status_id"],),
            flags={"damage_type": "Fire", "status_details": [listener]})},
        global_flags={"monster_rank_scores": rules.ir.metadata["monster_rank_scores"]})
    effects, reducer = EffectRegistry(StatusSystem(rules)), MutationReducer()
    for effect_id in grants:
        grant = effects.execute(rules.effect(effect_id), EffectExecutionContext(state, "enemy", effect_id,
            application_instance_id=effect_id))
        assert not grant.unsupported, grant.unsupported
        state = reducer.apply_all(state, grant.mutations)
    before = state
    breaks = BreakSystem(rules, effects)

    def hit(current, index, system=breaks):
        emission = rules.ir.toughness_emissions[index]
        packet = ToughnessPacket("actor", "enemy", emission.toughness_emission_id, emission.source_task_id,
            emission.hit_profile_id, "Fire", (450., 90.)[index], "primary", "executable", emission.source.to_json())
        reduced = ToughnessSystem(rules).apply_packet(current, packet)
        assert reduced.ok, reduced.errors
        candidate = reducer.apply_all(current, reduced.mutations)
        broken = system.enter_if_depleted(candidate, reduced)
        assert broken is not None
        return CombatExecutor(rules).commit_eventful_transition(current,
            mutations=(*reduced.mutations, *broken.mutations), events=(*reduced.events, *broken.events),
            records=(*reduced.records, *broken.records), rng_events=broken.rng_events,
            producer_kind="toughness_system", producer_id=emission.toughness_emission_id,
            actor_id="actor", producer_ok=broken.ok, blocked_reason=",".join(broken.errors),
            dispatched_event_ids=broken.dispatched_event_ids,
            event_normalizations=broken.event_normalizations)

    first = hit(state, 0)
    assert not first.errors, first.errors
    unit = first.after_state.units["enemy"]
    assert read_toughness_segments(unit).remaining_segments == 1 and unit.toughness == 90.
    assert not unit.flags.get("broken") and unit.action_value == state.units["enemy"].action_value
    assert not any(row.get("modifier_name") == "MCommon_Element_Burn" for row in unit.flags.get("status_details", ()))
    assert sum(row.path == ("units", "enemy", "hp") for row in first.mutations) == 2
    assert sum(event.event_type == "toughness.segment_depleted" for event in first.events) == 2
    assert not any(event.event_type == "break.triggered" for event in first.events)
    consumed = [row["payload"] for row in first.records if row["record_type"] == "break_template_already_applied"]
    assert len(consumed) == 2 and all(row["template_id"] == middle.template_id for row in consumed)
    assert len({row["source_mutation_id"] for row in consumed}) == 2
    second = hit(first.after_state, 1)
    assert not second.errors, second.errors
    unit = second.after_state.units["enemy"]
    assert read_toughness_segments(unit).remaining_segments == 0 and unit.toughness == 0 and unit.flags["broken"]
    assert "modifier:StanceBreakState" in unit.statuses and "modifier:MCommon_Element_Burn" in unit.statuses
    assert unit.action_value > first.after_state.units["enemy"].action_value
    assert sum(event.event_type == "break.triggered" for event in second.events) == 1
    # The processor facade must preserve the same overflow, callbacks and RNG;
    # commit skips events already dispatched inside the shared break system.
    from hsr.simulator_v8_clean_core.core.content_hooks import ProcessorServices

    candidate = before
    for index, expected in enumerate((first, second)):
        emission = rules.ir.toughness_emissions[index]
        packet = ToughnessPacket("actor", "enemy", emission.toughness_emission_id, emission.source_task_id,
            emission.hit_profile_id, "Fire", (450., 90.)[index], "primary", "executable", emission.source.to_json())
        services = ProcessorServices(candidate, rules, producer_id="fixture:processor")
        services.apply_toughness(packet)
        hook = services.finish()
        committed = CombatExecutor(rules).commit_eventful_transition(candidate,
            mutations=hook.mutations, events=hook.events, records=hook.records, rng_events=hook.rng_events,
            producer_kind="toughness_system", producer_id=emission.toughness_emission_id,
            actor_id="actor", dispatched_event_ids=hook.dispatched_event_ids,
            event_normalizations=hook.event_normalizations)
        assert not committed.errors, committed.errors
        assert committed.after_state == expected.after_state
        assert committed.rng_events == expected.rng_events
        candidate = committed.after_state
    recovery = breaks.recover_ordinary_before_action(second.after_state, unit_id="enemy")
    assert recovery is not None and recovery.ok, recovery.errors if recovery else None
    unit = recovery.after_state.units["enemy"]
    assert read_toughness_segments(unit).remaining_segments == 3 and unit.toughness == maximum
    assert not unit.flags["broken"] and "modifier:StanceBreakState" not in unit.statuses
    mutations = (*first.mutations, *second.mutations, *recovery.mutations)
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, (*first.records, *second.records, *recovery.records))
    assert audit.ok, audit.to_json()
    assert reducer.replay_snapshot(before, mutations, recovery.after_state.snapshot().to_json()).ok

    failed_system = BreakSystem(rules, effects)
    original, calls = failed_system._apply_break_damage_emission, []

    def fail_second(*args):
        calls.append(1)
        return (BreakApplicationResult(False, args[0], errors=("fixture:second-layer-damage-failed",))
                if len(calls) == 2 else original(*args))

    failed_system._apply_break_damage_emission = fail_second
    failed = hit(before, 0, failed_system)
    assert len(calls) == 2 and failed.errors
    assert failed.after_state == before and not failed.mutations and not failed.rng_events
    assert not failed.dispatched_event_ids
