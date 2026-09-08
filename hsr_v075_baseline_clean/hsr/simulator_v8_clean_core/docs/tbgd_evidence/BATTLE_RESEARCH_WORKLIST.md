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
| W02 | Ordinary character skill numeric/value authority | P0 | `blocked_evidence` | manually confirmed consumers; producer missing for March Skill02 | 2026-09-08 | locate ordinary `SkillID=100102` parameter authority or prove pin omission |
| W03 | Skill execution graph and combat operation dispatch | P0 | `active` | manually confirmed March/Aglaea examples | 2026-09-08 | build reusable execution/opcode mapping beyond representative skills |
| W04 | Damage resolution | P0 | `active` | manually confirmed 2.0 monster skill multiplier leaf | 2026-09-08 | close generic damage operands and composition/precedence |
| W05 | Healing and shielding | P0 | `active` | March formal Shield + snapshot behavior confirmed | 2026-09-08 | close shield arithmetic, refresh/replacement and healing counterpart |
| W06 | Weakness, toughness and Weakness Break | P0 | `active` | scattered candidate fields | 2026-09-08 | close stance/toughness mutation and break state transition chain |
| W07 | SPD, action value, turn/timeline and advance/delay | P0 | `active` | servant speed reads expose unresolved special handling | 2026-09-08 | close ordinary timeline authority and ordering semantics |
| W08 | Energy, Skill Points and actor-specific resources | P1 | `active` | scattered skill/resource fields | 2026-09-08 | close one full generation/consumption/callback chain for each shared resource |
| W09 | Buff/debuff/modifier/control semantics | P0 | `active` | formal March shield Modifier and death-rattle modifier examples | 2026-09-08 | build lifetime/stack/refresh/dispel/immunity semantic rules |
| W10 | Trigger, callback and event ordering | P0 | `active` | death-rattle/death event graph exists | 2026-09-08 | close ordering for one multi-trigger ordinary-combat chain, then generalize |
| W11 | Targeting, adjacency, aggro, retargeting and internal traversal | P1 | `active` | friend/enemy target and aggro examples confirmed | 2026-09-08 | distinguish legal external target contract from internal execution traversal |
| W12 | RNG and random-choice authority | P0 | `active` | candidate RandomConfig/AI relevance known | 2026-09-08 | close one ordinary RandomConfig/random-target producer-consumer chain |
| W13 | Summons, servants/memosprites and special battle entities | P0 | `active` | Aglaea Servant 11402 structural chain manually confirmed | 2026-09-08 | decode `#4/#5/#6`, sync timing, timeline ownership and cleanup |
| W14 | Monster final stats and difficulty scaling | P0 | `active` | template/unique/stage/hard-level inputs partially confirmed | 2026-09-08 | prove final HP/ATK/DEF/SPD/Stance equation and precedence |
| W15 | Enemy AI and decision authority | P1 | `active` | AI reference edges confirmed; semantics unresolved | 2026-09-08 | close skill selection, target choice, priority/weights and randomness |
| W16 | Encounter/wave/spawn/phase/stage-ability construction | P1 | `active` | Stage wave structure manually confirmed | 2026-09-08 | close spawn/transition/reinforcement and stage-owned effect semantics |
| W17 | Global/shared battle producers | P0 | `active` | families identified; reverse scan outstanding | 2026-09-08 | audit GlobalModifier/BattleEvent/CommonSkillPool/shared producers |
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
- [ ] Locate the pinned ordinary numeric source for March `SkillID=100102`, or prove that the pinned export omits it.
- [ ] Determine level/rank indexing of ordinary skill parameter arrays.
- [ ] Map `SkillParam`, `SkillRank` and `SkillTreeParam` to their respective producers and consumers.
- [ ] Cross-check the binding model on at least two unrelated ordinary characters.
- [ ] Document version-drift behavior when current/live tables contain values absent from the pinned corpus.

