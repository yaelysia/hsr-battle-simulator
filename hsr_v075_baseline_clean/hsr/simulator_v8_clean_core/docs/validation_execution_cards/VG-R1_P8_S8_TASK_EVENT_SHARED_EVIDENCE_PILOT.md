# VG-R1 P8-S8 task/event 共享证据试点执行卡

## 1. 执行状态

- 阶段：`VG-R1`
- 状态：方案已确认，等待独立执行线程实施
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

这些事实是本卡唯一的抽取依据。

## 4. 阶段完成结果

完成后必须能够在一个进程中同时请求 task 与 event 两类契约，并得到：

- owned-combatant 完整目录只构建一次；
- P8-S8 focused bundle 只构建一次；
- 两类契约共用的证据链只生成一次；
- task 与 event 各自保留独立结果、过滤条件和失败诊断；
- 单独运行、组合运行和不同切片顺序不改变业务结果；
- 旧单切片 CLI 仍路由到同一实现，不保留新旧双轨；
- 被替代的重复编排在同一改动中删除；
- 不修改任何游戏生产逻辑、lowering 语义或 Canonical IR。

本阶段不承诺解决完整 lowering 自身的峰值内存。它先消除同一验收轮中的重复
构建；单次 lowering 的限峰问题必须根据本试点数据另行判断。

## 5. 详细目标

### 5.1 建立一次性共享证据生命周期

在 P8-S8 验证模块内部形成一个局部共享上下文。它应清楚区分：

- 昂贵且只允许生成一次的目录、IR 和 RuleBook；
- task/event 共用且只允许生成一次的场景与事件证据；
- 每个切片独有的过滤、断言、行结果和输出。

共享上下文只服务当前进程，不落盘缓存，不成为 runtime、lowering 或其他阶段的
依赖。不能新建全项目 registry、selector、cache manager、plugin 或任务图。

共享证据不得被某个切片原地修改后影响另一个切片。允许共享不可变对象，也允许
为切片建立小型派生视图；禁止为了隔离而深拷贝完整 Canonical IR 或 RuleBook。

### 5.2 保持 task 与 event 契约独立

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

### 5.3 提供局部组合入口

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

### 5.4 保持输出兼容并增加运行级摘要

单切片和组合运行都继续写出现有 task/event summary 与矩阵文件。已有字段含义、
谓词键、计数口径和行身份不得因重构变化。

组合运行额外写一个紧凑的 run summary，至少记录：

- 实际请求和完成的切片；
- 每个切片的 `ok`；
- 聚合 `ok`；
- 实际 owned-combatant 目录构建次数；
- 实际 focused bundle 构建次数；
- 实际公共证据生成次数；
- 是否序列化完整 Canonical IR；
- 是否运行完整 P8-S8 聚合；
- 运行耗时和峰值内存证据路径。

构建次数必须由真实入口调用累计，不能直接把常数 `1` 写入 summary。

### 5.5 删除旧重复，不建立元验证

公共提取与旧编排删除必须在同一改动完成。允许保留很薄的兼容 wrapper，但所有
业务计算必须进入唯一实现。

禁止新增以下文件或等价物：

- 全项目 validator registry；
- 全项目 validation selector；
- 持久化构建缓存；
- 专门验证本试点的千行级 validator；
- 复制 P8-S8 输出再自行推导答案的第二套 oracle。

本阶段新增和删除的验证 Python 代码合计必须净减少。报告、执行卡和 JSON 产物
不计入该代码量。

## 6. 基线与测量协议

### 6.1 修改前基线

修改代码前只执行一次受限基线：

1. 从当前真实 inventory 中结构化选择一个可执行 task family。
2. 从当前真实 inventory 中结构化选择一个可执行 event family。
3. 分别使用旧单切片入口运行这两个 family。
4. 保存命令、选择身份、summary、矩阵、`/usr/bin/time -v` 输出和退出码。

选择结果只允许写入 `/tmp` 测量记录，不能硬编码进生产验证器或验收谓词。

基线只跑这两个代表 family，不分别重跑完整 task 和完整 event 集合。这样既能
触发两次相同重构建，也避免为测量重复支付完整业务矩阵成本。

### 6.2 修改后测量

使用相同的两个 family，通过组合入口运行一次，并与基线比较：

- summary 谓词和值；
- 行身份和关键诊断；
- 实际构建次数；
- 墙钟时间；
- 峰值 RSS；
- 文件系统输入输出计数；
- 产物大小。

随后只运行一次不带 family 过滤的 task+event 组合验证，证明两组现行完整谓词。
不得再分别运行完整 task 和完整 event。

