# Battle Execution Language Core v1

## Record metadata and authority

- Thread: `R0-BATTLE-LANGUAGE-CORE-V1`.
- Work: W03 + L01/L03/L04/L05; reusable **source-facing vocabulary**, not an opcode census or a runtime specification.
- Research date: 2026-09-09.
- Business-repository research baseline: `306935fe5f764cab448a86f1be9f6f3d5736b4c6` on PR #8. The actual head matched the planning head when research began.
- Authoritative corpus: `DimbreathBot/TurnBasedGameData` at **`14c1d18f91a8101d610e6c523447a7517de3fae1`**. Every upstream link below is immutable at that revision.
- Maturity: `manually_confirmed`, with heterogeneous Avatar / Servant / Monster cross-samples for the common structural contracts. Individual actor-local edges are not promoted to universal rules.
- Scope verdict: `include` for the ordinary producer/consumer edges below; `mixed` at ability-file level because presentation and battle operations coexist.
- Runtime verification: **not performed / not claimed**. No simulator runtime, business behavior, lowering, IR, tests, or production semantics changed.
- Exit status: **complete for this bounded v1 dictionary**, not complete for W03, L01/L03/L04/L05, all selectors, all entity families, or all engine semantics.

Authority remains: current BATTLE_SCOPE/evidence contract -> current worklist/inventory -> corrected detailed evidence -> historical parallel reconciliation -> older comments. This record consumes the current detailed records; it does not restore their superseded wording. Its literal-type clarification for the Asta template below supersedes treating that particular raw node as a literally named `RPG.GameCore.Retarget`.

### Scope gate and method

The gameplay navigation model is: an ordinary skill has an entry, operands, execution entities and targets; it may dispatch more work, install listeners, and change battle state. This model suggested where to look, but did not supply missing formulas or dispatcher behavior.

The actual route was mature evidence -> exact-pin producer reread -> exact-pin consumer reread -> local semantic interpretation -> heterogeneous comparison -> generic/actor-local split -> named boundary. The inspected consequences are shield/property/heal changes, direct damage, resource/delay writes, creation and forced cleanup. Cosmetic tasks are classified at node/consumer level, not by directory or ability name.

Out of scope: broad/global reverse scans; a fresh character survey; generic RNG/dispatcher/queue implementations; final damage/heal/shield/stat formulas; servant automatic passive activation, sync merge and coordinated normal-slot accounting. An adjacent mechanism is an entry edge for a later vertical slice, not permission to expand this thread.

## 1. How subsequent research should cite this record

Use the stable sections **P** (parameters), **E** (entities), **D** (dispatch), **O** (operations), and the anchor codes **A/B/C/D** below. A citation to an operation imports only its recorded operands, context and consequence category. It does **not** import a hidden numerical evaluator, callback total order or scheduler policy.

Bracketed codes such as `[D1]` identify primary sources in section 11; vocabulary IDs such as **D1 Skill EntryAbility** identify dictionary rows. Keep that distinction when reusing an individual claim.

For a new occurrence, retain this evidence tuple:

```text
pin + file + named ability/modifier + callback/task occurrence
-> binding producer + trigger/index or explicit value injection
-> invocation performer + target input + temporary traversal entity
-> exact operation type + operands + downstream battle consumer
-> sample-local interpretation + unresolved engine/default behavior
```

The following frame is **analyst notation**, not a proposed IR, a native GameCore structure, or a production implementation:

```text
F = (originating action, current invocation performer,
     declared skill target / explicitly supplied inherent target,
     current traversal-or-callback parameter entity,
     modifier holder where applicable,
     parameter bindings and explicitly observed working-value environment)
```

Keep the originating action distinct from the current invocation performer. Do not silently equate the performer with the caller, modifier holder, current traversal entity or last-created entity. Do not infer a stack layout, environment-copy policy or normal-action debit from this notation.

## 2. Exact ordinary anchors

### A — March Preservation Skill02: binding -> injection -> callbacks

`[A1]` `AvatarSkillConfig(SkillID=100102, Level=11)` declares `SkillTriggerKey=Skill02` and `ParamList=[0.589,3,0.3,802.75,5]`. This is a binding example, not renewed shield-number research. `[A2]` maps the five 0-based slots through `ReadInfo(Type=SkillParam, TriggerKey=Skill02, Index=0..4)` to hashes `-1091495116`, `-1016136907`, `398047946`, `1935511666`, `-1672381420`.

`[A2]` Skill02 is `SelectEntity` / `FriendSelect`, with entry `Avatar_Mar_7th_00_Skill02_Phase01`. In `[A3]`, Phase01 calls Phase02 on `Caster`; Phase02 uses `SkillTargetEntityList` and applies `MAvatar_March7th_00_BPSkill_Shield` to `AbilityTargetEntity`.

The call injects **named** values `MDF_ShieldPercentage`, `MDF_ShieldValue`, `MDF_HealPercentage`, `MDF_HealValue`, `MDF_AggroUp`, plus a lifetime expression. The shield modifier declares its own dynamic hashes and consumes the injected values in `OnStack -> InitShield / StackProperty`, `OnPhase1 -> HealHP`, and `OnDestroy -> RemoveShield`. Its `OnCreate` is not the `InitShield` occurrence. `[A3]`

The trace branch uses `[A4]` PointID `1001102`, `PointTriggerKey=PointB2`, `ParamList[0]=1`, bound by `[A2]` hash `948615157`. Rank06 uses `[A5]` RankID `100106`, Rank 6, `Param=[0.04,106]`, bound by `[A2]` hashes `-502601161` and `-72703950`. Phase02 conditionally writes `_Tree02_LifeTimeAdd`, `_Rank06_HealPercentage`, `_Rank06_HealValue` before injection. Inactive branches explicitly write zero; that does not make `ReadInfo.Type=None` a zero producer. `[A2-A5]`

Also used as a narrow dispatch cross-sample: `MAvatar_March7th_00_BPSkill_Shield_Mark.OnAfterAttack -> TurnInsertAbility`, with performer `Caster`, `AbilityTarget=ModifierOwnerEntity`, followed by caster-restricted removal of the mark. This records the invocation edge, not a fresh full counter-mechanic study. `[A3]`

### B — Asta Skill02: external target versus template traversal

`[B1]` Skill02 declares external `EnemySelect` and entry `Avatar_Asta_00_Skill02_Phase01`; it also contains the literal `SubTargetType=TargetAllTeammate`. Do not reinterpret that latter token as a proven selectable-target rule without its consumer. Phase01 calls Phase02 on `Caster`. `[B2]`

