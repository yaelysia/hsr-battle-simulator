# TBGD Battle Evidence Ledger

This directory is the durable evidence store for the manually audited TurnBasedGameData (TBGD) battle-source archaeology tracked by [Issue #7](https://github.com/yaelysia/hsr-battle-simulator/issues/7) / [PR #8](https://github.com/yaelysia/hsr-battle-simulator/pull/8).

## Core purpose

**Determine which facts in the pinned game database affect in-scope combat, what those facts mean, and how their source/reference chains fit together, so backend work can reuse and implement them.**

The deliverable is a version-pinned, manually audited battle-source catalog, relationship graph and evidence ledger. It is not a backend implementation, runtime-admission acceptance or repair-coordination project. Backend usefulness is the purpose of the research output; backend implementation readiness is not its completion criterion.

Pinned TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`.

The governing source scope and completeness obligations remain [BATTLE_SCOPE.md](BATTLE_SCOPE.md). Representative slices are milestones, not a substitute for accounting for the in-scope battle-reachable corpus. Deferred modes remain deferred, not non-battle.

**Combat-input boundary, clarified 2026-09-24:** the selected finished build's properties, effective skill parameters and activated effects are in scope; acquisition, EXP, material costs, ascension/unlock prerequisites and relic roll history are not. Classify mixed tables below file level using actual consumers and battle consequences. A progression-associated filename neither admits its costs nor excludes its proven combat inputs; a plausible property/variable name does not establish its meaning.

## Current shared result — F01, 2026-09-24

The [general parameter/effective-property record](../../../../../docs/tbgd_evidence/shared/general_parameter_effective_property_semantics_v1.md) unifies family/owner/level/index routing and working-value scope with ordinary base/percentage/flat composition. Empty-Param rank rows can still change effective skill levels; those effects remain separate from UnlockCost. Selected table coefficients are not new live buffs, and public stat equations do not silently certify R5's different local base-loader or affix arithmetic.

Exact consumers resolve misleading names: MDF_Target_CurrentAttack reads recipient BaseAttack and participates in a grant capped by provider Attack; Avatar_Gepard_Passive02_AttackDeltaUp actually writes AttackConvert after an explicit Defence-minus-DefenceConvert calculation. Refresh sites, actual property components, static set contributions and matching-hit contexts remain distinct. Repeated parameter values are not extra grants. Public formulas/descriptions, pinned fields and synthetic calculations retain separate provenance.

F01/W01/W02/W03 remain active for resolution/defaults, level/override precedence, additional conversion/sampling rules, exact bounds and source coverage. **Integrated foundation-gap and coverage review** is next: reconcile F01-F10 with the W worklist and source-family scope before choosing another bounded common-mechanism closure. Ten first-pass records are not proof of foundational completeness or authorization to default to character completion. No progression workflow, backend gate or runtime E is introduced.

## Shared result — F10, 2026-09-24

The [general event/entity/encounter-lifecycle record](../../../../../docs/tbgd_evidence/shared/general_event_entity_encounter_lifecycle_v1.md) distinguishes installed listeners, eligible events, pending requests and execution rechecks; lethal recovery, shared provider quotas and recipient readiness; natural death work and muted cleanup; and phase, wave and battle-result scopes. It explicitly reuses W10's known staged rescue and servant findings rather than presenting rereads as first discoveries. Exact ActivateAfterRevive=false, control/source/target exclusions and a guarded inserted heal supply additional reusable distinctions.

Published skill descriptions establish the selected once-per-battle recovery limits. Count and update sites retain their raw omissions; UI counters and new-member callbacks do not become extra charges. Shared stage graphs separately author enemy birth with passive suppression, later passive/entry requests, dying/turn-end wave guards and provisional-win rechecks. Phase reset acts on an existing Caster; leave callbacks also occur on loss and manual quit. None of these observations supplies a universal cross-event total order or an inferred muted-event set.

F10/W10/W13/W16/W17 remain active for competing recoveries, exact buff/action-slot retention, counter defaults, forced-departure triggers and exceptional spawn/result rules. Its F01 handoff has now produced the bounded parameter/property synthesis above. Prior next-task wording is checkpoint history rather than an unexecuted assignment. The numbered first-pass records do not by themselves certify foundation completeness; remaining common-rule gaps still need review. No backend gate or runtime E is introduced.

## Shared result — F09, 2026-09-24

The [general target-selection/expansion/source-context record](../../../../../docs/tbgd_evidence/shared/general_target_selection_expansion_source_context_v1.md) separates selectable primaries, automatic sets, actual per-effect recipients, internal traversal and actual source ownership. Exact examples distinguish primary/adjacent healing from primary-only explicit cleanse, bounded bounce selection from an all-target impact envelope, and a damage-distribution destination from the original attack target. The bounce template retains its opaque type, full validity predicate and IncludeLimbo rather than being replaced by a guessed generic selector.

The attributed positive-weight aggro model is paired with a pinned BaseAggro input and reused conditional AggroAddedRatio evidence. Collateral exposure is derived separately under a stated geometry; taunt and special policies are not reduced to a universal weighted draw. A guarded HitDamageSplit chain advances F04's distribution question, while InheritCaster=TargetSelf and a credited stat/kill-Energy report distinguish parameter donor from additional-damage owner. R7's Asta/shared-template cached-anchor discrepancy is explicitly recorded with actual exact-pin reread blobs, without inventing a version change.

F09/W11/W15 remain active for target invalidation, terminal/empty pools, special policy precedence, formation changes and full context/event attribution. Public descriptions, historical observations and synthetic calculations retain separate provenance. Its F10 handoff has now produced the bounded lifecycle record above; prior next-task wording is checkpoint history rather than an unexecuted assignment. No backend gate, generic AI implementation or runtime E is introduced.

## Shared result — F04, 2026-09-24

The [general healing/shield/HP-resolution record](../../../../../docs/tbgd_evidence/shared/general_healing_shield_hp_resolution_v1.md) reuses the recovered base equations and separates offered healing from realized HP gain, shield creation from recipient mitigation/absorption, ordinary non-additive shields from explicit accumulation, and incoming damage from direct HP loss. The selected Sam healing penalty is paired with an actual-healing-owner condition and a signed Target_HealTakenRatio request; its reported additive relationship does not become a permanent healer-property mutation or an unread pinned numeric row.

New exact source chains include the Set103 four-piece0.2 -> SkillRelic -> ShieldAddedRatio contribution, a named CurrentShield read with an explicit zero fallback, and separate StackShield amount/cap operands followed by dependent-state cleanup. Public skill text explains repeated-shield accumulation, while the credited mitigation-before-shield experiment is explicitly reused rather than claimed newly performed. Ordinary single-shield absorption and a separately attributed distribution model retain their applicability limits.

F04/W05 remain active for positive incoming-heal combinations, overflow event payloads, changed-property/cap sampling, multi-shield draining/expiry and special HP routes. These specific questions do not erase the ordinary rules. Its F09 handoff has now produced the bounded targeting/source-context record above, including a selected raw distribution join. Prior next-task wording is checkpoint history rather than an unexecuted assignment. No backend gate or runtime E is introduced.

## Shared result — F07, 2026-09-24

The [general Energy/Skill Point economy record](../../../../../docs/tbgd_evidence/shared/general_energy_skill_point_economy_v1.md) reconciles selected raw SP/BP families with actor Energy and shared team Skill Points. It distinguishes ordinary rate-amplified generation, fixed absolute grants, fixed recipient-maximum grants, cost/capacity, signed spending and offered versus realized gain. Existing Natasha rows are paired with explicitly labeled public skill data; new typed Tingyun/Huohuo requests preserve their distinct operands and recipients instead of applying one formula to every ModifySPNew.

New shared distinctions include a direct SPRatioBase0.05 input, separate team balance/capacity operations, signed per-point expenditure and a first-wave entry grant. The published memosprite redirection/one-per-memomaster rule explains the actual OnlyAddSPOnceForServant selector without inventing its native body. Credited historical ERR testing is retained while its contested rounding inference is rejected. Public skill values, exact pinned rows, source expressions and synthetic calculations remain separately identified.

F07/W08 remain active for initial Energy/carry-over, per-hit allocation, native input transport, per-family rate/owner sampling, special resources and transaction-order/precision questions. The covered resource names and models supersede R4's blanket native-only withholding, not its actual source gaps. Its F04 handoff has now produced the bounded sustain record above; the prior handoff remains checkpoint history rather than an unexecuted assignment. No backend gate or runtime E is introduced.

## Shared result — F08, 2026-09-24

The [general Speed/Action Value/action-clock record](../../../../../docs/tbgd_evidence/shared/general_speed_action_value_turn_clock_v1.md) supplies the ordinary timing model and concrete source distinctions: speed-only rescaling preserves remaining distance; normalized advance/delay applies to a full interval rather than a percentage of remaining AV; absolute zeroing, current-action cost and insertion remain different operations. Normal turns, extra actions, Ultimates, hits and modifier clocks are not interchangeable events.

New source chains include typed Asta SpeedDelta/lifetime inputs, exact relic Set110 four-piece0.25 through Equip/RelicAbility's SkillRelic binding to post-Ultra advance, and Bronya's selected SetActionDelay0 branch. The root RelicAbility sibling has different serialization and is not spliced into the typed chain. Preshow is not a second mutation. Public normalization10000 is retained separately from raw SpeedToDelayDistance1000 without an invented native unit conversion.

This first F08 pass supersedes the older W07/timeline blanket restriction on public formulas only for the supported ordinary rules. Initial-order models and first-step exceptions retain attribution; same-time clamps, exceptional zero-ready/insertion ordering, native unit transport and the complete event-to-clock map remain named questions. F08/W07/W10 are not globally closed and no runtime E is added. Its F07 handoff has now produced the bounded resource record above; prior next-task wording is checkpoint history rather than an unexecuted assignment.

## Shared result — F06, 2026-09-24

The [general modifier identity/stacking/lifetime record](../../../../../docs/tbgd_evidence/shared/general_modifier_identity_stacking_lifetime_v1.md) continues the F05 checkpoint that was already published before the interruption. It separates state identity, caster/holder, layers/caps, remaining duration, sampling and removal dependencies. Selected source/model chains distinguish refreshing a capped stack group from explicitly adding to an existing timer, natural ticking from extra activation, and a caster-timed parent from recipient-side child effects.

New pinned operations include SetModifierValueByBehaviorFlag(Add,LifeTime), a parent installing children on current and newly appearing eligible members, and named cleanup when that parent ends. Public skill text and authored explanations identify the observable timer/stack behavior without inventing unread pinned numerical rows or native matching/dispatcher code. The ordinary dynamic-DoT explanation and the limited snapshot report retain their actual evidence strength; no new gameplay experiment is claimed.

F06/W09/W10 remain active for specific same-template matching, stronger/weaker and already-extended update precedence, first-step/action exceptions, property sampling and overlapping removal visibility. F06 handed off to F08's action/clock boundary, whose first-pass result is now above. The prior handoff remains checkpoint history rather than an unexecuted current assignment; no backend implementation dependency is introduced.

## Shared result — F05, 2026-09-24

The [general effect-application record](../../../../../docs/tbgd_evidence/shared/general_effect_application_hit_resistance_immunity_v1.md) supplies an attributed ordinary base-chance equation and inverse threshold, fixed-proc versus status-request routing, general versus category resistance, shared immunity maps, consumed protection and actual-attempt counting. A two-hit/one-Freeze-request source discriminator prevents equating damage hits with debuff rolls. A control-category contribution is distinct from general Effect RES; one-use ImmuneDebuff protection is expressed through event removal, not a fabricated100% resistance or Count field.

Published skill wording, source operations, formula interpretations and calculated examples remain separately identified. No same-pin glossary join is claimed where large-file transport did not expose the text. The old native-evaluator-only stopping rule is superseded for the probability model actually covered; immunity-charge arbitration, overlapping categories, explicit overrides, application-source sampling and special Break applicability remain precise questions. F05/W09/W12 are not globally closed and no local-runtime E is added.

F05 handed off to F06's modifier-instance and lifetime boundary, whose first-pass result is now above. F03's former F05-next checkpoint and F05's former F06-next checkpoint remain history rather than unexecuted current assignments; this is not a new character-completion sequence or a backend dependency.

## Shared result — F03, 2026-09-24

The [general weakness/toughness/Break/Super Break record](../../../../../docs/tbgd_evidence/shared/general_weakness_toughness_break_super_break_v1.md) delivers a reusable shared-rule map: old/displayed toughness units, the exact level-based Break table, initial Break versus attack-Q-based Super Break, seven elemental branches, and common versus elemental action-delay inputs. It preserves the distinction between a supported observable amount/formula and an unidentified native context-injection edge. Level80 uses the exact pinned `BreakBaseDamage=3767.5535`; the shared Super Break expression has a literal denominator30 in old units.

Physical capped target-HP scaling, Wind layer-dependent damage, Frozen/Entangle Pursued damage versus DOT, and separate Quantum/Imaginary delay inputs are traced through shared installers and modifier consumers. Existing R2/F02 ownership and state chains are reused, not replaced by another whole-character study. The first common-rule pass is delivered; F03/W06 remain active for threshold/accumulator allocation, special toughness regimes, source injection and specific state-sampling questions. Calculations are predictions, not new game/runtime tests.

F03 prioritized F05 because of its shared elemental Chance1.5 inputs. The F05 result and next priority are now recorded above; the earlier F03 checkpoint remains historical evidence, not an unexecuted current assignment. No backend admission, repair or merge dependency is introduced.

## Current priority — foundations before character completion, 2026-09-23

The [foundation-first research roadmap](../../../../../docs/tbgd_evidence/shared/foundational_mechanics_research_roadmap_v1.md) is the current priority overlay. Research reusable rules, shared inputs and applicability first; characters, monsters, equipment and stages serve as discriminating samples, not the default unit of kit completion. The existing W worklist remains the obligation ledger, not a backend gate or a fixed denominator.

The [general damage formula/input-layer record](../../../../../docs/tbgd_evidence/shared/general_damage_formula_and_input_layers_v1.md) starts this pass. It joins attributed ordinary damage mathematics to exact shared DEF constants, common monster reduction/break/restoration and existing parameter/context/property evidence. It separates outgoing bonus from vulnerability, additive DEF reduction/ignore from their ownership, and the common toughness reduction from duplicate counting. Ordinary formulas are positive knowledge; exact cap quantities, special modes, rounding and transition-hit timing remain named questions.

This record supersedes R1's historical blanket restriction on public formulas for the claims it covers, without rewriting R1's exact source evidence. No global W04 closure or local-runtime validation is claimed. F01-F10 now have first-pass records; the roadmap sets integrated common-gap and source-coverage review as the next priority, not automatic character completion. The foundation roadmap records the remaining obligations and their exit criteria; no native-code recovery, progression simulation or implementation repair is a prerequisite.

## Current source finding — Guinaifen Burn, 2026-09-23

The [Guinaifen Burn description/application/tick/extra-trigger record](../../../../../docs/tbgd_evidence/shared/guinaifen_burn_tick_detonation_source_chain_v1.md) joins Skill121002/121003/121004 description hashes directly to same-pin TextMapCHS, exact level parameters, CharacterConfig bindings and Ability/shared-modifier consumers. It records the ordinary ATK-based Burn equation, affected-enemy turn-start tick, separate Ultimate multiplier, and Firekiss's distinct damage-taken layer. Precise raw percentages are not replaced by formatted web values.

The [Firekiss timing and E2/E4 follow-up](../../../../../docs/tbgd_evidence/shared/guinaifen_burn_timing_eidolon_attribution_v1.md) continues the recovered checkpoint rather than repeating it. Published talent wording and identifiable community explanations now support the ordinary rule that a triggering Burn does not benefit from its newly generated Firekiss layer; the raw before-hit callback and unspecified internal settlement mapping are preserved. Newly read rank/binding/graph evidence closes E2's conditional `p+0.4`, not `p*1.4`, and E4's separate own-source, Fire/DOT/non-split +2 Energy request. Burn originator, detonator and listener owner remain distinct. These are source/model findings, not new game measurements or backend acceptance.

**Mechanically meaningful skill descriptions are semantic evidence, not merely navigation hints or blanket presentation-only text.** Prefer the exact SkillDesc.Hash -> same-pin TextMap join when available; reconcile the described owner, operands, targets, conditions and timing with the graph. Description and data are complementary, not independent gameplay experiments. This does not promote all localization/UI text or silently resolve unmentioned exceptions. The selected DoT record introduces no backend dependency or whole-package completion claim.

## Public mechanics and result-led research — 2026-09-23

The [healing/shield public-model reconciliation](../../../../../docs/tbgd_evidence/shared/public_mechanics_healing_shield_reconciliation_v1.md) is the first applied checkpoint under the clarified method. It supplies positive equations, source mappings, selected timing and a first-hand community test instead of leaving all arithmetic unknown because the native evaluator was not exported.

For an established mechanic, first consult relevant game-data publications and original community theorycraft/testing. Extract the formula, operands, owners, conditions, timing and important exceptions; use their predicted consequences to navigate the pinned data. Return with a source-to-model map and a supported result, not just a list of numeric fields.

Keep pinned raw facts, public gameplay evidence and their reconciled interpretation explicit. Reliable public models and controlled experiments are usable evidence for observable mechanics, not merely navigation hints. A missing native function body does not invalidate that knowledge. Do not require a native implementation dump or a fresh personal replay of every established test before recording an attributed, adequately supported gameplay model.

This does not permit changing pinned coefficients, fabricating a missing reference or promoting community formulas to native code. Record source/version/test scope, distinguish independently observed results from calculated examples, and examine conflicting or underdetermined interpretations. Sites copying the same database do not constitute independent experiments. Negative results should name the remaining question, not erase an established basic equation.

The former R3/March blanket restrictions on deriving a usable equation from public descriptions/formulas are superseded by this checkpoint. Selected base healing, base shielding and recipient-turn-start HOT are now reconciled; native snapshot internals, exact rounding and universal callback order remain separately scoped questions. Public experiments, not only new engine sources, can advance those questions too.

## Current scope correction — 2026-09-23

The [PR #8 scope-drift audit](../../../../../docs/tbgd_evidence/shared/pr8_scope_drift_audit_2026-09-23.md) restores the original research charter after the owner explicitly rejected the backend workflow that had entered R9.

This correction supersedes the **research-status and sequencing authority** of earlier kernel-first/admission/repair instructions, including the post-R4/post-R5 compactions, R6 repair-dependent stops, R7/R8 mismatch-stop rules, R9 admission plan/checkpoint, and R9A dependency/restart comments. It does not invalidate their correctly scoped raw evidence or rewrite historical execution results.

- `NEEDS_REPLAN`, implementation repair acceptance, upstream implementation-PR waits and repair-before-next-research rules are not current PR #8 research states or gates. Historical quotations may remain for auditability; they are not instructions.
- R9's ordinary servant source facts are retained in the [corrected R9 entry](../../../../../docs/tbgd_evidence/shared/owned_servant_runtime_admission_v1.md). Its runtime-admission task is withdrawn from the archaeology completion path, not relabeled as successfully executed or globally complete.
- The R9-added W13 backend caller checklist item has been removed by restoring that worklist's exact pre-R9 blob. This removes only the implementation item, not the servant source findings or any other research leaves. The audit records the old item and its disposition.
- W13 remains `active` for actual unresolved source semantics. A missing local CreateServant handler does not make the pinned creation occurrence unknown, and it does not block unrelated research.
- R0-R8 retain their recorded bounded source claims. C/D/E observations remain restricted to their inspected/tested SHA and actual scope. No package is newly promoted to `mechanism_closed`.
- The scope correction did not authorize the old numbered implementation sequence. The subsequent public-model checkpoint above is separately requested archaeology, not R9A or an automatic R10 continuation.

The full prior README and R9 review remain available at immutable evidence head [8daa6a8](https://github.com/yaelysia/hsr-battle-simulator/tree/8daa6a8abb9a15e423ecf987356dcc0a936565ba). No history is erased or backend defect declared repaired.

## Authority and research method

Programmatic discovery is **candidate generation only**. A path, field, opcode, formula, dynamic value or reference edge is not authoritative merely because a tool can find it.

A source claim requires manual semantic inspection of pinned raw rows/graphs, their owners, bindings, references, conditions and battle-state consequences. Classify mixed sources below file level and retain false friends and negative evidence.

The research chain is:

```text
gameplay question, public model and observed consequences
-> exact pinned producer / reference / binding / authored consumer
-> source-to-model reconciliation and useful battle semantics
-> reviewed evidence plus precisely named remaining uncertainties
-> reusable facts for later backend consumption and implementation
```

An authored consumer in this chain can be a TBGD Ability task, Modifier, selector, formula operand or callback. It must not silently be replaced by a requirement that our Python runtime implements that operation.

The downstream architecture remains `TBGD -> compiler/lowering -> Canonical IR -> Combat Core`. That architecture explains how research may be consumed; it is not an obligation to make the entire path execute inside this evidence PR.

Gameplay knowledge guides questions and completeness checks and may independently support a behavior model. It cannot silently fill missing pinned values or claim recovery of hidden native code. External/runtime disagreement is a reason to inspect and document the discrepancy, not to force either source to match the other.

## Local implementation comparison is supplementary

Reading current lowering, IR, runtime and validators is allowed when it helps navigation, exposes an interpretation assumption or identifies a concrete consumption concern. Such comparison does not select the research scope, replace raw authority, or require repair before research can continue.

Keep the independent axes when relevant:

| Axis | Meaning | Consequence for this ledger |
| --- | --- | --- |
| A | TBGD source-facing claim closed | State the exact source-supported claim, not whole-mechanism completion. |
| B | Pinned export/native-engine gap | Name the missing source contract; distinguish an unavailable body from an externally established behavior model. |
| C | Local implementation exists | Optional implementation observation, not proof of A. |
| D | Inspected local contract agrees with source evidence | Optional comparison, not a prerequisite for a source fact to be recorded. |
| E | Actual matching-scope, SHA-bound execution evidence | Required only for a local runtime-verified claim, not for archaeological progress. |

External gameplay tests have their own attribution and version/scope. They are positive evidence but are not automatically local-runtime E. A source-plus-public-model interpretation can be `cross_validated` while the native body is still unavailable and local execution remains untested.

A local gap is a **backend consumption note**, separate from source uncertainties and the research queue. Record its source anchor and inspected SHA if useful, then leave implementation ownership outside PR #8. Do not attach a repair card, merge dependency or runtime acceptance gate to the next archaeology step. If comparison challenges a source interpretation, reopen only that evidenced interpretation question; a missing local implementation by itself is not such a contradiction.

Local `engine_convention` remains a convention. Existing code is not native GameCore authority. Test-file existence is not execution, and `skipped != passed`; neither an absent E nor a skipped workflow makes a reviewed raw fact fail.

Generic scheduler, RNG, AI, callback-total-order and native formula bodies stay explicitly unresolved where the pinned artifact does not expose them. This does not freeze every observable rule in those domains. Use credible experiments and source discriminators for the behavior actually in question; do not repeatedly scan the same corpus to guess hidden bodies.

## Research status and evidence maturity

Use [BATTLE_RESEARCH_WORKLIST.md](BATTLE_RESEARCH_WORKLIST.md) for source/mechanism obligations and [SOURCE_FAMILY_INVENTORY.md](SOURCE_FAMILY_INVENTORY.md) for corpus triage. The worklist is not a backend execution queue or fixed denominator.

Research work statuses remain `candidate_new`, `active`, `blocked_evidence`, `mechanism_closed`, `deferred`, `retired_not_required` and `merged_into:<id>`, with their existing meanings. `blocked_evidence` refers to a named source/semantic evidence boundary, not an unimplemented local handler. A bounded record may retain a source-partial result when source obligations really remain; do not use that result to smuggle in implementation acceptance.

Individual evidence maturity remains `candidate -> manually_confirmed -> cross_validated -> runtime_verified`. Cross-validation and runtime validation must describe their actual supporting evidence. Not every useful research claim must reach the final maturity level.

A checked leaf covers only its exact statement. No completion percentage or global closure follows from representative examples, a repaired backend path, or accumulated R-number milestones.

## Required record contents

Every source record should state the gameplay concept/scope, public model/test provenance where relevant, exact revision/path/blob/occurrence, entity and binding identities, producer/reference/authored-consumer chain, interpreted equation or battle consequence, authority class/maturity, negative evidence, and unresolved source questions. Include version context, a useful numerical or behavioral discriminator, and whether any stated numbers are observations or predictions.

When local code is inspected, put its SHA, behavior, comparison and validation level in a separately labeled implementation note. Do not make such a note mandatory for every raw fact or turn its unresolved items into research blockers.

Source roles remain `battle_authoritative`, `battle_supporting`, `mixed_requires_filter`, `progression_only`, `presentation_only`, `editor_tooling`, `telemetry_only` and `unknown_unreviewed`. Explicit `export_gap` / `engine_consumer_unavailable` annotations refer to pinned source boundaries, not backend readiness or proof that no public behavior model exists.

## Version discipline

All raw authority uses the fixed TBGD revision. Default-branch or live data may aid navigation and comparison but cannot silently fill pinned gaps. Large-file search/read failures are not omission proof. A source occurrence and its semantic interpretation must remain distinguishable from normalized local representations and externally measured behavior.

Implementation observations are dated and SHA-bound. Old inspection or execution evidence is not a claim about every later master. This does not require continuously revalidating the backend before publishing source research.

## Durable records and navigation

Governance and research ledgers:

- [Foundation-first research roadmap and claim ledger](../../../../../docs/tbgd_evidence/shared/foundational_mechanics_research_roadmap_v1.md)
- [General parameters and effective properties: combat, not progression](../../../../../docs/tbgd_evidence/shared/general_parameter_effective_property_semantics_v1.md)
- [General damage formula and input layers](../../../../../docs/tbgd_evidence/shared/general_damage_formula_and_input_layers_v1.md)
- [General weakness, toughness, Break and Super Break](../../../../../docs/tbgd_evidence/shared/general_weakness_toughness_break_super_break_v1.md)
- [General effect application, resistance, immunity and attempts](../../../../../docs/tbgd_evidence/shared/general_effect_application_hit_resistance_immunity_v1.md)
- [General modifier identity, stacking, lifetime and removal](../../../../../docs/tbgd_evidence/shared/general_modifier_identity_stacking_lifetime_v1.md)
- [General Speed, Action Value, action categories and clocks](../../../../../docs/tbgd_evidence/shared/general_speed_action_value_turn_clock_v1.md)
- [General Energy, regeneration, Skill Points and capacity](../../../../../docs/tbgd_evidence/shared/general_energy_skill_point_economy_v1.md)
- [General healing, shields and HP resolution](../../../../../docs/tbgd_evidence/shared/general_healing_shield_hp_resolution_v1.md)
- [General target selection, expansion, aggro and source context](../../../../../docs/tbgd_evidence/shared/general_target_selection_expansion_source_context_v1.md)
- [General event, entity and encounter lifecycle](../../../../../docs/tbgd_evidence/shared/general_event_entity_encounter_lifecycle_v1.md)
- [BATTLE_SCOPE.md](BATTLE_SCOPE.md)
- [SOURCE_FAMILY_INVENTORY.md](SOURCE_FAMILY_INVENTORY.md)
- [BATTLE_RESEARCH_WORKLIST.md](BATTLE_RESEARCH_WORKLIST.md)
- [PINNED_SOURCE_INDEX.md](PINNED_SOURCE_INDEX.md) — navigation cache, not independent semantic authority.
- [EVIDENCE_RECORD_TEMPLATE.md](EVIDENCE_RECORD_TEMPLATE.md)
- [Scope-drift audit and correction](../../../../../docs/tbgd_evidence/shared/pr8_scope_drift_audit_2026-09-23.md)
- [Public mechanics models: healing/shield reconciliation](../../../../../docs/tbgd_evidence/shared/public_mechanics_healing_shield_reconciliation_v1.md)

Bounded source records; consult their claim-level limits rather than treating them as backend acceptance gates:

- [R0 battle execution language](../../../../../docs/tbgd_evidence/shared/battle_execution_language_core_v1.md)
- [R1 ordinary damage](../../../../../docs/tbgd_evidence/shared/ordinary_damage_vertical_slice_v1.md)
- [R2 weakness, toughness and Break](../../../../../docs/tbgd_evidence/shared/weakness_toughness_break_vertical_slice_v1.md)
- [R3 healing and modifier lifecycle](../../../../../docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md)
- [R4 resource economy](../../../../../docs/tbgd_evidence/shared/resource_economy_core_v1.md)
- [R5 battle-start build source construction](../../../../../docs/tbgd_evidence/shared/battle_start_build_construction_v1.md)
- [R6 encounter, spawn, phase and termination](../../../../../docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md)
- [R7 targeting and enemy decision boundary](../../../../../docs/tbgd_evidence/shared/action_targeting_enemy_decision_boundary_v1.md)
- [R8 startup-effect source chains](../../../../../docs/tbgd_evidence/shared/battle_start_effect_activation_v1.md)
- [R9 retained servant source facts and scope correction](../../../../../docs/tbgd_evidence/shared/owned_servant_runtime_admission_v1.md)
- [Guinaifen Burn: skill text, application, tick, extra trigger and Firekiss](../../../../../docs/tbgd_evidence/shared/guinaifen_burn_tick_detonation_source_chain_v1.md)
- [Guinaifen Burn follow-up: Firekiss timing, E2 coefficient and E4 attribution](../../../../../docs/tbgd_evidence/shared/guinaifen_burn_timing_eidolon_attribution_v1.md)

Representative and shared records:

- [March shield](../../../../../docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md)
- [Aglaea servant11402](../../../../../docs/tbgd_evidence/characters/aglaea_servant_11402_reference_chain.md)
- [Monster1002011](../../../../../docs/tbgd_evidence/monsters/monster_1002011_reference_chain.md)
- [LC20000](../../../../../docs/tbgd_evidence/equipment/light_cone_20000_arrows.md)
- [Stage wave sources](../../../../../docs/tbgd_evidence/stages/stage_config_wave_source.md)
- [Global/shared reverse scan](../../../../../docs/tbgd_evidence/shared/global_shared_reverse_scan.md)
- [RNG and callback source chains](../../../../../docs/tbgd_evidence/shared/ordinary_rng_callback_reference_chains.md)
- [OneMore and speed boundary](../../../../../docs/tbgd_evidence/shared/timeline_one_more_and_speed_boundary.md)
- [Initial March wiring](characters/march_7th_preservation_source_chain.md)

Historical integration/planning, not current task authorization:

- [Parallel integration](PARALLEL_INTEGRATION_2026-09-09.md)
- [Post-R4 compaction](POST_R4_RESEARCH_COMPACTION_2026-09-10.md)
- [Post-R5 compaction](POST_R5_RESEARCH_COMPACTION_2026-09-11.md)

R6's retained implementation validation remains limited to the recorded tested SHA `70eabfe4a94ec458eacdd4bf324d9a8889743c49` and its selected materialization/wave-fixture/rejection/catalog scope. It does not prove complete battles, confer E on R7-R9, or establish a repair prerequisite for this ledger.

## Publication boundary

Keep PR #8 open/Draft and docs/evidence-only. Do not modify runtime, lowering, IR, tests, CI or the TBGD pin. A checkpoint reports new source/model knowledge, exact anchors, remaining uncertainties, affected documents and separately scoped public or runtime verification. It must not become a backend repair/merge handoff.
