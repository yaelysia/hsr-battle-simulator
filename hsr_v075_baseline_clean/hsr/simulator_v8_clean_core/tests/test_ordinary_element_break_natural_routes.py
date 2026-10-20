"""自然普通击破五元素路线：火/雷/冰/量子/虚数集中检查。

每条路线从 `examples/cli/` 的正式场景与固定外部操作出发，只经由
`BattleSession.advance/submit` 推进；不注入或覆盖 HP、韧性、弱点、状态、时间线、队列或
RNG。断言读取正式事件、mutation、状态实例、参数与结算来源，并允许链路完成后战斗仍未结束。

Wind 的既有自然路线单独保留在 `test_ordinary_wind_break_natural_route.py`；本模块是五元素
自然路线的唯一集成入口，共享下面的辅助函数，不复制五份风路线测试。归档校验不在本模块内
重复执行（量子归档由独立 CLI run/replay 验证）。

五条路线均为普通单韧性自然路线；火/雷/冰/量子的来源目标韧性为 30，虚数目标来源韧性为 60
（首次普攻只削一层，两发普攻击破），且虚数路线包含一次公开的同速 actor 选择。
"""
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.battle_archive import read_json_object
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
from hsr.simulator_v8_clean_core.systems.timeline import TimelineSystem
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration

CORE = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[4]
TBGD = REPO / "turnbasedgamedata-main"
EXAMPLES = CORE / "examples/cli"

# `unit.statuses` 使用带 `modifier:` 前缀的状态身份；status_details 与原生生命周期
# 事件 payload 的 `modifier_name` 使用裸修饰器名，两种读取面不能混用。
STANCE_BREAK_STATE = "modifier:StanceBreakState"
MONSTER_DAMAGE_REDUCE = "modifier:MonsterAllDamageReduce"
STANCE_BREAK_STATE_NAME = "StanceBreakState"
MONSTER_DAMAGE_REDUCE_NAME = "MonsterAllDamageReduce"
TIMELINE_TIE_ACTION = "timeline:select_tied_actor"


# ---------------------------------------------------------------------------
# 共享辅助：正式场景/会话、公开推进、事件与 mutation 提取
# ---------------------------------------------------------------------------
def load_route(route_name):
    """读取同名场景与固定外部操作；两者都是正式 CLI 输入。"""
    scenario = read_json_object(EXAMPLES / f"{route_name}.json")
    commands = read_json_object(EXAMPLES / f"{route_name}.commands.json")["commands"]
    return scenario, commands


def open_route(route_name):
    """范围编译正式规则并建立会话；编译缓存由 build_battle_rulebook 统一复用。"""
    scenario, commands = load_route(route_name)
    rules = build_battle_rulebook(TBGD, scenario)
    return scenario, rules, BattleSession(rules, scenario), commands


def advance_until_ready(session):
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    return decision


def advance_operations(session):
    operation = session.operations[-1]
    assert operation["kind"] == "advance"
    return list(operation["transitions"])


def submit_formal_command(session, command):
    result = session.submit(command_from_json(command))
    outcome = result.transition.outcome
    assert outcome.successor_eligible, outcome.reason_codes
    return result


def advance_transition(session):
    """取回最近一次 advance 的唯一原生 transition（首击破后的自然回合）。"""
    transitions = advance_operations(session)
    assert len(transitions) == 1
    transition = transitions[0]
    return transition, normalized_mutations(transition["mutations"]), list(transition["events"])


def normalized_mutations(mutations):
    """把 transaction mutation 对象和 operation 序列化 mutation 归一为同一读取形状。"""
    rows = []
    for mutation in mutations:
        if hasattr(mutation, "path"):
            path = tuple(mutation.path)
            before, after, metadata = mutation.before, mutation.after, mutation.metadata
            mutation_id = getattr(mutation, "mutation_id", None)
        else:
            path = tuple(mutation["path"])
            before, after = mutation["before"], mutation["after"]
            metadata = mutation.get("metadata")
            mutation_id = mutation.get("mutation_id")
        rows.append({"path": path, "before": before, "after": after,
                     "metadata": metadata or {}, "mutation_id": mutation_id})
    return rows


def event_type(event):
    return event.event_type if hasattr(event, "event_type") else event["event_type"]


def event_payload(event):
    payload = event.payload if hasattr(event, "payload") else event.get("payload")
    return payload or {}


def event_window(event):
    return event.window if hasattr(event, "window") else event.get("window")


def event_event_id(event):
    value = event.event_id if hasattr(event, "event_id") else event.get("event_id")
    return str(value)


def event_types(events):
    return [event_type(event) for event in events]


def transaction_events(result):
    return list(result.transition.transaction.events)


def transaction_mutations(result):
    return normalized_mutations(result.transition.transaction.mutations)


def settlement_records(result, record_type):
    settlement = result.transition.transaction.settlement
    assert settlement is not None
    return [record for record in settlement.records
            if record["record_type"] == record_type]


def break_triggered_events(events):
    return [event for event in events if event_type(event) == "break.triggered"]


def status_lifecycle_events(events, modifier_name=None, operation=None):
    rows = []
    for event in events:
        if event_type(event) != "status.lifecycle":
            continue
        payload = event_payload(event)
        if modifier_name is not None and payload.get("modifier_name") != modifier_name:
            continue
        if operation is not None and payload.get("lifecycle_operation") != operation:
            continue
        rows.append(event)
    return rows


def unit_mutations(mutations, unit_id, field=None):
    rows = [row for row in mutations if row["path"][:2] == ("units", unit_id)]
    if field is not None:
        rows = [row for row in rows if row["path"][-1] == field]
    return rows


def hp_mutations(mutations, unit_id):
    return unit_mutations(mutations, unit_id, "hp")


def toughness_mutations(mutations, unit_id):
    return unit_mutations(mutations, unit_id, "toughness")


def action_value_mutations(mutations, unit_id):
    return unit_mutations(mutations, unit_id, "action_value")


def status_details(state, unit_id, modifier_name):
    return [detail for detail in state.units[unit_id].flags.get("status_details") or ()
            if detail.get("modifier_name") == modifier_name]


def require_status_detail(state, unit_id, modifier_name):
    details = status_details(state, unit_id, modifier_name)
    assert len(details) == 1, [detail.get("instance_id") for detail in details]
    return details[0]


# ---------------------------------------------------------------------------
# 共享断言：正式来源、击破/恢复状态、元素差异
# ---------------------------------------------------------------------------
def assert_enemy_source(state, unit_id, element, stage_id, max_toughness=30.0):
    """目标必须来自真实关卡波次：该元素弱点、普通单层韧性与满血入场。"""
    unit = state.units[unit_id]
    assert unit.side == "enemy"
    assert element in unit.flags["weaknesses"]
    assert unit.max_toughness == max_toughness
    assert unit.flags["monster_stance_count"] == 1
    assert unit.flags["stage_id"] == stage_id
    assert unit.hp == unit.max_hp
    assert unit.toughness == unit.max_toughness


def assert_allies_alive(state):
    allies = [unit for unit in state.units.values() if unit.side == "ally"]
    assert allies
    for unit in allies:
        assert unit.hp > 0
        assert unit.lifecycle_status == "active"


def assert_break_applied(state, unit_id):
    unit = state.units[unit_id]
    assert unit.toughness == 0
    assert unit.flags["broken"] is True
    assert STANCE_BREAK_STATE in unit.statuses
    assert MONSTER_DAMAGE_REDUCE not in unit.statuses


def assert_stance_recovered(state, unit_id):
    unit = state.units[unit_id]
    assert unit.toughness == unit.max_toughness
    assert unit.flags["broken"] is False
    assert STANCE_BREAK_STATE not in unit.statuses
    assert MONSTER_DAMAGE_REDUCE in unit.statuses


def assert_command_available(decision, command):
    """命令必须出现在当前外部决策的合法选择中（动作、等级与目标均合法）。

    同速选择（``timeline:select_tied_actor``）是时间线决策，不是战斗单位动作，
    只核对 timeline_actor 选择项。
    """
    if command["action_id"] == TIMELINE_TIE_ACTION:
        assert any(choice.choice_kind == "timeline_actor"
                   and choice.actor_id == command["actor_id"]
                   and choice.action_id == command["action_id"]
                   for choice in decision.availability.choices), command
        return
    matches = [
        choice for choice in decision.availability.choices
        if choice.actor_id == command["actor_id"]
        and choice.action_id == command["action_id"]
        and choice.action_level == command["action_level"]
        and choice.target_query is not None
        and all(target in choice.target_query.candidate_ids
                for target in command["target_ids"])
    ]
    assert matches, (command, [(choice.actor_id, choice.action_id)
                               for choice in decision.availability.choices])


def assert_single_break_triggered(events, element_type, target_id, attacker_id,
                                  break_template_id):
    triggered = break_triggered_events(events)
    assert len(triggered) == 1, event_types(triggered)
    payload = event_payload(triggered[0])
    assert payload["element_type"] == element_type
    assert payload["target_id"] == target_id
    assert payload["attacker_id"] == attacker_id
    assert payload["break_template_id"] == break_template_id
    return payload


def break_damage_mutations(mutations, unit_id):
    return [row for row in hp_mutations(mutations, unit_id)
            if row["metadata"].get("damage_formula_family") == "break"]


def assert_break_damage(mutations, unit_id, element_type, break_template_id):
    """击破伤害必须是独立结算来源（break family + 模板），不能混进普攻直接伤害。"""
    rows = break_damage_mutations(mutations, unit_id)
    assert len(rows) == 1, [(row["before"], row["after"]) for row in rows]
    row = rows[0]
    assert row["metadata"].get("element_type") == element_type
    assert row["metadata"].get("break_template_id") == break_template_id
    assert row["after"] < row["before"]
    return row


