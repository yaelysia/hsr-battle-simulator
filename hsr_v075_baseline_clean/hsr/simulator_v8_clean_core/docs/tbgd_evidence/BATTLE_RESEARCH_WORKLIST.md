# TBGD battle research living worklist

## Purpose

This document is the **living work ledger** for the normal-combat archaeology tracked by Issue #7 and PR #8.

It converts the semantic scope in `BATTLE_SCOPE.md` and the source-family triage in `SOURCE_FAMILY_INVENTORY.md` into concrete research work packages and reviewable checklists.

This is deliberately **not a fixed taxonomy and not a fixed denominator**. The current work packages are the best decomposition supported by the evidence known at this checkpoint. During archaeology we may discover a new battle mechanism, prove that two packages are the same mechanism, split one package into several independently owned mechanisms, defer a mode-owned mechanism, or prove that a suspected mechanism is not needed for ordinary combat. The worklist must change when the evidence changes.

Pinned TBGD revision for the current ledger:

`14c1d18f91a8101d610e6c523447a7517de3fae1`

Initial worklist review date: **2026-09-08**.

## Governing principle: automate navigation, not semantics

The research model is intentionally hybrid.

Automation/search/scripts should aggressively reduce mechanical archaeology cost by:

- enumerating every candidate source family and path;
- indexing IDs, hashes, DynamicValue bindings, parameter arrays and reference edges;
- building forward and reverse-reference candidate graphs;
- locating repeated structural patterns across many actors/mechanics;
- diffing records and checking pinned path/blob identity;
- surfacing suspicious collisions, orphaned producers and unresolved consumers.

Automation must **not** decide that a source is combat-authoritative, non-combat, deferred, formula-equivalent or semantically identical. In particular, a script must not permanently discard candidates because of a filename, directory, prefix, ID collision or apparent presentation/event ownership.

Human semantic audit remains required for:

- ordinary-combat versus maze/scene/presentation/event ownership;
- formula operands and operator meaning;
- DynamicHash/DynamicValue ownership;
- target-selection meaning;
- modifier lifetime, stacking, refresh and snapshot semantics;
- callback/event ordering;
- action/timeline semantics;
- scaling joins and precedence;
- shared versus mode-owned primitives;
- logical battle timing versus presentation timing.

The intended division of labor is:

> automation makes it hard to miss candidates; manual review decides what the candidates actually mean.

## Worklist maintenance contract

This section is normative for maintaining this file.

### 1. The list is expected to change

The current `W01..W18` set is an **initial decomposition**, not a promise that ordinary combat contains exactly eighteen mechanisms.

When new evidence reveals an unrepresented battle-state consequence:

1. add a new work package immediately (`W19`, `W20`, ...), or add a named child package if it clearly belongs under an existing parent;
2. record the discovery source and why the existing taxonomy did not cover it;
3. set its initial work status and evidence maturity honestly;
4. update the summary table and change log in the same evidence checkpoint.

Do not postpone a newly discovered mechanism merely to preserve the apparent completion percentage.

### 2. Packages may be split, merged, deferred or retired

A work package may be changed when manual evidence supports it:

- **split** — one package turns out to contain mechanisms with different owners/semantics; preserve the parent and point to the children;
- **merge** — two packages are proven to be the same underlying authority; keep one canonical package and mark the other `merged_into:<id>`;
- **defer** — the mechanism is real combat authority but belongs only to an explicitly deferred mode in the current phase;
- **retire_not_required** — manual evidence proves the suspected mechanism/source has no ordinary-combat consequence;
- **reopen** — later evidence invalidates a previous closure.

Never silently delete historical worklist items. A removed requirement is useful negative knowledge and must remain traceable through the change log.

### 3. Checkbox meaning is narrow

A checked leaf item means only:

> the exact statement in that leaf has sufficient evidence at the pinned revision.

It does **not** mean the whole parent mechanism is complete.

If later evidence invalidates a checked leaf, uncheck it, explain why in the package notes/change log, and preserve the superseded evidence record if it remains useful history.

### 4. Work status and evidence maturity are separate

Work-package status:

- `candidate_new` — newly discovered and not yet scoped;
- `active` — in-scope work remains;
- `blocked_evidence` — a named source/consumer is missing or unavailable at the pin;
- `mechanism_closed` — all ordinary-combat semantic obligations currently known for the package are closed;
- `deferred` — valid combat mechanism intentionally postponed by scope;
- `retired_not_required` — manually proven unnecessary for current ordinary-combat scope;
- `merged_into:<id>` — tracked by another canonical package.

Evidence maturity for individual claims remains the ledger-wide sequence:

`candidate -> manually_confirmed -> cross_validated -> runtime_verified`

A package can contain a `runtime_verified` leaf and still remain `active` because other semantics are unresolved.

### 5. Freshness is part of correctness

Every active package must maintain:

- `Last reviewed` date;
- current strongest evidence/anchors;
- unresolved questions;
- one explicit `Next closure` target.

A meaningful PR checkpoint that changes a mechanism's interpretation should update this file in the same checkpoint whenever practical.

A stale checked box is worse than an unchecked box.

### 6. Do not publish a misleading completion percentage

Because the denominator can change as new mechanisms are discovered or retired, raw percentages such as `12/18 = 67% complete` are not authoritative.

If progress is summarized, report instead:

- packages `mechanism_closed`;
- packages `active`;
- packages `blocked_evidence`;
- packages `deferred`/`retired_not_required`;
- newly discovered packages since the previous checkpoint;
- major unresolved P0/P1 closures.

A percentage may be used only after the source-family inventory and mechanism taxonomy have stabilized enough to define the denominator explicitly.

## Current work-package summary

| ID | Work package | Priority | Work status | Strongest current evidence | Last reviewed | Next closure |
| --- | --- | --- | --- | --- | --- | --- |
| W01 | Character battle-stat construction | P1 | `active` | candidate / partial wiring known | 2026-09-08 | close final ordinary avatar stat composition at battle start |
| W02 | Ordinary character skill numeric/value authority | P0 | `active` | March `100102` producer/binding/consumers manually confirmed; Dan Heng cross-check | 2026-09-08 | generalize producer/index model across another unrelated ordinary character and record version-drift behavior |
| W03 | Skill execution graph and combat operation dispatch | P0 | `active` | manually confirmed March/Aglaea examples | 2026-09-08 | build reusable execution/opcode mapping beyond representative skills |
| W04 | Damage resolution | P0 | `active` | raw multiplier plus shared DamageBehavior/Super-Break producer candidates | 2026-09-08 | close generic damage operands and composition/precedence |
| W05 | Healing and shielding | P0 | `active` | March Skill02 numerics, Replace lifecycle hooks and Shield operands confirmed | 2026-09-08 | close generic ShieldByCasterDefence/snapshot/depletion semantics and one independent healing chain |
| W06 | Weakness, toughness and Weakness Break | P0 | `active` | shared break-state/elemental template chains manually confirmed | 2026-09-08 | close stance/toughness mutation and break state transition chain |
| W07 | SPD, action value, turn/timeline and advance/delay | P0 | `active` | operation-level scheduling semantics confirmed; generic scheduler implementation is `blocked_evidence` | 2026-09-09 | continue exported operation/lifecycle edges only; reopen generic scheduler only with a new authoritative engine source |
| W08 | Energy, Skill Points and actor-specific resources | P1 | `active` | shared resource mutation producers identified | 2026-09-08 | close one full generation/consumption/callback chain for each shared resource |
| W09 | Buff/debuff/modifier/control semantics | P0 | `active` | formal Shield plus multiple ordinary shared property/modifier samples | 2026-09-08 | build lifetime/stack/refresh/dispel/immunity semantic rules |
| W10 | Trigger, callback and event ordering | P0 | `active` | priority domains plus Aglaea natural pre-death/death-rattle/death-listener and muted forced-cleanup surfaces confirmed | 2026-09-09 | expand source-facing event/lifecycle chains; generic tie-break/cross-event dispatcher is `blocked_evidence` |
| W11 | Targeting, adjacency, aggro, retargeting and internal traversal | P1 | `active` | friend/enemy target, aggro and Asta random-target sample confirmed | 2026-09-08 | distinguish legal external target contract from internal execution traversal generically |
| W12 | RNG and random-choice authority | P0 | `active` | RandomConfig, random target and SetDynamicValueByRandom ordinary chains confirmed; generic algorithm/stream is `blocked_evidence` | 2026-09-09 | continue primitive census only when high-signal; reopen generic RNG contracts only with a new engine source |
| W13 | Summons, servants/memosprites and special battle entities | P0 | `active` | Aglaea construction numerics, self scheduling, natural lifecycle surfaces and priority-tiered muted forced cleanup confirmed | 2026-09-09 | close source-facing property sync/resource/JoinSkill semantics; passive auto-entry and universal death order remain blocked |
| W14 | Monster final stats and difficulty scaling | P0 | `active` | ordinary HardLevelGroup five-stat inputs + typed HardLevel property read + stage/elite/phase topology confirmed | 2026-09-09 | pursue source-facing Stance/explicit MonsterUnique cases; final configured-spawn operator is `blocked_evidence` |
| W15 | Enemy AI and decision authority | P1 | `active` | AI reference/random-source edges confirmed; final selection semantics unresolved | 2026-09-08 | close skill selection, target choice, priority/weights and randomness |
| W16 | Encounter/wave/spawn/phase/stage-ability construction | P1 | `active` | wave, pre/post-spawn StageAbility binding and phase-property inputs confirmed | 2026-09-08 | close remaining spawn/transition/reinforcement and battle-end semantics |
| W17 | Global/shared battle producers | P0 | `active` | broad reverse scan complete; AssistantTrigger/CommonSkillPool/loader tails frozen as ownership/export gaps | 2026-09-09 | inspect only new high-signal shared definitions with a concrete ordinary consumer; do not repeat broad scan |
| W18 | Equipment/build effects and Technique-to-battle boundary | P1 | `active` | one Light Cone effect chain exists | 2026-09-08 | close relic/set/rank semantics and battle-entry Technique effects |

## Detailed checklist

### W01 — Character battle-stat construction

Goal: establish the authoritative composition of playable-character battle-start properties, separating progression inputs from the values actually consumed by battle runtime.

- [ ] Locate ordinary avatar base-stat authority at the pinned revision.
- [ ] Trace level/promotion/stat-growth inputs only as far as they produce battle-start properties.
- [ ] Determine equipment/relic/traces/eidolons contributions and precedence at battle initialization.
- [ ] Separate static construction from modifiers applied after battle initialization.
- [ ] Confirm special properties such as effect hit/resistance, break effect, energy-related properties and elemental bonuses where represented.
- [ ] Record explicit negative knowledge for progression-only cost/material/reward neighbors.
- [ ] Cross-validate at least one fully constructed avatar property set against an independent source/runtime observation.

