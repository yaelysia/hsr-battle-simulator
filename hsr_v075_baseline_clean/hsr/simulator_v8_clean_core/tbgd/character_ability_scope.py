from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, cast

from ..immutable_json import freeze_json, thaw_json
from ..ir_types import IRSource, JSONValue
from ..rules.ir import (
    CharacterAbilityAdmissionStatus,
    CharacterAbilityExternalDependencyIR,
    CharacterAbilityFamilyIR,
    CharacterAbilityMaterializationRole,
    CharacterAbilityOccurrenceKind,
    CharacterAbilityProjectionIR,
    CharacterAbilityProjectionKind,
    CharacterAbilityProjectionScope,
    CharacterAbilityScope,
    CharacterAbilityScopeRecordIR,
    CharacterAbilitySemanticKind,
    CharacterAbilitySourceIR,
)


AVATAR_CONFIG_TABLES = (
    "ExcelOutput/AvatarConfig.json",
    "ExcelOutput/AvatarConfigLD.json",
)
AVATAR_ENHANCED_CONFIG_TABLE = "ExcelOutput/AvatarConfigEnhanced.json"
SHARED_CHARACTER_ABILITY_SOURCE = (
    "Config/ConfigAbility/Avatar/Avatar_Common_Ability.json"
)
DEFERRED_CHARACTER_BASE_TYPES = frozenset({"Memory", "Elation"})


def _names(value: str) -> frozenset[str]:
    return frozenset(value.split())


# This is the compiler fact source for opcode semantics. Effective scope is
# computed separately from the complete enclosing branch.
_SEMANTIC_OPCODE_GROUPS: dict[CharacterAbilitySemanticKind, frozenset[str]] = {
    "ai_excluded": _names(
        "AITryInsertUltra AutoUseUltraSkill StackAIUpperGroupForSpecified "
        "StackCrazyAIBehavior"
    ),
    "battle_data_projection": _names(
        "SetEnergyBarState SetSummonerEnergyBarState "
        "SetExcludeInMultiCharacterFormation"
    ),
    "build_resolution": _names(
        "ByIsGenderType ByRankActivated BySkillPointActivated"
    ),
    "client_only_excluded": _names(
        "ByAnimatorParam ByCompareTargetCountClientOnly ByHasStanceWeakPreview "
        "ByIsAutoBattle ByIsBodyPartClientOnly ByPreShowStanceBreak "
        "BySimulateSpeedUp SetDynamicValueByPropertyClientOnly "
        "SetDynamicValueClientOnly TargetSortByCustomFormationIndexClientOnly"
    ),
    "combat_condition": _names(
        "ByAnd ByAny ByAttackType ByAvatarBaseType ByCasterAliveOrLimbo "
        "ByCharacterDamageType ByCheckModifierCallBackBehaviorFlag "
        "ByCheckModifierCallBackModifierValue ByCheckModifierCallBackName "
        "ByCheckModifierCallBackStatusType ByCompareAbilityProperty ByCompareBP "
        "ByCompareBattleEventID ByCompareChangeValue ByCompareCharacterID "
        "ByCompareCharacterNumber ByCompareCurrentSkillEffectIsDamaging "
        "ByCompareDamageCustomName ByCompareDamageTag ByCompareHP "
        "ByCompareHPRatio ByCompareModifierValue ByCompareMonsterID "
        "ByCompareMonsterRank ByCompareMonsterUniqueID "
        "ByCompareNextUnusedInsertAction ByCompareParamString "
        "ByCompareParamValue ByCompareResistChance ByCompareSPChangeTag "
        "ByCompareSPRatio ByCompareSomatoType ByCompareSpecialSPRatio "
        "ByCompareStance ByCompareStanceCount ByCompareStanceRatio "
        "ByCompareTarget ByCompareTargetCount ByCompareTeamFormationWidth "
        "ByCompareTurnActionEntityTeamType ByCompareUnusedInsertAbilityCount "
        "ByCompareUnusedUltraSkillCount ByCompareWaveCount "
        "ByContainBehaviorFlag ByContainsParamFlag ByContainsRedStance "
        "ByCurrentSkillName ByCurrentSkillTargetType ByCurrentSkillType "
        "ByDamageSourceContainBehaviorFlag ByDistance "
        "ByHasInsertActionByTarget ByHasStanceWeak ByHasSummonRelation "
        "ByHaveEnemyAlive ByIsBattleEventEntity ByIsBodyPart "
        "ByIsBodyPartOwner ByIsContainModifier ByIsCurrentSkillActive "
        "ByIsDamageCritical ByIsDamageType ByIsEnemy "
        "ByIsFirstInsertAbilityInQueue ByIsInCharmAction ByIsInsertAction "
        "ByIsPropertyValueMinOrMax ByIsSplitDamage "
        "ByIsSubTargetOfHpSharedGroup ByIsTargetUnselectable ByIsTargetValid "
        "ByIsTeammate ByIsTurnActionEntity ByIsTurnOwnerEntity ByNot "
        "ByRandomChance ByTargetAliveState ByTargetEntityType "
        "ByTargetIsStanceWeak ByTargetListAll ByTargetListAny "
        "ByTargetListIntersects ByTargetTeam ByTurnOwnerActionPhaseEnd "
        "ByTurnOwnerHasActionInTurn ByTurnOwnerHasPendingOneMore"
    ),
    "combat_control_flow": _names(
        "ByCompareDynamicValue ConditionLoopExecuteTaskList "
        "ConditionLoopExecuteTaskListWithInterval FireMultiProjectiles "
        "FireProjectile FireWaveProjectile GoNextTargetInList "
        "IncludeGlobalTaskListTemplate IncludeTaskListTemplate "
        "LoopExecuteTaskList LoopExecuteTaskListWithInterval LoopTargetList "
        "MakeSuccess NewFireProjectile PredicateTaskList RandomConfig "
        "SwitchByCommandType SwitchCaseByAttackDamageType "
        "SwitchCaseByDynamicValue TriggerAbility TriggerParallelAbility "
        "TriggerParallelTaskListTemplate TriggerSkipDeadHandler "
        "TurnInsertAbilityCondition"
    ),
    "combat_decode_required": _names(
        "FFMONJGCKDI IKDAKCBKFAB LAJIKDENEOO LAPKGFCDPCD LPMGDCDFOOE "
        "NKLOMENKLHK"
    ),
    "combat_runtime": _names(
        "AddBehaviorFlagForModifier AddModifier AddRegardAsAttackType "
        "AddWeakByTeamAttackType AddWeakness AttachEntityDeparted "
        "AttachEntityUnselectable AttachSkillTypeDisable "
        "ChangeBattleEventOwner ChangeCharacterConfigParam ChangeCharacterRowData "
        "CharacterChangePhase ClearRegardAsAttackType CreateBattleEvent "
        "CreateServant DamageByAttackProperty DamageStance DefineDynamicValue "
        "DispelStatus EnableNegativeHP ForceKill HealHP HitDamageSplit "
        "InfectModifier InitShield LockActionDelayChange LockTargetHP LoseHP "
        "LoseHPByRatio ModifyActionDelay ModifyAddModifierBindValue "
        "ModifyCurrentSkillDelayCost ModifyDamageData ModifyEntityBoostPoint "
        "ModifyHealData ModifyProperty ModifySP ModifySPNew "
        "ModifySkillPropertyByName ModifySkillPropertyByType ModifySpecialSP "
        "ModifyTeamBoostPoint ModifyTeamBoostPointMax OwnerEntityAddAbility "
        "ProcessModifierLifeStep RandomSelectDynamicValue "
        "RedirectActionDelayChange ReinitProperty Remodifier "
        "RemoveBehaviorFlagForModifier RemoveModifier "
        "RemoveModifierByBehaviorFlag RemoveSelfModifier RemoveShield "
        "ResetActionDelay Retarget SetActionDelay SetActionDelayNearTarget "
        "SetControlSkillMapping SetDieImmediately SetDynamicValue "
        "SetDynamicValueByAddValue SetDynamicValueByAdsorption "
        "SetDynamicValueByAttackTargetCount SetDynamicValueByBPChange "
        "SetDynamicValueByBreakBaseDamage SetDynamicValueByChangeValue "
        "SetDynamicValueByCharacterCount SetDynamicValueByCopying "
        "SetDynamicValueByCountOfBaseType SetDynamicValueByCurrentBP "
        "SetDynamicValueByDamageDataProperty SetDynamicValueByHPRatio "
        "SetDynamicValueByHealDataProperty SetDynamicValueByMaxBP "
        "SetDynamicValueByModifierValue SetDynamicValueByPreCalcStanceDamage "
        "SetDynamicValueByProperty SetDynamicValueByRandom "
        "SetDynamicValueByShield SetDynamicValueBySkillProperty "
        "SetDynamicValueByStatusCount SetDynamicValueByStatusResistance "
        "SetDynamicValueByVariateType SetDynamicValueByWeaknessCount "
        "SetEntityActionState SetHP SetModifierDynamicValue SetModifierValue "
        "SetModifierValueByBehaviorFlag SetPhainonActionCount "
        "SetPhainonChargePoint SetResilience StackCustomUnselectable "
        "StackProperty StackRedStance StackShield StackStatusResistance "
        "StackWeakness TriggerModifierCustomEvent TurnInsertAbility "
        "TurnInsertAction UnlockTargetHP UseSkillOneMore"
    ),
    "contextual_data": _names(
        "AttackData LinearProjectileData RandomSelectInTargetList "
        "RandomTraceProjectileData SetDynamicValueInRange "
        "SortByModifierDynamicFloat SortTargets TargetAlias TargetCompute "
        "TargetConcat TargetFetchCaster TargetFetchCurrentInsertTurnSource "
        "TargetFetchPartner TargetFilter TargetFilterAliveState "
        "TargetFilterTargetType TargetMapAdjoinEntity TargetMapAllTeamMember "
        "TargetMapPartOwnerEntity TargetMapSkillPointEntity "
        "TargetMapTeamFormation TargetQuery TargetSelector TargetSequence "
        "TargetShuffle TargetSortByElationPriority TargetSortByFormation "
        "TargetSortByModifierStatusCount TargetSortByModifierValue "
        "TargetSortByProperty TargetSortMonsterRank TargetTake"
    ),
    "environment_input": _names(
        "ByInTurnBasedGameModeState ByIsMazeSkillAffectCurrentWave "
        "ByIsStageFirstWave SetDynamicValueByWaveStageCount "
        "SetDynamicValueByWorldLevel"
    ),
    "input_control_projection": _names(
        "SetDeathDragonSkillButtonState SetTeamLockTarget "
        "SetUseTemporaryLockTarget"
    ),
    "presentation_only": _names(
        "AddBuffPerform AddEntityToTeamFormation "
        "AddGlobalDynamicOffsetIgnoreEntity AddTargetStancePreshowConfig "
        "AlignTargetToTeamCenter AnimSetParameter ApplyOperation "
        "AttachPreshowDamageTypeForSkill BattleAudioSwitch BattlePlayVideo "
        "BattleSingleClickQTEConfig CameraFollowEntityTimeScale "
        "ChangeActionEntityToObserveState ChangeCharacterUIDisplay "
        "ChangeSkillUIDisplay CharacterChangeModel CharacterDisableLookAt "
        "CharacterPlayVO CharacterReactionAnimConfig "
        "CharacterReplaceAnimatorController ClearEntityDamageText "
        "ClearEntityFollowAttachPoint ClearFormationFaceDeltaRecord "
        "ClearTargetTimeSlow CreateAttachPoint DisableCharacterVO "
        "EnableEmotion EnableFieldEffectSoftZOffset EnableHugeMonsterHalfDither "
        "EnableSpecificModifierSpecialMark FindClosestAttachPoint "
        "FrameCaptureIfNeed GlobalMainIntensityEffect "
        "GlobalMainIntensityEffectAutoRevert GlobalTimeSlow HeadLookAt "
        "HideCharacterFilteredEffect HideEntityForCurrentCamera "
        "HideEntityInActionBarByDelay HideFieldEffect HideLevelStage "
        "HideModifierEffect LevelAudioState LevelAudioSwitch LockAnimatorSpeed "
        "LookAt MakeCharacterHUDVisible ModifierAttachEffect "
        "ModifierDetachEffect ModifierOverrideOnHitEffect "
        "ModifyCharacterOutlineTargetRender MoveStageOnTargetForward MoveTeam "
        "MoveToTargetList MoveToTargetPosition OverrideSelectDarkTeamEntityCamera "
        "OverrideSkillReadyCamera OverrideSkillReadyState PauseEntityFollowAttach "
        "PlayCrossHairPreviewFadeIn PlayScreenTransfer PlayTimeline "
        "PreloadBattleEventByID RPGColorGradingCurveEffect RadialBlurEffect "
        "RefreshQingQueEnergyBarState RefreshWeaknessUI "
        "ReleaseCharacterHUDVisibleControl ReleaseEnvProfile RemoveEffect "
        "RemoveEntityFromTeamFormation RemoveGlobalTimeSlow "
        "ResetBattleBGMToStage ResetCharacterCustomTeamFormation "
        "ResetHeadLookAt RevertActionEntityToObserveState ScaleCharacterModel "
        "SetActionBarItemAnimatorTrigger SetAttachmentScale "
        "SetAttachmentVisibility SetBattleBGMState SetBattleUIPanelState "
        "SetCameraRootFollow SetCharacterAnimFollow "
        "SetCharacterCustomTeamFormation SetCharacterEnhancedState "
        "SetCharacterFormation SetCharacterPartsVisibility "
        "SetCharacterScaleFollow SetCharacterShowSummonUI "
        "SetCharacterVisibilityFollow SetCharacterVisibleInViewMode "
        "SetColliderCenterFollowAttachPoint SetComponentAssetLoadState "
        "SetCustomLocationConfig SetDeathDragonLinjian "
        "SetDynamicAttachPointEffectAdaptionConfig "
        "SetDynamicValueByFormationIndex "
        "SetDynamicValueByTargetToTeamCenterDistance SetEffectAnimatorParameter "
        "SetEffectAnimatorState SetEffectAnimatorTrigger "
        "SetEffectAutoLayoutScale SetEffectFrameCaptureMatTex "
        "SetEffectProgress SetEntityFollowAttachPoint SetEntityForceVisible "
        "SetEntityPosition SetEntityVisible SetGlobalShaderProperty "
        "SetHeadButtonEff SetHpBreakHint SetLayerWeight "
        "SetModifierEffectVisible SetModifierOverrideNameForStatus "
        "SetNoShadowCaster SetPhainonChargePointPreshow SetShenJunActionBar "
        "SetSimulationSpeedEnable SetSkillButtonAdditionalStatus "
        "SetSkillTargetFormationByPos SetStanceHintEffect "
        "SetTargetAssetPreloadState SetTargetCrossHairVisible "
        "SetTargetCustomAssetPreloadState SetTargetDamageTextVisible "
        "SetTeamFormation SetTeamRootOffset SetUltraSkillAssetPreload "
        "SetViewModeEnabled ShowActionBarEffect ShowAttackTime "
        "ShowAvatarHUDSpecialEffect ShowBattleAvatarPanel ShowBattleQTEUI "
        "ShowBattleScreenEffect ShowBattleSkillEnhanced ShowBattleUI "
        "ShowBonusUIEffect ShowEntityFloatMessage ShowSkillReadyCamera "
        "ShowSkillTextDialog ShowUIPage ShowUltraSkillAlternative "
        "SkipPopupUIOffset StackSkillDesc StackStatusDesc StartAim "
        "StartBattleQTE StopAim StopEffectFollow StopTimeline SummonPartner "
        "SwitchBattleArea SwitchCaseByTeammateCount SyncCharLightAndCameraDir "
        "TargetTimeSlow TeamLookAt ToggleSkillPreShow ToggleSpecialSkillMark "
        "ToggleUITop TransitEnvProfile TriggerAdditiveAnimState "
        "TriggerAnimState TriggerAnimStateWithMove "
        "TriggerAutoLayoutTransferPerform TriggerCustomString TriggerEffect "
        "TriggerEffectList TriggerEnergyBarEffect TriggerSound "
        "TriggerSoundInAnim TriggerUINotify TriggerUINotifyWithTarget "
        "TryStartConnectUltraSkillFrameCapture VCameraConfigChange "
        "VCameraNoiseChange"
    ),
    "simulation_sequence": _names(
        "ByDieAnimFinished DamagePerformFinish PerformDelayExecute "
        "SkillPerformFinish WaitAnimState WaitFor WaitFrame "
        "WaitFrameForBattleServer WaitParallelTimeStamp WaitSecond "
        "WaitSkillPerformAbilityFinish WaitTimelineFinish"
    ),
    "telemetry_excluded": _names(
        "DebugLog WriteCustomValueToStatistic"
    ),
}


