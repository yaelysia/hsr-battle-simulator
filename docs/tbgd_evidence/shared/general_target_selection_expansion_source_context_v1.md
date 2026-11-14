# General targeting: selection, expansion, aggro and source context v1

## 1. Scope and result

Reviewed 2026-09-24. Evidence parent: `2718b77036a7085f67fd66814af2268ea3882f8d`; preceding checkpoint: `5808653282` (F04). Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains open/Draft and docs/evidence-only.

**F09 result:** separate selectable candidates, chosen primary, per-effect recipients, internal traversal, damage-distribution destination and actual effect owner. The shared model includes conditional aggro-weighted selection and its distinction from collateral exposure, an exact bounce validity predicate, primary versus adjacent healing/cleanse requests, a guarded damage split, and an ownership-transfer discriminator backed by a credited gameplay report.

The research unit is the common mechanism. Asta, Huohuo, Fu Xuan and Tingyun are contrasting source occurrences, not new whole-kit completion tasks. March's previously audited conditional aggro input is reused. F09/W11/W15 remain active for specific exceptional target, policy and attribution questions; no generic AI, selector census or backend acceptance is claimed.

[R7][R7]'s T1/T2/T3/T4 vocabulary is useful, but its local compiler projections and historical kernel-first instructions are not native authority or current research gates. No runtime, lowering, IR, test or CI file was inspected or changed for this pass. No game, simulator, Direct, test suite or workflow was run; no local-runtime E is added.

## 2. Source register and replay discipline

### Newly inspected pinned raw paths

Named selectors identify actual serialized occurrences, not guessed array offsets. Paths are relative to the pinned TBGD repository.

| Ref | Path / selected occurrence | Complete blob |
| --- | --- | --- |
| S1 | [Asta CharacterConfig][S1]; Skill02 TargetInfo and entry | `147dfdfb5b6170e0371bc0a105d5342868e8f025` |
| S2 | [Asta Ability][S2]; Skill02 Phase01/02, first hit, count branch and bounce continuation | `b2a03d625fe8628eb927bd198d4108e5f7ba70b7` |
| S3 | [GlobalTaskListTemplate][S3]; Bounce_SelectTarget, including its full predicate | `d1da985fbac1bcf4e23f3c1dcdf7dfd11bcb5c96` |
| S4 | [Huohuo CharacterConfig][S4]; Skill02 selection/adjacency and indices0-4 | `d3fd8ffbd4539ffcb4e51b023c7cc66c67f348c6` |
| S5 | [Huohuo Ability][S5]; Skill02 Phase01/02, primary/adjacent heals, cleanse and voice-only traversal | `2bcd081a8102a7666336826a1c9f3ae3ec9d6aa4` |
| S6 | [Fu Xuan CharacterConfig][S6]; Skill02 entry/membership and split input | `c666c8006ac9ad2e73e13ed3c927fc41fc94e267` |
| S7 | [Fu Xuan Ability][S7]; Skill02 installer and GlobalModifiers.MAvatar_FuXuan_00_HitDamageSplit | `dc7cf6f7bf78c6abdbe0746e2aa5d56308b162be` |
| S8 | [Tingyun CharacterConfig][S8]; Skill02/SkillP01 coefficient environments | `2211a8e69b180b176fbafdf098720d8d982fd255` |
| S9 | [Tingyun Ability][S9]; Skill02 baseline/rank-variant LeiLing installation and InheritCaster | `41b224f8a3261db6a2e0aeb269bf834a77381489` |
| S10 | [AvatarPromotionConfig][S10]; AvatarID1001 first row, MaxLevel20, BaseAggro | `d09a89b7abad0bd836050146416e9fe0331e61da` |

Replay ranges: S1 70-190; S2 280-690; S3 named template in the successfully read 2801-6000 range; S4 95-160 and341-440; S5 180-775; S6 complete CharacterConfig; S7 150-850 and1700-2370; S8 190-360; S9 770-1115; S10 1-80. Blob plus named occurrence is the stable anchor if viewer line layout changes. Reading neighboring operations does not include them all in the claim scope.

