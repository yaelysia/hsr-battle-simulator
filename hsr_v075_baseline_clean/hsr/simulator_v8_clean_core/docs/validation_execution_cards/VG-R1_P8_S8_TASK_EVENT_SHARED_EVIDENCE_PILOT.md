# VG-R1 P8-S8 task/event 共享证据试点执行卡

## 1. 执行状态

- 阶段：`VG-R1`
- 状态：第一次基线已按卡暂停；本修订版等待独立执行线程继续实施
- 实施基线：必须包含撤销提交 `9c8ac45`
- 最终只允许提交：`ready_for_review`
- 推荐模型：GPT-5.6 Sol
- 推荐推理等级：`max`
- 执行模式：普通模式，单线程施工，所有重验证严格串行

执行线程不能勾选本卡、不能提交 Git、不能进入第二个验证治理试点。

## 2. 项目背景

本项目的验证治理有两个目的：

1. 通用非法状态应在模型构造、Mutation 创建或原子提交边界直接暴露，不再依赖
   大型阶段验证事后发现。
2. 确实需要真实目录的验证应共享昂贵构建和公共证据，减少新验证代码、完整
   lowering 次数、运行时间、内存和 IO。

`VG-S1` 与 `VG-S2` 已完成第一类工作。原 `VG-S3` 试图先建立全项目注册表、
选择器和元验证，新增 5,110 行却没有同轮减少真实重验证，已被撤销。

本卡只做第二类工作的第一个真实纵向试点。它必须直接减少现有 P8-S8 的重复，
不能再建立一套验证治理基础设施。

第一次执行已提供一个更底层的事实：task 基线尚未进入 family 契约，就在
`_production_owned_combatant_catalog()` 调用完整 `TBGDLowering.build()` 时耗尽
4 GiB。原卡把“单次完整构建可承受”当成了前提，该前提不成立。本修订版以这次
失败作为有效成本基线，不允许提高上限或重新跑旧路径。

## 3. 当前代码事实

目标文件：

```text
simulator_v8_clean_core/tools/validate_p8_s8_light_cone_remaining_gameplay_closure.py
```

当前事实：

- 文件约 354 KiB，包含多个聚焦入口和完整 P8-S8 聚合。
- `run_task_contract_validation()` 与 `run_event_contract_validation()` 都调用
  `_focused_bundle(..., include_owned_combatant_catalog=True)`。
- 该构建路径通过 `_production_owned_combatant_catalog()` 执行完整
  `TBGDLowering.build()`。
- 两个入口随后重复生成：
  - 光锥机制分区；
  - 空装备角色路径清单；
  - 正式场景证据；
  - 生命周期证据；
  - 生产事件链；
  - 通用 mutation、战斗状态变更、治疗、自定义事件和弱点事件证据。
- 两条路径只在公共证据完成后，才分别进入 task/property 与 event 断言。
- CLI 当前限制一次只能运行一个聚焦模式，因此连续验证两类契约时，完整目录和
  公共证据必然构建两次。
- 工作区内没有该模块之外的 Python 调用者依赖两个 wrapper 的具体实现。
- 第一次 task 基线在 `_lower_action_ability_bindings()` 累积全部角色、怪物和
  servant 技能效果时触发 `MemoryError`：
  - 墙钟 46.76 秒；
  - 峰值 RSS 4,137,552 KiB；
  - 尚未进入所选 `AddModifier:s8` family 的契约执行。
- P8-S8 实际只从完整 Canonical IR 提取五类 owned-combatant 准入数据：
  servant 定义、servant 动作定义、动作能力绑定、动作准入和出生模板。为这五类
  数据构建全部角色、怪物、状态和能力图属于错误依赖。

这些事实是本卡唯一的抽取依据。

## 4. 阶段完成结果

完成后必须能够在一个进程中同时请求 task 与 event 两类契约，并得到：

- task/event 路径不再调用完整 `TBGDLowering.build()`；
- owned-combatant 准入投影由 lowering 层的来源真实窄构建器生成一次；
- P8-S8 focused bundle 只构建一次；
- 两类契约共用的证据链只生成一次；
- task 与 event 各自保留独立结果、过滤条件和失败诊断；
- 单独运行、组合运行和不同切片顺序不改变业务结果；
- 旧单切片 CLI 仍路由到同一实现，不保留新旧双轨；
- 被替代的重复编排在同一改动中删除；
- 不修改任何游戏生产逻辑、lowering 语义或 Canonical IR。

