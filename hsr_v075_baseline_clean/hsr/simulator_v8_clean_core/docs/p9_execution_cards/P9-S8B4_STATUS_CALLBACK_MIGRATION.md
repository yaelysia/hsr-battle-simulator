# P9-S8B4 状态 callback 任务图迁移执行卡

## 执行配置

- 对应问题：P9-I08；原 P9-S8B 的 status callback 消费域迁移。
- 硬前置：P9-S8B3A、S8B3B、S8B3C 均已验收并提交检查点。
- 推荐：5.6 Sol / `xhigh` / 普通聚焦。
- 本卡只迁移 status callback 控制流，不改 ability、scheduler 或最终跨入口上下文协议。
- 开工只读：本卡、S8B1/S8B2 公共 API、`StatusCallbackSystem` 正式入口和
  EventDispatchSystem 到 callback 的直接调用链。`systems/status.py` 的旧拓扑派生消费者归 S8B6。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 正式入口 | 已准入状态实例在生命周期/事件窗口触发的 callback |
| 图来源 | S8B1 按状态定义、callback 和 owner 物化的唯一任务图 |
| 控制执行 | 仅 S8B2 通用执行器 |
| 领域 leaf | 现有状态 effect、condition、target、dynamic value 与 modifier 操作适配器 |
| 特殊确定性结构 | Retarget 只返回目标序列；Remodifier/Predicate 只返回选择结果，不执行 child |
| 后续归属 | 跨 event active stack 和跨域投影聚合归 S8B5；随机 callback 归 S8C |

## 阶段目标

1. `StatusCallbackSystem` 从 RuleBook 取得正式状态 callback 图并调用共享执行器；不再按
   `parent_task_id` 搜 root，也不在状态系统内部解释通用 Predicate、循环或 child 列表。
2. Retarget 使用统一 target 结果作为有限目标迭代输入；它不能构造合成 Filter，也不能自行执行
   child。合法空目标、解析失败和来源 blocked 必须保持三种不同结果。
3. Remodifier 及确定性成功/失败选择只返回类型化选择结果；随机权重或 RandomConfig 精确 blocked
   给 S8C，不在本卡使用文件顺序或伪随机替代。
4. 状态 callback 的 leaf 适配器只处理状态领域副作用；不能接收 child runner、递归图或直接提交
   整棵 callback。
5. 任一已选择 child、目标迭代或 leaf blocked 时，整次 callback 返回入口状态，正式 mutation、
   event、RNG 和成功 settlement 为零。
6. 删除或退役 status 域旧 Predicate/container/loop/Retarget/Remodifier child 解释路径；S8C 专属
   随机和 projectile 路径保留精确 blocker，不得误删为非战斗。
7. `_on_create_define_dynamic_values` 等只读旧拓扑的派生消费者统一由 S8B6 随旧字段删除迁移；
   本卡不得以兼容为由扩展到 status 主生命周期。

## 本卡明确不做

- 不修改 ability 或 scheduler 的任务执行语义。
- 不解决跨同步 event 的 active graph stack 运输；若当前 EventDispatchSystem 只能通过修改该协议
  才能完成本卡，返回 `plan_mismatch`，交 S8B5 处理。
- 不实现 RandomConfig、随机权重、projectile、parallel 或 barrier。
- 不提前完成 P9-S10 的完整状态生命周期来源扩面；本卡只迁移已有准入 callback。

## 允许修改的生产范围

- `systems/status_callbacks.py`
- 必要时 `systems/event_dispatch.py` 仅做现有 callback 结果的类型运输，不改变跨入口调用栈语义。

如需修改 ability/core executor/lowering，或两个以上未列出的生产文件，立即返回 `plan_mismatch`。

## 验收谓词

```text
status_callback_control_flow_uses_shared_executor_only=true
status_domain_has_no_second_control_interpreter=true
retarget_returns_targets_but_never_executes_children=true
deterministic_selector_returns_choice_but_never_executes_children=true
empty_targets_blocked_targets_and_resolution_failure_are_distinct=true
selected_callback_failure_is_atomic=true
random_and_timing_nodes_remain_s8c_blocked=true
ability_runtime_behavior_changed=false
```

## 验证与止损

- 一个主入口：`validate_p9_s8b4_status_callback_migration.py`。
- 动态选择一个已有真实状态 callback 来源证明图运输；领域 leaf 若因 S10 后续来源缺口 blocked，
  使用明确 fixture 证明共享上下文，不能汇报为真实状态已 executable。
- 每个新增生产不变量一个最小反例；不复制完整状态生命周期、角色构筑或事件目录。
- 不重跑 B1-B3 主入口。只保留一个当前 callback 正例、一个 Retarget 目标迭代和一个失败原子性链。
- 预算：120 秒、768 MiB、640 KiB evidence、验证器目标不超过 350 非空行。
- 45 分钟内必须使一个已有 status callback root 经共享执行器形成可编译纵切；若被跨事件协议阻断，
  立即提交 `plan_mismatch`，不得在本卡内顺带设计 S8B5。

## 唯一执行清单

- [ ] status callback 已迁移到共享任务图执行器。
- [ ] Retarget、确定性选择和目标迭代职责已与 child 执行分离。
- [ ] status 域第二套控制解释器已移除。
- [ ] 合法空目标和失败原子性经正式入口证明。
- [ ] 唯一主验证和资源门通过，提交 `ready_for_review`。
