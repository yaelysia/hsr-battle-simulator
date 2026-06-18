# v8 v0_233 普通击破伤害公式检查点

## 范围

本阶段继续收束韧性/普通击破板块，没有切换到新模块。

已完成：

- `AvatarBreakDamage.json -> BreakBaseDamageIR`，作为普通击破基础伤害表。
- `StanceBreak_{element}.DamageByAttackProperty FormulaType=ByBreakDamage -> BreakDamageEmissionIR` admission。
- `NumericEvaluator` 增加保守 PostfixExpr VM，支持 fixed、dynamic hash、add/sub/mul/div。
- `BreakSystem` 在韧性归零后通过 executable `BreakDamageEmissionIR` 发送 `DamagePacket(family="break")`。
- `DamageSystem` 增加 `break` family，普通击破伤害产生 HP mutation 和 `break_damage` settlement。
- `RuntimeSourceAuditor` 校验 break damage mutation 的 `BreakDamageEmissionIR`、`BreakBaseDamageIR`、numeric evaluation 与 source trace。

仍未完成且未伪造：

- break DoT tick：需要击破状态 callback/tick formula admission。
- break delay/recovery：需要延后/恢复来源 task admission。
- global listener、being-hit listener、per-hit trigger、super-break、queue：不在本阶段范围。

## 来源与语义

- 削韧来源仍是 `DamageByAttackProperty.AttackProperty.StanceValue`，不是 `ShowStanceList`。
- 普通击破伤害来源为 `ConfigGlobalTaskListTemplate/StanceBreak_{element}` 中的 `ByBreakDamage` task。
- `BreakDamagePercentage` 通过通用 PostfixExpr evaluator 求值，不按角色、动作、文件名或固定 hash 特判。
- break damage 不生成 direct damage multiplier ledger；未 admission 的 postfix、未绑定 dynamic hash、blocked template 不改状态。

## 验证结果

运行目录：`hsr_v075_baseline_clean/hsr`

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_229 --output-dir /tmp/hsr_v8_regression_v0_229
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_231 --output-dir /tmp/hsr_v8_regression_v0_231
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_232 --output-dir /tmp/hsr_v8_regression_v0_232
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_233 --output-dir /tmp/hsr_v8_v0_233
git diff --check
```

结果：

- v0_225 / v0_227 / v0_229 / v0_231 / v0_232 / v0_233：全部 `ok=True`。
- v0_233：break base damage lowered/executable，break damage emission executable。
- v0_233：至少一条真实主线 action 触发韧性归零、break lifecycle、break status、break damage HP mutation。
- v0_233：break damage mutation 通过 settlement traceability、snapshot replay、source audit。
- v0_233：unsupported postfix、unbound dynamic hash 均 blocked。