Phase02 first damages `AbilityTargetEntity` using hash `-1847083384`, then defines `Bounce_Count` on `Caster` with **`ContextScope=ContextCaster`** (reset 5 or 4 under the configured rank branch). A `LoopExecuteTaskList` reads hash `-2146792706`. Each iteration calls `IncludeTaskListTemplate(Name=Bounce_SelectTarget, ParamTarget=AllEnemy)` and supplies `TemplateParamSequences.ParamTaskList`, whose damage operation targets **`ParamEntity`** and reuses `-1847083384`. The adjacent effect and camera tasks are not damage producers. `[B2]`

**Literal-type clarification.** At this pin, `[B3] TaskListTemplate[Name=Bounce_SelectTarget].TaskList[0].$type` is **`GLOABNLLLEL`**, not the string `RPG.GameCore.Retarget`. The node has:

```text
TargetType = TemplateParamEntityList
Predicate = ByAny(
  ByTargetListAny(TemplateParamEntityList,
                 ByTargetAliveState(ParamEntity, Mask_AliveOnly), Inverse=true),
  ByCompareHP(ParamEntity, Greater, 0))
ByRandom = true
IncludeLimbo = true
MaxNumber = 1
TaskList = [TaskTemplateFetchParamSequence(ParamName=ParamTaskList)]
```

This closes the **configured random traversal / supplied-continuation / downstream damage** edge at the data surface. It does not decode the obfuscated type's engine identity. Preserve it as unknown-type-with-observed-contract in O18; do not normalize it to `Retarget` merely because its fields look similar. The exact alias producers for `TemplateParamEntityList` and `ParamEntity` are `[E0]`.

For an independently literal `Retarget(ByRandom=true)` ordinary consumer, `[C3] GlobalModifiers.MAvatar_Aglaea_00_GoldenSword_Mark.OnCreate` traverses `AllDarkTeamWithAllDarkTeamUnselectable`, excludes the current `ModifierOwnerEntity` via `ByCompareTarget(..., Inverse=true)`, has `IncludeLimbo=true`, `MaxNumber=10`, and removes the same named modifier from `ParamEntity`. The mark is actually added by Aglaea ordinary Skill01/Skill11 in `[C3]`. This supports O15 without rewriting the identity of the Asta node.

### C — Aglaea / Servant: explicit ownership and three invocation paths

`[C3]` Aglaea Skill02 contains `CreateServant(ServantID=11402)` with explicit `DynamicValues` for `_PointB3Layer`, `Skill11_DamagePercentage`, `Skill11_DamagePercentageAD`. The create-if-absent / maintain-existing distinction is retained from the mature chain; the language consequence is that creation and an existing servant's `HealHP` are different operations, not an implicit replacement rule.

`[C1] AvatarServantConfig[11402]` points to `[C2]` and lists skills `1140201,1140203,1140205,1140206`. Its `SpeedSkill/HPSkill=140204` and `SpeedInherit=#4`, `HPInherit=#5`, `HPBase=#6` select the already-closed 1-based slots in `[A1]`. The reread Lv1 row has `[0.12,0,0,0.35,0.44,180]`. This reuses the known binding rule without recovering a constructor or sync formula.

After the inspected Skill02 creation, `[C3]` positions `CasterServant` relative to `Caster`, then writes **`SetActionDelay(Caster,0)`** and `ModifyCurrentSkillDelayCost(NormalizedValue=-1)`. The former is owner-side, not the initial servant queue position.

The invocation split is explicit:

| Path | Producer and callee | What is closed / what is not |
| --- | --- | --- |
| Servant selectable normal action | `[C1/C5]` skill `1140201 -> Skill01`; `[C2]` selects `EnemySelect` with `TargetAdjoinEntity`, entry `Servant_AglaeaServant_00_Skill11_Phase01`; `[C4]` calls its Phase02 on `Caster`, explicitly passing `AbilityTargetEntity` as inherent target. | A distinct selectable servant entry and damage path. Phase02 uses `InherentTargetEntity`, does servant-typed damage and reaches `SkillPerformFinish`. No generic queue initialization or debit algorithm is inferred. |
| Owner-coordinated Together | `[C3] Avatar_Aglaea_00_Skill11_Phase01` calls `TriggerParallelAbility` with two items: `Caster -> Avatar_Aglaea_00_Skill11_Phase02`; `CasterServant -> Servant_AglaeaServant_00_Skill11_Together_Phase01`. **Both** explicitly set `AbilityInherentTargetType=AbilityTargetEntity`. | `[C2]` assigns Together to **SkillP01**, not selectable Skill01. `[C4]` Together reads `CasterSummoner.Speed` and `Caster.Speed` separately, and damages its inherent target. No conclusion about coordinated normal-slot consumption or parallel completion order. |
| Inserted muted cleanup | `[C3] MAvatar_Aglaea_00_PassiveSkill01_BattleEvent.OnPhase1` uses `Retarget(AllLightTeam)` filtered by `MServant_AglaeaServant_Passive`, then `TurnInsertAbility(Servant_Aglaea_00_PassiveSkill01_ForceKill_Insert)` with **both performer and AbilityTarget = ParamEntity**. | Priority `AvatarBuffOthers`, `OwnerAliveState=Anyone`, `TargetAliveState=Mask_AliveOrLimbo`, `CanRunOnUnselectableTarget=true`, `ShowInActionBar=true` are explicit. `[C4]` kills `Caster` with both mute flags, sets die-immediately, and removes linked modifiers from `CasterSummoner`. Not the universal natural-death branch. |

`[C2/C5]` additionally bind `SkillP03[0] -> 1311494286` (sample row 1140205 Lv4: 1) and `SkillP04[0] -> -2017292130` (sample row 1140206 Lv3: 20). `[C4]` BattleCry installs a self modifier whose `OnStack` calls `ModifyActionDelay(ModifierOwnerEntity, 0 - 1311494286)`. DeathRattle installs a self modifier whose `OnDeathrattle` calls `ModifySPNew(CasterSummoner, AddValue=-2017292130)`. Those close normalized -1 and raw +20 operands, respectively; the latter is not relabeled as a shared Skill Point award.

### D — Ordinary Monster 1002011: not Avatar-only

`[D1] MonsterConfig[MonsterID=1002011]` explicitly references `MonsterTemplateID=1002011` and `SkillList=[100201101]`. `[D2]` that template explicitly names `Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json`. **These reference fields**, not numeric equality or the filename, establish the chain.