COMBAT_EVENT_FAMILIES = _names(
    "CheckParamFlagCallBack OnActionEnd OnActionPhaseBegin OnAddModifierSuc "
    "OnAfterAction OnAfterAttack OnAfterAttackEnd OnAfterBeingAttacked "
    "OnAfterBeingHeal OnAfterBeingHit OnAfterBeingHitAll OnAfterCharmAction "
    "OnAfterDealHeal OnAfterHit OnAfterHitAll OnAfterSkillUse OnAllowAction "
    "OnAttackerPrepareDamageData OnBeforeAction OnBeforeAttack "
    "OnBeforeBeingAttacked OnBeforeBeingBreak OnBeforeBeingHit "
    "OnBeforeBeingHitAll OnBeforeBeingStanceDamage OnBeforeDealHeal "
    "OnBeforeDeathrattle OnBeforeDying OnBeforeEscape OnBeforeHit "
    "OnBeforeHitAll OnBeforeInsertActionPrepare OnBeforeSkillUse OnBeingBreak "
    "OnBeingLimbo OnBeingRevived OnBeingStackWeakness OnBeingStanceDamage "
    "OnBreakExtendAnim OnCreate OnCriticalChanceChange OnCustomEvent "
    "OnDefenderPrepareAttackData OnDepartedEnd OnDepartedStart OnDestroy "
    "OnDispel OnEndBreak OnEnergyPointChange OnEnterBattle OnEnterRedStance "
    "OnHPChange OnImmuneDebuff OnInsertAbilityFinish OnInsertAbilityStart "
    "OnInsertActionFinish OnInsertActionStart OnLeaveBattle OnLimboWaitHeal "
    "OnListenActionEnd OnListenActionPhaseBegin OnListenAfterAction "
    "OnListenAfterAttack OnListenAfterAttackEnd OnListenAfterBeingHitAll "
    "OnListenAfterHitAll OnListenAfterSkillUse OnListenAllowAction "
    "OnListenAvatarBaseTypeChange OnListenBattleEventCreate "
    "OnListenBattleEventDie OnListenBeforeAction OnListenBeforeAttack "
    "OnListenBeforeBeingHit OnListenBeforeHitAll OnListenBeforeSkillUse "
    "OnListenBeforeTurnPhase1End OnListenBpChange OnListenBreak "
    "OnListenCharacterCreate OnListenCharacterDie OnListenCharacterEscape "
    "OnListenCharacterLimbo OnListenCharmDamagePerformFinish "
    "OnListenCharmMakeDamage OnListenEndBreak "
    "OnListenForceProcessModifierLifeStep OnListenHPChange OnListenInitShield "
    "OnListenInsertAbilityAbort OnListenInsertAbilityFinish "
    "OnListenInsertAbilityStart OnListenInsertActionFinish "
    "OnListenInsertActionStart OnListenInsertUltraSkill OnListenModifierAdd "
    "OnListenModifierOnStack OnListenModifierRemove OnListenRevive "
    "OnListenTurnBegin OnListenTurnEnd OnListenTurnPhase1Begin "
    "OnListenTurnPhase2Begin OnListenUltraSkillPrepare OnModifierAdd "
    "OnModifierDotAdd OnModifierOnStack OnModifierRemove OnOwnerChanged "
    "OnPhase1 OnPhase2 OnRedStanceBeingBreak OnSPChange OnSnapshotCreate "
    "OnStack OnTeamMemberRemove OnTriggerBreak OnTriggerDeath "
    "OnTriggerDeathrattle OnTriggerRedStanceBreak OnTriggerStanceCountDown "
    "OnUltraSkillPrepare OnUnselectableEnd OnUnselectableStart OnWaveMonster"
)


STRUCTURAL_ENTRY_KINDS: dict[str, CharacterAbilitySemanticKind] = {
    "OnAbilityPropertyChange": "combat_event",
    "OnAdd": "combat_event",
    "OnAfterHit": "combat_event",
    "OnChange": "combat_control_flow",
    "OnDynamicValueChange": "combat_event",
    "OnEnterRange": "combat_event",
    "OnExitRange": "combat_event",
    "OnInsertAbort": "combat_event",
    "OnNoNewWeak": "combat_control_flow",
    "OnProjectileHit": "combat_control_flow",
    "OnProjectileHitClientOnly": "client_only_excluded",
    "OnStart": "combat_control_flow",
    "OnSuccess": "combat_control_flow",
}


_NON_GAMEPLAY_KINDS = frozenset(
    {
        "presentation_only",
        "client_only_excluded",
        "ai_excluded",
        "telemetry_excluded",
    }
)
_TERMINAL_BRANCH_KINDS = frozenset(
    {
        *_NON_GAMEPLAY_KINDS,
        "build_resolution",
        "battle_data_projection",
        "input_control_projection",
        "environment_input",
        "combat_decode_required",
    }
)


def _validate_taxonomy() -> None:
    claimed: dict[str, CharacterAbilitySemanticKind] = {}
    for semantic_kind, opcodes in _SEMANTIC_OPCODE_GROUPS.items():
        for opcode in opcodes:
            prior = claimed.setdefault(opcode, semantic_kind)
            if prior != semantic_kind:
                raise RuntimeError(
                    f"character ability opcode scope conflict:{opcode}:{prior}:{semantic_kind}"
                )


_validate_taxonomy()
_OPCODE_SEMANTIC_KIND = {
    opcode: semantic_kind
    for semantic_kind, opcodes in _SEMANTIC_OPCODE_GROUPS.items()
    for opcode in opcodes
}


def character_ability_semantic_kind(family: str) -> CharacterAbilitySemanticKind | None:
    """Return the compiler taxonomy fact for one exact source family."""

    if not isinstance(family, str) or not family:
        raise ValueError("character ability family is required")
    return _OPCODE_SEMANTIC_KIND.get(family)


def character_control_flow_families() -> tuple[str, ...]:
    """Return semantic families eligible for P9 control-flow classification.

    The occurrence denominator still comes from the complete scope projection;
    structural containers must not be inferred to be typed task nodes.
    """

    return tuple(
        sorted(
            _SEMANTIC_OPCODE_GROUPS["combat_control_flow"]
            | _SEMANTIC_OPCODE_GROUPS["simulation_sequence"]
        )
    )


@dataclass(frozen=True)
class CharacterAbilityProjectionIssue:
    code: str
    subject: str
    detail: str = ""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str)
            or not self.code
            or not isinstance(self.subject, str)
            or not self.subject
            or not isinstance(self.detail, str)
        ):
            raise ValueError("character ability projection issue is invalid")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "code": self.code,
            "subject": self.subject,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CharacterAbilityDocumentProjection:
    scope_records: tuple[CharacterAbilityScopeRecordIR, ...]
    projections: tuple[CharacterAbilityProjectionIR, ...]
    families: tuple[CharacterAbilityFamilyIR, ...]
    issues: tuple[CharacterAbilityProjectionIssue, ...]
    discovered_occurrence_count: int
    observed_families: tuple[str, ...]

    def __post_init__(self) -> None:
        typed_collections = (
            ("scope_records", tuple(self.scope_records), CharacterAbilityScopeRecordIR),
            ("projections", tuple(self.projections), CharacterAbilityProjectionIR),
            ("families", tuple(self.families), CharacterAbilityFamilyIR),
            ("issues", tuple(self.issues), CharacterAbilityProjectionIssue),
        )
        if any(
            type(item) is not expected_type
            for _, values, expected_type in typed_collections
            for item in values
        ):
            raise TypeError("character ability document projection contains invalid IR")
        scope_records = typed_collections[0][1]
        observed_families = tuple(self.observed_families)
        if (
            not isinstance(self.discovered_occurrence_count, int)
            or isinstance(self.discovered_occurrence_count, bool)
            or self.discovered_occurrence_count < len(scope_records)
        ):
            raise ValueError("invalid character ability discovery count")
        if (
            any(not isinstance(family, str) or not family for family in observed_families)
            or tuple(sorted(set(observed_families))) != observed_families
        ):
            raise ValueError("observed character ability families are not canonical")
        for name, values, _ in typed_collections:
            object.__setattr__(self, name, values)
        object.__setattr__(self, "observed_families", observed_families)


