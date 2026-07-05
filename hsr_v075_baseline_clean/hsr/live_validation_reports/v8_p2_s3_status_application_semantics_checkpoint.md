# v8 P2-S3 状态施加语义检查点

日期：2026-07-05

## 本步完成

- 新增 `validate_p2_s3_status_application_semantics`。
- 接通同源重复施加且 modifier definition 明确 `Stacking=Replace` 的替换语义。
- 验证首次施加、叠层封顶、刷新、只叠层不刷新、叠层减少、叠层到 0 移除、替换、不同来源同名状态阻断、施加失败 process record。
- 验证每种成功 mutation 都能 replay 和 source audit。
- 验证不同来源同名状态仍明确 blocked，不默认替换、刷新、叠层或共存。

## 关键事实

替换正例按结构化谓词选择：

```text
EffectIR opcode=AddModifier
modifier_definition.stacking=Replace
target_alias=ModifierOwnerEntity
chance=missing
```

关键断言：

```text
operation_replace=True
replace_record_present=True
same_instance_replaced=True
status_id_not_duplicated=True
source_trace_has_modifier_definition=True
source_audit=True
replay=True
```

边界与缺口：

```text
different_source_blocked_reason=coexist_unsupported:different_source_same_status
failed_apply_reason=unsupported_or_missing_target_alias:ParamEntity
stack_refresh_status=coverage_gap
```

不同来源同名状态和失败施加均无 mutation，且 state unchanged。当前矩阵没有选出真实同源叠层且刷新持续时间正例，因此本步只记录 coverage gap，不构造 synthetic 正例。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s3_status_application_semantics --output-dir /tmp/hsr_v8_p2_s3_status_application_semantics
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s3_status_application_semantics validation ok=True
```

## 剩余范围

- S3 完成施加语义的可执行和阻断边界。
- S4 继续覆盖持续时间、tick、过期和跨波清理语义。
