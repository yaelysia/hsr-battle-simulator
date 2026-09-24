# Foundation-first battle mechanics research roadmap v1

## Current checkpoint — F01, 2026-09-24

[F01: general parameters and effective properties][PARAMETERS] is now delivered as a first shared-rule/source map. It separates completed-build combat inputs from progression costs and prerequisites, typed parameter/level/index routing from working values, ordinary base/ratio/flat composition from capped cross-entity grants, and conversion-sensitive inputs from flattened displayed totals. Actual property reads and writes override misleading variable or modifier names. F01/W01/W02/W03 remain active for precise resolution, conversion/sampling, override and coverage questions; no whole-package completion or runtime E is claimed.

The owner's explicit clarification is retained: research combat consequences of the selected finished build, not acquisition, leveling, ascension, unlock economy or relic roll history. Classify mixed tables below file level using actual consumers. The next primary task is an **integrated foundation-gap and coverage review** across F01-F10, the W worklist and source-family scope. All ten first-pass records now exist, but that does not certify foundational completeness or authorize default character completion. No backend admission or repair sequence is introduced.

## 1. Current direction

Originally reviewed 2026-09-23, at evidence parent `2100d31cbfb3425907ccacfedb564265f764768c`; F03 updated 2026-09-24 from parent `21c3d13a47d36dea57a25aa82b0915f4e6c4f3ea`; F05 continued from `d1ff8c9dd8df90eefd7134f7374b1faee78c5ace`; F06 continued from `b1b1db9fabb04926dd2669e44d93c830fd784397`; F08 continued from `96896f677eaf14eaaa0b7692289801f69b4fcb8c`; F07 continued from `e392081bd2c016ca686923b2e619d0a2564510d2`; F04 continued from `1a814ca21efc28e0af9aaac7a1e7220eff29938e`; F09 continued from `2718b77036a7085f67fd66814af2268ea3882f8d`; F10 continued from `adc555818592fd62556d4fc93d8be1bd020e79ea`; F01 continued from `98bc2a3db82756519816c7c577f274821cc68ba4`. The owner requested general, low-level combat research before filling individual character kits. This document makes that the current research priority for PR #8.

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

For the resource claims it covers, [F07][RESOURCES] supersedes R4's blanket withholding of public resource names and arithmetic. The selected SPBase/AddRatio interpretation, fixed grants and team-pool models do not claim recovery of mixed-operand evaluators, initial Energy policies or transaction ordering. A field name or rounded UI amount remains insufficient on its own.

[F04][SUSTAIN] extends the earlier healing/shield reconciliation rather than reopening its base equations. Raw ownership, original reported tests and public descriptions support the covered sustain rules while exact callback payloads, changed-cap sampling and overlapping shield arbitration remain separately scoped.

[F09][TARGETS] reuses R7's target-layer vocabulary without adopting local compiler defaults as native rules. Its source register records the Asta/shared-template cached-anchor discrepancy and supplies actual reread blobs. Supported aggro, effect-target and ownership models remain distinct from unknown enemy policies and opaque selector execution.

[F10][LIFECYCLE] reuses R6, W10 and the servant death/entry surfaces without their former backend gates. Known staged recovery is explicitly a reused finding; new eligibility, reactivation, execution-recheck and quota-scope distinctions are joined to descriptions. A missing total-order implementation does not erase these local causal edges or the stage's actual result/leave routes.

