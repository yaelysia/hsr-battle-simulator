"""Runtime contract for the ByIsTeamLocationIndexType condition family.

The condition compares one unit's flags["position"] against the formation
span of its living combat team. These fixtures build the typed IR by hand so
the evaluator contract is checked without going through lowering.
"""
from __future__ import annotations

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.evaluator import (
    EXECUTABLE_CONDITION_OPCODES,
    EvaluationContext,
    RuleEvaluator,
)
from hsr.simulator_v8_clean_core.rules.expression_ir import (
    CONDITION_EXPRESSION_NODE_SCHEMA,
)
from hsr.simulator_v8_clean_core.rules.ir import (
    ConditionIR,
    IRSource,
    TargetExpressionNodeIR,
)

_SOURCE_PATH = "fixture/ConfigAbility/TeamLocationPredicate.json"
_RAW_ID = "fixture:team-location-predicate"
_JSON_PATH = "$.fixture.Predicate"
_MISSING = object()


def _condition_source() -> IRSource:
    return IRSource(
        _SOURCE_PATH,
        "RPG.GameCore.ByIsTeamLocationIndexType",
        _RAW_ID,
        {"json_path": _JSON_PATH},
    )


def _target_expression() -> TargetExpressionNodeIR:
    return TargetExpressionNodeIR.build(
        "TargetAlias",
        IRSource(
            _SOURCE_PATH,
            "RPG.GameCore.TargetAlias",
            _RAW_ID + ":TargetType",
            {"json_path": _JSON_PATH + ".TargetType"},
        ),
        {"alias": "Caster"},
    )


