# General resources: Energy, regeneration, Skill Points and capacity v1

## 1. Scope and result

Reviewed 2026-09-24. Evidence parent: `e392081bd2c016ca686923b2e619d0a2564510d2`; preceding checkpoint: `5806458505` (F08). Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains open/Draft and documentation/evidence-only.

**F07 result:** distinguish actor Energy from shared team Skill Points; explain ordinary base generation and regeneration-rate scaling, fixed grants and fixed maximum-Energy fractions, cost versus capacity, offered versus realized gains, and balance changes versus capacity changes. A published memosprite rule explains Energy redirection and team-grant deduplication alongside an exact raw selector. Source operations, description-derived values, historical tests and calculated predictions retain separate provenance.

The research object is the common resource system. Natasha supplies the already-audited ordinary row comparison; Tingyun and Huohuo discriminate two grant families; Sparkle discriminates team balance/capacity and signed expenditure. This is not completion of their kits. F07/W08 remain active for the precise initialization, transport, sampling, special-resource and transaction-order residuals below.

For the claims covered here, this record supersedes [R4][R4]'s blanket withholding of public Energy/Skill Point names and arithmetic. R4's original rows, request recipients, omitted fields and genuinely missing native relationships survive. A supported gameplay model does not require that our backend implements it or that GameCore's evaluator body be available.

## 2. Source register

### Pinned raw sources inspected this round

All S paths refer to the fixed TBGD revision. Named Ability and callback selectors identify serialized occurrences without guessed numerical array offsets.

| Ref | Path / selected occurrence | Complete blob |
| --- | --- | --- |
| S1 | [GameCoreConstValue][S1]; TeamBPFloatStart/Max/ToIntegerRatio, neighboring Turn/RoundAddBoostPoint | `47ed0e027c76df398cf6e13de104933299ec1700` |
| S2 | [Tingyun CharacterConfig][S2]; Skill03 entry, SkillParam(Skill03,0), SkillRank(Rank06,0) | `2211a8e69b180b176fbafdf098720d8d982fd255` |
| S3 | [Tingyun Ability][S3]; Avatar_TingYun_Skill03_Phase02 grant branches and separate Caster AddRatio; selected basic hit layout | `41b224f8a3261db6a2e0aeb269bf834a77381489` |
| S4 | [Huohuo CharacterConfig][S4]; Skill03 entry/membership and SkillParam(Skill03,0) | `d3fd8ffbd4539ffcb4e51b023c7cc66c67f348c6` |
| S5 | [Huohuo Ability][S5]; Avatar_Huohuo_00_Skill03_Phase02 maximum-relative grant and separate self request | `2bcd081a8102a7666336826a1c9f3ae3ec9d6aa4` |
| S6 | [Sparkle CharacterConfig][S6]; Skill03/SkillP01 entry and typed resource inputs | `8d9b1dcb4cb0c07dca9b62988f384461b843e5e6` |
| S7 | [Sparkle Ability][S7]; Skill03 balance change; PassiveSkill_1 installation; local listener OnCreate/OnDestroy/OnListenBpChange; selected first-wave Technique request | `bc1b5b53e4387e82042505f94f28a28c78db8ad7` |
| S8 | [RelicSetSkillConfig][S8]; SetID308, RequireNum2, PropertyList and AbilityParamList | `a8022b783c42d05f6cb168010ecbcfa90b69182d` |

Useful replay ranges: S1 lines1-50; S2 95-385; S3 1270-1555 plus selected Skill01/Skill02 bodies; S4 250-435; S5 900-1080; S6 120-380; S7 1160-1350,1900-1990,2240-2400,2640-2755; S8 580-625. Use full blob plus named selectors if viewer line layout differs. Reading nearby material does not make all of it part of this mechanism audit.

### Explicitly reused pinned evidence

[R4][R4] supplies the exact Natasha AvatarID1105 / SkillID110501,110502,110503 level1 rows, common kill listener, servant-to-owner grant and resource/UI distinctions. Its AvatarConfig blob is `7ef386fe8256f1374c693e4962e7599249aac9db`; AvatarSkillConfig is `a5416ced941c247d475b2aaa83277b9cdf474dd9`; Natasha Ability is `0dd71d6942e4f8420749c56c8151710dee0bf9f0`; Avatar_Common_Ability is `21db58fafcb8fa826c5913b4e019d6c9e56e5f6f`. These are reused findings, not a new census or fresh numeric-row extraction.

