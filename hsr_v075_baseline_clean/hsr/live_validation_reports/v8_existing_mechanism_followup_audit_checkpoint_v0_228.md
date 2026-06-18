# v8 Existing Mechanism Follow-up Audit Checkpoint v0_228

## Scope

本检查点继续审查 v8 已有机制，不新增削韧、击破、DoT、super-break 或队列机制。

重点审查：

- runtime mutation 创建点是否仍有来源闸门缺口。
- action preflight / binding / event 来源是否真正阻断状态变化。
- TBGD lowering 和 build/validation 入口是否仍存在默认采样。
- effect registry 是否允许 blocked/audit-only EffectIR 绕过 coverage gate 执行。

## Fixed Issues

- `CombatExecutor` 现在显式把 `ActionAbilityBindingIR` 和 `ActionEventIR` 来源状态纳入 commit gate。
  - 缺失 binding、非 executable binding、无 phase id、未绑定 ability phase graph 的 action 都会 process-only blocked。
  - `TargetPolicy` 改为使用 `ActionEventIR.target_mode`，避免 target resolution 与 action execution plan 使用不同事实来源。

- `TBGDLowering` 默认不再截断 modifier callback。
  - `LoweringLimits.max_callbacks_per_file` 从 `200` 改为 `None`。
  - metadata 增加 `sampled.callbacks`，显式报告 callback 是否采样。

- `tools/build_ir.py` 默认不再截断 ability files。
  - `build_outputs(... max_ability_files=None)`。
  - CLI `--max-ability-files` 默认 `None`，只有显式传参才采样。

- 旧 v0_200、v0_203-v0_209 validation 入口残留的 `max_ability_files=120` 默认已改为 `None`。

- `EffectRegistry.execute()` 增加统一 coverage gate。
  - 非 executable effect 不再进入 handler。
  - blocked reason 保留 payload 级原因，例如 unsupported target alias、unsupported formula、缺失 numeric payload。
  - TriggerSystem 直接调用 registry 时也受该闸门保护。

- `validate_v0_227` 增加 guard：
  - `callbacks_not_sampled`
  - `build_ir_default_not_sampled`
  - blocked heal/shield 负例必须由 registry coverage gate 阻断。

## Validation

在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir /tmp/hsr_v8_current_audit_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_210 --output-dir /tmp/hsr_v8_current_audit_v0_210
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_211 --output-dir /tmp/hsr_v8_current_audit_v0_211
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_214 --output-dir /tmp/hsr_v8_current_audit_v0_214
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_219 --output-dir /tmp/hsr_v8_current_audit_v0_219
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_221 --output-dir /tmp/hsr_v8_current_audit_v0_221
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_current_audit_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_current_audit_v0_227
git diff --check
```

结果：全部通过。

## Remaining Boundaries

- 这不是完整机制证明。true damage、queue、global listener、being-hit listener、per-hit trigger、DoT、break、super-break 仍未实现。
- trigger window 仍是当前范围的结构化骨架，不等价完整游戏事件系统。
- AOE/blast 数值仍保持 structural-only 标记，不能当作最终伤害一致性证明。