**Next closure:** one complete avatar battle-start stat equation with source joins and precedence.

### W02 — Ordinary character skill numeric/value authority

Goal: resolve where ordinary skill parameter values actually come from and how typed parameter references bind to those values.

- [x] Confirm March Preservation `Skill02` DynamicHash bindings to `SkillParam(Skill02,index=0..4)`.
- [x] Reject same-ID `ILBattleAvatarSkill[100102]` as ordinary March authority after parent-family review.
- [x] Locate the pinned ordinary numeric source for March `SkillID=100102`: `ExcelOutput/AvatarSkillConfig.json` per-level `ParamList` rows.
- [x] Determine ordinary `SkillParam` level indexing and keep rank/tree parameters in their distinct producer spaces.
- [x] Map `SkillParam`, `SkillRank` and `SkillTreeParam` to `AvatarSkillConfig`, `AvatarRankConfig` and `AvatarSkillTreeConfig` producer/index spaces and their typed ConfigCharacter consumers.
- [x] Cross-check the ordinary `SkillParam` binding model on March and an unrelated ordinary character (Dan Heng).
- [ ] Add at least one further unrelated ordinary-character cross-check before treating every producer-family edge as globally exhaustive.
- [ ] Document version-drift behavior when current/live tables contain values absent from the pinned corpus.

**Next closure:** generalize the closed producer/index model without reopening the disproven `100102` omission hypothesis.

### W03 — Skill execution graph and combat operation dispatch

Goal: turn TBGD Ability/ConfigCharacter data into an audited battle-execution language rather than a set of one-off character traces.

- [x] Confirm a complete ordinary skill wiring example from character identity through ConfigCharacter to ConfigAbility.
- [x] Confirm that Ability files are mixed and require operation-level semantic review.
- [ ] Inventory battle-state-mutating opcode families reached by ordinary characters.
- [ ] Distinguish execution operations from animation/camera/presentation operations even when colocated.
- [ ] Trace prepare/entry/phase/passive/insert/counter/follow-up dispatch where each changes reachable battle state.
- [ ] Establish ownership and parameter environment for nested/sub-ability execution.
- [ ] Record unknown opcodes as explicit unresolved language entries rather than ignoring them.

**Next closure:** reusable opcode catalog for common ordinary skill execution.

### W04 — Damage resolution

Goal: derive the actual raw-data inputs and runtime ordering that produce damage.

- [x] Confirm one raw numeric skill multiplier (`MonsterSkillConfig[100201101].ParamList[0] = 2`) through DynamicHash to `DamagePercentage` consumer.
- [ ] Identify generic damage opcode(s) and operand roles.
- [ ] Close attacker scaling-stat selection and base multiplier semantics.
- [ ] Close additive/multiplicative damage bonus, vulnerability and mitigation layers.
- [ ] Close DEF and resistance layers and their ordering.
- [ ] Close critical-hit authority and any forced/non-critical exceptions.
- [ ] Close multi-hit/adjacent/blast/AoE internal traversal semantics.
- [ ] Close damage-event emission and downstream callback timing.
- [ ] Cross-validate at least one full ordinary damage result numerically.

**Next closure:** generic damage operand/order chain, not another isolated multiplier.

### W05 — Healing and shielding

Goal: establish healing/shield arithmetic and lifecycle semantics.

- [x] Confirm `MAvatar_March7th_00_BPSkill_Shield` is a formal Shield modifier.
- [x] Confirm `UseSnapshotEntity=true` for the inspected March shield modifier.
- [x] Resolve March ordinary Skill02 percentage/flat/lifetime/threshold/aggro parameter numerics and consumer mapping.
- [x] Confirm March shield reapplication is `Stacking="Replace"`, `OnStack -> InitShield`, and `OnDestroy -> RemoveShield` at the character-local graph level.
- [x] Confirm March Skill02 lifetime input is base `SkillParam[1]` plus PointB2's pinned `+1` increment.
- [ ] Determine generic `ShieldByCasterDefence` arithmetic and exact scaling-stat snapshot scope/capture point.
- [ ] Determine generic replacement callback order, depletion/lifetime-to-destroy timing and shield dispellability.
- [ ] Trace one ordinary healing formula from producer to final HP mutation.
- [ ] Determine healing modifiers, caps/overheal behavior where represented, and callback timing.

**Next closure:** generic shield engine semantics plus one independent healing chain; do not resume March numeric-source discovery.

### W06 — Weakness, toughness and Weakness Break

Goal: reconstruct the full stance/toughness state machine and break consequences.

- [ ] Locate authoritative enemy/player weakness representation and weakness matching rules.
- [ ] Locate base/final Stance/Toughness value construction.
- [ ] Trace skill toughness-damage inputs to the mutation consumer.
- [ ] Determine behavior for non-matching weakness and any universal/reduced toughness damage cases.
- [ ] Close transition into broken state and recovery transition.
- [x] Confirm ordinary shared `StanceBreakState` can apply normalized action delay and owns a break/recovery lifecycle for monsters wired to the common passive.
- [x] Confirm ordinary elemental `StanceBreak_*` templates apply element-specific shared break statuses/damage paths.
- [ ] Close Weakness Break damage/status application arithmetic and elemental specialization generically.
- [ ] Trace break-trigger callbacks and ordering relative to hit/damage/death.