@dataclass(frozen=True)
class _SourceCandidate:
    avatar_id: str
    base_type: str
    relative_path: str
    config_source_path: str
    config_row_index: int
    selected_version: str
    source_kind: Literal["character_main", "character_shared"] = "character_main"

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, str) or self.source_kind not in {
            "character_main",
            "character_shared",
        }:
            raise ValueError("invalid character ability candidate source kind")
        if not isinstance(self.avatar_id, str):
            raise TypeError("character ability candidate avatar identity must be a string")
        if any(
            not isinstance(value, str) or not value
            for value in (
                self.base_type,
                self.relative_path,
                self.config_source_path,
                self.selected_version,
            )
        ):
            raise ValueError("character ability candidate metadata is incomplete")
        if self.source_kind == "character_main" and not self.avatar_id:
            raise ValueError("character ability candidate avatar identity is missing")
        if self.source_kind == "character_shared" and self.avatar_id:
            raise ValueError("shared character ability candidate has an avatar")
        if (
            not isinstance(self.config_row_index, int)
            or isinstance(self.config_row_index, bool)
            or self.config_row_index < 0
        ):
            raise ValueError("character ability candidate row index is invalid")

    def manifest_fields(self) -> tuple[str, ...]:
        return (
            self.source_kind,
            self.avatar_id,
            self.base_type,
            self.relative_path,
            self.config_source_path,
            str(self.config_row_index),
            self.selected_version,
        )


@dataclass(frozen=True)
class _CharacterAbilityInventoryManifest:
    inventory_bytes: Mapping[str, bytes]
    candidates: tuple[_SourceCandidate, ...] = field(init=False)

    def __post_init__(self) -> None:
        inventory = _freeze_bytes_mapping(self.inventory_bytes, "inventory_bytes")
        if set(inventory) != {
            *AVATAR_CONFIG_TABLES,
            AVATAR_ENHANCED_CONFIG_TABLE,
        }:
            raise ValueError("character ability inventory source set is incomplete")
        rows = {
            path: _load_json_rows_bytes(inventory[path], path)
            for path in (*AVATAR_CONFIG_TABLES, AVATAR_ENHANCED_CONFIG_TABLE)
        }
        candidates = _discover_source_candidates_from_rows(rows)
        if any(type(candidate) is not _SourceCandidate for candidate in candidates):
            raise TypeError("character ability inventory contains an invalid candidate")
        object.__setattr__(self, "inventory_bytes", inventory)
        object.__setattr__(self, "candidates", candidates)


@dataclass(frozen=True)
class CharacterAbilityRawSnapshot:
    inventory_manifest: _CharacterAbilityInventoryManifest
    source_bytes: Mapping[str, bytes]
    sources: tuple[CharacterAbilitySourceIR, ...]
    source_fingerprint: str
    fingerprint_kind: Literal["complete", "partial"]
    source_filter: tuple[str, ...]
    build_counters: Mapping[str, Any]
    documents: Mapping[str, Mapping[str, Any]] = field(init=False)
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        _require_sha256(self.source_fingerprint, "character ability fingerprint")
        if self.fingerprint_kind not in {"complete", "partial"}:
            raise ValueError("invalid character ability fingerprint kind")
        source_filter = _canonical_string_tuple(self.source_filter, "source_filter")
        if (self.fingerprint_kind == "complete") != (not source_filter):
            raise ValueError("character ability fingerprint completeness is inconsistent")
        if type(self.inventory_manifest) is not _CharacterAbilityInventoryManifest:
            raise TypeError("character ability inventory manifest is invalid")
        inventory = self.inventory_manifest.inventory_bytes
        candidates = self.inventory_manifest.candidates
        if any(type(candidate) is not _SourceCandidate for candidate in candidates):
            raise TypeError("character ability snapshot candidates are invalid")
        candidate_paths = tuple(candidate.relative_path for candidate in candidates)
        if (
            not candidates
            or candidate_paths != tuple(sorted(candidate_paths))
            or len(candidate_paths) != len(set(candidate_paths))
        ):
            raise ValueError("character ability candidate identities are not unique")
        available = set(candidate_paths)
        if source_filter and not set(source_filter).issubset(available):
            raise ValueError("character ability source filter is not closed")
        selected_paths = set(source_filter) if source_filter else available

        source_bytes = _freeze_bytes_mapping(self.source_bytes, "source_bytes")
        if set(source_bytes) != selected_paths:
            raise ValueError("character ability source byte selection is inconsistent")

        documents: dict[str, Mapping[str, Any]] = {}
        for path in sorted(source_bytes):
            try:
                document = json.loads(source_bytes[path])
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"character ability source unreadable:{path}") from exc
            if not isinstance(document, dict):
                raise ValueError(f"character ability source root is not an object:{path}")
            documents[path] = cast(Mapping[str, Any], freeze_json(dict(document)))

        source_values = tuple(self.sources)
        if any(type(source) is not CharacterAbilitySourceIR for source in source_values):
            raise TypeError("character ability snapshot sources must be SourceIR values")
        sources = tuple(
            sorted(source_values, key=lambda item: item.source.source_path)
        )
        source_ids = [source.source_id for source in sources]
        source_paths = [source.source.source_path for source in sources]
        if (
            len(source_ids) != len(set(source_ids))
            or len(source_paths) != len(set(source_paths))
            or set(source_paths) != selected_paths
        ):
            raise ValueError("character ability source identities are not unique")
        candidates_by_path = {
            candidate.relative_path: candidate for candidate in candidates
        }
        for source in sources:
            source_path = source.source.source_path
            candidate = candidates_by_path[source_path]
            if (
                source.source_id != _candidate_source_id(candidate)
                or source.source_kind != candidate.source_kind
                or source.avatar_id != candidate.avatar_id
                or source.base_type != candidate.base_type
                or thaw_json(source.source.evidence) != _candidate_source_evidence(candidate)
            ):
                raise ValueError(
                    "character ability source does not match candidate manifest"
                )
            raw_bytes = source_bytes[source_path]
            if (
                source.content_sha256 != sha256(raw_bytes).hexdigest()
                or source.byte_size != len(raw_bytes)
            ):
                raise ValueError("character ability source digest does not match bytes")

        if not isinstance(self.build_counters, Mapping):
            raise TypeError("character ability snapshot counters must be an object")
        counters = cast(Mapping[str, Any], freeze_json(dict(self.build_counters)))
        expected_counts = {
            "inventory_source_read_count": len(AVATAR_CONFIG_TABLES) + 1,
            "inventory_source_parse_count": len(AVATAR_CONFIG_TABLES) + 1,
            "ability_source_read_count": len(selected_paths),
            "ability_source_parse_count": len(selected_paths),
        }
        if any(counters.get(key) != value for key, value in expected_counts.items()):
            raise ValueError("character ability snapshot counters are inconsistent")

        expected_fingerprint = _compute_source_fingerprint(
            inventory,
            candidates,
            source_bytes,
            self.fingerprint_kind,
            source_filter,
        )
        if expected_fingerprint != self.source_fingerprint:
            raise ValueError("character ability source fingerprint does not close")
        snapshot_id = _stable_id(
            "character_ability_raw_snapshot",
            self.fingerprint_kind,
            self.source_fingerprint,
            *source_filter,
        )
        object.__setattr__(self, "source_bytes", source_bytes)
        object.__setattr__(self, "documents", MappingProxyType(documents))
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "source_filter", source_filter)
        object.__setattr__(self, "build_counters", counters)
        object.__setattr__(self, "snapshot_id", snapshot_id)

    @property
    def inventory_bytes(self) -> Mapping[str, bytes]:
        return self.inventory_manifest.inventory_bytes

    @property
    def candidates(self) -> tuple[_SourceCandidate, ...]:
        return self.inventory_manifest.candidates

    @property
    def source_catalog_complete(self) -> bool:
        return self.fingerprint_kind == "complete" and not self.source_filter

    def summary_json(self) -> dict[str, JSONValue]:
        return {
            "snapshot_id": self.snapshot_id,
            "source_fingerprint": self.source_fingerprint,
            "fingerprint_kind": self.fingerprint_kind,
            "source_catalog_complete": self.source_catalog_complete,
            "source_filter": list(self.source_filter),
            "available_source_count": len(self.candidates),
            "selected_source_count": len(self.sources),
            "build_counters": cast(JSONValue, thaw_json(self.build_counters)),
        }


def character_ability_snapshot_fingerprint(
    snapshot: CharacterAbilityRawSnapshot,
    *,
    inventory_bytes: Mapping[str, bytes] | None = None,
    source_bytes: Mapping[str, bytes] | None = None,
    fingerprint_kind: Literal["complete", "partial"] | None = None,
    source_filter: tuple[str, ...] | None = None,
) -> str:
    if type(snapshot) is not CharacterAbilityRawSnapshot:
        raise TypeError("snapshot must be a CharacterAbilityRawSnapshot")
    manifest = (
        snapshot.inventory_manifest
        if inventory_bytes is None
        else _CharacterAbilityInventoryManifest(inventory_bytes)
    )
    ability_sources = snapshot.source_bytes if source_bytes is None else source_bytes
    return _compute_source_fingerprint(
        manifest.inventory_bytes,
        manifest.candidates,
        ability_sources,
        snapshot.fingerprint_kind if fingerprint_kind is None else fingerprint_kind,
        snapshot.source_filter if source_filter is None else source_filter,
    )