本阶段不承诺解决完整 lowering 自身的峰值内存。它先消除同一验收轮中的重复
构建，并从根本上删除 P8-S8 对完整 lowering 的错误依赖。完整 lowering 本身的
分批和限峰仍需根据本试点数据另行判断。

## 5. 详细目标

### 5.1 建立来源真实的 owned-combatant 准入窄投影

在 `tbgd/lowering` 边界建立类型化、递归不可变且确定性排序的窄构建结果，只投影
P8-S8 正式 Memory 角色构筑准入所需的五类数据：

1. servant 定义；
2. servant 动作定义；
3. servant 动作能力绑定；
4. servant 动作准入；
5. servant 出生模板。

该接口是 compiler/lowering 的正式窄投影，不是验证 fixture，也不是残缺
Canonical IR。它必须满足：

- 直接从当前 TBGD 和现有 character-card/lowering 生产函数生成。
- 在进入动作能力 lowering 前就按 servant 动作集合缩小输入；禁止先 lower 全部
  avatar/monster/servant 技能再过滤结果。
- 复用现有动作定义、能力绑定、动作准入、owner relation、spawn/replacement 和
  birth-template 语义函数；禁止复制 raw parser 或手工重建第二套 IR。
- 不按角色名、servant 名、固定 ID、固定文件或已知答案选取数据。
- 缺失、重复、歧义或来源断裂必须形成结构化 blocked/issue，不能取第一项。
- 每项保持原有 `IRSource`，且集合身份可由 raw 表和能力文件独立重算。
- 不读取 `/tmp` 基线、报告或验证 artifact。
- 不创建完整 Canonical IR、RuleBook、全角色/怪物能力图或与五类结果无关的集合。

完整 `TBGDLowering.build()` 与窄投影必须复用相同的底层语义构造函数。允许为现有
helper 增加默认保持全量行为的类型过滤边界；禁止形成两套会独立演进的
owned-combatant lowering。

P8-S8 的 `_production_owned_combatant_catalog()` 应被该正式窄投影替代或退役，
不能继续保留 full-build fallback。

### 5.2 建立一次性共享证据生命周期

在 P8-S8 验证模块内部形成一个局部共享上下文。它应清楚区分：

- 昂贵且只允许生成一次的目录、IR 和 RuleBook；
- task/event 共用且只允许生成一次的场景与事件证据；
- 每个切片独有的过滤、断言、行结果和输出。

共享上下文只服务当前进程，不落盘缓存，不成为 runtime、lowering 或其他阶段的
依赖。不能新建全项目 registry、selector、cache manager、plugin 或任务图。

共享证据不得被某个切片原地修改后影响另一个切片。允许共享不可变对象，也允许
为切片建立小型派生视图；禁止为了隔离而深拷贝完整 Canonical IR 或 RuleBook。

### 5.3 保持 task 与 event 契约独立

task 切片继续证明：

- 每个当前准入的真实 gameplay task family 有真实 callback 执行；
- 机制 family 不借角色构筑依赖豁免逃避执行；
- stack property family 具有不同的真实 consumer。

event 切片继续证明：

- 每个精确事件 family 被执行或诚实分类为未引用来源；
- 已执行 family 具有可执行契约；
- 未引用来源保留真实来源身份；
- 共享战斗状态事件使用真实 transition；
- 状态替换命名空间 fail-closed。

不能为了共享上下文合并两组通过条件，也不能让一组失败被另一组的 `ok=true`
覆盖。

### 5.4 提供局部组合入口

新增一个只面向本模块的可重复切片选择入口，至少支持：

```text
task
event
task + event
```

推荐使用可重复的 `--contract-slice task|event`。现有
`--task-contract-only`、`--event-contract-only` 继续作为薄路由，以免破坏
已有人工命令；它们不得保留另一套执行实现。

现有 `--task-family` 和 `--event-family` 过滤语义必须保持。组合运行时两个
过滤器分别作用于自己的切片。

其他 resource、catalog、condition、numeric 模式不进入本试点，不得借机重写。

### 5.5 保持输出兼容并增加运行级摘要

单切片和组合运行都继续写出现有 task/event summary 与矩阵文件。已有字段含义、
谓词键、计数口径和行身份不得因重构变化。

组合运行额外写一个紧凑的 run summary，至少记录：

