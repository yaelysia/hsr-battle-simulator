from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from hsr_engine.core_rules import EPS, coerce_bool, coerce_float, coerce_int, normalize_str_list
from hsr_engine.settlement import ModifierLedger, ModifierTerm


def _modifier_scope(source_type: str) -> str:
    if source_type.startswith("actor."):
        return "actor"
    if source_type.startswith("target."):
        return "target"
    if source_type == "packet":
        return "packet"
    return source_type or "unknown"


def _legacy_modifier_term(
    source_type: str,
    source_id: str,
    key: str,
    value: Any,
    *,
    stacks: int = 1,
    applied_value: Any | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    value_f = coerce_float(value, 0.0)
    applied = value_f * max(1, coerce_int(stacks, 1)) if applied_value is None else coerce_float(applied_value, 0.0)
    rec = {
        "source_type": source_type,
        "source_id": source_id,
        "key": key,
        "value": round(value_f, 9),
        "stacks": stacks,
        "applied_value": round(applied, 9),
    }
    if note:
        rec["note"] = note
    return rec


class DamageResolver:
    """Direct damage resolver for the parallel combat core.

    The first migration stage still queries legacy simulator rule helpers through
    `rules`, but the direct-damage formula ledger is built here.
    """

    def __init__(self, rules: Any) -> None:
        self.rules = rules

    def resolve_break_packet(self, packet: dict[str, Any], actor: Any, target: Any, action: dict[str, Any], events: dict[str, Any]) -> dict[str, Any]:
        return self.rules._resolve_break_damage_packet_legacy(packet, actor, target, action, events)

    def resolve_super_break_packet(self, packet: dict[str, Any], actor: Any, target: Any, action: dict[str, Any], events: dict[str, Any]) -> dict[str, Any]:
        return self.rules._resolve_super_break_damage_packet_legacy(packet, actor, target, action, events)

    def resolve_dot_tick(self, unit: Any, ctx: dict[str, Any]) -> None:
        return self.rules._resolve_dot_tick_legacy(unit, ctx)

    def resolve_packet(
        self,
        packet: dict[str, Any],
        actor: Any,
        target: Any,
        action: dict[str, Any],
        events: dict[str, Any],
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        packet = self.rules.normalize_damage_packet_schema(packet)
        if "multiplier" not in packet or coerce_float(packet.get("multiplier", 0.0)) == 0.0:
            ref_mult = self.rules.resolve_packet_multiplier_reference(packet, actor)
            if ref_mult is not None:
                packet["multiplier"] = ref_mult
        base_ctx = dict(ctx or {})
        dmg_ctx_for_element = {
            **base_ctx,
            "action": action,
            "packet": packet,
            "actor_id": actor.id,
            "actor": actor,
            "owner_id": actor.flags.get("owner_id"),
            "target_id": target.id,
            "target": target,
        }
        element = self.rules.resolve_dynamic_element(packet.get("element", "none"), dmg_ctx_for_element)
        packet["element"] = element
        damage_type = str(packet.get("damage_type", packet.get("type", "direct_damage")) or "direct_damage").lower()
        if damage_type in {"break", "break_damage", "weakness_break"}:
            return self.resolve_break_packet(packet, actor, target, action, events)
        if damage_type in {"super_break", "superbreak", "super_break_damage"}:
            return self.resolve_super_break_packet(packet, actor, target, action, events)

        scaling_stat = packet.get("scaling_stat", "atk")
        multiplier = coerce_float(packet.get("multiplier", 0.0))
        flat_damage = coerce_float(packet.get("flat_damage", 0.0))
        dmg_ctx = {
            **base_ctx,
            "action": action,
            "packet": packet,
            "actor_id": actor.id,
            "actor": actor,
            "owner_id": actor.flags.get("owner_id"),
            "target_id": target.id,
            "target": target,
        }
        scaling_value = self.rules.contextual_stat(actor, scaling_stat, dmg_ctx)
        base = scaling_value * multiplier + flat_damage
        crit_info = self.rules.resolve_crit(packet, actor, action, events, dmg_ctx)
        dmg_bonus = self.rules.get_dmg_bonus_multiplier(actor, packet, action, dmg_ctx)
        defense = self.rules.get_def_multiplier(actor, target, packet, dmg_ctx)
        res = self.rules.get_res_multiplier(actor, target, element, dmg_ctx)
        taken = self.rules.get_damage_taken_multiplier(target, packet, action, dmg_ctx)
        reduction = self.rules.get_universal_reduction_multiplier(target, packet, action, dmg_ctx)
        toughness = self.rules.get_toughness_state_multiplier(target, packet)
        other = coerce_float(packet.get("other_multiplier", 1.0))
        multipliers = {
            "dmg_bonus": dmg_bonus,
            "defense": defense,
            "res": res,
            "damage_taken": taken,
            "universal_reduction": reduction,
            "toughness_state": toughness,
            "other": other,
        }
        final = base * crit_info["multiplier"] * dmg_bonus * defense * res * taken * reduction * toughness * other
        final = max(0.0, final)
        toughness_reduction = coerce_float(packet.get("toughness_reduction", 0.0))
        formula_ledger, modifier_ledger = self.collect_direct_damage_ledgers(
            actor,
            target,
            packet,
            action,
            dmg_ctx,
            scaling_stat=str(scaling_stat),
            scaling_value=scaling_value,
            base_damage=base,
            crit_info=crit_info,
            multipliers=multipliers,
            final_damage=final,
        )
        return {
            "actor_id": actor.id,
            "target_id": target.id,
            "packet_id": packet.get("id"),
            "element": element,
            "base_damage": base,
            "crit": crit_info,
            "multipliers": multipliers,
            "formula_ledger": formula_ledger,
            "modifier_ledger": modifier_ledger.to_dict(),
            "damage": final,
            "toughness_reduction": toughness_reduction,
            "target_defeated": False,
        }

    def collect_direct_damage_ledgers(
        self,
        actor: Any,
        target: Any,
        packet: dict[str, Any],
        action: dict[str, Any],
        ctx: dict[str, Any],
        *,
        scaling_stat: str,
        scaling_value: float,
        base_damage: float,
        crit_info: dict[str, Any],
        multipliers: dict[str, float],
        final_damage: float,
    ) -> tuple[dict[str, Any], ModifierLedger]:
        tags = set(normalize_str_list(action.get("tags", []))) | set(normalize_str_list(packet.get("tags", [])))
        element = str(packet.get("element", "none") or "none")
        formula_ledger: dict[str, Any] = {
            "formula_type": "direct_damage",
            "actor_id": actor.id,
            "target_id": target.id,
            "action_id": action.get("id"),
            "packet_id": packet.get("id"),
            "tags": sorted(tags),
            "scaling": {
                "stat": scaling_stat,
                "scaling_value": round(coerce_float(scaling_value, 0.0), 9),
                "multiplier": round(coerce_float(packet.get("multiplier", 0.0), 0.0), 9),
                "flat_damage": round(coerce_float(packet.get("flat_damage", 0.0), 0.0), 9),
                "base_damage": round(coerce_float(base_damage, 0.0), 9),
            },
            "crit": deepcopy(crit_info),
            "buckets": {},
            "formula": "base * crit * dmg_bonus * defense * res * damage_taken * universal_reduction * toughness_state * other",
            "final_damage": round(final_damage, 9),
        }
        modifier_ledger = ModifierLedger(
            formula_type="direct_damage",
            actor_id=actor.id,
            target_id=target.id,
            action_id=str(action.get("id") or ""),
            packet_id=str(packet.get("id") or ""),
            formula=formula_ledger["formula"],
            final_damage=round(final_damage, 9),
            scaling=deepcopy(formula_ledger["scaling"]),
            crit=deepcopy(crit_info),
        )

        def add_applied(
            bucket: str,
            legacy_terms: list[dict[str, Any]],
            source_type: str,
            source_id: str,
            key: str,
            value: Any,
            *,
            stacks: int = 1,
            applied_value: Any | None = None,
            note: str | None = None,
            raw_path: str = "",
        ) -> None:
            legacy = _legacy_modifier_term(
                source_type,
                source_id,
                key,
                value,
                stacks=stacks,
                applied_value=applied_value,
                note=note,
            )
            legacy_terms.append(legacy)
            modifier_ledger.terms.append(
                ModifierTerm(
                    bucket=bucket,
                    term_index=len(legacy_terms) - 1,
                    source_type=source_type,
                    source_id=source_id,
                    key=key,
                    scope=_modifier_scope(source_type),
                    condition=note or "",
                    value=legacy["value"],
                    stacks=stacks,
                    applied_value=legacy["applied_value"],
                    applied=True,
                    applied_reason="included_in_formula_bucket",
                    raw_path=raw_path or f"formula_ledger.buckets.{bucket}.terms[{len(legacy_terms) - 1}]",
                    raw=deepcopy(legacy),
                )
            )

        def add_skipped(
            bucket: str,
            source_type: str,
            source_id: str,
            key: str,
            value: Any,
            *,
            stacks: int = 1,
            condition: str = "",
            skipped_reason: str,
            raw_path: str = "",
        ) -> None:
            modifier_ledger.skipped_terms.append(
                ModifierTerm(
                    bucket=bucket,
                    term_index=len(modifier_ledger.skipped_terms),
                    source_type=source_type,
                    source_id=source_id,
                    key=key,
                    scope=_modifier_scope(source_type),
                    condition=condition,
                    value=round(coerce_float(value, 0.0), 9),
                    stacks=stacks,
                    applied_value=0.0,
                    applied=False,
                    applied_reason="",
                    skipped_reason=skipped_reason,
                    raw_path=raw_path,
                    raw={"value": value, "stacks": stacks},
                )
            )

        dmg_terms: list[dict[str, Any]] = []
        all_bonus = coerce_float(actor.stats.get("all_dmg_bonus", 0.0))
        if abs(all_bonus) > EPS:
            add_applied("dmg_bonus", dmg_terms, "actor.stats", actor.id, "all_dmg_bonus", all_bonus, stacks=1)
        pkt_bonus = coerce_float(packet.get("dmg_bonus_add", 0.0))
        if abs(pkt_bonus) > EPS:
            add_applied("dmg_bonus", dmg_terms, "packet", str(packet.get("id")), "dmg_bonus_add", pkt_bonus, stacks=1)
        pkt_mult_alias = coerce_float(packet.get("dmg_bonus_multiplier", 0.0))
        if abs(pkt_mult_alias) > EPS:
            add_applied("dmg_bonus", dmg_terms, "packet", str(packet.get("id")), "dmg_bonus_multiplier", pkt_mult_alias, stacks=1)
        elem_bonus = coerce_float(actor.stats.get(f"{element}_dmg_bonus", 0.0)) if element else 0.0
        if abs(elem_bonus) > EPS:
            add_applied("dmg_bonus", dmg_terms, "actor.stats", actor.id, f"{element}_dmg_bonus", elem_bonus, stacks=1)
        for st, mods in self.rules.applicable_status_modifiers(actor, ctx or {"action": action, "packet": packet}):
            val = coerce_float(mods.get("dmg_bonus_add", 0.0))
            if abs(val) > EPS:
                add_applied("dmg_bonus", dmg_terms, "actor.status", st.id, "dmg_bonus_add", val, stacks=st.stacks, note=f"source={st.source_id}")
            if st.stacks > 0 and "next_attack_dmg_bonus_add" in mods:
                val2 = coerce_float(mods.get("next_attack_dmg_bonus_add", 0.0))
                if abs(val2) > EPS:
                    add_applied("dmg_bonus", dmg_terms, "actor.status", st.id, "next_attack_dmg_bonus_add", val2, stacks=1, note=f"source={st.source_id}; non_per_stack")
            sub = mods.get("dmg_bonus", {})
            if isinstance(sub, dict):
                for key, val3 in sub.items():
                    key_s = str(key)
                    condition = f"matches element={element} or action/packet tags"
                    if key_s == element or key_s in tags or key_s == "all":
                        val3f = coerce_float(val3, 0.0)
                        if abs(val3f) > EPS:
                            add_applied("dmg_bonus", dmg_terms, "actor.status", st.id, f"dmg_bonus.{key_s}", val3f, stacks=st.stacks, note=f"source={st.source_id}", raw_path=f"status.{st.id}.modifiers.dmg_bonus.{key_s}")
                        else:
                            add_skipped("dmg_bonus", "actor.status", st.id, f"dmg_bonus.{key_s}", val3, stacks=st.stacks, condition=condition, skipped_reason="zero_value", raw_path=f"status.{st.id}.modifiers.dmg_bonus.{key_s}")
                    else:
                        add_skipped("dmg_bonus", "actor.status", st.id, f"dmg_bonus.{key_s}", val3, stacks=st.stacks, condition=condition, skipped_reason="condition_not_matched", raw_path=f"status.{st.id}.modifiers.dmg_bonus.{key_s}")
        formula_ledger["buckets"]["dmg_bonus"] = {"multiplier": round(coerce_float(multipliers.get("dmg_bonus", 1.0)), 9), "terms": dmg_terms}

        def_terms: list[dict[str, Any]] = []
        raw_def = target.get_stat("defense") or target.get_stat("def")
        def_ignore = coerce_float(packet.get("def_ignore", 0.0))
        if abs(def_ignore) > EPS:
            add_applied("defense", def_terms, "packet", str(packet.get("id")), "def_ignore", def_ignore, stacks=1)
        for st, mods in self.rules.applicable_status_modifiers(target, ctx or {"packet": packet}):
            val = coerce_float(mods.get("def_reduction", 0.0))
            if abs(val) > EPS:
                add_applied("defense", def_terms, "target.status", st.id, "def_reduction", val, stacks=st.stacks, note=f"source={st.source_id}")
        total_def_reduction = sum(coerce_float(t.get("applied_value", 0.0)) for t in def_terms if t.get("key") == "def_reduction") + def_ignore
        effective_def = 0.0 if coerce_bool(packet.get("ignore_defense_multiplier", False), default=False) else max(0.0, raw_def * (1 - total_def_reduction))
        formula_ledger["buckets"]["defense"] = {
            "multiplier": round(coerce_float(multipliers.get("defense", 1.0)), 9),
            "raw_target_def": round(coerce_float(raw_def, 0.0), 9),
            "effective_target_def": round(coerce_float(effective_def, 0.0), 9),
            "ignore_defense_multiplier": coerce_bool(packet.get("ignore_defense_multiplier", False), default=False),
            "terms": def_terms,
        }

        res_terms: list[dict[str, Any]] = []
        base_res = coerce_float(target.res.get(element, target.res.get("all", 0.0)))
        for st, mods in self.rules.applicable_status_modifiers(target, ctx or {}):
            delta = mods.get("resistance_delta", {}) if isinstance(mods.get("resistance_delta", {}), dict) else {}
            selected_resistance_key = element if element in delta else "all" if "all" in delta else None
            for key, value in delta.items():
                key_s = str(key)
                condition = f"selected resistance key for element={element}"
                if key_s == selected_resistance_key:
                    val = coerce_float(value, 0.0)
                    if abs(val) > EPS:
                        add_applied("res", res_terms, "target.status", st.id, f"resistance_delta.{key_s}", val, stacks=st.stacks, note=f"source={st.source_id}", raw_path=f"status.{st.id}.modifiers.resistance_delta.{key_s}")
                else:
                    add_skipped("res", "target.status", st.id, f"resistance_delta.{key_s}", value, stacks=st.stacks, condition=condition, skipped_reason="condition_not_matched", raw_path=f"status.{st.id}.modifiers.resistance_delta.{key_s}")
        actor_stat_pen = coerce_float(actor.stats.get(f"{element}_res_pen", actor.stats.get("all_res_pen", 0.0)))
        if abs(actor_stat_pen) > EPS:
            add_applied("res", res_terms, "actor.stats", actor.id, f"{element}_or_all_res_pen", actor_stat_pen, stacks=1)
        for st, mods in self.rules.applicable_status_modifiers(actor, ctx or {}):
            if isinstance(mods.get("res_pen"), dict):
                for key, value in mods.get("res_pen", {}).items():
                    key_s = str(key)
                    if key_s == element:
                        val = coerce_float(value, 0.0)
                        if abs(val) > EPS:
                            add_applied("res", res_terms, "actor.status", st.id, f"res_pen.{key_s}", val, stacks=1, note=f"source={st.source_id}", raw_path=f"status.{st.id}.modifiers.res_pen.{key_s}")
                    else:
                        add_skipped("res", "actor.status", st.id, f"res_pen.{key_s}", value, stacks=1, condition=f"matches element={element}", skipped_reason="condition_not_matched", raw_path=f"status.{st.id}.modifiers.res_pen.{key_s}")
            val2 = coerce_float(mods.get("all_res_pen", 0.0))
            if abs(val2) > EPS:
                add_applied("res", res_terms, "actor.status", st.id, "all_res_pen", val2, stacks=1, note=f"source={st.source_id}")
        target_res_delta = sum(coerce_float(t.get("applied_value", 0.0)) for t in res_terms if t.get("source_type") == "target.status")
        res_pen_total = sum(coerce_float(t.get("applied_value", 0.0)) for t in res_terms if t.get("source_type") in {"actor.stats", "actor.status"})
        formula_ledger["buckets"]["res"] = {
            "multiplier": round(coerce_float(multipliers.get("res", 1.0)), 9),
            "base_target_res": round(base_res, 9),
            "target_res_after_delta": round(base_res + target_res_delta, 9),
            "res_pen_total": round(res_pen_total, 9),
            "terms": res_terms,
        }

        taken_terms: list[dict[str, Any]] = []
        base_taken = coerce_float(target.stats.get("damage_taken", 0.0))
        if abs(base_taken) > EPS:
            add_applied("damage_taken", taken_terms, "target.stats", target.id, "damage_taken", base_taken, stacks=1)
        for st, mods in self.rules.applicable_status_modifiers(target, ctx or {"action": action, "packet": packet}):
            val = coerce_float(mods.get("damage_taken_add", 0.0))
            if abs(val) > EPS:
                add_applied("damage_taken", taken_terms, "target.status", st.id, "damage_taken_add", val, stacks=st.stacks, note=f"source={st.source_id}")
            sub = mods.get("damage_taken", {})
            if isinstance(sub, dict):
                for key, val2 in sub.items():
                    key_s = str(key)
                    condition = f"matches element={element} or action/packet tags"
                    if key_s == element or key_s in tags or key_s == "all":
                        val2f = coerce_float(val2, 0.0)
                        if abs(val2f) > EPS:
                            add_applied("damage_taken", taken_terms, "target.status", st.id, f"damage_taken.{key_s}", val2f, stacks=st.stacks, note=f"source={st.source_id}", raw_path=f"status.{st.id}.modifiers.damage_taken.{key_s}")
                    else:
                        add_skipped("damage_taken", "target.status", st.id, f"damage_taken.{key_s}", val2, stacks=st.stacks, condition=condition, skipped_reason="condition_not_matched", raw_path=f"status.{st.id}.modifiers.damage_taken.{key_s}")
        formula_ledger["buckets"]["damage_taken"] = {"multiplier": round(coerce_float(multipliers.get("damage_taken", 1.0)), 9), "terms": taken_terms}

        reduction_terms: list[dict[str, Any]] = []
        stat_reduction = coerce_float(target.stats.get("damage_reduction", 0.0)) if "damage_reduction" in target.stats else 0.0
        if abs(stat_reduction) > EPS:
            add_applied("universal_reduction", reduction_terms, "target.stats", target.id, "damage_reduction", stat_reduction, stacks=1)
        for st, mods in self.rules.applicable_status_modifiers(target, ctx or {"action": action, "packet": packet}):
            if "damage_reduction" in mods:
                if isinstance(mods.get("titanic_corpus"), dict):
                    val = coerce_float(mods["damage_reduction"], 0.0)
                    if abs(val) > EPS:
                        add_applied("universal_reduction", reduction_terms, "target.status", st.id, "damage_reduction", val, stacks=1, note=f"source={st.source_id}; non_per_stack")
                else:
                    val = coerce_float(mods["damage_reduction"], 0.0)
                    if abs(val) > EPS:
                        add_applied("universal_reduction", reduction_terms, "target.status", st.id, "damage_reduction", val, stacks=st.stacks, note=f"source={st.source_id}")
            armor = mods.get("armor_layers") if isinstance(mods.get("armor_layers"), dict) else None
            if armor:
                fixed = armor.get("damage_reduction_while_active", None)
                layers = st.stacks if st.stacks is not None else coerce_int(armor.get("layers", 0), 0)
                if fixed is not None and layers > 0:
                    val = min(0.9, max(0.0, coerce_float(fixed)))
                    add_applied("universal_reduction", reduction_terms, "target.status", st.id, "armor_layers.damage_reduction_while_active", val, stacks=1, note=f"source={st.source_id}; layers={layers}")
                else:
                    per = coerce_float(armor.get("damage_reduction_per_layer", 0.0))
                    if abs(per) > EPS:
                        add_applied("universal_reduction", reduction_terms, "target.status", st.id, "armor_layers.damage_reduction_per_layer", per, stacks=layers, note=f"source={st.source_id}")
        formula_ledger["buckets"]["universal_reduction"] = {"multiplier": round(coerce_float(multipliers.get("universal_reduction", 1.0)), 9), "terms": reduction_terms}

        formula_ledger["buckets"]["toughness_state"] = {
            "multiplier": round(coerce_float(multipliers.get("toughness_state", 1.0)), 9),
            "target_toughness_before_packet": None if target.toughness is None else round(target.toughness, 9),
            "target_is_broken_before_packet": target.is_broken,
            "ignore_toughness_state_multiplier": coerce_bool(packet.get("ignore_toughness_state_multiplier", False), default=False),
        }
        formula_ledger["buckets"]["other"] = {
            "multiplier": round(coerce_float(multipliers.get("other", 1.0)), 9),
            "source": "packet.other_multiplier",
        }
        modifier_ledger.bucket_multipliers = {
            key: bucket.get("multiplier")
            for key, bucket in formula_ledger["buckets"].items()
            if isinstance(bucket, dict) and "multiplier" in bucket
        }
        return formula_ledger, modifier_ledger


@dataclass
class DamageApplication:
    target: Any
    actor: Any
    was_alive_before_damage: bool
    old_hp: float
    old_shield: float


class DamageApplier:
    """Applies direct damage HP/shield effects through the legacy mutator adapter."""

    def __init__(self, mutator: Any) -> None:
        self.mutator = mutator

    def apply_hp_loss(
        self,
        target: Any,
        amount: float,
        ctx: dict[str, Any],
        label: str = "hp_loss",
        ignore_shield: bool = False,
        carry_over_hp_bar_damage: Any | None = None,
    ) -> dict[str, Any]:
        return self.mutator._apply_hp_loss_legacy(
            target,
            amount,
            ctx,
            label=label,
            ignore_shield=ignore_shield,
            carry_over_hp_bar_damage=carry_over_hp_bar_damage,
        )

    def apply_direct_damage_result(self, result: dict[str, Any], ctx: dict[str, Any]) -> DamageApplication:
        target = self.mutator.state.unit(result["target_id"])
        actor = self.mutator.state.units.get(str(result.get("actor_id"))) if result.get("actor_id") is not None else None
        was_alive_before_damage = bool(target.alive)
        old_hp = target.hp
        old_shield = target.shield
        shield_absorbed = 0.0
        incoming = max(0.0, result["damage"])
        if not was_alive_before_damage:
            result["target_already_defeated_before_packet"] = True

        if was_alive_before_damage and target.shield > EPS and not coerce_bool(ctx.get("packet", {}).get("ignore_shield", False), default=False):
            absorbed = min(target.shield, incoming)
            self.mutator.commit_unit_shield(
                target,
                target.shield - absorbed,
                reason="damage:shield_absorb",
                ctx=ctx,
                payload={"absorbed": absorbed, "incoming_before": incoming},
            )
            incoming -= absorbed
            shield_absorbed = absorbed
            self.mutator.state.log_event(
                "shield",
                f"{target.id} shield absorbs {absorbed:.3f}",
                {"old_shield": old_shield, "new_shield": target.shield, "remaining_damage": incoming},
            )
            self.mutator._settle(
                ctx,
                "shield",
                unit_id=target.id,
                delta=-absorbed,
                old_value=old_shield,
                new_value=target.shield,
                reason=f"伤害吸收: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                record_state_change=False,
            )

        packet = ctx.get("packet", {})
        carry = packet.get("carry_over_hp_bar_damage", packet.get("carry_over_damage", None))
        if was_alive_before_damage:
            bar_result = self.mutator._apply_hp_damage_to_bars(target, incoming, carry, "damage", ctx=ctx)
        else:
            bar_result = {
                "hp_bar_depleted": False,
                "target_defeated": False,
                "bars_depleted": 0,
                "old_hp": old_hp,
                "new_hp": target.hp,
                "hp_bars_remaining": target.hp_bars_remaining,
                "depleted_bar_events": [],
                "phase_damage_locked_until_action_end": False,
            }
        result["hp_bar_depleted"] = bar_result["hp_bar_depleted"]
        result["target_defeated"] = bar_result["target_defeated"]
        result["bars_depleted"] = bar_result["bars_depleted"]
        result["hp_bars_remaining"] = target.hp_bars_remaining
        result["depleted_bar_events"] = bar_result.get("depleted_bar_events", [])
        result["phase_damage_locked_until_action_end"] = bar_result.get("phase_damage_locked_until_action_end", False)
        hp_loss = coerce_float(bar_result.get("hp_loss", 0.0), 0.0)
        damage_applied = max(0.0, shield_absorbed + hp_loss)
        final_damage = max(0.0, coerce_float(result.get("damage", 0.0), 0.0))
        overkill = max(0.0, final_damage - damage_applied)
        result["shield_absorbed"] = shield_absorbed
        result["hp_loss"] = hp_loss
        result["damage_applied"] = damage_applied
        result["applied_damage"] = damage_applied
        result["overkill"] = overkill
        result["is_overkill"] = overkill > EPS
        if bar_result.get("bars_depleted") and target.alive and target.hp_model_type == "phase_hp":
            old_phase = coerce_int(target.flags.get("current_phase", target.flags.get("monster_phase", 1)), 1)
            new_phase = min(target.hp_bars_total, old_phase + coerce_int(bar_result.get("bars_depleted", 1), 1))
            self.mutator.commit_unit_flag(
                target,
                "current_phase",
                new_phase,
                reason="damage:phase_transition:current_phase",
                ctx=ctx,
                payload={"old_phase": old_phase, "bars_depleted": bar_result.get("bars_depleted")},
            )
            self.mutator.commit_unit_flag(
                target,
                "monster_phase",
                new_phase,
                reason="damage:phase_transition:monster_phase",
                ctx=ctx,
                payload={"old_phase": old_phase, "bars_depleted": bar_result.get("bars_depleted")},
            )
            self.mutator.state.log_event(
                "phase_transition",
                f"{target.id} phase {old_phase}->{new_phase}",
                {"unit": target.id, "old_phase": old_phase, "new_phase": new_phase, "bars_depleted": bar_result.get("bars_depleted")},
            )

        self.mutator.state.log_event(
            "damage",
            f"{result['actor_id']} deals {result['damage']:.3f} {result['element']} damage to {target.id}",
            {"old_hp": old_hp, "new_hp": target.hp, "old_shield": old_shield, "new_shield": target.shield, **result},
        )
        hp_delta = target.hp - old_hp
        if abs(hp_delta) > EPS and was_alive_before_damage:
            self.mutator._settle(
                ctx,
                "hp",
                unit_id=target.id,
                delta=hp_delta,
                old_value=old_hp,
                new_value=target.hp,
                max_hp=target.max_hp,
                reason=f"受到伤害: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                record_state_change=False,
            )
        return DamageApplication(
            target=target,
            actor=actor,
            was_alive_before_damage=was_alive_before_damage,
            old_hp=old_hp,
            old_shield=old_shield,
        )
