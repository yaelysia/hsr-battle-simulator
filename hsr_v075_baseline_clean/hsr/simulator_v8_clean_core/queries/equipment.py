from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from ..builds.character_assembler import assemble_character_build
from ..builds.models import CharacterBuildAssemblyResult, CharacterBuildInput
from ..core.model import BattleTransition
from ..core.source_audit import RuntimeSourceAuditor
from ..equipment.models import (
    EquipmentDefinitionKey,
    EquipmentDefinitionResolution,
    RelicMainAffixDefinitionIR,
    RelicMainAffixGroupDefinitionIR,
    RelicSlotDefinitionIR,
    RelicSubAffixDefinitionIR,
    RelicSubAffixGroupDefinitionIR,
)
from ..immutable_json import freeze_json, thaw_json
from ..ir_types import JSONValue
from ..rules.rulebook import RuleBook


QueryStatus = Literal["resolved", "blocked"]
CatalogKind = Literal["light_cone", "relic_template", "relic_set"]
DefinitionQueryKind = Literal[
    "light_cone",
    "relic_template",
    "relic_set",
    "relic_set_threshold",
]
MAX_PAGE_SIZE = 100


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_query_shape(
    status: object,
    blocked_reason: object,
    *,
    resolved_payload: bool,
) -> None:
    if status not in {"resolved", "blocked"}:
        raise ValueError("invalid equipment query resolution_status")
    if not isinstance(blocked_reason, str):
        raise TypeError("blocked_reason must be a string")
    if status == "resolved":
        if blocked_reason or not resolved_payload:
            raise ValueError("resolved equipment query requires one payload and no reason")
    elif not blocked_reason or resolved_payload:
        raise ValueError("blocked equipment query requires a reason and no payload")


def _frozen(value: JSONValue) -> JSONValue:
    return cast(JSONValue, freeze_json(value))


def _thawed(value: JSONValue) -> JSONValue:
    return cast(JSONValue, thaw_json(value))


@dataclass(frozen=True)
class EquipmentDefinitionItemView:
    definition_kind: str
    definition_identity: str
    stable_id: str
    coverage_status: str
    snapshot: JSONValue

    def __post_init__(self) -> None:
        _require_text(self.definition_kind, "definition_kind")
        _require_text(self.definition_identity, "definition_identity")
        _require_text(self.stable_id, "stable_id")
        _require_text(self.coverage_status, "coverage_status")
        if not isinstance(self.snapshot, Mapping):
            raise TypeError("equipment definition snapshot must be a JSON object")
        raw_key = self.snapshot.get("definition_key")
        key = EquipmentDefinitionKey.from_json(raw_key)
        if (
            key.definition_kind != self.definition_kind
            or key.definition_identity != self.definition_identity
            or key.stable_id != self.stable_id
        ):
            raise ValueError("equipment definition view identity mismatch")
        object.__setattr__(self, "snapshot", _frozen(self.snapshot))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_kind": self.definition_kind,
            "definition_identity": self.definition_identity,
            "stable_id": self.stable_id,
            "coverage_status": self.coverage_status,
            "snapshot": _thawed(self.snapshot),
        }


