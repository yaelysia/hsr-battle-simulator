# General effect application: chance, resistance, immunity and attempts v1

## 1. Scope and result

Reviewed 2026-09-24. Evidence parent: `d1ff8c9dd8df90eefd7134f7374b1faee78c5ace`. All raw claims use `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains Draft / documentation-evidence only.

This F05/W09/W12 foundation explains ordinary base-chance application, fixed-chance triggers, general versus category resistance, hard immunity and actual application attempts. The reusable object is an application with explicit source, recipient, conditions and probability class. Yanqing, Luocha and Lynx supply different discriminators, not whole-character investigations.

**Result:** an attributed probability equation and inverse threshold; separate probability and eligibility contracts; fixed-proc versus Freeze-task routing; a category-resistance contribution rather than general Effect RES; shared immunity maps and consumed protection; and conditional repeated-attempt mathematics. Native RNG/evaluator code and backend readiness are not prerequisites.

Literal operations/bindings are `manually_confirmed`. Source/description/public-model correspondences are reconciled interpretations. Calculation agreement is not an independent gameplay experiment. No game, simulator, Direct, tests or workflow was run; no local-runtime E is added. F05 and wider W packages remain active for the named residuals.

For covered probability questions, this record supersedes the older [RNG/callback record][RNG]'s native-evaluator-only stopping rule. Its raw observations and unresolved PRNG, priority and callback details remain intact.

## 2. Evidence register

### Pinned sources inspected

Paths are relative to the fixed upstream repository. Named selectors are occurrence identities, not invented numeric offsets.

| Ref | Path and selected surface | Complete blob |
| --- | --- | --- |
| S1 | [Config/GlobalConfig/GameCoreConstValue.json][S1]: immunity maps, AntiDebuffResist list, adjacent event-map predicates and declared status-property names | `47ed0e027c76df398cf6e13de104933299ec1700` |
| S2 | [Config/ConfigCharacter/Avatar/Avatar_Yanqing_00_Config.json][S2]: SkillP01 ability membership and selected typed/working reads | `3083cf719ed15fa56da368f6ae53f42f04459a79` |
| S3 | [Config/ConfigAbility/Avatar/Avatar_Yanqing_00_Ability.json][S3]: OnBeforeAttack/OnAfterAttack proc path and `Avatar_Yanqing_00_PassiveSkill01_InsertAbilityPhase02` | `9bb1bd578ccbe4bac5d42dc6463fe789f063020c` |
| S4 | [Config/ConfigCharacter/Avatar/Avatar_Luocha_00_Config.json][S4]: hash1153510288, SkillTreeParam(PointB3,0) | `877d23dae9a21378da0f3c852ccf1a89f1bf80ab` |
| S5 | [Config/ConfigAbility/Avatar/Avatar_Luocha_00_Ability.json][S5]: `Avatar_Luocha_SkillTree03` and local `M_Luocha_SkillTree03` | `d8408125209366c4f16dfba1fd264974aacd2764` |
| S6 | [Config/ConfigAbility/Avatar/Avatar_Lynx_00_Ability.json][S6]: Skill02 Rank02 installation, `MAvatar_Lynx_00_Rank02_Resist`, HPAddedRatio01/02 destruction hooks | `cb034c68b0e1d6bf3675a118e42a69b0550e0db4` |

[F03][BREAK] supplies already-audited shared elemental Chance1.5 requests and flags. [RNG] and [ordinary Burn][BURN] supply earlier distinctions among status requests, random traversal, RandomConfig selection and random values. Reuse is not a new corpus-wide discovery.

### Public semantic and mathematical evidence

Retrieved 2026-09-24. Guide versions are not the TBGD pin's release label. Only the stated sections are adopted.

| Ref | Source | Role and limit |
| --- | --- | --- |
| P1 | [HoYoLAB article25056652: Version2.0 Black Swan DoT DPS Guide][P1], base-chance/EHR section | Published four-factor equation and worked calculation, recovered in indexed article text. The live page did not expose a readable full body; author identity was not verified. Community publication on HoYoLAB is not an official developer formula declaration. |
| P2 | [KQM Pela guide][P2], Version2.0, EHR section | Single-hit threshold table with an additional in-battle EHR contribution already accounted for; calculation comparison, not a new game test. |
| P3 | [KQM Misha guide][P3], Version2.0, Freeze Probabilities | Conditional multi-attempt calculations with separate Effect RES and Freeze RES; first hit must reach the selected target. A small tabulation discrepancy is preserved in section8. |
| P4 | [KQM SRL Yanqing][P4]; [KQM Yanqing guide][P4b], Version1.6 | Reproduced talent text separates fixed follow-up probability from base-chance Freeze. Published levels are not substitutes for unread pinned skill rows. |
| P5 | [KQM SRL Luocha][P5], Through the Valley | Reproduced control-resistance wording. Published70% supplies the semantic example; no newly read pinned PointB3 numeric row is claimed. |
| P6 | [KQM SRL Lynx][P6], E2 | Reproduced one-debuff protection wording; corroborates immunity-event removal, not the order of immunity and resistance checks. |
| P7 | [Schism's Arqade explanation][P7], answered2024-02-10 | Authored fixed/base distinction, product and inverse equation. Its62% Yanqing example is labeled Lv10 unlike KQM's level table; that numeric example is not adopted. |

Descriptions identify declared mechanics; graphs identify operations and bindings; public equations supply observable arithmetic. Repeated publication and description/database agreement are not independent experimental replication.

An attempted same-pin ExtraEffectConfig/TextMap glossary join was not completed: the large TextMap read was empty or truncated through available transports. No unmatched hash is promoted to a base/fixed-chance definition, and no failed read is treated as missing game text. Descriptions used here are explicitly public reproductions, not a new same-pin localization extraction.

## 3. Four separate questions

| Question | Inputs | Not established by that question alone |
| --- | --- | --- |
| Is there an eligible request? | Trigger predicate, source/target validity, action gates, invocation | A random roll occurred or a status was installed |
| Which probability applies? | Base/fixed class, expression, source EHR, target general/category resistance, overrides | Immunity bypass, PRNG order or lifetime |
| Can the effect be admitted? | Behavior/status-type immunity and exceptions | Universal immunity-versus-probability chronology |
| What does admission change? | Instance identity, layers, replacement/refresh and lifecycle | One application roll per damage hit or per installed layer |

This is semantic decomposition, **not native execution chronology**. Consumption of one-use protection must be tied to its actual event, not an invented ordering of these four questions.

## 4. Ordinary base-chance model

For an eligible ordinary debuff attempt without an applicable immunity/bypass exception:

```text
b = authored base-chance input
h = effective Effect Hit Rate of the application source
r = effective general Effect RES of the recipient
d = effective matching debuff/category resistance of the recipient

