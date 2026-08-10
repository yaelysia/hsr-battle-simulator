# P9-S5D2 弹射、动态目标接线与 S5 聚合执行卡

## 执行配置

- 对应问题：P9-I06 剩余动作消费与原 S5 聚合。
- 硬前置：S5D1 已验收；若检查点暂不可写，必须有 accepted 报告且差量未漂移。
- 推荐：5.6 Sol / `max` / 普通聚焦。
- 本卡迁移共享 executor/RNG/replay 边界，不能交给低成本模型自行裁决语义。

## 阶段目标

完成后，动作弹射的每次随机命中复用 S5D1 sampler，动作选择上下文仍由 S5C2 唯一控制。
随机目标事件、伤害/效果 mutation、settlement、来源审计和 replay 在同一 action transaction 中
原子提交。随后从 S5A 权威来源视图重新归并 S5A-S5D2，诚实判定目标领域是否完成。

本卡不得把 `IsDynamicTarget=true` 解释成统一“随机选目标”。该字段只声明效果目标可能在动作
执行期间重新计算。只有能力图中存在已类型化、来源真实且被正式消费者调用的目标生产者，
对应动作才能消除动态目标 blocker。尚未由能力控制流调用的生产者归 S8，不得在 S5D2 伪造。

## 闭合地图

- 权威分母：S5A 全部当前目标记录；S5C1 当前动作目标目录；S5A 中三类随机来源；当前动作
  hit profile/bounce policy；能力图内真实动态目标节点。
- 生产权威：S5C2 负责初始选择；S5D1 负责随机 draw；executor 只消费 sealed 选择上下文和
  source-backed hit plan。
- 正式调用者：`CombatExecutor` 弹射路径以及真正消费 `RandomSelectInTargetList` 的能力任务入口。
- 聚合输出：每条来源唯一归属为 executable、non-gameplay、真实 source gap 或精确后续 owner。

## 已确定语义

### 弹射与独立调用

- 一次弹射 hit 是一次 `single` draw；invocation 身份绑定动作、来源任务/命中、hit index 和当前池。
- 不同 hit 是独立调用，可以再次命中先前目标；只有真实 bounce policy 明确“优先未命中”时，
  remaining 候选按该策略变化，但池耗尽后是否可重复必须来自 policy。
- 已 defeated、removed、unselectable 或关系失效的单位必须在 draw 前由正式候选入口排除。
- 同一 request 的重复 key、错误 key、过期池或非法目标必须在对应选择被消费时 blocked。
  弹射后续候选可能依赖前一击形成的候选状态，因此允许 executor 在原子事务内部按正式顺序
  计算不可见的候选 mutation；所有 draw 与执行节点完整前，任何候选结果都不得对外发布。

### 原子性与 replay

- explicit ledger 未解决完所有 action 所需 draw 时，action 的业务 mutation、业务 event、RNG、
  可执行 settlement 和 committed state 全部不提交；只允许返回 typed request 与 planned-only
  诊断，不得把候选状态或候选结算伪装成已执行结果。
- 全部解决后，RNG events 按 hit 顺序与 action transaction 同时提交；settlement 原生记录选择
  identity 和来源，不从日志反推。
- replay 重新计算候选池、draw identity、目标顺序和 action mutation。删改/交换 event、来源、
  候选 fingerprint、selected target 或 hit index 必须失败。

### 动态目标边界

- bounce 动作的逐 hit sampler 是一种正式动态目标生产者。
- 普通动作只有在已准入能力图任务真正解析并消费类型化目标节点时才视为 dynamic target 已闭合。
- 仅有配置标记、仅有 raw 节点或仅有验证 fixture 都不能移除 admission blocker。
- 目标 evaluator 已实现但能力控制流尚未调用的记录，精确归属 S8，不计为 S5 实现缺失。

## S5 聚合完成定义

S5D2 必须从完整来源责任集合推导结果，不能以旧错误字符串消失或当前 handler 列表反推：

1. S5A 的每条目标来源和 S5C1 的每条动作契约都出现一次且只出现一次。
2. 目标 IR、实体关系、动作 query/submit/context、随机 sampler 和动作消费五段契约可串联。
3. S5 自身的 lowering、admission、implementation 和 validation gap 为零。
4. predicate、能力控制流、事件生产者、body-part 或新命途依赖有精确阶段/范围归属及代表来源。
5. `blocked` 账本计数一致只证明没有漏记；任何未归属 gameplay 项都会使聚合失败。