def assert_break_dot_tick_then_recovery(transition, mutations, events, unit_id, *,
                                        modifier_name, owner_id, element_type,
                                        max_toughness):
    """目标自然回合开始：击破 DOT tick 先结算，随后韧性回满。

    恢复后的单位状态（broken/减伤/状态实例）由调用方继续核对。
    """
    ticks = [row for row in hp_mutations(mutations, unit_id)
             if row["metadata"].get("record_type") == "break_dot_tick"]
    assert len(ticks) == 1, [(row["before"], row["after"]) for row in ticks]
    tick = ticks[0]
    metadata = tick["metadata"]
    assert metadata["damage_source_kind"] == "status_damage"
    assert metadata["damage_source_owner_id"] == owner_id
    assert metadata["modifier_name"] == modifier_name
    assert metadata["element_type"] == element_type
    assert metadata["status_damage_emission_id"]
    assert 0 < tick["after"] < tick["before"]

    recoveries = [row for row in toughness_mutations(mutations, unit_id) if row["before"] == 0]
    assert len(recoveries) == 1
    recovery = recoveries[0]
    assert recovery["after"] == max_toughness
    assert recovery["metadata"].get("ordinary_reset_stance") is True

    tick_index = next(index for index, row in enumerate(mutations) if row is tick)
    recovery_index = next(index for index, row in enumerate(mutations) if row is recovery)
    assert tick_index < recovery_index

    types = event_types(events)
    assert (types.index("status.lifecycle.tick")
            < types.index("break.recovery_requested")
            < types.index("break.recovered"))

    lifecycle = (transition.get("coverage") or {}).get("pre_action_lifecycle") or {}
    assert lifecycle.get("life_step_moment") == "ModifierPhase1End"

    # 自然恢复路径由 break 生命周期 mutation 元数据证明：下一次常规行动前恢复。
    recovery_rows = [row for row in mutations if row["metadata"].get("break_recovery")]
    assert recovery_rows
    for row in recovery_rows:
        assert row["metadata"]["break_recovery"]["kind"] == "ordinary_before_action"
        assert row["metadata"]["break_recovery"]["trigger_kind"] == "next_regular_action"
        assert row["metadata"]["break_lifecycle"]["operation"] == "recover"
    return tick


# ---------------------------------------------------------------------------
# 火：艾丝妲普攻击破 → 灼烧 tick → 自然恢复 → 同目标二次击破 → 后续行动
# ---------------------------------------------------------------------------
FIRE_ROUTE = "asta_fire_break_natural"
FIRE_STAGE_ID = "201011361"
FIRE_ENEMY = "enemy:stage:201011361:wave:0:pos:0"
FIRE_OTHER = "enemy:stage:201011361:wave:0:pos:1"
FIRE_BREAK_TEMPLATE = "break_template:StanceBreak_Fire"
FIRE_BURN = "MCommon_Element_Burn"  # status_details / 生命周期 payload 使用裸名


def test_natural_fire_break_burn_tick_recovery_and_second_break():
    _, rules, session, commands = open_route(FIRE_ROUTE)

    profile = rules.combatant_profile("monster:8001020")
    assert profile is not None and "Fire" in profile.weaknesses
    assert_enemy_source(session.state, FIRE_ENEMY, "Fire", FIRE_STAGE_ID)
    assert_enemy_source(session.state, FIRE_OTHER, "Fire", FIRE_STAGE_ID)
    assert_allies_alive(session.state)
    assert not status_details(session.state, FIRE_ENEMY, FIRE_BURN)

    assert [command["actor_id"] for command in commands] == [
        "asta", "natasha", FIRE_OTHER, FIRE_ENEMY, "asta", "natasha",
    ]

    # 1. 艾丝妲正式普攻完成首次火击破；灼烧实例必须由击破模板产生。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "asta"
    first_break = submit_formal_command(session, commands[0])
    first_events = transaction_events(first_break)
    first_mutations = transaction_mutations(first_break)
    assert_single_break_triggered(
        first_events, "Fire", FIRE_ENEMY, "asta", FIRE_BREAK_TEMPLATE)
    first_types = event_types(first_events)
    assert first_types.index("break.entered") < first_types.index("break.triggered")
    assert_break_applied(session.state, FIRE_ENEMY)
    assert_break_damage(first_mutations, FIRE_ENEMY, "Fire", FIRE_BREAK_TEMPLATE)
    assert len(hp_mutations(first_mutations, FIRE_ENEMY)) == 2  # 普攻直接伤害 + 击破伤害
    delays = action_value_mutations(first_mutations, FIRE_ENEMY)
    assert len(delays) == 1
    assert delays[0]["metadata"].get("modifier_name") == "StanceBreakState"
    assert delays[0]["after"] > delays[0]["before"]

    burn = require_status_detail(session.state, FIRE_ENEMY, FIRE_BURN)
    assert burn["status_id"] == "modifier:MCommon_Element_Burn"
    assert burn["owner_id"] == FIRE_ENEMY
    assert burn["caster_id"] == "asta"
    assert burn["source_id"] == "break_status_emission:StanceBreak_Fire:1"
    assert burn["stacks"] == 1 and burn["max_stacks"] == 1
    assert burn["duration"] == 2.0  # MCommon_Element_Burn 来源持续时间参数
    dynamic = burn["dynamic_values"]["__by_name"]
    assert dynamic["MDF_DamagePercentage"] == 1.0
    assert dynamic["_Layer"] == 1.0
    trace = burn["source_trace"]
    assert trace["effect_id"] == "break_effect:StanceBreak_Fire:1:AddModifier"
    effect_source = trace["effect_source"]
    assert effect_source["raw_id"] == "StanceBreak_Fire"
    assert effect_source["raw_type"] == "GlobalBreakStatusTask"
    evidence = effect_source["evidence"]
    assert evidence["template_id"] == FIRE_BREAK_TEMPLATE
    assert evidence["break_status_emission_id"] == burn["source_id"]
    burn_adds = status_lifecycle_events(first_events, FIRE_BURN, "add")
    assert burn_adds
    assert any(event_payload(event).get("status_instance_id") == burn["instance_id"]
               for event in burn_adds)

    # 2. 击破期间队员的合法动作不会再次削韧，也不产生第二次击破。
    hp_before_tick = session.state.units[FIRE_ENEMY].hp
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "natasha"
    filler = submit_formal_command(session, commands[1])
    assert not break_triggered_events(transaction_events(filler))
    assert session.state.units[FIRE_ENEMY].toughness == 0
    assert session.state.units[FIRE_ENEMY].hp == hp_before_tick
    assert_allies_alive(session.state)

    # 3. 另一只敌人的自然行动不改变该目标的击破状态。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == FIRE_OTHER
    other_turn = submit_formal_command(session, commands[2])
    assert not break_triggered_events(transaction_events(other_turn))
    assert session.state.units[FIRE_ENEMY].hp == hp_before_tick
    assert session.state.units[FIRE_ENEMY].toughness == 0

    # 4. 目标自然回合开始：灼烧 tick 先结算，随后恢复韧性、broken=False、减伤恢复。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == FIRE_ENEMY
    recovery_transition, recovery_mutations, recovery_events = advance_transition(session)
    tick = assert_break_dot_tick_then_recovery(
        recovery_transition, recovery_mutations, recovery_events, FIRE_ENEMY,
        modifier_name=FIRE_BURN, owner_id="asta", element_type="Fire",
        max_toughness=session.state.units[FIRE_ENEMY].max_toughness)
    recovering = session.state.units[FIRE_ENEMY]
    assert recovering.hp == tick["after"] < hp_before_tick
    assert_stance_recovered(session.state, FIRE_ENEMY)
    requested = next(event for event in recovery_events
                     if event_type(event) == "break.recovery_requested")
    requested_payload = event_payload(requested)
    assert requested_payload["break_template_id"] == FIRE_BREAK_TEMPLATE
    assert status_lifecycle_events(recovery_events, STANCE_BREAK_STATE_NAME, "remove")
    assert_allies_alive(session.state)

    # 5. 目标完成其自然行动后仍处于已恢复状态。
    target_turn = submit_formal_command(session, commands[3])
    assert target_turn.transition.outcome.successor_eligible
    assert session.state.units[FIRE_ENEMY].toughness == session.state.units[FIRE_ENEMY].max_toughness
    assert session.state.units[FIRE_ENEMY].flags["broken"] is False
    assert session.state.units[FIRE_ENEMY].hp == tick["after"]
    assert_allies_alive(session.state)

    # 6. 同一目标在恢复后再次被击破：新的 break 生命周期重新移除减伤并施加击破状态。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "asta"
    second_break = submit_formal_command(session, commands[4])
    second_events = transaction_events(second_break)
    second_mutations = transaction_mutations(second_break)
    assert_single_break_triggered(
        second_events, "Fire", FIRE_ENEMY, "asta", FIRE_BREAK_TEMPLATE)
    second_types = event_types(second_events)
    assert second_types.index("break.entered") < second_types.index("break.triggered")
    assert_break_applied(session.state, FIRE_ENEMY)
    assert_break_damage(second_mutations, FIRE_ENEMY, "Fire", FIRE_BREAK_TEMPLATE)
    second_delays = action_value_mutations(second_mutations, FIRE_ENEMY)
    assert len(second_delays) == 1
    assert second_delays[0]["metadata"].get("modifier_name") == "StanceBreakState"
    assert second_delays[0]["after"] > second_delays[0]["before"]

    second_adds = [event for event in
                   status_lifecycle_events(second_events, STANCE_BREAK_STATE_NAME, "add")
                   if event_payload(event).get("callback_event") == "OnCreate"]
    assert len(second_adds) == 1
    burn_refreshes = status_lifecycle_events(second_events, FIRE_BURN, "replace")
    assert burn_refreshes
    refreshed = require_status_detail(session.state, FIRE_ENEMY, FIRE_BURN)
    assert refreshed["caster_id"] == "asta"
    assert refreshed["source_id"].startswith("break_status_emission:StanceBreak_Fire:")
    assert refreshed["stacks"] == 1
    assert len(status_details(session.state, FIRE_ENEMY, FIRE_BURN)) == 1

    # 7. 后续合法行动可用且成功；战斗可以仍未结束。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "natasha"
    assert any(choice.actor_id == "natasha"
               and choice.action_id == commands[5]["action_id"]
               for choice in decision.availability.choices)
    follow_up = submit_formal_command(session, commands[5])
    assert not break_triggered_events(transaction_events(follow_up))
    assert session.outcome == ""
    assert session.state.units[FIRE_ENEMY].hp > 0
    assert session.state.units[FIRE_OTHER].hp > 0
    assert session.state.units[FIRE_ENEMY].flags["broken"] is True
    assert_allies_alive(session.state)

    submits = [operation for operation in session.operations if operation["kind"] == "submit"]
    assert len(submits) == len(commands)


