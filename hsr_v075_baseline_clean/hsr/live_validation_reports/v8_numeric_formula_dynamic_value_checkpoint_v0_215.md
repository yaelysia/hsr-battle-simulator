# v8 Numeric Formula / DynamicValue Checkpoint v0_215

## Scope

- Added a unified numeric evaluator for fixed values, bound dynamic hashes, unbound dynamic hashes, and unsupported postfix expressions.
- Runtime effect execution can now use explicit dynamic hash bindings without making context-free coverage claim those effects are generally executable.
- `StatusSystem` now uses the shared evaluator for AddModifier DynamicValues and StackProperty values, and status instances keep name/hash keyed dynamic value evidence.
- `ModifySPNew` is lowered as a skill point resource delta standard payload.
- Heal and shield formula types remain conservative: unsupported formula families are blocked instead of guessed.

## Validation

Command:

```bash
cd hsr_v075_baseline_clean/hsr
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_215 --output-dir validation_outputs_v0_215
```

Result:

- `ok=true`
- Numeric evaluator validates fixed, bound dynamic hash, unbound dynamic hash, and unsupported postfix paths.
- Real Gepard `InitShield` dynamic `ShieldValue` executes with explicit binding and produces a shield mutation.
- The same Gepard shield effect without binding is blocked with `dynamic_hash_unbound`.
- Real Huohuo `HealHP` remains blocked with `formula_type_not_supported:HealByHealerMaxHP`.
- Real `ModifySPNew` is lowered and executes with explicit dynamic hash binding as a skill point mutation.
- Status modifier ledger, direct damage semantics, true damage, and hp loss regressions pass.
- Static checks, snapshot completeness, transition contract, settlement traceability, and replay pass for executable transitions.

## Remaining Risks

- Runtime bindings are explicit battle inputs; v0_215 does not yet derive all hash values from TBGD level tables or full action context.
- `HealByHealerMaxHP`, `HealByTargetMaxHP`, shield percentage formulas, and complex PostfixExpr remain blocked.
- Context-free coverage still reports dynamic-hash-only effects as blocked/lowered because executable status depends on runtime bindings.
- Full DoT, break, super-break, queue, listener/global trigger, and C0-C8 route rebuild remain out of scope.