`[D3] MonsterSkillConfig[SkillID=100201101]` has `SkillTriggerKey=Skill04`, `ParamList[0]=2`. `[D4]` binds `-190305622 -> SkillParam(Skill04, Index=0)` and sets entry `Monster_Boss_Cocolia_P1_Weapon_Skill04_Phase01`. `[D5]` Phase01 calls Phase02 on `Caster`; Phase02 consumes `-190305622` in `DamageByAttackProperty( AllEnemy, AttackData{DamageType=Ice, AttackType=Normal, DamagePercentage=dynamic, SPHitRatio=1} )`.

This proves reuse of binding, phase dispatch, contextual selectors and damage-operation shape across a different source family. It does not prove all monster skills use that shape, that an ID ending in `01` means `Skill01`, or any configured-spawn final-stat formula.

## 3. P — Parameter / binding dictionary

| ID / vocabulary | Producer and binding/index rule | Consumer and ownership/scope | Proven scope / non-generalizable part |
| --- | --- | --- | --- |
| **P1 SkillParam** | A concrete actor's skill table supplies a `SkillTriggerKey` and `ParamList`; `ConfigCharacter.DynamicValues.Floats[hash].ReadInfo` selects `Type=SkillParam`, that trigger and a **0-based Index**. Ordinary avatar/servant rows also have a selected Level. | March `[A1-A3]`, servant `[C1/C2/C4/C5]`, monster `[D1-D5]`. Expressions read the resulting hash in that actor/invocation's binding context. | Shared data-facing structure across three families. AvatarSkillConfig, AvatarServantSkillConfig and MonsterSkillConfig are **different authorities**; not one global `(hash,index)` table. Arbitrary override/version precedence is not closed here. |
| **P2 SkillRank** | `[A5] AvatarRankConfig` contextual rank row; `[A2] ReadInfo(Type=SkillRank, TriggerKey=Rank06, Index=0/1)` selects `Param[0/1]`. | March Phase02 rank predicate -> temporary heal values -> named modifier injection -> `[A3] HealHP`. Ownership is the inspected March rank context, not the shield recipient's build. | Row, branch and consumers reread. `SkillAddLevelList` is a separate skill-level increment map, not `Param`; no universal rank-trigger evaluator is inferred. |
| **P3 SkillTreeParam** | `[A4] AvatarSkillTreeConfig[PointID=1001102]`, `PointTriggerKey=PointB2`, `ParamList[0]=1`; `[A2]` binds that trigger/index to `948615157`. | `[A3]` activation branch sets `_Tree02_LifeTimeAdd`; its working hash participates in AddModifier lifetime. | Typed trace binding and local gate are closed. The table is populated; empty Contents responses are not evidence that it is missing. No arbitrary trace-construction precedence is claimed. |
| **P4 #N** | `[C1]` chooses the corresponding `SpeedSkill/HPSkill`; `#N` selects **1-based** slot N of that skill's `[A1] ParamList`. | Dedicated servant HP/Speed construction input fields; not an ability expression hash or a zero-based `ReadInfo.Index`. | Reuse of the already-closed rule, checked against 11402/140204 here; the mature record retains its independent 11413 cross-sample. No renewed construction/formula/parser-body claim. |
| **P5 DynamicHash** | Numeric dictionary key in `DynamicValues.Floats`, or element of an expression's `PostfixExpr.DynamicHashes`; its binding comes from typed ReadInfo, a working-value producer or explicit injection. | `[A3]` uses different caller and modifier hashes for the same named transferred value; `[C4]` and `[D5]` resolve their own actor contexts. | A hash is a lookup operand, **not** an entity ID, source-family identity, globally unique mechanic or value. Binding/producer must accompany it. Hash algorithm and collision handling are not inferred. |
| **P6 DynamicValue operand** | Preserve `IsDynamic=false/FixedValue` versus `IsDynamic=true/PostfixExpr{OpCodes,FixedValues,DynamicHashes}`. Named DynamicValues maps at AddModifier/CreateServant are explicit transfer surfaces. | Lifetime, damage, shield, heal, delay and resource operands in A-C-D. `AQAR` is the inspected single-hash read form; the record only uses already-closed small expressions where needed. | Not a generic expression evaluator. Missing fields/defaults, arbitrary opcode bytes, rounding, saturation and final formula bodies remain outside v1. |
| **P7 ability-declared working environment** | `[A3]` Phase02 declares hashes `119443108`, `-889193254`, `-1361024633` with `ReadInfo.Type=None`; preceding `SetDynamicValue` tasks populate the corresponding working names. | Local **dataflow of this ability chain** feeds AddModifier lifetime and named heal values. The record does not assign an omitted ContextScope a guessed native enum. | A declaration alone does not produce a value. `None` is not zero, a missing skill row, or proof of a global variable. Native allocation, lookup fallback, shadowing, copy/reference inheritance, reentrancy and lifetime beyond this chain are unexported. |
| **P8 explicit caster working scope** | `[B2] DefineDynamicValue(Caster, Bounce_Count, ResetValue=5/4, ContextScope=ContextCaster)`. | Loop count hash `-2146792706` controls template invocations in Asta Phase02. | The literal caster scope is closed. Do not rename every temporary to `ContextAbility`, assume a fresh independent environment per loop, or derive generic RNG draw ordering from the counter. |
| **P9 modifier injection/environment** | `[A3] AddModifier.DynamicValues` transfers named shield/heal/aggro inputs; destination modifier declares its own Floats. | `MDF_ShieldPercentage -> -2062890509`, `MDF_ShieldValue -> 2126266902`, `MDF_HealPercentage -> 2054951994`, `MDF_HealValue -> 1276127143`, `MDF_AggroUp -> -994449299`, consumed by that modifier's callbacks. | Explicit caller-to-modifier dataflow is closed. Generic live/snapshot capture, overwrite/Replace order and environment teardown are not. Nearby `CasterDefence` property read is **not** an injected main-shield operand. |
| **P10 spawned-entity input environment** | `[C3] CreateServant.DynamicValues` explicitly passes three names; later owner `SetDynamicValue(TargetType=CasterServant)` writes `_CasterEnergy` and, in Skill11 Phase02, `_PairStanceDMG1/2`. | The creation call proves its explicit input map. The later paired stance values have Together damage StanceValue consumers in `[C4]`; this does not claim every creation input's complete consumer formula has been recovered. Entity targeting of the writes is explicit. | Do not replace these visible transfers with a claim that all caller parameters automatically migrate into a servant. Generic property sync/merge, object-lifetime policy and omitted write-scope defaults remain boundaries. |

