# General parameters and effective properties: combat semantics, not progression v1

## 1. Scope and result

Reviewed 2026-09-24. Evidence parent: `98bc2a3db82756519816c7c577f274821cc68ba4`; preceding checkpoint: `5810346824` (F10). Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains open/Draft and docs/evidence-only.

**F01 result:** unify typed parameter families and indexing with ordinary effective-stat composition, capped cross-entity grants, conversion-sensitive inputs and sampling sites. Classify fields by their battle consequence and actual consumer, not by a file, variable or property suffix. This is not a leveling, ascension, relic-enhancement, acquisition or unlock-system investigation.

The owner's scope clarification is explicit: investigate a selected finished build's combat properties and activated effects, not how the account obtained them. Costs, materials, EXP, prerequisite economy and roll history do not become combat requirements. A mixed table can contain useful battle coefficients beside excluded progression metadata. Conversely, an attractive field name is not enough to admit an unexplained value.

[R0][R0] and [R5][R5] already establish parameter/reference families and selected construction inputs. This pass reuses those facts without promoting R5's local assembler arithmetic, prerequisites or execution status into native facts. No complete character panel is reconstructed here. F01/W01/W02/W03 remain active for the specific residuals in section 9.

## 2. Evidence register

All S paths below are at the fixed TBGD revision. Named occurrences govern; no guessed array indices or default-branch content supply authority.

| Ref | Path / selected occurrence | Complete blob |
| --- | --- | --- |
| S1 | [AvatarPromotionConfig][S1]; first Avatar1001 row and its Promotion1 neighbor | `d09a89b7abad0bd836050146416e9fe0331e61da` |
| S2 | [AvatarRankConfig][S2]; Rank100103/100105, skill-level maps and excluded UnlockCost neighbors | `ecd3581d9307d3ac94123e0c30983ef6e627f4f3` |
| S3 | [RelicSetSkillConfig][S3]; Set102 thresholds2/4 and neighboring static property rows | `a8022b783c42d05f6cb168010ecbcfa90b69182d` |
| S4 | [typed Equip/RelicAbility][S4]; Ability51021/MRelic_102_Main and SkillRelic binding | `b9b9573f0ba69a6c332eeeebb9b587f3dfa99c01` |
| S5 | [Tingyun CharacterConfig][S5]; Skill02 indices0-3 and working-value declarations | `2211a8e69b180b176fbafdf098720d8d982fd255` |
| S6 | [Tingyun Ability][S6]; Skill02 capped grant, baseline LeiLing installation and OnStack | `41b224f8a3261db6a2e0aeb269bf834a77381489` |
| S7 | [Gepard CharacterConfig][S7]; PointB3 typed conversion input and working reads | `9d15bb0e10a74b00fcc74a493a83fc7eae85db55` |
| S8 | [Gepard Ability][S8]; SkillTree03, M_Gepard_AttackConvert and AttackDeltaUp consumer | `19a1f1d53bbe311677ccf0e1ee7012e7674553fc` |

Replay ranges: S1 1-105; S2 1-145; S3 1-140; S4 65-156; S5 185-315; S6 440-1115, 1680-2075; S7 230-370; S8 1906-2210. Additional S6 rank-variant neighbors were read for navigation, not audited as complete kits. Full blobs and named occurrences remain stable anchors if viewer line layout changes.

| Ref | Public semantic source | Accepted scope / limit |
| --- | --- | --- |
| P1 | [KQM SRL Damage Formula][P1], Base Damage/stat equations, crediting arkkus | Ordinary ATK/DEF/MaxHP composition. The page carries an under-construction notice; it is an attributed model, not an independently reproduced experiment or authority for every section on that page. |
| P2 | [KQM SRL Tingyun skill publication][P2], Soothing Melody | Recipient ATK increase capped by provider current ATK; distinct description slots for damage, stat increase, duration and cap. Public parameters are not substituted into unread pinned rows. |
| P3 | [KQM SRL Gepard skill publication][P3], Fighting Spirit | DEF-derived ATK and refresh at turn start. Its minAsc/prerequisite metadata is outside this combat slice. |

