# P8-S13 Relic Set Thresholds: Ready for Review

## Scope

- Added canonical, source-backed relic set activation decisions and contributors.
- Added pure set/domain/threshold admission and counting from completed relic selections.
- Connected decisions to formal equipment assembly without applying properties or abilities.
- Narrowed the relic battle blocker reason to `relic_static_contributions_not_assembled`.

## Business Evidence

Delta-authorized replacement final: `ok=true`, 22/22 predicates true.

- Admitted relics only; duplicate instance identity blocks the whole assembly with no decisions.
- Real outer 4, 2+2, 2+1+1, planar matching/mismatched, planar single-piece partial, domain isolation, replacement, source completeness, and permutation cases passed.
- All threshold definitions were resolved from the RuleBook. A validation-fixture 1/3 set proved non-2/4 thresholds and cumulative activation.
- Active decisions preserve lower thresholds, retain typed definition/domain/threshold sources and the contributing selection identity/source tuple.
- Model rejects a missing relic activation channel through both `from_json` and `replace`; forged activation IDs are rejected.
- An unpublished set fixture returns diagnostics with zero decisions, proving atomic rejection before threshold output.
- Permutation preserves build/result fingerprints and decisions. Controlled replacement changes both fingerprints while leaving the unrelated set decision byte-for-byte equal.
- No static contribution, dynamic mechanism, ability startup, runtime, scenario, or UI behavior was added.

## Validation Resources

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s13_delta_time_v.txt timeout --signal=TERM 5m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s13_relic_set_thresholds --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s13_relic_set_thresholds_delta
```

- Replacement-final wall time: 0.43 s; peak RSS: 64,072 KiB; summary: 340,549 bytes.
- One focused relic catalog build and one RuleBook build; 12 cases.
- Validator: 647 physical lines / 600 non-empty lines, below the 800-line target.
- This report: 46 physical lines / 32 non-empty lines.
- `compileall` and `git diff --check` passed.
- Direct slices: `roundtrip=true`, `source_conflict_blocked=true`, unpublished set atomic block, missing channel rejection through `from_json`/`replace`, and forged decision ID rejection all passed.

Before this delta, the validator had already run three full invocations, exceeding the execution card's two-run cap: an initialization failure before case execution, a diagnostic failure caused by fixture construction, and a replacement final that passed. This delta was explicitly authorized as one additional replacement final. Its focused failure slices were green before the fourth full invocation above; no earlier record was removed or reclassified.

## Not Run

- S10-S12 complete validators, static contribution, ability, runtime, scenario, UI, catalog/full aggregate validation.

## Remaining Blocker

Non-empty relic builds remain battle-blocked solely by `relic_static_contributions_not_assembled`; static contribution application is outside this stage.
