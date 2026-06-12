"""Phase 2: 结算收集器。

在引擎执行过程中收集各类结算记录，引擎状态变更与记录写入发生在同一代码位置。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from .records import (
    DamageRecord,
    ShieldRecord,
    HPRecord,
    EnergyRecord,
    SPRecord,
    StatusRecord,
    AVRecord,
    TurnRecord,
    MechanicRecord,
    TargetRecord,
    BreakRecord,
    ToughnessRecord,
    DotRecord,
    SuperBreakRecord,
)


@dataclass
class SettlementCollector:
    """结算收集器——在 resolve_route_step 中创建，通过 action_ctx 传递。

    可选注册表（text_map / status_registry / skill_registry）用于自动补全中文名。
    无注册表时 collector 仍正常工作，不抛异常。
    """

    # 按记录类型分组（保持发生顺序）
    damage_records: list[DamageRecord] = field(default_factory=list)
    shield_records: list[ShieldRecord] = field(default_factory=list)
    hp_records: list[HPRecord] = field(default_factory=list)
    energy_records: list[EnergyRecord] = field(default_factory=list)
    sp_records: list[SPRecord] = field(default_factory=list)
    status_records: list[StatusRecord] = field(default_factory=list)
    av_records: list[AVRecord] = field(default_factory=list)
    turn_records: list[TurnRecord] = field(default_factory=list)
    mechanic_records: list[MechanicRecord] = field(default_factory=list)
    break_records: list[BreakRecord] = field(default_factory=list)
    toughness_records: list[ToughnessRecord] = field(default_factory=list)
    dot_records: list[DotRecord] = field(default_factory=list)
    super_break_records: list[SuperBreakRecord] = field(default_factory=list)
    target_record: TargetRecord | None = None

    def __init__(
        self,
        text_map: Any = None,
        status_registry: Any = None,
        skill_registry: Any = None,
    ) -> None:
        self.damage_records = []
        self.shield_records = []
        self.hp_records = []
        self.energy_records = []
        self.sp_records = []
        self.status_records = []
        self.av_records = []
        self.turn_records = []
        self.mechanic_records = []
        self.break_records = []
        self.toughness_records = []
        self.dot_records = []
        self.super_break_records = []
        self.target_record = None
        self._text_map = text_map
        self._status_registry = status_registry
        self._skill_registry = skill_registry

    # ── 便捷记录方法 (主代码通过 _settle(ctx, record_type, **kwargs) 调用) ──

    def record_target(self, target_ids: list[str], method: str = "explicit") -> None:
        self.target_record = TargetRecord(
            action_id="", actor_id="",
            target_ids=list(target_ids), target_selection_reason=method,
        )

    def record_damage(self, **kwargs: Any) -> None:
        """kwargs 映射到 DamageRecord 字段名不匹配时做转换。"""
        mapped = {}
        for k, v in kwargs.items():
            if k == "crit_multiplier":
                mapped["crit_dmg_mult"] = v
            elif k == "dmg_bonus_multiplier":
                mapped["dmg_bonus_mult"] = v
            elif k == "def_multiplier":
                mapped["def_mult"] = v
            elif k == "res_multiplier":
                mapped["res_mult"] = v
            elif k == "damage_taken_multiplier":
                mapped["dmg_taken_mult"] = v
            elif k == "universal_reduction_multiplier" or k == "toughness_state_multiplier":
                mapped["toughness_mult"] = v
            elif k == "applied_damage":
                mapped["damage_applied"] = v
            elif k in DamageRecord.__dataclass_fields__:
                mapped[k] = v
        self.damage_records.append(DamageRecord(**mapped))

    def record_sp(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_sp"] = int(v)
            elif k == "new_value":
                mapped["new_sp"] = int(v)
            elif k == "max_value":
                mapped["sp_cap"] = int(v)
            elif k == "reason":
                mapped["reason"] = f"{v}: {kwargs.get('reason_detail', '')}"
            elif k == "source_unit_id":
                mapped["source_id"] = str(v)
            elif k in ("delta",):
                mapped[k] = int(v)
            elif k in SPRecord.__dataclass_fields__:
                mapped[k] = v
        self.sp_records.append(SPRecord(**mapped))

    def record_energy(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_energy"] = float(v)
            elif k == "new_value":
                mapped["new_energy"] = float(v)
            elif k == "source_detail":
                mapped["label"] = str(v)
            elif k in ("affected_by_err",):
                pass  # 元信息，不存入记录
            elif k in EnergyRecord.__dataclass_fields__:
                mapped[k] = v
        self.energy_records.append(EnergyRecord(**mapped))

    def record_shield(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_shield"] = float(v)
            elif k == "new_value":
                mapped["new_shield"] = float(v)
            elif k in ShieldRecord.__dataclass_fields__:
                mapped[k] = v
        self.shield_records.append(ShieldRecord(**mapped))

    def record_hp(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_hp"] = float(v)
            elif k == "new_value":
                mapped["new_hp"] = float(v)
            elif k == "reason":
                mapped["reason"] = str(v)
            elif k in HPRecord.__dataclass_fields__:
                mapped[k] = v
        self.hp_records.append(HPRecord(**mapped))

    def record_status(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "target_unit_id":
                mapped["unit_id"] = str(v)
            elif k == "source_unit_id":
                mapped["source_id"] = str(v)
            elif k == "stacks_before":
                mapped["old_stacks"] = int(v)
            elif k == "stacks_after":
                mapped["new_stacks"] = int(v)
            elif k == "trigger_reason":
                mapped["reason"] = str(v)
            elif k == "modifier_keys":
                pass  # 摘要信息，不存入
            elif k in StatusRecord.__dataclass_fields__:
                mapped[k] = v
        rec = StatusRecord(**mapped)
        # Phase 2.5: 自动补中文名 / status_type
        if self._status_registry is not None and rec.status_id:
            try:
                info = self._status_registry.lookup(int(rec.status_id))
                if info is not None:
                    if not rec.status_name_cn:
                        rec.status_name_cn = info.name_cn
                    if not rec.status_type:
                        rec.status_type = info.status_type
            except (ValueError, TypeError):
                pass
        self.status_records.append(rec)

    def record_av(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k in ("old_absolute_av", "new_absolute_av", "speed", "action_interval"):
                pass  # 可从 remaining_av 推导
            elif k == "change_type":
                mapped["reason"] = str(v)
            elif k == "change_detail":
                if "reason" not in mapped:
                    mapped["reason"] = str(v)
            elif k == "old_remaining_av":
                mapped["old_remaining_av"] = float(v)
            elif k == "new_remaining_av":
                new_val = float(v)
                mapped["new_remaining_av"] = new_val
                mapped["delta"] = new_val - float(kwargs.get("old_remaining_av", new_val))
            elif k in AVRecord.__dataclass_fields__:
                mapped[k] = v
        self.av_records.append(AVRecord(**mapped))

    def record_turn(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "event":
                mapped["event_type"] = str(v)
            elif k in TurnRecord.__dataclass_fields__:
                mapped[k] = v
        self.turn_records.append(TurnRecord(**mapped))

    def record_mechanic(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k in MechanicRecord.__dataclass_fields__:
                mapped[k] = v
            elif k == "detail":
                mapped["description"] = str(v)
            elif k == "data":
                mapped["data"] = dict(v) if isinstance(v, dict) else {}
        self.mechanic_records.append(MechanicRecord(**mapped))

    def record_break(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "break_effect":
                mapped["break_effect_mult"] = float(v)
            elif k == "aftermath_status":
                mapped["aftermath_status_id"] = str(v)
            elif k in BreakRecord.__dataclass_fields__:
                mapped[k] = v
        self.break_records.append(BreakRecord(**mapped))

    def record_toughness(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_toughness"] = float(v)
            elif k == "new_value":
                mapped["new_toughness"] = float(v)
            elif k in ToughnessRecord.__dataclass_fields__:
                mapped[k] = v
        self.toughness_records.append(ToughnessRecord(**mapped))

    def record_dot(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "break_effect":
                mapped["break_effect_mult"] = float(v)
            elif k == "source_status":
                mapped["source_status_id"] = str(v)
            elif k in DotRecord.__dataclass_fields__:
                mapped[k] = v
        self.dot_records.append(DotRecord(**mapped))

    def record_super_break(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "break_effect":
                mapped["break_effect_mult"] = float(v)
            elif k == "super_break_bonus_mult":
                mapped["super_break_bonus"] = float(v)
            elif k in SuperBreakRecord.__dataclass_fields__:
                mapped[k] = v
        self.super_break_records.append(SuperBreakRecord(**mapped))

    # ── 序列化 ──

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 兼容字典，供 run_route 写入 trace_entry。"""
        return {
            "damage_records": [asdict(r) for r in self.damage_records],
            "shield_records": [asdict(r) for r in self.shield_records],
            "hp_records": [asdict(r) for r in self.hp_records],
            "energy_records": [asdict(r) for r in self.energy_records],
            "sp_records": [asdict(r) for r in self.sp_records],
            "status_records": [asdict(r) for r in self.status_records],
            "av_records": [asdict(r) for r in self.av_records],
            "turn_records": [asdict(r) for r in self.turn_records],
            "mechanic_records": [asdict(r) for r in self.mechanic_records],
            "break_records": [asdict(r) for r in self.break_records],
            "toughness_records": [asdict(r) for r in self.toughness_records],
            "dot_records": [asdict(r) for r in self.dot_records],
            "super_break_records": [asdict(r) for r in self.super_break_records],
            "target_record": asdict(self.target_record) if self.target_record else None,
        }
