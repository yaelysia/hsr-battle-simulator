# v8 v0_249 Immediate Fix Closure Checkpoint

日期：2026-06-23

## 本次目标

本阶段不新增大模块，只清零当前已经有来源、runtime 承接能力和明确语义的可立即修复项。

## 已落地

- 终结技手动插队执行成功后，按 `ResourceRuleIR(source_kind=engine_convention)` 产生能量归零 mutation。
- 常用 condition VM 当前范围纳入验证：`ByAnd`、`ByAny`、`ByCompareDynamicValue`、`ByCompareModifierValue`、`ByCompareHPRatio`。
- Heal / Shield 新公式族接入当前可信范围：
  - `HealByTargetMaxHP`
  - `HealByHealerMaxHP`
  - `ShieldByCasterMaxHP`
  - `ShieldByCasterDefence`
  - `ShieldByTargetMaxHP`
- `ModifySPNew` 当前可证明的 add / set / max-ratio 分支接入资源 mutation。
- `LoseHPByRatio Floor=true` 执行 floor rounding，且仍不走 direct damage multiplier ledger。
- 新增 `validate_v0_249` 与 `actionability_matrix_v0_249.json`，所有 `fix_now` 项必须修完才能通过。

## 保持 blocked / structural 的项

- `true_damage`：仍缺 admitted executable TBGD true-damage emission/effect 来源。
- `enemy_ai`：等待敌方行动选择与 AI policy admission。
- `complete_actor_profile`：等待 AvatarPromotion / 装备 / 光锥 / 遗器等完整面板来源链。
- `assistant_summon`：等待 assistant/summon actor identity 与 action source admission。
- `bounce_rng`：等待弹射目标 RNG 来源与 per-hit target order admission。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_245 --output-dir /tmp/hsr_v8_regression_v0_245
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_248 --output-dir /tmp/hsr_v8_regression_v0_248
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_249 --output-dir /tmp/hsr_v8_v0_249
git diff --check
```

结果：

- compileall：通过。
- v0_225：`ok=true`。
- v0_227：`ok=true`。
- v0_245：`ok=true`。
- v0_248：`ok=true`。
- v0_249：`ok=true`。
- `git diff --check`：通过。

## 当前进度判断

v0_249 后，之前明确属于“可立即补、不需要等大模块”的资源、condition、heal/shield、SP、HP loss floor 项已经收口。下一阶段可以继续推进剩余大模块，但新增机制仍必须先证明真实来源、负例 state unchanged 和 source audit。
