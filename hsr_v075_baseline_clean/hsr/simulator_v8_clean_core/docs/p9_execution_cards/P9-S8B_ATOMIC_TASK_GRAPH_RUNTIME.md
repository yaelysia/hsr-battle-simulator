# P9-S8B 原子任务图 runtime 执行卡

## 阶段结果

消费已验收的 S8A 类型化目录，将模板参数声明与引用、Predicate、固定/条件/目标循环和 TriggerAbility
materialize 为一套通用任务图事务。普通动作与状态 callback 只能适配同一执行协议；不得各自扩展
第二套控制流语义。

## 完成边界

- template 唯一解析且无环；参数绑定在进入 child 前完成并冻结。
- count 表达式在 typed 上下文求值；条件循环每轮必须满足来源终止依据并产生可证明进展。
- child blocked、缺失或身份错配时，整棵事务的 state、mutation、event、RNG 均回到入口状态。
- TriggerAbility 使用来源图引用和调用栈环检测；不得保留任意固定深度上限。
- 下游 effect 可以按 S9-S16 精确 blocked，但不能被控制流静默跳过。

本卡不实现 projectile、parallel、Wait/barrier 或 RandomConfig；它们只通过 S8A 节点运输到 S8C。

## 通过条件

模板缺失/歧义/环、动态 count 非整数或负数、无进展条件循环、child parent 错配、触发环均在首个
提交前 fail-closed。正式 action 与 status callback 各保留一个最小真实纵切，证明共享事务协议和
原子回滚；不要求其下游领域效果已全部 executable。

## 验证预算

一个聚焦主入口，最多两个实际触达 direct；8 分钟、1 GiB、3 MiB evidence、900 非空行。
禁止完整 Canonical IR、旧 task/event 聚合和验证器手工展开任务图。
