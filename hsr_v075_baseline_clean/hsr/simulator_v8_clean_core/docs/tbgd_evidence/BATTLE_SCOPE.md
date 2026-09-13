# TBGD battle-semantic scope and completeness contract

## Purpose

This archaeology is not a sample collection. Its end state is a source-backed inventory of **all TBGD data and graphs at the pinned revision that can materially change Honkai: Star Rail battle state or battle execution within the current-phase scope**, while explicitly excluding progression, UI, camera, animation/presentation and other non-battle semantics.

Pinned TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`.

The practical question is not "does this file sound combat-related?". The question is:

> If this source fact were changed or removed while all other inputs stayed fixed, could an in-scope battle start differently, admit a different action, evolve through a different reachable state, produce a different numeric/state outcome, choose a different target/action, transition differently, or terminate differently?

If yes, the relevant fact belongs in the battle corpus. If no, it does not. If one source mixes both kinds of facts, it is `mixed_requires_filter` and must be classified below file level.

## Current-phase mode exclusions

To keep the first archaeology pass focused on the reusable/core battle model, the following battle families are **explicitly deferred from this phase even when their effects are battle-authoritative inside those modes**:

- Simulated Universe-specific rules, blessings, curios, equations and mode-owned battle assets;
- Divergent Universe-specific rules and battle assets;
- Currency Wars-specific rules and battle assets;
- event-specific battle modes, event-only combat rules, event-only combat entities and event-only combat buffs/modifiers.

These are `deferred`, not `non_battle`. They do not need to be exhaustively inventoried or semantically closed for the current PR to satisfy its completion condition.

The exclusion is mode-owned rather than primitive-owned. If a lower-level mechanic, opcode, modifier contract, character/enemy behavior or shared battle table is also reachable from ordinary in-scope combat, it remains in scope through that ordinary battle reference chain. Do not use a deferred-mode reference as the sole reason to expand the current pass into that mode.

## Battle-state consequence test

A source fact is in scope when it can materially affect at least one of these concepts in an in-scope battle:

1. **Battle entities and initial state** — playable units, enemies, summons/memosprites/other battle-owned entities, battle-start stats, properties, weaknesses, resistances, initial statuses/resources, or pre-battle effects that actually initialize battle state.
2. **Legal actions and action selection** — Basic ATK, Skill, Ultimate, follow-up, counter, Technique battle-entry effects, enhanced/transformed actions, action availability/disable conditions and costs.
3. **Targeting** — externally selectable target shape, valid-target predicates, taunt/aggro, retargeting, internal hit/effect traversal, random target selection, adjacency/formation semantics.
4. **Timeline and turn execution** — SPD, action value, action advance/delay, extra/inserted turns, interrupts, turn ownership, round/cycle semantics and callback ordering where it affects state.
5. **Resources** — Energy, Skill Points and character-specific gauges, stacks, charges, counters and resource generation/consumption.
6. **HP and survivability** — damage, healing, shields, mitigation, HP consumption, death, revive, defeat prevention and state derived from those systems.
7. **Toughness and Weakness Break** — toughness/stance values, weakness matching, toughness damage, break state, break effects and break-linked action delay/damage/statuses.
8. **Statuses/modifiers/control** — buffs, debuffs, crowd control, DoT, dispel, immunity, effect application chance/resistance, stack/refresh/duration semantics and modifier callbacks.
9. **Triggered mechanics** — on-hit/on-attack/on-damage/on-turn/on-break/on-death/follow-up/counter and other event-driven behavior whose ordering or conditions can change battle state.
10. **Enemy/ally AI** — skill sequence, action conditions, target choice, phase logic, decision weights and AI overrides.
11. **Encounter construction** — stage identity where it changes battle rules, ordered waves/slots, spawn/despawn, phase transitions, stage abilities, global/environment modifiers and battle-event entities for in-scope encounters.
12. **Mode rules and termination** — non-deferred battle-mode mechanics, round/cycle limits, timers that affect outcome, scoring state when it changes battle execution, win/lose/termination conditions.
13. **Equipment and character upgrades only at the combat-effect boundary** — Light Cone/relic/set effects, traces/eidolons and other upgrades are in scope only for stats, conditions or graphs that enter battle execution. Upgrade costs, materials, unlock economy and rewards are not.

## Explicit non-battle exclusions

The following are excluded unless a direct battle-state consequence is demonstrated by consumer tracing:

- camera graphs, camera targets, camera templates and camera-only timing;
- animation states, VFX, SFX, radial blur, look-at, lip-sync and presentation choreography;
- battle UI layout, icons, button presentation, hints, tutorial overlays and localization/text-only descriptions;
- BGM, voice and audio-only metadata;
- loading, scene art, level-decoration and client presentation data;
- character/Light Cone/relic EXP, ascension costs, trace materials, synthesis, shops, warp/gacha, reward tables and collection metadata;
- story, dialogue, mission narrative, release/availability and display metadata when they do not alter battle state;
- editor/test/tooling and telemetry data that does not feed runtime battle behavior.

A presentation operation occurring inside a battle Ability file is **not** battle authority merely because it is colocated with combat operations. Conversely, a source normally associated with progression is not excluded when a specific field/effect is consumed by in-scope battle runtime.

Deferred special-mode data is different from these non-battle exclusions: it can be genuinely combat-authoritative and still be intentionally postponed by the current-phase scope.

## Manual semantic audit requirement

Programmatic automation is a discovery aid, **not a semantic authority**.

Scripts/tools may be used for mechanical work such as:

- enumerating source families and filenames;
- locating exact IDs, hashes, strings and reference edges;
- building candidate inventories and reverse-reference indexes;
- checking path/blob/revision identity;
- diffing or extracting repetitive structural metadata;
- flagging likely battle-related producers for manual inspection.

They must not by themselves promote, reject or interpret a source fact. A final evidence claim requires manual inspection of the relevant raw TBGD rows/graphs and enough surrounding consumer/reference context to understand what the value actually means.

The following especially require human semantic review and must not be inferred from bulk pattern matching alone:

- whether a similarly named file/entity is actually a battle entity or a maze/scene/presentation entity;
- formula operands and operator meaning;
- DynamicValue/hash meaning and ownership;
- target-selection semantics;
- modifier lifetime, stacking, refresh and snapshot behavior;
- callback/event ordering;
- action/turn/timeline behavior;
- stage/monster scaling precedence and joins;
- shared-versus-mode-specific ownership;
- whether a field controls logical battle timing or presentation timing.

Automation may tell us **where to look**. It does not establish **what the data means**. Every `include`, `mixed`, important `exclude`, and semantic formula/behavior claim must have a manually reviewed evidence chain.

## Game-mechanics-informed archaeology requirement

Raw-data archaeology must be guided by an explicit understanding of the corresponding **in-game combat mechanic**. A researcher must not treat a mechanically resolved graph as semantically complete merely because every reference edge can be followed.

Before declaring a mechanism or evidence leaf semantically closed, establish enough of the gameplay model to know what the TBGD chain must explain. Depending on the mechanic, this includes:

- the observable battle-state transition or numeric outcome;
- actor/source/owner/target identity and legal target relationships;
- preconditions, branches, resource gates and trigger conditions;
- timing/order, duration, refresh/stacking/snapshot rules and cleanup;
- important edge cases or interactions that could expose a missing producer, consumer or precedence rule.

This gameplay model may be built or corrected during the archaeology itself. It does not require relying on prior memory. Official descriptions, direct gameplay observation, official data and trusted mechanics references may be used to learn the mechanic, form search hypotheses, identify expected branches and detect missing evidence.

The authority boundary remains strict:

- **gameplay knowledge guides navigation and completeness testing** — it helps determine what behavior should exist and what the raw chain still needs to explain;
- **pinned TBGD remains the source authority for this archaeology revision** — gameplay knowledge must not invent or overwrite a pinned numeric value, reference edge, formula, opcode meaning or ownership relation;
- **runtime and external sources are reconciliation evidence** — if the raw interpretation conflicts with known gameplay behavior, record the mismatch as unresolved, `not_proven` or version drift rather than normalizing either side away.

A closed reference graph is therefore necessary but not sufficient. The interpreted TBGD behavior must also form a coherent explanation of the actual combat mechanic at the relevant version. If a known gameplay branch, lifecycle rule, target behavior, timing rule or edge case has no accounted-for producer/consumer in the pinned chain, that absence is a named evidence gap, not permission to declare the mechanism closed.

The required research loop is:

```text
gameplay semantic model
  -> candidate/search expectations
  -> pinned raw producer/consumer tracing
  -> semantic interpretation
  -> runtime/external reconciliation
  -> closed evidence or explicit unresolved gap
