from __future__ import annotations

from dataclasses import dataclass

from .ir import (
    DamageFormulaRuleIR,
    DamageRouteRuleIR,
    IRSource,
    ResourceRuleIR,
    ShieldPriorityRuleIR,
    TimelineRuleIR,
)


ENGINE_RULE_REGISTRY_VERSION = "hsr_v8_engine_rules_v3"
ENGINE_RULE_SOURCE_KIND = "engine_convention"
TIMELINE_RULE_APPLICABILITY = "all timeline units with positive effective speed"
ULTIMATE_COST_RULE_APPLICABILITY = "admitted ultimate action committed from the ultimate queue window"
KILL_ENERGY_RULE_APPLICABILITY = "living kill-credit owner with a positive maximum energy"
DAMAGE_DEFENSE_RULE_APPLICABILITY = "direct and admitted non-direct damage defense stages"
DAMAGE_RESISTANCE_RULE_APPLICABILITY = "direct and admitted non-direct damage resistance stages"
SHIELD_PRIORITY_RULE_APPLICABILITY = "all source-distinguished shield instances"
NORMAL_DAMAGE_ROUTE_FAMILIES = (
    "direct",
    "additional",
    "dot",
    "break",
    "super_break",
    "true_damage",
)
HP_LOSS_ROUTE_FAMILIES = ("hp_loss",)
DAMAGE_ROUTE_APPLICABILITY = "damage family exact match before HP mutation"
SHIELD_PRIORITY_RULE_ID = "shield_priority_rule:engine_convention:priority_then_creation_order_v1"
ZERO_FLOOR_DYNAMIC_HASH = -1226284721
ZERO_FLOOR_DYNAMIC_RULE_KIND = "typed_numeric_max_zero_floor_operand"
ZERO_FLOOR_DYNAMIC_RULE_APPLICABILITY = (
    "typed numeric program using the undeclared dynamic hash as an operand of variadic max"
)
RANGE_ZERO_FLOOR_DYNAMIC_HASH = 339799074
RANGE_ZERO_FLOOR_DYNAMIC_RULE_KIND = (
    "typed_numeric_range_max_zero_floor_operand"
)
RANGE_ZERO_FLOOR_DYNAMIC_RULE_APPLICABILITY = (
    "typed numeric range program using the undeclared dynamic hash only as a direct operand of variadic max"
)


@dataclass(frozen=True)
class EngineRuleRegistry:
    registry_version: str
    timeline_rules: tuple[TimelineRuleIR, ...]
    resource_rules: tuple[ResourceRuleIR, ...]
    damage_formula_rules: tuple[DamageFormulaRuleIR, ...]
    damage_route_rules: tuple[DamageRouteRuleIR, ...]
    shield_priority_rules: tuple[ShieldPriorityRuleIR, ...]