p_base = clamp(b * (1+h) * (1-r) * (1-d), 0, 1)
```

P1/P7 state the product; P2/P3 provide discriminating calculations. The clamp expresses the final mathematical probability range, not recovered native clamp placement, floating-point representation, comparator or PRNG code. Use ordinary valid stat ranges; undocumented negative-stat and forced-status cases need separate contracts.

EHR increases base probability; it is not a standalone success chance. Neither `h-r` nor `r+d` replaces this product. A100% base request can fail. A base input above100% must not be clipped to1 before applying the other factors.

The EHR owner is the **application source**, obtained from the caller/context, not automatically the current turn actor, recipient or teammate causing an unrelated trigger. Concrete chains establish local roles; universal snapshot/caster-redirection behavior is not asserted.

S1 separately declares StatusProbability/StatusProbabilityBase/StatusProbabilityConvert and StatusResistance/StatusResistanceBase/StatusResistanceConvert. The names agree with established input families but do not recover all Base/Convert aggregation. F02/F03 damage resistance and weakness membership are different quantities, not this general Effect RES.

### 4.1 Inverse threshold and synthetic discriminators

For a desired probability and positive denominator:

```text
h_required = max(0, p_goal / (b * (1-r) * (1-d)) - 1)
```

A zero denominator cannot be overcome by finite EHR within this ordinary equation. Hard immunity is likewise not defeated merely by increasing the product; an explicit bypass would be a different contract.

The following deliberately chosen inputs are not a built character or measured fight:

| b | r | d | h | Probability |
| ---: | ---: | ---: | ---: | ---: |
| 1 | .4 | 0 | 0 | .60 |
| 1 | .4 | 0 | 2/3 | 1 |
| 1.5 | .4 | 0 | 0 | .90 |
| 1.5 | .4 | 0 | 1/9 | 1 |
| 1 | .4 | .5 | 0 | .30 |
| 1 | .4 | .5 | 7/3 | 1 |

Thus66.666...% is total EHR for `b=1,r=.4,d=0`, not a universal requirement. P2's lower displayed figure includes an extra in-battle10%; do not double-count it. No universal enemy40% Effect RES or enemy level-growth formula is established here.

With `b=1,h=0,r=.3,d=.7`, success probability is `.7*.3=.21`, not zero. General30% Effect RES plus70% control resistance does not create100% immunity. A non-control application need not use that category term at all.

### 4.2 F03's Chance1.5

F03's elemental installations supply1.5 separately from their status/control flags. This is a probability input, not150% final probability or guaranteed successful control after toughness breaks.

The `.90` example describes such an input **under the ordinary base-chance model**. It is not a newly measured Weakness Break rate or proof that every Break status has identical EHR/immunity/override handling. The general equation is accepted; a specific Break-only bypass remains an applicability question rather than making all probabilities unknown.

## 5. Fixed proc, random target and base-chance debuff in one chain

P4/P4b distinguish fixed follow-up probability from the subsequent base-chance Freeze. S2/S3 expose separate tasks and inputs:

```text
selected OnBeforeAttack listener
  -> ByAttackType(Caster,[Normal,BPSkill,Ultra])
  -> ByRandomChance
       Chance=AQABAQIR/[-247205968,-374893293]
  -> AddModifier(SkillTargetEntityList,BonusTargetMark)

