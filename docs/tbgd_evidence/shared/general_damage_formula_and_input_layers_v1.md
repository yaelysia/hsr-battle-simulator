# General damage: formula layers, shared inputs and applicability v1

## 1. Scope and result

Reviewed 2026-09-23. Evidence parent: `2100d31cbfb3425907ccacfedb564265f764768c`. TBGD is fixed to `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains Draft and documentation/evidence-only.

This is a mechanism-first W04 foundation, not another character study. It joins published ordinary-damage mathematics to shared constants, common monster state and previously audited input producers. The result is a reusable factor model, input-role map and exception register. It does not claim all damage families, exact rounding, every cap or the native evaluator body are recovered.

The ordinary formula below is accepted as an attributed gameplay model. Literal source claims are `manually_confirmed`; their specified source/model correspondences are reconciled interpretations. A model can be useful without being native source code. No backend code was inspected or changed in this checkpoint, no game/simulator/Direct/test was run, and no local-runtime E is claimed.

For the covered formula questions, this record supersedes R1's historical prohibition on using public models and its blanket statement that all final damage arithmetic remains unknown. [R1]'s exact occurrences, omissions, field identities and unresolved special cases are preserved, not rewritten. W04 remains active.

## 2. Evidence register and source quality

### Public mathematics and explanations

All resources below were read on 2026-09-23. Retrieval date is not a game-version label.

| Ref | Source | Use and limit |
| --- | --- | --- |
| P1 | [arkkus, Star Rail Damage Calculation][P1] | Original author report with equations and worked gameplay comparisons. Its conclusion anticipates the 1.0 release: historical evidence, not a current-patch certification. The introductory factorization is not copied literally; it places DMG% inconsistently across displayed formulas. The worked examples and later sources distinguish its application once. |
| P2 | [KQM SRL, Damage Formula][P2] | Separates base, crit, damage bonus, DEF, RES, damage taken and toughness. The page explicitly remains under construction and cites P1. Its DEF section is the unmodified standard-enemy simplification. Its Evidence Vault link is not an additional experiment. |
| P3 | [KQM Pela guide][P3], Version 2.0 | Authored explanation explicitly combines DEF reduction and DEF ignore additively and explains saturation when DEF reaches zero. Used only for this general interaction, not a new Pela audit. |
| P4 | [KQM Fu Xuan guide][P4], Version 1.3, incoming-damage explanation | Independently articulated defender-DEF/attacker-level equation; also distinguishes damage distribution before recipient-specific mitigation. Distribution is an exception boundary here, not a newly traced kit. |
| P5 | [Prydwen damage formula][P5] | Read as a comparison. It also credits P1 and reproduces its examples; P1/P2/P5 are not three independent experimental confirmations. Its ordinary RES-cap summary is retained only as a published claim, not substituted for the pin. |

P1's reported non-critical comparisons include an unbroken/broken pair near 312/346 damage with other inputs held fixed. They support the ordinary toughness factor. We inspected the written report, not a new game session or frame-by-frame video. This is distinct from the synthetic arithmetic in section 7.

Do not import the Genshin TCL's level+100 DEF formula or piecewise negative-RES formula into HSR. Matching site branding is not game identity. Public summaries may simplify, share ancestry or omit exceptions; their applicable mathematics can still be adopted without declaring every nearby sentence universal.

### Newly re-read shared TBGD sources

Paths are relative to the fixed upstream repository. Source identity is path + full revision + blob + the named occurrence.

| Ref | Path / selected surface | Complete blob |
| --- | --- | --- |
| S1 | [Config/GlobalConfig/GameCoreConstValue.json][S1], first 45 lines: damage/DEF/RES/reduction constants | `47ed0e027c76df398cf6e13de104933299ec1700` |
| S2 | [Config/ConfigAbility/Monster/Monster_Common_Ability.json][S2], first ability `Monster_Common_PassiveSkill_StanceBreak_Action`, its OnStart and Local_ListenStanceBreak | `fa02f6ab070fb8da16ebd2f5976503446d633e0e` |
| S3 | [Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json][S3], `ModifierMap.MonsterAllDamageReduce` and `ModifierMap.StanceBreakState` | `2db782ddc81b7a1328e4086dc71c8a23295b06a8` |
| S4 | [Config/GlobalConfig/DamageBehaviorTemplateListConfig.json][S4], complete ConfigList | `cee384c25587819c64b36dfe1b485ff0e797ada3` |

Reused source chains, not new actor investigations: [R1] damage request/DEF/RES/crit-context distinctions; [R2] concrete weakness/resistance and ordinary owner -> common break passive; [R8] set102's conditional normal-hit damage bonus; [Burn] ordinary DoT versus vulnerability; [W17] shared fatigue and the ordinary DirectlyLoseHp owner. Reuse preserves each record's exact scope and does not promote an untraced sibling.

## 3. Ordinary factor model

For an ordinary property-scaled damage instance to which these factors apply:

```text
D = B * C * G * F * R * V * U * W