**Replay-anchor reconciliation:** R7's cached Asta CharacterConfig/Ability and shared-template SHA strings differ from the successful exact-pin responses above. The S3 contents-directory response independently reports this same `d1da985...` blob. Use this table and the literal `Avatar_Asta_00_...` names for the new claims, not R7's cached strings or shortened names. The discrepancy's cause is not established; no different TBGD revision or gameplay change is invented. R7's useful layer distinction and the opaque selector-type correction survive. Its historical document is not silently rewritten.

### Reused evidence and public interpretation

[March][MARCH] supplies the audited Skill100102 level11/12 threshold0.3 and aggro input5, their typed bindings and the shield's AggroAddedRatio write. [F04][SUSTAIN], [F06][MODIFIERS] and [F07][RESOURCES] supply actual-owner predicates, state-holder roles and owner-directed resource grants. Those results are reused, not recounted as new raw extractions.

| Ref | Public source / provenance | Use and limit |
| --- | --- | --- |
| P1 | [KQM Asta guide][P1], Version1.4 | Skill description distinguishes a selected first target from subsequent random hits. No probability distribution or native RNG recovered from its wording. |
| P2 | [KQM Huohuo guide][P2], Version1.5, Skill section | Primary-target cleanse and separate adjacent healing; other Talent-triggered cleanses are separate effects. No unread numeric skill row is filled from this page. |
| P3 | [KQM teambuilding guide][P3], Aggro section | Relative ordinary base weights and positioning versus splash. Its legacy path list is not a census of all later paths/entities. |
| P4 | [Aqua_Essence's aggro explanation][P4], 2024-01-16, crediting GachaGuru for the formula | Attributed weight/probability model and worked algebra, not a controlled frequency experiment or proof of all enemy policies. |
| P5 | [KQM Fire Trailblazer guide][P5], Version2.0 | Taunt is a different targeting effect from raising aggro. No universal taunt/lock-on/script precedence is adopted. |
| P6 | [KQM memosprite mechanics][P6], Version3.2, Soul Fish | The described memosprites occupy adjacency positions, including the Huohuo example. Not every summon is assigned the same placement rule. |
| P7 | [KQM Fu Xuan guide][P7], Version1.3, Mechanics | The named65% distribution precedes recipient-specific defenses and shields. This interpretation now has a corresponding raw split/recipient chain, not a recovered native evaluator. |
| P8 | [Original Tingyun ownership report in KQM SRL][P8] | Credited tests vary ally/Tingyun stats and examine kill Energy. Actual reported scope is preserved; no new video or gameplay replay. |

P8 was read at `KQM-git/SRL@de0e5c09c8dbba9577367ad86e991fe91c4f0e36`, `docs/evidence/characters/lightning/tingyun.md`, blob `55fb73f6a56f5e1c7d1fba5a90c7e4a15c21bfa3`. Authors: daitobyte, falkyn, okarin_42 and neirodtheseal; added2023-06-01, last tested2023-05-01. The publication revision is not the TBGD pin. Public sources were consulted2026-09-24; retrieval date is not a patch label. Related KQM publications and copies of skill text are not independent experiments. No same-pin localization join, unread table coefficient, video viewing or native selector body is claimed.

## 3. Four targeting layers, plus an independent source axis

| Question | Evidence to retain | Common mistake |
| --- | --- | --- |
| T1: which primary can be selected? | Actor/skill identity, friend/enemy relation, explicit filters and relevant state | Inferring legality from the damage animation or all future recipients |
| T2: what is automatically addressed? | The action's actual automatic relation/set | Treating AllEnemy as a request to choose one enemy |
| T3: how is the selected context expanded? | Primary/adjacent/other-member relations and per-effect target operands | Giving every effect the union of every target used anywhere in the skill |
| T4: who is visited inside execution? | Template parameters, candidate predicates, loop count and continuation target | Reopening a player selection on each bounce, or treating a traversal as an attack |
| Source axis: who owns each consequence? | Parameter donor, executing context, status caster/holder, actual source and recipient | Assigning all consequences to the character whose name prefixes the file |

These are research distinctions, not a proposed backend schema. The same entry may declare `UseType=SelectEntity` while its TargetInfo is AllTeamMember, as S6 does. One token cannot determine external choice cardinality without the target relation and gameplay meaning.

Skill-level shape and per-operation recipients are different. Damage, healing, cleanse, resource gain and presentation can address different objects during one action. An automatically resolved set is not necessarily a chronological hit list. The shape labels Single/Blast/AoE/Bounce guide the investigation; actual targets, repeated requests and coefficients still come from the graph and corroborating descriptions.

Candidate validity also has a time dimension: valid at selection does not establish validity at a later hit, and an explicit later selector is not proof that every skill reruns selection. No universal 'original target gone -> choose another random target' fallback is introduced.

## 4. Selected first hit and bounded internal bounces

S1 declares Skill02 with EnemySelect, SubTargetType=TargetAllTeammate and entry `Avatar_Asta_00_Skill02_Phase01`. S2 triggers Phase02 on Caster; Phase02 uses SkillTargetEntityList and first requests Fire damage on AbilityTargetEntity. That target is distinct from the later template argument and callback entity.

```text
initial DamageByAttackProperty(AbilityTargetEntity)
 -> ByRankActivated(Hash2089636447)
      success: Bounce_Count=5
      failed:  Bounce_Count=4
 -> LoopExecuteTaskList(MaxLoopCount=hash-2146792706)
 -> IncludeTaskListTemplate(Bounce_SelectTarget, ParamTarget=AllEnemy)
 -> supplied ParamTaskList requests damage on ParamEntity
```

The first and subsequent damage sites use the same percentage read `-1847083384`. The later stance expression additionally multiplies its stance input by0.5; equal damage-coefficient reads do not prove equal toughness input. P1 corroborates the initial-plus-four baseline. The raw conditional branch is retained rather than generalized to every build.

The broad TargetAllTeammate declaration does not cause every enemy to take every bounce, and does not select the caster's allies for these damage requests. The concrete caller supplies AllEnemy; the continuation consumes the single internal ParamEntity. Animation/VFX operations in that continuation are not additional damage requests.

### Exact shared candidate predicate

S3 `TaskListTemplate[Name=Bounce_SelectTarget].TaskList[0]` literally has `$type=GLOABNLLLEL`. Do not rename it RPG.GameCore.Retarget. Its serialized structure is:

```text
TargetType = TemplateParamEntityList
Predicate = ByAny(
  ByTargetListAny(TemplateParamEntityList,
    ByTargetAliveState(ParamEntity, Mask_AliveOnly), Inverse=true),
  ByCompareHP(ParamEntity, Greater, 0))
ByRandom = true
IncludeLimbo = true
MaxNumber = 1
TaskList = TaskTemplateFetchParamSequence(ParamTaskList)
```

At the authored Boolean level, when the supplied list contains an AliveOnly entity, the first arm is false and a candidate needs HP>0. When it contains none, the first arm is true. IncludeLimbo is explicit and must not be erased by replacing the whole operation with an unconditional alive-only filter.

This closes the inspected predicate and per-call bound, not the opaque selector's full execution algorithm. It does not prove that every limbo entity is selected, that a dead entity revives, or what happens when the final candidate list is empty. Those are distinct terminal/invalidation questions.

ByRandom and MaxNumber1 alone do not prove uniform probabilities, independent draws, replacement between draws, or an aggro-weighted selector. P1 supplies ordinary random-hit meaning; exact distribution/stream claims require their own evidence. Potential recipients, actual hit sequence and distinct-hit-target count must remain different quantities.

## 5. Adjacency is per effect, not one skill-wide target list

S4 Skill02 declares FriendSelect with TargetAdjoinEntity. AlwaysDoAutoLock=true / AutoLockType=LowHP is a separate selection-assistance input, not proof that only the lowest-HP ally is legal. S5 carries SkillTargetEntityList through its phases and authors these distinct operations:

| Phase02 operation | Recipient | Typed input role |
| --- | --- | --- |
| DispelStatus, Order=LastAdded | AbilityTargetEntity | hash-672978835 <- SkillParam(Skill02,4) |
| Primary HealHP, HealByHealerMaxHP | AbilityTargetEntity | percentage-1544075911/index0; flat26571817/index1 |
| Adjacent HealHP, HealByHealerMaxHP | AbilityTargetAdjoinEntity | percentage1162693943/index2; flat-203632277/index3 |
| ModifySPNew(AddRatio1) | Caster | Separate self Energy request, as distinguished in F07 |
| Retarget(ByRandom,MaxNumber1) | Filtered SkillTargetEntityList -> ParamEntity | Continuation only CharacterPlayVO(ReceiveHealing) |

P2's Skill text confirms that the explicit cleanse belongs to the primary target while the two healing paths cover primary and adjacent recipients with different amounts. This does not deny separately triggered Talent cleansing. It also does not promote the voice selector or the earlier AbilityTargetAndAdjoinEntity VFX target into a healing operation.

Under a stated ordinary linear arrangement A-B-C-D, choosing B can give the primary heal to B and the adjacent heal to A/C; choosing endpoint A does not create a second neighbor. The explicit primary cleanse remains on the chosen primary, not all healed recipients. This is a consequence of the selected relation, not a proof of how every multirow formation or empty slot is maintained.

P6 provides a concrete branch that changes such reasoning: the described memosprites sit to their owner's right and participate in adjacency. A blast centered on the owner can therefore include that memosprite instead of an original neighboring character. Store the actual formation relation rather than hard-code a permanent four-character array. Exact insertion/reflow and other summon classes remain separate questions.

## 6. Aggro: conditional weighted selection, not a universal target resolver

For an ordinary enemy primary selection that actually uses positive aggro weights, with eligible pool V and no overriding target rule, adopt the attributed P3/P4 model:

```text
w_i = b_i * (1 + sum(applicable aggro-ratio contributions))
Pr(primary=i | V, weighted policy) = w_i / sum(w_j for j in V)
```

Here b_i is base aggro, not damage dealt or current HP. The denominator includes the actual eligible pool. The equation assumes finite nonnegative weights and a positive total; it does not invent negative-weight clamps, zero-total fallback or a generic enemy AI policy.

S10's first AvatarID1001 row, MaxLevel20, explicitly supplies BaseAggro150; Promotion is omitted in that occurrence and is not rewritten as a serialized zero. P3's legacy relative scale6:5:4:3 is compatible with150:125:100:75 because multiplying all weights by the same constant leaves the quotient unchanged. Only the selected150 is newly read as a raw numeric here; the remaining values are not a new same-pin all-path census.

[March][MARCH] already traces Skill100102's selected HP>=0.3 branch to an injected aggro-ratio input5, otherwise0, and then AggroAddedRatio. This is an application-time predicate in the audited graph, not newly discovered continuous HP tracking. An input+5 changes the modeled weight to six times its base, not a guaranteed primary-selection probability of100%.

For a deliberately fixed pool with base weights150,125,100,100, giving the125 entry an applicable+5 contribution produces750/1100, approximately68.18%. It remains below certainty. Two additive+5 contributions give1375/1725, approximately79.71%, not multiplication by6 twice. These are algebraic predictions under the stated model, not newly measured target frequencies.

**Taunt and special policies remain separate.** P5 distinguishes its forced-target effect from an increased chance to be selected. Do not implement that distinction as merely an enormous guessed aggro value, or claim it suppresses collateral/AoE effects. Scripted lock-ons, attack-specific preferences, taunt conflicts and immunity/validity precedence need their own rules. Ally target selection and Asta's opaque random bounce are not silently routed through this formula.

### Primary selection versus collateral exposure

For a specifically defined one-primary attack that also hits the immediate neighbors of that primary, with no other recipients or validity changes:

```text
Pr(unit i is hit) = p_i + sum(p_k for primary positions k adjacent to i)
```

The events 'primary is k' are mutually exclusive, which justifies this sum. In a four-position line with equal primary probabilities1/4, endpoints have exposure1/2 and interior positions3/4. Changing position can therefore change exposure without changing base aggro. These synthetic probabilities do not assert that any particular boss selects uniformly, or that primary and collateral damage amounts are equal.

## 7. Damage distribution changes the receiver, not the original primary selection

S6 Skill02 binds `-458258105=SkillParam(Skill02,0)`. S7 Phase02 installs `MAvatar_FuXuan_00_HitDamageSplit` on AllTeammateWithUnselectable and injects that value as MDF_SplitPercentage. A distinct Caster-owned parent receives the lifetime input. Thus the nominal all-team action and the actual split-state holders already have different roles.

The split-state consumer is exact:

```text
BehaviorFlagList = [RemoveWhenCasterDead]
OnBeforeBeingHitAll
 -> ByNot(ByIsSplitDamage(ModifierOwnerEntity))
 -> HitDamageSplit
      SplitTarget = Caster
      AliveState = Mask_AliveOrLimbo
      SelfSplitRatio = AAABAAMR / Fixed[1] / Hash[685349384] = 1-q
      TargetSplitRatio = AQAR / Hash[685349384] = q
```

The holder is the original receiving ally; Caster here is the split-state source, Fu Xuan, not the enemy that launched the attack. The guard excludes already-split damage from this split request. This is explicit recursion prevention, not a theory about a generic callback scheduler.

P7 supplies the named q=.65 gameplay interpretation and split-before-recipient-mitigation rule, previously public-only in F04. The selected raw input, complementary ratios, destination and guard are now traced. No numeric Skill02 table row was newly read: .65 retains its public-description provenance.

For ordinary incoming U, the two pre-shield branches are `(1-q)*U*M_ally` and `q*U*M_FuXuan` under that model. No new enemy target roll is required by this receiving-side operation. No attacker replacement is authored in the inspected request; complete identity and trigger payloads of the resulting split events remain an explicit residual, not inferred from field absence.

Mask_AliveOrLimbo and RemoveWhenCasterDead must both be retained. They do not independently settle lethal-hit, revive or concurrent-cleanup timing. Likewise P7 distinguishes direct hits from distributed damage for ordinary hit-Energy generation: receiving an HP deduction is insufficient to infer every 'attacked' trigger. F07's resource-source rules remain independent.

## 8. Effect provider and actual damage owner can differ

S8 supplies `-1847083384=SkillParam(Skill02,0)` and `1246667513=SkillParam(SkillP01,0)`. S9's selected baseline Skill02 branch installs MAvatar_TingYun_00_Passive_LeiLing on AbilityTargetEntity, passes those two damage-related inputs and a separate attack-delta value, and explicitly sets `InheritCaster=TargetSelf`. The inspected rank variants carry the same inheritance field; they are not newly audited in full.

P8 reports that the selected Benediction additional Lightning damage follows the blessed ally's relevant offensive stats and that a kill from it credits Energy to that ally, not Tingyun. Varying whose stats affect the result and whose resource is awarded provides two useful attribution discriminators. This is credited historical gameplay evidence, not a calculation promoted into an experiment.

The supported interpretation is therefore not 'the character who supplied the buff owns every later damage request'. The parameter donor remains Tingyun while the named inherited context can be ally-owned. This pass closes the selected installer/ownership interpretation with that report; it does not claim a fresh audit of every LeiLing callback or every current snapshot field.

The report also links a snapshot video. Without reading its full experimental scope, that single sentence is not promoted to a universal capture/refresh policy. Native inheritance defaults, mixed-source propagation and event payload construction remain distinct from the supported owner identification.

The same discipline applies to reused F04 actual-healing-owner predicates and F07 memosprite resource redirection. ParamEntity is a candidate inside a selector but an event argument in another context; it is not globally 'the original target'. ModifierOwnerEntity identifies the state holder, not necessarily the formula-stat donor. Preserve an original source separately from a detonator or a receiving-side distributor when the effect's evidence calls for it.

## 9. Claim accounting and discriminators

| Claim | Positive evidence | Specific limit |
| --- | --- | --- |
| Action selection and per-effect recipients differ | R7 vocabulary plus S1/S2/S4/S5/P1/P2 | Not every TargetInfo field/default or automatic cardinality |
| Selected bounce has explicit validity logic and one-target bound | S3 full predicate, IncludeLimbo, opaque type and supplied continuation | Opaque selection algorithm, terminal/empty pool, draw distribution |
| Primary versus adjacent heals and cleanse are distinct | S4/S5 typed inputs and P2 wording | Other triggered effects, formation reflow and special adjacency |
| Ordinary aggro weights and collateral exposure differ | P3/P4 model, S10, reused March; conditional probability algebra | Enemy-specific policies, taunt/lock arbitration, extreme weights |
| Distribution destination and original target differ | S6/S7 input, non-split guard, ratios and P7 | Full split-event attribution/trigger ordering |
| Parameter donor and additional-damage owner can differ | S8/S9 InheritCaster plus credited P8 tests | Complete callback census and property snapshot policy |
| Backend or all foundational mechanics complete | Not claimed | F09/W11/W15 active; F01/F10 and named residuals remain |

Additional calculated/source discriminators: choosing a different primary can change only the cleanse recipient while preserving some overlapping heal recipients; repeating a single-target bounce does not imply several distinct targets; a split-generated recipient need not have been selectable by the original attacker. All predictions require their stated operation/formation conditions, and are not new combat runs.

Outstanding questions are bounded: selectable-target invalidation between submission and impact; exact opaque-selector terminal behavior; empty/multi-target cardinality and draw replacement; taunt/lock-on/script conflicts; formation holes, late insertion and special adjacency; full context propagation through nested, inherited, split and redirected effects; and event-specific attribution for simultaneous death/heal/resource consumers. Public tests and precise source edges can resolve these without a native engine dump or backend repair.

## 10. Publication and next foundation

This checkpoint adds the present record and updates the foundation roadmap and evidence README only. Historical primary records, the broad W checklist, source inventory and pin remain intact. Ten pinned raw paths and the credited external GitHub report are registered; previously audited March/F04/F06/F07 results are explicitly reused. Source/model review and Git diff/content/head checks are not runtime tests.

**Next primary foundation: F10 event, entity and encounter lifecycle.** Separate registration from triggering, ordinary lethal/limbo/revive paths from forced cleanup, and entity/wave/phase transitions from presentation. Reuse R6 and retained servant/event evidence without creating runtime-admission or implementation prerequisites. F01's remaining shared parameter/property synthesis remains on the foundation map. No next foundation is executed in this checkpoint.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Asta_00_Config.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Huohuo_00_Config.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Huohuo_00_Ability.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_FuXuan_00_Config.json
[S7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_FuXuan_00_Ability.json
[S8]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Tingyun_00_Config.json
[S9]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Tingyun_00_Ability.json
[S10]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarPromotionConfig.json
[P1]: https://hsr.keqingmains.com/asta/
[P2]: https://hsr.keqingmains.com/huohuo/
[P3]: https://hsr.keqingmains.com/misc/teambuilding-guide/
[P4]: https://www.reddit.com/r/ClaraMainsStarRail/comments/1987y1x/clara_and_aggro_buffs_understanding_how_they_work/
[P5]: https://hsr.keqingmains.com/fire-trailblazer/
[P6]: https://hsr.keqingmains.com/misc/memosprite-mechanics/
[P7]: https://hsr.keqingmains.com/fu-xuan/
[P8]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/docs/evidence/characters/lightning/tingyun.md
[R7]: action_targeting_enemy_decision_boundary_v1.md
[MARCH]: ../characters/march_7th_preservation_skill02_shield.md
[SUSTAIN]: general_healing_shield_hp_resolution_v1.md
[MODIFIERS]: general_modifier_identity_stacking_lifetime_v1.md
[RESOURCES]: general_energy_skill_point_economy_v1.md
