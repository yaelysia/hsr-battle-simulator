from __future__ import annotations

import json
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource, RuleEntity
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _attach_target_expressions_to_effect_payload,
    _modifier_definition_entity, _standard_add_modifier_payload,
    _standard_remove_modifier_payload, _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import (
    build_target_language_definitions, close_target_expression_language,
)

ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"


@lru_cache(maxsize=1)
def _sources():
    lowering = TBGDLowering(ROOT)
    common = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
    raw = json.loads((ROOT / common).read_text())["ModifierMap"]
    endurance = _modifier_definition_entity(
        common, "ModifierMap", "MCommon_Endurance", raw["MCommon_Endurance"],
        source_context={"json_path": "$.ModifierMap.MCommon_Endurance"},
    )
    lynx = lowering._lower_ability_file(
        ROOT / "Config/ConfigAbility/Avatar/Avatar_Lynx_00_Ability.json", {}, ability_file_order=0,
    )
    protection = next(row for row in lynx.entities if row.fields.get("modifier_name") == "MAvatar_Lynx_00_Rank02_Resist")
    callbacks = tuple(row for row in lynx.status_callbacks if row.modifier_name == "MAvatar_Lynx_00_Rank02_Resist")
    return (
        tuple(lowering._lower_status_immunity_rules()), build_target_language_definitions(ROOT),
        endurance, protection, callbacks, raw["MCommon_CTRL_Frozen"]["BehaviorFlagList"],
    )