# ---------------------------------------------------------------------------
# 雷：阿兰普攻击破 → 触电 tick → 自然恢复 → 同目标二次击破 → 后续行动
# ---------------------------------------------------------------------------
THUNDER_ROUTE = "arlan_thunder_break_natural"
THUNDER_STAGE_ID = "202110311"
THUNDER_ENEMY = "enemy:stage:202110311:wave:0:pos:0"
THUNDER_OTHER = "enemy:stage:202110311:wave:0:pos:1"
THUNDER_BREAK_TEMPLATE = "break_template:StanceBreak_Thunder"
THUNDER_ELECTRIC = "MCommon_Element_Electric"
THUNDER_ELECTRIC_STATUS = "modifier:MCommon_Element_Electric"


def test_natural_thunder_break_electric_dot_recovery_and_second_break():
    scenario, rules, session, commands = open_route(THUNDER_ROUTE)
    assert scenario["stage_ref"] == THUNDER_STAGE_ID and scenario["wave_index"] == 0
    builds = {unit["unit_id"]: unit["character_build"] for unit in scenario["units"]}
    assert (builds["arlan"]["level"], builds["arlan"]["eidolon_level"]) == (1, 0)
    assert (builds["natasha"]["level"], builds["natasha"]["promotion"],
            builds["natasha"]["eidolon_level"]) == (80, 6, 0)

    profile = rules.combatant_profile("monster:8001050")
    assert profile is not None and "Thunder" in profile.weaknesses
    assert_enemy_source(session.state, THUNDER_ENEMY, "Thunder", THUNDER_STAGE_ID)
    assert session.state.units[THUNDER_OTHER].side == "enemy"
    assert_allies_alive(session.state)
    assert len(commands) == 6
    assert [command["actor_id"] for command in commands] == [
        "arlan", "natasha", THUNDER_OTHER, THUNDER_ENEMY, "arlan", "natasha",
    ]

    # 1. 阿兰正式普攻完成首次雷击破；触电由击破模板施加。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[0])
    assert decision.token.actor_id == "arlan"
    first_break = submit_formal_command(session, commands[0])
    first_events = transaction_events(first_break)
    first_mutations = transaction_mutations(first_break)
    assert_single_break_triggered(
        first_events, "Thunder", THUNDER_ENEMY, "arlan", THUNDER_BREAK_TEMPLATE)
    entered = [event for event in first_events if event_type(event) == "break.entered"]
    assert len(entered) == 1 and event_payload(entered[0])["element_type"] == "Thunder"
    first_break_ids = {event_type(event): event_event_id(event)
                       for event in (*entered, *break_triggered_events(first_events))}
    broken = session.state.units[THUNDER_ENEMY]
    assert broken.flags["break_element"] == "Thunder"
    assert broken.flags["break_source"]["attacker_id"] == "arlan"
    assert_break_applied(session.state, THUNDER_ENEMY)
    assert THUNDER_ELECTRIC_STATUS in broken.statuses
    assert_break_damage(first_mutations, THUNDER_ENEMY, "Thunder", THUNDER_BREAK_TEMPLATE)
    delays = action_value_mutations(first_mutations, THUNDER_ENEMY)
    assert len(delays) == 1 and delays[0]["after"] > delays[0]["before"]
    lifecycle_records = settlement_records(first_break, "break_lifecycle")
    assert {record["payload"]["field"] for record in lifecycle_records} == {
        "broken", "break_element", "break_source"}
    break_status_records = settlement_records(first_break, "break_status")
    assert len(break_status_records) == 1
    assert break_status_records[0]["payload"]["break_status_emission_id"] == (
        "break_status_emission:StanceBreak_Thunder:1")
    assert len(settlement_records(first_break, "break_damage")) == 1
    electric = require_status_detail(session.state, THUNDER_ENEMY, THUNDER_ELECTRIC)
    assert electric["caster_id"] == "arlan"
    assert electric["source_id"] == "break_status_emission:StanceBreak_Thunder:1"
    assert electric["instance_id"]
    assert electric["stacks"] == 1
    assert electric["dynamic_values"]["MDF_DamagePercentage"] == 2.0
    stance = require_status_detail(session.state, THUNDER_ENEMY, STANCE_BREAK_STATE_NAME)
    assert stance is not None and stance["caster_id"] == THUNDER_ENEMY
    hp_after_first_break = broken.hp
    assert_allies_alive(session.state)

    # 2. 娜塔莎的正式治疗是合法非伤害填充动作，不能削韧或改变目标 HP。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[1])
    assert decision.token.actor_id == "natasha"
    filler = submit_formal_command(session, commands[1])
    assert not break_triggered_events(transaction_events(filler))
    assert session.state.units[THUNDER_ENEMY].toughness == 0
    assert session.state.units[THUNDER_ENEMY].hp == hp_after_first_break
    assert_allies_alive(session.state)

    # 3. 非目标来源敌人也自然行动（外部选择目标为娜塔莎）。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[2])
    assert decision.token.actor_id == THUNDER_OTHER
    other_turn = submit_formal_command(session, commands[2])
    assert not break_triggered_events(transaction_events(other_turn))
    assert session.state.units[THUNDER_ENEMY].hp == hp_after_first_break
    assert session.state.units[THUNDER_OTHER].hp > 0
    assert_allies_alive(session.state)

    # 4. 目标自然回合先结算真实触电 break DOT，再恢复韧性层。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == THUNDER_ENEMY
    recovery_transitions = [transition for transition in advance_operations(session)
                            if (transition.get("coverage") or {}).get("pre_action_lifecycle")]
    assert len(recovery_transitions) == 1
    recovery = recovery_transitions[0]
    assert recovery["coverage"]["pre_action_lifecycle"]["life_step_moment"] == (
        "ModifierPhase1End")
    recovery_mutations = normalized_mutations(recovery["mutations"])
    recovery_events = recovery["events"]
    ticks = [row for row in hp_mutations(recovery_mutations, THUNDER_ENEMY)
             if row["metadata"].get("record_type") == "break_dot_tick"]
    assert len(ticks) == 1
    tick = ticks[0]
    tick_meta = tick["metadata"]
    assert tick_meta["damage_formula_family"] == "break"
    assert tick_meta["break_template_id"] == THUNDER_BREAK_TEMPLATE
    assert tick_meta["element_type"] == "Thunder"
    assert tick_meta["modifier_name"] == THUNDER_ELECTRIC
    assert tick_meta["damage_source_kind"] == "status_damage"
    assert tick_meta["damage_source_owner_id"] == "arlan"
    assert tick_meta["status_damage_emission_id"]
    assert tick_meta["status_instance_id"] == electric["instance_id"]
    assert 0 < tick["after"] < tick["before"] == hp_after_first_break
    break_dot_records = [record for record in recovery["settlement"]["records"]
                         if record["record_type"] == "break_dot_tick"]
    assert len(break_dot_records) == 1
    assert break_dot_records[0]["mutation_id"] == tick["mutation_id"]
    recovery_toughness = [row for row in toughness_mutations(recovery_mutations, THUNDER_ENEMY)
                          if row["before"] == 0]
    assert len(recovery_toughness) == 1
    assert recovery_toughness[0]["after"] == session.state.units[THUNDER_ENEMY].max_toughness
    break_recovery_records = [record for record in recovery["settlement"]["records"]
                              if record["record_type"] == "break_recovery"]
    assert {record["payload"]["field"] for record in break_recovery_records} == {
        "broken", "break_element", "break_source"}
    assert all(record["payload"]["trigger_kind"] == "next_regular_action"
               for record in break_recovery_records)
    recovery_types = event_types(recovery_events)
    assert (recovery_types.index("status.lifecycle.tick")
            < recovery_types.index("break.recovery_requested")
            < recovery_types.index("break.recovered"))
    assert status_lifecycle_events(recovery_events, STANCE_BREAK_STATE_NAME, "remove")
    assert status_lifecycle_events(recovery_events, MONSTER_DAMAGE_REDUCE_NAME, "add")
    recovering = session.state.units[THUNDER_ENEMY]
    assert recovering.hp == tick["after"] < hp_after_first_break
    assert_stance_recovered(session.state, THUNDER_ENEMY)
    assert THUNDER_ELECTRIC_STATUS in recovering.statuses
    assert_allies_alive(session.state)

    # 目标恢复后仍完成其自然行动。
    target_turn = submit_formal_command(session, commands[3])
    assert not break_triggered_events(transaction_events(target_turn))
    assert session.state.units[THUNDER_ENEMY].toughness == (
        session.state.units[THUNDER_ENEMY].max_toughness)
    assert session.state.units[THUNDER_ENEMY].flags["broken"] is False
    assert_allies_alive(session.state)

    # 5. 同一目标再次被击破：新的正式事务/生命周期，而非首次记录重放。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[4])
    assert decision.token.actor_id == "arlan"
    second_break = submit_formal_command(session, commands[4])
    second_events = transaction_events(second_break)
    second_mutations = transaction_mutations(second_break)
    assert_single_break_triggered(
        second_events, "Thunder", THUNDER_ENEMY, "arlan", THUNDER_BREAK_TEMPLATE)
    second_entered = [event for event in second_events if event_type(event) == "break.entered"]
    assert len(second_entered) == 1
    second_break_ids = {event_type(event): event_event_id(event)
                        for event in (*second_entered, *break_triggered_events(second_events))}
    assert second_break_ids["break.triggered"] != first_break_ids["break.triggered"]
    assert second_break_ids["break.entered"] != first_break_ids["break.entered"]
    assert_break_damage(second_mutations, THUNDER_ENEMY, "Thunder", THUNDER_BREAK_TEMPLATE)
    second_delays = action_value_mutations(second_mutations, THUNDER_ENEMY)
    assert len(second_delays) == 1 and second_delays[0]["after"] > second_delays[0]["before"]
    second_lifecycle = settlement_records(second_break, "break_lifecycle")
    assert {record["payload"]["field"] for record in second_lifecycle} == {
        "broken", "break_element", "break_source"}
    first_lifecycle_ids = {record["mutation_id"] for record in lifecycle_records}
    second_lifecycle_ids = {record["mutation_id"] for record in second_lifecycle}
    assert first_lifecycle_ids.isdisjoint(second_lifecycle_ids)
    assert len(settlement_records(second_break, "break_status")) == 1
    assert len(settlement_records(second_break, "break_damage")) == 1
    assert status_lifecycle_events(second_events, STANCE_BREAK_STATE_NAME, "add")
    assert (status_lifecycle_events(second_events, THUNDER_ELECTRIC, "add")
            or status_lifecycle_events(second_events, THUNDER_ELECTRIC, "replace"))
    assert_break_applied(session.state, THUNDER_ENEMY)
    rebroken = session.state.units[THUNDER_ENEMY]
    assert rebroken.hp > 0
    rebroken_electric = require_status_detail(session.state, THUNDER_ENEMY, THUNDER_ELECTRIC)
    assert rebroken_electric["caster_id"] == "arlan"
    assert_allies_alive(session.state)

    # 6. 二次击破后仍有合法外部行动且成功；战斗可以仍未结束。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[5])
    assert decision.token.actor_id == "natasha"
    follow_up = submit_formal_command(session, commands[5])
    assert not break_triggered_events(transaction_events(follow_up))
    assert session.outcome == ""
    assert session.state.units[THUNDER_ENEMY].hp > 0
    assert session.state.units[THUNDER_ENEMY].flags["broken"] is True
    assert_allies_alive(session.state)
    continuing = advance_until_ready(session)
    assert continuing.ready, continuing.blocked_reason
    assert session.outcome == ""

    submits = [operation for operation in session.operations if operation["kind"] == "submit"]
    assert len(submits) == len(commands)
    assert [operation["command"]["actor_id"] for operation in submits] == [
        command["actor_id"] for command in commands]


