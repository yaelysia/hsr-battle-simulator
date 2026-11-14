# General timing: Speed, Action Value, action categories and clocks v1

## 1. Scope and result

Reviewed 2026-09-24. Evidence parent: `96896f677eaf14eaaa0b7692289801f69b4fcb8c`; latest preceding checkpoint: `5806243144` (F06). Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains open/Draft and documentation/evidence-only.

F08 supplies an attributed ordinary Speed/Action Value model, concrete source mappings for speed mutation, normalized advance and absolute zeroing, and an action/clock distinction usable across actors. The unit of research is the mechanism. Asta, a relic set and Bronya are discriminators, not new whole-kit audits; previously established OneMore, inserted-action and modifier-lifecycle evidence is reused.

**Result:** ordinary time progression, remaining-AV rescaling, full-gauge advance/delay, normal versus extra/inserted actions, and clock ownership can be explained without recovering the native scheduler. Exact source operations remain distinct even when two operations happen to produce the same ordinary visible result. F08/W07/W10 remain active for the named exceptional ordering, unit-transport and lifecycle questions.

For the claims covered here, this record supersedes the old [timeline record][TIMELINE] and W07's blanket native-body-only restriction on adopting public timing mathematics. It does not erase their source distinctions or claim those native bodies were recovered. No backend inspection, modification, game session, simulator, Direct, test suite or workflow execution was performed. No local-runtime E is added.

## 2. Source and interpretation register

### Newly inspected pinned sources

Paths are relative to TBGD at the fixed revision. Named selectors refer to serialized objects, not guessed numerical array offsets.

| Ref | Path and inspected identity | Complete blob |
| --- | --- | --- |
| S1 | [Asta CharacterConfig][S1], Skill03 entry/membership and `SkillParam(Skill03,0/1)` | `147dfdfb5b6170e0371bc0a105d5342868e8f025` |
| S2 | [Asta Ability][S2], Skill03 Phase01/02, local Ultra_SpeedUP, separate preshow modifier | `b2a03d625fe8628eb927bd198d4108e5f7ba70b7` |
| S3 | [RelicSetSkillConfig][S3], `SetID=110,RequireNum=4` | `a8022b783c42d05f6cb168010ecbcfa90b69182d` |
| S4 | [Equip/RelicAbility][S4], Ability51101, MRelic_110_Main and typed SkillRelic environment | `b9b9573f0ba69a6c332eeeebb9b587f3dfa99c01` |
| S4b | [root RelicAbility sibling][S4b], same named ability with different serialized environment/expression | `f00dd3e79c43daa543c7a91894b55fda126bce32` |
| S5 | [Bronya CharacterConfig][S5], Skill02 FriendSelect and EntryAbility | `5139365b381cfc319c77093af0ae2a6ba9d6a036` |
| S6 | [Bronya Ability][S6], Skill02 Phase01 branch and Others_Phase02 absolute zero write | `78d897f4601e4fa13083a9edbb196faf2e6c5394` |
| S7 | [GameCoreConstValue][S7], SpeedToDelayDistance | `47ed0e027c76df398cf6e13de104933299ec1700` |

Replay ranges: S1 lines175-390; S2 lines790-1120 and1400-1750; S3 lines300-332; S4 lines890-1060; S4b lines820-1020; S5 lines1-225; S6 lines244-665; S7 lines250-280. Full blob identity and named occurrences are authoritative if display line layout differs.

[The old timeline record][TIMELINE] supplies previously audited Gepard/Claymore OneMore, Hanya conversion, Seele current-cost/insertion and Aglaea coordinated-entry distinctions. [F03][BREAK] supplies shared break/control operations; [F05][APPLICATION] supplies the distinction between damage hits and effect requests; [F06][MODIFIERS] supplies clocks, first-step examples and parent/child cleanup. These are explicitly reused rather than newly re-audited in full.

### Public semantic evidence

All pages were consulted on 2026-09-24. Retrieval date is not a patch label. These authored explanations and reproduced skill descriptions are not new measurements.

