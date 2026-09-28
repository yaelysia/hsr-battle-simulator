# Multiple shields: parallel absorption, effect ownership and pre-hit eligibility v1

## Current continuation — top-up target selection and balance sampling, 2026-09-28

Section 10 continues from `53cfdb35a979f113bc1edeef302b9170956bfce0` / checkpoint `5862671994`. It distinguishes actor-level Shield selection from named-shield balance reads, traces selection before the party grant and a fresh balance read before the marked extra grant, and separates CurrentHP from HPRatio in the unshielded branch. These are new selected source/behavior distinctions, not another parallel-absorption overview or a claim to have resolved shield-cap changes. Sections 1-9 retain the first-pass record and its provenance.

## 1. Decision and bounded result

Reviewed 2026-09-28 from evidence parent `23ae6e26fea5744ca7a746b28044ab6524e3e61d`, following checkpoint `5862417895`. Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 is open/Draft, docs/evidence-only.

At the user's request, stop pursuing the lethal-hit Energy edge for now and reassess the common-mechanism directions. **Select the shield-pool part of FG-05, not its separate immunity-charge arbitration question.** The result is an ordinary parallel-absorption model with explicit public provenance, plus a newly traced fixed-pin counter eligibility/marker/consumer chain. It distinguishes three things that a single shield number cannot represent: remaining absorption, effects belonging to one named shield, and consumers accepting any Shield flag.

The source increment is not another shield-formula overview. March's actual counter listener samples shielding at `OnBeforeBeingAttacked`, marks the attacker, and uses that mark at `OnAfterAttack` to request the inserted counter. It does not test for March's own shield at that later request. Existing named-shield amount and cleanup facts are explicitly reused, not counted as new discoveries. No game, simulator or test was run.

## 2. Direction review

This is a priority review of the current [integrated residual map][REVIEW], checked against [F04][F04], [F01][F01], the [ordinary-monster record][MONSTER], the [March record][MARCH] and the latest checkpoint. It is not a fresh audit of every F01-F10 upstream chain or a source census. The ordering is a research judgment, not empirical scoring.

| Direction | Present leverage and constraint | Decision this round |
| --- | --- | --- |
| FG-01 ordinary Break/Super Break | Its ordinary chain is phase-concluded; remaining transport/interleaving exceptions need a new discriminator | Retain results; no repeated scan |
| FG-02 modifier first step and clocks | User-paused; Bronya caution remains unresolved | Remain paused; no clock or refresh investigation |
| FG-03 property sampling and inherited context | Important, but needs a selected stat-change/source-transfer contrast rather than a generic snapshot-flag survey | Keep as a later bounded candidate |
| FG-04 Energy and life-state transitions | Ordinary weighted input model exists; the latest continuation did not settle terminal-hit admission or preservation | Park the lethal edge without marking it solved |
| FG-05 shield pools / consumed protection | Parallel depletion has an explicit public explanation; existing named shield definitions and an actual attack listener provide discriminating source anchors | **Execute shield-pool/effect-ownership slice now; keep immunity arbitration separate** |
| FG-06 enemy final-property construction | Ordinary HardLevel inputs are known, but flat placement and Stage/Monster Elite conflicts require a carefully paired encounter example | High-value next candidate; not frozen merely because native code is absent |
| FG-07 secondary entities and target policies | Several independent synchronization, slot and attribution questions | Require one source-qualified question before expanding |
| FG-08 special damage / encounters / coverage | Useful but broad; a coverage list alone does not answer a common behavioral question | Retain explicit residuals; no unrestricted census |

The selection favors a question where the available evidence already distinguishes incompatible state models. Shield loss is not the disputed first lifetime decrement. Referring to a shield's own removal or a heal's holder does not reopen buff timing, lethal Energy or whole character kits.

## 3. Evidence register

### Fixed-pin source reads

All S paths use the unchanged TBGD pin. Names and complete blobs are the replay anchors; line ranges are navigation aids, not a claim to have audited unrelated contents.

