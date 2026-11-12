"""Castorice (avatar:1407) content processors: character card + Netherwing sub-card.

Scope: behaviors the generic compiled path does not express for this content
only. Verified gaps and their evidence are recorded per behavior below; the
generic path's working behaviors (Newbud accumulation/gate, ultimate cost,
CreateServant spawn, compiled dragon damage graphs, HP-lock overflow) are NOT
reimplemented here (minimal intervention, M1-3 design §5).

Sources: fixed TBGD 14c1d18f91a8101d610e6c523447a7517de3fae1,
Config/ConfigAbility/Avatar/Avatar_Castorice_00_Ability.json and
Config/ConfigAbility/Servant/Servant_CastoriceServant_00_Ability.json;
adopted guide references are cited per behavior where used.
"""
from __future__ import annotations

from ..core.content_hooks import (
    ActionHookContext,
    AvailabilityContext,
    ContentProcessorBase,
    EventHookContext,
    EventSubscription,
    HookResult,
)
from ..core.model import BattleState
from ..systems.damage import DamagePacket, DamageSourceFrame
from ..systems.dynamic_values import servant_skill_param_binding_source
from ..systems.toughness import ToughnessPacket

_CASTORICE_ULTIMATE = "avatar_skill:140703"
_NETHERWING_REF = "servant:11407"


def _dragon_instances(state: BattleState, owner_id: str) -> tuple[str, ...]:
    return tuple(
        unit_id for unit_id, unit in sorted(state.units.items())
        if unit.flags.get("owner_id") == owner_id
        and str(unit.flags.get("servant_ref") or unit.template_id) == _NETHERWING_REF
    )


class CastoriceProcessor(ContentProcessorBase):
    """Castorice character-card processor.

    Behaviors (v0.1.0):
    1. Re-creation cleanup: the ultimate's CreateServant source node is
       unconditional (Avatar_Castorice_00_Skill03_Phase02, fixed TBGD
       14c1d18f...), i.e. the game re-creates Netherwing after it departed.
       The generic replacement-policy discovery requires an alive-only
       guard shape this source does not carry, so plan_spawn_servant blocks
       on defeated instances (servant_replacement_policy_missing). This
       hook removes the departed instance before the compiled CreateServant
       runs (takeover=False); the compiled graph keeps owning the spawn.
    """

    content_id = "avatar:1407"
    version = "0.3.0"

    def claims_action(self, state: BattleState, action_id: str, action_level: int) -> bool:
        if action_id != _CASTORICE_ULTIMATE:
            return False
        for unit_id, unit in sorted(state.units.items()):
            if unit.template_id != self.content_id or unit.lifecycle_status == "removed":
                continue
            if any(
                state.units[dragon_id].lifecycle_status == "defeated"
                for dragon_id in _dragon_instances(state, unit_id)
            ):
                return True
        return False

    def execute_action(self, ctx: ActionHookContext) -> HookResult:
        owner_id = ctx.command.actor_id
        departed = tuple(
            dragon_id for dragon_id in _dragon_instances(ctx.state, owner_id)
            if ctx.state.units[dragon_id].lifecycle_status == "defeated"
        )
        if not departed:
            return ctx.services.block("castorice_recreate_no_departed_instance")
        for dragon_id in departed:
            ctx.services.remove_summon(
                dragon_id,
                "castorice_recreate_departed_netherwing",
                source_trace={
                    "rule": "Avatar_Castorice_00_Skill03_Phase02 CreateServant (unconditional)",
                    "tbgd_commit": "14c1d18f91a8101d610e6c523447a7517de3fae1",
                    "processor": f"{self.content_id}:{self.version}",
                },
            )
        return ctx.services.finish(takeover=False)

    def subscriptions(self) -> tuple[EventSubscription, ...]:
        return (
            EventSubscription(("summon.spawned", "summon.removed", "unit.defeated"), scope="owned_units"),
        )

    def on_event(self, ctx: EventHookContext) -> HookResult:
        # Lifecycle observation only in v0.1.0; state changes for the dragon
        # sub-card belong to CastoriceServantProcessor.
        return ctx.services.finish()


