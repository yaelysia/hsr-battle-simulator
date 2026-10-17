"""Independent typed damage uses the shared packet path without an action grant."""
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, TargetResolution, UnitState
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR, CanonicalIR, DamageEmissionIR, EffectIR, HitProfileIR, IRSource,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem, _FormalAbilityInvocation
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutionContext
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphQueryResult
from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import _graph


@pytest.mark.parametrize("family", ("direct", "elation"))
def test_unbound_damage_has_real_formula_windows_and_requires_attack_classification(family):
    source = IRSource("validation_fixture/damage", "AbilityTask", "task", {
        "json_path": "$.OnStart[0]", "content_sha256": "c" * 64,
        "source_opcode": "DamageByAttackProperty",
    })
    task = AbilityTaskIR("task", "phase", "standalone_ability:test", 0, "fixture", "OnStart",
                         0, "$.OnStart[0]", "root", "DamageByAttackProperty", source,
                         effect_id="effect", coverage_status="executable")
    profile = HitProfileIR("hit", task.action_id, 0, 0, "selected", numeric_fixed(1), {},
                           numeric_fixed(0), {}, "direct", "Fire", source,
                           coverage_status="executable")
    basis = {"kind": "unit_stat", "unit_ref": "attacker", "stat": "attack",
             "admission_status": "executable", "attack_type": "Insert"}
    formulas = ()
    if family == "elation":
        from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering
        basis = {"kind": "elation_level_base", "elation_point_source": "echo",
                 "admission_status": "executable", "attack_type": "Insert"}
        formulas = tuple(formula for formula in TBGDLowering(
            Path(__file__).resolve().parents[4] / "turnbasedgamedata-main",
        )._lower_elation_mechanics() if formula.coverage_status == "executable")
    emission = DamageEmissionIR("damage", task.action_id, 0, "phase", "task", "hit", "selected",
        family, "Fire", numeric_fixed(1), basis, source, coverage_status="executable",
        toughness_emission_required=False)
    registry = build_engine_rule_registry()
    effect = EffectIR("effect", task.opcode, {},
        replace(source, evidence={**source.evidence, "parent_task_id": ""}), coverage_status="audit_only")
    graph = _graph(task.phase_id, task, references=(("effect", effect.effect_id, "deferred",
        "task_graph_definition_not_admitted:effect:audit_only"),))

    class GraphRules(RuleBook):
        def query_task_graph(self, graph_id):
            return TaskGraphQueryResult("resolved", "graph", (graph_id,), graph, "")

        def query_task_graph_node(self, node_id):
            return TaskGraphQueryResult("resolved", "node", (node_id,), graph.nodes[0], "")

    ir = CanonicalIR("validation", ability_tasks=(task,),
        formulas=formulas,
        damage_formula_rules=registry.damage_formula_rules, damage_route_rules=registry.damage_route_rules,
        resource_rules=registry.resource_rules,
        effects=(effect,),
        hit_profiles=(profile,), damage_emissions=(emission,))
    state = BattleState(units={
        "actor": UnitState("actor", "ally", "fixture", hp=1000, max_hp=1000, attack=100),
        "target": UnitState("target", "enemy", "fixture", hp=100000, max_hp=100000),
    })
    targets = TargetResolution(selected=("target",), legal=("target",), rejected=())
    invocation = _FormalAbilityInvocation("status_nested", "actor", task.action_id, 0, targets)
    rules = GraphRules(ir)
    runtime = AbilityTaskSystem(rules, EffectRegistry())
    def execute(runtime):
        return runtime.task_graph_executor.execute(state, graph, TaskGraphExecutionContext("independent-damage"),
            runtime._formal_task_graph_hooks(invocation=invocation))
    result = execute(runtime)
    assert result.ok, result.errors
    after, mutations, events = result.after_state, result.mutations, result.events
    records = tuple(record.to_json() for record in result.settlement_records)
    assert all(row["payload"].get("ok", True) for row in records if row["record_type"] == "ability_task"), records
    assert after.units["target"].hp < state.units["target"].hp
    assert invocation.hit_target_ids == ["target"]
    assert not any(event.event_type.startswith("action.window") for event in events)
    assert after.skill_points == state.skill_points
    assert after.units["actor"].energy == state.units["actor"].energy
    audit = RuntimeSourceAuditor(rules).validate_execution(tuple(mutations), tuple(records))
    assert audit.ok, audit.to_json()
    if family == "elation":
        from hsr.simulator_v8_clean_core.core.model import GameEvent
        from hsr.simulator_v8_clean_core.rules.ir import StatusCallbackIR, StatusCallbackTaskIR, StatusDamageEmissionIR
        from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem

        callback = StatusCallbackIR("callback", "fixture", "OnAfterAttack", ("status-task",),
                                    source, (0, 0), coverage_status="executable")
        status_task = StatusCallbackTaskIR("status-task", callback.callback_id, "fixture", "OnAfterAttack", 0,
            "$.CallbackConfig[0]", "root", task.opcode, source, coverage_status="executable",
            task_payload={"TargetType": "ParamEntity"})
        status_emission = StatusDamageEmissionIR("status-damage", callback.callback_id, status_task.task_id,
            "fixture", "OnAfterAttack", "Insert", family, "Fire",
            {"elation_percentage": numeric_fixed(1), "elation_point_source": "echo"}, source,
            coverage_status="executable")
        status_rules = RuleBook(replace(ir, status_callbacks=(callback,), status_callback_tasks=(status_task,),
                                       status_damage_emissions=(status_emission,)))
        triggered = StatusCallbackSystem(status_rules)._execute_damage_emissions(
            state, callback, status_task, {"owner_id": "actor", "caster_id": "actor", "instance_id": "fixture"},
            GameEvent("fixture", source_id="actor", target_id="target"), (status_emission,), None,
        )
        assert triggered.ok, triggered.errors
        assert triggered.after_state.units["target"].hp == after.units["target"].hp
        assert RuntimeSourceAuditor(status_rules).validate_execution(triggered.mutations, triggered.records).ok
    missing = replace(emission, scaling_basis_expr={key: value for key, value in basis.items()
                                                   if key != "attack_type"})
    runtime = AbilityTaskSystem(GraphRules(replace(ir, damage_emissions=(missing,))), EffectRegistry())
    failed = execute(runtime)
    assert not failed.ok and failed.after_state == state and not failed.mutations and not failed.rng_events
    assert any("attack_type_binding_missing" in reason for reason in failed.errors)
    corrupted = replace(effect, source=replace(effect.source,
        evidence={**effect.source.evidence, "unmatched_source": True}))
    runtime = AbilityTaskSystem(GraphRules(replace(ir, effects=(corrupted,))), EffectRegistry())
    refused = execute(runtime)
    assert not refused.ok and refused.after_state == state and not refused.mutations and not refused.rng_events
    assert refused.errors == ("task_graph_definition_not_admitted:effect:audit_only",)