@dataclass(frozen=True)
class CharacterAbilityScopeProjectionCatalog:
    snapshot_id: str
    sources: tuple[CharacterAbilitySourceIR, ...]
    scope_records: tuple[CharacterAbilityScopeRecordIR, ...]
    projections: tuple[CharacterAbilityProjectionIR, ...]
    families: tuple[CharacterAbilityFamilyIR, ...]
    external_dependencies: tuple[CharacterAbilityExternalDependencyIR, ...]
    source_fingerprint: str
    fingerprint_kind: Literal["complete", "partial"]
    build_counters: Mapping[str, Any]
    issues: tuple[CharacterAbilityProjectionIssue, ...]
    source_filter: tuple[str, ...] = ()
    family_filter: tuple[str, ...] = ()
    catalog_id: str = field(init=False)
    coverage_summary: Mapping[str, Any] = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise ValueError("character ability catalog snapshot identity is required")
        _require_sha256(self.source_fingerprint, "character ability fingerprint")
        if self.fingerprint_kind not in {"complete", "partial"}:
            raise ValueError("invalid character ability catalog fingerprint kind")
        source_filter = _canonical_string_tuple(self.source_filter, "source_filter")
        family_filter = _canonical_string_tuple(self.family_filter, "family_filter")
        if (self.fingerprint_kind == "complete") != (not source_filter):
            raise ValueError("character ability catalog completeness is inconsistent")

        typed_collections = (
            (self.sources, CharacterAbilitySourceIR),
            (self.scope_records, CharacterAbilityScopeRecordIR),
            (self.projections, CharacterAbilityProjectionIR),
            (self.families, CharacterAbilityFamilyIR),
            (self.external_dependencies, CharacterAbilityExternalDependencyIR),
            (self.issues, CharacterAbilityProjectionIssue),
        )
        if any(
            type(item) is not expected_type
            for values, expected_type in typed_collections
            for item in values
        ):
            raise TypeError("character ability catalog contains an invalid IR value")
        sources = tuple(sorted(self.sources, key=lambda item: item.source_id))
        records = tuple(sorted(self.scope_records, key=lambda item: item.record_id))
        projections = tuple(
            sorted(self.projections, key=lambda item: item.projection_id)
        )
        families = tuple(
            sorted(
                self.families,
                key=lambda item: (
                    item.occurrence_kind,
                    item.family,
                    item.semantic_kind,
                    item.nominal_scope,
                ),
            )
        )
        dependencies = tuple(
            sorted(self.external_dependencies, key=lambda item: item.dependency_id)
        )
        issues = tuple(
            sorted(self.issues, key=lambda item: (item.code, item.subject, item.detail))
        )
        source_ids = {source.source_id for source in sources}
        source_paths = {source.source.source_path for source in sources}
        sources_by_path = {
            source.source.source_path: source for source in sources
        }
        if (
            len(source_ids) != len(sources)
            or len(source_paths) != len(sources)
            or not sources
        ):
            raise ValueError("character ability catalog source identity conflict")
        if source_filter and source_paths != set(source_filter):
            raise ValueError("character ability catalog source filter is inconsistent")

        records_by_id = {record.record_id: record for record in records}
        if len(records_by_id) != len(records):
            raise ValueError("duplicate character ability scope record identity")
        for record in records:
            source = sources_by_path.get(record.source.source_path)
            if source is None:
                raise ValueError("scope record references an unknown source")
            evidence = record.source.evidence
            json_path = cast(str, evidence["json_path"])
            if (
                evidence["source_kind"] != source.source_kind
                or evidence["avatar_id"] != source.avatar_id
                or record.record_id
                != _stable_id(
                    "character_ability_scope",
                    record.occurrence_kind,
                    record.source.source_path,
                    json_path,
                    record.family,
                )
            ):
                raise ValueError("scope record identity or source evidence is forged")
            parent = records_by_id.get(record.parent_record_id)
            if parent is None:
                if (
                    record.parent_record_id != source.source_id
                    or record.parent_branch_path != "$"
                ):
                    raise ValueError("scope record parent reference is dangling")
            elif (
                parent.source.source_path != record.source.source_path
                or record.parent_branch_path
                != parent.source.evidence["json_path"]
            ):
                raise ValueError("scope record parent relationship is inconsistent")
            if (
                family_filter
                and record.materialization_role == "selected"
                and record.family not in family_filter
            ):
                raise ValueError("family view materialized an unrelated selected record")
            if not family_filter and record.materialization_role != "selected":
                raise ValueError("complete family view cannot contain context-only records")

        for record in records:
            seen = {record.record_id}
            parent = records_by_id.get(record.parent_record_id)
            while parent is not None:
                if parent.record_id in seen:
                    raise ValueError("scope record parent chain is cyclic")
                seen.add(parent.record_id)
                parent = records_by_id.get(parent.parent_record_id)
            inherited_id = cast(
                str,
                record.source.evidence["inherited_scope_record_id"],
            )
            direct_parent = records_by_id.get(record.parent_record_id)
            expected_inherited = ""
            if direct_parent is not None:
                expected_inherited = cast(
                    str,
                    direct_parent.source.evidence["inherited_scope_record_id"],
                )
                if not expected_inherited and _is_terminal_scope(
                    direct_parent.effective_scope
                ):
                    expected_inherited = direct_parent.record_id
            if expected_inherited and inherited_id != expected_inherited:
                raise ValueError("scope record inherited terminal identity is inconsistent")
            if inherited_id:
                inherited = records_by_id.get(inherited_id)
                if (
                    inherited is None
                    or inherited.record_id == record.record_id
                    or inherited.source.source_path != record.source.source_path
                    or not _is_terminal_scope(inherited.effective_scope)
                    or inherited.effective_scope != record.effective_scope
                    or (
                        not expected_inherited
                        and not _same_object_scope_markers(record, inherited)
                    )
                ):
                    raise ValueError("scope record inherited terminal reference is forged")

        object_markers: dict[tuple[str, str], list[CharacterAbilityScopeRecordIR]] = defaultdict(list)
        for record in records:
            if record.occurrence_kind not in {"event", "typed_node"}:
                continue
            marker_path = cast(str, record.source.evidence["json_path"])
            object_markers[(record.source.source_path, marker_path.rsplit(".", 1)[0])].append(record)
        for markers in object_markers.values():
            if len(markers) != 2:
                continue
            left, right = markers
            if left.effective_scope != right.effective_scope:
                raise ValueError("same-object scope markers disagree on effective scope")
            inherited_ids = [
                cast(str, marker.source.evidence["inherited_scope_record_id"])
                for marker in markers
            ]
            if not _is_terminal_scope(left.effective_scope):
                if any(inherited_ids):
                    raise ValueError("gameplay object marker inherits a terminal scope")
                continue
            local_origins = [
                marker for marker, inherited_id in zip(markers, inherited_ids)
                if not inherited_id
            ]
            if len(local_origins) == 1:
                origin = local_origins[0]
                dependent = right if origin is left else left
                if dependent.source.evidence["inherited_scope_record_id"] != origin.record_id:
                    raise ValueError("same-object terminal origin is inconsistent")
            elif local_origins or len(set(inherited_ids)) != 1:
                raise ValueError("same-object terminal inheritance is ambiguous")

        projection_ids = {projection.projection_id for projection in projections}
        projection_roots = {projection.scope_record_id for projection in projections}
        if (
            len(projection_ids) != len(projections)
            or len(projection_roots) != len(projections)
        ):
            raise ValueError("duplicate character ability projection identity")
        for projection in projections:
            record = records_by_id.get(projection.scope_record_id)
            if record is None:
                raise ValueError("character ability projection scope is dangling")
            if (
                record.materialization_role != "selected"
                or projection.source_opcode != record.family
                or projection.projection_scope != record.effective_scope
                or projection.source != record.source
                or projection.projection_id
                != _stable_id("character_ability_projection", record.record_id)
            ):
                raise ValueError("character ability projection relationship is invalid")

        _validate_family_reconciliation(records, families)
        dependency_ids = {dependency.dependency_id for dependency in dependencies}
        if len(dependency_ids) != len(dependencies):
            raise ValueError("duplicate character ability dependency identity")
        _validate_external_dependencies(
            dependencies,
            records,
            projections,
            source_catalog_complete=(
                self.fingerprint_kind == "complete" and not source_filter
            ),
            family_filtered=bool(family_filter),
        )
        if not isinstance(self.build_counters, Mapping):
            raise TypeError("character ability catalog counters must be an object")
        counters = cast(Mapping[str, Any], freeze_json(dict(self.build_counters)))
        coverage = cast(
            Mapping[str, Any],
            freeze_json(_coverage_summary(sources, records, projections, families)),
        )
        catalog_id = _catalog_identity(
            self.snapshot_id,
            self.source_fingerprint,
            self.fingerprint_kind,
            source_filter,
            family_filter,
            sources,
            records,
            projections,
            families,
            dependencies,
            issues,
        )
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "scope_records", records)
        object.__setattr__(self, "projections", projections)
        object.__setattr__(self, "families", families)
        object.__setattr__(self, "external_dependencies", dependencies)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "source_filter", source_filter)
        object.__setattr__(self, "family_filter", family_filter)
        object.__setattr__(self, "build_counters", counters)
        object.__setattr__(self, "coverage_summary", coverage)
        object.__setattr__(self, "catalog_id", catalog_id)

    @property
    def ok(self) -> bool:
        return not self.issues and all(
            projection.coverage_status != "blocked"
            for projection in self.projections
        )

    @property
    def source_catalog_complete(self) -> bool:
        return self.fingerprint_kind == "complete" and not self.source_filter

    @property
    def scope_reconciliation_complete(self) -> bool:
        blocking_codes = {
            "requested_family_not_found",
            "scope_decision_required",
            "source_traversal_incomplete",
        }
        return (
            self.source_catalog_complete
            and not self.family_filter
            and not any(issue.code in blocking_codes for issue in self.issues)
        )

    @property
    def complete(self) -> bool:
        return self.ok and self.scope_reconciliation_complete

    @property
    def gameplay_records(self) -> tuple[CharacterAbilityScopeRecordIR, ...]:
        return tuple(
            record
            for record in self.scope_records
            if record.admission_status == "gameplay_candidate"
        )

    def for_families(
        self,
        families: Iterable[str],
    ) -> "CharacterAbilityScopeProjectionCatalog":
        if type(self) is not CharacterAbilityScopeProjectionCatalog:
            raise TypeError("family view requires an exact character ability catalog")
        selected = _normalized_filter(families, "families")
        if not selected:
            raise ValueError("family filter cannot be empty")
        records_by_id = {record.record_id: record for record in self.scope_records}
        selected_ids = {
            record.record_id
            for record in self.scope_records
            if record.family in selected
            and record.materialization_role == "selected"
        }
        closure_ids = set(selected_ids)
        pending = list(selected_ids)
        while pending:
            record = records_by_id[pending.pop()]
            inherited_id = record.source.evidence["inherited_scope_record_id"]
            for related_id in (record.parent_record_id, inherited_id):
                if related_id in records_by_id and related_id not in closure_ids:
                    closure_ids.add(related_id)
                    pending.append(related_id)
        records = tuple(
            replace(
                record,
                materialization_role=(
                    "selected" if record.record_id in selected_ids else "ancestor_context"
                ),
            )
            for record in self.scope_records
            if record.record_id in closure_ids
        )
        projections = tuple(
            projection
            for projection in self.projections
            if projection.scope_record_id in selected_ids
        )
        family_rows = tuple(
            family for family in self.families if family.family in selected
        )
        found = {family.family for family in family_rows}
        missing = sorted(selected - found)
        issues = (*self.issues, *(
            CharacterAbilityProjectionIssue(
                "requested_family_not_found",
                family,
                "requested family is absent from the materialized source view",
            )
            for family in missing
        ))
        return CharacterAbilityScopeProjectionCatalog(
            snapshot_id=self.snapshot_id,
            sources=self.sources,
            scope_records=records,
            projections=projections,
            families=family_rows,
            external_dependencies=_external_dependencies(
                records,
                projections,
                source_catalog_complete=self.source_catalog_complete,
                family_filtered=True,
            ),
            source_fingerprint=self.source_fingerprint,
            fingerprint_kind=self.fingerprint_kind,
            build_counters={
                **cast(dict[str, JSONValue], thaw_json(self.build_counters)),
                "filtered_from_existing_catalog": True,
                "additional_source_read_count": 0,
                "additional_source_parse_count": 0,
                "materialized_record_count": len(records),
            },
            issues=tuple(issues),
            source_filter=self.source_filter,
            family_filter=tuple(sorted(selected)),
        )

    def summary_json(self) -> dict[str, JSONValue]:
        return {
            "catalog_id": self.catalog_id,
            "snapshot_id": self.snapshot_id,
            "ok": self.ok,
            "complete": self.complete,
            "source_catalog_complete": self.source_catalog_complete,
            "scope_reconciliation_complete": self.scope_reconciliation_complete,
            "source_fingerprint": self.source_fingerprint,
            "fingerprint_kind": self.fingerprint_kind,
            "source_filter": list(self.source_filter),
            "family_filter": list(self.family_filter),
            "coverage_summary": cast(JSONValue, thaw_json(self.coverage_summary)),
            "build_counters": cast(JSONValue, thaw_json(self.build_counters)),
            "external_dependencies": [
                dependency.to_json() for dependency in self.external_dependencies
            ],
            "issues": [issue.to_json() for issue in self.issues],
        }


@dataclass(frozen=True)
class _BranchContext:
    record_id: str
    path: str
    semantic_kind: CharacterAbilitySemanticKind


@dataclass(frozen=True)
class _SelectorBranchContext:
    branch_kind: Literal[
        "explicit_task_branches",
        "predicate_gated_object",
    ]
    branch_root_path: str
    true_subtree_path: str
    false_subtree_path: str


@dataclass(frozen=True)
class _ScopeDraft:
    record_id: str
    occurrence_kind: CharacterAbilityOccurrenceKind
    family: str
    nominal_semantic_kind: CharacterAbilitySemanticKind
    effective_semantic_kind: CharacterAbilitySemanticKind
    nominal_scope: CharacterAbilityScope
    effective_scope: CharacterAbilityScope
    path: str
    parent_record_id: str
    parent_branch_path: str
    inherited_scope_record_id: str
    raw_container: Mapping[str, Any]
    selector_branch: _SelectorBranchContext | None


def _selector_branch_context(
    path: str,
    container: Mapping[str, Any],
) -> _SelectorBranchContext | None:
    opcode = _short_type(container.get("$type"))
    if opcode in {"ByAnd", "ByAny", "ByNot"}:
        return None
    true_path = ""
    false_path = ""
    if "SuccessTaskList" in container:
        true_path = _child_path(path, "SuccessTaskList")
    elif "TaskList" in container:
        true_path = _child_path(path, "TaskList")
    if "FailedTaskList" in container:
        false_path = _child_path(path, "FailedTaskList")
    if true_path or false_path:
        return _SelectorBranchContext(
            branch_kind="explicit_task_branches",
            branch_root_path=path,
            true_subtree_path=true_path,
            false_subtree_path=false_path,
        )
    substantive_fields = set(container).difference(
        {"$type", "Predicate", "Condition", "Inverse"}
    )
    if not substantive_fields:
        return None
    return _SelectorBranchContext(
        branch_kind="predicate_gated_object",
        branch_root_path=path,
        true_subtree_path=path,
        false_subtree_path="",
    )