def build_engine_rule_registry() -> EngineRuleRegistry:
    """Versioned rules whose current source category is engine convention."""

    return EngineRuleRegistry(
        registry_version=ENGINE_RULE_REGISTRY_VERSION,
        timeline_rules=(
            TimelineRuleIR(
                timeline_rule_id="timeline_rule:engine_convention:base_action_gauge_10000",
                base_action_gauge=10000.0,
                initial_action_value_rule="base_action_gauge / effective_speed",
                turn_reset_rule="base_action_gauge / effective_speed after regular turn end",
                source_kind=ENGINE_RULE_SOURCE_KIND,
                source=_source(
                    "TimelineEngineConvention",
                    "base_action_gauge_10000",
                    "TBGD raw constant source not admitted; explicitly versioned as an engine convention.",
                ),
                registry_version=ENGINE_RULE_REGISTRY_VERSION,
                applicability=TIMELINE_RULE_APPLICABILITY,
                coverage_status="executable",
            ),
        ),
        resource_rules=(
            ResourceRuleIR(
                resource_rule_id="resource_rule:engine_convention:ultimate_energy_cost_then_action_spbase",
                rule_kind="ultimate_energy_cost",
                operation="set_actor_energy_to_action_spbase_after_admitted_ultimate_execution",
                source_kind=ENGINE_RULE_SOURCE_KIND,
                source=_source(
                    "ResourceEngineConvention",
                    "ultimate_energy_cost_then_action_spbase",
                    "Ultimate cost ordering is an explicit engine convention pending an admitted raw source.",
                ),
                registry_version=ENGINE_RULE_REGISTRY_VERSION,
                applicability=ULTIMATE_COST_RULE_APPLICABILITY,
                coverage_status="executable",
            ),
            ResourceRuleIR(
                resource_rule_id="resource_rule:engine_convention:kill_energy_gain_10",
                rule_kind="kill_energy_gain",
                operation="add_fixed_energy_to_kill_credit_owner_on_unit_defeated",
                source_kind=ENGINE_RULE_SOURCE_KIND,
                source=_source(
                    "ResourceEngineConvention",
                    "kill_energy_gain_10",
                    "Common caused-kill energy gain is an explicit engine convention pending an admitted raw source.",
                ),
                registry_version=ENGINE_RULE_REGISTRY_VERSION,
                applicability=KILL_ENERGY_RULE_APPLICABILITY,
                numeric_value=10.0,
                coverage_status="executable",
            ),
        ),
        damage_formula_rules=(
            DamageFormulaRuleIR(
                damage_formula_rule_id="damage_formula_rule:engine_convention:defense_v1",
                rule_kind="defense_multiplier",
                operation="one_minus_effective_defense_over_effective_defense_plus_flat_base_plus_level_coefficient_times_attacker_level",
                numeric_parameters={"flat_base": 200.0, "attacker_level_coefficient": 10.0},
                source_kind=ENGINE_RULE_SOURCE_KIND,
                source=_source(
                    "DamageFormulaEngineConvention",
                    "defense_multiplier_v1",
                    "Defense multiplier is centralized here pending an admitted raw formula source.",
                ),
                registry_version=ENGINE_RULE_REGISTRY_VERSION,
                applicability=DAMAGE_DEFENSE_RULE_APPLICABILITY,
            ),
            DamageFormulaRuleIR(
                damage_formula_rule_id="damage_formula_rule:engine_convention:resistance_v1",
                rule_kind="resistance_multiplier",
                operation="one_minus_effective_resistance_plus_penetration",
                numeric_parameters={},
                source_kind=ENGINE_RULE_SOURCE_KIND,
                source=_source(
                    "DamageFormulaEngineConvention",
                    "resistance_multiplier_v1",
                    "Resistance multiplier is centralized here pending an admitted raw formula source.",
                ),
                registry_version=ENGINE_RULE_REGISTRY_VERSION,
                applicability=DAMAGE_RESISTANCE_RULE_APPLICABILITY,
            ),
            DamageFormulaRuleIR(
                damage_formula_rule_id="damage_formula_rule:engine_convention:typed_numeric_max_zero_floor_v1",
                rule_kind=ZERO_FLOOR_DYNAMIC_RULE_KIND,
                operation="bind_undeclared_dynamic_hash_to_zero_only_inside_typed_variadic_max_program",
                numeric_parameters={
                    "dynamic_hash": float(ZERO_FLOOR_DYNAMIC_HASH),
                    "numeric_value": 0.0,
                },
                source_kind=ENGINE_RULE_SOURCE_KIND,
                source=_source(
                    "NumericExpressionEngineConvention",
                    "typed_numeric_max_zero_floor_v1",
                    "The current and legacy expression streams consistently use this undeclared first operand as the zero floor of variadic max; the absence of a declared raw binding is preserved as an explicit engine convention.",
                ),
                registry_version=ENGINE_RULE_REGISTRY_VERSION,
                applicability=ZERO_FLOOR_DYNAMIC_RULE_APPLICABILITY,
            ),
            DamageFormulaRuleIR(
                damage_formula_rule_id="damage_formula_rule:engine_convention:typed_numeric_range_max_zero_floor_v1",
                rule_kind=RANGE_ZERO_FLOOR_DYNAMIC_RULE_KIND,
                operation="bind_undeclared_dynamic_hash_to_zero_only_inside_typed_variadic_max_program",
                numeric_parameters={
                    "dynamic_hash": float(RANGE_ZERO_FLOOR_DYNAMIC_HASH),
                    "numeric_value": 0.0,
                },
                source_kind=ENGINE_RULE_SOURCE_KIND,
                source=_source(
                    "NumericExpressionEngineConvention",
                    "typed_numeric_range_max_zero_floor_v1",
                    "TBGD range and clamp programs consistently use this undeclared direct Max operand as their zero floor; the missing raw declaration remains explicit as an engine convention.",
                ),
                registry_version=ENGINE_RULE_REGISTRY_VERSION,
                applicability=RANGE_ZERO_FLOOR_DYNAMIC_RULE_APPLICABILITY,
            ),
        ),
        damage_route_rules=tuple(
            DamageRouteRuleIR(
                damage_route_rule_id=f"damage_route_rule:engine_convention:{family}_v1",
                damage_family=family,
                route_policy="bypass" if family in HP_LOSS_ROUTE_FAMILIES else "absorb",
                operation=(
                    "apply_hp_delta_without_shield_absorption"
                    if family in HP_LOSS_ROUTE_FAMILIES
                    else "consume_priority_ordered_shield_instances_then_apply_hp_remainder"
                ),
                source_kind=ENGINE_RULE_SOURCE_KIND,
                source=_source(
                    "DamageRouteEngineConvention",
                    f"{family}_route_v1",
                    "Damage-family shield routing is an explicit versioned engine convention.",
                ),
                registry_version=ENGINE_RULE_REGISTRY_VERSION,
                applicability=DAMAGE_ROUTE_APPLICABILITY,
            )
            for family in (*NORMAL_DAMAGE_ROUTE_FAMILIES, *HP_LOSS_ROUTE_FAMILIES)
        ),
        shield_priority_rules=(
            ShieldPriorityRuleIR(
                shield_priority_rule_id=SHIELD_PRIORITY_RULE_ID,
                operation="descending_numeric_priority_then_ascending_creation_event_then_instance_identity",
                source_kind=ENGINE_RULE_SOURCE_KIND,
                source=_source(
                    "ShieldPriorityEngineConvention",
                    "priority_then_creation_order_v1",
                    "Shield instance ordering is an explicit versioned engine convention.",
                ),
                registry_version=ENGINE_RULE_REGISTRY_VERSION,
                applicability=SHIELD_PRIORITY_RULE_APPLICABILITY,
            ),
        ),
    )