[F06][MODIFIERS] and [F08][TIMING] supply the distinction between a state clock, an action, an inserted skill and an individual damage operation. A resource operation needs its actual event and recipient; a UI counter or animation ending is not automatically a resource transaction.

### Public evidence and interpretation

Consulted 2026-09-24. Public version labels are not a substitute for the TBGD pin. Descriptions are semantic evidence; data-site copies are not independent gameplay experiments.

| Ref | Publication / provenance | Accepted use and limit |
| --- | --- | --- |
| P1 | [KQM beginner guide][P1], Character Stats / Skills / Combat Screen | Ordinary Energy versus shared Skill Points, common gain sources and default 3/5 team pool. Its broad launch-era maximum-Energy wording is restricted by P7's counterexample. |
| P2 | [DangitDon, An Optimization Guide on Energy Recharge][P2], original June2023 report and correction discussion | Reported ordinary scaling tests, named Tingyun exception, and an explicitly rejected rounding inference. No new game replay, video inspection or acceptance of every generalized claim in the post. |
| P3 | [KQM Huohuo guide][P3], body labeled Version1.5; authors Aimgo, skylarke, Sushou, soul_fish | Ultimate wording: each eligible teammate's maximum-Energy fraction; level10 20%; explicitly unaffected by ERR. The later infographic date does not repin the body. |
| P4 | [KQM Sparkle guide][P4], Version2.7, Ultimate/Talent/Technique/E4 | Public meanings of baseline +4 balance, +2 capacity, per-point consumption and first-entry +3; raw parameter slots remain separately registered. |
| P5 | [KQM SRL Natasha data publication][P5] | Explicit energyGain20/30/5 and energyNeeded90 labels for the same named skills; a semantic corroboration, not independent measurements. |
| P6 | [KQM memosprite mechanics][P6], Version3.2, by Soul Fish | Memosprite Energy routing and one grant per memomaster for the named teamwide effects. Not a claim about every summon or every special gauge. |
| P7 | [KQM Yunli quick guide][P7], Version2.4, by jas | Skill text consumes120; stated capacity is twice cost; useful counterexample to cost=capacity. Public-model-only here, without a new Yunli raw trace. |
| P8 | [KQM relics overview][P8], Sprightly Vonwacq | 5% Energy Regeneration Rate meaning for S8's SPRatioBase0.05; the other set effect is separate. |

P5 was read through GitHub at `KQM-git/SRL@de0e5c09c8dbba9577367ad86e991fe91c4f0e36`, `src/data/characters/Natasha.json`, blob `98fbeab966db7e0072342a52d01d539c5de1c8d5`. This external publication revision is not raw TBGD authority. P3/P4/P7 wording supplies selected numeric interpretations where this task did not reread the pinned skill rows. No same-pin localization join is claimed for those descriptions.

## 3. A resource record needs more than its displayed amount

Keep the following dimensions separate: resource namespace; state owner; actual recipient and possible redirection; current balance; capacity; initial-state policy; skill requirement/cost; nominal gain and its base; applicable amplification; trigger/eligibility; and realized post-cap change.

| Public domain | Pinned anchors | Do not conflate |
| --- | --- | --- |
| Actor Energy | SPNeed/SPBase in selected actor/skill rows; ModifySPNew with entity target; SPRatioBase contribution | Public abbreviation SP for Skill Points; a presentation EnergyBar counter |
| Team Skill Points | TeamBPFloatStart/Max; BPAdd/BPNeed; ModifyTeamBoostPoint; current/max BP readers | Each team member receiving an independent copy of the pool |
| Character-specific counters | Must retain their own operations and owners | Every gauge, charge or integer becoming either Energy or team BP |

P1/P5 connect R4's topology to the public names. This supersedes the old labels being merely energy-like and skill-point-like for these exact families. It does not classify every SP/BP substring across the corpus.

## 4. Ordinary Energy accounting and regeneration rate

For an eligible ordinary Energy gain with no explicit bypass or special converter, use the attributed model [P1][P2]:

```text
R_i = 1 + sum(applicable ERR bonus contributions at event i)
G_i = b_i * R_i
E_after = min(C, E_before + G_i)       for 0 <= E_before <= C, G_i >= 0
realized_gain = E_after - E_before
```

