# P9-S8B5C 跨入口 Runtime 运输执行卡

## 执行配置

- 硬前置：P9-S8B5A、S8B5B 均验收并提交。
- 推荐：5.6 Sol / `xhigh` / Goal。
- 唯一工作：把 A 已确立的 continuation/projection 契约穿过 ability -> event -> status callback，并消费
  B 已安装的状态 TriggerAbility nested graph；不新增模型或控制语义。
- 精确起点：`AbilityTaskSystem._execute_formal_leaf`、`EventDispatchSystem.dispatch_event`、
  `StatusCallbackSystem._execute_formal_callback` 与 status graph hook。
- 最早纵切：一个正式 ability leaf 同步派发事件，状态 callback 继承 active stack 并返回 child
  projection，外层共享执行器发布完整有序 projection。

## 阶段目标

1. ability leaf 从 hook request 派生 continuation；event dispatcher 只能透传该类型，所有同步递归事件
   和 watcher 路径保持同一父上下文，禁止 payload 重建或全局隐式栈。
2. 状态 callback 使用 continuation 的 active stack 创建 child execution context；TriggerAbility graph
   hook 只按类型化 phase/standalone 引用选择唯一 nested graph。
3. status、event、ability 结果类型化运输 child projection。外层共享执行器统一合并；任一层失败时
   state 与四通道及全部成功 projection 原子回滚。
4. A->event->status->A 与 A->event->status->B->A 在下一条 leaf mutation 前阻断；同 projection 身份
   冲突也 fail-closed。没有 continuation 的普通外部 legacy 入口保持既有行为，但不能进入角色正式图。
5. 真实来源与通用运输分栏取证：若当前事件/随机/生命周期 blocker 阻止完整角色链，只能汇报
   component executable 与唯一回验条件，不得伪称真实角色端到端已执行。

## 不做与停止条件

- 不改变 TaskGraphIR、共享执行器契约、lowering 调用角色或领域 leaf 规则。
- 不实现 RandomConfig、命中序列、Remodifier、parallel、barrier 或 S9/S10 事件和状态准入。
- 若需要修改 A/B 权威或两个以上额外生产域，返回 `plan_mismatch`。

## 允许修改

- `systems/ability.py`
- `systems/event_dispatch.py`
- `systems/status_callbacks.py`
- `systems/ability_property_watchers.py` 仅运输同一 continuation/projection；该正式 watcher 调用点已在
  修改前调用链核对中确认，不能绕过后留下上下文断点
- 必要时 `core/executor.py` 仅做既有结果运输
- 一个聚焦验证器、报告和规划状态文档

## 验收谓词与预算

```text
active_graph_stack_survives_synchronous_cross_entry_calls=true
direct_and_indirect_graph_cycles_fail_before_mutation=true
executed_projections_are_graph_qualified_and_conflict_checked=true
failed_transactions_publish_no_successful_child_projection=true
cross_entry_context_reconstruction_count=0
status_trigger_ability_uses_typed_nested_graph=true
s8c_s9_s10_obligations_remain_precise_and_unexecuted=true
```

- 一个同步成功组件链、一个环、一个 projection 冲突；真实来源只做链接/阻断审计。
- `compileall`、唯一主入口、最多一个现行 direct、`git diff --check`；不重跑 A/B/B3/B4 主入口。
- 预算：45 秒、512 MiB、160 KiB evidence；验证器目标 360、硬上限 420 非空行。修改前调用链
  核对补入了原卡遗漏的正式 watcher 入口及其原子失败反例，因此只调整代码规模预算；入口数、
  运行资源和 evidence 预算不变，禁止拆文件绕过上限。

## 唯一执行清单

- [x] continuation 穿过 ability/event/status 全链。
- [x] status TriggerAbility 只消费类型化 nested graph。
- [x] child projection 运输、冲突与失败原子性闭合。
- [x] 真实来源与组件证据边界诚实。
- [x] 唯一主验证和资源门通过，提交 `ready_for_review`。
