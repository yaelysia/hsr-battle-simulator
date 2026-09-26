# First modifier lifetime step: application turn, clock owner and delayed grants v1

## 1. Scope and bounded result

Reviewed 2026-09-26 at evidence parent `1b3ed9e96adda5e21702392e414e142ebf576c7c`, following checkpoint `5842523823`. Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 stays open/Draft and docs/evidence-only.

This executes `DIVE-FIRST-LIFETIME-STEP-V1`, the newly selected first-step part of FG-02/F06/F08/W07/W09/W10. The user approved switching from the bounded FG-01 result. Break-transition transport and exceptional-interleaving residuals remain recorded in [FG-01]; they are not prerequisites for this investigation.

**Result:** a newly installed effect's nominal duration does not alone determine whether the recipient's already-running turn consumes its first unit. The selected Asta Ultimate grants application-turn grace; the selected Bronya Ultimate counts that turn. A historical same-recipient/no-Resurgence comparison and explicit public explanations distinguish this from a blanket extra-action rule. The pinned grants differ in the presence of `LifeStepImmediately=true`, but omitted fields are not rewritten as serialized false and no universal native flag evaluator is claimed recovered. A delayed Bronya speed grant supplies a separate source-backed distinction between installing a listener and installing the timed property effect.

Scope is a fresh ordinary recipient-timed buff, normal turns, no expiry-boundary interruption, death, cleansing, or replacement by a concurrent application. Existing F06/F08 findings are reused. We do not complete character kits, enumerate all status clocks, study acquisition costs, or change production code. Reapplication/refresh/extension is explicitly not inferred from fresh-application behavior.

## 2. Source register and evidence strength

### Pinned source occurrences reread in this investigation

Paths are relative to TBGD at the pin above. Named selectors below are exact object identities; display line ranges are replay aids, not replacement source identities.

| Ref | Path and selected occurrences | Full blob; inspected ranges |
| --- | --- | --- |
| S1 | [Asta CharacterConfig][S1]: Skill03 entry/membership; lifetime and speed SkillParam reads | `147dfdfb5b6170e0371bc0a105d5342868e8f025`; 175-430 |
| S2 | [Asta Ability][S2]: Skill03 Phase01 -> Phase02; complete Ultra_SpeedUP definition and its installer | `b2a03d625fe8628eb927bd198d4108e5f7ba70b7`; 790-1140 |
| S3 | [Bronya CharacterConfig][S3]: Skill02/03 entries, membership, lifetime and Rank02 reads | `5139365b381cfc319c77093af0ae2a6ba9d6a036`; 110-600 |
| S4 | [Bronya Ability][S4]: Skill02 Others branch; Skill03 grant; complete relevant global modifiers and Rank02 listener | `78d897f4601e4fa13083a9edbb196faf2e6c5394`; 244-695, 1000-1450, 2100-2640 |

F08 already used these families for speed mutation and action advance. Here the new joins are application-turn behavior, the explicit first-step flag on the Ultimate grant, and the listener-to-later-speed-installation boundary. Their existence is not represented as discovery of previously unknown source families.

### Public descriptions, explanations and original reported observations

All listed public pages were retrieved in this investigation. Their version/date is not the fixed TBGD revision, and retrieval on 2026-09-26 is not a new gameplay test.

| Ref | Source and provenance | Narrow accepted use |
| --- | --- | --- |
| P1 | [KQM Asta][P1], body labeled v1.4; changelog publication 2023-10-14, later infographic entry 2025-01-23; credited AnemoneMeer, Alreph, MasterDank47 | Ultimate text gives two turns; explanation identifies application-turn non-decrement and recipient-specific duration. No gearing advice is imported. |
| P2 | [KQM Bronya][P2], body labeled v1.6; Ultimate and Quick March descriptions | Two-turn ATK/CRIT DMG grant; separate speed effect begins after the target acts and lasts one turn. The description alone does not state the Ultimate's first-step exception policy. |
| P3 | [KQM Seele][P3], body labeled v1.6; Playstyle and Talent | Buffed state is separate from Resurgence's extra action and can remain across the current and next normal turn when obtained by an on-turn Ultimate without a kill. Public-only supporting contrast here, not a fresh Seele raw audit. |
| P4 | [Original Reddit duration discussion][P4], 2023-10-22, thread started by u/toocoolforgg | A first-person reply reports casting Seele's Ultimate on her normal turn, expressly avoiding a kill/Resurgence, then casting Bronya's Ultimate before Seele acts. Bronya's buff decremented after that action; Seele's state did not. This is a reported observation, not our replay. |
| P5 | [KQM Hanya][P5], body labeled v2.1, publication 2024-04-15; writer ArielFriedrichGauss | Ultimate's mixed SPD/ATK buff has current-recipient-turn grace. Talent DMG buff is active before the attack yet also does not decrement on its acquisition turn. These are public-model counterexamples, not new Hanya source joins. |