B = base damage
C = applicable critical-hit multiplier
G = applicable outgoing damage-bonus multiplier
F = defender-DEF mitigation
R = damage-type resistance/penetration multiplier
V = applicable damage-taken / vulnerability multiplier
U = independent damage-reduction product, including the ordinary toughness term once
W = applicable outgoing Weaken factor; 1 when absent
```

This factorization synthesizes P1/P2 with P3/P4's specific explanations. It is an evaluation model, not the temporal order of native callbacks. Multiplication order alone cannot determine when a new buff becomes visible to a hit, when targets are selected, or how intermediate rounding works.

An effect's identity and conditions select its factors. Damage element, attack category, actual damage owner, recipient, current state and explicit behavior override are inputs, not conclusions obtained from the final number.

### 3.1 Base and crit

For a supported single-property base-damage family:

```text
B = (p + delta_p) * S + f
C = 1 + c_damage for a critical hit; 1 for a non-critical hit
```

`S` is the stat of the appropriate damage source; `p` is the authored coefficient; `delta_p` is a confirmed addition to that coefficient; `f` is a confirmed additive base-damage term. Multiple-property and special base formulas require their own authored expression, not forced conversion to ATK scaling. R1's explicit ByDefence occurrence disproves choosing S from the spelling of DamageByAttackProperty alone.

For expected damage with all other factors fixed, the ordinary crit expectation is `1 + clamp(c_rate,0,1)*c_damage` [P2]. It is not the multiplier of every individual hit. Crit eligibility, forced crit/non-crit and special damage classes remain separate from this arithmetic. An omitted crit field is not an explicit false flag; this document does not decree that every DoT in every version can or cannot crit.

### 3.2 Outgoing bonus and incoming vulnerability

```text
G = 1 + sum(applicable outgoing damage-bonus contributions)
V = 1 + sum(applicable damage-taken contributions)
```

These are distinct buckets [P2]. Elemental, all-type and category-specific contributions enter only when their conditions match. A Normal-only bonus is not automatically a DoT bonus; a DoT-only vulnerability is not a direct-hit vulnerability.

Adding a coefficient, increasing a scaling stat, adding G and adding V are four different operations. A translated phrase such as "damage increased" needs its linked description, operation and property destination before assigning a bucket. An installed status and a per-hit context mutation can contribute to the same conceptual bucket without being the same storage object.

### 3.3 General DEF equation and its limited simplification

Let `La` be the damage attacker's level and `De` the applicable effective defender DEF, with `De >= 0`:

```text
K = 200 + 10*La
F = K / (De + K)
```

P4 supplies the general equation. S1 literally contains `DefenceAdd.Value=200` and `DefenceMultipe.Value=10`; retain the misspelling. Their agreement is a strong source/model correspondence, not a recovered native call site. The defender is not necessarily an enemy, and the attacker is not necessarily a playable avatar.

For the ordinary no-flat/no-extra-DEF-buff case with base defender DEF `D0`, reduction `r` and applicable ignore `i`:

```text
De = max(0, D0 * (1-r-i))
```

The rates combine additively in this setting, not as `(1-r)*(1-i)` [P3]. Reduction is typically target-side and ignore can be attacker/hit-specific; matching algebra does not make their owners or lifetimes identical. Do not apply either rate twice to an already-adjusted DEF value.

Only if the selected defender's base really satisfies `D0=10*Ld+200`, with no extra flat/ratio context, may this simplify to:

```text
F = (La+20) / ((Ld+20)*max(0,1-r-i) + La+20)
```

At equal levels with no reduction/ignore, that special case is 0.5. With effective DEF zero, F is 1. The algebra does not authorize replacing every monster template/HardLevel/phase/elite construction with that standard base, nor using the simplified formula against an arbitrary built ally. Final monster-stat construction remains a separate input problem.

### 3.4 Resistance is separate from DEF, weakness and effect resistance

Within the ordinary supported resistance range:

```text
r_effective = applicable damage resistance after reductions and penetration
R = 1 - r_effective
```

For example, 20% damage resistance with 10 percentage points of penetration gives R=0.9, not `0.8*1.1` [P1/P2]. Damage-type and all-type terms must match the incoming damage's category and actual target.

R2 already distinguishes `StanceWeakList`, typed `DamageTypeResistance`, and `DebuffResist`; they are not interchangeable quantities. Do not infer all resistance values from weakness membership, confuse status hit resistance with this R factor, or automatically make a weakness implant a resistance reduction. Specific effects can author both changes, requiring both edges.

### 3.5 Reduction, toughness and Weaken

The ordinary independent-reduction model is:

```text
U = product(1-u_j)
W = 1-w for an applicable Weaken contribution
```

P1 supplies this ordinary model. Same-status stacking/aggregation still determines which independent contributions actually exist. The fact that independent reductions multiply does not prove every repeated application is a new independent term.

For the common monster break-passive family in section 4, one U term is 0.9 while unbroken and 1 while broken. A display or formula may name it a separate toughness factor T. Either representation is valid, but use it exactly once: `U=T*U_other`, never a 0.9 toughness multiplier on top of an U already containing that same reduction.

The multiplier is not the fraction of the toughness bar remaining. Neither this model nor the shared state writes imply that half a bar grants half of the 10% reduction. Special toughness regimes are not generalized from the common family.

## 4. Closed shared-state chain: why the ordinary toughness factor changes

R2 supplies concrete Monster1002011 -> ConfigCharacter PassiveSkill05 -> common ability reachability. Re-reading S2/S3 closes the shared operation chain:

```text
Monster_Common_PassiveSkill_StanceBreak_Action.OnStart[2]
  -> AddModifier(Caster, MonsterAllDamageReduce)
