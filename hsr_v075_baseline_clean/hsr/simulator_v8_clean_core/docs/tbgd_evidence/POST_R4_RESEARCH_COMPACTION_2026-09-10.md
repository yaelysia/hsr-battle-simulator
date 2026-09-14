# Post-R4 TBGD research compaction and kernel cross-check route

## Purpose

This document is the current sequencing and interpretation overlay for Issue #7 / PR #8 after the bounded R0-R4 archaeology sequence.

It does **not** replace the historical `W01..W18` checklist in `BATTLE_RESEARCH_WORKLIST.md`. That checklist remains the durable mechanism ledger. This document supersedes only stale sequencing/"next closure" wording that predates the completed R0-R4 slices, and adds a required simulator-kernel cross-check before launching new generic-engine archaeology.

Research baseline when this compaction was prepared:

- PR #8 branch: `research/tbgd-battle-evidence-ledger`
- baseline head: `2526aa979ce8ede782e58b7f004ec8834eb9175b`
- pinned TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- scope: documentation/evidence only; no runtime/business/lowering/IR behavior is changed here.

The formal source authority remains unchanged:

```text
turnbasedgamedata-main
-> compiler/lowering
-> Canonical IR / data-card IR
-> Combat Core
```

The local v8 simulator kernel is therefore **not a substitute raw authority**. It is, however, a high-value independent reverse-engineered implementation and consumer map. Ignoring it causes repeated archaeology of formula/scheduler/resource behavior that the repository has already encoded and isolated as executable rules or engine conventions.

## 1. R0-R4 bounded closures now on the ledger

The following sequence is complete at its stated bounded scope:

| Thread | Durable result | What is closed | What remains open |
| --- | --- | --- | --- |
| R0 `BATTLE-LANGUAGE-CORE-V1` | `docs/tbgd_evidence/shared/battle_execution_language_core_v1.md` | reusable P/E/D/O parameter, entity, dispatch and operation vocabulary across Avatar / Servant / Monster anchors | exhaustive opcode census and hidden generic engine semantics |
| R1 `DAMAGE-VERTICAL-SLICE-V1` | `docs/tbgd_evidence/shared/ordinary_damage_vertical_slice_v1.md` | ordinary damage request shape, explicit/omitted formula selectors, source-facing modifier/context inputs and heterogeneous damage occurrences | native damage mathematics/defaults/order and full numerical reproduction |
| R2 `TOUGHNESS-BREAK-VERTICAL-SLICE-V1` | `docs/tbgd_evidence/shared/weakness_toughness_break_vertical_slice_v1.md` | weakness/resistance separation, Stance state surfaces, break/recovery topology and an independent typed Stance producer | shared Avatar StanceValue injection producer export gap and hidden native arithmetic |
| R3 `HEALING-MODIFIER-LIFECYCLE-V1` | `docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md` | independent HealHP chains plus reusable lifetime/snapshot/stacking/replace/dispel/property lifecycle surfaces | generic heal/shield/snapshot arithmetic, deeper control/DoT and universal lifecycle ordering |
| R4 `RESOURCE-ECONOMY-CORE-V1` | `docs/tbgd_evidence/shared/resource_economy_core_v1.md` | raw-SP/raw-BP namespace separation, requirement/base/gain/cost/request/reader inputs and recipient topology | native gate/debit/clamp/ratio-base semantics, actor-specific gauges and exact public-name mapping |

`complete` above means the bounded record exit condition was met. It does **not** mean W03/W04/W05/W06/W08/W09 are globally `mechanism_closed`.

## 2. New mandatory distinction: source closure versus local-kernel closure

A single `engine_consumer_unavailable` label is no longer sufficient for planning because the pinned TBGD dump may omit a native consumer while the simulator repository already contains an independently reverse-engineered implementation.

For future work, track these dimensions separately:

| Axis | Meaning |
| --- | --- |
| A — TBGD source-facing closed | exact pinned producer / binding / selector / opcode / state-facing request is established |
| B — TBGD export or engine gap | a required loader/evaluator/dispatcher body is absent from the pinned release-data corpus |
| C — local v8 implementation present | current simulator contains a concrete consumer/rule/state machine for the mechanism |
| D — local v8 source-aligned | inspected local implementation consumes inputs compatible with current pinned source-facing evidence and no contradiction is found |
| E — local v8 validated/test-backed | the implementation has current executable validation sufficient for the specific claim |

These axes are deliberately independent.

- B does not imply C is false.
- C does not imply A or D.
- D does not automatically imply E.
- A local `engine_convention` must remain labeled as such until a formal admitted raw source exists.
- A local implementation must never be used to silently manufacture a missing TBGD producer, field value, target rule or source reference.

Only E should justify language equivalent to runtime verification for the exact tested claim.

## 3. Kernel-first archaeology preflight

Before starting any new search whose objective is a **generic formula, scheduler rule, RNG rule, resource evaluator, status lifecycle, targeting primitive or spawn formula**, perform this preflight first:

1. Identify the current source-facing residual precisely: producer, binding, selector, operation, state consequence or missing relation.
2. Locate the corresponding current v8 L1 consumer / RuleBook / EngineRuleRegistry entry before searching TBGD broadly.
3. Read the implementation enough to record its operands, applicability, source kind, fail-closed conditions and unresolved assumptions.
4. Classify the local side using C/D/E above. File existence alone is only C.
5. Return to pinned TBGD and prove the data inputs actually feeding that mechanism. Search for missing producer/transport edges, not for an already-implemented formula by default.
6. Compare source-facing evidence against the local implementation. A mismatch is a first-class archaeology result and reopens the mechanism.
7. Launch a generic-engine deep search only when one of the following is true:
   - no usable local implementation exists;
   - current local implementation conflicts with pinned source-facing evidence;
   - a new authoritative source/source family plausibly exposes the missing native rule;
   - the local implementation itself records an unresolved convention that blocks required correctness.

Repeated scans of the same release-data artifacts are not justified merely because the native GameCore body is absent.

## 4. Initial kernel cross-check map

This compaction performed a bounded kernel inspection, not a full runtime audit.

### Inspected in this integration

| Mechanism | Current v8 implementation surface | Current interpretation |
| --- | --- | --- |
| Direct damage | `systems/damage_formula.py` plus `rules/engine_rule_registry.py` | executable direct-damage pipeline already separates scaling/base, crit, damage bonus, DEF, RES, damage-taken, reduction and toughness-state buckets. DEF/RES are explicitly versioned `engine_convention` rules pending admitted raw formula authority. Use R1 to verify source-facing inputs; do not pretend the convention came from TBGD. |
| Timeline / AV | `systems/timeline.py` plus `EngineRuleRegistry` timeline rule | local implementation already initializes and advances AV, selects minimum AV and fails closed on unresolved ties. Base gauge `10000` / speed behavior is explicitly an engine convention. W07 raw operation archaeology should now be alignment work, not blind scheduler reconstruction. |
| Weakness Break | `systems/break_system.py` and its RuleBook/DamageSystem integration | local implementation consumes Canonical IR, enters broken state, applies elemental status/damage emissions and exposes recovery. R2 remains source authority for exported topology/inputs; missing TBGD evaluator bodies do not imply the repository lacks a break state machine. |

### Located but not re-audited deeply in this integration

The current `systems/` tree also contains dedicated surfaces for shield/status/callbacks, resource, RNG, targeting/random targeting, scheduler/queue, wave/spawn and related mechanisms. Their existence establishes only **C — local implementation present** for planning. Each future card must inspect the relevant file and its current validation before claiming D or E.

This distinction is intentional: the purpose of this compaction is to stop duplicate research, not to convert source-code presence into blanket runtime correctness.

## 5. Updated research strategy

R0-R4 substantially closed the execution middle at the source-facing level:

```text
skill / binding / invocation
-> damage / healing / modifier / resource request
-> toughness / break state-facing consequences
```

The highest-value remaining uncertainty is now concentrated in three regions:

1. **Execution inputs / battle initialization** — how complete avatar builds, equipment, relics, Techniques, stages and enemies become the initial canonical battle state.
2. **Legality / ownership / encounter control** — which actions and targets are legal, how enemies and waves are instantiated, and how phase/wave/termination state changes.
3. **Cross-cutting alignment residuals** — timeline, death/revive, control/DoT, RNG and callback details where source-facing evidence must be reconciled with existing local mechanisms.

Therefore subsequent archaeology should no longer continue the old R0 -> R1 -> R2 -> R3 -> R4 order. The new serial route is below.

## 6. Recommended serial research route

### R5 — Battle-start build construction v1

Primary packages: **W01 + W18**.

Goal: close one complete ordinary playable-character build from structured source inputs to battle-start properties.

Required vertical slice:

```text
Avatar identity
-> base/level/promotion battle stat inputs
-> Light Cone / relic main+sub stats / set effects
-> traces + eidolons that alter initialization
-> Technique or maze-to-battle entry effect when applicable
-> current v8 build/unit-stat assembler
-> canonical battle-start UnitState properties
```

Kernel preflight: inspect the current build assembly, `unit_stats` and equipment/relic consumers before inventing new composition formulas.

Exit when one representative build has source joins and precedence sufficient to reproduce the battle-start property set, with every local convention clearly separated from pinned raw authority and at least one unrelated build/equipment cross-check.

Why first: R0-R4 already provide strong execution semantics, but they are only as useful as the correctness of the state fed into them. Initial-state construction is now a larger completeness risk than another generic damage/heal formula search.

### R6 — Encounter / spawn / phase / termination v1

Primary packages: **W16 + source-facing W14 residuals**.

Goal: close one ordinary stage from stage selection through spawned enemy state, wave/phase transition and battle termination.

Required vertical slice:

```text
StageConfig
-> wave / group / slot / monster references
-> Level / HardLevelGroup / Elite context
-> current local spawn/stat-construction consumer
-> spawned enemy UnitState
-> pre/post-spawn StageAbility effects
-> phase transformation / reinforcement / next wave
-> win/lose/termination inputs
```

Kernel preflight: inspect current `wave`, `unit_spawn`, battle-state transition and monster/stat construction code first. Do not restart a whole-tree search for the final HardLevel formula if the repository already encodes an engine convention; instead prove TBGD inputs and precedence against that implementation.

Exit when one stage can be explained causally from source records to the set of battle entities and encounter transitions, with any remaining native arithmetic named separately.

### R7 — Legal actions and targeting v1

Primary packages: **W11 + the runtime-relevant subset of W15**, with W12 only as a dependency.

Goal: close what the simulator must expose to an external controller: legal actions, legal targets, internal traversal and source-facing enemy action constraints.

Important project boundary: the simulator does not need to reproduce a standalone autonomous enemy policy merely because TBGD contains AI scoring data. AI records are still useful evidence where they affect available skills, target contracts, phase/action gates or native combat semantics.

Required vertical slice:

```text
battle state
-> admitted actor/action
-> availability/gate inputs
-> external selectable target set
-> adjacency / taunt / aggro / owner relations as required
-> internal retarget/bounce/random traversal
-> selected skill execution via R0 vocabulary
```

Kernel preflight: inspect `action_availability`, `action_selection`, `enemy_action`, `target` and `target_random` before inferring a second legality model from AI metadata.

Exit when at least one player action and one ordinary enemy action can expose reproducible legal targets and execution targets without conflating AI score/weight with legality.

### R8 — Lifecycle, death/revive and timeline alignment v1

Primary packages: **W07 + W10 + bounded W13 residuals**.

Goal: reconcile the already-source-backed scheduling/lifecycle surfaces with the existing scheduler/event/lifecycle implementation.

Focus only on behavior that can change ordinary execution:

- regular turn begin/end and source-facing round/cycle boundaries;
- action delay/advance/insert/OneMore visibility;
- modifier lifetime decrement moments;
- natural death, Limbo/revive, DeathRattle and destruction/removal boundaries;
- servant-specific lifecycle residuals only where they cross these generic mechanisms.

Kernel preflight is mandatory: scheduler/timeline/event dispatch/status callback/unit lifecycle code exists and should be audited against the pinned source surfaces before any attempt to recover a hidden universal native dispatcher.