## 验收标准

| 目标 | 通过条件 | 权威证据 |
|---|---|---|
| 弹射接线 | 多 hit 使用共享 sampler，独立 invocation 可重复且策略来源真实 | formal bounce slice |
| 提交原子性 | 未完整选择零业务输出；完成后 RNG/action/settlement 同时出现 | atomic transaction slice |
| replay | 候选、顺序、来源、事件和 mutation 可重算，任一篡改被拒绝 | replay mutation slice |
| 动态目标诚实 | 仅正式生产者闭合；控制流 gap 精确交给 S8 | dynamic producer ledger |
| S5 完整性 | 五段契约与全部来源唯一归属，S5 自有四类 gap 为零 | S5 aggregate |
| 通用性 | 不存在角色/技能/固定 ID handler 或第二套随机账本 | static and CodeGraph audit |

## 必须覆盖的最小负例

- 两个 hit 错误共享 invocation/remaining，导致第二次不能重复命中。
- 第一 draw 已产生 mutation/event，而第二 draw 缺 choice。
- 候选在查询后死亡、离场、变为不可选或关系变化仍接受旧 choice。
- 交换 hit event、改 selected target、source、pool fingerprint 或 hit index 后 replay 仍通过。
- 只有 `IsDynamicTarget` 标记、没有正式 producer 的动作被准入。
- S5 aggregate 漏掉未类型化来源，或把 S6/S8/S9/S17 gap 计为 executable。

## 明确不做与停止条件

- 不实现 S8 的通用 Retarget 任务控制流、循环或模板调用；只迁移当前已有正式生产入口。
- 不实现概率条件、随机分支和随机数值。
- 不为怪物 AI 选择目标；规则候选仍可供外部推演器选择。
- 不重跑 S5A-S5D1 主验证，只消费 accepted summary 和轻量顶层范围门。
- 若 executor 需要先**发布**部分 action 才能知道候选，或现有原子提交无法在私有候选状态中
  表达多步选择，暂停并返回架构影响，不在验证器手工模拟提交顺序。

## 拟改范围

- `systems/target.py`：弹射迁移到共享 sampler。
- `core/executor.py`、原子提交/settlement/replay 实际消费者：仅做目标 RNG 链迁移。
- 能力任务入口：只接已有类型化 `RandomSelectInTargetList` 或动态目标 producer。
- 仅为完成来源责任映射最小修改 lowering/IR。
- 新增唯一验证器和仓库级报告。

## 验证预算

- 顺序：`compileall -> 秒级原子失败切片 -> 唯一主入口 -> 最多一个 RNG direct -> git diff --check`。
- 主入口 5 分钟，累计 8 分钟，RSS 768 MiB，evidence 1.5 MiB，验证器 620 非空行。
- 完整 Canonical IR 构建 0；S5 聚合只读一次目标窄投影及前序 accepted summary。

## 唯一执行清单

- [x] 弹射/独立随机命中复用 S5D1 sampler 和真实 policy。
- [ ] 多 draw action 在首次 mutation 前完成选择校验并原子提交。
- [ ] settlement、来源审计和 replay 与正式 transaction 同链闭合。
- [x] 动态目标只按真实生产者准入，S8 依赖没有被伪造完成。
- [x] 完整来源责任集合唯一归属，S5 自有四类 gap 为零。
- [x] 机制主验证、必要 direct、资源和通用性审计通过。

## 2026-08-06 验收裁决

当前状态为 `mechanism_accepted_external_e2e_dependency`，不是阶段完成：

- 真实弹射策略、每段随机来源、候选生命周期、共享随机计划和逐段 replay 已闭合。
- S5 权威目标分母与动作目标分母已唯一归属，S5 自有 gap 为零。
- 当前可选真实动作仍由 `IncludeTaskListTemplate`、`TriggerEffect` 等后续能力图任务阻断；
  生产入口保持 state、mutation 和 RNG 不变，没有删减任务制造正例。
- P9-S8 验收后必须返回本卡，只选择届时完整动作图已准入的真实弹射动作，证明多段选择在
  首次 mutation 前闭合，并完成同一 transaction 的 mutation、settlement、来源审计和 replay。
  两个未勾项通过后，才允许勾选本卡及总计划中的 P9-S5D2。

组件验收报告：`live_validation_reports/P9-S5D2_BOUNCE_DYNAMIC_TARGET_MECHANISM_accepted.md`。