- 实际请求和完成的切片；
- 每个切片的 `ok`；
- 聚合 `ok`；
- 实际完整 `TBGDLowering.build()` 调用次数；
- 实际 owned-combatant 窄投影构建次数；
- 实际 focused bundle 构建次数；
- 实际公共证据生成次数；
- 是否序列化完整 Canonical IR；
- 是否运行完整 P8-S8 聚合；
- 运行耗时和峰值内存证据路径。

构建次数必须由真实入口调用累计，不能直接把常数 `1` 写入 summary。

### 5.6 删除旧重复，不建立元验证

公共提取与旧编排删除必须在同一改动完成。允许保留很薄的兼容 wrapper，但所有
业务计算必须进入唯一实现。

禁止新增以下文件或等价物：

- 全项目 validator registry；
- 全项目 validation selector；
- 持久化构建缓存；
- 专门验证本试点的千行级 validator；
- 复制 P8-S8 输出再自行推导答案的第二套 oracle。

本阶段新增和删除的验证 Python 代码合计必须净减少。lowering 层允许增加窄投影
边界，但新增代码必须复用和收敛现有语义，不得复制 parser。报告、执行卡和 JSON
产物不计入代码量。

## 6. 基线与测量协议

### 6.1 已接受的修改前失败基线

以下证据已经由第一次执行生成，视为本阶段正式基线：

```text
/tmp/vg_r1_p8_s8_shared_evidence/baseline_task/stderr.log
/tmp/vg_r1_p8_s8_shared_evidence/baseline_task/time-v.txt
/tmp/vg_r1_p8_s8_shared_evidence/selection.json
```

事实为：

- task family：结构化选出的 `AddModifier:s8`；
- event family：结构化选出的 `OnAddModifierSuc:s8`；
- task 旧入口在进入 family 执行前发生 `MemoryError`；
- 墙钟 46.76 秒；
- 峰值 RSS 4,137,552 KiB；
- 退出码 1。

该失败证明旧路径在预算内不可执行，不是业务谓词基线。不得再次运行旧 task 或
event 路径，不得提高上限补齐第二条失败样本，也不得把两个 family 身份写入生产
选择逻辑。

### 6.2 修改后测量

修改后按三层、各一次测量：

1. 单独构建一次 owned-combatant 准入窄投影，输出来源闭合矩阵和
   `/usr/bin/time -v`。
2. 使用第一次选出的 task/event family 运行一次受限组合入口，证明原来无法进入
   的两个 family 现在都能执行。
3. 只有前两项通过后，运行一次不带 family 过滤的 task+event 组合验证，证明两组
   现行完整谓词。

所有 summary 必须报告来自实际调用的：

- 完整 `TBGDLowering.build()` 次数；
- owned-combatant 窄投影次数；
- focused bundle 次数；
- 公共证据次数；
- 墙钟、RSS、IO 和产物大小。

### 6.3 资源限制

- 所有重命令使用低 CPU 与 IO 优先级并严格串行。
- 同一时间只允许一个 lowering/RuleBook 进程。
- 所有产物写入 `/tmp`。
- 所有测量继续使用 4 GiB 地址空间硬上限和相同低优先级命令环境。
- 任一命令发生 `MemoryError`、被系统杀死或超过限制后不得提高上限反复重跑。
- 不清理系统页缓存，不使用 sudo，不安装依赖。

旧路径从未完成，所以本阶段不伪造“前后成功耗时百分比”。硬证据是完整 build
调用从 1 次失败降为 0 次且验证成功；时间、RSS 和 IO 仍必须记录，并形成后续
重复运行的真实新基线。

## 7. 验收标准

以下条件必须全部满足，执行线程才可提交 `ready_for_review`：