def _condition(
    *,
    team_type: object = "TeamDark",
    index_type: object = "Left",
    include_index_type: bool = True,
) -> ConditionIR:
    payload: dict[str, object] = {
        "TargetType": _target_expression(),
        "TeamType": team_type,
    }
    if include_index_type:
        payload["Type"] = index_type
    return ConditionIR(
        "fixture:team-location-predicate",
        "ByIsTeamLocationIndexType",
        payload,
        _condition_source(),
        "executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )


def _unit(
    unit_id: str,
    side: str,
    position: object = _MISSING,
    *,
    hp: float = 100.0,
    lifecycle_status: str = "active",
) -> UnitState:
    flags = {} if position is _MISSING else {"position": position}
    return UnitState(
        unit_id,
        side,
        f"fixture:{unit_id}",
        lifecycle_status=lifecycle_status,
        hp=hp,
        max_hp=100.0,
        flags=flags,
    )


def _evaluate(condition: ConditionIR, state: BattleState, actor_id: str):
    return RuleEvaluator().evaluate_condition_result(
        condition,
        EvaluationContext(state=state, actor_id=actor_id),
    )


def _three_member_state() -> BattleState:
    return BattleState(
        units={
            "enemy:left": _unit("enemy:left", "enemy", 0),
            "enemy:middle": _unit("enemy:middle", "enemy", 1),
            "enemy:right": _unit("enemy:right", "enemy", 2),
            "ally:outsider": _unit("ally:outsider", "ally", 1),
        }
    )


def test_opcode_is_registered_as_executable():
    assert "ByIsTeamLocationIndexType" in EXECUTABLE_CONDITION_OPCODES


def test_single_unit_is_both_left_and_right():
    state = BattleState(
        units={
            "enemy:solo": _unit("enemy:solo", "enemy", 3),
            "ally:helper": _unit("ally:helper", "ally", 0),
        }
    )
    for index_type in ("Left", "Right", "Max"):
        result = _evaluate(_condition(index_type=index_type), state, "enemy:solo")
        assert result.ok is True, result.to_json()
        assert result.result is True, (index_type, result.to_json())
        assert result.details["team_member_ids"] == ["enemy:solo"]
        assert result.details["team_positions"] == [3]
        assert result.details["target_position"] == 3
        assert result.details["index_type"] == index_type
        assert result.details["team_type"] == "TeamDark"
    medium = _evaluate(_condition(index_type="Medium"), state, "enemy:solo")
    assert (medium.ok, medium.result) == (True, False), medium.to_json()


def test_three_unit_team_classifies_left_medium_right():
    state = _three_member_state()
    left = _evaluate(_condition(index_type="Left"), state, "enemy:left")
    assert (left.ok, left.result) == (True, True), left.to_json()
    middle_as_left = _evaluate(_condition(index_type="Left"), state, "enemy:middle")
    assert (middle_as_left.ok, middle_as_left.result) == (True, False)
    middle = _evaluate(_condition(index_type="Medium"), state, "enemy:middle")
    assert (middle.ok, middle.result) == (True, True), middle.to_json()
    assert middle.details["target_position"] == 1
    assert middle.details["team_member_ids"] == [
        "enemy:left",
        "enemy:middle",
        "enemy:right",
    ]
    assert middle.details["team_positions"] == [0, 1, 2]
    assert middle.details["team_min_position"] == 0
    assert middle.details["team_max_position"] == 2
    left_as_medium = _evaluate(_condition(index_type="Medium"), state, "enemy:left")
    assert (left_as_medium.ok, left_as_medium.result) == (True, False)
    right = _evaluate(_condition(index_type="Right"), state, "enemy:right")
    assert (right.ok, right.result) == (True, True), right.to_json()
    right_as_medium = _evaluate(_condition(index_type="Medium"), state, "enemy:right")
    assert (right_as_medium.ok, right_as_medium.result) == (True, False)


def test_max_alias_matches_the_rightmost_member():
    state = _three_member_state()
    right_max = _evaluate(_condition(index_type="Max"), state, "enemy:right")
    assert (right_max.ok, right_max.result) == (True, True), right_max.to_json()
    middle_max = _evaluate(_condition(index_type="Max"), state, "enemy:middle")
    assert (middle_max.ok, middle_max.result) == (True, False)


def test_missing_index_type_defaults_to_left():
    state = _three_member_state()
    default_left = _evaluate(_condition(include_index_type=False), state, "enemy:left")
    assert (default_left.ok, default_left.result) == (True, True), default_left.to_json()
    assert default_left.details["index_type"] == "Left"
    middle = _evaluate(_condition(include_index_type=False), state, "enemy:middle")
    assert (middle.ok, middle.result) == (True, False)


def test_missing_position_on_teammate_or_target_blocks():
    teammate_missing = BattleState(
        units={
            "enemy:left": _unit("enemy:left", "enemy", 0),
            "enemy:middle": _unit("enemy:middle", "enemy"),
            "enemy:right": _unit("enemy:right", "enemy", 2),
        }
    )
    result = _evaluate(_condition(index_type="Medium"), teammate_missing, "enemy:left")
    assert result.ok is False and result.result is None
    assert "team_location_position_missing" in result.reason
    assert result.details["missing_position_unit_ids"] == ["enemy:middle"]
    for key in ("team_type", "index_type", "target_position", "team_positions", "team_member_ids"):
        assert key in result.details

    target_missing = BattleState(
        units={"enemy:solo": _unit("enemy:solo", "enemy")}
    )
    target_result = _evaluate(_condition(index_type="Left"), target_missing, "enemy:solo")
    assert target_result.ok is False and target_result.result is None
    assert "team_location_position_missing" in target_result.reason
    assert target_result.details["missing_position_unit_ids"] == ["enemy:solo"]

    boolean_position = BattleState(
        units={
            "enemy:left": _unit("enemy:left", "enemy", 0),
            "enemy:middle": _unit("enemy:middle", "enemy", True),
            "enemy:right": _unit("enemy:right", "enemy", 2),
        }
    )
    boolean_result = _evaluate(_condition(index_type="Medium"), boolean_position, "enemy:left")
    assert boolean_result.ok is False and boolean_result.result is None
    assert "team_location_position_missing" in boolean_result.reason
    assert boolean_result.details["missing_position_unit_ids"] == ["enemy:middle"]


def test_team_type_mismatch_is_false_without_requiring_positions():
    state = BattleState(
        units={
            "enemy:target": _unit("enemy:target", "enemy"),
            "ally:target": _unit("ally:target", "ally"),
        }
    )
    enemy_as_light = _evaluate(_condition(team_type="TeamLight"), state, "enemy:target")
    assert (enemy_as_light.ok, enemy_as_light.result) == (True, False), enemy_as_light.to_json()
    assert enemy_as_light.details["expected_side"] == "ally"
    assert enemy_as_light.details["target_side"] == "enemy"
    ally_as_dark = _evaluate(_condition(team_type="TeamDark"), state, "ally:target")
    assert (ally_as_dark.ok, ally_as_dark.result) == (True, False)


def test_unknown_index_type_blocks():
    state = _three_member_state()
    result = _evaluate(_condition(index_type="Pos2"), state, "enemy:left")
    assert result.ok is False and result.result is None
    assert "team_location_index_type_not_admitted:Pos2" in result.reason
    assert result.details["index_type"] == "Pos2"


def test_unknown_team_type_blocks():
    state = _three_member_state()
    result = _evaluate(_condition(team_type="TeamNeutral"), state, "enemy:left")
    assert result.ok is False and result.result is None
    assert "team_type_not_admitted" in result.reason
    assert result.details["team_type"] == "TeamNeutral"


def test_only_living_units_join_the_formation_span():
    state = BattleState(
        units={
            "enemy:left": _unit("enemy:left", "enemy", 0),
            "enemy:middle": _unit("enemy:middle", "enemy", 1),
            "enemy:right": _unit("enemy:right", "enemy", 2),
            "enemy:zero_hp": _unit("enemy:zero_hp", "enemy", 5, hp=0.0),
            "enemy:defeated": _unit(
                "enemy:defeated", "enemy", 6, lifecycle_status="defeated"
            ),
        }
    )
    right = _evaluate(_condition(index_type="Right"), state, "enemy:right")
    assert (right.ok, right.result) == (True, True), right.to_json()
    assert "enemy:zero_hp" not in right.details["team_member_ids"]
    assert "enemy:defeated" not in right.details["team_member_ids"]
    middle = _evaluate(_condition(index_type="Medium"), state, "enemy:middle")
    assert (middle.ok, middle.result) == (True, True), middle.to_json()

    dead_target = BattleState(
        units={
            "enemy:dead": _unit("enemy:dead", "enemy", 0, hp=0.0),
            "enemy:alive": _unit("enemy:alive", "enemy", 1),
        }
    )
    dead_result = _evaluate(_condition(index_type="Left"), dead_target, "enemy:dead")
    assert (dead_result.ok, dead_result.result) == (True, False), dead_result.to_json()
    assert "enemy:dead" not in dead_result.details["team_member_ids"]
