# v8 v0_232 Break Damage Lifecycle Checkpoint

## Scope

本阶段继续收束普通韧性与普通弱点击破链路：

- 新增 `BreakStatusEmissionIR`，从普通 break template 内已标准化的 `AddModifier` 生成可审计状态发射源。
- 新增 `BreakSystem`，把 broken 状态、break element、break source、break event、break status、break damage admission 从 `ToughnessSystem` 拆出。
- `ToughnessSystem` 只负责削韧 mutation 和 pending break process record，不再直接写 broken 状态。
- `CombatExecutor` 在削韧归零后调用 `BreakSystem`，同一 transition 内产生 break lifecycle mutation 和 break status mutation。
- `RuntimeSourceAuditor` 增加 break template、break damage emission、break status emission 审计。

## Current Trust

- toughness execution: `trusted_for_current_scope`
- normal break lifecycle: `trusted_for_current_scope`
- break status: `trusted_for_current_scope`
- break damage: `blocked`
- break DoT tick / delay lifecycle: `blocked`

break damage 仍 blocked 的具体原因：

```text
break_damage_percentage_not_executable:postfix_expr:unsupported_postfix_expr
```

当前 TBGD break damage emission 已 lowered，但 `ByBreakDamage` 中的 `BreakDamagePercentage` 仍依赖尚未 admission 的 postfix/formula 输入。本阶段没有用手写公式或观测数值补规则。

## Validation

运行目录：

```text
hsr_v075_baseline_clean/hsr
```

已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_229 --output-dir /tmp/hsr_v8_regression_v0_229
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_231 --output-dir /tmp/hsr_v8_regression_v0_231
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_232 --output-dir /tmp/hsr_v8_v0_232
git diff --check
```

v0_232 checks:

- source audit: passed
- break transition: passed
- break status mutation: passed
- break damage admission: passed as blocked with concrete dependency
- negative cases: passed
- static checks: passed

## Remaining Risks

- 普通 break damage 需要统一 admission `ByBreakDamage` 公式输入和 postfix evaluator 后才能 trusted。
- 击破 DoT 的持续 tick、解除、行动延后仍未实现，不能从当前 break status instance 推断完整游戏生命周期。
- global listener、being-hit listener、per-hit trigger 仍 blocked，不在本阶段伪造。