Exit with a source-alignment matrix: confirmed match, explicit local convention, actual mismatch, or named unresolved boundary for each tested transition. A hidden upstream dispatcher is not itself an exit requirement if the local semantics are source-aligned and the missing body cannot be exported.

### R9 — Status probability, control, DoT and RNG alignment v1

Primary packages: **remaining W09 + W12**.

Goal: close the still-material modifier specializations that R3 deliberately left open.

Focus:

- AddModifier application chance versus Effect Hit / Effect RES / immunity inputs;
- control application/removal and lifetime;
- DoT tick ownership/timing/formula inputs;
- random choice versus random target versus random numeric value;
- replay-relevant RNG identity/order only to the extent required by existing executable mechanics.

Kernel preflight: inspect current status/callback, DoT formula and RNG implementations first. `RandomConfig.OddsList` and source-side `Chance` must not be treated as final probability simply because the local implementation has a formula.

Exit when representative control + DoT + application-probability paths are source-aligned to current local consumers, with RNG implementation provenance and any engine convention explicit.

### R10 — Coverage closure / sentinel sweep

Primary packages: **W02/W13/W14/W17 sentinels plus all remaining source-family gaps**.

Goal: determine what is genuinely still missing after the causal front-to-back slices, not to repeat broad scans.

Actions:

- update `SOURCE_FAMILY_INVENTORY.md` from concrete residuals found in R5-R9;
- inspect W17/global/shared only for newly discovered ordinary consumers/source families;
- run targeted reverse scans for state consequences that still lack any producer;
- cross-check representative Character / Monster / Stage / Equipment chains against Issue #7 acceptance criteria;
- route remaining gaps into new small cards only when each gap has a concrete consequence and owner.

Exit when the remaining list is a bounded set of explicit source/export/convention/validation gaps rather than unknown mechanism classes.

## 7. Sentinel / no-repeat rules

The following remain frozen from standalone generic searching unless a current vertical slice produces new evidence:

- W02 ordinary SkillParam producer/index model;
- W07 hidden native scheduler body merely to re-prove AV math already isolated locally;
- W10 universal hidden dispatcher/tie-break with no new source;
- W12 PRNG stream/algorithm with no new authoritative owner;
- W13 passive auto-entry/sync merge/normal-slot accounting with no new consumer;
- W14 native configured-spawn operator with no new source, except alignment against current local implementation;
- W17 broad whole-tree shared reverse scan;
- R2 shared Avatar StanceValue injection gap with no new bridge;
- R3 generic HealHP/Shield evaluator body with no new authority;
- R4 generic resource gate/debit/clamp body with no new authority.

A local kernel mismatch, a new TBGD family, a newly admitted compiler/lowering source or a new ordinary consumer is sufficient reason to reopen the relevant item.

## 8. Per-thread execution contract from R5 onward

Each thread should still be one causal closure, not one arbitrary W package.

At startup record:

```text
THREAD_ID
current PR head
pinned TBGD revision
primary causal closure
reused evidence records
local kernel consumers/rules to inspect first
named frozen boundaries
```

During research keep four evidence buckets separate:

```text
1. pinned TBGD fact / source-facing contract
2. local v8 implementation fact
3. alignment inference supported by comparing 1 and 2
4. unresolved source/export/convention/validation gap
```

Do not promote bucket 2 into bucket 1. Do not label bucket 3 `runtime_verified` without bucket E validation evidence.

A durable thread checkpoint should report:

- source-facing closures;
- local implementation surfaces inspected;
- alignments and mismatches;
- engine conventions reused;
- exact gaps frozen;
- modified evidence/ledger files;
- recommended next causal slice.

## 9. Current recommended next thread

The next serial archaeology thread should be:

**R5 — W01 + W18 — Battle-start Build Construction v1**.

It should begin from the current PR head after this compaction is committed, read this overlay first, and treat current simulator build/unit-stat/equipment code as a required verification target before searching for generic stat-composition formulas.

Do not automatically continue to R6 in the same thread. R5 should end at a durable evidence checkpoint so that its findings can change the remaining route if necessary.
