# Enemy-hit Energy: bounce weights, lethal hits and rescue confounders v1

## Current continuation — rescue-path Energy isolation, 2026-09-28

The continuation from `01d6b98d5588f3264b42d23a8901cab8459e2859` / checkpoint `5861793650` adds the targeted Bailu resource audit in section 10. **The ordinary lethal hit's final Energy award and death/rescue preservation remain unresolved.** New source facts separate the direct rescue body, its rescue-charge display, and an independently conditioned recipient Energy grant when Invigoration ends. They improve source isolation; they are not a yes/no answer to the lethal-hit question. The first-pass findings below are retained, and neither paused buff timing nor another character kit is reopened.

## 1. Scope and current result

Reviewed 2026-09-28 at evidence parent `a1e1304efa800321372ef74aed15206ef5054d18`, following checkpoint `5861348420`. Raw authority is `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains open/Draft and docs/evidence-only.

The user requested pausing buff-timing research and investigating Energy received from enemy attacks, including repeated bounce hits and the lethal hit. This is the enemy-hit portion of FG-04/F07/W08, with F09 targeting and F10 life-state distinctions reused only where necessary. The disputed FG-02 result is not a prerequisite and is not further promoted here.

**Bounded result:** the selected ordinary enemy supplies different Energy bases and hit weights for a single hit, a two-hit attack and a bounce attack. These support a recipient-specific weighted Energy model rather than one award per enemy action or a full award for every visual hit. A projectile's explicit pre-damage HP gate distinguishes an already-zero-HP landing from a hit that itself reduces HP to zero. **The final ordinary Energy award on that lethal hit is still unresolved.** A separately authored rescue-related refill must not be mistaken for evidence that the lethal hit awarded Energy.

The sample is Decaying Shadow / 蚕食者之影, ordinary template 8003040; an earlier conversational progress message misstated the Chinese name. No variant census, whole-character completion, progression, generic native scheduler reconstruction or local backend repair is part of this result. No game, simulator or test was run.

## 2. Evidence register

### Fixed-pin source reads

All S paths are relative to the TBGD repository at the pin above. Named objects and full blobs are authoritative; line ranges are replay aids.

| Ref | Source and selected occurrence | Complete blob |
| --- | --- | --- |
| S1 | [MonsterSkillConfig][S1], complete rows 800304002, 800304003 and 800304005; adjacent charge row used only to distinguish SkillTriggerKey | `b6cbf024dd00a13fee5578d0e3eca101d467a1e6` |
| S2 | [MonsterTemplateConfig][S2], MonsterTemplateID=8003040 and its JsonConfig reference | `cddb6b3d6d46ec12dc4c7a985190723aadbca57e` |
| S3 | [Monster_XP_Elite02_01_Config][S3], Skill02/03/04 entries, SkillAbilityList and SkillParam bindings | `7ac1e675c407e894b8a82c624a167ef615b453d7` |
| S4 | [Monster_XP_Elite02_01_Ability][S4], selected Skill02/03 Phase02 damage requests, Skill04 entry and projectile OnProjectileHit branch | `4ba3e2c9259bca78b636da5c13ed3afc11aa51a9` |
| S5 | [Gepard Ability][S5], Gepard_00_PassiveSkill_1_Insert, SetHP and separate PointB2 Energy branch | `19a1f1d53bbe311677ccf0e1ee7012e7674553fc` |

S3 was read through line360. Useful S4 ranges are900-1500,1400-1475,1460-2060 and2460-2820; the latter contains the complete selected non-waited projectile's HP predicate and successful damage body. This is not a claim that every projectile group or enemy variant was audited. S5 ranges1430-1765 contain the selected recovery and resource branch.

The large S1 path reader initially returned no usable content. Its returned blob was subsequently fetched and the actual decoded rows inspected. This is a retrieval limitation, not an empty-table or missing-export finding. No failed read is used as absence proof. Default-branch searches served only as navigation; all promoted S facts were read at the fixed pin.

### Public semantics and reused evidence

| Ref | Actually consulted source | Accepted role and limitation |
| --- | --- | --- |
| P1 | [Honey Hunter Decaying Shadow][P1], ordinary #8003040 skill list and linked [Liberation of the Golden Age][P1a] | Publishes the matching single-target10/15 and bounce5 Energy entries and skill descriptions. Data-site corroboration, not an independent gameplay experiment or proof of lethal-hit handling. Its live/beta revision labels are not the fixed pin. |
| P2 | [KQM beginner guide][P2], Energy Regeneration Rate and combat-screen Energy sections | Ordinary being-hit Energy is affected by the recipient's Energy Regeneration Rate. The guide contains legacy material; unrelated build advice and blanket claims about all resource sources are not adopted. |
| P3 | [KQM SRL Decaying Shadow JSON][P3] at de0e5c09c8dbba9577367ad86e991fe91c4f0e36 | Skill text describes successive random-target attacks, with count determined by remaining Gauge Recollection, initially nine. Blob `4d26097b4cc97f133a70413a6c2c00d74f57134a`; it does not supply the Energy numbers. |
| P4 | [KQM SRL Gepard][P4], Unyielding Will and Commander | Distinguishes lethal recovery from being knocked down and explicitly describes the separate talent-triggered refill to100% Energy. Published skill semantics, not a test of the ordinary lethal-hit award. |

Public pages were consulted on2026-09-28. Related data reproductions are not counted as independent empirical confirmations. No embedded video, claimed support response or linked unpublished spreadsheet was treated as inspected evidence. Searches for a directly isolated lethal-hit Energy observation did not yield a sufficient original trace in this pass; that is not proof that none exists.

[F07] provides the already accepted ordinary Energy-rate/cap model and its fixed/max-relative exceptions. [R4] identifies the resource-adjacent SPHitRatio surface without having resolved its meaning universally. [F10] already maps Gepard/Bailu staged rescue and their life-state predicates. This pass advances the selected enemy attack instances, not every occurrence of SPHitRatio in attack and healing tasks.

## 3. Three different quantities, not one SP field

Keep these separate:

- the enemy skill row's `SPHitBase`, interpreted here as the base for the victim's ordinary being-hit Energy;
- `SPHitRatio` on each actual damage request, providing that request's Energy weight in the reconciled model;
- the receiving character's Energy pool, applicable recovery rate, capacity and life-state-dependent admission.

A player's outgoing skill `SPBase`, its explicit `ModifySPNew(Caster,AddRatio=1)`, an on-kill grant and the victim's being-hit Energy are different sources. In particular, an Asta or Welt outgoing bounce-skill Energy figure does not establish the Energy awarded to a character hit by an enemy bounce. [F07][R4]

Likewise, S4's `EnergyLayer` is used by this monster's charge/projectile control. Skill04 copies it into `AccelerateLayer`, selects presentation/attack branches by those working values, and contains local decrement operations. The spelling Energy does not identify the playable recipient's Ultimate Energy. P3 supplies the charge-stack context; unrelated controller internals are not equated to the resource award.

## 4. Selected ordinary source chain

S2's template8003040 points to S3. The selected S3 Skill02, Skill03 and Skill04 entries explicitly select their Phase01 abilities and list the corresponding Phase02 abilities. The S4 entry bodies trigger those execution phases. Skill04's overall target configuration is AllEnemy with dynamic targeting, while its selected projectile chooses `TauntOrRandomEnemy`; a potential target set is not an all-target hit.

| S1 SkillID | Explicit SkillTriggerKey | SPHitBase.Value | S3 damage-coefficient binding |
| --- | --- | ---: | --- |
| 800304002 | Skill02 | 10 | -1847083384 = SkillParam(Skill02,0) |
| 800304003 | Skill03 | 15 | -56289053 = SkillParam(Skill03,0) |
| 800304005 | Skill04 | 5 | -190305622 = SkillParam(Skill04,0) |

These are read row values and explicit trigger keys, not guesses from ID suffixes: adjacent row800304004 actually uses Skill05. The selected skill-name hashes are7132209553960546852,17855634056918616142 and13716181518741922250 respectively. S1/S3/P1 jointly identify the selected skills; this pass does not audit every MonsterConfig variant override, native row-lookup precedence or same-pin localization string.

The damage-coefficient bindings above route HP damage, not the SPHitBase itself. Their existence does not supply a fabricated dynamic-hash binding for Energy. The native SPHitBase lookup and final Energy consumer are not exposed in these AttackData objects; the ordinary resource interpretation below uses the matching public values and the actual hit weights.

### Single versus two-hit requests

S4 Skill02 Phase02 has one selected `DamageByAttackProperty(AbilityTargetEntity)` request with `SPHitRatio=1`.

S4 Skill03 Phase02 has two such damage requests to AbilityTargetEntity. Each separately specifies `SPHitRatio=0.5`; each also carries half of the skill's damage coefficient. The two resource weights are explicit and need not be inferred from animation count or HP damage. Their ordinary weighted total is one skill base, not two. No universal equality of damage-split weights and Energy weights is inferred from this example.

### Bounce request

The selected Skill04 Phase02 branch contains:

```text
FireProjectile(TargetType=TauntOrRandomEnemy)
  OnProjectileHit
    require ProjectileHitEntity HPRatio > 0
    DamageByAttackProperty(ProjectileHitEntity)
      DamageType = Imaginary
      DamagePercentage = SkillParam(Skill04,0)
      SPHitRatio = 1
    ... separate status, presentation and charge-controller tasks
