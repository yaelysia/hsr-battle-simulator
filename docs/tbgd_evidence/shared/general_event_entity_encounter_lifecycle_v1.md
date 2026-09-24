# General lifecycle: events, lethal recovery, entities and encounters v1

## 1. Scope and result

Reviewed 2026-09-24. Evidence parent: `adc555818592fd62556d4fc93d8be1bd020e79ea`; preceding checkpoint: `5809240856` (F09). Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains open/Draft and docs/evidence-only.

**F10 result:** distinguish installed listeners from eligible and executed effects; lethal recovery from completed death/removal; provider-owned rescue budgets from recipient markers; death-rattle work from explicitly muted cleanup; and an existing entity's phase change from new-wave creation or encounter completion. Shared stage graphs provide concrete birth/activation/entry and provisional-win/result/leave boundaries. Published skill descriptions establish the selected once-per-battle behavior without requiring a native dispatcher body.

The research unit is the common lifecycle, not a character kit. Gepard and Bailu discriminate self/other recovery and reactivation, while the already documented servant and stage graphs supply exit/phase/wave contrasts. W10 already records Bailu's staged revival and the servant death surfaces: rereading them is not a first discovery. This pass adds a unified rule map, detailed eligibility and execution rechecks, budget/marker separation, and reset-scope distinctions. F10/W10/W13/W16/W17 remain active for the precise residuals below.

## 2. Source register

All S paths are at the fixed TBGD revision. Named selectors are serialized occurrences, not guessed array indices.

| Ref | Path / inspected occurrence | Complete blob |
| --- | --- | --- |
| S1 | [Gepard CharacterConfig][S1]; SkillP01 entry, ActivateAfterRevive and typed recovery inputs | `9d15bb0e10a74b00fcc74a493a83fc7eae85db55` |
| S2 | [Gepard Ability][S2]; PassiveSkill01.UnDead, inserted recovery and the first-wave Technique listener | `19a1f1d53bbe311677ccf0e1ee7012e7674553fc` |
| S3 | [Bailu CharacterConfig][S3]; SkillP01 entry, inserted-Ability membership and recovery parameter slots | `e43961381a0dca5b30f9a89f31925dc247afe42e` |
| S4 | [Bailu Ability][S4]; DieEvent/ReviveEvent, Revive_Ready/Mark and InsertSkill_Revive | `24ec3e9dfe4bc00291367648f019b9ffb19d479d` |
| S5 | [StageCommonTemplate][S5]; OnStartSequece birth/activation, wave continuations and terminal listeners | `d76c3f1d8a2536da6a6f79e4bb44b79f48b91c5a` |
| S6 | [GlobalTaskListTemplate][S6]; Monster_ChangePhase, Wave_CommonPreProcess/Process and delayed creation | `d1da985fbac1bcf4e23f3c1dcdf7dfd11bcb5c96` |
| S7 | [Aglaea servant Ability][S7]; passive pre-death/state transfer, DeathRattle and ForceKill_Insert | `80cb71c2d1c5b166ec4726a1828497d8ca28d640` |

Replay ranges: S1 100-400; S2 1170-1900; S3 80-375; S4 1520-2115, 2350-2530 and the final Revive_Mark definition around3150 onward; S5 1-760 and1050-end; S6 1-380; S7 880-1410 and1660-2020. Full blob plus named occurrence governs if viewer line layout differs. Neighboring kit/presentation operations are not all included in this audit.

Reused evidence: [R6][R6] supplies the Stage103201/301001 table-to-LevelGraphPath relation and the selected stage listener; [the servant record][SERVANT] supplies Servant11402 identity, SkillP04-to-20-Energy input and the countdown caller of forced cleanup. [F06][MODIFIERS], [F07][RESOURCES], [F08][TIMING] and [F09][TARGETS] supply clock, owner, resource and target distinctions. Old local runtime projections and R6's SHA-bound fixture results are not TBGD authority or new validation here.

