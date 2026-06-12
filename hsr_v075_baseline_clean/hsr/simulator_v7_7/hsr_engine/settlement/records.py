"""Phase 2: 结算记录类型。

每种记录对应引擎里的一类状态变更。所有字段固定，
确保结算单的每一条都能追溯到引擎内的具体计算位置。

所有 dataclass 字段均有默认值，方便 SettlementCollector 通过 **kwargs 构造。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# 伤害记录
# ---------------------------------------------------------------------------

@dataclass
class DamageRecord:
    """一段直接伤害的完整结算记录。"""
    packet_index: int = 0
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


@dataclass
class TurnRecord:
    """回合开始/结束。"""
    unit_id: str = ""
    turn_kind: str = ""
    event_type: str = ""
    action_id: str = ""


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