Here b_i is the base grant, R_i the applicable total regeneration factor, and C the effective Energy capacity. For ordinary actor-owned generation, the actor's rate is relevant; the effect applier is not automatically the rate owner. Redirected memosprite grants need the source/owner distinction in section7 rather than blindly applying a second rate on receipt.

A displayed total rate of125% corresponds to R=1.25; a +25% bonus also produces R=1.25 when no other bonus applies. Do not add another baseline1 to an already-total factor. Changing R between events prevents factoring one final rate out of the whole history.

S8 `[SetID=308,RequireNum=2].PropertyList[0]` literally uses `FODBMMCKAEN=SPRatioBase`, `MNDFOPKBHKP.Value=0.05`. P8 identifies its Energy Regeneration Rate meaning. The separate AbilityParamList contains0.05/120/0.4; those values are not three regeneration contributions or three separate grants. The property input is not an immediate +5 Energy operation.

### 4.1 Ordinary skill base, requirement and refund

R4 plus P5 provides a directly reusable comparison:

| Selected row, level1 | SPBase | BP fields retained | Public semantic result |
| --- | ---: | --- | --- |
| Natasha110501 / Skill01 | 20 | BPAdd1, BPNeed-1 | Ordinary basic base Energy20; ordinary team-point generation is separate |
| Natasha110502 / Skill02 | 30 | BPNeed1; BPAdd omitted | Ordinary Skill base Energy30 and team-point cost1 |
| Natasha110503 / Skill03 | 5 | SPNeed90, BPNeed-1; BPAdd omitted | Ultimate requires/consumes90 in this ordinary case, then generates base Energy5 |

Do not decode BPNeed-1 as negative spending or fabricate omitted BPAdd=0. The public ordinary zero-cost interpretation does not supply the native sentinel-resolution implementation.

Natasha's non-damaging Skill and Ultimate submit `ModifySPNew(Caster,AddRatio=1)` in their own execution bodies. Paired with the skill-qualified SPBase and P5's labels, the selected observable interpretation is one copy of that skill's base generation, not100% of maximum Energy. R4's exact native lookup between SPBase and AddRatio is still not recovered. Mixed AddRatio/AddValue requests and arbitrary defaults are not given a universal evaluator by this comparison.

A cost and a later refund must remain separate. For the selected ordinary90-cost Ultimate, consumption followed by base5 generation is not an85-cost Ultimate. Rate amplification applies to the eligible grant, not by definition to the cost. Exact reservation/debit timing, interruptions and interleaved gains remain transaction-order questions.

### 4.2 Count the energy-producing event, not animation hits

R4's common listener requests AddValue10 on its holder after the selected OnTriggerDeath predicate, explicitly excluding MonsterID9001013. The source owner and predicate survive; this is not an unconditional +10 for every actor whenever any target disappears. Other attack, hit, kill, trace and triggered gains require their own amounts and eligibility.

S3's selected basic has two damage requests with HitSplitRatio0.3/0.7 and SPHitRatio1 on both. Their mere count does not prove two full20-Energy grants. Likewise, damaging several targets or generating several DoT instances does not authorize a full skill-base award per recipient. The shared SPHitRatio allocation/aggregation remains separately unidentified; do not repair it by multiplying public20/30/5 by hit count.

## 5. Two distinct fixed-grant families

A number described as flat in ordinary language need not bypass ERR. The accepted bypass below is supported by both a distinct raw operand and the named public behavior, not by the English word flat alone.

### 5.1 Fixed absolute grant

S2/S3:

```text
Skill03 -> Avatar_TingYun_Skill03_Phase01 -> Phase02
 -> ByRankActivated(TriggerKey.Hash=-1445815962)
    inactive branch:
      ModifySPNew(AbilityTargetEntity)
        Tag={EnumIndex:6,Value:1}
        FixedAddValue=AQAR / [-1349665456]
        -1349665456 <- SkillParam(Skill03,index0)
    active branch:
        FixedAddValue=AQABAQIR / [-1349665456,-1752447704]
        -1752447704 <- SkillRank(Rank06,index0)
 -> separate later ModifySPNew(Caster,AddRatio=1)
```

The named grant's public baseline is50 Energy and does not scale with either Tingyun's or the target's ERR [P2][P7]. Therefore its selected nominal gain is F, with realized gain `min(C,E+F)-E`. The active branch adds the rank parameter; this record does not expand that character's remaining ranks or pretend its numeric row was reread.

