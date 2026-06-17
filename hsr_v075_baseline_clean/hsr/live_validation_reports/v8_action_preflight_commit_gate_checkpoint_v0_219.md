# v8 Action Preflight Commit Gate Checkpoint v0_219

## Scope

- Added a preflight/commit gate to `CombatExecutor`.
- Failed or blocked actions now keep process-only audit records but do not commit timeline, resource, trigger, damage, status, or RNG mutations.
- `TargetSystem` now treats `bounce`, `unknown`, and unsupported target modes as non-executable target resolution results.
- Every transition now records `action_preflight` with `action_enabled`, `blocked_reason`, `target_ok`, `resource_ok`, and plan block state.
- Multi-target transitions now expose current limitations explicitly:
  - `primary_action_target_id`
  - `per_hit_target_context_not_implemented`
  - trigger metadata `multi_target_scope_partial`
  - damage packet metadata `target_group_multiplier_not_implemented`
- Static checks now guard runtime main paths from importing the TBGD compiler/discovery layer directly.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir /tmp/hsr_v8_regression_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir /tmp/hsr_v8_regression_v0_203
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir /tmp/hsr_v8_regression_v0_204
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_205 --output-dir /tmp/hsr_v8_regression_v0_205
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_206 --output-dir /tmp/hsr_v8_regression_v0_206
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_207 --output-dir /tmp/hsr_v8_regression_v0_207
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_208 --output-dir /tmp/hsr_v8_regression_v0_208
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_209 --output-dir /tmp/hsr_v8_regression_v0_209
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_210 --output-dir /tmp/hsr_v8_regression_v0_210
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_211 --output-dir /tmp/hsr_v8_regression_v0_211
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_212 --output-dir /tmp/hsr_v8_regression_v0_212
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_213 --output-dir /tmp/hsr_v8_regression_v0_213
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_214 --output-dir /tmp/hsr_v8_regression_v0_214
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_215 --output-dir /tmp/hsr_v8_regression_v0_215
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_216 --output-dir /tmp/hsr_v8_regression_v0_216
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_217 --output-dir /tmp/hsr_v8_regression_v0_217
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_218 --output-dir /tmp/hsr_v8_regression_v0_218
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_219 --output-dir validation_outputs_v0_219
```

Result: all validations returned `ok=True`.

v0_219 checks:

- `unknown_target`, `insufficient_sp`, `bounce`, and `unknown_target_mode` all produce unchanged after snapshots.
- These failed/blocked transitions have zero mutations, zero trigger windows, zero RNG events, and `action_enabled=false`.
- `action_preflight`, `action_blocked`, `target_error`, and `resource_error` records now agree with transition coverage.
- AOE and blast multi-target damage still replay successfully.
- AOE and blast trigger windows explicitly mark primary-target-only context as partial.
- AOE and blast damage packets explicitly mark target-group multiplier handling as incomplete.
- Runtime main import boundary guard passes.

## Remaining Risks

- `ActionExecutionPlan` is still derived from `ActionDefinitionIR`; real TBGD action/event IR remains future work.
- Multi-target trigger execution is still actor/primary-target local only; per-hit target context is not implemented.
- AOE/blast target-group multipliers are not implemented; current damage is structural only, not final numeric fidelity.
- Bounce RNG, multi-hit routing, toughness damage, break, DoT, and super-break remain blocked/future work.
- `core/fidelity.py` still belongs more naturally in an audit/tools boundary; this checkpoint only guards the executor runtime path.
