# v8 v0_250 Extra-Turn Lifecycle Checkpoint

## Summary

v0_250 收束额外回合来源与生命周期边界。额外回合仍不能伪造成自然 AV 回合，也不能靠手写 queue entry 执行。

本阶段已完成：

- `QueueLifecyclePolicyIR`：记录 `OneMore` 生命周期来源、`ActionPhaseEnd` duration tick 证据、额外回合非自然 AV 回合策略。
- `UseSkillOneMore` 来源发现：主线 Ability task 中的 `UseSkillOneMore` 会 lowered 成 `QueueIntentIR -> QueueWindowIR(window_family=extra_turn)`。
- source audit 加固：extra-turn queue mutation 若出现，必须携带可执行 `QueueLifecyclePolicyIR` 链路。
- scheduler queue drain hook：extra-turn child transition 会记录 `extra_turn.begin / extra_turn.end` process event，但只有 admitted queue entry 才能执行。
- v0_250 validation 输出 `extra_turn_source_actionability_matrix_v0_250.json`，区分 source discovery、queue window、lifecycle policy、execution。

## Current Result

当前 TBGD/IR 中发现了额外回合来源，但没有 admitted execution：

- `QueueLifecyclePolicyIR` source discovery：trusted for current scope。
- `QueueWindowIR(window_family=extra_turn)`：已发现真实 `UseSkillOneMore` 来源，但全部 blocked。
- `extra_turn_execution`：blocked。

主要 blocker：

```text
UseSkillOneMore 缺少完整 priority / target / action resolution / lifecycle policy 绑定，不能安全 drain 或执行 child action。
```

因此本阶段没有产生额外回合 runtime mutation，也没有伪造正例。

## Validation

Required commands:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_245 --output-dir /tmp/hsr_v8_regression_v0_245
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_248 --output-dir /tmp/hsr_v8_regression_v0_248
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_249 --output-dir /tmp/hsr_v8_regression_v0_249
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_250 --output-dir /tmp/hsr_v8_v0_250
git diff --check
```

Status after local validation:

```text
compileall: pass
validate_v0_225: ok=True
validate_v0_245: ok=True
validate_v0_248: ok=True
validate_v0_249: ok=True
validate_v0_250: ok=True
git diff --check: pass
```

## Remaining

- Admit `UseSkillOneMore` action/target semantics only after its actor, child skill/action, priority, and lifecycle policy can be proven from Canonical IR.
- Extra-turn duration tick, AV reset/restore, and turn ownership remain blocked unless tied to executable lifecycle policy.
- Enemy AI, full character profile, assistant actor, bounce RNG, and wave system remain outside this checkpoint.
