from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Literal, TypeVar

from ..equipment.models import (
    CharacterEquipmentEligibilityIR,
    EQUIPMENT_RESOLVABLE_COVERAGE_STATES,
    EquipmentAbilityParameterReadIR,
    EquipmentDefinition,
    EquipmentDefinitionKey,
    EquipmentDefinitionResolution,
    EquipmentDefinitionT,
    EquipmentMechanismRefIR,
    EquipmentParameterBasis,
    EquipmentResolutionCandidate,
    LightConeDefinitionIR,
    LightConeParameterIR,
    LightConeRankParameterBasis,
    RelicDomainDefinitionIR,
    RelicMainAffixDefinitionIR,
    RelicMainAffixGroupDefinitionIR,
    RelicSetDefinitionIR,
    RelicSetParameterIR,
    RelicSetThresholdIR,
    RelicSetThresholdParameterBasis,
    RelicSlotDefinitionIR,
    RelicSubAffixDefinitionIR,
    RelicSubAffixGroupDefinitionIR,
    RelicTemplateDefinitionIR,
    relic_definition_reference_issues,
)
from .engine_rule_registry import (
    EngineRuleRegistry,
    ENGINE_RULE_REGISTRY_VERSION,
    KILL_ENERGY_RULE_APPLICABILITY,
    TIMELINE_RULE_APPLICABILITY,
    ULTIMATE_COST_RULE_APPLICABILITY,
    engine_rule_admission_reason,
)
from .task_graph import (
    TaskGraphEntryMaterializationIR,
    TaskGraphIR,
    TaskGraphQuery,
    TaskGraphQueryResult,
)
from .action_target_contract import (
    ActionTargetContractIR,
    ActionTargetContractQueryResult,
)
from .ir import (
    AbilityPropertyRangeIR,
    AbilityPropertyWatcherIR,
    AbilityPhaseIR,
    AbilityTaskIR,
    ActionAbilityBindingIR,
    ActionAdmissionIR,
    ActionDefinitionIR,
    ActionDelayEmissionIR,
    ActionEventIR,
    AssistantAbilityResolutionIR,
    AvatarProfileIR,
    CharacterAbilityBindingKind,
    CharacterAbilityBindingIR,
    CharacterAbilityDefinitionIR,
    CharacterAbilitySourceIR,
    CharacterAbilitySourceGraphCatalogIR,
    CharacterAbilitySourceGraphIR,
    CharacterActionSourceIR,
    CharacterBuildBindingIR,
    CharacterBuildSelectorGapIR,
    CharacterBuildSelectorRelationIR,
    CharacterNonGameplaySkillSourceIR,
    CharacterEidolonSlotIR,
    CharacterMechanismSlotIR,
    CharacterTraceNodeIR,
    CharacterDataCardIR,
    MonsterDataCardIR,
    PassiveMechanismSlotIR,
    BreakBaseDamageIR,
    BattleStateTransitionIR,
    BreakDamageEmissionIR,
    BreakStatusEmissionIR,
    BreakTemplateIR,
    BouncePolicyIR,
    CanonicalIR,
    CombatantActionSetIR,
    CombatantProfileIR,
    ConditionIR,
    DamageEmissionIR,
    DamageFormulaRuleIR,
    DamageModifierIR,
    DamageRouteRuleIR,
    EffectIR,
    ExtraActionPolicyIR,
    FormulaIR,
    HitProfileIR,
    JSONValue,
    QueueIntentIR,
    QueueLifecyclePolicyIR,
    QueuePriorityIR,
    QueueResolutionIR,
    QueueWindowIR,
    ResourceRuleIR,
    RuleEntity,
    SkillContinuationIR,
    SkillFormulaBindingIR,
    ShieldPriorityRuleIR,
    StandaloneAbilityGraphIR,
    StatusCallbackIR,
    StatusCallbackTaskIR,
    StatusDamageEmissionIR,
    StatusEventFamilyIR,
    ServantDefinitionIR,
    ServantOwnerRelationIR,
    SummonMonsterIntentIR,
    SummonUnitDefinitionIR,
    SuperBreakEmissionIR,
    TargetExpressionIR,
    TimelineRuleIR,
    ToughnessEmissionIR,
    TriggerIR,
    UnitBirthTemplateIR,
    WaveDefinitionIR,
    WaveMonsterEntryIR,
)


@dataclass(frozen=True)
class CharacterAbilitySourceGraphQueryResult:
    status: Literal["resolved", "blocked"]
    owner_avatar_id: str
    action_id: str
    ability_name: str
    action_source_ids: tuple[str, ...]
    non_gameplay_skill_source_ids: tuple[str, ...]
    binding_ids: tuple[str, ...]
    definition_ids: tuple[str, ...]
    gap_ids: tuple[str, ...]
    blocked_reason: str

    def __post_init__(self) -> None:
        if self.status not in {"resolved", "blocked"}:
            raise ValueError("invalid character ability query status")
        if not isinstance(self.owner_avatar_id, str) or not self.owner_avatar_id:
            raise ValueError("character ability query owner is required")
        if not isinstance(self.action_id, str) or not isinstance(
            self.ability_name, str
        ):
            raise TypeError("character ability query references must be strings")
        for field_name in (
            "action_source_ids",
            "non_gameplay_skill_source_ids",
            "binding_ids",
            "definition_ids",
            "gap_ids",
        ):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, str) or not value for value in values):
                raise TypeError(f"character ability query {field_name} is invalid")
            if len(values) != len(set(values)):
                raise ValueError(
                    f"character ability query {field_name} contains duplicates"
                )
            object.__setattr__(self, field_name, tuple(sorted(values)))
        if self.status == "resolved":
            if (
                self.blocked_reason
                or self.non_gameplay_skill_source_ids
                or not self.binding_ids
                or not self.definition_ids
            ):
                raise ValueError("resolved character ability query is incomplete")
        elif not self.blocked_reason:
            raise ValueError("blocked character ability query must explain why")
        if self.blocked_reason == "non_gameplay_skill_retired" and (
            not self.action_id
            or len(self.non_gameplay_skill_source_ids) != 1
            or self.action_source_ids
            or self.binding_ids
            or self.definition_ids
            or self.gap_ids
        ):
            raise ValueError("retired skill query result is inconsistent")


@dataclass(frozen=True)
class CharacterAbilityResolutionLedgerEntry:
    relation_id: str
    outcome: Literal["resolved", "blocked"]
    binding_kind: CharacterAbilityBindingKind
    owner_avatar_id: str
    action_source_id: str
    ability_name: str
    result_id: str
    source_path: str
    json_path: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (
                self.relation_id,
                self.binding_kind,
                self.result_id,
                self.source_path,
                self.json_path,
            )
        ):
            raise ValueError("character ability resolution ledger entry is incomplete")
        if self.outcome not in {"resolved", "blocked"}:
            raise ValueError("character ability resolution ledger outcome is invalid")


class CharacterAbilitySourceGraphQuery:
    """Fail-closed narrow lookup over the P9-S1 source relationship graph."""

    def __init__(self, catalog: CharacterAbilitySourceGraphCatalogIR) -> None:
        if type(catalog) is not CharacterAbilitySourceGraphCatalogIR:
            raise TypeError("source graph query requires the exact catalog type")
        self._catalog = catalog
        actions_by_action_id: dict[str, list[CharacterActionSourceIR]] = {}
        for action in catalog.action_sources:
            actions_by_action_id.setdefault(action.action_id, []).append(action)
        self._actions_by_action_id = {
            action_id: tuple(
                sorted(actions, key=lambda action: action.action_source_id)
            )
            for action_id, actions in actions_by_action_id.items()
        }
        retired_by_action_id: dict[str, list[CharacterNonGameplaySkillSourceIR]] = {}
        for source in catalog.non_gameplay_skill_sources:
            retired_by_action_id.setdefault(
                f"avatar_skill:{source.skill_id}", []
            ).append(source)
        self._retired_by_action_id = {
            action_id: tuple(
                sorted(
                    sources,
                    key=lambda source: source.non_gameplay_skill_source_id,
                )
            )
            for action_id, sources in retired_by_action_id.items()
        }
        definitions_by_name: dict[str, list[CharacterAbilityDefinitionIR]] = {}
        for definition in catalog.definitions:
            definitions_by_name.setdefault(definition.ability_name, []).append(
                definition
            )
        self._definitions_by_name = {
            ability_name: tuple(
                sorted(
                    definitions,
                    key=lambda definition: definition.definition_id,
                )
            )
            for ability_name, definitions in definitions_by_name.items()
        }

    @property
    def catalog(self) -> CharacterAbilitySourceGraphCatalogIR:
        return self._catalog

    def resolution_ledger(
        self,
    ) -> tuple[CharacterAbilityResolutionLedgerEntry, ...]:
        entries = [
            CharacterAbilityResolutionLedgerEntry(
                relation_id=binding.relation_id,
                outcome="resolved",
                binding_kind=binding.binding_kind,
                owner_avatar_id=binding.owner_avatar_id,
                action_source_id=binding.action_source_id,
                ability_name=binding.ability_name,
                result_id=binding.binding_id,
                source_path=binding.relation_source.source_path,
                json_path=str(binding.relation_source.evidence["json_path"]),
            )
            for binding in self._catalog.bindings
        ]
        entries.extend(
            CharacterAbilityResolutionLedgerEntry(
                relation_id=gap.relation_id,
                outcome="blocked",
                binding_kind=gap.expected_binding_kind,
                owner_avatar_id=gap.owner_avatar_id,
                action_source_id=gap.action_source_id,
                ability_name=gap.requested_ability_name,
                result_id=gap.gap_id,
                source_path=gap.source.source_path,
                json_path=str(gap.source.evidence["json_path"]),
            )
            for gap in self._catalog.gaps
        )
        return tuple(sorted(entries, key=lambda entry: entry.relation_id))

    @staticmethod
    def _blocked(
        *,
        owner_avatar_id: str,
        action_id: str = "",
        ability_name: str = "",
        action_source_ids: Iterable[str] = (),
        non_gameplay_skill_source_ids: Iterable[str] = (),
        binding_ids: Iterable[str] = (),
        definition_ids: Iterable[str] = (),
        gap_ids: Iterable[str] = (),
        reason: str,
    ) -> CharacterAbilitySourceGraphQueryResult:
        return CharacterAbilitySourceGraphQueryResult(
            status="blocked",
            owner_avatar_id=owner_avatar_id,
            action_id=action_id,
            ability_name=ability_name,
            action_source_ids=tuple(action_source_ids),
            non_gameplay_skill_source_ids=tuple(non_gameplay_skill_source_ids),
            binding_ids=tuple(binding_ids),
            definition_ids=tuple(definition_ids),
            gap_ids=tuple(gap_ids),
            blocked_reason=reason,
        )

    @staticmethod
    def _validate_owner(owner_avatar_id: str) -> None:
        if not isinstance(owner_avatar_id, str) or not owner_avatar_id:
            raise ValueError("character ability query owner is required")

    def query_action(
        self,
        owner_avatar_id: str,
        action_id: str,
    ) -> CharacterAbilitySourceGraphQueryResult:
        self._validate_owner(owner_avatar_id)
        if not isinstance(action_id, str) or not action_id:
            raise ValueError("character ability query action_id is required")
        candidates = self._actions_by_action_id.get(action_id, ())
        retired_candidates = self._retired_by_action_id.get(action_id, ())
        own_retired = tuple(
            source
            for source in retired_candidates
            if source.owner_avatar_id == owner_avatar_id
        )
        if own_retired:
            return self._blocked(
                owner_avatar_id=owner_avatar_id,
                action_id=action_id,
                non_gameplay_skill_source_ids=(
                    source.non_gameplay_skill_source_id for source in own_retired
                ),
                reason=(
                    "non_gameplay_skill_retired"
                    if len(own_retired) == 1
                    else "duplicate_non_gameplay_skill_source_blocked"
                ),
            )
        own_candidates = tuple(
            action
            for action in candidates
            if action.owner_avatar_id == owner_avatar_id
        )
        if not own_candidates:
            reason = (
                "cross_character_blocked"
                if candidates or retired_candidates
                else "missing_action_source_blocked"
            )
            return self._blocked(
                owner_avatar_id=owner_avatar_id,
                action_id=action_id,
                action_source_ids=(
                    action.action_source_id for action in candidates
                ),
                non_gameplay_skill_source_ids=(
                    source.non_gameplay_skill_source_id
                    for source in retired_candidates
                ),
                reason=reason,
            )
        if len(own_candidates) != 1:
            kinds = {action.action_kind for action in own_candidates}
            reason = (
                "cross_kind_blocked"
                if len(kinds) > 1
                else "duplicate_action_source_blocked"
            )
            return self._blocked(
                owner_avatar_id=owner_avatar_id,
                action_id=action_id,
                action_source_ids=(
                    action.action_source_id for action in own_candidates
                ),
                reason=reason,
            )
        action = own_candidates[0]
        related_gaps = tuple(
            gap
            for gap in self._catalog.gaps
            if gap.owner_avatar_id == owner_avatar_id
            and gap.expected_binding_kind != "presentation"
            and (
                gap.action_source_id == action.action_source_id
                or action.action_source_id in gap.candidate_action_source_ids
            )
        )
        action_bindings = tuple(
            binding
            for binding in self._catalog.bindings
            if binding.action_source_id == action.action_source_id
        )
        gameplay_bindings = tuple(
            binding
            for binding in action_bindings
            if binding.binding_kind in {"entry", "phase", "passive"}
        )
        if related_gaps:
            return self._blocked(
                owner_avatar_id=owner_avatar_id,
                action_id=action_id,
                action_source_ids=(action.action_source_id,),
                binding_ids=(binding.binding_id for binding in action_bindings),
                definition_ids=tuple(
                    sorted(
                        {
                            binding.ability_definition_id
                            for binding in action_bindings
                        }
                    )
                ),
                gap_ids=(gap.gap_id for gap in related_gaps),
                reason="action_relationship_gap_blocked",
            )
        if not gameplay_bindings:
            return self._blocked(
                owner_avatar_id=owner_avatar_id,
                action_id=action_id,
                action_source_ids=(action.action_source_id,),
                reason="missing_action_ability_binding_blocked",
            )
        return CharacterAbilitySourceGraphQueryResult(
            status="resolved",
            owner_avatar_id=owner_avatar_id,
            action_id=action_id,
            ability_name="",
            action_source_ids=(action.action_source_id,),
            non_gameplay_skill_source_ids=(),
            binding_ids=tuple(binding.binding_id for binding in action_bindings),
            definition_ids=tuple(
                sorted(
                    {
                        binding.ability_definition_id
                        for binding in action_bindings
                    }
                )
            ),
            gap_ids=(),
            blocked_reason="",
        )

    def query_standalone_ability(
        self,
        owner_avatar_id: str,
        ability_name: str,
        *,
        binding_kind: Literal["standalone", "presentation"] = "standalone",
    ) -> CharacterAbilitySourceGraphQueryResult:
        self._validate_owner(owner_avatar_id)
        if not isinstance(ability_name, str) or not ability_name:
            raise ValueError("character ability query ability_name is required")
        if binding_kind not in {"standalone", "presentation"}:
            raise ValueError("standalone query kind is invalid")
        candidates = self._definitions_by_name.get(ability_name, ())
        own_gameplay = tuple(
            definition
            for definition in candidates
            if definition.definition_kind in {"character_main", "character_shared"}
            and definition.owner_avatar_id in {"", owner_avatar_id}
        )
        own_presentation = tuple(
            definition
            for definition in candidates
            if definition.definition_kind == "presentation"
            and definition.owner_avatar_id == owner_avatar_id
        )
        foreign = tuple(
            definition
            for definition in candidates
            if definition.owner_avatar_id not in {"", owner_avatar_id}
        )
        expected = own_presentation if binding_kind == "presentation" else own_gameplay
        wrong_kind = own_gameplay if binding_kind == "presentation" else own_presentation
        if not expected:
            return self._blocked(
                owner_avatar_id=owner_avatar_id,
                ability_name=ability_name,
                definition_ids=(
                    definition.definition_id for definition in foreign
                ),
                reason=(
                    "cross_character_blocked"
                    if foreign
                    else "wrong_kind_blocked"
                    if wrong_kind
                    else "source_gap_blocked"
                ),
            )
        if len(expected) != 1:
            return self._blocked(
                owner_avatar_id=owner_avatar_id,
                ability_name=ability_name,
                definition_ids=(
                    definition.definition_id for definition in expected
                ),
                reason="ambiguous_binding_blocked",
            )
        definition = expected[0]
        matching_bindings = tuple(
            binding
            for binding in self._catalog.bindings
            if binding.ability_definition_id == definition.definition_id
            and binding.binding_kind == binding_kind
            and binding.owner_avatar_id in {"", owner_avatar_id}
        )
        if len(matching_bindings) != 1:
            return self._blocked(
                owner_avatar_id=owner_avatar_id,
                ability_name=ability_name,
                definition_ids=(definition.definition_id,),
                binding_ids=(
                    binding.binding_id for binding in matching_bindings
                ),
                reason="missing_or_duplicate_typed_binding_blocked",
            )
        return CharacterAbilitySourceGraphQueryResult(
            status="resolved",
            owner_avatar_id=owner_avatar_id,
            action_id="",
            ability_name=ability_name,
            action_source_ids=(),
            non_gameplay_skill_source_ids=(),
            binding_ids=(matching_bindings[0].binding_id,),
            definition_ids=(definition.definition_id,),
            gap_ids=(),
            blocked_reason="",
        )


