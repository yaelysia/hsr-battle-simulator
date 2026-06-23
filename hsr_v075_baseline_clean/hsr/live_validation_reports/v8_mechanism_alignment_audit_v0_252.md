# v8 v0_252 Mechanism Alignment Audit

## Summary

v0_252 adds a mechanism-alignment audit for extra action semantics. The goal is to prevent runtime behavior from drifting away from game mechanics when TBGD names look suggestive but do not prove executable semantics.

The key correction is that text hints such as `follow`, `counter`, `oneMore`, or `ultimate` no longer make a queue window executable. They remain discovery evidence only. Executable queue behavior still requires admitted source, priority, target, action or ability resolution, and source audit.

## Game Mechanic Baseline

External references used for audit context only:

- Seele combat page: https://honkai-star-rail.fandom.com/wiki/Seele/Combat
- Rappa combat page: https://honkai-star-rail.fandom.com/wiki/Rappa/Combat
- Feixiao combat page: https://honkai-star-rail.fandom.com/wiki/Feixiao/Combat
- Acheron combat page: https://honkai-star-rail.fandom.com/wiki/Acheron/Combat

These references are not runtime rule inputs. Runtime rules still come from TBGD lowering into Canonical IR.

## Implemented

- `UseSkillOneMore` remains `SkillContinuationIR`, not true extra turn.
- Queue window lowering keeps text matches as `discovered_only` evidence instead of executable family classification.
- Extra-turn policy records that action choice must come from source or route and cannot default to a normal free turn.
- `validate_v0_252` writes `extra_action_alignment_matrix_v0_252.json`.

## Current Status

- Seele-style true extra turn: partially structured through `OneMore` and inserted action evidence, but not yet fully executable as a free/limited extra-turn action policy.
- Rappa-style limited extra turn: blocked until state-driven action restriction is admitted.
- Feixiao/Acheron-style continuation: classified as skill or ultimate internal continuation; no continuation runner yet.
- Follow-up/counter: text hints are discovery only; executable cases require admitted listener or callback source.
- Manual ultimate queue execution: remains trusted for the current scope.

## Validation

Expected commands from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_248 --output-dir /tmp/hsr_v8_regression_v0_248
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_249 --output-dir /tmp/hsr_v8_regression_v0_249
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_250 --output-dir /tmp/hsr_v8_regression_v0_250
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_251 --output-dir /tmp/hsr_v8_regression_v0_251
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_252 --output-dir /tmp/hsr_v8_v0_252
git diff --check
```

