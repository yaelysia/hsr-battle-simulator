# TBGD battle-semantic scope and completeness contract

## Purpose

This archaeology is not a sample collection. Its end state is a source-backed inventory of **all TBGD data and graphs at the pinned revision that can materially change Honkai: Star Rail battle state or battle execution**, while explicitly excluding progression, UI, camera, animation/presentation and other non-battle semantics.

Pinned TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`.

The practical question is not "does this file sound combat-related?". The question is:

> If this source fact were changed or removed while all other inputs stayed fixed, could a battle start differently, admit a different action, evolve through a different reachable state, produce a different numeric/state outcome, choose a different target/action, transition differently, or terminate differently?

If yes, the relevant fact belongs in the battle corpus. If no, it does not. If one source mixes both kinds of facts, it is `mixed_requires_filter` and must be classified below file level.

## Battle-state consequence test

A source fact is in scope when it can materially affect at least one of these concepts:

1. **Battle entities and initial state** — playable units, enemies, summons/memosprites/other battle-owned entities, battle-start stats, properties, weaknesses, resistances, initial statuses/resources, or pre-battle effects that actually initialize battle state.
2. **Legal actions and action selection** — Basic ATK, Skill, Ultimate, follow-up, counter, Technique battle-entry effects, enhanced/transformed actions, mode-specific actions, action availability/disable conditions and costs.
3. **Targeting** — externally selectable target shape, valid-target predicates, taunt/aggro, retargeting, internal hit/effect traversal, random target selection, adjacency/formation semantics.
4. **Timeline and turn execution** — SPD, action value, action advance/delay, extra/inserted turns, interrupts, turn ownership, round/cycle semantics and callback ordering where it affects state.
5. **Resources** — Energy, Skill Points and character/mode-specific gauges, stacks, charges, counters and resource generation/consumption.
6. **HP and survivability** — damage, healing, shields, mitigation, HP consumption, death, revive, defeat prevention and state derived from those systems.
7. **Toughness and Weakness Break** — toughness/stance values, weakness matching, toughness damage, break state, break effects and break-linked action delay/damage/statuses.
8. **Statuses/modifiers/control** — buffs, debuffs, crowd control, DoT, dispel, immunity, effect application chance/resistance, stack/refresh/duration semantics and modifier callbacks.
9. **Triggered mechanics** — on-hit/on-attack/on-damage/on-turn/on-break/on-death/follow-up/counter and other event-driven behavior whose ordering or conditions can change battle state.
10. **Enemy/ally AI** — skill sequence, action conditions, target choice, phase logic, decision weights and AI overrides.
11. **Encounter construction** — stage identity where it changes battle rules, ordered waves/slots, spawn/despawn, phase transitions, stage abilities, global/environment modifiers and battle-event entities.
12. **Mode rules and termination** — special battle-mode mechanics, round/cycle limits, timers that affect outcome, scoring state when it changes battle execution, win/lose/termination conditions.
13. **Equipment and character upgrades only at the combat-effect boundary** — Light Cone/relic/set effects, traces/eidolons and other upgrades are in scope only for stats, conditions or graphs that enter battle execution. Upgrade costs, materials, unlock economy and rewards are not.
14. **Roguelike/event systems only at the combat-effect boundary** — blessings, curios, equations, scepters, components, event buffs or other mode assets are in scope when their selected state produces a battle modifier/action/entity/rule. Their acquisition UI, shop economy, collection/progression or reward flow is out of scope unless it changes battle execution directly.

## Explicit exclusions

The following are excluded unless a direct battle-state consequence is demonstrated by consumer tracing:

- camera graphs, camera targets, camera templates and camera-only timing;
- animation states, VFX, SFX, radial blur, look-at, lip-sync and presentation choreography;
- battle UI layout, icons, button presentation, hints, tutorial overlays and localization/text-only descriptions;
- BGM, voice and audio-only metadata;
- loading, scene art, level-decoration and client presentation data;
- character/Light Cone/relic EXP, ascension costs, trace materials, synthesis, shops, warp/gacha, reward tables and collection metadata;
- story, dialogue, mission narrative, release/availability and display metadata when they do not alter battle state;
- editor/test/tooling and telemetry data that does not feed runtime battle behavior.

A presentation operation occurring inside a battle Ability file is **not** battle authority merely because it is colocated with combat operations. Conversely, a source normally associated with progression or an event is not excluded when a specific field/effect is consumed by battle runtime.

## Combat timing versus presentation timing

Timing is a high-risk false friend. Animation waits and camera choreography may determine when an effect is displayed without defining the simulator's logical action order. Treat animation/presentation timing as excluded by default. Promote a timing value only after tracing that it gates or schedules a battle-state transition, hit, callback, action insertion, resource mutation or other logical event.

## External action targeting versus internal execution targeting

A user-facing action's selectable target contract and the internal targets traversed by its Ability graph are separate concepts. Internal random/adjacent/all-target operations can be battle-authoritative without changing the externally legal action target shape. The ledger must record both layers rather than flattening one into the other.

## Required completeness method

The PR is complete only when archaeology moves beyond representative samples and accounts for the battle-reachable TBGD corpus.

### 1. Build a source-family inventory

Enumerate candidate families at the pinned revision, including at minimum character/skill/equipment, monster, stage/encounter, Ability/modifier, AI, summon/battle-entity, global/environment modifier, battle-event and mode-specific sources. Every discovered family receives one of:

- `include` — battle-authoritative/supporting facts are present;
- `exclude` — reviewed and no battle-state consequence exists for the claimed scope;
- `mixed` — relevant and irrelevant facts coexist; field/row/operation filtering is required;
- `unresolved` — evidence is insufficient; it must not be silently treated as excluded.

### 2. Traverse battle-root references

Start from known battle roots (entities, actions, equipment combat effects, enemies, stages/modes) and follow every reference edge that can carry execution semantics into ConfigAbility/modifiers, AI, summons, global effects, stage abilities and shared runtime tables. Record the semantic owner at each edge.

### 3. Reverse-scan for missed producers

Forward traversal alone can miss global or mode-owned producers. Search for source families that reference known battle graphs/identities or write battle properties/statuses without being reached from the initial roots. Classify those sources explicitly.

### 4. Classify below filename level

Do not use filenames, directory names or raw field names as semantic authority. `ConfigAbility`, character Excel rows, stage rows and mode data are commonly mixed. Trace the consumer and classify at the narrowest practical level: file -> row/entity -> field/opcode/reference edge.

### 5. Preserve negative knowledge

For every high-risk false friend, record why it was rejected. An exclusion without inspected evidence is not completeness evidence.

### 6. Close unknowns rather than normalizing them

If a formula opcode, hash, precedence rule, mode join, stage scaling edge or callback ordering cannot be proven, keep it explicit as unresolved. Do not fill it from community formulas or current-version websites.

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
- global/stage/mode modifier and battle-event families — encounter-owned mechanics;
- `ExcelOutput/StageConfig.json` and related stage/mode tables — encounter construction, mixed with client/presentation metadata;
- monster base/unique/status/skill tables — enemy state, scaling inputs, skills and modifiers;
- avatar skill/trace/rank/equipment tables — only their combat-facing values/graphs;
- Light Cone/relic/set and mode-buff data — combat effects only, not acquisition/progression metadata.

Directories such as camera templates, battle-perform/presentation graphs, UI and BGM are exclusion candidates, **not automatic exclusions**: a family is only closed after checking that no field is consumed by battle-state logic.

## Completion condition

"We sampled enough" is not a completion condition. The archaeology is ready for a later canonical lowering phase only when:

- the candidate source-family inventory is explicit;
- all battle-root reference families have been traversed or carry named unresolved gaps;
- reverse scans have been performed for global/mode-owned producers;
- mixed sources have filtering rules rather than blanket inclusion;
- reviewed non-battle families carry negative evidence;
- no unresolved source family is silently treated as non-battle;
- representative reference chains cover each major combat-semantic category above;
- external corroboration/version context is recorded where useful;
- no archaeology claim requires changing simulator runtime code in this PR.