[F01][PARAMETERS] synthesizes R0/R5 without treating their local loader/affix arithmetic as newly proven native behavior. Public base-to-effective stat equations are a different claim from the selected base-value loader. Finished-build selectors, combat skill-level increments and activated effects remain distinct from excluded costs/prerequisites; field names alone do not establish either inclusion or algebra.

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
| F01 | Parameter and property semantics | W01/W02/W03; R0, R5, current healing/shield reconciliation and F02-F10 | **Active; first shared-rule map delivered 2026-09-24.** Combat/progression field separation, qualified parameters, base/ratio/flat composition, capped grants and conversion-sensitive sampling are mapped. Resolution, overrides and coverage remain explicit. |
| F02 | Ordinary damage layers and damage-kind routing | W04; R1, shared constants/behavior templates, R8 | Active; first general formula/input-layer record delivered 2026-09-23. Retain named caps/overrides/rounding/transition-hit questions. Do not mark all damage complete. |
| F03 | Weakness, toughness, Break and Super Break | W06/W14; R2 and shared templates | **Active; first shared-rule map delivered 2026-09-24.** Units, level table, initial/seven-element/Super Break bases and applicability are recorded. Remaining injection, accumulator/threshold, special-bar and state-sampling questions are explicit. |
| F04 | Healing, shielding and damage-to-HP interfaces | W05; R3, March and public-model reconciliation, F06 lifecycle | **Active; first shared-rule map delivered 2026-09-24.** Healing eligibility/realized gain, creator bonuses, ordinary absorption, explicit named-shield accumulation and direct-loss distinctions are mapped. Sampling, multi-pool overlap, overflow payloads and special routes remain explicit. |
| F05 | Effect application, immunity and random-choice classes | W09/W12; ordinary RNG/callback record and F03 application inputs | **Active; first shared-rule map delivered 2026-09-24.** Base/fixed probability, EHR/general/category resistance, shared immunity and consumed protection, actual attempt count and conditional repeated-attempt model. Exact override/charge/context questions remain open. |
| F06 | Modifier instances and lifetime | W09/W10; R3, shared modifiers and F05 admission/consumption boundary | **Active; first shared-rule map delivered 2026-09-24.** Identity, layer/cap-refresh, lifetime addition, caster-timed parent/recipient children and cleanup are mapped. Matching/update precedence, clock exceptions and exact sampling remain named residuals. |
| F07 | Shared resource economy | W08; R4, linked skill descriptions and F08 action/clock distinctions | **Active; first shared-rule map delivered 2026-09-24.** Energy/BP identity, amplified/fixed/max-relative grants, cost/capacity, signed spending and memosprite deduplication are mapped. Initial Energy policies, per-event allocation, overrides and transaction-order questions remain explicit. |
| F08 | Time, turn and action categories | W07/W10; OneMore/timeline source record and F06 clock distinctions | **Active; first shared-rule map delivered 2026-09-24.** Ordinary SPD/AV, rescaling, full-gauge advance/delay, absolute zero and action/clock distinctions are mapped. Exact unit transport, exceptional scheduling and first-step rules remain named questions. |
| F09 | Target and damage-source context | W11/W15; R7, general source/frame evidence and F04 source ownership | **Active; first shared-rule map delivered 2026-09-24.** Per-effect targets, bounded bounce validity, weighted-primary versus collateral exposure, split destinations and inherited ownership are mapped. Invalid-target, policy, formation and context-propagation residuals remain explicit. |
| F10 | Event, entity and encounter lifecycle | W10/W13/W16/W17; R6, retained servant/source records and F09 context distinctions | **Active; first shared-rule map delivered 2026-09-24.** Activation/trigger/recheck, lethal recovery/shared quota, death-rattle/forced cleanup, phase/wave/result/leave boundaries are mapped. Exact arbitration, state retention, muting and exceptional scenario routes remain explicit. |

F01 facts have been reused as the other foundations proceeded; its first synthesis is now delivered. An integrated assessment of unresolved common behaviors and source coverage is the next obligation, not a result already claimed by the ten first-pass records. Any subsequent bounded closure must explain the mechanism reason rather than follow an actor's remaining kit or import a progression workflow.

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

## 6D. F07 shared-rule result and remaining research

[F07 v1][RESOURCES] follows the former resource frame while reusing R4's precise rows and F08's action/clock distinctions. It separates public-model conclusions from exact new field and binding discoveries.

