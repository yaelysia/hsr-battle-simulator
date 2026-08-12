# P9-S8B3C Queue Standalone Ability 迁移验收报告

状态：`accepted`

## 结论

Scheduler 已将准入的 queue standalone ability 交给 B3A 正式目录与 B2 原子任务图执行器。
Queue resolution 继续提供 graph、actor、targets 和 queue identity；正式路径不再构造临时
`ActionDefinitionIR` 或 `ActionCommand`，也不再对子图执行第二次原子提交。

## 五面审查

1. 来源范围：窄来源探针动态选中一个真实角色 queue standalone graph，其 resolution、graph、phase、
   task 与 executable task 账本逐项一致。真实执行诚实阻断于 S8C 的随机命中序列领域，mutation 为 0，
   没有把 fixture 结果冒充真实角色可执行。
2. 生产不变量：queue entry、drain plan、resolution、graph、phase、task、target ledger 和 callback
   生命周期身份在第一条 ability mutation 前闭合。任一 callback、递归或 leaf 失败返回 ability 入口
   状态并清空其 mutation、event、RNG 和成功 settlement；scheduler 只从原 queue 状态发布既有
   terminalization。
3. 正式调用者：`CombatScheduler._try_queue_drain` 是 formal standalone 的唯一生产调用者。B2 候选状态、
   四类结果通道和 graph node projection 只在 scheduler 最外层 `_transition` 发布一次；状态 callback
   文件未修改。
4. Gap 归属：standalone damage/hit source frame 与随机命中序列归 S8C，status callback 归 S8B4，
   跨事件 active graph context 归 S8B5，`external_legacy` 旧 adapter 归 S8B6。以上均未计入本卡成功。
5. 验证独立性：真实来源语义与通用执行 fixture 分栏。Fixture 通过公开 scheduler 入口同时证明
   mutation、event、RNG、settlement、replay 和一次外层提交；递归失败在 effect 已执行后仍无部分通道
   泄漏。B3A/B3B helper 仅在相邻迁移批次内复用，已完成导入现行性核对，本验证器验收后冻结为
   `historical_evidence`，后续阶段不得继续形成 helper 依赖链。

## 验证结果

- 唯一主入口最终结果：`ok=true`，13 项检查符合预期；同一主命令共运行 2 次。
- 最终墙钟：8.27 秒；峰值 RSS：344,580 KiB；evidence：1,556 bytes。
- 验证器：547 个非空行，低于预检修订后的 560 行硬上限。
- 动作 direct、`compileall`、`git diff --check` 通过。
- 完整 `TBGDLowering.build()`：0 次；未运行 B1-B3B 主入口或历史聚合。

## 流程反馈

首次主验证通过后，最终正式调用链审查发现 queue entry 的能力引用与已准入 resolution 尚未逐项
对账；这不是主验证暴露的问题。补充生产身份门和一个公开 scheduler 反例后，同一主命令最终重跑
通过。主入口前另已收口两项设计问题：原 260 行预算没有计入公开 scheduler 集成所需的四类证据面；
standalone damage 原先先进入动作专属准入，迫使验证器伪造完整动作伤害对象。生产代码现先按
invocation kind 拒绝缺失领域上下文。由此新增的流程结论是：跨边界适配器必须在闭合地图中列出
重复身份字段的逐项来源与等值关系，不能只证明每个输入对象分别合法。