**Next closure:** March Skill02 parameter producer/omission proof.

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
- [ ] Resolve March shield percentage/flat-value/lifetime/threshold/aggro parameter numerics.
- [ ] Determine shield value construction formula and scaling-stat snapshot point.
- [ ] Determine refresh, replacement, stacking and depletion behavior.
- [ ] Trace one ordinary healing formula from producer to final HP mutation.
- [ ] Determine healing modifiers, caps/overheal behavior where represented, and callback timing.

**Next closure:** March shield arithmetic plus one independent healing chain.

### W06 — Weakness, toughness and Weakness Break

Goal: reconstruct the full stance/toughness state machine and break consequences.

- [ ] Locate authoritative enemy/player weakness representation and weakness matching rules.
- [ ] Locate base/final Stance/Toughness value construction.
- [ ] Trace skill toughness-damage inputs to the mutation consumer.
- [ ] Determine behavior for non-matching weakness and any universal/reduced toughness damage cases.
- [ ] Close transition into broken state and recovery transition.
- [ ] Close break-linked action delay.
- [ ] Close Weakness Break damage/status application and elemental specialization.
- [ ] Trace break-trigger callbacks and ordering relative to hit/damage/death.

**Next closure:** one complete hit -> toughness zero -> break -> recovery chain.

### W07 — SPD, action value, turn/timeline and advance/delay

Goal: identify the authority that determines when every battle entity acts.

- [ ] Prove SPD-to-action-value conversion from raw/runtime semantics.
- [ ] Identify initial AV/turn-queue initialization.
- [ ] Trace action advance and delay operations and their ordering/rounding semantics.
- [ ] Distinguish extra turns, inserted actions, follow-ups and normal turns.
- [ ] Determine round/cycle boundary semantics used by ordinary combat.
- [ ] Determine how SPD changes affect already-scheduled action value.
- [ ] Close summon/servant independent or shared timeline ownership.
- [ ] Separate logical timing from animation/presentation waits.

**Next closure:** ordinary actor SPD -> queue -> advance/delay -> next action chain.

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
- [ ] Determine refresh versus extend versus replace behavior.
- [ ] Determine snapshot versus live-property reads.
- [ ] Trace dispel categories and dispel immunity.
- [ ] Trace crowd-control application, immunity, resistance and expiration.
- [ ] Close DoT lifecycle and tick timing as a modifier specialization.

**Next closure:** one reusable modifier lifecycle state machine validated on multiple mechanics.

### W10 — Trigger, callback and event ordering

Goal: establish deterministic ordering for event-driven battle behavior.

- [x] Confirm an ordinary servant death-rattle/death-event subgraph exists.
- [ ] Inventory ordinary event/trigger names and registration mechanisms.
- [ ] Trace on-attack/on-hit/on-damage distinctions.
- [ ] Trace on-break, on-kill, on-death and defeat-prevention ordering.
- [ ] Trace follow-up/counter trigger registration and dispatch.
- [ ] Determine nested callback ordering and whether queues/stacks/priority tiers exist.
- [ ] Determine cleanup timing relative to callbacks.
- [ ] Validate one multi-trigger interaction with an observable expected order.

**Next closure:** a single ordinary interaction with at least three causally related callbacks whose exact order is source-backed.

### W11 — Targeting, adjacency, aggro, retargeting and internal traversal

Goal: separate action legality from the targets affected during execution.

- [x] Confirm ordinary configs distinguish friend/enemy selectable target types.
- [x] Confirm Aglaea servant raw config carries an Aggro value.
- [ ] Inventory external selectable target shapes and predicates.
- [ ] Trace adjacency/formation semantics.
- [ ] Trace internal target expansion for blast/AoE/bounce/random hits.
- [ ] Trace taunt/aggro target-choice influence and exceptions.
- [ ] Determine retarget behavior when an intended target becomes invalid/dead.
- [ ] Distinguish AI target choice from player legal-target contract.

