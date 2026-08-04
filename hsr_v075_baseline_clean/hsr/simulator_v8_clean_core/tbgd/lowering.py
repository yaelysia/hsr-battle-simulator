from __future__ import annotations

import json
import base64
import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
from operator import attrgetter
from pathlib import Path
from typing import Any, NamedTuple, cast

from ..dynamic_key_hash import tbgd_dynamic_key_hash
from .coverage import ability_task_execution_mode, classify_opcode
from .character_ability_scope import (
    CharacterAbilityRawSnapshot,
    CharacterAbilityScopeProjectionCatalog,
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
)
from .character_ability_source_graph import (
    _skill_entries,
    build_character_ability_source_graph,
)
from .character_source_resolution import (
    build_character_ability_source_resolution,
    character_dynamic_value_decode_families,
    lower_character_decoded_dynamic_value_operation,
)
from .character_cards import (
    CHARACTER_ACTION_DEFINITION_TABLES,
    build_character_card_ir,
)
from .equipment_ability_families import (
    classify_equipment_callback,
    classify_equipment_condition,
    classify_equipment_family,
    classify_equipment_task,
)
from .light_cone_cards import (
    build_light_cone_catalog,
    require_complete_light_cone_catalog,
)
from .relic_cards import build_relic_catalog, require_complete_relic_catalog
from .monster_cards import build_monster_card_ir
from .paths import relative_source_path
from .. import BASELINE_VERSION
from ..equipment.models import (
    EquipmentAbilityParameterReadIR,
    EquipmentDefinitionKey,
    EquipmentMechanismRefIR,
    LightConeDefinitionIR,
    RelicSetThresholdIR,
    make_equipment_source,
)
from ..immutable_json import freeze_json, thaw_json
from ..resource_event_contract import (
    resource_callback_runtime_sources,
    resource_scope_for_callback,
)
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ability_properties import ability_property_is_runtime_readable
from ..rules.engine_rule_registry import build_engine_rule_registry
from ..rules.expression_ir import (
    CONDITION_EXPRESSION_NODE_SCHEMA,
    DynamicValueOperationIR,
    NUMERIC_EXPRESSION_SCHEMA,
    TARGET_EXPRESSION_NODE_SCHEMA,
    is_typed_numeric_expression,
    numeric_dynamic_hashes,
    numeric_fixed,
    numeric_missing,
)
from .expression_lowering import (
    is_dynamic_value_opcode,
    lower_dynamic_value_operation_spec,
    lower_numeric_expression,
)
from ..rules.ir import (
    AbilityPropertyRangeIR,
    AbilityPropertyWatcherIR,
    AbilityPhaseIR,
    AbilityTaskIR,
    ActionAbilityBindingIR,
    ActionAdmissionIR,
    ActionDefinitionIR,
    ActionDelayEmissionIR,
    ActionEventIR,
    ActionPhaseStepIR,
    AssistantAbilityResolutionIR,
    AvatarProfileIR,
    BreakBaseDamageIR,
    BreakDamageEmissionIR,
    BreakStatusEmissionIR,
    BreakTemplateIR,
    BattleStateTransitionIR,
    BouncePolicyIR,
    CanonicalIR,
    CharacterDataCardIR,
    CharacterAbilityDefinitionIR,
    CharacterAbilitySourceGraphCatalogIR,
    CharacterAbilitySourceResolutionCatalogIR,
    CharacterEidolonSlotIR,
    CharacterEquipmentEligibilityIR,
    CharacterMechanismSlotIR,
    CharacterTraceNodeIR,
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
    IRSource,
    JSONValue,
    MonsterDataCardIR,
    PassiveMechanismSlotIR,
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
    StatusEventFamilyIR,
    StatusCallbackTaskIR,
    StatusDamageEmissionIR,
    ServantDefinitionIR,
    ServantOwnerRelationIR,
    SummonMonsterEntryIR,
    SummonMonsterIntentIR,
    SummonUnitDefinitionIR,
    SuperBreakEmissionIR,
    TargetExpressionIR,
    TargetExpressionNodeIR,
    TimelineRuleIR,
    ToughnessEmissionIR,
    TriggerIR,
    UnitBirthTemplateIR,
    WaveDefinitionIR,
    WaveMonsterEntryIR,
)
from ..rules.rulebook import CharacterAbilitySourceGraphQuery


def _equipment_catalog_fingerprint_metadata(
    *,
    light_cone_source_content_fingerprint: Mapping[str, JSONValue],
    relic_source_content_fingerprint: Mapping[str, JSONValue],
    light_cone_catalog_definition_fingerprint: Mapping[str, JSONValue],
    relic_catalog_definition_fingerprint: Mapping[str, JSONValue],
) -> dict[str, JSONValue]:
    """Keep source and definition fingerprints explicit per equipment family."""

    return {
        "light_cone_source_content_fingerprint": thaw_json(
            light_cone_source_content_fingerprint
        ),
        "relic_source_content_fingerprint": thaw_json(
            relic_source_content_fingerprint
        ),
        "light_cone_catalog_definition_fingerprint": thaw_json(
            light_cone_catalog_definition_fingerprint
        ),
        "relic_catalog_definition_fingerprint": thaw_json(
            relic_catalog_definition_fingerprint
        ),
    }


ENTITY_TABLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "ExcelOutput/AvatarConfig.json": ("avatar", "AvatarID", ("DamageType", "SPNeed", "SkillList", "AvatarBaseType", "Rarity", "JsonPath")),
    "ExcelOutput/AvatarConfigLD.json": ("avatar", "AvatarID", ("DamageType", "SPNeed", "SkillList", "AvatarBaseType", "Rarity", "JsonPath")),
    "ExcelOutput/AvatarConfigEnhanced.json": ("avatar", "AvatarID", ("EnhancedID", "SPNeed", "SkillList", "RankIDList", "JsonPath", "AIPath")),
    "ExcelOutput/AvatarSkillConfig.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel", "SkillIcon", "UltraSkillIcon"),
    ),
    "ExcelOutput/AvatarSkillConfigLD.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel", "SkillIcon", "UltraSkillIcon"),
    ),
    "ExcelOutput/AvatarPromotionConfig.json": (
        "avatar_promotion",
        "AvatarID",
        ("Promotion", "MaxLevel", "AttackBase", "AttackAdd", "DefenceBase", "DefenceAdd", "HPBase", "HPAdd", "SpeedBase", "CriticalChance", "CriticalDamage", "BaseAggro"),
    ),
    "ExcelOutput/AvatarPromotionConfigLD.json": (
        "avatar_promotion",
        "AvatarID",
        ("Promotion", "MaxLevel", "AttackBase", "AttackAdd", "DefenceBase", "DefenceAdd", "HPBase", "HPAdd", "SpeedBase", "CriticalChance", "CriticalDamage", "BaseAggro"),
    ),
    "ExcelOutput/CommonAvatarSkillConfig.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel"),
    ),
    "ExcelOutput/CommonActiveSkillConfig.json": (
        "active_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel"),
    ),
    "ExcelOutput/StatusConfig.json": (
        "status",
        "StatusID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList"),
    ),
    "ExcelOutput/AvatarStatusConfig.json": (
        "status",
        "StatusID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList"),
    ),
    "ExcelOutput/AvatarStatusConfigLD.json": (
        "status",
        "StatusID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList"),
    ),
    "ExcelOutput/MonsterStatusConfig.json": (
        "status",
        "StatusID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList"),
    ),
    "ExcelOutput/ILBattleStatusConfig.json": (
        "status",
        "ID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList", "DisplayPriority"),
    ),
    "ExcelOutput/ILBattleMonsterSkill.json": (
        "ilbattle_monster_skill",
        "ID",
        ("SkillTriggerKey", "AttackType", "InitialCD", "CoolDown", "ParamList"),
    ),
    "ExcelOutput/MonsterSkillConfig.json": (
        "monster_skill",
        "SkillID",
        ("SkillTriggerKey", "DamageType", "AttackType", "SPHitBase", "ParamList", "PhaseList"),
    ),
    "ExcelOutput/MonsterSkillUniqueConfig.json": (
        "monster_skill",
        "SkillID",
        ("SkillTriggerKey", "DamageType", "AttackType", "SPHitBase", "ParamList", "PhaseList"),
    ),
    "ExcelOutput/MonsterConfig.json": (
        "monster",
        "MonsterID",
        ("MonsterTemplateID", "HardLevelGroup", "AttackModifyRatio", "DefenceModifyRatio", "HPModifyRatio", "SpeedModifyRatio", "StanceModifyRatio", "StanceWeakList", "DamageTypeResistance", "SkillList"),
    ),
    "ExcelOutput/MonsterTemplateConfig.json": (
        "monster_template",
        "MonsterTemplateID",
        ("Rank", "AttackBase", "DefenceBase", "HPBase", "SpeedBase", "StanceBase", "CriticalDamageBase", "StatusResistanceBase", "StanceType", "AIPath", "AISkillSequence"),
    ),
    "ExcelOutput/SummonUnitData.json": (
        "summon_unit",
        "ID",
        ("JsonPath", "MaxSummonCount", "UniqueGroup", "DestroyOnEnterBattle"),
    ),
    "ExcelOutput/AvatarServantConfig.json": (
        "servant",
        "ServantID",
        (
            "Config",
            "AIPath",
            "SkillIDList",
            "HPBase",
            "HPInherit",
            "HPSkill",
            "SpeedBase",
            "SpeedInherit",
            "SpeedSkill",
            "Aggro",
        ),
    ),
    "ExcelOutput/AvatarServantSkillConfig.json": (
        "servant_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel", "ParamList"),
    ),
    "ExcelOutput/RelicSetSkillConfig.json": (
        "relic_set_skill",
        "SetID",
        ("SkillList", "SetSkillList", "AbilityName", "ParamList"),
    ),
    "ExcelOutput/AvatarBreakDamage.json": (
        "break_damage",
        "Level",
        ("BreakBaseDamage", "HardnessBaseDamage"),
    ),
}


ACTION_DEFINITION_TABLES: tuple[tuple[str, str, str], ...] = (
    ("ExcelOutput/AvatarSkillConfig.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/AvatarSkillConfigLD.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/CommonAvatarSkillConfig.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/CommonActiveSkillConfig.json", "active_skill", "SkillID"),
    ("ExcelOutput/MonsterSkillConfig.json", "monster_skill", "SkillID"),
    ("ExcelOutput/MonsterSkillUniqueConfig.json", "monster_skill", "SkillID"),
    ("ExcelOutput/ILBattleMonsterSkill.json", "ilbattle_monster_skill", "ID"),
    ("ExcelOutput/AvatarServantSkillConfig.json", "servant_skill", "SkillID"),
)

ELATION_MECHANIC_FILES: tuple[str, ...] = (
    "Config/GlobalConfig/GameCoreConstValue.json",
    "Config/GlobalConfig/PriorityConfig.json",
)

ELATION_STATE_TRANSITION_FILE = (
    "Config/ConfigAbility/BattleEvent/StageAbility_Elation.json"
)


DAMAGE_BEHAVIOR_TEMPLATE_FILE = "Config/GlobalConfig/DamageBehaviorTemplateListConfig.json"

ABILITY_TASK_CALLBACKS = ("OnStart", "OnAttack", "OnHit", "OnEnd")


@dataclass(frozen=True)
class LoweringLimits:
    max_records_per_table: int | None = None
    max_ability_files: int | None = None
    max_callbacks_per_file: int | None = None


class OwnedCombatantProjectionIssue(NamedTuple):
    code: str
    subject: str


class IRIdentityConflictError(ValueError):
    def __init__(
        self,
        *,
        item_kind: str,
        identity_field: str,
        identity: str,
    ) -> None:
        self.item_kind = item_kind
        self.identity_field = identity_field
        self.identity = identity
        self.reason_code = "ir_identity_conflict"
        super().__init__(
            f"{self.reason_code}:{item_kind}:{identity_field}:{identity}"
        )


class OwnedCombatantAdmissionProjection(NamedTuple):
    """Source-backed projection used by owned-combatant admission."""

    servant_definitions: tuple[ServantDefinitionIR, ...]
    action_definitions: tuple[ActionDefinitionIR, ...]
    action_ability_bindings: tuple[ActionAbilityBindingIR, ...]
    action_admissions: tuple[ActionAdmissionIR, ...]
    unit_birth_templates: tuple[UnitBirthTemplateIR, ...]
    issues: tuple[OwnedCombatantProjectionIssue, ...] = ()
    entities: tuple[RuleEntity, ...] = ()
    combatant_action_sets: tuple[CombatantActionSetIR, ...] = ()
    ability_phases: tuple[AbilityPhaseIR, ...] = ()
    ability_tasks: tuple[AbilityTaskIR, ...] = ()
    action_events: tuple[ActionEventIR, ...] = ()
    hit_profiles: tuple[HitProfileIR, ...] = ()
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...] = ()
    damage_emissions: tuple[DamageEmissionIR, ...] = ()
    toughness_emissions: tuple[ToughnessEmissionIR, ...] = ()
    effects: tuple[EffectIR, ...] = ()
    conditions: tuple[ConditionIR, ...] = ()
    formulas: tuple[FormulaIR, ...] = ()
    target_expressions: tuple[TargetExpressionIR, ...] = ()
    status_callbacks: tuple[StatusCallbackIR, ...] = ()
    status_callback_tasks: tuple[StatusCallbackTaskIR, ...] = ()
    status_damage_emissions: tuple[StatusDamageEmissionIR, ...] = ()
    damage_modifiers: tuple[DamageModifierIR, ...] = ()
    action_delay_emissions: tuple[ActionDelayEmissionIR, ...] = ()
    queue_intents: tuple[QueueIntentIR, ...] = ()
    skill_continuations: tuple[SkillContinuationIR, ...] = ()
    triggers: tuple[TriggerIR, ...] = ()
    avatar_profiles: tuple[AvatarProfileIR, ...] = ()
    character_data_cards: tuple[CharacterDataCardIR, ...] = ()
    character_equipment_eligibilities: tuple[
        CharacterEquipmentEligibilityIR,
        ...,
    ] = ()
    character_mechanism_slots: tuple[CharacterMechanismSlotIR, ...] = ()
    character_trace_nodes: tuple[CharacterTraceNodeIR, ...] = ()
    character_eidolon_slots: tuple[CharacterEidolonSlotIR, ...] = ()
    bounce_policies: tuple[BouncePolicyIR, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues


class TBGDLowering:
    """Converts TBGD raw files into v8 Canonical IR."""

    def __init__(self, tbgd_root: Path, limits: LoweringLimits | None = None):
        self.tbgd_root = tbgd_root.resolve()
        self.limits = limits or LoweringLimits()
        self._damage_tag_registry = _damage_tag_registry(self.tbgd_root)

    def build_character_ability_source_graph_catalog(
        self,
        *,
        snapshot: CharacterAbilityRawSnapshot | None = None,
        scope_catalog: CharacterAbilityScopeProjectionCatalog | None = None,
    ) -> CharacterAbilitySourceGraphCatalogIR:
        cached = getattr(self, "_character_ability_source_graph_catalog", None)
        if cached is not None:
            if type(cached) is not CharacterAbilitySourceGraphCatalogIR:
                raise TypeError("invalid cached character ability source graph catalog")
            cached_snapshot = getattr(self, "_character_ability_raw_snapshot", None)
            cached_scope = getattr(self, "_character_ability_scope_catalog", None)
            if (
                snapshot is not None
                and (
                    type(snapshot) is not CharacterAbilityRawSnapshot
                    or snapshot.snapshot_id != cached.snapshot_id
                )
            ) or (
                scope_catalog is not None
                and (
                    type(scope_catalog) is not CharacterAbilityScopeProjectionCatalog
                    or scope_catalog.catalog_id != cached.scope_catalog_id
                )
            ):
                raise ValueError("cached character ability source closure mismatch")
            if (
                type(cached_snapshot) is not CharacterAbilityRawSnapshot
                or type(cached_scope) is not CharacterAbilityScopeProjectionCatalog
            ):
                raise TypeError("cached character ability source context is invalid")
            return cached
        if snapshot is None:
            snapshot = build_character_ability_raw_snapshot(self.tbgd_root)
        elif type(snapshot) is not CharacterAbilityRawSnapshot:
            raise TypeError("lowering requires the exact S0 character snapshot type")
        if scope_catalog is None:
            scope_catalog = build_character_ability_scope_projection(
                self.tbgd_root,
                snapshot=snapshot,
            )
        elif type(scope_catalog) is not CharacterAbilityScopeProjectionCatalog:
            raise TypeError("lowering requires the exact S0 scope catalog type")
        catalog = build_character_ability_source_graph(
            self.tbgd_root,
            snapshot=snapshot,
            scope_catalog=scope_catalog,
        )
        self._character_ability_raw_snapshot = snapshot
        self._character_ability_scope_catalog = scope_catalog
        self._character_ability_source_graph_catalog = catalog
        return catalog

    def build_character_ability_source_resolution_catalog(
        self,
        *,
        snapshot: CharacterAbilityRawSnapshot | None = None,
        scope_catalog: CharacterAbilityScopeProjectionCatalog | None = None,
        source_graph_catalog: CharacterAbilitySourceGraphCatalogIR | None = None,
    ) -> CharacterAbilitySourceResolutionCatalogIR:
        cached = getattr(self, "_character_ability_source_resolution_catalog", None)
        if cached is not None:
            if type(cached) is not CharacterAbilitySourceResolutionCatalogIR:
                raise TypeError("invalid cached character ability source resolution catalog")
            if (
                snapshot is not None
                and (
                    type(snapshot) is not CharacterAbilityRawSnapshot
                    or snapshot.snapshot_id
                    != getattr(
                        self, "_character_ability_raw_snapshot", None
                    ).snapshot_id
                )
            ) or (
                scope_catalog is not None
                and (
                    type(scope_catalog) is not CharacterAbilityScopeProjectionCatalog
                    or scope_catalog.catalog_id != cached.scope_catalog_id
                )
            ) or (
                source_graph_catalog is not None
                and (
                    type(source_graph_catalog)
                    is not CharacterAbilitySourceGraphCatalogIR
                    or source_graph_catalog.catalog_id
                    != cached.source_graph_catalog_id
                )
            ):
                raise ValueError("cached character source resolution closure mismatch")
            return cached
        if source_graph_catalog is None:
            source_graph_catalog = self.build_character_ability_source_graph_catalog(
                snapshot=snapshot,
                scope_catalog=scope_catalog,
            )
            snapshot = getattr(self, "_character_ability_raw_snapshot")
            scope_catalog = getattr(self, "_character_ability_scope_catalog")
        else:
            if type(source_graph_catalog) is not CharacterAbilitySourceGraphCatalogIR:
                raise TypeError("source resolution requires the exact S1 catalog type")
            if snapshot is None or scope_catalog is None:
                raise ValueError(
                    "explicit S1 source graph requires its S0 snapshot and scope catalog"
                )
        if type(snapshot) is not CharacterAbilityRawSnapshot or type(
            scope_catalog
        ) is not CharacterAbilityScopeProjectionCatalog:
            raise TypeError("source resolution requires exact S0 prerequisite types")
        catalog = build_character_ability_source_resolution(
            self.tbgd_root,
            snapshot=snapshot,
            scope_catalog=scope_catalog,
            source_graph_catalog=source_graph_catalog,
        )
        self._character_ability_raw_snapshot = snapshot
        self._character_ability_scope_catalog = scope_catalog
        self._character_ability_source_graph_catalog = source_graph_catalog
        self._character_ability_source_resolution_catalog = catalog
        return catalog

    def build_character_action_ability_slice(
        self,
        definition: ActionDefinitionIR,
        *,
        snapshot: CharacterAbilityRawSnapshot,
        scope_catalog: CharacterAbilityScopeProjectionCatalog,
        source_graph_catalog: CharacterAbilitySourceGraphCatalogIR,
    ) -> CanonicalIR:
        """Lower one source-backed character action through the production path."""

        if type(definition) is not ActionDefinitionIR:
            raise TypeError("character action slice requires an exact action definition")
        graph_catalog = self.build_character_ability_source_graph_catalog(
            snapshot=snapshot,
            scope_catalog=scope_catalog,
        )
        if graph_catalog.catalog_id != source_graph_catalog.catalog_id:
            raise ValueError("character action slice source graph mismatch")
        action_sources = tuple(
            item
            for item in graph_catalog.action_sources
            if item.action_id == definition.action_id
        )
        if len(action_sources) != 1:
            raise ValueError("character action slice owner is missing or ambiguous")
        owner_avatar_id = action_sources[0].owner_avatar_id
        binding, phases, lowered = self._avatar_action_binding(definition)
        action_events, hit_profiles = _lower_action_execution_ir(
            [definition], [binding], phases, [], []
        )
        damage_emissions = _lower_damage_emissions(
            lowered.ability_tasks,
            lowered.effects,
            hit_profiles,
            [],
            self._damage_tag_registry,
        )
        toughness_emissions = _lower_toughness_emissions(
            lowered.ability_tasks,
            lowered.effects,
            hit_profiles,
        )
        ability_tasks = _admit_damage_ability_tasks(
            lowered.ability_tasks,
            damage_emissions,
            toughness_emissions,
            hit_profiles,
        )
        avatar_rows = [
            item
            for item in self._avatar_config_rows_prefer_enhanced()
            if str(item[2].get("AvatarID")) == owner_avatar_id
        ]
        action_sets = self._lower_combatant_action_sets(
            [definition],
            entity_types=frozenset({"avatar"}),
            avatar_config_rows=avatar_rows,
        )
        action_sets, action_admissions = _lower_action_admissions(
            action_sets,
            [definition],
        )
        owner_entities = self._lower_entity_table(
            "ExcelOutput/AvatarConfig.json",
            ENTITY_TABLES["ExcelOutput/AvatarConfig.json"],
            entity_ids=frozenset({f"avatar:{owner_avatar_id}"}),
        )
        return CanonicalIR(
            version=BASELINE_VERSION,
            entities=tuple(
                _dedupe_entities([*owner_entities, *lowered.entities]).values()
            ),
            action_definitions=(definition,),
            action_ability_bindings=(binding,),
            ability_phases=tuple(phases),
            ability_tasks=tuple(ability_tasks),
            action_events=tuple(action_events),
            hit_profiles=tuple(hit_profiles),
            damage_emissions=tuple(damage_emissions),
            toughness_emissions=tuple(toughness_emissions),
            status_callbacks=tuple(lowered.status_callbacks),
            status_callback_tasks=tuple(lowered.status_callback_tasks),
            ability_property_watchers=tuple(lowered.ability_property_watchers),
            ability_property_ranges=tuple(lowered.ability_property_ranges),
            status_damage_emissions=tuple(lowered.status_damage_emissions),
            damage_modifiers=tuple(lowered.damage_modifiers),
            action_delay_emissions=tuple(lowered.action_delay_emissions),
            queue_intents=tuple(lowered.queue_intents),
            skill_continuations=tuple(lowered.skill_continuations),
            target_expressions=tuple(lowered.target_expressions),
            combatant_action_sets=tuple(action_sets),
            action_admissions=tuple(action_admissions),
            triggers=tuple(lowered.triggers),
            effects=tuple(lowered.effects),
            conditions=tuple(lowered.conditions),
            formulas=tuple(lowered.formulas),
            metadata={
                "projection": "character_action_ability_slice",
                "action_id": definition.action_id,
                "action_level": definition.level,
                "owner_entity_ref": f"avatar:{owner_avatar_id}",
                "source_graph_catalog_id": source_graph_catalog.catalog_id,
            },
        )

    def _decoded_dynamic_task_projection(
        self,
        *,
        ability_path: str,
        ability_index: int | None,
        task_path: str,
        source_opcode: str,
    ) -> tuple[str, dict[str, JSONValue], IRSource, str] | None:
        if ability_index is None:
            return None
        catalog = getattr(
            self,
            "_character_ability_source_resolution_catalog",
            None,
        )
        json_path = f"$.AbilityList[{ability_index}].{task_path}.$type"
        decoded_id = ""
        if type(catalog) is CharacterAbilitySourceResolutionCatalogIR:
            matches = tuple(
                item
                for item in catalog.decoded_items
                if item.source_family == source_opcode
                and item.source.source_path == ability_path
                and item.source.evidence.get("json_path") == json_path
                and item.typed_operation is not None
            )
            if len(matches) > 1:
                raise ValueError("decoded dynamic task source is ambiguous")
            if matches:
                decoded = matches[0]
                operation = DynamicValueOperationIR.from_spec(
                    thaw_json(decoded.typed_operation),
                    decoded.source,
                )
                decoded_id = decoded.decoded_id
            else:
                operation = None
        else:
            operation = None
        if operation is None:
            if source_opcode not in character_dynamic_value_decode_families():
                return None
            scope_catalog = getattr(self, "_character_ability_scope_catalog", None)
            if type(scope_catalog) is not CharacterAbilityScopeProjectionCatalog:
                raise TypeError("decoded dynamic task requires a typed scope catalog")
            records = tuple(
                record
                for record in scope_catalog.scope_records
                if record.family == source_opcode
                and record.source.source_path == ability_path
                and record.source.evidence.get("json_path") == json_path
            )
            if len(records) != 1:
                raise ValueError("decoded dynamic task scope record is missing or ambiguous")
            operation = lower_character_decoded_dynamic_value_operation(records[0])
            decoded_id = records[0].record_id
        runtime_opcode = {
            "define": "DefineDynamicValue",
            "set": "SetDynamicValue",
            "add": "SetDynamicValueByAddValue",
            "copy": "SetDynamicValueByCopying",
        }.get(operation.operation_kind)
        if runtime_opcode is None:
            raise ValueError("decoded dynamic operation kind is unsupported")
        return (
            runtime_opcode,
            operation.to_spec_json(),
            operation.source,
            decoded_id,
        )

    def build_owned_combatant_admission_projection(
        self,
        *,
        offensive_action_only: bool = False,
        max_servant_count: int | None = None,
    ) -> OwnedCombatantAdmissionProjection:
        """Build only the source-backed sets required for servant admission.

        The owner-card read below supplies formula bindings for servant actions. It
        is not a complete character-card directory and does not consume build
        selectors; complete character builds require the paired S0/S1 catalogs.
        """

        servant_rows = self._servant_config_rows()
        if offensive_action_only:
            servant_rows = self._offensive_servant_config_rows(servant_rows)
        if max_servant_count is not None:
            if (
                not isinstance(max_servant_count, int)
                or isinstance(max_servant_count, bool)
                or max_servant_count <= 0
            ):
                raise ValueError("max_servant_count must be a positive integer")
            servant_rows = servant_rows[:max_servant_count]
        servant_action_ids = frozenset(
            f"servant_skill:{skill_id}"
            for _, _, row in servant_rows
            for skill_id in (
                row.get("SkillIDList")
                if isinstance(row.get("SkillIDList"), list)
                else ()
            )
            if str(skill_id)
        )
        action_definitions = self._lower_action_definitions(
            action_ids=servant_action_ids,
            entity_types=frozenset({"servant_skill"}),
        )
        (
            action_ability_bindings,
            ability_phases,
            ability_tasks,
            ability_task_effects,
            ability_task_conditions,
            ability_task_formulas,
            ability_task_target_expressions,
        ) = self._lower_action_ability_bindings(
            action_definitions,
        )
        combatant_action_sets = self._lower_combatant_action_sets(
            action_definitions,
            entity_types=frozenset({"servant"}),
            servant_config_rows=servant_rows,
        )
        combatant_action_sets, action_admissions = _lower_action_admissions(
            combatant_action_sets,
            action_definitions,
        )
        projected_owner_avatar_ids = (
            self._servant_owner_avatar_ids_from_sources(servant_rows)
        )
        character_cards = build_character_card_ir(
            self.tbgd_root,
            max_records_per_table=self.limits.max_records_per_table,
            skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
            avatar_ids=projected_owner_avatar_ids,
        )
        ability_task_effects = _attach_status_formula_bindings_to_add_modifier_effects(
            ability_task_effects,
            ability_tasks,
            list(character_cards.skill_formula_bindings),
        )
        action_modifier_definitions = self._lower_owned_action_modifier_definitions(
            action_ability_bindings,
            ability_task_effects,
        )
        ability_task_effects = _link_status_effect_runtime_fields(
            ability_task_effects,
            action_modifier_definitions,
            [],
        )
        skill_formula_bindings = list(character_cards.skill_formula_bindings)
        skill_formula_bindings.extend(
            self._lower_servant_damage_formula_bindings(
                action_definitions,
                ability_tasks,
                ability_task_effects,
            )
        )
        action_events, hit_profiles = _lower_action_execution_ir(
            action_definitions,
            action_ability_bindings,
            ability_phases,
            skill_formula_bindings,
            list(character_cards.bounce_policies),
        )
        damage_emissions = _lower_damage_emissions(
            ability_tasks,
            ability_task_effects,
            hit_profiles,
            skill_formula_bindings,
            self._damage_tag_registry,
        )
        toughness_emissions = _lower_toughness_emissions(
            ability_tasks,
            ability_task_effects,
            hit_profiles,
        )
        ability_tasks = _admit_damage_ability_tasks(
            ability_tasks,
            damage_emissions,
            toughness_emissions,
            hit_profiles,
        )
        selected_ability_files = _limit_sequence(
            self._ability_files(),
            self.limits.max_ability_files,
        )
        selected_servant_ids = frozenset(
            str(row.get("ServantID"))
            for _, _, row in servant_rows
            if row.get("ServantID") is not None
        )
        spawn_sources = _discover_servant_spawn_sources(
            self.tbgd_root,
            selected_ability_files,
            servant_ids=selected_servant_ids,
        )
        replacement_policies = _discover_servant_replacement_policies(
            self.tbgd_root,
            selected_ability_files,
            servant_ids=selected_servant_ids,
        )
        servant_definitions = self._lower_servant_definitions(
            combatant_action_sets,
            action_ability_bindings,
            character_data_cards=list(character_cards.character_data_cards),
            character_trace_nodes=list(character_cards.character_trace_nodes),
            character_eidolon_slots=list(character_cards.character_eidolon_slots),
            character_mechanism_slots=list(character_cards.character_mechanism_slots),
            action_admissions=action_admissions,
            spawn_sources_by_servant=spawn_sources,
            replacement_policies=replacement_policies,
            servant_config_rows=servant_rows,
        )
        unit_birth_templates = _lower_unit_birth_templates(
            summon_monster_intents=[],
            servant_definitions=servant_definitions,
            wave_definitions=[],
            combatant_profiles=[],
            monster_data_cards=(),
            timeline_rules=self._lower_timeline_rules(),
        )
        issues = _owned_combatant_projection_build_issues(
            servant_rows=servant_rows,
            servant_definitions=servant_definitions,
            action_definitions=action_definitions,
            action_ability_bindings=action_ability_bindings,
            action_admissions=action_admissions,
            unit_birth_templates=unit_birth_templates,
        )
        owner_entity_refs = {
            owner_entity_ref
            for definition in servant_definitions
            for owner_entity_ref in definition.owner_entity_refs
        }
        owner_entities = self._lower_entity_table(
            "ExcelOutput/AvatarConfig.json",
            ENTITY_TABLES["ExcelOutput/AvatarConfig.json"],
            entity_ids=frozenset(owner_entity_refs),
        )
        owner_cards = tuple(
            card
            for card in character_cards.character_data_cards
            if card.entity_ref in owner_entity_refs
        )
        owner_card_ids = {card.card_id for card in owner_cards}
        owner_profile_ids = {card.profile_id for card in owner_cards}
        skill_formula_bindings = [
            binding
            for binding in skill_formula_bindings
            if binding.action_id in servant_action_ids
            or binding.character_data_card_id in owner_card_ids
        ]
        owner_action_ids = frozenset(
            f"avatar_skill:{skill_id}"
            for card in owner_cards
            for skill_id in card.skill_ids
            if str(skill_id)
        )
        owner_action_definitions = self._lower_action_definitions(
            action_ids=owner_action_ids,
            entity_types=frozenset({"avatar_skill"}),
        )
        (
            owner_action_ability_bindings,
            owner_ability_phases,
            owner_ability_tasks,
            owner_ability_effects,
            owner_ability_conditions,
            owner_ability_formulas,
            owner_ability_targets,
        ) = self._lower_action_ability_bindings(
            owner_action_definitions,
        )
        owner_ability_effects = (
            _attach_status_formula_bindings_to_add_modifier_effects(
                owner_ability_effects,
                owner_ability_tasks,
                skill_formula_bindings,
            )
        )
        owner_action_modifier_definitions = (
            self._lower_owned_action_modifier_definitions(
                owner_action_ability_bindings,
                owner_ability_effects,
            )
        )
        owner_ability_effects = _link_status_effect_runtime_fields(
            owner_ability_effects,
            owner_action_modifier_definitions,
            [],
        )
        owner_action_events, owner_hit_profiles = (
            _lower_action_execution_ir(
                owner_action_definitions,
                owner_action_ability_bindings,
                owner_ability_phases,
                skill_formula_bindings,
                [
                    policy
                    for policy in character_cards.bounce_policies
                    if policy.character_data_card_id in owner_card_ids
                ],
            )
        )
        owner_damage_emissions = _lower_damage_emissions(
            owner_ability_tasks,
            owner_ability_effects,
            owner_hit_profiles,
            skill_formula_bindings,
            self._damage_tag_registry,
        )
        owner_toughness_emissions = _lower_toughness_emissions(
            owner_ability_tasks,
            owner_ability_effects,
            owner_hit_profiles,
        )
        owner_ability_tasks = _admit_damage_ability_tasks(
            owner_ability_tasks,
            owner_damage_emissions,
            owner_toughness_emissions,
            owner_hit_profiles,
        )
        owner_avatar_ids = {
            entity_ref.split(":", 1)[1]
            for entity_ref in owner_entity_refs
            if entity_ref.startswith("avatar:")
        }
        owner_avatar_rows = [
            item
            for item in self._avatar_config_rows_prefer_enhanced()
            if str(item[2].get("AvatarID")) in owner_avatar_ids
        ]
        owner_action_sets = self._lower_combatant_action_sets(
            owner_action_definitions,
            entity_types=frozenset({"avatar"}),
            avatar_config_rows=owner_avatar_rows,
        )
        owner_action_sets, owner_action_admissions = (
            _lower_action_admissions(
                owner_action_sets,
                owner_action_definitions,
            )
        )
        action_definitions.extend(owner_action_definitions)
        action_ability_bindings.extend(owner_action_ability_bindings)
        action_admissions.extend(owner_action_admissions)
        combatant_action_sets.extend(owner_action_sets)
        ability_phases.extend(owner_ability_phases)
        ability_tasks.extend(owner_ability_tasks)
        ability_task_effects.extend(owner_ability_effects)
        ability_task_conditions.extend(owner_ability_conditions)
        ability_task_formulas.extend(owner_ability_formulas)
        ability_task_target_expressions.extend(owner_ability_targets)
        action_events.extend(owner_action_events)
        hit_profiles.extend(owner_hit_profiles)
        damage_emissions.extend(owner_damage_emissions)
        toughness_emissions.extend(owner_toughness_emissions)
        action_modifier_definitions = list(
            _dedupe_entities(
                [
                    *action_modifier_definitions,
                    *owner_action_modifier_definitions,
                ]
            ).values()
        )
        owned_ability_paths = sorted(
            {
                path
                for binding in action_ability_bindings
                for path in (
                    *(
                        tuple(binding.config_source.get("ability_file_paths"))
                        if isinstance(
                            binding.config_source.get(
                                "ability_file_paths"
                            ),
                            (list, tuple),
                        )
                        else ()
                    ),
                    *(
                        (
                            binding.config_source.get(
                                "ability_file_path"
                            ),
                        )
                        if isinstance(
                            binding.config_source.get(
                                "ability_file_path"
                            ),
                            str,
                        )
                        else ()
                    ),
                )
                if isinstance(path, str) and path
            }
        )
        lowered_owned_files = [
            self._lower_ability_file(
                self.tbgd_root / relative_path,
                {},
                ability_file_order=order,
            )
            for order, relative_path in enumerate(owned_ability_paths)
        ]
        action_modifier_definitions = list(
            _dedupe_entities(
                [
                    *action_modifier_definitions,
                    *(
                        entity
                        for lowered in lowered_owned_files
                        for entity in lowered.entities
                    ),
                ]
            ).values()
        )
        ability_task_effects = list(
            merge_identical_ir_items(
                (
                    *ability_task_effects,
                    *(
                        effect
                        for lowered in lowered_owned_files
                        for effect in lowered.effects
                    ),
                ),
                "effect_id",
                item_kind="effect",
            )
        )
        ability_task_conditions = list(
            merge_identical_ir_items(
                (
                    *ability_task_conditions,
                    *(
                        condition
                        for lowered in lowered_owned_files
                        for condition in lowered.conditions
                    ),
                ),
                "condition_id",
                item_kind="condition",
            )
        )
        ability_task_formulas = list(
            merge_identical_ir_items(
                (
                    *ability_task_formulas,
                    *(
                        formula
                        for lowered in lowered_owned_files
                        for formula in lowered.formulas
                    ),
                ),
                "formula_id",
                item_kind="formula",
            )
        )
        ability_task_target_expressions = list(
            merge_identical_ir_items(
                (
                    *ability_task_target_expressions,
                    *(
                        target
                        for lowered in lowered_owned_files
                        for target in lowered.target_expressions
                    ),
                ),
                "target_expression_id",
                item_kind="target_expression",
            )
        )
        return OwnedCombatantAdmissionProjection(
            servant_definitions=tuple(
                sorted(
                    merge_identical_ir_items(
                        servant_definitions,
                        "servant_definition_id",
                        item_kind="servant_definition",
                    ),
                    key=attrgetter("servant_definition_id"),
                )
            ),
            action_definitions=tuple(
                sorted(
                    merge_identical_ir_items(
                        action_definitions,
                        "definition_id",
                        item_kind="action_definition",
                    ),
                    key=attrgetter("action_id", "level", "definition_id"),
                )
            ),
            action_ability_bindings=tuple(
                sorted(
                    merge_identical_ir_items(
                        action_ability_bindings,
                        "binding_id",
                        item_kind="action_ability_binding",
                    ),
                    key=attrgetter("action_id", "level", "binding_id"),
                )
            ),
            action_admissions=tuple(
                sorted(
                    merge_identical_ir_items(
                        action_admissions,
                        "admission_id",
                        item_kind="action_admission",
                    ),
                    key=attrgetter(
                        "owner_entity_ref",
                        "action_id",
                        "action_level",
                        "admission_id",
                    ),
                )
            ),
            unit_birth_templates=tuple(
                sorted(
                    merge_identical_ir_items(
                        unit_birth_templates,
                        "birth_template_id",
                        item_kind="unit_birth_template",
                    ),
                    key=attrgetter("birth_template_id"),
                )
            ),
            issues=issues,
            entities=tuple(
                sorted(
                    _dedupe_entities(
                        [*owner_entities, *action_modifier_definitions]
                    ).values(),
                    key=attrgetter("entity_id"),
                )
            ),
            combatant_action_sets=tuple(
                sorted(
                    merge_identical_ir_items(
                        combatant_action_sets,
                        "combatant_action_set_id",
                        item_kind="combatant_action_set",
                    ),
                    key=attrgetter("combatant_action_set_id"),
                )
            ),
            ability_phases=tuple(
                sorted(
                    merge_identical_ir_items(
                        ability_phases,
                        "phase_id",
                        item_kind="ability_phase",
                    ),
                    key=attrgetter("phase_id"),
                )
            ),
            ability_tasks=tuple(
                sorted(
                    merge_identical_ir_items(
                        ability_tasks,
                        "task_id",
                        item_kind="ability_task",
                    ),
                    key=attrgetter("task_id"),
                )
            ),
            action_events=tuple(
                sorted(
                    merge_identical_ir_items(
                        action_events,
                        "action_event_id",
                        item_kind="action_event",
                    ),
                    key=attrgetter("action_id", "level", "action_event_id"),
                )
            ),
            hit_profiles=tuple(
                sorted(
                    merge_identical_ir_items(
                        hit_profiles,
                        "hit_profile_id",
                        item_kind="hit_profile",
                    ),
                    key=attrgetter("hit_profile_id"),
                )
            ),
            skill_formula_bindings=tuple(
                sorted(
                    merge_identical_ir_items(
                        skill_formula_bindings,
                        "binding_id",
                        item_kind="skill_formula_binding",
                    ),
                    key=attrgetter("action_id", "level", "binding_id"),
                )
            ),
            damage_emissions=tuple(
                sorted(
                    merge_identical_ir_items(
                        damage_emissions,
                        "damage_emission_id",
                        item_kind="damage_emission",
                    ),
                    key=attrgetter("damage_emission_id"),
                )
            ),
            toughness_emissions=tuple(
                sorted(
                    merge_identical_ir_items(
                        toughness_emissions,
                        "toughness_emission_id",
                        item_kind="toughness_emission",
                    ),
                    key=attrgetter("toughness_emission_id"),
                )
            ),
            effects=tuple(
                sorted(
                    merge_identical_ir_items(
                        ability_task_effects,
                        "effect_id",
                        item_kind="effect",
                    ),
                    key=attrgetter("effect_id"),
                )
            ),
            conditions=tuple(
                sorted(
                    merge_identical_ir_items(
                        ability_task_conditions,
                        "condition_id",
                        item_kind="condition",
                    ),
                    key=attrgetter("condition_id"),
                )
            ),
            formulas=tuple(
                sorted(
                    merge_identical_ir_items(
                        ability_task_formulas,
                        "formula_id",
                        item_kind="formula",
                    ),
                    key=attrgetter("formula_id"),
                )
            ),
            target_expressions=tuple(
                sorted(
                    merge_identical_ir_items(
                        ability_task_target_expressions,
                        "target_expression_id",
                        item_kind="target_expression",
                    ),
                    key=attrgetter("target_expression_id"),
                )
            ),
            status_callbacks=tuple(
                sorted(
                    merge_identical_ir_items(
                        (
                            callback
                            for lowered in lowered_owned_files
                            for callback in lowered.status_callbacks
                        ),
                        "callback_id",
                        item_kind="status_callback",
                    ),
                    key=attrgetter("callback_id"),
                )
            ),
            status_callback_tasks=tuple(
                sorted(
                    merge_identical_ir_items(
                        (
                            task
                            for lowered in lowered_owned_files
                            for task in lowered.status_callback_tasks
                        ),
                        "task_id",
                        item_kind="status_callback_task",
                    ),
                    key=attrgetter("task_id"),
                )
            ),
            status_damage_emissions=tuple(
                sorted(
                    merge_identical_ir_items(
                        (
                            emission
                            for lowered in lowered_owned_files
                            for emission in lowered.status_damage_emissions
                        ),
                        "status_damage_emission_id",
                        item_kind="status_damage_emission",
                    ),
                    key=attrgetter("status_damage_emission_id"),
                )
            ),
            damage_modifiers=tuple(
                sorted(
                    merge_identical_ir_items(
                        (
                            modifier
                            for lowered in lowered_owned_files
                            for modifier in lowered.damage_modifiers
                        ),
                        "damage_modifier_id",
                        item_kind="damage_modifier",
                    ),
                    key=attrgetter("damage_modifier_id"),
                )
            ),
            action_delay_emissions=tuple(
                sorted(
                    merge_identical_ir_items(
                        (
                            emission
                            for lowered in lowered_owned_files
                            for emission in lowered.action_delay_emissions
                        ),
                        "action_delay_emission_id",
                        item_kind="action_delay_emission",
                    ),
                    key=attrgetter("action_delay_emission_id"),
                )
            ),
            queue_intents=tuple(
                sorted(
                    merge_identical_ir_items(
                        (
                            intent
                            for lowered in lowered_owned_files
                            for intent in lowered.queue_intents
                        ),
                        "queue_intent_id",
                        item_kind="queue_intent",
                    ),
                    key=attrgetter("queue_intent_id"),
                )
            ),
            skill_continuations=tuple(
                sorted(
                    merge_identical_ir_items(
                        (
                            continuation
                            for lowered in lowered_owned_files
                            for continuation in lowered.skill_continuations
                        ),
                        "continuation_id",
                        item_kind="skill_continuation",
                    ),
                    key=attrgetter("continuation_id"),
                )
            ),
            triggers=tuple(
                sorted(
                    merge_identical_ir_items(
                        (
                            trigger
                            for lowered in lowered_owned_files
                            for trigger in lowered.triggers
                        ),
                        "trigger_id",
                        item_kind="trigger",
                    ),
                    key=attrgetter("trigger_id"),
                )
            ),
            avatar_profiles=tuple(
                profile
                for profile in character_cards.avatar_profiles
                if profile.avatar_profile_id in owner_profile_ids
            ),
            character_data_cards=owner_cards,
            character_equipment_eligibilities=tuple(
                eligibility
                for eligibility in (
                    character_cards.character_equipment_eligibilities
                )
                if eligibility.character_card_id in owner_card_ids
            ),
            character_mechanism_slots=tuple(
                slot
                for slot in character_cards.character_mechanism_slots
                if slot.character_data_card_id in owner_card_ids
            ),
            character_trace_nodes=tuple(
                node
                for node in character_cards.character_trace_nodes
                if node.character_data_card_id in owner_card_ids
            ),
            character_eidolon_slots=tuple(
                slot
                for slot in character_cards.character_eidolon_slots
                if slot.character_data_card_id in owner_card_ids
            ),
            bounce_policies=tuple(
                policy
                for policy in character_cards.bounce_policies
                if policy.character_data_card_id in owner_card_ids
            ),
        )

    def _lower_owned_action_modifier_definitions(
        self,
        bindings: list[ActionAbilityBindingIR],
        effects: list[EffectIR],
    ) -> list[RuleEntity]:
        required_modifier_names = {
            modifier_name
            for effect in effects
            if effect.opcode == "AddModifier"
            for standard in (
                effect.payload.get("standard")
                if isinstance(effect.payload.get("standard"), dict)
                else {},
            )
            if isinstance(
                modifier_name := standard.get("modifier_name"),
                str,
            )
            and modifier_name
        }
        if not required_modifier_names:
            return []
        ability_paths = sorted(
            {
                path
                for binding in bindings
                for raw_paths in (
                    binding.config_source.get("ability_file_paths"),
                )
                if isinstance(raw_paths, list)
                for path in raw_paths
                if isinstance(path, str) and path
            }
        )
        definitions: list[RuleEntity] = []
        for ability_file_order, relative_path in enumerate(ability_paths):
            lowered = self._lower_ability_file(
                self.tbgd_root / relative_path,
                {},
                ability_file_order=ability_file_order,
            )
            definitions.extend(
                entity
                for entity in lowered.entities
                if entity.entity_type == "modifier_definition"
                and (
                    entity.fields.get("modifier_name")
                    in required_modifier_names
                )
            )
        return list(_dedupe_entities(definitions).values())

    def _offensive_servant_config_rows(
        self,
        servant_rows: list[tuple[str, int, dict[str, Any]]],
    ) -> list[tuple[str, int, dict[str, Any]]]:
        relative_path = "ExcelOutput/AvatarServantSkillConfig.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        offensive_skill_ids = {
            str(row.get("SkillID"))
            for row in data
            if isinstance(row, dict)
            and row.get("SkillID") is not None
            and row.get("AttackType") == "Servant"
            and row.get("SkillEffect")
            in {"AoEAttack", "Blast", "Bounce", "SingleAttack"}
        }
        return [
            item
            for item in servant_rows
            if any(
                str(skill_id) in offensive_skill_ids
                for skill_id in (
                    item[2].get("SkillIDList")
                    if isinstance(item[2].get("SkillIDList"), list)
                    else ()
                )
            )
        ]

    def build(self) -> CanonicalIR:
        character_ability_source_graph_catalog = (
            self.build_character_ability_source_graph_catalog()
        )
        character_ability_source_resolution_catalog = (
            self.build_character_ability_source_resolution_catalog()
        )
        light_cone_catalog = build_light_cone_catalog(self.tbgd_root)
        light_cone_definitions = require_complete_light_cone_catalog(light_cone_catalog)
        relic_catalog_result = build_relic_catalog(self.tbgd_root)
        relic_catalog = require_complete_relic_catalog(relic_catalog_result)
        relic_set_thresholds = relic_catalog.set_thresholds
        equipment_ability_sources = _equipment_ability_source_projection(
            (*light_cone_definitions, *relic_set_thresholds)
        )
        entities: list[RuleEntity] = []
        action_definitions: list[ActionDefinitionIR] = []
        triggers: list[TriggerIR] = []
        effects: list[EffectIR] = []
        conditions: list[ConditionIR] = []
        formulas: list[FormulaIR] = []
        status_callbacks: list[StatusCallbackIR] = []
        status_callback_tasks: list[StatusCallbackTaskIR] = []
        ability_property_watchers: list[AbilityPropertyWatcherIR] = []
        ability_property_ranges: list[AbilityPropertyRangeIR] = []
        status_damage_emissions: list[StatusDamageEmissionIR] = []
        damage_modifiers: list[DamageModifierIR] = []
        action_delay_emissions: list[ActionDelayEmissionIR] = []
        queue_intents: list[QueueIntentIR] = []
        skill_continuations: list[SkillContinuationIR] = []
        super_break_emissions: list[SuperBreakEmissionIR] = []
        target_expressions: list[TargetExpressionIR] = []
        target_expressions.extend(self._lower_global_target_expressions())
        timeline_rules = self._lower_timeline_rules()
        resource_rules = self._lower_resource_rules()
        battle_state_transitions = self._lower_battle_state_transitions()
        damage_formula_rules = self._lower_damage_formula_rules()
        damage_route_rules = self._lower_damage_route_rules()
        shield_priority_rules = self._lower_shield_priority_rules()
        queue_priorities = self._lower_queue_priorities()
        queue_priority_lookup = {
            (priority.priority_table, priority.priority_key): priority
            for priority in queue_priorities
            if priority.coverage_status == "executable"
        }

        table_stats: dict[str, dict[str, Any]] = {}
        for relative_path, spec in ENTITY_TABLES.items():
            entities.extend(self._lower_entity_table(relative_path, spec))
            table_stats[relative_path] = self._table_stats(relative_path, spec[1])
        entities = list(_dedupe_entities(entities).values())
        character_cards = build_character_card_ir(
            self.tbgd_root,
            max_records_per_table=None,
            skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
            ability_source_graph_catalog=character_ability_source_graph_catalog,
            ability_scope_catalog=self._character_ability_scope_catalog,
        )
        avatar_profiles = character_cards.avatar_profiles
        character_data_cards = character_cards.character_data_cards
        character_equipment_eligibilities = (
            character_cards.character_equipment_eligibilities
        )
        character_mechanism_slots = list(character_cards.character_mechanism_slots)
        character_trace_nodes = character_cards.character_trace_nodes
        character_eidolon_slots = character_cards.character_eidolon_slots
        skill_formula_bindings = character_cards.skill_formula_bindings
        bounce_policies = character_cards.bounce_policies
        monster_cards = build_monster_card_ir(
            self.tbgd_root,
            max_records_per_table=self.limits.max_records_per_table,
        )
        monster_data_cards = monster_cards.monster_data_cards
        summon_unit_definitions = self._lower_summon_unit_definitions()
        passive_mechanism_slots = list(monster_cards.passive_mechanism_slots)
        skill_formula_bindings = [*skill_formula_bindings, *monster_cards.skill_formula_bindings]
        combatant_profiles = self._lower_combatant_profiles()
        wave_definitions = self._lower_wave_definitions(entities, combatant_profiles, monster_data_cards)
        action_definitions = self._lower_action_definitions()
        (
            action_ability_bindings,
            ability_phases,
            ability_tasks,
            ability_task_effects,
            ability_task_conditions,
            ability_task_formulas,
            ability_task_target_expressions,
        ) = self._lower_action_ability_bindings(action_definitions)
        target_expressions.extend(ability_task_target_expressions)
        ability_task_effects = _attach_status_formula_bindings_to_add_modifier_effects(
            ability_task_effects,
            ability_tasks,
            skill_formula_bindings,
        )
        skill_formula_bindings.extend(
            self._lower_servant_damage_formula_bindings(
                action_definitions,
                ability_tasks,
                ability_task_effects,
            )
        )
        effects.extend(ability_task_effects)
        conditions.extend(ability_task_conditions)
        formulas.extend(ability_task_formulas)
        action_events, hit_profiles = _lower_action_execution_ir(
            action_definitions,
            action_ability_bindings,
            ability_phases,
            skill_formula_bindings,
            bounce_policies,
        )
        damage_emissions = _lower_damage_emissions(
            ability_tasks,
            ability_task_effects,
            hit_profiles,
            skill_formula_bindings,
            self._damage_tag_registry,
        )
        toughness_emissions = _lower_toughness_emissions(
            ability_tasks,
            ability_task_effects,
            hit_profiles,
        )
        break_base_damage = self._lower_break_base_damage()
        (
            break_templates,
            break_damage_emissions,
            break_status_emissions,
            break_effects,
            break_target_expressions,
        ) = self._lower_break_templates()
        target_expressions.extend(break_target_expressions)
        super_break_emissions.extend(self._lower_super_break_emissions())
        effects.extend(break_effects)
        for relative_path, _, id_key in ACTION_DEFINITION_TABLES:
            table_stats[f"action_definitions:{relative_path}"] = self._table_stats(relative_path, id_key)

        ability_files = self._ability_files()
        selected_ability_files = _limit_sequence(ability_files, self.limits.max_ability_files)
        for ability_file_order, path in enumerate(selected_ability_files):
            relative = relative_source_path(self.tbgd_root, path)
            selected_equipment_sources = None
            if relative.startswith("Config/ConfigAbility/Equip/"):
                selected_equipment_sources = equipment_ability_sources.get(relative, {})
                if not selected_equipment_sources:
                    continue
            lowered = self._lower_ability_file(
                path,
                queue_priority_lookup,
                ability_file_order=ability_file_order,
                selected_equipment_sources=selected_equipment_sources,
            )
            entities.extend(lowered.entities)
            triggers.extend(lowered.triggers)
            effects.extend(lowered.effects)
            conditions.extend(lowered.conditions)
            formulas.extend(lowered.formulas)
            target_expressions.extend(lowered.target_expressions)
            status_callbacks.extend(lowered.status_callbacks)
            status_callback_tasks.extend(lowered.status_callback_tasks)
            ability_property_watchers.extend(lowered.ability_property_watchers)
            ability_property_ranges.extend(lowered.ability_property_ranges)
            status_damage_emissions.extend(lowered.status_damage_emissions)
            damage_modifiers.extend(lowered.damage_modifiers)
            action_delay_emissions.extend(lowered.action_delay_emissions)
            queue_intents.extend(lowered.queue_intents)
            skill_continuations.extend(lowered.skill_continuations)
        (
            standalone_ability_graphs,
            standalone_phases,
            standalone_tasks,
            standalone_effects,
            standalone_conditions,
            standalone_formulas,
            standalone_target_expressions,
        ) = self._lower_standalone_ability_graphs(selected_ability_files)
        (
            equipment_ability_graphs,
            equipment_phases,
            equipment_tasks,
            equipment_effects,
            equipment_conditions,
            equipment_formulas,
            equipment_target_expressions,
            equipment_parameter_reads,
        ) = self._lower_equipment_ability_graphs(
            (*light_cone_definitions, *relic_set_thresholds),
            status_callbacks=status_callbacks,
        )
        standalone_ability_graphs.extend(equipment_ability_graphs)
        standalone_phases.extend(equipment_phases)
        standalone_tasks.extend(equipment_tasks)
        standalone_effects.extend(equipment_effects)
        standalone_conditions.extend(equipment_conditions)
        standalone_formulas.extend(equipment_formulas)
        standalone_target_expressions.extend(equipment_target_expressions)
        (
            light_cone_definitions,
            relic_set_thresholds,
            equipment_mechanism_refs,
        ) = (
            _attach_equipment_mechanism_refs(
                light_cone_definitions,
                relic_set_thresholds,
                equipment_ability_graphs,
                equipment_parameter_reads,
            )
        )
        ability_phases.extend(standalone_phases)
        ability_tasks.extend(standalone_tasks)
        effects.extend(standalone_effects)
        conditions.extend(standalone_conditions)
        formulas.extend(standalone_formulas)
        target_expressions.extend(standalone_target_expressions)
        ability_tasks = _link_trigger_ability_graphs(
            ability_tasks,
            effects,
            standalone_ability_graphs,
            ability_phases,
        )
        standalone_task_ids = {task.task_id for task in standalone_tasks}
        linked_standalone_tasks = [task for task in ability_tasks if task.task_id in standalone_task_ids]
        skill_formula_bindings.extend(
            _project_standalone_skill_formula_bindings(
                linked_standalone_tasks,
                standalone_effects,
                skill_formula_bindings,
            )
        )
        standalone_hit_profiles = _lower_standalone_hit_profiles(
            standalone_tasks,
            standalone_effects,
            skill_formula_bindings,
        )
        hit_profiles.extend(standalone_hit_profiles)
        damage_emissions.extend(
            _lower_damage_emissions(
                standalone_tasks,
                standalone_effects,
                standalone_hit_profiles,
                skill_formula_bindings,
                self._damage_tag_registry,
            )
        )
        toughness_emissions.extend(
            _lower_toughness_emissions(
                standalone_tasks,
                standalone_effects,
                standalone_hit_profiles,
            )
        )
        ability_tasks = _admit_damage_ability_tasks(
            ability_tasks,
            damage_emissions,
            toughness_emissions,
            hit_profiles,
        )
        character_mechanism_slots = _admit_trace_startup_ability_slots(
            character_mechanism_slots,
            standalone_graphs=standalone_ability_graphs,
            ability_tasks=ability_tasks,
            effects=effects,
        )
        passive_mechanism_slots = _admit_passive_startup_slots(
            passive_mechanism_slots,
            standalone_graphs=standalone_ability_graphs,
            ability_tasks=ability_tasks,
            effects=effects,
            triggers=triggers,
        )
        skill_continuations = _skill_continuations_from_ability_tasks(ability_tasks)
        combatant_action_sets = self._lower_combatant_action_sets(action_definitions)
        combatant_action_sets, action_admissions = _lower_action_admissions(
            combatant_action_sets,
            action_definitions,
        )
        summon_monster_intents = _lower_summon_monster_intents(
            ability_tasks=ability_tasks,
            effects=effects,
            combatant_profiles=combatant_profiles,
            monster_data_cards=monster_data_cards,
        )
        status_event_families = _lower_status_event_families(status_callbacks, status_callback_tasks)
        status_event_blocked_reasons = _status_event_blocked_reasons(status_event_families)
        status_callbacks = _block_status_callbacks_by_event_family(status_callbacks, status_event_blocked_reasons)
        effects = _link_status_effect_runtime_fields(
            effects,
            entities,
            status_callbacks,
            ability_property_watchers,
        )
        status_callback_blocked_reasons = {
            callback.callback_id: (
                status_event_blocked_reasons.get(callback.event)
                or callback.blocked_reason
                or callback.blocking_dependency
            )
            for callback in status_callbacks
            if (
                callback.event in status_event_blocked_reasons
                or callback.blocked_reason
                == "equipment_modifier_definition_unreferenced"
            )
        }
        status_callback_tasks = _block_status_callback_tasks_by_callback(
            status_callback_tasks,
            status_callback_blocked_reasons,
        )
        status_damage_emissions = _block_status_callback_derived_by_callback(
            status_damage_emissions,
            status_callback_blocked_reasons,
        )
        damage_modifiers = _block_status_callback_derived_by_callback(
            damage_modifiers,
            status_callback_blocked_reasons,
        )
        action_delay_emissions = _block_status_callback_derived_by_callback(
            action_delay_emissions,
            status_callback_blocked_reasons,
        )
        queue_intents = _block_status_callback_derived_by_callback(
            queue_intents,
            status_callback_blocked_reasons,
        )
        status_event_families = _lower_status_event_families(status_callbacks, status_callback_tasks)
        queue_resolutions = _lower_queue_resolutions(
            queue_intents=queue_intents,
            action_bindings=action_ability_bindings,
            ability_phases=ability_phases,
            standalone_graphs=standalone_ability_graphs,
            combatant_action_sets=combatant_action_sets,
        )
        assistant_ability_resolutions = _lower_assistant_ability_resolutions(queue_intents, queue_resolutions)
        servant_spawn_sources = _discover_servant_spawn_sources(
            self.tbgd_root,
            selected_ability_files,
        )
        servant_replacement_policies = _discover_servant_replacement_policies(
            self.tbgd_root,
            selected_ability_files,
        )
        servant_definitions = self._lower_servant_definitions(
            combatant_action_sets,
            action_ability_bindings,
            character_data_cards=character_data_cards,
            character_trace_nodes=character_trace_nodes,
            character_eidolon_slots=character_eidolon_slots,
            character_mechanism_slots=character_mechanism_slots,
            action_admissions=action_admissions,
            spawn_sources_by_servant=servant_spawn_sources,
            replacement_policies=servant_replacement_policies,
        )
        unit_birth_templates = _lower_unit_birth_templates(
            summon_monster_intents=summon_monster_intents,
            servant_definitions=servant_definitions,
            wave_definitions=wave_definitions,
            combatant_profiles=combatant_profiles,
            monster_data_cards=monster_data_cards,
            timeline_rules=timeline_rules,
        )
        ability_tasks = _admit_summon_monster_ability_tasks(
            ability_tasks,
            summon_monster_intents,
            unit_birth_templates,
        )
        extra_turn_source_basis = self._extra_turn_source_basis()
        queue_windows = _lower_queue_windows(queue_intents, queue_resolutions, extra_turn_source_basis)
        queue_lifecycle_policies = _lower_queue_lifecycle_policies(queue_windows, extra_turn_source_basis)
        extra_action_policies = _lower_extra_action_policies(
            queue_intents=queue_intents,
            queue_windows=queue_windows,
            queue_lifecycle_policies=queue_lifecycle_policies,
            skill_continuations=skill_continuations,
            extra_turn_source_basis=extra_turn_source_basis,
        )
        runtime_character_slots = _character_runtime_mechanism_slots(
            character_data_cards=character_data_cards,
            skill_formula_bindings=skill_formula_bindings,
            action_ability_bindings=action_ability_bindings,
            status_callbacks=status_callbacks,
            damage_modifiers=damage_modifiers,
            queue_intents=queue_intents,
            queue_windows=queue_windows,
            extra_action_policies=extra_action_policies,
            skill_continuations=skill_continuations,
        )
        character_mechanism_slots.extend(runtime_character_slots)
        character_data_cards = _attach_character_runtime_mechanism_slots(character_data_cards, runtime_character_slots)
        entities = list(_dedupe_entities(entities).values())
        formulas.extend(self._lower_elation_mechanics())
        formulas.extend(self._lower_damage_behavior_templates())

        return CanonicalIR(
            version=BASELINE_VERSION,
            entities=tuple(entities),
            avatar_profiles=tuple(avatar_profiles),
            character_data_cards=tuple(character_data_cards),
            character_equipment_eligibilities=tuple(
                character_equipment_eligibilities
            ),
            monster_data_cards=tuple(monster_data_cards),
            light_cone_definitions=tuple(light_cone_definitions),
            relic_domain_definitions=relic_catalog.domain_definitions,
            relic_slot_definitions=relic_catalog.slot_definitions,
            relic_main_affix_group_definitions=(
                relic_catalog.main_affix_group_definitions
            ),
            relic_main_affix_definitions=relic_catalog.main_affix_definitions,
            relic_sub_affix_group_definitions=(
                relic_catalog.sub_affix_group_definitions
            ),
            relic_sub_affix_definitions=relic_catalog.sub_affix_definitions,
            relic_template_definitions=relic_catalog.template_definitions,
            relic_set_definitions=relic_catalog.set_definitions,
            relic_set_thresholds=relic_set_thresholds,
            equipment_ability_parameter_reads=tuple(equipment_parameter_reads),
            equipment_mechanism_refs=tuple(equipment_mechanism_refs),
            summon_unit_definitions=tuple(summon_unit_definitions),
            unit_birth_templates=tuple(unit_birth_templates),
            summon_monster_intents=tuple(summon_monster_intents),
            assistant_ability_resolutions=tuple(assistant_ability_resolutions),
            servant_definitions=tuple(servant_definitions),
            character_mechanism_slots=tuple(character_mechanism_slots),
            passive_mechanism_slots=tuple(passive_mechanism_slots),
            character_trace_nodes=tuple(character_trace_nodes),
            character_eidolon_slots=tuple(character_eidolon_slots),
            character_build_selector_relations=tuple(
                character_cards.character_build_selector_relations
            ),
            character_build_selector_gaps=tuple(
                character_cards.character_build_selector_gaps
            ),
            bounce_policies=tuple(bounce_policies),
            combatant_profiles=tuple(combatant_profiles),
            action_definitions=tuple(action_definitions),
            action_ability_bindings=tuple(action_ability_bindings),
            ability_phases=tuple(ability_phases),
            ability_tasks=tuple(ability_tasks),
            action_events=tuple(action_events),
            hit_profiles=tuple(hit_profiles),
            skill_formula_bindings=tuple(skill_formula_bindings),
            damage_emissions=tuple(damage_emissions),
            toughness_emissions=tuple(toughness_emissions),
            break_templates=tuple(break_templates),
            break_base_damage=tuple(break_base_damage),
            break_damage_emissions=tuple(break_damage_emissions),
            break_status_emissions=tuple(break_status_emissions),
            status_event_families=tuple(status_event_families),
            status_callbacks=tuple(status_callbacks),
            status_callback_tasks=tuple(status_callback_tasks),
            ability_property_watchers=tuple(ability_property_watchers),
            ability_property_ranges=tuple(ability_property_ranges),
            status_damage_emissions=tuple(status_damage_emissions),
            damage_modifiers=tuple(damage_modifiers),
            action_delay_emissions=tuple(action_delay_emissions),
            queue_intents=tuple(queue_intents),
            queue_resolutions=tuple(queue_resolutions),
            queue_priorities=tuple(queue_priorities),
            queue_windows=tuple(queue_windows),
            queue_lifecycle_policies=tuple(queue_lifecycle_policies),
            extra_action_policies=tuple(extra_action_policies),
            skill_continuations=tuple(skill_continuations),
            standalone_ability_graphs=tuple(standalone_ability_graphs),
            combatant_action_sets=tuple(combatant_action_sets),
            action_admissions=tuple(action_admissions),
            timeline_rules=tuple(timeline_rules),
            resource_rules=tuple(resource_rules),
            battle_state_transitions=tuple(battle_state_transitions),
            damage_formula_rules=tuple(damage_formula_rules),
            damage_route_rules=tuple(damage_route_rules),
            shield_priority_rules=tuple(shield_priority_rules),
            super_break_emissions=tuple(super_break_emissions),
            target_expressions=tuple(_dedupe_target_expressions(target_expressions).values()),
            wave_definitions=tuple(wave_definitions),
            triggers=tuple(triggers),
            effects=tuple(effects),
            conditions=tuple(conditions),
            formulas=tuple(formulas),
            character_ability_source_graph_catalog=(
                character_ability_source_graph_catalog
            ),
            character_ability_source_resolution_catalog=(
                character_ability_source_resolution_catalog
            ),
            metadata={
                "source": "turnbasedgamedata-main",
                "lowering": "tbgd_first_v0_200",
                "character_ability_source_graph": {
                    "catalog_id": character_ability_source_graph_catalog.catalog_id,
                    "snapshot_id": character_ability_source_graph_catalog.snapshot_id,
                    "scope_catalog_id": (
                        character_ability_source_graph_catalog.scope_catalog_id
                    ),
                    "source_fingerprint": (
                        character_ability_source_graph_catalog.source_fingerprint
                    ),
                },
                "character_ability_source_resolution": {
                    "catalog_id": (
                        character_ability_source_resolution_catalog.catalog_id
                    ),
                    "typed_dynamic_operation_count": sum(
                        item.typed_operation is not None
                        for item in character_ability_source_resolution_catalog.decoded_items
                    ),
                },
                "limits": {
                    "max_records_per_table": self.limits.max_records_per_table,
                    "max_ability_files": self.limits.max_ability_files,
                    "max_callbacks_per_file": self.limits.max_callbacks_per_file,
                },
                "sampled": {
                    "entity_tables": self.limits.max_records_per_table is not None,
                    "ability_files": self.limits.max_ability_files is not None
                    and len(selected_ability_files) < len(ability_files),
                    "callbacks": self.limits.max_callbacks_per_file is not None,
                },
                **_equipment_catalog_fingerprint_metadata(
                    light_cone_source_content_fingerprint=(
                        light_cone_catalog.source_content_fingerprint
                    ),
                    relic_source_content_fingerprint=(
                        relic_catalog_result.source_content_fingerprint
                    ),
                    light_cone_catalog_definition_fingerprint=(
                        light_cone_catalog.catalog_definition_fingerprint
                    ),
                    relic_catalog_definition_fingerprint=(
                        relic_catalog_result.catalog_definition_fingerprint
                    ),
                ),
                "light_cone_catalog_limited": False,
                "equipment_ability_graph_status": {
                    "graph_count": len(equipment_ability_graphs),
                    "executable_count": sum(
                        1
                        for graph in equipment_ability_graphs
                        if graph.coverage_status == "executable"
                    ),
                    "partial_count": sum(
                        1
                        for graph in equipment_ability_graphs
                        if graph.coverage_status != "executable"
                    ),
                    "parameter_read_count": len(equipment_parameter_reads),
                },
                "table_status": table_stats,
                "ability_file_status": {
                    "raw_count": len(ability_files),
                    "lowered_count": len(selected_ability_files),
                    "skipped_count": max(0, len(ability_files) - len(selected_ability_files)),
                },
                "action_binding_status": {
                    "lowered_count": len(action_ability_bindings),
                    "ability_phase_count": len(ability_phases),
                    "ability_task_count": len(ability_tasks),
                    "damage_emission_count": len(damage_emissions),
                    "toughness_emission_count": len(toughness_emissions),
                    "break_template_count": len(break_templates),
                    "break_base_damage_count": len(break_base_damage),
                    "break_damage_emission_count": len(break_damage_emissions),
                    "break_status_emission_count": len(break_status_emissions),
                    "status_event_family_count": len(status_event_families),
                    "executable_status_event_family_count": sum(
                        1 for family in status_event_families if family.coverage_status == "executable"
                    ),
                    "status_callback_count": len(status_callbacks),
                    "status_callback_task_count": len(status_callback_tasks),
                    "status_damage_emission_count": len(status_damage_emissions),
                    "action_delay_emission_count": len(action_delay_emissions),
                    "queue_intent_count": len(queue_intents),
                    "queue_resolution_count": len(queue_resolutions),
                    "queue_priority_count": len(queue_priorities),
                    "queue_window_count": len(queue_windows),
                    "standalone_ability_graph_count": len(standalone_ability_graphs),
                    "combatant_action_set_count": len(combatant_action_sets),
                    "action_admission_count": len(action_admissions),
                    "timeline_rule_count": len(timeline_rules),
                    "resource_rule_count": len(resource_rules),
                    "super_break_emission_count": len(super_break_emissions),
                    "target_expression_count": len(target_expressions),
                    "executable_target_expression_count": sum(
                        1 for expression in target_expressions if expression.coverage_status == "executable"
                    ),
                    "wave_definition_count": len(wave_definitions),
                    "executable_wave_definition_count": sum(
                        1 for definition in wave_definitions if definition.coverage_status == "executable"
                    ),
                    "skill_formula_binding_count": len(skill_formula_bindings),
                    "bounce_policy_count": len(bounce_policies),
                    "character_mechanism_slot_count": len(character_mechanism_slots),
                    "passive_mechanism_slot_count": len(passive_mechanism_slots),
                    "executable_passive_mechanism_slot_count": sum(
                        1 for slot in passive_mechanism_slots if slot.coverage_status == "executable"
                    ),
                    "character_trace_node_count": len(character_trace_nodes),
                    "character_eidolon_slot_count": len(character_eidolon_slots),
                },
                "avatar_profile_status": {
                    "lowered_count": len(avatar_profiles),
                    "executable_count": sum(1 for profile in avatar_profiles if profile.coverage_status == "executable"),
                    "blocked_count": sum(1 for profile in avatar_profiles if profile.coverage_status == "blocked"),
                },
                "character_data_card_status": {
                    "lowered_count": len(character_data_cards),
                    "executable_count": sum(1 for card in character_data_cards if card.coverage_status == "executable"),
                    "blocked_count": sum(1 for card in character_data_cards if card.coverage_status == "blocked"),
                },
                "monster_data_card_status": {
                    "lowered_count": len(monster_data_cards),
                    "sequence_admitted_count": sum(
                        1
                        for card in monster_data_cards
                        if card.ai_policy.get("admission_status") == "executable"
                    ),
                    "blocked_count": sum(1 for card in monster_data_cards if card.coverage_status == "blocked"),
                },
                "combatant_profile_status": {
                    "lowered_count": len(combatant_profiles),
                    "executable_count": sum(1 for profile in combatant_profiles if profile.coverage_status == "executable"),
                    "blocked_count": sum(1 for profile in combatant_profiles if profile.coverage_status == "blocked"),
                },
            },
        )

    def _lower_timeline_rules(self) -> list[TimelineRuleIR]:
        return list(build_engine_rule_registry().timeline_rules)

    def _lower_resource_rules(self) -> list[ResourceRuleIR]:
        return list(build_engine_rule_registry().resource_rules)

    def _lower_damage_formula_rules(self) -> list[DamageFormulaRuleIR]:
        return list(build_engine_rule_registry().damage_formula_rules)

    def _lower_damage_route_rules(self) -> list[DamageRouteRuleIR]:
        return list(build_engine_rule_registry().damage_route_rules)

    def _lower_shield_priority_rules(self) -> list[ShieldPriorityRuleIR]:
        return list(build_engine_rule_registry().shield_priority_rules)

    def _lower_global_target_expressions(self) -> list[TargetExpressionIR]:
        alias_relative = "Config/GlobalConfig/TargetAliasConfig.json"
        alias_path = self.tbgd_root / alias_relative
        alias_config = _json_object_from_path(alias_path)
        alias_dict = alias_config.get("AliasDict") if isinstance(alias_config.get("AliasDict"), dict) else {}
        expressions: list[TargetExpressionIR] = []
        for alias, raw in sorted(alias_dict.items()):
            if not isinstance(alias, str) or not isinstance(raw, dict):
                continue
            source = IRSource(
                source_path=alias_relative,
                raw_type="TargetAliasConfig.AliasDict",
                raw_id=alias,
                evidence={
                    "source_path": alias_relative,
                    "target_config_path": alias_relative,
                    "alias": alias,
                    "json_path": f"$.AliasDict.{alias}",
                },
            )
            expression = _target_expression_from_raw(
                raw,
                field_name="$self",
                expression_id=f"target_expression:global_alias:{_safe_id(alias)}",
                source=source,
            )
            if expression is not None:
                expressions.append(expression)
        return expressions

    def _lower_combatant_profiles(self) -> list[CombatantProfileIR]:
        monster_rows = self._rows_by_id("ExcelOutput/MonsterConfig.json", "MonsterID")
        template_rows = self._rows_by_id("ExcelOutput/MonsterTemplateConfig.json", "MonsterTemplateID")
        unique_monster_rows = self._rows_by_id("ExcelOutput/MonsterUniqueConfig.json", "MonsterID")
        unique_template_rows = self._rows_by_id("ExcelOutput/MonsterTemplateUniqueConfig.json", "MonsterTemplateID")
        profiles: list[CombatantProfileIR] = []
        for monster_id, monster_row in sorted(monster_rows.items()):
            template_id = str(monster_row.get("MonsterTemplateID") or "")
            template_row = template_rows.get(template_id)
            profiles.append(_combatant_profile_from_monster(monster_id, monster_row, template_id, template_row))
        for monster_id, monster_row in sorted(unique_monster_rows.items()):
            template_id = str(monster_row.get("MonsterTemplateID") or "")
            template_row = unique_template_rows.get(template_id)
            profiles.append(
                _combatant_profile_from_monster(
                    monster_id,
                    monster_row,
                    template_id,
                    template_row,
                    source_path="ExcelOutput/MonsterUniqueConfig.json",
                    raw_type="MonsterUniqueConfig",
                    template_source_path="ExcelOutput/MonsterTemplateUniqueConfig.json",
                )
            )
        for template_id, template_row in sorted(template_rows.items()):
            profiles.append(_combatant_profile_from_template(template_id, template_row))
        for template_id, template_row in sorted(unique_template_rows.items()):
            profiles.append(
                _combatant_profile_from_template(
                    template_id,
                    template_row,
                    source_path="ExcelOutput/MonsterTemplateUniqueConfig.json",
                    raw_type="MonsterTemplateUniqueConfig",
                )
            )
        return profiles

    def _lower_wave_definitions(
        self,
        entities: list[RuleEntity],
        combatant_profiles: list[CombatantProfileIR],
        monster_data_cards: tuple[MonsterDataCardIR, ...],
    ) -> list[WaveDefinitionIR]:
        relative = "ExcelOutput/StageConfig.json"
        path = self.tbgd_root / relative
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []
        rows = _limit_sequence(raw, self.limits.max_records_per_table)
        entity_by_id = {entity.entity_id: entity for entity in entities}
        profile_by_entity = {profile.entity_id: profile for profile in combatant_profiles}
        card_by_entity = {card.entity_ref: card for card in monster_data_cards}
        hard_level_profiles = self._hard_level_profiles()
        definitions: list[WaveDefinitionIR] = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            stage_id = _stage_id(row)
            if not stage_id:
                continue
            monster_list = row.get("MonsterList")
            if not isinstance(monster_list, list) or not monster_list:
                continue
            declared_wave_count = _stage_config_wave_count(row.get("StageConfigData"))
            wave_count = declared_wave_count if declared_wave_count > 0 else len(monster_list)
            level = _positive_int(row.get("Level"))
            hard_level_group = _positive_int(row.get("HardLevelGroup"))
            level_policy = _wave_level_policy(
                stage_id=stage_id,
                stage_row_index=row_index,
                level=level,
                hard_level_group=hard_level_group,
                hard_level_profile=hard_level_profiles.get((hard_level_group, level))
                if hard_level_group is not None and level is not None
                else None,
            )
            entries: list[WaveMonsterEntryIR] = []
            for wave_index, wave in enumerate(monster_list):
                if not isinstance(wave, dict):
                    continue
                for monster_key, raw_monster_id in _stage_monster_items(wave):
                    position = _stage_monster_position(monster_key)
                    monster_raw_id = _stage_monster_raw_id(raw_monster_id)
                    monster_entity_ref = f"monster:{monster_raw_id}" if monster_raw_id else ""
                    coverage_status = "executable"
                    blocked_reason = ""
                    if level_policy.get("admission_status") != "executable":
                        coverage_status = "blocked"
                        blocked_reason = str(level_policy.get("blocked_reason") or "wave_stage_level_source_blocked")
                    elif not monster_raw_id or monster_raw_id == "0":
                        coverage_status = "blocked"
                        blocked_reason = "wave_monster_entry_empty"
                    elif (
                        monster_entity_ref not in entity_by_id
                        or entity_by_id[monster_entity_ref].entity_type not in {"monster", "monster_template"}
                    ):
                        coverage_status = "blocked"
                        blocked_reason = "wave_monster_entity_missing"
                    else:
                        profile = profile_by_entity.get(monster_entity_ref)
                        card = card_by_entity.get(monster_entity_ref)
                        if profile is None or profile.coverage_status != "executable":
                            coverage_status = "blocked"
                            blocked_reason = "combatant_profile_missing_or_blocked"
                        elif card is None:
                            coverage_status = "blocked"
                            blocked_reason = "monster_data_card_missing"
                    entries.append(
                        WaveMonsterEntryIR(
                            entry_id=f"wave_entry:stage:{_safe_id(stage_id)}:w{wave_index}:p{position}:{_safe_id(monster_raw_id or 'empty')}",
                            stage_id=stage_id,
                            wave_index=wave_index,
                            position=position,
                            monster_entity_ref=monster_entity_ref,
                            monster_raw_id=monster_raw_id,
                            source=IRSource(
                                source_path=relative_source_path(self.tbgd_root, path),
                                raw_type="StageConfig.MonsterList",
                                raw_id=f"{stage_id}:{wave_index}:{monster_key}",
                                evidence={
                                    "StageID": stage_id,
                                    "stage_row_index": row_index,
                                    "StageConfigData": row.get("StageConfigData") if isinstance(row.get("StageConfigData"), list) else [],
                                    "declared_wave_count": declared_wave_count,
                                    "MonsterList_wave_index": wave_index,
                                    "MonsterList_key": monster_key,
                                    "monster_id": monster_raw_id,
                                    "level_policy": level_policy,
                                },
                            ),
                            birth_template_id=_wave_birth_template_id(stage_id, wave_index, position, monster_raw_id),
                            coverage_status=coverage_status,  # type: ignore[arg-type]
                            blocked_reason=blocked_reason,
                        )
                    )
            blocked_entries = [entry for entry in entries if entry.coverage_status != "executable"]
            definition_blocked_reason = ""
            definition_status = "executable"
            if level_policy.get("admission_status") != "executable":
                definition_status = "blocked"
                definition_blocked_reason = str(level_policy.get("blocked_reason") or "wave_stage_level_source_blocked")
            elif declared_wave_count <= 0:
                definition_status = "blocked"
                definition_blocked_reason = "stage_wave_count_missing"
            elif wave_count != len(monster_list):
                definition_status = "blocked"
                definition_blocked_reason = "stage_wave_count_monster_list_mismatch"
            elif not entries:
                definition_status = "blocked"
                definition_blocked_reason = "stage_wave_entries_missing"
            elif blocked_entries:
                definition_status = "blocked"
                definition_blocked_reason = "stage_wave_entry_blocked"
            stage_ability_refs = tuple(str(item) for item in row.get("StageAbilityConfig", ()) if str(item))
            definitions.append(
                WaveDefinitionIR(
                    wave_definition_id=f"wave_definition:stage:{_safe_id(stage_id)}",
                    stage_id=stage_id,
                    wave_count=wave_count,
                    entries=tuple(entries),
                    stage_ability_refs=stage_ability_refs,
                    source=IRSource(
                        source_path=relative_source_path(self.tbgd_root, path),
                        raw_type="StageConfig",
                        raw_id=stage_id,
                        evidence={
                            "StageID": stage_id,
                            "stage_row_index": row_index,
                            "declared_wave_count": declared_wave_count,
                            "monster_list_wave_count": len(monster_list),
                            "entry_count": len(entries),
                            "blocked_entry_count": len(blocked_entries),
                            "StageAbilityConfig": list(stage_ability_refs),
                            "Level": level,
                            "HardLevelGroup": hard_level_group,
                            "level_policy": level_policy,
                        },
                    ),
                    level=level,
                    hard_level_group=hard_level_group,
                    level_policy=level_policy,
                    coverage_status=definition_status,  # type: ignore[arg-type]
                    blocked_reason=definition_blocked_reason,
                )
            )
        return definitions

    def _hard_level_profiles(self) -> dict[tuple[int, int], dict[str, Any]]:
        relative = "ExcelOutput/HardLevelGroup.json"
        path = self.tbgd_root / relative
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, list):
            return {}
        result: dict[tuple[int, int], dict[str, Any]] = {}
        for row_index, row in enumerate(_limit_sequence(raw, self.limits.max_records_per_table)):
            if not isinstance(row, dict):
                continue
            group = _positive_int(row.get("HardLevelGroup"))
            level = _positive_int(row.get("Level"))
            if group is None or level is None:
                continue
            result[(group, level)] = {**row, "_v8_source_path": relative, "_v8_row_index": row_index}
        return result

    def _lower_break_base_damage(self) -> list[BreakBaseDamageIR]:
        relative_path = "ExcelOutput/AvatarBreakDamage.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        rows: list[BreakBaseDamageIR] = []
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict):
                continue
            level_value = row.get("Level")
            break_base = _value_field(row.get("BreakBaseDamage"))
            hardness_base = _value_field(row.get("HardnessBaseDamage"))
            coverage_status = "executable"
            blocked_reason = ""
            if not isinstance(level_value, int):
                coverage_status = "blocked"
                blocked_reason = "break_base_damage_level_missing"
                level_value = -1
            if not isinstance(break_base, (int, float)):
                coverage_status = "blocked"
                blocked_reason = "break_base_damage_value_missing"
                break_base = 0.0
            rows.append(
                BreakBaseDamageIR(
                    level=int(level_value),
                    break_base_damage=float(break_base),
                    hardness_base_damage=float(hardness_base) if isinstance(hardness_base, (int, float)) else None,
                    source=IRSource(
                        source_path=relative_path,
                        raw_type="AvatarBreakDamage",
                        raw_id=str(level_value),
                        evidence={
                            "row_index": row_index,
                            "fields": {
                                "BreakBaseDamage": _json_safe(row.get("BreakBaseDamage")),
                                "HardnessBaseDamage": _json_safe(row.get("HardnessBaseDamage")),
                            },
                        },
                    ),
                    coverage_status=coverage_status,
                    blocked_reason=blocked_reason,
                )
            )
        return rows

    def _lower_break_templates(
        self,
    ) -> tuple[
        list[BreakTemplateIR],
        list[BreakDamageEmissionIR],
        list[BreakStatusEmissionIR],
        list[EffectIR],
        list[TargetExpressionIR],
    ]:
        relative_path = "Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return [], [], [], [], []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return [], [], [], [], []
        templates = data.get("TaskListTemplate") if isinstance(data, dict) else None
        if not isinstance(templates, list):
            return [], [], [], [], []
        lowered_templates: list[BreakTemplateIR] = []
        damage_emissions: list[BreakDamageEmissionIR] = []
        status_emissions: list[BreakStatusEmissionIR] = []
        effects: list[EffectIR] = []
        target_expressions: list[TargetExpressionIR] = []
        for index, template in enumerate(templates):
            if not isinstance(template, dict):
                continue
            name = str(template.get("Name") or "")
            if not name.startswith("StanceBreak_"):
                continue
            task_list = template.get("TaskList")
            if not isinstance(task_list, list):
                task_list = []
            element = name.removeprefix("StanceBreak_") or None
            source = IRSource(
                source_path=relative_path,
                raw_type="GlobalTaskListTemplate",
                raw_id=name,
                evidence={
                    "row_index": index,
                    "task_count": len(task_list),
                    "purpose": "normal_weakness_break_lifecycle_template",
                },
            )
            lowered_templates.append(
                BreakTemplateIR(
                    template_id=f"break_template:{name}",
                    element_type=element,
                    task_names=tuple(_short_gamecore_type(task.get("$type")) for task in task_list if isinstance(task, dict)),
                    source=source,
                    coverage_status="executable",
                    blocked_reason="",
                )
            )
            for task_index, task in enumerate(task_list):
                if not isinstance(task, dict):
                    continue
                opcode = _short_gamecore_type(task.get("$type"))
                task_id = f"break_template_task:{name}:{task_index}:{opcode}"
                if opcode == "AddModifier":
                    effect_id = f"break_effect:{name}:{task_index}:{opcode}"
                    status_emission_id = f"break_status_emission:{name}:{task_index}"
                    effect_source = IRSource(
                        source_path=relative_path,
                        raw_type="GlobalBreakStatusTask",
                        raw_id=name,
                        evidence={
                            "template_id": f"break_template:{name}",
                            "break_status_emission_id": status_emission_id,
                            "task_index": task_index,
                            "task_id": task_id,
                            "opcode": opcode,
                            "task": _json_safe(task),
                        },
                    )
                    payload = _effect_payload(task, opcode, name)
                    payload, effect_target_expressions = _attach_target_expressions_to_effect_payload(
                        payload,
                        task,
                        effect_id=effect_id,
                        source=effect_source,
                    )
                    target_expressions.extend(effect_target_expressions)
                    coverage_status = _effect_coverage_status(opcode, payload)
                    blocked_reason = _effect_blocked_reason(opcode, payload, coverage_status) if coverage_status != "executable" else ""
                    standard = payload.get("standard") if isinstance(payload.get("standard"), dict) else {}
                    payload = {
                        **payload,
                        "standard": {
                            **standard,
                            "break_template_id": f"break_template:{name}",
                            "break_element_type": element,
                            "break_status_emission_id": status_emission_id,
                        },
                    }
                    effects.append(
                        EffectIR(
                            effect_id=effect_id,
                            opcode=opcode,
                            payload=payload,
                            source=effect_source,
                            coverage_status=coverage_status,
                            owner_modifier_name=name,
                        )
                    )
                    standard = payload.get("standard") if isinstance(payload.get("standard"), dict) else {}
                    status_emissions.append(
                        BreakStatusEmissionIR(
                            break_status_emission_id=status_emission_id,
                            template_id=f"break_template:{name}",
                            source_task_id=task_id,
                            effect_id=effect_id,
                            opcode=opcode,
                            target_alias=str(standard.get("target_alias") or "") or None,
                            modifier_name=str(standard.get("modifier_name") or "") or None,
                            source=effect_source,
                            coverage_status=coverage_status,
                            blocked_reason=blocked_reason,
                        )
                    )
                    continue
                if opcode != "DamageByAttackProperty":
                    continue
                attack_property = task.get("AttackProperty")
                if not isinstance(attack_property, dict):
                    continue
                formula_type = str(attack_property.get("FormulaType") or "")
                if formula_type != "ByBreakDamage":
                    continue
                scaling_expr = _numeric_expr_summary(attack_property.get("BreakDamagePercentage"))
                coverage_status = "executable" if _numeric_expr_can_be_runtime_bound(scaling_expr) else "blocked"
                damage_emissions.append(
                    BreakDamageEmissionIR(
                        break_damage_emission_id=f"break_damage_emission:{name}:{task_index}",
                        template_id=f"break_template:{name}",
                        source_task_id=task_id,
                        element_type=element,
                        damage_formula_family="break",
                        scaling_expr=scaling_expr,
                        source=IRSource(
                            source_path=relative_path,
                            raw_type="GlobalBreakDamageTask",
                            raw_id=name,
                            evidence={
                                "template_id": f"break_template:{name}",
                                "task_index": task_index,
                                "task_id": task_id,
                                "opcode": opcode,
                                "attack_property": _json_safe(attack_property),
                            },
                        ),
                        coverage_status=coverage_status,
                        blocked_reason="" if coverage_status == "executable" else _break_damage_blocked_reason(scaling_expr),
                    )
                )
        return lowered_templates, damage_emissions, status_emissions, effects, target_expressions

    def _lower_super_break_emissions(self) -> list[SuperBreakEmissionIR]:
        relative_path = "Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        templates = data.get("TaskListTemplate") if isinstance(data, dict) else None
        if not isinstance(templates, list):
            return []
        emissions: list[SuperBreakEmissionIR] = []
        admitted_templates = {"DealSuperBreakDamage", "BeingDealSuperBreakDamage"}
        for template_index, template in enumerate(templates):
            if not isinstance(template, dict):
                continue
            name = str(template.get("Name") or "")
            if name not in admitted_templates:
                continue
            for task_path, task in _iter_task_tree(template.get("TaskList"), prefix="TaskList"):
                opcode = _short_gamecore_type(task.get("$type"))
                if opcode != "DamageByAttackProperty":
                    continue
                attack_property = task.get("AttackProperty")
                if not isinstance(attack_property, dict):
                    continue
                if not _is_super_break_attack_property(attack_property, template_name=name):
                    continue
                scaling_expr = _numeric_expr_summary(attack_property.get("BreakDamagePercentage"))
                coverage_status = "executable" if _numeric_expr_can_be_runtime_bound(scaling_expr) else "blocked"
                blocked_reason = "" if coverage_status == "executable" else _super_break_blocked_reason(scaling_expr)
                source = IRSource(
                    source_path=relative_path,
                    raw_type="GlobalSuperBreakDamageTask",
                    raw_id=name,
                    evidence={
                        "template_id": f"super_break_template:{name}",
                        "template_index": template_index,
                        "task_path": task_path,
                        "opcode": opcode,
                        "attack_property": _json_safe(attack_property),
                    },
                )
                emissions.append(
                    SuperBreakEmissionIR(
                        super_break_emission_id=f"super_break_emission:{name}:{_safe_id(task_path)}",
                        template_id=f"super_break_template:{name}",
                        source_task_id=f"super_break_template_task:{name}:{_safe_id(task_path)}:{opcode}",
                        target_alias=_target_alias(task.get("TargetType")),
                        attack_type=str(attack_property.get("AttackType") or task.get("AttackType") or ""),
                        damage_formula_family="super_break",
                        element_type=_display_element_type(attack_property),
                        scaling_expr=scaling_expr,
                        source=source,
                        coverage_status=coverage_status,
                        blocked_reason=blocked_reason,
                    )
                )
        return emissions

    def _lower_queue_priorities(self) -> list[QueuePriorityIR]:
        relative_path = "Config/GlobalConfig/PriorityConfig.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        config = data.get("ConfigList") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            return []
        priorities: list[QueuePriorityIR] = []
        for table_name in ("InsertAbilityPriority", "InsertActionPriority"):
            table = config.get(table_name)
            priority_keys = table.get("PriorityKeys") if isinstance(table, dict) else None
            if not isinstance(priority_keys, dict):
                continue
            for priority_key, priority_value in sorted(priority_keys.items()):
                coverage_status = "executable" if isinstance(priority_value, (int, float)) else "blocked"
                blocked_reason = "" if coverage_status == "executable" else "queue_priority_value_not_numeric"
                priorities.append(
                    QueuePriorityIR(
                        queue_priority_id=f"queue_priority:{table_name}:{priority_key}",
                        priority_table=table_name,
                        priority_key=str(priority_key),
                        priority_value=float(priority_value) if isinstance(priority_value, (int, float)) else 0.0,
                        source=IRSource(
                            source_path=relative_path,
                            raw_type="PriorityConfig",
                            raw_id=f"{table_name}:{priority_key}",
                            evidence={
                                "table": table_name,
                                "priority_key": str(priority_key),
                                "priority_value": _json_safe(priority_value),
                                "raw_path": f"ConfigList.{table_name}.PriorityKeys.{priority_key}",
                            },
                        ),
                        coverage_status=coverage_status,
                        blocked_reason=blocked_reason,
                    )
                )
        return priorities

    def _extra_turn_source_basis(self) -> dict[str, Any]:
        basis: dict[str, Any] = {
            "source_kind": "extra_turn_source_discovery",
            "source_basis_status": "blocked",
            "blocking_dependency": "extra_turn_lifecycle_source_missing",
            "evidence": {},
        }
        enum_path = "Config/GlobalConfig/JsonEnumDefineConfig.json"
        enum_data = _read_json_file(self.tbgd_root / enum_path)
        if isinstance(enum_data, dict):
            modifier_flags = _enum_values(enum_data, "ModifierBehaviorFlag")
            modifier_states = _enum_values(enum_data, "ModifierState")
            enum_evidence: dict[str, Any] = {}
            if "OneMore" in modifier_flags:
                enum_evidence["ModifierBehaviorFlag.OneMore"] = {
                    "value": modifier_flags["OneMore"],
                    "source": IRSource(
                        source_path=enum_path,
                        raw_type="JsonEnumDefineConfig",
                        raw_id="ModifierBehaviorFlag.OneMore",
                        evidence={"enum": "ModifierBehaviorFlag", "key": "OneMore", "value": modifier_flags["OneMore"]},
                    ).to_json(),
                }
            if "OneMoreCount" in modifier_flags:
                enum_evidence["ModifierBehaviorFlag.OneMoreCount"] = {
                    "value": modifier_flags["OneMoreCount"],
                    "source": IRSource(
                        source_path=enum_path,
                        raw_type="JsonEnumDefineConfig",
                        raw_id="ModifierBehaviorFlag.OneMoreCount",
                        evidence={"enum": "ModifierBehaviorFlag", "key": "OneMoreCount", "value": modifier_flags["OneMoreCount"]},
                    ).to_json(),
                }
            if "OneMore" in modifier_states:
                enum_evidence["ModifierState.OneMore"] = {
                    "value": modifier_states["OneMore"],
                    "source": IRSource(
                        source_path=enum_path,
                        raw_type="JsonEnumDefineConfig",
                        raw_id="ModifierState.OneMore",
                        evidence={"enum": "ModifierState", "key": "OneMore", "value": modifier_states["OneMore"]},
                    ).to_json(),
                }
            if enum_evidence:
                basis["evidence"]["enum"] = enum_evidence

        const_path = "Config/GlobalConfig/GameCoreConstValue.json"
        const_data = _read_json_file(self.tbgd_root / const_path)
        custom_switches = const_data.get("CustomSwitchMap") if isinstance(const_data, dict) else None
        if isinstance(custom_switches, dict) and "InsertAbilityAfterUltraSkillEndDontTickAbility" in custom_switches:
            value = custom_switches.get("InsertAbilityAfterUltraSkillEndDontTickAbility")
            basis["evidence"]["insert_ability_after_ultra_skill_end_dont_tick_ability"] = {
                "value": _json_safe(value),
                "source": IRSource(
                    source_path=const_path,
                    raw_type="GameCoreConstValue",
                    raw_id="CustomSwitchMap.InsertAbilityAfterUltraSkillEndDontTickAbility",
                    evidence={
                        "raw_path": "CustomSwitchMap.InsertAbilityAfterUltraSkillEndDontTickAbility",
                        "value": _json_safe(value),
                    },
                ).to_json(),
            }

        modifier_path = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
        modifier_data = _read_json_file(self.tbgd_root / modifier_path)
        modifier_map = modifier_data.get("ModifierMap") if isinstance(modifier_data, dict) else None
        modifier = modifier_map.get("OneMore") if isinstance(modifier_map, dict) else None
        if isinstance(modifier, dict):
            behavior_flags = tuple(str(item) for item in modifier.get("BehaviorFlagList", ()) if isinstance(item, str))
            lifetime = modifier.get("LifeTime")
            life_step_moment = modifier.get("LifeStepMoment")
            lifecycle_admitted = (
                "OneMore" in behavior_flags
                and isinstance(lifetime, (int, float))
                and str(life_step_moment) == "ActionPhaseEnd"
            )
            source = IRSource(
                source_path=modifier_path,
                raw_type="ConfigGlobalModifier",
                raw_id="OneMore",
                evidence={
                    "modifier_name": "OneMore",
                    "raw_path": "ModifierMap.OneMore",
                    "BehaviorFlagList": list(behavior_flags),
                    "LifeTime": _json_safe(lifetime),
                    "LifeStepMoment": _json_safe(life_step_moment),
                    "Stacking": _json_safe(modifier.get("Stacking")),
                },
            )
            basis["evidence"]["one_more_modifier"] = {
                "lifecycle_admitted": lifecycle_admitted,
                "source": source.to_json(),
            }
            if lifecycle_admitted:
                basis["source_basis_status"] = "lifecycle_source_admitted"
                basis["blocking_dependency"] = ""
                basis["lifecycle_policy"] = {
                    "turn_begin_policy": "queue_extra_turn_begin_event",
                    "turn_end_policy": "queue_extra_turn_end_event",
                    "duration_tick_policy": "ActionPhaseEnd_from_OneMore_LifeStepMoment",
                    "av_policy": "queue_child_bypasses_natural_av_advance",
                    "natural_turn_policy": "extra_turn_is_non_natural_queue_turn",
                    "reentry_policy": "append_pending_no_recursive_drain",
                    "remaining_duration": int(lifetime),
                }
            else:
                basis["blocking_dependency"] = "one_more_modifier_lifecycle_not_admitted"
        return basis

    def _lower_combatant_action_sets(
        self,
        definitions: list[ActionDefinitionIR],
        *,
        entity_types: frozenset[str] | None = None,
        avatar_config_rows: list[
            tuple[str, int, dict[str, Any]]
        ] | None = None,
        servant_config_rows: list[tuple[str, int, dict[str, Any]]] | None = None,
    ) -> list[CombatantActionSetIR]:
        definitions_by_action: dict[str, list[ActionDefinitionIR]] = {}
        for definition in definitions:
            definitions_by_action.setdefault(definition.action_id, []).append(definition)
        servant_skill_rows = (
            self._servant_stat_skill_rows_by_skill_id()
            if entity_types is None or "servant" in entity_types
            else {}
        )
        rows: list[CombatantActionSetIR] = []
        for relative_path, entity_type, id_key, skill_key, config_rows in (
            (
                "ExcelOutput/AvatarConfig.json",
                "avatar",
                "AvatarID",
                "SkillList",
                (
                    avatar_config_rows
                    if avatar_config_rows is not None
                    else self._avatar_config_rows_prefer_enhanced()
                )
                if entity_types is None or "avatar" in entity_types
                else [],
            ),
            ("ExcelOutput/MonsterConfig.json", "monster", "MonsterID", "SkillList", None),
            ("ExcelOutput/MonsterUniqueConfig.json", "monster", "MonsterID", "SkillList", None),
            (
                "ExcelOutput/AvatarServantConfig.json",
                "servant",
                "ServantID",
                "SkillIDList",
                (
                    servant_config_rows
                    if servant_config_rows is not None
                    else self._servant_config_rows()
                )
                if entity_types is None or "servant" in entity_types
                else [],
            ),
        ):
            if entity_types is not None and entity_type not in entity_types:
                continue
            path = self.tbgd_root / relative_path
            if config_rows is None:
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(data, list):
                    continue
                config_rows = [
                    (relative_path, row_index, row)
                    for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table))
                ]
            for source_relative_path, row_index, row in config_rows:
                if not isinstance(row, dict) or id_key not in row:
                    continue
                raw_id = str(row[id_key])
                skills = row.get(skill_key)
                if not isinstance(skills, list):
                    skills = []
                servant_character_path = (
                    str(row.get("Config") or "")
                    if entity_type == "servant"
                    else ""
                )
                servant_character_config = (
                    self._read_json_dict(servant_character_path)
                    if servant_character_path
                    else None
                )
                skill_index_map: dict[str, JSONValue] = {}
                for index, skill_id in enumerate(skills):
                    if entity_type == "avatar":
                        action_ref = f"avatar_skill:{skill_id}"
                    elif entity_type == "servant":
                        action_ref = f"servant_skill:{skill_id}"
                    else:
                        action_ref = f"monster_skill:{skill_id}"
                    candidate_definitions = definitions_by_action.get(action_ref, ())
                    compatible_definitions = _compatible_action_definitions_for_combatant_action_set(
                        entity_type,
                        candidate_definitions,
                    )
                    levels = sorted({definition.level for definition in compatible_definitions})
                    blocked_reason = ""
                    if not levels:
                        blocked_reason = (
                            "action_definition_source_mismatch_for_monster_config_skill"
                            if entity_type == "monster" and candidate_definitions
                            else "action_definition_source_mismatch_for_servant_config_skill"
                            if entity_type == "servant" and candidate_definitions
                            else "action_definition_missing_for_skill"
                        )
                    role_source: dict[str, JSONValue] = {}
                    if entity_type == "servant" and servant_character_config is not None:
                        trigger_keys = {
                            str(
                                definition.source.evidence.get(
                                    "skill_trigger_key"
                                )
                                or ""
                            )
                            for definition in compatible_definitions
                        }
                        trigger_keys.discard("")
                        servant_skill_row = servant_skill_rows.get(str(skill_id))
                        raw_trigger_key = (
                            str(servant_skill_row.get("SkillTriggerKey") or "")
                            if servant_skill_row is not None
                            else ""
                        )
                        if raw_trigger_key:
                            trigger_keys.add(raw_trigger_key)
                        if len(trigger_keys) == 1:
                            trigger_key = next(iter(trigger_keys))
                            skill_config = _skill_config_by_name(
                                servant_character_config,
                                trigger_key,
                            )
                            if skill_config is not None:
                                role_source = {
                                    "skill_trigger_key": trigger_key,
                                    "skill_type": str(
                                        skill_config.get("SkillType") or ""
                                    ),
                                    "use_type": str(
                                        skill_config.get("UseType") or ""
                                    ),
                                    "entry_ability": str(
                                        skill_config.get("EntryAbility") or ""
                                    ),
                                    "skill_record_source_trace": (
                                        IRSource(
                                            source_path=str(
                                                servant_skill_row.get("_v8_source_path")
                                                or "ExcelOutput/AvatarServantSkillConfig.json"
                                            ),
                                            raw_type="AvatarServantSkillConfig",
                                            raw_id=f"{skill_id}:{servant_skill_row.get('Level')}",
                                            evidence={
                                                "row_index": int(
                                                    servant_skill_row.get("_v8_row_index", -1)
                                                ),
                                                "servant_ref": f"servant:{raw_id}",
                                                "skill_trigger_key": raw_trigger_key,
                                                "classification": "combatant_action_role_trigger_source",
                                            },
                                        ).to_json()
                                        if servant_skill_row is not None
                                        else {}
                                    ),
                                    "source_trace": IRSource(
                                        source_path=servant_character_path,
                                        raw_type="ServantSkillConfig",
                                        raw_id=trigger_key,
                                        evidence={
                                            "servant_ref": f"servant:{raw_id}",
                                            "skill_id": str(skill_id),
                                            "action_ref": action_ref,
                                            "classification": (
                                                "combatant_action_role_source"
                                            ),
                                        },
                                    ).to_json(),
                                }
                    servant_action_role = (
                        _servant_action_slot_role(role_source)
                        if entity_type == "servant"
                        else ""
                    )
                    skill_index_map[str(index)] = {
                        "skill_id": str(skill_id),
                        "action_ref": action_ref,
                        "levels": levels,
                        "default_level": levels[-1] if levels else None,
                        "coverage_status": "executable" if levels else "blocked",
                        "blocked_reason": blocked_reason,
                        "role_source": role_source,
                        "servant_action_role": servant_action_role,
                    }
                action_set_blocked_reason = ""
                if entity_type == "servant":
                    unclassified_slots = [
                        slot
                        for slot, item in skill_index_map.items()
                        if not isinstance(item, dict)
                        or item.get("servant_action_role") == "unknown"
                    ]
                    required_slots = [
                        slot
                        for slot, item in skill_index_map.items()
                        if isinstance(item, dict)
                        and item.get("servant_action_role") == "required_action"
                    ]
                    blocked_required_slots = [
                        slot
                        for slot in required_slots
                        if not isinstance(skill_index_map.get(slot), dict)
                        or skill_index_map[slot].get("coverage_status") != "executable"  # type: ignore[union-attr]
                    ]
                    if unclassified_slots:
                        action_set_blocked_reason = (
                            "servant_action_slots_unclassified:"
                            + ",".join(unclassified_slots)
                        )
                    elif not required_slots:
                        action_set_blocked_reason = "servant_required_action_slots_missing"
                    elif blocked_required_slots:
                        action_set_blocked_reason = (
                            "servant_required_action_slots_blocked:"
                            + ",".join(blocked_required_slots)
                        )
                    coverage_status = (
                        "blocked" if action_set_blocked_reason else "executable"
                    )
                else:
                    coverage_status = "executable" if any(
                        isinstance(item, dict) and item.get("coverage_status") == "executable"
                        for item in skill_index_map.values()
                    ) else "blocked"
                    action_set_blocked_reason = (
                        ""
                        if coverage_status == "executable"
                        else "combatant_action_set_has_no_executable_actions"
                    )
                rows.append(
                    CombatantActionSetIR(
                        combatant_action_set_id=f"combatant_action_set:{entity_type}:{raw_id}",
                        entity_ref=f"{entity_type}:{raw_id}",
                        skill_index_map=skill_index_map,
                        source=IRSource(
                            source_path=source_relative_path,
                            raw_type=Path(source_relative_path).stem,
                            raw_id=raw_id,
                            evidence={
                                "row_index": row_index,
                                "id_key": id_key,
                                "skill_list": _json_safe(skills),
                                "skill_list_field": skill_key,
                                "version_kind": str(row.get("_v8_version_kind") or "base"),
                                "base_source_path": str(row.get("_v8_base_source_path") or source_relative_path),
                                "base_skill_list": _json_safe(row.get("_v8_base_skill_list") or []),
                                "enhanced_source_path": str(row.get("_v8_enhanced_source_path") or ""),
                                "enhanced_id": _json_safe(row.get("_v8_enhanced_id")),
                                "enhanced_overrides_base": str(row.get("_v8_version_kind") or "base") == "enhanced",
                            },
                        ),
                        coverage_status=coverage_status,
                        blocked_reason=action_set_blocked_reason,
                    )
                )
        return rows

    def _servant_config_rows(self) -> list[tuple[str, int, dict[str, Any]]]:
        relative_path = "ExcelOutput/AvatarServantConfig.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        rows: list[tuple[str, int, dict[str, Any]]] = []
        for row_index, row in enumerate(
            _limit_sequence(data, self.limits.max_records_per_table)
        ):
            if not isinstance(row, dict) or row.get("ServantID") is None:
                continue
            copied = dict(row)
            copied["_v8_source_path"] = relative_path
            copied["_v8_row_index"] = row_index
            rows.append((relative_path, row_index, copied))
        return rows

    def _servant_owner_avatar_ids_from_sources(
        self,
        servant_rows: list[tuple[str, int, dict[str, Any]]],
    ) -> frozenset[str]:
        """Discover selected servant owners from raw trace/eidolon joins."""

        servant_skill_ids = {
            str(skill_id)
            for _, _, row in servant_rows
            for skill_id in row.get("SkillIDList") or ()
            if str(skill_id)
        }
        if not servant_skill_ids:
            return frozenset()
        avatar_rows = self._avatar_config_rows_prefer_enhanced()
        avatar_by_id = {
            str(row.get("AvatarID")): row
            for _, _, row in avatar_rows
            if row.get("AvatarID") is not None
        }
        owner_avatar_ids: set[str] = set()
        for relative_path in (
            "ExcelOutput/AvatarSkillTreeConfig.json",
            "ExcelOutput/AvatarSkillTreeConfigLD.json",
        ):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row in _limit_sequence(
                data,
                self.limits.max_records_per_table,
            ):
                if not isinstance(row, dict) or row.get("AvatarID") is None:
                    continue
                avatar_id = str(row["AvatarID"])
                avatar_row = avatar_by_id.get(avatar_id)
                if avatar_row is None:
                    continue
                selected_enhanced_id = avatar_row.get("_v8_enhanced_id")
                source_enhanced_id = row.get("EnhancedID")
                if (
                    selected_enhanced_id is None
                    and source_enhanced_id is not None
                ) or (
                    selected_enhanced_id is not None
                    and str(source_enhanced_id) != str(selected_enhanced_id)
                ):
                    continue
                card_skill_ids = {
                    str(skill_id)
                    for skill_id in avatar_row.get("SkillList") or ()
                }
                relation_skill_ids = servant_skill_ids.intersection(
                    str(skill_id)
                    for skill_id in row.get("LevelUpSkillID") or ()
                ).difference(card_skill_ids)
                if relation_skill_ids:
                    owner_avatar_ids.add(avatar_id)

        rank_relation_skills: dict[str, set[str]] = {}
        for relative_path in (
            "ExcelOutput/AvatarRankConfig.json",
            "ExcelOutput/AvatarRankConfigLD.json",
        ):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row in _limit_sequence(
                data,
                self.limits.max_records_per_table,
            ):
                if not isinstance(row, dict) or row.get("RankID") is None:
                    continue
                bonuses = row.get("SkillAddLevelList")
                if not isinstance(bonuses, dict):
                    continue
                matched = servant_skill_ids.intersection(
                    str(skill_id) for skill_id in bonuses
                )
                if matched:
                    rank_relation_skills.setdefault(
                        str(row["RankID"]),
                        set(),
                    ).update(matched)
        for avatar_id, avatar_row in avatar_by_id.items():
            card_skill_ids = {
                str(skill_id)
                for skill_id in avatar_row.get("SkillList") or ()
            }
            relation_skill_ids = {
                skill_id
                for rank_id in avatar_row.get("RankIDList") or ()
                for skill_id in rank_relation_skills.get(str(rank_id), ())
            }.difference(card_skill_ids)
            if relation_skill_ids:
                owner_avatar_ids.add(avatar_id)
        return frozenset(owner_avatar_ids)

    def _rows_by_id(self, relative_path: str, id_key: str) -> dict[str, dict[str, Any]]:
        path = self.tbgd_root / relative_path
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return {}
        rows: dict[str, dict[str, Any]] = {}
        for row in _limit_sequence(data, self.limits.max_records_per_table):
            if isinstance(row, dict) and id_key in row:
                rows[str(row[id_key])] = row
        return rows

    def _avatar_config_rows_prefer_enhanced(self) -> list[tuple[str, int, dict[str, Any]]]:
        base_rows: list[tuple[str, int, dict[str, Any]]] = []
        for relative_path in ("ExcelOutput/AvatarConfig.json", "ExcelOutput/AvatarConfigLD.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("AvatarID") is not None:
                    copied = dict(row)
                    copied["_v8_version_kind"] = "base"
                    copied["_v8_base_source_path"] = relative_path
                    copied["_v8_base_row_index"] = row_index
                    copied["_v8_base_skill_list"] = _json_safe(row.get("SkillList") or [])
                    base_rows.append((relative_path, row_index, copied))

        enhanced_rows: list[tuple[str, int, dict[str, Any]]] = []
        enhanced_relative = "ExcelOutput/AvatarConfigEnhanced.json"
        enhanced_path = self.tbgd_root / enhanced_relative
        if enhanced_path.exists():
            try:
                enhanced_data = json.loads(enhanced_path.read_text(encoding="utf-8"))
            except Exception:
                enhanced_data = []
            if isinstance(enhanced_data, list):
                for row_index, row in enumerate(_limit_sequence(enhanced_data, self.limits.max_records_per_table)):
                    if isinstance(row, dict) and row.get("AvatarID") is not None:
                        enhanced_rows.append((enhanced_relative, row_index, dict(row)))

        enhanced_by_avatar = {str(row["AvatarID"]): (relative_path, row_index, row) for relative_path, row_index, row in enhanced_rows}
        rows: list[tuple[str, int, dict[str, Any]]] = []
        seen: set[str] = set()
        for base_relative, base_index, base_row in base_rows:
            avatar_id = str(base_row["AvatarID"])
            enhanced = enhanced_by_avatar.get(avatar_id)
            if enhanced is None:
                rows.append((base_relative, base_index, base_row))
                seen.add(avatar_id)
                continue
            enhanced_relative_path, enhanced_index, enhanced_row = enhanced
            merged = {**base_row, **enhanced_row}
            for key in ("DamageType", "AvatarBaseType", "Rarity"):
                if not merged.get(key):
                    merged[key] = base_row.get(key)
            merged["_v8_version_kind"] = "enhanced"
            merged["_v8_base_source_path"] = base_relative
            merged["_v8_base_row_index"] = base_index
            merged["_v8_base_skill_list"] = _json_safe(base_row.get("SkillList") or [])
            merged["_v8_enhanced_source_path"] = enhanced_relative_path
            merged["_v8_enhanced_row_index"] = enhanced_index
            merged["_v8_enhanced_id"] = enhanced_row.get("EnhancedID")
            merged["_v8_enhanced_skill_list"] = _json_safe(enhanced_row.get("SkillList") or [])
            rows.append((enhanced_relative_path, enhanced_index, merged))
            seen.add(avatar_id)

        for enhanced_relative_path, enhanced_index, enhanced_row in enhanced_rows:
            avatar_id = str(enhanced_row["AvatarID"])
            if avatar_id in seen:
                continue
            copied = dict(enhanced_row)
            copied["_v8_version_kind"] = "enhanced"
            copied["_v8_enhanced_source_path"] = enhanced_relative_path
            copied["_v8_enhanced_row_index"] = enhanced_index
            copied["_v8_enhanced_id"] = enhanced_row.get("EnhancedID")
            copied["_v8_enhanced_skill_list"] = _json_safe(enhanced_row.get("SkillList") or [])
            rows.append((enhanced_relative_path, enhanced_index, copied))
        return rows

    def _lower_action_ability_bindings(
        self,
        definitions: list[ActionDefinitionIR],
        *,
        retain_lowered_details: bool = True,
    ) -> tuple[
        list[ActionAbilityBindingIR],
        list[AbilityPhaseIR],
        list[AbilityTaskIR],
        list[EffectIR],
        list[ConditionIR],
        list[FormulaIR],
        list[TargetExpressionIR],
    ]:
        has_avatar_actions = any(
            definition.action_id.startswith("avatar_skill:")
            for definition in definitions
        )
        has_monster_actions = any(
            definition.action_id.startswith("monster_skill:")
            for definition in definitions
        )
        has_servant_actions = any(
            definition.action_id.startswith("servant_skill:")
            for definition in definitions
        )
        if has_avatar_actions:
            self.build_character_ability_source_graph_catalog()
        monster_skill_rows = (
            self._monster_skill_rows_by_skill_id() if has_monster_actions else {}
        )
        monster_configs = (
            self._monster_configs_by_skill_id() if has_monster_actions else {}
        )
        servant_skill_rows = (
            self._servant_skill_rows_by_skill_id() if has_servant_actions else {}
        )
        servant_configs = (
            self._servant_configs_by_skill_id() if has_servant_actions else {}
        )
        monster_ability_file_index: dict[str, tuple[str, ...]] | None = None
        ability_file_cache: dict[str, dict[str, Any] | None] = {}
        bindings: list[ActionAbilityBindingIR] = []
        phases: list[AbilityPhaseIR] = []
        tasks: list[AbilityTaskIR] = []
        effects: list[EffectIR] = []
        conditions: list[ConditionIR] = []
        formulas: list[FormulaIR] = []
        target_expressions: list[TargetExpressionIR] = []
        for definition in definitions:
            if definition.action_id.startswith("avatar_skill:"):
                binding, binding_phases, lowered_tasks = self._avatar_action_binding(
                    definition,
                    lower_tasks=retain_lowered_details,
                )
            elif definition.action_id.startswith("monster_skill:"):
                if monster_ability_file_index is None:
                    monster_ability_file_index = self._monster_ability_file_index()
                binding, binding_phases, lowered_tasks = self._monster_action_binding(
                    definition,
                    monster_skill_rows.get(definition.source.raw_id, {}),
                    monster_configs.get(definition.source.raw_id, []),
                    monster_skill_rows,
                    ability_file_cache,
                    monster_ability_file_index,
                )
            elif definition.action_id.startswith("servant_skill:"):
                binding, binding_phases, lowered_tasks = self._servant_action_binding(
                    definition,
                    servant_skill_rows.get(definition.source.raw_id, {}),
                    servant_configs.get(definition.source.raw_id, []),
                    servant_skill_rows,
                    ability_file_cache,
                )
            else:
                binding, binding_phases, lowered_tasks = _blocked_action_binding(definition, "non_avatar_ability_binding_not_executable")
            bindings.append(binding)
            if retain_lowered_details:
                phases.extend(binding_phases)
                tasks.extend(lowered_tasks.ability_tasks)
                effects.extend(lowered_tasks.effects)
                conditions.extend(lowered_tasks.conditions)
                formulas.extend(lowered_tasks.formulas)
                target_expressions.extend(lowered_tasks.target_expressions)
        return bindings, phases, tasks, effects, conditions, formulas, target_expressions

    def _lower_standalone_ability_graphs(
        self,
        ability_files: list[Path],
    ) -> tuple[
        list[StandaloneAbilityGraphIR],
        list[AbilityPhaseIR],
        list[AbilityTaskIR],
        list[EffectIR],
        list[ConditionIR],
        list[FormulaIR],
        list[TargetExpressionIR],
    ]:
        graphs: list[StandaloneAbilityGraphIR] = []
        phases: list[AbilityPhaseIR] = []
        tasks: list[AbilityTaskIR] = []
        effects: list[EffectIR] = []
        conditions: list[ConditionIR] = []
        formulas: list[FormulaIR] = []
        target_expressions: list[TargetExpressionIR] = []
        for path in ability_files:
            relative = relative_source_path(self.tbgd_root, path)
            if not _standalone_ability_source_admitted(relative):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            ability_map = _ability_map(data)
            source_mode = _standalone_ability_source_mode(relative)
            for ability_index, (ability_name, ability) in enumerate(sorted(ability_map.items())):
                action_id = f"standalone_ability:{ability_name}"
                phase_id = f"standalone_ability_phase:{_safe_id(relative)}:{ability_index}:{_safe_id(ability_name)}"
                graph_id = f"standalone_ability_graph:{_safe_id(relative)}:{_safe_id(ability_name)}"
                definition = _StandaloneActionRef(action_id=action_id, level=0)
                lowered = self._lower_ability_phase_tasks(
                    definition=definition,  # type: ignore[arg-type]
                    phase_id=phase_id,
                    ability_name=ability_name,
                    ability=ability,
                    ability_path=relative,
                    target_alias_registry=(
                        data.get("GlobalTargetAlias")
                        if isinstance(data.get("GlobalTargetAlias"), dict)
                        else {}
                    ),
                )
                tasks.extend(lowered.ability_tasks)
                effects.extend(lowered.effects)
                conditions.extend(lowered.conditions)
                formulas.extend(lowered.formulas)
                target_expressions.extend(lowered.target_expressions)
                task_ids = tuple(task.task_id for task in lowered.ability_tasks)
                executable_task_ids = tuple(
                    task.task_id
                    for task in lowered.ability_tasks
                    if task.coverage_status == "executable" and task.effect_id
                )
                phase = AbilityPhaseIR(
                    phase_id=phase_id,
                    binding_id=graph_id,
                    action_id=action_id,
                    level=0,
                    ability_name=ability_name,
                    phase_index=0,
                    target_info=_json_safe(ability.get("TargetInfo")) if isinstance(ability.get("TargetInfo"), dict) else {},
                    opcode_summary=_ability_opcode_summary(ability),
                    callback_summaries=_ability_callback_summaries(ability),
                    source=IRSource(
                        source_path=relative,
                        raw_type="StandaloneAbilityList",
                        raw_id=ability_name,
                        evidence={
                            "ability_index": ability_index,
                            "ability_name": ability_name,
                            "source_mode": source_mode,
                            "purpose": "queue_insert_ability_resolution",
                        },
                    ),
                    coverage_status="lowered",
                    blocked_reason="",
                    task_ids=task_ids,
                )
                phases.append(phase)
                graphs.append(
                    StandaloneAbilityGraphIR(
                        standalone_ability_graph_id=graph_id,
                        ability_name=ability_name,
                        source_mode=source_mode,
                        phase_ids=(phase_id,),
                        task_ids=task_ids,
                        executable_task_ids=executable_task_ids,
                        source=phase.source,
                        coverage_status="executable" if task_ids else "blocked",
                        blocked_reason="" if task_ids else "standalone_ability_has_no_tasks",
                    )
                )
        return graphs, phases, tasks, effects, conditions, formulas, target_expressions

    def _lower_equipment_ability_graphs(
        self,
        definitions: tuple[
            LightConeDefinitionIR | RelicSetThresholdIR,
            ...,
        ],
        *,
        status_callbacks: list[StatusCallbackIR] | None = None,
    ) -> tuple[
        list[StandaloneAbilityGraphIR],
        list[AbilityPhaseIR],
        list[AbilityTaskIR],
        list[EffectIR],
        list[ConditionIR],
        list[FormulaIR],
        list[TargetExpressionIR],
        list[EquipmentAbilityParameterReadIR],
    ]:
        """Lower S3 source rows into the existing standalone graph namespace.

        Equipment graph identity is the source document plus the raw AbilityList
        row.  AbilityName remains content, never graph identity.
        """

        graphs: list[StandaloneAbilityGraphIR] = []
        phases: list[AbilityPhaseIR] = []
        tasks: list[AbilityTaskIR] = []
        effects: list[EffectIR] = []
        conditions: list[ConditionIR] = []
        formulas: list[FormulaIR] = []
        target_expressions: list[TargetExpressionIR] = []
        parameter_reads: list[EquipmentAbilityParameterReadIR] = []
        documents: dict[str, dict[str, Any]] = {}

        for definition in _admitted_equipment_ability_definitions(definitions):
            ability_source = definition.ability_source
            if ability_source is None:
                continue
            relative = ability_source.source.source_path
            document = documents.get(relative)
            if document is None:
                path = self.tbgd_root / relative
                try:
                    parsed = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(parsed, dict):
                    continue
                document = parsed
                documents[relative] = document
            ability_list = document.get("AbilityList")
            if (
                not isinstance(ability_list, list)
                or ability_source.record_index < 0
                or ability_source.record_index >= len(ability_list)
            ):
                continue
            ability = ability_list[ability_source.record_index]
            if not isinstance(ability, dict):
                continue
            ability_name = ability.get("Name") or ability.get("AbilityName")
            if ability_name != ability_source.ability_name:
                continue

            identity = f"{relative}:ability_list_row:{ability_source.record_index}"
            graph_id = f"standalone_equipment_ability_graph:{identity}"
            phase_id = f"standalone_equipment_ability_phase:{identity}"
            action_id = f"standalone_ability:{ability_name}"
            definition_ref = _StandaloneActionRef(action_id=action_id, level=0)
            lowered = self._lower_ability_phase_tasks(
                definition=definition_ref,  # type: ignore[arg-type]
                phase_id=phase_id,
                ability_name=ability_name,
                ability=ability,
                ability_path=relative,
                source_context={
                    "equipment_ability_source_admitted": True,
                    "ability_index": ability_source.record_index,
                    "ability_json_path": (
                        f"$.AbilityList[{ability_source.record_index}]"
                    ),
                    "equipment_ability_source": ability_source.source.to_json(),
                },
                target_alias_registry=(
                    document.get("GlobalTargetAlias")
                    if isinstance(document.get("GlobalTargetAlias"), dict)
                    else {}
                ),
            )
            tasks.extend(lowered.ability_tasks)
            effects.extend(lowered.effects)
            conditions.extend(lowered.conditions)
            formulas.extend(lowered.formulas)
            target_expressions.extend(lowered.target_expressions)
            task_ids = tuple(task.task_id for task in lowered.ability_tasks)
            executable_task_ids = tuple(
                task.task_id
                for task in lowered.ability_tasks
                if task.coverage_status == "executable" and task.effect_id
            )

            reads, invalid_read = _lower_equipment_parameter_reads(
                graph_ref_id=graph_id,
                ability=ability,
                ability_source=ability_source.source,
                ability_name=ability_name,
                record_index=ability_source.record_index,
                target_definition_key=definition.definition_key,
            )
            parameter_reads.extend(reads)
            row_callbacks = tuple(
                callback
                for callback in (status_callbacks or ())
                if callback.source.source_path == relative
                and callback.source.evidence.get("ability_index")
                == ability_source.record_index
                and callback.source.evidence.get("equipment_ability_source")
                == ability_source.source.to_json()
            )
            reachable_modifier_names = _equipment_reachable_modifier_names(
                document,
                ability_source.record_index,
            )
            gameplay_callbacks = tuple(
                callback
                for callback in row_callbacks
                if callback.blocked_reason
                not in {
                    "equipment_event_family_non_gameplay",
                    "equipment_modifier_definition_unreferenced",
                }
            )
            non_gameplay_callbacks = tuple(
                callback
                for callback in row_callbacks
                if callback.blocked_reason == "equipment_event_family_non_gameplay"
            )
            unadmitted_callback_ids = tuple(
                callback.callback_id
                for callback in gameplay_callbacks
                if callback.coverage_status != "executable"
                or callback.admission_status != "executable"
            )
            nested_modifier_stage = _equipment_nested_modifier_stage(
                tuple(
                    modifier_row
                    for modifier_row in self._modifier_maps(
                    document,
                    selected_ability_indices=frozenset(
                        {ability_source.record_index}
                    ),
                    )
                    if modifier_row[1] in reachable_modifier_names
                )
            )
            has_unlowered_nested_graph = nested_modifier_stage == "unknown" or (
                status_callbacks is None and nested_modifier_stage == "s8"
            )
            if invalid_read:
                graph_status = "blocked"
                graph_reason = "equipment_ability_parameter_read_invalid"
            elif has_unlowered_nested_graph:
                graph_status = "blocked"
                graph_reason = (
                    "equipment_ability_nested_modifier_graph_deferred_to_p8_s8"
                    if nested_modifier_stage == "s8"
                    else "equipment_ability_nested_modifier_graph_unclassified"
                )
            elif unadmitted_callback_ids:
                graph_status = "blocked"
                graph_reason = "equipment_ability_callback_graph_partial"
            elif not task_ids and not gameplay_callbacks:
                graph_status = "blocked"
                graph_reason = "equipment_ability_has_no_lowered_tasks"
            elif len(executable_task_ids) != len(task_ids):
                graph_status = "blocked"
                graph_reason = "equipment_ability_task_graph_partial"
            else:
                graph_status = "executable"
                graph_reason = ""

            phase = AbilityPhaseIR(
                phase_id=phase_id,
                binding_id=graph_id,
                action_id=action_id,
                level=0,
                ability_name=ability_name,
                phase_index=0,
                target_info=(
                    _json_safe(ability.get("TargetInfo"))
                    if isinstance(ability.get("TargetInfo"), dict)
                    else {}
                ),
                opcode_summary=_ability_opcode_summary(ability),
                callback_summaries=_ability_callback_summaries(ability),
                source=ability_source.source,
                coverage_status="lowered",
                blocked_reason="",
                task_ids=task_ids,
            )
            phases.append(phase)
            graphs.append(
                StandaloneAbilityGraphIR(
                    standalone_ability_graph_id=graph_id,
                    ability_name=ability_name,
                    source_mode="mainline_equipment",
                    phase_ids=(phase_id,),
                    task_ids=task_ids,
                    executable_task_ids=executable_task_ids,
                    source=ability_source.source,
                    coverage_status=graph_status,
                    blocked_reason=graph_reason,
                    status_callback_ids=tuple(
                        callback.callback_id for callback in gameplay_callbacks
                    ),
                    non_gameplay_callback_ids=tuple(
                        callback.callback_id for callback in non_gameplay_callbacks
                    ),
                )
            )
        return (
            graphs,
            phases,
            tasks,
            effects,
            conditions,
            formulas,
            target_expressions,
            parameter_reads,
        )

    def _monster_skill_rows_by_skill_id(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for relative_path in ("ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("SkillID") is not None:
                    copied = dict(row)
                    copied["_v8_source_path"] = relative_path
                    copied["_v8_row_index"] = row_index
                    rows[str(row["SkillID"])] = copied
        return rows

    def _monster_configs_by_skill_id(self) -> dict[str, list[dict[str, Any]]]:
        template_rows: dict[str, dict[str, Any]] = {}
        for relative_path in ("ExcelOutput/MonsterTemplateConfig.json", "ExcelOutput/MonsterTemplateUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("MonsterTemplateID") is not None:
                    copied = dict(row)
                    copied["_v8_source_path"] = relative_path
                    copied["_v8_row_index"] = row_index
                    template_rows[str(row["MonsterTemplateID"])] = copied

        result: dict[str, list[dict[str, Any]]] = {}
        for relative_path in ("ExcelOutput/MonsterConfig.json", "ExcelOutput/MonsterUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if not isinstance(row, dict) or row.get("MonsterID") is None:
                    continue
                template_id = str(row.get("MonsterTemplateID") or "")
                template_row = template_rows.get(template_id, {})
                config = {
                    "relative_path": relative_path,
                    "row_index": row_index,
                    "monster_id": row.get("MonsterID"),
                    "template_id": template_id,
                    "json_path": template_row.get("JsonConfig"),
                    "skill_list": row.get("SkillList") or [],
                    "template_source_path": template_row.get("_v8_source_path") or "",
                    "template_row_index": template_row.get("_v8_row_index"),
                    "override_skill_params": _json_safe(row.get("OverrideSkillParams") or []),
                    "custom_values": _json_safe(row.get("CustomValues") or {}),
                    "dynamic_values": _json_safe(row.get("DynamicValues") or {}),
                }
                for skill_id in row.get("SkillList") or []:
                    result.setdefault(str(skill_id), []).append(config)
        return result

    def _servant_skill_rows_by_skill_id(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        relative_path = "ExcelOutput/AvatarServantSkillConfig.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return rows
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return rows
        if not isinstance(data, list):
            return rows
        best_levels: dict[str, int] = {}
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or row.get("SkillID") is None:
                continue
            skill_id = str(row["SkillID"])
            level = int(_number_value(row.get("Level"), 1.0))
            if skill_id in rows and level < best_levels.get(skill_id, 0):
                continue
            copied = dict(row)
            copied["_v8_source_path"] = relative_path
            copied["_v8_row_index"] = row_index
            best_levels[skill_id] = level
            rows[skill_id] = copied
        return rows

    def _servant_configs_by_skill_id(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        relative_path = "ExcelOutput/AvatarServantConfig.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return result
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return result
        if not isinstance(data, list):
            return result
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or row.get("ServantID") is None:
                continue
            skills = row.get("SkillIDList") if isinstance(row.get("SkillIDList"), list) else []
            config = {
                "relative_path": relative_path,
                "row_index": row_index,
                "servant_id": row.get("ServantID"),
                "json_path": row.get("Config"),
                "skill_list": skills,
                "hp_skill": row.get("HPSkill"),
                "speed_skill": row.get("SpeedSkill"),
            }
            for skill_id in skills:
                result.setdefault(str(skill_id), []).append(config)
        return result

    def _servant_stat_skill_rows_by_skill_id(self) -> dict[str, dict[str, Any]]:
        cached = getattr(self, "_servant_stat_skill_rows_cache", None)
        if isinstance(cached, dict):
            return cached
        rows: dict[str, dict[str, Any]] = {}
        best_levels: dict[str, int] = {}
        for relative_path, _, id_key in (
            *CHARACTER_ACTION_DEFINITION_TABLES,
            ("ExcelOutput/AvatarServantSkillConfig.json", "servant_skill", "SkillID"),
        ):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if not isinstance(row, dict) or row.get(id_key) is None:
                    continue
                skill_id = str(row[id_key])
                level = int(_number_value(row.get("Level"), 1.0))
                if skill_id in rows and level < best_levels.get(skill_id, 0):
                    continue
                copied = dict(row)
                copied["_v8_source_path"] = relative_path
                copied["_v8_row_index"] = row_index
                best_levels[skill_id] = level
                rows[skill_id] = copied
        self._servant_stat_skill_rows_cache = rows
        return rows

    def _monster_ability_file_index(self) -> dict[str, tuple[str, ...]]:
        indexed: dict[str, list[str]] = {}
        roots = (
            self.tbgd_root / "Config/ConfigAbility/Monster",
        )
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                relative_path = relative_source_path(self.tbgd_root, path)
                for ability_name in _ability_map(data):
                    indexed.setdefault(ability_name, []).append(relative_path)
        return {name: tuple(paths) for name, paths in indexed.items()}

    def _character_relation_document(
        self,
        source_path: str,
        catalog: CharacterAbilitySourceGraphCatalogIR,
    ) -> Any:
        if type(catalog) is not CharacterAbilitySourceGraphCatalogIR:
            raise TypeError("character relation resolver requires the exact catalog type")
        expected_digest = catalog.relation_source_digests.get(source_path)
        if not isinstance(expected_digest, str):
            raise ValueError("character relation source is outside the S1 catalog")
        cache = getattr(self, "_character_relation_document_cache", None)
        if cache is None:
            cache = {}
            self._character_relation_document_cache = cache
        if source_path in cache:
            return cache[source_path]
        path = (self.tbgd_root / source_path).resolve()
        try:
            path.relative_to(self.tbgd_root)
        except ValueError as exc:
            raise ValueError("character relation source escapes TBGD root") from exc
        raw_bytes = path.read_bytes()
        if sha256(raw_bytes).hexdigest() != expected_digest:
            raise ValueError("character relation source digest changed after graph build")
        document = json.loads(raw_bytes)
        if not isinstance(document, (dict, list)):
            raise ValueError("character relation source root is invalid")
        cache[source_path] = document
        return document

    def _character_ability_definition_record(
        self,
        definition: CharacterAbilityDefinitionIR,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if type(definition) is not CharacterAbilityDefinitionIR:
            raise TypeError("ability resolver requires an exact typed definition")
        catalog = self.build_character_ability_source_graph_catalog()
        if definition.definition_kind == "presentation":
            document = self._character_relation_document(
                definition.source.source_path, catalog
            )
        else:
            snapshot = getattr(self, "_character_ability_raw_snapshot", None)
            if type(snapshot) is not CharacterAbilityRawSnapshot:
                raise TypeError("S0 snapshot is unavailable for ability resolution")
            document = snapshot.documents.get(definition.source.source_path)
            source = next(
                (
                    item
                    for item in snapshot.sources
                    if item.source_id == definition.source_id
                ),
                None,
            )
            if (
                document is None
                or source is None
                or source.source.source_path != definition.source.source_path
                or source.content_sha256
                != definition.source.evidence.get("content_sha256")
            ):
                raise ValueError("ability definition is outside the cached S0 source")
        if not isinstance(document, Mapping):
            raise ValueError("ability definition source is not an object")
        ability_list = document.get("AbilityList")
        ability_index = definition.source.evidence.get("ability_index")
        if (
            not isinstance(ability_list, list)
            or not isinstance(ability_index, int)
            or isinstance(ability_index, bool)
            or ability_index < 0
            or ability_index >= len(ability_list)
            or not isinstance(ability_list[ability_index], Mapping)
            or ability_list[ability_index].get("Name") != definition.ability_name
        ):
            raise ValueError("ability definition row identity is invalid")
        record = thaw_json(ability_list[ability_index])
        document_copy = thaw_json(document)
        if not isinstance(record, dict) or not isinstance(document_copy, dict):
            raise TypeError("ability definition thaw produced an invalid object")
        return record, document_copy

    def _avatar_action_binding(
        self,
        definition: ActionDefinitionIR,
        *,
        lower_tasks: bool = True,
    ) -> tuple[ActionAbilityBindingIR, list[AbilityPhaseIR], "_LoweredAbility"]:
        catalog = self.build_character_ability_source_graph_catalog()
        actions = tuple(
            action
            for action in catalog.action_sources
            if action.action_id == definition.action_id
        )
        query = CharacterAbilitySourceGraphQuery(catalog)
        if len(actions) != 1:
            retired = tuple(
                source
                for source in catalog.non_gameplay_skill_sources
                if f"avatar_skill:{source.skill_id}" == definition.action_id
            )
            if len(retired) == 1:
                query_result = query.query_action(
                    retired[0].owner_avatar_id,
                    definition.action_id,
                )
                return _blocked_action_binding(
                    definition,
                    query_result.blocked_reason,
                )
            return _blocked_action_binding(
                definition,
                "missing_or_ambiguous_character_action_source_graph",
            )
        action = actions[0]
        query_result = query.query_action(
            action.owner_avatar_id,
            definition.action_id,
        )
        if query_result.status != "resolved":
            return _blocked_action_binding(
                definition,
                query_result.blocked_reason or "character_action_source_graph_blocked",
            )
        level_sources = tuple(
            source
            for source in action.skill_sources
            if source.evidence.get("level") == definition.level
        )
        if len(level_sources) != 1:
            return _blocked_action_binding(
                definition, "character_action_level_source_missing_or_ambiguous"
            )
        level_source = level_sources[0]
        if (
            definition.source.source_path != level_source.source_path
            or definition.source.raw_id != action.skill_id
            or definition.source.evidence.get("row_index")
            != level_source.evidence.get("row_index")
            or definition.source.evidence.get("level") != definition.level
            or definition.skill_trigger_key != action.skill_trigger_key
        ):
            return _blocked_action_binding(
                definition, "action_definition_source_graph_mismatch"
            )

        relation_document = self._character_relation_document(
            level_source.source_path, catalog
        )
        row_index = level_source.evidence["row_index"]
        if (
            not isinstance(relation_document, list)
            or not isinstance(row_index, int)
            or isinstance(row_index, bool)
            or row_index < 0
            or row_index >= len(relation_document)
            or not isinstance(relation_document[row_index], dict)
        ):
            return _blocked_action_binding(
                definition, "character_action_level_row_invalid"
            )
        skill_row = dict(relation_document[row_index])
        if (
            str(skill_row.get("SkillID")) != action.skill_id
            or skill_row.get("SkillTriggerKey") != action.skill_trigger_key
            or int(_number_value(skill_row.get("Level"), 1.0)) != definition.level
        ):
            return _blocked_action_binding(
                definition, "character_action_level_row_mismatch"
            )
        skill_row["_v8_source_path"] = level_source.source_path
        skill_row["_v8_row_index"] = row_index

        character_path = action.config_source.source_path
        character_document = self._character_relation_document(
            character_path, catalog
        )
        if not isinstance(character_document, dict):
            return _blocked_action_binding(
                definition, "avatar_character_config_not_readable", character_path
            )
        character_config = dict(character_document)
        skill_entries = _skill_entries(character_config, action.skill_trigger_key)
        expected_skill_path = action.config_source.evidence.get("json_path")
        if len(skill_entries) != 1 or skill_entries[0][0] != expected_skill_path:
            return _blocked_action_binding(
                definition,
                "character_action_config_relation_mismatch",
                character_path,
            )
        skill_config = dict(skill_entries[0][1])

        bindings_by_id = {binding.binding_id: binding for binding in catalog.bindings}
        definitions_by_id = {
            item.definition_id: item for item in catalog.definitions
        }
        source_bindings = tuple(
            bindings_by_id[binding_id]
            for binding_id in query_result.binding_ids
        )
        binding_order = {"entry": 0, "passive": 0, "phase": 1, "presentation": 2}
        source_bindings = tuple(
            sorted(
                source_bindings,
                key=lambda item: (
                    binding_order.get(item.binding_kind, 3),
                    item.ordinal,
                    item.relation_id,
                ),
            )
        )
        gameplay_bindings = tuple(
            binding
            for binding in source_bindings
            if binding.binding_kind in {"entry", "phase", "passive"}
        )
        presentation_bindings = tuple(
            binding
            for binding in source_bindings
            if binding.binding_kind == "presentation"
        )
        if not gameplay_bindings:
            return _blocked_action_binding(
                definition, "character_action_has_no_gameplay_definition"
            )

        graph = next(
            graph
            for graph in catalog.graphs
            if action.action_source_id in graph.action_source_ids
        )
        admitted_definition_ids = set(graph.definition_ids)
        for shared_graph_id in graph.shared_graph_ids:
            admitted_definition_ids.update(
                next(
                    shared_graph.definition_ids
                    for shared_graph in catalog.graphs
                    if shared_graph.graph_id == shared_graph_id
                )
            )
        admitted_by_name: dict[str, list[CharacterAbilityDefinitionIR]] = {}
        for item in catalog.definitions:
            if item.definition_id in admitted_definition_ids:
                admitted_by_name.setdefault(item.ability_name, []).append(item)

        resolved_definitions: list[CharacterAbilityDefinitionIR] = []
        resolved_ids: set[str] = set()
        record_by_definition_id: dict[str, dict[str, Any]] = {}
        document_by_definition_id: dict[str, dict[str, Any]] = {}

        def add_gameplay_definition(item: CharacterAbilityDefinitionIR) -> None:
            if item.definition_id in resolved_ids:
                return
            record, document = self._character_ability_definition_record(item)
            resolved_ids.add(item.definition_id)
            resolved_definitions.append(item)
            record_by_definition_id[item.definition_id] = record
            document_by_definition_id[item.definition_id] = document

        for binding in gameplay_bindings:
            add_gameplay_definition(definitions_by_id[binding.ability_definition_id])

        client_only_names = list(
            dict.fromkeys(binding.ability_name for binding in presentation_bindings)
        )
        client_only_paths = [
            definitions_by_id[binding.ability_definition_id].source.source_path
            for binding in presentation_bindings
        ]
        unresolved_names: list[str] = []
        queue = list(resolved_definitions)
        queue_index = 0
        while queue_index < len(queue):
            current = queue[queue_index]
            queue_index += 1
            for child_name in _trigger_ability_names_from_value(
                record_by_definition_id[current.definition_id]
            ):
                candidates = admitted_by_name.get(child_name, ())
                selected_child = _select_trigger_ability_candidate(candidates)
                if selected_child is None:
                    if child_name not in unresolved_names:
                        unresolved_names.append(child_name)
                elif selected_child.definition_kind == "presentation":
                    if child_name not in client_only_names:
                        client_only_names.append(child_name)
                    client_only_paths.append(selected_child.source.source_path)
                elif selected_child.definition_id not in resolved_ids:
                    add_gameplay_definition(selected_child)
                    queue.append(selected_child)

        if unresolved_names:
            return _blocked_action_binding(
                definition, "source_graph_definition_resolution_blocked"
            )

        direct_names = [binding.ability_name for binding in source_bindings]
        ability_names = list(
            dict.fromkeys(
                [*direct_names, *(item.ability_name for item in resolved_definitions)]
            )
        )
        entry_ability = next(
            (
                binding.ability_name
                for binding in gameplay_bindings
                if binding.binding_kind == "entry"
            ),
            str(skill_config.get("EntryAbility") or resolved_definitions[0].ability_name),
        )
        exact_ability_map = {
            item.ability_name: record_by_definition_id[item.definition_id]
            for item in resolved_definitions
        }
        config_source = {
            "relative_path": action.config_source.evidence["inventory_source_path"],
            "row_index": action.config_source.evidence["inventory_row_index"],
            "avatar_id": action.owner_avatar_id,
            "json_path": character_path,
            "version_kind": action.config_source.evidence["selected_version"],
        }
        source_context = _ability_graph_source_context(
            source_mode="mainline_avatar",
            skill_row=skill_row,
            skill_trigger_key=action.skill_trigger_key,
            character_path=character_path,
            character_config=character_config,
            config_source=config_source,
            config_kind="avatar_config",
            ability_paths=tuple(
                dict.fromkeys(item.source.source_path for item in resolved_definitions)
            ),
            skill_rows_by_trigger_key={action.skill_trigger_key: skill_row},
            allowed_dynamic_hashes=_dynamic_hashes_for_ability_names(
                [item.ability_name for item in resolved_definitions],
                exact_ability_map,
            ),
        )
        binding_id = f"action_binding:{definition.action_id}:{definition.level}"
        binding_phases: list[AbilityPhaseIR] = []
        lowered = _LoweredAbility()
        camera_paths = tuple(
            dict.fromkeys(client_only_paths)
        )
        for phase_index, ability_definition in enumerate(resolved_definitions):
            ability_name = ability_definition.ability_name
            ability = record_by_definition_id[ability_definition.definition_id]
            ability_path = ability_definition.source.source_path
            ability_data = document_by_definition_id[ability_definition.definition_id]
            source = IRSource(
                source_path=ability_path,
                raw_type="AbilityList",
                raw_id=ability_name,
                evidence={
                    "action_id": definition.action_id,
                    "level": definition.level,
                    "phase_index": phase_index,
                    "skill_trigger_key": action.skill_trigger_key,
                    "entry_ability": entry_ability,
                    "source_graph_action_source_id": action.action_source_id,
                    "source_graph_definition_id": ability_definition.definition_id,
                    "ability_source_context": source_context,
                },
            )
            phase_id = f"ability_phase:{definition.action_id}:{definition.level}:{phase_index}:{ability_name}"
            phase_lowered = (
                self._lower_ability_phase_tasks(
                    definition=definition,
                    phase_id=phase_id,
                    ability_name=ability_name,
                    ability=ability,
                    ability_path=ability_path,
                    ability_index=(
                        ability_definition.source.evidence.get("ability_index")
                        if type(
                            ability_definition.source.evidence.get("ability_index")
                        ) is int
                        else None
                    ),
                    source_context=source_context,
                    target_alias_registry=(
                        ability_data.get("GlobalTargetAlias")
                        if isinstance(ability_data.get("GlobalTargetAlias"), dict)
                        else {}
                    ),
                )
                if lower_tasks
                else _LoweredAbility()
            )
            if lower_tasks:
                _mark_client_only_trigger_ability_tasks(
                    phase_lowered,
                    client_only_ability_names=frozenset(client_only_names),
                    client_only_ability_path=camera_paths[0] if camera_paths else "",
                )
            lowered.merge(phase_lowered)
            binding_phases.append(
                AbilityPhaseIR(
                    phase_id=phase_id,
                    binding_id=binding_id,
                    action_id=definition.action_id,
                    level=definition.level,
                    ability_name=ability_name,
                    phase_index=phase_index,
                    target_info=_json_safe(ability.get("TargetInfo")) if isinstance(ability.get("TargetInfo"), dict) else {},
                    opcode_summary=_ability_opcode_summary(ability),
                    callback_summaries=_ability_callback_summaries(ability),
                    source=source,
                    coverage_status="lowered",
                    blocked_reason="",
                    task_ids=tuple(task.task_id for task in phase_lowered.ability_tasks),
                )
            )
        blocked_reason = "" if binding_phases else "character_action_has_no_gameplay_definition"
        coverage_status = "executable" if binding_phases else "blocked"
        source = IRSource(
            source_path=character_path,
            raw_type="AvatarCharacterConfig",
            raw_id=action.skill_trigger_key,
            evidence={
                "action_id": definition.action_id,
                "level": definition.level,
                "avatar_id": action.owner_avatar_id,
                "avatar_config": _json_safe(config_source),
                "ability_files": [
                    item.source.source_path for item in resolved_definitions
                ],
                "camera_ability_files": list(camera_paths),
                "source_graph_action_source_id": action.action_source_id,
                "client_only_ability_names": client_only_names,
                "missing_ability_names": unresolved_names,
                "trigger_expanded_ability_names": ability_names,
            },
        )
        return (
            ActionAbilityBindingIR(
                binding_id=binding_id,
                action_id=definition.action_id,
                level=definition.level,
                skill_trigger_key=action.skill_trigger_key,
                skill_name=str(skill_config.get("Name") or action.skill_trigger_key),
                entry_ability=entry_ability,
                ability_names=tuple(ability_names),
                config_source={
                    "avatar_config": _json_safe(config_source),
                    "character_config_path": character_path,
                    "ability_file_paths": [
                        item.source.source_path for item in resolved_definitions
                    ],
                },
                phase_ids=tuple(phase.phase_id for phase in binding_phases),
                source_mode="mainline_avatar",
                source=source,
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
            ),
            binding_phases,
            lowered,
        )

    def _monster_action_binding(
        self,
        definition: ActionDefinitionIR,
        skill_row: dict[str, Any],
        monster_configs: list[dict[str, Any]],
        monster_skill_rows: dict[str, dict[str, Any]],
        ability_file_cache: dict[str, dict[str, Any] | None],
        ability_file_index: dict[str, tuple[str, ...]],
    ) -> tuple[ActionAbilityBindingIR, list[AbilityPhaseIR], "_LoweredAbility"]:
        skill_trigger_key = str(skill_row.get("SkillTriggerKey") or definition.source.evidence.get("skill_trigger_key") or "")
        if not skill_trigger_key:
            return _blocked_action_binding(definition, "missing_monster_skill_trigger_key")
        mainline_configs = [
            config
            for config in monster_configs
            if isinstance(config.get("json_path"), str)
            and str(config.get("json_path") or "").startswith("Config/ConfigCharacter/Monster/")
        ]
        if not mainline_configs:
            return _blocked_action_binding(definition, "missing_mainline_monster_config")
        monster_config = sorted(
            mainline_configs,
            key=lambda item: (str(item.get("json_path") or ""), str(item.get("monster_id") or "")),
        )[0]
        character_path = str(monster_config.get("json_path") or "")
        character_config = self._read_json_dict(character_path)
        if character_config is None:
            return _blocked_action_binding(definition, "monster_character_config_not_readable", character_path)
        skill_config = _skill_config_by_name(character_config, skill_trigger_key)
        if not skill_config:
            return _blocked_action_binding(definition, "monster_skill_trigger_key_not_in_character_config", character_path)
        entry_ability = str(skill_config.get("EntryAbility") or "")
        ability_names = _ability_names_for_skill(character_config, skill_trigger_key, entry_ability)
        if not entry_ability or not ability_names:
            return _blocked_action_binding(definition, "missing_monster_entry_ability_or_skill_ability_list", character_path)

        resolved_paths, missing_names, ambiguous_names = _resolve_monster_ability_paths(ability_names, ability_file_index)
        combined_ability_map: dict[str, dict[str, Any]] = {}
        for ability_path in resolved_paths.values():
            ability_data = ability_file_cache.setdefault(ability_path, self._read_json_dict(ability_path))
            if ability_data is None:
                continue
            combined_ability_map.update(_ability_map(ability_data))
        expanded_names = _expand_triggered_ability_names(ability_names, combined_ability_map)
        if tuple(expanded_names) != tuple(ability_names):
            ability_names = expanded_names
            resolved_paths, missing_names, ambiguous_names = _resolve_monster_ability_paths(ability_names, ability_file_index)

        source_context = _ability_graph_source_context(
            source_mode="mainline_monster",
            skill_row=skill_row,
            skill_trigger_key=skill_trigger_key,
            character_path=character_path,
            character_config=character_config,
            config_source=monster_config,
            config_kind="monster_config",
            ability_paths=tuple(sorted(set(resolved_paths.values()))),
            skill_rows_by_trigger_key=_skill_rows_by_trigger_key_for_config(monster_config, monster_skill_rows, skill_row),
            allowed_dynamic_hashes=_dynamic_hashes_for_ability_names(ability_names, combined_ability_map),
        )
        binding_id = f"action_binding:{definition.action_id}:{definition.level}"
        binding_phases: list[AbilityPhaseIR] = []
        lowered = _LoweredAbility()
        unreadable_paths: list[str] = []
        for phase_index, ability_name in enumerate(ability_names):
            ability_path = resolved_paths.get(ability_name, "")
            if not ability_path:
                continue
            ability_data = ability_file_cache.setdefault(ability_path, self._read_json_dict(ability_path))
            if ability_data is None:
                unreadable_paths.append(ability_path)
                continue
            ability_map = _ability_map(ability_data)
            ability = ability_map.get(ability_name)
            if not isinstance(ability, dict):
                missing_names.append(ability_name)
                continue
            source = IRSource(
                source_path=ability_path,
                raw_type="AbilityList",
                raw_id=ability_name,
                evidence={
                    "action_id": definition.action_id,
                    "level": definition.level,
                    "phase_index": phase_index,
                    "skill_trigger_key": skill_trigger_key,
                    "entry_ability": entry_ability,
                    "monster_id": _json_safe(monster_config.get("monster_id")),
                    "template_id": _json_safe(monster_config.get("template_id")),
                    "character_config_path": character_path,
                    "ability_source_context": source_context,
                },
            )
            phase_id = f"ability_phase:{definition.action_id}:{definition.level}:{phase_index}:{ability_name}"
            phase_lowered = self._lower_ability_phase_tasks(
                definition=definition,
                phase_id=phase_id,
                ability_name=ability_name,
                ability=ability,
                ability_path=ability_path,
                source_context=source_context,
                target_alias_registry=(
                    ability_data.get("GlobalTargetAlias")
                    if isinstance(ability_data.get("GlobalTargetAlias"), dict)
                    else {}
                ),
            )
            lowered.merge(phase_lowered)
            binding_phases.append(
                AbilityPhaseIR(
                    phase_id=phase_id,
                    binding_id=binding_id,
                    action_id=definition.action_id,
                    level=definition.level,
                    ability_name=ability_name,
                    phase_index=phase_index,
                    target_info=_json_safe(ability.get("TargetInfo")) if isinstance(ability.get("TargetInfo"), dict) else {},
                    opcode_summary=_ability_opcode_summary(ability),
                    callback_summaries=_ability_callback_summaries(ability),
                    source=source,
                    coverage_status="lowered",
                    blocked_reason="",
                    task_ids=tuple(task.task_id for task in phase_lowered.ability_tasks),
                )
            )
        blocking_reasons = []
        if missing_names:
            blocking_reasons.append("missing_monster_ability_name")
        if ambiguous_names:
            blocking_reasons.append("ambiguous_monster_ability_name")
        if unreadable_paths:
            blocking_reasons.append("monster_ability_file_not_readable")
        if not binding_phases:
            blocking_reasons.append("missing_monster_ability_phase_in_ability_file")
        blocked_reason = ";".join(dict.fromkeys(blocking_reasons))
        coverage_status = "blocked" if blocked_reason else "executable"
        source = IRSource(
            source_path=character_path,
            raw_type="MonsterCharacterConfig",
            raw_id=skill_trigger_key,
            evidence={
                "action_id": definition.action_id,
                "level": definition.level,
                "monster_config": _json_safe(monster_config),
                "skill_trigger_key": skill_trigger_key,
                "entry_ability": entry_ability,
                "ability_file_paths": sorted(set(resolved_paths.values())),
                "missing_ability_names": list(missing_names),
                "ambiguous_ability_names": ambiguous_names,
                "unreadable_ability_paths": unreadable_paths,
                "trigger_expanded_ability_names": ability_names,
            },
        )
        return (
            ActionAbilityBindingIR(
                binding_id=binding_id,
                action_id=definition.action_id,
                level=definition.level,
                skill_trigger_key=skill_trigger_key,
                skill_name=str(skill_config.get("Name") or skill_trigger_key),
                entry_ability=entry_ability,
                ability_names=tuple(ability_names),
                config_source={
                    "monster_config": _json_safe(monster_config),
                    "character_config_path": character_path,
                    "ability_file_paths": sorted(set(resolved_paths.values())),
                },
                phase_ids=tuple(phase.phase_id for phase in binding_phases),
                source_mode="mainline_monster",
                source=source,
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
            ),
            binding_phases,
            lowered,
        )

    def _servant_action_binding(
        self,
        definition: ActionDefinitionIR,
        skill_row: dict[str, Any],
        servant_configs: list[dict[str, Any]],
        servant_skill_rows: dict[str, dict[str, Any]],
        ability_file_cache: dict[str, dict[str, Any] | None],
    ) -> tuple[ActionAbilityBindingIR, list[AbilityPhaseIR], "_LoweredAbility"]:
        skill_trigger_key = str(skill_row.get("SkillTriggerKey") or definition.source.evidence.get("skill_trigger_key") or "")
        if not skill_trigger_key:
            return _blocked_action_binding(definition, "missing_servant_skill_trigger_key")
        mainline_configs = [
            config
            for config in servant_configs
            if isinstance(config.get("json_path"), str)
            and str(config.get("json_path") or "").startswith("Config/ConfigCharacter/Servant/")
        ]
        if not mainline_configs:
            return _blocked_action_binding(definition, "missing_mainline_servant_config")
        servant_config = sorted(
            mainline_configs,
            key=lambda item: (str(item.get("json_path") or ""), str(item.get("servant_id") or "")),
        )[0]
        character_path = str(servant_config.get("json_path") or "")
        character_config = self._read_json_dict(character_path)
        if character_config is None:
            return _blocked_action_binding(definition, "servant_character_config_not_readable", character_path)
        skill_config = _skill_config_by_name(character_config, skill_trigger_key)
        if not skill_config:
            return _blocked_action_binding(definition, "servant_skill_trigger_key_not_in_character_config", character_path)
        entry_ability = str(skill_config.get("EntryAbility") or "")
        ability_names = _ability_names_for_skill(character_config, skill_trigger_key, entry_ability)
        if not entry_ability or not ability_names:
            return _blocked_action_binding(definition, "missing_servant_entry_ability_or_skill_ability_list", character_path)
        ability_path = _servant_ability_path_from_character_path(character_path)
        ability_data = ability_file_cache.setdefault(
            ability_path,
            self._read_json_dict(ability_path),
        )
        if ability_data is None:
            return _blocked_action_binding(
                definition,
                "servant_ability_file_not_readable",
                ability_path,
            )
        ability_documents: list[tuple[str, dict[str, Any]]] = [
            (ability_path, ability_data),
        ]
        camera_ability_path = _servant_camera_ability_path_from_character_path(
            character_path
        )
        camera_ability_data = ability_file_cache.setdefault(
            camera_ability_path,
            self._read_json_dict(camera_ability_path),
        )
        if camera_ability_data is not None:
            ability_documents.append((camera_ability_path, camera_ability_data))
        ability_map: dict[str, dict[str, Any]] = {}
        ability_source_paths: dict[str, str] = {}
        ability_source_documents: dict[str, dict[str, Any]] = {}
        ambiguous_ability_names: set[str] = set()
        for source_path, document in ability_documents:
            for ability_name, ability in _ability_map(document).items():
                if ability_name in ability_map:
                    ambiguous_ability_names.add(ability_name)
                    continue
                ability_map[ability_name] = ability
                ability_source_paths[ability_name] = source_path
                ability_source_documents[ability_name] = document
        if ambiguous_ability_names:
            return _blocked_action_binding(
                definition,
                "servant_ability_name_ambiguous_across_files",
                character_path,
            )
        ability_names = _expand_triggered_ability_names(ability_names, ability_map)
        source_context = _ability_graph_source_context(
            source_mode="mainline_servant",
            skill_row=skill_row,
            skill_trigger_key=skill_trigger_key,
            character_path=character_path,
            character_config=character_config,
            config_source=servant_config,
            config_kind="servant_config",
            ability_paths=tuple(path for path, _document in ability_documents),
            skill_rows_by_trigger_key=_skill_rows_by_trigger_key_for_config(servant_config, servant_skill_rows, skill_row),
            allowed_dynamic_hashes=_dynamic_hashes_for_ability_names(ability_names, ability_map),
        )
        binding_id = f"action_binding:{definition.action_id}:{definition.level}"
        binding_phases: list[AbilityPhaseIR] = []
        lowered = _LoweredAbility()
        missing_names = [name for name in ability_names if name not in ability_map]
        for phase_index, ability_name in enumerate(ability_names):
            ability = ability_map.get(ability_name)
            if not isinstance(ability, dict):
                continue
            phase_ability_path = ability_source_paths[ability_name]
            phase_ability_document = ability_source_documents[ability_name]
            source = IRSource(
                source_path=phase_ability_path,
                raw_type="AbilityList",
                raw_id=ability_name,
                evidence={
                    "action_id": definition.action_id,
                    "level": definition.level,
                    "phase_index": phase_index,
                    "skill_trigger_key": skill_trigger_key,
                    "entry_ability": entry_ability,
                    "servant_id": _json_safe(servant_config.get("servant_id")),
                    "character_config_path": character_path,
                    "ability_source_context": source_context,
                },
            )
            phase_id = f"ability_phase:{definition.action_id}:{definition.level}:{phase_index}:{ability_name}"
            phase_lowered = self._lower_ability_phase_tasks(
                definition=definition,
                phase_id=phase_id,
                ability_name=ability_name,
                ability=ability,
                ability_path=phase_ability_path,
                source_context=source_context,
                target_alias_registry=(
                    phase_ability_document.get("GlobalTargetAlias")
                    if isinstance(
                        phase_ability_document.get("GlobalTargetAlias"),
                        dict,
                    )
                    else {}
                ),
            )
            lowered.merge(phase_lowered)
            binding_phases.append(
                AbilityPhaseIR(
                    phase_id=phase_id,
                    binding_id=binding_id,
                    action_id=definition.action_id,
                    level=definition.level,
                    ability_name=ability_name,
                    phase_index=phase_index,
                    target_info=_json_safe(ability.get("TargetInfo")) if isinstance(ability.get("TargetInfo"), dict) else {},
                    opcode_summary=_ability_opcode_summary(ability),
                    callback_summaries=_ability_callback_summaries(ability),
                    source=source,
                    coverage_status="lowered",
                    blocked_reason="",
                    task_ids=tuple(task.task_id for task in phase_lowered.ability_tasks),
                )
            )
        blocked_reason = "missing_servant_ability_phase_in_ability_file" if missing_names or not binding_phases else ""
        coverage_status = "blocked" if blocked_reason else "executable"
        source = IRSource(
            source_path=character_path,
            raw_type="ServantCharacterConfig",
            raw_id=skill_trigger_key,
            evidence={
                "action_id": definition.action_id,
                "level": definition.level,
                "servant_config": _json_safe(servant_config),
                "skill_trigger_key": skill_trigger_key,
                "entry_ability": entry_ability,
                "ability_file_path": ability_path,
                "ability_file_paths": [
                    path for path, _document in ability_documents
                ],
                "missing_ability_names": missing_names,
                "trigger_expanded_ability_names": ability_names,
            },
        )
        return (
            ActionAbilityBindingIR(
                binding_id=binding_id,
                action_id=definition.action_id,
                level=definition.level,
                skill_trigger_key=skill_trigger_key,
                skill_name=str(skill_config.get("Name") or skill_trigger_key),
                entry_ability=entry_ability,
                ability_names=tuple(ability_names),
                config_source={
                    "servant_config": _json_safe(servant_config),
                    "character_config_path": character_path,
                    "ability_file_path": ability_path,
                    "ability_file_paths": [
                        path for path, _document in ability_documents
                    ],
                },
                phase_ids=tuple(phase.phase_id for phase in binding_phases),
                source_mode="mainline_servant",
                source=source,
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
            ),
            binding_phases,
            lowered,
        )

    def _lower_ability_phase_tasks(
        self,
        *,
        definition: ActionDefinitionIR,
        phase_id: str,
        ability_name: str,
        ability: dict[str, Any],
        ability_path: str,
        ability_index: int | None = None,
        source_context: dict[str, Any] | None = None,
        target_alias_registry: dict[str, Any] | None = None,
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        for callback_kind in ABILITY_TASK_CALLBACKS:
            callback_tasks = ability.get(callback_kind)
            if not isinstance(callback_tasks, list):
                continue
            for task_index, task in enumerate(callback_tasks):
                task_lowered = self._lower_ability_task_tree(
                    task,
                    definition=definition,
                    phase_id=phase_id,
                    ability_name=ability_name,
                    ability_path=ability_path,
                    ability_index=ability_index,
                    callback_kind=callback_kind,
                    task_index=task_index,
                    task_path=f"{callback_kind}[{task_index}]",
                    branch="root",
                    parent_task_id="",
                    source_context=source_context,
                    target_alias_registry=target_alias_registry,
                )
                lowered.merge(task_lowered)
        return lowered

    def _lower_ability_task_tree(
        self,
        task: Any,
        *,
        definition: ActionDefinitionIR,
        phase_id: str,
        ability_name: str,
        ability_path: str,
        ability_index: int | None,
        callback_kind: str,
        task_index: int,
        task_path: str,
        branch: str,
        parent_task_id: str,
        source_context: dict[str, Any] | None = None,
        target_alias_registry: dict[str, Any] | None = None,
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        if not isinstance(task, dict):
            return lowered
        source_opcode = _short_gamecore_type(task.get("$type"))
        decoded_dynamic = self._decoded_dynamic_task_projection(
            ability_path=ability_path,
            ability_index=ability_index,
            task_path=task_path,
            source_opcode=source_opcode,
        )
        opcode = decoded_dynamic[0] if decoded_dynamic is not None else source_opcode
        task_id = f"ability_task:{phase_id}:{callback_kind}:{task_path}:{opcode}"
        source = IRSource(
            source_path=ability_path,
            raw_type="AbilityTask",
            raw_id=ability_name,
            evidence={
                "action_id": definition.action_id,
                "level": definition.level,
                "phase_id": phase_id,
                "callback_kind": callback_kind,
                "task_index": task_index,
                "task_path": task_path,
                "ability_index": ability_index,
                "json_path": (
                    f"$.AbilityList[{ability_index}].{task_path}"
                    if isinstance(ability_index, int)
                    else ""
                ),
                "source_opcode": source_opcode,
                "branch": branch,
                "parent_task_id": parent_task_id,
                "ability_source_context": _json_safe(source_context or {}),
            },
        )
        self_expression = _target_expression_from_raw(
            task,
            field_name="$self",
            expression_id=f"target_expression:{task_id}:self",
            source=source,
        )
        if self_expression is not None:
            lowered.target_expressions.append(self_expression)
        if opcode == "PredicateTaskList":
            condition = self._lower_ability_task_condition(
                task.get("Predicate"),
                source,
                task_id,
                target_alias_registry=target_alias_registry,
            )
            if condition:
                lowered.conditions.append(condition)
            success_ids: list[str] = []
            failed_ids: list[str] = []
            for child_index, child in enumerate(task.get("SuccessTaskList") or []):
                child_lowered = self._lower_ability_task_tree(
                    child,
                    definition=definition,
                    phase_id=phase_id,
                    ability_name=ability_name,
                    ability_path=ability_path,
                    ability_index=ability_index,
                    callback_kind=callback_kind,
                    task_index=child_index,
                    task_path=f"{task_path}.SuccessTaskList[{child_index}]",
                    branch="success",
                    parent_task_id=task_id,
                    source_context=source_context,
                    target_alias_registry=target_alias_registry,
                )
                lowered.merge(child_lowered)
                success_ids.extend(
                    item.task_id
                    for item in child_lowered.ability_tasks
                    if item.parent_task_id == task_id
                )
            for child_index, child in enumerate(task.get("FailedTaskList") or []):
                child_lowered = self._lower_ability_task_tree(
                    child,
                    definition=definition,
                    phase_id=phase_id,
                    ability_name=ability_name,
                    ability_path=ability_path,
                    ability_index=ability_index,
                    callback_kind=callback_kind,
                    task_index=child_index,
                    task_path=f"{task_path}.FailedTaskList[{child_index}]",
                    branch="failed",
                    parent_task_id=task_id,
                    source_context=source_context,
                    target_alias_registry=target_alias_registry,
                )
                lowered.merge(child_lowered)
                failed_ids.extend(
                    item.task_id
                    for item in child_lowered.ability_tasks
                    if item.parent_task_id == task_id
                )
            coverage_status, blocked_reason = _predicate_task_status(condition)
            lowered.ability_tasks.insert(
                0,
                AbilityTaskIR(
                    task_id=task_id,
                    phase_id=phase_id,
                    action_id=definition.action_id,
                    level=definition.level,
                    ability_name=ability_name,
                    callback_kind=callback_kind,
                    task_index=task_index,
                    task_path=task_path,
                    branch=branch,
                    opcode=opcode,
                    condition_id=condition.condition_id if condition else "",
                    parent_task_id=parent_task_id,
                    child_task_ids=tuple(success_ids + failed_ids),
                    success_task_ids=tuple(success_ids),
                    failed_task_ids=tuple(failed_ids),
                    source=source,
                    coverage_status=coverage_status,
                    blocked_reason=blocked_reason,
                ),
            )
            return lowered

        if opcode == "LoopExecuteTaskListWithInterval":
            repeat_expression = lower_numeric_expression(task.get("MaxLoopCount"))
            repeat_value = _fixed_expr_value(repeat_expression)
            repeat_count = (
                int(repeat_value)
                if repeat_value is not None
                and repeat_value > 0
                and repeat_value.is_integer()
                else 0
            )
            child_ids: list[str] = []
            raw_children = task.get("TaskList")
            if isinstance(raw_children, list):
                for child_index, child in enumerate(raw_children):
                    child_lowered = self._lower_ability_task_tree(
                        child,
                        definition=definition,
                        phase_id=phase_id,
                        ability_name=ability_name,
                        ability_path=ability_path,
                        ability_index=ability_index,
                        callback_kind=callback_kind,
                        task_index=child_index,
                        task_path=f"{task_path}.TaskList[{child_index}]",
                        branch="loop",
                        parent_task_id=task_id,
                        source_context=source_context,
                        target_alias_registry=target_alias_registry,
                    )
                    lowered.merge(child_lowered)
                    child_ids.extend(
                        item.task_id
                        for item in child_lowered.ability_tasks
                        if item.parent_task_id == task_id
                    )
            if repeat_count <= 0:
                blocked_reason = "fixed_positive_loop_count_required"
            elif not child_ids:
                blocked_reason = "loop_task_list_missing_or_empty"
            elif not isinstance(raw_children, list) or len(child_ids) != len(raw_children):
                blocked_reason = "loop_task_list_contains_unlowered_child"
            else:
                blocked_reason = ""
            loop_source = IRSource(
                source_path=source.source_path,
                raw_type=source.raw_type,
                raw_id=source.raw_id,
                evidence={
                    **source.evidence,
                    "repeat_count_expression": _json_safe(repeat_expression),
                    "repeat_count": repeat_count,
                    "child_task_count": len(child_ids),
                },
            )
            lowered.ability_tasks.insert(
                0,
                AbilityTaskIR(
                    task_id=task_id,
                    phase_id=phase_id,
                    action_id=definition.action_id,
                    level=definition.level,
                    ability_name=ability_name,
                    callback_kind=callback_kind,
                    task_index=task_index,
                    task_path=task_path,
                    branch=branch,
                    opcode=opcode,
                    parent_task_id=parent_task_id,
                    child_task_ids=tuple(child_ids),
                    repeat_count=repeat_count,
                    source=loop_source,
                    coverage_status="executable" if not blocked_reason else "blocked",
                    blocked_reason=blocked_reason,
                ),
            )
            return lowered

        effect_id = f"effect:{task_id}"
        payload = (
            {
                "standard": {"dynamic_operation": decoded_dynamic[1]},
                "decoded_source_ref": {
                    "decoded_id": decoded_dynamic[3],
                    "source_family": source_opcode,
                },
            }
            if decoded_dynamic is not None
            else _effect_payload(task, opcode, "")
        )
        effect_source = decoded_dynamic[2] if decoded_dynamic is not None else source
        payload, task_target_expressions = _attach_target_expressions_to_effect_payload(
            payload,
            task,
            effect_id=effect_id,
            source=source,
        )
        lowered.target_expressions.extend(task_target_expressions)
        execution_mode = ability_task_execution_mode(opcode)
        process_only_blocked_reason = (
            _process_only_ability_task_source_blocked_reason(task, opcode)
            if execution_mode == "process_only"
            else ""
        )
        if execution_mode == "process_only":
            payload["process_only_contract"] = {
                "schema_version": "ability_process_only_source_shape_v1",
                "opcode": opcode,
                "source_fields": sorted(task),
                "source_field_types": {
                    key: type(value).__name__
                    for key, value in sorted(task.items())
                },
                "source_shape_status": (
                    "blocked" if process_only_blocked_reason else "admitted"
                ),
                "blocked_reason": process_only_blocked_reason,
            }
        coverage_status = (
            "audit_only"
            if execution_mode == "process_only" and not process_only_blocked_reason
            else "blocked"
            if execution_mode == "process_only"
            else _effect_coverage_status(opcode, payload)
        )
        blocked_reason = (
            process_only_blocked_reason
            if execution_mode == "process_only"
            else ""
            if coverage_status in {"executable", "audit_only"}
            else _effect_blocked_reason(opcode, payload, coverage_status)
        )
        lowered.effects.append(
            EffectIR(
                effect_id=effect_id,
                opcode=opcode,
                payload=payload,
                source=effect_source,
                coverage_status=coverage_status,
            )
        )
        lowered.formulas.extend(self._extract_formulas(task, source, effect_id))
        lowered.formulas.extend(_damage_family_evidence(task, opcode, source, effect_id))
        lowered.ability_tasks.append(
            AbilityTaskIR(
                task_id=task_id,
                phase_id=phase_id,
                action_id=definition.action_id,
                level=definition.level,
                ability_name=ability_name,
                callback_kind=callback_kind,
                task_index=task_index,
                task_path=task_path,
                branch=branch,
                opcode=opcode,
                effect_id=effect_id,
                parent_task_id=parent_task_id,
                source=source,
                execution_mode=execution_mode,  # type: ignore[arg-type]
                coverage_status=(
                    "audit_only"
                    if execution_mode == "process_only" and not blocked_reason
                    else "blocked"
                    if execution_mode == "process_only"
                    else "executable"
                    if coverage_status == "executable"
                    else "blocked"
                ),
                blocked_reason=blocked_reason,
            )
        )
        return lowered

    def _lower_ability_task_condition(
        self,
        predicate: Any,
        source: IRSource,
        task_id: str,
        *,
        target_alias_registry: dict[str, Any] | None = None,
    ) -> ConditionIR | None:
        if not isinstance(predicate, dict):
            return None
        opcode = _short_gamecore_type(predicate.get("$type"))
        condition_source = _condition_source_from_parent(source, "Predicate")
        payload = _condition_payload_with_tbgd_defaults(
            opcode,
            _typed_condition_payload(
                _compact_payload(predicate),
                target_alias_registry,
                source=condition_source,
            ),
        )
        target_blocked_reason = _condition_payload_target_blocked_reason(payload)
        status = "blocked" if target_blocked_reason else (
            "executable" if _condition_payload_executable(opcode, payload) else classify_opcode(opcode)
        )
        return ConditionIR(
            condition_id=f"condition:{task_id}:{opcode}",
            opcode=opcode,
            payload=payload,
            source=condition_source,
            coverage_status=status,
            expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
            blocked_reason="" if status == "executable" else target_blocked_reason or f"condition_not_admitted:{opcode}",
        )

    def _read_json_dict(self, relative_path: str) -> dict[str, Any] | None:
        path = self.tbgd_root / relative_path
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _lower_entity_table(
        self,
        relative_path: str,
        spec: tuple[str, str, tuple[str, ...]],
        *,
        entity_ids: frozenset[str] | None = None,
    ) -> list[RuleEntity]:
        entity_type, id_key, field_keys = spec
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        entities: list[RuleEntity] = []
        for index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or id_key not in row:
                continue
            raw_id = _entity_raw_id(entity_type, id_key, row)
            if (
                entity_ids is not None
                and f"{entity_type}:{raw_id}" not in entity_ids
            ):
                continue
            fields = {key: _json_safe(row.get(key)) for key in field_keys if key in row}
            source = IRSource(
                source_path=relative_path,
                raw_type=Path(relative_path).stem,
                raw_id=raw_id,
                evidence={"row_index": index, "id_key": id_key},
            )
            entities.append(
                RuleEntity(
                    entity_id=f"{entity_type}:{raw_id}",
                    entity_type=entity_type,
                    fields=fields,
                    source=source,
                    coverage_status="audit_only",
                )
            )
        return entities

    def _lower_action_definitions(
        self,
        *,
        action_ids: frozenset[str] | None = None,
        entity_types: frozenset[str] | None = None,
    ) -> list[ActionDefinitionIR]:
        definitions: list[ActionDefinitionIR] = []
        monster_target_sources = (
            self._monster_skill_target_mode_sources()
            if entity_types is None or "monster_skill" in entity_types
            else {}
        )
        servant_target_sources = (
            self._servant_skill_target_sources()
            if entity_types is None or "servant_skill" in entity_types
            else {}
        )
        for relative_path, entity_type, id_key in ACTION_DEFINITION_TABLES:
            if entity_types is not None and entity_type not in entity_types:
                continue
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if not isinstance(row, dict) or id_key not in row:
                    continue
                raw_id = str(row[id_key])
                if (
                    action_ids is not None
                    and f"{entity_type}:{raw_id}" not in action_ids
                ):
                    continue
                definition = _action_definition_from_row(
                    relative_path,
                    entity_type,
                    id_key,
                    index,
                    row,
                    monster_target_source=monster_target_sources.get(raw_id)
                    if entity_type == "monster_skill"
                    else None,
                    servant_target_source=servant_target_sources.get(raw_id)
                    if entity_type == "servant_skill"
                    else None,
                )
                definitions.append(definition)
        return definitions

    def _monster_skill_target_mode_sources(self) -> dict[str, dict[str, Any]]:
        skill_rows: dict[str, dict[str, Any]] = {}
        for relative_path in ("ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("SkillID") is not None:
                    copied = dict(row)
                    copied["_v8_source_path"] = relative_path
                    copied["_v8_row_index"] = row_index
                    skill_rows[str(row["SkillID"])] = copied

        template_rows: dict[str, dict[str, Any]] = {}
        for relative_path in ("ExcelOutput/MonsterTemplateConfig.json", "ExcelOutput/MonsterTemplateUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("MonsterTemplateID") is not None:
                    copied = dict(row)
                    copied["_v8_source_path"] = relative_path
                    copied["_v8_row_index"] = row_index
                    template_rows[str(row["MonsterTemplateID"])] = copied

        result: dict[str, dict[str, Any]] = {}
        path = self.tbgd_root / "ExcelOutput/MonsterConfig.json"
        if not path.exists():
            return result
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return result
        if not isinstance(data, list):
            return result
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or row.get("MonsterID") is None:
                continue
            template_id = str(row.get("MonsterTemplateID") or "")
            template_row = template_rows.get(template_id, {})
            json_config = str(template_row.get("JsonConfig") or "")
            if not json_config:
                continue
            character_config = self._read_json_dict(json_config)
            if character_config is None:
                continue
            skill_ids = row.get("SkillList") if isinstance(row.get("SkillList"), list) else []
            for skill_id_value in skill_ids:
                skill_id = str(skill_id_value)
                skill_row = skill_rows.get(skill_id, {})
                trigger_key = str(skill_row.get("SkillTriggerKey") or "")
                if not trigger_key:
                    continue
                skill_config = _skill_config_by_name(character_config, trigger_key)
                if not skill_config:
                    continue
                target_info = skill_config.get("TargetInfo")
                target_type = str(target_info.get("TargetType") or "") if isinstance(target_info, dict) else ""
                target_mode = _monster_target_mode(target_type)
                source = {
                    "target_mode": target_mode,
                    "target_type": target_type,
                    "skill_trigger_key": trigger_key,
                    "monster_id": str(row.get("MonsterID") or ""),
                    "template_id": template_id,
                    "character_config_path": json_config,
                    "target_info": _json_safe(target_info) if isinstance(target_info, dict) else {},
                    "source_trace": {
                        "monster_config": {
                            "source_path": "ExcelOutput/MonsterConfig.json",
                            "raw_type": "MonsterConfig",
                            "raw_id": str(row.get("MonsterID") or ""),
                            "row_index": row_index,
                            "raw_path": "SkillList",
                        },
                        "template_config": {
                            "source_path": str(template_row.get("_v8_source_path") or ""),
                            "raw_type": Path(str(template_row.get("_v8_source_path") or "")).stem,
                            "raw_id": template_id,
                            "row_index": template_row.get("_v8_row_index"),
                            "raw_path": "JsonConfig",
                        },
                        "character_config": {
                            "source_path": json_config,
                            "raw_type": "MonsterCharacterConfig",
                            "raw_id": trigger_key,
                            "raw_path": "SkillList.TargetInfo",
                        },
                    },
                    "coverage_status": "blocked" if target_mode == "unknown" else "lowered",
                    "blocked_reason": "" if target_mode != "unknown" else f"unsupported_monster_target_type:{target_type}",
                    "monster_count": 1,
                }
                existing = result.get(skill_id)
                if existing is not None:
                    if existing.get("target_mode") != target_mode or existing.get("target_type") != target_type:
                        result[skill_id] = {
                            **existing,
                            "target_mode": "unknown",
                            "coverage_status": "blocked",
                            "blocked_reason": "monster_skill_target_mode_conflict",
                            "conflicting_target_source": source,
                            "monster_count": int(existing.get("monster_count") or 1) + 1,
                        }
                    else:
                        existing["monster_count"] = int(existing.get("monster_count") or 1) + 1
                else:
                    result[skill_id] = source
        return result

    def _servant_skill_target_sources(self) -> dict[str, dict[str, Any]]:
        skill_rows: dict[str, dict[str, Any]] = {}
        skill_path = self.tbgd_root / "ExcelOutput/AvatarServantSkillConfig.json"
        if skill_path.exists():
            try:
                skill_data = json.loads(skill_path.read_text(encoding="utf-8"))
            except Exception:
                skill_data = []
            if isinstance(skill_data, list):
                for row_index, row in enumerate(
                    _limit_sequence(skill_data, self.limits.max_records_per_table)
                ):
                    if not isinstance(row, dict) or row.get("SkillID") is None:
                        continue
                    skill_id = str(row["SkillID"])
                    trigger_key = str(row.get("SkillTriggerKey") or "")
                    existing = skill_rows.get(skill_id)
                    if existing is None:
                        skill_rows[skill_id] = {
                            "skill_trigger_key": trigger_key,
                            "row_index": row_index,
                        }
                    elif existing.get("skill_trigger_key") != trigger_key:
                        existing["skill_trigger_key"] = ""
                        existing["blocked_reason"] = "servant_skill_trigger_key_conflict"

        config_path = self.tbgd_root / "ExcelOutput/AvatarServantConfig.json"
        if not config_path.exists():
            return {}
        try:
            servant_data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(servant_data, list):
            return {}

        result: dict[str, dict[str, Any]] = {}
        for row_index, row in enumerate(
            _limit_sequence(servant_data, self.limits.max_records_per_table)
        ):
            if not isinstance(row, dict) or row.get("ServantID") is None:
                continue
            servant_id = str(row["ServantID"])
            character_config_path = str(row.get("Config") or "")
            character_config = self._read_json_dict(character_config_path)
            if character_config is None:
                continue
            skill_ids = row.get("SkillIDList")
            if not isinstance(skill_ids, list):
                continue
            for raw_skill_id in skill_ids:
                skill_id = str(raw_skill_id)
                skill_row = skill_rows.get(skill_id, {})
                trigger_key = str(skill_row.get("skill_trigger_key") or "")
                skill_config = _skill_config_by_name(character_config, trigger_key)
                if not trigger_key or not skill_config:
                    continue
                target_info = skill_config.get("TargetInfo")
                target_info = target_info if isinstance(target_info, dict) else {}
                target_type = str(target_info.get("TargetType") or "")
                target_relation = _target_relation_from_alias(target_type)
                source = {
                    "target_type": target_type,
                    "target_alias": target_info.get("TargetAlias"),
                    "target_info": _json_safe(target_info),
                    "skill_trigger_key": trigger_key,
                    "servant_id": servant_id,
                    "character_config_path": character_config_path,
                    "source_trace": {
                        "servant_config": {
                            "source_path": "ExcelOutput/AvatarServantConfig.json",
                            "raw_type": "AvatarServantConfig",
                            "raw_id": servant_id,
                            "row_index": row_index,
                            "raw_path": "SkillIDList/Config",
                        },
                        "servant_skill_config": {
                            "source_path": "ExcelOutput/AvatarServantSkillConfig.json",
                            "raw_type": "AvatarServantSkillConfig",
                            "raw_id": skill_id,
                            "row_index": skill_row.get("row_index"),
                            "raw_path": "SkillTriggerKey",
                        },
                        "character_config": {
                            "source_path": character_config_path,
                            "raw_type": "ServantCharacterConfig",
                            "raw_id": trigger_key,
                            "raw_path": "SkillList.TargetInfo",
                        },
                    },
                    "coverage_status": "lowered" if target_relation != "unknown" else "blocked",
                    "blocked_reason": ""
                    if target_relation != "unknown"
                    else f"unsupported_servant_target_type:{target_type}",
                }
                existing = result.get(skill_id)
                if existing is None:
                    result[skill_id] = source
                    continue
                same_source = (
                    existing.get("target_type") == source.get("target_type")
                    and existing.get("skill_trigger_key") == source.get("skill_trigger_key")
                    and existing.get("servant_id") == source.get("servant_id")
                )
                if not same_source:
                    result[skill_id] = {
                        **existing,
                        "coverage_status": "blocked",
                        "blocked_reason": "servant_skill_target_source_conflict",
                        "conflicting_target_source": source,
                    }
        return result

    def _lower_servant_damage_formula_bindings(
        self,
        definitions: list[ActionDefinitionIR],
        tasks: list[AbilityTaskIR],
        effects: list[EffectIR],
    ) -> list[SkillFormulaBindingIR]:
        definitions_by_key = {
            (definition.action_id, definition.level): definition
            for definition in definitions
            if definition.action_id.startswith("servant_skill:")
        }
        effects_by_id = {effect.effect_id: effect for effect in effects}
        source_contexts = self._servant_skill_formula_source_contexts()
        candidates: dict[tuple[str, int, int, str], list[dict[str, Any]]] = {}
        for task in sorted(
            tasks,
            key=lambda item: (
                item.action_id,
                item.level,
                item.phase_id,
                item.callback_kind,
                item.task_path,
            ),
        ):
            if task.opcode != "DamageByAttackProperty":
                continue
            definition = definitions_by_key.get((task.action_id, task.level))
            if definition is None:
                continue
            skill_id = task.action_id.split(":", 1)[1]
            contexts = source_contexts.get(skill_id, ())
            if len(contexts) != 1:
                continue
            context = contexts[0]
            if definition.skill_trigger_key != context.get("skill_trigger_key"):
                continue
            effect = effects_by_id.get(task.effect_id)
            dynamic_hash = _damage_percentage_dynamic_hash(effect)
            if dynamic_hash is None:
                continue
            dynamic_key = (definition.skill_trigger_key, dynamic_hash)
            parameter_sources = context.get("dynamic_parameters", {}).get(dynamic_key, ())
            if len(parameter_sources) != 1:
                continue
            parameter_source = parameter_sources[0]
            param_index = parameter_source.get("param_index")
            if (
                not isinstance(param_index, int)
                or isinstance(param_index, bool)
                or param_index < 0
                or param_index >= len(definition.param_list)
            ):
                continue
            param_value = definition.param_list[param_index]
            if not isinstance(_value_field(param_value), (int, float)):
                continue
            target_alias = _target_alias(effect.payload.get("TargetType")) if effect else None
            target_group_hint = _servant_damage_target_group_hint(target_alias)
            if not target_group_hint:
                continue
            key = (task.action_id, task.level, param_index, target_group_hint)
            candidates.setdefault(key, []).append(
                {
                    "task": task,
                    "effect": effect,
                    "definition": definition,
                    "context": context,
                    "parameter_source": parameter_source,
                    "dynamic_hash": dynamic_hash,
                    "target_alias": target_alias,
                    "param_value": param_value,
                }
            )

        bindings: list[SkillFormulaBindingIR] = []
        for key, grouped in sorted(candidates.items()):
            signatures = {
                (
                    str(item["context"].get("servant_id") or ""),
                    str(item["definition"].skill_trigger_key),
                    str(item["dynamic_hash"]),
                    int(item["parameter_source"]["param_index"]),
                    str(item["target_alias"] or ""),
                )
                for item in grouped
            }
            if len(signatures) != 1:
                continue
            item = grouped[0]
            task = item["task"]
            definition = item["definition"]
            context = item["context"]
            parameter_source = item["parameter_source"]
            dynamic_hash = str(item["dynamic_hash"])
            target_group_hint = key[3]
            servant_id = str(context["servant_id"])
            data_card_id = f"servant_definition:{servant_id}"
            owner_entity_ref = f"servant:{servant_id}"
            source = IRSource(
                source_path=definition.source.source_path,
                raw_type="ServantSkillFormulaBinding",
                raw_id=definition.source.raw_id,
                evidence={
                    "builder": "servant_damage_formula_binding_v1",
                    "action_definition_source": definition.source.to_json(),
                    "servant_config_source": context["servant_config_source"],
                    "character_config_path": context["character_config_path"],
                    "dynamic_parameter_source": parameter_source,
                    "damage_task_sources": [
                        candidate["task"].source.to_json() for candidate in grouped
                    ],
                    "damage_effect_sources": [
                        candidate["effect"].source.to_json()
                        for candidate in grouped
                        if candidate["effect"] is not None
                    ],
                    "basis_semantics": {
                        "task_opcode": "DamageByAttackProperty",
                        "unit_ref": "attacker",
                        "stat": "attack",
                    },
                    "param_ref": f"ParamList[{key[2]}]",
                    "target_group_hint": target_group_hint,
                    "dynamic_hash": dynamic_hash,
                },
            )
            scaling_basis_expr: dict[str, JSONValue] = {
                "kind": "unit_stat",
                "unit_ref": "attacker",
                "stat": "attack",
                "source_kind": "servant_ability_task_opcode",
                "admission_status": "executable",
                "data_card_id": data_card_id,
                "data_card_kind": "servant",
                "owner_entity_ref": owner_entity_ref,
                "param_index": key[2],
                "param_value": _json_safe(item["param_value"]),
                "dynamic_hash": dynamic_hash,
                "source_trace": source.to_json(),
            }
            bindings.append(
                SkillFormulaBindingIR(
                    binding_id=(
                        f"skill_formula_binding:{task.action_id}:{task.level}:direct_damage:"
                        f"param:{key[2]}:{target_group_hint}:servant_ability:{dynamic_hash}"
                    ),
                    character_data_card_id="",
                    formula_slot_id=(
                        f"formula_slot:{task.action_id}:{task.level}:direct_damage:"
                        f"{target_group_hint}:{key[2]}"
                    ),
                    action_id=task.action_id,
                    level=task.level,
                    param_index=key[2],
                    sequence_order=key[2],
                    formula_role="direct_damage",
                    target_group_hint=target_group_hint,
                    param_value=_json_safe(item["param_value"]),
                    scaling_basis_expr=scaling_basis_expr,
                    text_hash="",
                    skill_text="",
                    matched_text="",
                    source=source,
                    coverage_status="executable",
                    data_card_id=data_card_id,
                    data_card_kind="servant",
                    owner_entity_ref=owner_entity_ref,
                )
            )
        return bindings

    def _servant_skill_formula_source_contexts(
        self,
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        path = self.tbgd_root / "ExcelOutput/AvatarServantConfig.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, list):
            return {}
        result: dict[str, list[dict[str, Any]]] = {}
        for row_index, row in enumerate(
            _limit_sequence(data, self.limits.max_records_per_table)
        ):
            if not isinstance(row, dict) or row.get("ServantID") is None:
                continue
            servant_id = str(row["ServantID"])
            character_config_path = str(row.get("Config") or "")
            character_config = self._read_json_dict(character_config_path)
            if character_config is None:
                continue
            dynamic_parameters: dict[
                tuple[str, str], list[dict[str, Any]]
            ] = {}
            dynamic_values = character_config.get("DynamicValues")
            if isinstance(dynamic_values, dict):
                for group_name, group in dynamic_values.items():
                    if not isinstance(group, dict):
                        continue
                    for raw_hash, raw_binding in group.items():
                        read_info = (
                            raw_binding.get("ReadInfo")
                            if isinstance(raw_binding, dict)
                            else None
                        )
                        if not isinstance(read_info, dict):
                            continue
                        if read_info.get("Type") != "SkillParam":
                            continue
                        trigger_key = str(read_info.get("TriggerKey") or "")
                        param_index = read_info.get("Index")
                        if (
                            not trigger_key
                            or not isinstance(param_index, int)
                            or isinstance(param_index, bool)
                        ):
                            continue
                        dynamic_parameters.setdefault(
                            (trigger_key, str(raw_hash)),
                            [],
                        ).append(
                            {
                                "source_path": character_config_path,
                                "raw_path": (
                                    f"DynamicValues.{group_name}.{raw_hash}.ReadInfo"
                                ),
                                "dynamic_hash": str(raw_hash),
                                "trigger_key": trigger_key,
                                "param_index": param_index,
                                "read_info": _json_safe(read_info),
                            }
                        )
            skill_ids = row.get("SkillIDList")
            if not isinstance(skill_ids, list):
                continue
            servant_config_source = {
                "source_path": "ExcelOutput/AvatarServantConfig.json",
                "raw_type": "AvatarServantConfig",
                "raw_id": servant_id,
                "row_index": row_index,
                "raw_path": "SkillIDList/Config",
            }
            for raw_skill_id in skill_ids:
                skill_id = str(raw_skill_id)
                result.setdefault(skill_id, []).append(
                    {
                        "servant_id": servant_id,
                        "character_config_path": character_config_path,
                        "servant_config_source": servant_config_source,
                        "dynamic_parameters": {
                            key: tuple(values)
                            for key, values in dynamic_parameters.items()
                        },
                    }
                )
        skill_triggers: dict[str, set[str]] = {}
        skill_path = self.tbgd_root / "ExcelOutput/AvatarServantSkillConfig.json"
        if skill_path.exists():
            try:
                skill_data = json.loads(skill_path.read_text(encoding="utf-8"))
            except Exception:
                skill_data = []
            if isinstance(skill_data, list):
                for row in _limit_sequence(
                    skill_data,
                    self.limits.max_records_per_table,
                ):
                    if isinstance(row, dict) and row.get("SkillID") is not None:
                        trigger_key = str(row.get("SkillTriggerKey") or "")
                        if trigger_key:
                            skill_triggers.setdefault(str(row["SkillID"]), set()).add(
                                trigger_key
                            )
        return {
            skill_id: tuple(
                {
                    **context,
                    "skill_trigger_key": next(iter(skill_triggers[skill_id])),
                }
                for context in contexts
            )
            for skill_id, contexts in result.items()
            if len(skill_triggers.get(skill_id, ())) == 1
        }

    def _table_stats(self, relative_path: str, id_key: str) -> dict[str, Any]:
        path = self.tbgd_root / relative_path
        if not path.exists():
            return {"raw_count": 0, "lowered_count": 0, "skipped_count": 0, "missing": True}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return {"raw_count": 0, "lowered_count": 0, "skipped_count": 0, "shape": type(data).__name__}
        selected = _limit_sequence(data, self.limits.max_records_per_table)
        lowered_count = sum(1 for row in selected if isinstance(row, dict) and id_key in row)
        return {
            "raw_count": len(data),
            "lowered_count": lowered_count,
            "skipped_count": max(0, len(data) - len(selected)),
            "sampled": len(selected) < len(data),
            "id_key": id_key,
        }

    def _lower_summon_unit_definitions(self) -> list[SummonUnitDefinitionIR]:
        relative_path = "ExcelOutput/SummonUnitData.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        definitions: list[SummonUnitDefinitionIR] = []
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or row.get("ID") is None:
                continue
            summon_unit_id = str(row.get("ID"))
            config_path = str(row.get("JsonPath") or "")
            config = self._read_json_dict(config_path) if config_path else None
            config_summary = _summon_unit_config_summary(config)
            summon_kind = _summon_unit_kind(row, config_summary)
            blocked_reason = _summon_unit_blocked_reason(row, config_summary)
            raw_flags = _summon_unit_raw_flags(row)
            battle_admission = _summon_unit_battle_admission(row, config_summary, blocked_reason)
            source = IRSource(
                source_path=relative_path,
                raw_type="SummonUnitData",
                raw_id=summon_unit_id,
                evidence={
                    "row_index": row_index,
                    "config_path": config_path,
                    "config_source_exists": config is not None,
                    "config_summary": config_summary,
                    "raw_flags": raw_flags,
                    "source_mode": battle_admission["source_mode"],
                    "source_boundary": "summon_unit_definition_only_not_spawn_trigger",
                    "raw_paths": {
                        "json_path": "JsonPath",
                        "is_client": "IsClient",
                        "is_team_summon": "IsTeamSummon",
                        "destroy_on_enter_battle": "DestroyOnEnterBattle",
                        "max_summon_count": "MaxSummonCount",
                        "unique_group": "UniqueGroup",
                    },
                },
            )
            definitions.append(
                SummonUnitDefinitionIR(
                    summon_definition_id=f"summon_unit_definition:{summon_unit_id}",
                    summon_unit_id=summon_unit_id,
                    summon_kind=summon_kind,
                    config_path=config_path,
                    unique_group=str(row.get("UniqueGroup") or ""),
                    max_summon_count=_optional_int(row.get("MaxSummonCount")),
                    destroy_on_enter_battle=_optional_bool(row.get("DestroyOnEnterBattle")),
                    remove_maze_buff_on_destroy=_optional_bool(row.get("RemoveMazeBuffOnDestroy")),
                    battle_admission=battle_admission,
                    skill_config=config_summary,
                    source=source,
                    coverage_status="blocked",
                    blocked_reason=blocked_reason,
                )
            )
        return definitions

    def _ability_files(self) -> list[Path]:
        roots = [self.tbgd_root / "Config/ConfigAbility", self.tbgd_root / "Config/ConfigGlobalModifier"]
        files: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            files.extend(path for path in root.rglob("*.json") if not path.name.endswith(".layout.json"))
        return sorted(files)

    def _lower_servant_definitions(
        self,
        combatant_action_sets: list[CombatantActionSetIR],
        action_ability_bindings: list[ActionAbilityBindingIR],
        *,
        character_data_cards: list[CharacterDataCardIR],
        character_trace_nodes: list[CharacterTraceNodeIR],
        character_eidolon_slots: list[CharacterEidolonSlotIR],
        character_mechanism_slots: list[CharacterMechanismSlotIR],
        action_admissions: list[ActionAdmissionIR],
        spawn_sources_by_servant: dict[str, tuple[IRSource, ...]],
        replacement_policies: dict[str, dict[str, Any]] | None = None,
        servant_config_rows: list[tuple[str, int, dict[str, Any]]] | None = None,
    ) -> list[ServantDefinitionIR]:
        definitions: list[ServantDefinitionIR] = []
        action_set_by_entity = {item.entity_ref: item for item in combatant_action_sets}
        bindings_by_action: dict[
            tuple[str, int], list[ActionAbilityBindingIR]
        ] = {}
        for binding in action_ability_bindings:
            bindings_by_action.setdefault(
                (binding.action_id, binding.level),
                [],
            ).append(binding)
        admissions_by_action: dict[
            tuple[str, str, int], list[ActionAdmissionIR]
        ] = {}
        for admission in action_admissions:
            admissions_by_action.setdefault(
                (
                    admission.owner_entity_ref,
                    admission.action_id,
                    admission.action_level,
                ),
                [],
            ).append(admission)
        stat_skill_rows = self._servant_stat_skill_rows_by_skill_id()
        rows = (
            servant_config_rows
            if servant_config_rows is not None
            else self._servant_config_rows()
        )
        for relative_path, row_index, row in rows:
            servant_id = str(row.get("ServantID"))
            servant_ref = f"servant:{servant_id}"
            config_path = str(row.get("Config") or "")
            servant_config_data = (
                self._read_json_dict(config_path) if config_path else None
            )
            ability_path = _servant_ability_path_from_character_path(config_path) if config_path else ""
            ability_data = self._read_json_dict(ability_path) if ability_path else None
            ability_names = tuple(sorted(_ability_map(ability_data))) if isinstance(ability_data, dict) else ()
            action_set_ir = action_set_by_entity.get(servant_ref)
            action_set, binding_ids = _servant_action_set_admission(
                servant_ref,
                action_set_ir,
                bindings_by_action,
                admissions_by_action,
            )
            stat_source = _servant_stat_source(
                row,
                stat_skill_rows,
                config_path=config_path,
                servant_config_data=servant_config_data,
            )
            owner_relations = _servant_owner_relations(
                row,
                character_data_cards=character_data_cards,
                character_trace_nodes=character_trace_nodes,
                character_eidolon_slots=character_eidolon_slots,
                character_mechanism_slots=character_mechanism_slots,
            )
            owner_entity_refs = tuple(
                sorted(relation.owner_entity_ref for relation in owner_relations)
            )
            timeline_source = _servant_timeline_source(row, stat_source)
            lifecycle_source = _servant_lifecycle_source(
                row,
                replacement_policy=(replacement_policies or {}).get(servant_id),
            )
            action_set_status = str(action_set.get("admission_status") or action_set.get("coverage_status") or "")
            spawn_sources = spawn_sources_by_servant.get(servant_id, ())
            blocked_reason = _servant_definition_blocked_reason(
                owner_relations=owner_relations,
                config_path=config_path,
                ability_path=ability_path,
                ability_data=ability_data,
                action_set_status=action_set_status,
                stat_source=stat_source,
                timeline_source=timeline_source,
                lifecycle_source=lifecycle_source,
                spawn_sources=spawn_sources,
            )
            coverage_status = "blocked" if blocked_reason else "executable"
            source = IRSource(
                source_path=relative_path,
                raw_type="AvatarServantConfig",
                raw_id=servant_id,
                evidence={
                    "row_index": row_index,
                    "id_key": "ServantID",
                    "servant_ref": servant_ref,
                    "owner_entity_refs": list(owner_entity_refs),
                    "owner_relation_ids": [
                        relation.owner_relation_id for relation in owner_relations
                    ],
                    "config_path": config_path,
                    "ability_path": ability_path,
                    "ability_count": len(ability_names),
                    "ability_names": list(ability_names),
                    "skill_id_list": _json_safe(row.get("SkillIDList") or []),
                    "raw_paths": {
                        "config": "Config",
                        "skill_id_list": "SkillIDList",
                        "hp_base": "HPBase",
                        "hp_inherit": "HPInherit",
                        "hp_skill": "HPSkill",
                        "speed_base": "SpeedBase",
                        "speed_inherit": "SpeedInherit",
                        "speed_skill": "SpeedSkill",
                        "aggro": "Aggro",
                        "sync_property_except_list": (
                            f"{config_path}:$.SyncPropertyExceptList"
                            if config_path
                            else ""
                        ),
                    },
                    "unit_admission": "executable" if coverage_status == "executable" else "blocked",
                    "blocked_reason": blocked_reason,
                },
            )
            definitions.append(
                ServantDefinitionIR(
                    servant_definition_id=f"servant_definition:{servant_id}",
                    servant_ref=servant_ref,
                    representation="unit" if coverage_status == "executable" else "blocked",
                    ability_graph_ids=tuple(binding_ids),
                    action_set=action_set,
                    stat_source=stat_source,
                    timeline_source=timeline_source,
                    lifecycle_source=lifecycle_source,
                    source=source,
                    birth_template_id=_servant_birth_template_id(servant_id),
                    coverage_status=coverage_status,
                    blocked_reason=blocked_reason,
                    skill_ids=tuple(
                        str(skill_id) for skill_id in row.get("SkillIDList") or ()
                    ),
                    owner_relations=owner_relations,
                    spawn_sources=spawn_sources,
                )
            )
        return definitions

    def _lower_ability_file(
        self,
        path: Path,
        queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
        *,
        ability_file_order: int,
        selected_equipment_sources: dict[int, IRSource] | None = None,
        raw_document: Mapping[str, Any] | None = None,
    ) -> "_LoweredAbility":
        relative = relative_source_path(self.tbgd_root, path)
        if raw_document is None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return _LoweredAbility()
        elif isinstance(raw_document, Mapping):
            data = raw_document
        else:
            raise TypeError("ability lowering raw document must be a mapping")
        modifier_maps = self._modifier_maps(
            data,
            selected_ability_indices=(
                frozenset(selected_equipment_sources)
                if selected_equipment_sources is not None
                else None
            ),
        )
        equipment_reachable_modifiers = {
            ability_index: _equipment_reachable_modifier_names(data, ability_index)
            for ability_index in (selected_equipment_sources or {})
        }
        dynamic_key_hash_bindings = _document_dynamic_key_hash_bindings(
            modifier_maps
        )
        global_task_templates = _task_list_template_bindings(
            data.get("GlobalTemplates") if isinstance(data, dict) else None,
            json_path="$.GlobalTemplates",
            scope="global",
        )
        lowered = _LoweredAbility()
        callback_index = 0
        for map_name, modifier_name, modifier, modifier_context in modifier_maps:
            ability_index = modifier_context.get("ability_index")
            equipment_source = (
                selected_equipment_sources.get(ability_index)
                if selected_equipment_sources is not None
                and isinstance(ability_index, int)
                else None
            )
            source_context = {
                **{
                    key: value
                    for key, value in modifier_context.items()
                    if not str(key).startswith("_")
                },
                "equipment_ability_source_admitted": equipment_source is not None,
                "equipment_ability_source": (
                    equipment_source.to_json() if equipment_source is not None else {}
                ),
            }
            equipment_modifier_reachable = (
                equipment_source is None
                or modifier_name
                in equipment_reachable_modifiers.get(ability_index, frozenset())
            )
            if equipment_source is not None:
                source_context["equipment_modifier_reachability_status"] = (
                    "reachable"
                    if equipment_modifier_reachable
                    else "unreferenced_source_definition"
                )
            task_templates = _merge_task_list_template_bindings(
                global_task_templates,
                _task_list_template_bindings(
                    modifier.get("TaskListTemplate"),
                    json_path=f"{source_context.get('json_path')}.TaskListTemplate",
                    scope="modifier",
                ),
            )
            addition_effects, addition_target_expressions = (
                _modifier_addition_effects(
                    relative,
                    map_name,
                    modifier_name,
                    modifier,
                    source_context=source_context,
                )
            )
            lowered.effects.extend(addition_effects)
            lowered.target_expressions.extend(addition_target_expressions)
            lowered.entities.append(
                _modifier_definition_entity(
                    relative,
                    map_name,
                    modifier_name,
                    modifier,
                    source_context={
                        **source_context,
                        "_ability_dynamic_values": modifier_context.get(
                            "_ability_dynamic_values"
                        ),
                        "_ability_dynamic_values_json_path": modifier_context.get(
                            "_ability_dynamic_values_json_path"
                        ),
                    },
                    dynamic_key_hash_bindings=dynamic_key_hash_bindings,
                    addition_effect_ids=tuple(
                        effect.effect_id for effect in addition_effects
                    ),
                )
            )
            callbacks = modifier.get("_CallbackList") if isinstance(modifier, dict) else None
            if not isinstance(callbacks, list):
                callbacks = []
            for modifier_callback_index, callback in enumerate(callbacks):
                if (
                    self.limits.max_callbacks_per_file is not None
                    and callback_index >= self.limits.max_callbacks_per_file
                ):
                    return lowered
                callback_index += 1
                if not isinstance(callback, dict):
                    continue
                event = str(callback.get("Event") or "UnknownEvent")
                tasks = callback.get("CallbackConfig") or []
                if not isinstance(tasks, list):
                    continue
                callback_json_path = (
                    f"{source_context.get('json_path')}"
                    f"._CallbackList[{modifier_callback_index}]"
                )
                callback_source_context = {
                    **source_context,
                    "modifier_callback_index": modifier_callback_index,
                    "callback_json_path": callback_json_path,
                }
                trigger_effects: list[str] = []
                trigger_conditions: list[str] = []
                callback_id = f"status_callback:{relative}:{modifier_name}:{callback_index}:{event}"
                callback_lowered = self._lower_status_callback_tasks(
                    tasks,
                    relative=relative,
                    map_name=map_name,
                    modifier_name=modifier_name,
                    callback_id=callback_id,
                    event=event,
                    callback_index=callback_index,
                    task_list_json_path=f"{callback_json_path}.CallbackConfig",
                    queue_priority_lookup=queue_priority_lookup,
                    source_context=callback_source_context,
                    task_templates=task_templates,
                )
                lowered.merge(callback_lowered)
                trigger_effects.extend(
                    effect.effect_id
                    for effect in callback_lowered.effects
                )
                trigger_conditions.extend(
                    condition.condition_id
                    for condition in callback_lowered.conditions
                )
                source = IRSource(
                    source_path=relative,
                    raw_type=map_name,
                    raw_id=modifier_name,
                    evidence={
                        "callback_index": callback_index,
                        "event": event,
                        **_json_safe(callback_source_context),
                    },
                )
                callback_task_ids = tuple(
                    task.task_id
                    for task in callback_lowered.status_callback_tasks
                    if not task.parent_task_id
                )
                equipment_source_admitted = equipment_source is not None
                source_mode = _status_callback_source_mode(
                    relative,
                    equipment_source_admitted=equipment_source_admitted,
                )
                source_admitted = _status_callback_source_admitted(
                    relative,
                    equipment_source_admitted=equipment_source_admitted,
                )
                scope_kind = _status_callback_scope_kind(event)
                has_executable_queue_intent = any(
                    intent.coverage_status == "executable"
                    for intent in callback_lowered.queue_intents
                    if intent.callback_id == callback_id
                )
                has_executable_callback_task = any(
                    task.coverage_status == "executable"
                    for task in callback_lowered.status_callback_tasks
                    if task.callback_id == callback_id
                )
                foundational_events = {
                    "OnBeforeSkillUse",
                    "OnBeforeHit",
                    "OnAfterAttack",
                    "OnActionEnd",
                    "OnCreate",
                    "OnDestroy",
                    "OnEnterBattle",
                    "OnListenTurnEnd",
                    "OnBeforeInsertActionPrepare",
                    "OnInsertActionStart",
                    "OnInsertActionFinish",
                    "OnListenInsertAbilityFinish",
                    "OnCustomEvent",
                }
                equipment_event_stage = (
                    classify_equipment_callback(event, tasks)
                    if equipment_source_admitted
                    else "unknown"
                )
                if equipment_source_admitted:
                    admitted_event = (
                        equipment_modifier_reachable
                        and
                        equipment_event_stage in {"s7", "s8"}
                        and bool(callback_task_ids)
                        and all(
                            task.coverage_status == "executable"
                            or task.blocked_reason
                            == "equipment_task_family_non_gameplay"
                            for task in callback_lowered.status_callback_tasks
                            if task.callback_id == callback_id
                        )
                    )
                else:
                    admitted_event = event in {"OnStack", "OnPhase1"} or (
                        event == "OnListenTurnEnd"
                        and any(
                            task.coverage_status == "executable"
                            for task in callback_lowered.status_callback_tasks
                        )
                    ) or has_executable_queue_intent or (
                        event in {
                            "OnTriggerDeath",
                            "OnListenCharacterDie",
                            "OnTriggerDeathrattle",
                            "OnBeforeHitAll",
                            "OnAfterHitAll",
                            "OnAfterBeingAttacked",
                            "OnAfterSkillUse",
                            "OnBeforeDying",
                            "OnListenAllowAction",
                            *foundational_events,
                        }
                        and has_executable_callback_task
                    )
                status = (
                    "executable"
                    if admitted_event
                    and (
                        source_admitted
                        or (
                            not equipment_source_admitted
                            and (has_executable_queue_intent or has_executable_callback_task)
                        )
                    )
                    else "blocked"
                )
                if status == "executable":
                    blocked_reason = ""
                elif equipment_source_admitted and not equipment_modifier_reachable:
                    blocked_reason = "equipment_modifier_definition_unreferenced"
                elif equipment_source_admitted and equipment_event_stage == "s8":
                    blocked_reason = "equipment_event_family_deferred_to_p8_s8"
                elif equipment_source_admitted and equipment_event_stage == "non_gameplay":
                    blocked_reason = "equipment_event_family_non_gameplay"
                elif equipment_source_admitted and equipment_event_stage == "unknown":
                    blocked_reason = "equipment_event_family_unclassified"
                elif equipment_source_admitted and any(
                    task.coverage_status != "executable"
                    and task.blocked_reason
                    != "equipment_task_family_non_gameplay"
                    for task in callback_lowered.status_callback_tasks
                    if task.callback_id == callback_id
                ):
                    blocked_reason = "equipment_callback_contains_unadmitted_task"
                elif not source_admitted:
                    blocked_reason = "status_callback_source_mode_not_admitted"
                else:
                    blocked_reason = f"status_callback_event_not_admitted:{event}"
                blocking_dependency = "" if status == "executable" else blocked_reason
                lowered.status_callbacks.append(
                    StatusCallbackIR(
                        callback_id=callback_id,
                        modifier_name=modifier_name,
                        event=event,
                        task_ids=callback_task_ids,
                        source=source,
                        coverage_status=status,
                        blocked_reason=blocked_reason,
                        scope_kind=scope_kind,
                        source_mode=source_mode,
                        admission_status=status,
                        blocking_dependency=blocking_dependency,
                        execution_order=(ability_file_order, callback_index),
                    )
                )
                lowered.triggers.append(
                    TriggerIR(
                        trigger_id=f"trigger:{relative}:{modifier_name}:{callback_index}",
                        event=event,
                        conditions=tuple(trigger_conditions),
                        effects=tuple(trigger_effects),
                        source=source,
                        coverage_status="audit_only",
                        modifier_name=modifier_name,
                    )
                )
            watcher_lowered, callback_index = self._lower_ability_property_watchers(
                modifier.get("OnAbilityPropertyChange"),
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                ability_file_order=ability_file_order,
                callback_index=callback_index,
                queue_priority_lookup=queue_priority_lookup,
                source_context=source_context,
                task_templates=task_templates,
            )
            lowered.merge(watcher_lowered)
        return lowered

    def _lower_ability_property_watchers(
        self,
        raw_watchers: Any,
        *,
        relative: str,
        map_name: str,
        modifier_name: str,
        ability_file_order: int,
        callback_index: int,
        queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
        source_context: dict[str, Any],
        task_templates: dict[str, tuple["_TaskListTemplateBinding", ...]],
    ) -> tuple["_LoweredAbility", int]:
        lowered = _LoweredAbility()
        if raw_watchers is None:
            return lowered, callback_index
        if not isinstance(raw_watchers, list):
            source = IRSource(
                source_path=relative,
                raw_type=map_name,
                raw_id=modifier_name,
                evidence={
                    **_json_safe(source_context),
                    "json_path": f"{source_context.get('json_path')}.OnAbilityPropertyChange",
                },
            )
            lowered.ability_property_watchers.append(
                AbilityPropertyWatcherIR(
                    watcher_id=f"ability_property_watcher:{relative}:{modifier_name}:invalid",
                    modifier_name=modifier_name,
                    property_name="",
                    range_ids=(),
                    source=source,
                    blocked_reason="ability_property_watcher_list_invalid",
                )
            )
            return lowered, callback_index

        for watcher_index, raw_watcher in enumerate(raw_watchers):
            watcher_path = (
                f"{source_context.get('json_path')}"
                f".OnAbilityPropertyChange[{watcher_index}]"
            )
            watcher_id = (
                f"ability_property_watcher:{relative}:{modifier_name}:"
                f"{watcher_index}"
            )
            property_name = (
                str(raw_watcher.get("Property") or "")
                if isinstance(raw_watcher, dict)
                else ""
            )
            raw_ranges = (
                raw_watcher.get("Ranges")
                if isinstance(raw_watcher, dict)
                else None
            )
            watcher_source = IRSource(
                source_path=relative,
                raw_type=map_name,
                raw_id=modifier_name,
                evidence={
                    **_json_safe(source_context),
                    "ability_property_watcher_index": watcher_index,
                    "ability_property_watcher_json_path": watcher_path,
                    "property_name": property_name,
                },
            )
            range_ids: list[str] = []
            watcher_blocked_reason = ""
            if not ability_property_is_runtime_readable(property_name):
                watcher_blocked_reason = (
                    f"ability_property_not_runtime_readable:{property_name or 'missing'}"
                )
            elif not isinstance(raw_ranges, list) or not raw_ranges:
                watcher_blocked_reason = "ability_property_ranges_missing"
            else:
                for range_index, raw_range in enumerate(raw_ranges):
                    range_id = f"{watcher_id}:range:{range_index}"
                    range_ids.append(range_id)
                    range_path = f"{watcher_path}.Ranges[{range_index}]"
                    property_range, branch_lowered, callback_index = (
                        self._lower_ability_property_range(
                            raw_range,
                            relative=relative,
                            map_name=map_name,
                            modifier_name=modifier_name,
                            watcher_id=watcher_id,
                            range_id=range_id,
                            range_index=range_index,
                            range_path=range_path,
                            ability_file_order=ability_file_order,
                            callback_index=callback_index,
                            queue_priority_lookup=queue_priority_lookup,
                            source_context=source_context,
                            task_templates=task_templates,
                        )
                    )
                    lowered.merge(branch_lowered)
                    lowered.ability_property_ranges.append(property_range)
                    if (
                        property_range.coverage_status != "executable"
                        and not watcher_blocked_reason
                    ):
                        watcher_blocked_reason = (
                            property_range.blocked_reason
                            or "ability_property_range_not_executable"
                        )
            lowered.ability_property_watchers.append(
                AbilityPropertyWatcherIR(
                    watcher_id=watcher_id,
                    modifier_name=modifier_name,
                    property_name=property_name,
                    range_ids=tuple(range_ids),
                    source=watcher_source,
                    coverage_status=(
                        "executable" if not watcher_blocked_reason else "blocked"
                    ),
                    blocked_reason=watcher_blocked_reason,
                )
            )
        return lowered, callback_index

    def _lower_ability_property_range(
        self,
        raw_range: Any,
        *,
        relative: str,
        map_name: str,
        modifier_name: str,
        watcher_id: str,
        range_id: str,
        range_index: int,
        range_path: str,
        ability_file_order: int,
        callback_index: int,
        queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
        source_context: dict[str, Any],
        task_templates: dict[str, tuple["_TaskListTemplateBinding", ...]],
    ) -> tuple[AbilityPropertyRangeIR, "_LoweredAbility", int]:
        lowered = _LoweredAbility()
        source = IRSource(
            source_path=relative,
            raw_type=map_name,
            raw_id=modifier_name,
            evidence={
                **_json_safe(source_context),
                "ability_property_watcher_id": watcher_id,
                "ability_property_range_index": range_index,
                "ability_property_range_json_path": range_path,
            },
        )
        if not isinstance(raw_range, dict):
            return (
                AbilityPropertyRangeIR(
                    range_id=range_id,
                    watcher_id=watcher_id,
                    range_index=range_index,
                    minimum=None,
                    maximum=None,
                    minimum_inclusive=True,
                    maximum_inclusive=False,
                    enter_callback_id="",
                    exit_callback_id="",
                    source=source,
                    blocked_reason="ability_property_range_invalid",
                ),
                lowered,
                callback_index,
            )

        minimum = (
            _numeric_expr_summary(raw_range.get("Min"))
            if raw_range.get("Min") is not None
            else None
        )
        maximum = (
            _numeric_expr_summary(raw_range.get("Max"))
            if raw_range.get("Max") is not None
            else None
        )
        blocked_reason = ""
        if minimum is not None and not _numeric_expr_can_be_runtime_bound(minimum):
            blocked_reason = "ability_property_range_minimum_not_executable"
        elif maximum is not None and not _numeric_expr_can_be_runtime_bound(maximum):
            blocked_reason = "ability_property_range_maximum_not_executable"

        branch_callback_ids: dict[str, str] = {}
        for raw_key, event in (
            ("OnEnterRange", "OnAbilityPropertyRangeEnter"),
            ("OnExitRange", "OnAbilityPropertyRangeExit"),
        ):
            raw_tasks = raw_range.get(raw_key)
            if raw_tasks is None:
                continue
            if not isinstance(raw_tasks, list) or not raw_tasks:
                blocked_reason = blocked_reason or (
                    f"ability_property_range_branch_invalid:{raw_key}"
                )
                continue
            callback_index += 1
            callback_id = (
                f"status_callback:{relative}:{modifier_name}:"
                f"{callback_index}:{event}"
            )
            branch_path = f"{range_path}.{raw_key}"
            callback_source_context = {
                **source_context,
                "callback_index": callback_index,
                "callback_json_path": branch_path,
                "ability_property_watcher_id": watcher_id,
                "ability_property_range_id": range_id,
                "ability_property_range_branch": raw_key,
            }
            branch_lowered = self._lower_status_callback_tasks(
                raw_tasks,
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                callback_id=callback_id,
                event=event,
                callback_index=callback_index,
                task_list_json_path=branch_path,
                queue_priority_lookup=queue_priority_lookup,
                source_context=callback_source_context,
                task_templates=task_templates,
            )
            lowered.merge(branch_lowered)
            callback_task_ids = tuple(
                task.task_id
                for task in branch_lowered.status_callback_tasks
                if not task.parent_task_id
            )
            callback_status = (
                "executable"
                if callback_task_ids
                and all(
                    task.coverage_status == "executable"
                    for task in branch_lowered.status_callback_tasks
                )
                else "blocked"
            )
            callback_reason = (
                ""
                if callback_status == "executable"
                else "ability_property_range_branch_task_not_executable"
            )
            callback_source = IRSource(
                source_path=relative,
                raw_type=map_name,
                raw_id=modifier_name,
                evidence={
                    "callback_index": callback_index,
                    "event": event,
                    **_json_safe(callback_source_context),
                },
            )
            lowered.status_callbacks.append(
                StatusCallbackIR(
                    callback_id=callback_id,
                    modifier_name=modifier_name,
                    event=event,
                    task_ids=callback_task_ids,
                    source=callback_source,
                    execution_order=(ability_file_order, callback_index),
                    coverage_status=callback_status,
                    blocked_reason=callback_reason,
                    scope_kind="ability_property_range",
                    source_mode="mainline_equipment",
                    admission_status=callback_status,
                    blocking_dependency=callback_reason,
                )
            )
            branch_callback_ids[raw_key] = callback_id
            if callback_status != "executable" and not blocked_reason:
                blocked_reason = callback_reason

        if not branch_callback_ids:
            blocked_reason = blocked_reason or "ability_property_range_branch_missing"
        return (
            AbilityPropertyRangeIR(
                range_id=range_id,
                watcher_id=watcher_id,
                range_index=range_index,
                minimum=minimum,
                maximum=maximum,
                minimum_inclusive=bool(
                    raw_range.get("MinInclusive", True)
                ),
                maximum_inclusive=bool(
                    raw_range.get("MaxInclusive", False)
                ),
                enter_callback_id=branch_callback_ids.get("OnEnterRange", ""),
                exit_callback_id=branch_callback_ids.get("OnExitRange", ""),
                source=source,
                coverage_status=(
                    "executable" if not blocked_reason else "blocked"
                ),
                blocked_reason=blocked_reason,
            ),
            lowered,
            callback_index,
        )

    def _lower_status_callback_tasks(
        self,
        tasks: Any,
        *,
        relative: str,
        map_name: str,
        modifier_name: str,
        callback_id: str,
        event: str,
        callback_index: int,
        task_list_json_path: str,
        queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
        source_context: dict[str, Any] | None = None,
        task_templates: dict[str, tuple["_TaskListTemplateBinding", ...]] | None = None,
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        if not isinstance(tasks, list):
            return lowered
        for task_index, task in enumerate(tasks):
            task_lowered = self._lower_status_callback_task_tree(
                task,
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                callback_id=callback_id,
                event=event,
                callback_index=callback_index,
                task_index=task_index,
                task_path=f"{task_list_json_path}[{task_index}]",
                branch="root",
                parent_task_id="",
                queue_priority_lookup=queue_priority_lookup,
                source_context=source_context,
                task_templates=task_templates,
                template_stack=(),
            )
            lowered.merge(task_lowered)
        return lowered

    def _lower_status_callback_task_tree(
        self,
        task: Any,
        *,
        relative: str,
        map_name: str,
        modifier_name: str,
        callback_id: str,
        event: str,
        callback_index: int,
        task_index: int,
        task_path: str,
        branch: str,
        parent_task_id: str,
        queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
        source_context: dict[str, Any] | None = None,
        task_templates: dict[str, tuple["_TaskListTemplateBinding", ...]] | None = None,
        template_stack: tuple[str, ...] = (),
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        if not isinstance(task, dict):
            return lowered
        raw_task = task
        raw_opcode = _short_gamecore_type(raw_task.get("$type"))
        equipment_source_admitted = bool(
            (source_context or {}).get("equipment_ability_source_admitted")
        )
        opcode, task, schema_alias_evidence = _normalized_equipment_task(
            raw_opcode,
            raw_task,
            equipment_source_admitted=equipment_source_admitted,
        )
        task_id = f"status_callback_task:{relative}:{modifier_name}:{callback_index}:{task_path}:{opcode}"
        evidence: dict[str, Any] = {
            "callback_id": callback_id,
            "callback_index": callback_index,
            "event": event,
            "task_index": task_index,
            "task_path": task_path,
            "branch": branch,
            "parent_task_id": parent_task_id,
            "opcode": opcode,
            "raw_opcode": raw_opcode,
            "task": _json_safe(raw_task),
            **schema_alias_evidence,
            **_json_safe(source_context or {}),
            "json_path": task_path,
        }
        if opcode == "Retarget":
            evidence["retarget"] = _retarget_task_evidence(task)
        source = IRSource(
            source_path=relative,
            raw_type=map_name,
            raw_id=modifier_name,
            evidence=evidence,
        )
        self_expression = _target_expression_from_raw(
            task,
            field_name="$self",
            expression_id=f"target_expression:{task_id}:self",
            source=source,
        )
        if self_expression is not None:
            lowered.target_expressions.append(self_expression)
        task_target_expression_id = (
            self_expression.target_expression_id
            if self_expression is not None
            else ""
        )
        if opcode == "PredicateTaskList" or opcode in STATUS_CALLBACK_EFFECTLESS_OPCODES:
            task_target_payload, source_target_expressions = _attach_target_expressions_to_effect_payload(
                {},
                task,
                effect_id=f"task_target:{task_id}",
                source=source,
            )
            lowered.target_expressions.extend(source_target_expressions)
            target_refs = task_target_payload.get("target_expression_refs")
            target_ref = (
                target_refs.get("TargetType")
                if isinstance(target_refs, dict)
                else None
            )
            if isinstance(target_ref, dict) and isinstance(
                target_ref.get("target_expression_id"),
                str,
            ):
                task_target_expression_id = target_ref["target_expression_id"]
        if opcode == "PredicateTaskList":
            condition = self._lower_condition(task.get("Predicate"), source, task_index)
            if condition:
                lowered.conditions.append(condition)
            success_ids: list[str] = []
            failed_ids: list[str] = []
            for child_index, child in enumerate(task.get("SuccessTaskList") or []):
                child_lowered = self._lower_status_callback_task_tree(
                    child,
                    relative=relative,
                    map_name=map_name,
                    modifier_name=modifier_name,
                    callback_id=callback_id,
                    event=event,
                    callback_index=callback_index,
                    task_index=child_index,
                    task_path=f"{task_path}.SuccessTaskList[{child_index}]",
                    branch="success",
                    parent_task_id=task_id,
                    queue_priority_lookup=queue_priority_lookup,
                    source_context=source_context,
                    task_templates=task_templates,
                    template_stack=template_stack,
                )
                lowered.merge(child_lowered)
                success_ids.extend(item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id)
            for child_index, child in enumerate(task.get("FailedTaskList") or []):
                child_lowered = self._lower_status_callback_task_tree(
                    child,
                    relative=relative,
                    map_name=map_name,
                    modifier_name=modifier_name,
                    callback_id=callback_id,
                    event=event,
                    callback_index=callback_index,
                    task_index=child_index,
                    task_path=f"{task_path}.FailedTaskList[{child_index}]",
                    branch="failed",
                    parent_task_id=task_id,
                    queue_priority_lookup=queue_priority_lookup,
                    source_context=source_context,
                    task_templates=task_templates,
                    template_stack=template_stack,
                )
                lowered.merge(child_lowered)
                failed_ids.extend(item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id)
            coverage_status, blocked_reason = _predicate_task_status(condition)
            lowered.status_callback_tasks.insert(
                0,
                StatusCallbackTaskIR(
                    task_id=task_id,
                    callback_id=callback_id,
                    modifier_name=modifier_name,
                    event=event,
                    task_index=task_index,
                    task_path=task_path,
                    branch=branch,
                    opcode=opcode,
                    condition_id=condition.condition_id if condition else "",
                    target_expression_id=task_target_expression_id,
                    parent_task_id=parent_task_id,
                    child_task_ids=tuple(success_ids + failed_ids),
                    success_task_ids=tuple(success_ids),
                    failed_task_ids=tuple(failed_ids),
                    source=source,
                    coverage_status=coverage_status,
                    blocked_reason=blocked_reason,
                    task_payload=_status_callback_runtime_payload(
                        task,
                        source_modifier_name=modifier_name,
                    ),
                    retarget_policy=_retarget_task_evidence(task) if opcode == "Retarget" else {},
                )
            )
            return lowered

        retarget_condition = self._lower_condition(task.get("Predicate"), source, task_index) if opcode == "Retarget" else None
        if retarget_condition:
            lowered.conditions.append(retarget_condition)

        effect_id = (
            f"effect:{relative}:{modifier_name}:{callback_index}:"
            f"{task_path}:{opcode}"
        )
        child_task_ids: list[str] = []
        success_task_ids: list[str] = []
        failed_task_ids: list[str] = []
        template_blocked_reason = ""
        child_task_list: Any = task.get("TaskList") or []
        child_task_list_json_path = f"{task_path}.TaskList"
        child_template_stack = template_stack
        if opcode == "IncludeTaskListTemplate":
            template_name = task.get("Name")
            bindings = (
                (task_templates or {}).get(template_name, ())
                if isinstance(template_name, str) and template_name
                else ()
            )
            if not isinstance(template_name, str) or not template_name:
                template_blocked_reason = "task_list_template_name_missing"
                child_task_list = []
            elif template_name in template_stack:
                template_blocked_reason = f"task_list_template_cycle:{template_name}"
                child_task_list = []
            elif len(bindings) != 1:
                template_blocked_reason = (
                    f"task_list_template_missing:{template_name}"
                    if not bindings
                    else f"task_list_template_ambiguous:{template_name}"
                )
                child_task_list = []
            else:
                binding = bindings[0]
                child_task_list = list(binding.task_list)
                child_task_list_json_path = f"{binding.json_path}.TaskList"
                child_template_stack = (*template_stack, template_name)
                evidence["task_list_template"] = {
                    "name": template_name,
                    "json_path": binding.json_path,
                    "scope": binding.scope,
                    "task_count": len(binding.task_list),
                }
        for child_index, child in enumerate(child_task_list):
            child_lowered = self._lower_status_callback_task_tree(
                child,
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                callback_id=callback_id,
                event=event,
                callback_index=callback_index,
                task_index=child_index,
                task_path=f"{child_task_list_json_path}[{child_index}]",
                branch=f"{branch}:task_list",
                parent_task_id=task_id,
                queue_priority_lookup=queue_priority_lookup,
                source_context=source_context,
                task_templates=task_templates,
                template_stack=child_template_stack,
            )
            lowered.merge(child_lowered)
            child_task_ids.extend(item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id)
        for child_index, child in enumerate(task.get("SuccessTaskList") or []):
            child_lowered = self._lower_status_callback_task_tree(
                child,
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                callback_id=callback_id,
                event=event,
                callback_index=callback_index,
                task_index=child_index,
                task_path=f"{task_path}.SuccessTaskList[{child_index}]",
                branch="success",
                parent_task_id=task_id,
                queue_priority_lookup=queue_priority_lookup,
                source_context=source_context,
                task_templates=task_templates,
                template_stack=template_stack,
            )
            lowered.merge(child_lowered)
            child_ids = [item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id]
            child_task_ids.extend(child_ids)
            success_task_ids.extend(child_ids)
        for child_index, child in enumerate(task.get("FailedTaskList") or []):
            child_lowered = self._lower_status_callback_task_tree(
                child,
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                callback_id=callback_id,
                event=event,
                callback_index=callback_index,
                task_index=child_index,
                task_path=f"{task_path}.FailedTaskList[{child_index}]",
                branch="failed",
                parent_task_id=task_id,
                queue_priority_lookup=queue_priority_lookup,
                source_context=source_context,
                task_templates=task_templates,
                template_stack=template_stack,
            )
            lowered.merge(child_lowered)
            child_ids = [item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id]
            child_task_ids.extend(child_ids)
            failed_task_ids.extend(child_ids)
        if opcode == "Retarget":
            coverage_status, blocked_reason = _retarget_task_status(retarget_condition, child_task_ids)
        elif equipment_source_admitted:
            coverage_status, blocked_reason = _equipment_task_admission(
                event,
                opcode,
                task,
                modifier_name=modifier_name,
            )
        else:
            coverage_status, blocked_reason = _status_callback_task_admission(event, opcode, task)
        source_admitted = (
            _queue_intent_source_admitted(relative)
            if opcode in QUEUE_INTENT_OPCODES
            else _status_callback_task_source_admitted(
                relative,
                event,
                opcode,
                equipment_source_admitted=equipment_source_admitted,
            )
        )
        if coverage_status == "executable" and not source_admitted:
            coverage_status = "blocked"
            blocked_reason = "status_callback_source_mode_not_admitted"
        if template_blocked_reason:
            coverage_status = "blocked"
            blocked_reason = template_blocked_reason
        task_payload = _status_callback_runtime_payload(
            task,
            source_modifier_name=modifier_name,
        )
        if opcode == "IncludeTaskListTemplate":
            task_payload = {
                **task_payload,
                "template_name": task.get("Name") if isinstance(task.get("Name"), str) else "",
                "template_blocked_reason": template_blocked_reason,
            }
        lowered.status_callback_tasks.append(
            StatusCallbackTaskIR(
                task_id=task_id,
                callback_id=callback_id,
                modifier_name=modifier_name,
                event=event,
                task_index=task_index,
                task_path=task_path,
                branch=branch,
                opcode=opcode,
                effect_id="" if opcode == "Retarget" else effect_id,
                condition_id=retarget_condition.condition_id if retarget_condition else "",
                target_expression_id=(
                    task_target_expression_id
                ),
                parent_task_id=parent_task_id,
                child_task_ids=tuple(child_task_ids),
                success_task_ids=tuple(success_task_ids),
                failed_task_ids=tuple(failed_task_ids),
                source=source,
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
                task_payload=task_payload,
                retarget_policy=_retarget_task_evidence(task) if opcode == "Retarget" else {},
            )
        )
        if opcode not in STATUS_CALLBACK_EFFECTLESS_OPCODES:
            payload = _effect_payload(task, opcode, modifier_name)
            payload, task_target_expressions = _attach_target_expressions_to_effect_payload(
                payload,
                task,
                effect_id=effect_id,
                source=source,
            )
            lowered.target_expressions.extend(task_target_expressions)
            effect_status = _effect_coverage_status(opcode, payload)
            lowered.effects.append(
                EffectIR(
                    effect_id=effect_id,
                    opcode=opcode,
                    payload=payload,
                    source=source,
                    coverage_status=effect_status,
                    source_mode=(
                        "mainline" if equipment_source_admitted else ""
                    ),
                    owner_modifier_name=modifier_name,
                )
            )
            lowered.formulas.extend(self._extract_formulas(task, source, effect_id))
            lowered.formulas.extend(_damage_family_evidence(task, opcode, source, effect_id))
        if opcode == "DamageByAttackProperty":
            emission = _status_damage_emission_from_task(
                callback_id=callback_id,
                task_id=task_id,
                modifier_name=modifier_name,
                event=event,
                task=task,
                source=source,
            )
            if emission is not None:
                lowered.status_damage_emissions.append(emission)
        if opcode == "ModifyDamageData":
            lowered.damage_modifiers.append(
                _damage_modifier_from_task(
                    callback_id=callback_id,
                    task_id=task_id,
                    modifier_name=modifier_name,
                    event=event,
                    task=task,
                    source=source,
                )
            )
        if opcode in {"ModifyActionDelay", "SetActionDelay"}:
            lowered.action_delay_emissions.append(
                _action_delay_emission_from_task(
                    callback_id=callback_id,
                    task_id=task_id,
                    modifier_name=modifier_name,
                    event=event,
                    opcode=opcode,
                    task=task,
                    source=source,
                )
            )
        if opcode in QUEUE_INTENT_OPCODES:
            lowered.queue_intents.append(
                _queue_intent_from_task(
                    callback_id=callback_id,
                    task_id=task_id,
                    event=event,
                    opcode=opcode,
                    task=task,
                    source=source,
                    queue_priority_lookup=queue_priority_lookup,
                )
            )
        return lowered

    def _lower_condition(self, predicate: Any, source: IRSource, task_index: int) -> ConditionIR | None:
        if not isinstance(predicate, dict):
            return None
        opcode = _short_gamecore_type(predicate.get("$type"))
        equipment_source_admitted = bool(
            source.evidence.get("equipment_ability_source_admitted")
        )
        condition_source = _condition_source_from_parent(source, "Predicate")
        payload = _condition_payload_with_tbgd_defaults(
            opcode,
            _typed_condition_payload(
                _compact_payload(predicate),
                equipment_scope=equipment_source_admitted,
                damage_tag_registry=self._damage_tag_registry,
                source=condition_source,
            ),
        )
        family_stage = (
            classify_equipment_condition(opcode, predicate)
            if equipment_source_admitted
            else "unknown"
        )
        target_blocked_reason = _condition_payload_target_blocked_reason(payload)
        if target_blocked_reason:
            status = "blocked"
            blocked_reason = target_blocked_reason
        elif equipment_source_admitted and family_stage not in {"s7", "s8"}:
            status = "blocked"
            blocked_reason = (
                "equipment_condition_family_unclassified"
            )
        else:
            status = (
                "executable"
                if _condition_payload_executable(opcode, payload)
                else classify_opcode(opcode)
            )
            blocked_reason = (
                "" if status == "executable" else f"condition_not_admitted:{opcode}"
            )
        condition_path = str(source.evidence.get("task_path", task_index)) if isinstance(source.evidence, dict) else str(task_index)
        return ConditionIR(
            condition_id=f"condition:{source.source_path}:{source.raw_id}:{source.evidence.get('callback_index')}:{condition_path}:{opcode}",
            opcode=opcode,
            payload=payload,
            source=condition_source,
            coverage_status=status,
            expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
            blocked_reason=blocked_reason,
        )

    def _extract_formulas(self, task: Any, source: IRSource, parent_id: str) -> list[FormulaIR]:
        formulas: list[FormulaIR] = []
        for index, expression in enumerate(_iter_postfix_expr(task)):
            formulas.append(
                FormulaIR(
                    formula_id=f"formula:{parent_id}:{index}",
                    kind="postfix_expr",
                    expression=_json_safe(expression),
                    source=source,
                    coverage_status="audit_only",
                )
            )
        for index, fixed_value in enumerate(_iter_fixed_values(task)):
            formulas.append(
                FormulaIR(
                    formula_id=f"formula:{parent_id}:fixed:{index}",
                    kind="fixed_value",
                    expression=_json_safe(fixed_value),
                    source=source,
                    coverage_status="executable",
                )
            )
        return formulas

    def _lower_elation_mechanics(self) -> list[FormulaIR]:
        formulas: list[FormulaIR] = []
        for relative_path in ELATION_MECHANIC_FILES:
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for index, (raw_path, key, value) in enumerate(_iter_elation_values(data)):
                mechanic = "elation_damage" if key == "ElationDamageAddedRatio" else "elation_runtime"
                coverage_status = "blocked" if key == "ElationDamageAddedRatio" else "discovered_only"
                source = IRSource(
                    source_path=relative_path,
                    raw_type=Path(relative_path).stem,
                    raw_id=raw_path,
                    evidence={
                        "raw_path": raw_path,
                        "key": key,
                        "mechanic": mechanic,
                        "damage_formula_family": "elation",
                    },
                )
                blocked_reason = (
                    "Elation damage property is discovered in TBGD, "
                    "but the complete 4.0 damage formula is not executable in v0_207"
                )
                formulas.append(
                    FormulaIR(
                        formula_id=f"mechanic:{mechanic}:{relative_path}:{index}",
                        kind="mechanic_property",
                        expression={
                            "mechanic": mechanic,
                            "property": key,
                            "raw_path": raw_path,
                            "value": _json_safe(value),
                            "damage_formula_family": "elation",
                            "source_mode": "mainline",
                            "runtime_status": coverage_status,
                            "blocked_reason": blocked_reason
                            if key == "ElationDamageAddedRatio"
                            else "Elation runtime property discovered for taxonomy evidence",
                        },
                        source=source,
                        coverage_status=coverage_status,
                    )
                )
        return formulas

    def _lower_battle_state_transitions(self) -> list[BattleStateTransitionIR]:
        """Project shared battle-event windows from their structured queue tasks.

        The raw tasks name the engine insertion contract.  The state path and
        callback mapping are an explicit v8 lowering rule; runtime never reads
        the stage ability file or infers an event from display text.
        """

        relative_path = ELATION_STATE_TRANSITION_FILE
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

        callback_events = {
            str(node.get("Event") or "")
            for _, node in _iter_json_dicts(data)
            if isinstance(node.get("Event"), str)
        }
        specifications = (
            {
                "transition_rule_id": (
                    "battle_state_transition:elation_time_active:start"
                ),
                "trigger_kind": "turn_insert_action_priority",
                "trigger_identity": "StartElationTime",
                "runtime_event_type": "elation.time.started",
                "callback_event": "OnListenElationTimeStart",
                "before_value": False,
                "after_value": True,
                "allow_missing_before": True,
                "matches": tuple(
                    (json_path, node)
                    for json_path, node in _iter_json_dicts(data)
                    if node.get("$type") == "RPG.GameCore.TurnInsertAction"
                    and node.get("InsertActionPriority") == "StartElationTime"
                ),
            },
            {
                "transition_rule_id": (
                    "battle_state_transition:elation_time_active:end"
                ),
                "trigger_kind": "turn_insert_ability",
                "trigger_identity": next(
                    (
                        str(ability_name)
                        for _, node in _iter_json_dicts(data)
                        if node.get("$type") == "RPG.GameCore.TurnInsertAbility"
                        and isinstance(node.get("AbilityName"), dict)
                        and isinstance(
                            ability_name := node["AbilityName"].get("Value"),
                            str,
                        )
                        and "Elation" in ability_name
                        and ability_name.endswith("EndElationTime")
                    ),
                    "",
                ),
                "runtime_event_type": "elation.time.ended",
                "callback_event": "OnListenElationTimeEnd",
                "before_value": True,
                "after_value": False,
                "allow_missing_before": False,
                "matches": tuple(
                    (json_path, node)
                    for json_path, node in _iter_json_dicts(data)
                    if node.get("$type") == "RPG.GameCore.TurnInsertAbility"
                    and isinstance(node.get("AbilityName"), dict)
                    and isinstance(node["AbilityName"].get("Value"), str)
                    and "Elation" in node["AbilityName"]["Value"]
                    and node["AbilityName"]["Value"].endswith(
                        "EndElationTime"
                    )
                ),
            },
        )

        transitions: list[BattleStateTransitionIR] = []
        for specification in specifications:
            matches = specification["matches"]
            callback_event = str(specification["callback_event"])
            executable = (
                len(matches) == 1
                and bool(specification["trigger_identity"])
                and callback_event in callback_events
            )
            blocked_reason = "" if executable else (
                "battle_state_transition_source_not_unique_or_callback_missing"
            )
            for json_path, node in matches:
                transitions.append(
                    BattleStateTransitionIR(
                        transition_rule_id=str(
                            specification["transition_rule_id"]
                        ),
                        trigger_kind=str(specification["trigger_kind"]),
                        trigger_identity=str(
                            specification["trigger_identity"]
                        ),
                        state_path=("global_flags", "elation_time_active"),
                        before_value=specification["before_value"],
                        after_value=specification["after_value"],
                        runtime_event_type=str(
                            specification["runtime_event_type"]
                        ),
                        callback_event=callback_event,
                        source=IRSource(
                            source_path=relative_path,
                            raw_type=str(node.get("$type") or ""),
                            raw_id=json_path,
                            evidence={
                                "json_path": json_path,
                                "trigger_kind": specification["trigger_kind"],
                                "trigger_identity": specification[
                                    "trigger_identity"
                                ],
                                "runtime_event_type": specification[
                                    "runtime_event_type"
                                ],
                                "callback_event": callback_event,
                                "derivation": (
                                    "structured_battle_event_queue_contract"
                                ),
                            },
                        ),
                        coverage_status=(
                            "executable" if executable else "blocked"
                        ),
                        blocked_reason=blocked_reason,
                        allow_missing_before=bool(
                            specification["allow_missing_before"]
                        ),
                    )
                )
        return transitions

    def _lower_damage_behavior_templates(self) -> list[FormulaIR]:
        path = self.tbgd_root / DAMAGE_BEHAVIOR_TEMPLATE_FILE
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        config = data.get("ConfigList") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            return []
        formulas: list[FormulaIR] = []
        for name, payload in sorted(config.items()):
            family = _damage_behavior_family(str(name))
            if family == "unknown":
                continue
            source = IRSource(
                source_path=DAMAGE_BEHAVIOR_TEMPLATE_FILE,
                raw_type=Path(DAMAGE_BEHAVIOR_TEMPLATE_FILE).stem,
                raw_id=str(name),
                evidence={
                    "template_name": str(name),
                    "damage_formula_family": family,
                    "bypasses_normal_multipliers": family in {"true_damage", "hp_loss"},
                },
            )
            formulas.append(
                FormulaIR(
                    formula_id=f"mechanic:{family}:{DAMAGE_BEHAVIOR_TEMPLATE_FILE}:{name}",
                    kind="mechanic_property",
                    expression={
                        "mechanic": f"{family}_damage",
                        "property": str(name),
                        "value": _json_safe(payload),
                        "damage_formula_family": family,
                        "source_mode": "mainline",
                        "runtime_status": "executable",
                        "bypasses_normal_multipliers": True,
                    },
                    source=source,
                    coverage_status="lowered",
                )
            )
        return formulas

    def _modifier_maps(
        self,
        data: Any,
        *,
        selected_ability_indices: frozenset[int] | None = None,
    ) -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
        maps: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        if not isinstance(data, dict):
            return maps
        ability_list = data.get("AbilityList")
        selected_abilities: list[tuple[int, dict[str, Any]]] = []
        if isinstance(ability_list, list):
            for ability_index, ability in enumerate(ability_list):
                if (
                    selected_ability_indices is not None
                    and ability_index not in selected_ability_indices
                ):
                    continue
                if not isinstance(ability, dict):
                    continue
                selected_abilities.append((ability_index, ability))
                modifiers = ability.get("Modifiers")
                if isinstance(modifiers, dict):
                    ability_name = str(
                        ability.get("Name") or ability.get("AbilityName") or ""
                    )
                    maps.extend(
                        (
                            "Modifiers",
                            name,
                            value,
                            {
                                "ability_index": ability_index,
                                "ability_name": ability_name,
                                "json_path": (
                                    f"$.AbilityList[{ability_index}].Modifiers.{name}"
                                ),
                                "_ability_dynamic_values": ability.get(
                                    "DynamicValues"
                                ),
                                "_ability_dynamic_values_json_path": (
                                    f"$.AbilityList[{ability_index}].DynamicValues"
                                ),
                            },
                        )
                        for name, value in modifiers.items()
                        if isinstance(value, dict)
                    )
        modifier_map = data.get("ModifierMap")
        if isinstance(modifier_map, dict):
            for name, value in modifier_map.items():
                if not isinstance(value, dict):
                    continue
                references = tuple(
                    ability_index
                    for ability_index, ability in selected_abilities
                    if _raw_structure_references_text(ability, str(name))
                )
                if selected_ability_indices is not None and not references:
                    continue
                maps.append(
                    (
                        "ModifierMap",
                        name,
                        value,
                        {
                            "ability_index": references[0]
                            if len(references) == 1
                            else None,
                            "referenced_by_ability_indices": list(references),
                            "json_path": f"$.ModifierMap.{name}",
                        },
                    )
                )
        global_modifiers = data.get("GlobalModifiers")
        if isinstance(global_modifiers, dict):
            for name, value in global_modifiers.items():
                if not isinstance(value, dict):
                    continue
                references = tuple(
                    ability_index
                    for ability_index, ability in selected_abilities
                    if _raw_structure_references_text(ability, str(name))
                )
                if selected_ability_indices is not None and not references:
                    continue
                maps.append(
                    (
                        "GlobalModifiers",
                        name,
                        value,
                        {
                            "ability_index": references[0]
                            if len(references) == 1
                            else None,
                            "referenced_by_ability_indices": list(references),
                            "json_path": f"$.GlobalModifiers.{name}",
                        },
                    )
                )
        return maps


@dataclass(frozen=True)
class _TaskListTemplateBinding:
    name: str
    task_list: tuple[dict[str, Any], ...]
    json_path: str
    scope: str


def _task_list_template_bindings(
    raw_templates: Any,
    *,
    json_path: str,
    scope: str,
) -> dict[str, tuple[_TaskListTemplateBinding, ...]]:
    """Index concrete task templates without hiding duplicates or bad rows."""

    indexed: dict[str, list[_TaskListTemplateBinding]] = {}
    if raw_templates is None:
        return {}
    if not isinstance(raw_templates, list):
        return {
            "": (
                _TaskListTemplateBinding(
                    name="",
                    task_list=(),
                    json_path=json_path,
                    scope=f"{scope}:invalid_container",
                ),
            )
        }
    for index, raw_template in enumerate(raw_templates):
        if not isinstance(raw_template, dict):
            continue
        name = raw_template.get("Name")
        tasks = raw_template.get("TaskList")
        if not isinstance(name, str) or not name or not isinstance(tasks, list):
            continue
        if any(not isinstance(task, dict) for task in tasks):
            continue
        indexed.setdefault(name, []).append(
            _TaskListTemplateBinding(
                name=name,
                task_list=tuple(tasks),
                json_path=f"{json_path}[{index}]",
                scope=scope,
            )
        )
    return {
        name: tuple(bindings)
        for name, bindings in sorted(indexed.items())
    }


def _merge_task_list_template_bindings(
    global_bindings: dict[str, tuple[_TaskListTemplateBinding, ...]],
    local_bindings: dict[str, tuple[_TaskListTemplateBinding, ...]],
) -> dict[str, tuple[_TaskListTemplateBinding, ...]]:
    """Local and global rows share a namespace; collisions stay ambiguous."""

    names = set(global_bindings) | set(local_bindings)
    return {
        name: (*global_bindings.get(name, ()), *local_bindings.get(name, ()))
        for name in sorted(names)
    }


def _equipment_nested_modifier_stage(
    modifier_maps: list[tuple[str, str, dict[str, Any], dict[str, Any]]],
) -> str:
    """Classify the nested modifier graph selected by one equipment raw row."""

    if not modifier_maps:
        return "non_gameplay"
    stages: list[str] = []
    for _, _, modifier, _ in modifier_maps:
        callbacks = modifier.get("_CallbackList")
        if callbacks is None:
            stages.append("s7")
            continue
        if not isinstance(callbacks, list):
            return "unknown"
        if not callbacks:
            stages.append("s7")
            continue
        for callback in callbacks:
            if not isinstance(callback, dict):
                return "unknown"
            event = callback.get("Event")
            tasks = callback.get("CallbackConfig")
            if not isinstance(event, str) or not event:
                return "unknown"
            stages.append(classify_equipment_callback(event, tasks))
    if "unknown" in stages:
        return "unknown"
    if "s8" in stages:
        return "s8"
    if stages and all(stage == "non_gameplay" for stage in stages):
        return "non_gameplay"
    return "s7"


@dataclass
class _LoweredAbility:
    entities: list[RuleEntity] = field(default_factory=list)
    ability_tasks: list[AbilityTaskIR] = field(default_factory=list)
    status_callbacks: list[StatusCallbackIR] = field(default_factory=list)
    status_callback_tasks: list[StatusCallbackTaskIR] = field(default_factory=list)
    ability_property_watchers: list[AbilityPropertyWatcherIR] = field(default_factory=list)
    ability_property_ranges: list[AbilityPropertyRangeIR] = field(default_factory=list)
    status_damage_emissions: list[StatusDamageEmissionIR] = field(default_factory=list)
    damage_modifiers: list[DamageModifierIR] = field(default_factory=list)
    action_delay_emissions: list[ActionDelayEmissionIR] = field(default_factory=list)
    queue_intents: list[QueueIntentIR] = field(default_factory=list)
    skill_continuations: list[SkillContinuationIR] = field(default_factory=list)
    triggers: list[TriggerIR] = field(default_factory=list)
    effects: list[EffectIR] = field(default_factory=list)
    conditions: list[ConditionIR] = field(default_factory=list)
    formulas: list[FormulaIR] = field(default_factory=list)
    target_expressions: list[TargetExpressionIR] = field(default_factory=list)

    def merge(self, other: "_LoweredAbility") -> None:
        self.entities.extend(other.entities)
        self.ability_tasks.extend(other.ability_tasks)
        self.status_callbacks.extend(other.status_callbacks)
        self.status_callback_tasks.extend(other.status_callback_tasks)
        self.ability_property_watchers.extend(other.ability_property_watchers)
        self.ability_property_ranges.extend(other.ability_property_ranges)
        self.status_damage_emissions.extend(other.status_damage_emissions)
        self.damage_modifiers.extend(other.damage_modifiers)
        self.action_delay_emissions.extend(other.action_delay_emissions)
        self.queue_intents.extend(other.queue_intents)
        self.skill_continuations.extend(other.skill_continuations)
        self.triggers.extend(other.triggers)
        self.effects.extend(other.effects)
        self.conditions.extend(other.conditions)
        self.formulas.extend(other.formulas)
        self.target_expressions.extend(other.target_expressions)


def _mark_client_only_trigger_ability_tasks(
    lowered: _LoweredAbility,
    *,
    client_only_ability_names: frozenset[str],
    client_only_ability_path: str,
) -> None:
    if not client_only_ability_names:
        return
    client_only_effect_ids: set[str] = set()
    rewritten_effects: list[EffectIR] = []
    for effect in lowered.effects:
        standard = effect.payload.get("standard")
        ability_name = (
            standard.get("ability_name")
            if effect.opcode == "TriggerAbility" and isinstance(standard, dict)
            else None
        )
        if not isinstance(ability_name, str) or ability_name not in client_only_ability_names:
            rewritten_effects.append(effect)
            continue
        raw_fields = {
            key: value
            for key, value in effect.payload.items()
            if key not in {"standard", "target_expression_refs"}
        }
        payload = {
            **effect.payload,
            "client_only_ability_source": {
                "ability_name": ability_name,
                "source_path": client_only_ability_path,
                "raw_type": "AbilityList",
                "raw_id": ability_name,
            },
            "process_only_contract": {
                "schema_version": "ability_process_only_source_shape_v1",
                "opcode": effect.opcode,
                "source_fields": sorted({"$type", *raw_fields}),
                "source_field_types": {
                    "$type": "str",
                    **{
                        key: type(value).__name__
                        for key, value in sorted(raw_fields.items())
                    },
                },
                "source_shape_status": "admitted",
                "blocked_reason": "",
                "classification": "client_only_avatar_camera_ability",
            },
        }
        client_only_effect_ids.add(effect.effect_id)
        rewritten_effects.append(
            replace(
                effect,
                payload=payload,
                coverage_status="audit_only",
                source_mode="client_only_avatar_camera",
            )
        )
    lowered.effects = rewritten_effects
    lowered.ability_tasks = [
        replace(
            task,
            execution_mode="process_only",
            coverage_status="audit_only",
            blocked_reason="",
        )
        if task.effect_id in client_only_effect_ids
        else task
        for task in lowered.ability_tasks
    ]


@dataclass(frozen=True)
class _StandaloneActionRef:
    action_id: str
    level: int


def _read_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _enum_values(data: dict[str, Any], enum_name: str) -> dict[str, Any]:
    config_list = data.get("ConfigList")
    enum_root = config_list if isinstance(config_list, dict) else data
    enum = enum_root.get(enum_name)
    values = enum.get("Values") if isinstance(enum, dict) else None
    return dict(values) if isinstance(values, dict) else {}


def _damage_tag_registry(
    tbgd_root: Path,
) -> dict[int, tuple[dict[str, Any], ...]]:
    relative = "Config/GlobalConfig/JsonEnumDefineConfig.json"
    data = _read_json_file(tbgd_root / relative)
    values = _enum_values(data, "DamageTag") if isinstance(data, dict) else {}
    candidates: dict[int, list[dict[str, Any]]] = {}
    for name, raw_value in sorted(values.items()):
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(raw_value, int)
            or isinstance(raw_value, bool)
        ):
            continue
        candidates.setdefault(raw_value, []).append(
            {
                "name": name,
                "value": raw_value,
                "source": IRSource(
                    source_path=relative,
                    raw_type="JsonEnumDefineConfig",
                    raw_id=f"DamageTag.{name}",
                    evidence={
                        "enum": "DamageTag",
                        "key": name,
                        "value": raw_value,
                        "field_context": "DamageTagList",
                        "raw_path": (
                            f"ConfigList.DamageTag.Values.{name}"
                        ),
                    },
                ).to_json(),
            }
        )
    return {
        value: tuple(entries)
        for value, entries in sorted(candidates.items())
    }


def _short_gamecore_type(raw_type: Any) -> str:
    if not isinstance(raw_type, str):
        return "Unknown"
    return raw_type.removeprefix("RPG.GameCore.")


def _normalized_equipment_task(
    raw_opcode: str,
    raw_task: dict[str, Any],
    *,
    equipment_source_admitted: bool,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Normalize an admitted obfuscated schema alias without losing raw evidence."""

    if not equipment_source_admitted:
        return raw_opcode, raw_task, {}
    if raw_opcode == "DIHCJLDIMNA":
        allowed_fields = {"$type", "FHLJGDGMMHK"}
        dynamic_key = raw_task.get("FHLJGDGMMHK")
        if (
            set(raw_task) != allowed_fields
            or not isinstance(dynamic_key, str)
            or not dynamic_key
        ):
            return raw_opcode, raw_task, {
                "schema_alias_admission": "blocked",
                "schema_alias_blocked_reason": (
                    "obfuscated_change_value_schema_shape_mismatch"
                ),
            }
        return (
            "SetDynamicValueByChangeValue",
            {
                "$type": "RPG.GameCore.SetDynamicValueByChangeValue",
                "DynamicKey": dynamic_key,
            },
            {
                "schema_alias_admission": "executable",
                "schema_alias_raw_opcode": raw_opcode,
                "schema_alias_canonical_opcode": (
                    "SetDynamicValueByChangeValue"
                ),
                "schema_alias_field_mapping": {
                    "FHLJGDGMMHK": "DynamicKey",
                },
            },
        )
    if raw_opcode != "JDOLDFECMPL":
        return raw_opcode, raw_task, {}
    allowed_fields = {"$type", "AJHHCOHFIFA", "FKCKKFALPBK"}
    amount = raw_task.get("AJHHCOHFIFA")
    operation = raw_task.get("FKCKKFALPBK")
    if (
        set(raw_task) != allowed_fields
        or not isinstance(amount, dict)
        or operation not in {"Add", "Set"}
    ):
        return raw_opcode, raw_task, {
            "schema_alias_admission": "blocked",
            "schema_alias_blocked_reason": "obfuscated_team_boost_schema_shape_mismatch",
        }
    normalized = {
        "$type": "RPG.GameCore.ModifyTeamBoostPoint",
        "ModifyValue": amount,
        "ModifyFunction": operation,
    }
    return "ModifyTeamBoostPoint", normalized, {
        "schema_alias_admission": "executable",
        "schema_alias_raw_opcode": raw_opcode,
        "schema_alias_canonical_opcode": "ModifyTeamBoostPoint",
        "schema_alias_field_mapping": {
            "AJHHCOHFIFA": "ModifyValue",
            "FKCKKFALPBK": "ModifyFunction",
        },
    }


def _entity_raw_id(entity_type: str, id_key: str, row: dict[str, Any]) -> str:
    if entity_type == "avatar_promotion":
        promotion = row.get("Promotion", 0)
        return f"{row[id_key]}:{promotion}"
    return str(row[id_key])


def _stage_id(row: dict[str, Any]) -> str:
    value = row.get("StageID")
    if isinstance(value, bool) or value is None:
        return ""
    return str(value)


def _stage_config_wave_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    for item in value:
        if not isinstance(item, dict):
            continue
        key = item.get("BFLIFKBEOPJ")
        raw_value = item.get("MNDFOPKBHKP")
        if key != "_Wave":
            continue
        try:
            return int(str(raw_value))
        except (TypeError, ValueError):
            return 0
    return 0


def _stage_monster_items(wave: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    items: list[tuple[int, str, Any]] = []
    for key, value in wave.items():
        if not isinstance(key, str) or not key.startswith("Monster"):
            continue
        items.append((_stage_monster_position(key), key, value))
    return tuple((key, value) for _, key, value in sorted(items, key=lambda item: (item[0], item[1])))


def _stage_monster_position(key: str) -> int:
    suffix = key.removeprefix("Monster")
    try:
        return int(suffix)
    except ValueError:
        return 9999


def _stage_monster_raw_id(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text


STATUS_EVENT_RUNTIME_SOURCES: dict[str, tuple[str, ...]] = {
    "OnListenAllowAction": ("turn.begin",),
    "OnListenTurnEnd": ("turn.end",),
    "OnListenTurnPhase1Begin": ("turn.begin",),
    "OnBeforeSkillUse": ("action.window.before_skill_use",),
    "OnListenBeforeSkillUse": ("action.window.before_skill_use",),
    "OnBeforeAttack": ("action.window.before_attack",),
    "OnListenBeforeAttack": ("action.window.before_attack",),
    "OnAfterAttack": ("action.window.after_attack", "action.after_attack"),
    "OnListenAfterAttack": ("action.after_attack",),
    "OnAfterAttackEnd": ("action.attack_end",),
    "OnAfterSkillUse": ("action.window.after_skill_use",),
    "OnListenAfterSkillUse": ("action.window.after_skill_use",),
    "OnActionEnd": ("action.end",),
    "OnBeforeInsertActionPrepare": ("queue.action.before",),
    "OnInsertActionStart": ("queue.action.before",),
    "OnInsertActionFinish": ("queue.action.after",),
    "OnListenInsertAbilityFinish": ("queue.action.after",),
    "OnBeforeHit": ("damage.before_hit",),
    "OnBeforeHitAll": ("damage.hit_sequence.before",),
    "OnBeforeBeingAttacked": ("damage.target_attack.before",),
    "OnDefenderPrepareAttackData": ("damage.target_attack.before",),
    "OnBeforeBeingHitAll": ("damage.target_hit_sequence.before",),
    "OnAfterHit": ("damage.hit",),
    "OnAfterHitAll": ("damage.hit_sequence.after",),
    "OnAfterBeingHitAll": ("damage.target_hit_sequence.after",),
    "OnAfterBeingAttacked": ("damage.target_attack.after",),
    "OnBeingHit": ("damage.hit",),
    "OnHit": ("damage.hit", "toughness.hit"),
    "OnHPChange": ("hp.change", "heal.after"),
    "OnListenHPChange": ("hp.change", "heal.after"),
    "OnAfterBeingHeal": ("heal.after",),
    "OnAfterDealHeal": ("heal.after",),
    "OnBeforeDealHeal": ("heal.before",),
    "OnHPOverflow": ("heal.after",),
    "OnShieldChange": ("shield.change",),
    "OnListenShieldChange": ("shield.change",),
    "OnListenInitShield": ("shield.change",),
    "OnBeforeBeingStanceDamage": ("toughness.before_hit",),
    "OnBeingStanceDamage": ("toughness.hit",),
    "OnTriggerBreak": ("break.triggered",),
    "OnBeforeBeingBreak": ("toughness.hit",),
    "OnBeingBreak": ("break.triggered",),
    "OnListenBreak": ("break.triggered",),
    "OnTriggerDeath": ("unit.defeated",),
    "OnDeathrattle": ("unit.defeated",),
    "OnListenCharacterDie": ("unit.defeated",),
    "OnTriggerDeathrattle": ("unit.defeated",),
    "OnBeforeDying": ("unit.before_dying",),
    "OnCreate": ("status.lifecycle",),
    "OnDestroy": ("status.lifecycle",),
    "OnPhase1": ("status.lifecycle",),
    "OnPhase2": ("status.lifecycle",),
    "OnStack": ("status.lifecycle",),
    "OnModifierAdd": ("status.lifecycle",),
    "OnModifierRemove": ("status.lifecycle",),
    "OnAddModifierSuc": ("status.lifecycle",),
    "OnListenModifierAdd": ("status.lifecycle",),
    "OnListenModifierRemove": ("status.lifecycle",),
    "OnModifierOnStack": ("status.lifecycle",),
    "OnListenModifierOnStack": ("status.lifecycle",),
    "OnModifierDotAdd": ("status.lifecycle",),
    "OnActionDelayEffect": ("action_delay.changed",),
    "OnActionDelayEffectAll": ("action_delay.changed",),
    "OnListenGlobalActionDelayChanged": ("action_delay.changed",),
    "OnEnterBattle": ("battle.setup",),
    "OnWaveMonster": ("wave.monster",),
    "OnListenCharacterCreate": ("unit.created", "summon.spawned", "wave.monster"),
    "OnListenBattleEventCreate": ("battle_event.created",),
    "OnListenCharacterEscape": ("unit.removed", "summon.removed"),
    "OnListenDepartedStart": ("unit.departed.started",),
    "OnListenDepartedEnd": ("unit.departed.ended",),
    "OnSnapshotCreate": ("unit.created", "summon.spawned", "wave.monster"),
    "OnListenAvatarBaseTypeChange": ("unit.base_type.changed",),
    "OnStackWeakness": ("weakness.stacked",),
    "OnListenElationTimeStart": ("elation.time.started",),
    "OnListenElationTimeEnd": ("elation.time.ended",),
    "OnUltraSkillPrepare": ("action.ultimate.prepare",),
    "OnCustomEvent": ("custom.event",),
    **resource_callback_runtime_sources(),
}


STATUS_EVENT_BLOCKED_DEPENDENCIES: dict[str, str] = {}


def _lower_status_event_families(
    status_callbacks: list[StatusCallbackIR],
    status_callback_tasks: list[StatusCallbackTaskIR],
) -> list[StatusEventFamilyIR]:
    callbacks_by_event: dict[str, list[StatusCallbackIR]] = {}
    for callback in status_callbacks:
        if callback.scope_kind == "ability_property_range":
            continue
        callbacks_by_event.setdefault(callback.event, []).append(callback)
    tasks_by_callback: dict[str, list[StatusCallbackTaskIR]] = {}
    for task in status_callback_tasks:
        tasks_by_callback.setdefault(task.callback_id, []).append(task)
    families: list[StatusEventFamilyIR] = []
    for event, callbacks in sorted(callbacks_by_event.items()):
        tasks = [task for callback in callbacks for task in tasks_by_callback.get(callback.callback_id, ())]
        runtime_sources = STATUS_EVENT_RUNTIME_SOURCES.get(event, ())
        blocked_dependency = STATUS_EVENT_BLOCKED_DEPENDENCIES.get(event, "")
        if not runtime_sources and not blocked_dependency:
            blocked_dependency = f"event_source_missing:{event}"
        coverage_status = "blocked" if blocked_dependency else "executable"
        families.append(
            StatusEventFamilyIR(
                status_event_family_id=f"status_event_family:{_safe_id(event)}",
                callback_event=event,
                event_family=_status_event_family_name(event),
                default_scope_kind=_status_callback_scope_kind(event),
                runtime_event_sources=runtime_sources,
                source_basis="StatusCallbackIR.event",
                source=IRSource(
                    source_path="CanonicalIR/status_callbacks",
                    raw_type="StatusCallbackEventFamily",
                    raw_id=event,
                    evidence={
                        "callback_event": event,
                        "callback_count": len(callbacks),
                        "runtime_event_sources": list(runtime_sources),
                        "blocked_dependency": blocked_dependency,
                        "source_basis": "lowered from StatusCallbackIR.event values produced by TBGD ability lowering",
                    },
                ),
                callback_count=len(callbacks),
                executable_callback_count=sum(
                    1
                    for callback in callbacks
                    if callback.coverage_status == "executable" and callback.admission_status == "executable"
                ),
                blocked_callback_count=sum(
                    1
                    for callback in callbacks
                    if callback.coverage_status != "executable" or callback.admission_status != "executable"
                ),
                task_count=len(tasks),
                task_opcode_counts=dict(Counter(task.opcode for task in tasks)),
                source_mode_counts=dict(Counter(callback.source_mode for callback in callbacks)),
                coverage_status=coverage_status,
                blocked_reason=blocked_dependency,
                admission_status=coverage_status,
                blocking_dependency=blocked_dependency,
            )
        )
    return families


def _status_event_blocked_reasons(status_event_families: list[StatusEventFamilyIR]) -> dict[str, str]:
    return {
        family.callback_event: family.blocking_dependency or family.blocked_reason
        for family in status_event_families
        if family.coverage_status != "executable" or family.admission_status != "executable"
    }


def _block_status_callbacks_by_event_family(
    status_callbacks: list[StatusCallbackIR],
    blocked_reasons_by_event: dict[str, str],
) -> list[StatusCallbackIR]:
    blocked_callbacks: list[StatusCallbackIR] = []
    for callback in status_callbacks:
        reason = blocked_reasons_by_event.get(callback.event)
        if not reason:
            blocked_callbacks.append(callback)
            continue
        blocked_callbacks.append(
            replace(
                callback,
                coverage_status="blocked",
                admission_status="blocked",
                blocked_reason=callback.blocked_reason or reason,
                blocking_dependency=callback.blocking_dependency or reason,
            )
        )
    return blocked_callbacks


def _block_status_callback_tasks_by_callback(
    status_callback_tasks: list[StatusCallbackTaskIR],
    blocked_reasons_by_callback: dict[str, str],
) -> list[StatusCallbackTaskIR]:
    blocked_tasks: list[StatusCallbackTaskIR] = []
    for task in status_callback_tasks:
        reason = blocked_reasons_by_callback.get(task.callback_id)
        if not reason:
            blocked_tasks.append(task)
            continue
        blocked_tasks.append(
            replace(
                task,
                coverage_status="blocked",
                blocked_reason=task.blocked_reason or reason,
            )
        )
    return blocked_tasks


def _block_status_callback_derived_by_callback(items: list[Any], blocked_reasons_by_callback: dict[str, str]) -> list[Any]:
    blocked_items: list[Any] = []
    for item in items:
        reason = blocked_reasons_by_callback.get(item.callback_id)
        if not reason:
            blocked_items.append(item)
            continue
        blocked_items.append(
            replace(
                item,
                coverage_status="blocked",
                blocked_reason=item.blocked_reason or reason,
            )
        )
    return blocked_items


def _status_event_family_name(event: str) -> str:
    if event in {"OnCustomEvent"}:
        return "custom_event"
    if event in {"OnWaveMonster"}:
        return "wave"
    if event in {
        "OnCreate",
        "OnDestroy",
        "OnStack",
        "OnModifierAdd",
        "OnModifierRemove",
        "OnPhase1",
        "OnPhase2",
        "OnAddModifierSuc",
        "OnListenModifierAdd",
        "OnListenModifierRemove",
        "OnModifierOnStack",
        "OnListenModifierOnStack",
        "OnModifierDotAdd",
    }:
        return "status_lifecycle"
    if "Hit" in event or "Attacked" in event:
        return "hit"
    if "Break" in event:
        return "break"
    if "Death" in event or "Die" in event or "Dying" in event:
        return "death"
    if "Insert" in event or "Action" in event:
        return "action_or_queue"
    if "Turn" in event or event == "OnListenAllowAction":
        return "turn"
    if "HP" in event or "Heal" in event or "Shield" in event or "SP" in event or "Energy" in event:
        return "resource"
    if "Rogue" in event or "Elation" in event or "Evolve" in event or "Chess" in event:
        return "special_mode"
    return "unadmitted"


def _character_runtime_mechanism_slots(
    *,
    character_data_cards: list[CharacterDataCardIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
    action_ability_bindings: list[ActionAbilityBindingIR],
    status_callbacks: list[StatusCallbackIR],
    damage_modifiers: list[DamageModifierIR],
    queue_intents: list[QueueIntentIR],
    queue_windows: list[QueueWindowIR],
    extra_action_policies: list[ExtraActionPolicyIR],
    skill_continuations: list[SkillContinuationIR],
) -> list[CharacterMechanismSlotIR]:
    valid_card_ids = {card.card_id for card in character_data_cards}
    action_to_card: dict[tuple[str, int], str] = {}
    for binding in skill_formula_bindings:
        if binding.character_data_card_id in valid_card_ids:
            action_to_card[(binding.action_id, binding.level)] = binding.character_data_card_id
    ability_file_to_card: dict[str, str] = {}
    for binding in action_ability_bindings:
        card_id = action_to_card.get((binding.action_id, binding.level))
        if not card_id:
            continue
        ability_file = _ability_file_from_action_binding(binding)
        if ability_file:
            ability_file_to_card[ability_file] = card_id
    callback_to_card: dict[str, str] = {}
    slots: list[CharacterMechanismSlotIR] = []
    for callback in status_callbacks:
        card_id = ability_file_to_card.get(callback.source.source_path, "")
        if not card_id:
            continue
        callback_to_card[callback.callback_id] = card_id
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:status_callback:{callback.callback_id}",
                character_data_card_id=card_id,
                mechanism_kind="status_callback",
                runtime_system="event_dispatch_system",
                linked_ir_ids={
                    "status_callback_id": callback.callback_id,
                    "modifier_name": callback.modifier_name,
                    "event": callback.event,
                    "task_ids": list(callback.task_ids),
                },
                activation={
                    "kind": "status_listener",
                    "event": callback.event,
                    "scope_kind": callback.scope_kind,
                    "source_mode": callback.source_mode,
                },
                semantics={
                    "admission_status": callback.admission_status,
                    "blocking_dependency": callback.blocking_dependency,
                    "blocked_reason": callback.blocked_reason,
                },
                source=callback.source,
                coverage_status=callback.coverage_status,
                blocked_reason=callback.blocked_reason,
            )
        )
    for modifier in damage_modifiers:
        card_id = callback_to_card.get(modifier.callback_id) or ability_file_to_card.get(modifier.source.source_path, "")
        if not card_id:
            continue
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:damage_modifier:{modifier.damage_modifier_id}",
                character_data_card_id=card_id,
                mechanism_kind="damage_modifier",
                runtime_system="damage_formula",
                linked_ir_ids={
                    "damage_modifier_id": modifier.damage_modifier_id,
                    "callback_id": modifier.callback_id,
                    "source_task_id": modifier.source_task_id,
                    "modifier_name": modifier.modifier_name,
                },
                activation={
                    "kind": "status_callback_task",
                    "event": modifier.event,
                    "target_alias": modifier.target_alias,
                },
                semantics={
                    "modifier_terms": list(modifier.modifier_terms),
                },
                source=modifier.source,
                coverage_status=modifier.coverage_status,
                blocked_reason=modifier.blocked_reason,
            )
        )
    intent_to_card: dict[str, str] = {}
    window_by_intent = {window.queue_intent_id: window for window in queue_windows}
    for intent in queue_intents:
        card_id = callback_to_card.get(intent.callback_id) or ability_file_to_card.get(intent.source.source_path, "")
        if not card_id:
            continue
        intent_to_card[intent.queue_intent_id] = card_id
        window = window_by_intent.get(intent.queue_intent_id)
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:queue_intent:{intent.queue_intent_id}",
                character_data_card_id=card_id,
                mechanism_kind="queue_intent",
                runtime_system="queue_system",
                linked_ir_ids={
                    "queue_intent_id": intent.queue_intent_id,
                    "callback_id": intent.callback_id,
                    "source_task_id": intent.source_task_id,
                    "queue_window_id": window.queue_window_id if window else "",
                },
                activation={
                    "kind": "callback_task",
                    "opcode": intent.opcode,
                    "queue_kind": intent.queue_kind,
                },
                semantics={
                    "action_ref_or_ability_name": intent.action_ref_or_ability_name,
                    "skill_index_expr": intent.skill_index_expr,
                    "actor_target_alias": intent.actor_target_alias,
                    "ability_target_alias": intent.ability_target_alias,
                    "window_family": window.window_family if window else "",
                },
                source=intent.source,
                coverage_status=intent.coverage_status,
                blocked_reason=intent.blocked_reason,
            )
        )
    for policy in extra_action_policies:
        card_id = intent_to_card.get(policy.queue_intent_id)
        if not card_id:
            continue
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:extra_action_policy:{policy.extra_action_policy_id}",
                character_data_card_id=card_id,
                mechanism_kind="extra_action_policy",
                runtime_system="scheduler",
                linked_ir_ids={
                    "extra_action_policy_id": policy.extra_action_policy_id,
                    "queue_intent_id": policy.queue_intent_id,
                    "queue_window_id": policy.queue_window_id,
                    "lifecycle_policy_id": policy.lifecycle_policy_id,
                },
                activation={
                    "kind": "queue_window",
                    "source_kind": policy.source_kind,
                },
                semantics={
                    "action_selection_kind": policy.action_selection_kind,
                    "allowed_action_kinds": list(policy.allowed_action_kinds),
                    "fixed_action_ref": policy.fixed_action_ref,
                    "source_basis": policy.source_basis,
                },
                source=policy.source,
                coverage_status=policy.coverage_status,
                blocked_reason=policy.blocked_reason,
            )
        )
    for continuation in skill_continuations:
        card_id = action_to_card.get((continuation.action_id, continuation.level))
        if not card_id:
            continue
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:skill_continuation:{continuation.continuation_id}",
                character_data_card_id=card_id,
                mechanism_kind="skill_continuation",
                runtime_system="skill_continuation_runner",
                linked_ir_ids={
                    "skill_continuation_id": continuation.continuation_id,
                    "source_task_id": continuation.source_task_id,
                    "action_id": continuation.action_id,
                    "level": continuation.level,
                },
                activation={
                    "kind": "ability_task",
                    "opcode": continuation.opcode,
                },
                semantics={
                    "continuation_kind": continuation.continuation_kind,
                    "fixed_skill_type": continuation.fixed_skill_type,
                    "child_skill_index_expr": continuation.child_skill_index_expr,
                },
                source=continuation.source,
                coverage_status=continuation.coverage_status,
                blocked_reason=continuation.blocked_reason,
            )
        )
    return _dedupe_character_mechanism_slots(slots)


def _admit_trace_startup_ability_slots(
    slots: list[CharacterMechanismSlotIR],
    *,
    standalone_graphs: list[StandaloneAbilityGraphIR],
    ability_tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
) -> list[CharacterMechanismSlotIR]:
    graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]] = {}
    for graph in standalone_graphs:
        graphs_by_name.setdefault(graph.ability_name, []).append(graph)
    tasks_by_phase: dict[str, list[AbilityTaskIR]] = {}
    for task in ability_tasks:
        tasks_by_phase.setdefault(task.phase_id, []).append(task)
    effects_by_id = {effect.effect_id: effect for effect in effects}
    admitted: list[CharacterMechanismSlotIR] = []
    for slot in slots:
        if slot.mechanism_kind != "trace_ability_hook":
            admitted.append(slot)
            continue
        admitted.append(
            _admit_trace_startup_ability_slot(
                slot,
                graphs_by_name=graphs_by_name,
                tasks_by_phase=tasks_by_phase,
                effects_by_id=effects_by_id,
            )
        )
    return admitted


def _admit_trace_startup_ability_slot(
    slot: CharacterMechanismSlotIR,
    *,
    graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]],
    tasks_by_phase: dict[str, list[AbilityTaskIR]],
    effects_by_id: dict[str, EffectIR],
) -> CharacterMechanismSlotIR:
    evidence = slot.source.evidence if isinstance(slot.source.evidence, dict) else {}
    if evidence.get("enhanced_id") is None:
        return slot
    semantics = dict(slot.semantics)
    ability_name = str(semantics.get("ability_name") or slot.linked_ir_ids.get("ability_name") or "")
    if not ability_name:
        return _trace_startup_blocked_slot(slot, "trace_ability_name_missing", semantics)
    graph_candidates = tuple(sorted(graphs_by_name.get(ability_name, ()), key=lambda item: item.standalone_ability_graph_id))
    executable_graphs = tuple(graph for graph in graph_candidates if graph.coverage_status == "executable")
    if len(executable_graphs) != 1:
        reason = "trace_startup_graph_missing_or_ambiguous"
        if graph_candidates and not executable_graphs:
            reason = "trace_startup_graph_not_executable"
        return _trace_startup_blocked_slot(
            slot,
            reason,
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": reason,
                    "ability_name": ability_name,
                    "candidate_graph_ids": [graph.standalone_ability_graph_id for graph in graph_candidates],
                    "candidate_graph_statuses": [graph.coverage_status for graph in graph_candidates],
                },
            },
        )
    graph = executable_graphs[0]
    candidate_tasks = tuple(
        task
        for phase_id in graph.phase_ids
        for task in tasks_by_phase.get(phase_id, ())
        if task.callback_kind == "OnStart"
        and not task.parent_task_id
        and task.opcode == "AddModifier"
        and task.effect_id
    )
    if not candidate_tasks:
        return _trace_startup_blocked_slot(
            slot,
            "trace_startup_on_start_add_modifier_missing",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": "trace_startup_on_start_add_modifier_missing",
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                },
            },
        )
    admitted_tasks: list[dict[str, JSONValue]] = []
    blocked_tasks: list[dict[str, JSONValue]] = []
    for task in candidate_tasks:
        effect = effects_by_id.get(task.effect_id)
        if effect is None:
            blocked_tasks.append({"task_id": task.task_id, "blocked_reason": "trace_startup_effect_missing"})
            continue
        effect_reason = _trace_startup_effect_blocked_reason(effect)
        if effect_reason:
            blocked_tasks.append(
                {
                    "task_id": task.task_id,
                    "effect_id": effect.effect_id,
                    "blocked_reason": effect_reason,
                    "effect_coverage_status": effect.coverage_status,
                }
            )
            continue
        dynamic_admission = _trace_startup_dynamic_binding_admission(effect.payload.get("standard"), semantics)
        if dynamic_admission.get("admission_status") == "blocked":
            blocked_tasks.append(
                {
                    "task_id": task.task_id,
                    "effect_id": effect.effect_id,
                    "blocked_reason": str(dynamic_admission.get("blocked_reason") or "trace_dynamic_binding_blocked"),
                    "dynamic_value_binding": dynamic_admission,
                }
            )
            continue
        admitted_tasks.append(
            {
                "task_id": task.task_id,
                "effect_id": effect.effect_id,
                "dynamic_value_binding": _json_safe(dynamic_admission),
            }
        )
    if not admitted_tasks:
        return _trace_startup_blocked_slot(
            slot,
            "trace_startup_no_admitted_on_start_add_modifier",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": "trace_startup_no_admitted_on_start_add_modifier",
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                    "blocked_tasks": blocked_tasks,
                },
            },
        )
    return replace(
        slot,
        semantics={
            **semantics,
            "startup_admission": {
                "admission_status": "executable",
                "startup_kind": "trace_on_start_add_modifier",
                "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                "admitted_tasks": admitted_tasks,
                "blocked_tasks": blocked_tasks,
            },
        },
        coverage_status="executable",
        blocked_reason="",
    )


def _trace_startup_blocked_slot(
    slot: CharacterMechanismSlotIR,
    reason: str,
    semantics: dict[str, JSONValue],
) -> CharacterMechanismSlotIR:
    return replace(
        slot,
        semantics=semantics,
        coverage_status="blocked",
        blocked_reason=reason,
    )


def _trace_startup_effect_blocked_reason(effect: EffectIR) -> str:
    if effect.opcode != "AddModifier":
        return f"trace_startup_effect_opcode_not_add_modifier:{effect.opcode}"
    if effect.coverage_status != "executable":
        return f"trace_startup_effect_not_executable:{effect.coverage_status}"
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return "trace_startup_effect_standard_payload_missing"
    modifier_name = standard.get("modifier_name")
    if not isinstance(modifier_name, str) or not modifier_name:
        return "trace_startup_effect_modifier_name_missing"
    target_alias = standard.get("target_alias")
    if target_alias not in {"Caster", "ModifierOwnerEntity"}:
        return f"trace_startup_effect_target_alias_not_admitted:{target_alias}"
    return ""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        converted = int(value)
        return converted if converted > 0 else None
    return None


def _wave_level_policy(
    *,
    stage_id: str,
    stage_row_index: int,
    level: int | None,
    hard_level_group: int | None,
    hard_level_profile: dict[str, Any] | None,
) -> dict[str, JSONValue]:
    blocked_reasons: list[str] = []
    if level is None:
        blocked_reasons.append("stage_level_missing")
    if hard_level_group is None:
        blocked_reasons.append("stage_hard_level_group_missing")
    if level is not None and hard_level_group is not None and hard_level_profile is None:
        blocked_reasons.append("stage_hard_level_profile_missing")
    ratios: dict[str, JSONValue] = {}
    if hard_level_profile is not None:
        for field_name, raw_key in (
            ("attack", "AttackRatio"),
            ("defense", "DefenceRatio"),
            ("max_hp", "HPRatio"),
            ("speed", "SpeedRatio"),
            ("max_toughness", "StanceRatio"),
        ):
            ratio = _required_number(hard_level_profile, raw_key)
            if ratio is None or ratio <= 0:
                blocked_reasons.append(f"stage_hard_level_ratio_missing:{raw_key}")
            else:
                ratios[field_name] = ratio
    blocked_reason = ";".join(dict.fromkeys(blocked_reasons))
    return {
        "kind": "stage_level_hard_level_group",
        "admission_status": "blocked" if blocked_reason else "executable",
        "blocked_reason": blocked_reason,
        "level": level,
        "hard_level_group": hard_level_group,
        "ratios": ratios,
        "source_trace": {
            "stage": {
                "source_path": "ExcelOutput/StageConfig.json",
                "raw_type": "StageConfig",
                "raw_id": stage_id,
                "evidence": {
                    "row_index": stage_row_index,
                    "level_field": "Level",
                    "hard_level_group_field": "HardLevelGroup",
                    "level": level,
                    "hard_level_group": hard_level_group,
                },
            },
            "hard_level_profile": {
                "source_path": str((hard_level_profile or {}).get("_v8_source_path") or ""),
                "raw_type": "HardLevelGroup",
                "raw_id": f"{hard_level_group}:{level}" if hard_level_group is not None and level is not None else "",
                "evidence": {
                    "row_index": (hard_level_profile or {}).get("_v8_row_index"),
                    "ratios": ratios,
                },
            },
        },
    }


def _wave_birth_template_id(stage_id: str, wave_index: int, position: int, monster_raw_id: str) -> str:
    return f"unit_birth_template:wave:{_safe_id(stage_id)}:{_safe_id(monster_raw_id or 'empty')}"


def _summoned_monster_birth_template_id(task_id: str, entry_index: int) -> str:
    return f"unit_birth_template:summoned_monster:{_safe_id(task_id)}:{entry_index}"


def _servant_birth_template_id(servant_id: str) -> str:
    return f"unit_birth_template:servant:{_safe_id(servant_id)}"


def _lower_unit_birth_templates(
    *,
    summon_monster_intents: list[SummonMonsterIntentIR],
    servant_definitions: list[ServantDefinitionIR],
    wave_definitions: list[WaveDefinitionIR],
    combatant_profiles: list[CombatantProfileIR],
    monster_data_cards: tuple[MonsterDataCardIR, ...] | list[MonsterDataCardIR],
    timeline_rules: list[TimelineRuleIR],
) -> list[UnitBirthTemplateIR]:
    profile_by_entity = {profile.entity_id: profile for profile in combatant_profiles}
    card_by_entity = {card.entity_ref: card for card in monster_data_cards}
    timeline_rule = next((rule for rule in timeline_rules if rule.coverage_status == "executable"), None)
    templates: list[UnitBirthTemplateIR] = []
    for intent in summon_monster_intents:
        for entry in intent.entries:
            templates.append(
                _summoned_monster_birth_template(
                    intent,
                    entry,
                    profile_by_entity.get(entry.monster_entity_ref),
                    card_by_entity.get(entry.monster_entity_ref),
                    timeline_rule,
                )
            )
    for definition in servant_definitions:
        templates.append(_servant_birth_template(definition, timeline_rule))
    for definition in wave_definitions:
        for entry in definition.entries:
            templates.append(
                _wave_enemy_birth_template(
                    definition,
                    entry,
                    profile_by_entity.get(entry.monster_entity_ref),
                    card_by_entity.get(entry.monster_entity_ref),
                    timeline_rule,
                )
            )
    return list({template.birth_template_id: template for template in templates}.values())


def _summoned_monster_birth_template(
    intent: SummonMonsterIntentIR,
    entry: SummonMonsterEntryIR,
    profile: CombatantProfileIR | None,
    card: MonsterDataCardIR | None,
    timeline_rule: TimelineRuleIR | None,
) -> UnitBirthTemplateIR:
    reasons: list[str] = []
    if intent.coverage_status != "executable":
        reasons.append(intent.blocked_reason or f"summon_monster_intent_not_executable:{intent.coverage_status}")
    if entry.coverage_status != "executable":
        reasons.append(entry.blocked_reason or f"summon_monster_entry_not_executable:{entry.coverage_status}")
    if profile is None or profile.coverage_status != "executable":
        reasons.append("summon_monster_combatant_profile_missing_or_blocked")
    if card is None:
        reasons.append("summon_monster_data_card_missing")
    if timeline_rule is None:
        reasons.append("summon_monster_timeline_rule_missing")
    if entry.level_policy.get("admission_status") != "executable" or (
        profile is not None and entry.level_policy.get("profile_id") != profile.profile_id
    ):
        reasons.append("summon_monster_level_policy_source_blocked")
    delay_ratio = _strict_json_number(intent.delay_policy.get("value"))
    if intent.delay_policy.get("admission_status") != "executable" or delay_ratio is None or delay_ratio < 0:
        reasons.append("summon_monster_delay_policy_source_blocked")
        delay_ratio = 0.0
    position_policy = entry.position_policy
    if position_policy.get("admission_status") != "executable":
        reasons.append(str(position_policy.get("blocked_reason") or "summon_monster_position_policy_blocked"))
    profile_values, profile_reasons = _birth_profile_values(profile)
    reasons.extend(profile_reasons)
    stat_resolutions = _birth_profile_stat_resolutions(entry, profile, profile_values)
    source_trace = entry.source.to_json()
    card_source = card.source.to_json() if card is not None else {}
    profile_source = profile.source.to_json() if profile is not None else {}
    timeline_source = timeline_rule.source.to_json() if timeline_rule is not None else {}
    location_type = str(position_policy.get("location_type") or "")
    unit_field_specs: dict[str, JSONValue] = {
        "side": "enemy",
        "template_id": entry.monster_entity_ref,
        "level": {"binding_kind": "owner_field", "field": "level"},
        "max_hp": profile_values.get("max_hp"),
        "hp": {"binding_kind": "copy_unit_field", "field": "max_hp"},
        "attack": profile_values.get("attack"),
        "defense": profile_values.get("defense"),
        "speed": profile_values.get("speed"),
        "energy": 0.0,
        "max_energy": 0.0,
        "toughness": profile_values.get("current_toughness"),
        "max_toughness": profile_values.get("max_toughness"),
        "action_value": {
            "binding_kind": "timeline_action_value",
            "speed_field": "speed",
            "base_action_gauge": timeline_rule.base_action_gauge if timeline_rule is not None else None,
            "multiplier": delay_ratio,
        },
    }
    flag_specs: dict[str, JSONValue] = {
        "position": {
            "binding_kind": "relative_owner_position",
            "location_type": location_type,
            "offset_request_field": "spawn_index",
        },
        "team_side": "enemy",
        "summon_kind": "summoned_monster",
        "wave_member_kind": "enemy_summon",
        "wave_clear_policy": entry.wave_clear_policy,
        "owner_id": {"binding_kind": "request_field", "field": "owner_id"},
        "summoner_id": {"binding_kind": "request_field", "field": "summoner_id"},
        "summon_intent_id": {"binding_kind": "request_field", "field": "source_id"},
        "summon_entry_id": {"binding_kind": "request_field", "field": "entry_id"},
        "summon_entry_index": {"binding_kind": "request_field", "field": "entry_index"},
        "summon_entry_copy_index": {"binding_kind": "request_field", "field": "copy_index"},
        "summon_spawn_index": {"binding_kind": "request_field", "field": "spawn_index"},
        "summon_entry_count": entry.count,
        "summon_source_trace": intent.source.to_json(),
        "summon_entry_source_trace": source_trace,
        "summon_position_policy": entry.position_policy,
        "summon_level_policy": entry.level_policy,
        "summon_value_resolutions": stat_resolutions,
        "summon_level_source_trace": profile_source,
        "summon_delay_policy": intent.delay_policy,
        "combatant_profile_id": profile.profile_id if profile is not None else "",
        "combatant_profile_source_trace": profile_source,
        "combatant_profile_coverage_status": profile.coverage_status if profile is not None else "blocked",
        "monster_data_card_id": card.card_id if card is not None else "",
        "monster_data_card_source_trace": card_source,
        "monster_passive_mechanism_slot_ids": list(card.passive_mechanism_slot_ids) if card is not None else [],
        "weaknesses": list(profile.weaknesses) if profile is not None else [],
        "debuff_resistances": list(profile.debuff_resistances) if profile is not None else [],
        "toughness_profile_source_trace": profile_source,
        "resistance_source_trace": profile_source,
        "status_resistance_source_trace": profile_source,
        "timeline_admitted": timeline_rule is not None,
        "summon_action_admitted": card is not None,
        "summon_action_admission": {
            "coverage_status": "executable" if card is not None else "blocked",
            "source_trace": {
                "summon_intent": intent.source.to_json(),
                "summon_entry": source_trace,
                "monster_data_card": card_source,
                "combatant_profile": profile_source,
            },
            "action_set_kind": "enemy_fixed_sequence",
            "monster_data_card_id": card.card_id if card is not None else "",
            "action_sequence_count": len(card.action_sequence) if card is not None else 0,
            "executable_action_sequence_count": sum(
                1
                for step in (card.action_sequence if card is not None else ())
                if isinstance(step, dict) and step.get("coverage_status") == "executable"
            ),
        },
        "lifecycle_source": {
            "admission_status": "executable",
            "presence": "field",
            "targetable": True,
            "actionable": card is not None,
            "timeline_admitted": timeline_rule is not None,
            "source_trace": {
                "summon_entry": source_trace,
                "monster_data_card": card_source,
                "combatant_profile": profile_source,
            },
        },
        "initial_action_value_source_trace": {
            "binding_kind": "timeline_trace",
            "timeline_rule_id": timeline_rule.timeline_rule_id if timeline_rule is not None else "",
            "timeline_rule_source": timeline_source,
            "speed_source": profile_source,
            "formula": timeline_rule.initial_action_value_rule if timeline_rule is not None else "",
            "multiplier": delay_ratio,
            "summon_delay_policy": intent.delay_policy,
            "summon_delay_application": "initial_action_value_full_av_times_delay_ratio",
        },
    }
    blocked_reason = ";".join(dict.fromkeys(reason for reason in reasons if reason))
    return UnitBirthTemplateIR(
        birth_template_id=entry.birth_template_id,
        spawn_kind="summoned_monster",
        entity_ref=entry.monster_entity_ref,
        unit_field_specs=unit_field_specs,
        flag_specs=flag_specs,
        resource_specs=_birth_profile_resources(profile),
        request_contract={
            "spawn_kind": "summoned_monster",
            "entity_ref": entry.monster_entity_ref,
            "source_id": intent.summon_intent_id,
            "entry_id": entry.entry_id,
            "owner_required": True,
            "summoner_matches_owner": True,
            "template_source_role": "entry",
        },
        source=entry.source,
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _servant_birth_template(
    definition: ServantDefinitionIR,
    timeline_rule: TimelineRuleIR | None,
) -> UnitBirthTemplateIR:
    reasons: list[str] = []
    if definition.coverage_status != "executable" or definition.representation != "unit":
        reasons.append(definition.blocked_reason or f"servant_definition_not_executable:{definition.coverage_status}")
    if timeline_rule is None:
        reasons.append("servant_timeline_rule_missing")
    components = definition.stat_source.get("components") if isinstance(definition.stat_source, dict) else None
    for key in ("hp_base", "hp_inherit", "speed_base", "speed_inherit", "base_aggro"):
        component = components.get(key) if isinstance(components, dict) else None
        value = _strict_json_number(component.get("value")) if isinstance(component, dict) else None
        if value is None:
            reasons.append(f"servant_birth_template_stat_component_missing:{key}")
    owner_sync_fields = (
        definition.stat_source.get("owner_sync_fields")
        if isinstance(definition.stat_source, dict)
        else None
    )
    for key in ("attack", "defense", "critical_chance", "critical_damage"):
        source = owner_sync_fields.get(key) if isinstance(owner_sync_fields, dict) else None
        if not isinstance(source, dict) or source.get("admission_status") != "executable":
            reasons.append(f"servant_birth_template_owner_sync_source_missing:{key}")
    source_trace = definition.source.to_json()
    timeline_source_trace = _birth_first_source_trace(definition.timeline_source, source_trace)
    lifecycle_source_trace = _birth_first_source_trace(definition.lifecycle_source, source_trace)
    action_set_trace = definition.action_set.get("source_trace") if isinstance(definition.action_set, dict) else None
    unit_field_specs: dict[str, JSONValue] = {
        "side": "summon",
        "template_id": definition.servant_ref,
        "level": {"binding_kind": "owner_field", "field": "level"},
        "max_hp": {
            "binding_kind": "owned_combatant_stat",
            "servant_definition_id": definition.servant_definition_id,
            "property_type": "max_hp",
        },
        "hp": {"binding_kind": "copy_unit_field", "field": "max_hp"},
        "attack": {
            "binding_kind": "owned_combatant_stat",
            "servant_definition_id": definition.servant_definition_id,
            "property_type": "attack",
        },
        "defense": {
            "binding_kind": "owned_combatant_stat",
            "servant_definition_id": definition.servant_definition_id,
            "property_type": "defense",
        },
        "speed": {
            "binding_kind": "owned_combatant_stat",
            "servant_definition_id": definition.servant_definition_id,
            "property_type": "speed",
        },
        "energy": {
            "binding_kind": "owned_combatant_stat",
            "servant_definition_id": definition.servant_definition_id,
            "property_type": "energy",
            "inactive_value": 0.0,
        },
        "max_energy": {
            "binding_kind": "owned_combatant_stat",
            "servant_definition_id": definition.servant_definition_id,
            "property_type": "max_energy",
            "inactive_value": 0.0,
        },
        "toughness": 0.0,
        "max_toughness": 0.0,
        "action_value": {
            "binding_kind": "timeline_action_value",
            "speed_field": "speed",
            "base_action_gauge": timeline_rule.base_action_gauge if timeline_rule is not None else None,
            "multiplier": 1.0,
        },
    }
    flag_specs: dict[str, JSONValue] = {
        "position": {"binding_kind": "owner_position"},
        "team_side": {"binding_kind": "owner_team_side"},
        "summon_kind": "servant",
        "owner_id": {"binding_kind": "request_field", "field": "owner_id"},
        "summoner_id": {"binding_kind": "request_field", "field": "summoner_id"},
        "owner_entity_ref": {"binding_kind": "owner_field", "field": "template_id"},
        "owner_relation": {
            "binding_kind": "owner_relation",
            "relations": [relation.to_json() for relation in definition.owner_relations],
        },
        "servant_definition_id": {"binding_kind": "request_field", "field": "source_id"},
        "servant_ref": definition.servant_ref,
        "owned_combatant_build_result": {
            "binding_kind": "owner_owned_combatant_build",
            "servant_definition_id": definition.servant_definition_id,
        },
        "summon_intent_id": {"binding_kind": "request_field", "field": "source_id"},
        "summon_source_trace": {
            "binding_kind": "request_field",
            "field": "source_trace",
        },
        "servant_definition_source_trace": source_trace,
        "stat_source": definition.stat_source,
        "timeline_source": definition.timeline_source,
        "lifecycle_source": definition.lifecycle_source,
        "servant_runtime_stat_values": {
            "binding_kind": "owned_combatant_runtime_stat_values",
            "servant_definition_id": definition.servant_definition_id,
        },
        "servant_damage_stat_admission": {
            "binding_kind": "owned_combatant_damage_stat_admission",
            "servant_definition_id": definition.servant_definition_id,
        },
        "timeline_admitted": timeline_rule is not None,
        "summon_action_admitted": definition.action_set.get("admission_status") == "executable",
        "summon_action_admission": {
            "coverage_status": definition.action_set.get("admission_status") or definition.action_set.get("coverage_status"),
            "source_trace": {
                "servant_definition": source_trace,
                "action_set_source_trace": list(action_set_trace) if isinstance(action_set_trace, list) else [],
            },
            "action_set": definition.action_set,
            "ability_graph_ids": list(definition.ability_graph_ids),
            "skipped_slots": definition.action_set.get("skipped_slots", [])
            if isinstance(definition.action_set, dict)
            else [],
        },
        "owner_death_policy": "remove",
        "owner_death_policy_admission": {
            "coverage_status": "executable",
            "remove_source_admitted": True,
            "lifecycle_source": definition.lifecycle_source,
        },
        "owner_death_policy_source_trace": lifecycle_source_trace,
        "initial_action_value_source_trace": {
            "binding_kind": "timeline_trace",
            "timeline_rule_id": timeline_rule.timeline_rule_id if timeline_rule is not None else "",
            "timeline_rule_source": timeline_rule.source.to_json() if timeline_rule is not None else {},
            "timeline_source": timeline_source_trace,
            "formula": timeline_rule.initial_action_value_rule if timeline_rule is not None else "",
            "multiplier": 1.0,
        },
        "servant_attack_defense_source_status": {
            "coverage_status": "executable",
            "source": "OwnedCombatantBuildAssemblyResult.stat_bindings",
            "required_property_types": ["attack", "defense"],
        },
    }
    blocked_reason = ";".join(dict.fromkeys(reason for reason in reasons if reason))
    return UnitBirthTemplateIR(
        birth_template_id=definition.birth_template_id,
        spawn_kind="servant",
        entity_ref=definition.servant_ref,
        unit_field_specs=unit_field_specs,
        flag_specs=flag_specs,
        resource_specs={
            property_type: {
                "binding_kind": "owned_combatant_stat",
                "servant_definition_id": definition.servant_definition_id,
                "property_type": property_type,
            }
            for property_type in (
                "base_aggro",
                "critical_chance",
                "critical_damage",
            )
        },
        request_contract={
            "spawn_kind": "servant",
            "entity_ref": definition.servant_ref,
            "source_id": definition.servant_definition_id,
            "entry_id": definition.servant_definition_id,
            "owner_required": True,
            "summoner_matches_owner": True,
            "owner_entity_refs": list(definition.owner_entity_refs),
            "template_source_role": "entry",
        },
        source=definition.source,
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _wave_enemy_birth_template(
    definition: WaveDefinitionIR,
    entry: WaveMonsterEntryIR,
    profile: CombatantProfileIR | None,
    card: MonsterDataCardIR | None,
    timeline_rule: TimelineRuleIR | None,
) -> UnitBirthTemplateIR:
    reasons: list[str] = []
    if definition.coverage_status != "executable":
        reasons.append(definition.blocked_reason or f"wave_definition_not_executable:{definition.coverage_status}")
    if entry.coverage_status != "executable":
        reasons.append(entry.blocked_reason or f"wave_entry_not_executable:{entry.coverage_status}")
    if definition.level_policy.get("admission_status") != "executable":
        reasons.append(str(definition.level_policy.get("blocked_reason") or "wave_stage_level_source_blocked"))
    if definition.level is None or definition.hard_level_group is None:
        reasons.append("wave_stage_level_source_missing")
    if profile is None or profile.coverage_status != "executable":
        reasons.append("wave_combatant_profile_missing_or_blocked")
    if card is None:
        reasons.append("wave_monster_data_card_missing")
    if timeline_rule is None:
        reasons.append("wave_timeline_rule_missing")
    profile_values, profile_reasons = _birth_profile_values(profile)
    reasons.extend(profile_reasons)
    ratios = definition.level_policy.get("ratios") if isinstance(definition.level_policy, dict) else None
    scaled_values: dict[str, float] = {}
    for field_name in ("max_hp", "attack", "defense", "speed", "max_toughness"):
        ratio = _strict_json_number(ratios.get(field_name)) if isinstance(ratios, dict) else None
        source_field = "max_toughness" if field_name == "max_toughness" else field_name
        base_value = _strict_json_number(profile_values.get(source_field))
        if ratio is None or ratio <= 0 or base_value is None:
            reasons.append(f"wave_stage_scaled_stat_source_missing:{field_name}")
        else:
            scaled_values[field_name] = base_value * ratio
    scaled_values["current_toughness"] = scaled_values.get("max_toughness", 0.0)
    profile_source = profile.source.to_json() if profile is not None else {}
    card_source = card.source.to_json() if card is not None else {}
    timeline_source = timeline_rule.source.to_json() if timeline_rule is not None else {}
    level_source_trace = definition.level_policy.get("source_trace") if isinstance(definition.level_policy, dict) else {}
    unit_field_specs: dict[str, JSONValue] = {
        "side": "enemy",
        "template_id": entry.monster_entity_ref,
        "level": definition.level,
        "max_hp": scaled_values.get("max_hp"),
        "hp": {"binding_kind": "copy_unit_field", "field": "max_hp"},
        "attack": scaled_values.get("attack"),
        "defense": scaled_values.get("defense"),
        "speed": scaled_values.get("speed"),
        "energy": 0.0,
        "max_energy": 0.0,
        "toughness": scaled_values.get("current_toughness"),
        "max_toughness": scaled_values.get("max_toughness"),
        "action_value": {
            "binding_kind": "timeline_action_value",
            "speed_field": "speed",
            "base_action_gauge": timeline_rule.base_action_gauge if timeline_rule is not None else None,
            "multiplier": 1.0,
        },
    }
    flag_specs: dict[str, JSONValue] = {
        "position": {"binding_kind": "request_field", "field": "position"},
        "wave_definition_id": {"binding_kind": "request_field", "field": "wave_definition_id"},
        "stage_id": definition.stage_id,
        "wave_index": {"binding_kind": "request_field", "field": "wave_index"},
        "wave_position": {"binding_kind": "request_field", "field": "position"},
        "wave_entry_id": {"binding_kind": "request_field", "field": "entry_id"},
        "wave_member_kind": "stage_wave_enemy",
        "wave_clear_policy": "counts",
        "wave_entry_source_trace": {"binding_kind": "request_field", "field": "entry_source_trace"},
        "wave_definition_source_trace": {"binding_kind": "request_field", "field": "source_trace"},
        "stage_level": definition.level,
        "hard_level_group": definition.hard_level_group,
        "stage_level_policy": definition.level_policy,
        "stage_level_source_trace": level_source_trace if isinstance(level_source_trace, dict) else {},
        "wave_stat_scaling": {
            "kind": "combatant_profile_times_stage_hard_level_ratios",
            "base_profile_values": profile_values,
            "ratios": ratios if isinstance(ratios, dict) else {},
            "resolved_values": scaled_values,
            "source_trace": {
                "combatant_profile": profile_source,
                "stage_level": level_source_trace if isinstance(level_source_trace, dict) else {},
            },
        },
        "combatant_profile_id": profile.profile_id if profile is not None else "",
        "combatant_profile_source_trace": profile_source,
        "combatant_profile_coverage_status": profile.coverage_status if profile is not None else "blocked",
        "monster_data_card_id": card.card_id if card is not None else "",
        "monster_data_card_source_trace": card_source,
        "monster_passive_mechanism_slot_ids": list(card.passive_mechanism_slot_ids) if card is not None else [],
        "weaknesses": list(profile.weaknesses) if profile is not None else [],
        "debuff_resistances": list(profile.debuff_resistances) if profile is not None else [],
        "initial_action_value_source_trace": {
            "binding_kind": "timeline_trace",
            "timeline_rule_id": timeline_rule.timeline_rule_id if timeline_rule is not None else "",
            "timeline_rule_source": timeline_source,
            "speed_source": {
                "combatant_profile": profile_source,
                "stage_level": level_source_trace if isinstance(level_source_trace, dict) else {},
            },
            "formula": timeline_rule.initial_action_value_rule if timeline_rule is not None else "",
            "multiplier": 1.0,
        },
    }
    blocked_reason = ";".join(dict.fromkeys(reason for reason in reasons if reason))
    return UnitBirthTemplateIR(
        birth_template_id=entry.birth_template_id,
        spawn_kind="wave_enemy",
        entity_ref=entry.monster_entity_ref,
        unit_field_specs=unit_field_specs,
        flag_specs=flag_specs,
        resource_specs=_birth_profile_resources(profile),
        request_contract={
            "spawn_kind": "wave_enemy",
            "entity_ref": entry.monster_entity_ref,
            "source_id": definition.wave_definition_id,
            "wave_definition_id": definition.wave_definition_id,
            "stage_id": definition.stage_id,
            "owner_required": False,
            "template_source_role": "source",
        },
        source=definition.source,
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _birth_profile_values(profile: CombatantProfileIR | None) -> tuple[dict[str, float], list[str]]:
    if profile is None:
        return {}, ["unit_birth_template_combatant_profile_missing"]
    values: dict[str, float] = {}
    reasons: list[str] = []
    for field_name in ("max_hp", "attack", "defense", "speed"):
        value = _strict_json_number(profile.base_stats.get(field_name))
        if value is None:
            reasons.append(f"unit_birth_template_profile_stat_missing:{field_name}")
        else:
            values[field_name] = value
    for field_name in ("current_toughness", "max_toughness"):
        value = _strict_json_number(profile.toughness_profile.get(field_name))
        if value is None:
            reasons.append(f"unit_birth_template_profile_toughness_missing:{field_name}")
        else:
            values[field_name] = value
    return values, reasons


def _birth_profile_resources(profile: CombatantProfileIR | None) -> dict[str, JSONValue]:
    if profile is None:
        return {}
    resources: dict[str, JSONValue] = {
        f"{damage_type}_resistance": float(value)
        for damage_type, value in profile.resistances.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if isinstance(profile.status_resistance, (int, float)) and not isinstance(profile.status_resistance, bool):
        resources["effect_resistance"] = float(profile.status_resistance)
    return resources


def _birth_profile_stat_resolutions(
    entry: SummonMonsterEntryIR,
    profile: CombatantProfileIR | None,
    values: dict[str, float],
) -> dict[str, JSONValue]:
    profile_source = profile.source.to_json() if profile is not None else {}
    source_trace = {"summon_entry": entry.source.to_json(), "combatant_profile": profile_source}
    result: dict[str, JSONValue] = {}
    for field_name in ("max_hp", "attack", "defense", "speed"):
        value = values.get(field_name)
        result[field_name] = {
            "ok": value is not None,
            "value": value,
            "binding_kind": "combatant_profile_base_stat",
            "source_trace": source_trace,
            "context_trace": {
                "combatant_profile_id": profile.profile_id if profile is not None else "",
                "available_keys": ["combatant_profile"] if profile is not None else [],
            },
            "blocked_reason": "" if value is not None else f"combatant_profile_base_stat_missing:{field_name}",
            "request": {
                "binding_kind": "combatant_profile_base_stat",
                "field_name": field_name,
                "required_context_keys": ["combatant_profile"],
            },
            "delegate_resolution": {
                "value_source": f"CombatantProfileIR.base_stats.{field_name}",
                "profile_id": profile.profile_id if profile is not None else "",
            },
            "context_keys": ["combatant_profile"] if profile is not None else [],
        }
    return result


def _birth_first_source_trace(source: dict[str, JSONValue], fallback: dict[str, JSONValue]) -> dict[str, JSONValue]:
    traces = source.get("source_trace") if isinstance(source, dict) else None
    if isinstance(traces, list) and traces and isinstance(traces[0], dict):
        return dict(traces[0])
    if isinstance(traces, dict):
        return dict(traces)
    return dict(fallback)


def _strict_json_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _trace_startup_dynamic_binding_admission(
    standard: object,
    semantics: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    if not isinstance(standard, dict):
        return {"admission_status": "blocked", "blocked_reason": "trace_startup_standard_payload_missing"}
    requests = standard.get("dynamic_value_requests")
    if not isinstance(requests, dict) or not requests:
        return {"admission_status": "not_applicable", "reason": "no_dynamic_value_requests"}
    configured_bindings = semantics.get("dynamic_value_bindings")
    configured_by_hash = configured_bindings.get("by_hash") if isinstance(configured_bindings, dict) else None
    if not isinstance(configured_by_hash, dict) or not configured_by_hash:
        return {
            "admission_status": "blocked",
            "blocked_reason": "trace_skill_tree_dynamic_value_bindings_missing",
        }
    params = tuple(_number_items(semantics.get("param_values")))
    bindings: list[dict[str, JSONValue]] = []
    for name, request in requests.items():
        if not isinstance(request, dict):
            continue
        raw_hash = request.get("hash")
        if raw_hash is None:
            return {
                "admission_status": "blocked",
                "blocked_reason": "trace_dynamic_value_request_hash_missing",
                "request_name": str(name),
            }
        configured = configured_by_hash.get(str(raw_hash))
        if not isinstance(configured, dict):
            return {
                "admission_status": "blocked",
                "blocked_reason": "trace_dynamic_value_binding_hash_missing",
                "request_name": str(name),
                "hash": str(raw_hash),
            }
        param_index = configured.get("param_index")
        if not isinstance(param_index, int):
            return {
                "admission_status": "blocked",
                "blocked_reason": "trace_dynamic_value_binding_param_index_missing",
                "request_name": str(name),
                "hash": str(raw_hash),
                "binding": _json_safe(configured),
            }
        if param_index < 0 or param_index >= len(params):
            return {
                "admission_status": "blocked",
                "blocked_reason": "trace_dynamic_value_binding_param_index_out_of_range",
                "request_name": str(name),
                "hash": str(raw_hash),
                "param_index": param_index,
                "param_count": len(params),
            }
        bindings.append(
            {
                "name": str(name),
                "hash": str(raw_hash),
                "param_index": param_index,
                "value": float(params[param_index]),
                "binding_source_kind": "character_config_skill_tree_param_read_info",
                "binding_source": _json_safe(configured),
            }
        )
    return {
        "admission_status": "executable",
        "source_kind": "trace_skill_tree_param_to_startup_ability_dynamic_value_request",
        "bindings": bindings,
    }


def _admit_passive_startup_slots(
    slots: list[PassiveMechanismSlotIR],
    *,
    standalone_graphs: list[StandaloneAbilityGraphIR],
    ability_tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    triggers: list[TriggerIR],
) -> list[PassiveMechanismSlotIR]:
    graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]] = {}
    for graph in standalone_graphs:
        graphs_by_name.setdefault(graph.ability_name, []).append(graph)
    tasks_by_phase: dict[str, list[AbilityTaskIR]] = {}
    for task in ability_tasks:
        tasks_by_phase.setdefault(task.phase_id, []).append(task)
    effects_by_id = {effect.effect_id: effect for effect in effects}
    modifiers_with_triggers = _modifier_names_with_triggers(triggers)
    admitted: list[PassiveMechanismSlotIR] = []
    for slot in slots:
        if slot.mechanism_kind != "monster_ability_list_passive":
            admitted.append(slot)
            continue
        admitted.append(
            _admit_passive_startup_slot(
                slot,
                graphs_by_name=graphs_by_name,
                tasks_by_phase=tasks_by_phase,
                effects_by_id=effects_by_id,
                modifiers_with_triggers=modifiers_with_triggers,
            )
        )
    return admitted


def _admit_passive_startup_slot(
    slot: PassiveMechanismSlotIR,
    *,
    graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]],
    tasks_by_phase: dict[str, list[AbilityTaskIR]],
    effects_by_id: dict[str, EffectIR],
    modifiers_with_triggers: set[str],
) -> PassiveMechanismSlotIR:
    semantics = dict(slot.semantics)
    ability_name = str(semantics.get("ability_name") or slot.linked_ir_ids.get("ability_name") or "")
    if slot.coverage_status == "blocked":
        return _passive_startup_blocked_slot(
            slot,
            slot.blocked_reason or "monster_passive_slot_not_lowered",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": slot.blocked_reason or "monster_passive_slot_not_lowered",
                    "ability_name": ability_name,
                },
            },
        )
    if not ability_name:
        return _passive_startup_blocked_slot(slot, "monster_passive_ability_name_missing", semantics)

    expected_path = str(slot.linked_ir_ids.get("ability_file_path") or "")
    graph_candidates = tuple(sorted(graphs_by_name.get(ability_name, ()), key=lambda item: item.standalone_ability_graph_id))
    if expected_path:
        graph_candidates = tuple(graph for graph in graph_candidates if graph.source.source_path == expected_path)
    executable_graphs = tuple(
        graph for graph in graph_candidates if graph.coverage_status == "executable" and graph.source_mode == "mainline_monster"
    )
    if len(executable_graphs) != 1:
        reason = "monster_passive_startup_graph_missing_or_ambiguous"
        if graph_candidates and not executable_graphs:
            reason = "monster_passive_startup_graph_not_executable"
        return _passive_startup_blocked_slot(
            slot,
            reason,
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": reason,
                    "ability_name": ability_name,
                    "expected_ability_file_path": expected_path,
                    "candidate_graph_ids": [graph.standalone_ability_graph_id for graph in graph_candidates],
                    "candidate_graph_statuses": [graph.coverage_status for graph in graph_candidates],
                    "candidate_graph_source_modes": [graph.source_mode for graph in graph_candidates],
                },
            },
        )
    graph = executable_graphs[0]
    root_on_start_tasks = tuple(
        task
        for phase_id in graph.phase_ids
        for task in tasks_by_phase.get(phase_id, ())
        if task.callback_kind == "OnStart" and not task.parent_task_id
    )
    unadmitted_root_tasks = tuple(
        task for task in root_on_start_tasks if task.opcode != "AddModifier" or not task.effect_id
    )
    if unadmitted_root_tasks:
        reason = "monster_passive_startup_root_on_start_has_unadmitted_tasks"
        return _passive_startup_blocked_slot(
            slot,
            reason,
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": reason,
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                    "blocked_tasks": [
                        {
                            "task_id": task.task_id,
                            "opcode": task.opcode,
                            "effect_id": task.effect_id,
                            "blocked_reason": f"root_on_start_task_not_admitted:{task.opcode}",
                        }
                        for task in unadmitted_root_tasks
                    ],
                },
            },
        )

    candidate_tasks = tuple(
        task
        for task in root_on_start_tasks
        if task.opcode == "AddModifier" and task.effect_id
    )
    if not candidate_tasks:
        return _passive_startup_blocked_slot(
            slot,
            "monster_passive_startup_on_start_add_modifier_missing",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": "monster_passive_startup_on_start_add_modifier_missing",
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                },
            },
        )

    admitted_tasks: list[dict[str, JSONValue]] = []
    blocked_tasks: list[dict[str, JSONValue]] = []
    for task in candidate_tasks:
        effect = effects_by_id.get(task.effect_id)
        if effect is None:
            blocked_tasks.append({"task_id": task.task_id, "blocked_reason": "monster_passive_startup_effect_missing"})
            continue
        effect_reason = _passive_startup_effect_blocked_reason(effect, modifiers_with_triggers)
        if effect_reason:
            blocked_tasks.append(
                {
                    "task_id": task.task_id,
                    "effect_id": effect.effect_id,
                    "blocked_reason": effect_reason,
                    "effect_coverage_status": effect.coverage_status,
                }
            )
            continue
        admitted_tasks.append({"task_id": task.task_id, "effect_id": effect.effect_id})
    if not admitted_tasks:
        return _passive_startup_blocked_slot(
            slot,
            "monster_passive_startup_no_admitted_on_start_add_modifier",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": "monster_passive_startup_no_admitted_on_start_add_modifier",
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                    "blocked_tasks": blocked_tasks,
                },
            },
        )
    return replace(
        slot,
        linked_ir_ids={
            **slot.linked_ir_ids,
            "standalone_ability_graph_id": graph.standalone_ability_graph_id,
            "admitted_task_ids": [str(item["task_id"]) for item in admitted_tasks],
            "admitted_effect_ids": [str(item["effect_id"]) for item in admitted_tasks],
        },
        semantics={
            **semantics,
            "startup_admission": {
                "admission_status": "executable",
                "startup_kind": "monster_passive_on_start_add_modifier",
                "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                "admitted_tasks": admitted_tasks,
                "blocked_tasks": blocked_tasks,
                "event_trigger_execution_admitted": False,
            },
        },
        activation={
            **slot.activation,
            "kind": "monster_passive_startup_ability",
        },
        coverage_status="executable",
        blocked_reason="",
    )


def _passive_startup_blocked_slot(
    slot: PassiveMechanismSlotIR,
    reason: str,
    semantics: dict[str, JSONValue],
) -> PassiveMechanismSlotIR:
    return replace(slot, semantics=semantics, coverage_status="blocked", blocked_reason=reason)


def _passive_startup_effect_blocked_reason(effect: EffectIR, modifiers_with_triggers: set[str]) -> str:
    if effect.opcode != "AddModifier":
        return f"monster_passive_startup_effect_opcode_not_add_modifier:{effect.opcode}"
    if effect.coverage_status != "executable":
        return f"monster_passive_startup_effect_not_executable:{effect.coverage_status}"
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return "monster_passive_startup_effect_standard_payload_missing"
    modifier_name = standard.get("modifier_name")
    if not isinstance(modifier_name, str) or not modifier_name:
        return "monster_passive_startup_effect_modifier_name_missing"
    target_alias = standard.get("target_alias")
    if target_alias not in {"Caster", "ModifierOwnerEntity"}:
        return f"monster_passive_startup_effect_target_alias_not_admitted:{target_alias}"
    requests = standard.get("dynamic_value_requests")
    if requests:
        return "monster_passive_startup_dynamic_value_request_not_admitted"
    if modifier_name in modifiers_with_triggers:
        return "monster_passive_startup_modifier_has_event_triggers"
    return ""


def _modifier_names_with_triggers(triggers: list[TriggerIR]) -> set[str]:
    return {
        str(trigger.source.raw_id)
        for trigger in triggers
        if isinstance(trigger.source.raw_id, str) and trigger.source.raw_id
    }


def _attach_character_runtime_mechanism_slots(
    cards: list[CharacterDataCardIR],
    slots: list[CharacterMechanismSlotIR],
) -> list[CharacterDataCardIR]:
    slot_ids_by_card: dict[str, list[str]] = {}
    for slot in slots:
        slot_ids_by_card.setdefault(slot.character_data_card_id, []).append(slot.mechanism_slot_id)
    updated: list[CharacterDataCardIR] = []
    for card in cards:
        existing = list(card.mechanism_slot_ids)
        existing.extend(slot_ids_by_card.get(card.card_id, ()))
        updated.append(replace(card, mechanism_slot_ids=tuple(sorted(dict.fromkeys(existing)))))
    return updated


def _dedupe_character_mechanism_slots(slots: list[CharacterMechanismSlotIR]) -> list[CharacterMechanismSlotIR]:
    deduped: dict[str, CharacterMechanismSlotIR] = {}
    for slot in slots:
        deduped[slot.mechanism_slot_id] = slot
    return list(deduped.values())


def _ability_file_from_action_binding(binding: ActionAbilityBindingIR) -> str:
    for value in (
        binding.config_source.get("ability_file") if isinstance(binding.config_source, dict) else None,
        binding.config_source.get("ability_file_path") if isinstance(binding.config_source, dict) else None,
        binding.source.evidence.get("ability_file") if isinstance(binding.source.evidence, dict) else None,
        binding.source.evidence.get("ability_file_path") if isinstance(binding.source.evidence, dict) else None,
    ):
        if isinstance(value, str) and value:
            return value
    return ""


def merge_identical_ir_items(
    items,
    identity_field: str,
    *,
    item_kind: str = "ir_item",
) -> tuple[Any, ...]:
    """Merge exact duplicates while rejecting identity collisions."""

    deduped: dict[str, Any] = {}
    for item in items:
        if not hasattr(item, identity_field):
            raise TypeError(
                f"{item_kind} has no identity field {identity_field!r}"
            )
        identity = str(getattr(item, identity_field))
        existing = deduped.get(identity)
        if existing is None:
            deduped[identity] = item
            continue
        if existing != item:
            raise IRIdentityConflictError(
                item_kind=item_kind,
                identity_field=identity_field,
                identity=identity,
            )
    return tuple(deduped.values())


def _dedupe_entities(entities: list[RuleEntity]) -> dict[str, RuleEntity]:
    return {
        entity.entity_id: entity
        for entity in merge_identical_ir_items(
            entities,
            "entity_id",
            item_kind="entity",
        )
    }


def _dedupe_target_expressions(expressions: list[TargetExpressionIR]) -> dict[str, TargetExpressionIR]:
    return {
        expression.target_expression_id: expression
        for expression in merge_identical_ir_items(
            expressions,
            "target_expression_id",
            item_kind="target_expression",
        )
    }


def _modifier_definition_entity(
    relative_path: str,
    map_name: str,
    modifier_name: str,
    modifier: dict[str, Any],
    *,
    source_context: dict[str, Any] | None = None,
    dynamic_key_hash_bindings: dict[str, dict[str, Any]] | None = None,
    addition_effect_ids: tuple[str, ...] = (),
) -> RuleEntity:
    source_context = source_context or {}
    public_source_context = {
        key: value
        for key, value in source_context.items()
        if not str(key).startswith("_")
    }
    source = IRSource(
        source_path=relative_path,
        raw_type=map_name,
        raw_id=modifier_name,
        evidence={
            "modifier_name": modifier_name,
            "map_name": map_name,
            "definition_kind": "modifier_definition",
            **_json_safe(public_source_context),
        },
    )
    dynamic_value_bindings = _dynamic_value_bindings(
        modifier.get("DynamicValues")
    )
    modifier_dynamic_keys = _modifier_callback_dynamic_keys(modifier)
    inherited_bindings = _dynamic_value_bindings(
        source_context.get("_ability_dynamic_values")
    )
    inherited_by_hash = inherited_bindings.get("by_hash")
    callback_by_hash = _callback_dynamic_hashes(modifier).get("by_hash")
    referenced_hashes = {
        str(hash_key)
        for hash_key in (
            callback_by_hash.keys() if isinstance(callback_by_hash, dict) else ()
        )
    }
    referenced_hashes.update(
        str(_tbgd_dynamic_key_hash(name)) for name in modifier_dynamic_keys
    )
    local_by_hash = dynamic_value_bindings.get("by_hash")
    if not isinstance(local_by_hash, dict):
        local_by_hash = {}
        dynamic_value_bindings["by_hash"] = local_by_hash
    modifier_json_path = str(source_context.get("json_path") or "")
    for hash_key, binding in local_by_hash.items():
        if not isinstance(binding, dict):
            continue
        binding["source_scope"] = "modifier_dynamic_values"
        binding["source_json_path"] = (
            f"{modifier_json_path}.DynamicValues.Floats[{hash_key}]"
            if modifier_json_path
            else str(binding.get("raw_path") or "")
        )
    for hash_key, binding in (
        inherited_by_hash.items() if isinstance(inherited_by_hash, dict) else ()
    ):
        if str(hash_key) not in referenced_hashes or str(hash_key) in local_by_hash:
            continue
        if not isinstance(binding, dict):
            continue
        local_by_hash[str(hash_key)] = {
            **_json_safe(binding),
            "source_scope": "ability_dynamic_values",
            "source_json_path": str(
                source_context.get("_ability_dynamic_values_json_path") or ""
            ),
        }
    modifier_dynamic_names = set(modifier_dynamic_keys)
    for name, binding in (
        dynamic_key_hash_bindings.items()
        if isinstance(dynamic_key_hash_bindings, dict)
        else ()
    ):
        hashes = binding.get("hashes") if isinstance(binding, dict) else None
        if (
            isinstance(hashes, (list, tuple))
            and len(hashes) == 1
            and str(hashes[0]) in local_by_hash
        ):
            modifier_dynamic_names.add(name)
    dynamic_value_bindings["by_name"] = {
        name: _json_safe(dynamic_key_hash_bindings[name])
        for name in sorted(modifier_dynamic_names)
        if dynamic_key_hash_bindings is not None
        and name in dynamic_key_hash_bindings
    }
    fields = {
        "modifier_name": modifier_name,
        "map_name": map_name,
        "stacking": _json_safe(modifier.get("Stacking")),
        "lifetime": _json_safe(modifier.get("LifeTime")),
        "lifetime_expr": _numeric_expr_summary(modifier.get("LifeTime")),
        "life_step_moment": _value_field(modifier.get("LifeStepMoment")),
        "duration_admission": _duration_admission_payload(
            _numeric_expr_summary(modifier.get("LifeTime")),
            _value_field(modifier.get("LifeStepMoment")),
        ),
        "behavior_flags": _json_safe(modifier.get("BehaviorFlagList", [])),
        "dynamic_values": _json_safe(modifier.get("DynamicValues", {})),
        "dynamic_value_bindings": dynamic_value_bindings,
        "callback_dynamic_hashes": _callback_dynamic_hashes(modifier),
        "callback_events": _callback_events(modifier),
        "stack_properties": _stack_property_summaries(modifier),
        "addition_effect_ids": list(addition_effect_ids),
    }
    return RuleEntity(
        entity_id=f"modifier_definition:{modifier_name}:{_safe_id(relative_path)}:{_safe_id(map_name)}",
        entity_type="modifier_definition",
        fields=fields,
        source=source,
        coverage_status="lowered",
    )


def _modifier_addition_effects(
    relative_path: str,
    map_name: str,
    modifier_name: str,
    modifier: dict[str, Any],
    *,
    source_context: dict[str, Any],
) -> tuple[list[EffectIR], list[TargetExpressionIR]]:
    """Lower source-backed AdditionConfig sub-modifiers as attached effects."""

    addition = modifier.get("AdditionConfig")
    sub_modifiers = (
        addition.get("SubModifierList") if isinstance(addition, dict) else None
    )
    if not isinstance(sub_modifiers, list):
        return [], []
    effects: list[EffectIR] = []
    target_expressions: list[TargetExpressionIR] = []
    base_path = str(source_context.get("json_path") or "")
    for index, raw in enumerate(sub_modifiers):
        if not isinstance(raw, dict):
            continue
        sub_modifier_name = raw.get("Name")
        target_type = raw.get("TargetType")
        if not isinstance(sub_modifier_name, str) or not sub_modifier_name:
            continue
        source_json_path = f"{base_path}.AdditionConfig.SubModifierList[{index}]"
        halo_present = "IsHaloStatus" in raw
        halo_raw = raw.get("IsHaloStatus")
        halo_value = halo_raw if isinstance(halo_raw, bool) else False
        halo_blocked_reason = (
            ""
            if not halo_present or isinstance(halo_raw, bool)
            else "modifier_addition_is_halo_status_type_invalid"
        )
        alive_only_raw = raw.get("AliveOnly")
        alive_only_value, alive_only_reason = _addition_alive_only_value(
            alive_only_raw,
            present="AliveOnly" in raw,
        )
        if halo_value and alive_only_reason:
            halo_blocked_reason = alive_only_reason
        effect_id = (
            "effect:modifier_addition:"
            f"{_safe_id(relative_path)}:{_safe_id(map_name)}:"
            f"{_safe_id(modifier_name)}:{index}"
        )
        source = IRSource(
            source_path=relative_path,
            raw_type="ModifierAdditionConfig",
            raw_id=f"{modifier_name}:{sub_modifier_name}:{index}",
            evidence={
                **_json_safe(source_context),
                "definition_kind": "modifier_addition_sub_modifier",
                "parent_modifier_name": modifier_name,
                "sub_modifier_name": sub_modifier_name,
                "sub_modifier_index": index,
                "json_path": source_json_path,
                "target_json_path": f"{source_json_path}.TargetType",
                "is_halo_status": halo_raw,
                "is_halo_status_json_path": (
                    f"{source_json_path}.IsHaloStatus" if halo_present else ""
                ),
                "alive_only": alive_only_raw,
                "alive_only_json_path": (
                    f"{source_json_path}.AliveOnly"
                    if "AliveOnly" in raw
                    else ""
                ),
            },
        )
        task_like = {
            "$type": "RPG.GameCore.AddModifier",
            "ModifierName": sub_modifier_name,
            "TargetType": target_type,
            **{
                field_name: raw[field_name]
                for field_name in (
                    "DynamicValues",
                    "LifeTime",
                    "LifeStepMoment",
                    "LayerAddWhenStack",
                    "MaxLayer",
                    "Chance",
                )
                if field_name in raw
            },
        }
        payload = _effect_payload(task_like, "AddModifier", modifier_name)
        payload, expressions = _attach_target_expressions_to_effect_payload(
            payload,
            task_like,
            effect_id=effect_id,
            source=source,
        )
        standard = payload.get("standard")
        if isinstance(standard, dict):
            payload["standard"] = {
                **standard,
                "addition_parent_modifier_name": modifier_name,
                "addition_source_json_path": source_json_path,
                "is_halo_status": halo_value,
                "is_halo_status_present": halo_present,
                "is_halo_status_source_json_path": (
                    f"{source_json_path}.IsHaloStatus" if halo_present else ""
                ),
                "alive_only": alive_only_value,
                "alive_only_raw": _json_safe(alive_only_raw),
                "alive_only_source_json_path": (
                    f"{source_json_path}.AliveOnly"
                    if "AliveOnly" in raw
                    else ""
                ),
                "halo_admission_status": (
                    "blocked"
                    if halo_blocked_reason
                    else ("executable" if halo_value else "ordinary")
                ),
                "halo_blocked_reason": halo_blocked_reason,
            }
        effects.append(
            EffectIR(
                effect_id=effect_id,
                opcode="AddModifier",
                payload=payload,
                source=source,
                coverage_status=(
                    "blocked"
                    if halo_blocked_reason
                    else _effect_coverage_status("AddModifier", payload)
                ),
                owner_modifier_name=modifier_name,
                link_blocked_reason=halo_blocked_reason,
            )
        )
        target_expressions.extend(expressions)
    return effects, target_expressions


def _addition_alive_only_value(
    value: Any,
    *,
    present: bool,
) -> tuple[bool | None, str]:
    if not present:
        return None, ""
    if isinstance(value, bool):
        return value, ""
    if value == "True":
        return True, ""
    if value == "False":
        return False, ""
    return None, "modifier_addition_alive_only_value_invalid"


def _callback_events(modifier: dict[str, Any]) -> list[str]:
    events: list[str] = []
    callbacks = modifier.get("_CallbackList")
    if not isinstance(callbacks, list):
        return events
    for callback in callbacks:
        if isinstance(callback, dict):
            events.append(str(callback.get("Event") or "UnknownEvent"))
    return events


def _callback_dynamic_hashes(modifier: dict[str, Any]) -> dict[str, Any]:
    callbacks = modifier.get("_CallbackList")
    hashes: dict[str, dict[str, Any]] = {}
    if not isinstance(callbacks, list):
        return {"by_hash": {}}

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            dynamic_hashes = value.get("DynamicHashes")
            if isinstance(dynamic_hashes, list):
                for index, raw_hash in enumerate(dynamic_hashes):
                    if isinstance(raw_hash, int):
                        hashes.setdefault(
                            str(raw_hash),
                            {
                                "hash": str(raw_hash),
                                "raw_path": f"{path}.DynamicHashes[{index}]",
                                "source_kind": "modifier_callback_dynamic_hash",
                            },
                        )
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(callbacks, "_CallbackList")
    return {"by_hash": hashes}


def _document_dynamic_key_hash_bindings(
    modifier_maps: list[tuple[str, str, dict[str, Any], dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    modifier_rows: list[dict[str, Any]] = []
    for map_name, modifier_name, modifier, context in modifier_maps:
        names = sorted(_modifier_callback_dynamic_keys(modifier))
        bindings = _dynamic_value_bindings(modifier.get("DynamicValues"))
        by_hash = bindings.get("by_hash")
        internal_hashes = sorted(
            str(hash_key)
            for hash_key, binding in (
                by_hash.items() if isinstance(by_hash, dict) else ()
            )
            if isinstance(binding, dict)
            and isinstance(binding.get("read_info"), dict)
            and str(binding["read_info"].get("Type") or "") == "None"
        )
        callback_bindings = _callback_dynamic_hashes(modifier).get("by_hash")
        callback_hashes = sorted(
            str(hash_key)
            for hash_key, binding in (
                callback_bindings.items()
                if isinstance(callback_bindings, dict)
                else ()
            )
            if isinstance(binding, dict)
        )
        modifier_rows.append(
            {
                "names": names,
                "named_inputs": sorted(
                    _modifier_callback_named_dynamic_inputs(modifier)
                ),
                "internal_hashes": internal_hashes,
                "callback_hashes": callback_hashes,
                "source_modifier_name": modifier_name,
                "source_map_name": map_name,
                "source_json_path": str(context.get("json_path") or ""),
            }
        )
        for name in names:
            computed_hash = str(_tbgd_dynamic_key_hash(name))
            if (
                computed_hash not in internal_hashes
                and computed_hash not in callback_hashes
            ):
                continue
            candidates.setdefault(name, []).append(
                {
                    "dynamic_key": name,
                    "hashes": [computed_hash],
                    "source_kind": (
                        "tbgd_dynamic_key_hash_matches_modifier_slot"
                        if computed_hash in internal_hashes
                        else "tbgd_dynamic_key_hash_matches_modifier_callback"
                    ),
                    "source_modifier_name": modifier_name,
                    "source_map_name": map_name,
                    "source_json_path": str(context.get("json_path") or ""),
                    "callback_hash_path": (
                        callback_bindings[computed_hash].get("raw_path")
                        if computed_hash in callback_hashes
                        and isinstance(callback_bindings, dict)
                        and isinstance(callback_bindings.get(computed_hash), dict)
                        else ""
                    ),
                }
            )
        if len(names) != 1 or len(internal_hashes) != 1:
            continue
        name = names[0]
        candidates.setdefault(name, []).append(
            {
                "dynamic_key": name,
                "hashes": internal_hashes,
                "source_kind": "unique_name_and_internal_hash_in_modifier",
                "source_modifier_name": modifier_name,
                "source_map_name": map_name,
                "source_json_path": str(context.get("json_path") or ""),
            }
        )
    # AddModifier.DynamicValues names occur on the source modifier, while the
    # destination modifier declares only hashed Type=None slots.  Bind across
    # the ability document only when the TBGD name hash identifies one unique
    # declared destination slot; input order is never used as evidence.
    named_inputs_by_hash: dict[str, set[str]] = {}
    for row in modifier_rows:
        for name in row["named_inputs"]:
            named_inputs_by_hash.setdefault(
                str(_tbgd_dynamic_key_hash(name)),
                set(),
            ).add(name)
    for row in modifier_rows:
        for name in row["named_inputs"]:
            computed_hash = str(_tbgd_dynamic_key_hash(name))
            target_rows = tuple(
                target_row
                for target_row in modifier_rows
                if computed_hash in target_row["internal_hashes"]
            )
            target_identities = sorted(
                {
                (
                    target_row["source_modifier_name"],
                    target_row["source_map_name"],
                    target_row["source_json_path"],
                )
                for target_row in target_rows
                }
            )
            if (
                not target_identities
                or named_inputs_by_hash.get(computed_hash) != {name}
            ):
                continue
            candidates.setdefault(name, []).append(
                {
                    "dynamic_key": name,
                    "hashes": [computed_hash],
                    "source_kind": "named_dynamic_input_matches_unique_document_slot",
                    "source_modifier_name": row["source_modifier_name"],
                    "source_map_name": row["source_map_name"],
                    "source_json_path": row["source_json_path"],
                    "target_modifier_identities": [
                        list(identity) for identity in target_identities
                    ],
                }
            )
    resolved: dict[str, dict[str, Any]] = {}
    for name, rows in sorted(candidates.items()):
        hashes = {
            hash_key
            for row in rows
            for hash_key in row.get("hashes", ())
        }
        if len(hashes) != 1:
            continue
        resolved[name] = {
            "dynamic_key": name,
            "hashes": sorted(hashes),
            "source_kind": "document_unique_dynamic_key_hash_evidence",
            "evidence_count": len(rows),
            "evidence": rows,
        }

    # Multi-slot modifiers do not repeat the string name beside every hashed
    # read.  Once single-slot evidence has fixed the shared document names, a
    # modifier with one remaining named writer and one remaining Type=None slot
    # is an exact one-to-one relation.  Resolve those residual relations
    # iteratively and retain the raw modifier rows used as evidence.
    while True:
        resolved_hashes = {
            str(hash_key)
            for binding in resolved.values()
            for hash_key in binding.get("hashes", ())
        }
        residual_candidates: dict[str, list[dict[str, Any]]] = {}
        for row in modifier_rows:
            unresolved_names = [
                name for name in row["names"] if name not in resolved
            ]
            remaining_hashes = [
                hash_key
                for hash_key in row["internal_hashes"]
                if hash_key not in resolved_hashes
            ]
            if len(unresolved_names) != 1 or len(remaining_hashes) != 1:
                continue
            name = unresolved_names[0]
            residual_candidates.setdefault(name, []).append(
                {
                    "dynamic_key": name,
                    "hashes": remaining_hashes,
                    "source_kind": "modifier_residual_name_slot_bijection",
                    "source_modifier_name": row["source_modifier_name"],
                    "source_map_name": row["source_map_name"],
                    "source_json_path": row["source_json_path"],
                    "eliminated_document_hashes": sorted(
                        set(row["internal_hashes"]) - set(remaining_hashes)
                    ),
                }
            )
        additions: dict[str, dict[str, Any]] = {}
        for name, rows in sorted(residual_candidates.items()):
            hashes = {
                hash_key
                for row in rows
                for hash_key in row.get("hashes", ())
            }
            if len(hashes) != 1:
                continue
            additions[name] = {
                "dynamic_key": name,
                "hashes": sorted(hashes),
                "source_kind": "document_residual_dynamic_key_hash_evidence",
                "evidence_count": len(rows),
                "evidence": rows,
            }
        if not additions:
            break
        resolved.update(additions)
    return resolved


def _tbgd_dynamic_key_hash(value: str) -> int:
    return tbgd_dynamic_key_hash(value)


def _modifier_callback_dynamic_keys(modifier: dict[str, Any]) -> set[str]:
    names: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for writer_field in ("DynamicKey", "DynamicFloatSet"):
                if writer_field not in value:
                    continue
                raw_name = _value_field(value.get(writer_field))
                if isinstance(raw_name, str) and raw_name:
                    names.add(raw_name)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    callbacks = modifier.get("_CallbackList")
    if isinstance(callbacks, list):
        walk(callbacks)
    return names


def _modifier_callback_named_dynamic_inputs(
    modifier: dict[str, Any],
) -> set[str]:
    names: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            named_dynamic_values = value.get("DynamicValues")
            if isinstance(named_dynamic_values, dict):
                names.update(
                    str(name)
                    for name in named_dynamic_values
                    if isinstance(name, str) and name
                )
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    callbacks = modifier.get("_CallbackList")
    if isinstance(callbacks, list):
        walk(callbacks)
    return names


def _stack_property_summaries(modifier: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    callbacks = modifier.get("_CallbackList")
    if not isinstance(callbacks, list):
        return summaries
    for callback_index, callback in enumerate(callbacks):
        if not isinstance(callback, dict):
            continue
        event = str(callback.get("Event") or "UnknownEvent")
        tasks = callback.get("CallbackConfig")
        if not isinstance(tasks, list):
            continue
        for task_index, task in enumerate(tasks):
            if not isinstance(task, dict) or _short_gamecore_type(task.get("$type")) != "StackProperty":
                continue
            summaries.append(
                {
                    "event": event,
                    "callback_index": callback_index,
                    "task_index": task_index,
                    "property": str(task.get("Property") or ""),
                    "target_alias": _target_alias(task.get("TargetType")),
                    "value_expr": _numeric_expr_summary(task.get("PropertyValue")),
                    "is_refresh": bool(task.get("IsRefresh", False)),
                    "raw_path": f"_CallbackList[{callback_index}].CallbackConfig[{task_index}]",
                }
            )
    return summaries


def _combatant_profile_from_monster(
    monster_id: str,
    monster_row: dict[str, Any],
    template_id: str,
    template_row: dict[str, Any] | None,
    *,
    source_path: str = "ExcelOutput/MonsterConfig.json",
    raw_type: str = "MonsterConfig",
    template_source_path: str = "ExcelOutput/MonsterTemplateConfig.json",
) -> CombatantProfileIR:
    source = IRSource(
        source_path=source_path,
        raw_type=raw_type,
        raw_id=monster_id,
        evidence={
            "entity_id": f"monster:{monster_id}",
            "template_id": template_id,
            "template_source_path": template_source_path,
            "raw_paths": {
                "template_id": "MonsterTemplateID",
                "attack_modify_ratio": "AttackModifyRatio",
                "defense_modify_ratio": "DefenceModifyRatio",
                "hp_modify_ratio": "HPModifyRatio",
                "speed_modify_ratio": "SpeedModifyRatio",
                "stance_modify_ratio": "StanceModifyRatio",
                "weaknesses": "StanceWeakList",
                "resistances": "DamageTypeResistance",
            },
        },
    )
    if template_row is None:
        return _blocked_combatant_profile(
            profile_id=f"combatant_profile:monster:{monster_id}",
            entity_id=f"monster:{monster_id}",
            entity_type="monster",
            template_id=template_id,
            source=source,
            reason="monster_template_missing",
        )
    stat_result = _monster_profile_stats(monster_row, template_row)
    blocked_reason = stat_result.get("blocked_reason", "")
    return CombatantProfileIR(
        profile_id=f"combatant_profile:monster:{monster_id}",
        entity_id=f"monster:{monster_id}",
        entity_type="monster",
        template_id=f"monster_template:{template_id}" if template_id else "",
        base_stats=stat_result["base_stats"] if isinstance(stat_result.get("base_stats"), dict) else {},
        toughness_profile=stat_result["toughness_profile"] if isinstance(stat_result.get("toughness_profile"), dict) else {},
        weaknesses=tuple(str(item) for item in monster_row.get("StanceWeakList") or ()),
        resistances=_damage_type_resistances(monster_row.get("DamageTypeResistance")),
        source=source,
        status_resistance=_required_number(template_row, "StatusResistanceBase"),
        debuff_resistances=tuple(_json_safe(item) for item in monster_row.get("DebuffResist") or ()),
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _lower_action_admissions(
    action_sets: list[CombatantActionSetIR],
    definitions: list[ActionDefinitionIR],
) -> tuple[list[CombatantActionSetIR], list[ActionAdmissionIR]]:
    definitions_by_key: dict[tuple[str, int], list[ActionDefinitionIR]] = {}
    for definition in definitions:
        definitions_by_key.setdefault((definition.action_id, definition.level), []).append(definition)
    updated_sets: list[CombatantActionSetIR] = []
    admissions: list[ActionAdmissionIR] = []
    for action_set in action_sets:
        updated_map: dict[str, JSONValue] = {}
        for skill_index, raw_entry in action_set.skill_index_map.items():
            if not isinstance(raw_entry, dict):
                updated_map[skill_index] = raw_entry
                continue
            entry = dict(raw_entry)
            action_id = str(entry.get("action_ref") or "")
            levels = tuple(
                int(level)
                for level in entry.get("levels", ())
                if isinstance(level, int) and not isinstance(level, bool) and level > 0
            )
            admission_ids: dict[str, JSONValue] = {}
            for level in levels:
                admission_id = (
                    f"action_admission:{action_set.entity_ref}:{action_id}:level:{level}"
                )
                candidates = definitions_by_key.get((action_id, level), ())
                definition = candidates[0] if len(candidates) == 1 else None
                contract = _action_role_contract(definition, action_entry=entry)
                blocked_reason = str(contract["blocked_reason"] or "")
                if len(candidates) > 1:
                    blocked_reason = "action_definition_reference_ambiguous"
                elif definition is None:
                    blocked_reason = "action_definition_reference_missing"
                coverage_status = "blocked" if blocked_reason else "executable"
                admissions.append(
                    ActionAdmissionIR(
                        admission_id=admission_id,
                        owner_entity_ref=action_set.entity_ref,
                        action_id=action_id,
                        action_level=level,
                        action_role=str(contract["action_role"]),
                        submission_modes=tuple(contract["submission_modes"]),
                        allowed_windows=tuple(contract["allowed_windows"]),
                        control_kind=str(contract["control_kind"]),
                        resource_gate_kind=str(contract["resource_gate_kind"]),
                        source=IRSource(
                            source_path=action_set.source.source_path,
                            raw_type="ActionAdmission",
                            raw_id=admission_id,
                            evidence={
                                "combatant_action_set_id": action_set.combatant_action_set_id,
                                "skill_index": skill_index,
                                "action_set_source": action_set.source.to_json(),
                                "action_definition_source": definition.source.to_json()
                                if definition is not None
                                else {},
                                "attack_type": definition.attack_type if definition is not None else "",
                            },
                        ),
                        coverage_status=coverage_status,
                        blocked_reason=blocked_reason,
                    )
                )
                admission_ids[str(level)] = admission_id
            entry["admission_ids"] = admission_ids
            default_level = entry.get("default_level")
            entry["admission_id"] = (
                admission_ids.get(str(default_level), "")
                if isinstance(default_level, int) and not isinstance(default_level, bool)
                else ""
            )
            updated_map[skill_index] = entry
        updated_sets.append(replace(action_set, skill_index_map=updated_map))
    return updated_sets, admissions


def _action_role_contract(
    definition: ActionDefinitionIR | None,
    *,
    action_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if definition is None:
        return {
            "action_role": "unknown",
            "submission_modes": (),
            "allowed_windows": (),
            "control_kind": "blocked",
            "resource_gate_kind": "action_definition",
            "blocked_reason": "action_definition_reference_missing",
        }
    attack_type = definition.attack_type
    role_source = (
        action_entry.get("role_source")
        if isinstance(action_entry, dict)
        else None
    )
    if (
        definition.action_id.startswith("servant_skill:")
        and attack_type in {"", "Unknown"}
        and isinstance(role_source, dict)
        and role_source.get("skill_type") == "Passive"
        and role_source.get("use_type") == "Passive"
        and isinstance(role_source.get("source_trace"), dict)
    ):
        return {
            "action_role": "passive_trigger",
            "submission_modes": ("trigger",),
            "allowed_windows": ("event_trigger",),
            "control_kind": "internal_trigger",
            "resource_gate_kind": "none",
            "blocked_reason": "",
        }
    if attack_type in {"Normal", "BPSkill", "Servant"}:
        return {
            "action_role": "turn_action",
            "submission_modes": ("external_turn", "queue"),
            "allowed_windows": ("idle", "turn_active", "turn_action"),
            "control_kind": "external",
            "resource_gate_kind": "action_definition",
            "blocked_reason": "",
        }
    if attack_type == "Ultra":
        return {
            "action_role": "insert_action",
            "submission_modes": ("insert_window", "queue"),
            "allowed_windows": ("ultimate",),
            "control_kind": "selectable_window",
            "resource_gate_kind": "ultimate_energy",
            "blocked_reason": "",
        }
    if attack_type in {"Maze", "MazeNormal"}:
        return {
            "action_role": "out_of_combat",
            "submission_modes": ("out_of_combat",),
            "allowed_windows": ("scenario",),
            "control_kind": "scenario",
            "resource_gate_kind": "none",
            "blocked_reason": "",
        }
    if attack_type in {"Talent", "Passive", "TalentPassive"}:
        return {
            "action_role": "passive_trigger",
            "submission_modes": ("trigger",),
            "allowed_windows": ("event_trigger",),
            "control_kind": "internal_trigger",
            "resource_gate_kind": "none",
            "blocked_reason": "",
        }
    if not attack_type or attack_type == "Unknown":
        return {
            "action_role": "unknown",
            "submission_modes": (),
            "allowed_windows": (),
            "control_kind": "blocked",
            "resource_gate_kind": "action_definition",
            "blocked_reason": "action_role_classification_missing",
        }
    return {
        "action_role": "unknown",
        "submission_modes": (),
        "allowed_windows": (),
        "control_kind": "blocked",
        "resource_gate_kind": "action_definition",
        "blocked_reason": f"action_role_not_admitted:{attack_type}",
    }


def _compatible_action_definitions_for_combatant_action_set(
    entity_type: str,
    definitions: tuple[ActionDefinitionIR, ...] | list[ActionDefinitionIR],
) -> tuple[ActionDefinitionIR, ...]:
    if entity_type == "monster":
        return tuple(
            definition
            for definition in definitions
            if definition.source.source_path
            in {
                "ExcelOutput/MonsterSkillConfig.json",
                "ExcelOutput/MonsterSkillUniqueConfig.json",
            }
        )
    if entity_type == "servant":
        return tuple(
            definition
            for definition in definitions
            if definition.source.source_path == "ExcelOutput/AvatarServantSkillConfig.json"
        )
    return tuple(definitions)


def _combatant_profile_from_template(
    template_id: str,
    template_row: dict[str, Any],
    *,
    source_path: str = "ExcelOutput/MonsterTemplateConfig.json",
    raw_type: str = "MonsterTemplateConfig",
) -> CombatantProfileIR:
    source = IRSource(
        source_path=source_path,
        raw_type=raw_type,
        raw_id=template_id,
        evidence={
            "entity_id": f"monster_template:{template_id}",
            "raw_paths": {
                "attack": "AttackBase",
                "defense": "DefenceBase",
                "hp": "HPBase",
                "speed": "SpeedBase",
                "stance": "StanceBase",
            },
        },
    )
    stat_result = _monster_template_profile_stats(template_row)
    blocked_reason = stat_result.get("blocked_reason", "")
    return CombatantProfileIR(
        profile_id=f"combatant_profile:monster_template:{template_id}",
        entity_id=f"monster_template:{template_id}",
        entity_type="monster_template",
        template_id=f"monster_template:{template_id}",
        base_stats=stat_result["base_stats"] if isinstance(stat_result.get("base_stats"), dict) else {},
        toughness_profile=stat_result["toughness_profile"] if isinstance(stat_result.get("toughness_profile"), dict) else {},
        weaknesses=(),
        resistances={},
        source=source,
        status_resistance=_required_number(template_row, "StatusResistanceBase"),
        debuff_resistances=(),
        coverage_status="blocked" if blocked_reason else "lowered",
        blocked_reason=blocked_reason or "monster_template_profile_lacks_monster_weakness_and_resistance",
    )


def _monster_profile_stats(monster_row: dict[str, Any], template_row: dict[str, Any]) -> dict[str, Any]:
    template_stats = _monster_template_profile_stats(template_row)
    if template_stats.get("blocked_reason"):
        return template_stats
    required_ratios = {
        "attack": ("AttackModifyRatio", "attack"),
        "defense": ("DefenceModifyRatio", "defense"),
        "max_hp": ("HPModifyRatio", "max_hp"),
        "speed": ("SpeedModifyRatio", "speed"),
        "max_toughness": ("StanceModifyRatio", "max_toughness"),
    }
    missing = [key for key, _ in required_ratios.values() if _required_number(monster_row, key) is None]
    if missing:
        return {"blocked_reason": f"monster_modify_ratio_missing:{','.join(missing)}"}
    base_stats = dict(template_stats["base_stats"])
    toughness_profile = dict(template_stats["toughness_profile"])
    for stat_name, (ratio_key, source_stat) in required_ratios.items():
        ratio = _required_number(monster_row, ratio_key)
        if ratio is None:
            continue
        if stat_name == "max_toughness":
            base_value = float(toughness_profile.get(source_stat, 0.0))
            toughness_profile[stat_name] = base_value * ratio
            toughness_profile["current_toughness"] = toughness_profile[stat_name]
            toughness_profile["stance_modify_ratio"] = ratio
        else:
            base_stats[stat_name] = float(base_stats.get(source_stat, 0.0)) * ratio
    return {
        "base_stats": base_stats,
        "toughness_profile": toughness_profile,
        "blocked_reason": "",
    }


def _monster_template_profile_stats(template_row: dict[str, Any]) -> dict[str, Any]:
    required = {
        "attack": "AttackBase",
        "defense": "DefenceBase",
        "max_hp": "HPBase",
        "speed": "SpeedBase",
        "max_toughness": "StanceBase",
    }
    missing = [key for key in required.values() if _required_number(template_row, key) is None]
    if missing:
        return {"blocked_reason": f"monster_template_base_stat_missing:{','.join(missing)}"}
    base_stats = {
        "attack": _required_number(template_row, "AttackBase") or 0.0,
        "defense": _required_number(template_row, "DefenceBase") or 0.0,
        "max_hp": _required_number(template_row, "HPBase") or 0.0,
        "speed": _required_number(template_row, "SpeedBase") or 0.0,
    }
    max_toughness = _required_number(template_row, "StanceBase") or 0.0
    return {
        "base_stats": base_stats,
        "toughness_profile": {
            "max_toughness": max_toughness,
            "current_toughness": max_toughness,
            "stance_base": max_toughness,
            "stance_type": str(template_row.get("StanceType") or ""),
        },
        "blocked_reason": "",
    }


def _damage_type_resistances(value: Any) -> dict[str, Any]:
    if not isinstance(value, list):
        return {}
    result: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        damage_type = item.get("DamageType")
        if not isinstance(damage_type, str) or not damage_type:
            continue
        resistance = _required_number(item, "Value")
        if resistance is not None:
            result[damage_type] = resistance
    return result


def _blocked_combatant_profile(
    *,
    profile_id: str,
    entity_id: str,
    entity_type: str,
    template_id: str,
    source: IRSource,
    reason: str,
) -> CombatantProfileIR:
    return CombatantProfileIR(
        profile_id=profile_id,
        entity_id=entity_id,
        entity_type=entity_type,
        template_id=template_id,
        base_stats={},
        toughness_profile={},
        weaknesses=(),
        resistances={},
        source=source,
        status_resistance=None,
        debuff_resistances=(),
        coverage_status="blocked",
        blocked_reason=reason,
    )


def _target_relation_from_action_source(
    target_source: dict[str, Any],
    row_target_type: Any,
) -> str:
    candidates = (
        target_source.get("target_type"),
        target_source.get("target_alias"),
        row_target_type,
    )
    relations = {
        relation
        for candidate in candidates
        for relation in (_target_relation_from_alias(candidate),)
        if relation != "unknown"
    }
    return next(iter(relations)) if len(relations) == 1 else "unknown"


def _target_relation_from_ability_phases(phases: tuple[AbilityPhaseIR, ...]) -> str:
    relations = {
        relation
        for phase in phases
        for alias in _target_alias_operands(phase.target_info)
        for relation in (_target_relation_from_alias(alias),)
        if relation != "unknown"
    }
    return next(iter(relations)) if len(relations) == 1 else "unknown"


def _target_relation_from_action_semantics(
    definition: ActionDefinitionIR,
) -> str:
    if (
        definition.damage_kind == "hp_damage"
        and definition.target_mode in {"single", "blast", "aoe", "bounce"}
    ):
        return "enemy"
    return "unknown"


def _target_alias_operands(value: Any) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"Alias", "alias", "TargetType"} and isinstance(item, str):
                found.append(item)
            elif isinstance(item, (dict, list)):
                found.extend(_target_alias_operands(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_target_alias_operands(item))
    return tuple(found)


def _target_relation_from_alias(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("Alias") or value.get("alias") or value.get("TargetType")
    if not isinstance(value, str) or not value:
        return "unknown"
    lowered = value.lower()
    if "enemy" in lowered:
        return "enemy"
    if lowered in {"caster", "self"}:
        return "self"
    if any(token in lowered for token in ("team", "ally", "partner")):
        return "ally_or_self"
    if "owner" in lowered:
        return "owner"
    if "summoner" in lowered:
        return "summoner"
    if "servant" in lowered or "summon" in lowered:
        return "summon"
    return "unknown"


def _action_definition_from_row(
    relative_path: str,
    entity_type: str,
    id_key: str,
    row_index: int,
    row: dict[str, Any],
    *,
    monster_target_source: dict[str, Any] | None = None,
    servant_target_source: dict[str, Any] | None = None,
) -> ActionDefinitionIR:
    raw_id = str(row[id_key])
    action_id = f"{entity_type}:{raw_id}"
    level = int(_number_value(row.get("Level"), 1.0))
    monster_target_mode = str((monster_target_source or {}).get("target_mode") or "")
    skill_effect = (
        _skill_effect_from_target_mode(monster_target_mode)
        if entity_type == "monster_skill"
        else str(row.get("SkillEffect") or row.get("AttackType") or "Unknown")
    )
    attack_type = str(row.get("AttackType") or "Unknown")
    element_type = (
        str(row["StanceDamageType"])
        if row.get("StanceDamageType") is not None
        else str(row["DamageType"])
        if row.get("DamageType") is not None
        else None
    )
    target_mode = monster_target_mode or _target_mode(skill_effect)
    target_source = monster_target_source or servant_target_source or {}
    target_relation = _target_relation_from_action_source(
        target_source,
        row.get("TargetType"),
    )
    source_mode = "mainline_monster" if entity_type == "monster_skill" else _source_mode(attack_type)
    source = IRSource(
        source_path=relative_path,
        raw_type=Path(relative_path).stem,
        raw_id=raw_id,
        evidence={
            "row_index": row_index,
            "id_key": id_key,
            "level": level,
            "skill_desc_hash": _hash_ref(row.get("SkillDesc")),
            "skill_trigger_key": str(row.get("SkillTriggerKey") or ""),
            "damage_type": str(row.get("DamageType") or ""),
            "sp_hit_base": _json_safe(row.get("SPHitBase")),
            "monster_target_source": _json_safe(monster_target_source or {}),
            "servant_target_source": _json_safe(servant_target_source or {}),
            "resource_mapping": {
                "BPNeed": "skill_point_cost_if_positive",
                "BPAdd": "skill_point_gain_if_positive",
                "SPBase": "energy_gain",
            },
            "taxonomy": {
                "attack_type": "raw TBGD AttackType; follow-up is an attack type axis",
                "damage_formula_family": "formula family axis; follow-up is not a damage family",
                "element_type": "raw TBGD StanceDamageType when present",
            },
        },
    )
    return ActionDefinitionIR(
        definition_id=f"action_def:{action_id}:{level}",
        action_id=action_id,
        level=level,
        attack_type=attack_type,
        skill_effect=skill_effect,
        target_mode=target_mode,
        bp_need=_number_value(row.get("BPNeed"), 0.0),
        bp_add=_number_value(row.get("BPAdd"), 0.0),
        sp_base=_number_value(row.get("SPBase"), 0.0),
        sp_multiple_ratio=_number_value(row.get("SPMultipleRatio"), 0.0),
        param_list=tuple(_list_json_values(row.get("ParamList"))),
        show_stance_list=tuple(_list_json_values(row.get("ShowStanceList"))),
        show_damage_list=tuple(_list_json_values(row.get("ShowDamageList"))),
        stance_damage_type=element_type,
        source=source,
        coverage_status="executable",
        damage_kind=_damage_kind(skill_effect),
        damage_formula_family=_damage_formula_family(attack_type, skill_effect),
        element_type=element_type,
        source_mode=source_mode,
        skill_trigger_key=str(row.get("SkillTriggerKey") or ""),
        target_relation=target_relation,
    )


def build_character_action_definition_ir(
    tbgd_root: Path,
    *,
    max_records_per_table: int | None = None,
) -> tuple[ActionDefinitionIR, ...]:
    """Build only character-owned action definitions without full TBGD lowering."""

    definitions: list[ActionDefinitionIR] = []
    for relative_path, entity_type, id_key in CHARACTER_ACTION_DEFINITION_TABLES:
        path = tbgd_root / relative_path
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
            if not isinstance(row, dict) or id_key not in row:
                continue
            definitions.append(
                _action_definition_from_row(
                    relative_path,
                    entity_type,
                    id_key,
                    row_index,
                    row,
                )
            )
    return tuple(definitions)


def _link_trigger_ability_graphs(
    tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    graphs: list[StandaloneAbilityGraphIR],
    phases: list[AbilityPhaseIR],
) -> list[AbilityTaskIR]:
    effects_by_id = {effect.effect_id: effect for effect in effects}
    graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]] = {}
    for graph in graphs:
        graphs_by_name.setdefault(graph.ability_name, []).append(graph)
    phases_by_id = {phase.phase_id: phase for phase in phases}
    linked: list[AbilityTaskIR] = []
    for task in tasks:
        if task.opcode != "TriggerAbility":
            linked.append(task)
            continue
        if task.coverage_status != "executable":
            linked.append(task)
            continue
        effect = effects_by_id.get(task.effect_id)
        standard = effect.payload.get("standard") if effect is not None else None
        ability_name = standard.get("ability_name") if isinstance(standard, dict) else None
        current_phase = phases_by_id.get(task.phase_id)
        bound_phase_candidates = tuple(
            phase
            for phase in phases
            if current_phase is not None
            and phase.binding_id == current_phase.binding_id
            and phase.phase_id != current_phase.phase_id
            and phase.ability_name == str(ability_name or "")
        )
        if len(bound_phase_candidates) == 1:
            linked.append(
                replace(
                    task,
                    coverage_status="executable",
                    blocked_reason="",
                    linked_standalone_graph_id="",
                )
            )
            continue
        if len(bound_phase_candidates) > 1:
            linked.append(
                replace(
                    task,
                    coverage_status="blocked",
                    blocked_reason="trigger_ability_bound_phase_ambiguous",
                    linked_standalone_graph_id="",
                )
            )
            continue
        candidates = graphs_by_name.get(str(ability_name or ""), ())
        exact = tuple(graph for graph in candidates if graph.source.source_path == task.source.source_path)
        selected = exact if len(exact) == 1 else tuple(candidates) if len(candidates) == 1 else ()
        if selected:
            linked.append(replace(task, linked_standalone_graph_id=selected[0].standalone_ability_graph_id))
            continue
        reason = "trigger_ability_graph_missing" if not candidates else "trigger_ability_graph_link_ambiguous"
        linked.append(
            replace(
                task,
                coverage_status="blocked",
                blocked_reason=reason,
                linked_standalone_graph_id="",
            )
        )
    return linked


def _link_status_effect_runtime_fields(
    effects: list[EffectIR],
    entities: list[RuleEntity],
    callbacks: list[StatusCallbackIR],
    ability_property_watchers: Iterable[AbilityPropertyWatcherIR] = (),
) -> list[EffectIR]:
    definitions_by_modifier: dict[str, list[RuleEntity]] = {}
    for entity in entities:
        if entity.entity_type != "modifier_definition":
            continue
        modifier_name = entity.fields.get("modifier_name") or entity.fields.get("ModifierName")
        if isinstance(modifier_name, str) and modifier_name:
            definitions_by_modifier.setdefault(modifier_name, []).append(entity)
    callbacks_by_modifier: dict[str, list[StatusCallbackIR]] = {}
    for callback in callbacks:
        callbacks_by_modifier.setdefault(callback.modifier_name, []).append(callback)
    watchers_by_modifier: dict[str, list[AbilityPropertyWatcherIR]] = {}
    for watcher in ability_property_watchers:
        watchers_by_modifier.setdefault(watcher.modifier_name, []).append(watcher)

    linked: list[EffectIR] = []
    for effect in effects:
        source_mode = _runtime_source_mode(effect.source.source_path)
        if effect.opcode != "AddModifier":
            linked.append(replace(effect, source_mode=source_mode))
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        modifier_name = standard.get("modifier_name") if isinstance(standard, dict) else None
        if not isinstance(modifier_name, str) or not modifier_name:
            linked.append(
                replace(
                    effect,
                    coverage_status="blocked",
                    source_mode=source_mode,
                    link_blocked_reason="modifier_name_missing",
                )
            )
            continue
        definitions = definitions_by_modifier.get(modifier_name, ())
        exact = tuple(item for item in definitions if item.source.source_path == effect.source.source_path)
        selected = exact if len(exact) == 1 else tuple(definitions) if len(definitions) == 1 else ()
        if not selected:
            reason = "modifier_definition_missing" if not definitions else "modifier_definition_link_ambiguous"
            linked.append(
                replace(
                    effect,
                    coverage_status="blocked",
                    source_mode=source_mode,
                    link_blocked_reason=reason,
                )
            )
            continue
        same_source_callbacks = tuple(
            callback
            for callback in callbacks_by_modifier.get(modifier_name, ())
            if callback.source.source_path == selected[0].source.source_path
        )
        callback_ids = tuple(
            callback.callback_id
            for callback in sorted(
                same_source_callbacks or callbacks_by_modifier.get(modifier_name, ()),
                key=lambda item: item.callback_id,
            )
        )
        watcher_ids = tuple(
            watcher.watcher_id
            for watcher in sorted(
                (
                    watcher
                    for watcher in watchers_by_modifier.get(modifier_name, ())
                    if watcher.source.source_path == selected[0].source.source_path
                ),
                key=lambda item: item.watcher_id,
            )
        )
        linked.append(
            replace(
                effect,
                modifier_definition_id=selected[0].entity_id,
                status_callback_ids=callback_ids,
                ability_property_watcher_ids=watcher_ids,
                source_mode=source_mode,
                link_blocked_reason="",
            )
        )
    return linked


def _runtime_source_mode(source_path: str) -> str:
    blocked_markers = (
        "/Activity/",
        "/Rogue/",
        "/GridFight/",
        "/Fate/",
        "/Story/",
        "/Level/",
        "/SubLevelGraph/",
        "/ElationBattle/",
        "Config/Level/",
        "Config/Gameplays/",
    )
    return "special_mode" if any(marker in source_path for marker in blocked_markers) else "mainline"


def _hash_ref(value: Any) -> str:
    if isinstance(value, dict) and value.get("Hash") is not None:
        return str(value["Hash"])
    return ""


def _blocked_action_binding(
    definition: ActionDefinitionIR,
    reason: str,
    source_path: str = "",
) -> tuple[ActionAbilityBindingIR, list[AbilityPhaseIR], _LoweredAbility]:
    source = IRSource(
        source_path=source_path or definition.source.source_path,
        raw_type="ActionAbilityBinding",
        raw_id=f"{definition.action_id}:{definition.level}",
        evidence={
            "action_id": definition.action_id,
            "level": definition.level,
            "definition_source": definition.source.to_json(),
            "blocked_reason": reason,
        },
    )
    source_mode = "mainline_avatar_blocked" if definition.action_id.startswith("avatar_skill:") else "non_avatar_blocked"
    return (
        ActionAbilityBindingIR(
            binding_id=f"action_binding:{definition.action_id}:{definition.level}",
            action_id=definition.action_id,
            level=definition.level,
            skill_trigger_key=str(definition.source.evidence.get("skill_trigger_key") or ""),
            skill_name="",
            entry_ability="",
            ability_names=(),
            config_source={},
            phase_ids=(),
            source_mode=source_mode,
            source=source,
            coverage_status="blocked",
            blocked_reason=reason,
        ),
        [],
        _LoweredAbility(),
    )


def _skill_config_by_name(character_config: dict[str, Any], skill_trigger_key: str) -> dict[str, Any] | None:
    skill_list = character_config.get("SkillList")
    if isinstance(skill_list, list):
        for item in skill_list:
            if not isinstance(item, dict):
                continue
            names = {
                str(item.get("Name") or ""),
                str(item.get("SkillName") or ""),
                str(item.get("Skill") or ""),
                str(item.get("SkillTriggerKey") or ""),
            }
            if skill_trigger_key in names:
                return item
    if isinstance(skill_list, dict):
        item = skill_list.get(skill_trigger_key)
        if isinstance(item, dict):
            return item
        for key, value in skill_list.items():
            if str(key) == skill_trigger_key and isinstance(value, dict):
                return value
    return None


def _ability_names_for_skill(
    character_config: dict[str, Any],
    skill_trigger_key: str,
    entry_ability: str,
) -> list[str]:
    ability_names: list[str] = []
    if entry_ability:
        ability_names.append(entry_ability)
    skill_ability_list = character_config.get("SkillAbilityList")
    matched: Any = None
    if isinstance(skill_ability_list, dict):
        matched = skill_ability_list.get(skill_trigger_key)
        if matched is None:
            for key, value in skill_ability_list.items():
                if str(key) == skill_trigger_key:
                    matched = value
                    break
    elif isinstance(skill_ability_list, list):
        for item in skill_ability_list:
            if not isinstance(item, dict):
                continue
            names = {
                str(item.get("Name") or ""),
                str(item.get("SkillName") or ""),
                str(item.get("Skill") or ""),
                str(item.get("SkillTriggerKey") or ""),
            }
            if skill_trigger_key in names:
                matched = item
                break
    ability_names.extend(_ability_names_from_value(matched))
    return list(dict.fromkeys(name for name in ability_names if name))


def _expand_triggered_ability_names(
    ability_names: list[str],
    ability_map: dict[str, dict[str, Any]],
    *,
    max_depth: int = 3,
) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    queue: list[tuple[str, int]] = [(name, 0) for name in ability_names]
    while queue:
        ability_name, depth = queue.pop(0)
        if not ability_name or ability_name in seen:
            continue
        seen.add(ability_name)
        expanded.append(ability_name)
        if depth >= max_depth:
            continue
        ability = ability_map.get(ability_name)
        if not isinstance(ability, dict):
            continue
        for child_name in _trigger_ability_names_from_value(ability):
            if child_name in ability_map and child_name not in seen:
                queue.append((child_name, depth + 1))
    return expanded


def _trigger_ability_names_from_value(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, list):
        for item in value:
            names.extend(_trigger_ability_names_from_value(item))
    elif isinstance(value, dict):
        raw_type = str(value.get("$type") or "")
        if raw_type.endswith("TriggerAbility"):
            ability_name = value.get("AbilityName")
            if isinstance(ability_name, dict) and isinstance(ability_name.get("Value"), str):
                names.append(str(ability_name["Value"]))
            elif isinstance(ability_name, str):
                names.append(ability_name)
        for item in value.values():
            names.extend(_trigger_ability_names_from_value(item))
    return list(dict.fromkeys(name for name in names if name))


def _select_trigger_ability_candidate(
    candidates: list[CharacterAbilityDefinitionIR]
    | tuple[CharacterAbilityDefinitionIR, ...],
) -> CharacterAbilityDefinitionIR | None:
    if type(candidates) not in {list, tuple} or any(
        type(item) is not CharacterAbilityDefinitionIR for item in candidates
    ):
        raise TypeError("trigger ability candidates must be exact typed definitions")
    gameplay = tuple(
        item
        for item in candidates
        if item.definition_kind in {"character_main", "character_shared"}
    )
    if len(gameplay) == 1:
        return gameplay[0]
    presentation = tuple(
        item for item in candidates if item.definition_kind == "presentation"
    )
    if not gameplay and len(presentation) == 1:
        return presentation[0]
    return None


def _ability_names_from_value(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, str):
        names.append(value)
    elif isinstance(value, list):
        for item in value:
            names.extend(_ability_names_from_value(item))
    elif isinstance(value, dict):
        for key in ("AbilityName", "Name", "PhaseAbility", "PhaseAbilityName", "EntryAbility"):
            item = value.get(key)
            if isinstance(item, str):
                names.append(item)
        for key in ("AbilityList", "AbilityNameList", "PhaseList", "PhaseAbilityList"):
            names.extend(_ability_names_from_value(value.get(key)))
        if not names:
            for item in value.values():
                names.extend(_ability_names_from_value(item))
    return names


def _resolve_monster_ability_paths(
    ability_names: list[str],
    ability_file_index: dict[str, tuple[str, ...]],
) -> tuple[dict[str, str], list[str], dict[str, list[str]]]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    ambiguous: dict[str, list[str]] = {}
    for ability_name in ability_names:
        paths = tuple(ability_file_index.get(ability_name, ()))
        if not paths:
            missing.append(ability_name)
            continue
        if len(paths) > 1:
            ambiguous[ability_name] = list(paths)
            continue
        resolved[ability_name] = paths[0]
    return resolved, missing, ambiguous


def _servant_ability_path_from_character_path(character_path: str) -> str:
    path = Path(character_path)
    name = path.name
    if name.endswith("_Config.json"):
        ability_name = name.replace("_Config.json", "_Ability.json")
    else:
        ability_name = f"{path.stem}_Ability.json"
    return f"Config/ConfigAbility/Servant/{ability_name}"


def _servant_camera_ability_path_from_character_path(character_path: str) -> str:
    path = Path(character_path)
    name = path.name
    if name.endswith("_Config.json"):
        camera_name = name.replace("_Config.json", "_Camera.json")
    else:
        camera_name = f"{path.stem}_Camera.json"
    return f"Config/ConfigAbility/Servant/Camera/{camera_name}"


def _servant_action_set_admission(
    servant_ref: str,
    action_set: CombatantActionSetIR | None,
    bindings_by_action: dict[tuple[str, int], list[ActionAbilityBindingIR]],
    admissions_by_action: dict[
        tuple[str, str, int], list[ActionAdmissionIR]
    ],
) -> tuple[dict[str, Any], list[str]]:
    if action_set is None:
        return (
            {
                "admission_status": "blocked",
                "coverage_status": "blocked",
                "blocked_reason": "servant_action_set_missing",
                "entity_ref": servant_ref,
                "skill_index_map": {},
                "executable_binding_ids": [],
                "required_action_skill_ids": [],
                "source_trace": [],
            },
            [],
        )
    source_trace = [action_set.source.to_json()]
    executable_binding_ids: list[str] = []
    skipped_slots: list[dict[str, Any]] = []
    classified_non_action_slots: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    required_action_slots: list[str] = []
    required_action_skill_ids: list[str] = []
    passive_slots: list[str] = []
    lifecycle_slots: list[str] = []
    skill_index_map = _json_safe(action_set.skill_index_map)
    for slot, entry in sorted(action_set.skill_index_map.items()):
        if not isinstance(entry, dict):
            blocking_reasons.append(f"servant_action_slot_not_structured:{slot}")
            continue
        slot_role = str(entry.get("servant_action_role") or "unknown")
        if slot_role == "passive":
            passive_slots.append(slot)
            classified_non_action_slots.append(
                {"slot": slot, "servant_action_role": slot_role}
            )
            continue
        if slot_role == "lifecycle":
            lifecycle_slots.append(slot)
            classified_non_action_slots.append(
                {"slot": slot, "servant_action_role": slot_role}
            )
            continue
        if slot_role != "required_action":
            blocking_reasons.append(f"servant_action_slot_role_unclassified:{slot}")
            continue
        required_action_slots.append(slot)
        skill_id = str(entry.get("skill_id") or "")
        if not skill_id:
            blocking_reasons.append(f"servant_required_action_skill_id_missing:{slot}")
        elif skill_id in required_action_skill_ids:
            blocking_reasons.append(
                f"servant_required_action_skill_id_duplicate:{skill_id}"
            )
        else:
            required_action_skill_ids.append(skill_id)
        if entry.get("coverage_status") != "executable":
            reason = str(entry.get("blocked_reason") or "servant_action_slot_blocked")
            skipped_slots.append({"slot": slot, "blocked_reason": reason})
            blocking_reasons.append(f"servant_required_action_slot_blocked:{slot}:{reason}")
            continue
        action_ref = str(entry.get("action_ref") or "")
        level = _optional_int(entry.get("default_level"))
        if not action_ref or level is None:
            skipped_slots.append({"slot": slot, "blocked_reason": "servant_action_ref_or_level_missing"})
            blocking_reasons.append(f"servant_required_action_ref_or_level_missing:{slot}")
            continue
        admissions = admissions_by_action.get(
            (servant_ref, action_ref, level),
            [],
        )
        if len(admissions) != 1:
            reason = (
                "servant_action_admission_missing"
                if not admissions
                else "servant_action_admission_ambiguous"
            )
            skipped_slots.append(
                {"slot": slot, "action_ref": action_ref, "level": level, "blocked_reason": reason}
            )
            blocking_reasons.append(f"servant_required_action_admission_invalid:{slot}:{reason}")
            continue
        admission = admissions[0]
        source_trace.append(admission.source.to_json())
        if admission.coverage_status != "executable" or admission.action_role != "turn_action":
            reason = admission.blocked_reason or (
                f"servant_action_admission_role_or_coverage_mismatch:"
                f"{admission.action_role}:{admission.coverage_status}"
            )
            skipped_slots.append(
                {"slot": slot, "action_ref": action_ref, "level": level, "blocked_reason": reason}
            )
            blocking_reasons.append(f"servant_required_action_admission_blocked:{slot}:{reason}")
            continue
        bindings = bindings_by_action.get((action_ref, level), [])
        if len(bindings) != 1:
            reason = (
                "servant_action_binding_missing"
                if not bindings
                else "servant_action_binding_ambiguous"
            )
            skipped_slots.append({"slot": slot, "action_ref": action_ref, "level": level, "blocked_reason": reason})
            blocking_reasons.append(f"servant_required_action_binding_invalid:{slot}:{reason}")
            continue
        binding = bindings[0]
        source_trace.append(binding.source.to_json())
        if binding.coverage_status != "executable":
            skipped_slots.append(
                {
                    "slot": slot,
                    "action_ref": action_ref,
                    "level": level,
                    "binding_id": binding.binding_id,
                    "blocked_reason": binding.blocked_reason or "servant_action_binding_blocked",
                }
            )
            blocking_reasons.append(
                f"servant_required_action_binding_blocked:{slot}:"
                f"{binding.blocked_reason or binding.coverage_status}"
            )
            continue
        executable_binding_ids.append(binding.binding_id)
    if action_set.coverage_status != "executable":
        blocking_reasons.append(action_set.blocked_reason or "servant_combatant_action_set_blocked")
    if not required_action_slots:
        blocking_reasons.append("servant_required_action_slots_missing")
    if len(executable_binding_ids) != len(required_action_slots):
        blocking_reasons.append("servant_required_action_bindings_incomplete")
    blocked_reason = ";".join(dict.fromkeys(reason for reason in blocking_reasons if reason))
    status = "blocked" if blocked_reason else "executable"
    return (
        {
            "admission_status": status,
            "coverage_status": status,
            "blocked_reason": blocked_reason,
            "combatant_action_set_id": action_set.combatant_action_set_id,
            "entity_ref": action_set.entity_ref,
            "skill_index_map": skill_index_map,
            "executable_binding_ids": executable_binding_ids,
            "required_action_slots": required_action_slots,
            "required_action_skill_ids": required_action_skill_ids,
            "passive_slots": passive_slots,
            "lifecycle_slots": lifecycle_slots,
            "classified_non_action_slots": _json_safe(classified_non_action_slots),
            "skipped_slots": _json_safe(skipped_slots),
            "source_trace": source_trace,
        },
        executable_binding_ids,
    )


def _servant_action_slot_role(role_source: dict[str, JSONValue]) -> str:
    skill_type = str(role_source.get("skill_type") or "")
    use_type = str(role_source.get("use_type") or "")
    entry_ability = str(role_source.get("entry_ability") or "")
    if (
        skill_type == "Servant"
        and use_type in {"SelectEntity", "UIButtonClick", "UIButtonPress"}
        and entry_ability
    ):
        return "required_action"
    if use_type == "Passive" and skill_type in {"Passive", "Servant"}:
        if skill_type == "Passive" and entry_ability.endswith(
            ("_BattleCry", "_DeathRattle")
        ):
            return "lifecycle"
        if entry_ability:
            return "passive"
    return "unknown"


def _servant_stat_source(
    row: dict[str, Any],
    stat_skill_rows: dict[str, dict[str, Any]],
    *,
    config_path: str,
    servant_config_data: dict[str, Any] | None,
) -> dict[str, Any]:
    hp_skill = str(row.get("HPSkill") or "")
    speed_skill = str(row.get("SpeedSkill") or "")
    hp_base = _servant_stat_component(row.get("HPBase"), hp_skill, stat_skill_rows, "HPBase")
    hp_inherit = _servant_stat_component(row.get("HPInherit"), hp_skill, stat_skill_rows, "HPInherit")
    speed_base = _servant_stat_component(row.get("SpeedBase"), speed_skill, stat_skill_rows, "SpeedBase")
    speed_inherit = _servant_stat_component(row.get("SpeedInherit"), speed_skill, stat_skill_rows, "SpeedInherit")
    base_aggro = _servant_stat_component(
        row.get("Aggro"),
        "",
        stat_skill_rows,
        "Aggro.Value",
    )
    components = {
        "hp_base": hp_base,
        "hp_inherit": hp_inherit,
        "speed_base": speed_base,
        "speed_inherit": speed_inherit,
        "base_aggro": base_aggro,
    }
    for component_key, field_name in (
        ("hp_base", "HPBase"),
        ("hp_inherit", "HPInherit"),
        ("speed_base", "SpeedBase"),
        ("speed_inherit", "SpeedInherit"),
        ("base_aggro", "Aggro.Value"),
    ):
        component = components[component_key]
        if not component.get("source_trace"):
            component["source_trace"] = [_servant_config_stat_field_source(row, field_name)]
    owner_sync_fields = _servant_owner_sync_fields(
        row,
        config_path=config_path,
        servant_config_data=servant_config_data,
    )
    blocking_reasons = [
        str(component.get("blocked_reason") or "")
        for component in components.values()
        if component.get("admission_status") != "executable"
    ]
    for property_type, base_key, inherit_key in (
        ("max_hp", "hp_base", "hp_inherit"),
        ("speed", "speed_base", "speed_inherit"),
    ):
        base_value = components[base_key].get("value")
        inherit_value = components[inherit_key].get("value")
        if (
            isinstance(base_value, (int, float))
            and not isinstance(base_value, bool)
            and isinstance(inherit_value, (int, float))
            and not isinstance(inherit_value, bool)
            and base_value <= 0
            and inherit_value <= 0
        ):
            blocking_reasons.append(
                f"servant_stat_formula_nonpositive:{property_type}"
            )
    blocking_reasons.extend(
        str(binding.get("blocked_reason") or "")
        for binding in owner_sync_fields.values()
        if binding.get("admission_status") != "executable"
    )
    blocked_reason = ";".join(dict.fromkeys(reason for reason in blocking_reasons if reason))
    status = "blocked" if blocked_reason else "executable"
    return {
        "admission_status": status,
        "coverage_status": status,
        "blocked_reason": blocked_reason,
        "hp_skill": hp_skill,
        "speed_skill": speed_skill,
        "components": components,
        "formula": {
            "max_hp": "owner.max_hp * hp_inherit + hp_base",
            "speed": "owner.speed * speed_inherit + speed_base",
            "attack": "owner.attack via ServantConfig.SyncPropertyExceptList",
            "defense": "owner.defense via ServantConfig.SyncPropertyExceptList",
        },
        "runtime_required_owner_fields": ["max_hp", "speed", "attack", "defense"],
        "owner_sync_fields": owner_sync_fields,
        "source_trace": [
            *_servant_component_source_trace(components),
            *(
                next(iter(owner_sync_fields.values())).get("source_trace") or []
                if owner_sync_fields
                else []
            ),
        ],
    }


_SERVANT_OWNER_SYNC_PROPERTY_FAMILIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "attack": (
        "owner_field",
        "attack",
        (
            "Attack",
            "BaseAttack",
            "AttackAddedRatio",
            "AttackConvert",
            "AttackDelta",
            "AttackOverride",
        ),
    ),
    "defense": (
        "owner_field",
        "defense",
        (
            "Defence",
            "BaseDefence",
            "DefenceAddedRatio",
            "DefenceConvert",
            "DefenceDelta",
            "DefenceOverride",
            "Defense",
            "BaseDefense",
            "DefenseAddedRatio",
            "DefenseConvert",
            "DefenseDelta",
            "DefenseOverride",
        ),
    ),
    "critical_chance": (
        "owner_resource",
        "critical_chance",
        ("CriticalChance", "CriticalChanceBase"),
    ),
    "critical_damage": (
        "owner_resource",
        "critical_damage",
        ("CriticalDamage", "CriticalDamageBase"),
    ),
}


def _servant_owner_sync_fields(
    row: dict[str, Any],
    *,
    config_path: str,
    servant_config_data: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    servant_id = str(row.get("ServantID") or "")
    raw_exclusions = (
        servant_config_data.get("SyncPropertyExceptList")
        if isinstance(servant_config_data, dict)
        else None
    )
    source = IRSource(
        source_path=config_path or str(row.get("_v8_source_path") or ""),
        raw_type="ServantConfig.SyncPropertyExceptList",
        raw_id=servant_id,
        evidence={
            "json_path": "$.SyncPropertyExceptList",
            "servant_id": servant_id,
            "config_type": (
                str(servant_config_data.get("$type") or "")
                if isinstance(servant_config_data, dict)
                else ""
            ),
            "excluded_properties": _json_safe(raw_exclusions),
        },
    )
    list_valid = (
        isinstance(raw_exclusions, list)
        and all(isinstance(item, str) and item for item in raw_exclusions)
        and len(set(raw_exclusions)) == len(raw_exclusions)
        and isinstance(servant_config_data, dict)
        and str(servant_config_data.get("$type") or "").endswith("ServantConfig")
        and bool(config_path)
    )
    exclusions = set(raw_exclusions) if list_valid else set()
    result: dict[str, dict[str, Any]] = {}
    for property_type, (binding_kind, owner_field, raw_family) in sorted(
        _SERVANT_OWNER_SYNC_PROPERTY_FAMILIES.items()
    ):
        excluded = tuple(item for item in raw_family if item in exclusions)
        blocked_reason = ""
        if not list_valid:
            blocked_reason = "servant_sync_property_except_list_missing_or_invalid"
        elif excluded:
            blocked_reason = f"servant_owner_property_not_synchronized:{property_type}"
        result[property_type] = {
            "admission_status": "blocked" if blocked_reason else "executable",
            "coverage_status": "blocked" if blocked_reason else "executable",
            "blocked_reason": blocked_reason,
            "binding_kind": binding_kind,
            "owner_field": owner_field,
            "raw_property_family": list(raw_family),
            "matched_exclusions": list(excluded),
            "source_trace": [source.to_json()],
        }
    return result


def _servant_stat_component(
    raw_value: Any,
    skill_id: str,
    stat_skill_rows: dict[str, dict[str, Any]],
    field_name: str,
) -> dict[str, Any]:
    direct = _servant_direct_number(raw_value)
    if direct is not None:
        return {
            "admission_status": "executable",
            "source_kind": "literal",
            "raw": _json_safe(raw_value),
            "value": direct,
            "source_trace": [],
        }
    if isinstance(raw_value, dict):
        return _servant_stat_component(raw_value.get("Value"), skill_id, stat_skill_rows, field_name)
    if not isinstance(raw_value, str) or not raw_value.startswith("#"):
        return {
            "admission_status": "blocked",
            "source_kind": "unsupported",
            "raw": _json_safe(raw_value),
            "value": None,
            "blocked_reason": f"servant_{field_name}_unsupported_value",
            "source_trace": [],
        }
    index_raw = raw_value[1:]
    if not index_raw.isdigit():
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "blocked_reason": f"servant_{field_name}_invalid_param_ref",
            "source_trace": [],
        }
    if not skill_id:
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "blocked_reason": f"servant_{field_name}_param_skill_missing",
            "source_trace": [],
        }
    skill_row = stat_skill_rows.get(skill_id)
    if not isinstance(skill_row, dict):
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "skill_id": skill_id,
            "blocked_reason": f"servant_{field_name}_param_skill_not_found",
            "source_trace": [],
        }
    param_index = int(index_raw) - 1
    params = skill_row.get("ParamList")
    if not isinstance(params, list) or param_index < 0 or param_index >= len(params):
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "skill_id": skill_id,
            "param_index": param_index,
            "blocked_reason": f"servant_{field_name}_param_index_out_of_range",
            "source_trace": [_servant_skill_row_source(skill_id, skill_row)],
        }
    resolved = _servant_direct_number(params[param_index])
    if resolved is None:
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "skill_id": skill_id,
            "param_index": param_index,
            "param_raw": _json_safe(params[param_index]),
            "blocked_reason": f"servant_{field_name}_param_value_not_numeric",
            "source_trace": [_servant_skill_row_source(skill_id, skill_row)],
        }
    return {
        "admission_status": "executable",
        "source_kind": "param_ref",
        "raw": raw_value,
        "value": resolved,
        "skill_id": skill_id,
        "param_index": param_index,
        "param_raw": _json_safe(params[param_index]),
        "source_trace": [_servant_skill_row_source(skill_id, skill_row)],
    }


def _servant_direct_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return _servant_direct_number(value.get("Value"))
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("#") or not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _servant_skill_row_source(skill_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": str(row.get("_v8_source_path") or ""),
        "raw_type": "SkillConfig",
        "raw_id": skill_id,
        "evidence": {
            "row_index": _json_safe(row.get("_v8_row_index")),
            "level": _json_safe(row.get("Level")),
            "param_list": _json_safe(row.get("ParamList") or []),
        },
    }


def _servant_config_stat_field_source(row: dict[str, Any], field_name: str) -> dict[str, Any]:
    return {
        "source_path": str(row.get("_v8_source_path") or "ExcelOutput/AvatarServantConfig.json"),
        "raw_type": "AvatarServantConfig",
        "raw_id": str(row.get("ServantID") or ""),
        "evidence": {
            "row_index": _json_safe(row.get("_v8_row_index")),
            "field_name": field_name,
            "raw_value": _json_safe(row.get(field_name)),
        },
    }


def _servant_component_source_trace(components: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for component in components.values():
        for trace in component.get("source_trace") or []:
            if not isinstance(trace, dict):
                continue
            key = (str(trace.get("source_path") or ""), str(trace.get("raw_id") or ""))
            if key in seen:
                continue
            seen.add(key)
            traces.append(trace)
    return traces


def _servant_owner_relations(
    row: dict[str, Any],
    *,
    character_data_cards: list[CharacterDataCardIR],
    character_trace_nodes: list[CharacterTraceNodeIR],
    character_eidolon_slots: list[CharacterEidolonSlotIR],
    character_mechanism_slots: list[CharacterMechanismSlotIR],
) -> tuple[ServantOwnerRelationIR, ...]:
    servant_id = str(row.get("ServantID") or "")
    servant_skill_ids = {
        str(skill_id) for skill_id in row.get("SkillIDList") or () if str(skill_id)
    }
    mechanism_by_id = {
        slot.mechanism_slot_id: slot for slot in character_mechanism_slots
    }
    nodes_by_card: dict[str, list[CharacterTraceNodeIR]] = {}
    for node in character_trace_nodes:
        nodes_by_card.setdefault(node.character_data_card_id, []).append(node)
    eidolons_by_card: dict[str, list[CharacterEidolonSlotIR]] = {}
    for slot in character_eidolon_slots:
        eidolons_by_card.setdefault(slot.character_data_card_id, []).append(slot)
    relations: list[ServantOwnerRelationIR] = []
    servant_source = IRSource(
        source_path=str(
            row.get("_v8_source_path") or "ExcelOutput/AvatarServantConfig.json"
        ),
        raw_type="AvatarServantConfig",
        raw_id=servant_id,
        evidence={
            "row_index": _json_safe(row.get("_v8_row_index")),
            "skill_id_list": sorted(servant_skill_ids),
            "join_role": "owned_combatant_skill_catalog",
        },
    )
    for card in sorted(character_data_cards, key=lambda item: item.card_id):
        card_skill_ids = set(card.skill_ids)
        card_enhanced_id = card.source.evidence.get("enhanced_id")

        def current_source(source: IRSource) -> bool:
            source_enhanced_id = source.evidence.get("enhanced_id")
            if card_enhanced_id is None:
                return source_enhanced_id is None
            return str(source_enhanced_id) == str(card_enhanced_id)

        relation_skill_ids: set[str] = set()
        relation_sources: list[IRSource] = [servant_source]
        for node in nodes_by_card.get(card.card_id, ()):
            if not current_source(node.source):
                continue
            matched = servant_skill_ids.intersection(node.level_up_skill_ids).difference(
                card_skill_ids
            )
            if matched:
                relation_skill_ids.update(matched)
                relation_sources.append(node.source)
                relation_sources.extend(
                    mechanism.source
                    for slot_id in node.linked_mechanism_slot_ids
                    if (mechanism := mechanism_by_id.get(slot_id)) is not None
                    and mechanism.mechanism_kind == "trace_skill_level"
                )
        for eidolon in eidolons_by_card.get(card.card_id, ()):
            if not current_source(eidolon.source):
                continue
            for slot_id in eidolon.linked_mechanism_slot_ids:
                mechanism = mechanism_by_id.get(slot_id)
                if mechanism is None or mechanism.mechanism_kind != "eidolon_skill_level":
                    continue
                bonuses = mechanism.semantics.get("skill_add_level_list")
                if not isinstance(bonuses, dict):
                    continue
                matched = servant_skill_ids.intersection(
                    str(skill_id) for skill_id in bonuses
                ).difference(card_skill_ids)
                if matched:
                    relation_skill_ids.update(matched)
                    relation_sources.extend((eidolon.source, mechanism.source))
        if not relation_skill_ids:
            continue
        relations.append(
            ServantOwnerRelationIR(
                owner_relation_id=(
                    f"servant_owner_relation:{servant_id}:{card.entity_ref}"
                ),
                owner_entity_ref=card.entity_ref,
                owner_character_card_id=card.card_id,
                auxiliary_skill_ids=tuple(sorted(relation_skill_ids)),
                sources=_dedupe_ir_sources(relation_sources),
                coverage_status="executable",
                blocked_reason="",
            )
        )
    return tuple(relations)


def _dedupe_ir_sources(sources: list[IRSource]) -> tuple[IRSource, ...]:
    result: list[IRSource] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        key = (source.source_path, source.raw_type, source.raw_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return tuple(sorted(result, key=lambda item: (item.source_path, item.raw_type, item.raw_id)))


def _servant_timeline_source(row: dict[str, Any], stat_source: dict[str, Any]) -> dict[str, Any]:
    if stat_source.get("admission_status") != "executable":
        return {
            "admission_status": "blocked",
            "coverage_status": "blocked",
            "blocked_reason": "servant_timeline_stat_source_blocked",
            "source_trace": stat_source.get("source_trace") or [],
        }
    speed_components = {
        "speed_base": ((stat_source.get("components") or {}).get("speed_base") or {}),
        "speed_inherit": ((stat_source.get("components") or {}).get("speed_inherit") or {}),
    }
    return {
        "admission_status": "executable",
        "coverage_status": "executable",
        "blocked_reason": "",
        "formula": "timeline.action_value = 10000 / servant.speed",
        "speed_formula": "owner.speed * speed_inherit + speed_base",
        "speed_components": _json_safe(speed_components),
        "timeline_rule_source": "TimelineRuleIR.default_v8_timeline_rule",
        "source_trace": _servant_component_source_trace(speed_components),
    }


def _servant_lifecycle_source(
    row: dict[str, Any],
    *,
    replacement_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    servant_id = str(row.get("ServantID") or "")
    config_path = str(row.get("Config") or "")
    if not config_path:
        return {
            "admission_status": "blocked",
            "coverage_status": "blocked",
            "blocked_reason": "servant_lifecycle_config_missing",
            "source_trace": [],
        }
    return {
        "admission_status": "executable",
        "coverage_status": "executable",
        "blocked_reason": "",
        "summon_kind": "servant",
        "representation": "unit",
        "presence": "field",
        "targetable": True,
        "actionable": True,
        "team_side_policy": "inherit_owner_combat_team",
        "lifetime_policy": "permanent_until_removed_or_owner_removed",
        "owner_removed_policy": "remove",
        "replacement_policy": replacement_policy
        or {
            "admission_status": "blocked",
            "mode": "replace_defeated_same_owner_servant",
            "blocked_reason": "create_servant_alive_only_guard_missing",
        },
        "source_trace": [
            {
                "source_path": "ExcelOutput/AvatarServantConfig.json",
                "raw_type": "AvatarServantConfig",
                "raw_id": servant_id,
                "evidence": {
                    "config_path": config_path,
                    "lifecycle_admission": "servant_unit_catalog",
                },
            }
        ],
    }


def _discover_servant_replacement_policies(
    tbgd_root: Path,
    ability_files: list[Path],
    *,
    servant_ids: frozenset[str] | None = None,
) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    for path in ability_files:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if servant_ids and not any(servant_id in raw for servant_id in servant_ids):
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        relative_path = path.relative_to(tbgd_root).as_posix()
        for node_path, node in _iter_json_dicts(data):
            raw_type = str(node.get("$type") or "")
            if not raw_type.endswith("PredicateTaskList"):
                continue
            predicate = node.get("Predicate")
            if not _is_zero_alive_servant_guard(predicate):
                continue
            success_tasks = node.get("SuccessTaskList")
            for create_path, create in _iter_json_dicts(
                success_tasks,
                f"{node_path}.SuccessTaskList",
            ):
                if not str(create.get("$type") or "").endswith("CreateServant"):
                    continue
                servant_id = _fixed_raw_id(create.get("ServantID"))
                if not servant_id:
                    continue
                if servant_ids is not None and servant_id not in servant_ids:
                    continue
                evidence = {
                    "admission_status": "executable",
                    "mode": "replace_defeated_same_owner_servant",
                    "blocked_reason": "",
                    "policy_schema_version": "servant_replacement_policy_v1",
                    "subject_kind": "servant",
                    "owner_scope": "same_owner",
                    "alive_filter": "alive_only",
                    "comparison": "less_equal_zero",
                    "replacement_operation": "remove_defeated_then_spawn",
                    "servant_id": servant_id,
                    "predicate_semantics": "alive_servant_count_less_equal_zero",
                    "source_path": relative_path,
                    "predicate_path": node_path,
                    "create_task_path": create_path,
                }
                existing = policies.get(servant_id)
                if existing is None or (
                    evidence["source_path"], evidence["predicate_path"]
                ) < (
                    str(existing.get("source_path") or ""),
                    str(existing.get("predicate_path") or ""),
                ):
                    policies[servant_id] = evidence
    return policies


def _discover_servant_spawn_sources(
    tbgd_root: Path,
    ability_files: list[Path],
    *,
    servant_ids: frozenset[str] | None = None,
) -> dict[str, tuple[IRSource, ...]]:
    by_servant: dict[str, list[IRSource]] = {}
    for path in ability_files:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if servant_ids and not any(servant_id in raw for servant_id in servant_ids):
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        relative_path = path.relative_to(tbgd_root).as_posix()
        for node_path, node in _iter_json_dicts(data):
            if not str(node.get("$type") or "").endswith("CreateServant"):
                continue
            servant_id = _fixed_raw_id(node.get("ServantID"))
            if not servant_id:
                continue
            if servant_ids is not None and servant_id not in servant_ids:
                continue
            dynamic_fields = tuple(
                sorted(
                    child_path
                    for child_path, child in _iter_json_dicts(node, node_path)
                    if child.get("IsDynamic") is True
                )
            )
            by_servant.setdefault(servant_id, []).append(
                IRSource(
                    source_path=relative_path,
                    raw_type="RPG.GameCore.CreateServant",
                    raw_id=f"{servant_id}:{node_path}",
                    evidence={
                        "servant_id": servant_id,
                        "json_path": node_path,
                        "payload_keys": sorted(str(key) for key in node),
                        "dynamic_field_paths": list(dynamic_fields),
                        "source_role": "servant_spawn_intent",
                    },
                )
            )
    return {
        servant_id: _dedupe_ir_sources(sources)
        for servant_id, sources in sorted(by_servant.items())
    }


def _owned_combatant_projection_build_issues(
    *,
    servant_rows: list[tuple[str, int, dict[str, Any]]],
    servant_definitions: list[ServantDefinitionIR],
    action_definitions: list[ActionDefinitionIR],
    action_ability_bindings: list[ActionAbilityBindingIR],
    action_admissions: list[ActionAdmissionIR],
    unit_birth_templates: list[UnitBirthTemplateIR],
) -> tuple[OwnedCombatantProjectionIssue, ...]:
    """Fail closed on identities and relationships required to construct the projection."""

    issues: list[OwnedCombatantProjectionIssue] = []
    raw_servant_ids = [str(row.get("ServantID") or "") for _, _, row in servant_rows]
    skill_lists = [row.get("SkillIDList") for _, _, row in servant_rows]
    raw_action_ids = {
        f"servant_skill:{skill_id}"
        for skill_ids in skill_lists
        if isinstance(skill_ids, list)
        for skill_id in skill_ids
    }
    definition_keys = Counter(
        (item.action_id, item.level) for item in action_definitions
    )
    checks = (
        (
            "servant_config_or_action_source_not_closed",
            bool(raw_servant_ids)
            and len(set(raw_servant_ids)) == len(raw_servant_ids)
            and all(isinstance(items, list) and items for items in skill_lists)
            and {item.action_id for item in action_definitions} == raw_action_ids,
        ),
        (
            "servant_definition_identity_not_closed",
            Counter(item.servant_ref for item in servant_definitions)
            == Counter(f"servant:{item}" for item in raw_servant_ids),
        ),
        (
            "action_definition_identity_not_closed",
            all(count == 1 for count in definition_keys.values()),
        ),
        (
            "action_ability_binding_identity_not_closed",
            Counter(
                (item.action_id, item.level) for item in action_ability_bindings
            )
            == definition_keys,
        ),
        (
            "action_admission_identity_not_closed",
            Counter(
                (item.action_id, item.action_level) for item in action_admissions
            )
            == definition_keys,
        ),
        (
            "unit_birth_template_identity_not_closed",
            Counter(item.birth_template_id for item in unit_birth_templates)
            == Counter(
                item.birth_template_id
                for item in servant_definitions
                if item.birth_template_id
            ),
        ),
    )
    for code, ok in checks:
        if not ok:
            issues.append(OwnedCombatantProjectionIssue(code, code))

    for servant in servant_definitions:
        if (
            servant.coverage_status == "executable" and not servant.owner_relations
        ) or (
            not servant.spawn_sources
            and (
                servant.coverage_status != "blocked"
                or "servant_spawn_source_missing" not in servant.blocked_reason
            )
        ) or any(
            relation.coverage_status != "executable"
            or not relation.sources
            or not set(relation.auxiliary_skill_ids).issubset(servant.skill_ids)
            for relation in servant.owner_relations
        ):
            issues.append(
                OwnedCombatantProjectionIssue(
                    "servant_relationship_not_closed", servant.servant_ref
                )
            )
    return tuple(sorted(issues))


def _iter_json_dicts(value: Any, path: str = "$"):
    if isinstance(value, dict):
        yield path, value
        for key, item in value.items():
            yield from _iter_json_dicts(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_json_dicts(item, f"{path}[{index}]")


def _is_zero_alive_servant_guard(value: Any) -> bool:
    if not isinstance(value, dict) or not str(value.get("$type") or "").endswith("ByCompareTargetCount"):
        return False
    target = value.get("TargetType")
    alias = str(target.get("Alias") or "") if isinstance(target, dict) else ""
    return (
        "Servant" in alias
        and value.get("AliveOnly") is True
        and str(value.get("CompareType") or "") in {"LessEqual", "Equal"}
        and _fixed_raw_number(value.get("Number")) == 0.0
    )


def _fixed_raw_id(value: Any) -> str:
    number = _fixed_raw_number(value)
    return str(int(number)) if number is not None and number.is_integer() else ""


def _fixed_raw_number(value: Any) -> float | None:
    if not isinstance(value, dict) or value.get("IsDynamic") is not False:
        return None
    fixed = value.get("FixedValue")
    raw = fixed.get("Value") if isinstance(fixed, dict) else None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    return None


def _servant_definition_blocked_reason(
    *,
    owner_relations: tuple[ServantOwnerRelationIR, ...],
    config_path: str,
    ability_path: str,
    ability_data: dict[str, Any] | None,
    action_set_status: str,
    stat_source: dict[str, Any],
    timeline_source: dict[str, Any],
    lifecycle_source: dict[str, Any],
    spawn_sources: tuple[IRSource, ...],
) -> str:
    reasons: list[str] = []
    if not owner_relations:
        reasons.append("servant_owner_relation_missing")
    if any(relation.coverage_status != "executable" for relation in owner_relations):
        reasons.append("servant_owner_relation_not_executable")
    if not spawn_sources:
        reasons.append("servant_spawn_source_missing")
    if not config_path:
        reasons.append("servant_character_config_path_missing")
    if not ability_path or not isinstance(ability_data, dict):
        reasons.append("servant_ability_file_missing_or_unreadable")
    if action_set_status != "executable":
        reasons.append("servant_action_set_not_executable")
    for label, source in (
        ("stat", stat_source),
        ("timeline", timeline_source),
        ("lifecycle", lifecycle_source),
    ):
        if source.get("admission_status") != "executable":
            reasons.append(str(source.get("blocked_reason") or f"servant_{label}_source_blocked"))
    return ";".join(dict.fromkeys(reason for reason in reasons if reason))


def _ability_map(ability_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ability_list = ability_data.get("AbilityList")
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(ability_list, list):
        return result
    for ability in ability_list:
        if not isinstance(ability, dict):
            continue
        name = ability.get("Name") or ability.get("AbilityName")
        if isinstance(name, str) and name:
            result[name] = ability
    return result


def _lower_equipment_parameter_reads(
    *,
    graph_ref_id: str,
    ability: dict[str, Any],
    ability_source: IRSource,
    ability_name: str,
    record_index: int,
    target_definition_key: EquipmentDefinitionKey,
) -> tuple[list[EquipmentAbilityParameterReadIR], bool]:
    dynamic_values = ability.get("DynamicValues")
    if not isinstance(dynamic_values, dict):
        return [], False
    fingerprint = thaw_json(ability_source.evidence.get("source_fingerprint"))
    if not isinstance(fingerprint, dict):
        return [], True
    reads: list[EquipmentAbilityParameterReadIR] = []
    invalid = False
    for value_type, values in sorted(dynamic_values.items(), key=lambda item: str(item[0])):
        if not isinstance(value_type, str) or not isinstance(values, dict):
            continue
        for dynamic_hash, value_definition in sorted(
            values.items(),
            key=lambda item: str(item[0]),
        ):
            if not isinstance(value_definition, dict):
                continue
            read_info = value_definition.get("ReadInfo")
            if not isinstance(read_info, dict):
                continue
            read_type = read_info.get("Type")
            if read_type not in {"SkillEquip", "SkillRelic"}:
                continue
            if read_type == "SkillEquip":
                parameter_basis_kind = "light_cone_rank"
                parameter_basis_identity = ""
                trigger_key = read_info.get("TriggerKey")
                if (
                    target_definition_key.definition_kind != "light_cone"
                    or trigger_key not in {None, ""}
                ):
                    invalid = True
                    continue
            else:
                parameter_basis_kind = "relic_set_threshold"
                parameter_basis_identity = (
                    target_definition_key.definition_identity
                )
                expected_trigger = parameter_basis_identity.replace(":", "_")
                if (
                    target_definition_key.definition_kind
                    != "relic_set_threshold"
                    or read_info.get("TriggerKey") != expected_trigger
                ):
                    invalid = True
                    continue
            parameter_index = read_info.get("Index")
            dynamic_hash_text = str(dynamic_hash)
            if (
                not dynamic_hash_text
                or not isinstance(parameter_index, int)
                or isinstance(parameter_index, bool)
                or parameter_index < 0
            ):
                invalid = True
                continue
            parameter_read_id = (
                f"equipment_parameter_read:{ability_source.source_path}:"
                f"json_path:$.AbilityList[{record_index}]:"
                f"value_type:{value_type}:dynamic_hash:{dynamic_hash_text}:"
                f"parameter_index:{parameter_index}"
            )
            reads.append(
                EquipmentAbilityParameterReadIR(
                    parameter_read_id=parameter_read_id,
                    graph_ref_id=graph_ref_id,
                    dynamic_hash=dynamic_hash_text,
                    parameter_index=parameter_index,
                    value_type=value_type,
                    parameter_basis_kind=parameter_basis_kind,
                    parameter_basis_identity=parameter_basis_identity,
                    source=make_equipment_source(
                        source_path=ability_source.source_path,
                        raw_type="EquipmentAbilityParameterRead",
                        raw_id=(
                            f"{ability_name}:{dynamic_hash_text}:{parameter_index}"
                        ),
                        json_path=(
                            f"$.AbilityList[{record_index}].DynamicValues."
                            f"{value_type}.{dynamic_hash_text}.ReadInfo"
                        ),
                        source_fingerprint=fingerprint,
                    ),
                    coverage_status="lowered",
                    blocked_reason="",
                )
            )
    read_ids = tuple(item.parameter_read_id for item in reads)
    dynamic_hashes = tuple(item.dynamic_hash for item in reads)
    if len(read_ids) != len(set(read_ids)) or len(dynamic_hashes) != len(set(dynamic_hashes)):
        invalid = True
    return sorted(reads, key=lambda item: (item.parameter_index, item.dynamic_hash)), invalid


def _attach_equipment_mechanism_refs(
    light_cone_definitions: tuple[LightConeDefinitionIR, ...],
    relic_set_thresholds: tuple[RelicSetThresholdIR, ...],
    graphs: list[StandaloneAbilityGraphIR],
    parameter_reads: list[EquipmentAbilityParameterReadIR],
) -> tuple[
    tuple[LightConeDefinitionIR, ...],
    tuple[RelicSetThresholdIR, ...],
    tuple[EquipmentMechanismRefIR, ...],
]:
    graphs_by_source: dict[tuple[str, str, str, str, str], list[StandaloneAbilityGraphIR]] = {}
    for graph in graphs:
        graphs_by_source.setdefault(_equipment_source_identity(graph.source), []).append(graph)
    reads_by_graph: dict[str, list[EquipmentAbilityParameterReadIR]] = {}
    for parameter_read in parameter_reads:
        reads_by_graph.setdefault(parameter_read.graph_ref_id, []).append(parameter_read)

    mechanism_refs: list[EquipmentMechanismRefIR] = []

    def link_definition(
        definition: LightConeDefinitionIR | RelicSetThresholdIR,
    ) -> LightConeDefinitionIR | RelicSetThresholdIR:
        ability_source = definition.ability_source
        if ability_source is None:
            return definition
        matching_graphs = graphs_by_source.get(
            _equipment_source_identity(ability_source.source),
            (),
        )
        if len(matching_graphs) != 1:
            return definition
        graph = matching_graphs[0]
        definition_kind = definition.definition_key.definition_kind
        mechanism_key = EquipmentDefinitionKey(
            "equipment_mechanism",
            (
                f"{definition_kind}:"
                f"{definition.definition_key.definition_identity}:"
                f"ability_record:{ability_source.record_index}"
            ),
        )
        graph_reads = tuple(
            sorted(
                reads_by_graph.get(graph.standalone_ability_graph_id, ()),
                key=lambda item: (
                    item.parameter_index,
                    item.dynamic_hash,
                    item.parameter_read_id,
                ),
            )
        )
        mechanism_refs.append(
            EquipmentMechanismRefIR(
                definition_key=mechanism_key,
                graph_ref_id=graph.standalone_ability_graph_id,
                parameter_binding_ids=tuple(
                    item.parameter_read_id for item in graph_reads
                ),
                source=ability_source.source,
                coverage_status=(
                    "executable"
                    if graph.coverage_status == "executable"
                    else "lowered"
                ),
                blocked_reason="",
            )
        )
        return replace(
            definition,
            mechanism_ref_ids=(mechanism_key,),
        )

    return (
        tuple(
            link_definition(definition)
            for definition in light_cone_definitions
        ),
        tuple(
            link_definition(definition)
            for definition in relic_set_thresholds
        ),
        tuple(mechanism_refs),
    )


def _admitted_equipment_ability_definitions(
    definitions: tuple[
        LightConeDefinitionIR | RelicSetThresholdIR,
        ...,
    ],
) -> tuple[LightConeDefinitionIR | RelicSetThresholdIR, ...]:
    """Admit one unambiguous definition declaration per physical ability row."""

    definitions_by_row: dict[
        tuple[str, int],
        list[LightConeDefinitionIR | RelicSetThresholdIR],
    ] = {}
    for definition in definitions:
        ability_source = definition.ability_source
        if ability_source is None:
            continue
        definitions_by_row.setdefault(
            (
                ability_source.source.source_path,
                ability_source.record_index,
            ),
            [],
        ).append(definition)

    admitted: list[LightConeDefinitionIR | RelicSetThresholdIR] = []
    for row_key in sorted(definitions_by_row):
        candidates = definitions_by_row[row_key]
        first = candidates[0]
        first_source = first.ability_source
        declaration = (
            type(first),
            first.definition_key,
            first_source,
        )
        if any(
            (
                type(candidate),
                candidate.definition_key,
                candidate.ability_source,
            )
            != declaration
            for candidate in candidates[1:]
        ):
            continue
        admitted.append(first)
    return tuple(admitted)


def _equipment_ability_source_projection(
    definitions: tuple[
        LightConeDefinitionIR | RelicSetThresholdIR,
        ...,
    ],
) -> dict[str, dict[int, IRSource]]:
    sources: dict[str, dict[int, IRSource]] = {}
    for definition in _admitted_equipment_ability_definitions(definitions):
        ability_source = definition.ability_source
        if ability_source is None:
            continue
        sources.setdefault(
            ability_source.source.source_path,
            {},
        )[ability_source.record_index] = ability_source.source
    return sources


def _equipment_source_identity(source: IRSource) -> tuple[str, str, str, str, str]:
    fingerprint = source.evidence.get("source_fingerprint")
    fingerprint_sha = (
        str(fingerprint.get("sha256") or "")
        if isinstance(fingerprint, dict)
        else ""
    )
    return (
        source.source_path,
        source.raw_type,
        source.raw_id,
        str(source.evidence.get("json_path") or ""),
        fingerprint_sha,
    )


def _ability_opcode_summary(ability: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for opcode in _iter_gamecore_opcodes(ability):
        counts[opcode] = counts.get(opcode, 0) + 1
    return {
        "opcode_counts": dict(sorted(counts.items())),
        "task_count": sum(counts.values()),
        "raw_task_summary_only": True,
    }


def _ability_callback_summaries(ability: dict[str, Any]) -> dict[str, Any]:
    return {
        "on_start": _callback_summary(ability.get("OnStart")),
        "on_attack": _callback_summary(ability.get("OnAttack")),
        "on_hit": _callback_summary(ability.get("OnHit")),
        "on_end": _callback_summary(ability.get("OnEnd")),
    }


def _callback_summary(value: Any) -> dict[str, Any]:
    opcodes = _iter_gamecore_opcodes(value)
    counts: dict[str, int] = {}
    for opcode in opcodes:
        counts[opcode] = counts.get(opcode, 0) + 1
    return {"opcode_counts": dict(sorted(counts.items())), "task_count": len(opcodes)}


def _iter_gamecore_opcodes(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        raw_type = value.get("$type")
        if isinstance(raw_type, str):
            found.append(_short_gamecore_type(raw_type))
        for nested in value.values():
            found.extend(_iter_gamecore_opcodes(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_gamecore_opcodes(nested))
    return found


def _binding_blocked_reason(
    binding: ActionAbilityBindingIR | None,
    phases: tuple[AbilityPhaseIR, ...],
) -> str:
    if binding is None:
        return "action_ability_binding_missing"
    if binding.coverage_status != "executable":
        return binding.blocked_reason or f"action_ability_binding_{binding.coverage_status}"
    if not phases:
        return "ability_phase_graph_missing"
    return ""


def _lower_action_execution_ir(
    definitions: list[ActionDefinitionIR],
    bindings: list[ActionAbilityBindingIR],
    phases: list[AbilityPhaseIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
    bounce_policies: list[BouncePolicyIR],
) -> tuple[list[ActionEventIR], list[HitProfileIR]]:
    binding_by_action = {(binding.action_id, binding.level): binding for binding in bindings}
    formula_bindings_by_action: dict[tuple[str, int], list[SkillFormulaBindingIR]] = {}
    for formula_binding in skill_formula_bindings:
        formula_bindings_by_action.setdefault((formula_binding.action_id, formula_binding.level), []).append(formula_binding)
    bounce_policy_by_action = {(policy.action_id, policy.level): policy for policy in bounce_policies}
    phases_by_binding: dict[str, list[AbilityPhaseIR]] = {}
    for phase in phases:
        phases_by_binding.setdefault(phase.binding_id, []).append(phase)
    events: list[ActionEventIR] = []
    profiles: list[HitProfileIR] = []
    for definition in definitions:
        action_profiles = _hit_profiles_from_definition(
            definition,
            tuple(formula_bindings_by_action.get((definition.action_id, definition.level), ())),
            bounce_policy_by_action.get((definition.action_id, definition.level)),
        )
        profiles.extend(action_profiles)
        binding = binding_by_action.get((definition.action_id, definition.level))
        binding_phases = tuple(sorted(
            phases_by_binding.get(binding.binding_id if binding else "", []),
            key=lambda phase: (phase.phase_index, phase.phase_id),
        ))
        events.append(_action_event_from_definition(definition, action_profiles, binding, binding_phases))
    return events, profiles


def _lower_damage_emissions(
    tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    hit_profiles: list[HitProfileIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
    damage_tag_registry: dict[int, tuple[dict[str, Any], ...]],
) -> list[DamageEmissionIR]:
    effect_by_id = {effect.effect_id: effect for effect in effects}
    direct_basis_bindings = _direct_damage_binding_lookup(skill_formula_bindings)
    profiles_by_action: dict[tuple[str, int], list[HitProfileIR]] = {}
    tasks_by_action: dict[tuple[str, int], list[AbilityTaskIR]] = {}
    for profile in hit_profiles:
        profiles_by_action.setdefault((profile.action_id, profile.level), []).append(profile)
    for task in tasks:
        if task.opcode in DAMAGE_EMISSION_OPCODES:
            tasks_by_action.setdefault((task.action_id, task.level), []).append(task)

    emissions: list[DamageEmissionIR] = []
    for action_key, action_tasks in tasks_by_action.items():
        action_profiles = tuple(sorted(
            profiles_by_action.get(action_key, ()),
            key=lambda profile: (profile.hit_index, profile.target_group, profile.hit_profile_id),
        ))
        for task in sorted(action_tasks, key=lambda item: (item.phase_id, item.callback_kind, item.task_path, item.task_id)):
            effect = effect_by_id.get(task.effect_id)
            target_profiles = _target_profiles_for_damage_task(
                action_profiles,
                task,
                effect,
            )
            for profile in target_profiles:
                damage_tags, damage_tag_sources, damage_tag_blocked_reason = (
                    _attack_property_damage_tags(
                        effect.payload if effect else {},
                        damage_tag_registry,
                    )
                )
                scaling_basis_expr = _damage_scaling_basis_expr(task, effect, profile, direct_basis_bindings)
                scaling_ratio_expr = _damage_task_scaling_ratio_expr(
                    task,
                    effect,
                    profile,
                    direct_basis_bindings,
                )
                blocked_reason = _damage_emission_blocked_reason(
                    task,
                    effect,
                    profile,
                    scaling_basis_expr,
                    scaling_ratio_expr,
                )
                if not blocked_reason:
                    blocked_reason = damage_tag_blocked_reason
                source = _damage_emission_source(
                    task,
                    effect,
                    profile,
                    damage_tags=damage_tags,
                    damage_tag_sources=damage_tag_sources,
                )
                emissions.append(
                    DamageEmissionIR(
                        damage_emission_id=_damage_emission_id(task, profile),
                        action_id=task.action_id,
                        level=task.level,
                        phase_id=task.phase_id,
                        source_task_id=task.task_id,
                        hit_profile_id=profile.hit_profile_id if profile else "",
                        target_group=profile.target_group if profile else "unknown",
                        damage_formula_family=profile.damage_formula_family if profile else "unknown",
                        element_type=profile.element_type if profile else None,
                        scaling_ratio_expr=scaling_ratio_expr,
                        scaling_basis_expr=scaling_basis_expr,
                        source=source,
                        coverage_status="blocked" if blocked_reason else "executable",
                        blocked_reason=blocked_reason,
                        damage_custom_name=_attack_property_custom_name(effect.payload if effect else {}),
                        damage_tags=damage_tags,
                    )
                )
    return emissions


def _attach_status_formula_bindings_to_add_modifier_effects(
    effects: list[EffectIR],
    tasks: list[AbilityTaskIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
) -> list[EffectIR]:
    dot_bindings_by_action: dict[tuple[str, int], list[SkillFormulaBindingIR]] = {}
    for binding in skill_formula_bindings:
        if binding.formula_role != "dot_damage":
            continue
        if binding.coverage_status != "executable":
            continue
        dot_bindings_by_action.setdefault((binding.action_id, binding.level), []).append(binding)
    if not dot_bindings_by_action:
        return effects

    task_by_effect_id = {task.effect_id: task for task in tasks if task.effect_id}
    updated: list[EffectIR] = []
    for effect in effects:
        if effect.opcode != "AddModifier":
            updated.append(effect)
            continue
        task = task_by_effect_id.get(effect.effect_id)
        if task is None:
            updated.append(effect)
            continue
        bindings = tuple(sorted(
            dot_bindings_by_action.get((task.action_id, task.level), ()),
            key=lambda item: (item.sequence_order, item.param_index, item.binding_id),
        ))
        if not bindings:
            updated.append(effect)
            continue
        payload = dict(effect.payload)
        standard = dict(payload.get("standard")) if isinstance(payload.get("standard"), dict) else {}
        standard["status_formula_bindings"] = [binding.to_json() for binding in bindings]
        standard["status_formula_binding_source"] = {
            "source_kind": "character_data_card_status_formula_slots",
            "action_id": task.action_id,
            "action_level": task.level,
            "task_id": task.task_id,
            "binding_count": len(bindings),
        }
        payload["standard"] = standard
        updated.append(
            EffectIR(
                effect_id=effect.effect_id,
                opcode=effect.opcode,
                payload=payload,
                source=effect.source,
                coverage_status=effect.coverage_status,
                modifier_definition_id=effect.modifier_definition_id,
                status_callback_ids=effect.status_callback_ids,
                source_mode=effect.source_mode,
                link_blocked_reason=effect.link_blocked_reason,
                owner_modifier_name=effect.owner_modifier_name,
            )
        )
    return updated


def _lower_toughness_emissions(
    tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    hit_profiles: list[HitProfileIR],
) -> list[ToughnessEmissionIR]:
    effect_by_id = {effect.effect_id: effect for effect in effects}
    profiles_by_action: dict[tuple[str, int], list[HitProfileIR]] = {}
    tasks_by_action: dict[tuple[str, int], list[AbilityTaskIR]] = {}
    for profile in hit_profiles:
        profiles_by_action.setdefault((profile.action_id, profile.level), []).append(profile)
    for task in tasks:
        if task.opcode in DAMAGE_EMISSION_OPCODES:
            tasks_by_action.setdefault((task.action_id, task.level), []).append(task)

    emissions: list[ToughnessEmissionIR] = []
    for action_key, action_tasks in tasks_by_action.items():
        action_profiles = tuple(sorted(
            profiles_by_action.get(action_key, ()),
            key=lambda profile: (profile.hit_index, profile.target_group, profile.hit_profile_id),
        ))
        for task in sorted(action_tasks, key=lambda item: (item.phase_id, item.callback_kind, item.task_path, item.task_id)):
            effect = effect_by_id.get(task.effect_id)
            target_profiles = _target_profiles_for_damage_task(
                action_profiles,
                task,
                effect,
            )
            for profile in target_profiles:
                blocked_reason = _toughness_emission_blocked_reason(task, effect, profile)
                emissions.append(
                    ToughnessEmissionIR(
                        toughness_emission_id=_toughness_emission_id(task, profile),
                        action_id=task.action_id,
                        level=task.level,
                        phase_id=task.phase_id,
                        source_task_id=task.task_id,
                        hit_profile_id=profile.hit_profile_id if profile else "",
                        target_group=profile.target_group if profile else "unknown",
                        element_type=profile.element_type if profile else None,
                        toughness_amount_expr=_toughness_amount_expr(effect, profile),
                        source=_toughness_emission_source(task, effect, profile),
                        coverage_status="blocked" if blocked_reason else "executable",
                        blocked_reason=blocked_reason,
                    )
                )
    return emissions


def _admit_damage_ability_tasks(
    tasks: list[AbilityTaskIR],
    damage_emissions: list[DamageEmissionIR],
    toughness_emissions: list[ToughnessEmissionIR],
    hit_profiles: list[HitProfileIR],
) -> list[AbilityTaskIR]:
    damage_by_task: dict[str, list[DamageEmissionIR]] = {}
    toughness_by_task: dict[str, list[ToughnessEmissionIR]] = {}
    profiles_by_id: dict[str, list[HitProfileIR]] = {}
    for emission in damage_emissions:
        damage_by_task.setdefault(emission.source_task_id, []).append(emission)
    for emission in toughness_emissions:
        toughness_by_task.setdefault(emission.source_task_id, []).append(emission)
    for profile in hit_profiles:
        profiles_by_id.setdefault(profile.hit_profile_id, []).append(profile)

    admitted: list[AbilityTaskIR] = []
    for task in tasks:
        if task.opcode not in DAMAGE_EMISSION_OPCODES:
            admitted.append(task)
            continue

        reasons: list[str] = []
        task_damage = damage_by_task.get(task.task_id, ())
        task_toughness = toughness_by_task.get(task.task_id, ())
        if task.execution_mode != "runtime_effect":
            reasons.append(
                f"damage_task_execution_mode_not_admitted:{task.execution_mode}"
            )
        if not task_damage:
            reasons.append("damage_emission_missing")

        damage_by_profile: dict[str, list[DamageEmissionIR]] = {}
        for emission in task_damage:
            damage_by_profile.setdefault(emission.hit_profile_id, []).append(emission)
            if emission.action_id != task.action_id or emission.level != task.level:
                reasons.append("damage_emission_action_binding_mismatch")
            if emission.phase_id != task.phase_id:
                reasons.append("damage_emission_phase_binding_mismatch")
            if emission.coverage_status != "executable":
                reasons.append(
                    emission.blocked_reason
                    or f"damage_emission_not_executable:{emission.coverage_status}"
                )
            profiles = profiles_by_id.get(emission.hit_profile_id, ())
            if len(profiles) != 1:
                reasons.append(
                    "damage_hit_profile_missing"
                    if not profiles
                    else "damage_hit_profile_ambiguous"
                )
                continue
            profile = profiles[0]
            if profile.action_id != task.action_id or profile.level != task.level:
                reasons.append("damage_hit_profile_action_binding_mismatch")
            if profile.coverage_status != "executable":
                reasons.append(
                    profile.blocked_reason
                    or f"damage_hit_profile_not_executable:{profile.coverage_status}"
                )

        for emissions in damage_by_profile.values():
            if len(emissions) != 1:
                reasons.append("damage_emission_hit_profile_ambiguous")

        toughness_by_profile: dict[str, list[ToughnessEmissionIR]] = {}
        for emission in task_toughness:
            toughness_by_profile.setdefault(emission.hit_profile_id, []).append(emission)
            if emission.action_id != task.action_id or emission.level != task.level:
                reasons.append("toughness_emission_action_binding_mismatch")
            if emission.phase_id != task.phase_id:
                reasons.append("toughness_emission_phase_binding_mismatch")
            if emission.coverage_status != "executable":
                reasons.append(
                    emission.blocked_reason
                    or f"toughness_emission_not_executable:{emission.coverage_status}"
                )
            profiles = profiles_by_id.get(emission.hit_profile_id, ())
            if len(profiles) != 1:
                reasons.append(
                    "toughness_hit_profile_missing"
                    if not profiles
                    else "toughness_hit_profile_ambiguous"
                )
            elif profiles[0].coverage_status != "executable":
                reasons.append(
                    profiles[0].blocked_reason
                    or "toughness_hit_profile_not_executable"
                )

        for emissions in toughness_by_profile.values():
            if len(emissions) != 1:
                reasons.append("toughness_emission_hit_profile_ambiguous")
        damage_profile_ids = set(damage_by_profile)
        toughness_profile_ids = set(toughness_by_profile)
        if damage_profile_ids - toughness_profile_ids:
            reasons.append("toughness_emission_missing_for_damage_hit_profile")
        if toughness_profile_ids - damage_profile_ids:
            reasons.append("toughness_emission_without_damage_hit_profile")

        blocked_reason = ";".join(
            dict.fromkeys(reason for reason in reasons if reason)
        )
        admitted.append(
            replace(
                task,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
            )
        )
    return admitted


def _target_profiles_for_damage_task(
    action_profiles: tuple[HitProfileIR, ...],
    task: AbilityTaskIR,
    effect: EffectIR | None,
) -> tuple[HitProfileIR | None, ...]:
    if not action_profiles:
        return (None,)
    task_scoped_profiles = tuple(
        profile
        for profile in action_profiles
        if isinstance(profile.target_selection_policy, dict)
        and bool(profile.target_selection_policy.get("task_id"))
    )
    if task_scoped_profiles:
        matching = tuple(
            profile
            for profile in task_scoped_profiles
            if profile.target_selection_policy.get("task_id") == task.task_id
        )
        if matching:
            return matching
    target_alias = _target_alias(effect.payload.get("TargetType")) if effect is not None else None
    if target_alias in {"AbilityTargetEntity", "CurrentActionTarget"}:
        matching = tuple(
            profile
            for profile in action_profiles
            if profile.target_group in {"primary", "selected"}
            or profile.target_group.startswith("bounce:")
        )
    elif target_alias == "AbilityTargetAdjoinEntity":
        matching = tuple(
            profile for profile in action_profiles if profile.target_group == "adjacent"
        )
    elif target_alias == "AllEnemy":
        matching = tuple(
            profile for profile in action_profiles if profile.target_group == "selected"
        )
    else:
        matching = ()
    return matching or (None,)


def _lower_standalone_hit_profiles(
    tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
) -> list[HitProfileIR]:
    effect_by_id = {effect.effect_id: effect for effect in effects}
    bindings_by_action: dict[tuple[str, int], list[SkillFormulaBindingIR]] = {}
    for binding in skill_formula_bindings:
        if binding.formula_role != "direct_damage":
            continue
        if not binding.action_id.startswith("standalone_ability:"):
            continue
        bindings_by_action.setdefault((binding.action_id, binding.level), []).append(binding)
    profiles: list[HitProfileIR] = []
    for task in sorted(tasks, key=lambda item: (item.action_id, item.phase_id, item.callback_kind, item.task_path, item.task_id)):
        if task.opcode != "DamageByAttackProperty":
            continue
        effect = effect_by_id.get(task.effect_id)
        payload = effect.payload if effect is not None else {}
        target_alias = _target_alias(payload.get("TargetType")) if isinstance(payload, dict) else None
        target_group = _standalone_target_group(target_alias)
        binding = _standalone_binding_for_damage_task(
            tuple(bindings_by_action.get((task.action_id, task.level), ())),
            effect,
        )
        blocked_reason = ""
        if target_group == "unknown":
            blocked_reason = f"standalone_damage_target_alias_not_admitted:{target_alias or 'missing'}"
        elif binding is None:
            blocked_reason = "standalone_damage_skill_formula_binding_missing"
        elif binding.coverage_status != "executable":
            blocked_reason = binding.blocked_reason or f"skill_formula_binding_not_executable:{binding.coverage_status}"
        multiplier_expr = _binding_param_multiplier_expr(binding, effect) if binding is not None else {"kind": "missing", "blocked_reason": "standalone_damage_skill_formula_binding_missing"}
        profiles.append(
            HitProfileIR(
                hit_profile_id=(
                    f"hit_profile:{task.action_id}:{task.level}:"
                    f"{len(profiles)}:{target_group}:task:{_safe_id(task.task_path)}"
                ),
                action_id=task.action_id,
                level=task.level,
                hit_index=len(profiles),
                target_group=target_group,
                multiplier_expr=multiplier_expr,
                multiplier_source=_standalone_multiplier_source(task, effect, binding),
                stance_expr={"kind": "missing", "blocked_reason": "standalone_show_stance_not_present"},
                stance_source={"source_kind": "standalone_ability_damage_task", "task_source": task.source.to_json()},
                damage_formula_family="direct",
                element_type=_attack_property_element_type(payload.get("AttackProperty")) if isinstance(payload.get("AttackProperty"), dict) else None,
                source=binding.source if binding is not None else task.source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
                numeric_fidelity_status="trusted_for_current_scope" if not blocked_reason else "blocked",
                target_selection_policy={
                    "target_alias": target_alias or "",
                    "source_kind": "standalone_ability_damage_task",
                    "task_id": task.task_id,
                },
            )
        )
    return profiles


def _project_standalone_skill_formula_bindings(
    tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    existing_bindings: list[SkillFormulaBindingIR],
) -> list[SkillFormulaBindingIR]:
    """Project parent skill parameters through explicit TriggerAbility links."""

    effect_by_id = {effect.effect_id: effect for effect in effects}
    available: dict[tuple[str, str], SkillFormulaBindingIR] = {}
    for binding in existing_bindings:
        dynamic_hash = binding.scaling_basis_expr.get("dynamic_hash")
        if (
            binding.formula_role != "direct_damage"
            or binding.coverage_status != "executable"
            or not binding.action_id.startswith("standalone_ability:")
            or dynamic_hash is None
        ):
            continue
        available.setdefault((binding.action_id, str(dynamic_hash)), binding)

    projected: list[SkillFormulaBindingIR] = []
    trigger_tasks = tuple(
        task
        for task in sorted(tasks, key=lambda item: (item.action_id, item.task_id))
        if task.opcode == "TriggerAbility" and task.linked_standalone_graph_id
    )
    for _depth in range(4):
        added = False
        for task in trigger_tasks:
            effect = effect_by_id.get(task.effect_id)
            standard = effect.payload.get("standard") if effect is not None and isinstance(effect.payload, dict) else None
            child_name = standard.get("ability_name") if isinstance(standard, dict) else None
            if not isinstance(child_name, str) or not child_name:
                continue
            child_action_id = f"standalone_ability:{child_name}"
            parent_bindings = tuple(
                (dynamic_hash, binding)
                for (action_id, dynamic_hash), binding in available.items()
                if action_id == task.action_id
            )
            for dynamic_hash, source_binding in parent_bindings:
                key = (child_action_id, dynamic_hash)
                if key in available:
                    continue
                projection = replace(
                    source_binding,
                    binding_id=f"skill_formula_binding:{child_action_id}:0:direct_damage:hash:{dynamic_hash}",
                    formula_slot_id=f"formula_slot:{child_action_id}:0:direct_damage:hash:{dynamic_hash}",
                    action_id=child_action_id,
                    level=0,
                    sequence_order=len(projected),
                    matched_text="DamageByAttackProperty.DamagePercentage:trigger_ability_projection",
                    source=IRSource(
                        source_path=source_binding.source.source_path,
                        raw_type="StandaloneSkillFormulaBindingProjection",
                        raw_id=f"{task.task_id}:{dynamic_hash}",
                        evidence={
                            "source_binding_id": source_binding.binding_id,
                            "source_trigger_task_id": task.task_id,
                            "linked_standalone_graph_id": task.linked_standalone_graph_id,
                            "parent_action_id": task.action_id,
                            "child_action_id": child_action_id,
                            "dynamic_hash": dynamic_hash,
                            "projection_kind": "trigger_ability_parameter_inheritance",
                        },
                    ),
                )
                projected.append(projection)
                available[key] = projection
                added = True
        if not added:
            break
    for task in sorted(tasks, key=lambda item: (item.action_id, item.task_id)):
        if task.opcode != "DamageByAttackProperty":
            continue
        effect = effect_by_id.get(task.effect_id)
        dynamic_hash = _damage_percentage_dynamic_hash(effect)
        if dynamic_hash is None:
            continue
        key = (task.action_id, str(dynamic_hash))
        if key in available:
            continue
        source_entries: list[dict[str, Any]] = []
        for binding_source in _numeric_binding_sources_from_task(task):
            by_hash = binding_source.get("by_hash")
            entry = by_hash.get(str(dynamic_hash)) if isinstance(by_hash, dict) else None
            if isinstance(entry, dict) and entry.get("admission_status") == "executable":
                source_entries.append(entry)
        source_context = task.source.evidence.get("ability_source_context")
        binding_summary = (
            source_context.get("skill_param_dynamic_bindings")
            if isinstance(source_context, dict)
            else None
        )
        summary_entries = binding_summary.get("entries") if isinstance(binding_summary, dict) else None
        if isinstance(summary_entries, list):
            source_entries.extend(
                entry
                for entry in summary_entries
                if isinstance(entry, dict)
                and str(entry.get("hash")) == str(dynamic_hash)
                and entry.get("admission_status") == "executable"
            )
        values = {
            float(entry["value"])
            for entry in source_entries
            if isinstance(entry.get("value"), (int, float)) and not isinstance(entry.get("value"), bool)
        }
        if len(values) != 1:
            continue
        entry = sorted(source_entries, key=lambda item: (str(item.get("source_path") or ""), str(item.get("param_index"))))[0]
        source_trace = entry.get("source_trace") if isinstance(entry.get("source_trace"), dict) else {}
        value = values.pop()
        projection = SkillFormulaBindingIR(
            binding_id=f"skill_formula_binding:{task.action_id}:0:direct_damage:hash:{dynamic_hash}",
            character_data_card_id="",
            data_card_id="",
            data_card_kind="monster",
            owner_entity_ref="",
            formula_slot_id=f"formula_slot:{task.action_id}:0:direct_damage:hash:{dynamic_hash}",
            action_id=task.action_id,
            level=task.level,
            param_index=int(entry.get("param_index")) if isinstance(entry.get("param_index"), int) else -1,
            sequence_order=len(projected),
            formula_role="direct_damage",
            target_group_hint="",
            param_value=value,
            scaling_basis_expr={
                "kind": "unit_stat",
                "unit_ref": "attacker",
                "stat": "attack",
                "source_kind": "standalone_task_numeric_binding_source_projection",
                "admission_status": "executable",
                "dynamic_hash": str(dynamic_hash),
                "param_index": entry.get("param_index"),
                "param_value": value,
            },
            text_hash="",
            skill_text="",
            matched_text="DamageByAttackProperty.DamagePercentage:task_source_projection",
            source=IRSource(
                source_path=str(source_trace.get("source_path") or entry.get("source_path") or task.source.source_path),
                raw_type="StandaloneSkillFormulaBindingProjection",
                raw_id=f"{task.task_id}:{dynamic_hash}",
                evidence={
                    "source_task_id": task.task_id,
                    "dynamic_hash": str(dynamic_hash),
                    "binding_entry": _json_safe(entry),
                    "projection_kind": "ability_source_context_numeric_binding",
                },
            ),
            coverage_status="executable",
            blocked_reason="",
        )
        projected.append(projection)
        available[key] = projection
    return projected


def _standalone_target_group(target_alias: str | None) -> str:
    if target_alias in {"AbilityTargetEntity", "CurrentActionTarget"}:
        return "selected"
    if target_alias == "AllEnemy":
        return "selected"
    return "unknown"


def _standalone_binding_for_damage_task(
    bindings: tuple[SkillFormulaBindingIR, ...],
    effect: EffectIR | None,
) -> SkillFormulaBindingIR | None:
    if not bindings:
        return None
    effect_hash = _damage_percentage_dynamic_hash(effect)
    candidates = tuple(binding for binding in bindings if str(binding.scaling_basis_expr.get("dynamic_hash")) == str(effect_hash))
    if candidates:
        return sorted(candidates, key=lambda item: item.binding_id)[0]
    return sorted(bindings, key=lambda item: item.binding_id)[0] if effect_hash is None and len(bindings) == 1 else None


def _binding_param_multiplier_expr(binding: SkillFormulaBindingIR | None, effect: EffectIR | None = None) -> dict[str, Any]:
    if binding is None:
        return {"kind": "missing", "blocked_reason": "skill_formula_binding_missing"}
    value = _value_field(binding.param_value)
    attack_property = effect.payload.get("AttackProperty") if effect is not None and isinstance(effect.payload, dict) else None
    damage_percentage = attack_property.get("DamagePercentage") if isinstance(attack_property, dict) else None
    expr = _numeric_expr_summary(damage_percentage)
    dynamic_hash = _damage_percentage_dynamic_hash(effect)
    if expr.get("kind") in {"dynamic_hash", "postfix_expr"} and dynamic_hash is not None and isinstance(value, (int, float)):
        expr = dict(expr)
        expr["binding_source"] = _skill_formula_binding_runtime_source(binding, dynamic_hash, float(value))
        expr["source_kind"] = f"{_skill_formula_source_kind(binding)}_damage_percentage_expr"
        return expr
    if isinstance(value, (int, float)):
        return {"kind": "fixed", "value": float(value)}
    return {"kind": "missing", "blocked_reason": "skill_formula_binding_param_value_not_numeric"}


def _skill_formula_binding_runtime_source(
    binding: SkillFormulaBindingIR,
    dynamic_hash: str,
    value: float,
) -> dict[str, Any]:
    entry_key = f"skill_formula_binding:{binding.binding_id}"
    entry = {
        "scope": "skill_formula_binding",
        "owner_id": binding.owner_entity_ref,
        "status_id": None,
        "status_instance_id": None,
        "effect_id": None,
        "name": None,
        "hash": str(dynamic_hash),
        "value": float(value),
        "source_trace": binding.source.to_json(),
    }
    return {
        "source_type": "skill_formula_binding",
        "entries": {entry_key: entry},
        "by_hash": {str(dynamic_hash): entry_key},
        "by_name": {},
    }


def _standalone_multiplier_source(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    binding: SkillFormulaBindingIR | None,
) -> dict[str, Any]:
    source = {
        "source_kind": _skill_formula_source_kind(binding) if binding else "standalone_ability_missing_formula_binding",
        "task_id": task.task_id,
        "task_source": task.source.to_json(),
        "effect_id": effect.effect_id if effect is not None else "",
        "effect_source": effect.source.to_json() if effect is not None else {},
    }
    if binding is not None:
        source.update(
            {
                "raw_path": f"ParamList[{binding.param_index}]",
                "raw_value": _json_safe(binding.param_value),
                "param_index": binding.param_index,
                "skill_formula_binding_id": binding.binding_id,
                "formula_slot_id": binding.formula_slot_id,
                "sequence_order": binding.sequence_order,
                "target_group_hint": binding.target_group_hint,
                "character_data_card_id": binding.character_data_card_id,
                "data_card_id": _formula_binding_data_card_id(binding),
                "data_card_kind": binding.data_card_kind,
                "owner_entity_ref": binding.owner_entity_ref,
                "skill_formula_binding_source": binding.source.to_json(),
            }
        )
    return source


def _damage_emission_id(task: AbilityTaskIR, profile: HitProfileIR | None) -> str:
    hit_id = profile.hit_profile_id if profile else "missing_hit_profile"
    return f"damage_emission:{task.task_id}:{hit_id}"


def _direct_damage_binding_lookup(
    bindings: list[SkillFormulaBindingIR],
) -> dict[tuple[str, int, int], SkillFormulaBindingIR]:
    lookup: dict[tuple[str, int, int], SkillFormulaBindingIR] = {}
    for binding in sorted(bindings, key=lambda item: item.binding_id):
        if binding.formula_role != "direct_damage":
            continue
        if not _formula_binding_data_card_id(binding):
            continue
        key = (binding.action_id, binding.level, binding.param_index)
        existing = lookup.get(key)
        if existing is None or (
            existing.coverage_status != "executable" and binding.coverage_status == "executable"
        ):
            lookup[key] = binding
    return lookup


def _formula_binding_data_card_id(binding: SkillFormulaBindingIR) -> str:
    return binding.data_card_id or binding.character_data_card_id


def _skill_formula_source_kind(binding: SkillFormulaBindingIR | None) -> str:
    if binding is None:
        return "action_definition_param_list"
    if binding.data_card_kind:
        return f"{binding.data_card_kind}_data_card_skill_formula"
    return "character_data_card_skill_formula"


def _damage_percentage_hash_mismatch(
    effect: EffectIR | None,
    binding: SkillFormulaBindingIR,
) -> str:
    data_card_kind = binding.data_card_kind or ""
    if data_card_kind not in {"monster", "servant"}:
        return ""
    effect_hash = _damage_percentage_dynamic_hash(effect)
    if effect_hash is None:
        return f"{data_card_kind}_damage_percentage_dynamic_hash_missing"
    binding_hash = binding.scaling_basis_expr.get("dynamic_hash")
    if binding_hash is None:
        binding_hash = binding.source.evidence.get("dynamic_hash")
    if str(binding_hash) != str(effect_hash):
        return f"{data_card_kind}_damage_percentage_dynamic_hash_mismatch"
    return ""


def _damage_percentage_dynamic_hash(effect: EffectIR | None) -> str | None:
    if effect is None:
        return None
    attack_property = effect.payload.get("AttackProperty") if isinstance(effect.payload, dict) else None
    if not isinstance(attack_property, dict):
        return None
    expr = _numeric_expr_summary(attack_property.get("DamagePercentage"))
    hashes = tuple(item for item in numeric_dynamic_hashes(expr) if item is not None)
    if len(hashes) == 1:
        return str(hashes[0])
    return None


def _damage_emission_source(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
    *,
    damage_tags: tuple[str, ...],
    damage_tag_sources: tuple[dict[str, Any], ...],
) -> IRSource:
    payload = effect.payload if effect else {}
    return IRSource(
        source_path=task.source.source_path,
        raw_type="AbilityDamageEmission",
        raw_id=task.opcode,
        evidence={
            **task.source.evidence,
            "task_id": task.task_id,
            "effect_id": task.effect_id,
            "target_alias": _target_alias(payload.get("TargetType")),
            "damage_custom_name": _attack_property_custom_name(payload),
            "damage_tags": list(damage_tags),
            "damage_tag_sources": list(damage_tag_sources),
            "hit_profile_id": profile.hit_profile_id if profile else "",
            "hit_profile_source": profile.source.to_json() if profile else None,
        },
    )


def _damage_scaling_basis_expr(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
    direct_basis_bindings: dict[tuple[str, int, int], SkillFormulaBindingIR],
) -> dict[str, Any]:
    if profile is None or profile.damage_formula_family != "direct":
        return {
            "kind": "missing",
            "supported": False,
            "reason": "damage_scaling_basis_not_applicable",
        }
    payload = effect.payload if effect else {}
    param_index = _hit_profile_param_index(profile)
    binding = direct_basis_bindings.get((task.action_id, task.level, param_index))
    if binding is None:
        return {
            "kind": "missing",
            "supported": False,
            "reason": "character_data_card_skill_formula_missing",
            "param_index": param_index,
            "source_trace": {
                "task_source": task.source.to_json(),
                "effect_id": task.effect_id,
                "target_alias": _target_alias(payload.get("TargetType")),
                "hit_profile_id": profile.hit_profile_id,
                "hit_profile_source": profile.source.to_json(),
            },
        }
    if binding.coverage_status != "executable":
        return {
            "kind": "missing",
            "supported": False,
            "reason": binding.blocked_reason or f"character_data_card_skill_formula_{binding.coverage_status}",
            "param_index": param_index,
            "source_trace": {
                "task_source": task.source.to_json(),
                "effect_id": task.effect_id,
                "target_alias": _target_alias(payload.get("TargetType")),
                "hit_profile_id": profile.hit_profile_id,
                "hit_profile_source": profile.source.to_json(),
                "skill_formula_binding": binding.to_json(),
                "character_data_card_id": binding.character_data_card_id,
                "data_card_id": _formula_binding_data_card_id(binding),
            },
        }
    hash_mismatch = _damage_percentage_hash_mismatch(effect, binding)
    if hash_mismatch:
        return {
            "kind": "missing",
            "supported": False,
            "reason": hash_mismatch,
            "param_index": param_index,
            "source_trace": {
                "task_source": task.source.to_json(),
                "effect_id": task.effect_id,
                "target_alias": _target_alias(payload.get("TargetType")),
                "hit_profile_id": profile.hit_profile_id,
                "hit_profile_source": profile.source.to_json(),
                "skill_formula_binding": binding.to_json(),
                "data_card_id": _formula_binding_data_card_id(binding),
            },
        }
    basis_expr = dict(binding.scaling_basis_expr)
    source_trace = basis_expr.get("source_trace")
    if not isinstance(source_trace, dict):
        source_trace = {}
    basis_expr["source_trace"] = {
        **source_trace,
        "task_source": task.source.to_json(),
        "effect_id": task.effect_id,
        "target_alias": _target_alias(payload.get("TargetType")),
        "hit_profile_id": profile.hit_profile_id,
        "hit_profile_source": profile.source.to_json(),
        "skill_formula_binding": binding.to_json(),
        "character_data_card_id": binding.character_data_card_id,
        "data_card_id": _formula_binding_data_card_id(binding),
    }
    return basis_expr


def _damage_task_scaling_ratio_expr(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
    direct_basis_bindings: dict[tuple[str, int, int], SkillFormulaBindingIR],
) -> dict[str, Any]:
    if profile is None:
        return numeric_missing("damage_emission_hit_profile_missing")
    binding = direct_basis_bindings.get(
        (task.action_id, task.level, _hit_profile_param_index(profile))
    )
    expression = (
        _binding_param_multiplier_expr(binding, effect)
        if binding is not None
        else dict(profile.multiplier_expr)
    )
    attack_property = (
        effect.payload.get("AttackProperty")
        if effect is not None and isinstance(effect.payload, dict)
        else None
    )
    if not isinstance(attack_property, dict) or "HitSplitRatio" not in attack_property:
        return expression
    split_expression = lower_numeric_expression(attack_property.get("HitSplitRatio"))
    split_value = _fixed_expr_value(split_expression)
    if split_value is None:
        return numeric_missing("damage_hit_split_ratio_not_fixed")
    return _multiply_numeric_expression_by_fixed(expression, split_value)


def _multiply_numeric_expression_by_fixed(
    expression: dict[str, Any],
    factor: float,
) -> dict[str, Any]:
    fixed_value = _fixed_expr_value(expression)
    if fixed_value is not None:
        return {
            "schema_version": NUMERIC_EXPRESSION_SCHEMA,
            "kind": "fixed",
            "value": fixed_value * factor,
            "supported": True,
        }
    if not is_typed_numeric_expression(expression):
        return numeric_missing("damage_scaling_ratio_not_lowered")
    kind = str(expression.get("kind") or "")
    if kind == "dynamic_hash":
        instructions: list[dict[str, Any]] = [
            {"opcode": "push_dynamic", "hash": expression.get("hash")},
            {"opcode": "push_fixed", "value": factor},
            {"opcode": "mul"},
            {"opcode": "end"},
        ]
    elif kind == "program" and isinstance(expression.get("instructions"), list):
        original = list(expression["instructions"])
        if not original or original[-1] != {"opcode": "end"}:
            return numeric_missing("damage_scaling_ratio_program_end_missing")
        instructions = [
            *original[:-1],
            {"opcode": "push_fixed", "value": factor},
            {"opcode": "mul"},
            {"opcode": "end"},
        ]
    else:
        return numeric_missing("damage_scaling_ratio_not_multipliable")
    result: dict[str, Any] = {
        "schema_version": NUMERIC_EXPRESSION_SCHEMA,
        "kind": "program",
        "instructions": instructions,
        "supported": True,
        "hit_split_ratio": factor,
    }
    binding_source = expression.get("binding_source")
    if isinstance(binding_source, dict):
        result["binding_source"] = binding_source
    return result


def _hit_profile_param_index(profile: HitProfileIR) -> int:
    source = profile.multiplier_source
    raw_path = str(source.get("raw_path") or "")
    match = re.search(r"ParamList\[(\d+)\]", raw_path)
    if match:
        return int(match.group(1))
    return 0


def _damage_emission_blocked_reason(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
    scaling_basis_expr: dict[str, Any],
    scaling_ratio_expr: dict[str, Any],
) -> str:
    if effect is None:
        return "damage_emission_effect_missing"
    payload = effect.payload
    target_alias = _target_alias(payload.get("TargetType"))
    if target_alias not in DAMAGE_EMISSION_TARGET_ALIASES:
        return f"unsupported_damage_target_alias:{target_alias}"
    if not isinstance(payload.get("AttackProperty"), dict):
        return "damage_emission_attack_property_missing"
    if profile is None:
        return "damage_emission_hit_profile_missing"
    target_group_reason = _damage_emission_target_group_blocked_reason(target_alias, profile.target_group)
    if target_group_reason:
        return target_group_reason
    if profile.coverage_status != "executable":
        return f"hit_profile_not_executable:{profile.blocked_reason or profile.coverage_status}"
    if profile.damage_formula_family != "direct":
        return f"damage_emission_family_not_executable:{profile.damage_formula_family}"
    if not _numeric_expr_can_be_runtime_bound(scaling_ratio_expr):
        return "damage_emission_scaling_ratio_not_runtime_bound"
    if scaling_basis_expr.get("kind") != "unit_stat" or scaling_basis_expr.get("admission_status") != "executable":
        reason = str(scaling_basis_expr.get("reason") or "character_data_card_skill_formula_missing")
        return f"damage_scaling_basis_not_admitted:{reason}"
    return ""


def _damage_emission_target_group_blocked_reason(target_alias: str | None, target_group: str) -> str:
    if target_alias in {"AbilityTargetEntity", "CurrentActionTarget"}:
        if target_group in {"primary", "selected"} or target_group.startswith("bounce:"):
            return ""
        return f"damage_target_group_mismatch:{target_alias}:{target_group}"
    if target_alias == "AbilityTargetAdjoinEntity":
        return "" if target_group == "adjacent" else f"damage_target_group_mismatch:{target_alias}:{target_group}"
    if target_alias == "AllEnemy":
        return "" if target_group == "selected" else f"damage_target_group_mismatch:{target_alias}:{target_group}"
    return f"unsupported_damage_target_alias:{target_alias}"


def _servant_damage_target_group_hint(target_alias: str | None) -> str:
    if target_alias in {"AbilityTargetEntity", "CurrentActionTarget"}:
        return "primary"
    if target_alias == "AbilityTargetAdjoinEntity":
        return "adjacent"
    if target_alias == "AllEnemy":
        return "all_enemy"
    return ""


def _toughness_emission_id(task: AbilityTaskIR, profile: HitProfileIR | None) -> str:
    hit_id = profile.hit_profile_id if profile else "missing_hit_profile"
    return f"toughness_emission:{task.task_id}:{hit_id}"


def _toughness_emission_source(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
) -> IRSource:
    payload = effect.payload if effect else {}
    return IRSource(
        source_path=task.source.source_path,
        raw_type="AbilityToughnessEmission",
        raw_id=task.opcode,
        evidence={
            **task.source.evidence,
            "task_id": task.task_id,
            "effect_id": task.effect_id,
            "target_alias": _target_alias(payload.get("TargetType")),
            "hit_profile_id": profile.hit_profile_id if profile else "",
            "hit_profile_source": profile.source.to_json() if profile else None,
            "stance_source": profile.stance_source if profile else {},
            "toughness_amount_source": _toughness_amount_expr(effect, profile),
            "attack_property": _json_safe(payload.get("AttackProperty")) if isinstance(payload, dict) else {},
        },
    )


def _toughness_emission_blocked_reason(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
) -> str:
    if effect is None:
        return "toughness_emission_effect_missing"
    payload = effect.payload
    target_alias = _target_alias(payload.get("TargetType"))
    if target_alias not in DAMAGE_EMISSION_TARGET_ALIASES:
        return f"unsupported_toughness_target_alias:{target_alias}"
    if not isinstance(payload.get("AttackProperty"), dict):
        return "toughness_emission_attack_property_missing"
    if profile is None:
        return "toughness_emission_hit_profile_missing"
    target_group_reason = _damage_emission_target_group_blocked_reason(target_alias, profile.target_group)
    if target_group_reason:
        return target_group_reason.replace("damage_", "toughness_", 1)
    if profile.coverage_status != "executable":
        return f"hit_profile_not_executable:{profile.blocked_reason or profile.coverage_status}"
    amount_expr = _toughness_amount_expr(effect, profile)
    if not _numeric_expr_can_be_runtime_bound(amount_expr):
        return amount_expr.get("reason") or amount_expr.get("blocked_reason") or "toughness_amount_not_executable"
    return ""


def _toughness_amount_expr(effect: EffectIR | None, profile: HitProfileIR | None = None) -> dict[str, Any]:
    if effect is None:
        return {"kind": "missing", "reason": "toughness_emission_effect_missing"}
    attack_property = effect.payload.get("AttackProperty") if isinstance(effect.payload, dict) else None
    if not isinstance(attack_property, dict):
        return {"kind": "missing", "reason": "toughness_emission_attack_property_missing"}
    if "StanceValue" not in attack_property:
        return _monster_sp_hit_toughness_amount_expr(effect, profile, attack_property)
    expr = _numeric_expr_summary(attack_property.get("StanceValue"))
    return {
        **expr,
        "raw_path": "AttackProperty.StanceValue",
        "source_kind": "ability_task_attack_property_stance_value",
    }


def _monster_sp_hit_toughness_amount_expr(
    effect: EffectIR,
    profile: HitProfileIR | None,
    attack_property: dict[str, Any],
) -> dict[str, Any]:
    if profile is None:
        return {"kind": "missing", "reason": "attack_property_stance_value_missing"}
    action_source = profile.stance_source.get("source") if isinstance(profile.stance_source, dict) else None
    if not isinstance(action_source, dict):
        action_source = profile.source.to_json()
    action_evidence = action_source.get("evidence") if isinstance(action_source, dict) else {}
    sp_hit_base_raw = action_evidence.get("sp_hit_base") if isinstance(action_evidence, dict) else None
    sp_hit_base = _number_value(sp_hit_base_raw, float("nan"))
    sp_hit_ratio_expr = _numeric_expr_summary(attack_property.get("SPHitRatio"))
    sp_hit_ratio = _fixed_expr_value(sp_hit_ratio_expr)
    if not isinstance(sp_hit_base, float) or sp_hit_base != sp_hit_base:
        return {
            "kind": "missing",
            "reason": "attack_property_stance_value_missing",
            "secondary_reason": "monster_sp_hit_base_missing",
            "raw_path": "ActionDefinition.source.evidence.sp_hit_base",
            "source_kind": "monster_skill_sp_hit_base",
            "source_trace": action_source,
        }
    if sp_hit_ratio is None:
        return {
            "kind": "missing",
            "reason": "monster_sp_hit_ratio_not_fixed",
            "raw_path": "AttackProperty.SPHitRatio",
            "source_kind": "monster_skill_sp_hit_ratio",
            "sp_hit_ratio_expr": sp_hit_ratio_expr,
            "source_trace": effect.source.to_json(),
        }
    return {
        "kind": "fixed",
        "value": sp_hit_base * sp_hit_ratio,
        "source_kind": "monster_skill_sp_hit_base_times_attack_property_sp_hit_ratio",
        "raw_path": "MonsterSkillConfig.SPHitBase * AttackProperty.SPHitRatio",
        "sp_hit_base": sp_hit_base,
        "sp_hit_base_raw": _json_safe(sp_hit_base_raw),
        "sp_hit_ratio": sp_hit_ratio,
        "sp_hit_ratio_expr": sp_hit_ratio_expr,
        "source_trace": {
            "action_definition": action_source,
            "effect": effect.source.to_json(),
        },
    }


def _action_event_from_definition(
    definition: ActionDefinitionIR,
    hit_profiles: list[HitProfileIR],
    binding: ActionAbilityBindingIR | None,
    phases: tuple[AbilityPhaseIR, ...],
) -> ActionEventIR:
    has_damage = definition.damage_kind == "hp_damage" and any(
        profile.coverage_status != "blocked" for profile in hit_profiles
    )
    has_attack_windows = _action_definition_is_attack(definition)
    binding_blocked_reason = _binding_blocked_reason(binding, phases)
    target_relation = definition.target_relation
    if target_relation == "unknown":
        target_relation = _target_relation_from_ability_phases(phases)
    if target_relation == "unknown":
        target_relation = _target_relation_from_action_semantics(definition)
    target_blocked_reason = _action_event_target_blocked_reason(
        definition,
        hit_profiles,
        target_relation,
    )
    blocked_reason = ",".join(reason for reason in (binding_blocked_reason, target_blocked_reason) if reason)
    status = "blocked" if blocked_reason else "lowered"
    source = binding.source if binding and binding.coverage_status == "executable" else definition.source
    binding_id = binding.binding_id if binding else ""
    phase_ids = tuple(phase.phase_id for phase in phases)
    source_mode = binding.source_mode if binding else "missing_binding"
    event_source_status = "ability_phase_graph_bound" if binding and binding.coverage_status == "executable" else "blocked_missing_or_incomplete_ability_binding"
    steps: list[ActionPhaseStepIR] = [
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="before_skill_use",
            canonical_window="before_skill_use",
            tbgd_event="OnBeforeSkillUse",
            coverage_status=status,
            blocked_reason=blocked_reason,
            source=source,
        )
    ]
    if has_attack_windows and not blocked_reason:
        steps.append(
            ActionPhaseStepIR(
                kind="trigger_window",
                phase="before_attack",
                canonical_window="before_attack",
                tbgd_event="OnBeforeAttack",
                coverage_status="lowered",
                source=source,
            )
        )
    if has_damage and not blocked_reason:
        steps.append(
            ActionPhaseStepIR(
                kind="damage",
                phase="damage",
                coverage_status="lowered",
                source=source,
            )
        )
    if has_attack_windows and not blocked_reason:
        steps.append(
            ActionPhaseStepIR(
                kind="trigger_window",
                phase="after_attack",
                canonical_window="after_attack",
                tbgd_event="OnAfterAttack",
                coverage_status="lowered",
                source=source,
            )
        )
    steps.append(
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="after_skill_use",
            canonical_window="after_skill_use",
            tbgd_event="OnAfterSkillUse",
            coverage_status=status,
            blocked_reason=blocked_reason,
            source=source,
        )
    )
    return ActionEventIR(
        action_event_id=f"action_event:{definition.action_id}:{definition.level}",
        action_id=definition.action_id,
        level=definition.level,
        target_mode=definition.target_mode,
        selection_mode=_selection_mode(definition.target_mode),
        phase_steps=tuple(steps),
        hit_profile_ids=tuple(profile.hit_profile_id for profile in hit_profiles),
        derived_status="derived_from_ability_phase_graph" if not blocked_reason else "blocked_action_ability_binding",
        derived_reason=(
            "phase windows are projected from ActionAbilityBindingIR/AbilityPhaseIR evidence; "
            "individual Ability task execution is not implemented in v0_221"
        ),
        source=source,
        coverage_status=status,
        blocked_reason=blocked_reason,
        binding_id=binding_id,
        phase_ids=phase_ids,
        source_mode=source_mode,
        event_source_status=event_source_status,
        target_relation=target_relation,
    )


def _action_event_target_blocked_reason(
    definition: ActionDefinitionIR,
    hit_profiles: list[HitProfileIR],
    target_relation: str,
) -> str:
    if target_relation == "unknown":
        return "action_target_relation_not_lowered"
    if definition.target_mode == "bounce" and any(
        profile.coverage_status == "executable" and profile.bounce_policy_id for profile in hit_profiles
    ):
        return ""
    return _target_blocked_reason(definition.target_mode)


def _hit_profiles_from_definition(
    definition: ActionDefinitionIR,
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...] = (),
    bounce_policy: BouncePolicyIR | None = None,
) -> list[HitProfileIR]:
    if definition.damage_kind != "hp_damage":
        return []
    formula_hit_profiles = _hit_profiles_from_skill_formula_bindings(definition, skill_formula_bindings, bounce_policy)
    if formula_hit_profiles:
        return formula_hit_profiles
    groups = _hit_target_groups(definition.target_mode)
    if not groups:
        groups = (definition.target_mode or "unknown",)
    profiles: list[HitProfileIR] = []
    for hit_index, target_group in enumerate(groups):
        blocked_reason = _hit_profile_blocked_reason(definition, target_group)
        if (
            not blocked_reason
            and definition.action_id.startswith("avatar_skill:")
            and definition.damage_formula_family == "direct"
        ):
            blocked_reason = "skill_text_scaling_basis_binding_missing"
        profiles.append(
            HitProfileIR(
                hit_profile_id=f"hit_profile:{definition.action_id}:{definition.level}:{hit_index}:{target_group}",
                action_id=definition.action_id,
                level=definition.level,
                hit_index=hit_index,
                target_group=target_group,
                multiplier_expr=_param_multiplier_expr(definition.param_list, 0),
                multiplier_source=_param_multiplier_source(definition, 0),
                stance_expr=_stance_expr(definition.show_stance_list),
                stance_source=_stance_source(definition),
                damage_formula_family=definition.damage_formula_family,
                element_type=definition.element_type,
                source=definition.source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
                numeric_fidelity_status=_numeric_fidelity_status(definition, target_group),
            )
        )
    return profiles


def _hit_profiles_from_skill_formula_bindings(
    definition: ActionDefinitionIR,
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...],
    bounce_policy: BouncePolicyIR | None = None,
) -> list[HitProfileIR]:
    if definition.damage_formula_family != "direct":
        return []
    if definition.target_mode == "bounce":
        return _bounce_hit_profiles_from_skill_formula_bindings(definition, skill_formula_bindings, bounce_policy)
    selected: list[SkillFormulaBindingIR] = []
    seen: set[tuple[int, str]] = set()
    for binding in sorted(skill_formula_bindings, key=lambda item: (item.sequence_order, item.param_index, item.binding_id)):
        if binding.formula_role != "direct_damage":
            continue
        target_group = _target_group_from_formula_binding(definition, binding)
        key = (binding.param_index, target_group)
        if key in seen:
            continue
        seen.add(key)
        selected.append(binding)
    profiles: list[HitProfileIR] = []
    for hit_index, binding in enumerate(selected):
        target_group = _target_group_from_formula_binding(definition, binding)
        blocked_reason = _hit_profile_blocked_reason(definition, target_group)
        if binding.coverage_status != "executable":
            blocked_reason = binding.blocked_reason or f"skill_formula_binding_not_executable:{binding.coverage_status}"
        param_reason = _param_index_blocked_reason(definition.param_list, binding.param_index)
        if param_reason and not blocked_reason:
            blocked_reason = param_reason
        profiles.append(
            HitProfileIR(
                hit_profile_id=(
                    f"hit_profile:{definition.action_id}:{definition.level}:"
                    f"{hit_index}:{target_group}:slot:{binding.sequence_order}"
                ),
                action_id=definition.action_id,
                level=definition.level,
                hit_index=hit_index,
                target_group=target_group,
                multiplier_expr=_param_multiplier_expr(definition.param_list, binding.param_index),
                multiplier_source=_param_multiplier_source(definition, binding.param_index, binding),
                stance_expr=_stance_expr(definition.show_stance_list),
                stance_source=_stance_source(definition),
                damage_formula_family=definition.damage_formula_family,
                element_type=definition.element_type,
                source=binding.source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
                numeric_fidelity_status=_numeric_fidelity_status(definition, target_group),
            )
        )
    return profiles


def _bounce_hit_profiles_from_skill_formula_bindings(
    definition: ActionDefinitionIR,
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...],
    bounce_policy: BouncePolicyIR | None,
) -> list[HitProfileIR]:
    direct_bindings = [
        binding
        for binding in sorted(skill_formula_bindings, key=lambda item: (item.sequence_order, item.param_index, item.binding_id))
        if binding.formula_role == "direct_damage"
    ]
    primary_binding = next((binding for binding in direct_bindings if binding.target_group_hint != "random"), None)
    bounce_binding = next((binding for binding in direct_bindings if binding.target_group_hint == "random"), primary_binding)
    if primary_binding is None and bounce_binding is None:
        return []
    policy_blocked_reason = _bounce_policy_blocked_reason(bounce_policy)
    entries: list[tuple[str, SkillFormulaBindingIR | None, int]] = []
    entries.append(("primary", primary_binding or bounce_binding, 0))
    bounce_count = bounce_policy.bounce_count if bounce_policy and bounce_policy.coverage_status == "executable" else 0
    for index in range(bounce_count):
        entries.append((f"bounce:{index}", bounce_binding, index + 1))
    if not bounce_count and bounce_binding is not None:
        entries.append(("bounce:0", bounce_binding, 1))
    profiles: list[HitProfileIR] = []
    for hit_index, (target_group, binding, sequence_order) in enumerate(entries):
        blocked_reason = policy_blocked_reason if target_group.startswith("bounce:") else ""
        if binding is None:
            blocked_reason = blocked_reason or "bounce_skill_formula_binding_missing"
            source = definition.source
            multiplier_expr = _param_multiplier_expr(definition.param_list, 0)
            multiplier_source = _param_multiplier_source(definition, 0)
            target_selection_policy: dict[str, Any] = {}
        else:
            if binding.coverage_status != "executable":
                blocked_reason = blocked_reason or binding.blocked_reason or f"skill_formula_binding_not_executable:{binding.coverage_status}"
            param_reason = _param_index_blocked_reason(definition.param_list, binding.param_index)
            if param_reason and not blocked_reason:
                blocked_reason = param_reason
            source = binding.source
            multiplier_expr = _param_multiplier_expr(definition.param_list, binding.param_index)
            multiplier_source = _param_multiplier_source(definition, binding.param_index, binding)
            target_selection_policy = {
                "target_group_hint": binding.target_group_hint,
                "formula_slot_id": binding.formula_slot_id,
                "skill_formula_binding_id": binding.binding_id,
            }
        if bounce_policy is not None:
            target_selection_policy = {
                **target_selection_policy,
                "bounce_policy": bounce_policy.to_json(),
            }
        profiles.append(
            HitProfileIR(
                hit_profile_id=(
                    f"hit_profile:{definition.action_id}:{definition.level}:"
                    f"{hit_index}:{target_group}:slot:{sequence_order}"
                ),
                action_id=definition.action_id,
                level=definition.level,
                hit_index=hit_index,
                target_group=target_group,
                multiplier_expr=multiplier_expr,
                multiplier_source=multiplier_source,
                stance_expr=_stance_expr(definition.show_stance_list),
                stance_source=_stance_source(definition),
                damage_formula_family=definition.damage_formula_family,
                element_type=definition.element_type,
                source=source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
                numeric_fidelity_status="trusted_for_current_scope" if not blocked_reason else "blocked",
                bounce_policy_id=bounce_policy.bounce_policy_id if bounce_policy is not None else "",
                target_selection_policy=target_selection_policy,
            )
        )
    return profiles


def _target_group_from_formula_binding(
    definition: ActionDefinitionIR,
    binding: SkillFormulaBindingIR,
) -> str:
    hint = binding.target_group_hint
    if definition.target_mode == "blast":
        return "adjacent" if hint == "adjacent" else "primary"
    if definition.target_mode in {"single", "aoe"}:
        return "selected"
    if definition.target_mode in {"bounce", "unknown"}:
        return "bounce" if hint == "random" else "primary"
    return "selected"


def _hit_target_groups(target_mode: str) -> tuple[str, ...]:
    if target_mode == "blast":
        return ("primary", "adjacent")
    if target_mode in {"single", "aoe"}:
        return ("selected",)
    if target_mode in {"bounce", "unknown"}:
        return (target_mode,)
    return ()


def _bounce_policy_blocked_reason(policy: BouncePolicyIR | None) -> str:
    if policy is None:
        return "bounce_policy_missing_from_character_data_card"
    if policy.coverage_status != "executable":
        return policy.blocked_reason or f"bounce_policy_not_executable:{policy.coverage_status}"
    return ""


def _hit_profile_blocked_reason(definition: ActionDefinitionIR, target_group: str) -> str:
    target_reason = _target_blocked_reason(definition.target_mode)
    if target_reason:
        return target_reason
    if definition.damage_formula_family not in {"direct", "true_damage", "hp_loss", "elation"}:
        return f"damage_formula_family_not_executable:{definition.damage_formula_family}"
    if target_group in {"adjacent", "selected"} and definition.target_mode in {"aoe", "blast"}:
        return ""
    return ""


def _param_multiplier_expr(param_list: tuple[Any, ...], param_index: int = 0) -> dict[str, Any]:
    if not param_list:
        return {"kind": "missing", "blocked_reason": "missing_param_list"}
    if param_index < 0 or param_index >= len(param_list):
        return {"kind": "missing", "blocked_reason": "param_list_index_out_of_range", "param_index": param_index}
    item = param_list[param_index]
    value = _number_value(item, 0.0)
    if _param_value_is_fixed(item):
        return {"kind": "fixed", "value": value}
    return {"kind": "unsupported", "raw": _json_safe(item), "blocked_reason": "param_list_multiplier_not_fixed"}


def _param_multiplier_source(
    definition: ActionDefinitionIR,
    param_index: int = 0,
    binding: SkillFormulaBindingIR | None = None,
) -> dict[str, Any]:
    item = definition.param_list[param_index] if 0 <= param_index < len(definition.param_list) else None
    source = {
        "raw_path": f"ParamList[{param_index}]",
        "raw_value": _json_safe(item),
        "param_index": param_index,
        "param_list_count": len(definition.param_list),
        "multi_param_list_not_implemented": False,
        "show_damage_count": len(definition.show_damage_list),
        "show_damage_audit_only": bool(definition.show_damage_list),
        "source_kind": _skill_formula_source_kind(binding) if binding else "action_definition_param_list",
        "source": definition.source.to_json(),
    }
    if binding is not None:
        source.update(
            {
                "skill_formula_binding_id": binding.binding_id,
                "formula_slot_id": binding.formula_slot_id,
                "sequence_order": binding.sequence_order,
                "target_group_hint": binding.target_group_hint,
                "character_data_card_id": binding.character_data_card_id,
                "data_card_id": _formula_binding_data_card_id(binding),
                "data_card_kind": binding.data_card_kind,
                "owner_entity_ref": binding.owner_entity_ref,
                "skill_formula_binding_source": binding.source.to_json(),
            }
        )
    return source


def _stance_expr(show_stance_list: tuple[Any, ...]) -> dict[str, Any]:
    if not show_stance_list:
        return {"kind": "missing", "blocked_reason": "show_stance_not_present"}
    first = show_stance_list[0]
    return {
        "kind": "audit_only",
        "raw": _json_safe(first),
        "blocked_reason": "show_stance_semantics_not_confirmed",
    }


def _stance_source(definition: ActionDefinitionIR) -> dict[str, Any]:
    first = definition.show_stance_list[0] if definition.show_stance_list else None
    return {
        "raw_path": "ShowStanceList[0]",
        "raw_value": _json_safe(first),
        "show_stance_count": len(definition.show_stance_list),
        "show_stance_audit_only": bool(definition.show_stance_list),
        "stance_damage_type": definition.stance_damage_type,
        "source": definition.source.to_json(),
    }


def _param_multiplier_is_fixed(param_list: tuple[Any, ...]) -> bool:
    if not param_list:
        return False
    first = param_list[0]
    return _param_value_is_fixed(first)


def _param_value_is_fixed(value: Any) -> bool:
    if isinstance(value, dict):
        return isinstance(value.get("Value"), (int, float))
    return isinstance(value, (int, float))


def _param_index_blocked_reason(param_list: tuple[Any, ...], param_index: int) -> str:
    if param_index < 0:
        return "param_list_index_invalid"
    if param_index >= len(param_list):
        return "param_list_index_out_of_range"
    if not _param_value_is_fixed(param_list[param_index]):
        return "param_list_multiplier_not_fixed"
    return ""


def _numeric_fidelity_status(definition: ActionDefinitionIR, target_group: str) -> str:
    if definition.target_mode in {"aoe", "blast"}:
        return "structural_only"
    if len(definition.param_list) > 1 or definition.show_damage_list or definition.show_stance_list:
        return "structural_only"
    if target_group in {"bounce", "unknown"}:
        return "blocked"
    return "single_hit_ratio"


def _target_blocked_reason(target_mode: str) -> str:
    if target_mode == "bounce":
        return "bounce_not_executable"
    if target_mode == "unknown":
        return "unknown_target_mode_not_executable"
    if target_mode not in {"single", "aoe", "blast", "self_or_team"}:
        return f"unsupported_target_mode:{target_mode}"
    return ""


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


def _action_definition_is_attack(definition: ActionDefinitionIR) -> bool:
    skill_effect = definition.skill_effect.lower()
    attack_type = definition.attack_type.lower()
    if definition.target_mode in {"single", "blast", "aoe", "bounce"}:
        return True
    return "attack" in skill_effect or "attack" in attack_type


def _target_mode(skill_effect: str) -> str:
    normalized = skill_effect.lower()
    if normalized in {"singleattack", "mazeattack"}:
        return "single"
    if normalized == "blast":
        return "blast"
    if normalized in {"aoeattack", "aoe"}:
        return "aoe"
    if normalized == "bounce":
        return "bounce"
    if normalized == "enhance":
        return "self_or_team"
    return "unknown"


def _monster_target_mode(target_type: str) -> str:
    if target_type == "AllEnemy":
        return "aoe"
    if target_type == "EnemySelect":
        return "single"
    if target_type in {"Caster", "FriendSelect", "AllTeamMember"}:
        return "self_or_team"
    return "unknown"


def _skill_effect_from_target_mode(target_mode: str) -> str:
    if target_mode == "aoe":
        return "AoeAttack"
    if target_mode == "single":
        return "SingleAttack"
    if target_mode == "blast":
        return "Blast"
    if target_mode == "bounce":
        return "Bounce"
    if target_mode == "self_or_team":
        return "Enhance"
    return "Unknown"


def _damage_kind(skill_effect: str) -> str:
    return "hp_damage" if _target_mode(skill_effect) in {"single", "blast", "aoe", "bounce"} else "non_damage"


def _damage_formula_family(attack_type: str, skill_effect: str) -> str:
    normalized_attack = attack_type.lower()
    normalized_effect = skill_effect.lower()
    if normalized_attack == "elationdamage" or normalized_effect == "byelationdamage":
        return "elation"
    if normalized_attack == "truedamage":
        return "true_damage"
    if normalized_attack == "dot" or normalized_effect == "dot":
        return "dot"
    if normalized_attack == "elementdamage":
        return "direct"
    if _target_mode(skill_effect) in {"single", "blast", "aoe", "bounce"}:
        return "direct"
    return "none"


def _source_mode(attack_type: str) -> str:
    return "maze" if attack_type.lower().startswith("maze") else "mainline"


def _limit_sequence(items: list[Any], limit: int | None) -> list[Any]:
    if limit is None:
        return items
    return items[:limit]


def _number_value(value: Any, default: float) -> float:
    if isinstance(value, dict):
        nested = value.get("Value")
        return _number_value(nested, default)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _number_items(value: Any) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[float] = []
    for item in value:
        number = _number_value(item, default=float("nan"))
        if number == number:
            result.append(number)
    return tuple(result)


def _required_number(row: dict[str, Any], key: str) -> float | None:
    if key not in row:
        return None
    value = row.get(key)
    if isinstance(value, dict):
        return _required_number(value, "Value")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _list_json_values(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [_json_safe(item) for item in value]


def _json_object_from_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _compact_payload(value: dict[str, Any]) -> dict[str, Any]:
    ignored = {"SuccessTaskList", "FailedTaskList", "CallbackConfig"}
    return {key: _json_safe(item) for key, item in value.items() if key not in ignored and key != "$type"}


REMOVE_MODIFIER_OPCODES = {"RemoveModifier", "RemoveSelfModifier"}
HEAL_OPCODES = {"HealHP"}
SHIELD_OPCODES = {"InitShield", "StackShield", "ModifyShield"}
REMOVE_SHIELD_OPCODES = {"RemoveShield"}
MECHANISM_BAR_OPCODES = {"SetEnergyBarState", "SetMonsterEnergyBarState", "SetSummonerEnergyBarState"}
RESOURCE_DELTA_OPCODES = {
    "ModifySPNew",
    "ModifyTeamBoostPoint",
    "ModifyTeamBoostPointMax",
}
DYNAMIC_VALUE_OPCODES = {"DefineDynamicValue", "SetDynamicValue", "SetDynamicValueByAddValue", "SetDynamicValueByModifierValue"}
DAMAGE_EMISSION_OPCODES = {"DamageByAttackProperty"}
HP_LOSS_OPCODES = {"LoseHPByRatio"}
DISPEL_STATUS_OPCODES = {"DispelStatus"}
EXECUTABLE_TARGET_ALIASES = {
    "Caster",
    "CurrentActionTarget",
    "CurrentTurnOwnerEntity",
    "DamageAttackerEntity",
    "DamageDefenderEntity",
    "ModifierOwnerEntity",
    "ParamEntity",
    "ParamEntity2",
}
ADD_MODIFIER_TARGET_ALIASES = EXECUTABLE_TARGET_ALIASES | {
    "AbilityTargetEntity",
    "AllDarkTeam",
    "AllEnemy",
    "AllTeamMember",
    "AllLightTeam",
    "AllTeammate",
    "AttackTargetList",
    "SkillSubTargetEntityList",
    "SkillTargetEntityList",
}
STATUS_CALLBACK_LIST_TARGET_ALIASES = {
    "AllEnemyWithUnSelectable",
    "ParamEntityAttackTargetList",
    "ParamEntitySkillSubTargetEntityList",
    "ParamEntitySkillTargetEntityList",
}
TARGET_EXPRESSION_CONTEXT_ALIASES = {
    "AllDarkTeam",
    "CasterServant",
    "CasterSummonedMinions",
    "FriendServantSelect",
    "LastSummonMonsters",
    "SkillTargetEntityList",
    "ParamEntityList",
    "ServantEntityList",
    "BattleEventEntityList",
    "TeamFormation",
    "GridFight_AllBackEnd",
    "GridFight_AllBackEndRoleOnly",
    "GridFight_AllBackEndActivedRoleOnly",
}
P1_6_SAFE_TARGET_FETCH_KINDS = {
    "TargetFetchActualOwner",
    "TargetFetchAbilityTarget",
    "TargetFetchCaster",
    "TargetFetchCurrentActionTarget",
    "TargetFetchModifierOwner",
    "TargetFetchOwner",
    "TargetFetchParamEntityList",
    "TargetFetchPartner",
    "TargetFetchUniqueNameEntity",
}
P1_6_SAFE_TARGET_PROPERTY_SORTS = {"CurrentHP", "MaxHP", "CurrentStance", "MaxStance"}
P1_6_SAFE_TARGET_RATIO_SORTS = {"HPRatio", "StanceRatio"}
P1_6_SAFE_DIRECT_TARGET_ALIASES = {
    "AbilityTargetAdjoinEntity",
    "AbilityTargetAndAdjoinEntity",
    "AbilityTargetLeftEntity",
    "AbilityTargetRightEntity",
    "AbilityTargetServantOrSummoner",
    "AllEnemyIgnoreServant",
    "AllDarkTeamWithAllDarkTeamUnselectable",
    "AllLightTeamIgnoreServant",
    "AllLightTeamOnlyAddSPOnceForServant",
    "AllLightTeamWithAllLightTeamUnselectable",
    "AllLightTeamWithAllUnselectableLightTeam",
    "AllTeamMemberWithUnselectable",
    "AllTeammateOnlyAddSPOnceForServant",
    "AllTeammateWithUnselectable",
    "CasterServantOrSummoner",
    "CasterBEServant",
    "CasterSummoner",
    "CurrentAimAtTarget",
    "LevelEntity",
    "CasterAdjoinEntity",
    "CasterWithAbilityTargetAndAdjoinEntity",
    "LeftToRightLightTeamTarget",
    "LightTeamLeftWithoutServant",
    "LightTeamRightWithoutServant",
    "ModifierOwnerSummoner",
    "ModifierOwnerEntityAdjoinEntity",
    "ModifierOwnerSummonedMinions",
    "ModifierOwnerSkillTargetEntityList",
    "TurnActionEntitySkillTarget",
    "ParamEntityAdjoinEntity",
    "ParamEntitySummoner",
    "AllUnselectable",
}
P1_6_SAFE_DOT_TARGET_BASE_ALIASES = ADD_MODIFIER_TARGET_ALIASES | STATUS_CALLBACK_LIST_TARGET_ALIASES | TARGET_EXPRESSION_CONTEXT_ALIASES
P1_6_SAFE_DOT_TARGET_OPERATIONS = {
    "GetAdjoinEntity",
    "GetAliveOnly",
    "Reverse",
    "Select1",
    "Select2",
    "Select3",
    "Select4",
    "SelectLast",
    "Shuffle",
    "SortByFormation",
    "SortByHP",
    "SortByHPRatio",
    "SortByMaxHP",
    "SortByStance",
    "SortByStanceRatio",
    "SortByBreakDamageAddedRatio",
    "GetServant",
    "GetServantAndDummyCharacter",
    "GetDummyCharacter",
    "GetBEServant",
    "GetSummonedMinions",
    "GetSkillAllTarget",
    "GetSkillTarget",
    "WithServant",
    "WithBEServant",
    "WithServantAndDummyCharacter",
    "RemoveBattleEvent",
    "RemoveBEServant",
    "RemoveCharacterChangeTarget",
    "RemoveNonSelfCreateBattleEvent",
    "RemoveServant",
    "RemoveUnselectable",
    "GetSummoner",
    "WithSummoner",
}
DAMAGE_EMISSION_TARGET_ALIASES = {
    "AbilityTargetEntity",
    "AbilityTargetAdjoinEntity",
    "AllEnemy",
    "CurrentActionTarget",
}
SUPPORTED_MODIFIER_VALUE_TYPES = {"Layer", "LifeTime", "MaxLayer"}
EXECUTABLE_CONDITION_OPCODES = {
    "AlwaysTrue",
    "ByAnd",
    "ByAny",
    "ByAttackType",
    "ByCheckModifierCallBackBehaviorFlag",
    "ByCheckModifierCallBackIsSelf",
    "ByCheckModifierCallBackName",
    "ByCheckModifierCallBackStatusType",
    "ByCompareAbilityProperty",
    "ByCompareCharacterID",
    "ByCompareDynamicValue",
    "ByCompareCharacterNumber",
    "ByCompareCurrentModifierStatusType",
    "ByCompareHPRatio",
    "ByCompareModifierValue",
    "ByCompareMonsterID",
    "ByCompareDamageCustomName",
    "ByCompareDamageTag",
    "ByCompareTarget",
    "ByCompareTargetCount",
    "ByContainBehaviorFlag",
    "ByContainsParamFlag",
    "ByCharacterDamageType",
    "ByCompareChangeValue",
    "ByCompareParamValue",
    "ByCompareSPRatio",
    "ByCompareWaveCount",
    "ByHasStanceWeak",
    "ByInTurnBasedGameModeState",
    "ByIsDamageCritical",
    "ByIsPropertyValueMinOrMax",
    "ByIsTargetValid",
    "ByIsTopActionDelayTarget",
    "ByRandomChance",
    "ByCurrentSkillName",
    "ByCurrentSkillType",
    "ByIsContainModifier",
    "ByHaveEnemyAlive",
    "ByIsCurrentSkillActive",
    "ByIsInsertAction",
    "ByIsTeammate",
    "ByIsTurnOwnerEntity",
    "ByNot",
    "ByStatusCount",
    "ByTargetAliveState",
    "ByTargetListIntersects",
    "ByTargetEntityType",
    "ByTargetTeam",
}


def _effect_payload(value: dict[str, Any], opcode: str, source_modifier_name: str) -> dict[str, Any]:
    payload = _compact_payload(value)
    if opcode == "AddModifier":
        payload["standard"] = _standard_add_modifier_payload(value)
    elif opcode in REMOVE_MODIFIER_OPCODES:
        payload["standard"] = _standard_remove_modifier_payload(value, opcode, source_modifier_name)
    elif opcode in DISPEL_STATUS_OPCODES:
        payload["standard"] = _standard_dispel_status_payload(value)
    elif opcode in HEAL_OPCODES:
        payload["standard"] = _standard_heal_payload(value)
    elif opcode in SHIELD_OPCODES:
        payload["standard"] = _standard_shield_payload(value, opcode)
    elif opcode in REMOVE_SHIELD_OPCODES:
        payload["standard"] = _standard_remove_shield_payload(value)
    elif opcode in MECHANISM_BAR_OPCODES:
        payload["standard"] = _standard_mechanism_bar_payload(value, opcode)
    elif opcode in RESOURCE_DELTA_OPCODES:
        payload["standard"] = _standard_resource_delta_payload(value, opcode)
    elif opcode in HP_LOSS_OPCODES:
        payload["standard"] = _standard_hp_loss_ratio_payload(value)
    elif opcode == "TriggerAbility":
        payload["standard"] = _standard_trigger_ability_payload(value)
    elif opcode == "OwnerEntityAddAbility":
        payload["standard"] = _standard_owner_entity_add_ability_payload(value)
    elif opcode == "AttachEntityDeparted":
        payload["standard"] = _standard_attach_entity_departed_payload(value)
    elif opcode == "DefineDynamicValue":
        payload["standard"] = _standard_define_dynamic_value_payload(value)
    elif opcode == "SetDynamicValue":
        payload["standard"] = _standard_set_dynamic_value_payload(value)
    elif opcode == "SetDynamicValueByAddValue":
        payload["standard"] = _standard_set_dynamic_value_by_add_value_payload(value)
    elif opcode == "SetDynamicValueByModifierValue":
        payload["standard"] = _standard_set_dynamic_value_by_modifier_value_payload(value, source_modifier_name)
    elif opcode == "TriggerModifierCustomEvent":
        payload["standard"] = _standard_trigger_modifier_custom_event_payload(value)
    elif opcode == "StackWeakness":
        payload["standard"] = _standard_stack_weakness_payload(value)
    if is_dynamic_value_opcode(opcode):
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            standard = _standard_generic_dynamic_value_payload(
                value,
                opcode,
                source_modifier_name,
            )
        standard = dict(standard)
        standard["dynamic_operation"] = lower_dynamic_value_operation_spec(
            opcode,
            standard,
        )
        payload["standard"] = standard
    family = _task_damage_family(value, opcode)
    if family != "unknown":
        payload["damage_formula_family"] = family
        payload["bypasses_normal_multipliers"] = family in {"true_damage", "hp_loss"}
    return payload


def lower_character_dynamic_value_operation(
    opcode: str,
    raw_fields: dict[str, Any],
    source: IRSource,
    *,
    source_modifier_name: str = "",
) -> DynamicValueOperationIR:
    payload = _effect_payload(raw_fields, opcode, source_modifier_name)
    standard = payload.get("standard")
    spec = standard.get("dynamic_operation") if isinstance(standard, dict) else None
    if not isinstance(spec, dict):
        raise ValueError(f"dynamic value operation was not lowered:{opcode}")
    return DynamicValueOperationIR.from_spec(spec, source)


_PROCESS_ONLY_TASK_FIELD_TYPES: dict[str, dict[str, str]] = {
    "DamagePerformFinish": {
        "IsFakeAvatarAttack": "bool",
        "SkipDeathSettlement": "bool",
    },
    "GlobalMainIntensityEffect": {
        "FadeDuration": "number",
        "IsDurable": "bool",
        "IsRevert": "bool",
        "TargetIntensity": "number",
    },
    "GlobalTimeSlow": {
        "ActiveNextFrame": "bool",
        "FadeInCurveName": "string",
        "FadeInTime": "numeric_expression",
        "FadeOutCurveName": "string",
        "FadeOutTime": "numeric_expression",
        "Infinite": "bool",
        "SlowKey": "string",
        "TimeScale": "numeric_expression",
        "UnscaledDuration": "numeric_expression",
    },
    "LookAt": {
        "AngleOffset": "number",
        "CustomTargetType": "mapping",
        "Duration": "number",
        "PerformerType": "mapping",
        "SyncYawTargetType": "mapping",
        "TargetType": "string",
        "ToTargetRatio": "number",
    },
    "MoveToTargetPosition": {
        "ApplyTargetPosY": "bool",
        "IgnoreRadius": "bool",
        "OffsetCoord": "string",
        "OffsetForward": "numeric_expression",
        "OffsetHorizontal": "numeric_expression",
        "OffsetTargetDistance": "numeric_expression",
        "OffsetVertical": "numeric_expression",
        "PerformerType": "mapping",
        "TargetAttachPointName": "string",
        "TargetType": "mapping",
    },
    "RadialBlurEffect": {
        "Active": "bool",
        "BlurFeather": "number",
        "BlurRadius": "number",
        "BlurStart": "number",
        "BlurX": "number",
        "BlurY": "number",
        "Duration": "number",
        "HiendOnly": "bool",
        "Iteration": "integer",
        "TargetType": "mapping",
    },
    "SetTeamFormation": {
        "CustomCenterTargetType": "mapping",
        "CustomFormationIgnoreDying": "bool",
        "CustomFormationName": "string",
        "FormationConfigName": "string",
        "FormationTarget": "mapping",
        "FormationType": "string",
        "ImmediatelyStopHeadLookAt": "bool",
        "RefreshFormationCenter": "bool",
        "RemoveDying": "bool",
        "ServantState": "string",
        "Team": "string",
        "TeamMemberCountingOption": "integer",
    },
    "SkillExecutionStart": {},
    "SkillPerformFinish": {"SkipAttackSettlement": "bool"},
    "TriggerAnimState": {
        "AnimLogicState": "string",
        "AnimStateName": "string",
        "ForceStart": "bool",
        "NormalizedTimeEnd": "numeric_expression",
        "NormalizedTimeStart": "numeric_expression",
        "NormalizedTimeWait": "numeric_expression",
        "NormalizedTransitionDuration": "numeric_expression",
        "RandomHitAngle": "bool",
        "TargetType": "mapping",
        "WaitAnimState": "bool",
    },
    "TriggerAnimStateWithMove": {
        "AnimLogicState": "string",
        "AnimStateName": "string",
        "EventList": "list",
        "ForceStart": "bool",
        "MovingRangeList": "list",
        "NormalizedTimeEnd": "numeric_expression",
        "NormalizedTimeStart": "numeric_expression",
        "NormalizedTransitionDuration": "numeric_expression",
        "TargetType": "mapping",
        "WaitAnimState": "bool",
    },
    "VCameraConfigChange": {"CameraConfig": "mapping"},
    "WaitAnimState": {
        "AnimStateName": "string",
        "IgnoreStateChangeCheck": "bool",
        "NormalizedTimeEnd": "numeric_expression",
        "SkipWhenStateChange": "bool",
        "SyncVCameraTime": "bool",
        "TargetType": "mapping",
        "WaitForFrameEnd": "bool",
    },
    "WaitSecond": {
        "IsRealtime": "bool",
        "WaitTime": "numeric_expression",
    },
}


def _process_only_source_field_reason(
    field_name: str,
    value: Any,
    expected_type: str,
) -> str:
    valid = False
    if expected_type == "bool":
        valid = isinstance(value, bool)
    elif expected_type == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif expected_type == "number":
        valid = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    elif expected_type == "string":
        valid = isinstance(value, str) and bool(value)
    elif expected_type == "mapping":
        valid = isinstance(value, dict) and bool(value)
    elif expected_type == "list":
        valid = isinstance(value, list)
    elif expected_type == "numeric_expression":
        expression = lower_numeric_expression(value)
        valid = (
            is_typed_numeric_expression(expression)
            and expression.get("supported") is True
        )
    return "" if valid else f"process_only_task_field_invalid:{field_name}:{expected_type}"


def _process_only_ability_task_source_blocked_reason(
    task: dict[str, Any],
    opcode: str,
) -> str:
    if _short_gamecore_type(task.get("$type")) != opcode:
        return "process_only_task_source_type_mismatch"
    field_types = _PROCESS_ONLY_TASK_FIELD_TYPES.get(opcode)
    if field_types is None:
        return "process_only_task_source_schema_missing"
    unknown_fields = sorted(set(task).difference({"$type", *field_types}))
    if unknown_fields:
        return "process_only_task_unknown_fields:" + ",".join(unknown_fields)
    for field_name, expected_type in field_types.items():
        if field_name not in task:
            continue
        reason = _process_only_source_field_reason(
            field_name,
            task[field_name],
            expected_type,
        )
        if reason:
            return reason
    if opcode == "DamagePerformFinish":
        return "" if set(task) == {"$type"} else "damage_perform_finish_settlement_payload_not_admitted"
    if opcode == "GlobalMainIntensityEffect":
        return (
            ""
            if set(task).intersection(
                {"IsRevert", "TargetIntensity", "FadeDuration"}
            )
            else "global_main_intensity_payload_not_admitted"
        )
    if opcode == "GlobalTimeSlow":
        infinite = task.get("Infinite") is True
        return (
            ""
            if "TimeScale" in task
            and (infinite or "UnscaledDuration" in task)
            else "global_time_slow_payload_not_admitted"
        )
    if opcode == "LookAt":
        return (
            ""
            if set(task).intersection({"TargetType", "CustomTargetType"})
            else "look_at_target_source_missing"
        )
    if opcode == "MoveToTargetPosition":
        return "" if "TargetType" in task else "move_to_target_position_target_missing"
    if opcode == "RadialBlurEffect":
        visual_fields = {
            "Active",
            "BlurFeather",
            "BlurRadius",
            "BlurStart",
            "BlurX",
            "BlurY",
            "Duration",
            "HiendOnly",
            "Iteration",
            "TargetType",
        }
        return (
            ""
            if set(task).intersection(visual_fields)
            else "radial_blur_visual_payload_missing"
        )
    if opcode == "SetTeamFormation":
        has_formation = bool(task.get("FormationType") or task.get("CustomFormationName"))
        has_scope = bool(
            task.get("Team")
            or task.get("FormationTarget")
            or task.get("CustomCenterTargetType")
        )
        return (
            ""
            if has_formation and has_scope
            else "set_team_formation_payload_not_admitted"
        )
    if opcode == "SkillExecutionStart":
        return "" if set(task) == {"$type"} else "skill_execution_start_payload_not_admitted"
    if opcode == "SkillPerformFinish":
        return "" if set(task) == {"$type"} else "skill_perform_finish_settlement_payload_not_admitted"
    if opcode == "TriggerAnimState":
        return (
            ""
            if task.get("AnimStateName") or task.get("AnimLogicState")
            else "trigger_anim_state_name_missing"
        )
    if opcode == "TriggerAnimStateWithMove":
        if task.get("EventList"):
            return "trigger_anim_state_with_move_nested_events_not_admitted"
        return (
            ""
            if "TargetType" in task
            and bool(task.get("AnimStateName") or task.get("AnimLogicState"))
            and isinstance(task.get("MovingRangeList"), list)
            and bool(task.get("MovingRangeList"))
            else "trigger_anim_state_with_move_payload_not_admitted"
        )
    if opcode == "VCameraConfigChange":
        return "" if "CameraConfig" in task else "camera_config_missing"
    if opcode == "WaitAnimState":
        return (
            ""
            if task.get("AnimStateName") and "NormalizedTimeEnd" in task
            else "wait_anim_state_source_incomplete"
        )
    if opcode == "WaitSecond":
        return "" if "WaitTime" in task else "wait_second_duration_missing"
    return "process_only_task_source_contract_unhandled"


TARGET_EXPRESSION_FIELD_NAMES = {
    "Attacker",
    "TargetType",
    "TargetInfo",
    "AbilityTarget",
    "AutoCastTargetType",
    "AbilityInherentTargetType",
    "BaseTypeSourceTarget",
    "CasterFilter",
    "FromTargetType",
    "ReadTargetType",
    "ToTargetType",
    "WriteTargetType",
    "CompareType",
    "FirstTargetType",
    "SecondTargetType",
}


def _attach_target_expressions_to_effect_payload(
    payload: dict[str, Any],
    task: dict[str, Any],
    *,
    effect_id: str,
    source: IRSource,
) -> tuple[dict[str, Any], list[TargetExpressionIR]]:
    expressions: list[TargetExpressionIR] = []
    refs_by_field: dict[str, Any] = {}
    for field_name, raw_value in _iter_target_expression_fields(task):
        expression = _target_expression_from_raw(
            raw_value,
            field_name=field_name,
            expression_id=f"target_expression:{effect_id}:{field_name}",
            source=source,
        )
        if expression is None:
            continue
        expressions.append(expression)
        refs_by_field[field_name] = {
            "target_expression_id": expression.target_expression_id,
            "expression_kind": expression.expression_kind,
            "alias": expression.alias,
            "coverage_status": expression.coverage_status,
            "blocked_reason": expression.blocked_reason,
            "admission_batch": expression.admission_batch,
            "source": expression.source.to_json(),
        }
    if not expressions:
        return payload, []
    updated = dict(payload)
    updated["target_expression_refs"] = refs_by_field
    standard = updated.get("standard")
    if isinstance(standard, dict):
        standard = dict(standard)
        target_ref = refs_by_field.get("TargetType")
        if isinstance(target_ref, dict):
            standard["target_expression_id"] = target_ref["target_expression_id"]
            standard["target_expression_kind"] = target_ref["expression_kind"]
            standard["target_expression_coverage_status"] = target_ref["coverage_status"]
            standard["target_expression_blocked_reason"] = target_ref["blocked_reason"]
            standard["target_expression_source"] = target_ref["source"]
        standard["target_expression_refs"] = refs_by_field
        updated["standard"] = standard
    return updated, expressions


def _iter_target_expression_fields(task: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    pairs: list[tuple[str, Any]] = []
    for field_name in sorted(TARGET_EXPRESSION_FIELD_NAMES):
        value = task.get(field_name)
        if _is_target_expression_node(value):
            pairs.append((field_name, value))
        elif field_name == "TargetInfo":
            pairs.extend(_target_info_expression_fields(value))
    for key, value in sorted(task.items()):
        if key in TARGET_EXPRESSION_FIELD_NAMES or key in {
            "Predicate",
            "PredicateList",
            "TaskList",
            "SuccessTaskList",
            "FailedTaskList",
        }:
            continue
        pairs.extend(_nested_target_expression_fields(value, key))
    return tuple(pairs)


def _nested_target_expression_fields(
    value: Any,
    path: str,
) -> tuple[tuple[str, Any], ...]:
    pairs: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in sorted(value.items()):
            child_path = f"{path}.{key}"
            if key in TARGET_EXPRESSION_FIELD_NAMES and _is_target_expression_node(child):
                pairs.append((child_path, child))
                continue
            pairs.extend(_nested_target_expression_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            pairs.extend(_nested_target_expression_fields(child, f"{path}[{index}]"))
    return tuple(pairs)


def _target_info_expression_fields(value: Any) -> tuple[tuple[str, dict[str, Any]], ...]:
    # A string alias is an implicit engine input, not a raw target-expression
    # node.  It must remain an alias in the surrounding payload; creating a
    # synthetic TargetAlias here would give it a source path that does not
    # exist in TBGD.
    if isinstance(value, str):
        return ()
    if not isinstance(value, dict):
        return ()
    target_type = value.get("TargetType")
    if _is_target_expression_node(target_type):
        assert isinstance(target_type, dict)
        return (("TargetInfo.TargetType", target_type),)
    if isinstance(target_type, str):
        return ()
    return ()


def _is_target_expression_node(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    node_type = value.get("$type")
    if node_type is not None and not isinstance(node_type, str):
        return True
    return isinstance(node_type, str) and (
        node_type.startswith("RPG.GameCore.Target") or node_type == "RPG.GameCore.Retarget"
    )


def _target_raw_expression_kind(raw: dict[str, Any]) -> str:
    node_type = raw.get("$type")
    if node_type is not None and not isinstance(node_type, str):
        return "UnknownTargetExpression"
    return _target_expression_kind(node_type or "", raw)


def _target_expression_from_raw(
    value: Any,
    *,
    field_name: str,
    expression_id: str,
    source: IRSource,
) -> TargetExpressionIR | None:
    if not _is_target_expression_node(value):
        return None
    assert isinstance(value, dict)
    # A typed runtime node is only valid when its parent can point to the
    # exact raw location.  Older lowering callers sometimes have only a
    # logical task label; silently manufacturing a JSON path for those would
    # make the result executable without source lineage.
    if not _has_raw_json_path(source):
        return None
    expression_kind = _target_raw_expression_kind(value)
    alias = _target_alias(value) or ""
    target_source = _target_expression_source(
        source,
        expression_id=expression_id,
        field_name=field_name,
        expression_kind=expression_kind,
    )
    coverage_status, blocked_reason, admission_batch = _target_expression_admission(
        expression_kind,
        alias,
        value,
        source=target_source,
    )
    node = _target_expression_execution_node(value, target_source)
    node_blocked_reason = _target_node_contract_blocked_reason(node)
    if node_blocked_reason:
        coverage_status = "blocked"
        blocked_reason = node_blocked_reason
    return TargetExpressionIR(
        target_expression_id=expression_id,
        expression_kind=expression_kind,
        alias=alias,
        node=node,
        source=target_source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
        admission_batch=admission_batch,
    )


def _has_raw_json_path(source: IRSource) -> bool:
    json_path = source.evidence.get("json_path")
    return (
        isinstance(source.source_path, str)
        and bool(source.source_path)
        and isinstance(json_path, str)
        and bool(json_path)
        and json_path.startswith("$")
    )


def _target_node_contract_blocked_reason(node: TargetExpressionNodeIR) -> str:
    if node.runtime_blocked_reason:
        return node.runtime_blocked_reason
    if node.expression_kind == "TargetUnsupported":
        return str(node.payload["blocked_reason"])
    for child in node.children:
        reason = _target_node_contract_blocked_reason(child)
        if reason:
            return reason
    for child in (node.candidate, node.target, node.query_target, node.query_compare):
        if child is not None:
            reason = _target_node_contract_blocked_reason(child)
            if reason:
                return reason
    if node.predicate is not None and node.predicate.coverage_status != "executable":
        return node.predicate.blocked_reason or "target_predicate_not_executable"
    return ""


def _target_expression_source(
    source: IRSource,
    *,
    expression_id: str,
    field_name: str,
    expression_kind: str,
) -> IRSource:
    evidence = dict(source.evidence)
    base_path = evidence.get("json_path")
    if not isinstance(base_path, str) or not base_path.startswith("$"):
        raise ValueError("target expression source requires an exact raw JSON path")
    json_path = base_path if field_name == "$self" else f"{base_path}.{field_name}"
    return IRSource(
        source_path=source.source_path,
        raw_type="TargetExpression",
        raw_id=expression_id,
        evidence={
            "json_path": json_path,
            "source_raw_type": source.raw_type,
            "source_raw_id": source.raw_id,
            "target_expression_field": field_name,
            "target_expression_kind": expression_kind,
        },
    )


def _target_expression_kind(node_type: str, value: dict[str, Any]) -> str:
    if node_type.startswith("RPG.GameCore."):
        return node_type.removeprefix("RPG.GameCore.")
    if value.get("Alias") is not None:
        return "TargetAlias"
    return "UnknownTargetExpression"


def _target_expression_admission(
    kind: str,
    alias: str,
    raw: dict[str, Any],
    *,
    source: IRSource | None = None,
) -> tuple[str, str, str]:
    if kind == "TargetAlias" and _target_alias_admitted(alias):
        return "executable", "", "p1_6_target_pipeline" if _target_alias_chain_admitted(alias) else "v0_288_target_alias_core"
    if kind in {"TargetConcat", "TargetSequence", "TargetFilter", "Retarget"}:
        reason = _target_expression_runtime_blocked_reason(raw, source=source)
        if not reason:
            return "executable", "", "p1_6_target_pipeline" if _target_expression_uses_p1_6_node(raw) else "v0_289_target_sequence_filter_retarget"
        return "blocked", reason, "p1_6_target_pipeline" if _target_expression_uses_p1_6_node(raw) else "v0_289_target_sequence_filter_retarget"
    reason = _target_expression_runtime_blocked_reason(raw, source=source)
    if not reason and _target_expression_kind_admitted(kind, raw):
        return "executable", "", "p1_6_target_pipeline"
    if kind.startswith("TargetSort"):
        return "blocked", f"target_sort_not_admitted:{kind}", "after_target_sequence_sorting"
    if kind.startswith("TargetFetch"):
        return "blocked", f"target_fetch_not_admitted:{kind}", "after_summon_or_unique_entity_system"
    if kind == "TargetAlias" and alias:
        return "blocked", f"target_alias_not_admitted:{alias}", "later_target_expression_admission"
    return "blocked", f"target_expression_not_admitted:{kind or 'missing'}", "later_target_expression_admission"


def _target_alias_admitted(alias: str) -> bool:
    return alias in (
        ADD_MODIFIER_TARGET_ALIASES
        | STATUS_CALLBACK_LIST_TARGET_ALIASES
        | TARGET_EXPRESSION_CONTEXT_ALIASES
        | P1_6_SAFE_DIRECT_TARGET_ALIASES
    ) or _target_alias_chain_admitted(alias)


def _target_expression_runtime_blocked_reason(
    raw: dict[str, Any],
    *,
    source: IRSource | None = None,
) -> str:
    kind = _target_raw_expression_kind(raw)
    if kind == "TargetAlias":
        alias = _target_alias(raw) or ""
        return "" if _target_alias_admitted(alias) else f"target_alias_not_admitted:{alias or 'missing'}"
    if kind == "TargetConcat":
        targets = raw.get("Targets")
        if not isinstance(targets, list) or not targets:
            return "target_concat_children_missing"
        return _first_target_expression_child_blocked_reason(targets, source=source, field_name="Targets")
    if kind == "TargetSequence":
        sequence = raw.get("Sequence")
        if not isinstance(sequence, list) or not sequence:
            return "target_sequence_children_missing"
        return _first_target_expression_child_blocked_reason(sequence, source=source, field_name="Sequence")
    if kind == "TargetFilter":
        predicate = raw.get("Predicate")
        if not isinstance(predicate, dict):
            return "target_filter_predicate_missing"
        if source is None:
            return "target_filter_predicate_source_missing"
        predicate_node = _typed_condition_execution_node(
            predicate,
            equipment_scope=True,
            source=_target_child_source(source, "Predicate", "TargetPredicate"),
        )
        opcode = str(predicate_node.get("opcode") or "")
        if predicate_node.get("supported") is not True:
            return f"target_filter_condition_not_admitted:{opcode or 'missing'}"
        target = raw.get("TargetType") or raw.get("Target") or raw.get("Targets")
        if isinstance(target, dict):
            return _target_expression_runtime_blocked_reason(
                target,
                source=_target_child_source(source, "TargetType", "TargetExpression") if source is not None else None,
            )
        return ""
    if kind == "Retarget":
        target = raw.get("TargetType")
        if not isinstance(target, dict):
            return "retarget_target_type_missing"
        reason = _target_expression_runtime_blocked_reason(
            target,
            source=_target_child_source(source, "TargetType", "TargetExpression") if source is not None else None,
        )
        if reason:
            return reason
        predicate = raw.get("Predicate")
        if isinstance(predicate, dict):
            if source is None:
                return "retarget_predicate_source_missing"
            predicate_node = _typed_condition_execution_node(
                predicate,
                equipment_scope=True,
                source=_target_child_source(source, "Predicate", "TargetPredicate"),
            )
            opcode = str(predicate_node.get("opcode") or "")
            if predicate_node.get("supported") is not True:
                return f"retarget_condition_not_admitted:{opcode or 'missing'}"
        include_limbo = raw.get("IncludeLimbo", False)
        if type(include_limbo) is not bool:
            return "retarget_include_limbo_invalid"
        if include_limbo:
            return "retarget_include_limbo_deferred_s5b"
        by_random = _target_boolean_field(raw, "ByRandom")
        if by_random is None:
            return "retarget_by_random_invalid"
        max_number = raw.get("MaxNumber")
        if max_number is not None and not _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(max_number)):
            return "retarget_max_number_not_executable"
        return ""
    if kind == "TargetQuery":
        return _target_query_blocked_reason(raw, source=source)
    reason = _target_pipeline_node_blocked_reason(kind, raw)
    if reason != "target_pipeline_node_not_matched":
        return reason
    if kind.startswith("TargetSort"):
        return f"target_sort_not_admitted:{kind}"
    if kind.startswith("TargetFetch"):
        return f"target_fetch_not_admitted:{kind}"
    return f"target_expression_kind_not_admitted:{kind or 'missing'}"


def _first_target_expression_child_blocked_reason(
    children: list[Any],
    *,
    source: IRSource | None,
    field_name: str,
) -> str:
    for index, child in enumerate(children):
        if not isinstance(child, dict):
            return "target_expression_child_not_object"
        reason = _target_expression_runtime_blocked_reason(
            child,
            source=(
                _target_child_source(source, f"{field_name}[{index}]", "TargetExpression")
                if source is not None
                else None
            ),
        )
        if reason:
            return reason
    return ""


def _target_expression_kind_admitted(kind: str, raw: dict[str, Any]) -> bool:
    return _target_pipeline_node_blocked_reason(kind, raw) == ""


def _target_string_field(raw: dict[str, Any], field_name: str, default: str = "") -> str | None:
    value = raw.get(field_name, default)
    return value if isinstance(value, str) else None


def _target_boolean_field(raw: dict[str, Any], field_name: str, default: bool = False) -> bool | None:
    value = raw.get(field_name, default)
    return value if type(value) is bool else None


def _target_fetch_field_reason(kind: str, name: str, unique_name: str) -> str:
    if kind == "TargetFetchPartner":
        return "target_fetch_partner_unique_name_unused" if unique_name else ""
    if kind == "TargetFetchUniqueNameEntity":
        if name:
            return "target_fetch_unique_name_name_unused"
        return "" if unique_name else "unique_entity_key_missing"
    if name:
        return "target_fetch_name_unused"
    return "target_fetch_unique_name_unused" if unique_name else ""


def _target_pipeline_node_blocked_reason(kind: str, raw: dict[str, Any]) -> str:
    if kind in P1_6_SAFE_TARGET_FETCH_KINDS:
        name = _target_string_field(raw, "Name")
        if name is None:
            return "target_fetch_name_invalid"
        unique_name = _target_string_field(raw, "UniqueName")
        if unique_name is None:
            return "target_fetch_unique_name_invalid"
        return _target_fetch_field_reason(kind, name, unique_name)
    if kind == "TargetMapAdjoinEntity":
        side = _target_string_field(raw, "SideType", "Both")
        if side not in {"Both", "Left", "Right"}:
            return "target_adjacent_side_invalid" if side is None else f"target_adjacent_side_not_admitted:{side or 'missing'}"
        counting_option = raw.get("CountingOption", "")
        if not isinstance(counting_option, str):
            return "target_adjacent_counting_option_invalid"
        if counting_option:
            return f"target_adjacent_counting_option_deferred_s5b:{counting_option}"
        return ""
    if kind == "TargetMapSummoner":
        recursive = raw.get("Recursive", False)
        if type(recursive) is not bool:
            return "target_summoner_recursive_invalid"
        return "" if not recursive else "target_summoner_recursive_deferred_s5b"
    if kind == "TargetMapSummonedMinions":
        return ""
    if kind == "TargetReverse":
        return ""
    if kind == "TargetShuffle":
        return ""
    if kind == "TargetTake":
        count = raw.get("Count")
        if count is None:
            return "target_take_count_missing"
        if not _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(count)):
            return "target_take_count_not_executable"
        return ""
    if kind == "TargetIndex":
        index_type = _target_string_field(raw, "IndexType", "IndexStrict")
        if index_type not in {"First", "IndexStrict", "Last"}:
            return "target_index_type_invalid" if index_type is None else f"target_index_type_not_admitted:{index_type or 'missing'}"
        index_value = raw.get("IndexValue")
        if index_type in {"First", "Last"} and index_value is not None:
            return "target_index_value_unused"
        if index_value is not None and not _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(index_value)):
            return "target_index_value_not_executable"
        return ""
    if kind == "TargetSortByProperty":
        property_type = _target_string_field(raw, "PropertyType")
        if property_type in P1_6_SAFE_TARGET_PROPERTY_SORTS:
            highest_first = _target_boolean_field(raw, "HighestFirst")
            return "" if highest_first is not None else "target_sort_highest_first_invalid"
        return "target_sort_property_invalid" if property_type is None else f"target_sort_property_not_admitted:{property_type or 'missing'}"
    if kind == "TargetSortByPropertyRatio":
        property_type = _target_string_field(raw, "PropertyRatioType")
        if property_type in P1_6_SAFE_TARGET_RATIO_SORTS:
            highest_first = _target_boolean_field(raw, "HighestFirst")
            return "" if highest_first is not None else "target_sort_highest_first_invalid"
        return "target_sort_ratio_invalid" if property_type is None else f"target_sort_ratio_not_admitted:{property_type or 'missing'}"
    if kind == "TargetSortByFormation":
        return "" if _target_boolean_field(raw, "HighestFirst") is not None else "target_sort_highest_first_invalid"
    return "target_pipeline_node_not_matched"


def _target_query_blocked_reason(
    raw: dict[str, Any],
    *,
    source: IRSource | None = None,
) -> str:
    entity_type = _target_string_field(raw, "EntityTypeMask")
    if entity_type != "Servant":
        return "target_query_entity_type_invalid" if entity_type is None else f"target_query_entity_type_not_admitted:{entity_type or 'missing'}"
    alive_state_mask = _target_string_field(raw, "AliveStateMask")
    if alive_state_mask is None:
        return "target_query_alive_state_mask_invalid"
    if alive_state_mask:
        return f"target_query_alive_state_mask_deferred_s5b:{alive_state_mask}"
    predicate = raw.get("Predicate")
    if predicate is None:
        return ""
    if not isinstance(predicate, dict):
        return "target_query_predicate_missing"
    opcode = _short_gamecore_type(predicate.get("$type"))
    if opcode != "ByCompareTarget":
        return f"target_query_predicate_not_admitted:{opcode or 'missing'}"
    target = predicate.get("TargetType")
    compare = predicate.get("CompareType")
    if not isinstance(target, dict) or not isinstance(compare, dict):
        return "target_query_compare_target_missing"
    target_reason = _target_expression_runtime_blocked_reason(
        target,
        source=(
            _target_child_source(source, "Predicate.TargetType", "TargetExpression")
            if source is not None
            else None
        ),
    )
    if target_reason:
        return f"target_query_target_type_blocked:{target_reason}"
    compare_reason = _target_expression_runtime_blocked_reason(
        compare,
        source=(
            _target_child_source(source, "Predicate.CompareType", "TargetExpression")
            if source is not None
            else None
        ),
    )
    if compare_reason:
        return f"target_query_compare_type_blocked:{compare_reason}"
    return ""


def _target_expression_uses_p1_6_node(raw: dict[str, Any]) -> bool:
    kind = _target_raw_expression_kind(raw)
    if _target_pipeline_node_blocked_reason(kind, raw) != "target_pipeline_node_not_matched":
        return True
    if kind == "TargetQuery" and not _target_query_blocked_reason(raw):
        return True
    if kind == "TargetAlias" and _target_alias_chain_admitted(_target_alias(raw) or ""):
        return True
    children = raw.get("Targets") if kind == "TargetConcat" else raw.get("Sequence")
    if isinstance(children, list):
        return any(isinstance(child, dict) and _target_expression_uses_p1_6_node(child) for child in children)
    target = raw.get("TargetType") or raw.get("Target") or raw.get("Targets")
    return isinstance(target, dict) and _target_expression_uses_p1_6_node(target)


def _target_alias_chain_admitted(alias: str) -> bool:
    if alias in P1_6_SAFE_DIRECT_TARGET_ALIASES:
        return True
    if _target_alias_set_admitted(alias):
        return True
    return _target_alias_dot_chain_admitted(alias)


def _target_alias_set_admitted(alias: str) -> bool:
    parsed = _parse_target_alias_set(alias)
    if len(parsed) < 2:
        return False
    for _, token in parsed:
        if token in P1_6_SAFE_DIRECT_TARGET_ALIASES:
            continue
        if _target_alias_dot_chain_admitted(token):
            continue
        if token in (
            ADD_MODIFIER_TARGET_ALIASES
            | STATUS_CALLBACK_LIST_TARGET_ALIASES
            | TARGET_EXPRESSION_CONTEXT_ALIASES
        ):
            continue
        return False
    return True


def _parse_target_alias_set(alias: str) -> tuple[tuple[str, str], ...]:
    parsed: list[tuple[str, str]] = []
    operator = "+"
    current: list[str] = []
    for ch in alias:
        if ch in {"+", "|", "-"}:
            operand = "".join(current).strip()
            if not operand:
                return ()
            parsed.append((operator, operand))
            operator = ch
            current = []
            continue
        current.append(ch)
    operand = "".join(current).strip()
    if not operand:
        return ()
    parsed.append((operator, operand))
    return tuple(parsed) if len(parsed) >= 2 else ()


def _target_alias_dot_chain_admitted(alias: str) -> bool:
    if "." not in alias or any(token in alias for token in (" ", "+", "-", "|", "(", ")")):
        return False
    parts = tuple(part for part in alias.split(".") if part)
    if len(parts) < 2:
        return False
    if parts[0] not in P1_6_SAFE_DOT_TARGET_BASE_ALIASES and parts[0] not in P1_6_SAFE_DIRECT_TARGET_ALIASES:
        return False
    return all(part in P1_6_SAFE_DOT_TARGET_OPERATIONS for part in parts[1:])


def _target_expression_execution_node(
    raw: dict[str, Any],
    source: IRSource,
) -> TargetExpressionNodeIR:
    kind = _target_raw_expression_kind(raw)
    alias = _target_alias(raw) or ""
    node_source = _target_expression_node_source(source, kind)
    if kind == "TargetConcat":
        return _target_children_node(raw, "Targets", kind, node_source)
    if kind == "TargetSequence":
        return _target_children_node(raw, "Sequence", kind, node_source)
    if kind == "TargetAlias":
        if not alias:
            return _target_unsupported_node(node_source, kind, "target_alias_missing")
        return TargetExpressionNodeIR.build(kind, node_source, {"alias": alias})
    if kind == "TargetFilter":
        candidate_key, candidate_raw = _first_target_child(raw, ("TargetType", "Target", "Targets"))
        predicate_raw = raw.get("Predicate")
        if not isinstance(predicate_raw, dict):
            return _target_unsupported_node(node_source, kind, "target_filter_predicate_missing")
        candidate = (
            _target_expression_execution_node(
                candidate_raw,
                _target_child_source(node_source, candidate_key, "TargetExpression"),
            )
            if candidate_key and isinstance(candidate_raw, dict)
            else None
        )
        predicate = _condition_ir_from_typed_target_predicate(
            predicate_raw,
            _target_child_source(node_source, "Predicate", "TargetPredicate"),
        )
        return TargetExpressionNodeIR.build(
            kind,
            node_source,
            {"candidate": candidate, "predicate": predicate},
        )
    if kind == "Retarget":
        target_raw = raw.get("TargetType")
        if not isinstance(target_raw, dict):
            return _target_unsupported_node(node_source, kind, "retarget_target_type_missing")
        target = _target_expression_execution_node(
            target_raw,
            _target_child_source(node_source, "TargetType", "TargetExpression"),
        )
        predicate_raw = raw.get("Predicate")
        predicate = (
            _condition_ir_from_typed_target_predicate(
                predicate_raw,
                _target_child_source(node_source, "Predicate", "TargetPredicate"),
            )
            if isinstance(predicate_raw, dict)
            else None
        )
        include_limbo = raw.get("IncludeLimbo", False)
        if type(include_limbo) is not bool:
            return _target_unsupported_node(node_source, kind, "retarget_include_limbo_invalid")
        by_random = _target_boolean_field(raw, "ByRandom")
        if by_random is None:
            return _target_unsupported_node(node_source, kind, "retarget_by_random_invalid")
        max_number_expr = (
            _numeric_expr_summary(raw["MaxNumber"])
            if raw.get("MaxNumber") is not None
            else {}
        )
        if max_number_expr and not _numeric_expr_can_be_runtime_bound(max_number_expr):
            return _target_unsupported_node(node_source, kind, "retarget_max_number_not_executable")
        return TargetExpressionNodeIR.build(
            kind,
            node_source,
            {
                "target": target,
                "predicate": predicate,
                "by_random": by_random,
                "max_number_expr": max_number_expr,
                "include_limbo": include_limbo,
            },
        )
    if kind == "TargetQuery":
        entity_type_mask = _target_string_field(raw, "EntityTypeMask")
        if entity_type_mask != "Servant":
            return _target_unsupported_node(
                node_source,
                kind,
                "target_query_entity_type_invalid"
                if entity_type_mask is None
                else f"target_query_entity_type_not_admitted:{entity_type_mask or 'missing'}",
            )
        alive_state_mask = _target_string_field(raw, "AliveStateMask")
        if alive_state_mask is None:
            return _target_unsupported_node(node_source, kind, "target_query_alive_state_mask_invalid")
        predicate_raw = raw.get("Predicate")
        query_target: TargetExpressionNodeIR | None = None
        query_compare: TargetExpressionNodeIR | None = None
        if isinstance(predicate_raw, dict) and _short_gamecore_type(predicate_raw.get("$type")) == "ByCompareTarget":
            left = predicate_raw.get("TargetType")
            right = predicate_raw.get("CompareType")
            query_target = (
                _target_expression_execution_node(
                    left,
                    _target_child_source(node_source, "Predicate.TargetType", "TargetExpression"),
                )
                if isinstance(left, dict)
                else None
            )
            query_compare = (
                _target_expression_execution_node(
                    right,
                    _target_child_source(node_source, "Predicate.CompareType", "TargetExpression"),
                )
                if isinstance(right, dict)
                else None
            )
        if (query_target is None) != (query_compare is None):
            return _target_unsupported_node(node_source, kind, "target_query_compare_target_missing")
        return TargetExpressionNodeIR.build(
            kind,
            node_source,
            {
                "entity_type_mask": entity_type_mask,
                "alive_state_mask": alive_state_mask,
                "target": query_target,
                "compare": query_compare,
            },
        )
    if kind in _TYPED_TARGET_FETCH_KINDS:
        name = _target_string_field(raw, "Name")
        if name is None:
            return _target_unsupported_node(node_source, kind, "target_fetch_name_invalid")
        unique_name = _target_string_field(raw, "UniqueName")
        if unique_name is None:
            return _target_unsupported_node(node_source, kind, "target_fetch_unique_name_invalid")
        fetch_reason = _target_fetch_field_reason(kind, name, unique_name)
        if fetch_reason:
            return _target_unsupported_node(node_source, kind, fetch_reason)
        return TargetExpressionNodeIR.build(
            kind,
            node_source,
            {"name": name, "unique_name": unique_name},
        )
    if kind == "TargetMapAdjoinEntity":
        side = _target_string_field(raw, "SideType", "Both")
        if side not in {"Both", "Left", "Right"}:
            return _target_unsupported_node(
                node_source,
                kind,
                "target_adjacent_side_invalid" if side is None else f"target_adjacent_side_not_admitted:{side or 'missing'}",
            )
        counting_option = raw.get("CountingOption", "")
        if not isinstance(counting_option, str):
            return _target_unsupported_node(node_source, kind, "target_adjacent_counting_option_invalid")
        return TargetExpressionNodeIR.build(
            kind, node_source, {"side": side, "counting_option": counting_option}
        )
    if kind == "TargetMapSummoner":
        recursive = raw.get("Recursive", False)
        if type(recursive) is not bool:
            return _target_unsupported_node(node_source, kind, "target_summoner_recursive_invalid")
        return TargetExpressionNodeIR.build(kind, node_source, {"recursive": recursive})
    if kind in {"TargetMapSummonedMinions", "TargetReverse", "TargetShuffle"}:
        return TargetExpressionNodeIR.build(kind, node_source, {})
    if kind == "TargetTake":
        count = raw.get("Count")
        if count is None:
            return _target_unsupported_node(node_source, kind, "target_take_count_missing")
        count_expr = _numeric_expr_summary(count)
        if not _numeric_expr_can_be_runtime_bound(count_expr):
            return _target_unsupported_node(node_source, kind, "target_take_count_not_executable")
        return TargetExpressionNodeIR.build(kind, node_source, {"count_expr": count_expr})
    if kind == "TargetIndex":
        index_type = _target_string_field(raw, "IndexType", "IndexStrict")
        if index_type not in {"First", "IndexStrict", "Last"}:
            return _target_unsupported_node(
                node_source,
                kind,
                "target_index_type_invalid" if index_type is None else f"target_index_type_not_admitted:{index_type or 'missing'}",
            )
        index_value = raw.get("IndexValue")
        if index_type in {"First", "Last"} and index_value is not None:
            return _target_unsupported_node(node_source, kind, "target_index_value_unused")
        index_expr = _numeric_expr_summary(index_value) if index_value is not None else {}
        if index_expr and not _numeric_expr_can_be_runtime_bound(index_expr):
            return _target_unsupported_node(node_source, kind, "target_index_value_not_executable")
        return TargetExpressionNodeIR.build(
            kind,
            node_source,
            {
                "index_type": index_type,
                "index_expr": index_expr,
            },
        )
    if kind == "TargetSortByProperty":
        sort_key = _target_string_field(raw, "PropertyType")
        if sort_key not in P1_6_SAFE_TARGET_PROPERTY_SORTS:
            return _target_unsupported_node(node_source, kind, "target_sort_property_invalid" if sort_key is None else f"target_sort_property_not_admitted:{sort_key or 'missing'}")
        highest_first = _target_boolean_field(raw, "HighestFirst")
        if highest_first is None:
            return _target_unsupported_node(node_source, kind, "target_sort_highest_first_invalid")
        return TargetExpressionNodeIR.build(kind, node_source, {"sort_key": sort_key, "highest_first": highest_first})
    if kind == "TargetSortByPropertyRatio":
        sort_key = _target_string_field(raw, "PropertyRatioType")
        if sort_key not in P1_6_SAFE_TARGET_RATIO_SORTS:
            return _target_unsupported_node(node_source, kind, "target_sort_ratio_invalid" if sort_key is None else f"target_sort_ratio_not_admitted:{sort_key or 'missing'}")
        highest_first = _target_boolean_field(raw, "HighestFirst")
        if highest_first is None:
            return _target_unsupported_node(node_source, kind, "target_sort_highest_first_invalid")
        return TargetExpressionNodeIR.build(kind, node_source, {"sort_key": sort_key, "highest_first": highest_first})
    if kind == "TargetSortByFormation":
        highest_first = _target_boolean_field(raw, "HighestFirst")
        if highest_first is None:
            return _target_unsupported_node(node_source, kind, "target_sort_highest_first_invalid")
        return TargetExpressionNodeIR.build(kind, node_source, {"sort_key": "formation_position", "highest_first": highest_first})
    return _target_unsupported_node(node_source, kind, f"target_expression_kind_not_typed:{kind or 'missing'}")


_TYPED_TARGET_FETCH_KINDS = frozenset(
    {
        "TargetFetchCaster",
        "TargetFetchModifierOwner",
        "TargetFetchOwner",
        "TargetFetchAbilityTarget",
        "TargetFetchCurrentActionTarget",
        "TargetFetchParamEntityList",
        "TargetFetchActualOwner",
        "TargetFetchPartner",
        "TargetFetchUniqueNameEntity",
    }
)


def _target_expression_node_source(source: IRSource, kind: str) -> IRSource:
    return IRSource(
        source_path=source.source_path,
        raw_type=kind or "UnknownTargetExpression",
        raw_id=source.raw_id,
        evidence={**source.evidence, "node_kind": kind or "UnknownTargetExpression"},
    )


def _target_child_source(source: IRSource, suffix: str, raw_type: str) -> IRSource:
    json_path = str(source.evidence["json_path"])
    return IRSource(
        source_path=source.source_path,
        raw_type=raw_type,
        raw_id=f"{source.raw_id}:{suffix}",
        evidence={"json_path": f"{json_path}.{suffix}"},
    )


def _target_children_node(
    raw: dict[str, Any],
    field_name: str,
    kind: str,
    source: IRSource,
) -> TargetExpressionNodeIR:
    children_raw = raw.get(field_name)
    if not isinstance(children_raw, list) or not children_raw or not all(isinstance(item, dict) for item in children_raw):
        return _target_unsupported_node(source, kind, f"target_{field_name.lower()}_children_missing")
    children = tuple(
        _target_expression_execution_node(
            item,
            _target_child_source(source, f"{field_name}[{index}]", "TargetExpression"),
        )
        for index, item in enumerate(children_raw)
    )
    return TargetExpressionNodeIR.build(kind, source, {"children": children})


def _target_unsupported_node(source: IRSource, kind: str, blocked_reason: str) -> TargetExpressionNodeIR:
    return TargetExpressionNodeIR.build(
        "TargetUnsupported",
        source,
        {"original_kind": kind or "UnknownTargetExpression", "blocked_reason": blocked_reason},
    )


def _first_target_child(raw: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, Any]:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, dict):
            return key, value
    return "", None


def _condition_ir_from_typed_target_predicate(
    raw: dict[str, Any],
    source: IRSource,
) -> ConditionIR:
    node = _typed_condition_execution_node(raw, source=source)
    opcode = str(node.get("opcode") or "UnknownCondition")
    metadata = {"schema_version", "expression_kind", "opcode", "supported", "blocked_reason"}
    return ConditionIR(
        condition_id=f"target_predicate:{_safe_id(str(source.evidence['json_path']))}:{_safe_id(opcode)}",
        opcode=opcode,
        payload={key: value for key, value in node.items() if key not in metadata},
        source=source,
        coverage_status="executable" if node.get("supported") is True else "blocked",
        expression_schema_version=str(node.get("schema_version") or ""),
        blocked_reason=str(node.get("blocked_reason") or ""),
    )


def _typed_condition_execution_node(
    raw: dict[str, Any],
    target_alias_registry: dict[str, Any] | None = None,
    *,
    equipment_scope: bool = False,
    damage_tag_registry: dict[
        int, tuple[dict[str, Any], ...]
    ] | None = None,
    source: IRSource,
) -> dict[str, Any]:
    opcode = _short_gamecore_type(raw.get("$type"))
    payload = _condition_payload_with_tbgd_defaults(
        opcode,
        _typed_condition_payload(
            _compact_payload(raw),
            target_alias_registry,
            equipment_scope=equipment_scope,
            damage_tag_registry=damage_tag_registry,
            source=source,
        ),
    )
    family_stage = (
        classify_equipment_condition(opcode, raw)
        if equipment_scope
        else "s7"
    )
    executable = (
        family_stage in {"s7", "s8"}
        and _condition_payload_executable(opcode, payload)
    )
    target_blocked_reason = _condition_payload_target_blocked_reason(payload)
    executable = executable and not target_blocked_reason
    return {
        "schema_version": CONDITION_EXPRESSION_NODE_SCHEMA,
        "expression_kind": opcode,
        "opcode": opcode,
        **payload,
        "supported": executable,
        "blocked_reason": (
            ""
            if executable
            else (
                target_blocked_reason
                or (
                    "equipment_condition_family_unclassified"
                    if equipment_scope and family_stage == "unknown"
                    else f"condition_not_admitted:{opcode}"
                )
            )
        ),
    }


def _typed_condition_payload(
    payload: dict[str, Any],
    target_alias_registry: dict[str, Any] | None = None,
    *,
    equipment_scope: bool = False,
    damage_tag_registry: dict[
        int, tuple[dict[str, Any], ...]
    ] | None = None,
    source: IRSource,
) -> dict[str, Any]:
    lowered: dict[str, Any] = {}
    if type(source) is not IRSource:
        raise TypeError("typed condition lowering requires a real parent source")
    condition_source = source
    for key, value in payload.items():
        if _is_target_expression_node(value):
            assert isinstance(value, dict)
            if _has_raw_json_path(condition_source):
                lowered[key] = _target_expression_execution_node(
                    value,
                    _target_child_source(condition_source, key, "TargetExpression"),
                )
            else:
                lowered[key] = {
                    "blocked_reason": "nested_target_source_missing",
                    "source_path": condition_source.source_path,
                }
        elif key in {
            "Chance",
            "CompareValue",
            "CompareNumber",
            "Number",
            "TargetCharacterID",
            "TargetMonsterID",
        }:
            lowered[key] = _numeric_expr_summary(value)
        elif key == "Predicate" and isinstance(value, dict):
            if _has_raw_json_path(condition_source):
                lowered[key] = _typed_condition_execution_node(
                    value,
                    target_alias_registry,
                    equipment_scope=equipment_scope,
                    damage_tag_registry=damage_tag_registry,
                    source=_target_child_source(condition_source, key, "TargetPredicate"),
                )
            else:
                lowered[key] = {"blocked_reason": "nested_target_source_missing"}
        elif key == "PredicateList" and isinstance(value, list):
            lowered[key] = [
                _typed_condition_execution_node(
                    item,
                    target_alias_registry,
                    equipment_scope=equipment_scope,
                    damage_tag_registry=damage_tag_registry,
                    source=_target_child_source(condition_source, f"{key}[{index}]", "TargetPredicate"),
                )
                if isinstance(item, dict) and _has_raw_json_path(condition_source)
                else {"schema_version": CONDITION_EXPRESSION_NODE_SCHEMA, "supported": False, "blocked_reason": "condition_child_not_object"}
                for index, item in enumerate(value)
            ]
        elif key == "DamageTagList":
            lowered[key] = _typed_damage_tag_list(
                value,
                damage_tag_registry or {},
            )
        else:
            lowered[key] = _json_safe(value)
    return lowered


def _condition_source_from_parent(source: IRSource, field_name: str) -> IRSource:
    """Derive nested condition lineage without manufacturing a raw location."""

    if _has_raw_json_path(source):
        return _target_child_source(source, field_name, "Condition")
    return IRSource(
        source_path=source.source_path,
        raw_type="Condition",
        raw_id=f"{source.raw_id}:{field_name}",
        evidence=cast(dict[str, JSONValue], freeze_json(dict(source.evidence))),
    )


def _typed_damage_tag_list(
    value: Any,
    registry: dict[int, tuple[dict[str, Any], ...]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [
            {
                "blocked_reason": "damage_tag_list_not_array",
                "raw": _json_safe(value),
            }
        ]
    lowered: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, str) and item:
            name_candidates = tuple(
                candidate
                for candidates in registry.values()
                for candidate in candidates
                if candidate.get("name") == item
            )
            if len(name_candidates) != 1:
                lowered.append(
                    {
                        "index": index,
                        "name": item,
                        "candidate_count": len(name_candidates),
                        "blocked_reason": (
                            "damage_tag_name_mapping_missing"
                            if not name_candidates
                            else "damage_tag_name_mapping_ambiguous"
                        ),
                    }
                )
                continue
            candidate = name_candidates[0]
            lowered.append(
                {
                    "index": index,
                    "name": item,
                    "enum_value": candidate.get("value"),
                    "source_mode": "raw_literal_verified_json_enum",
                    "source": candidate.get("source"),
                }
            )
            continue
        if not isinstance(item, dict):
            lowered.append(
                {
                    "index": index,
                    "blocked_reason": "damage_tag_entry_invalid",
                    "raw": _json_safe(item),
                }
            )
            continue
        enum_index = item.get("EnumIndex")
        enum_value = item.get("Value")
        if (
            not isinstance(enum_index, int)
            or isinstance(enum_index, bool)
            or enum_index < 0
        ):
            lowered.append(
                {
                    "index": index,
                    "enum_index": enum_index,
                    "enum_value": enum_value,
                    "blocked_reason": "damage_tag_enum_index_invalid",
                    "raw": _json_safe(item),
                }
            )
            continue
        candidates = (
            registry.get(enum_value, ())
            if (
                isinstance(enum_value, int)
                and not isinstance(enum_value, bool)
            )
            else ()
        )
        if len(candidates) != 1:
            lowered.append(
                {
                    "index": index,
                    "enum_index": enum_index,
                    "enum_value": enum_value,
                    "candidate_count": len(candidates),
                    "blocked_reason": (
                        "damage_tag_enum_mapping_missing"
                        if not candidates
                        else "damage_tag_enum_mapping_ambiguous"
                    ),
                    "raw": _json_safe(item),
                }
            )
            continue
        candidate = candidates[0]
        lowered.append(
            {
                "index": index,
                "name": candidate["name"],
                "enum_index": enum_index,
                "enum_value": enum_value,
                "source_mode": "json_enum_define",
                "enum_index_source_mode": "raw_typed_field_context",
                "source": candidate["source"],
            }
        )
    return lowered


def _condition_payload_with_tbgd_defaults(
    opcode: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Project omitted serialized enum defaults without hiding their origin."""

    if opcode != "ByCurrentSkillType" or "SkillType" in payload:
        return payload
    return {
        **payload,
        "SkillType": "Normal",
        "SkillTypeSourceMode": "tbgd_omitted_enum_default",
    }


def _effect_coverage_status(opcode: str, payload: dict[str, Any]) -> str:
    if opcode == "AddModifier":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if not standard.get("modifier_name"):
            return "blocked"
        if standard.get("target_expression_coverage_status") == "executable":
            return "executable"
        if _target_alias_admitted(str(standard.get("target_alias") or "")):
            return "executable"
        return "blocked"
    if opcode in REMOVE_MODIFIER_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        has_modifier = isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))
        has_status = isinstance(standard.get("status_id"), str) and bool(standard.get("status_id"))
        if (
            (has_modifier or has_status)
            and (
                standard.get("target_expression_coverage_status") == "executable"
                or _target_alias_admitted(str(standard.get("target_alias") or ""))
            )
        ):
            return "executable"
        return "blocked"
    if opcode in DISPEL_STATUS_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("blocked_reason"):
            return "blocked"
        if standard.get("target_expression_coverage_status") == "executable":
            return "executable"
        if _target_alias_admitted(str(standard.get("target_alias") or "")):
            return "executable"
        return "blocked"
    if opcode in HEAL_OPCODES | SHIELD_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("blocked_reason"):
            return "blocked"
        if (
            standard.get("target_expression_coverage_status") != "executable"
            and not _target_alias_admitted(str(standard.get("target_alias") or ""))
        ):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("amount")):
            return "blocked"
        return "executable"
    if opcode in REMOVE_SHIELD_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_expression_coverage_status") == "executable":
            return "executable"
        return (
            "executable"
            if _target_alias_admitted(str(standard.get("target_alias") or ""))
            else "blocked"
        )
    if opcode in MECHANISM_BAR_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if _mechanism_bar_has_runtime_payload(standard):
            return "executable"
        return "blocked"
    if opcode in RESOURCE_DELTA_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("blocked_reason"):
            return "blocked"
        if standard.get("resource") not in {
            "skill_points",
            "max_skill_points",
        } and (
            standard.get("target_expression_coverage_status") != "executable"
            and not _target_alias_admitted(str(standard.get("target_alias") or ""))
        ):
            return "blocked"
        if not isinstance(standard.get("resource"), str):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("amount")):
            return "blocked"
        return "executable"
    if opcode in HP_LOSS_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("blocked_reason"):
            return "blocked"
        if (
            standard.get("target_expression_coverage_status") != "executable"
            and not _target_alias_admitted(str(standard.get("target_alias") or ""))
        ):
            return "blocked"
        if standard.get("ratio_type") not in {"MaxHP", "CurrentHP"}:
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("ratio")):
            return "blocked"
        return "executable"
    if opcode == "TriggerAbility":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if not isinstance(standard.get("ability_name"), str) or not standard.get("ability_name"):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        return "executable"
    if opcode == "OwnerEntityAddAbility":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if not isinstance(standard.get("ability_name"), str) or not standard.get("ability_name"):
            return "blocked"
        return "executable"
    if opcode == "AttachEntityDeparted":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        return (
            "executable"
            if standard.get("target_alias") == "ModifierOwnerEntity"
            and standard.get("target_expression_coverage_status") == "executable"
            and isinstance(standard.get("config_group_name"), str)
            else "blocked"
        )
    if is_dynamic_value_opcode(opcode):
        standard = payload.get("standard")
        operation = (
            standard.get("dynamic_operation")
            if isinstance(standard, dict)
            else None
        )
        return (
            "executable"
            if isinstance(operation, dict)
            and operation.get("coverage_status") == "executable"
            else "blocked"
        )
    if opcode == "DefineDynamicValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
            return "blocked"
        if not isinstance(standard.get("value_name"), str) or not standard.get("value_name"):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("value_expr")):
            return "blocked"
        return "executable"
    if opcode == "SetDynamicValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
            return "blocked"
        if not isinstance(standard.get("value_name"), str) or not standard.get("value_name"):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("value_expr")):
            return "blocked"
        return "executable"
    if opcode == "SetDynamicValueByAddValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
            return "blocked"
        if not isinstance(standard.get("value_name"), str) or not standard.get("value_name"):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("add_value")):
            return "blocked"
        return "executable"
    if opcode == "SetDynamicValueByModifierValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if standard.get("source_target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if not isinstance(standard.get("source_modifier"), str) or not standard.get("source_modifier"):
            return "blocked"
        if not isinstance(standard.get("target_value_name"), str) or not standard.get("target_value_name"):
            return "blocked"
        if standard.get("source_value_name") not in SUPPORTED_MODIFIER_VALUE_TYPES:
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("multiplier")):
            return "blocked"
        return "executable"
    if opcode == "TriggerModifierCustomEvent":
        standard = payload.get("standard")
        if not isinstance(standard, dict) or standard.get("blocked_reason"):
            return "blocked"
        if standard.get("target_expression_coverage_status") != "executable":
            return "blocked"
        if not isinstance(standard.get("dynamic_key"), str) or not standard.get("dynamic_key"):
            return "blocked"
        if not isinstance(standard.get("event_type"), (int, str)) or isinstance(
            standard.get("event_type"), bool
        ):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("value_expr")):
            return "blocked"
        return "executable"
    if opcode == "StackWeakness":
        standard = payload.get("standard")
        if not isinstance(standard, dict) or standard.get("blocked_reason"):
            return "blocked"
        if standard.get("operation_type") != "Attach":
            return "blocked"
        weaknesses = standard.get("weaknesses")
        if not isinstance(weaknesses, list) or not weaknesses:
            return "blocked"
        if not all(isinstance(item, str) and item for item in weaknesses):
            return "blocked"
        if standard.get("target_expression_coverage_status") != "executable":
            return "blocked"
        return "executable"
    return classify_opcode(opcode)


def _predicate_task_status(condition: ConditionIR | None) -> tuple[str, str]:
    if condition is None:
        return "blocked", "missing_predicate_condition"
    if condition.coverage_status != "executable":
        return "blocked", f"condition_not_executable:{condition.coverage_status}:{condition.opcode}"
    return "executable", ""


def _retarget_task_evidence(task: dict[str, Any]) -> dict[str, Any]:
    target_alias = _target_alias(task.get("TargetType")) or ""
    return {
        "target_alias": target_alias,
        "include_limbo": bool(task.get("IncludeLimbo")) if isinstance(task.get("IncludeLimbo"), bool) else False,
        "max_number_expr": _numeric_expr_summary(task.get("MaxNumber")),
        "candidate_policy": _retarget_candidate_policy(target_alias),
    }


def _retarget_candidate_policy(target_alias: str) -> dict[str, Any]:
    if target_alias == "ParamEntityAttackTargetList.SortByHP":
        return {
            "candidate_source": "event.param_entity_attack_target_ids_or_action_targets",
            "sort": "hp_ascending",
            "alive_targets_first": True,
            "fallback": "lowest_hp_alive_enemy_of_status_owner",
            "admission_status": "executable",
        }
    return {
        "candidate_source": target_alias,
        "admission_status": "blocked",
        "blocked_reason": f"retarget_alias_not_admitted:{target_alias or 'missing'}",
    }


def _retarget_task_status(condition: ConditionIR | None, child_task_ids: list[str]) -> tuple[str, str]:
    if condition is not None and condition.coverage_status != "executable":
        return "blocked", f"condition_not_executable:{condition.coverage_status}:{condition.opcode}"
    if not child_task_ids:
        return "blocked", "retarget_child_task_missing"
    return "executable", ""


def _equipment_task_admission(
    event: str,
    opcode: str,
    task: dict[str, Any],
    *,
    modifier_name: str,
) -> tuple[str, str]:
    stage = classify_equipment_task(opcode, task)
    if stage == "non_gameplay":
        return "blocked", "equipment_task_family_non_gameplay"
    if stage == "unknown":
        return "blocked", "equipment_task_family_unclassified"
    if opcode == "PredicateTaskList":
        return "blocked", "predicate_task_requires_condition_lowering"
    if opcode in {
        "IncludeTaskListTemplate",
        "LoopExecuteTaskList",
        "RandomConfig",
        "Retarget",
    }:
        return "executable", ""
    if opcode in {
        "SetDynamicValueByCharacterCount",
        "SetDynamicValueByBehaviorFlagCount",
        "SetDynamicValueByChangeValue",
        "SetDynamicValueByCopying",
        "SetDynamicValueByCountOfBaseType",
        "SetDynamicValueByHPRatio",
        "SetDynamicValueByProperty",
        "SetDynamicValueByStatusCount",
        "SetDynamicValueByWeaknessCount",
        "SetModifierDynamicValue",
        "StackProperty",
        "SetDynamicValueByAttackTargetCount",
        "SetDynamicValueByBPChange",
        "SetDynamicValueByDamageDataProperty",
        "SetDynamicValueByHealDataProperty",
        "SetDynamicValueByMaxBP",
        "SetDynamicValueByVariateType",
    }:
        return _equipment_structured_task_admission(opcode, task)
    if opcode == "ModifyDamageData":
        terms = _damage_modifier_terms(task)
        if not terms:
            return "blocked", "modify_damage_data_fields_missing"
        blocked = tuple(
            term for term in terms if term.get("coverage_status") != "executable"
        )
        if blocked:
            return "blocked", str(
                blocked[0].get("blocked_reason")
                or "modify_damage_data_term_not_executable"
            )
        return "executable", ""
    if opcode == "DamageByAttackProperty":
        return _equipment_damage_task_admission(task)
    if opcode == "ModifyHealData":
        heal_ratio = _numeric_expr_summary(task.get("Healer_HealRatio"))
        if _numeric_expr_can_be_runtime_bound(heal_ratio):
            return "executable", ""
        return "blocked", str(
            heal_ratio.get("reason") or "healer_heal_ratio_not_executable"
        )
    if opcode == "ModifyCurrentSkillDelayCost":
        normalized = _numeric_expr_summary(task.get("NormalizedValue"))
        if _numeric_expr_can_be_runtime_bound(normalized):
            return "executable", ""
        return "blocked", str(
            normalized.get("reason")
            or "current_skill_delay_cost_normalized_value_not_executable"
        )
    if opcode == "Remodifier":
        target_alias = _target_alias(task.get("TargetType"))
        caster_alias = _target_alias(task.get("CasterFilter"))
        flags = task.get("BehaviorFlagFilter")
        maximum = _numeric_expr_summary(task.get("MaxNumber"))
        if target_alias != "ParamEntity":
            return "blocked", "remodifier_target_alias_not_admitted"
        if caster_alias != "Caster":
            return "blocked", "remodifier_caster_filter_not_admitted"
        if not isinstance(flags, list) or not flags or not all(
            isinstance(item, str) and item for item in flags
        ):
            return "blocked", "remodifier_behavior_flag_filter_missing"
        if not _numeric_expr_can_be_runtime_bound(maximum):
            return "blocked", str(
                maximum.get("reason") or "remodifier_max_number_not_executable"
            )
        if not isinstance(task.get("TaskList"), list) or not isinstance(
            task.get("FailedTaskList"), list
        ):
            return "blocked", "remodifier_branch_missing"
        return "executable", ""
    if opcode == "SetResilience":
        if task.get("DoReset") not in {None, True, False}:
            return "blocked", "set_resilience_reset_flag_invalid"
        return "executable", ""
    if opcode in {"ModifyActionDelay", "SetActionDelay"}:
        delay_expr = _action_delay_expr(task, opcode)
        if _numeric_expr_can_be_runtime_bound(delay_expr):
            return "executable", ""
        return "blocked", str(
            delay_expr.get("reason") or "action_delay_value_not_executable"
        )
    payload = _effect_payload(task, opcode, modifier_name)
    standard = payload.get("standard")
    target_raw = task.get("TargetType")
    # This admission helper has no exact raw-node source.  It must not grant
    # executable target status by re-evaluating an untracked nested payload;
    # the source-aware target lowering path is the sole producer of that
    # status.
    coverage = _effect_coverage_status(opcode, payload)
    if coverage == "executable":
        return "executable", ""
    return "blocked", _effect_blocked_reason(opcode, payload, coverage)


def _equipment_damage_task_admission(task: dict[str, Any]) -> tuple[str, str]:
    attack_property = task.get("AttackProperty")
    if not isinstance(attack_property, dict):
        return "blocked", "attack_property_missing"
    attack_type = str(attack_property.get("AttackType") or task.get("AttackType") or "")
    formula_type = str(attack_property.get("FormulaType") or "")
    final_formula_type = str(attack_property.get("FinalFormulaType") or "")
    damage_value = _numeric_expr_summary(attack_property.get("DamageValue"))
    damage_percentage = _numeric_expr_summary(
        attack_property.get("DamagePercentage")
    )
    if attack_type == "DOT":
        if formula_type == "ByBreakDamage":
            scaling = _numeric_expr_summary(
                attack_property.get("BreakDamagePercentage")
            )
            if _numeric_expr_can_be_runtime_bound(scaling):
                return "executable", ""
            return "blocked", str(
                scaling.get("reason") or "break_damage_scaling_not_executable"
            )
        if _numeric_expr_can_be_runtime_bound(damage_value) or _numeric_expr_can_be_runtime_bound(
            damage_percentage
        ):
            return "executable", ""
        return "blocked", str(
            damage_value.get("reason")
            or damage_percentage.get("reason")
            or "dot_damage_value_not_executable"
        )
    if attack_type == "TrueDamage" or final_formula_type == "ByPureDamage":
        if _numeric_expr_can_be_runtime_bound(damage_value):
            return "executable", ""
        return "blocked", str(
            damage_value.get("reason") or "true_damage_value_not_executable"
        )
    if attack_type == "Pursued":
        if _numeric_expr_can_be_runtime_bound(damage_percentage) or _numeric_expr_can_be_runtime_bound(
            damage_value
        ):
            return "executable", ""
        return "blocked", str(
            damage_percentage.get("reason")
            or damage_value.get("reason")
            or "additional_damage_value_not_executable"
        )
    return "blocked", f"damage_attack_type_not_admitted:{attack_type or 'missing'}"


def _equipment_structured_task_admission(
    opcode: str,
    task: dict[str, Any],
) -> tuple[str, str]:
    if opcode == "StackProperty":
        property_name = task.get("Property")
        value = _numeric_expr_summary(task.get("PropertyValue"))
        if not isinstance(property_name, str) or not property_name:
            return "blocked", "stack_property_name_missing"
        if not _numeric_expr_can_be_runtime_bound(value):
            return "blocked", str(
                value.get("reason") or "stack_property_value_not_executable"
            )
        return "executable", ""
    dynamic_key = _value_field(
        task.get("DynamicKey")
        or task.get("ToDynamicKey")
        or task.get("Key")
    )
    if not isinstance(dynamic_key, str) or not dynamic_key:
        return "blocked", "dynamic_value_name_required"
    if opcode == "SetDynamicValueByCopying":
        from_key = _value_field(task.get("FromDynamicKey"))
        if not isinstance(from_key, str) or not from_key:
            return "blocked", "source_dynamic_value_name_required"
    if opcode == "SetDynamicValueByBehaviorFlagCount":
        behavior_flag = _value_field(task.get("BehaviorFlag"))
        if not isinstance(behavior_flag, str) or not behavior_flag:
            return "blocked", "behavior_flag_required"
        read_target = _target_alias(task.get("ReadTargetType"))
        if read_target not in EXECUTABLE_TARGET_ALIASES:
            return "blocked", (
                "dynamic_value_read_target_not_admitted:"
                f"{read_target or 'missing'}"
            )
    if opcode == "SetDynamicValueByProperty":
        property_name = _value_field(task.get("Value"))
        if not isinstance(property_name, str) or not property_name:
            return "blocked", "source_property_name_required"
    if opcode in {
        "SetDynamicValueByDamageDataProperty",
        "SetDynamicValueByHealDataProperty",
    }:
        read_target = _target_alias(task.get("ReadTargetType"))
        if read_target is not None and not read_target:
            return "blocked", "dynamic_value_read_target_invalid"
    if opcode == "SetDynamicValueByBPChange":
        value_type = task.get("ValueType")
        if value_type not in {None, "", "UnclampedDelta"}:
            return "blocked", f"bp_change_value_type_not_admitted:{value_type}"
    if opcode == "SetDynamicValueByVariateType":
        variate_type = task.get("VariateType")
        if variate_type != "ParamValue":
            return "blocked", f"variate_type_not_admitted:{variate_type or 'missing'}"
    return "executable", ""


def _status_callback_task_admission(event: str, opcode: str, task: dict[str, Any]) -> tuple[str, str]:
    foundational_effect_events = {
        "OnBeforeSkillUse",
        "OnBeforeAttack",
        "OnAfterAttack",
        "OnAfterSkillUse",
        "OnActionEnd",
        "OnCreate",
        "OnDestroy",
        "OnEnterBattle",
        "OnListenTurnEnd",
        "OnBeforeInsertActionPrepare",
        "OnInsertActionStart",
        "OnInsertActionFinish",
        "OnListenInsertAbilityFinish",
        "OnCustomEvent",
        "OnAfterBeingAttacked",
        "OnListenBeforeSkillUse",
        "OnBeingBreak",
    }
    if opcode in QUEUE_INTENT_OPCODES:
        actor_target_alias = _queue_actor_target_alias(task, opcode)
        ability_target_alias = _queue_ability_target_alias(task, opcode)
        skill_index_expr = _queue_skill_index_expr(task, opcode)
        coverage_status, blocked_reason = _queue_intent_admission(
            task=task,
            opcode=opcode,
            source=IRSource(source_path="Config/ConfigGlobalModifier/_admission_probe.json", raw_type="QueueIntentAdmissionProbe", raw_id=opcode),
            actor_target_alias=actor_target_alias,
            ability_target_alias=ability_target_alias,
            ability_name=_queue_action_ref_or_ability_name(task, opcode),
            skill_index_expr=skill_index_expr,
            priority_source={"priority_ordering_admitted": True},
            abort_policy=_queue_abort_policy(task),
        )
        if blocked_reason == "queue_intent_source_mode_not_admitted":
            return "executable", ""
        return coverage_status, blocked_reason
    if event in {"OnTriggerDeath", "OnTriggerDeathrattle"} and opcode == "ModifySPNew":
        payload = _effect_payload(task, opcode, "")
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if (
        event in {
            "OnTriggerDeath",
            "OnTriggerDeathrattle",
            "OnAfterSkillUse",
            "OnAfterBeingAttacked",
            "OnListenBeforeSkillUse",
            "OnBeingBreak",
            "OnListenAfterAttack",
            *foundational_effect_events,
        }
        and opcode in {
            "DefineDynamicValue",
            "SetDynamicValue",
            "SetDynamicValueByAddValue",
            "AddModifier",
            "RemoveModifier",
            "RemoveSelfModifier",
            "TriggerModifierCustomEvent",
            "StackWeakness",
        }
    ):
        payload = _effect_payload(task, opcode, "")
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if event in {"OnBeforeHitAll", "OnBeforeHit"} and opcode == "ModifyDamageData":
        terms = _damage_modifier_terms(task)
        unsupported = [term for term in terms if term.get("coverage_status") != "executable"]
        if unsupported:
            reason = str(unsupported[0].get("blocked_reason") or "modify_damage_data_term_not_executable")
            return "blocked", reason
        if not terms:
            return "blocked", "modify_damage_data_fields_missing"
        return "executable", ""
    if event in {"OnAfterHitAll", "OnAfterHit"} and opcode in {"SetDynamicValue", "SetDynamicValueByDamageDataProperty"}:
        if opcode == "SetDynamicValueByDamageDataProperty":
            dynamic_key = _value_field(task.get("DynamicKey"))
            property_name = _value_field(task.get("Property"))
            if not isinstance(dynamic_key, str) or not dynamic_key:
                return "blocked", "dynamic_value_name_required"
            if property_name not in {"Result_FinalDamageBase", "Result_FinalDamage"}:
                return "blocked", f"damage_data_property_not_admitted:{property_name}"
            return "executable", ""
        payload = _effect_payload(task, opcode, "")
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if event == "OnAfterBeingAttacked" and opcode == "DamageByAttackProperty":
        attack_property = task.get("AttackProperty")
        if not isinstance(attack_property, dict):
            return "blocked", "attack_property_missing"
        attack_type = str(attack_property.get("AttackType") or task.get("AttackType") or "")
        if attack_type != "TrueDamage":
            return "blocked", f"being_attacked_damage_attack_type_not_admitted:{attack_type}"
        damage_value = _numeric_expr_summary(attack_property.get("DamageValue"))
        if not _numeric_expr_can_be_runtime_bound(damage_value):
            return "blocked", f"true_damage_value_not_executable:{damage_value.get('reason') or damage_value.get('kind')}"
        return "executable", ""
    if event == "OnBeforeDying" and opcode == "RemoveModifier":
        payload = _effect_payload(task, opcode, "")
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if event == "OnListenAllowAction" and opcode == "RemoveSelfModifier":
        return "executable", ""
    if event == "OnCreate" and opcode == "OwnerEntityAddAbility":
        payload = _effect_payload(task, opcode, "")
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if event == "OnStack" and opcode == "AttachEntityDeparted":
        payload = _effect_payload(task, opcode, "")
        standard = payload.get("standard")
        if isinstance(standard, dict):
            # TargetType is omitted by this opcode and means the current
            # modifier owner. The full lowering path attaches the source-backed
            # implicit target expression below.
            standard["target_expression_coverage_status"] = "executable"
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if event not in {"OnStack", "OnPhase1", "OnListenTurnEnd"}:
        return "blocked", f"status_callback_event_not_admitted:{event}"
    if opcode == "DamageByAttackProperty":
        attack_property = task.get("AttackProperty")
        if not isinstance(attack_property, dict):
            return "blocked", "attack_property_missing"
        formula_type = str(attack_property.get("FormulaType") or "")
        attack_type = str(attack_property.get("AttackType") or task.get("AttackType") or "")
        if event != "OnPhase1":
            return "blocked", f"status_damage_event_not_admitted:{event}"
        if attack_type == "DOT" and formula_type != "ByBreakDamage":
            damage_value = _numeric_expr_summary(attack_property.get("DamageValue"))
            damage_percentage = _numeric_expr_summary(attack_property.get("DamagePercentage"))
            extra_formula_type = str(attack_property.get("ExtraFormulaType") or "")
            extra_damage_percentage = _numeric_expr_summary(attack_property.get("ExtraDamagePercentage"))
            if not _numeric_expr_can_be_runtime_bound(damage_value):
                if _numeric_expr_can_be_runtime_bound(damage_percentage):
                    if extra_formula_type and extra_formula_type != "ByDefence":
                        return "blocked", f"dot_extra_formula_type_not_admitted:{extra_formula_type}"
                    if extra_formula_type == "ByDefence" and not _numeric_expr_can_be_runtime_bound(extra_damage_percentage):
                        return "blocked", f"dot_extra_damage_percentage_not_executable:{extra_damage_percentage.get('reason') or extra_damage_percentage.get('kind')}"
                    return "executable", ""
                return "blocked", f"dot_damage_value_not_executable:{damage_value.get('reason') or damage_value.get('kind')}"
            if extra_formula_type and extra_formula_type != "ByDefence":
                return "blocked", f"dot_extra_formula_type_not_admitted:{extra_formula_type}"
            if extra_formula_type == "ByDefence" and not _numeric_expr_can_be_runtime_bound(extra_damage_percentage):
                return "blocked", f"dot_extra_damage_percentage_not_executable:{extra_damage_percentage.get('reason') or extra_damage_percentage.get('kind')}"
            return "executable", ""
        if formula_type != "ByBreakDamage":
            return "blocked", f"status_damage_formula_not_admitted:{formula_type}"
        if attack_type != "DOT":
            return "blocked", f"status_damage_attack_type_not_admitted:{attack_type}"
        scaling_expr = _numeric_expr_summary(attack_property.get("BreakDamagePercentage"))
        if not _numeric_expr_can_be_runtime_bound(scaling_expr):
            return "blocked", f"status_damage_scaling_not_executable:{scaling_expr.get('reason') or scaling_expr.get('kind')}"
        return "executable", ""
    if opcode in {"ModifyActionDelay", "SetActionDelay"}:
        if event not in {"OnStack", "OnListenTurnEnd"}:
            return "blocked", f"action_delay_event_not_admitted:{event}"
        if opcode == "ModifyActionDelay":
            return "blocked", "normalized_action_delay_scale_not_admitted"
        delay_expr = _action_delay_expr(task, opcode)
        if _numeric_expr_can_be_runtime_bound(delay_expr):
            return "executable", ""
        return "blocked", f"action_delay_numeric_not_executable:{delay_expr.get('reason') or delay_expr.get('kind')}"
    return "blocked", f"status_callback_task_opcode_not_admitted:{opcode}"


def _status_callback_source_admitted(
    relative_path: str,
    *,
    equipment_source_admitted: bool = False,
) -> bool:
    return (
        equipment_source_admitted
        or
        relative_path == "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
        or _mainline_avatar_ability_source(relative_path)
        or _mainline_monster_ability_source(relative_path)
        or (_queue_source_candidate(relative_path) and not _queue_source_blocked(relative_path))
    )


def _status_callback_task_source_admitted(
    relative_path: str,
    event: str,
    opcode: str,
    *,
    equipment_source_admitted: bool = False,
) -> bool:
    if _status_callback_source_admitted(
        relative_path,
        equipment_source_admitted=equipment_source_admitted,
    ):
        return True
    if (
        _queue_source_candidate(relative_path)
        and not _queue_source_blocked(relative_path)
        and event in {"OnTriggerDeath", "OnTriggerDeathrattle", "OnAfterSkillUse"}
        and opcode in {"SetDynamicValue", "AddModifier", "ModifySPNew"}
    ):
        return True
    return False


def _status_callback_source_mode(
    relative_path: str,
    *,
    equipment_source_admitted: bool = False,
) -> str:
    if equipment_source_admitted:
        return "mainline_equipment_ability"
    if _status_callback_source_admitted(relative_path):
        if _mainline_avatar_ability_source(relative_path):
            return "mainline_avatar_ability"
        if _mainline_monster_ability_source(relative_path):
            return "mainline_monster_ability"
        return "mainline_global_modifier"
    if "Rogue" in relative_path or "Activity" in relative_path or "GridFight" in relative_path:
        return "special_mode_audit_only"
    return "mainline_unadmitted"


def _status_callback_scope_kind(event: str) -> str:
    resource_scope = resource_scope_for_callback(event)
    if resource_scope:
        return resource_scope
    if event in {"OnListenCharacterDie", "OnListenAllowAction"}:
        return "owner_local"
    if event in {"OnAfterDealHeal", "OnBeforeDealHeal"}:
        return "actor_local"
    if event in {
        "OnHPChange",
        "OnHPOverflow",
        "OnAfterBeingHeal",
        "OnBeforeBeingHeal",
        "OnShieldChange",
        "OnBeforeBeingStanceDamage",
        "OnBeingStanceDamage",
        "OnActionDelayEffect",
        "OnActionDelayEffectAll",
        "OnDefenderPrepareAttackData",
        "OnDeathrattle",
    }:
        return "being_hit_target_local"
    if event in {
        "OnBeforeHitAll",
        "OnAfterHitAll",
        "OnAfterSkillUse",
        "OnBeforeSkillUse",
        "OnBeforeAttack",
        "OnAfterAttack",
        "OnActionEnd",
        "OnBeforeInsertActionPrepare",
        "OnInsertActionStart",
        "OnInsertActionFinish",
        "OnListenInsertAbilityFinish",
    }:
        return "actor_local"
    if event in {
        "OnCreate",
        "OnDestroy",
        "OnStack",
        "OnPhase1",
        "OnPhase2",
        "OnModifierAdd",
        "OnModifierRemove",
        "OnAddModifierSuc",
        "OnModifierOnStack",
        "OnModifierDotAdd",
    }:
        return "status_local"
    if event in {"OnSnapshotCreate"}:
        return "global_listener"
    if event.startswith("OnListen"):
        return "global_listener"
    if event.startswith("OnBeing") or "BeingHit" in event or "BeingAttacked" in event:
        return "being_hit_target_local"
    if "Hit" in event:
        return "per_hit_target_local"
    return "owner_local"


def _mainline_avatar_ability_source(relative_path: str) -> bool:
    if not relative_path.startswith("Config/ConfigAbility/Avatar/"):
        return False
    blocked_tokens = (
        "/Activity/",
        "/Rogue/",
        "/GridFight/",
        "/ElationBattle/",
        "/Fate/",
        "/Story/",
        "/Level/",
        "/SubLevelGraph/",
        "/TrialPlayer/",
    )
    return not any(token in relative_path for token in blocked_tokens)


def _mainline_monster_ability_source(relative_path: str) -> bool:
    if not relative_path.startswith("Config/ConfigAbility/Monster/"):
        return False
    return not _queue_source_blocked(relative_path)


def _status_damage_emission_from_task(
    *,
    callback_id: str,
    task_id: str,
    modifier_name: str,
    event: str,
    task: dict[str, Any],
    source: IRSource,
) -> StatusDamageEmissionIR | None:
    attack_property = task.get("AttackProperty")
    if not isinstance(attack_property, dict):
        return None
    formula_type = str(attack_property.get("FormulaType") or "")
    attack_type = str(attack_property.get("AttackType") or task.get("AttackType") or "")
    if formula_type == "ByBreakDamage":
        damage_formula_family = "break"
        scaling_expr = _numeric_expr_summary(attack_property.get("BreakDamagePercentage"))
        element_type = None
    elif attack_type == "TrueDamage":
        damage_formula_family = "true_damage"
        scaling_expr = _numeric_expr_summary(attack_property.get("DamageValue"))
        element_type = _attack_property_element_type(attack_property)
    elif str(attack_property.get("FinalFormulaType") or "") == "ByPureDamage":
        damage_formula_family = "true_damage"
        scaling_expr = _numeric_expr_summary(attack_property.get("DamageValue"))
        element_type = _attack_property_element_type(attack_property)
    elif attack_type == "Pursued":
        damage_formula_family = "additional"
        scaling_expr = {
            "kind": "additional_attack_property",
            "damage_percentage": _numeric_expr_summary(
                attack_property.get("DamagePercentage")
            ),
            "damage_value": _numeric_expr_summary(
                attack_property.get("DamageValue")
            ),
            "final_formula_type": str(
                attack_property.get("FinalFormulaType") or ""
            ),
        }
        element_type = _attack_property_element_type(attack_property)
    elif attack_type == "DOT":
        damage_formula_family = "dot"
        scaling_expr = {
            "kind": "dot_attack_property",
            "damage_percentage": _numeric_expr_summary(attack_property.get("DamagePercentage")),
            "damage_percentage_basis": {
                "kind": "unit_stat",
                "supported": True,
                "unit_ref": "attacker",
                "stat": "attack",
                "source_kind": "damage_by_attack_property_contract",
                "source_field": "AttackProperty.DamagePercentage",
                "source_trace": source.to_json(),
            },
            "damage_value": _numeric_expr_summary(attack_property.get("DamageValue")),
            "formula_type": str(attack_property.get("FormulaType") or ""),
            "extra_formula_type": str(attack_property.get("ExtraFormulaType") or ""),
            "extra_damage_percentage": _numeric_expr_summary(attack_property.get("ExtraDamagePercentage")),
        }
        element_type = _attack_property_element_type(attack_property)
    else:
        return None
    if bool(source.evidence.get("equipment_ability_source_admitted")):
        coverage_status, blocked_reason = _equipment_damage_task_admission(task)
    else:
        coverage_status, blocked_reason = _status_callback_task_admission(
            event,
            "DamageByAttackProperty",
            task,
        )
    if coverage_status == "executable" and not _status_callback_source_admitted(
        source.source_path,
        equipment_source_admitted=bool(
            source.evidence.get("equipment_ability_source_admitted")
        ),
    ):
        coverage_status = "blocked"
        blocked_reason = "status_callback_source_mode_not_admitted"
    return StatusDamageEmissionIR(
        status_damage_emission_id=f"status_damage_emission:{callback_id}:{task_id}",
        callback_id=callback_id,
        source_task_id=task_id,
        modifier_name=modifier_name,
        event=event,
        attack_type=attack_type,
        damage_formula_family=damage_formula_family,
        element_type=element_type,
        scaling_expr=scaling_expr,
        source=source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _damage_modifier_from_task(
    *,
    callback_id: str,
    task_id: str,
    modifier_name: str,
    event: str,
    task: dict[str, Any],
    source: IRSource,
) -> DamageModifierIR:
    terms = tuple(_damage_modifier_terms(task))
    if bool(source.evidence.get("equipment_ability_source_admitted")):
        coverage_status, blocked_reason = _equipment_task_admission(
            event,
            "ModifyDamageData",
            task,
            modifier_name=modifier_name,
        )
    else:
        coverage_status, blocked_reason = _status_callback_task_admission(
            event,
            "ModifyDamageData",
            task,
        )
    if coverage_status == "executable" and not _status_callback_source_admitted(
        source.source_path,
        equipment_source_admitted=bool(
            source.evidence.get("equipment_ability_source_admitted")
        ),
    ):
        coverage_status = "blocked"
        blocked_reason = "status_callback_source_mode_not_admitted"
    return DamageModifierIR(
        damage_modifier_id=f"damage_modifier:{callback_id}:{task_id}",
        callback_id=callback_id,
        source_task_id=task_id,
        modifier_name=modifier_name,
        event=event,
        target_alias="ParamEntity",
        modifier_terms=terms,
        source=source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _damage_modifier_terms(task: dict[str, Any]) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    supported_fields = {
        "AttackData_DamageValue": ("base", "damage_value", "attack_data"),
        "Attacker_AttackAddedRatio": ("base", "attack_added_ratio", "attacker"),
        "Attacker_AllDamageTypeAddedRatio": (
            "damage_bonus",
            "damage_added_ratio",
            "attacker",
        ),
        "Attacker_CriticalChance": ("crit", "critical_chance", "attacker"),
        "Attacker_CriticalDamage": ("crit", "critical_damage", "attacker"),
        "Defender_DefenceAddedRatio": ("defense", "defender_defence_added_ratio", "defender"),
        "Defender_AllDamageTypeTakenRatio": (
            "damage_taken",
            "damage_taken_ratio",
            "defender",
        ),
        "Defender_AllDamageReduce": (
            "damage_reduction",
            "damage_reduction",
            "defender",
        ),
    }
    ignored = {"$type", "TaskList", "SuccessTaskList", "FailedTaskList", "CallbackConfig"}
    for field, value in task.items():
        if field in ignored:
            continue
        bucket_info = supported_fields.get(field)
        expr = _numeric_expr_summary(value)
        if bucket_info is None:
            terms.append(
                {
                    "field": field,
                    "bucket": "unknown",
                    "key": field,
                    "scope": "unknown",
                    "numeric_expr": expr,
                    "coverage_status": "blocked",
                    "blocked_reason": f"modify_damage_data_field_not_admitted:{field}",
                }
            )
            continue
        bucket, key, scope = bucket_info
        if not _numeric_expr_can_be_runtime_bound(expr):
            terms.append(
                {
                    "field": field,
                    "bucket": bucket,
                    "key": key,
                    "scope": scope,
                    "numeric_expr": expr,
                    "coverage_status": "blocked",
                    "blocked_reason": str(expr.get("reason") or f"modify_damage_data_value_not_executable:{field}"),
                }
            )
            continue
        terms.append(
            {
                "field": field,
                "bucket": bucket,
                "key": key,
                "scope": scope,
                "target_alias": "ParamEntity",
                "numeric_expr": expr,
                "coverage_status": "executable",
                "blocked_reason": "",
            }
        )
    return terms


def _action_delay_emission_from_task(
    *,
    callback_id: str,
    task_id: str,
    modifier_name: str,
    event: str,
    opcode: str,
    task: dict[str, Any],
    source: IRSource,
) -> ActionDelayEmissionIR:
    delay_mode = _value_field(task.get("DelayType")) or _value_field(task.get("ActionDelayType")) or _first_present_key(
        task,
        ("AddNormalizedValue", "SetNormalizedValue", "FixedValue", "Value"),
    )
    delay_expr = _action_delay_expr(task, opcode)
    if bool(source.evidence.get("equipment_ability_source_admitted")):
        coverage_status, blocked_reason = _equipment_task_admission(
            event,
            opcode,
            task,
            modifier_name=modifier_name,
        )
    else:
        coverage_status, blocked_reason = _status_callback_task_admission(
            event,
            opcode,
            task,
        )
    if coverage_status == "executable" and not _status_callback_source_admitted(
        source.source_path,
        equipment_source_admitted=bool(
            source.evidence.get("equipment_ability_source_admitted")
        ),
    ):
        coverage_status = "blocked"
        blocked_reason = "status_callback_source_mode_not_admitted"
    return ActionDelayEmissionIR(
        action_delay_emission_id=f"action_delay_emission:{callback_id}:{task_id}",
        callback_id=callback_id,
        source_task_id=task_id,
        modifier_name=modifier_name,
        event=event,
        opcode=opcode,
        target_alias=_target_alias(task.get("TargetType")) or "ModifierOwnerEntity",
        delay_mode=str(delay_mode or opcode),
        delay_expr=delay_expr,
        source=source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _action_delay_expr(task: dict[str, Any], opcode: str) -> dict[str, Any]:
    key = _first_present_key(
        task,
        (
            "AddNormalizedValue",
            "SetNormalizedValue",
            "FixedAddNormalizedValue",
            "FixedSetNormalizedValue",
            "DelayValue",
            "Value",
        ),
    )
    if not key:
        return {"kind": "missing", "value": None, "supported": False, "reason": "action_delay_value_missing"}
    expr = _numeric_expr_summary(task.get(key))
    expr["source_field"] = key
    expr["opcode"] = opcode
    return expr


def _lower_summon_monster_intents(
    *,
    ability_tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    combatant_profiles: list[CombatantProfileIR],
    monster_data_cards: list[MonsterDataCardIR],
) -> list[SummonMonsterIntentIR]:
    effect_by_id = {effect.effect_id: effect for effect in effects}
    profile_by_entity = {profile.entity_id: profile for profile in combatant_profiles}
    card_by_entity = {card.entity_ref: card for card in monster_data_cards}
    intents: list[SummonMonsterIntentIR] = []
    for task in sorted(ability_tasks, key=lambda item: item.task_id):
        if task.opcode != "SummonMonster":
            continue
        effect = effect_by_id.get(task.effect_id)
        payload = effect.payload if effect is not None else {}
        entries_raw = payload.get("SummonMonsterDataList") if isinstance(payload, dict) else None
        delay_policy = _summon_monster_delay_policy(payload if isinstance(payload, dict) else {}, task)
        entries: list[SummonMonsterEntryIR] = []
        if isinstance(entries_raw, list):
            for entry_index, raw_entry in enumerate(entries_raw):
                if not isinstance(raw_entry, dict):
                    continue
                entries.append(
                    _summon_monster_entry_from_raw(
                        task,
                        raw_entry,
                        entry_index,
                        profile_by_entity=profile_by_entity,
                        card_by_entity=card_by_entity,
                    )
                )
        source_admitted = _mainline_monster_ability_source(task.source.source_path)
        blocked_reasons: list[str] = []
        if not source_admitted:
            blocked_reasons.append("summon_monster_source_mode_not_admitted")
        if not entries:
            blocked_reasons.append("summon_monster_entries_missing")
        if delay_policy.get("admission_status") != "executable":
            blocked_reasons.append(str(delay_policy.get("blocked_reason") or "summon_monster_delay_ratio_not_admitted"))
        for entry in entries:
            if entry.coverage_status != "executable":
                blocked_reasons.append(entry.blocked_reason or f"summon_monster_entry_not_executable:{entry.coverage_status}")
        blocked_reason = ";".join(dict.fromkeys(reason for reason in blocked_reasons if reason))
        source = IRSource(
            source_path=task.source.source_path,
            raw_type="SummonMonsterIntent",
            raw_id=task.task_id,
            evidence={
                "source_task": task.to_json(),
                "effect": effect.to_json() if effect is not None else {},
                "entry_count": len(entries),
                "delay_policy": delay_policy,
                "source_admitted": source_admitted,
                "admission_policy": "mainline_monster_ability_fixed_monster_id_profile_card_zero_or_missing_delay_ratio",
            },
        )
        intents.append(
            SummonMonsterIntentIR(
                summon_intent_id=f"summon_monster_intent:{task.task_id}",
                source_task_id=task.task_id,
                owner_scope="caster",
                target_scope="summoned_monster_entries",
                delay_policy=delay_policy,
                entries=tuple(entries),
                source_event=task.callback_kind,
                source=source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
            )
        )
    return intents


def _admit_summon_monster_ability_tasks(
    tasks: list[AbilityTaskIR],
    intents: list[SummonMonsterIntentIR],
    birth_templates: list[UnitBirthTemplateIR],
) -> list[AbilityTaskIR]:
    intents_by_task: dict[str, list[SummonMonsterIntentIR]] = {}
    for intent in intents:
        intents_by_task.setdefault(intent.source_task_id, []).append(intent)
    templates_by_id: dict[str, list[UnitBirthTemplateIR]] = {}
    for template in birth_templates:
        templates_by_id.setdefault(template.birth_template_id, []).append(template)
    admitted: list[AbilityTaskIR] = []
    for task in tasks:
        if task.opcode != "SummonMonster":
            admitted.append(task)
            continue
        candidates = intents_by_task.get(task.task_id, ())
        reasons: list[str] = []
        if len(candidates) != 1:
            reasons.append(
                "summon_monster_intent_missing"
                if not candidates
                else "summon_monster_intent_ambiguous"
            )
        else:
            intent = candidates[0]
            if intent.coverage_status != "executable":
                reasons.append(
                    intent.blocked_reason
                    or f"summon_monster_intent_not_executable:{intent.coverage_status}"
                )
            if not intent.entries:
                reasons.append("summon_monster_entries_missing")
            for entry in intent.entries:
                templates = templates_by_id.get(entry.birth_template_id, ())
                if len(templates) != 1:
                    reasons.append(
                        "summon_monster_birth_template_missing"
                        if not templates
                        else "summon_monster_birth_template_ambiguous"
                    )
                elif templates[0].coverage_status != "executable":
                    reasons.append(
                        templates[0].blocked_reason
                        or "summon_monster_birth_template_not_executable"
                    )
        blocked_reason = ";".join(
            dict.fromkeys(reason for reason in reasons if reason)
        )
        admitted.append(
            replace(
                task,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
            )
        )
    return admitted


def _summon_monster_delay_policy(payload: dict[str, Any], task: AbilityTaskIR) -> dict[str, Any]:
    if "DelayRatio" not in payload:
        return {
            "kind": "missing",
            "source_field": "SummonMonster.DelayRatio",
            "admission_status": "executable",
            "runtime_policy": "initial_action_value_full_av_times_delay_ratio",
            "value": 1.0,
            "reason": "DelayRatio field absent; current runtime uses the default full action value, equivalent to ratio 1.",
        }
    expr = _numeric_expr_summary(payload.get("DelayRatio"))
    resolution = _resolve_summon_numeric_expr(
        task,
        expr,
        source_kind="summon_monster_delay_ratio",
        binding_missing_reason="summon_monster_delay_ratio_dynamic_binding_source_missing",
    )
    policy: dict[str, Any] = {
        "kind": str(expr.get("kind") or "unknown"),
        "source_field": "SummonMonster.DelayRatio",
        "expr": expr,
        "raw": _json_safe(payload.get("DelayRatio")),
        "resolution": resolution,
    }
    if resolution.get("ok") is not True or not isinstance(resolution.get("value"), (int, float)):
        return {
            **policy,
            "admission_status": "blocked",
            "blocked_reason": str(resolution.get("blocked_reason") or "summon_monster_delay_ratio_dynamic_not_admitted"),
            "runtime_policy": "blocked_until_delay_ratio_timeline_semantics_admitted",
        }
    value = float(resolution["value"])
    policy["value"] = value
    if value < 0:
        return {
            **policy,
            "admission_status": "blocked",
            "blocked_reason": "summon_monster_delay_ratio_negative_not_admitted",
            "runtime_policy": "blocked_until_negative_delay_ratio_semantics_admitted",
        }
    return {
        **policy,
        "admission_status": "executable",
        "runtime_policy": "initial_action_value_full_av_times_delay_ratio",
        "reason": "DelayRatio is admitted as a non-negative multiplier over the default full action value.",
    }


def _summon_monster_entry_from_raw(
    task: AbilityTaskIR,
    raw_entry: dict[str, Any],
    entry_index: int,
    *,
    profile_by_entity: dict[str, CombatantProfileIR],
    card_by_entity: dict[str, MonsterDataCardIR],
) -> SummonMonsterEntryIR:
    monster_expr = _summon_monster_id_expr(raw_entry)
    monster_resolution = _resolve_summon_monster_id_expr(task, monster_expr)
    monster_value = monster_resolution.get("value") if monster_resolution.get("ok") is True else None
    blocked_reasons: list[str] = []
    if monster_value is None:
        if raw_entry.get("MonsterIDFromCustomValue") is not None:
            blocked_reasons.append(
                _summon_monster_id_unbound_reason(
                    monster_expr,
                    str(monster_resolution.get("blocked_reason") or "summon_monster_id_from_custom_value_not_admitted"),
                )
            )
        elif monster_expr.get("kind") == "dynamic_hash":
            blocked_reasons.append(
                _summon_monster_id_unbound_reason(
                    monster_expr,
                    str(monster_resolution.get("blocked_reason") or "summon_monster_dynamic_monster_id_not_admitted"),
                )
            )
        elif monster_expr.get("kind") == "postfix_expr":
            blocked_reasons.append(
                _summon_monster_id_unbound_reason(
                    monster_expr,
                    str(
                        monster_resolution.get("blocked_reason")
                        or f"summon_monster_monster_id_expr_not_admitted:{monster_expr.get('reason') or 'postfix_expr'}"
                    ),
                )
            )
        elif monster_expr.get("kind") == "missing":
            blocked_reasons.append("summon_monster_monster_id_missing")
        else:
            blocked_reasons.append("summon_monster_fixed_monster_id_missing")
    monster_raw_id = str(int(monster_value)) if monster_value is not None else ""
    monster_entity_ref = f"monster:{monster_raw_id}" if monster_raw_id else ""
    profile = profile_by_entity.get(monster_entity_ref)
    card = card_by_entity.get(monster_entity_ref)
    id_normalization = _summon_monster_fixed_id_normalization(
        monster_raw_id,
        profile_by_entity=profile_by_entity,
        card_by_entity=card_by_entity,
    )
    if (profile is None or card is None) and id_normalization.get("admission_status") == "executable":
        monster_raw_id = str(id_normalization["normalized_monster_id"])
        monster_entity_ref = f"monster:{monster_raw_id}"
        profile = profile_by_entity.get(monster_entity_ref)
        card = card_by_entity.get(monster_entity_ref)
    if monster_entity_ref:
        if profile is None:
            blocked_reasons.append("summon_monster_profile_source_missing")
        elif profile.coverage_status != "executable":
            blocked_reasons.append(
                f"summon_monster_profile_source_blocked:{profile.blocked_reason or 'combatant_profile_blocked'}"
            )
        if card is None:
            blocked_reasons.append("summon_monster_data_card_source_missing")
    location_type = str(raw_entry.get("LocationType") or "")
    supported_location_types = {"BeforeCaster", "AfterCaster", "First", "Last", "KeepOnFirst", "KeepOnLast"}
    if not location_type:
        blocked_reasons.append("summon_monster_location_type_missing")
    elif location_type not in supported_location_types:
        blocked_reasons.append(f"summon_monster_location_type_not_admitted:{location_type}")
    position_policy = {
        "kind": "relative_location_type",
        "location_type": location_type,
        "init_anim_state_name": str(raw_entry.get("InitAnimStateName") or ""),
        "source_field": "SummonMonsterDataList.LocationType",
        "admission_status": "executable" if location_type in supported_location_types else "blocked",
        "blocked_reason": "" if location_type in supported_location_types else f"summon_monster_location_type_not_admitted:{location_type or 'missing'}",
    }
    count_policy = {
        "kind": "implicit_single_entry",
        "source_field": "SummonMonsterDataList",
        "admission_status": "executable",
        "value": 1,
        "reason": "current raw SummonMonsterDataList entries have no Count field; each list item lowers to one spawn instance.",
    }
    level_policy = {
        "kind": "profile_base_stats_no_runtime_level_scaling",
        "admission_status": "executable" if profile is not None and profile.coverage_status == "executable" else "blocked",
        "source_basis": "CombatantProfileIR.base_stats",
        "profile_id": profile.profile_id if profile is not None else "",
    }
    if level_policy["admission_status"] != "executable":
        if monster_entity_ref:
            if profile is None:
                blocked_reasons.append("summon_monster_level_policy_profile_source_missing")
            else:
                blocked_reasons.append(
                    f"summon_monster_level_policy_profile_source_blocked:{profile.blocked_reason or 'combatant_profile_blocked'}"
                )
        else:
            blocked_reasons.append("summon_monster_level_policy_monster_id_unresolved")
    blocked_reason = ";".join(dict.fromkeys(reason for reason in blocked_reasons if reason))
    source = IRSource(
        source_path=task.source.source_path,
        raw_type="SummonMonsterDataList",
        raw_id=f"{task.task_id}:{entry_index}",
        evidence={
            "source_task_id": task.task_id,
            "entry_index": entry_index,
            "raw_entry": _json_safe(raw_entry),
            "monster_id_expr": monster_expr,
            "monster_id_resolution": monster_resolution,
            "monster_id_normalization": id_normalization,
            "position_policy": position_policy,
            "count_policy": count_policy,
            "level_policy": level_policy,
            "wave_clear_policy_basis": "p1_3_conservative_enemy_summon_counts",
        },
    )
    return SummonMonsterEntryIR(
        entry_id=f"summon_monster_entry:{task.task_id}:{entry_index}",
        monster_entity_ref=monster_entity_ref,
        monster_raw_id=monster_raw_id,
        position_policy=position_policy,
        count=1,
        level_policy=level_policy,
        wave_clear_policy="blocked" if blocked_reason else "counts",
        source=source,
        birth_template_id=_summoned_monster_birth_template_id(task.task_id, entry_index),
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _summon_monster_fixed_id_normalization(
    monster_raw_id: str,
    *,
    profile_by_entity: dict[str, CombatantProfileIR],
    card_by_entity: dict[str, MonsterDataCardIR],
) -> dict[str, Any]:
    if not monster_raw_id or not monster_raw_id.endswith("00") or not monster_raw_id[:-2].isdigit():
        return {"admission_status": "not_applicable"}
    normalized = str(int(monster_raw_id) // 100)
    if normalized == monster_raw_id:
        return {"admission_status": "not_applicable"}
    normalized_ref = f"monster:{normalized}"
    profile = profile_by_entity.get(normalized_ref)
    card = card_by_entity.get(normalized_ref)
    if profile is None or profile.coverage_status != "executable" or card is None:
        return {
            "admission_status": "blocked",
            "blocked_reason": "summon_monster_fixed_id_x100_candidate_missing_profile_or_card",
            "raw_monster_id": monster_raw_id,
            "normalized_monster_id": normalized,
        }
    return {
        "admission_status": "executable",
        "normalization": "fixed_monster_id_x100_to_monster_config_id",
        "raw_monster_id": monster_raw_id,
        "normalized_monster_id": normalized,
        "normalized_entity_ref": normalized_ref,
        "profile_id": profile.profile_id,
        "card_id": card.card_id,
    }


def _summon_monster_id_expr(raw_entry: dict[str, Any]) -> dict[str, Any]:
    if raw_entry.get("MonsterID") is not None:
        expr = _numeric_expr_summary(raw_entry.get("MonsterID"))
        expr["source_field"] = "SummonMonsterDataList.MonsterID"
        return expr
    custom_value = raw_entry.get("MonsterIDFromCustomValue")
    if isinstance(custom_value, dict) and isinstance(custom_value.get("Hash"), int):
        return {
            "kind": "dynamic_hash",
            "hash": int(custom_value["Hash"]),
            "supported": True,
            "source_field": "SummonMonsterDataList.MonsterIDFromCustomValue.Hash",
            "raw": _json_safe(custom_value),
        }
    expr = _numeric_expr_summary(custom_value)
    expr["source_field"] = "SummonMonsterDataList.MonsterIDFromCustomValue"
    return expr


def _resolve_summon_monster_id_expr(task: AbilityTaskIR, monster_expr: dict[str, Any]) -> dict[str, Any]:
    result = _resolve_summon_numeric_expr(
        task,
        monster_expr,
        source_kind="dynamic_monster_id",
        binding_missing_reason="summon_monster_dynamic_binding_source_missing",
        fixed_source_kind="fixed_monster_id",
    )
    source_field = str(monster_expr.get("source_field") or "")
    if result.get("ok") is not True and source_field.endswith("MonsterIDFromCustomValue.Hash"):
        reason = str(result.get("blocked_reason") or "")
        if reason == "summon_monster_dynamic_binding_source_missing":
            result["blocked_reason"] = "custom_value_hash_to_name_binding_missing"
        elif reason.startswith("dynamic_hash_unbound:"):
            result["blocked_reason"] = f"custom_value_hash_unbound:{reason.removeprefix('dynamic_hash_unbound:')}"
        result["custom_value_binding_candidates"] = _custom_value_binding_candidates_from_task(task)
    return result


def _resolve_summon_numeric_expr(
    task: AbilityTaskIR,
    numeric_expr: dict[str, Any],
    *,
    source_kind: str,
    binding_missing_reason: str,
    fixed_source_kind: str | None = None,
) -> dict[str, Any]:
    fixed_value = _fixed_expr_value(numeric_expr)
    if fixed_value is not None:
        return {
            "ok": True,
            "value": float(fixed_value),
            "source_kind": fixed_source_kind or source_kind,
            "expr": numeric_expr,
            "source_trace": task.source.to_json(),
        }
    binding_sources = _numeric_binding_sources_from_task(task)
    if not binding_sources:
        return {
            "ok": False,
            "value": None,
            "source_kind": source_kind,
            "expr": numeric_expr,
            "blocked_reason": binding_missing_reason,
            "source_trace": task.source.to_json(),
        }
    result = RuleEvaluator().evaluate_numeric(
        numeric_expr,
        NumericEvaluationContext(
            binding_sources=binding_sources,
            source_trace=task.source.to_json(),
        ),
    )
    if result.ok and result.value is not None:
        return {
            "ok": True,
            "value": float(result.value),
            "source_kind": source_kind,
            "expr": numeric_expr,
            "bindings": result.bindings,
            "source_trace": result.source_trace,
        }
    return {
        "ok": False,
        "value": None,
        "source_kind": source_kind,
        "expr": numeric_expr,
        "bindings": result.bindings,
        "blocked_reason": result.blocked_reason or binding_missing_reason,
        "source_trace": result.source_trace,
    }


def _numeric_binding_sources_from_task(task: AbilityTaskIR) -> tuple[dict[str, Any], ...]:
    source_context = task.source.evidence.get("ability_source_context")
    if not isinstance(source_context, dict):
        return ()
    raw_sources = source_context.get("numeric_binding_sources")
    if not isinstance(raw_sources, list):
        return ()
    return tuple(source for source in raw_sources if isinstance(source, dict))


def _custom_value_binding_candidates_from_task(task: AbilityTaskIR) -> dict[str, Any]:
    source_context = task.source.evidence.get("ability_source_context")
    if not isinstance(source_context, dict):
        return {}
    candidates = source_context.get("custom_value_bindings")
    return dict(candidates) if isinstance(candidates, dict) else {}


def _summon_monster_id_unbound_reason(monster_expr: dict[str, Any], reason: str) -> str:
    source_field = str(monster_expr.get("source_field") or "")
    if source_field.endswith("MonsterIDFromCustomValue.Hash"):
        return f"summon_monster_id_from_custom_value_not_admitted:{reason}"
    if monster_expr.get("kind") == "dynamic_hash":
        return f"summon_monster_dynamic_monster_id_not_admitted:{reason}"
    if monster_expr.get("kind") == "postfix_expr":
        return f"summon_monster_monster_id_expr_not_admitted:{reason or 'postfix_expr'}"
    return reason or "summon_monster_fixed_monster_id_missing"


def _lower_assistant_ability_resolutions(
    queue_intents: list[QueueIntentIR],
    queue_resolutions: list[QueueResolutionIR],
) -> list[AssistantAbilityResolutionIR]:
    resolutions_by_intent = {resolution.queue_intent_id: resolution for resolution in queue_resolutions}
    assistant_resolutions: list[AssistantAbilityResolutionIR] = []
    for intent in sorted(queue_intents, key=lambda item: item.queue_intent_id):
        if intent.opcode != "TurnInsertAssistantAbility":
            continue
        resolution = resolutions_by_intent.get(intent.queue_intent_id)
        ability_id = ""
        value = _fixed_expr_value(intent.skill_index_expr)
        if value is not None:
            ability_id = str(int(value))
        blocked_reasons: list[str] = []
        if not ability_id:
            blocked_reasons.append("assistant_ability_id_missing_or_dynamic")
        if not intent.actor_target_alias:
            blocked_reasons.append("assistant_owner_alias_missing")
        if not intent.ability_target_alias:
            blocked_reasons.append("assistant_target_alias_missing")
        blocked_reasons.extend(
            (
                "assistant_actor_source_not_admitted",
                "assistant_stats_source_not_admitted",
                "assistant_action_graph_source_not_admitted",
            )
        )
        source = IRSource(
            source_path=intent.source.source_path,
            raw_type="AssistantAbilityResolution",
            raw_id=intent.queue_intent_id,
            evidence={
                "queue_intent": intent.to_json(),
                "queue_resolution": resolution.to_json() if resolution is not None else {},
                "admission_policy": "p1_3_assistant_requires_owner_target_graph_and_stats",
            },
        )
        assistant_resolutions.append(
            AssistantAbilityResolutionIR(
                assistant_resolution_id=f"assistant_ability_resolution:{intent.queue_intent_id}",
                queue_intent_id=intent.queue_intent_id,
                assistant_ability_id=ability_id,
                owner_alias=intent.actor_target_alias or "",
                target_alias=intent.ability_target_alias or "",
                resolved_graph_id="",
                attribution_policy={
                    "kind": "blocked",
                    "blocked_reason": "assistant_actor_source_not_admitted;assistant_stats_source_not_admitted;assistant_action_graph_source_not_admitted",
                    "actor_source": {
                        "coverage_status": "blocked",
                        "blocked_reason": "assistant_actor_source_not_admitted",
                    },
                    "stat_source": {
                        "coverage_status": "blocked",
                        "blocked_reason": "assistant_stats_source_not_admitted",
                    },
                    "action_graph_source": {
                        "coverage_status": "blocked",
                        "blocked_reason": "assistant_action_graph_source_not_admitted",
                        "assistant_ability_id": ability_id,
                    },
                    "source_queue_intent_id": intent.queue_intent_id,
                },
                source=source,
                coverage_status="blocked",
                blocked_reason=";".join(dict.fromkeys(blocked_reasons)),
            )
        )
    return assistant_resolutions


QUEUE_INTENT_OPCODES = {"TurnInsertAbility", "TurnInsertAction", "TurnInsertAssistantAbility"}
STATUS_CALLBACK_EFFECTLESS_OPCODES = QUEUE_INTENT_OPCODES | {
    "DamageByAttackProperty",
    "ModifyActionDelay",
    "SetActionDelay",
    "Retarget",
    "ModifyDamageData",
    "ModifyHealData",
    "ModifyCurrentSkillDelayCost",
    "Remodifier",
    "SetResilience",
    "SetDynamicValueByBehaviorFlagCount",
    "SetDynamicValueByChangeValue",
    "TriggerEffect",
    "AddBuffPerform",
}
SKILL_CONTINUATION_OPCODES = {"UseSkillOneMore"}
QUEUE_TARGET_ALIASES = {
    "Caster",
    "ModifierOwnerEntity",
    "ParamEntity",
    "CurrentActionTarget",
    "DamageAttackerEntity",
    "AbilityTargetEntity",
    "ModifierOwnerSkillTargetEntityList",
    "ParamEntitySkillTargetEntityList",
    "AllEnemy",
    "AllTeamMember",
    "AllLightTeam",
}


def _queue_intent_from_task(
    *,
    callback_id: str,
    task_id: str,
    event: str,
    opcode: str,
    task: dict[str, Any],
    source: IRSource,
    queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
) -> QueueIntentIR:
    queue_kind = {
        "TurnInsertAbility": "turn_insert_ability",
        "TurnInsertAction": "turn_insert_action",
        "TurnInsertAssistantAbility": "turn_insert_assistant_ability",
    }.get(opcode, "unknown")
    actor_target_alias = _queue_actor_target_alias(task, opcode)
    ability_target_alias = _queue_ability_target_alias(task, opcode)
    ability_name = _queue_action_ref_or_ability_name(task, opcode)
    skill_index_expr = _queue_skill_index_expr(task, opcode)
    priority_source = _queue_priority_source(task, opcode, queue_priority_lookup)
    abort_policy = _queue_abort_policy(task)
    coverage_status, blocked_reason = _queue_intent_admission(
        task=task,
        opcode=opcode,
        source=source,
        actor_target_alias=actor_target_alias,
        ability_target_alias=ability_target_alias,
        ability_name=ability_name,
        skill_index_expr=skill_index_expr,
        priority_source=priority_source,
        abort_policy=abort_policy,
    )
    return QueueIntentIR(
        queue_intent_id=f"queue_intent:{callback_id}:{task_id}",
        source_task_id=task_id,
        callback_id=callback_id,
        phase_id="",
        opcode=opcode,
        queue_kind=queue_kind,
        priority_source=priority_source,
        actor_target_alias=actor_target_alias,
        action_ref_or_ability_name=str(ability_name or ""),
        skill_index_expr=skill_index_expr,
        ability_target_alias=ability_target_alias,
        auto_cast=bool(task.get("AutoCast")) if isinstance(task.get("AutoCast"), bool) else False,
        abort_policy=abort_policy,
        source=source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _skill_continuation_from_task(task: AbilityTaskIR) -> SkillContinuationIR:
    raw_task = task.source.evidence.get("task") if isinstance(task.source.evidence, dict) else None
    task_payload = raw_task if isinstance(raw_task, dict) else {}
    skill_type = _value_field(task_payload.get("SkillType"))
    child_index = _numeric_expr_summary(task_payload.get("ChildSkillIndex"))
    child_index["source_field"] = "ChildSkillIndex"
    child_index["opcode"] = task.opcode
    return SkillContinuationIR(
        continuation_id=f"skill_continuation:{task.task_id}",
        source_task_id=task.task_id,
        phase_id=task.phase_id,
        action_id=task.action_id,
        level=task.level,
        ability_name=task.ability_name,
        opcode=task.opcode,
        continuation_kind="ultimate_or_skill_internal_sequence",
        fixed_skill_type=str(skill_type or ""),
        child_skill_index_expr=child_index,
        source=task.source,
        coverage_status="blocked",
        blocked_reason=(
            "skill_continuation_not_queue_extra_turn:"
            "requires source-specific continuation runner and fixed action segment admission"
        ),
    )


def _skill_continuations_from_ability_tasks(tasks: list[AbilityTaskIR]) -> list[SkillContinuationIR]:
    continuations: list[SkillContinuationIR] = []
    seen: set[str] = set()
    for task in tasks:
        if task.opcode not in SKILL_CONTINUATION_OPCODES:
            continue
        continuation = _skill_continuation_from_task(task)
        if continuation.continuation_id in seen:
            continue
        seen.add(continuation.continuation_id)
        continuations.append(continuation)
    return continuations


def _queue_skill_index_expr(task: dict[str, Any], opcode: str) -> dict[str, Any]:
    if opcode == "TurnInsertAction":
        if _queue_prepare_ability_name(task):
            return {
                "kind": "none",
                "value": None,
                "supported": True,
                "source_field": "PrepareAbilityName",
                "opcode": opcode,
                "action_selection": "route_or_source_selected_action",
            }
        skill_type = _queue_skill_type_action_selection(task)
        if skill_type:
            return {
                "kind": "skill_type",
                "value": skill_type["skill_type"],
                "supported": skill_type["skill_index"] is not None,
                "source_field": "SkillType",
                "opcode": opcode,
                "skill_index": skill_type["skill_index"],
                "action_kind": skill_type["action_kind"],
                "source_basis": skill_type["source_basis"],
            }
        expr = _numeric_expr_summary(task.get("SkillIndex"))
        expr["source_field"] = "SkillIndex"
        expr["opcode"] = opcode
        return expr
    if opcode == "TurnInsertAssistantAbility":
        expr = _numeric_expr_summary(task.get("AssistantAbilityID"))
        expr["source_field"] = "AssistantAbilityID"
        expr["opcode"] = opcode
        return expr
    return {"kind": "none", "value": None, "supported": True, "source_field": "", "opcode": opcode}


def _queue_priority_source(
    task: dict[str, Any],
    opcode: str,
    queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
) -> dict[str, Any]:
    key = {
        "TurnInsertAbility": "InsertAbilityPriority",
        "TurnInsertAction": "InsertActionPriority",
        "TurnInsertAssistantAbility": "InsertAbilityPriority",
    }.get(opcode, "InsertPriority")
    priority_table = "InsertActionPriority" if opcode == "TurnInsertAction" else "InsertAbilityPriority"
    priority_key = task.get(key)
    if priority_key is None and opcode == "TurnInsertAction" and (
        _queue_prepare_ability_name(task) or _queue_skill_type_action_selection(task)
    ):
        priority_key = "PROG_Default"
    priority = queue_priority_lookup.get((priority_table, str(priority_key))) if priority_key is not None else None
    if priority is not None:
        return {
            "field": key,
            "priority_table": priority_table,
            "priority_key": priority.priority_key,
            "priority_value": priority.priority_value,
            "queue_priority_id": priority.queue_priority_id,
            "priority_ordering_admitted": True,
            "source_trace": priority.source.to_json(),
        }
    return {
        "field": key,
        "priority_table": priority_table,
        "priority_key": str(priority_key or ""),
        "value": _json_safe(priority_key),
        "priority_ordering_admitted": False,
        "reason": f"queue_priority_key_not_admitted:{priority_table}:{priority_key or 'missing'}",
    }


def _queue_abort_policy(task: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "OnInsertAbort": _json_safe(task.get("OnInsertAbort")),
        "AbortBehaviorFlags": _json_safe(task.get("AbortBehaviorFlags")),
        "OwnerAliveState": _json_safe(task.get("OwnerAliveState")),
        "TargetAliveState": _json_safe(task.get("TargetAliveState")),
        "CanRunOnUnselectableTarget": _json_safe(task.get("CanRunOnUnselectableTarget")),
        "ShowInActionBar": _json_safe(task.get("ShowInActionBar")),
        "IgnoreBPDec": _json_safe(task.get("IgnoreBPDec")),
        "CustomTag": _json_safe(task.get("CustomTag")),
        "PreCheck": _json_safe(task.get("PreCheck")),
    }
    policy = {key: value for key, value in fields.items() if value not in (None, [], {})}
    if policy.get("IgnoreBPDec") is True:
        policy["resource_policy"] = {
            "ignore_skill_point_delta": True,
            "ignore_energy_gain": True,
            "source_field": "IgnoreBPDec",
            "source_basis": "tbgd_turn_insert_action_ignore_bp_dec",
        }
    insert_once_policy = _queue_insert_once_policy(task)
    if insert_once_policy:
        policy["insert_once_policy"] = insert_once_policy
    return policy


def _queue_prepare_ability_name(task: dict[str, Any]) -> str:
    value = _value_field(task.get("PrepareAbilityName"))
    return value if isinstance(value, str) and value else ""


def _queue_insert_once_policy(task: dict[str, Any]) -> dict[str, Any]:
    precheck = task.get("PreCheck")
    if not isinstance(precheck, dict):
        return {}
    if precheck.get("GMPGDEINODK") != "SameTagInsertUnusedCount":
        return {}
    max_count = _numeric_expr_summary(precheck.get("HOCMHABKLGJ"))
    custom_tag = _value_field(task.get("CustomTag"))
    used_modifiers: list[str] = []
    for abort_task in task.get("OnInsertAbort", ()) if isinstance(task.get("OnInsertAbort"), list) else ():
        if not isinstance(abort_task, dict):
            continue
        opcode = str(abort_task.get("$type") or "").rsplit(".", 1)[-1]
        if opcode != "AddModifier":
            continue
        modifier_name = _value_field(abort_task.get("ModifierName"))
        if isinstance(modifier_name, str) and modifier_name:
            used_modifiers.append(modifier_name)
    return {
        "kind": "same_tag_insert_unused_count",
        "max_count_expr": max_count,
        "custom_tag": custom_tag if isinstance(custom_tag, str) else "",
        "used_modifier_names": used_modifiers,
        "source_field": "PreCheck",
        "source_basis": "tbgd_turn_insert_action_same_tag_insert_unused_count",
    }


def _queue_skill_type_action_selection(task: dict[str, Any]) -> dict[str, Any] | None:
    value = _value_field(task.get("SkillType"))
    if not isinstance(value, str) or not value:
        return None
    normalized = value.lower()
    if normalized in {"normal", "controlskill01"}:
        return {
            "skill_type": value,
            "skill_index": 0,
            "action_kind": "basic",
            "source_basis": "tbgd_turn_insert_action_skill_type",
        }
    if normalized in {"skill", "controlskill02"}:
        return {
            "skill_type": value,
            "skill_index": 1,
            "action_kind": "skill",
            "source_basis": "tbgd_turn_insert_action_skill_type",
        }
    if normalized in {"ultra", "ultimate", "controlskill03"}:
        return {
            "skill_type": value,
            "skill_index": 2,
            "action_kind": "ultimate",
            "source_basis": "tbgd_turn_insert_action_skill_type",
        }
    return {
        "skill_type": value,
        "skill_index": None,
        "action_kind": "unknown",
        "source_basis": "tbgd_turn_insert_action_skill_type_not_admitted",
    }


def _queue_action_ref_or_ability_name(task: dict[str, Any], opcode: str) -> Any:
    if opcode == "TurnInsertAction":
        prepared = _queue_prepare_ability_name(task)
        if prepared:
            return prepared
        skill_type = _queue_skill_type_action_selection(task)
        if skill_type:
            return f"skill_type:{skill_type['skill_type']}"
    return _value_field(task.get("AbilityName"))


def _queue_actor_target_alias(task: dict[str, Any], opcode: str) -> str | None:
    alias = _target_alias(task.get("TargetType"))
    if alias:
        return alias
    if opcode == "TurnInsertAbility":
        return "ModifierOwnerEntity"
    if opcode == "TurnInsertAction" and (_queue_prepare_ability_name(task) or _queue_skill_type_action_selection(task)):
        return "ModifierOwnerEntity"
    return None


def _queue_ability_target_alias(task: dict[str, Any], opcode: str) -> str | None:
    alias = _target_alias(task.get("AbilityTarget")) or _target_alias(task.get("AutoCastTargetType"))
    if alias:
        return alias
    if opcode == "TurnInsertAction" and _queue_prepare_ability_name(task):
        return None
    return None


def _queue_intent_admission(
    *,
    task: dict[str, Any],
    opcode: str,
    source: IRSource,
    actor_target_alias: str | None,
    ability_target_alias: str | None,
    ability_name: Any,
    skill_index_expr: dict[str, Any],
    priority_source: dict[str, Any],
    abort_policy: dict[str, Any],
) -> tuple[str, str]:
    if not _queue_intent_source_admitted(source.source_path):
        return "blocked", "queue_intent_source_mode_not_admitted"
    if actor_target_alias not in QUEUE_TARGET_ALIASES:
        return "blocked", f"queue_actor_target_alias_not_admitted:{actor_target_alias or 'missing'}"
    if ability_target_alias and ability_target_alias not in QUEUE_TARGET_ALIASES:
        return "blocked", f"queue_ability_target_alias_not_admitted:{ability_target_alias}"
    if priority_source.get("priority_ordering_admitted") is not True:
        return "blocked", str(priority_source.get("reason") or "queue_priority_not_admitted")
    if abort_policy.get("OnInsertAbort"):
        if not (
            opcode == "TurnInsertAction"
            and (_queue_prepare_ability_name(task) or _queue_skill_type_action_selection(task))
        ):
            return "blocked", "queue_abort_policy_not_admitted"
    if opcode == "TurnInsertAbility":
        if not isinstance(ability_name, str) or not ability_name:
            return "blocked", "queue_insert_ability_name_missing"
        return "executable", ""
    if opcode == "TurnInsertAction":
        if _queue_prepare_ability_name(task):
            return "executable", ""
        if skill_index_expr.get("kind") == "skill_type":
            if isinstance(skill_index_expr.get("skill_index"), int):
                return "executable", ""
            return "blocked", f"queue_insert_action_skill_type_not_admitted:{skill_index_expr.get('value') or 'missing'}"
        if skill_index_expr.get("kind") != "fixed":
            return "blocked", f"queue_insert_action_skill_index_not_admitted:{skill_index_expr.get('kind') or 'missing'}"
        return "executable", ""
    if opcode == "TurnInsertAssistantAbility":
        return "blocked", "queue_insert_assistant_ability_not_admitted"
    return "blocked", f"queue_opcode_not_admitted:{opcode}"


def _queue_intent_source_admitted(relative_path: str) -> bool:
    if not _queue_source_candidate(relative_path):
        return False
    return not _queue_source_blocked(relative_path)


def _standalone_ability_source_admitted(relative_path: str) -> bool:
    return relative_path.startswith("Config/ConfigAbility/") and _queue_source_candidate(relative_path) and not _queue_source_blocked(relative_path)


def _standalone_ability_source_mode(relative_path: str) -> str:
    if relative_path.startswith("Config/ConfigAbility/Avatar/"):
        return "mainline_avatar"
    if relative_path.startswith("Config/ConfigAbility/Monster/"):
        return "mainline_monster"
    if relative_path.startswith("Config/ConfigAbility/BattleEventAbility"):
        return "mainline_battle_event"
    if relative_path.endswith("Config/ConfigAbility/Common_Additional_Ability.json"):
        return "mainline_common_additional"
    return "blocked_or_unknown"


def _queue_source_candidate(relative_path: str) -> bool:
    return (
        relative_path.startswith("Config/ConfigGlobalModifier/")
        or relative_path.startswith("Config/ConfigAbility/Avatar/")
        or relative_path.startswith("Config/ConfigAbility/Monster/")
        or relative_path.startswith("Config/ConfigAbility/BattleEventAbility")
        or relative_path == "Config/ConfigAbility/Common_Additional_Ability.json"
    )


def _queue_source_blocked(relative_path: str) -> bool:
    blocked_markers = ("Rogue", "Activity", "GridFight", "ElationBattle", "Fate", "Story", "Level/", "SubLevelGraph", "Chess")
    return any(marker in relative_path for marker in blocked_markers)


def _lower_queue_resolutions(
    *,
    queue_intents: list[QueueIntentIR],
    action_bindings: list[ActionAbilityBindingIR],
    ability_phases: list[AbilityPhaseIR],
    standalone_graphs: list[StandaloneAbilityGraphIR],
    combatant_action_sets: list[CombatantActionSetIR],
) -> list[QueueResolutionIR]:
    phases_by_ability: dict[str, list[AbilityPhaseIR]] = {}
    for phase in ability_phases:
        phases_by_ability.setdefault(phase.ability_name, []).append(phase)
    bindings_by_action: dict[tuple[str, int], ActionAbilityBindingIR] = {
        (binding.action_id, binding.level): binding for binding in action_bindings
    }
    standalone_by_ability: dict[str, list[StandaloneAbilityGraphIR]] = {}
    for graph in standalone_graphs:
        standalone_by_ability.setdefault(graph.ability_name, []).append(graph)
    resolutions: list[QueueResolutionIR] = []
    for intent in queue_intents:
        resolutions.append(
            _queue_resolution_from_intent(
                intent,
                phases_by_ability=phases_by_ability,
                bindings_by_action=bindings_by_action,
                standalone_by_ability=standalone_by_ability,
                combatant_action_sets=combatant_action_sets,
            )
        )
    return resolutions


def _queue_resolution_from_intent(
    intent: QueueIntentIR,
    *,
    phases_by_ability: dict[str, list[AbilityPhaseIR]],
    bindings_by_action: dict[tuple[str, int], ActionAbilityBindingIR],
    standalone_by_ability: dict[str, list[StandaloneAbilityGraphIR]],
    combatant_action_sets: list[CombatantActionSetIR],
) -> QueueResolutionIR:
    source = IRSource(
        source_path=intent.source.source_path,
        raw_type="QueueResolution",
        raw_id=intent.queue_intent_id,
        evidence={
            "queue_intent_id": intent.queue_intent_id,
            "queue_intent_source": intent.source.to_json(),
            "opcode": intent.opcode,
            "queue_kind": intent.queue_kind,
        },
    )
    resolution_id = f"queue_resolution:{intent.queue_intent_id}"
    if intent.coverage_status != "executable":
        reason = intent.blocked_reason or f"queue_intent_not_executable:{intent.coverage_status}"
        return QueueResolutionIR(
            queue_resolution_id=resolution_id,
            queue_intent_id=intent.queue_intent_id,
            action_or_ability_ref=intent.action_ref_or_ability_name,
            resolved_kind="blocked_intent",
            resolved_ids={},
            source=source,
            coverage_status="blocked",
            blocked_reason=f"queue_intent_not_executable:{reason}",
        )
    if intent.opcode == "TurnInsertAbility":
        ability_name = intent.action_ref_or_ability_name
        if not ability_name:
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=ability_name,
                resolved_kind="missing_ability_name",
                resolved_ids={},
                source=source,
                coverage_status="blocked",
                blocked_reason="queue_ability_name_missing",
            )
        graph_candidates = tuple(sorted(standalone_by_ability.get(ability_name, ()), key=lambda item: item.standalone_ability_graph_id))
        same_source_graphs = tuple(graph for graph in graph_candidates if graph.source.source_path == intent.source.source_path)
        selected_graphs = same_source_graphs or graph_candidates
        if len(selected_graphs) > 1:
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=ability_name,
                resolved_kind="ambiguous_standalone_ability_graph",
                resolved_ids={
                    "candidate_graph_ids": [graph.standalone_ability_graph_id for graph in selected_graphs],
                    "candidate_source_paths": [graph.source.source_path for graph in selected_graphs],
                },
                source=source,
                coverage_status="blocked",
                blocked_reason=f"queue_ability_graph_ambiguous:{ability_name}",
            )
        if len(selected_graphs) == 1:
            graph = selected_graphs[0]
            if graph.coverage_status != "executable":
                return QueueResolutionIR(
                    queue_resolution_id=resolution_id,
                    queue_intent_id=intent.queue_intent_id,
                    action_or_ability_ref=ability_name,
                    resolved_kind="standalone_ability_graph_blocked",
                    resolved_ids={"standalone_ability_graph_id": graph.standalone_ability_graph_id},
                    source=source,
                    coverage_status="blocked",
                    blocked_reason=graph.blocked_reason or f"standalone_ability_graph_not_executable:{graph.coverage_status}",
                )
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=ability_name,
                resolved_kind="standalone_ability_graph",
                resolved_ids={
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                    "phase_ids": list(graph.phase_ids),
                    "task_ids": list(graph.task_ids),
                    "executable_task_ids": list(graph.executable_task_ids),
                    "source_mode": graph.source_mode,
                },
                source=source,
                coverage_status="executable",
                blocked_reason="",
            )
        phases = tuple(sorted(phases_by_ability.get(ability_name, ()), key=lambda item: item.phase_id))
        if not phases:
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=ability_name,
                resolved_kind="unresolved_ability_name",
                resolved_ids={},
                source=source,
                coverage_status="blocked",
                blocked_reason=f"queue_ability_graph_not_lowered_or_missing:{ability_name}",
            )
        action_keys = tuple(sorted({(phase.action_id, phase.level) for phase in phases}))
        binding_ids = tuple(
            binding.binding_id
            for key in action_keys
            for binding in (bindings_by_action.get(key),)
            if binding is not None
        )
        return QueueResolutionIR(
            queue_resolution_id=resolution_id,
            queue_intent_id=intent.queue_intent_id,
            action_or_ability_ref=ability_name,
            resolved_kind="ability_phase_graph",
            resolved_ids={
                "phase_ids": [phase.phase_id for phase in phases],
                "task_ids": [task_id for phase in phases for task_id in phase.task_ids],
                "action_keys": [f"{action_id}:{level}" for action_id, level in action_keys],
                "binding_ids": list(binding_ids),
            },
            source=source,
            coverage_status="executable",
            blocked_reason="",
        )
    if intent.opcode == "TurnInsertAction":
        if intent.action_ref_or_ability_name and intent.skill_index_expr.get("source_field") == "PrepareAbilityName":
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=intent.action_ref_or_ability_name,
                resolved_kind="extra_turn_action_choice",
                resolved_ids={
                    "prepare_ability_name": intent.action_ref_or_ability_name,
                    "action_selection": "route_or_source_selected_action",
                    "skill_index_expr": _json_safe(intent.skill_index_expr),
                },
                source=source,
                coverage_status="executable",
                blocked_reason="",
            )
        if intent.skill_index_expr.get("kind") == "skill_type":
            skill_index = intent.skill_index_expr.get("skill_index")
            if not isinstance(skill_index, int):
                reason = f"queue_insert_action_skill_type_not_admitted:{intent.skill_index_expr.get('value') or 'missing'}"
                return QueueResolutionIR(
                    queue_resolution_id=resolution_id,
                    queue_intent_id=intent.queue_intent_id,
                    action_or_ability_ref=intent.action_ref_or_ability_name,
                    resolved_kind="insert_action_not_admitted",
                    resolved_ids={"skill_index_expr": _json_safe(intent.skill_index_expr)},
                    source=source,
                    coverage_status="blocked",
                    blocked_reason=reason,
                )
            return _queue_action_definition_resolution(
                intent,
                source,
                resolution_id,
                str(skill_index),
                combatant_action_sets,
            )
        if intent.skill_index_expr.get("kind") != "fixed":
            reason = f"queue_insert_action_skill_index_not_admitted:{intent.skill_index_expr.get('kind') or 'missing'}"
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=intent.action_ref_or_ability_name,
                resolved_kind="insert_action_not_admitted",
                resolved_ids={"skill_index_expr": _json_safe(intent.skill_index_expr)},
                source=source,
                coverage_status="blocked",
                blocked_reason=reason,
            )
        skill_index_value = intent.skill_index_expr.get("value")
        if not isinstance(skill_index_value, (int, float)):
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=intent.action_ref_or_ability_name,
                resolved_kind="insert_action_not_admitted",
                resolved_ids={"skill_index_expr": _json_safe(intent.skill_index_expr)},
                source=source,
                coverage_status="blocked",
                blocked_reason="queue_insert_action_skill_index_value_missing",
            )
        skill_index_key = str(int(skill_index_value))
        return _queue_action_definition_resolution(
            intent,
            source,
            resolution_id,
            skill_index_key,
            combatant_action_sets,
        )
    if intent.opcode == "TurnInsertAssistantAbility":
        return QueueResolutionIR(
            queue_resolution_id=resolution_id,
            queue_intent_id=intent.queue_intent_id,
            action_or_ability_ref=intent.action_ref_or_ability_name,
            resolved_kind="assistant_ability_not_admitted",
            resolved_ids={"assistant_ability_expr": _json_safe(intent.skill_index_expr)},
            source=source,
            coverage_status="blocked",
            blocked_reason="queue_insert_assistant_ability_not_admitted",
        )
    return QueueResolutionIR(
        queue_resolution_id=resolution_id,
        queue_intent_id=intent.queue_intent_id,
        action_or_ability_ref=intent.action_ref_or_ability_name,
        resolved_kind="queue_opcode_not_admitted",
        resolved_ids={},
        source=source,
        coverage_status="blocked",
        blocked_reason=f"queue_opcode_not_admitted:{intent.opcode}",
    )


def _queue_action_definition_resolution(
    intent: QueueIntentIR,
    source: IRSource,
    resolution_id: str,
    skill_index_key: str,
    combatant_action_sets: list[CombatantActionSetIR],
) -> QueueResolutionIR:
    candidates: list[dict[str, Any]] = []
    for action_set in sorted(combatant_action_sets, key=lambda item: item.combatant_action_set_id):
        if action_set.coverage_status != "executable":
            continue
        entry = action_set.skill_index_map.get(skill_index_key)
        if not isinstance(entry, dict) or entry.get("coverage_status") != "executable":
            continue
        action_ref = entry.get("action_ref")
        default_level = entry.get("default_level")
        if not isinstance(action_ref, str) or not isinstance(default_level, int):
            continue
        candidates.append(
            {
                "combatant_action_set_id": action_set.combatant_action_set_id,
                "entity_ref": action_set.entity_ref,
                "skill_index": skill_index_key,
                "action_ref": action_ref,
                "action_level": default_level,
                "skill_id": entry.get("skill_id"),
                "source": action_set.source.to_json(),
            }
        )
    action_set_count = sum(1 for action_set in combatant_action_sets if action_set.coverage_status == "executable")
    if not candidates:
        return QueueResolutionIR(
            queue_resolution_id=resolution_id,
            queue_intent_id=intent.queue_intent_id,
            action_or_ability_ref=f"skill_index:{skill_index_key}",
            resolved_kind="insert_action_not_admitted",
            resolved_ids={
                "skill_index_expr": _json_safe(intent.skill_index_expr),
                "skill_index": skill_index_key,
                "executable_action_set_count": action_set_count,
            },
            source=source,
            coverage_status="blocked",
            blocked_reason=f"queue_insert_action_no_action_set_candidate:{skill_index_key}",
        )
    return QueueResolutionIR(
        queue_resolution_id=resolution_id,
        queue_intent_id=intent.queue_intent_id,
        action_or_ability_ref=f"skill_index:{skill_index_key}",
        resolved_kind="action_definition",
        resolved_ids={
            "skill_index_expr": _json_safe(intent.skill_index_expr),
            "skill_index": skill_index_key,
            "action_set_candidates": candidates,
            "executable_action_set_count": action_set_count,
        },
        source=source,
        coverage_status="executable",
        blocked_reason="",
    )


def _lower_queue_windows(
    queue_intents: list[QueueIntentIR],
    queue_resolutions: list[QueueResolutionIR],
    extra_turn_source_basis: dict[str, Any],
) -> list[QueueWindowIR]:
    resolutions_by_intent = {resolution.queue_intent_id: resolution for resolution in queue_resolutions}
    return [
        _queue_window_from_intent(intent, resolutions_by_intent.get(intent.queue_intent_id), extra_turn_source_basis)
        for intent in queue_intents
    ]


def _lower_queue_lifecycle_policies(
    queue_windows: list[QueueWindowIR],
    extra_turn_source_basis: dict[str, Any],
) -> list[QueueLifecyclePolicyIR]:
    policies: list[QueueLifecyclePolicyIR] = []
    source_evidence = extra_turn_source_basis.get("evidence") if isinstance(extra_turn_source_basis.get("evidence"), dict) else {}
    source_policy = extra_turn_source_basis.get("lifecycle_policy") if isinstance(extra_turn_source_basis.get("lifecycle_policy"), dict) else {}
    one_more_source = _first_source_from_extra_turn_basis(extra_turn_source_basis)
    policies.append(
        QueueLifecyclePolicyIR(
            queue_lifecycle_policy_id="queue_lifecycle_policy:extra_turn_source:OneMore",
            queue_window_id="",
            queue_intent_id="",
            window_family="extra_turn",
            lifecycle_policy=_json_safe(source_policy) if source_policy else {},
            source_basis=_json_safe(extra_turn_source_basis),
            source=one_more_source,
            coverage_status="discovered_only"
            if extra_turn_source_basis.get("source_basis_status") == "lifecycle_source_admitted"
            else "blocked",
            blocked_reason=""
            if extra_turn_source_basis.get("source_basis_status") == "lifecycle_source_admitted"
            else str(extra_turn_source_basis.get("blocking_dependency") or "extra_turn_lifecycle_source_missing"),
        )
    )
    for window in queue_windows:
        if window.window_family != "extra_turn":
            continue
        window_policy = window.window_policy if isinstance(window.window_policy, dict) else {}
        policy_id = str(window_policy.get("queue_lifecycle_policy_id") or f"queue_lifecycle_policy:queue_window:{window.queue_intent_id}")
        admitted = window.coverage_status == "executable" and window_policy.get("lifecycle_policy_admitted") is True
        lifecycle_policy = _json_safe(source_policy) if source_policy else {}
        if isinstance(lifecycle_policy, dict):
            lifecycle_policy = {
                **lifecycle_policy,
                "queue_window_id": window.queue_window_id,
                "queue_intent_id": window.queue_intent_id,
                "window_family": window.window_family,
                "window_policy": window_policy,
            }
        blocked_reason = ""
        if not admitted:
            blocked_reason = (
                window.blocked_reason
                or str(window_policy.get("blocking_dependency") or "")
                or "extra_turn_window_or_lifecycle_not_admitted"
            )
        policies.append(
            QueueLifecyclePolicyIR(
                queue_lifecycle_policy_id=policy_id,
                queue_window_id=window.queue_window_id,
                queue_intent_id=window.queue_intent_id,
                window_family=window.window_family,
                lifecycle_policy=lifecycle_policy if isinstance(lifecycle_policy, dict) else {},
                source_basis={
                    "extra_turn_source_basis": _json_safe(extra_turn_source_basis),
                    "queue_window_source": window.source.to_json(),
                    "source_evidence_keys": sorted(str(key) for key in source_evidence),
                },
                source=IRSource(
                    source_path=window.source.source_path,
                    raw_type="QueueLifecyclePolicy",
                    raw_id=policy_id,
                    evidence={
                        "queue_window_id": window.queue_window_id,
                        "queue_intent_id": window.queue_intent_id,
                        "queue_window_source": window.source.to_json(),
                        "extra_turn_source_basis": _json_safe(extra_turn_source_basis),
                    },
                ),
                coverage_status="executable" if admitted else "blocked",
                blocked_reason=blocked_reason,
            )
        )
    return policies


def _lower_extra_action_policies(
    *,
    queue_intents: list[QueueIntentIR],
    queue_windows: list[QueueWindowIR],
    queue_lifecycle_policies: list[QueueLifecyclePolicyIR],
    skill_continuations: list[SkillContinuationIR],
    extra_turn_source_basis: dict[str, Any],
) -> list[ExtraActionPolicyIR]:
    policies: list[ExtraActionPolicyIR] = []
    lifecycle_by_window = {policy.queue_window_id: policy for policy in queue_lifecycle_policies if policy.queue_window_id}
    intent_by_id = {intent.queue_intent_id: intent for intent in queue_intents}
    for window in queue_windows:
        if window.window_family != "extra_turn":
            continue
        intent = intent_by_id.get(window.queue_intent_id)
        lifecycle = lifecycle_by_window.get(window.queue_window_id)
        lifecycle_ok = lifecycle is not None and lifecycle.coverage_status == "executable"
        window_ok = window.coverage_status == "executable"
        policy_id = f"extra_action_policy:queue_window:{window.queue_intent_id}"
        source_basis = {
            "queue_window_source": window.source.to_json(),
            "queue_intent_source": intent.source.to_json() if intent is not None else {},
            "queue_lifecycle_policy": lifecycle.to_json() if lifecycle is not None else {},
            "extra_turn_source_basis": _json_safe(extra_turn_source_basis),
        }
        blocked_reason = ""
        if not window_ok:
            blocked_reason = window.blocked_reason or f"queue_window_not_executable:{window.coverage_status}"
        elif not lifecycle_ok:
            blocked_reason = "extra_turn_lifecycle_policy_not_admitted"
        policies.append(
            ExtraActionPolicyIR(
                extra_action_policy_id=policy_id,
                queue_intent_id=window.queue_intent_id,
                queue_window_id=window.queue_window_id,
                source_kind="true_extra_turn",
                action_selection_kind="route_or_source_selected_action",
                allowed_action_kinds=("basic", "skill", "ultimate"),
                fixed_action_ref="",
                lifecycle_policy_id=lifecycle.queue_lifecycle_policy_id if lifecycle is not None else "",
                source_basis=source_basis,
                source=IRSource(
                    source_path=window.source.source_path,
                    raw_type="ExtraActionPolicy",
                    raw_id=policy_id,
                    evidence=source_basis,
                ),
                coverage_status="executable" if window_ok and lifecycle_ok else "blocked",
                blocked_reason=blocked_reason,
            )
        )
    for continuation in skill_continuations:
        policy_id = f"extra_action_policy:skill_continuation:{continuation.continuation_id}"
        source_basis = {
            "skill_continuation": continuation.to_json(),
            "reason": "UseSkillOneMore is a skill or ultimate internal continuation, not a true extra turn",
        }
        policies.append(
            ExtraActionPolicyIR(
                extra_action_policy_id=policy_id,
                queue_intent_id="",
                queue_window_id="",
                source_kind="skill_or_ultimate_internal_continuation",
                action_selection_kind="fixed_internal_segment",
                allowed_action_kinds=(),
                fixed_action_ref=continuation.fixed_skill_type,
                lifecycle_policy_id="",
                source_basis=source_basis,
                source=IRSource(
                    source_path=continuation.source.source_path,
                    raw_type="SkillContinuationPolicy",
                    raw_id=policy_id,
                    evidence=source_basis,
                ),
                coverage_status="blocked",
                blocked_reason=(
                    "skill_continuation_runner_not_admitted:"
                    "requires source-specific mapping from continuation segment to executable action or ability"
                ),
            )
        )
    return policies


def _first_source_from_extra_turn_basis(extra_turn_source_basis: dict[str, Any]) -> IRSource:
    evidence = extra_turn_source_basis.get("evidence") if isinstance(extra_turn_source_basis.get("evidence"), dict) else {}
    modifier = evidence.get("one_more_modifier") if isinstance(evidence.get("one_more_modifier"), dict) else {}
    source = modifier.get("source") if isinstance(modifier.get("source"), dict) else None
    if isinstance(source, dict):
        return IRSource(
            source_path=str(source.get("source_path") or "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"),
            raw_type=str(source.get("raw_type") or "ConfigGlobalModifier"),
            raw_id=str(source.get("raw_id") or "OneMore"),
            evidence=_json_safe(source.get("evidence") or {}),
        )
    return IRSource(
        source_path="Config/GlobalConfig/JsonEnumDefineConfig.json",
        raw_type="ExtraTurnSourceDiscovery",
        raw_id="OneMore",
        evidence=_json_safe(extra_turn_source_basis),
    )


def _queue_window_from_intent(
    intent: QueueIntentIR,
    resolution: QueueResolutionIR | None,
    extra_turn_source_basis: dict[str, Any],
) -> QueueWindowIR:
    family, basis = _queue_window_family(intent)
    policy = _queue_window_policy(intent, resolution, family, basis, extra_turn_source_basis)
    source = IRSource(
        source_path=intent.source.source_path,
        raw_type="QueueWindow",
        raw_id=intent.queue_intent_id,
        evidence={
            "queue_intent_id": intent.queue_intent_id,
            "queue_intent_source": intent.source.to_json(),
            "queue_kind": intent.queue_kind,
            "opcode": intent.opcode,
            "priority_source": _json_safe(intent.priority_source),
            "family_basis": basis,
            "resolution": resolution.to_json() if resolution is not None else {},
        },
    )
    if intent.coverage_status != "executable":
        status = "blocked"
        reason = intent.blocked_reason or f"queue_intent_not_executable:{intent.coverage_status}"
    elif resolution is None:
        status = "blocked"
        reason = "queue_resolution_missing_for_window"
    elif resolution.coverage_status != "executable":
        status = "blocked"
        reason = resolution.blocked_reason or f"queue_resolution_not_executable:{resolution.coverage_status}"
    elif not policy.get("priority_ordering_admitted"):
        status = "blocked"
        reason = str(policy.get("blocking_dependency") or "queue_window_ordering_not_admitted")
    elif policy.get("lifecycle_policy_admitted") is False:
        status = "blocked"
        reason = str(policy.get("blocking_dependency") or "queue_window_lifecycle_policy_not_admitted")
    elif family in {"assistant", "unknown"}:
        status = "blocked"
        reason = f"queue_window_family_not_admitted:{family}"
    else:
        status = "executable"
        reason = ""
    return QueueWindowIR(
        queue_window_id=f"queue_window:{intent.queue_intent_id}",
        queue_intent_id=intent.queue_intent_id,
        queue_kind=intent.queue_kind,
        window_family=family,
        priority_key=str(intent.priority_source.get("priority_key") or ""),
        priority_value=_json_float(intent.priority_source.get("priority_value")),
        window_policy=policy,
        source=source,
        coverage_status=status,
        blocked_reason=reason,
    )


def _queue_window_family(intent: QueueIntentIR) -> tuple[str, dict[str, Any]]:
    priority_key = str(intent.priority_source.get("priority_key") or "")
    ref = intent.action_ref_or_ability_name
    text = " ".join(
        (
            intent.opcode,
            intent.queue_kind,
            priority_key,
            ref,
            intent.source.source_path,
            str(intent.source.raw_id),
        )
    )
    lowered = text.lower()
    text_hints = _queue_window_text_hints(lowered)
    basis = {
        "opcode": intent.opcode,
        "queue_kind": intent.queue_kind,
        "priority_key": priority_key,
        "action_or_ability_ref": ref,
        "source_path": intent.source.source_path,
        "text_hints": text_hints,
        "text_hint_status": "discovered_only" if text_hints else "",
    }
    if intent.opcode == "TurnInsertAssistantAbility":
        return "assistant", basis
    if intent.queue_kind == "extra_turn":
        return "extra_turn", {
            **basis,
            "extra_turn_basis_status": "discovered_only",
            "source_basis": "structured_extra_turn_source_task",
            "blocking_dependency": (
                intent.blocked_reason
                or "extra_turn_source_task_not_admitted_without_priority_target_action_resolution"
            ),
        }
    if intent.queue_kind == "turn_insert_action" and intent.skill_index_expr.get("source_field") == "PrepareAbilityName":
        return "extra_turn", {
            **basis,
            "extra_turn_basis_status": "admitted",
            "source_basis": "structured_turn_insert_action_prepare_ability",
            "prepare_ability_name": intent.action_ref_or_ability_name,
            "action_selection_policy": "route_or_source_selected_action",
        }
    if intent.queue_kind == "turn_insert_action":
        return "insert_action", basis
    if intent.queue_kind == "turn_insert_ability":
        return "insert_ability", basis
    if text_hints:
        return "unknown", {
            **basis,
            "source_basis": "text_only_queue_window_hint",
            "blocking_dependency": "queue_window_text_hint_not_admitted_without_structured_source",
        }
    return "unknown", basis


def _queue_window_text_hints(lowered_text: str) -> list[str]:
    hints: list[str] = []
    if any(token in lowered_text for token in ("counter", "反击")):
        hints.append("counter")
    if any(token in lowered_text for token in ("follow", "followup", "follow_up", "追加", "追击")):
        hints.append("follow_up")
    if any(token in lowered_text for token in ("onemore", "one_more", "extra_turn", "extraturn", "additionalturn")):
        hints.append("extra_turn")
    if any(token in lowered_text for token in ("ultra", "ultimate", "ultimateskill")):
        hints.append("ultimate")
    if "interrupt" in lowered_text:
        hints.append("interrupt")
    if "immediate" in lowered_text:
        hints.append("immediate")
    return hints


def _queue_window_policy(
    intent: QueueIntentIR,
    resolution: QueueResolutionIR | None,
    family: str,
    basis: dict[str, Any],
    extra_turn_source_basis: dict[str, Any],
) -> dict[str, Any]:
    priority_value = _json_float(intent.priority_source.get("priority_value"))
    ordering_admitted = intent.priority_source.get("priority_ordering_admitted") is True and priority_value is not None
    policy: dict[str, Any] = {
        "window_family": family,
        "source_basis": basis,
        "text_hints": _json_safe(basis.get("text_hints") or []),
        "text_hint_status": str(basis.get("text_hint_status") or ""),
        "priority_ordering_admitted": ordering_admitted,
        "priority_value": priority_value,
        "dequeue_before_execute": True,
        "drain_via_scheduler": True,
        "reentrant_drain_allowed": False,
    }
    if not ordering_admitted:
        policy["blocking_dependency"] = str(intent.priority_source.get("reason") or "queue_priority_not_admitted")
    if resolution is None:
        policy["blocking_dependency"] = "queue_resolution_missing_for_window"
    elif resolution.coverage_status != "executable":
        policy["blocking_dependency"] = resolution.blocked_reason or f"queue_resolution_not_executable:{resolution.coverage_status}"
    if family == "extra_turn":
        lifecycle_admitted = (
            basis.get("extra_turn_basis_status") == "admitted"
            and extra_turn_source_basis.get("source_basis_status") == "lifecycle_source_admitted"
        )
        lifecycle_policy_id = f"queue_lifecycle_policy:queue_window:{intent.queue_intent_id}"
        policy.update(
            {
                "natural_av_advance": "bypassed_for_queue_child",
                "queue_lifecycle_policy_id": lifecycle_policy_id,
                "extra_action_policy_id": f"extra_action_policy:queue_window:{intent.queue_intent_id}",
                "lifecycle_policy_admitted": lifecycle_admitted,
                "turn_lifecycle_policy": "admitted_from_queue_lifecycle_policy" if lifecycle_admitted else "blocked_until_extra_turn_lifecycle_source_admitted",
                "duration_tick_policy": "ActionPhaseEnd_from_OneMore_LifeStepMoment" if lifecycle_admitted else "blocked_until_extra_turn_lifecycle_source_admitted",
                "action_selection_policy": "source_or_route_selected_action_required",
                "action_selection_admitted": lifecycle_admitted and resolution is not None and resolution.coverage_status == "executable",
                "extra_turn_source_basis": _json_safe(extra_turn_source_basis),
            }
        )
        if not lifecycle_admitted:
            policy["blocking_dependency"] = (
                str(basis.get("blocking_dependency") or "")
                or str(extra_turn_source_basis.get("blocking_dependency") or "")
                or "extra_turn_lifecycle_source_not_admitted"
            )
    elif family == "ultimate":
        policy.update(
            {
                "interrupts_current_action": "not_admitted",
                "energy_cost_policy": "manual_preflight_only_until_ultimate_cost_source_admitted",
            }
        )
    elif family in {"follow_up", "counter"}:
        policy.update({"attack_semantics": "queue_window_only_not_damage_family"})
    elif family == "assistant":
        policy["blocking_dependency"] = "assistant_actor_resolution_not_admitted"
    elif family == "unknown":
        policy["blocking_dependency"] = "queue_window_family_unknown"
    return policy


def _effect_blocked_reason(opcode: str, payload: dict[str, Any], coverage_status: str) -> str:
    standard = payload.get("standard")
    if isinstance(standard, dict) and standard.get("blocked_reason"):
        return str(standard["blocked_reason"])
    if coverage_status == "blocked":
        if not isinstance(standard, dict):
            return f"effect_payload_not_standardized:{opcode}"
        target_expression_reason = standard.get("target_expression_blocked_reason")
        if isinstance(target_expression_reason, str) and target_expression_reason:
            return target_expression_reason
        target_alias = standard.get("target_alias")
        if target_alias is not None and target_alias not in EXECUTABLE_TARGET_ALIASES | ADD_MODIFIER_TARGET_ALIASES | STATUS_CALLBACK_LIST_TARGET_ALIASES:
            return f"unsupported_target_alias:{target_alias}"
        return f"effect_not_executable:{opcode}"
    return f"effect_coverage_status:{coverage_status}:{opcode}"


def _condition_payload_executable(opcode: str, payload: dict[str, Any]) -> bool:
    if opcode not in EXECUTABLE_CONDITION_OPCODES:
        return False
    if opcode == "AlwaysTrue":
        return True
    condition_aliases = (
        EXECUTABLE_TARGET_ALIASES
        | ADD_MODIFIER_TARGET_ALIASES
        | STATUS_CALLBACK_LIST_TARGET_ALIASES
    )
    if opcode in {
        "ByCheckModifierCallBackIsSelf",
        "ByIsTurnOwnerEntity",
        "ByIsTeammate",
        "ByTargetAliveState",
    }:
        if opcode == "ByCheckModifierCallBackIsSelf":
            return True
        if not _condition_target_value_executable(payload.get("TargetType")):
            return False
        if opcode == "ByTargetAliveState":
            return payload.get("AliveStateMask") == "Mask_AliveOrRevivable"
        return True
    if opcode == "ByCharacterDamageType":
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and isinstance(payload.get("DamageType"), str)
            and bool(payload.get("DamageType"))
        )
    if opcode in {"ByCompareChangeValue", "ByCompareParamValue", "ByCompareWaveCount"}:
        return (
            isinstance(payload.get("CompareType"), str)
            and _numeric_expr_can_be_runtime_bound(payload.get("CompareValue"))
        )
    if opcode == "ByCompareSPRatio":
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and isinstance(payload.get("CompareType"), str)
            and _numeric_expr_can_be_runtime_bound(payload.get("CompareValue"))
        )
    if opcode == "ByHasStanceWeak":
        weak_type = payload.get("WeakType")
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and isinstance(weak_type, dict)
            and isinstance(weak_type.get("DamageType"), str)
        )
    if opcode in {"ByInTurnBasedGameModeState", "ByIsDamageCritical"}:
        return True
    if opcode == "ByIsPropertyValueMinOrMax":
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and _condition_target_value_executable(payload.get("CompareTargetType"))
            and payload.get("PropertyRatioType") == "HPRatio"
        )
    if opcode == "ByIsTargetValid":
        return _condition_target_value_executable(payload.get("TargetType"))
    if opcode == "ByIsTopActionDelayTarget":
        exclude = payload.get("ExcludeTargetType")
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and _condition_target_value_executable(payload.get("CompareTargetType"))
            and (
                exclude is None
                or _condition_target_value_executable(exclude)
            )
        )
    if opcode == "ByRandomChance":
        return _numeric_expr_can_be_runtime_bound(payload.get("Chance"))
    if opcode in {
        "ByCheckModifierCallBackName",
        "ByCheckModifierCallBackStatusType",
        "ByCompareCurrentModifierStatusType",
        "ByCurrentSkillName",
    }:
        key = {
            "ByCheckModifierCallBackName": "ModifierName",
            "ByCheckModifierCallBackStatusType": "TargetStatusType",
            "ByCompareCurrentModifierStatusType": "TargetStatusType",
            "ByCurrentSkillName": "SkillName",
        }[opcode]
        return isinstance(_value_field(payload.get(key)), str)
    if opcode == "ByCheckModifierCallBackBehaviorFlag":
        target = payload.get("TargetType")
        return (
            (target is None or _condition_target_value_executable(target))
            and isinstance(payload.get("Flag"), str)
        )
    if opcode == "ByCompareAbilityProperty":
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and ability_property_is_runtime_readable(payload.get("Property"))
            and _numeric_expr_can_be_runtime_bound(payload.get("CompareValue"))
        )
    if opcode == "ByCompareCharacterID":
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and _numeric_expr_can_be_runtime_bound(payload.get("TargetCharacterID"))
        )
    if opcode == "ByCompareTargetCount":
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and _numeric_expr_can_be_runtime_bound(payload.get("Number"))
            and ("AliveOnly" not in payload or isinstance(payload.get("AliveOnly"), bool))
        )
    if opcode == "ByStatusCount":
        return (
            _target_alias(payload.get("TargetType")) in condition_aliases
            and _numeric_expr_can_be_runtime_bound(payload.get("CompareValue"))
        )
    if opcode == "ByCurrentSkillType":
        value = payload.get("SkillType")
        return isinstance(value, str) and bool(value)
    if opcode == "ByAttackType":
        return isinstance(payload.get("AttackTypes"), list)
    if opcode == "ByTargetTeam":
        return _condition_target_value_executable(payload.get("TargetType")) and payload.get("Team") in {"TeamLight", "TeamDark"}
    if opcode == "ByCompareMonsterID":
        return (
            _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("TargetMonsterID")))
        )
    if opcode == "ByContainBehaviorFlag":
        singular = payload.get("Flag")
        plural = payload.get("Flags")
        flags_executable = (
            isinstance(singular, str)
            and bool(singular)
            and plural is None
        ) or (
            singular is None
            and isinstance(plural, list)
            and bool(plural)
            and all(isinstance(flag, str) and bool(flag) for flag in plural)
            and len(plural) == len(set(plural))
        )
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and flags_executable
        )
    if opcode == "ByContainsParamFlag":
        return isinstance(payload.get("Flag"), str)
    if opcode == "ByTargetListIntersects":
        return _condition_target_value_executable(
            payload.get("FirstTargetType")
        ) and _condition_target_value_executable(payload.get("SecondTargetType"))
    if opcode == "ByIsContainModifier":
        return _condition_target_value_executable(payload.get("TargetType")) and isinstance(_value_field(payload.get("ModifierName")), str)
    if opcode == "ByIsInsertAction":
        return True
    if opcode in {"ByIsCurrentSkillActive", "ByHaveEnemyAlive"}:
        return _condition_target_value_executable(payload.get("TargetType"))
    if opcode == "ByCompareHPRatio":
        return (
            _condition_target_value_executable(payload.get("TargetType"))
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("CompareValue")))
        )
    if opcode == "ByCompareDynamicValue":
        return (
            isinstance(_value_field(payload.get("DynamicKey")), str)
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("CompareValue")))
        )
    if opcode == "ByCompareCharacterNumber":
        target_node = payload.get("TargetType")
        return (
            isinstance(target_node, TargetExpressionNodeIR)
            and _condition_target_node_executable(target_node)
            and _numeric_expr_can_be_runtime_bound(payload.get("CompareNumber"))
        )
    if opcode == "ByCompareModifierValue":
        return (
            (
                payload.get("TargetType") is None
                or _condition_target_value_executable(payload.get("TargetType"))
            )
            and (payload.get("ValueType") or "Layer") in SUPPORTED_MODIFIER_VALUE_TYPES
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("CompareValue")))
        )
    if opcode == "ByCompareTarget":
        return _condition_target_value_executable(
            payload.get("TargetType")
        ) and _condition_target_value_executable(payload.get("CompareType"))
    if opcode == "ByTargetEntityType":
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES and payload.get("EntityTypeMask") == "Servant"
    if opcode == "ByCompareDamageCustomName":
        return isinstance(_value_field(payload.get("CustomName")), str)
    if opcode == "ByCompareDamageTag":
        tags = payload.get("DamageTagList")
        return (
            isinstance(tags, list)
            and bool(tags)
            and all(
                isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and bool(item.get("name"))
                and not item.get("blocked_reason")
                for item in tags
            )
            and len({str(item["name"]) for item in tags}) == len(tags)
        )
    if opcode in {"ByAnd", "ByAny"}:
        predicates = payload.get("PredicateList")
        return isinstance(predicates, list) and all(_raw_condition_payload_executable(item) for item in predicates)
    if opcode == "ByNot":
        return _raw_condition_payload_executable(payload.get("Predicate"))
    return False


def _condition_target_node_executable(node: TargetExpressionNodeIR) -> bool:
    if node.schema_version != TARGET_EXPRESSION_NODE_SCHEMA:
        return False
    if node.runtime_blocked_reason:
        return False
    if node.expression_kind == "TargetAlias":
        return _target_alias_admitted(node.alias) or node.alias == "AllUnselectable"
    if node.expression_kind in {"TargetSequence", "TargetConcat"}:
        return bool(node.children) and all(_condition_target_node_executable(child) for child in node.children)
    if node.expression_kind == "TargetFilter":
        return (
            (node.candidate is None or _condition_target_node_executable(node.candidate))
            and node.predicate is not None
            and node.predicate.coverage_status == "executable"
        )
    if node.expression_kind in P1_6_SAFE_TARGET_FETCH_KINDS:
        return True
    if node.expression_kind == "TargetQuery":
        return (
            node.query_entity_type_mask == "Servant"
            and node.query_target is not None
            and node.query_compare is not None
            and _condition_target_node_executable(node.query_target)
            and _condition_target_node_executable(node.query_compare)
        )
    return False


def _condition_payload_target_blocked_reason(value: Any) -> str:
    if type(value) is TargetExpressionNodeIR:
        return value.runtime_blocked_reason
    if type(value) is ConditionIR:
        return value.blocked_reason if value.coverage_status != "executable" else _condition_payload_target_blocked_reason(value.payload)
    if isinstance(value, Mapping):
        return next((reason for child in value.values() if (reason := _condition_payload_target_blocked_reason(child))), "")
    if isinstance(value, (list, tuple)):
        return next((reason for child in value if (reason := _condition_payload_target_blocked_reason(child))), "")
    return ""


def _condition_target_value_executable(value: Any) -> bool:
    if isinstance(value, TargetExpressionNodeIR):
        return _condition_target_node_executable(value)
    alias = _target_alias(value)
    return bool(alias and _target_alias_admitted(alias))


def _raw_condition_payload_executable(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("schema_version") == CONDITION_EXPRESSION_NODE_SCHEMA:
        opcode = str(value.get("opcode") or value.get("expression_kind") or "")
        payload = {
            key: item
            for key, item in value.items()
            if key
            not in {
                "schema_version",
                "expression_kind",
                "opcode",
                "supported",
                "blocked_reason",
            }
        }
        return _condition_payload_executable(opcode, payload)
    opcode = _short_gamecore_type(value.get("$type"))
    payload = _compact_payload(value)
    return _condition_payload_executable(opcode, payload)


def _standard_add_modifier_payload(value: dict[str, Any]) -> dict[str, Any]:
    dynamic_values = {
        str(key): _numeric_expr_summary(item)
        for key, item in (value.get("DynamicValues") or {}).items()
        if isinstance(value.get("DynamicValues"), dict)
    }
    lifetime = _numeric_expr_summary(value.get("LifeTime"))
    life_step_moment = _value_field(value.get("LifeStepMoment"))
    return {
        "modifier_name": _value_field(value.get("ModifierName")),
        "target_alias": _target_alias(value.get("TargetType")),
        "dynamic_values": dynamic_values,
        "dynamic_value_requests": _dynamic_value_requests(dynamic_values),
        "lifetime": lifetime,
        "life_step_moment": life_step_moment,
        "duration_admission": _duration_admission_payload(lifetime, life_step_moment),
        "layer_add_when_stack": _numeric_expr_summary(value.get("LayerAddWhenStack")),
        "max_layer": _numeric_expr_summary(value.get("MaxLayer")),
        "chance": _numeric_expr_summary(value.get("Chance")),
        "chance_field_present": "Chance" in value and value.get("Chance") is not None,
        "omitted_chance_semantics": "guaranteed_no_resistance",
        "omitted_chance_semantics_source": {
            "kind": "engine_rule",
            "rule_id": "add_modifier_omitted_chance_is_guaranteed",
        },
    }


SUPPORTED_DURATION_LIFE_STEP_MOMENTS = {"ModifierPhase1End", "ActionPhaseEnd"}


def _duration_admission_payload(lifetime_expr: dict[str, Any], life_step_moment: object) -> dict[str, Any]:
    moment = str(life_step_moment or "")
    if lifetime_expr.get("kind") == "missing":
        return {
            "admission_status": "not_applicable",
            "blocked_reason": "lifetime_missing",
            "life_step_moment": moment,
            "lifetime_expr": lifetime_expr,
        }
    if lifetime_expr.get("kind") != "fixed":
        return {
            "admission_status": "blocked",
            "blocked_reason": f"lifetime_not_fixed:{lifetime_expr.get('kind') or 'unknown'}",
            "life_step_moment": moment,
            "lifetime_expr": lifetime_expr,
        }
    value = lifetime_expr.get("value")
    if not isinstance(value, (int, float)) or float(value) <= 0:
        return {
            "admission_status": "blocked",
            "blocked_reason": "lifetime_non_positive_or_missing",
            "life_step_moment": moment,
            "lifetime_expr": lifetime_expr,
        }
    if moment not in SUPPORTED_DURATION_LIFE_STEP_MOMENTS:
        reason = "life_step_moment_missing" if not moment else f"unsupported_life_step_moment:{moment}"
        return {
            "admission_status": "blocked",
            "blocked_reason": reason,
            "life_step_moment": moment,
            "lifetime_expr": lifetime_expr,
        }
    return {
        "admission_status": "executable",
        "blocked_reason": "",
        "life_step_moment": moment,
        "remaining_duration": float(value),
        "lifetime_expr": lifetime_expr,
    }


def _standard_remove_modifier_payload(value: dict[str, Any], opcode: str, source_modifier_name: str) -> dict[str, Any]:
    if opcode == "RemoveSelfModifier":
        modifier_name = source_modifier_name
        target_alias = "ModifierOwnerEntity"
    else:
        modifier_name = _value_field(value.get("ModifierName"))
        target_alias = _target_alias(value.get("TargetType"))
    status_id = f"modifier:{modifier_name}" if isinstance(modifier_name, str) and modifier_name else None
    return {
        "kind": "status_remove",
        "target_alias": target_alias,
        "modifier_name": modifier_name,
        "status_id": status_id,
    }


def _standard_dispel_status_payload(value: dict[str, Any]) -> dict[str, Any]:
    count_expr = _numeric_expr_summary(value.get("Numbers"))
    order = _value_field(value.get("Order"))
    payload = {
        "kind": "status_dispel",
        "target_alias": _target_alias(value.get("TargetType")),
        "buff_type": _value_field(value.get("BuffType")),
        "numbers": count_expr,
        "order": order,
        "only_alive": value.get("OnlyAlive") if isinstance(value.get("OnlyAlive"), bool) else None,
        "only_can_dispel": value.get("OnlyCanDispel") if isinstance(value.get("OnlyCanDispel"), bool) else True,
        "is_silent_dispel": value.get("IsSilentDispel") if isinstance(value.get("IsSilentDispel"), bool) else None,
        "mute_all_visual_effect": value.get("MuteAllVisualEffect") if isinstance(value.get("MuteAllVisualEffect"), bool) else None,
        "behavior_flags": _list_json_values(value.get("BehaviorFlags")),
        "dispel_count_key": _value_field(value.get("DispelCountKey")),
    }
    if not _numeric_expr_can_be_runtime_bound(count_expr):
        payload["blocked_reason"] = f"dispel_count_not_executable:{count_expr.get('kind') or 'unknown'}"
    elif order not in {"LastAdded", "Random"}:
        payload["blocked_reason"] = f"dispel_order_not_admitted:{order or 'missing'}"
    return payload


def _standard_heal_payload(value: dict[str, Any]) -> dict[str, Any]:
    modify_value = _numeric_expr_summary(value.get("ModifyValue"))
    percentage = _numeric_expr_summary(value.get("HealPercentage"))
    formula_type = _value_field(value.get("FormulaType"))
    formula_type_missing = formula_type in {None, ""}
    ratio_formula_types = {
        "HealByTargetLostHP",
        "HealByTargetMaxHP",
        "HealByHealerMaxHP",
    }
    implicit_percentage_formula = (
        formula_type_missing
        and _numeric_expr_can_be_runtime_bound(percentage)
        and not _numeric_expr_can_be_runtime_bound(modify_value)
    )
    effective_formula_type = (
        "HealByTargetMaxHP" if implicit_percentage_formula else formula_type
    )
    amount = (
        percentage
        if effective_formula_type in ratio_formula_types
        else modify_value
    )
    payload = {
        "kind": "heal",
        "target_alias": _target_alias(value.get("TargetType")),
        "formula_type": effective_formula_type,
        "raw_formula_type": formula_type,
        "formula_type_source": (
            "tbgd_schema_default_for_percentage_only_heal"
            if implicit_percentage_formula
            else "explicit_tbgd_field"
            if not formula_type_missing
            else "missing"
        ),
        "amount": amount,
        "amount_role": (
            "ratio" if effective_formula_type in ratio_formula_types else "flat"
        ),
        "formula_base": _heal_formula_base(effective_formula_type),
        "percentage": percentage,
        "modify_value": modify_value,
        "flat_addition": (
            modify_value
            if effective_formula_type in ratio_formula_types
            and _numeric_expr_can_be_runtime_bound(modify_value)
            else numeric_missing("heal_flat_addition_missing")
        ),
        "raw_formula_fields": {
            "ModifyValue": _json_safe(value.get("ModifyValue")),
            "HealPercentage": _json_safe(value.get("HealPercentage")),
            "FormulaType": _json_safe(value.get("FormulaType")),
        },
    }
    if effective_formula_type not in {
        None,
        "",
        "HealByBaseValue",
        *ratio_formula_types,
    }:
        payload["blocked_reason"] = (
            f"formula_type_not_supported:{effective_formula_type}"
        )
    elif not _numeric_expr_can_be_runtime_bound(amount):
        payload["blocked_reason"] = "fixed_or_bound_heal_percentage_required" if effective_formula_type in ratio_formula_types else "fixed_or_bound_modify_value_required"
    return payload


def _standard_shield_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    shield_value = _numeric_expr_summary(value.get("ShieldValue"))
    percentage = _numeric_expr_summary(value.get("ShieldPercentage"))
    formula_type = _value_field(value.get("FormulaType"))
    ratio_formula_types = {"ShieldByCasterMaxHP", "ShieldByCasterDefence", "ShieldByTargetMaxHP"}
    amount = percentage if formula_type in ratio_formula_types else shield_value
    payload = {
        "kind": "shield",
        "shield_opcode": opcode,
        "target_alias": _target_alias(value.get("TargetType")),
        "formula_type": formula_type,
        "amount": amount,
        "amount_role": "ratio" if formula_type in ratio_formula_types else "flat",
        "formula_base": _shield_formula_base(formula_type),
        "percentage": percentage,
        "shield_value": shield_value,
        "raw_formula_fields": {
            "ShieldValue": _json_safe(value.get("ShieldValue")),
            "ShieldPercentage": _json_safe(value.get("ShieldPercentage")),
            "FormulaType": _json_safe(value.get("FormulaType")),
        },
    }
    if formula_type not in {None, "", "ShieldByBaseValue", *ratio_formula_types}:
        payload["blocked_reason"] = f"formula_type_not_supported:{formula_type}"
    elif not _numeric_expr_can_be_runtime_bound(amount):
        payload["blocked_reason"] = "fixed_or_bound_shield_percentage_required" if formula_type in ratio_formula_types else "fixed_or_bound_shield_value_required"
    return payload


def _standard_remove_shield_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "shield_remove",
        "target_alias": _target_alias(value.get("TargetType")),
        "removal_identity": "current_status_instance",
    }


def _standard_mechanism_bar_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    current_count = _numeric_expr_summary(value.get("CurrentCount"))
    max_count = _numeric_expr_summary(value.get("MaxCount"))
    payload = {
        "kind": "mechanism_bar_state",
        "opcode": opcode,
        "target_alias": _target_alias(value.get("TargetType")),
        "bar_type": _value_field(value.get("BarType")),
        "active": _value_field(value.get("Active")),
        "state": _value_field(value.get("CurrentState", value.get("State"))),
        "current_count": current_count,
        "max_count": max_count,
        "raw_formula_fields": {
            "Active": _json_safe(value.get("Active")),
            "BarType": _json_safe(value.get("BarType")),
            "CurrentState": _json_safe(value.get("CurrentState")),
            "State": _json_safe(value.get("State")),
            "CurrentCount": _json_safe(value.get("CurrentCount")),
            "MaxCount": _json_safe(value.get("MaxCount")),
        },
    }
    if not _mechanism_bar_has_runtime_payload(payload):
        payload["blocked_reason"] = "fixed_or_bound_mechanism_bar_state_or_count_required"
    return payload


def _standard_resource_delta_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    admitted_fields = (
        "AddValue",
        "ModifyValue",
        "FixedAddValue",
        "SetValue",
        "FixedSetValue",
        "AddMaxSPRatio",
        "FixedAddMaxSPRatio",
        "SetMaxSPRatio",
        "FixedSetMaxSPRatio",
    )
    amount_field = _first_present_key(value, admitted_fields)
    unsupported_field = "" if amount_field else _first_present_key(
        value,
        (
            "AddRatio",
            "FixedAddRatio",
        ),
    )
    formula_field = amount_field or unsupported_field
    amount = _numeric_expr_summary(value.get(formula_field) if formula_field else None)
    raw_operation = _value_field(value.get("ModifyFunction"))
    operation = (
        str(raw_operation).lower()
        if raw_operation in {"Add", "Set"}
        else "set"
        if formula_field in {
            "SetValue",
            "FixedSetValue",
            "SetMaxSPRatio",
            "FixedSetMaxSPRatio",
        }
        else "add"
    )
    scale_basis = "max_energy" if formula_field in {"AddMaxSPRatio", "FixedAddMaxSPRatio", "SetMaxSPRatio", "FixedSetMaxSPRatio"} else "flat"
    resource = {
        "ModifySPNew": "energy",
        "ModifyTeamBoostPoint": "skill_points",
        "ModifyTeamBoostPointMax": "max_skill_points",
    }.get(opcode, opcode)
    payload = {
        "kind": "resource_delta",
        "resource": resource,
        "target_alias": _target_alias(value.get("TargetType")),
        "formula_type": formula_field or "missing",
        "amount": amount,
        "operation": operation,
        "scale_basis": scale_basis,
        "raw_formula_fields": {
            "AddValue": _json_safe(value.get("AddValue")),
            "ModifyValue": _json_safe(value.get("ModifyValue")),
            "FixedAddValue": _json_safe(value.get("FixedAddValue")),
            "AddRatio": _json_safe(value.get("AddRatio")),
            "FixedAddRatio": _json_safe(value.get("FixedAddRatio")),
            "AddMaxSPRatio": _json_safe(value.get("AddMaxSPRatio")),
            "FixedAddMaxSPRatio": _json_safe(value.get("FixedAddMaxSPRatio")),
            "SetValue": _json_safe(value.get("SetValue")),
            "SetMaxSPRatio": _json_safe(value.get("SetMaxSPRatio")),
            "FixedSetValue": _json_safe(value.get("FixedSetValue")),
            "FixedSetMaxSPRatio": _json_safe(value.get("FixedSetMaxSPRatio")),
            "ModifyFunction": _json_safe(value.get("ModifyFunction")),
        },
    }
    if raw_operation not in {None, "", "Add", "Set"}:
        payload["blocked_reason"] = (
            f"resource_modify_function_not_supported:{raw_operation}"
        )
    elif unsupported_field:
        payload["blocked_reason"] = f"resource_formula_type_not_supported:{unsupported_field}"
    elif not _numeric_expr_can_be_runtime_bound(amount):
        payload["blocked_reason"] = "fixed_or_bound_resource_delta_required"
    return payload


def _standard_hp_loss_ratio_payload(value: dict[str, Any]) -> dict[str, Any]:
    ratio = _numeric_expr_summary(value.get("Ratio"))
    ratio_type = _value_field(value.get("RatioType"))
    dynamic_result_present = "DynamicFloatSet" in value
    dynamic_result_name = _value_field(value.get("DynamicFloatSet"))
    floor = bool(value.get("Floor")) if value.get("Floor") is not None else False
    payload = {
        "kind": "hp_loss_ratio",
        "target_alias": _target_alias(value.get("TargetType")),
        "ratio": ratio,
        "ratio_type": ratio_type,
        "floor": floor,
        "attack_type": _value_field(value.get("AttackType")),
        "damage_type": _value_field(value.get("DamageType")),
        "raw_formula_fields": {
            "Ratio": _json_safe(value.get("Ratio")),
            "RatioType": _json_safe(value.get("RatioType")),
            "Floor": _json_safe(value.get("Floor")),
            "AttackType": _json_safe(value.get("AttackType")),
            "DamageType": _json_safe(value.get("DamageType")),
            "TargetType": _json_safe(value.get("TargetType")),
            "DynamicFloatSet": _json_safe(value.get("DynamicFloatSet")),
        },
    }
    if dynamic_result_present:
        payload["dynamic_result_name"] = dynamic_result_name
    if floor:
        payload["rounding_policy"] = "floor_from_tbgd_flag"
    if dynamic_result_present and (
        not isinstance(dynamic_result_name, str) or not dynamic_result_name
    ):
        payload["blocked_reason"] = "hp_loss_dynamic_result_name_invalid"
    elif ratio_type not in {"MaxHP", "CurrentHP"}:
        payload["blocked_reason"] = f"hp_loss_ratio_type_not_supported:{ratio_type}"
    elif not _numeric_expr_can_be_runtime_bound(ratio):
        payload["blocked_reason"] = str(ratio.get("reason") or "fixed_or_bound_hp_loss_ratio_required")
    return payload


def _heal_formula_base(formula_type: Any) -> str:
    if formula_type == "HealByTargetLostHP":
        return "target.lost_hp"
    if formula_type == "HealByTargetMaxHP":
        return "target.max_hp"
    if formula_type == "HealByHealerMaxHP":
        return "caster.max_hp"
    return "flat"


def _shield_formula_base(formula_type: Any) -> str:
    if formula_type == "ShieldByCasterMaxHP":
        return "caster.max_hp"
    if formula_type == "ShieldByCasterDefence":
        return "caster.defense"
    if formula_type == "ShieldByTargetMaxHP":
        return "target.max_hp"
    return "flat"


def _standard_set_dynamic_value_payload(value: dict[str, Any]) -> dict[str, Any]:
    value_expr = _numeric_expr_summary(value.get("Value"))
    value_name = _value_field(value.get("DynamicKey"))
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "SetDynamicValue",
        "target_alias": target_alias,
        "status_scope": _value_field(value.get("ContextScope")) or "modifier_local",
        "value_name": value_name,
        "hash": None,
        "value_expr": value_expr,
        "raw_formula_fields": {
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "Value": _json_safe(value.get("Value")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(value_name, str) or not value_name:
        payload["blocked_reason"] = "dynamic_value_name_required"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif not _numeric_expr_can_be_runtime_bound(value_expr):
        payload["blocked_reason"] = str(value_expr.get("reason") or "fixed_or_bound_dynamic_value_required")
    return payload


def _standard_trigger_modifier_custom_event_payload(
    value: dict[str, Any],
) -> dict[str, Any]:
    dynamic_key = _value_field(value.get("DynamicKey"))
    event_type = _value_field(value.get("EventType"))
    value_expr = _numeric_expr_summary(value.get("Value"))
    payload = {
        "kind": "modifier_custom_event",
        "opcode": "TriggerModifierCustomEvent",
        "target_alias": _target_alias(value.get("TargetType")) or "",
        "dynamic_key": dynamic_key,
        "event_type": event_type,
        "value_expr": value_expr,
        "raw_fields": {
            "TargetType": _json_safe(value.get("TargetType")),
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "EventType": _json_safe(value.get("EventType")),
            "Value": _json_safe(value.get("Value")),
        },
    }
    if not isinstance(dynamic_key, str) or not dynamic_key:
        payload["blocked_reason"] = "custom_event_dynamic_key_required"
    elif not isinstance(event_type, (int, str)) or isinstance(event_type, bool):
        payload["blocked_reason"] = "custom_event_type_required"
    elif not _numeric_expr_can_be_runtime_bound(value_expr):
        payload["blocked_reason"] = str(
            value_expr.get("reason") or "custom_event_value_not_executable"
        )
    return payload


def _standard_stack_weakness_payload(value: dict[str, Any]) -> dict[str, Any]:
    raw_weaknesses = value.get("WeakList")
    weaknesses = (
        list(raw_weaknesses)
        if isinstance(raw_weaknesses, list)
        else []
    )
    operation_type = value.get("OPType")
    payload = {
        "kind": "stack_weakness",
        "opcode": "StackWeakness",
        "target_alias": _target_alias(value.get("TargetType")) or "",
        "operation_type": operation_type,
        "weaknesses": weaknesses,
        "raw_fields": {
            "TargetType": _json_safe(value.get("TargetType")),
            "OPType": _json_safe(operation_type),
            "WeakList": _json_safe(raw_weaknesses),
        },
    }
    if operation_type != "Attach":
        payload["blocked_reason"] = (
            f"stack_weakness_operation_not_admitted:{operation_type or 'missing'}"
        )
    elif not weaknesses:
        payload["blocked_reason"] = "stack_weakness_list_missing"
    elif not all(isinstance(item, str) and item for item in weaknesses):
        payload["blocked_reason"] = "stack_weakness_list_invalid"
    elif len(weaknesses) != len(set(weaknesses)):
        payload["blocked_reason"] = "stack_weakness_list_duplicate"
    return payload


def _standard_trigger_ability_payload(value: dict[str, Any]) -> dict[str, Any]:
    ability_name = _value_field(value.get("AbilityName"))
    target_alias = _target_alias(value.get("TargetType")) or "Caster"
    inherent_target_alias = _target_alias(value.get("AbilityInherentTargetType"))
    payload = {
        "kind": "standalone_ability_trigger",
        "opcode": "TriggerAbility",
        "ability_name": ability_name,
        "target_alias": target_alias,
        "inherent_target_alias": inherent_target_alias or "",
        "raw_fields": {
            "AbilityName": _json_safe(value.get("AbilityName")),
            "TargetType": _json_safe(value.get("TargetType")),
            "AbilityInherentTargetType": _json_safe(value.get("AbilityInherentTargetType")),
        },
    }
    if not isinstance(ability_name, str) or not ability_name:
        payload["blocked_reason"] = "trigger_ability_name_required"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    return payload


def _standard_define_dynamic_value_payload(value: dict[str, Any]) -> dict[str, Any]:
    value_expr = _numeric_expr_summary(value.get("ResetValue"))
    if value_expr.get("kind") == "missing":
        value_expr = numeric_fixed(0.0)
    value_name = _value_field(value.get("DynamicKey"))
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "DefineDynamicValue",
        "target_alias": target_alias,
        "status_scope": _value_field(value.get("ContextScope")) or "modifier_local",
        "value_name": value_name,
        "hash": None,
        "value_expr": value_expr,
        "value_source_basis": (
            "tbgd_define_dynamic_value_missing_reset_defaults_to_zero"
            if "ResetValue" not in value
            else "explicit_tbgd_field"
        ),
        "raw_formula_fields": {
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "ResetValue": _json_safe(value.get("ResetValue")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(value_name, str) or not value_name:
        payload["blocked_reason"] = "dynamic_value_name_required"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif not _numeric_expr_can_be_runtime_bound(value_expr):
        payload["blocked_reason"] = str(value_expr.get("reason") or "fixed_or_bound_dynamic_value_required")
    return payload


def _standard_set_dynamic_value_by_add_value_payload(value: dict[str, Any]) -> dict[str, Any]:
    add_value = _numeric_expr_summary(value.get("AddValue"))
    min_value = _numeric_expr_summary(value.get("Min"))
    max_value = _numeric_expr_summary(value.get("Max"))
    value_name = _value_field(value.get("Key") or value.get("DynamicKey"))
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "SetDynamicValueByAddValue",
        "target_alias": target_alias,
        "status_scope": _value_field(value.get("ContextScope")) or "modifier_local",
        "value_name": value_name,
        "add_value": add_value,
        "min_value": min_value,
        "max_value": max_value,
        "raw_formula_fields": {
            "Key": _json_safe(value.get("Key")),
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "AddValue": _json_safe(value.get("AddValue")),
            "Min": _json_safe(value.get("Min")),
            "Max": _json_safe(value.get("Max")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(value_name, str) or not value_name:
        payload["blocked_reason"] = "dynamic_value_name_required"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif not _numeric_expr_can_be_runtime_bound(add_value):
        payload["blocked_reason"] = str(add_value.get("reason") or "fixed_or_bound_dynamic_add_value_required")
    return payload


def _standard_set_dynamic_value_by_modifier_value_payload(
    value: dict[str, Any],
    source_modifier_name: str,
) -> dict[str, Any]:
    source_modifier = _value_field(value.get("ModifierName")) or source_modifier_name
    source_value_name = _value_field(value.get("ValueType"))
    target_value_name = _value_field(value.get("DynamicKey"))
    multiplier = _numeric_expr_summary(value.get("Multiplier"))
    source_target_alias = _target_alias(value.get("ReadTargetType")) or "ModifierOwnerEntity"
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "SetDynamicValueByModifierValue",
        "source_modifier": source_modifier,
        "source_value_name": source_value_name,
        "source_hash": None,
        "target_value_name": target_value_name,
        "target_hash": None,
        "target_alias": target_alias,
        "source_target_alias": source_target_alias,
        "context_scope": _value_field(value.get("ContextScope")),
        "multiplier": multiplier,
        "raw_formula_fields": {
            "ModifierName": _json_safe(value.get("ModifierName")),
            "ValueType": _json_safe(value.get("ValueType")),
            "Multiplier": _json_safe(value.get("Multiplier")),
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "ReadTargetType": _json_safe(value.get("ReadTargetType")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(source_modifier, str) or not source_modifier:
        payload["blocked_reason"] = "source_modifier_required"
    elif source_target_alias not in EXECUTABLE_TARGET_ALIASES:
        payload["blocked_reason"] = f"unsupported_source_target_alias:{source_target_alias}"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif source_value_name not in SUPPORTED_MODIFIER_VALUE_TYPES:
        payload["blocked_reason"] = f"unsupported_modifier_value_type:{source_value_name}"
    elif not isinstance(target_value_name, str) or not target_value_name:
        payload["blocked_reason"] = "target_value_name_required"
    elif not _numeric_expr_can_be_runtime_bound(multiplier):
        payload["blocked_reason"] = str(multiplier.get("reason") or "fixed_or_bound_multiplier_required")
    return payload


def _standard_generic_dynamic_value_payload(
    value: dict[str, Any],
    opcode: str,
    source_modifier_name: str,
) -> dict[str, Any]:
    destination_fields = (
        ("ToDynamicKey",)
        if opcode == "SetDynamicValueByCopying"
        else ("WriteToKey",)
        if opcode == "SetDynamicValueByWaveStageCount"
        else (
            "DynamicKey",
            "Key",
            "TargetDynamicKey",
            "TargetKey",
            "DynamicFloatSet",
        )
    )
    destination_key = _first_dynamic_string(
        value,
        destination_fields,
    )
    target_field = (
        "ToTargetType"
        if opcode == "SetDynamicValueByCopying"
        else "WriteTargetType"
        if opcode == "SetDynamicValueByWeaknessCount"
        else "TargetType"
    )
    target_alias = _target_alias(value.get(target_field)) or "ModifierOwnerEntity"
    source_target_alias = (
        _target_alias(value.get("FromTargetType"))
        if opcode == "SetDynamicValueByCopying"
        else _target_alias(value.get("ReadTargetType"))
        or _target_alias(value.get("SourceTargetType"))
        or target_alias
    )
    property_name = (
        _first_dynamic_string(value, ("Value",))
        if opcode in {
            "SetDynamicValueByProperty",
            "SetDynamicValueByPropertyClientOnly",
        }
        else _first_dynamic_string(
            value,
            ("PropertyName", "PropertyType", "DataProperty", "AbilityProperty"),
        )
    )
    status_identity = _first_dynamic_string(
        value,
        ("ModifierName", "StatusID", "StatusType", "StatusName"),
    )
    resource_name = _first_dynamic_string(
        value,
        ("ResourceName", "ResourceType", "BPType"),
    )
    source_key = _first_dynamic_string(
        value,
        (
            "FromDynamicKey",
            "SourceDynamicKey",
            "SourceKey",
            "ReadDynamicKey",
            "CopyKey",
        ),
    )
    resource_name = (
        "skill_points"
        if opcode == "SetDynamicValueByCurrentBP"
        else "max_skill_points"
        if opcode == "SetDynamicValueByMaxBP"
        else resource_name
    )
    multiplier = (
        _numeric_expr_summary(value.get("Multiplier"))
        if "Multiplier" in value
        else None
    )
    payload: dict[str, Any] = {
        "kind": "dynamic_value_store",
        "opcode": opcode,
        "target_alias": target_alias,
        "status_scope": _value_field(
            value.get("TargetContextScope")
            if opcode == "SetDynamicValueByCopying"
            else value.get("ContextScope")
        ),
        "value_name": destination_key,
        "hash": _value_field(value.get("Hash")),
        "operation": _value_field(value.get("Operation")),
        "operand_parameters": {
            "source_target_alias": source_target_alias,
            "source_key": source_key,
            "source_hash": _value_field(value.get("SourceHash")),
            "source_modifier": _first_dynamic_string(
                value,
                ("FromModifierName",),
            ),
            "property_name": property_name,
            "status_identity": status_identity,
            "count_mode": (
                "debuff"
                if opcode == "SetDynamicValueByStatusCount"
                else None
            ),
            "modifier_name": _value_field(value.get("ModifierName"))
            or source_modifier_name,
            "modifier_value_name": _value_field(value.get("ValueType")),
            "resource_name": resource_name,
            "event_property": _value_field(value.get("Property")),
            "value_type": _value_field(value.get("ValueType")),
            "base_types": _json_safe(value.get("BaseTypeList")),
            "alive_only": _json_safe(value.get("AliveOnly")),
            "predicate": _json_safe(value.get("Predicate")),
            "attacker_alias": _target_alias(value.get("Attacker"))
            or _target_alias(value.get("AttackerTargetType")),
            "defender_alias": _target_alias(value.get("DefenderTargetType")),
            "attack_type": _value_field(value.get("AttackType")),
            "damage_type": _value_field(value.get("DamageType")),
            "force_stance_break_ratio": _json_safe(
                value.get("ForceStanceBreakRatio")
            ),
            "stance_value": _json_safe(value.get("StanceValue")),
            "add_force_stance_damage": _json_safe(
                value.get("AddForceStanceDamageFlag")
            ),
            "skill_trigger_key": _json_safe(value.get("SkillTriggerKey")),
            "status_flag": _value_field(value.get("Flag")),
            "variate_type": _value_field(value.get("VariateType")),
            "minimum": (
                _numeric_expr_summary(value.get("Min"))
                if "Min" in value
                else None
            ),
            "maximum": (
                _numeric_expr_summary(value.get("Max"))
                if "Max" in value
                else None
            ),
            "integer_only": _json_safe(value.get("IsInt")),
            "weakness_filter": _json_safe(value.get("WeaknessFilter")),
            "write_target_alias": _target_alias(value.get("WriteTargetType")),
            "wave_stage_source": (
                "battle_wave_stage"
                if opcode == "SetDynamicValueByWaveStageCount"
                else None
            ),
        },
    }
    if opcode == "SetModifierDynamicValue":
        payload["value_expr"] = _numeric_expr_summary(value.get("NewValue"))
        payload["status_scope"] = "ContextModifier"
    if opcode == "SetDynamicValueClientOnly":
        payload["value_expr"] = _numeric_expr_summary(value.get("Value"))
        payload["blocked_reason"] = "client_only_dynamic_value"
    elif opcode == "SetDynamicValueByPropertyClientOnly":
        payload["blocked_reason"] = "client_only_dynamic_value"
    if multiplier is not None:
        payload["multiplier"] = multiplier
    if target_alias not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    return payload


def _first_dynamic_string(
    value: dict[str, Any],
    fields: tuple[str, ...],
) -> str | None:
    for field_name in fields:
        field_value = _value_field(value.get(field_name))
        if isinstance(field_value, str) and field_value:
            return field_value
    return None


def _dynamic_value_bindings(value: Any) -> dict[str, Any]:
    floats = value.get("Floats") if isinstance(value, dict) else None
    if not isinstance(floats, dict):
        return {"by_hash": {}, "raw": _json_safe(value)}
    by_hash: dict[str, Any] = {}
    for key, item in floats.items():
        by_hash[str(key)] = {
            "hash": str(key),
            "value_type": "float",
            "read_info": _json_safe(item.get("ReadInfo")) if isinstance(item, dict) else None,
            "raw": _json_safe(item),
            "raw_path": f"DynamicValues.Floats[{key}]",
        }
    return {"by_hash": by_hash, "raw": _json_safe(value)}


def _ability_graph_source_context(
    *,
    source_mode: str,
    skill_row: dict[str, Any],
    skill_trigger_key: str,
    character_path: str,
    character_config: dict[str, Any],
    config_source: dict[str, Any],
    config_kind: str,
    ability_paths: tuple[str, ...],
    skill_rows_by_trigger_key: dict[str, dict[str, Any]] | None = None,
    allowed_dynamic_hashes: set[str] | None = None,
) -> dict[str, Any]:
    skill_param_binding_source, skill_param_summary = _skill_param_numeric_binding_source(
        character_config=character_config,
        skill_row=skill_row,
        skill_trigger_key=skill_trigger_key,
        character_path=character_path,
        skill_rows_by_trigger_key=skill_rows_by_trigger_key,
        allowed_dynamic_hashes=allowed_dynamic_hashes,
    )
    custom_values = character_config.get("CustomValues")
    context: dict[str, Any] = {
        "source_mode": source_mode,
        "skill_id": _json_safe(skill_row.get("SkillID")),
        "skill_trigger_key": skill_trigger_key,
        "skill_source_path": str(skill_row.get("_v8_source_path") or ""),
        "skill_row_index": _json_safe(skill_row.get("_v8_row_index")),
        "param_list": _json_safe(skill_row.get("ParamList") if isinstance(skill_row.get("ParamList"), list) else []),
        "character_config_path": character_path,
        "config_kind": config_kind,
        "config_source": _compact_ability_config_source(config_source),
        "ability_paths": [path for path in ability_paths if path],
        "skill_param_dynamic_bindings": skill_param_summary,
        "numeric_binding_sources": [skill_param_binding_source] if skill_param_binding_source.get("by_hash") else [],
        "custom_value_keys": sorted(str(key) for key in custom_values.keys())[:80] if isinstance(custom_values, dict) else [],
        "custom_value_bindings": _custom_value_binding_summary(config_source, character_config),
        "override_skill_params": _json_safe(config_source.get("override_skill_params") or []),
    }
    return _json_safe(context)


def _compact_ability_config_source(config_source: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "relative_path",
        "row_index",
        "avatar_id",
        "monster_id",
        "servant_id",
        "template_id",
        "json_path",
        "template_source_path",
        "template_row_index",
        "version_kind",
        "enhanced_id",
    )
    return {key: _json_safe(config_source.get(key)) for key in keys if key in config_source}


def _custom_value_binding_summary(config_source: dict[str, Any], character_config: dict[str, Any]) -> dict[str, Any]:
    raw_custom_values = config_source.get("custom_values")
    character_values = character_config.get("CustomValues") if isinstance(character_config, dict) else None
    character_values = character_values if isinstance(character_values, dict) else {}
    entries: list[dict[str, Any]] = []
    if isinstance(raw_custom_values, list):
        for index, item in enumerate(raw_custom_values):
            if not isinstance(item, dict):
                continue
            name = item.get("BFLIFKBEOPJ") or item.get("Name") or item.get("Key")
            raw_value = item.get("MNDFOPKBHKP", item.get("Value"))
            entry: dict[str, Any] = {
                "index": index,
                "name": str(name or ""),
                "raw_path": f"CustomValues[{index}]",
                "raw_name_field": "BFLIFKBEOPJ" if "BFLIFKBEOPJ" in item else "",
                "raw_value_field": "MNDFOPKBHKP" if "MNDFOPKBHKP" in item else ("Value" if "Value" in item else ""),
                "value": _json_safe(raw_value),
                "character_config_value": _json_safe(character_values.get(str(name))) if name is not None else None,
                "character_config_hit": str(name) in character_values if name is not None else False,
            }
            entries.append(entry)
    elif isinstance(raw_custom_values, dict):
        for index, (name, raw_value) in enumerate(sorted(raw_custom_values.items(), key=lambda pair: str(pair[0]))):
            entries.append(
                {
                    "index": index,
                    "name": str(name),
                    "raw_path": f"CustomValues[{name}]",
                    "raw_name_field": "dict_key",
                    "raw_value_field": "dict_value",
                    "value": _json_safe(raw_value),
                    "character_config_value": _json_safe(character_values.get(str(name))),
                    "character_config_hit": str(name) in character_values,
                }
            )
    return {
        "source_type": "monster_config_custom_values",
        "entry_count": len(entries),
        "entries": _json_safe(entries[:24]),
        "hash_to_name_admitted": False,
        "blocked_reason": "custom_value_hash_to_name_binding_missing",
    }


def _standard_owner_entity_add_ability_payload(value: dict[str, Any]) -> dict[str, Any]:
    ability_name = _value_field(value.get("AbilityName"))
    return {
        "schema_version": "hsr.owner_entity_ability_attachment.v1",
        "ability_name": ability_name if isinstance(ability_name, str) else "",
        "target_relation": "status_owner_entity",
    }


def _standard_attach_entity_departed_payload(
    value: dict[str, Any],
) -> dict[str, Any]:
    target_alias = _target_alias(value.get("TargetType"))
    return {
        "schema_version": "hsr.entity_departure_attachment.v1",
        "target_alias": target_alias or "ModifierOwnerEntity",
        "target_source_mode": (
            "explicit_target_expression"
            if target_alias
            else "opcode_omitted_modifier_owner"
        ),
        "config_group_name": (
            value["ConfigGroupName"]
            if isinstance(value.get("ConfigGroupName"), str)
            else ""
        ),
    }


def _skill_param_numeric_binding_source(
    *,
    character_config: dict[str, Any],
    skill_row: dict[str, Any],
    skill_trigger_key: str,
    character_path: str,
    skill_rows_by_trigger_key: dict[str, dict[str, Any]] | None = None,
    allowed_dynamic_hashes: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    floats = character_config.get("DynamicValues", {}).get("Floats") if isinstance(character_config, dict) else None
    rows_by_trigger: dict[str, dict[str, Any]] = dict(skill_rows_by_trigger_key or {})
    if skill_trigger_key and skill_trigger_key not in rows_by_trigger:
        rows_by_trigger[skill_trigger_key] = skill_row
    by_hash: dict[str, Any] = {}
    summary_entries: list[dict[str, Any]] = []
    if isinstance(floats, dict):
        for raw_hash, item in sorted(floats.items(), key=lambda pair: str(pair[0])):
            hash_key = str(raw_hash)
            if allowed_dynamic_hashes is not None and hash_key not in allowed_dynamic_hashes:
                continue
            if not isinstance(item, dict):
                continue
            read_info = item.get("ReadInfo")
            if not isinstance(read_info, dict):
                continue
            if read_info.get("Type") != "SkillParam":
                continue
            trigger_key = str(read_info.get("TriggerKey") or "")
            binding_skill_row = rows_by_trigger.get(trigger_key)
            if binding_skill_row is None:
                continue
            param_list = binding_skill_row.get("ParamList") if isinstance(binding_skill_row.get("ParamList"), list) else []
            param_index_raw = read_info.get("Index")
            entry_summary: dict[str, Any] = {
                "hash": str(raw_hash),
                "trigger_key": trigger_key,
                "current_skill_trigger_key": skill_trigger_key,
                "skill_id": _json_safe(binding_skill_row.get("SkillID")),
                "skill_source_path": str(binding_skill_row.get("_v8_source_path") or ""),
                "skill_row_index": _json_safe(binding_skill_row.get("_v8_row_index")),
                "param_index": _json_safe(param_index_raw),
                "read_info": _json_safe(read_info),
                "source_path": character_path,
                "raw_path": f"DynamicValues.Floats[{raw_hash}].ReadInfo",
            }
            if not isinstance(param_index_raw, int):
                summary_entries.append({**entry_summary, "admission_status": "blocked", "blocked_reason": "skill_param_index_not_integer"})
                continue
            if param_index_raw < 0 or param_index_raw >= len(param_list):
                summary_entries.append(
                    {
                        **entry_summary,
                        "admission_status": "blocked",
                        "blocked_reason": "skill_param_index_out_of_range",
                        "param_count": len(param_list),
                    }
                )
                continue
            param_raw = param_list[param_index_raw]
            value = _numeric_param_value(param_raw)
            if value is None:
                summary_entries.append(
                    {
                        **entry_summary,
                        "admission_status": "blocked",
                        "blocked_reason": "skill_param_value_not_numeric",
                        "param_raw": _json_safe(param_raw),
                    }
                )
                continue
            entry = {
                "hash": str(raw_hash),
                "trigger_key": trigger_key,
                "current_skill_trigger_key": skill_trigger_key,
                "skill_id": _json_safe(binding_skill_row.get("SkillID")),
                "skill_source_path": str(binding_skill_row.get("_v8_source_path") or ""),
                "skill_row_index": _json_safe(binding_skill_row.get("_v8_row_index")),
                "param_index": _json_safe(param_index_raw),
                "source_path": character_path,
                "raw_path": f"DynamicValues.Floats[{raw_hash}].ReadInfo",
                "admission_status": "executable",
                "param_raw": _json_safe(param_raw),
                "value": float(value),
                "source_trace": {
                    "source_path": character_path,
                    "raw_type": "CharacterConfig.DynamicValues.SkillParam",
                    "raw_id": str(raw_hash),
                    "evidence": {
                        "skill_source_path": str(skill_row.get("_v8_source_path") or ""),
                        "current_skill_id": _json_safe(skill_row.get("SkillID")),
                        "current_skill_trigger_key": skill_trigger_key,
                        "binding_skill_source_path": str(binding_skill_row.get("_v8_source_path") or ""),
                        "binding_skill_id": _json_safe(binding_skill_row.get("SkillID")),
                        "binding_skill_trigger_key": trigger_key,
                        "param_ref": f"ParamList[{param_index_raw}]",
                        "param_value": _json_safe(param_raw),
                    },
                },
            }
            by_hash[str(raw_hash)] = entry
            summary_entries.append(entry)
    binding_source = {
        "source_type": "character_config_skill_param",
        "by_hash": by_hash,
        "by_name": {},
    }
    summary = {
        "source_type": "character_config_skill_param",
        "entry_count": len(by_hash),
        "blocked_count": sum(1 for item in summary_entries if item.get("admission_status") == "blocked"),
        "allowed_dynamic_hash_count": len(allowed_dynamic_hashes or ()),
        "entries": summary_entries[:12],
    }
    return binding_source, summary


def _dynamic_hashes_for_ability_names(ability_names: list[str], ability_map: dict[str, dict[str, Any]]) -> set[str]:
    hashes: set[str] = set()
    for ability_name in ability_names:
        ability = ability_map.get(ability_name)
        if isinstance(ability, dict):
            _collect_dynamic_hashes(ability, hashes)
    return hashes


def _collect_dynamic_hashes(value: Any, result: set[str]) -> None:
    if isinstance(value, dict):
        dynamic_hashes = value.get("DynamicHashes")
        if isinstance(dynamic_hashes, list):
            for item in dynamic_hashes:
                if isinstance(item, int):
                    result.add(str(item))
        for item in value.values():
            _collect_dynamic_hashes(item, result)
    elif isinstance(value, list):
        for item in value:
            _collect_dynamic_hashes(item, result)


def _skill_rows_by_trigger_key_for_config(
    config_source: dict[str, Any],
    skill_rows_by_id: dict[str, dict[str, Any]],
    current_skill_row: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    def add(row: Any) -> None:
        if not isinstance(row, dict):
            return
        trigger_key = str(row.get("SkillTriggerKey") or "")
        if trigger_key:
            rows.setdefault(trigger_key, row)

    add(current_skill_row)
    for key in ("skill_list", "base_skill_list", "enhanced_skill_list"):
        raw_skill_ids = config_source.get(key)
        if not isinstance(raw_skill_ids, list):
            continue
        for skill_id in raw_skill_ids:
            add(skill_rows_by_id.get(str(skill_id)))
    return rows


def _numeric_param_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return _numeric_param_value(value.get("Value"))
    return None


def _dynamic_value_requests(dynamic_values: dict[str, Any]) -> dict[str, Any]:
    requests: dict[str, Any] = {}
    for key, expr in dynamic_values.items():
        request: dict[str, Any] = {"name": key, "expr": _json_safe(expr)}
        if isinstance(expr, dict) and expr.get("kind") == "dynamic_hash":
            request["hash"] = expr.get("hash")
        requests[key] = request
    return requests


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _summon_unit_config_summary(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {"config_readable": False}
    on_create_opcodes = _iter_gamecore_opcodes(config.get("OnCreate"))[:40]
    on_destroy_opcodes = _iter_gamecore_opcodes(config.get("OnDestroy"))[:40]
    trigger_opcodes = _iter_gamecore_opcodes(config.get("TriggerConfig"))[:80]
    adventure_or_maze_markers = _summon_unit_adventure_or_maze_markers(
        group_name=str(config.get("GroupConfigName") or ""),
        opcodes=(*on_create_opcodes, *on_destroy_opcodes, *trigger_opcodes),
    )
    return {
        "config_readable": True,
        "group_config_name": str(config.get("GroupConfigName") or ""),
        "config_entity_path": str(config.get("ConfigEntityPath") or ""),
        "has_skill_config": isinstance(config.get("SkillConfig"), dict),
        "has_ai_config": isinstance(config.get("AIConfig"), dict),
        "has_trigger_config": isinstance(config.get("TriggerConfig"), dict),
        "has_resident_effects": isinstance(config.get("ResidentEffects"), list) and bool(config.get("ResidentEffects")),
        "on_create_opcodes": on_create_opcodes,
        "on_destroy_opcodes": on_destroy_opcodes,
        "trigger_opcodes": trigger_opcodes,
        "adventure_or_maze_markers": adventure_or_maze_markers,
        "raw_config_keys": sorted(str(key) for key in config.keys())[:80],
    }


def _summon_unit_kind(row: dict[str, Any], config_summary: dict[str, Any]) -> str:
    source_mode = _summon_unit_source_mode(row, config_summary)
    if source_mode == "client_or_visual":
        return "client_or_visual_summon"
    if source_mode == "destroy_on_enter_battle":
        return "destroy_on_enter_battle_summon"
    if source_mode == "adventure_or_maze":
        return "adventure_or_maze_summon"
    if source_mode == "battle_runtime_candidate":
        return "battle_runtime_candidate"
    if source_mode == "config_missing":
        return "config_missing"
    return "catalog_or_scene_summon"


def _summon_unit_source_mode(row: dict[str, Any], config_summary: dict[str, Any]) -> str:
    if row.get("IsClient") is True:
        return "client_or_visual"
    if row.get("DestroyOnEnterBattle") is True:
        return "destroy_on_enter_battle"
    if config_summary.get("config_readable") is not True:
        return "config_missing"
    group_name = str(config_summary.get("group_config_name") or "")
    markers = config_summary.get("adventure_or_maze_markers")
    if group_name in {"FollowUnit", "FollowField", "Field"} or (isinstance(markers, list) and markers):
        return "adventure_or_maze"
    if row.get("IsTeamSummon") is True or config_summary.get("has_skill_config") is True:
        return "battle_runtime_candidate"
    return "catalog_or_scene"


def _summon_unit_blocked_reason(row: dict[str, Any], config_summary: dict[str, Any]) -> str:
    source_mode = _summon_unit_source_mode(row, config_summary)
    if source_mode == "client_or_visual":
        return "summon_unit_client_only_not_combat_runtime"
    if source_mode == "destroy_on_enter_battle":
        return "summon_unit_destroy_on_enter_battle_not_battle_spawn"
    if source_mode == "config_missing":
        return "summon_unit_config_missing"
    if source_mode == "adventure_or_maze":
        return "summon_unit_adventure_or_maze_not_combat_runtime"
    if source_mode == "catalog_or_scene":
        return "summon_unit_catalog_or_scene_not_battle_trigger"
    return "summon_unit_battle_admission_source_missing"


def _summon_unit_battle_admission(
    row: dict[str, Any],
    config_summary: dict[str, Any],
    blocked_reason: str,
) -> dict[str, Any]:
    source_mode = _summon_unit_source_mode(row, config_summary)
    return {
        "admission_status": "blocked",
        "blocked_reason": blocked_reason,
        "source_mode": source_mode,
        "catalog_not_trigger": source_mode in {"catalog_or_scene", "client_or_visual", "destroy_on_enter_battle", "adventure_or_maze"},
        "runtime_spawn_requires_explicit_intent": True,
        "raw_flags": _summon_unit_raw_flags(row),
        "config_markers": {
            "group_config_name": str(config_summary.get("group_config_name") or ""),
            "config_entity_path": str(config_summary.get("config_entity_path") or ""),
            "has_skill_config": config_summary.get("has_skill_config") is True,
            "has_ai_config": config_summary.get("has_ai_config") is True,
            "has_trigger_config": config_summary.get("has_trigger_config") is True,
            "has_resident_effects": config_summary.get("has_resident_effects") is True,
            "adventure_or_maze_markers": list(config_summary.get("adventure_or_maze_markers") or []),
        },
        "required_runtime_sources": {
            "battle_trigger": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_battle_trigger_source_absent",
            },
            "unit_profile": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_profile_source_absent",
            },
            "stats": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_stats_source_absent",
            },
            "position": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_position_source_absent",
            },
            "lifetime": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_lifetime_source_absent",
            },
            "targetability": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_targetability_source_absent",
            },
            "actionability": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_actionability_source_absent",
            },
        },
    }


def _summon_unit_raw_flags(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "is_client": row.get("IsClient") is True,
        "is_team_summon": row.get("IsTeamSummon") is True,
        "destroy_on_enter_battle": row.get("DestroyOnEnterBattle") is True,
        "remove_maze_buff_on_destroy": row.get("RemoveMazeBuffOnDestroy") is True,
        "max_summon_count": _optional_int(row.get("MaxSummonCount")),
        "unique_group": str(row.get("UniqueGroup") or ""),
    }


def _summon_unit_adventure_or_maze_markers(*, group_name: str, opcodes: tuple[str, ...]) -> list[str]:
    markers: list[str] = []
    if group_name in {"FollowUnit", "FollowField", "Field"}:
        markers.append(f"group_config:{group_name}")
    adventure_opcodes = {
        "AddMazeBuff",
        "RefreshMazeBuffTime",
        "AddAdventureModifier",
        "TriggerHitProp",
        "PropDestructReset",
        "RemoveEffect",
        "TriggerEffect",
    }
    for opcode in opcodes:
        if opcode in adventure_opcodes:
            markers.append(f"opcode:{opcode}")
    return list(dict.fromkeys(markers))


def _target_alias(value: Any) -> str | None:
    if isinstance(value, TargetExpressionNodeIR):
        return value.alias or None
    if isinstance(value, dict):
        alias = value.get("Alias") or value.get("alias")
        if isinstance(alias, str):
            return alias
    return None


def _value_field(value: Any) -> Any:
    if isinstance(value, dict) and "Value" in value:
        return _json_safe(value.get("Value"))
    return _json_safe(value)


def _first_present_key(value: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in value:
            return key
    return ""


def _numeric_expr_summary(value: Any) -> dict[str, Any]:
    if is_typed_numeric_expression(value):
        return dict(value)
    return lower_numeric_expression(value)


def _fixed_expr_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and value.get("kind") == "fixed" and isinstance(value.get("value"), (int, float)):
        return float(value["value"])
    return None


def _postfix_expr_fixed_value(postfix: dict[str, Any]) -> float | None:
    dynamic_hashes = postfix.get("DynamicHashes")
    if isinstance(dynamic_hashes, list) and dynamic_hashes:
        return None
    fixed_values = postfix.get("FixedValues")
    if not isinstance(fixed_values, list):
        return None
    opcodes = postfix.get("OpCodes")
    if not isinstance(opcodes, str) or not opcodes:
        return None
    try:
        decoded = list(base64.b64decode(opcodes))
    except Exception:
        return None
    stack: list[float] = []
    index = 0
    ended = False
    while index < len(decoded):
        opcode = decoded[index]
        if opcode == 17:
            ended = True
            index += 1
            continue
        if opcode == 0:
            if index + 1 >= len(decoded):
                return None
            fixed_index = decoded[index + 1]
            if fixed_index >= len(fixed_values):
                return None
            value = _numeric_fixed_value_item(fixed_values[fixed_index])
            if value is None:
                return None
            stack.append(value)
            index += 2
            continue
        if opcode in {2, 3, 4, 5}:
            if len(stack) < 2:
                return None
            right = stack.pop()
            left = stack.pop()
            if opcode == 2:
                stack.append(left + right)
            elif opcode == 3:
                stack.append(left - right)
            elif opcode == 4:
                stack.append(left * right)
            elif opcode == 5:
                if right == 0:
                    return None
                stack.append(left / right)
            index += 1
            continue
        return None
    return stack[0] if ended and len(stack) == 1 else None


def _numeric_fixed_value_item(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and isinstance(value.get("Value"), (int, float)):
        return float(value["Value"])
    return None


def _numeric_expr_can_be_runtime_bound(value: Any) -> bool:
    if _fixed_expr_value(value) is not None:
        return True
    if is_typed_numeric_expression(value) and isinstance(value, dict):
        if value.get("kind") == "dynamic_hash" and value.get("hash") is not None:
            return True
        if value.get("kind") == "program" and value.get("supported") is True:
            return True
    return False


def _break_damage_blocked_reason(scaling_expr: dict[str, Any]) -> str:
    reason = scaling_expr.get("reason")
    kind = scaling_expr.get("kind")
    if isinstance(reason, str) and reason:
        return f"break_damage_percentage_not_executable:{kind}:{reason}"
    if kind == "dynamic_hash":
        return "break_damage_formula_not_admitted:break_base_damage_inputs_missing"
    if kind == "fixed":
        return "break_damage_formula_not_admitted:break_base_damage_formula_missing"
    return f"break_damage_percentage_not_executable:{kind or 'unknown'}"


def _super_break_blocked_reason(scaling_expr: dict[str, Any]) -> str:
    reason = scaling_expr.get("reason")
    kind = scaling_expr.get("kind")
    if isinstance(reason, str) and reason:
        return f"super_break_percentage_not_executable:{kind}:{reason}"
    return f"super_break_percentage_not_executable:{kind or 'unknown'}"


def _is_super_break_attack_property(attack_property: dict[str, Any], *, template_name: str) -> bool:
    formula_type = str(attack_property.get("FormulaType") or "")
    final_formula_type = str(attack_property.get("FinalFormulaType") or "")
    display = attack_property.get("DisplayData")
    display_element = str(display.get("ElementDamageType") or "") if isinstance(display, dict) else ""
    return (
        template_name in {"DealSuperBreakDamage", "BeingDealSuperBreakDamage"}
        and formula_type == "ByBreakDamage"
        and (final_formula_type == "ByPureDamage" or display_element == "Super")
    )


def _display_element_type(attack_property: dict[str, Any]) -> str | None:
    display = attack_property.get("DisplayData")
    if not isinstance(display, dict):
        return None
    element = display.get("ElementDamageType")
    return str(element) if isinstance(element, str) and element else None


def _attack_property_element_type(attack_property: dict[str, Any]) -> str | None:
    damage_type = attack_property.get("DamageType")
    if isinstance(damage_type, dict):
        element = damage_type.get("DamageType")
        if isinstance(element, str) and element:
            return element
    return _display_element_type(attack_property)


def _attack_property_custom_name(payload: dict[str, Any]) -> str:
    attack_property = payload.get("AttackProperty")
    if not isinstance(attack_property, dict):
        return ""
    value = _value_field(attack_property.get("CustomName"))
    return value if isinstance(value, str) else ""


def _attack_property_damage_tags(
    payload: dict[str, Any],
    registry: dict[int, tuple[dict[str, Any], ...]],
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...], str]:
    attack_property = payload.get("AttackProperty")
    if not isinstance(attack_property, dict) or "DamageTag" not in attack_property:
        return (), (), ""
    lowered = _typed_damage_tag_list(attack_property.get("DamageTag"), registry)
    tags: list[str] = []
    sources: list[dict[str, Any]] = []
    for item in lowered:
        blocked_reason = item.get("blocked_reason")
        if isinstance(blocked_reason, str) and blocked_reason:
            return (), (), f"damage_emission_tag_not_lowered:{blocked_reason}"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return (), (), "damage_emission_tag_name_missing"
        if name in tags:
            return (), (), "damage_emission_tag_duplicate"
        tags.append(name)
        sources.append(
            {
                "index": item.get("index"),
                "name": name,
                "enum_index": item.get("enum_index"),
                "enum_value": item.get("enum_value"),
                "source_mode": item.get("source_mode"),
                "enum_source": item.get("source"),
                "raw_path": f"AttackProperty.DamageTag[{item.get('index')}]",
            }
        )
    return tuple(tags), tuple(sources), ""


def _iter_task_tree(value: Any, *, prefix: str) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(value, list):
        return result
    for index, task in enumerate(value):
        if not isinstance(task, dict):
            continue
        path = f"{prefix}[{index}]"
        result.append((path, task))
        for child_key in ("TaskList", "SuccessTaskList", "FailedTaskList"):
            child = task.get(child_key)
            if isinstance(child, list):
                result.extend(_iter_task_tree(child, prefix=f"{path}.{child_key}"))
    return result


def _safe_id(value: str) -> str:
    return (
        value.replace("[", "_")
        .replace("]", "")
        .replace(".", "_")
        .replace(":", "_")
        .replace("/", "_")
    )


def _postfix_expr_is_admitted(postfix: dict[str, Any]) -> bool:
    opcodes = postfix.get("OpCodes")
    if not isinstance(opcodes, str) or not opcodes:
        return False
    try:
        decoded = list(base64.b64decode(opcodes))
    except Exception:
        return False
    fixed_values = postfix.get("FixedValues")
    dynamic_hashes = postfix.get("DynamicHashes")
    fixed_count = len(fixed_values) if isinstance(fixed_values, list) else 0
    dynamic_count = len(dynamic_hashes) if isinstance(dynamic_hashes, list) else 0
    stack_size = 0
    index = 0
    ended = False
    while index < len(decoded):
        opcode = decoded[index]
        if opcode == 17:
            ended = True
            index += 1
            continue
        if opcode == 0:
            if index + 1 >= len(decoded) or decoded[index + 1] >= fixed_count:
                return False
            stack_size += 1
            index += 2
            continue
        if opcode == 1:
            if index + 1 >= len(decoded) or decoded[index + 1] >= dynamic_count:
                return False
            stack_size += 1
            index += 2
            continue
        if opcode in {2, 3, 4, 5}:
            if stack_size < 2:
                return False
            stack_size -= 1
            index += 1
            continue
        return False
    return ended and stack_size == 1


def _mechanism_bar_has_fixed_payload(standard: dict[str, Any]) -> bool:
    if standard.get("state") is not None or standard.get("active") is not None:
        return True
    return _fixed_expr_value(standard.get("current_count")) is not None or _fixed_expr_value(standard.get("max_count")) is not None


def _mechanism_bar_has_runtime_payload(standard: dict[str, Any]) -> bool:
    if standard.get("state") is not None or standard.get("active") is not None:
        return True
    return _numeric_expr_can_be_runtime_bound(standard.get("current_count")) or _numeric_expr_can_be_runtime_bound(standard.get("max_count"))


def _task_damage_family(value: dict[str, Any], opcode: str) -> str:
    attack_type = str(value.get("AttackType") or "")
    formula_type = str(value.get("FormulaType") or "")
    if attack_type == "ElationDamage" or formula_type == "ByElationDamage":
        return "elation"
    if attack_type == "TrueDamage":
        return "true_damage"
    if opcode in {"LoseHPByRatio", "DirectlyLoseHp", "DirectlyLoseHpHit"}:
        return "hp_loss"
    return "unknown"


def _damage_behavior_family(template_name: str) -> str:
    if template_name == "TrueDamage":
        return "true_damage"
    if template_name in {"DirectlyLoseHp", "DirectlyLoseHpHit"}:
        return "hp_loss"
    return "unknown"


def _damage_family_evidence(
    task: dict[str, Any],
    opcode: str,
    source: IRSource,
    parent_id: str,
) -> list[FormulaIR]:
    family = _task_damage_family(task, opcode)
    if family == "unknown":
        return []
    property_name = {
        "elation": "ElationDamage",
        "true_damage": "TrueDamage",
        "hp_loss": opcode,
    }[family]
    return [
        FormulaIR(
            formula_id=f"formula:{parent_id}:damage_family:{family}",
            kind="mechanic_property",
            expression={
                "mechanic": f"{family}_damage",
                "property": property_name,
                "damage_formula_family": family,
                "source_mode": "mainline",
                "bypasses_normal_multipliers": family in {"true_damage", "hp_loss"},
                "runtime_status": "executable" if family in {"true_damage", "hp_loss"} else "blocked",
                "blocked_reason": "Elation damage formula is not executable in v0_208"
                if family == "elation"
                else "",
            },
            source=source,
            coverage_status="blocked" if family == "elation" else "lowered",
        )
    ]


def _status_callback_runtime_payload(
    task: dict[str, Any],
    *,
    source_modifier_name: str = "",
) -> dict[str, JSONValue]:
    """Project only typed fields consumed by status callback runtime."""

    payload: dict[str, JSONValue] = {"schema_version": "hsr.status_callback_task_payload.v1"}
    for key in (
        "BaseTypeKind",
        "BehaviorFlag",
        "ContextScope",
        "DynamicKey",
        "DynamicFloatSet",
        "FromDynamicKey",
        "FromModifierName",
        "ModifierName",
        "Property",
        "ToDynamicKey",
        "ValueType",
        "WeaknessFilter",
        "VariateType",
        "ModifyFunction",
    ):
        value = task.get(key)
        if isinstance(value, dict) and "Value" in value:
            value = value.get("Value")
        if value is None or isinstance(value, (bool, int, float, str)):
            payload[key] = value
    for key in (
        "BaseTypeSourceTarget",
        "FromTargetType",
        "ReadTargetType",
        "TargetType",
        "ToTargetType",
        "WriteTargetType",
        "Attacker",
        "CasterFilter",
    ):
        payload[key] = _target_alias(task.get(key)) or ""
    for key in ("AliveOnly",):
        if isinstance(task.get(key), bool):
            payload[key] = task[key]
    if source_modifier_name:
        payload["source_modifier_name"] = source_modifier_name
    base_type_list = task.get("BaseTypeList")
    if isinstance(base_type_list, list) and all(
        isinstance(item, str) for item in base_type_list
    ):
        payload["BaseTypeList"] = list(base_type_list)
    behavior_flag_filter = task.get("BehaviorFlagFilter")
    if isinstance(behavior_flag_filter, list) and all(
        isinstance(item, str) and item for item in behavior_flag_filter
    ):
        payload["BehaviorFlagFilter"] = list(behavior_flag_filter)
    if "Value" in task and not isinstance(task.get("Value"), str):
        payload["Value"] = lower_numeric_expression(task.get("Value"))
    elif isinstance(task.get("Value"), str):
        payload["SourceProperty"] = task["Value"]
    if "PropertyValue" in task:
        payload["PropertyValue"] = lower_numeric_expression(
            task.get("PropertyValue")
        )
    if "NewValue" in task:
        payload["NewValue"] = lower_numeric_expression(task.get("NewValue"))
    for key in (
        "AddNormalizedValue",
        "Healer_HealRatio",
        "MaxLoopCount",
        "MaxNumber",
        "ModifyValue",
        "NormalizedValue",
    ):
        if key in task:
            payload[key] = lower_numeric_expression(task.get(key))
    odds_list = task.get("OddsList")
    if isinstance(odds_list, list):
        payload["OddsList"] = [lower_numeric_expression(item) for item in odds_list]
    for key in ("ByRandom", "IncludeLimbo", "DoReset", "Floor"):
        if isinstance(task.get(key), bool):
            payload[key] = task[key]
    return payload


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _raw_structure_references_text(value: Any, expected: str) -> bool:
    if isinstance(value, dict):
        return any(
            _raw_structure_references_text(item, expected)
            for item in value.values()
        )
    if isinstance(value, list):
        return any(_raw_structure_references_text(item, expected) for item in value)
    return value == expected


def _equipment_reachable_modifier_names(
    document: Any,
    ability_index: int,
) -> frozenset[str]:
    """Return modifier definitions reachable from one raw equipment ability row.

    Modifier dictionaries are declarations, not implicit startup behavior.  A
    definition becomes part of the gameplay graph only when the ability body or
    another already-reachable definition names it.  The traversal deliberately
    compares exact raw string identities and does not infer reachability from an
    event family or from the mere presence of a definition.
    """

    if not isinstance(document, dict):
        return frozenset()
    ability_list = document.get("AbilityList")
    if (
        not isinstance(ability_list, list)
        or isinstance(ability_index, bool)
        or not isinstance(ability_index, int)
        or ability_index < 0
        or ability_index >= len(ability_list)
    ):
        return frozenset()
    ability = ability_list[ability_index]
    if not isinstance(ability, dict):
        return frozenset()

    definitions: dict[str, list[dict[str, Any]]] = {}
    for container in (
        ability.get("Modifiers"),
        document.get("ModifierMap"),
        document.get("GlobalModifiers"),
    ):
        if not isinstance(container, dict):
            continue
        for raw_name, raw_definition in container.items():
            if isinstance(raw_name, str) and raw_name and isinstance(raw_definition, dict):
                definitions.setdefault(raw_name, []).append(raw_definition)
    if not definitions:
        return frozenset()

    ability_root = {
        key: value
        for key, value in ability.items()
        if key != "Modifiers"
    }
    templates: dict[str, list[Any]] = {}
    raw_templates = document.get("GlobalTemplates")
    if isinstance(raw_templates, list):
        for raw_template in raw_templates:
            if not isinstance(raw_template, dict):
                continue
            name = raw_template.get("Name")
            if isinstance(name, str) and name:
                templates.setdefault(name, []).append(raw_template)
    elif isinstance(raw_templates, dict):
        for name, raw_template in raw_templates.items():
            if isinstance(name, str) and name and isinstance(raw_template, (dict, list)):
                templates.setdefault(name, []).append(raw_template)

    reachable: set[str] = set()
    reached_templates: set[str] = set()
    pending: list[Any] = [ability_root]
    while pending:
        current = pending.pop()
        for candidate, candidate_definitions in definitions.items():
            if candidate in reachable:
                continue
            if _raw_structure_references_text(current, candidate):
                reachable.add(candidate)
                pending.extend(candidate_definitions)
        for candidate, candidate_templates in templates.items():
            if candidate in reached_templates:
                continue
            if _raw_structure_references_text(current, candidate):
                reached_templates.add(candidate)
                # Ambiguous template identities must not make otherwise
                # unreachable modifier definitions executable.
                if len(candidate_templates) == 1:
                    pending.append(candidate_templates[0])
    return frozenset(reachable)


def _json_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _iter_postfix_expr(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        expr = value.get("PostfixExpr")
        if isinstance(expr, dict):
            found.append(expr)
        for nested in value.values():
            found.extend(_iter_postfix_expr(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_postfix_expr(nested))
    return found


def _iter_fixed_values(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        fixed = value.get("FixedValue")
        if isinstance(fixed, dict) and "Value" in fixed:
            found.append(fixed)
        for nested in value.values():
            found.extend(_iter_fixed_values(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_fixed_values(nested))
    return found


def _iter_elation_values(value: Any, path: tuple[str, ...] = ()) -> list[tuple[str, str, Any]]:
    found: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            child_path = (*path, str(key))
            if _is_elation_key(str(key)):
                found.append((".".join(child_path), str(key), nested))
            found.extend(_iter_elation_values(nested, child_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_iter_elation_values(nested, (*path, str(index))))
    return found


def _is_elation_key(key: str) -> bool:
    return key.startswith("Elation") or "ElationTime" in key
