# Foundation-first battle mechanics research roadmap v1

## Current checkpoint — F08, 2026-09-24

[F08: general Speed, Action Value, action categories and clocks][TIMING] is now delivered as a first shared-rule/source map. It supplies the ordinary gauge/AV and remaining-time rescale model; distinguishes full-interval advance from scaling the remaining timer; and maps speed mutation, a typed relic advance and absolute zeroing to different raw operations. Normal, extra and inserted actions are separated from duration clocks. F08/W07/W10 remain active for precise unit-transport, clamp/ordering, exceptional action-slot and clock questions; no whole-package completion or runtime E is claimed.

[F06][MODIFIERS]'s identity, stacking, timer and cleanup results remain established, alongside [F05][APPLICATION]'s admission rules and [F03][BREAK]'s units/formula families. The next primary target is **F07: shared resource economy**, using the timing distinctions to explain Energy/Skill Point generation, cost, regeneration and availability without equating every action with a natural turn. F04's shared healing/shield questions remain queued; no backend repair or native-code recovery is a prerequisite.

## 1. Current direction

Originally reviewed 2026-09-23, at evidence parent `2100d31cbfb3425907ccacfedb564265f764768c`; F03 updated 2026-09-24 from parent `21c3d13a47d36dea57a25aa82b0915f4e6c4f3ea`; F05 continued from `d1ff8c9dd8df90eefd7134f7374b1faee78c5ace`; F06 continued from `b1b1db9fabb04926dd2669e44d93c830fd784397`; F08 continued from `96896f677eaf14eaaa0b7692289801f69b4fcb8c`. The owner requested general, low-level combat research before filling individual character kits. This document makes that the current research priority for PR #8.

The research object is a reusable mechanic, not a character. A character, monster, equipment effect or stage may be inspected only as a concrete producer, a contrasting case or a counterexample needed to explain that mechanic. Completing an actor's remaining Eidolons or kit details is not the default next task.

The objective remains the pinned game database's combat facts and supported gameplay semantics, usable by later backend work. This is not backend acceptance, not a runtime refactor and not a return to the withdrawn R9 repair workflow. PR #8 stays Draft and docs/evidence-only; TBGD remains `14c1d18f91a8101d610e6c523447a7517de3fae1`.

## 2. Relationship to existing ledgers

The [living W worklist][WORKLIST] remains the mechanism-obligation ledger; [BATTLE_SCOPE][SCOPE] still owns inclusion, exclusions and corpus completeness. This roadmap is a priority and claim-level overlay, not a replacement taxonomy or completion percentage.

Existing R0-R8 and later public-model/skill-text records are reusable evidence, not work to repeat. Old Next closure lines and R-number serial sequences do not override the direction here. The original broad checkboxes are not promoted merely because one new general model or one actor example exists.

For explicitly covered ordinary damage formulas, [the general damage record][DAMAGE] supersedes the old R1 blanket restriction on public mathematics. Exact old source identities, omissions and special-case uncertainties survive. The historical A/B/C/D labels inside R1 section 11 predate the later independent axes; read their local definitions rather than treating them as the current global A/B/C/D/E matrix.

For explicitly covered toughness/Break rules, [F03][BREAK] likewise supersedes R2's blanket unknown-mechanics wording while retaining its actual `1659254037` input-injection gap. Published/declared behavior and an unidentified native transport edge can coexist without turning the former back into an unknown.

For the covered application rules, [F05][APPLICATION] supersedes the old RNG record's native-evaluator-only stopping rule. Known probability mathematics does not reveal the PRNG, immunity-charge arbitration or every category override; those precise residuals stay separate. Public wording is labeled as such when a same-pin localization join was not completed.

For the lifecycle rules it actually covers, [F06][MODIFIERS] likewise supplies observable update and clock semantics without claiming the complete native matching/dispatcher implementation. Stacking policy tokens remain literal source facts, not substitutes for the accompanying layer, duration, payload and ownership rules.

For the ordinary timing claims it covers, [F08][TIMING] supersedes W07 and the older timeline record's native-body-only freeze. The raw `SpeedToDelayDistance=1000` is not rewritten to the public normalization10000. Initial-order models, explicit delay operations and unknown mixed-insertion arbitration remain separately attributed.

