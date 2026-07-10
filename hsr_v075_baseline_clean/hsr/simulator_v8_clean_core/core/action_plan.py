from __future__ import annotations

from dataclasses import dataclass, field

from ..rules.ir import ActionDefinitionIR, ActionEventIR, DamageEmissionIR, HitProfileIR, ToughnessEmissionIR


@dataclass(frozen=True)
class ActionEventStep:
    kind: str
    phase: str
    canonical_window: str = ""
    tbgd_event: str = ""
    requires_action_enabled: bool = True

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "phase": self.phase,
            "canonical_window": self.canonical_window,
            "tbgd_event": self.tbgd_event,
            "requires_action_enabled": self.requires_action_enabled,
        }


@dataclass(frozen=True)
class ActionEventPlan:
    action_id: str
    action_level: int
    skill_type: str
    attack_type: str
    damage_kind: str
    damage_formula_family: str
    has_attack_windows: bool
    has_damage_step: bool
    steps: tuple[ActionEventStep, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_level": self.action_level,
            "skill_type": self.skill_type,
            "attack_type": self.attack_type,
            "damage_kind": self.damage_kind,
            "damage_formula_family": self.damage_formula_family,
            "has_attack_windows": self.has_attack_windows,
            "has_damage_step": self.has_damage_step,
            "steps": [step.to_json() for step in self.steps],
        }


@dataclass(frozen=True)
class TargetPlan:
    target_mode: str
    selection_mode: str
    requested_target_ids: tuple[str, ...]
    source: str = "action_definition"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "target_mode": self.target_mode,
            "selection_mode": self.selection_mode,
            "requested_target_ids": list(self.requested_target_ids),
            "source": self.source,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class HitPlan:
    hit_profile_id: str
    hit_index: int
    target_group: str
    multiplier_source: object
    scaling_ratio: float | None = None
    hit_source_trace: dict[str, object] | None = None
    numeric_fidelity_status: str = "unknown"
    multi_hit_not_implemented: bool = True
    hit_formula_slot_admitted: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "hit_profile_id": self.hit_profile_id,
            "hit_index": self.hit_index,
            "target_group": self.target_group,
            "multiplier_source": self.multiplier_source,
            "scaling_ratio": self.scaling_ratio,
            "hit_source_trace": self.hit_source_trace or {},
            "numeric_fidelity_status": self.numeric_fidelity_status,
            "multi_hit_not_implemented": self.multi_hit_not_implemented,
            "hit_formula_slot_admitted": self.hit_formula_slot_admitted,
        }


@dataclass(frozen=True)
class DamagePlan:
    damage_emission_id: str
    source_task_id: str
    hit_profile_id: str
    hit_index: int
    target_id: str
    target_group: str
    damage_formula_family: str
    multiplier_source: object
    scaling_ratio: float
    scaling_basis: dict[str, object]
    hit_source_trace: dict[str, object]
    numeric_fidelity_status: str = "unknown"
    primary_action_target_id: str | None = None
    blocked_reason: str = ""
    target_group_multiplier_not_implemented: bool = False
    target_selection_policy: dict[str, object] | None = None
    value_request: dict[str, object] = field(default_factory=dict)
    value_context: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "damage_emission_id": self.damage_emission_id,
            "source_task_id": self.source_task_id,
            "hit_profile_id": self.hit_profile_id,
            "hit_index": self.hit_index,
            "target_id": self.target_id,
            "target_group": self.target_group,
            "damage_formula_family": self.damage_formula_family,
            "multiplier_source": self.multiplier_source,
            "scaling_ratio": self.scaling_ratio,
            "scaling_basis": self.scaling_basis,
            "hit_source_trace": self.hit_source_trace,
            "numeric_fidelity_status": self.numeric_fidelity_status,
            "primary_action_target_id": self.primary_action_target_id,
            "blocked_reason": self.blocked_reason,
            "target_group_multiplier_not_implemented": self.target_group_multiplier_not_implemented,
            "target_selection_policy": self.target_selection_policy or {},
            "value_request": self.value_request,
            "value_context": self.value_context,
        }