`FixedAddValue` is not `AddValue`, and the allied grant is not the caster's later ordinary self-generation. Neither the matching Tag nor the operation type alone defines an ERR policy for every other request.

### 5.2 Fixed fraction of recipient maximum Energy

S4/S5:

```text
Skill03 -> Avatar_Huohuo_00_Skill03_Phase01 -> Phase02
 -> ModifySPNew
      TargetType=AllTeammateOnlyAddSPOnceForServant
      Tag={EnumIndex:6,Value:1}
      FixedAddMaxSPRatio=AQAR / [-668390952]
      -668390952 <- SkillParam(Skill03,index0)
 -> separate later ModifySPNew(Caster,AddRatio=1)
```

P3's description identifies q times each eligible recipient's own maximum Energy, excluding Huohuo, with no ERR multiplication; at described level10 q=.20. The selected nominal gain is `q*C_recipient`, not q times current Energy, the caster's capacity, the recipient's missing Energy or the current skill's SPBase.

These three similarly named inputs consequently have different bases: ordinary AddRatio against the selected skill-generation model; FixedAddValue as an absolute grant; FixedAddMaxSPRatio as a recipient-capacity fraction. A universal `all ratios * maxEnergy` rule is incorrect for the covered cases.

## 6. Cost, capacity, initialization and overflow

For an ordinary positive cost c, the Energy part of availability requires sufficient current Energy; other legal-entry conditions can still prevent use. A selected post-consumption model subtracts c, rather than clamping an unaffordable cast into legality. This is a behavioral account, not the native reservation, rollback or queue implementation.

Cost and capacity may happen to match in R4's ordinary Natasha sample, but equality is not a universal construction rule. P7 states that Yunli consumes120 while storing twice that amount. Thus the public-model capacity is240; Huohuo's described20% grants48, also stated by P7, not24. This is a public-only counterexample to a bad generalization, not a newly closed Yunli source chain.

For ordinary positive grants at a fixed cap, offered gain can exceed realized gain. With E80, C90 and an offered37.5, only10 is stored. Do not retain discarded overflow for a subsequent Ultimate unless an explicit mechanic permits it. Cap shrinkage, special overfill reservoirs and multi-cost states require separate rules.

There is **no universal initial Energy value established by this pass**. The selected raw actor requirement does not specify whether an encounter imports prior state, sets a mode-specific amount or applies entry grants. Record initial Energy as a scenario-policy input until its actual source is identified; do not invent zero, full or50% for every battle. Team Skill Point baseline initialization is separately supported below. This remaining initialization edge does not make ordinary gain or cost arithmetic unknown.

## 7. Recipient, resource owner and team-grant deduplication

P6 establishes the ordinary memosprite model: it has no independent Energy gauge; Energy generated through its relevant skills, hits, defeats or received grants goes to its memomaster. The named teamwide sources, including Huohuo's Ultimate, apply only once to that memomaster whether the memosprite is present or absent.

S5's actual `AllTeammateOnlyAddSPOnceForServant` selector directly corroborates the one-per-owner interpretation. R4's independently explicit `ModifySPNew(CasterSummoner,AddValue20)` death-rattle path also preserves the summoner as recipient. Keep the raw selectors rather than flattening a team grant into one identical transaction per visible entity.

A non-gauge-owning entity can still be an event source and possess ERR-related properties. P6 describes inherited ERR; this does not authorize multiplying by both memosprite and memomaster rates. Exact property sampling/redirection for each grant family and the native alias expansion remain separately scoped. The documented public redirection/deduplication rule is nevertheless usable now, not frozen pending that alias body.

This is not a claim that every battle event, summon, companion or character-specific charge uses the memosprite Energy model.

## 8. Team Skill Points: balance, capacity and spending

S1 with P1 identifies the ordinary baseline `P_start=3`, `P_max=5`, distinct from actor Energy. R4's basic BPAdd1 and Skill BPNeed1 align with ordinary gain and spending. Enhanced actions, no-cost skills and special grants are explicit exceptions, not a reason to force every Skill or Basic to those values.

For one admitted standalone change with no intervening event:

```text
positive gain g: P_after = min(P_max, P_before + g)
cost c: require P_before >= c; P_after = P_before - c
capacity change: update P_max separately, not an automatic balance grant
```

ERR is not a multiplier on team Skill Points. A later refund is a later grant and cannot generally be netted against a cost before affordability or spent-point triggers. An ability that can be selected several times during one natural turn still needs its actual per-use resource rules; F08's turn/action distinction applies.

