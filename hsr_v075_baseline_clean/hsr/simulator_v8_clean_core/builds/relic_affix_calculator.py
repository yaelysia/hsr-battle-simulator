from __future__ import annotations

from dataclasses import dataclass
from ..build_types import StatCalculation
from ..equipment.models import (
    EquipmentDefinitionKey,
    EquipmentDefinitionResolution,
    EquipmentResolutionCandidate,
    RelicInstanceInput,
    RelicMainAffixComputation,
    RelicMainAffixDefinitionIR,
    RelicMainAffixGroupDefinitionIR,
    RelicSlotDefinitionIR,
    RelicSubAffixComputation,
    RelicSubAffixDefinitionIR,
    RelicSubAffixGroupDefinitionIR,
    RelicSubAffixRollInput,
    RelicTemplateDefinitionIR,
    relic_sub_affix_exact_value,
)
from ..ir_types import JSONValue
from ..rules.rulebook import RuleBook


@dataclass(frozen=True)
class RelicMainAffixAdmissionIssue:
    """One fail-closed main-affix admission rejection.

    Issues never carry a computed value; a blocked main affix leaves no
    intermediate result behind.
    """

    reason: str
    requested_key: EquipmentDefinitionKey | None = None
    candidates: tuple[EquipmentResolutionCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("main affix admission issue requires a reason")
        if self.requested_key is not None and not isinstance(
            self.requested_key,
            EquipmentDefinitionKey,
        ):
            raise TypeError("main affix admission issue key must be typed")
        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "reason": self.reason,
            "requested_key": (
                self.requested_key.to_json()
                if self.requested_key is not None
                else None
            ),
            "candidates": [candidate.to_json() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class RelicSubAffixAdmissionIssue:
    """One fail-closed rejection for the complete sub-affix tuple."""

    reason: str
    requested_key: EquipmentDefinitionKey | None = None
    candidates: tuple[EquipmentResolutionCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("sub affix admission issue requires a reason")
        if self.requested_key is not None and not isinstance(
            self.requested_key,
            EquipmentDefinitionKey,
        ):
            raise TypeError("sub affix admission issue key must be typed")
        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "reason": self.reason,
            "requested_key": (
                self.requested_key.to_json()
                if self.requested_key is not None
                else None
            ),
            "candidates": [candidate.to_json() for candidate in self.candidates],
        }


def admit_relic_main_affix(
    rules: RuleBook,
    template: RelicTemplateDefinitionIR,
    slot_definition: RelicSlotDefinitionIR,
    instance: RelicInstanceInput,
) -> tuple[RelicMainAffixComputation | None, tuple[RelicMainAffixAdmissionIssue, ...]]:
    """Admit one instance main affix and compute its exact value.

    Legality is the intersection of three source-backed relations: the
    template main-affix group must contain the affix definition, the real
    slot of the template must allow the affix property, and the affix group
    identity must match the template group (which binds the rarity tier).
    Any missing relation is fail-closed with zero intermediate value.
    """

    if not isinstance(rules, RuleBook):
        raise TypeError("rules must be a RuleBook")
    if not isinstance(template, RelicTemplateDefinitionIR):
        raise TypeError("template must be a RelicTemplateDefinitionIR")
    if not isinstance(slot_definition, RelicSlotDefinitionIR):
        raise TypeError("slot_definition must be a RelicSlotDefinitionIR")
    if not isinstance(instance, RelicInstanceInput):
        raise TypeError("instance must be a RelicInstanceInput")

    identity_issue = _identity_issue(template, slot_definition, instance)
    if identity_issue is not None:
        return None, (identity_issue,)

    if instance.level < 0 or instance.level > template.max_level:
        return None, (
            RelicMainAffixAdmissionIssue(
                reason="relic_level_outside_template_bounds",
                requested_key=instance.template_key,
            ),
        )

    issues: list[RelicMainAffixAdmissionIssue] = []
    group_resolution = rules.relic_main_affix_group_definition(
        template.main_affix_group_key.definition_identity
    )
    group, group_issues = _resolved(group_resolution)
    issues.extend(group_issues)
    affix_resolution = rules.relic_main_affix_definition(
        instance.main_affix_key.definition_identity
    )
    affix, affix_issues = _resolved(affix_resolution)
    issues.extend(affix_issues)
    if group is None or affix is None:
        return None, tuple(issues)
    if group.definition_key != template.main_affix_group_key:
        return None, (
            RelicMainAffixAdmissionIssue(
                reason="relic_main_affix_group_identity_mismatch",
                requested_key=template.main_affix_group_key,
                candidates=group_resolution.candidates,
            ),
        )

    if instance.main_affix_key not in group.affix_keys:
        return None, (
            RelicMainAffixAdmissionIssue(
                reason="relic_main_affix_not_in_template_group",
                requested_key=instance.main_affix_key,
                candidates=affix_resolution.candidates,
            ),
        )
    if affix.group_key != group.definition_key:
        return None, (
            RelicMainAffixAdmissionIssue(
                reason="relic_main_affix_group_membership_mismatch",
                requested_key=instance.main_affix_key,
                candidates=affix_resolution.candidates,
            ),
        )
    if affix.property_type not in group.property_types:
        return None, (
            RelicMainAffixAdmissionIssue(
                reason="relic_main_affix_property_not_in_group_projection",
                requested_key=instance.main_affix_key,
                candidates=affix_resolution.candidates,
            ),
        )
    if len(group.rarity_types) != 1:
        return None, (
            RelicMainAffixAdmissionIssue(
                reason="relic_main_affix_group_rarity_ambiguous",
                requested_key=group.definition_key,
                candidates=group_resolution.candidates,
            ),
        )
    if template.rarity != group.rarity_types[0]:
        return None, (
            RelicMainAffixAdmissionIssue(
                reason="relic_main_affix_group_rarity_mismatch",
                requested_key=template.definition_key,
            ),
        )
    if affix.property_type not in slot_definition.allowed_main_property_types:
        return None, (
            RelicMainAffixAdmissionIssue(
                reason="relic_main_affix_property_not_allowed_for_slot",
                requested_key=instance.main_affix_key,
                candidates=affix_resolution.candidates,
            ),
        )

    sources = (
        template.source,
        slot_definition.source,
        group.source,
        affix.source,
    )
    fingerprints = tuple(
        source.evidence.get("source_fingerprint") for source in sources
    )
    if any(item != fingerprints[0] for item in fingerprints[1:]):
        return None, (
            RelicMainAffixAdmissionIssue(
                reason="relic_main_affix_source_fingerprint_mismatch",
                requested_key=instance.main_affix_key,
                candidates=affix_resolution.candidates,
            ),
        )

    calculation = StatCalculation(
        "linear_growth",
        affix.base_value,
        affix.level_add,
        instance.level,
    )
    computation = RelicMainAffixComputation(
        template_key=template.definition_key,
        slot_key=slot_definition.definition_key,
        group_key=group.definition_key,
        affix_key=affix.definition_key,
        property_type=affix.property_type,
        level=instance.level,
        exact_value=calculation.exact_value,
        calculation=calculation,
        template_source=template.source,
        slot_source=slot_definition.source,
        group_source=group.source,
        affix_source=affix.source,
    )
    return computation, ()


def admit_relic_sub_affixes(
    rules: RuleBook,
    template: RelicTemplateDefinitionIR,
    instance: RelicInstanceInput,
    main_affix: RelicMainAffixComputation,
) -> tuple[
    tuple[RelicSubAffixComputation, ...] | None,
    tuple[RelicSubAffixAdmissionIssue, ...],
]:
    """Admit and compute an already-finished relic's complete sub-affix tuple."""

    if not isinstance(rules, RuleBook):
        raise TypeError("rules must be a RuleBook")
    if not isinstance(template, RelicTemplateDefinitionIR):
        raise TypeError("template must be a RelicTemplateDefinitionIR")
    if not isinstance(instance, RelicInstanceInput):
        raise TypeError("instance must be a RelicInstanceInput")
    if not isinstance(main_affix, RelicMainAffixComputation):
        raise TypeError("main_affix must be a RelicMainAffixComputation")
    template_resolution = rules.relic_template_definition(
        instance.template_key.definition_identity
    )
    if (
        template_resolution.resolution_status != "resolved"
        or template_resolution.value is None
    ):
        return None, (
            RelicSubAffixAdmissionIssue(
                reason=(
                    template_resolution.blocked_reason
                    or "relic_sub_affix_template_definition_blocked"
                ),
                requested_key=template_resolution.requested_key,
                candidates=template_resolution.candidates,
            ),
        )
    canonical_template = template_resolution.value
    if canonical_template.definition_key != instance.template_key:
        return None, (
            RelicSubAffixAdmissionIssue(
                reason="relic_sub_affix_template_identity_mismatch",
                requested_key=instance.template_key,
                candidates=template_resolution.candidates,
            ),
        )
    if template != canonical_template:
        return None, (
            RelicSubAffixAdmissionIssue(
                reason="relic_sub_affix_template_not_canonical",
                requested_key=instance.template_key,
                candidates=template_resolution.candidates,
            ),
        )
    template = canonical_template
    identity_issue = _sub_affix_main_identity_issue(
        template,
        instance,
        main_affix,
    )
    if identity_issue is not None:
        return None, (identity_issue,)
    canonical_main, canonical_main_issues = _canonical_main_affix(
        rules,
        template,
        instance,
    )
    if canonical_main_issues:
        return None, canonical_main_issues
    if canonical_main is None:
        return None, (
            RelicSubAffixAdmissionIssue(
                reason="relic_sub_affix_canonical_main_not_admitted",
                requested_key=instance.main_affix_key,
            ),
        )
    main_computation_issue = _main_computation_issue(
        canonical_main,
        main_affix,
    )
    if main_computation_issue is not None:
        return None, (main_computation_issue,)

    rolls = instance.sub_affix_rolls
    if len(rolls) > 4:
        return None, (
            RelicSubAffixAdmissionIssue(
                reason="relic_sub_affix_property_limit_exceeded",
                requested_key=template.sub_affix_group_key,
            ),
        )
    roll_keys = tuple(roll.affix_key for roll in rolls)
    if len(roll_keys) != len(set(roll_keys)):
        return None, (
            RelicSubAffixAdmissionIssue(
                reason="relic_sub_affix_duplicate_affix",
                requested_key=template.sub_affix_group_key,
            ),
        )

    group_resolution = rules.relic_sub_affix_group_definition(
        template.sub_affix_group_key.definition_identity
    )
    if (
        group_resolution.resolution_status != "resolved"
        or group_resolution.value is None
    ):
        return None, (
            RelicSubAffixAdmissionIssue(
                reason=(
                    group_resolution.blocked_reason
                    or "relic_sub_affix_group_definition_blocked"
                ),
                requested_key=group_resolution.requested_key,
                candidates=group_resolution.candidates,
            ),
        )
    group = group_resolution.value
    if group.definition_key != template.sub_affix_group_key:
        return None, (
            RelicSubAffixAdmissionIssue(
                reason="relic_sub_affix_group_identity_mismatch",
                requested_key=template.sub_affix_group_key,
                candidates=group_resolution.candidates,
            ),
        )

    resolved: list[
        tuple[
            RelicSubAffixRollInput,
            RelicSubAffixDefinitionIR,
            EquipmentDefinitionResolution[RelicSubAffixDefinitionIR],
        ]
    ] = []
    issues: list[RelicSubAffixAdmissionIssue] = []
    for roll in rolls:
        resolution = rules.relic_sub_affix_definition(
            roll.affix_key.definition_identity
        )
        if resolution.resolution_status != "resolved" or resolution.value is None:
            issues.append(
                RelicSubAffixAdmissionIssue(
                    reason=(
                        resolution.blocked_reason
                        or "relic_sub_affix_definition_blocked"
                    ),
                    requested_key=resolution.requested_key,
                    candidates=resolution.candidates,
                )
            )
            continue
        affix = resolution.value
        if roll.affix_key not in group.affix_keys:
            issues.append(
                RelicSubAffixAdmissionIssue(
                    reason="relic_sub_affix_not_in_template_group",
                    requested_key=roll.affix_key,
                    candidates=resolution.candidates,
                )
            )
        elif affix.group_key != group.definition_key:
            issues.append(
                RelicSubAffixAdmissionIssue(
                    reason="relic_sub_affix_group_membership_mismatch",
                    requested_key=roll.affix_key,
                    candidates=resolution.candidates,
                )
            )
        elif affix.property_type not in group.property_types:
            issues.append(
                RelicSubAffixAdmissionIssue(
                    reason="relic_sub_affix_property_not_in_group_projection",
                    requested_key=roll.affix_key,
                    candidates=resolution.candidates,
                )
            )
        if roll.count <= 0:
            issues.append(
                RelicSubAffixAdmissionIssue(
                    reason="relic_sub_affix_count_not_positive",
                    requested_key=roll.affix_key,
                )
            )
        if roll.step < 0:
            issues.append(
                RelicSubAffixAdmissionIssue(
                    reason="relic_sub_affix_step_negative",
                    requested_key=roll.affix_key,
                )
            )
        elif roll.step > roll.count * affix.step_count:
            issues.append(
                RelicSubAffixAdmissionIssue(
                    reason="relic_sub_affix_step_exceeds_cumulative_bound",
                    requested_key=roll.affix_key,
                )
            )
        resolved.append((roll, affix, resolution))
    if issues:
        return None, tuple(issues)

    properties = tuple(affix.property_type for _, affix, _ in resolved)
    if len(properties) != len(set(properties)):
        return None, (
            RelicSubAffixAdmissionIssue(
                reason="relic_sub_affix_duplicate_property",
                requested_key=group.definition_key,
            ),
        )
    if canonical_main.property_type in properties:
        return None, (
            RelicSubAffixAdmissionIssue(
                reason="relic_main_sub_affix_property_conflict",
                requested_key=canonical_main.affix_key,
            ),
        )

    sources = (
        template.source,
        group.source,
        *(affix.source for _, affix, _ in resolved),
    )
    fingerprints = tuple(
        source.evidence.get("source_fingerprint") for source in sources
    )
    if any(item != fingerprints[0] for item in fingerprints[1:]):
        return None, (
            RelicSubAffixAdmissionIssue(
                reason="relic_sub_affix_source_fingerprint_mismatch",
                requested_key=group.definition_key,
                candidates=group_resolution.candidates,
            ),
        )

    computations = tuple(
        RelicSubAffixComputation(
            template_key=template.definition_key,
            group_key=group.definition_key,
            affix_key=affix.definition_key,
            property_type=affix.property_type,
            count=roll.count,
            step=roll.step,
            base_value=affix.base_value,
            step_value=affix.step_value,
            step_count=affix.step_count,
            exact_value=relic_sub_affix_exact_value(
                affix.base_value,
                roll.count,
                affix.step_value,
                roll.step,
            ),
            template_source=template.source,
            group_source=group.source,
            affix_source=affix.source,
        )
        for roll, affix, _ in resolved
    )
    return computations, ()


def _sub_affix_main_identity_issue(
    template: RelicTemplateDefinitionIR,
    instance: RelicInstanceInput,
    main_affix: RelicMainAffixComputation,
) -> RelicSubAffixAdmissionIssue | None:
    checks = (
        (
            instance.template_key != template.definition_key,
            "relic_sub_affix_instance_template_mismatch",
            instance.template_key,
        ),
        (
            instance.slot_key != template.slot_key,
            "relic_sub_affix_instance_slot_mismatch",
            instance.slot_key,
        ),
        (
            main_affix.template_key != template.definition_key,
            "relic_sub_affix_main_template_mismatch",
            main_affix.template_key,
        ),
        (
            main_affix.slot_key != template.slot_key,
            "relic_sub_affix_main_slot_mismatch",
            main_affix.slot_key,
        ),
        (
            main_affix.level != instance.level,
            "relic_sub_affix_main_level_mismatch",
            main_affix.affix_key,
        ),
        (
            main_affix.affix_key != instance.main_affix_key,
            "relic_sub_affix_main_key_mismatch",
            main_affix.affix_key,
        ),
    )
    for rejected, reason, requested_key in checks:
        if rejected:
            return RelicSubAffixAdmissionIssue(
                reason=reason,
                requested_key=requested_key,
            )
    return None


def _canonical_main_affix(
    rules: RuleBook,
    template: RelicTemplateDefinitionIR,
    instance: RelicInstanceInput,
) -> tuple[
    RelicMainAffixComputation | None,
    tuple[RelicSubAffixAdmissionIssue, ...],
]:
    slot_resolution = rules.relic_slot_definition(
        template.slot_key.definition_identity
    )
    if (
        slot_resolution.resolution_status != "resolved"
        or slot_resolution.value is None
    ):
        return None, (
            RelicSubAffixAdmissionIssue(
                reason=(
                    slot_resolution.blocked_reason
                    or "relic_sub_affix_slot_definition_blocked"
                ),
                requested_key=slot_resolution.requested_key,
                candidates=slot_resolution.candidates,
            ),
        )
    computation, issues = admit_relic_main_affix(
        rules,
        template,
        slot_resolution.value,
        instance,
    )
    return computation, tuple(
        RelicSubAffixAdmissionIssue(
            reason=issue.reason,
            requested_key=issue.requested_key,
            candidates=issue.candidates,
        )
        for issue in issues
    )


def _main_computation_issue(
    canonical: RelicMainAffixComputation,
    supplied: RelicMainAffixComputation,
) -> RelicSubAffixAdmissionIssue | None:
    if supplied.group_key != canonical.group_key:
        reason = "relic_sub_affix_main_group_mismatch"
    elif supplied.property_type != canonical.property_type:
        reason = "relic_sub_affix_main_property_mismatch"
    elif (
        supplied.exact_value != canonical.exact_value
        or supplied.calculation != canonical.calculation
    ):
        reason = "relic_sub_affix_main_calculation_mismatch"
    else:
        canonical_sources = (
            canonical.template_source,
            canonical.slot_source,
            canonical.group_source,
            canonical.affix_source,
        )
        supplied_sources = (
            supplied.template_source,
            supplied.slot_source,
            supplied.group_source,
            supplied.affix_source,
        )
        canonical_fingerprints = tuple(
            source.evidence.get("source_fingerprint")
            for source in canonical_sources
        )
        supplied_fingerprints = tuple(
            source.evidence.get("source_fingerprint")
            for source in supplied_sources
        )
        if supplied_fingerprints != canonical_fingerprints:
            reason = "relic_sub_affix_main_source_fingerprint_mismatch"
        elif supplied_sources != canonical_sources:
            reason = "relic_sub_affix_main_source_mismatch"
        elif supplied.computation_fingerprint != canonical.computation_fingerprint:
            reason = "relic_sub_affix_main_computation_fingerprint_mismatch"
        else:
            return None
    return RelicSubAffixAdmissionIssue(
        reason=reason,
        requested_key=supplied.affix_key,
    )


def _identity_issue(
    template: RelicTemplateDefinitionIR,
    slot_definition: RelicSlotDefinitionIR,
    instance: RelicInstanceInput,
) -> RelicMainAffixAdmissionIssue | None:
    """Close the calculator's own identity relations before any lookup."""

    if instance.template_key != template.definition_key:
        return RelicMainAffixAdmissionIssue(
            reason="relic_main_affix_template_identity_mismatch",
            requested_key=instance.template_key,
        )
    if instance.slot_key != template.slot_key:
        return RelicMainAffixAdmissionIssue(
            reason="relic_main_affix_instance_slot_mismatch",
            requested_key=instance.slot_key,
        )
    if slot_definition.definition_key != template.slot_key:
        return RelicMainAffixAdmissionIssue(
            reason="relic_main_affix_slot_definition_mismatch",
            requested_key=slot_definition.definition_key,
        )
    return None


def _resolved(
    resolution: EquipmentDefinitionResolution[
        RelicMainAffixGroupDefinitionIR | RelicMainAffixDefinitionIR
    ],
) -> tuple[
    RelicMainAffixGroupDefinitionIR | RelicMainAffixDefinitionIR | None,
    tuple[RelicMainAffixAdmissionIssue, ...],
]:
    if (
        resolution.resolution_status == "resolved"
        and resolution.value is not None
    ):
        return resolution.value, ()
    return None, (
        RelicMainAffixAdmissionIssue(
            reason=resolution.blocked_reason or "equipment_definition_blocked",
            requested_key=resolution.requested_key,
            candidates=resolution.candidates,
        ),
    )