@dataclass(frozen=True)
class ToughnessPlan:
    toughness_emission_id: str
    source_task_id: str
    hit_profile_id: str
    hit_index: int
    target_id: str
    target_group: str
    element_type: str | None
    toughness_amount_expr: dict[str, object]
    toughness_amount_evaluation: dict[str, object] | None
    source_trace: dict[str, object]
    primary_action_target_id: str | None = None
    blocked_reason: str = ""
    value_request: dict[str, object] = field(default_factory=dict)
    value_context: dict[str, object] = field(default_factory=dict)
    value_binding_sources: tuple[dict[str, object], ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "toughness_emission_id": self.toughness_emission_id,
            "source_task_id": self.source_task_id,
            "hit_profile_id": self.hit_profile_id,
            "hit_index": self.hit_index,
            "target_id": self.target_id,
            "target_group": self.target_group,
            "element_type": self.element_type,
            "toughness_amount_expr": self.toughness_amount_expr,
            "toughness_amount_evaluation": self.toughness_amount_evaluation or {},
            "source_trace": self.source_trace,
            "primary_action_target_id": self.primary_action_target_id,
            "blocked_reason": self.blocked_reason,
            "value_request": self.value_request,
            "value_context": self.value_context,
            "value_binding_sources": list(self.value_binding_sources),
        }


@dataclass(frozen=True)
class ActionExecutionPlan:
    action_id: str
    action_level: int
    event_steps: tuple[ActionEventStep, ...]
    target_plan: TargetPlan
    hit_plan: tuple[HitPlan, ...]
    damage_plan: tuple[DamagePlan, ...]
    damage_emissions: tuple[DamageEmissionIR, ...]
    toughness_plan: tuple[ToughnessPlan, ...]
    toughness_emissions: tuple[ToughnessEmissionIR, ...]
    source_trace: dict[str, object]
    derived_reason: str
    primary_action_target_id: str | None = None
    per_hit_target_context_available: bool = False
    per_hit_listener_admission_partial: bool = True

    def to_json(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_level": self.action_level,
            "event_steps": [step.to_json() for step in self.event_steps],
            "target_plan": self.target_plan.to_json(),
            "hit_plan": [hit.to_json() for hit in self.hit_plan],
            "damage_plan": [damage.to_json() for damage in self.damage_plan],
            "damage_emissions": [emission.to_json() for emission in self.damage_emissions],
            "toughness_plan": [toughness.to_json() for toughness in self.toughness_plan],
            "toughness_emissions": [emission.to_json() for emission in self.toughness_emissions],
            "source_trace": self.source_trace,
            "derived_reason": self.derived_reason,
            "derived_from_action_definition": True,
            "plan_source": "action_event_ir_damage_emission_ir_hit_profile_ir",
            "damage_plan_source": "damage_emission_ir_hit_profile_ir",
            "event_source_status": self.source_trace.get("event_source_status", ""),
            "binding_id": self.source_trace.get("binding_id", ""),
            "phase_ids": list(self.source_trace.get("phase_ids", ())),
            "damage_emission_ids": [emission.damage_emission_id for emission in self.damage_emissions],
            "toughness_emission_ids": [emission.toughness_emission_id for emission in self.toughness_emissions],
            "primary_action_target_id": self.primary_action_target_id,
            "per_hit_target_context_available": self.per_hit_target_context_available,
            "per_hit_listener_admission_partial": self.per_hit_listener_admission_partial,
            "per_hit_target_context_not_implemented": not self.per_hit_target_context_available,
        }


def build_action_event_plan(action_definition: ActionDefinitionIR) -> ActionEventPlan:
    has_damage = action_definition.damage_kind == "hp_damage"
    has_attack_windows = has_damage or _is_explicit_attack(action_definition)
    steps: list[ActionEventStep] = [
        ActionEventStep(
            kind="trigger_window",
            phase="before_skill_use",
            canonical_window="before_skill_use",
            tbgd_event="OnBeforeSkillUse",
        )
    ]
    if has_attack_windows:
        steps.append(
            ActionEventStep(
                kind="trigger_window",
                phase="before_attack",
                canonical_window="before_attack",
                tbgd_event="OnBeforeAttack",
            )
        )
    if has_damage:
        steps.append(ActionEventStep(kind="damage", phase="damage"))
    if has_attack_windows:
        steps.append(
            ActionEventStep(
                kind="trigger_window",
                phase="after_attack",
                canonical_window="after_attack",
                tbgd_event="OnAfterAttack",
            )
        )
    steps.append(
        ActionEventStep(
            kind="trigger_window",
            phase="after_skill_use",
            canonical_window="after_skill_use",
            tbgd_event="OnAfterSkillUse",
        )
    )
    return ActionEventPlan(
        action_id=action_definition.action_id,
        action_level=action_definition.level,
        skill_type=action_definition.skill_effect,
        attack_type=action_definition.attack_type,
        damage_kind=action_definition.damage_kind,
        damage_formula_family=action_definition.damage_formula_family,
        has_attack_windows=has_attack_windows,
        has_damage_step=has_damage,
        steps=tuple(steps),
    )


