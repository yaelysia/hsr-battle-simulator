# Post-R5 TBGD research compaction and R6 execution contract

## Purpose

This document is the current sequencing and handoff overlay for Issue #7 / PR #8 after the bounded R0-R5 archaeology sequence.

It supersedes the **sequencing** portions of `POST_R4_RESEARCH_COMPACTION_2026-09-10.md` and stale per-package `Next closure` wording that predates R5. It does not erase the historical `W01..W18` ledger and does not declare those packages globally complete.

Planning baseline:

- PR #8 branch: `research/tbgd-battle-evidence-ledger`
- baseline head inspected for this compaction: `6c1275529d4e63cb57c50c30bb73d00d65c93715`
- pinned TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- scope: documentation/evidence only; no runtime/business/lowering/IR behavior is changed by this checkpoint.

The formal authority chain remains:

```text
turnbasedgamedata-main
-> compiler/lowering
-> Canonical IR / data-card IR
-> Combat Core
```

The current v8 implementation is a consumer/alignment target, not a substitute for missing pinned raw authority.

## 1. Bounded R0-R5 state

| Thread | Durable result | Bounded closure | Material residual |
| --- | --- | --- | --- |
| R0 Battle Language Core v1 | `docs/tbgd_evidence/shared/battle_execution_language_core_v1.md` | reusable parameter/entity/dispatch/operation vocabulary across Avatar/Servant/Monster anchors | exhaustive opcode census and hidden generic engine semantics |
| R1 Ordinary Damage v1 | `docs/tbgd_evidence/shared/ordinary_damage_vertical_slice_v1.md` | ordinary source-facing damage request/operand/context shape | native/default arithmetic and full numerical runtime reproduction |
| R2 Toughness/Break v1 | `docs/tbgd_evidence/shared/weakness_toughness_break_vertical_slice_v1.md` | weakness/resistance separation, stance state surfaces, break/recovery topology | shared injection/native arithmetic boundaries |
| R3 Healing + Modifier Lifecycle v1 | `docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md` | independent HealHP chains and reusable lifecycle surfaces | generic evaluator/ordering details and broader control/DoT |
| R4 Resource Economy v1 | `docs/tbgd_evidence/shared/resource_economy_core_v1.md` | raw-SP/raw-BP source topology and operation inputs | native gate/debit/clamp/ratio-base semantics and actor-specific gauges |
| R5 Battle-start Build Construction v1 | `docs/tbgd_evidence/shared/battle_start_build_construction_v1.md` | one selected ordinary build from source coefficients/equipment/relic/trace/Technique edges to local battle-start destinations | formal admission/execution validation, MazeBuff transport and explicit convention authority |

`complete` above is intentionally bounded. W01/W18 remain `active`: R5 closes a representative source-facing construction slice, not every build family and not runnable parity.

## 2. R5 final compaction

### Source-facing closure established

R5 records a concrete analyst-constructed ordinary tuple:

```text
Avatar 1002 L80/P6/E0
+ Equipment 20000 L80/P6/S1
+ six L15 relics
+ Set102 x4 + Set301 x2
+ Point1002201 L1
+ optional MazeBuff100201 Technique bridge
```

Closed source-facing edges include:

- Avatar and Light Cone promotion/stat coefficients;
- relic slot identity, main-affix coefficients and finished sub-affix inputs;
- set-count static and dynamic effect partition for the selected sets;
- selected static trace contribution;
- LC startup effect parameter binding;
- ordinary Technique bridge `LocalPlayer_DanHeng_MazeSkill -> AddMazeBuff100201 -> CharacterSkill/SkillMaze -> battle-entry AttackAddedRatio`;
- exact Technique numeric correction `Skill100207 Level1 ParamList=[0.4,3]`.

### Local implementation facts established

R5 inspected the current build/card/state construction consumers before extending raw searches, including character/equipment/relic assemblers, `ScenarioStateBuilder` and `systems/unit_stats.py`.