- [x] Reconcile selected SPBase/SPNeed and BPAdd/BPNeed with actor Energy and shared Skill Points using source roles and labeled public skill data.
- [x] State ordinary base-grant amplification, cost/refund separation, capacity bounds and offered versus realized gain; retain varying event-local rates.
- [x] Read a direct SPRatioBase0.05 property contribution and distinguish it from an immediate Energy grant or an unrelated set-effect parameter.
- [x] Trace FixedAddValue and FixedAddMaxSPRatio through distinct typed inputs/recipients; do not conflate either with AddRatio or AddValue.
- [x] Use published fixed-grant behavior and a capacity-versus-cost counterexample without pretending unread numeric rows were newly extracted.
- [x] Reconcile the memosprite one-per-memomaster team-grant model with AllTeammateOnlyAddSPOnceForServant and reused explicit owner grants.
- [x] Trace separate team balance and maximum-capacity operations, preserving the baseline3/5 and actual override branches.
- [x] Trace signed negative-BP-event input to a per-point layer addition rather than a per-action increment.
- [x] Distinguish first-wave entry grants from baseline initialization and reject automatic round regeneration inferred from an unconsumed constant.
- [x] Retain a credited historical ERR test while rejecting its contested rounding and blanket-origin generalizations.
- [ ] Resolve encounter-specific initial Energy/carry-over and capacity construction beyond the selected requirement inputs.
- [ ] Resolve per-hit/SPHitRatio/additional-action allocation and remaining SPBase/mixed-field evaluator edges.
- [ ] Resolve per-family rate/owner sampling during redirection and concurrent debit/refund/grant/availability behavior.
- [ ] Map special spending substitutes, overfill/alternate gauges, exact precision and capacity-override teardown.

The common equations and named branches are usable evidence; these unchecked residuals are not backend repair gates or a claim that all resource behavior remains unknown.

## 6E. F04 shared-rule result and remaining research

[F04 v1][SUSTAIN] follows the former sustain frame while reusing R3/March's basic formulas and the earlier public-model reconciliation. It distinguishes an operation's amount, eligibility, source identity, realized state change and exit dependencies.

- [x] Separate base/modified/offered healing from ordinary realized HP recovery and overflow; do not invent a universal overflow-to-shield conversion or callback payload.
- [x] Trace the selected healing penalty from typed parameter through installation to an actual-owner comparison and signed Target_HealTakenRatio request; retain its additive public-model interpretation and self-source exclusion.
- [x] Trace shared outgoing-healing and shield-bonus inputs separately, including exact Set103 four-piece0.2 -> SkillRelic -> ShieldAddedRatio.
- [x] Separate creator shield generation from recipient damage mitigation and ordinary absorption/HP overflow, using the credited historical mitigation-before-shield report.
- [x] Distinguish ordinary non-additive shields from a publicly specified, explicitly authored StackShield accumulation mechanism.
- [x] Trace a named CurrentShield carry read with an explicit zero fallback; distinguish its state identity, new grant, cap and lifetime.
- [x] Preserve explicit shield/dependent-state cleanup without turning it into a universal same-hit destruction order.
- [x] Read a MaxHP-relative direct-loss request with Floor1 and retain a public-model distribution-before-mitigation counterexample as separately attributed.
- [ ] Resolve remaining positive incoming-heal combinations, extreme factors, special conversions and offered/effective/overheal event payloads.
- [ ] Reconcile exact per-family sampling and changed-cap/mixed-grant behavior beyond fixed-input accumulation.
- [ ] Complete multi-shield draining/expiry arbitration, special team/shared shields and shield-depletion visibility.
- [ ] Resolve exact distribution/source joins, direct-loss event consequences, rounding and concurrent HP/cleanup transitions.

The checked leaves cover these shared rules and contrasting branches, not every sustain effect or W05 mechanism_closed. Native implementation absence does not erase their supported gameplay meanings.

## 6F. F09 shared-rule result and remaining research

[F09 v1][TARGETS] follows the former targeting frame while separating raw target operations from local projections, public behavior models and credited experiments. It does not reopen an enemy-controller implementation task.

