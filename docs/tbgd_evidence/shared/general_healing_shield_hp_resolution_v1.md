# General sustain mechanics: healing, shields and HP resolution v1

## 1. Scope and result

Reviewed 2026-09-24. Evidence parent: `1a814ca21efc28e0af9aaac7a1e7220eff29938e`; preceding checkpoint: `5806912921` (F07). Raw authority is `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains open/Draft and docs/evidence-only.

**F04 result:** separate base healing, applicable healing modifiers and realized HP gain; shield creation, remaining absorption and damage mitigation; ordinary non-additive shields and explicitly replenishable shields; and ordinary damage, direct HP loss and damage distribution. Previously recovered Natasha/Gallagher/March equations are reused rather than researched again. New source discriminators are two shared relic effects, an enemy-authored healing penalty with a source-identity condition, and a named-instance shield carry/stack/cleanup chain.

The unit of research is the mechanic, not a kit. Sam and Aventurine supply contrasting operations. Public descriptions, original reports, raw expressions and model predictions have separate provenance. F04/W05 remain active for the specific residuals in section 10; no whole-mechanism or local-runtime validation is claimed.

## 2. Evidence register

### Newly inspected exact-pin sources

| Ref | Path and selected occurrence | Complete blob |
| --- | --- | --- |
| S1 | [ExcelOutput/RelicSetSkillConfig.json][S1]; Set101/RequireNum2 and Set103/RequireNum2,4 | `a8022b783c42d05f6cb168010ecbcfa90b69182d` |
| S2 | [Config/ConfigAbility/Equip/RelicAbility.json][S2]; Ability51031 and MRelic_103_Main | `b9b9573f0ba69a6c332eeeebb9b587f3dfa99c01` |
| S3 | [Config/ConfigCharacter/Monster/Monster_W3_Sam_00_Config.json][S3]; Skill04/06 entries and PassiveSkill01/Skill04 parameter reads | `a6a8cbe751ba545b6b21c72e30414115d6f3b34e` |
| S4 | [Config/ConfigAbility/Monster/Monster_W3_Sam_00_Ability.json][S4]; Skill04 Phase02, BurningBP, Skill06 Phase02 and the adjacent contrasting healing callback | `3e97c5aec8df84d3599cfd44b722eacc895dfa68` |
| S5 | [Config/ConfigCharacter/Avatar/Avatar_Aventurine_00_Config.json][S5]; Skill02 membership and indices0-3 | `092c497b64e381ac3e49f6bfc3198d755e7e326f` |
| S6 | [Config/ConfigAbility/Avatar/Avatar_Aventurine_00_Ability.json][S6]; Skill02 Phase02, MAvatar_Aventurine_StackableShield and Aventurine_RecordCurrentShield | `67212a729fcfbae03093549b69194e6987968d6c` |

Useful replay ranges are S1 1-120; S2 145-225; S3 full CharacterConfig; S4 2290-2710, Skill06 Phase02, and 5610-6220; S5 250-460; S6 Skill02 Phase02, 5200-5850 and the final GlobalTemplates entry. Named objects plus complete blobs remain the stable anchors if viewer line layouts differ.

### Reused records and public evidence

[R3][R3], [March][MARCH] and [the earlier reconciliation][HEAL] retain the exact base-heal/shield operands, HOT clock, snapshot/read sites and removal surfaces. [F02][DAMAGE] provides ordinary damage factors; [F06][MODIFIERS] provides state identity and lifetime distinctions. These are reused results, not new raw discoveries.

| Ref | Provenance | Use and limit |
| --- | --- | --- |
| P1 | [Ludgerz/Ludgeria, original Sam healing report][P1], crediting MeeHun for testing/graph assistance | Reports testing an additive healing penalty and reproduces the other-character-healing condition. The example graph is calculated, not a separate measured data set. |
| P2 | [KQM SRL shielding evidence][P2], bobrokrot, added2023-05-17, tested2023-05-16 | Controlled damage-reduction versus shield-consumption report. Already cited by HEAL; reread here, not a new experiment. |
| P3 | [Star Rail Station, Aventurine Skill text][P3] | Explicit repeated-shield stacking and a cap relative to the current Skill shield. Public text, not a same-pin localization join. |
| P4 | [KQM Relics Overview][P4], Knight/Passerby sections | Identifies the shield-absorption and outgoing-healing meanings of the exact relic inputs. |
| P5 | [KQM Fire Trailblazer guide][P5], updated Version2.0; AnemoneMeer, Sushou, Arbutus unedo | Ordinary shields from different sources do not add together; also distinguishes shielded-hit utility from HP restoration. Not a native per-shield arbitration algorithm. |
| P6 | [KQM Fu Xuan guide][P6], Version1.3, Mechanics | Public-model contrast: distribution before recipient-specific mitigation and shields. No new Fu Xuan raw trace is claimed. |

P2 was read through GitHub at `KQM-git/SRL@de0e5c09c8dbba9577367ad86e991fe91c4f0e36`, `docs/evidence/combat-mechanics/damage/Shielding.md`, blob `ce4dc27dd3d156e1d6540fc82c97e964c052b288`. That publication revision is not the TBGD pin. Public sources were consulted on2026-09-24; retrieval date is not their patch date. No linked video was newly watched and no game, simulator, Direct, tests or workflow was executed.

## 3. Healing amount and actual HP recovery are different quantities

For the ordinary scale-plus-flat families already reconciled in HEAL:

```text
H_base = coefficient * specified_stat_of_specified_entity + flat_amount
H_offered = H_base * applicable_healing_factor
H_realized = min(H_offered, HP_max - HP_before)
HP_after = HP_before + H_realized
```

The last two lines describe an admitted positive ordinary heal to a living target, with fixed maximum HP and no special conversion/override. They do not define every revive, HP-setting operation or callback payload. A pure flat base is a mathematical specialization, not permission to insert absent JSON fields.

Keep the scaling-stat owner, healing source, actual source owner and recipient distinct. R3's direct Natasha heal uses healer MaxHP and a selected ally target; her HOT later operates on its holder. Neither the selected target nor the holder automatically supplies the scaling MaxHP. Gallagher's already recovered flat base does not become unexplained because FormulaType is omitted in that occurrence.

For ordinary outgoing boosts and the selected Sam penalty, with no other healing correction, the supported model is:

```text
H_offered = H_base * (1 + outgoing_boost - applicable_reduction)
```

The reduction is part of the same additive factor, not a second multiplier on the already boosted heal [P1]. This establishes the covered relation without asserting all positive incoming-boost, sign-boundary, special-converter or clamp rules. Extreme negative factors are not converted into damaging heals by extrapolation.

Example: H_base1000, outgoing_boost0.50 and applicable_reduction0.90 produce600, not150. If the recipient lacks only100 HP, the ordinary realized gain is100. The unretained500 is not automatically a shield, a stored future heal, or proof that no healing-trigger event occurs. A consumer that uses offered, effective or overflow healing needs its own documented payload rule.

## 4. Healing modifiers: ownership and eligibility before arithmetic

### 4.1 A shared outgoing-healing contribution

S1 `[SetID=101,RequireNum=2].PropertyList[0]` literally has `FODBMMCKAEN=HealRatioBase` and `MNDFOPKBHKP.Value=0.1`. P4 identifies the two-piece effect as outgoing healing. It supplies an attribute contribution; it is not an immediate HP grant, a receiver-owned bonus or the separate four-piece Skill Point effect.

### 4.2 Sam's recipient-side penalty, not an unconditional global debuff

S3/S4 supply this chain:

```text
CharacterConfig Skill04 -> Monster_W3_Sam_00_Skill04_Phase01
 -> TriggerAbility(Caster, Skill04_Phase02)
 -> AddModifier(AllEnemyWithUnSelectable, Monster_W3_Sam_00_BurningBP)
      MDF_HealDownRatio <- hash421057014
      hash421057014 = SkillParam(PassiveSkill01,index4)