MonsterAllDamageReduce.OnStack
  -> StackProperty(ModifierOwnerEntity, AllDamageReduce, fixed 0.1)

Local_ListenStanceBreak.OnBeingBreak
  -> AddModifier(holder, StanceBreakState)
  -> RemoveModifier(holder, MonsterAllDamageReduce)

StanceBreakState.OnEndBreak -> RemoveSelfModifier
StanceBreakState.OnDestroy.CallbackConfig[3]
  -> AddModifier(holder, MonsterAllDamageReduce)
```

The published 0.9/1 behavior is therefore paired with explicit installation, property value, break removal and recovery restoration; it is not inferred from the word Stance. This is reusable for consumers of that shared passive, not an assertion that every possible entity has that passive.

This also identifies a discriminating boundary: the exact hit that crosses the break threshold requires damage/toughness settlement timing. Before/after-state factors do not by themselves decide that transition hit. No universal dispatcher is invented to answer it.

## 5. Reusable input-role map

Entries marked reused point to an already audited producer/binding/consumer, not a newly surveyed full character or equipment family.

| Conceptual input | Evidence-backed surface | Meaning / non-equivalence |
| --- | --- | --- |
| Scaling family and coefficient | R1 AttackData.FormulaType / DamagePercentage with typed SkillParam reads; Burn's linked skill description | Coefficient and selected source stat, not final damage. No universal default filled into omitted JSON. |
| Additive base channel | R1 request-shape inventory; P2 base equation | Classify the particular operand before treating a field as base-flat; special formula modes may differ. |
| Crit chance versus crit amount | R8 LC20000 CriticalChanceBase; R1 Attacker_CriticalDamage | Probability versus multiplier input; neither is an ordinary G contribution. |
| Outgoing conditional G | R8 set102 OnBeforeHitAll Normal predicate -> ModifyDamageData.Attacker_AllDamageTypeAddedRatio | Condition-scoped hit input, not permanent ATK or an unconditional all-category bonus. |
| Target vulnerability V | R1 Defender_AllDamageTypeTakenRatio; Burn Oil_Sub -> StackProperty(AllDamageTypeTakenRatio) | Context storage versus status property storage; same conceptual damage-taken role does not prove same-hit visibility. |
| DEF parameters | S1 DefenceAdd/DefenceMultipe; R1 Defender_DefenceAddedRatio surface | Constants reconcile with P4; the R1 literal field is not renamed to an invented generic ignore opcode. |
| Damage resistance | R1 AllDamageTypeResistance contribution; R2 typed concrete resistance rows | Target resistance differs from status resistance and weakness membership. |
| Ordinary toughness reduction | S2/S3 MonsterAllDamageReduce -> AllDamageReduce=0.1 | Shared state-conditioned reduction; do not double-count as T and U. |
| Weaken | W17's owner-backed MCommon_FatigueRatio surface; P1 ordinary model | Distinct outgoing-weakening channel. No universal stacking/cap inference from the property name. |
| Damage behavior override | S4 ConfigList, with W17's ordinary Sam reachability | Route/interaction control, not automatically a new numeric multiplier. |

This map does not make every similarly named sibling canonical. It supplies reusable destinations and classification questions for future source entries.

## 6. Applicability, bounds and unresolved discriminators

### Damage kinds must be dispatched before reusing the equation

Ordinary property-scaled direct damage and ordinary skill DoT can reuse relevant parts of this model. Break damage and Super Break have different base producers and eligibility rules; reuse their relevant mitigation factors only after checking the family. Direct HP loss, damage sharing, fixed/pure modes and extra damage events are not silently identical to an ordinary hit.

S4 provides explicit distinctions:

- `DirectlyLoseHp` has `MuteShield=true`, `MuteSplitHp=true`, `OnlyIsIndirectAttack=true` and `OnlyIsNotHit=true`.
- `DirectlyLoseHpHit` also has MuteShield/MuteSplitHp but a different blocking-related flag set.
- `TrueDamage` in this file has MuteSplitHp and MuteDamageBlockExcludeDot; it does **not** serialize a universal numeric DEF/RES-bypass equation.

These are literal interaction flags. Do not define all mechanics named true damage in later versions from this template name. W17's ordinary DamageBehavior=1 -> DirectlyLoseHp mapping is reused; no new enum decoder is invented.

### Bounds are individually tracked, not used to erase the ordinary formula

| S1 literal | Published comparison | Current disposition |
| --- | --- | --- |
| DamageTakenRatioMax=3.5 | P1 describes a damage-taken ceiling | Compatible candidate for the boundary, but exact internal quantity/clamp placement is not traced here. V equations/examples below stay away from the ceiling. |
| AllDamageReduceMax=0.99 | P1 describes a residual multiplier floor | Compatible bound pair; exact aggregation/clamp stage remains separate. Independent interior-range reduction behavior is retained. |
| OverallResistanceMin=-1, OverallResistanceMax=2 | P1/P5 summarize effective resistance limits as -100%/90% | Not a matched upper-bound encoding. Do not replace the raw 2 with 0.9, or claim the two names necessarily address the same intermediate quantity. Exact bound correspondence is open. |
| DamageRandomMin=1, DamageRandomMax=1 | Ordinary deterministic base examples | Fixed raw endpoints; not proof that crit, target selection or callbacks consume no RNG. No generic stream algorithm is recovered. |

Other precise questions: flat/mixed-scaling special channels; conditional crit overrides; threshold-crossing hit timing; per-hit and aggregate rounding; snapshot/live input refresh; exceptional mitigation modes; exact cap behavior at extremes. Resolve them with linked descriptions, pertinent public tests and source discriminators. Absence of native code is not a prerequisite for leaving them open or for later resolving their observable behavior.

## 7. Character-independent arithmetic discriminators

These are synthetic predictions, not observed combat and not a simulator test. Choose ordinary eligible factors below boundary caps:

```text
B=2000; C=1; G=1.5; F=0.5; R=0.8; V=1.2;
T=0.9; U_other=1; W=1.
Baseline D = 1296.
```

| Single controlled change | Predicted D | What it distinguishes |
| --- | ---: | --- |
| Add 0.2 to applicable G | 1468.8 | G becomes 1.7; not a new independent x1.2. |
| Instead add 0.2 to applicable V | 1512 | V becomes 1.4; G and V are separate buckets. |
| Remove the common unbroken reduction, T=1 | 1440 | Broken-state factor applied once; transition-hit timing not tested. |
| For the equal-level standard DEF case, r=0.4 and i=0.1 | 1728 | F becomes 2/3 because the combined reduction is 0.5. |
| A critical hit with c_damage=1, all other inputs fixed | 2592 | Per-hit crit factor 2, not an averaged crit probability. |
| Add two independent reductions 0.2 and 0.1 to U_other | 933.12 | Additional factor 0.8*0.9=0.72, not 0.70. |

A future measured comparison should hold the other factors, owners, level context, conditions and rounding visibility fixed. Matching one displayed number is not unique identification of every factor or event order.

## 8. Knowledge gained and continuation

The new result is the general layer model and its source-role map, not more character coverage. Supported ordinary rules include additive applicable G and V in separate buckets, general defender-DEF/attacker-level mitigation, additive reduction/ignore in the stated case, linear ordinary RES behavior, independent reduction products, and the explicit shared break-state reduction lifecycle.

The [foundation-first roadmap][ROADMAP] is the current research sequence. Complete reusable rule families and their named exceptions before expanding full actor kits. Existing character/monster/equipment records remain validation anchors.

Current claim accounting: raw constants/common state/behavior flags are manually confirmed; public mathematics remains attributed; the combined source/model explanation is positive evidence; literal code absence and unresolved boundary quantities remain separate. No new local C/D/E claim, backend repair task, broad source-family promotion or whole W04 closure is created.

Document verification: exact-pin file/blob and selected occurrence review, cited-public-text comparison, algebraic consistency review and final Git scope/head checks. No automated numeric test, video audit or runtime/CI success is claimed.

[P1]: https://docs.google.com/document/d/e/2PACX-1vQ9M7q5jLz9DKkTRlsGiB8RGYyPQyhShbuTbrVPQ7-Ke4_U787MfWzr2NjY-KrQo5Ota4Lj3JrFyge9/pub
[P2]: https://srl.keqingmains.com/combat-mechanics/damage/damage-formula
[P3]: https://hsr.keqingmains.com/pela/
[P4]: https://hsr.keqingmains.com/fu-xuan/
[P5]: https://www.prydwen.gg/star-rail/guides/damage-formula
[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConstValue.json#L1-L45
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_Common_Ability.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/DamageBehaviorTemplateListConfig.json
[R1]: ordinary_damage_vertical_slice_v1.md
[R2]: weakness_toughness_break_vertical_slice_v1.md
[R8]: battle_start_effect_activation_v1.md
[Burn]: guinaifen_burn_tick_detonation_source_chain_v1.md
[W17]: global_shared_reverse_scan.md
[ROADMAP]: foundational_mechanics_research_roadmap_v1.md
