"""已采纳固定技能削韧例外只认 RuleBook 正式发射与 profile。

聚焦组件：真实编译形态（dynamic_hash 表达式 + 已采纳 30 固定 stance）经正式
ToughnessSystem 生产 mutation 后，审计接受 evaluator 记录的 verified_fallback；
只改被审 metadata 的伪造动态载体、错值或错表达式必须拒绝，非 toughness
mutation 也不能借用该例外。不读 TBGD、不建完整规则。
"""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.source_audit import (
    RuntimeSourceAuditor,
    _audit_dynamic_numeric_binding,
)
from hsr.simulator_v8_clean_core.immutable_json import thaw_json
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR,
    CanonicalIR,
    EffectIR,
    HitProfileIR,
    IRSource,
    ToughnessEmissionIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.toughness import ToughnessPacket, ToughnessSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import _toughness_amount_expr

HASH = 1659254037
SOURCE = IRSource("ExcelOutput/AvatarSkillConfig.json", "AvatarSkillConfig", "100801", {})


def _adopted_trace() -> dict:
    """Compiler adopted record for ordinary 30/60/30 old-unit skill data."""

    return {
        "kind": "adopted_mechanism_data",
        "unit": "old_toughness",
        "condition": "fixed single/blast/aoe skill; retain each raw hit's multiplier",
        "raw_path": "ShowStanceList[0]",
        "action_source": {
            "source_path": "ExcelOutput/AvatarSkillConfig.json",
            "raw_type": "AvatarSkillConfig",
            "raw_id": "100801",
            "evidence": {},
        },
        "research_source": "https://srl.keqingmains.com/characters/fire/himeko",
        "research_version": "not specified; ordinary 30/60/30 old-unit skill data",
        "unit_source": (
            "https://github.com/yaelysia/hsr-battle-simulator/blob/"
            "a987d2607f135799a9427c9341ebdf002a1b2c90/"
            "docs/tbgd_evidence/shared/general_weakness_toughness_break_super_break_v1.md"
        ),
    }


def _dynamic_stance_value() -> dict:
    """Raw TBGD shape for a StanceValue that is a single dynamic operand."""

    return {
        "IsDynamic": True,
        "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [HASH]},
    }


def _formal_rulebook(*, fixed_emission: bool = False) -> tuple[
    RuleBook, AbilityTaskIR, HitProfileIR, ToughnessEmissionIR
]:
    task = AbilityTaskIR(
        "task", "phase", "avatar_skill:100801", 1, "Arlan", "OnStart", 0,
        "$.AbilityList[1].OnStart[3]", "main", "DamageByAttackProperty", SOURCE,
        effect_id="effect", coverage_status="executable",
    )
    profile = HitProfileIR(
        "profile", "avatar_skill:100801", 1, 0, "selected", numeric_fixed(1.0), {},
        {
            **numeric_fixed(30.0),
            "dynamic_hash": HASH,
            "show_stance_index": 0,
            "source_kind": "adopted_fixed_skill_toughness",
            "source_trace": _adopted_trace(),
        },
        {"source": _adopted_trace()}, "direct", "Fire", SOURCE,
        coverage_status="executable",
    )
    effect = EffectIR(
        "effect", "Attack",
        {
            "AttackProperty": {"StanceValue": _dynamic_stance_value()},
            "TargetType": "AbilityTargetEntity",
        },
        SOURCE,
    )
    expression = (
        numeric_fixed(30.0)
        if fixed_emission
        else _toughness_amount_expr(effect, profile)
    )
    emission = ToughnessEmissionIR(
        "emission", "avatar_skill:100801", 1, "phase", "task", "profile",
        "selected", "Fire", expression, SOURCE, coverage_status="executable",
    )
    rules = RuleBook(CanonicalIR(
        "component:toughness-adopted-binding",
        ability_tasks=(task,),
        hit_profiles=(profile,),
        toughness_emissions=(emission,),
    ))
    return rules, task, profile, emission