| Ref | Read occurrence | Complete blob |
| --- | --- | --- |
| S1 | [March CharacterConfig][S1], `SkillP01` entry and SkillAbilityList; SkillP01 parameter bindings; file lines 1-435 | `614cbf345e7d0d7d39adb525a04fc4685b0f48f5` |
| S2 | [March Ability][S2], passive installation, teammate counter listener, attacker mark, inserted attack request/body and main-shield ownership; principal ranges 1740-2165, 2210-2825, 3340-3825 | `b9b4e3705a73cb691306d7e68912a7b33e597e94` |
| S3 | [Aventurine Ability][S3], `MAvatar_Aventurine_StackableShield` OnDestroy/OnStack, lines 5150-5570 | `67212a729fcfbae03093549b69194e6987968d6c` |

The ordinary March identity/skill chain, main-shield formula and rank-conditional inputs are reused from MARCH. F04 already maps Aventurine's named CurrentShield read, stack cap and effect cleanup. S3 is a targeted reread of those facts, not their first discovery. A default-branch search located March's passive name; every source claim below comes from the fixed-pin reads.

### Public semantics and provenance

Consulted 2026-09-28. Public version labels do not repin the raw data. These publications explain behavior; they are not newly executed measurements.

| Ref | Publication actually obtained | Use and limitation |
| --- | --- | --- |
| P1 | [KQM Fire Trailblazer guide][P1], Version 2.0 | Retained non-additivity of different shields, already used by F04; not by itself proof of every depletion callback |
| P2 | [Honkai: Star Rail Wiki, Shield / Shield Stacking][P2] | Retrieved indexed article text explicitly describes simultaneous depletion, highest remaining protection, and a smaller shield/status disappearing while another remains. Public compilation, not an isolated original experiment. Direct page opening failed; no page history, embedded media or experimental trace was inspected |
| P3 | [Purple Cat / 紫喵Azunya explanation reproduced by 17173][P3], displayed 2024-04-11, UID 100043850 | The readable authored text distinguishes accumulating Fortified Wager from parallel loss across different shields. It explicitly concerns the creator experience server and disclaims guaranteed live-server applicability; historical corroboration only, not an independent release-version test |
| P4 | [KQM March guide][P4], Version 1.5, Talent / E2 / E6 / Secondary Sustain | Other characters' shields can enable March's Talent, whereas E6 specifies the Skill shield; E2's distinct shield lacks the Skill's aggro benefit |

P2 is admitted as a clearly attributed ordinary public model, not as raw proof or new empirical validation. P3's preview context is retained rather than silently upgraded. Reproductions of P3 and translations of P2 are not independent confirmations. F04's bobrokrot mitigation-before-shield report is reused through F04; no linked video was replayed. P4 contains conflicting aggro/HP wording in other build paragraphs; those paragraphs are not used to redefine the already source-mapped application predicate.

## 4. Ordinary parallel absorption is not addition or a reserve queue

For one ordinary recipient and one damage instance, let `D >= 0` be the shield-eligible damage **after recipient mitigation**. Let `s_j >= 0` be each eligible shield instance's current remaining amount immediately before that damage. Assume no bypass, conversion, intervening grant or changing mitigation within this instance.

The P2 public model, consistent with P1's non-addition and P3's authored explanation, is:

```text
s_j_after = max(0, s_j_before - D)              for each eligible shield j
S_effective_before = max(0, s_1_before, ..., s_n_before)
HP_damage = max(0, D - S_effective_before)
prevented_HP_damage = min(D, S_effective_before)
```

These equations formalize the public rule; the generic native shield loop was not recovered. F04 supplies the already supported mitigation-before-absorption relation. The shield creator's DEF is not reapplied as the receiver's damage mitigation.

Every participating pool loses up to D. Damage is not divided among shields, and smaller pools are not held untouched in reserve behind the largest. Nevertheless HP is protected only once: summing the losses of all shield pools overcounts prevented HP damage. A displayed maximum can summarize immediate protection, but cannot replace the identities and balances of the underlying states.

### Calculated discriminators, not observed runs

| Setup with unchanged ordinary mitigation | Parallel-model result | Incorrect model distinguished |
| --- | --- | --- |
| Shields 1000 and 1500; damage 1200 | Remaining 0 and 300; HP loss 0 | Additive pool would leave 1300; largest-only depletion would leave the smaller 1000 untouched |
| Follow with damage 400 and no intervening grant | Both 0; HP loss 100 | An untouched smaller reserve would wrongly prevent this HP loss |
| Shields 600 and 1500; damage 200; then remove only the second shield before any next hit | Remaining first shield 400 | Discarding the smaller instance when the larger was added loses a real surviving state |
| Shields 1000 and 1500; one damage instance 1800 | Both 0; HP loss 300 | Two separate HP overflows of 800 and 300 must not be added |

