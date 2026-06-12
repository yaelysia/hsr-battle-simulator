"""Phase 2: 结算收集器。

在引擎执行过程中收集各类结算记录，引擎状态变更与记录写入发生在同一代码位置。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, asdict
from typing import Any

from hsr_engine.kernel import ActionRequest, ActionTransition, ProcessEvent, RNGEvent, SourceRef, StateChange, TargetResolution
from hsr_engine.transition_reducer import validate_transition_replay

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
    transition: ActionTransition = field(default_factory=ActionTransition)

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
        self.transition = ActionTransition()
        self._text_map = text_map
        self._status_registry = status_registry
        self._skill_registry = skill_registry

    # ── 便捷记录方法 (主代码通过 _settle(ctx, record_type, **kwargs) 调用) ──

    def begin_action(self, request: ActionRequest) -> None:
        self.transition = ActionTransition(request=request)

    def capture_before_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.transition.capture_before(snapshot)

    def capture_after_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.transition.capture_after(snapshot)

    def record_state_change(self, change: StateChange) -> None:
        self.transition.append_change(change)

    def record_rng_event(self, event: RNGEvent) -> None:
        self.transition.append_rng_event(event)

    def record_process_event(self, event: ProcessEvent) -> None:
        self.transition.append_process_event(event)

    def _action_source(self, *, source_id: str = "", owner_id: str = "") -> SourceRef:
        request = self.transition.request
        return SourceRef.action(
            actor_id=owner_id or request.actor_id,
            action_id=source_id or request.action_id,
            origin_path=request.source.origin_path,
        )

    def _record_change(
        self,
        change_type: str,
        *,
        scope: str,
        subject_id: str = "",
        field_path: str = "",
        old_value: Any = None,
        new_value: Any = None,
        delta: Any = None,
        source: SourceRef | None = None,
        reason: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.transition.append_change(
            StateChange(
                change_type=change_type,
                scope=scope,
                subject_id=str(subject_id or ""),
                field_path=str(field_path or ""),
                old_value=old_value,
                new_value=new_value,
                delta=delta,
                source=source or self._action_source(),
                reason=str(reason or ""),
                payload=dict(payload or {}),
            )
        )

    def record_target(self, target_ids: list[str], method: str = "explicit") -> None:
        request = self.transition.request
        decision_trace = []
        if self.transition.target_resolution is not None:
            decision_trace = deepcopy(self.transition.target_resolution.decision_trace)
        self.target_record = TargetRecord(
            action_id=request.action_id, actor_id=request.actor_id,
            target_ids=list(target_ids), target_selection_reason=method,
        )
        self.transition.target_resolution = TargetResolution(
            actor_id=request.actor_id,
            action_id=request.action_id,
            requested_target_ids=list(request.target_ids or []),
            resolved_target_ids=list(target_ids or []),
            method=str(method or ""),
            reason=str(method or ""),
            source=request.source,
            decision_trace=decision_trace,
        )

    def record_target_decision(self, decision: dict[str, Any]) -> None:
        request = self.transition.request
        if self.transition.target_resolution is None:
            self.transition.target_resolution = TargetResolution(
                actor_id=request.actor_id,
                action_id=request.action_id,
                requested_target_ids=list(request.target_ids or []),
                source=request.source,
            )
        self.transition.target_resolution.decision_trace.append(deepcopy(decision))

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
        rec = DamageRecord(**mapped)
        self.damage_records.append(rec)
        self._record_change(
            "damage",
            scope="unit",
            subject_id=rec.target_id,
            field_path="unit.hp_or_shield",
            delta=-rec.damage_applied,
            source=self._action_source(source_id=rec.source_action_id, owner_id=rec.actor_id),
            reason=rec.damage_type,
            payload=asdict(rec),
        )

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
        rec = SPRecord(**mapped)
        self.sp_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "resource",
                scope="global",
                subject_id="team",
                field_path="global.skill_points",
                old_value=rec.old_sp,
                new_value=rec.new_sp,
                delta=rec.delta,
                reason=rec.reason,
                payload=asdict(rec),
            )

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
        rec = EnergyRecord(**mapped)
        self.energy_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "resource",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.energy",
                old_value=rec.old_energy,
                new_value=rec.new_energy,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id, owner_id=rec.unit_id),
                reason=rec.source_type or rec.label,
                payload=asdict(rec),
            )

    def record_shield(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_shield"] = float(v)
            elif k == "new_value":
                mapped["new_shield"] = float(v)
            elif k in ShieldRecord.__dataclass_fields__:
                mapped[k] = v
        rec = ShieldRecord(**mapped)
        self.shield_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "resource",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.shield",
                old_value=rec.old_shield,
                new_value=rec.new_shield,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=asdict(rec),
            )

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
        rec = HPRecord(**mapped)
        self.hp_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "resource",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.hp",
                old_value=rec.old_hp,
                new_value=rec.new_hp,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=asdict(rec),
            )

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
        if kwargs.get("record_state_change", True):
            self._record_change(
                "status",
                scope="unit",
                subject_id=rec.unit_id,
                field_path=f"unit.statuses.{rec.status_id}",
                old_value=rec.old_stacks,
                new_value=rec.new_stacks,
                delta=rec.new_stacks - rec.old_stacks,
                source=SourceRef.status(owner_id=rec.source_id or rec.unit_id, status_id=rec.status_id),
                reason=rec.change_type or rec.reason,
                payload=asdict(rec),
            )

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
        rec = AVRecord(**mapped)
        self.av_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "av",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.remaining_av",
                old_value=rec.old_remaining_av,
                new_value=rec.new_remaining_av,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=asdict(rec),
            )

    def record_turn(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "event":
                mapped["event_type"] = str(v)
            elif k in TurnRecord.__dataclass_fields__:
                mapped[k] = v
        rec = TurnRecord(**mapped)
        self.turn_records.append(rec)
        self._record_change(
            "turn",
            scope="unit",
            subject_id=rec.unit_id,
            field_path="unit.turn",
            source=self._action_source(source_id=rec.action_id, owner_id=rec.unit_id),
            reason=rec.event_type,
            payload=asdict(rec),
        )

    def record_mechanic(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k in MechanicRecord.__dataclass_fields__:
                mapped[k] = v
            elif k == "detail":
                mapped["description"] = str(v)
            elif k == "data":
                mapped["data"] = dict(v) if isinstance(v, dict) else {}
        rec = MechanicRecord(**mapped)
        self.mechanic_records.append(rec)
        self._record_change(
            "mechanic",
            scope="unit" if rec.unit_id else "battle",
            subject_id=rec.unit_id,
            field_path="mechanic",
            reason=rec.event_type,
            payload=asdict(rec),
        )

    def record_break(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "break_effect":
                mapped["break_effect_mult"] = float(v)
            elif k == "aftermath_status":
                mapped["aftermath_status_id"] = str(v)
            elif k in BreakRecord.__dataclass_fields__:
                mapped[k] = v
        rec = BreakRecord(**mapped)
        self.break_records.append(rec)
        self._record_change(
            "break",
            scope="unit",
            subject_id=rec.target_id,
            field_path="unit.toughness.break",
            delta=-rec.damage_applied,
            source=self._action_source(owner_id=rec.actor_id),
            reason="weakness_break",
            payload=asdict(rec),
        )

    def record_toughness(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_toughness"] = float(v)
            elif k == "new_value":
                mapped["new_toughness"] = float(v)
            elif k in ToughnessRecord.__dataclass_fields__:
                mapped[k] = v
        rec = ToughnessRecord(**mapped)
        self.toughness_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "toughness",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.toughness",
                old_value=rec.old_toughness,
                new_value=rec.new_toughness,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=asdict(rec),
            )

    def record_dot(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "break_effect":
                mapped["break_effect_mult"] = float(v)
            elif k == "source_status":
                mapped["source_status_id"] = str(v)
            elif k in DotRecord.__dataclass_fields__:
                mapped[k] = v
        rec = DotRecord(**mapped)
        self.dot_records.append(rec)
        self._record_change(
            "dot",
            scope="unit",
            subject_id=rec.unit_id,
            field_path="unit.hp_or_shield",
            delta=-rec.damage_applied,
            source=SourceRef.status(owner_id=rec.unit_id, status_id=rec.source_status_id),
            reason=rec.kind,
            payload=asdict(rec),
        )

    def record_super_break(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "break_effect":
                mapped["break_effect_mult"] = float(v)
            elif k == "super_break_bonus_mult":
                mapped["super_break_bonus"] = float(v)
            elif k in SuperBreakRecord.__dataclass_fields__:
                mapped[k] = v
        rec = SuperBreakRecord(**mapped)
        self.super_break_records.append(rec)
        self._record_change(
            "super_break",
            scope="unit",
            subject_id=rec.target_id,
            field_path="unit.hp_or_shield",
            delta=-rec.damage_applied,
            source=self._action_source(owner_id=rec.actor_id),
            reason="super_break",
            payload=asdict(rec),
        )

    # ── 序列化 ──

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 兼容字典，供 run_route 写入 trace_entry。"""
        transition = self.transition.to_dict()
        transition["replay_validation"] = validate_transition_replay(transition)
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
            "transition": transition,
        }
