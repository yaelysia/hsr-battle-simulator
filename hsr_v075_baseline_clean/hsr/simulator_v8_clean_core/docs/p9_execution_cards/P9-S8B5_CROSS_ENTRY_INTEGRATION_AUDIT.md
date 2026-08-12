# P9-S8B5 跨入口任务图上下文集成聚合说明

## 为什么拆分

修改前代码预检确认，原 S8B5 同时要求修改三种可独立验收的权威：

1. S8B2 共享执行器尚无跨入口 continuation 与子调用 projection 通道。
2. 状态 callback 已有 8 条真实 TriggerAbility 关联，但目标 phase 仍被分类为未绑定定义，正式目录
   没有对应 nested entry。
3. ability -> event -> status callback 的同步调用没有运输 active graph stack，也没有把嵌套 projection
   返回外层原子执行器。

把三者放在一张卡会同时改变共享执行契约、lowering 调用角色和三个消费域，违反当前阶段复杂度门。
S8B5 因此改为聚合项，不直接施工。

## 唯一执行顺序

1. `P9-S8B5A_CROSS_ENTRY_CONTINUATION_CONTRACT.md`
2. `P9-S8B5B_STATUS_TRIGGER_ABILITY_CATALOG_ADMISSION.md`
3. `P9-S8B5C_CROSS_ENTRY_RUNTIME_TRANSPORT.md`

只有三张子卡均验收并提交检查点后，才允许勾选总计划中的 P9-S8B5。

## 聚合完成条件

- 共享执行器拥有不可变 continuation 和原子 child projection 合并契约。
- 状态 TriggerAbility 的真实目标定义进入 nested formal catalog，但 blocked callback/task 不因此
  被提升为 gameplay executable。
- ability、event dispatch、status callback 只运输上述既定契约，直接和间接图环在首条 mutation
  前阻断，失败事务不泄露成功 projection。
- 旧 task 拓扑退役仍留给 S8B6；随机、命中、parallel 和 barrier 仍留给 S8C。
