from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TypeAlias

from ..equipment.models import (
    EquipmentAssemblyDiagnostic,
    EquipmentDefinitionKey,
    EquipmentDefinitionResolution,
    RelicAssemblySelection,
    RelicDomainDefinitionIR,
    RelicSetActivationContributor,
    RelicSetActivationDecision,
    RelicSetDefinitionIR,
    RelicSetThresholdIR,
    RelicSlotDefinitionIR,
    RelicTemplateDefinitionIR,
)
from ..rules.rulebook import RuleBook


RelicSetResolution: TypeAlias = (
    EquipmentDefinitionResolution[RelicTemplateDefinitionIR]
    | EquipmentDefinitionResolution[RelicSlotDefinitionIR]
    | EquipmentDefinitionResolution[RelicSetDefinitionIR]
    | EquipmentDefinitionResolution[RelicDomainDefinitionIR]
    | EquipmentDefinitionResolution[RelicSetThresholdIR]
)


@dataclass(frozen=True)
class _AdmittedRelicSetRecord:
    selection: RelicAssemblySelection
    template: RelicTemplateDefinitionIR
    relic_set: RelicSetDefinitionIR
    domain: RelicDomainDefinitionIR
    thresholds: tuple[RelicSetThresholdIR, ...]


def assemble_relic_set_activations(
    rules: RuleBook,
    selections: tuple[RelicAssemblySelection, ...],
) -> tuple[
    tuple[RelicSetActivationDecision, ...],
    tuple[EquipmentAssemblyDiagnostic, ...],
]:
    """Compute all thresholds from canonical set definitions for admitted relics.

    The function deliberately re-closes every selection against the RuleBook.
    A caller must discard the entire result when diagnostics are returned.
    """

    if not isinstance(rules, RuleBook):
        raise TypeError("rules must be a RuleBook")
    if not isinstance(selections, tuple) or not all(
        isinstance(item, RelicAssemblySelection) for item in selections
    ):
        raise TypeError("selections must be a tuple of RelicAssemblySelection")

    diagnostics: list[EquipmentAssemblyDiagnostic] = []
    records: list[_AdmittedRelicSetRecord] = []
    seen_instances: dict[str, RelicAssemblySelection] = {}
    seen_slots: dict[EquipmentDefinitionKey, RelicAssemblySelection] = {}
    for selection in selections:
        existing_instance = seen_instances.get(selection.instance_id)
        if existing_instance is not None:
            reason = (
                "relic_set_instance_identity_conflict"
                if existing_instance.instance_fingerprint != selection.instance_fingerprint
                else "relic_set_instance_id_reused"
            )
            diagnostics.append(_diagnostic(selection, reason, selection.template_key))
            continue
        seen_instances[selection.instance_id] = selection
        existing_slot = seen_slots.get(selection.slot_key)
        if existing_slot is not None:
            diagnostics.append(
                _diagnostic(selection, "relic_set_slot_reused", selection.slot_key)
            )
            continue
        seen_slots[selection.slot_key] = selection

        template_resolution = rules.relic_template_definition(
            selection.template_key.definition_identity
        )
        template = template_resolution.value
        if template_resolution.resolution_status != "resolved" or template is None:
            diagnostics.append(_resolution_diagnostic(selection, template_resolution))
            continue
        if (
            template.definition_key != selection.template_key
            or template.slot_key != selection.slot_key
            or template.source != selection.template_source
            or template.publication_status != "published"
            or template.mode != "BASIC"
        ):
            diagnostics.append(
                _diagnostic(selection, "relic_set_selection_template_identity_mismatch", selection.template_key)
            )
            continue

        slot_resolution = rules.relic_slot_definition(selection.slot_key.definition_identity)
        slot = slot_resolution.value
        if slot_resolution.resolution_status != "resolved" or slot is None:
            diagnostics.append(_resolution_diagnostic(selection, slot_resolution))
            continue
        if (
            slot.definition_key != selection.slot_key
            or slot.source != selection.slot_source
            or slot.domain_key != template.domain_key
        ):
            diagnostics.append(
                _diagnostic(selection, "relic_set_selection_slot_identity_mismatch", selection.slot_key)
            )
            continue

        set_resolution = rules.relic_set_definition(template.set_key.definition_identity)
        relic_set = set_resolution.value
        if set_resolution.resolution_status != "resolved" or relic_set is None:
            diagnostics.append(_resolution_diagnostic(selection, set_resolution))
            continue
        if (
            relic_set.definition_key != template.set_key
            or relic_set.domain_key != template.domain_key
            or relic_set.publication_status != "published"
            or selection.slot_key not in relic_set.slot_keys
            or selection.template_key not in relic_set.template_keys
        ):
            reason = (
                "relic_set_publication_status_not_admitted"
                if relic_set.publication_status != "published"
                else "relic_set_template_membership_mismatch"
            )
            diagnostics.append(
                _diagnostic(selection, reason, template.set_key)
            )
            continue

        domain_resolution = rules.relic_domain_definition(template.domain_key.definition_identity)
        domain = domain_resolution.value
        if domain_resolution.resolution_status != "resolved" or domain is None:
            diagnostics.append(_resolution_diagnostic(selection, domain_resolution))
            continue
        if (
            domain.definition_key != template.domain_key
            or relic_set.definition_key not in domain.set_keys
            or selection.slot_key not in domain.slot_keys
        ):
            diagnostics.append(
                _diagnostic(selection, "relic_set_domain_membership_mismatch", template.domain_key)
            )
            continue

        thresholds: list[RelicSetThresholdIR] = []
        threshold_counts: set[int] = set()
        for threshold_key in relic_set.threshold_keys:
            threshold_resolution = rules.relic_set_threshold(
                threshold_key.definition_identity
            )
            threshold = threshold_resolution.value
            if threshold_resolution.resolution_status != "resolved" or threshold is None:
                diagnostics.append(_resolution_diagnostic(selection, threshold_resolution))
                continue
            if (
                threshold.definition_key != threshold_key
                or threshold.set_key != relic_set.definition_key
                or threshold.require_count in threshold_counts
            ):
                diagnostics.append(
                    _diagnostic(selection, "relic_set_threshold_identity_mismatch", threshold_key)
                )
                continue
            threshold_counts.add(threshold.require_count)
            thresholds.append(threshold)
        if len(thresholds) != len(relic_set.threshold_keys):
            continue

        sources = (
            selection.template_source,
            selection.slot_source,
            domain.source,
            relic_set.source,
            *(item.source for item in thresholds),
        )
        fingerprints = tuple(
            source.evidence.get("source_fingerprint") for source in sources
        )
        if any(item != fingerprints[0] for item in fingerprints[1:]):
            diagnostics.append(
                _diagnostic(selection, "relic_set_source_fingerprint_mismatch", relic_set.definition_key)
            )
            continue
        records.append(
            _AdmittedRelicSetRecord(
                selection=selection,
                template=template,
                relic_set=relic_set,
                domain=domain,
                thresholds=tuple(thresholds),
            )
        )

    if diagnostics:
        return (), tuple(sorted(diagnostics, key=lambda item: item.diagnostic_id))

    grouped: dict[
        tuple[EquipmentDefinitionKey, EquipmentDefinitionKey],
        list[_AdmittedRelicSetRecord],
    ] = defaultdict(list)
    for record in records:
        grouped[(record.domain.definition_key, record.relic_set.definition_key)].append(record)

    decisions: list[RelicSetActivationDecision] = []
    for (domain_key, set_key), group in sorted(
        grouped.items(),
        key=lambda item: (item[0][0].stable_id, item[0][1].stable_id),
    ):
        first_record = group[0]
        relic_set = first_record.relic_set
        domain = first_record.domain
        thresholds = first_record.thresholds
        if any(
            record.relic_set != relic_set
            or record.domain != domain
            or record.thresholds != thresholds
            for record in group[1:]
        ):
            return (), (
                _diagnostic(
                    first_record.selection,
                    "relic_set_definition_identity_conflict",
                    set_key,
                ),
            )
        contributors = tuple(
            RelicSetActivationContributor(
                instance_id=selection.instance_id,
                instance_fingerprint=selection.instance_fingerprint,
                selection_fingerprint=selection.selection_fingerprint,
                template_key=selection.template_key,
                slot_key=selection.slot_key,
                template_source=selection.template_source,
            )
            for record in group
            for selection in (record.selection,)
        )
        for threshold in sorted(
            thresholds,
            key=lambda item: (item.require_count, item.definition_key.stable_id),
        ):
            matched_count = len(contributors)
            decisions.append(
                RelicSetActivationDecision(
                    decision_id=(
                        "relic_set_activation:"
                        f"{domain_key.definition_identity}:"
                        f"{set_key.definition_identity}:"
                        f"{threshold.definition_key.definition_identity}"
                    ),
                    threshold_key=threshold.definition_key,
                    set_key=set_key,
                    domain_key=domain_key,
                    activation_status=(
                        "active"
                        if matched_count >= threshold.require_count
                        else "inactive"
                    ),
                    matched_count=matched_count,
                    required_count=threshold.require_count,
                    missing_count=max(0, threshold.require_count - matched_count),
                    contributors=contributors,
                    domain_source=domain.source,
                    set_source=relic_set.source,
                    threshold_source=threshold.source,
                )
            )
    return tuple(decisions), ()


def _diagnostic(
    selection: RelicAssemblySelection,
    reason: str,
    requested_key: EquipmentDefinitionKey,
) -> EquipmentAssemblyDiagnostic:
    return EquipmentAssemblyDiagnostic(
        diagnostic_id=(
            f"relic_set_assembly:{selection.instance_id}:{reason}"
        ),
        reason=reason,
        requested_key=requested_key,
    )


def _resolution_diagnostic(
    selection: RelicAssemblySelection,
    resolution: RelicSetResolution,
) -> EquipmentAssemblyDiagnostic:
    return EquipmentAssemblyDiagnostic(
        diagnostic_id=(
            f"relic_set_assembly:{selection.instance_id}:"
            f"{resolution.blocked_reason or 'relic_set_definition_blocked'}"
        ),
        reason=resolution.blocked_reason or "relic_set_definition_blocked",
        requested_key=resolution.requested_key,
        candidates=resolution.candidates,
    )