def test_compound_queue_formula_keeps_primary_basis_and_both_skill_levels():
    import hashlib
    import json
    import math
    from pathlib import Path
    from hsr.simulator_v8_clean_core.rules.ir import (
        CharacterAbilityDefinitionIR, CharacterDataCardIR, StandaloneAbilityGraphIR,
    )
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hashes
    from hsr.simulator_v8_clean_core.rules.value_binding import resolve_runtime_numeric_expression
    from hsr.simulator_v8_clean_core.tbgd.character_cards import skill_formula_bindings_from_row
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _action_definition_from_row, _bind_character_queue_damage, _dynamic_value_bindings,
        _effect_payload, _lower_standalone_hit_profiles, _skill_param_numeric_binding_source,
        _lower_damage_emissions, _lower_toughness_emissions, _admit_damage_ability_tasks, _damage_tag_registry,
    )

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    path = "Config/ConfigAbility/Avatar/Avatar_Topaz_00_Ability.json"
    raw_bytes = (root / path).read_bytes()
    ability = json.loads(raw_bytes)["AbilityList"][17]
    raw = ability["OnStart"][7]
    config_path = "Config/ConfigCharacter/Avatar/Avatar_Topaz_00_Config.json"
    config = json.loads((root / config_path).read_text())
    skill_path = "ExcelOutput/AvatarSkillConfig.json"
    rows = [(index, row) for index, row in enumerate(json.loads((root / skill_path).read_text()))
            if row.get("SkillID") in (111203, 111204) and row.get("Level") in (1, 2)]
    text_map = json.loads((root / "TextMap/TextMapCHS.json").read_text())
    definitions = [_action_definition_from_row(skill_path, "avatar_skill", "SkillID", index, row)
                   for index, row in rows]
    bindings = [binding for index, row in rows for binding in skill_formula_bindings_from_row(
        relative_path=skill_path, entity_type="avatar_skill", id_key="SkillID", row_index=index,
        row=row, text_map=text_map, skill_to_card={"111203": "card", "111204": "card"})]
    source = IRSource(path, "AbilityList", ability["Name"], {
        "source_id": "source", "source_kind": "character_main", "avatar_id": "1112",
        "json_path": "$.AbilityList[17]", "ability_index": 17,
        "content_sha256": hashlib.sha256(raw_bytes).hexdigest(),
    })
    definition = CharacterAbilityDefinitionIR("ability", "source", "1112", ability["Name"],
        "character_main", source)
    card = CharacterDataCardIR("card", "avatar:1112", "profile", ("111203", "111204"),
        tuple(binding.binding_id for binding in bindings), (), source,
        dynamic_value_bindings=_dynamic_value_bindings(config["DynamicValues"]))
    action = "standalone_ability:" + ability["Name"]
    task = AbilityTaskIR("task", "phase", action, 0, ability["Name"], "OnStart", 7,
        "$.AbilityList[17].OnStart[7]", "root", "DamageByAttackProperty", source,
        effect_id="effect", coverage_status="executable")
    effect = EffectIR("effect", task.opcode, _effect_payload(raw, task.opcode, "", source=source), source)
    graph = StandaloneAbilityGraphIR("graph", ability["Name"], "mainline_avatar", ("phase",),
        (task.task_id,), (task.task_id,), source)
    updated, projected = _bind_character_queue_damage([graph], [task], [effect], bindings,
        definitions, [card], [definition])
    assert updated[0].action_id == "avatar_skill:111204"
    assert len(projected) == 1 and projected[0].scaling_basis_expr["stat"] == "attack"
    assert projected[0].scaling_basis_expr["runtime_skill_param"] is True
    assert {row["action_id"] for row in projected[0].source.evidence["parameter_reads"].values()} == {
        "avatar_skill:111203", "avatar_skill:111204"}
    profiles = _lower_standalone_hit_profiles([task], [effect], projected,
        {action: next(row for row in definitions if row.action_id == updated[0].action_id)})
    assert profiles[0].coverage_status == "executable"
    emissions = _lower_damage_emissions([task], [effect], profiles, projected, _damage_tag_registry(root))
    toughness = _lower_toughness_emissions([task], [effect], profiles, projected)
    admitted = _admit_damage_ability_tasks([task], emissions, toughness, profiles)
    assert admitted[0].coverage_status == "executable", admitted[0].blocked_reason
    expression = profiles[0].multiplier_expr
    assert set(map(str, numeric_dynamic_hashes(expression))) == {"-1900945986", "892461053"}
    for passive_level, ultimate_level, expected in ((1, 1, 1.5), (1, 2, 1.575), (2, 1, 1.575)):
        selected = {row["SkillTriggerKey"]: row for _, row in rows
                    if row["Level"] == (passive_level if row["SkillTriggerKey"] == "SkillP01" else ultimate_level)}
        source_binding, _ = _skill_param_numeric_binding_source(character_config=config,
            skill_row=selected["SkillP01"], skill_trigger_key="SkillP01", character_path=config_path,
            skill_rows_by_trigger_key=selected)
        value = resolve_runtime_numeric_expression(expression, binding_sources=(source_binding,), source_trace={})
        assert value.ok and math.isclose(value.value, expected), value.to_json()
    # A second proven direct-damage basis is ambiguous, even with equal stats.
    extra = replace(projected[0], action_id="avatar_skill:111203", param_index=0,
        level=1, binding_id="ambiguous:1")
    ambiguous, refused = _bind_character_queue_damage([graph], [task], [effect],
        [*bindings, extra, replace(extra, level=2, binding_id="ambiguous:2")], definitions, [card], [definition])
    assert not ambiguous[0].action_id and not refused
