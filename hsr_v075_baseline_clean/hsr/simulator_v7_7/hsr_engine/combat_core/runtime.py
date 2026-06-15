from __future__ import annotations

from typing import Any, Optional

from ._adapter import SimulatorRuntimeAdapter


from .actions import ActionRuntime
from .effects import EffectRuntime
from .queues import QueueRuntime

class CombatRuntime(SimulatorRuntimeAdapter):
    """Top-level combat runtime facade used by BattleSimulator wrappers."""

    def __init__(self, simulator: Any) -> None:
        super().__init__(simulator)
        self.actions = ActionRuntime(simulator)
        self.effects = EffectRuntime(simulator)
        self.queues = QueueRuntime(simulator)

    def resolve_action(self, action: dict[str, Any], targets: list[str], events: dict[str, Any], context: Optional[dict[str, Any]] = None) -> None:
        return self.actions.resolve_action(action, targets, events, context=context)

    def apply_effect(self, eff: dict[str, Any], ctx: dict[str, Any]) -> None:
        return self.effects.apply_effect(eff, ctx)

    def drain_queues(self, default_events: Optional[dict[str, Any]] = None) -> None:
        return self.queues.drain_queues(default_events=default_events)

    def resolve_route_step(self, step: dict[str, Any]) -> None:
        # Drain queued actions before route step unless explicitly suppressed.
        if coerce_bool(step.get("auto_resolve_queues_before", True), default=True):
            self.drain_queues(default_events=step.get("events", {}))

        if step.get("type") == "advance_to_next_regular":
            collector = self.begin_route_control_settlement(step)
            actor_id = self.advance_to_next_regular_actor(ctx={"_settlement": collector})
            collector.transition.request.metadata["next_actor_id"] = actor_id
            # Enter and end an empty regular turn only if explicitly requested.
            if coerce_bool(step.get("resolve_empty_turn", False), default=False):
                actor = self.state.unit(actor_id)
                turn_ctx = {"_settlement": collector}
                self.begin_turn(actor, "regular", None, context=turn_ctx)
                self.end_turn(actor, "regular", None, context=turn_ctx)
            collector.capture_after_snapshot(self.full_scene_snapshot())
            return

        if step.get("type") in ("apply_effects", "battle_start_effects", "setup_effects"):
            settlement = self.begin_route_control_settlement(step)
            ctx = {
                "events": step.get("events", {}),
                "context": {"route_step": step},
                "phase_locked_targets": set(),
                "_settlement": settlement,
            }
            self.state.log_event("route_effects", f"Apply route effects: {step.get('type')}")
            for eff in step.get("effects", []) or []:
                self.apply_effect(eff, ctx)
            settlement.capture_after_snapshot(self.full_scene_snapshot())
            return

        actor_id = step["actor"]
        action_id = step["action"]
        mode = step.get("timing", "manual")
        turn_kind = step.get("turn_kind")
        action = self.get_action_def(actor_id, action_id)
        step_context = {"route_step": step, "turn_kind": turn_kind}
        if step.get("extra_turn_type") is not None:
            step_context["extra_turn_type"] = step.get("extra_turn_type")
        # Phase 2: 为每一步创建结算收集器（可选注册表自动补中文名）
        settlement = SettlementCollector(
            text_map=self._text_map,
            status_registry=self._status_registry,
            skill_registry=self._skill_registry,
        )
        action_request = ActionRequest.from_route_step(step, [])
        action_request.timing = mode
        settlement.begin_action(action_request)
        settlement.capture_before_snapshot(self.full_scene_snapshot())
        step_context["_settlement"] = settlement
        # 让 run_route 能取出结算数据
        step["_settlement"] = settlement

        targets = self.normalize_targets(step["targets"]) if "targets" in step else self.select_targets(action, step_context)
        settlement.transition.request.target_ids = list(targets or [])
        settlement.record_target(targets or [], method="explicit" if "targets" in step else "auto")

        if mode == "regular_turn":
            self.advance_until_regular_actor(actor_id, ctx=step_context)
            turn_kind = turn_kind or "regular"
        elif mode == "next_regular_turn":
            next_actor = self.advance_to_next_regular_actor(ctx=step_context)
            if next_actor != actor_id:
                raise SimulatorError(f"Expected {actor_id}, got next regular actor {next_actor}")
            turn_kind = turn_kind or "regular"
        elif mode in ("extra_turn", "ultimate"):
            turn_kind = turn_kind or mode
        elif mode in ("interrupt", "manual", "immediate"):
            # Manual/interrupt actions do not tick regular-turn durations unless caller sets turn_kind.
            pass
        else:
            raise SimulatorError(f"Unknown timing mode: {mode}")
        step_context["turn_kind"] = turn_kind
        settlement.transition.request.turn_kind = turn_kind
        self.resolve_action(action, targets or [], step.get("events", {}), context=step_context)
        settlement.capture_after_snapshot(self.full_scene_snapshot())

        if coerce_bool(step.get("auto_resolve_queues_after", True), default=True):
            self.drain_queues(default_events=step.get("events", {}))
