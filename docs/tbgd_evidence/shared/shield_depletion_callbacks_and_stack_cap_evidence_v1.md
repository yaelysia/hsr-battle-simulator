# Shield depletion callbacks and changing stack caps: evidence v1

## 1. Scope and result

Reviewed 2026-09-28 from evidence parent `b811950b88d95c3309e634740bb27441933f09e1`, following checkpoint `5864174021`. Startup and pre-write reads agreed on that head and open/Draft/unmerged PR #8. Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`.

The requested questions are which coexisting ordinary shields lose value on one incoming damage instance, how depletion differs from removal notifications, whether shield-generation bonuses affect an accumulation cap, and what a changed cap does to an existing balance. This continues the shield-pool part of FG-05; it does not reopen immunity-charge arbitration, buff first-step timing, lethal Energy, the phase-concluded ordinary Break chain, or a complete character kit.

**New fixed-pin result:** an actual shield-related removal observer filters the callback's Shield classification and then recounts currently shielded teammates; it does not decrement a shield count once per removal. A separate refresh path removes and rebuilds a mixed combat/presentation companion modifier while using the named shield's carry/stack path. Consequently shield-value loss, destruction of one shield, removal of its companions, and the holder losing its last shield are not interchangeable events.

The ordinary parallel-loss arithmetic is reused from [MAIN], not newly discovered. For the cap question, this pass identifies an explicit bonus-inclusive public explanation and a contrary original guide, preserving their provenance and limitations. The inclusive expression is a preferred description-backed model, **not a resolved cross-source or newly measured fact**. New-cap handling when the existing balance already exceeds that cap remains undecided. No game, simulator or automated test was run by this investigation.

## 2. Source register

### Fixed-pin occurrences

[A] is `Config/ConfigAbility/Avatar/Avatar_Aventurine_00_Ability.json`, full blob `67212a729fcfbae03093549b69194e6987968d6c`. The same file supplied earlier findings, but the selected observer and companion-consumer chains below were not the previous result.

| Occurrence | Replay range | Role and evidence boundary |
| --- | --- | --- |
| Skill02_Phase02, complete selected remove/read/grant/rebuild sequence | 385-684 | Companion removal, new DEF read, named-balance template, shield reapplication, companion reinstallation |
| PassiveSkill01 entry and MAvatar_Aventurine_Passive.OnStack | 1550-1685; 2360-2495 | Passive installation and rank-gated installation of the removal observer |
| MAvatar_Aventurine_00_Skill02_ShieldEffect.OnStack | 3580-4215, with adjoining ranges read | Its rank-conditioned CriticalDamageBase write, status-name override and visual tasks; not presentation-only |
| MAvatar_Aventurine_Rank06 add/remove listeners and Rank06_Sub | 4860-5305, with adjoining ranges read | Callback-qualified Shield predicate, per-entity recount, capped property grant and zero-count removal |
| MAvatar_Aventurine_StackableShield.OnDestroy/OnStack | Named definition; earlier replay 5150-5570 | Reused cleanup and StackShield operands; not a newly recovered native shield loop |
| Skill02 and PointB3 grant operands, RecordCurrentShield | Skill02 range above; prior MAIN section 10 anchors | Reused named-pool storage and skill-sized cap basis; native working-value transport remains separate |

[AC], `Config/ConfigCharacter/Avatar/Avatar_Aventurine_00_Config.json`, blob `092c497b64e381ac3e49f6bfc3198d755e7e326f`, supplies the already registered SkillP01 entry and typed Skill02/Rank01/Rank06 parameter families. Those bindings are reused from the prior record; no new AvatarRankConfig or skill numeric-row extraction is claimed here. Names plus immutable blobs take precedence over viewer line layouts.

### Public evidence obtained this round