def engine_rule_admission_reason(
    rule: TimelineRuleIR | ResourceRuleIR | DamageFormulaRuleIR | DamageRouteRuleIR | ShieldPriorityRuleIR,
    *,
    expected_applicability: str,
    numeric_value_required: bool = False,
) -> str:
    if rule.coverage_status != "executable":
        return f"engine_rule_not_executable:{rule.coverage_status}"
    if rule.source_kind != ENGINE_RULE_SOURCE_KIND:
        return f"engine_rule_source_kind_not_admitted:{rule.source_kind}"
    if rule.registry_version != ENGINE_RULE_REGISTRY_VERSION:
        return f"engine_rule_registry_version_mismatch:{rule.registry_version or 'missing'}"
    if rule.applicability != expected_applicability:
        return "engine_rule_applicability_mismatch"
    if numeric_value_required:
        value = getattr(rule, "numeric_value", None)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "engine_rule_numeric_value_missing"
    return ""


def select_damage_formula_rule(
    rule_kind: str,
    registry: EngineRuleRegistry | None = None,
) -> tuple[DamageFormulaRuleIR | None, str]:
    rules = tuple(
        rule for rule in (registry or build_engine_rule_registry()).damage_formula_rules if rule.rule_kind == rule_kind
    )
    if not rules:
        return None, f"damage_formula_engine_rule_missing:{rule_kind}"
    if len(rules) != 1:
        return None, f"damage_formula_engine_rule_ambiguous:{rule_kind}"
    applicability = {
        "defense_multiplier": DAMAGE_DEFENSE_RULE_APPLICABILITY,
        "resistance_multiplier": DAMAGE_RESISTANCE_RULE_APPLICABILITY,
    }.get(rule_kind)
    if applicability is None:
        return None, f"damage_formula_engine_rule_kind_not_admitted:{rule_kind}"
    reason = engine_rule_admission_reason(rules[0], expected_applicability=applicability)
    return (None, reason) if reason else (rules[0], "")