def _produce(
    rules: RuleBook,
    emission: ToughnessEmissionIR,
    *,
    carrier_values: dict | None = None,
    fallback_values: dict | None = None,
):
    """Mirror the formal ability producer's packet binding sources."""

    expression = emission.toughness_amount_expr
    binding_sources: list[dict] = []
    if "binding_source" in expression:
        binding_sources.append({
            "source_type": "action_toughness_parameters",
            "values": (
                dict(expression["binding_source"]["values"])
                if carrier_values is None
                else dict(carrier_values)
            ),
            "source_trace": [expression["binding_source"]["source_trace"]],
        })
        fallback = {
            **expression["binding_source"],
            "binding_role": "compiled_expression_fallback",
        }
        if fallback_values is not None:
            fallback["values"] = dict(fallback_values)
        binding_sources.append(fallback)
    state = BattleState(units={
        "actor": UnitState("actor", "ally", "fixture:attacker", level=80, hp=1000, max_hp=1000),
        "target": UnitState(
            "target", "enemy", "fixture:target", level=80, hp=1000, max_hp=1000,
            toughness=100.0, max_toughness=100.0, flags={"weaknesses": ["Fire"]},
        ),
    })
    packet = ToughnessPacket(
        "actor", "target", emission.toughness_emission_id, emission.source_task_id,
        emission.hit_profile_id, "Fire", None, "selected", "executable",
        SOURCE.to_json(), amount_expr=expression,
        metadata={"value_binding_sources": binding_sources},
    )
    return ToughnessSystem(rules).apply_packet(state, packet)


def _reassociate(produced, change, **fields):
    mutation = produced.mutations[0]
    metadata = thaw_json(mutation.metadata)
    change(metadata)
    changed = replace(mutation, metadata=metadata, **fields)
    records = tuple(
        {**record, "mutation_id": changed.stable_id()}
        if record.get("mutation_id") == mutation.stable_id()
        else record
        for record in produced.records
    )
    return changed, records


def _audit_reasons(rules: RuleBook, produced) -> list[str]:
    result = RuntimeSourceAuditor(rules).validate_execution(produced.mutations, produced.records)
    return [violation.reason for violation in result.violations]


def test_compiled_adopted_dynamic_fallback_is_admitted():
    rules, _, profile, emission = _formal_rulebook()
    assert emission.toughness_amount_expr["kind"] == "dynamic_hash"
    assert emission.toughness_amount_expr["binding_source"]["values"] == {str(HASH): 30.0}
    assert profile.stance_expr["value"] == 30.0
    produced = _produce(rules, emission)
    assert produced.ok, produced.errors
    mutation = produced.mutations[0]
    bindings = mutation.metadata["numeric_evaluation"]["bindings"]
    assert bindings["source_type"] == "action_toughness_parameters"
    assert bindings["key"] == str(HASH) and bindings["value"] == 30.0
    assert bindings["verified_fallback"] == {
        "source_type": "adopted_fixed_skill_toughness",
        "matched_by": "values",
    }
    assert _audit_reasons(rules, produced) == []


def test_fixed_formal_emission_rejects_rewritten_dynamic_carrier():
    rules, _, _, emission = _formal_rulebook(fixed_emission=True)
    assert emission.toughness_amount_expr["kind"] == "fixed"
    produced = _produce(rules, emission)
    assert produced.ok, produced.errors
    # The native fixed emission itself stays admitted; only the rewritten
    # metadata claim is rejected.
    assert _audit_reasons(rules, produced) == []

    def forge(metadata):
        metadata["amount_expr"] = {
            "kind": "dynamic_hash",
            "hash": "invented",
            "binding_source": {
                "source_type": "adopted_fixed_skill_toughness",
                "values": {"invented": 999.0},
                "source_trace": {
                    **_adopted_trace(),
                    "research_source": "https://example.invalid/unadopted",
                },
            },
        }
        metadata["numeric_evaluation"] = {
            **metadata["numeric_evaluation"],
            "expression_kind": "dynamic_hash",
            "bindings": {
                "source_type": "action_toughness_parameters",
                "key": "invented",
                "value": 999.0,
                "verified_fallback": {
                    "source_type": "adopted_fixed_skill_toughness",
                    "matched_by": "values",
                },
            },
        }

    changed, records = _reassociate(produced, forge)
    result = RuntimeSourceAuditor(rules).validate_execution((changed,), records)
    assert not result.ok
    assert "dynamic_numeric_binding_source_not_trusted" in {
        violation.reason for violation in result.violations
    }