### 8.1 Source chain for capacity versus balance

S6 binds `419301503=SkillParam(Skill03,1)` and `-1284285354=SkillParam(SkillP01,2)`. S7 has different consumers:

```text
SkillP01 -> Avatar_Sparkle_00_PassiveSkill_1
 -> SetDynamicValueByMaxBP(TeamBpMax)
 -> AddModifier(Caster,Avatar_Sparkle_00_PassiveSkill_Listen)
 -> listener.OnCreate, inactive selected rank branch:
      ModifyTeamBoostPointMax(Add, hash -1284285354)

Skill03 -> Avatar_Sparkle_00_Skill03_Phase02
 -> SetDynamicValueByCurrentBP(MDF_PassiveLayer01)
 -> inactive selected rank branch:
      ModifyTeamBoostPoint(Add, hash419301503)
      SetDynamicValueByCurrentBP(MDF_PassiveLayer02)
```

P4 describes baseline +2 maximum and +4 recovery. Thus, without the rank override, the ordinary capacity becomes7 rather than5; raising capacity does not itself refill the balance. An offered +4 at P6/cap7 stores1, not4. The before/after readers reinforce that balance is not identical to the requested amount; they do not themselves prove native clamp code.

Both OnCreate and Ultimate contain an active `ByRankActivated(Hash1686351920)` branch adding literal1 to their respective inputs, matching the described E4 distinction. The inspected OnDestroy subtracts only the base capacity parameter, without that extra literal. Retain this scoped source asymmetry; this pass does not infer its whole lifecycle outcome, call it a backend defect or invent compensating cleanup. The ordinary no-override path is not withheld because that exception needs separate treatment.

### 8.2 Expenditure is a signed event and can count points, not actions

The same listener's `OnListenBpChange` reads ParamValue into MDF_BPCount, negates it, and gates on `ParamValue<0` plus `ParamEntity` belonging to TeamLight. The outgoing buff's `LayerAddWhenStack` uses that negated amount. This preserves a per-point expenditure input rather than hard-coding one increment per skill or hit. P4's description expressly says per1 Skill Point consumed.

The event surface does not settle native reservation/refund semantics or every callback's relative priority. Its explicit negative-delta gate must not be generalized to spending whenever the gauge is merely below maximum.

### 8.3 Initial bonuses are separate from the default pool

S7's selected Technique state has `OnEnterBattle(Priority=-80) -> ByCompareWaveCount(Equal,1) -> ModifyTeamBoostPoint(Add,hash1984425976)`. P4 describes an entry +3 when its Technique condition is met. The raw numerical binding for that hash was not newly completed here; the exact first-wave gate and separate grant are directly inspected.

Therefore the ordinary3 starting points are a baseline, not a promise that every encounter begins with exactly3 after all entry effects. S1 also exports `TurnAddBoostPoint=0` and `RoundAddBoostPoint=2`; no ordinary reachable consumer for the latter was established here. Its existence does **not** justify an automatic +2 after every round. Constants, active requests and scenario initialization must remain distinct.

## 9. Public testing can discriminate rules without supplying native code

P2 reports Sushang with a displayed1.194 regeneration factor charging a120-cost Ultimate after base amounts `5+30+30+20` and two S1 Quid Pro Quo grants of8. Scaling those grants predicts120.594; excluding them from scaling predicts117.49. That reported result supports the selected Light Cone grants being amplified. It refutes the rule that every externally supplied or numerically flat grant is unscaled. No Quid Pro Quo raw chain or new experiment is claimed here.

The same post proposes rounding near a fractional .8 based on displayed inputs. Its discussion identifies hidden input precision as an alternative, and the author acknowledges that explanation. This record does **not** adopt an arbitrary .8 Ultimate threshold, nor the post's tentative generalization to all character skill grants. Keep the useful named tests separate from their unsupported extensions. Future boundary checks must use exact pinned operands rather than rounded UI numbers.

## 10. Calculation-only discriminators

These are synthetic predictions under the stated models, with admitted requests, fixed relevant capacities and no intervening gains, locks or special overrides. They are not game observations or canonical-build fixtures.