| 验收对象 | 通过条件 |
|---|---|
| 窄投影身份 | 五类集合均为类型化、不可变、确定性排序，不携带无关 Canonical IR 集合 |
| 来源完整 | raw servant、技能、owner relation、spawn/replacement 和 timeline 来源与五类投影闭合；缺失或冲突 fail-closed |
| 无硬编码 | 不按角色、servant、技能、固定 ID 或已知 family 驱动正式窄投影 |
| 真实功能 | 未过滤的 task 与 event 两组现行谓词分别全部为真 |
| 组合结果 | 组合 `ok` 只在两个切片都通过时为真 |
| 完整构建 | task/event 路径实际 `TBGDLowering.build()` 调用为 0 次 |
| 窄构建 | 组合运行实际 owned-combatant 准入窄投影为 1 次 |
| focused 构建 | 组合运行实际 P8-S8 focused bundle 为 1 次 |
| 公共证据 | partition、路径清单、正式场景、生命周期和公共事件链各生成 1 次 |
| 受限正例 | 基线选出的 task/event family 均执行成功，并保留真实来源、settlement、RNG/replay 证据 |
| 顺序独立 | 受限 family 以 task/event 和 event/task 两种消费顺序得到相同结果；不得重新构建共享上下文 |
| 失败隔离 | 一个切片失败时另一个切片结果仍完整可见，聚合结果为失败 |
| 构建失败 | 共享构建失败时不写伪成功的切片 summary |
| CLI 兼容 | 两个旧单切片参数只路由到新实现，过滤语义不变 |
| 代码收缩 | 本阶段验证 Python 代码净行数变化小于 0 |
| 窄投影资源 | 单独窄投影峰值 RSS 不高于 1.5 GiB |
| 组合内存 | 受限和未过滤组合运行峰值 RSS 均不高于 3.5 GiB |
| 运行证据 | 三次修改后测量均记录墙钟、RSS、IO；不虚构旧成功耗时对比 |
| 产物边界 | 不写完整 Canonical IR、RuleBook、transition 或 replay dump |
| 架构边界 | runtime、Canonical IR schema 和游戏机制行为不变；lowering 只新增窄投影或收敛共享 helper |
| 单一语义 | 完整 build 与窄投影复用同一套动作、owner relation、准入和出生模板构造函数 |
| 无新框架 | 没有 registry、selector、持久缓存或独立元验证系统 |

若来源、构建次数或内存指标未达到，不得把“功能正确”解释为本治理试点通过。应提交
`blocked` 证据并由规划线程判断是否继续。

## 8. 必跑验证

按以下顺序串行执行：

1. 不重跑修改前基线。
2. owned-combatant 窄投影的来源闭合、负例和资源测量。
3. 修改后相同两个 family 的受限组合运行。
4. 修改后一次未过滤 task+event 组合运行。
5. 切片顺序独立和失败隔离的轻量探针；探针复用已构建上下文，不能再次 lowering。
6. `compileall`，缓存写入 `/tmp`。
7. `git diff --check`。

明确不运行：

- 完整 P8-S8 聚合入口；
- P8-S8 catalog startup；
- 任何直接或间接调用完整 `TBGDLowering.build()` 的 owned-combatant 验证；
- P1-P7 聚合；
- `validate_v0_209`；
- P3/P4/P6/P7 重目录验证；
- 与 task/event 调用链无关的 runtime、UI 或 scenario 验证。

## 9. 交付物

- P8-S8 验证模块的局部共享证据重构。
- lowering 层来源真实的 owned-combatant 准入窄投影。
- `/tmp` 下的前后 summary、矩阵、time/RSS/IO 和代码量比较。
- `live_validation_reports/v8_vg_r1_p8_s8_task_event_shared_evidence_ready_for_review.md`。

报告必须列出真实命令、实际计数、前后数值、未运行范围和任何 gap。不能只写
`ok=true`。

## 10. 唯一完成清单

- [ ] `VG-R1-01` 第一次 4 GiB 失败基线已作为正式证据保留，旧路径未再次运行。
- [ ] `VG-R1-02` lowering 层已提供五类数据的来源真实 owned-combatant 准入窄投影。
- [ ] `VG-R1-03` 窄投影的完整来源闭合、确定性和 fail-closed 负例均已证明。
- [ ] `VG-R1-04` task/event 路径完整 `TBGDLowering.build()` 调用次数为零。
- [ ] `VG-R1-05` P8-S8 共享构建与公共证据在一个进程中只生成一次。
- [ ] `VG-R1-06` task/event 保持独立谓词、过滤、顺序独立和失败诊断。
- [ ] `VG-R1-07` 新组合入口和旧 CLI 薄路由使用同一实现。
- [ ] `VG-R1-08` 受限及未过滤 task+event 组合验证各一次通过并满足内存门槛。
- [ ] `VG-R1-09` 被替代的 full-build/重复编排已删除，验证 Python 代码净减少，未新增治理框架。
- [ ] `VG-R1-10` 资源证据、聚焦编译、格式检查和报告完整且诚实。