@dataclass(frozen=True)
class EquipmentDynamicParameterContext:
    target_definition_key: EquipmentDefinitionKey
    parameter_basis: EquipmentParameterBasis
    parameters: tuple[LightConeParameterIR | RelicSetParameterIR, ...]
    mechanism_ref: EquipmentMechanismRefIR
    graph: StandaloneAbilityGraphIR


@dataclass(frozen=True)
class RuleBook:
    """Read-only view over Canonical IR."""

    ir: CanonicalIR

    def __post_init__(self) -> None:
        task_graph_catalog = self.ir.task_graph_catalog
        object.__setattr__(
            self,
            "_task_graph_query",
            TaskGraphQuery(task_graph_catalog) if task_graph_catalog is not None else None,
        )
        catalog = self.ir.character_ability_source_graph_catalog
        object.__setattr__(
            self,
            "_character_ability_source_graph_query",
            (
                CharacterAbilitySourceGraphQuery(catalog)
                if catalog is not None
                else None
            ),
        )
        object.__setattr__(
            self,
            "_character_ability_sources",
            {source.source_id: source for source in catalog.sources}
            if catalog is not None
            else {},
        )
        object.__setattr__(
            self,
            "_character_ability_definitions",
            {
                definition.definition_id: definition
                for definition in catalog.definitions
            }
            if catalog is not None
            else {},
        )
        object.__setattr__(
            self,
            "_character_ability_bindings",
            {binding.binding_id: binding for binding in catalog.bindings}
            if catalog is not None
            else {},
        )
        object.__setattr__(
            self,
            "_character_ability_source_graphs",
            {graph.graph_id: graph for graph in catalog.graphs}
            if catalog is not None
            else {},
        )
        object.__setattr__(self, "_entities", {entity.entity_id: entity for entity in self.ir.entities})
        modifier_definitions_by_name: dict[str, list[RuleEntity]] = {}
        status_entities_by_modifier: dict[str, list[RuleEntity]] = {}
        for entity in self.ir.entities:
            modifier_name = entity.fields.get("modifier_name")
            if not isinstance(modifier_name, str) or not modifier_name:
                modifier_name = entity.fields.get("ModifierName")
            if not isinstance(modifier_name, str) or not modifier_name:
                continue
            if entity.entity_type == "modifier_definition":
                modifier_definitions_by_name.setdefault(modifier_name, []).append(entity)
            elif entity.entity_type == "status":
                status_entities_by_modifier.setdefault(modifier_name, []).append(entity)
        object.__setattr__(
            self,
            "_modifier_definitions_by_name",
            {
                key: tuple(sorted(value, key=lambda item: item.entity_id))
                for key, value in modifier_definitions_by_name.items()
            },
        )
        object.__setattr__(
            self,
            "_status_entities_by_modifier",
            {
                key: tuple(sorted(value, key=lambda item: item.entity_id))
                for key, value in status_entities_by_modifier.items()
            },
        )
        object.__setattr__(
            self,
            "_avatar_profiles",
            {profile.avatar_id: profile for profile in self.ir.avatar_profiles},
        )
        object.__setattr__(
            self,
            "_avatar_profiles_by_profile_id",
            {profile.avatar_profile_id: profile for profile in self.ir.avatar_profiles},
        )
        object.__setattr__(
            self,
            "_character_data_cards",
            {card.card_id: card for card in self.ir.character_data_cards},
        )
        object.__setattr__(
            self,
            "_character_data_cards_by_entity_ref",
            {card.entity_ref: card for card in self.ir.character_data_cards},
        )
        object.__setattr__(
            self,
            "_monster_data_cards",
            {card.card_id: card for card in self.ir.monster_data_cards},
        )
        object.__setattr__(
            self,
            "_monster_data_cards_by_entity_ref",
            {card.entity_ref: card for card in self.ir.monster_data_cards},
        )
        equipment_catalogs: tuple[
            tuple[str, type[EquipmentDefinition], tuple[object, ...]],
            ...,
        ] = (
            (
                "character_equipment_eligibility",
                CharacterEquipmentEligibilityIR,
                self.ir.character_equipment_eligibilities,
            ),
            ("light_cone", LightConeDefinitionIR, self.ir.light_cone_definitions),
            ("relic_domain", RelicDomainDefinitionIR, self.ir.relic_domain_definitions),
            ("relic_slot", RelicSlotDefinitionIR, self.ir.relic_slot_definitions),
            (
                "relic_main_affix_group",
                RelicMainAffixGroupDefinitionIR,
                self.ir.relic_main_affix_group_definitions,
            ),
            (
                "relic_main_affix",
                RelicMainAffixDefinitionIR,
                self.ir.relic_main_affix_definitions,
            ),
            (
                "relic_sub_affix_group",
                RelicSubAffixGroupDefinitionIR,
                self.ir.relic_sub_affix_group_definitions,
            ),
            (
                "relic_sub_affix",
                RelicSubAffixDefinitionIR,
                self.ir.relic_sub_affix_definitions,
            ),
            ("relic_template", RelicTemplateDefinitionIR, self.ir.relic_template_definitions),
            ("relic_set", RelicSetDefinitionIR, self.ir.relic_set_definitions),
            ("relic_set_threshold", RelicSetThresholdIR, self.ir.relic_set_thresholds),
            ("equipment_mechanism", EquipmentMechanismRefIR, self.ir.equipment_mechanism_refs),
        )
        equipment_definitions: list[EquipmentDefinition] = []
        equipment_definitions_by_key: dict[EquipmentDefinitionKey, list[EquipmentDefinition]] = {}
        equipment_definitions_by_identity: dict[str, list[EquipmentDefinition]] = {}
        invalid_equipment_catalog_entry_count = 0
        for declared_kind, _expected_type, definitions in equipment_catalogs:
            for definition in definitions:
                if not isinstance(
                    definition,
                    (
                        CharacterEquipmentEligibilityIR,
                        LightConeDefinitionIR,
                        RelicDomainDefinitionIR,
                        RelicSlotDefinitionIR,
                        RelicMainAffixGroupDefinitionIR,
                        RelicMainAffixDefinitionIR,
                        RelicSubAffixGroupDefinitionIR,
                        RelicSubAffixDefinitionIR,
                        RelicTemplateDefinitionIR,
                        RelicSetDefinitionIR,
                        RelicSetThresholdIR,
                        EquipmentMechanismRefIR,
                    ),
                ):
                    invalid_equipment_catalog_entry_count += 1
                    continue
                equipment_definitions.append(definition)
                declared_key = EquipmentDefinitionKey(
                    declared_kind,
                    definition.definition_key.definition_identity,
                )
                equipment_definitions_by_key.setdefault(declared_key, []).append(definition)
                equipment_definitions_by_identity.setdefault(
                    declared_key.definition_identity,
                    [],
                ).append(definition)
        object.__setattr__(
            self,
            "_equipment_definitions",
            tuple(sorted(equipment_definitions, key=_equipment_definition_sort_key)),
        )
        object.__setattr__(
            self,
            "_invalid_equipment_catalog_entry_count",
            invalid_equipment_catalog_entry_count,
        )
        object.__setattr__(
            self,
            "_equipment_definitions_by_key",
            {
                key: tuple(sorted(definitions, key=_equipment_definition_sort_key))
                for key, definitions in equipment_definitions_by_key.items()
            },
        )
        object.__setattr__(
            self,
            "_equipment_definitions_by_identity",
            {
                identity: tuple(sorted(definitions, key=_equipment_definition_sort_key))
                for identity, definitions in equipment_definitions_by_identity.items()
            },
        )
        relic_reference_issues_by_key: dict[
            EquipmentDefinitionKey,
            list[str],
        ] = {}
        for issue in relic_definition_reference_issues(equipment_definitions):
            relic_reference_issues_by_key.setdefault(
                issue.definition_key,
                [],
            ).append(issue.issue_code)
        object.__setattr__(
            self,
            "_relic_reference_issues_by_key",
            {
                key: tuple(sorted(set(issue_codes)))
                for key, issue_codes in relic_reference_issues_by_key.items()
            },
        )
        equipment_parameter_reads, equipment_parameter_read_conflicts = _unique_index(
            self.ir.equipment_ability_parameter_reads,
            lambda item: item.parameter_read_id,
        )
        object.__setattr__(self, "_equipment_parameter_reads", equipment_parameter_reads)
        object.__setattr__(
            self,
            "_equipment_parameter_read_conflicts",
            equipment_parameter_read_conflicts,
        )
        object.__setattr__(
            self,
            "_summon_unit_definitions",
            {definition.summon_definition_id: definition for definition in self.ir.summon_unit_definitions},
        )
        object.__setattr__(
            self,
            "_summon_unit_definitions_by_unit_id",
            {definition.summon_unit_id: definition for definition in self.ir.summon_unit_definitions},
        )
        object.__setattr__(
            self,
            "_unit_birth_templates",
            {template.birth_template_id: template for template in self.ir.unit_birth_templates},
        )
        object.__setattr__(
            self,
            "_summon_monster_intents",
            {intent.summon_intent_id: intent for intent in self.ir.summon_monster_intents},
        )
        summon_monster_intents_by_task: dict[str, list[SummonMonsterIntentIR]] = {}
        for intent in self.ir.summon_monster_intents:
            summon_monster_intents_by_task.setdefault(intent.source_task_id, []).append(intent)
        object.__setattr__(
            self,
            "_summon_monster_intents_by_task",
            {
                key: tuple(sorted(value, key=lambda item: item.summon_intent_id))
                for key, value in summon_monster_intents_by_task.items()
            },
        )
        object.__setattr__(
            self,
            "_assistant_ability_resolutions",
            {
                resolution.assistant_resolution_id: resolution
                for resolution in self.ir.assistant_ability_resolutions
            },
        )
        object.__setattr__(
            self,
            "_assistant_ability_resolution_by_intent",
            {
                resolution.queue_intent_id: resolution
                for resolution in self.ir.assistant_ability_resolutions
            },
        )
        assistant_ability_resolutions_by_ability_id: dict[str, list[AssistantAbilityResolutionIR]] = {}
        for resolution in self.ir.assistant_ability_resolutions:
            if resolution.assistant_ability_id:
                assistant_ability_resolutions_by_ability_id.setdefault(
                    resolution.assistant_ability_id,
                    [],
                ).append(resolution)
        object.__setattr__(
            self,
            "_assistant_ability_resolutions_by_ability_id",
            {
                key: tuple(sorted(value, key=lambda item: item.assistant_resolution_id))
                for key, value in assistant_ability_resolutions_by_ability_id.items()
            },
        )
        servant_definitions, definition_id_conflicts = _unique_index(
            self.ir.servant_definitions,
            lambda definition: definition.servant_definition_id,
        )
        if definition_id_conflicts:
            raise ValueError(
                "duplicate servant definition identities: "
                + ", ".join(sorted(definition_id_conflicts))
            )
        servant_definitions_by_ref, definition_ref_conflicts = _unique_index(
            (
                definition
                for definition in self.ir.servant_definitions
                if definition.servant_ref
            ),
            lambda definition: definition.servant_ref,
        )
        if definition_ref_conflicts:
            raise ValueError(
                "duplicate servant definition refs: "
                + ", ".join(sorted(definition_ref_conflicts))
            )
        object.__setattr__(self, "_servant_definitions", servant_definitions)
        object.__setattr__(self, "_servant_definitions_by_ref", servant_definitions_by_ref)
        servant_definitions_by_owner: dict[str, list[ServantDefinitionIR]] = {}
        relation_rows = tuple(
            relation
            for definition in self.ir.servant_definitions
            for relation in definition.owner_relations
        )
        servant_owner_relations, relation_id_conflicts = _unique_index(
            relation_rows,
            lambda relation: relation.owner_relation_id,
        )
        if relation_id_conflicts:
            raise ValueError(
                "duplicate servant owner relation identities: "
                + ", ".join(sorted(relation_id_conflicts))
            )
        semantic_relation_counts: dict[tuple[str, str], int] = {}
        for key in (
            (definition.servant_definition_id, relation.owner_entity_ref)
            for definition in self.ir.servant_definitions
            for relation in definition.owner_relations
        ):
            semantic_relation_counts[key] = semantic_relation_counts.get(key, 0) + 1
        duplicate_semantic_relations = sorted(
            key
            for key, count in semantic_relation_counts.items()
            if count != 1
        )
        if duplicate_semantic_relations:
            raise ValueError(
                "duplicate servant owner relation semantics: "
                + ", ".join(
                    f"{definition_id}:{owner_ref}"
                    for definition_id, owner_ref in duplicate_semantic_relations
                )
            )
        servant_definitions_by_owned_skill: dict[
            tuple[str, str], list[ServantDefinitionIR]
        ] = {}
        for definition in self.ir.servant_definitions:
            for relation in definition.owner_relations:
                if relation.coverage_status != "executable":
                    continue
                servant_definitions_by_owner.setdefault(
                    relation.owner_entity_ref,
                    [],
                ).append(definition)
                for skill_id in relation.auxiliary_skill_ids:
                    servant_definitions_by_owned_skill.setdefault(
                        (relation.owner_entity_ref, skill_id),
                        [],
                    ).append(definition)
        object.__setattr__(self, "_servant_owner_relations", servant_owner_relations)
        object.__setattr__(
            self,
            "_servant_definitions_by_owner",
            {
                key: tuple(sorted(value, key=lambda item: item.servant_definition_id))
                for key, value in servant_definitions_by_owner.items()
            },
        )
        object.__setattr__(
            self,
            "_servant_definitions_by_owned_skill",
            {
                key: tuple(
                    sorted(value, key=lambda item: item.servant_definition_id)
                )
                for key, value in servant_definitions_by_owned_skill.items()
            },
        )
        mechanism_slots_by_card: dict[str, list[CharacterMechanismSlotIR]] = {}
        for slot in self.ir.character_mechanism_slots:
            mechanism_slots_by_card.setdefault(slot.character_data_card_id, []).append(slot)
        object.__setattr__(
            self,
            "_character_mechanism_slots",
            {slot.mechanism_slot_id: slot for slot in self.ir.character_mechanism_slots},
        )
        object.__setattr__(
            self,
            "_character_mechanism_slots_by_card",
            {
                key: tuple(sorted(value, key=lambda item: item.mechanism_slot_id))
                for key, value in mechanism_slots_by_card.items()
            },
        )
        passive_slots_by_card: dict[str, list[PassiveMechanismSlotIR]] = {}
        passive_slots_by_owner: dict[str, list[PassiveMechanismSlotIR]] = {}
        for slot in self.ir.passive_mechanism_slots:
            passive_slots_by_card.setdefault(slot.data_card_id, []).append(slot)
            passive_slots_by_owner.setdefault(slot.owner_entity_ref, []).append(slot)
        object.__setattr__(
            self,
            "_passive_mechanism_slots",
            {slot.passive_slot_id: slot for slot in self.ir.passive_mechanism_slots},
        )
        object.__setattr__(
            self,
            "_passive_mechanism_slots_by_card",
            {
                key: tuple(sorted(value, key=lambda item: item.passive_slot_id))
                for key, value in passive_slots_by_card.items()
            },
        )
        object.__setattr__(
            self,
            "_passive_mechanism_slots_by_owner",
            {
                key: tuple(sorted(value, key=lambda item: item.passive_slot_id))
                for key, value in passive_slots_by_owner.items()
            },
        )
        trace_nodes_by_card: dict[str, list[CharacterTraceNodeIR]] = {}
        for node in self.ir.character_trace_nodes:
            trace_nodes_by_card.setdefault(node.character_data_card_id, []).append(node)
        object.__setattr__(
            self,
            "_character_trace_nodes",
            {node.trace_node_id: node for node in self.ir.character_trace_nodes},
        )
        object.__setattr__(
            self,
            "_character_trace_nodes_by_card",
            {
                key: tuple(sorted(value, key=lambda item: (item.trace_id, item.trace_node_id)))
                for key, value in trace_nodes_by_card.items()
            },
        )
        eidolon_slots_by_card: dict[str, list[CharacterEidolonSlotIR]] = {}
        for slot in self.ir.character_eidolon_slots:
            eidolon_slots_by_card.setdefault(slot.character_data_card_id, []).append(slot)
        object.__setattr__(
            self,
            "_character_eidolon_slots",
            {slot.eidolon_slot_id: slot for slot in self.ir.character_eidolon_slots},
        )
        object.__setattr__(
            self,
            "_character_eidolon_slots_by_card",
            {
                key: tuple(sorted(value, key=lambda item: (item.rank, item.eidolon_slot_id)))
                for key, value in eidolon_slots_by_card.items()
            },
        )
        selector_relations = tuple(self.ir.character_build_selector_relations)
        selector_gaps = tuple(self.ir.character_build_selector_gaps)
        if any(
            type(item) is not CharacterBuildSelectorRelationIR
            for item in selector_relations
        ) or any(
            type(item) is not CharacterBuildSelectorGapIR
            for item in selector_gaps
        ):
            raise TypeError("RuleBook selector ledger contains an invalid typed value")
        relation_ids = tuple(
            relation.selector_relation_id for relation in selector_relations
        )
        gap_ids = tuple(gap.selector_gap_id for gap in selector_gaps)
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("RuleBook selector relation identities must be unique")
        if len(gap_ids) != len(set(gap_ids)):
            raise ValueError("RuleBook selector gap identities must be unique")
        selector_identities = tuple(
            item.selector_identity for item in (*selector_relations, *selector_gaps)
        )
        if len(selector_identities) != len(set(selector_identities)):
            raise ValueError("RuleBook selector source identities must be unique")
        selector_relations_by_id = {
            relation.selector_relation_id: relation
            for relation in selector_relations
        }
        selector_gaps_by_id = {
            gap.selector_gap_id: gap for gap in selector_gaps
        }
        selector_relations_by_card: dict[
            str, list[CharacterBuildSelectorRelationIR]
        ] = {}
        selector_relations_by_selection: dict[
            str, list[CharacterBuildSelectorRelationIR]
        ] = {}
        selector_gaps_by_card: dict[str, list[CharacterBuildSelectorGapIR]] = {}
        for relation in selector_relations:
            selector_relations_by_card.setdefault(
                relation.character_data_card_id,
                [],
            ).append(relation)
            for selection_ref_id in relation.selection_ref_ids:
                selector_relations_by_selection.setdefault(
                    selection_ref_id,
                    [],
                ).append(relation)
        for gap in selector_gaps:
            selector_gaps_by_card.setdefault(
                gap.character_data_card_id,
                [],
            ).append(gap)
        for item in (*selector_relations, *selector_gaps):
            evidence = item.selector_source.evidence
            expected_opcode = (
                "BySkillPointActivated"
                if item.selector_kind == "skill_point"
                else "ByRankActivated"
            )
            if (
                item.selector_source.raw_id != item.selector_scope_record_id
                or item.selector_source.raw_type != expected_opcode
                or evidence.get("json_path")
                != f"{item.selector_json_path}.$type"
                or evidence.get("selector_projection_id")
                != item.selector_projection_id
                or evidence.get("selector_kind") != item.selector_kind
                or evidence.get("selector_key") != (item.selector_key or None)
                or evidence.get("selector_hash") != item.selector_hash
                or evidence.get("source_content_sha256")
                != item.source_content_sha256
            ):
                raise ValueError("RuleBook selector source identity is inconsistent")
            card = self._character_data_cards.get(item.character_data_card_id)
            expected_card_id = (
                f"character_data_card:avatar:{item.owner_avatar_id}"
            )
            if (
                card is None
                or item.character_data_card_id != expected_card_id
                or card.entity_ref != f"avatar:{item.owner_avatar_id}"
                or item.selector_source.evidence.get("avatar_id")
                != item.owner_avatar_id
            ):
                raise ValueError("character build selector owner/card mismatch")
            source = self._character_ability_sources.get(item.source_id)
            source_graph = self._character_ability_source_graphs.get(
                item.source_graph_id
            )
            source_closed = (
                source is not None
                and source.source_kind == "character_main"
                and source.avatar_id == item.owner_avatar_id
                and source.source.source_path == item.selector_source.source_path
                and source.content_sha256 == item.source_content_sha256
                and source_graph is not None
                and source_graph.source_id == source.source_id
                and source_graph.source_kind == "character_main"
                and source_graph.owner_avatar_id == item.owner_avatar_id
            )
            if isinstance(item, CharacterBuildSelectorRelationIR):
                if not source_closed:
                    raise ValueError(
                        "character build selector relation is outside S1 source closure"
                    )
                graph_ref = next(
                    (
                        ref
                        for ref in card.ability_source_graph_refs
                        if ref.graph_ref_id == item.source_graph_ref_id
                    ),
                    None,
                )
                if graph_ref is None or graph_ref.graph_id != item.source_graph_id:
                    raise ValueError(
                        "character build selector relation has no card graph ref"
                    )
                selection_items: tuple[CharacterTraceNodeIR | CharacterEidolonSlotIR, ...]
                if item.selection_kind == "trace":
                    selection_items = tuple(
                        self._character_trace_nodes.get(ref_id)
                        for ref_id in item.selection_ref_ids
                    )  # type: ignore[assignment]
                    selection_closed = all(
                        isinstance(selection, CharacterTraceNodeIR)
                        and selection.character_data_card_id == item.character_data_card_id
                        and selection.avatar_id == item.owner_avatar_id
                        and selection.trace_id == item.logical_selection_id
                        and selection.source.evidence.get("point_trigger_key")
                        == item.selector_key
                        for selection in selection_items
                    )
                else:
                    selection_items = tuple(
                        self._character_eidolon_slots.get(ref_id)
                        for ref_id in item.selection_ref_ids
                    )  # type: ignore[assignment]
                    selection_closed = all(
                        isinstance(selection, CharacterEidolonSlotIR)
                        and selection.character_data_card_id == item.character_data_card_id
                        and selection.avatar_id == item.owner_avatar_id
                        and str(selection.rank) == item.logical_selection_id
                        and selection.semantics.get("trigger_hash")
                        == item.selector_hash
                        for selection in selection_items
                    )
                if not selection_closed:
                    raise ValueError(
                        "character build selector relation selection is dangling"
                    )
                if item.location_kind == "ability_definition":
                    definition = self._character_ability_definitions.get(
                        item.ability_definition_id
                    )
                    if (
                        definition is None
                        or definition.definition_id not in source_graph.definition_ids
                        or definition.source_id != item.source_id
                        or definition.owner_avatar_id != item.owner_avatar_id
                        or definition.ability_name != item.ability_name
                        or definition.source != item.ability_definition_source
                    ):
                        raise ValueError(
                            "character build selector ability definition is not source-closed"
                        )
            elif item.gap_kind not in {
                "source_graph_missing",
                "source_closure_mismatch",
            } and not source_closed:
                raise ValueError(
                    "character build selector gap invented an S1 source closure"
                )
        object.__setattr__(
            self,
            "_character_build_selector_relations",
            selector_relations_by_id,
        )
        object.__setattr__(
            self,
            "_character_build_selector_gaps",
            selector_gaps_by_id,
        )
        object.__setattr__(
            self,
            "_character_build_selector_relations_by_card",
            {
                key: tuple(
                    sorted(value, key=lambda item: item.selector_relation_id)
                )
                for key, value in selector_relations_by_card.items()
            },
        )
        object.__setattr__(
            self,
            "_character_build_selector_relations_by_selection",
            {
                key: tuple(
                    sorted(value, key=lambda item: item.selector_relation_id)
                )
                for key, value in selector_relations_by_selection.items()
            },
        )
        object.__setattr__(
            self,
            "_character_build_selector_gaps_by_card",
            {
                key: tuple(sorted(value, key=lambda item: item.selector_gap_id))
                for key, value in selector_gaps_by_card.items()
            },
        )
        character_build_bindings = tuple(
            binding
            for item in (
                *self.ir.character_trace_nodes,
                *self.ir.character_eidolon_slots,
            )
            for binding in item.build_bindings
        )
        build_binding_ids = tuple(
            binding.build_binding_id for binding in character_build_bindings
        )
        if len(build_binding_ids) != len(set(build_binding_ids)):
            raise ValueError("character build binding identities must be globally unique")
        mechanism_slots_by_id = {
            slot.mechanism_slot_id: slot
            for slot in self.ir.character_mechanism_slots
        }
        for binding in character_build_bindings:
            mechanism_slot = mechanism_slots_by_id.get(binding.mechanism_slot_id)
            if (
                mechanism_slot is None
                or mechanism_slot.character_data_card_id
                != binding.character_data_card_id
                or mechanism_slot.source != binding.source
            ):
                raise ValueError(
                    "character build binding mechanism slot is not source-closed"
                )
            if binding.projection_kind == "dynamic_graph_ref":
                card = self._character_data_cards.get(
                    binding.character_data_card_id
                )
                graph_ref = next(
                    (
                        ref
                        for ref in card.ability_source_graph_refs
                        if ref.graph_ref_id == binding.source_graph_ref_id
                    ),
                    None,
                ) if card is not None else None
                source_graph = self._character_ability_source_graphs.get(
                    binding.source_graph_id
                )
                if (
                    graph_ref is None
                    or graph_ref.graph_id != binding.source_graph_id
                    or source_graph is None
                ):
                    raise ValueError(
                        "dynamic character build binding is outside the S1 source graph"
                    )
                ability_binding = self._character_ability_bindings.get(
                    binding.ability_binding_id
                )
                definition = self._character_ability_definitions.get(
                    binding.ability_definition_id
                )
                if (
                    binding.dynamic_ref_kind != "direct_ability"
                    or ability_binding is None
                    or definition is None
                    or ability_binding.graph_id != source_graph.graph_id
                    or ability_binding.ability_definition_id
                    != definition.definition_id
                    or ability_binding.relation_source
                    != binding.relation_source
                    or definition.source != binding.definition_source
                ):
                    raise ValueError(
                        "direct character build binding is outside the S1 source graph"
                    )
        build_bindings_by_card: dict[str, list[CharacterBuildBindingIR]] = {}
        build_bindings_by_selection: dict[str, list[CharacterBuildBindingIR]] = {}
        for binding in character_build_bindings:
            build_bindings_by_card.setdefault(
                binding.character_data_card_id, []
            ).append(binding)
            build_bindings_by_selection.setdefault(
                binding.selection_ref_id, []
            ).append(binding)
        object.__setattr__(
            self,
            "_character_build_bindings",
            {
                binding.build_binding_id: binding
                for binding in character_build_bindings
            },
        )
        object.__setattr__(
            self,
            "_character_build_bindings_by_card",
            {
                key: tuple(sorted(value, key=lambda item: item.build_binding_id))
                for key, value in build_bindings_by_card.items()
            },
        )
        object.__setattr__(
            self,
            "_character_build_bindings_by_selection",
            {
                key: tuple(sorted(value, key=lambda item: item.build_binding_id))
                for key, value in build_bindings_by_selection.items()
            },
        )
        bounce_policies_by_action: dict[tuple[str, int], list[BouncePolicyIR]] = {}
        for policy in self.ir.bounce_policies:
            bounce_policies_by_action.setdefault((policy.action_id, policy.level), []).append(policy)
        object.__setattr__(
            self,
            "_bounce_policies",
            {policy.bounce_policy_id: policy for policy in self.ir.bounce_policies},
        )
        object.__setattr__(
            self,
            "_bounce_policies_by_action",
            {
                key: tuple(sorted(value, key=lambda item: item.bounce_policy_id))
                for key, value in bounce_policies_by_action.items()
            },
        )
        object.__setattr__(
            self,
            "_combatant_profiles",
            {profile.entity_id: profile for profile in self.ir.combatant_profiles},
        )
        object.__setattr__(
            self,
            "_combatant_profiles_by_profile_id",
            {profile.profile_id: profile for profile in self.ir.combatant_profiles},
        )
        action_definition_candidates: dict[tuple[str, int], list[ActionDefinitionIR]] = {}
        for definition in self.ir.action_definitions:
            action_definition_candidates.setdefault(
                (definition.action_id, definition.level),
                [],
            ).append(definition)
        frozen_action_definition_candidates = {
            key: tuple(
                sorted(
                    values,
                    key=_action_definition_candidate_sort_key,
                )
            )
            for key, values in action_definition_candidates.items()
        }
        object.__setattr__(
            self,
            "_action_definition_candidates",
            frozen_action_definition_candidates,
        )
        object.__setattr__(
            self,
            "_action_definitions",
            {
                key: candidates[0]
                for key, candidates in frozen_action_definition_candidates.items()
                if len(candidates) == 1
            },
        )
        action_target_candidates: dict[
            tuple[str, int], list[ActionTargetContractIR]
        ] = {}
        target_catalog = self.ir.action_target_contract_catalog
        for contract in target_catalog.contracts if target_catalog is not None else ():
            action_target_candidates.setdefault(
                (contract.action_id, contract.level), []
            ).append(contract)
        object.__setattr__(
            self,
            "_action_target_contract_candidates",
            {
                key: tuple(sorted(values, key=lambda item: item.contract_id))
                for key, values in action_target_candidates.items()
            },
        )
        damage_modifiers_by_callback: dict[str, list[DamageModifierIR]] = {}
        for modifier in self.ir.damage_modifiers:
            damage_modifiers_by_callback.setdefault(modifier.callback_id, []).append(modifier)
        object.__setattr__(
            self,
            "_damage_modifiers",
            {modifier.damage_modifier_id: modifier for modifier in self.ir.damage_modifiers},
        )
        object.__setattr__(
            self,
            "_damage_modifiers_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: (item.source_task_id, item.damage_modifier_id)))
                for key, value in damage_modifiers_by_callback.items()
            },
        )
        object.__setattr__(
            self,
            "_action_events",
            {(event.action_id, event.level): event for event in self.ir.action_events},
        )
        object.__setattr__(
            self,
            "_action_ability_bindings",
            {(binding.action_id, binding.level): binding for binding in self.ir.action_ability_bindings},
        )
        object.__setattr__(
            self,
            "_action_ability_bindings_by_id",
            {binding.binding_id: binding for binding in self.ir.action_ability_bindings},
        )
        ability_phases_by_binding: dict[str, list[AbilityPhaseIR]] = {}
        ability_phases_by_action: dict[tuple[str, int], list[AbilityPhaseIR]] = {}
        for phase in self.ir.ability_phases:
            ability_phases_by_binding.setdefault(phase.binding_id, []).append(phase)
            ability_phases_by_action.setdefault((phase.action_id, phase.level), []).append(phase)
        object.__setattr__(self, "_ability_phases", {phase.phase_id: phase for phase in self.ir.ability_phases})
        object.__setattr__(
            self,
            "_ability_phases_by_binding",
            {
                key: tuple(sorted(value, key=lambda item: (item.phase_index, item.phase_id)))
                for key, value in ability_phases_by_binding.items()
            },
        )
        object.__setattr__(
            self,
            "_ability_phases_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.phase_index, item.phase_id)))
                for key, value in ability_phases_by_action.items()
            },
        )
        ability_tasks_by_phase: dict[str, list[AbilityTaskIR]] = {}
        ability_tasks_by_action: dict[tuple[str, int], list[AbilityTaskIR]] = {}
        for task in self.ir.ability_tasks:
            ability_tasks_by_phase.setdefault(task.phase_id, []).append(task)
            ability_tasks_by_action.setdefault((task.action_id, task.level), []).append(task)
        object.__setattr__(self, "_ability_tasks", {task.task_id: task for task in self.ir.ability_tasks})
        object.__setattr__(
            self,
            "_ability_tasks_by_phase",
            {
                key: tuple(sorted(value, key=lambda item: (item.callback_kind, item.task_path, item.task_id)))
                for key, value in ability_tasks_by_phase.items()
            },
        )
        object.__setattr__(
            self,
            "_ability_tasks_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.phase_id, item.callback_kind, item.task_path, item.task_id)))
                for key, value in ability_tasks_by_action.items()
            },
        )
        hit_profiles_by_action: dict[tuple[str, int], list[HitProfileIR]] = {}
        for profile in self.ir.hit_profiles:
            hit_profiles_by_action.setdefault((profile.action_id, profile.level), []).append(profile)
        object.__setattr__(self, "_hit_profiles", {profile.hit_profile_id: profile for profile in self.ir.hit_profiles})
        object.__setattr__(
            self,
            "_hit_profiles_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.hit_index, item.target_group, item.hit_profile_id)))
                for key, value in hit_profiles_by_action.items()
            },
        )
        skill_formula_bindings_by_action_param_role: dict[tuple[str, int, int, str], list[SkillFormulaBindingIR]] = {}
        for binding in self.ir.skill_formula_bindings:
            skill_formula_bindings_by_action_param_role.setdefault(
                (binding.action_id, binding.level, binding.param_index, binding.formula_role),
                [],
            ).append(binding)
        object.__setattr__(
            self,
            "_skill_formula_bindings",
            {binding.binding_id: binding for binding in self.ir.skill_formula_bindings},
        )
        object.__setattr__(
            self,
            "_skill_formula_bindings_by_action_param_role",
            {
                key: tuple(sorted(value, key=lambda item: item.binding_id))
                for key, value in skill_formula_bindings_by_action_param_role.items()
            },
        )
        damage_emissions_by_action: dict[tuple[str, int], list[DamageEmissionIR]] = {}
        damage_emissions_by_task: dict[str, list[DamageEmissionIR]] = {}
        for emission in self.ir.damage_emissions:
            damage_emissions_by_action.setdefault((emission.action_id, emission.level), []).append(emission)
            damage_emissions_by_task.setdefault(emission.source_task_id, []).append(emission)
        object.__setattr__(self, "_damage_emissions", {emission.damage_emission_id: emission for emission in self.ir.damage_emissions})
        object.__setattr__(
            self,
            "_damage_emissions_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.source_task_id, item.hit_profile_id, item.damage_emission_id)))
                for key, value in damage_emissions_by_action.items()
            },
        )
        object.__setattr__(
            self,
            "_damage_emissions_by_task",
            {
                key: tuple(sorted(value, key=lambda item: (item.hit_profile_id, item.damage_emission_id)))
                for key, value in damage_emissions_by_task.items()
            },
        )
        toughness_emissions_by_action: dict[tuple[str, int], list[ToughnessEmissionIR]] = {}
        toughness_emissions_by_task: dict[str, list[ToughnessEmissionIR]] = {}
        for emission in self.ir.toughness_emissions:
            toughness_emissions_by_action.setdefault((emission.action_id, emission.level), []).append(emission)
            toughness_emissions_by_task.setdefault(emission.source_task_id, []).append(emission)
        object.__setattr__(
            self,
            "_toughness_emissions",
            {emission.toughness_emission_id: emission for emission in self.ir.toughness_emissions},
        )
        object.__setattr__(
            self,
            "_toughness_emissions_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.source_task_id, item.hit_profile_id, item.toughness_emission_id)))
                for key, value in toughness_emissions_by_action.items()
            },
        )
        object.__setattr__(
            self,
            "_toughness_emissions_by_task",
            {
                key: tuple(sorted(value, key=lambda item: (item.hit_profile_id, item.toughness_emission_id)))
                for key, value in toughness_emissions_by_task.items()
            },
        )
        object.__setattr__(
            self,
            "_break_templates",
            {template.template_id: template for template in self.ir.break_templates},
        )
        object.__setattr__(
            self,
            "_break_templates_by_element",
            {
                str(template.element_type): template
                for template in self.ir.break_templates
                if template.element_type
            },
        )
        object.__setattr__(
            self,
            "_break_damage_emissions",
            {emission.break_damage_emission_id: emission for emission in self.ir.break_damage_emissions},
        )
        object.__setattr__(
            self,
            "_break_base_damage_by_level",
            {row.level: row for row in self.ir.break_base_damage},
        )
        break_damage_emissions_by_template: dict[str, list[BreakDamageEmissionIR]] = {}
        for emission in self.ir.break_damage_emissions:
            break_damage_emissions_by_template.setdefault(emission.template_id, []).append(emission)
        object.__setattr__(
            self,
            "_break_damage_emissions_by_template",
            {
                key: tuple(sorted(value, key=lambda item: item.break_damage_emission_id))
                for key, value in break_damage_emissions_by_template.items()
            },
        )
        object.__setattr__(
            self,
            "_break_status_emissions",
            {emission.break_status_emission_id: emission for emission in self.ir.break_status_emissions},
        )
        break_status_emissions_by_template: dict[str, list[BreakStatusEmissionIR]] = {}
        for emission in self.ir.break_status_emissions:
            break_status_emissions_by_template.setdefault(emission.template_id, []).append(emission)
        object.__setattr__(
            self,
            "_break_status_emissions_by_template",
            {
                key: tuple(sorted(value, key=lambda item: item.break_status_emission_id))
                for key, value in break_status_emissions_by_template.items()
            },
        )
        status_callbacks, status_callback_id_conflicts = _unique_index(
            self.ir.status_callbacks,
            lambda callback: callback.callback_id,
        )
        if status_callback_id_conflicts:
            raise ValueError(
                "status_callback_identity_duplicate:"
                + ",".join(sorted(status_callback_id_conflicts))
            )
        object.__setattr__(self, "_status_callbacks", status_callbacks)
        object.__setattr__(
            self,
            "_status_event_families",
            {family.callback_event: family for family in self.ir.status_event_families},
        )
        status_event_families_by_runtime_event: dict[str, list[StatusEventFamilyIR]] = {}
        for family in self.ir.status_event_families:
            for runtime_event in family.runtime_event_sources:
                status_event_families_by_runtime_event.setdefault(runtime_event, []).append(family)
        object.__setattr__(
            self,
            "_status_event_families_by_runtime_event",
            {
                key: tuple(sorted(value, key=lambda item: item.callback_event))
                for key, value in status_event_families_by_runtime_event.items()
            },
        )
        status_callbacks_by_modifier_event: dict[tuple[str, str], list[StatusCallbackIR]] = {}
        status_callbacks_by_event: dict[str, list[StatusCallbackIR]] = {}
        status_callbacks_by_event_scope: dict[tuple[str, str], list[StatusCallbackIR]] = {}
        status_callbacks_by_modifier_event_scope: dict[tuple[str, str, str], list[StatusCallbackIR]] = {}
        for callback in self.ir.status_callbacks:
            status_callbacks_by_modifier_event.setdefault((callback.modifier_name, callback.event), []).append(callback)
            status_callbacks_by_event.setdefault(callback.event, []).append(callback)
            status_callbacks_by_event_scope.setdefault((callback.event, callback.scope_kind), []).append(callback)
            status_callbacks_by_modifier_event_scope.setdefault(
                (callback.modifier_name, callback.event, callback.scope_kind),
                [],
            ).append(callback)
        object.__setattr__(
            self,
            "_status_callbacks_by_modifier_event",
            {
                key: tuple(sorted(value, key=lambda item: item.execution_order))
                for key, value in status_callbacks_by_modifier_event.items()
            },
        )
        object.__setattr__(
            self,
            "_status_callbacks_by_event",
            {
                key: tuple(sorted(value, key=lambda item: item.execution_order))
                for key, value in status_callbacks_by_event.items()
            },
        )
        object.__setattr__(
            self,
            "_status_callbacks_by_event_scope",
            {
                key: tuple(sorted(value, key=lambda item: item.execution_order))
                for key, value in status_callbacks_by_event_scope.items()
            },
        )
        object.__setattr__(
            self,
            "_status_callbacks_by_modifier_event_scope",
            {
                key: tuple(sorted(value, key=lambda item: item.execution_order))
                for key, value in status_callbacks_by_modifier_event_scope.items()
            },
        )
        object.__setattr__(
            self,
            "_status_callback_tasks",
            {task.task_id: task for task in self.ir.status_callback_tasks},
        )
        status_callback_tasks_by_callback: dict[str, list[StatusCallbackTaskIR]] = {}
        for task in self.ir.status_callback_tasks:
            status_callback_tasks_by_callback.setdefault(task.callback_id, []).append(task)
        object.__setattr__(
            self,
            "_status_callback_tasks_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: (item.task_path, item.task_id)))
                for key, value in status_callback_tasks_by_callback.items()
            },
        )
        ability_property_watchers: dict[str, AbilityPropertyWatcherIR] = {}
        for watcher in self.ir.ability_property_watchers:
            if watcher.watcher_id in ability_property_watchers:
                raise ValueError(
                    "ability_property_watcher_identity_duplicate:"
                    f"{watcher.watcher_id}"
                )
            ability_property_watchers[watcher.watcher_id] = watcher
        object.__setattr__(
            self,
            "_ability_property_watchers",
            ability_property_watchers,
        )
        ability_property_watchers_by_modifier: dict[
            str,
            list[AbilityPropertyWatcherIR],
        ] = {}
        for watcher in self.ir.ability_property_watchers:
            ability_property_watchers_by_modifier.setdefault(
                watcher.modifier_name,
                [],
            ).append(watcher)
        object.__setattr__(
            self,
            "_ability_property_watchers_by_modifier",
            {
                key: tuple(sorted(value, key=lambda item: item.watcher_id))
                for key, value in ability_property_watchers_by_modifier.items()
            },
        )
        ability_property_ranges: dict[str, AbilityPropertyRangeIR] = {}
        for property_range in self.ir.ability_property_ranges:
            if property_range.range_id in ability_property_ranges:
                raise ValueError(
                    "ability_property_range_identity_duplicate:"
                    f"{property_range.range_id}"
                )
            ability_property_ranges[property_range.range_id] = property_range
        object.__setattr__(
            self,
            "_ability_property_ranges",
            ability_property_ranges,
        )
        ability_property_ranges_by_watcher: dict[
            str,
            list[AbilityPropertyRangeIR],
        ] = {}
        for property_range in self.ir.ability_property_ranges:
            ability_property_ranges_by_watcher.setdefault(
                property_range.watcher_id,
                [],
            ).append(property_range)
        object.__setattr__(
            self,
            "_ability_property_ranges_by_watcher",
            {
                key: tuple(
                    sorted(
                        value,
                        key=lambda item: (item.range_index, item.range_id),
                    )
                )
                for key, value in ability_property_ranges_by_watcher.items()
            },
        )
        watcher_contract_error = _ability_property_watcher_contract_error(
            ability_property_watchers,
            ability_property_ranges,
            self._status_callbacks,
        )
        if watcher_contract_error:
            raise ValueError(watcher_contract_error)
        watcher_effect_contract_error = (
            _ability_property_watcher_effect_contract_error(
                self.ir.effects,
                self._entities,
                ability_property_watchers,
            )
        )
        if watcher_effect_contract_error:
            raise ValueError(watcher_effect_contract_error)
        object.__setattr__(
            self,
            "_status_damage_emissions",
            {emission.status_damage_emission_id: emission for emission in self.ir.status_damage_emissions},
        )
        status_damage_emissions_by_callback: dict[str, list[StatusDamageEmissionIR]] = {}
        for emission in self.ir.status_damage_emissions:
            status_damage_emissions_by_callback.setdefault(emission.callback_id, []).append(emission)
        object.__setattr__(
            self,
            "_status_damage_emissions_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: item.status_damage_emission_id))
                for key, value in status_damage_emissions_by_callback.items()
            },
        )
        object.__setattr__(
            self,
            "_action_delay_emissions",
            {emission.action_delay_emission_id: emission for emission in self.ir.action_delay_emissions},
        )
        action_delay_emissions_by_callback: dict[str, list[ActionDelayEmissionIR]] = {}
        for emission in self.ir.action_delay_emissions:
            action_delay_emissions_by_callback.setdefault(emission.callback_id, []).append(emission)
        object.__setattr__(
            self,
            "_action_delay_emissions_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: item.action_delay_emission_id))
                for key, value in action_delay_emissions_by_callback.items()
            },
        )
        object.__setattr__(
            self,
            "_queue_intents",
            {intent.queue_intent_id: intent for intent in self.ir.queue_intents},
        )
        queue_intents_by_callback: dict[str, list[QueueIntentIR]] = {}
        for intent in self.ir.queue_intents:
            queue_intents_by_callback.setdefault(intent.callback_id, []).append(intent)
        object.__setattr__(
            self,
            "_queue_intents_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: item.queue_intent_id))
                for key, value in queue_intents_by_callback.items()
            },
        )
        object.__setattr__(
            self,
            "_queue_resolutions",
            {resolution.queue_resolution_id: resolution for resolution in self.ir.queue_resolutions},
        )
        object.__setattr__(
            self,
            "_queue_resolution_by_intent",
            {resolution.queue_intent_id: resolution for resolution in self.ir.queue_resolutions},
        )
        object.__setattr__(
            self,
            "_queue_priorities",
            {priority.queue_priority_id: priority for priority in self.ir.queue_priorities},
        )
        object.__setattr__(
            self,
            "_queue_priority_by_table_key",
            {(priority.priority_table, priority.priority_key): priority for priority in self.ir.queue_priorities},
        )
        object.__setattr__(
            self,
            "_queue_windows",
            {window.queue_window_id: window for window in self.ir.queue_windows},
        )
        object.__setattr__(
            self,
            "_queue_window_by_intent",
            {window.queue_intent_id: window for window in self.ir.queue_windows},
        )
        queue_windows_by_family: dict[str, list[QueueWindowIR]] = {}
        for window in self.ir.queue_windows:
            queue_windows_by_family.setdefault(window.window_family, []).append(window)
        object.__setattr__(
            self,
            "_queue_windows_by_family",
            {
                key: tuple(sorted(value, key=lambda item: item.queue_window_id))
                for key, value in queue_windows_by_family.items()
            },
        )
        object.__setattr__(
            self,
            "_queue_lifecycle_policies",
            {policy.queue_lifecycle_policy_id: policy for policy in self.ir.queue_lifecycle_policies},
        )
        queue_lifecycle_policies_by_family: dict[str, list[QueueLifecyclePolicyIR]] = {}
        for policy in self.ir.queue_lifecycle_policies:
            queue_lifecycle_policies_by_family.setdefault(policy.window_family, []).append(policy)
        object.__setattr__(
            self,
            "_queue_lifecycle_policies_by_family",
            {
                key: tuple(sorted(value, key=lambda item: item.queue_lifecycle_policy_id))
                for key, value in queue_lifecycle_policies_by_family.items()
            },
        )
        object.__setattr__(
            self,
            "_queue_lifecycle_policy_by_window",
            {
                policy.queue_window_id: policy
                for policy in self.ir.queue_lifecycle_policies
                if policy.queue_window_id
            },
        )
        object.__setattr__(
            self,
            "_queue_lifecycle_policy_by_intent",
            {
                policy.queue_intent_id: policy
                for policy in self.ir.queue_lifecycle_policies
                if policy.queue_intent_id
            },
        )
        object.__setattr__(
            self,
            "_extra_action_policies",
            {policy.extra_action_policy_id: policy for policy in self.ir.extra_action_policies},
        )
        object.__setattr__(
            self,
            "_extra_action_policy_by_window",
            {
                policy.queue_window_id: policy
                for policy in self.ir.extra_action_policies
                if policy.queue_window_id
            },
        )
        object.__setattr__(
            self,
            "_extra_action_policy_by_intent",
            {
                policy.queue_intent_id: policy
                for policy in self.ir.extra_action_policies
                if policy.queue_intent_id
            },
        )
        object.__setattr__(
            self,
            "_skill_continuations",
            {continuation.continuation_id: continuation for continuation in self.ir.skill_continuations},
        )
        standalone_ability_graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]] = {}
        for graph in self.ir.standalone_ability_graphs:
            standalone_ability_graphs_by_name.setdefault(graph.ability_name, []).append(graph)
        standalone_ability_graphs, standalone_ability_graph_conflicts = _unique_index(
            self.ir.standalone_ability_graphs,
            lambda graph: graph.standalone_ability_graph_id,
        )
        object.__setattr__(self, "_standalone_ability_graphs", standalone_ability_graphs)
        object.__setattr__(
            self,
            "_standalone_ability_graph_conflicts",
            standalone_ability_graph_conflicts,
        )
        object.__setattr__(
            self,
            "_standalone_ability_graphs_by_name",
            {
                key: tuple(sorted(value, key=lambda item: item.standalone_ability_graph_id))
                for key, value in standalone_ability_graphs_by_name.items()
            },
        )
        object.__setattr__(
            self,
            "_combatant_action_sets",
            {action_set.entity_ref: action_set for action_set in self.ir.combatant_action_sets},
        )
        action_admissions, action_admission_conflicts = _unique_index(
            self.ir.action_admissions,
            lambda admission: admission.admission_id,
        )
        object.__setattr__(self, "_action_admissions", action_admissions)
        object.__setattr__(self, "_action_admission_conflicts", action_admission_conflicts)
        action_admissions_by_owner_action: dict[
            tuple[str, str, int], list[ActionAdmissionIR]
        ] = {}
        for admission in self.ir.action_admissions:
            action_admissions_by_owner_action.setdefault(
                (
                    admission.owner_entity_ref,
                    admission.action_id,
                    admission.action_level,
                ),
                [],
            ).append(admission)
        object.__setattr__(
            self,
            "_action_admissions_by_owner_action",
            {
                key: tuple(sorted(value, key=lambda item: item.admission_id))
                for key, value in action_admissions_by_owner_action.items()
            },
        )
        object.__setattr__(
            self,
            "_timeline_rules",
            {rule.timeline_rule_id: rule for rule in self.ir.timeline_rules},
        )
        object.__setattr__(
            self,
            "_resource_rules",
            {rule.resource_rule_id: rule for rule in self.ir.resource_rules},
        )
        battle_state_transitions, battle_state_transition_conflicts = (
            _unique_index(
                self.ir.battle_state_transitions,
                lambda item: item.transition_rule_id,
            )
        )
        object.__setattr__(
            self,
            "_battle_state_transitions",
            battle_state_transitions,
        )
        object.__setattr__(
            self,
            "_battle_state_transition_conflicts",
            battle_state_transition_conflicts,
        )
        battle_state_transitions_by_trigger: dict[
            tuple[str, str], list[BattleStateTransitionIR]
        ] = {}
        battle_state_transitions_by_runtime_event: dict[
            str, list[BattleStateTransitionIR]
        ] = {}
        for transition in self.ir.battle_state_transitions:
            battle_state_transitions_by_trigger.setdefault(
                (transition.trigger_kind, transition.trigger_identity),
                [],
            ).append(transition)
            battle_state_transitions_by_runtime_event.setdefault(
                transition.runtime_event_type,
                [],
            ).append(transition)
        object.__setattr__(
            self,
            "_battle_state_transitions_by_trigger",
            {
                key: tuple(
                    sorted(value, key=lambda item: item.transition_rule_id)
                )
                for key, value in battle_state_transitions_by_trigger.items()
            },
        )
        object.__setattr__(
            self,
            "_battle_state_transitions_by_runtime_event",
            {
                key: tuple(
                    sorted(value, key=lambda item: item.transition_rule_id)
                )
                for key, value in battle_state_transitions_by_runtime_event.items()
            },
        )
        object.__setattr__(
            self,
            "_damage_formula_rules",
            {rule.damage_formula_rule_id: rule for rule in self.ir.damage_formula_rules},
        )
        object.__setattr__(
            self,
            "_damage_route_rules",
            {rule.damage_route_rule_id: rule for rule in self.ir.damage_route_rules},
        )
        object.__setattr__(
            self,
            "_shield_priority_rules",
            {rule.shield_priority_rule_id: rule for rule in self.ir.shield_priority_rules},
        )
        object.__setattr__(
            self,
            "_super_break_emissions",
            {emission.super_break_emission_id: emission for emission in self.ir.super_break_emissions},
        )
        super_break_emissions_by_template: dict[str, list[SuperBreakEmissionIR]] = {}
        for emission in self.ir.super_break_emissions:
            super_break_emissions_by_template.setdefault(emission.template_id, []).append(emission)
        object.__setattr__(
            self,
            "_super_break_emissions_by_template",
            {
                key: tuple(sorted(value, key=lambda item: item.super_break_emission_id))
                for key, value in super_break_emissions_by_template.items()
            },
        )
        target_expressions, target_expression_conflicts = _unique_index(
            self.ir.target_expressions,
            lambda expression: expression.target_expression_id,
        )
        object.__setattr__(self, "_target_expressions", target_expressions)
        object.__setattr__(self, "_target_expression_conflicts", target_expression_conflicts)
        target_expressions_by_source: dict[tuple[str, str], list[TargetExpressionIR]] = {}
        for expression in self.ir.target_expressions:
            json_path = expression.source.evidence.get("json_path")
            if not isinstance(json_path, str) or not json_path:
                raise ValueError("target expression source JSON path is missing")
            target_expressions_by_source.setdefault(
                (expression.source.source_path, json_path),
                [],
            ).append(expression)
        object.__setattr__(
            self,
            "_target_expressions_by_source",
            {
                key: tuple(sorted(values, key=lambda item: item.target_expression_id))
                for key, values in target_expressions_by_source.items()
            },
        )
        object.__setattr__(
            self,
            "_target_language_expressions",
            tuple(
                expression
                for expression in self.ir.target_expressions
                if expression.source.source_path in {
                    "Config/GlobalConfig/TargetAliasConfig.json",
                    "Config/GlobalConfig/TargetOperationConfig.json",
                }
                or expression.source.evidence.get("source_raw_type") == "GlobalTargetAlias"
                or expression.source.raw_type == "GlobalTargetAlias"
            ),
        )
        wave_definitions_by_stage: dict[str, list[WaveDefinitionIR]] = {}
        wave_entries_by_definition_wave: dict[tuple[str, int], list[WaveMonsterEntryIR]] = {}
        for definition in self.ir.wave_definitions:
            wave_definitions_by_stage.setdefault(definition.stage_id, []).append(definition)
            for entry in definition.entries:
                wave_entries_by_definition_wave.setdefault(
                    (definition.wave_definition_id, entry.wave_index),
                    [],
                ).append(entry)
        object.__setattr__(
            self,
            "_wave_definitions",
            {definition.wave_definition_id: definition for definition in self.ir.wave_definitions},
        )
        object.__setattr__(
            self,
            "_wave_definitions_by_stage",
            {
                stage_id: tuple(sorted(definitions, key=lambda item: item.wave_definition_id))
                for stage_id, definitions in wave_definitions_by_stage.items()
            },
        )
        object.__setattr__(
            self,
            "_wave_entries_by_definition_wave",
            {
                key: tuple(sorted(entries, key=lambda item: (item.position, item.entry_id)))
                for key, entries in wave_entries_by_definition_wave.items()
            },
        )
        object.__setattr__(self, "_effects", {effect.effect_id: effect for effect in self.ir.effects})
        conditions, condition_conflicts = _unique_index(
            self.ir.conditions,
            lambda condition: condition.condition_id,
        )
        object.__setattr__(self, "_conditions", conditions)
        object.__setattr__(self, "_condition_conflicts", condition_conflicts)
        object.__setattr__(self, "_triggers", {trigger.trigger_id: trigger for trigger in self.ir.triggers})
        formulas, formula_conflicts = _unique_index(
            self.ir.formulas,
            lambda formula: formula.formula_id,
        )
        object.__setattr__(self, "_formulas", formulas)
        object.__setattr__(self, "_formula_conflicts", formula_conflicts)
        triggers_by_modifier: dict[str, list[TriggerIR]] = {}
        triggers_by_modifier_event: dict[tuple[str, str], list[TriggerIR]] = {}
        for trigger in self.ir.triggers:
            modifier_name = trigger.modifier_name
            if not modifier_name:
                continue
            triggers_by_modifier.setdefault(modifier_name, []).append(trigger)
            triggers_by_modifier_event.setdefault((modifier_name, trigger.event), []).append(trigger)
        object.__setattr__(
            self,
            "_triggers_by_modifier",
            {key: tuple(value) for key, value in triggers_by_modifier.items()},
        )
        object.__setattr__(
            self,
            "_triggers_by_modifier_event",
            {key: tuple(value) for key, value in triggers_by_modifier_event.items()},
        )

    def character_ability_source_graph_query(
        self,
    ) -> CharacterAbilitySourceGraphQuery | None:
        return self._character_ability_source_graph_query

    def task_graph_query(self) -> TaskGraphQuery | None:
        return self._task_graph_query

    def query_task_graph(self, graph_id: str) -> TaskGraphQueryResult:
        if self._task_graph_query is None:
            return TaskGraphQueryResult("blocked", "graph", (), None, "task_graph_catalog_not_installed")
        return self._task_graph_query.query_graph(graph_id)

    def query_task_graph_entry(
        self,
        entry_kind: Literal["ability_phase_callback", "status_callback"],
        owner_id: str,
        callback_kind: str,
    ) -> TaskGraphQueryResult:
        if self._task_graph_query is None:
            return TaskGraphQueryResult("blocked", "entry", (), None, "task_graph_catalog_not_installed")
        return self._task_graph_query.query_entry(entry_kind, owner_id, callback_kind)

    def query_formal_task_graph(
        self,
        entry_kind: Literal["ability_phase_callback", "status_callback"],
        owner_id: str,
        callback_kind: str,
        formal_task_ids: Iterable[str],
    ) -> TaskGraphQueryResult:
        selected = tuple(formal_task_ids)
        if (
            not selected
            or any(not isinstance(item, str) or not item for item in selected)
            or len(selected) != len(set(selected))
        ):
            return TaskGraphQueryResult(
                "blocked",
                "graph",
                (),
                None,
                "formal_task_graph_selection_invalid",
            )
        entry_result = self.query_task_graph_entry(
            entry_kind,
            owner_id,
            callback_kind,
        )
        entry = entry_result.value
        if (
            entry_result.status != "resolved"
            or type(entry) is not TaskGraphEntryMaterializationIR
            or entry.status != "materialized"
        ):
            return TaskGraphQueryResult(
                "blocked",
                "graph",
                (),
                None,
                entry_result.blocked_reason
                or "formal_task_graph_entry_not_materialized",
            )
        graph_result = self.query_task_graph(entry.graph_id)
        graph = graph_result.value
        if graph_result.status != "resolved" or type(graph) is not TaskGraphIR:
            return graph_result
        expected = set(selected)
        if (
            graph.entry_id != entry.entry_id
            or graph.entry_kind != entry_kind
            or graph.owner_id != owner_id
            or graph.callback_kind != callback_kind
            or set(entry.formal_task_ids) != expected
            or {node.formal_task_id for node in graph.nodes} != expected
        ):
            return TaskGraphQueryResult(
                "blocked",
                "graph",
                (graph.graph_id,),
                None,
                "formal_task_graph_identity_mismatch",
            )
        return graph_result

    def query_task_graph_node(self, graph_node_id: str) -> TaskGraphQueryResult:
        if self._task_graph_query is None:
            return TaskGraphQueryResult("blocked", "node", (), None, "task_graph_catalog_not_installed")
        return self._task_graph_query.query_node(graph_node_id)

    def query_character_action_source(
        self,
        owner_avatar_id: str,
        action_id: str,
    ) -> CharacterAbilitySourceGraphQueryResult:
        query = self._character_ability_source_graph_query
        if query is None:
            return CharacterAbilitySourceGraphQuery._blocked(
                owner_avatar_id=owner_avatar_id,
                action_id=action_id,
                reason="character_ability_source_graph_not_installed",
            )
        return query.query_action(owner_avatar_id, action_id)

    def query_character_standalone_ability(
        self,
        owner_avatar_id: str,
        ability_name: str,
    ) -> CharacterAbilitySourceGraphQueryResult:
        query = self._character_ability_source_graph_query
        if query is None:
            return CharacterAbilitySourceGraphQuery._blocked(
                owner_avatar_id=owner_avatar_id,
                ability_name=ability_name,
                reason="character_ability_source_graph_not_installed",
            )
        return query.query_standalone_ability(owner_avatar_id, ability_name)

    def character_ability_definition(
        self,
        definition_id: str,
    ) -> CharacterAbilityDefinitionIR | None:
        return self._character_ability_definitions.get(definition_id)

    def character_ability_source(
        self,
        source_id: str,
    ) -> CharacterAbilitySourceIR | None:
        return self._character_ability_sources.get(source_id)

    def character_ability_binding(
        self,
        binding_id: str,
    ) -> CharacterAbilityBindingIR | None:
        return self._character_ability_bindings.get(binding_id)

    def character_ability_source_graph(
        self,
        graph_id: str,
    ) -> CharacterAbilitySourceGraphIR | None:
        return self._character_ability_source_graphs.get(graph_id)

    def entity(self, entity_id: str) -> RuleEntity | None:
        return self._entities.get(entity_id)

    def require_entity(self, entity_id: str, expected_types: set[str] | tuple[str, ...] | None = None) -> RuleEntity:
        entity = self.entity(entity_id)
        if entity is None:
            raise KeyError(f"unknown rule entity {entity_id!r}")
        if expected_types is not None and entity.entity_type not in set(expected_types):
            raise TypeError(
                f"rule entity {entity_id!r} has type {entity.entity_type!r}, "
                f"expected one of {sorted(set(expected_types))}"
            )
        return entity

    def entities_by_type(self, entity_type: str) -> tuple[RuleEntity, ...]:
        return tuple(entity for entity in self.ir.entities if entity.entity_type == entity_type)

    def is_entity_type(self, entity_id: str, expected_types: set[str] | tuple[str, ...]) -> bool:
        entity = self.entity(entity_id)
        return bool(entity and entity.entity_type in set(expected_types))

    def source_trace(self, entity_id: str) -> dict[str, object] | None:
        entity = self.entity(entity_id)
        if not entity:
            return None
        return {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "coverage_status": entity.coverage_status,
            "source": entity.source.to_json(),
        }

    def combatant_profile(self, entity_id: str) -> CombatantProfileIR | None:
        return self._combatant_profiles.get(entity_id)

    def combatant_profile_by_profile_id(self, profile_id: str) -> CombatantProfileIR | None:
        return self._combatant_profiles_by_profile_id.get(profile_id)

    def avatar_profile(self, avatar_id: str) -> AvatarProfileIR | None:
        return self._avatar_profiles.get(avatar_id)

    def avatar_profile_by_profile_id(self, profile_id: str) -> AvatarProfileIR | None:
        return self._avatar_profiles_by_profile_id.get(profile_id)

    def character_data_card(self, card_id: str) -> CharacterDataCardIR | None:
        return self._character_data_cards.get(card_id)

    def character_data_card_for_entity(self, entity_ref: str) -> CharacterDataCardIR | None:
        return self._character_data_cards_by_entity_ref.get(entity_ref)

    def character_dynamic_value_bindings_for_card(self, card_id: str) -> dict[str, JSONValue]:
        card = self.character_data_card(card_id)
        if card is None:
            return {}
        bindings = card.dynamic_value_bindings
        if not isinstance(bindings, dict):
            return {}
        return _json_object_copy(bindings)

    def monster_data_card(self, card_id: str) -> MonsterDataCardIR | None:
        return self._monster_data_cards.get(card_id)

    def monster_data_card_for_entity(self, entity_ref: str) -> MonsterDataCardIR | None:
        return self._monster_data_cards_by_entity_ref.get(entity_ref)

    def equipment_definitions(self) -> tuple[EquipmentDefinition, ...]:
        return self._equipment_definitions

    def character_equipment_eligibility(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[CharacterEquipmentEligibilityIR]:
        key = EquipmentDefinitionKey("character_equipment_eligibility", definition_identity)
        return self._equipment_definition_resolution(key, CharacterEquipmentEligibilityIR)

    def character_equipment_eligibility_for_card(
        self,
        card_id: str,
    ) -> EquipmentDefinitionResolution[CharacterEquipmentEligibilityIR]:
        card = self.character_data_card(card_id)
        if card is None:
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=EquipmentDefinitionKey("character_equipment_eligibility", card_id),
                expected_kind="character_equipment_eligibility",
                value=None,
                blocked_reason="character_data_card_missing",
            )
        if not card.equipment_eligibility_id:
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=EquipmentDefinitionKey("character_equipment_eligibility", card.card_id),
                expected_kind="character_equipment_eligibility",
                value=None,
                blocked_reason="character_equipment_eligibility_unbound",
            )
        resolution = self.character_equipment_eligibility(card.equipment_eligibility_id)
        if (
            resolution.resolution_status == "resolved"
            and resolution.value is not None
            and resolution.value.character_card_id != card.card_id
        ):
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=resolution.requested_key,
                expected_kind="character_equipment_eligibility",
                value=None,
                candidates=resolution.candidates,
                blocked_reason="character_equipment_eligibility_owner_mismatch",
            )
        if resolution.resolution_status == "resolved" and resolution.value is not None:
            profile = self.avatar_profile_by_profile_id(card.profile_id)
            if profile is None:
                return EquipmentDefinitionResolution(
                    resolution_status="blocked",
                    requested_key=resolution.requested_key,
                    expected_kind="character_equipment_eligibility",
                    value=None,
                    candidates=resolution.candidates,
                    blocked_reason="character_equipment_eligibility_profile_missing",
                )
            eligibility = resolution.value
            if eligibility.character_profile_id != profile.avatar_profile_id:
                return EquipmentDefinitionResolution(
                    resolution_status="blocked",
                    requested_key=resolution.requested_key,
                    expected_kind="character_equipment_eligibility",
                    value=None,
                    candidates=resolution.candidates,
                    blocked_reason="character_equipment_eligibility_profile_mismatch",
                )
            if (
                eligibility.character_path_type != profile.base_type
                or eligibility.character_path_type
                not in eligibility.passive_activation_path_types
            ):
                return EquipmentDefinitionResolution(
                    resolution_status="blocked",
                    requested_key=resolution.requested_key,
                    expected_kind="character_equipment_eligibility",
                    value=None,
                    candidates=resolution.candidates,
                    blocked_reason="character_equipment_eligibility_path_mismatch",
                )
            if eligibility.source != profile.source:
                return EquipmentDefinitionResolution(
                    resolution_status="blocked",
                    requested_key=resolution.requested_key,
                    expected_kind="character_equipment_eligibility",
                    value=None,
                    candidates=resolution.candidates,
                    blocked_reason="character_equipment_eligibility_source_mismatch",
                )
        return resolution

    def light_cone_definition(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[LightConeDefinitionIR]:
        key = EquipmentDefinitionKey("light_cone", definition_identity)
        return self._equipment_definition_resolution(key, LightConeDefinitionIR)

    def relic_domain_definition(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[RelicDomainDefinitionIR]:
        key = EquipmentDefinitionKey("relic_domain", definition_identity)
        return self._equipment_definition_resolution(key, RelicDomainDefinitionIR)

    def relic_slot_definition(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[RelicSlotDefinitionIR]:
        key = EquipmentDefinitionKey("relic_slot", definition_identity)
        return self._equipment_definition_resolution(key, RelicSlotDefinitionIR)

    def relic_main_affix_group_definition(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[RelicMainAffixGroupDefinitionIR]:
        key = EquipmentDefinitionKey("relic_main_affix_group", definition_identity)
        return self._equipment_definition_resolution(
            key,
            RelicMainAffixGroupDefinitionIR,
        )

    def relic_main_affix_definition(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[RelicMainAffixDefinitionIR]:
        key = EquipmentDefinitionKey("relic_main_affix", definition_identity)
        return self._equipment_definition_resolution(
            key,
            RelicMainAffixDefinitionIR,
        )

    def relic_sub_affix_group_definition(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[RelicSubAffixGroupDefinitionIR]:
        key = EquipmentDefinitionKey("relic_sub_affix_group", definition_identity)
        return self._equipment_definition_resolution(
            key,
            RelicSubAffixGroupDefinitionIR,
        )

    def relic_sub_affix_definition(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[RelicSubAffixDefinitionIR]:
        key = EquipmentDefinitionKey("relic_sub_affix", definition_identity)
        return self._equipment_definition_resolution(
            key,
            RelicSubAffixDefinitionIR,
        )

    def relic_template_definition(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[RelicTemplateDefinitionIR]:
        key = EquipmentDefinitionKey("relic_template", definition_identity)
        return self._equipment_definition_resolution(key, RelicTemplateDefinitionIR)

    def relic_set_definition(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[RelicSetDefinitionIR]:
        key = EquipmentDefinitionKey("relic_set", definition_identity)
        return self._equipment_definition_resolution(key, RelicSetDefinitionIR)

    def relic_set_threshold(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[RelicSetThresholdIR]:
        key = EquipmentDefinitionKey("relic_set_threshold", definition_identity)
        return self._equipment_definition_resolution(key, RelicSetThresholdIR)

    def equipment_mechanism_ref(
        self,
        definition_identity: str,
    ) -> EquipmentDefinitionResolution[EquipmentMechanismRefIR]:
        key = EquipmentDefinitionKey("equipment_mechanism", definition_identity)
        return self._equipment_definition_resolution(key, EquipmentMechanismRefIR)

    def equipment_ability_parameter_read(
        self,
        parameter_read_id: str,
    ) -> EquipmentAbilityParameterReadIR | None:
        return self._equipment_parameter_reads.get(parameter_read_id)

    def equipment_dynamic_parameter_context(
        self,
        target_definition_key: EquipmentDefinitionKey,
        parameter_basis: EquipmentParameterBasis,
    ) -> tuple[EquipmentDynamicParameterContext | None, str]:
        if not isinstance(target_definition_key, EquipmentDefinitionKey):
            return None, "equipment_parameter_target_key_invalid"
        if isinstance(parameter_basis, LightConeRankParameterBasis):
            if (
                target_definition_key.definition_kind != "light_cone"
                or parameter_basis.definition_key != target_definition_key
            ):
                return None, "equipment_parameter_basis_target_mismatch"
            resolution = self.light_cone_definition(
                target_definition_key.definition_identity
            )
            definition = resolution.value
            if resolution.resolution_status != "resolved" or definition is None:
                return (
                    None,
                    resolution.blocked_reason
                    or "equipment_parameter_definition_unresolved",
                )
            if definition.skill_id != parameter_basis.skill_id:
                return None, "equipment_parameter_skill_identity_mismatch"
            ranks = tuple(
                rank
                for rank in definition.superimposition_levels
                if rank.level == parameter_basis.superimposition_level
                and rank.skill_id == parameter_basis.skill_id
            )
            if len(ranks) != 1:
                return None, "equipment_parameter_rank_unresolved"
            if ranks[0].source != parameter_basis.source:
                return None, "equipment_parameter_basis_source_mismatch"
            parameters: tuple[
                LightConeParameterIR | RelicSetParameterIR,
                ...,
            ] = ranks[0].parameters
            mechanism_ref_ids = definition.mechanism_ref_ids
            ability_source = definition.ability_source
        elif isinstance(
            parameter_basis,
            RelicSetThresholdParameterBasis,
        ):
            if (
                target_definition_key.definition_kind
                != "relic_set_threshold"
                or parameter_basis.threshold_key != target_definition_key
            ):
                return None, "equipment_parameter_basis_target_mismatch"
            resolution = self.relic_set_threshold(
                target_definition_key.definition_identity
            )
            threshold = resolution.value
            if resolution.resolution_status != "resolved" or threshold is None:
                return (
                    None,
                    resolution.blocked_reason
                    or "equipment_parameter_definition_unresolved",
                )
            if (
                threshold.set_key != parameter_basis.set_key
                or threshold.require_count != parameter_basis.required_count
                or threshold.source != parameter_basis.source
            ):
                return None, "equipment_parameter_basis_source_mismatch"
            parameters = threshold.parameters
            mechanism_ref_ids = threshold.mechanism_ref_ids
            ability_source = threshold.ability_source
        else:
            return None, "equipment_parameter_basis_type_invalid"
        if ability_source is None:
            return None, "equipment_parameter_ability_source_missing"
        if len(mechanism_ref_ids) != 1:
            return None, "equipment_parameter_mechanism_not_unique"
        mechanism_resolution = self.equipment_mechanism_ref(
            mechanism_ref_ids[0].definition_identity
        )
        mechanism = mechanism_resolution.value
        if (
            mechanism_resolution.resolution_status != "resolved"
            or mechanism is None
        ):
            return (
                None,
                mechanism_resolution.blocked_reason
                or "equipment_parameter_mechanism_unresolved",
            )
        graph = self.standalone_ability_graph(mechanism.graph_ref_id)
        if (
            graph is None
            or graph.source != ability_source.source
            or mechanism.source != ability_source.source
        ):
            return None, "equipment_parameter_graph_source_mismatch"
        return (
            EquipmentDynamicParameterContext(
                target_definition_key=target_definition_key,
                parameter_basis=parameter_basis,
                parameters=parameters,
                mechanism_ref=mechanism,
                graph=graph,
            ),
            "",
        )

    def equipment_parameter_read_matches_basis(
        self,
        parameter_read: EquipmentAbilityParameterReadIR,
        parameter_basis: EquipmentParameterBasis,
    ) -> bool:
        if isinstance(parameter_basis, LightConeRankParameterBasis):
            return bool(
                parameter_read.parameter_basis_kind == "light_cone_rank"
                and not parameter_read.parameter_basis_identity
            )
        if isinstance(
            parameter_basis,
            RelicSetThresholdParameterBasis,
        ):
            return bool(
                parameter_read.parameter_basis_kind
                == "relic_set_threshold"
                and parameter_read.parameter_basis_identity
                == parameter_basis.threshold_key.definition_identity
            )
        return False

    def _equipment_definition_resolution(
        self,
        key: EquipmentDefinitionKey,
        expected_type: type[EquipmentDefinitionT],
    ) -> EquipmentDefinitionResolution[EquipmentDefinitionT]:
        exact_candidates = self._equipment_definitions_by_key.get(key, ())
        if not exact_candidates:
            diagnostic_candidates = self._equipment_definitions_by_identity.get(
                key.definition_identity,
                (),
            )
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=key,
                expected_kind=key.definition_kind,
                value=None,
                candidates=tuple(
                    EquipmentResolutionCandidate.from_definition(candidate)
                    for candidate in diagnostic_candidates
                ),
                blocked_reason=(
                    "equipment_definition_kind_mismatch"
                    if diagnostic_candidates
                    else "equipment_definition_missing"
                ),
            )
        candidates = tuple(
            EquipmentResolutionCandidate.from_definition(candidate)
            for candidate in exact_candidates
        )
        if len(exact_candidates) != 1:
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=key,
                expected_kind=key.definition_kind,
                value=None,
                candidates=candidates,
                blocked_reason="equipment_definition_ambiguous",
            )
        selected = exact_candidates[0]
        if type(selected) is not expected_type:
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=key,
                expected_kind=key.definition_kind,
                value=None,
                candidates=candidates,
                blocked_reason="equipment_definition_object_type_mismatch",
            )
        if selected.definition_key != key:
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=key,
                expected_kind=key.definition_kind,
                value=None,
                candidates=candidates,
                blocked_reason="equipment_definition_canonical_key_mismatch",
            )
        if selected.coverage_status not in EQUIPMENT_RESOLVABLE_COVERAGE_STATES:
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=key,
                expected_kind=key.definition_kind,
                value=None,
                candidates=candidates,
                blocked_reason="equipment_definition_not_lowered",
            )
        if key in self._relic_reference_issues_by_key:
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=key,
                expected_kind=key.definition_kind,
                value=None,
                candidates=candidates,
                blocked_reason=(
                    "equipment_definition_reference_closure_invalid"
                ),
            )
        if isinstance(selected, EquipmentMechanismRefIR):
            graph = self.standalone_ability_graph(selected.graph_ref_id)
            if graph is None:
                return EquipmentDefinitionResolution(
                    resolution_status="blocked",
                    requested_key=key,
                    expected_kind=key.definition_kind,
                    value=None,
                    candidates=candidates,
                    blocked_reason="equipment_mechanism_graph_missing_or_duplicate",
                )
            if graph.source != selected.source:
                return EquipmentDefinitionResolution(
                    resolution_status="blocked",
                    requested_key=key,
                    expected_kind=key.definition_kind,
                    value=None,
                    candidates=candidates,
                    blocked_reason="equipment_mechanism_graph_source_mismatch",
                )
            if selected.coverage_status == "executable":
                graph_reason = self._equipment_graph_runtime_closure_reason(graph)
                if graph_reason:
                    return EquipmentDefinitionResolution(
                        resolution_status="blocked",
                        requested_key=key,
                        expected_kind=key.definition_kind,
                        value=None,
                        candidates=candidates,
                        blocked_reason=graph_reason,
                    )
            parameter_reads = tuple(
                self.equipment_ability_parameter_read(binding_id)
                for binding_id in selected.parameter_binding_ids
            )
            if any(
                read is None
                or read.graph_ref_id != selected.graph_ref_id
                or not _equipment_parameter_read_matches_graph(read, graph)
                for read in parameter_reads
            ):
                return EquipmentDefinitionResolution(
                    resolution_status="blocked",
                    requested_key=key,
                    expected_kind=key.definition_kind,
                    value=None,
                    candidates=candidates,
                    blocked_reason="equipment_mechanism_parameter_read_unresolved",
                )
        mechanism_ref_ids = getattr(selected, "mechanism_ref_ids", ())
        if len(mechanism_ref_ids) != len(set(mechanism_ref_ids)):
            return EquipmentDefinitionResolution(
                resolution_status="blocked",
                requested_key=key,
                expected_kind=key.definition_kind,
                value=None,
                candidates=candidates,
                blocked_reason="equipment_mechanism_reference_duplicate",
            )
        for mechanism_key in mechanism_ref_ids:
            mechanism_resolution = self._equipment_definition_resolution(
                mechanism_key,
                EquipmentMechanismRefIR,
            )
            if mechanism_resolution.resolution_status != "resolved":
                return EquipmentDefinitionResolution(
                    resolution_status="blocked",
                    requested_key=key,
                    expected_kind=key.definition_kind,
                    value=None,
                    candidates=candidates,
                    blocked_reason="equipment_mechanism_reference_unresolved",
                )
            if isinstance(
                selected,
                (LightConeDefinitionIR, RelicSetThresholdIR),
            ) and (
                selected.ability_source is None
                or mechanism_resolution.value is None
                or mechanism_resolution.value.source
                != selected.ability_source.source
            ):
                return EquipmentDefinitionResolution(
                    resolution_status="blocked",
                    requested_key=key,
                    expected_kind=key.definition_kind,
                    value=None,
                    candidates=candidates,
                    blocked_reason="equipment_mechanism_reference_source_mismatch",
                )
        return EquipmentDefinitionResolution(
            resolution_status="resolved",
            requested_key=key,
            expected_kind=key.definition_kind,
            value=selected,
            candidates=candidates,
        )

    def _equipment_graph_runtime_closure_reason(
        self,
        graph: StandaloneAbilityGraphIR,
    ) -> str:
        if graph.coverage_status != "executable" or graph.blocked_reason:
            return "equipment_mechanism_graph_not_executable"
        if len(graph.task_ids) != len(set(graph.task_ids)) or len(
            graph.status_callback_ids
        ) != len(set(graph.status_callback_ids)):
            return "equipment_mechanism_graph_runtime_reference_duplicate"
        tasks = tuple(self.ability_task(task_id) for task_id in graph.task_ids)
        if any(task is None for task in tasks):
            return "equipment_mechanism_graph_task_missing"
        executable_task_ids = tuple(
            task.task_id
            for task in tasks
            if task is not None and task.coverage_status == "executable"
        )
        if executable_task_ids != graph.executable_task_ids:
            return "equipment_mechanism_graph_task_admission_mismatch"
        callbacks = tuple(
            self.status_callback(callback_id)
            for callback_id in graph.status_callback_ids
        )
        if any(callback is None for callback in callbacks):
            return "equipment_mechanism_graph_callback_missing"
        if any(
            callback is not None
            and (
                callback.coverage_status != "executable"
                or callback.admission_status != "executable"
                or not _equipment_callback_matches_graph(callback, graph)
            )
            for callback in callbacks
        ):
            return "equipment_mechanism_graph_callback_admission_mismatch"
        non_gameplay_callbacks = tuple(
            self.status_callback(callback_id)
            for callback_id in graph.non_gameplay_callback_ids
        )
        if any(callback is None for callback in non_gameplay_callbacks):
            return "equipment_mechanism_graph_non_gameplay_callback_missing"
        if any(
            callback is not None
            and (
                callback.blocked_reason != "equipment_event_family_non_gameplay"
                or not _equipment_callback_matches_graph(callback, graph)
            )
            for callback in non_gameplay_callbacks
        ):
            return "equipment_mechanism_graph_non_gameplay_classification_mismatch"
        if not graph.task_ids and not graph.status_callback_ids:
            return "equipment_mechanism_graph_runtime_nodes_missing"
        return ""

    def summon_unit_definition(self, summon_definition_id: str) -> SummonUnitDefinitionIR | None:
        return self._summon_unit_definitions.get(summon_definition_id)

    def summon_unit_definition_for_unit_id(self, summon_unit_id: str) -> SummonUnitDefinitionIR | None:
        return self._summon_unit_definitions_by_unit_id.get(summon_unit_id)

    def summon_unit_definitions(self) -> tuple[SummonUnitDefinitionIR, ...]:
        return tuple(sorted(self.ir.summon_unit_definitions, key=lambda item: item.summon_definition_id))

    def unit_birth_template(self, birth_template_id: str) -> UnitBirthTemplateIR | None:
        return self._unit_birth_templates.get(birth_template_id)

    def unit_birth_templates(self) -> tuple[UnitBirthTemplateIR, ...]:
        return tuple(sorted(self.ir.unit_birth_templates, key=lambda item: item.birth_template_id))

    def summon_monster_intent(self, summon_intent_id: str) -> SummonMonsterIntentIR | None:
        return self._summon_monster_intents.get(summon_intent_id)

    def summon_monster_intents(self) -> tuple[SummonMonsterIntentIR, ...]:
        return tuple(sorted(self.ir.summon_monster_intents, key=lambda item: item.summon_intent_id))

    def summon_monster_intents_for_task(self, source_task_id: str) -> tuple[SummonMonsterIntentIR, ...]:
        return self._summon_monster_intents_by_task.get(source_task_id, ())

    def assistant_ability_resolution(self, assistant_resolution_id: str) -> AssistantAbilityResolutionIR | None:
        return self._assistant_ability_resolutions.get(assistant_resolution_id)

    def assistant_ability_resolution_for_intent(self, queue_intent_id: str) -> AssistantAbilityResolutionIR | None:
        return self._assistant_ability_resolution_by_intent.get(queue_intent_id)

    def assistant_ability_resolutions_for_ability(self, assistant_ability_id: str) -> tuple[AssistantAbilityResolutionIR, ...]:
        return self._assistant_ability_resolutions_by_ability_id.get(assistant_ability_id, ())

    def assistant_ability_resolutions(self) -> tuple[AssistantAbilityResolutionIR, ...]:
        return tuple(sorted(self.ir.assistant_ability_resolutions, key=lambda item: item.assistant_resolution_id))

    def servant_definition(self, servant_definition_id: str) -> ServantDefinitionIR | None:
        return self._servant_definitions.get(servant_definition_id) or self._servant_definitions_by_ref.get(servant_definition_id)

    def servant_definitions_for_owner(self, owner_entity_ref: str) -> tuple[ServantDefinitionIR, ...]:
        return self._servant_definitions_by_owner.get(owner_entity_ref, ())

    def servant_owner_relation(
        self,
        owner_relation_id: str,
    ) -> ServantOwnerRelationIR | None:
        return self._servant_owner_relations.get(owner_relation_id)

    def servant_definitions_for_owned_skill(
        self,
        owner_entity_ref: str,
        skill_id: str,
    ) -> tuple[ServantDefinitionIR, ...]:
        return self._servant_definitions_by_owned_skill.get(
            (owner_entity_ref, skill_id),
            (),
        )

    def servant_definitions(self) -> tuple[ServantDefinitionIR, ...]:
        return tuple(sorted(self.ir.servant_definitions, key=lambda item: item.servant_definition_id))

    def character_mechanism_slot(self, mechanism_slot_id: str) -> CharacterMechanismSlotIR | None:
        return self._character_mechanism_slots.get(mechanism_slot_id)

    def character_mechanism_slots_for_card(self, card_id: str) -> tuple[CharacterMechanismSlotIR, ...]:
        return self._character_mechanism_slots_by_card.get(card_id, ())

    def passive_mechanism_slot(self, passive_slot_id: str) -> PassiveMechanismSlotIR | None:
        return self._passive_mechanism_slots.get(passive_slot_id)

    def passive_mechanism_slots_for_card(self, data_card_id: str) -> tuple[PassiveMechanismSlotIR, ...]:
        return self._passive_mechanism_slots_by_card.get(data_card_id, ())

    def passive_mechanism_slots_for_owner(self, owner_entity_ref: str) -> tuple[PassiveMechanismSlotIR, ...]:
        return self._passive_mechanism_slots_by_owner.get(owner_entity_ref, ())

    def character_trace_node(self, trace_node_id: str) -> CharacterTraceNodeIR | None:
        return self._character_trace_nodes.get(trace_node_id)

    def character_trace_nodes_for_card(self, card_id: str) -> tuple[CharacterTraceNodeIR, ...]:
        return self._character_trace_nodes_by_card.get(card_id, ())

    def character_eidolon_slot(self, eidolon_slot_id: str) -> CharacterEidolonSlotIR | None:
        return self._character_eidolon_slots.get(eidolon_slot_id)

    def character_eidolon_slots_for_card(self, card_id: str) -> tuple[CharacterEidolonSlotIR, ...]:
        return self._character_eidolon_slots_by_card.get(card_id, ())

    def character_eidolon_slots_for_level(self, card_id: str, eidolon_level: int) -> tuple[CharacterEidolonSlotIR, ...]:
        if eidolon_level < 0 or eidolon_level > 6:
            raise ValueError(f"eidolon_level must be between 0 and 6, got {eidolon_level!r}")
        return tuple(slot for slot in self.character_eidolon_slots_for_card(card_id) if slot.rank <= eidolon_level)

    def character_build_binding(
        self,
        build_binding_id: str,
    ) -> CharacterBuildBindingIR | None:
        return self._character_build_bindings.get(build_binding_id)

    def character_build_bindings_for_card(
        self,
        card_id: str,
    ) -> tuple[CharacterBuildBindingIR, ...]:
        return self._character_build_bindings_by_card.get(card_id, ())

    def character_build_bindings_for_selection(
        self,
        selection_ref_id: str,
    ) -> tuple[CharacterBuildBindingIR, ...]:
        return self._character_build_bindings_by_selection.get(
            selection_ref_id,
            (),
        )

    def character_build_selector_relation(
        self,
        selector_relation_id: str,
    ) -> CharacterBuildSelectorRelationIR | None:
        return self._character_build_selector_relations.get(selector_relation_id)

    def character_build_selector_relations_for_card(
        self,
        card_id: str,
    ) -> tuple[CharacterBuildSelectorRelationIR, ...]:
        return self._character_build_selector_relations_by_card.get(card_id, ())

    def character_build_selector_relations_for_selection(
        self,
        selection_ref_id: str,
    ) -> tuple[CharacterBuildSelectorRelationIR, ...]:
        return self._character_build_selector_relations_by_selection.get(
            selection_ref_id,
            (),
        )

    def character_build_selector_gaps_for_card(
        self,
        card_id: str,
    ) -> tuple[CharacterBuildSelectorGapIR, ...]:
        return self._character_build_selector_gaps_by_card.get(card_id, ())

    def require_combatant_profile(self, entity_id: str) -> CombatantProfileIR:
        profile = self.combatant_profile(entity_id)
        if profile is None:
            raise KeyError(f"unknown combatant profile {entity_id!r}")
        return profile

    def effect(self, effect_id: str) -> EffectIR | None:
        return self._effects.get(effect_id)

    def condition(self, condition_id: str) -> ConditionIR | None:
        return self._conditions.get(condition_id)

    def condition_resolution(self, condition_id: str) -> tuple[ConditionIR | None, str]:
        if condition_id in self._condition_conflicts:
            return None, "condition_reference_ambiguous"
        condition = self._conditions.get(condition_id)
        return (condition, "" if condition is not None else "condition_reference_missing")

    def trigger(self, trigger_id: str) -> TriggerIR | None:
        return self._triggers.get(trigger_id)

    def formula(self, formula_id: str) -> FormulaIR | None:
        return self._formulas.get(formula_id)

    def formula_resolution(self, formula_id: str) -> tuple[FormulaIR | None, str]:
        if formula_id in self._formula_conflicts:
            return None, "formula_reference_ambiguous"
        formula = self._formulas.get(formula_id)
        return (formula, "" if formula is not None else "formula_reference_missing")

    def target_expression(self, target_expression_id: str) -> TargetExpressionIR | None:
        return self._target_expressions.get(target_expression_id)

    def target_expression_resolution(
        self,
        target_expression_id: str,
    ) -> tuple[TargetExpressionIR | None, str]:
        if target_expression_id in self._target_expression_conflicts:
            return None, "target_expression_reference_ambiguous"
        expression = self._target_expressions.get(target_expression_id)
        return (
            expression,
            "" if expression is not None else "target_expression_reference_missing",
        )

    def target_expressions(self) -> tuple[TargetExpressionIR, ...]:
        return self.ir.target_expressions

    def target_language_expressions(self) -> tuple[TargetExpressionIR, ...]:
        """Return source-closed global target definitions without rescanning IR."""
        return self._target_language_expressions

    def target_expressions_for_source(
        self,
        source_path: str,
        json_path: str,
    ) -> tuple[TargetExpressionIR, ...]:
        """Return the exact target expressions lowered from one raw node path."""
        if not isinstance(source_path, str) or not source_path:
            raise ValueError("target source path is required")
        if not isinstance(json_path, str) or not json_path:
            raise ValueError("target JSON path is required")
        return self._target_expressions_by_source.get((source_path, json_path), ())

    def wave_definition(self, wave_definition_id: str) -> WaveDefinitionIR | None:
        return self._wave_definitions.get(wave_definition_id)

    def wave_definitions(self) -> tuple[WaveDefinitionIR, ...]:
        return tuple(sorted(self.ir.wave_definitions, key=lambda item: item.wave_definition_id))

    def wave_definition_for_stage(self, stage_id: str) -> WaveDefinitionIR | None:
        definitions = self._wave_definitions_by_stage.get(stage_id, ())
        return definitions[0] if definitions else None

    def wave_entries_for_wave(self, wave_definition_id: str, wave_index: int) -> tuple[WaveMonsterEntryIR, ...]:
        return self._wave_entries_by_definition_wave.get((wave_definition_id, int(wave_index)), ())

    def has_action(self, action_id: str) -> bool:
        entity = self._entities.get(action_id)
        return bool(entity and entity.entity_type in {"avatar_skill", "monster_skill", "active_skill"})

    def action_definition(self, action_id: str, level: int) -> ActionDefinitionIR | None:
        return self._action_definitions.get((action_id, level))

    def action_definition_candidates(
        self,
        action_id: str,
        level: int,
    ) -> tuple[ActionDefinitionIR, ...]:
        return self._action_definition_candidates.get((action_id, level), ())

    def action_target_contract(
        self,
        action_id: str,
        level: int,
    ) -> ActionTargetContractQueryResult:
        if not isinstance(action_id, str) or not action_id:
            raise ValueError("action target query action_id is required")
        if not isinstance(level, int) or isinstance(level, bool) or level <= 0:
            raise ValueError("action target query level is invalid")
        candidates = self._action_target_contract_candidates.get(
            (action_id, level), ()
        )
        candidate_ids = tuple(item.contract_id for item in candidates)
        if not candidates:
            return ActionTargetContractQueryResult(
                resolution_status="blocked",
                action_id=action_id,
                level=level,
                blocked_reason="action_target_contract_missing",
            )
        if len(candidates) != 1:
            return ActionTargetContractQueryResult(
                resolution_status="blocked",
                action_id=action_id,
                level=level,
                candidate_ids=candidate_ids,
                blocked_reason="action_target_contract_ambiguous",
            )
        contract = candidates[0]
        if contract.coverage_status != "lowered":
            return ActionTargetContractQueryResult(
                resolution_status="blocked",
                action_id=action_id,
                level=level,
                candidate_ids=candidate_ids,
                blocked_reason=contract.blocked_reason,
            )
        return ActionTargetContractQueryResult(
            resolution_status="resolved",
            action_id=action_id,
            level=level,
            value=contract,
            candidate_ids=candidate_ids,
        )

    def require_action_definition(self, action_id: str, level: int) -> ActionDefinitionIR:
        definition = self.action_definition(action_id, level)
        if definition is None:
            levels = self.action_levels(action_id)
            if levels:
                raise KeyError(f"unknown action definition {action_id!r} level {level}; known levels: {list(levels)}")
            raise KeyError(f"unknown action definition {action_id!r} level {level}")
        return definition

    def action_levels(self, action_id: str) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    definition.level
                    for definition in self.ir.action_definitions
                    if definition.action_id == action_id
                }
            )
        )

    def action_definition_source_trace(self, action_id: str, level: int) -> dict[str, object] | None:
        definition = self.action_definition(action_id, level)
        if not definition:
            return None
        return {
            "definition_id": definition.definition_id,
            "action_id": definition.action_id,
            "level": definition.level,
            "coverage_status": definition.coverage_status,
            "source": definition.source.to_json(),
        }

    def action_event(self, action_id: str, level: int) -> ActionEventIR | None:
        return self._action_events.get((action_id, level))

    def require_action_event(self, action_id: str, level: int) -> ActionEventIR:
        event = self.action_event(action_id, level)
        if event is None:
            raise KeyError(f"unknown action event {action_id!r} level {level}")
        return event

    def hit_profiles_for_action(self, action_id: str, level: int) -> tuple[HitProfileIR, ...]:
        return self._hit_profiles_by_action.get((action_id, level), ())

    def hit_profile(self, hit_profile_id: str) -> HitProfileIR | None:
        return self._hit_profiles.get(hit_profile_id)

    def bounce_policy(self, bounce_policy_id: str) -> BouncePolicyIR | None:
        return self._bounce_policies.get(bounce_policy_id)

    def bounce_policies_for_action(self, action_id: str, level: int) -> tuple[BouncePolicyIR, ...]:
        return self._bounce_policies_by_action.get((action_id, level), ())

    def skill_formula_binding(self, binding_id: str) -> SkillFormulaBindingIR | None:
        return self._skill_formula_bindings.get(binding_id)

    def skill_formula_bindings_for_action_param(
        self,
        action_id: str,
        level: int,
        param_index: int,
        formula_role: str,
    ) -> tuple[SkillFormulaBindingIR, ...]:
        return self._skill_formula_bindings_by_action_param_role.get(
            (action_id, level, param_index, formula_role),
            (),
        )

    def damage_emission(self, damage_emission_id: str) -> DamageEmissionIR | None:
        return self._damage_emissions.get(damage_emission_id)

    def damage_emissions_for_action(self, action_id: str, level: int) -> tuple[DamageEmissionIR, ...]:
        return self._damage_emissions_by_action.get((action_id, level), ())

    def damage_emissions_for_task(self, task_id: str) -> tuple[DamageEmissionIR, ...]:
        return self._damage_emissions_by_task.get(task_id, ())

    def toughness_emission(self, toughness_emission_id: str) -> ToughnessEmissionIR | None:
        return self._toughness_emissions.get(toughness_emission_id)

    def toughness_emissions_for_action(self, action_id: str, level: int) -> tuple[ToughnessEmissionIR, ...]:
        return self._toughness_emissions_by_action.get((action_id, level), ())

    def toughness_emissions_for_task(self, task_id: str) -> tuple[ToughnessEmissionIR, ...]:
        return self._toughness_emissions_by_task.get(task_id, ())

    def break_template(self, template_id: str) -> BreakTemplateIR | None:
        return self._break_templates.get(template_id)

    def break_templates(self) -> tuple[BreakTemplateIR, ...]:
        return self.ir.break_templates

    def break_template_for_element(self, element_type: str | None) -> BreakTemplateIR | None:
        if not element_type:
            return None
        return self._break_templates_by_element.get(str(element_type))

    def break_damage_emission(self, emission_id: str) -> BreakDamageEmissionIR | None:
        return self._break_damage_emissions.get(emission_id)

    def break_base_damage(self, level: int) -> BreakBaseDamageIR | None:
        return self._break_base_damage_by_level.get(level)

    def break_base_damage_rows(self) -> tuple[BreakBaseDamageIR, ...]:
        return self.ir.break_base_damage

    def break_damage_emissions(self) -> tuple[BreakDamageEmissionIR, ...]:
        return self.ir.break_damage_emissions

    def break_damage_emissions_for_template(self, template_id: str) -> tuple[BreakDamageEmissionIR, ...]:
        return self._break_damage_emissions_by_template.get(template_id, ())

    def break_status_emission(self, emission_id: str) -> BreakStatusEmissionIR | None:
        return self._break_status_emissions.get(emission_id)

    def break_status_emissions(self) -> tuple[BreakStatusEmissionIR, ...]:
        return self.ir.break_status_emissions

    def break_status_emissions_for_template(self, template_id: str) -> tuple[BreakStatusEmissionIR, ...]:
        return self._break_status_emissions_by_template.get(template_id, ())

    def status_event_family(self, callback_event: str) -> StatusEventFamilyIR | None:
        return self._status_event_families.get(callback_event)

    def status_event_families(self) -> tuple[StatusEventFamilyIR, ...]:
        return self.ir.status_event_families

    def status_event_families_for_runtime_event(self, runtime_event: str) -> tuple[StatusEventFamilyIR, ...]:
        return self._status_event_families_by_runtime_event.get(runtime_event, ())

    def status_callback(self, callback_id: str) -> StatusCallbackIR | None:
        return self._status_callbacks.get(callback_id)

    def status_callbacks_for_modifier_event(self, modifier_name: str, event: str) -> tuple[StatusCallbackIR, ...]:
        return self._status_callbacks_by_modifier_event.get((modifier_name, event), ())

    def status_callbacks_for_event(self, event: str) -> tuple[StatusCallbackIR, ...]:
        return self._status_callbacks_by_event.get(event, ())

    def status_callbacks_for_event_scope(self, event: str, scope_kind: str) -> tuple[StatusCallbackIR, ...]:
        return self._status_callbacks_by_event_scope.get((event, scope_kind), ())

    def status_callbacks_for_modifier_event_scope(
        self,
        modifier_name: str,
        event: str,
        scope_kind: str,
    ) -> tuple[StatusCallbackIR, ...]:
        return self._status_callbacks_by_modifier_event_scope.get((modifier_name, event, scope_kind), ())

    def status_callback_task(self, task_id: str) -> StatusCallbackTaskIR | None:
        return self._status_callback_tasks.get(task_id)

    def status_callback_tasks_for_callback(self, callback_id: str) -> tuple[StatusCallbackTaskIR, ...]:
        return self._status_callback_tasks_by_callback.get(callback_id, ())

    def ability_property_watcher(
        self,
        watcher_id: str,
    ) -> AbilityPropertyWatcherIR | None:
        return self._ability_property_watchers.get(watcher_id)

    def ability_property_watchers_for_modifier(
        self,
        modifier_name: str,
    ) -> tuple[AbilityPropertyWatcherIR, ...]:
        return self._ability_property_watchers_by_modifier.get(modifier_name, ())

    def ability_property_range(
        self,
        range_id: str,
    ) -> AbilityPropertyRangeIR | None:
        return self._ability_property_ranges.get(range_id)

    def ability_property_ranges_for_watcher(
        self,
        watcher_id: str,
    ) -> tuple[AbilityPropertyRangeIR, ...]:
        return self._ability_property_ranges_by_watcher.get(watcher_id, ())

    def status_damage_emission(self, emission_id: str) -> StatusDamageEmissionIR | None:
        return self._status_damage_emissions.get(emission_id)

    def status_damage_emissions_for_callback(self, callback_id: str) -> tuple[StatusDamageEmissionIR, ...]:
        return self._status_damage_emissions_by_callback.get(callback_id, ())

    def damage_modifier(self, damage_modifier_id: str) -> DamageModifierIR | None:
        return self._damage_modifiers.get(damage_modifier_id)

    def damage_modifiers_for_callback(self, callback_id: str) -> tuple[DamageModifierIR, ...]:
        return self._damage_modifiers_by_callback.get(callback_id, ())

    def action_delay_emission(self, emission_id: str) -> ActionDelayEmissionIR | None:
        return self._action_delay_emissions.get(emission_id)

    def action_delay_emissions_for_callback(self, callback_id: str) -> tuple[ActionDelayEmissionIR, ...]:
        return self._action_delay_emissions_by_callback.get(callback_id, ())

    def queue_intent(self, queue_intent_id: str) -> QueueIntentIR | None:
        return self._queue_intents.get(queue_intent_id)

    def queue_intents_for_callback(self, callback_id: str) -> tuple[QueueIntentIR, ...]:
        return self._queue_intents_by_callback.get(callback_id, ())

    def queue_resolution(self, queue_resolution_id: str) -> QueueResolutionIR | None:
        return self._queue_resolutions.get(queue_resolution_id)

    def queue_resolution_for_intent(self, queue_intent_id: str) -> QueueResolutionIR | None:
        return self._queue_resolution_by_intent.get(queue_intent_id)

    def queue_priority(self, queue_priority_id: str) -> QueuePriorityIR | None:
        return self._queue_priorities.get(queue_priority_id)

    def queue_priority_by_key(self, priority_table: str, priority_key: str) -> QueuePriorityIR | None:
        return self._queue_priority_by_table_key.get((priority_table, priority_key))

    def queue_window(self, queue_window_id: str) -> QueueWindowIR | None:
        return self._queue_windows.get(queue_window_id)

    def queue_windows(self) -> tuple[QueueWindowIR, ...]:
        return tuple(sorted(self.ir.queue_windows, key=lambda item: item.queue_window_id))

    def queue_window_for_intent(self, queue_intent_id: str) -> QueueWindowIR | None:
        return self._queue_window_by_intent.get(queue_intent_id)

    def queue_windows_by_family(self, window_family: str) -> tuple[QueueWindowIR, ...]:
        return self._queue_windows_by_family.get(window_family, ())

    def queue_lifecycle_policy(self, policy_id: str) -> QueueLifecyclePolicyIR | None:
        return self._queue_lifecycle_policies.get(policy_id)

    def queue_lifecycle_policies(self) -> tuple[QueueLifecyclePolicyIR, ...]:
        return tuple(sorted(self.ir.queue_lifecycle_policies, key=lambda item: item.queue_lifecycle_policy_id))

    def queue_lifecycle_policy_for_window(self, queue_window_id: str) -> QueueLifecyclePolicyIR | None:
        return self._queue_lifecycle_policy_by_window.get(queue_window_id)

    def queue_lifecycle_policy_for_intent(self, queue_intent_id: str) -> QueueLifecyclePolicyIR | None:
        return self._queue_lifecycle_policy_by_intent.get(queue_intent_id)

    def queue_lifecycle_policies_by_family(self, window_family: str) -> tuple[QueueLifecyclePolicyIR, ...]:
        return self._queue_lifecycle_policies_by_family.get(window_family, ())

    def extra_action_policy(self, policy_id: str) -> ExtraActionPolicyIR | None:
        return self._extra_action_policies.get(policy_id)

    def extra_action_policies(self) -> tuple[ExtraActionPolicyIR, ...]:
        return tuple(sorted(self.ir.extra_action_policies, key=lambda item: item.extra_action_policy_id))

    def extra_action_policy_for_window(self, queue_window_id: str) -> ExtraActionPolicyIR | None:
        return self._extra_action_policy_by_window.get(queue_window_id)

    def extra_action_policy_for_intent(self, queue_intent_id: str) -> ExtraActionPolicyIR | None:
        return self._extra_action_policy_by_intent.get(queue_intent_id)

    def skill_continuation(self, continuation_id: str) -> SkillContinuationIR | None:
        return self._skill_continuations.get(continuation_id)

    def skill_continuations(self) -> tuple[SkillContinuationIR, ...]:
        return tuple(sorted(self.ir.skill_continuations, key=lambda item: item.continuation_id))

    def standalone_ability_graph(self, graph_id: str) -> StandaloneAbilityGraphIR | None:
        return self._standalone_ability_graphs.get(graph_id)

    def standalone_ability_graphs_by_name(self, ability_name: str) -> tuple[StandaloneAbilityGraphIR, ...]:
        return self._standalone_ability_graphs_by_name.get(ability_name, ())

    def combatant_action_set(self, entity_ref: str) -> CombatantActionSetIR | None:
        return self._combatant_action_sets.get(entity_ref)

    def combatant_action_sets(self) -> tuple[CombatantActionSetIR, ...]:
        return tuple(sorted(self.ir.combatant_action_sets, key=lambda item: item.combatant_action_set_id))

    def action_admission(self, admission_id: str) -> ActionAdmissionIR | None:
        return self._action_admissions.get(admission_id)

    def action_admissions_for(
        self,
        owner_entity_ref: str,
        action_id: str,
        action_level: int,
    ) -> tuple[ActionAdmissionIR, ...]:
        return self._action_admissions_by_owner_action.get(
            (owner_entity_ref, action_id, action_level),
            (),
        )

    def action_admission_resolution(
        self,
        owner_entity_ref: str,
        action_id: str,
        action_level: int,
        submission_mode: str,
    ) -> tuple[ActionAdmissionIR | None, str]:
        candidates = self.action_admissions_for(owner_entity_ref, action_id, action_level)
        if not candidates:
            return None, "action_admission_missing"
        admitted = tuple(
            candidate
            for candidate in candidates
            if submission_mode in candidate.submission_modes
        )
        if not admitted:
            roles = ",".join(sorted({candidate.action_role for candidate in candidates}))
            return None, f"action_submission_mode_not_admitted:{submission_mode}:{roles}"
        if len(admitted) != 1:
            return None, "action_admission_ambiguous"
        admission = admitted[0]
        if admission.coverage_status != "executable":
            return None, admission.blocked_reason or (
                f"action_admission_not_executable:{admission.coverage_status}"
            )
        return admission, ""

    def timeline_rule(self, timeline_rule_id: str) -> TimelineRuleIR | None:
        return self._timeline_rules.get(timeline_rule_id)

    def default_timeline_rule(self) -> TimelineRuleIR:
        rule, reason = self.select_timeline_rule()
        if rule is None:
            raise KeyError(reason)
        return rule

    def select_timeline_rule(self) -> tuple[TimelineRuleIR | None, str]:
        rules = tuple(sorted(self.ir.timeline_rules, key=lambda item: item.timeline_rule_id))
        if not rules:
            return None, "timeline_engine_rule_missing"
        if len(rules) != 1:
            return None, "timeline_engine_rule_ambiguous"
        reason = engine_rule_admission_reason(
            rules[0],
            expected_applicability=TIMELINE_RULE_APPLICABILITY,
        )
        return (None, reason) if reason else (rules[0], "")

    def resource_rule(self, resource_rule_id: str) -> ResourceRuleIR | None:
        return self._resource_rules.get(resource_rule_id)

    def battle_state_transition(
        self,
        transition_rule_id: str,
    ) -> BattleStateTransitionIR | None:
        return self._battle_state_transitions.get(transition_rule_id)

    def battle_state_transitions_for_runtime_event(
        self,
        runtime_event_type: str,
    ) -> tuple[BattleStateTransitionIR, ...]:
        return self._battle_state_transitions_by_runtime_event.get(
            runtime_event_type,
            (),
        )

    def battle_state_transition_resolution_for_trigger(
        self,
        trigger_kind: str,
        trigger_identity: str,
    ) -> tuple[BattleStateTransitionIR | None, str]:
        candidates = self._battle_state_transitions_by_trigger.get(
            (trigger_kind, trigger_identity),
            (),
        )
        if not candidates:
            return None, "battle_state_transition_missing"
        if len(candidates) != 1:
            return None, "battle_state_transition_ambiguous"
        transition = candidates[0]
        if transition.transition_rule_id in self._battle_state_transition_conflicts:
            return None, "battle_state_transition_identity_conflict"
        if transition.coverage_status != "executable":
            return None, transition.blocked_reason or (
                "battle_state_transition_not_executable:"
                f"{transition.coverage_status}"
            )
        if (
            not transition.transition_rule_id
            or not transition.trigger_kind
            or not transition.trigger_identity
            or not transition.state_path
            or not transition.runtime_event_type
            or not transition.callback_event
            or not transition.source.source_path
            or not transition.source.raw_type
            or not transition.source.raw_id
        ):
            return None, "battle_state_transition_contract_incomplete"
        return transition, ""

    def damage_formula_rule(self, damage_formula_rule_id: str) -> DamageFormulaRuleIR | None:
        return self._damage_formula_rules.get(damage_formula_rule_id)

    def damage_route_rule(self, damage_route_rule_id: str) -> DamageRouteRuleIR | None:
        return self._damage_route_rules.get(damage_route_rule_id)

    def shield_priority_rule(self, shield_priority_rule_id: str) -> ShieldPriorityRuleIR | None:
        return self._shield_priority_rules.get(shield_priority_rule_id)

    def engine_rule_registry(self) -> EngineRuleRegistry:
        return EngineRuleRegistry(
            registry_version=ENGINE_RULE_REGISTRY_VERSION,
            timeline_rules=self.ir.timeline_rules,
            resource_rules=self.ir.resource_rules,
            damage_formula_rules=self.ir.damage_formula_rules,
            damage_route_rules=self.ir.damage_route_rules,
            shield_priority_rules=self.ir.shield_priority_rules,
        )

    def resource_rules_by_kind(self, rule_kind: str) -> tuple[ResourceRuleIR, ...]:
        return tuple(
            sorted(
                (rule for rule in self.ir.resource_rules if rule.rule_kind == rule_kind),
                key=lambda item: item.resource_rule_id,
            )
        )

    def default_ultimate_energy_cost_rule(self) -> ResourceRuleIR:
        rule, reason = self.select_resource_rule("ultimate_energy_cost")
        if rule is None:
            raise KeyError(reason)
        return rule

    def default_kill_energy_gain_rule(self) -> ResourceRuleIR:
        rule, reason = self.select_resource_rule("kill_energy_gain")
        if rule is None:
            raise KeyError(reason)
        return rule

    def select_resource_rule(self, rule_kind: str) -> tuple[ResourceRuleIR | None, str]:
        rules = self.resource_rules_by_kind(rule_kind)
        if not rules:
            return None, f"resource_engine_rule_missing:{rule_kind}"
        if len(rules) != 1:
            return None, f"resource_engine_rule_ambiguous:{rule_kind}"
        applicability = {
            "ultimate_energy_cost": ULTIMATE_COST_RULE_APPLICABILITY,
            "kill_energy_gain": KILL_ENERGY_RULE_APPLICABILITY,
        }.get(rule_kind)
        if applicability is None:
            return None, f"resource_engine_rule_kind_not_admitted:{rule_kind}"
        reason = engine_rule_admission_reason(
            rules[0],
            expected_applicability=applicability,
            numeric_value_required=rule_kind == "kill_energy_gain",
        )
        return (None, reason) if reason else (rules[0], "")

    def super_break_emission(self, emission_id: str) -> SuperBreakEmissionIR | None:
        return self._super_break_emissions.get(emission_id)

    def super_break_emissions(self) -> tuple[SuperBreakEmissionIR, ...]:
        return self.ir.super_break_emissions

    def super_break_emissions_for_template(self, template_id: str) -> tuple[SuperBreakEmissionIR, ...]:
        return self._super_break_emissions_by_template.get(template_id, ())

    def action_ability_binding(self, action_id: str, level: int) -> ActionAbilityBindingIR | None:
        return self._action_ability_bindings.get((action_id, level))

    def action_ability_binding_by_id(self, binding_id: str) -> ActionAbilityBindingIR | None:
        return self._action_ability_bindings_by_id.get(binding_id)

    def ability_phases_for_action(self, action_id: str, level: int) -> tuple[AbilityPhaseIR, ...]:
        return self._ability_phases_by_action.get((action_id, level), ())

    def ability_phases_for_binding(self, binding_id: str) -> tuple[AbilityPhaseIR, ...]:
        return self._ability_phases_by_binding.get(binding_id, ())

    def ability_phase(self, phase_id: str) -> AbilityPhaseIR | None:
        return self._ability_phases.get(phase_id)

    def ability_task(self, task_id: str) -> AbilityTaskIR | None:
        return self._ability_tasks.get(task_id)

    def ability_tasks_for_phase(self, phase_id: str) -> tuple[AbilityTaskIR, ...]:
        return self._ability_tasks_by_phase.get(phase_id, ())

    def ability_tasks_for_action(self, action_id: str, level: int) -> tuple[AbilityTaskIR, ...]:
        return self._ability_tasks_by_action.get((action_id, level), ())

    def triggers_for_event(self, event: str) -> tuple[TriggerIR, ...]:
        return tuple(trigger for trigger in self.ir.triggers if trigger.event == event)

    def triggers_for_modifier(self, modifier_name: str) -> tuple[TriggerIR, ...]:
        return self._triggers_by_modifier.get(modifier_name, ())

    def triggers_for_modifier_event(self, modifier_name: str, event: str) -> tuple[TriggerIR, ...]:
        return self._triggers_by_modifier_event.get((modifier_name, event), ())

    def modifier_definitions(self, modifier_name: str) -> tuple[RuleEntity, ...]:
        return self._modifier_definitions_by_name.get(modifier_name, ())

    def modifier_definition(self, modifier_name: str) -> RuleEntity | None:
        definitions = self.modifier_definitions(modifier_name)
        if definitions:
            return definitions[0]
        return self.entity(f"modifier_definition:{modifier_name}")

    def require_modifier_definition(self, modifier_name: str) -> RuleEntity:
        return self.require_entity(f"modifier_definition:{modifier_name}", {"modifier_definition"})

    def status_entities_for_modifier(self, modifier_name: str) -> tuple[RuleEntity, ...]:
        return self._status_entities_by_modifier.get(modifier_name, ())

    def status_entity_for_modifier(self, modifier_name: str) -> RuleEntity | None:
        entities = self.status_entities_for_modifier(modifier_name)
        if entities:
            return entities[0]
        return None


def _ability_property_watcher_contract_error(
    watchers: dict[str, AbilityPropertyWatcherIR],
    ranges: dict[str, AbilityPropertyRangeIR],
    callbacks: dict[str, StatusCallbackIR],
) -> str:
    for watcher_id in sorted(watchers):
        watcher = watchers[watcher_id]
        if watcher.coverage_status != "executable":
            continue
        attached_ranges = tuple(
            ranges.get(range_id) for range_id in watcher.range_ids
        )
        indexed_range_ids = tuple(
            property_range.range_id
            for property_range in sorted(
                (
                    property_range
                    for property_range in ranges.values()
                    if property_range.watcher_id == watcher_id
                ),
                key=lambda item: (item.range_index, item.range_id),
            )
        )
        if (
            not watcher.range_ids
            or len(set(watcher.range_ids)) != len(watcher.range_ids)
            or any(property_range is None for property_range in attached_ranges)
            or indexed_range_ids != watcher.range_ids
            or tuple(
                property_range.range_index
                for property_range in attached_ranges
                if property_range is not None
            )
            != tuple(range(len(attached_ranges)))
        ):
            return (
                "ability_property_watcher_range_contract_invalid:"
                f"{watcher_id}"
            )
        for property_range in attached_ranges:
            assert property_range is not None
            if (
                property_range.coverage_status != "executable"
                or property_range.source.source_path
                != watcher.source.source_path
                or property_range.source.raw_id != watcher.source.raw_id
            ):
                return (
                    "ability_property_range_source_contract_invalid:"
                    f"{property_range.range_id}"
                )
            for branch, callback_id, expected_event in (
                (
                    "OnEnterRange",
                    property_range.enter_callback_id,
                    "OnAbilityPropertyRangeEnter",
                ),
                (
                    "OnExitRange",
                    property_range.exit_callback_id,
                    "OnAbilityPropertyRangeExit",
                ),
            ):
                if not callback_id:
                    continue
                callback = callbacks.get(callback_id)
                evidence = (
                    callback.source.evidence
                    if callback is not None
                    else {}
                )
                if (
                    callback is None
                    or callback.coverage_status != "executable"
                    or callback.admission_status != "executable"
                    or callback.scope_kind != "ability_property_range"
                    or callback.event != expected_event
                    or callback.modifier_name != watcher.modifier_name
                    or callback.source.source_path
                    != property_range.source.source_path
                    or callback.source.raw_id != property_range.source.raw_id
                    or evidence.get("ability_property_watcher_id")
                    != watcher_id
                    or evidence.get("ability_property_range_id")
                    != property_range.range_id
                    or evidence.get("ability_property_range_branch")
                    != branch
                ):
                    return (
                        "ability_property_range_callback_contract_invalid:"
                        f"{property_range.range_id}:{branch}"
                    )
    return ""


def _ability_property_watcher_effect_contract_error(
    effects: tuple[EffectIR, ...],
    entities: dict[str, RuleEntity],
    watchers: dict[str, AbilityPropertyWatcherIR],
) -> str:
    for effect in effects:
        watcher_ids = effect.ability_property_watcher_ids
        if not watcher_ids:
            continue
        standard = effect.payload.get("standard")
        modifier_name = (
            standard.get("modifier_name")
            if isinstance(standard, dict)
            else None
        )
        definition = entities.get(effect.modifier_definition_id)
        attached = tuple(watchers.get(watcher_id) for watcher_id in watcher_ids)
        if (
            effect.opcode != "AddModifier"
            or watcher_ids != tuple(sorted(set(watcher_ids)))
            or not isinstance(modifier_name, str)
            or not modifier_name
            or definition is None
            or definition.entity_type != "modifier_definition"
            or definition.source.raw_id != modifier_name
            or any(watcher is None for watcher in attached)
            or any(
                watcher is not None
                and (
                    watcher.modifier_name != modifier_name
                    or not _ability_property_watcher_matches_definition(
                        watcher,
                        definition,
                    )
                )
                for watcher in attached
            )
        ):
            return (
                "ability_property_watcher_effect_contract_invalid:"
                f"{effect.effect_id}"
            )
    return ""


def _ability_property_watcher_matches_definition(
    watcher: AbilityPropertyWatcherIR,
    definition: RuleEntity,
) -> bool:
    watcher_evidence = watcher.source.evidence
    definition_evidence = definition.source.evidence
    source_identity_fields = (
        "json_path",
        "ability_index",
        "equipment_ability_source_admitted",
        "equipment_ability_source",
    )
    return bool(
        watcher.source.source_path == definition.source.source_path
        and watcher.source.raw_type == definition.source.raw_type
        and watcher.source.raw_id == definition.source.raw_id
        and all(
            watcher_evidence.get(field) == definition_evidence.get(field)
            for field in source_identity_fields
        )
    )


def _equipment_callback_matches_graph(
    callback: StatusCallbackIR,
    graph: StandaloneAbilityGraphIR,
) -> bool:
    return bool(
        callback.source.source_path == graph.source.source_path
        and callback.source.evidence.get("equipment_ability_source")
        == graph.source.to_json()
    )


def _equipment_parameter_read_matches_graph(
    parameter_read: EquipmentAbilityParameterReadIR,
    graph: StandaloneAbilityGraphIR,
) -> bool:
    graph_json_path = graph.source.evidence.get("json_path")
    read_json_path = parameter_read.source.evidence.get("json_path")
    return bool(
        isinstance(graph_json_path, str)
        and isinstance(read_json_path, str)
        and parameter_read.source.raw_type == "EquipmentAbilityParameterRead"
        and parameter_read.source.raw_id
        == (
            f"{graph.ability_name}:{parameter_read.dynamic_hash}:"
            f"{parameter_read.parameter_index}"
        )
        and parameter_read.source.source_path == graph.source.source_path
        and parameter_read.parameter_read_id
        == (
            f"equipment_parameter_read:{graph.source.source_path}:"
            f"json_path:{graph_json_path}:value_type:{parameter_read.value_type}:"
            f"dynamic_hash:{parameter_read.dynamic_hash}:"
            f"parameter_index:{parameter_read.parameter_index}"
        )
        and read_json_path
        == (
            f"{graph_json_path}.DynamicValues.{parameter_read.value_type}."
            f"{parameter_read.dynamic_hash}.ReadInfo"
        )
        and parameter_read.source.evidence.get("source_fingerprint")
        == graph.source.evidence.get("source_fingerprint")
    )


def _equipment_definition_sort_key(
    definition: EquipmentDefinition,
) -> tuple[str, str, str, str, str]:
    return (
        definition.definition_key.definition_kind,
        definition.definition_key.definition_identity,
        definition.source.source_path,
        definition.source.raw_id,
        str(definition.source.evidence.get("json_path") or ""),
    )


def _action_definition_candidate_sort_key(
    definition: ActionDefinitionIR,
) -> tuple[str, str, str]:
    return (
        definition.definition_id,
        definition.source.source_path,
        definition.source.raw_id,
    )


def _json_object_copy(value: dict[str, JSONValue]) -> dict[str, JSONValue]:
    copied: dict[str, JSONValue] = {}
    for key, item in value.items():
        copied[str(key)] = _json_copy(item)
    return copied


_IndexItem = TypeVar("_IndexItem")


def _unique_index(
    items: Iterable[_IndexItem],
    key_getter: Callable[[_IndexItem], str],
) -> tuple[dict[str, _IndexItem], frozenset[str]]:
    grouped: dict[str, list[_IndexItem]] = {}
    for item in items:
        grouped.setdefault(key_getter(item), []).append(item)
    conflicts = frozenset(key for key, candidates in grouped.items() if len(candidates) != 1)
    return (
        {
            key: candidates[0]
            for key, candidates in grouped.items()
            if key not in conflicts
        },
        conflicts,
    )


def _json_copy(value: JSONValue) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_copy(item) for item in value]
    return str(value)
