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
    RelicTemplateDefinitionIR,
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