```

This loop prevents both failure modes: guessing game rules from plausible-looking data names, and forcing raw TBGD to match an assumed game rule without source proof.

## Combat timing versus presentation timing

Timing is a high-risk false friend. Animation waits and camera choreography may determine when an effect is displayed without defining the simulator's logical action order. Treat animation/presentation timing as excluded by default. Promote a timing value only after tracing that it gates or schedules a battle-state transition, hit, callback, action insertion, resource mutation or other logical event.

## External action targeting versus internal execution targeting

A user-facing action's selectable target contract and the internal targets traversed by its Ability graph are separate concepts. Internal random/adjacent/all-target operations can be battle-authoritative without changing the externally legal action target shape. The ledger must record both layers rather than flattening one into the other.

## Required completeness method

The PR is complete only when archaeology moves beyond representative samples and accounts for the battle-reachable TBGD corpus **inside the current-phase scope**.

### 1. Build a source-family inventory

Enumerate candidate families at the pinned revision, including at minimum character/skill/equipment, monster, stage/encounter, Ability/modifier, AI, summon/battle-entity, global/environment modifier and battle-event sources used by in-scope combat. Every discovered family receives one of:

- `include` — battle-authoritative/supporting facts are present;
- `exclude` — manually reviewed and no battle-state consequence exists for the claimed scope;
- `mixed` — relevant and irrelevant facts coexist; field/row/operation filtering is required;
- `deferred` — belongs to an explicitly postponed special mode/event family;
- `unresolved` — evidence is insufficient; it must not be silently treated as excluded.

### 2. Traverse battle-root references

Start from known in-scope battle roots (entities, actions, equipment combat effects, enemies, stages/modes) and follow every reference edge that can carry execution semantics into ConfigAbility/modifiers, AI, summons, global effects, stage abilities and shared runtime tables. Record the semantic owner at each edge.

When traversal reaches an explicitly deferred special-mode-only owner, record the boundary and stop expanding that mode. Continue only if the referenced primitive is independently reachable from in-scope combat.

### 3. Reverse-scan for missed producers

Forward traversal alone can miss global or encounter-owned producers. Search for source families that reference known battle graphs/identities or write battle properties/statuses without being reached from the initial roots. Classify those sources explicitly. Reverse scans may be automated for candidate generation, but each promoted producer still requires manual semantic inspection.

### 4. Classify below filename level

Do not use filenames, directory names or raw field names as semantic authority. `ConfigAbility`, character Excel rows, stage rows and mode data are commonly mixed. Trace the consumer and classify at the narrowest practical level: file -> row/entity -> field/opcode/reference edge.

### 5. Preserve negative knowledge

For every high-risk false friend, record why it was rejected. An exclusion without inspected evidence is not completeness evidence. Bulk script classification alone is not inspected evidence.

### 6. Close unknowns rather than normalizing them

If a formula opcode, hash, precedence rule, stage scaling edge or callback ordering cannot be proven, keep it explicit as unresolved. Do not fill it from community formulas or current-version websites.

## Evidence hierarchy

Use sources in this order of authority:

1. **Pinned TBGD raw data** — primary source for this archaeology revision.
2. **Repository lowerer/runtime/validators** — interpretation and implementation cross-check; not a substitute for raw upstream semantics.
3. **Official HoYo documentation/data** — semantic corroboration and terminology.
4. **Trusted independent data/mechanics references** — e.g. KQM or comparable data/theorycraft sources, used to verify interpretation and identify gaps.
5. **Community wikis/guides** — weaker corroboration or discovery aids.

External sources may identify what should be searched or corroborate a semantic interpretation. They must never overwrite a pinned TBGD value, silently bridge a missing reference edge, or erase live/beta/historical version differences.

## Version discipline

This ledger describes the pinned TBGD revision first. Current live sources may contain newer entities, values or mechanics. Record version drift explicitly. A current live value can corroborate that a concept exists, but it cannot prove that the same value or implementation existed at the pinned revision.

## Initial high-priority audit families

The following are priority candidates, not blanket authority classifications:

- `Config/ConfigAbility/**` — execution graphs; strongly mixed with presentation operations;
- `Config/ConfigCharacter/**` — battle wiring and DynamicValue bindings mixed with other character configuration;
- AI configuration families — action/target/phase decisions;
- summon/battle-unit configuration families — spawned battle entities and owner relationships;
- global/stage modifier and battle-event families used by in-scope encounters;
- `ExcelOutput/StageConfig.json` and related in-scope stage tables — encounter construction, mixed with client/presentation metadata;
- monster base/unique/status/skill tables — enemy state, scaling inputs, skills and modifiers;
- avatar skill/trace/rank/equipment tables — only their combat-facing values/graphs;
- Light Cone/relic/set data — combat effects only, not acquisition/progression metadata.

Simulated Universe, Divergent Universe, Currency Wars and event-specific battle families are explicitly deferred in this phase. They may still appear during reference discovery, but their mode-owned graphs/tables do not need full semantic expansion now.

Directories such as camera templates, battle-perform/presentation graphs, UI and BGM are exclusion candidates, **not automatic exclusions**: a family is only closed after checking that no field is consumed by battle-state logic.

## Completion condition

"We sampled enough" is not a completion condition. The archaeology is ready for a later canonical lowering phase only when:

- the current-phase candidate source-family inventory is explicit;
- all in-scope battle-root reference families have been manually traversed or carry named unresolved gaps;
- reverse scans have been performed for shared/global/in-scope encounter-owned producers;
- mixed sources have filtering rules rather than blanket inclusion;
- reviewed non-battle families carry negative evidence;
- deferred special-mode/event families are marked as deferred rather than silently classified as non-battle;
- no unresolved in-scope source family is silently treated as non-battle;
- representative manually audited reference chains cover each major in-scope combat-semantic category above;
- each mechanism claimed as semantically closed has an explicit gameplay semantic model sufficient to identify the behavior, branches, ownership, timing/lifecycle and material edge cases that the raw chain must explain;
- interpreted pinned-TBGD behavior has been reconciled with known gameplay behavior at the relevant version, with material discrepancies retained as explicit unresolved/version-drift evidence rather than silently normalized;
- scripts have not been used as the sole basis for semantic promotion/rejection;
- external corroboration/version context is recorded where useful;
- no archaeology claim requires changing simulator runtime code in this PR.