### 6.3 资源限制

- 所有重命令使用低 CPU 与 IO 优先级并严格串行。
- 同一时间只允许一个 lowering/RuleBook 进程。
- 所有产物写入 `/tmp`。
- 前后测量使用相同的 4 GiB 地址空间上限和相同命令环境。
- 任一命令发生 `MemoryError`、被系统杀死或超过限制后不得提高上限反复重跑。
- 不清理系统页缓存，不使用 sudo，不安装依赖。

墙钟时间可能受系统缓存影响，因此“构建次数从二降到一”是硬证据；时间、RSS 和
IO 是必须记录的运行证据。

## 7. 验收标准

以下条件必须全部满足，执行线程才可提交 `ready_for_review`：

| 验收对象 | 通过条件 |
|---|---|
| 真实功能 | 未过滤的 task 与 event 两组现行谓词分别全部为真 |
| 组合结果 | 组合 `ok` 只在两个切片都通过时为真 |
| 构建次数 | 组合运行实际完整 owned-combatant lowering 为 1 次 |
| focused 构建 | 组合运行实际 P8-S8 focused bundle 为 1 次 |
| 公共证据 | partition、路径清单、正式场景、生命周期和公共事件链各生成 1 次 |
| 结果等价 | 受限 family 在旧单跑与新组合运行中的谓词、行身份和诊断一致 |
| 顺序独立 | 受限 family 以 task/event 和 event/task 两种消费顺序得到相同结果；不得重新构建共享上下文 |
| 失败隔离 | 一个切片失败时另一个切片结果仍完整可见，聚合结果为失败 |
| 构建失败 | 共享构建失败时不写伪成功的切片 summary |
| CLI 兼容 | 两个旧单切片参数只路由到新实现，过滤语义不变 |
| 代码收缩 | 本阶段验证 Python 代码净行数变化小于 0 |
| 运行收益 | 受限组合运行墙钟时间不高于两个旧基线总和的 75% |
| 内存边界 | 组合运行峰值 RSS 不高于旧基线中较高者的 110% |
| 产物边界 | 不写完整 Canonical IR、RuleBook、transition 或 replay dump |
| 架构边界 | runtime、lowering、Canonical IR 和游戏机制行为均未改变 |
| 无新框架 | 没有 registry、selector、持久缓存或独立元验证系统 |

若时间或内存指标未达到，不得把“功能正确”解释为本治理试点通过。应提交
`blocked` 证据并由规划线程判断是否继续。

## 8. 必跑验证

按以下顺序串行执行：

1. 修改前两个受限单切片基线。
2. 修改后相同 family 的受限组合运行。
3. 修改后一次未过滤 task+event 组合运行。
4. 切片顺序独立和失败隔离的轻量探针；探针复用已构建上下文，不能再次 lowering。
5. `compileall`，缓存写入 `/tmp`。
6. `git diff --check`。

明确不运行：

- 完整 P8-S8 聚合入口；
- P8-S8 catalog startup；
- P1-P7 聚合；
- `validate_v0_209`；
- P3/P4/P6/P7 重目录验证；
- 与 task/event 调用链无关的 runtime、UI 或 scenario 验证。

## 9. 交付物

- P8-S8 验证模块的局部共享证据重构。
- `/tmp` 下的前后 summary、矩阵、time/RSS/IO 和代码量比较。
- `live_validation_reports/v8_vg_r1_p8_s8_task_event_shared_evidence_ready_for_review.md`。

报告必须列出真实命令、实际计数、前后数值、未运行范围和任何 gap。不能只写
`ok=true`。

## 10. 唯一完成清单

- [ ] `VG-R1-01` 修改前已完成两个受限 family 的单次基线，证据完整且未反复重跑。
- [ ] `VG-R1-02` P8-S8 共享构建与公共证据在一个进程中只生成一次。
- [ ] `VG-R1-03` task/event 保持独立谓词、过滤和失败诊断。
- [ ] `VG-R1-04` 新组合入口和旧 CLI 薄路由使用同一实现。
- [ ] `VG-R1-05` 受限等价、顺序独立和失败隔离均已证明。
- [ ] `VG-R1-06` 未过滤 task+event 组合验证一次通过。
- [ ] `VG-R1-07` 构建次数、耗时、RSS、IO 和代码量达到验收阈值。
- [ ] `VG-R1-08` 被替代的重复编排已删除，验证 Python 代码净减少。
- [ ] `VG-R1-09` 未新增通用治理框架、持久缓存、元验证或生产依赖。
- [ ] `VG-R1-10` 聚焦编译与格式检查通过，报告诚实记录未验证范围。