| Deliberate input | Predicted result / interpretation |
| --- | --- |
| Ordinary base30, total ERR factor1.25 | Offered37.5 Energy |
| Named fixed absolute grant50, either participant has factor1.25 | Offered50, not62.5 |
| Named fixed maximum fraction.20, capacity130 versus140 | Offered26 versus28, not a fraction of missing Energy |
| E80/C90, ordinary offered37.5 | Realized10; stored90 |
| Selected ordinary90-cost sequence, factor1.20, post-Ult base5 then Skill30 and two Basic20 grants | `(5+30+20+20)*1.20=90`; a model threshold, not a new successful battle |
| Capacity rises5->7 with current team balance4 | Balance remains4 until a separate balance-changing operation |
| Offer team +4 at P4/cap5 versus P4/cap7 | Final5 versus7; realized1 versus3 |
| One qualifying signed team expenditure of3 | The inspected listener receives a three-point layer-add input, subject to its state cap, not one because one action occurred |
| Huohuo's eligible team grant with a memomaster and its memosprite present | One eligible owner grant under P6; not two copies because two entities are visible |

## 11. Claim accounting and precise remaining research

| Claim | Established basis | Deliberate boundary |
| --- | --- | --- |
| Selected raw SP / BP public identity | R4 topology plus P1/P5 labels | Not every similarly named field or gauge |
| Ordinary skill base generation, rate scaling and cost/refund separation | R4, P1/P2/P5, S8 property input | Exact SPBase lookup, mixed operand/default behavior and transaction timing |
| Fixed absolute versus fixed recipient-max grants | S2-S5 and P2/P3/P7 | No universal inference from Tag or English wording |
| Memosprite redirection and named team-grant deduplication | P6, S5 selector and reused R4 owner request | Native alias expansion and per-family rate sampling |
| Team baseline, separate balance/capacity changes and per-point spending | S1/S6/S7, P1/P4 | Special cap shrinkage, override teardown and event arbitration |
| Capacity is not always one Ultimate cost | P7's explicit counterexample | Public-only discriminator; no new raw capacity constructor |
| All resource families or local runtime correctness | Not claimed | F07/W08 active; no C/D/E promotion |

Remaining research: encounter-specific initial Energy/carry-over and capacity construction; SPHitRatio/per-hit and additional-action award allocation; resource-owner/rate selection during redirection; simultaneous debit/refund/grant/Ultimate availability; exact numerical precision and boundary clamps; special spending substitutes, overfill and alternate gauges; and capacity-override teardown. These are concrete behavioral or source-edge questions, not a backend implementation queue.

## 12. Publication and next foundation

This checkpoint adds this record and updates the foundation roadmap/README only. R4's historical source record and broad W checkboxes remain intact. No runtime, lowering, IR, tests, CI, inventory or pin change, and no implementation dependency is created. No game session, simulator, Direct or test/workflow execution was invoked for this research; no passing CI or local-runtime E is claimed.

Verification is actual source/public-document inspection, expression and equation review, and Git diff/content/head/Draft checks. A guessed Hanabi filename returned404 before the actual Sparkle path was found; it is not absence evidence. Public-page transport limitations were handled with readable indexed text or the identified GitHub publication. No unread video, spreadsheet, localization row or native body is claimed inspected.

**Next primary foundation: F04 healing, shielding and damage-to-HP interfaces.** Reuse already reconciled base equations and study the remaining common gain/mitigation/absorption/overflow/cleanup distinctions. Do not continue the resource samples' kits or redo the old formula searches. F04 is not executed in this checkpoint.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConstValue.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Tingyun_00_Config.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Tingyun_00_Ability.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Huohuo_00_Config.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Huohuo_00_Ability.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Sparkle_00_Config.json
[S7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Sparkle_00_Ability.json
[S8]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicSetSkillConfig.json
[P1]: https://hsr.keqingmains.com/misc/beginner-guide/
[P2]: https://www.reddit.com/r/HonkaiStarRail/comments/14hnu7w/
[P3]: https://hsr.keqingmains.com/huohuo/
[P4]: https://hsr.keqingmains.com/sparkle/
[P5]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/src/data/characters/Natasha.json
[P6]: https://hsr.keqingmains.com/misc/memosprite-mechanics/
[P7]: https://hsr.keqingmains.com/q/yunli-quickguide/
[P8]: https://hsr.keqingmains.com/misc/relics-overview/
[R4]: resource_economy_core_v1.md
[MODIFIERS]: general_modifier_identity_stacking_lifetime_v1.md
[TIMING]: general_speed_action_value_turn_clock_v1.md