| Ref | Public semantic evidence | Accepted use and limit |
| --- | --- | --- |
| P1 | [KQM SRL Gepard skill publication][P1], Unyielding Will and Comradery | Lethal recovery instead of being knocked down; a fraction of his MaxHP; once per battle; Technique at the next battle. Description evidence, not a new experiment. |
| P2 | [KQM SRL Bailu skill publication][P2], Gourdful of Elixir and the extra-rescue Eidolon | Distinct Invigoration and killing-blow recovery, healer-MaxHP-plus-flat operands, baseline once per battle and an explicit extra-use exception. Not proof of every rescue conflict or native counter default. |

Both publications were read at `KQM-git/SRL@de0e5c09c8dbba9577367ad86e991fe91c4f0e36`, consulted2026-09-24. P1 blob=`036599ce95a588396ef6003d0264d60e67aa2c4f`; P2 blob=`0b434c0fd3aa2fea9a63b96d7f2affa87a4bc2c4`. Their revision is not the TBGD pin, and their copied skill text is not an independent gameplay test. No same-pin TextMap join or fresh numeric skill-row extraction is claimed. The related Gepard evidence page contained headings only; it supplies no empirical proof.

## 3. Lifecycle facts are not one boolean or one universal event list

| Dimension | Concrete source discriminator | Incorrect collapse |
| --- | --- | --- |
| Definition versus activation | EntryAbility/membership, then OnStart AddModifier | A registered Ability has already executed every callback |
| Listener versus eligible trigger | Event plus HP, source, control and budget predicates | Every instance of the event causes the effect |
| Request versus execution | TurnInsertAbility, precheck/abort inputs and the inserted body's recheck | Enqueueing is the completed heal or accepted global ordering |
| HP versus life state/presence | HP<=0, Mask_AliveOrLimbo and explicit recovery operations | Zero HP immediately means a removed, inaccessible entity |
| Recovery versus death work | OnLimboWaitHeal versus OnBeforeDying/OnDeathrattle | Every colloquial revive is the same completed-death reversal |
| Removal versus result | RemoveModifier/ForceKill versus stage result gates | One disappearance or cleanup event proves victory |
| Reset scope | Instance, provider quota, wave, phase and battle | Every entry/wave callback starts a fresh battle |

These are evidence dimensions, not a proposed backend schema or a reconstructed universal GameCore state machine. A condition, explicit call/continuation or emitted-and-waited string can establish a local dependency. Similar callback names, neighboring array entries in different listeners or numerical priorities in unrelated domains cannot establish a universal total order.

## 4. Self lethal recovery: eligibility, reentry and amount are separate

S1 binds SkillP01 to `Avatar_Gepard_00_PassiveSkill01`, includes `Gepard_00_PassiveSkill_1_Insert`, and explicitly sets **ActivateAfterRevive=false** for that passive entry. This is a real reactivation-policy input, not a rule that every passive always restarts after recovery.

S2's passive OnStart installs `MAvatar_Gepard_00_PassiveSkill_UnDead` on Caster. The local definition has literal Count1. OnCreate defines target-scoped controller/success working values and sets a talent-ratio working value; it also displays a one-use icon. The display is not the authorizing count, and omitted ResetValue fields are not quoted as literal zero assignments.

The trigger is specifically:

```text
UnDead.OnLimboWaitHeal, Priority=-80
 -> controller _Gepard_00_PassiveSkill_InsertController == 0
 -> ModifierOwnerEntity HP <= 0
 -> success marker = 1; DispelStatus(OnlyAlive=false)
 -> TurnInsertAbility(Gepard_00_PassiveSkill_1_Insert)
      InsertAbilityPriority=AvatarReviveSelf
      OwnerAliveState=Mask_AliveOrLimbo
      CanRunOnUnselectableTarget=true
 -> controller = 1
```

The controller addresses repeated insertion during the pending recovery, while the count and P1's once-per-battle wording address lifetime use. They are not interchangeable limits. This path is not a normal player-selected heal on an already removed target. P1's immediate recovery describes the gameplay consequence; it does not mean the source has no insertion or presentation steps.

