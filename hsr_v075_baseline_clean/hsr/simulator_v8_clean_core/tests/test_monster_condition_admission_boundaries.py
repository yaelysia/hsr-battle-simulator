"""Component boundaries for monster condition facts and ForceKill admission.

The tests here do not build a rulebook or enter a battle.  Alive/opposing
counting consumes the same unit eligibility authority as every relation
consumer, while ForceKill shape admission is checked by lowering the real
Common_Servant_Forcekill leaf plus explicit component counterexamples.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.condition_state import ConditionOperandRequest
from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator
from hsr.simulator_v8_clean_core.rules.expression_ir import CONDITION_EXPRESSION_NODE_SCHEMA
from hsr.simulator_v8_clean_core.rules.ir import ConditionIR, IRSource
from hsr.simulator_v8_clean_core.systems.condition_state import CommittedConditionFactProvider
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _effect_coverage_status,
    _effect_payload,
)

_ROOT = Path(__file__).resolve().parents[4]
_TBGD = _ROOT / "turnbasedgamedata-main"
_COMMON_SERVANT_FORCEKILL = (
    _TBGD / "Config/ConfigAbility/Common_Additional_Ability.json"
)


def _field_lifecycle(presence: str = "field", admission: str = "executable") -> dict:
    return {
        "admission_status": admission,
        "presence": presence,
        "targetable": True,
        "actionable": True,
        "timeline_admitted": True,
    }


def _summon_unit(
    unit_id: str,
    template_id: str,
    team_side: str,
    *,
    summon_kind: str = "servant",
    presence: str = "field",
    admission: str = "executable",
) -> UnitState:
    return UnitState(
        unit_id,
        "summon",
        template_id,
        flags={
            "summon_kind": summon_kind,
            "team_side": team_side,
            "lifecycle_source": _field_lifecycle(presence, admission),
        },
    )


def _departed_enemy() -> UnitState:
    return UnitState(
        "departed_enemy",
        "enemy",
        "monster:departed",
        flags={
            "departed_sources": [
                {
                    "departure_source_id": "status:departed:effect:departed",
                    "source_status_instance_id": "status:departed",
                    "source_effect_id": "effect:departed",
                    "config_group_name": "fixture",
                    "admission_status": "executable",
                    "source_trace": {
                        "effect_id": "effect:departed",
                        "effect_source": {"fixture": True},
                        "status_instance_id": "status:departed",
                        "status_instance_source": {"fixture": True},
                    },
                }
            ]
        },
    )


def _count_state() -> BattleState:
    return BattleState(
        units={
            "ally": UnitState("ally", "ally", "avatar:1001"),
            "ally_peer": UnitState("ally_peer", "ally", "avatar:1002"),
            "ally_servant": _summon_unit(
                "ally_servant", "servant:ally", "ally"
            ),
            "enemy": UnitState("enemy", "enemy", "monster:enemy"),
            "enemy_servant": _summon_unit(
                "enemy_servant", "monster:enemy-summon", "enemy"
            ),
            "neutral_battle_event": UnitState(
                "neutral_battle_event",
                "summon",
                "battle_event:fixture",
                flags={
                    "system_entity_kind": "battle_event",
                    "entity_type": "battle_event",
                },
            ),
            "removed_enemy": UnitState(
                "removed_enemy", "enemy", "monster:removed",
                lifecycle_status="removed", hp=100.0,
            ),
            "hp0_enemy": UnitState("hp0_enemy", "enemy", "monster:hp0", hp=0.0),
            "limbo_enemy": UnitState(
                "limbo_enemy", "enemy", "monster:limbo",
                lifecycle_status="limbo", hp=100.0,
            ),
            "departed_enemy": _departed_enemy(),
            "off_field_enemy_servant": _summon_unit(
                "off_field_enemy_servant", "monster:off-field", "enemy",
                presence="off_field",
            ),
            "unadmitted_enemy_servant": _summon_unit(
                "unadmitted_enemy_servant", "monster:unadmitted", "enemy",
                admission="pending",
            ),
            # Unselectable is a target gate, not an alive/on-field gate.
            "unselectable_enemy": UnitState(
                "unselectable_enemy", "enemy", "monster:unselectable",
                flags={"unselectable": True},
            ),
        }
    )


def test_alive_opposing_count_uses_formal_team_and_field_lifecycle():
    provider = CommittedConditionFactProvider(None)
    state = _count_state()

    ally_result = provider.resolve(
        state,
        ConditionOperandRequest("relation.alive_opposing_count", ("ally",)),
    )
    # enemy + enemy_servant (team_side=enemy) + unselectable_enemy.
    # ally servant, neutral battle event, removed, hp0, limbo, departed,
    # off-field and unadmitted summons are excluded.
    assert ally_result.status == "resolved"
    assert ally_result.value == 3.0

    enemy_result = provider.resolve(
        state,
        ConditionOperandRequest("relation.alive_opposing_count", ("enemy",)),
    )
    # ally + ally_peer + ally_servant (team_side=ally).
    assert enemy_result.status == "resolved"
    assert enemy_result.value == 3.0

    # A servant subject also reads its formal team_side, not its side field.
    servant_result = provider.resolve(
        state,
        ConditionOperandRequest(
            "relation.alive_opposing_count", ("ally_servant",)
        ),
    )
    assert servant_result.status == "resolved"
    assert servant_result.value == 3.0


def test_compare_alive_enemy_number_consumer_uses_the_formal_count():
    condition = ConditionIR(
        "test:alive-opposing-count",
        "ByCompareAliveEnemyNumber",
        {
            "TargetType": {"alias": "Caster"},
            "CompareType": "Equal",
            "CompareValue": {"kind": "fixed", "value": 3.0},
        },
        IRSource("fixture", "ByCompareAliveEnemyNumber", "test"),
        "executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )
    result = RuleEvaluator().evaluate_condition_result(
        condition,
        EvaluationContext(
            state=_count_state(),
            actor_id="ally",
            committed_condition_provider=CommittedConditionFactProvider(None),
        ),
    )
    assert result.ok, result.to_json()
    assert result.result is True
    assert result.details["actual"] == 3.0


def _force_kill(alias: str = "Caster", **fields: object) -> dict:
    return {
        "$type": "RPG.GameCore.ForceKill",
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": alias},
        **fields,
    }


def test_real_common_servant_forcekill_leaf_admits_formal_forced_death():
    document = json.loads(_COMMON_SERVANT_FORCEKILL.read_text(encoding="utf-8"))
    leaf = document["AbilityList"][0]["OnStart"][0]
    assert leaf["$type"] == "RPG.GameCore.ForceKill"

    payload = _effect_payload(leaf, "ForceKill", "")
    standard = payload["standard"]
    assert standard["operation"] == "formal_forced_death"
    assert standard["target_alias"] == "AbilityTargetEntity"
    assert standard["abort_unused_insert_ability"] is True
    assert standard["mute_hp_change"] is False
    assert standard["mute_all_trigger_death"] is False
    assert standard["source_shape_admitted"] is True
    assert _effect_coverage_status("ForceKill", payload) == "executable"


@pytest.mark.parametrize(
    ("fields", "operation", "coverage"),
    [
        # Complete non-muted shapes: both mute flags absent or explicit false.
        ({"AbortUnusedInsertAbility": True}, "formal_forced_death", "executable"),
        (
            {
                "AbortUnusedInsertAbility": True,
                "MuteHpChange": False,
                "MuteAllTriggerDeath": False,
            },
            "formal_forced_death",
            "executable",
        ),
        # A single declared mute or a non-bool value must not collapse into the
        # non-muted executable shape.
        (
            {"AbortUnusedInsertAbility": True, "MuteHpChange": True},
            "muted_unit_retirement",
            "blocked",
        ),
        (
            {"AbortUnusedInsertAbility": True, "MuteAllTriggerDeath": True},
            "muted_unit_retirement",
            "blocked",
        ),
        (
            {"AbortUnusedInsertAbility": True, "MuteHpChange": 0},
            "muted_unit_retirement",
            "blocked",
        ),
        (
            {"AbortUnusedInsertAbility": True, "MuteAllTriggerDeath": 0},
            "muted_unit_retirement",
            "blocked",
        ),
        # The retired double-mute shape stays executable with absent/false
        # abort, but the unimplemented abort-cleanup combination is rejected.
        (
            {"MuteHpChange": True, "MuteAllTriggerDeath": True},
            "muted_unit_retirement",
            "executable",
        ),
        (
            {
                "MuteHpChange": True,
                "MuteAllTriggerDeath": True,
                "AbortUnusedInsertAbility": False,
            },
            "muted_unit_retirement",
            "executable",
        ),
        (
            {
                "MuteHpChange": True,
                "MuteAllTriggerDeath": True,
                "AbortUnusedInsertAbility": True,
            },
            "muted_unit_retirement",
            "blocked",
        ),
        (
            {
                "MuteHpChange": 1,
                "MuteAllTriggerDeath": True,
                "AbortUnusedInsertAbility": True,
            },
            "muted_unit_retirement",
            "blocked",
        ),
        (
            {
                "MuteHpChange": True,
                "MuteAllTriggerDeath": True,
                "AbortUnusedInsertAbility": 0,
            },
            "muted_unit_retirement",
            "blocked",
        ),
        # An unknown behavior field is not dropped just because the known
        # fields happen to form the non-muted shape.
        (
            {"AbortUnusedInsertAbility": True, "DeathSource": "Escape"},
            "muted_unit_retirement",
            "blocked",
        ),
    ],
)
def test_force_kill_admits_only_complete_source_shapes(fields, operation, coverage):
    payload = _effect_payload(_force_kill(**fields), "ForceKill", "")
    standard = payload["standard"]
    assert standard["operation"] == operation
    assert _effect_coverage_status("ForceKill", payload) == coverage
    if coverage == "blocked":
        assert standard["blocked_reason"]


def test_force_kill_keeps_alias_boundary_outside_the_admitted_pair():
    payload = _effect_payload(
        _force_kill("ModifierOwnerEntity", AbortUnusedInsertAbility=True),
        "ForceKill",
        "",
    )
    assert _effect_coverage_status("ForceKill", payload) == "blocked"