| Ref | Source | Accepted role and limit |
| --- | --- | --- |
| P1 | [KQM Speed guide][P1], credited multi-author guide with launch-context discussion | Ordinary gauge mathematics and off-order Ultimate behavior; no adoption of its gearing advice, a universal insertion order or every casual damage-category label. |
| P2 | [KQM SRL Turn Order Mechanics][P2] | Speed composition, gauge/AV relations and an attributed initial-deployment tie model. Its sorting explanation is not recovered native code. |
| P3 | [KQM Asta guide][P3], Ultimate section | Flat-speed interpretation and the stated application-turn duration exception. Numeric level rows are not newly extracted from the pin here. |
| P4 | [KQM SRL relic descriptions][P4], Eagle of Twilight Line | Four-piece effect explains the selected exact 0.25 as post-Ultimate action advance. |
| P5 | [KQM SRL Bronya description][P5], Skill | Immediate allied action with a self-target exception; read alongside the literal turn-action predicate, not as a replacement for it. |
| P6 | [KQM Seele guide][P6], Version1.6, Talent and team discussion | Resurgence's extra action, retained ordinary buffs, and its separately granted buff state; not a universal rule for all extra-action protocols. |

P1/P2 are related KQM publications, not two independent controlled experiments. Public text and the pinned data can support a reconciled model while exact same-pin localization hashes remain unjoined. No video was newly inspected, no live combat reproduced and no public coefficient substituted for an unread pinned skill row.

## 3. Coordinates: effective Speed, remaining distance and remaining AV

Use the public ordinary model for eligible entities with positive effective Speed, outside explicit timing locks/overrides. Let s be current effective Speed, G the remaining normalized action distance, and r the remaining Action Value:

```text
G0 = 10000                       public normalization for a full interval
r = G / s
r_base = 10000 / s
ordinary s = s_base * (1 + sum(applicable percentage contributions))
             + sum(applicable flat contributions)
```

Percentage Speed and flat Speed are different inputs [P2]. The simple composition does not subsume conversion-based contributions, hard setters, clamped/locked Speed or every secondary entity. An already effective Speed value must not receive its modifiers a second time.

At fixed speeds, elapsed shared battle AV t reduces each eligible waiting entity's G by s*t. Thus, with no ready inserted work or intervening event, advancing to the next normal event can be represented by the smallest remaining r, subtracting that same elapsed AV from the other waiting entries. This is a mathematical event-step representation, not evidence that GameCore literally loops over integer AV ticks or uses a particular queue container.

Normal-slot renewal is associated with the applicable normal-turn completion. Do not blindly apply a fresh G0 after every ability, damage operation, Ultimate or follow-up. Initial deployment, entry effects and subsequent slot renewal are separate contexts; G0 does not bypass an authored battle-start advance or special initial position.

### Raw 1000 is not silently changed into public 10000

S7 literally has `SpeedToDelayDistance.Value=1000`. The public model uses 10000. This task has not located a native conversion/getter connecting that constant to displayed AV. Preserve both facts; neither rename the raw value to10000 nor invent a factor-of-ten native conversion. The useful observable model does not depend on claiming that its chosen distance unit is the engine's storage unit.

Display rounding is also a different layer from the value used for ordering. P1 describes upward rounding of visible AV; that does not justify running the timing model on rounded display integers. Exact internal precision and boundary equality remain separately testable questions.

## 4. Changing Speed is not advancing a percentage of the remaining timer

For a speed-only change with unchanged remaining G, algebra gives:

```text
r_new = r_old * s_old / s_new
```

The change preserves progress already made along the current interval; it does not reset the entity to `10000/s_new`. When remaining distance is small, a speed gain produces a smaller immediate AV reduction. After removal of a speed buff, the same relation applies to the then-current remaining distance, not to a saved old timer.

For one ordinary normalized advance a and delay d, expressed as fractions of a full interval:

```text
G_new = max(0, G_old - 10000*a + 10000*d)
r_new = G_new / s_new
```

With no intervening event, G_old may be reconstructed as `r_old*s_old`. An advance of25% at Speed100 deducts25 AV, even when only40 AV remain; the resulting15 is not `40*.75=30`. The public full-distance rule [P1/P2] and this calculation distinguish advance from proportional reduction of the remaining timer.

The lower bound is part of the adopted ordinary observable model, not recovered native clamp code. Sequential operations cannot always be collapsed into one net amount: under this model, G1000 followed by20% advance and then20% delay becomes0 and then2000. Netting the two changes before clamping instead leaves1000. This is an algebraic discriminator for a specified sequence, not proof of the game's ordering for two simultaneous effects.

An absolute `SetActionDelay(0)` is not definitionally the same operation. Subtracting one full interval from a hypothetical G15000 leaves5000 under the proportional model; setting the delay tozero does not. This example intentionally exposes the extrapolation boundary beyond a normal full interval. It does not assert that every in-game effect advertised as100% advance uses that subtraction rule in an over-delayed case.