| Ref | Provenance actually obtained | Permitted use and limit |
| --- | --- | --- |
| P6 | [Azunya mechanism explanation reproduced by 3DM][P6], page credits 米游社 / 紫喵Azunya and displays 2025-09-03 | Explicitly says both individual Fortified Wager grants and its cap benefit from shield bonuses. Author-attributed explanation, not an inspected numerical experiment; page date is not a verified test/version timestamp |
| P7 | [小橙子阿 original TapTap guide][P7], V2.6, 2024-11-18, UID104802274 | Explicit contrary cap example: base1000, boosted grant1200, only800 further space. Kept as a contradiction, not silently omitted |
| P8 | [Creator-experience-server guide reproduced by 17173][P8], displayed 2024-04-14 | Retrieved indexed prose says the intended two-actual-grants cap includes bonuses, and attributes a contrary preview-video appearance to a preview-server bug. No video, native fix or live-version confirmation was inspected; this is a historical explanation lead |
| P9 | [疯狂马小艺 explanation reproduced by GamerSky][P9], 2024-04-11, credited to 米游社论坛 | Says a temporary Moment of Victory DEF increase raises the cap and that the shield amount does not immediately fall when the increase expires. Pre-release-dated assertion, not an isolated current/pin-matched trace; it does not state the next-grant overflow rule |
| P10 | [Honey Hunter reproduced Skill/Eidolon text][P10], consulted 2026-09-28 | Skill describes a cap at twice the current Skill shield; E1 ties its benefit to Fortified Wager; E6 counts shielded teammates. Description semantics, not independent measurement or a same-pin localization join |

P6 shares an author/wording lineage with the preview material already registered in MAIN; its reproductions are not independent confirmations. P7's GamerSky/17173 copies likewise are one lineage. P7 additionally hard-wires the double follow-up shield to Aventurine, contrary to MAIN section 10's marked-target chain, and has an internally inconsistent depleted-small-shield example. Those are concrete reasons for caution about that guide, **not a logical disproof of its separate cap assertion**. P8's proposed preview bug does not establish that P7 inherited it or when any fix occurred. An inspected 17173 rendering of another guide carried a third-party-AI-summary warning and was not used as independent confirmation.

The old mitigation-before-shield report and MAIN's parallel model are explicitly reused. Search misses and unread/default-branch entries are not evidence of corpus-wide absence. No inaccessible linked image/video or an author's generic claim to have tested other effects is counted as a cap experiment.

## 3. One damage instance: per-pool loss, one HP overflow

For the already supported ordinary model in MAIN section 4, fix one living recipient, its post-mitigation shield-eligible damage D, and the ordinary shield instances that participate in that damage. Exclude special bypass/shared-pool rules and interleaved new grants or removals. Each participating positive pool loses `min(s_j,D)`, not a share of D:

```text
loss_j = min(s_j_before, D)
s_j_after = max(0, s_j_before - D)
newly_depleted = {j | s_j_before > 0 and s_j_after == 0}
HP_damage = max(0, D - max(0, all participating s_j_before))
```

The shield creator's generation bonus changes a grant's amount; it does not mean that an already established smaller pool is held in reserve or assigned only the largest pool's overflow. The same recipient's mitigation is not recomputed separately from each shield creator's DEF. A pool already absent/zero is not newly broken again by this arithmetic. A positive pool exactly exhausted by D belongs to the depletion set under this model.

Calculated example, not an observation: pools A=500, B=1000, C=1500 and D=1000 lose 500/1000/1000 respectively, leaving 0/0/500 and no HP loss. Two shields are depleted while the actor still has shielding. If D=1700 instead, losses are 500/1000/1500, all are depleted and HP loss is200 once, not the sum of three overflows. These calculations reuse the model and identify outcome sets; they do not specify native callback counts.

Apply the accounting to actual damage instances, not an animation's total. In a multi-instance attack, intervening removals or changes in recipient mitigation can alter subsequent inputs. This record does not assume an engine-wide atomic pass that snapshots every pool and delays every listener until all damage instances finish.

## 4. A removal observer distinguishes the removed shield from current shielding

### 4.1 Reachability and event inputs

[AC]'s SkillP01 entry selects `Avatar_Aventurine_00_PassiveSkill01`; its OnStart installs `MAvatar_Aventurine_Passive`. In [A], that passive's OnStack has `ByRankActivated(TriggerKey.Hash=-1445815962)` gating `AddModifier(Caster,MAvatar_Aventurine_Rank06)`. The observer is therefore source-owned and conditional, not a universal rule attached to every actor.