**Binding example with both environments retained:**

```text
AvatarSkillConfig[100102,11].ParamList[0]
 -> March ConfigCharacter hash -1091495116
 -> Skill02_Phase02 AddModifier.DynamicValues.MDF_ShieldPercentage
 -> shield modifier hash -2062890509
 -> OnStack.InitShield.ShieldPercentage
```

This is transferable language. It does not expand `ShieldByCasterDefence` into an arithmetic formula.

## 4. E — Entity selector / ownership dictionary

| ID / selector | Exact producer / resolver surface | Invocation-context meaning in the anchors | Limit / non-generalization |
| --- | --- | --- | --- |
| **E1 Caster** | `[E0] AliasDict.Caster -> TargetFetchCaster`. | March/Asta/Monster phase calls explicitly execute on Caster. `[C3]` parallel items select different performers; `[C4]` the servant branch's Caster is the servant and CasterSummoner is its summoner. | Not always the root action owner or the calling node's entity. Modifier-caster snapshot/live selection and every dispatcher's native context construction are not recovered. |
| **E2 AbilityTargetEntity** | `[E0] -> TargetFetchAbilityTarget`; `SkillTargetEntityList` is `Caster -> TargetMapSkillTarget`. | Asta's first hit and March's shield use the skill-derived target; the servant normal Phase02 and both Aglaea parallel items demonstrate explicit inherent-target transfer. | TargetInfo on the callee and the call's `AbilityInherentTargetType` must be retained. It is not an unconditional immutable original-target alias. A bare `Target` is only a role word here, **not a proven universal raw alias**. |
| **E3 ParamEntity** | `[E0] -> TargetFetchParamEntity`; `TemplateParamEntityList -> TargetFetchTemplateEntityList`. | In B, the template selects the continuation entity and the supplied damage task consumes it. In C's Retarget/insert chain it is the filtered traversal entity. Callback predicates also use a callback-supplied ParamEntity. | Not always the external target, always the attacker, always Caster, or a global current target. Nested push/pop/restore and generic callback argument conventions are unexported. |
| **E4 CasterServant** | `[E0] TargetQuery(EntityTypeMask=Servant, AliveStateMask=Mask_AliveOrLimbo, Predicate=ByCompareTarget(ParamEntity.GetSummoner, Caster))`. | Resolves servants related to the **current context's Caster**; used by Aglaea for creation-adjacent writes, existing-servant heal and parallel dispatch. | Not the last-created entity, a fixed ID, or proof that the query is always single-valued. Exact lifecycle filtering is only the literal configured mask. |
| **E5 CasterSummoner** | `[E0] TargetSequence(Caster, TargetMapSummoner)`. | `[C4]` reads owner Speed, awards the raw DeathRattle resource and removes owner-linked modifiers from a servant execution context. | Not a universal `Owner`, `Source`, or originating action selector. No cross-family meaning is inferred from the name alone. |
| **E6 ModifierOwnerEntity** | `[E0] -> TargetFetchModifierOwner`. | `[A3]` shield/heal/property/removal target is the modifier holder, not necessarily its caster. `[C4]` self-installed BattleCry uses the servant holder; GoldenSword mark removal excludes the current holder. | Distinct from caster and invocation caller. Universal attribution and snapshot substitution remain unknown. |
| **E7 AllEnemy / supplied target pool** | `[E0] AllEnemy = Caster -> TargetMapEnemyTeamEntity -> TargetMapAllTeamMember`; `[B2]` explicitly supplies it to the template; `[D5]` directly damages AllEnemy. | The same pool-producing language can feed a multi-target mutation or an internal traversal. | A pool is not an externally selectable single target and not itself a random algorithm. The complete legality/selection pipeline remains W11. |

### External, current and original target are not interchangeable

`EnemySelect` / `FriendSelect` in ConfigCharacter establish the inspected external selection **class**, not the complete engine legality predicate. Call them external selection contracts, not a complete legal-target evaluator.

In B, keep at least: externally selected target -> first-hit `AbilityTargetEntity`; supplied bounce candidate list -> temporary `ParamEntity` -> bounce damage. In C, keep parent `AbilityTargetEntity` -> explicitly passed inherent target -> servant invocation's ability target. These are visible edges, not proof that every nested call preserves the caller's target automatically.

An analyst may name the root selection `T0` for a trace, but must not claim `OriginalTarget`, `Source`, `Owner` or generic `Target` aliases have been decoded. Whether an engine mutates/restores an ability target while traversing, how it snapshots the candidate list and how nested traversals restore ParamEntity remain explicit unknowns.

## 5. D — Dispatch / invocation dictionary

| ID / entry form | Caller -> callee and entity context | Parameter/target environment | Normal-action ownership and boundary |
| --- | --- | --- | --- |
| **D1 Skill EntryAbility** | Actor skill row -> matching ConfigCharacter SkillList entry -> named ability: March Skill02, Asta Skill02, servant Skill01, monster Skill04. | Typed skill bindings plus that skill entry's TargetInfo; retain source family, trigger and level where present. | Establishes a selectable skill entry where `UseType=SelectEntity`; does not recover universal command validation, costs or dispatcher body. |
| **D2 phase / nested TriggerAbility** | Phase01 explicitly calls another ability on Caster in A/B/D; servant normal Phase01 calls Phase02 on servant Caster in C. | March/Asta/monster callees declare `SkillTargetEntityList`; servant Phase02 declares `InherentTargetEntity` and its caller explicitly supplies `AbilityInherentTargetType=AbilityTargetEntity`. `IsSkillPerform=true` is preserved as a raw flag. | A call edge is not evidence of a fresh selectable action or a normal-slot debit. Environment inheritance and default inherent targets are not universalized. |
| **D3 passive/listener entry** | ConfigCharacter passive EntryAbility declarations -> explicit AddModifier task -> modifier `_CallbackList(Event, optional Priority, CallbackConfig)`. Examples: servant BattleCry/DeathRattle OnStart and Aglaea BattleEvent ability OnAdd. | Self-installed modifier holder versus callback parameter entity must be retained; callbacks may read bound skill values and injected/local values. | Data declaration and installation task are closed, **automatic passive activation timing is not**. Callback-array order is not a universal dispatcher total order; no same-priority tie-break inferred. |
| **D4 task-template continuation** | Asta LoopExecuteTaskList -> IncludeTaskListTemplate -> Bounce_SelectTarget -> TaskTemplateFetchParamSequence(ParamTaskList) -> caller-supplied task list. | Explicit ParamTarget pool, TemplateParamSequences and ParamEntity; Asta damage hash remains a caller-side operand while target comes from traversal. | Not a new character skill invocation. Do not guess loop scheduling, list snapshotting, nested-environment push/pop or RNG stream behavior. |
| **D5 TriggerParallelAbility** | Aglaea Skill11 Phase01 -> two ParallelAbilityList items: owner Phase02 on Caster and servant Together on CasterServant. | Both explicitly pass parent's AbilityTargetEntity as AbilityInherentTargetType. Subsequent owner-to-servant SetDynamicValue writes are independent visible dataflow, not an implicit copy-all rule. | Together belongs to servant SkillP01, not selectable normal Skill01. Fan-out is closed; join timing, interleaving, failure/cancel propagation and coordinated normal-slot accounting are not. |
| **D6 TurnInsertAbility** | March mark callback -> March counter ability (performer Caster; target ModifierOwnerEntity). Aglaea BattleEvent callback -> servant forced-cleanup ability (performer and target ParamEntity). | Retain AbilityName, TargetType, AbilityTarget, configured priority and flags. Neither inspected call supplies an explicit all-parameters copy map. | An inserted request is not the same as `SetActionDelay(0)` or granting a normal turn. Runnable ordering, same-priority arbitration and default environments remain engine boundaries. |
| **D7 callback-to-mutation continuation** | March OnStack/OnPhase1/OnDestroy, servant OnDeathrattle, GoldenSword mark OnCreate. | The callback's holder/caster/parameter roles and the concrete consumer operands define the local contract. | A configured event name identifies a dispatch surface, not a proof of cross-event chronological order. Muted ForceKill cleanup must not be used to order natural death callbacks. |

