# v8 v0_251 Extra Action Semantics Checkpoint

## Summary

v0_251 separates three mechanics that were previously easy to confuse:

- true extra turns, such as Seele-style extra action opportunities;
- skill or ultimate internal continuations, represented by `UseSkillOneMore`;
- follow-up and counter queue windows.

`UseSkillOneMore` is no longer lowered as an extra-turn queue source. It is recorded as `SkillContinuationIR` and remains blocked until a dedicated continuation runner is admitted.

## Implemented

- Added `SkillContinuationIR` for `UseSkillOneMore` evidence.
- Removed `UseSkillOneMore -> extra_turn QueueIntentIR` lowering.
- Updated queue ordering so follow-up/counter come before ultimate and extra turn, while ultimate and extra turn share the same order tier.
- Added deferred natural turn end handling when an action creates pending queue entries.
- Added `validate_v0_251` for classification, queue ordering, and deferred turn-end replay/source-audit checks.

## Not Implemented

- No skill/ultimate continuation runner yet.
- No character-specific extra-turn implementation.
- No enemy AI, assistant actor resolution, or full follow-up/counter automation.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_248 --output-dir /tmp/hsr_v8_regression_v0_248
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_249 --output-dir /tmp/hsr_v8_regression_v0_249
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_250 --output-dir /tmp/hsr_v8_regression_v0_250
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_251 --output-dir /tmp/hsr_v8_v0_251
git diff --check
```

All checks passed.