Its complete selected removal callback has this structure:

```text
MAvatar_Aventurine_Rank06._CallbackList[1]
  Event = OnListenModifierRemove
  require ByCheckModifierCallBackBehaviorFlag(ParamEntity, Shield)
  require ByTargetTeam(ParamEntity, TeamLight)
  MDF_ShieldCount = 0
  Retarget(AllTeammateWithUnselectable):
    if ByContainBehaviorFlag(ParamEntity, Shield):
      MDF_ShieldCount = MDF_ShieldCount + 1
  if MDF_ShieldCount > 0:
    request Rank06_Sub with count * rank coefficient, limited by rank cap
  else:
    RemoveModifier(Caster, MAvatar_Aventurine_Rank06_Sub)
```

The callback-specific predicate and the later live-entity `ByContainBehaviorFlag` are **different serialized operations**, not one test duplicated under two names. The callback interpretation is that a shield-classified modifier removal causes reconsideration of current shielded entities. The native payload construction is not recovered. P10's per-shielded-teammate E6 description supports the entity-count interpretation, not a per-pool counter.

The first callback listens to `OnListenModifierAdd` with the same qualification and recount pattern. The removal callback's zero-count branch explicitly removes the granted submodifier. `Rank06_Sub.OnStack` writes `AllDamageTypeAddedRatio` using working hash68164246. Thus this observer changes a battle property; it is not the separate EnergyBar display scanner from MAIN.

### 4.2 Multi-shield consequences

Within the traversed population, an entity with three shields contributes one successful live Shield check, not three. After a completed removal that leaves another ordinary shield on that entity, the entity can still contribute one. After its last shield is gone, it contributes none at a recount observing that state. Consequently an unconditional `count -= 1` for each removed shield would misrepresent this consumer. Cap saturation may hide changes in its visible damage bonus; count and granted bonus are distinct.

This source does **not** tell us whether simultaneous A/B/C depletion produces three global notifications, whether each notification is interleaved with individual OnDestroy work, or whether an observer can see partially processed pools. It specifies what this consumer requests whenever the qualifying callback is delivered. Its reread strategy cannot be upgraded into a universal notification batching or reentrancy guarantee.

## 5. Destruction of a shield is not every shield-adjacent removal

### 5.1 Actual destruction cleanup, retained from the earlier record

The named `MAvatar_Aventurine_StackableShield.OnDestroy` requests RemoveShield on its holder, removes its named companion/status/control states, and resets resilience. March's main shield has its own OnDestroy cleanup. These are per-definition cleanup surfaces. The ordinary public disappearance result supplies the link between depleted ordinary shields and loss of their associated protection/effects; the exact native zero-to-destruction instruction and dispatch order remain uninspected.

A bare `RemoveShield(ModifierOwnerEntity)` within that definition is not proof that every unrelated shield is erased. Nor does OnDestroy encode a universal reason of damage depletion: forced removal and other lifetime exits require their actual cause/context. The already supported public model retains unrelated surviving shields.

### 5.2 New counterexample: companion removal during an authored top-up

[A] `Avatar_Aventurine_00_Skill02_Phase02` explicitly orders these selected tasks:

```text
RemoveModifier(AllLightTeam, MAvatar_Aventurine_00_Skill02_ShieldEffect)
... presentation waits ...
read Caster.Defence -> MDF_CurrentDefence2
IncludeTaskListTemplate(Aventurine_RecordCurrentShield)
AddModifier(AllLightTeam, MAvatar_Aventurine_StackableShield, new operands)
LoopTargetList:
  ... selected appearance inputs ...
  AddModifier(AbilityTargetEntity, MAvatar_Aventurine_00_Skill02_ShieldEffect,
              including MDF_CritDmg1 = hash164770054)
```

The explicitly removed name is a companion, **not** `MAvatar_Aventurine_StackableShield`. Its inspected definition has an OnStack callback and no authored OnDestroy shield-removal body. The ordinary carry/stack interpretation is already supported in MAIN/F04; this new comparison demonstrates why the remove/re-add requests in a refill must not be reclassified as damage breaking the named pool. It does not recover native modifier replacement semantics or guarantee the absence of every external listener side effect.

