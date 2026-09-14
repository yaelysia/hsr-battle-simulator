# Ordinary-combat RNG and callback-order reference chains

## Record metadata

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed` for the representative raw chains below
- Scope: W12 RNG/random-choice primitives and W10 callback/continuation ordering examples
- Runtime production code changed: no
- Important boundary: the pinned TBGD revision is a release-data corpus (`Config`, `ExcelOutput`, `Stages`, `Story`, `TextMap`, README), not a GameCore implementation repository. It exposes draw sites, weights/ranges, event registrations and priority inputs, but not the generic RNG-state owner, scheduler/dispatcher body or all effect-application implementations.

## Gameplay semantic model

Ordinary combat cannot be represented by one generic `probability` primitive. The pinned corpus distinguishes at least:

1. weighted task/branch selection (`RandomConfig`);
2. random target/traversal selection (`Retarget(ByRandom=true)` / shared selectors);
3. status/effect application attempt (`AddModifier.Chance`);
4. direct random scalar/integer generation (`SetDynamicValueByRandom`);
5. AI decision-plane random sources (`ComplexSkillAISourceRandom01` / weighted-random-target sources);
6. presentation-risk random branches whose outcome may not change battle state.

Callback ordering likewise has multiple surfaces: ordered task lists, event-specific modifier priorities, insert-action/insert-ability priority domains, nested abilities, death-rattle, limbo/revive windows and cleanup.

## W12 — Silver Wolf weighted Bug selection

Pinned ordinary chain:

```text
M_SilverWolf_Passive.OnAfterAttack
  -> SetDynamicValue(chance working value)
  -> Retarget(AbilityAttackTargetList)
  -> TriggerAbility(Avatar_Silwolf_00_PassiveSkill_RandomBug)
  -> predicates inspect existing Bug modifiers
  -> RandomConfig when >1 candidate remains
  -> selected AddModifier(Bug1|Bug2|Bug3, Chance=dynamic)
  -> successful Bug OnStack
  -> StackProperty(ATK/DEF/SPD down)
```

The `RandomConfig` branch chooses **which Bug type** is attempted. The chosen `AddModifier` separately carries a `Chance` gate. Therefore branch-choice RNG and effect-application probability are distinct semantic stages.

Candidate reduction is state-dependent:

- three-way branch: raw odds `[0.3333,0.3333,0.3334]`;
- two-way branch: `[0.5,0.5]`;
- one legal candidate: direct deterministic AddModifier without RandomConfig.

This is sample-specific predicate pruning, not proof of a generic no-replacement/shuffle primitive.

## `RandomConfig.OddsList` is not final normalized probability authority

Two independent ordinary samples disprove a universal “entries are final probabilities summing to 1” interpretation:

- Aventurine ordinary Skill02: `[0.2,0.2,0.2]`, sum `0.6`;
- Argenti ordinary Skill03: `[0.3,0.4,0.4]`, sum `1.1`.

Silver Wolf's unit-sum list is therefore only a property of that sample.

Safe pinned representation:

> preserve ordered raw odds/weight inputs plus branch payloads; do not convert them into final branch probabilities until the generic `RandomConfig` consumer/algorithm is recovered.

The pin does not expose whether the implementation normalizes weights, uses intervals/remainders, clamps, or follows another rule.

## W12 — Asta random-target bounce

Asta Skill02 performs an initial deterministic hit, establishes a bounce count, then repeatedly calls shared `Bounce_SelectTarget`.

Pinned shared template:

```text
TemplateParamEntityList
  -> random selector
       ByRandom=true
       MaxNumber=1
       IncludeLimbo=true
  -> selected ParamEntity
  -> caller-provided damage task
