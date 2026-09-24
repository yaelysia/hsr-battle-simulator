# General weakness, toughness, Weakness Break and Super Break v1

## 1. Scope and result

Reviewed **2026-09-24**. Evidence parent: `21c3d13a47d36dea57a25aa82b0915f4e6c4f3ea`. Raw authority is `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains Draft and documentation/evidence-only.

This is **F03's first reusable shared-rule map**, principally W06 with W04/W09/W10 dependencies. It explains ordinary weakness and toughness, unit normalization, initial Break damage, the seven shared elemental outcomes, and the shared Super Break request. Actors are evidence anchors, not the subject of another complete kit investigation.

The result is positive gameplay rules plus their source map. It supersedes R2's blanket refusal to use public explanations for the covered observable mechanics. It does **not** erase R2's actual skill-context injection gap, invent missing JSON fields, or claim every special toughness regime is covered. F03 and W06 remain active for the precise residuals in section 10.

Exact fields, expressions and calls are manually confirmed. Published mechanics and reproduced skill wording support explicitly attributed interpretations. Numerical examples are predictions, not measurements. No game session, simulator, Direct, tests or workflow was run; no backend code was inspected or changed and no local-runtime E is added.

## 2. Evidence register

### Pinned source and reused chains

Paths are relative to the pinned upstream repository. A named object/field selector plus the path, full revision and complete blob identifies the occurrence; unobserved numeric array offsets are not invented.

| Ref | Exact source / selected occurrences | Complete blob |
| --- | --- | --- |
| S1 | [ExcelOutput/AvatarBreakDamage.json][S1], `Level` -> `BreakBaseDamage`; especially levels 1/70/80 | `6a246c257b106f0afab04807901822d1ea45b273` |
| S2 | [Config/ConfigAbility/Avatar/Avatar_Common_Ability.json][S2], `Avatar_Common_PassiveSkill`; `TriggerStanceCountDown_Test.OnTriggerBreak`; shared DynamicValues | `21db58fafcb8fa826c5913b4e019d6c9e56e5f6f` |
| S3 | [Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json][S3], all seven `StanceBreak_*` templates and `DealSuperBreakDamage` / `BeingDealSuperBreakDamage` | `d1da985fbac1bcf4e23f3c1dcdf7dfd11bcb5c96` |
| S4 | [Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json][S4], `ModifierMap.MCommon_Element_Bleed/Frozen/Burn/Poison/Electric/Confine/Entangle` | `2db782ddc81b7a1328e4086dc71c8a23295b06a8` |

S1/S2 and the selected S3/S4 branches were read at the pin in this investigation. Useful S3 read regions are the elemental block around lines 550-1500 and Super Break around 4200-4550; S4's elemental block is around 5770-8120. Named selectors are authoritative when locating an individual task within those regions. The similarly named earlier `MCommon_DOT_*` and control-only families are not substituted for `MCommon_Element_*`.

Reused rather than rediscovered: [R2] supplies the ordinary Asta/Dan Heng/Gallagher skill rows and shared StanceValue reader, the explicit monster Stance input, static weakness/RES distinction, ordinary owner-to-common-passive reachability, and the Sam/StageCommon Super Break caller/accumulator context. [F02] supplies common monster reduction installation, break removal and recovery restoration. [Burn] supplies an independently identified ordinary skill DoT for the formula-family contrast. Their exact raw joins remain available in those records.

### Public descriptions and models

Accessed 2026-09-24. A retrieval date is not a claim that a page describes every feature of the pinned revision or the latest live patch.

| Ref | Source / context | Adopted use and evidence limit |
| --- | --- | --- |
| P1 | [KQM beginner guide][P1], Elements and Break Effect explanations | Ordinary depletion and elemental behavior, including periodic versus control/delayed effects. An authored guide, not a new test in this investigation; unrelated progression advice is not used. |
| P2 | [Guoba, Calculating & Understanding Super Break!][P2], original report dated 2024-05-09, with unit-conversion edit labelled 25/06 | Break versus Super Break factors, old-to-displayed toughness conversion, and source-specific conversion bonuses. The search-indexed original post was read; direct page opening failed. Its calculator was not executed and its worked numbers are not our measurements. |
| P3 | [KQM Ruan Mei guide][P3], marked Version 1.6 | Published Skill/A2 wording separates Weakness Break Efficiency from Break Effect; Ultimate wording demonstrates a recovery-interception exception. Only these mechanic discriminators are used, not a new Ruan Mei source audit. |
| P4 | [真面目にゲームする！: toughness and Break calculation][P4] | Published explanation of the ordinary maximum-toughness normalization. It cites public data for its level coefficients, so it is not an independent experimental verification of that table; S1 supplies our exact numbers. |

Descriptions and established models are evidence, not merely navigation. Conversely, agreement between two pages copying the same data is not two independent experiments. P1's casual statement elsewhere that resistances drop on breaking is not used as a universal RES mutation: [R2]/[F02] distinguish the actual common reduction state from elemental resistance.

## 3. Separate four quantities before calculating

| Quantity | What it governs | What it is not |
| --- | --- | --- |
| Weakness membership | Which damage types can ordinarily reduce this target's toughness | A numerical damage-RES value |
| Toughness reduction Q | How much an eligible hit contributes toward depletion, or to a specifically authored Super Break calculation | HP damage, ATK scaling or Break Effect |
| Maximum toughness T | The target's full toughness capacity; an input to ordinary initial Break and certain later effects | The amount remaining before a hit, or that hit's Q |
| Break Effect b | The scaling of Break-related damage and specified elemental delays | A general increase to Q |

In the ordinary matching-weakness case, positive eligible Q reduces the remaining gauge; reaching zero triggers Weakness Break. HP damage can occur without reducing toughness. Weakness protection/locks, weakness-ignore attacks, implants and explicit alternate toughness rules require their own conditions. [P1, R2]

An increase to damage bonus or ATK does not by itself enlarge Q. With only one ordinary efficiency contribution eta and no other adjustment, `Q = Q_base * (1 + eta)`. P3's declared efficiency buff explains this role independently of its distinct damage bonus and Break Effect effects. Other additive reductions, conditional multipliers and special caps must retain their own producer; this v1 does not invent an exhaustive Q formula from one buff.

[R2]'s `StanceWeakList`, `DamageTypeResistance` and `DebuffResist` are three different inputs. A weakness implant is not automatically a RES reduction. Likewise, an explicit weakness-ignore condition is not automatically permission to bypass a toughness lock. These are applicability distinctions, not reasons to leave the ordinary rule unknown.

### 3.1 Old raw units, displayed units and normalized basic units

Use explicit units throughout:

```text
T_old = 3 * T_display
Q_old = 3 * Q_display
normalized basic unit = Q_old / 30 = Q_display / 10
```

P2 explicitly documents the factor-of-three convention change. R2's already-inspected ordinary basic rows contain both `ShowStanceList=[30,0,0]` and `StanceDamageDisplay=10`. The paired values are consistent with that model; they are not proof that one field is copied into a particular hidden context slot. This is a unit conversion, not a threefold change to combat effectiveness.

For the unmodified basic examples already in R2, 30 old units and 10 displayed units represent the same reduction. Do not generalize that amount to enhanced basics, every Technique, every hit of a multi-hit skill or every enemy action. Preserve an explicit unit label for all imported tables and public calculations.

**Two assertions stay separate:** the ordinary observable amount/unit interpretation is usable; the exact loader assignment into dynamic hash `1659254037` remains unidentified. R2's bounded injection gap is retained. It is no longer a reason to label both 30 and 10 semantically uninterpretable. The independent monster `Skill405201002/index1=30 -> hash1127134183 -> StanceValue` chain is not used to fabricate the missing avatar assignment.

## 4. The shared transition, level source and damage context

### 4.1 Transition versus elemental consequence

Reuse the ordinary common-passive chain from R2/F02:

```text
ordinary monster -> common break listener
  OnBeingBreak -> StanceBreakState + remove MonsterAllDamageReduce
  StanceBreakState.OnCreate -> holder ModifyActionDelay(+0.25 normalized)
                           -> distinct TriggerBreak notification surface
  OnEndBreak -> RemoveSelfModifier
  OnDestroy -> ResetStance / SetStanceCount / restore common reduction