The inserted body reads Caster.MaxHP and calls **SetHP**, not HealHP. Its ModifyValue expression is `AQABAQECAgQR`, hashes `[-1596688819,-330553393,-1179058669]`: the working MaxHP times the sum of the talent and Rank06 ratio inputs. S1 identifies the latter reads as SkillParam(SkillP01,0) and SkillRank(Rank06,0). P1 supports the baseline fraction-of-own-MaxHP interpretation. The inactive-rank resolver and internal HP/state promotion are not recovered by this expression.

Separate rank/trace branches request extra action or Energy. They are not automatic consequences of SetHP and are already timing/resource contrasts, not new kit-completion work. The later `SetModifierValue(UnDead,ModifyFunction=Add)` omits Value and ValueType; do not fabricate an explicit -1 or a default evaluator. Count1, the update site, ActivateAfterRevive=false and P1 support the selected single-use recovery model while that exact native counter operation remains separately unidentified.

## 5. Other-recipient rescue: one provider budget, several readiness markers

### 5.1 Installation is not one independent charge per teammate

S3 identifies the passive and separately registered inserted recovery. S4's passive initializes MDF_ReviveTime to literal1 in the no-override branch, with an explicit alternative adding1 to a rank input. It installs an empty-body `MAvatar_Bailu_00_ReviveEvent` on Caster with Count supplied from that working budget, and a separate `MAvatar_Bailu_00_DieEvent` listener.

The empty ReviveEvent definition is not proof of no state: its installed instance carries a Count used by the surrounding graph. Conversely the UI's copied current/max values do not create extra charges.

DieEvent.OnStack installs `MAvatar_Bailu_Revive_Ready` on **AllTeammate.RemoveServant**. Its TeamLight-qualified OnListenCharacterCreate repeats that group installation, not a quota reset. The listener does not grant a new budget merely because another entity appeared. The explicit source selector excludes servants for this path; do not generalize the exclusion to every possible revive effect.

### 5.2 Two event stages and repeated eligibility checks

The previously known W10 shape is now read with its actual conditions:

```text
Revive_Ready.OnBeingLimbo
 -> ReviveEvent value > 0
 -> holder HP <= 0
 -> holder is not Caster
 -> Caster HP > 0
 -> Caster has neither STAT_CTRL nor DisableAction
 -> AddModifier(holder, Revive_Mark, AliveOnly=false)

Revive_Mark.OnLimboWaitHeal, Priority=-70
 -> controlled/disabled Caster: RemoveSelfModifier
 -> otherwise request Avatar_Bailu_00_InsertSkill_Revive
      executor=Caster; AbilityTarget=ModifierOwnerEntity
      TargetAliveState=Mask_AliveOrLimbo
      AbortBehaviorFlags=[DisableAction,STAT_CTRL]
      InsertAbilityPriority=AvatarReviveOthers
      PreCheck=AbilityOwnerInsertUnusedCount, Count=hash963991070
```

Inside the second callback, the holder-HP check guards the Limbo animation; the insertion request is outside that inner HP branch. The actual heal is protected by the **inserted body's own** HP<=0 check. Do not conflate those scopes or infer a native claim-reservation algorithm from PreCheck's name.

When that execution-time check succeeds, the body updates the Caster's ReviveEvent, then issues an eligible-target cleanse and `HealHP(AbilityTargetEntity,AliveOnly=false,HealByHealerMaxHP)`. S3 maps percentage677042698 to SkillP01[2] and flat1314703783 to SkillP01[3]. These are the rescue operands, not Invigoration's separate indices0/1. No Invigoration-mark prerequisite appears in the inspected readiness/mark gates, consistent with P2 separating the two effects.

If the target is already above zero when the inserted body evaluates its outer predicate, its guarded budget update and heal do not run. This is a concrete duplicate-recovery discriminator, not a claim about which of several simultaneous rescue providers wins. The two displayed callback priorities and insertion classes do not by themselves close that conflict.

### 5.3 Exhaustion, provider loss and reset scope

The successful body removes the target's Revive_Mark and updates the remaining-budget display. Its `SetModifierValue(ReviveEvent,ModifyFunction=Add)` again omits Value/ValueType; exact default arithmetic is not asserted. P2's single-use wording and the shared Caster budget explain the ordinary baseline as one rescue per battle, not one per marked ally.