class _DocumentClassifier:
    def __init__(
        self,
        source: CharacterAbilitySourceIR,
        family_filter: frozenset[str] | None,
    ) -> None:
        if type(source) is not CharacterAbilitySourceIR:
            raise TypeError("character ability classifier source must be exact SourceIR")
        self.source = source
        self.family_filter = family_filter
        self.drafts: list[_ScopeDraft] = []
        self.issues: list[CharacterAbilityProjectionIssue] = []

    def classify(self, document: Mapping[str, Any]) -> None:
        self._walk(document, "$", None, None, None)

    def _walk(
        self,
        value: Any,
        path: str,
        terminal_branch: _BranchContext | None,
        parent_branch: _BranchContext | None,
        selector_branch: _SelectorBranchContext | None,
    ) -> None:
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                self._walk(
                    item,
                    f"{path}[{index}]",
                    terminal_branch,
                    parent_branch,
                    selector_branch,
                )
            return
        if not isinstance(value, Mapping):
            return

        event = value.get("Event")
        event_semantic: CharacterAbilitySemanticKind | None = None
        if isinstance(event, str):
            event_semantic = self._event_semantic_kind(event, f"{path}.Event")

        raw_type = value.get("$type")
        opcode = _short_type(raw_type)
        type_semantic: CharacterAbilitySemanticKind | None = None
        type_local_semantic: CharacterAbilitySemanticKind | None = None
        if isinstance(raw_type, str):
            type_semantic = _OPCODE_SEMANTIC_KIND.get(opcode)
            if type_semantic is None:
                type_semantic = "combat_decode_required"
                self.issues.append(
                    CharacterAbilityProjectionIssue(
                        "scope_decision_required",
                        f"{self.source.source.source_path}:{path}",
                        f"unknown typed opcode:{opcode}",
                    )
                )
            type_local_semantic = _local_effective_semantic(opcode, value)

        marker_rows: list[tuple[str, str, CharacterAbilitySemanticKind]] = []
        if event_semantic is not None:
            marker_rows.append(
                (
                    _stable_id(
                        "character_ability_scope",
                        "event",
                        self.source.source.source_path,
                        f"{path}.Event",
                        cast(str, event),
                    ),
                    f"{path}.Event",
                    event_semantic,
                )
            )
        if type_semantic is not None:
            marker_rows.append(
                (
                    _stable_id(
                        "character_ability_scope",
                        "typed_node",
                        self.source.source.source_path,
                        f"{path}.$type",
                        opcode,
                    ),
                    f"{path}.$type",
                    type_local_semantic or type_semantic,
                )
            )
        terminal_markers = tuple(
            marker
            for marker in marker_rows
            if _is_terminal_scope(_scope_for_semantic(marker[2]))
        )
        terminal_scopes = {
            _scope_for_semantic(marker[2]) for marker in terminal_markers
        }
        conflicting_markers = len(terminal_scopes) > 1
        local_terminal: _BranchContext | None = None
        if terminal_markers:
            marker_id, marker_path, marker_semantic = terminal_markers[0]
            if conflicting_markers:
                marker_semantic = "combat_decode_required"
                self.issues.append(
                    CharacterAbilityProjectionIssue(
                        "scope_decision_required",
                        f"{self.source.source.source_path}:{path}",
                        "conflicting same-object terminal scopes:"
                        + ",".join(sorted(terminal_scopes)),
                    )
                )
            local_terminal = _BranchContext(
                marker_id,
                marker_path,
                marker_semantic,
            )
        object_terminal = local_terminal if terminal_branch is None else terminal_branch

        event_context: _BranchContext | None = None
        if event_semantic is not None:
            event_id = marker_rows[0][0]
            event_record = self._record(
                occurrence_kind="event",
                family=cast(str, event),
                semantic_kind=event_semantic,
                path=f"{path}.Event",
                raw_container=value,
                terminal_branch=(
                    None
                    if local_terminal is not None
                    and object_terminal is local_terminal
                    and event_id == local_terminal.record_id
                    else object_terminal
                ),
                parent_branch=parent_branch,
                selector_branch=selector_branch,
                local_semantic_kind=(
                    "combat_decode_required"
                    if conflicting_markers
                    and local_terminal is not None
                    and event_id == local_terminal.record_id
                    else None
                ),
            )
            event_context = _BranchContext(
                event_record.record_id,
                f"{path}.Event",
                event_record.effective_semantic_kind,
            )

        type_context: _BranchContext | None = None
        type_record: _ScopeDraft | None = None
        if type_semantic is not None:
            type_id = next(
                marker[0]
                for marker in marker_rows
                if marker[1] == f"{path}.$type"
            )
            type_record = self._record(
                occurrence_kind="typed_node",
                family=opcode,
                semantic_kind=type_semantic,
                path=f"{path}.$type",
                raw_container=value,
                terminal_branch=(
                    None
                    if local_terminal is not None
                    and object_terminal is local_terminal
                    and type_id == local_terminal.record_id
                    else object_terminal
                ),
                parent_branch=parent_branch,
                selector_branch=selector_branch,
                local_semantic_kind=(
                    "combat_decode_required"
                    if conflicting_markers
                    and local_terminal is not None
                    and type_id == local_terminal.record_id
                    else type_local_semantic
                ),
            )
            type_context = _BranchContext(
                type_record.record_id,
                f"{path}.$type",
                type_record.effective_semantic_kind,
            )

        child_parent = type_context or event_context or parent_branch
        child_terminal = object_terminal

        for key, child in value.items():
            child_path = _child_path(path, key)
            child_selector_branch = selector_branch
            if key in {"Predicate", "Condition"} and isinstance(
                child,
                (Mapping, list, tuple),
            ):
                local_selector_branch = _selector_branch_context(path, value)
                if local_selector_branch is not None:
                    child_selector_branch = local_selector_branch
            if key.startswith("On") and isinstance(child, (Mapping, list, tuple)):
                semantic_kind = STRUCTURAL_ENTRY_KINDS.get(key)
                if semantic_kind is None:
                    semantic_kind = "combat_decode_required"
                    self.issues.append(
                        CharacterAbilityProjectionIssue(
                            "scope_decision_required",
                            f"{self.source.source.source_path}:{child_path}",
                            f"unknown structural entry:{key}",
                        )
                    )
                entry_record = self._record(
                    occurrence_kind="structural_entry",
                    family=key,
                    semantic_kind=semantic_kind,
                    path=child_path,
                    raw_container={"entry": key, "value": child},
                    terminal_branch=child_terminal,
                    parent_branch=child_parent,
                    selector_branch=child_selector_branch,
                )
                entry_context = _BranchContext(
                    entry_record.record_id,
                    child_path,
                    entry_record.effective_semantic_kind,
                )
                entry_terminal = child_terminal
                if entry_terminal is None and _is_terminal_scope(
                    entry_record.effective_scope
                ):
                    entry_terminal = entry_context
                self._walk(
                    child,
                    child_path,
                    entry_terminal,
                    entry_context,
                    child_selector_branch,
                )
            else:
                self._walk(
                    child,
                    child_path,
                    child_terminal,
                    child_parent,
                    child_selector_branch,
                )

    def _event_semantic_kind(
        self,
        event: str,
        path: str,
    ) -> CharacterAbilitySemanticKind:
        if event in COMBAT_EVENT_FAMILIES:
            return "combat_event"
        if event.endswith("_CL"):
            return "client_only_excluded"
        self.issues.append(
            CharacterAbilityProjectionIssue(
                "scope_decision_required",
                f"{self.source.source.source_path}:{path}",
                f"unknown event family:{event}",
            )
        )
        return "combat_decode_required"

    def _record(
        self,
        *,
        occurrence_kind: CharacterAbilityOccurrenceKind,
        family: str,
        semantic_kind: CharacterAbilitySemanticKind,
        path: str,
        raw_container: Mapping[str, Any],
        terminal_branch: _BranchContext | None,
        parent_branch: _BranchContext | None,
        selector_branch: _SelectorBranchContext | None,
        local_semantic_kind: CharacterAbilitySemanticKind | None = None,
    ) -> _ScopeDraft:
        nominal_scope = _scope_for_semantic(semantic_kind)
        effective_semantic = (
            terminal_branch.semantic_kind
            if terminal_branch is not None
            else local_semantic_kind or semantic_kind
        )
        effective_scope = _scope_for_semantic(effective_semantic)
        record_id = _stable_id(
            "character_ability_scope",
            occurrence_kind,
            self.source.source.source_path,
            path,
            family,
        )
        record = _ScopeDraft(
            record_id=record_id,
            occurrence_kind=occurrence_kind,
            family=family,
            nominal_semantic_kind=semantic_kind,
            effective_semantic_kind=effective_semantic,
            nominal_scope=nominal_scope,
            effective_scope=effective_scope,
            path=path,
            parent_record_id=(
                parent_branch.record_id
                if parent_branch is not None
                else self.source.source_id
            ),
            parent_branch_path=(
                parent_branch.path if parent_branch is not None else "$"
            ),
            inherited_scope_record_id=(
                terminal_branch.record_id if terminal_branch is not None else ""
            ),
            raw_container=raw_container,
            selector_branch=selector_branch,
        )
        self.drafts.append(record)
        return record

    def _selected(self, family: str) -> bool:
        return self.family_filter is None or family in self.family_filter

    def materialize(self) -> CharacterAbilityDocumentProjection:
        drafts_by_id = {draft.record_id: draft for draft in self.drafts}
        selected_ids = {
            draft.record_id
            for draft in self.drafts
            if self._selected(draft.family)
        }
        closure_ids = set(selected_ids)
        pending = list(selected_ids)
        while pending:
            draft = drafts_by_id[pending.pop()]
            for related_id in (
                draft.parent_record_id,
                draft.inherited_scope_record_id,
            ):
                if related_id in drafts_by_id and related_id not in closure_ids:
                    closure_ids.add(related_id)
                    pending.append(related_id)

        records: list[CharacterAbilityScopeRecordIR] = []
        selected_drafts: list[_ScopeDraft] = []
        for draft in self.drafts:
            if draft.record_id not in closure_ids:
                continue
            role = cast(
                CharacterAbilityMaterializationRole,
                "selected" if draft.record_id in selected_ids else "ancestor_context",
            )
            record = _materialize_scope_record(self.source, draft, role)
            records.append(record)
            if role == "selected":
                selected_drafts.append(draft)

        projections: list[CharacterAbilityProjectionIR] = []
        records_by_id = {record.record_id: record for record in records}
        for draft in selected_drafts:
            if (
                draft.nominal_scope
                not in {
                    "build_resolution",
                    "battle_data_projection",
                    "input_projection",
                    "environment_input",
                }
                or draft.effective_scope != draft.nominal_scope
            ):
                continue
            projection, blocked_reason = _project_node(
                records_by_id[draft.record_id],
                draft.raw_container,
                draft.selector_branch,
            )
            if projection is not None:
                projections.append(projection)
            else:
                self.issues.append(
                    CharacterAbilityProjectionIssue(
                        "projection_blocked",
                        draft.record_id,
                        blocked_reason,
                    )
                )
        return CharacterAbilityDocumentProjection(
            scope_records=tuple(records),
            projections=tuple(projections),
            families=_family_rows_from_drafts(
                selected_drafts,
                self.source.source.source_path,
            ),
            issues=tuple(self.issues),
            discovered_occurrence_count=len(self.drafts),
            observed_families=tuple(sorted({draft.family for draft in self.drafts})),
        )


def classify_character_ability_document(
    source: CharacterAbilitySourceIR,
    document: Mapping[str, Any],
    *,
    families: Iterable[str] | None = None,
) -> CharacterAbilityDocumentProjection:
    if type(source) is not CharacterAbilitySourceIR:
        raise TypeError("character ability classifier source must be exact SourceIR")
    family_filter = (
        _normalized_filter(families, "families")
        if families is not None
        else None
    )
    if family_filter is not None and not family_filter:
        raise ValueError("character ability family selection cannot be empty")
    frozen_document = cast(Mapping[str, Any], freeze_json(dict(document)))
    return _classify_frozen_character_ability_document(
        source,
        frozen_document,
        family_filter,
    )


def _classify_frozen_character_ability_document(
    source: CharacterAbilitySourceIR,
    document: Mapping[str, Any],
    family_filter: frozenset[str] | None,
) -> CharacterAbilityDocumentProjection:
    if type(source) is not CharacterAbilitySourceIR:
        raise TypeError("character ability classifier source must be exact SourceIR")
    classifier = _DocumentClassifier(source, family_filter)
    classifier.classify(document)
    return classifier.materialize()