```

This closes a distinct ordinary random-target producer -> consumer chain. One target is selected per bounce iteration because the source explicitly constrains `MaxNumber=1`.

Do not generalize this to every `Retarget(ByRandom=true)` occurrence. When `MaxNumber` is absent, single-target semantics remain unproven.

## W12 — direct random value: Aventurine

Aventurine ordinary Skill03 uses a modifier whose OnStack begins with:

- `$type = RPG.GameCore.SetDynamicValueByRandom`
- `DynamicKey = MDF_Coin`
- `ContextScope = ContextModifier`
- `IsInt = true`
- `Min = 1`
- dynamic `Max`

The generated value then feeds a later state/modifier consumer before the helper modifier removes itself.

This is an ordinary random scalar/integer producer distinct from `RandomConfig` and random target selection.

Unresolved engine semantics:

- whether integer `Max` is inclusive/exclusive;
- distribution;
- RNG stream/state ownership.

## W12 — status application input is not final hit probability

Pinned Asta/Guinaifen/Silver Wolf samples show `AddModifier.Chance` as an application input. The corpus separately exposes battle properties including:

- `StatusProbability`
- `StatusProbabilityBase`
- `StatusProbabilityConvert`
- `StatusResistance`
- `StatusResistanceBase`
- `StatusResistanceConvert`

and category-specific anti-debuff/control-resistance grouping.

No generic exported evaluator states the arithmetic joining raw `Chance`, attacker probability properties, defender resistance, category-specific resistance and caps/floors.

Therefore final effect-hit arithmetic is an **engine-authority gap**. It must not be inferred from field names or public formulas.

## Callback-local RNG ordering example — Guinaifen

In Guinaifen ordinary Skill02 projectile-hit task order:

1. a rank branch may attempt a status-resistance modifier with dynamic `Chance`;
2. random retarget executes with `ByRandom=true`, `MaxNumber=3`;
3. Burn modifier application attempts execute with their own dynamic `Chance` on selected targets;
4. damage task executes later.

This proves source-defined task-site order:

`possible resistance application -> random target selection -> Burn application attempts -> damage`

It does not prove RNG-state-advance counts or whether a just-applied resistance modifier synchronously changes a same-hit probability evaluation; those require the generic modifier/RNG consumers.

## Presentation-risk RNG false friend — Jing Yuan

A pinned Jing Yuan ability contains a nested `RandomConfig` with branches whose battle damage operands are equivalent while the visible differing payload is the hit-effect asset.

Therefore:

> `RandomConfig` occurring inside a battle Ability file is not enough to promote it as battle-state RNG.

This also leaves a replay question unresolved: a presentation-only draw could still matter if it advances the same RNG stream as later gameplay draws.

## AI randomness is a separate data plane

Pinned ComplexSkillAI data includes:

- `ComplexSkillAISourceRandom01`;
- a precheck variant with `FromRecord=true`;
- `ComplexSkillAISourceIsCombatPowerWeightedRandomTarget`.

These are consumed through ComplexSkillAI scoring/decision data rather than ordinary Ability `RandomConfig` tasks.

No pinned edge proves that AI randomness shares the same seed/state/stream with execution RNG. `FromRecord=true` is retained literally; its record ownership/reuse semantics are not inferred.

## W12 — engine boundary is now explicit

The exact pinned repository root contains data/configuration surfaces but no GameCore implementation source tree. Repeated representative archaeology has already located the data-facing RNG primitives and their battle consumers. The remaining questions require implementation contracts that are not present in this artifact:

- `RandomConfig` weighted-selection algorithm for non-unit-sum inputs;
- `SetDynamicValueByRandom` endpoint/distribution semantics;
- `AddModifier.Chance` effective status-probability evaluator;
- RNG seed/state/stream allocation and advancement;
- whether execution, AI and presentation draws share a stream;
- whether failed/guaranteed checks consume stream state.

These are now classified as `engine_consumer_unavailable` / `blocked_evidence` for this pin. Future work should reopen them only if a new authoritative engine/source family appears. Additional character samples can improve the primitive census but cannot establish the missing generic algorithm by themselves.

## W10 — priority domains

Pinned `Config/GlobalConfig/PriorityConfig.json` (exact blob `ec353c8fb5a0d8fa0848948d46289a32d2a6a5c5`) exposes separate priority domains for modifier events and inserted actions/abilities.

Representative symbolic mappings establish direction within inspected domains:

- `Highest=0` versus progressively larger/lower-priority insert tiers and defaults near `999999`;
- event entries named `Before...` use lower/negative values;
- `AfterAll...` entries use larger values.

Combined raw evidence supports:

> within an inspected configured priority domain, smaller numeric values execute earlier/have higher priority.

The same file has explicit tables for `OnEnterBattle`, `OnLimboWaitHeal`, `OnPhase1`, `OnAfterAttack`, `OnListenCharacterCreate` and `OnListenCharacterDie`, among others. It does not provide a generic implementation for comparing different event classes or breaking ties inside an equal-priority bucket.

Do **not** compare numbers directly across different priority domains. Equal-priority tie breaking and universal cross-event arbitration remain unresolved.

## W10 — causal three-callback chain on Aglaea

Aglaea Rank02 supplies a source-backed causal chain:

1. listener (`OnListenBeforeSkillUse` or insert-ability-start listener) adds `MAvatar_Aglaea_Rank02_Effect`;
2. the added effect's `OnStack` initializes layer-derived internal state;
3. later `OnBeforeHitAll` consumes that established effect state to modify damage data.

The raw JSON lists `OnBeforeHitAll` before `OnStack`, so this chain is also explicit negative evidence that serialized callback-list order is not dispatch order.

The precise dispatcher structure (immediate nested call vs queued drain) remains unproven.

## W10 — death-rattle continuation by inserted ability

Pinned ordinary Monster_W3_Junk data provides a concrete death-rattle continuation:

- formal death-rattle state/callback;
- `OnDeathrattle` performs state/phase tasks and `SetDieImmediately`;
- then `TurnInsertAbility` schedules the death continuation with `InsertAbilityPriority="MonsterDeathRattle"`;
- owner/target can be `AliveOrLimbo`;
- the inserted ability performs the subsequent death sequence.

This proves death-rattle continuation can be a priority-tiered inserted ability rather than immediate nested `TriggerAbility` execution.

## W10 — Bailu limbo/revive window

Ordinary Bailu closes a distinct defeat-prevention path:

```text
HP <= 0 / enter limbo
  -> OnBeingLimbo eligibility callback
  -> add revive mark
  -> OnLimboWaitHeal with priority AvatarReviveOthers (-70)
  -> TurnInsertAbility(Avatar_Bailu_00_InsertSkill_Revive)
  -> target still HP <= 0
  -> HealHP(... AliveOnly=false)
