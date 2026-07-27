# 验证治理与状态完整性回正计划

## 1. 计划定位

本计划是独立治理轨道，代号 `VG`。它不属于新的游戏内容阶段，也不替代
P1-P8 的机制计划。

这条轨道解决三个已经互相放大的问题：

1. 某些非法战斗状态可以先被构造或提交，之后才由大型验证发现。
2. 新阶段不断新增独立验证器、重复构建完整 RuleBook，执行时间、内存、IO
   和 token 成本持续增长。
3. 历史验证器固化了旧阶段当时的缺口和验收语义；代码演进后，执行线程常被迫
   维护旧验证，而不是证明本次改动。

目标不是降低严谨度，而是把严谨度前移到生产契约：

```text
状态模型拒绝非法表示
  -> 事务边界拒绝不完整提交
  -> 轻量验证证明这些不变量
  -> 目录验证只证明来源覆盖
  -> 里程碑才运行全局聚合
```

## 2. 当前事实基线

首轮静态扫描已经确认：

- `simulator_v8_clean_core/tools/` 下有 177 个 `validate_*.py`，合计约
  5.54 MiB。
- 至少 122 个验证文件存在直接 `TBGDLowering(...).build()` 路径。
- `TBGDLowering.build()` 是单体完整构建：光锥目录、角色卡、怪物卡、动作、
  全能力文件、状态、目标、队列、召唤、波次和装备图在同一调用中闭合。
- `validate_p7_current_tree_shared_regressions.py` 已能共享一次 RuleBook，但仍
  依赖上述完整构建，并把 P2/P3 当时的特定缺口写进当前通过条件。
- `finalize_selected_execution_graph()` 会检查节点完整、Mutation 前置条件和
  候选状态一致性，但成功发布前没有领域状态完整性检查。
- `UnitState`、`BattleState` 和 `Snapshot` 使用 frozen dataclass，但其中多个
  `dict/list` 并未在模型构造边界递归冻结。
- 当前存在同一事实的多份运行时表示，例如：
  - 状态粗索引与完整状态实例；
  - 单位生命周期标记与 HP；
  - 召唤单位 flags、召唤实体表及多个索引；
  - 光环父关系、成员清单与投影状态；
  - 原始事件与 dispatcher 返回事件集合。

这些只是首轮定位事实，不等于所有项目问题已经审计完成。

## 3. 第一性原则

### 3.1 一项事实只能有一个权威所有者

同一事实可以有多个派生视图，但必须明确：

- 哪个字段或类型是权威来源；
- 派生视图何时重算；
- 派生视图是否进入 snapshot/replay；
- 权威事实和派生视图不一致时，是拒绝、重建还是迁移；
- 禁止两个可独立写入的字段同时充当权威来源。

### 3.2 候选状态可以暂时不完整，提交状态不可以

一个事务内部可以按顺序规划多条相互依赖的 Mutation。中间候选状态不对 UI、
推演器、snapshot 或 replay 可见。

只有事务全部完成并通过以下检查后才能发布：

- Mutation 自身结构与 before/after 一致；
- 本次触达领域的不变量成立；
- 必须原子变化的权威事实和派生索引同时闭合；
- settlement、事件和 RNG 账本与已提交 Mutation 一致。

### 3.3 不建立每动作全量扫描器

状态完整性检查必须按领域和触达路径增量执行：

- Mutation 创建边界检查单字段合法性。
- 原子提交边界只运行本次触达领域的完整性检查。
- snapshot load、replay load、debug 和里程碑可运行全局完整性检查。

禁止为了“统一”而在每个动作后扫描完整 RuleBook、全部单位、全部状态和全部
目录。

### 3.4 三种失败不得混淆

- 游戏规则阻断：合法状态下动作不允许执行，返回正式 blocked outcome。
- 内部状态非法：程序不变量被破坏，事务必须拒绝发布并给出机器可读 integrity
  issue；不能伪装成游戏机制 blocked。
- 证据未证明：目录或重回归未运行，报告标记 `not_proven/deferred`，不能改变
  生产行为。

### 3.5 验证按证明对象拆分

- `fast`：语法、类型、局部不变量和小型 fixture。
- `direct`：本次触达调用链上的现行生产契约。
- `catalog`：真实来源集合、完整 lowering、目录 admission。
- `full`：里程碑和共享内核大改后的全局聚合。

目录覆盖不能替代运行时正确性，fixture 也不能替代完整来源证明。

## 4. 目标形态

### 4.1 状态完整性

最终应形成：

- 递归不可变、外部输入无法别名修改的 committed state。
- 每个核心领域有明确的权威状态、派生索引和完整性谓词。
- 原子提交能根据 Mutation 触达域运行必要且有限的完整性检查。
- 非法状态无法被正式发布，也无法进入 snapshot/replay。
- 完整性失败保持 before state、零 committed Mutation，并携带稳定错误码和路径。

### 4.2 验证治理

最终应形成：

- 一份机器可读的验证清单，记录验证类型、触达域、来源范围、资源等级、替代关系
  和适用触发条件。
- 新阶段默认只写紧凑的生产契约验证，不再复制完整 lowering、通用 fixture、
  source audit 和 replay 编排。
- 同一轮需要完整 RuleBook 时只构建一次；不需要目录证明的验证不构建完整
  RuleBook。
- 历史验证被分类为现行契约、目录审计、历史证据、已替代或无效，而不是永久
  默认重跑。