```

The actual damage receiver is ProjectileHitEntity. Do not give the entire party5 merely because the ability's outer TargetInfo says AllEnemy. Nor does the target alias prove uniform independent draws, prevent repeated targets, or establish fallback when a selected target becomes invalid. Those selector rules are not needed to compute the conditional Energy of a known landed hit sequence.

## 5. Reconciled ordinary Energy model

For the inspected nonlethal enemy-hit cases, with ordinary Energy admission and no special override, let b be the selected SPHitBase, w_h the actual request's SPHitRatio and r_i the receiving character's applicable recovery-rate multiplier. The supported working model is:

```text
nominal ordinary being-hit Energy for hit h on recipient i = b * w_h * r_i
r_i = 1 + applicable Energy Regeneration Rate bonuses
```

This is a source/public reconciliation, not a newly executed test or recovered native evaluator. P1 supplies the exact skill-value correspondence; P2/F07 supply ordinary recovery-rate semantics; S4 discriminates the weighted requests. Public labels alone do not prove every internal award timestamp, and the raw field's name alone is not the justification.

| Selected attack | Ordinary base input before rate/cap | Incorrect collapse avoided |
| --- | ---: | --- |
| Skill02, one valid nonlethal hit | 10*1 = 10 | Every enemy attack grants the same universal amount |
| Skill03, both half-weight hits valid/nonlethal on the recipient | 15*0.5 + 15*0.5 = 15 | Two visual hits necessarily grant30 |
| Skill04, one admitted nonlethal bounce impact | 5*1 = 5 | The entire bounce action grants only5 once |
| Skill04, the same recipient receives n such impacts | 5*n | Deduplicate all hits on one target to one award |

The7.5+7.5 split is an arithmetic interpretation of the read weights; it is not a recorded UI trace or a claim that fractional Energy is rounded after each hit. Exact settlement granularity remains separate from the weighted aggregate.

For a deliberately supplied hit sequence A,A,B,A, all ordinary/nonlethal, A receives base15 and B base5; C and D receive none from these impacts. With only A having a20% rate bonus, the nominal totals become18 and5. This does not estimate the probability of that target sequence or assume an RNG algorithm.

Actual stored gain also respects the recipient's remaining capacity under F07's ordinary model. A calculated5 with only2 capacity available stores2. A full pool can hide further grants; an action-total screenshot cannot by itself prove whether each hit produced an internal event. Mixed sources and cap changes need their own event-level accounting.

## 6. Already-zero HP is not the lethal crossing hit

S4's selected projectile tests HP **before** issuing its damage request. Consequently:

| Situation at that predicate | Source-backed consequence | What is not established |
| --- | --- | --- |
| HP ratio is already0 | The successful damage branch, including its SPHitRatio carrier, is not issued | Whether another selector or effect elsewhere retargets, awards Energy or revives |
| HP ratio > 0; the hit remains nonlethal | The request is issued; section5 supplies the ordinary model | Precise native/UI timestamp of its resource update |
| HP ratio > 0; this very hit reduces HP to0 | The precondition still passed and the request was issued | Whether ordinary being-hit Energy is awarded, canceled, deferred or retained through the ensuing life-state transition |

**The third row remains a real behavioral question.** Neither `SPHitRatio=1` nor the pre-hit HP check proves the final answer. A pre-hit condition is not a post-hit survival condition. Conversely, the already-zero-HP rejection does not prove that the terminal hit loses its award.

A later projectile landing on a still-zero-HP target and the earlier projectile that made it zero are therefore different cases. If rescue restores HP before a later predicate, that predicate may pass again; this conditional statement does not establish when rescue interleaves with projectiles or guarantee that they choose the same target.

The ordinary weighted model is not silently extended to death, special HP floors, force-kill, damage distribution, shield-only absorption, invulnerability or other nonstandard admission paths. A successful hit, a change in HP, a resource request and a usable Ultimate are distinct outcomes.

## 7. Rescue-related Energy can mask the terminal-hit result

F10 already distinguishes zero HP / pending rescue from final knockout. Its Bailu path contains a readiness event, pending mark, inserted rescue and an execution-time HP recheck. Those retained facts do not settle the ordinary resource award's ordering, and a queued rescue is not itself proof that the character survived the energy-admission step.

This pass rereads a concrete additional confounder in S5:

```text
Gepard_00_PassiveSkill_1_Insert
  ... SetHP(Caster, recovery expression)
  BySkillPointActivated(PointB2)
    SetDynamicValueByProperty(MDF_MaxSP, Caster, MaxSP)
    ModifySPNew(Caster, AddValue = single-hash read -1657931065)