def build_action_execution_plan(
    action_definition: ActionDefinitionIR,
    action_event: ActionEventIR,
    hit_profiles: tuple[HitProfileIR, ...],
    damage_emissions: tuple[DamageEmissionIR, ...] = (),
    toughness_emissions: tuple[ToughnessEmissionIR, ...] = (),
    *,
    requested_target_ids: tuple[str, ...],
    resolved_target_groups: dict[str, tuple[str, ...]] | None = None,
    source_trace: dict[str, object] | None = None,
) -> ActionExecutionPlan:
    target_mode = action_event.target_mode
    target_plan_blocked_reason = _combined_blocked_reason(
        _execution_target_plan_source_blocked_reason(action_event.blocked_reason, damage_emissions, toughness_emissions),
        _target_plan_blocked_reason(target_mode),
    )
    target_plan = TargetPlan(
        target_mode=target_mode,
        selection_mode=action_event.selection_mode or _selection_mode(target_mode),
        requested_target_ids=requested_target_ids,
        source="action_event_ir",
        blocked_reason=target_plan_blocked_reason,
    )
    primary_action_target_id = _primary_action_target_id(resolved_target_groups or {})
    hit_plan = tuple(_hit_plan(profile) for profile in hit_profiles)
    damage_plan = _damage_plan_from_emissions(
        action_definition,
        damage_emissions,
        {profile.hit_profile_id: profile for profile in hit_profiles},
        resolved_target_groups or {},
        primary_action_target_id,
        target_plan.blocked_reason,
    )
    toughness_plan = _toughness_plan_from_emissions(
        action_definition,
        toughness_emissions,
        {profile.hit_profile_id: profile for profile in hit_profiles},
        resolved_target_groups or {},
        primary_action_target_id,
        target_plan.blocked_reason,
    )
    event_steps = tuple(_event_step_from_ir(step) for step in action_event.phase_steps)
    if not any(step.kind == "damage" for step in event_steps) and (damage_plan or toughness_plan):
        event_steps = (
            *event_steps,
            ActionEventStep(
                kind="damage",
                phase="damage",
                canonical_window="damage",
                tbgd_event="action_damage_plan",
                requires_action_enabled=True,
            ),
        )
    return ActionExecutionPlan(
        action_id=action_definition.action_id,
        action_level=action_definition.level,
        event_steps=event_steps,
        target_plan=target_plan,
        hit_plan=hit_plan,
        damage_plan=damage_plan,
        damage_emissions=damage_emissions,
        toughness_plan=toughness_plan,
        toughness_emissions=toughness_emissions,
        source_trace=source_trace or {},
        derived_reason=action_event.derived_reason,
        primary_action_target_id=primary_action_target_id,
        per_hit_target_context_available=bool(damage_plan or toughness_plan),
        per_hit_listener_admission_partial=True,
    )


def _event_step_from_ir(step) -> ActionEventStep:
    return ActionEventStep(
        kind=step.kind,
        phase=step.phase,
        canonical_window=step.canonical_window,
        tbgd_event=step.tbgd_event,
        requires_action_enabled=step.requires_action_enabled,
    )


def _hit_plan(profile: HitProfileIR) -> HitPlan:
    hit_formula_slot_admitted = profile.multiplier_source.get("source_kind") == "character_data_card_skill_formula"
    return HitPlan(
        hit_profile_id=profile.hit_profile_id,
        hit_index=profile.hit_index,
        target_group=profile.target_group,
        multiplier_source=profile.multiplier_source,
        scaling_ratio=_hit_scaling_ratio(profile),
        hit_source_trace=profile.source.to_json(),
        numeric_fidelity_status=profile.numeric_fidelity_status,
        multi_hit_not_implemented=not hit_formula_slot_admitted,
        hit_formula_slot_admitted=hit_formula_slot_admitted,
    )