**Next closure:** one complete hit -> toughness zero -> break -> recovery chain with arithmetic and ordering.

### W07 — SPD, action value, turn/timeline and advance/delay

Goal: identify the authority that determines when every battle entity acts.

- [ ] Prove SPD-to-action-value conversion from raw/runtime semantics. **Blocked evidence:** pinned TBGD exports data-facing constants/opcodes but no GameCore scheduler implementation source.
- [ ] Identify initial AV/turn-queue initialization and equal-delay tie break. **Blocked by the same exported-engine boundary.**
- [x] Confirm `ModifyActionDelay`, `ModifyCurrentSkillDelayCost`, `SetActionDelay` and `TurnInsertAbility` are distinct scheduling surfaces, with source-backed context-dependent routing on Seele/Jingliu.
- [ ] Close action advance/delay clamp/rounding and normal requeue semantics. **Blocked evidence:** generic scheduler consumer unavailable.
- [ ] Determine round/cycle boundary semantics used by ordinary combat from exported source-facing rules.
- [ ] Determine how SPD changes affect already-scheduled action value; Hanya confirms the property write but the reschedule consumer is not exported.
- [x] Confirm Servant 11402 has its own speed/action-delay state and a servant-owned `ModifyActionDelay(-1 normalized)` passive, establishing independent schedulability at the data level.
- [x] Separate logical scheduling operations from animation/presentation/preshow waits in inspected ordinary graphs.
- [ ] Close exact `OneMore` queue/status-tick semantics; source confirms it is distinct from delay mutation/insert action but not its scheduler implementation.

**Next closure:** exported operation/lifecycle edges only; generic SPD→AV/queue/requeue/rescale/tie-break remains `blocked_evidence` until a new authoritative engine source appears.

### W08 — Energy, Skill Points and actor-specific resources

Goal: close shared and actor-owned resource state mutation semantics.

- [ ] Trace Energy maximum/initial value sources.
- [ ] Trace Energy generation, consumption and ultimate availability timing.
- [ ] Trace shared Skill Point initialization, gain, cost and caps.
- [ ] Determine callback ordering around resource consumption/generation.
- [ ] Inventory generic resource/stack/charge/counter opcodes.
- [ ] Close one actor-specific gauge from initialization through spend/gain and action gating.
- [ ] Distinguish UI/display counters from battle-authoritative resources.

**Next closure:** one complete Energy chain and one complete SP chain.

### W09 — Buff/debuff/modifier/control semantics

Goal: derive the shared lifecycle rules that many character/enemy effects reuse.

- [x] Confirm ordinary battle modifiers can carry lifetime and snapshot configuration.
- [ ] Inventory add/remove/replace modifier operations.
- [ ] Determine stack count, max stack and per-stack value semantics.
- [ ] Determine duration decrement owner/timing.
- [ ] Determine refresh versus extend versus replace behavior generically.
- [ ] Determine snapshot versus live-property reads generically.
- [ ] Trace dispel categories and dispel immunity.
- [ ] Trace crowd-control application, immunity, resistance and expiration.
- [ ] Close DoT lifecycle and tick timing as a modifier specialization.

**Next closure:** one reusable modifier lifecycle state machine validated on multiple mechanics.

### W10 — Trigger, callback and event ordering

Goal: establish deterministic ordering for event-driven battle behavior.

- [x] Confirm an ordinary servant death-rattle/death-event subgraph exists.
- [ ] Inventory ordinary event/trigger names and registration mechanisms exhaustively.
- [ ] Trace on-attack/on-hit/on-damage distinctions generically.
- [x] Confirm priority domains are first-class pinned inputs and that lower numeric values are earlier/higher priority within the inspected domains.
- [x] Validate one multi-trigger ordinary interaction with source-backed causal order (Aglaea Rank02 listener -> OnStack initialization -> later OnBeforeHitAll consumer).
- [x] Confirm ordinary death-rattle can continue through priority-tiered `TurnInsertAbility`, and muted `ForceKill(...MuteAllTriggerDeath=true)` is a distinct cleanup path.
- [x] Confirm ordinary Bailu revival uses distinct `OnBeingLimbo -> OnLimboWaitHeal -> inserted revive ability` stages rather than an immediate pre-death rollback.
- [x] Confirm Aglaea Servant 11402 exposes separate natural `OnBeforeDying`, formal `OnDeathrattle`, owner `OnListenCharacterDie`, and later death-dependent removal surfaces.
- [x] Confirm Aglaea BattleEvent `OnPhase1` can priority-insert a dedicated servant forced-cleanup ability at `AvatarBuffOthers`, which then uses `ForceKill(...MuteAllTriggerDeath=true)` + `SetDieImmediately`.
- [ ] Close a universal full non-muted death total order across the exported surfaces. **Blocked evidence:** generic cross-event/destruction dispatcher implementation is not in the pinned release-data corpus.
- [ ] Determine same-priority tie-break and universal cross-event dispatcher semantics. **Blocked evidence:** `PriorityConfig` exports priority tables but not the dispatcher body.
- [ ] Determine cleanup timing generically across entity/modifier classes where individual source-facing lifecycle rules remain available.