BurningBP.OnBeforeBeingHeal
 -> ByCompareTarget(ParamEntityActualOwner, ModifierOwnerEntity, Inverse=true)
 -> ModifyHealData.Target_HealTakenRatio
      OpCodes=AAAOAQAEEQ==, FixedValues=[1], DynamicHashes=[1260053363]
      signed expression: -1 * the working reduction input
```

The installer supplies a named value; the consumer retains its exact working-hash read. The underlying symbol-resolution implementation and the numeric MonsterSkillConfig row are not newly recovered here. P1's reported90% belongs to its stated encounter/test context; it is not silently written into an unread pinned row.

The condition compares **actual healing owner** with the state holder. Equal-owner healing does not enter this penalty branch. The state is on the recipient, but its algebra can offset an outgoing boost. P1's description of a negative outgoing bonus is an arithmetic explanation, not proof that the raw operation permanently subtracts from the healer's HealRatioBase: this occurrence modifies `Target_HealTakenRatio` in the healing context.

The named Skill06_Phase02 recovery path removes BurningBP from `AllLightTeamWithAllLightTeamUnselectable.RemoveBattleEvent`; the AIChange pre-death cleanup also explicitly removes it. A field-wide visual ending is not substituted for these removal operations.

A neighboring callback in the same file instead compares `ParamEntity` and writes `Healer_HealRatio` using a layer-dependent negative expression. It is a different occurrence, not evidence that BurningBP has the same owner predicate, parameter or algebra. The full boss phase machine and mode-specific variants are outside this slice.

## 5. Shield generation is not recipient damage reduction

For a covered ordinary shield generated from one scaling stat:

```text
S_base = coefficient * creator_scaling_stat + flat_amount
S_granted = S_base * (1 + applicable_creator_shield_bonus)
```

The already recovered March equations remain in HEAL. P3's Aventurine wording separately identifies his DEF as the creator stat. The shielded ally's DEF instead affects ordinary incoming damage; it is not substituted into the creator's shield formula.

S1/S2 close an exact shared shield-bonus input:

```text
RelicSetSkillConfig[SetID103,RequireNum4]
  AbilityName=Ability51031; AbilityParamList[0].Value=0.2
 -> Equip/RelicAbility Ability51031
      hash885378938=SkillRelic(103_4,index0)
 -> OnStart AddModifier(Caster,MRelic_103_Main)
 -> MRelic_103_Main.OnStack
      StackProperty(ModifierOwnerEntity,ShieldAddedRatio,hash885378938)