selected OnAfterAttack listener
  -> Retarget(AllEnemy,predicate=has BonusTargetMark,
              ByRandom=true,MaxNumber=1)
  -> TurnInsertAbility(...PassiveSkill01_InsertAbility)
  -> TriggerAbility(...PassiveSkill01_InsertAbilityPhase02,
                    AbilityInherentTargetType=AbilityTargetEntity)

InsertAbilityPhase02.OnStart
  [1] damage, HitSplitRatio=.3, AttackType=Insert
  [3] damage, HitSplitRatio=.7, AttackType=Insert
  [4] DamagePerformFinish
  [5] AddModifier(AbilityTargetEntity,MCommon_CTRL_Frozen,
                  Chance=AQAR/[-285097779],LifeTime=1)
```

S2 binds `-247205968` to SkillParam(SkillP01,2), and `-285097779` to SkillParam(SkillP01,5). The additional proc operand `-374893293` is Type=None, not an EHR field; its effective value is not assumed zero. No pinned level row or complete proc-adjustment initialization is newly materialized.

For the fixed gate, the ordinary meaning is `p_fixed=f`, without the EHR/Effect RES/category-resistance product. Its branch still depends on trigger conditions and successfully reaching the inserted action. Fixed probability does not ignore death, control, target validity or a downstream immunity check. ByRandomChance is not proof of every forced-debuff override.

The reusable negative discriminator is **two damage operations but one explicit Freeze request** in this inserted body. Do not roll Freeze twice because the damage splits. The separate traversal chooses among marked targets, not status-resistance outcomes.

If a proc has probability f and its single eligible Freeze would land with probability p, an otherwise uninterrupted two-step example has total Freeze probability `f*p`. This is conditional probability composition, not native draw-count evidence. Published60%/65% illustrates the two roles, not a newly verified pinned level tuple.

## 6. General resistance versus category resistance

S4/S5 give this contribution chain:

```text
hash1153510288 = SkillTreeParam(PointB3,0)
 -> Avatar_Luocha_SkillTree03.OnStart[0]
    AddModifier(Caster,M_Luocha_SkillTree03,
       MDF_Resistance=read1153510288)
 -> local modifier.OnStack
    StackStatusResistance(Caster,BehaviorFlag=STAT_CTRL,
                          Resistance=read741349151)