P4's nested reply is located by its opening `I just tested this and this is not how it works` and its explicit no-kill/no-Resurgence setup. The indexed nested text did not reliably expose that reply's author/permalink; do not assign it to the thread starter or infer an author from neighboring replies. The page also contains corrected speculation and an explicitly unconfirmed list of flags. Neither that list nor an uninspected Discord link is an audited TBGD source. No embedded video was replayed. Exact client revision, complete build and initial-state trace are not supplied by the short report.

P3 independently supplies an authored explanation compatible with the reported Seele half; it is not a second replay of P4. P1/P2/P3/P5 are related KQM publications and are not counted as four independent experiments. A 2023-05-04 TapTap article found during navigation explicitly labels itself an NGA repost; its broad speed/offense classification was not adopted as an original test or universal rule.

## 3. The first-step question is separate from duration, potency and activation

For each effect, preserve the following research facts:

| Fact | Why it matters |
| --- | --- |
| Admitted lifetime | The duration input from the skill/installer, not a count of all actions in the battle |
| Recipient and clock owner | A provider's action and a recipient's duration event need not be the same event |
| Actual installation point | A request, pending listener or preview can precede the timed effect |
| Eligible lifecycle moment | Turn start, end, a parent clock, a named action event or a use count are distinct |
| Treatment of an already-running application turn | That boundary can be counted or exempted for the selected effect |
| Reapplication and removal | Neither is derived from the fresh-installation rule |

The operative question is not just whether an Ultimate was used. It is which effect was admitted, whose normal turn was in progress, and whether that effect counts that turn's relevant boundary. F06's caster-clock parents and periodic callbacks remain separate cases; this record does not apply recipient-turn-end bookkeeping to all of them.

## 4. Asta: a live speed grant with application-turn grace

S1 joins Skill03 to `Avatar_Asta_00_Skill03_Phase01`. S2's Phase01 triggers Phase02, whose actual `OnStart[2]` grants `MAvatar_Asta_00_Ultra_SpeedUP` to `AllTeamMember`.

```text
S1 DynamicValues.Floats[242053466]
  SkillParam(Skill03, index=1)
    -> S2 Phase02.OnStart[2].LifeTime

S1 DynamicValues.Floats[812362065]
  SkillParam(Skill03, index=0)
    -> installer.DynamicValues.MDF_PropertyValue
    -> receiving working hash 2128130574
    -> Ultra_SpeedUP.OnStack
    -> StackProperty(ModifierOwnerEntity, SpeedDelta)
```

This is a combat property effect, not an animation timer. The complete selected modifier has `STAT_SpeedUp`, `Stacking=ReplaceByCaster` and the property callback. It does not explicitly serialize `LifeStepMoment`. The selected AddModifier does not serialize `LifeStepImmediately`. Both omissions are preserved as omissions.

P1 supplies the two-turn meaning and the rule that the application turn does not spend duration. For a recipient whose normal turn is already running when the fresh buff is applied, the supported ordinary model preserves both units at that turn's end. It is not necessary to invent an explicit false field or a native decrement function before accepting this behavior.

The two-turn number here is from the published skill description; the raw lifetime is the exact typed index above. This pass does not claim to have newly read the corresponding numeric AvatarSkillConfig row. F08's already established speed/AV relation is reused, not rederived or confused with duration spending.

## 5. Bronya: a grant that counts the recipient's application turn

S3 selects `Bronya_00_Skill03_Phase01`; S4 triggers its Phase02. The selected installer is `Bronya_00_Skill03_Phase02.OnStart[5]`:

```text
AddModifier
  TargetType = AllTeamMember
  ModifierName = MAvatar_Bronya_00_Ultra_PowerUp
  LifeStepImmediately = true
  LifeTime = AQAR / hash235360596

S3 hash235360596 = SkillParam(Skill03, index=3)
```

The complete global definition separately contains `LifeTime=2`, consistent with P2's two-turn text; the installer still supplies its own typed lifetime input. Its OnStack writes `AttackAddedRatio` and `CriticalDamageConvert` from the injected ATK/CRIT payloads. It has no explicit `LifeStepMoment` in this definition. The actual consumers establish an ordinary combat buff, not a countdown used only for display. [S4]

P4 gives the direct behavioral discriminator: with both buffs on the same recipient in the same normal turn, and Resurgence deliberately excluded, Bronya's two-turn Ultimate buff spends a unit while Seele's buffed state does not. P3 explicitly corroborates the latter's independence from an extra action.