# ---------------------------------------------------------------------------
# 冰：三月七普攻击破 → 冻结消耗目标回合（不恢复）→ 解冻后自然恢复 → 二次击破
# ---------------------------------------------------------------------------
ICE_ROUTE = "march7th_ice_break_natural"
ICE_STAGE_ID = "202232051"
ICE_ENEMY = "enemy:stage:202232051:wave:0:pos:0"
ICE_BREAK_TEMPLATE = "break_template:StanceBreak_Ice"
ICE_FROZEN = "MCommon_Element_Frozen"
ICE_FROZEN_STATUS = "modifier:MCommon_Element_Frozen"


def _assert_ice_frozen(detail, *, caster_id):
    assert detail["status_id"] == ICE_FROZEN_STATUS
    assert detail["caster_id"] == caster_id
    assert detail["owner_id"] == ICE_ENEMY
    assert detail["source_id"] == "break_status_emission:StanceBreak_Ice:1"
    assert detail["status_category"] == "control"
    assert detail["control_kind"] == "CTRL_Frozen_Effect"
    assert "DisableAction" in detail["behavior_flags"]
    assert detail["stacks"] == 1 and detail["max_stacks"] == 1
    assert detail["duration"] == 1.0 and detail["remaining_duration"] == 1.0
    assert detail["life_step_moment"] == "ModifierPhase1End"
    assert detail["lifecycle_state"] == "active"
    assert detail.get("lifecycle_operation") in (None, "add")
    duration_admission = detail["duration_admission"]
    assert duration_admission["admission_status"] == "executable"
    assert duration_admission["life_step_moment"] == "ModifierPhase1End"
    assert duration_admission["tick_owner_policy"] == "holder"
    trace = detail["source_trace"]
    assert trace["effect_id"] == "break_effect:StanceBreak_Ice:1:AddModifier"
    effect_source = trace["effect_source"]
    assert effect_source["raw_id"] == "StanceBreak_Ice"
    assert effect_source["raw_type"] == "GlobalBreakStatusTask"
    assert effect_source["evidence"]["template_id"] == ICE_BREAK_TEMPLATE
    return detail["instance_id"]


def test_natural_ice_break_frozen_turn_skip_recovery_and_second_break():
    scenario, rules, session, commands = open_route(ICE_ROUTE)
    assert scenario["stage_ref"] == ICE_STAGE_ID and scenario["wave_index"] == 0
    profile = rules.combatant_profile("monster:8001010")
    assert profile is not None and "Ice" in profile.weaknesses
    enemy_before = session.state.units[ICE_ENEMY]
    assert_enemy_source(session.state, ICE_ENEMY, "Ice", ICE_STAGE_ID)
    assert_allies_alive(session.state)
    assert len(commands) == 7
    assert [command["actor_id"] for command in commands] == [
        "march7th", "natasha", "march7th", "natasha", ICE_ENEMY, "march7th", "natasha",
    ]

    # 0. 真实波次入场：首个 advance 内部先完成 wave 转场，再打开首个外部决策。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "march7th"
    wave_transitions = [transition for transition in advance_operations(session)
                        if transition["command"]["action_id"] == "wave:transition"]
    assert len(wave_transitions) == 1
    assert "wave.started" in event_types(wave_transitions[0]["events"])

    # 1. 三月七正式普攻完成首次冰击破，冻结由击破模板自然施加。
    first_break = submit_formal_command(session, commands[0])
    first_events = transaction_events(first_break)
    first_mutations = transaction_mutations(first_break)
    first_types = event_types(first_events)
    assert "break.entered" in first_types and "break.triggered" in first_types
    assert first_types.index("break.entered") < first_types.index("break.triggered")
    assert_single_break_triggered(
        first_events, "Ice", ICE_ENEMY, "march7th", ICE_BREAK_TEMPLATE)
    assert_break_applied(session.state, ICE_ENEMY)

    hp_rows = hp_mutations(first_mutations, ICE_ENEMY)
    break_rows = [row for row in hp_rows
                  if row["metadata"].get("damage_formula_family") == "break"]
    direct_rows = [row for row in hp_rows
                   if row["metadata"].get("damage_formula_family") == "direct"]
    assert len(break_rows) == 1 and len(direct_rows) == 1
    assert break_rows[0]["metadata"]["element_type"] == "Ice"
    assert break_rows[0]["metadata"]["break_template_id"] == ICE_BREAK_TEMPLATE
    assert direct_rows[0]["metadata"]["element_type"] == "Ice"
    assert 0 < break_rows[0]["after"] < break_rows[0]["before"]
    delay_rows = action_value_mutations(first_mutations, ICE_ENEMY)
    assert len(delay_rows) == 1
    assert delay_rows[0]["metadata"].get("modifier_name") == "StanceBreakState"
    assert delay_rows[0]["after"] > delay_rows[0]["before"]

    frozen = require_status_detail(session.state, ICE_ENEMY, ICE_FROZEN)
    frozen_instance = _assert_ice_frozen(frozen, caster_id="march7th")
    frozen_adds = status_lifecycle_events(first_events, ICE_FROZEN, "add")
    assert frozen_adds
    assert any(event_payload(event).get("status_instance_id") == frozen_instance
               for event in frozen_adds)

    # 2. 击破期间娜塔莎的合法治疗战技不削韧、不改变目标 HP，冻结仍在。
    hp_before_filler = session.state.units[ICE_ENEMY].hp
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "natasha"
    filler = submit_formal_command(session, commands[1])
    assert not break_triggered_events(transaction_events(filler))
    assert session.state.units[ICE_ENEMY].hp == hp_before_filler
    assert session.state.units[ICE_ENEMY].toughness == 0
    assert session.state.units[ICE_ENEMY].flags["broken"] is True
    assert require_status_detail(session.state, ICE_ENEMY, ICE_FROZEN)["instance_id"] == (
        frozen_instance)

    # 3. 目标自然回合被冻结消耗：先结算冻结 ByBreakDamage，再到期移除，最后 control_skip。
    #    该回合不恢复韧性（control gate 早于 recover_ordinary_before_action）。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "march7th"
    skip_transitions = [transition for transition in advance_operations(session)
                        if (transition.get("coverage") or {}).get("control_skip")]
    assert len(skip_transitions) == 1
    skip = skip_transitions[0]
    assert skip["command"]["action_id"] == "timeline:consume_controlled_turn"
    control_skip = skip["coverage"]["control_skip"]
    assert control_skip["consumed"] is True
    assert control_skip["state"] == "pending_turn_end"
    gate = control_skip["control_gate"]
    assert gate["scope"] == "status_control"
    assert gate["actor_id"] == ICE_ENEMY
    assert gate["metadata"]["modifier_name"] == ICE_FROZEN
    assert gate["metadata"]["status_id"] == ICE_FROZEN_STATUS
    assert gate["metadata"]["control_kind"] == "CTRL_Frozen_Effect"
    assert gate["metadata"]["status_instance_id"] == frozen_instance
    assert skip["coverage"]["pre_action_lifecycle"]["life_step_moment"] == "ModifierPhase1End"
    skip_events = list(skip["events"])
    skip_types = event_types(skip_events)
    assert "turn.control_skipped" in skip_types
    assert "break.recovery_requested" not in skip_types
    assert "break.recovered" not in skip_types
    assert ICE_FROZEN_STATUS in skip["before"]["units"][ICE_ENEMY]["statuses"]
    frozen_ticks = status_lifecycle_events(skip_events, ICE_FROZEN, "tick")
    frozen_expires = status_lifecycle_events(skip_events, ICE_FROZEN, "expire")
    assert frozen_ticks and frozen_expires
    assert all(event_payload(event).get("status_instance_id") == frozen_instance
               for event in (*frozen_ticks, *frozen_expires))
    tick_index = skip_events.index(frozen_ticks[0])
    expire_index = skip_events.index(frozen_expires[0])
    assert tick_index < expire_index < skip_types.index("turn.control_skipped")
    damage_hits = [index for index, event in enumerate(skip_events)
                   if event_type(event) == "damage.hit"
                   and event_payload(event).get("element_type") == "Ice"]
    assert damage_hits and tick_index < damage_hits[0] < expire_index

    dot_rows = [row for row in hp_mutations(normalized_mutations(skip["mutations"]), ICE_ENEMY)
                if row["metadata"].get("record_type") == "break_dot_tick"]
    assert len(dot_rows) == 1
    dot = dot_rows[0]
    assert dot["metadata"]["damage_source_kind"] == "status_damage"
    assert dot["metadata"]["damage_source_owner_id"] == "march7th"
    assert dot["metadata"]["modifier_name"] == ICE_FROZEN
    assert dot["metadata"]["element_type"] == "Ice"
    assert dot["metadata"]["break_template_id"] == ICE_BREAK_TEMPLATE
    assert dot["metadata"]["status_damage_emission_id"]
    assert 0 < dot["after"] < dot["before"]
    status_rows = unit_mutations(normalized_mutations(skip["mutations"]), ICE_ENEMY, "statuses")
    assert any(ICE_FROZEN_STATUS not in row["after"] and ICE_FROZEN_STATUS in row["before"]
               for row in status_rows)
    skipped_enemy = session.state.units[ICE_ENEMY]
    assert skipped_enemy.hp == dot["after"]
    assert skipped_enemy.toughness == 0
    assert skipped_enemy.flags["broken"] is True
    assert ICE_FROZEN_STATUS not in skipped_enemy.statuses

    # 4. 解冻后的击破期填充动作：目标仍为 broken，不产生新击破。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "march7th"
    held = submit_formal_command(session, commands[2])
    assert not break_triggered_events(transaction_events(held))
    assert session.state.units[ICE_ENEMY].toughness == 0
    assert session.state.units[ICE_ENEMY].flags["broken"] is True
    assert_allies_alive(session.state)

    decision = advance_until_ready(session)
    assert decision.token.actor_id == "natasha"
    submit_formal_command(session, commands[3])

    # 5. 目标解冻后的下一自然回合才恢复：pre-action 先请求并完成恢复，随后目标正常行动。
    hp_before_recovery = session.state.units[ICE_ENEMY].hp
    decision = advance_until_ready(session)
    assert decision.token.actor_id == ICE_ENEMY
    # 按正式事件身份定位恢复 transition，不假定 advance 内部只有一步调度。
    recovery = next(transition for transition in advance_operations(session)
                    if "break.recovered" in event_types(transition["events"]))
    recovery_events = list(recovery["events"])
    recovery_types = event_types(recovery_events)
    assert "turn.control_skipped" not in recovery_types
    before_enemy = recovery["before"]["units"][ICE_ENEMY]
    assert before_enemy["toughness"] == 0
    assert before_enemy["toughness_state"]["broken"] is True
    assert ICE_FROZEN_STATUS not in before_enemy["statuses"]
    assert (recovery_types.index("status.lifecycle.tick")
            < recovery_types.index("break.recovery_requested")
            < recovery_types.index("break.recovered"))
    recovery_mutations = normalized_mutations(recovery["mutations"])
    recovery_rows = [row for row in toughness_mutations(recovery_mutations, ICE_ENEMY)
                     if row["before"] == 0]
    assert len(recovery_rows) == 1
    assert recovery_rows[0]["after"] == enemy_before.max_toughness
    assert recovery_rows[0]["metadata"].get("ordinary_reset_stance") is True
    assert (recovery["coverage"]["pre_action_lifecycle"]["life_step_moment"]
            == "ModifierPhase1End")
    recovered = session.state.units[ICE_ENEMY]
    assert_stance_recovered(session.state, ICE_ENEMY)
    assert recovered.hp == hp_before_recovery

    # 6. 恢复后的目标在当前决策中完成其自然行动；队员仍存活。
    enemy_turn = submit_formal_command(session, commands[4])
    assert not break_triggered_events(transaction_events(enemy_turn))
    assert session.state.units[ICE_ENEMY].toughness == enemy_before.max_toughness
    assert session.state.units[ICE_ENEMY].flags["broken"] is False
    assert_allies_alive(session.state)
    assert session.state.units["natasha"].hp < session.state.units["natasha"].max_hp

    # 7. 同一目标再次被击破：新的击破生命周期重新施加冻结（add → expire → add）。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "march7th"
    second_break = submit_formal_command(session, commands[5])
    second_events = transaction_events(second_break)
    second_mutations = transaction_mutations(second_break)
    assert_single_break_triggered(
        second_events, "Ice", ICE_ENEMY, "march7th", ICE_BREAK_TEMPLATE)
    assert_break_applied(session.state, ICE_ENEMY)
    assert break_damage_mutations(second_mutations, ICE_ENEMY)
    refrozen = require_status_detail(session.state, ICE_ENEMY, ICE_FROZEN)
    refrozen_instance = _assert_ice_frozen(refrozen, caster_id="march7th")
    second_adds = status_lifecycle_events(second_events, ICE_FROZEN, "add")
    assert second_adds
    assert all(event_payload(event).get("status_instance_id") == refrozen_instance
               for event in second_adds)
    # 实例 ID 由来源哈希确定，两次冻结同 ID；新生命周期由 add → expire → add 证明。
    assert refrozen_instance == frozen_instance
    assert status_lifecycle_events(first_events, ICE_FROZEN, "add")
    assert status_lifecycle_events(skip_events, ICE_FROZEN, "expire")
    assert status_lifecycle_events(second_events, ICE_FROZEN, "add")

    # 8. 二次击破后仍有合法外部行动且成功；战斗可以仍未结束。
    hp_before_follow_up = session.state.units[ICE_ENEMY].hp
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "natasha"
    assert any(choice.actor_id == "natasha"
               and choice.action_id == commands[6]["action_id"]
               for choice in decision.availability.choices)
    follow_up = submit_formal_command(session, commands[6])
    assert not break_triggered_events(transaction_events(follow_up))
    assert session.state.units[ICE_ENEMY].flags["broken"] is True
    assert session.state.units[ICE_ENEMY].toughness == 0
    assert 0 < session.state.units[ICE_ENEMY].hp < hp_before_follow_up
    # 目标仍有充足余量，不会在链路终点前死亡。
    assert session.state.units[ICE_ENEMY].hp > 0.5 * session.state.units[ICE_ENEMY].max_hp
    assert_allies_alive(session.state)
    assert session.outcome == ""
    # 二次冻结仍在等待目标回合结算；会话可继续操作。
    _assert_ice_frozen(require_status_detail(session.state, ICE_ENEMY, ICE_FROZEN),
                       caster_id="march7th")

    submits = [operation for operation in session.operations if operation["kind"] == "submit"]
    assert len(submits) == len(commands)


