# v8 v0_260 Global Kernel Review Checkpoint

## Summary

本次全局审查重点检查“runtime 是否自己猜规则”，尤其是伤害基础值、默认值、source audit 和 trust matrix。

审查结论：公式层已经改成通用接口，但 direct damage 的来源链仍没有完成技能文本/ParamList 绑定。之前验证矩阵把 direct 标为 trusted 是错误的，已修正为 blocked，并明确依赖。

## Findings

- Direct damage 仍有 150 条 executable emission 使用当前范围的显式 attack basis。
- 这些 basis 已不在公式层硬编码，但还不是技能文本/ParamList 证明出来的来源。
- `damage_family_matrix_v0_257` 和 `damage_family_matrix_v0_258` 之前误把 direct 标为 `trusted_for_current_scope`。

## Fixed In This Checkpoint

- 更新 v0_257/v0_258 damage family matrix：
  - direct 若存在 `requires_skill_text_binding=true`，不再标 trusted。
  - direct blocking dependency 明确为 `direct_scaling_basis_requires_skill_text_param_binding`。
  - source counts 增加 `executable_requires_skill_text_binding`。

## Checked

- Monster profile 基础面板 lowering：缺字段会 blocked；后续 `or 0.0` 在 missing guard 之后，未发现静默默认 0 profile executable。
- Heal/Shield formula base：当前由 formula type 显式映射到 `target.max_hp`、`caster.max_hp`、`caster.defense` 等，不是 runtime 猜。
- Manual/scheduler current-scope 标记：用于 route/manual 输入，不是规则来源。
- Resource helper 中无 trace 的旧 helper 基本不在主审计链路调用。

## Remaining Blocking Issue

direct damage 要重新升为 trusted，必须新增：

```text
AvatarSkillConfig / SkillDesc TextMap / ParamList
-> scaling basis admission
-> DamageEmissionIR.scaling_basis_expr
-> DirectDamageFormula
```

文本写攻击力就绑定攻击力，写生命/防御/其他值就绑定对应基础。未绑定的倍率伤害必须继续 blocked。

## Validation

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_audit_v0_225_global_review
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_audit_v0_257_matrix_fix
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_258 --output-dir /tmp/hsr_v8_audit_v0_258_matrix_fix
```

All commands passed.
