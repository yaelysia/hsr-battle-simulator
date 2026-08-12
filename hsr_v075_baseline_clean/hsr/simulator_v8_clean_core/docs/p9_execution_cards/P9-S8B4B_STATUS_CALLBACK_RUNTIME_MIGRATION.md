# P9-S8B4B 状态 callback runtime 迁移执行卡

## 执行配置

- 对应问题：P9-I08；S8B4 的唯一 runtime 消费域。
- 硬前置：P9-S8B4A 已验收并提交检查点。
- 推荐：5.6 Sol / `xhigh` / 普通聚焦。
- 本卡只消费 S8B4A 已安装目录，不再改变来源范围、任务身份或 materializer。
- 精确起点：`StatusCallbackSystem._execute_callback`、`_execute_task`、
  `EventDispatchSystem._dispatch_listener_event` 的直接 callback 调用。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 正式入口 | 已准入状态实例触发且 callback 属于 S8B4A 角色正式目录 |
| 控制执行 | 仅 S8B2 `TaskGraphExecutor` |
| 领域 leaf | 从旧 `_execute_task` 中抽出的无 child-runner 叶节点适配器 |
| 条件与目标 | 既有统一 condition/target 生产入口，只返回类型化结果 |
| 无任务 callback | 来源 task 账本为空时形成无 mutation 的 callback 结果，不调用图执行器 |
| 外部内容 | 不属于角色正式目录的 callback 走明确外部内容 legacy 路径并列账，不得静默 fallback |
| 后续归属 | 跨 event active stack 归 S8B5；旧拓扑字段退役归 S8B6；随机/时序归 S8C |

## 阶段目标

1. 角色正式 callback 必须通过 callback/entry/graph/status instance 四方身份核对后调用共享执行器；
   任一不一致在第一条 mutation 前 blocked，不得回退旧解释器。
2. 旧 `_execute_task` 中领域 leaf 与 child/control 解释分离。正式 leaf hook 不得接收 child runner、
   parent map 或递归 callback；Predicate、loop、template、Retarget 和 selector 的 child 只由共享执行器
   调度。
3. Retarget 只返回有限、有序目标。合法空目标、来源 blocked 和解析失败保持不同结果；Remodifier
   及确定性分支只返回选择，不执行 child。随机选择精确 blocked 给 S8C。
4. 任一被选择节点 blocked 时，整次 callback 回到入口状态，mutation、event、RNG 和成功
   settlement 均为空。多个 callback 的事件派发原子边界不在本卡扩大，跨入口合并归 S8B5。
5. EventDispatch、属性区间 watcher、击破和 scheduler 四类正式调用者均通过同一 callback API；
   不得让其中某个入口绕过目录身份或继续读取旧父子拓扑。
6. 角色正式范围内旧 Predicate/container/loop/Retarget/Remodifier child 解释分支为零；外部内容
   legacy 使用点必须可由来源范围判定并进入 S8B6 账本。

## 不得自行决定

- 不修改 ability、scheduler 业务语义或跨事件 active stack 协议。
- 不实现 RandomConfig、随机权重、projectile、parallel、barrier 或完整 P9-S10 状态来源扩面。
- 不用 callback 是否“当前能跑通”反向定义正式目录，不用错误字符串选择 fallback。
- 不把验证 fixture 冒充真实角色 callback executable。

## 允许修改

- `systems/status_callbacks.py`
- 必要时 `systems/event_dispatch.py`、`systems/ability_property_watchers.py` 仅做既有结果类型运输
- 本卡聚焦验证器、报告和规划状态文档

若需修改 materializer/lowering、core executor，或改变两个以上独立领域 leaf 语义，返回
`plan_mismatch`。

## 验收谓词

```text
character_status_callback_uses_shared_executor_only=true
formal_status_leaf_has_no_child_runner=true
retarget_and_deterministic_selection_do_not_execute_children=true
empty_targets_blocked_targets_and_resolution_failure_are_distinct=true
selected_callback_failure_is_atomic=true
all_formal_callers_share_one_admission_boundary=true
external_content_legacy_path_is_explicit_and_bounded=true
random_and_timing_nodes_remain_s8c_blocked=true
```

## 验证与止损

- 一个主入口：`validate_p9_s8b4b_status_callback_runtime_migration.py`。
- 只保留一个真实图运输、一个最小领域 leaf、一个 Retarget/分支和一个失败原子性链；真实内容若
  被后续领域阻断，只证明图运输，不宣称完整角色 executable。
- 不重跑 B1-B4A 主入口；只运行 compileall、当前主入口、最多一个直接 callback 入口探针及 diff。
- 预算：120 秒、768 MiB、384 KiB evidence；验证器目标不超过 360 非空行，硬上限 430。
- 若 45 分钟内仍需修改来源目录，或正式迁移暴露三个以上独立 leaf 语义缺口，暂停并再次拆卡。

## 唯一执行清单

- [ ] 角色正式 callback 只通过共享执行器执行控制流。
- [ ] leaf、条件、目标和 child 调度职责已分离。
- [ ] 所有正式调用者共享同一 admission，失败原子且外部 legacy 有界。
- [ ] 唯一主验证和资源门通过，提交 `ready_for_review`。