## 3. Reusable deliverable for each foundation

Each foundation record should answer:

1. **What happens?** State the equation, rule or state transition in usable terms, with actor/source/owner/recipient identities and applicability.
2. **Where is it expressed?** Map exact pinned table/description/parameter/graph/shared-definition inputs to the rule. A native function body is not the required endpoint.
3. **Why accept the interpretation?** Use linked skill/effect descriptions, exact source operations, original community testing and attributed public formulas. Distinguish common ancestry from independent evidence.
4. **What varies?** Enumerate the relevant formula families, branches and exceptions; explain which operands or conditions select them.
5. **How can alternatives be distinguished?** Supply a controlled numerical or behavioral discriminator, labeling predictions versus measurements.
6. **What is still unknown?** Name the particular unresolved quantity, source edge or behavior. Do not replace an established general equation with a blanket unknown.

Do not make a source fact wait for a local handler, passing runtime test, implementation PR or native-code export. Local implementation comparison remains optional and separately attributed.

## 4. Foundation map and priority

The order is an initial dependency-informed route, not a claim that the game has exactly ten mechanisms. A newly discovered foundational branch changes this map rather than being hidden inside a character-specific record.

| ID | General research unit | W obligations / existing anchors | Deliverable and current position |
| --- | --- | --- | --- |
| F01 | Parameter and property semantics | W01/W02/W03; R0, R5, current healing/shield reconciliation | Family-qualified parameters, description placeholders, dynamic environments, base/flat/ratio/current/effective values and source ownership. Existing material is reusable; unify remaining shared rules rather than rebuild another full character panel. |
| F02 | Ordinary damage layers and damage-kind routing | W04; R1, shared constants/behavior templates, R8 | Active; first general formula/input-layer record delivered 2026-09-23. Retain named caps/overrides/rounding/transition-hit questions. Do not mark all damage complete. |
| F03 | Weakness, toughness, Break and Super Break | W06/W14; R2 and shared templates | **Active; first shared-rule map delivered 2026-09-24.** Units, level table, initial/seven-element/Super Break bases and applicability are recorded. Remaining injection, accumulator/threshold, special-bar and state-sampling questions are explicit. |
| F04 | Healing, shielding and damage-to-HP interfaces | W05; R3, March and public-model reconciliation | General scale/flat/healing-bonus roles, shield creation versus mitigation/consumption, overflow and explicit special formulas. Preserve already recovered equations; investigate shared residuals, not another isolated healer. |
| F05 | Effect application, immunity and random-choice classes | W09/W12; ordinary RNG/callback record and F03 application inputs | **Active; first shared-rule map delivered 2026-09-24.** Base/fixed probability, EHR/general/category resistance, shared immunity and consumed protection, actual attempt count and conditional repeated-attempt model. Exact override/charge/context questions remain open. |
| F06 | Modifier instances and lifetime | W09/W10; R3, shared modifiers and F05 admission/consumption boundary | **Active; first shared-rule map delivered 2026-09-24.** Identity, layer/cap-refresh, lifetime addition, caster-timed parent/recipient children and cleanup are mapped. Matching/update precedence, clock exceptions and exact sampling remain named residuals. |
| F07 | Shared resource economy | W08; R4, linked skill descriptions and F08 action/clock distinctions | **Next primary research target.** Energy versus team Skill Points, initial/max values, gain/cost/regen, recipient and timing rules, with character gauges as later extensions. A raw SP name alone does not identify the public resource. |
| F08 | Time, turn and action categories | W07/W10; OneMore/timeline source record and F06 clock distinctions | **Active; first shared-rule map delivered 2026-09-24.** Ordinary SPD/AV, rescaling, full-gauge advance/delay, absolute zero and action/clock distinctions are mapped. Exact unit transport, exceptional scheduling and first-step rules remain named questions. |
| F09 | Target and damage-source context | W11/W15; R7 and general source/frame evidence | Explicit/automatic targets, adjacency, internal traversal, retargeting, target validity, original/current target and caster/actual damage owner. AI policy need not be implemented to document its source constraints. |
| F10 | Event, entity and encounter lifecycle | W10/W13/W16/W17; R6 and retained servant/source records | Registration versus triggering, supported local causal order, death/limbo/revive, secondary-entity ownership, spawn/wave/phase/termination. Source facts and actual observable events, not Python admission readiness. |