## 5. Exact source-to-rule maps

### 5.1 Flat-speed producer, not an explicit delay mutation

S1/S2:

```text
Skill03 (Ultra, AllTeamMember) -> Avatar_Asta_00_Skill03_Phase01
 -> TriggerAbility(Caster, Avatar_Asta_00_Skill03_Phase02)
 -> AddModifier(AllTeamMember, MAvatar_Asta_00_Ultra_SpeedUP)
      LifeTime = hash242053466 <- SkillParam(Skill03,1)
      MDF_PropertyValue = hash812362065 <- SkillParam(Skill03,0)
 -> local modifier.OnStack
      StackProperty(ModifierOwnerEntity, SpeedDelta,
                    read working hash2128130574)
```

The selected Phase02 and speed-modifier bodies contain no explicit SetActionDelay/ModifyActionDelay transport. The mutation is a SpeedDelta contribution. P3 explains its flat-speed meaning; section4 supplies the accepted observable remaining-AV consequence. We do not pretend that the implicit scheduler rescale call was exported here.

A separate `MAvatar_Asta_00_SkillPreShowModifier` authors `ActionDelayPreshowConfig.AddSpeedValue` with the same producer. That predicts a display; it is not a second Speed grant. The speed-state definition does not serialize a LifeStepMoment in the inspected body. Do not borrow one from the unrelated passive charge state to manufacture a timer rule.

### 5.2 Exact 25% normalized advance with an Ultimate gate

S3/S4 provide a complete selected parameter-to-operation chain:

```text
RelicSetSkillConfig[SetID110,RequireNum4]
  AbilityName = Ability51101
  AbilityParamList[0].Value = 0.25
 -> Equip/RelicAbility Ability51101
      hash1098494600 = SkillRelic(TriggerKey110_4,Index0)
 -> OnStart AddModifier(Caster,MRelic_110_Main)
 -> OnAfterSkillUse
      ByCurrentSkillType(Ultra)
 -> ModifyActionDelay(ModifierOwnerEntity)
      AddNormalizedValue:
        OpCodes=AQAOEQ==, FixedValues=[], DynamicHashes=[1098494600]
```

The expression's unary-negative interpretation gives -0.25, reconciled with P4's post-Ultimate advance wording and the already retained positive-delay direction. The holder is the wearer; neither the Ultimate's target nor the effect's display label is substituted as timing owner.

This same modifier contains `ModifierAffectedPreshowConfig` with the same expression. Only the actual callback invokes the logical delay operation. Counting the preview as another advance would be double application.

S4b is a genuine same-pin sibling with the same ability name, but it has `DynamicValues.Values`, `ReadInfo.Type=None/Str=110_4` and `OpCodes=AQAHCg==`. S4 has the typed Floats/SkillRelic form. Do not splice the two serialized languages together. This record uses S4 for its typed binding; it does not claim to have recovered native registry precedence between duplicate named definitions.

### 5.3 Immediate normal action through an absolute write

S5 selects Skill02 as a FriendSelect Skill with `EntryAbility=Bronya_00_Skill02_Phase01`. S6 Phase01 tests the literal `ByIsTurnActionEntity(AbilityTargetEntity)`, choosing its self/current-action branch or its Others branch. In the inspected Others_Phase02:

```text
selected ally cleanup/buff work
 -> SetActionDelay(AbilityTargetEntity, fixed0)
 -> explicit continuation and SkillPerformFinish
```

P5's immediate allied action explains the zero write; its self-target exception agrees with having a separate branch. The predicate is not renamed to a generic caster-equality test, and this task does not claim a complete audit of the Self_Phase02 body. Being ready at zero is distinct from executing in the middle of another unresolved operation or overriding all queued inserted work.

## 6. Action categories are not one reset-and-decrement hook

The following matrix is a source/model distinction, not a proposed backend IR or a universal scheduler order.

