# Guinaifen Burn: description, application, periodic tick and extra trigger v1

## Follow-up overlay — 2026-09-23

The [timing/E2/E4 follow-up](guinaifen_burn_timing_eidolon_attribution_v1.md) continues this record after its publication at `1f7211ca36bc65c93afbd937fe7f7fe780a190f7`. It adopts the attributed ordinary gameplay rule that a triggering Burn does not benefit from the Firekiss layer it generates, while preserving the raw `OnBeforeBeingHitAll` name and leaving its internal settlement mapping unspecified. It also closes E2's conditional `p+0.4` expression and E4's separate own-damage Energy request. The former same-hit question in sections8/10 below is retained as checkpoint history and superseded at the gameplay-model level, not by claiming a new game test or recovered dispatcher. All other original claims and limits remain unchanged.

## 1. Scope and result

Reviewed 2026-09-23. Evidence parent: `9582b32287820afed68b788d46ed60c5a455be2c`; PR #8 remains Draft / documentation-evidence only. All raw sources use `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`.

This is a selected ordinary W09/W10 source-and-gameplay-model result: Guinaifen Skill02 Burn, its shared periodic damage callback, Skill03's extra activation, and the separate Firekiss damage-taken modifier. The numeric examples use no Eidolon bonuses. Relevant E2/E6 branches are identified, not silently folded into those examples. No full-character, all-DoT, Break-DoT, general probability or engine-dispatcher census is claimed.

**Positive result:** the same-pin skill descriptions, exact parameters, typed bindings and authored consumers explain what is applied, who takes the periodic damage, the usable ATK-based equation, how the Ultimate scales an existing Burn request, and why Firekiss is a different damage-amplification layer. Native evaluator code and backend implementation are not prerequisites for these findings.

Maturity is `manually_confirmed` for exact raw/text joins and authored operations, with attributed public-model corroboration for the ordinary extra-trigger interpretation. No game session, simulator, Direct or test suite was run; no local-runtime E is added. W09/W10/W12 remain active beyond these named claims.

## 2. Exact source register

Paths below are relative to the pinned TBGD repository. The path, revision, blob and occurrence selector together form the audit identity.

| Ref | Path and selected occurrences | Blob |
| --- | --- | --- |
| S1 | [ExcelOutput/AvatarSkillConfig.json][S1]: `(SkillID,Level)=(121002,1/10),(121003,1/10),(121004,1/10)`; SkillTriggerKey, SkillDesc.Hash and ParamList | `a5416ced941c247d475b2aaa83277b9cdf474dd9` |
| S2 | [TextMap/TextMapCHS.json][S2]: exact description keys `10522593120453882406`, `173772522358125556`, `1257547725356166088` | `0889d38b4014e27daa7229b1dd517a5e93e81821` |
| S3 | [Config/ConfigCharacter/Avatar/Avatar_Guinaifen_00_Config.json][S3]: Skill02/Skill03/SkillP01 entries and DynamicValues.Floats | `8f5d214f18593f1d1f9162b36844b72c46928ac1` |
| S4 | [Config/ConfigAbility/Avatar/Avatar_Guinaifen_00_Ability.json][S4]: Skill02_Phase02, Skill03_Phase02, PassiveSkill01, and named Oil/Oil_Sub modifiers | `011c0f8851b6e594183764e6ab71ec0e21eac991` |
| S5 | [Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json][S5]: named `MCommon_DOT_Burn`, especially OnStack, OnPhase1 and OnCustomEvent | `2db782ddc81b7a1328e4086dc71c8a23295b06a8` |

S1/S2 are large files: empty Contents payloads were recovered through their exact Git blobs, then the selected rows/text were inspected. Empty transport output was not treated as absent data. No default-branch replacement is used as pin authority.

Reused context: [R0 execution vocabulary][R0], [R2 Break distinction][R2], [ordinary RNG/callback evidence][RNG], and [public mechanics method][METHOD]. The old RNG record's Guinaifen traversal is refined below, not replaced with a new whole-board random-target interpretation.

## 3. Skill text is linked semantic evidence

The join is `SkillID + Level -> SkillDesc.Hash -> same-pin TextMapCHS entry`, not a description found only by name on a current website.