For the first row, total pool loss is 2200 but prevented HP damage is only 1200. These values are arithmetic consequences of the stated model, not recorded UI readings, precision tests or source numeric rows. The removal example specifies a completed removal; it makes no claim about which turn decrements a lifetime.

## 5. An effect belongs to its actual shield or listener

### 5.1 Named shield benefits do not transfer to a surviving unrelated shield

S2 `GlobalModifiers.MAvatar_March7th_00_BPSkill_Shield` owns the main Skill shield. Its OnStack performs InitShield and contributes the injected AggroAddedRatio; its OnPhase1 contains the rank-conditional HealHP on ModifierOwnerEntity. OnDestroy calls RemoveShield and resets resilience. These are the same owner-backed surfaces recorded in MARCH, now used to distinguish coexistence consequences rather than to redo the shield equation.

P2 describes a depleted background shield losing its associated status/effects. P4 separately ties E6 healing to the Skill shield and says the distinct E2 shield does not grant its aggro increase. Therefore an unrelated surviving shield does not inherit the vanished Skill shield's aggro contribution or E6 heal. This is a public/source reconciliation about **which state supplies the benefit**, not recovery of the exact native zero-shield-to-OnDestroy instruction or its ordering against a simultaneous heal.

For the S3 contrast, the named stackable shield's OnStack contributes StatusResistanceBase. Its OnDestroy has an explicit cleanup list including `MAvatar_Aventurine_Rank01_Status`, the four shield-display effect names, `MAvatar_Aventurine_00_Skill02_BlackJack` and `MAvatar_Aventurine_00_ResistCtrl`, alongside RemoveShield and resilience reset. This is scoped cleanup authored by that shield; another shield is not a substitute parent for these benefits. Do not interpret the bare RemoveShield task as a newly proved command to erase every unrelated shield on the actor.

### 5.2 A consumer of any Shield flag is a different case

March's actual counter listener is **not** installed by the main Skill shield. S1 explicitly binds `SkillP01` to `Avatar_Mar_7th_00_PassiveSkill01` and lists the inserted counter Ability in that skill's AbilityList. In S2:

```text
Avatar_Mar_7th_00_PassiveSkill01.OnStart
  -> AddModifier(Caster, MAvatar_March7th_00_Passive)

that passive's OnStack
  -> AddModifier(AllTeamMember, MAvatar_March7th_00_BPSkill_Shield_Counter)

that passive's OnListenCharacterCreate
  -> require ByIsTeammate(ParamEntity)
  -> AddModifier(ParamEntity, same counter listener)
```

The passive's OnBeforeDying removes caster-added copies of this listener from its explicit target set. This is not the main shield's OnDestroy. The listener's name contains BPSkill_Shield, but its installation and actual predicate, rather than that name, establish its meaning.

P4's Secondary Sustain discussion explicitly permits shields supplied by Gepard or Fire Trailblazer to enable March's Talent. Thus the generic-shield interpretation has both an authored predicate and a public gameplay explanation, not merely a file-name inference.

## 6. New source chain: pre-hit eligibility, attacker mark, post-attack request

The complete selected S2 callback is:

```text
GlobalModifiers.MAvatar_March7th_00_BPSkill_Shield_Counter
  Event = OnBeforeBeingAttacked
  ByAnd:
    ByContainBehaviorFlag(ModifierOwnerEntity, Shield)
    ByTargetTeam(ParamEntity, TeamDark)
    ByCompareModifierValue(MAvatar_March7th_00_Passive_CanAttack, > 0)
  success:
    AddModifier(ParamEntity, MAvatar_March7th_00_BPSkill_Shield_Mark)

GlobalModifiers.MAvatar_March7th_00_BPSkill_Shield_Mark
  Event = OnAfterAttack
  TurnInsertAbility:
    AbilityName = Avatar_Mar_7th_00_PassiveSkill01_InsertAbility
    TargetType = Caster
    AbilityTarget = ModifierOwnerEntity
    AbortBehaviorFlags = [DisableAction, STAT_CTRL]
    InsertAbilityPriority = AvatarInsertAttackSelf
    ShowInActionBar = true
  RemoveModifier(ModifierOwnerEntity, same mark, OnlyRemoveCasterAdded=true)
```