def engine_numeric_binding_source(
    expression: object,
    registry: EngineRuleRegistry | None = None,
) -> tuple[dict[str, object] | None, str]:
    """Return the audited engine binding only for its exact typed-program shape."""

    specifications = (
        (
            ZERO_FLOOR_DYNAMIC_HASH,
            ZERO_FLOOR_DYNAMIC_RULE_KIND,
            ZERO_FLOOR_DYNAMIC_RULE_APPLICABILITY,
        ),
        (
            RANGE_ZERO_FLOOR_DYNAMIC_HASH,
            RANGE_ZERO_FLOOR_DYNAMIC_RULE_KIND,
            RANGE_ZERO_FLOOR_DYNAMIC_RULE_APPLICABILITY,
        ),
    )
    present = tuple(
        specification
        for specification in specifications
        if _contains_zero_floor_dynamic_hash(expression, specification[0])
    )
    if not present:
        return None, ""
    if any(
        not _is_zero_floor_program(expression, dynamic_hash)
        for dynamic_hash, _, _ in present
    ):
        return None, "engine_zero_floor_program_shape_not_admitted"
    rule_registry = registry or build_engine_rule_registry()
    entries: dict[str, object] = {}
    by_hash: dict[str, str] = {}
    for expected_hash, rule_kind, applicability in present:
        rules = tuple(
            rule
            for rule in rule_registry.damage_formula_rules
            if rule.rule_kind == rule_kind
        )
        if not rules:
            return None, "engine_zero_floor_rule_missing"
        if len(rules) != 1:
            return None, "engine_zero_floor_rule_ambiguous"
        rule = rules[0]
        reason = engine_rule_admission_reason(
            rule,
            expected_applicability=applicability,
        )
        if reason:
            return None, reason
        if rule.operation != "bind_undeclared_dynamic_hash_to_zero_only_inside_typed_variadic_max_program":
            return None, "engine_zero_floor_rule_operation_mismatch"
        dynamic_hash = rule.numeric_parameters.get("dynamic_hash")
        numeric_value = rule.numeric_parameters.get("numeric_value")
        if (
            not isinstance(dynamic_hash, (int, float))
            or isinstance(dynamic_hash, bool)
            or int(dynamic_hash) != expected_hash
            or float(dynamic_hash) != float(expected_hash)
            or not isinstance(numeric_value, (int, float))
            or isinstance(numeric_value, bool)
            or float(numeric_value) != 0.0
        ):
            return None, "engine_zero_floor_rule_parameters_mismatch"
        entry_key = rule.damage_formula_rule_id
        entries[entry_key] = {
            "value": 0.0,
            "hash": str(expected_hash),
            "rule_id": rule.damage_formula_rule_id,
            "operation": rule.operation,
            "registry_version": rule.registry_version,
            "source_trace": rule.source.to_json(),
        }
        by_hash[str(expected_hash)] = entry_key
    return {
        "source_type": "engine_numeric_convention",
        "entries": entries,
        "by_hash": by_hash,
        "by_name": {},
    }, ""


def _is_zero_floor_program(expression: object, dynamic_hash: int) -> bool:
    if not isinstance(expression, dict) or expression.get("kind") != "program":
        return False
    instructions = expression.get("instructions")
    if not isinstance(instructions, list):
        return False
    # Each stack entry tracks (zero_hash_count, zero_hashes_admitted_by_max,
    # is_the_unmodified_zero_hash_leaf).  Binding is safe only when every
    # occurrence of the undeclared hash is consumed as a direct operand of a
    # typed ``max`` instruction.  Merely appearing somewhere in the same
    # program as an unrelated max is not sufficient evidence.
    stack: list[tuple[int, int, bool]] = []
    ended = False
    for index, instruction in enumerate(instructions):
        if not isinstance(instruction, dict):
            return False
        opcode = instruction.get("opcode")
        if opcode == "end":
            if index != len(instructions) - 1:
                return False
            ended = True
            continue
        if opcode == "push_dynamic":
            is_zero_hash = instruction.get("hash") == dynamic_hash
            stack.append((1 if is_zero_hash else 0, 0, is_zero_hash))
            continue
        if opcode == "push_fixed":
            stack.append((0, 0, False))
            continue
        if opcode == "negate":
            if not stack:
                return False
            zero_count, admitted_count, _ = stack.pop()
            stack.append((zero_count, admitted_count, False))
            continue
        if opcode == "max":
            operand_count = instruction.get("operand_count")
            if (
                not isinstance(operand_count, int)
                or isinstance(operand_count, bool)
                or operand_count < 2
                or len(stack) < operand_count
            ):
                return False
            operands = stack[-operand_count:]
            del stack[-operand_count:]
            zero_count = sum(item[0] for item in operands)
            admitted_count = sum(item[1] for item in operands) + sum(
                1 for item in operands if item[2]
            )
            stack.append((zero_count, admitted_count, False))
            continue
        if opcode not in {"add", "sub", "mul", "div"} or len(stack) < 2:
            return False
        rhs = stack.pop()
        lhs = stack.pop()
        stack.append((lhs[0] + rhs[0], lhs[1] + rhs[1], False))
    if not ended or len(stack) != 1:
        return False
    zero_count, admitted_count, _ = stack[0]
    return zero_count > 0 and admitted_count == zero_count


