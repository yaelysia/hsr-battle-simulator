# Foundation-first battle mechanics research roadmap v1

## Current checkpoint — 2026-09-24

[F03: general weakness, toughness, Weakness Break and Super Break][BREAK] is now delivered as a first shared-rule/source map. It separates observable mechanics from unresolved context injection, identifies the exact level table, reconciles toughness units, maps seven elemental branches, and reads the shared Super Break denominator/accumulator-input contract. F03/W06 remain active for the explicit residuals; no whole-package completion or runtime E is claimed.

The next primary target is **F05: effect application, resistance and immunity**, because F03's shared Chance1.5 requests leave a high-impact common distinction between a declared status and its successful application. This is a mechanism dependency, not continuation of an actor's kit. F04 and F06 remain queued with their existing results retained. The older F03-next wording is superseded by this dated checkpoint; no backend repair or native-code recovery is a prerequisite.

## 1. Current direction

Originally reviewed 2026-09-23, at evidence parent `2100d31cbfb3425907ccacfedb564265f764768c`; updated 2026-09-24 from parent `21c3d13a47d36dea57a25aa82b0915f4e6c4f3ea`. The owner requested general, low-level combat research before filling individual character kits. This document makes that the current research priority for PR #8.

The research object is a reusable mechanic, not a character. A character, monster, equipment effect or stage may be inspected only as a concrete producer, a contrasting case or a counterexample needed to explain that mechanic. Completing an actor's remaining Eidolons or kit details is not the default next task.

The objective remains the pinned game database's combat facts and supported gameplay semantics, usable by later backend work. This is not backend acceptance, not a runtime refactor and not a return to the withdrawn R9 repair workflow. PR #8 stays Draft and docs/evidence-only; TBGD remains `14c1d18f91a8101d610e6c523447a7517de3fae1`.

## 2. Relationship to existing ledgers

The [living W worklist][WORKLIST] remains the mechanism-obligation ledger; [BATTLE_SCOPE][SCOPE] still owns inclusion, exclusions and corpus completeness. This roadmap is a priority and claim-level overlay, not a replacement taxonomy or completion percentage.

Existing R0-R8 and later public-model/skill-text records are reusable evidence, not work to repeat. Old Next closure lines and R-number serial sequences do not override the direction here. The original broad checkboxes are not promoted merely because one new general model or one actor example exists.

For explicitly covered ordinary damage formulas, [the general damage record][DAMAGE] supersedes the old R1 blanket restriction on public mathematics. Exact old source identities, omissions and special-case uncertainties survive. The historical A/B/C/D labels inside R1 section 11 predate the later independent axes; read their local definitions rather than treating them as the current global A/B/C/D/E matrix.

For explicitly covered toughness/Break rules, [F03][BREAK] likewise supersedes R2's blanket unknown-mechanics wording while retaining its actual `1659254037` input-injection gap. Published/declared behavior and an unidentified native transport edge can coexist without turning the former back into an unknown.

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
| F05 | Effect application, immunity and random-choice classes | W09/W12; ordinary RNG/callback record and F03 application inputs | **Next primary research target.** Base versus fixed chance, effect hit/RES/category RES, immunity, independent attempts; separate status checks, weighted branches, targets and random values. Use known probability models; do not require PRNG implementation recovery. |
| F06 | Modifier instances and lifetime | W09/W10; R3 and shared modifiers | Owner/caster identity, stacks and caps, refresh/replace/extend, periodic versus extra activation, snapshot/live inputs, dispel/removal and property rollback. Named source policies require observable semantics, not just a token inventory. |
| F07 | Shared resource economy | W08; R4 and linked skill descriptions | Energy versus team Skill Points, initial/max values, gain/cost/regen, recipient and timing rules, with character gauges as later extensions. A raw SP name alone does not identify the public resource. |
| F08 | Time, turn and action categories | W07/W10; OneMore/timeline source record | SPD/AV, advance/delay, natural versus extra/insert/follow-up actions, action start/end and duration-driving events. Adopt supported public timing models while keeping exact unsupported tie-breaks separate. |
| F09 | Target and damage-source context | W11/W15; R7 and general source/frame evidence | Explicit/automatic targets, adjacency, internal traversal, retargeting, target validity, original/current target and caster/actual damage owner. AI policy need not be implemented to document its source constraints. |
| F10 | Event, entity and encounter lifecycle | W10/W13/W16/W17; R6 and retained servant/source records | Registration versus triggering, supported local causal order, death/limbo/revive, secondary-entity ownership, spawn/wave/phase/termination. Source facts and actual observable events, not Python admission readiness. |

F01 facts are prerequisites reused while F02/F03 proceed; this does not require an artificial complete-every-property preflight. F04-F10 are scheduled research, not results claimed by this checkpoint. The first-pass order may be adjusted for a concrete missing foundational dependency; changes must explain the mechanism reason rather than follow an actor's remaining kit.

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

### F05 next research frame

Use the shared application request as the starting point: what does a base probability mean, which actor supplies hit rate, which target supplies general/category resistance, and when is an effect immune rather than merely unlikely? Distinguish fixed probability and separate independent attempts. Public probability formulas and skill text are positive inputs; exact raw Chance/property/flag/binding surfaces explain applicability.

Keep application probability distinct from RandomConfig branch choice, random target traversal and random scalar generation. A known observable probability model does not require recovering the PRNG stream or native evaluator code. F03's elemental Chance1.5 is one generic discriminator; do not turn it into a single-character gearing exercise. F05 has not been executed by this checkpoint.

## 7. What counts as finishing the foundation pass

The pass is ready to support systematic actor completion when each known in-scope foundational family has a reusable rule/source map, applicability boundaries, representative positive and negative distinctions, and an explicit inventory of unresolved behavioral or export questions. Unknown foundational classes cannot be silently omitted.

This is not a requirement to prove the hidden engine's entire implementation or solve every extreme exception before any other research can move. A materially unknown common behavior remains open; a merely missing native body does not invalidate an independently established model. Unresolved source families remain in the completeness ledger.

Only then should the default activity become actor/equipment completion: instantiate the established common rules with their particular parameters, targets, conditions and lifecycle, and route genuinely new primitives back into the foundation records. Do not duplicate a general formula in every character record as if it were independently discovered.

## 8. Publication and history

The 2026-09-23 checkpoint added this roadmap and general damage. The 2026-09-24 continuation adds F03's shared-rule record and updates this roadmap/README. The existing W worklist, older source records, scope, inventory and pin are preserved; claim-level results do not silently check package-wide obligations. Prior roadmap content remains auditable at evidence parent `21c3d13a47d36dea57a25aa82b0915f4e6c4f3ea`.

No runtime, lowering, IR, tests, CI or backend task is changed. Existing public reports and calculations are not claimed as new gameplay runs. The PR checkpoint records the actual final evidence head and Markdown-only diff. Stop this checkpoint after publication; F05 is the next mechanism priority, not another character follow-up or R9A repair.

[WORKLIST]: ../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_RESEARCH_WORKLIST.md
[SCOPE]: ../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_SCOPE.md
[DAMAGE]: general_damage_formula_and_input_layers_v1.md
[BREAK]: general_weakness_toughness_break_super_break_v1.md