**Mixed dispatch warning:** `[A2/A3]`, `[B1/B2]`, `[D4/D5]` contain camera abilities in skill ability sets and `TriggerAbility` calls alongside battle-phase calls. Classify the resolved callee, not `TriggerAbility`, `SkillAbilityList` membership, `IsSkillPerform`, or a `_Phase`/`Camera` filename alone. A presentation wrapper can also contain a battle callback: March's `FireProjectile.OnProjectileHit` contains `DamageByAttackProperty`. Do not discard its child by classifying only the wrapper. `[A3]`

## 6. O — Battle-state mutation and execution-operation registry v1

The exact type prefix is `RPG.GameCore.` for O1-O17. **O18 keeps its actual obfuscated type.** Dispatch/traversal/environment operations are included because they reach an ordinary mutation; they are not misrepresented as immediate HP changes.

Each consequence below means an observable **source-declared operation category**, not a runtime-verified final number or a proven engine implementation. Opaque details remain attached to the entry.

| ID / opcode | Known operands and selector/target | Owner/context -> consequence; ordinary evidence | False friend / unresolved generic semantics |
| --- | --- | --- | --- |
| **O1 AddModifier** | `TargetType`, `ModifierName`, optional `LifeTime`, named `DynamicValues`; A uses AbilityTargetEntity, C self uses Caster. | Ability/callback -> installs named state whose callbacks/flags/property/shield/heal consumers are explicit. A3 shield; C3 GoldenSword mark; C4 BattleCry/DeathRattle. | Status UI is not the state mutation. Stacking replacement order, allocation, snapshot and generic callback firing policy remain unknown. |
| **O2 RemoveModifier** | `TargetType`, `ModifierName`; A mark removal additionally `OnlyRemoveCasterAdded=true`; C removes linked names from CasterSummoner or other traversal entities. | Callback/cleanup -> requests removal of named modifier state. A3 mark; C3 GoldenSword Retarget; C4 ForceKill_Insert. | Do not substitute RemoveEffect. Generic destruction order, matching defaults and teardown side effects are not closed. |
| **O3 DamageByAttackProperty** | `TargetType`, `AttackProperty.$type=AttackData`, DamageType, DamagePercentage, and occurrence-specific StanceValue / HitSplitRatio / SPHitRatio / AttackType / flags. | Ability or callback -> damage-operation request on the resolved entity/pool. A3 projectile hit; B2 first/bounce hits; C4 normal/Together; D5 Skill04. | DisplayData, hit effect, animation, screen shake are not numerical producers. Full mitigation/crit/split/resource/break evaluation belongs to W04/W06/W08. Missing operands are not guessed defaults. |
| **O4 HealHP** | A3: ModifierOwnerEntity, `FormulaType=HealByTargetMaxHP`, dynamic HealPercentage and ModifyValue; C3 existing-servant heal: CasterServant, same formula token, dynamic HealPercentage. | Modifier callback or owner skill -> healing request on holder/servant. A3 OnPhase1; C3 Skill02. | Do not promote heal display text to arithmetic. Formula body, rounding, overheal/clamp and healing modifiers remain later W05 work. |
| **O5 InitShield** | ModifierOwnerEntity, `FormulaType=ShieldByCasterDefence`, ShieldValue hash 2126266902 and ShieldPercentage hash -2062890509. | A3 shield modifier OnStack -> shield initialization using explicitly injected operands. | StackStatusDesc / ModifierOverrideOnHitEffect are not the shield formula. Snapshot capture, replacement total order, formula body and depletion-triggered destruction stay frozen W05 boundaries. |
| **O6 RemoveShield** | `TargetType=ModifierOwnerEntity`. | A3 shield OnDestroy -> shield-removal request. | Not RemoveEffect; this callback does not establish what destroys a depleted shield or a universal destroy ordering. |
| **O7 ModifySPNew** | A3 Skill02: Caster, `AddRatio=1`; C4 DeathRattle: CasterSummoner, `AddValue` reading -2017292130 (sample +20). | Skill/modifier callback -> resource modification of the explicitly selected entity. | Ratio and flat-value operands are distinct. Do not infer a shared player Skill Point award from the name `SP`, or infer caps/cost/energy formula; route W08. |
| **O8 ModifyActionDelay** | C4 BattleCry OnStack: ModifierOwnerEntity, `AddNormalizedValue` with raw postfix `AAABAAMR`, FixedValues=[0], DynamicHashes=[1311494286]. | Servant self modifier -> normalized delay modification; sample bound input gives -1. | Not absolute AV, SPD->AV formula or proof of a runnable queue position. Scheduler/rescale/tie-break remain frozen W07. |
| **O9 SetActionDelay** | C3 Skill02 create branch: `TargetType=Caster`, `Value=0`. | Owner ability -> writes owner action delay. | Not servant queue initialization and not TurnInsertAbility/OneMore. Requeue/ordering engine semantics unexported. |
| **O10 ModifyCurrentSkillDelayCost** | C3 same branch: `NormalizedValue=-1`; current-skill context rather than an explicit servant target. | Current owner skill -> changes its configured delay-cost surface. | Not a property Speed write or a new normal action. Relation to queue updates/cost accounting stays engine-owned. |
| **O11 TurnInsertAbility** | Exact caller/callee/target operands in D6; March priority AvatarInsertAttackSelf and AbortBehaviorFlags; Aglaea priority AvatarBuffOthers plus explicit alive-state/unselectable flags. | Callback -> requests named executable work. The Aglaea C3 call and C4 callee close through muted cleanup; A3 independently proves the March mark-to-insert request. | ShowInActionBar is display metadata, not evidence of normal-slot ownership. Generic priority dispatch, tie-break and cancellation are unknown. |
| **O12 TriggerParallelAbility** | `ParallelAbilityList[{TargetType, AbilityInherentTargetType, AbilityName}]` in D5. | Owner Skill11 -> owner and servant execution branches, both with explicit target transport, reaching damage. C3/C4. | Do not infer simultaneous completion, join algorithm or servant selectable-normal ownership. |
| **O13 CreateServant** | C3 `ServantID=11402`, explicit named DynamicValues; C1 table chooses C2 config and skill rows. | Ordinary owner ability -> creates a related battle servant with configured inputs; later CasterServant consumers distinguish the spawned context. | Not scene/maze ConfigSummonUnit or a same-number BattleEvent. No generic constructor, passive auto-entry, sync merge or initial scheduler placement is inferred. |
| **O14 ForceKill / SetDieImmediately** | **Two distinct types**, retained separately in the sequence. C4: ForceKill(Caster, MuteHpChange=true, MuteAllTriggerDeath=true), then SetDieImmediately(Caster); later RemoveModifier targets CasterSummoner. | Inserted servant execution -> explicitly muted forced death/cleanup path. C3 supplies the actual inserted call. | Not an animation-only disappearance and not proof that natural death suppresses DeathRattle. Internal death-state/teardown total order is unknown. |
| **O15 Retarget** | C3 GoldenSword OnCreate: TargetType=AllDarkTeamWithAllDarkTeamUnselectable, predicate excluding ModifierOwnerEntity, ByRandom=true, IncludeLimbo=true, MaxNumber=10, TaskList RemoveModifier(ParamEntity). C3 inserted cleanup also uses a filtered Retarget. | Callback -> selects/traverses candidate entities and executes ordinary mutation/dispatch continuation on ParamEntity. | Not the external legal target rule, not automatically mutation of the stored original target, and not proof of an RNG algorithm. Do not rename B3's different raw type. |
| **O16 DefineDynamicValue / SetDynamicValue** | **Distinct declaration/reset and write types**. B2 DefineDynamicValue has TargetType, DynamicKey, ResetValue, ContextScope=ContextCaster. A3 SetDynamicValue has DynamicKey/Value and branch-local explicit writes; C3 has writes targeted to CasterServant. | Execution environment -> values later read by loop count, shield/heal injection or servant damage operands. A3/B2/C3/C4. | Dynamic writes used only by display tasks are not automatically battle state. Omitted scopes, lifetime, shadowing and copy/reference transport remain unknown. |
| **O17 StackProperty** | A3: ModifierOwnerEntity, `Property=AggroAddedRatio`, PropertyValue hash -994449299. C4 AddSpeed modifier additionally declares a SpeedDelta property write. | Modifier callback -> battle-property contribution on holder; A3 has the full ordinary producer/injection/consumer edge. | StackStatusDesc and SetSummonerEnergyBarState are not interchangeable property/resource writes. Generic combination/rollback and queue consequences of Speed changes are not closed. C4 speed-combination details remain in the mature servant record. |
| **O18 unknown type GLOABNLLLEL** | The complete inspected B3 selection/continuation shape is recorded in anchor B: TemplateParamEntityList, predicate, ByRandom, IncludeLimbo, MaxNumber=1, TaskTemplateFetchParamSequence. | Ordinary Asta caller B2 supplies AllEnemy and a ParamEntity damage continuation. Thus the source-facing battle consumer is known while the engine type identity remains unknown. | **Unknown is retained, not guessed as Retarget.** No class-body, draw/replacement/stream or generic traversal algorithm recovery. |

