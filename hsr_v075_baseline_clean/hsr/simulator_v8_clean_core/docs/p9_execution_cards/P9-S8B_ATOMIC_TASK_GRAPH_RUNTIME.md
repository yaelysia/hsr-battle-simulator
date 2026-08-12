# P9-S8B 原子任务图事务聚合说明

此文件不再是可直接执行的阶段卡。

原 S8B 同时建立任务图数据权威、实现通用事务执行器、迁移动作系统、迁移状态系统并改造
跨事件上下文。2026-08-12 的子代理试运行证明，这些工作虽然属于同一机制包，但分别改变五个
可独立验收的生产边界。继续单卡实施会造成上下文膨胀、首次审查范围不断扩大，并使执行线程
无法在合理时间内形成可编译、可验收的纵切。

## 严格执行顺序

1. `P9-S8B1_TASK_GRAPH_IR_MATERIALIZATION.md`
2. `P9-S8B2_ATOMIC_EXECUTOR_CORE.md`
3. `P9-S8B3_ABILITY_STANDALONE_MIGRATION.md`
4. `P9-S8B4_STATUS_CALLBACK_MIGRATION.md`
5. `P9-S8B5_CROSS_ENTRY_INTEGRATION_AUDIT.md`
6. `P9-S8B6_LEGACY_TOPOLOGY_RETIREMENT.md`

六张卡全部验收后，才能勾选总计划中的 P9-S8B。任何子卡都不得提前宣称原子任务图事务
已经完整接管正式战斗。

## 边界划分

| 子阶段 | 唯一生产结果 | 明确不承担 |
|---|---|---|
| S8B1 | S8A 来源与正式 task 形成不可变任务图 IR、物化账本及 RuleBook 查询 | runtime 执行 |
| S8B2 | 单一通用执行器完成选中路径的原子事务语义 | 领域系统迁移 |
| S8B3 | 普通动作和队列 standalone ability 只消费共享任务图 | 状态 callback |
| S8B4 | 状态 callback、确定性分支和目标迭代只消费共享任务图 | 跨入口最终聚合 |
| S8B5 | 调用栈、执行投影和跨同步入口上下文统一收口 | 旧拓扑模型退役 |
| S8B6 | 旧 task 拓扑字段、双写及消费者退役，形成 S8B 聚合账本 | S8C 随机与命中时序 |

## 聚合通过条件

- S8A 的完整来源分母在 S8B1 中有且只有一个责任结果；正式物化身份与来源发生身份分离。
- S8B2 的事务执行器自身保证失败后状态不变且 mutation、event、RNG、成功 settlement 为零。
- 动作、standalone ability 和状态 callback 不再拥有 Predicate、循环、模板或子图的第二套解释器。
- `core/` 与 `systems/` 中除共享执行器外，不再读取正式 task 的父子字段决定运行时拓扑。
- 同步跨入口调用持续运输 active graph stack 和 graph-qualified executed projection。
- S8C 的 projectile、parallel、barrier 和随机分支仍诚实 deferred，不被 S8B 伪执行。
- 每张子卡的验证只证明该卡新增权威；不得在最后一张卡重跑前四张卡的完整主入口。

## 共享成本上限

拆卡只拆生产责任，不能把原 S8B 的验证成本复制六次。S8B1-S8B6 共同遵守：

- 五个主入口累计墙钟目标不超过 6 分钟，硬上限 8 分钟。
- 单进程峰值不超过 768 MiB，累计 evidence 不超过 3 MiB。
- 六张卡新增验证代码合计目标不超过 1,650 非空行；达到 1,300 行时先复核是否重复证明。
- S8B1 之后不得重跑前序主入口；后序只消费已验收生产契约和必要的最小 active-contract slice。
- 完整 S8A 来源目录只允许 S8B1 构建一次。后序真实纵切必须在来源读取前按正式入口缩窄，
  不得重新构建完整目录后再筛选。
- 任一子卡超出自身预算时不得借用其他子卡余量；先缩小 evidence 或返回规划线程。

## 失败试运行留档

未验收的中间实现没有进入 Git。清理前的 tracked patch 与新文件快照仅保存在：

```text
/tmp/p9_s8b_tracked_midstate_2026-08-12.patch
/tmp/p9_s8b_untracked_midstate_2026-08-12.tar.gz
```

这些文件只用于追查，不是后续实现模板。新执行线程必须从检查点 `e513b79` 和对应子卡重新开始，
不得直接恢复中间 patch。