The local construction arithmetic observed for the selected typed buckets is:

```text
base_pool * (1 + static_ratio + active_status_ratio)
+ static_flat
+ active_status_flat
```

This remains a local implementation/convention fact unless a formal admitted raw evaluator proves the same operator.

### Explicit R5 residuals

The following are routed residuals, not permission to restart broad R5 source discovery:

1. **formal admission validation** — the exact tuple was not run through native card compilation/admission and `ScenarioStateBuilder`;
2. **Technique transport validation** — automatic `MazeBuff100201 -> formal startup manifest -> callback execution` was not demonstrated;
3. **resource-cap convention** — raw `SPNeed=100` was observed, while local construction maps that requirement to `max_energy`; the raw source was not proven to declare the cap directly;
4. **B2 callback execution** — LC/set/Technique startup and conditional callbacks were not run;
5. **runtime/CI evidence** — R5 document/arithmetic checks are not E-level runtime validation.

These belong to a later implementation-validation task unless R6 discovers a direct source mismatch that materially changes battle-start construction. PR #8 must not add manual stat injection to make the tuple runnable.

## 3. Why R6 is next

With R0-R5, the largest ordinary-combat source gap has moved from the selected player build and execution middle to the **encounter envelope**:

```text
Stage selection
-> ordered wave/slot definitions
-> enemy identity + difficulty context
-> source-bearing birth template
-> spawned enemy UnitState
-> StageAbility / phase / reinforcement layers
-> wave clear / next wave
-> battle victory / defeat / completion
```

The next thread is therefore:

**R6 — W16 + source-facing W14 residuals — Encounter / Spawn / Phase / Termination v1**

Do not start R7 in the same thread.

## 4. Mandatory R6 kernel-first preflight

The following exact-head local consumers were inspected during this compaction and must be treated as the initial alignment targets rather than rediscovered mechanisms.

### `systems/wave.py::WaveSystem`

Current code consumes `WaveDefinitionIR` and `WaveMonsterEntryIR` and already exposes a formal wave state machine:

- blocks transition while queue work is pending;
- validates executable wave definition/entries;
- starts the current wave only when materialized IDs match the source-bearing entries;
- refuses transition while current/non-current active enemies still block it;
- removes cleared wave entities;
- plans next-wave spawns through `UnitSpawnSystem`;
- emits `battle_victory` when the final wave clears;
- emits `battle_defeat` when no active ally remains;
- records wave/termination mutations, events and settlement data.

R6 should prove where the consumed definitions and entries came from and whether their source identity matches the pinned encounter chain.

### `systems/unit_spawn.py::UnitSpawnSystem`

Current code consumes an executable `UnitBirthTemplateIR` plus typed `UnitSpawnRequest`.

For `spawn_kind="wave_enemy"`, the request carries and validates:

- `unit_id` / `birth_template_id` / `entity_ref`;
- `source_id` / `entry_id`;
- `wave_definition_id` / `stage_id` / `wave_index` / `position`;
- source and entry source traces.

Materialization requires explicit specs for side/template/level/HP/ATK/DEF/SPD/Energy/Toughness/action value and fails closed on request/template/source mismatch. This makes `UnitBirthTemplateIR` construction the highest-value R6 lowering alignment point.

### `systems/phase_machine.py`

The current combat phase machine has an explicit `WAVE_TRANSITION` phase. Wave and terminal events (`wave.monster`, `wave.started`, `wave.cleared`, `battle.victory`, `battle.defeat`, `battle.completed`) are phase-gated there.

Do not infer battle timing from animation or serialized JSON order when this typed runtime contract is the actual consumer.

### `systems/battle_state_transition.py`

This system consumes typed `BattleStateTransitionIR` rules for shared `global_flags`, validates before-state identity, emits mutation/event/settlement facts and fails closed.

It is an alignment candidate for source-backed encounter/global state transitions. It is **not** automatically the same mechanism as monster-internal phase replacement or wave spawning.

### `tbgd/monster_cards.py` and `tbgd/lowering.py`

