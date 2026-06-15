from __future__ import annotations

from typing import Any, Optional

from ._adapter import SimulatorRuntimeAdapter
from .contracts import ActionTransaction


class ActionRuntime(SimulatorRuntimeAdapter):
    """Migrated resolve_action runtime from BattleSimulator."""

    def resolve_action(self, action: dict[str, Any], targets: list[str], events: dict[str, Any], context: Optional[dict[str, Any]] = None) -> None:
        context = context or {}
        if not context.get("action_resolution_id"):
            self._action_resolution_counter += 1
            context["action_resolution_id"] = f"action_{self._action_resolution_counter}"
        targets = self.normalize_targets(targets) or []
        actor = self.state.unit(action["actor_id"])
        transaction = context.get("_transaction")
        if not isinstance(transaction, ActionTransaction):
            transaction = ActionTransaction.from_legacy_action(
                action=action,
                targets=targets,
                events=events,
                legacy_context=context,
                actor=actor,
            )
            context["_transaction"] = transaction
        transaction.bind_targets(targets)
        if "owner_id" not in context and actor.flags.get("owner_id"):
            context["owner_id"] = actor.flags.get("owner_id")
        if not actor.alive and not coerce_bool(action.get("allow_dead_actor", False), default=False):
            raise SimulatorError(f"Actor {actor.id} is dead")
        action_tags = set(normalize_str_list(action.get("tags", [])))
        turn_kind = context.get("turn_kind")
        if turn_kind:
            self.begin_turn(actor, turn_kind, action, context=context)
            blockers = self.action_block_statuses(actor) if turn_kind == "regular" else []
            if blockers:
                self.state.log_event("action_block", f"{actor.id} action blocked by {blockers[0].id}", {"actor": actor.id, "statuses": [st.id for st in blockers], "turn_kind": turn_kind})
                self.finish_regular_action(actor, action, ctx=context)
                if any(st.modifiers.get("frozen") for st in blockers if isinstance(st.modifiers, dict)):
                    self.apply_action_advance(actor, 0.50, ctx=context, reason="control:frozen_auto_advance")
                self.end_turn(actor, turn_kind, action, context=context)
                transaction.sync_from_transition()
                return
        action_ctx = {
            "action": action,
            "actor_id": actor.id,
            "actor": actor,
            "targets": targets,
            "events": events,
            "context": context,
            "turn_kind": turn_kind,
            "action_resolution_id": context.get("action_resolution_id"),
            "owner_id": context.get("owner_id"),
            "_transaction": transaction,
            # Phase 2: 结算收集器通过 action_ctx 传给所有下游函数
            "_settlement": context.get("_settlement"),
            # Shared within a single action. Non-carry phase_hp boundaries
            # reached by packets or action-owned effect damage lock that target
            # against later damage sources in the same action.
            "phase_locked_targets": transaction.phase_locked_targets,
        }
        if len(targets) == 1:
            action_ctx["target_id"] = targets[0]
            if targets[0] in self.state.units:
                action_ctx["target"] = self.state.unit(targets[0])
        self.state.log_event("action_start", f"{actor.id} uses {action['id']} on {targets}", {"tags": sorted(action_tags), "turn_kind": turn_kind})
        self.run_triggers("before_action_check", action_ctx)
        self.validate_and_pay_cost(actor, action, action_ctx=action_ctx)
        self.run_triggers("action_start", action_ctx)

        if actor.side == "ally" and ({"skill_use", "ultimate_use"} & action_tags):
            for st in actor.statuses:
                if st.id == "savage_god_glory" or "glory" in {str(t).lower() for t in st.tags}:
                    old = st.stacks
                    self.commit_status_stacks(
                        actor,
                        st,
                        min(st.max_stacks, st.stacks + 1),
                        reason="savage_glory:ally_action_stack",
                        ctx=action_ctx,
                        payload={"action": action.get("id"), "action_tags": sorted(action_tags)},
                    )
                    if st.stacks != old:
                        self.state.log_event("enemy_mechanic", f"{actor.id} Glory stacks {old}->{st.stacks}", {"unit": actor.id, "status": st.id})

        # Some character actions have a dedicated post-start/pre-damage window
        # (for example self-buffs applied by a skill before its own damage).
        for eff in action.get("effects_after_action_start", []) or []:
            self.apply_effect(eff, action_ctx)

        # Direct action effects before damage.
        for eff in action.get("effects_before_damage", []):
            self.apply_effect(eff, action_ctx)

        attack_targets_hit: set[str] = set()
        any_packet_hit = False
        total_attack_damage = 0.0
        # Phase HP bars are semantic phase boundaries, not merely visual HP
        # segments. When a non-carry phase boundary is reached, later packets in
        # the same action must not immediately damage the newly entered phase.
        # Otherwise a multi-hit attack can leak damage across a phase boundary
        # even though carry_over_damage=false.
        phase_locked_targets: set[str] = action_ctx.setdefault("phase_locked_targets", set())
        damage_packets = self.expand_damage_packets(action.get("damage_packets", []) or [])
        packet_count_for_energy = max(1, len(damage_packets))
        for packet_idx, packet in enumerate(damage_packets):
            packet_actor_energy_applied = False
            # If packet defines target/targets/target_policy it may override route targets.
            packet_targets = self.resolve_packet_targets(packet, action, action_ctx, targets)
            packet_for_targets = packet
            if coerce_bool(packet.get("split_damage_across_targets", False), default=False) and packet_targets:
                packet_for_targets = deepcopy(packet)
                divisor = max(1, len(packet_targets))
                if "multiplier" in packet_for_targets:
                    packet_for_targets["multiplier"] = coerce_float(packet_for_targets.get("multiplier", 0.0)) / divisor
                if "flat_damage" in packet_for_targets:
                    packet_for_targets["flat_damage"] = coerce_float(packet_for_targets.get("flat_damage", 0.0)) / divisor
                packet_for_targets["split_damage_divisor"] = divisor
            for target_id in packet_targets:
                if target_id in phase_locked_targets:
                    self.record_process_event(
                        action_ctx,
                        event_type="damage_target_skip",
                        subject_id=str(target_id),
                        reason="damage:phase_boundary_locked",
                        payload={
                            "target_id": str(target_id),
                            "packet_id": packet.get("id"),
                            "phase_locked_targets": sorted(str(x) for x in phase_locked_targets),
                        },
                    )
                    self.state.log_event(
                        "damage_skip",
                        f"Skip {target_id}: phase HP boundary locked further damage from {actor.id}.{action['id']}",
                        {"actor": actor.id, "action": action["id"], "target": target_id, "packet": packet.get("id")},
                    )
                    continue
                if target_id not in self.state.units:
                    continue
                target_unit_for_packet = self.state.unit(target_id)
                defeated_this_action = action_ctx.get("defeated_targets_this_action")
                already_defeated_by_primary = isinstance(defeated_this_action, set) and str(target_id) in defeated_this_action
                if not target_unit_for_packet.alive and not already_defeated_by_primary:
                    continue
                if already_defeated_by_primary:
                    self.record_process_event(
                        action_ctx,
                        event_type="primary_damage_continue_defeated_target",
                        subject_id=str(target_id),
                        reason="damage:primary_action_full_resolution",
                        payload={
                            "target_id": str(target_id),
                            "packet_id": packet.get("id"),
                            "defeated_targets_this_action": sorted(str(x) for x in defeated_this_action) if isinstance(defeated_this_action, set) else [],
                        },
                    )
                    self.state.log_event(
                        "primary_damage_overkill",
                        f"{actor.id}.{action['id']} continues primary damage packet {packet.get('id')} on already defeated {target_id}",
                        {"actor": actor.id, "action": action["id"], "target": target_id, "packet": packet.get("id"), "reason": "primary_action_full_resolution"},
                    )
                packet_ctx = {**action_ctx, "packet": packet_for_targets, "target_id": target_id, "target": target_unit_for_packet}
                self.run_triggers("before_damage", packet_ctx)
                result = self.resolve_damage_packet(packet_for_targets, actor, self.state.unit(target_id), action, events, packet_ctx)
                self.apply_damage_result(result, packet_ctx)
                # Phase 2: 伤害记录
                self._settle(action_ctx, "damage",
                    packet_index=packet_idx,
                    packet_id=str(packet.get("id", "")),
                    source_action_id=action.get("id", ""),
                    actor_id=actor.id,
                    target_id=target_id,
                    element=str(result.get("element", "")),
                    damage_type=str(packet.get("damage_type", "direct_damage")),
                    base_damage=float(result.get("base_damage", 0.0)),
                    crit=bool(result.get("crit", {}).get("is_critical", False)),
                    crit_multiplier=float(result.get("crit", {}).get("multiplier", 1.0)),
                    dmg_bonus_multiplier=float(result.get("multipliers", {}).get("dmg_bonus", 1.0)),
                    def_multiplier=float(result.get("multipliers", {}).get("defense", 1.0)),
                    res_multiplier=float(result.get("multipliers", {}).get("res", 1.0)),
                    damage_taken_multiplier=float(result.get("multipliers", {}).get("damage_taken", 1.0)),
                    universal_reduction_multiplier=float(result.get("multipliers", {}).get("universal_reduction", 1.0)),
                    toughness_state_multiplier=float(result.get("multipliers", {}).get("toughness_state", 1.0)),
                    final_damage=float(result.get("damage", 0.0)),
                    applied_damage=float(result.get("damage_applied", result.get("damage", 0.0))),
                    shield_absorbed=float(result.get("shield_absorbed", 0.0)),
                    hp_loss=float(result.get("hp_loss", 0.0)),
                    overkill=float(result.get("overkill", 0.0)),
                    is_overkill=bool(result.get("is_overkill", False)),
                    formula_ledger=result.get("formula_ledger", {}),
                    modifier_ledger=result.get("modifier_ledger", {}),
                    skip_reason="",
                )
                total_attack_damage += coerce_float(result.get("final_damage", result.get("damage", 0.0)))
                if target_id in self.state.units:
                    self.apply_entanglement_hit_stack(self.state.unit(target_id), result, ctx=packet_ctx)
                packet_ctx["damage_result"] = result
                if result.get("hp_bar_depleted"):
                    self.apply_hp_bar_depleted_effects(result, packet_ctx)
                self.apply_hit_taken_energy(self.state.unit(target_id), packet_for_targets, action, result, ctx=action_ctx)
                if not packet_actor_energy_applied:
                    self.apply_packet_actor_energy_gain(actor, action, packet, packet_count_for_energy, ctx=action_ctx)
                    packet_actor_energy_applied = True
                self.run_triggers("after_damage", packet_ctx)
                self.run_triggers("after_hp_change", packet_ctx)
                if result.get("hp_bar_depleted"):
                    self.run_triggers("after_hp_bar_depleted", packet_ctx)
                if result["target_defeated"]:
                    # Defeat energy is part of resolving the killing hit.
                    # Apply it before after_defeat_enemy triggers so trigger
                    # conditions and queued follow-up actions observe the
                    # post-kill energy state.
                    self.note_action_defeat(target_id, actor.id, "primary_action_damage", action_ctx)
                    self.apply_kill_energy(actor, self.state.unit(target_id), action, ctx=action_ctx)
                    packet_ctx["actor"] = actor
                    packet_ctx["target"] = self.state.unit(target_id)
                    self.run_triggers("after_defeat_enemy", packet_ctx)
                if result.get("phase_damage_locked_until_action_end"):
                    phase_locked_targets.add(target_id)
                    self.record_process_event(
                        action_ctx,
                        event_type="phase_damage_lock",
                        subject_id=str(target_id),
                        reason="damage:phase_boundary_lock",
                        payload={
                            "target_id": str(target_id),
                            "packet_id": packet.get("id"),
                            "damage_type": packet.get("damage_type", "direct_damage"),
                            "hp_bars_remaining": result.get("hp_bars_remaining"),
                            "bars_depleted": result.get("bars_depleted"),
                            "phase_locked_targets": sorted(str(x) for x in phase_locked_targets),
                        },
                    )
                self.tick_hit_durations(actor, self.state.unit(target_id), action, ctx=action_ctx)
                if "attack" in action_tags:
                    any_packet_hit = True
                    attack_targets_hit.add(target_id)

        if any_packet_hit:
            self.tick_attack_durations(actor, sorted(attack_targets_hit), action, ctx=action_ctx)
        action_ctx["attacked_targets"] = sorted(attack_targets_hit)
        action_ctx["hit_target_count"] = len(attack_targets_hit)
        action_ctx["total_attack_damage"] = total_attack_damage

        # Action-level after-damage effects resolve once after all packets, not
        # after each hit. Per-packet reactions should use triggers at timing
        # after_damage instead.
        for eff in action.get("effects_after_damage", []) or []:
            self.apply_effect(eff, action_ctx)

        for eff in action.get("effects", []):
            self.apply_effect(eff, action_ctx)

        self.apply_action_energy_gain(actor, action, ctx=action_ctx)
        # For a regular action, the next action value is established before
        # action_end triggers.  Otherwise action-end action-advance effects on the
        # actor are applied to the just-spent 0 AV and then lost when the regular
        # action refreshes the timeline.  Speed/status changes still recalculate
        # the refreshed AV through their normal helpers.
        self.finish_regular_action(actor, action, ctx=action_ctx)

        # Model-pack semantic timings that depend on the fully resolved action,
        # not merely the raw action_start/action_end lifecycle.  These are needed
        # for stateful video replay: Dance! Dance! Dance! after the wearer's
        # Ultimate, Seele's basic-attack advance, and Dan Heng's Souldragon
        # advance after the bondmate attacks.
        if "ultimate_use" in action_tags:
            self.run_triggers("after_wearer_uses_ultimate", action_ctx)
            self.run_triggers("after_ally_uses_ultimate", action_ctx)
            if actor.side == "ally":
                self.run_triggers("after_other_ally_uses_ultimate", action_ctx)
        if "attack" in action_tags and any_packet_hit:
            self.run_triggers("after_ally_attacks" if actor.side == "ally" else "after_enemy_attacks", action_ctx)
            bondmate = self.state.global_flags.get("bondmate") or self.state.global_flags.get("bondmate_target")
            if bondmate and str(bondmate) == actor.id:
                _bondmate_trigger_log_start = len(self.state.log)
                self.run_triggers("after_bondmate_uses_attack", action_ctx)
                self.apply_souldragon_bondmate_attack_semantics(action_ctx, _bondmate_trigger_log_start)
        if actor.id == "souldragon" or "souldragon" in {str(t).lower() for t in actor.tags}:
            self.run_triggers("after_souldragon_action", action_ctx)

        if actor.side == "enemy":
            enemy_chain_context = coerce_bool(context.get("enemy_action_chain", False), default=False)
            record_chain_use = coerce_bool(context.get("chain_record_skill_use", action.get("chain_record_skill_use", True)), default=True)
            if (not enemy_chain_context) or record_chain_use:
                self.record_enemy_skill_use_after_action(actor, str(action.get("id")), ctx=action_ctx)
            else:
                self.state.log_event("enemy_ai", f"{actor.id} does not record chained skill use {action.get('id')}", {"action": action.get("id"), "chain_id": context.get("chain_id")})
        if actor.side == "enemy" and isinstance(actor.flags.get("enemy_ai_sequence"), list):
            enemy_chain_context = coerce_bool(context.get("enemy_action_chain", False), default=False)
            advance_chain = coerce_bool(context.get("chain_advances_enemy_sequence", action.get("chain_advances_enemy_sequence", False)), default=False)
            if (not enemy_chain_context) or advance_chain:
                self.advance_enemy_ai_sequence_after_action(actor, str(action.get("id")), ctx=action_ctx)
            else:
                self.state.log_event("enemy_ai", f"{actor.id} holds AI cursor after chained continuation {action.get('id')}", {"action": action.get("id"), "sequence_index": actor.flags.get("enemy_ai_sequence_index"), "chain_id": context.get("chain_id")})
        if actor.side == "enemy" and str(actor.flags.get("clear_glory_after_next_savage_action", "")).lower() == "ready":
            self.clear_savage_god_glory_after_action(actor, action_ctx)
            self.commit_unit_flag(actor, "clear_glory_after_next_savage_action", False, reason="savage_glory:clear_flag_consumed", ctx=action_ctx, payload={"action": action.get("id")})
        elif actor.side == "enemy" and str(actor.flags.get("clear_glory_after_next_savage_action", "")).lower() == "armed":
            self.commit_unit_flag(actor, "clear_glory_after_next_savage_action", "ready", reason="savage_glory:arm_clear_after_next_action", ctx=action_ctx, payload={"action": action.get("id")})
            self.state.log_event("enemy_mechanic", f"{actor.id} arms Glory clear after next action", {"flag": "clear_glory_after_next_savage_action"})

        self.run_triggers("action_end", action_ctx)
        # Summon lifecycle ticks after semantic/action_end triggers so triggers such
        # as after_souldragon_action can still observe the just-used enhanced state.
        self.tick_summon_lifecycle(actor, action, ctx=action_ctx)
        self.tick_status_durations(event="action_end", actor=actor, turn_kind=turn_kind, action=action, ctx=action_ctx)
        if turn_kind:
            self.end_turn(actor, turn_kind, action, context=action_ctx)
        self.check_wave_transition(ctx=action_ctx)
        self.state.log_event("action_end", f"{actor.id} finished {action['id']}")
        transaction.sync_from_transition()