```

Destination working hash741349151 is Type=None. P5's70% control-resistance wording explains the role. This is not `StackProperty(StatusResistanceBase,.7)`. The binding and consumer are audited; the70% is public wording, not a newly extracted pinned trace row.

In contrast, S3's selected PointB2-gated listener writes StatusResistanceBase, which P4 describes as general Effect RES. S6 similarly has a general StatusResistanceBase write in HPAddedRatio02, separate from its Rank02 immunity state. Different operations must not be collapsed into one stat.

Match an applicable category contribution once. Freeze can carry both STAT_CTRL and STAT_CTRL_Frozen; that alone does not justify applying the same control resistance twice. Overlapping category entries, exclusions and multiple matching contributions need an explicit aggregation rule, not an invented product per flag.

## 7. Hard immunity and consumed protection

### 7.1 Exact shared mappings

| S1 map / key | Exact matching payload |
| --- | --- |
| ModifierBehaviorFlagImmuneMap.Endurance, EnduranceLogicOnly, EnduranceEnemyOnly, EnduranceEnemyLogicOnly, STAT_ForceActionable | BehaviorFlags=[STAT_CTRL] |
| ModifierBehaviorFlagImmuneMap.ImmuneDot | BehaviorFlags=[STAT_DOT] |
| ModifierBehaviorFlagImmuneMap.MuteAttachWeakness | BehaviorFlags=[STAT_AttachWeakness] |
| ModifierBehaviorFlagImmuneMap.STAT_ImmuneKnowledge | BehaviorFlags=[STAT_Knowledge] |
| ModifierStatusTypeImmuneMap.Dodge or ImmuneDebuff | StatusTypes=[Debuff] |
| ModifierStatusTypeImmuneMap.STAT_ResistAll | StatusTypes=[Debuff,Buff,Other] |

These are categories, not additions to numerical Effect RES. Definition presence does not mean every unit has the capability: each occurrence needs its actual owner/installer. Do not infer full Dodge or enemy-only variant semantics from names.

`ModifierBehaviorFlagAntiDebuffResistList` maps key AntiDebuffResist_CTRL to STAT_CTRL/STAT_CTRL_Frozen/STAT_Confine; native numerical behavior remains unspecified. Nearby event-map entries500/501 issue control-focused DispelStatus with OnlyCanDispel=false, guarded by exclusion of STAT_ForceControl;501 adds an enemy-relation predicate. These are real exception/cleanup surfaces, not a complete forced-status precedence table or a reason to call immunity unconditional in every mode.

### 7.2 An ordinary one-use consumer

S6 and P6 connect the shared ImmuneDebuff classification to installed protection:

```text
Avatar_Lynx_00_Skill02_Phase02
 -> ByRankActivated(TriggerKey.Hash=523552506)
 -> AddModifier(AbilityTargetEntity,MAvatar_Lynx_00_Rank02_Resist)

GlobalModifiers.MAvatar_Lynx_00_Rank02_Resist
  BehaviorFlagList=[ImmuneDebuff]
  OnImmuneDebuff:
    TriggerEffect(...DispelDebuff.prefab) // visual, not DispelStatus
    RemoveModifier(holder,this named state)

HPAddedRatio01 / HPAddedRatio02.OnDestroy
 -> RemoveModifier(holder,MAvatar_Lynx_00_Rank02_Resist)