```

P4 explains the20% shield increase. It affects the covered shield amount, including the flat term, not merely the DEF coefficient. Set103's separate two-piece `DefenceAddedRatio=0.15` is a different contribution. A total generated shield of1200 from base1000 with the sole20% shield bonus does not grant20% incoming damage reduction.

The typed `Equip/RelicAbility.json` is used here. F08 already documented the differently serialized root sibling; this record does not splice its environment into the typed binding or claim native duplicate-definition registry precedence.

## 6. Ordinary absorption, overflow and coexistence

Let D be the damage eligible for absorption **after the applicable recipient mitigation**, and S an ordinary remaining shield amount. For a single eligible shield without special bypass or conversion:

```text
absorbed = min(S, D)
S_after = max(0, S - D)
HP_damage = max(0, D - S)
```

This is an observable accounting model, not a claim about the native order of every damage callback. Mitigation already included in D must not be applied again to HP_damage. Shield creation bonuses belong to the shield side of this calculation, not a second reduction of D.

P2 reports the same incoming attack doing154 with the10% damage reduction, both without a shield and with one; after the reduction expires it does171 against a shield. The approximate relation171*0.9=153.9 supports mitigation before shield consumption. The displayed integers are not evidence of the game's precise internal rounding implementation.

A completely absorbed hit has zero ordinary HP loss, but this does not make it a non-hit. P5's shielded-counter discussion is a concrete public distinction. Hit-driven, damage-driven, HP-change-driven and shield-depletion-driven consumers require their actual event conditions; one should not be inferred from another's numeric delta.

P5 explicitly rejects additive stacking of ordinary shields from different sources. Thus two unrelated shields cannot simply be summed into one HP buffer, nor should their source identities and dependent effects be deleted merely to keep a single display number. This first pass establishes non-addition and the explicit accumulation exception below. It does not newly certify a complete parallel-drain/priority table for every overlapping shield family or the exact same-hit timing when a smaller shield disappears.

## 7. Explicit accumulation: amount, cap, identity and clock

### 7.1 New grant and named current amount are separate inputs

S5 identifies the four Skill02 inputs:

| Hash | Typed read | Role at the selected installer |
| --- | --- | --- |
| 583785975 | SkillParam(Skill02,0) | DEF coefficient |
| 1089505780 | SkillParam(Skill02,1) | Flat amount |
| -1019407308 | SkillParam(Skill02,2) | Lifetime |
| -1317091266 | SkillParam(Skill02,3) | Maximum-shield ratio |

S6 Skill02_Phase02 reads Caster.Defence into `MDF_CurrentDefence2`, calls `Aventurine_RecordCurrentShield`, then installs `MAvatar_Aventurine_StackableShield` on AllLightTeam. Both `MDF_InitShieldValue` and `MDF_ForceShield` use `AQABAQQBAgIR` with hashes `[995479797,583785975,1089505780]`, the working DEF times coefficient plus flat expression. The maximum ratio and lifetime are passed separately.

The template is not a read of an arbitrary visible total:

```text
Aventurine_RecordCurrentShield
 -> Retarget(AllLightTeam)
 -> contains named MAvatar_Aventurine_StackableShield?
    yes: read that modifier's CurrentShield into tmp_currentshield
         then write AventurineShieldValue in TargetEntity scope
    no:  write AventurineShieldValue=0 in TargetEntity scope
