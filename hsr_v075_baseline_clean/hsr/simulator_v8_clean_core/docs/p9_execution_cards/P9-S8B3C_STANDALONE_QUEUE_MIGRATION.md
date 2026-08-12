# P9-S8B3C Queue Standalone Ability 迁移执行卡

## 执行配置

- 硬前置：P9-S8B3B 已验收并提交。
- 推荐：5.6 Sol / `high`。
- 本卡只迁移 scheduler 已准入的 standalone ability。

## 目标与边界

1. queue resolution 继续唯一决定 graph、actor、targets 和 queue identity；scheduler 不造临时
   action definition，也不解释 task 树。
2. `execute_standalone` 查询 B3A 的 `standalone_root` entry，并复用 B3B ability hooks 与 S8B2。
3. queue graph 缺失、身份不一致、递归或 leaf blocker 时，在发布 dequeue/ability 结果前
   fail-closed；既有 queue terminalization 语义保持一致。
4. standalone 的 mutation/event/RNG/settlement/node projection 原样运输到 scheduler 的原子提交，
   不进行第二次 reducer 模拟或从记录反推结果。
5. 非角色 standalone 来源保持外部内容依赖；不因本卡目录不存在而伪装成功。

## 允许修改

- `systems/ability.py`
- `systems/scheduler.py`
- B3B adapter（仅复用，不新增控制语义）
- 一个聚焦验证器和报告

## 验收谓词

```text
queue_standalone_uses_formal_graph_authority=true
queue_cannot_bypass_graph_admission=true
standalone_reuses_action_ability_hooks=true
standalone_root_is_in_active_graph_stack=true
queue_failure_publishes_no_partial_ability_channels=true
temporary_action_definition_created=false
status_callback_behavior_changed=false
```

## 验证预算

- 一个主入口；一个真实 queue standalone 来源加最小失败反例。
- 35 秒、384 MiB、160 KiB evidence、验证器目标 180 非空行。
- 不重跑 B1-B3B 主入口，不构建完整 Canonical IR。

## 唯一执行清单

- [ ] queue standalone 复用正式目录、共享执行器和同一 hook。
- [ ] queue admission、原子失败和结果运输完成。
- [ ] 唯一主验证通过，提交 `ready_for_review`。