```

The zero-depletion interpretation comes from the gameplay model, not from an invented `Stance <= 0` JSON predicate. Restoration requests are explicit; special recovery interception and detailed multi-action timing are separate. P3's Ultimate description shows why the next attempted recovery cannot always be treated as an unconditional transition.

On the attacker-side shared path, S2's `TriggerStanceCountDown_Test.OnTriggerBreak` has seven `ByCharacterDamageType(ModifierOwnerEntity, type)` branches calling S3's corresponding template. Its `_Test` suffix does not exclude this ordinary-reachable path. This selected dispatcher reads character damage type; it is not proof of how every overridden attack element or secondary entity is attributed. Preserve those exceptional cases rather than silently replacing the raw selector.

Break state, initial extra damage, elemental-status application, periodic/delayed status damage and later recovery are distinct surfaces. The common 10% reduction described in F02 is not an elemental-RES change and must not be counted twice. An elemental status's duration is not automatically the lifetime of `StanceBreakState`.

### 4.2 Actual pinned level table

S1 provides a direct reusable coefficient source:

| Level | BreakBaseDamage |
| ---: | ---: |
| 1 | 54 |
| 70 | 2659.6406 |
| 80 | **3767.5535** |

Let `L(level)` denote this lookup. Some public formulas use `3767.5533`; our exact pinned row is `3767.5535`. The difference is retained, not rounded away or silently used to overwrite the source. Rows above ordinary playable levels do not prove that an avatar can legally be built at those levels.

The table is an identified source of level-based Break data, not a recovered native lookup implementation. S2 also declares working values without assignments; those must not be described as new typed table bindings merely because the magnitudes are expected.

## 5. Initial Weakness Break damage

For the ordinary shared elemental model, before explicit special overrides:

```text
H(T) = 0.5 + T_old / 120 = 0.5 + T_display / 40
B_initial = L(level_breaker) * e * H(T_max)
D_initial = B_initial * (1 + b_breaker) * M_applicable
```

`e` is the elemental Break coefficient in section 6, not elemental DMG Bonus. `M_applicable` contains the applicable defender DEF, damage RES/PEN, vulnerability, reduction and explicit Break-related modifications. Reuse F02 only for factors that actually apply; do not import ordinary ATK/crit/DMG%-bonus factors wholesale. P2's ordinary Break model supplies the factor roles; P4 gives H's normalization; S1/S3 provide the level data and elemental expression structure.

The breaker supplies the level/Break Effect for the ordinary initial event. The target supplies T_max and defender state. A teammate who merely enabled a mechanic is not thereby the damage-stat owner. Distinct proc damage may have a different owner and must be traced separately.

### 5.1 What the exported expression does and does not prove

S3 reads `MaxStance` from `ParamEntity` into `TargetStance`. Its elemental requests use `FormulaType=ByBreakDamage`, `AttackType=ElementDamage`, and `FinalFormulaType=ByPureDamage`.

A representative expression is:

```text
BreakDamagePercentage:
  OpCodes = AAAAAQEAAQEFAgQAAgUR
  FixedValues = [e, 2, 4]
  DynamicHashes = [-1293338785, -276098552]
  expression shape = e * (2 + h0 / h1) / 4