class CastoriceServantProcessor(ContentProcessorBase):
    """Netherwing (servant:11407) sub-card processor.

    Behaviors (v0.2.0):
    1. Breath (Skill02/21/22 = servant_skill:1140702/1140710/1140711) H1
       takeover. The compiled graphs are not admittable on the generic path
       (effect_coverage_status:unsupported:UseSkillOneMore,
       condition_not_executable:ByAnd, scaling_ratio_not_runtime_bound;
       probe v3 dragon_decision dump, /tmp/m1_3_dragon_probe.json). The
       breath loop opcode UseSkillOneMore has no second v1 consumer, so the
       processor owns these actions (frozen generic path, M1-3).

       Settlement (all via L1 DamageSystem, no second formula):
       - HP cost: LoseHP node, Servant_CastoriceServant_Skill02_Phase02
         (fixed TBGD 14c1d18f...): DamageValue = MaxHP × Skill02 param #0
         (0.25), Floor=1. Implemented as an hp_loss packet on the dragon.
       - Damage: DamageByAttackProperty node, same phase: FormulaType
         BySummonerMaxHP, Quantum, AttackType Servant, DamagePercentage =
         Skill02 param #1 (0.12 at Lv1 / 0.336 at Lv10). Implemented as
         direct packets with scaling_basis attacker_summoner max_hp on the
         generically resolved targets.
       - Multi-cast loop (UseSkillOneMore) and BP-level multiplier stacking
         (params #2/#3) are NOT yet implemented; v0.2.0 is a single cast
         per turn. Tracked for v0.3.0 (queue insertion proposal to lead).
    """

    content_id = "servant:11407"
    version = "0.4.0"

    _BREATH_ACTIONS = frozenset({
        "servant_skill:1140702", "servant_skill:1140710", "servant_skill:1140711",
    })

    def claims_action(self, state: BattleState, action_id: str, action_level: int) -> bool:
        return action_id in self._BREATH_ACTIONS

    def _primary_damage_hash(self, ctx: ActionHookContext) -> str | None:
        """Formal primary damage dynamic hash of this action's attack data.

        Read from the compiled DamageByAttackProperty effect payload
        (AttackProperty.DamagePercentage.PostfixExpr.DynamicHashes[0]); the
        servant config ReadInfo behind each hash decides which skill
        parameter it binds to (auxiliary Skill21/22 bind Skill02 param #2).
        """
        rules = ctx.services.rules
        for task in rules.ability_tasks_for_action(ctx.command.action_id, ctx.command.action_level):
            if task.opcode != "DamageByAttackProperty":
                continue
            effect = rules.effect(task.effect_id)
            if effect is None:
                continue
            attack = (effect.payload or {}).get("AttackProperty") or {}
            percentage = attack.get("DamagePercentage") or {}
            postfix = percentage.get("PostfixExpr") or {}
            hashes = postfix.get("DynamicHashes") or ()
            if hashes:
                return str(hashes[0])
        return None

    def _resolve_damage_ratio(self, ctx: ActionHookContext, binding_source) -> float | None:
        # Formal skill-parameter binding: the action's damage hash resolved
        # through the servant config ReadInfo chain (L1 binding source), so
        # auxiliary actions inherit the main skill parameter by formal
        # binding, never by ParamList position.
        damage_hash = self._primary_damage_hash(ctx)
        if damage_hash is not None and binding_source is not None:
            # by_hash maps hash -> entry keys; entries holds the typed rows.
            entries = binding_source.get("entries") or {}
            for key in (binding_source.get("by_hash") or {}).get(damage_hash) or ():
                entry = entries.get(key)
                if not isinstance(entry, dict):
                    continue
                if entry.get("owner_id") not in (None, ctx.command.actor_id):
                    continue
                value = entry.get("value")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
        # Main breath action carries its own damage parameter formally.
        params = ctx.action_definition.param_list
        if len(params) >= 2:
            try:
                return float(params[1]["Value"])
            except (TypeError, ValueError, KeyError):
                return None
        return None

    def execute_action(self, ctx: ActionHookContext) -> HookResult:
        dragon_id = ctx.command.actor_id
        dragon = ctx.state.units.get(dragon_id)
        if dragon is None or dragon.lifecycle_status != "active":
            return ctx.services.block("castorice_breath_dragon_not_active")
        params = ctx.action_definition.param_list
        if not params:
            return ctx.services.block("castorice_breath_params_missing")
        try:
            cost_ratio = float(params[0]["Value"])
        except (TypeError, ValueError, KeyError):
            return ctx.services.block("castorice_breath_params_invalid")
        binding_source = servant_skill_param_binding_source(
            ctx.services.rules, ctx.state, dragon_id,
        )
        damage_ratio = self._resolve_damage_ratio(ctx, binding_source)
        if damage_ratio is None:
            return ctx.services.block("castorice_breath_damage_binding_missing")
        trace = {
            "rule": "Servant_CastoriceServant_Skill02_Phase02 LoseHP + DamageByAttackProperty",
            "tbgd_commit": "14c1d18f91a8101d610e6c523447a7517de3fae1",
            "processor": f"{self.content_id}:{self.version}",
        }
        # HP cost (floor 1): hp_loss family, L1 settlement.
        cost = min(dragon.max_hp * cost_ratio, max(0.0, dragon.hp - 1.0))
        if cost > 0:
            ctx.services.apply_damage(DamagePacket(
                attacker_id=dragon_id, target_id=dragon_id, attack_type="hp_loss",
                damage_formula_family="hp_loss", amount=cost, amount_stage="fixed_final",
                damage_kind="hp_loss",
                source_frame=DamageSourceFrame(
                    owner_id=dragon_id, source_id="content_processor:castorice:breath_cost",
                    source_kind="effect_damage",
                    sequence_id=f"breath_cost:{ctx.state.event_index}:{dragon_id}",
                    target_id=dragon_id, can_continue_after_lethal=False,
                    source_trace=trace,
                ),
                source_trace=trace,
                metadata={"content_processor": self.content_id, "breath_hp_cost_ratio": cost_ratio},
            ))
        # AoE damage on the generically resolved targets.
        targets = tuple(ctx.target_resolution.selected)
        if not targets:
            return ctx.services.block("castorice_breath_no_targets")
        for index, target_id in enumerate(targets):
            ctx.services.apply_damage(DamagePacket(
                attacker_id=dragon_id, target_id=target_id, attack_type="Servant",
                damage_formula_family="direct", damage_kind="hp_damage",
                element_type="Quantum",
                scaling_ratio=damage_ratio,
                scaling_basis={"kind": "unit_stat", "unit_ref": "attacker_summoner", "stat": "max_hp"},
                action_definition=ctx.action_definition,
                source_task_id="content_processor:castorice:breath",
                source_frame=DamageSourceFrame(
                    owner_id=dragon_id, source_id="content_processor:castorice:breath",
                    source_kind="effect_damage",
                    sequence_id=f"breath:{ctx.state.event_index}:{dragon_id}:{index}",
                    target_id=target_id, can_continue_after_lethal=True,
                    source_trace=trace,
                ),
                source_trace=trace,
                metadata={"content_processor": self.content_id, "breath_damage_ratio": damage_ratio},
            ))
        # Formal toughness reduction through the shared L1 toughness/break
        # path. Preferred source: the action's compiled toughness emission
        # (canonical amount expression + formal binding sources). Fallback:
        # the action definition's formal show_stance_list per-hit values.
        rules = ctx.services.rules
        emissions = rules.toughness_emissions_for_action(ctx.command.action_id, ctx.command.action_level)
        emission = next(
            (item for item in emissions if item.coverage_status == "executable"),
            emissions[0] if emissions else None,
        )
        # Resolve the formal stance amount: first the compiled emission's
        # canonical expression through the L1 evaluator (runtime binding
        # sources + compiled fallback), then the action definition's formal
        # show_stance_list per-hit values. Neither available -> fail closed.
        stance_amount: float | None = None
        stance_source = ""
        if emission is not None:
            from ..rules.value_binding import resolve_runtime_numeric_expression

            expr_sources = []
            if binding_source is not None:
                expr_sources.append(binding_source)
            compiled = (emission.toughness_amount_expr or {}).get("binding_source")
            if isinstance(compiled, dict):
                expr_sources.append({
                    **compiled,
                    "binding_role": "compiled_expression_fallback",
                })
            resolution = resolve_runtime_numeric_expression(
                emission.toughness_amount_expr,
                binding_sources=tuple(expr_sources),
            )
            if resolution.ok and resolution.value is not None and resolution.value > 0:
                stance_amount = float(resolution.value)
                stance_source = "toughness_emission.toughness_amount_expr"
        if stance_amount is None:
            stance_values = tuple(
                float(item["Value"])
                for item in ctx.action_definition.show_stance_list
                if isinstance(item, dict)
                and isinstance(item.get("Value"), (int, float))
                and float(item["Value"]) > 0
            )
            if stance_values:
                stance_amount = stance_values[0]
                stance_source = "action_definition.show_stance_list"
        if stance_amount is None:
            return ctx.services.block("castorice_breath_stance_source_missing")
        for target_id in targets:
            packet = ToughnessPacket(
                attacker_id=dragon_id,
                target_id=target_id,
                toughness_emission_id=emission.toughness_emission_id if emission is not None else "",
                source_task_id=emission.source_task_id if emission is not None else "content_processor:castorice:breath",
                hit_profile_id=emission.hit_profile_id if emission is not None else "",
                element_type=emission.element_type if emission is not None else "Quantum",
                amount=stance_amount,
                target_group=emission.target_group if emission is not None else "primary",
                coverage_status="executable",
                source_trace=trace,
                amount_expr=emission.toughness_amount_expr if emission is not None else {},
                metadata={
                    "content_processor": self.content_id,
                    "primary_action_target_id": targets[0],
                    "stance_source": stance_source,
                    "value_binding_sources": [binding_source] if binding_source else [],
                },
            )
            ctx.services.apply_toughness(packet)
        return ctx.services.finish(takeover=True)

    def subscriptions(self) -> tuple[EventSubscription, ...]:
        return (
            EventSubscription(("summon.spawned", "unit.defeated", "summon.removed"), scope="self_units"),
        )

    def on_event(self, ctx: EventHookContext) -> HookResult:
        return ctx.services.finish()
