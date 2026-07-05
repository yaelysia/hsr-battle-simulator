# v8 P1-7 RNG branch checkpoint

## Summary

P1-7 introduces a unified RNG decision substrate for the current first-phase random/probability paths. Runtime systems still use `core.model.RNGEvent`, but new and migrated events now share a `v8_rng_decision_v1` result/metadata shape:

- `decision_kind`, `purpose`, `choice_key`, `choice_source`
- `outcomes`, `selected_outcome_id`, `selected_payload`
- `available_rng_outcomes`
- `source_trace`

The new primary input is `rng_choices` plus optional `rng_mode`. Existing compatibility inputs remain accepted where they already existed:

- `crit_mode` maps to forced `crit/noncrit` outcomes.
- `target_random_choices` maps to `rng_choices` for P1-6 compatibility.

No new dependency was added.

## RNG Surface Matrix

| Surface | Current status | Source/admission boundary | Notes |
|---|---|---|---|
| `crit` | `executable` | engine convention + actor resources + direct damage source trace | Migrated through `systems/rng.py`; explicit ledger, forced legacy `crit_mode`, and deterministic seed mode are supported. |
| `target_random` | `executable` when target expression is executable | Canonical target expression IR | Missing explicit choice remains blocked and now carries `available_rng_outcomes`. |
| `bounce_target` | `executable` when bounce policy is executable | bounce policy from hit profile/action plan | Explicit ledger can select a legal target; deterministic seed mode remains available. |
| `status_apply_chance` | `executable` when AddModifier chance admission is executable | AddModifier standardized payload + numeric evaluator | Success/fail outcomes use unified probability event schema. |
| `status_resist` | `executable` for current first-phase effect resistance resource path | target `effect_resistance` runtime resource from setup/cards | Resisted/not-resisted outcomes use unified probability event schema. |
| `control_resist` | `source_gap_blocked` | `control_kind` metadata exists, complete control resist formula/admission is not complete | Not promoted to a separate executable RNG branch. |
| `random_dispel` | guarded runtime path; positive source remains source-gap if no `Order=Random` source exists | DispelStatus `Order=Random` only | Unified choice event is used when admitted; no synthetic positive mutation is claimed. |

## Implementation Notes

- Added `systems/rng.py` with `RNGOutcome`, `RNGRequest`, `RNGResolution`, `resolve_rng_request`, `available_rng_outcomes`, and event result helpers.
- Migrated direct damage crit RNG, target expression random selection, bounce target selection, status apply chance, status resist, and random dispel selection to the central resolver.
- Threaded `rng_choices`/`rng_mode` through action damage metadata, ability effect contexts, trigger effect contexts, and event dispatch RNG aggregation.
- Kept old compatibility fields only as input shims; emitted `RNGEvent` records use the unified schema.

## Validation

Lightweight validation entry:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_rng_branch_system
```

The P1-7 validator covers:

- central helper missing choice, invalid choice, explicit choice, forced choice, deterministic replay
- crit explicit `crit/noncrit` and deterministic replay
- target random explicit choice, legacy `target_random_choices`, missing choice, invalid choice
- bounce deterministic replay, explicit choice, invalid choice
- no process random static scan over `core/` and `systems/`
- RNG surface/source matrix output

Heavy legacy regressions such as `validate_v0_209` and `validate_v0_264` were not run as part of this checkpoint to avoid WSL resource exhaustion. The direct P1-7 validator contains focused contract coverage for the migrated surfaces; old regression execution remains a separate final-stage option.

## Current Completion State

`P1-7-SUBSTRATE-ACCEPTED` is the intended completion level for this checkpoint:

- Existing first-phase RNG paths have a shared request/event schema.
- Explicit ledger and deterministic seed modes are both represented.
- Missing/invalid choices return blocked data with available outcomes.
- Failed chance, resisted, and missing choice paths remain process-only and do not create status mutations.
- Random dispel and control resist are not claimed as full positive executable mechanisms without complete source/admission.

Remaining work toward full replication:

- Full branch enumerator/searcher integration in P1-8+.
- Complete official control resistance semantics.
- Broader source-admitted random dispel positive validation if/when current TBGD/IR provides `Order=Random`.
- Full legacy regression sweep under controlled resource limits.