- [x] Separate selected primaries, automatic sets, per-effect expansion, internal traversal and actual source/recipient roles.
- [x] Trace the selected initial hit, bounded bounce count and supplied ParamEntity damage continuation without treating an impact envelope as every actual hit.
- [x] Preserve the shared bounce's opaque task type, full AliveOnly/HP predicate, IncludeLimbo and MaxNumber1; reject unconditional alive-only replacement.
- [x] Trace distinct primary/adjacent HealHP inputs, primary-only explicit cleanse, self Energy and voice-only random traversal within the selected skill body.
- [x] State the conditional positive-weight aggro model with a pinned BaseAggro input and reused HP-gated aggro contribution; distinguish relative weights from guaranteed targeting.
- [x] Derive collateral exposure separately from primary probability under a stated simple blast geometry, without claiming uniform boss targeting.
- [x] Retain public taunt and memosprite-adjacency contrasts without generalizing them to all scripts or secondary entities.
- [x] Trace a split parameter into complementary ratios, Caster destination and a guard against already-split damage; keep original selection distinct from distributed recipients.
- [x] Pair explicit InheritCaster=TargetSelf with a credited stat/kill-Energy ownership report, without generalizing its snapshot sentence.
- [x] Record the old Asta/shared-template cached-anchor mismatch and use actual exact-pin reread blobs for new claims.
- [ ] Resolve selection-to-impact invalidation, empty/terminal candidate behavior and generic retarget cardinality/replacement.
- [ ] Resolve enemy-specific policies, taunt/lock-on/script precedence and extreme-weight cases with concrete evidence.
- [ ] Reconcile formation holes, late insertion, multirow and special adjacency outside the selected ordinary model.
- [ ] Trace complete nested/inherited/split/redirection context and event-specific attribution for simultaneous consequences.

The selected Fu Xuan source join advances F04's named distribution question, not every damage-sharing or event-attribution rule. F09/W11/W15 remain active; no broad W checkbox or runtime maturity is promoted by these leaves.

## 6G. F10 shared-rule result and remaining research

[F10 v1][LIFECYCLE] follows the former lifecycle frame and explicitly reuses the staged Bailu/servant findings already in W10. It expands their common eligibility, quota and reset-scope meanings rather than claiming a second discovery of the same event names.

- [x] Distinguish definition/installation, event eligibility, pending insertion and execution-time mutation as separate evidence dimensions.
- [x] Trace self lethal recovery's controller, Count1, typed SetHP operands and explicit ActivateAfterRevive=false, preserving omitted counter-update fields.
- [x] Trace provider-owned rescue quota versus teammate readiness; retain the RemoveServant selector, self/source-health/control exclusions and separate late-member installation.
- [x] Distinguish OnBeingLimbo marking, OnLimboWaitHeal insertion/abort conditions and the inserted body's HP recheck; do not infer a universal winner between rescue providers.
- [x] Reconcile the selected once-per-battle descriptions with source quota/reentry inputs rather than reset charges on every wave or entity-create notification.
- [x] Reuse death-rattle input and selective carry-state transfer while preserving muted ForceKill, immediate death and explicit cleanup as different requests.
- [x] Separate same-Caster phase HP/stance resets from new-wave creation and encounter completion.
- [x] Trace suppressed-passive enemy spawning followed by explicit passive and entry requests; distinguish later-wave entry dispatch from first-wave-gated effects.
- [x] Preserve dying/turn-end/fight-finished guards, delayed-spawn context, provisional-win rechecks and win/lose/quit leave routes.
- [ ] Resolve competing recovery/reservation, simultaneous lethal/split effects and exact cross-event ordering with concrete evidence.
- [ ] Reconcile per-revival-family buff, action-slot and source-state retention, including omitted counter defaults and special reentry.
- [ ] Resolve exact muted-event coverage and departure-trigger/resource outcomes beyond the literal force-kill requests.
- [ ] Complete exceptional late/delayed spawn, reinforcement, restart and scenario-result precedence/settlement rules.

These are bounded common-rule results, not a universal lifecycle census, complete native dispatcher or broad W-package closure. Public descriptions and credible tests can advance the residuals without a backend repair prerequisite.

## 6H. F01 shared-rule result and remaining research

[F01 v1][PARAMETERS] follows the former synthesis frame with the owner's explicit exclusion of progression research. It uses the actual read, expression, write and consequence rather than a name-based property taxonomy.