| Skill | Exact description hash | Meaning established by the authored description |
| --- | --- | --- |
| 121002 / Skill02 | `10522593120453882406` | Primary and adjacent Fire damage are separate. The primary and adjacent targets receive a base-chance Burn attempt. Burn deals Fire DoT based on Guinaifen's ATK at the affected enemy's turn starts for the specified duration. |
| 121003 / Skill03 | `173772522358125556` | Deals separate Fire damage to all enemies. A currently Burned target's existing Burn immediately produces the specified fraction of its original damage. |
| 121004 / SkillP01 | `1257547725356166088` | With Guinaifen on the field, Burn damage provides a base-chance opportunity to apply Firekiss (吞火). Firekiss raises damage received, has its own duration and a stack limit. |

S2's Skill02 placeholders `#1..#5` correspond here to S1 ParamList indices `0..4`; Skill03 `#1/#2` to indices `0/1`; talent `#1/#4/#5/#6` to indices `0/3/4/5`. This is a verified correspondence for these descriptions, not a global claim that every localization placeholder addresses ParamList directly. Formatting such as `[i]` or `[f1]` does not replace exact numeric coefficients.

A linked description is strong evidence for the declared mechanic, not merely a search hint. It is not proof of every unmentioned exception or an engine enum's native name. Disagreement between prose and graph must be exposed; section 8 retains one such timing question rather than silently normalizing it.

## 4. Exact parameters and consumer bindings

Selected raw arrays in S1:

```text
Skill121002 Lv1  = [0.6, 0.2, 1, 0.83904, 2]
Skill121002 Lv10 = [1.2, 0.4, 1, 2.18208, 2]
Skill121003 Lv1  = [0.72, 0.72]
Skill121003 Lv10 = [1.2, 0.92]
Skill121004 Lv1  = [1, 0, 0, 0.04, 3, 3]
Skill121004 Lv10 = [1, 0, 0, 0.07, 3, 3]
```

| Read in S3 | Hash | Consumer / meaning in the selected chain |
| --- | --- | --- |
| SkillParam(Skill02,0) | `-1847083384` | Immediate primary DamagePercentage |
| SkillParam(Skill02,1) | `2004444791` | Immediate adjacent DamagePercentage |
| SkillParam(Skill02,2) | `242174909` | Burn AddModifier.Chance; base chance, not guaranteed final application |
| SkillParam(Skill02,3) | `-883252236` | `Modifier_Burn_DamagePercentage` injected into Burn |
| SkillParam(Skill02,4) | `-1016908754` | Burn LifeTime |
| SkillParam(Skill03,0) | `-56289053` | Ultimate's immediate all-enemy DamagePercentage |
| SkillParam(Skill03,1) | `878411509` | `TriggerModifierCustomEvent` value under `DOT_TriggerRatio` |
| SkillParam(SkillP01,0) | `674451867` | Firekiss application base chance |
| SkillParam(SkillP01,3) | `-26169913` | Firekiss per-layer `MDF_PropertyValue2` |
| SkillParam(SkillP01,4) | `-156957008` | Firekiss LifeTime |
| SkillParam(SkillP01,5) | `-545598557` | Firekiss base MaxLayer; E6 has a separate increment branch |

Talent indices1/2 remain raw zero-valued slots. They are not Burn coefficients or proof that Firekiss has zero duration: the actual Oil_Sub consumers use indices3/4/5. Equal values across skills also do not imply equal roles: the Ultimate's two Lv1 values are both 0.72 but feed different operations.

At Lv10 the Burn operand is exactly `2.18208` (218.208%), not a rounded `2.18`. Precise parameters stay pinned even when a public page or formatted description displays fewer decimals.

## 5. Application: one blast target contract, internal traversal, then distinct damage

S3 declares `Skill02.TargetInfo={EnemySelect, SubTargetType=TargetAdjoinEntity}` and its Phase01 entry. In S4 select `AbilityList[Name=Avatar_Guinaifen_00_Skill02_Phase02]`:

```text
OnStart[1]: FireProjectile
  OnProjectileHit[0]: optional Rank01 status-resistance application
  OnProjectileHit[1]: Retarget
    TargetAlias=AbilityTargetAndAdjoinEntity
    ByRandom=true; MaxNumber=3
    TaskList[0]: E2-and-already-Burned predicate
      FailedTaskList[0]: ordinary AddModifier(ParamEntity,MCommon_DOT_Burn)
      SuccessTaskList[0]: same modifier with E2-adjusted Burn operand
  OnProjectileHit[2]: primary direct Fire damage
  OnProjectileHit[3]: adjacent direct Fire damage
```

