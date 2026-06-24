# v8 v0_259 Damage Scaling Basis Interface Checkpoint

## Summary

本次修复把“倍率要乘什么基础值”从伤害公式层移出，改成显式输入。

公式层现在只做一件事：拿到已经证明的基础值和倍率后计算伤害。它不会再自己决定使用攻击、生命、防御或其他数值。

## Changed

- 新增通用 scaling basis 解析接口，支持显式声明攻击者或目标的基础面板/资源值。
- direct damage 不再在公式层硬编码 `attacker.attack`。
- DoT 的 `DamagePercentage` 路径只有在同时提供明确基础值声明时才可计算；缺声明继续 blocked。
- v0_258 验证新增公式能力检查，证明倍率路径可以使用非攻击基础值。

## Not Changed

- 没有把角色技能文本解析为可执行规则。
- 没有把任意 `DamagePercentage` 自动等同为攻击力倍率。
- 当前已有 direct damage 仍保留当前范围的显式基础值输入，后续角色文本/参数绑定接入后应替换为真实文本来源。

## Validation

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_258 --output-dir /tmp/hsr_v8_v0_258_scaling_basis
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225_scaling_basis
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_207 --output-dir /tmp/hsr_v8_regression_v0_207_scaling_basis
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_249 --output-dir /tmp/hsr_v8_regression_v0_249_scaling_basis
git diff --check
```

All commands passed.

## Remaining Work

- 建立技能文本/ParamList 到 scaling basis 的来源绑定。
- 角色机制接入时，按文本中写明的基础值和倍率填入 scaling basis。
- 任何未绑定基础值的倍率公式必须继续 blocked，不能由 runtime 猜。
