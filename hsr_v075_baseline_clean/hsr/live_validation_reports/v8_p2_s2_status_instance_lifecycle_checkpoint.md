# v8 P2-S2 状态实例、来源、默认生命周期检查点

日期：2026-07-05

## 本步完成

- 新增 `validate_p2_s2_status_instance_lifecycle`。
- 验证状态实例保留 owner、caster、source、status definition、层数、持续时间、refresh/stack policy、可审计 source trace、状态分类和 source stack key。
- 验证同源重复施加普通状态按真实来源刷新持续时间，不新增重复 status id，不默认叠层。
- 验证同名不同来源当前明确 `coexist_blocked`，不会误删、误刷新、误叠层或伪造共存。
- 验证缺目标、缺 modifier definition 的负例 blocked/process-only/state unchanged。

## 关键事实

本步正例按结构化谓词选择：

```text
EffectIR opcode=AddModifier
refresh_admission.source_kind=modifier_definition_stacking
lifetime=fixed 2.0
target_alias=Caster
```

关键断言：

```text
operation_refresh=True
same_instance_id=True
same_source_stack_key=True
ordinary_reapply_not_stacked=True
remaining_duration_refreshed=True
refresh_record_present=True
source_audit=True
replay=True
```

负例：

```text
different_source_blocked_reason=coexist_unsupported:different_source_same_status
missing_target_reason=unsupported_or_missing_target_alias:ParamEntity
missing_definition_reason=unknown modifier definition 'validation_missing_modifier_definition'
```

这些负例均无 mutation，且 state unchanged。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s2_status_instance_lifecycle --output-dir /tmp/hsr_v8_p2_s2_status_instance_lifecycle
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s2_status_instance_lifecycle validation ok=True
```

## 剩余范围

- S2 只收紧状态实例身份和默认生命周期边界。
- S3 继续覆盖首次施加、叠层、刷新、减少层数、到 0 移除、替换/共存边界和 per-operation settlement。