```

The Physical/Fire forms reuse the literal 2 and serialize `AAAAAAEAAQEFAgQAAQUR`, with fixed values `[2,4]`. The retained postfix vocabulary distinguishes multiplication/addition/division; the result is not a skill ATK coefficient.

The conventional interpretation `h0/h1 = T_old/30` yields exactly `e * H(T)`. This is an explicit source/model reconciliation, **not** a claim that a new raw assignment `h1=30` was discovered. S2 declares these working hashes with `ReadInfo.Type=None`; the particular native context injection remains separate. `ByPureDamage` is also not evidence that defender DEF/RES are bypassed.

An attack that depletes the last point can contain ordinary hit damage, an initial Break event and other effects. This formula is not permission to give all those instances the same sampled defender state. The threshold-crossing hit's exact reduction/rounding and multi-hit allocation remain a named boundary; later stable broken-state calculations are not withheld because of it.

## 6. Seven shared elemental branches

The table states **pre-Break-Effect, pre-target-multiplier base terms**. Let `L=L(level_breaker)`, `H=H(T_max)`, `HPt=target MaxHP`. Apply the relevant `(1+b)` and damage factors afterwards; do not apply Break Effect twice to an already-computed `DamageValue`.

| Break type | Initial e | Shared installed modifier | Ordinary later base/effect | Authored installation lifetime |
| --- | ---: | --- | --- | ---: |
| Physical | 2 | `MCommon_Element_Bleed` | `min(r * HPt, 2 * L * H)` per eligible pulse; r=.16 in ordinary lower-rank branch, .07 in elite/boss interpretation | 2 |
| Fire | 2 | `MCommon_Element_Burn` | `L` per layer per eligible Burn pulse | 2 |
| Ice | 1 | `MCommon_Element_Frozen` | `L` additional damage; freezes the action, with the selected current delay-cost rule below | 1 |
| Lightning (`Thunder`) | 1 | `MCommon_Element_Electric` | `2 * L` per layer per eligible Shock pulse | 2 |
| Wind | 1.5 | `MCommon_Element_Poison` | `L * n`; ordinary rank branch installs 1 or 3 layers; definition MaxLayer=5 | 2 |
| Quantum | .5 | `MCommon_Element_Entangle` | `.6 * L * H * n` when the delayed damage resolves; ordinary model n=1..5; extra delay `.2*(1+b)` | 1 |
| Imaginary | .5 | `MCommon_Element_Confine` | No damage task in this inspected modifier; extra delay `.3*(1+b)` and SpeedAddedRatio contribution -.1 | 1 |

S3 provides the elemental coefficients, named installers, lifetimes and inputs; S4 provides damage/property/condition consumers. P1 supplies the ordinary observable interpretation of the periodic and control outcomes. The table is not a claim that every similarly named character-created status uses these shared Break formulas.

Selected elemental installers serialize `Chance=1.5`. This is an application input, **not a 150% final probability or a guarantee against immunity**. Status success and the toughness-break transition are different questions. Detailed hit/RES/category-immunity evaluation belongs to F05; its absence does not erase the declared effect or its formula.

### 6.1 Physical: target-HP scaling has an explicit cap

`StanceBreak_Physical` supplies `MDF_CommonRatio=.16`, `MDF_SpecialRatio=.07` and `MDF_DamageMax`. The latter expression includes the working Break base and the same maximum-toughness structure as initial Physical Break.

`MCommon_Element_Bleed` reads the holder's MaxHP, uses `ByCompareMonsterRank(Greater,2)` to choose the special ratio, writes the candidate `MDF_DamageValue`, then caps it against hash `1008130519` (the injected maximum). It separately reads `BreakDamageAddedRatio` from `SnapshotPropertyEntity`.

Its periodic `DamageValue` expression is `AQAAAAEBAgQBAgQR`, fixed `[1]`, hashes `[286452074,369211422,1912601768]`: capped base times `(1+Break Effect)` times layer. Its request has `AttackType=DOT`, `FinalFormulaType=ByPureDamage`; the base was already formed as a DamageValue rather than a fresh ATK percentage. An extra-trigger callback has an additional ratio input.

This is why ordinary Break Bleed is neither an uncapped fixed percentage of boss HP nor a copy of a character's ATK-scaling Bleed. The literal rank predicate is retained; the elite/boss label is a gameplay interpretation, not a substituted raw enum.

### 6.2 Wind: stronger elite/boss application is layer count, not initial e

S3's Wind template tests `ByCompareMonsterRank(GreaterEqual,3)`. Its success installer passes `LayerAddWhenStack=3`; the other installer relies on S4's explicit definition value 1. The definition's MaxLayer is 5.

OnPhase1 reads the actual modifier layer into `MDF_PoisonLayer`; the damage expression multiplies hashes `[1486739431,-520506105]`. Thus the stronger ordinary elite/boss periodic outcome is explained by layers. The initial coefficient remains 1.5. Shared skill Wind Shear and Break Wind Shear must not be joined solely because both raw names contain Poison.

### 6.3 Ice and Quantum are not DOT merely because damage happens later

Frozen's OnPhase1 requests Ice / `ByBreakDamage` / **`AttackType=Pursued`**, with the installed damage percentage. Its behavior flags include DisableAction and control/frozen flags. That callback also calls `ModifyCurrentSkillDelayCost(ModifyFunction=Set, NormalizedValue=.5)`.

P1 describes the ordinary skipped frozen action and faster following turn. The .5 cost is the source-side counterpart of that shorter interval; it is not an additional +50% delay pasted onto the initial Break delay. This does not reconstruct a universal scheduler or decide every interaction between Freeze, attempted recovery and extra actions.

Entangle's OnPhase1 also uses **Pursued**, not DOT. Its percentage expression `AAABAAIBAQQR`, fixed `[1]`, hashes `[-434232686,1486739431]`, multiplies the injected percentage by one plus the working hit count. Before/after-being-attacked callbacks maintain a gated count with a dynamic maximum. P1's ordinary 1-to-5 interpretation is adopted; this record does not claim that every count-increment/override input was newly sourced or that every visual hit increments it.

The corresponding Quantum installer supplies the `.6 * H` damage coefficient and .2 delay input. Neither Quantum delayed damage nor Frozen damage should be routed through a generic DOT-only trigger solely on the basis of their timing.

### 6.4 Common delay versus elemental delay and speed

The common break-state request is fixed `+.25` normalized. It does not multiply that term by Break Effect. Separately, Confine and Entangle write `ModifyActionDelay` from `delay_ratio * (1 + BreakDamageAddedRatio)`, using `AQAAAAEBAgQR`, fixed `[1]`, hashes `[-2109623552,369211422]`.

Confine reads the property from Caster; Entangle reads it through SnapshotPropertyEntity. Confine independently writes the negative speed ratio. Preserve these selectors: the two delay expressions do not prove identical snapshot semantics, and speed reduction is not the same operation as adding action delay.

In the ordinary unmodified model, the requested common-plus-elemental delay components are `.25 + .2*(1+b)` for Quantum and `.25 + .3*(1+b)` for Imaginary; Imaginary additionally contributes -.1 to SpeedAddedRatio. These are components, not a claim that their sum alone determines final displayed AV under all speed/control interactions.

## 7. Super Break: attack reduction, not target maximum toughness

An ordinary Super Break **enabler and its applicable target/attack conditions** must exist. Breaking a target alone is not a universal Super Break passive. The baseline described by P2 operates in the broken-state window; explicitly authored alternative enablers/state rules must be audited separately rather than rejected by a universal hard-coded rule.

For one admitted source of the ordinary shared calculation:

```text
B_super = L(level_damage_source) * (Q_old / 30) * s
        = L(level_damage_source) * (Q_display / 10) * s