def build_character_ability_raw_snapshot(
    tbgd_root: Path,
    *,
    source_paths: Iterable[str] | None = None,
) -> CharacterAbilityRawSnapshot:
    root = tbgd_root.resolve()
    inventory_bytes: dict[str, bytes] = {}
    for relative_path in (*AVATAR_CONFIG_TABLES, AVATAR_ENHANCED_CONFIG_TABLE):
        raw_bytes = _read_required_bytes(
            root / relative_path,
            f"character source inventory table missing:{relative_path}",
        )
        inventory_bytes[relative_path] = raw_bytes
    inventory_manifest = _CharacterAbilityInventoryManifest(inventory_bytes)
    candidates = inventory_manifest.candidates
    available_paths = {candidate.relative_path for candidate in candidates}
    source_filter = (
        _normalized_filter(source_paths, "source_paths")
        if source_paths is not None
        else None
    )
    if source_filter is not None:
        unknown_paths = sorted(source_filter - available_paths)
        if unknown_paths:
            raise ValueError(
                "character ability source filter contains unknown paths:"
                + ",".join(unknown_paths)
            )
        if not source_filter:
            raise ValueError("character ability source selection cannot be empty")
    selected_candidates = tuple(
        candidate
        for candidate in candidates
        if source_filter is None or candidate.relative_path in source_filter
    )
    source_bytes: dict[str, bytes] = {}
    sources: list[CharacterAbilitySourceIR] = []
    for candidate in selected_candidates:
        raw_bytes = _read_required_bytes(
            root / candidate.relative_path,
            f"character ability source missing:{candidate.relative_path}",
        )
        source_bytes[candidate.relative_path] = raw_bytes
        sources.append(_source_ir(candidate, raw_bytes))
    normalized_source_filter = tuple(sorted(source_filter or ()))
    fingerprint_kind = cast(
        Literal["complete", "partial"],
        "partial" if source_filter is not None else "complete",
    )
    source_fingerprint = _compute_source_fingerprint(
        inventory_bytes,
        candidates,
        source_bytes,
        fingerprint_kind,
        normalized_source_filter,
    )
    return CharacterAbilityRawSnapshot(
        inventory_manifest=inventory_manifest,
        source_bytes=source_bytes,
        sources=tuple(sources),
        source_fingerprint=source_fingerprint,
        fingerprint_kind=fingerprint_kind,
        source_filter=normalized_source_filter,
        build_counters={
            "inventory_source_read_count": len(inventory_bytes),
            "inventory_source_parse_count": len(inventory_manifest.inventory_bytes),
            "ability_source_read_count": len(source_bytes),
            "ability_source_parse_count": len(source_bytes),
            "source_filter_applied_before_ability_read": source_filter is not None,
        },
    )


def build_character_ability_scope_projection(
    tbgd_root: Path,
    *,
    source_paths: Iterable[str] | None = None,
    families: Iterable[str] | None = None,
    snapshot: CharacterAbilityRawSnapshot | None = None,
) -> CharacterAbilityScopeProjectionCatalog:
    if snapshot is None:
        snapshot = build_character_ability_raw_snapshot(
            tbgd_root,
            source_paths=source_paths,
        )
    elif type(snapshot) is not CharacterAbilityRawSnapshot:
        raise TypeError("scope projection snapshot must be exact RawSnapshot")
    elif source_paths is not None:
        requested = tuple(sorted(_normalized_filter(source_paths, "source_paths")))
        if requested != snapshot.source_filter:
            raise ValueError("snapshot source filter does not match requested sources")

    family_filter = (
        _normalized_filter(families, "families")
        if families is not None
        else None
    )
    if family_filter is not None and not family_filter:
        raise ValueError("character ability family selection cannot be empty")

    records: list[CharacterAbilityScopeRecordIR] = []
    projections: list[CharacterAbilityProjectionIR] = []
    issues: list[CharacterAbilityProjectionIssue] = []
    family_rows: list[CharacterAbilityFamilyIR] = []
    discovered_occurrence_count = 0
    observed_families: set[str] = set()
    for source_ir in snapshot.sources:
        document = snapshot.documents[source_ir.source.source_path]
        document_projection = _classify_frozen_character_ability_document(
            source_ir,
            document,
            family_filter,
        )
        if type(document_projection) is not CharacterAbilityDocumentProjection:
            raise TypeError("character ability classifier returned an invalid projection")
        records.extend(document_projection.scope_records)
        projections.extend(document_projection.projections)
        family_rows.extend(document_projection.families)
        issues.extend(document_projection.issues)
        discovered_occurrence_count += document_projection.discovered_occurrence_count
        observed_families.update(document_projection.observed_families)

    if family_filter is not None:
        for missing_family in sorted(family_filter - observed_families):
            issues.append(
                CharacterAbilityProjectionIssue(
                    "requested_family_not_found",
                    missing_family,
                    "requested family is absent from the selected source snapshot",
                )
            )

    merged_families = _merge_family_rows(family_rows)
    return CharacterAbilityScopeProjectionCatalog(
        snapshot_id=snapshot.snapshot_id,
        sources=snapshot.sources,
        scope_records=tuple(records),
        projections=tuple(projections),
        families=merged_families,
        external_dependencies=_external_dependencies(
            tuple(records),
            tuple(projections),
            source_catalog_complete=snapshot.source_catalog_complete,
            family_filtered=family_filter is not None,
        ),
        source_fingerprint=snapshot.source_fingerprint,
        fingerprint_kind=snapshot.fingerprint_kind,
        build_counters={
            **cast(dict[str, JSONValue], thaw_json(snapshot.build_counters)),
            "discovered_occurrence_count": discovered_occurrence_count,
            "materialized_record_count": len(records),
            "family_filter_applied_before_ir_materialization": family_filter is not None,
        },
        issues=tuple(issues),
        source_filter=snapshot.source_filter,
        family_filter=tuple(sorted(family_filter or ())),
    )


def _normalize_inventory_avatar_id(value: object, context: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"avatar identity is not an integer:{context}")
    return str(value)


def _discover_source_candidates_from_rows(
    inventory_rows: Mapping[str, list[Any]],
) -> tuple[_SourceCandidate, ...]:
    base_rows: dict[str, tuple[str, int, dict[str, Any]]] = {}
    for relative_path in AVATAR_CONFIG_TABLES:
        rows = inventory_rows.get(relative_path)
        if rows is None:
            raise ValueError(f"character source inventory missing:{relative_path}")
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"avatar config row is not an object:{relative_path}")
            release = row.get("Release")
            if not isinstance(release, bool):
                raise ValueError(
                    f"avatar release scope is not explicit:{relative_path}:{row_index}"
                )
            if not release:
                continue
            avatar_id = _normalize_inventory_avatar_id(
                row.get("AvatarID"), f"{relative_path}:{row_index}"
            )
            base_type = row.get("AvatarBaseType")
            if (
                not isinstance(base_type, str)
                or not base_type
            ):
                raise ValueError(
                    f"avatar source identity incomplete:{relative_path}:{row_index}"
                )
            if avatar_id in base_rows:
                raise ValueError(f"duplicate avatar source identity:{avatar_id}")
            base_rows[avatar_id] = (relative_path, row_index, row)

    enhanced_rows: dict[str, tuple[int, dict[str, Any]]] = {}
    enhanced_source = inventory_rows.get(AVATAR_ENHANCED_CONFIG_TABLE)
    if enhanced_source is None:
        raise ValueError("enhanced avatar source inventory is missing")
    for row_index, row in enumerate(enhanced_source):
        if not isinstance(row, dict):
            raise ValueError("enhanced avatar config row is not an object")
        avatar_id = _normalize_inventory_avatar_id(
            row.get("AvatarID"), f"{AVATAR_ENHANCED_CONFIG_TABLE}:{row_index}"
        )
        if avatar_id in enhanced_rows:
            raise ValueError(f"duplicate enhanced avatar source identity:{avatar_id}")
        enhanced_rows[avatar_id] = (row_index, row)

    unknown_enhanced = sorted(set(enhanced_rows) - set(base_rows))
    if unknown_enhanced:
        raise ValueError(
            "enhanced avatar source has no released base row:"
            + ",".join(unknown_enhanced)
        )

    candidates: list[_SourceCandidate] = []
    for avatar_id, (config_path, row_index, base_row) in base_rows.items():
        base_type = base_row["AvatarBaseType"]
        if not isinstance(base_type, str) or not base_type:
            raise ValueError(f"avatar base type is invalid:{avatar_id}")
        if base_type in DEFERRED_CHARACTER_BASE_TYPES:
            continue
        enhanced = enhanced_rows.get(avatar_id)
        selected_row = enhanced[1] if enhanced is not None else base_row
        character_path = selected_row.get("JsonPath")
        if not isinstance(character_path, str) or not character_path:
            raise ValueError(f"avatar character source path missing:{avatar_id}")
        candidates.append(
            _SourceCandidate(
                avatar_id=avatar_id,
                base_type=base_type,
                relative_path=_avatar_ability_path(character_path),
                config_source_path=(
                    AVATAR_ENHANCED_CONFIG_TABLE
                    if enhanced is not None
                    else config_path
                ),
                config_row_index=enhanced[0] if enhanced is not None else row_index,
                selected_version="enhanced" if enhanced is not None else "base",
            )
        )
    candidates.append(
        _SourceCandidate(
            avatar_id="",
            base_type="shared_character_runtime",
            relative_path=SHARED_CHARACTER_ABILITY_SOURCE,
            config_source_path=SHARED_CHARACTER_ABILITY_SOURCE,
            config_row_index=0,
            selected_version="shared",
            source_kind="character_shared",
        )
    )
    paths = [candidate.relative_path for candidate in candidates]
    if len(paths) != len(set(paths)):
        duplicates = sorted(
            path for path, count in Counter(paths).items() if count > 1
        )
        raise ValueError(
            "character records do not map one-to-one to ability sources:"
            + ",".join(duplicates)
        )
    return tuple(sorted(candidates, key=lambda item: item.relative_path))


def _candidate_source_id(candidate: _SourceCandidate) -> str:
    return (
        "character_ability_source:shared"
        if candidate.source_kind == "character_shared"
        else f"character_ability_source:avatar:{candidate.avatar_id}"
    )


def _candidate_source_evidence(candidate: _SourceCandidate) -> dict[str, JSONValue]:
    return {
        "avatar_id": candidate.avatar_id,
        "base_type": candidate.base_type,
        "config_source_path": candidate.config_source_path,
        "config_row_index": candidate.config_row_index,
        "selected_version": candidate.selected_version,
    }


def _source_ir(candidate: _SourceCandidate, raw_bytes: bytes) -> CharacterAbilitySourceIR:
    source_id = _candidate_source_id(candidate)
    return CharacterAbilitySourceIR(
        source_id=source_id,
        source_kind=candidate.source_kind,
        avatar_id=candidate.avatar_id,
        base_type=candidate.base_type,
        content_sha256=sha256(raw_bytes).hexdigest(),
        byte_size=len(raw_bytes),
        source=IRSource(
            source_path=candidate.relative_path,
            raw_type="character_ability_source",
            raw_id=source_id,
            evidence=_candidate_source_evidence(candidate),
        ),
    )


def _read_required_bytes(path: Path, missing_message: str) -> bytes:
    if not path.is_file():
        raise ValueError(missing_message)
    return path.read_bytes()


def _load_json_rows_bytes(raw_bytes: bytes, relative_path: str) -> list[Any]:
    try:
        value = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"character source inventory table unreadable:{relative_path}"
        ) from exc
    if not isinstance(value, list):
        raise ValueError(
            f"character source inventory table is not a list:{relative_path}"
        )
    return value


def _avatar_ability_path(character_path: str) -> str:
    path = PurePosixPath(character_path)
    if path.name.endswith("_Config.json"):
        name = path.name.removesuffix("_Config.json") + "_Ability.json"
    else:
        name = path.stem + "_Ability.json"
    root = (
        "Config/ConfigAbility/Avatar/Advanced"
        if "Advanced" in path.parts
        else "Config/ConfigAbility/Avatar"
    )
    return f"{root}/{name}"


def _scope_for_semantic(
    semantic_kind: CharacterAbilitySemanticKind,
) -> CharacterAbilityScope:
    if semantic_kind in {
        "combat_runtime",
        "combat_condition",
        "combat_control_flow",
        "simulation_sequence",
        "contextual_data",
        "combat_event",
    }:
        return "gameplay"
    if semantic_kind in _NON_GAMEPLAY_KINDS:
        return "non_gameplay"
    if semantic_kind == "input_control_projection":
        return "input_projection"
    if semantic_kind == "combat_decode_required":
        return "decode_required"
    return cast(CharacterAbilityScope, semantic_kind)


