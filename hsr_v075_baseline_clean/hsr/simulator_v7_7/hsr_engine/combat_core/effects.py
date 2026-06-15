from __future__ import annotations

from copy import deepcopy
from typing import Any

from hsr_engine.core_rules import coerce_comparison_value
from hsr_engine.kernel import SourceRef, StateChange

from ._legacy_effects import LegacyEffectRuntime
from .effect_registry import EffectRegistry


class EffectRuntime:
    """Clean-core effect facade backed by an explicit EffectRegistry."""

    def __init__(self, simulator: Any, registry: EffectRegistry | None = None) -> None:
        self.sim = simulator
        self.legacy = LegacyEffectRuntime(simulator)
        self.registry = registry or EffectRegistry(fallback=self.legacy.apply_effect)
        self.registry.register("set_unit_flag", self._handle_set_unit_flag)

    def apply_effect(self, eff: dict[str, Any], ctx: dict[str, Any]) -> None:
        return self.registry.dispatch(eff, ctx)

    def coverage_matrix(self) -> dict[str, Any]:
        return self.registry.coverage_matrix()

    def _handle_set_unit_flag(self, eff: dict[str, Any], ctx: dict[str, Any]) -> None:
        rule_evaluator = ctx.get("_rule_evaluator") or getattr(self.sim, "_rule_evaluator", None)
        state_store = ctx.get("_state_store") or getattr(self.sim, "_state_store", None)
        state_mutator = ctx.get("_state_mutator") or getattr(self.sim, "_state_mutator", None)
        if rule_evaluator is None or state_store is None or state_mutator is None:
            return self.legacy.apply_effect(eff, ctx)
        action = ctx.get("action") if isinstance(ctx.get("action"), dict) else {}
        actor_id = str(ctx.get("actor_id") or action.get("actor_id") or "")
        action_id = str(action.get("id") or action.get("action_id") or "effect:set_unit_flag")
        targets = rule_evaluator.target_reference(eff.get("target", "actor"), ctx, default="actor")
        for target_id in targets:
            unit = state_store.unit(target_id)
            key = str(eff["key"])
            old = deepcopy(unit.flags.get(key))
            value = coerce_comparison_value(eff.get("value", True))
            change = StateChange(
                change_type="flag",
                scope="unit",
                subject_id=unit.id,
                field_path=f"unit.flags.{key}",
                old_value=old,
                new_value=deepcopy(value),
                source=SourceRef(source_type="effect", source_id=action_id, owner_id=actor_id),
                reason="effect:set_unit_flag",
                payload={"effect": deepcopy(eff)},
            )
            state_mutator.commit_state_change(change, ctx)
            state_store.state.log_event("effect", f"Set {target_id}.{key}={unit.flags[key]}")