**Next closure:** continue source-facing event/lifecycle classification and local causal chains; reopen universal tie-break/cross-event ordering only if a new authoritative engine source appears.

### W11 — Targeting, adjacency, aggro, retargeting and internal traversal

Goal: separate action legality from the targets affected during execution.

- [x] Confirm ordinary configs distinguish friend/enemy selectable target types.
- [x] Confirm Aglaea servant raw config carries an Aggro value.
- [ ] Inventory external selectable target shapes and predicates.
- [ ] Trace adjacency/formation semantics.
- [x] Close one ordinary random-target internal traversal sample: Asta `Bounce_SelectTarget(ByRandom=true, MaxNumber=1)` -> selected `ParamEntity` -> damage consumer.
- [ ] Trace taunt/aggro target-choice influence and exceptions.
- [ ] Determine generic retarget behavior/cardinality/replacement rules, especially `ByRandom=true` without `MaxNumber`.
- [ ] Distinguish AI target choice from player legal-target contract.

**Next closure:** one end-to-end action showing external selection -> internal traversal -> final affected entities, then generalize selector semantics.

### W12 — RNG and random-choice authority

Goal: make random behavior deterministic/replayable by identifying every authoritative draw site and its ordering.

- [ ] Inventory every ordinary-combat `RandomConfig` and equivalent random-choice primitive; representative classes are known but the corpus census is not complete.
- [x] Close one ordinary `RandomConfig` producer/consumer chain using Silver Wolf's Bug selection.
- [x] Close one ordinary random-target selection chain using Asta bounce (`ByRandom=true`, `MaxNumber=1`).
- [x] Confirm `SetDynamicValueByRandom` is a separate ordinary random-value primitive using Aventurine's coin modifier.
- [ ] Close final probability arithmetic for a status/effect application. **Blocked evidence:** `AddModifier.Chance` inputs are traced but the StatusProbability/Resistance evaluator implementation is outside exported TBGD.
- [ ] Determine random draw ordering/stream advancement relative to callbacks and nested actions. **Blocked evidence:** RNG-state owner/advance implementation unavailable.
- [ ] Determine whether AI, presentation and execution randomness share or separate RNG state/stream authority. **Blocked evidence:** no shared stream owner is exported.
- [x] Record negative evidence that `RandomConfig.OddsList` is not final normalized probability authority: ordinary examples sum to `0.6`, `1.0` and `1.1`.
- [x] Record a presentation-risk `RandomConfig` false friend (Jing Yuan hit-effect branch) to prevent blanket promotion of every occurrence.
- [x] Confirm the exact pinned repository is release-data/configuration rather than a GameCore implementation source tree; the missing generic RNG contracts cannot be recovered by repeating character-level searches in the same artifact.
- [ ] Determine `RandomConfig` selection algorithm and `SetDynamicValueByRandom` endpoint/distribution semantics. **Blocked evidence:** generic implementation unavailable at this pin.

**Next closure:** continue the ordinary primitive census only when it improves coverage; generic selection/probability/stream semantics are frozen `blocked_evidence` until a new authoritative engine source appears.

### W13 — Summons, servants/memosprites and special battle entities

Goal: fully model battle-owned secondary entities and their relationship to the owner.

- [x] Confirm Aglaea ordinary ability can `CreateServant(11402)`.
- [x] Confirm `AvatarServantConfig[11402]` config/AI/skill/HP/speed/agro fields.
- [x] Confirm servant ConfigCharacter identifies a battle servant with battle skill/AI/property-inherit wiring.
- [x] Confirm speed-family properties are excluded from the inspected generic property-sync path.
- [x] Confirm separate `CasterSummoner.Speed` and `Caster.Speed` reads in the servant ability graph.
- [x] Reject the inspected Aglaea `ConfigSummonUnit` as the Garmentmaker battle authority.
- [x] Decode `#4/#5/#6`: corresponding `SpeedSkill/HPSkill` selects `AvatarSkillConfig.SkillID`, and `#N` selects the 1-based `ParamList` slot; cross-sampled on servant 11413.
- [x] Confirm ordinary Aglaea recast is create-if-absent / maintain-or-heal-existing, not replacement-on-recast.
- [x] Confirm servant data-level timeline ownership through own Speed/action-delay state and `SkillP03 -> BattleCry -> self ModifyActionDelay(-1 normalized)`.
- [x] Close `SkillP04 -> DeathRattle -> ModifySPNew(CasterSummoner,+20)` target/raw numeric chain; shared resource labeling/caps remain W08.
- [x] Confirm natural servant lifecycle exposes `OnBeforeDying` pre-death cleanup/state transfer, `OnDeathrattle`, owner `OnListenCharacterDie`, and later death-dependent removal surfaces.
- [x] Confirm Aglaea BattleEvent `OnPhase1` selects the servant and priority-inserts `Servant_Aglaea_00_PassiveSkill01_ForceKill_Insert`, whose `ForceKill(...MuteAllTriggerDeath=true)` + `SetDieImmediately` path is distinct from natural death-rattle.
- [ ] Determine creation-time versus continuous/event-driven property synchronization.
- [ ] Determine generic passive-entry activation timing during `CreateServant`. **Blocked evidence:** entry wiring is exported; GameCore autoactivation implementation is not.
- [ ] Determine exact initial queue position / scheduler arithmetic for the created servant. **Blocked by W07 engine boundary.**
- [ ] Determine resource ownership and servant skill `SPBase` meaning generically.
- [ ] Close the universal natural death/death-rattle/OnDestroy/entity-removal total order. **Blocked evidence:** local surfaces are closed but generic dispatcher/removal arbitration is unavailable.
- [ ] Close JoinSkill/owner-servant coordinated action semantics where present.

