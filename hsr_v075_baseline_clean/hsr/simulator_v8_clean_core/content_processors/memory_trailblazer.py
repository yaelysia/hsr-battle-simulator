"""记忆开拓者史诗耗尽时解除强化普攻映射。

14c1d18f Avatar_PlayerBoy_30_Ability：UltraState_Sub.AdditionConfig.DependencyOnRemove
明确依赖同施加者的UltraState。通过现有状态移除入口执行子状态OnDestroy，恢复Skill01。
"""
from dataclasses import replace
from ..core.content_hooks import ContentProcessorBase, EventSubscription
from ..systems.action_availability import BlockedActionReason
from ..systems.status import StatusLifecyclePlan
from ..systems.dynamic_values import store_from_state
from ..systems.mutation_events import native_energy_change_value


class MemoryTrailblazerProcessor(ContentProcessorBase):
    content_id = 'avatar:8007'
    version = '0.3.0'
    # 800704: all allies' recovered energy feeds ONE summoner-owned pool.
    # The generic omitted-target writes otherwise split it across aura owners.
    replaced_status_callbacks = frozenset({('MAvatar_PlayerBoy_30_Halo_ListenSPChange', 'OnSPChange')})

    def claims_action(self, state, action_id, action_level):
        return action_id in {'avatar_skill:800702', 'avatar_skill:800703'} and any(
            u.template_id == 'servant:18007' and u.lifecycle_status == 'defeated' for u in state.units.values())

    def execute_action(self, ctx):
        # 800702/800703 explicitly summon Mem. Retire only this owner's defeated
        # instance; the original creation task still owns all birth parameters.
        for unit in tuple(ctx.state.units.values()):
            if (unit.template_id == 'servant:18007' and unit.flags.get('owner_id') == ctx.command.actor_id
                    and unit.lifecycle_status == 'defeated'):
                ctx.services.remove_summon(unit.unit_id, 'memory_recreate_defeated_mem',
                    source_trace={'rule': '800702/800703 summon Mem', 'processor': self.version})
        return ctx.services.finish(takeover=False)

    def subscriptions(self):
        return (EventSubscription(('status.lifecycle',)), EventSubscription(('energy.change',), scope='battle'))

    def on_event(self, ctx):
        if ctx.event.event_type == 'energy.change':
            gained, reason = native_energy_change_value(ctx.event)
            if reason or gained is None or gained <= 0:
                return ctx.services.finish()
            target = ctx.services.unit(ctx.event.target_id)
            for owner in ctx.state.units.values():
                if owner.template_id != self.content_id or owner.lifecycle_status != 'active' or target is None or target.side != owner.side:
                    continue
                if not any(u.flags.get('owner_id') == owner.unit_id and u.template_id == 'servant:18007'
                           and u.lifecycle_status == 'active' for u in ctx.state.units.values()):
                    continue
                values = [entry['value'] for entry in store_from_state(ctx.services.state)['entries'].values()
                          if entry.get('scope') == 'unit' and entry.get('owner_id') == owner.unit_id
                          and entry.get('hash') == '-1043063097']
                if len(values) != 1:
                    return ctx.services.block('memory_team_energy_pool_missing')
                ctx.services.set_dynamic_value(owner.unit_id, 'TeamAddSP', '-1043063097', values[0] + gained, ctx.event)
            return ctx.services.finish()
        plan = ctx.event.status_lifecycle_plan
        if (type(plan) is not StatusLifecyclePlan or ctx.event.window != 'OnDestroy'
                or plan.status_id != 'modifier:MAvatar_PlayerBoy_30_UltraState'
                or plan.operation not in {'remove', 'dispel', 'expire', 'stack_reduce_remove'}):
            return ctx.services.finish()
        unit = ctx.services.unit(plan.target_id)
        if unit is not None and plan.existing_detail is not None:
            for detail in tuple(unit.flags.get('status_details', ())):
                if (detail['modifier_name'] == 'MAvatar_PlayerBoy_30_UltraState_Sub'
                        and detail['caster_id'] == plan.existing_detail['caster_id']):
                    ctx.services.remove_status(unit.unit_id, detail)
        return ctx.services.finish()


class MemProcessor(ContentProcessorBase):
    """1800703/1800707: full charge replaces Mem's attack with selectable support."""
    content_id = 'servant:18007'
    version = '0.1.0'

    def filter_choices(self, ctx):
        full = 'modifier:M_PlayerBoyServant_30_EnableSkill' in ctx.actor.statuses
        selected = 'servant_skill:1800707' if full else 'servant_skill:1800701'
        rejected = tuple(c for c in ctx.choices if c.choice_kind in {'normal_action', 'summon_action'} and c.action_id != selected)
        return replace(ctx, choices=tuple(c for c in ctx.choices if c not in rejected),
            blocked=ctx.blocked + tuple(BlockedActionReason('mem_charge_action_replaced', 'content',
                actor_id=ctx.actor.unit_id, actor_side=ctx.actor.side, action_id=c.action_id,
                action_level=c.action_level) for c in rejected))
