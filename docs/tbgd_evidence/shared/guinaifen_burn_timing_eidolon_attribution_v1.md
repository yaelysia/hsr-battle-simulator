# Guinaifen Burn follow-up: Firekiss timing, E2 coefficient and E4 attribution v1

## 1. Scope and result

Reviewed 2026-09-23. Evidence parent: `1f7211ca36bc65c93afbd937fe7f7fe780a190f7`. Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains Draft and documentation/evidence-only.

The interrupted task had already published the [Burn description/application/tick/extra-trigger chain][BASE] and checkpoint `5792067441`. This follow-up reuses that work instead of rediscovering it. It advances three selected questions: whether a fresh Firekiss stack amplifies its triggering Burn; whether E2 adds to or multiplies the Burn coefficient; and whose damage qualifies for E4 energy.

**Results:** adopt the attributed ordinary gameplay model that the triggering Burn does not benefit from the Firekiss stack it generates; establish E2's source-authored `p + 0.4` branch; and close the selected E4 `Rank04 -> SpAdded -> owner-filtered ModifySPNew` chain. Firekiss's broad Burn trigger and E4's own-damage trigger are different rules. Neither native evaluator recovery nor backend implementation is a prerequisite for recording these results.

Exact raw claims are `manually_confirmed`. Text/model reconciliations are identified separately as `cross_validated` interpretations, not new gameplay measurements. No simulator, game session, Direct, tests or workflow was run. No local-runtime E is added. W08/W09/W10 and broader corpus obligations are not globally closed.

## 2. Evidence register

### Re-read pinned sources

| Ref | Path / exact selected identity | Blob |
| --- | --- | --- |
| S1 | [ExcelOutput/AvatarRankConfig.json][S1], RankID121002 and RankID121004; Rank/Trigger/Param/RankAbility/Desc fields | `ecd3581d9307d3ac94123e0c30983ef6e627f4f3` |
| S2 | [Config/ConfigCharacter/Avatar/Avatar_Guinaifen_00_Config.json][S2], SkillP01 entry and DynamicValues.Floats SkillRank reads | `8f5d214f18593f1d1f9162b36844b72c46928ac1` |
| S3 | [Config/ConfigAbility/Avatar/Avatar_Guinaifen_00_Ability.json][S3], Skill02_Phase02 and GlobalModifiers passive/Oil/Oil_Sub/Rank04 | `011c0f8851b6e594183764e6ab71ec0e21eac991` |

Useful read ranges: S1 lines5000-5145; S3 lines1450-2005 for the passive and Firekiss, and the final Rank04 modifier through end-of-file for E4. Named occurrence selectors below identify objects by their serialized names; they are not invented numeric array offsets.

Reused, not newly enumerated: BASE's Skill121002 Lv10 `p=2.18208`, Skill121004 Lv10 Firekiss `v=0.07/max3`, and exact SkillDesc.Hash -> same-pin TextMapCHS joins. The talent description key `1257547725356166088` narrates Firekiss following Burn damage. The new Rank rows instead serialize `Desc="AvatarRankDesc_121002"` and `Desc="AvatarRankDesc_121004"`; this session does not claim a newly decoded same-pin rank-localization hash. Published Eidolon wording below supplies the explanation alongside the newly read raw operands and predicates.

### Public descriptions and authored explanations

All pages were read on 2026-09-23. A historical guide is not silently treated as a statement about every later patch.

