# P8-S5 至 P8-S21 与 P8-R1、P8-R2 执行卡索引

## 1. 用途

本目录保存 P8 剩余阶段的预先规划执行卡。执行线程不再临时重写阶段目标，而是读取对应执行卡，核对当前代码事实后只实施该阶段。执行线程最多提交 `ready_for_review`，不得修改 P8 checklist、不得自称完成、不得提交 Git。

长期目标、全局红线和唯一阶段 checklist 仍以
`../P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md` 为准。本目录不是第二套总计划；每个文件只包含一个阶段的唯一执行清单。

P8-S0 至 P8-S21、R1 和 R2 已于当前源码完成最终聚合验收。后续只在来源版本变化或装备契约被实际修改时重新进入相应责任阶段，不把本目录重新作为默认执行队列。最终结论见 `live_validation_reports/v8_p8_equipment_build_light_cone_relic_final_checkpoint.md`。

## 2. 依赖图与并行边界

```text
accepted S4
   |-- light-cone track: S5 -> S6 -> S7 -> S8 -> R1 -> R2 --|
   |                                                         |-> S18 -> S19 -> S20 -> S21
   |-- relic track:      S9 -> ... -> S17 -------------------|
```

- S5 与 S9 只有在 S4 验收并形成代码检查点后才能开始。
- 光锥轨内部严格按 S5、S6、S7、S8 顺序执行。
- 遗器轨内部严格按 S9 至 S17 顺序执行。
- R1 是 CHAR-M1 后发现的共享 runtime 修复门。R1-RUNTIME 已于检查点 `2d1a3f9` 通过聚焦验收并合入，满足 S15 的生产代码前置条件。
- VG-R1 曾用低内存入口确认三个真实 task/event family 失败；R2 已关闭这些失败，并以低内存目录入口完成当前 162 张已发布光锥的正式启动收口。
- R2 施工期间退役了未过滤运行和九族过滤入口；最终差量与历史暂停裁决保存在
  `P8-R2_REVIEW_DELTA_AFTER_UNFILTERED_FAILURES.md`，后续不得恢复为常规 gate。
- 两条轨可并行，但必须从同一个已验收 S4 检查点创建不同 Git worktree；禁止在同一工作区并行修改。
- 每个阶段验收后先形成独立检查点，下一阶段再基于该检查点继续。
- S18 只有在 R2 与 S17 均验收、两个检查点已合并且聚焦回归通过后才能开始。
- S19-S21 重新严格串行，不允许继续在分支上各自演进共享装配或 runtime 契约。

### 2.1 S9-S21 阶段分组

| 分组 | 阶段 | 每组结束时唯一应得到的结果 |
|---|---|---|
| 定义与实例 | S9-S12 | 当前遗器目录、六槽实例、主词条和副词条可被精确、合法地表示；尚不应用属性或套装效果 |
| 装配入口 | S13-S15 | 套装门槛、静态账本和动态 provider 已接入正式构筑；未闭合机制仍阻止战斗准入 |
| 机制闭合 | S16-S17 | 当前玩家遗器套装 gameplay family 全部走通用系统，严格零实现/验收缺口 |
| 两轨汇合 | S18-S20 | 光锥与遗器形成唯一最终面板、出生、查询、回放链，并以一个正式构筑纵切证明可用 |
| 里程碑收口 | S21 | 对当前源码只做一次共享 full 聚合；发现问题退回责任阶段，S21 本身不修生产代码 |

阶段之间只能传递已验收的生产契约和结构化证据，不能传递“下一阶段会替本阶段补完”的默认假设。

## 3. 执行模式定义

- `普通聚焦模式`：单独线程只做一张卡，适合边界明确、需要人工审查设计取舍的阶段；达到 `ready_for_review` 立即停止。
- `Goal 模式`：目标只允许设为当前一张卡，适合大量来源扫描、机制族闭合或长时间 property test；仍不得自动进入下一阶段、勾 checklist 或提交 Git。
- `独立 worktree`：并行轨的必选隔离方式，不是一种放宽验收的模式。分支必须记录基线 commit，不能复制未提交工作区。
- `max`：用于跨 runtime、来源图、原子提交、回放或最终集成；`xhigh` 用于数据投影、纯装配和有限共享边界；本目录不推荐 `medium` 执行任何剩余 P8 阶段。

## 4. 每张卡的统一执行协议