The supported reconciliation is that this Bronya grant counts the in-progress recipient turn, unlike the selected Asta/Seele grace cases. The explicit `LifeStepImmediately=true` is a source-facing distinction compatible with that result. Do not elevate the comparison into a universal truth table for every task carrying the token.

In particular, `Immediately` is not interpreted as executing `LifeTime := LifeTime - 1` at the instant the grant is created. The selected sequence contains no such explicit operation, and P4 describes the decrement after the recipient acts. Determining the native step flag/default implementation, or an exact callback-to-UI-frame boundary, remains separate from the usable ordinary outcome.

## 6. A controlled first-step model and distinguishing cases

The table below concerns fresh two-turn recipient-clock buffs, no refresh/cleanse/death, no extra turn and no inserted work at the expiry boundary. T0 is the recipient's already-running normal turn; the application occurs before its ordinary action. T1 and T2 are that same recipient's subsequent normal turns, not the next two combatants or two encounter cycles.

| Observation point | Asta-type application-turn grace | Selected Bronya Ultimate current-turn counting |
| --- | ---: | ---: |
| Just admitted during T0 | 2 | 2 |
| After T0's applicable end boundary | 2 | 1 |
| After T1's applicable end boundary | 1 | 0 / expired |
| After T2's applicable end boundary | 0 / expired | Already absent |

This is a model prediction derived from P1/P2/P4 and the distinct source grants, not a new Asta-versus-Bronya game recording. The P4 actual reported comparison was Bronya versus Seele, whose nominal duration differs. No test is invented by normalizing durations to two here.

For the ordinary recipient model, a buff granted *before* T0 begins has no already-running recipient turn to exempt: the next two completed recipient turns spend its two units normally. Current-turn grace must not be implemented conceptually as an unconditional instruction to skip the first future recipient turn regardless of installation time. P1's recipient duration and P5's explicit on-target-turn condition support this distinction.

A compact descriptive model for these covered turn-end cases is:

```text
at an applicable recipient-turn end:
  current remaining duration is unchanged
    if this is the exempted application turn for this effect
  otherwise spend one unit
```

This is not a recovered native algorithm or a blanket modifier default. The earlier condition includes an effect-specific policy and an actual recipient-turn context. Nominal duration stays two; an exempt current turn does not rewrite the skill parameter to three.

Two additional discriminators follow:

- Other characters taking their turns do not spend the recipient-timed buff merely because the provider has already acted. Parent/caster-timed effects from F06 have their own owner instead.
- Finishing an inserted Ultimate and finishing the surrounding normal turn are not interchangeable. P4 expressly distinguishes two effects within the same no-Resurgence turn. A rule that freezes all buffs whenever an Ultimate occurs cannot reproduce that report.

The exact position of queued Ultimates, follow-ups, control handling and expiry cleanup is outside this table. Do not equate a completed attack animation, `SkillPerformFinish`, every `OnAfterSkillUse`, and the recipient's final duration step.

## 7. Potency labels do not supply the first-step policy

The initial speed-grace contrast does not justify classifying all SPD buffs as exempt and all damage buffs as current-turn counting. P3's Seele state already supplies a damage-related counterexample. P5 is even more discriminating: Hanya's Talent DMG buff is described as effective before the triggering attack and nevertheless exempt from spending duration on that acquisition turn.

Thus already benefiting from the current attack is not a sufficient rule for deciding whether to decrement. This is not a balance argument about what a buff ought to do; it is a difference in described behavior. The same caution applies to an effect containing both ATK and SPD, as in P5's Ultimate.

These public counterexamples prevent an unsupported generic classifier; they do not expand this pass into raw Hanya/Seele kit completion. Their individual configuration and reapplication paths remain separately attributable work.

## 8. Delayed installation is a different mechanism

Within the already inspected S3/S4 source, the selected Bronya Rank02 branch gives a useful timing contrast without another character search.

```text
Bronya_00_Skill02_Others_Phase02
  -> ByRankActivated(hash523552506)
  -> AddModifier(AbilityTargetEntity,
       MAvatar_Bronya_00_BPSkill_Rank02_Listen)
  -> inject Bronya_SpeedUP_Ratio_01 from hash-253973695

S3 hash-253973695 = SkillRank(Rank02, index=0)

MAvatar_Bronya_00_BPSkill_Rank02_Listen.OnAfterSkillUse
  -> AddModifier(ModifierOwnerEntity,
       MAvatar_Bronya_00_BPSkill_SpeedUp,
       LifeTime=1,
       Bronya_SpeedUP_Ratio from working hash-308080954)
  -> RemoveSelfModifier

MAvatar_Bronya_00_BPSkill_SpeedUp.OnStack
  -> StackProperty(ModifierOwnerEntity, SpeedAddedRatio,
       receiving working hash1596249176)
```