@dataclass(frozen=True)
class EquipmentDefinitionView:
    resolution_status: QueryStatus
    expected_kind: str
    requested_identity: str
    value: EquipmentDefinitionItemView | None = None
    candidates: tuple[JSONValue, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        _require_text(self.expected_kind, "expected_kind")
        if not isinstance(self.requested_identity, str):
            raise TypeError("requested_identity must be a string")
        if self.value is not None and not isinstance(
            self.value,
            EquipmentDefinitionItemView,
        ):
            raise TypeError("equipment definition query value has the wrong type")
        _require_query_shape(
            self.resolution_status,
            self.blocked_reason,
            resolved_payload=self.value is not None,
        )
        if self.value is not None and self.value.definition_kind != self.expected_kind:
            raise ValueError("equipment definition query kind mismatch")
        object.__setattr__(
            self,
            "candidates",
            tuple(_frozen(candidate) for candidate in self.candidates),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_status": self.resolution_status,
            "expected_kind": self.expected_kind,
            "requested_identity": self.requested_identity,
            "value": self.value.to_json() if self.value is not None else None,
            "candidates": [_thawed(candidate) for candidate in self.candidates],
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class EquipmentCatalogPageView:
    resolution_status: QueryStatus
    catalog_kind: CatalogKind
    page: int
    page_size: int
    total_items: int
    total_pages: int
    items: tuple[EquipmentDefinitionItemView, ...] = ()
    candidates: tuple[JSONValue, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if self.catalog_kind not in {"light_cone", "relic_template", "relic_set"}:
            raise ValueError("invalid equipment catalog kind")
        for field_name in ("page", "page_size", "total_items", "total_pages"):
            if type(getattr(self, field_name)) is not int or getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if not isinstance(self.items, (list, tuple)) or not all(
            isinstance(item, EquipmentDefinitionItemView) for item in self.items
        ):
            raise TypeError("equipment catalog items have the wrong type")
        items = tuple(self.items)
        _require_query_shape(
            self.resolution_status,
            self.blocked_reason,
            resolved_payload=self.resolution_status == "resolved",
        )
        if self.resolution_status == "blocked" and items:
            raise ValueError("blocked equipment catalog cannot expose items")
        if any(item.definition_kind != self.catalog_kind for item in items):
            raise ValueError("equipment catalog contains a cross-kind item")
        object.__setattr__(self, "items", items)
        object.__setattr__(
            self,
            "candidates",
            tuple(_frozen(candidate) for candidate in self.candidates),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_status": self.resolution_status,
            "catalog_kind": self.catalog_kind,
            "page": self.page,
            "page_size": self.page_size,
            "total_items": self.total_items,
            "total_pages": self.total_pages,
            "items": [item.to_json() for item in self.items],
            "candidates": [_thawed(candidate) for candidate in self.candidates],
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class RelicTemplateAffixView:
    resolution_status: QueryStatus
    requested_identity: str
    template: EquipmentDefinitionItemView | None = None
    slot: EquipmentDefinitionItemView | None = None
    legal_main_affixes: tuple[EquipmentDefinitionItemView, ...] = ()
    legal_sub_affixes: tuple[EquipmentDefinitionItemView, ...] = ()
    candidates: tuple[JSONValue, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.requested_identity, str):
            raise TypeError("requested_identity must be a string")
        payload_present = self.template is not None or self.slot is not None
        _require_query_shape(
            self.resolution_status,
            self.blocked_reason,
            resolved_payload=payload_present,
        )
        if self.resolution_status == "resolved" and (
            self.template is None
            or self.slot is None
            or not self.legal_main_affixes
            or not self.legal_sub_affixes
        ):
            raise ValueError("resolved relic affix query is incomplete")
        if self.resolution_status == "blocked" and (
            self.template is not None
            or self.slot is not None
            or self.legal_main_affixes
            or self.legal_sub_affixes
        ):
            raise ValueError("blocked relic affix query cannot expose definitions")
        object.__setattr__(
            self,
            "candidates",
            tuple(_frozen(candidate) for candidate in self.candidates),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_status": self.resolution_status,
            "requested_identity": self.requested_identity,
            "template": self.template.to_json() if self.template is not None else None,
            "slot": self.slot.to_json() if self.slot is not None else None,
            "legal_main_affixes": [item.to_json() for item in self.legal_main_affixes],
            "legal_sub_affixes": [item.to_json() for item in self.legal_sub_affixes],
            "candidates": [_thawed(candidate) for candidate in self.candidates],
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterBuildAssemblySummaryView:
    assembly_status: str
    battle_admission_status: str
    build_id: str
    input_fingerprint: str
    result_fingerprint: str
    final_panel: JSONValue
    static_contributions: tuple[JSONValue, ...]
    light_cone_activation: tuple[JSONValue, ...]
    relic_set_tiers: tuple[JSONValue, ...]
    dynamic_mechanisms: tuple[JSONValue, ...]
    character_dynamic_mechanisms: tuple[JSONValue, ...]
    battle_admission_blockers: tuple[JSONValue, ...]
    diagnostics: tuple[JSONValue, ...]
    blocked_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "final_panel", _frozen(self.final_panel))
        for field_name in (
            "static_contributions",
            "light_cone_activation",
            "relic_set_tiers",
            "dynamic_mechanisms",
            "character_dynamic_mechanisms",
            "battle_admission_blockers",
            "diagnostics",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(_frozen(item) for item in getattr(self, field_name)),
            )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "assembly_status": self.assembly_status,
            "battle_admission_status": self.battle_admission_status,
            "build_id": self.build_id,
            "input_fingerprint": self.input_fingerprint,
            "result_fingerprint": self.result_fingerprint,
            "final_panel": _thawed(self.final_panel),
            "static_contributions": [
                _thawed(item) for item in self.static_contributions
            ],
            "light_cone_activation": [
                _thawed(item) for item in self.light_cone_activation
            ],
            "relic_set_tiers": [_thawed(item) for item in self.relic_set_tiers],
            "dynamic_mechanisms": [
                _thawed(item) for item in self.dynamic_mechanisms
            ],
            "character_dynamic_mechanisms": [
                _thawed(item) for item in self.character_dynamic_mechanisms
            ],
            "battle_admission_blockers": [
                _thawed(item) for item in self.battle_admission_blockers
            ],
            "diagnostics": [_thawed(item) for item in self.diagnostics],
            "blocked_reasons": list(self.blocked_reasons),
        }


@dataclass(frozen=True)
class CharacterBuildSubmissionView:
    resolution_status: QueryStatus
    summary: CharacterBuildAssemblySummaryView | None = None
    blocked_reason: str = ""
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.summary is not None and not isinstance(
            self.summary,
            CharacterBuildAssemblySummaryView,
        ):
            raise TypeError("character build query summary has the wrong type")
        _require_query_shape(
            self.resolution_status,
            self.blocked_reason,
            resolved_payload=self.summary is not None,
        )
        if not isinstance(self.diagnostics, (list, tuple)) or not all(
            isinstance(item, str) for item in self.diagnostics
        ):
            raise TypeError("character build query diagnostics must be strings")
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_status": self.resolution_status,
            "summary": self.summary.to_json() if self.summary is not None else None,
            "blocked_reason": self.blocked_reason,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class StaticContributionSourceView:
    resolution_status: QueryStatus
    contribution_id: str
    contribution: JSONValue = None
    ledger_entry: JSONValue = None
    definition_key: JSONValue = None
    term_source: JSONValue = None
    definition_source: JSONValue = None
    candidates: tuple[JSONValue, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "contribution",
            "ledger_entry",
            "definition_key",
            "term_source",
            "definition_source",
        ):
            object.__setattr__(self, field_name, _frozen(getattr(self, field_name)))
        payload_present = all(
            getattr(self, field_name) is not None
            for field_name in (
                "contribution",
                "ledger_entry",
                "definition_key",
                "term_source",
                "definition_source",
            )
        )
        _require_query_shape(
            self.resolution_status,
            self.blocked_reason,
            resolved_payload=payload_present,
        )
        object.__setattr__(
            self,
            "candidates",
            tuple(_frozen(candidate) for candidate in self.candidates),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_status": self.resolution_status,
            "contribution_id": self.contribution_id,
            "contribution": _thawed(self.contribution),
            "ledger_entry": _thawed(self.ledger_entry),
            "definition_key": _thawed(self.definition_key),
            "term_source": _thawed(self.term_source),
            "definition_source": _thawed(self.definition_source),
            "candidates": [_thawed(candidate) for candidate in self.candidates],
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class DynamicMutationSourceView:
    resolution_status: QueryStatus
    mutation_id: str
    audit_trace: JSONValue = None
    ability_provider: JSONValue = None
    selection: JSONValue = None
    mechanism_definition: JSONValue = None
    target_definition: JSONValue = None
    mechanism_source: JSONValue = None
    target_source: JSONValue = None
    candidates: tuple[JSONValue, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "audit_trace",
            "ability_provider",
            "selection",
            "mechanism_definition",
            "target_definition",
            "mechanism_source",
            "target_source",
        ):
            object.__setattr__(self, field_name, _frozen(getattr(self, field_name)))
        payload_present = all(
            getattr(self, field_name) is not None
            for field_name in (
                "audit_trace",
                "ability_provider",
                "selection",
                "mechanism_definition",
                "target_definition",
                "mechanism_source",
                "target_source",
            )
        )
        _require_query_shape(
            self.resolution_status,
            self.blocked_reason,
            resolved_payload=payload_present,
        )
        object.__setattr__(
            self,
            "candidates",
            tuple(_frozen(candidate) for candidate in self.candidates),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_status": self.resolution_status,
            "mutation_id": self.mutation_id,
            "audit_trace": _thawed(self.audit_trace),
            "ability_provider": _thawed(self.ability_provider),
            "selection": _thawed(self.selection),
            "mechanism_definition": _thawed(self.mechanism_definition),
            "target_definition": _thawed(self.target_definition),
            "mechanism_source": _thawed(self.mechanism_source),
            "target_source": _thawed(self.target_source),
            "candidates": [_thawed(candidate) for candidate in self.candidates],
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class EquipmentQueryService:
    rules: RuleBook

    def __post_init__(self) -> None:
        if not isinstance(self.rules, RuleBook):
            raise TypeError("rules must be a RuleBook")

    def list_light_cones(
        self,
        page: int = 1,
        page_size: int = 50,
    ) -> EquipmentCatalogPageView:
        return self._catalog_page("light_cone", page, page_size)

    def list_relic_templates(
        self,
        page: int = 1,
        page_size: int = 50,
    ) -> EquipmentCatalogPageView:
        return self._catalog_page("relic_template", page, page_size)

    def list_relic_sets(
        self,
        page: int = 1,
        page_size: int = 50,
    ) -> EquipmentCatalogPageView:
        return self._catalog_page("relic_set", page, page_size)

    def get_light_cone(self, definition_identity: str) -> EquipmentDefinitionView:
        return self._definition("light_cone", definition_identity)

    def get_relic_template(self, definition_identity: str) -> EquipmentDefinitionView:
        return self._definition("relic_template", definition_identity)

    def get_relic_set(self, definition_identity: str) -> EquipmentDefinitionView:
        return self._definition("relic_set", definition_identity)

    def get_relic_set_threshold(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionView:
        return self._definition("relic_set_threshold", definition_identity)

    def get_relic_template_affixes(
        self,
        definition_identity: str,
    ) -> RelicTemplateAffixView:
        if not isinstance(definition_identity, str) or not definition_identity.strip():
            return RelicTemplateAffixView(
                resolution_status="blocked",
                requested_identity="",
                blocked_reason="definition_identity_invalid",
            )
        template_resolution = self.rules.relic_template_definition(definition_identity)
        if template_resolution.resolution_status != "resolved" or template_resolution.value is None:
            return _blocked_affix_view(definition_identity, template_resolution)
        template = template_resolution.value
        slot_resolution = self.rules.relic_slot_definition(
            template.slot_key.definition_identity
        )
        main_group_resolution = self.rules.relic_main_affix_group_definition(
            template.main_affix_group_key.definition_identity
        )
        sub_group_resolution = self.rules.relic_sub_affix_group_definition(
            template.sub_affix_group_key.definition_identity
        )
        dependency_resolutions = (
            slot_resolution,
            main_group_resolution,
            sub_group_resolution,
        )
        blocked = tuple(
            resolution
            for resolution in dependency_resolutions
            if resolution.resolution_status != "resolved" or resolution.value is None
        )
        if blocked:
            return RelicTemplateAffixView(
                resolution_status="blocked",
                requested_identity=definition_identity,
                candidates=tuple(
                    candidate.to_json()
                    for resolution in blocked
                    for candidate in resolution.candidates
                ),
                blocked_reason="relic_template_affix_dependency_unresolved",
            )
        slot = cast(RelicSlotDefinitionIR, slot_resolution.value)
        main_group = cast(
            RelicMainAffixGroupDefinitionIR,
            main_group_resolution.value,
        )
        sub_group = cast(
            RelicSubAffixGroupDefinitionIR,
            sub_group_resolution.value,
        )
        main_affixes: list[RelicMainAffixDefinitionIR] = []
        for key in main_group.affix_keys:
            resolution = self.rules.relic_main_affix_definition(
                key.definition_identity
            )
            if resolution.resolution_status != "resolved" or resolution.value is None:
                return _blocked_affix_dependency(
                    definition_identity,
                    "relic_template_main_affix_unresolved",
                    resolution,
                )
            affix = resolution.value
            if affix.group_key != main_group.definition_key:
                return RelicTemplateAffixView(
                    resolution_status="blocked",
                    requested_identity=definition_identity,
                    blocked_reason="relic_template_main_affix_group_mismatch",
                )
            if affix.property_type in slot.allowed_main_property_types:
                main_affixes.append(affix)
        if not main_affixes:
            return RelicTemplateAffixView(
                resolution_status="blocked",
                requested_identity=definition_identity,
                blocked_reason="relic_template_has_no_legal_main_affix",
            )
        sub_affixes: list[RelicSubAffixDefinitionIR] = []
        for key in sub_group.affix_keys:
            resolution = self.rules.relic_sub_affix_definition(
                key.definition_identity
            )
            if resolution.resolution_status != "resolved" or resolution.value is None:
                return _blocked_affix_dependency(
                    definition_identity,
                    "relic_template_sub_affix_unresolved",
                    resolution,
                )
            affix = resolution.value
            if affix.group_key != sub_group.definition_key:
                return RelicTemplateAffixView(
                    resolution_status="blocked",
                    requested_identity=definition_identity,
                    blocked_reason="relic_template_sub_affix_group_mismatch",
                )
            sub_affixes.append(affix)
        return RelicTemplateAffixView(
            resolution_status="resolved",
            requested_identity=definition_identity,
            template=_definition_item(template),
            slot=_definition_item(slot),
            legal_main_affixes=tuple(
                _definition_item(item)
                for item in sorted(
                    main_affixes,
                    key=lambda item: item.definition_key.stable_id,
                )
            ),
            legal_sub_affixes=tuple(
                _definition_item(item)
                for item in sorted(
                    sub_affixes,
                    key=lambda item: item.definition_key.stable_id,
                )
            ),
        )

    def submit_character_build(
        self,
        payload: object,
    ) -> CharacterBuildSubmissionView:
        try:
            build = CharacterBuildInput.from_json(payload)
        except (KeyError, TypeError, ValueError) as exc:
            return CharacterBuildSubmissionView(
                resolution_status="blocked",
                blocked_reason="character_build_payload_invalid",
                diagnostics=(f"{type(exc).__name__}:{exc}",),
            )
        try:
            result = assemble_character_build(self.rules, build)
        except (KeyError, TypeError, ValueError) as exc:
            return CharacterBuildSubmissionView(
                resolution_status="blocked",
                blocked_reason="character_build_assembly_failed",
                diagnostics=(f"{type(exc).__name__}:{exc}",),
            )
        return CharacterBuildSubmissionView(
            resolution_status="resolved",
            summary=assembly_summary(result),
        )

    def get_static_contribution_source(
        self,
        result: CharacterBuildAssemblyResult,
        contribution_id: str,
    ) -> StaticContributionSourceView:
        if not isinstance(result, CharacterBuildAssemblyResult):
            return _blocked_static(contribution_id, "character_build_result_invalid")
        if not isinstance(contribution_id, str) or not contribution_id:
            return _blocked_static("", "contribution_id_invalid")
        equipment = result.equipment_assembly_result
        if equipment is None or equipment.assembly_status != "assembled":
            return _blocked_static(contribution_id, "equipment_assembly_unavailable")
        contributions = tuple(
            item
            for item in equipment.static_contributions
            if item.contribution_id == contribution_id
        )
        if len(contributions) != 1:
            return _blocked_static(
                contribution_id,
                "static_contribution_missing"
                if not contributions
                else "static_contribution_ambiguous",
                tuple(item.to_json() for item in contributions),
            )
        contribution = contributions[0]
        ledger_entries = tuple(
            item
            for item in equipment.source_ledger
            if item.ledger_entry_id == f"equipment_source:{contribution_id}"
        )
        if len(ledger_entries) != 1:
            return _blocked_static(
                contribution_id,
                "static_contribution_ledger_missing"
                if not ledger_entries
                else "static_contribution_ledger_ambiguous",
                tuple(item.to_json() for item in ledger_entries),
            )
        definition_key = EquipmentDefinitionKey(
            cast(str, contribution.source_ref.definition_kind),
            contribution.source_ref.definition_identity,
        )
        ledger = ledger_entries[0]
        if ledger.definition_key != definition_key or ledger.source != contribution.source:
            return _blocked_static(
                contribution_id,
                "static_contribution_ledger_identity_mismatch",
            )
        definition_resolution = self._resolution_for_key(definition_key)
        if (
            definition_resolution.resolution_status != "resolved"
            or definition_resolution.value is None
        ):
            return _blocked_static(
                contribution_id,
                definition_resolution.blocked_reason
                or "static_definition_unresolved",
                tuple(
                    candidate.to_json()
                    for candidate in definition_resolution.candidates
                ),
            )
        definition = definition_resolution.value
        if not _source_is_tbgd(contribution.source) or not _source_is_tbgd(
            definition.source
        ):
            return _blocked_static(
                contribution_id,
                "static_source_not_tbgd",
            )
        return StaticContributionSourceView(
            resolution_status="resolved",
            contribution_id=contribution_id,
            contribution=contribution.to_json(),
            ledger_entry=ledger.to_json(),
            definition_key=definition_key.to_json(),
            term_source=contribution.source.to_json(),
            definition_source=definition.source.to_json(),
        )

    def get_dynamic_mutation_source(
        self,
        result: CharacterBuildAssemblyResult,
        transition: BattleTransition,
        mutation_id: str,
        *,
        provider_id: str = "",
    ) -> DynamicMutationSourceView:
        if not isinstance(result, CharacterBuildAssemblyResult):
            return _blocked_dynamic(mutation_id, "character_build_result_invalid")
        if not isinstance(transition, BattleTransition):
            return _blocked_dynamic(mutation_id, "battle_transition_invalid")
        if not isinstance(mutation_id, str) or not mutation_id:
            return _blocked_dynamic("", "mutation_id_invalid")
        equipment = result.equipment_assembly_result
        if equipment is None or equipment.assembly_status != "assembled":
            return _blocked_dynamic(mutation_id, "equipment_assembly_unavailable")
        mutations = tuple(
            mutation
            for mutation in transition.transaction.mutations
            if mutation.stable_id() == mutation_id
        )
        if len(mutations) != 1:
            return _blocked_dynamic(
                mutation_id,
                "dynamic_mutation_missing"
                if not mutations
                else "dynamic_mutation_ambiguous",
                tuple(mutation.to_json() for mutation in mutations),
            )
        mutation = mutations[0]
        audit = RuntimeSourceAuditor(self.rules).validate_transition(transition)
        if not audit.ok:
            return _blocked_dynamic(
                mutation_id,
                "runtime_source_audit_failed",
                tuple(violation.to_json() for violation in audit.violations),
            )
        traces = tuple(
            trace
            for trace in audit.traces
            if isinstance(trace.get("mutation"), Mapping)
            and trace["mutation"].get("mutation_id") == mutation_id
        )
        if len(traces) != 1:
            return _blocked_dynamic(
                mutation_id,
                "runtime_source_trace_missing"
                if not traces
                else "runtime_source_trace_ambiguous",
                traces,
            )
        trace = traces[0]
        records = trace.get("settlement_records")
        if not isinstance(records, (list, tuple)) or not records:
            return _blocked_dynamic(
                mutation_id,
                "runtime_settlement_trace_missing",
            )
        if mutation.source != "ability_provider_registry":
            return _blocked_dynamic(
                mutation_id,
                "mutation_is_not_ability_provider_registration",
            )
        providers = mutation.metadata.get("providers")
        if not isinstance(providers, (list, tuple)) or not all(
            isinstance(provider, Mapping) for provider in providers
        ):
            return _blocked_dynamic(
                mutation_id,
                "ability_provider_payload_invalid",
            )
        if not isinstance(provider_id, str):
            return _blocked_dynamic(
                mutation_id,
                "ability_provider_query_identity_invalid",
            )
        if provider_id:
            providers = tuple(
                provider
                for provider in providers
                if provider.get("provider_id") == provider_id
            )
            if not providers:
                return _blocked_dynamic(
                    mutation_id,
                    "ability_provider_query_identity_missing",
                )
        elif len(providers) != 1:
            return _blocked_dynamic(
                mutation_id,
                "ability_provider_query_identity_required",
                tuple(cast(JSONValue, thaw_json(provider)) for provider in providers),
            )
        provider_matches: list[tuple[Mapping[str, object], object]] = []
        provider_errors: list[dict[str, JSONValue]] = []
        for provider in providers:
            try:
                mechanism_key = EquipmentDefinitionKey.from_json(
                    provider.get("mechanism_key")
                )
                target_key = EquipmentDefinitionKey.from_json(
                    provider.get("target_definition_key")
                )
            except (KeyError, TypeError, ValueError) as exc:
                provider_errors.append(
                    {
                        "reason": "ability_provider_identity_invalid",
                        "diagnostic": f"{type(exc).__name__}:{exc}",
                        "provider": cast(JSONValue, thaw_json(provider)),
                    }
                )
                continue
            matches = tuple(
                selection
                for selection in equipment.dynamic_mechanisms
                if selection.mechanism_key == mechanism_key
                and selection.target_definition_key == target_key
            )
            provider_source_id = provider.get("provider_source_id")
            if isinstance(provider_source_id, str) and provider_source_id:
                matches = tuple(
                    selection
                    for selection in matches
                    if selection.provider_source_id == provider_source_id
                )
            selection_id = provider.get("selection_id")
            if isinstance(selection_id, str) and selection_id:
                matches = tuple(
                    selection
                    for selection in matches
                    if selection.selection_id == selection_id
                )
            for selection in matches:
                if provider.get("source") == selection.source.to_json():
                    provider_matches.append((provider, selection))
        if provider_errors:
            return _blocked_dynamic(
                mutation_id,
                "ability_provider_identity_invalid",
                tuple(provider_errors),
            )
        if len(provider_matches) != 1:
            return _blocked_dynamic(
                mutation_id,
                "ability_provider_selection_missing"
                if not provider_matches
                else "ability_provider_selection_ambiguous",
                tuple(
                    {
                        "provider": cast(JSONValue, thaw_json(provider)),
                        "selection": selection.to_json(),
                    }
                    for provider, selection in provider_matches
                ),
            )
        provider, selection = provider_matches[0]
        mechanism_resolution = self.rules.equipment_mechanism_ref(
            selection.mechanism_key.definition_identity
        )
        target_resolution = self._resolution_for_key(
            selection.target_definition_key
        )
        if (
            mechanism_resolution.resolution_status != "resolved"
            or mechanism_resolution.value is None
            or target_resolution.resolution_status != "resolved"
            or target_resolution.value is None
        ):
            return _blocked_dynamic(
                mutation_id,
                "ability_provider_definition_unresolved",
                tuple(
                    candidate.to_json()
                    for resolution in (mechanism_resolution, target_resolution)
                    for candidate in resolution.candidates
                ),
            )
        mechanism = mechanism_resolution.value
        target = target_resolution.value
        if (
            mechanism.definition_key != selection.mechanism_key
            or mechanism.graph_ref_id != selection.graph_ref_id
            or mechanism.source != selection.source
            or selection.mechanism_key not in target.mechanism_ref_ids
        ):
            return _blocked_dynamic(
                mutation_id,
                "ability_provider_definition_chain_mismatch",
            )
        if not _source_is_tbgd(mechanism.source) or not _source_is_tbgd(
            target.source
        ):
            return _blocked_dynamic(
                mutation_id,
                "dynamic_source_not_tbgd",
            )
        return DynamicMutationSourceView(
            resolution_status="resolved",
            mutation_id=mutation_id,
            audit_trace=trace,
            ability_provider=cast(JSONValue, thaw_json(provider)),
            selection=selection.to_json(),
            mechanism_definition=mechanism.to_json(),
            target_definition=target.to_json(),
            mechanism_source=mechanism.source.to_json(),
            target_source=target.source.to_json(),
        )

    def _catalog_page(
        self,
        catalog_kind: CatalogKind,
        page: int,
        page_size: int,
    ) -> EquipmentCatalogPageView:
        pagination_reason = _pagination_blocked_reason(page, page_size)
        if pagination_reason:
            return EquipmentCatalogPageView(
                resolution_status="blocked",
                catalog_kind=catalog_kind,
                page=page if type(page) is int else 0,
                page_size=page_size if type(page_size) is int else 0,
                total_items=0,
                total_pages=0,
                blocked_reason=pagination_reason,
            )
        definitions = tuple(
            definition
            for definition in self.rules.equipment_definitions()
            if definition.definition_key.definition_kind == catalog_kind
        )
        by_identity: dict[str, list[object]] = {}
        for definition in definitions:
            by_identity.setdefault(
                definition.definition_key.definition_identity,
                [],
            ).append(definition)
        duplicate_definitions = tuple(
            definition
            for identity in sorted(by_identity)
            if len(by_identity[identity]) != 1
            for definition in by_identity[identity]
        )
        if duplicate_definitions:
            return EquipmentCatalogPageView(
                resolution_status="blocked",
                catalog_kind=catalog_kind,
                page=page,
                page_size=page_size,
                total_items=len(by_identity),
                total_pages=(len(by_identity) + page_size - 1) // page_size,
                candidates=tuple(
                    definition.to_json() for definition in duplicate_definitions
                ),
                blocked_reason="equipment_catalog_definition_ambiguous",
            )
        identities = tuple(sorted(by_identity))
        total_items = len(identities)
        total_pages = (total_items + page_size - 1) // page_size
        if page > max(1, total_pages):
            return EquipmentCatalogPageView(
                resolution_status="blocked",
                catalog_kind=catalog_kind,
                page=page,
                page_size=page_size,
                total_items=total_items,
                total_pages=total_pages,
                blocked_reason="page_out_of_range",
            )
        start = (page - 1) * page_size
        items: list[EquipmentDefinitionItemView] = []
        for identity in identities[start : start + page_size]:
            view = self._definition(catalog_kind, identity)
            if view.resolution_status != "resolved" or view.value is None:
                return EquipmentCatalogPageView(
                    resolution_status="blocked",
                    catalog_kind=catalog_kind,
                    page=page,
                    page_size=page_size,
                    total_items=total_items,
                    total_pages=total_pages,
                    candidates=view.candidates,
                    blocked_reason=view.blocked_reason
                    or "equipment_catalog_entry_unresolved",
                )
            items.append(view.value)
        return EquipmentCatalogPageView(
            resolution_status="resolved",
            catalog_kind=catalog_kind,
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            items=tuple(items),
        )

    def _definition(
        self,
        expected_kind: DefinitionQueryKind,
        definition_identity: str,
    ) -> EquipmentDefinitionView:
        if not isinstance(definition_identity, str) or not definition_identity.strip():
            return EquipmentDefinitionView(
                resolution_status="blocked",
                expected_kind=expected_kind,
                requested_identity="",
                blocked_reason="definition_identity_invalid",
            )
        key = EquipmentDefinitionKey(expected_kind, definition_identity)
        resolution = self._resolution_for_key(key)
        if resolution.resolution_status != "resolved" or resolution.value is None:
            return EquipmentDefinitionView(
                resolution_status="blocked",
                expected_kind=expected_kind,
                requested_identity=definition_identity,
                candidates=tuple(
                    candidate.to_json() for candidate in resolution.candidates
                ),
                blocked_reason=resolution.blocked_reason,
            )
        return EquipmentDefinitionView(
            resolution_status="resolved",
            expected_kind=expected_kind,
            requested_identity=definition_identity,
            value=_definition_item(resolution.value),
        )

    def _resolution_for_key(
        self,
        key: EquipmentDefinitionKey,
    ) -> EquipmentDefinitionResolution:
        identity = key.definition_identity
        if key.definition_kind == "light_cone":
            return self.rules.light_cone_definition(identity)
        if key.definition_kind == "relic_slot":
            return self.rules.relic_slot_definition(identity)
        if key.definition_kind == "relic_main_affix_group":
            return self.rules.relic_main_affix_group_definition(identity)
        if key.definition_kind == "relic_main_affix":
            return self.rules.relic_main_affix_definition(identity)
        if key.definition_kind == "relic_sub_affix_group":
            return self.rules.relic_sub_affix_group_definition(identity)
        if key.definition_kind == "relic_sub_affix":
            return self.rules.relic_sub_affix_definition(identity)
        if key.definition_kind == "relic_template":
            return self.rules.relic_template_definition(identity)
        if key.definition_kind == "relic_set":
            return self.rules.relic_set_definition(identity)
        if key.definition_kind == "relic_set_threshold":
            return self.rules.relic_set_threshold(identity)
        if key.definition_kind == "equipment_mechanism":
            return self.rules.equipment_mechanism_ref(identity)
        raise ValueError(f"unsupported equipment query definition kind {key.definition_kind!r}")


def assembly_summary(
    result: CharacterBuildAssemblyResult,
) -> CharacterBuildAssemblySummaryView:
    if not isinstance(result, CharacterBuildAssemblyResult):
        raise TypeError("result must be a CharacterBuildAssemblyResult")
    equipment = result.equipment_assembly_result
    return CharacterBuildAssemblySummaryView(
        assembly_status=result.assembly_status,
        battle_admission_status=result.battle_admission_status,
        build_id=result.build_id,
        input_fingerprint=result.input_fingerprint,
        result_fingerprint=result.result_fingerprint,
        final_panel=(
            result.base_panel.to_json() if result.base_panel is not None else None
        ),
        static_contributions=tuple(
            item.to_json() for item in result.contribution_ledger
        ),
        light_cone_activation=(
            tuple(item.to_json() for item in equipment.activation_decisions)
            if equipment is not None
            else ()
        ),
        relic_set_tiers=(
            tuple(
                item.to_json()
                for item in equipment.relic_set_activation_decisions
            )
            if equipment is not None
            else ()
        ),
        dynamic_mechanisms=(
            tuple(item.to_json() for item in equipment.dynamic_mechanisms)
            if equipment is not None
            else ()
        ),
        character_dynamic_mechanisms=tuple(
            item.to_json() for item in result.admitted_dynamic_mechanism_refs
        ),
        battle_admission_blockers=(
            tuple(item.to_json() for item in equipment.battle_admission_blockers)
            if equipment is not None
            else ()
        ),
        diagnostics=(
            tuple(item.to_json() for item in equipment.diagnostics)
            if equipment is not None
            else ()
        )
        + tuple(
            item.to_json()
            for item in result.unadmitted_mechanism_diagnostics
        ),
        blocked_reasons=result.blocked_reasons,
    )


def _definition_item(definition: object) -> EquipmentDefinitionItemView:
    key = definition.definition_key
    return EquipmentDefinitionItemView(
        definition_kind=key.definition_kind,
        definition_identity=key.definition_identity,
        stable_id=key.stable_id,
        coverage_status=definition.coverage_status,
        snapshot=definition.to_json(),
    )


def _pagination_blocked_reason(page: object, page_size: object) -> str:
    if type(page) is not int or page <= 0:
        return "page_invalid"
    if type(page_size) is not int or page_size <= 0:
        return "page_size_invalid"
    if page_size > MAX_PAGE_SIZE:
        return "page_size_exceeds_limit"
    return ""


def _blocked_affix_view(
    definition_identity: str,
    resolution: EquipmentDefinitionResolution,
) -> RelicTemplateAffixView:
    return RelicTemplateAffixView(
        resolution_status="blocked",
        requested_identity=definition_identity,
        candidates=tuple(
            candidate.to_json() for candidate in resolution.candidates
        ),
        blocked_reason=resolution.blocked_reason,
    )


def _blocked_affix_dependency(
    definition_identity: str,
    reason: str,
    resolution: EquipmentDefinitionResolution,
) -> RelicTemplateAffixView:
    return RelicTemplateAffixView(
        resolution_status="blocked",
        requested_identity=definition_identity,
        candidates=tuple(
            candidate.to_json() for candidate in resolution.candidates
        ),
        blocked_reason=resolution.blocked_reason or reason,
    )


def _source_is_tbgd(source: object) -> bool:
    evidence = getattr(source, "evidence", None)
    return bool(
        getattr(source, "source_path", "")
        and getattr(source, "raw_type", "")
        and getattr(source, "raw_id", "")
        and isinstance(evidence, Mapping)
        and evidence.get("source_kind") == "tbgd"
    )


def _blocked_static(
    contribution_id: object,
    reason: str,
    candidates: tuple[JSONValue, ...] = (),
) -> StaticContributionSourceView:
    return StaticContributionSourceView(
        resolution_status="blocked",
        contribution_id=contribution_id if isinstance(contribution_id, str) else "",
        candidates=candidates,
        blocked_reason=reason,
    )


def _blocked_dynamic(
    mutation_id: object,
    reason: str,
    candidates: tuple[JSONValue, ...] = (),
) -> DynamicMutationSourceView:
    return DynamicMutationSourceView(
        resolution_status="blocked",
        mutation_id=mutation_id if isinstance(mutation_id, str) else "",
        candidates=candidates,
        blocked_reason=reason,
    )