def _formal_immunity_source(root, relative, avatar_id):
    """Preserve one avatar's source bytes without building combatant content."""
    for table in ("AvatarConfig", "AvatarConfigLD", "AvatarConfigEnhanced", "AvatarServantConfig"):
        rows = [row for row in json.loads((ROOT / f"ExcelOutput/{table}.json").read_text())
                if row.get("AvatarID") == avatar_id]
        path = root / f"ExcelOutput/{table}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
    for name in (relative, "Config/ConfigAbility/Avatar/Avatar_Common_Ability.json",
                 "Config/GlobalConfig/TargetAliasConfig.json", "Config/GlobalConfig/TargetOperationConfig.json",
                 "Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    lowering = TBGDLowering(root)
    source_catalog = lowering.build_character_control_flow_contract_catalog()
    lowered = lowering._lower_ability_file(root / relative, {}, ability_file_order=0,
        formal_status_source_context=lowering._character_formal_task_source_context())
    return lowering, source_catalog, lowered, lowering._strict_target_language_definitions()


def _case(*, grant="Endurance", incoming_flags=(), status_type="Debuff", one_use=False):
    immunity_rules, languages, endurance, lynx, callbacks, _ = _sources()
    if one_use:
        protection = lynx
    elif grant == "Endurance":
        protection = endurance
    else:
        # Other grants are synthetic holders of the exact shared table flag.
        protection = _modifier_definition_entity(
            "fixture/immunity.json", "ModifierMap", "Protection",
            {"BehaviorFlagList": [grant]}, source_context={"json_path": "$.ModifierMap.Protection"},
        )
    incoming = _modifier_definition_entity(
        "fixture/immunity.json", "ModifierMap", "Incoming",
        {"BehaviorFlagList": list(incoming_flags)}, source_context={"json_path": "$.ModifierMap.Incoming"},
    )
    status = RuleEntity(
        "test:incoming_type", "status", {"ModifierName": "Incoming", "StatusType": status_type},
        IRSource("fixture/status.json", "StatusConfig", "test:incoming_type"), "lowered",
    )
    effects = []
    expressions = [row.expression for row in languages]
    for effect_id, opcode, definition in (
        ("grant", "AddModifier", protection), ("incoming", "AddModifier", incoming),
        ("remove", "RemoveModifier", protection),
    ):
        raw = {"$type": f"RPG.GameCore.{opcode}", "ModifierName": {"Value": definition.fields["modifier_name"]}, "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}}
        if effect_id == "incoming" and status_type in {"Buff", "Debuff"}:
            raw["Chance"] = {"IsDynamic": False, "FixedValue": {"Value": 1.0}}
        source = IRSource("fixture/immunity_requests.json", opcode, effect_id, {"json_path": f"$.{effect_id}"})
        standard = _standard_add_modifier_payload(raw) if opcode == "AddModifier" else _standard_remove_modifier_payload(raw, opcode, "")
        payload, targets = _attach_target_expressions_to_effect_payload({"standard": standard}, raw, effect_id=effect_id, source=source)
        targets = [close_target_expression_language(row, languages) for row in targets]
        effect = EffectIR(effect_id, opcode, payload, source, "executable", modifier_definition_id=definition.entity_id, source_mode="mainline")
        if one_use and effect_id == "grant":
            effect = replace(effect, status_callback_ids=tuple(row.callback_id for row in callbacks))
        effects.extend(_synchronize_effect_target_expression_metadata([effect], targets))
        expressions.extend(targets)
    rules = RuleBook(CanonicalIR(
        "test", entities=(*immunity_rules, protection, incoming, status), effects=tuple(effects),
        target_expressions=tuple(expressions), status_callbacks=callbacks if one_use else (),
    ))
    state = BattleState(units={"holder": UnitState(
        "holder", "ally", "test:holder", hp=100.0, max_hp=100.0,
        resources={"effect_hit_rate": 100.0},
    )})
    installed = StatusSystem(rules).apply_add_modifier(state, rules.effect("grant"), caster_id="holder", source_id="test:grant")
    assert installed.ok, installed.unsupported
    return rules, MutationReducer().apply_all(state, installed.mutations)


def _attempt(rules, state):
    return StatusSystem(rules).apply_add_modifier(
        state, rules.effect("incoming"), caster_id="holder", source_id="test:attempt",
    )


def test_real_endurance_blocks_control_until_formal_removal():
    frozen_flags = _sources()[-1]
    rules, state = _case(incoming_flags=frozen_flags)
    before = state.snapshot()
    result = _attempt(rules, state)
    assert result.ok and not result.mutations and not result.rng_events, result.unsupported
    immunity = next(row for row in result.records if row["record_type"] == "status_immunity")
    match = immunity["payload"]["immunity_source"]["shared_immunity_matches"][0]
    assert match["granting_behavior_flag"] == "Endurance"
    assert match["rule_source"]["evidence"]["json_path"].endswith("ModifierBehaviorFlagImmuneMap.Endurance")
    assert state.snapshot() == before
    removed = StatusSystem(rules).apply_remove_modifier(state, rules.effect("remove"), caster_id="holder", source_id="test:remove")
    assert removed.ok, removed.unsupported
    cleared = MutationReducer().apply_all(state, removed.mutations)
    result = _attempt(rules, cleared)
    assert result.ok and result.mutations
    assert not any(row["record_type"] == "status_immunity" for row in result.records)


def test_all_shared_mappings_and_nonmatching_requests():
    rules = _sources()[0]
    assert len(rules) == 11
    for rule in rules:
        flags, types = rule.fields["behavior_flags"], rule.fields["status_types"]
        for status_type in types or ["Debuff"]:
            book, state = _case(grant=rule.fields["granting_behavior_flag"], incoming_flags=flags, status_type=status_type)
            result = _attempt(book, state)
            assert result.ok and not result.mutations and not result.rng_events, (rule.entity_id, result.unsupported)
            assert any(row["record_type"] == "status_immunity" for row in result.records)
    for grant, incoming_flags in (("Endurance", ("STAT_DOT",)), ("ImmuneDot", ("STAT_CTRL",)), ("ImmuneDebuff", ())):
        book, state = _case(grant=grant, incoming_flags=incoming_flags, status_type="Buff")
        result = _attempt(book, state)
        assert result.ok and result.mutations, result.unsupported


def test_consumed_protection_override_and_unknown_type_fail_closed():
    cases = (
        ({"one_use": True}, "status_immunity_callback_order_not_admitted"),
        ({"incoming_flags": ("STAT_CTRL", "STAT_ForceControl")}, "status_immunity_override_order_not_admitted"),
        ({"grant": "ImmuneDebuff", "status_type": "Unknown"}, "status_immunity_application_type_unknown"),
    )
    for kwargs, reason in cases:
        rules, state = _case(**kwargs)
        before = state.snapshot()
        result = _attempt(rules, state)
        assert not result.ok and result.unsupported == (reason,), result.unsupported
        assert not result.mutations and not result.rng_events
        assert state.snapshot() == before


def test_only_installed_grants_and_admitted_rules_are_consumed():
    rules, state = _case(incoming_flags=("STAT_CTRL",))
    unit = state.units["holder"]
    detached = replace(state, units={"holder": replace(unit, statuses=())})
    result = _attempt(rules, detached)
    assert result.ok and result.mutations
    assert not any(row["record_type"] == "status_immunity" for row in result.records)
    for coverage in ("blocked", "audit_only"):
        entities = tuple(
            replace(row, coverage_status=coverage)
            if row.entity_type == "status_immunity_rule" and row.fields["granting_behavior_flag"] == "Endurance"
            else row for row in rules.ir.entities
        )
        blocked = _attempt(RuleBook(replace(rules.ir, entities=entities)), state)
        assert not blocked.ok and not blocked.mutations and not blocked.rng_events
        assert blocked.unsupported == ("status_immunity_rule_not_admitted",)


def test_real_lynx_e2_consumes_protection_through_its_formal_immunity_callback():
    """Real E2 callback and grant; units and the incoming debuff are component inputs."""
    from hsr.simulator_v8_clean_core.core.model import TargetResolution
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry, EffectResult
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _dedupe_target_expressions, _effect_coverage_status, _effect_payload,
        _link_status_effect_runtime_fields, _lower_status_event_families,
    )
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
        attach_task_graph_catalog, materialize_status_callback_task_graph,
    )

    immunity_rules, _, _, _, _, _ = _sources()
    relative = "Config/ConfigAbility/Avatar/Avatar_Lynx_00_Ability.json"
    modifier = "MAvatar_Lynx_00_Rank02_Resist"
    document = json.loads((ROOT / relative).read_text())
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        lowering, source_catalog, lowered, languages = _formal_immunity_source(root, relative, 1110)
        protection = next(row for row in lowered.entities if row.fields.get("modifier_name") == modifier)
        callback = next(row for row in lowered.status_callbacks
                        if row.modifier_name == modifier and row.event == "OnImmuneDebuff")
        tasks = tuple(row for row in lowered.status_callback_tasks if row.callback_id == callback.callback_id)
        assert callback.coverage_status == callback.admission_status == "executable"
        assert all(row.coverage_status == "executable" or row.blocked_reason == "source_proven_presentation_only"
                   for row in tasks)
        incoming = _modifier_definition_entity("fixture/immunity.json", "ModifierMap", "Incoming", {},
            source_context={"json_path": "$.ModifierMap.Incoming"})
        incoming_type = RuleEntity("test:incoming_type", "status", {"ModifierName": "Incoming", "StatusType": "Debuff"},
            IRSource("fixture/status.json", "StatusConfig", "test:incoming_type"), "lowered")
        expressions = [close_target_expression_language(row, languages) for row in lowered.target_expressions]
        expressions.extend(row.expression for row in languages)
        raw_grant = document["AbilityList"][3]["OnStart"][6]["SuccessTaskList"][0]
        assert raw_grant["ModifierName"]["Value"] == modifier
        raw_incoming = {"$type": "RPG.GameCore.AddModifier", "ModifierName": {"Value": "Incoming"},
            "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
            "Chance": {"IsDynamic": False, "FixedValue": {"Value": 1.}}}
        effects = []
        for effect_id, raw, definition, source in (
            ("real:lynx_e2_grant", raw_grant, protection,
             IRSource(relative, "AbilityTask", "real_e2_grant", {
                 "json_path": "$.AbilityList[3].OnStart[6].SuccessTaskList[0]", "source_opcode": "AddModifier"})),
            ("fixture:incoming", raw_incoming, incoming,
             IRSource("fixture/immunity_requests.json", "AddModifier", "incoming", {"json_path": "$.incoming"})),
        ):
            payload, targets = _attach_target_expressions_to_effect_payload(
                _effect_payload(raw, "AddModifier", ""), raw, effect_id=effect_id, source=source,
                target_language_definitions=languages)
            expressions.extend(targets)
            effects.append(EffectIR(effect_id, "AddModifier", payload, source,
                _effect_coverage_status("AddModifier", payload), modifier_definition_id=definition.entity_id))
        effects = _link_status_effect_runtime_fields(effects, [protection, incoming], [callback])
        expressions = list(_dedupe_target_expressions(expressions).values())
        canonical = CanonicalIR("lynx-e2-immunity-component",
            entities=(*immunity_rules, protection, incoming, incoming_type),
            effects=tuple(_synchronize_effect_target_expression_metadata([*lowered.effects, *effects], expressions)),
            conditions=tuple(lowered.conditions), target_expressions=tuple(expressions),
            status_callbacks=(callback,), status_callback_tasks=tasks,
            status_event_families=tuple(_lower_status_event_families([callback], tasks)))
        catalog = materialize_status_callback_task_graph(source_catalog, canonical,
            callback_id=callback.callback_id, source_snapshot=lowering._character_ability_raw_snapshot)
        assert len(catalog.graphs) == 1
        rules = RuleBook(attach_task_graph_catalog(canonical, catalog))

    registry = EffectRegistry(StatusSystem(rules))
    state = BattleState(units={unit_id: UnitState(unit_id, "ally", "fixture:" + unit_id,
        hp=100., max_hp=100., resources={"effect_hit_rate": 100., "effect_resistance": 1.})
        for unit_id in ("lynx", "protected")})
    selected = TargetResolution(selected=("protected",), legal=("protected",), rejected=())
    grant = registry.execute(rules.effect("real:lynx_e2_grant"), EffectExecutionContext(
        state, "lynx", "fixture:grant", target_resolution=selected, current_action_target_id="protected",
        application_instance_id="fixture:grant:protected"))
    assert not grant.unsupported, grant.unsupported
    reducer = MutationReducer()
    protected = reducer.apply_all(state, grant.mutations)
    detail = next(row for row in protected.units["protected"].flags["status_details"] if row["modifier_name"] == modifier)
    assert detail["caster_id"] == "lynx" and detail["owner_id"] == "protected"
    assert not protected.units["lynx"].statuses

    def attempt(current, identity):
        return registry.execute(rules.effect("fixture:incoming"), EffectExecutionContext(
            current, "protected", identity, application_instance_id=identity))

    first = attempt(protected, "fixture:attempt:first")
    assert not first.unsupported and first.mutations and not first.rng_events, first.unsupported
    cleared = reducer.apply_all(protected, first.mutations)
    assert detail["status_id"] not in cleared.units["protected"].statuses
    assert "modifier:Incoming" not in cleared.units["protected"].statuses
    events = [event for event in first.events if event.event_type == "status.immunity"]
    assert len(events) == 1 and events[0].window == "OnImmuneDebuff"
    assert events[0].event_id in first.dispatched_event_ids
    invoked = [event for event in first.events if event.event_type == "status.callback"
               and event.payload.get("callback_id") == callback.callback_id]
    assert len(invoked) == 1 and invoked[0].source_id == "lynx" and invoked[0].target_id == "protected"
    # The next component request explicitly resets resistance so that it can
    # distinguish an absent protection from a normal resistance success.
    unit = cleared.units["protected"]
    cleared = replace(cleared, units={**cleared.units, "protected": replace(unit,
        resources={**unit.resources, "effect_resistance": 0.})})
    second = attempt(cleared, "fixture:attempt:second")
    assert not second.unsupported, second.unsupported
    after = reducer.apply_all(cleared, second.mutations)
    assert "modifier:Incoming" in after.units["protected"].statuses
    assert not any(event.event_type == "status.immunity" for event in second.events)
    audit = RuntimeSourceAuditor(rules).validate_execution(
        (*grant.mutations, *first.mutations, *second.mutations), (*grant.records, *first.records, *second.records))
    assert audit.ok, audit.to_json()

    # Inject one actual consumer failure at the source-backed RemoveModifier
    # leaf; the formal graph and its admission remain the real source graph.
    execute = registry.execute

    def fail_consume(effect, context):
        if effect.opcode == "RemoveModifier":
            return EffectResult(unsupported=("fixture_immunity_consume_failed",))
        return execute(effect, context)

    registry.execute = fail_consume
    snapshot = protected.snapshot()
    failed = attempt(protected, "fixture:attempt:failed")
    assert failed.unsupported and "fixture_immunity_consume_failed" in str(failed.unsupported)
    assert not failed.mutations and not failed.rng_events and not failed.dispatched_event_ids and not failed.events
    assert protected.snapshot() == snapshot
    listener_id = "modifier:fixture_global_immunity_listener"
    other = UnitState("other-listener", "ally", "fixture:listener", statuses=(listener_id,), flags={
        "status_details": [{"instance_id": "fixture:global-immunity", "status_id": listener_id,
            "owner_id": "other-listener", "lifecycle_state": "active",
            "trigger_ids_by_event": {"OnListenImmuneDebuff": ["fixture:unadmitted-global"]}}]})
    guarded = attempt(replace(protected, units={**protected.units, other.unit_id: other}), "fixture:attempt:global-listener")
    assert guarded.unsupported == ("status_immunity_global_listener_not_admitted",)
    assert not guarded.mutations and not guarded.rng_events and not guarded.events and not guarded.dispatched_event_ids


if __name__ == "__main__":
    test_real_endurance_blocks_control_until_formal_removal()
    test_all_shared_mappings_and_nonmatching_requests()
    test_consumed_protection_override_and_unknown_type_fail_closed()
    test_only_installed_grants_and_admitted_rules_are_consumed()
    test_real_lynx_e2_consumes_protection_through_its_formal_immunity_callback()
    print("shared status immunity: 5 checks passed")
