# v8 v0_235 普通击破收尾与超击破接入检查点

## 范围

- 新增 `SuperBreakEmissionIR`，从主线 `ConfigGlobalTaskListTemplate` 的 `DealSuperBreakDamage` / `BeingDealSuperBreakDamage` 降低真实 super-break 伤害来源。
- `DamageSystem` 新增 `super_break` family，只消费 executable `SuperBreakEmissionIR`，不走 direct 暴击/增伤账本。
- `StatusCallbackSystem` 接入 admitted `SetActionDelay -> TimelineSystem`，仅执行 fixed/status-bound numeric；`ModifyActionDelay.AddNormalizedValue` 继续 blocked。
- `BreakSystem` 新增基于真实 break status instance 的 recovery/expire 入口，清除 broken flags、恢复 toughness、移除 break status。
- `RuntimeSourceAuditor` 增加 action delay、break recovery、super-break damage provenance policy。

## 当前可信范围

- 普通削韧、弱点门控、broken lifecycle、普通 break damage、break DOT tick 保持当前范围可信。
- `SetActionDelay` 在 fixed/status-bound dynamic numeric 范围内可信；normalized delay 仍 blocked，依赖 AV 尺度 admission。
- break recovery 在 admitted break status instance 来源范围内可信。
- super-break 在 admitted global template + break base damage + 本次/已审计削韧量输入范围内可信。

## 仍不纳入本阶段

- `ShowStanceList` / `ShowStance` 仍只作 evidence，不产生 toughness/break/super-break mutation。
- `ModifyActionDelay.AddNormalizedValue` 未执行，blocking dependency 为 normalized AV 尺度未 admission。
- global listener、being-hit listener、per-hit trigger、队列插队、bounce RNG 仍未接入。

## 验证

运行目录：`hsr_v075_baseline_clean/hsr`

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_231 --output-dir /tmp/hsr_v8_regression_v0_231
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_233 --output-dir /tmp/hsr_v8_regression_v0_233
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_234 --output-dir /tmp/hsr_v8_regression_v0_234
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_235 --output-dir /tmp/hsr_v8_v0_235
git diff --check
```

结果：全部通过。