P1-P3 were read through GitHub at publication revision `de0e5c09c8dbba9577367ad86e991fe91c4f0e36`, not the TBGD pin. Their blobs are respectively `2928c24daa92422d90df5cf3ef1766932779f4d2`, `cb8b276e4a6876c8b60a76a4b797052d3d5a6ac3`, and `036599ce95a588396ef6003d0264d60e67aa2c4f`. Public source retrieval was 2026-09-24; that date is not a patch label. No same-pin localization join, new gameplay measurement or video replay is claimed.

Reused evidence is explicitly identified: R0's Avatar/Servant/Monster binding dictionary and postfix addition/subtraction/multiplication; R5's selected finished-build source joins, SkillEquip and SkillRelic consumers; [March][MARCH]'s typed shield inputs; [the servant record][SERVANT]'s #N rule; and [the description-joined Burn record][BURN]'s same-pin text reconciliation. F02-F10 supply mechanics and context, not permission to expand into unrelated kit details.

## 3. Field-level combat inclusion

Apply the [battle consequence test][SCOPE] while holding the selected finished build fixed. Retain the producer/reference, consumer and changed battle quantity. Record an untraced candidate as unreviewed rather than letting its name decide the outcome.

| Inspected field or neighborhood | Treatment and reason |
| --- | --- |
| S1 AttackBase/AttackAdd, HP/DEF coefficients and SpeedBase | Battle-start input family already traced in R5; selected-row coefficients are not themselves a live stat mutation. Their presence does not authorize reimplementing progression. |
| S1 PromotionCostList, PlayerLevelRequire and WorldLevelRequire | Excluded account progression/cost neighbors; do not require payment or account-level eligibility to explain an already selected combat input. No material acquisition chain is followed. |
| S1 MaxLevel / Promotion | Preserve row/variant metadata when needed to identify a source. Do not import an account progression-cap or prerequisite simulation. The first row omits Promotion; it is not quoted as an explicit serialized zero. |
| S2 SkillAddLevelList | Combat-relevant routing: changes the selected skill's effective parameter level. It is not an additive ATK/HP bonus. |
| S2 UnlockCost / IconPath | Excluded unlock economy / presentation. Neither grants an additional battle effect. |
| S3 RequireNum | Equipped-set effect threshold, not a number of materials to spend. Its role follows the set/effect join in R5 and the named Ability consumer. |
| S3 PropertyList versus AbilityParamList | Property contribution versus parameters requiring interpretation. Repeated numbers are not two automatic stat grants. |
| S6 MDF_Target_CurrentAttack | Its actual ReadTargetType is AbilityTargetEntity and Value is BaseAttack, despite CurrentAttack in the variable name. |
| S8 Avatar_Gepard_Passive02_AttackDeltaUp | Its actual property write is AttackConvert, despite AttackDelta in the modifier name. |
| P3 minAsc and other description-site unlock metadata | Not a combat requirement; only the selected effect's description and source-wired operations are used. |

For a discriminator, changing only a required material count while retaining the identical selected build does not change the combat formula in this slice. Changing a proven AttackAddedRatio input can. The former is an exclusion under the project's scope, not an empirical claim about an account subsystem that was never audited.

S1's `AttackAdd=3.48` is not evidence of a separate +3.48 attack buff. R5 treats analogous fields as selected-row growth coefficients in its local construction model. This pass does not newly certify that loader equation or insert a growth term into a finished base stat already supplied by another source. Likewise it does not re-derive relic LevelAdd/StepValue or roll-history arithmetic. Those are separate from the established base-to-effective composition below.

## 4. Parameter identity, slot and value lifetime

The reusable identity is family + actual owner/definition + effective selector/level + trigger/index + invocation environment, not a bare integer hash. This is research notation, not a proposed runtime schema.

