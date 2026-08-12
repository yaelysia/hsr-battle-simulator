# P9-S8 能力图控制流与时序聚合说明

此文件不再是可执行阶段卡。实时来源核对证明原 S8 同时改变三个可独立验收的权威边界，
继续单卡施工会让来源完整性、任务图事务和命中/RNG 正确性相互遮蔽。

严格执行顺序：

1. `P9-S8A_CONTROL_FLOW_SOURCE_CONTRACT.md`
2. `P9-S8B1_TASK_GRAPH_IR_MATERIALIZATION.md`
3. `P9-S8B2_ATOMIC_EXECUTOR_CORE.md`
4. `P9-S8B3_ABILITY_STANDALONE_MIGRATION.md`
5. `P9-S8B4_STATUS_CALLBACK_MIGRATION.md`
6. `P9-S8B5_CROSS_ENTRY_INTEGRATION_AUDIT.md`
7. `P9-S8B6_LEGACY_TOPOLOGY_RETIREMENT.md`
8. `P9-S8C_HIT_BARRIER_RANDOM_SEQUENCE.md`

S8A-S8C 全部验收前，总计划中的控制流机制包不得宣称完成；后序 S9 也不得把未完成的任务图
运输当成事件生产者正例。

## 拆分依据

- S8A 的权威输入是当前完整角色 ability 来源、结构化 scope 记录和对象内全部同级字段；输出是
  compiler 侧类型化责任目录，不改变 runtime。
- S8B1-S8B6 依次建立任务图物化权威、领域中立原子执行器、ability 消费、status callback 消费、
  跨入口上下文和旧拓扑退役；`P9-S8B_ATOMIC_TASK_GRAPH_RUNTIME.md` 只保留聚合说明，不再直接执行。
- S8C 的权威输入是 S8B 的事务边界与统一 RNG ledger；输出是命中身份、模拟 barrier、parallel
  合并和随机分支的确定性顺序。

旧的 `31 / 8,651` 只作历史背景，不能作为完成门。每一子阶段必须从实时完整来源重建分母，
并分别报告直接来源节点和仅为分支闭合保留的祖先上下文，禁止相加冒充待执行节点数。