```

P4 explicitly describes Commander as restoring Energy to100% when Unyielding Will triggers. Thus the recovery sequence has its own conditionally authored Energy source; it is not merely the enemy attack's SPHitBase arriving late. The raw AddValue request is preserved, not rewritten into an invented native SetEnergy command or a claim about its exact recovery-rate bypass.

**A full Energy bar after this rescue cannot discriminate whether the killing hit also granted its ordinary5/10/15.** With a refill and capacity limit, both grant and no-grant hypotheses can produce the same visible full bar. This is an identifiability argument from the separate source, not a new experimental finding.

Ordinary terminal-hit Energy, any preservation/reset on final knockout, the recovery operation and explicitly triggered bonus Energy must be recorded separately. No inference about all rescue abilities follows from this one refill path.

## 8. Precise discriminators for the still-open lethal branch

A useful follow-through must isolate the same enemy request on the same recipient at known pre-hit Energy and rate, with only HP changed to make the hit nonlethal versus lethal. Avoid capacity saturation and all unrelated on-hit, kill, rescue-refill or end-of-action Energy sources.

For a hypothetical5-Energy impact at ordinary rate1, initial Energy40 and ample capacity, the nonlethal model predicts45. The lethal alternatives45 versus40 are only proposed discriminators, not accepted outcomes. Observing a different post-rescue value is inconclusive until preservation/reset and rescue-specific additions are separately controlled.

Required observation points are: before impact; after the terminal damage/resource boundary if observable; before and after rescue or final knockout; and before any subsequent bounce. Record HP, life state, exact Energy where accessible, recipient, caps and all relevant effects. An ultimate-ready icon or aggregate animation number alone is insufficient.

A comparison with one surviving hit followed by a lethal hit also must retain the first award: a later death-related reset could hide earlier grants, not just cancel the terminal one. Likewise, availability of an inserted Ultimate is not a direct Energy measurement while a character is dead or awaiting recovery.

This is a research discriminator, not a request that the user perform a test or a report that we ran one. A properly scoped original report or a concrete source-side resource-admission/life-state consumer can settle it without reconstructing a universal scheduler.

## 9. Claim accounting and continuation

| Claim | Basis | Current boundary |
| --- | --- | --- |
| Selected10/15/5 bases and1/.5/.5/1 request weights | S1/S3/S4, matching P1 entries | Source-facing inputs confirmed; no variant census |
| Ordinary recipient-specific weighted totals and rate scaling | P1/P2/F07 reconciled with S4 | Adopted ordinary model; not new per-hit gameplay measurements |
| Already-zero-HP selected projectile does not issue the guarded hit | S4 complete selected predicate/body | Does not answer terminal-hit resource settlement |
| Lethal hit's ordinary being-hit Energy | Not resolved | Need award/life-state observation or concrete consumer; not inferred from a field name |
| Pending rescue is distinct from final knockout | Reused F10 | No newly recovered global event order |
| Gepard recovery has a separate conditionally authored Energy source | S5 and P4 | Full-bar recovery is not terminal-hit Energy proof |
| Buff first-step dispute | Paused at user's request | Existing caution retained; no further claim promotion |
| F07/FG-04/W08 whole-mechanism completion or runtime correctness | Not claimed | Lethal settlement, event granularity, special hit paths and coverage remain |

This is a bounded result on the ordinary base/weight distinction and the precise lethal boundary, not closure of the entire user question. The next high-value continuation is the isolated terminal-hit Energy award and preservation/rescue interaction, not another identical bounce-weight scan, a buff-timing detour or a backend repair card.

Publication consists of this record plus current integrated-review navigation and a checkpoint with actual head/diff/readback. Existing first-step and break records are unchanged. Validation is manual GitHub pin/blob/row/predicate review, attributed public-semantic comparison, labeled synthetic arithmetic and publication checks. No runtime/lowering/IR/tests/CI, TBGD pin, broad W checkbox or mode scope changes; no new C/D/E or passing test is claimed.

## 10. Continuation: distinguish the rescued recipient's Energy from rescue work

### 10.1 Additional source register

This continuation rereads the already reachable Bailu rescue family for its resource consequences. F10's rescue reachability is reused, not claimed newly discovered. S6/S7 remain at the unchanged TBGD pin; P5 is an external publication at its own immutable revision.

| Ref | Inspected occurrence | Full blob / evidence role |
| --- | --- | --- |
| S6 | [Bailu Ability][S6]: complete Avatar_Bailu_00_InsertSkill_Revive; selected Skill03 new-Invigoration branch; complete Heal_Mark OnDestroy; adjacent OnAfterBeingAttacked HP predicate | `24ec3e9dfe4bc00291367648f019b9ffb19d479d`; ranges1040-1460,1770-2140,2350-2845 |
| S7 | [Bailu CharacterConfig][S7]: SkillP01 rescue operands, SkillRank(Rank01,0), working declarations | `e43961381a0dca5b30f9a89f31925dc247afe42e`; range245-530 |
| P5 | [KQM SRL Bailu skill publication][P5], Gourdful of Elixir and Ambrosial Aqua | `0b434c0fd3aa2fea9a63b96d7f2affa87a4bc2c4` at `de0e5c09c8dbba9577367ad86e991fe91c4f0e36`; skill-description semantics, not a lethal-hit test |

### 10.2 The direct rescue body has no explicit Energy mutation

S6 `$.AbilityList[?(@.Name=='Avatar_Bailu_00_InsertSkill_Revive')].OnStart[0]` checks AbilityTargetEntity HP<=0. Its complete successful body updates the provider's rescue budget, requests presentation, cleanses and heals the target, updates the rescue-budget display, removes the pending rescue marker, and finishes its presentation work.

The healing request is `HealHP(AbilityTargetEntity,AliveOnly=false,HealByHealerMaxHP)`, with percentage677042698 and flat1314703783. S7 binds those to SkillP01 indices2/3. The direct body does not contain ModifySPNew, an explicit SP refill/reset, or a serialized SPHitRatio on that HealHP request.

This is a bounded absence claim about the inspected direct body, not about every task's native implementation, a called camera Ability, all heal listeners or all active equipment. It does not prove that the victim's ordinary lethal-hit Energy is canceled, that Energy is preserved through rescue, or that every possible side effect of HealHP is absent. P5 describes saving a target from a killing blow; it does not state a resource reset or lethal-hit award rule. An omitted energyGain field in published Talent data is also not quoted as an explicit zero.

The body contains `SetEnergyBarState(BarType=3)`, but its values come from `MAvatar_Bailu_00_ReviveEvent`, MDF_ReviveTime and MDF_ReviveTime2, with the passive icon. These operations update the rescue-charge display, not the rescued character's current Ultimate Energy. The preceding `TriggerAnimState(...Revive...)` likewise is not a documented SP-preservation instruction.

### 10.3 Invigoration's ending has a separate, conditioned Energy grant

S7 maps hash-1351111378 to `SkillRank(Rank01,0)`. In S6's `Avatar_Bailu_00_Skill03_Phase02.OnStart[5]`, the per-target branch for a missing Heal_Mark prepares MDF_Rank01_AddSP: the active rank branch reads that parameter; the inactive branch explicitly writes0. The installer injects MDF_AddSP through working hash-1177881702 into MAvatar_Bailu_Heal_Mark.

The corresponding consumer is:

```text
$.GlobalModifiers.MAvatar_Bailu_Heal_Mark._CallbackList[0]
  Event = OnDestroy
  require ModifierOwnerEntity HPRatio == 1
  require MDF_AddSP (ContextModifier) > 0
  -> ModifySPNew(ModifierOwnerEntity,
       FixedAddValue = AQAR / hash-636281976)