# ---------------------------------------------------------------------------
# 量子：玲可普攻击破 → 纠缠计数 1→2 → 到期一次结算 → 自然恢复 → 二次击破
# ---------------------------------------------------------------------------
QUANTUM_ROUTE = "lynx_quantum_break_natural"
QUANTUM_STAGE_ID = "400020800"
QUANTUM_ENEMY = "enemy:stage:400020800:wave:0:pos:0"
QUANTUM_OTHER = "enemy:stage:400020800:wave:0:pos:1"
QUANTUM_BREAK_TEMPLATE = "break_template:StanceBreak_Quantum"
QUANTUM_ENTANGLE = "MCommon_Element_Entangle"
QUANTUM_ENTANGLE_STATUS = "modifier:MCommon_Element_Entangle"
QUANTUM_HIT_COUNT_HASH = "-434232686"
QUANTUM_BE_HIT_FLAG_HASH = "40896036"
QUANTUM_MAX_COUNT_HASH = "808921108"
QUANTUM_INCREMENT_HASH = "560166466"


def _assert_quantum_entangle(detail, *, caster_id):
    assert detail["status_id"] == QUANTUM_ENTANGLE_STATUS
    assert detail["caster_id"] == caster_id
    assert detail["owner_id"] == QUANTUM_ENEMY
    assert detail["source_id"] == "break_status_emission:StanceBreak_Quantum:1"
    assert detail["status_category"] == "control"
    assert detail["control_kind"] == "Entangle"
    assert "STAT_Entangle" in detail["behavior_flags"]
    assert "DisableAction" in detail["behavior_flags"]
    assert detail["stack_policy"] == "independent_count"
    assert detail["stacks"] == 1
    assert detail["max_stacks"] is None
    assert detail["duration"] == 1.0 and detail["remaining_duration"] == 1.0
    assert detail["life_step_moment"] == "ModifierPhase1End"
    assert detail["lifecycle_state"] == "active"
    duration_admission = detail["duration_admission"]
    assert duration_admission["admission_status"] == "executable"
    assert duration_admission["life_step_moment"] == "ModifierPhase1End"
    assert duration_admission["tick_owner_policy"] == "holder"
    dynamic_values = detail["dynamic_values"]
    # 击破时计数初始值 = 1（MDF_BeingHitDamageValue 从 0 起，每次命中 +1，上限 5）。
    assert dynamic_values["__by_hash"][QUANTUM_HIT_COUNT_HASH] == 0
    assert dynamic_values["__by_hash"][QUANTUM_BE_HIT_FLAG_HASH] == 0
    assert dynamic_values["__by_hash"][QUANTUM_MAX_COUNT_HASH] == 5
    assert dynamic_values["__by_hash"][QUANTUM_INCREMENT_HASH] == 1
    trace = detail["source_trace"]
    assert trace["effect_id"] == "break_effect:StanceBreak_Quantum:1:AddModifier"
    assert trace["modifier_definition"]["raw_id"] == QUANTUM_ENTANGLE
    return detail


def _quantum_count_changes(mutations):
    """返回 status_details mutation 中纠缠 stacks 的前后变化（实际命中计数）。"""
    changes = []
    for row in normalized_mutations(mutations):
        if row["path"][:3] != ("units", QUANTUM_ENEMY, "flags"):
            continue
        if row["path"][-1] != "status_details":
            continue
        before = [detail for detail in row["before"] or ()
                  if isinstance(detail, dict) and detail.get("modifier_name") == QUANTUM_ENTANGLE]
        after = [detail for detail in row["after"] or ()
                 if isinstance(detail, dict) and detail.get("modifier_name") == QUANTUM_ENTANGLE]
        if len(before) == 1 and len(after) == 1 and before[0].get("stacks") != after[0].get("stacks"):
            changes.append((before[0].get("stacks"), after[0].get("stacks"),
                            (after[0].get("dynamic_values") or {}).get("__by_hash")))
    return changes