The ordinary installation has `StackingFlag=CharacterSkill`, Chance from index2, LifeTime from index4, and named `Modifier_Burn_DamagePercentage` from index3. The E2 branch adds the distinct SkillRank(Rank02,0) input/hash `1589728048` when the target already carries `STAT_DOT_Burn`. E0 examples use the ordinary branch.

**The random flag does not mean three arbitrary enemies.** Its candidate domain is the selected primary plus adjacent targets, matching the skill text. It is internal ParamEntity traversal, not another external target choice. Exact random ordering, draw count and replacement implementation are not inferred; they are unnecessary to identify this candidate domain and the application operands.

The two later direct damage tasks consume indices0/1 and different target aliases. They must not be used as the periodic Burn coefficient. Authored task-site order is recorded without claiming a universal nested callback completion order. Projectile flight, camera effects and WaitSecond values are not the enemy's logical turn timer.

## 6. Shared Burn: natural periodic request and usable equation

S5 `MCommon_DOT_Burn` explicitly has MaxLayer=1, LayerAddWhenStack=1, `Stacking=ReplaceByCaster`, `LifeStepMoment=ModifierPhase1End`, `UseSnapshotEntity=true`, and flags including `STAT_DOT` and `STAT_DOT_Burn`.

Its OnStack reads the holder's modifier Layer into `_Layer` (working hash `1912601768`). Its OnPhase1 damage task targets `ModifierOwnerEntity` and declares Fire / `AttackType=DOT` / `DamageTag={EnumIndex:3,Value:32}`.

The ordinary percentage expression is:

```text
DamagePercentage.PostfixExpr:
  OpCodes=AQABAQQR
  DynamicHashes=[1614570279,1912601768]
  interpreted operands: Burn percentage * _Layer
```

This uses R0's retained small postfix multiplication vocabulary. The named installation input `Modifier_Burn_DamagePercentage` and the shared percentage reader are reconciled through the matching producer/consumer roles and S2's explicit formula meaning; this checkpoint does not claim a newly recovered native name-hashing or context-lookup implementation.

For this selected ordinary Guinaifen Burn, define `A_G` as the Guinaifen ATK used by the effect, `p` as its admitted Burn percentage, and `L` as this modifier's layer count:

```text
base Burn term B = A_G * p * L
ordinary damage D = B * M
```

`M` collects applicable damage bonuses, target mitigation/vulnerability and other damage modifiers. The equation is a useful gameplay model joined to pinned inputs, not a claim that all components of the damage evaluator were rederived here. S2 identifies the scaling character; S4 supplies p; S5 supplies layer multiplication, holder targeting and DOT/Fire classification. For the selected one-layer state L=1.

The generic shared template also has `DamageValue` and a ByDefence `ExtraDamagePercentage` channel. S4's selected installation supplies the named ATK-percentage input, and S2 describes ATK scaling. The extra channels are not permission to invent a Guinaifen DEF term; conversely this record does not fabricate zero-valued raw fields or native defaults for unsupplied generic slots. Other installers may use this reusable template differently.

S2's affected-enemy turn-start wording gives the selected OnPhase1 callback its observable timing. Duration2 and ModifierPhase1End form the corresponding authored lifetime surface. `PerformTime=0.3` and presentation waits do not mean a 0.3-second DoT interval. No complete generic phase dispatcher is required to retain the selected enemy-turn-start interpretation.

`UseSnapshotEntity=true` remains a real routing input, not proof that every stat freezes at application. This record does not establish all ATK/buff refresh or reapplication snapshot rules.

## 7. Ultimate: extra activation is not Burn application or a normal duration step

S4 `AbilityList[Name=Avatar_Guinaifen_00_Skill03_Phase02].OnStart` contains:

```text
[1] DamageByAttackProperty(AllEnemy, direct percentage=Skill03 index0)
[2] TriggerModifierCustomEvent(
      AllEnemy,
      EventType={EnumIndex:4,Value:2},
      DynamicKey=DOT_TriggerRatio,
      Value=AQAR/[878411509])
```

