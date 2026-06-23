# v8 Status Duration Lifecycle Checkpoint v0_245

## Summary

v0_245 closes the fixed-duration status lifecycle gap left by the scheduler loop work.

The admitted path is now:

```text
AddModifier LifeTime / modifier LifeStepMoment
-> runtime duration admission
-> StatusInstance.remaining_duration
-> scheduler ActionPhaseEnd / ModifierPhase1End hook
-> StatusSystem tick / expire mutation
-> settlement / replay / source audit
```

This checkpoint does not add character-specific behavior. It only admits fixed numeric `LifeTime` with a supported `LifeStepMoment`.

## Implemented

- Added duration evidence to lowered modifier definitions and `AddModifier` standard payloads:
  - `lifetime_expr`
  - `life_step_moment`
  - `duration_admission`
- Added runtime duration admission in `StatusSystem`.
- Replaced the old vague `turn_or_life_step` runtime duration marker with explicit `life_step_moment`.
- Added `StatusSystem.plan_lifecycle_tick()` and `StatusSystem.apply_lifecycle_tick()`.
- Added mutation-backed duration decrement for admitted status details.
- Added mutation-backed expire that removes both `statuses` and `status_details`.
- Wired `ActionPhaseEnd` lifecycle ticks after action execution and before turn end.
- Wired `ModifierPhase1End` lifecycle ticks into `CombatScheduler.end_current_turn()`.
- Extended source audit so status tick/expire mutations require executable duration admission.
- Updated scheduler coverage so duration tick is admitted for the fixed-duration current scope instead of reported as fully blocked.
- Added `validate_v0_245`.

## Validation Results

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_242 --output-dir /tmp/hsr_v8_regression_v0_242
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_244 --output-dir /tmp/hsr_v8_regression_v0_244
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_245 --output-dir /tmp/hsr_v8_v0_245
git diff --check
```

All checks passed.

v0_245 checked:

- A real `ModifierPhase1End` duration status from `StanceBreak_Fire` can tick from 2 to 1.
- The same status expires on the next admitted tick and removes status id plus status detail.
- A real `ActionPhaseEnd` duration status from a mainline monster ability using `OneMore` expires through `CombatScheduler.step()`.
- Dynamic lifetime, unknown `LifeStepMoment`, and permanent/unknown duration negative cases do not mutate state.
- Status lifecycle mutations pass settlement traceability, snapshot replay, and source audit.

## Remaining Boundaries

- Dynamic or postfix `LifeTime` remains blocked until numeric admission proves the value.
- Unsupported `LifeStepMoment` values remain blocked until each moment is mapped to a concrete scheduler hook.
- This checkpoint does not implement enemy AI, full character profile construction, follow-up/counter semantics, ultimate interrupt flow, waves, or bounce RNG.
- Extra turn, ultimate, and interrupt hooks remain blocked until their queue/window priority semantics are admitted.