| Category | Normal position / elapsed AV | Lifecycle consequence to preserve |
| --- | --- | --- |
| Ordinary naturally scheduled turn | Waiting time progresses; applicable normal interval is renewed after completion | Relevant start/end clocks can step; not one step per hit |
| Normal turn made ready by advance/zeroing | May become ready without positive elapsed AV | Still a normal turn for applicable duration rules, unlike an exempt extra-action protocol |
| Ordinary out-of-turn Ultimate | Does not itself replace the next normal turn; effects can modify position | Skill-use callbacks and named consumption still execute; it is not a global modifier-expiry command |
| Triggered follow-up / inserted ability | Entry is trigger/insertion-owned rather than automatically a new natural slot | Damage category, owner, trigger counter and insertion priority are independent inputs |
| Resurgence-like extra action | An explicitly described extra opportunity | P6 supports retaining ordinary buffs; the granted buff state and action entitlement are separate |
| OneMore protocol | Source-authored marker/controller rather than just AVzero | Its own action-phase lifetime/count updates can consume it |
| Coordinated sub-ability | Entry may be a parallel contribution to another actor's action | Do not infer what happens to the contributor's separate normal slot without evidence |

P1's ordinary Ultimate description is used with legal-entry restrictions, not as permission to interrupt any internal hit arbitrarily. The Eagle chain proves why "Ultimates never change AV" is too strong: the action category and its triggered timing effects are separate. Likewise, Asta can change several recipients' remaining AV through a Speed mutation.

[The timeline record][TIMELINE] already establishes that TurnInsertAbility can transport a revive action as well as other inserted work. It cannot therefore be interpreted as the damage category "follow-up" merely from the operation name. [F05][APPLICATION]'s two-hit/one-application distinction additionally rules out equating hit count with action count or lifetime steps.

### OneMore's own clock is an explicit counterexample

Reused shared `OneMore` has `LifeTime=1`, `LifeStepMoment=ActionPhaseEnd`, flags `[OneMore,LifeStepImmediately]` and `Stacking=Merge`. Its `OneMorePerTurn` controller instead has a modifier-phase clock and separate create, action-end, turn-end and destruction writes. Entitlement, counter and natural action slot are not interchangeable.

The audited Gepard branch selects an OneMore marker when already turn owner, but SetActionDelay0 otherwise, after a separate revive insertion. The inspected Seele route does not reduce to that OneMore marker. These positive source distinctions survive even when public language calls both outcomes an extra action.

Consequently, a public exemption from ordinary buff-duration ticking must not become "no modifier or counter ever changes during extra actions." The enabling marker itself can have an action-bound consumption rule. Exact runnable ordering among that marker, pending Ultimates and other inserts is not newly settled here.

## 7. Duration clocks, control and presentation time

Reuse F06's finite-state clock dimensions: clock entity, eligible event, first eligible step, subsequent steps and exit dependency. A status on a teammate may be removed by a caster-owned parent's clock. Advancing that teammate does not magically make the teammate the parent's clock owner.

P6's ordinary-Bronya-turn versus Resurgence comparison supplies the practical distinction: an advanced normal turn can consume the affected unit's ordinary buff duration whereas the described extra action retains it. P3 and P6 also state specific application-turn exceptions for Asta's speed buff and Seele's separately granted buff. These are positive rules, not justification to invent a universal first-step flag default.

Natural periodic callbacks, OnAfterSkillUse, OnActionEnd, ActionPhaseEnd and ModifierPhase1End remain separate names and domains. F06's DoT/HOT recipient-phase tick is not invoked anew solely because another actor uses an Ultimate. An explicitly requested extra activation is another path; its damage does not by itself create a natural turn.

F03 already inspected shared Frozen with `ModifyCurrentSkillDelayCost(ModifyFunction=Set,NormalizedValue=0.5)`. P2 describes its skipped action and shortened following interval. This is a selected current-cost/control rule, not an extra positive50% delay and not a universal one-turn cooldown. F03's Frozen/Entangle damage is authored as Pursued: P1's loose DoT terminology does not override that raw category.

Animation waits, cinematic Timeline names, TargetTimeSlow, preshow and wall-clock duration are not elapsed battle AV just because they contain time-related words. Mode-defined cycles or score windows are another clock again; their budgets and exact boundary handling require that mode's rule. No universal cycle length is invented in this ordinary timing record.

## 8. Initial ties and exact scheduling residuals

P2 gives an ordinary initial-deployment ordering: lower AV first, with allies before enemies at equal AV and lower slots first within those groups. Record this as an attributed observable initial-order model. Its description of stable sorting is not a recovered native algorithm, nor proof that late summons, forced zeroing and pending inserts reuse the same tie rule.

P1 separately describes queue behavior for consecutive full advances. This record does not turn that narrow prose into a global last-in-first-out rule. Initial tie resolution, equal ready positions after mutation, insertion priorities and within-turn continuation are different questions. A supported initial model and an unresolved mixed-insertion case can coexist.