DieEvent.OnBeforeDying removes readiness and pending marks from the stated team/unselectable target set. A separate mark-removal listener checks whether Caster still has ReviveEvent before removing remaining readiness. These are provider/availability dependencies, not a universal wipe of every unrelated buff.

Under the selected no-extra-use public model, a used quota remains used through another wave of the same battle. A wave transition, a new teammate notification, or reappearing UI does not authorize replenishing it. P1 gives Gepard the same per-battle limit, while S1 separately disables passive reactivation after revive. Cross-battle initialization, restart and unusual revival/entry variants require their own sources; the ordinary reset scope is nevertheless known.

## 6. Death-rattle, selective carry-over and muted cleanup

S7 retains distinct pre-death and destruction work on `MServant_AglaeaServant_Passive`. Under the named trace condition, pre-death work reads the servant's speed-stack state and stores a summoner-held carry state. Later passive installation can read that specific state, apply its bounded stack amount and remove the carry state. Other owner-linked modifiers have explicit removal operations. This is selective persistence, not preserve-all or clear-all across every departure/recreation.

The formal `MServant_AglaeaServant_00_DeathRattle` has BehaviorFlag Deathrattle and `OnDeathrattle -> ModifySPNew(CasterSummoner,AddValue=hash-2017292130)`. The existing servant record closes that input to20, and F07 supplies the Energy identity. The installation/definition is not evidence that this callback executes on every kind of disappearance.

The separate, already documented countdown caller requests `Servant_Aglaea_00_PassiveSkill01_ForceKill_Insert`. Its reread body explicitly authors:

```text
ForceKill(Caster, MuteHpChange=true, MuteAllTriggerDeath=true)
 -> SetDieImmediately(Caster)
 -> named summoner-state removal
 -> separate disappearance effects and visibility changes
```

Pre-death cleanup can also ForceKill a still-valid countdown BattleEvent with the same mute flags. The force-kill target there is the countdown, not the servant. Preserve both target identities instead of charging every cleanup to an enemy kill.

The raw mute flags distinguish these requests from an ordinary lethal hit. They do **not**, without a mapped consumer or matching observation, prove exactly which death, disappearance, death-rattle or resource callbacks are suppressed. This pass therefore neither awards nor cancels the20-Energy effect solely from that flag name. Visual hiding, entity death, callback muting and dependent-state removal remain different facts. No universal death-event total order is declared.

## 7. Phase, wave, entity creation and battle are different scopes

| Transition | Source-supported effect | No automatic implication |
| --- | --- | --- |
| Existing entity phase reset | Monster_ChangePhase operates on Caster's HP, stance and a custom-event marker | Allocate a new enemy, advance wave or reset all player quotas |
| New-wave creation | WaveMonster plus table/timing context, bindings and explicit passive activation | Restart the encounter or refill every per-battle effect |
| New allied entity notification | Selected listeners can install effects on eligible members | Every listener repeats all initialization or grants a new budget |
| Encounter result/leave | Guarded result write and leave callback | Every death or removed modifier is a victory |

S6's Monster_ChangePhase includes ExitBreakState, SetHP(ModifyRatio1), ResetStance, SetStanceCount, then an explicit temporary `MMonster_Common_ChangephaseMark` around `TriggerModifierCustomEvent(BattleAllEntity.GetAliveOrLimbo,EnumIndex4,Value8)`. It finally removes that mark. The operations keep the same Caster reference. Neither the numeric event value nor the omitted SetStanceCount amount is assigned an invented default meaning.

The shared reset body does not contain a universal remove-all-modifiers step. Particular boss callers may add cleanup or reinforcements, so this does not establish all boss state persistence. A phase-animation switch alone is also not equivalent to this HP/stance reset template. R6's table/phase distinctions remain reusable without its historical backend sequencing requirements.

## 8. Shared stage graph: born, activate and enter are separate requests

