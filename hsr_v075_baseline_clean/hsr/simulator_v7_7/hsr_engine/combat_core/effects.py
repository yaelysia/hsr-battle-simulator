from __future__ import annotations

from typing import Any, Optional

from ._adapter import SimulatorRuntimeAdapter


class EffectRuntime(SimulatorRuntimeAdapter):
    """Migrated apply_effect runtime from BattleSimulator."""

    def apply_effect(self, eff: dict[str, Any], ctx: dict[str, Any]) -> None:
        etype = eff.get("type")
        # Model-pack aliases: allow high-level template effects to execute in the
        # route validator without pre-translating every YAML file.
        if etype == "add_or_refresh_stack":
            status_id = eff.get("status_id") or eff.get("buff_id") or eff.get("id")
            if not status_id:
                raise SimulatorError("add_or_refresh_stack requires status_id")
            stacks = self.resolve_numeric_expr(eff.get("stacks", eff.get("amount", 1)), ctx, default=1.0)
            max_stacks = self.resolve_numeric_expr(eff.get("max_stacks", stacks), ctx, default=stacks)
            aliased = deepcopy(eff)
            aliased["type"] = "add_status"
            aliased["stacks"] = int(stacks)
            aliased["max_stacks"] = int(max_stacks)
            aliased["status"] = self.materialize_status(str(status_id), ctx, {"stacks": int(stacks), "max_stacks": int(max_stacks), "refresh_duration": True})
            return self.apply_effect(aliased, ctx)
        if etype in {"add_buff", "apply_status", "add_prebattle_status", "add_buff_on_battle_start"}:
            status = eff.get("status")
            if status is None:
                status_id = eff.get("buff_id") or eff.get("status_id") or eff.get("id")
                status = status_id if status_id else None
            if status is None:
                raise SimulatorError(f"{etype} requires status, status_id, or buff_id")
            aliased = deepcopy(eff)
            aliased["type"] = "add_status"
            aliased["status"] = self.materialize_status(status, ctx, eff)
            return self.apply_effect(aliased, ctx)
        if etype in {"remove_buff", "dispel_buff", "remove_status_effect"}:
            aliased = deepcopy(eff)
            aliased["type"] = "remove_status"
            aliased.setdefault("status_id", eff.get("buff_id") or eff.get("id"))
            return self.apply_effect(aliased, ctx)
        if etype == "follow_up_attack" and eff.get("damage_packets"):
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            # Attached units such as Souldragon may not be modeled as standalone
            # timeline units in a reduced route case. Use the current owner/actor
            # as the executor while preserving packet scaling refs like
            # dan_heng_permansor_terrae.atk.
            if actor_id not in self.state.units:
                actor_id = ctx.get("actor_id")
            synthetic = {
                "id": eff.get("id", "follow_up_attack"),
                "actor_id": actor_id,
                "tags": normalize_str_list(eff.get("tags", [])) + ["attack", "follow_up_damage", "can_trigger_kill_energy"],
                "cost": {"skill_points": 0},
                "energy_gain": eff.get("energy_gain", {"base_energy_gain": 0, "affected_by_err": False}),
                "damage_packets": eff.get("damage_packets", []),
                "target_policy": eff.get("target_policy", "all_enemies"),
            }
            targets = self.resolve_effect_targets(eff, ctx, default=synthetic.get("target_policy", "all_enemies"))
            if not targets:
                targets = self.select_targets(synthetic, ctx)
            targets = self.derived_damage_live_targets(targets, ctx, effect_name=str(eff.get("id") or "follow_up_attack"))
            if not targets:
                return None
            return self.resolve_action(synthetic, targets, ctx.get("events", {}), context={"queued": True, "turn_kind": eff.get("turn_kind")})
        if etype in {"enqueue_extra_turn", "launch_follow_up_attack"}:
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            explicit_action = eff.get("action") or eff.get("action_id") or eff.get("extra_turn_action") or eff.get("follow_up_action")
            if etype == "enqueue_extra_turn" and not explicit_action:
                queue_name = eff.get("queue", "extra_turn_queue")
                queued = {
                    "actor": actor_id,
                    "action": None,
                    "extra_turn_type": eff.get("extra_turn_type", "extra_turn"),
                    "turn_kind": eff.get("turn_kind", "extra_turn"),
                    "queued_wave_index": self.state.wave_index,
                    "carry_across_wave": self.queued_action_carry_across_wave(eff, {}, default=False),
                    "events": eff.get("events", {}),
                }
                self.commit_queue_append(
                    queue_name if queue_name in {"ultimate_queue", "immediate_queue", "interrupt_queue", "extra_turn_queue"} else "interrupt_queue",
                    queued,
                    reason="effect:enqueue_extra_turn",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff), "requested_queue": queue_name},
                )
                self.state.log_event("effect", f"Extra turn grant queued for {actor_id}", queued)
                return
            action_id = explicit_action or eff.get("extra_turn_type")
            aliased = deepcopy(eff)
            aliased["type"] = "launch_action"
            aliased["actor"] = actor_id
            aliased["action"] = action_id
            aliased.setdefault("queue", eff.get("queue", "extra_turn_queue" if etype == "enqueue_extra_turn" else "immediate_queue"))
            aliased.setdefault("turn_kind", "extra_turn" if etype == "enqueue_extra_turn" else None)
            return self.apply_effect(aliased, ctx)
        # For normal effects, `condition` is an effect-level gate. For
        # conditional_branch, the same field is the branch selector and must allow
        # effects_if_false to execute when false.
        if etype != "conditional_branch" and "condition" in eff and not self.eval_condition(eff.get("condition"), ctx):
            self.state.log_event("effect_skip", f"Effect {eff.get('type')} skipped by condition", {"effect": eff})
            return
        if etype == "add_status":
            eff = deepcopy(eff)
            eff["status"] = self.materialize_status(eff.get("status"), ctx, eff)
            # Optional effect-hit gate for debuffs / conditional status applications.
            # Do not use ``eff.get("effect_hit") or eff.get("chance")`` here:
            # an explicit false value is meaningful and must not be discarded.
            if "effect_hit" in eff:
                gate = eff.get("effect_hit")
            else:
                gate = eff.get("chance") if "chance" in eff else None
            if gate is not None and not isinstance(gate, dict) and not coerce_bool(gate, default=True):
                self.state.log_event("effect_skip", f"Status {eff['status']['id']} skipped by chance/effect_hit=false")
                return
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                allowed, hit_audit = self.effect_hit_gate_allows(gate, eff, ctx, target_id)
                if hit_audit:
                    self.state.log_event("effect_hit_check", f"Status {eff['status']['id']} effect-hit check on {target_id}", hit_audit)
                if not allowed:
                    self.state.log_event("effect_skip", f"Status {eff['status']['id']} failed effect-hit gate", hit_audit)
                    continue
                unit = self.state.unit(target_id)
                old_speed = self.effective_speed(unit)
                status = StatusEffect.from_dict(eff["status"], runtime_values_by_key=self.runtime_dynamic_values_for_context(ctx, target_id))
                if status.source_id is None:
                    status.source_id = ctx.get("actor_id")
                status = self.normalize_attack_convert_status_for_target(status, target_id, ctx)
                before = next((s for s in unit.statuses if s.id == status.id), None)
                before_stacks = before.stacks if before else 0
                after_status = self.merged_status_for_add(before, status)
                if self.state.global_flags.get("_active_turn_token") is not None:
                    after_status.modifiers.setdefault("_created_turn_token", self.state.global_flags.get("_active_turn_token"))
                    after_status.modifiers.setdefault("_created_turn_actor_id", self.state.global_flags.get("_active_turn_actor_id"))
                    after_status.modifiers.setdefault("_created_turn_kind", self.state.global_flags.get("_active_turn_kind"))
                self.commit_status_entry(
                    unit,
                    after_status,
                    reason="effect:add_status" if before is None else "effect:refresh_status",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff), "incoming_status": status.to_json()},
                    change_kind="add" if before is None else "refresh",
                )
                after = next((s for s in unit.statuses if s.id == status.id), after_status)
                if before is None:
                    self.apply_status_resource_side_effects(unit, after, ctx=ctx)
                self.recalculate_remaining_av_for_speed_change(unit, old_speed, reason="add_status", ctx=ctx)
                self.state.log_event("effect", f"Add status {status.id} to {target_id}", {"status": after.to_json(), "was_present": before is not None, "old_stacks": before_stacks, "new_stacks": after.stacks})
                # Phase 2: 状态记录
                self._settle(ctx, "status",
                    status_id=status.id, target_unit_id=target_id, source_unit_id=status.source_id or "",
                    change_type="add" if before is None else "refresh",
                    stacks_before=before_stacks, stacks_after=after.stacks,
                    max_stacks=after.max_stacks, duration_type=str(after.duration_type or ""),
                    duration_value=after.duration_value or 0,
                    modifier_keys=sorted(after.modifiers.keys()) if after.modifiers else [],
                    trigger_reason=f"effect:{ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                    record_state_change=False,
                )
                lifecycle_ctx = {**ctx, "target_id": target_id, "target": unit, "status_id": after.id, "status": after, "trigger": {"status_id": after.id}, "status_owner_id": target_id}
                self.run_triggers("status_stack" if before is not None else "status_create", lifecycle_ctx)
                watcher_depth = coerce_int(ctx.get("watcher_depth", 0), 0) + 1
                self.run_triggers("ability_property_change", {**lifecycle_ctx, "watcher_depth": watcher_depth, "context": {**lifecycle_ctx.get("context", {}), "phase": "ability_property_change", "reason": "status_added"}})
                self.run_triggers("status_dynamic_value_change", {**lifecycle_ctx, "watcher_depth": watcher_depth, "context": {**lifecycle_ctx.get("context", {}), "phase": "status_dynamic_value_change", "reason": "status_added"}})
        elif etype == "remove_status":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                old_speed = self.effective_speed(unit)
                status_id = str(eff["status_id"])
                removed = next((s for s in unit.statuses if s.id == status_id), None)
                if removed is not None:
                    self.remove_status_resource_side_effects(unit, removed, ctx=ctx)
                    self.commit_status_remove(
                        unit,
                        removed,
                        reason="effect:remove_status",
                        ctx=ctx,
                        payload={"effect": deepcopy(eff), "removed_status": removed.to_json()},
                    )
                self.recalculate_remaining_av_for_speed_change(unit, old_speed, reason="remove_status", ctx=ctx)
                self.state.log_event("effect", f"Remove status {status_id} from {target_id}")
                # Phase 2: 状态移除记录
                if removed is not None:
                    self._settle(ctx, "status",
                        status_id=status_id, target_unit_id=target_id, source_unit_id=removed.source_id or "",
                        change_type="remove", stacks_before=removed.stacks, stacks_after=0,
                        max_stacks=removed.max_stacks, duration_type=str(removed.duration_type or ""),
                        duration_value=0, modifier_keys=sorted(removed.modifiers.keys()) if removed.modifiers else [],
                        trigger_reason=f"effect_remove:{ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                        record_state_change=False,
                    )
                if removed is not None:
                    lifecycle_ctx = {**ctx, "target_id": target_id, "target": unit, "status_id": status_id, "status": removed, "removed_status": removed, "trigger": {"status_id": status_id}, "status_owner_id": target_id}
                    self.run_triggers("status_destroy", lifecycle_ctx)
                    self.run_triggers("ability_property_change", {**lifecycle_ctx, "context": {**lifecycle_ctx.get("context", {}), "phase": "ability_property_change", "reason": "status_removed"}})
                    self.run_triggers("status_dynamic_value_change", {**lifecycle_ctx, "context": {**lifecycle_ctx.get("context", {}), "phase": "status_dynamic_value_change", "reason": "status_removed"}})
        elif etype == "set_unit_resource":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                audit = {"target": target_id}
                for key in ("hp", "max_hp", "shield", "energy", "max_energy", "remaining_av", "toughness", "max_toughness"):
                    if key in eff:
                        old = getattr(unit, key)
                        val = coerce_float(eff.get(key), old)
                        if key == "hp":
                            val = max(0.0, min(val, unit.max_hp))
                            self.commit_unit_hp(unit, val, reason="effect:set_resources:hp", ctx=ctx, payload={"effect": deepcopy(eff)})
                            self.commit_unit_alive(unit, val > EPS, reason="effect:set_resources:hp_alive", ctx=ctx, payload={"hp": val})
                            audit[key] = {"old": old, "new": unit.hp}
                            audit["alive"] = unit.alive
                            continue
                        if key == "max_hp":
                            val = max(0.0, val)
                            self.commit_unit_max_hp(unit, val, reason="effect:set_resources:max_hp", ctx=ctx, payload={"effect": deepcopy(eff)})
                            audit[key] = {"old": old, "new": unit.max_hp}
                            continue
                        if key == "shield":
                            val = max(0.0, val)
                            self.commit_unit_shield(unit, val, reason="effect:set_resources:shield", ctx=ctx, payload={"effect": deepcopy(eff)})
                            audit[key] = {"old": old, "new": unit.shield}
                            continue
                        if key == "energy":
                            val = max(0.0, min(val, unit.max_energy))
                            self.commit_unit_energy(unit, val, reason="effect:set_resources:energy", ctx=ctx, payload={"effect": deepcopy(eff)})
                            audit[key] = {"old": old, "new": unit.energy}
                            continue
                        if key == "remaining_av":
                            val = max(0.0, val)
                            self.commit_unit_remaining_av(unit, val, reason="effect:set_resources:remaining_av", ctx=ctx, payload={"effect": deepcopy(eff)})
                            audit[key] = {"old": old, "new": unit.remaining_av}
                            continue
                        if key in {"shield", "remaining_av", "toughness", "max_toughness", "max_hp", "max_energy"}:
                            val = max(0.0, val)
                        setattr(unit, key, val)
                        audit[key] = {"old": old, "new": val}
                if "alive" in eff:
                    self.commit_unit_alive(unit, coerce_bool(eff.get("alive"), default=unit.alive), reason="effect:set_resources:alive", ctx=ctx, payload={"effect": deepcopy(eff)})
                    audit["alive"] = unit.alive
                self.state.log_event("effect", f"Set resources for {target_id}", audit)
        elif etype == "set_status_stacks":
            status_id = str(eff.get("status_id") or eff.get("id") or "")
            if not status_id:
                self.state.log_event("effect_skip", "set_status_stacks skipped without status_id", {"effect": eff})
            else:
                for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                    unit = self.state.unit(target_id)
                    st = next((row for row in unit.statuses if row.id == status_id), None)
                    if st is None:
                        self.state.log_event("effect_skip", f"set_status_stacks skipped missing {target_id}.{status_id}", {"effect": eff})
                        continue
                    old = st.stacks
                    old_duration = st.duration_value
                    self.commit_status_stacks(
                        unit,
                        st,
                        max(0, coerce_int(eff.get("stacks", old), old)),
                        reason="effect:set_status_stacks:stacks",
                        ctx=ctx,
                        payload={"effect": deepcopy(eff)},
                    )
                    if "max_stacks" in eff:
                        self.commit_status_field(
                            unit,
                            st,
                            "max_stacks",
                            max(st.stacks, coerce_int(eff.get("max_stacks", st.max_stacks), st.max_stacks)),
                            reason="effect:set_status_stacks:max_stacks",
                            ctx=ctx,
                            payload={"effect": deepcopy(eff)},
                        )
                    if "duration_value" in eff:
                        self.commit_status_duration_value(
                            unit,
                            st,
                            coerce_int(eff.get("duration_value"), st.duration_value or 0),
                            reason="effect:set_status_stacks:duration_value",
                            ctx=ctx,
                            payload={"effect": deepcopy(eff), "old_duration_value": old_duration},
                        )
                    self.state.log_event("effect", f"Set {target_id}.{status_id} stacks {old}->{st.stacks}", {"old": old, "new": st.stacks, "duration_value": st.duration_value})
        elif etype == "set_global_resource":
            if "skill_points" in eff:
                old = self.state.skill_points
                self.commit_skill_points(
                    coerce_float(eff.get("skill_points"), old),
                    reason="effect:set_global_resource:skill_points",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff)},
                )
                self.state.log_event("effect", "Set global skill_points", {"old": old, "new": self.state.skill_points})
            if "skill_point_cap" in eff:
                old = self.state.skill_point_cap
                self.commit_skill_point_cap(
                    coerce_float(eff.get("skill_point_cap"), old),
                    reason="effect:set_global_resource:skill_point_cap",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff)},
                )
                if self.state.skill_points > self.state.skill_point_cap:
                    self.commit_skill_points(
                        self.state.skill_point_cap,
                        reason="effect:set_global_resource:skill_points_clamp",
                        ctx=ctx,
                        payload={"old_skill_points": self.state.skill_points},
                    )
                self.state.log_event("effect", "Set global skill_point_cap", {"old": old, "new": self.state.skill_point_cap})
            if "av" in eff:
                old = self.state.av
                self.commit_global_av(
                    coerce_float(eff.get("av"), old),
                    reason="effect:set_global_resource:av",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff)},
                )
                self.state.log_event("effect", "Set global av", {"old": old, "new": self.state.av})
        elif etype == "modify_energy":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                u = self.state.unit(target_id)
                amount = coerce_float(eff.get("amount", 0.0))
                if "target_max_energy_pct" in eff:
                    amount += u.max_energy * coerce_float(eff["target_max_energy_pct"])
                if "source_max_energy_pct" in eff:
                    src_id = self.resolve_special_unit(eff.get("source", "actor"), ctx)
                    amount += self.state.unit(src_id).max_energy * coerce_float(eff["source_max_energy_pct"])
                old = u.energy
                self.commit_unit_energy(
                    u,
                    u.energy + amount,
                    reason="effect:modify_energy",
                    ctx=ctx,
                    payload={"amount": amount, "effect": deepcopy(eff)},
                )
                self.state.log_event("effect", f"{target_id} energy modified by {amount:.3f}", {"old": old, "new": u.energy})
                # Phase 2: 能量修改记录
                self._settle(ctx, "energy",
                    unit_id=target_id, delta=u.energy - old,
                    old_value=old, new_value=u.energy, max_energy=u.max_energy,
                    source_type=ENERGY_SOURCE_EFFECT,
                    source_detail=f"modify_energy: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                    record_state_change=False,
                )
        elif etype in {"gain_energy", "grant_energy"}:
            source = deepcopy(eff.get("energy_gain", eff))
            if (
                "amount" in eff
                and "base" not in source
                and "base_energy_gain" not in source
                and "fixed" not in source
                and "fixed_energy_gain_not_affected_by_err" not in source
            ):
                # Model-pack shorthand often writes `amount: 30` plus
                # `affected_by_err: true`. Preserve that semantic: an amount that
                # is explicitly ERR-affected must become base energy, not fixed
                # energy. If the flag is omitted, keep the historical fixed-energy
                # behavior for compatibility.
                affected = coerce_bool(eff.get("affected_by_err", False), default=False)
                amount_value = self.resolve_numeric_expr(eff.get("amount", 0.0), ctx, default=coerce_float(eff.get("amount", 0.0)))
                if "energy_per_hit" in eff:
                    # Generic helper for effects such as Tribbie A6:
                    # gain X energy for each target hit by the triggering attack.
                    amount_value += coerce_float(eff.get("energy_per_hit", 0.0)) * coerce_float(ctx.get("hit_target_count", 0.0))
                if affected:
                    source["base"] = amount_value
                else:
                    source["fixed"] = amount_value
                source["affected_by_err"] = affected
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                self.apply_energy_source(self.state.unit(target_id), source, f"effect:{etype}", default_affected_by_err=True, ctx=ctx)
        elif etype == "consume_energy":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                u = self.state.unit(target_id)
                amount = coerce_float(eff.get("amount", eff.get("energy", 0.0)))
                old = u.energy
                self.commit_unit_energy(
                    u,
                    u.energy - amount,
                    reason="effect:consume_energy",
                    ctx=ctx,
                    payload={"amount": amount, "effect": deepcopy(eff)},
                )
                self.state.log_event("effect", f"{target_id} consumes {amount:.3f} energy", {"old": old, "new": u.energy})
                # Phase 2: 能量消耗记录
                self._settle(ctx, "energy",
                    unit_id=target_id, delta=u.energy - old,
                    old_value=old, new_value=u.energy, max_energy=u.max_energy,
                    source_type=ENERGY_SOURCE_COST,
                    source_detail=f"consume_energy: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                    record_state_change=False,
                )
        elif etype == "modify_skill_points":
            amount = coerce_float(eff.get("amount", 0), 0.0)
            old_sp = self.state.skill_points
            self.modify_skill_points_with_overflow(amount, overflow_record=eff.get("overflow_record") if isinstance(eff.get("overflow_record"), dict) else None, reason="effect:modify_skill_points", ctx=ctx)
            # Phase 2: SP 变化记录
            self._settle(ctx, "sp",
                delta=int(amount), old_value=int(old_sp), new_value=self.state.skill_points,
                max_value=self.state.skill_point_cap,
                reason="modify_skill_points" if amount >= 0 else "consume",
                reason_detail=f"effect: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                source_unit_id=str(ctx.get("actor_id", "")),
                record_state_change=False,
            )
        elif etype == "modify_skill_points_from_flag":
            flag = eff.get("flag")
            scale = coerce_float(eff.get("scale", 1.0), 1.0)
            raw = self.state.global_flags.get(str(flag), ctx.get(str(flag), 0))
            amount = coerce_float(raw, 0.0) * scale
            old_sp2 = self.state.skill_points
            result = self.modify_skill_points_with_overflow(amount, overflow_record=eff.get("overflow_record") if isinstance(eff.get("overflow_record"), dict) else None, reason=f"effect:modify_skill_points_from_flag:{flag}", ctx=ctx)
            self.state.log_event("effect", f"Skill points modified from flag {flag} by {amount}", {"old": result["old"], "new": result["new"], "flag_value": raw})
            # Phase 2: SP 变化记录
            self._settle(ctx, "sp",
                delta=int(amount), old_value=int(old_sp2), new_value=self.state.skill_points,
                max_value=self.state.skill_point_cap, reason=f"modify_skill_points_from_flag:{flag}",
                reason_detail=f"flag {flag}={raw}", source_unit_id=str(ctx.get("actor_id", "")),
                record_state_change=False,
            )
        elif etype == "modify_skill_point_cap":
            amount = coerce_int(eff.get("amount", eff.get("delta", 0)), 0)
            old_cap = self.state.skill_point_cap
            self.commit_skill_point_cap(
                self.state.skill_point_cap + amount,
                reason="effect:modify_skill_point_cap",
                ctx=ctx,
                payload={"amount": amount, "effect": deepcopy(eff)},
            )
            if self.state.skill_points > self.state.skill_point_cap:
                self.commit_skill_points(
                    self.state.skill_point_cap,
                    reason="effect:modify_skill_point_cap:skill_points_clamp",
                    ctx=ctx,
                    payload={"old_skill_points": self.state.skill_points},
                )
            self.state.log_event("effect", f"Skill point cap modified by {amount}", {"old": old_cap, "new": self.state.skill_point_cap, "skill_points": self.state.skill_points})
        elif etype == "advance_action":
            # Accept simulator-native `percent`, model-pack `advance_percent`,
            # shorthand `amount`, and light-cone tables such as
            # `advance_percent_by_superimposition: {5: 0.24}`.  If a table is
            # provided without an explicit superimposition in the effect/context,
            # use the highest table entry; this matches reduced validation cases
            # where the equipped S value is already implied by the selected build.
            percent = eff.get("percent", eff.get("advance_percent", eff.get("amount")))
            if percent is None and isinstance(eff.get("advance_percent_by_superimposition"), dict):
                table = eff.get("advance_percent_by_superimposition") or {}
                raw_s = eff.get("superimposition", eff.get("source_superimposition", ctx.get("superimposition")))
                if raw_s is None:
                    keys = []
                    for k in table.keys():
                        try:
                            keys.append(int(k))
                        except Exception:
                            pass
                    raw_s = max(keys) if keys else None
                if raw_s is not None:
                    percent = table.get(raw_s, table.get(str(raw_s)))
            if percent is None:
                raise SimulatorError("advance_action requires percent, advance_percent, amount, or advance_percent_by_superimposition")
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                self.apply_action_advance(unit, coerce_float(percent), ctx=ctx, reason="effect:advance_action")
        elif etype == "delay_action":
            # Accept both simulator-native `percent` and model-pack aliases such
            # as `delay_percent`.
            percent = eff.get("percent", eff.get("delay_percent", eff.get("amount")))
            if percent is None:
                raise SimulatorError("delay_action requires percent or delay_percent")
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                self.apply_action_delay(unit, coerce_float(percent), ctx=ctx, reason="effect:delay_action")
        elif etype == "set_action_delay":
            # TBGD SetActionDelay uses a normalized delay ratio: 1.0 means the
            # target's remaining AV is set to one full action interval at its
            # current effective speed.  This is distinct from additive delay.
            percent = eff.get("percent", eff.get("delay_percent", eff.get("amount")))
            if percent is None:
                raise SimulatorError("set_action_delay requires percent/delay_percent/amount")
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                old = unit.remaining_av
                self.commit_unit_remaining_av(
                    unit,
                    self.action_interval(unit) * coerce_float(percent),
                    reason="effect:set_action_delay",
                    ctx=ctx,
                    payload={"percent": coerce_float(percent), "action_interval": self.action_interval(unit), "effect": deepcopy(eff)},
                    av_reason=AV_DELAY,
                    av_detail=f"set action delay {coerce_float(percent):.1%}",
                )
                self.state.log_event("av_change", f"{target_id} action delay set to {coerce_float(percent):.1%}", {"old": old, "new": unit.remaining_av})
        elif etype in {"delay_self_action", "delay_next_action"}:
            aliased = deepcopy(eff)
            aliased["type"] = "delay_action"
            aliased.setdefault("target", "actor" if etype == "delay_self_action" else eff.get("target", "target"))
            aliased.setdefault("percent", eff.get("delay_percent", eff.get("amount", 0.0)))
            return self.apply_effect(aliased, ctx)
        elif etype == "set_target":
            status_id = eff.get("status_id") or eff.get("id") or "target_mark"
            targets = self.resolve_effect_targets(eff, ctx, default="target")
            if targets:
                chosen = targets[0]
                self.commit_global_flag(str(status_id), chosen, reason="effect:set_target", ctx=ctx, payload={"effect": deepcopy(eff)})
                # Bondmate is a special character-model alias used by Dan Heng.
                if str(status_id) == "bondmate":
                    self.clear_bondmate_runtime_state(keep_target=chosen, ctx=ctx)
                    self.commit_global_flag("bondmate_target", chosen, reason="effect:set_target:bondmate_target", ctx=ctx, payload={"effect": deepcopy(eff)})
                    self.ensure_bondmate_souldragon(chosen, ctx)
                status = self.materialize_status(status_id, {**ctx, "target_id": chosen}, eff)
                self.apply_effect({"type": "add_status", "status": status, "target": chosen}, ctx)
                if str(status_id) == "bondmate":
                    self.apply_attack_convert_to_bondmate(chosen, ctx.get("actor_id") if ctx.get("actor_id") in self.state.units else None, ctx)
                self.state.log_event("effect", f"Set target mark {status_id} -> {chosen}")
        elif etype == "apply_attack_convert":
            targets = self.resolve_effect_targets(eff, ctx, default="actor")
            source_id = eff.get("source")
            if source_id in {"actor", "self"}:
                source_id = ctx.get("actor_id")
            for target_id in targets:
                self.apply_attack_convert_to_bondmate(target_id, str(source_id) if source_id else None, ctx)
        elif etype == "provide_shield":
            formula = (
                eff.get("shield_formula") or eff.get("shield_formula_at_skill_10")
                or eff.get("shield_formula_at_talent_10") or eff.get("shield_formula_at_ultimate_10")
            )
            amount = coerce_float(eff.get("amount", 0.0)) if formula is None else self.eval_formula(formula, ctx)
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                old_shield = self.state.unit(target_id).shield
                self.apply_stackable_shield(target_id, amount, eff, ctx, reason="provide_shield")
                # Phase 2: 护盾记录
                new_shield = self.state.unit(target_id).shield
                self._settle(ctx, "shield",
                    unit_id=target_id, delta=new_shield - old_shield,
                    old_value=old_shield, new_value=new_shield,
                    reason=f"provide_shield: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                )
        elif etype == "modify_stat":
            if self._is_legacy_danheng_attack_convert_effect(eff):
                aliased = {"type": "apply_attack_convert", "target": eff.get("target", "bondmate"), "source": ctx.get("actor_id"), "semantic": "legacy_modify_stat_attack_convert_redirect"}
                return self.apply_effect(aliased, ctx)
            stat = eff.get("stat")
            if not stat:
                self.state.log_event("effect_skip", "modify_stat skipped without stat", {"effect": eff})
            else:
                amount = coerce_float(eff.get("add", eff.get("amount", 0.0)))
                for key in ("delta_formula_from_bonus_ability", "formula", "add_expression", "add_by_superimposition_field"):
                    if key in eff:
                        amount += self.eval_formula(eff.get(key), ctx)
                for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                    status = {"id": f"stat_mod_{stat}_{len(self.state.unit(target_id).statuses)+1}", "modifiers": {f"{stat}_add": amount}, "source_id": ctx.get("actor_id")}
                    self.apply_effect({"type": "add_status", "status": status, "target": target_id}, ctx)
        elif etype == "add_zone":
            zone_id = eff.get("zone_id") or eff.get("id") or "zone_active"
            self.commit_global_flag(str(zone_id), True, reason="effect:add_zone", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.commit_global_flag("zone_active", True, reason="effect:add_zone:zone_active", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Zone {zone_id} active")
        elif etype in {"remove_zone", "clear_zone", "end_zone"}:
            zone_id = eff.get("zone_id") or eff.get("id")
            if zone_id:
                self.commit_global_flag(str(zone_id), False, reason="effect:remove_zone", ctx=ctx, payload={"effect": deepcopy(eff)})
            else:
                for key in list(self.state.global_flags):
                    if "zone" in str(key).lower():
                        self.commit_global_flag(key, False, reason="effect:remove_zone:clear_all", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.commit_global_flag(
                "zone_active",
                any(bool(v) for k, v in self.state.global_flags.items() if "zone" in str(k).lower() and str(k) != "zone_active"),
                reason="effect:remove_zone:zone_active",
                ctx=ctx,
                payload={"effect": deepcopy(eff)},
            )
            self.state.log_event("effect", f"Zone {zone_id or 'all'} inactive", {"zone_active": self.state.global_flags.get("zone_active")})
            self.expire_statuses_if_zone_inactive(reason="zone_inactive", ctx=ctx)
        elif etype == "gain_skill_point_on_battle_start":
            return self.apply_effect({"type": "gain_skill_point", "amount": eff.get("amount", 0)}, ctx)
        elif etype == "deal_damage":
            packet = eff.get("damage_packet") or eff.get("packet")
            if not packet:
                self.state.log_event("effect_skip", "deal_damage skipped without damage_packet", {"effect": eff})
            else:
                action = deepcopy(ctx.get("action", {})) if isinstance(ctx.get("action"), dict) else {}
                action.setdefault("id", f"effect_{packet.get('id','damage')}")
                action.setdefault("actor_id", ctx.get("actor_id"))
                action.setdefault("tags", normalize_str_list(action.get("tags", [])) + ["attack"])
                packet = self.normalize_damage_packet_schema(packet)
                targets = self.resolve_packet_targets(packet, action, ctx, ctx.get("targets", []))
                targets = self.derived_damage_live_targets(targets, ctx, effect_name=str(eff.get("id") or packet.get("id") or "deal_damage"))
                actor = self.state.unit(action["actor_id"])
                for target_id in targets:
                    if target_id not in self.state.units or not self.state.unit(target_id).alive:
                        continue
                    packet_ctx = {**ctx, "action": action, "packet": packet, "target_id": target_id, "target": self.state.unit(target_id)}
                    self.run_triggers("before_damage", packet_ctx)
                    result = self.resolve_damage_packet(packet, actor, self.state.unit(target_id), action, ctx.get("events", {}), packet_ctx)
                    self.apply_damage_result(result, packet_ctx)
                    packet_ctx["damage_result"] = result
                    self.run_triggers("after_damage", packet_ctx)
                    if result.get("target_defeated"):
                        self.note_action_defeat(target_id, actor.id, str(packet.get("damage_type") or "deal_damage"), ctx)
                        self.apply_kill_energy(actor, self.state.unit(target_id), action, ctx=action_ctx)
                        self.run_triggers("after_defeat_enemy", packet_ctx)
        elif etype in {"detonate_dot_damage", "detonate_dots", "trigger_dot_damage_now", "trigger_dots_now"}:
            # Kafka-style immediate DoT settlement baseline.  DoTs resolve in
            # current status order and stop as soon as the target dies.  Kill
            # credit/energy belongs to the unit that applied/generated the DoT,
            # not to the unit that triggered the detonation.
            include_break_dot = coerce_bool(eff.get("include_break_dot", True), default=True)
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                if target_id not in self.state.units:
                    continue
                target = self.state.unit(target_id)
                if not target.alive:
                    continue
                dot_rows = self.detonatable_dot_payloads(target, include_break_dot=include_break_dot)
                if eff.get("status_ids"):
                    wanted = {str(x) for x in (eff.get("status_ids") if isinstance(eff.get("status_ids"), list) else [eff.get("status_ids")])}
                    dot_rows = [(st, payload) for st, payload in dot_rows if st.id in wanted]
                detonated = 0
                for st, payload in dot_rows:
                    if not target.alive:
                        self.state.log_event("derived_damage_skip", f"DoT detonation stopped after {target.id} was defeated", {"target": target.id, "effect": etype, "reason": "dot_target_defeated", "detonated": detonated})
                        break
                    result = self.dot_damage_result_for_status(target, st, payload)
                    if result is None:
                        self.state.log_event("dot_damage_skip", f"{target.id}.{st.id} DoT detonation unresolved", {"unit": target.id, "status": st.id, "payload": payload})
                        continue
                    source_actor = self.state.units.get(str(result.get("actor_id")))
                    dot_action = {"id": eff.get("id", "detonate_dot_damage"), "tags": ["dot_damage", "detonated_dot", "can_trigger_kill_energy"]}
                    dot_ctx = {**ctx, "actor_id": result.get("actor_id"), "actor": source_actor, "target_id": target.id, "target": target, "status": st, "packet": {"id": result.get("packet_id"), "damage_type": result.get("damage_type", "dot_damage"), "element": result.get("element"), "ignore_shield": coerce_bool(payload.get("ignore_shield", False), default=False)}, "action": dot_action}
                    self.apply_damage_result(result, dot_ctx)
                    dot_ctx["damage_result"] = result
                    detonated += 1
                    self.state.log_event("dot_damage", f"{target.id}.{st.id} detonates for {result.get('damage', 0.0):.3f}", {"unit": target.id, "status": st.id, "source": result.get("actor_id"), "damage": result.get("damage"), "damage_type": result.get("damage_type")})
                    self.run_triggers("after_hp_change", dot_ctx)
                    if result.get("target_defeated"):
                        if source_actor is not None:
                            self.note_action_defeat(target.id, source_actor.id, str(result.get("damage_type") or "dot_damage"), ctx)
                            self.apply_kill_energy(source_actor, target, dot_action)
                        self.run_triggers("after_defeat_enemy", dot_ctx)
                        remaining = max(0, len(dot_rows) - detonated)
                        if remaining:
                            self.state.log_event("derived_damage_skip", f"DoT detonation stopped after {target.id} was defeated", {"target": target.id, "effect": etype, "reason": "dot_target_defeated", "detonated": detonated, "remaining_dot_count": remaining})
                        break
                self.state.log_event("effect", f"Detonated {detonated} DoT statuses on {target.id}", {"target": target.id, "detonated": detonated, "effect": etype})
        elif etype == "enhance_souldragon":
            # Generic Souldragon enhancement lifecycle: store both a global audit
            # flag and unit-local counters when the attached unit exists.
            self.commit_global_flag(str(etype), True, reason="effect:enhance_souldragon", ctx=ctx, payload={"effect": deepcopy(eff)})
            added = coerce_int(eff.get("remaining_actions_added", eff.get("remaining_souldragon_actions", self.souldragon_template_value("enhanced_action_count", 2.0))), 0)
            dragon_id = str(eff.get("target") or eff.get("unit_id") or "souldragon")
            if added:
                self.commit_global_flag(
                    "souldragon_enhanced_actions",
                    coerce_float(self.state.global_flags.get("souldragon_enhanced_actions", 0.0)) + added,
                    reason="effect:enhance_souldragon:pending_actions",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff), "added": added},
                )
            if dragon_id in self.state.units:
                dragon = self.state.unit(dragon_id)
                old = coerce_int(dragon.flags.get("remaining_enhanced_actions", 0), 0)
                self.commit_unit_flag(dragon, "is_enhanced", True, reason="effect:enhance_souldragon", ctx=ctx, payload={"effect": deepcopy(eff)})
                self.commit_unit_flag(dragon, "souldragon_enhanced", True, reason="effect:enhance_souldragon", ctx=ctx, payload={"effect": deepcopy(eff)})
                self.commit_unit_flag(dragon, "remaining_enhanced_actions", old + added, reason="effect:enhance_souldragon:remaining_actions", ctx=ctx, payload={"effect": deepcopy(eff), "old": old, "added": added})
                self.state.log_event("summon_lifecycle", f"{dragon_id} enhanced actions {old}->{old+added}", {"unit": dragon_id, "added": added})
            else:
                self.state.log_event("effect", f"Recorded model-pack effect {etype}", {"effect": eff, "unit_missing": dragon_id})
        elif etype in {"apply_enemy_field_status", "auto_use_skill_on_battle_start"}:
            # Minimal model-pack support: these are represented as flags so route
            # cases can branch on them, while exact action execution remains route-driven.
            self.commit_global_flag(str(etype), True, reason=f"effect:{etype}", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Recorded model-pack effect {etype}", {"effect": eff})
        elif etype == "record_skill_property_modifier":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                mods = deepcopy(unit.flags.get("skill_property_modifiers", []))
                if not isinstance(mods, list):
                    mods = []
                record = {"skill_name": eff.get("skill_name"), "property": eff.get("property"), "value": eff.get("value")}
                mods.append(record)
                self.commit_unit_flag(unit, "skill_property_modifiers", mods, reason="effect:record_skill_property_modifier", ctx=ctx, payload={"effect": deepcopy(eff), "record": deepcopy(record)})
                self.state.log_event("effect", f"Recorded skill property modifier for {target_id}", record)
        elif etype == "enqueue_extra_turn_by_skill_type":
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            skill_type = str(eff.get("skill_type") or "")
            action_id = self.find_action_by_skill_type(actor_id, skill_type) if actor_id else None
            if action_id:
                launch_eff = {"type": "launch_action", "actor": actor_id, "action": action_id, "queue": eff.get("queue", "immediate_queue"), "turn_kind": "extra_turn", "extra_turn_type": skill_type}
                if eff.get("target_policy"):
                    launch_eff["target_policy"] = eff.get("target_policy")
                return self.apply_effect(launch_eff, ctx)
            key = f"pending_extra_turn_by_skill_type:{actor_id}:{skill_type}"
            self.commit_global_flag(key, coerce_float(self.state.global_flags.get(key, 0)) + 1, reason="effect:pending_extra_turn_by_skill_type", ctx=ctx, payload={"actor": actor_id, "skill_type": skill_type})
            self.state.log_event("effect", f"Recorded pending extra turn by skill type {skill_type}", {"actor": actor_id, "skill_type": skill_type})
        elif etype == "launch_action":
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            action_id = eff.get("action") or eff.get("action_id")
            action = self.get_action_def(actor_id, action_id)
            target_policy = eff.get("target_policy") or action.get("target_policy") or "same_target"
            # Do not permanently resolve queued targets too early. If a wave transition
            # happens before the queued action is executed, target selection must be
            # re-evaluated against the then-current enemies. Explicit eff.targets still wins.
            explicit_targets = self.normalize_targets(eff.get("targets")) if "targets" in eff else None
            queue_name = eff.get("queue", "immediate_queue")
            turn_kind = self.queued_action_turn_kind(eff, action, queue_name)
            queued = {
                "actor": actor_id,
                "action": action_id,
                "targets": explicit_targets,
                "defer_target_policy": target_policy,
                "context_target_id": ctx.get("target_id"),
                "events": eff.get("events", {}),
                "turn_kind": turn_kind,
                "extra_turn_type": eff.get("extra_turn_type"),
                "queued_wave_index": self.state.wave_index,
                "carry_across_wave": self.queued_action_carry_across_wave(eff, action, default=True),
                "queued_actor_phase": self.effective_unit_phase(ctx.get("actor") if ctx.get("actor") is not None else (self.state.unit(actor_id) if actor_id in self.state.units else None)),
                "carry_across_phase": coerce_bool(eff.get("carry_across_phase", action.get("carry_across_phase", False) if isinstance(action, dict) else False), default=False),
            }
            # Enemy one-turn multi-action chains must be interruptible.  Preserve
            # chain metadata on the queued continuation so drain_queues can
            # re-check death/break/control right before the follow-up resolves.
            for meta_key in (
                "enemy_action_chain", "enemy_chain_id", "chain_id", "chain_index",
                "interrupt_policy", "interruptible_by_break", "interruptible_by_control",
                "interruptible_by_death", "cancel_chain_on_interrupt",
            ):
                if meta_key in eff:
                    queued[meta_key] = deepcopy(eff.get(meta_key))
                elif isinstance(action, dict) and meta_key in action:
                    queued[meta_key] = deepcopy(action.get(meta_key))
            if eff.get("queue") == "immediate_queue" and ctx.get("actor") is not None and getattr(ctx.get("actor"), "side", None) == "enemy":
                queued.setdefault("enemy_action_chain", coerce_bool(eff.get("enemy_action_chain", action.get("enemy_action_chain", False) if isinstance(action, dict) else False), default=False))
            self.commit_queue_append(
                queue_name,
                queued,
                reason="effect:launch_action",
                ctx=ctx,
                payload={"effect": deepcopy(eff), "requested_queue": queue_name},
            )
            self.state.log_event("effect", f"Queued action {actor_id}.{action_id} in {queue_name}", queued)
        elif etype == "modify_damage_packet":
            self.apply_modify_damage_packet(eff, ctx)
        elif etype == "random_select_flag":
            values = list(eff.get("values") or [])
            if not values or not eff.get("key"):
                self.state.log_event("effect_skip", "random_select_flag skipped without key/values", {"effect": eff})
            else:
                event_id = eff.get("event_id") or f"{ctx.get('actor_id')}.{eff.get('key')}.random_select"
                forced = (ctx.get("events") or {}).get(event_id, (self.raw_case.get("events") or {}).get(event_id, None))
                idx = None
                if forced is not None:
                    if isinstance(forced, str) and forced in values:
                        idx = values.index(forced)
                    else:
                        try:
                            forced_i = int(forced)
                            idx = forced_i if 0 <= forced_i < len(values) else None
                        except Exception:
                            idx = None
                if idx is None:
                    idx = 0
                value = values[idx]
                self.record_rng_event(
                    ctx,
                    event_type="random_select_flag",
                    event_id=str(event_id),
                    mode="forced" if forced is not None else "deterministic_first",
                    outcome={"index": idx, "value": value},
                    probability={"choice_count": len(values)},
                    payload={"key": eff.get("key"), "values": deepcopy(values), "forced": deepcopy(forced)},
                    reason="rng:random_select_flag",
                )
                self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:random_select_flag", ctx=ctx, payload={"event_id": event_id, "index": idx, "values": values})
                self.state.log_event("random_select", f"Random selected {eff['key']}={value}", {"event_id": event_id, "index": idx, "values": values})
        elif etype == "set_dynamic_entity_param":
            targets = self.resolve_effect_targets({"target": eff.get("target")}, ctx, default="actor")
            params = self.resolve_effect_targets({"target": eff.get("param_target")}, ctx, default="target")
            value = params[0] if params else (ctx.get("target_id") or (targets[0] if targets else None))
            if not eff.get("key") or value is None:
                self.state.log_event("effect_skip", "set_dynamic_entity_param skipped without key/value", {"effect": eff, "targets": targets, "params": params})
            else:
                self.commit_global_flag(str(eff["key"]), str(value), reason="effect:set_dynamic_entity_param", ctx=ctx, payload={"effect": deepcopy(eff), "targets": targets, "params": params})
                self.state.log_event("effect", f"Set dynamic entity {eff['key']}={value}", {"targets": targets, "params": params})
        elif etype == "trigger_custom_string":
            value = eff.get("custom_string")
            if value is None:
                self.state.log_event("effect_skip", "trigger_custom_string skipped without value", {"effect": eff})
            else:
                self.commit_global_flag("last_custom_string", str(value), reason="effect:trigger_custom_string", ctx=ctx, payload={"effect": deepcopy(eff)})
                self.state.log_event("custom_string", f"Trigger custom string {value}", {"custom_string": value})
        elif etype == "random_choice":
            choices = list(eff.get("choices") or [])
            if not choices:
                self.state.log_event("effect_skip", "random_choice skipped without choices", {"effect": eff})
            else:
                event_id = eff.get("event_id") or f"{ctx.get('actor_id')}.{ctx.get('status_id','random_choice')}.random_choice"
                forced = (ctx.get("events") or {}).get(event_id, (self.raw_case.get("events") or {}).get(event_id, None))
                available_indices = [int(row.get("index", i)) for i, row in enumerate(choices)]
                random_count = max(1, coerce_int(eff.get("random_count", 1), 1))
                mask_key = eff.get("random_mask_key")
                random_unique = coerce_bool(eff.get("random_unique", False), default=False)
                used_indices: set[int] = set()
                if random_unique and mask_key:
                    raw_mask = self.state.global_flags.get(str(mask_key), [])
                    if isinstance(raw_mask, list):
                        used_indices = {coerce_int(x, -999999) for x in raw_mask}
                    elif isinstance(raw_mask, str):
                        used_indices = {coerce_int(x.strip(), -999999) for x in raw_mask.split(',') if x.strip()}
                forced_indices: list[int] = []
                if forced is not None:
                    if isinstance(forced, list):
                        raw_items = forced
                    else:
                        raw_items = [x.strip() for x in str(forced).split(',') if str(x).strip()]
                    for item in raw_items:
                        try:
                            forced_indices.append(int(item))
                        except Exception:
                            pass
                selected_indices: list[int] = []
                for idx in forced_indices:
                    if idx in available_indices and idx not in selected_indices:
                        selected_indices.append(idx)
                        if len(selected_indices) >= random_count:
                            break
                if len(selected_indices) < random_count:
                    for idx in available_indices:
                        if idx in selected_indices:
                            continue
                        if random_unique and idx in used_indices:
                            continue
                        selected_indices.append(idx)
                        if len(selected_indices) >= random_count:
                            break
                if len(selected_indices) < random_count and random_unique:
                    # All branches are masked.  Validation mode resets the mask and
                    # deterministically takes the first remaining branches instead
                    # of failing or executing all branches.
                    used_indices.clear()
                    for idx in available_indices:
                        if idx not in selected_indices:
                            selected_indices.append(idx)
                        if len(selected_indices) >= random_count:
                            break
                selected_rows = [row for row in choices if int(row.get("index", -1)) in selected_indices]
                if not selected_rows:
                    selected_rows = [choices[0]]; selected_indices = [int(choices[0].get("index", 0))]
                self.record_rng_event(
                    ctx,
                    event_type="random_choice",
                    event_id=str(event_id),
                    mode="forced" if forced is not None else "deterministic_order",
                    outcome={"indices": list(selected_indices), "index": selected_indices[0] if selected_indices else None},
                    probability={"choice_count": len(choices), "odds": deepcopy(eff.get("odds"))},
                    payload={
                        "forced": deepcopy(forced),
                        "available_indices": list(available_indices),
                        "random_count": random_count,
                        "random_unique": random_unique,
                        "random_mask_key": mask_key,
                        "used_indices_before": sorted(used_indices),
                    },
                    reason="rng:random_choice",
                )
                if random_unique and mask_key:
                    new_used = sorted(used_indices.union(set(selected_indices)))
                    if coerce_bool(eff.get("auto_reset_random_mask", False), default=False) and len(new_used) >= len(available_indices):
                        new_used = []
                    self.commit_global_flag(str(mask_key), new_used, reason="effect:random_choice:mask", ctx=ctx, payload={"event_id": event_id, "selected_indices": selected_indices})
                self.state.log_event("random_choice", f"RandomConfig chose branches {selected_indices}", {"event_id": event_id, "indices": selected_indices, "index": selected_indices[0] if selected_indices else None, "random_count": random_count, "random_unique": random_unique, "random_mask_key": mask_key, "choice_count": len(choices), "odds": eff.get("odds")})
                for row in selected_rows:
                    idx = int(row.get("index", 0))
                    for nested in row.get("effects") or []:
                        self.apply_effect(nested, {**ctx, "random_choice_index": idx, "random_choice_indices": selected_indices})
        elif etype == "conditional_branch":
            cond = eff.get("condition", {})
            cond_ctx = ctx
            # ByRandomChance predicates around generated AddModifier branches are
            # debuff/effect-hit gates.  Give condition evaluation the first status
            # target so EHR/RES can be included in the logged probability.
            if isinstance(cond, dict) and isinstance(cond.get("chance_gate"), dict) and cond["chance_gate"].get("use_effect_hit") and "target_id" not in ctx:
                for nested_eff in eff.get("effects_if_true", eff.get("effects", [])) or []:
                    if isinstance(nested_eff, dict) and nested_eff.get("type") == "add_status":
                        targets = self.resolve_effect_targets(nested_eff, ctx, default="actor")
                        if targets:
                            tid = targets[0]
                            cond_ctx = {**ctx, "target_id": tid, "target": self.state.unit(tid)}
                        break
            branch = eff.get("effects_if_true", eff.get("effects", [])) if self.eval_condition(cond, cond_ctx) else eff.get("effects_if_false", [])
            for nested_eff in branch or []:
                self.apply_effect(nested_eff, ctx)
        elif etype == "gain_skill_point":
            self.apply_effect({"type": "modify_skill_points", "amount": coerce_float(eff.get("amount", 1), 1.0), "overflow_record": eff.get("overflow_record")}, ctx)
        elif etype == "consume_skill_point":
            self.apply_effect({"type": "modify_skill_points", "amount": -coerce_int(eff.get("amount", 1), 1)}, ctx)
        elif etype == "set_flag":
            self.commit_global_flag(str(eff["key"]), coerce_comparison_value(eff.get("value", True)), reason="effect:set_flag", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Set flag {eff['key']}={self.state.global_flags[eff['key']]}")
        elif etype == "set_flag_from_context_value":
            kind = str(eff.get("context_value_type") or eff.get("variate_type") or "")
            if kind == "SetDynamicValueByAttackTargetCount":
                value = len(ctx.get("attacked_targets") or ctx.get("targets") or ([ctx.get("target_id")] if ctx.get("target_id") else []))
            elif str(eff.get("variate_type")) == "ParamValue" or kind == "SetDynamicValueByVariateType":
                value = ctx.get("consumed_skill_points", ctx.get("skill_point_delta", ctx.get("param_value", 0)))
                if isinstance(value, (int, float)) and value < 0:
                    value = abs(value)
            else:
                value = ctx.get("value", ctx.get("param_value", 0))
            self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:set_flag_from_context_value", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Set flag {eff['key']} from context={self.state.global_flags[eff['key']]}", {"context_value_type": eff.get("context_value_type"), "variate_type": eff.get("variate_type")})
        elif etype == "set_flag_from_property":
            targets = self.resolve_effect_targets(eff, ctx, default="actor")
            value = None
            if targets:
                value = self.read_unit_property(self.state.unit(targets[0]), eff.get("property"))
            if value is None:
                # Unknown/derived engine-side properties such as AttackConvert must
                # not be silently coerced to zero; that would make downstream
                # symbolic runtime formulas look resolved with a false value.
                model = describe_engine_property(eff.get("property")).to_dict()
                self.state.log_event("effect_skip", f"Set flag {eff['key']} from unresolved property skipped", {"property": eff.get("property"), "targets": targets, "engine_property_model": model})
            else:
                self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:set_flag_from_property", ctx=ctx, payload={"effect": deepcopy(eff), "property": eff.get("property")})
                self.state.log_event("effect", f"Set flag {eff['key']} from property={self.state.global_flags[eff['key']]}", {"property": eff.get("property")})
        elif etype == "set_flag_from_status_value":
            targets = self.resolve_effect_targets(eff, ctx, default="actor")
            value = self.read_status_value(self.state.unit(targets[0]), eff.get("status_id"), eff.get("value_type"), eff.get("key")) if targets else 0
            self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:set_flag_from_status_value", ctx=ctx, payload={"effect": deepcopy(eff), "targets": targets})
            self.state.log_event("effect", f"Set flag {eff['key']} from status={self.state.global_flags[eff['key']]}", {"status_id": eff.get("status_id"), "value_type": eff.get("value_type")})
        elif etype == "copy_flag":
            value = self.read_flag_or_status_value(eff, ctx)
            self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:copy_flag", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Copied flag {eff.get('source_key')} -> {eff['key']}={self.state.global_flags[eff['key']]}", {"source_status_id": eff.get("source_status_id")})
        elif etype == "trigger_custom_event":
            event_id = str(eff.get("custom_event_id") or eff.get("event_id") or "")
            if not event_id:
                self.state.log_event("effect_skip", "trigger_custom_event skipped without custom_event_id", {"effect": eff})
            else:
                for target_id in self.resolve_effect_targets(eff, ctx, default="actor") or [ctx.get("actor_id")]:
                    custom_ctx = {**ctx, "target_id": target_id, "custom_event_id": event_id, "context": {**ctx.get("context", {}), "custom_event_id": event_id}}
                    if target_id in self.state.units:
                        custom_ctx["target"] = self.state.unit(target_id)
                    self.state.log_event("effect", f"Trigger custom event {event_id}", {"target": target_id})
                    self.run_triggers("custom_event", custom_ctx)
        elif etype == "record_visual_effect":
            targets = self.resolve_effect_targets(eff, ctx, default="actor")
            self.state.log_event("visual_effect", f"Record visual effect {eff.get('effect_path')}", {"targets": targets, "effect_path": eff.get("effect_path")})
        elif etype == "record_preshow_event":
            self.state.log_event("preshow_audit", f"Record preshow event {eff.get('event_name')}", {"status_id": eff.get("status_id"), "owner_avatar_id": eff.get("owner_avatar_id"), "condition": eff.get("condition")})
        elif etype == "set_unit_flag":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                self.commit_unit_flag(unit, str(eff["key"]), coerce_comparison_value(eff.get("value", True)), reason="effect:set_unit_flag", ctx=ctx, payload={"effect": deepcopy(eff)})
                self.state.log_event("effect", f"Set {target_id}.{eff['key']}={unit.flags[eff['key']]}")
        elif etype == "copy_unit_flag":
            source_targets = self.resolve_effect_targets({"target": eff.get("source_target", eff.get("target", "actor"))}, ctx, default="actor")
            value = None
            source_key = str(eff.get("source_key") or "")
            if source_targets:
                src = self.state.unit(source_targets[0])
                value = src.flags.get(source_key, 0)
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                self.commit_unit_flag(unit, str(eff["key"]), coerce_comparison_value(value), reason="effect:copy_unit_flag", ctx=ctx, payload={"effect": deepcopy(eff), "source_targets": source_targets})
                self.state.log_event("effect", f"Copy unit flag {source_key} -> {target_id}.{eff['key']}={unit.flags[eff['key']]}", {"source_targets": source_targets})
        elif etype == "set_unit_flag_from_target_count":
            actor = self.state.unit(ctx.get("actor_id")) if ctx.get("actor_id") in self.state.units else None
            count = 0
            spec = deepcopy(eff.get("target_spec") or {})
            filters = list(eff.get("filters") or []) + list(spec.get("filters") or [])
            if actor is not None:
                units = self.enemy_ai_target_candidates_from_spec(actor, spec)
                if filters:
                    units = [u for u in units if self.target_unit_passes_ai_filters(actor, u, filters, ctx)]
                count = len(units)
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                self.commit_unit_flag(unit, str(eff["key"]), count, reason="effect:set_unit_flag_from_target_count", ctx=ctx, payload={"target_spec": spec, "filters": filters})
                self.state.log_event("effect", f"Set {target_id}.{eff['key']} from target count={count}", {"target_spec": spec, "filters": filters})
        elif etype == "modify_unit_counter":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                key = eff["key"]
                old = coerce_float(unit.flags.get(key, eff.get("default", 0)))
                new = old + coerce_float(eff.get("amount", 0))
                if "min" in eff: new = max(coerce_float(eff["min"]), new)
                if "max" in eff: new = min(coerce_float(eff["max"]), new)
                self.commit_unit_flag(unit, str(key), new, reason="effect:modify_unit_counter", ctx=ctx, payload={"effect": deepcopy(eff), "old": old})
                self.state.log_event("effect", f"{target_id}.{key} {old} -> {new}")
        elif etype == "hp_loss":
            aliased = deepcopy(eff)
            aliased["type"] = "damage_unit"
            if "amount" not in aliased:
                if "amount_percent_max_hp" in aliased:
                    aliased["target_max_hp_pct"] = aliased.get("amount_percent_max_hp")
                elif "hp_pct" in aliased:
                    aliased["target_max_hp_pct"] = aliased.get("hp_pct")
            aliased.setdefault("ignore_shield", True)
            return self.apply_effect(aliased, ctx)
        elif etype == "summon":
            for nested in eff.get("effects", []) or []:
                if isinstance(nested, dict) and "summon_entity" in nested:
                    entity = str(nested.get("summon_entity"))
                    count = coerce_int(nested.get("count", 1), 1)
                    for i in range(count):
                        base_id = f"{entity}_{i+1}" if count > 1 else entity
                        unit_id = base_id
                        n = 1
                        while unit_id in self.state.units:
                            n += 1
                            unit_id = f"{base_id}_{n}"
                        template = deepcopy(
                            (self.raw_case.get("unit_templates", {}) or {}).get(entity)
                            or (self.raw_case.get("summon_templates", {}) or {}).get(entity)
                            or nested.get("unit")
                            or {"side": "enemy", "hp": 1, "max_hp": 1, "speed": 100, "tags": ["summoned_placeholder"]}
                        )
                        self.apply_effect({"type": "summon_unit", "unit_id": unit_id, "unit": template, "side": template.get("side", "enemy")}, ctx)
                elif isinstance(nested, dict):
                    self.apply_effect(nested, ctx)
        elif etype is None and "summon_entity" in eff:
            return self.apply_effect({"type": "summon", "effects": [eff]}, ctx)
        elif etype == "force_defeat":
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                unit = self.state.unit(target_id)
                if not unit.alive:
                    continue
                result = self.apply_hp_loss(unit, unit.hp + unit.shield, {**ctx, "target_id": target_id, "target": unit}, label="force_defeat", ignore_shield=True, carry_over_hp_bar_damage=True)
                nested_ctx = {**ctx, "target_id": target_id, "target": unit, "damage_result": result}
                self.run_triggers("after_hp_change", nested_ctx)
                if result.get("target_defeated"):
                    self.run_triggers("after_defeat_enemy", nested_ctx)
            if not ctx.get("action"):
                self.check_wave_transition(ctx=ctx)
        elif etype == "damage_unit":
            raw_targets = self.resolve_effect_targets(eff, ctx, default="target")
            for target_id in self.derived_damage_live_targets(raw_targets, ctx, effect_name=str(eff.get("id") or "damage_unit")):
                phase_locked = ctx.get("phase_locked_targets")
                if isinstance(phase_locked, set) and target_id in phase_locked:
                    self.record_process_event(
                        ctx,
                        event_type="effect_damage_target_skip",
                        subject_id=str(target_id),
                        reason="effect_damage:phase_boundary_locked",
                        payload={"target_id": str(target_id), "effect": deepcopy(eff), "phase_locked_targets": sorted(str(x) for x in phase_locked)},
                    )
                    self.state.log_event(
                        "effect_damage_skip",
                        f"Skip {target_id}: phase HP boundary locked further effect damage in this action",
                        {"target": target_id, "effect": eff},
                    )
                    continue
                unit = self.state.unit(target_id)
                if not unit.alive:
                    continue
                amount = coerce_float(eff.get("amount", 0.0))
                if "target_max_hp_pct" in eff:
                    amount += unit.max_hp * coerce_float(eff["target_max_hp_pct"])
                if "source_max_hp_pct" in eff:
                    src_id = self.resolve_special_unit(eff.get("source", "actor"), ctx)
                    amount += self.state.unit(src_id).max_hp * coerce_float(eff["source_max_hp_pct"])
                result = self.apply_hp_loss(
                    unit,
                    amount,
                    {**ctx, "target_id": target_id, "target": unit, "damage_result": None},
                    label="effect_damage",
                    ignore_shield=coerce_bool(eff.get("ignore_shield", False), default=False),
                    carry_over_hp_bar_damage=eff.get("carry_over_hp_bar_damage", eff.get("carry_over_damage", None)),
                )
                nested_ctx = {**ctx, "target_id": target_id, "target": unit, "damage_result": result}
                if result.get("hp_bar_depleted"):
                    self.apply_hp_bar_depleted_effects(result, nested_ctx)
                    if unit.alive and unit.flags.get("phase_transition_immediate_action"):
                        action_id = unit.flags.get("phase_transition_immediate_action")
                        if action_id is True:
                            action_id = self.default_probe_action_id(unit) or next(iter(unit.action_defs), None)
                        if action_id:
                            self.state.log_event("enemy_mechanic", f"{unit.id} phase transition queues immediate action", {"action": action_id, "bars_depleted": result.get("bars_depleted")})
                            self.apply_effect({"type": "immediate_action", "actor": unit.id, "action": action_id, "target_policy": "first_ally"}, nested_ctx)
                if result.get("phase_damage_locked_until_action_end"):
                    phase_locked = ctx.get("phase_locked_targets")
                    if isinstance(phase_locked, set):
                        phase_locked.add(target_id)
                        self.record_process_event(
                            ctx,
                            event_type="phase_damage_lock",
                            subject_id=str(target_id),
                            reason="effect_damage:phase_boundary_lock",
                            payload={
                                "target_id": str(target_id),
                                "effect": deepcopy(eff),
                                "hp_bars_remaining": result.get("hp_bars_remaining"),
                                "bars_depleted": result.get("bars_depleted"),
                                "phase_locked_targets": sorted(str(x) for x in phase_locked),
                            },
                        )
                self.run_triggers("after_hp_change", nested_ctx)
                if result.get("hp_bar_depleted"):
                    self.run_triggers("after_hp_bar_depleted", nested_ctx)
                if result.get("target_defeated"):
                    actor = ctx.get("actor") if isinstance(ctx.get("actor"), UnitState) else None
                    if actor is None and ctx.get("actor_id") in self.state.units:
                        actor = self.state.unit(ctx["actor_id"])
                    self.note_action_defeat(target_id, actor.id if actor is not None else ctx.get("actor_id"), str(eff.get("damage_type") or eff.get("id") or "effect_damage"), ctx)
                    self.apply_kill_energy_for_effect_damage(actor, unit, ctx)
                    nested_ctx["actor"] = actor or nested_ctx.get("actor")
                    self.run_triggers("after_defeat_enemy", nested_ctx)
            # Do not spawn the next wave in the middle of an action-owned effect.
            # resolve_action performs the action-level wave transition after all
            # packets/effects/resource gains have settled. This keeps effect damage
            # consistent with normal damage packets and prevents later packets in
            # the same action from hitting a newly spawned wave.
            if not ctx.get("action"):
                self.check_wave_transition(ctx=ctx)
        elif etype == "heal_unit":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                amount = coerce_float(eff.get("amount", 0.0))
                if "target_max_hp_pct" in eff:
                    amount += unit.max_hp * coerce_float(eff["target_max_hp_pct"])
                old = unit.hp
                heal_cap_ratio = coerce_float(unit.flags.get("max_restorable_hp_ratio", unit.flags.get("recoverable_hp_cap_ratio", 1.0)), 1.0)
                for st, mods in self.applicable_status_modifiers(unit, ctx or {}):
                    if "max_restorable_hp_ratio" in mods:
                        heal_cap_ratio = min(heal_cap_ratio, coerce_float(mods.get("max_restorable_hp_ratio"), 1.0))
                    if "recoverable_hp_cap_ratio" in mods:
                        heal_cap_ratio = min(heal_cap_ratio, coerce_float(mods.get("recoverable_hp_cap_ratio"), 1.0))
                heal_cap = unit.max_hp * max(0.0, min(1.0, heal_cap_ratio))
                self.commit_unit_hp(
                    unit,
                    min(heal_cap, unit.hp + amount),
                    reason="effect:heal",
                    ctx=ctx,
                    payload={"amount": amount, "heal_cap": heal_cap, "max_restorable_hp_ratio": heal_cap_ratio, "effect": deepcopy(eff)},
                )
                self.state.log_event("effect_heal", f"{target_id} heals {amount:.3f} HP", {"old_hp": old, "new_hp": unit.hp, "heal_cap": heal_cap, "max_restorable_hp_ratio": heal_cap_ratio})
                # Phase 2: 治疗 HP 记录
                self._settle(ctx, "hp",
                    unit_id=target_id, delta=unit.hp - old,
                    old_value=old, new_value=unit.hp, max_hp=unit.max_hp,
                    reason=f"heal: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                    record_state_change=False,
                )
        elif etype == "cleanse_debuffs":
            count = coerce_int(eff.get("count", eff.get("amount", 1)), 1)
            source = str(eff.get("source_template") or eff.get("source") or etype)
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                if target_id in self.state.units:
                    self.cleanse_debuffs_from_unit(self.state.unit(target_id), count, source=source, ctx=ctx)
        elif etype == "summon_unit":
            unit_id = eff["unit_id"]
            raw = deepcopy(eff["unit"])
            raw.setdefault("side", eff.get("side", "enemy"))
            flags = raw.setdefault("flags", {})
            flags.setdefault("summoned", True)
            if eff.get("owner") or eff.get("owner_id") or ctx.get("actor_id"):
                flags.setdefault("owner_id", eff.get("owner") or eff.get("owner_id") or ctx.get("actor_id"))
            if eff.get("attached_to"):
                flags.setdefault("attached_to", eff.get("attached_to"))
                flags.setdefault("attached_unit", True)
            for k in ("lifespan_actions", "remove_when_owner_defeated", "remove_when_attached_target_defeated"):
                if k in eff and k not in flags:
                    flags[k] = eff[k]
            unit = UnitState.from_dict(unit_id, raw)
            self.ensure_souldragon_unit_defaults(unit)
            unit.remaining_av = self.unit_initial_av(unit, raw)
            self.commit_unit_add(
                unit,
                reason="effect:summon_unit",
                ctx=ctx,
                payload={"effect": deepcopy(eff)},
            )
            self.state.log_event("summon", f"Summon unit {unit_id}", {"unit": unit.to_json()})
        elif etype == "modify_toughness":
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                unit = self.state.unit(target_id)
                if unit.toughness is not None:
                    old = unit.toughness
                    self.commit_unit_toughness(unit, unit.toughness + coerce_float(eff.get("amount", 0.0)), reason="effect:modify_toughness", ctx=ctx, payload={"effect": deepcopy(eff)})
                    self.state.log_event("toughness", f"{target_id} toughness {old} -> {unit.toughness}")
        elif etype == "modify_shield":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                amount = coerce_float(eff.get("amount", 0.0))
                if "target_max_hp_pct" in eff:
                    amount += unit.max_hp * coerce_float(eff["target_max_hp_pct"])
                if "source_stat_pct" in eff:
                    src_id = self.resolve_special_unit(eff.get("source", "actor"), ctx)
                    stat_name = str(eff.get("source_stat", "atk"))
                    if src_id in self.state.units:
                        amount += self.contextual_stat(self.state.unit(src_id), stat_name, {**ctx, "target_id": target_id, "target": unit}) * coerce_float(eff.get("source_stat_pct", 0.0))
                self.apply_stackable_shield(target_id, amount, eff, ctx, reason="modify_shield")
        elif etype == "immediate_action":
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            action_id = eff.get("action") or eff.get("action_id")
            action = self.get_action_def(actor_id, action_id)
            target_policy = eff.get("target_policy") or action.get("target_policy") or "manual"
            explicit_targets = self.normalize_targets(eff.get("targets")) if "targets" in eff else None
            queue_name = eff.get("queue", "immediate_queue")
            # Keep target selection lazy unless explicit targets are provided.
            # This matches launch_action and is important for after_defeat /
            # hp_bar_depleted effects: a queued immediate action may resolve only
            # after the current action finishes and a wave transition has spawned
            # new enemies. Eagerly storing [] or a now-dead target would silently
            # drop the queued action.
            queued = {
                "actor": actor_id,
                "action": action_id,
                "targets": explicit_targets,
                "defer_target_policy": target_policy,
                "context_target_id": ctx.get("target_id"),
                "events": eff.get("events", {}),
                "turn_kind": self.queued_action_turn_kind(eff, action, queue_name),
                "extra_turn_type": eff.get("extra_turn_type"),
                "queued_wave_index": self.state.wave_index,
                "carry_across_wave": self.queued_action_carry_across_wave(eff, action, default=True),
                "queued_actor_phase": self.effective_unit_phase(ctx.get("actor") if ctx.get("actor") is not None else (self.state.unit(actor_id) if actor_id in self.state.units else None)),
                "carry_across_phase": coerce_bool(eff.get("carry_across_phase", action.get("carry_across_phase", False) if isinstance(action, dict) else False), default=False),
            }
            self.commit_queue_append(
                queue_name,
                queued,
                reason="effect:immediate_action",
                ctx=ctx,
                payload={"effect": deepcopy(eff), "requested_queue": queue_name},
            )
            self.state.log_event("effect", f"Immediate action queued {actor_id}.{action_id} in {queue_name}", queued)
        elif etype == "reset_trigger_usage":
            prefix = eff.get("prefix") or eff.get("trigger_id")
            if prefix:
                removed = []
                for k in list(self.state.trigger_usage):
                    if k.startswith(str(prefix)):
                        removed.append(k)
                        self.commit_trigger_usage_remove(
                            k,
                            reason="effect:reset_trigger_usage",
                            ctx=ctx,
                            payload={"effect": deepcopy(eff), "prefix": prefix},
                        )
                self.state.log_event("effect", f"Reset trigger usage prefix {prefix}", {"removed": removed})
        elif etype == "zone_additional_damage":
            source_id = eff.get("source") or eff.get("actor") or eff.get("owner") or ctx.get("owner_id") or ctx.get("actor_id")
            if source_id not in self.state.units:
                self.state.log_event("effect_skip", "zone_additional_damage skipped without live source", {"source": source_id, "effect": eff})
                return
            raw_hit_targets = [str(tid) for tid in (ctx.get("attacked_targets", []) or [])]
            hit_targets = self.derived_damage_live_targets(raw_hit_targets, ctx, effect_name=str(eff.get("id") or "zone_additional_damage"))
            if not hit_targets:
                raw_hit_targets = self.resolve_effect_targets(eff, ctx, default="target")
                hit_targets = self.derived_damage_live_targets(raw_hit_targets, ctx, effect_name=str(eff.get("id") or "zone_additional_damage"))
            if not hit_targets:
                self.state.log_event("effect_skip", "zone_additional_damage skipped without attacked targets", {"effect": eff})
                return
            if str(eff.get("target_policy", "highest_hp_among_hit_targets")) == "highest_hp_among_hit_targets":
                target_id = max(hit_targets, key=lambda tid: self.state.unit(tid).hp)
            else:
                target_id = hit_targets[0]
            per_hit = coerce_bool(eff.get("per_target_hit", False), default=False)
            count = len(hit_targets) if per_hit else 1
            packet = {
                "id": eff.get("packet_id", "zone_additional_damage"),
                "element": eff.get("element", "quantum"),
                "damage_type": eff.get("damage_type", "additional_damage"),
                "target_policy": "selected_enemy",
                "scaling_stat": eff.get("scaling_stat", eff.get("stat", "hp")),
                "multiplier": eff.get("multiplier", eff.get("multiplier_at_ult_10", 0.0)),
                "can_crit": coerce_bool(eff.get("can_crit", False), default=False),
                "toughness_reduction": eff.get("toughness_reduction", 0.0),
                "is_attack": False,
                "tags": ["additional_damage", "zone_damage"],
            }
            source = self.state.unit(source_id)
            synthetic_action = {
                "id": eff.get("id", "zone_additional_damage"),
                "actor_id": source_id,
                "tags": ["additional_damage", "zone_damage", "can_trigger_kill_energy"],
                "target_policy": "selected_enemy",
            }
            dealt_total = 0.0
            dealt_targets: list[str] = []
            for _ in range(max(1, count)):
                if target_id not in self.state.units or not self.state.unit(target_id).alive:
                    break
                packet_ctx = {**ctx, "actor_id": source_id, "actor": source, "action": synthetic_action, "packet": packet, "target_id": target_id, "target": self.state.unit(target_id)}
                self.run_triggers("before_damage", packet_ctx)
                result = self.resolve_damage_packet(packet, source, self.state.unit(target_id), synthetic_action, [], packet_ctx)
                self.apply_damage_result(result, packet_ctx)
                dealt_total += coerce_float(result.get("final_damage", result.get("damage", 0.0)))
                dealt_targets.append(target_id)
                packet_ctx["damage_result"] = result
                self.run_triggers("after_damage", packet_ctx)
                self.run_triggers("after_hp_change", packet_ctx)
                if result.get("hp_bar_depleted"):
                    self.run_triggers("after_hp_bar_depleted", packet_ctx)
                if result.get("target_defeated"):
                    # Tribbie-style zone/additional damage is owned by its source,
                    # not by the ally whose attack triggered it.  Kill energy and
                    # after_defeat triggers must therefore see actor_id=source_id.
                    self.note_action_defeat(target_id, source_id, "zone_additional_damage", ctx)
                    self.apply_kill_energy_for_effect_damage(source, self.state.unit(target_id), packet_ctx)
                    self.run_triggers("after_defeat_enemy", packet_ctx)
                    break
            zone_ctx = {**ctx, "actor_id": source_id, "actor": source, "zone_additional_targets": dealt_targets, "target_id": target_id, "target": self.state.unit(target_id) if target_id in self.state.units else None, "zone_additional_damage_total": dealt_total}
            self.state.log_event("effect", f"Zone additional damage by {source_id} to {target_id} x{count}", {"total": dealt_total, "targets": dealt_targets})
            self.run_triggers("after_tribbie_zone_additional_damage", zone_ctx)
        elif etype == "zone_followup_true_damage":
            effect = eff.get("effect", {}) if isinstance(eff.get("effect", {}), dict) else eff
            ratio = self.resolve_numeric_expr(effect.get("true_damage_equal_to_total_attack_damage", effect.get("ratio", 0.0)), ctx, default=0.0)
            base_damage = self.resolve_numeric_expr(effect.get("base_damage", ctx.get("total_attack_damage", 0.0)), ctx, default=0.0)
            if base_damage <= 0 and isinstance(ctx.get("damage_result"), dict):
                base_damage = coerce_float(ctx["damage_result"].get("final_damage", 0.0))
            amount = base_damage * ratio
            for target_id in self.resolve_effect_targets(effect, ctx, default="target"):
                if target_id in self.state.units and self.state.unit(target_id).alive:
                    self.apply_effect({"type": "damage_unit", "target": target_id, "amount": amount, "ignore_shield": True}, ctx)
        elif etype == "add_enemy_core_status":
            target_ids = self.resolve_effect_targets(eff, ctx, default="actor")
            status = eff.get("status") or {"id": eff.get("status_id", "enemy_core_status"), "modifiers": eff.get("modifiers", {}), "stacks": eff.get("stacks", 1), "max_stacks": eff.get("max_stacks", eff.get("stacks", 1))}
            for target_id in target_ids:
                self.apply_effect({"type": "add_status", "target": target_id, "status": status}, ctx)
        elif etype in {"control_immunity", "toughness_lock", "protect_toughness"}:
            key = "toughness_lock" if etype in {"toughness_lock", "protect_toughness"} else "control_immunity"
            self.apply_effect({"type": "add_status", "target": eff.get("target", "actor"), "status": {"id": eff.get("status_id", key), "modifiers": {key: True}}}, ctx)
        elif etype == "add_damage_taken":
            val = self.resolve_numeric_expr(eff.get("amount", eff.get("value", eff.get("damage_taken", 0.0))), ctx, default=0.0)
            self.apply_effect({"type": "add_status", "target": eff.get("target", "actor"), "status": {"id": eff.get("status_id", "damage_taken_status"), "modifiers": {"damage_taken_add": val}, "duration": eff.get("duration")}}, ctx)
        elif etype == "reduce_resistance":
            val = self.resolve_numeric_expr(eff.get("amount", eff.get("value", eff.get("resistance_reduction", 0.0))), ctx, default=0.0)
            element = str(eff.get("element", eff.get("damage_type", "all"))).lower()
            mods = {"damage_taken": {}}
            # Resistance reduction on target is equivalent to attacker res_pen for
            # damage math; store as negative target resistance via a status payload
            # consumed by an immediate target.res patch here to stay simple.
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                old = coerce_float(unit.res.get(element if element != "all" else "all", 0.0))
                unit.res[element if element != "all" else "all"] = old - val
                self.state.log_event("enemy_mechanic", f"{target_id} {element} resistance {old}->{unit.res[element if element != 'all' else 'all']}", {"property": "reduce_resistance", "element": element, "value": val})
        elif etype == "spawn_corresponding_summons":
            allies_for_correspondence = self.state.allies_alive() if coerce_bool(eff.get("per_ally", True), default=True) else []
            count = coerce_int(eff.get("count", len(allies_for_correspondence) if allies_for_correspondence else 1), 1)
            base_id = str(eff.get("unit_id", eff.get("summon_id", "enemy_summon")))
            for idx in range(count):
                uid = f"{base_id}_{idx+1}" if count > 1 else base_id
                if uid in self.state.units:
                    continue
                corresponding_ally = allies_for_correspondence[idx].id if idx < len(allies_for_correspondence) else None
                flags = {"corresponding_summon": True, "summon_monster_id": eff.get("summon_monster_id")}
                if corresponding_ally:
                    flags["corresponding_ally"] = corresponding_ally
                unit_template = deepcopy(eff.get("unit_template") or {}) if isinstance(eff.get("unit_template"), dict) else {}
                unit_raw = {**unit_template}
                unit_raw.setdefault("side", eff.get("side", "enemy"))
                unit_raw.setdefault("hp", eff.get("hp", 1000))
                unit_raw.setdefault("max_hp", eff.get("max_hp", eff.get("hp", 1000)))
                unit_raw.setdefault("speed", eff.get("speed", 100))
                unit_raw.setdefault("level", eff.get("level", 80))
                unit_raw.setdefault("stats", {"atk": eff.get("atk", 1000), "def": eff.get("def", 0)})
                unit_raw.setdefault("tags", ["summoned", "enemy_summon"])
                if "summoned" not in normalize_str_list(unit_raw.get("tags", [])):
                    unit_raw["tags"] = normalize_str_list(unit_raw.get("tags", [])) + ["summoned", "enemy_summon"]
                merged_flags = deepcopy(unit_raw.get("flags", {})) if isinstance(unit_raw.get("flags", {}), dict) else {}
                merged_flags.update(flags)
                unit_raw["flags"] = merged_flags
                self.apply_effect({"type": "summon_unit", "unit_id": uid, "side": eff.get("side", "enemy"), "owner": ctx.get("actor_id"), "unit": unit_raw}, ctx)
        elif etype == "phase_transition_immediate_action":
            target_id = eff.get("target") or ctx.get("actor_id")
            if target_id in self.state.units:
                self.commit_unit_flag(
                    self.state.unit(target_id),
                    "phase_transition_immediate_action",
                    eff.get("action") or eff.get("action_id") or True,
                    reason="effect:phase_transition_immediate_action",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff)},
                )
                self.state.log_event("enemy_mechanic", f"{target_id} phase transition immediate action armed", {"action": self.state.unit(target_id).flags["phase_transition_immediate_action"]})
        elif etype == "hp_based_damage":
            amount_key = eff.get("target_max_hp_pct", eff.get("max_hp_pct", eff.get("ratio", 0.0)))
            ratio = self.resolve_numeric_expr(amount_key, ctx, default=0.0)
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                if target_id in self.state.units:
                    unit = self.state.unit(target_id)
                    self.apply_effect({"type": "damage_unit", "target": target_id, "amount": unit.max_hp * ratio, "element": eff.get("element"), "ignore_shield": eff.get("ignore_shield", False), "ignore_defense": eff.get("ignore_defense", True)}, ctx)
        elif etype == "add_toughness_protection":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                self.apply_effect({"type": "add_status", "target": target_id, "status": {"id": eff.get("status_id", "toughness_protection"), "tags": ["enemy_core_mechanic", "toughness_protection"], "modifiers": {"toughness_lock": True}}}, ctx)
        elif etype == "absorb_remaining_summons":
            contains = str(eff.get("summon_id_contains", "")).lower()
            tag = str(eff.get("summon_tag", "")).lower()
            absorbed = 0
            for unit in list(self.state.units.values()):
                if not unit.alive or unit.side != "enemy":
                    continue
                tag_match = (not tag) or tag in {str(t).lower() for t in unit.tags}
                id_match = (not contains) or contains in str(unit.id).lower()
                if tag_match and id_match and unit.id != ctx.get("actor_id"):
                    self.commit_unit_hp(
                        unit,
                        0.0,
                        reason="effect:absorb_remaining_summons",
                        ctx=ctx,
                        payload={"absorbed_by": ctx.get("actor_id"), "summon_id_contains": contains, "summon_tag": tag},
                    )
                    self.commit_unit_alive(unit, False, reason="effect:absorb_remaining_summons", ctx=ctx, payload={"absorbed_by": ctx.get("actor_id"), "summon_id_contains": contains, "summon_tag": tag})
                    absorbed += 1
                    self.state.log_event("enemy_mechanic", f"{ctx.get('actor_id')} absorbs {unit.id}", {"absorbed_unit": unit.id})
            flag = eff.get("store_count_flag")
            if flag and ctx.get("actor_id") in self.state.units:
                self.commit_unit_flag(self.state.unit(ctx["actor_id"]), str(flag), absorbed, reason="effect:absorb_remaining_summons:store_count_flag", ctx=ctx, payload={"summon_id_contains": contains, "summon_tag": tag})
            self.state.log_event("enemy_mechanic", f"Absorbed {absorbed} enemy summons", {"absorbed_count": absorbed, "summon_id_contains": contains, "summon_tag": tag})
        elif etype == "dispel_status_categories":
            categories = {str(x).lower() for x in normalize_str_list(eff.get("categories", []))}
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                if target_id not in self.state.units:
                    continue
                unit = self.state.unit(target_id)
                removed = []
                for st in list(unit.statuses):
                    st_tags = {str(t).lower() for t in st.tags}
                    if categories and (categories & st_tags or str(st.id).lower() in categories):
                        removed.append(st.id)
                        self.commit_status_remove(
                            unit,
                            st,
                            reason="effect:dispel_status_categories",
                            ctx=ctx,
                            payload={"categories": sorted(categories), "removed_status": st.to_json()},
                        )
                if "weakness_break" in categories or "break" in categories:
                    self.commit_unit_is_broken(unit, False, reason="effect:dispel_status_categories:is_broken", ctx=ctx, payload={"categories": sorted(categories)})
                self.state.log_event("enemy_mechanic", f"{target_id} dispels status categories", {"categories": sorted(categories), "removed": removed})
        elif etype == "reduce_recoverable_hp_cap":
            ratio = self.resolve_numeric_expr(eff.get("ratio", eff.get("amount", eff.get("value", 0.5))), ctx, default=0.5)
            cap_ratio = max(0.0, min(1.0, 1.0 - ratio))
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                if target_id in self.state.units:
                    unit = self.state.unit(target_id)
                    old = coerce_float(unit.flags.get("max_restorable_hp_ratio", 1.0), 1.0)
                    self.commit_unit_flag(unit, "max_restorable_hp_ratio", min(old, cap_ratio), reason="effect:reduce_recoverable_hp_cap", ctx=ctx, payload={"ratio": ratio, "cap_ratio": cap_ratio})
                    self.state.log_event("enemy_mechanic", f"{target_id} max restorable HP ratio {old}->{unit.flags['max_restorable_hp_ratio']}", {"ratio": ratio, "cap_ratio": cap_ratio})
        elif etype == "restore_recoverable_hp_cap_by_damaging_corresponding_summon":
            # Runtime restoration is handled in handle_enemy_on_hit_mechanics when
            # a corresponding summon carries flags.corresponding_ally.  This effect
            # arms the summon/template path without tying it to a concrete monster id.
            self.state.log_event("enemy_mechanic", "restore_recoverable_hp_cap_by_damaging_corresponding_summon armed", {"effect": eff})
        elif etype in {
            "damage_reduction", "reduce_stack_on_attacked", "on_stack_reaches_zero",
            "charge", "charging", "buff_self", "apply_state_to_corresponding_character",
            "summon_or_attached_unit", "boss_buff", "self_state_change", "self_state_transition",
            "deal_damage_to_self", "grant_energy_to_breaking_player_unit", "mark_armor_broken",
            "while_broken_extra_damage_on_hit", "restore_to_max_at_self_turn_end",
            "linked_to_conquered_state", "protect_toughness", "cleanse_control_and_weakness_break_on_apply",
            "mark_summon_armor_intact", "increases_fury_descends_damage_if_intact", "control_immunity",
            "toughness_lock", "replace_regular_action_pattern", "immediate_action_on_hit_by_element",
            "count_attacks_taken", "add_damage_taken", "reduce_resistance", "spawn_corresponding_summons",
            "enemy_turns",
            "dispel_debuff",
        }:
            self.state.log_event("effect_noop", f"Model-pack descriptive effect recorded as no-op: {etype}", {"effect": eff})
        else:
            raise SimulatorError(f"Unsupported effect type: {etype}")