```

P5's first Eidolon explains the ordinary meaning: when Invigoration ends with the ally at full HP, that target receives8 extra Energy. The8 is the public description's parameter in this continuation; no new same-pin AvatarRankConfig numeric row or native hash algorithm is claimed recovered. This is a recipient grant, not Energy earned by Bailu for executing a rescue. Its FixedAddValue operand is retained separately from the enemy's SPHitBase/SPHitRatio route; no new universal ERR rule is derived here.

This grant is not automatic at every hit or every rescue. With the inspected inactive-rank injection0, its positive-value guard fails. With a non-full-HP holder at the OnDestroy evaluation, its full-HP guard fails. If HP is still0 at that evaluation it fails as well; the source does not thereby decide whether some later removal happens before or after healing. Neither this continuation nor the rescue body establishes that rescue itself destroys Invigoration. That causal edge must not be invented to make the extra8 occur.

The same Heal_Mark's OnAfterBeingAttacked callback separately requires holder HP>0 before its ordinary Invigoration healing and use update. This is an effect-specific post-hit survival condition. It must not be transplanted into the unrelated ordinary being-hit Energy evaluator. The ready-for-rescue listener, by contrast, tests HP<=0 at OnBeingLimbo. These opposed conditions help separate which effect is being examined; they do not supply the missing Energy admission predicate.

### 10.4 A cleaner discriminator, not a claimed experiment

A target rescued by Bailu without Invigoration, extra Energy equipment/effects, capacity saturation or subsequent hits avoids the explicitly identified Invigoration-ending grant and the Gepard refill. The already inspected rescue readiness does not require Invigoration. This makes it a more discriminating candidate, not proof of the eventual Energy result or proof of all indirect native side effects being absent.

An original observation must identify the **victim's** resource, not the healer's gauge or the rescue-charge icon. A comment that Bailu gained no Energy while rescuing someone does not answer whether the rescued character gained Energy from the lethal impact. Similarly, a post-rescue full bar or an unusable Ultimate button cannot alone resolve grant versus preservation.

The original one-baseline40->40/45 test is strengthened by two initial Energy values. For the same hypothetical5-base impact at rate1, capacities safely above65, no independent changes and otherwise matched setups:

| Hypothesis under those controls | Post-rescue results for initial40 / initial60 |
| --- | --- |
| Preserve Energy and award the terminal5 | 45 / 65 |
| Preserve Energy but omit the terminal5 | 40 / 60 |
| A reset/refill overwrites both histories to a fixed amount | The same value in both runs; terminal award may remain hidden |

These are competing predictions, not observed outputs or an exported execution sequence. An intervening refund, rate change, state-dependent reset or an extra ordinary hit can invalidate the simplified comparison. No user-run test is being assumed or requested by recording these controls.

### 10.5 What the continuation established, and where it stops

| Question | Result of this continuation |
| --- | --- |
| Does the selected Bailu rescue directly author a victim Energy refill/reset? | No such operation in the complete inspected direct body; indirect/native behavior remains separate |
| Is its SetEnergyBarState a victim-Energy write? | No; the operands and icon identify the rescue-budget display |
| Is there another explicit victim Energy source nearby? | Yes; the separately installed Invigoration-ending/full-HP/rank-parameter grant is mapped |
| Does Invigoration's HP>0 healing predicate decide ordinary lethal-hit Energy? | No; it belongs to a different effect and resource pathway |
| Does the terminal hit finally grant ordinary Energy, and is it preserved? | Still not determined by the acquired evidence |

Targeted public searches for lethal-hit awards and death/rescue Energy preservation did not yield a sufficiently isolated original trace. Skill descriptions and guides obtained explain rescue and its separately triggered grants, not the terminal ordinary award. Indexed forum comments about the healer's own gauge, other characters' alternate resources, and other rescue/version contexts were not promoted into that answer. No inaccessible video, preview text or repeated reproduction was counted as an inspected experiment. These search limits are not proof that a suitable public report cannot exist.

The continuation also checked the global constants/enum surfaces and a common departure/formation branch as navigation. Their names and presentation/formation operations supplied no concrete ordinary lethal-Energy consumer or reset assignment; they are not a corpus-wide absence result. This route should not be repeated without a new specific producer/consumer anchor.

The central unresolved edge remains `issued lethal damage request -> ordinary victim-Energy admission -> observed value through the particular life-state transition`. The new rescue audit removes specific interpretation hazards but does not close that edge. Further progress needs a directly relevant observation or concrete evaluator, not another character's generic rescue description. The ordinary bounce-weight model is retained; no whole FG-04/F07/W08 completion or backend acceptance is claimed. Buff timing remains paused.

Publication updates this existing main record only; the integrated review already links here and correctly identifies lethal settlement as open. Prior source findings remain intact. Validation is manual immutable-source reading, exact-predicate and resource-owner comparison, attributed skill-text reconciliation and Git content/diff/head/Draft checks. No game, simulator, tests or workflow is run; no runtime, lowering, IR, tests, CI, pin, mode scope or broad worklist checkbox is changed.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterSkillConfig.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterTemplateConfig.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Monster/Monster_XP_Elite02_01_Config.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_XP_Elite02_01_Ability.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Gepard_00_Ability.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Bailu_00_Ability.json
[S7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Bailu_00_Config.json
[P1]: https://starrail.honeyhunterworld.com/decaying-shadow-enemy/?lang=EN
[P1a]: https://starrail.honeyhunterworld.com/liberation-of-the-golden-age-monster_skill/?lang=EN
[P2]: https://hsr.keqingmains.com/misc/beginner-guide/
[P3]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/src/data/enemies/Decaying_Shadow.json
[P4]: https://srl.keqingmains.com/characters/ice/gepard
[P5]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/src/data/characters/Bailu.json
[F07]: general_energy_skill_point_economy_v1.md
[R4]: resource_economy_core_v1.md
[F10]: general_event_entity_encounter_lifecycle_v1.md