F01 facts are prerequisites reused as other foundations proceed; this does not require an artificial complete-every-property preflight. F04, F07 and F09-F10 retain their pending general obligations, not results claimed by F08. The first-pass order may be adjusted for a concrete missing foundational dependency; changes must explain the mechanism reason rather than follow an actor's remaining kit.

## 5. Current F02 claim ledger

These leaves refer only to [General damage v1][DAMAGE]. Checked statements do not mean W04 or F02 as a whole is complete.

- [x] Express an attributed ordinary damage factor model with distinct coefficient/stat, crit, outgoing bonus, DEF, RES, vulnerability, reduction and Weaken roles.
- [x] Reconcile the general DEF equation's 200/10 with exact pinned shared constants, preserving the limited assumptions of the level-only simplification.
- [x] Separate additive DEF reduction/ignore in the stated ordinary case from their different ownership and storage roles.
- [x] Trace common monster reduction installation -> AllDamageReduce0.1 -> break removal -> recovery restoration; prevent counting it twice as toughness and generic reduction.
- [x] Preserve damage-type resistance, status resistance and weakness membership as different inputs.
- [x] Map known status-property versus hit-context contribution surfaces without claiming their same-hit visibility is universal.
- [x] Distinguish ordinary damage from explicit DirectlyLoseHp/behavior overrides; retain the literal flags instead of deducing all arithmetic from a template name.
- [ ] Close exact resistance/damage-taken/reduction boundary quantities and clamp stages at the pin.
- [ ] Complete mixed-scaling, fixed/pure, special damage and crit-override applicability where not covered by the ordinary model.
- [ ] Resolve transition-hit, per-hit/aggregate rounding and relevant context-sampling discriminators with suitable evidence.

These remaining questions stay active and searchable, but do not erase the known interior-range rules. They do not require a runtime repair before other foundations can be investigated.

## 6. F03 shared-rule result and remaining research

The original F03 frame was to start from public behavior of ordinary toughness depletion, Weakness Break and Super Break, then reconcile it with existing R2 evidence. [F03 v1][BREAK] now applies that frame to shared Stance/Break fields, elemental templates, formula families and common state transitions.

- [x] Separate HP damage, toughness reduction, maximum toughness, Break Effect and Weakness Break Efficiency.
- [x] Reconcile 30 old / 10 displayed toughness units while retaining the specific loader-to-hash gap.
- [x] Locate the pinned Level -> BreakBaseDamage table, preserving Level80=3767.5535 instead of copying a rounded/different public value.
- [x] Map ordinary initial Break's elemental and maximum-toughness factors to the shared expressions and attributed gameplay model.
- [x] Trace all seven common elemental installers; distinguish physical capped HP scaling, wind layers, ordinary Break DOT and delayed Pursued damage.
- [x] Separate fixed common break delay from Break-Effect-scaled Quantum/Imaginary delay and the independent speed contribution.
- [x] Read shared Super Break's literal /30, target accumulator versus explicit-input branch, positive-Q guard and distinct context roles.
- [x] Preserve separate initial Break, extra status activation, explicit Break proc and Super Break semantics, with calculation-only discriminators.
- [ ] Resolve remaining input-injection and context-assignment edges without inventing raw values.
- [ ] Resolve threshold-crossing/multi-hit accumulator allocation, reset and multiple-source invocation where a concrete source/test can discriminate them.
- [ ] Map special toughness bars, locks, alternate eligibility and explicit caps beyond the ordinary shared model.
- [ ] Reconcile relevant snapshot/refresh/control/rounding interactions with narrow observable evidence.

A published or measured amount can establish observable units even while a particular loader-to-hash transport remains unidentified. The F03 record keeps these assertions separate instead of declaring either one proven by the other. No whole-character completion, equip recommendation or backend implementation belongs in this task.

## 6A. F05 shared-rule result and remaining research

[F05 v1][APPLICATION] starts from the requested effect and its probability class, then maps its inputs, category and protection state. Public descriptions and formulas are positive evidence, not substitutes for pinned numeric fields or proof of a native function body.

