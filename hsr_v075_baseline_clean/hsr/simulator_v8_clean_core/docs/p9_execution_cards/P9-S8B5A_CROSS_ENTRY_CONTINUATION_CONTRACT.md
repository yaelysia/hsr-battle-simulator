# P9-S8B5A 跨入口 Continuation 与 Projection 契约执行卡

## 执行配置

- 硬前置：P9-S8B4 已验收并提交。
- 推荐：5.6 Sol / `xhigh` / 普通聚焦。
- 唯一权威：S8B2 共享任务图执行器的跨入口子调用契约。
- 精确起点：`TaskGraphExecutionContext`、`TaskGraphHookRequest`、`TaskGraphLeafResult`、
  `_TaskGraphRun._admit_leaf`。
- 最早纵切：外层 leaf 从 hook request 生成 continuation，调用第二个共享执行器并把 child projection
  原子归并回外层结果。

## 闭合地图

| 项目 | 本卡裁决 |
|---|---|
| continuation 来源 | 只能从当前 `TaskGraphHookRequest` 类型化派生，不能从 event payload、日志或 source trace 重建 |
| 活动栈 | 保存父 invocation、当前 graph/node/task 身份和完整 active graph stack；递归不限固定深度 |
| 子结果 | 复用既有 `TaskGraphNodeProjection`，不创建第二套 execution record |
| 合并 | 相同稳定身份且内容完全相同可去重；同身份不同内容阻断整个外层图，四通道与 projection 均不发布 |
| 消费者 | 本卡不迁移 ability/event/status，统一留给 S8B5C |

## 阶段目标

1. 建立递归不可变的 continuation 类型，并提供唯一的 hook-request 派生入口和 child execution context
   构造入口。伪造 parent graph/node/task、活动栈末端不一致、重复活动图或可变输入必须被拒绝。
2. `TaskGraphLeafResult` 增加类型化 child projection 通道；blocked 结果不能携带该通道。
3. 共享执行器归并 child projection，并与本次图自身 projection 做稳定身份冲突检查。直接 A->A、
   间接 A->B->A 均由 active stack 阻断，不使用深度上限。
4. 子调用失败时外层状态及四条正式结果通道全部回到入口，子调用的成功 projection 不得发布；
   外层既有 blocked projection 仍可作为诊断。成功时 projection 保留 graph/node/formal task/path 身份。

## 不做与停止条件

- 不修改 lowering、Canonical IR、RuleBook、ability、event dispatch 或 status callback。
- 不加入线程本地变量、全局栈、可变 collector 或 payload 重建兼容层。
- 若需要领域信息才能定义 continuation，或需要改变 TaskGraphIR 身份，返回 `plan_mismatch`。

## 允许修改

- `systems/task_graph.py` 及必要导出。
- 一个聚焦验证器、报告和规划状态文档。

## 验收谓词与预算

```text
continuation_is_derived_from_typed_hook_request=true
continuation_is_recursively_immutable=true
direct_and_indirect_cycles_fail_before_mutation=true
child_projections_are_graph_qualified=true
projection_identity_conflict_is_atomic=true
blocked_leaf_cannot_leak_child_projection=true
domain_consumers_changed=false
```

- 一个无来源扫描的主入口；一个 A->B 成功链、一个 A->B->A 环和一个 projection 冲突负例。
- `compileall`、主入口、`git diff --check`；不跑 B1-B4 或完整 lowering。
- 预算：10 秒、192 MiB、64 KiB evidence；验证器目标 180、硬上限 230 非空行。

## 唯一执行清单

- [x] continuation 构造与不可变边界完成。
- [x] child projection 原子归并完成。
- [x] 环、冲突和 blocked 泄漏负例通过。
- [x] 唯一主验证和资源门通过，提交 `ready_for_review`。