```

One-debuff protection is explained by immunity-event removal and parent cleanup. No literal Count=1 is fabricated; consumption is authored as removal. The visual asset name does not prove a debuff was first admitted and then cleansed.

This is immunity with consumption, not100% general Effect RES. Whether a would-have-resisted attempt consumes it, how simultaneous applications arbitrate it and how protections overlap remain specific ordering questions. Those do not erase the established basic protection mechanism.

## 8. Multiple attempts: count requests, then calculate

For a specified sequence whose conditions justify the ordinary independent-trial model:

```text
P(at least one success) = 1 - product(1-p_i)
identical p and n attempts: 1 - (1-p)^n
```

Random target selection, early-success stopping, changing resistance, existing-status gates and consumed immunity can change that sequence. Writing the equation does not recover native RNG independence, streams or draw order.

P3 provides a calculation discriminator: first base chance1, four later base chances.2, EHR.6, Effect RES.4. With no Freeze RES, probabilities are.96 and.192; `1-.04*.808^4` rounds to98.3%, matching the guide. With Freeze RES.5, probabilities are.48 and.096; `1-.52*.904^4` gives about65.27%, while the guide prints65.2%. **Preserve that small tabulation/rounding discrepancy; do not claim exact reproduction of the second entry or recovery of game rounding.** Neither calculation is measured gameplay or a new Misha source trace.

S3's two-hit/one-request example must not receive n=2 for its single Freeze attempt. A single installation that adds several layers likewise does not prove one probability roll per layer. Count actual requests and gating, not animation hits or displayed stack count.

## 9. Reusable facts and precise residuals

An application record should retain: source occurrence/environment; declared probability class and expression; recipient selector; effect labels; EHR/general/category inputs; immunity/override conditions; actual attempt sites and gates; and separately the resulting instance/layer/lifetime behavior. This is evidence for later use, not an IR redesign.

| Claim | Accepted evidence | Remaining boundary |
| --- | --- | --- |
| Ordinary probability product and inverse threshold | Attributed model, published numerical checks, source input roles | Native evaluator/clamp code and special overrides |
| Fixed proc versus base debuff and traversal | Text plus S2/S3 distinct tasks/bindings | Proc working-value initialization; no universal defaults |
| General Effect RES versus control resistance | S4/S5 StackStatusResistance versus general property writes | Overlapping categories and override algebra |
| Hard immunity and one-use consumption | S1 maps plus S6 installation/removal/cleanup | Immunity-versus-roll order and concurrent consumption |
| Repeated-attempt mathematics | Conditional probability derivation and P3 comparison, including discrepancy | Per-mechanism attempt allocation and state changes |
| Full research or runtime completion | Not claimed | W09/W12/F05 remain active; no runtime E |

Residuals are bounded: category aggregation and anti-resistance/force overrides; attempt-local source/snapshot selection; elemental Break probability exceptions; immunity-charge arbitration; explicit fixed-chance debuff bypasses; and state-dependent/multiple-source attempt sequences. Descriptions, original tests and new source edges can resolve these. No local handler repair or PRNG recovery is required first.

**Next foundation: F06 modifier instances and lifetime.** Follow successful admission into caster/holder identity, stacks, replacement/refresh, duration-driving events, periodic versus extra activation and removal/rollback. Reuse existing shared lifecycle records; do not fill the three sample characters' remaining kits. F06 is not executed here.

## 10. Publication and verification

This checkpoint adds this record and updates roadmap/README. Older raw records, broad W checklists, inventory and pin are preserved. No whole-package percentage or implementation requirement is introduced.

Validation is actual source/public-text inspection, expression/selector comparison, algebraic review and documentation/Git diff/head review. No new gameplay experiment or software test is represented as performed. Published calculations are not promoted to observations, and a tabulation discrepancy is not suppressed. The checkpoint comment records the actual final commit and changed paths.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConstValue.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Yanqing_00_Config.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Yanqing_00_Ability.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Luocha_00_Config.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Luocha_00_Ability.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Lynx_00_Ability.json
[P1]: https://www.hoyolab.com/article/25056652
[P2]: https://hsr.keqingmains.com/pela/
[P3]: https://hsr.keqingmains.com/misha/
[P4]: https://srl.keqingmains.com/characters/ice/yanqing
[P4b]: https://hsr.keqingmains.com/yanqing/
[P5]: https://srl.keqingmains.com/characters/imaginary/luocha
[P6]: https://srl.keqingmains.com/characters/quantum/lynx
[P7]: https://gaming.stackexchange.com/questions/402781/what-is-effect-hit-rate
[RNG]: ordinary_rng_callback_reference_chains.md
[BREAK]: general_weakness_toughness_break_super_break_v1.md
[BURN]: guinaifen_burn_tick_detonation_source_chain_v1.md