- [x] State the ordinary base-chance product and inverse EHR threshold, with source/recipient roles, valid-range assumptions and explicit probability-domain limits.
- [x] Explain why base100% is not final100%, why a base1.5 input is not clipped before the other ordinary factors, and why a numeric example is not a new Break-status measurement.
- [x] Distinguish a fixed proc, randomized candidate traversal and a base-chance status request through separate exact Yanqing operations and typed input slots.
- [x] Prove the selected inserted body's two damage operations contain only one explicit Freeze application request; do not count visual or damage hits as rolls.
- [x] Trace a control-category StackStatusResistance contribution separately from StatusResistanceBase writes and reject direct addition of general and category resistance.
- [x] Read shared behavior-flag and status-type immunity maps, preserving actual owner/activation requirements and named override boundaries.
- [x] Trace one-use protection installation, ImmuneDebuff classification, OnImmuneDebuff self-removal and parent-state cleanup without inventing a Count field or cleanse operation.
- [x] Give the conditional independent-attempt equation and reproduce a published calculation table without labeling it gameplay testing.
- [ ] Resolve overlapping category aggregation, AntiDebuffResist/forced-status numeric behavior and fixed-debuff override applicability where concretely needed.
- [ ] Resolve immunity-charge versus resistance-check ordering, simultaneous requests and overlapping protection consumption.
- [ ] Resolve application-source/snapshot selection and state-dependent or multiple-source attempt allocation beyond the selected examples.
- [ ] Corroborate any special elemental Break probability exceptions separately from the ordinary base-chance model.

## 6B. F06 shared-rule result and remaining research

[F06 v1][MODIFIERS] follows the former F06 frame: creation/update, caster/holder, identity versus display label, initial versus remaining duration, periodic versus extra activation, and explicit removal versus expiry/cleanup. It reuses the admitted/immune distinction rather than repeating F05 or expanding a sample kit.

- [x] Distinguish definition/source/holder, layers/caps, remaining lifetime, charges, payload sampling and exit dependencies as separate evidence dimensions, without claiming a native instance-key tuple.
- [x] Keep ordinary and Break Wind Shear as distinct definitions/formula families even when they share a category and can coexist.
- [x] Join the selected stackable Poison installer to its typed chance/lifetime/cap/coefficient inputs and shared layer consumer; use attributed reapplication behavior to explain cap-refresh without a sixth layer.
- [x] Trace an actual SetModifierValueByBehaviorFlag(Add,LifeTime) operation; distinguish existing-duration addition from refreshing or reapplying a state.
- [x] Trace a caster-timed parent distributing recipient-side children, late eligible-member installation, and named parent cleanup; absence of a child timer does not imply an eternal independent buff.
- [x] Preserve natural periodic and extra-activation clocks, alongside specifically attributed first-turn exceptions rather than a universal decrement-after-every-action rule.
- [x] Separate duration changes, installed payloads and property-read/sampling sites; label the ordinary dynamic-DoT explanation as an attributed model, not a new controlled test.
- [x] Distinguish dispellability, dispel requests, named/self removal, parent-dependent cleanup, property contribution withdrawal and visual removal.
- [ ] Resolve complete same-template source matching and StackingFlag precedence when concrete overlap cases require it.
- [ ] Resolve stronger/weaker payload, already-extended-timer and per-layer independent-expiry variants beyond the selected ordinary model.
- [ ] Resolve first eligible lifetime step, extra-action/control exceptions and same-time decrement/reapplication arbitration.
- [ ] Reconcile exact property sampling/refresh by effect family and overlapping contribution-removal visibility.

The checked leaves cover selected reusable rules and counterexamples, not a complete modifier corpus or W09 mechanism_closed. New source operations and credible public behavior evidence can advance the remaining questions; no backend repair or native dispatcher dump is required first.

## 6C. F08 shared-rule result and remaining research

[F08 v1][TIMING] follows the previous timing frame while preserving the actual scope of the prior OneMore/lifecycle records. Supported public mathematics is positive knowledge; exact raw constants, operations and unpublished native transport remain separate evidence claims.

