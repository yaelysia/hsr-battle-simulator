from __future__ import annotations

from typing import Any, Optional

from ._adapter import SimulatorRuntimeAdapter


class QueueRuntime(SimulatorRuntimeAdapter):
    """Migrated drain_queues runtime from BattleSimulator."""

    def drain_queues(self, default_events: Optional[dict[str, Any]] = None) -> None:
        default_events = default_events or {}
        guard = 0
        while self.state.ultimate_queue or self.state.immediate_queue or self.state.interrupt_queue:
            guard += 1
            if guard > 100:
                raise SimulatorError("Queue drain guard exceeded; possible infinite trigger loop")
            if self.state.ultimate_queue:
                qname = "ultimate_queue"
                item = deepcopy(self.state.ultimate_queue[0])
            elif self.state.immediate_queue:
                qname = "immediate_queue"
                item = deepcopy(self.state.immediate_queue[0])
            else:
                qname = "interrupt_queue"
                item = deepcopy(self.state.interrupt_queue[0])
            self.state.log_event("queue", f"Resolve queued action from {qname}: {item['actor']}.{item.get('action')}")
            if item.get("carry_across_wave") is False and item.get("queued_wave_index") != self.state.wave_index:
                settlement = self.begin_queued_action_settlement(item, qname, guard, [], target_source="none")
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:skip_wave",
                    ctx={"_settlement": settlement},
                    payload={"guard": guard, "item": deepcopy(item), "current_wave_index": self.state.wave_index},
                )
                self.state.log_event(
                    "queue_skip",
                    f"Skip queued action {item['actor']}.{item['action']}: cannot carry across wave",
                    {"item": item, "current_wave_index": self.state.wave_index},
                )
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason="cannot_carry_across_wave")
                continue
            if not item.get("action"):
                key = f"pending_extra_turn:{item['actor']}:{item.get('extra_turn_type', 'extra_turn')}"
                grant_item = {**item, "action": "extra_turn_grant"}
                settlement = self.begin_queued_action_settlement(grant_item, qname, guard, [], target_source="none")
                settlement_ctx = {"_settlement": settlement}
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:extra_turn_grant",
                    ctx=settlement_ctx,
                    payload={"guard": guard, "item": deepcopy(item)},
                )
                self.commit_global_flag(
                    key,
                    coerce_float(self.state.global_flags.get(key, 0)) + 1,
                    reason="queue:extra_turn_grant",
                    ctx=settlement_ctx,
                    payload={"item": deepcopy(item)},
                )
                self.state.log_event("extra_turn_grant", f"Queued extra turn grant available for {item['actor']}", {"item": item, "flag": key})
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(grant_item, qname, guard, settlement)
                continue
            if item["actor"] not in self.state.units or (not self.state.unit(item["actor"]).alive):
                settlement = self.begin_queued_action_settlement(item, qname, guard, [], target_source="none")
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:skip_dead_actor",
                    ctx={"_settlement": settlement},
                    payload={"guard": guard, "item": deepcopy(item)},
                )
                self.state.log_event(
                    "queue_skip",
                    f"Skip queued action {item['actor']}.{item['action']}: queued actor is dead or missing",
                    {"item": item},
                )
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason="queued_actor_dead_or_missing")
                continue
            action = self.get_action_def(item["actor"], item["action"])
            actor_for_queue = self.state.unit(item["actor"])
            interrupt_reason = self.queued_enemy_chain_interrupt_reason(actor_for_queue, item, action)
            if interrupt_reason:
                settlement = self.begin_queued_action_settlement(item, qname, guard, [], target_source="none")
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:skip_enemy_chain_interrupt",
                    ctx={"_settlement": settlement},
                    payload={"guard": guard, "item": deepcopy(item), "interrupt_reason": interrupt_reason},
                )
                self.state.log_event(
                    "queue_skip",
                    f"Skip queued enemy chain action {item['actor']}.{item['action']}: interrupted by {interrupt_reason}",
                    {"item": item, "reason": interrupt_reason, "actor_statuses": [st.id for st in actor_for_queue.statuses], "is_broken": actor_for_queue.is_broken},
                )
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason=f"enemy_chain_interrupted:{interrupt_reason}")
                continue
            targets = self.normalize_targets(item.get("targets"))
            resolved_from_deferred_policy = targets is None
            settlement: Optional[SettlementCollector] = None
            if targets is None:
                action["target_policy"] = item.get("defer_target_policy", action.get("target_policy", "manual"))
                settlement = self.begin_queued_action_settlement(item, qname, guard, [], target_source="deferred_policy")
                selector_context = {
                    "target_id": item.get("context_target_id"),
                    "queued": True,
                    "turn_kind": item.get("turn_kind"),
                    "_settlement": settlement,
                }
                targets = self.select_targets(action, selector_context)
                settlement.record_target(targets or [], method="deferred_policy")
            if resolved_from_deferred_policy and not targets:
                # Support/utility queued actions may intentionally have no explicit
                # target.  Only skip empty-target queued actions when their action
                # actually contains offensive damage that needs a live target.
                if not self.queued_action_has_valid_damage_target(action, []):
                    if settlement is None:
                        settlement = self.begin_queued_action_settlement(item, qname, guard, [], target_source="deferred_policy")
                    self.commit_queue_popleft(
                        qname,
                        reason="queue:popleft:skip_no_deferred_targets",
                        ctx={"_settlement": settlement},
                        payload={"guard": guard, "item": deepcopy(item)},
                    )
                    self.state.log_event(
                        "queue_skip",
                        f"Skip queued action {item['actor']}.{item['action']}: deferred target policy found no valid targets",
                        {"item": item},
                    )
                    settlement.capture_after_snapshot(self.full_scene_snapshot())
                    self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason="deferred_target_policy_no_valid_targets")
                    continue
            if not self.queued_action_has_valid_damage_target(action, targets or []):
                if settlement is None:
                    settlement = self.begin_queued_action_settlement(item, qname, guard, targets or [], target_source="deferred_policy" if resolved_from_deferred_policy else "queued_item")
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:skip_no_live_damage_targets",
                    ctx={"_settlement": settlement},
                    payload={"guard": guard, "item": deepcopy(item), "targets": targets},
                )
                self.state.log_event(
                    "queue_skip",
                    f"Skip queued action {item['actor']}.{item['action']}: no live damage targets remain",
                    {"item": item, "targets": targets},
                )
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason="no_live_damage_targets")
                continue
            events = {**default_events, **item.get("events", {})}
            target_source = "deferred_policy" if resolved_from_deferred_policy else "queued_item"
            if settlement is None:
                settlement = self.begin_queued_action_settlement(item, qname, guard, targets or [], target_source=target_source)
            q_context = {"queued": True, "turn_kind": item.get("turn_kind"), "_settlement": settlement}
            self.commit_queue_popleft(
                qname,
                reason="queue:popleft:resolve_action",
                ctx=q_context,
                payload={"guard": guard, "item": deepcopy(item), "targets": targets or []},
            )
            if self.queued_action_is_enemy_chain(item, action):
                q_context["enemy_action_chain"] = True
                q_context["chain_id"] = item.get("chain_id") or item.get("enemy_chain_id") or action.get("chain_id") or action.get("enemy_chain_id")
                q_context["chain_record_skill_use"] = item.get("record_skill_use", item.get("chain_record_skill_use", action.get("chain_record_skill_use", True)))
                q_context["chain_advances_enemy_sequence"] = item.get("advance_ai_sequence", item.get("chain_advances_enemy_sequence", action.get("chain_advances_enemy_sequence", False)))
            if item.get("extra_turn_type") is not None:
                q_context["extra_turn_type"] = item.get("extra_turn_type")
            self.resolve_action(action, targets or [], events, context=q_context)
            settlement.capture_after_snapshot(self.full_scene_snapshot())
            self.record_queued_action_transition(item, qname, guard, settlement)