R6's exact StageConfig examples point to S5. The inspected `OnStartSequece` list declares table-driven stage Abilities and pre-birth bindings, CreatePlayerTeam, then `WaveMonster(WaitDie=false,ForbiddenPassiveSkill=true)`. Later it requests `UsePassiveSkill(TeamDark)` and `TriggerModifierEnterBattle`, with born/character bindings and delayed-spawn handling at distinct authored sites before StartBattle.

This directly shows an enemy birth path whose passive activation is deliberately separated from creation. It does not recover every player/servant auto-entry mechanism or mean that no birth notification can run until UsePassiveSkill. R8's registration-versus-execution distinction remains important: a name in an Ability list is not an executed effect.

For the ordinary later-wave path, S5's emitted/waited Stage_Wave1End and caller-provided TriggerNextWave sequences link S6's two templates:

```text
Wave_CommonPreProcess
  pause; wait until no qualifying TeamDark dying entity
  -> WaitForTurnEnd(GoNextImmediately=true)
  -> fight-finished guard
  -> pre-birth bindings
  -> WaveMonster(ForbiddenPassiveSkill=true)
  -> UsePassiveSkill(TeamDark)

Wave_CommonProcess
  after-birth bindings; delayed-create template
  -> TriggerModifierEnterBattle
  -> DarkTeamDestroyCheck(ForWaveEnd=true)
  -> last-wave comparison
       last: wait turn end; emit Stage_PreLocalWin
       other: invoke caller's TriggerNextWave sequence
```

The dying check retains TeamDark and Mask_TeamCharacters; it is not an all-entity HP census. Logical waits and guards cannot be discarded merely because nearby tasks play BGM or wait for performance. Array order inside these task sequences describes authored control flow, not a measured global callback-completion schedule.

The delayed-create template has an explicit ByContainMonsterOnWave(CreateTiming=DelayCreate,AfterWave=true) gate and a WaveMonster request with an empty inline MonsterList. Table/timing context therefore matters; the empty list alone does not prove that no entity can be created. No new delayed-roster numeric row or spawning experiment is claimed.

Entry callbacks are requested on the later-wave path too. S2's Technique listener and S4's Technique listener explicitly gate their OnEnterBattle effect to wave1. Together with the next-battle descriptions, this distinguishes event dispatch from a once-at-start effect. Do not impose one lifetime frequency on every callback named OnEnterBattle, nor reset the rescue quotas merely because that event is dispatched again.

## 9. Provisional victory, result and leave-battle must not be conflated

S5's ordinary route checks dark-team destruction and whether the current wave is the final one before emitting Stage_PreLocalWin. A separate listener rechecks loss/trial conditions and the literal custom-string exception hash `-1148494254` before SetLocalWinFlag and Stage_WriteLocalWin. The hash's complete scenario meaning is not decoded or removed from the condition.

```text
Stage_WriteLocalWin  -> SetBattleResult(IsWin=true) -> TriggerModifierLeaveBattle
Stage_WriteLocalLose -> SetBattleResult           -> TriggerModifierLeaveBattle
Stage_ManualBattleQuit                           -> TriggerModifierLeaveBattle
independent listener: WaitAndProcessBattleResult
```

The lose-side SetBattleResult omits IsWin; it is not quoted as an explicitly serialized false. The surrounding lose route supplies its intended branch identity. Manual quit also requests leave callbacks without setting a win result in that listener. **A leave-battle notification therefore cannot be used as evidence of victory.**

Additional win/loss/trial predicates and an explicit infinite-battle branch prevent turning the ordinary last-wave route into a universal all-mode rule. The graph distinguishes a provisional completion signal from result publication; it does not settle every simultaneous-wipe, pending-insert or network/result-arbitration case. The last visible enemy reaching zero HP is not, by itself, the entire victory contract.

## 10. Discriminators and claim accounting

These are source-conditional or description-derived consequences, not newly observed game runs.