| Family | Producer / selector | What its value is not |
| --- | --- | --- |
| SkillParam | Owner-qualified AvatarSkillConfig, AvatarServantSkillConfig or MonsterSkillConfig; SkillTriggerKey and zero-based ReadInfo.Index; appropriate skill Level when present | A global hash-to-number table or automatic skill unlock |
| SkillTreeParam | Selected point's parameter row and PointTriggerKey/index | The point's material cost or proof that it is active merely because its definition exists |
| SkillRank | Selected rank effect's Param and Rank trigger/index | SkillAddLevelList or a generic rank multiplier on all stats |
| SkillEquip | Selected equipment effect's parameter level/rank and index, as traced in R5 | Equipped weapon base stats or character level |
| SkillRelic | SetID/RequireNum-qualified AbilityParamList and index | Every repeated PropertyList number applied a second time |
| #N servant inputs | The corresponding HPSkill/SpeedSkill selects the skill row; #N is its one-based slot | A zero-based ReadInfo.Index or an unspecified nearest skill |
| Description #N placeholders | Parameter position plus display formatting, reconciled with the relevant description and graph | An executable assignment, hidden rounding rule or interchangeable #N namespace |
| Working values / Type=None | Actual property reads, named writes, injected values and scoped expression reads | An unconditional zero, missing mechanic, or a persistent unit property merely because a float is declared |

S2 supplies an especially useful empty-parameter counterexample. Rank100103 has `Param=[]` but `SkillAddLevelList={100103:2,100101:1}`; Rank100105 similarly has `{100102:2,100104:2}`. These are source-family-qualified keys, not proof that equal numeric IDs in the Rank and Skill tables denote the same object. The effect changes which existing skill-parameter row is used. It is not represented by summing Param, and does not require modeling how the rank was acquired.

When a caller supplies a base skill level plus selected increments, resolve the effective level once; when an input already denotes effective level, do not add them again. This is a representation distinction for consuming the documented rule, not a new claim about every level cap/override or the project's current importer.

P2's description uses #2 for the recipient stat increase, #4 for its provider-relative cap, #1 for additional damage and #3 for duration. S5 binds those to zero-based Skill02 indices1,3,0,2 respectively. The shared text/graph interpretation is meaningful even though this pass has not joined P2 to same-pin TextMap. The earlier BURN record retains its actual same-pin join; it is not rerun here.

## 5. Ordinary base-to-effective stat composition

For ordinary ATK, DEF and MaxHP, take the correctly resolved character and Light Cone base values as inputs. P1 supplies:

```text
B_X = X_character_base + X_light_cone_base
X_effective = B_X * (1 + sum(applicable percentage bonuses))
              + sum(applicable flat amounts)
X in {ATK, DEF, MaxHP}
```

This is a usable attributed model reconciled with R5's base/ratio/flat source partition and the explicit property consumers here. It is not a universal native formula for every property, enemy difficulty variant, override or temporary state. It does not infer how each base value was loaded, and does not require simulating leveling to use a supplied finished base value.

The important consequence is that ordinary percentage bonuses multiply the relevant base pool, not a current value containing other bonuses and flat additions. Conditional contributions count only while their actual predicate/lifecycle is satisfied. R5's already-mapped set threshold is not replaced with an unconditional startup grant.

Example: character base600, Light Cone base400, ratio total0.50 and flat total200 give1700. Adding an applicable0.20 percentage contribution gives1900, not1700*1.2=2040. These are synthetic inputs and predictions, not a recovered character panel or game observation.

A derived flat grant can be part of the final additive amount while retaining its conversion provenance. Do not erase separate AttackDelta/AttackConvert inputs merely because both can increase the displayed ATK: another consumer can distinguish them, as section 7 shows. Do not sum a previously flattened total and its constituent pools again.

Property spelling is not a universal algebra. R5's LC20000 temporarily contributes to `CriticalChanceBase` through OnStack; Base in that name does not mean immutable character-only data. F08 separately establishes speed inputs; F04 distinguishes MaxHP from actual healing; F07 distinguishes a resource maximum from its current balance. A probability or damage-multiplier property is not assigned this ATK equation because it also ends in Base or Ratio.

## 6. Capped grants: two stat owners and a misleading working name

S5/S6 expose the following selected Skill02 chain:

```text
read AbilityTargetEntity.BaseAttack -> MDF_Target_CurrentAttack
read Caster.Attack                 -> MDF_Tingyun_Attack
multiply first working value by SkillParam(Skill02,1)
multiply second by SkillParam(Skill02,3)
compare the two; write the smaller to MDF_Skill02_Attack
 -> inject MDF_AttackDelta into selected recipient-side states
 -> baseline MAvatar_TingYun_00_Passive_LeiLing.OnStack
 -> StackProperty(ModifierOwnerEntity, AttackDelta, hash1521339462)
```

