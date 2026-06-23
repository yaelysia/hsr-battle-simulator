# v8 v0_253 Extra Action Execution Checkpoint

## 本次做到哪里

- 新增 `ExtraActionPolicyIR`，把真额外回合、受限额外回合、技能/终结技内连续段的动作选择策略从队列窗口里拆出来。
- 真额外回合如果没有固定动作，必须由 route/manual 指定普攻或战技；终结技在额外回合里会被阻断。
- 额外回合仍只通过 queue drain 执行，不走自然回合开始/结束，也不会触发普通状态持续时间扣减。
- `UseSkillOneMore` 进入 `SkillContinuationRunner`，当前只输出 process-only blocked 记录，不会误进额外回合队列。
- 来源审计增加额外行动策略要求：额外回合相关 queue mutation 必须能追到 `QueueLifecyclePolicyIR + ExtraActionPolicyIR`。

## 没做什么

- 当前 Canonical IR 里还没有可执行的真额外回合来源，所以没有造假正例。
- 受限额外回合的角色专属动作限制还没有执行；需要先把状态限制动作映射 admission。
- 技能/终结技内连续段还没有真正执行后续段；需要把 continuation segment 映射到可执行 action/ability。
- 敌方 AI、完整角色面板、assistant actor、波次系统和 bounce RNG 不在本阶段。

## 当前进度

- 额外行动分类与来源边界：已收束。
- 真额外回合执行框架：已接入，但等待真实可执行来源。
- 连续段 runner：已建立 admission 边界，未执行假逻辑。
- 追击/反击优先级：保持高于终结技和额外回合，仍等待更完整的自动触发正例。

## 验证

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_248 --output-dir /tmp/hsr_v8_regression_v0_248
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_249 --output-dir /tmp/hsr_v8_regression_v0_249
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_252 --output-dir /tmp/hsr_v8_regression_v0_252
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_253 --output-dir /tmp/hsr_v8_v0_253
git diff --check
```

当前新增验证：

- `validate_v0_253`: `ok=true`

回归结果：

- `compileall`: pass
- `validate_v0_225`: `ok=true`
- `validate_v0_248`: `ok=true`
- `validate_v0_249`: `ok=true`
- `validate_v0_252`: `ok=true`
- `validate_v0_253`: `ok=true`
- `git diff --check`: pass