def test_wrong_adopted_value_or_expression_is_rejected():
    """Self-consistent metadata claims still lose to the RuleBook IR."""

    rules, _, _, emission = _formal_rulebook()
    produced = _produce(rules, emission)
    assert produced.ok, produced.errors
    mutation = produced.mutations[0]
    fallback = {
        "source_type": "adopted_fixed_skill_toughness",
        "matched_by": "values",
    }

    def reasons_for(change):
        changed, records = _reassociate(produced, change)
        return [
            violation.reason
            for violation in RuntimeSourceAuditor(rules).validate_execution(
                (changed,), records,
            ).violations
        ]

    def wrong_value(metadata):
        claim = 60.0
        metadata["amount_expr"] = {
            **metadata["amount_expr"],
            "binding_source": {
                **metadata["amount_expr"]["binding_source"],
                "values": {str(HASH): claim},
            },
        }
        metadata["numeric_evaluation"] = {
            **metadata["numeric_evaluation"],
            "value": claim,
            "bindings": {
                **metadata["numeric_evaluation"]["bindings"],
                "value": claim,
                "verified_fallback": fallback,
            },
        }

    assert "dynamic_numeric_binding_source_not_trusted" in reasons_for(wrong_value)

    def wrong_expression(metadata):
        claim_hash = 999999
        claim_value = 45.0
        metadata["amount_expr"] = {
            "kind": "dynamic_hash",
            "hash": claim_hash,
            "supported": True,
            "raw_path": "AttackProperty.StanceValue",
            "source_kind": "ability_task_attack_property_stance_value",
            "binding_source": {
                "source_type": "adopted_fixed_skill_toughness",
                "values": {str(claim_hash): claim_value},
                "source_trace": _adopted_trace(),
            },
        }
        metadata["numeric_evaluation"] = {
            **metadata["numeric_evaluation"],
            "value": claim_value,
            "bindings": {
                "hash": claim_hash,
                "key": str(claim_hash),
                "value": claim_value,
                "source_type": "action_toughness_parameters",
                "matched_by": "values",
                "verified_fallback": fallback,
            },
        }

    assert "dynamic_numeric_binding_source_not_trusted" in reasons_for(wrong_expression)

    def wrong_source(metadata):
        metadata["amount_expr"] = {
            **metadata["amount_expr"],
            "binding_source": {
                **metadata["amount_expr"]["binding_source"],
                "source_trace": {
                    **_adopted_trace(),
                    "research_source": "https://example.invalid/unadopted",
                },
            },
        }

    assert "dynamic_numeric_binding_source_not_trusted" in reasons_for(wrong_source)
    # The untouched production still matches the RuleBook IR.
    assert _audit_reasons(rules, produced) == []
    assert mutation.metadata["amount_expr"] == emission.toughness_amount_expr


def test_self_consistent_forged_fallback_still_loses_to_rulebook_value():
    """The evaluator agreeing with a forged carrier is not adopted authority."""

    rules, _, _, emission = _formal_rulebook()
    forged_values = {str(HASH): 60.0}
    produced = _produce(
        rules, emission,
        carrier_values=forged_values, fallback_values=forged_values,
    )
    assert produced.ok, produced.errors
    bindings = produced.mutations[0].metadata["numeric_evaluation"]["bindings"]
    assert bindings["value"] == 60.0
    assert bindings["verified_fallback"] == {
        "source_type": "adopted_fixed_skill_toughness",
        "matched_by": "values",
    }
    assert _audit_reasons(rules, produced) == [
        "dynamic_numeric_binding_source_not_trusted"
    ]


def test_non_toughness_mutation_cannot_borrow_the_exception():
    rules, _, _, emission = _formal_rulebook()
    produced = _produce(rules, emission)
    assert produced.ok, produced.errors

    def forge(metadata):
        metadata["amount_expr"] = {
            "kind": "dynamic_hash",
            "hash": "invented",
            "binding_source": {
                "source_type": "adopted_fixed_skill_toughness",
                "values": {"invented": 999.0},
                "source_trace": {
                    **_adopted_trace(),
                    "research_source": "https://example.invalid/unadopted",
                },
            },
        }
        metadata["numeric_evaluation"] = {
            **metadata["numeric_evaluation"],
            "expression_kind": "dynamic_hash",
            "bindings": {
                "source_type": "action_toughness_parameters",
                "key": "invented",
                "value": 999.0,
                "verified_fallback": {
                    "source_type": "adopted_fixed_skill_toughness",
                    "matched_by": "values",
                },
            },
        }
        metadata["damage_formula_family"] = "break"

    damage, records = _reassociate(
        produced, forge, source="damage_system", path=("units", "target", "hp"),
    )
    reasons = [
        violation.reason
        for violation in RuntimeSourceAuditor(rules).validate_execution(
            (damage,), records,
        ).violations
    ]
    assert "dynamic_numeric_binding_source_not_trusted" in reasons

    violations = []
    _audit_dynamic_numeric_binding(
        damage,
        dict(damage.metadata["numeric_evaluation"]),
        violations,
    )
    assert [violation.reason for violation in violations] == [
        "dynamic_numeric_binding_source_not_trusted"
    ]