def _damage_plan_from_emissions(
    action_definition: ActionDefinitionIR,
    damage_emissions: tuple[DamageEmissionIR, ...],
    hit_profiles: dict[str, HitProfileIR],
    target_groups: dict[str, tuple[str, ...]],
    primary_action_target_id: str | None,
    plan_blocked_reason: str,
) -> tuple[DamagePlan, ...]:
    if action_definition.damage_kind != "hp_damage" or plan_blocked_reason:
        return ()
    plans: list[DamagePlan] = []
    for emission in damage_emissions:
        if emission.coverage_status != "executable":
            continue
        profile = hit_profiles.get(emission.hit_profile_id)
        if profile is None:
            continue
        scaling_ratio = _hit_scaling_ratio(profile)
        if scaling_ratio is None:
            continue
        value_request = _damage_value_request(profile, emission, scaling_ratio)
        for target_id in _targets_for_hit_profile(profile, target_groups):
            plans.append(
                DamagePlan(
                    damage_emission_id=emission.damage_emission_id,
                    source_task_id=emission.source_task_id,
                    hit_profile_id=profile.hit_profile_id,
                    hit_index=profile.hit_index,
                    target_id=target_id,
                    target_group=profile.target_group,
                    damage_formula_family=profile.damage_formula_family,
                    multiplier_source=profile.multiplier_source,
                    scaling_ratio=scaling_ratio,
                    scaling_basis=emission.scaling_basis_expr,
                    hit_source_trace=emission.source.to_json(),
                    numeric_fidelity_status=profile.numeric_fidelity_status,
                    primary_action_target_id=primary_action_target_id,
                    blocked_reason=profile.blocked_reason,
                    target_group_multiplier_not_implemented=_target_group_multiplier_not_implemented(action_definition, profile),
                    target_selection_policy=profile.target_selection_policy,
                    value_request=value_request,
                    value_context=_damage_value_context(profile),
                )
            )
    return tuple(plans)


def _toughness_plan_from_emissions(
    action_definition: ActionDefinitionIR,
    toughness_emissions: tuple[ToughnessEmissionIR, ...],
    hit_profiles: dict[str, HitProfileIR],
    target_groups: dict[str, tuple[str, ...]],
    primary_action_target_id: str | None,
    plan_blocked_reason: str,
) -> tuple[ToughnessPlan, ...]:
    if plan_blocked_reason:
        return ()
    plans: list[ToughnessPlan] = []
    for emission in toughness_emissions:
        if emission.coverage_status != "executable":
            continue
        profile = hit_profiles.get(emission.hit_profile_id)
        if profile is None:
            continue
        value_request, value_binding_sources = _toughness_value_request(emission)
        for target_id in _targets_for_hit_profile(profile, target_groups):
            plans.append(
                ToughnessPlan(
                    toughness_emission_id=emission.toughness_emission_id,
                    source_task_id=emission.source_task_id,
                    hit_profile_id=profile.hit_profile_id,
                    hit_index=profile.hit_index,
                    target_id=target_id,
                    target_group=profile.target_group,
                    element_type=emission.element_type,
                    toughness_amount_expr=emission.toughness_amount_expr,
                    toughness_amount_evaluation=None,
                    source_trace=emission.source.to_json(),
                    primary_action_target_id=primary_action_target_id,
                    blocked_reason=emission.blocked_reason,
                    value_request=value_request,
                    value_context={},
                    value_binding_sources=value_binding_sources,
                )
            )
    return tuple(plans)