**Control surfaces, not extra guessed mutations:** IncludeTaskListTemplate, TaskTemplateFetchParamSequence, LoopExecuteTaskList, PredicateTaskList and TriggerAbility are recorded through D2/D4 and their concrete children. `SkillExecutionStart`, `DamagePerformFinish`, `SkillPerformFinish` and waits are preserved as observed execution markers. v1 does not classify them all as presentation, translate them into universal action debits, or recover their dispatcher bodies.

**Property-read helper, not an additional confirmed mutation:** `SetDynamicValueByProperty` exposes `DynamicKey`, `ReadTargetType` and a `Value` property token. `[C4]` Together separately reads summoner Speed into `_CurrentSpeed` and servant Speed into `_ServantCurrentSpeed`. This is useful selector evidence, not itself a Speed change or a recovered downstream formula. `[A3]` also reads Caster Defence into `CasterDefence`, but the inspected main-shield injection does not pass that name. Proximity alone does not close a consumer edge or recover `ShieldByCasterDefence`.

**Registry admission rule:** a readable type string alone is insufficient. A new occurrence needs an ordinary producer/caller and a concrete battle consumer; an opaque operation can be admitted with an observed contract but must retain its opaque identity. This is a representative registry, not an absence list for unlisted types.

## 7. Cross-sample findings and negative knowledge

| Shared structural result | Heterogeneous check | Boundary retained |
| --- | --- | --- |
| Typed skill binding -> hash consumer | March skill parameter to shield injection; servant skill parameter to BattleCry/DeathRattle; monster skill parameter to direct damage. | Source table and entity context cannot be erased. Equal hashes/index positions do not establish global identity. |
| Phase call -> resolved callee -> target consumer | Avatar A/B, servant normal action C, monster D. | Explicit inherent-target transport differs from a callee reading SkillTargetEntityList. No universal implicit environment copy. |
| Modifier holder differs from caller/caster roles | March shield recipient; Aglaea enemy mark; self-installed servant BattleCry. | No universal Source/Owner alias or snapshot semantics. |
| Internal traversal -> ParamEntity continuation | Asta opaque random template; Aglaea literal Retarget and inserted cleanup. | Similar fields do not prove identical opcode identity; external selection legality, replacement and target restoration are not solved. |
| Distinct invocation ownership | Servant selectable Skill01 versus owner-triggered Together versus callback-inserted ForceKill. | A listed/triggered ability is not automatically a selectable normal action or a new normal-turn entitlement. |