## 9. Calculation-only discriminators

All rows below are synthetic predictions under the stated ordinary model, before display rounding and with no intervening timing effect. They are not gameplay observations.

| Controlled input | Result / distinction |
| --- | --- |
| Full interval, Speed100 versus125 | Base AV100 versus80 |
| Base Speed100, flat25, then +20% of base | Effective Speed145, not150 |
| Remaining AV40, Speed100 becomes150 | Remaining AV26.6667, not a new full interval66.6667 |
| Remaining AV40, Speed100, 25% advance | Remaining AV15, not30 |
| Remaining AV10, Speed100, 25% advance | Ready at0; excess is not carried into the next ordinary interval by this model |
| Remaining AV40, Speed100, 25% delay | Remaining AV65 |
| G1000, 20% advance followed by20% delay | G0 then2000; not the net-before-clamp result1000 |
| Two waiting entities at Speed100/125, both G10000 | After80 elapsed AV, the second is ready and the first has20 AV left |
| A legal non-timing Ultimate resolves while another entry has40 AV left | No positive AV passage solely from the animation; any speed/advance callback must be accounted for separately |

These examples are derived from the accepted equations and selected source distinctions, not a fit to invented measurements. Internal precision, an exact boundary event, or an explicit override may require additional information before predicting a full encounter.

## 10. Claim accounting, remaining work and next foundation

| Claim | Established basis | Remaining boundary |
| --- | --- | --- |
| Ordinary positive-speed gauge/AV model and rescaling | P1/P2, algebra and S1/S2 speed-input mapping | Native unit conversion, property conversion/lock exceptions |
| Full-interval advance versus remaining-timer scaling | P1/P2 and exact S3/S4 coefficient/callback | Special full-advance overrides, clamps and simultaneous ordering |
| Absolute zero, normalized delta, current-cost and insertion are distinct | S4/S6 and reused timeline/F03 graphs | Exceptional equivalence and normal-slot accounting by action family |
| Normal/extra/Ultimate action versus modifier clocks | Reused OneMore/F06 and P3/P6 descriptions | Complete first-step/control/event-category matrix |
| Ordinary initial tie model | Attributed P2 explanation | Native implementation and mixed ready/insert/summon ties |
| Backend/runtime correctness | Not evaluated | No implementation acceptance or E claim |

Specific residuals: the mapping between raw SpeedToDelayDistance1000 and any native/display representation; same-time speed/advance/clamp and zero-ready arbitration; special speed/turn locks and oversized-delay full-advance behavior; first-step/control exceptions and exact slot renewal; coordinated or newly created entity timing; and a complete event-to-clock map. Descriptions and controlled public tests can advance these questions without a native dump. They do not invalidate the ordinary equations above.

**Next primary foundation: F07 shared resource economy.** Use the action/clock distinctions to separate Energy from team Skill Points, base generation from regeneration modifiers, costs from availability, and action-triggered gains from natural-turn counters. Reuse R4 and the source labels already reconciled by F05/F06; do not expand the timing samples' remaining kits. F04 remains queued. F07 is not executed by this checkpoint.

Publication adds this record and updates only roadmap/README navigation and claim-level status. Historical timeline evidence and broad W checkboxes remain intact; no whole-package completion percentage is introduced. Verification consists of source/public-text and algebra review, plus Git content/diff/head checks. No raw pin, runtime, lowering, IR, tests or CI change.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Asta_00_Config.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicSetSkillConfig.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Equip/RelicAbility.json
[S4b]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/RelicAbility.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Bronya_00_Config.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Bronya_00_Ability.json
[S7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConstValue.json
[P1]: https://hsr.keqingmains.com/misc/speed-guide/
[P2]: https://srl.keqingmains.com/combat-mechanics/turn-order/turn-order-mechanics
[P3]: https://hsr.keqingmains.com/asta/
[P4]: https://srl.keqingmains.com/equipment/relics
[P5]: https://srl.keqingmains.com/characters/wind/bronya
[P6]: https://hsr.keqingmains.com/seele/
[TIMELINE]: timeline_one_more_and_speed_boundary.md
[BREAK]: general_weakness_toughness_break_super_break_v1.md
[APPLICATION]: general_effect_application_hit_resistance_immunity_v1.md
[MODIFIERS]: general_modifier_identity_stacking_lifetime_v1.md