The unsuffixed `ShieldEffect` definition is mixed, not presentation-only. Its rank-gated OnStack branches request `StackProperty(ModifierOwnerEntity,CriticalDamageBase,hash130698171)` and add `MAvatar_Aventurine_Rank01_Status`; the installer supplies the rank-derived MDF_CritDmg1 input. Other tasks choose status names and effects. This **qualifies MAIN section 5.1's shorthand about shield-display effect names**: the unsuffixed companion must not be excluded from combat merely because of its name or adjacent visual tasks. No exact transient stat visibility during the remove/rebuild sequence is asserted.

`ModifierOverrideOnHitEffect.SheildBreakEffectPath` is a visual asset field in that mixed definition. It is not an exported gameplay `OnShieldBreak` callback or evidence of a one-to-one visual/event count. Conversely, the Rank06 observer uses a callback Shield classification rather than admitting every arbitrary companion removal solely because its holder has another shield.

### 5.3 What remains missing in the event chain

Keep four questions separate: numerical pool loss; disappearance of the depleted pool and its associated effects; dispatch of that instance's destruction/removal hooks; and notifications consumed by other effects. We now have a real consumer and an explicit non-depletion removal path. We still lack a source/observation deciding per-pool versus aggregated OnListenShieldChange emission, the relative order of multiple shield OnDestroy callbacks and global remove listeners, visibility of sibling pools during callbacks, and reason/interrupt handling. No guessed event total order is written as a game fact.

## 6. Shield bonus and cap: useful public model, unresolved contradiction

P6 explicitly includes shield-generation bonuses in Fortified Wager's cap, in agreement with interpreting P10's cap as twice the current Skill's actual grant. The preferred **description-backed** expression for fixed relevant inputs is:

```text
base_skill_shield = a * effective_creator_DEF + f
skill_grant = base_skill_shield * (1 + applicable_shield_bonus)
cap_inclusive = 2 * skill_grant
```

This is a named shield family's public model, not a universal formula for every stackable shield. F04 already establishes the ordinary generation-bonus contribution. For a hypothetical base1000 and sole bonus20%, the inclusive model offers1200 and caps at2400. P7 instead implies cap2000, leaving800 after one grant. These are genuinely different predictions, not a wording difference about shield absorption versus current HP.

This pass does not choose by counting reproductions. P6 provides a direct semantic explanation; P7 provides an explicit contradictory original guide but no isolated cap trace in the acquired material. P8 shows that preview-video behavior may have a version-specific complication, without proving the live resolution. Therefore the inclusive model is preferred for an attributed calculation, while **bonus participation is not marked conclusively verified or raw-closed**. A cap-sensitive output should retain this qualification instead of presenting either2000 or2400 as newly observed.

The fixed source's reused topology is:

```text
fresh Caster.Defence read at the selected grant
  -> MDF_InitShieldValue = DEF * Skill02[0] + Skill02[1]
  -> MDF_ForceShield = the skill-sized expression
  -> MDF_MaxShieldRatio = Skill02[3]
MAvatar_Aventurine_StackableShield.OnStack:
  StackShield.StackValue = AQAR / [-1200970748]
  StackShield.MaxStack = AQABAQQR / [1079898730, -1177161350]
```

These are distinct generation/cap inputs. The native preprocessing and working-value bridge into the last expression were not recovered. In particular, the lack of a literal ShieldAddedRatio term in that serialized product does **not** prove bonus exclusion: an input or the native operation may already incorporate it. Conversely, the field name MDF_ForceShield is not proof of bonus inclusion. No extra multiplier or hidden default is fabricated.

## 7. Changed attributes: new request, existing balance and lower-cap policy

The selected grant bodies explicitly reread creator DEF and supply new shield operands. This supports recomputing those request inputs when a subsequent grant occurs, rather than permanently retaining the DEF from the battle's first shield. It does not by itself prove that every already stored shield balance changes at the moment a DEF buff changes.

Separate the three boundaries:

| Boundary | Evidence obtained | Unresolved consequence |
| --- | --- | --- |
| DEF/bonus changes with no shield grant or incoming damage | P9 explicitly asserts old shield amount does not immediately fall when one temporary DEF boost expires | Historical/pre-release assertion only; not a generic current balance-rescaling/reset rule |
| A later selected shield grant is authored | Raw fresh DEF read and new skill-sized operands; public cap depends on the current Skill shield | Precise native cap transport and bonus policy remain qualified above |
| Existing named balance is already above the newly applicable cap when another grant arrives | Previous fixed-input min formula does not resolve this case | Clamp downward, preserve over-cap balance, or retain a previous higher ceiling are not distinguished by the acquired evidence |

A cap is a limit, not a grant: increasing the allowed ceiling alone does not algebraically create stored shielding. Equally, describing a cap as dynamic does not decide whether an existing balance is immediately truncated or how the next grant treats excess. P9's preservation wording answers neither the next-grant operation nor a later damage/removal sequence.

Calculated discriminator only: suppose old cap3200, old balance2800, new cap2400 and a later offered grant200, with no other changes. Different policies would produce:

| Candidate policy | Predicted balance after that grant |
| --- | ---: |
| Unconditional `min(old_balance + grant, new_cap)` | 2400 |
| Preserve existing excess and allow no growth above the new cap | 2800 |
| Continue using the old higher ceiling | 3000 |

None of these outcomes is reported as observed. The first candidate can lower a shield on a positive grant, so copying the earlier unchanged-input min formula into a shrinking-cap case would silently choose a real behavioral policy. A useful original trace must show DEF/bonus, exact named balance before the attribute change, after the change without a hit, and after the next isolated grant; a full-bar icon alone cannot discriminate these stages.

## 8. Claim accounting and publication boundary

| Question | This continuation's answer |
| --- | --- |
| Which ordinary participating shields lose value, and how much? | Retained parallel model: each loses min(own remaining,D); no reserve queue; HP overflow once |
| Is one destroyed shield identical to the actor losing all shielding? | No; the new removal consumer rechecks current shielded entities rather than subtracting once per removed pool |
| Is every shield-adjacent modifier removal a shield break? | No; the explicit mixed-companion remove/rebuild during a refill is a counterexample |
| Are the unsuffixed ShieldEffect tasks presentation-only? | No; selected rank-gated CriticalDamageBase writes are newly identified |
| Are exact global break/removal notification count and order settled? | No; authored consumers/cleanup are separated from the missing native dispatch edges |
| Does a shield bonus affect the named accumulation cap? | Inclusive public model preferred with a registered explicit contradiction; no isolated current/pin-matched validation obtained |
| Does changed DEF affect subsequent selected request operands? | Yes, through an explicit fresh read; not proof of immediate rewriting of existing balances |
| What happens on a positive grant when the existing balance exceeds a reduced cap? | Still unresolved; the three outcomes above are predictions, not test results |

Publish this new focused record and a continuation link in MAIN. The integrated review already points to MAIN and remains accurate; no broad checkbox or whole FG-05/F04/W05 completion is claimed. Repository access and publication use only the GitHub connector. Actual work is immutable-source reading, comparison of predicates/owners/operations, attributed public-source review, labeled arithmetic, and the publication checks reported in the checkpoint. No game, simulator or test was run by this investigation; no CI workflow was manually started and no skipped/unknown check is described as passed. Runtime, lowering, IR, tests, CI configuration, pin and mode boundaries are unchanged.

[MAIN]: multi_shield_parallel_absorption_and_effect_ownership_v1.md
[F04]: general_healing_shield_hp_resolution_v1.md
[A]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Aventurine_00_Ability.json
[AC]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Aventurine_00_Config.json
[P6]: https://ol.3dmgame.com/gl/266544_2.html
[P7]: https://www.taptap.cn/moment/607666503239599859
[P8]: https://news.17173.com/content/04142024/171552893.shtml
[P9]: https://www.gamersky.com/handbook/202404/1731357.shtml
[P10]: https://starrail.honeyhunterworld.com/aventurine-character/?lang=EN