```

`OnBeforeDying` in the same family has a different cleanup/eligibility responsibility. Therefore `OnBeforeDying`, `OnBeingLimbo` and `OnLimboWaitHeal` are distinct lifecycle stages and must not be flattened into one death event.

## W10/W13 — Aglaea natural servant lifecycle surfaces

Aglaea Servant 11402 now supplies a pinned natural-death decomposition with multiple independently authored event surfaces.

### Pre-death surface

`MServant_AglaeaServant_Passive.OnBeforeDying` performs battle-state cleanup/transfer before final death handling, including:

- conditional speed-layer preservation onto `CasterSummoner`;
- removal of owner-side Skill02/Rank06 state;
- muted cleanup of a still-alive `BattleEventCountDown`.

### Death-rattle surface

`MServant_AglaeaServant_00_DeathRattle` carries the `Deathrattle` behavior flag and runs `OnDeathrattle -> ModifySPNew(CasterSummoner,+20 raw)`.

A separate modifier with `KeepOnDeathrattle` and `RemoveWhenCasterDead` proves selected state may survive through the death-rattle interval and be removed after caster-death state is reached.

### Post-character-death listener

Aglaea's owner passive listens to `OnListenCharacterDie`. When the dead entity intersects `CasterServant`, it sets the owner's internal `_Energy` working value to `0`.

These are source-backed distinct lifecycle stages/surfaces. They substantially narrow the natural-death model, but the generic dispatcher implementation that totally orders `OnBeforeDying`, `OnDeathrattle`, `OnListenCharacterDie`, `OnDestroy` and entity removal is absent from the pinned release-data corpus.

## W10/W13 — BattleEvent-driven muted forced cleanup

A separate Aglaea BattleEvent phase proves that forced cleanup does not reuse the natural death-rattle path:

```text
MAvatar_Aglaea_00_PassiveSkill01_BattleEvent.OnPhase1
  -> select servant carrying MServant_AglaeaServant_Passive
  -> TurnInsertAbility(
       Servant_Aglaea_00_PassiveSkill01_ForceKill_Insert,
       InsertAbilityPriority=AvatarBuffOthers)
  -> ForceKill(servant, MuteHpChange=true, MuteAllTriggerDeath=true)
  -> SetDieImmediately(servant)
  -> explicit owner/servant-linked modifier cleanup