**Correction retained:** Aglaea Skill02's explicit `SetActionDelay(0)` targets `Caster` (Aglaea), not `CasterServant`; the exact pinned ability does not contain a literal `ActivityOnCreate` field.

**Next closure:** source-facing property synchronization, resource ownership and JoinSkill semantics; do not reopen `#N`, passive autoactivation or universal dispatcher gaps without a new authoritative source.

### W14 — Monster final stats and difficulty scaling

Goal: derive the exact final ordinary-enemy property construction formula where the authoritative consumer is available, while preserving explicit engine gaps where it is not.

- [x] Confirm MonsterConfig/template/character/ability chain for representative Monster 1002011 and correct the template identity to `MonsterTemplateConfig[1002011]`.
- [x] Confirm Stage supplies independent `Level`, `HardLevelGroup` and encounter context in representative ordinary encounters.
- [x] Confirm ordinary five-stat level-scaling inputs are in `ExcelOutput/HardLevelGroup.json`, keyed by `(HardLevelGroup, Level)`, with ATK/DEF/HP/SPD/Stance slots.
- [x] Reject `ILHardLevelGroup` / `ILBattleMonster` as ordinary W14 authority for the inspected ID collision; retain them as RtBattle/special-mode false-friend evidence.
- [x] Cross-check `HardLevelGroup` inputs across multiple levels/groups, including a real SPD-ratio change after level 65.
- [x] Confirm Stage EliteGroup and concrete MonsterConfig EliteGroup can coexist as separate context inputs.
- [x] Confirm non-zero concrete/template flat SPD/Stance modification inputs exist and must not be silently discarded.
- [x] Confirm an exact pinned ordinary `SetDynamicValueByHardLevelProperty(Property=HPRatio)` consumer surface, proving HardLevel properties are typed battle-language inputs rather than dead Excel metadata.
- [ ] Prove final HP composition and precedence. **Blocked evidence:** generic configured-spawn constructor implementation unavailable.
- [ ] Prove final ATK composition and precedence. **Blocked evidence:** same engine boundary.
- [ ] Prove final DEF composition and precedence. **Blocked evidence:** same engine boundary.
- [ ] Prove final SPD composition, flat-value placement and difficulty scaling operator. **Blocked evidence:** same engine boundary.
- [ ] Prove final Stance composition and any player-facing Toughness conversion; continue only if a source-facing conversion consumer is found.
- [ ] Resolve effective Stage/Monster hard-level and EliteGroup precedence when inputs overlap. **Blocked evidence:** generic configured-spawn context resolver unavailable.
- [ ] Resolve MonsterUnique only for families that explicitly reference it; do not insert it universally.

**Next closure:** source-facing Stance/Toughness conversion or an explicit MonsterUnique consumer; generic configured-spawn composition/precedence is frozen until a new authoritative engine source appears.

### W15 — Enemy AI and decision authority

Goal: reconstruct ordinary enemy action and target choice without confusing AI metadata with execution semantics.

- [x] Confirm inspected monster/servant ConfigCharacter data references AI configuration.
- [ ] Inventory ordinary enemy AI families and shared AI primitives.
- [ ] Determine skill priority/sequence rules.
- [ ] Determine conditional action gates and phase switches.
- [ ] Determine target-choice rules and their use of aggro/randomness.
- [ ] Determine weighted/random selection and RNG ownership.
- [ ] Trace AI-selected action into the same execution graph used by battle runtime.
- [ ] Distinguish auto-fight player AI from enemy AI where shared filenames/primitives exist.

**Next closure:** one ordinary enemy from battle state -> AI decision -> target -> skill -> execution.

### W16 — Encounter/wave/spawn/phase/stage-ability construction

Goal: reproduce ordinary encounter composition and transitions.

- [x] Confirm stage records provide ordered wave references rather than a flat monster list.
- [x] Confirm Stage `Level`, `HardLevelGroup`, EliteGroup and StageAbility inputs can be independent battle inputs.
- [x] Confirm shared Stage bootstrap binds StageAbility hooks before and after `WaveMonster`, so encounter-owned effects have explicit pre/post-birth phases.
- [x] Confirm ordinary StageAbility can mutate live monster properties after creation and must remain separate from static spawn-stat construction.
- [x] Confirm a same-entity monster phase path can carry explicit HP/Stance property inputs and is not equivalent to wave respawn; Yanqing variants provide a pinned cross-sample producer chain.
- [ ] Inventory subordinate wave/monster-group/spawn records for ordinary encounters exhaustively.
- [ ] Determine slot/order/formation semantics.
- [ ] Determine wave completion and next-wave transition timing generically.
- [ ] Determine reinforcements/summoned enemy spawn semantics.
- [ ] Resolve phase-property application operator/order and `ApplyOverrideConfig` defaults where source-facing rules are exported.
- [ ] Close ordinary win/lose/battle termination inputs owned by the encounter.

**Next closure:** remaining spawn/transition/reinforcement/battle-end rules plus any source-facing phase-property semantics.