D_super = B_super * (1 + b_damage_source) * M_applicable
```

`s` denotes the actual source's conversion coefficient and any separately proven source-specific multiplier. It is not a universal Trailblazer bonus or an assumed raw default of 1. P2 explicitly separates the Trailblazer-specific additional multiplier from other sources. Initial-Break e and H(T_max) are absent here.

Therefore increasing Q can increase Super Break even when ATK is unchanged; increasing target maximum toughness does not directly increase this base when Q and all other conditions are fixed. Element can still affect weakness applicability and target RES, so absence of an elemental Break coefficient does not imply identical final damage against every resistance profile.

### 7.1 Exact shared consumer

S3 `DealSuperBreakDamage`:

```text
Retarget(TemplateParamEntityList, ByRandom=true)
 -> define TDF_TotalStanceDamageOnTarget in ContextTaskTemplate
 -> test template-context StanceValue < 0
    success: copy MDF_TotalStanceDamage from target's
             MStageAbility_BattleCommonRule_SuperBreak_SubOnEnemy
    failure: use the explicit StanceValue input
 -> require TDF_TotalStanceDamageOnTarget > 0
 -> DamageByAttackProperty(ParamEntity)
      FormulaType=ByBreakDamage
      AttackType=ElementDamage
      DamageTag={EnumIndex:3,Value:33}
      BreakDamagePercentage:
        OpCodes=AQABAQAABQQR
        FixedValues=[30]
        DynamicHashes=[44044987,1039671212]
      FinalFormulaType=ByPureDamage