1. 核对依赖阶段的已验收 commit、当前工作区和 CodeGraph 索引状态。
2. 只读审查卡内“当前事实”。若实际代码已改变但不影响目标，报告差异后按当前结构实施；若目标、职责边界或验收谓词失效，停止并交回规划线程修订，不能自行改目标。
3. 先建立来源、lowering、admission、runtime、validation 五层缺口矩阵，再编码。检查脚本没选到正例不能直接写成 source gap。
4. 只修改本卡范围。发现相邻阶段问题时记录为依赖或后续项，不提前实现。
5. 必须检查代码结构、通用性、来源真实性、不可变性和失败原子性，不能只跑脚本。
6. 先把可在生产边界判定的非法状态固化为模型、装配器或原子提交不变量，再用少量正负例证明；不得把本可直接拒绝的错误留给大型验证扫描发现。
7. 开发期间只运行秒级失败切片。实现稳定后运行一次阶段主验证，再按实际 diff 选择直接回归；不得把前序阶段脚本清单当作固定套餐。
8. 验证失败时一次性汇总当前可见问题；修复期间只跑失败切片。完整主验证最多一次诊断运行和一次最终运行。
9. 提交 `ready_for_review` 报告，列出实际 diff、每个谓词的证据路径、未运行验证及剩余风险；执行线程不得修改卡内勾选项。
10. 验收线程独立复核代码和证据，只有通过后才更新本卡和总计划 checklist，并提交阶段检查点。

## 5. 共用状态口径

- `executable`：真实来源已投影，装配已准入，runtime、settlement、source audit、snapshot/replay 均按阶段要求闭合。
- `non_gameplay`：有结构化证据证明只属于展示、动画或养成，不参与战斗。
- `source_gap_blocked`：raw 确实缺来源；必须同时排除 lowering、admission 和验证谓词错误。
- `lowering_gap`、`admission_gap`、`implementation_missing`、`validation_gap`：均是当前阶段应关闭的真实缺口，不能改名为 deferred 后打勾。
- 被当前已发布装备选中的 gameplay 图只支持一部分时，整个正式构筑 battle admission 必须 blocked；不能部分执行。

## 6. 共用资源边界

### 6.1 验证顺序

验证顺序固定为：

```text
生产不变量 -> 秒级失败切片 -> 阶段主验证 -> 按实际触达选择 direct
             -> 仅在本阶段职责要求时运行 catalog/full
```

- 已验收检查点证明未改调用链的历史契约，不因新阶段开始而自动重跑。
- 每阶段只有一个主验证入口。主验证必须直接消费生产 API，不得复制 lowering、装配、动作、伤害或 replay 逻辑。
- `direct` 只由实际修改符号触发，默认最多两个。需要第三个时先证明主验证不能覆盖该调用链，并在报告解释。
- `catalog` 只用于来源、目录、lowering 或目录准入变化；`full` 只允许 S21 或用户明确要求。
- 主验证首次失败后，中间修复只运行具体失败 family、矩阵行或小型契约；禁止反复运行完整入口观察下一个错误。
- 验证器自身错误不得通过放宽生产契约解决。修正验证器后只允许一次替代最终运行，并记录前次失败为何不属于业务失败。

### 6.2 运行预算

所有命令默认从 `hsr_v075_baseline_clean/hsr` 运行，产物写入 `/tmp`。重验证使用
`ionice -c3 nice -n 15` 严格串行；禁止与 `compileall` 或其他验证并发。

每张卡的主验证命令必须同时使用：

```text
/usr/bin/time -v -o /tmp/<stage>_time_v.txt timeout --signal=TERM <单次上限> ...
```

`timeout` 返回 124、time 记录缺失或主验证被外部终止都视为本轮失败，残留产物不得作为 evidence。不得去掉 wrapper 后重新裸跑。

| 阶段 | 单次主验证上限 | 从首次主验证到 `ready_for_review` 的累计验证预算 | 峰值 RSS | 默认总产物 |
|---|---:|---:|---:|---:|
| S9 | 8 分钟 | 15 分钟 | 1 GiB | 5 MiB |
| S10-S14 | 5 分钟 | 每阶段 10 分钟 | 768 MiB | 3 MiB |
| S15 | 8 分钟 | 15 分钟 | 1 GiB | 5 MiB |
| S16-S17 | 12 分钟 | 每阶段 25 分钟 | 1 GiB | 10 MiB |
| S18-S20 | 10 分钟 | 每阶段 20 分钟 | 1 GiB | 10 MiB |
| S21 | 30 分钟 | 45 分钟 | 1.5 GiB | 20 MiB |