### W17 — Global/shared battle producers

Goal: detect battle-state producers missed by actor-centric forward traversal.

- [x] Perform a broad reverse-scan of `ConfigGlobalModifier/**` and close representative ordinary owners for shared break, speed, defence, status-resistance, fatigue, reference and skill-tree property primitives.
- [x] Audit the logical BattleEvent family at this pin (distributed across Excel/ConfigCharacter/ConfigAbility rather than one `ConfigBattleEvent/**` directory) and confirm ordinary actor-created/activated BattleEvents.
- [x] Audit `ConfigCommonSkillPool/**`: a pinned ordinary Painter consumer/key exists, but the executable pool definition is absent; classify as consumer-present / export-gap rather than non-battle.
- [x] Audit `ConfigGlobalTaskListTemplate/**` and confirm ordinary wave/phase/Break/Super-Break task authority alongside presentation false friends.
- [x] Reverse-scan known battle properties/statuses/opcodes for producers missed by actor-centric traversal, including shared common-passive and stage-global producers outside `ConfigGlobalModifier/**`.
- [x] Preserve shared-vs-mode distinctions at owner/primitive level rather than deferring an entire family from mode-only sightings.
- [x] Preserve explicit negative evidence for camera/RT/GM/WhiteBox/empty-system and definition-only candidates where ordinary reachability is absent.
- [x] Re-read exact pinned `GlobalModifier_Avatar_AssistantTrigger`: battle listeners and `TurnInsertAssistantAbility` are real, but ordinary owner and dynamic `AssistantAbilityID` producer are unresolved; freeze as definition-present ownership/export gap rather than non-battle or an endless scan target.
- [ ] Classify remaining high-risk unowned shared definitions only where new ordinary-consumer evidence appears; avoid exhaustive sibling proof with no navigation signal.

**Next closure:** new high-signal shared definitions with concrete ordinary consumers only. AssistantTrigger/CommonSkillPool/generic loader tails are durably frozen until new source appears.

### W18 — Equipment/build effects and Technique-to-battle boundary

Goal: close combat-facing equipment/build effects and battle-entry effects without importing progression or scene-only semantics.

- [x] Close one representative Light Cone identity -> level/rank params -> DynamicValue -> Ability/Modifier chain.
- [ ] Determine Light Cone superimposition/augment/rank parameter semantics generically.
- [ ] Locate relic main/sub-stat battle-property contribution sources.
- [ ] Locate relic/planar set-effect producers and their Ability/Modifier chains.
- [ ] Close stack/condition/timing semantics for one nontrivial equipment effect.
- [ ] Trace a normal Technique/maze effect that actually changes ordinary battle initialization.
- [ ] Separate scene-only `MazeBuff`/`AdventureAbility`/`AdventureModifier` behavior from battle-entry consequences.
- [ ] Preserve progression/acquisition/EXP/material/salvage/reward data as explicit non-battle neighbors where needed.

**Next closure:** one complex equipment chain plus one Technique -> battle-start state chain.

## Cross-cutting deliverable — TBGD battle language dictionary

The work packages above should converge on a reusable semantic dictionary. This dictionary is more valuable than accumulating isolated character examples because many actors use the same underlying battle language.

This is a cross-cutting deliverable rather than an additional fixed work-package denominator.

### L01 — Parameter/binding language

- [x] `SkillParam` producer/index semantics for ordinary avatar samples.
- [x] `SkillRank` producer/index space for inspected ordinary rank samples.
- [x] `SkillTreeParam` producer/index space for inspected ordinary trace samples.
- [ ] DynamicHash/DynamicValue binding environment and ownership generically across all entity families.
- [x] `#N` servant indirect parameter syntax: corresponding SkillID selects the ParamList and `#N` selects the 1-based slot; parser implementation itself is not exported.

### L02 — Formula/arithmetic language

- [ ] constant/property/reference operands.
- [ ] arithmetic operators and evaluation order generically.
- [ ] clamping/min/max/threshold/conditional operations.
- [ ] rounding/precision rules where they can change battle state.

### L03 — Battle-state mutation opcodes

- [ ] damage.
- [ ] heal.
- [ ] shield.
- [ ] add/remove/modify status.
- [ ] resource gain/cost.
- [ ] toughness mutation/break.
- [ ] action advance/delay/insert.
- [ ] spawn/create/kill/revive/cleanup.

### L04 — Entity selectors and ownership

- [ ] caster/target/source/owner/summoner selectors.
- [ ] ally/enemy/all/adjacent/random selectors.
- [ ] original target versus current/retargeted target.
- [ ] spawned entity ownership/scope.

### L05 — Event/scheduling language

- [ ] trigger registration.
- [ ] callback dispatch; configured priorities/local causal chains are known, generic dispatcher/tie-break is `blocked_evidence`.
- [ ] nested ability invocation.
- [ ] turn/round/cycle boundaries.
- [ ] death/cleanup ordering; natural and muted branches are distinguished, universal cross-event destruction order is `blocked_evidence`.

### L06 — Modifier lifecycle language

- [ ] lifetime units and decrement timing.
- [ ] stacking.
- [ ] refresh/replace/extend.
- [ ] snapshot/live reads.
- [ ] dispel/control immunity interaction.

### L07 — Randomness language