**Next closure:** one end-to-end action showing external selection -> internal traversal -> final affected entities.

### W12 — RNG and random-choice authority

Goal: make random behavior deterministic/replayable by identifying every authoritative draw site and its ordering.

- [ ] Inventory ordinary-combat `RandomConfig` and equivalent random-choice primitives.
- [ ] Close one RandomConfig producer/consumer chain.
- [ ] Close one random-target selection chain.
- [ ] Close one probability-based status/effect application chain.
- [ ] Determine random draw ordering relative to callbacks and nested actions.
- [ ] Determine whether AI randomness shares or separates authority from execution randomness.
- [ ] Record any weighted-choice, shuffle, no-replacement or retry semantics.
- [ ] Cross-check against the simulator RNG ledger requirements used by current P9 work without changing runtime in this PR.

**Next closure:** one ordinary RandomConfig chain with exact draw owner, inputs, result consumer and ordering.

### W13 — Summons, servants/memosprites and special battle entities

Goal: fully model battle-owned secondary entities and their relationship to the owner.

- [x] Confirm Aglaea ordinary ability can `CreateServant(11402)`.
- [x] Confirm `AvatarServantConfig[11402]` config/AI/skill/HP/speed/agro fields.
- [x] Confirm servant ConfigCharacter identifies a `Memosprite` with battle skill/AI/property-inherit wiring.
- [x] Confirm speed-family properties are excluded from the inspected generic property-sync path.
- [x] Confirm separate `CasterSummoner.Speed` and `Caster.Speed` reads in the servant ability graph.
- [x] Reject the inspected Aglaea `ConfigSummonUnit` as the Garmentmaker battle authority.
- [ ] Decode `#4/#5/#6` and prove the referenced ordinary parameter source.
- [ ] Determine creation-time versus continuous/event-driven property synchronization.
- [ ] Determine action-value/turn ownership.
- [ ] Determine resource ownership and servant skill `SPBase` meaning.
- [ ] Close replacement/ForceKill/death/death-rattle/cleanup ordering.
- [ ] Close JoinSkill/owner-servant coordinated action semantics where present.

**Next closure:** parameter decode plus timeline/lifecycle semantics for Servant 11402.

### W14 — Monster final stats and difficulty scaling

Goal: derive the exact final ordinary-enemy property construction formula.

- [x] Confirm MonsterConfig/template/unique/character/ability chain for representative Monster 1002011.
- [x] Confirm Stage supplies independent `Level` and `HardLevelGroup` inputs in a representative ordinary encounter.
- [x] Confirm `ILHardLevelGroup` contains the inspected `(HardLevelGroup=1, Level=29)` HP/ATK/DEF ratio lookup edge.
- [ ] Re-verify exact template/unique IDs for the representative chain and correct any stale ledger mismatch.
- [ ] Prove HP composition and precedence.
- [ ] Prove ATK composition and precedence.
- [ ] Prove DEF composition and precedence.
- [ ] Prove SPD composition and any difficulty scaling.
- [ ] Prove Stance/Toughness composition and any difficulty scaling.
- [ ] Resolve precedence when Stage and MonsterUnique provide different/overlapping scaling keys.
- [ ] Cross-validate final stats for multiple levels/groups.

**Next closure:** complete `Stage Level + HardLevelGroup + MonsterTemplate + MonsterUnique -> final stats` equation.

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
- [x] Confirm Stage `Level`, `HardLevelGroup` and StageAbility inputs can be independent battle inputs.
- [ ] Inventory subordinate wave/monster-group/spawn records for ordinary encounters.
- [ ] Determine slot/order/formation semantics.
- [ ] Determine wave completion and next-wave transition timing.
- [ ] Determine reinforcements/summoned enemy spawn semantics.
- [ ] Determine multi-phase/boss transition mechanisms.
- [ ] Trace ordinary StageAbility/global encounter effects into battle state.
- [ ] Close ordinary win/lose/battle termination inputs owned by the encounter.

