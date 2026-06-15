"""Phase 2: 结算记录类型。

每种记录对应引擎里的一类状态变更。所有字段固定，
确保结算单的每一条都能追溯到引擎内的具体计算位置。

所有 dataclass 字段均有默认值，方便 SettlementCollector 通过 **kwargs 构造。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, asdict, is_dataclass
from typing import Any


ACTION_SETTLEMENT_ENCODING = "hsr.settlement.action.v1"


def _record_to_dict(record: Any) -> dict[str, Any]:
    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    if isinstance(record, dict):
        return deepcopy(record)
    raise TypeError(f"unsupported settlement record type: {type(record).__name__}")


def _record_list_to_dicts(records: list[Any]) -> list[dict[str, Any]]:
    return [_record_to_dict(record) for record in records]


@dataclass
class ActionSettlement:
    """一次动作输入产生的完整结算结果。"""
    damage_records: list[DamageRecord | dict[str, Any]] = field(default_factory=list)
    shield_records: list[ShieldRecord | dict[str, Any]] = field(default_factory=list)
    hp_records: list[HPRecord | dict[str, Any]] = field(default_factory=list)
    energy_records: list[EnergyRecord | dict[str, Any]] = field(default_factory=list)
    sp_records: list[SPRecord | dict[str, Any]] = field(default_factory=list)
    status_records: list[StatusRecord | dict[str, Any]] = field(default_factory=list)
    av_records: list[AVRecord | dict[str, Any]] = field(default_factory=list)
    turn_records: list[TurnRecord | dict[str, Any]] = field(default_factory=list)
    queue_records: list[QueueRecord | dict[str, Any]] = field(default_factory=list)
    trigger_usage_records: list[TriggerUsageRecord | dict[str, Any]] = field(default_factory=list)
    mechanic_records: list[MechanicRecord | dict[str, Any]] = field(default_factory=list)
    break_records: list[BreakRecord | dict[str, Any]] = field(default_factory=list)
    toughness_records: list[ToughnessRecord | dict[str, Any]] = field(default_factory=list)
    dot_records: list[DotRecord | dict[str, Any]] = field(default_factory=list)
    super_break_records: list[SuperBreakRecord | dict[str, Any]] = field(default_factory=list)
    target_record: TargetRecord | dict[str, Any] | None = None
    settlement_record_validation: dict[str, Any] = field(default_factory=dict)
    transition: dict[str, Any] = field(default_factory=dict)
    encoding: str = ACTION_SETTLEMENT_ENCODING

    def to_dict(self) -> dict[str, Any]:
        target_record = _record_to_dict(self.target_record) if self.target_record is not None else None
        return {
            "encoding": self.encoding,
            "damage_records": _record_list_to_dicts(self.damage_records),
            "shield_records": _record_list_to_dicts(self.shield_records),
            "hp_records": _record_list_to_dicts(self.hp_records),
            "energy_records": _record_list_to_dicts(self.energy_records),
            "sp_records": _record_list_to_dicts(self.sp_records),
            "status_records": _record_list_to_dicts(self.status_records),
            "av_records": _record_list_to_dicts(self.av_records),
            "turn_records": _record_list_to_dicts(self.turn_records),
            "queue_records": _record_list_to_dicts(self.queue_records),
            "trigger_usage_records": _record_list_to_dicts(self.trigger_usage_records),
            "mechanic_records": _record_list_to_dicts(self.mechanic_records),
            "break_records": _record_list_to_dicts(self.break_records),
            "toughness_records": _record_list_to_dicts(self.toughness_records),
            "dot_records": _record_list_to_dicts(self.dot_records),
            "super_break_records": _record_list_to_dicts(self.super_break_records),
            "target_record": target_record,
            "settlement_record_validation": deepcopy(self.settlement_record_validation),
            "transition": deepcopy(self.transition),
        }


# ---------------------------------------------------------------------------
# 伤害记录
# ---------------------------------------------------------------------------

@dataclass
class DamageRecord:
    """一段直接伤害的完整结算记录。"""
    packet_index: int = 0
    packet_id: str = ""
    source_action_id: str = ""
    actor_id: str = ""
    target_id: str = ""
    element: str = ""
    damage_type: str = "direct_damage"
    base_damage: float = 0.0
    crit: bool = False
    crit_dmg_mult: float = 1.0
    dmg_bonus_mult: float = 1.0
    def_mult: float = 1.0
    res_mult: float = 1.0
    dmg_taken_mult: float = 1.0
    toughness_mult: float = 1.0
    final_damage: float = 0.0
    damage_applied: float = 0.0
    shield_absorbed: float = 0.0
    hp_loss: float = 0.0
    overkill: float = 0.0
    is_overkill: bool = False
    formula_ledger: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 护盾 / 血量 / 能量 / 战技点 记录
# ---------------------------------------------------------------------------

@dataclass
class ShieldRecord:
    """护盾变化：加盾或扣盾。"""
    unit_id: str = ""
    old_shield: float = 0.0
    new_shield: float = 0.0
    delta: float = 0.0
    reason: str = ""
    source_id: str = ""


@dataclass
class HPRecord:
    """血量变化：扣血或治疗。"""
    unit_id: str = ""
    old_hp: float = 0.0
    new_hp: float = 0.0
    delta: float = 0.0
    reason: str = ""
    source_id: str = ""
    overkill: float = 0.0


@dataclass
class EnergyRecord:
    """能量变化。"""
    unit_id: str = ""
    old_energy: float = 0.0
    new_energy: float = 0.0
    delta: float = 0.0
    max_energy: float = 0.0
    source_type: str = ""
    source_id: str = ""
    label: str = ""


@dataclass
class SPRecord:
    """战技点变化。"""
    old_sp: int = 0
    new_sp: int = 0
    delta: int = 0
    sp_cap: int = 5
    reason: str = ""
    source_id: str = ""


# ---------------------------------------------------------------------------
# Buff/Debuff 记录
# ---------------------------------------------------------------------------

@dataclass
class StatusRecord:
    """Buff/Debuff 的挂载、移除、层数变化。"""
    unit_id: str = ""
    status_id: str = ""
    status_name_cn: str = ""
    status_type: str = ""                       # Buff / Debuff / Other
    change_type: str = ""
    old_stacks: int = 0
    new_stacks: int = 0
    max_stacks: int = 0
    duration_type: str = ""
    duration_value: float = 0.0
    source_id: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# 行动轴 / 回合 记录
# ---------------------------------------------------------------------------

@dataclass
class AVRecord:
    """行动值变化（拉条、推条、回合推进）。"""
    unit_id: str = ""
    old_remaining_av: float = 0.0
    new_remaining_av: float = 0.0
    delta: float = 0.0
    reason: str = ""
    source_id: str = ""
    old_absolute_av: float = 0.0
    new_absolute_av: float = 0.0
    speed: float = 0.0
    action_interval: float | None = None
    detail: str = ""


@dataclass
class TurnRecord:
    """回合开始/结束。"""
    unit_id: str = ""
    turn_kind: str = ""
    event_type: str = ""
    action_id: str = ""


# ---------------------------------------------------------------------------
# 队列 / 触发次数记录
# ---------------------------------------------------------------------------

@dataclass
class QueueRecord:
    """队列变化：入队、出队或替换队列内容。"""
    queue_name: str = ""
    operation: str = ""
    old_queue: list[dict[str, Any]] = field(default_factory=list)
    new_queue: list[dict[str, Any]] = field(default_factory=list)
    delta: dict[str, Any] = field(default_factory=dict)
    item: dict[str, Any] = field(default_factory=dict)
    requested_queue: str = ""
    reason: str = ""
    source_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TriggerUsageRecord:
    """触发器使用次数变化。"""
    key: str = ""
    old_count: int = 0
    new_count: int | None = 0
    delta: int | str = 0
    reason: str = ""
    source_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 机制事件
# ---------------------------------------------------------------------------

@dataclass
class MechanicRecord:
    """特殊机制事件：破韧、转阶段、被动触发等。"""
    event_type: str = ""
    unit_id: str = ""
    description: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 目标记录
# ---------------------------------------------------------------------------

@dataclass
class TargetRecord:
    """本次行动指定的目标列表。"""
    action_id: str = ""
    actor_id: str = ""
    target_ids: list[str] = field(default_factory=list)
    target_selection_reason: str = ""


# ---------------------------------------------------------------------------
# 击破 / 韧性 / DoT 记录
# ---------------------------------------------------------------------------

@dataclass
class BreakRecord:
    """弱点击破事件：破韧瞬间产生的击破伤害 + 后续状态。"""
    actor_id: str = ""                          # 谁打出了击破
    target_id: str = ""                         # 被击破的单位
    element: str = ""                           # 击破元素
    base_break_damage: float = 0.0              # 击破基础伤害（等级公式）
    element_mult: float = 1.0                   # 元素倍率
    toughness_mult: float = 1.0                 # 韧性倍率
    break_effect_mult: float = 1.0              # 击破特攻倍率（1 + BE）
    final_break_damage: float = 0.0             # 最终击破伤害
    damage_applied: float = 0.0                 # 实际造成伤害
    shield_absorbed: float = 0.0                # 护盾吸收
    hp_loss: float = 0.0                        # HP 损失
    aftermath_status_id: str = ""               # 击破后挂载的 aftermath 状态 ID


@dataclass
class ToughnessRecord:
    """韧性条变化：每次减韧 + 破韧瞬间。"""
    unit_id: str = ""
    old_toughness: float = 0.0
    new_toughness: float = 0.0
    delta: float = 0.0
    is_break: bool = False                      # 是否为破韧瞬间
    element: str = ""                           # 造成韧性削减的元素
    source_id: str = ""
    reason: str = ""


@dataclass
class DotRecord:
    """DoT 周期伤害：一次跳伤害的完整结算。"""
    unit_id: str = ""                           # 受伤害单位
    source_status_id: str = ""                  # 来源 DoT 状态 ID
    element: str = ""                           # 元素
    kind: str = ""                              # bleed / burn / shock / wind_shear / freeze_thaw / entanglement
    base_damage: float = 0.0                    # DoT 基础伤害（break_dot_base_damage）
    per_stack: bool = False                     # 是否每层独立
    stacks: int = 1                             # 当前层数
    break_effect_mult: float = 1.0
    def_mult: float = 1.0
    res_mult: float = 1.0
    dmg_taken_mult: float = 1.0
    final_damage: float = 0.0
    damage_applied: float = 0.0
    shield_absorbed: float = 0.0
    hp_loss: float = 0.0


@dataclass
class SuperBreakRecord:
    """超击破伤害：对已破韧目标的每次伤害附带的超击破结算。"""
    actor_id: str = ""
    target_id: str = ""
    element: str = ""
    base_damage: float = 0.0                    # break_base_damage(level)
    toughness_reduction: float = 0.0             # 本次削韧量（用于 toughness_mult）
    toughness_mult: float = 1.0                  # super_break_toughness_multiplier
    break_effect_mult: float = 1.0               # 1 + break_effect
    super_break_bonus: float = 1.0               # 超击破增伤乘区
    def_mult: float = 1.0
    res_mult: float = 1.0
    dmg_taken_mult: float = 1.0
    final_damage: float = 0.0
    damage_applied: float = 0.0
    shield_absorbed: float = 0.0
    hp_loss: float = 0.0


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ENERGY_SOURCE_ACTION = "action_energy"
ENERGY_SOURCE_HIT_TAKEN = "hit_taken"
ENERGY_SOURCE_KILL = "kill_energy"
ENERGY_SOURCE_COST = "energy_cost"
ENERGY_SOURCE_EFFECT = "effect_energy"

AV_REGULAR_TURN = "regular_turn_end"
AV_ADVANCE = "action_advance"
AV_DELAY = "action_delay"
AV_TIMELINE_TICK = "timeline_tick"

BREAK_EVENT = "weakness_break"
TOUGHNESS_REDUCTION = "toughness_reduction"
DOT_TICK = "dot_tick"
DOT_SOURCE_BREAK = "break_aftermath"
DOT_SOURCE_STATUS = "status_dot"