```

The expression is the source multiplier times accumulated/supplied Q divided by **literal 30**. This is direct exported denominator evidence, unlike R2's still-missing avatar StanceValue injection. The negative template-input branch selects the accumulator; it does **not** mean the enemy's remaining toughness is negative.

`BeingDealSuperBreakDamage` uses the same arithmetic with a holder-oriented target and alive guard, reading damage type from Caster. The outgoing form reads it from ModifierOwnerEntity. These two invocations retain different context roles. Matching algebra does not license substituting caster/owner/target identities.

R2's already-closed StageCommon/Sam path supplies ordinary caller/accumulator reachability; this round does not claim to have re-audited every write/reset in that accumulator. The target's gauge is already zero in the ordinary broken-state case, so Q cannot simply be implemented as `gauge_before - gauge_after`. Which portions of a threshold-crossing or multi-hit action enter the accumulator remains a specific transport/settlement question, not an unknown basic Super Break equation.

### 7.2 Distinguish four operations with superficially similar numbers

| Operation | Governing base/input | Not equivalent to |
| --- | --- | --- |
| Natural initial Weakness Break | Breaker level, initial elemental e, target T_max, Break Effect | An ordinary skill ATK hit |
| Extra activation of an existing Break DOT | Existing status's base/owner plus the activation ratio | A new depletion event or automatic duration decrement |
| Explicit repeat/proc of Break damage | Whatever Break base and owner its authored source specifies | Necessarily Super Break |
| Super Break | Relevant attack Q, source coefficient, damage-source level/Break Effect | Initial elemental Break coefficient times T_max |

S4's Break Burn/Wind/Shock/Bleed custom callbacks and the existing ordinary Burn record establish separate extra-activation surfaces. They are not permission to trigger every status through every custom event. Keep the literal event/tag identities and the caller's filtering authority.

## 8. Numerical discriminators

All numbers below are deliberate **model predictions before target mitigation, state-dependent reduction, special bonuses and rounding**. They are not an observed battle, not a new test report and not examples of fabricated canonical builds.

Use level80 (`L=3767.5535`), Break Effect100% (`b=1`), target maximum displayed toughness60 (`T_old=180`, `H=2`), and no additional source-specific multiplier unless specified.

| Deliberate case | Predicted base after Break Effect |
| --- | ---: |
| Initial Fire/Physical Break | `3767.5535 * 2 * 2 * 2 = 30140.428` |
| Initial Imaginary/Quantum Break | `3767.5535 * .5 * 2 * 2 = 7535.107` |
| Shared Super Break, Q_display20 and s1 | `3767.5535 * (20/10) * 2 = 15070.214` |
| Same Q_base with only +50% efficiency, hence Q_display30 | `22605.321` |
| One-layer Break Burn pulse | `7535.107` |

Doubling target maximum displayed toughness from60 to120 changes H from2 to3.5, increasing the initial base by1.75, **not by2**. It leaves the above Super Break base unchanged if Q and other inputs remain fixed. Doubling Break Effect from100% to200% changes its factor from2 to3, **not from2 to4**. Increasing ordinary ATK or crit alone changes none of these baseline terms.

An additional discriminator is a successful break against a target resisting the associated control status: depletion/state and elemental application must not be flattened into one guaranteed debuff. Exact resistance probabilities are intentionally not supplied by this v1.

## 9. Claim-level accounting

| Claim | Evidence level | Deliberate boundary |
| --- | --- | --- |
| Observable weakness/depletion and distinction from RES | Public rule + R2's separate raw fields/operations | Explicit locks, implants and overrides remain separate |
| 30 old / 10 displayed unit interpretation | P2 plus reused paired pinned skill fields | No invented loader-to-1659254037 edge |
| Level80 BreakBaseDamage3767.5535 | S1 exact raw row | Native lookup body and legal actor levels not inferred |
| Ordinary initial Break factorization | Attributed model + S1/S3 expression reconciliation | Working-context assignments, transition-hit sampling and special overrides not fully recovered |
| Seven named elemental installers and consumers | S2/S3/S4, with P1's observable interpretation | Not every character-created similarly named status |
| Physical cap, Wind layers, Frozen/Pursued distinction, elemental delays | Actual selected expressions/conditions/property reads | Global snapshot, reapply and scheduling algorithms not claimed |
| Shared Super Break denominator and input-mode selection | S3 literal30, copy/fallback, positive guard and damage request | Full accumulator producer/reset and multi-source arbitration not re-audited |
| Local runtime/test correctness | Not evaluated | No C/D/E implementation promotion or acceptance gate |

## 10. Precise residuals and next foundation

1. **Source transport:** retain the avatar `1659254037` loader gap and unresolved generic context assignments for initial Break working values. Do not repeat identical actor samples just to rediscover the absence. A known observable formula remains usable while that particular edge stays unidentified.
2. **Threshold/accumulator accounting:** identify precisely which hit portions contribute to Super Break when an action first breaks a target; verify accumulator reset, per-target grouping and multiple-source invocation. The shared consumer alone does not prove all producer behavior.
3. **Special toughness regimes:** toughness locks, secondary/exo/count-based bars, proportional reduction, alternate Super Break state eligibility and explicit caps require bounded source/model comparisons. None is silently declared non-battle or globally unsupported.
4. **State sampling and control:** exact snapshot updates, layer refresh, duration-driving action exceptions, freeze/recovery interaction, per-hit rounding and context visibility remain named questions. Use relevant descriptions and controlled published tests as well as new raw edges; native source is not the only permitted evidence.
5. **Application probability:** the shared Chance1.5 requests make general hit/RES/category resistance/immunity the next high-value dependency. **F05 is the next priority**, before returning to remaining F04/F06 specializations. This is a source-mechanism priority, not a backend task; F05 is not executed by this checkpoint.

The bounded shared-rule pass is delivered; F03/W06 are not globally mechanism_closed. Existing R2 and W-package history are preserved. This checkpoint adds this record and updates only the foundation roadmap/README navigation. No raw pin, runtime, lowering, IR, tests or CI change is required.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarBreakDamage.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Common_Ability.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json
[P1]: https://hsr.keqingmains.com/misc/beginner-guide/
[P2]: https://www.reddit.com/r/HonkaiStarRail/comments/1co5sqr/
[P3]: https://hsr.keqingmains.com/ruan-mei/
[P4]: https://mazimenigame.com/hsr-break-damage-calc/
[R2]: weakness_toughness_break_vertical_slice_v1.md
[F02]: general_damage_formula_and_input_layers_v1.md
[Burn]: guinaifen_burn_tick_detonation_source_chain_v1.md
