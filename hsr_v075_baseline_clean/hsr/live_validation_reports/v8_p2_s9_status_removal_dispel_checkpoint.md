# v8 P2-S9 状态移除与驱散检查点

日期：2026-07-05

## 本步完成

- 新增 `validate_p2_s9_status_removal_dispel`。
- 验证 `RemoveModifier`、`RemoveSelfModifier`、确定性 `DispelStatus(Order=LastAdded)`。
- 验证同名多实例移除只删除选中的 `instance_id`，不会把同名不同来源实例全部误删。
- 验证驱散按最后添加顺序选择候选，且候选、跳过原因、选中实例都写入审计 trace。
- 验证不可驱散、无候选、缺失状态均为 process-only / blocked，不产生 mutation。
- 验证动态数量驱散：缺 binding blocked；绑定为 1 可执行；绑定为 2 当前阶段 blocked。

## 移除 / 驱散矩阵

```text
remove_modifier executable source_count=12288
remove_self_modifier executable source_count=3313
deterministic_last_added_dispel executable source_count=376
dynamic_count_dispel executable source_count=269
fixed_count_gt_one_dispel boundary_only source_count=11
blocked_remove_dispel_sources boundary_only source_count=6626
random_dispel source_absent_not_required source_count=0
```

## 关键断言

```text
source_audit=True
replay=True
settlement_traceability=True
same_name_old_removed=True
same_name_new_survives=True
last_added_selected_instance=dispel:new
undispellable_skipped=True
no_candidate_process_only=True
dynamic_count_bound_1_executable=True
dynamic_count_bound_2_blocked=True
```

随机驱散当前数据库没有 `Order=Random` 来源，本步只记录 source gap，不合成随机正例。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s9_status_removal_dispel --output-dir /tmp/hsr_v8_p2_s9_status_removal_dispel
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s9_status_removal_dispel validation ok=True
```

## 剩余范围

- S9 完成当前状态离场、驱散候选、不可驱散和动态数量边界验证。
- count > 1 驱散当前阶段保持 blocked；需要完整多数量语义时再单独扩大 admission 和验证。
- S10 继续覆盖状态回调事件族和 callback task opcode。
