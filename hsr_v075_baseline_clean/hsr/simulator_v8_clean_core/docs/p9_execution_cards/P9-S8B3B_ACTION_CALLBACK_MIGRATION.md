# P9-S8B3B 普通角色动作任务图迁移执行卡

## 执行配置

- 硬前置：P9-S8B3A 已验收并提交。
- 推荐：5.6 Sol / `high`。
- 本卡只迁移普通角色 action callback；不处理 queue standalone 或 status callback。

## 目标与边界

1. `AbilityTaskSystem.execute_callback` 对 `action_root` 只查询 B3A formal catalog 并调用 S8B2；
   `nested_only` 不作为并列 root 执行。
2. ability hook 只执行一个 leaf 的 effect/damage/summon/condition/target/numeric 领域职责，不持有
   child runner，不读取旧父子字段，不返回候选状态。
3. TriggerAbility graph hook 根据 B3A 的类型化 phase/standalone 定义关联返回唯一嵌套图；活动图
   栈由 S8B2 连续运输，直接或间接递归 fail-closed。
4. 角色正式 phase 缺图、选中 deferred 节点、leaf blocker 或重复通道身份时，整个 callback
   原子失败且不回退旧解释器。
5. `external_legacy` 内容域行为保持不变并列入外部依赖账本；不得计入角色通过。

## 允许修改

- `systems/ability.py`
- 必要时一个只承载 ability hook 的 `systems/ability_task_graph_adapter.py`
- `core/executor.py` 仅结果运输
- 一个聚焦验证器和报告

## 验收谓词

```text
character_action_uses_shared_executor_only=true
nested_phase_not_executed_as_parallel_root=true
ability_leaf_has_no_child_runner=true
character_graph_missing_does_not_fallback=true
selected_path_failure_is_atomic=true
active_graph_cycle_is_blocked=true
external_legacy_behavior_changed=false
status_callback_behavior_changed=false
```

## 验证预算

- 一个主入口；真实 root+nested 来源与最小领域 fixture 分栏取证。
- 45 秒、448 MiB、192 KiB evidence、验证器目标 300、硬上限 360 非空行。
- 开工后的 70% 范围复核确认：真实来源必须独立证明“有图但所选后续域未准入时不回退”，显式
  validation fixture 必须独立证明“嵌套只执行一次及中途失败整体回滚”。两类证据不能互相冒充，
  因此修订原 220 行估算；不得导入历史验证器 helper，也不得再增加并列入口。
- 不重跑 B1/B2/B3A 主入口，不构建完整 Canonical IR。

## 唯一执行清单

- [x] 普通角色动作只消费共享任务图。
- [x] 嵌套调用、失败原子性和角色无回退完成。
- [x] 外部内容域边界保持诚实。
- [x] 唯一主验证通过并完成验收。
