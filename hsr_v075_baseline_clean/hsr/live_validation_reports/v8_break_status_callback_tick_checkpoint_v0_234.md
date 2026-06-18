# v8 v0_234 Break Status Callback Tick Checkpoint

## Scope

本阶段继续收束普通韧性/击破板块，新增从真实主线 `ConfigGlobalModifier` modifier `_CallbackList` 到 runtime tick 的结构化链路：

```text
Break AddModifier -> StatusInstance -> StatusCallbackIR/StatusCallbackTaskIR
-> StatusDamageEmissionIR / ActionDelayEmissionIR
-> StatusCallbackSystem -> DamageSystem / blocked delay record
```

## Implemented

- 新增 `StatusCallbackIR`、`StatusCallbackTaskIR`、`StatusDamageEmissionIR`、`ActionDelayEmissionIR`。
- 从主线 `ConfigGlobalModifier/GlobalModifier_Common_Specific.json` lower `OnStack`、`OnPhase1` callback。
- `OnPhase1 + DamageByAttackProperty + FormulaType=ByBreakDamage + AttackType=DOT` admitted 为 break DoT tick。
- 新增 `StatusCallbackSystem`，显式执行 `ModifierPhase1End` 类 tick transition。
- break DoT tick 通过 `DamageSystem` 发出 `damage_formula_family=break` 的 HP mutation，settlement `record_type=break_dot_tick`，不走 direct multiplier ledger。
- `ModifyActionDelay/SetActionDelay` lower 为 `ActionDelayEmissionIR`；当前 `AddNormalizedValue` AV 尺度未 admission，因此只输出 blocked process record，不改 state。
- `BreakSystem` 在 break status 创建后执行 `OnStack` callback；blocked 延后只记录，不使 break lifecycle 失败。
- `RuntimeSourceAuditor` 增加 status callback damage provenance，tick mutation 可追溯到 `StatusDamageEmissionIR + StatusCallbackIR + StatusCallbackTaskIR + BreakBaseDamageIR + BreakTemplateIR`。

## Guardrails

- 非主线 Activity/Rogue/SU/DU/Currency War callback 不进入 executable 主路径。
- `ShowStanceList/ShowStance` 继续只作为 evidence，不产生 toughness/break/tick mutation。
- unsupported callback、unsupported condition、unbound dynamic hash、blocked action delay 不改 state。
- tick 数值绑定来自 `AvatarBreakDamage` 与 `StatusInstance.dynamic_values`，不使用固定角色、固定 action、固定 hash 或观测数值。

## Validation

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_231 --output-dir /tmp/hsr_v8_regression_v0_231
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_233 --output-dir /tmp/hsr_v8_regression_v0_233
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_234 --output-dir /tmp/hsr_v8_v0_234
git diff --check
```

结果：

- v0_225 ok=true
- v0_227 ok=true
- v0_231 ok=true
- v0_233 ok=true
- v0_234 ok=true

## Remaining Boundaries

- `ModifyActionDelay.AddNormalizedValue` 到最终 AV 尺度仍 blocked，等待更明确的 timeline formula/source admission。
- `OnListen*`、global listener、being-hit listener、per-hit trigger 仍不执行。
- 超击破、队列插队、弹射 RNG 不属于本阶段。