def _targets_for_hit_profile(
    profile: HitProfileIR,
    target_groups: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    if profile.target_group == "primary":
        return target_groups.get("primary", ())
    if profile.target_group == "adjacent":
        return target_groups.get("adjacent", ())
    if profile.target_group == "selected":
        return target_groups.get("selected", ())
    if profile.target_group.startswith("bounce:"):
        return ("__bounce_pending__",)
    return ()


def _target_group_multiplier_not_implemented(action_definition: ActionDefinitionIR, profile: HitProfileIR) -> bool:
    if action_definition.target_mode not in {"aoe", "blast"}:
        return False
    return str(profile.multiplier_source.get("source_kind") or "") != "character_data_card_skill_formula"


def _hit_scaling_ratio(profile: HitProfileIR) -> float | None:
    expr = profile.multiplier_expr
    if expr.get("kind") != "fixed":
        return None
    value = expr.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _damage_value_request(
    profile: HitProfileIR,
    emission: DamageEmissionIR,
    scaling_ratio: float,
) -> dict[str, object]:
    multiplier_source = profile.multiplier_source if isinstance(profile.multiplier_source, dict) else {}
    source_kind = str(multiplier_source.get("source_kind") or "")
    binding_id = str(multiplier_source.get("skill_formula_binding_id") or "")
    trace = {
        "value_request_source": "HitProfileIR.multiplier_source",
        "damage_emission_id": emission.damage_emission_id,
        "hit_profile_id": profile.hit_profile_id,
        "source_kind": source_kind,
        "multiplier_source": multiplier_source,
    }
    if binding_id and source_kind in {"character_data_card_skill_formula", "monster_data_card_skill_formula"}:
        param_index = _structured_param_index(multiplier_source)
        if param_index is None:
            return {
                "binding_kind": "blocked",
                "blocked_reason": "damage_value_request_param_index_missing",
                "required_context_keys": [],
                "source_trace": trace,
            }
        return {
            "binding_kind": "skill_formula_param",
            "binding_id": binding_id,
            "param_index": param_index,
            "formula_role": "direct_damage",
            "required_context_keys": ["action"],
            "source_trace": trace,
        }
    if _fixed_expr_value(profile.multiplier_expr) is not None:
        return {
            "binding_kind": "fixed_numeric_expression",
            "expression": dict(profile.multiplier_expr),
            "required_context_keys": ["action"],
            "source_trace": {
                **trace,
                "value_request_source": "HitProfileIR.multiplier_expr",
                "scaling_ratio": scaling_ratio,
            },
        }
    return {
        "binding_kind": "blocked",
        "blocked_reason": "damage_value_request_missing",
        "required_context_keys": [],
        "source_trace": trace,
    }


def _damage_value_context(profile: HitProfileIR) -> dict[str, object]:
    multiplier_source = profile.multiplier_source if isinstance(profile.multiplier_source, dict) else {}
    data_card_id = str(
        multiplier_source.get("data_card_id")
        or multiplier_source.get("character_data_card_id")
        or ""
    )
    data_card_kind = str(multiplier_source.get("data_card_kind") or "")
    if not data_card_kind and data_card_id:
        data_card_kind = "character"
    return {
        "data_card_id": data_card_id,
        "data_card_kind": data_card_kind,
    }


def _structured_param_index(source: dict[str, object]) -> int | None:
    param_index = source.get("param_index")
    if isinstance(param_index, bool) or not isinstance(param_index, int) or param_index < 0:
        return None
    return param_index


def _toughness_value_request(emission: ToughnessEmissionIR) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    expression = emission.toughness_amount_expr
    binding_sources = _binding_sources_from_expression(expression)
    hashes = sorted(_hashes_from_expression(expression))
    trace = {
        "value_request_source": "ToughnessEmissionIR.toughness_amount_expr",
        "toughness_emission_id": emission.toughness_emission_id,
        "source_kind": expression.get("source_kind") if isinstance(expression, dict) else "",
    }
    if hashes:
        if not binding_sources:
            return (
                {
                    "binding_kind": "blocked",
                    "blocked_reason": "toughness_dynamic_binding_source_missing",
                    "expression": {"kind": "dynamic_hash", "hash": hashes[0]},
                    "required_context_keys": ["dynamic_value_source"],
                    "source_trace": trace,
                },
                (),
            )
        return (
            {
                "binding_kind": "dynamic_hash",
                "expression": {"kind": "dynamic_hash", "hash": hashes[0]},
                "required_context_keys": ["dynamic_value_source"],
                "source_trace": trace,
            },
            binding_sources,
        )
    if _fixed_expr_value(expression) is not None:
        return (
            {
                "binding_kind": "fixed_numeric_expression",
                "expression": dict(expression),
                "required_context_keys": ["action"],
                "source_trace": trace,
            },
            (),
        )
    return (
        {
            "binding_kind": "blocked",
            "blocked_reason": "toughness_value_request_missing",
            "expression": dict(expression) if isinstance(expression, dict) else expression,
            "required_context_keys": [],
            "source_trace": trace,
        },
        binding_sources,
    )


def _binding_sources_from_expression(expression: object) -> tuple[dict[str, object], ...]:
    sources: list[dict[str, object]] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            binding_source = value.get("binding_source")
            if _is_binding_source(binding_source):
                sources.append(dict(binding_source))
            for key, item in value.items():
                if key == "source_trace":
                    continue
                if isinstance(item, (dict, list, tuple)):
                    visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(expression)
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        key = (
            str(source.get("source_type") or ""),
            ",".join(sorted(str(key) for key in dict(source.get("by_hash") or {}).keys())),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return tuple(deduped)


def _is_binding_source(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return bool(value.get("source_type")) and (
        isinstance(value.get("by_hash"), dict) or isinstance(value.get("by_name"), dict)
    )


def _hashes_from_expression(expression: object) -> set[str]:
    hashes: set[str] = set()
    if isinstance(expression, dict):
        if str(expression.get("kind") or "") == "dynamic_hash" and expression.get("hash") is not None:
            hashes.add(str(expression.get("hash")))
        dynamic_hashes = expression.get("DynamicHashes")
        if isinstance(dynamic_hashes, list):
            for item in dynamic_hashes:
                hashes.add(str(item))
        raw = expression.get("raw")
        if isinstance(raw, (dict, list)):
            hashes.update(_hashes_from_expression(raw))
        postfix = expression.get("PostfixExpr")
        if isinstance(postfix, dict):
            hashes.update(_hashes_from_expression(postfix))
        for key, item in expression.items():
            if key in {"raw", "PostfixExpr", "source_trace"}:
                continue
            if isinstance(item, (dict, list)):
                hashes.update(_hashes_from_expression(item))
    elif isinstance(expression, list):
        for item in expression:
            hashes.update(_hashes_from_expression(item))
    return hashes


def _fixed_expr_value(expression: object) -> float | None:
    if isinstance(expression, bool):
        return None
    if isinstance(expression, (int, float)):
        return float(expression)
    if not isinstance(expression, dict):
        return None
    kind = str(expression.get("kind") or "")
    if kind == "fixed":
        value = expression.get("value")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    fixed_value = expression.get("FixedValue")
    if isinstance(fixed_value, dict):
        value = fixed_value.get("Value")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return None


def _is_explicit_attack(action_definition: ActionDefinitionIR) -> bool:
    skill_effect = action_definition.skill_effect.lower()
    attack_type = action_definition.attack_type.lower()
    target_mode = action_definition.target_mode.lower()
    if target_mode in {"single", "blast", "aoe", "bounce"}:
        return True
    return "attack" in skill_effect or "attack" in attack_type


def _selection_mode(target_mode: str) -> str:
    if target_mode == "single":
        return "primary"
    if target_mode == "aoe":
        return "all_enemies"
    if target_mode == "blast":
        return "primary_plus_adjacent"
    if target_mode == "bounce":
        return "blocked_random_bounce"
    if target_mode == "self_or_team":
        return "explicit_ally_or_self"
    return "unknown"


def _target_plan_blocked_reason(target_mode: str) -> str:
    if target_mode == "unknown":
        return "unknown_target_mode_not_executable"
    return ""


def _execution_target_plan_source_blocked_reason(
    blocked_reason: str,
    damage_emissions: tuple[DamageEmissionIR, ...],
    toughness_emissions: tuple[ToughnessEmissionIR, ...],
) -> str:
    if blocked_reason == "missing_ability_phase_in_ability_file" and (damage_emissions or toughness_emissions):
        return ""
    return blocked_reason


def _combined_blocked_reason(*reasons: str) -> str:
    return ",".join(dict.fromkeys(reason for reason in reasons if reason))


def _damage_targets(
    action_definition: ActionDefinitionIR,
    target_groups: dict[str, tuple[str, ...]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if action_definition.damage_kind != "hp_damage":
        return ()
    if action_definition.target_mode == "bounce":
        return ()
    if action_definition.target_mode == "blast":
        groups: list[tuple[str, tuple[str, ...]]] = []
        primary = target_groups.get("primary", ())
        adjacent = target_groups.get("adjacent", ())
        if primary:
            groups.append(("primary", primary))
        if adjacent:
            groups.append(("adjacent", adjacent))
        return tuple(groups)
    selected = target_groups.get("selected", ())
    return (("selected", selected),) if selected else ()


def _primary_action_target_id(target_groups: dict[str, tuple[str, ...]]) -> str | None:
    primary = target_groups.get("primary", ())
    if primary:
        return primary[0]
    selected = target_groups.get("selected", ())
    if selected:
        return selected[0]
    return None