def _quantum_added_detail(mutations):
    """返回事务内 AddModifier 施加纠缠后（stacks=1 起始）的状态详情。"""
    for row in normalized_mutations(mutations):
        if row["path"][:3] != ("units", QUANTUM_ENEMY, "flags"):
            continue
        if row["path"][-1] != "status_details":
            continue
        before = [detail for detail in row["before"] or ()
                  if isinstance(detail, dict) and detail.get("modifier_name") == QUANTUM_ENTANGLE]
        after = [detail for detail in row["after"] or ()
                 if isinstance(detail, dict) and detail.get("modifier_name") == QUANTUM_ENTANGLE]
        if not before and len(after) == 1:
            return after[0]
    raise AssertionError("entangle add mutation missing")


def test_natural_quantum_break_entangle_count_settlement_recovery_and_second_break():
    scenario, rules, session, commands = open_route(QUANTUM_ROUTE)
    assert scenario["stage_ref"] == QUANTUM_STAGE_ID and scenario["wave_index"] == 0

    # 真实关卡：Monster 8011020 自带 Quantum 弱点与单层普通韧性。
    profile = rules.combatant_profile("monster:8011020")
    assert profile is not None and "Quantum" in profile.weaknesses
    enemy_before = session.state.units[QUANTUM_ENEMY]
    assert_enemy_source(session.state, QUANTUM_ENEMY, "Quantum", QUANTUM_STAGE_ID)
    assert session.state.units[QUANTUM_OTHER].side == "enemy"
    assert len(commands) == 6
    assert [command["actor_id"] for command in commands] == [
        "lynx", "natasha", QUANTUM_OTHER, QUANTUM_ENEMY, "lynx", "natasha",
    ]
    assert commands[0]["action_id"] == "avatar_skill:111001"
    assert commands[1]["action_id"] == "avatar_skill:110501"
    assert commands[4]["action_id"] == "avatar_skill:111001"
    assert commands[5]["action_id"] == "avatar_skill:110501"

    # 0. 真实波次入场：wave:transition 生成两只 8011020，随后打开玲可的决策。
    decision = advance_until_ready(session)
    wave_transitions = [transition for transition in advance_operations(session)
                        if transition["command"]["action_id"] == "wave:transition"]
    assert len(wave_transitions) == 1
    wave_events = list(wave_transitions[0]["events"])
    wave_types = event_types(wave_events)
    assert "wave.started" in wave_types
    started = next(event for event in wave_events if event_type(event) == "wave.started")
    assert event_payload(started)["stage_id"] == QUANTUM_STAGE_ID
    assert list(event_payload(started)["unit_ids"]) == [QUANTUM_ENEMY, QUANTUM_OTHER]
    spawned = [event_payload(event) for event in wave_events
               if event_type(event) == "wave.monster"]
    assert sorted(payload["monster_entity_ref"] for payload in spawned) == [
        "monster:8011020", "monster:8011020"]
    assert decision.token.actor_id == "lynx"
    assert_allies_alive(session.state)

    # 1. 玲可普攻首次击破：纠缠施加、计数初始 1、0.2×full_AV 行动延后。
    first_break = submit_formal_command(session, commands[0])
    first_events = transaction_events(first_break)
    first_mutations = transaction_mutations(first_break)
    first_types = event_types(first_events)
    assert "break.entered" in first_types and "break.triggered" in first_types
    triggered = break_triggered_events(first_events)
    assert len(triggered) == 1
    first_break_event_id = event_event_id(triggered[0])
    assert_single_break_triggered(
        first_events, "Quantum", QUANTUM_ENEMY, "lynx", QUANTUM_BREAK_TEMPLATE)
    assert_break_applied(session.state, QUANTUM_ENEMY)

    hp_rows = hp_mutations(first_mutations, QUANTUM_ENEMY)
    break_rows = [row for row in hp_rows
                  if row["metadata"].get("damage_formula_family") == "break"]
    direct_rows = [row for row in hp_rows
                   if row["metadata"].get("damage_formula_family") == "direct"]
    assert len(break_rows) == 1 and len(direct_rows) == 1
    assert break_rows[0]["metadata"]["element_type"] == "Quantum"
    assert break_rows[0]["metadata"]["break_template_id"] == QUANTUM_BREAK_TEMPLATE
    assert 0 < break_rows[0]["after"] < break_rows[0]["before"]

    timeline_rule, reason = rules.select_timeline_rule()
    assert timeline_rule is not None, reason
    full_av = TimelineSystem().full_action_value(
        effective_unit_stat(enemy_before, "speed").value, timeline_rule)
    delay_rows = action_value_mutations(first_mutations, QUANTUM_ENEMY)
    stance_delay = next(row for row in delay_rows
                        if row["metadata"].get("modifier_name") == "StanceBreakState")
    entangle_delay = next(row for row in delay_rows
                          if row["metadata"].get("modifier_name") == QUANTUM_ENTANGLE)
    assert stance_delay["after"] > stance_delay["before"]
    assert entangle_delay["after"] > entangle_delay["before"]
    assert stance_delay["after"] - stance_delay["before"] == pytest.approx(0.25 * full_av)
    # 纠缠 OnStack：MDF_ActionDelayRatio(0.2) × (1 + _CasterBreakDamageAddedRatio=0) × full_AV。
    assert entangle_delay["after"] - entangle_delay["before"] == pytest.approx(0.2 * full_av)

    entangle = _assert_quantum_entangle(
        require_status_detail(session.state, QUANTUM_ENEMY, QUANTUM_ENTANGLE),
        caster_id="lynx")
    entangle_adds = status_lifecycle_events(first_events, QUANTUM_ENTANGLE, "add")
    assert entangle_adds
    assert any(event_payload(event).get("status_instance_id") == entangle["instance_id"]
               for event in entangle_adds)

    # 2. 击破期间娜塔莎攻击命中同一目标：纠缠计数由实际命中 1→2。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "natasha"
    hp_before_hit = session.state.units[QUANTUM_ENEMY].hp
    hit = submit_formal_command(session, commands[1])
    assert not break_triggered_events(transaction_events(hit))
    assert session.state.units[QUANTUM_ENEMY].toughness == 0
    assert session.state.units[QUANTUM_ENEMY].flags["broken"] is True
    assert session.state.units[QUANTUM_ENEMY].hp < hp_before_hit
    counted = require_status_detail(session.state, QUANTUM_ENEMY, QUANTUM_ENTANGLE)
    assert counted["stacks"] == 2
    assert counted["lifecycle_state"] == "active"
    assert counted["dynamic_values"]["__by_hash"][QUANTUM_HIT_COUNT_HASH] == 1
    assert counted["dynamic_values"]["__by_hash"][QUANTUM_BE_HIT_FLAG_HASH] == 1
    changes = _quantum_count_changes(hit.transition.transaction.mutations)
    assert [(before, after) for before, after, _ in changes] == [(1, 2)]
    assert changes[0][2][QUANTUM_HIT_COUNT_HASH] == 1
    assert_allies_alive(session.state)

    # 3. E1 的自然行动（外部选择目标），目标 E0 仍保持击破/纠缠状态，尚未结算或恢复。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == QUANTUM_OTHER
    filler = submit_formal_command(session, commands[2])
    assert not break_triggered_events(transaction_events(filler))
    assert session.state.units[QUANTUM_ENEMY].toughness == 0
    assert session.state.units[QUANTUM_ENEMY].flags["broken"] is True
    assert require_status_detail(
        session.state, QUANTUM_ENEMY, QUANTUM_ENTANGLE)["stacks"] == 2
    assert_allies_alive(session.state)

    # 4. 目标自然回合：OnPhase1 只结算一次 break_dot_tick，随后纠缠到期移除，再做普通恢复。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == QUANTUM_ENEMY
    transitions = advance_operations(session)
    assert len(transitions) == 1
    turn = transitions[0]
    assert turn["command"]["action_id"] == "timeline:advance_to_next_turn"
    assert turn["coverage"]["pre_action_lifecycle"]["life_step_moment"] == "ModifierPhase1End"
    turn_events = list(turn["events"])
    turn_types = event_types(turn_events)
    turn_mutations = normalized_mutations(turn["mutations"])

    # 结算恰好一次（不是每回合 DOT），且伤害来源/参数可追溯。
    dot_rows = [row for row in hp_mutations(turn_mutations, QUANTUM_ENEMY)
                if row["metadata"].get("record_type") == "break_dot_tick"]
    assert len(dot_rows) == 1
    dot = dot_rows[0]
    assert dot["metadata"]["damage_formula_family"] == "break"
    assert dot["metadata"]["element_type"] == "Quantum"
    assert dot["metadata"]["modifier_name"] == QUANTUM_ENTANGLE
    assert dot["metadata"]["damage_source_kind"] == "status_damage"
    assert dot["metadata"]["damage_source_owner_id"] == "lynx"
    assert dot["metadata"]["break_template_id"] == QUANTUM_BREAK_TEMPLATE
    assert dot["metadata"]["status_damage_emission_id"]
    assert 0 < dot["after"] < dot["before"]

    # 结算 → 到期移除 → 恢复：事件顺序与 mutation 顺序一致，且不跳过目标行动。
    on_phase1 = [event for event in status_lifecycle_events(turn_events, QUANTUM_ENTANGLE, "tick")
                 if event_window(event) == "OnPhase1"]
    expires = status_lifecycle_events(turn_events, QUANTUM_ENTANGLE, "expire")
    assert len(on_phase1) == 1 and expires
    phase1_index = turn_events.index(on_phase1[0])
    lifecycle_tick_index = turn_types.index("status.lifecycle.tick")
    recovery_requested_index = turn_types.index("break.recovery_requested")
    recovered_index = turn_types.index("break.recovered")
    assert phase1_index < lifecycle_tick_index < recovery_requested_index < recovered_index
    assert "turn.control_skipped" not in turn_types

    dot_index = turn_mutations.index(dot)
    recovery_rows = [row for row in toughness_mutations(turn_mutations, QUANTUM_ENEMY)
                     if row["before"] == 0 and row["after"] == enemy_before.max_toughness]
    assert len(recovery_rows) == 1
    recovery_index = turn_mutations.index(recovery_rows[0])
    assert dot_index < recovery_index
    flags_rows = [row for row in turn_mutations
                  if row["path"][:3] == ("units", QUANTUM_ENEMY, "flags")
                  and row["path"][-1] == "broken" and row["before"] is True
                  and row["after"] is False]
    assert flags_rows

    recovering = session.state.units[QUANTUM_ENEMY]
    assert_stance_recovered(session.state, QUANTUM_ENEMY)
    assert QUANTUM_ENTANGLE_STATUS not in recovering.statuses
    assert status_details(session.state, QUANTUM_ENEMY, QUANTUM_ENTANGLE) == []
    assert recovering.hp == dot["after"]
    assert_allies_alive(session.state)

    # 目标在恢复后正常行动：纠缠不消耗行动，外部提交其怪物技能成功。
    action = submit_formal_command(session, commands[3])
    assert not break_triggered_events(transaction_events(action))
    assert session.state.units[QUANTUM_ENEMY].hp == recovering.hp
    assert_allies_alive(session.state)

    # 5. 恢复后同一目标被玲可再次击破：新的 break.triggered 与新 add 生命周期。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "lynx"
    second_break = submit_formal_command(session, commands[4])
    second_events = transaction_events(second_break)
    second_mutations = transaction_mutations(second_break)
    triggered = break_triggered_events(second_events)
    assert len(triggered) == 1
    second_break_event_id = event_event_id(triggered[0])
    assert second_break_event_id != first_break_event_id
    assert_single_break_triggered(
        second_events, "Quantum", QUANTUM_ENEMY, "lynx", QUANTUM_BREAK_TEMPLATE)
    assert break_damage_mutations(second_mutations, QUANTUM_ENEMY)
    assert_break_applied(session.state, QUANTUM_ENEMY)
    second_entangle = require_status_detail(session.state, QUANTUM_ENEMY, QUANTUM_ENTANGLE)
    assert second_entangle["caster_id"] == "lynx"
    assert second_entangle["remaining_duration"] == 1.0
    assert second_entangle["life_step_moment"] == "ModifierPhase1End"
    assert status_lifecycle_events(second_events, QUANTUM_ENTANGLE, "add")
    # 新生命周期计数从 1 重新开始：AddModifier 时的动态值不继承已过期实例
    # （MDF_BeingHitDamageValue=0、MDF_BeHitFlag=0；本次击破命中不额外加层）。
    added = _quantum_added_detail(second_break.transition.transaction.mutations)
    assert added["stacks"] == 1
    assert added["dynamic_values"]["__by_hash"][QUANTUM_HIT_COUNT_HASH] == 0
    assert added["dynamic_values"]["__by_hash"][QUANTUM_BE_HIT_FLAG_HASH] == 0
    assert second_entangle["stacks"] == 1
    assert second_entangle["dynamic_values"]["__by_hash"][QUANTUM_HIT_COUNT_HASH] == 0
    assert_allies_alive(session.state)

    # 6. 二次击破后的后续合法行动：娜塔莎命中击破中的目标并成功提交。
    decision = advance_until_ready(session)
    assert decision.token.actor_id == "natasha"
    choices = [(choice.actor_id, choice.action_id,
                list(getattr(choice.target_query, "candidate_ids", ()) or ()))
               for choice in decision.availability.choices]
    assert any(actor_id == "natasha" and action_id == commands[5]["action_id"]
               and QUANTUM_ENEMY in candidate_ids
               for actor_id, action_id, candidate_ids in choices)
    follow_up = submit_formal_command(session, commands[5])
    assert not break_triggered_events(transaction_events(follow_up))
    assert session.state.units[QUANTUM_ENEMY].hp > 0
    assert session.state.units[QUANTUM_ENEMY].flags["broken"] is True
    # 二次击破生命周期的实际命中同样使纠缠计数 1→2。
    second_counted = require_status_detail(session.state, QUANTUM_ENEMY, QUANTUM_ENTANGLE)
    assert second_counted["stacks"] == 2
    assert second_counted["dynamic_values"]["__by_hash"][QUANTUM_HIT_COUNT_HASH] == 1
    second_changes = _quantum_count_changes(follow_up.transition.transaction.mutations)
    assert [(before, after) for before, after, _ in second_changes] == [(1, 2)]
    assert_allies_alive(session.state)
    assert session.outcome == ""

    # 全局核对：整条路线只发生一次纠缠到期结算 DOT（不是每回合 DOT）；
    # 纠缠从不产生冻结式 control_skip；两次击破均为量子模板。
    all_transitions = []
    for operation in session.operations:
        if operation["kind"] == "submit":
            all_transitions.append(operation["transition"])
        else:
            all_transitions.extend(operation.get("transitions", ()))
    dot_ticks = [
        row for transition in all_transitions
        for row in normalized_mutations(transition.get("mutations", ()))
        if row["path"][:2] == ("units", QUANTUM_ENEMY) and row["path"][-1] == "hp"
        and row["metadata"].get("record_type") == "break_dot_tick"
        and row["metadata"].get("modifier_name") == QUANTUM_ENTANGLE
    ]
    assert len(dot_ticks) == 1
    all_event_types = [event_type(event) for transition in all_transitions
                       for event in transition.get("events", ())]
    assert "turn.control_skipped" not in all_event_types
    all_breaks = [event for transition in all_transitions
                  for event in break_triggered_events(transition.get("events", ()))]
    assert len(all_breaks) == 2
    assert all(event_payload(event)["target_id"] == QUANTUM_ENEMY for event in all_breaks)
    assert sum(1 for operation in session.operations
               if operation["kind"] == "submit") == len(commands)