The expression reads preserve exact hashes: first product `[1105114375,-1829192421]`, second product `[-19417079,645810140]`, both `AQABAQQR`; result read for injection is `-1581832284`. S5 maps -1829192421 to Skill02[1] and645810140 to Skill02[3]. Working declarations with Type=None do not make these calculations zero.

With B the recipient BaseAttack, A the provider Attack read at this operation, alpha the first ratio and c the cap ratio:

```text
grant = min(alpha * B, c * A)
```

P2 supports the capped-grant interpretation; the actual BaseAttack read resolves the recipient-side ambiguity in its abbreviated ATK wording. The variable first stores a base property, then a scaled candidate amount. Its name alone identifies neither its property source nor its current stage in the calculation.

For the public Level10 example alpha=.50 and c=.25, B=1000 and A=1600 give400; raising A to2400 gives500. Increasing only the recipient's flat ATK, with B and A unchanged, does not increase this calculated grant. The level10 pair is P2 provenance, not a newly read TBGD skill row. The calculation is not a gameplay test.

The baseline installer for LeiLing also uses `InheritCaster=TargetSelf`, already treated in F09. Parameter donor, stat-read owner, modifier holder and later damage owner remain distinct. The lifetime wrapper and the damage-owning state both receive named values; that does not create two ATK grants merely by counting occurrences of MDF_AttackDelta. The actual baseline property write is the one above. Full variant/refresh arbitration is not newly certified.

## 7. Conversion-sensitive inputs and explicit sampling sites

S7 maps `-1106312403 -> SkillTreeParam(PointB3,0)`. S8 `Avatar_Gepard_SkillTree03.OnStart` passes it as MDF_ConvertRatio to M_Gepard_AttackConvert. Both OnStack and OnPhase1 read the holder's Defence and DefenceConvert, then supply:

```text
PostfixExpr = AQABAQMBAgQR
DynamicHashes = [1316963685,-2083367191,-1316363322]
interpreted amount = (Defence - DefenceConvert) * conversion_ratio
 -> AddModifier(Avatar_Gepard_Passive02_AttackDeltaUp,
                MDF_PropertyValue=amount)
 -> OnStack StackProperty(ModifierOwnerEntity, AttackConvert,
                         hash2128130574)
```

R0's independently audited subtraction/multiplication vocabulary supports this expression. The subtraction is in the calculation; there is no corresponding request here to remove Defence from the character. It filters the basis of this derived grant. The consumer writes AttackConvert, not the AttackDelta suggested by the modifier's name.

P3 describes a35%-of-current-DEF ATK increase refreshed at turn start. Its coefficient belongs to that publication; no unread pinned point row is filled with .35. The graph refines the ordinary description by explicitly excluding the DefenceConvert component. This is a demonstrated conversion-sensitive branch, not proof that every conversion in the entire game excludes the same categories.

With total Defence2000, DefenceConvert500 and ratio.35, this request supplies525, not700. Two states with identical displayed Defence can therefore yield different conversion amounts. This calculation distinguishes preserving component provenance from flattening everything to one final number; it is not a new measured result.

OnStack and OnPhase1 are explicit refresh sites, and P3 supplies the selected turn-start interpretation. This is not a promise of instantaneous recomputation after every unrelated property change or a global topological order. In section 6, grant inputs are read during skill execution and then injected; in this section they are read by recurrent callbacks. S8's ReplaceByCaster metadata is preserved but does not alone prove every stronger/weaker refresh rule or inter-effect ordering.

## 8. One parameter occurrence is not one extra stat mutation

S3 Set102/RequireNum2 contains both `PropertyList: AttackAddedRatio=.12` and `AbilityParamList:[.12]`, with empty AbilityName. Its four-piece row instead has static `SpeedAddedRatio=.06`, Ability51021 and parameters `[.06,.1]`.

S4 closes the actual dynamic consumer:

```text
Ability51021 -> install MRelic_102_Main
 -> OnBeforeHitAll -> ByAttackType(Normal)
 -> ModifyDamageData.Attacker_AllDamageTypeAddedRatio
      hash459179394 = SkillRelic(102_4,index1) = .1
```