`monster_cards.py` reads both normal and unique monster families into the source-card layer, while current archaeology says `MonsterUniqueConfig` is conditional rather than a universal ordinary override.

R6 must inspect the exact selected encounter/lowering chain and determine whether any unique-family row actually participates before citing it. The large `tbgd/lowering.py` should be entered through exact `WaveDefinitionIR`, `WaveMonsterEntryIR` and `UnitBirthTemplateIR` producer symbols; do not broad-read the entire file.

The existence of these consumers establishes **C**, not D or E.

## 5. R6 source starting anchors

Reuse current evidence before opening new raw searches.

### Stage anchor A — 103201

Pinned ordinary facts already recorded:

- `StageType=Mainline`;
- `Level=29`;
- `HardLevelGroup=1`;
- no `StageAbilityConfig` entry;
- one ordered wave: `1022020, 1023010, 1022020`.

Use this as a low-noise stage -> wave -> spawn identity anchor.

### Stage anchor B — 301001

Pinned facts already recorded:

- `Level=40`;
- `StageAbilityConfig=["StageAbility_301001"]`;
- ordered roster includes `1022020, 1023010, 8003020, 1022020`;
- Stage-level Elite context and monster-side Elite inputs can coexist.

Use this as the StageAbility/Elite discriminator; do not assume precedence.

### Monster/difficulty anchors

Reuse:

- `MonsterConfig` concrete identity/modification/resistance/skill inputs;
- `MonsterTemplateConfig` base HP/ATK/DEF/SPD/Stance;
- ordinary `HardLevelGroup.json` keyed by `(HardLevelGroup, Level)` with ATK/DEF/HP/SPD/Stance ratios;
- `SetDynamicValueByHardLevelProperty` only as proof that typed HardLevel properties are engine-readable;
- existing phase evidence distinguishing same-entity `Monster_ChangePhase` from wave respawn.

Do **not** use `ILHardLevelGroup` as ordinary authority. Do not insert `MonsterUniqueConfig` without participation evidence.

## 6. R6 causal slice

The primary closure is:

```text
StageConfig selected ordinary encounter
-> wave count / ordered waves / ordered slots
-> WaveDefinitionIR + WaveMonsterEntryIR
-> selected MonsterID
-> concrete/template/difficulty/Elite inputs that actually participate
-> UnitBirthTemplateIR
-> UnitSpawnRequest(spawn_kind=wave_enemy)
-> UnitState
-> StageAbility pre/post-spawn consequences where referenced
-> wave clear
-> next-wave spawn or terminal result
-> battle.completed / victory / defeat facts
```

Monster phase or reinforcement is a sibling encounter transition. If the selected primary stage does not exercise it, add one already-known ordinary phase/reinforcement anchor rather than pretending the primary stage proves a mechanism it never reaches.

## 7. R6 evidence buckets

Keep four buckets separate throughout the thread:

1. **S — pinned TBGD/source-facing fact**: exact stage/monster/table/ability occurrence and reference chain;
2. **K — local implementation fact**: current lowering/IR/RuleBook/runtime behavior;
3. **I — alignment inference**: supported comparison between S and K;
4. **G — unresolved gap**: export, convention, ownership, precedence or validation boundary.

Use the A/B/C/D/E matrix at the end of the durable record. Do not label C/D as runtime verification.

## 8. R6 bounded deliverable

Primary durable record:

`docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md`

Update only the ledgers whose interpretation materially changes:

- `SOURCE_FAMILY_INVENTORY.md` when participation/classification changes;
- `PINNED_SOURCE_INDEX.md` for expensive exact-pin lookups or corrected false friends;
- `BATTLE_RESEARCH_WORKLIST.md` only for evidence leaves/status that the R6 result genuinely changes;
- this README/navigation at the final R6 checkpoint.

No runtime/business/lowering/IR/test file is in the R6 write set on PR #8.

## 9. R6 exit condition

R6 v1 is bounded-complete only when all of the following are true:

1. **Stage source join:** one ordinary StageConfig chain is manually closed into its exact ordered `WaveDefinitionIR` / `WaveMonsterEntryIR` identities and source evidence.
2. **Enemy birth join:** at least one real wave entry is traced through the exact participating monster/template/difficulty inputs into the `UnitBirthTemplateIR` consumed by `UnitSpawnSystem`.
3. **No false difficulty source:** ordinary `HardLevelGroup.json` is used where proven; IL/RtBattle families remain excluded from the ordinary chain.
4. **Conditional overrides remain conditional:** any `MonsterUnique`/Elite/phase input is included only with a concrete participation edge; absence is not normalized into zero/default authority.
5. **StageAbility ownership:** a referenced StageAbility is resolved far enough to classify its pre/post-spawn battle consequences or retain a named gap.
6. **Transition/termination alignment:** one wave clear is traced to either a real next-wave spawn or terminal victory, and defeat/termination inputs are reconciled with the current `WaveSystem` contract.
7. **Phase/reinforcement discriminator:** same-entity phase versus new spawn/reinforcement is explicitly distinguished using a reachable anchor.
8. **Alignment matrix:** each tested layer is labeled A/B/C/D/E without converting conventions into raw authority.
9. **Negative knowledge:** stale `ILHardLevelGroup` and universal-`MonsterUnique` assumptions stay explicitly rejected.
10. **No runtime mutation:** PR #8 remains documentation/evidence-only and Draft.

A hidden upstream GameCore spawn-stat method is **not** an exit requirement when the source-facing inputs are closed, the current local convention is explicit, and no new authoritative source exposes the missing native body.

## 10. Frozen boundaries / no-repeat rules during R6

Do not spend the R6 thread on:

- recovering the generic final spawn ATK/DEF/HP/SPD/Stance arithmetic from the same release-data dump when no new engine source exists;
- guessing flat-value placement, clamp or rounding from community formulas;
- declaring Stage-vs-Monster HardLevel/Elite precedence without a discriminator;
- treating `ILHardLevelGroup` as ordinary data;
- whole-tree W17 reverse scans;
- W07 scheduler math, W10 universal dispatcher, W12 PRNG algorithm or unrelated R2/R3/R4 evaluator gaps;
- progression/reward/acquisition data;
- special-mode encounter families already deferred by `BATTLE_SCOPE.md`.

A new authoritative source, a current local-kernel contradiction, or a newly reached ordinary source family is sufficient to reopen the relevant boundary.

## 11. R6 execution order

Use this order to minimize duplicate archaeology:

1. locate the exact current lowering symbols that create `WaveDefinitionIR`, `WaveMonsterEntryIR` and wave-enemy `UnitBirthTemplateIR`;
2. select the primary ordinary stage and manually re-read its pinned StageConfig row;
3. walk each source join only as far as the selected wave/birth template needs;
4. compare the resulting inputs/identity against `WaveSystem` and `UnitSpawnSystem` contracts;
5. resolve one StageAbility owner/graph and classify battle versus presentation operations;
6. exercise the evidence chain through wave clear -> next wave or termination at the semantic/runtime-contract level;
7. add phase/reinforcement anchor only if the primary stage does not already contain one;
8. write the bounded durable record and update affected ledgers;
9. stop at the R6 checkpoint. Do not automatically enter R7.

## 12. Stop / replan conditions

Stop and re-scope instead of broadening silently if:

- the chosen stage belongs to a deferred special mode rather than ordinary combat;
- R6 discovers a second independent encounter authority not represented by the current W16/W14 model;
- local lowering contradicts pinned stage/monster identity or silently consumes a source family currently classified as false/conditional;
- a source-true behavior would require changing runtime/lowering/IR to document correctly;
- a required source family is genuinely absent/unexported and the remaining question is only hidden engine implementation.

Such a result is a valid archaeology finding. Record the concrete mismatch/gap and leave runtime repair to a separate implementation PR/card.