| Deliberately specified case | Supported consequence / limit |
| --- | --- |
| A passive is listed but its installing entry has not run | Listing alone does not prove an installed rescue listener or consumed charge |
| Gepard's eligible pending recovery is requested twice while its controller is1 | The inspected controller==0 branch excludes the second request; this is not the per-battle quota itself |
| Bailu's marked ally is above zero when the inserted body checks HP | That body's guarded budget update and heal do not execute |
| Bailu is controlled or has HP<=0 at the readiness check | The selected rescue mark is not installed; later abort/control checks are separate |
| A teammate lacks Invigoration but otherwise satisfies the selected rescue gates | That unrelated mark is not a prerequisite in this source path |
| Two eligible teammates have readiness while the baseline shared quota is one | P2 permits one rescue, not one per marker; the winning request/order remains unresolved |
| Wave2 starts after the described once-per-battle recovery was used | No new quota follows from the wave boundary alone |
| Monster_ChangePhase runs on an existing Caster | HP/stance reset and custom notification are not themselves a new-wave spawn |
| A leave-battle callback occurs | The surrounding win/lose/quit route is still required to determine the outcome |

| Claim family | Positive basis | Specific residual |
| --- | --- | --- |
| Lethal recovery is not arbitrary post-removal healing | S1-S4, P1/P2 and reused W10 shape | Native promotion/removal timing and other revival families |
| Reentry, pending guards and shared quota are separate | ActivateAfterRevive=false, Count/markers, source conditions and per-battle wording | Omitted counter-update defaults and simultaneous reservations |
| Eligibility and execution can be checked at different times | Ready/Mark conditions, insert abort/precheck and HP recheck | Cross-provider conflict and simultaneous hit/split/death arbitration |
| Natural death work differs from muted cleanup | S7's actual requests and reused servant input/caller | Exact muted-event set and departure-trigger outcomes |
| Phase, birth, wave and battle scopes differ | S5/S6, P1/P2 and selected late-member listener | Special restart, reinforcement and state-transfer variants |
| Result and leave are distinct | Guarded terminal strings, result writes, manual-quit leave | Scenario-specific precedence, settlement/replay and result processing internals |

Raw occurrences are manually confirmed; the selected behavioral interpretations are cross-validated with identified descriptions where stated, not with an invented experiment. No universal event census or full F10/W-package mechanism_closed is claimed. Remaining work includes exact callback/priorities across competing recoveries, buff/slot retention after each revival family, lifecycle consequences of direct/split HP loss, mute-flag semantics, late/delayed spawn participation and unusual terminal conditions. These questions can advance through readable source edges and credible observations; none requires a backend repair first.

## 11. Publication and next foundation

This checkpoint adds this record and updates the foundation roadmap and evidence README only. R6, W10 and the servant record remain historical/reusable evidence rather than documents silently rewritten as new discoveries. Seven exact-pin raw paths and two versioned public description files are registered. The empty external Gepard evidence page is not treated as testing; no linked video, same-pin localization or unread numeric table is claimed inspected.

Validation is manual source/description review, ownership/predicate/expression checks and Git diff/content/head/Draft verification. No runtime, lowering, IR, tests, CI, pin or broad W checklist changes; no game, simulator, Direct or workflow execution was invoked, and no local-runtime E or passing CI is claimed.

**Next primary foundation: F01 shared parameter and effective-property synthesis.** Reuse R0/R5 and F02-F10 to unify typed parameter families, description placeholders, working environments, base/flat/ratio/conversion/override inputs and effective-property ownership. Then assess the remaining common-rule gaps before deciding on systematic character completion; finishing the numbered first-pass records is not itself proof that the foundation pass is complete. F01 is not executed here.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Gepard_00_Config.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Gepard_00_Ability.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Bailu_00_Config.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Bailu_00_Ability.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/Level/StageCommonTemplate.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json
[S7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json
[P1]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/src/data/characters/Gepard.json
[P2]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/src/data/characters/Bailu.json
[R6]: encounter_spawn_phase_termination_v1.md
[SERVANT]: ../characters/aglaea_servant_11402_reference_chain.md
[MODIFIERS]: general_modifier_identity_stacking_lifetime_v1.md
[RESOURCES]: general_energy_skill_point_economy_v1.md
[TIMING]: general_speed_action_value_turn_clock_v1.md
[TARGETS]: general_target_selection_expansion_source_context_v1.md