- [x] Representative random-choice primitives: `RandomConfig`, `Retarget(ByRandom=true)` and `SetDynamicValueByRandom` are distinct source surfaces.
- [ ] weighted-selection algorithm (`RandomConfig.OddsList` is raw odds/weights input, not final normalized probability) — `blocked_evidence` at generic engine layer.
- [ ] generic random target traversal/cardinality/replacement semantics where source-facing selectors remain available.
- [ ] generic status/effect probability evaluator — `blocked_evidence` at engine layer.
- [ ] draw ordering/state/stream authority across execution, AI and presentation — `blocked_evidence` at engine layer.

### L08 — Scope and authority language

- [x] Exact numeric ID equality is not sufficient identity proof.
- [x] Filename/directory prefix is not sufficient battle-scope proof.
- [x] Deferred special-mode use does not automatically defer a primitive independently reachable from ordinary combat.
- [x] A missing exported definition does not prove a mechanic is absent when an ordinary pinned consumer/key exists; record an export gap instead.
- [x] A typed `RPG.GameCore.*` opcode or raw constant proves a data-facing contract surface, not that its generic engine implementation body is present in the pinned release-data repository.
- [ ] Build enough repeated examples to turn these guardrails into reusable source-family classification rules without replacing manual review.

## Discovery inbox

Use this section for newly encountered mechanisms that may require a new work package or a split of an existing one. Entries should not remain here indefinitely: every item must eventually be promoted into a work package, merged into an existing package, deferred, or retired with evidence.

Current inbox:

- [ ] No untriaged mechanism recorded by the first five-lane integration or second boundary pass. W17 found no battle-state consequence requiring W19+; add future discoveries here rather than forcing them into an unsuitable package.

## Deferred-by-scope register

These mechanisms may be genuine battle authority but do not need exhaustive closure in the current ordinary-combat phase:

- Simulated Universe mode-owned mechanics;
- Divergent Universe mode-owned mechanics;
- Currency Wars mode-owned mechanics;
- event-specific battle modes and event-only combat entities/rules, including inspected `Config/Activity/RtBattle/**` / `ILBattleAvatar*` records.

If any of these exposes a primitive independently used by ordinary combat, the shared primitive remains in the relevant active work package.

## Retirement criteria

A work package or leaf can be marked `retired_not_required` only when manual evidence establishes one of the following:

1. changing/removing the source fact cannot alter an in-scope ordinary battle state or execution;
2. the suspected mechanism is presentation/scene/tooling/telemetry only;
3. the apparent mechanism is fully subsumed by another proven authority and has no independent semantics;
4. the mechanism is not ordinary combat and belongs wholly to a deferred mode (use `deferred`, not `retired_not_required`, when it is still genuine combat authority there).

Retirement requires a durable negative-evidence note. “We did not find a consumer” is not, by itself, sufficient proof.

## Change log

| Date | Change | Reason/evidence |
| --- | --- | --- |
| 2026-09-08 | Created living worklist with initial `W01..W18` decomposition and cross-cutting battle-language dictionary. | PR #8 had accumulated representative evidence but lacked a maintainable mechanism-level completion ledger. The worklist intentionally treats its denominator as mutable and preserves manual semantic review as the promotion authority. |
| 2026-09-08 | Integrated first five-lane parallel archaeology checkpoint. | Corrected W02 producer false-negative and W14 `IL*` false-friend, promoted closed W05/W10/W12/W13/W16/W17 leaves, recorded W07/RNG engine-export boundaries, and retained all packages as `active` where mechanism-level obligations remain. |
| 2026-09-09 | Integrated second boundary-focused archaeology pass. | Closed Aglaea natural pre-death/death-rattle/death-listener surfaces plus priority-tiered muted forced cleanup; proved HardLevel typed property access while freezing the generic spawn-stat constructor; froze W10/W12 dispatcher/RNG implementation gaps and W17 AssistantTrigger ownership/ID producer at the exact pinned release-data boundary. |

## Current P0 closure queue

This queue is intentionally short and should be reordered when evidence changes.

1. **W04/W05/W09 — core numerical/lifecycle language:** generic Damage plus Shield/Modifier arithmetic/lifecycle; use source-facing operands and multiple ordinary consumers.
2. **W06 — toughness/break state machine:** close one full hit -> stance mutation -> break -> element-specific consequence -> recovery chain where source-facing rules are exported.
3. **W03 — execution language:** broaden reusable battle-mutating opcode/dispatch mapping and preserve presentation/mixed filtering.
4. **W02 — producer model finishing pass:** one further unrelated ordinary-character cross-check plus version-drift discipline; do not reopen March producer discovery.
5. **W13 — special-entity source-facing semantics:** property synchronization, resource ownership and JoinSkill. Passive autoactivation, initial scheduler math and universal death dispatcher are frozen engine gaps.
6. **W10/W12/W14/W07 — blocked generic engine contracts:** do not repeatedly search the same release-data dump for dispatcher/RNG/final-spawn-stat/SPD→AV implementation bodies. Reopen only with a new authoritative engine/source family; continue only their independent source-facing leaves.
7. **W17 — reverse-scan maintenance:** broad pass and high-risk tails are complete/frozen enough for this checkpoint; inspect new shared definitions only when a concrete ordinary consumer or new source signal appears.

W02 ordinary March SkillParam producer discovery remains removed from the P0 queue because the exact pinned producer is confirmed. No package-level completion percentage is authoritative while the taxonomy/denominator remains mutable.
