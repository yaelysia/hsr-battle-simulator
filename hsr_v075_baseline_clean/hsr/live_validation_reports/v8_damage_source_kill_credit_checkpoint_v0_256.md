# v8 v0_256 Damage Source Kill Credit Checkpoint

## 本次做到哪里

- 引入 `DamageSourceFrame` 与 `DamageWindowLedger`，把击杀归因从 actor 粗粒度提升到具体伤害来源。
- 主行动同一来源序列击杀后可继续结算后续 hit，但不再重复发 `unit.defeated`。
- 派生/附加/状态/DoT 类新来源遇到本窗口内已死亡目标时，只写 process-only skip record，不产生 HP mutation，不偷击杀收益。
- `unit.defeated` payload 现在包含 `kill_credit_owner_id`、`kill_credit_source_id`、`kill_credit_source_kind`、`damage_sequence_id`。
- v0_255 的真实击杀触发额外回合链保持可用。

## 没做什么

- 没实现完整 DoT 生命周期，只做 source-window 顺序 gate 的基础能力。
- 没把旧 v7 作为 runtime 依赖；旧版只用于行为对照。
- 没补角色专属硬编码或观测数值。

## 当前进度

- 击杀归因基础：当前范围可信。
- 主行动多段死后继续：当前范围可信。
- 派生/附加/DoT 死后跳过：基础 gate 已建立，完整 DoT 系统仍待后续接入真实状态 tick。
- 额外回合击杀触发链：保持 v0_255 当前可信范围。

## 验证

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_253 --output-dir /tmp/hsr_v8_regression_v0_253
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_254 --output-dir /tmp/hsr_v8_regression_v0_254
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_255 --output-dir /tmp/hsr_v8_regression_v0_255
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_256 --output-dir /tmp/hsr_v8_v0_256
git diff --check
```

结果：

- compileall: passed
- validate_v0_225: ok=true
- validate_v0_253: ok=true
- validate_v0_254: ok=true
- validate_v0_255: ok=true
- validate_v0_256: ok=true
- git diff --check: passed
