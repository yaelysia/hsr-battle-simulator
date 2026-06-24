# v8 v0_258 Ordinary DoT Formula Checkpoint

## Summary

v0_258 fixes ordinary DoT admission. `DamageByAttackProperty` with `AttackType=DOT` is no longer blanket-blocked when its `DamageValue` can be evaluated from admitted runtime bindings.

Runtime path:

```text
StatusDamageEmissionIR(dot)
-> DotFormula
-> DamagePacket(dot)
-> DamageSystem
-> Mutation / Settlement / SourceAudit
```

## Implemented

- Ordinary DoT lowering admits real mainline `OnPhase1 + AttackType=DOT` status damage when `DamageValue` is fixed or runtime-bound.
- `ExtraFormulaType=ByDefence` is admitted when caster defense is available and `ExtraDamagePercentage` is evaluable.
- `DamagePercentage` is retained as evidence and a skipped ledger term until its base formula is admitted.
- Status callbacks now dispatch ordinary `dot` and break DoT separately.
- DoT uses `DamageSourceFrame(source_kind="dot")`, keeps v0_256 kill attribution, and skips later DoT sources after target death.
- DoT does not produce direct crit or direct multiplier ledger.

## Still Blocked

- DoT `DamagePercentage` as a primary formula branch: blocked on admitted base stat/formula source.
- Non-`ByDefence` extra formula types: blocked until each formula family is admitted.
- True damage and elation remain blocked without executable TBGD source/formula admission.

## Validation

Required validation target:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_258 --output-dir /tmp/hsr_v8_v0_258
```

Result:

```text
v8 v0_258 validation ok=True
```

Key coverage:

- Real mainline ordinary DoT status callback produces HP mutation.
- Real `ByDefence` extra branch applies through the DoT ledger.
- Unbound dynamic hash blocks with unchanged snapshot.
- Unsupported extra formula blocks with unchanged snapshot.
- DoT order preserves v0_256 source-window semantics: the lethal DoT receives kill credit and later DoT sources skip dead targets.