The counter listener is on the protected teammate. It puts the mark on the incoming TeamDark entity. Consequently the mark's holder supplies the later counter target; it is not the protected teammate. The marked OnAfterAttack body has **no second shield-presence test** before TurnInsertAbility. The fixed source separates eligibility capture from reaction scheduling.

The inserted Ability's inspected attack body fires a projectile and issues DamageByAttackProperty to AbilityTargetEntity with AttackType=Insert. This confirms a combat request, not just an action-bar or EnergyBar display. S1 maps the ordinary damage parameter hash 1246667513 to SkillParam(SkillP01,0), and the counter allowance input 1299003598 to SkillParam(SkillP01,1). No unread numeric row or omitted SetModifierValue operand is decoded into a new universal quota rule here.

### Consequences and limits

For a surviving ally with sufficient counter allowance and an ordinary eligible attacker, shielding present at the **pre-hit callback** can author the mark even if that attack subsequently exhausts the shield. Replacing this source chain with an unconditional post-damage `hasShield` gate would discard its captured eligibility. This establishes the local request path; it does not guarantee that every queued counter executes despite control, attacker removal, death, or other intervening events. The explicit abort flags must be retained.

If March's own smaller shield has already disappeared while an unrelated ordinary shield remains, a later attack can still satisfy this generic Shield predicate. The Skill shield's own benefits and the independently installed Talent listener therefore have different persistence rules. Conversely, with no shield at the pre-hit callback, a shield obtained only afterwards cannot retroactively satisfy this inspected predicate.

The predicate is Boolean, not one iteration per shield. This callback does not author one counter per shield pool. Multi-target attacks, multiple pre-hit notifications, repeated marker application and quota reservation require their actual grouping/stacking semantics; this record does not invent those from the callback name.

S2 also has a separate `MAvatar_March7th_00_ListenEnergyBar` that scans for Shield flags on modifier-add/remove events. Those checks drive display state. They are not the battle-eligibility evidence above, an ordinary Energy transaction, or proof that every shield-change notification schedules an attack.

## 7. Accumulation remains local to the named shield

F04's already traced `Aventurine_RecordCurrentShield` reads CurrentShield specifically from `MAvatar_Aventurine_StackableShield`, with zero in the absent-name branch. It does not read the character's arbitrary visible maximum. The named definition then uses StackShield with its own stack-value/cap inputs.

The retained fixed-input accumulation model `min(own_remaining + new_grant, own_cap)` is therefore a separate update from section 4's parallel incoming-damage loss. An unrelated larger shield must neither donate its balance to this accumulation nor prevent the named smaller shield from being depleted. This is a joined consequence of the existing named reader and the public parallel model; the CurrentShield trace and stack cap are not new discoveries.

Changed creator stats, changed cap reconciliation, same-name replacement visibility and lifetime refresh are not settled by this combination. No buff first-step policy is promoted.

## 8. Claim accounting and remaining scope

| Claim | Result and authority |
| --- | --- |
| Different ordinary shields take damage in parallel, rather than add or form a reserve queue | Adopted attributed public model P2, with P1 non-addition and explicitly preview-scoped P3 corroboration; not newly measured or a native loop |
| HP overflow is calculated once against effective protection | Derived accounting under that public model; scenario arithmetic is not an experiment |
| A lost shield's named effects do not migrate to a different shield | P2/P4 semantics reconciled with S2/S3 ownership; exact zero-to-destroy timing remains separate |
| March's actual Talent listener accepts any Shield flag | New S1/S2 registration and predicate chain plus P4's other-provider examples |
| Shield eligibility is captured before the incoming attack; the later attacker-mark consumer requests the counter without a shield recheck | New complete selected S2 callbacks; request eligibility is not unconditional execution |
| Existing Aventurine carry/stack/cleanup and March base formulas | Explicit reuse, not a new raw discovery |
| All FG-05/F04/W05 mechanisms, immunity arbitration or backend correctness | Not claimed |

