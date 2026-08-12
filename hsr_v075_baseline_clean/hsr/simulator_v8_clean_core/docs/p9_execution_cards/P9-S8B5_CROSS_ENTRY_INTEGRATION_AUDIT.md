# P9-S8B5 跨入口任务图上下文集成执行卡

## 执行配置

- 对应问题：P9-I08；原 P9-S8B 的最终跨入口收口。
- 硬前置：P9-S8B4 已验收并提交检查点。
- 推荐：5.6 Sol / `xhigh` / 普通聚焦。
- 本卡不再创建任务图模型或控制语义，只运输跨入口上下文；旧 IR 拓扑退役归 S8B6。
- 开工只读：本卡、B1-B4 公共结果、EventDispatchSystem 以及 ability/status callback 的同步调用
  边界。禁止通读 B1-B4 历史验证器或扩展到旧拓扑消费者。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 跨入口上下文 | active graph stack、当前 graph/node identity、graph-qualified executed projection |
| 运输边界 | ability -> event -> status callback -> nested ability 的同步调用链 |
| 冲突处理 | 同一图身份不同内容/来源、活动栈重复、投影身份冲突均在下一次 leaf 前 fail-closed |
| 本卡残留审计 | 跨入口链不得重置、重建或伪造图上下文 |
| 后续归属 | 旧字段与构造路径退役归 S8B6；projectile、随机、parallel、barrier 和命中顺序归 S8C |

## 阶段目标

1. 定义并运输一个不可变的任务图调用上下文。同步 event dispatch、状态 callback 和 nested ability
   必须继承同一 active graph stack，不能在跨系统调用时重置或从普通 event payload 重建。
2. 当前图 A 直接再次进入 A、A 调 B 再回 A、同 graph id 对应不同内容或来源，均在下一条正式
   mutation 前 fail-closed；不使用固定递归深度。
3. ability、status callback 和 event 结果统一运输 graph-qualified executed projection。嵌套结果按
   稳定身份合并；同身份不同内容拒绝，失败事务不泄露任何成功投影。
4. 本卡只审计跨入口链中的上下文重置、普通 event payload 重建和投影冲突；全生产旧拓扑字段
   删除及 S8B 聚合账本归 S8B6。

## 本卡明确不做

- 不新增任务图 node kind、loop/branch 语义或领域 leaf handler。
- 不重新设计 Canonical IR、RuleBook、AbilityTaskSystem 或 StatusCallbackSystem。
- 不删除旧 task 拓扑模型/codec/lowering 字段；它们由 S8B6 一次性退役。
- 不实现 projectile、RandomConfig、parallel、barrier、命中与 RNG ledger。
- 不运行 P1-P8/P9 聚合、完整 Canonical lowering 或 B1-B4 历史主入口。

## 允许修改的生产范围

- `systems/event_dispatch.py`
- `systems/ability.py`
- `systems/status_callbacks.py`
- `core/executor.py` 仅限跨入口调用上下文运输
- 必要时共享执行结果模型；不迁移领域派生消费者。

本卡允许跨这些文件运输同一个既定上下文，但不允许新增第二个生产权威。若发现还需改变图模型、
执行选择语义或领域 admission，返回对应 B1-B4 的 `plan_mismatch`，不得在集成卡中补做。

## 验收谓词

```text
active_graph_stack_survives_synchronous_cross_entry_calls=true
direct_and_indirect_graph_cycles_fail_before_mutation=true
executed_projections_are_graph_qualified_and_conflict_checked=true
failed_transactions_publish_no_execution_projection=true
cross_entry_context_reconstruction_count=0
s8c_obligations_remain_precise_and_unexecuted=true
full_canonical_ir_build_count=0
prior_substage_main_rerun_count=0
```

## 验证与止损

- 一个主入口：`validate_p9_s8b5_cross_entry_integration_audit.py`。
- 只保留一个同步跨入口成功链、一个 A→B→A 失败链和一个投影冲突负例。
  不重复 B2 的全部控制结构或 B3/B4 的领域矩阵。
- 生产残留审计可使用 AST/CodeGraph 证明“旧权威不存在”，但跨入口行为必须由正式调用链证明。
- 低成本读取 B1-B4 summary 只核对已验收 fingerprint/状态，不执行其主验证。
- 预算：75 秒、768 MiB、384 KiB evidence、验证器目标不超过 250 非空行。
- 45 分钟内必须形成 active stack 穿过一次 event callback 的可编译纵切；若需要改变 B1/B2 公共
  契约，立即停止并返回规划线程，不能用兼容字段或双轨结果继续。

## 唯一执行清单

- [ ] active graph stack 已跨同步 event/callback/ability 连续运输。
- [ ] 图调用环和投影冲突在 mutation 前 fail-closed。
- [ ] 跨入口链没有上下文重建，S8C 义务未被提前执行。
- [ ] 唯一主验证和资源门通过，提交 `ready_for_review`。