- [x] Separate selected combat coefficient/effect fields from colocated costs, materials, account prerequisites and presentation metadata.
- [x] Reuse family/owner/level-qualified parameter routing, zero-based typed indices, one-based description/servant slots and scoped working values.
- [x] Read empty-Param rank rows with nonempty SkillAddLevelList; distinguish combat parameter-level changes from acquisition and direct stat addition.
- [x] State an attributed ordinary character-plus-Light-Cone base, additive percentage and flat-amount composition without promoting unrelated native loader equations.
- [x] Trace a capped grant using recipient BaseAttack and provider Attack, including its misleading CurrentAttack working name and final AttackDelta consumer.
- [x] Trace Defence minus DefenceConvert, a typed conversion ratio and actual AttackConvert write despite an AttackDeltaUp modifier name.
- [x] Pair explicit OnStack/OnPhase1 reads with described refresh behavior; do not infer instant recomputation or a global conversion order.
- [x] Separate set PropertyList, repeated parameters and normal-hit context mutation instead of counting each numeric occurrence as a new stat grant.
- [ ] Resolve remaining family/working-slot resolution, initialization defaults and effective-level/override precedence through specific evidence.
- [ ] Reconcile additional conversion eligibility, snapshot/refresh interaction and same-time property propagation.
- [ ] Close exact bounds/precision and remaining base-loader/affix-source questions only at the combat-input boundary, without progression simulation.
- [ ] Reconcile the foundation results with W obligations and the in-scope source-family coverage ledger.

### Next research frame — integrated foundation gaps and coverage

Review F01-F10's claim-level residuals against the W worklist and source-family scope. Separate materially unknown common behavior, known behavior with an unexported native body, exceptional branches and missing corpus coverage. Retire superseded blanket unknowns only with precise supporting records; preserve actual uncertainties. Choose the next bounded common-mechanism closure using reusable value and discriminating evidence, not actor completion, backend readiness or progression completeness. This integrated review is not performed by the F01 checkpoint.

## 7. What counts as finishing the foundation pass

The pass is ready to support systematic actor completion when each known in-scope foundational family has a reusable rule/source map, applicability boundaries, representative positive and negative distinctions, and an explicit inventory of unresolved behavioral or export questions. Unknown foundational classes cannot be silently omitted.

This is not a requirement to prove the hidden engine's entire implementation or solve every extreme exception before any other research can move. A materially unknown common behavior remains open; a merely missing native body does not invalidate an independently established model. Unresolved source families remain in the completeness ledger.

Only then should the default activity become actor/equipment completion: instantiate the established common rules with their particular parameters, targets, conditions and lifecycle, and route genuinely new primitives back into the foundation records. Do not duplicate a general formula in every character record as if it were independently discovered.

## 8. Publication and history

The 2026-09-23 checkpoint added this roadmap and general damage. The 2026-09-24 continuations added F03, F05, F06, F08, F07, F04, F09, F10 and now F01, with corresponding roadmap/README updates. The existing W worklist, older source records, scope, inventory and pin are preserved; claim-level results do not silently check package-wide obligations. Prior roadmap content remains auditable at evidence parents `21c3d13a47d36dea57a25aa82b0915f4e6c4f3ea`, `d1ff8c9dd8df90eefd7134f7374b1faee78c5ace`, `b1b1db9fabb04926dd2669e44d93c830fd784397`, `96896f677eaf14eaaa0b7692289801f69b4fcb8c`, `e392081bd2c016ca686923b2e619d0a2564510d2`, `1a814ca21efc28e0af9aaac7a1e7220eff29938e`, `2718b77036a7085f67fd66814af2268ea3882f8d`, `adc555818592fd62556d4fc93d8be1bd020e79ea` and `98bc2a3db82756519816c7c577f274821cc68ba4`.

No runtime, lowering, IR, tests, CI or backend task is changed. Existing public reports and calculations are not claimed as new gameplay runs. The PR checkpoint records the actual final evidence head and Markdown-only diff. Stop this checkpoint after publication; integrated foundation-gap/coverage review is next, not automatic character completion, progression research or a repair handoff.

[WORKLIST]: ../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_RESEARCH_WORKLIST.md
[SCOPE]: ../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_SCOPE.md
[DAMAGE]: general_damage_formula_and_input_layers_v1.md
[BREAK]: general_weakness_toughness_break_super_break_v1.md
[APPLICATION]: general_effect_application_hit_resistance_immunity_v1.md
[MODIFIERS]: general_modifier_identity_stacking_lifetime_v1.md
[TIMING]: general_speed_action_value_turn_clock_v1.md
[RESOURCES]: general_energy_skill_point_economy_v1.md
[SUSTAIN]: general_healing_shield_hp_resolution_v1.md
[TARGETS]: general_target_selection_expansion_source_context_v1.md
[LIFECYCLE]: general_event_entity_encounter_lifecycle_v1.md
[PARAMETERS]: general_parameter_effective_property_semantics_v1.md