- 验收先审代码和不变量，再按触达域选择验证；不以脚本数量代表严格程度。

## 5. 分阶段路线

以下阶段是依赖顺序，不是第二套完成清单。唯一可打勾内容只存在于各阶段执行卡。

### VG-S0 状态权威与验证成本审计

只读审计活跃生产路径和验证器。形成权威事实矩阵、可构造非法状态矩阵、验证成本
矩阵和不超过三个的首批实现优先级。S0 不修改战斗行为。

推荐：GPT-5.6 Sol，`max`，普通模式。

### VG-S1 committed state 递归不可变与快照隔离

关闭 frozen dataclass 内部容器仍可写、构造输入可反向别名修改状态、
`Snapshot.to_json()` 泄露内部引用这三个共享绕过入口。只收紧 UnitState、
BattleState、Snapshot、codec 和 reducer 的表示边界，不加入任何领域战斗语义。

推荐：GPT-5.6 Sol，`max`，普通模式；单卡执行。

### VG-S2 committed integrity 协议与生命周期试点

建立机器可读 integrity issue、touched-domain 选择和原子提交失败语义，只以
单位生命周期作为第一个领域试点。候选状态可以在事务中暂时不完整，正式提交前
必须闭合；失败保持 before state 和零 committed mutation。

推荐：GPT-5.6 Sol，`max`，普通模式；单卡执行。

### VG-S3 验证选择与共享构建入口

建立最小 validator registry 和统一选择入口。先复用现有验证函数，不重写全部
验证器；将 source inventory、完整 RuleBook 和小型 fixture 的构建边界分开。

推荐：GPT-5.6 Terra，`high/xhigh`，普通模式。

### VG-S4 事件 closure 所有权回正

统一 root event、dispatcher closure、callback emitted event 和递归 dispatch
的所有权，消除当前 executor/scheduler 中已确认的重复 root event。该阶段只做
事件契约，不顺带迁移 status、summon 或 queue 权威事实。

推荐：GPT-5.6 Sol，`max`，普通模式。

### VG-S5 权威事实逐域回正

按独立执行卡依次处理状态实例/粗索引、召唤关系/索引、光环投影和
wave/turn/queue 关系。`VG-S5` 是阶段族，不是一张大卡；每次只能实施其中一个
领域，不能用共享编号把多个系统合成一次重构。

推荐：GPT-5.6 Sol，`xhigh/max`；每个领域单卡执行。

### VG-S6 目录验证限峰与共享构建

只针对确实需要 catalog 的路径分离 source inventory、完整 lowering、RuleBook
和 direct fixture 边界，建立单轮共享构建、紧凑摘要和粗粒度恢复。缓存只服务
验证，生产代码不得依赖缓存或 `/tmp` 产物。

推荐：GPT-5.6 Sol，`xhigh/max`。

### VG-S7 P8 试点

用后续遗器阶段试运行新流程，比较修改前后的峰值内存、IO、耗时、验证代码增量、
返工次数和漏检问题。试点通过后才推广到后续内容卡。

推荐：执行模型按 P8 卡决定；验收使用 GPT-5.6 Sol。

### VG-S8 历史验证渐进迁移

只在触达旧领域时迁移对应验证。保留有效谓词，退役重复脚本结构。禁止一次性重写
P1-P8，也禁止为了旧脚本继续保留错误生产语义。

## 6. 总体红线

- 不降低 source audit、settlement、RNG、snapshot 或 replay 的真实性要求。
- 不用固定角色、怪物、装备、技能 ID 代替结构化选样。
- 不把“验证没跑”解释成生产 blocked。
- 不把生产状态完整性检查写进验证工具目录。
- 不让 runtime 依赖验证 artifact、缓存、报告或 `/tmp`。
- 不为每个动作运行完整全局状态扫描。
- 不先造通用框架再寻找用途；每个抽象必须由 S0 中的实际重复或风险支撑。
- 不一次改造全部历史验证。
- 不新增依赖；若后续确有必要，必须先向用户申请。
- 不修改或提交工作区现有无关 UI 草稿。

## 7. 成功指标

治理成功不能只看“脚本变少”，至少要同时满足：

- 非法 committed state 在生产边界直接被拒绝。
- 新阶段聚焦验证不需要完整 lowering，除非目标本身是目录覆盖。
- 一轮验收中的完整 RuleBook 构建次数可解释且通常不超过一次。
- 新增验证代码量与本次新增生产契约相称，不复制历史聚合编排。
- 历史验证失败先被分类，不再默认触发生产兼容修补。
- catalog 未运行时报告诚实为 `not_proven`。
- 返工问题能定位到具体权威事实、不变量或来源缺口，而不是继续扩大验证矩阵。

## 8. 当前状态与下一入口

`VG-S0` 状态权威与成本审计、`VG-S1` committed state 递归不可变与快照隔离、
`VG-S2` committed integrity 协议与生命周期试点、`VG-S3` validator registry
与纯 dry-run 选择入口均已由验收线程复核通过。`VG-S3` 的唯一完成清单与当前
代码、聚焦验证及定向绕过探针一致：

```text
docs/validation_execution_cards/VG-S3_VALIDATOR_REGISTRY_AND_SELECTION_ENTRY.md
```

下一步只能先编写并确认 `VG-S4` 事件 closure 所有权回正执行卡，确认前不修改
代码。`VG-S4` 只处理事件所有权；实际共享 lowering/RuleBook 仍属于 `VG-S6`，
不得提前混入。