- [x] State the ordinary positive-speed full-gauge/remaining-AV model and distinguish flat from percentage Speed.
- [x] Derive remaining-AV rescaling from unchanged remaining distance rather than resetting progress after a Speed mutation.
- [x] Distinguish full-gauge advance/delay from proportional reduction of remaining AV, with lower-bound and sequential-operation discriminators.
- [x] Trace Asta's typed flat-Speed/lifetime inputs and a separate preshow surface without inventing an explicit scheduler-rescale call.
- [x] Trace exact Set110 four-piece0.25 -> SkillRelic -> post-Ultra negative normalized delay; distinguish the typed Equip file from its differently serialized root sibling.
- [x] Trace the selected immediate allied-action branch to SetActionDelay0, retaining its actual ByIsTurnActionEntity predicate.
- [x] Separate normal, advanced-normal, extra, Ultimate, inserted and coordinated entries from damage/hit categories and duration-driving events.
- [x] Reuse OneMore's own action-bound lifetime and F06's clock ownership to reject a universal decrement/reset hook after every action.
- [x] Record the attributed ordinary initial-deployment tie model without claiming a native stable-sort implementation or universal mixed-insert order.
- [ ] Resolve the native/display unit transport for SpeedToDelayDistance and exact internal precision/boundary handling.
- [ ] Resolve same-time Speed/advance/clamp ordering, oversized-delay full advances, ready ties and pending-insert arbitration for concrete cases.
- [ ] Resolve exceptional speed/turn locks, action-slot renewal and coordinated/new-entity slot accounting.
- [ ] Complete first-eligible-step/control exceptions and the event-to-clock matrix beyond the selected rules.

### F07 next research frame

Explain shared Energy and team Skill Points as different resources: initial/max values, gain/cost, regeneration modifiers, recipient/source roles, availability and their actual triggering events. Reuse R4 and mechanically meaningful descriptions; use the F08 distinction between elapsed time, natural turns and skill execution to avoid invented per-turn resource rules. Character-exclusive gauges are contrasts only when they reveal a new primitive. F04 remains queued and F07 has not been executed by this checkpoint.

## 7. What counts as finishing the foundation pass

The pass is ready to support systematic actor completion when each known in-scope foundational family has a reusable rule/source map, applicability boundaries, representative positive and negative distinctions, and an explicit inventory of unresolved behavioral or export questions. Unknown foundational classes cannot be silently omitted.

This is not a requirement to prove the hidden engine's entire implementation or solve every extreme exception before any other research can move. A materially unknown common behavior remains open; a merely missing native body does not invalidate an independently established model. Unresolved source families remain in the completeness ledger.

Only then should the default activity become actor/equipment completion: instantiate the established common rules with their particular parameters, targets, conditions and lifecycle, and route genuinely new primitives back into the foundation records. Do not duplicate a general formula in every character record as if it were independently discovered.

## 8. Publication and history

The 2026-09-23 checkpoint added this roadmap and general damage. The 2026-09-24 continuations added F03, F05, F06 and now F08, with corresponding roadmap/README updates. The existing W worklist, older source records, scope, inventory and pin are preserved; claim-level results do not silently check package-wide obligations. Prior roadmap content remains auditable at evidence parents `21c3d13a47d36dea57a25aa82b0915f4e6c4f3ea`, `d1ff8c9dd8df90eefd7134f7374b1faee78c5ace`, `b1b1db9fabb04926dd2669e44d93c830fd784397` and `96896f677eaf14eaaa0b7692289801f69b4fcb8c`.

No runtime, lowering, IR, tests, CI or backend task is changed. Existing public reports and calculations are not claimed as new gameplay runs. The PR checkpoint records the actual final evidence head and Markdown-only diff. Stop this checkpoint after publication; F07 is the next mechanism priority, not another character follow-up or R9A repair.

[WORKLIST]: ../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_RESEARCH_WORKLIST.md
[SCOPE]: ../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_SCOPE.md
[DAMAGE]: general_damage_formula_and_input_layers_v1.md
[BREAK]: general_weakness_toughness_break_super_break_v1.md
[APPLICATION]: general_effect_application_hit_resistance_immunity_v1.md
[MODIFIERS]: general_modifier_identity_stacking_lifetime_v1.md
[TIMING]: general_speed_action_value_turn_clock_v1.md