| Ref | Source / context | What is used; evidence limit |
| --- | --- | --- |
| P1 | [KQM SRL Guinaifen][P1], Talent and Eidolon sections | Published skill wording distinguishes Burn-triggered Firekiss from E4's Burn inflicted by Guinaifen; E2 names a 40% multiplier increase and E4 names 2 Energy. This is reproduced game text, not a fresh gameplay experiment or exact-pin localization extraction. |
| P2 | [The Vizier's comment on Honey Hunter][P2], dated 2023-10-29 06:09, under the Guinaifen comments | Explicitly states that a triggering Burn, including extra activation, cannot benefit from the newly generated Firekiss stack. An identifiable original community explanation, not a documented controlled test. |
| P3 | [Signed Guinaifen analysis on TapTap][P3], published 2023-11-02, body credited to 澈晓嘟噜噜, posted under 游创工坊 | Explicitly explains post-damage Firekiss and separate stacking from multiple Burns. Other hosts reproduce this article; they are not additional independent tests. Its unrelated gearing and Technique wording is not adopted as authority. |
| P4 | [KQM Kafka guide][P4], Version1.2, Mechanics and Skill sections | Ordinary detonation preserves the original DoT owner's scaling rather than transferring it to the detonator. Used for the role distinction, not a complete new Kafka source audit. |

Descriptions identify the declared mechanic; the graph resolves specific operands and predicates; attributed community explanations can establish a useful observable model. Agreement among prose sources does not prove a native dispatcher implementation, and unmeasured assertions are not relabeled as controlled experiments.

## 3. Firekiss: the fresh layer is not a retroactive damage multiplier

BASE left a narrow question because the skill text says Firekiss follows Burn damage whereas the exact installer is under `GlobalModifiers.MAvatar_Guinaifen_00_Oil._CallbackList[Event=OnBeforeBeingHitAll]`.

P2 and P3 answer the observable question explicitly and agree with the linked talent wording: **the triggering Burn uses the already-applicable Firekiss state, not the fresh layer generated by that damage.** This is now an accepted, attributed ordinary gameplay interpretation rather than an unexplained timing question. It is not a new exact-pin game measurement.

Retain the raw callback name unchanged. S3 still has:

```text
Oil.OnBeforeBeingHitAll
  -> ByDamageSourceContainBehaviorFlag([STAT_DOT_Burn])
  -> resolve MaxLayer (with a separate E6 branch)
  -> AddModifier(ModifierOwnerEntity, Oil_Sub,
       Chance=SkillP01[0], LifeTime=SkillP01[4],
       LayerAddWhenStack=1, MDF_PropertyValue2=SkillP01[3])
Oil_Sub.OnStack
  -> read Layer
  -> MDF_PropertyValue = Layer * MDF_PropertyValue2
  -> StackProperty(AllDamageTypeTakenRatio, MDF_PropertyValue)
```

Registration under a before-hit callback is not proof that the in-flight damage calculation rereads the just-written property. The observable no-retroactive-benefit rule does not select among a latched damage context, delayed mutation visibility or another native explanation. Those remain unproven implementation explanations, not reasons to withhold the supported gameplay rule.

The adjacent `MDF_IsAttack=2` write and `OnAfterBeingAttacked -> MDF_IsAttack=0` are retained as raw working-state writes. No consumer establishing their timing role was traced here; they must not be invented into a latch or delay mechanism.

For an isolated model, let K be the otherwise unchanged Burn damage before Firekiss and n the already-applicable layer count. With talent Lv10, no E6 and no other damage-taken modifier:

```text
this Burn damage = K * (1 + 0.07*n)
if this damage's Firekiss application succeeds:
  subsequent layer count = min(n+1, 3)
```

Illustrative prediction with K=1000, starting at zero layers, all applications successful and no intervening expiry: four separate eligible Burn events deal 1000, 1070, 1140, 1210. These are not measured values and not four natural ticks from one two-turn Burn; extra activations or other eligible Burn events can supply the sequence. A resisted application does not increment n.

## 4. E2: a conditional addition to the stored coefficient

S1 RankID121002 has Rank2, Trigger.Hash523552506, `Param[0].Value=0.4`, and an empty RankAbility list. S2 maps hash1589728048 to `SkillRank(Rank02,index0)`.

At S3 `AbilityList[Name=Avatar_Guinaifen_00_Skill02_Phase02].OnStart[1].OnProjectileHit[1].TaskList[0]`, the predicate is:

```text
ByAnd(
  ByRankActivated(TriggerKey.Hash=523552506),
  ByContainBehaviorFlag(ParamEntity, STAT_DOT_Burn))
```

The success AddModifier still installs `MCommon_DOT_Burn` with `StackingFlag=CharacterSkill`, but its `Modifier_Burn_DamagePercentage` uses `OpCodes=AQABAQIR`, hashes `[-883252236,1589728048]`. The failure branch uses only `-883252236`. The retained postfix vocabulary interprets these as `p+0.4` versus p.

Thus a selected effective Skill02 Lv10 application gives:

```text
not already Burned, or E2 inactive: p = 2.18208
already Burned and E2 active:      p = 2.58208
not:                              p = 2.18208 * 1.4
```

At effect ATK3000 and one layer, the corresponding pre-modifier base terms are 6546.24 and 7746.24, a difference of 1200. These are arithmetic predictions, not gameplay runs. The level here is the effective selected skill level; Eidolon skill-level bonuses are not silently added a second time.

The gate asks whether the target has the Burn behavior flag, not whether that Burn was applied by Guinaifen. Another source's Burn can satisfy the authored precondition. Conversely, simply obtaining E2 does not make an initially unburned target satisfy it. This is an application-time parameter branch, not an in-place instruction to multiply every existing Burn or its last displayed damage.

## 5. E4: raw 2 -> exact parameter transport -> own-damage energy request

S1 RankID121004 has Rank4, Trigger.Hash1686351920, `Param[0].Value=2`, `Desc="AvatarRankDesc_121004"`, and `RankAbility=[]`. S2 maps hash-1921537208 to `SkillRank(Rank04,index0)`. RankID121004 is not the talent's SkillID121004: their numeric ID equality does not join the parameter spaces.

The activation is inside the existing passive, so an empty RankAbility list is not absence of an E4 mechanic:

```text
SkillP01 -> Avatar_Guinaifen_00_PassiveSkill01
 -> MAvatar_GuiNaiFen_00_PassiveSkill01_Modifier
 -> OnListenCharacterCreate.CallbackConfig[1]
    ByRankActivated(1686351920)
    -> AddModifier(AllDarkTeam, MAvatar_Guinaifen_00_Rank04,
         DynamicValues.SpAdded = read hash-1921537208)
 -> Rank04.OnAfterBeingHitAll
    -> eligibility predicates
    -> ModifySPNew(Caster, AddValue=read hash1693335963)
```

The Rank04 modifier declares working hash1693335963 with ReadInfo.Type=None. The named SpAdded transfer and its destination request use the already-established named-value/working-reader pattern; no new general hash algorithm is claimed.

All four serialized eligibility predicates are retained:

| Predicate | Exact distinguishing input |
| --- | --- |
| ByAttackType | ParamEntity; AttackTypes=[DOT] |
| ByIsDamageType | ModifierOwnerEntity; DamageTypeList=[Fire] |
| ByIsSplitDamage | ModifierOwnerEntity; Inverse=true |
| ByTargetListIntersects | ParamEntityActualOwner intersects Caster; both AliveOnly fields=false |

P1's E4 wording identifies the resource as Guinaifen's Energy. Therefore the selected +2 raw AddValue is an energy-generation request, not two team Skill Points. Final energy gain after any general regeneration modifiers or cap is not newly evaluated here.

The actual-owner predicate is decisive: the originator of the DoT and the actor requesting an extra activation are separate roles. The query is not simply `current action actor == Guinaifen`. The negative split-damage predicate is also real and must not be dropped merely because the short description omits it.

For the selected ordinary Burn family, the source/text/model comparison predicts:

| Damage event, with the relevant listener active | Firekiss eligibility | E4 own-source predicate |
| --- | --- | --- |
| Guinaifen's Burn, natural pulse | Burn-flag match | Matches Guinaifen |
| Guinaifen's Burn, extra activation requested by a teammate | Burn-flag match | Still matches if original DoT ownership is preserved, as in P4's ordinary model |
| A teammate's Burn, including an activation requested by Guinaifen | Burn-flag match | Does not match Guinaifen merely because she requested activation |
| Direct Fire damage without a Burn damage-source flag | No Burn-flag match | Not DOT; rejected |

The table is a source/model discriminator, not a newly executed mixed-party test. Firekiss retains its separate Chance gate. E4's callback has no dependency on successful Oil_Sub installation; a failed Firekiss application is not by itself a reason to deny an otherwise eligible E4 request.

Importantly, the E4 raw predicate is DOT + Fire + non-split + actual-owner, not the identical Burn-flag predicate used by Oil. The ordinary Burn interpretation is closed here; do not generalize Fire=Burn or claim exhaustive behavior for every special Fire DoT/Break source from this one comparison.

## 6. Evidence accounting and remaining precise questions

| Claim | Status in this record |
| --- | --- |
| Fresh Firekiss layer does not amplify its triggering ordinary Burn | Attributed text/community-model interpretation; no new game measurement; native before-hit/settlement mapping remains unspecified. |
| E2 conditional p+0.4, versus p*1.4 | Exact pinned rank, read, condition and expression chain; public E2 text supplies the declared mechanic. |
| E4 numeric input, activation and ownership filter | Exact pinned Rank04 Param[0]=2 transport and full four-predicate callback, reconciled with published E4 Energy wording. |
| Distinct Burn owner, detonator and listener owner | Source predicates plus P4 ordinary attribution model; mixed-party outcomes are explicitly predicted, not executed. |
| Backend or native engine correctness | Not evaluated or required. No C/D/E implementation promotion. |

Remaining work is specific: direct mixed-party/Break-family corroboration beyond the selected ordinary branch, native snapshot/refresh details, exact energy-regeneration/cap interactions, and internal damage-context visibility. Existing public evidence can advance these questions; there is no requirement to discover a native function body first. No RNG algorithm, scheduler, universal callback order or full character census was opened.

This checkpoint updates the main Burn record's former same-hit question by a linked status overlay and updates README navigation. Broad worklist leaves and package statuses are unchanged: the three claim-level results above do not satisfy an exhaustive modifier/resource/event checklist. The source inventory is not broadened, and no backend implementation task is created.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarRankConfig.json#L5000-L5145
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Guinaifen_00_Config.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Guinaifen_00_Ability.json
[P1]: https://srl.keqingmains.com/characters/fire/guinaifen
[P2]: https://starrail.honeyhunterworld.com/guinaifen-character/?lang=EN
[P3]: https://www.taptap.cn/moment/469210683309818669
[P4]: https://hsr.keqingmains.com/kafka/
[BASE]: guinaifen_burn_tick_detonation_source_chain_v1.md