```

The successful branch uses `ContextTaskTemplate` for the temporary read and copies it through hash-562841136. The failed branch explicitly supplies zero. A different shield being present does not satisfy this named-state test. The template does not authorize importing another shield's remaining value into this carry-state read.

### 7.2 The consumer really is StackShield

The named definition has `BehaviorFlagList=[Shield]` and `Stacking=ReplaceByCaster`, but its `OnStack` calls:

```text
StackShield
  StackValue = AQAR / [-1200970748]
  MaxStack = AQABAQQR / [1079898730,-1177161350]
```

Those are shield-value/cap operands, not proof of a two-layer modifier counter. The source's property/carry machinery and working hashes remain recorded without fabricating a generic native StackShield evaluator. P3 gives the observable accumulation rule and cap relative to the current Skill shield.

For an ordinary repeated grant with unchanged relevant stats/bonuses and a fixed cap C:

```text
S_after = min(S_remaining + S_granted, C)
C = 2 * current Skill shield amount       selected public Skill description
```

This is neither universal additivity of all shields nor a command to reset the amount solely because the modifier says ReplaceByCaster. Reapplication also supplies a lifetime; accumulating amount and updating that clock are different obligations. Changed creator DEF, a changed shield bonus, cap shrinkage and mixed-grant arbitration need their specific sampling rule, not an extrapolation from this fixed-input example.

### 7.3 Cleanup belongs to the state that supplied the protection

The definition's OnDestroy calls RemoveShield, removes named attached shield-display and resistance/control-related states, and resets resilience. The state also owns a StatusResistanceBase contribution. Existing March evidence separately has InitShield and RemoveShield surfaces.

These explicit exits establish dependencies, not a universal depletion-to-OnDestroy chronology or an instruction to wipe every unrelated state from the target. Ending this shield's protection and ending all shielding on the actor are not definitionally the same event. F06's property-contribution and lifetime distinctions remain applicable.

## 8. HP loss and damage distribution are separate branches

S3/S4 provide a direct loss discriminator in the same Skill04 path:

```text
LoseHPByRatio(Target=Caster, RatioType=MaxHP)
  Ratio <- hash930883309 = SkillParam(Skill04,index1)
  Floor = fixed1