# ---------------------------------------------------------------------------
# 虚数：同谐主普攻削 60→30 再击破 → 禁锢减速/延后 → 到期恢复 → 二次击破
# ---------------------------------------------------------------------------
IMAGINARY_ROUTE = "trailblazer_imaginary_break_natural"
IMAGINARY_STAGE_ID = "1022231"
IMAGINARY_ENEMY = "enemy:stage:1022231:wave:0:pos:0"
IMAGINARY_OTHER = "enemy:stage:1022231:wave:0:pos:1"
IMAGINARY_BREAK_TEMPLATE = "break_template:StanceBreak_Imaginary"
IMAGINARY_BREAK_STATUS_EMISSION = "break_status_emission:StanceBreak_Imaginary:1"
IMAGINARY_CONFINE = "MCommon_Element_Confine"
IMAGINARY_CONFINE_STATUS = "modifier:MCommon_Element_Confine"
IMAGINARY_SLOW_RATIO = -0.1
IMAGINARY_DELAY_RATIO = 0.3


def _assert_imaginary_confine_applied(result, state, base_speed, timeline_rule):
    """Confine 的 typed 减速条目、OnStack 延后参数与正式来源证据。"""
    broken = state.units[IMAGINARY_ENEMY]
    assert broken.toughness == 0
    assert broken.flags["broken"] is True
    assert broken.flags["break_element"] == "Imaginary"
    assert broken.flags["break_source"]["attacker_id"] == "trailblazer"
    assert STANCE_BREAK_STATE in broken.statuses
    assert IMAGINARY_CONFINE_STATUS in broken.statuses
    assert MONSTER_DAMAGE_REDUCE not in broken.statuses
    # 基础速度不被改写；减速是类型化的状态 modifier 条目。
    assert broken.speed == pytest.approx(base_speed)
    assert effective_unit_stat(broken, "speed").value == pytest.approx(
        base_speed * (1.0 + IMAGINARY_SLOW_RATIO))
    detail = require_status_detail(state, IMAGINARY_ENEMY, IMAGINARY_CONFINE)
    assert detail["caster_id"] == "trailblazer"
    assert detail["source_id"] == IMAGINARY_BREAK_STATUS_EMISSION
    assert detail["instance_id"]
    assert detail["stacks"] == 1
    assert detail["remaining_duration"] == 1.0
    assert detail["life_step_moment"] == "ModifierPhase1End"
    assert detail["duration_admission"]["admission_status"] == "executable"
    speed_terms = [modifier for modifier in detail["modifiers"]
                   if modifier.get("bucket") == "attribute"
                   and modifier.get("key") == "speed_added_ratio"]
    assert len(speed_terms) == 1
    assert speed_terms[0]["value"] == pytest.approx(IMAGINARY_SLOW_RATIO)
    assert speed_terms[0]["property"] == "SpeedAddedRatio"
    by_name = detail["dynamic_values"]["__by_name"]
    assert by_name["MDF_SpeedDownRatio"] == pytest.approx(0.1)
    assert by_name["MDF_ActionDelayRatio"] == pytest.approx(IMAGINARY_DELAY_RATIO)
    assert by_name["_CasterBreakDamageAddedRatio"] == pytest.approx(0.0)
    # StanceBreakState 的 0.25 延后是另一条生命周期 mutation；此处核对 Confine 的
    # OnStack 延后 = 0.3 × 减速后 holder 的 full AV。
    delays = [row for row in
              action_value_mutations(transaction_mutations(result), IMAGINARY_ENEMY)
              if row["metadata"].get("modifier_name") == IMAGINARY_CONFINE]
    assert len(delays) == 1
    delay = delays[0]
    metadata = delay["metadata"]
    assert metadata["event"] == "OnStack"
    assert metadata["callback_id"].endswith("MCommon_Element_Confine:118:OnStack")
    assert metadata["normalized_value"] == pytest.approx(IMAGINARY_DELAY_RATIO)
    full_av = TimelineSystem().full_action_value(
        base_speed * (1.0 + IMAGINARY_SLOW_RATIO), timeline_rule)
    assert delay["after"] - delay["before"] == pytest.approx(
        IMAGINARY_DELAY_RATIO * full_av)
    return detail