def _contains_zero_floor_dynamic_hash(
    expression: object,
    dynamic_hash: int,
) -> bool:
    if not isinstance(expression, dict) or expression.get("kind") != "program":
        return False
    instructions = expression.get("instructions")
    return bool(
        isinstance(instructions, list)
        and any(
            isinstance(instruction, dict)
            and instruction.get("opcode") == "push_dynamic"
            and instruction.get("hash") == dynamic_hash
            for instruction in instructions
        )
    )


def evaluate_defense_multiplier(
    *,
    effective_defense: float,
    attacker_level: int,
    registry: EngineRuleRegistry | None = None,
) -> tuple[float, DamageFormulaRuleIR]:
    rule, reason = select_damage_formula_rule("defense_multiplier", registry)
    if rule is None:
        raise ValueError(reason)
    if rule.operation != "one_minus_effective_defense_over_effective_defense_plus_flat_base_plus_level_coefficient_times_attacker_level":
        raise ValueError("damage_formula_engine_rule_operation_mismatch:defense_multiplier")
    flat_base = rule.numeric_parameters.get("flat_base")
    level_coefficient = rule.numeric_parameters.get("attacker_level_coefficient")
    if not isinstance(flat_base, (int, float)) or not isinstance(level_coefficient, (int, float)):
        raise ValueError("damage_formula_engine_rule_parameters_missing:defense_multiplier")
    effective = max(0.0, float(effective_defense))
    denominator = effective + float(flat_base) + float(level_coefficient) * int(attacker_level)
    return (1.0 if effective <= 0 else 1.0 - effective / denominator), rule


def evaluate_resistance_multiplier(
    *,
    resistance: float,
    penetration: float,
    registry: EngineRuleRegistry | None = None,
) -> tuple[float, DamageFormulaRuleIR]:
    rule, reason = select_damage_formula_rule("resistance_multiplier", registry)
    if rule is None:
        raise ValueError(reason)
    if rule.operation != "one_minus_effective_resistance_plus_penetration":
        raise ValueError("damage_formula_engine_rule_operation_mismatch:resistance_multiplier")
    return 1.0 - float(resistance) + float(penetration), rule


def select_damage_route_rule(
    damage_family: str,
    registry: EngineRuleRegistry | None = None,
) -> tuple[DamageRouteRuleIR | None, str]:
    rules = tuple(
        rule for rule in (registry or build_engine_rule_registry()).damage_route_rules if rule.damage_family == damage_family
    )
    if not rules:
        return None, f"damage_route_engine_rule_missing:{damage_family}"
    if len(rules) != 1:
        return None, f"damage_route_engine_rule_ambiguous:{damage_family}"
    reason = engine_rule_admission_reason(rules[0], expected_applicability=DAMAGE_ROUTE_APPLICABILITY)
    if reason:
        return None, reason
    expected_policy = "bypass" if damage_family in HP_LOSS_ROUTE_FAMILIES else "absorb"
    if rules[0].route_policy != expected_policy:
        return None, "damage_route_engine_rule_policy_mismatch"
    return rules[0], ""


def select_shield_priority_rule(
    rule_id: str,
    registry_version: str,
    registry: EngineRuleRegistry | None = None,
) -> tuple[ShieldPriorityRuleIR | None, str]:
    rules = tuple(
        rule
        for rule in (registry or build_engine_rule_registry()).shield_priority_rules
        if rule.shield_priority_rule_id == rule_id
    )
    if not rules:
        return None, f"shield_priority_engine_rule_missing:{rule_id or 'missing'}"
    if len(rules) != 1:
        return None, f"shield_priority_engine_rule_ambiguous:{rule_id}"
    if registry_version != ENGINE_RULE_REGISTRY_VERSION:
        return None, f"shield_priority_engine_rule_version_mismatch:{registry_version or 'missing'}"
    reason = engine_rule_admission_reason(rules[0], expected_applicability=SHIELD_PRIORITY_RULE_APPLICABILITY)
    return (None, reason) if reason else (rules[0], "")


def _source(raw_type: str, raw_id: str, reason: str) -> IRSource:
    return IRSource(
        source_path="simulator_v8_clean_core/rules/engine_rule_registry.py",
        raw_type=raw_type,
        raw_id=raw_id,
        evidence={
            "source_category": ENGINE_RULE_SOURCE_KIND,
            "registry_version": ENGINE_RULE_REGISTRY_VERSION,
            "reason": reason,
        },
    )