**Next closure:** one representative ordinary stage from stage ID through all waves/transitions to battle end.

### W17 — Global/shared battle producers

Goal: detect battle-state producers missed by actor-centric forward traversal.

- [ ] Reverse-scan `ConfigGlobalModifier/**` for ordinary-combat reachable producers.
- [ ] Reverse-scan `ConfigBattleEvent/**` for ordinary battle-state mutations and transitions.
- [ ] Audit `ConfigCommonSkillPool/**` and shared dispatch used by ordinary actors.
- [ ] Audit `ConfigGlobalTaskListTemplate/**` for actual battle callback/state authority versus tooling/script noise.
- [ ] Reverse-scan known battle properties/statuses/opcodes for producers not reached from current character/monster/stage roots.
- [ ] Separate shared primitives from deferred-mode-only ownership.
- [ ] Preserve explicit negative evidence for plausible-looking global families that prove non-battle.

**Next closure:** first complete reverse-scan pass with all discovered ordinary global producers classified.

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

- [ ] `SkillParam` producer/index semantics.
- [ ] `SkillRank` producer/index semantics.
- [ ] `SkillTreeParam` producer/index semantics.
- [ ] DynamicHash/DynamicValue binding environment and ownership.
- [ ] `#N`-style indirect parameter syntax and decoder, if proven.

### L02 — Formula/arithmetic language

- [ ] constant/property/reference operands.
- [ ] arithmetic operators and evaluation order.
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
- [ ] callback dispatch.
- [ ] nested ability invocation.
- [ ] turn/round/cycle boundaries.
- [ ] death/cleanup ordering.

### L06 — Modifier lifecycle language

- [ ] lifetime units and decrement timing.
- [ ] stacking.
- [ ] refresh/replace/extend.
- [ ] snapshot/live reads.
- [ ] dispel/control immunity interaction.

### L07 — Randomness language

- [ ] random-choice primitive(s).
- [ ] weighted selection.
- [ ] random target traversal.
- [ ] probability checks.
- [ ] draw ordering/authority.

### L08 — Scope and authority language

- [x] Exact numeric ID equality is not sufficient identity proof.
- [x] Filename/directory prefix is not sufficient battle-scope proof.
- [x] Deferred special-mode use does not automatically defer a primitive independently reachable from ordinary combat.
- [ ] Build enough repeated examples to turn these guardrails into reusable source-family classification rules without replacing manual review.

## Discovery inbox

Use this section for newly encountered mechanisms that may require a new work package or a split of an existing one. Entries should not remain here indefinitely: every item must eventually be promoted into a work package, merged into an existing package, deferred, or retired with evidence.

Current inbox:

- [ ] No untriaged mechanism recorded at initial creation. Add the first new discovery here rather than forcing it into an unsuitable existing package.

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

## Current P0 closure queue

This queue is intentionally short and should be reordered when evidence changes.

1. **W02 — ordinary skill numeric authority:** March Preservation `SkillID=100102` producer or pinned-export omission proof.
2. **W14 — monster final stats:** `Stage Level + HardLevelGroup + MonsterTemplate + MonsterUnique -> HP/ATK/DEF/SPD/Stance`.
3. **W04/W05/W09 — core numerical/lifecycle language:** generic Damage plus Shield/Modifier arithmetic/lifecycle.
4. **W07 — timeline:** SPD/AV/advance/delay/turn ownership.
5. **W12 — RNG:** one full ordinary RandomConfig/random target chain with draw authority/order.
6. **W10 — callback ordering:** one multi-trigger chain with exact causal order.
7. **W17 — reverse scan:** global/shared battle producers not reached by current actor-centric samples.

This queue is operational guidance, not a frozen priority contract. Update it whenever a newly discovered mechanism poses a larger completeness or correctness risk.