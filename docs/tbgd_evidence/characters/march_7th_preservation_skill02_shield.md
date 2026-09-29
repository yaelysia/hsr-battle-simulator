# March 7th (Preservation) Skill02 shield/control-flow evidence

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Raw maturity: `manually_confirmed`, with unrelated ordinary-character cross-checks for the SkillParam producer/binding model and independent postfix-expression samples.
- **2026-09-23:** the selected base-shield equation is additionally `cross_validated` with public gameplay explanation. Native implementation and local runtime execution are separate evidence dimensions.
- Scope: ordinary Skill02 numeric authority, typed parameter bindings, target/control flow, lifetime expression, trace/eidolon branches, shield lifecycle hooks, dispellability, snapshot-routing inputs, public base-shield model and explicitly remaining questions.
- Battle-scope verdict: mixed at Ability-operation level; battle execution retained, presentation operations excluded; same-ID RtBattle records are false friends.
- Runtime production code changed: no. No new simulator or gameplay run.

## Public model reconciliation — 2026-09-23

The [public mechanics reconciliation](../shared/public_mechanics_healing_shield_reconciliation_v1.md) corrects the earlier blanket restriction against using community formulas unless a native GameCore evaluator becomes available. The [former complete record](https://github.com/yaelysia/hsr-battle-simulator/blob/61541a5c692314bbd33e5ac835b12da0044dd8ce/docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md) remains available for audit.

The [KQM March guide](https://hsr.keqingmains.com/march-7th/), marked Version 1.5, explains the ordinary shield as a percentage of March's DEF plus a flat amount. Joining that interpretation to the pinned coefficient/flat bindings gives:

```text
base shield = shield percentage * March effective DEF + flat shield value
Lv11: 0.589 * March DEF + 802.75
Lv12: 0.608 * March DEF + 845.5
```

These are **usable gameplay equations with explicit provenance**, not a claim that the native function body has been recovered. The guide's summarized coefficients are not substituted for pinned decimals. Creation scaling belongs to March; defensive properties of the recipient affect the damage the shield must absorb and are a different stage.

For a model example with March DEF=2000, Skill02 Lv12 and no shield-generation modifier, the predicted initial amount is 2061.5 before rounding. This is a calculation, not an observed game result.

A separate [KQM original experiment by bobrokrot, 2023-05-16](https://hsr-tickets.keqingmains.com/transcripts/dmg-reduction-before-shields) supports damage reduction before shield loss: its reported same-attack comparison is 154 under 10% reduction versus 171 after expiry. This externally tested ordering is positive gameplay evidence even though the native shield evaluator is not exported. It does not establish snapshot capture or zero-shield modifier destruction. The reconciliation record retains its setup, source and validation limits.

## Correction history

This record supersedes older archaeology claims that:

1. pinned ExcelOutput/AvatarSkillConfig.json had no ordinary March SkillID100102 row — it does; the earlier result was a large-file/search false negative;
2. the main shield initializes on OnCreate — exact pin shows OnStack -> InitShield, Stacking=Replace, and OnDestroy -> RemoveShield;
3. shield dispellability was unresolved — AvatarStatusConfig10010011 closes CanDispel=true;
4. absence of the native ShieldByCasterDefence body requires withholding the basic publicly supported DEF-percentage-plus-flat equation — it does not.

ILBattleAvatarSkill100102 remains a real numeric-ID collision from deferred RtBattle content and is rejected as ordinary March authority.

## Gameplay semantic model

The ordinary Skill02 is a selected-ally support action. The pinned source chain accounts for selected ally targeting, DEF-based shield operands, base lifetime plus trace extension, HP-gated aggro injection, trace-gated dispel, rank healing, replacement/removal hooks, dispellability and snapshot-routing inputs.

Public gameplay evidence supplies the base equation and guides specific tests of remaining behavior. It does not change a pinned value, fabricate a binding or recover the native snapshot algorithm.

## Ordinary source chain

```text
AvatarConfig[AvatarID=1001]
  -> ordinary SkillID100102
  -> ExcelOutput/AvatarSkillConfig.json[SkillID=100102,Level].ParamList[index]
  -> Config/ConfigCharacter/Avatar/Avatar_Mar_7th_00_Config.json
       SkillParam(Skill02,index) -> DynamicHash
  -> Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json
       Skill02 control flow
  -> AddModifier(MAvatar_March7th_00_BPSkill_Shield)
  -> shield modifier callbacks/property consumers
```

Pinned AvatarSkillConfig blob: `a5416ced941c247d475b2aaa83277b9cdf474dd9`.

Audited rows:

- Level11: `[0.589,3,0.3,802.75,5]`
- Level12: `[0.608,3,0.3,845.5,5]`

These values remain raw-source authority. Their meanings come from the bindings/consumers and the explicitly attributed gameplay interpretation, not positional guessing.

## Typed bindings and consumer mapping

| Index | Dynamic hash | Confirmed consumer role |
| --- | --- | --- |
| 0 | `-1091495116` | MDF_ShieldPercentage -> InitShield.ShieldPercentage. |
| 1 | `-1016136907` | Base shield lifetime operand. |
| 2 | `398047946` | Selected-target HP-ratio threshold. |
| 3 | `1935511666` | MDF_ShieldValue -> InitShield.ShieldValue. |
| 4 | `-1672381420` | HP-gated MDF_AggroUp -> AggroAddedRatio. |

CharacterConfig declares FriendSelect. Ability application targets AbilityTargetEntity. The comparison is GreaterEqual: HP ratio>=SkillParam[2] injects SkillParam[4] as aggro input; otherwise the same shield receives 0. No generic continuous HP watcher is inferred from that application predicate.

## Parameter-family authority

The audited ordinary samples support distinct producer/index spaces:

- SkillParam -> AvatarSkillConfig[SkillID,Level].ParamList[index].
- SkillTreeParam -> AvatarSkillTreeConfig[PointID/PointTriggerKey].ParamList[index].
- SkillRank -> AvatarRankConfig[RankID/rank trigger].Param[index].
- SkillAddLevelList -> independent skill-level increment mechanism.

Dan Heng independently cross-checks the ordinary producer/binding/consumer pattern. W02's March producer gap is closed; broader family exhaustiveness remains separate.

## Trace and rank branches

Pinned ordinary data confirms PointB1 DispelStatus on AbilityTargetEntity, Numbers=1, Order=LastAdded. PointB2's point1001102 has `ParamList=[1]`; its zero-based index0 supplies the lifetime increment. Skill02 writes this value to _Tree02_LifeTimeAdd, otherwise 0. Rank06's AvatarRankConfig100106 has `Param=[0.04,106]`; Skill02 injects these heal operands when active, otherwise zeros.

Trace/rank inputs remain distinct from the five ordinary Skill02 operands.

## Lifetime and postfix-expression closure

The supplied lifetime is `SkillParam[1] + _Tree02_LifeTimeAdd`. Independent exact-pin samples establish opcode bytes 0x02 addition, 0x03 subtraction and 0x04 multiplication. For rows with SkillParam[1]=3, the supplied lifetime is 3 without PointB2 and 4 with it.

This does not by itself prove all native timer/reapplication rules. Public duration descriptions and targeted gameplay tests can provide additional behavioral evidence without requiring the timer's source code.

## Formal main-shield lifecycle

MAvatar_March7th_00_BPSkill_Shield has Shield in BehaviorFlagList, UseSnapshotEntity=true and Stacking=Replace. Its exact hooks are:

- OnCreate: resilience/effect setup, not InitShield.
- OnStack: InitShield(ModifierOwnerEntity), FormulaType=ShieldByCasterDefence, injected percentage/flat inputs; also applies injected AggroAddedRatio.
- OnDestroy: RemoveShield and resilience reset.
- OnPhase1: Rank06 heal branch when its injected heal operand is positive.

These are source-backed application/reapplication/removal surfaces. The base-shield equation is now independently explained above; generic replacement ordering remains a distinct question.

## Main-shield dispellability

Pinned AvatarStatusConfig10010011 has ModifierName=MAvatar_March7th_00_BPSkill_Shield, StatusType=Buff and CanDispel=true. The ordinary main shield is therefore source-confirmed dispellable. The neighboring Rank02 shield is a distinct status, also dispellable, not the same modifier.

## Snapshot subsystem: routing versus capture

The pin exports GameCoreConstValue.SnapshotEntityInheritBlackList, including Defence, Attack, Shield/MaxShield, MaxStance and SPRatio; TargetAliasConfig entries SnapshotEntityList, SnapshotEntityActualOwner and SnapshotPropertyEntity; and TargetOperationConfig.GetSnapshot -> RPG.GameCore.TargetMapSnapshotEntity.

An independent Luka DOT with UseSnapshotEntity=true reads Attack from SnapshotPropertyEntity in OnCreate. This proves battle-state routing rather than presentation metadata; it does not prove copy-all at cast time.

The base equation identifies March's DEF as the creation scaling stat. Exact capture moment, selective copy/redirection, blacklist behavior and refresh still need specific evidence. Public stat-change experiments are a valid way to test their observable consequences.

The nearby Skill02 Phase02 `SetDynamicValueByProperty(Caster.Defence -> CasterDefence)` is **not explicitly passed into the ordinary main-shield AddModifier.DynamicValues**. Knowing the public equation must not turn that nearby read into a fabricated direct binding. Preserve the actual formula-family/binding route.

## Shield depletion / shield-change negative evidence

Pinned shared data exposes OnListenInitShield and OnListenShieldChange. Independent Gepard shields use Shield + OnStack InitShield + OnDestroy RemoveShield + Replace. Their shield-change callbacks inspect state for UI/resource behavior, but do not remove the shield modifier there.

Thus OnListenShieldChange is not itself proof that zero shield immediately destroys the modifier. March's main shield has no local shield-change callback closing that transition. The exact depletion/expiry-to-destruction connection remains unestablished here, separate from the externally supported mitigation-before-shield-loss rule.

## Separate Rank02 shield

AvatarRankConfig[RankID=100102] is March Rank2, not ordinary SkillID100102. Its `Param=[0.24,3,320]` feeds a separate explicit expression `0.24 * CasterDefence + 320`, lifetime 3.

This corroborates the postfix operators. It does not substitute for the main Skill02's formula family, parameters or modifier identity.

## Rejected same-ID candidate and filtering

ExcelOutput/ILBattleAvatarSkill.json contains an unrelated RtBattle ID100102 with `ParamList=[6,0.3,6,1,6]`. Numeric equality is insufficient identity evidence; these values remain rejected.

Retain property reads, predicates, dispel, HP comparisons, dynamic inputs, modifier/shield/heal/aggro consumers and callback references. Camera, animation waits, VFX and choreography remain presentation unless an independent battle-state dependency proves otherwise. Animation time is not logical action/timeline authority.

## Guardrails and remaining questions

A failed large-file search is not omission proof. Shared numeric IDs, filenames and matching floats are not semantic joins. FormulaType names alone do not reveal native bodies, but source operands plus credible public mechanics can establish useful equations. Snapshot flags do not freeze an entire character; Replace does not define universal old/new callback order; shield-change does not by itself imply destruction. Raw SP names are not renamed to player Skill Points without their own evidence.

Selected base-shield arithmetic and creator identity are no longer listed as wholly unknown. Remaining questions are exact capture/refresh, rounding or special caps, shield-generation modifier composition outside this base sample, replacement/old-state visibility, duration/depletion-to-destruction and event ordering where behavior differs.

These can be advanced by controlled public gameplay evidence or new source discriminators as well as native code. No community value is silently promoted to an absent pinned row, and no missing backend implementation blocks the research.