Keep the exact typed event pair: this occurrence does not serialize a readable `DOT_TriggerBurn` event name. The skill description provides the Burn-specific meaning. The inspected source does not expose the entire native event-type-to-modifier routing implementation; no enum name or global routing algorithm is invented.

S5's Burn OnCustomEvent callback has a Fire/DOT damage task, again targeting the holder. Its percentage becomes:

```text
OpCodes=AQABAQQBAgQR
DynamicHashes=[375103313,1614570279,1912601768]
interpreted operands: DOT_TriggerRatio * Burn percentage * _Layer
```

Its flat and extra-DEF channels are likewise multiplied by the extra-trigger input. This is an additional scalar on the existing status's damage operands, not the Ultimate's direct ATK coefficient and not a second Burn AddModifier. The selected callback contains no authored lifetime reduction, timer reset, RemoveModifier or Burn reinstallation.

The positive ordinary model is `extra Burn damage = q * B * M_extra`, with q=0.72 at Ultimate Lv1 and q=0.92 at Lv10. At identical damage conditions this is q times a normal tick. **It is not necessarily q times the last displayed tick:** target vulnerability and other applicable conditions may have changed, and the callback evaluates operands rather than reading a saved displayed-damage number.

[KQM's Kafka guide][P2], explicitly Version1.2, independently explains ordinary extra DoT activations as non-duration-consuming and retaining the original DoT owner's scaling. That is an attributed mechanism cross-check, not a new Guinaifen experiment or a universal rule for all later special DoTs. Together with S2's existing-Burn wording and S4/S5's separate custom callback, it supports treating this selected extra activation separately from natural turn ticking. Native timer dispatch and special interactions are not newly executed evidence.

The same principle distinguishes originating damage stats from the character requesting an extra activation. The selected Guinaifen self-Burn example is closed; the text covers a target's existing Burns without restricting them to her own. A full second-applier/Break-Burn source matrix was not run here and is not inferred from this single ordinary template.

## 8. Firekiss is a separate debuff and damage-taken layer

S4 provides this source-facing listener chain:

```text
Avatar_Guinaifen_00_PassiveSkill01.OnStart
  -> MAvatar_GuiNaiFen_00_PassiveSkill01_Modifier on Caster
  -> OnListenCharacterCreate: AddModifier(AllDarkTeam,MAvatar_Guinaifen_00_Oil)
  -> Oil.OnBeforeBeingHitAll
     ByDamageSourceContainBehaviorFlag(STAT_DOT_Burn)
     -> AddModifier(holder,MAvatar_Guinaifen_00_Oil_Sub)
        Chance=SkillP01[0], LifeTime=SkillP01[4]
        MaxLayer=SkillP01[5] (+ separate E6 branch)
        LayerAddWhenStack=1
        MDF_PropertyValue2=SkillP01[3]
  -> Oil_Sub.OnStack
     read layer -> MDF_Layer
     MDF_PropertyValue = MDF_Layer * MDF_PropertyValue2
     StackProperty(holder,AllDamageTypeTakenRatio,MDF_PropertyValue)
```

The last multiplication uses hashes `-2125946860` and `1662446059`; the result is consumed through `2128130574`. Firekiss has its own instance, layers, lifetime and application chance. It is not another name for Burn, a second DoT tick, an ATK increase or a higher value of Skill02's p.

At talent Lv10 without E6, v=0.07, duration=3 and maximum layers=3, so three layers contribute **0.21 to AllDamageTypeTakenRatio**. In an isolated ordinary model with no other damage-taken modifiers this corresponds to a 1.21 multiplier. This arithmetic does not audit every vulnerability-composition exception or claim a new game observation.

**Specific unresolved timing detail:** S2 narrates Firekiss following Burn damage, while S4 places the installer under `OnBeforeBeingHitAll`. Both facts are preserved. The callback name alone cannot prove whether a newly installed stack modifies that same triggering damage or only later damage; a narrowly controlled first-tick/existing-stack comparison or a matching detailed test can resolve it. This does not invalidate the established trigger family, stack arithmetic or separate vulnerability role.

The selected predicate tests a damage-source Burn flag, not merely Fire element or an arbitrary hit. Do not classify direct Fire damage as a Firekiss trigger by element name alone. No complete claim about off-field/removed-owner cleanup or every damage-source attribution is made.

## 9. Useful predictions and discriminators

These are calculations/inspection expectations, not measured gameplay results:

| Specified conditions | Prediction / source discriminator |
| --- | --- |
| E0 Skill02 Lv1, effect ATK=3000, one Burn layer | Base term 2517.12 before M. |
| E0 Skill02 Lv10, same ATK/layer | Base term 6546.24; using a rounded 218% instead would incorrectly give 6540. |
| Same Lv10 Burn, Ultimate Lv10, otherwise unchanged conditions | Extra base term 6022.5408 before M_extra, from q=0.92. |
| Talent Lv10, three already-existing Firekiss layers, no E6 | Target damage-taken contribution0.21; it does not change p=2.18208. |
| Ultimate on a target without Burn | Direct all-enemy damage is still described; no existing Burn means no Burn damage contribution to multiply. |
| Different prior displayed tick but changed target vulnerability | Re-evaluate current applicable damage conditions; do not multiply a historical display value blindly. |

The last two are discriminating behavioral expectations, not fabricated new tests. Display rounding, HP loss and critical/special-DoT exceptions are not inferred from these arithmetic examples.

## 10. Public corroboration and evidence accounting

Public pages read on 2026-09-23:

- [KQM SRL Guinaifen][P1] reproduces the skill, Ultimate, talent and trace descriptions. It corroborates the declared shapes; its interactive skill-level display and rounded percentages are not pin-exact coefficient authority or independent experiments. Its separate Guinaifen Evidence Vault page has empty mechanics headings, which are not test evidence.
- [KQM Kafka guide][P2], Version1.2, supplies an authored ordinary-DoT ownership/extra-activation model. This record adopts only the stated comparison in section7, not a newly traced Kafka kit or an assertion covering future special effects.

| Claim | Evidence and result | Deliberate limit |
| --- | --- | --- |
| What Skill02/03/P01 say | S1 exact hashes joined to S2 same-pin text | Description does not silently define omitted edge cases. |
| Burn application inputs and fixed blast candidate domain | S3/S4; exact ParamList/read/task chain | Generic RNG draw/order semantics not recovered. |
| Enemy-turn-start ATK-based Burn | S2 meaning plus S4 installation and S5 holder/callback/operand chain | Native snapshot/evaluator bodies not required; all refresh behavior not claimed. |
| Extra activation scalar and separate entry | S2/S4/S5 plus attributed P2 ordinary model | Raw event pair retained; no fabricated native enum/routing body. |
| Firekiss separate vulnerability and layer arithmetic | S1/S2/S3/S4 | Same-triggering-hit stack effectiveness remains a specific question. |
| Runtime correctness | Not tested here | No backend prerequisite, code changes or E promotion. |

The bounded selected source/model chain is recorded; broader W09/W10/W12 obligations remain open. Remaining questions are specific: same-hit Firekiss effectiveness, detailed snapshot/refresh behavior, and exact typed custom-event routing across other Burn families. They can be advanced by relevant descriptions, reliable tests or source discriminators, not only by finding native code. No backend repair workflow is introduced.

## 11. Reuse and publication

This checkpoint adds the present record and README navigation/method clarification only. Existing broad worklist leaves are not checked as whole-mechanism completion. Source-family classification is not broadened to all TextMap: mechanically meaningful, skill-linked prose is evidence; unrelated names, icons, story and UI text remain distinct.

Validation consisted of actual pinned row/text/graph inspection, exact blob identification, arithmetic consistency checks and documentation review. No game/runtime/test/CI execution is represented as performed. The PR checkpoint records the actual published commit and changed paths separately.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillConfig.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/TextMap/TextMapCHS.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Guinaifen_00_Config.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Guinaifen_00_Ability.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json
[P1]: https://srl.keqingmains.com/characters/fire/guinaifen
[P2]: https://hsr.keqingmains.com/kafka/
[R0]: battle_execution_language_core_v1.md
[R2]: weakness_toughness_break_vertical_slice_v1.md
[RNG]: ordinary_rng_callback_reference_chains.md
[METHOD]: public_mechanics_healing_shield_reconciliation_v1.md
