# Foundation-first battle mechanics research roadmap v1

## 1. Current direction

Reviewed 2026-09-23, at evidence parent `2100d31cbfb3425907ccacfedb564265f764768c`. The owner requested general, low-level combat research before filling individual character kits. This document makes that the current research priority for PR #8.

The research object is a reusable mechanic, not a character. A character, monster, equipment effect or stage may be inspected only as a concrete producer, a contrasting case or a counterexample needed to explain that mechanic. Completing an actor's remaining Eidolons or kit details is not the default next task.

The objective remains the pinned game database's combat facts and supported gameplay semantics, usable by later backend work. This is not backend acceptance, not a runtime refactor and not a return to the withdrawn R9 repair workflow. PR #8 stays Draft and docs/evidence-only; TBGD remains `14c1d18f91a8101d610e6c523447a7517de3fae1`.

## 2. Relationship to existing ledgers

The [living W worklist][WORKLIST] remains the mechanism-obligation ledger; [BATTLE_SCOPE][SCOPE] still owns inclusion, exclusions and corpus completeness. This roadmap is a priority and claim-level overlay, not a replacement taxonomy or completion percentage.

Existing R0-R8 and later public-model/skill-text records are reusable evidence, not work to repeat. Old Next closure lines and R-number serial sequences do not override the direction here. The original broad checkboxes are not promoted merely because one new general model or one actor example exists.

For explicitly covered ordinary damage formulas, [the general damage record][DAMAGE] supersedes the old R1 blanket restriction on public mathematics. Exact old source identities, omissions and special-case uncertainties survive. The historical A/B/C/D labels inside R1 section 11 predate the later independent axes; read their local definitions rather than treating them as the current global A/B/C/D/E matrix.

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
| F02 | Ordinary damage layers and damage-kind routing | W04; R1, shared constants/behavior templates, R8 | **Active; first general formula/input-layer record delivered in this checkpoint.** Retain named caps/overrides/rounding/transition-hit questions. Do not mark all damage complete. |
| F03 | Weakness, toughness, Break and Super Break | W06/W14; R2 and shared templates | Separate damage resistance from weakness; explain toughness units, reduction, break/recovery, ordinary versus Break DoT and Super Break bases. **Next primary research target after this checkpoint**, using public formulas and declared skill toughness to reconcile existing raw surfaces. Do not restart whole-actor studies. |
| F04 | Healing, shielding and damage-to-HP interfaces | W05; R3, March and public-model reconciliation | General scale/flat/healing-bonus roles, shield creation versus mitigation/consumption, overflow and explicit special formulas. Preserve already recovered equations; investigate shared residuals, not another isolated healer. |
| F05 | Effect application, immunity and random-choice classes | W09/W12; ordinary RNG/callback record | Base versus fixed chance, effect hit/RES/category RES, immunity, independent attempts; separate status checks, weighted branches, targets and random values. Use known probability models; do not require PRNG implementation recovery. |
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

These remaining questions stay active and searchable, but do not erase the known interior-range rules. They do not require a runtime repair before F03 can be investigated.

## 6. F03 next research frame

Start from the public behavior of ordinary toughness depletion, Weakness Break and Super Break, then reconcile it with existing R2 evidence. The primary objects are shared Stance/Break fields, elemental templates, formula families and common state transitions.

The required distinctions include HP damage versus toughness damage; raw/displayed toughness units; weakness membership versus damage RES; the breaking source versus affected target; initial Break damage versus applied Break DoT; and repeated Super Break damage versus the one-time break transition. Reuse the existing typed Stance producer and exact display/consumer observations.

A published or measured basic-attack toughness amount may establish the observable amount/unit conversion even while a particular loader-to-hash transport remains unidentified. Do not falsely claim that the loader edge is found, and do not therefore label the observable value unknown. Follow the same separation for known Break equations and native evaluator code.

A sample is justified only by the discriminator it supplies: an ordinary direct hit, a different element, an explicit special toughness operation or a Super Break caller. No whole-character completion, equip recommendation or backend implementation belongs in this task. This checkpoint does not claim F03 has already been executed.

## 7. What counts as finishing the foundation pass

The pass is ready to support systematic actor completion when each known in-scope foundational family has a reusable rule/source map, applicability boundaries, representative positive and negative distinctions, and an explicit inventory of unresolved behavioral or export questions. Unknown foundational classes cannot be silently omitted.

This is not a requirement to prove the hidden engine's entire implementation or solve every extreme exception before any other research can move. A materially unknown common behavior remains open; a merely missing native body does not invalidate an independently established model. Unresolved source families remain in the completeness ledger.

Only then should the default activity become actor/equipment completion: instantiate the established common rules with their particular parameters, targets, conditions and lifecycle, and route genuinely new primitives back into the foundation records. Do not duplicate a general formula in every character record as if it were independently discovered.

## 8. Publication and history

This roadmap and the general damage record are new evidence documents. README links them as the current priority. The existing W worklist, older source records, scope, inventory and pin are preserved; this overlay supplies the current F02 claim ledger without silently checking old package-wide obligations.

No runtime, lowering, IR, tests, CI or backend task is changed. Existing public reports and calculations are not claimed as new gameplay runs. The PR checkpoint records the actual final evidence head and Markdown-only diff. Stop this checkpoint after publication; the next research target is the F03 mechanism above, not another Guinaifen follow-up or R9A repair.

[WORKLIST]: ../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_RESEARCH_WORKLIST.md
[SCOPE]: ../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_SCOPE.md
[DAMAGE]: general_damage_formula_and_input_layers_v1.md