```

The insert priority is a real configured ordering input. Because `MuteAllTriggerDeath=true`, this branch is explicit negative evidence against treating every servant removal as a natural death-rattle sequence.

Presentation waits/effects inside the inserted ability do not establish logical cleanup timing.

## W10 — dispatcher boundary is now explicit

`PriorityConfig.json` provides event/insert priority tables, and the exact data gives several causal chains, but the pinned repository does not contain the generic GameCore dispatcher implementation. Therefore the following are `engine_consumer_unavailable` / `blocked_evidence` at this pin:

- same-priority tie breaking;
- universal cross-event arbitration;
- exact queue/stack/drain model for nested callbacks;
- full universal non-muted death total order after the exported event surfaces;
- final entity/modifier destruction arbitration when multiple listeners participate.

This does **not** erase the source-backed local orders above. It prevents the ledger from converting event names or JSON order into a fabricated universal dispatcher.

## Current engine/export boundaries

Still unresolved after representative source closure:

1. RNG seed/state/stream owner across `RandomConfig`, random retarget, `AddModifier.Chance`, `SetDynamicValueByRandom`, AI and presentation draws — `engine_consumer_unavailable`;
2. `RandomConfig` generic non-unit-sum selection algorithm — `engine_consumer_unavailable`;
3. `SetDynamicValueByRandom` range endpoint/distribution — `engine_consumer_unavailable`;
4. final `AddModifier.Chance` / StatusProbability / StatusResistance equation — `engine_consumer_unavailable`;
5. whether failed/guaranteed checks consume RNG state — `engine_consumer_unavailable`;
6. same-priority callback/insert tie break — `engine_consumer_unavailable`;
7. universal cross-event ordering among attack/hit/damage/break/kill/death events — `engine_consumer_unavailable`;
8. universal final destruction/removal order after the now-identified Aglaea natural-death event surfaces — `engine_consumer_unavailable`.

These should only be reopened when an accepted new source exposes the missing engine contracts.

## Durable lowering guardrails

- Preserve raw `OddsList` inputs, not guessed probabilities.
- Keep branch-choice RNG distinct from application probability.
- Keep random target traversal distinct from `RandomConfig`.
- Include `SetDynamicValueByRandom` in the RNG primitive inventory.
- Do not promote presentation-only random branches solely because they use a combat-file `RandomConfig`.
- Do not infer RNG stream ownership from nearby draw sites.
- Keep event priority domains separate from insert priority domains.
- Do not use JSON callback order as dispatch order.
- Keep limbo/revive/death-rattle/natural-death-listener/muted-force-kill paths distinct.
- Treat the release-data root shape as an explicit source boundary: data-facing opcode presence does not imply the GameCore implementation body is available.