P2's Quick March text states that the speed effect is obtained after the target takes action. The listener has an action-delay preview configuration but no StackProperty speed grant; the actual live property write belongs to the later modifier. Therefore the selected path cannot be described as applying this speed buff immediately with Bronya's Skill and merely delaying its first decrement.

`OnAfterSkillUse` is the literal authored event. Its callback has no additional skill-category predicate; do not silently insert one while quoting the source or extrapolate all unusual inserted-action interactions. Likewise the eventual speed modifier's omitted first-step field does not alone prove its exact expiry behavior.

This branch closes the distinction between pending installation and an already-active exempted timer. It does not solve every expiry boundary for that one-turn speed effect. Its Rank02 flag is an activated battle effect; how the account acquired it is irrelevant.

## 9. Claim matrix and precise remaining questions

| Claim | Evidence basis | Limit retained |
| --- | --- | --- |
| Asta recipient speed grant, typed lifetime, live property and omitted first-step token | S1/S2 | No inferred native omitted-field default or newly read numeric skill row |
| Bronya Ultimate grant, explicit first-step token, lifetime input and live properties | S3/S4 | The flag evaluator and unspecified lifecycle defaults are not exported by these occurrences |
| Asta current-recipient-turn grace | P1 with the S1/S2 grant | Public explained behavior, not new gameplay testing or all-buff default |
| Bronya application-turn counting versus a non-counting buff on the same actor | P4, qualified by P2/P3 and S3/S4 | First-person report without our replay; incomplete client/build/initial-state metadata |
| Current application turn and first future turn are different cases | P1/P5 plus the stated controlled recipient model | Exact phase-edge/queued-action arbitration remains open |
| Damage buff can both benefit now and retain duration | P3/P5 | Public supporting contrasts, not raw coverage of those entire actors |
| Rank02 listener -> later one-turn speed effect -> listener removal | S3/S4, P2 description | No claim that all OnAfterSkillUse events have identical natural-turn consequences |
| Whole FG-02 / W07 / W09 / W10 completion or local runtime correctness | Not claimed | Further clock families, interaction and source-coverage obligations remain |

The useful remaining questions are narrower than first-step behavior being wholly unknown:

1. On reapplying the same effect during an existing timer, is application-turn exemption recreated, preserved or consumed? `ReplaceByCaster` and fresh-installation examples alone do not decide this.
2. Which exact recipient-turn context is used when application occurs inside a turn-start/end callback, a queued Ultimate, an extra action or a parent-clock transition?
3. How do an explicit task flag, a definition's lifecycle configuration and an omitted value combine for other source families? Keep actual serialized values and effect-specific behavior separate.
4. When a timer reaches zero alongside queued work, which effects still observe its properties before removal? The present ordinary end-boundary table is not a global ordering theorem.

Do not expand this list into generic scheduler recovery. A directly described or observed rule can close a behavior question even while its native implementation remains unavailable.

## 10. Delivery and stopping point

The selected first-step slice is a bounded research result: current-turn counting, current-turn grace, future-turn counting and pending installation now have separate explanations and replayable evidence. It advances FG-02 without declaring every lifetime mechanism closed. FG-01 remains phase-concluded for its ordinary chain with explicitly parked residuals, not erased.

The most discriminating continuation inside FG-02 would be one same-effect reapplication before its first eligible decrement, holding the recipient/action category fixed. Start it from a concrete report or source mutation; do not infer its answer here or simultaneously open all extra-action, control and periodic-effect branches.

Repository validation is manual pin/blob/occurrence and content/diff/head/Draft review. External descriptions and reported observations are recorded with their actual strength; all timeline tables here are predictions. No game session, simulator, Direct, test suite or workflow is invoked. No runtime/lowering/IR/tests/CI, broad W checkbox, mode scope or TBGD pin changes; no new C/D/E is claimed. The integrated review's current navigation is updated without rewriting historical primary evidence.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Asta_00_Config.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Bronya_00_Config.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Bronya_00_Ability.json
[P1]: https://hsr.keqingmains.com/asta/
[P2]: https://hsr.keqingmains.com/bronya/
[P3]: https://hsr.keqingmains.com/seele/
[P4]: https://www.reddit.com/r/HonkaiStarRail/comments/17dm2ot/buff_durations_are_confusing_claras_buff_counts/
[P5]: https://hsr.keqingmains.com/hanya/
[FG-01]: break_transition_hit_super_break_accounting_v1.md