def _is_terminal_scope(scope: CharacterAbilityScope) -> bool:
    return scope != "gameplay"


def _admission_for_scope(
    scope: CharacterAbilityScope,
) -> CharacterAbilityAdmissionStatus:
    return {
        "gameplay": "gameplay_candidate",
        "build_resolution": "build_only",
        "battle_data_projection": "projection_only",
        "input_projection": "projection_only",
        "environment_input": "projection_only",
        "non_gameplay": "retired",
        "decode_required": "blocked",
    }[scope]


def _coverage_for_scope(scope: CharacterAbilityScope) -> str:
    return {
        "gameplay": "discovered_only",
        "build_resolution": "lowered",
        "battle_data_projection": "lowered",
        "input_projection": "lowered",
        "environment_input": "lowered",
        "non_gameplay": "audit_only",
        "decode_required": "blocked",
    }[scope]


_SPECIAL_RESOURCE_CLIENT_FIELDS = frozenset(
    {"EnergyDotPrefabPaths", "IconPath", "PrefabPath"}
)
_SPECIAL_RESOURCE_FIELDS = frozenset(
    {
        "Active",
        "ActiveCount",
        "BarType",
        "CD",
        "CurrentCount",
        "CurrentState",
        "MaxCount",
        "TargetType",
    }
)
def _local_effective_semantic(
    opcode: str,
    raw_node: Mapping[str, Any],
) -> CharacterAbilitySemanticKind | None:
    if opcode not in {"SetEnergyBarState", "SetSummonerEnergyBarState"}:
        return None
    fields = {key for key in raw_node if key != "$type"}
    if fields.intersection(_SPECIAL_RESOURCE_FIELDS):
        return None
    if fields and fields.issubset(_SPECIAL_RESOURCE_CLIENT_FIELDS):
        return "presentation_only"
    return "combat_decode_required"


def _materialize_scope_record(
    source: CharacterAbilitySourceIR,
    draft: _ScopeDraft,
    role: CharacterAbilityMaterializationRole,
) -> CharacterAbilityScopeRecordIR:
    return CharacterAbilityScopeRecordIR(
        record_id=draft.record_id,
        occurrence_kind=draft.occurrence_kind,
        family=draft.family,
        semantic_kind=draft.effective_semantic_kind,
        nominal_scope=draft.nominal_scope,
        effective_scope=draft.effective_scope,
        admission_status=_admission_for_scope(draft.effective_scope),
        source=IRSource(
            source_path=source.source.source_path,
            raw_type=draft.family,
            raw_id=draft.record_id,
            evidence={
                "json_path": draft.path,
                "parent_branch_path": draft.parent_branch_path,
                "inherited_scope_record_id": draft.inherited_scope_record_id,
                "nominal_semantic_kind": draft.nominal_semantic_kind,
                "source_kind": source.source_kind,
                "avatar_id": source.avatar_id,
            },
        ),
        materialization_role=role,
        parent_record_id=draft.parent_record_id,
        parent_branch_path=draft.parent_branch_path,
        raw_fields=(
            cast(Mapping[str, Any], draft.raw_container)
            if draft.effective_scope == "decode_required"
            else {}
        ),
        coverage_status=cast(Any, _coverage_for_scope(draft.effective_scope)),
        blocked_reason=(
            "character_ability_scope_decode_required"
            if draft.effective_scope == "decode_required"
            else ""
        ),
    )


def _project_node(
    record: CharacterAbilityScopeRecordIR,
    raw_node: Mapping[str, Any],
    selector_branch: _SelectorBranchContext | None,
) -> tuple[CharacterAbilityProjectionIR | None, str]:
    opcode = record.family
    fields = {key: value for key, value in raw_node.items() if key != "$type"}
    if any(not isinstance(key, str) for key in fields):
        return None, "projection_field_name_invalid"
    raw_field_names = tuple(sorted(fields))
    projection_scope = cast(
        CharacterAbilityProjectionScope,
        record.effective_scope,
    )
    projection_kind: CharacterAbilityProjectionKind
    payload: dict[str, JSONValue] = {}
    ignored_fields: tuple[str, ...] = ()

    if opcode in {"BySkillPointActivated", "ByRankActivated"}:
        inverse = fields.get("Inverse", False)
        if not isinstance(inverse, bool):
            return None, "build_selector_inverse_not_boolean"
        selector_key: str | None = None
        selector_hash: int | None = None
        if opcode == "BySkillPointActivated":
            raw_key = fields.get("PointTriggerKey")
            if not isinstance(raw_key, str) or not raw_key:
                return None, "build_selector_point_trigger_key_missing"
            selector_key = raw_key
        else:
            trigger_key = fields.get("TriggerKey")
            raw_hash = (
                trigger_key.get("Hash")
                if isinstance(trigger_key, Mapping)
                else None
            )
            if not isinstance(raw_hash, int) or isinstance(raw_hash, bool):
                return None, "build_selector_rank_trigger_hash_missing"
            if set(trigger_key) != {"Hash"}:
                return None, "build_selector_rank_trigger_shape_invalid"
            selector_hash = raw_hash
        selector_json_path = str(record.source.evidence["json_path"])
        if selector_json_path.endswith(".$type"):
            selector_json_path = selector_json_path.removesuffix(".$type")
        branch_kind = "predicate_context"
        branch_root_path = str(record.parent_branch_path).removesuffix(".$type")
        true_subtree_path = ""
        false_subtree_path = ""
        if selector_branch is not None:
            branch_kind = selector_branch.branch_kind
            branch_root_path = selector_branch.branch_root_path
            true_subtree_path = selector_branch.true_subtree_path
            false_subtree_path = selector_branch.false_subtree_path
        if not branch_root_path:
            return None, "build_selector_branch_boundary_missing"
        projection_kind = "build_selector"
        payload = {
            "operation": "build_selector",
            "selector_kind": (
                "skill_point"
                if opcode == "BySkillPointActivated"
                else "rank"
            ),
            "selector_key": selector_key,
            "selector_hash": selector_hash,
            "inverse": inverse,
            "selector_json_path": selector_json_path,
            "branch_kind": branch_kind,
            "branch_root_path": branch_root_path,
            "true_subtree_path": true_subtree_path,
            "false_subtree_path": false_subtree_path,
        }
    elif opcode in {"SetEnergyBarState", "SetSummonerEnergyBarState"}:
        projection_kind = "special_resource_state_fragment"
        unknown_fields = sorted(
            set(fields) - _SPECIAL_RESOURCE_CLIENT_FIELDS - _SPECIAL_RESOURCE_FIELDS
        )
        if unknown_fields:
            return (
                None,
                "battle_data_projection_field_unclassified:"
                + ",".join(unknown_fields),
            )
        if not set(fields).intersection(_SPECIAL_RESOURCE_FIELDS):
            return None, "battle_data_projection_has_no_known_battle_field"
        ignored_fields = tuple(
            sorted(set(fields) & _SPECIAL_RESOURCE_CLIENT_FIELDS)
        )
        resource_fields = {
            key: fields[key]
            for key in sorted(set(fields) & _SPECIAL_RESOURCE_FIELDS)
        }
        payload = {
            "operation": "summoner_resource_state"
            if opcode == "SetSummonerEnergyBarState"
            else "resource_state",
            "resource_fields": cast(
                dict[str, JSONValue],
                _json_value(resource_fields),
            ),
        }
    elif opcode == "SetExcludeInMultiCharacterFormation":
        return None, "unit_topology_payload_shape_not_admitted_in_s0"
    elif opcode == "SetTeamLockTarget":
        projection_kind = "target_persistence"
        if set(fields) != {"TargetType", "Team"}:
            return None, "target_persistence_fields_invalid"
        team = fields.get("Team")
        target = fields.get("TargetType")
        target_payload, target_reason = _target_selector_projection(target)
        if not isinstance(team, str) or not team or target_reason:
            return None, target_reason or "target_persistence_team_missing"
        payload = {
            "operation": "team_lock_target",
            "team": team,
            "target_selector": target_payload,
            "persists_across_phases": True,
        }
    elif opcode in {
        "SetDeathDragonSkillButtonState",
        "SetUseTemporaryLockTarget",
    }:
        return None, "input_action_payload_shape_not_admitted_in_s0"
    elif opcode in {
        "ByInTurnBasedGameModeState",
        "ByIsMazeSkillAffectCurrentWave",
        "ByIsStageFirstWave",
    }:
        projection_kind = "environment_dependency"
        if fields:
            return None, "environment_predicate_parameters_unclassified"
        environment_key = {
            "ByInTurnBasedGameModeState": "turn_based_game_mode_state",
            "ByIsMazeSkillAffectCurrentWave": "maze_skill_affects_current_wave",
            "ByIsStageFirstWave": "stage_first_wave",
        }[opcode]
        payload = {
            "operation": "predicate_input",
            "environment_key": environment_key,
            "parameters": {},
        }
    elif opcode in {
        "SetDynamicValueByWaveStageCount",
        "SetDynamicValueByWorldLevel",
    }:
        projection_kind = "environment_dependency"
        if set(fields) != {"ContextScope", "WriteToKey"}:
            return None, "environment_projection_fields_invalid"
        write_to_key = fields.get("WriteToKey")
        context_scope = fields.get("ContextScope")
        if (
            not isinstance(write_to_key, str)
            or not write_to_key
            or not isinstance(context_scope, str)
            or not context_scope
        ):
            return None, "environment_projection_value_invalid"
        payload = {
            "operation": "dynamic_value_input",
            "environment_key": (
                "wave_stage_count"
                if opcode == "SetDynamicValueByWaveStageCount"
                else "world_level"
            ),
            "write_to_key": write_to_key,
            "context_scope": context_scope,
        }
    else:
        return None, "projection_opcode_not_supported"

    try:
        projection = CharacterAbilityProjectionIR(
            projection_id=_stable_id(
                "character_ability_projection",
                record.record_id,
            ),
            scope_record_id=record.record_id,
            projection_scope=projection_scope,
            projection_kind=projection_kind,
            source_opcode=opcode,
            payload=payload,
            raw_field_names=raw_field_names,
            ignored_client_fields=ignored_fields,
            source=record.source,
            coverage_status="lowered",
        )
    except (TypeError, ValueError) as exc:
        return None, f"projection_contract_rejected:{exc}"
    return projection, ""


def _target_selector_projection(
    value: Any,
) -> tuple[dict[str, JSONValue], str]:
    if not isinstance(value, Mapping) or set(value) != {"$type", "Alias"}:
        return {}, "target_persistence_selector_missing"
    raw_type = value.get("$type")
    alias = value.get("Alias")
    if _short_type(raw_type) != "TargetAlias" or not isinstance(alias, str) or not alias:
        return {}, "target_persistence_selector_ambiguous"
    return {"kind": "target_alias", "alias": alias}, ""


def _family_rows_from_drafts(
    drafts: Iterable[_ScopeDraft],
    source_path: str,
) -> tuple[CharacterAbilityFamilyIR, ...]:
    counts: Counter[tuple[str, str, str, str]] = Counter()
    scopes: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    for draft in drafts:
        key = (
            draft.occurrence_kind,
            draft.family,
            draft.nominal_semantic_kind,
            draft.nominal_scope,
        )
        counts[key] += 1
        scopes[key][draft.effective_scope] += 1
    return tuple(
        CharacterAbilityFamilyIR(
            family=key[1],
            occurrence_kind=cast(CharacterAbilityOccurrenceKind, key[0]),
            semantic_kind=cast(CharacterAbilitySemanticKind, key[2]),
            nominal_scope=cast(CharacterAbilityScope, key[3]),
            occurrence_count=counts[key],
            source_paths=(source_path,),
            effective_scope_counts=dict(sorted(scopes[key].items())),
        )
        for key in sorted(counts)
    )


def _merge_family_rows(
    rows: Iterable[CharacterAbilityFamilyIR],
) -> tuple[CharacterAbilityFamilyIR, ...]:
    counts: Counter[tuple[str, str, str, str]] = Counter()
    source_paths: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    scopes: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    for row in rows:
        key = (
            row.occurrence_kind,
            row.family,
            row.semantic_kind,
            row.nominal_scope,
        )
        counts[key] += row.occurrence_count
        source_paths[key].update(row.source_paths)
        scopes[key].update(row.effective_scope_counts)
    return tuple(
        CharacterAbilityFamilyIR(
            family=key[1],
            occurrence_kind=cast(CharacterAbilityOccurrenceKind, key[0]),
            semantic_kind=cast(CharacterAbilitySemanticKind, key[2]),
            nominal_scope=cast(CharacterAbilityScope, key[3]),
            occurrence_count=counts[key],
            source_paths=tuple(sorted(source_paths[key])),
            effective_scope_counts=dict(sorted(scopes[key].items())),
        )
        for key in sorted(counts)
    )