- 预算包含主验证、失败切片和 direct 的实际墙钟，不包含编码时间。
- 表中数值是止损上限，不是允许用满的目标；主验证正常设计目标应低于单次上限的一半。
- 诊断运行达到单次上限的 80%，即使业务通过，也必须先缩窄来源投影、case 或 evidence，再允许最终运行；不能原样再跑一次。
- 达到任一上限立即停止，不提高限制、不并发补跑、不删除验收谓词；提交资源证据给规划线程重新拆分。
- 完整主验证最多两次：一次诊断、一次最终。catalog/full 在最终源码上最多一次。
- 默认不写完整 Canonical IR、RuleBook、raw ability、全 transition 或全组合；只写 summary、矩阵、最小失败样本和少量来源/transition。
- summary 必须记录构建入口计数、读取文件/字节、case 数、墙钟、峰值 RSS 和各产物大小。无法采集的指标明确写 `not_measured`，不得估算。
- ready-for-review 报告同时记录完整主验证次数、失败切片次数、实际 direct 清单，以及生产代码与验证代码的非空行增减；不能只报最终一次绿色耗时。
- S9-S15 的新增阶段验证代码目标不超过 800 行非空 Python，S16-S21 目标不超过 1000 行；超过目标或验证代码量超过生产改动量时，必须先暂停做结构审查。
- 1200 行是未经新执行卡批准不得越过的硬上限，不是默认配额；不得靠压缩可读性、生成代码或把同一逻辑搬到 helper 规避。

### 6.3 阶段证明对象

| 阶段 | 主验证唯一证明对象 | 禁止自动追加 |
|---|---|---|
| S9 | 当前遗器定义目录与来源闭合 | S0/S1 全阶段重跑、完整战斗 RuleBook |
| S10-S12 | 实例与词条生产不变量、精确 oracle | 前序阶段完整验证器、全组合枚举 |
| S13-S14 | 套装计数和统一静态账本 | 全词条 property test、战斗 runtime |
| S15 | 套装动态图绑定与启动入口 | 全套装 transition、固定 P7 套餐 |
| S16-S17 | 当前 family 分区及本阶段 family 执行 | 九族/未过滤旧聚合、全部 P2/P5/P7 脚本 |
| S18 | 唯一最终装配与出生顺序 | 重跑 S8/S17 聚合 |
| S19 | 查询、审计、snapshot/replay 契约 | 完整目录 dump、固定 P7 套餐 |
| S20 | 一条正式构筑纵切及受控反例 | 重跑 S18/S19 主验证 |
| S21 | 当前源码一次性里程碑聚合 | 逐阶段重新完整构建、边聚合边修生产 |

## 7. 执行卡

| 阶段 | 执行卡 | 推荐执行配置 |
|---|---|---|
| S5 | `P8-S5_LIGHT_CONE_STATIC_CONTRIBUTIONS.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S6 | `P8-S6_LIGHT_CONE_DYNAMIC_STARTUP.md` | 5.6 Sol / max / 普通聚焦 |
| S7 | `P8-S7_LIGHT_CONE_STATUS_CONDITION_LISTENER_CLOSURE.md` | 5.6 Sol / max / Goal |
| S8 | `P8-S8_LIGHT_CONE_REMAINING_GAMEPLAY_CLOSURE.md` | 5.6 Sol / max / Goal |
| R1 | `P8-R1_SUMMON_RUNTIME_HALO_LIFECYCLE_REPAIR.md` | 5.6 Sol / max / 普通聚焦 |
| R2 | `P8-R2_MEMORY_LIGHT_CONE_FORMAL_EVENT_CHAIN_CLOSURE.md` + `P8-R2_REVIEW_DELTA_AFTER_UNFILTERED_FAILURES.md` | 5.6 Sol / max / 普通聚焦 |
| S9 | `P8-S9_RELIC_DEFINITION_CARDS.md` | 5.6 Terra / xhigh / Goal |
| S10 | `P8-S10_RELIC_INSTANCE_LEGALITY.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S11 | `P8-S11_RELIC_MAIN_AFFIX.md` | 5.6 Terra / xhigh / Goal |
| S12 | `P8-S12_RELIC_SUB_AFFIX_ROLLS.md` | 5.6 Sol / max / Goal |
| S13 | `P8-S13_RELIC_SET_THRESHOLDS.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S14 | `P8-S14_RELIC_STATIC_CONTRIBUTIONS.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S15 | `P8-S15_RELIC_SET_DYNAMIC_STARTUP.md` | 5.6 Sol / max / 普通聚焦 |
| S16 | `P8-S16_RELIC_SET_STATUS_CONDITION_LISTENER_CLOSURE.md` | 5.6 Sol / max / Goal |
| S17 | `P8-S17_RELIC_SET_REMAINING_GAMEPLAY_CLOSURE.md` | 5.6 Sol / max / Goal |
| S18 | `P8-S18_FINAL_PANEL_AND_BIRTH_ORDER.md` | 5.6 Sol / max / 普通聚焦 |
| S19 | `P8-S19_QUERY_AUDIT_SNAPSHOT_REPLAY.md` | 5.6 Sol / max / 普通聚焦 |
| S20 | `P8-S20_SEELE_COMPLETE_BUILD_SLICE.md` | 5.6 Sol / max / 普通聚焦 |
| S21 | `P8-S21_CURRENT_SOURCE_AGGREGATE.md` | 5.6 Sol / max / Goal |
