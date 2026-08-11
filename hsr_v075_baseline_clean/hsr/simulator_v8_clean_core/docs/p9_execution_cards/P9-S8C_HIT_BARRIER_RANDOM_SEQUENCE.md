# P9-S8C 命中、barrier、parallel 与随机顺序执行卡

## 阶段结果

在 S8B 原子事务上闭合 projectile 命中身份、目标迭代、真正影响结算窗口的 barrier、parallel
确定性合并和 RandomConfig。所有 gameplay 随机消费统一 RNG ledger；物理飞行和演出等待退役。

## 完成边界

- projectile 只产生来源支持的有序 hit/target 身份，不模拟坐标、速度、碰撞或特效。
- 纯动画/帧/timeline wait 为 process-only；携带 settlement/window 语义的字段形成 typed barrier，
  并由对应 S9/S11 生产者消费。
- parallel 分支先形成稳定计划，再按来源定义合并；不能依赖文件或字典顺序。
- RandomConfig 完整列候选和权重，使用稳定 choice identity；过期 choice、候选变化和 replay 篡改拒绝。
- 任一命中或分支 blocked 时遵守 S8B 的事务策略，不能保留半段 mutation/settlement。

本卡完成后回验 S5D2 的真实动作 transaction/replay 条件；不提前实现 S9-S16 的领域效果。

## 验证预算

一个聚焦主入口，最多两个实际触达 direct；8 分钟、1 GiB、4 MiB evidence、900 非空行。
正式 action 入口至少覆盖有序多 hit 和 RandomConfig，各自只保留一个最小真实来源纵切。