def _validate_family_reconciliation(
    records: tuple[CharacterAbilityScopeRecordIR, ...],
    families: tuple[CharacterAbilityFamilyIR, ...],
) -> None:
    expected_counts: Counter[tuple[str, str, str, str]] = Counter()
    expected_paths: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    expected_scopes: dict[
        tuple[str, str, str, str], Counter[str]
    ] = defaultdict(Counter)
    for record in records:
        if record.materialization_role != "selected":
            continue
        nominal_semantic = record.source.evidence.get("nominal_semantic_kind")
        if not isinstance(nominal_semantic, str):
            raise ValueError("scope record nominal semantic evidence is missing")
        if _scope_for_semantic(
            cast(CharacterAbilitySemanticKind, nominal_semantic)
        ) != record.nominal_scope:
            raise ValueError("scope record nominal semantic evidence is inconsistent")
        key = (
            record.occurrence_kind,
            record.family,
            nominal_semantic,
            record.nominal_scope,
        )
        expected_counts[key] += 1
        expected_paths[key].add(record.source.source_path)
        expected_scopes[key][record.effective_scope] += 1

    actual: dict[tuple[str, str, str, str], CharacterAbilityFamilyIR] = {}
    for family in families:
        key = (
            family.occurrence_kind,
            family.family,
            family.semantic_kind,
            family.nominal_scope,
        )
        if key in actual:
            raise ValueError("duplicate character ability family identity")
        actual[key] = family
    if set(actual) != set(expected_counts):
        raise ValueError("character ability family references do not close")
    for key, family in actual.items():
        if (
            family.occurrence_count != expected_counts[key]
            or family.source_paths != tuple(sorted(expected_paths[key]))
            or dict(family.effective_scope_counts)
            != dict(sorted(expected_scopes[key].items()))
        ):
            raise ValueError("character ability family summary is inconsistent")


def _external_dependencies(
    records: tuple[CharacterAbilityScopeRecordIR, ...],
    projections: tuple[CharacterAbilityProjectionIR, ...],
    *,
    source_catalog_complete: bool,
    family_filtered: bool,
) -> tuple[CharacterAbilityExternalDependencyIR, ...]:
    if any(
        record.materialization_role == "selected"
        and record.family == "SetExcludeInMultiCharacterFormation"
        and record.effective_scope == "battle_data_projection"
        for record in records
    ) or any(
        projection.projection_kind == "unit_topology" for projection in projections
    ):
        return ()
    status = cast(
        Literal["external_content_dependency", "not_proven"],
        (
            "external_content_dependency"
            if source_catalog_complete and not family_filtered
            else "not_proven"
        ),
    )
    return (
        CharacterAbilityExternalDependencyIR(
            dependency_id=_stable_id(
                "character_ability_external_dependency",
                "unit_topology",
                status,
            ),
            projection_kind="unit_topology",
            status=status,
            reason=(
                "current complete character ability source catalog has no unit-topology producer"
                if status == "external_content_dependency"
                else "filtered source or family view cannot establish producer absence"
            ),
        ),
    )


def _validate_external_dependencies(
    dependencies: tuple[CharacterAbilityExternalDependencyIR, ...],
    records: tuple[CharacterAbilityScopeRecordIR, ...],
    projections: tuple[CharacterAbilityProjectionIR, ...],
    *,
    source_catalog_complete: bool,
    family_filtered: bool,
) -> None:
    expected = _external_dependencies(
        records,
        projections,
        source_catalog_complete=source_catalog_complete,
        family_filtered=family_filtered,
    )
    if tuple(item.to_json() for item in dependencies) != tuple(
        item.to_json() for item in expected
    ):
        raise ValueError("character ability external dependency state is inconsistent")


def _coverage_summary(
    sources: tuple[CharacterAbilitySourceIR, ...],
    records: tuple[CharacterAbilityScopeRecordIR, ...],
    projections: tuple[CharacterAbilityProjectionIR, ...],
    families: tuple[CharacterAbilityFamilyIR, ...],
) -> dict[str, JSONValue]:
    selected_records = tuple(
        record
        for record in records
        if record.materialization_role == "selected"
    )
    by_kind = Counter(record.occurrence_kind for record in selected_records)
    by_scope = Counter(record.effective_scope for record in selected_records)
    typed_by_scope = Counter(
        record.effective_scope
        for record in selected_records
        if record.occurrence_kind == "typed_node"
    )
    family_by_kind = Counter(family.occurrence_kind for family in families)
    typed_node_count = by_kind["typed_node"]
    non_gameplay_typed_node_count = typed_by_scope["non_gameplay"]
    return {
        "source_count": len(sources),
        "character_main_source_count": sum(
            source.source_kind == "character_main" for source in sources
        ),
        "character_shared_source_count": sum(
            source.source_kind == "character_shared" for source in sources
        ),
        "typed_node_count": typed_node_count,
        "event_count": by_kind["event"],
        "structural_entry_count": by_kind["structural_entry"],
        "typed_node_family_count": family_by_kind["typed_node"],
        "event_family_count": family_by_kind["event"],
        "structural_entry_family_count": family_by_kind["structural_entry"],
        "record_counts_by_effective_scope": dict(sorted(by_scope.items())),
        "typed_node_counts_by_effective_scope": dict(
            sorted(typed_by_scope.items())
        ),
        "typed_node_included_count": typed_node_count
        - non_gameplay_typed_node_count,
        "typed_node_non_gameplay_count": non_gameplay_typed_node_count,
        "retired_non_gameplay_count": sum(
            record.effective_scope == "non_gameplay"
            and record.admission_status == "retired"
            for record in selected_records
        ),
        "gameplay_admitted_record_count": sum(
            record.admission_status == "gameplay_candidate"
            for record in selected_records
        ),
        "materialized_record_count": len(records),
        "ancestor_context_record_count": len(records) - len(selected_records),
        "decode_required_count": by_scope["decode_required"],
        "projection_count": len(projections),
        "blocked_projection_count": sum(
            projection.coverage_status == "blocked"
            for projection in projections
        ),
    }


def _freeze_bytes_mapping(
    value: Mapping[str, bytes],
    name: str,
) -> Mapping[str, bytes]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    copied: dict[str, bytes] = {}
    for path, raw_bytes in value.items():
        if not isinstance(path, str) or not path:
            raise ValueError(f"{name} contains an invalid path")
        if not isinstance(raw_bytes, bytes):
            raise TypeError(f"{name} values must be bytes")
        copied[path] = bytes(raw_bytes)
    return MappingProxyType(copied)


def _canonical_string_tuple(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be a tuple")
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"{name} must contain non-empty strings")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} must be unique and sorted")
    return tuple(values)


def _require_sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be lowercase sha256 hex")
    return value


def _hash_frame(digest: Any, tag: str, *parts: bytes) -> None:
    tag_bytes = tag.encode("ascii")
    digest.update(len(tag_bytes).to_bytes(8, "big"))
    digest.update(tag_bytes)
    digest.update(len(parts).to_bytes(8, "big"))
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)


def _compute_source_fingerprint(
    inventory_bytes: Mapping[str, bytes],
    candidates: tuple[_SourceCandidate, ...],
    source_bytes: Mapping[str, bytes],
    fingerprint_kind: str,
    source_filter: tuple[str, ...],
) -> str:
    if fingerprint_kind not in {"complete", "partial"}:
        raise ValueError("invalid character ability fingerprint kind")
    normalized_filter = _canonical_string_tuple(source_filter, "source_filter")
    if (fingerprint_kind == "complete") != (not normalized_filter):
        raise ValueError("character ability fingerprint selection is inconsistent")
    inventory = _freeze_bytes_mapping(inventory_bytes, "inventory_bytes")
    ability_sources = _freeze_bytes_mapping(source_bytes, "source_bytes")
    if not isinstance(candidates, tuple) or any(
        type(candidate) is not _SourceCandidate for candidate in candidates
    ):
        raise TypeError("character ability fingerprint candidates are invalid")
    canonical_candidates = tuple(
        sorted(candidates, key=lambda candidate: candidate.relative_path)
    )
    candidate_paths = tuple(
        candidate.relative_path for candidate in canonical_candidates
    )
    if len(candidate_paths) != len(set(candidate_paths)):
        raise ValueError("character ability fingerprint candidates are duplicated")
    available_paths = set(candidate_paths)
    selected_paths = set(normalized_filter) if normalized_filter else available_paths
    if set(ability_sources) != selected_paths:
        raise ValueError("character ability fingerprint source set is inconsistent")

    digest = sha256()
    _hash_frame(digest, "schema", b"hsr.character_ability_source_fingerprint.v2")
    _hash_frame(digest, "fingerprint_kind", fingerprint_kind.encode("ascii"))
    for path in sorted(inventory):
        _hash_frame(digest, "inventory", path.encode("utf-8"), inventory[path])
    for candidate in canonical_candidates:
        _hash_frame(
            digest,
            "selection_mapping",
            *(field.encode("utf-8") for field in candidate.manifest_fields()),
        )
    for path in normalized_filter:
        _hash_frame(digest, "source_filter", path.encode("utf-8"))
    for path in sorted(ability_sources):
        _hash_frame(
            digest,
            "ability_source",
            path.encode("utf-8"),
            ability_sources[path],
        )
    return digest.hexdigest()


def _catalog_identity(
    snapshot_id: str,
    source_fingerprint: str,
    fingerprint_kind: str,
    source_filter: tuple[str, ...],
    family_filter: tuple[str, ...],
    sources: tuple[CharacterAbilitySourceIR, ...],
    records: tuple[CharacterAbilityScopeRecordIR, ...],
    projections: tuple[CharacterAbilityProjectionIR, ...],
    families: tuple[CharacterAbilityFamilyIR, ...],
    dependencies: tuple[CharacterAbilityExternalDependencyIR, ...],
    issues: tuple[CharacterAbilityProjectionIssue, ...],
) -> str:
    semantics = {
        "schema": "hsr.character_ability_scope_catalog.identity.v2",
        "snapshot_id": snapshot_id,
        "source_fingerprint": source_fingerprint,
        "fingerprint_kind": fingerprint_kind,
        "source_filter": list(source_filter),
        "family_filter": list(family_filter),
        "sources": [source.to_json() for source in sources],
        "records": [record.to_json() for record in records],
        "projections": [projection.to_json() for projection in projections],
        "families": [family.to_json() for family in families],
        "external_dependencies": [item.to_json() for item in dependencies],
        "issues": [issue.to_json() for issue in issues],
    }
    encoded = json.dumps(
        semantics,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"character_ability_scope_catalog:{sha256(encoded).hexdigest()}"


def _normalized_filter(values: Iterable[str], name: str) -> frozenset[str]:
    result: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must contain non-empty strings")
        result.add(value.strip())
    return frozenset(result)


def _stable_id(prefix: str, *parts: str) -> str:
    identity = "\0".join(parts).encode("utf-8")
    return f"{prefix}:{sha256(identity).hexdigest()[:24]}"


def _short_type(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.rsplit(".", 1)[-1]


def _same_object_scope_markers(
    left: CharacterAbilityScopeRecordIR,
    right: CharacterAbilityScopeRecordIR,
) -> bool:
    if {
        left.occurrence_kind,
        right.occurrence_kind,
    } != {"event", "typed_node"}:
        return False
    left_path = cast(str, left.source.evidence["json_path"])
    right_path = cast(str, right.source.evidence["json_path"])
    return left_path.rsplit(".", 1)[0] == right_path.rsplit(".", 1)[0]


def _child_path(path: str, key: Any) -> str:
    key_text = str(key)
    if key_text and all(character.isalnum() or character == "_" for character in key_text):
        return f"{path}.{key_text}"
    return f"{path}[{json.dumps(key_text, ensure_ascii=True)}]"


def _json_value(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("character ability JSON object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported character ability source value:{type(value).__name__}")


__all__ = [
    "CharacterAbilityDocumentProjection",
    "CharacterAbilityProjectionIssue",
    "CharacterAbilityRawSnapshot",
    "CharacterAbilityScopeProjectionCatalog",
    "build_character_ability_raw_snapshot",
    "build_character_ability_scope_projection",
    "character_ability_snapshot_fingerprint",
    "classify_character_ability_document",
]