The remaining shield questions are specific: generic depletion-to-destruction/event visibility for arbitrary consumers, special bypass/shared-shield families, changed-cap/replacement cases, and notification/grouping semantics across multi-hit or multi-target attacks. The ordinary parallel model and the selected pre-hit/mark/post-attack chain are usable without waiting for every native body. Do not reopen a broad shield-formula survey to answer these residuals.

Lethal Energy is parked, not resolved. Buff timing remains paused with its existing caution. The ordinary Break/Super Break chain remains phase-concluded. A future new source or isolated observation may justify revisiting a parked question; another identical search is not the current task.

## 9. Publication and actual validation

Publish this record and the integrated review's current-focus overlay only. Preserve prior evidence, TBGD pin, broad worklist checkboxes and mode boundaries. The checkpoint records the actual commits, cumulative diff, immutable content readback and final PR head/Draft state.

Actual validation here is manual fixed-pin source reading, consumer/recipient/event comparison, attributed public-text review and calculated accounting. No game session, simulator, automated test, CI workflow or local implementation was run. Failed page/media retrieval is not a passed experiment; no inaccessible image or video is reported as inspected. No runtime, lowering, IR, tests or CI configuration is changed, and no backend repair dependency is introduced.

## 10. Continuation: top-up target selection is not the shield balance snapshot

Reviewed 2026-09-28 from `53cfdb35a979f113bc1edeef302b9170956bfce0`, after checkpoint `5862671994`; startup and pre-write PR reads matched that head and open/Draft state. The selected question is how an automatic party shield plus one additional grant chooses its recipient and preserves the correct pool balance. It advances FG-05 with a bounded F09/F01 sampling contrast, not a complete Aventurine kit or a return to modifier clocks.

### 10.1 Additional evidence and reuse