These are different quantities: static ATK percentage, static speed percentage, and a matching-hit damage-bonus input. Do not sum every .12/.06/.1 into a persistent ATK pool, repeat the two-piece bonus because it is also a parameter, or turn the normal-hit bonus into a bonus for all attacks. F02 owns the damage factor; this pass establishes its input role and scope.

R5 already recorded this set split; the exact-pin reread supports the general classification here rather than a first-discovery claim. The typed Equip file is used consistently; F08's differently serialized root sibling is not spliced into its binding environment. Similarly, a value used by a preshow/icon/text operation remains presentation at that occurrence even when a separate combat task reads the same parameter.

## 9. Claim accounting and remaining research

| Claim | Positive basis | Specific remaining boundary |
| --- | --- | --- |
| Combat inputs versus progression neighbors are classified below file level | S1-S3, R5 joins and explicit scope | Untraced families are not admitted or rejected by naming alone |
| Parameter family/owner/level/index and working lifetime are separate | R0/R5, S2/S5/S7, description-slot reconciliation | Full family census, alias resolution, fallback/override precedence |
| Ordinary base/ratio/flat composition is usable | P1, R5 input partition and typed contributions | Native loader equations, extreme bounds and special overrides |
| Capped grant uses recipient base and provider effective input | S5/S6 and P2 | Other variants, precise reapplication/snapshot/conflict rules |
| Conversion provenance can affect a later derived amount | S7/S8 expression and P3 | Other conversion families, propagation and same-time refresh ordering |
| Static contributions, parameter transport and hit-context effects differ | S3/S4 and R5 | Full set/provider reachability and activation census |
| Full foundation pass or local implementation is complete | Not claimed | Common residuals and corpus coverage require integrated review |

Raw selected occurrences are manually confirmed; the stated behavioral reconciliations have identified public-model/description support. The public sources are not native implementation or new empirical tests. C/D/E are not inspected or promoted here; no runtime execution is required to retain the source claims.

Precisely open questions include generic property/working-slot resolution and initialization defaults; inactive/missing effective-level inputs and override precedence; per-family conversion eligibility and refresh/snapshot interaction; exact clamps/precision; and source coverage beyond these ordinary cases. R5's loader/affix arithmetic remains at its recorded evidence strength rather than being silently promoted by P1's different, base-to-effective equation. None is a backend repair prerequisite, and none authorizes progression simulation.

## 10. Publication and next research decision

This record, the foundation roadmap and evidence README are the intended documentation changes. Broad W checkboxes, scope, inventory, old primary records and the TBGD pin remain intact. Eight pinned raw paths and three versioned public publications are registered; previously known R0/R5/foundation findings are identified as reuse.

Validation is manual source/description/formula review, predicate/owner/expression checks and Git content/diff/head/Draft verification. No runtime, lowering, IR, tests or CI is changed. No game, simulator, Direct, test suite or workflow is invoked, and synthetic arithmetic is not labeled testing.

**Next research task: integrated foundation-gap and coverage review.** Reconcile F01-F10's claim-level residuals with the W worklist and source-family scope, separate material unknown common rules from native-only implementation gaps and exceptional branches, and choose the next bounded common-mechanism closure. Do not default to character completion merely because all ten first-pass records exist. Do not revive old native-body-only freezes or backend acceptance sequences. The review itself is not executed in this checkpoint.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarPromotionConfig.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarRankConfig.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicSetSkillConfig.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Equip/RelicAbility.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Tingyun_00_Config.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Tingyun_00_Ability.json
[S7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Gepard_00_Config.json
[S8]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Gepard_00_Ability.json
[P1]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/docs/combat-mechanics/damage/damage-formula.md
[P2]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/src/data/characters/Tingyun.json
[P3]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/src/data/characters/Gepard.json
[SCOPE]: ../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_SCOPE.md
[R0]: battle_execution_language_core_v1.md
[R5]: battle_start_build_construction_v1.md
[MARCH]: ../characters/march_7th_preservation_skill02_shield.md
[SERVANT]: ../characters/aglaea_servant_11402_reference_chain.md
[BURN]: guinaifen_burn_tick_detonation_source_chain_v1.md