Specific false friends retained:

- `SkillAbilityList`, `_Phase`, `_Test`, `Global`, `IL`, `Reference`, directory names and numeric IDs do not establish battle scope or entity identity. No whole-tree search or new source-family reclassification was performed here.
- Ability files are mixed: `TriggerEffect`, camera changes, blur, animation, HUD/description changes and display operands are not promoted into damage/shield/resource authority. Conversely, a projectile callback can contain actual damage.
- `SetSummonerEnergyBarState` describes UI state in the inspected servant callback; its name alone is not a ModifySPNew/resource-economy contract.
- Main March shield dispellability and its already-closed numeric producer remain closed in the mature record; no old “unresolved/missing” conclusion is restored. v1 does not re-prove them or broaden their formula authority.
- OneMore is not downgraded to an unknown flag; its existing source-facing protocol remains in the timeline record. This v1 does not equate it to every delay or inserted-ability operation.
- Asta's actual B3 raw type is preserved even where older prose used “Retarget” as traversal shorthand. An unknown class identity and a proven downstream battle consumer can coexist.

### Tool negative knowledge from this reread

GitHub Contents-backed `fetch_file` returned `content=""` for the large AvatarSkillConfig, AvatarSkillTreeConfig and MonsterSkillConfig while returning their blob SHAs. A raw-file fetch also rejected the large AvatarSkillConfig. Direct Git blob reads recovered the actual content, including March `100102`, Aglaea `140204`, populated trace rows and MonsterSkill `100201101`. These are **tool transport limits**, not source absence evidence.

High-cost reusable blob identities (all tied to the pinned path):

| File | Exact blob |
| --- | --- |
| ExcelOutput/AvatarSkillConfig.json | `a5416ced941c247d475b2aaa83277b9cdf474dd9` |
| ExcelOutput/AvatarSkillTreeConfig.json | `cee634adac569ad417ebedf55f9be67caa05fab8` |
| ExcelOutput/MonsterSkillConfig.json | `b6cbf024dd00a13fee5578d0e3eca101d467a1e6` |
| Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json | `d1da985fbac1bcf4e23f3c1dcdf7dfd11bcb5c96` |
| Config/GlobalConfig/TargetAliasConfig.json | `f5842163ac2eafc9f42316e521512b22f7a0b5fe` |

Replay a large file through `GET /repos/DimbreathBot/TurnBasedGameData/git/blobs/<blob>` after verifying its pinned path-to-blob association. Use named occurrences/record keys below, not line offsets in a tool's escaped JSON wrapper. A guessed standalone `Bounce_SelectTarget.json` returned 404; the real definition is the named entry in the consolidated B3 file. No absence claim follows from that navigation miss.

## 8. Remaining engine/export boundaries

| Boundary | What v1 supplies instead of guessing |
| --- | --- |
| Binding/environment implementation | Typed producer/index, explicit writes and transfer maps. No generic scope defaults, shadowing, context allocation, copy/reference, reentrancy, hash collision or expression evaluator implementation. |
| Selector/dispatcher implementation | Exact alias recipes and per-call target/performer operands. No universal OriginalTarget/Source/Owner, nested traversal restoration, implicit target inheritance or generic dispatcher body. |
| W05 shield/heal/modifier engine | Named formula/operands, callback holder and explicit property mutations. No ShieldByCasterDefence expansion, snapshot capture, Replace total order or depletion destruction. |
| W07 timeline | Separate normalized delay, absolute delay write, current-skill cost and inserted work. No SPD->AV, queue/requeue/rescale/tie-break or exact OneMore runnable order. |
| W10 callback/death | Distinct callback entry names and configured insertion flags. No universal callback dispatcher, same-priority arbitration or death/destruction total order. |
| W12 RNG | Actual random-selector operands, continuation and opaque identity where applicable. No RNG stream, RandomConfig algorithm or final status-probability evaluator. |
| W13 servant | Explicit creation/ownership/parameter transfer and normal-versus-Together-versus-inserted paths. No automatic passive-entry timing, property-sync merge, initial queue or coordinated normal-slot accounting. |
| W14/W17 frozen residuals | No new authority found or searched for here. Configured-spawn stat formula/HardLevel+Elite precedence, Assistant owner/ID transport and CommonSkillPool payload remain at their existing named boundaries. W17's completed broad reverse scan is not reopened. |

No final community combat formula is substituted for an unavailable consumer. No same-release keyword re-search is counted as progress.

## 9. Discovery / later-work routing

| Entry edge retained | Routing and stop condition |
| --- | --- |
| DamageByAttackProperty / AttackData across B/C/D, with StanceValue, HitSplitRatio, SPHitRatio and flags only where present | **W04 next**: select one ordinary direct hit, trace source operands to damage-state consequence, then cross-sample. Reuse P/E/D/O3 instead of rebuilding the frame. Stance/resource operands are dependency edges, not completed Break/Resource mechanics. |
| C3 GoldenSword mark `OnBeforeBeingHitAll -> ModifyDamageData(Defender_AllDamageTypeTakenRatio)` under a rank predicate; the ordinary mark-adder is already visible | W04/W09: trace damage-context mutation and attribution/order. This is a concrete later-slice entry, not a final modifier arithmetic claim or a new global opcode survey. |
| C4 `MServant_Aglaea_00_HitDamageSplit.OnBeforeBeingHitAll -> HitDamageSplit` seen beside the mature servant chain | W04/W09 candidate: require its own complete installation/consumer edge before promoting a generic split contract. v1 intentionally does not add it to the confirmed registry merely because the definition was encountered. |
| HealHP, InitShield/RemoveShield, StackProperty and callback lifetime/stacking fields | W05/W09: independent healing and lifecycle slices, with existing March numeric/dispellability closure retained. No renewed frozen shield-formula search. |
| ModifySPNew AddValue versus AddRatio, skill-table SPBase/BPNeed fields | W08: establish actual Energy/shared Skill Point ownership, gain/cost/caps; the raw SP operation is not a ready-made player-resource interpretation. |
| Asta GLOABNLLLEL versus literal Retarget, selection filters and ParamEntity | W11/W12 source-facing residual: preserve literal identity and investigate only a required concrete target/selection edge. Generic RNG algorithms remain frozen. |