def test_natural_imaginary_break_confine_slow_delay_expiry_recovery_and_second_break():
    scenario, rules, session, commands = open_route(IMAGINARY_ROUTE)
    assert scenario["stage_ref"] == IMAGINARY_STAGE_ID and scenario["wave_index"] == 0
    builds = {unit["unit_id"]: unit["character_build"] for unit in scenario["units"]}
    assert (builds["trailblazer"]["level"], builds["trailblazer"]["eidolon_level"]) == (1, 0)
    assert (builds["natasha"]["level"], builds["natasha"]["promotion"],
            builds["natasha"]["eidolon_level"]) == (80, 6, 0)

    # 来源卡拥有 Imaginary 弱点与普通单层韧性（60，两发普攻一层击破）。
    profile = rules.combatant_profile("monster:1022020")
    assert profile is not None and "Imaginary" in profile.weaknesses
    assert_enemy_source(session.state, IMAGINARY_ENEMY, "Imaginary", IMAGINARY_STAGE_ID,
                        max_toughness=60.0)
    enemy_before = session.state.units[IMAGINARY_ENEMY]
    base_speed = enemy_before.speed
    assert session.state.units[IMAGINARY_OTHER].side == "enemy"
    timeline_rule, reason = rules.select_timeline_rule()
    assert timeline_rule is not None, reason
    assert_allies_alive(session.state)

    assert len(commands) == 15
    assert [command["actor_id"] for command in commands] == [
        "trailblazer", IMAGINARY_ENEMY, IMAGINARY_ENEMY, IMAGINARY_OTHER, "natasha",
        "trailblazer", IMAGINARY_OTHER, "natasha", IMAGINARY_ENEMY, "trailblazer",
        IMAGINARY_OTHER, "natasha", IMAGINARY_ENEMY, "trailblazer", IMAGINARY_OTHER,
    ]
    assert commands[1]["action_id"] == TIMELINE_TIE_ACTION

    # 1. 同谐主正式普攻削掉第一层普通韧性（60 → 30），尚未击破。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[0])
    assert decision.token.actor_id == "trailblazer"
    opening_hit = submit_formal_command(session, commands[0])
    assert not break_triggered_events(transaction_events(opening_hit))
    assert session.state.units[IMAGINARY_ENEMY].toughness == 30
    assert_allies_alive(session.state)

    # 2. 两只 Lv32 士兵同速；同速选择是公开决策，提交后才进入 pos0 的怪物技能。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[1])
    assert all(choice.choice_kind == "timeline_actor"
               for choice in decision.availability.choices)
    tie = submit_formal_command(session, commands[1])
    assert tie.transition.outcome.successor_eligible

    # 3-4. 两只来源敌人都自然行动（外部选择目标为娜塔莎）；韧性层不受影响。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[2])
    assert decision.token.actor_id == IMAGINARY_ENEMY
    first_enemy_turn = submit_formal_command(session, commands[2])
    assert not break_triggered_events(transaction_events(first_enemy_turn))
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[3])
    assert decision.token.actor_id == IMAGINARY_OTHER
    second_enemy_turn = submit_formal_command(session, commands[3])
    assert not break_triggered_events(transaction_events(second_enemy_turn))
    assert session.state.units[IMAGINARY_ENEMY].toughness == 30
    assert_allies_alive(session.state)

    # 5. 娜塔莎正式治疗作为合法非伤害填充动作。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[4])
    assert decision.token.actor_id == "natasha"
    filler = submit_formal_command(session, commands[4])
    assert not break_triggered_events(transaction_events(filler))
    assert session.state.units[IMAGINARY_ENEMY].toughness == 30
    assert_allies_alive(session.state)

    # 6. 首次虚数击破：禁锢施加减速与 OnStack 延后。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[5])
    assert decision.token.actor_id == "trailblazer"
    first_break = submit_formal_command(session, commands[5])
    assert_single_break_triggered(
        transaction_events(first_break), "Imaginary", IMAGINARY_ENEMY,
        "trailblazer", IMAGINARY_BREAK_TEMPLATE)
    entered = [event for event in transaction_events(first_break)
               if event_type(event) == "break.entered"]
    assert len(entered) == 1 and event_payload(entered[0])["element_type"] == "Imaginary"
    assert_break_damage(transaction_mutations(first_break), IMAGINARY_ENEMY,
                        "Imaginary", IMAGINARY_BREAK_TEMPLATE)
    break_status_records = settlement_records(first_break, "break_status")
    assert len(break_status_records) == 1
    assert break_status_records[0]["payload"]["break_status_emission_id"] == (
        IMAGINARY_BREAK_STATUS_EMISSION)
    first_confine = _assert_imaginary_confine_applied(
        first_break, session.state, base_speed, timeline_rule)
    hp_after_first_break = session.state.units[IMAGINARY_ENEMY].hp
    assert_allies_alive(session.state)

    # 7-8. 同伴敌人行动、娜塔莎治疗；holder 仍处于击破/禁锢并保持减速。
    for index, actor in ((6, IMAGINARY_OTHER), (7, "natasha")):
        decision = advance_until_ready(session)
        assert_command_available(decision, commands[index])
        assert decision.token.actor_id == actor
        filler = submit_formal_command(session, commands[index])
        assert not break_triggered_events(transaction_events(filler))
        held = session.state.units[IMAGINARY_ENEMY]
        assert held.toughness == 0
        assert held.hp == pytest.approx(hp_after_first_break)
        assert held.flags["broken"] is True
        held_confine = require_status_detail(
            session.state, IMAGINARY_ENEMY, IMAGINARY_CONFINE)
        assert held_confine["instance_id"] == first_confine["instance_id"]
        assert effective_unit_stat(held, "speed").value == pytest.approx(
            base_speed * (1.0 + IMAGINARY_SLOW_RATIO))
        assert_allies_alive(session.state)

    # 9. holder 自己的 ModifierPhase1End 到期移除禁锢（速度恢复），随后普通击破恢复
    #    韧性层，最后才执行其自然行动。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[8])
    assert decision.token.actor_id == IMAGINARY_ENEMY
    recovery_transitions = [transition for transition in advance_operations(session)
                            if (transition.get("coverage") or {}).get("pre_action_lifecycle")]
    assert len(recovery_transitions) == 1
    recovery = recovery_transitions[0]
    lifecycle = recovery["coverage"]["pre_action_lifecycle"]
    assert lifecycle["life_step_moment"] == "ModifierPhase1End"
    recovery_mutations = normalized_mutations(recovery["mutations"])
    expiry_details = [
        row for row in recovery_mutations
        if row["path"] == ("units", IMAGINARY_ENEMY, "flags", "status_details")
        and row["metadata"].get("operation") == "expire"
        and IMAGINARY_CONFINE in [detail.get("modifier_name")
                                  for detail in (row["before"] or ())]
        and IMAGINARY_CONFINE not in [detail.get("modifier_name")
                                      for detail in (row["after"] or ())]
    ]
    assert len(expiry_details) == 1
    recovery_toughness = [row for row in toughness_mutations(recovery_mutations, IMAGINARY_ENEMY)
                          if row["before"] == 0]
    assert len(recovery_toughness) == 1
    assert recovery_toughness[0]["after"] == enemy_before.max_toughness
    assert "StanceBreakState:2:OnDestroy" in (
        recovery_toughness[0]["metadata"] or {}).get("callback_id", "")
    reduction_restored = any(
        row["path"] == ("units", IMAGINARY_ENEMY, "flags", "status_details")
        and "MonsterAllDamageReduce" in [detail.get("modifier_name")
                                         for detail in (row["after"] or ())]
        for row in recovery_mutations)
    assert reduction_restored
    recovery_types = event_types(recovery["events"])
    assert (recovery_types.index("status.lifecycle.tick")
            < recovery_types.index("break.recovery_requested")
            < recovery_types.index("break.recovered"))
    restored = session.state.units[IMAGINARY_ENEMY]
    assert_stance_recovered(session.state, IMAGINARY_ENEMY)
    assert IMAGINARY_CONFINE_STATUS not in restored.statuses
    assert status_details(session.state, IMAGINARY_ENEMY, IMAGINARY_CONFINE) == []
    assert effective_unit_stat(restored, "speed").value == pytest.approx(base_speed)
    holder_turn = submit_formal_command(session, commands[8])
    assert not break_triggered_events(transaction_events(holder_turn))
    assert_allies_alive(session.state)

    # 10. 恢复后的韧性层再吃一发普攻（60 → 30），尚未二次击破。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[9])
    assert decision.token.actor_id == "trailblazer"
    second_hit = submit_formal_command(session, commands[9])
    assert not break_triggered_events(transaction_events(second_hit))
    assert session.state.units[IMAGINARY_ENEMY].toughness == 30
    assert_allies_alive(session.state)

    # 11-13. 填充动作后，同一目标被二次击破（新生命周期）。
    for index, actor in ((10, IMAGINARY_OTHER), (11, "natasha"), (12, IMAGINARY_ENEMY)):
        decision = advance_until_ready(session)
        assert_command_available(decision, commands[index])
        assert decision.token.actor_id == actor
        filler = submit_formal_command(session, commands[index])
        assert not break_triggered_events(transaction_events(filler))
        assert session.state.units[IMAGINARY_ENEMY].toughness == 30
        assert_allies_alive(session.state)
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[13])
    assert decision.token.actor_id == "trailblazer"
    second_break = submit_formal_command(session, commands[13])
    assert_single_break_triggered(
        transaction_events(second_break), "Imaginary", IMAGINARY_ENEMY,
        "trailblazer", IMAGINARY_BREAK_TEMPLATE)
    assert_break_damage(transaction_mutations(second_break), IMAGINARY_ENEMY,
                        "Imaginary", IMAGINARY_BREAK_TEMPLATE)
    second_confine = _assert_imaginary_confine_applied(
        second_break, session.state, base_speed, timeline_rule)
    # 上一次 holder 回合到期后重新施加：同来源身份、新击破事件、剩余时间重置为 1。
    assert second_confine["source_id"] == IMAGINARY_BREAK_STATUS_EMISSION
    assert second_confine["remaining_duration"] == 1.0
    assert second_confine["instance_id"] == first_confine["instance_id"]
    assert_allies_alive(session.state)

    # 14. 二次击破后仍有合法外部行动且成功；战斗可以仍未结束。
    decision = advance_until_ready(session)
    assert_command_available(decision, commands[14])
    assert decision.token.actor_id == IMAGINARY_OTHER
    follow_up = submit_formal_command(session, commands[14])
    assert not break_triggered_events(transaction_events(follow_up))
    assert session.outcome == ""
    assert session.state.units[IMAGINARY_ENEMY].hp > 0
    assert_allies_alive(session.state)

    submits = [operation for operation in session.operations if operation["kind"] == "submit"]
    assert len(submits) == len(commands)