| Ref | Exact read / role | Identity and limit |
| --- | --- | --- |
| S3 | InsertAbilityPhase02 PointB3 installer; complete SkillTree03_Trigger callbacks; ShieldMark definition; RecordCurrentShield template | Same blob `67212a729fcfbae03093549b69194e6987968d6c`; replay ranges 1800-2000, 5430-6250 and 6340-6508. Selection/grant sequencing is new; named carry and StackShield existence are reused |
| S4 | [Aventurine CharacterConfig][S4], SkillP01 membership and typed PointB3/Skill02 bindings, lines 250-620 | Blob `092c497b64e381ac3e49f6bfc3198d755e7e326f`; no new pinned numeric-row extraction |
| S2 | March Rank02_Shield_pre selected Retarget, lines 3250-3340 | Same March blob; minimal contrast between PropertyRatioType=HPRatio and S3's PropertyType=CurrentHP, not new E2 kit research |
| P5 | [Star Rail Station's reproduced Bingo! skill text][P5], consulted 2026-09-28 | Describes a party grant plus an extra grant to the lowest-shield ally, both 7.2% DEF+96. Description semantics, not an original experiment or same-pin localization/numeric join |
| P4 | KQM March E2 description, Version 1.5, reread | Explicit lowest HP percentage corroborates S2's ratio selector; unrelated guide paragraphs remain excluded |

### 10.2 Entry, eligibility and two differently scoped readers

S4 lists `Avatar_Aventurine_00_PassiveSkill01_InsertAbilityPhase02` under SkillP01. In that execution body, `BySkillPointActivated(PointB3)` gates `AddModifier(Caster,MAvatar_Aventurine_SkillTree03_Trigger)`. Its `OnAfterAttackEnd` callback first reads Caster.Defence into MDF_CurrentDefence2, then selects the extra recipient before either shield grant.

The first `Retarget(AllLightTeam)` uses `ByAny` over these exact arms:

| Arm | Required flag state | ByIsPropertyValueMinOrMax input | Comparison population |
| --- | --- | --- | --- |
| A | ParamEntity does not contain Shield | PropertyType=CurrentHP | AllLightTeam filtered to entities without Shield |
| B | ParamEntity contains Shield | PropertyType=Shield | AllLightTeam |

The request has `ByRandom=true`, `MaxNumber=1`; its task adds `MAvatar_Aventurine_PointB3_ShieldMark` to ParamEntity. It does not compare `MAvatar_Aventurine_StackableShield.CurrentShield`, shield percentage, missing HP or Caster identity. The extra recipient is not hard-wired to Aventurine.

The minimum interpretation is a source/public reconciliation: P5 specifies lowest shield, and P4's independently identified lowest-HP-percentage selector uses the same predicate family with HPRatio. The occurrences do not serialize an explicit min/max switch; this record does not invent a literal default flag or claim to have recovered its native constructor. The **CurrentHP versus HPRatio distinction and the filtered comparison population are literal source facts**.

For ordinary living recipients with positive Shield values when the flag is present and zero when absent, the reconciled model selects a lowest-CurrentHP member of the unshielded subset when that subset is nonempty; otherwise it selects a lowest actor-Shield member. Equal candidates are subject to the authored randomized, at-most-one selection. No uniform probability, seed, first-slot tie-break or guarantee for zero-valued-but-still-flagged shields is established. The serialized union of arms, rather than an invented unconditional lowest-HP rule, remains the source authority.

By contrast, `Aventurine_RecordCurrentShield` checks the **named** stackable modifier and reads its `ValueType=CurrentShield`, then writes AventurineShieldValue in TargetEntity scope; the absent-name branch writes zero. The actor-level Shield used to rank recipients and this named-pool carry read are different operations. Under section 4's ordinary effective-shield model, an unrelated shield can alter the selection while contributing nothing to the named carry amount.

### 10.3 Capture the recipient early, reread balances later

The authored order within the complete selected callback is:

```text
read Caster.Defence -> MDF_CurrentDefence2
select extra recipient by the two-arm predicate -> add ShieldMark
IncludeTaskListTemplate(Aventurine_RecordCurrentShield)
AddModifier(AllLightTeam, MAvatar_Aventurine_StackableShield, party operands)
Retarget(AllLightTeam, contains ShieldMark, ByRandom=true, MaxNumber=1):
  IncludeTaskListTemplate(Aventurine_RecordCurrentShield)
  AddModifier(ParamEntity, MAvatar_Aventurine_StackableShield, extra operands)
Retarget(AllLightTeam): remove ShieldMark; separate display-state work
```

Both branches of the intervening named-shield-presence condition author the party grant; their lifetime inputs differ, but that condition does not restrict the party grant to the marked entity. No lifetime-step interpretation is added.

The second selection checks the mark, **not current Shield or CurrentHP again**. Meanwhile the named-balance template is called again inside that marked-target task list, after the party grant. Its body still traverses AllLightTeam and reads each named pool; it is not a read of the arbitrary displayed maximum. Thus recipient identity is retained while balance-read requests are renewed. Reusing one pre-both-grants balance snapshot or reranking recipients after the party grant would not reproduce this authored sequence.

The mark has `Stacking=ReplaceByCaster`. The normal callback explicitly removes it; the trigger modifier also has `OnInsertAbilityFinish -> RemoveSelfModifier`. These are local cleanup sites, not a universal nested-callback ordering, interruption-recovery or stale-mark guarantee. The template's existing working-slot/native carry boundary remains as recorded by F04; a fresh read request is not a recovered generic StackShield implementation.

### 10.4 Separate grant operands, one authored DEF read

S4 and the two S3 installers distinguish the inputs:

| Operand | Typed source / hashes |
| --- | --- |
| Party grant coefficient and flat | SkillTreeParam(PointB3,0/1): 1623238753 / -1198431344 |
| Extra grant coefficient and flat | SkillTreeParam(PointB3,3/4): 126518748 / 880721815 |
| Skill-sized MDF_ForceShield basis in both installers | SkillParam(Skill02,0/1): 583785975 / 1089505780 |
| MDF_MaxShieldRatio in both installers | SkillParam(Skill02,3): -1317091266 |

Both MDF_InitShieldValue expressions use `AQABAQQBAgIR` with the shared working DEF hash 995479797 followed by their own coefficient and flat hashes. The callback supplies one explicit Caster.Defence read before selection; the extra-grant task does not issue a second property read. This is selected read-site/operand evidence, not a claim that every shield or every property is permanently snapshotted, or that uninspected nested effects cannot change working state.

P5 supplies equal public amounts for these separately bound grant families. No unread AvatarSkillTreeConfig row is promoted by that equality. The source does not give one doubled grant to Caster: it authors a party grant and then a second grant to the marked recipient. Stored gains can still be capped. Shield-bonus participation in the cap and changes to cap/balance when DEF changes remain separate unresolved questions; no new cap rule is inferred here.

### 10.5 Calculated cases that distinguish the models

For an isolated ordinary calculation, use P5's described coefficient and flat amount with a supplied hypothetical DEF=4000 and no shield-generation bonus, so each offered grant is `0.072*4000+96=384`. Supply enough named-pool capacity to avoid all saturation below, no incoming damage/removal between steps, no stale mark, and two other living teammates with actor Shield values above 1500. These are deliberately constructed states and predictions, not game observations or pinned numeric rows.

| State | A: own Fortified Wager / unrelated shield | B: own Fortified Wager / unrelated shield | Consequence |
| --- | --- | --- | --- |
| Before selection | 0 / 1000 | 800 / 0 | Actor Shield is 1000 versus 800, so B is marked; ranking only own pools would incorrectly choose A |
| After party +384 | 384 / 1000 | 1184 / 0 | A now has the smaller effective Shield, but the existing mark remains on B |
| After marked extra +384 | 384 / 1000 | 1568 / 0 | B receives the second grant; post-party reranking would instead grant it to A |

The external 1000 is not added to A's named balance. The second grant uses the updated B balance rather than overwriting the first grant by reusing the original 800. This example simultaneously distinguishes actor-level ranking, named-pool storage, pre-grant target capture and post-party balance resampling.

For the unshielded branch, let A have HP1600/4000 and B HP1800/6000, with neither carrying Shield and all other teammates shielded. The minimum-CurrentHP interpretation chooses A even though B's HP percentage is lower (30% versus 40%). S2's March E2 HPRatio selector would prefer B under an otherwise matching unique-minimum comparison. This is an input-domain discriminator, not a new experiment or a general rule that every emergency shield targets absolute HP.

### 10.6 Result and publication boundary

New fixed-pin facts are the PointB3-gated installer, two-arm target predicate, pre-grant mark and post-grant mark consumer, repeated named-balance template calls, distinct party/extra parameter slots, and the selected DEF read site. The ordinary minimum/actor-protection interpretation has explicit description/model support; hypothetical values remain calculation-only. Existing parallel absorption, named carry and March's counter chain are not counted again as new discoveries.

Only this main record is updated; the integrated review already identifies this shield-pool direction and links here. No whole FG-05/F04/W05/F09 closure is claimed. Open edges include special/zero-valued shield states, exact RNG/ties beyond the authored request, interruptions or stale marks, native carry transport, shield-cap/DEF-change handling, and arbitrary depletion-to-destruction ordering. The cap route was not resolved by the acquired evidence and is not presented as the result of this continuation.

Repository access and publication use the GitHub connector. Validation is fixed-pin blob/occurrence reading, public skill-text reconciliation, scoped arithmetic, and commit diff/content/head/Draft checks. No game, simulator, automated tests or CI workflow was run or manually started; no skipped result is called passed. Runtime, lowering, IR, tests, CI, pin and broad coverage checkboxes are unchanged. Lethal Energy remains parked, buff timing paused, and the ordinary Break chain phase-concluded.

[REVIEW]: foundational_mechanics_gap_coverage_review_v1.md
[F01]: general_parameter_effective_property_semantics_v1.md
[F04]: general_healing_shield_hp_resolution_v1.md
[MONSTER]: ../monsters/monster_1002011_reference_chain.md
[MARCH]: ../characters/march_7th_preservation_skill02_shield.md
[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Mar_7th_00_Config.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Aventurine_00_Ability.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Aventurine_00_Config.json
[P1]: https://hsr.keqingmains.com/fire-trailblazer/
[P2]: https://honkai-star-rail.fandom.com/wiki/Shield
[P3]: https://news.17173.com/content/04112024/171802075.shtml
[P5]: https://starrailstation.com/en/character/aventurine
[P4]: https://hsr.keqingmains.com/march-7th/