No new battle-state consequence requiring W19+ was established. The opaque-type clarification is a vocabulary/authority correction within W03/W11/W12, not a new mechanism. The adjacent damage-context operations route to existing W04/W09; they do not justify a scope expansion here.

## 10. Exit check and documentation impact

- [x] Parameter/binding dictionary names producer, index rule, consumer, ownership/scope and limits.
- [x] Selector dictionary separates external selection, ability target, traversal parameter, performer, servant/summoner and modifier holder.
- [x] Dispatch dictionary covers skill entry, phase/nested call, passive/listener, template continuation, parallel and inserted work without inventing normal-action accounting.
- [x] Registry contains actual ordinary consumers and retains an encountered opaque type as opaque.
- [x] Avatar + Servant + Monster heterogeneous ordinary evidence is present.
- [x] Presentation false friends and frozen engine/export boundaries are explicit.
- [x] Later W04/W06/W05/W09/W08 threads can reuse P/E/D/O without reconstructing each character's entire execution frame.

Only this durable record is added by the R0 checkpoint. The worklist's broad/generic leaves are **not** checked; the inventory's source-family classification is unchanged; no duplicate global index sweep is needed. This does not claim the pre-existing broad L03/L04/L05 obligations are exhausted.

Validation for this documentation-only change: manual producer/consumer reread at the pin; local Markdown structure/reference checks; verify the committed diff contains only this record and PR #8 remains Draft. No Fast/Direct runtime test result is claimed.

**Next recommended vertical slice: W04 — Damage.** It is not started by this checkpoint.

## 11. Sources and replay index

All references in this table are exact-pin primary sources. Named record/ability/modifier occurrences, not matching numeric IDs alone, identify the evidence.

| Code | Exact pinned source | Occurrences reread for this dictionary |
| --- | --- | --- |
| A1 | [AvatarSkillConfig][raw-a1] | SkillID 100102 Lv11/Lv12; SkillID 140204 Lv1; their SkillTriggerKey and ParamList. Large-file blob fallback used. |
| A2 | [March ConfigCharacter][raw-a2] | Skill02/SkillP01/Skill03 entries, SkillAbilityList and DynamicValues.Floats typed bindings. |
| A3 | [March Ability][raw-a3] | Skill02 Phase01/02; GlobalModifiers main shield, mark and their named callbacks; Skill01 projectile hit as mixed-wrapper cross-check. |
| A4 | [AvatarSkillTreeConfig][raw-a4] | PointID 1001102 / PointB2 / ParamList. Large-file blob fallback used. |
| A5 | [AvatarRankConfig][raw-a5] | RankID 100106 Param; adjacent rank SkillAddLevelList distinguishes the producer spaces. |
| B1 | [Asta ConfigCharacter][raw-b1] | Skill02 external target and EntryAbility. |
| B2 | [Asta Ability][raw-b2] | Skill02 Phase01/02, Bounce_Count definition, LoopExecuteTaskList, IncludeTaskListTemplate and supplied ParamTaskList. |
| B3 | [GlobalTaskListTemplate][raw-b3] | TaskListTemplate named Bounce_SelectTarget; exact obfuscated type and complete selector/continuation operands. |
| C1 | [AvatarServantConfig][raw-c1] | ServantID 11402, explicit Config/SkillIDList and #N/SkillID inputs. |
| C2 | [Aglaea servant ConfigCharacter][raw-c2] | Skill01 versus SkillP01/P03/P04, SkillAbilityList ownership and SkillParam bindings. |
| C3 | [Aglaea owner Ability][raw-c3] | Skill02 create/existing-servant heal; Skill11 parallel and servant-targeted working writes; BattleEvent modifier OnPhase1/OnAdd; GoldenSword ordinary add and OnCreate/OnBeforeBeingHitAll consumers. |
| C4 | [Aglaea servant Ability][raw-c4] | Together, normal Skill11 Phase01/02, ForceKill_Insert, BattleCry and DeathRattle; adjacent named global modifiers only to the boundaries stated. |
| C5 | [AvatarServantSkillConfig][raw-c5] | 1140201 Lv1, 1140205 Lv4-Lv6, 1140206 Lv3-Lv4 trigger/ParamList samples. |
| D1 | [MonsterConfig][raw-d1] | MonsterID 1002011 explicit MonsterTemplateID and SkillList. Blob `f0096989cc770b8e50746c3ac929f3a7eaa58fc9`. |
| D2 | [MonsterTemplateConfig][raw-d2] | MonsterTemplateID 1002011 explicit JsonConfig. Blob `cddb6b3d6d46ec12dc4c7a985190723aadbca57e`. |
| D3 | [MonsterSkillConfig][raw-d3] | SkillID 100201101 / Skill04 / ParamList[0]. Large-file blob fallback used. |
| D4 | [Monster ConfigCharacter][raw-d4] | Skill04 EntryAbility and hash -190305622 binding. |
| D5 | [Monster Ability][raw-d5] | Monster_Boss_Cocolia_P1_Weapon_Skill04_Phase01 -> Phase02 -> AllEnemy DamageByAttackProperty. |
| E0 | [TargetAliasConfig][raw-e0] | Caster, AbilityTargetEntity, SkillTargetEntityList, AllEnemy, ModifierOwnerEntity, TemplateParamEntityList, ParamEntity, CasterServant and CasterSummoner. |

Mature evidence reused, without reopening its frozen engine residuals:

- [March shield](../characters/march_7th_preservation_skill02_shield.md).
- [Aglaea / servant](../characters/aglaea_servant_11402_reference_chain.md).
- [Monster 1002011](../monsters/monster_1002011_reference_chain.md).
- [Timeline / OneMore](timeline_one_more_and_speed_boundary.md).
- [Ordinary RNG / callbacks](ordinary_rng_callback_reference_chains.md); use anchor B above for the literal-type clarification.
- [Global/shared reverse scan](global_shared_reverse_scan.md).

[raw-a1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillConfig.json
[raw-a2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Mar_7th_00_Config.json
[raw-a3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json
[raw-a4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillTreeConfig.json
[raw-a5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarRankConfig.json
[raw-b1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Asta_00_Config.json
[raw-b2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json
[raw-b3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json
[raw-c1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarServantConfig.json
[raw-c2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json
[raw-c3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json
[raw-c4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json
[raw-c5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarServantSkillConfig.json
[raw-d1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterConfig.json
[raw-d2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterTemplateConfig.json
[raw-d3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterSkillConfig.json
[raw-d4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json
[raw-d5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_W1_CocoliaP1_01_Ability.json
[raw-e0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/TargetAliasConfig.json
