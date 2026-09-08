# Ordinary-combat RNG and callback-order reference chains

## Record metadata

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed` for the representative raw chains below
- Scope: W12 RNG/random-choice primitives and W10 callback/continuation ordering examples
- Runtime production code changed: no
- Important boundary: the pinned TBGD release-data dump exposes draw sites, weights/ranges, event registrations and priority inputs, but not the generic RNG-state owner or all dispatcher/effect-application implementation bodies.

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

No generic exported evaluator was found that states the arithmetic joining raw `Chance`, attacker probability properties, defender resistance, category-specific resistance and caps/floors.

Therefore final effect-hit arithmetic is an **engine-authority gap**, not something to infer from field names or public formulas.

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

## W10 — priority domains

Pinned `Config/GlobalConfig/PriorityConfig.json` exposes separate priority domains for modifier events and inserted actions/abilities.

Representative symbolic mappings establish direction within inspected domains:

- `Highest=0` versus progressively larger/lower-priority insert tiers and defaults near `999999`;
- event entries named `Before...` use lower/negative values;
- `AfterAll...` entries use larger values.

Combined raw evidence supports:

> within an inspected configured priority domain, smaller numeric values execute earlier/have higher priority.

Do **not** compare numbers directly across different priority domains. Equal-priority tie breaking remains unresolved.

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

## Death-rattle retention versus muted cleanup

Aglaea servant evidence provides two negative/positive rules:

- a modifier with `KeepOnDeathrattle` + later `RemoveWhenCasterDead`/`OnDestroy` demonstrates cleanup can occur **after** death-rattle;
- `ForceKill(...MuteAllTriggerDeath=true)` is an explicit trigger-suppressed cleanup path and must not be used as ordinary death-order evidence.

## Current engine/export boundaries

Still unresolved after representative source closure:

1. RNG seed/state/stream owner across `RandomConfig`, random retarget, `AddModifier.Chance`, `SetDynamicValueByRandom`, AI and presentation draws;
2. `RandomConfig` generic non-unit-sum selection algorithm;
3. `SetDynamicValueByRandom` range endpoint/distribution;
4. final `AddModifier.Chance` / StatusProbability / StatusResistance equation;
5. whether failed/guaranteed checks consume RNG state;
6. same-priority callback/insert tie break;
7. universal cross-event ordering among attack/hit/damage/break/kill/death events;
8. a complete non-muted, non-revived ordinary death total order through listeners, destruction and final entity removal.

These should remain explicit engine-authority gaps if no accepted source outside the pinned release-data dump supplies the implementation.

## Durable lowering guardrails

- Preserve raw `OddsList` inputs, not guessed probabilities.
- Keep branch-choice RNG distinct from application probability.
- Keep random target traversal distinct from `RandomConfig`.
- Include `SetDynamicValueByRandom` in the RNG primitive inventory.
- Do not promote presentation-only random branches solely because they use a combat-file `RandomConfig`.
- Do not infer RNG stream ownership from nearby draw sites.
- Keep event priority domains separate from insert priority domains.
- Do not use JSON callback order as dispatch order.
- Keep limbo/revive/death-rattle/muted-force-kill paths distinct.