```

The request-level interpretation, for HP_before>=1 and nonnegative ratio q, is a maximum-HP-relative loss bounded to leave1: `loss=min(q*HP_max,HP_before-1)`. It is not expressed as an ordinary AttackData hit and must not acquire an invented crit roll, enemy DEF multiplier or healing bonus. This task does not infer all emitted HP-loss events, arbitrary shield-bypass policies or lethal-cleanup ordering from the operation name.

A separate public branch is damage distribution. P6 explains the selected ordinary Matrix case as a split before recipient-specific mitigation and shields. If unmitigated input is U, the two ordinary branches use `.35*U*M_ally` and `.65*U*M_FuXuan`, not65% of an already mitigated ally HP loss. This is an attributed public-model contrast, not a new raw Fu Xuan audit or a universal damage-sharing implementation.

Consequently the reusable route is not one undifferentiated subtraction: determine whether this is healing, direct HP loss, ordinary incoming damage, or a named distribution/conversion; retain each recipient and input; then apply that branch's supported formula. Revival and maximum-HP construction remain separately owned lifecycle problems.

## 9. Calculation-only discriminators

These are synthetic predictions, not game observations. Assume admitted operations, the stated fixed inputs and no intervening expiry, immunity, conversion or unrelated effect.

| Controlled case | Prediction / distinction |
| --- | --- |
| Base heal1000, outgoing+50%, no penalty | Offered1500 |
| Same base/boost, selected90% additive penalty | Offered600, not150 |
| Offered600, target missing100 HP | Realized100; no implicit500-point shield |
| Base shield1000, sole shield bonus20% | Granted1200, not recipient damage reduction20% |
| Eligible post-mitigation damage900, single shield600 | Shield0, HP damage300; do not mitigate300 again |
| Named stackable shield500, grant1000, cap2000 | New amount1500 |
| Same named shield1700, grant1000, cap2000 | New amount2000; only300 added |
| Named carry-state absent but an unrelated shield is present | The inspected template still records0 for its own carry state |
| Selected loss: MaxHP1000, currentHP100, q0.2, floor1 | Loss99, resultingHP1 |
| Public split: U1000, M_ally0.5, M_FuXuan0.2 | Pre-shield recipient amounts175 and130, not one shared defensive factor |

## 10. Claim accounting and remaining research

| Claim | Positive basis | Remaining boundary |
| --- | --- | --- |
| Base/modified/offered/realized healing differ | Reused R3/HEAL, ordinary HP accounting and P1 | Special conversions, overheal event payloads, positive incoming-boost combinations and exact bounds |
| Selected penalty eligibility and additive effect | S3/S4 installer, actual-owner predicate, signed target-context write and P1 | Unread numeric monster row, variant coefficients and redirected-source edge cases |
| Creator shield bonus differs from receiver mitigation | S1/S2 exact0.2 chain, P4 and reused base shields | Sampling, dynamic refresh and uncommon shield-formula overrides |
| Ordinary mitigation precedes shield consumption | Credited P2 report and the explicit single-shield accounting model | Special bypass and exact rounding/depletion visibility |
| Ordinary shields are not summed; explicit accumulation exists | P5 versus S5/S6/P3 | Complete multi-pool draining/expiry arbitration and special team/shared shields |
| Own current shield, new grant, cap and clock are separate | Named CurrentShield template, typed inputs, StackShield and P3 | Working-slot/native carry implementation and changed-cap reconciliation |
| Removal and direct HP loss have distinct source edges | S4/S6 and reused March/F06 | Universal event order, concurrent exits and arbitrary loss overrides |
| Distribution can precede recipient mitigation | P6's attributed model | Exact source/recipient linkage deferred to F09, not falsely claimed raw-closed here |

No remaining item is a backend repair prerequisite. Readable descriptions and credible observed results can advance the behavioral questions; missing native code is not a blanket rejection of the rules above. Conversely a pointer to a formula, an empty read or a similarly named operation cannot fill an uninspected numeric row or prove every exception.

## 11. Publication and next foundation

This checkpoint adds this record and updates the foundation roadmap and evidence README. Existing R3/March/HEAL records, broad W checkboxes and source inventory remain intact. Six pinned raw files were inspected; selected previously established equations and the historical shielding experiment were reused.

Verification consists of manual source/public-text inspection, expression/ownership review, model arithmetic and Git content/diff/head/Draft checks. No runtime, lowering, IR, tests, CI or pin change. No local C/D/E promotion and no new gameplay experiment is implied by the calculations.

**Next primary foundation: F09 target selection, affected-target expansion and source context.** Reuse R7 and these source/holder/actual-owner distinctions. Explain selectable versus internal targets, validity/retargeting and the originator versus executor of damage/healing without expanding either sample's remaining kit. F01's remaining property synthesis and F10's lifecycle obligations remain on the foundation map; no next foundation is executed here.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicSetSkillConfig.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Equip/RelicAbility.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Monster/Monster_W3_Sam_00_Config.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_W3_Sam_00_Ability.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Aventurine_00_Config.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Aventurine_00_Ability.json
[P1]: https://www.reddit.com/r/HonkaiStarRail/comments/1au9po0/dont_make_this_simple_mistake_when_facing_boss/
[P2]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/docs/evidence/combat-mechanics/damage/Shielding.md
[P3]: https://starrailstation.com/en/character/aventurine
[P4]: https://hsr.keqingmains.com/misc/relics-overview/
[P5]: https://hsr.keqingmains.com/fire-trailblazer/
[P6]: https://hsr.keqingmains.com/fu-xuan/
[R3]: healing_modifier_lifecycle_core_v1.md
[MARCH]: ../characters/march_7th_preservation_skill02_shield.md
[HEAL]: public_mechanics_healing_shield_reconciliation_v1.md
[DAMAGE]: general_damage_formula_and_input_layers_v1.md
[MODIFIERS]: general_modifier_identity_stacking_lifetime_v1.md
